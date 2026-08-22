//! WebP 解码器（todo 18 实现；Design Revision 5 落地）。
//!
//! 职责：**接线 image crate 内建 WebP 覆盖**（image 0.25.10 已启用 webp feature：
//! image-webp 0.2.4 完整实现 VP8 有损 / VP8L 无损 / VP8X 扩展 + ALPH alpha /
//! 动画 ANIM/ANMF 解析），不自研 RIFF 分块与 VP8L 熵解码。本模块唯一逻辑：
//! 解码前读取容器声明的宽做解压炸弹防御（与 `thumbnail_manager.py`
//! MAX_IMAGE_DIMENSION=8192 对齐），超限返回 `STATUS_TOO_LARGE=-7`，
//! 解码失败返回 `STATUS_DECODE_FAILED=-2`，均不 panic。
//!
//! 容器高宽解析（实测 image-webp 0.2.4 源码 + PIL 12.3.0 夹具逐字节验证）：
//! - `VP8X` chunk（偏移 12 起首个 chunk）：canvas 宽在偏移 24、高在偏移 27，
//!   各 3 字节小端 +1（extended.rs:224-227 `read_3_bytes + 1`，前置 1 字节
//!   flags + 3 字节 reserved）。
//! - `VP8 ` chunk：负载起于偏移 20，帧宽/高为帧头偏移 6-9 的 14-bit 小端
//!   u16（`& 0x3FFF`，跨越文件偏移 26-29），要求关键帧位（帧头 bit0=0）
//!   与 start code `9D 01 2A`（同 `vp8.rs::vp8_dimensions` 的既有验证）。
//! - `VP8L` chunk：负载起于偏移 20，签名 `0x2F` 后接 14+14 bit 位打包
//!   宽/高（各 +1）。image-webp lossless.rs:151-153 用 LSB-first BitReader
//!   `read_bits::<u16>(14) + 1` 读取（vp8 位序自测 `0x9C -> 低 3 位=4`）。
//!   因签名恰好占满首字节，宽字段始于字节边界 → 直接 `u32::from_le_bytes`
//!   读取偏移 21 起即可等价（宽取低 14 bit，高取 14-27 bit）。
//! - 首个 chunk 不在以上三类（ALPH/ANIM/未知/损坏）→ 跳过预检，委托
//!   image crate（其失败 → -2）。
//!
//! 输出契约为统一 RGBA8（`to_rgba8`）。VP8 有损/alpaa/无损/动画均由此入口覆盖，
//! 不单独接线 `vp8.rs`（该模块面向裸 VP8 流，见其模块注释）。

use crate::{STATUS_DECODE_FAILED, STATUS_TOO_LARGE};

/// 解码防御上限（像素维度，与 `thumbnail_manager.py:216-217` 对齐）。
const MAX_IMAGE_DIMENSION: u32 = 8192;
/// 像素数上限 `8192*8192`（u64 常量，避免 u32 乘法溢出）。
const MAX_PIXELS: u64 = MAX_IMAGE_DIMENSION as u64 * MAX_IMAGE_DIMENSION as u64;

/// VP8 关键帧 start code（帧头偏移 3-5，同 `vp8.rs`）。
const VP8_START_CODE: &[u8] = &[0x9D, 0x01, 0x2A];
/// VP8L 位流签名（payload 首字节）。
const VP8L_SIGNATURE: u8 = 0x2F;

#[allow(dead_code)]
// 解码器未接线 lib.rs（待 todo 24/26 经 infra/registry 分发接入）；cdylib 构建下
// 当前仅 `#[cfg(test)]` 引用，显式标注避免 dead_code 警告（同 decoders/png.rs
// 的 decode_png 先例）。
/// 解码 WebP 数据为 RGBA8（`Vec<u8>` 行优先、每像素 4 字节）。
///
/// 输入为完整 WebP 文件字节（RIFF 容器，含 `RIFF....WEBP` 头）。
/// 实现 = 容器高宽预检（解压炸弹防御）+ 委托 `image::load_from_memory`
/// （image-webp 覆盖 VP8 / VP8L / VP8X 全部变体）。
///
/// # 错误语义
/// - 尺寸超限（容器声明像素数 > 8192×8192）→ `STATUS_TOO_LARGE=-7`（解码前拦截）。
/// - 非 WebP / 损坏 / 截断 / 解码失败 → `STATUS_DECODE_FAILED=-2`。
pub fn decode_webp(bytes: &[u8]) -> Result<(Vec<u8>, u32, u32), i32> {
    // 解压炸弹防御：先在解码前读取容器声明的宽高，超限直接拒绝，不交给 image
    // 分配内存。非 WebP / 头不完整的输入此步跳过，交由 image crate 判定失败。
    if let Some((w, h)) = webp_dimensions(bytes) {
        if is_oversized(w, h) {
            return Err(STATUS_TOO_LARGE);
        }
    }
    // image crate 内建覆盖全部 WebP 变体；输出经 to_rgba8 统一为 8bit RGBA。
    let rgba = image::load_from_memory(bytes)
        .map_err(|_| STATUS_DECODE_FAILED)?
        .to_rgba8();
    let w = rgba.width();
    let h = rgba.height();
    Ok((rgba.into_raw(), w, h))
}

