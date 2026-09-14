//! `faf_core` —— FreeAssetFilter 原生性能库（Rust `cdylib`，与缩略图引擎并列）。
//!
//! 本文件为 todo 2 骨架：只提供版本导出与 FFI 共享基础设施（状态码、JSON
//! 输出 helper、`catch_unwind` 兜底、裸指针入参守卫），不实现任何业务导出
//!（`faf_scan_directory` / `faf_highlight_text` 等留待各自 todo）。
//!
//! FFI 范式镜像 `thumbnail_rust`（`src/lib.rs`）：
//! - 状态码语义 `0/-1/-2/-3/-4/-5/-6/-7`（`:42-52`）
//! - `CString::into_raw` 输出模式（`:535-569`）
//! - `#[no_mangle] pub extern "C" fn` 导出形态（`:672-1029`）
//!
//! 调用纪律（Python 桥侧）：`faf_version` 返回的指针必须先
//! `ctypes.string_at` 拷贝，再调 `faf_free_message` 释放（对称分配）。

use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_int};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::path::Path;

/// 目录扫描模块（todo 6：`faf_scan_directory`，见 [`scan::scan_directory_impl`]）。
mod scan;

/// 目录条目排序模块（todo 7：`faf_sort_entries`，见 [`sort::sort_entries_impl`]）。
mod sort;

/// 代码语法高亮模块（todo 11：`faf_highlight_text`，见 [`highlight::highlight_text_impl`]）。
mod highlight;

/// Markdown 渲染模块（todo 15：`faf_render_markdown`，见 [`markdown::render_markdown_impl`]）。
mod markdown;

/// 流式哈希模块（todo 21：`faf_hash_init/update/final/free`，见 [`hash`] 模块文档）。
mod hash;

/// 文本编码探测模块（todo 22：`faf_detect_encoding`，见 [`detect`] 模块文档）。
mod detect;

/// 字体信息解析模块（todo 22：`faf_parse_font`，见 [`font`] 模块文档）。
mod font;

/// 批量文件复制与目录大小聚合模块（todo 27：`faf_copy_files` /
/// `faf_sum_directory_sizes`，见 [`copy`] 模块文档）。
mod copy;

// ---------------------------------------------------------------------------
// 状态码（与 thumbnail_rust 语义对齐）
// ---------------------------------------------------------------------------

/// 成功。
pub const STATUS_OK: i32 = 0;
/// 非法入参（含 null 裸指针、非法长度、空路径）。
pub const STATUS_INVALID_ARG: i32 = -1;
/// I/O 错误。
pub const STATUS_IO_ERROR: i32 = -2;
/// 内存不足。
pub const STATUS_OUT_OF_MEMORY: i32 = -3;
/// 文件/条目不存在。
pub const STATUS_NOT_FOUND: i32 = -4;
/// 内部错误（含 panic 兜底、锁中毒）。
pub const STATUS_INTERNAL: i32 = -5;
/// 不支持的输入（未知语言、WOFF2 等，调用方回退 Python 路径）。
pub const STATUS_UNSUPPORTED: i32 = -6;
/// 输出超过上限。
pub const STATUS_TOO_LARGE: i32 = -7;

/// crate 版本（与 `Cargo.toml` 同源）。
pub const FAF_CORE_VERSION: &str = env!("CARGO_PKG_VERSION");

/// JSON 输出上限（8MB；目录扫描 10k 条目约 1-2MB）。
/// 超限返回 [`STATUS_TOO_LARGE`]，Python 侧回退自身实现，不崩溃。
pub const MAX_JSON_BYTES: usize = 8 * 1024 * 1024;

// ---------------------------------------------------------------------------
// 共享基础设施（后续 todo 复用）
// ---------------------------------------------------------------------------

/// 把 Rust 字符串分配为 C 侧拥有的 NUL 终止 `*mut c_char`
///（`CString::into_raw` 模式；释放一律经 [`faf_free_message`]）。
///
/// 失败（内部 NUL / 超 [`MAX_JSON_BYTES`]）返回 null，不 panic。
/// 调用方必须检查 null。
pub(crate) fn alloc_json_message(payload: &str) -> *mut c_char {
    if payload.len() > MAX_JSON_BYTES {
        return std::ptr::null_mut();
    }
    match CString::new(payload) {
        Ok(owned) => owned.into_raw(),
        // 内部 NUL：返回 null（错误路径），绝不 panic。
        Err(_) => std::ptr::null_mut(),
    }
}

