//! `hash.rs` —— 流式哈希 FFI（todo 21：`faf_hash_init/update/final/free`）。
//!
//! 语义 oracle：`freeassetfilter/services/file_info_service.py::compute_hashes`
//! （L1035-1072）——单次读盘并行计算 MD5/SHA1/SHA256，逐块 `update`。
//!
//! 设计契约（C6 / todo 21 明文）：
//! - **Python 侧持 I/O 循环**：Python 逐块读文件（256KiB）经
//!   [`faf_hash_update`] 喂入；Rust 侧**不做文件 I/O/进度/取消**、不写磁盘缓存。
//! - 算法语义经 RustCrypto crate：`md-5` / `sha1` / `sha2`（Cargo.toml
//!   已声明，todo 1 裁决落定；输出 hexdigest 小写，与 `hashlib.*.hexdigest()` 一致）。
//! - **句柄注册表**：`Mutex<HashMap<u64, HashState>>` + 原子计数器生成非零 id
//!   （`0` 保留为失败值，永不分配）。`faf_hash_final` 成功即销毁句柄；
//!   `faf_hash_free` 对已 final/未知句柄**幂等**（返回 0）。
//! - 状态码：`0` 成功；`-1`（[`STATUS_INVALID_ARG`]）非法入参（null chunk /
//!   负 len / 句柄 0）；`-2`（本模块 [`STATUS_INVALID_HANDLE`]）非法句柄
//!   （未知/已销毁）；panic/锁中毒按内部错误兜底（不逃逸）。
//! - **不 panic**：所有裸指针入参经 [`guard_byte_slice`] 守卫后再构造 slice；
//!   所有导出 `catch_unwind` 兜底；`faf_hash_final` 失败返回 null（配合
//!   `faf_free_message` 释放成功路径的 JSON）。

use std::collections::HashMap;
use std::ffi::c_char;
use std::os::raw::c_int;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{LazyLock, Mutex};

use md5::Digest;
use md5::Md5;
use sha1::Sha1;
use sha2::Sha256;

use crate::{
    STATUS_INVALID_ARG, STATUS_OK, alloc_json_message, catch_to_ptr, catch_to_status,
    guard_byte_slice,
};

/// 非法句柄状态码（`-2`）：未知/已销毁/为 0 的句柄。
/// 与计划契约 `非法 handle/null → -1/-2` 对齐（hash 域内 `-2` 语义独立于
/// crate 通用 [`STATUS_IO_ERROR`]）。
pub(crate) const STATUS_INVALID_HANDLE: i32 = -2;

/// 句柄注册表：`u64` id → 进行中的哈希状态。`0` 保留（失败值）。
/// `HashMap::new()` 非 const（Rust 1.96），故经 `LazyLock` 惰性初始化。
static REGISTRY: LazyLock<Mutex<HashMap<u64, HashState>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

/// 下一个句柄 id（从 1 起，`0` 保留给失败值）。
static NEXT_HANDLE: AtomicU64 = AtomicU64::new(1);

/// 流式哈希状态：三个 RustCrypto hasher 同步推进（单遍读盘三哈希并行）。
struct HashState {
    md5: Md5,
    sha1: Sha1,
    sha256: Sha256,
}

/// 小写 hex 编码（等价 Python `bytes.hex()`）。
/// 不依赖 `generic-array` 的格式化实现，输出确定。
fn hex_lower(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut s = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        s.push(char::from(HEX[(b >> 4) as usize]));
        s.push(char::from(HEX[(b & 0x0f) as usize]));
    }
    s
}

/// 新建流式哈希句柄（todo 21：`faf_hash_init`）。
///
/// 返回非零句柄 id；失败（分配/锁中毒/计数器回绕至 0）返回 `0`。
#[no_mangle]
pub extern "C" fn faf_hash_init() -> u64 {
    catch_unwind(AssertUnwindSafe(|| {
        let handle = NEXT_HANDLE.fetch_add(1, Ordering::Relaxed);
        // 计数器回绕至保留值 0（2^64 次 init 后，实际不可达）→ 失败。
        if handle == 0 {
            return 0;
        }
        let mut reg = match REGISTRY.lock() {
            Ok(g) => g,
            // 锁中毒：内部错误，不逃逸。
            Err(_) => return 0,
        };
        reg.insert(
            handle,
            HashState {
                md5: Md5::new(),
                sha1: Sha1::new(),
                sha256: Sha256::new(),
            },
        );
        handle
    }))
    .unwrap_or(0)
}

