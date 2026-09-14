//! todo 6：`faf_scan_directory` 目录扫描实现（`scan_directory_impl`）。
//!
//! 语义 oracle：`freeassetfilter/ui/layout/file_selector_layout.py`
//! `_collect_directory_entries`（L1254-1279）。逐字节对齐要点：
//! - `os.listdir` ↔ `std::fs::read_dir`（枚举顺序不同无妨，对拍按 name 键序无关比较）；
//! - 每项一次 stat（`std::fs::metadata`，跟随符号链接 == `os.stat`），
//!   `is_dir = meta.file_type().is_dir()`（复用同一次 metadata，不再二次 stat）；
//! - `suffix = os.path.splitext(name)[1].lower().lstrip(".")`、目录为空串；
//! - `modified/created = fromtimestamp(...).strftime("%Y-%m-%d %H:%M")`
//!   （本地时区，Rust 侧 `chrono::Local`）；
//! - 逐项 `PermissionError/OSError` → 跳过；
//! - 目录不可读 → Err 状态码（`NotFound` → -4，其余 I/O → -2）；
//! - `Metadata::created()` 返回 Err → 回退 modified 格式化值；
//! - JSON 输出 > [`MAX_JSON_BYTES`] → `Err(STATUS_TOO_LARGE)`。
//!
//! **不实现排序**（并行 todo 7 的 `sort.rs` 拥有；勿读勿改）。不用 Win32 API
//! 直调（`std::fs` 底层即 `FindFirstFileW`）。
//!
//! 序列化说明：`Cargo.toml` 只直依赖 `serde_json`（`serde` 仅为传递依赖，且本
//! todo 禁止改 Cargo.toml），故 7 键 JSON 经 `serde_json::json!` 构建而非
//! `#[derive(Serialize)]`；输出形态与 oracle dict 完全同构。

use std::fs::Metadata;
use std::io::Result as IoResult;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use crate::{
    MAX_JSON_BYTES, STATUS_INTERNAL, STATUS_IO_ERROR, STATUS_NOT_FOUND, STATUS_TOO_LARGE,
};

/// `modified()` 异常兜底值（Windows 上 stat 成功后取不到 mtime 实际不会发生）。
const FALLBACK_TIME: &str = "1970-01-01 00:00";

/// 目录扫描单条目（7 键，与 oracle `_collect_directory_entries` 逐字段对齐）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Entry {
    /// 文件名（UTF-8 有损解码；Windows 上罕见非法代理对按 U+FFFD 输出）。
    pub name: String,
    /// 完整路径（`dir_entry.path()`，与 Python `os.path.join` 同分隔符语义）。
    pub path: String,
    /// 是否目录（复用同一次 metadata 的 `file_type().is_dir()`，跟随符号链接）。
    pub is_dir: bool,
    /// 字节大小（目录通常为 0，与 `st.st_size` 同源）。
    pub size: u64,
    /// 修改时间 `"%Y-%m-%d %H:%M"`（本地时区）。
    pub modified: String,
    /// 创建时间 `"%Y-%m-%d %H:%M"`（本地时区）；`created()` Err 时回退 modified。
    pub created: String,
    /// 扩展名（`splitext[1].lower().lstrip(".")`）；目录为空串。
    pub suffix: String,
}

