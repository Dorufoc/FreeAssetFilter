//! PNG 解码器（todo 14 实现；Design Revision 5 落地）。
//!
//! 职责：**接线 image crate 内建覆盖**，不自研 PNG 解析——png crate（flate2→
//! miniz_oxide 纯 Rust）覆盖全部颜色类型 0/2/3/4/6、位深 1/2/4/8/16、
//! Adam7 隔行、5 种滤波、tRNS 透明、多 IDAT 拼接、CRC 校验。本模块唯一逻辑：
//! 解码前读取 IHDR 宽高做解压炸弹防御（与 `thumbnail_manager.py`
//! MAX_IMAGE_DIMENSION=8192 对齐），超限返回 `STATUS_TOO_LARGE=-7`，
//! 解码失败返回 `STATUS_DECODE_FAILED=-2`，均不 panic。
//!
//! 输出契约为统一 RGBA8：16bit 输入由 `to_rgba8` 降采样 —— image 的
//! `FromPrimitive<u16> for u8` 实现为 `(v + 128) / 257`（等价 `round(v*255/65535)`，
//! 四舍五入缩放，非简单取高字节）。后续 todo（registry 分发 / T1 解码器接线）消费本入口。

use crate::{STATUS_DECODE_FAILED, STATUS_TOO_LARGE};

/// 解码防御上限（像素维度，与 `thumbnail_manager.py:216-217` 对齐）。
const MAX_IMAGE_DIMENSION: u32 = 8192;
/// 像素数上限 `8192*8192`（u64 常量，避免 u32 乘法溢出）。
const MAX_PIXELS: u64 = MAX_IMAGE_DIMENSION as u64 * MAX_IMAGE_DIMENSION as u64;

/// PNG 魔数签名（8 字节）。
const PNG_SIGNATURE: [u8; 8] = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];

#[allow(dead_code)]
// 该函数供 todo 7 registry 分发与后续 T1 接线消费；cdylib 下当前仅测试引用，
// 故显式标注避免 dead_code 警告（同 infra/resize.rs / registry.rs 先例）。
/// 解码 PNG 数据为 RGBA8（`Vec<u8>` 行优先、每像素 4 字节）。
///
/// # 错误语义
/// - 尺寸超限（IHDR 声明像素数 > 8192×8192）→ `STATUS_TOO_LARGE=-7`（解码前拦截）。
/// - 数据非 PNG 或解码失败/截断 → `STATUS_DECODE_FAILED=-2`。
pub fn decode_png(bytes: &[u8]) -> Result<(Vec<u8>, u32, u32), i32> {
    // 解压炸弹防御：先在解码前读取 IHDR 声明的宽高，超限直接拒绝，不交给 image
    // 分配内存。非 PNG / 头不完整的输入此步跳过，交由 image crate 判定失败。
    if let Some((w, h)) = png_dimensions(bytes) {
        if is_oversized(w, h) {
            return Err(STATUS_TOO_LARGE);
        }
    }
    // image crate 内建覆盖全部 PNG 变体；16bit 输入由 to_rgba8 降采样到 8bit。
    let rgba = image::load_from_memory(bytes)
        .map_err(|_| STATUS_DECODE_FAILED)?
        .to_rgba8();
    let w = rgba.width();
    let h = rgba.height();
    Ok((rgba.into_raw(), w, h))
}

/// 读取 IHDR 声明的宽高（偏移 16..24，大端）。
///
/// 返回 `None` 表示非 PNG（签名不符）或头不完整（不足 24 字节）。
fn png_dimensions(bytes: &[u8]) -> Option<(u32, u32)> {
    if bytes.len() < 24 || bytes[..8] != PNG_SIGNATURE || &bytes[12..16] != b"IHDR" {
        return None;
    }
    let w = u32::from_be_bytes([bytes[16], bytes[17], bytes[18], bytes[19]]);
    let h = u32::from_be_bytes([bytes[20], bytes[21], bytes[22], bytes[23]]);
    Some((w, h))
}

/// 像素数是否超限（u64 乘法，避免 u32 溢出）。
fn is_oversized(w: u32, h: u32) -> bool {
    u64::from(w) * u64::from(h) > MAX_PIXELS
}

#[cfg(test)]
mod tests {
    use super::decode_png;