/// 状态码导出兜底：闭包 panic 时返回 `fallback`（默认 [`STATUS_INTERNAL`]），不逃逸。
/// 本 todo 仅测试使用；后续业务导出复用。
#[allow(dead_code)]
pub(crate) fn catch_to_status<F>(fallback: i32, f: F) -> i32
where
    F: FnOnce() -> i32,
{
    catch_unwind(AssertUnwindSafe(f)).unwrap_or(fallback)
}

/// 指针型导出兜底：闭包 panic 时返回 null，不逃逸。
pub(crate) fn catch_to_ptr<F>(f: F) -> *mut c_char
where
    F: FnOnce() -> *mut c_char,
{
    catch_unwind(AssertUnwindSafe(f)).unwrap_or(std::ptr::null_mut())
}

/// 裸指针入参守卫：`CStr` 指针。
///
/// null → `Err(STATUS_INVALID_ARG)`。必须在任何 `CStr::from_ptr`
/// 构造之前调用。
///
/// # Safety
///
/// 返回的 `&CStr` 借用调用方内存；调用方须保证指针在借用期内有效且
/// NUL 终止（ctypes 传 `c_char_p` 即满足）。
///
/// 本 todo 仅测试使用；后续业务导出复用。
#[allow(dead_code)]
pub(crate) unsafe fn guard_c_str<'a>(ptr: *const c_char) -> Result<&'a CStr, i32> {
    if ptr.is_null() {
        return Err(STATUS_INVALID_ARG);
    }
    // SAFETY：已做 null 守卫；NUL 终止性由 FFI 契约保证（ctypes `c_char_p`）。
    Ok(unsafe { CStr::from_ptr(ptr) })
}

/// 裸指针入参守卫：字节缓冲区 `(ptr, len)`。
///
/// null 指针或负长度 → `Err(STATUS_INVALID_ARG)`。
/// `len == 0` 且指针非空 → 合法空 slice。
/// 必须在任何 `slice::from_raw_parts` 构造之前调用。
///
/// # Safety
///
/// 调用方须保证 `[ptr, ptr+len)` 可读且在借用期内有效。
///
/// 本 todo 仅测试使用；后续业务导出复用。
#[allow(dead_code)]
pub(crate) unsafe fn guard_byte_slice<'a>(
    ptr: *const u8,
    len: c_int,
) -> Result<&'a [u8], i32> {
    if ptr.is_null() {
        return Err(STATUS_INVALID_ARG);
    }
    if len < 0 {
        return Err(STATUS_INVALID_ARG);
    }
    let len = len as usize;
    // SAFETY：已做 null/len 守卫；内存有效性由 FFI 契约保证。
    Ok(unsafe { std::slice::from_raw_parts(ptr, len) })
}

// ---------------------------------------------------------------------------
// 导出
// ---------------------------------------------------------------------------

/// 返回版本 JSON，如 `{"version":"0.1.0"}`。
///
/// 返回指针由 Rust 分配，调用方必须先拷贝内容再经
/// [`faf_free_message`] 释放。失败返回 null。
#[no_mangle]
pub extern "C" fn faf_version() -> *mut c_char {
    catch_to_ptr(|| {
        let payload = serde_json::json!({"version": FAF_CORE_VERSION}).to_string();
        alloc_json_message(&payload)
    })
}

/// 释放 [`faf_version`]（及后续 JSON 导出）返回的指针。
///
/// null 输入直接返回；内部 `catch_unwind` 兜底。
///
/// `#[allow(clippy::not_unsafe_ptr_arg_deref)]`：FFI 边界必须保持
/// `safe extern "C"`（与 thumbnail 的 `native_free_message` 同契约，ctypes
/// 侧按普通函数指针调用）；入参已做 null 守卫，指针来源限定为本 crate
/// 分配，对称可审计，故不标记 `unsafe`。
#[allow(clippy::not_unsafe_ptr_arg_deref)]
#[no_mangle]
pub extern "C" fn faf_free_message(msg: *mut c_char) {
    let _ = catch_unwind(AssertUnwindSafe(|| {
        if msg.is_null() {
            return;
        }
        // SAFETY：指针必为 alloc_json_message/CString::into_raw 分配。
        unsafe {
            let _ = CString::from_raw(msg);
        }
    }));
}

