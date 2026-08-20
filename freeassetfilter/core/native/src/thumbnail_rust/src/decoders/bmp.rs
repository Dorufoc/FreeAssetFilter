//! BMP 解码器（todo 10 实现）。
//!
//! 职责：BITMAPCOREHEADER/BITMAPINFOHEADER/BITMAPV4HEADER/BITMAPV5HEADER；
//! 1/4/8/24/32bpp；RLE8/RLE4 压缩；CLUT 调色板；自底向上行序（负高度顶行序）；
//! V4/V5 走同一逻辑；`BM` 魔数解码、`BA` 数组魔数由 image crate 拒绝（-2）；
//! 截断/越界 CLUT 调色板大小报错不 panic。
//!
//! **纯接线实现（Design Revision 5 选型，同 qoi/tga/gif/png 先例）**：不自研
//! BMP 解析——Cargo.toml 已启用 `image = { features=["bmp"] }`，image 0.25.10
//! 内建 bmp codec（四种头、1/4/8/24/32bpp、RLE8/RLE4、CLUT 读取恒补 256 项、
//! 底/顶行序翻转、V4/V5 位域与 alpha 掩码全部内建）。本模块只做两件事：
//! ① 解码前按文件头/DIB 头读取宽高做解压炸弹防御（与 `infra/limits.rs` 目标
//!    及 `thumbnail_manager.py` MAX_IMAGE_DIMENSION=8192 对齐，解压炸弹拦截
//!    在进入 image crate 分配像素缓冲之前返回 `-7`）；
//! ② 委托 `image::load_from_memory` → `to_rgba8` → `into_raw` 输出统一 RGBA8。
//!
//! 错误契约：维度超限（`w*h > 8192*8192`）返回 `STATUS_TOO_LARGE(-7)`；其余
//! 一切解码失败（输入不足/魔数非 BM/BA、截断、坏 DIB 头、RLE 码流损坏、
//! 越界 CLUT 大小即 `colors_used > 1<<bit_count` 触发 PaletteSizeExceeded）均
//! 返回 `STATUS_DECODE_FAILED(-2)`——与 `legacy_image_decode.rs` 既有错误码
//! 语义一致，全部不 panic。
//!
//! 文件超 250 纯行门阈属 SIZE_OK：plans 强制的「内联夹具」（PIL 真实产物 +
//! 手写 RLE4/RLE8/V4 位域/顶行序/BA/超限/坏 CLUT 大小变体，约 2KB fixture
//! 数据表）+ 计划强制的单测内联于同文件（同 infra/registry.rs / tga.rs 先例；
//! fixture 可由生成脚本
//! `.omo/evidence/thumbnail-rust-refactor/task-10-gen-bmp-fixtures.py` 复现，
//! 输出见该目录 `bmp_fixtures_out.txt`）。

use crate::{STATUS_DECODE_FAILED, STATUS_TOO_LARGE};

/// 目标解码尺寸上限（与 `thumbnail_manager.py` MAX_IMAGE_DIMENSION=8192 对齐；
/// todo 34 统一入口 `infra/limits.rs::check_dimensions` 落地后移交）。
const MAX_DIMENSION: u32 = 8192;
/// 像素数上限 `8192*8192`（u64 常量，避免 u32 乘法溢出）。
const MAX_PIXELS: u64 = MAX_DIMENSION as u64 * MAX_DIMENSION as u64;
/// BMP 文件头最小长度（`BM` + 文件大小 + 保留 + 像素数据偏移 = 14 字节）。
const FILE_HEADER_LEN: usize = 14;
/// DIB 头大小字段在文件头中的偏移（u32 LE，区分 BITMAPCOREHEADER 12 与 INFO/V4/V5）。
const DIB_SIZE_OFFSET: usize = 14;
/// BITMAPCOREHEADER 的 DIB 大小（12 字节：w/h 为 u16）。
const DIB_CORE_SIZE: u32 = 12;
/// 宽度字段偏移（INFO/V4/V5 为 i32 LE；CORE 为 u16 LE）。
const WIDTH_OFFSET: usize = 18;
/// 高度字段偏移（INFO/V4/V5 为 i32 LE，可为负=顶行序；CORE 为 u16 LE）。
const HEIGHT_OFFSET: usize = 22;

