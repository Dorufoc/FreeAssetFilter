//! T2 ffmpeg/ffprobe 能力探测（todo 23 实现）。
//!
//! 启动/按需调用 `ffprobe -version`、`ffmpeg -formats`、`ffmpeg -codecs`
//! 解析能力表：demuxer/muxer（`-formats` 首两列 `D`/`E` 标记 + 尾部
//! `(demuxing)`/`(muxing)` 后缀变体）、编解码器（`-codecs` 6 字符标记位）、
//! 版本号（`-version` 首行）。结果由 `OnceLock` 进程内缓存（仅探测一次），
//! 单命令 5s 超时（复用 lib.rs `run_command_with_timeout`），失败/缺二进制时
//! 返回空能力并通过 `infra::errorlog::push_error` 记录。**不硬编码 AVIF/HEIF
//! 可用性**——能力矩阵由实测决定（todo 24 据此定 T2 图像/视频清单）。
//!
//! 本文件单测全部使用伪造文本夹具（不依赖真实 ffmpeg）；真实探测仅在二进制
//! 存在时跑一次（`real_probe_when_binary_present`），缺失时跳过。
//! SIZE_OK：计划强制内联单测（6 组解析形态 + 超时/缺命令 + 实跑探针）。
use crate::infra::errorlog::push_error;
use crate::{ffmpeg_path, ffprobe_path, run_command_with_timeout};
use std::path::Path;
use std::process::Command;
use std::sync::OnceLock;
use std::time::Duration;

/// 能力探测单命令超时（对齐 lib.rs `available_hwaccels_from_ffmpeg` 的 5s）。
const CAPABILITY_TIMEOUT_SECS: u64 = 5;
/// `STATUS_INTERNAL(-5)` 字面量：lib.rs 常量非 `pub(crate)`，此处按同值引用。
const FFMPEG_CAP_STATUS_INTERNAL: i32 = -5;

/// 实测 ffmpeg/ffprobe 能力表。
#[derive(Debug, Clone, Default)]
pub struct FfmpegCapability {
    /// `ffprobe -version`/`ffmpeg -version` 首行解析出的版本号（失败为空串）。
    pub version: String,
    /// `ffmpeg -formats` 中可 demux 的格式名（多名称条目如
    /// `mov,mp4,m4a,3gp,3g2,mj2` 保持原样，拆分属 todo 24 矩阵职责）。
    pub formats_demuxer: Vec<String>,
    /// `ffmpeg -formats` 中可 mux 的格式名。
    pub formats_muxer: Vec<String>,
    /// `ffmpeg -codecs` 中的编解码器名。
    pub codecs: Vec<String>,
}

/// 能力缓存（进程内只探测一次；探测失败也是空能力，不重试）。
static FFMPEG_CAPABILITY: OnceLock<FfmpegCapability> = OnceLock::new();

/// 访问能力表（惰性探测并缓存）。
pub fn ffmpeg_capability() -> &'static FfmpegCapability {
    FFMPEG_CAPABILITY.get_or_init(probe_capability)
}

/// 序列化为 `{"version","formats","demuxer","muxer","codecs"}` JSON。
/// 失败/缺二进制时各数组为空、version 为空串——结构恒为合法 JSON。
pub fn capabilities_json() -> String {
    build_json(ffmpeg_capability())
}

/// 能力表 JSON 序列化（纯函数：失败也为合法 JSON，供单测直接构造）。
fn build_json(cap: &FfmpegCapability) -> String {
    // `formats` = demuxer ∪ muxer（保持 ffmpeg 输出的顺序稳定；dedup 去重）。
    let mut formats: Vec<String> = cap.formats_demuxer.clone();
    for name in &cap.formats_muxer {
        if !formats.iter().any(|existing| existing == name) {
            formats.push(name.clone());
        }
    }
    serde_json::json!({
        "version": cap.version,
        "formats": formats,
        "demuxer": cap.formats_demuxer,
        "muxer": cap.formats_muxer,
        "codecs": cap.codecs,
    })
    .to_string()
}

