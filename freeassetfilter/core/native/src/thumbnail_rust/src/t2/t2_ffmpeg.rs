//! T2 ffmpeg 管线（todo 24 实现）。
//!
//! 自 `lib.rs` 整体搬迁的 ffmpeg 缩略图编排逻辑（行为零变化，DR6：搬迁非重写）：
//! - `extract_best_video_frame_jpeg` / `try_extract_frame_with_ffmpeg`：
//!   HW 尝试顺序 d3d11va → dxva2 → qsv、软件回退、
//!   `-frames:v 1 -vf scale -vcodec mjpeg -q:v 3` 参数组、20s 强杀；
//! - `run_ffprobe_basic_info`：ffprobe 时长探测；`build_seek_candidates` 多 seek 候选
//!   （0.20/0.35/0.50/0.10/0.70 比例 + 1/3s + 0s，去重阈值 0.05）；
//! - HW 并发槽位默认 1（`HW_VIDEO_DECODE_SLOTS` / `MAX_CONCURRENT_HW_VIDEO_DECODE_LIMIT`）
//!   与 `native_set_max_concurrent_hw_video_decodes` 导出对齐；软件回退路径另有
//!   独立并发槽位（`SW_VIDEO_DECODE_SLOTS`，默认 min(CPU 逻辑核数, 4)，内建
//!   默认值不新增导出）——突发批量视频时软件 ffmpeg 子进程数有界；
//! - `is_video_ext` 扩展覆盖 T2 清单全集：21 个视频扩展名恒路由 +
//!   avif/heic/heif/jp2 图像容器经 `ffmpeg_capability` 实测 demuxer 表取交集
//!   （**不硬编码可用性**，minimal build 无对应 demuxer 时自动排除）；
//! - 视频 RGBA 缓存路径改经 `decoders::jpeg::decode_jpeg` 解码 ffmpeg MJPEG 输出
//!   （jpeg.rs 的 SOI+EOI 尾预检与完整 MJPEG 帧天然兼容；失败回退 legacy
//!   image crate 解码并记录原因——DR6 兜底路径保留）。
//!
//! 工具路径解析（`ffmpeg_path`/`ffprobe_path`/`run_command_with_timeout`）仍归
//! lib.rs：todo 23 `ffmpeg_capability` 已按 `crate::` 路径复用，保持不动。
//!
//! lib.rs 经本模块薄调用层消费的 API（均 `pub(crate)`）：`is_video_ext`、
//! `decode_video_with_ffmpeg`、`extract_best_video_frame_jpeg_bytes`、
//! `decode_stats_to_json`、`reset_decode_stats`、
//! `set_max_concurrent_hw_video_decodes`、`available_hwaccels_from_ffmpeg`。

use crate::decoders::jpeg::decode_jpeg;
use crate::legacy_image_decode::decode_image_bytes_to_rgba;
use crate::t2::ffmpeg_capability::ffmpeg_capability;
use crate::{ffmpeg_path, ffprobe_path, run_command_with_timeout, STATUS_DECODE_FAILED};
use once_cell::sync::Lazy;
use std::path::Path;
use std::process::Command;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

const FFPROBE_TIMEOUT_SECS: u64 = 8;
const FFMPEG_TIMEOUT_SECS: u64 = 20;
const DEFAULT_MAX_CONCURRENT_HW_VIDEO_DECODES: usize = 1;
const DEFAULT_MAX_CONCURRENT_SW_VIDEO_DECODES: usize = 4;

/// T2 视频扩展名全集（恒路由 ffmpeg 管线；README 视频清单 ∩ 计划 T2 清单）。
/// 对照：Python 侧 `thumbnail_manager.py` VIDEO_FORMATS 仅 11 项（无 vob/m2ts/ts/
/// mts/m2t/dv/prores/3gp/hevc/h264），Python 侧扩展为 todo 27 范围，此处只对照不改。
const VIDEO_EXTS_ALWAYS: &[&str] = &[
    "mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "m4v", "mpeg", "mpg", "mxf", "vob",
    "m2ts", "ts", "mts", "m2t", "dv", "prores", "3gp", "hevc", "h264",
];

