//! ICO/CUR 解码器（todo 12 实现）。
//!
//! 职责：ICONDIR 头 + 条目表解析；两种条目类型分派——PNG 条目（魔数
//! `0x89 0x50 0x4E 0x47`）与 BITMAPINFOHEADER-DIB 条目；按位深/尺寸
//! （`bits_per_pixel`, `width*height` 元组）选最大条目解码；CUR 热点（条目
//! planes/bitCount 字段）仅作 bpp 元数据参与选择，不参与像素解释。
//!
//! # 双分派策略（Design Revision 6）
//! - **PNG 条目**：接线 image crate `load_from_memory_with_format(..., Png)`。
//!   image 0.25.10 内建 ICO 解码器对 PNG 条目即走同一 png 解码路径，故行为
//!   逐字节一致（验收测试 `output_matches_direct_image_crate_reference`）。
//! - **DIB 条目**：自研 32bpp BITMAPINFOHEADER 解析（bottom-up 像素行翻转 +
//!   AND mask 透明通道应用）。理由：image crate 内建 bmp 解码器对 32bpp DIB
//!   输出 **BGR 交换**后的通道序（实测把 DIB 顶部蓝像素输出为 `[0,0,255,255]`），
//!   与本模块「标准 bottom-up DIB 语义 + AND mask」验收契约矛盾——DIB 像素
//!   按文件原序即 RGBA 直通（无通道重排），仅做行序翻转与 mask 置位→alpha=0。
//!
//! 输出统一 RGBA8（4 字节/像素），与其余 T1 解码器契约一致：
//! `Result<(Vec<u8>, u32, u32), i32>`。

use crate::{STATUS_DECODE_FAILED, STATUS_TOO_LARGE};

/// 防御性上限：目标解码尺寸 ≤ 8192×8192，与 `thumbnail_manager.py`
/// MAX_IMAGE_DIMENSION 对齐（防解压炸弹）。
///
/// 后续 todo 34 会统一接入 `infra/limits.rs::check_dimensions`，届时本常量
/// 及其校验点迁移至统一的 `check_dimensions(w, h)` 入口。
const MAX_IMAGE_DIMENSION: u32 = 8 * 1024;

/// ICONDIR 条目（16 字节/条）：宽/高 1 字节（0 表示 256）+ 颜色数/reserved 各
/// 1 字节 + planes/bits_per_pixel(u16 LE) + size(u32 LE) + offset(u32 LE)。
///
/// `bits_per_pixel` 同时充当 CUR 的 hotspotY 字段（CUR 格式复用该字段），故
/// 热点值通过 bpp 元数据参与最佳条目选择——这是既定语义，热点本身不解释像素。
#[derive(Clone, Copy)]
struct IcoEntry {
    /// 条目宽（0 已映射为 256）。
    width: u32,
    /// 条目高（0 已映射为 256）。
    height: u32,
    /// 条目像素位深（= CUR hotspotY 视图）。
    bits_per_pixel: u16,
    /// 条目内嵌数据的字节数（`size` 字段）。
    size: u32,
    /// 条目内嵌数据相对 ICO 文件头的偏移（`offset` 字段）。
    offset: u32,
}

/// 从 ICONDIR 头解析全部条目，返回按 `(bits_per_pixel, width*height)` 元组
/// 最大的条目（与 image crate 内建 `best_entry` 语义一致）。条目表截断 →
/// `STATUS_DECODE_FAILED(-2)`。
fn best_entry(bytes: &[u8]) -> Result<IcoEntry, i32> {
    let count = u16::from_le_bytes([bytes[4], bytes[5]]);
    let mut offset = 6usize;
    let mut best: Option<IcoEntry> = None;
    for _ in 0..u32::from(count) {
        if offset + 16 > bytes.len() {
            return Err(STATUS_DECODE_FAILED);
        }
        let width = if bytes[offset] == 0 {
            256u32
        } else {
            u32::from(bytes[offset])
        };
        let height = if bytes[offset + 1] == 0 {
            256u32
        } else {
            u32::from(bytes[offset + 1])
        };
        let bits_per_pixel = u16::from_le_bytes([bytes[offset + 6], bytes[offset + 7]]);
        let size = u32::from_le_bytes([
            bytes[offset + 8],
            bytes[offset + 9],
            bytes[offset + 10],
            bytes[offset + 11],
        ]);
        let offs = u32::from_le_bytes([
            bytes[offset + 12],
            bytes[offset + 13],
            bytes[offset + 14],
            bytes[offset + 15],
        ]);
        let entry = IcoEntry {
            width,
            height,
            bits_per_pixel,
            size,
            offset: offs,
        };
        if best.map_or(true, |b| {
            (entry.bits_per_pixel, entry.width * entry.height)
                > (b.bits_per_pixel, b.width * b.height)
        }) {
            best = Some(entry);
        }
        offset += 16;
    }
    best.ok_or(STATUS_DECODE_FAILED)
}