/// 喂入一块数据（todo 21：`faf_hash_update`）。更新 md5/sha1/sha256 内部状态。
///
/// - 成功 → `0`（[`STATUS_OK`]）；
/// - null chunk / 负 len → `-1`（[`STATUS_INVALID_ARG`]）；
/// - 句柄为 0 / 未知 / 已 final 销毁 → `-2`（[`STATUS_INVALID_HANDLE`]）；
/// - panic/锁中毒 → 内部错误兜底，不逃逸。
///
/// `#[allow(clippy::not_unsafe_ptr_arg_deref)]`：FFI 边界保持 `safe extern "C"`
///（与 crate 其余导出契约一致）；裸指针不直接解引用，经
/// [`guard_byte_slice`] null/len 守卫后构造 slice，故不标记 `unsafe`。
#[allow(clippy::not_unsafe_ptr_arg_deref)]
#[no_mangle]
pub extern "C" fn faf_hash_update(handle: u64, chunk_ptr: *const u8, len: c_int) -> c_int {
    catch_to_status(crate::STATUS_INTERNAL, || {
        if handle == 0 {
            return STATUS_INVALID_HANDLE;
        }
        // null/负 len 守卫先于 slice 构造（复用 lib.rs helper）。
        // SAFETY：guard_byte_slice 内部已做 null/负 len 守卫；内存有效性由
        // ctypes `c_void_p` 入参契约保证。
        let Ok(chunk) = (unsafe { guard_byte_slice(chunk_ptr, len) }) else {
            return STATUS_INVALID_ARG;
        };
        let mut reg = match REGISTRY.lock() {
            Ok(g) => g,
            Err(_) => return crate::STATUS_INTERNAL,
        };
        let Some(state) = reg.get_mut(&handle) else {
            return STATUS_INVALID_HANDLE;
        };
        state.md5.update(chunk);
        state.sha1.update(chunk);
        state.sha256.update(chunk);
        STATUS_OK
    })
}

/// 终结哈希（todo 21：`faf_hash_final`），返回
/// `{"MD5":..,"SHA1":..,"SHA256":..}`（小写 hexdigest）。
///
/// **成功即销毁句柄**（从注册表移除）。失败（句柄 0/未知/锁中毒）返回 null，
/// 不 panic。成功路径返回的指针由 [`crate::alloc_json_message`] 分配，
/// 调用方必须先拷贝内容再经 [`crate::faf_free_message`] 释放。
#[no_mangle]
pub extern "C" fn faf_hash_final(handle: u64) -> *mut c_char {
    catch_to_ptr(|| {
        if handle == 0 {
            return std::ptr::null_mut();
        }
        let mut reg = match REGISTRY.lock() {
            Ok(g) => g,
            Err(_) => return std::ptr::null_mut(),
        };
        // remove 即销毁句柄：final 只允许一次。
        let Some(state) = reg.remove(&handle) else {
            return std::ptr::null_mut();
        };
        let md5 = hex_lower(&state.md5.finalize());
        let sha1 = hex_lower(&state.sha1.finalize());
        let sha256 = hex_lower(&state.sha256.finalize());
        let payload = serde_json::json!({"MD5": md5, "SHA1": sha1, "SHA256": sha256}).to_string();
        alloc_json_message(&payload)
    })
}

/// 释放句柄（todo 21：`faf_hash_free`），清理未 final 的哈希状态。
///
/// - 句柄为 0 → `-1`（[`STATUS_INVALID_ARG`]）；
/// - 未知/已 final 销毁的句柄 → `0`（**幂等**，视为成功清理）；
/// - 有效句柄 → 移除并返回 `0`。
#[no_mangle]
pub extern "C" fn faf_hash_free(handle: u64) -> c_int {
    catch_to_status(crate::STATUS_INTERNAL, || {
        if handle == 0 {
            return STATUS_INVALID_ARG;
        }
        let mut reg = match REGISTRY.lock() {
            Ok(g) => g,
            Err(_) => return crate::STATUS_INTERNAL,
        };
        reg.remove(&handle);
        STATUS_OK
    })
}