/// 读取 WebP 容器首个 chunk 声明的宽高（RIFF 头 12 字节后首个 chunk）。
///
/// 返回 `None` 表示非 WebP（魔数不符）、头不完整，或首个 chunk 类型无法
/// 可靠定位尺寸（非 VP8/VP8L/VP8X，如 ALPH/ANIM/未知）——此时跳过预检，
/// 交由 image crate 判定。
fn webp_dimensions(bytes: &[u8]) -> Option<(u32, u32)> {
    if bytes.len() < 12 || &bytes[0..4] != b"RIFF" || &bytes[8..12] != b"WEBP" {
        return None;
    }
    match &bytes[12..16] {
        b"VP8X" => vp8x_dimensions(bytes),
        b"VP8 " => vp8_lossy_dimensions(bytes),
        b"VP8L" => vp8l_dimensions(bytes),
        _ => None,
    }
}

/// 读取 RIFF 中的 3 字节小端无符号数（用于 VP8X canvas 维度）。
fn read_u24_le(bytes: &[u8], offset: usize) -> Option<u32> {
    let hi = bytes.get(offset + 2)?;
    Some(u32::from(bytes[offset]) | (u32::from(bytes[offset + 1]) << 8) | (u32::from(*hi) << 16))
}

/// VP8X chunk：canvas 宽/高各 3 字节 LE +1（flags 1 字节 + reserved 3 字节后）。
fn vp8x_dimensions(bytes: &[u8]) -> Option<(u32, u32)> {
    if bytes.len() < 30 {
        return None;
    }
    let w = read_u24_le(bytes, 24)?.checked_add(1)?;
    let h = read_u24_le(bytes, 27)?.checked_add(1)?;
    Some((w, h))
}

/// `VP8 ` chunk：帧宽/高为负载偏移 6-9 的 14-bit 小端 u16（文件偏移 26-29）。
fn vp8_lossy_dimensions(bytes: &[u8]) -> Option<(u32, u32)> {
    if bytes.len() < 30 {
        return None;
    }
    // 非关键帧（interframe）依赖参考帧——无法独立解析/解码，跳过预检
    // 交由 image crate（其失败 → -2，与 vp8.rs 语义一致）。
    if bytes[20] & 1 != 0 {
        return None;
    }
    if &bytes[23..26] != VP8_START_CODE {
        return None;
    }
    let w = u32::from(u16::from_le_bytes([bytes[26], bytes[27]]) & 0x3FFF);
    let h = u32::from(u16::from_le_bytes([bytes[28], bytes[29]]) & 0x3FFF);
    if w == 0 || h == 0 {
        return None;
    }
    Some((w, h))
}

/// `VP8L` chunk：签名 `0x2F` 后 14-bit 宽 + 14-bit 高（各 +1）。签名占满
/// 首字节 → 宽字段始于字节边界，`u32::from_le_bytes(偏移 21)` 直接等价
/// image-webp LSB-first BitReader 的连续读取。
fn vp8l_dimensions(bytes: &[u8]) -> Option<(u32, u32)> {
    if bytes.len() < 25 || bytes[20] != VP8L_SIGNATURE {
        return None;
    }
    let bits = u32::from_le_bytes([bytes[21], bytes[22], bytes[23], bytes[24]]);
    let w = (bits & 0x3FFF) + 1;
    let h = ((bits >> 14) & 0x3FFF) + 1;
    Some((w, h))
}

/// 像素数是否超限（u64 乘法，避免 u32 溢出）。
fn is_oversized(w: u32, h: u32) -> bool {
    u64::from(w) * u64::from(h) > MAX_PIXELS
}

#[cfg(test)]
mod tests {
    use super::decode_webp;

    // 夹具由 PIL 12.3.0 确定性生成（脚本 task-18-gen-webp-fixtures.py），
    // 像素公式见各 const 注释；有损夹具仅保留解码成功/尺寸断言，内容基准由
    // image crate 参考路径完成（image 与 libwebp 输出经 task-19 实测逐字节相同）。

