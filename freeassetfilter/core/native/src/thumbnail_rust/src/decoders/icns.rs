//! ICNS 解码器（todo 22 实现；Design Revision 5 落地：引入 `icns = "0.4"`
//! crate，MIT，mdsteele/rust-icns——纯 Rust，静态合并进 thumbnail_generator.dll
//! 无外部 DLL，AGPL-3.0 兼容，选型理由见 .omo/notepads/decisions.md）。
//!
//! 职责：`icns` 魔数 + 条目表解析（`u32 type + u32 len + data` 循环）；
//! **PNG 内嵌条目**（`ic04`-`ic14` 等，payload 为 PNG 字节）解码；**is32+mask
//! 组合**（is32 RGB 通道 + s8mk 掩码合成 alpha）由 icns crate 的
//! `IconFamily::get_icon_with_type` 完成；**JP2/jp2/ic10 类型不解析** → 返回
//! `STATUS_UNSUPPORTED(-6)` 交 T2/T3；多条目**选最大**（像素数最多者）。
//!
//! 委托策略：
//! - icns crate 已识别的 OSType（`icp4`/`icp5`/`icp6`/`ic07`-`ic14`/`is32`+
//!   `s8mk`/`il32`+`l8mk`/`ih32`+`h8mk`/`it32`+`t8mk` 等）→ 直接
//!   `get_icon_with_type` 解码（含掩码合成），经 `convert_to(PixelFormat::RGBA)`
//!   归一化为 RGBA8。crate 0.4 的 `Image` 不提供 `as_png`/`as_rgba` 方法，
//!   `convert_to(PixelFormat::RGBA)` 即等价 RGBA8 输出入口。
//! - icns crate **未识别**的 PNG 条目（`ic04`/`ic05` 等）→ 本模块提取 payload
//!   自行用 image crate 解码（避免耦合 decoders/png.rs；image 0.25 `png`
//!   feature 已在 Cargo.toml 启用）。
//! - `ic10`/`jp2 ` OSType 或任一条目 payload 命中 JPEG 2000 魔数 → 直接返回
//!   `STATUS_UNSUPPORTED`（**在交给 icns crate 之前拦截**：crate 默认启用
//!   `jp2io` feature 会成功解码 JP2，与本模块「jp2 不解析」语义冲突）。
//!
//! 防御：魔数非 `icns`/头不足 → `STATUS_DECODE_FAILED(-2)`；PNG 条目经 PNG 头
//! 预检出宽高 `> 8192` → `STATUS_TOO_LARGE(-7)`（防解压炸弹，与 infra/limits
//! 目标及 thumbnail_manager.py MAX_IMAGE_DIMENSION 对齐）。解码路径零 panic。

use crate::{STATUS_DECODE_FAILED, STATUS_TOO_LARGE, STATUS_UNSUPPORTED};
use std::io::Cursor;

/// 防御上限：目标解码尺寸 ≤ 8192×8192（与 `thumbnail_manager.py`
/// MAX_IMAGE_DIMENSION、todo 34 `infra/limits.rs` 对齐）。
const MAX_IMAGE_DIMENSION: u32 = 8192;
/// ICNS 魔数（4 字节）。
const ICNS_MAGIC: [u8; 4] = *b"icns";
/// PNG 魔数签名（8 字节）。
const PNG_SIGNATURE: [u8; 8] = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];
/// JPEG 2000 魔数（12 字节，与 icns crate `element.rs` 同一定义）。
const JPEG_2000_MAGIC: [u8; 12] =
    [0x00, 0x00, 0x00, 0x0C, 0x6A, 0x50, 0x20, 0x20, 0x0D, 0x0A, 0x87, 0x0A];

/// 一个可解码候选条目（RGBA8 行优先输出）。
struct RgbaCandidate {
    data: Vec<u8>,
    width: u32,
    height: u32,
}

impl RgbaCandidate {
    /// 像素总数（u64 乘法避免溢出；用于「选最大条目」排序）。
    fn pixel_count(&self) -> u64 {
        u64::from(self.width) * u64::from(self.height)
    }
}