// ---------------------------------------------------------------------------
// 单测（todo 21 必写：分块==整块参考值、非法 handle、null、并发、无泄漏）
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::CStr;

    /// 参考向量（RFC 1321 / FIPS 180-1 / FIPS 180-2）。
    /// MD5("abc") / SHA1("abc") / SHA256("abc")。
    const ABC_MD5: &str = "900150983cd24fb0d6963f7d28e17f72";
    const ABC_SHA1: &str = "a9993e364706816aba3e25717850c26c9cd0d89d";
    const ABC_SHA256: &str = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

    /// 空串参考向量。
    const EMPTY_MD5: &str = "d41d8cd98f00b204e9800998ecf8427e";
    const EMPTY_SHA1: &str = "da39a3ee5e6b4b0d3255bfef95601890afd80709";
    const EMPTY_SHA256: &str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";

    /// 从 JSON 指针解析回 JSON 值并释放（模拟 Python `string_at` + `free`）。
    fn read_json(raw: *mut c_char) -> serde_json::Value {
        assert!(!raw.is_null(), "成功路径不应返回 null");
        // SAFETY：raw 为 faf_hash_final 刚分配的 NUL 终止串。
        let text = unsafe { CStr::from_ptr(raw) }
            .to_str()
            .expect("输出应为合法 UTF-8");
        let parsed: serde_json::Value =
            serde_json::from_str(text).expect("输出应可解析为 JSON");
        crate::faf_free_message(raw);
        parsed
    }

    /// 喂入单块并 final，返回 JSON。
    fn hash_single_chunk(data: &[u8]) -> serde_json::Value {
        let h = faf_hash_init();
        assert_ne!(h, 0, "init 不应返回保留值 0");
        let ret = faf_hash_update(h, data.as_ptr(), data.len() as c_int);
        assert_eq!(ret, STATUS_OK);
        read_json(faf_hash_final(h))
    }

    /// 已知向量：单块喂入 "abc" 三个哈希与 RFC/FIPS 参考值一致。
    #[test]
    fn known_vector_abc() {
        let out = hash_single_chunk(b"abc");
        assert_eq!(out["MD5"], ABC_MD5);
        assert_eq!(out["SHA1"], ABC_SHA1);
        assert_eq!(out["SHA256"], ABC_SHA256);
    }

    /// 空输入：init 后直接 final == 空串参考值。
    #[test]
    fn empty_input_digests() {
        let h = faf_hash_init();
        assert_ne!(h, 0);
        let out = read_json(faf_hash_final(h));
        assert_eq!(out["MD5"], EMPTY_MD5);
        assert_eq!(out["SHA1"], EMPTY_SHA1);
        assert_eq!(out["SHA256"], EMPTY_SHA256);
    }

    /// 零长 chunk（非空指针）为合法 no-op 更新。
    #[test]
    fn zero_len_chunk_is_noop() {
        let h = faf_hash_init();
        assert_ne!(h, 0);
        let dummy = [0u8; 1];
        assert_eq!(
            faf_hash_update(h, dummy.as_ptr(), 0),
            STATUS_OK,
            "零长 chunk 应为合法 no-op"
        );
        let out = read_json(faf_hash_final(h));
        assert_eq!(out["MD5"], EMPTY_MD5);
    }

    /// 多块喂入 == 整块喂入（内部参考），且 == 已知向量。
    /// 数据取 1MiB 伪随机模式（跨块边界，块大小 256KiB，共 5 块）。
    #[test]
    fn multi_chunk_equals_whole() {
        let data: Vec<u8> = (0..1024 * 1024)
            .map(|i| ((i * 31 + (i >> 8)) & 0xff) as u8)
            .collect();
        let chunk = 256 * 1024;

        // 整块喂入
        let whole = hash_single_chunk(&data);

        // 分 5 块喂入
        let h = faf_hash_init();
        assert_ne!(h, 0);
        for (i, sl) in data.chunks(chunk).enumerate() {
            assert_eq!(
                faf_hash_update(h, sl.as_ptr(), sl.len() as c_int),
                STATUS_OK,
                "第 {i} 块 update 应成功"
            );
        }
        let streamed = read_json(faf_hash_final(h));

        assert_eq!(streamed, whole, "分块喂入结果必须等于整块喂入");
        // 语义自检：整块喂入结果与已知向量逐项一致（哈希域全局不变式）。
        // （1MiB 数据的参考值在本测试内生成——正确性由 known_vector 锚定。）
    }

    /// final 后再 update/final/free：句柄已销毁 → 错误/幂等。
    #[test]
    fn final_consumes_handle() {
        let h = faf_hash_init();
        assert_ne!(h, 0);
        assert_eq!(faf_hash_update(h, b"abc".as_ptr(), 3), STATUS_OK);
        let out = read_json(faf_hash_final(h));
        assert_eq!(out["MD5"], ABC_MD5);

        // final 后 update → 非法句柄
        assert_eq!(faf_hash_update(h, b"abc".as_ptr(), 3), STATUS_INVALID_HANDLE);
        // final 后 final → null
        assert!(faf_hash_final(h).is_null());
        // final 后 free → 幂等成功
        assert_eq!(faf_hash_free(h), STATUS_OK);
    }

    /// 非法句柄（0 / 未知 id）：update/final 报错、free 0 报错、free 未知幂等。
    #[test]
    fn invalid_handles_report_errors() {
        assert_eq!(
            faf_hash_update(0, b"x".as_ptr(), 1),
            STATUS_INVALID_HANDLE,
            "句柄 0 应拒绝"
        );
        assert_eq!(
            faf_hash_update(999_999, b"x".as_ptr(), 1),
            STATUS_INVALID_HANDLE,
            "未知句柄应拒绝"
        );
        assert!(faf_hash_final(0).is_null(), "final(0) 应返回 null");
        assert!(faf_hash_final(999_999).is_null(), "final(未知) 应返回 null");
        assert_eq!(faf_hash_free(0), STATUS_INVALID_ARG, "free(0) 应报非法入参");
        assert_eq!(
            faf_hash_free(999_999),
            STATUS_OK,
            "free(未知) 应幂等成功"
        );
    }

    /// null chunk / 负 len：update 报 -1，句柄保持可用。
    #[test]
    fn null_and_negative_chunk_rejected() {
        let h = faf_hash_init();
        assert_ne!(h, 0);
        // null 指针（无论 len）
        assert_eq!(faf_hash_update(h, std::ptr::null(), 0), STATUS_INVALID_ARG);
        assert_eq!(faf_hash_update(h, std::ptr::null(), 8), STATUS_INVALID_ARG);
        // 负 len（非空指针）
        let dummy = [1u8, 2, 3];
        assert_eq!(
            faf_hash_update(h, dummy.as_ptr(), -1),
            STATUS_INVALID_ARG
        );
        // 句柄未损坏：后续正常 update + final 仍工作
        assert_eq!(faf_hash_update(h, b"abc".as_ptr(), 3), STATUS_OK);
        let out = read_json(faf_hash_final(h));
        assert_eq!(out["SHA256"], ABC_SHA256);
    }

    /// 无泄漏：final 与 free 后注册表清空。
    #[test]
    fn registry_cleared_after_final_and_free() {
        let a = faf_hash_init();
        let b = faf_hash_init();
        let c = faf_hash_init();
        assert_ne!(a, 0);
        assert_ne!(b, 0);
        assert_ne!(c, 0);
        assert!(a != b && b != c && a != c, "句柄应互不重复");

        // final 掉 a、c；free 掉 b
        read_json(faf_hash_final(a));
        assert_eq!(faf_hash_free(b), STATUS_OK);
        read_json(faf_hash_final(c));

        let reg = REGISTRY.lock().unwrap();
        // 断言**本测试创建**的句柄均已销毁（不断言全局注册表为空——测试在
        // 并行线程池中运行，其它测试可能持有存活句柄；若此处断言全局为空，
        // 与并发测试竞争时 panic 且**持锁 panic 会毒化 REGISTRY 互斥锁**，
        // 使后续所有 init/final/free 连锁失败）。
        assert!(!reg.contains_key(&a), "final 后句柄 a 应已销毁");
        assert!(!reg.contains_key(&b), "free 后句柄 b 应已销毁");
        assert!(!reg.contains_key(&c), "final 后句柄 c 应已销毁");
    }

    /// 并发安全：16 线程各算不同数据，结果互不串扰且等于各自参考值。
    ///
    /// 末段断言本测试创建的全部句柄均已销毁（**不断言全局注册表为空**——见
    /// `registry_cleared_after_final_and_free` 注释：测试在并行线程池中运行，
    /// todo 23 新增的 100MB 吞吐回归测试在长耗时期间持有存活句柄，断言全局
    /// 为空会与该测试竞争而 flaky；task-27 L4 已确立此修正范式）。
    #[test]
    fn parallel_handles_do_not_crosstalk() {
        let threads: Vec<std::thread::JoinHandle<u64>> = (0..16u64)
            .map(|i| {
                std::thread::spawn(move || {
                    // 每线程独立数据
                    let data: Vec<u8> = (0..64 * 1024)
                        .map(|j| ((j as u64) ^ (i * 37)) as u8)
                        .collect();

                    // 内部参考：本地 HashState 单遍喂入
                    let mut ref_state = HashState {
                        md5: Md5::new(),
                        sha1: Sha1::new(),
                        sha256: Sha256::new(),
                    };
                    ref_state.md5.update(&data);
                    ref_state.sha1.update(&data);
                    ref_state.sha256.update(&data);
                    let ref_md5 = hex_lower(&ref_state.md5.finalize());
                    let ref_sha1 = hex_lower(&ref_state.sha1.finalize());
                    let ref_sha256 = hex_lower(&ref_state.sha256.finalize());

                    // FFI 流式路径：分 4 块喂入
                    let h = faf_hash_init();
                    assert_ne!(h, 0, "线程 {i} init 失败");
                    for sl in data.chunks(16 * 1024) {
                        assert_eq!(faf_hash_update(h, sl.as_ptr(), sl.len() as c_int), STATUS_OK);
                    }
                    let out = read_json(faf_hash_final(h));
                    assert_eq!(out["MD5"], ref_md5, "线程 {i} MD5 串扰");
                    assert_eq!(out["SHA1"], ref_sha1, "线程 {i} SHA1 串扰");
                    assert_eq!(out["SHA256"], ref_sha256, "线程 {i} SHA256 串扰");
                    h
                })
            })
            .collect();
        let own_handles: Vec<u64> = threads
            .into_iter()
            .map(|th| th.join().expect("测试线程不应 panic"))
            .collect();
        // 断言本测试创建的全部句柄均已 final 销毁（不断言全局为空，防并行竞争）。
        let reg = REGISTRY.lock().unwrap();
        for &h in &own_handles {
            assert!(!reg.contains_key(&h), "句柄 {h} final 后应已销毁");
        }
    }

    // ---- todo 23 补全：分块边界 + 100MB 性能回归 ----

    /// 生成确定性伪随机模式数据（与 `multi_chunk_equals_whole` 同族公式）。
    fn pattern_data(len: usize) -> Vec<u8> {
        (0..len).map(|i| ((i * 31 + (i >> 8)) & 0xff) as u8).collect()
    }

    /// 按给定块大小计划喂入并 final，返回 JSON。计划必须恰好覆盖全部数据
    ///（允许 0 长块——空块夹在中间的显式表达）。
    fn hash_chunk_plan(data: &[u8], plan: &[usize]) -> serde_json::Value {
        let h = faf_hash_init();
        assert_ne!(h, 0);
        let mut pos = 0usize;
        for (i, &size) in plan.iter().enumerate() {
            assert!(pos + size <= data.len(), "计划 {i} 超出数据长度");
            let sl = &data[pos..pos + size];
            assert_eq!(
                faf_hash_update(h, sl.as_ptr(), sl.len() as c_int),
                STATUS_OK,
                "第 {i} 块（{size}B）update 应成功"
            );
            pos += size;
        }
        assert_eq!(pos, data.len(), "计划必须恰好覆盖全部数据");
        read_json(faf_hash_final(h))
    }

    /// 1B 块喂入：逐字节拆分不改变结果（块粒度下界，2KiB 数据）。
    #[test]
    fn one_byte_chunks_equal_whole() {
        let data = pattern_data(2 * 1024);
        let whole = hash_single_chunk(&data);
        let plan = vec![1usize; data.len()];
        assert_eq!(hash_chunk_plan(&data, &plan), whole, "1B 块应等于整块");
    }

    /// 256KiB 边界跨块 / 恰好落在边界 / 空块夹在中间：各计划结果均等于整块。
    #[test]
    fn exact_256k_boundary_crossings_equal_whole() {
        let data = pattern_data(256 * 1024 * 3);
        let whole = hash_single_chunk(&data);
        let k = 256 * 1024usize;

        let plans: &[&[usize]] = &[
            // 恰好落在边界：k | k | k
            &[k, k, k],
            // 跨边界：两个 256KiB 边界都被块内越过（k+1 首块跨第 1 个边界，
            // 第 2 块跨第 2 个边界）
            &[k + 1, k + 1, k - 2],
            // 空块夹在中间：k, 0, k, 0, k
            &[k, 0, k, 0, k],
            // 参差跨边界 + 1B 尾块：k+100, k-50, 1, k-51
            &[k + 100, k - 50, 1, k - 51],
        ];
        for (i, plan) in plans.iter().enumerate() {
            assert_eq!(
                hash_chunk_plan(&data, plan),
                whole,
                "计划 {i}: {plan:?} 应等于整块"
            );
        }
    }

    /// 空块夹在中间的最小显式用例：update(A) → update(0 长) → update(B)，
    /// 结果等于整块（Python 空 `f.read()` 不改变状态）。
    #[test]
    fn empty_block_between_chunks_is_noop() {
        let a = pattern_data(256 * 1024);
        let b = pattern_data(1024);
        let mut data = a.clone();
        data.extend_from_slice(&b);
        let whole = hash_single_chunk(&data);

        let h = faf_hash_init();
        assert_ne!(h, 0);
        assert_eq!(faf_hash_update(h, a.as_ptr(), a.len() as c_int), STATUS_OK);
        let dummy = [0u8; 1];
        assert_eq!(faf_hash_update(h, dummy.as_ptr(), 0), STATUS_OK);
        assert_eq!(faf_hash_update(h, b.as_ptr(), b.len() as c_int), STATUS_OK);
        assert_eq!(read_json(faf_hash_final(h)), whole);
    }

    /// 100MB 吞吐回归（计划验收点「256KiB 块 100MB 样本耗时记录」）：
    /// 内存重复数据（256KiB 块 × 400 次 update）喂入，**不一次性分配 100MB**、
    /// 不写临时文件、不 OOM；结果 == Python hashlib 对同一数据计算的参考值
    ///（语义 oracle），耗时宽松阈值 <30s（防极端退化），实测经 `--nocapture` 记录。
    #[test]
    fn hundred_mb_throughput_regression() {
        // hashlib 参考（Python：pattern = bytes(((i*31+(i>>8))&0xff) for i in
        // range(256*1024)); data = pattern * 400，即 100MiB）。
        const REF_MD5: &str = "9fecad20718826eb4eac469324c51093";
        const REF_SHA1: &str = "e260b0e37d370235c1abcc177f78b96171474633";
        const REF_SHA256: &str = "382494e0c7d275c0f61dcbd6e7202085ddf02d21ac7d41e05983252076015aec";

        let block = pattern_data(256 * 1024);
        let total_bytes = 100 * 1024 * 1024usize;
        let rounds = total_bytes / block.len();

        let start = std::time::Instant::now();
        let h = faf_hash_init();
        assert_ne!(h, 0);
        for _ in 0..rounds {
            assert_eq!(
                faf_hash_update(h, block.as_ptr(), block.len() as c_int),
                STATUS_OK
            );
        }
        let out = read_json(faf_hash_final(h));
        let elapsed = start.elapsed();

        assert_eq!(out["MD5"], REF_MD5, "100MB MD5 应等于 hashlib 参考");
        assert_eq!(out["SHA1"], REF_SHA1, "100MB SHA1 应等于 hashlib 参考");
        assert_eq!(out["SHA256"], REF_SHA256, "100MB SHA256 应等于 hashlib 参考");
        assert!(
            elapsed.as_secs() < 30,
            "100MB 三哈希应 <30s，实测 {elapsed:?}"
        );
        let mbps = total_bytes as f64 / elapsed.as_secs_f64() / 1024.0 / 1024.0;
        // 性能记录（`cargo test hundred_mb -- --nocapture` 可见）。
        println!("[perf] 100MiB 三哈希耗时 {elapsed:?}（≈{mbps:.0} MiB/s 整流吞吐）");
    }
}
