//! DDS 解码器（todo 21 实现）。
//!
//! 职责：`DDS ` 魔数 + DDS_HEADER(124B) + DX10 扩展头解析；BC1-BC5 解压为
//! 统一 RGBA8 输出；BC6H/BC7/未压缩/未知类型返回 `STATUS_UNSUPPORTED` 交 T3。
//!
//! **实现策略（Design Revision 5 / 当前任务定稿）**：
//! - **BC1-BC3**：委托 image crate（`image::load_from_memory` → `to_rgba8`）——
//!   与既有 legacy 路径同源，输出与改造前逐字节一致；image 0.25 的 dds feature
//!   内建 DXT1/3/5（及 DX10 70-78），但要求宽高为 4 的倍数（`DxtDecoder::new`
//!   对非 4 倍数返回 `DimensionMismatch`），故**非 4 倍数尺寸回退 bcdec_rs 手动
//!   解码**（手动路径自带边缘裁剪，支持任意尺寸）。
//! - **BC4/BC5**：bcdec_rs（`bcdec_rs = "0.2"`，MIT 纯 Rust no_std，BC1-7 全覆盖，
//!   ScanMountGoat/image_dds 分拆）手动解码——image crate 不支持 BC4/5
//!   （`src/codecs/dds.rs` 的 fourCC 匹配表仅 DXT1/3/5 + DX10 70-78）。选型理由
//!   与 AGPL-3.0 兼容性核对见 `.omo/notepads/thumbnail-rust-refactor/decisions.md`。
//! - **BC7 未实现 → `STATUS_UNSUPPORTED`(-6)**（交 T3，不 panic）。
//!
//! 防御上限：声明尺寸 `w*h > 8192×8192` → `STATUS_TOO_LARGE`(-7)（与
//! `thumbnail_manager.py` MAX_IMAGE_DIMENSION 对齐）；块数据截断/头损坏 →
//! `STATUS_DECODE_FAILED`(-2)。解码路径零 `unwrap()`，不 panic。
//!
//! SIZE_OK：本文件含计划强制的内联 `#[cfg(test)]` 夹具（≥6 条 DDS 测试）与
//! BC 格式数据表，纯 LOC 超过 250 门槛属计划强制内联测试的合理例外
//! （同 infra/resize.rs / infra/registry.rs 先例，模块单一职责：DDS 解码器）。

use crate::{STATUS_DECODE_FAILED, STATUS_TOO_LARGE, STATUS_UNSUPPORTED};

/// 解码尺寸上限（与 thumbnail_manager.py MAX_IMAGE_DIMENSION=8192 对齐）。
const MAX_DIM: u64 = 8192;

/// 解析得到的 BC 变体（决定块大小与解码路径）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum DdsVariant {
    Bc1,
    Bc2,
    Bc3,
    Bc4,
    Bc5,
    Bc7,
}

impl DdsVariant {
    /// 每 4x4 块的压缩字节数。
    fn block_bytes(self) -> usize {
        match self {
            DdsVariant::Bc1 | DdsVariant::Bc4 => 8,
            DdsVariant::Bc2 | DdsVariant::Bc3 | DdsVariant::Bc5 | DdsVariant::Bc7 => 16,
        }
    }
}