    // 夹具由 PIL 确定性生成（脚本 gen_png_fixtures.py），像素公式见各 const 注释。
    // PNG_L8_4X4: 灰度8bit pixel(x,y)=(x*7+y*13)%256 → RGBA (v,v,v,255)
    const PNG_L8_4X4: &[u8] = &[137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 4, 0, 0, 0, 4, 8, 0, 0, 0, 0, 140, 154, 193, 162, 0, 0, 0, 20, 73, 68, 65, 84, 120, 156, 99, 100, 96, 103, 103, 103, 228, 101, 103, 103, 103, 129, 19, 0, 4, 240, 0, 134, 193, 173, 227, 17, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130];
    // PNG_LA8_4X4: 灰度+alpha pixel(x,y)=((x*30+y*10)%256,(x*40+y*20)%256) → RGBA (L,L,L,A)
    const PNG_LA8_4X4: &[u8] = &[137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 4, 0, 0, 0, 4, 8, 4, 0, 0, 0, 3, 248, 86, 245, 0, 0, 0, 21, 73, 68, 65, 84, 120, 156, 99, 100, 96, 144, 211, 0, 65, 38, 46, 17, 8, 196, 100, 0, 0, 44, 106, 2, 66, 232, 222, 64, 29, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130];
    // PNG_P8_4X4: 8色灰阶调色板 pixel index=(x+4*y)%8 → RGBA (i,i,i,255)
    const PNG_P8_4X4: &[u8] = &[137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 4, 0, 0, 0, 4, 8, 3, 0, 0, 0, 158, 47, 110, 76, 0, 0, 0, 24, 80, 76, 84, 69, 0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5, 5, 6, 6, 6, 7, 7, 7, 191, 149, 9, 106, 0, 0, 0, 20, 73, 68, 65, 84, 120, 218, 99, 96, 96, 100, 98, 102, 96, 97, 101, 99, 103, 128, 179, 0, 1, 224, 0, 57, 111, 117, 191, 93, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130];
    // PNG_RGB8_4X4: RGB8 pixel(x,y)=(x*60,y*60,(x+y)*40%256) → RGBA (r,g,b,255)
    const PNG_RGB8_4X4: &[u8] = &[137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 4, 0, 0, 0, 4, 8, 2, 0, 0, 0, 38, 147, 9, 41, 0, 0, 0, 26, 73, 68, 65, 84, 120, 156, 99, 100, 96, 96, 176, 97, 208, 128, 32, 22, 6, 27, 13, 6, 6, 40, 194, 205, 1, 0, 104, 252, 3, 206, 130, 114, 203, 60, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130];
    // PNG_RGBA8_4X4: RGBA8 pixel(x,y)=(x*50,y*50,(x*y)*30%256,255-x*40)
    const PNG_RGBA8_4X4: &[u8] = &[137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 4, 0, 0, 0, 4, 8, 6, 0, 0, 0, 169, 241, 158, 126, 0, 0, 0, 36, 73, 68, 65, 84, 120, 156, 99, 100, 96, 96, 248, 111, 196, 192, 112, 3, 134, 89, 24, 140, 24, 24, 24, 24, 228, 224, 24, 73, 192, 6, 140, 209, 4, 162, 24, 0, 35, 91, 6, 101, 68, 189, 34, 212, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130];
    // PNG_L16_4X4: 16bit灰度 pixel=257*((x*100+y*37)%256) → 8bit=k=(x*100+y*37)%256
    const PNG_L16_4X4: &[u8] = &[137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 4, 0, 0, 0, 4, 16, 0, 0, 0, 0, 220, 10, 29, 225, 0, 0, 0, 22, 73, 68, 65, 84, 120, 156, 99, 96, 96, 72, 73, 57, 113, 66, 71, 135, 73, 21, 10, 48, 25, 0, 130, 60, 6, 47, 102, 98, 199, 127, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130];
    // PNG_RGB16_4X4: 16bit RGB pixel(x,y)=(x*1000+y*100, x*400+y*900, x*700+y*300) mod 65536
    const PNG_RGB16_4X4: &[u8] = &[137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 4, 0, 0, 0, 4, 16, 2, 0, 0, 0, 118, 3, 213, 106, 0, 0, 0, 106, 73, 68, 65, 84, 120, 218, 99, 96, 0, 3, 230, 23, 140, 19, 152, 246, 176, 95, 96, 86, 96, 173, 224, 222, 193, 178, 129, 195, 132, 129, 33, 133, 185, 133, 81, 135, 197, 135, 85, 132, 249, 5, 135, 9, 219, 18, 182, 37, 60, 50, 28, 38, 156, 9, 12, 12, 39, 216, 57, 152, 34, 128, 106, 102, 176, 138, 112, 204, 224, 210, 96, 191, 192, 211, 192, 189, 131, 171, 135, 129, 81, 135, 171, 135, 185, 133, 85, 132, 71, 134, 205, 129, 227, 15, 239, 26, 142, 63, 60, 79, 248, 109, 184, 119, 0, 0, 20, 68, 22, 234, 79, 201, 240, 221, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130];
    // PNG_INTERLACED_ADAM7_8X8: Adam7 隔行 RGB8 pixel(x,y)=(x*31,y*29,(x^y)*15)
    const PNG_INTERLACED_ADAM7_8X8: &[u8] = &[137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 8, 0, 0, 0, 8, 8, 2, 0, 0, 1, 60, 106, 25, 74, 0, 0, 0, 160, 73, 68, 65, 84, 120, 218, 13, 142, 65, 13, 64, 33, 12, 197, 158, 3, 20, 0, 10, 48, 176, 16, 12, 76, 192, 18, 18, 4, 112, 223, 17, 19, 156, 241, 128, 128, 89, 152, 2, 220, 252, 223, 115, 147, 22, 248, 89, 168, 128, 214, 165, 64, 67, 50, 116, 52, 237, 166, 9, 160, 212, 8, 139, 186, 209, 111, 220, 222, 110, 93, 55, 217, 5, 50, 194, 64, 57, 224, 135, 137, 76, 101, 80, 56, 52, 31, 49, 178, 242, 208, 121, 52, 60, 45, 200, 119, 142, 203, 231, 150, 119, 3, 16, 67, 142, 104, 177, 140, 152, 86, 228, 19, 171, 197, 249, 98, 7, 164, 100, 73, 77, 194, 16, 44, 153, 71, 186, 9, 63, 249, 147, 155, 243, 174, 109, 207, 177, 251, 218, 225, 108, 216, 46, 111, 255, 99, 62, 179, 247, 230, 60, 188, 46, 47, 199, 147, 121, 120, 142, 15, 81, 240, 65, 161, 48, 166, 118, 182, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130];
    // PNG_1BIT_4X4: 1bit 黑白灰度 (x+y)%2 → 黑(0,0,0,255) / 白(255,255,255,255)
    const PNG_1BIT_4X4: &[u8] = &[137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 4, 0, 0, 0, 4, 1, 0, 0, 0, 0, 129, 138, 163, 211, 0, 0, 0, 16, 73, 68, 65, 84, 120, 156, 99, 8, 96, 10, 96, 8, 96, 10, 0, 0, 5, 24, 1, 69, 173, 244, 82, 14, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130];
    // PNG_P4BIT_4X4: 4bit 调色板 8色 index=(x+4*y)%8 → RGBA (i,i,i,255)
    const PNG_P4BIT_4X4: &[u8] = &[137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 4, 0, 0, 0, 4, 4, 3, 0, 0, 0, 91, 223, 131, 77, 0, 0, 0, 48, 80, 76, 84, 69, 0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5, 5, 6, 6, 6, 7, 7, 7, 8, 8, 8, 9, 9, 9, 10, 10, 10, 11, 11, 11, 12, 12, 12, 13, 13, 13, 14, 14, 14, 15, 15, 15, 214, 62, 45, 135, 0, 0, 0, 16, 73, 68, 65, 84, 120, 156, 99, 100, 84, 98, 113, 81, 98, 4, 147, 0, 5, 242, 1, 29, 154, 53, 194, 43, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130];
    // PNG_OVERSIZE_IHDR_10000: 伪造 IHDR 声明 10000x10000（合法 CRC），像素数超限。
    const PNG_OVERSIZE_IHDR_10000: &[u8] = &[137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 39, 16, 0, 0, 39, 16, 8, 6, 0, 0, 0, 186, 78, 98, 39, 0, 0, 0, 10, 73, 68, 65, 84, 120, 156, 99, 0, 1, 0, 0, 5, 0, 1, 13, 10, 45, 180];

