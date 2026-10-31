//! PNM 解码器（todo 8 实现）。
//!
//! 职责：PBM/PGM/PPM/PAM（P1-P7）解码——纯 ASCII/二进制变体、任意位深按需
//! 归一化到 RGBA8；支持注释/空白解析、8/16bit 样本；截断输入返回错误不 panic。
//!
//! 按 Design Revision 5（todo 7/8 执行），本解码器**不自研 PNM 解析**：
//! 纯接线——`image::load_from_memory`（image 0.25.10 `pnm` feature 已启用，
//! Cargo.toml 确认）内建覆盖 P1-P7 全部变体，含 ASCII/二进制、注释/空白解析、
//! 1-bit/8-bit/16-bit 样本、PAM 任意 depth/tupltype。本模块只做统一入口转发、
//! 维度防御性上限校验与 RGBA8 归一化：解码前先以 `parse_pnm_dimensions` 做
//! **头 token 级**预检（非位级解析），总像素统一经
//! `infra/limits::check_dimensions` 在 image crate 分配前拦截超限；解析失败
//! 的畸形头保持原路径（image 判 -2）。
//!
//! 输出统一 RGBA8（4 字节/像素），与其余 T1 解码器契约一致：
//! `Result<(Vec<u8>, u32, u32), i32>`。

use crate::infra::limits::check_dimensions;
use crate::STATUS_DECODE_FAILED;

/// 读取下一个 PNM ASCII 头 token（跳过空白与 `#` 注释行）。
///
/// 返回 `None` 表示已到输入末尾（解析失败由调用方处理）。
fn next_pnm_token<'a>(bytes: &'a [u8], pos: &mut usize) -> Option<&'a [u8]> {
    loop {
        while *pos < bytes.len() && bytes[*pos].is_ascii_whitespace() {
            *pos += 1;
        }
        if *pos < bytes.len() && bytes[*pos] == b'#' {
            while *pos < bytes.len() && bytes[*pos] != b'\n' {
                *pos += 1;
            }
            continue;
        }
        break;
    }
    if *pos >= bytes.len() {
        return None;
    }
    let start = *pos;
    while *pos < bytes.len() && !bytes[*pos].is_ascii_whitespace() && bytes[*pos] != b'#' {
        *pos += 1;
    }
    Some(&bytes[start..*pos])
}

/// 解析十进制 PNM 维度 token（仅 ASCII 数字；空/非数字/超 u32 → `None`）。
fn parse_pnm_u32(token: &[u8]) -> Option<u32> {
    if token.is_empty() || !token.iter().all(u8::is_ascii_digit) {
        return None;
    }
    std::str::from_utf8(token).ok()?.parse::<u32>().ok()
}

/// 解析 P1-P7 头声明的 `(width, height)`（仅 ASCII 头 token 解析，非位级解码）。
///
/// - P1-P6：magic 后依次读 width/height 两个十进制 token（跳过空白与 `#`
///   注释行）；
/// - P7（PAM）：逐对读取 `KEY VALUE`，取 `WIDTH`/`HEIGHT` 键，`ENDHDR` 终止。
///
/// 任何解析失败（非 PNM / 缺 token / 非数字 / P7 缺 ENDHDR 或 WIDTH/HEIGHT /
/// 超 u32 范围）返回 `None`——调用方保持原路径，把裁决权交给 image crate
/// （损坏文件仍由 image 返回 `STATUS_DECODE_FAILED`）。
fn parse_pnm_dimensions(bytes: &[u8]) -> Option<(u32, u32)> {
    let mut pos = 0usize;
    match next_pnm_token(bytes, &mut pos)? {
        b"P1" | b"P2" | b"P3" | b"P4" | b"P5" | b"P6" => {
            let w = parse_pnm_u32(next_pnm_token(bytes, &mut pos)?)?;
            let h = parse_pnm_u32(next_pnm_token(bytes, &mut pos)?)?;
            Some((w, h))
        }
        b"P7" => {
            let mut w: Option<u32> = None;
            let mut h: Option<u32> = None;
            loop {
                let key = next_pnm_token(bytes, &mut pos)?;
                if key == b"ENDHDR" {
                    break;
                }
                let value = next_pnm_token(bytes, &mut pos)?;
                if key == b"WIDTH" {
                    w = parse_pnm_u32(value);
                } else if key == b"HEIGHT" {
                    h = parse_pnm_u32(value);
                }
            }
            Some((w?, h?))
        }
        _ => None,
    }
}