/// 解码 BMP 字节流为 RGBA8，返回 `(RGBA8 像素, 宽, 高)`。
///
/// # 错误
/// - `STATUS_DECODE_FAILED(-2)`：空输入、魔数非 `BM`/`BA`、image crate 解码
///   失败（截断/DIB 头损坏/RLE 码流损坏/`colors_used > 1<<bit_count` 越界 CLUT
///   大小等）——不 panic。
/// - `STATUS_TOO_LARGE(-7)`：文件/DIB 头声明的 `w*h > 8192*8192`（解压炸弹
///   防御，在进入 image crate 分配像素缓冲之前返回）。
#[allow(dead_code)]
// 当前 crate 为 cdylib：本函数由 todo 8-22 解码器接线（registry 分发路由）消费，
// 在此之前仅 `#[cfg(test)]` 引用——显式标注避免 dead_code 警告
// （同 infra/resize.rs / registry.rs / tga.rs 先例）。
pub fn decode_bmp(bytes: &[u8]) -> Result<(Vec<u8>, u32, u32), i32> {
    if bytes.is_empty() || bytes.len() < FILE_HEADER_LEN {
        return Err(STATUS_DECODE_FAILED);
    }
    // 魔数预检：`BM` 标准 BMP 可解码；`BA` 数组 BMP 也放行（image crate 对 BA
    // 报读头签名错误 → 返回 -2）。其余魔数直接拒绝。
    if &bytes[0..2] != b"BM" && &bytes[0..2] != b"BA" {
        return Err(STATUS_DECODE_FAILED);
    }
    // 解压炸弹防御：解码前读取头声明的宽高，超限直接拒绝，不交给 image 分配内存。
    // 读不到宽/高（头不完整/未知 DIB 布局）则跳过预检，交由 image crate 判定。
    if let Some((w, h)) = bmp_dimensions(bytes) {
        if is_oversized(w, h) {
            return Err(STATUS_TOO_LARGE);
        }
    }
    // 委托 image crate 内建 BMP 解码（Design Revision 5：不自研 DIB/RLE 解析）。
    let img = image::load_from_memory(bytes).map_err(|_| STATUS_DECODE_FAILED)?;
    let rgba = img.to_rgba8();
    let (w, h) = (rgba.width(), rgba.height());
    // 解码后再校验兜底：防御 image crate 返回的输出尺寸与头声明不一致。
    if is_oversized(w, h) {
        return Err(STATUS_TOO_LARGE);
    }
    Ok((rgba.into_raw(), w, h))
}

/// 读取 BMP 文件/DIB 头声明的宽高（解压炸弹防御用，非完整 BMP 解析）。
///
/// 返回 `None` 表示头不完整或未知 DIB 布局（跳过预检，交由 image crate 判定）。
/// 负高度（顶行序）取其绝对值作为高度；`i32::MIN`/非正宽度视为畸形，返回
/// `None`（image crate 将返回解码失败而非泄放异常大分配）。
fn bmp_dimensions(bytes: &[u8]) -> Option<(u32, u32)> {
    if bytes.len() < FILE_HEADER_LEN + 4 {
        return None; // 不足 DIB 大小字段
    }
    let dib_size = u32::from_le_bytes(bytes[DIB_SIZE_OFFSET..DIB_SIZE_OFFSET + 4].try_into().ok()?);
    if dib_size == DIB_CORE_SIZE {
        // BITMAPCOREHEADER：宽高为 u16（offset 18/20），行序恒自底向上。
        let need = WIDTH_OFFSET + 2; // 读 w(2) + h(2) = 22 字节
        if bytes.len() < need {
            return None;
        }
        let w = u32::from(u16::from_le_bytes([bytes[WIDTH_OFFSET], bytes[WIDTH_OFFSET + 1]]));
        let h = u32::from(u16::from_le_bytes([bytes[HEIGHT_OFFSET - 2], bytes[HEIGHT_OFFSET - 1]]));
        if w == 0 || h == 0 {
            return None;
        }
        Some((w, h))
    } else {
        // INFO/V4/V5（及未识别的 >12 尺寸）：宽高为 i32（offset 18/22），
        // 高度可为负（顶行序，取绝对值）。i32::MIN 无法取 abs，视为畸形。
        let need = HEIGHT_OFFSET + 4; // 读 w(4) + h(4) = 26 字节
        if bytes.len() < need {
            return None;
        }
        let w = i32::from_le_bytes(bytes[WIDTH_OFFSET..WIDTH_OFFSET + 4].try_into().ok()?);
        let h = i32::from_le_bytes(bytes[HEIGHT_OFFSET..HEIGHT_OFFSET + 4].try_into().ok()?);
        if w <= 0 || h == i32::MIN {
            return None;
        }
        Some((w as u32, h.unsigned_abs()))
    }
}

