use image::codecs::jpeg::JpegEncoder;
use image::{ColorType, ImageEncoder};
use once_cell::sync::Lazy;
use rayon::prelude::*;
use std::collections::{HashMap, HashSet, VecDeque};
use std::ffi::{CStr, CString};
use std::fs;
use std::os::raw::{c_char, c_int};
use std::path::Path;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};
use sysinfo::System;

use opencv::core::{AlgorithmHint, Mat, Size, Vector};
use opencv::imgproc;
use opencv::prelude::*;
use opencv::videoio::{
    self, VideoCapture, CAP_FFMPEG, CAP_INTEL_MFX, CAP_MSMF, CAP_PROP_FRAME_COUNT,
    CAP_PROP_HW_ACCELERATION, CAP_PROP_HW_ACCELERATION_USE_OPENCL, CAP_PROP_HW_DEVICE,
    CAP_PROP_N_THREADS, CAP_PROP_POS_FRAMES, VIDEO_ACCELERATION_ANY,
    VIDEO_ACCELERATION_D3D11, VIDEO_ACCELERATION_MFX,
};

const DEFAULT_MAX_MEMORY_BYTES: usize = 200 * 1024 * 1024;
const DEFAULT_K: usize = 2;

const STATUS_OK: i32 = 0;
const STATUS_INVALID_ARG: i32 = -1;
const STATUS_DECODE_FAILED: i32 = -2;
const STATUS_OOM: i32 = -3;
const STATUS_NOT_FOUND: i32 = -4;
const STATUS_INTERNAL: i32 = -5;

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

fn decode_with_image_crate(path: &str, width: u32, height: u32) -> Result<(Vec<u8>, u32, u32), i32> {
    let input = image::open(path).map_err(|_| STATUS_DECODE_FAILED)?;
    let resized = input.thumbnail(width, height).to_rgba8();
    let rw = resized.width();
    let rh = resized.height();

    Ok((resized.into_raw(), rw, rh))
}

fn read_frame_at(cap: &mut VideoCapture, frame_index_1based: i64) -> Option<Mat> {
    let target_index = frame_index_1based.saturating_sub(1).max(0) as f64;
    if cap.set(CAP_PROP_POS_FRAMES, target_index).is_err() {
        return None;
    }
    let mut frame = Mat::default();
    if cap.read(&mut frame).ok()? && !frame.empty() {
        return Some(frame);
    }
    None
}

fn build_probe_positions(total_frames: i64, probe_count: usize) -> Vec<i64> {
    if total_frames <= 1 {
        return vec![0];
    }
    if probe_count <= 1 {
        return vec![0, total_frames - 1];
    }

    let mut positions = Vec::with_capacity(probe_count + 2);
    positions.push(0);

    for i in 0..probe_count {
        let p = ((i as f64) * ((total_frames - 1) as f64) / ((probe_count - 1) as f64)).round() as i64;
        positions.push(p.clamp(0, total_frames - 1));
    }

    positions.push(total_frames - 1);
    positions.sort_unstable();
    positions.dedup();
    positions
}

fn extract_nth_keyframe_by_seek(cap: &mut VideoCapture, nth: usize, total_frames: i64) -> Option<Mat> {
    if nth == 0 || total_frames <= 0 {
        return None;
    }

    let mut seen = HashSet::new();
    let mut found_count = 0usize;

    // 第一轮：稀疏探测，尽量减少 seek+decode 次数
    for pos in build_probe_positions(total_frames, 48) {
        if cap.set(CAP_PROP_POS_FRAMES, pos as f64).is_err() {
            continue;
        }

        let mut frame = Mat::default();
        let ok = cap.read(&mut frame).ok().unwrap_or(false);
        if !ok || frame.empty() {
            continue;
        }

        // 多数后端 seek 到最近关键帧，这里用“实际落点”作为关键帧去重标识
        let mut landed = cap.get(CAP_PROP_POS_FRAMES).ok().unwrap_or(pos as f64 + 1.0) as i64 - 1;
        if landed < 0 {
            landed = pos;
        }

        if seen.insert(landed) {
            found_count += 1;
            if found_count == nth {
                return Some(frame);
            }
        }
    }

    // 第二轮：加密探测，提高低关键帧密度视频命中率
    for pos in build_probe_positions(total_frames, 160) {
        if cap.set(CAP_PROP_POS_FRAMES, pos as f64).is_err() {
            continue;
        }

        let mut frame = Mat::default();
        let ok = cap.read(&mut frame).ok().unwrap_or(false);
        if !ok || frame.empty() {
            continue;
        }

        let mut landed = cap.get(CAP_PROP_POS_FRAMES).ok().unwrap_or(pos as f64 + 1.0) as i64 - 1;
        if landed < 0 {
            landed = pos;
        }

        if seen.insert(landed) {
            found_count += 1;
            if found_count == nth {
                return Some(frame);
            }
        }
    }

    None
}

