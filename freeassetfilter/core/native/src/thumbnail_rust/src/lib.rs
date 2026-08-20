use image::codecs::jpeg::JpegEncoder;
use image::ColorType;
use once_cell::sync::Lazy;
use rayon::prelude::*;
use std::collections::{HashMap, VecDeque};
use std::env;
use std::ffi::{CStr, CString};
use std::fs;
use std::os::raw::{c_char, c_int};
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use sysinfo::System;

// 模块骨架（todo 1）：T1 自研解码器 / T2 ffmpeg 管线 / T3 跳过记录 /
// 输出编码器 / image crate 回退（todo 26 移除 legacy_image_decode）。
mod decoders;
mod encoders;
mod infra;
mod legacy_image_decode;
mod t2;
mod t3;

// image crate 回退路径（todo 1 自本文件抽取至 legacy_image_decode.rs）；
// todo 26 随 image crate 一并移除。
use legacy_image_decode::{decode_image_bytes_to_rgba, decode_with_image_crate};

const DEFAULT_MAX_MEMORY_BYTES: usize = 200 * 1024 * 1024;
const DEFAULT_K: usize = 2;
const FFPROBE_TIMEOUT_SECS: u64 = 8;
const FFMPEG_TIMEOUT_SECS: u64 = 20;
const DEFAULT_MAX_CONCURRENT_HW_VIDEO_DECODES: usize = 1;

const STATUS_OK: i32 = 0;
const STATUS_INVALID_ARG: i32 = -1;
pub(crate) const STATUS_DECODE_FAILED: i32 = -2;
const STATUS_OOM: i32 = -3;
const STATUS_NOT_FOUND: i32 = -4;
const STATUS_INTERNAL: i32 = -5;
// todo 25（T3 跳过）接入前暂未被消费；与 STATUS_OOM=-3 区分路由（-3 低内存交
// Python 回退，-7 仅维度超限），见 plan todo 27 路由表。
#[allow(dead_code)]
pub(crate) const STATUS_UNSUPPORTED: i32 = -6;
#[allow(dead_code)]
pub(crate) const STATUS_TOO_LARGE: i32 = -7;

#[repr(C)]
pub struct NativeThumbnailResult {
    pub status: i32,
    pub width: u32,
    pub height: u32,
    pub channels: u8,
    pub len: usize,
    pub data: *mut u8,
    pub message: *mut c_char,
}

#[repr(C)]
pub struct NativeThumbnailBatchResult {
    pub status: i32,
    pub count: usize,
    pub results: *mut NativeThumbnailResult,
    pub message: *mut c_char,
}

#[derive(Clone)]
struct CacheEntry {
    data: Vec<u8>,
    width: u32,
    height: u32,
    channels: u8,
    byte_size: usize,
    accesses: VecDeque<u64>,
}

impl CacheEntry {
    fn touch(&mut self, ts: u64, k: usize) {
        self.accesses.push_back(ts);
        while self.accesses.len() > k {
            self.accesses.pop_front();
        }
    }

    fn k_th_access(&self, k: usize) -> u64 {
        if self.accesses.len() >= k {
            *self.accesses.front().unwrap_or(&0)
        } else {
            0
        }
    }
}

struct NativeEngine {
    cache: HashMap<String, CacheEntry>,
    max_memory_bytes: usize,
    used_memory_bytes: usize,
    k: usize,
    system: System,
    paused_preload: bool,
    emergency_mode: bool,
}

impl NativeEngine {
    fn new() -> Self {
        Self {
            cache: HashMap::new(),
            max_memory_bytes: DEFAULT_MAX_MEMORY_BYTES,
            used_memory_bytes: 0,
            k: DEFAULT_K,
            system: System::new_all(),
            paused_preload: false,
            emergency_mode: false,
        }
    }