/// 统一 PNM 解码入口（P1-P7：PBM/PGM/PPM/PAM，ASCII/二进制，8/16bit）。
///
/// 转发 image crate 内建 PNM 解码器，不做任何 PNM 位级/ASCII 解析（Design
/// Revision 5：自研降级为接线）。解码前先解析头声明宽高做解压炸弹防御：
/// 解析成功且 `w*h > 8192×8192` 时在 `image::load_from_memory` **之前**经
/// `infra/limits::check_dimensions` 返回 `STATUS_TOO_LARGE(-7)`（不再分配）；
/// 解析失败的畸形头保持原路径，由 image crate 裁决。成功返回
/// `(RGBA8 字节流, 宽, 高)`；解码失败（损坏/截断/非 PNM 字节/空输入）返回
/// `STATUS_DECODE_FAILED(-2)`。
pub fn decode_pnm(bytes: &[u8]) -> Result<(Vec<u8>, u32, u32), i32> {
    // 预检（安全增强）：头声明宽高解析成功即经统一入口判定，超限在 image
    // crate 分配/解码之前拒绝；解析失败保持原路径（损坏文件由 image 返回 -2）。
    if let Some((w, h)) = parse_pnm_dimensions(bytes) {
        check_dimensions(w, h)?;
    }

    // 内存流经 image 内建 PNM 解码；损坏/截断/空/非 PNM 一并在内报 decode 错误。
    let input = image::load_from_memory(bytes).map_err(|_| STATUS_DECODE_FAILED)?;

    // 解码后二次校验（统一入口兜底）：`load_from_memory` 已产出完整解码图，
    // 此处防御头声明与实际输出尺寸不一致，避免后续 RGBA8 转换再放大峰值内存。
    let (w, h) = (input.width(), input.height());
    check_dimensions(w, h)?;

    // 任意位深/颜色类型统一归一化为 RGBA8（4 字节/像素）输出。
    let rgba = input.to_rgba8();
    Ok((rgba.into_raw(), w, h))
}

#[cfg(test)]
mod tests {
    use super::decode_pnm;
    use crate::{STATUS_DECODE_FAILED, STATUS_TOO_LARGE};

    // ---- 内联夹具 -----------------------------------------------------
    // 生成：二进制类（P4/P5-8bit/P6-8bit）为 Python PIL `save(format="PPM")`
    // 确定性输出转内联字节数组；P5-16bit/P6-16bit/P7 为手写最小字节（PAM 头
    // 含 DEPTH/TUPLTYPE，PIL PPM 插件不产 16bit/PAM 全变体）。ASCII 类
    // （P1/P2/P3）为手写字节串（PIL PPM 插件只写二进制），含注释行以覆盖
    // 注释/空白解析路径。无外部随机源，同一输入永远产出同一字节。

    /// P4 4x4 二进制 PBM（PIL 生成，棋盘格：黑=1/白=0，位 MSB-first 按行打包）。
    const P4_PBM_4X4: &[u8] = &[
        80, 52, 10, 52, 32, 52, 10, 160, 80, 160, 80,
    ];

    /// P1 4x4 ASCII PBM（手写字节串，含注释行）。
    const P1_PBM_4X4: &[u8] = b"P1\n# sopeek pnm fixture\n4 4\n0 1 0 1\n1 0 1 0\n0 1 0 1\n1 0 1 0\n";

    /// P5 4x4 二进制 PGM（PIL 生成，灰阶 0..255 线性 16 级）。
    const P5_PGM_8BIT_4X4: &[u8] = &[
        80, 53, 10, 52, 32, 52, 10, 50, 53, 53, 10, 0, 17, 34, 51, 68, 85, 102, 119, 136, 153, 170, 187, 204, 221, 238, 255,
    ];

    /// P2 4x4 ASCII PGM（手写字节串，灰阶线性 16 级，含注释行）。
    const P2_PGM_4X4: &[u8] = b"P2\n# sopeek pgm fixture\n4 4\n255\n0 17 34 51\n68 85 102 119\n136 153 170 187\n204 221 238 255\n";

