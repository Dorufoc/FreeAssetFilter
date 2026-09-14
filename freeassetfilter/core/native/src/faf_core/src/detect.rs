//! `detect.rs` —— 文本编码探测 FFI（todo 22：`faf_detect_encoding`）。
//!
//! 语义 oracle：`freeassetfilter/services/file_info_service.py`
//! （`_text_light_rows` L648-659 / `_collect_text_detail` L865-900 / todo 25
//! 收敛的三处调用点统一采样窗口 1KB/4KB/全文件）。
//!
//! 设计契约（C6 / todo 22 明文）：
//! - **只吃入参字节**：`faf_detect_encoding` 不读文件、不碰磁盘，输入为调用方
//!   提供的原始字节样本（Python 侧持文件读取）。
//! - **chardetng 探测器**：`EncodingDetector::new()` + `feed(bytes, true)` +
//!   `guess_assess(None, true)`（`allow_utf8=true` 即计划所称「allowlist」；
//!   `None` TLD = 通用域名）。与调用点相同的采样窗口语义由 Python 侧保证。
//! - **置信度闸门（<0.5 → 空 JSON `{}`，Python 走 `utf-8 → latin-1` 链）**：
//!   chardetng 0.1.17 **不暴露数值置信度**（已核实 public API 仅
//!   `feed`/`guess`/`guess_assess`；`find_score` 为 test-only feature 门控）。
//!   故置信度按确定性启发式计算并落档：以「非 ASCII 字节信号量」为指标
//!   `score = 1 - 1/(1 + n/K)`（K=500，n=非 ASCII 字节数，封顶 0.99）；
//!   `guess_assess` 的布尔判定作为附加否决信号（chardetng 官方文档：返回
//!   false 表示「猜测可能错误」）。纯 ASCII 恒为高置信（UTF-8 合法解码）。
//!   校准锚点：CJK 长样本（≥8KB，非 ASCII 数千字节）→ ≥0.9；1KB 采样窗口
//!   （n≈900）→ ~0.65；latin-1 样本（n≈385）→ 0.435 < 0.5 → `{}`
//!   （与 Python chardet 对同一样本给出 confidence 0.02 的判定一致）；
//!   短样本（n < ~250）→ <0.5 → `{}`（计划明文：短样本 gbk/big5/shift-jis
//!   歧义高）。
//! - **空样本**：`len == 0` 无法有意义探测，返回 null（QA「空样本 → 错误状态」）；
//!   `null/负 len` 经 [`crate::guard_byte_slice`] 返回 null。
//! - **不 panic**：裸指针入参守卫先于 slice 构造；导出 `catch_to_ptr` 兜底。
//!
//! 返回指针由 Rust 分配，调用方必须先拷贝内容再经 [`crate::faf_free_message`] 释放。

use std::ffi::c_char;
use std::os::raw::c_int;

use chardetng::EncodingDetector;

use crate::{alloc_json_message, catch_to_ptr, guard_byte_slice};

/// 置信度闸门：低于该值返回空 JSON `{}`（Python 走回退链）。
const CONFIDENCE_THRESHOLD: f64 = 0.5;
/// 置信度封顶（chardetng 无数值置信度 API，报告值 ≤ 此上界）。
const CONFIDENCE_MAX: f64 = 0.99;
/// 非 ASCII 信号量饱和常数（score = 1 - 1/(1 + n/K)；n=非 ASCII 字节数）。
const NON_ASCII_SATURATION: f64 = 500.0;

/// 确定性置信度启发式（见模块文档「置信度闸门」）。
///
/// - `assessed == false`（chardetng「猜测可能错误」）→ 0.0；
/// - 纯 ASCII → [`CONFIDENCE_MAX`]（UTF-8 合法解码，任何编码结果等价）；
/// - 否则按非 ASCII 信号量 `score = 1 - 1/(1 + n/K)` 封顶到
///   [`CONFIDENCE_MAX`]。
fn detection_confidence(sample: &[u8], assessed: bool) -> f64 {
    if !assessed {
        return 0.0;
    }
    let non_ascii = sample.iter().filter(|&&b| b >= 0x80).count();
    if non_ascii == 0 {
        return CONFIDENCE_MAX;
    }
    let score = 1.0 - 1.0 / (1.0 + non_ascii as f64 / NON_ASCII_SATURATION);
    score.min(CONFIDENCE_MAX)
}

