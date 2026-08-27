use once_cell::sync::Lazy;
use rayon::prelude::*;
use std::collections::{HashMap, VecDeque};
use std::env;
use std::ffi::{CStr, CString};
use std::fs;
use std::os::raw::{c_char, c_int};
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
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
use legacy_image_decode::decode_with_image_crate;
// todo 24：ffmpeg 视频管线已整体搬迁至 t2/t2_ffmpeg.rs，本文件仅保留薄调用层。
use t2::t2_ffmpeg::{
    available_hwaccels_from_ffmpeg, decode_stats_to_json, decode_video_with_ffmpeg,
    extract_best_video_frame_jpeg_bytes, is_video_ext, reset_decode_stats,
    set_max_concurrent_hw_video_decodes,
};
// todo 25：T3 兜底通道——扩展名跳过清单路由与解码失败 errorlog 统一补录。
use t3::skip::{
    is_t3_skip_path, path_format, record_decode_failure, skip_with_status, T3_SKIP_MESSAGE,
};

const DEFAULT_MAX_MEMORY_BYTES: usize = 200 * 1024 * 1024;
const DEFAULT_K: usize = 2;

const STATUS_OK: i32 = 0;
const STATUS_INVALID_ARG: i32 = -1;
pub(crate) const STATUS_DECODE_FAILED: i32 = -2;
const STATUS_OOM: i32 = -3;
const STATUS_NOT_FOUND: i32 = -4;
const STATUS_INTERNAL: i32 = -5;
// todo 25 已接线消费：-6 由 T3 扩展名清单路由返回、-2/-6/-7 失败补录经
// t3::skip 引用；与 STATUS_OOM=-3 区分路由（-3 低内存交 Python 回退，-7 仅
// 维度超限），见 plan todo 27 路由表。
pub(crate) const STATUS_UNSUPPORTED: i32 = -6;
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

// todo 24：`VideoProbeInfo` / `DecodeStats` / `FrameExtractResult` /
// `HwDecodePermit` 与 ffmpeg 编排函数群已整体迁至 `t2::t2_ffmpeg`。

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

// todo 24：ffprobe 时长探测 / seek 候选 / HW 命中判定 / MJPEG 抽帧编排
// （`run_ffprobe_basic_info`、`clamp_seek_time`、`build_seek_candidates`、
// `ffmpeg_log_indicates_hw_hit`、`scale_filter`、`try_extract_frame_with_ffmpeg`、
// `extract_best_video_frame_jpeg`、`decode_video_with_ffmpeg`）已整体迁至
// `t2::t2_ffmpeg`，本文件仅经薄调用层（顶部 use）使用。

/// AVIF 系能力门控图像容器：bundled ffmpeg 最小构建无对应 demuxer 时，
/// 既不能走 T2，也没有 T1 解码器——按 todo 25 通则快速 -6 交 Python 回退链。
const CAPABILITY_GATED_IMAGE_EXTS: &[&str] = &["avif", "heic", "heif", "jp2"];

