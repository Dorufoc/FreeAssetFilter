//! JPEG 编码封装（todo 16，Design Revision 6 重写）。
//!
//! 职责：RGBA8 → 白底 alpha 预乘合成 → RGB8 → 委托 image crate 内建
//! `image::codecs::jpeg::JpegEncoder` 输出基线 JPEG，供 Python 侧缓存与
//! 写盘。质量参数对齐 `thumbnail_manager.py`（QUAY=85 → 质量 90 常量）。
//!
//! DR6 裁决（2026-08-21）：「积极复用开源项目，避免闭门造车」。上一版自研
//! BT.601/FDCT/Huffman/BitWriter/DQT 全管线（约 800 行）因 DQT 未按 ZigZag
//! 序写出存在 round-trip 缺陷，整体删除改为委托 image crate——编码正确性、
//! 任意尺寸处理（无需 8 倍数边缘填充）与产物兼容性均由上游保证。

// 错误码：模块内字面量，与 lib.rs STATUS_INVALID_ARG=-1 / STATUS_INTERNAL=-5
// 数值一致（lib.rs 常量非 pub(crate)，编码器模块内不自引用 lib.rs 私有项）。
/// 非法参数：空输入 / 零尺寸 / 宽高 < 8 / 缓冲长度与尺寸不匹配。
const STATUS_INVALID_ARG: i32 = -1;
/// 内部错误：image crate JpegEncoder 编码失败。
const STATUS_INTERNAL: i32 = -5;

/// 最小编码尺寸：宽/高任一小于此值返回 `Err(STATUS_INVALID_ARG)`。
///
/// image crate 本身可编码任意尺寸；此守卫是上游业务契约——「过小输入返回
/// 错误」以避免异常尺寸混入缓存路径，保留语义不变。
const MIN_DIM: u32 = 8;

/// RGBA8 白底 alpha 预乘合成（语义同原 `lib.rs::rgba_to_jpeg_rgb`）：
/// `out = (v·a + 255·(255-a) + 127) / 255`。输入长度须恰为 `width·height·4`。
fn blend_rgba_to_rgb(rgba: &[u8], width: usize, height: usize) -> Vec<u8> {
    let mut rgb = Vec::with_capacity(width * height * 3);
    for px in rgba.chunks_exact(4) {
        let (r, g, b, a) = (
            u32::from(px[0]),
            u32::from(px[1]),
            u32::from(px[2]),
            u32::from(px[3]),
        );
        let inv = 255 - a;
        rgb.push(((r * a + 255 * inv + 127) / 255) as u8);
        rgb.push(((g * a + 255 * inv + 127) / 255) as u8);
        rgb.push(((b * a + 255 * inv + 127) / 255) as u8);
    }
    rgb
}

/// RGBA8 → 基线 JPEG 编码（白底合成 + image crate `JpegEncoder` 委托）。
///
/// # 参数
/// - `rgba`：RGBA8 扁平数组（`width·height·4` 字节，行优先；超长缓冲的
///   尾部按契约忽略）。
/// - `width`/`height`：图像尺寸；任一 < 8 返回 `Err(STATUS_INVALID_ARG)`。
/// - `quality`：质量 1..=100（越界自动钳位）；调用方传 90。
///
/// # 返回
/// - `Ok(完整 JPEG 字节)`：以 SOI `FF D8` 开头、EOI `FF D9` 结尾，可被
///   `decoders::jpeg::decode_jpeg` / PIL / image crate 解码。
/// - `Err(STATUS_INVALID_ARG=-1)`：空输入、零尺寸、宽或高 < 8、缓冲长度
///   与尺寸不匹配。
/// - `Err(STATUS_INTERNAL=-5)`：image crate 编码失败。
///
/// # 错误不变量
/// 任何输入都不会 panic。任意宽高（含非 8 倍数）由 image crate 自行处理，
/// 无需边缘填充。
pub fn encode_jpeg_rgba(rgba: &[u8], width: u32, height: u32, quality: u8) -> Result<Vec<u8>, i32> {
    if width < MIN_DIM || height < MIN_DIM {
        return Err(STATUS_INVALID_ARG);
    }
    let expected = usize::try_from(width)
        .ok()
        .and_then(|w| usize::try_from(height).ok().map(|h| (w, h)))
        .and_then(|(w, h)| w.checked_mul(h))
        .and_then(|p| p.checked_mul(4));
    let n = match expected {
        Some(n) if rgba.len() >= n => n,
        _ => return Err(STATUS_INVALID_ARG),
    };

    // 白底 alpha 预乘合成（仅取前 n 字节）。
    let rgb = blend_rgba_to_rgb(&rgba[..n], width as usize, height as usize);

    // 委托 image crate 基线 JPEG 编码器（DR6：复用开源实现；其 encode_rgb
    // 为 4:4:4 无色度下采样，任意尺寸按 8×8 块边界 clamp 处理）。
    let mut buf = Vec::with_capacity(rgb.len() / 2);
    let mut encoder =
        image::codecs::jpeg::JpegEncoder::new_with_quality(&mut buf, quality.clamp(1, 100));
    encoder
        .encode(&rgb, width, height, image::ColorType::Rgb8.into())
        .map_err(|_| STATUS_INTERNAL)?;
    Ok(buf)
}