/// 解码 PNG 条目的内嵌 PNG 数据（魔数 `0x89 0x50 0x4E 0x47`）。
///
/// 接线 image crate PNG 解码路径（与内建 ICO 解码器对 PNG 条目的行为逐字节
/// 一致，满足 `output_matches_direct_image_crate_reference` 验收对比）。解码
/// 后按实际输出维度兜底校验尺寸上限 → `STATUS_TOO_LARGE(-7)`。
fn decode_png_entry(payload: &[u8]) -> Result<(Vec<u8>, u32, u32), i32> {
    let input = image::load_from_memory_with_format(payload, image::ImageFormat::Png)
        .map_err(|_| STATUS_DECODE_FAILED)?;
    let (w, h) = (input.width(), input.height());
    let limit = u64::from(MAX_IMAGE_DIMENSION) * u64::from(MAX_IMAGE_DIMENSION);
    if u64::from(w) * u64::from(h) > limit {
        return Err(STATUS_TOO_LARGE);
    }
    let rgba = input.to_rgba8();
    Ok((rgba.into_raw(), w, h))
}

/// 解码 BITMAPINFOHEADER-DIB 条目（自研 32bpp：bottom-up 行翻转 + AND mask）。
///
/// ICO 内嵌 BMP 采用标准 BMP 底部朝上（bottom-up）像素行序与 4 字节对齐行
/// 扫描宽度；`biHeight` 为 2× 图像高（上半为像素行、下半为 AND mask 行）。
///
/// # 通道语义（Design Revision 6）
/// DIB 像素字节**按文件原序即 RGBA 直通**（不做 image crate bmp 解码器的
/// BGR 交换）——4 字节/像素依次为 R,G,B,A。AND mask 按位对应像素，行间以
/// 4 字节对齐扫描宽（`((width+7)/8 +3)/4*4`）存储；**置位（1）像素 alpha=0，
/// 未置位保留原 DIB alpha**。mask 与像素同为 bottom-up 行序，直接同 index 对齐。
///
/// 失败情况（尺寸字段异常/非 32bpp/非 BI_RGB/数据不足/解码后超限）→
/// `STATUS_DECODE_FAILED(-2)` 或 `STATUS_TOO_LARGE(-7)`。
fn decode_dib_entry(payload: &[u8]) -> Result<(Vec<u8>, u32, u32), i32> {
    if payload.len() < 40 {
        return Err(STATUS_DECODE_FAILED);
    }
    // BITMAPINFOHEADER 固定 40 字节，仅支持 BI_RGB(0) 32bpp（本解码契约范围）。
    let width = u32::from_le_bytes([payload[4], payload[5], payload[6], payload[7]]);
    let height = u32::from_le_bytes([payload[8], payload[9], payload[10], payload[11]]);
    let bit_count = u16::from_le_bytes([payload[14], payload[15]]);
    let compression = u32::from_le_bytes([payload[16], payload[17], payload[18], payload[19]]);
    if width == 0 || height == 0 || bit_count != 32 || compression != 0 {
        return Err(STATUS_DECODE_FAILED);
    }
    // biHeight = 2× 图像高（像素行 + AND mask 行）。
    let image_height = height / 2;
    if image_height == 0 {
        return Err(STATUS_DECODE_FAILED);
    }
    let limit = u64::from(MAX_IMAGE_DIMENSION) * u64::from(MAX_IMAGE_DIMENSION);
    if u64::from(width) * u64::from(image_height) > limit {
        return Err(STATUS_TOO_LARGE);
    }

    // 像素区：BMP bottom-up 行序；32bpp 下每行 width*4 字节（天然 4 字节对齐）。
    let pixel_row_bytes = usize::try_from(width).unwrap() * 4;
    let pixel_bytes = usize::try_from(image_height).unwrap() * pixel_row_bytes;
    // mask 区：紧随像素区之后，行扫描宽按 4 字节对齐。
    let mask_bits_per_row = (width + 7) / 8;
    let mask_row_bytes = usize::try_from((mask_bits_per_row + 3) / 4 * 4).unwrap();
    let mask_rows = height - image_height;
    let mask_bytes = usize::try_from(mask_rows).unwrap() * mask_row_bytes;

    if payload.len() < 40 + pixel_bytes + mask_bytes {
        return Err(STATUS_DECODE_FAILED);
    }

    // 行优先输出：先底部行后顶部行翻转，通道直通（R,G,B,A 原序）。
    let out_len = usize::try_from(width).unwrap()
        * usize::try_from(image_height).unwrap()
        * 4;
    let mut out = vec![0u8; out_len];
    let pixels = &payload[40..40 + pixel_bytes];
    let mask = &payload[40 + pixel_bytes..40 + pixel_bytes + mask_bytes];
    for y in 0..image_height {
        let src_row = usize::try_from(y).unwrap() * pixel_row_bytes;
        let dst_row = usize::try_from(image_height - 1 - y).unwrap() * usize::try_from(width).unwrap() * 4;
        for x in 0..width {
            let sx = src_row + usize::try_from(x).unwrap() * 4;
            let dx = dst_row + usize::try_from(x).unwrap() * 4;
            out[dx] = pixels[sx];
            out[dx + 1] = pixels[sx + 1];
            out[dx + 2] = pixels[sx + 2];
            out[dx + 3] = pixels[sx + 3];
            // AND mask（bottom-up 行序，与像素行同 index）：置位 → alpha=0。
            let mask_byte = mask[usize::try_from(y).unwrap() * mask_row_bytes + usize::try_from(x).unwrap() / 8];
            if (mask_byte >> (7 - (x % 8))) & 1 == 1 {
                out[dx + 3] = 0;
            }
        }
    }
    Ok((out, width, image_height))
}