/// 像素数是否超限（u64 乘法，避免 u32 溢出）。
fn is_oversized(w: u32, h: u32) -> bool {
    u64::from(w) * u64::from(h) > MAX_PIXELS
}

#[cfg(test)]
mod tests {
    use super::{decode_bmp, is_oversized, MAX_DIMENSION};
    use crate::{STATUS_DECODE_FAILED, STATUS_TOO_LARGE};

    // ===== 内联夹具（PIL 12.3 生成 + 手写，见 `task-10-gen-bmp-fixtures.py`）=====

    /// 78 bytes — PIL 1bpp：8x4 棋盘 (x+y)%2 → 索引0=黑,1=白。
    const BMP_1BPP_8X4: &[u8] = &[
        66, 77, 78, 0, 0, 0, 0, 0, 0, 0, 62, 0,
        0, 0, 40, 0, 0, 0, 8, 0, 0, 0, 4, 0,
        0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 16, 0,
        0, 0, 196, 14, 0, 0, 196, 14, 0, 0, 2, 0,
        0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 255, 255,
        255, 0, 170, 0, 0, 0, 85, 0, 0, 0, 170, 0,
        0, 0, 85, 0, 0, 0
    ];

    /// 1110 bytes — PIL 8bpp 调色板：7x4，7 色调色板 index=(x+y)%7。
    const BMP_8BPP_PALETTE_7X4: &[u8] = &[
        66, 77, 86, 4, 0, 0, 0, 0, 0, 0, 54, 4,
        0, 0, 40, 0, 0, 0, 7, 0, 0, 0, 4, 0,
        0, 0, 1, 0, 8, 0, 0, 0, 0, 0, 32, 0,
        0, 0, 196, 14, 0, 0, 196, 14, 0, 0, 0, 1,
        0, 0, 0, 1, 0, 0, 0, 0, 255, 0, 0, 255,
        0, 0, 255, 0, 0, 0, 0, 255, 255, 0, 255, 255,
        0, 0, 255, 0, 255, 0, 255, 255, 255, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 4,
        5, 6, 0, 1, 2, 0, 2, 3, 4, 5, 6, 0,
        1, 0, 1, 2, 3, 4, 5, 6, 0, 0, 0, 1,
        2, 3, 4, 5, 6, 0
    ];

    /// 198 bytes — PIL 24bpp RGB：8x6 pixel=(x*30, y*40, (x+y)*20) mod 256。
    const BMP_24BPP_8X6: &[u8] = &[
        66, 77, 198, 0, 0, 0, 0, 0, 0, 0, 54, 0,
        0, 0, 40, 0, 0, 0, 8, 0, 0, 0, 6, 0,
        0, 0, 1, 0, 24, 0, 0, 0, 0, 0, 144, 0,
        0, 0, 196, 14, 0, 0, 196, 14, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 100, 200, 0, 120, 200, 30,
        140, 200, 60, 160, 200, 90, 180, 200, 120, 200, 200, 150,
        220, 200, 180, 240, 200, 210, 80, 160, 0, 100, 160, 30,
        120, 160, 60, 140, 160, 90, 160, 160, 120, 180, 160, 150,
        200, 160, 180, 220, 160, 210, 60, 120, 0, 80, 120, 30,
        100, 120, 60, 120, 120, 90, 140, 120, 120, 160, 120, 150,
        180, 120, 180, 200, 120, 210, 40, 80, 0, 60, 80, 30,
        80, 80, 60, 100, 80, 90, 120, 80, 120, 140, 80, 150,
        160, 80, 180, 180, 80, 210, 20, 40, 0, 40, 40, 30,
        60, 40, 60, 80, 40, 90, 100, 40, 120, 120, 40, 150,
        140, 40, 180, 160, 40, 210, 0, 0, 0, 20, 0, 30,
        40, 0, 60, 60, 0, 90, 80, 0, 120, 100, 0, 150,
        120, 0, 180, 140, 0, 210
    ];

