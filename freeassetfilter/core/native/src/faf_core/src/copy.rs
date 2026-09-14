//! `copy.rs` —— 批量文件复制与目录大小聚合（todo 27）。
//!
//! 语义 oracle：
//! - 复制：`freeassetfilter/ui/layout/file_pool_layout.py` `copy_files`
//!   （L2223-2236）——文件 `shutil.copy2`（内容 + copystat：mtime + 权限）、
//!   目录 `shutil.copytree(src, dst, dirs_exist_ok=True)`（递归、跟随符号链接）；
//! - 大小聚合：`freeassetfilter/services/staging_pool_service.py`
//!   `_iter_file_entries`（L375-407）——单遍递归 walk、`follow_symlinks=False`。
//!
//! 设计契约（计划 todo 27 / C8 明文）：
//! - [`faf_copy_files`]：≤[`CHUNK_SIZE`] 文件/批内部 rayon 并行；跨批进度/取消
//!   归 Python 侧（todo 29，批次粒度），本模块不做、不跨 FFI；
//! - 冲突改名（`_get_unique_target_path`）与分类复制保持 Python 侧（todo 29）；
//! - 复制跟随符号链接（`shutil.copy2` 语义；copytree `symlinks=False` 行为）；
//! - 大小聚合**不跟随**符号链接（`DirEntry::file_type()` 不解析目标）；
//! - per-file 失败 → 记入 `failed` 继续，**不中断整批**；
//! - JSON 输出 > [`crate::MAX_JSON_BYTES`] → `Err(crate::STATUS_TOO_LARGE)`。

use std::path::{Path, PathBuf};

use rayon::prelude::*;
use serde_json::Value;

use crate::{MAX_JSON_BYTES, STATUS_INVALID_ARG, STATUS_TOO_LARGE};

/// 单批并行复制的最大源数（进度/取消按批次粒度，由 Python 侧控制）。
const CHUNK_SIZE: usize = 32;

/// 单源复制成功结果。
#[derive(Debug)]
struct CopySuccess {
    src: String,
    dst: String,
    size: u64,
}

/// 单源复制失败结果。
#[derive(Debug)]
struct CopyFailure {
    src: String,
    error: String,
}

/// 复制文件并保留 mtime/权限（等价 `shutil.copy2` = copyfile + copystat）。
///
/// - 内容 + 基础属性：`std::fs::copy`（Windows 上同时复制只读等属性位）；
/// - mtime：`filetime::set_file_mtime`（等价 copystat 的 `os.utime` 写 mtime）；
/// - 权限：`std::fs::set_permissions`（等价 copystat 的 `shutil.copymode`）。
///
/// 跟随符号链接：`fs::copy` 默认解析目标，与 copy2 语义一致。
///
/// **Windows 只读坑**：`CopyFileW` 会把源只读属性复制到目标；`filetime` 的
/// `set_file_mtime` 以写模式打开目标文件，对只读目标会 `AccessDenied`（os error
/// 5）。故先临时清目标只读位 → 写 mtime → 最后恢复源权限。
///
/// `#[allow(clippy::permissions_set_readonly_false)]`：`set_readonly(false)` 为
/// Windows 上解锁 mtime 写入所必需；Unix 上的「world writable」中间态是瞬时的，
/// 紧随其后的 `set_permissions(dst, 源权限)` 立即还原（clippy 静态无法跨语句
/// 看见该恢复，故显式豁免）。
#[allow(clippy::permissions_set_readonly_false)]
fn copy_file_with_stat(src: &Path, dst: &Path) -> std::io::Result<u64> {
    let size = std::fs::copy(src, dst)?;
    let meta = std::fs::metadata(src)?;
    let mtime = meta.modified()?;
    // 目标若已被复制为只读，先临时清掉（写 mtime 需要写权限）。
    if let Ok(mut perm) = std::fs::metadata(dst).map(|m| m.permissions()) {
        if perm.readonly() {
            perm.set_readonly(false);
            let _ = std::fs::set_permissions(dst, perm);
        }
    }
    // copystat：保留 mtime（源值 → 目标）。
    filetime::set_file_mtime(dst, filetime::FileTime::from_system_time(mtime))?;
    // copystat：保留权限位（最后恢复源权限，含只读）。
    std::fs::set_permissions(dst, meta.permissions())?;
    Ok(size)
}

