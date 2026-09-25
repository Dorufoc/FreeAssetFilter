//! `fluid.rs` —— 流体背景 CPU 帧（todo 13：`faf_render_fluid_frame`）。
//!
//! todo 1 spike（task-1-decisions.md §6）裁决 **DROP**：Python `round()` 为银行家
//! 舍入（half-to-even）而 Rust `f64::round()` 为 half-away-from-zero，且
//! `math.hypot(11.25, 7.75)` vs `f64::hypot` 本机差 **1 ULP**（bits 实测不同：
//! rust `405bc71c5eab9ed8` vs py `405bc71c5eab9ed9`），逐像素 hash parity
//! 必要条件不成立 → **明确保持 Python CPU 路径**
//!（`freeassetfilter/ui/components/_styled_fluid_cpu.py`）。
//!
//! 导出 `faf_render_fluid_frame` 仍存在（FFI 契约占位，RGBA 缓冲 + `out_len`），
//! 但恒返回 `STATUS_UNSUPPORTED` → FFI 映射为 null；`QPixmap`/`QImage` 永远
//! 留在 GUI 线程。
//!
//! **todo 13 结论：DROP 终态（spike 门控触发）**——`render_fluid_frame_impl`
//! 维持恒返回 `Err(STATUS_UNSUPPORTED)`，不实现任何近似渲染；证据见
//! `.omo/evidence/rust-hot-path-native-migration/task-13-fluid.txt`。完整接线
//!（`_styled_fluid_cpu.render_static_frame` 消费桥结果 / 显式回退）留待 todo 14。

use crate::STATUS_UNSUPPORTED;

/// 渲染流体背景帧为 RGBA 像素缓冲（todo 13 裁决 DROP：恒 `STATUS_UNSUPPORTED`）。
///
/// - 占位/裁决失败：`Err(STATUS_UNSUPPORTED)`（FFI 侧返回 null，`out_len`
///   置 0），不 panic、不分配缓冲、不做任何像素数学。
pub fn render_fluid_frame_impl(
    _width: u32,
    _height: u32,
    _palette_json: &str,
    _noise_seed: u32,
    _time: f64,
    _overlay_json: &str,
) -> Result<Vec<u8>, i32> {
    Err(STATUS_UNSUPPORTED)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// spike 裁决：DROP —— 恒 `STATUS_UNSUPPORTED`（保持 Python CPU 路径）。
    #[test]
    fn placeholder_returns_unsupported() {
        assert_eq!(
            render_fluid_frame_impl(64, 48, "{}", 42, 0.5, "{}").unwrap_err(),
            STATUS_UNSUPPORTED
        );
    }

    /// 0×0 边界：恒 `STATUS_UNSUPPORTED`，不 panic、不分配缓冲、不做像素数学。
    #[test]
    fn zero_size_returns_unsupported_without_panic() {
        assert_eq!(
            render_fluid_frame_impl(0, 0, "{}", 1, 0.0, "{}").unwrap_err(),
            STATUS_UNSUPPORTED
        );
    }

    /// 非有限 time（NaN/Inf）：恒 `STATUS_UNSUPPORTED`，不 panic。
    #[test]
    fn non_finite_time_returns_unsupported_without_panic() {
        assert_eq!(
            render_fluid_frame_impl(64, 48, "{}", 1, f64::NAN, "{}").unwrap_err(),
            STATUS_UNSUPPORTED
        );
        assert_eq!(
            render_fluid_frame_impl(64, 48, "{}", 1, f64::INFINITY, "{}").unwrap_err(),
            STATUS_UNSUPPORTED
        );
    }
}