    /// 174 bytes — PIL 32bpp RGBA（BI_RGB）：6x5。image crate 将 32bpp BI_RGB
    /// 读为 RGB32（alpha 字节被丢弃 → 输出 alpha=255）。
    const BMP_32BPP_BI_RGB_6X5: &[u8] = &[
        66, 77, 174, 0, 0, 0, 0, 0, 0, 0, 54, 0,
        0, 0, 40, 0, 0, 0, 6, 0, 0, 0, 5, 0,
        0, 0, 1, 0, 32, 0, 0, 0, 0, 0, 120, 0,
        0, 0, 196, 14, 0, 0, 196, 14, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 120, 200, 0, 80, 140, 200,
        40, 120, 160, 200, 80, 160, 180, 200, 120, 200, 200, 200,
        160, 240, 220, 200, 200, 24, 90, 150, 0, 60, 110, 150,
        40, 100, 130, 150, 80, 140, 150, 150, 120, 180, 170, 150,
        160, 220, 190, 150, 200, 4, 60, 100, 0, 40, 80, 100,
        40, 80, 100, 100, 80, 120, 120, 100, 120, 160, 140, 100,
        160, 200, 160, 100, 200, 240, 30, 50, 0, 20, 50, 50,
        40, 60, 70, 50, 80, 100, 90, 50, 120, 140, 110, 50,
        160, 180, 130, 50, 200, 220, 0, 0, 0, 0, 20, 0,
        40, 40, 40, 0, 80, 80, 60, 0, 120, 120, 80, 0,
        160, 160, 100, 0, 200, 200
    ];

    /// 154 bytes — 手写 BITMAPV4HEADER(108) BI_BITFIELDS 32bpp：4x2，RGBA 掩码
    /// (r=0xFF0000,g=0xFF00,b=0xFF,a=0xFF000000)。真 alpha 保留（RGBA32）。
    const BMP_V4_BITFIELDS_32BPP_4X2: &[u8] = &[
        66, 77, 0, 0, 0, 0, 0, 0, 0, 0, 122, 0,
        0, 0, 108, 0, 0, 0, 4, 0, 0, 0, 2, 0,
        0, 0, 1, 0, 32, 0, 3, 0, 0, 0, 0, 0,
        0, 0, 19, 11, 0, 0, 19, 11, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 255, 0, 0, 255,
        0, 0, 255, 0, 0, 0, 0, 0, 0, 255, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 30, 60, 0, 0, 60, 60, 50, 40, 90, 60,
        100, 80, 120, 60, 150, 120, 0, 0, 0, 0, 30, 0,
        50, 40, 60, 0, 100, 80, 90, 0, 150, 120
    ];

    /// 134 bytes — 手写 4bpp：4x4，16 色调色板 index=(x+y)%16，无压缩。
    const BMP_4BPP_4X4: &[u8] = &[
        66, 77, 0, 0, 0, 0, 0, 0, 0, 0, 118, 0,
        0, 0, 40, 0, 0, 0, 4, 0, 0, 0, 4, 0,
        0, 0, 1, 0, 4, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 19, 11, 0, 0, 19, 11, 0, 0, 16, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 48, 32,
        16, 0, 96, 64, 32, 0, 144, 96, 48, 0, 192, 128,
        64, 0, 240, 160, 80, 0, 32, 192, 96, 0, 80, 224,
        112, 0, 128, 0, 128, 0, 176, 32, 144, 0, 224, 64,
        160, 0, 16, 96, 176, 0, 64, 128, 192, 0, 112, 160,
        208, 0, 160, 192, 224, 0, 208, 224, 240, 0, 52, 86,
        0, 0, 35, 69, 0, 0, 18, 52, 0, 0, 1, 35,
        0, 0
    ];