#[allow(dead_code)]
// 当前 crate 为 cdylib，`decode_icns` 待 todo 24/26 经 infra/registry 分发接线，
// 现仅 `#[cfg(test)]` 引用——显式标注避免 dead_code 警告（同 pnm/gif/png.rs 先例）。
/// 解码 ICNS 数据为 RGBA8（行优先、每像素 4 字节）。
///
/// # 语义
/// - 条目表逐条扫描：PNG 内嵌条目经 PNG 头预检宽高（>8192 返回 `STATUS_TOO_LARGE`），
///   `ic10`/`jp2 ` 或 JP2 魔数条目返回 `STATUS_UNSUPPORTED`（交 T2/T3）。
/// - 已识别条目委托 icns crate `IconFamily::read`/`get_icon_with_type`（含
///   is32+s8mk 掩码合成）；未识别 PNG 条目（ic04/ic05）由本模块经 image crate 解码。
/// - 多条目**选最大**（像素数最多者；同像素数时保留先出现者）。
/// - 失败返回 `STATUS_DECODE_FAILED(-2)`；不 panic。
pub fn decode_icns(bytes: &[u8]) -> Result<(Vec<u8>, u32, u32), i32> {
    // 头防御：不足 8 字节或魔数不符 → -2。
    if bytes.len() < 8 || &bytes[..4] != &ICNS_MAGIC {
        return Err(STATUS_DECODE_FAILED);
    }
    let declared_len = u32::from_be_bytes([bytes[4], bytes[5], bytes[6], bytes[7]]) as usize;
    // 声明长度必须 ≥ 头长（8）且不越过实际字节（截断文件 → -2）。
    if declared_len < 8 || declared_len > bytes.len() {
        return Err(STATUS_DECODE_FAILED);
    }

    let effective_end = declared_len;
    let mut candidates: Vec<RgbaCandidate> = Vec::new();
    let mut pos = 8usize;

    // 条目表：`4cc type + u32 len(含 8B 头) + data` 循环。
    while pos + 8 <= effective_end {
        let elem_len = u32::from_be_bytes([
            bytes[pos + 4],
            bytes[pos + 5],
            bytes[pos + 6],
            bytes[pos + 7],
        ]) as usize;
        if elem_len < 8 || pos + elem_len > effective_end {
            return Err(STATUS_DECODE_FAILED);
        }
        let ostype = &bytes[pos..pos + 4];
        let payload = &bytes[pos + 8..pos + elem_len];

        // jp2/ic10 类型不解析 → -6（T2/T3 处理）。JP2PNG 条目携带 JPEG 2000
        // 数据时 payload 以 JP2 魔数开头——一并拦截（否则 icns crate 的
        // jp2io feature 会解码成功，违反本模块语义）。
        if ostype == b"ic10" || ostype == b"jp2 " || payload.starts_with(&JPEG_2000_MAGIC) {
            return Err(STATUS_UNSUPPORTED);
        }

        // PNG 内嵌条目：解码前经 PNG 头（IHDR）预检宽高做解压炸弹防御。
        if payload.starts_with(&PNG_SIGNATURE) {
            if let Some((w, h)) = png_dimensions(payload) {
                if is_oversized(w, h) {
                    return Err(STATUS_TOO_LARGE);
                }
            }
            // ic04/ic05 等 icns crate 未识别条目：payload 即完整 PNG，自行解码；
            // 已识别条目（ic07-ic14/icp4-icp6 等）委托 icns crate 处理。
            let known = icns::IconType::from_ostype(icns::OSType([
                ostype[0], ostype[1], ostype[2], ostype[3],
            ]))
            .is_some();
            if !known {
                let (data, w, h) = decode_png_payload(payload)?;
                candidates.push(RgbaCandidate {
                    data,
                    width: w,
                    height: h,
                });
            }
        }
        pos += elem_len;
    }
    if pos != effective_end {
        // 条目表未完整消费声明长度（残留 <8B 的伪条目头）→ 截断。
        return Err(STATUS_DECODE_FAILED);
    }

    // 已识别条目：icns crate 解码（含 is32+s8mk / il32+l8mk / it32+t8mk 掩码合成）。
    let family = match icns::IconFamily::read(Cursor::new(bytes)) {
        Ok(family) => family,
        Err(_) => return Err(STATUS_DECODE_FAILED),
    };
    for icon_type in family.available_icons() {
        let image = match family.get_icon_with_type(icon_type) {
            Ok(image) => image,
            // 损坏/维度不符条目跳过；其余条目仍可产出，不整体失败。
            Err(_) => continue,
        };
        if image.width() > MAX_IMAGE_DIMENSION || image.height() > MAX_IMAGE_DIMENSION {
            return Err(STATUS_TOO_LARGE);
        }
        let rgba = image.convert_to(icns::PixelFormat::RGBA);
        let width = rgba.width();
        let height = rgba.height();
        candidates.push(RgbaCandidate {
            data: rgba.into_data().into_vec(),
            width,
            height,
        });
    }

    // 选最大条目：像素数最多者；同像素数保留先出现者（确定性）。
    // 注意：`Iterator::max_by` 在平局时返回最后一个元素，不符合「tie 保留先
    // 出现」语义——改用 `reduce`，仅当新条目像素数**严格更大**时才替换累加器，
    // 平局/更小时保留先出现的累加器。
    let best = candidates
        .into_iter()
        .reduce(|best, c| if c.pixel_count() > best.pixel_count() { c } else { best });
    match best {
        Some(c) => Ok((c.data, c.width, c.height)),
        None => Err(STATUS_DECODE_FAILED),
    }
}