/// 能力门控的图像容器：扩展名 → 可解码所需的 demuxer 名（任一命中即路由 T2）。
/// **不硬编码可用性**——经 `ffmpeg_capability()` 实测 `-formats` demuxer 表取交集；
/// bundled minimal build 无 avif/heif/jpeg2000 demuxer 时这些扩展名自动回落
/// image crate 路径。demuxer 名依据：avif→`avif`（FFmpeg n6.1+）、heic/heif→`heif`、
/// jp2→`jpeg2000`（raw JPEG 2000 demuxer 运行时名）。
const CAPABILITY_GATED_IMAGE_EXTS: &[(&str, &[&str])] = &[
    ("avif", &["avif"]),
    ("heic", &["heif"]),
    ("heif", &["heif"]),
    ("jp2", &["jpeg2000"]),
];

#[derive(Default, Debug, Clone)]
struct VideoProbeInfo {
    duration_secs: Option<f64>,
}

#[derive(Default, Debug, Clone)]
struct DecodeStats {
    d3d11va_attempts: u64,
    d3d11va_hits: u64,
    dxva2_attempts: u64,
    dxva2_hits: u64,
    qsv_attempts: u64,
    qsv_hits: u64,
    software_attempts: u64,
    software_hits: u64,
    software_fallbacks: u64,
}

impl DecodeStats {
    fn record_attempt(&mut self, mode: Option<&str>) {
        match mode {
            Some("d3d11va") => self.d3d11va_attempts += 1,
            Some("dxva2") => self.dxva2_attempts += 1,
            Some("qsv") => self.qsv_attempts += 1,
            _ => self.software_attempts += 1,
        }
    }

    fn record_hit(&mut self, mode: Option<&str>) {
        match mode {
            Some("d3d11va") => self.d3d11va_hits += 1,
            Some("dxva2") => self.dxva2_hits += 1,
            Some("qsv") => self.qsv_hits += 1,
            _ => self.software_hits += 1,
        }
    }

    fn record_software_fallback(&mut self) {
        self.software_fallbacks += 1;
    }

    fn to_json(&self) -> String {
        format!(
            "{{\"d3d11va_attempts\":{},\"d3d11va_hits\":{},\"dxva2_attempts\":{},\"dxva2_hits\":{},\"qsv_attempts\":{},\"qsv_hits\":{},\"software_attempts\":{},\"software_hits\":{},\"software_fallbacks\":{}}}",
            self.d3d11va_attempts,
            self.d3d11va_hits,
            self.dxva2_attempts,
            self.dxva2_hits,
            self.qsv_attempts,
            self.qsv_hits,
            self.software_attempts,
            self.software_hits,
            self.software_fallbacks
        )
    }
}

#[derive(Debug, Clone)]
struct FrameExtractResult {
    bytes: Vec<u8>,
    mode: Option<String>,
    verified_hw: bool,
    software_fallback: bool,
}

struct HwDecodePermit {
    acquired: bool,
}

impl HwDecodePermit {
    fn try_acquire() -> Self {
        loop {
            let max_slots = MAX_CONCURRENT_HW_VIDEO_DECODE_LIMIT
                .load(Ordering::Acquire)
                .max(1);
            let current = HW_VIDEO_DECODE_SLOTS.load(Ordering::Acquire);
            if current >= max_slots {
                return Self { acquired: false };
            }
            if HW_VIDEO_DECODE_SLOTS
                .compare_exchange(current, current + 1, Ordering::AcqRel, Ordering::Acquire)
                .is_ok()
            {
                return Self { acquired: true };
            }
        }
    }

    fn acquired(&self) -> bool {
        self.acquired
    }
}