    /// 78 bytes — 手写 RLE8：4x2，3 色调色板，compr=1。RLE 流：
    /// 底行全绿(4,1)+EOL / 顶行 红×2(2,0)+蓝×2(2,2)+EOL / EOF。
    const BMP_RLE8_4X2: &[u8] = &[
        66, 77, 0, 0, 0, 0, 0, 0, 0, 0, 66, 0,
        0, 0, 40, 0, 0, 0, 4, 0, 0, 0, 2, 0,
        0, 0, 1, 0, 8, 0, 1, 0, 0, 0, 0, 0,
        0, 0, 19, 11, 0, 0, 19, 11, 0, 0, 3, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 255, 0, 0, 255,
        0, 0, 255, 0, 0, 0, 4, 1, 0, 0, 2, 0,
        2, 2, 0, 0, 0, 1
    ];

    /// 112 bytes — 手写 RLE4：4x4，8 色调色板，compr=2。行 y 像素索引=(y+x)%8，
    /// 每行用 absolute 模式 `00 04 b0 b1 00 00`（4 像素=2 字节）+ EOF(00 01)。
    const BMP_RLE4_4X4: &[u8] = &[
        66, 77, 0, 0, 0, 0, 0, 0, 0, 0, 86, 0,
        0, 0, 40, 0, 0, 0, 4, 0, 0, 0, 4, 0,
        0, 0, 1, 0, 4, 0, 2, 0, 0, 0, 0, 0,
        0, 0, 19, 11, 0, 0, 19, 11, 0, 0, 8, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 255, 0, 0, 255,
        0, 0, 255, 0, 0, 0, 0, 255, 255, 0, 255, 255,
        0, 0, 255, 0, 255, 0, 128, 128, 128, 0, 255, 255,
        255, 0, 0, 4, 52, 86, 0, 0, 0, 4, 35, 69,
        0, 0, 0, 4, 18, 52, 0, 0, 0, 4, 1, 35,
        0, 0, 0, 1
    ];

    /// 90 bytes — 手写顶行序：24bpp 3x3 负高度 -3，行按视觉顺序存储。
    const BMP_TOP_DOWN_24BPP_3X3: &[u8] = &[
        66, 77, 0, 0, 0, 0, 0, 0, 0, 0, 54, 0,
        0, 0, 40, 0, 0, 0, 3, 0, 0, 0, 253, 255,
        255, 255, 1, 0, 24, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 19, 11, 0, 0, 19, 11, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 30, 0, 50,
        60, 0, 100, 0, 0, 0, 30, 70, 0, 60, 70, 50,
        90, 70, 100, 0, 0, 0, 60, 140, 0, 90, 140, 50,
        120, 140, 100, 0, 0, 0
    ];

    /// 90 bytes — BA 数组魔数变体（合法 24bpp 体，仅魔数 BM→BA）。
    const BMP_BA_MAGIC_24BPP: &[u8] = &[
        66, 65, 0, 0, 0, 0, 0, 0, 0, 0, 54, 0,
        0, 0, 40, 0, 0, 0, 3, 0, 0, 0, 253, 255,
        255, 255, 1, 0, 24, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 19, 11, 0, 0, 19, 11, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 30, 0, 50,
        60, 0, 100, 0, 0, 0, 30, 70, 0, 60, 70, 50,
        90, 70, 100, 0, 0, 0, 60, 140, 0, 90, 140, 50,
        120, 140, 100, 0, 0, 0
    ];

    /// 54 bytes — 超限头：BITMAPINFOHEADER 声明 9000x9000（w*h=81e6 > 8192²）。
    const BMP_OVERSIZE_9000X9000: &[u8] = &[
        66, 77, 0, 0, 0, 0, 0, 0, 0, 0, 54, 0,
        0, 0, 40, 0, 0, 0, 40, 35, 0, 0, 40, 35,
        0, 0, 1, 0, 24, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 19, 11, 0, 0, 19, 11, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0
    ];

    /// 74 bytes — 越界 CLUT 大小：8bpp 声明 colors_used=300 > 2^8=256
    /// （image crate get_palette_size → PaletteSizeExceeded → -2）。
    const BMP_8BPP_BAD_CLUT_SIZE_300: &[u8] = &[
        66, 77, 0, 0, 0, 0, 0, 0, 0, 0, 66, 0,
        0, 0, 40, 0, 0, 0, 4, 0, 0, 0, 2, 0,
        0, 0, 1, 0, 8, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 19, 11, 0, 0, 19, 11, 0, 0, 44, 1,
        0, 0, 0, 0, 0, 0, 0, 0, 255, 0, 0, 255,
        0, 0, 255, 0, 0, 0, 1, 1, 1, 1, 0, 0,
        0, 2
    ];

