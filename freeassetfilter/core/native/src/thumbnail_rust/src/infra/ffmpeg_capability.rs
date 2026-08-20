//! ffmpeg/ffprobe 能力探测（todo 23 实现）。
//!
//! 职责：启动/按需调用 `ffprobe -version`、`ffmpeg -formats`、`ffmpeg -codecs`
//! 解析能力表（5s 超时、`OnceLock` 缓存、失败默认为未知并计入 errorlog）；
//! 为 T2 管线提供实测依据（**不硬编码 AVIF/HEIF 可用性**），并新增导出
//! `native_get_ffmpeg_capabilities_json`。
//!
//! 本文件为骨架：todo 23 中实现子进程调用、输出解析与能力缓存。