/// 统一入口：`bytes` 为完整 DDS 文件，成功返回 `(RGBA8, 宽, 高)`。
///
/// 失败返回结构化 `i32` 状态码：`-2` 解码失败（魔数/头/块数据损坏截断）、
/// `-6` 不支持（BC7/BC6H/未压缩/未知类型）、`-7` 声明尺寸超限。
///
/// `#[allow(dead_code)]` + 注释：todo 8-22 解码器由 registry/上层路由接线前
/// 仅测试引用（同 infra/resize.rs / infra/registry.rs 先例）。
#[allow(dead_code)]
pub fn decode_dds(bytes: &[u8]) -> Result<(Vec<u8>, u32, u32), i32> {
    if bytes.len() < 128 || !bytes.starts_with(b"DDS ") || le_u32(bytes, 4) != 124 {
        return Err(STATUS_DECODE_FAILED);
    }
    let width = le_u32(bytes, 16);
    let height = le_u32(bytes, 12);
    if width == 0 || height == 0 {
        return Err(STATUS_DECODE_FAILED);
    }
    // 解压炸弹防御：先于任何解码/分配检查声明尺寸。
    if u64::from(width) * u64::from(height) > MAX_DIM * MAX_DIM {
        return Err(STATUS_TOO_LARGE);
    }
    let (variant, is_signed, data_off) = parse_dds_variant(bytes)?;
    match variant {
        DdsVariant::Bc7 => Err(STATUS_UNSUPPORTED),
        DdsVariant::Bc1 | DdsVariant::Bc2 | DdsVariant::Bc3 => {
            decode_image_first(bytes, width, height, variant, is_signed, data_off)
        }
        DdsVariant::Bc4 | DdsVariant::Bc5 => {
            decode_bcdec_manual(bytes, width, height, variant, is_signed, data_off)
        }
    }
}

/// 解析像素格式：返回 `(BC 变体, 是否 signed, 块数据起始偏移)`。
///
/// `ddspf.fourCC`（offset 84）判定 legacy 格式；`DX10` fourCC 续读
/// 20 字节 DXT10 头并在 offset 128 取 `dxgiFormat` 做 DXGI 映射。
/// BC7（fourCC `BC7 ` 或 DXGI 98-100）与 BC6H（95-97）在此识别——
/// BC7 返回变体由上层映射 `-6`，BC6H/未知格式直接 `-6`。
fn parse_dds_variant(bytes: &[u8]) -> Result<(DdsVariant, bool, usize), i32> {
    let fourcc = &bytes[84..88];
    if !(tag_eq(fourcc, *b"DX10")) {
        return match fourcc {
            fourcc if tag_eq(fourcc, *b"DXT1") => Ok((DdsVariant::Bc1, false, 128)),
            // DXT2=DXT3 premultiplied、DXT4=DXT5 premultiplied：块数据形态相同。
            fourcc if tag_eq(fourcc, *b"DXT2") || tag_eq(fourcc, *b"DXT3") => {
                Ok((DdsVariant::Bc2, false, 128))
            }
            fourcc if tag_eq(fourcc, *b"DXT4") || tag_eq(fourcc, *b"DXT5") => {
                Ok((DdsVariant::Bc3, false, 128))
            }
            fourcc if tag_eq(fourcc, *b"ATI1") || tag_eq(fourcc, *b"BC4U") => {
                Ok((DdsVariant::Bc4, false, 128))
            }
            fourcc if tag_eq(fourcc, *b"BC4S") => Ok((DdsVariant::Bc4, true, 128)),
            fourcc if tag_eq(fourcc, *b"ATI2") || tag_eq(fourcc, *b"BC5U") => {
                Ok((DdsVariant::Bc5, false, 128))
            }
            fourcc if tag_eq(fourcc, *b"BC5S") => Ok((DdsVariant::Bc5, true, 128)),
            fourcc if tag_eq(fourcc, *b"BC7 ") => Ok((DdsVariant::Bc7, false, 128)),
            _ => Err(STATUS_UNSUPPORTED),
        };
    }
    // DX10 扩展头（magic + HEADER 124B + DXT10 20B）。
    if bytes.len() < 148 {
        return Err(STATUS_DECODE_FAILED);
    }
    let dxgi = le_u32(bytes, 128);
    // DXGI_FORMAT 枚举值（MS Direct3D 文档）：BC1/2/3 映射到 image 路径，
    // BC4/5（80/81/83/84）映射到 bcdec_rs；98-100=BC7 → -6；95-97=BC6H → -6。
    let (variant, signed) = match dxgi {
        70..=72 => (DdsVariant::Bc1, false),
        73..=75 => (DdsVariant::Bc2, false),
        76..=78 => (DdsVariant::Bc3, false),
        79 | 80 => (DdsVariant::Bc4, false),
        81 => (DdsVariant::Bc4, true),
        82 | 83 => (DdsVariant::Bc5, false),
        84 => (DdsVariant::Bc5, true),
        95..=100 => (DdsVariant::Bc7, false), // BC6H_TYPELESS/UF16/SF16 + BC7 三态
        _ => return Err(STATUS_UNSUPPORTED),
    };
    Ok((variant, signed, 148))
}