/// 名称字段是否像合法的格式/编解码器名（过滤 `=`/`.` 等图例行噪声）。
fn is_valid_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 64
        && name.as_bytes()[0].is_ascii_alphanumeric()
}

/// 从标记位之后的部分提取首个空白分隔 token 作为名称。
fn parse_name(rest: &str) -> Option<&str> {
    let name = rest.trim_start().split_whitespace().next()?;
    is_valid_name(name).then_some(name)
}

/// 按名称去重追加。
fn push_unique(list: &mut Vec<String>, name: &str) {
    if !list.iter().any(|existing| existing == name) {
        list.push(name.to_string());
    }
}

/// 校验 `-formats` 标记 token（首 token），返回 (is_demux, is_mux)。
/// 标记字符集 = {D,E,d,.,空格}（`d`=device 标记，忽略）；出现其他字符视为非能力
/// 行（头部/图例/乱码）。`D`/`E` 在 token 内任意位置均有效——最小构建将标记与
/// 名称直接拼接为首 token（如 `E` 单独成 token），标准构建为 2 字符 `D.`/`.E`/`DE`。
fn format_flags(flags: &str) -> (bool, bool) {
    let mut is_demux = false;
    let mut is_mux = false;
    for b in flags.as_bytes() {
        match b {
            b'D' => is_demux = true,
            b'E' => is_mux = true,
            b'd' | b'.' | b' ' => {}
            _ => return (false, false),
        }
    }
    (is_demux, is_mux)
}

/// 校验 `-codecs` 6 字符标记位是否为能力行（字符集 = 标记位 + 点/空格，且至少
/// 含一个标记）；头部/图例行（如 `D..... = Decoding supported`）名称位被
/// `is_valid_name` 兜底拒绝，纯点/短线分隔行在此被拒绝。
fn is_codec_flags(flags: &str) -> bool {
    let mut has_marker = false;
    for b in flags.as_bytes() {
        match b {
            b'D' | b'E' | b'V' | b'A' | b'S' | b'T' | b'I' | b'L' => has_marker = true,
            b'.' | b' ' => {}
            _ => return false,
        }
    }
    has_marker
}

/// 解析 `ffprobe -version`/`ffmpeg -version` 首行，取 `version` 后的第一 token。
fn parse_version_line(line: &str) -> Option<String> {
    let trimmed = line.trim();
    let rest = trimmed
        .strip_prefix("ffprobe version ")
        .or_else(|| trimmed.strip_prefix("ffmpeg version "))?;
    let token = rest.split_whitespace().next()?;
    is_valid_name(token).then(|| token.to_string())
}

/// 解析 `ffmpeg -formats` 输出，返回 (demuxer, muxer) 名称列表。
///
/// 行形态：标准头部 + 标记行 `DE name description`（列 0 `D`=demux、列 1 `E`=mux，
/// `.`/空格=不支持，minimal build 现为 `D..` 三列含 device 标记）；变体行为尾部
/// `(demuxing)`/`(muxing)` 后缀。对任意无法解析的行静默跳过，零 panic。
fn parse_formats_output(output: &str) -> (Vec<String>, Vec<String>) {
    let mut demuxer: Vec<String> = Vec::new();
    let mut muxer: Vec<String> = Vec::new();

    for raw in output.lines() {
        let line = raw.trim();
        if line.is_empty() || line == "--" || line == "---" {
            continue;
        }

        // 变体：尾缀 `(demuxing)`/`(muxing)` 决定归类（取后缀前最后一个 token）。
        if line.ends_with("(demuxing)") || line.ends_with("(muxing)") {
            let (is_demux, suffix) = if line.ends_with("(demuxing)") {
                (true, "(demuxing)")
            } else {
                (false, "(muxing)")
            };
            let Some(body) = line.strip_suffix(suffix) else {
                continue;
            };
            let Some(name) = body.trim().split_whitespace().last() else {
                continue;
            };
            if is_valid_name(name) {
                push_unique(if is_demux { &mut demuxer } else { &mut muxer }, name);
            }
            continue;
        }

        // 标准标记行：首 token 为标记位，次 token 为名称。
        let mut tokens = line.split_whitespace();
        let Some(flags) = tokens.next() else {
            continue;
        };
        let (is_demux, is_mux) = format_flags(flags);
        if !is_demux && !is_mux {
            continue;
        }
        let Some(name) = tokens.next() else {
            continue;
        };
        if !is_valid_name(name) {
            continue;
        }
        if is_demux {
            push_unique(&mut demuxer, name);
        }
        if is_mux {
            push_unique(&mut muxer, name);
        }
    }

    (demuxer, muxer)
}

