//! T3 智能识别跳过（todo 25 实现）。
//!
//! 职责：T3 通则——`STATUS_UNSUPPORTED`（RAW 系 cr2/cr3/nef/arw/dng/orf/raf/
//! rw2/pef/x3f、psb、xcf、svg、jxr、icns-jp2、dds-bc7 未实现等）与
//! `STATUS_TOO_LARGE`（解码尺寸/内存超限）及一切解码失败统一入 errorlog
//! （path/format/status/message/timestamp）并快速返回；各失败路径不 panic
//! 而返回结构化状态。
//!
//! 接线位置（lib.rs）：`generate_entry` 在解码分发前做扩展名路由（命中
//! [`T3_SKIP_EXTS`] 即 [`skip_with_status`] 快速返回），其解码失败臂与
//! `generate_jpeg_bytes` 的视频抽帧分支经 [`record_decode_failure`] 补录。

use std::path::Path;

use crate::{STATUS_DECODE_FAILED, STATUS_TOO_LARGE, STATUS_UNSUPPORTED};

/// T3 扩展名跳过清单（小写、不含点号；对照 `is_video_ext` 的扩展名路由风格）。
///
/// 扩展名路由**先于魔数嗅探**：CR2/NEF/ARW/DNG/RAF/RW2/PEF/ORF 多为 TIFF
/// 魔数，若放行走魔数嗅探会被误判为 TIFF 进入 TIFF 解码器；psb/xcf/svg/jxr
/// 无原生解码器，统一快速返回 `-6` 交下游 Python 回退链。dds-bc7 与 icns-jp2
/// 的 -6 已在各自解码器内部返回（todo 21/22），不在此重复登记——其入日志由
/// 调用侧 [`record_decode_failure`] 统一承担。
pub(crate) const T3_SKIP_EXTS: &[&str] = &[
    // RAW 系（多为 TIFF 魔数，必须先于魔数嗅探拦截）
    "cr2", "cr3", "nef", "arw", "dng", "orf", "raf", "rw2", "pef", "x3f",
    // 无原生解码器的专业格式
    "psb", "xcf", "svg", "jxr",
];

/// T3 跳过写入 errorlog 的简短原因（message 字段）。
pub(crate) const T3_SKIP_MESSAGE: &str = "T3 unsupported format";

/// 解码失败路径补录 errorlog 的默认消息（message 字段）。
const DECODE_FAILURE_MESSAGE: &str = "decode failed";

/// 提取路径的小写扩展名作为格式标识（不含点号；无扩展名返回空串）。
///
/// errorlog 的 format 字段契约是小写扩展名或魔数格式名；T3 跳过与失败补录
/// 场景统一取扩展名（如 `"cr2"`），大写扩展名在此归一化。
pub(crate) fn path_format(path: &str) -> String {
    Path::new(path)
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase()
}

/// 路径扩展名是否命中 T3 跳过清单（小写化比较，`.CR2` 与 `.cr2` 等价）。
pub(crate) fn is_t3_skip_path(path: &str) -> bool {
    let ext = path_format(path);
    !ext.is_empty() && T3_SKIP_EXTS.contains(&ext.as_str())
}

/// T3 通则：写入一条 errorlog 记录（path/format/status/message/timestamp）
/// 并**原样返回 status**——调用方据此快速返回，不尝试解码。写入失败
/// （锁中毒返回 false）不影响返回值语义：状态码是上层路由依据，日志只是
/// 观测通道。
pub(crate) fn skip_with_status(path: &str, format: &str, status: i32, message: &str) -> i32 {
    crate::infra::errorlog::push_error(path, format, status, message);
    status
}

/// 解码失败路径的统一补录：仅结构化解码状态码记入 errorlog——
/// `-2` [`STATUS_DECODE_FAILED`] / `-6` [`STATUS_UNSUPPORTED`] /
/// `-7` [`STATUS_TOO_LARGE`]；其余（-1 参数 / -3 内存压力 / -4 不存在 /
/// -5 内部）属参数与路由层语义，原样放行不记录。format 取路径小写扩展名。
///
/// dds-bc7 / icns-jp2 等解码器内部返回的 -6（todo 21/22）在接入生成流程后
/// 同样经本函数进入日志，无需在各解码器内重复实现记录逻辑。
pub(crate) fn record_decode_failure(path: &str, status: i32) {
    if matches!(
        status,
        STATUS_DECODE_FAILED | STATUS_UNSUPPORTED | STATUS_TOO_LARGE
    ) {
        crate::infra::errorlog::push_error(
            path,
            &path_format(path),
            status,
            DECODE_FAILURE_MESSAGE,
        );
    }
}