    // WEBP_LOSSY_Q90_8X8: 有损 quality=90，VP8 chunk（无 alpha），8x8。
    //   pixel(x,y)=(x*40,y*50,(x+y)*25) mod 256
    const WEBP_LOSSY_Q90_8X8: &[u8] = &[82, 73, 70, 70, 144, 0, 0, 0, 87, 69, 66, 80, 86, 80, 56, 32, 132, 0, 0, 0, 112, 2, 0, 157, 1, 42, 8, 0, 8, 0, 0, 192, 18, 37, 176, 2, 116, 76, 0, 89, 0, 116, 176, 3, 192, 125, 237, 128, 0, 254, 254, 122, 57, 231, 252, 35, 138, 178, 100, 88, 227, 255, 191, 240, 76, 243, 255, 211, 86, 255, 243, 77, 59, 224, 110, 149, 97, 93, 83, 37, 241, 3, 31, 158, 143, 232, 42, 127, 248, 143, 103, 127, 155, 123, 171, 126, 59, 127, 206, 111, 159, 244, 34, 255, 228, 219, 6, 86, 247, 193, 127, 255, 67, 207, 252, 104, 113, 254, 156, 46, 46, 167, 253, 163, 186, 36, 176, 191, 159, 255, 194, 238, 205, 155, 21, 249, 167, 5, 147, 127, 216, 223, 247, 147, 47, 159, 255, 208, 223, 234, 0, 0];
    // WEBP_LOSSLESS_8X8: 无损 VP8L chunk（无 alpha），8x8。
    //   pixel(x,y)=(x*31,y*37,x*y*17) mod 256 → RGBA (r,g,b,255)
    const WEBP_LOSSLESS_8X8: &[u8] = &[82, 73, 70, 70, 74, 0, 0, 0, 87, 69, 66, 80, 86, 80, 56, 76, 62, 0, 0, 0, 47, 7, 192, 1, 0, 185, 50, 68, 244, 63, 118, 17, 209, 255, 128, 130, 182, 109, 24, 147, 9, 127, 146, 59, 20, 230, 195, 32, 219, 72, 83, 24, 203, 25, 60, 195, 41, 188, 211, 51, 61, 85, 76, 0, 200, 28, 112, 254, 144, 133, 91, 144, 6, 68, 194, 33, 203, 7, 68, 68, 202, 51];
    // WEBP_RGBA_LOSSLESS_8X8: 无损 VP8L chunk（真 alpha），8x8。
    //   pixel(x,y)=(x*50,y*60,(x+y)*30,(255-x*40)) mod 256 → alpha 逐列变化
    const WEBP_RGBA_LOSSLESS_8X8: &[u8] = &[82, 73, 70, 70, 46, 0, 0, 0, 87, 69, 66, 80, 86, 80, 56, 76, 34, 0, 0, 0, 47, 7, 192, 1, 16, 185, 10, 68, 244, 63, 118, 17, 209, 255, 48, 144, 73, 219, 84, 88, 253, 43, 235, 55, 3, 99, 100, 234, 49, 216, 121, 174, 204, 0];
    // WEBP_LOSSY_Q90_12X8: 有损 quality=90 非正方形 12x8（VP8 chunk）。
    //   pixel(x,y)=(x*25,y*35,(x*3+y*7)) mod 256
    const WEBP_LOSSY_Q90_12X8: &[u8] = &[82, 73, 70, 70, 122, 0, 0, 0, 87, 69, 66, 80, 86, 80, 56, 32, 110, 0, 0, 0, 80, 3, 0, 157, 1, 42, 12, 0, 8, 0, 0, 192, 18, 37, 176, 2, 116, 186, 1, 248, 1, 74, 3, 92, 3, 64, 3, 36, 0, 22, 103, 186, 173, 3, 0, 0, 254, 255, 129, 223, 249, 197, 225, 238, 28, 114, 127, 212, 183, 255, 127, 193, 151, 187, 79, 125, 150, 180, 135, 221, 229, 31, 254, 215, 86, 135, 253, 64, 233, 149, 208, 39, 206, 223, 31, 252, 238, 254, 219, 239, 127, 223, 255, 141, 196, 243, 48, 210, 223, 248, 224, 133, 255, 10, 107, 242, 77, 254, 248, 184, 230, 250, 219, 193, 149, 127, 192, 0, 0, 0];
    // WEBP_VP8X_WRAPPED_LOSSY_8X8: 真实 VP8X+VP8 双 chunk（canvas 8x8），有损。
    //   由任务 1 有损夹具手工包裹（VP8X canvas dims 偏移 24/27，各 3B LE +1）。
    const WEBP_VP8X_WRAPPED_LOSSY_8X8: &[u8] = &[82, 73, 70, 70, 162, 0, 0, 0, 87, 69, 66, 80, 86, 80, 56, 88, 10, 0, 0, 0, 0, 0, 0, 0, 7, 0, 0, 7, 0, 0, 86, 80, 56, 32, 132, 0, 0, 0, 112, 2, 0, 157, 1, 42, 8, 0, 8, 0, 0, 192, 18, 37, 176, 2, 116, 76, 0, 89, 0, 116, 176, 3, 192, 125, 237, 128, 0, 254, 254, 122, 57, 231, 252, 35, 138, 178, 100, 88, 227, 255, 191, 240, 76, 243, 255, 211, 86, 255, 243, 77, 59, 224, 110, 149, 97, 93, 83, 37, 241, 3, 31, 158, 143, 232, 42, 127, 248, 143, 103, 127, 155, 123, 171, 126, 59, 127, 206, 111, 159, 244, 34, 255, 228, 219, 6, 86, 247, 193, 127, 255, 67, 207, 252, 104, 113, 254, 156, 46, 46, 167, 253, 163, 186, 36, 176, 191, 159, 255, 194, 238, 205, 155, 21, 249, 167, 5, 147, 127, 216, 223, 247, 147, 47, 159, 255, 208, 223, 234, 0, 0];
    // WEBP_GARBAGE_16B: 垃圾字节（非 RIFF）→ -2 不 panic。
    const WEBP_GARBAGE_16B: &[u8] = &[0, 17, 34, 51, 68, 85, 102, 119, 136, 153, 170, 187, 204, 221, 238, 255];
    // WEBP_FORGED_RIFF_BROKEN_VP8: 伪造 RIFF+WEBP 但 VP8 chunk 数据无效 → -2 不 panic。
    const WEBP_FORGED_RIFF_BROKEN_VP8: &[u8] = &[82, 73, 70, 70, 20, 0, 0, 0, 87, 69, 66, 80, 86, 80, 56, 32, 4, 0, 0, 0, 0, 0, 0, 0];
    // WEBP_FORGED_VP8X_10000X10000: 伪造 VP8X 声明 10000x10000（合法 chunk 头，
    //   canvas 3B LE +1 = 10000），无实际图像数据 → 预检 B → -7 不 panic。
    const WEBP_FORGED_VP8X_10000X10000: &[u8] = &[82, 73, 70, 70, 22, 0, 0, 0, 87, 69, 66, 80, 86, 80, 56, 88, 10, 0, 0, 0, 0, 0, 0, 0, 15, 39, 0, 15, 39, 0];