/// 读取 PNG IHDR 声明的宽高（偏移 16..24，大端）。
///
/// 返回 `None` 表示非 PNG（签名不符）或头不完整（不足 24 字节）。
fn png_dimensions(bytes: &[u8]) -> Option<(u32, u32)> {
    if bytes.len() < 24 || &bytes[..8] != &PNG_SIGNATURE || &bytes[12..16] != b"IHDR" {
        return None;
    }
    let w = u32::from_be_bytes([bytes[16], bytes[17], bytes[18], bytes[19]]);
    let h = u32::from_be_bytes([bytes[20], bytes[21], bytes[22], bytes[23]]);
    Some((w, h))
}

/// 像素数是否超限（u64 乘法，避免 u32 溢出）。
fn is_oversized(w: u32, h: u32) -> bool {
    u64::from(w) * u64::from(h) > u64::from(MAX_IMAGE_DIMENSION) * u64::from(MAX_IMAGE_DIMENSION)
}

/// 解码 PNG payload（ic04/ic05 等 crate 未识别条目），归一化为 RGBA8。
fn decode_png_payload(payload: &[u8]) -> Result<(Vec<u8>, u32, u32), i32> {
    let img = image::load_from_memory(payload).map_err(|_| STATUS_DECODE_FAILED)?;
    let (w, h) = (img.width(), img.height());
    if is_oversized(w, h) {
        return Err(STATUS_TOO_LARGE);
    }
    let rgba = img.to_rgba8();
    Ok((rgba.into_raw(), w, h))
}

#[cfg(test)]
mod tests {
    use super::decode_icns;
    use crate::{STATUS_DECODE_FAILED, STATUS_TOO_LARGE, STATUS_UNSUPPORTED};

    // ---- 内联夹具 -----------------------------------------------------
    // 生成：Python PIL 确定性生成 + 手拼 icns 容器（脚本见 evidence task-22）。
    // - PNG16_RAW: 16x16 RGBA 渐变 pixel(x,y)=(x*16, y*16, (x*y)%256, 255-x*7)
    // - PNG32_RAW: 32x32 纯蓝 (0,0,255,255)；PNG16GREEN_RAW: 16x16 纯绿。
    // - ICNS_*: `icns` + u32 BE 总长 + 条目(`4cc type + u32 len(含8B头) + data`)。
    //   · is32 RLE（16x16 纯红 r=255/g=0/b=0：每通道 run130=[255,v] + run126=[251,v]）
    //   · s8mk 掩码 pixel(x,y)=(x*17+y*31)%256。

