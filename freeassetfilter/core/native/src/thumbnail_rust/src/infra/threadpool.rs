//! 本模块原规划自研线程池，经 Design Revision 5 与选型报告确认由 rayon
//! （静态链接进 cdylib，无外部 DLL）替代，本模块仅作架构占位，不实现代码。
//!
//! 语义说明：`lib.rs` 批量路径（`native_generate_batch` /
//! `native_generate_batch_jpg`）直接使用 `rayon::prelude::*` 的 `.par_iter()`，
//! 其全局线程池由 rayon-core 的 `THE_REGISTRY_SET.call_once` 进程级单例管理，
//! 首次 `par_iter` 时惰性初始化，worker 线程数与 CPU 数相当，进程内所有调用
//! （含 Python 侧并发 `native_generate_batch_jpg`）共享同一池，不随调用方数量
//! 新增线程——并发正确性由测试 `tests/unit/core/test_rust_batch_concurrency.py`
//! 验证（todo 4）。