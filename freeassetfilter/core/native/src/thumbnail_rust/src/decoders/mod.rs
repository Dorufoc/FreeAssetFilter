//! `decoders` — T1 自研纯 std 图像解码器（todo 8-22 逐个实现）。
//!
//! 每个解码器遵守统一输出契约：返回 `(RGBA8 Vec<u8>, width, height)` 或结构化
//! `i32` 错误码，先经 `infra/limits::check_dimensions` 做解压炸弹防御，
//! 解码尺寸 ≤ 8192×8192；解码失败返回错误不 panic。各格式魔数入口在
//! `infra/registry.rs` 注册分发。
//!
//! 覆盖 14 组格式：pnm / qoi / bmp / tga / ico / gif / png / jpeg / tiff /
//! webp / vp8 / psd / dds / icns。本目录当前为骨架，仅声明模块。

pub mod bmp;
pub mod dds;
pub mod gif;
pub mod icns;
pub mod ico;
pub mod jpeg;
pub mod png;
pub mod pnm;
pub mod psd;
pub mod qoi;
pub mod tga;
pub mod tiff;
pub mod vp8;
pub mod webp;