    /// PNG16_RAW — 150 bytes。
    const PNG16_RAW: &[u8] = &[
        137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82,
        0, 0, 0, 16, 0, 0, 0, 16, 8, 6, 0, 0, 0, 31, 243, 255,
        97, 0, 0, 0, 93, 73, 68, 65, 84, 120, 156, 165, 204, 57, 14, 128,
        48, 12, 4, 192, 13, 44, 247, 149, 255, 255, 148, 10, 36, 10, 16, 202,
        101, 59, 197, 180, 227, 0, 92, 30, 56, 173, 8, 15, 0, 206, 140, 95,
        208, 152, 240, 31, 180, 106, 12, 3, 170, 48, 30, 116, 98, 76, 7, 189,
        8, 243, 193, 80, 196, 114, 48, 102, 81, 22, 76, 73, 148, 7, 115, 20,
        117, 193, 18, 160, 62, 88, 127, 140, 193, 246, 170, 8, 246, 71, 101, 112,
        224, 6, 83, 98, 22, 140, 97, 176, 161, 37, 0, 0, 0, 0, 73, 69,
        78, 68, 174, 66, 96, 130,
    ];

    /// PNG32_RAW — 108 bytes。
    const PNG32_RAW: &[u8] = &[
        137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82,
        0, 0, 0, 32, 0, 0, 0, 32, 8, 6, 0, 0, 0, 115, 122, 122,
        244, 0, 0, 0, 51, 73, 68, 65, 84, 120, 156, 237, 208, 65, 13, 0,
        0, 8, 3, 177, 129, 127, 207, 16, 84, 240, 233, 12, 220, 210, 74, 102,
        242, 184, 254, 140, 59, 64, 128, 0, 1, 2, 4, 8, 16, 32, 64, 128,
        0, 1, 2, 4, 8, 156, 192, 2, 46, 229, 2, 62, 218, 87, 49, 77,
        0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130,
    ];

    /// PNG16GREEN_RAW — 94 bytes。
    const PNG16GREEN_RAW: &[u8] = &[
        137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82,
        0, 0, 0, 16, 0, 0, 0, 16, 8, 6, 0, 0, 0, 31, 243, 255,
        97, 0, 0, 0, 37, 73, 68, 65, 84, 120, 156, 99, 100, 248, 207, 240,
        159, 129, 2, 192, 68, 137, 230, 81, 3, 32, 128, 137, 129, 66, 192, 52,
        106, 0, 195, 104, 24, 48, 80, 30, 6, 0, 87, 110, 2, 30, 250, 18,
        153, 119, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130,
    ];

    /// ICNS_IC04_PNG — ic04 内嵌 PNG16（16x16）— 166 bytes。
    const ICNS_IC04_PNG: &[u8] = &[
        105, 99, 110, 115, 0, 0, 0, 166, 105, 99, 48, 52, 0, 0, 0, 158,
        137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82,
        0, 0, 0, 16, 0, 0, 0, 16, 8, 6, 0, 0, 0, 31, 243, 255,
        97, 0, 0, 0, 93, 73, 68, 65, 84, 120, 156, 165, 204, 57, 14, 128,
        48, 12, 4, 192, 13, 44, 247, 149, 255, 255, 148, 10, 36, 10, 16, 202,
        101, 59, 197, 180, 227, 0, 92, 30, 56, 173, 8, 15, 0, 206, 140, 95,
        208, 152, 240, 31, 180, 106, 12, 3, 170, 48, 30, 116, 98, 76, 7, 189,
        8, 243, 193, 80, 196, 114, 48, 102, 81, 22, 76, 73, 148, 7, 115, 20,
        117, 193, 18, 160, 62, 88, 127, 140, 193, 246, 170, 8, 246, 71, 101, 112,
        224, 6, 83, 98, 22, 140, 97, 176, 161, 37, 0, 0, 0, 0, 73, 69,
        78, 68, 174, 66, 96, 130,
    ];

