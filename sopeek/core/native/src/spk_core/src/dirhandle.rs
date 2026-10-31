//! P3.2 目录句柄：Rust 侧持有扫描结果，Python 按窗口取行。
//!
//! 背景：`spk_scan_directory` / `spk_sort_entries` 以整份 JSON 往返，
//! 10k 条目约 4.2MiB，且超过 [`crate::MAX_JSON_BYTES`]（8MiB）时直接
//! 回退 Python——大目录反而更慢。句柄化之后：
//!
//! * 扫描/排序结果留在 Rust，Python 只取**可视窗口**（如 2000 行）；
//! * 排序在句柄上原地完成，不再回传全量条目；
//! * 句柄表有硬上限（[`MAX_HANDLES`]），关闭幂等，泄漏可控。
//!
//! 句柄 0 为保留的「无效」值；所有导出对非法句柄返回 0 / -1 / null。

use std::collections::HashMap;
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

use once_cell::sync::Lazy;
use serde_json::Value;

use crate::scan;
use crate::sort::{self, Entry};

/// 同时存活的目录句柄上限（超出后拒绝新句柄，调用方回退整份 JSON）。
pub const MAX_HANDLES: usize = 32;

/// 单个句柄的状态：条目、流式游标与取消标记。
pub struct DirState {
    entries: Vec<Entry>,
    /// 流式游标（`spk_dir_next` 已交付到的下标）。
    cursor: usize,
    /// 取消标记（P3.7）；置位后 `next` 返回空数组。
    cancelled: bool,
}

static REGISTRY: Lazy<Mutex<HashMap<u64, DirState>>> =
    Lazy::new(|| Mutex::new(HashMap::new()));
static NEXT_ID: AtomicU64 = AtomicU64::new(1);

/// 把 `scan::Entry` 转为排序层使用的 JSON 载体。
fn to_value(entry: &scan::Entry) -> Value {
    serde_json::json!({
        "name": entry.name,
        "path": entry.path,
        "is_dir": entry.is_dir,
        "size": entry.size,
        "modified": entry.modified,
        "created": entry.created,
        "suffix": entry.suffix,
        "attrs": entry.attrs,
    })
}

/// 扫描目录并登记为句柄。
///
/// Returns:
///     u64: 非零句柄；目录不可读或句柄表已满返回 0。
pub fn open(path: &Path) -> u64 {
    let Ok(scanned) = scan::scan_directory_impl(path) else {
        return 0;
    };
    let entries: Vec<Entry> = scanned
        .iter()
        .map(|entry| Entry::from_value(to_value(entry)))
        .collect();
    let id = NEXT_ID.fetch_add(1, Ordering::Relaxed);
    let Ok(mut guard) = REGISTRY.lock() else {
        return 0;
    };
    if guard.len() >= MAX_HANDLES {
        return 0;
    }
    guard.insert(
        id,
        DirState {
            entries,
            cursor: 0,
            cancelled: false,
        },
    );
    id
}

/// 句柄条目数；非法句柄返回 -1。
pub fn count(handle: u64) -> i32 {
    let Ok(guard) = REGISTRY.lock() else {
        return -1;
    };
    match guard.get(&handle) {
        Some(state) => state.entries.len() as i32,
        None => -1,
    }
}

/// 在句柄上原地排序；返回状态码（0 成功，-1 非法句柄/模式）。
pub fn sort(handle: u64, mode: i32) -> i32 {
    let Ok(mut guard) = REGISTRY.lock() else {
        return -1;
    };
    let Some(state) = guard.get_mut(&handle) else {
        return -1;
    };
    if state.cancelled {
        return -1;
    }
    match sort::sort_entries_impl(&mut state.entries, mode) {
        Ok(()) => {
            state.cursor = 0;
            0
        }
        Err(code) => code,
    }
}

/// 取 `[first, first+count)` 窗口的 JSON 数组；非法参数返回 None。
pub fn rows(handle: u64, first: i32, count: i32) -> Option<String> {
    if first < 0 || count <= 0 {
        return None;
    }
    let guard = REGISTRY.lock().ok()?;
    let state = guard.get(&handle)?;
    let entries = &state.entries;
    let start = first as usize;
    if start >= entries.len() {
        return Some("[]".to_string());
    }
    let end = (start + count as usize).min(entries.len());
    let values: Vec<Value> = entries[start..end]
        .iter()
        .map(|entry| entry.as_value().clone())
        .collect();
    serde_json::to_string(&values).ok()
}

/// 关闭句柄（幂等）；返回是否确实移除了条目。
pub fn close(handle: u64) -> bool {
    let Ok(mut guard) = REGISTRY.lock() else {
        return false;
    };
    guard.remove(&handle).is_some()
}