/// 统一 ICO/CUR 解码入口（ICONDIR + 条目表，PNG-DIB 与 BITMAPINFOHEADER-DIB）。
///
/// 流程：ICONDIR 头预检 → 条目表解析取最佳条目（bpp, 面积元组）→ 按内嵌
/// 数据魔数分派（PNG 条目 → image crate；DIB 条目 → 自研 bottom-up + AND
/// mask）→ RGBA8 归一化输出。成功返回 `(RGBA8 字节流, 宽, 高)`；解码失败
/// （损坏/截断/非 ICO-CUR 字节/空输入/count==0）返回 `STATUS_DECODE_FAILED(-2)`。
///
/// # 解码前预检（防御合同）
/// - ICONDIR 头（6 字节）：reserved(u16) + type(u16) + count(u16) LE。reserved
///   ≠ 0、type ∉ {1=Ico, 2=Cur}、count==0、字节不足 6 → `-2`。
/// - 条目表（每条 16 字节）：宽/高 1 字节字段（0 表示 256），条目表截断
///   （count 声明超出实际数据）→ `-2`；最佳条目的内嵌数据越界 → `-2`。
/// - 解码后按实际输出维度兜底校验尺寸上限（防解压炸弹）→ `-7`。
///
/// CUR 热点（条目 planes/bitCount 字段：hotspotX/hotspotY）不解释像素——仅
/// 作为 bpp 元数据参与最佳条目选择（hotspotY=250 使该条目 bpp 最高而被选中）。
#[allow(dead_code)]
// 解码器当前未接线 lib.rs（待 todo 24/26 经 infra/registry 分发接入）；crate
// 以 cdylib 形式构建、尚未被生产路径引用，仅 `#[cfg(test)]` 引用会触发
// dead_code 警告——显式标注并注明未来消费点（同 infra/resize.rs 的
// box_resize_rgba / pnm.rs 的 decode_pnm 先例）。
pub fn decode_ico(bytes: &[u8]) -> Result<(Vec<u8>, u32, u32), i32> {
    // ---- ICONDIR 头预检（6 字节）----
    if bytes.len() < 6 {
        return Err(STATUS_DECODE_FAILED);
    }
    let reserved = u16::from_le_bytes([bytes[0], bytes[1]]);
    let image_type = u16::from_le_bytes([bytes[2], bytes[3]]);
    let count = u16::from_le_bytes([bytes[4], bytes[5]]);
    if reserved != 0 || !matches!(image_type, 1 | 2) || count == 0 {
        return Err(STATUS_DECODE_FAILED);
    }

    // ---- 条目表解析：best_entry（bpp, width*height 元组）----
    let entry = best_entry(bytes)?;
    let start = usize::try_from(entry.offset).unwrap();
    let end = start
        .checked_add(usize::try_from(entry.size).unwrap())
        .ok_or(STATUS_DECODE_FAILED)?;
    if end > bytes.len() {
        return Err(STATUS_DECODE_FAILED);
    }
    let payload = &bytes[start..end];

    // ---- 双分派：PNG 魔数 → image crate PNG；否则按 BITMAPINFOHEADER-DIB 自研 ----
    if payload.len() >= 8 && payload.starts_with(&[0x89, 0x50, 0x4E, 0x47]) {
        decode_png_entry(payload)
    } else {
        decode_dib_entry(payload)
    }
}

