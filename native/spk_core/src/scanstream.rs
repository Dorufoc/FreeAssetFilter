//! P3.4 流式目录扫描游标：`spk_scan_begin / spk_scan_next / spk_scan_free`。
//!
//! 与 [`crate::dirhandle`]（整目录先扫完、再按窗口取行）不同，本模块持有
//! **`std::fs::ReadDir` 迭代器本身**：每次 [`next_batch`] 只推进 `max` 项，
//! 因此首帧延迟与 Python `os.scandir` 逐批路径同量级（无需等待整目录扫完），
//! 同时保留 P2.1 的「`DirEntry::metadata()` 零额外 syscall」收益。
//!
//! 行结构与 `spk_scan_directory` 的 7 键一致，**额外带 `attrs`**（Windows
//! `st_file_attributes` 同源）：UI 侧的隐藏/系统过滤依赖它，缺失会导致
//! 「打开隐藏文件」开关失效——这是本模块存在的唯一理由。
//!
//! 契约：
//! * 游标同时存活上限 [`MAX_CURSORS`]，超出返回 0（调用方回退 Python）；
//! * `next` 读到末尾返回空数组（幂等）；非法句柄返回 null；
//! * `free` 幂等，返回是否真的移除了游标；
//! * 全程不 panic：`read_dir` 单项错误跳过（与 `scan_directory_impl` 一致）。

use std::collections::HashMap;
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

use once_cell::sync::Lazy;

use crate::scan::{self, Entry};

/// 同时存活的流式游标上限（超出后调用方回退 Python 逐批扫描）。
pub const MAX_CURSORS: usize = 8;

/// 单个游标的状态：底层迭代器。
pub struct ScanCursor {
    iter: std::fs::ReadDir,
}

static REGISTRY: Lazy<Mutex<HashMap<u64, ScanCursor>>> =
    Lazy::new(|| Mutex::new(HashMap::new()));
static NEXT_ID: AtomicU64 = AtomicU64::new(1);

/// 打开目录游标；目录不可读或游标表已满返回 0。
pub fn begin(path: &Path) -> u64 {
    let Ok(iter) = std::fs::read_dir(path) else {
        return 0;
    };
    let id = NEXT_ID.fetch_add(1, Ordering::Relaxed);
    let Ok(mut guard) = REGISTRY.lock() else {
        return 0;
    };
    if guard.len() >= MAX_CURSORS {
        return 0;
    }
    guard.insert(id, ScanCursor { iter });
    id
}

/// 读取至多 `max` 条（跳过 stat 失败项）；游标耗尽时返回空 `Vec`。
///
/// 返回 `None` 表示非法句柄/参数（调用方按失败处理）。
pub fn next_batch(handle: u64, max: usize) -> Option<Vec<Entry>> {
    if max == 0 {
        return None;
    }
    let mut guard = REGISTRY.lock().ok()?;
    let cursor = guard.get_mut(&handle)?;
    let mut batch: Vec<Entry> = Vec::with_capacity(max.min(4096));
    while batch.len() < max {
        let Some(item) = cursor.iter.next() else {
            break;
        };
        // read_dir 迭代项本身失败（罕见）→ 跳过，与整目录扫描语义一致。
        let Ok(dir_entry) = item else { continue };
        let name = dir_entry.file_name().to_string_lossy().into_owned();
        let full_path = dir_entry.path();
        // P2.1：符号链接补一次跟随 stat，其余直接复用 WIN32_FIND_DATA。
        let meta = match dir_entry.file_type() {
            Ok(file_type) if file_type.is_symlink() => std::fs::metadata(&full_path),
            _ => dir_entry.metadata(),
        };
        if let Some(entry) = scan::entry_from_metadata(name, full_path, &meta) {
            batch.push(entry);
        }
    }
    Some(batch)
}

/// 序列化一批（8 键，含 `attrs`）；仅供 [`crate::lib`] 的 `spk_scan_next` 使用。
pub(crate) fn batch_json(batch: &[Entry]) -> Result<String, i32> {
    scan::entries_to_json_with_attrs(batch)
}

/// 关闭游标（幂等）；返回是否真的移除了游标。
pub fn free(handle: u64) -> bool {
    let Ok(mut guard) = REGISTRY.lock() else {
        return false;
    };
    guard.remove(&handle).is_some()
}

/// 当前存活游标数（诊断用）。
#[allow(dead_code)]
pub fn live_cursors() -> usize {
    REGISTRY.lock().map(|guard| guard.len()).unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn temp_dir(tag: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "spk_scanstream_{tag}_{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).expect("应可创建临时目录");
        dir
    }

    #[test]
    fn batches_cover_all_entries_and_are_idempotent_at_end() {
        let dir = temp_dir("coverage");
        for i in 0..7 {
            fs::write(dir.join(format!("f{i}.txt")), b"x").expect("应可写文件");
        }
        let handle = begin(&dir);
        assert!(handle > 0);
        let mut names: Vec<String> = Vec::new();
        loop {
            let batch = next_batch(handle, 3).expect("有效句柄应返回 Some");
            if batch.is_empty() {
                break;
            }
            assert!(batch.len() <= 3);
            names.extend(batch.into_iter().map(|e| e.name));
        }
        names.sort();
        assert_eq!(names.len(), 7);
        // 耗尽后幂等
        assert_eq!(next_batch(handle, 3).map(|b| b.len()), Some(0));
        assert!(free(handle));
        assert!(!free(handle));
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn bad_handle_and_zero_max_are_rejected() {
        assert!(next_batch(0, 4).is_none());
        assert!(!free(0));
        let dir = temp_dir("bad");
        let handle = begin(&dir);
        assert!(handle > 0);
        assert!(next_batch(handle, 0).is_none());
        assert!(free(handle));
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn missing_directory_returns_zero() {
        assert_eq!(begin(Path::new("Z:/definitely/not/here")), 0);
    }

    #[test]
    fn batch_json_contains_attrs_key() {
        let dir = temp_dir("attrs");
        fs::write(dir.join("a.txt"), b"x").expect("应可写文件");
        let handle = begin(&dir);
        let batch = next_batch(handle, 4).expect("应可读");
        assert_eq!(batch.len(), 1);
        let json = batch_json(&batch).expect("应可序列化");
        assert!(json.contains("\"attrs\""));
        assert!(json.contains("\"name\":\"a.txt\""));
        assert!(free(handle));
        let _ = fs::remove_dir_all(&dir);
    }
}