/// BC1-BC3 路径：image crate 优先；失败（非 4 倍数尺寸、截断、DX10 拒解等）
/// 回退 bcdec_rs 手动解码。返回 `(RGBA8, 宽, 高)` 或状态码。
fn decode_image_first(
    bytes: &[u8],
    width: u32,
    height: u32,
    variant: DdsVariant,
    is_signed: bool,
    data_off: usize,
) -> Result<(Vec<u8>, u32, u32), i32> {
    // image crate 输出与 legacy 路径逐字节一致（行为零回归）；输出尺寸与
    // 头声明不符时视为不信任（罕见），回退手动路径。
    if let Ok(decoded) = image::load_from_memory(bytes) {
        let rgba = decoded.to_rgba8();
        if rgba.width() == width && rgba.height() == height {
            return Ok((rgba.into_raw(), width, height));
        }
    }
    decode_bcdec_manual(bytes, width, height, variant, is_signed, data_off)
}

/// BC4/BC5 与 BC1-BC3 兜底：按 4x4 块循环调用 bcdec_rs，边缘像素裁剪。
fn decode_bcdec_manual(
    bytes: &[u8],
    width: u32,
    height: u32,
    variant: DdsVariant,
    is_signed: bool,
    data_off: usize,
) -> Result<(Vec<u8>, u32, u32), i32> {
    if bytes.len() < data_off {
        return Err(STATUS_DECODE_FAILED);
    }
    let blocks_x = (width as usize).div_ceil(4);
    let blocks_y = (height as usize).div_ceil(4);
    let block_bytes = variant.block_bytes();
    // 块数据总量（checked：防御 any 溢出）。
    let total_blocks = blocks_x
        .checked_mul(blocks_y)
        .ok_or(STATUS_TOO_LARGE)?;
    let needed = total_blocks
        .checked_mul(block_bytes)
        .ok_or(STATUS_TOO_LARGE)?;
    if bytes.len() - data_off < needed {
        return Err(STATUS_DECODE_FAILED); // 截断
    }
    let out_len = (width as usize)
        .checked_mul(height as usize)
        .and_then(|n| n.checked_mul(4))
        .ok_or(STATUS_TOO_LARGE)?;
    let mut out = vec![0u8; out_len];
    let tex = &bytes[data_off..];
    for by in 0..blocks_y {
        for bx in 0..blocks_x {
            let block = &tex[(by * blocks_x + bx) * block_bytes..][..block_bytes];
            let dst_x = bx * 4;
            let dst_y = by * 4;
            match variant {
                DdsVariant::Bc1 => {
                    let mut tmp = [0u8; 64];
                    bcdec_rs::bc1(block, &mut tmp, 16);
                    blit_rgba(&mut out, width, height, dst_x, dst_y, &tmp);
                }
                DdsVariant::Bc2 => {
                    let mut tmp = [0u8; 64];
                    bcdec_rs::bc2(block, &mut tmp, 16);
                    blit_rgba(&mut out, width, height, dst_x, dst_y, &tmp);
                }
                DdsVariant::Bc3 => {
                    let mut tmp = [0u8; 64];
                    bcdec_rs::bc3(block, &mut tmp, 16);
                    blit_rgba(&mut out, width, height, dst_x, dst_y, &tmp);
                }
                DdsVariant::Bc4 => {
                    // bcdec_rs::bc4 输出 R8（16 字节 = 4x4）；R 复制到 RGB、A=255。
                    let mut tmp = [0u8; 16];
                    bcdec_rs::bc4(block, &mut tmp, 4, is_signed);
                    blit_r8(&mut out, width, height, dst_x, dst_y, &tmp);
                }
                DdsVariant::Bc5 => {
                    // bcdec_rs::bc5 输出 RG8（32 字节 = 4x4）；R/G 原样、B=0、A=255。
                    // BC5 多用于法线贴图（x/y），B 由 shader 重建，缩略图取原始 RG。
                    let mut tmp = [0u8; 32];
                    bcdec_rs::bc5(block, &mut tmp, 8, is_signed);
                    blit_rg8(&mut out, width, height, dst_x, dst_y, &tmp);
                }
                DdsVariant::Bc7 => return Err(STATUS_UNSUPPORTED),
            }
        }
    }
    Ok((out, width, height))
}