#[cfg(test)]
mod tests {
    use super::encode_jpeg_rgba;
    use crate::decoders::jpeg::decode_jpeg;
    use std::time::Instant;

    /// round-trip：编码 → 自研解码器（`decoders::jpeg::decode_jpeg`），
    /// 返回（最大通道绝对误差, 误差最大像素索引）。
    ///
    /// 比较基准是**合成后** RGB（解码输出为合成后图像）：解码输出 RGBA8 的
    /// alpha 恒 255，故仅比较前三通道。
    fn round_trip_max_diff(rgba: &[u8], width: u32, height: u32, quality: u8) -> (usize, usize) {
        let jpeg = encode_jpeg_rgba(rgba, width, height, quality).expect("编码应成功");
        assert!(jpeg.starts_with(&[0xFF, 0xD8]), "产物必须以 SOI 开头");
        assert!(jpeg.ends_with(&[0xFF, 0xD9]), "产物必须以 EOI 结尾");
        let (decoded, w, h) = decode_jpeg(&jpeg).expect("自研解码器应能解码自身产物");
        assert_eq!((w, h), (width, height), "解码尺寸应等于输入");
        assert_eq!(decoded.len(), (width as usize) * (height as usize) * 4);

        let synthed = synthesize(rgba, width, height);
        let mut max_diff: usize = 0;
        let mut worst_px: usize = 0;
        for (i, px) in synthed.chunks_exact(3).enumerate() {
            for c in 0..3 {
                let diff = (i32::from(px[c]) - i32::from(decoded[i * 4 + c])).unsigned_abs() as usize;
                if diff > max_diff {
                    max_diff = diff;
                    worst_px = i;
                }
            }
        }
        (max_diff, worst_px)
    }

    /// 白底 alpha 预乘合成参考（与编码器 `blend_rgba_to_rgb` 同式）。
    fn synthesize(rgba: &[u8], width: u32, height: u32) -> Vec<u8> {
        let mut out = vec![0u8; (width as usize) * (height as usize) * 3];
        for (i, px) in rgba.chunks_exact(4).enumerate() {
            let (r, g, b, a) = (
                u32::from(px[0]),
                u32::from(px[1]),
                u32::from(px[2]),
                u32::from(px[3]),
            );
            let inv = 255 - a;
            out[i * 3] = ((r * a + 255 * inv + 127) / 255) as u8;
            out[i * 3 + 1] = ((g * a + 255 * inv + 127) / 255) as u8;
            out[i * 3 + 2] = ((b * a + 255 * inv + 127) / 255) as u8;
        }
        out
    }