impl Drop for HwDecodePermit {
    fn drop(&mut self) {
        if self.acquired {
            HW_VIDEO_DECODE_SLOTS.fetch_sub(1, Ordering::AcqRel);
        }
    }
}

/// 软件解码默认并发上限：CPU 逻辑核数与 4 取较小值（突发批量视频场景
/// 下软件 ffmpeg 子进程数有界；内建默认值，不新增 FFI 导出）。
fn default_max_concurrent_sw_video_decodes() -> usize {
    thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(DEFAULT_MAX_CONCURRENT_SW_VIDEO_DECODES)
        .min(DEFAULT_MAX_CONCURRENT_SW_VIDEO_DECODES)
        .max(1)
}

/// 软件解码并发许可：与 `HwDecodePermit` 相同的原子槽位模式，区别在于
/// 获取为阻塞等待——软件路径是最终回退，拿不到槽位不能像 HW 一样降级
/// 跳过；持有生命周期 = 单个 ffmpeg 子进程（无嵌套等待，故无死锁）。
struct SwDecodePermit;

impl SwDecodePermit {
    fn acquire() -> Self {
        loop {
            let max_slots = MAX_CONCURRENT_SW_VIDEO_DECODE_LIMIT
                .load(Ordering::Acquire)
                .max(1);
            let current = SW_VIDEO_DECODE_SLOTS.load(Ordering::Acquire);
            if current < max_slots
                && SW_VIDEO_DECODE_SLOTS
                    .compare_exchange(current, current + 1, Ordering::AcqRel, Ordering::Acquire)
                    .is_ok()
            {
                return Self;
            }
            thread::sleep(Duration::from_millis(20));
        }
    }
}

impl Drop for SwDecodePermit {
    fn drop(&mut self) {
        SW_VIDEO_DECODE_SLOTS.fetch_sub(1, Ordering::AcqRel);
    }
}

static DECODE_STATS: Lazy<Mutex<DecodeStats>> = Lazy::new(|| Mutex::new(DecodeStats::default()));
static HW_VIDEO_DECODE_SLOTS: Lazy<AtomicUsize> = Lazy::new(|| AtomicUsize::new(0));
static MAX_CONCURRENT_HW_VIDEO_DECODE_LIMIT: Lazy<AtomicUsize> =
    Lazy::new(|| AtomicUsize::new(DEFAULT_MAX_CONCURRENT_HW_VIDEO_DECODES));
static SW_VIDEO_DECODE_SLOTS: Lazy<AtomicUsize> = Lazy::new(|| AtomicUsize::new(0));
static MAX_CONCURRENT_SW_VIDEO_DECODE_LIMIT: Lazy<AtomicUsize> =
    Lazy::new(|| AtomicUsize::new(default_max_concurrent_sw_video_decodes()));

/// 能力表 demuxer 条目是否覆盖任一给定名称。
///
/// todo 23 契约：多名称条目（如 `mov,mp4,m4a,3gp,3g2,mj2` / `matroska,webm`）
/// 保持原样存储，拆分属 todo 24（本模块）职责——故逐条目按逗号拆分成员后匹配。
fn demuxer_supports_any(names: &[&str]) -> bool {
    ffmpeg_capability()
        .formats_demuxer
        .iter()
        .any(|entry| entry.split(',').any(|member| names.contains(&member.trim())))
}

pub(crate) fn is_video_ext(path: &str) -> bool {
    let ext = Path::new(path)
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    if VIDEO_EXTS_ALWAYS.contains(&ext.as_str()) {
        return true;
    }
    // 图像容器：仅当实测 demuxer 能力命中才路由 T2（交集逻辑，不硬编码可用性）。
    CAPABILITY_GATED_IMAGE_EXTS
        .iter()
        .any(|(image_ext, demuxers)| *image_ext == ext.as_str() && demuxer_supports_any(demuxers))
}