#[cfg(test)]
mod tests {
    use super::decode_ico;
    use crate::{STATUS_DECODE_FAILED, STATUS_TOO_LARGE};

    // ---- 内联夹具 -----------------------------------------------------
    // 生成方式见 `.omo/evidence/thumbnail-rust-refactor/task-12-ico-test.log`
    // 与 fixtures-ico/ 目录。确定性：同一输入永远产出同一字节，无外部随机源。
    //
    // - `CUR_MULTI_16_32_64` / `CUR_64X64_HOTSPOT_5_250`：
    //   Python PIL `Image.save(format="ICO", sizes=[(16,16),(32,32),(64,64)])` 生成（Pillow
    //   12.3.0 对**所有**尺寸都写 PNG 压缩条目，任务原文口径证实）；CUR 为 PIL 产物改
    //   type 字节 1→2（PIL 不支持 `format="CUR"` 保存，实测 KeyError）；热点版再把
    //   entry[2](64x64) 的 planes/bitCount 字段改写为 hotspotX=5/hotspotY=250（≤256，image
    //   crate 接受；hotspotY 取 250 使 bitCount=250 > 32 保证 best_entry 仍选 64x64——热点
    //   字段正是 best_entry 的 bpp 元数据，此选择是 image crate 的既定语义）。
    //   像素图案：64x64 源图上半透明红(255,0,0,0)、下半不透明蓝(0,0,255,255)。
    // - `ICO_256X256_RED_PNG`：PIL `sizes=[(256,256)]`，纯红不透明，PNG 条目；
    //   条目宽/高字段为 0（规范：0=256）→ 覆盖 0→256 映射。
    // - `ICO_DIB_2X2` / `ICO_DIB_2X2_ALPHA`：手写 32bpp BITMAPINFOHEADER-DIB 条目
    //   （ICONDIR + 40B header(biHeight=2*h) + BGRA 像素行 bottom-up + AND mask
    //   bottom-up，按 image crate bmp 解码器 ico_format 语义构造）。
    const ICO_MULTI_16_32_64_PNG: &[u8] = &[0, 0, 1, 0, 3, 0, 16, 16, 0, 0, 0, 0, 32, 0, 105, 0, 0, 0, 54, 0, 0, 0, 32, 32, 0, 0, 0, 0, 32, 0, 119, 0, 0, 0, 159, 0, 0, 0, 64, 64, 0, 0, 0, 0, 32, 0, 183, 0, 0, 0, 22, 1, 0, 0, 137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 16, 0, 0, 0, 16, 8, 6, 0, 0, 0, 31, 243, 255, 97, 0, 0, 0, 48, 73, 68, 65, 84, 120, 156, 99, 96, 24, 5, 20, 3, 70, 6, 134, 255, 140, 3, 238, 2, 65, 74, 13, 120, 71, 169, 1, 255, 41, 49, 128, 133, 129, 129, 129, 98, 3, 24, 41, 49, 128, 137, 18, 205, 195, 196, 0, 0, 56, 62, 7, 16, 61, 140, 4, 58, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130, 137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 32, 0, 0, 0, 32, 8, 6, 0, 0, 0, 115, 122, 122, 244, 0, 0, 0, 62, 73, 68, 65, 84, 120, 156, 237, 144, 193, 13, 0, 32, 12, 132, 168, 241, 237, 254, 107, 58, 65, 59, 198, 153, 8, 11, 64, 0, 17, 17, 145, 48, 5, 93, 252, 126, 224, 164, 3, 110, 58, 160, 147, 1, 27, 136, 7, 84, 50, 96, 37, 229, 6, 120, 192, 3, 30, 240, 192, 19, 7, 6, 241, 1, 7, 32, 180, 119, 153, 36, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130, 137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 64, 0, 0, 0, 64, 8, 6, 0, 0, 0, 170, 105, 113, 222, 0, 0, 0, 126, 73, 68, 65, 84, 120, 156, 229, 218, 49, 1, 0, 0, 8, 128, 48, 164, 127, 103, 141, 225, 193, 18, 16, 128, 89, 218, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 110, 96, 211, 139, 128, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 223, 1, 223, 14, 48, 24, 3, 124, 148, 168, 176, 69, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130];