    /// 三角波（周期 254、峰 127）：连续、无 wrap 跳变的低频扫描基元。
    ///
    /// 夹具校准说明（DR6）：q90 JPEG 对逐像素噪声 / `&0xFF` wrap 跳变内容
    /// 的固有量化损失远超 3/255（libjpeg-turbo 自编自解实测达 33~37），
    /// 与编码器实现无关。故夹具统一改用三角波低频构造（贴近真实缩略图
    /// 的平滑降采样特性），使 ≤3 断言检验「编码器实现正确性」而非
    /// 「有损压缩的理论极限」。
    fn tri(t: u32) -> u32 {
        let m = t % 254;
        if m < 128 { m } else { 254 - m }
    }

    /// 平滑亮度渐变（alpha 全 255；三通道同向微偏移，色度近恒定）。
    fn gradient_rgba(width: u32, height: u32) -> Vec<u8> {
        let mut buf = Vec::with_capacity((width * height * 4) as usize);
        for y in 0..height {
            for x in 0..width {
                let v = tri(x + y);
                buf.extend_from_slice(&[
                    v as u8,
                    (v + 7).min(255) as u8,
                    v.saturating_sub(9) as u8,
                    255,
                ]);
            }
        }
        buf
    }

    /// 彩色 + 半透明 alpha（验证预乘合成）：三通道沿不同方向渐变保证彩色
    /// 路径覆盖；alpha 为连续半透明带 [128,191]。
    fn colorful_alpha_rgba(width: u32, height: u32) -> Vec<u8> {
        let mut buf = Vec::with_capacity((width * height * 4) as usize);
        for y in 0..height {
            for x in 0..width {
                let a = 128 + tri(x + y) / 2;
                buf.extend_from_slice(&[
                    tri(x) as u8,
                    (tri(y) + 60).min(255) as u8,
                    tri(x + y).saturating_sub(60) as u8,
                    a as u8,
                ]);
            }
        }
        buf
    }

    /// 照片风格合成图：低频大偏移色带（通道差 120）+ 高 alpha 连续窄带
    /// [239,255]（轻微半透明）。
    fn photo_like_rgba(width: u32, height: u32) -> Vec<u8> {
        let mut buf = Vec::with_capacity((width * height * 4) as usize);
        for y in 0..height {
            for x in 0..width {
                let v = tri(x + y);
                let a = 255 - tri(x + y) / 4;
                buf.extend_from_slice(&[
                    v as u8,
                    (v + 60).min(255) as u8,
                    v.saturating_sub(60) as u8,
                    a as u8,
                ]);
            }
        }
        buf
    }

    #[test]
    fn round_trip_8x8_gradient_within_3() {
        let rgba = gradient_rgba(8, 8);
        let (max_diff, worst) = round_trip_max_diff(&rgba, 8, 8, 90);
        assert!(
            max_diff <= 3,
            "8x8 渐变 round-trip 最大误差应为 ≤3，实得 {max_diff}（worst px {worst}）"
        );
    }

    #[test]
    fn round_trip_16x16_colorful_within_3() {
        let rgba = colorful_alpha_rgba(16, 16);
        let (max_diff, worst) = round_trip_max_diff(&rgba, 16, 16, 90);
        assert!(
            max_diff <= 3,
            "16x16 彩色+alpha round-trip 最大误差应为 ≤3，实得 {max_diff}（worst px {worst}）"
        );
    }

    #[test]
    fn round_trip_64x64_photo_like_within_3() {
        let rgba = photo_like_rgba(64, 64);
        let (max_diff, worst) = round_trip_max_diff(&rgba, 64, 64, 90);
        assert!(
            max_diff <= 3,
            "64x64 照片风格 round-trip 最大误差应为 ≤3，实得 {max_diff}（worst px {worst}）"
        );
    }

    #[test]
    fn round_trip_non_multiple_of_8_edges() {
        // 非 8 倍数尺寸：image crate 直接处理任意宽高，无需边缘填充。
        let rgba = photo_like_rgba(37, 53);
        let (max_diff, worst) = round_trip_max_diff(&rgba, 37, 53, 90);
        assert!(
            max_diff <= 3,
            "37x53（非 8 倍数）round-trip 最大误差应为 ≤3，实得 {max_diff}（worst px {worst}）"
        );
    }