/// 注册表魔数嗅探 → T1 解码器主路径（Design Revision 6：legacy image crate 兜底）。
///
/// 返回 `None` 表示未命中注册表（调用方落 legacy 兜底）；`Some(Ok)` 为 T1 成功；
/// `Some(Err(-7))` 为维度超限权威判定（不兜底直接透传）；其余 Err 已尝试过
/// legacy 兜底（兜底成功则已被替换为 Ok）。
/// 与 image 0.25 `math::utils::resize_dimensions` 逐字同语义（该函数为
/// `pub(crate)` 无法外部调用，故本地复刻；fill=false 即 legacy
/// `image::thumbnail` 的保比例、不放大目标框算法）。
fn resize_dimensions(
    width: u32,
    height: u32,
    nwidth: u32,
    nheight: u32,
    fill: bool,
) -> (u32, u32) {
    let wratio = f64::from(nwidth) / f64::from(width);
    let hratio = f64::from(nheight) / f64::from(height);

    let ratio = if fill {
        f64::max(wratio, hratio)
    } else {
        // 与 legacy `image::thumbnail` 一致：保比例模式下永不放大（钳制到 ≤1.0）。
        // 历史 bug：64x48@128 曾因 ratio 未封顶输出 128x96 维度，而
        // box_resize_rgba 按自身契约截断到源尺寸输出 64x48 数据，
        // 维度与数据长度错配导致下游 JPEG 编码 -5 / PIL frombytes 崩溃。
        f64::min(wratio, hratio).min(1.0)
    };

    let nw = std::cmp::max((f64::from(width) * ratio).round() as u64, 1);
    let nh = std::cmp::max((f64::from(height) * ratio).round() as u64, 1);

    if nw > u64::from(u32::MAX) {
        let ratio = f64::from(u32::MAX) / f64::from(width);
        (
            u32::MAX,
            std::cmp::max((f64::from(height) * ratio).round() as u32, 1),
        )
    } else if nh > u64::from(u32::MAX) {
        let ratio = f64::from(u32::MAX) / f64::from(height);
        (
            std::cmp::max((f64::from(width) * ratio).round() as u32, 1),
            u32::MAX,
        )
    } else {
        (nw as u32, nh as u32)
    }
}

fn decode_via_t1(
    path: &str,
    width: u32,
    height: u32,
) -> Option<Result<(Vec<u8>, u32, u32), i32>> {
    use infra::registry::{sniff_format, FormatId};

    let fmt = sniff_format(path)?;
    let bytes = fs::read(path).ok()?;

    let t1 = match fmt {
        FormatId::Pnm => decoders::pnm::decode_pnm(&bytes),
        FormatId::Qoi => decoders::qoi::decode_qoi(&bytes),
        FormatId::Bmp => decoders::bmp::decode_bmp(&bytes),
        FormatId::Tga => decoders::tga::decode_tga(&bytes),
        FormatId::Ico => decoders::ico::decode_ico(&bytes),
        FormatId::Gif => decoders::gif::decode_gif(&bytes),
        FormatId::Png => decoders::png::decode_png(&bytes),
        FormatId::Jpeg => decoders::jpeg::decode_jpeg(&bytes),
        FormatId::Tiff => decoders::tiff::decode_tiff(&bytes),
        FormatId::Webp => decoders::webp::decode_webp(&bytes),
        FormatId::Vp8 => decoders::vp8::decode_vp8(&bytes),
        FormatId::Psd => decoders::psd::decode_psd(&bytes),
        FormatId::Dds => decoders::dds::decode_dds(&bytes),
        FormatId::Icns => decoders::icns::decode_icns(&bytes),
    };

    Some(match t1 {
        Ok((data, sw, sh)) => {
            // 与 legacy `image::thumbnail` 同一目标尺寸算法
            // （保比例、不放大）；像素用 todo 6 的 box_resize_rgba（面积平均，
            // 与 image crate 抽样差值已验收 ≤3/255）。
            let (dw, dh) =
                resize_dimensions(sw, sh, width, height, false);
            match infra::resize::box_resize_rgba(&data, sw, sh, dw, dh) {
                Some(resized) => {
                    // 长度守卫：box_resize_rgba 契约为「不放大」（请求维超过源时
                    // 截断到源尺寸），输出长度必须与 (dw, dh) 严格一致；不一致
                    // 说明上游给出了放大的目标尺寸，此时退回原图数据 + 原始
                    // 尺寸保持维度自洽（否则 CacheEntry 的 len≠w*h*4 会让下游
                    // JPEG 编码误报 -5 / Python frombytes 崩溃）。
                    let expected_bytes = u64::from(dw)
                        .checked_mul(u64::from(dh))
                        .and_then(|px| px.checked_mul(4));
                    if expected_bytes == Some(resized.len() as u64) {
                        Ok((resized, dw, dh))
                    } else {
                        Ok((data, sw, sh))
                    }
                }
                // resize 拒绝（异常维度）时退回原图数据，保持可用性
                None => Ok((data, sw, sh)),
            }
        }
        Err(STATUS_TOO_LARGE) => Err(STATUS_TOO_LARGE),
        Err(_) => decode_with_image_crate(path, width, height),
    })
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

    // todo 25：T3 扩展名路由先于解码分发——RAW 系多为 TIFF 魔数，若走魔数
    // 嗅探会误入 TIFF 解码器；命中清单即记录 errorlog 并快速返回 UNSUPPORTED。
    if is_t3_skip_path(path) {
        return Err(skip_with_status(
            path,
            &path_format(path),
            STATUS_UNSUPPORTED,
            T3_SKIP_MESSAGE,
        ));
    }

    // AVIF 系能力门控容器：ffmpeg 无 demuxer 且无 T1 解码器 → 快速 -6 交 Python 回退链。
    let ext_lower = path
        .rsplit('.')
        .next()
        .map(str::to_ascii_lowercase)
        .unwrap_or_default();
    if !is_video_ext(path) && CAPABILITY_GATED_IMAGE_EXTS.contains(&ext_lower.as_str()) {
        return Err(skip_with_status(
            path,
            &path_format(path),
            STATUS_UNSUPPORTED,
            "capability-gated image container unsupported by bundled ffmpeg",
        ));
    }

    let decoded = if is_video_ext(path) {
        decode_video_with_ffmpeg(path, width, height)
    } else if let Some(t1) = decode_via_t1(path, width, height) {
        t1
    } else {
        decode_with_image_crate(path, width, height)
    };

    let (data, w, h) = match decoded {
        Ok(out) => out,
        // todo 25：解码失败路径（-2/-6/-7）统一补录 errorlog 后原样透传；
        // dds-bc7/icns-jp2 等解码器内部的 -6 接线后也经此进入日志。
        Err(code) => {
            record_decode_failure(path, code);
            return Err(code);
        }
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
        // todo 25：视频 JPEG 抽帧分支不经 generate_entry，失败同样补录 errorlog。
        return match extract_best_video_frame_jpeg_bytes(path, width, height) {
            Ok(bytes) => Ok(bytes),
            Err(code) => {
                record_decode_failure(path, code);
                Err(code)
            }
        };
    }

    let entry = generate_entry(path, width, height)?;
    encode_jpeg_bytes(&entry)
}