    fn now_ts() -> u64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_millis() as u64)
            .unwrap_or(0)
    }

    fn make_cache_key(path: &str, width: u32, height: u32) -> String {
        format!("{path}|{width}x{height}")
    }

    fn update_memory_pressure(&mut self) {
        self.system.refresh_memory();
        let total = self.system.total_memory() as f64;
        let used = self.system.used_memory() as f64;
        if total <= 0.0 {
            return;
        }
        let ratio = used / total;

        self.paused_preload = ratio >= 0.80;
        if ratio >= 0.90 {
            self.evict_until_budget(self.max_memory_bytes.saturating_mul(60) / 100);
        }
        self.emergency_mode = ratio >= 0.95;
    }

    fn get(&mut self, key: &str) -> Option<CacheEntry> {
        let ts = Self::now_ts();
        if let Some(entry) = self.cache.get_mut(key) {
            entry.touch(ts, self.k);
            return Some(entry.clone());
        }
        None
    }

    fn put(&mut self, key: String, mut entry: CacheEntry) {
        let ts = Self::now_ts();
        entry.touch(ts, self.k);
        let size = entry.byte_size;
        if let Some(old) = self.cache.insert(key, entry) {
            self.used_memory_bytes = self.used_memory_bytes.saturating_sub(old.byte_size);
        }
        self.used_memory_bytes = self.used_memory_bytes.saturating_add(size);
        self.evict_until_budget(self.max_memory_bytes);
    }

    fn evict_until_budget(&mut self, budget: usize) {
        while self.used_memory_bytes > budget && !self.cache.is_empty() {
            let mut victim_key = None;
            let mut oldest = u64::MAX;
            for (k, v) in &self.cache {
                let ts = v.k_th_access(self.k);
                if ts < oldest {
                    oldest = ts;
                    victim_key = Some(k.clone());
                }
            }
            if let Some(vk) = victim_key {
                if let Some(v) = self.cache.remove(&vk) {
                    self.used_memory_bytes = self.used_memory_bytes.saturating_sub(v.byte_size);
                }
            } else {
                break;
            }
        }
    }

    fn set_cache_limit(&mut self, bytes: usize) {
        self.max_memory_bytes = bytes.max(8 * 1024 * 1024);
        self.evict_until_budget(self.max_memory_bytes);
    }

    fn clear_cache(&mut self) {
        self.cache.clear();
        self.used_memory_bytes = 0;
    }
}

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

fn is_video_ext(path: &str) -> bool {
    let ext = Path::new(path)
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    matches!(
        ext.as_str(),
        "mp4"
            | "mov"
            | "mkv"
            | "flv"
            | "3gp"
            | "mxf"
            | "avi"
            | "webm"
            | "wmv"
            | "mpg"
            | "mpeg"
            | "m4v"
    )
}

fn candidate_native_dir_paths() -> Vec<PathBuf> {
    let mut paths = Vec::new();

    if let Ok(cwd) = env::current_dir() {
        paths.push(cwd.join("freeassetfilter").join("core").join("native"));
        paths.push(cwd.join("core").join("native"));
        paths.push(cwd.join("native"));
        paths.push(cwd.join("freeassetfilter").join("core").join("native").join("bin"));
        paths.push(cwd.join("core").join("native").join("bin"));
        paths.push(cwd.join("native").join("bin"));
    }

    if let Ok(exe) = env::current_exe() {
        if let Some(dir) = exe.parent() {
            paths.push(dir.join("freeassetfilter").join("core").join("native"));
            paths.push(dir.join("core").join("native"));
            paths.push(dir.join("native"));
            paths.push(dir.join("freeassetfilter").join("core").join("native").join("bin"));
            paths.push(dir.join("core").join("native").join("bin"));
            paths.push(dir.join("native").join("bin"));
        }
    }

    paths.push(PathBuf::from("freeassetfilter").join("core").join("native"));
    paths.push(PathBuf::from("core").join("native"));
    paths.push(PathBuf::from("freeassetfilter").join("core").join("native").join("bin"));
    paths.push(PathBuf::from("core").join("native").join("bin"));

    let mut dedup = Vec::new();
    for p in paths {
        if !dedup.iter().any(|existing: &PathBuf| existing == &p) {
            dedup.push(p);
        }
    }
    dedup
}

