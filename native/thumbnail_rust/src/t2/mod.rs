//! `t2` — 第二级管线：捆绑 ffmpeg 的视频 / 复杂图像处理。
//!
//! T2 复用 `core/native/bin/` 的 ffmpeg.exe / ffprobe.exe 子进程，能力矩阵由
//! 本目录 `ffmpeg_capability` 模块实测决定（**不硬编码 AVIF/HEIF 可用性**）；
//! `t2_ffmpeg.rs` 承载实际管线逻辑（todo 24 实现）。

pub mod ffmpeg_capability;
pub mod t2_ffmpeg;