    /// ICNS_IC04_IC5_MULTI — ic04(16x16 PNG16) + icp5(32x32 PNG32) — 282 bytes。
    const ICNS_IC04_IC5_MULTI: &[u8] = &[
        105, 99, 110, 115, 0, 0, 1, 26, 105, 99, 48, 52, 0, 0, 0, 158,
        137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82,
        0, 0, 0, 16, 0, 0, 0, 16, 8, 6, 0, 0, 0, 31, 243, 255,
        97, 0, 0, 0, 93, 73, 68, 65, 84, 120, 156, 165, 204, 57, 14, 128,
        48, 12, 4, 192, 13, 44, 247, 149, 255, 255, 148, 10, 36, 10, 16, 202,
        101, 59, 197, 180, 227, 0, 92, 30, 56, 173, 8, 15, 0, 206, 140, 95,
        208, 152, 240, 31, 180, 106, 12, 3, 170, 48, 30, 116, 98, 76, 7, 189,
        8, 243, 193, 80, 196, 114, 48, 102, 81, 22, 76, 73, 148, 7, 115, 20,
        117, 193, 18, 160, 62, 88, 127, 140, 193, 246, 170, 8, 246, 71, 101, 112,
        224, 6, 83, 98, 22, 140, 97, 176, 161, 37, 0, 0, 0, 0, 73, 69,
        78, 68, 174, 66, 96, 130, 105, 99, 112, 53, 0, 0, 0, 116, 137, 80,
        78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0,
        0, 32, 0, 0, 0, 32, 8, 6, 0, 0, 0, 115, 122, 122, 244, 0,
        0, 0, 51, 73, 68, 65, 84, 120, 156, 237, 208, 65, 13, 0, 0, 8,
        3, 177, 129, 127, 207, 16, 84, 240, 233, 12, 220, 210, 74, 102, 242, 184,
        254, 140, 59, 64, 128, 0, 1, 2, 4, 8, 16, 32, 64, 128, 0, 1,
        2, 4, 8, 156, 192, 2, 46, 229, 2, 62, 218, 87, 49, 77, 0, 0,
        0, 0, 73, 69, 78, 68, 174, 66, 96, 130,
    ];

    /// ICNS_IS32_S8MK — is32(纯红 RLE) + s8mk(掩码梯度) — 292 bytes。
    const ICNS_IS32_S8MK: &[u8] = &[
        105, 99, 110, 115, 0, 0, 1, 36, 105, 115, 51, 50, 0, 0, 0, 20,
        255, 255, 251, 255, 255, 0, 251, 0, 255, 0, 251, 0, 115, 56, 109, 107,
        0, 0, 1, 8, 0, 17, 34, 51, 68, 85, 102, 119, 136, 153, 170, 187,
        204, 221, 238, 255, 31, 48, 65, 82, 99, 116, 133, 150, 167, 184, 201, 218,
        235, 252, 13, 30, 62, 79, 96, 113, 130, 147, 164, 181, 198, 215, 232, 249,
        10, 27, 44, 61, 93, 110, 127, 144, 161, 178, 195, 212, 229, 246, 7, 24,
        41, 58, 75, 92, 124, 141, 158, 175, 192, 209, 226, 243, 4, 21, 38, 55,
        72, 89, 106, 123, 155, 172, 189, 206, 223, 240, 1, 18, 35, 52, 69, 86,
        103, 120, 137, 154, 186, 203, 220, 237, 254, 15, 32, 49, 66, 83, 100, 117,
        134, 151, 168, 185, 217, 234, 251, 12, 29, 46, 63, 80, 97, 114, 131, 148,
        165, 182, 199, 216, 248, 9, 26, 43, 60, 77, 94, 111, 128, 145, 162, 179,
        196, 213, 230, 247, 23, 40, 57, 74, 91, 108, 125, 142, 159, 176, 193, 210,
        227, 244, 5, 22, 54, 71, 88, 105, 122, 139, 156, 173, 190, 207, 224, 241,
        2, 19, 36, 53, 85, 102, 119, 136, 153, 170, 187, 204, 221, 238, 255, 16,
        33, 50, 67, 84, 116, 133, 150, 167, 184, 201, 218, 235, 252, 13, 30, 47,
        64, 81, 98, 115, 147, 164, 181, 198, 215, 232, 249, 10, 27, 44, 61, 78,
        95, 112, 129, 146, 178, 195, 212, 229, 246, 7, 24, 41, 58, 75, 92, 109,
        126, 143, 160, 177, 209, 226, 243, 4, 21, 38, 55, 72, 89, 106, 123, 140,
        157, 174, 191, 208,
    ];