/// 递归复制目录树（等价 `shutil.copytree(src, dst, dirs_exist_ok=True)`）。
///
/// - `create_dir_all`：目标已存在也通过（dirs_exist_ok 语义）；
/// - 逐条目：目录递归、文件走 [`copy_file_with_stat`]；
/// - 跟随符号链接：`std::fs::metadata` 解析目标 → 目录递归 / 文件复制
///   （copytree `symlinks=False` 行为；悬空链接 → `metadata` 报错 → 整树失败，
///   与 copytree 未设 `ignore_dangling_symlinks` 的行为一致）；
/// - 后序把每个被复制目录的 mtime/权限置为源值（copystat 语义；先复制子项
///   再设 mtime，避免被后续写入刷新；目录元数据尽力而为，失败不致命）。
///
/// `#[allow(clippy::permissions_set_readonly_false)]`：同 [`copy_file_with_stat`]
/// ——Windows 只读目录无法写 mtime，临时清只读后由源权限恢复（Unix 中间态瞬时）。
#[allow(clippy::permissions_set_readonly_false)]
fn copy_tree(src: &Path, dst: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(dst)?;
    let mut subdirs: Vec<(PathBuf, PathBuf)> = Vec::new();
    for entry in std::fs::read_dir(src)? {
        let entry = entry?;
        let src_entry = entry.path();
        let dst_entry = dst.join(entry.file_name());
        // metadata 跟随符号链接：symlink→目录 也按目录递归（copytree symlinks=False）。
        let meta = std::fs::metadata(&src_entry)?;
        if meta.is_dir() {
            subdirs.push((src_entry, dst_entry));
        } else {
            copy_file_with_stat(&src_entry, &dst_entry)?;
        }
    }
    for (s, d) in subdirs {
        copy_tree(&s, &d)?;
    }
    // 后序目录元数据（尽力而为；同文件：先临时清只读再写 mtime，最后恢复权限）。
    if let Ok(meta) = std::fs::metadata(src) {
        if let Ok(mut perm) = std::fs::metadata(dst).map(|m| m.permissions()) {
            if perm.readonly() {
                perm.set_readonly(false);
                let _ = std::fs::set_permissions(dst, perm);
            }
        }
        if let Ok(mtime) = meta.modified() {
            let _ = filetime::set_file_mtime(dst, filetime::FileTime::from_system_time(mtime));
        }
        let _ = std::fs::set_permissions(dst, meta.permissions());
    }
    Ok(())
}

/// 复制单个源（文件或目录）到 `dest_dir` 下（目标名 = 源文件名）。
///
/// 目标路径冲突改名由 Python 侧 `_get_unique_target_path` 负责（todo 29）。
fn copy_one_source(src: &str, dest_dir: &Path) -> Result<CopySuccess, CopyFailure> {
    let src_path = Path::new(src);
    let file_name = match src_path.file_name() {
        Some(name) => name.to_string_lossy().into_owned(),
        None => {
            return Err(CopyFailure {
                src: src.to_string(),
                error: "invalid source path (no file name)".to_string(),
            });
        }
    };
    let dst = dest_dir.join(&file_name);
    let meta = match std::fs::metadata(src_path) {
        Ok(m) => m,
        Err(e) => {
            return Err(CopyFailure {
                src: src.to_string(),
                error: e.to_string(),
            });
        }
    };
    let result = if meta.is_dir() {
        copy_tree(src_path, &dst).map(|_| meta.len())
    } else {
        copy_file_with_stat(src_path, &dst)
    };
    match result {
        Ok(size) => Ok(CopySuccess {
            src: src.to_string(),
            dst: dst.to_string_lossy().into_owned(),
            size,
        }),
        Err(e) => Err(CopyFailure {
            src: src.to_string(),
            error: e.to_string(),
        }),
    }
}

/// `faf_copy_files` 实现：解析 `sources_json`，按 ≤[`CHUNK_SIZE`] 分批并行复制。
///
/// - `sources_json` 须为字符串数组（坏 JSON / 非数组 / 空串 → `STATUS_INVALID_ARG`）；
/// - 数组内非字符串条目 → 该条目记入 `failed`（不中断）；
/// - 成功返回 `{"copied":[{"src","dst","size"}],"failed":[{"src","error"}]}`；
/// - 输出超 [`MAX_JSON_BYTES`] → `Err(STATUS_TOO_LARGE)`。
pub fn copy_files_impl(sources_json: &str, dest_dir: &Path) -> Result<String, i32> {
    if sources_json.trim().is_empty() {
        return Err(STATUS_INVALID_ARG);
    }
    let parsed: Value = serde_json::from_str(sources_json).map_err(|_| STATUS_INVALID_ARG)?;
    let Some(arr) = parsed.as_array() else {
        return Err(STATUS_INVALID_ARG);
    };

    let mut copied: Vec<CopySuccess> = Vec::new();
    let mut failed: Vec<CopyFailure> = Vec::new();
    // 分批：批内 rayon 并行，批间顺序推进（并行度上限 = CHUNK_SIZE）。
    for chunk in arr.chunks(CHUNK_SIZE) {
        let results: Vec<Result<CopySuccess, CopyFailure>> = chunk
            .par_iter()
            .map(|item| match item.as_str() {
                Some(s) => copy_one_source(s, dest_dir),
                None => Err(CopyFailure {
                    src: item.to_string(),
                    error: "source entry is not a string".to_string(),
                }),
            })
            .collect();
        for r in results {
            match r {
                Ok(c) => copied.push(c),
                Err(f) => failed.push(f),
            }
        }
    }

    let copied_json: Vec<Value> = copied
        .iter()
        .map(|c| serde_json::json!({"src": c.src, "dst": c.dst, "size": c.size}))
        .collect();
    let failed_json: Vec<Value> = failed
        .iter()
        .map(|f| serde_json::json!({"src": f.src, "error": f.error}))
        .collect();
    let payload = serde_json::json!({"copied": copied_json, "failed": failed_json}).to_string();
    if payload.len() > MAX_JSON_BYTES {
        return Err(STATUS_TOO_LARGE);
    }
    Ok(payload)
}