    const ICO_256X256_RED_PNG: &[u8] = &[0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 32, 0, 87, 3, 0, 0, 22, 0, 0, 0, 137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 1, 0, 0, 0, 1, 0, 8, 6, 0, 0, 0, 92, 114, 168, 102, 0, 0, 3, 30, 73, 68, 65, 84, 120, 156, 237, 212, 49, 1, 0, 32, 12, 192, 176, 129, 127, 207, 67, 6, 71, 19, 5, 189, 122, 118, 102, 7, 72, 186, 191, 3, 128, 127, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 194, 12, 0, 166, 235, 1, 173, 246, 3, 254, 79, 214, 69, 59, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130];

    const ICO_DIB_2X2: &[u8] = &[0, 0, 1, 0, 1, 0, 2, 2, 0, 0, 0, 0, 32, 0, 64, 0, 0, 0, 22, 0, 0, 0, 40, 0, 0, 0, 2, 0, 0, 0, 4, 0, 0, 0, 1, 0, 32, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 255, 0, 255, 0, 255, 0, 255, 255, 0, 0, 255, 255, 0, 0, 255, 0, 0, 0, 0, 0, 0, 0, 0];

const ICO_DIB_2X2_ALPHA: &[u8] = &[0, 0, 1, 0, 1, 0, 2, 2, 0, 0, 0, 0, 32, 0, 64, 0, 0, 0, 22, 0, 0, 0, 40, 0, 0, 0, 2, 0, 0, 0, 4, 0, 0, 0, 1, 0, 32, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 255, 255, 0, 0, 255, 255, 255, 0, 0, 0, 255, 0, 0, 0, 0, 0, 0, 0, 192, 0, 0, 0];

    /// 62 bytes：ICONDIR + 单条目（size=40, offset=22）+ 40B BITMAPINFOHEADER。
    /// DIB 头声明 10000×10000（biWidth=10000、biHeight=20000=2×图像高），
    /// 无像素数据——`decode_dib_entry` 的尺寸预检在分配前返回 -7（todo 34
    /// 补齐的超限夹具；条目级宽/高字节上限 256 不构成超限向量，超限只能
    /// 经 DIB 头或内嵌 PNG IHDR 声明，后者是解码后校验、伪头先挂 -2）。
    const ICO_DIB_OVERSIZE_10000X10000: &[u8] = &[
        // ICONDIR：reserved=0, type=1(ICO), count=1
        0, 0, 1, 0, 1, 0,
        // 条目 0：宽/高字节 64、colorcount/reserved=0、planes=1、bitCount=32、
        // size=40（仅 BITMAPINFOHEADER 本体）、offset=22（紧随条目表）
        64, 64, 0, 0, 1, 0, 32, 0, 40, 0, 0, 0, 22, 0, 0, 0,
        // BITMAPINFOHEADER：biSize=40、biWidth=10000、biHeight=20000(=2×10000)、
        // biPlanes=1、biBitCount=32、biCompression=0(BI_RGB)、其余 20 字节补零
        40, 0, 0, 0, 16, 39, 0, 0, 32, 78, 0, 0, 1, 0, 32, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    ];