pub(crate) fn available_hwaccels_from_ffmpeg() -> Vec<String> {
    let ffmpeg = match ffmpeg_path() {
        Ok(path) => path,
        Err(_) => return Vec::new(),
    };

    let mut command = Command::new(ffmpeg);
    command
        .arg("-hide_banner")
        .arg("-loglevel")
        .arg("quiet")
        .arg("-hwaccels");

    let output = match run_command_with_timeout(command, Duration::from_secs(5)) {
        Ok(o) if o.status.success() => o,
        _ => return Vec::new(),
    };

    let mut detected = Vec::new();
    let combined_output = format!(
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );

    for line in combined_output.lines() {
        let normalized = line.trim().to_ascii_lowercase();
        if normalized.is_empty() || normalized == "hardware acceleration methods:" {
            continue;
        }

        if matches!(normalized.as_str(), "d3d11va" | "dxva2" | "qsv")
            && !detected.iter().any(|existing| existing == &normalized)
        {
            detected.push(normalized);
        }
    }

    detected
}

fn run_ffprobe_basic_info(path: &str) -> VideoProbeInfo {
    let ffprobe = match ffprobe_path() {
        Ok(p) => p,
        Err(_) => return VideoProbeInfo::default(),
    };

    let mut command = Command::new(ffprobe);
    command
        .arg("-v")
        .arg("error")
        .arg("-select_streams")
        .arg("v:0")
        .arg("-show_entries")
        .arg("format=duration")
        .arg("-of")
        .arg("default=noprint_wrappers=1:nokey=0")
        .arg(path);

    let output = match run_command_with_timeout(command, Duration::from_secs(FFPROBE_TIMEOUT_SECS))
    {
        Ok(o) if o.status.success() => o,
        _ => return VideoProbeInfo::default(),
    };

    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut info = VideoProbeInfo::default();

    for line in stdout.lines() {
        let trimmed = line.trim();
        if let Some(value) = trimmed.strip_prefix("duration=") {
            if let Ok(v) = value.trim().parse::<f64>() {
                if v.is_finite() && v > 0.0 {
                    info.duration_secs = Some(v);
                }
            }
        }
    }

    info
}

fn clamp_seek_time(t: f64, duration: Option<f64>) -> f64 {
    let mut time = if t.is_finite() { t } else { 0.0 };
    if time < 0.0 {
        time = 0.0;
    }
    if let Some(d) = duration {
        if d.is_finite() && d > 0.0 {
            let upper = (d - 0.05).max(0.0);
            if time > upper {
                time = upper;
            }
        }
    }
    time
}

fn build_seek_candidates(info: &VideoProbeInfo) -> Vec<f64> {
    let mut candidates = Vec::new();

    if let Some(duration) = info.duration_secs {
        if duration.is_finite() && duration > 0.0 {
            for ratio in [0.20f64, 0.35, 0.50, 0.10, 0.70] {
                candidates.push(duration * ratio);
            }
        }
    }

    candidates.push(1.0 / 3.0);
    candidates.push(0.0);

    let mut normalized = Vec::new();
    for v in candidates {
        let clamped = clamp_seek_time(v, info.duration_secs);
        if !normalized
            .iter()
            .any(|existing: &f64| (*existing - clamped).abs() < 0.05)
        {
            normalized.push(clamped);
        }
    }
    normalized
}

fn ffmpeg_log_indicates_hw_hit(stderr: &str, hwaccel: &str) -> bool {
    let log = stderr.to_ascii_lowercase();
    match hwaccel {
        "d3d11va" => {
            (log.contains("d3d11va")
                && (log.contains("hwaccel") || log.contains("using") || log.contains("decoder")))
                || log.contains("using auto hwaccel type d3d11va")
                || log.contains("using hwaccel d3d11va")
                || log.contains("av_hwdevice_ctx_create")
        }
        "dxva2" => {
            (log.contains("dxva2")
                && (log.contains("hwaccel") || log.contains("using") || log.contains("decoder")))
                || log.contains("using auto hwaccel type dxva2")
                || log.contains("using hwaccel dxva2")
        }
        "qsv" => {
            (log.contains("qsv")
                && (log.contains("mfx") || log.contains("hwaccel") || log.contains("decoder")))
                || log.contains("initialized an internal mfx session")
                || log.contains("using hwaccel qsv")
        }
        _ => false,
    }
}