    /// 构造仅含 VP8X 头（canvas w x h）的伪造 WebP，用于维度边界测试。
    fn vp8x_only(w: u32, h: u32) -> Vec<u8> {
        let mut v = Vec::new();
        v.extend_from_slice(b"RIFF");
        v.extend_from_slice(&30u32.to_le_bytes());
        v.extend_from_slice(b"WEBP");
        v.extend_from_slice(b"VP8X");
        v.extend_from_slice(&10u32.to_le_bytes());
        v.extend_from_slice(&[0, 0, 0, 0]); // flags + reserved
        v.extend_from_slice(&(w - 1).to_le_bytes()[..3]);
        v.extend_from_slice(&(h - 1).to_le_bytes()[..3]);
        v
    }

    /// image crate 参考路径（未走我们的预检）——用于内容逐字节基准。
    fn reference_rgba(bytes: &[u8]) -> Vec<u8> {
        image::load_from_memory(bytes).unwrap().to_rgba8().into_raw()
    }

    fn px_at(raw: &[u8], w: u32, x: u32, y: u32) -> [u8; 4] {
        let i = (y * w + x) as usize * 4;
        [raw[i], raw[i + 1], raw[i + 2], raw[i + 3]]
    }

    #[test]
    fn lossy_vp8_chunk_decodes_to_rgba8() {
        // 有损 VP8（无 alpha）→ RGBA8，尺寸 8x8，内容与 image crate 参考一致。
        let (out, w, h) = decode_webp(WEBP_LOSSY_Q90_8X8).expect("有损 VP8 应解码成功");
        assert_eq!((w, h), (8, 8));
        assert_eq!(out.len(), 8 * 8 * 4, "输出必须为 RGBA8");
        assert_eq!(out, reference_rgba(WEBP_LOSSY_Q90_8X8),
                   "有损输出应与 image crate 参考逐字节一致");
    }