    fn px_at(raw: &[u8], w: u32, x: u32, y: u32) -> [u8; 4] {
        let i = (y * w + x) as usize * 4;
        [raw[i], raw[i + 1], raw[i + 2], raw[i + 3]]
    }

    #[test]
    fn grayscale_l8_decodes_to_rgba8() {
        // 颜色类型 0（灰度8bit）→ RGBA (v,v,v,255)。
        let (out, w, h) = decode_png(PNG_L8_4X4).expect("L8 应解码成功");
        assert_eq!((w, h), (4, 4));
        assert_eq!(out.len(), 4 * 4 * 4, "输出必须为 RGBA8");
        assert_eq!(px_at(&out, w, 0, 0), [0, 0, 0, 255]);
        assert_eq!(px_at(&out, w, 1, 0), [7, 7, 7, 255]);
        assert_eq!(px_at(&out, w, 0, 1), [13, 13, 13, 255]);
        assert_eq!(px_at(&out, w, 3, 3), [60, 60, 60, 255]);
    }

    #[test]
    fn gray_alpha_la8_decodes() {
        // 颜色类型 4（灰度+alpha）→ RGBA (L,L,L,A)。
        let (out, w, h) = decode_png(PNG_LA8_4X4).expect("LA8 应解码成功");
        assert_eq!((w, h), (4, 4));
        assert_eq!(out.len(), 64);
        assert_eq!(px_at(&out, w, 0, 0), [0, 0, 0, 0]);
        assert_eq!(px_at(&out, w, 1, 0), [30, 30, 30, 40]);
        assert_eq!(px_at(&out, w, 0, 1), [10, 10, 10, 20]);
        assert_eq!(px_at(&out, w, 2, 3), [90, 90, 90, 140]);
    }