#[cfg(test)]
mod tests {
    use super::{
        is_t3_skip_path, path_format, record_decode_failure, skip_with_status,
        DECODE_FAILURE_MESSAGE, T3_SKIP_EXTS, T3_SKIP_MESSAGE,
    };
    use crate::infra::errorlog::{self, MAX_ERROR_LOG_ENTRIES, TEST_GLOBAL_LOCK};
    use crate::{STATUS_DECODE_FAILED, STATUS_TOO_LARGE, STATUS_UNSUPPORTED};
    use std::path::PathBuf;

    /// 写临时夹具文件（名称带进程号 + 用例语义防并行碰撞），返回绝对路径。
    fn temp_file(name: &str, bytes: &[u8]) -> PathBuf {
        let mut p = std::env::temp_dir();
        p.push(format!("faf_t3_{}_{name}", std::process::id()));
        std::fs::write(&p, bytes).expect("写临时夹具应成功");
        p
    }

    /// 当前全局错误日志条数（环形上限内全量读取）。
    fn global_log_len() -> usize {
        errorlog::recent_error_log(MAX_ERROR_LOG_ENTRIES).len()
    }

    /// 全部 14 个 T3 扩展名（RAW 系全 10 项 + psb/xcf/svg/jxr）：
    /// 经 generate_entry 断言返回 -6、errorlog 恰 +1 且各字段正确；
    /// 另验大写扩展名（.CR2）与小写等价路由且 format 归一化为小写。
    #[test]
    fn every_t3_extension_skips_with_unsupported_and_logs() {
        let _guard = TEST_GLOBAL_LOCK.lock().unwrap();
        assert!(errorlog::clear_error_log());

        for (i, ext) in T3_SKIP_EXTS.iter().enumerate() {
            let path = temp_file(&format!("sample{i}.{ext}"), b"not-a-real-codec-payload");
            let before = global_log_len();

            let code = match crate::generate_entry(path.to_str().unwrap(), 64, 64) {
                Err(code) => code,
                Ok(_) => panic!("扩展名 {ext} 命中 T3 清单必须跳过而非解码成功"),
            };
            assert_eq!(code, STATUS_UNSUPPORTED, "扩展名 {ext} 应返回 -6");
            assert_eq!(global_log_len(), before + 1, "扩展名 {ext} 应新增一条 errorlog");

            let last = errorlog::recent_error_log(1);
            assert_eq!(last.len(), 1);
            assert_eq!(last[0].status, STATUS_UNSUPPORTED);
            assert_eq!(last[0].format, *ext, "format 应记小写扩展名");
            assert_eq!(last[0].message, T3_SKIP_MESSAGE);
            assert_eq!(last[0].path, path.to_str().unwrap());
            assert!(last[0].timestamp > 0, "timestamp 应为 Unix 毫秒");
        }

        // 大写扩展名等价：.CR2 与 .cr2 同路由，且 format 归一化为小写。
        let upper = temp_file("UPPERCASE.CR2", b"x");
        let before = global_log_len();
        let code = match crate::generate_entry(upper.to_str().unwrap(), 64, 64) {
            Err(code) => code,
            Ok(_) => panic!(".CR2 大写扩展名应命中清单"),
        };
        assert_eq!(code, STATUS_UNSUPPORTED);
        assert_eq!(global_log_len(), before + 1);
        let last = errorlog::recent_error_log(1);
        assert_eq!(last[0].format, "cr2");
    }