static ENGINE: Lazy<Mutex<NativeEngine>> = Lazy::new(|| Mutex::new(NativeEngine::new()));
// todo 24：`DECODE_STATS` / `HW_VIDEO_DECODE_SLOTS` /
// `MAX_CONCURRENT_HW_VIDEO_DECODE_LIMIT` 已迁至 `t2::t2_ffmpeg`（与编排逻辑同址）。

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

fn encode_jpeg_bytes(entry: &CacheEntry) -> Result<Vec<u8>, i32> {
    // todo 16：自研基线 JPEG 编码器（4:4:4 / BT.601 / 定点 FDCT / Q90）。
    // 内部完成 alpha 预乘白底合成（等价原 `rgba_to_jpeg_rgb`），故不再单独合成。
    encoders::jpeg_encoder::encode_jpeg_rgba(&entry.data, entry.width, entry.height, 90)
        .map_err(|_| STATUS_INTERNAL)
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
    std::panic::catch_unwind(|| c_message(&decode_stats_to_json()))
        .unwrap_or_else(|_| std::process::abort())
}

#[no_mangle]
pub extern "C" fn native_reset_decode_stats() -> c_int {
    std::panic::catch_unwind(|| {
        if reset_decode_stats() {
            STATUS_OK
        } else {
            STATUS_INTERNAL
        }
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
        set_max_concurrent_hw_video_decodes(max_slots);
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