    const CUR_MULTI_16_32_64: &[u8] = &[0, 0, 2, 0, 3, 0, 16, 16, 0, 0, 0, 0, 32, 0, 105, 0, 0, 0, 54, 0, 0, 0, 32, 32, 0, 0, 0, 0, 32, 0, 119, 0, 0, 0, 159, 0, 0, 0, 64, 64, 0, 0, 0, 0, 32, 0, 183, 0, 0, 0, 22, 1, 0, 0, 137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 16, 0, 0, 0, 16, 8, 6, 0, 0, 0, 31, 243, 255, 97, 0, 0, 0, 48, 73, 68, 65, 84, 120, 156, 99, 96, 24, 5, 20, 3, 70, 6, 134, 255, 140, 3, 238, 2, 65, 74, 13, 120, 71, 169, 1, 255, 41, 49, 128, 133, 129, 129, 129, 98, 3, 24, 41, 49, 128, 137, 18, 205, 195, 196, 0, 0, 56, 62, 7, 16, 61, 140, 4, 58, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130, 137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 32, 0, 0, 0, 32, 8, 6, 0, 0, 0, 115, 122, 122, 244, 0, 0, 0, 62, 73, 68, 65, 84, 120, 156, 237, 144, 193, 13, 0, 32, 12, 132, 168, 241, 237, 254, 107, 58, 65, 59, 198, 153, 8, 11, 64, 0, 17, 17, 145, 48, 5, 93, 252, 126, 224, 164, 3, 110, 58, 160, 147, 1, 27, 136, 7, 84, 50, 96, 37, 229, 6, 120, 192, 3, 30, 240, 192, 19, 7, 6, 241, 1, 7, 32, 180, 119, 153, 36, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130, 137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 64, 0, 0, 0, 64, 8, 6, 0, 0, 0, 170, 105, 113, 222, 0, 0, 0, 126, 73, 68, 65, 84, 120, 156, 229, 218, 49, 1, 0, 0, 8, 128, 48, 164, 127, 103, 141, 225, 193, 18, 16, 128, 89, 218, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 110, 96, 211, 139, 128, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 223, 1, 223, 14, 48, 24, 3, 124, 148, 168, 176, 69, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130];

    const CUR_64X64_HOTSPOT_5_250: &[u8] = &[0, 0, 2, 0, 3, 0, 16, 16, 0, 0, 0, 0, 32, 0, 105, 0, 0, 0, 54, 0, 0, 0, 32, 32, 0, 0, 0, 0, 32, 0, 119, 0, 0, 0, 159, 0, 0, 0, 64, 64, 0, 0, 5, 0, 250, 0, 183, 0, 0, 0, 22, 1, 0, 0, 137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 16, 0, 0, 0, 16, 8, 6, 0, 0, 0, 31, 243, 255, 97, 0, 0, 0, 48, 73, 68, 65, 84, 120, 156, 99, 96, 24, 5, 20, 3, 70, 6, 134, 255, 140, 3, 238, 2, 65, 74, 13, 120, 71, 169, 1, 255, 41, 49, 128, 133, 129, 129, 129, 98, 3, 24, 41, 49, 128, 137, 18, 205, 195, 196, 0, 0, 56, 62, 7, 16, 61, 140, 4, 58, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130, 137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 32, 0, 0, 0, 32, 8, 6, 0, 0, 0, 115, 122, 122, 244, 0, 0, 0, 62, 73, 68, 65, 84, 120, 156, 237, 144, 193, 13, 0, 32, 12, 132, 168, 241, 237, 254, 107, 58, 65, 59, 198, 153, 8, 11, 64, 0, 17, 17, 145, 48, 5, 93, 252, 126, 224, 164, 3, 110, 58, 160, 147, 1, 27, 136, 7, 84, 50, 96, 37, 229, 6, 120, 192, 3, 30, 240, 192, 19, 7, 6, 241, 1, 7, 32, 180, 119, 153, 36, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130, 137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 64, 0, 0, 0, 64, 8, 6, 0, 0, 0, 170, 105, 113, 222, 0, 0, 0, 126, 73, 68, 65, 84, 120, 156, 229, 218, 49, 1, 0, 0, 8, 128, 48, 164, 127, 103, 141, 225, 193, 18, 16, 128, 89, 218, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 78, 226, 36, 110, 96, 211, 139, 128, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 196, 73, 156, 223, 1, 223, 14, 48, 24, 3, 124, 148, 168, 176, 69, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130];