/// 取下一块（流式游标，P3.4）：最多 `max_count` 条，游标前移。
///
/// 取消后（P3.7）返回空数组；非法句柄/参数返回 None。
pub fn next_chunk(handle: u64, max_count: i32) -> Option<String> {
    if max_count <= 0 {
        return None;
    }
    let mut guard = REGISTRY.lock().ok()?;
    let state = guard.get_mut(&handle)?;
    if state.cancelled {
        return Some("[]".to_string());
    }
    let start = state.cursor.min(state.entries.len());
    let end = (start + max_count as usize).min(state.entries.len());
    let values: Vec<Value> = state.entries[start..end]
        .iter()
        .map(|entry| entry.as_value().clone())
        .collect();
    state.cursor = end;
    serde_json::to_string(&values).ok()
}

/// 标记取消（P3.7，幂等）；返回是否命中有效句柄。
pub fn cancel(handle: u64) -> bool {
    let Ok(mut guard) = REGISTRY.lock() else {
        return false;
    };
    match guard.get_mut(&handle) {
        Some(state) => {
            state.cancelled = true;
            true
        }
        None => false,
    }
}

/// POD 行记录（P3.3）：定长 56 字节，字符串以 `(offset, len)` 指向尾部 arena。
///
/// 布局（小端，`repr(C)`）：
/// `name_off,name_len,path_off,path_len,suffix_off,suffix_len,`
/// `modified_off,modified_len,created_off,created_len`（10×u32 = 40）+ 
/// `size`（u64，偏移 40）+ `is_dir`（u8，偏移 48）+ 3 字节对齐 + 
/// `attrs`（u32，偏移 52）= 56 字节。
#[repr(C)]
#[derive(Clone, Copy)]
pub struct SpkDirRow {
    pub name_off: u32,
    pub name_len: u32,
    pub path_off: u32,
    pub path_len: u32,
    pub suffix_off: u32,
    pub suffix_len: u32,
    pub modified_off: u32,
    pub modified_len: u32,
    pub created_off: u32,
    pub created_len: u32,
    pub size: u64,
    pub is_dir: u8,
    /// Windows 属性位（P3.4；非 Windows 恒 0）。
    pub attrs: u32,
}

/// POD 行缓冲区（行数组 + 尾部 arena）。
pub struct PodRows {
    pub buffer: Vec<u8>,
    pub count: u32,
    pub arena_len: u32,
}

/// 取 `[first, first+count)` 窗口的 POD 行（P3.3）。
///
/// 字符串写入同一缓冲区的 arena 段（offset 相对于 arena 起点）；
/// 返回 `None` 表示非法句柄/参数。
pub fn rows_pod(handle: u64, first: i32, count: i32) -> Option<PodRows> {
    if first < 0 || count <= 0 {
        return None;
    }
    let guard = REGISTRY.lock().ok()?;
    let state = guard.get(&handle)?;
    if state.cancelled {
        return None;
    }
    let start = (first as usize).min(state.entries.len());
    let end = (start + count as usize).min(state.entries.len());
    let slice = &state.entries[start..end];

    let mut arena: Vec<u8> = Vec::new();
    let mut rows: Vec<SpkDirRow> = Vec::with_capacity(slice.len());
    let push_str = |arena: &mut Vec<u8>, text: &str| -> (u32, u32) {
        let off = arena.len() as u32;
        arena.extend_from_slice(text.as_bytes());
        (off, text.len() as u32)
    };

    for entry in slice {
        let value = entry.as_value();
        let get = |key: &str| -> &str { value.get(key).and_then(Value::as_str).unwrap_or("") };
        let (name_off, name_len) = push_str(&mut arena, get("name"));
        let (path_off, path_len) = push_str(&mut arena, get("path"));
        let (suffix_off, suffix_len) = push_str(&mut arena, get("suffix"));
        let (modified_off, modified_len) = push_str(&mut arena, get("modified"));
        let (created_off, created_len) = push_str(&mut arena, get("created"));
        let size = value.get("size").and_then(Value::as_u64).unwrap_or(0);
        let is_dir = u8::from(
            value
                .get("is_dir")
                .and_then(Value::as_bool)
                .unwrap_or(false),
        );
        let attrs = value
            .get("attrs")
            .and_then(Value::as_u64)
            .unwrap_or(0) as u32;
        rows.push(SpkDirRow {
            name_off,
            name_len,
            path_off,
            path_len,
            suffix_off,
            suffix_len,
            modified_off,
            modified_len,
            created_off,
            created_len,
            size,
            is_dir,
            attrs,
        });
    }

    let rows_bytes = unsafe {
        std::slice::from_raw_parts(
            rows.as_ptr() as *const u8,
            rows.len() * std::mem::size_of::<SpkDirRow>(),
        )
    };
    let mut buffer = Vec::with_capacity(rows_bytes.len() + arena.len());
    buffer.extend_from_slice(rows_bytes);
    buffer.extend_from_slice(&arena);
    Some(PodRows {
        buffer,
        count: rows.len() as u32,
        arena_len: arena.len() as u32,
    })
}

/// 当前存活句柄数（诊断用）。
#[allow(dead_code)]
pub fn live_handles() -> usize {
    REGISTRY.lock().map(|guard| guard.len()).unwrap_or(0)
}