/// 单目录递归求和（**不跟随符号链接**，等价 `_iter_file_entries` 的
/// `is_dir(follow_symlinks=False)` 语义）。
///
/// `DirEntry::file_type()` 不解析符号链接目标：symlink→文件 与 symlink→目录
/// 的 `is_file()`/`is_dir()` 均为 false，故符号链接条目被整体跳过。
fn sum_directory(dir: &Path) -> std::io::Result<u64> {
    fn walk(dir: &Path, total: &mut u64) -> std::io::Result<()> {
        for entry in std::fs::read_dir(dir)? {
            let entry = entry?;
            let ft = entry.file_type()?;
            if ft.is_dir() {
                walk(&entry.path(), total)?;
            } else if ft.is_file() {
                // 真实文件（非符号链接）：stat 计入大小；saturating 防溢出 panic。
                *total = total.saturating_add(entry.metadata()?.len());
            }
        }
        Ok(())
    }
    let mut total: u64 = 0;
    walk(dir, &mut total)?;
    Ok(total)
}

/// `faf_sum_directory_sizes` 实现：解析 `paths_json`（字符串数组），rayon
/// 顶层并行逐路径递归求和。
///
/// - 成功返回 `{"results":[{"path","size","error"}]}`（成功 `error` 为 null，
///   失败 `size` 为 0、`error` 为原因字符串）；
/// - 坏 JSON / 非数组 / 空串 → `STATUS_INVALID_ARG`；输出超限 → `STATUS_TOO_LARGE`。
pub fn sum_directory_sizes_impl(paths_json: &str) -> Result<String, i32> {
    if paths_json.trim().is_empty() {
        return Err(STATUS_INVALID_ARG);
    }
    let parsed: Value = serde_json::from_str(paths_json).map_err(|_| STATUS_INVALID_ARG)?;
    let Some(arr) = parsed.as_array() else {
        return Err(STATUS_INVALID_ARG);
    };

    let results: Vec<Value> = arr
        .par_iter()
        .map(|item| {
            let path = match item.as_str() {
                Some(s) => s,
                None => {
                    return serde_json::json!({
                        "path": item.to_string(),
                        "size": 0,
                        "error": "path entry is not a string",
                    });
                }
            };
            match sum_directory(Path::new(path)) {
                Ok(size) => serde_json::json!({"path": path, "size": size, "error": Value::Null}),
                Err(e) => serde_json::json!({"path": path, "size": 0, "error": e.to_string()}),
            }
        })
        .collect();

    let payload = serde_json::json!({"results": results}).to_string();
    if payload.len() > MAX_JSON_BYTES {
        return Err(STATUS_TOO_LARGE);
    }
    Ok(payload)
}

