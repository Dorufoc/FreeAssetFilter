//! 自研 JPEG 基线编码器（todo 16 实现）。
//!
//! 职责：BT.601 RGB→YCbCr、定点 FDCT、量化表 Q90、标准 Huffman 表、JFIF
//! APP0、4:4:4、质量参数对齐 `thumbnail_manager.py`（QUAY=85 → 质量 90 常量）；
//! 替换 `lib.rs` 现有 `rgba_to_jpeg_rgb` + image crate JpegEncoder 调用点，
//! 输出 JPEG 供 Python 侧缓存与写盘。128px 图编码耗时 ≤5ms。
//!
//! 本文件为骨架：todo 16 中实现 `encode_jpeg_rgba` 等入口函数。