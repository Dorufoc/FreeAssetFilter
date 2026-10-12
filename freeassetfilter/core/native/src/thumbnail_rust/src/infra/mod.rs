//! `infra` — 解码基础设施层。
//!
//! 供 T1 解码器（`decoders/`）、JPEG 编码器（`encoders/`）、T2/T3 管线共用：
//!
//! - `resize`：面积平均缩放（box filter，输出 RGBA8）；
//! - `registry`：魔数嗅探注册表（分发到各 T1 解码器）；
//! - `errorlog`：环形错误缓冲（上限 512 条，Mutex 保护）；
//! - `limits`：防御性尺寸上限统一入口（解码尺寸 ≤ 8192×8192，
//!   各 T1 解码器的总像素预检统一经此调用）。
//!
//! # 已删除的骨架（review 3.3 收口）
//! 早期计划中的 `bitreader` / `inflate` / `lzw` / `threadpool` /
//! `memmonitor` / `minijson` / `ffmpeg_capability` 空骨架已删除：
//! 对应能力分别由 image crate（位读取 / inflate / LZW）、rayon（并行）、
//! `sysinfo`（内存监控）、`serde_json`（JSON）、`t2/ffmpeg_capability.rs`
//! （ffmpeg 能力探测）承担，不再保留占位模块以免误导。

pub mod errorlog;
pub mod limits;
pub mod registry;
pub mod resize;