/// 将 4x4x4 RGBA 块复制到输出（裁剪到 w×h 边界，处理非 4 倍数尺寸）。
fn blit_rgba(out: &mut [u8], w: u32, h: u32, dst_x: usize, dst_y: usize, block: &[u8]) {
    for py in 0..4usize {
        let y = dst_y + py;
        if y >= h as usize {
            continue;
        }
        for px in 0..4usize {
            let x = dst_x + px;
            if x >= w as usize {
                continue;
            }
            let src = (py * 4 + px) * 4;
            let dst = (y * w as usize + x) * 4;
            out[dst..dst + 4].copy_from_slice(&block[src..src + 4]);
        }
    }
}

/// 将 4x4 R8 块写为 RGBA（R 复制三通道，A=255）。
fn blit_r8(out: &mut [u8], w: u32, h: u32, dst_x: usize, dst_y: usize, block: &[u8]) {
    for py in 0..4usize {
        let y = dst_y + py;
        if y >= h as usize {
            continue;
        }
        for px in 0..4usize {
            let x = dst_x + px;
            if x >= w as usize {
                continue;
            }
            let v = block[py * 4 + px];
            let dst = (y * w as usize + x) * 4;
            out[dst..dst + 4].copy_from_slice(&[v, v, v, 255]);
        }
    }
}

/// 将 4x4 RG8 块写为 RGBA（R/G 原样，B=0，A=255）。
fn blit_rg8(out: &mut [u8], w: u32, h: u32, dst_x: usize, dst_y: usize, block: &[u8]) {
    for py in 0..4usize {
        let y = dst_y + py;
        if y >= h as usize {
            continue;
        }
        for px in 0..4usize {
            let x = dst_x + px;
            if x >= w as usize {
                continue;
            }
            let src = (py * 4 + px) * 2;
            let dst = (y * w as usize + x) * 4;
            out[dst..dst + 4].copy_from_slice(&[block[src], block[src + 1], 0, 255]);
        }
    }
}

/// 小端 u32 读取（绝对偏移，调用方保证长度）。
fn le_u32(b: &[u8], off: usize) -> u32 {
    u32::from_le_bytes([b[off], b[off + 1], b[off + 2], b[off + 3]])
}