    /// ICNS_JP2 — 假 `jp2 ` 条目 — 28 bytes。
    const ICNS_JP2: &[u8] = &[
        105, 99, 110, 115, 0, 0, 0, 28, 106, 112, 50, 32, 0, 0, 0, 20,
        0, 0, 0, 12, 106, 112, 50, 32, 102, 97, 107, 101,
    ];

    /// ICNS_IC10 — `ic10` 条目（JP2 载体类型）— 35 bytes。
    const ICNS_IC10: &[u8] = &[
        105, 99, 110, 115, 0, 0, 0, 35, 105, 99, 49, 48, 0, 0, 0, 27,
        115, 111, 109, 101, 32, 106, 112, 50, 32, 98, 121, 116, 101, 115, 32, 104,
        101, 114, 101,
    ];

    /// ICNS_OVERSIZE — ic04 内嵌 IHDR 声明 10000x10000 的 PNG — 49 bytes。
    const ICNS_OVERSIZE: &[u8] = &[
        105, 99, 110, 115, 0, 0, 0, 49, 105, 99, 48, 52, 0, 0, 0, 41,
        137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82,
        0, 0, 39, 16, 0, 0, 39, 16, 8, 6, 0, 0, 0, 0, 0, 0,
        0,
    ];

    /// ICNS_IC04_GARBAGE_PLUS_PNG — 未知 payload ic04 + 合法 ic04 PNG — 180 bytes。
    const ICNS_IC04_GARBAGE_PLUS_PNG: &[u8] = &[
        105, 99, 110, 115, 0, 0, 0, 180, 105, 99, 48, 52, 0, 0, 0, 14,
        0, 1, 97, 114, 103, 98, 105, 99, 48, 52, 0, 0, 0, 158, 137, 80,
        78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0,
        0, 16, 0, 0, 0, 16, 8, 6, 0, 0, 0, 31, 243, 255, 97, 0,
        0, 0, 93, 73, 68, 65, 84, 120, 156, 165, 204, 57, 14, 128, 48, 12,
        4, 192, 13, 44, 247, 149, 255, 255, 148, 10, 36, 10, 16, 202, 101, 59,
        197, 180, 227, 0, 92, 30, 56, 173, 8, 15, 0, 206, 140, 95, 208, 152,
        240, 31, 180, 106, 12, 3, 170, 48, 30, 116, 98, 76, 7, 189, 8, 243,
        193, 80, 196, 114, 48, 102, 81, 22, 76, 73, 148, 7, 115, 20, 117, 193,
        18, 160, 62, 88, 127, 140, 193, 246, 170, 8, 246, 71, 101, 112, 224, 6,
        83, 98, 22, 140, 97, 176, 161, 37, 0, 0, 0, 0, 73, 69, 78, 68,
        174, 66, 96, 130,
    ];

    /// ICNS_EMPTY — 仅 8 字节头（无条目）— 8 bytes。
    const ICNS_EMPTY: &[u8] = &[105, 99, 110, 115, 0, 0, 0, 8];

    /// ICNS_ICP5_PNG — icp5 内嵌 PNG32（32x32）— 124 bytes。
    const ICNS_ICP5_PNG: &[u8] = &[
        105, 99, 110, 115, 0, 0, 0, 124, 105, 99, 112, 53, 0, 0, 0, 116,
        137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82,
        0, 0, 0, 32, 0, 0, 0, 32, 8, 6, 0, 0, 0, 115, 122, 122,
        244, 0, 0, 0, 51, 73, 68, 65, 84, 120, 156, 237, 208, 65, 13, 0,
        0, 8, 3, 177, 129, 127, 207, 16, 84, 240, 233, 12, 220, 210, 74, 102,
        242, 184, 254, 140, 59, 64, 128, 0, 1, 2, 4, 8, 16, 32, 64, 128,
        0, 1, 2, 4, 8, 156, 192, 2, 46, 229, 2, 62, 218, 87, 49, 77,
        0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130,
    ];