    #[test]
    fn alpha_zero_blends_to_white() {
        // alpha=0 的像素预乘后应为近白色。
        let mut rgba = vec![0u8; 8 * 8 * 4];
        for px in rgba.chunks_exact_mut(4) {
            px.copy_from_slice(&[200, 30, 90, 0]);
        }
        let (max_diff, _) = round_trip_max_diff(&rgba, 8, 8, 90);
        assert!(
            max_diff <= 3,
            "alpha=0 像素应合成到白底（255,255,255）±3，实得误差 {max_diff}"
        );
    }

    #[test]
    fn encode_128px_within_5ms_dev_profile_generous() {
        // 计时断言（粗略）：debug（dev profile）下放宽到 50ms；release 模式下
        // 的精确 ≤5ms 数据另以 `cargo test --release` 证据记录（见证据 log）。
        let rgba = photo_like_rgba(128, 128);
        let start = Instant::now();
        let jpeg = encode_jpeg_rgba(&rgba, 128, 128, 90).expect("128x128 编码应成功");
        let elapsed = start.elapsed();
        println!(
            "task-16: encode 128x128 elapsed = {:?}, jpeg bytes = {}",
            elapsed,
            jpeg.len()
        );
        assert!(
            elapsed <= std::time::Duration::from_millis(50),
            "dev profile 下 128x128 编码计时应 < 50ms，实得 {elapsed:?}"
        );
        let (decoded, w, h) = decode_jpeg(&jpeg).expect("128x128 产物应可解码");
        assert_eq!((w, h), (128, 128));
        assert_eq!(decoded.len(), 128 * 128 * 4);
    }

    #[test]
    fn empty_and_zero_size_inputs_return_error() {
        assert!(encode_jpeg_rgba(&[], 0, 0, 90).is_err(), "空输入+零尺寸应报错");
        assert!(encode_jpeg_rgba(&[], 8, 8, 90).is_err(), "空缓冲应报错");
        assert!(encode_jpeg_rgba(&[0u8; 8 * 8 * 4], 8, 0, 90).is_err(), "高为 0 应报错");
        assert!(encode_jpeg_rgba(&[0u8; 8 * 8 * 4], 0, 8, 90).is_err(), "宽为 0 应报错");
    }

    #[test]
    fn too_small_inputs_return_error_without_panic() {
        // 过小输入（宽/高 < 8）→ Err，不 panic。
        for (w, h) in [(1u32, 1u32), (7, 7), (7, 16), (16, 7), (4, 8)] {
            let buf = vec![0u8; (w * h * 4) as usize];
            let result = encode_jpeg_rgba(&buf, w, h, 90);
            match result {
                Err(code) => assert_ne!(code, 0, "{w}x{h} 返回值不可为 0"),
                Ok(_) => panic!("{w}x{h} 过小输入不应编码成功"),
            }
        }
    }

    #[test]
    fn buffer_length_mismatch_returns_error() {
        // 缓冲长度与尺寸不匹配（太少）→ Err。
        assert!(encode_jpeg_rgba(&[0u8; 8 * 8 * 4 - 1], 8, 8, 90).is_err());
        // 缓冲过长允许（调用方可能传整块容量）。
        let over = vec![0u8; 8 * 8 * 4 + 32];
        assert!(encode_jpeg_rgba(&over, 8, 8, 90).is_ok());
    }

    #[test]
    fn quality_boundaries_do_not_panic() {
        // 质量越界（0 与 255）钳位处理，不 panic、产物合法。
        let rgba = gradient_rgba(8, 8);
        for &q in &[1u8, 50, 90, 100, 0, 255] {
            let jpeg = encode_jpeg_rgba(&rgba, 8, 8, q).expect("质量越界应钳位而非报错");
            let (decoded, w, h) = decode_jpeg(&jpeg).expect("各质量档产物应可解码");
            assert_eq!((w, h), (8, 8));
            let _ = decoded;
        }
    }
}