/// 解析 `ffmpeg -codecs` 输出，返回编解码器名称列表。
///
/// 行形态：`DEVILS h264 name`（前 6 字符标记位：D=decode/E=encode/V/A/S/D/T
/// 类型/I=intra/L=lossy/S=lossless，`.` 表示位未置）；头部图例行及其余无法
/// 解析的行静默跳过——名称字段经 `is_valid_name` 校验兜底（`=` 等被过滤）。
fn parse_codecs_output(output: &str) -> Vec<String> {
    let mut codecs: Vec<String> = Vec::new();

    for raw in output.lines() {
        let line = raw.trim();
        if line.is_empty() {
            continue;
        }
        if line.len() < 7 {
            continue;
        }
        // 数据行标记位为能力字符集；头部/图例/乱码行被 `is_codec_flags` 拒绝。
        let flags = &line[..6];
        if !is_codec_flags(flags) {
            continue;
        }
        let Some(name) = parse_name(&line[6..]) else {
            continue;
        };
        push_unique(&mut codecs, name);
    }

    codecs
}

/// 解析已解析的二进制路径运行命令并捕获 stdout+stderr 合并文本。
/// 命令缺失（spawn 失败）、非零退出或超时强杀均返回 `None`（不挂起）。
fn run_tool_capture(path: &Path, args: &[&str]) -> Option<String> {
    let mut command = Command::new(path);
    command.args(args);
    let output =
        run_command_with_timeout(command, Duration::from_secs(CAPABILITY_TIMEOUT_SECS)).ok()?;
    if !output.status.success() {
        return None;
    }
    Some(format!(
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    ))
}

/// 按工具名解析路径并运行（ffprobe 优先用于版本号）。
fn run_tool(tool: &str, args: &[&str]) -> Option<String> {
    let path = match tool {
        "ffprobe" => ffprobe_path().ok()?,
        _ => ffmpeg_path().ok()?,
    };
    run_tool_capture(&path, args)
}

