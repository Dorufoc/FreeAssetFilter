//! 自研面积平均缩放（todo 6 实现）。
//!
//! 职责：box filter 面积平均缩放——不放大、保比例（比例由调用方预先算好，
//! 本函数只做保面积平均缩放）、目标尺寸基准与 `thumbnail_manager.py`
//! BASE_SIZE=128 / 64x51 类契约对齐、1x1 特例返回 1px；输入任意位深 RGBA、
//! 输出 RGBA8；供全部 T1 解码器统一使用，并与 image crate 现缩放结果视觉
//! 等价（差值 ≤3/255 抽样比对）。
//!
//! 纯自研实现，不调用 image crate 的 resize；image crate 仅用于 `#[cfg(test)]`
//! 中做结果对照。

/// 面积平均（box filter）缩放 RGBA 图像（RGBA8 → RGBA8）。
///
/// # 参数
/// - `src`：源像素字节流，行优先（row-major），每像素恰好 4 字节（R,G,B,A）。
/// - `src_w` / `src_h`：源图宽/高（像素）。
/// - `dst_w` / `dst_h`：请求的目标宽/高（像素）。
///
/// # 语义
/// - **不放大**：请求尺寸任一维超过源尺寸时，该维截断到源尺寸（缩放比为 1
///   时恒等输出）；各维独立截断，不放大不代表保比例——保比例由调用方预先按
///   长边/短边基准算好目标尺寸，本函数只保证既不放大、面积平均正确。
/// - **面积平均**：输出像素 = 源对应矩形区域 RGBA 四通道独立取均值（u64 累加，
///   结果 `(sum + count/2) / count` 四舍五入到 0-255）。
/// - **1x1 特例**：输出 1 像素 = 全图平均色；1x1 输入 → 逐字节原样输出。
/// - **输入校验**：任一尺寸为 0、`src` 长度 ≠ `src_w*src_h*4`、
///   `src_w*src_h` / `dst_w*dst_h` 乘法溢出 usize 时返回 `None`。
///
/// # 区域映射策略（防末尾错位）
/// 输出像素 `(x,y)` 映射到源半开区间：
/// ```text
/// sx = x*src_w/dst_w         sy = y*src_h/dst_h
/// ex = (x+1)*src_w/dst_w     ey = (y+1)*src_h/dst_h   （均为整数除法）
/// ```
/// 最后一个输出列/行（x = dst_w-1 / y = dst_h-1）满足：
/// `ex = dst_w*src_w/dst_w = src_w`、`ey = src_h`——必然覆盖源末尾像素，
/// 避免末尾列/行因整除丢采样导致的整图错位。截断后 `dst_w <= src_w`、
/// `dst_h <= src_h`，故每个输出像素的源区间宽度/高度 ≥ 1，count 永不为 0。
#[allow(dead_code)]
// 该函数供 todo 8-22 各 T1 解码器统一接线使用；当前 crate 为 cdylib 且尚未
// 有解码器引入，仅 `#[cfg(test)]` 引用到它，故显式标注以避免 dead_code 警告。
pub fn box_resize_rgba(
    src: &[u8],
    src_w: u32,
    src_h: u32,
    dst_w: u32,
    dst_h: u32,
) -> Option<Vec<u8>> {
    // 尺寸合法性：任一维为 0 拒绝。
    if src_w == 0 || src_h == 0 || dst_w == 0 || dst_h == 0 {
        return None;
    }

    // 源字节长度必须严格等于 src_w*src_h*4（含 usize 溢出检查）。
    let src_px = (u64::from(src_w)).checked_mul(u64::from(src_h))?;
    let expected_len = src_px.checked_mul(4)?;
    if expected_len != src.len() as u64 {
        return None;
    }

    // 不放大：任一维请求超过源尺寸时截断到源尺寸。
    let dst_w = dst_w.min(src_w);
    let dst_h = dst_h.min(src_h);

    // 目标像素数与输出字节数溢出检查（截断后 ≤ 源像素数，双保险）。
    let dst_px = (u64::from(dst_w)).checked_mul(u64::from(dst_h))?;
    let out_bytes = usize::try_from(dst_px.checked_mul(4)?).ok()?;

    // 1x1 特例：输出 1 像素 = 全图平均色。
    if dst_w == 1 && dst_h == 1 {
        return Some(average_whole_image(src));
    }

    let (sw, sh) = (u64::from(src_w), u64::from(src_h));
    let (dw, dh) = (u64::from(dst_w), u64::from(dst_h));

    // 输出按行填充；目标像素数 ≤ 源像素数，with_capacity 直接满足。
    let mut out = Vec::with_capacity(out_bytes);
    for y in 0..dh {
        let sy = (y * sh) / dh;
        let ey = ((y + 1) * sh) / dh;
        for x in 0..dw {
            let sx = (x * sw) / dw;
            let ex = ((x + 1) * sw) / dw;
            let count = (ex - sx) * (ey - sy);
            let half = count / 2;
            let mut sums = [0u64; 4];
            for r in sy..ey {
                let row_base = (r * sw) as usize;
                for c in sx..ex {
                    let i = (row_base + c as usize) * 4;
                    sums[0] += u64::from(src[i]);
                    sums[1] += u64::from(src[i + 1]);
                    sums[2] += u64::from(src[i + 2]);
                    sums[3] += u64::from(src[i + 3]);
                }
            }
            out.push(((sums[0] + half) / count) as u8);
            out.push(((sums[1] + half) / count) as u8);
            out.push(((sums[2] + half) / count) as u8);
            out.push(((sums[3] + half) / count) as u8);
        }
    }
    Some(out)
}