    /// P6 4x4 二进制 PPM（PIL 生成，RGB 8bit）。
    const P6_PPM_8BIT_4X4: &[u8] = &[
        80, 54, 10, 52, 32, 52, 10, 50, 53, 53, 10, 255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 0, 0, 255, 255, 255, 0, 255, 255, 255, 255, 0, 0, 0, 1, 2, 3, 10, 20, 30, 100, 150, 200, 200, 100, 50, 255, 1, 2, 3, 255, 4, 5, 6, 255, 7, 8, 9,
    ];

    /// P3 4x4 ASCII PPM（手写字节串，与 P6 同像素，含注释行）。
    const P3_PPM_4X4: &[u8] = b"P3\n# sopeek ppm fixture\n4 4\n255\n255 0 0 0 255 0 0 0 255 255 255 0\n0 255 255 255 0 255 255 255 255 0 0 0\n1 2 3 10 20 30 100 150 200 200 100 50\n255 1 2 3 255 4 5 6 255 7 8 9\n";

    /// P5 4x4 二进制 PGM 16bit（手写：MAXVAL 65535，样本 = c*257 大端）。
    const P5_PGM_16BIT_4X4: &[u8] = &[
        80, 53, 10, 52, 32, 52, 10, 54, 53, 53, 51, 53, 10, 0, 0, 17, 17, 34, 34, 51, 51, 68, 68, 85, 85, 102, 102, 119, 119, 136, 136, 153, 153, 170, 170, 187, 187, 204, 204, 221, 221, 238, 238, 255, 255,
    ];

    /// P6 4x4 二进制 PPM 16bit（手写：MAXVAL 65535，通道 = c*257 大端）。
    const P6_PPM_16BIT_4X4: &[u8] = &[
        80, 54, 10, 52, 32, 52, 10, 54, 53, 53, 51, 53, 10, 255, 255, 0, 0, 0, 0, 0, 0, 255, 255, 0, 0, 0, 0, 0, 0, 255, 255, 255, 255, 255, 255, 0, 0, 0, 0, 255, 255, 255, 255, 255, 255, 0, 0, 255, 255, 255, 255, 255, 255, 255, 255, 0, 0, 0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 10, 10, 20, 20, 30, 30, 100, 100, 150, 150, 200, 200, 200, 200, 100, 100, 50, 50, 255, 255, 1, 1, 2, 2, 3, 3, 255, 255, 4, 4, 5, 5, 6, 6, 255, 255, 7, 7, 8, 8, 9, 9,
    ];

    /// P7 4x4 PAM RGB（手写头 DEPTH 3 / MAXVAL 255 / TUPLTYPE RGB + 48B 光栅）。
    const P7_PAM_RGB_4X4: &[u8] = &[
        80, 55, 10, 87, 73, 68, 84, 72, 32, 52, 10, 72, 69, 73, 71, 72, 84, 32, 52, 10, 68, 69, 80, 84, 72, 32, 51, 10, 77, 65, 88, 86, 65, 76, 32, 50, 53, 53, 10, 84, 85, 80, 76, 84, 89, 80, 69, 32, 82, 71, 66, 10, 69, 78, 68, 72, 68, 82, 10, 255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 0, 0, 255, 255, 255, 0, 255, 255, 255, 255, 0, 0, 0, 1, 2, 3, 10, 20, 30, 100, 150, 200, 200, 100, 50, 255, 1, 2, 3, 255, 4, 5, 6, 255, 7, 8, 9,
    ];

    /// P7 4x4 PAM RGBA（手写头 DEPTH 4 / MAXVAL 255 / TUPLTYPE RGB_ALPHA + 64B 光栅）。
    const P7_PAM_RGBA_4X4: &[u8] = &[
        80, 55, 10, 87, 73, 68, 84, 72, 32, 52, 10, 72, 69, 73, 71, 72, 84, 32, 52, 10, 68, 69, 80, 84, 72, 32, 52, 10, 77, 65, 88, 86, 65, 76, 32, 50, 53, 53, 10, 84, 85, 80, 76, 84, 89, 80, 69, 32, 82, 71, 66, 95, 65, 76, 80, 72, 65, 10, 69, 78, 68, 72, 68, 82, 10, 255, 0, 0, 128, 0, 255, 0, 200, 0, 0, 255, 64, 255, 255, 0, 0, 0, 255, 255, 255, 255, 0, 255, 32, 255, 255, 255, 96, 0, 0, 0, 160, 1, 2, 3, 192, 10, 20, 30, 1, 100, 150, 200, 254, 200, 100, 50, 5, 255, 1, 2, 12, 3, 255, 4, 240, 5, 6, 255, 80, 7, 8, 9, 255,
    ];