/// 探测全量能力；任一子命令失败即记录 errorlog 一次并保持对应字段为空。
fn probe_capability() -> FfmpegCapability {
    let mut cap = FfmpegCapability::default();
    let mut failures: Vec<&'static str> = Vec::new();

    // 版本号：ffprobe 优先，ffmpeg 兜底。
    match run_tool("ffprobe", &["-version"]) {
        Some(out) => {
            cap.version = out
                .lines()
                .next()
                .and_then(parse_version_line)
                .unwrap_or_default()
        }
        None => failures.push("ffprobe -version"),
    }
    if cap.version.is_empty() {
        match run_tool("ffmpeg", &["-version"]) {
            Some(out) => {
                cap.version = out
                    .lines()
                    .next()
                    .and_then(parse_version_line)
                    .unwrap_or_default()
            }
            None => failures.push("ffmpeg -version"),
        }
    }

    // 能力表。
    match run_tool("ffmpeg", &["-hide_banner", "-formats"]) {
        Some(out) => {
            let (demuxer, muxer) = parse_formats_output(&out);
            cap.formats_demuxer = demuxer;
            cap.formats_muxer = muxer;
        }
        None => failures.push("ffmpeg -formats"),
    }
    match run_tool("ffmpeg", &["-hide_banner", "-codecs"]) {
        Some(out) => cap.codecs = parse_codecs_output(&out),
        None => failures.push("ffmpeg -codecs"),
    }

    if !failures.is_empty() {
        let _ = push_error(
            "",
            "ffmpeg",
            FFMPEG_CAP_STATUS_INTERNAL,
            &format!("ffmpeg capability probe failed: {}", failures.join(", ")),
        );
    }

    cap
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;
    use std::process::Command;
    use std::time::{Duration, Instant};

    // ---- 伪造 `-formats` 文本：3 种形态 --------------------------------------
    const FORMATS_NORMAL: &str = "\
Formats:
 D.. = Demuxing supported
 .E. = Muxing supported
 ..d = Is a device
 ---
 D   asf              
 D   avi              
 D   aac            AAC (Advanced Audio Coding)
  E  image2           
  E  image2pipe       
 D   matroska,webm    
 D   mov,mp4,m4a,3gp,3g2,mj2  
 D   mpegts           
";

    #[test]
    fn parse_formats_normal_multiline() {
        let (demuxer, muxer) = parse_formats_output(FORMATS_NORMAL);
        assert_eq!(
            demuxer,
            vec![
                "asf",
                "avi",
                "aac",
                "matroska,webm",
                "mov,mp4,m4a,3gp,3g2,mj2",
                "mpegts",
            ]
        );
        assert_eq!(muxer, vec!["image2", "image2pipe"]);
    }

    #[test]
    fn parse_formats_empty_output() {
        let empty: Vec<String> = Vec::new();
        assert_eq!(parse_formats_output(""), (empty.clone(), empty.clone()));
        assert_eq!(parse_formats_output("\n   \n--\n"), (empty.clone(), empty));
    }

    #[test]
    fn parse_formats_garbage_lines_no_panic() {
        let garbage = "\
garbage line with no flags
D. = only flags and no name
.E = mux flag but junk name
..d = device row
D   
-------
File formats: legacy header
";
        let (demuxer, muxer) = parse_formats_output(garbage);
        assert!(demuxer.is_empty());
        assert!(muxer.is_empty());
    }

    #[test]
    fn parse_formats_suffix_variants() {
        let input = "\
aac (demuxing)
hls (muxing)
D amv (demuxing)
E wav (muxing)
(prefixed) skips
";
        let (demuxer, muxer) = parse_formats_output(input);
        assert_eq!(demuxer, vec!["aac", "amv"]);
        assert_eq!(muxer, vec!["hls", "wav"]);
    }

    // ---- 伪造 `-codecs` 文本：3 种形态 --------------------------------------
    const CODECS_NORMAL: &str = "\
Codecs:
 D..... = Decoding supported
 .E.... = Encoding supported
 ..V... = Video codec
 ..A... = Audio codec
 ..S... = Subtitle codec
 ..D... = Data codec
 ..T... = Attachment codec
 ...I.. = Intra frame-only codec
 ....L. = Lossy compression
 .....S = Lossless compression
 -------
 ..VI.S 012v                 
 ..V.L. 4xm                  
 ..VI.S 8bps                 
 ..VIL. a64_multi            
 ..VIL. a64_multi5           
 ..V..S aasc                 
";

    #[test]
    fn parse_codecs_normal_multiline() {
        let codecs = parse_codecs_output(CODECS_NORMAL);
        assert_eq!(
            codecs,
            vec!["012v", "4xm", "8bps", "a64_multi", "a64_multi5", "aasc"]
        );
    }

    #[test]
    fn parse_codecs_empty_output() {
        assert!(parse_codecs_output("").is_empty());
        assert!(parse_codecs_output("\n   \n-------\n").is_empty());
    }

    #[test]
    fn parse_codecs_garbage_lines_no_panic() {
        let garbage = "\
not a codec row
DEVIL =
.....
Codecs: legacy header
```
";
        assert!(parse_codecs_output(garbage).is_empty());
    }

    // ---- 版本号 -----------------------------------------------------------------
    #[test]
    fn parse_version_from_probe_and_ffmpeg() {
        assert_eq!(
            parse_version_line(
                "ffprobe version git-2026-08-18-21bbd98 Copyright (c) 2007-2026 the FFmpeg developers"
            ),
            Some("git-2026-08-18-21bbd98".to_string())
        );
        assert_eq!(
            parse_version_line(
                "ffmpeg version 6.1.1-full_build-www.gyan.dev Copyright (c) 2000-2023 the FFmpeg developers"
            ),
            Some("6.1.1-full_build-www.gyan.dev".to_string())
        );
    }

    #[test]
    fn parse_version_rejects_unparseable() {
        assert_eq!(parse_version_line("garbage line"), None);
        assert_eq!(parse_version_line(""), None);
        assert_eq!(parse_version_line("ffmpeg version "), None);
    }

    // ---- JSON 形状（纯函数构造，不触发子进程）-------------------------------------
    #[test]
    fn build_json_returns_valid_shape_even_when_empty() {
        let json = build_json(&FfmpegCapability::default());
        let value: serde_json::Value = serde_json::from_str(&json).expect("应为合法 JSON");
        assert_eq!(value["version"], "");
        assert!(value["formats"].is_array());
        assert!(value["formats"].as_array().unwrap().is_empty());
        assert!(value["codecs"].as_array().unwrap().is_empty());
        assert_eq!(value["demuxer"], value["muxer"]);
    }

    #[test]
    fn build_json_formats_is_demuxer_union_muxer_dedup() {
        let mut cap = FfmpegCapability::default();
        cap.version = "9.9".to_string();
        cap.formats_demuxer = vec!["asf".into(), "mov".into()];
        cap.formats_muxer = vec!["mov".into(), "image2".into()];
        let value: serde_json::Value =
            serde_json::from_str(&build_json(&cap)).expect("应为合法 JSON");
        assert_eq!(value["version"], "9.9");
        assert_eq!(value["formats"], serde_json::json!(["asf", "mov", "image2"]));
    }

    // ---- 命令缺失 / 超时：不挂起 ---------------------------------------------------
    #[test]
    fn missing_binary_returns_none_without_hanging() {
        let start = Instant::now();
        let result = run_tool_capture(Path::new("nonexistent_ffprobe_xyz.exe"), &["-version"]);
        assert!(result.is_none(), "命令缺失应返回 None");
        assert!(start.elapsed() < Duration::from_secs(3), "缺失命令应快速返回");
    }

    #[test]
    fn timeout_kills_long_running_command() {
        let mut command = Command::new("powershell");
        command.args(["-NoProfile", "-Command", "Start-Sleep -Seconds 5"]);
        let start = Instant::now();
        let output = run_command_with_timeout(command, Duration::from_millis(300));
        let elapsed = start.elapsed();
        let output = output.expect("超时返回应仍为 Ok(Output)");
        assert!(!output.status.success(), "超时强杀后状态不应为成功");
        assert!(elapsed < Duration::from_secs(3), "超时应在 3s 内返回，实际 {elapsed:?}");
    }

    // ---- 真实探测（二进制存在才跑，缺失时跳过，不阻塞 cargo test）--------------------
    #[test]
    fn real_probe_when_binary_present() {
        if crate::ffmpeg_path().is_err() {
            return; // 无捆绑 ffmpeg：不依赖真实二进制，跳过本探针。
        }
        let cap = ffmpeg_capability();
        let value: serde_json::Value =
            serde_json::from_str(&capabilities_json()).expect("capabilities_json 应恒为合法 JSON");
        assert!(value["version"].is_string());
        assert!(value["formats"].is_array());
        assert!(value["codecs"].is_array());
        // 捆绑 minimal build 已知支持 asf/avi demuxing（实测定稿，非硬编码断言）。
        assert!(!cap.formats_demuxer.is_empty(), "真实 ffmpeg 下 demuxer 不应为空");
        assert!(cap.formats_demuxer.iter().any(|f| f == "asf" || f == "avi"));
        // 捆绑 build 配置只含 muxer image2/image2pipe（test_ffmpeg_minimal_binaries
        // allow-list 的实测印证）；此处不硬断言其内容，仅要求不因解析而 panic。
    }
}