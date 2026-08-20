//! `infra` — 自研基础设施层（纯 std）。
//!
//! 供 T1 自研解码器（`decoders/`）、JPEG 编码器（`encoders/`）、T2/T3 管线共用
//! 的基础组件。本计划要将其全部实现为零 crate 依赖：
//!
//! - `bitreader`：位读取器（todo 2）——大端/小端、bit 级读取、防越界；
//! - `inflate`：deflate/zlib inflate（todo 2）——RFC 1950/1951，供 PNG/TIFF/WebP 使用；
//! - `lzw`：LZW 解压（todo 3）——GIF（LSB）与 TIFF（MSB）两变体；
//! - `threadpool`：自研线程池（todo 4）——`std::thread::scope` + mpsc，替代 rayon；
//! - `memmonitor`：系统内存监控（todo 5）——`GlobalMemoryStatusEx` + `#[link]` 声明；
//! - `resize`：面积平均缩放（todo 6）——box filter，输出 RGBA8；
//! - `registry`：魔数嗅探注册表（todo 7）——分发到各 T1 解码器；
//! - `errorlog`：环形错误缓冲（todo 5）——上限 512 条，Mutex 保护；
//! - `minijson`：手写 JSON 解析/序列化（todo 5）——ffmpeg 能力输出解析；
//! - `ffmpeg_capability`：ffmpeg/ffprobe 能力探测（todo 23）——`OnceLock` 缓存；
//! - `limits`：防御性上限检查（todo 34）——解码尺寸 ≤ 8192×8192 等。
//!
//! 本目录文件在 todo 1 中仅建立骨架（模块职责说明），真实实现分散于各后续 todo。

pub mod bitreader;
pub mod errorlog;
pub mod ffmpeg_capability;
pub mod inflate;
pub mod limits;
pub mod lzw;
pub mod memmonitor;
pub mod minijson;
pub mod registry;
pub mod resize;
pub mod threadpool;