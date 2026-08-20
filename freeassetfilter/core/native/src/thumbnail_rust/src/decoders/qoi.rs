//! QOI 解码器（todo 9 实现）。
//!
//! 职责：QOIF 魔数、RGBA/RGB 通道序；统一输出 RGBA8；解码尺寸 ≤ 8192×8192。
//!
//! 实现为「接线」（Design Revision 5 point 5）：不自研操作码解析，解码委托
//! image crate 内建 qoi feature（image 0.25.10 → qoi 0.4.1，纯 Rust，静态合并
//! 进 `thumbnail_generator.dll`，MIT/MIT 许可与 AGPL-3.0 兼容）。

/// 解码失败（截断/坏魔数/坏通道序/损坏数据）——与 lib.rs `STATUS_DECODE_FAILED` 同值。
const STATUS_DECODE_FAILED: i32 = -2;
/// 解码尺寸超限——与 lib.rs `STATUS_TOO_LARGE`（-7）同值，todo 27 路由区分依据。
const STATUS_TOO_LARGE: i32 = -7;
/// 解码尺寸上限，与 `thumbnail_manager.py` MAX_IMAGE_DIMENSION=8192 对齐。
const MAX_DIMENSION: u32 = 8192;
/// QOI 文件头长度：`qoif`(4) + w(4) + h(4) + channels(1) + colorspace(1)。
const HEADER_LEN: usize = 14;
/// QOI 魔数。
const QOI_MAGIC: &[u8; 4] = b"qoif";

/// QOI 解码统一入口：image crate 内建解码 → RGBA8 输出。
///
/// 流程：解析 14 字节头（只读尺寸字面量，非操作码解析）→ `w*h > 8192²` 直接
/// 返回 `STATUS_TOO_LARGE`（**解码前拦截**解压炸弹）→ `image::load_from_memory`
/// 解码 → `to_rgba8()` → `into_raw()` → 对实际输出尺寸**解码后再校验**一次兜底。
///
/// 待 registry/decoders 分发接线（各格式 Native 切换）消费，故标 `allow(dead_code)`。
///
/// # 错误
/// - 输入 < 14 字节 / 魔数非 `qoif` / 通道数非 3、4 / w 或 h 为 0 → `STATUS_DECODE_FAILED`
/// - `w*h > 8192²` → `STATUS_TOO_LARGE`
/// - image crate 解码失败（截断/损坏数据）→ `STATUS_DECODE_FAILED`
#[allow(dead_code)]
pub fn decode_qoi(bytes: &[u8]) -> Result<(Vec<u8>, u32, u32), i32> {
    let (w, h) = parse_dimensions(bytes)?;
    // **解码前拦截**：头尺寸超限直接返回，避免给 image crate 喂解压炸弹
    // （10000×10000 头会让 qoi 解码器先分配 ~400MB 再失败）。
    if too_large(w, h) {
        return Err(STATUS_TOO_LARGE);
    }
    // 委托 image crate 内建 qoi 解码（Design Revision 5：不自研操作码解析）。
    let img = image::load_from_memory(bytes).map_err(|_| STATUS_DECODE_FAILED)?;
    let rgba = img.to_rgba8();
    let (rw, rh) = (rgba.width(), rgba.height());
    // **解码后再校验**兜底：防御 image crate 返回的输出尺寸与头声明不一致。
    if too_large(rw, rh) {
        return Err(STATUS_TOO_LARGE);
    }
    Ok((rgba.into_raw(), rw, rh))
}

/// 解析 14 字节 QOI 头：校验魔数/长度/通道序，返回 (w, h)（大端 u32）。
fn parse_dimensions(bytes: &[u8]) -> Result<(u32, u32), i32> {
    if bytes.len() < HEADER_LEN || &bytes[0..4] != QOI_MAGIC {
        return Err(STATUS_DECODE_FAILED);
    }
    let w = u32::from_be_bytes([bytes[4], bytes[5], bytes[6], bytes[7]]);
    let h = u32::from_be_bytes([bytes[8], bytes[9], bytes[10], bytes[11]]);
    // QOI 规范：w/h 必须 > 0，channels 仅 3(RGB)/4(RGBA)。
    if w == 0 || h == 0 || !matches!(bytes[12], 3 | 4) {
        return Err(STATUS_DECODE_FAILED);
    }
    Ok((w, h))
}

