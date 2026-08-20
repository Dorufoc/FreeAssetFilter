//! T2 ffmpeg 管线（todo 24 实现）。
//!
//! 职责：将 `lib.rs` 现内联 ffmpeg 缩略图逻辑整体搬迁至此——`extract_best_video_frame_jpeg`
//! / `try_extract_frame` 、HW 尝试顺序 d3d11va → dxva2 → qsv、软件回退、
//! `-frames:v 1 -vf scale -vcodec mjpeg -q:v 3`、20s 强杀、`ffprobe` 时长、
//! 多 seek 候选、HW 并发槽位（默认 1）与 `native_set_max_concurrent_hw_video_decodes`
//! 对齐；并扩展 Rust 侧视频路由谓词覆盖 T2 清单全集（能力探测 ∩ README 视频清单）。
//! 视频 RGBA 缓存路径改经 `jpeg.rs` 解码 ffmpeg MJPEG 输出（不再用 image crate）。
//!
//! 本文件为骨架：todo 24 中搬迁现有 ffmpeg 逻辑并接线上述能力。