/// 扫描目录（todo 6），返回条目 JSON 数组（**未排序**，排序在 todo 7）。
///
/// 语义对齐 Python oracle `_collect_directory_entries`
/// （`ui/layout/file_selector_layout.py`）：7 键 `name/path/is_dir/size/
/// modified/created/suffix`；时间本地时区 `"%Y-%m-%d %H:%M"`；逐项 stat 失败
/// 跳过；目录不可读返回错误（失败统一返回 null，错误码不跨 FFI）。
///
/// - 成功：非空 NUL 终止 JSON 数组（`alloc_json_message` 分配，经
///   [`faf_free_message`] 释放）；
/// - 失败（null/非法/不可读/超 [`MAX_JSON_BYTES`]）：返回 null，不 panic。
///
/// `#[allow(clippy::not_unsafe_ptr_arg_deref)]`：FFI 边界保持 `safe extern "C"`
///（与 [`faf_sort_entries`]/[`faf_free_message`]/thumbnail 契约一致）；入参经
/// `guard_c_str` null 守卫，指针来源限定为本 crate 调用方（ctypes `c_char_p`），
/// 故不标记 `unsafe`。
#[allow(clippy::not_unsafe_ptr_arg_deref)]
#[no_mangle]
pub extern "C" fn faf_scan_directory(path: *const c_char) -> *mut c_char {
    catch_to_ptr(|| {
        // SAFETY：guard_c_str 已做 null 守卫；NUL 终止性由 ctypes c_char_p 契约保证。
        let Ok(path_cstr) = (unsafe { guard_c_str(path) }) else {
            return std::ptr::null_mut();
        };
        // 非 UTF-8 路径 → 按失败处理（Windows 路径经 ctypes 传入恒为 UTF-8 或可损失码）。
        let Ok(path_str) = path_cstr.to_str() else {
            return std::ptr::null_mut();
        };
        let path = std::path::Path::new(path_str);
        let entries = match scan::scan_directory_impl(path) {
            Ok(entries) => entries,
            Err(_) => return std::ptr::null_mut(),
        };
        let payload = match scan::entries_to_json(&entries) {
            Ok(payload) => payload,
            Err(_) => return std::ptr::null_mut(),
        };
        alloc_json_message(&payload)
    })
}

/// 排序目录条目（todo 7）：`entries_json`（条目 JSON 数组）+ `sort_mode`（0-7）。
///
/// 语义逐字节对齐 Python `_apply_sort`（`ui/layout/file_selector_layout.py`
/// L1363-1380）：8 种模式 `(not is_dir, 次键)` 元组 + reverse 语义，稳定排序，
/// equal-key 保持输入相对序；reverse 模式同时翻转 dirs-first。详见
/// [`sort::sort_entries_impl`]。
///
/// - 成功：非空 NUL 终止 JSON 数组（`alloc_json_message` 分配，经
///   [`faf_free_message`] 释放）；
/// - 失败（null 指针 / 坏 JSON / 非数组 / 非法 mode）：返回 null，不 panic。
///
/// `#[allow(clippy::not_unsafe_ptr_arg_deref)]`：FFI 边界保持 `safe extern "C"`
///（与 [`faf_free_message`]/thumbnail 契约一致）；入参经 `guard_c_str`
/// null 守卫，指针来源限定为本 crate 调用方（ctypes `c_char_p`），故不
/// 标记 `unsafe`。
#[allow(clippy::not_unsafe_ptr_arg_deref)]
#[no_mangle]
pub extern "C" fn faf_sort_entries(entries_json: *const c_char, sort_mode: c_int) -> *mut c_char {
    catch_to_ptr(|| {
        // SAFETY：guard_c_str 已做 null 守卫；NUL 终止性由 ctypes c_char_p 契约保证。
        let Ok(raw) = (unsafe { guard_c_str(entries_json) }) else {
            return std::ptr::null_mut();
        };
        let Ok(text) = raw.to_str() else {
            return std::ptr::null_mut();
        };
        let Ok(parsed) = serde_json::from_str::<serde_json::Value>(text) else {
            return std::ptr::null_mut();
        };
        let Some(arr) = parsed.as_array() else {
            return std::ptr::null_mut();
        };
        let mut entries: Vec<sort::Entry> = arr
            .iter()
            .map(|v| sort::Entry::from_value(v.clone()))
            .collect();
        if sort::sort_entries_impl(&mut entries, sort_mode).is_err() {
            return std::ptr::null_mut();
        }
        let out = serde_json::Value::Array(entries.iter().map(|e| e.as_value().clone()).collect());
        alloc_json_message(&out.to_string())
    })
}