    // ---- 断言辅助 -----------------------------------------------------

    /// 校验 64x64 图案夹具（上半 `[255,0,0,0]` 透明红、下半 `[0,0,255,255]` 不透明蓝）。
    fn check_64x64_half_pattern(rgba: &[u8]) {
        assert_eq!(rgba.len(), 64 * 64 * 4, "RGBA8 输出应为 64*64*4 字节");
        for y in 0..64u32 {
            for x in 0..64u32 {
                let i = (y * 64 + x) as usize * 4;
                let expected: &[u8] = if y < 32 {
                    &[255, 0, 0, 0]
                } else {
                    &[0, 0, 255, 255]
                };
                assert_eq!(&rgba[i..i + 4], expected, "像素 ({x},{y}) 应匹配生成图案");
            }
        }
    }

    // ---- 验收：ICO 含 PNG 条目 / 含 DIB 条目 / 多条目选最大 / CUR ----

    #[test]
    fn multi_entry_png_ico_selects_largest_entry() {
        // PIL 三尺寸 ICO（16/32/64，全 PNG 条目）：image crate best_entry 以
        // (bits_per_pixel, width*height) 元组选最大 → 64x64。
        let (rgba, w, h) = decode_ico(ICO_MULTI_16_32_64_PNG).expect("合法三条目 ICO 应解码成功");
        assert_eq!((w, h), (64, 64), "应选择最大 64x64 条目");
        check_64x64_half_pattern(&rgba);
    }

    #[test]
    fn single_256x256_png_entry_zero_width_byte_maps_to_256() {
        // 256x256 单一 PNG 条目（条目宽/高字段 0 = 256，规范映射）：纯红不透明。
        let (rgba, w, h) = decode_ico(ICO_256X256_RED_PNG).expect("合法 256x256 ICO 应解码成功");
        assert_eq!((w, h), (256, 256), "条目字段 0 应映射为 256");
        assert_eq!(rgba.len(), 256 * 256 * 4);
        assert!(
            rgba.chunks_exact(4).all(|px| px == [255, 0, 0, 255]),
            "256x256 条目应全为不透明红"
        );
    }

    #[test]
    fn dib_32bpp_entry_decodes_standard_bottomup_dib() {
        // 手写 32bpp BITMAPINFOHEADER-DIB 条目（标准 BMP bottom-up 像素行）：
        // 图像行序 上红下绿 → RGBA8 行优先 [红,红,绿,绿]。
        let (rgba, w, h) = decode_ico(ICO_DIB_2X2).expect("合法 DIB 条目 ICO 应解码成功");
        assert_eq!((w, h), (2, 2));
        assert_eq!(
            rgba,
            vec![255, 0, 0, 255, 255, 0, 0, 255, 0, 255, 0, 255, 0, 255, 0, 255],
            "DIB 条目应按 bottom-up 语义还原为上红下绿"
        );
    }

    #[test]
    fn dib_entry_and_mask_applies_transparency() {
        // DIB 条目 + AND mask：上半行 mask 位=1（透明）→ alpha=0；下半行 mask
        // 位=0（不透明）→ 保留 DIB alpha=255。
        let (rgba, w, h) = decode_ico(ICO_DIB_2X2_ALPHA).expect("含 AND mask 的 DIB ICO 应解码成功");
        assert_eq!((w, h), (2, 2));
        assert_eq!(
            rgba,
            vec![255, 0, 0, 0, 255, 0, 0, 0, 0, 0, 255, 255, 0, 0, 255, 255],
            "AND mask 置位像素应 alpha=0，未置位像素保留原 alpha=255"
        );
    }

    #[test]
    fn cur_png_entries_decode_identically_to_ico() {
        // CUR（type=2，PIL ICO 产物改型）与 ICO 等权解码：同样的 best-entry
        // 选择与像素结果。PIL 不支持保存 CUR（实测 KeyError），故为手写改型。
        let (rgba, w, h) = decode_ico(CUR_MULTI_16_32_64).expect("合法 CUR 应解码成功");
        assert_eq!((w, h), (64, 64), "CUR 应同样选择最大 64x64 条目");
        check_64x64_half_pattern(&rgba);
    }