/// 探测编码（todo 22：`faf_detect_encoding`）。
///
/// 输入为调用方提供的原始字节样本 `(sample_ptr, len)`：
///
/// - 成功：JSON `{"encoding":"gbk","confidence":0.98}`（`encoding` 为
///   encoding_rs 名称的 **小写** 形式，Python `bytes.decode` 可直用；
///   `confidence >= 0.5`）；
/// - **置信度 < 0.5 / 未知编码**：返回空 JSON `{}`（非 null——调用方以此走
///   `utf-8 → latin-1` 回退链，见 C6）；
/// - `null` 指针 / 负 `len` / 空样本（`len == 0`）：返回 null，不 panic；
/// - 内部 panic：`catch_to_ptr` 兜底返回 null。
///
/// `#[allow(clippy::not_unsafe_ptr_arg_deref)]`：FFI 边界保持 `safe extern "C"`
///（与 crate 其余导出契约一致）；裸指针经 [`crate::guard_byte_slice`] 守卫后
/// 构造 slice，故不标记 `unsafe`。
#[allow(clippy::not_unsafe_ptr_arg_deref)]
#[no_mangle]
pub extern "C" fn faf_detect_encoding(sample_ptr: *const u8, len: c_int) -> *mut c_char {
    catch_to_ptr(|| {
        // null/负 len 守卫先于 slice 构造（复用 lib.rs helper）。
        // SAFETY：guard_byte_slice 内部已做 null/负 len 守卫；内存有效性由
        // ctypes `c_char_p` / `c_void_p` 入参契约保证。
        let Ok(sample) = (unsafe { guard_byte_slice(sample_ptr, len) }) else {
            return std::ptr::null_mut();
        };
        // 空样本无法有意义探测（QA「空样本 → 错误状态」）。
        if sample.is_empty() {
            return std::ptr::null_mut();
        }
        let mut detector = EncodingDetector::new();
        detector.feed(sample, true);
        // guess(None, true)：`allow_utf8=true` 允许 UTF-8 候选（计划「allowlist」）。
        let (encoding, assessed) = detector.guess_assess(None, true);
        let confidence = detection_confidence(sample, assessed);
        if confidence < CONFIDENCE_THRESHOLD {
            // 置信度不足：空 JSON，Python 走 `utf-8 → latin-1` 链。
            return alloc_json_message("{}");
        }
        let payload = serde_json::json!({
            "encoding": encoding.name().to_ascii_lowercase(),
            "confidence": confidence,
        })
        .to_string();
        alloc_json_message(&payload)
    })
}