    /// 42 bytes — 手写 BITMAPCOREHEADER(12B) 24bpp：2x2 pixel=(x*40,y*50,(x+y)*20)。
    const BMP_CORE_24BPP_2X2: &[u8] = &[
        66, 77, 0, 0, 0, 0, 0, 0, 0, 0, 26, 0,
        0, 0, 12, 0, 0, 0, 2, 0, 2, 0, 1, 0,
        24, 0, 20, 50, 0, 40, 50, 40, 0, 0, 0, 0,
        0, 20, 0, 40, 0, 0
    ];

    /// 调色板 7 色（索引 0..6）。源 RGB 顺序。
    const PAL7: [[u8; 3]; 7] = [
        [255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 0],
        [0, 255, 255], [255, 0, 255], [255, 255, 255],
    ];

    /// 读取 RGBA8 缓冲中 (x,y)（输出坐标，解码后顶行在 y=0）的 4 通道值。
    fn rgba_at(data: &[u8], w: u32, x: u32, y: u32) -> [u8; 4] {
        let i = ((y * w + x) * 4) as usize;
        [data[i], data[i + 1], data[i + 2], data[i + 3]]
    }

    #[test]
    fn decodes_1bpp_checkerboard() {
        let (data, w, h) = decode_bmp(BMP_1BPP_8X4).expect("PIL 1bpp BMP 应解码成功");
        assert_eq!((w, h), (8, 4));
        assert_eq!(data.len(), 8 * 4 * 4);
        // (x+y)%2：偶→黑(0,0,0,255)，奇→白(255,255,255,255)。
        for y in 0..4 {
            for x in 0..8 {
                let exp = if (x + y) % 2 == 0 {
                    [0, 0, 0, 255]
                } else {
                    [255, 255, 255, 255]
                };
                assert_eq!(rgba_at(&data, w, x, y), exp, "1bpp 像素 ({x},{y})");
            }
        }
    }

    #[test]
    fn decodes_8bpp_palette() {
        let (data, w, h) = decode_bmp(BMP_8BPP_PALETTE_7X4).expect("PIL 8bpp 调色板 BMP 应解码成功");
        assert_eq!((w, h), (7, 4));
        assert_eq!(data.len(), 7 * 4 * 4);
        for y in 0..4 {
            for x in 0..7 {
                let c = PAL7[((x + y) % 7) as usize];
                assert_eq!(
                    rgba_at(&data, w, x, y),
                    [c[0], c[1], c[2], 255],
                    "8bpp 像素 ({x},{y}) 应展开为调色板色"
                );
            }
        }
    }

    #[test]
    fn decodes_24bpp_rgb() {
        let (data, w, h) = decode_bmp(BMP_24BPP_8X6).expect("PIL 24bpp BMP 应解码成功");
        assert_eq!((w, h), (8, 6));
        for y in 0..6 {
            for x in 0..8 {
                let r = (x * 30) % 256;
                let g = (y * 40) % 256;
                let b = ((x + y) * 20) % 256;
                assert_eq!(
                    rgba_at(&data, w, x, y),
                    [r as u8, g as u8, b as u8, 255],
                    "24bpp 像素 ({x},{y})"
                );
            }
        }
    }

    #[test]
    fn decodes_32bpp_bi_rgb_drops_alpha() {
        // BI_RGB 32bpp：image crate 读作 RGB32（num_channels=3），alpha 字节被
        // 跳过，输出 alpha=255（源像素 alpha 不保留）。
        let (data, w, h) = decode_bmp(BMP_32BPP_BI_RGB_6X5).expect("PIL 32bpp BMP 应解码成功");
        assert_eq!((w, h), (6, 5));
        for y in 0..5 {
            for x in 0..6 {
                let r = (x * 40) % 256;
                let g = (y * 50) % 256;
                let b = (x * 20 + y * 30) % 256;
                assert_eq!(
                    rgba_at(&data, w, x, y),
                    [r as u8, g as u8, b as u8, 255],
                    "BI_RGB 32bpp 像素 ({x},{y}) 应 RGB 不变、alpha 强制 255"
                );
            }
        }
    }