fn compose_rgba_canvas_from_bgr_frame(frame: &Mat, target_w: u32, target_h: u32) -> Result<(Vec<u8>, u32, u32), i32> {
    if target_w == 0 || target_h == 0 {
        return Err(STATUS_INVALID_ARG);
    }

    let src_w = frame.cols().max(0) as u32;
    let src_h = frame.rows().max(0) as u32;
    if src_w == 0 || src_h == 0 {
        return Err(STATUS_DECODE_FAILED);
    }

    let scale = f64::min(target_w as f64 / src_w as f64, target_h as f64 / src_h as f64);
    let resize_w = ((src_w as f64 * scale).round() as i32).max(1);
    let resize_h = ((src_h as f64 * scale).round() as i32).max(1);

    let mut resized = Mat::default();
    imgproc::resize(
        frame,
        &mut resized,
        Size::new(resize_w, resize_h),
        0.0,
        0.0,
        imgproc::INTER_AREA,
    )
    .map_err(|_| STATUS_DECODE_FAILED)?;

    let mut rgba = Mat::default();
    let ch = resized.channels();
    let code = if ch == 4 {
        imgproc::COLOR_BGRA2RGBA
    } else if ch == 1 {
        imgproc::COLOR_GRAY2RGBA
    } else {
        imgproc::COLOR_BGR2RGBA
    };

    imgproc::cvt_color(&resized, &mut rgba, code, 0, AlgorithmHint::ALGO_HINT_DEFAULT)
        .map_err(|_| STATUS_DECODE_FAILED)?;

    let bytes = rgba.data_bytes().map_err(|_| STATUS_DECODE_FAILED)?.to_vec();
    let resized_rgba =
        image::RgbaImage::from_raw(resize_w as u32, resize_h as u32, bytes).ok_or(STATUS_DECODE_FAILED)?;

    Ok((resized_rgba.into_raw(), resize_w as u32, resize_h as u32))
}

fn make_hw_capture_params(accel_type: i32, device_index: i32, enable_opencl: bool) -> Vector<i32> {
    let mut params = Vector::<i32>::new();
    params.push(CAP_PROP_HW_ACCELERATION);
    params.push(accel_type);
    params.push(CAP_PROP_HW_DEVICE);
    params.push(device_index);
    params.push(CAP_PROP_HW_ACCELERATION_USE_OPENCL);
    params.push(if enable_opencl { 1 } else { 0 });
    // FFmpeg 后端可额外显式允许其内部线程策略
    params.push(CAP_PROP_N_THREADS);
    params.push(0);
    params
}

fn try_open_with_backend(path: &str, backend: i32, accel_type: i32, enable_opencl: bool) -> Option<VideoCapture> {
    let params = make_hw_capture_params(accel_type, 0, enable_opencl);
    if let Ok(cap) = VideoCapture::from_file_with_params(path, backend, &params) {
        if cap.is_opened().ok().unwrap_or(false) {
            return Some(cap);
        }
    }
    None
}

fn open_video_capture(path: &str) -> Result<VideoCapture, i32> {
    // Windows 上优先尝试更明确的 GPU 路径：
    // 1. MSMF + D3D11
    if let Some(cap) = try_open_with_backend(path, CAP_MSMF, VIDEO_ACCELERATION_D3D11, true) {
        return Ok(cap);
    }

    // 2. FFmpeg + D3D11
    if let Some(cap) = try_open_with_backend(path, CAP_FFMPEG, VIDEO_ACCELERATION_D3D11, true) {
        return Ok(cap);
    }

    // 3. Intel MFX / oneVPL
    if let Some(cap) = try_open_with_backend(path, CAP_INTEL_MFX, VIDEO_ACCELERATION_MFX, false) {
        return Ok(cap);
    }

    // 4. 任意后端 + ANY
    if let Some(cap) = try_open_with_backend(path, videoio::CAP_ANY, VIDEO_ACCELERATION_ANY, true) {
        return Ok(cap);
    }

    // 5. FFmpeg + ANY
    if let Some(cap) = try_open_with_backend(path, CAP_FFMPEG, VIDEO_ACCELERATION_ANY, true) {
        return Ok(cap);
    }

    // 6. 最终回退到普通打开（软件解码）
    let cap = VideoCapture::from_file(path, videoio::CAP_ANY).map_err(|_| STATUS_DECODE_FAILED)?;
    if cap.is_opened().map_err(|_| STATUS_DECODE_FAILED)? {
        Ok(cap)
    } else {
        Err(STATUS_DECODE_FAILED)
    }
}

fn decode_video_with_opencv(path: &str, width: u32, height: u32) -> Result<(Vec<u8>, u32, u32), i32> {
    let mut cap = open_video_capture(path)?;

    let total_frames = cap
        .get(CAP_PROP_FRAME_COUNT)
        .ok()
        .map(|v| v.max(0.0).round() as i64)
        .unwrap_or(0);

    // 按要求的降级顺序：第4关键帧 -> 第3关键帧 -> 第1关键帧 -> 第10普通帧
    let frame = extract_nth_keyframe_by_seek(&mut cap, 4, total_frames)
        .or_else(|| extract_nth_keyframe_by_seek(&mut cap, 3, total_frames))
        .or_else(|| extract_nth_keyframe_by_seek(&mut cap, 1, total_frames))
        .or_else(|| read_frame_at(&mut cap, 10))
        .ok_or(STATUS_DECODE_FAILED)?;

    compose_rgba_canvas_from_bgr_frame(&frame, width, height)
}