// ---------------------------------------------------------------------------
// 单测（todo 22 必写：编码夹具探测、置信度阈值路径、null/负 len/空样本守卫）
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::CStr;

    /// 编码夹具（todo 5 生成，CJK 样本 ≥8KB）。include_bytes! 编译期内嵌，
    /// 与 highlight.rs 的 include_str! 夹具约定一致。
    const GBK_1: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/gbk_01.txt");
    const GBK_2: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/gbk_02.txt");
    const GBK_3: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/gbk_03.txt");
    const GBK_4: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/gbk_04.txt");
    const GBK_5: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/gbk_05.txt");
    const SJIS_1: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/shiftjis_01.txt");
    const SJIS_2: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/shiftjis_02.txt");
    const SJIS_3: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/shiftjis_03.txt");
    const SJIS_4: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/shiftjis_04.txt");
    const SJIS_5: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/shiftjis_05.txt");
    const BIG5_1: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/big5_01.txt");
    const BIG5_2: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/big5_02.txt");
    const UTF8_1: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/utf8_01.txt");
    const UTF8_2: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/utf8_02.txt");
    const UTF8_3: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/utf8_03.txt");
    const UTF8_4: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/utf8_04.txt");
    const UTF8_5: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/utf8_05.txt");
    const UTF8BOM_1: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/utf8bom_01.txt");
    const UTF8BOM_2: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/utf8bom_02.txt");
    const LATIN1_1: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/encoding_samples/latin1_01.txt");

    /// 读取 FFI 返回的 JSON 并释放（模拟 Python `string_at` + `free`）。
    /// 允许 null 返回（返回 `None`）。
    fn read_json(raw: *mut c_char) -> Option<serde_json::Value> {
        if raw.is_null() {
            return None;
        }
        // SAFETY：raw 为 faf_detect_encoding 刚分配的 NUL 终止串。
        let text = unsafe { CStr::from_ptr(raw) }
            .to_str()
            .expect("输出应为合法 UTF-8");
        let parsed: serde_json::Value =
            serde_json::from_str(text).expect("输出应可解析为 JSON");
        crate::faf_free_message(raw);
        Some(parsed)
    }

    /// 便捷封装：探测字节样本，返回解析后的 JSON（null 时为 None）。
    fn detect(data: &[u8]) -> Option<serde_json::Value> {
        read_json(faf_detect_encoding(data.as_ptr(), data.len() as c_int))
    }

    /// gbk 样本（≥8KB CJK）探测为 `gbk` 且置信度 ≥ 0.5。
    #[test]
    fn gbk_samples_detect_gbk() {
        for (i, sample) in [GBK_1, GBK_2, GBK_3, GBK_4, GBK_5].iter().enumerate() {
            let out = detect(sample).expect("gbk 样本应返回 JSON");
            assert_eq!(out["encoding"], "gbk", "gbk_{} 应为 gbk", i + 1);
            assert!(
                out["confidence"].as_f64().unwrap() >= CONFIDENCE_THRESHOLD,
                "gbk_{} 置信度应 >= 0.5",
                i + 1
            );
        }
    }

    /// shift-jis 样本（≥8KB CJK）探测为 `shift_jis` 且置信度 ≥ 0.5。
    #[test]
    fn shiftjis_samples_detect_shift_jis() {
        for (i, sample) in [SJIS_1, SJIS_2, SJIS_3, SJIS_4, SJIS_5].iter().enumerate() {
            let out = detect(sample).expect("shift-jis 样本应返回 JSON");
            assert_eq!(out["encoding"], "shift_jis", "shiftjis_{} 应为 shift_jis", i + 1);
            assert!(
                out["confidence"].as_f64().unwrap() >= CONFIDENCE_THRESHOLD,
                "shiftjis_{} 置信度应 >= 0.5",
                i + 1
            );
        }
    }

    /// big5 样本探测为 `big5`。
    #[test]
    fn big5_samples_detect_big5() {
        for (i, sample) in [BIG5_1, BIG5_2].iter().enumerate() {
            let out = detect(sample).expect("big5 样本应返回 JSON");
            assert_eq!(out["encoding"], "big5", "big5_{} 应为 big5", i + 1);
        }
    }

    /// utf-8 / utf-8-bom 样本探测为 `utf-8`（BOM 由 chardetng 识别）。
    #[test]
    fn utf8_and_bom_samples_detect_utf8() {
        for (i, sample) in [UTF8_1, UTF8_2, UTF8_3, UTF8_4, UTF8_5].iter().enumerate() {
            let out = detect(sample).expect("utf-8 样本应返回 JSON");
            assert_eq!(out["encoding"], "utf-8", "utf8_{} 应为 utf-8", i + 1);
            assert!(
                out["confidence"].as_f64().unwrap() >= CONFIDENCE_THRESHOLD,
                "utf8_{} 置信度应 >= 0.5",
                i + 1
            );
        }
        for (i, sample) in [UTF8BOM_1, UTF8BOM_2].iter().enumerate() {
            let out = detect(sample).expect("utf-8-bom 样本应返回 JSON");
            assert_eq!(out["encoding"], "utf-8", "utf8bom_{} 应为 utf-8", i + 1);
            assert!(
                out["confidence"].as_f64().unwrap() >= CONFIDENCE_THRESHOLD,
                "utf8bom_{} 置信度应 >= 0.5",
                i + 1
            );
        }
    }

    /// latin-1 样本：非 ASCII 信号量不足（n≈385）→ 置信度 <0.5 → 空 JSON `{}`。
    /// 与 Python chardet 对同一样本给出 confidence=0.02 的判定一致；Python
    /// 链经 `utf-8 → latin-1` 正确解码（latin-1 逐字节直译）。
    #[test]
    fn latin1_sample_low_confidence_returns_empty_json() {
        let out = detect(LATIN1_1).expect("latin-1 样本应返回可解析 JSON");
        assert_eq!(
            out.as_object().map(|m| m.len()).unwrap_or(0),
            0,
            "latin-1 样本置信度应 <0.5 → 空 JSON {{}}"
        );
    }

    /// 采样窗口语义：shift-jis 的 1KB/4KB 前缀窗口（非 ASCII n≈700+）仍
    /// 探测正确（与 Python `_text_light_rows` / `_collect_text_detail` 的
    /// 1KB/4KB 采样一致，chardet 对同窗口给出 cp932）。
    ///
    /// 注：gbk_01 的 1KB/4KB 前缀窗口 chardetng 判为 windows-1252
    /// （chardet 判 koi8-u 且 confidence 0.037）——两者均为歧义误判，属
    /// todo 25 对拍的 accepted-diffs 范畴，非本 todo 缺陷。
    #[test]
    fn sjis_prefix_window_still_detects() {
        for &win in &[1024usize, 4096] {
            let s = detect(&SJIS_1[..win]).expect("shift-jis 前缀窗口应返回 JSON");
            assert_eq!(s["encoding"], "shift_jis", "shift-jis 前 {win}B 窗口应为 shift_jis");
            assert!(
                s["confidence"].as_f64().unwrap() >= CONFIDENCE_THRESHOLD,
                "shift-jis 前 {win}B 置信度应 >= 0.5"
            );
        }
    }

    /// 置信度阈值路径：短乱码样本（非 ASCII 信号量不足）→ 空 JSON `{}`
    ///（置信度 <0.5），非 null、可解析。
    #[test]
    fn low_confidence_sample_returns_empty_json() {
        // 32 字节高位乱码：n=32 → score≈0.06 <0.5。
        let garbage: Vec<u8> = (0..32u8).map(|i| 0x80 + i % 0x70).collect();
        let out = detect(&garbage).expect("低置信样本应返回可解析 JSON（{}）");
        assert_eq!(
            out.as_object().map(|m| m.len()).unwrap_or(0),
            0,
            "应返回空 JSON {{}}"
        );
    }

    /// null 指针 / 负 len → null，不 panic。
    ///（`faf_detect_encoding` 为 `safe extern "C"`，null/负 len 入参正是
    /// `guard_byte_slice` 的被测场景——返回 null 且不解引用。）
    #[test]
    fn null_and_negative_len_return_null() {
        assert!(
            faf_detect_encoding(std::ptr::null(), 10).is_null(),
            "null 指针应返回 null"
        );
        assert!(
            faf_detect_encoding(std::ptr::null(), 0).is_null(),
            "null 指针 + len 0 应返回 null"
        );
        let dummy = [0u8; 4];
        assert!(
            faf_detect_encoding(dummy.as_ptr(), -1).is_null(),
            "负 len 应返回 null"
        );
    }

    /// 空样本（len == 0，非空指针）→ null（QA「空样本 → 错误状态」）。
    #[test]
    fn empty_sample_returns_null() {
        let dummy = [0u8; 1];
        assert!(
            faf_detect_encoding(dummy.as_ptr(), 0).is_null(),
            "空样本应返回 null"
        );
    }

    /// 纯 ASCII 输入：合法 UTF-8 → `utf-8` 置信度封顶（chardetng 视 ASCII 为
    /// UTF-8 候选，`allow_utf8=true` 直接命中）。
    #[test]
    fn pure_ascii_detects_utf8() {
        let out =
            detect(b"The quick brown fox jumps over the lazy dog").expect("ASCII 应返回 JSON");
        assert_eq!(out["encoding"], "utf-8");
        assert_eq!(out["confidence"], CONFIDENCE_MAX);
    }

    /// 置信度启发式锚点：非 ASCII 信号量映射确定性（单测隔离公式本身）。
    #[test]
    fn confidence_heuristic_anchors() {
        // assessed=false → 0（chardetng 否决信号）。
        assert_eq!(detection_confidence(&[0xE4, 0x94], false), 0.0);
        // 纯 ASCII → 封顶。
        assert_eq!(detection_confidence(b"hello", true), CONFIDENCE_MAX);
        // 短信号 → 低于阈值。
        assert!(detection_confidence(&[0xE4u8; 16], true) < CONFIDENCE_THRESHOLD);
        // 长 CJK 信号 → 高置信。
        let big = vec![0xE4u8; 8192];
        assert!(detection_confidence(&big, true) >= 0.9);
    }

    // ---- todo 23 补全：空样本 / 纯 ASCII / 长文本边界 ----

    /// `{}` 字面量（占位符文本，计划「空样本 `{}`」的 ASCII 形态）→
    /// 合法 UTF-8 → `utf-8` 置信度封顶。
    #[test]
    fn braces_placeholder_detects_utf8() {
        let out = detect(b"{}").expect("'{{}}' 为合法 ASCII 应返回 JSON");
        assert_eq!(out["encoding"], "utf-8");
        assert_eq!(out["confidence"], CONFIDENCE_MAX);
    }

    /// 长纯 ASCII 文本（64KiB）边界：仍判 `utf-8`、置信度封顶
    ///（chardetng 对 ASCII 恒为 UTF-8 候选，`allow_utf8=true`）。
    #[test]
    fn long_pure_ascii_detects_utf8() {
        let long_ascii: Vec<u8> = b"the quick brown fox jumps over the lazy dog. "
            .iter()
            .cycle()
            .take(64 * 1024)
            .copied()
            .collect();
        let out = detect(&long_ascii).expect("长 ASCII 应返回 JSON");
        assert_eq!(out["encoding"], "utf-8");
        assert_eq!(out["confidence"], CONFIDENCE_MAX);
    }

    /// 长 UTF-8 中文文本（≥64KiB，远超采样窗口上限）边界：`utf-8` 高置信。
    ///
    /// 构造注意：样本必须**整体合法 UTF-8**——chardetng 在 `allow_utf8=true`
    /// 时对任何合法 UTF-8 输入直接判 `utf-8`（lib.rs `guess_assess` 的
    /// `candidates[UTF_8_INDEX].score.is_some()` 短路）；若用 `take()` 在
    /// 多字节字符中途截断，样本尾块变非法 UTF-8，scorer 会跌落到
    /// windows-1252 等（实测复现）。故按**完整句子轮次**拼接，每轮长度
    /// 固定、末尾必落在合法边界。内容用多句互不相同的中文，贴近真实长文本。
    #[test]
    fn long_utf8_cjk_text_high_confidence() {
        let sentences = [
            "春风又绿江南岸，明月何时照我还。\n",
            "千山鸟飞绝，万径人踪灭。孤舟蓑笠翁，独钓寒江雪。\n",
            "床前明月光，疑是地上霜。举头望明月，低头思故乡。\n",
            "白日依山尽，黄河入海流。欲穷千里目，更上一层楼。\n",
            "葡萄美酒夜光杯，欲饮琵琶马上催。醉卧沙场君莫笑，古来征战几人回。\n",
            "大江东去，浪淘尽，千古风流人物。故垒西边，人道是，三国周郎赤壁。\n",
        ];
        let mut long: Vec<u8> = Vec::new();
        while long.len() < 64 * 1024 {
            for s in &sentences {
                long.extend_from_slice(s.as_bytes());
            }
        }
        let out = detect(&long).expect("长中文样本应返回 JSON");
        assert_eq!(out["encoding"], "utf-8", "长中文样本应为 utf-8");
        assert!(
            out["confidence"].as_f64().unwrap() >= CONFIDENCE_THRESHOLD,
            "长中文样本置信度应 >= 0.5"
        );
    }

    /// 超短 CJK 样本（单个汉字 3 字节）边界：非 ASCII 信号量不足
    ///（n=3 → score≈0.006 <0.5）→ 空 JSON `{}`（非 null、可解析，
    /// Python 走 `utf-8 → latin-1` 回退链）。
    #[test]
    fn short_cjk_sample_low_confidence_empty_json() {
        let out = detect("中".as_bytes()).expect("3 字节 CJK 应返回可解析 JSON（{}）");
        assert_eq!(
            out.as_object().map(|m| m.len()).unwrap_or(0),
            0,
            "3 字节 CJK 置信度应 <0.5 → 空 JSON {{}}"
        );
    }
}