/// 高亮代码文本（todo 11）：`faf_highlight_text(language, text)`。
///
/// 语义与 Python `syntax_highlighter.py` 对齐（见 [`highlight`] 模块文档）：
///
/// - 成功：JSON 数组 `[{"start":N,"len":N,"token_type":N},…]`（**字符偏移**、
///   span 连续覆盖全文、`token_type` 索引 = Python `TokenType` 枚举顺序）；
/// - 未知语言（映射表外且无扩展名）→ 空数组 `[]`（Python 保默认样式）；
/// - 应用语言映射命中但 syntect 默认集缺失其语法（如 PowerShell）→ 返回
///   **null**，Python 侧路由 Pygments（逐语言回退，不许静默子集）；
/// - null 指针 / 非 UTF-8 / 其他错误 → null，不 panic。
///
/// 返回指针由 Rust 分配，调用方必须先拷贝内容再经 [`faf_free_message`] 释放。
///
/// `#[allow(clippy::not_unsafe_ptr_arg_deref)]`：FFI 边界保持 `safe extern "C"`
///（与 [`faf_sort_entries`]/[`faf_free_message`]/thumbnail 契约一致）；入参经
/// `guard_c_str` null 守卫，指针来源限定为本 crate 调用方（ctypes `c_char_p`），
/// 故不标记 `unsafe`。
#[allow(clippy::not_unsafe_ptr_arg_deref)]
#[no_mangle]
pub extern "C" fn faf_highlight_text(language: *const c_char, text: *const c_char) -> *mut c_char {
    catch_to_ptr(|| {
        // SAFETY：guard_c_str 已做 null 守卫；NUL 终止性由 ctypes c_char_p 契约保证。
        let Ok(lang) = (unsafe { guard_c_str(language) }) else {
            return std::ptr::null_mut();
        };
        let Ok(text_cstr) = (unsafe { guard_c_str(text) }) else {
            return std::ptr::null_mut();
        };
        let Ok(lang_str) = lang.to_str() else {
            return std::ptr::null_mut();
        };
        let Ok(text_str) = text_cstr.to_str() else {
            return std::ptr::null_mut();
        };
        let spans = match highlight::highlight_text_impl(lang_str, text_str) {
            Ok(spans) => spans,
            Err(_) => return std::ptr::null_mut(),
        };
        let arr: Vec<serde_json::Value> = spans
            .iter()
            .map(|s| {
                serde_json::json!({"start": s.start, "len": s.len, "token_type": s.token_type})
            })
            .collect();
        alloc_json_message(&serde_json::Value::Array(arr).to_string())
    })
}