fn is_video_ext(path: &str) -> bool {
    let ext = Path::new(path)
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    matches!(
        ext.as_str(),
        "mp4" | "mov" | "mkv" | "flv" | "3gp" | "mxf" | "avi" | "webm" | "wmv" | "mpg" | "mpeg" | "m4v"
    )
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
        decode_video_with_opencv(path, width, height)?
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

    // 双检：避免并发重复计算后的覆盖写入
    if let Some(entry) = engine.get(&key) {
        return Ok(entry);
    }

    engine.put(key, candidate.clone());
    Ok(candidate)
}

static ENGINE: Lazy<Mutex<NativeEngine>> = Lazy::new(|| Mutex::new(NativeEngine::new()));

fn c_message(msg: &str) -> *mut c_char {
    CString::new(msg).unwrap_or_else(|_| CString::new("invalid message").unwrap()).into_raw()
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

fn make_jpeg_result_from_entry(entry: CacheEntry) -> NativeThumbnailResult {
    let jpeg_buf = match encode_jpeg_bytes(&entry) {
        Ok(b) => b,
        Err(_) => return make_error_result(STATUS_INTERNAL, "jpeg encode failed"),
    };

    let mut boxed = jpeg_buf.into_boxed_slice();
    let len = boxed.len();
    let ptr = boxed.as_mut_ptr();
    std::mem::forget(boxed);

    NativeThumbnailResult {
        status: STATUS_OK,
        width: entry.width,
        height: entry.height,
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

    fn ok_jpeg_from_entry(entry: CacheEntry) -> Self {
        let width = entry.width;
        let height = entry.height;
        let channels = 3;
        match encode_jpeg_bytes(&entry) {
            Ok(data) => Self {
                status: STATUS_OK,
                width,
                height,
                channels,
                data,
                message: "ok".to_string(),
            },
            Err(_) => Self::err(STATUS_INTERNAL, "jpeg encode failed"),
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
pub extern "C" fn native_generate_thumbnail(path: *const c_char, width: c_int, height: c_int) -> NativeThumbnailResult {
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
}

#[no_mangle]
pub extern "C" fn native_generate_thumbnail_jpeg(path: *const c_char, width: c_int, height: c_int) -> NativeThumbnailResult {
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
        Ok(entry) => make_jpeg_result_from_entry(entry),
        Err(code) => make_error_result(code, "generate failed"),
    }
}

#[no_mangle]
pub extern "C" fn native_generate_thumbnail_jpg(path: *const c_char, width: c_int, height: c_int) -> NativeThumbnailResult {
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
        Ok(entry) => make_jpeg_result_from_entry(entry),
        Err(code) => make_error_result(code, "generate failed"),
    }
}

#[no_mangle]
pub extern "C" fn native_generate_batch(
    paths: *const *const c_char,
    count: c_int,
    width: c_int,
    height: c_int,
) -> NativeThumbnailBatchResult {
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
}

#[no_mangle]
pub extern "C" fn native_generate_batch_jpg(
    paths: *const *const c_char,
    count: c_int,
    width: c_int,
    height: c_int,
) -> NativeThumbnailBatchResult {
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
                Ok(entry) => ParallelBatchItem::ok_jpeg_from_entry(entry),
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
}

#[no_mangle]
pub extern "C" fn native_set_cache_limit(max_bytes: usize) -> c_int {
    let mut engine = match ENGINE.lock() {
        Ok(g) => g,
        Err(_) => return STATUS_INTERNAL,
    };
    engine.set_cache_limit(max_bytes);
    STATUS_OK
}

#[no_mangle]
pub extern "C" fn native_clear_cache() -> c_int {
    let mut engine = match ENGINE.lock() {
        Ok(g) => g,
        Err(_) => return STATUS_INTERNAL,
    };
    engine.clear_cache();
    STATUS_OK
}

#[no_mangle]
pub extern "C" fn native_free_buffer(data: *mut u8, len: usize) {
    if data.is_null() || len == 0 {
        return;
    }
    unsafe {
        let _ = Vec::from_raw_parts(data, len, len);
    }
}

#[no_mangle]
pub extern "C" fn native_free_message(msg: *mut c_char) {
    if msg.is_null() {
        return;
    }
    unsafe {
        let _ = CString::from_raw(msg);
    }
}

#[no_mangle]
pub extern "C" fn native_free_result(result: *mut NativeThumbnailResult) {
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
}

#[no_mangle]
pub extern "C" fn native_free_batch_result(batch: *mut NativeThumbnailBatchResult) {
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
}