fn scale_filter(width: u32, height: u32) -> String {
    format!(
        "scale={}:{}:force_original_aspect_ratio=decrease:flags=fast_bilinear",
        width.max(1),
        height.max(1)
    )
}

fn try_extract_frame_with_ffmpeg(
    path: &str,
    seek_time: f64,
    width: u32,
    height: u32,
    hwaccel: Option<&str>,
    software_fallback: bool,
) -> Option<FrameExtractResult> {
    let ffmpeg = ffmpeg_path().ok()?;
    let seek = format!("{seek_time:.3}");

    {
        let mut stats = DECODE_STATS.lock().ok()?;
        stats.record_attempt(hwaccel);
    }

    // 软件路径独立并发槽位：HW 槽位只约束 hwaccel 尝试，软件 ffmpeg
    // 子进程若无独立上限，突发批量视频会同时起 N 个 ffmpeg.exe。
    let _sw_permit = if hwaccel.is_none() {
        Some(SwDecodePermit::acquire())
    } else {
        None
    };

    let mut command = Command::new(ffmpeg);
    command.arg("-hide_banner");
    if hwaccel.is_some() {
        command.arg("-loglevel").arg("info");
    } else {
        command.arg("-loglevel").arg("error");
    }

    if let Some(accel) = hwaccel {
        command.arg("-hwaccel").arg(accel);
        if accel == "qsv" {
            command.arg("-hwaccel_output_format").arg("qsv");
        }
    }

    command.arg("-ss").arg(&seek);
    command.arg("-i").arg(path);
    command.arg("-frames:v").arg("1");
    command.arg("-an");
    command.arg("-sn");
    command.arg("-dn");
    command.arg("-vf").arg(scale_filter(width, height));
    command.arg("-vcodec").arg("mjpeg");
    command.arg("-q:v").arg("3");
    command.arg("-f").arg("image2pipe");
    command.arg("pipe:1");

    let output =
        run_command_with_timeout(command, Duration::from_secs(FFMPEG_TIMEOUT_SECS)).ok()?;
    if !output.status.success() || output.stdout.is_empty() {
        return None;
    }

    let verified_hw = if let Some(accel) = hwaccel {
        let stderr = String::from_utf8_lossy(&output.stderr);
        ffmpeg_log_indicates_hw_hit(&stderr, accel)
    } else {
        false
    };

    {
        let mut stats = DECODE_STATS.lock().ok()?;
        if hwaccel.is_none() {
            stats.record_hit(None);
            if software_fallback {
                stats.record_software_fallback();
            }
        } else if verified_hw {
            stats.record_hit(hwaccel);
        } else {
            // HW 标签尝试成功但日志无法证实硬件路径：ffmpeg d3d11va 可静默
            // 回退软件解码且 info 级日志不可区分，此时按软件归因——HW 尝试
            // 成功要么记 hit 要么记 software_fallback，不再两边落空（修复
            // d3d11va_attempts 递增而 d3d11va_hits 恒 0 的统计失衡）。
            stats.record_software_fallback();
        }
    }

    Some(FrameExtractResult {
        bytes: output.stdout,
        mode: hwaccel.map(|s| s.to_string()),
        verified_hw,
        software_fallback,
    })
}