/// 渲染 Markdown（todo 15）：`faf_render_markdown(text)`。
///
/// 语义与 Python `markdown_renderer.py` 对齐（见 [`markdown`] 模块文档）：
///
/// - 成功：JSON `{"html": "<body 片段>"}`（**不含颜色/CSS**，主题 CSS 由
///   Python `_build_css` 注入；`md_in_html`/heading-id 重写归 Python 侧
///   todo 17 共享后处理）；
/// - fenced code 块（含语言）内嵌 syntect tokenization →
///   `<span class="tok-<TYPE_NAME>">`（复用 [`highlight`] 的 SyntaxSet 单例
///   与 token_type 模块）；
/// - 降级：admonition/def_list/abbr/toc 语法按普通段落/原文渲染，Rust 侧
///   不实现新扩展；
/// - 空文本 → `{"html":""}`；损坏输入不 panic（产出可渲染 HTML）；
/// - null 指针 / 非 UTF-8 / 其他错误 → null，不 panic。
///
/// 返回指针由 Rust 分配，调用方必须先拷贝内容再经 [`faf_free_message`] 释放。
///
/// `#[allow(clippy::not_unsafe_ptr_arg_deref)]`：FFI 边界保持 `safe extern "C"`
///（与 [`faf_highlight_text`]/thumbnail 契约一致）；入参经 `guard_c_str`
/// null 守卫，指针来源限定为本 crate 调用方（ctypes `c_char_p`），故不
/// 标记 `unsafe`。
#[allow(clippy::not_unsafe_ptr_arg_deref)]
#[no_mangle]
pub extern "C" fn faf_render_markdown(text: *const c_char) -> *mut c_char {
    catch_to_ptr(|| {
        // SAFETY：guard_c_str 已做 null 守卫；NUL 终止性由 ctypes c_char_p 契约保证。
        let Ok(text_cstr) = (unsafe { guard_c_str(text) }) else {
            return std::ptr::null_mut();
        };
        let Ok(text_str) = text_cstr.to_str() else {
            return std::ptr::null_mut();
        };
        let body = match markdown::render_markdown_impl(text_str) {
            Ok(body) => body,
            Err(_) => return std::ptr::null_mut(),
        };
        let payload = serde_json::json!({"html": body}).to_string();
        alloc_json_message(&payload)
    })
}

/// 批量复制文件/目录（todo 27）：`faf_copy_files(sources_json, dest_dir, opts_json)`。
///
/// 语义对齐 Python `file_pool_layout.copy_files`（L2223-2236）：文件
/// `shutil.copy2`（内容 + mtime/权限 = copystat）、目录 `shutil.copytree(
/// dirs_exist_ok=True)`（递归、跟随符号链接）。详见 [`copy::copy_files_impl`]。
///
/// - `sources_json`：源路径字符串数组；`dest_dir`：目标目录（NUL 终止）；
///   `opts_json`：预留参数对象（`{}`，内容暂忽略，仅校验 UTF-8）；
/// - ≤32 文件/批内部 rayon 并行（批次粒度；跨批进度/取消归 Python 侧 todo 29）；
/// - 冲突改名（`_get_unique_target_path`）与分类复制保持 Python 侧（todo 29）；
/// - 成功：`{"copied":[{"src","dst","size"}],"failed":[{"src","error"}]}`；
///   单源失败记入 `failed` 继续，不中断整批；
/// - 失败（null 指针 / 非 UTF-8 / 坏 JSON / 非数组 / 输出超 [`MAX_JSON_BYTES`]）：
///   返回 null，不 panic。
///
/// `#[allow(clippy::not_unsafe_ptr_arg_deref)]`：FFI 边界保持 `safe extern "C"`
///（与 [`faf_scan_directory`]/[`faf_free_message`]/thumbnail 契约一致）；入参经
/// `guard_c_str` null 守卫，指针来源限定为本 crate 调用方（ctypes `c_char_p`），
/// 故不标记 `unsafe`。
#[allow(clippy::not_unsafe_ptr_arg_deref)]
#[no_mangle]
pub extern "C" fn faf_copy_files(
    sources_json: *const c_char,
    dest_dir: *const c_char,
    opts_json: *const c_char,
) -> *mut c_char {
    catch_to_ptr(|| {
        // SAFETY：guard_c_str 已做 null 守卫；NUL 终止性由 ctypes c_char_p 契约保证。
        let Ok(sources_cstr) = (unsafe { guard_c_str(sources_json) }) else {
            return std::ptr::null_mut();
        };
        let Ok(dest_cstr) = (unsafe { guard_c_str(dest_dir) }) else {
            return std::ptr::null_mut();
        };
        let Ok(opts_cstr) = (unsafe { guard_c_str(opts_json) }) else {
            return std::ptr::null_mut();
        };
        let Ok(sources_text) = sources_cstr.to_str() else {
            return std::ptr::null_mut();
        };
        let Ok(dest_text) = dest_cstr.to_str() else {
            return std::ptr::null_mut();
        };
        // opts_json 为 todo 29 预留；本 todo 只校验 UTF-8（内容忽略）。
        let Ok(_opts_text) = opts_cstr.to_str() else {
            return std::ptr::null_mut();
        };
        let payload = match copy::copy_files_impl(sources_text, Path::new(dest_text)) {
            Ok(payload) => payload,
            Err(_) => return std::ptr::null_mut(),
        };
        alloc_json_message(&payload)
    })
}

