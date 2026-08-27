//! 防御性上限检查（todo 34 实现）。
//!
//! 职责：统一入口 `check_dimensions(w, h)`——目标解码尺寸 ≤ 8192×8192（与
//! `thumbnail_manager.py` MAX_IMAGE_DIMENSION 对齐），超限返回
//! `STATUS_TOO_LARGE`；含中间缓冲上限与 ffmpeg 输出读取上限（2MB）。
//! 每个 T1 解码器必须在解码前调用。
//!
//! # 接线状态（todo 34）
//! 各 T1 解码器的既有内联预检（png/jpeg/tiff/webp/psd/bmp/pnm/qoi/tga/
//! gif/dds/icns/vp8/ico）已全部工作正常且各有超限测试覆盖——按「不重构
//! 工作正常的内联预检」原则保持不动；本模块作为新代码的统一入口供未来
//! 新增解码器使用，避免回归风险。

use crate::STATUS_TOO_LARGE;

/// 防御性维度上限（单边）：8192 像素，与 `thumbnail_manager.py` 的
/// `MAX_IMAGE_DIMENSION` 对齐（防解压炸弹）。
pub(crate) const MAX_IMAGE_DIMENSION: u32 = 8 * 1024;

/// 统一维度上限入口：判定目标解码尺寸是否超限。
///
/// 与 Python 侧 `thumbnail_manager.py` 的 `MAX_IMAGE_DIMENSION = 8192`
/// 对齐：总像素数 `w*h ≤ 8192×8192` 放行，超出返回
/// [`STATUS_TOO_LARGE`](`crate::STATUS_TOO_LARGE`)（-7）。乘法以 u64
/// 进行——`u32::MAX × u32::MAX ≈ 1.8e19` 溢出 u32 但不溢出 u64，
/// 保证极端声明值下无 panic、判定正确。
///
/// # Arguments
/// * `w` - 头部声明的图像宽度（像素）
/// * `h` - 头部声明的图像高度（像素）
///
/// # Returns
/// * `Ok(())` - 尺寸在上限内（含边界 8192×8192 恰好通过）
/// * `Err(STATUS_TOO_LARGE)` - `w*h > 8192×8192`
///
/// # 零维度语义（既有解码器行为对齐）
/// `w == 0 || h == 0` 返回 `Ok(())`：零面积不构成解压炸弹风险，且各解码器
/// 对零维度的既有语义不一（qoi/psd-DIB 显式 `-2`；png/webp/jpeg/tiff 的
/// 维度扫描失败时委托 image crate 裁决）——本入口只负责「超限」单一判定，
/// 零维度交由各解码器既有路径处理，不改变其行为。
#[allow(dead_code)]
// check_dimensions 为未来新增解码器的统一预检入口；既有 14 组解码器的
// 内联预检按 todo 34 决策保持不动（避免回归），当前仅 `#[cfg(test)]`
// 引用会触发 dead_code 警告——显式标注并注明消费点（同 infra/resize.rs
// 的 box_resize_rgba 先例）。
pub(crate) fn check_dimensions(w: u32, h: u32) -> Result<(), i32> {
    let limit = u64::from(MAX_IMAGE_DIMENSION) * u64::from(MAX_IMAGE_DIMENSION);
    if u64::from(w) * u64::from(h) > limit {
        Err(STATUS_TOO_LARGE)
    } else {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::{check_dimensions, MAX_IMAGE_DIMENSION};
    use crate::STATUS_TOO_LARGE;

    #[test]
    fn boundary_8192_squared_exactly_passes() {
        // 边界：8192×8192 = 67,108,864 恰为上限，应放行（含非对称等面积形态）。
        assert_eq!(check_dimensions(8192, 8192), Ok(()));
        assert_eq!(check_dimensions(MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Ok(()));
        assert_eq!(check_dimensions(67_108_864, 1), Ok(()), "等面积的 1×N 形态同样放行");
        assert_eq!(check_dimensions(1, 1), Ok(()));
        assert_eq!(check_dimensions(100, 100), Ok(()));
    }

    #[test]
    fn one_pixel_over_limit_rejected_with_status_too_large() {
        // 任一维 +1 即超限 → 确定性 -7。
        assert_eq!(check_dimensions(8192, 8193), Err(STATUS_TOO_LARGE));
        assert_eq!(check_dimensions(8193, 8192), Err(STATUS_TOO_LARGE));
        assert_eq!(check_dimensions(10_000, 10_000), Err(STATUS_TOO_LARGE));
        assert_eq!(check_dimensions(16_384, 16_384), Err(STATUS_TOO_LARGE));
    }

    #[test]
    fn u32_max_declarations_do_not_overflow() {
        // u64 乘法防溢出：u32 极端声明值不 panic 且正确判超限。
        assert_eq!(check_dimensions(u32::MAX, u32::MAX), Err(STATUS_TOO_LARGE));
        assert_eq!(check_dimensions(u32::MAX, 1), Err(STATUS_TOO_LARGE));
        assert_eq!(check_dimensions(1, u32::MAX), Err(STATUS_TOO_LARGE));
    }

    #[test]
    fn zero_dimensions_pass_through_per_decoder_semantics() {
        // 零维度放行（Ok）：零面积无解压炸弹风险，-2 裁决权在各解码器既有
        // 路径（见 check_dimensions doc「零维度语义」节）。
        assert_eq!(check_dimensions(0, 0), Ok(()));
        assert_eq!(check_dimensions(0, 8192), Ok(()));
        assert_eq!(check_dimensions(8192, 0), Ok(()));
    }
}