    #[test]
    fn decodes_32bpp_v4_bitfields_preserves_alpha() {
        // V4 BI_BITFIELDS 带 alpha 掩码 → 真 alpha 保留（与 BI_RGB 的 alpha 丢弃
        // 形成对照，验证 V4 走 RGBA32 路径）。
        let (data, w, h) = decode_bmp(BMP_V4_BITFIELDS_32BPP_4X2).expect("V4 位域 BMP 应解码成功");
        assert_eq!((w, h), (4, 2));
        for y in 0..2 {
            for x in 0..4 {
                let r = (x * 50) % 256;
                let g = (y * 60) % 256;
                let b = ((x + y) * 30) % 256;
                let a = (x * 40) % 256;
                assert_eq!(
                    rgba_at(&data, w, x, y),
                    [r as u8, g as u8, b as u8, a as u8],
                    "V4 位域像素 ({x},{y}) 应含真实 alpha"
                );
            }
        }
    }

    #[test]
    fn decodes_4bpp_palette() {
        let (data, w, h) = decode_bmp(BMP_4BPP_4X4).expect("手写 4bpp BMP 应解码成功");
        assert_eq!((w, h), (4, 4));
        for y in 0..4 {
            for x in 0..4 {
                let i = (x + y) % 16;
                let r = (i * 16) % 256;
                let g = (i * 32) % 256;
                let b = (i * 48) % 256;
                assert_eq!(
                    rgba_at(&data, w, x, y),
                    [r as u8, g as u8, b as u8, 255],
                    "4bpp 像素 ({x},{y})"
                );
            }
        }
    }

    #[test]
    fn decodes_rle8_compressed() {
        // RLE8：3 色调色板。输出顶行 红红蓝蓝；底行 全绿。
        let (data, w, h) = decode_bmp(BMP_RLE8_4X2).expect("RLE8 BMP 应解码成功");
        assert_eq!((w, h), (4, 2));
        let expected: &[[u8; 4]] = &[
            [255, 0, 0, 255], [255, 0, 0, 255], [0, 0, 255, 255], [0, 0, 255, 255],
            [0, 255, 0, 255], [0, 255, 0, 255], [0, 255, 0, 255], [0, 255, 0, 255],
        ];
        for y in 0..2 {
            for x in 0..4 {
                assert_eq!(
                    rgba_at(&data, w, x, y),
                    expected[(y * 4 + x) as usize],
                    "RLE8 像素 ({x},{y})"
                );
            }
        }
    }

    #[test]
    fn decodes_rle4_compressed() {
        // RLE4：8 色调色板，像素索引 = (y+x)%8（absolute 模式逐行）。
        let (data, w, h) = decode_bmp(BMP_RLE4_4X4).expect("RLE4 BMP 应解码成功");
        assert_eq!((w, h), (4, 4));
        let pal: [[u8; 3]; 8] = [
            [255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 0],
            [0, 255, 255], [255, 0, 255], [128, 128, 128], [255, 255, 255],
        ];
        for y in 0..4 {
            for x in 0..4 {
                let c = pal[((y + x) % 8) as usize];
                assert_eq!(
                    rgba_at(&data, w, x, y),
                    [c[0], c[1], c[2], 255],
                    "RLE4 像素 ({x},{y})"
                );
            }
        }
    }

    #[test]
    fn decodes_top_down_negative_height() {
        // 负高度（顶行序）：行按视觉顺序存储，image crate 自动翻转输出。
        let (data, w, h) = decode_bmp(BMP_TOP_DOWN_24BPP_3X3).expect("顶行序 BMP 应解码成功");
        assert_eq!((w, h), (3, 3));
        for y in 0..3 {
            for x in 0..3 {
                let r = (x * 50) % 256;
                let g = (y * 70) % 256;
                let b = ((x + y) * 30) % 256;
                assert_eq!(
                    rgba_at(&data, w, x, y),
                    [r as u8, g as u8, b as u8, 255],
                    "顶行序像素 ({x},{y})"
                );
            }
        }
    }