fn extract_best_video_frame_jpeg(
    path: &str,
    width: u32,
    height: u32,
) -> Result<FrameExtractResult, i32> {
    let info = run_ffprobe_basic_info(path);
    let seek_candidates = build_seek_candidates(&info);
    let hw_permit = HwDecodePermit::try_acquire();
    let allow_hw = hw_permit.acquired();

    for seek_time in seek_candidates {
        let mut had_hw_attempt = false;

        if allow_hw {
            for accel in [Some("d3d11va"), Some("dxva2"), Some("qsv")] {
                had_hw_attempt = true;
                if let Some(result) =
                    try_extract_frame_with_ffmpeg(path, seek_time, width, height, accel, false)
                {
                    if !result.bytes.is_empty() {
                        eprintln!(
                            "[thumbnail_generator] decode path file={} mode={} verified_hw={}",
                            path,
                            result.mode.as_deref().unwrap_or("software"),
                            result.verified_hw
                        );
                        return Ok(result);
                    }
                }
            }
        }

        if let Some(result) = try_extract_frame_with_ffmpeg(
            path,
            seek_time,
            width,
            height,
            None,
            had_hw_attempt || !allow_hw,
        ) {
            if !result.bytes.is_empty() {
                eprintln!(
                    "[thumbnail_generator] decode path file={} mode={} verified_hw={} software_fallback={}",
                    path,
                    result.mode.as_deref().unwrap_or("software"),
                    result.verified_hw,
                    result.software_fallback
                );
                return Ok(result);
            }
        }
    }

    Err(STATUS_DECODE_FAILED)
}

pub(crate) fn decode_video_with_ffmpeg(
    path: &str,
    width: u32,
    height: u32,
) -> Result<(Vec<u8>, u32, u32), i32> {
    let result = extract_best_video_frame_jpeg(path, width, height)?;
    // todo 24：MJPEG 帧解码改经 decoders::jpeg::decode_jpeg（jpeg.rs SOI+EOI 尾
    // 预检与 ffmpeg image2pipe 完整输出天然兼容——合法 MJPEG 帧以 FFD9 结尾）。
    // 回退：若 ffmpeg 管道截断输出丢失 EOI 尾标记，jpeg.rs 预检 A' 会拒绝（-2），
    // 此时退回 legacy image crate 解码兜底（DR6：保留不删），行为不劣于搬迁前。
    match decode_jpeg(&result.bytes) {
        Ok(out) => Ok(out),
        Err(code) => {
            eprintln!(
                "[thumbnail_generator] mjpeg decode via jpeg.rs failed code={} falling back to legacy image decode file={}",
                code, path
            );
            decode_image_bytes_to_rgba(&result.bytes)
        }
    }
}

// ---- lib.rs 薄调用层消费的导出（pub(crate)，FFI 导出仍在 lib.rs）----------------

/// 抽帧并直接返回 JPEG 字节（`generate_jpeg_bytes` 视频分支用）。
pub(crate) fn extract_best_video_frame_jpeg_bytes(
    path: &str,
    width: u32,
    height: u32,
) -> Result<Vec<u8>, i32> {
    extract_best_video_frame_jpeg(path, width, height).map(|r| r.bytes)
}

/// 解码统计 JSON（锁失败返回 `"{}"`，与搬迁前 `native_get_decode_stats_json`
/// 的 `Err(_) => c_message("{}")` 行为一致）。
pub(crate) fn decode_stats_to_json() -> String {
    match DECODE_STATS.lock() {
        Ok(stats) => stats.to_json(),
        Err(_) => "{}".to_string(),
    }
}

/// 重置解码统计（true=成功；lib.rs 映射 STATUS_OK / STATUS_INTERNAL）。
pub(crate) fn reset_decode_stats() -> bool {
    match DECODE_STATS.lock() {
        Ok(mut stats) => {
            *stats = DecodeStats::default();
            true
        }
        Err(_) => false,
    }
}

/// 设置 HW 并发槽位上限（下限钳到 1；与搬迁前导出语义一致）。
pub(crate) fn set_max_concurrent_hw_video_decodes(max_slots: usize) {
    MAX_CONCURRENT_HW_VIDEO_DECODE_LIMIT.store(max_slots.max(1), Ordering::Release);
}