    // ---- 断言辅助 -----------------------------------------------------

    /// 校验解码结果为 4x4 RGBA8 且逐像素等于 `expected`。
    fn check_rgba_4x4(result: Result<(Vec<u8>, u32, u32), i32>, expected: &[[u8; 4]]) {
        let (bytes, w, h) = result.expect("合法 PNM 夹具应解码成功");
        assert_eq!((w, h), (4, 4), "PNM 夹具尺寸应为 4x4");
        assert_eq!(bytes.len(), 4 * 4 * 4, "RGBA8 输出应为 64 字节");
        for (i, px) in expected.iter().enumerate() {
            assert_eq!(
                &bytes[i * 4..i * 4 + 4],
                px,
                "像素 {i} RGBA 应与夹具期望一致"
            );
        }
    }

    // ---- 验收：P1-P7 各档位解码成功、尺寸正确 --------------------------

    #[test]
    fn p1_ascii_pbm_with_comments_decodes() {
        // 1-bit ASCII：0→白(255,255,255)，1→黑(0,0,0)；注释行在头部（width 前）。
        // 行序交替：[W,B,W,B / B,W,B,W / W,B,W,B / B,W,B,W]（与夹具 P1 字节串一致）。
        let black = [0u8, 0, 0, 255];
        let white = [255u8, 255, 255, 255];
        let expected = [
            white, black, white, black,
            black, white, black, white,
            white, black, white, black,
            black, white, black, white,
        ];
        check_rgba_4x4(decode_pnm(P1_PBM_4X4), &expected);
    }

    #[test]
    fn p2_ascii_pgm_with_comments_decodes() {
        // 2-bit... 8bit ASCII 灰阶：g → [g,g,g,255]，线性 16 级。
        let gray: [u8; 16] = [0, 17, 34, 51, 68, 85, 102, 119, 136, 153, 170, 187, 204, 221, 238, 255];
        let expected: Vec<[u8; 4]> = gray
            .iter()
            .map(|&g| [g, g, g, 255])
            .collect();
        check_rgba_4x4(decode_pnm(P2_PGM_4X4), &expected);
    }

    #[test]
    fn p3_ascii_ppm_with_comments_decodes() {
        // 8bit ASCII RGB → RGBA8（alpha=255），与 P6 同一像素集合。
        let rgb: [[u8; 4]; 16] = [
            [255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255], [255, 255, 0, 255],
            [0, 255, 255, 255], [255, 0, 255, 255], [255, 255, 255, 255], [0, 0, 0, 255],
            [1, 2, 3, 255], [10, 20, 30, 255], [100, 150, 200, 255], [200, 100, 50, 255],
            [255, 1, 2, 255], [3, 255, 4, 255], [5, 6, 255, 255], [7, 8, 9, 255],
        ];
        check_rgba_4x4(decode_pnm(P3_PPM_4X4), &rgb);
    }

    #[test]
    fn p4_binary_pbm_decodes() {
        // 4x4 棋盘格（PIL 验证：行序 [0,255,0,255 / 255,0,255,0 / ...]）：
        // 位=1(黑)→[0,0,0,255]，位=0(白)→[255,255,255,255]。
        let black = [0u8, 0, 0, 255];
        let white = [255u8, 255, 255, 255];
        let expected = [
            black, white, black, white,
            white, black, white, black,
            black, white, black, white,
            white, black, white, black,
        ];
        check_rgba_4x4(decode_pnm(P4_PBM_4X4), &expected);
    }

    #[test]
    fn p5_binary_pgm_8bit_decodes() {
        let gray: [u8; 16] = [0, 17, 34, 51, 68, 85, 102, 119, 136, 153, 170, 187, 204, 221, 238, 255];
        let expected: Vec<[u8; 4]> = gray.iter().map(|&g| [g, g, g, 255]).collect();
        check_rgba_4x4(decode_pnm(P5_PGM_8BIT_4X4), &expected);
    }