/// 扫描目录并返回**原始未排序**条目列表（顺序为 `read_dir` 枚举序）。
///
/// - 目录不可读/不存在 → `Err(STATUS_NOT_FOUND)`（NotFound）或 `Err(STATUS_IO_ERROR)`；
/// - 逐项 stat 失败（权限等）→ 跳过该条目；
/// - 条目命名空间按 `to_string_lossy` 有损解码，绝不 panic。
pub fn scan_directory_impl(path: &Path) -> Result<Vec<Entry>, i32> {
    let read_dir = match std::fs::read_dir(path) {
        Ok(rd) => rd,
        Err(e) => {
            return Err(match e.kind() {
                std::io::ErrorKind::NotFound => STATUS_NOT_FOUND,
                _ => STATUS_IO_ERROR,
            });
        }
    };
    let mut entries: Vec<Entry> = Vec::new();
    for item in read_dir {
        // read_dir 迭代项本身失败（罕见）→ 跳过，与逐项错误跳过语义一致。
        let Ok(dir_entry) = item else { continue };
        let name = dir_entry.file_name().to_string_lossy().into_owned();
        let full_path = dir_entry.path();
        // 每项一次 stat（跟随符号链接，等价 Python `os.stat`）。
        let meta = std::fs::metadata(&full_path);
        if let Some(entry) = entry_from_metadata(name, full_path, &meta) {
            entries.push(entry);
        }
    }
    Ok(entries)
}

/// 把「文件名 + 完整路径 + stat 结果」转为条目；metadata 为 Err（权限等）→ None（跳过）。
///
/// 独立成函数以便在 Windows 上直接以注入的 `Err(PermissionDenied)` 模拟
/// 不可读条目（见 `dir_samples/PERMISSIONS_NOTE.txt`；icacls deny 需提权且
/// 污染 checkout，故夹具不构造真实不可读文件）。
fn entry_from_metadata(name: String, full_path: PathBuf, meta: &IoResult<Metadata>) -> Option<Entry> {
    match meta {
        Ok(m) => Some(build_entry(&name, &full_path, m)),
        Err(_) => None,
    }
}

/// 由单次 stat 结果构造条目（字段计算核心）。
fn build_entry(name: &str, full_path: &Path, meta: &Metadata) -> Entry {
    let is_dir = meta.file_type().is_dir();
    let modified = meta
        .modified()
        .map(format_local_time)
        .unwrap_or_else(|_| FALLBACK_TIME.to_string());
    let created = created_or_modified(&meta.created(), &modified);
    Entry {
        name: name.to_string(),
        path: full_path.to_string_lossy().into_owned(),
        is_dir,
        size: meta.len(),
        modified,
        created,
        suffix: compute_suffix(name, is_dir),
    }
}

/// `created()` 结果 → 格式化创建时间；Err 时回退已格式化的 modified 值。
///
/// 独立成函数以便单测直接注入 `Err` 覆盖回退分支（Windows 真实文件
/// `created()` 成功，无法天然触发）。
fn created_or_modified(created: &IoResult<SystemTime>, modified: &str) -> String {
    match created {
        Ok(t) => format_local_time(*t),
        Err(_) => modified.to_string(),
    }
}

/// `SystemTime` → 本地时区 `"%Y-%m-%d %H:%M"` 字符串（等价
/// `datetime.fromtimestamp(...).strftime("%Y-%m-%d %H:%M")`）。
fn format_local_time(t: SystemTime) -> String {
    let dt: chrono::DateTime<chrono::Local> = t.into();
    dt.format("%Y-%m-%d %H:%M").to_string()
}

/// 目录 → 空串；否则 `splitext(name)[1].lower().lstrip(".")`。
fn compute_suffix(name: &str, is_dir: bool) -> String {
    if is_dir {
        return String::new();
    }
    split_ext(name)
        .1
        .to_lowercase()
        .trim_start_matches('.')
        .to_string()
}