/// 4 字节标签比较（&[u8] 切片段 vs 数组字面量）。
fn tag_eq(b: &[u8], tag: [u8; 4]) -> bool {
    b == tag.as_slice()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 拼装传统 DDS（魔数 + 124B 头 + 载荷）。fourCC 写在 offset 84。
    fn legacy_dds(w: u32, h: u32, fourcc: [u8; 4], pitch: u32, payload: &[u8]) -> Vec<u8> {
        let mut d = Vec::with_capacity(128 + payload.len());
        d.extend_from_slice(b"DDS ");
        d.extend_from_slice(&124u32.to_le_bytes()); // dwSize
        d.extend_from_slice(&0x1007u32.to_le_bytes()); // CAPS|HEIGHT|WIDTH|PIXELFORMAT
        d.extend_from_slice(&h.to_le_bytes()); // dwHeight @12
        d.extend_from_slice(&w.to_le_bytes()); // dwWidth @16
        d.extend_from_slice(&pitch.to_le_bytes()); // dwPitchOrLinearSize
        d.extend_from_slice(&[0u8; 8]); // depth + mipmap count
        d.extend_from_slice(&[0u8; 44]); // reserved1
        d.extend_from_slice(&32u32.to_le_bytes()); // ddspf.dwSize
        d.extend_from_slice(&0x4u32.to_le_bytes()); // ddspf.dwFlags = DDPF_FOURCC
        d.extend_from_slice(&fourcc); // ddspf.dwFourCC @84
        d.extend_from_slice(&[0u8; 20]); // RGBBitCount + 4 masks
        d.extend_from_slice(&0x1000u32.to_le_bytes()); // dwCaps = DDSCAPS_TEXTURE
        d.extend_from_slice(&[0u8; 16]); // caps2..4 + reserved2
        d.extend_from_slice(payload);
        d
    }

    /// 拼装 DX10 DDS：传统头（fourCC=DX10）+ 20B DXT10 头 + 载荷。
    fn dx10_dds(w: u32, h: u32, dxgi: u32, payload: &[u8]) -> Vec<u8> {
        let mut d = legacy_dds(w, h, *b"DX10", 0, &[]);
        d.extend_from_slice(&dxgi.to_le_bytes()); // dxgiFormat @128
        d.extend_from_slice(&3u32.to_le_bytes()); // resourceDimension = 3 (2D)
        d.extend_from_slice(&0u32.to_le_bytes()); // miscFlag
        d.extend_from_slice(&1u32.to_le_bytes()); // arraySize
        d.extend_from_slice(&0u32.to_le_bytes()); // miscFlags2
        d.extend_from_slice(payload);
        d
    }

    /// 16 个 3bit 索引（BC4/BC5/DXT5 alpha 索引区），LSB 先行拼 6 字节。
    fn idx3(v: u8) -> [u8; 6] {
        let mut word = 0u64;
        for i in 0..16usize {
            word |= u64::from(v & 0x7) << (i * 3);
        }
        let b = word.to_le_bytes();
        [b[0], b[1], b[2], b[3], b[4], b[5]]
    }

    /// 全像素同色的期望 RGBA。
    fn const_pixel(w: u32, h: u32, px: [u8; 4]) -> Vec<u8> {
        (0..(w * h) as usize)
            .flat_map(|_| px)
            .collect::<Vec<u8>>()
    }

    /// 标准 BC1 颜色块：c0=(255,0,0)(565=0xF800) → c1=(0,255,0)(0x07E0)，
    /// 4 色模式（c0>c1），全部索引=0 → 像素=color0。
    const RED_BLOCK: [u8; 8] = [0x00, 0xF8, 0xE0, 0x07, 0x00, 0x00, 0x00, 0x00];

    #[test]
    fn bc1_dxt1_decodes_and_matches_image() {
        let dds = legacy_dds(4, 4, *b"DXT1", 8, &RED_BLOCK);
        let (rgba, w, h) = decode_dds(&dds).expect("BC1 应解码成功");
        assert_eq!((w, h), (4, 4));
        assert_eq!(rgba, const_pixel(4, 4, [255, 0, 0, 255]));
        // 同一 bytes 与 image crate 逐字节一致（image 路径 + 参考值双验证）。
        let img = image::load_from_memory(&dds).expect("image 应解码 DXT1").to_rgba8();
        assert_eq!(rgba, img.into_raw());
    }

    #[test]
    fn bc2_dxt3_decodes_and_matches_image() {
        // alpha 全 nibble=0xF → 255；颜色块同 BC1 → (255,0,0)。
        let mut block = [0xFFu8; 16];
        block[8..16].copy_from_slice(&RED_BLOCK);
        let dds = legacy_dds(4, 4, *b"DXT3", 16, &block);
        let (rgba, w, h) = decode_dds(&dds).expect("BC2 应解码成功");
        assert_eq!((w, h), (4, 4));
        assert_eq!(rgba, const_pixel(4, 4, [255, 0, 0, 255]));
        let img = image::load_from_memory(&dds).expect("image 应解码 DXT3").to_rgba8();
        assert_eq!(rgba, img.into_raw());
    }

    #[test]
    fn bc3_dxt5_decodes_and_matches_image() {
        // alpha0=255 > alpha1=0，全部 3bit alpha 索引=0 → alpha=255；颜色块同 BC1。
        let mut block = [0u8; 16];
        block[0] = 0xFF;
        block[1] = 0x00;
        block[2..8].copy_from_slice(&idx3(0));
        block[8..16].copy_from_slice(&RED_BLOCK);
        let dds = legacy_dds(4, 4, *b"DXT5", 16, &block);
        let (rgba, w, h) = decode_dds(&dds).expect("BC3 应解码成功");
        assert_eq!((w, h), (4, 4));
        assert_eq!(rgba, const_pixel(4, 4, [255, 0, 0, 255]));
        let img = image::load_from_memory(&dds).expect("image 应解码 DXT5").to_rgba8();
        assert_eq!(rgba, img.into_raw());
    }

    #[test]
    fn bc4_ati1_decodes_known_gray() {
        // r0=128 > r1=64，全部 3bit 索引=1 → R=64；R 复制三通道。
        let mut block = [0u8; 8];
        block[0] = 128;
        block[1] = 64;
        block[2..8].copy_from_slice(&idx3(1));
        let dds = legacy_dds(4, 4, *b"ATI1", 8, &block);
        let (rgba, w, h) = decode_dds(&dds).expect("BC4 应解码成功");
        assert_eq!((w, h), (4, 4));
        assert_eq!(rgba, const_pixel(4, 4, [64, 64, 64, 255]));
        // "BC4U" fourCC 与 ATI1 等价。
        let dds_u = legacy_dds(4, 4, *b"BC4U", 8, &block);
        let (rgba_u, _, _) = decode_dds(&dds_u).expect("BC4U 应解码成功");
        assert_eq!(rgba_u, const_pixel(4, 4, [64, 64, 64, 255]));
    }

    #[test]
    fn bc5_ati2_decodes_known_rg() {
        // 第一 BC4 块 R=64、第二 BC4 块 G=100（r0=200>r1=100，索引=1 → r1=100）；
        // 输出 (R=64, G=100, B=0, A=255)。
        let mut block = [0u8; 16];
        block[0] = 128;
        block[1] = 64;
        block[2..8].copy_from_slice(&idx3(1));
        block[8] = 200;
        block[9] = 100;
        block[10..16].copy_from_slice(&idx3(1));
        let dds = legacy_dds(4, 4, *b"ATI2", 16, &block);
        let (rgba, w, h) = decode_dds(&dds).expect("BC5 应解码成功");
        assert_eq!((w, h), (4, 4));
        assert_eq!(rgba, const_pixel(4, 4, [64, 100, 0, 255]));
        let dds_u = legacy_dds(4, 4, *b"BC5U", 16, &block);
        let (rgba_u, _, _) = decode_dds(&dds_u).expect("BC5U 应解码成功");
        assert_eq!(rgba_u, const_pixel(4, 4, [64, 100, 0, 255]));
    }

    #[test]
    fn non_multiple_of_four_clips_without_panic() {
        // 6x6 → 2x2 块；image crate 拒解（要求 4 的倍数）→ 自动回退 bcdec_rs 裁剪。
        // 块序 (bx,by)：红(0,0)、绿(1,0)、蓝(0,1)、白(1,1)。
        let green = [0xE0u8, 0x07, 0x00, 0x00, 0, 0, 0, 0]; // (0,255,0)
        let blue = [0x1Fu8, 0x00, 0x00, 0x00, 0, 0, 0, 0]; // (0,0,255)
        let white = [0xFFu8, 0xFF, 0x00, 0x00, 0, 0, 0, 0]; // (255,255,255)
        let mut payload = Vec::new();
        payload.extend_from_slice(&RED_BLOCK);
        payload.extend_from_slice(&green);
        payload.extend_from_slice(&blue);
        payload.extend_from_slice(&white);
        let dds = legacy_dds(6, 6, *b"DXT1", 16, &payload);
        let (rgba, w, h) = decode_dds(&dds).expect("6x6 BC1 应解码成功");
        assert_eq!((w, h), (6, 6));
        assert_eq!(rgba.len(), 6 * 6 * 4);
        let px = |x: usize, y: usize| -> [u8; 4] {
            let o = (y * 6 + x) * 4;
            [rgba[o], rgba[o + 1], rgba[o + 2], rgba[o + 3]]
        };
        assert_eq!(px(0, 0), [255, 0, 0, 255]); // 左上整块
        assert_eq!(px(5, 0), [0, 255, 0, 255]); // 右缘裁剪列
        assert_eq!(px(0, 5), [0, 0, 255, 255]); // 底缘裁剪行
        assert_eq!(px(5, 5), [255, 255, 255, 255]); // 右下角
    }

    #[test]
    fn dx10_header_maps_dxgi_formats() {
        // DXGI 71 = BC1_UNORM：走 image 路径并与 image crate 对照。
        let dds = dx10_dds(4, 4, 71, &RED_BLOCK);
        let (rgba, w, h) = decode_dds(&dds).expect("DX10 BC1 应解码成功");
        assert_eq!((w, h), (4, 4));
        assert_eq!(rgba, const_pixel(4, 4, [255, 0, 0, 255]));
        let img = image::load_from_memory(&dds).expect("image 应解码 DX10 BC1").to_rgba8();
        assert_eq!(rgba, img.into_raw());
        // DXGI 80 = BC4_UNORM：bcdec_rs 手动路径。
        let mut block = [0u8; 8];
        block[0] = 128;
        block[1] = 64;
        block[2..8].copy_from_slice(&idx3(1));
        let dds4 = dx10_dds(4, 4, 80, &block);
        let (rgba4, _, _) = decode_dds(&dds4).expect("DX10 BC4 应解码成功");
        assert_eq!(rgba4, const_pixel(4, 4, [64, 64, 64, 255]));
    }

    #[test]
    fn bc7_returns_unsupported() {
        // fourCC "BC7 " → -6（不 panic、不解析块数据）。
        let dds = legacy_dds(4, 4, *b"BC7 ", 16, &[0u8; 16]);
        assert_eq!(decode_dds(&dds), Err(STATUS_UNSUPPORTED));
        // DX10 BC7_UNORM（dxgi=99）同样 -6。BC6H（dxgi=96）亦不支持 → -6。
        let dds10 = dx10_dds(4, 4, 99, &[0u8; 16]);
        assert_eq!(decode_dds(&dds10), Err(STATUS_UNSUPPORTED));
        let dds6h = dx10_dds(4, 4, 96, &[0u8; 16]);
        assert_eq!(decode_dds(&dds6h), Err(STATUS_UNSUPPORTED));
    }

    #[test]
    fn truncated_or_bad_header_returns_decode_failed() {
        // 块数据只有 4 字节（需要 8）→ image 失败 + bcdec 兜底失败 → -2。
        let dds = legacy_dds(4, 4, *b"DXT1", 8, &[0u8; 4]);
        assert_eq!(decode_dds(&dds), Err(STATUS_DECODE_FAILED));
        // 不足 128 字节 → -2。
        assert_eq!(decode_dds(&[0u8; 100]), Err(STATUS_DECODE_FAILED));
        // 非 DDS 魔数 → -2。
        assert_eq!(decode_dds(b"NOT-DDS-PAYLOAD-XXXXXXXX"), Err(STATUS_DECODE_FAILED));
        // dxSize != 124 → -2。
        let dds_bad_size = legacy_dds(4, 4, *b"DXT1", 8, &RED_BLOCK);
        assert_eq!(decode_dds(&dds_bad_size[..4]), Err(STATUS_DECODE_FAILED));
    }

    #[test]
    fn oversized_declared_dims_return_too_large() {
        // 头声明 10000x10000 → -7（任何数据/载荷都不需要，不分配内存）。
        let dds = legacy_dds(10000, 10000, *b"DXT1", 8, &[]);
        assert_eq!(decode_dds(&dds), Err(STATUS_TOO_LARGE));
        // 临界值 8192x8192 在限内（无载荷 → 块数据不足 → -2，而非 -7）。
        let dds_limit = legacy_dds(8192, 8192, *b"DXT1", 8, &[]);
        assert_eq!(decode_dds(&dds_limit), Err(STATUS_DECODE_FAILED));
    }
}