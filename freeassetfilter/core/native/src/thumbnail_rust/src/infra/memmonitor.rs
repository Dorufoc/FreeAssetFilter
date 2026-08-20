//! 系统内存监控（todo 5 实现）。
//!
//! 职责：通过 `extern "system" GlobalMemoryStatusEx`（保持零 crate，用 `#[link]`
//! 声明替代 windows-sys）监控系统内存；低内存时拒绝新解码（返回既有
//! `STATUS_OOM = -3`，与 `STATUS_TOO_LARGE = -7` 语义区分：-3 供 Python 现有
//! 回退，-7 仅用于维度超限）。
//!
//! 本文件为骨架：todo 5 中实现内存读取与低内存判定逻辑。