/// Python `os.path.splitext`（ntpath 语义，3.11 实测逐例对齐）的等价实现。
///
/// 规则（实测样例）：`README.md`→`.md`、`.hidden.txt`→`.txt`、`.a.b`→`.b`、
/// `file.`→`.`、`.hidden_config`→``、`.hidden`→``、`..foo`→``、`...`→``、
/// `..`→``、`.`→``。核心：取最后一个点（在最后分隔符之后），若「分隔符后到
/// 该点之间全是点」则为前导点文件名 → 无扩展名；否则从该点起切为扩展名。
fn split_ext(name: &str) -> (&str, &str) {
    // `rfind(['/', '\\'])` 与 ntpath 的 `rfind(_seps)`（`'\\/'`）等价。
    let sep_pos: isize = name.rfind(['/', '\\']).map_or(-1, |i| i as isize);
    let Some(dot) = name.rfind('.') else {
        return (name, "");
    };
    let dot_pos = dot as isize;
    if dot_pos <= sep_pos {
        return (name, "");
    }
    // Skip all leading dots（`.` 为 ASCII 字节，字节索引即字符边界，切片安全）。
    let mut filename_index: isize = sep_pos + 1;
    while filename_index < dot_pos {
        if name.as_bytes()[filename_index as usize] != b'.' {
            break;
        }
        filename_index += 1;
    }
    if filename_index == dot_pos {
        // 分隔符后到最后一个点全是点 → 前导点文件名，无扩展名。
        (name, "")
    } else {
        (&name[..dot], &name[dot..])
    }
}

/// 序列化条目列表为 JSON 数组；输出超 [`MAX_JSON_BYTES`] → `Err(STATUS_TOO_LARGE)`。
///
/// 用 `serde_json::json!` 构建（避免依赖传递的 `serde` derive），键序与 oracle
/// dict 同构（`name/path/is_dir/size/modified/created/suffix`）。
pub(crate) fn entries_to_json(entries: &[Entry]) -> Result<String, i32> {
    let values: Vec<serde_json::Value> = entries
        .iter()
        .map(|e| {
            serde_json::json!({
                "name": e.name,
                "path": e.path,
                "is_dir": e.is_dir,
                "size": e.size,
                "modified": e.modified,
                "created": e.created,
                "suffix": e.suffix,
            })
        })
        .collect();
    let payload = serde_json::to_string(&values).map_err(|_| STATUS_INTERNAL)?;
    if payload.len() > MAX_JSON_BYTES {
        return Err(STATUS_TOO_LARGE);
    }
    Ok(payload)
}