    #[test]
    fn decodes_core_header() {
        // BITMAPCOREHEADER（12B DIB）：宽高为 u16，24bpp 无调色板。
        let (data, w, h) = decode_bmp(BMP_CORE_24BPP_2X2).expect("CORE 头 BMP 应解码成功");
        assert_eq!((w, h), (2, 2));
        for y in 0..2 {
            for x in 0..2 {
                let r = (x * 40) % 256;
                let g = (y * 50) % 256;
                let b = ((x + y) * 20) % 256;
                assert_eq!(rgba_at(&data, w, x, y), [r as u8, g as u8, b as u8, 255], "CORE ({x},{y})");
            }
        }
    }

    #[test]
    fn ba_magic_returns_decode_failed() {
        // BA 数组魔数：image crate read_file_header 只认 BM → 解码失败 -2，不 panic。
        assert_eq!(decode_bmp(BMP_BA_MAGIC_24BPP), Err(STATUS_DECODE_FAILED));
        // 其他魔数 / 空 / 不足文件头都返回 -2。
        assert_eq!(decode_bmp(b""), Err(STATUS_DECODE_FAILED));
        assert_eq!(decode_bmp(b"\x50\x4e\x47"), Err(STATUS_DECODE_FAILED));
        assert_eq!(decode_bmp(&BMP_24BPP_8X6[..4]), Err(STATUS_DECODE_FAILED));
    }

    #[test]
    fn bad_clut_size_returns_decode_failed() {
        // colors_used=300 > 256 → PaletteSizeExceeded → -2。
        assert_eq!(decode_bmp(BMP_8BPP_BAD_CLUT_SIZE_300), Err(STATUS_DECODE_FAILED));
    }

    #[test]
    fn oversize_header_returns_too_large() {
        // 9000x9000 头声明的像素数超 8192² → 预检返回 -7，不进入 image 分配。
        assert_eq!(decode_bmp(BMP_OVERSIZE_9000X9000), Err(STATUS_TOO_LARGE));
    }

    #[test]
    fn truncated_pixel_data_returns_error_without_panic() {
        // 截断到像素区中部 → image crate 解码失败 -2，不 panic。
        let full = BMP_24BPP_8X6;
        for cut in [14usize, 32, 54, 80, full.len() / 2, full.len() - 1] {
            let result = decode_bmp(&full[..cut]);
            assert!(
                matches!(result, Err(STATUS_DECODE_FAILED)),
                "截断到 {cut} 字节应返回 -2，得到 {result:?}"
            );
        }
    }

    #[test]
    fn dimension_threshold_boundary() {
        // 边界：8192² 恰在限内不拒绝；越界即超限（函数级阈值测试）。
        assert!(!is_oversized(8192, 8192), "8192² 恰为上限，不应超限");
        assert!(is_oversized(8192, 8193), "超一像素即超限");
        assert!(is_oversized(9000, 9000), "9000² 应超限");
        assert!(is_oversized(u32::MAX, u32::MAX), "u32 极值不溢出");
    }

    /// 全部有效夹具经本包装解码后与 image crate 直解（基准路径）逐字节一致。
    #[test]
    fn wrapper_matches_raw_image_crate_for_all_fixtures() {
        let fixtures: &[&[u8]] = &[
            BMP_1BPP_8X4,
            BMP_8BPP_PALETTE_7X4,
            BMP_24BPP_8X6,
            BMP_32BPP_BI_RGB_6X5,
            BMP_V4_BITFIELDS_32BPP_4X2,
            BMP_4BPP_4X4,
            BMP_RLE8_4X2,
            BMP_RLE4_4X4,
            BMP_TOP_DOWN_24BPP_3X3,
            BMP_CORE_24BPP_2X2,
        ];
        for (i, bytes) in fixtures.iter().enumerate() {
            let got = decode_bmp(bytes).expect("有效夹具应解码成功");
            let baseline = image::load_from_memory(bytes)
                .expect("image crate 直解应成功")
                .to_rgba8();
            assert_eq!(got.1, baseline.width(), "夹具 {i} 宽度应一致");
            assert_eq!(got.2, baseline.height(), "夹具 {i} 高度应一致");
            assert_eq!(got.0, baseline.into_raw(), "夹具 {i} 像素应逐字节一致");
        }
    }
}