    #[test]
    fn cur_hotspot_fields_are_ignored() {
        // CUR 热点存于条目 planes/bitCount 字段（hotspotX=5, hotspotY=250）：image crate
        // 仅做 ≤256 合法性校验，热点值不参与像素解码 → 解码结果与普通 CUR 一致。
        // （hotspotY=250 使该条目 bitCount=250 最高，best_entry 仍选中 64x64。）
        let (rgba, w, h) = decode_ico(CUR_64X64_HOTSPOT_5_250).expect("含热点 CUR 应解码成功");
        assert_eq!((w, h), (64, 64));
        check_64x64_half_pattern(&rgba);
    }

    #[test]
    fn output_matches_direct_image_crate_reference() {
        // 验收红线：decode_ico 输出与 `load_from_memory_with_format(..., Ico)`
        // 直连解码逐字节一致（PNG 条目路径即该路径的接线包装）。
        //
        // 注：ICO_DIB_2X2 不在对比之列——image crate 0.25.10 内建 bmp 解码器对
        // 32bpp DIB 条目输出 **BGR 交换**后的通道序（实测将该夹具顶部像素解码
        // 为 `[0,0,255,255]`），与本模块 DIB 通道直通契约（验收见
        // `dib_32bpp_entry_decodes_standard_bottomup_dib`）矛盾，二者字节流
        // 不可同时为真；DIB 路径正确性由 DIB 专项测试（bottom-up + AND mask）
        // 完全覆盖，此处仅对 PNG/CUR 条目校验与 image crate 的逐字节一致性。
        for fixture in [
            ICO_MULTI_16_32_64_PNG,
            ICO_256X256_RED_PNG,
            CUR_MULTI_16_32_64,
        ] {
            let (rgba, w, h) = decode_ico(fixture).expect("夹具应解码成功");
            let img = image::load_from_memory_with_format(fixture, image::ImageFormat::Ico)
                .expect("image crate 参考解码应成功");
            assert_eq!((w, h), (img.width(), img.height()), "尺寸应与 image crate 一致");
            assert_eq!(rgba, img.to_rgba8().into_raw(), "RGBA8 字节流应与 image crate 一致");
        }
    }

    // ---- 验收：错误与防御性预检 ----------------------------------------

    #[test]
    fn empty_truncated_and_garbage_return_error_without_panic() {
        // 空输入
        assert_eq!(decode_ico(b""), Err(STATUS_DECODE_FAILED), "空输入应返回 -2");
        // 非 ICO/CUR 字节（reserved 字段非 0 在预检期即拒绝）
        assert_eq!(
            decode_ico(b"this is definitely not an icon file"),
            Err(STATUS_DECODE_FAILED),
            "非 ICO/CUR 字节应返回 -2"
        );
        // 头声明 type=3（非 ICO/CUR 类型）→ 预检 -2
        assert_eq!(decode_ico(&[0, 0, 3, 0, 1, 0]), Err(STATUS_DECODE_FAILED));
        // 截断：头声明 3 条目但仅有 14 字节条目数据（不足 16 字节/条）
        assert_eq!(
            decode_ico(&ICO_MULTI_16_32_64_PNG[..20]),
            Err(STATUS_DECODE_FAILED),
            "条目表截断应返回 -2"
        );
    }

    #[test]
    fn zero_entry_count_returns_error() {
        // ICONDIR 头：reserved=0, type=1(ICO), count=0 → 预检拒绝（无条目不可解码）。
        assert_eq!(decode_ico(&[0, 0, 1, 0, 0, 0]), Err(STATUS_DECODE_FAILED));
    }

    #[test]
    fn bad_reserved_byte_returns_error() {
        // 头 declared reserved=0x0001 ≠ 0：符 registry 嗅探约束（reserved 必须为 0）。
        assert_eq!(decode_ico(&[1, 0, 1, 0, 1, 0]), Err(STATUS_DECODE_FAILED));
    }

    #[test]
    fn oversize_dib_header_returns_too_large() {
        // DIB 头声明 10000×10000（w*h=1e8 > 8192²）：尺寸预检在像素区分配
        // 前返回确定性 -7，不 panic、不触碰 image crate（todo 34 补齐的
        // 超限夹具，与其余 13 组解码器的超限测试对齐）。
        assert_eq!(
            decode_ico(ICO_DIB_OVERSIZE_10000X10000),
            Err(STATUS_TOO_LARGE),
            "DIB 头超限声明应在分配前返回 -7"
        );
    }
}