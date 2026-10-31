//! `encoders` — 输出侧编码器。
//!
//! 目前仅 JPEG 基线编码器（todo 16 实现），替代 image crate 的 JpegEncoder
//! 作为全部 jpg 输出路径的最终编码器。

pub mod jpeg_encoder;