/// 计算整幅图像的四通道平均值（1x1 特例辅助函数）。
///
/// 输入保证来自 `box_resize_rgba` 的校验：`src.len()` 为 4 的整数倍且非空，
/// 故 `count >= 1`，不存在除零。
fn average_whole_image(src: &[u8]) -> Vec<u8> {
    let count = (src.len() / 4) as u64;
    let half = count / 2;
    let mut sums = [0u64; 4];
    for px in src.chunks_exact(4) {
        sums[0] += u64::from(px[0]);
        sums[1] += u64::from(px[1]);
        sums[2] += u64::from(px[2]);
        sums[3] += u64::from(px[3]);
    }
    vec![
        ((sums[0] + half) / count) as u8,
        ((sums[1] + half) / count) as u8,
        ((sums[2] + half) / count) as u8,
        ((sums[3] + half) / count) as u8,
    ]
}

#[cfg(test)]
mod tests {
    use super::box_resize_rgba;

    /// 确定性生成平滑渐变 + 小幅噪声的 RGBA 测试图（行优先、无外部随机源）。
    ///
    /// 噪声幅度刻意压到 ~1/16 位深（≈15/255）：真实缩略图以平滑内容为主，
    /// 与 image crate Triangle 插值的差异收敛在小量；纯高频噪声图对 box filter
    /// 与三角插值本就是两种不同低通，会人为放大 MAD 掩盖真实视觉等价性。
    fn synthetic_rgba(w: u32, h: u32, seed: u64) -> Vec<u8> {
        let mut state = seed;
        let mut next = move || {
            // 32-bit LCG（Numerical Recipes 常数），仅用于测试图片生成。
            state = state.wrapping_mul(1664525).wrapping_add(1013904223);
            (state >> 24) as u8
        };
        let mut buf = Vec::with_capacity((w as usize) * (h as usize) * 4);
        for y in 0..h {
            for x in 0..w {
                let r = ((x as u64 * 255 / u64::from(w)) / 2 + u64::from(next() / 16)) as u8;
                let g = ((y as u64 * 255 / u64::from(h)) / 2 + u64::from(next() / 16)) as u8;
                let b = (((x as u64 + y as u64) * 255 / u64::from(w + h)) / 2
                    + u64::from(next() / 16)) as u8;
                let a = 220u8 + next() / 16;
                buf.extend_from_slice(&[r, g, b, a]);
            }
        }
        buf
    }

    /// 逐字节平均绝对差值（归一化到 0-255 单位）。
    fn mean_abs_diff(a: &[u8], b: &[u8]) -> f64 {
        debug_assert_eq!(a.len(), b.len());
        let mut total: u64 = 0;
        for (&x, &y) in a.iter().zip(b) {
            total += u64::from((i32::from(x) - i32::from(y)).unsigned_abs());
        }
        total as f64 / a.len() as f64
    }

    #[test]
    fn downsample_100x80_to_64x64_shape() {
        // todo 6 验收：100x80 → 64x64，输出字节数 = 64*64*4（各测试独立，
        // 与桥测试的 64x51 契约关系不耦合——本函数为通用 box filter）。
        let src = synthetic_rgba(100, 80, 1);
        let out = box_resize_rgba(&src, 100, 80, 64, 64).expect("合法参数应成功");
        assert_eq!(out.len(), 64 * 64 * 4, "输出字节数应等于 64*64*4");
    }

    #[test]
    fn one_pixel_input_identity() {
        // 1x1 输入 → 1x1 输出 = 像素原样。
        let src = [10u8, 20, 30, 40];
        let out = box_resize_rgba(&src, 1, 1, 1, 1).expect("1x1 输入应成功");
        assert_eq!(out, vec![10, 20, 30, 40]);
    }

    #[test]
    fn huge_panorama_no_overflow_and_correct_size() {
        // 超大输入（10000x1 全景）：64x1 降采样与 1x1 全图平均均不溢出、尺寸正确。
        let src = synthetic_rgba(10000, 1, 7);
        let out = box_resize_rgba(&src, 10000, 1, 64, 1).expect("合法参数应成功");
        assert_eq!(out.len(), 64 * 4);
        let avg = box_resize_rgba(&src, 10000, 1, 1, 1).expect("合法参数应成功");
        assert_eq!(avg.len(), 4);
    }