    /// 坏输入返回结构化错误码且不崩溃：伪扩展名 .txt / 零字节 / 截断 PNG，
    /// 三者均以 -2 解码失败透传并经 record_decode_failure 各补录一条 errorlog。
    #[test]
    fn bad_inputs_return_error_codes_without_panic() {
        let _guard = TEST_GLOBAL_LOCK.lock().unwrap();
        assert!(errorlog::clear_error_log());

        // 伪扩展名 .txt：不在 T3 清单，内容无有效魔数 → image crate 判定 -2。
        let txt = temp_file("garbage.txt", b"this is definitely not an image payload");
        let before = global_log_len();
        let code = match crate::generate_entry(txt.to_str().unwrap(), 64, 64) {
            Err(code) => code,
            Ok(_) => panic!(".txt 垃圾内容不应解码成功"),
        };
        assert_eq!(code, STATUS_DECODE_FAILED);
        assert_eq!(global_log_len(), before + 1, ".txt 失败应补录一条 errorlog");

        // 零字节文件：任何解码器都无法处理 → -2。
        let empty = temp_file("empty.png", b"");
        let before = global_log_len();
        let code = match crate::generate_entry(empty.to_str().unwrap(), 64, 64) {
            Err(code) => code,
            Ok(_) => panic!("零字节文件不应解码成功"),
        };
        assert_eq!(code, STATUS_DECODE_FAILED);
        assert_eq!(global_log_len(), before + 1, "零字节失败应补录一条 errorlog");

        // 截断 PNG（签名 + 半个 IHDR）→ 非零错误码且不 panic。
        let truncated = temp_file("truncated.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHD");
        let before = global_log_len();
        let code = match crate::generate_entry(truncated.to_str().unwrap(), 64, 64) {
            Err(code) => code,
            Ok(_) => panic!("截断 PNG 不应解码成功"),
        };
        assert_ne!(code, 0);
        assert_eq!(global_log_len(), before + 1, "截断失败应补录一条 errorlog");

        // 三条补录的字段形态：-2 + 默认失败消息（format 为各自小写扩展名）。
        let recent = errorlog::recent_error_log(3);
        assert_eq!(recent.len(), 3);
        for entry in &recent {
            assert_eq!(entry.status, STATUS_DECODE_FAILED);
            assert_eq!(entry.message, DECODE_FAILURE_MESSAGE);
        }
    }

    /// 通则函数语义锁定：skip_with_status 对任意状态码原样透传并各记一条；
    /// record_decode_failure 仅对 -2/-6/-7 补录（-3/-5 放行不记录）；
    /// 扩展名谓词大小写等价、非清单扩展名/无扩展名/空串不命中；
    /// errorlog JSON 出口为数组且字段齐备。
    #[test]
    fn skip_passthrough_and_failure_filter_semantics() {
        let _guard = TEST_GLOBAL_LOCK.lock().unwrap();
        assert!(errorlog::clear_error_log());

        // 透传语义：返回值与传入 status 一致，每调用一次恰记一条。
        assert_eq!(
            skip_with_status("a.cr2", "cr2", STATUS_UNSUPPORTED, T3_SKIP_MESSAGE),
            STATUS_UNSUPPORTED
        );
        assert_eq!(
            skip_with_status("b.tif", "tiff", STATUS_TOO_LARGE, "too large"),
            STATUS_TOO_LARGE
        );
        assert_eq!(
            skip_with_status("c.bin", "bin", STATUS_DECODE_FAILED, "boom"),
            STATUS_DECODE_FAILED
        );
        assert_eq!(global_log_len(), 3, "三次透传调用应各记一条");

        // 过滤语义：-2/-6/-7 记录；-3（内存压力交 Python 回退）/ -5（内部）不记录。
        record_decode_failure("d.txt", STATUS_UNSUPPORTED);
        record_decode_failure("e.mp4", STATUS_DECODE_FAILED);
        record_decode_failure("f.qoi", STATUS_TOO_LARGE);
        record_decode_failure("g.bin", -3); // STATUS_OOM（lib.rs 私有常量，字面量同值）
        record_decode_failure("h.bin", -5); // STATUS_INTERNAL（同上）
        assert_eq!(global_log_len(), 6, "仅 -2/-6/-7 应被补录");

        let recent = errorlog::recent_error_log(3);
        let statuses: Vec<i32> = recent.iter().map(|e| e.status).collect();
        assert_eq!(
            statuses,
            vec![STATUS_UNSUPPORTED, STATUS_DECODE_FAILED, STATUS_TOO_LARGE]
        );
        assert_eq!(recent[0].format, "txt");

        // JSON 出口形状：数组 + path/format 字符串字段齐备（serde_json round-trip）。
        let value: serde_json::Value =
            serde_json::from_str(&errorlog::error_log_to_json()).expect("日志 JSON 应可解析");
        let arr = value.as_array().expect("应为 JSON 数组");
        assert_eq!(arr.len(), 6);
        assert!(arr.iter().all(|e| e["path"].is_string() && e["format"].is_string()));

        // 谓词语义：大小写等价、非清单扩展名/无扩展名/空串不命中。
        assert!(is_t3_skip_path(r"D:\pics\IMG_0001.CR2"));
        assert!(is_t3_skip_path("/tmp/render.svg"));
        assert!(!is_t3_skip_path("photo.jpg"));
        assert!(!is_t3_skip_path("archive.txt"));
        assert!(!is_t3_skip_path("noext"));
        assert!(!is_t3_skip_path(""));
        // path_format：小写归一化 + 无扩展名返回空串。
        assert_eq!(path_format("A.B.PNG"), "png");
        assert_eq!(path_format("noext"), "");
        assert_eq!(path_format(""), "");
    }
}