    #[test]
    fn lossless_vp8l_chunk_decodes_to_rgba8() {
        // 无损 VP8L（RGB，无 alpha）→ alpha 恒 255，内容逐像素精确。
        let (out, w, h) = decode_webp(WEBP_LOSSLESS_8X8).expect("无损 VP8L 应解码成功");
        assert_eq!((w, h), (8, 8));
        assert_eq!(out.len(), 8 * 8 * 4);
        assert_eq!(px_at(&out, w, 1, 0), [31, 0, 0, 255]);
        assert_eq!(px_at(&out, w, 0, 1), [0, 37, 0, 255]);
        assert_eq!(px_at(&out, w, 2, 3), [62, 111, 102, 255]); // (2*31, 3*37, 2*3*17)
        assert_eq!(out, reference_rgba(WEBP_LOSSLESS_8X8));
    }

    #[test]
    fn rgba_lossless_preserves_alpha() {
        // 无损 RGBA → alpha 逐列变化（255-x*40）且非全 255。
        let (out, w, h) = decode_webp(WEBP_RGBA_LOSSLESS_8X8)
            .expect("无损 RGBA 应解码成功");
        assert_eq!((w, h), (8, 8));
        assert_eq!(out.len(), 8 * 8 * 4);
        assert_eq!(px_at(&out, w, 0, 0), [0, 0, 0, 255]);
        assert_eq!(px_at(&out, w, 1, 0), [50, 0, 30, 215]); // (x=1,y=0,a=255-40)
        assert_eq!(px_at(&out, w, 4, 4), [200, 240, 240, 95]); // (a=255-160)
        assert!(out.iter().step_by(4).skip(3).any(|&a| a != 255),
                "alpha 必须包含非 255 值（真 alpha 保留）");
        assert_eq!(out, reference_rgba(WEBP_RGBA_LOSSLESS_8X8));
    }

    #[test]
    fn non_square_lossy_decodes() {
        // 非正方形 12x8，w*h=96。
        let (out, w, h) = decode_webp(WEBP_LOSSY_Q90_12X8).expect("非正方形应解码成功");
        assert_eq!((w, h), (12, 8));
        assert_eq!(out.len(), 12 * 8 * 4);
        assert_eq!(out, reference_rgba(WEBP_LOSSY_Q90_12X8));
    }

    #[test]
    fn vp8x_wrapped_lossy_decodes() {
        // 真实 VP8X+VP8 双 chunk（canvas 8x8）→ VP8X 预检分支 + 解码成功。
        let (out, w, h) = decode_webp(WEBP_VP8X_WRAPPED_LOSSY_8X8)
            .expect("VP8X 包裹应解码成功");
        assert_eq!((w, h), (8, 8));
        assert_eq!(out.len(), 8 * 8 * 4);
        assert_eq!(out, reference_rgba(WEBP_VP8X_WRAPPED_LOSSY_8X8));
    }

    #[test]
    fn empty_garbage_and_forged_return_error_without_panic() {
        // 空字节 / 垃圾 / 伪造 RIFF+WEBP 坏 chunk → Err(non-zero)，不 panic。
        assert!(decode_webp(&[]).is_err());
        assert_eq!(decode_webp(&[]), Err(-2));
        assert_eq!(decode_webp(WEBP_GARBAGE_16B), Err(-2));
        assert_eq!(decode_webp(WEBP_FORGED_RIFF_BROKEN_VP8), Err(-2));
    }

    #[test]
    fn oversize_vp8x_returns_status_too_large() {
        // 伪造 VP8X 声明 10000x10000（w*h=1e8 > 8192²）→ -7 不 panic，
        // 且在委托 image crate（无实际数据，原本必然解码失败）之前拦截。
        assert_eq!(decode_webp(WEBP_FORGED_VP8X_10000X10000), Err(-7));
    }

    #[test]
    fn dimension_threshold_boundary() {
        // 恰好 8192*8192 = MAX_PIXELS 允许通过预检（随后 image crate 因无数据
        // 解码失败 → -2），8192*8193 超限 → -7。验证边界不错位。
        assert_eq!(decode_webp(&vp8x_only(8192, 8192)), Err(-2));
        assert_eq!(decode_webp(&vp8x_only(8192, 8193)), Err(-7));
        assert_eq!(decode_webp(&vp8x_only(8193, 8192)), Err(-7));
        // 超小 canvas 也正常通过预检 → -2（image 因缺数据失败）。
        assert_eq!(decode_webp(&vp8x_only(1, 1)), Err(-2));
    }
}