    #[test]
    fn p5_binary_pgm_16bit_decodes() {
        // 16bit 灰阶：样本 c*257 → to_rgba8 取高字节 = c。
        let gray: [u8; 16] = [0, 17, 34, 51, 68, 85, 102, 119, 136, 153, 170, 187, 204, 221, 238, 255];
        let expected: Vec<[u8; 4]> = gray.iter().map(|&g| [g, g, g, 255]).collect();
        check_rgba_4x4(decode_pnm(P5_PGM_16BIT_4X4), &expected);
    }

    #[test]
    fn p6_binary_ppm_to_rgba8_with_full_alpha() {
        // P6 二进制 PPM：RGB → RGBA8，alpha 由 to_rgba8 补齐为全 1。
        // （PPM 本身无 alpha 通道；PNM 族中携带真实 alpha 的二进制变体是 P7 PAM
        //  RGB_ALPHA，见 p7_pam_rgba_alpha_preserved。）
        let rgb: [[u8; 4]; 16] = [
            [255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255], [255, 255, 0, 255],
            [0, 255, 255, 255], [255, 0, 255, 255], [255, 255, 255, 255], [0, 0, 0, 255],
            [1, 2, 3, 255], [10, 20, 30, 255], [100, 150, 200, 255], [200, 100, 50, 255],
            [255, 1, 2, 255], [3, 255, 4, 255], [5, 6, 255, 255], [7, 8, 9, 255],
        ];
        check_rgba_4x4(decode_pnm(P6_PPM_8BIT_4X4), &rgb);
    }

    #[test]
    fn p6_binary_ppm_16bit_decodes() {
        // 16bit RGB：通道 c*257 → 高字节 = c。
        let rgb: [[u8; 4]; 16] = [
            [255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255], [255, 255, 0, 255],
            [0, 255, 255, 255], [255, 0, 255, 255], [255, 255, 255, 255], [0, 0, 0, 255],
            [1, 2, 3, 255], [10, 20, 30, 255], [100, 150, 200, 255], [200, 100, 50, 255],
            [255, 1, 2, 255], [3, 255, 4, 255], [5, 6, 255, 255], [7, 8, 9, 255],
        ];
        check_rgba_4x4(decode_pnm(P6_PPM_16BIT_4X4), &rgb);
    }

    #[test]
    fn p7_pam_rgb_decodes() {
        // PAM DEPTH 3 / TUPLTYPE RGB：同 RGB 像素，alpha=255。
        let rgb: [[u8; 4]; 16] = [
            [255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255], [255, 255, 0, 255],
            [0, 255, 255, 255], [255, 0, 255, 255], [255, 255, 255, 255], [0, 0, 0, 255],
            [1, 2, 3, 255], [10, 20, 30, 255], [100, 150, 200, 255], [200, 100, 50, 255],
            [255, 1, 2, 255], [3, 255, 4, 255], [5, 6, 255, 255], [7, 8, 9, 255],
        ];
        check_rgba_4x4(decode_pnm(P7_PAM_RGB_4X4), &rgb);
    }

    #[test]
    fn p7_pam_rgba_alpha_preserved() {
        // P7 PAM DEPTH 4 / TUPLTYPE RGB_ALPHA：携带的真实 alpha 原样进入 RGBA8。
        let rgba: [[u8; 4]; 16] = [
            [255, 0, 0, 128], [0, 255, 0, 200], [0, 0, 255, 64], [255, 255, 0, 0],
            [0, 255, 255, 255], [255, 0, 255, 32], [255, 255, 255, 96], [0, 0, 0, 160],
            [1, 2, 3, 192], [10, 20, 30, 1], [100, 150, 200, 254], [200, 100, 50, 5],
            [255, 1, 2, 12], [3, 255, 4, 240], [5, 6, 255, 80], [7, 8, 9, 255],
        ];
        check_rgba_4x4(decode_pnm(P7_PAM_RGBA_4X4), &rgba);
    }

    // ---- 验收：错误与防御性上限 ----------------------------------------