/// 聚合目录大小（todo 27）：`faf_sum_directory_sizes(paths_json)`。
///
/// 语义对齐 Python `staging_pool_service._iter_file_entries`（L375-407）：
/// 单遍递归 walk、**`follow_symlinks=False`**（`DirEntry::file_type()` 不解析
/// 目标）；rayon 顶层并行。详见 [`copy::sum_directory_sizes_impl`]。
///
/// - `paths_json`：目录路径字符串数组；
/// - 成功：`{"results":[{"path","size","error"}]}`（成功 `error` 为 null；
///   缺失/不可读/非目录 → `error` 字段携带原因，不中断其它路径）；
/// - 失败（null 指针 / 非 UTF-8 / 坏 JSON / 非数组 / 输出超 [`MAX_JSON_BYTES`]）：
///   返回 null，不 panic。
///
/// `#[allow(clippy::not_unsafe_ptr_arg_deref)]`：FFI 边界保持 `safe extern "C"`
///（与 [`faf_copy_files`]/[`faf_free_message`]/thumbnail 契约一致）；入参经
/// `guard_c_str` null 守卫，指针来源限定为本 crate 调用方（ctypes `c_char_p`），
/// 故不标记 `unsafe`。
#[allow(clippy::not_unsafe_ptr_arg_deref)]
#[no_mangle]
pub extern "C" fn faf_sum_directory_sizes(paths_json: *const c_char) -> *mut c_char {
    catch_to_ptr(|| {
        // SAFETY：guard_c_str 已做 null 守卫；NUL 终止性由 ctypes c_char_p 契约保证。
        let Ok(paths_cstr) = (unsafe { guard_c_str(paths_json) }) else {
            return std::ptr::null_mut();
        };
        let Ok(paths_text) = paths_cstr.to_str() else {
            return std::ptr::null_mut();
        };
        let payload = match copy::sum_directory_sizes_impl(paths_text) {
            Ok(payload) => payload,
            Err(_) => return std::ptr::null_mut(),
        };
        alloc_json_message(&payload)
    })
}