// ---------------------------------------------------------------------------
// 单测（todo 27 必写：复制正确性/递归/mtime/权限/目标存在/源缺失 per-file、
// 大小聚合/符号链接不跟随/缺失与权限错误）
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::{CStr, CString};
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::time::{Duration, SystemTime};

    static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

    /// 唯一临时根目录（测试并行安全）。
    struct TempDir(PathBuf);

    impl TempDir {
        fn new() -> Self {
            let n = TEST_COUNTER.fetch_add(1, Ordering::Relaxed);
            let p = std::env::temp_dir().join(format!(
                "faf_core_copy_test_{}_{}",
                std::process::id(),
                n
            ));
            std::fs::create_dir_all(&p).unwrap();
            TempDir(p)
        }

        fn path(&self) -> &Path {
            &self.0
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    /// 递归清除只读位（Windows 上只读文件无法直接删除）。
    fn make_writable(dir: &Path) {
        fn walk(d: &Path) {
            if let Ok(rd) = std::fs::read_dir(d) {
                for e in rd.flatten() {
                    let p = e.path();
                    if p.is_dir() {
                        walk(&p);
                    } else {
                        clear_readonly(&p);
                    }
                }
            }
            clear_readonly(d);
        }
        walk(dir);
    }

    /// 清除单个路径的只读位（`Permissions::set_readonly` 为全平台固有方法）。
    #[allow(clippy::permissions_set_readonly_false)]
    fn clear_readonly(p: &Path) {
        if let Ok(mut perm) = std::fs::metadata(p).map(|m| m.permissions()) {
            perm.set_readonly(false);
            let _ = std::fs::set_permissions(p, perm);
        }
    }

    /// 已知 mtime 参考值。
    fn known_mtime() -> SystemTime {
        SystemTime::UNIX_EPOCH + Duration::from_secs(1_700_000_000)
    }

    // ── 复制：文件 ──────────────────────────────────────────────────────────

    #[test]
    fn copy_file_preserves_content_and_mtime() {
        let tmp = TempDir::new();
        let src_dir = tmp.path().join("src");
        std::fs::create_dir_all(&src_dir).unwrap();
        let src_file = src_dir.join("a.txt");
        std::fs::write(&src_file, b"hello world").unwrap();
        let known = known_mtime();
        filetime::set_file_mtime(&src_file, filetime::FileTime::from_system_time(known)).unwrap();

        let dest_dir = tmp.path().join("dst");
        std::fs::create_dir_all(&dest_dir).unwrap();

        let c = copy_one_source(src_file.to_str().unwrap(), &dest_dir)
            .expect("单文件复制应成功");
        assert_eq!(c.dst, dest_dir.join("a.txt").to_string_lossy().into_owned());
        assert_eq!(c.size, 11, "copied.size 应为源文件字节数");
        let dst_file = dest_dir.join("a.txt");
        assert_eq!(std::fs::read(&dst_file).unwrap(), b"hello world");
        assert_eq!(
            std::fs::metadata(&dst_file).unwrap().modified().unwrap(),
            known,
            "目标 mtime 必须与源一致（copy2 copystat 语义）"
        );
    }

    #[test]
    fn copy_directory_tree_recursively() {
        let tmp = TempDir::new();
        let src = tmp.path().join("tree");
        std::fs::create_dir_all(src.join("sub").join("deep")).unwrap();
        std::fs::write(src.join("root.txt"), b"root").unwrap();
        std::fs::write(src.join("sub").join("inner.txt"), b"inner").unwrap();
        std::fs::write(src.join("sub").join("deep").join("leaf.txt"), b"leaf").unwrap();
        let dest_dir = tmp.path().join("dst");
        std::fs::create_dir_all(&dest_dir).unwrap();

        let c = copy_one_source(src.to_str().unwrap(), &dest_dir).expect("目录复制应成功");
        let dst = dest_dir.join("tree");
        assert!(dst.is_dir());
        assert!(dst.join("sub").is_dir());
        assert!(dst.join("sub").join("deep").is_dir());
        assert_eq!(std::fs::read(dst.join("root.txt")).unwrap(), b"root");
        assert_eq!(std::fs::read(dst.join("sub").join("inner.txt")).unwrap(), b"inner");
        assert_eq!(
            std::fs::read(dst.join("sub").join("deep").join("leaf.txt")).unwrap(),
            b"leaf"
        );
        assert_eq!(c.dst, dst.to_string_lossy().into_owned());
    }

    #[test]
    fn copy_directory_to_existing_destination_ok() {
        let tmp = TempDir::new();
        let src = tmp.path().join("tree");
        std::fs::create_dir_all(src.join("sub")).unwrap();
        std::fs::write(src.join("f.txt"), b"x").unwrap();
        let dest_dir = tmp.path().join("dst");
        // 目标已存在 → dirs_exist_ok=True 语义：不报错。
        std::fs::create_dir_all(dest_dir.join("tree")).unwrap();

        assert!(
            copy_one_source(src.to_str().unwrap(), &dest_dir).is_ok(),
            "目标目录已存在时复制不得失败（dirs_exist_ok=True）"
        );
        assert_eq!(std::fs::read(dest_dir.join("tree").join("f.txt")).unwrap(), b"x");
    }

    #[test]
    fn missing_source_is_per_file_failure_not_batch_abort() {
        let tmp = TempDir::new();
        let src_file = tmp.path().join("ok.txt");
        std::fs::write(&src_file, b"data").unwrap();
        let missing = tmp.path().join("missing.txt");
        let dest_dir = tmp.path().join("dst");
        std::fs::create_dir_all(&dest_dir).unwrap();

        let input = serde_json::json!([src_file.to_str().unwrap(), missing.to_str().unwrap()])
            .to_string();
        let payload = copy_files_impl(&input, &dest_dir).expect("整批不应因单源缺失而失败");
        let v: Value = serde_json::from_str(&payload).unwrap();
        assert_eq!(v["copied"].as_array().unwrap().len(), 1, "有效源应复制成功");
        assert_eq!(v["failed"].as_array().unwrap().len(), 1, "缺失源应记入 failed");
        assert_eq!(
            v["copied"][0]["dst"],
            dest_dir.join("ok.txt").to_string_lossy().into_owned()
        );
        assert_eq!(v["failed"][0]["src"], missing.to_str().unwrap());
        assert!(
            !v["failed"][0]["error"].as_str().unwrap().is_empty(),
            "失败原因不应为空"
        );
    }

    #[test]
    fn copy_preserves_readonly_permission() {
        let tmp = TempDir::new();
        let src = tmp.path().join("ro.txt");
        std::fs::write(&src, b"x").unwrap();
        let mut perm = std::fs::metadata(&src).unwrap().permissions();
        perm.set_readonly(true);
        std::fs::set_permissions(&src, perm).unwrap();
        let dest_dir = tmp.path().join("dst");
        std::fs::create_dir_all(&dest_dir).unwrap();

        copy_one_source(src.to_str().unwrap(), &dest_dir).expect("复制只读文件应成功");
        let dst = dest_dir.join("ro.txt");
        assert!(
            std::fs::metadata(&dst).unwrap().permissions().readonly(),
            "目标应保留源只读权限（copystat 权限位）"
        );
        make_writable(&dest_dir); // 清理只读位，保证 TempDir Drop 可删除
    }

    #[test]
    fn copy_ffi_null_args_return_null() {
        // null 输入必须返回 null（guard_c_str 守卫，safe extern "C" 调用无需 unsafe）。
        let raw = crate::faf_copy_files(
            std::ptr::null(),
            std::ptr::null(),
            std::ptr::null(),
        );
        assert!(raw.is_null());
    }

    #[test]
    fn copy_ffi_bad_json_returns_null() {
        let s = CString::new("not json").unwrap();
        let d = CString::new("C:\\").unwrap();
        let o = CString::new("{}").unwrap();
        // CString::as_ptr 为合法 NUL 终止 c_char_p；导出为 safe extern "C"。
        let raw = crate::faf_copy_files(s.as_ptr(), d.as_ptr(), o.as_ptr());
        assert!(raw.is_null(), "坏 JSON 应返回 null");
    }

    #[test]
    fn copy_ffi_roundtrip_and_empty_result() {
        let tmp = TempDir::new();
        let src = tmp.path().join("s.txt");
        std::fs::write(&src, b"hi").unwrap();
        let dest_dir = tmp.path().join("out");
        std::fs::create_dir_all(&dest_dir).unwrap();

        // serde_json::json! 保证反斜杠正确转义（Windows 路径含 `\`）。
        let sources = serde_json::json!([src.to_string_lossy()]).to_string();
        let s = CString::new(sources).unwrap();
        let d = CString::new(dest_dir.to_string_lossy().as_ref()).unwrap();
        let o = CString::new("{}").unwrap();
        // CString::as_ptr 为合法 NUL 终止 c_char_p；导出为 safe extern "C"。
        let raw = crate::faf_copy_files(s.as_ptr(), d.as_ptr(), o.as_ptr());
        assert!(!raw.is_null(), "合法入参不应返回 null");
        // SAFETY：raw 为本 crate 刚分配。
        let text = unsafe { CStr::from_ptr(raw) }.to_str().unwrap().to_string();
        crate::faf_free_message(raw);
        let v: Value = serde_json::from_str(&text).unwrap();
        assert_eq!(v["copied"].as_array().unwrap().len(), 1);
        assert_eq!(v["failed"].as_array().unwrap().len(), 0);
        assert_eq!(std::fs::read(dest_dir.join("s.txt")).unwrap(), b"hi");

        // 空数组 → 空结果（不报错）。
        let e = CString::new("[]").unwrap();
        // 导出为 safe extern "C"。
        let raw2 = crate::faf_copy_files(e.as_ptr(), d.as_ptr(), o.as_ptr());
        assert!(!raw2.is_null());
        // SAFETY：raw2 为本 crate 刚分配。
        let text2 = unsafe { CStr::from_ptr(raw2) }.to_str().unwrap().to_string();
        crate::faf_free_message(raw2);
        let v2: Value = serde_json::from_str(&text2).unwrap();
        assert_eq!(v2["copied"].as_array().unwrap().len(), 0);
        assert_eq!(v2["failed"].as_array().unwrap().len(), 0);
    }

    // ── 大小聚合 ──────────────────────────────────────────────────────────

    #[test]
    fn sum_directory_nested() {
        let tmp = TempDir::new();
        std::fs::create_dir_all(tmp.path().join("d/sub1/sub2")).unwrap();
        std::fs::write(tmp.path().join("d/a.txt"), vec![1u8; 100]).unwrap();
        std::fs::write(tmp.path().join("d/sub1/b.txt"), vec![2u8; 200]).unwrap();
        std::fs::write(tmp.path().join("d/sub1/sub2/c.txt"), vec![3u8; 300]).unwrap();

        let total = sum_directory(&tmp.path().join("d")).expect("嵌套目录求和应成功");
        assert_eq!(total, 600, "单遍递归 walk 应累加所有文件字节数");
    }

    #[test]
    fn sum_directory_ignores_symlink() {
        let tmp = TempDir::new();
        std::fs::create_dir_all(tmp.path().join("d")).unwrap();
        std::fs::create_dir_all(tmp.path().join("outside")).unwrap();
        std::fs::write(tmp.path().join("d/real.txt"), vec![9u8; 50]).unwrap();
        std::fs::write(tmp.path().join("outside/big.bin"), vec![0u8; 10_000]).unwrap();

        // Windows 上创建符号链接需要开发者模式/管理员权限；失败则跳过断言。
        let link = tmp.path().join("d").join("link_to_big");
        #[cfg(windows)]
        let link_ok = std::os::windows::fs::symlink_file(tmp.path().join("outside").join("big.bin"), &link).is_ok();
        #[cfg(unix)]
        let link_ok = std::os::unix::fs::symlink(tmp.path().join("outside").join("big.bin"), &link).is_ok();
        if !link_ok {
            return; // 无权限创建符号链接 → 跳过（本环境已知限制）
        }

        let total = sum_directory(&tmp.path().join("d")).expect("含符号链接的目录求和应成功");
        assert_eq!(total, 50, "follow_symlinks=False：符号链接目标不得计入");
    }

    #[test]
    fn sum_missing_path_reports_error() {
        let tmp = TempDir::new();
        let input = serde_json::json!([tmp.path().join("nope").to_str().unwrap()]).to_string();
        let payload = sum_directory_sizes_impl(&input).expect("缺失路径应返回 error 而非整批失败");
        let v: Value = serde_json::from_str(&payload).unwrap();
        let r = &v["results"][0];
        assert_eq!(r["size"], 0);
        assert!(
            r["error"].as_str().is_some(),
            "缺失路径应携带 error 字段"
        );
    }

    #[test]
    fn sum_file_path_reports_error() {
        let tmp = TempDir::new();
        let f = tmp.path().join("file.txt");
        std::fs::write(&f, b"x").unwrap();
        let input = serde_json::json!([f.to_str().unwrap()]).to_string();
        let payload = sum_directory_sizes_impl(&input).expect("非目录路径应返回 error 而非整批失败");
        let v: Value = serde_json::from_str(&payload).unwrap();
        assert!(
            v["results"][0]["error"].as_str().is_some(),
            "非目录路径（read_dir 失败）应携带 error 字段"
        );
    }

    #[test]
    fn sum_non_string_entry_reports_error() {
        let input = r#"[42]"#.to_string();
        let payload = sum_directory_sizes_impl(&input).expect("非字符串条目应返回 error 而非整批失败");
        let v: Value = serde_json::from_str(&payload).unwrap();
        assert_eq!(v["results"][0]["size"], 0);
        assert!(v["results"][0]["error"].as_str().is_some());
    }

    #[test]
    fn sum_empty_array_ok() {
        let payload = sum_directory_sizes_impl("[]").expect("空数组应返回空结果");
        let v: Value = serde_json::from_str(&payload).unwrap();
        assert_eq!(v["results"].as_array().unwrap().len(), 0);
    }

    #[test]
    fn sum_ffi_roundtrip() {
        let tmp = TempDir::new();
        std::fs::write(tmp.path().join("a.bin"), vec![1u8; 123]).unwrap();
        // serde_json::json! 保证反斜杠正确转义（Windows 路径含 `\`）。
        let paths = serde_json::json!([tmp.path().to_string_lossy()]).to_string();
        let p = CString::new(paths).unwrap();
        // CString::as_ptr 为合法 NUL 终止 c_char_p；导出为 safe extern "C"。
        let raw = crate::faf_sum_directory_sizes(p.as_ptr());
        assert!(!raw.is_null(), "合法入参不应返回 null");
        // SAFETY：raw 为本 crate 刚分配。
        let text = unsafe { CStr::from_ptr(raw) }.to_str().unwrap().to_string();
        crate::faf_free_message(raw);
        let v: Value = serde_json::from_str(&text).unwrap();
        assert_eq!(v["results"][0]["size"], 123);
        assert!(v["results"][0]["error"].is_null());
    }

    #[test]
    fn sum_ffi_null_and_bad_json_return_null() {
        // null 输入必须返回 null（guard_c_str 守卫，safe extern "C" 调用无需 unsafe）。
        assert!(crate::faf_sum_directory_sizes(std::ptr::null()).is_null());
        let bad = CString::new("not json").unwrap();
        // CString::as_ptr 为合法 NUL 终止 c_char_p；导出为 safe extern "C"。
        let raw = crate::faf_sum_directory_sizes(bad.as_ptr());
        assert!(raw.is_null(), "坏 JSON 应返回 null");
    }

    #[test]
    fn chunking_preserves_input_order() {
        // 复制结果顺序应与输入顺序一致（par_iter collect 保序），供 todo 29
        // 「错误元组顺序一致」使用。生成 35 个源（> CHUNK_SIZE 一桶）验证分批。
        let tmp = TempDir::new();
        let src_dir = tmp.path().join("srcs");
        std::fs::create_dir_all(&src_dir).unwrap();
        let mut items: Vec<Value> = Vec::new();
        for i in 0..35 {
            let f = src_dir.join(format!("f{:02}.txt", i));
            std::fs::write(&f, format!("data{i}")).unwrap();
            items.push(Value::String(f.to_string_lossy().into_owned()));
        }
        let dest_dir = tmp.path().join("out");
        std::fs::create_dir_all(&dest_dir).unwrap();

        let payload = copy_files_impl(&serde_json::json!(items).to_string(), &dest_dir)
            .expect("分批复制应成功");
        let v: Value = serde_json::from_str(&payload).unwrap();
        let copied = v["copied"].as_array().unwrap();
        assert_eq!(copied.len(), 35);
        for (i, c) in copied.iter().enumerate() {
            assert_eq!(
                c["src"],
                src_dir.join(format!("f{:02}.txt", i)).to_string_lossy().into_owned(),
                "结果必须保持输入顺序（批间顺序推进）"
            );
        }
    }

    // ── todo 28 边界补全：大文件 / 重名目标 / 空目录 / 深目录 / 取消语义 ──

    #[test]
    fn copy_large_file_content_and_mtime() {
        let tmp = TempDir::new();
        let src_dir = tmp.path().join("src");
        std::fs::create_dir_all(&src_dir).unwrap();
        let src_file = src_dir.join("big.bin");
        // ≥10MB 内容内存生成（模式字节便于逐字节核对；首字节非零避免稀疏文件优化干扰）。
        let size = 10 * 1024 * 1024;
        let mut data = vec![0u8; size];
        for (i, b) in data.iter_mut().enumerate() {
            *b = (i % 251) as u8;
        }
        std::fs::write(&src_file, &data).unwrap();
        let known = known_mtime();
        filetime::set_file_mtime(&src_file, filetime::FileTime::from_system_time(known)).unwrap();

        let dest_dir = tmp.path().join("dst");
        std::fs::create_dir_all(&dest_dir).unwrap();

        let start = std::time::Instant::now();
        let c = copy_one_source(src_file.to_str().unwrap(), &dest_dir).expect("大文件复制应成功");
        let elapsed = start.elapsed();
        eprintln!(
            "[perf] copy_large_file: {size} bytes copied in {:.1} ms",
            elapsed.as_secs_f64() * 1000.0
        );

        assert_eq!(c.size, size as u64, "copied.size 应为源字节数");
        let dst_file = dest_dir.join("big.bin");
        assert_eq!(std::fs::metadata(&dst_file).unwrap().len(), size as u64);
        assert_eq!(
            std::fs::metadata(&dst_file).unwrap().modified().unwrap(),
            known,
            "目标 mtime 必须与源一致（copy2 copystat 语义）"
        );
        // 读回整块逐字节比对（10MB 读入内存验证内容完全正确）。
        let back = std::fs::read(&dst_file).unwrap();
        assert_eq!(back, data, "目标内容必须与源逐字节一致");
    }

    #[test]
    fn copy_overwrites_existing_target_preserving_source_mtime() {
        let tmp = TempDir::new();
        let src_dir = tmp.path().join("src");
        std::fs::create_dir_all(&src_dir).unwrap();
        let src_file = src_dir.join("s.txt");
        std::fs::write(&src_file, b"new content").unwrap();
        let known = known_mtime();
        filetime::set_file_mtime(&src_file, filetime::FileTime::from_system_time(known)).unwrap();

        let dest_dir = tmp.path().join("dst");
        std::fs::create_dir_all(&dest_dir).unwrap();
        // 重名目标已存在（旧内容 + 远古 mtime）→ fs::copy 覆盖语义：必须覆盖成功、
        // 且目标 mtime 最终为源 mtime（等价 copy2 对已存在文件的覆盖行为；
        // 目录级 dirs_exist_ok 语义由 copy_directory_to_existing_destination_ok 覆盖）。
        let dst_file = dest_dir.join("s.txt");
        std::fs::write(&dst_file, b"old content").unwrap();
        filetime::set_file_mtime(
            &dst_file,
            filetime::FileTime::from_system_time(SystemTime::UNIX_EPOCH + Duration::from_secs(1)),
        )
        .unwrap();

        let c = copy_one_source(src_file.to_str().unwrap(), &dest_dir).expect("重名文件复制应覆盖成功");
        assert_eq!(c.size, 11);
        assert_eq!(
            std::fs::read(&dst_file).unwrap(),
            b"new content",
            "目标内容必须被源覆盖（fs::copy 覆盖语义）"
        );
        assert_eq!(
            std::fs::metadata(&dst_file).unwrap().modified().unwrap(),
            known,
            "覆盖后目标 mtime 必须为源 mtime（copy2 copystat）"
        );
    }

    #[test]
    fn copy_empty_directory_and_sum_zero() {
        let tmp = TempDir::new();
        let empty = tmp.path().join("empty");
        std::fs::create_dir_all(&empty).unwrap();
        let dest_dir = tmp.path().join("dst");
        std::fs::create_dir_all(&dest_dir).unwrap();

        let c = copy_one_source(empty.to_str().unwrap(), &dest_dir).expect("空目录复制应成功");
        let dst = dest_dir.join("empty");
        assert!(dst.is_dir(), "空目录复制后目标目录必须存在");
        assert_eq!(std::fs::read_dir(&dst).unwrap().count(), 0, "目标应为空目录");
        // 空目录大小聚合 = 0（源空目录 len=0；sizesum 递归结果 0）。
        assert_eq!(c.size, 0, "空目录顶层 metadata len 应为 0");
        assert_eq!(
            sum_directory(&dst).expect("空目录求和应成功"),
            0,
            "空目录 sizesum 必须为 0"
        );
    }

    #[test]
    fn copy_deep_directory_tree_with_sizesum() {
        let tmp = TempDir::new();
        // 8 层嵌套：deep/l1/.../l8；最深目录放 leaf,每层 1 个小文件。
        let src = tmp.path().join("deep");
        let mut cur = src.clone();
        for i in 1..=8 {
            cur = cur.join(format!("l{}", i));
        }
        std::fs::create_dir_all(&cur).unwrap();
        let leaf = cur.join("leaf.bin");
        std::fs::write(&leaf, vec![7u8; 777]).unwrap();
        let known = known_mtime();
        filetime::set_file_mtime(&leaf, filetime::FileTime::from_system_time(known)).unwrap();
        // 各层小文件 → sizesum 手算值（每层文件 "level N" 长度 7）。
        let mut expected = 777u64;
        let mut layer_dir = src.clone();
        for i in 1..=8 {
            layer_dir = layer_dir.join(format!("l{}", i));
            let f = layer_dir.join(format!("layer{}.txt", i));
            std::fs::write(&f, format!("level {}", i)).unwrap();
            expected += format!("level {}", i).len() as u64;
        }

        let dest_dir = tmp.path().join("dst");
        std::fs::create_dir_all(&dest_dir).unwrap();
        copy_one_source(src.to_str().unwrap(), &dest_dir).expect("8 层嵌套深目录复制不得 panic/失败");
        let dst = dest_dir.join("deep");

        // 结构逐层校验。
        let mut expect_dir = dst.clone();
        for i in 1..=8 {
            expect_dir = expect_dir.join(format!("l{}", i));
            assert!(expect_dir.is_dir(), "第 {} 层目录必须存在", i);
        }
        // leaf 内容 + mtime（深层文件 copystat）。
        let dst_leaf = expect_dir.join("leaf.bin");
        assert_eq!(std::fs::read(&dst_leaf).unwrap(), vec![7u8; 777]);
        assert_eq!(
            std::fs::metadata(&dst_leaf).unwrap().modified().unwrap(),
            known,
            "深层文件 mtime 必须与源一致"
        );
        // 目录 mtime 后序保留（copytree 语义；root 与最深层各验一处）。
        assert_eq!(
            std::fs::metadata(&dst).unwrap().modified().unwrap(),
            std::fs::metadata(&src).unwrap().modified().unwrap()
        );
        assert_eq!(
            std::fs::metadata(&expect_dir).unwrap().modified().unwrap(),
            std::fs::metadata(&cur).unwrap().modified().unwrap()
        );
        // sizesum：目标树 == 源树 == 手算值。
        assert_eq!(
            sum_directory(&dst).expect("目标树求和应成功"),
            expected,
            "复制后 sizesum 必须等于各文件字节和"
        );
        assert_eq!(
            sum_directory(&src).expect("源树求和应成功"),
            expected,
            "源树 sizesum 应为手算值"
        );
    }

    /// 取消语义（impl 层无长阻塞点/无泄漏，仅记录——真正的批间取消在 todo 29
    /// Python 侧 `should_stop` 检查）。
    ///
    /// 设计契约：取消是**批间**的，Python 侧在批次边界检查；本 impl 层批内 =
    /// ≤[`CHUNK_SIZE`] 源 rayon 并行，单源 = 一次文件/目录复制——不存在单个
    /// 长阻塞点（无跨 FFI 轮询、无自建取消标志）。“无泄漏” = 无全局可变状态：
    /// 同一进程内重复调用首次、二次结果必须逐字节一致（对照 hash.rs L4 教训）。
    #[test]
    fn copy_batch_bounded_and_repeatable() {
        let tmp = TempDir::new();
        let src_dir = tmp.path().join("srcs");
        std::fs::create_dir_all(&src_dir).unwrap();
        let mut items: Vec<Value> = Vec::new();
        for i in 0..100 {
            let f = src_dir.join(format!("f{:03}.txt", i));
            std::fs::write(&f, vec![b'x'; 10_000]).unwrap();
            items.push(Value::String(f.to_string_lossy().into_owned()));
        }
        let dest_dir = tmp.path().join("out");
        std::fs::create_dir_all(&dest_dir).unwrap();
        let input = serde_json::json!(items).to_string();

        let start = std::time::Instant::now();
        let payload = copy_files_impl(&input, &dest_dir).expect("100 源分批复制应成功");
        let elapsed = start.elapsed();
        eprintln!(
            "[perf] copy_batch_bounded: 100×10KB in {:.1} ms (4 chunks × ≤32 rayon)",
            elapsed.as_secs_f64() * 1000.0
        );
        // 宽松防 flaky：100 个 10KB 小文件应秒级完成；上限 30s 只证「批内无长阻塞」。
        assert!(
            elapsed < Duration::from_secs(30),
            "impl 层批内不应存在长阻塞点（宽松上限 30s，实际 {:?}）",
            elapsed
        );
        let v: Value = serde_json::from_str(&payload).unwrap();
        assert_eq!(v["copied"].as_array().unwrap().len(), 100);
        assert_eq!(v["failed"].as_array().unwrap().len(), 0);
        // 重复调用（独立目标目录）→ `src`/`size`/`failed` 与首次逐项一致
        //（无全局状态泄漏；`dst` 因目标目录不同必然相异，故不比较）。
        let dest2 = tmp.path().join("out2");
        std::fs::create_dir_all(&dest2).unwrap();
        let payload2 = copy_files_impl(&input, &dest2).expect("重复调用应成功");
        let v2: Value = serde_json::from_str(&payload2).unwrap();
        let copied2 = v2["copied"].as_array().unwrap();
        assert_eq!(copied2.len(), 100);
        for (a, b) in v["copied"]
            .as_array()
            .unwrap()
            .iter()
            .zip(copied2.iter())
        {
            assert_eq!(a["src"], b["src"], "重复调用 src 序列必须一致");
            assert_eq!(a["size"], b["size"], "重复调用 size 序列必须一致");
        }
        assert_eq!(v2["failed"].as_array().unwrap().len(), 0);
    }
}