    /// ICNS_IC04_TWO_PNGS — 两个 16x16 ic04（PNG16 + PNG16GREEN）— 268 bytes。
    const ICNS_IC04_TWO_PNGS: &[u8] = &[
        105, 99, 110, 115, 0, 0, 1, 12, 105, 99, 48, 52, 0, 0, 0, 158,
        137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82,
        0, 0, 0, 16, 0, 0, 0, 16, 8, 6, 0, 0, 0, 31, 243, 255,
        97, 0, 0, 0, 93, 73, 68, 65, 84, 120, 156, 165, 204, 57, 14, 128,
        48, 12, 4, 192, 13, 44, 247, 149, 255, 255, 148, 10, 36, 10, 16, 202,
        101, 59, 197, 180, 227, 0, 92, 30, 56, 173, 8, 15, 0, 206, 140, 95,
        208, 152, 240, 31, 180, 106, 12, 3, 170, 48, 30, 116, 98, 76, 7, 189,
        8, 243, 193, 80, 196, 114, 48, 102, 81, 22, 76, 73, 148, 7, 115, 20,
        117, 193, 18, 160, 62, 88, 127, 140, 193, 246, 170, 8, 246, 71, 101, 112,
        224, 6, 83, 98, 22, 140, 97, 176, 161, 37, 0, 0, 0, 0, 73, 69,
        78, 68, 174, 66, 96, 130, 105, 99, 48, 52, 0, 0, 0, 102, 137, 80,
        78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0,
        0, 16, 0, 0, 0, 16, 8, 6, 0, 0, 0, 31, 243, 255, 97, 0,
        0, 0, 37, 73, 68, 65, 84, 120, 156, 99, 100, 248, 207, 240, 159, 129,
        2, 192, 68, 137, 230, 81, 3, 32, 128, 137, 129, 66, 192, 52, 106, 0,
        195, 104, 24, 48, 80, 30, 6, 0, 87, 110, 2, 30, 250, 18, 153, 119,
        0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130,
    ];

    /// 直接解码 PNG（测试参照：证明 ICNS 条目解码与直接解码内嵌 PNG 一致）。
    fn direct_png_rgba(png: &[u8]) -> (Vec<u8>, u32, u32) {
        let img = image::load_from_memory(png).expect("参照 PNG 应可解码");
        let (w, h) = (img.width(), img.height());
        (img.to_rgba8().into_raw(), w, h)
    }

    // ---- 测试 ---------------------------------------------------------

    #[test]
    fn ic04_png_entry_matches_direct_decode() {
        // ic04：icns crate 未识别的 PNG 条目 → 由本模块解码，须与直接解码一致。
        let (data, w, h) = decode_icns(ICNS_IC04_PNG).expect("ic04 PNG 条目应解码成功");
        assert_eq!((w, h), (16, 16));
        let (direct, dw, dh) = direct_png_rgba(PNG16_RAW);
        assert_eq!((dw, dh), (16, 16));
        assert_eq!(data, direct, "ic04 条目解码须等于内嵌 PNG 直接解码结果");
    }

    #[test]
    fn is32_s8mk_mask_composited_to_reference() {
        // is32(纯红 RLE) + s8mk(掩码梯度) → rgba=[255,0,0,(x*17+y*31)%256]。
        let (data, w, h) = decode_icns(ICNS_IS32_S8MK).expect("is32+s8mk 应解码成功");
        assert_eq!((w, h), (16, 16));
        assert_eq!(data.len(), 16 * 16 * 4, "RGBA8 像素数");
        for y in 0..16u32 {
            for x in 0..16u32 {
                let i = (y * 16 + x) as usize * 4;
                let alpha = ((x * 17 + y * 31) % 256) as u8;
                assert_eq!(&data[i..i + 4], &[255, 0, 0, alpha], "像素 ({x},{y})");
            }
        }
    }