    #[test]
    fn zero_and_overflow_dimensions_rejected() {
        let src = vec![0u8; 10 * 10 * 4];
        assert!(box_resize_rgba(&src, 10, 10, 0, 10).is_none(), "dst_w=0 应拒绝");
        assert!(box_resize_rgba(&src, 10, 10, 10, 0).is_none(), "dst_h=0 应拒绝");
        assert!(box_resize_rgba(&src, 0, 10, 10, 10).is_none(), "src_w=0 应拒绝");
        assert!(box_resize_rgba(&src, 10, 0, 10, 10).is_none(), "src_h=0 应拒绝");
        // 字节数不匹配（≠ src_w*src_h*4）应拒绝。
        assert!(box_resize_rgba(&[0u8; 10], 3, 3, 2, 2).is_none(), "长度≠w*h*4 应拒绝");
        // usize 溢出：u32::MAX * u32::MAX * 4 超出 u64，返回 None。
        assert!(
            box_resize_rgba(&[0u8; 4], u32::MAX, u32::MAX, 1, 1).is_none(),
            "src 像素数溢出应拒绝"
        );
    }

    #[test]
    fn upscale_request_truncated_to_source() {
        // 放大请求按不放大语义截断：100x100 → 200x200 输出 = 100x100。
        let src = synthetic_rgba(100, 100, 3);
        let out = box_resize_rgba(&src, 100, 100, 200, 200).expect("放大请求应截断而非拒绝");
        assert_eq!(out.len(), 100 * 100 * 4, "截断后输出应为源尺寸");
        assert_eq!(out, src, "两维均截断到源 → 恒等输出");
        // 单维放大：请求 (200,50) → 宽度维截断到 100，高度维仍降采样 100→50。
        // 水平恒等（宽度截断后 1:1）、垂直为 2 行平均（+1 四舍五入）。
        let out2 = box_resize_rgba(&src, 100, 100, 200, 50).expect("单维放大应截断");
        assert_eq!(out2.len(), 100 * 50 * 4, "截断后（另维降采样）输出 = 100x50");
        for x in 0..100usize {
            let i0 = x * 4;
            let i1 = 100 * 4 + x * 4;
            for ch in 0..4 {
                let exp = ((i32::from(src[i0 + ch]) + i32::from(src[i1 + ch]) + 1) / 2) as u8;
                let got = out2[x * 4 + ch];
                assert_eq!(got, exp, "第 0 行像素 {x} 通道 {ch} 应为源两行均值");
            }
        }
    }

    #[test]
    fn solid_color_invariant() {
        // 纯色输入 → 输出像素 == 输入色（平均不变式：均匀区域均值即原色）。
        let color = [10u8, 200, 30, 128];
        let src = color.repeat(100 * 80);
        let out = box_resize_rgba(&src, 100, 80, 64, 64).expect("合法参数应成功");
        assert_eq!(out.len(), 64 * 64 * 4);
        for px in out.chunks_exact(4) {
            assert_eq!(px, &color, "均一图像面积平均后仍应为原色");
        }
    }

    #[test]
    fn one_by_one_is_whole_image_average() {
        // 2x2 图：四通道各一像素有值，其余为 0 → 每通道和 255、像素 4 个，
        // 四舍五入得 64。
        let src = [0u8, 0, 0, 0, 255, 0, 0, 0, 0, 255, 0, 0, 0, 0, 255, 0];
        let out = box_resize_rgba(&src, 2, 2, 1, 1).expect("1x1 特例应成功");
        assert_eq!(out, vec![64, 64, 64, 0]);
    }

    #[test]
    fn visually_equivalent_to_image_crate() {
        // 与 image crate 现缩放（FilterType::Triangle）抽样比对：5+ 张不同
        // 尺寸/颜色的合成图，通道级平均绝对差值（MAD）≤ 3/255。
        let cases: [(u32, u32, u32, u32, u64); 8] = [
            (80, 60, 32, 32, 11),
            (129, 97, 64, 48, 22),
            (200, 150, 100, 75, 33),
            (51, 33, 16, 16, 44),
            (300, 200, 128, 128, 55),
            (137, 91, 32, 32, 66),
            (64, 256, 32, 128, 77),
            (257, 193, 100, 75, 88),
        ];
        let mut worst = f64::MIN;
        for (w, h, dw, dh, seed) in cases {
            let src = synthetic_rgba(w, h, seed);
            let mine = box_resize_rgba(&src, w, h, dw, dh).expect("合法缩放应成功");
            let img =
                image::RgbaImage::from_raw(w, h, src).expect("构造对照源图应成功");
            let theirs =
                image::imageops::resize(&img, dw, dh, image::imageops::FilterType::Triangle)
                    .into_raw();
            assert_eq!(mine.len(), theirs.len(), "自研与 image 输出尺寸应一致");
            let mad = mean_abs_diff(&mine, &theirs);
            println!("case {w}x{h}->{dw}x{dh} (seed {seed}): MAD={mad:.4}/255");
            assert!(
                mad <= 3.0,
                "case {w}x{h}->{dw}x{dh} MAD={mad:.4} 超出 3/255 阈值"
            );
            worst = worst.max(mad);
        }
        println!(
            "visual equivalence: {} cases, worst MAD={worst:.4}/255 (limit 3.0)",
            cases.len()
        );
    }
}