    #[test]
    fn palette_p8_decodes_via_clut() {
        // 颜色类型 3（调色板）→ 灰阶调色板索引展开为 RGBA。
        let (out, w, h) = decode_png(PNG_P8_4X4).expect("P8 应解码成功");
        assert_eq!((w, h), (4, 4));
        assert_eq!(out.len(), 64);
        assert_eq!(px_at(&out, w, 0, 0), [0, 0, 0, 255]);
        assert_eq!(px_at(&out, w, 1, 0), [1, 1, 1, 255]);
        assert_eq!(px_at(&out, w, 0, 1), [4, 4, 4, 255]);
        assert_eq!(px_at(&out, w, 3, 3), [7, 7, 7, 255]); // (3+12)%8 = 7
    }

    #[test]
    fn rgb8_decodes() {
        let (out, w, h) = decode_png(PNG_RGB8_4X4).expect("RGB8 应解码成功");
        assert_eq!((w, h), (4, 4));
        assert_eq!(out.len(), 64);
        assert_eq!(px_at(&out, w, 0, 0), [0, 0, 0, 255]);
        assert_eq!(px_at(&out, w, 1, 0), [60, 0, 40, 255]);
        assert_eq!(px_at(&out, w, 0, 1), [0, 60, 40, 255]);
        assert_eq!(px_at(&out, w, 3, 3), [180, 180, 240, 255]);
    }

    #[test]
    fn rgba8_decodes() {
        let (out, w, h) = decode_png(PNG_RGBA8_4X4).expect("RGBA8 应解码成功");
        assert_eq!((w, h), (4, 4));
        assert_eq!(out.len(), 64);
        assert_eq!(px_at(&out, w, 0, 0), [0, 0, 0, 255]);
        assert_eq!(px_at(&out, w, 1, 0), [50, 0, 0, 215]);
        assert_eq!(px_at(&out, w, 2, 2), [100, 100, 120, 175]);
        assert_eq!(px_at(&out, w, 3, 3), [150, 150, 14, 135]); // 9*30=270%256=14
    }

    #[test]
    fn l16_16bit_grayscale_downsampled_to_8bit() {
        // 16bit 灰度：像素=257*k → 降采样后 8bit=k → RGBA (k,k,k,255)。
        let (out, w, h) = decode_png(PNG_L16_4X4).expect("16bit 灰度应解码成功");
        assert_eq!((w, h), (4, 4));
        assert_eq!(out.len(), 64, "16bit 输入经 to_rgba8 后输出仍为 RGBA8");
        assert_eq!(px_at(&out, w, 0, 0), [0, 0, 0, 255]); // k=0
        assert_eq!(px_at(&out, w, 1, 0), [100, 100, 100, 255]); // k=100
        assert_eq!(px_at(&out, w, 0, 1), [37, 37, 37, 255]); // k=37
        assert_eq!(px_at(&out, w, 3, 3), [155, 155, 155, 255]); // k=411%256=155
    }