    #[test]
    fn empty_truncated_and_garbage_return_error_without_panic() {
        // 空输入
        assert_eq!(decode_pnm(b""), Err(STATUS_DECODE_FAILED), "空输入应返回 -2");
        // 非 PNM 字节
        assert_eq!(
            decode_pnm(b"this is definitely not a netpbm file"),
            Err(STATUS_DECODE_FAILED),
            "非 PNM 字节应返回 -2"
        );
        // 损坏/截断：P6 头声明 4x4 但光栅仅有 5 字节。
        let mut truncated = P6_PPM_8BIT_4X4[..12].to_vec();
        truncated.extend_from_slice(&[255, 0, 0, 0, 0]);
        assert_eq!(
            decode_pnm(&truncated),
            Err(STATUS_DECODE_FAILED),
            "截断光栅应返回 -2"
        );
    }

    #[test]
    fn oversize_declared_dimensions_return_status_too_large() {
        // 伪造头声明 10000x10000（>8192x8192）：小体积头即被统一上限入口在
        // 解码前拒绝（-7），不再构造 12.5MB 光栅、不进入 image 分配。
        assert_eq!(decode_pnm(b"P4\n10000 10000\n"), Err(STATUS_TOO_LARGE));
        assert_eq!(decode_pnm(b"P5\n10000 10000\n255\n"), Err(STATUS_TOO_LARGE));
        assert_eq!(
            decode_pnm(b"P3\n# comment\n10000 10000\n255\n"),
            Err(STATUS_TOO_LARGE),
            "ASCII 头（含注释）同样前置拒绝"
        );
        // P7 PAM：WIDTH/HEIGHT 头键声明超限。
        assert_eq!(
            decode_pnm(b"P7\nWIDTH 10000\nHEIGHT 10000\nDEPTH 3\nMAXVAL 255\nTUPLTYPE RGB\nENDHDR\n"),
            Err(STATUS_TOO_LARGE)
        );
    }

    #[test]
    fn malformed_header_falls_back_to_image_crate_decode_failed() {
        // 头解析失败（缺 height / 维度非数字 / P7 缺 ENDHDR）→ 保持原路径：
        // 由 image crate 判定 -2，预检不产假阳性 -7。
        assert_eq!(decode_pnm(b"P6\n10000\n"), Err(STATUS_DECODE_FAILED));
        assert_eq!(decode_pnm(b"P6\nabc def\n255\n"), Err(STATUS_DECODE_FAILED));
        assert_eq!(
            decode_pnm(b"P7\nWIDTH 4\nHEIGHT 4\nDEPTH 3\nMAXVAL 255\n"),
            Err(STATUS_DECODE_FAILED),
            "P7 缺 ENDHDR → 回落 image 判 -2"
        );
    }

    #[test]
    fn parse_pnm_dimensions_reads_ascii_and_pam_headers() {
        use super::parse_pnm_dimensions;
        // P1-P6：magic 后 width/height token；注释与各类空白被跳过。
        assert_eq!(parse_pnm_dimensions(b"P6\n4 4\n255\n"), Some((4, 4)));
        assert_eq!(parse_pnm_dimensions(b"P3\n# c1\n# c2\n7\t3\n255\n"), Some((7, 3)));
        assert_eq!(parse_pnm_dimensions(b"P4\n10000 10000\n"), Some((10000, 10000)));
        // P7 PAM：WIDTH/HEIGHT 头键（ENDHDR 终止）。
        assert_eq!(
            parse_pnm_dimensions(
                b"P7\nWIDTH 8\nHEIGHT 6\nDEPTH 3\nMAXVAL 255\nTUPLTYPE RGB\nENDHDR\n"
            ),
            Some((8, 6))
        );
        // 解析失败族：非 PNM / 缺 token / 非数字 / 缺 ENDHDR / 缺 WIDTH。
        assert_eq!(parse_pnm_dimensions(b"not pnm"), None);
        assert_eq!(parse_pnm_dimensions(b"P6\n"), None);
        assert_eq!(parse_pnm_dimensions(b"P6\n10\n"), None);
        assert_eq!(parse_pnm_dimensions(b"P6\nabc 10\n"), None);
        assert_eq!(parse_pnm_dimensions(b"P7\nWIDTH 8\nHEIGHT 6\n"), None);
        assert_eq!(parse_pnm_dimensions(b"P7\nHEIGHT 6\nENDHDR\n"), None);
    }
}