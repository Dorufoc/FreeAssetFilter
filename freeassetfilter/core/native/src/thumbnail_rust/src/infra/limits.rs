//! 防御性上限检查（todo 34 实现）。
//!
//! 职责：统一入口 `check_dimensions(w, h)`——目标解码尺寸 ≤ 8192×8192（与
//! `thumbnail_manager.py` MAX_IMAGE_DIMENSION 对齐），超限返回
//! `STATUS_TOO_LARGE`；含中间缓冲上限与 ffmpeg 输出读取上限（2MB）。
//! 每个 T1 解码器必须在解码前调用。
//!
//! 本文件为骨架：todo 34 中实现维度/内存上限判定。