    #[test]
    fn rgb16_16bit_downsampled_to_8bit() {
        // 16bit RGB：image `to_rgba8` 用 `(v+128)/257`（= round(v*255/65535)）四舍五入
        // 缩放，非简单 >>8。pixel(x,y)=(x*1000+y*100, x*400+y*900, x*700+y*300)。
        let (out, w, h) = decode_png(PNG_RGB16_4X4).expect("16bit RGB 应解码成功");
        assert_eq!((w, h), (4, 4));
        assert_eq!(out.len(), 64, "16bit 输入经 to_rgba8 后输出仍为 RGBA8");
        assert_eq!(px_at(&out, w, 0, 0), [0, 0, 0, 255]);
        assert_eq!(px_at(&out, w, 1, 0), [4, 2, 3, 255]); // (1000,400,700)→((1000+128)/257,(400+128)/257,(700+128)/257)
        assert_eq!(px_at(&out, w, 0, 1), [0, 4, 1, 255]); // (100,900,300)→((228)/257,(1028)/257,(428)/257)
        assert_eq!(px_at(&out, w, 1, 1), [4, 5, 4, 255]); // (1100,1300,1000)→(1228/257,1428/257,1128/257)
        assert_eq!(px_at(&out, w, 3, 3), [13, 15, 12, 255]); // (3300,3900,3000)→(3428/257,4028/257,3128/257)
    }

    #[test]
    fn adam7_interlaced_decodes() {
        // Adam7 隔行：还原 8x8 全分辨率像素。
        let (out, w, h) = decode_png(PNG_INTERLACED_ADAM7_8X8).expect("Adam7 隔行应解码成功");
        assert_eq!((w, h), (8, 8));
        assert_eq!(out.len(), 8 * 8 * 4);
        assert_eq!(px_at(&out, w, 0, 0), [0, 0, 0, 255]);
        assert_eq!(px_at(&out, w, 7, 0), [217, 0, 105, 255]);
        assert_eq!(px_at(&out, w, 0, 7), [0, 203, 105, 255]);
        assert_eq!(px_at(&out, w, 7, 7), [217, 203, 0, 255]);
        assert_eq!(px_at(&out, w, 4, 3), [124, 87, 105, 255]); // 4^3=7 → 7*15=105
    }

    #[test]
    fn one_bit_and_four_bit_depth_decode() {
        // 位深 1（黑白灰度）与位深 4（调色板）。
        let (out, w, h) = decode_png(PNG_1BIT_4X4).expect("1bit 应解码成功");
        assert_eq!((w, h), (4, 4));
        assert_eq!(out.len(), 64);
        assert_eq!(px_at(&out, w, 0, 0), [0, 0, 0, 255]); // (0+0)%2=0 → 黑
        assert_eq!(px_at(&out, w, 1, 0), [255, 255, 255, 255]); // 白

        let (out, w, h) = decode_png(PNG_P4BIT_4X4).expect("4bit 调色板应解码成功");
        assert_eq!((w, h), (4, 4));
        assert_eq!(out.len(), 64);
        assert_eq!(px_at(&out, w, 0, 0), [0, 0, 0, 255]);
        assert_eq!(px_at(&out, w, 1, 0), [1, 1, 1, 255]);
        assert_eq!(px_at(&out, w, 0, 1), [4, 4, 4, 255]);
        assert_eq!(px_at(&out, w, 3, 3), [7, 7, 7, 255]); // 15%8=7
    }

    #[test]
    fn truncated_input_returns_error_without_panic() {
        // 截断到一半（切进 IDAT）：解码失败返回 -2，不 panic。
        let truncated = &PNG_RGB8_4X4[..PNG_RGB8_4X4.len() / 2];
        let err = decode_png(truncated).expect_err("截断 PNG 应返回错误");
        assert_eq!(err, -2, "解码失败应为 STATUS_DECODE_FAILED");
    }

    #[test]
    fn non_png_input_returns_error() {
        let err = decode_png(b"not a png file").expect_err("非 PNG 应返回错误");
        assert_eq!(err, -2);
        let err = decode_png(&[]).expect_err("空输入应返回错误");
        assert_eq!(err, -2);
    }

    #[test]
    fn oversize_ihdr_returns_too_large() {
        // 伪造 IHDR 声明 10000x10000（合法 CRC）：像素数 1e8 > 8192²，返回 -7 不 panic。
        let err = decode_png(PNG_OVERSIZE_IHDR_10000).expect_err("超限 IHDR 应返回 STATUS_TOO_LARGE");
        assert_eq!(err, -7);
    }

    #[test]
    fn dimension_threshold_boundary() {
        // 边界：8192×8192 恰在限内不拒绝；任一维越界即超限（函数级阈值测试）。
        assert!(!super::is_oversized(8192, 8192), "8192² 恰为上限，不应超限");
        assert!(super::is_oversized(8192, 8193), "超一像素即超限");
        assert!(super::is_oversized(10000, 10000), "10000² 应超限");
        // u32 极限不溢出（is_oversized 内部使用 u64 乘法）。
        assert!(super::is_oversized(u32::MAX, u32::MAX));
    }
}