fn resolve_tool_path(tool_name: &str) -> Option<PathBuf> {
    for dir in candidate_native_dir_paths() {
        let candidate = dir.join(tool_name);
        if candidate.exists() {
            return Some(candidate);
        }
    }
    None
}

// `pub(crate)`：供 todo 23 `t2::ffmpeg_capability` 能力探测复用（子进程路径解析）。
pub(crate) fn ffprobe_path() -> Result<PathBuf, i32> {
    resolve_tool_path("ffprobe.exe").ok_or(STATUS_INTERNAL)
}

pub(crate) fn ffmpeg_path() -> Result<PathBuf, i32> {
    resolve_tool_path("ffmpeg.exe").ok_or(STATUS_INTERNAL)
}

fn available_hwaccels_from_ffmpeg() -> Vec<String> {
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

// `pub(crate)`：供 todo 23 `t2::ffmpeg_capability` 能力探测复用（子进程超时保护）。
pub(crate) fn run_command_with_timeout(
    mut command: Command,
    timeout: Duration,
) -> std::io::Result<Output> {
    command.stdout(Stdio::piped()).stderr(Stdio::piped());

    let mut child = command.spawn()?;
    let start = Instant::now();

    loop {
        if child.try_wait()?.is_some() {
            return child.wait_with_output();
        }

        if start.elapsed() >= timeout {
            let _ = child.kill();
            return child.wait_with_output();
        }

        thread::sleep(Duration::from_millis(20));
    }
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

fn decode_video_with_ffmpeg(
    path: &str,
    width: u32,
    height: u32,
) -> Result<(Vec<u8>, u32, u32), i32> {
    let result = extract_best_video_frame_jpeg(path, width, height)?;
    decode_image_bytes_to_rgba(&result.bytes)
}

fn generate_entry(path: &str, width: u32, height: u32) -> Result<CacheEntry, i32> {
    let key = NativeEngine::make_cache_key(path, width, height);

    {
        let mut engine = ENGINE.lock().map_err(|_| STATUS_INTERNAL)?;
        engine.update_memory_pressure();

        if let Some(entry) = engine.get(&key) {
            return Ok(entry);
        }

        if engine.emergency_mode
            && fs::metadata(path)
                .map(|m| m.len() > 10 * 1024 * 1024)
                .unwrap_or(false)
        {
            return Err(STATUS_OOM);
        }
    }

    let (data, w, h) = if is_video_ext(path) {
        decode_video_with_ffmpeg(path, width, height)?
    } else {
        decode_with_image_crate(path, width, height)?
    };

    let candidate = CacheEntry {
        byte_size: data.len(),
        data,
        width: w,
        height: h,
        channels: 4,
        accesses: VecDeque::with_capacity(DEFAULT_K),
    };

    let mut engine = ENGINE.lock().map_err(|_| STATUS_INTERNAL)?;
    if let Some(entry) = engine.get(&key) {
        return Ok(entry);
    }

    engine.put(key, candidate.clone());
    Ok(candidate)
}

fn generate_jpeg_bytes(path: &str, width: u32, height: u32) -> Result<Vec<u8>, i32> {
    if is_video_ext(path) {
        return extract_best_video_frame_jpeg(path, width, height).map(|r| r.bytes);
    }

    let entry = generate_entry(path, width, height)?;
    encode_jpeg_bytes(&entry)
}

static ENGINE: Lazy<Mutex<NativeEngine>> = Lazy::new(|| Mutex::new(NativeEngine::new()));
static DECODE_STATS: Lazy<Mutex<DecodeStats>> = Lazy::new(|| Mutex::new(DecodeStats::default()));
static HW_VIDEO_DECODE_SLOTS: Lazy<AtomicUsize> = Lazy::new(|| AtomicUsize::new(0));
static MAX_CONCURRENT_HW_VIDEO_DECODE_LIMIT: Lazy<AtomicUsize> =
    Lazy::new(|| AtomicUsize::new(DEFAULT_MAX_CONCURRENT_HW_VIDEO_DECODES));

fn c_message(msg: &str) -> *mut c_char {
    CString::new(msg)
        .unwrap_or_else(|_| CString::new("invalid message").unwrap())
        .into_raw()
}

fn make_result_from_entry(entry: CacheEntry) -> NativeThumbnailResult {
    let mut boxed = entry.data.into_boxed_slice();
    let len = boxed.len();
    let ptr = boxed.as_mut_ptr();
    std::mem::forget(boxed);

    NativeThumbnailResult {
        status: STATUS_OK,
        width: entry.width,
        height: entry.height,
        channels: entry.channels,
        len,
        data: ptr,
        message: c_message("ok"),
    }
}

fn rgba_to_jpeg_rgb(entry: &CacheEntry) -> Vec<u8> {
    let mut rgb = Vec::with_capacity((entry.width as usize) * (entry.height as usize) * 3);
    for px in entry.data.chunks_exact(4) {
        let r = px[0] as u32;
        let g = px[1] as u32;
        let b = px[2] as u32;
        let a = px[3] as u32;

        let out_r = ((r * a) + (255 * (255 - a)) + 127) / 255;
        let out_g = ((g * a) + (255 * (255 - a)) + 127) / 255;
        let out_b = ((b * a) + (255 * (255 - a)) + 127) / 255;

        rgb.push(out_r as u8);
        rgb.push(out_g as u8);
        rgb.push(out_b as u8);
    }
    rgb
}

fn encode_jpeg_bytes(entry: &CacheEntry) -> Result<Vec<u8>, i32> {
    let rgb = rgba_to_jpeg_rgb(entry);
    let mut jpeg_buf = Vec::with_capacity(entry.byte_size / 4 + 256);
    let mut encoder = JpegEncoder::new_with_quality(&mut jpeg_buf, 90);
    if encoder
        .encode(&rgb, entry.width, entry.height, ColorType::Rgb8.into())
        .is_err()
    {
        return Err(STATUS_INTERNAL);
    }
    Ok(jpeg_buf)
}

fn make_jpeg_result(bytes: Vec<u8>) -> NativeThumbnailResult {
    let mut boxed = bytes.into_boxed_slice();
    let len = boxed.len();
    let ptr = boxed.as_mut_ptr();
    std::mem::forget(boxed);

    NativeThumbnailResult {
        status: STATUS_OK,
        width: 0,
        height: 0,
        channels: 3,
        len,
        data: ptr,
        message: c_message("ok"),
    }
}

fn make_error_result(status: i32, msg: &str) -> NativeThumbnailResult {
    NativeThumbnailResult {
        status,
        width: 0,
        height: 0,
        channels: 0,
        len: 0,
        data: std::ptr::null_mut(),
        message: c_message(msg),
    }
}

struct ParallelBatchItem {
    status: i32,
    width: u32,
    height: u32,
    channels: u8,
    data: Vec<u8>,
    message: String,
}

impl ParallelBatchItem {
    fn ok_from_entry(entry: CacheEntry) -> Self {
        Self {
            status: STATUS_OK,
            width: entry.width,
            height: entry.height,
            channels: entry.channels,
            data: entry.data,
            message: "ok".to_string(),
        }
    }

    fn ok_jpeg_bytes(data: Vec<u8>) -> Self {
        Self {
            status: STATUS_OK,
            width: 0,
            height: 0,
            channels: 3,
            data,
            message: "ok".to_string(),
        }
    }

    fn err(status: i32, message: &str) -> Self {
        Self {
            status,
            width: 0,
            height: 0,
            channels: 0,
            data: Vec::new(),
            message: message.to_string(),
        }
    }

    fn into_native(self) -> NativeThumbnailResult {
        let mut boxed = self.data.into_boxed_slice();
        let len = boxed.len();
        let ptr = if len > 0 {
            let p = boxed.as_mut_ptr();
            std::mem::forget(boxed);
            p
        } else {
            std::ptr::null_mut()
        };

        NativeThumbnailResult {
            status: self.status,
            width: self.width,
            height: self.height,
            channels: self.channels,
            len,
            data: ptr,
            message: c_message(&self.message),
        }
    }
}

fn ptr_to_string(path: *const c_char) -> Result<String, i32> {
    if path.is_null() {
        return Err(STATUS_INVALID_ARG);
    }
    let c = unsafe { CStr::from_ptr(path) };
    let s = c.to_string_lossy().trim().to_string();
    if s.is_empty() {
        return Err(STATUS_INVALID_ARG);
    }
    Ok(s)
}

#[no_mangle]
pub extern "C" fn native_generate_thumbnail(
    path: *const c_char,
    width: c_int,
    height: c_int,
) -> NativeThumbnailResult {
    std::panic::catch_unwind(|| {
        if width <= 0 || height <= 0 {
            return make_error_result(STATUS_INVALID_ARG, "invalid target size");
        }

        let path = match ptr_to_string(path) {
            Ok(p) => p,
            Err(_) => return make_error_result(STATUS_INVALID_ARG, "invalid path"),
        };

        if !Path::new(&path).exists() {
            return make_error_result(STATUS_NOT_FOUND, "file not found");
        }

        match generate_entry(&path, width as u32, height as u32) {
            Ok(entry) => make_result_from_entry(entry),
            Err(code) => make_error_result(code, "generate failed"),
        }
    })
    .unwrap_or_else(|_| std::process::abort())
}

#[no_mangle]
pub extern "C" fn native_generate_thumbnail_jpeg(
    path: *const c_char,
    width: c_int,
    height: c_int,
) -> NativeThumbnailResult {
    std::panic::catch_unwind(|| {
        if width <= 0 || height <= 0 {
            return make_error_result(STATUS_INVALID_ARG, "invalid target size");
        }

        let path = match ptr_to_string(path) {
            Ok(p) => p,
            Err(_) => return make_error_result(STATUS_INVALID_ARG, "invalid path"),
        };

        if !Path::new(&path).exists() {
            return make_error_result(STATUS_NOT_FOUND, "file not found");
        }

        match generate_jpeg_bytes(&path, width as u32, height as u32) {
            Ok(bytes) => make_jpeg_result(bytes),
            Err(code) => make_error_result(code, "generate failed"),
        }
    })
    .unwrap_or_else(|_| std::process::abort())
}

#[no_mangle]
pub extern "C" fn native_generate_thumbnail_jpg(
    path: *const c_char,
    width: c_int,
    height: c_int,
) -> NativeThumbnailResult {
    std::panic::catch_unwind(|| native_generate_thumbnail_jpeg(path, width, height))
        .unwrap_or_else(|_| std::process::abort())
}

#[no_mangle]
pub extern "C" fn native_generate_batch(
    paths: *const *const c_char,
    count: c_int,
    width: c_int,
    height: c_int,
) -> NativeThumbnailBatchResult {
    std::panic::catch_unwind(|| {
        if paths.is_null() || count <= 0 || width <= 0 || height <= 0 {
            return NativeThumbnailBatchResult {
                status: STATUS_INVALID_ARG,
                count: 0,
                results: std::ptr::null_mut(),
                message: c_message("invalid args"),
            };
        }

        let slice = unsafe { std::slice::from_raw_parts(paths, count as usize) };
        let mut parsed_paths = Vec::with_capacity(slice.len());
        for &p in slice {
            match ptr_to_string(p) {
                Ok(s) => parsed_paths.push(s),
                Err(_) => parsed_paths.push(String::new()),
            }
        }

        let parallel_items: Vec<ParallelBatchItem> = parsed_paths
            .par_iter()
            .map(|path| {
                if path.is_empty() {
                    return ParallelBatchItem::err(STATUS_INVALID_ARG, "invalid path");
                }
                if !Path::new(path).exists() {
                    return ParallelBatchItem::err(STATUS_NOT_FOUND, "file not found");
                }

                match generate_entry(path, width as u32, height as u32) {
                    Ok(entry) => ParallelBatchItem::ok_from_entry(entry),
                    Err(code) => ParallelBatchItem::err(code, "generate failed"),
                }
            })
            .collect();

        let results_vec: Vec<NativeThumbnailResult> = parallel_items
            .into_iter()
            .map(ParallelBatchItem::into_native)
            .collect();

        let mut boxed = results_vec.into_boxed_slice();
        let ptr = boxed.as_mut_ptr();
        let len = boxed.len();
        std::mem::forget(boxed);

        NativeThumbnailBatchResult {
            status: STATUS_OK,
            count: len,
            results: ptr,
            message: c_message("ok"),
        }
    })
    .unwrap_or_else(|_| std::process::abort())
}

#[no_mangle]
pub extern "C" fn native_generate_batch_jpg(
    paths: *const *const c_char,
    count: c_int,
    width: c_int,
    height: c_int,
) -> NativeThumbnailBatchResult {
    std::panic::catch_unwind(|| {
        if paths.is_null() || count <= 0 || width <= 0 || height <= 0 {
            return NativeThumbnailBatchResult {
                status: STATUS_INVALID_ARG,
                count: 0,
                results: std::ptr::null_mut(),
                message: c_message("invalid args"),
            };
        }

        let slice = unsafe { std::slice::from_raw_parts(paths, count as usize) };
        let mut parsed_paths = Vec::with_capacity(slice.len());
        for &p in slice {
            match ptr_to_string(p) {
                Ok(s) => parsed_paths.push(s),
                Err(_) => parsed_paths.push(String::new()),
            }
        }

        let parallel_items: Vec<ParallelBatchItem> = parsed_paths
            .par_iter()
            .map(|path| {
                if path.is_empty() {
                    return ParallelBatchItem::err(STATUS_INVALID_ARG, "invalid path");
                }
                if !Path::new(path).exists() {
                    return ParallelBatchItem::err(STATUS_NOT_FOUND, "file not found");
                }

                match generate_jpeg_bytes(path, width as u32, height as u32) {
                    Ok(bytes) => ParallelBatchItem::ok_jpeg_bytes(bytes),
                    Err(code) => ParallelBatchItem::err(code, "generate failed"),
                }
            })
            .collect();

        let results_vec: Vec<NativeThumbnailResult> = parallel_items
            .into_iter()
            .map(ParallelBatchItem::into_native)
            .collect();

        let mut boxed = results_vec.into_boxed_slice();
        let ptr = boxed.as_mut_ptr();
        let len = boxed.len();
        std::mem::forget(boxed);

        NativeThumbnailBatchResult {
            status: STATUS_OK,
            count: len,
            results: ptr,
            message: c_message("ok"),
        }
    })
    .unwrap_or_else(|_| std::process::abort())
}

#[no_mangle]
pub extern "C" fn native_get_decode_stats_json() -> *mut c_char {
    std::panic::catch_unwind(|| match DECODE_STATS.lock() {
        Ok(stats) => c_message(&stats.to_json()),
        Err(_) => c_message("{}"),
    })
    .unwrap_or_else(|_| std::process::abort())
}

#[no_mangle]
pub extern "C" fn native_reset_decode_stats() -> c_int {
    std::panic::catch_unwind(|| match DECODE_STATS.lock() {
        Ok(mut stats) => {
            *stats = DecodeStats::default();
            STATUS_OK
        }
        Err(_) => STATUS_INTERNAL,
    })
    .unwrap_or_else(|_| std::process::abort())
}

#[no_mangle]
pub extern "C" fn native_get_error_log_json() -> *mut c_char {
    std::panic::catch_unwind(|| c_message(&infra::errorlog::error_log_to_json()))
        .unwrap_or_else(|_| c_message("[]"))
}

#[no_mangle]
pub extern "C" fn native_clear_error_log() -> c_int {
    std::panic::catch_unwind(|| match infra::errorlog::clear_error_log() {
        true => STATUS_OK,
        false => STATUS_INTERNAL,
    })
    .unwrap_or_else(|_| STATUS_INTERNAL)
}

#[no_mangle]
pub extern "C" fn native_get_supported_formats_json() -> *mut c_char {
    std::panic::catch_unwind(|| c_message(&infra::registry::supported_formats_json()))
        .unwrap_or_else(|_| c_message("{}"))
}

#[no_mangle]
pub extern "C" fn native_get_available_hwaccels_json() -> *mut c_char {
    std::panic::catch_unwind(|| {
        let hwaccels = available_hwaccels_from_ffmpeg();
        let json = serde_json::to_string(&hwaccels).unwrap_or_else(|_| "[]".to_string());
        c_message(&json)
    })
    .unwrap_or_else(|_| std::process::abort())
}

#[no_mangle]
pub extern "C" fn native_set_max_concurrent_hw_video_decodes(max_slots: usize) -> c_int {
    std::panic::catch_unwind(|| {
        MAX_CONCURRENT_HW_VIDEO_DECODE_LIMIT.store(max_slots.max(1), Ordering::Release);
        STATUS_OK
    })
    .unwrap_or_else(|_| std::process::abort())
}

#[no_mangle]
pub extern "C" fn native_set_cache_limit(max_bytes: usize) -> c_int {
    std::panic::catch_unwind(|| {
        let mut engine = match ENGINE.lock() {
            Ok(g) => g,
            Err(_) => return STATUS_INTERNAL,
        };
        engine.set_cache_limit(max_bytes);
        STATUS_OK
    })
    .unwrap_or_else(|_| std::process::abort())
}

#[no_mangle]
pub extern "C" fn native_clear_cache() -> c_int {
    std::panic::catch_unwind(|| {
        let mut engine = match ENGINE.lock() {
            Ok(g) => g,
            Err(_) => return STATUS_INTERNAL,
        };
        engine.clear_cache();
        STATUS_OK
    })
    .unwrap_or_else(|_| std::process::abort())
}

#[no_mangle]
pub extern "C" fn native_free_buffer(data: *mut u8, len: usize) {
    std::panic::catch_unwind(|| {
        if data.is_null() || len == 0 {
            return;
        }
        unsafe {
            let _ = Vec::from_raw_parts(data, len, len);
        }
    })
    .unwrap_or_else(|_| std::process::abort())
}

#[no_mangle]
pub extern "C" fn native_free_message(msg: *mut c_char) {
    std::panic::catch_unwind(|| {
        if msg.is_null() {
            return;
        }
        unsafe {
            let _ = CString::from_raw(msg);
        }
    })
    .unwrap_or_else(|_| std::process::abort())
}

#[no_mangle]
pub extern "C" fn native_free_result(result: *mut NativeThumbnailResult) {
    std::panic::catch_unwind(|| {
        if result.is_null() {
            return;
        }
        unsafe {
            let r = &mut *result;
            if !r.data.is_null() && r.len > 0 {
                native_free_buffer(r.data, r.len);
                r.data = std::ptr::null_mut();
                r.len = 0;
            }
            if !r.message.is_null() {
                native_free_message(r.message);
                r.message = std::ptr::null_mut();
            }
        }
    })
    .unwrap_or_else(|_| std::process::abort())
}

#[no_mangle]
pub extern "C" fn native_free_batch_result(batch: *mut NativeThumbnailBatchResult) {
    std::panic::catch_unwind(|| {
        if batch.is_null() {
            return;
        }
        unsafe {
            let b = &mut *batch;
            if !b.results.is_null() && b.count > 0 {
                let results = Vec::from_raw_parts(b.results, b.count, b.count);
                for r in results {
                    if !r.data.is_null() && r.len > 0 {
                        native_free_buffer(r.data, r.len);
                    }
                    if !r.message.is_null() {
                        native_free_message(r.message);
                    }
                }
                b.results = std::ptr::null_mut();
                b.count = 0;
            }
            if !b.message.is_null() {
                native_free_message(b.message);
                b.message = std::ptr::null_mut();
            }
        }
    })
    .unwrap_or_else(|_| std::process::abort())
}

// todo 23：ffmpeg/ffprobe 能力表查询导出（实测能力矩阵驱动 T2 管线）。
// 查询型导出沿 todo 5/7 约定：panic 时降级返回 "{}" 而非 abort。
#[no_mangle]
pub extern "C" fn native_get_ffmpeg_capabilities_json() -> *mut c_char {
    std::panic::catch_unwind(|| c_message(&t2::ffmpeg_capability::capabilities_json()))
        .unwrap_or_else(|_| c_message("{}"))
}

#[cfg(test)]
mod lzw_wiring_tests {
    //! Design Revision 5 验证：image 0.25.10 内建 GIF（gif crate）与 TIFF
    //! （tiff crate → weezl 纯 Rust）覆盖 LZW 两变体（GIF LSB / TIFF MSB）。
    //! 本测试不实现任何 LZW 算法，仅验证经 image 解码 LZW 压缩样本成功且尺寸合理。

    /// 4x4 RGB GIF（LZW 压缩，gif crate 解码），PIL 确定性生成。
    const GIF_4X4_LZW: &[u8] = &[
        71, 73, 70, 56, 55, 97, 4, 0, 4, 0, 129, 0, 0, 255, 255, 0, 0, 255, 0, 255, 0, 0, 0, 0,
        255, 44, 0, 0, 0, 0, 4, 0, 4, 0, 0, 8, 14, 0, 5, 4, 24, 0, 64, 32, 65, 131, 5, 7, 2, 8, 8, 0,
        59,
    ];

    /// 4x4 RGB TIFF（little-endian, Compression=5 LZW，tiff crate → weezl 解码），PIL 确定性生成。
    const TIFF_4X4_LZW: &[u8] = &[
        73, 73, 42, 0, 34, 0, 0, 0, 128, 63, 192, 16, 56, 20, 17, 255, 2, 130, 128, 33, 48, 120, 68,
        14, 21, 14, 134, 67, 224, 145, 8, 56, 2, 2, 10, 0, 0, 1, 3, 0, 1, 0, 0, 0, 4, 0, 0, 0, 1, 1,
        3, 0, 1, 0, 0, 0, 4, 0, 0, 0, 2, 1, 3, 0, 3, 0, 0, 0, 160, 0, 0, 0, 3, 1, 3, 0, 1, 0, 0, 0,
        5, 0, 0, 0, 6, 1, 3, 0, 1, 0, 0, 0, 2, 0, 0, 0, 17, 1, 4, 0, 1, 0, 0, 0, 8, 0, 0, 0, 21, 1,
        3, 0, 1, 0, 0, 0, 3, 0, 0, 0, 22, 1, 3, 0, 1, 0, 0, 0, 4, 0, 0, 0, 23, 1, 4, 0, 1, 0, 0, 0,
        26, 0, 0, 0, 28, 1, 3, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 8, 0, 8, 0, 8, 0,
    ];

    #[test]
    fn lzw_gif_and_tiff_samples_decode_via_image_crate() {
        let gif = image::load_from_memory(GIF_4X4_LZW).expect("GIF LZW 样本应解码成功");
        assert_eq!((gif.width(), gif.height()), (4, 4), "GIF 尺寸应为 4x4");

        let tiff = image::load_from_memory(TIFF_4X4_LZW).expect("TIFF LZW 样本应解码成功");
        assert_eq!((tiff.width(), tiff.height()), (4, 4), "TIFF 尺寸应为 4x4");

        // 像素数据完整输出（RGBA8），证明 LZW 解码两变体链路均可用。
        assert_eq!(gif.to_rgba8().pixels().count(), 16);
        assert_eq!(tiff.to_rgba8().pixels().count(), 16);
    }
}