    #[test]
    fn multi_entry_selects_largest_icon() {
        // ic04(16x16) + icp5(32x32)：选最大 → 32x32，与直接解码 PNG32 一致。
        let (data, w, h) = decode_icns(ICNS_IC04_IC5_MULTI).expect("多条目应解码成功");
        assert_eq!((w, h), (32, 32), "应选最大条目 icp5 32x32");
        let (direct, _, _) = direct_png_rgba(PNG32_RAW);
        assert_eq!(data, direct);
    }

    #[test]
    fn tie_entries_keep_first_encountered() {
        // 两个 16x16 ic04 PNG：同像素数时保留先出现者（PNG16 渐变，非纯绿）。
        let (data, w, h) = decode_icns(ICNS_IC04_TWO_PNGS).expect("同尺寸多条目应解码");
        assert_eq!((w, h), (16, 16));
        let (direct, _, _) = direct_png_rgba(PNG16_RAW);
        assert_eq!(data, direct, "tie 时应保留先出现的 PNG16");
    }

    #[test]
    fn recognized_icp5_png_entry_decodes() {
        // icp5：crate 已识别的 PNG 条目 → 32x32 纯蓝 (0,0,255,255)。
        let (data, w, h) = decode_icns(ICNS_ICP5_PNG).expect("icp5 应解码成功");
        assert_eq!((w, h), (32, 32));
        assert!(data.chunks_exact(4).all(|px| px == [0, 0, 255, 255]), "icp5 应为纯蓝");
    }

    #[test]
    fn jp2_and_ic10_entries_return_status_unsupported() {
        // jp2/ic10 类型不解析 → -6（T2/T3 处理 JP2）。
        assert_eq!(decode_icns(ICNS_JP2), Err(STATUS_UNSUPPORTED), "jp2 条目 → -6");
        assert_eq!(decode_icns(ICNS_IC10), Err(STATUS_UNSUPPORTED), "ic10 条目 → -6");
    }

    #[test]
    fn oversize_png_entry_returns_status_too_large() {
        // ic04 内嵌 IHDR 声明 10000x10000 的 PNG：PNG 头预检命中 → -7。
        assert_eq!(decode_icns(ICNS_OVERSIZE), Err(STATUS_TOO_LARGE), "超限 PNG → -7");
    }

    #[test]
    fn garbage_ic04_skipped_when_valid_png_present() {
        // 未知 payload（ARGB 子格式）的 ic04 跳过，另一合法 ic04 PNG 正常产出。
        let (data, w, h) = decode_icns(ICNS_IC04_GARBAGE_PLUS_PNG).expect("合法 PNG 条目应解码");
        assert_eq!((w, h), (16, 16));
        let (direct, _, _) = direct_png_rgba(PNG16_RAW);
        assert_eq!(data, direct, "跳过垃圾条目后须解出合法 PNG");
    }

    #[test]
    fn bad_magic_truncated_and_empty_return_error_without_panic() {
        // 魔数不符 / 空 / 截断 / 声明长度越界 → -2；且不 panic。
        assert_eq!(decode_icns(b"not an icns file"), Err(STATUS_DECODE_FAILED));
        assert_eq!(decode_icns(b""), Err(STATUS_DECODE_FAILED));
        assert_eq!(decode_icns(b"icns"), Err(STATUS_DECODE_FAILED));
        assert_eq!(
            decode_icns(&ICNS_IC04_PNG[..40]),
            Err(STATUS_DECODE_FAILED),
            "截断条目 → -2"
        );
        assert_eq!(decode_icns(ICNS_EMPTY), Err(STATUS_DECODE_FAILED), "空家族（仅头）→ -2");
        // 头声明长度越过实际字节（伪造大长度）→ -2。
        let mut fake = b"icns".to_vec();
        fake.extend_from_slice(&[0, 0, 0xFF, 0xFF]);
        assert_eq!(decode_icns(&fake), Err(STATUS_DECODE_FAILED), "伪造长度 → -2");
    }
}