// ---------------------------------------------------------------------------
// 单测（todo 6 必写：字段/子目录/隐藏文件/权限跳过/目录不可读/UTF-8/
// created 回退/>8MB→-7 + FFI null/不存在目录）
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::{CStr, CString};

    use crate::{faf_free_message, faf_scan_directory};

    /// 测试临时目录守卫：创建唯一子目录，Drop 时尽力清理。
    struct TestDir {
        path: PathBuf,
    }

    impl TestDir {
        fn new(name: &str) -> Self {
            let dir = std::env::temp_dir().join(format!(
                "faf_core_scan_test_{name}_{}",
                std::process::id()
            ));
            let _ = std::fs::remove_dir_all(&dir);
            std::fs::create_dir_all(&dir).expect("创建临时测试目录");
            TestDir { path: dir }
        }

        /// 在测试目录下写一个文件（自动创建父目录）。
        fn file(&self, name: &str, content: &str) -> PathBuf {
            let p = self.path.join(name);
            if let Some(parent) = p.parent() {
                let _ = std::fs::create_dir_all(parent);
            }
            std::fs::write(&p, content).expect("写入临时测试文件");
            p
        }

        /// 在测试目录下创建子目录。
        fn dir(&self, name: &str) -> PathBuf {
            let p = self.path.join(name);
            std::fs::create_dir_all(&p).expect("创建临时测试子目录");
            p
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.path);
        }
    }

    /// 断言字符串符合 `%Y-%m-%d %H:%M` 形态（16 字符）。
    fn assert_fmt_time(s: &str) {
        assert_eq!(s.len(), 16, "时间串长度应为 16: {s:?}");
        assert_eq!(&s[4..5], "-");
        assert_eq!(&s[7..8], "-");
        assert_eq!(&s[10..11], " ");
        assert_eq!(&s[13..14], ":");
        for i in [0, 1, 2, 3, 5, 6, 8, 9, 11, 12, 14, 15] {
            assert!(s.as_bytes()[i].is_ascii_digit(), "第 {i} 字符非数字: {s:?}");
        }
    }

    #[test]
    fn normal_dir_fields_match_oracle_shape() {
        let td = TestDir::new("normal");
        td.file("README.md", "hello");
        let entries = scan_directory_impl(&td.path).expect("应成功扫描");
        assert_eq!(entries.len(), 1);
        let e = &entries[0];
        assert_eq!(e.name, "README.md");
        assert_eq!(e.path, td.path.join("README.md").to_string_lossy());
        assert!(!e.is_dir);
        assert_eq!(e.size, 5);
        assert_eq!(e.suffix, "md");
        assert_fmt_time(&e.modified);
        assert_fmt_time(&e.created);
        // JSON 往返：7 键齐全。
        let payload = entries_to_json(&entries).expect("应可序列化");
        let parsed: serde_json::Value = serde_json::from_str(&payload).expect("应可解析");
        assert_eq!(parsed.as_array().unwrap().len(), 1);
        let obj = &parsed[0];
        for key in ["name", "path", "is_dir", "size", "modified", "created", "suffix"] {
            assert!(obj.get(key).is_some(), "缺少键 {key}");
        }
        assert_eq!(obj["name"], "README.md");
        assert_eq!(obj["suffix"], "md");
        assert!(!obj["is_dir"].as_bool().unwrap());
    }

    #[test]
    fn subdir_is_dir_true_and_empty_suffix() {
        let td = TestDir::new("subdir");
        td.file("root.txt", "x");
        td.dir("src");
        let entries = scan_directory_impl(&td.path).expect("应成功扫描");
        assert_eq!(entries.len(), 2);
        let sub = entries.iter().find(|e| e.name == "src").expect("应含子目录");
        assert!(sub.is_dir);
        assert_eq!(sub.suffix, "", "目录 suffix 应为空串");
        // 目录 size 通常为 0（与 Python st.st_size 同源，对拍以实测为准）。
        assert_eq!(sub.size, 0);
    }

    #[test]
    fn hidden_file_included_with_empty_suffix() {
        let td = TestDir::new("hidden");
        td.file(".hidden_config", "secret");
        td.file(".hidden_token", "tok");
        let entries = scan_directory_impl(&td.path).expect("应成功扫描");
        assert_eq!(entries.len(), 2);
        for e in &entries {
            assert_eq!(e.suffix, "", "前导点文件 suffix 应为空串: {}", e.name);
        }
    }

    #[test]
    fn metadata_error_skips_entry() {
        // Windows 无法廉价构造真实不可读文件（icacls deny 需提权且污染 checkout），
        // 以注入 Err(PermissionDenied) 模拟 PermissionError 跳过路径。
        let err: IoResult<Metadata> =
            Err(std::io::Error::new(std::io::ErrorKind::PermissionDenied, "simulated"));
        let got = entry_from_metadata(
            "secret.txt".to_string(),
            PathBuf::from(r"C:\fake\secret.txt"),
            &err,
        );
        assert!(got.is_none(), "metadata Err 应跳过该条目");
    }

    #[test]
    fn nonexistent_dir_returns_not_found() {
        let err = scan_directory_impl(Path::new(r"C:\faf_core_no_such_dir_xyz_0123"));
        assert_eq!(err, Err(STATUS_NOT_FOUND));
        // 指向文件而非目录 → read_dir 报错（IO_ERROR）。
        let td = TestDir::new("file_as_dir");
        let f = td.file("plain.txt", "x");
        assert_eq!(scan_directory_impl(&f), Err(STATUS_IO_ERROR));
    }

    #[test]
    fn created_err_falls_back_to_modified() {
        // 注入 Err：必须返回 modified 格式化值（验收判据）。
        let err: IoResult<SystemTime> = Err(std::io::Error::other("no created"));
        assert_eq!(
            created_or_modified(&err, "2020-06-01 12:30"),
            "2020-06-01 12:30"
        );
        // Ok：走 format_local_time（本机本地时区，不返回 modified）。
        let ok: IoResult<SystemTime> = Ok(SystemTime::UNIX_EPOCH);
        let got = created_or_modified(&ok, "ignored");
        assert_eq!(got, format_local_time(SystemTime::UNIX_EPOCH));
        assert_ne!(got, "ignored");
    }

    #[test]
    fn utf8_filenames_preserved() {
        let td = TestDir::new("utf8");
        td.file("数据报告_2026.txt", "数据");
        td.file("说明_README.txt", "说明");
        let entries = scan_directory_impl(&td.path).expect("应成功扫描");
        assert_eq!(entries.len(), 2);
        let cjk = entries
            .iter()
            .find(|e| e.name.starts_with("数据报告"))
            .expect("应含中文名条目");
        assert_eq!(cjk.name, "数据报告_2026.txt");
        assert_eq!(cjk.suffix, "txt");
        assert_eq!(cjk.path, td.path.join("数据报告_2026.txt").to_string_lossy());
    }

    #[test]
    fn split_ext_matches_python_ntpath() {
        // 与 Python 3.11 ntpath.splitext 实测输出逐例对齐（ground truth 见 probe）。
        let cases: &[(&str, &str)] = &[
            ("README.md", ".md"),
            (".hidden_config", ""),
            (".hidden_token", ""),
            (".hidden.txt", ".txt"),
            ("...", ""),
            ("..foo", ""),
            ("data_2026.csv", ".csv"),
            ("说明_README.txt", ".txt"),
            ("file.", "."),
            ("a.b.c", ".c"),
            (".", ""),
            ("..", ""),
            (".a.b", ".b"),
            (".bashrc.tar", ".tar"),
            ("main.py", ".py"),
        ];
        for (name, ext) in cases {
            assert_eq!(split_ext(name).1, *ext, "splitext 分歧: {name:?}");
        }
    }

    #[test]
    fn suffix_lower_strip_and_dir_empty() {
        assert_eq!(compute_suffix("archive.tar.gz", false), "gz");
        assert_eq!(compute_suffix("README.MD", false), "md");
        assert_eq!(compute_suffix(".hidden_config", false), "");
        assert_eq!(compute_suffix("file.", false), "");
        assert_eq!(compute_suffix("src", true), "");
        assert_eq!(compute_suffix("目录", true), "");
    }

    #[test]
    fn oversize_json_returns_status_too_large() {
        // 单条 8MB name 的 JSON 输出必然 > MAX_JSON_BYTES（8MB）→ -7。
        let entries = vec![Entry {
            name: "x".repeat(MAX_JSON_BYTES),
            path: "p".to_string(),
            is_dir: false,
            size: 0,
            modified: FALLBACK_TIME.to_string(),
            created: FALLBACK_TIME.to_string(),
            suffix: String::new(),
        }];
        assert_eq!(entries_to_json(&entries), Err(STATUS_TOO_LARGE));
        // 反例：正常小载荷 → Ok 且未超限。
        let small = vec![Entry {
            name: "a.txt".to_string(),
            path: "a.txt".to_string(),
            is_dir: false,
            size: 1,
            modified: FALLBACK_TIME.to_string(),
            created: FALLBACK_TIME.to_string(),
            suffix: "txt".to_string(),
        }];
        let payload = entries_to_json(&small).expect("小载荷应序列化成功");
        assert!(payload.len() <= MAX_JSON_BYTES);
        assert!(payload.starts_with('['));
    }

    // ── 边界测试（todo 8：空目录/单文件/超长文件名/非 UTF-8/1k 性能/50k 上限）────

    /// 直接构造假条目（性能/上限测试用，不落盘）。
    /// `inflated` 为 true 时生成放大 name/path，用于快速撑爆 8MB 上限。
    fn fake_entry(i: u32, prefix: &str, inflated: bool) -> Entry {
        let (name, path) = if inflated {
            // 每条 ≈350B，50k 条 ≈17MB，远超 8MB 上限。
            let filler = "x".repeat(100);
            let name = format!("{prefix}{i:05}_{filler}");
            (name.clone(), format!("C:/simulated/very/deep/dir/tree/{name}"))
        } else {
            let name = format!("{prefix}{i:05}.txt");
            (name.clone(), format!("C:/simulated/dir/{name}"))
        };
        Entry {
            name,
            path,
            is_dir: i.is_multiple_of(7),
            size: (i as u64) * 1_048_576 % 10_000_000,
            modified: format!(
                "2024-{:02}-{:02} {:02}:{:02}",
                1 + (i % 12),
                1 + (i % 28),
                i % 24,
                i % 60
            ),
            created: format!("2023-{:02}-{:02} 00:00", 1 + (i % 12), 1 + (i % 28)),
            suffix: String::new(),
        }
    }

    #[test]
    fn empty_directory_returns_zero_entries() {
        let td = TestDir::new("empty");
        let entries = scan_directory_impl(&td.path).expect("空目录应扫描成功");
        assert!(entries.is_empty(), "空目录不应产出条目");
        let payload = entries_to_json(&entries).expect("空列表序列化成功");
        assert_eq!(payload, "[]");
        // FFI 往返：空目录 → 非空指针且可解析为 []。
        let cpath = CString::new(td.path.to_str().expect("临时路径应为 UTF-8")).unwrap();
        let raw = faf_scan_directory(cpath.as_ptr());
        assert!(!raw.is_null(), "空目录应返回非空 JSON");
        let text = unsafe { CStr::from_ptr(raw) }.to_str().unwrap().to_string();
        faf_free_message(raw);
        assert_eq!(text, "[]");
    }

    #[test]
    fn single_file_directory_scans_one_entry() {
        let td = TestDir::new("single");
        td.file("only.txt", "solo");
        let entries = scan_directory_impl(&td.path).expect("应成功扫描");
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].name, "only.txt");
        assert_eq!(entries[0].suffix, "txt");
        assert!(!entries[0].is_dir);
    }

    #[test]
    fn long_filename_240_chars_scans_ok() {
        let td = TestDir::new("longname");
        // Windows 文件名上限 255，取 240 字符做边界（含扩展名的总名长）。
        let name = format!("{}.txt", "d".repeat(236));
        assert_eq!(name.chars().count(), 240);
        td.file(&name, "x");
        let entries = scan_directory_impl(&td.path).expect("超长文件名目录应扫描成功");
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].name, name);
        assert_eq!(entries[0].name.chars().count(), 240);
        assert_eq!(entries[0].suffix, "txt");
    }

    /// 非 UTF-8 文件名：有损解码（`to_string_lossy`）只替换非法代理对，绝不 panic。
    ///
    /// Windows 上真实文件名经 UTF-16；Win32 对未配对代理对的创建支持因版本而异，
    /// 无法创建的场合记录说明并跳过真实文件路径（计划注明的合理降级）。
    #[test]
    fn non_utf8_filename_lossy_decode_no_panic() {
        #[cfg(windows)]
        {
            use std::os::windows::ffi::OsStringExt;
            // "data" + 未配对高代理项 0xD800 + ".bin"：非法 UTF-16 标量序列。
            let mut wide: Vec<u16> = "data".encode_utf16().collect();
            wide.push(0xD800);
            wide.extend(".bin".encode_utf16());
            let name_os = std::ffi::OsString::from_wide(&wide);
            assert!(
                name_os.to_string_lossy().contains('\u{FFFD}'),
                "非法代理对应按 U+FFFD 有损替换"
            );
            let td = TestDir::new("nonutf8");
            let full = td.path.join(&name_os);
            match std::fs::write(&full, b"payload") {
                Ok(()) => {
                    let entries =
                        scan_directory_impl(&td.path).expect("含非法代理名条目的目录扫描不应 panic");
                    assert_eq!(entries.len(), 1);
                    assert!(
                        entries[0].name.contains('\u{FFFD}'),
                        "有损解码后的条目名应含 U+FFFD"
                    );
                }
                Err(e) => eprintln!(
                    "NOTE: 本机无法创建未配对代理对文件名（{e}），已跳过真实文件路径（文档化限制）"
                ),
            }
        }
        #[cfg(not(windows))]
        {
            // 非 Windows：非法 UTF-8 字节 → 有损解码含 U+FFFD 且不 panic。
            use std::os::unix::ffi::OsStringExt;
            let os = std::ffi::OsString::from_vec(vec![0x66, 0x80, 0x80, 0x62]); // 'f' + 非法 + 'b'
            assert!(os.to_string_lossy().contains('\u{FFFD}'));
        }
    }

    /// 1k 条目 `entries_to_json` 性能回归：<100ms（宽松阈值防 flaky），耗时打印。
    #[test]
    fn thousand_entries_entries_to_json_under_100ms() {
        let entries: Vec<Entry> = (0..1000).map(|i| fake_entry(i, "file_", false)).collect();
        let start = std::time::Instant::now();
        let payload = entries_to_json(&entries).expect("1k 条目应可序列化");
        let elapsed = start.elapsed();
        eprintln!("entries_to_json 1k entries: {elapsed:?}");
        assert!(
            elapsed.as_millis() < 100,
            "1k 条目序列化耗时 {elapsed:?} 超过 100ms 预算"
        );
        let parsed: serde_json::Value = serde_json::from_str(&payload).expect("应可解析");
        assert_eq!(parsed.as_array().unwrap().len(), 1000);
    }

    /// >8MB 上限扩展：50k 虚假条目模拟超大目录 → 返回 `STATUS_TOO_LARGE`（-7）。
    #[test]
    fn fifty_k_fake_entries_hit_json_limit() {
        let entries: Vec<Entry> = (0..50_000u32).map(|i| fake_entry(i, "big_", true)).collect();
        let start = std::time::Instant::now();
        assert_eq!(
            entries_to_json(&entries),
            Err(STATUS_TOO_LARGE),
            "50k 膨胀条目必须命中 8MB 上限返回 -7"
        );
        let elapsed = start.elapsed();
        eprintln!("50k 虚假条目构造+序列化（命中上限）: {elapsed:?}");
    }

    // ── FFI 层（faf_scan_directory）──────────────────────────────────────

    #[test]
    fn faf_scan_directory_null_input_returns_null() {
        // SAFETY：守卫本身就是被测对象；null 输入必须返回 null 且不解引用。
        let raw = faf_scan_directory(std::ptr::null());
        assert!(raw.is_null());
    }

    #[test]
    fn faf_scan_directory_nonexistent_returns_null() {
        let cpath = CString::new(r"C:\faf_core_no_such_dir_xyz_0123").unwrap();
        // faf_scan_directory 为 safe extern "C"，无需 unsafe 块。
        let raw = faf_scan_directory(cpath.as_ptr());
        assert!(raw.is_null());
    }

    #[test]
    fn faf_scan_directory_returns_json_array() {
        let td = TestDir::new("ffi");
        td.file("hello.txt", "hi");
        let cpath = CString::new(td.path.to_str().expect("临时路径应为 UTF-8")).unwrap();
        // faf_scan_directory 为 safe extern "C"；返回指针先拷贝再释放。
        let raw = faf_scan_directory(cpath.as_ptr());
        assert!(!raw.is_null(), "正常目录应返回非空 JSON");
        let text = unsafe { CStr::from_ptr(raw) }.to_str().unwrap().to_string();
        faf_free_message(raw);
        let parsed: serde_json::Value = serde_json::from_str(&text).expect("应可解析为 JSON");
        assert!(parsed.is_array());
        let arr = parsed.as_array().unwrap();
        assert_eq!(arr.len(), 1);
        assert_eq!(arr[0]["name"], "hello.txt");
        assert_eq!(arr[0]["suffix"], "txt");
        assert!(!arr[0]["is_dir"].as_bool().unwrap());
        // null 释放为 no-op，不崩。
        faf_free_message(std::ptr::null_mut());
    }
}
