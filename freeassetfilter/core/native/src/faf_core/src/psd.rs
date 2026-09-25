//! `psd.rs` —— PSD 合成（todo 8：`faf_composite_psd`）。
//!
//! **DROP 裁决终态**（todo 1 spike，证据 `task-1-decisions.md` §3）：
//! `psd` crate 0.3.5 的唯一合成 API `flatten_layers_rgba` 实测**不应用混合
//! 模式**——multiply 样本（底层 128 灰 + 顶层 255 白、`BlendMode.MULTIPLY`）
//! 输出 `(255,255,255,255)` vs psd-tools `.composite()` 的 `(128,128,128,
//! 255)`；且无蒙版/裁剪/调整图层。官方文档自承 "TODO: Take the layer's
//! blend mode into account… ONE_MINUS_SRC_ALPHA regardless of the layer"，
//! 维护者 issue #14 亦确认不尊重 blend mode / clipping mask / 蒙版 / 调整
//! 图层。等价性不成立 → **明确保持 Python `psd-tools`**（`_decode_psd`）。
//!
//! 导出 `faf_composite_psd` 仍存在（FFI 契约占位），但恒返回
//! `STATUS_UNSUPPORTED` → FFI 映射为 null，Python 回退 `_decode_psd`
//!（`freeassetfilter/services/image_decoder_service.py:324-`）。**禁止输出
//! 与 psd-tools 不一致的合成结果**——绝不实现"近似合成"。

use crate::STATUS_UNSUPPORTED;

/// PSD 合成（todo 8 裁决 DROP：恒 `STATUS_UNSUPPORTED`）。
///
/// - 占位/裁决失败：`Err(STATUS_UNSUPPORTED)`（FFI 侧返回 null），不 panic、
///   不做文件 I/O、不输出任何与 psd-tools 不一致的像素。
pub fn composite_psd_impl(_path: &str) -> Result<serde_json::Value, i32> {
    Err(STATUS_UNSUPPORTED)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// spike 裁决：DROP —— 恒 `STATUS_UNSUPPORTED`（保持 Python psd-tools）。
    #[test]
    fn placeholder_returns_unsupported() {
        assert_eq!(composite_psd_impl("C:/nonexistent.psd").unwrap_err(), STATUS_UNSUPPORTED);
    }
}