/// `w*h > 8192²` 判定（u64 乘法防 u32 溢出）。
fn too_large(w: u32, h: u32) -> bool {
    (w as u64) * (h as u64) > (MAX_DIMENSION as u64) * (MAX_DIMENSION as u64)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 纯色 RLE 夹具：8×8 全白 RGBA。RGBA 操作码(0xFF)置白 + RUN(0xFD=62) +
    /// RUN(0xC0=1)，共 1+62+1=64 像素，全程 RLE 无逐像素数据。
    const SOLID_RLE_8X8: [u8; 29] = [
        b'q', b'o', b'i', b'f', // magic
        0x00, 0x00, 0x00, 0x08, // w=8
        0x00, 0x00, 0x00, 0x08, // h=8
        0x04,                   // channels=4 (RGBA)
        0x00,                   // colorspace=0 (sRGB)
        0xFF, 0xFF, 0xFF, 0xFF, 0xFF, // RGBA 操作码: (255,255,255,255)
        0xFD,                   // RUN run=62
        0xC0,                   // RUN run=1
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, // 结尾 8 字节
    ];

    /// RGB 通道序夹具：2×1，channels=3。RGB 操作码(0xFE)：纯绿 → 纯蓝。
    /// 注意：qoi 0.4.1 的结尾填充（QOI_PADDING）恒为 7×`0x00`+`0x01`，与通道数无关
    /// （规范文本的"RGB 结尾 0x00"未被该 crate 采用——已实测 InvalidPadding）。
    const RGB_CHANNEL_2X1: [u8; 30] = [
        b'q', b'o', b'i', b'f', // magic
        0x00, 0x00, 0x00, 0x02, // w=2
        0x00, 0x00, 0x00, 0x01, // h=1
        0x03,                   // channels=3 (RGB)
        0x00,                   // colorspace=0
        0xFE, 0x00, 0xFF, 0x00, // RGB 操作码: (0,255,0) → alpha 强制 255
        0xFE, 0x00, 0x00, 0xFF, // RGB 操作码: (0,0,255)
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, // qoi crate 结尾填充
    ];

    /// DIFF 渐变夹具：4×4 RGBA。RGBA 操作码置 (255,0,0,255)，随后 15 个 DIFF
    /// (0x6E = r 字段 0b10→dr+2=+0, g 字段 0b11→dg+2=+1, b 字段 0b10→db+2=+0)，
    /// 红绿渐变：第 i 像素 = (255, i, 0, 255)。
    const GRADIENT_DIFF_4X4: [u8; 42] = [
        b'q', b'o', b'i', b'f', // magic
        0x00, 0x00, 0x00, 0x04, // w=4
        0x00, 0x00, 0x00, 0x04, // h=4
        0x04,                   // channels=4
        0x00,                   // colorspace=0
        0xFF, 0xFF, 0x00, 0x00, 0xFF, // RGBA 操作码: (255,0,0,255)
        0x6E, 0x6E, 0x6E, 0x6E, 0x6E, // DIFF ×15（绿色逐像素 +1）
        0x6E, 0x6E, 0x6E, 0x6E, 0x6E,
        0x6E, 0x6E, 0x6E, 0x6E, 0x6E,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, // 结尾 8 字节
    ];

    /// 截断夹具：仅 14 字节头（w=2,h=2,channels=4），无任何像素数据。
    const TRUNCATED_HEADER_ONLY: [u8; 14] = [
        b'q', b'o', b'i', b'f', 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00,
        0x02, 0x04, 0x00,
    ];

    /// 坏魔数夹具：首 4 字节非 `qoif`。
    const BAD_MAGIC: [u8; 14] = [
        b'Q', b'O', b'I', b'F', 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00,
        0x01, 0x04, 0x00,
    ];

    /// 超限夹具：仅 14 字节头，w=10000, h=10000（字面量），10000² > 8192²。
    const OVERSIZED_10000: [u8; 14] = [
        b'q', b'o', b'i', b'f', 0x00, 0x00, 0x27, 0x10, 0x00, 0x00, 0x27,
        0x10, 0x04, 0x00,
    ];

    #[test]
    fn solid_rle_8x8_decodes_to_all_white() {
        let (raw, w, h) = decode_qoi(&SOLID_RLE_8X8).expect("合法纯色 RLE 夹具应解码成功");
        assert_eq!((w, h), (8, 8));
        let expected = vec![0xFFu8; 8 * 8 * 4];
        assert_eq!(raw, expected);
    }

    #[test]
    fn rgb_channel_order_decodes_with_forced_alpha() {
        let (raw, w, h) = decode_qoi(&RGB_CHANNEL_2X1).expect("合法 RGB 夹具应解码成功");
        assert_eq!((w, h), (2, 1));
        // channels=3 → alpha 强制 255
        assert_eq!(raw, vec![0x00, 0xFF, 0x00, 0xFF, 0x00, 0x00, 0xFF, 0xFF]);
    }

    #[test]
    fn gradient_diff_4x4_decodes_row_major() {
        let (raw, w, h) = decode_qoi(&GRADIENT_DIFF_4X4).expect("合法 DIFF 夹具应解码成功");
        assert_eq!((w, h), (4, 4));
        let mut expected: Vec<u8> = Vec::with_capacity(4 * 4 * 4);
        for i in 0u8..16 {
            expected.extend_from_slice(&[0xFF, i, 0x00, 0xFF]);
        }
        assert_eq!(raw, expected);
    }

    #[test]
    fn truncated_header_only_returns_decode_failed() {
        assert_eq!(decode_qoi(&TRUNCATED_HEADER_ONLY), Err(-2));
    }

    #[test]
    fn bad_magic_returns_decode_failed() {
        assert_eq!(decode_qoi(&BAD_MAGIC), Err(-2));
        // 不足 14 字节也不 panic
        assert_eq!(decode_qoi(b"qoif\x00\x00"), Err(-2));
    }

    #[test]
    fn oversized_dimensions_return_too_large() {
        assert_eq!(decode_qoi(&OVERSIZED_10000), Err(-7));
    }

    #[test]
    fn zero_dimensions_return_decode_failed() {
        // w=0 或 h=0 违反 QOI 规范，返回解码失败而非超限
        let mut zero_w = SOLID_RLE_8X8;
        zero_w[4..8].copy_from_slice(&[0x00, 0x00, 0x00, 0x00]);
        assert_eq!(decode_qoi(&zero_w), Err(-2));
    }
}