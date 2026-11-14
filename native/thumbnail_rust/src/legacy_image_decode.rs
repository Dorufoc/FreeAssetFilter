//! image crate 回退解码路径（todo 26 移除本模块）。
//!
//! **to be removed in todo 26**：本模块保留 image crate 作为 T1 解码器上线前
//! 的回退，保证行为零回归。todo 26（`Cargo.toml [dependencies]` 置空）时删除
//! 本文件及 lib.rs 中对 `decode_with_image_crate` / `decode_image_bytes_to_rgba`
//! 的调用并改走新解码器/T2/T3。
//!
//! 本文件为 todo 1 从原 `lib.rs` 原样搬迁的过渡容器：`decode_with_image_crate`
//! 与 `decode_image_bytes_to_rgba` 逻辑一字未改（含 image crate 与错误码 i32
//! 的使用）。todo 7 的 `infra/registry.rs` 与 todo 24 的 `t2/t2_ffmpeg.rs`
//! 均引用本模块作为回退接线。

use crate::STATUS_DECODE_FAILED;

/// 以 image crate 打开路径图像、缩放至目标尺寸并转为 RGBA8。
///
/// 原出自 `lib.rs`（todo 1 抽取搬迁，逻辑未改）；todo 26 随 image crate 一并移除。
pub(crate) fn decode_with_image_crate(
    path: &str,
    width: u32,
    height: u32,
) -> Result<(Vec<u8>, u32, u32), i32> {
    let input = image::open(path).map_err(|_| STATUS_DECODE_FAILED)?;
    let resized = input.thumbnail(width, height).to_rgba8();
    let rw = resized.width();
    let rh = resized.height();
    Ok((resized.into_raw(), rw, rh))
}

/// 以 image crate 从内存字节解码为 RGBA8（不缩放）。
///
/// 原出自 `lib.rs`（todo 1 抽取搬迁，逻辑未改）；todo 26 随 image crate 一并移除，
/// 届时视频 MJPEG 输出改经 `decoders/jpeg.rs` 解码。
pub(crate) fn decode_image_bytes_to_rgba(bytes: &[u8]) -> Result<(Vec<u8>, u32, u32), i32> {
    let input = image::load_from_memory(bytes).map_err(|_| STATUS_DECODE_FAILED)?;
    let rgba = input.to_rgba8();
    let rw = rgba.width();
    let rh = rgba.height();
    Ok((rgba.into_raw(), rw, rh))
}