// ---------------------------------------------------------------------------
// 单测（todo 2 必写：NUL/null/panic 三守卫 + version 往返 + feature 冒烟）
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::CString;

    /// JSON helper 正常往返：合法内容 → CString → 可读回。
    #[test]
    fn json_helper_roundtrip() {
        let raw = alloc_json_message(r#"{"version":"0.1.0"}"#);
        assert!(!raw.is_null(), "合法 JSON 应返回非空指针");
        // SAFETY：raw 为 alloc_json_message 刚分配的 NUL 终止串。
        let back = unsafe { CStr::from_ptr(raw) }
            .to_str()
            .expect("输出应为合法 UTF-8");
        let parsed: serde_json::Value =
            serde_json::from_str(back).expect("输出应可解析为 JSON");
        assert_eq!(parsed["version"], "0.1.0");
        // 对称释放：与 Python 桥 finally 路径一致。
        faf_free_message(raw);
    }

    /// `CString::new` 遇内部 NUL → 返回 null 错误路径，不 panic。
    #[test]
    fn json_helper_interior_nul_returns_null() {
        let raw = alloc_json_message("bad\0payload");
        assert!(
            raw.is_null(),
            "含内部 NUL 的载荷必须返回 null 而非 panic"
        );
    }

    /// 超 `MAX_JSON_BYTES` → 返回 null，不尝试分配。
    #[test]
    fn json_helper_oversize_returns_null() {
        let big = "x".repeat(MAX_JSON_BYTES + 1);
        let raw = alloc_json_message(&big);
        assert!(raw.is_null(), "超限载荷必须返回 null");
    }

    /// `catch_unwind`：panic 闭包 → fallback/错误状态码，不崩溃。
    #[test]
    fn catch_unwind_returns_fallback_on_panic() {
        let code = catch_to_status(STATUS_INTERNAL, || {
            panic!("intentional panic for guard test");
        });
        assert_eq!(code, STATUS_INTERNAL);

        let ptr = catch_to_ptr(|| panic!("intentional panic for guard test"));
        assert!(ptr.is_null());

        // 正常闭包不受影响。
        assert_eq!(catch_to_status(STATUS_INTERNAL, || STATUS_OK), STATUS_OK);
    }

    /// 裸指针守卫：null 入参 → 错误状态码，不 UB。
    #[test]
    fn null_pointer_guards_reject_without_ub() {
        // SAFETY：守卫本身就是被测对象；null 输入必须返回 Err 且不解引用。
        unsafe {
            assert_eq!(
                guard_c_str(std::ptr::null()).unwrap_err(),
                STATUS_INVALID_ARG
            );
            assert_eq!(
                guard_byte_slice(std::ptr::null(), 10).unwrap_err(),
                STATUS_INVALID_ARG
            );
            assert_eq!(
                guard_byte_slice(std::ptr::null(), 0).unwrap_err(),
                STATUS_INVALID_ARG
            );
        }
        // 负长度同样拒绝（非空指针）。
        let dummy: u8 = 0;
        unsafe {
            assert_eq!(
                guard_byte_slice(&dummy as *const u8, -1).unwrap_err(),
                STATUS_INVALID_ARG
            );
        }
        // 合法输入通过：零长空 slice 与正常 slice。
        let data = [1u8, 2, 3];
        unsafe {
            assert_eq!(guard_byte_slice(data.as_ptr(), 0).unwrap(), &[] as &[u8]);
            assert_eq!(
                guard_byte_slice(data.as_ptr(), 3).unwrap(),
                &[1u8, 2, 3] as &[u8]
            );
            let s = CString::new("hello").unwrap();
            assert_eq!(guard_c_str(s.as_ptr()).unwrap().to_bytes(), b"hello");
        }
    }

    /// `faf_version` 返回非空指针且内容可解析；释放不崩。
    #[test]
    fn faf_version_returns_parseable_json() {
        let raw = faf_version();
        assert!(!raw.is_null(), "faf_version 不应返回 null");
        // SAFETY：raw 为 faf_version 刚分配的 NUL 终止串。
        let text = unsafe { CStr::from_ptr(raw) }
            .to_str()
            .expect("版本输出应为合法 UTF-8");
        let parsed: serde_json::Value =
            serde_json::from_str(text).expect("版本输出应可解析为 JSON");
        assert_eq!(parsed["version"], FAF_CORE_VERSION);
        faf_free_message(raw);
        // null 释放为 no-op，不崩。
        faf_free_message(std::ptr::null_mut());
    }

    /// syntect feature 冒烟：`default-syntaxes` 供 `load_defaults_newlines()` 使用，
    /// 纯 Rust 正则引擎 `regex-fancy` 生效（todo 11 前提）。
    #[test]
    fn syntect_default_syntaxes_load_with_fancy_regex() {
        let ss = syntect::parsing::SyntaxSet::load_defaults_newlines();
        assert!(
            !ss.syntaxes().is_empty(),
            "内置默认语法集不应为空"
        );
        assert!(
            ss.find_syntax_by_extension("rs").is_some(),
            "默认集应含 Rust 语法"
        );
    }

    /// 状态码常量与 thumbnail 语义对齐。
    #[test]
    fn status_codes_match_thumbnail_semantics() {
        assert_eq!(STATUS_OK, 0);
        assert_eq!(STATUS_INVALID_ARG, -1);
        assert_eq!(STATUS_IO_ERROR, -2);
        assert_eq!(STATUS_OUT_OF_MEMORY, -3);
        assert_eq!(STATUS_NOT_FOUND, -4);
        assert_eq!(STATUS_INTERNAL, -5);
        assert_eq!(STATUS_UNSUPPORTED, -6);
        assert_eq!(STATUS_TOO_LARGE, -7);
    }
}
