//! `sort.rs` —— 目录条目排序（todo 7）。
//!
//! 逐字节复刻 `freeassetfilter/ui/layout/file_selector_layout.py` 的
//! `_apply_sort`（L1363-1380）与 `SORT_MODE_NAMES`（L2523-2527）：
//!
//! | mode | 语义 | key | reverse |
//! |------|------|-----|---------|
//! | 0 | 名称↑ | `(not is_dir, name.lower())` | 否 |
//! | 1 | 名称↓ | 同 mode 0 | 是 |
//! | 2 | 修改时间↓ | `(not is_dir, modified)` | 是 |
//! | 3 | 修改时间↑ | 同 mode 2 | 否 |
//! | 4 | 大小↓ | `(not is_dir, size)` | 是 |
//! | 5 | 大小↑ | 同 mode 4 | 否 |
//! | 6 | 创建时间↓ | `(not is_dir, created)` | 是 |
//! | 7 | 创建时间↑ | 同 mode 6 | 否 |
//!
//! 关键语义（与 CPython `list.sort` 逐字节一致，含 bug 兼容）：
//! - **稳定**：一律 `slice::sort_by`（**禁止 `sort_unstable_*`**）；
//! - **reverse 元组整体反转**：`(not is_dir, 次键)` 的比较结果整体取反，
//!   即 reverse 模式同时翻转 dirs-first（文件在前）；
//! - **equal-key 保持原序**：CPython 的 `reverse=True` 是「稳定升序 + 反转
//!   比较器」（实测 3.11.9），而非「升序后整体倒序」——equal-key 相对序
//!   保持输入序。`Reverse` 包装 + 稳定 `sort_by` 精确复刻该语义。
//! - 名称 `to_lowercase()`（与 Python `str.lower()` 在 ASCII + 夹具语料上
//!   逐字节一致；非 ASCII 分歧见测试 `name_lowercase_matches_python`）。
//! - 时间/大小取原值：时间按字符串逐码点比较（UTF-8 字节序 = 码点序，
//!   与 Python 字符串比较一致）；大小按整数比较。

use std::cmp::Reverse;

use serde_json::Value;

use crate::STATUS_INVALID_ARG;

/// 排序次键（同一 mode 内所有条目共享同一变体，变体间比较不会发生）。
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
enum SortKey {
    /// mode 0/1：名称（已 `to_lowercase()`）。
    Name(String),
    /// mode 2/3：修改时间字符串原值。
    Modified(String),
    /// mode 4/5：大小整数原值。
    Size(i64),
    /// mode 6/7：创建时间字符串原值。
    Created(String),
}

/// 排序次键种类（由 mode 决定）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SortKind {
    Name,
    Modified,
    Size,
    Created,
}

/// 单条目录条目（JSON 值载体）。
///
/// 保留原始 `serde_json::Value`，排序后重序列化不丢字段、不改字段顺序，
/// 与「输入条目 JSON → 输出条目 JSON」的无损往返一致。
#[derive(Debug, Clone)]
pub struct Entry {
    value: Value,
}

impl Entry {
    /// 从解析后的 JSON 对象构造条目。
    pub(crate) fn from_value(value: Value) -> Self {
        Entry { value }
    }

    /// 原始 JSON 值（重序列化用）。
    pub(crate) fn as_value(&self) -> &Value {
        &self.value
    }

    /// `is_dir`；缺失按 `false`（Python 侧 `x["is_dir"]` 恒存在）。
    fn is_dir(&self) -> bool {
        self.value
            .get("is_dir")
            .and_then(Value::as_bool)
            .unwrap_or(false)
    }

    /// `name`；缺失按空串（Python 侧 `x["name"].lower()`）。
    fn name(&self) -> &str {
        self.value
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("")
    }

    /// 字符串字段（`modified`/`created`），对应 `x.get(field, "")`。
    fn str_field(&self, field: &str) -> &str {
        self.value
            .get(field)
            .and_then(Value::as_str)
            .unwrap_or("")
    }

    /// `size`，对应 `x.get("size", 0)`；JSON 整数优先 i64，u64 溢出截断
    /// （真实文件大小远小于 2^63，不产生排序差异）。
    fn size(&self) -> i64 {
        match self.value.get("size") {
            Some(v) => v.as_i64().unwrap_or_else(|| v.as_u64().unwrap_or(0) as i64),
            None => 0,
        }
    }
}

/// 提取排序键：`(not is_dir, 次键)`，与 Python 元组语义逐字节对齐。
fn sort_key(entry: &Entry, kind: SortKind) -> (bool, SortKey) {
    let second = match kind {
        SortKind::Name => SortKey::Name(entry.name().to_lowercase()),
        SortKind::Modified => SortKey::Modified(entry.str_field("modified").to_string()),
        SortKind::Size => SortKey::Size(entry.size()),
        SortKind::Created => SortKey::Created(entry.str_field("created").to_string()),
    };
    (!entry.is_dir(), second)
}

/// mode → (次键种类, 是否 reverse)。非法 mode → `Err(STATUS_INVALID_ARG)`。
fn mode_to_params(sort_mode: i32) -> Result<(SortKind, bool), i32> {
    let params = match sort_mode {
        0 => (SortKind::Name, false),
        1 => (SortKind::Name, true),
        2 => (SortKind::Modified, true),
        3 => (SortKind::Modified, false),
        4 => (SortKind::Size, true),
        5 => (SortKind::Size, false),
        6 => (SortKind::Created, true),
        7 => (SortKind::Created, false),
        _ => return Err(STATUS_INVALID_ARG),
    };
    Ok(params)
}

/// 就地排序条目列表（语义与 Python `_apply_sort` 逐字节一致）。
///
/// 非法 mode → `Err(STATUS_INVALID_ARG)`（列表保持原样）；否则 `Ok(())`。
///
/// 签名沿用计划规定的 `&mut Vec<Entry>`（非 `&mut [Entry]`），故显式压制
/// `ptr_arg`。
///
/// 稳定：`slice::sort_by`（禁 `sort_unstable_*`）。reverse 模式用
/// `Reverse` 包装比较器——等价 CPython `reverse=True` 的「稳定升序 + 反转
/// 比较器」，equal-key 相对序保持输入序，同时 `(not is_dir, …)` 整体反转
/// 令文件在前（dirs-first 翻转）。
#[allow(clippy::ptr_arg)] // 计划规定签名 `&mut Vec<Entry>`，见任务说明
pub fn sort_entries_impl(entries: &mut Vec<Entry>, sort_mode: i32) -> Result<(), i32> {
    let (kind, reverse) = mode_to_params(sort_mode)?;
    entries.sort_by(|a, b| {
        let ka = sort_key(a, kind);
        let kb = sort_key(b, kind);
        if reverse {
            Reverse(ka).cmp(&Reverse(kb))
        } else {
            ka.cmp(&kb)
        }
    });
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::{CStr, CString};

    /// 把 JSON 数组字符串解析为条目列表（测试夹具）。
    fn entries_from_json(json: &str) -> Vec<Entry> {
        let parsed: Value = serde_json::from_str(json).expect("sample JSON should parse");
        parsed
            .as_array()
            .expect("sample JSON should be an array")
            .iter()
            .map(|v| Entry::from_value(v.clone()))
            .collect()
    }

    /// 取条目 name 序列（断言对象）。
    fn names(entries: &[Entry]) -> Vec<String> {
        entries
            .iter()
            .map(|e| e.name().to_string())
            .collect()
    }

    /// 测试样本：混合目录/文件、大小写歧义（`alpha.txt`/`Alpha.txt`、
    /// `src`/`SRC`）、相同 mtime（`Zed.txt`/`zebra.txt`）、相同 size
    /// （`Zed.txt`/`zebra.txt` 100、`alpha.txt`/`Alpha.txt` 50）。
    const SAMPLE: &str = r#"[
        {"name":"Zed.txt","path":"x/Zed.txt","is_dir":false,"size":100,"modified":"2024-03-02 12:00","created":"2024-01-01 09:00","suffix":"txt"},
        {"name":"alpha.txt","path":"x/alpha.txt","is_dir":false,"size":50,"modified":"2024-01-01 08:00","created":"2024-02-01 10:00","suffix":"txt"},
        {"name":"Alpha.txt","path":"x/Alpha.txt","is_dir":false,"size":50,"modified":"2024-01-01 08:00","created":"2024-02-01 10:00","suffix":"txt"},
        {"name":"docs","path":"x/docs","is_dir":true,"size":0,"modified":"2024-02-15 11:30","created":"2024-01-15 08:00","suffix":""},
        {"name":"src","path":"x/src","is_dir":true,"size":0,"modified":"2024-01-20 09:00","created":"2024-01-20 09:00","suffix":""},
        {"name":"middle.txt","path":"x/middle.txt","is_dir":false,"size":75,"modified":"2024-02-10 14:00","created":"2024-03-10 14:00","suffix":"txt"},
        {"name":"aardvark.txt","path":"x/aardvark.txt","is_dir":false,"size":30,"modified":"2024-02-01 07:00","created":"2024-02-01 07:00","suffix":"txt"},
        {"name":"SRC","path":"x/SRC","is_dir":true,"size":0,"modified":"2024-01-20 09:00","created":"2024-01-20 09:00","suffix":""},
        {"name":"zebra.txt","path":"x/zebra.txt","is_dir":false,"size":100,"modified":"2024-03-02 12:00","created":"2024-03-20 12:00","suffix":"txt"},
        {"name":"Beta.txt","path":"x/Beta.txt","is_dir":false,"size":60,"modified":"2024-01-25 10:00","created":"2024-01-25 10:00","suffix":"txt"}
    ]"#;

    /// 8 种模式预期 name 序列 —— 由真实 Python `_apply_sort` 对同一样本
    /// 实测得出（2026-09-13，CPython 3.11.9），硬编码为回归基准。
    const EXPECTED_BY_MODE: [&[&str]; 8] = [
        // 0 名称↑：目录先（docs, src, SRC），文件按小写名升序
        //（alpha.txt 与 Alpha.txt 同键保持输入序）。
        &["docs", "src", "SRC", "aardvark.txt", "alpha.txt", "Alpha.txt", "Beta.txt", "middle.txt", "zebra.txt", "Zed.txt"],
        // 1 名称↓：文件先、目录后，键整体反转；同键保持输入序
        //（src/SRC、alpha.txt/Alpha.txt、Zed.txt/zebra.txt）。
        &["Zed.txt", "zebra.txt", "middle.txt", "Beta.txt", "alpha.txt", "Alpha.txt", "aardvark.txt", "src", "SRC", "docs"],
        // 2 修改时间↓：文件先（时间降序，Zed.txt/zebra.txt 同键保持输入序）。
        &["Zed.txt", "zebra.txt", "middle.txt", "aardvark.txt", "Beta.txt", "alpha.txt", "Alpha.txt", "docs", "src", "SRC"],
        // 3 修改时间↑：目录先（src/SRC 同键）。
        &["src", "SRC", "docs", "alpha.txt", "Alpha.txt", "Beta.txt", "aardvark.txt", "middle.txt", "Zed.txt", "zebra.txt"],
        // 4 大小↓：文件先（100: Zed.txt/zebra.txt 同键；50: alpha/Alpha 同键）。
        &["Zed.txt", "zebra.txt", "middle.txt", "Beta.txt", "alpha.txt", "Alpha.txt", "aardvark.txt", "docs", "src", "SRC"],
        // 5 大小↑：目录先（size 0 同键 docs/src/SRC 输入序）。
        &["docs", "src", "SRC", "aardvark.txt", "alpha.txt", "Alpha.txt", "Beta.txt", "middle.txt", "Zed.txt", "zebra.txt"],
        // 6 创建时间↓：文件先；alpha/Alpha 同键保持输入序。
        &["zebra.txt", "middle.txt", "alpha.txt", "Alpha.txt", "aardvark.txt", "Beta.txt", "Zed.txt", "src", "SRC", "docs"],
        // 7 创建时间↑：目录先（docs, src/SRC）。
        &["docs", "src", "SRC", "Zed.txt", "Beta.txt", "aardvark.txt", "alpha.txt", "Alpha.txt", "middle.txt", "zebra.txt"],
    ];

    /// 8 种模式全量对拍（ground truth 来自 Python oracle 实测）。
    #[test]
    fn all_eight_modes_match_python_oracle() {
        for mode in 0..8 {
            let mut entries = entries_from_json(SAMPLE);
            sort_entries_impl(&mut entries, mode).expect("valid mode should return Ok");
            assert_eq!(
                names(&entries),
                EXPECTED_BY_MODE[mode as usize].to_vec(),
                "mode {mode} 排序结果与 Python `_apply_sort` 不一致"
            );
        }
    }

    /// reverse 模式 equal-key 稳定序专项断言：CPython `reverse=True` 是
    /// 「稳定升序 + 反转比较器」，**不是**「升序后整体倒序」。
    #[test]
    fn reverse_modes_keep_equal_key_stability() {
        let json = r#"[
            {"name":"B.txt","path":"x/B.txt","is_dir":false,"size":1,"modified":"2024-01-01 00:00","created":"2024-01-01 00:00","suffix":"txt"},
            {"name":"b.txt","path":"x/b.txt","is_dir":false,"size":1,"modified":"2024-01-01 00:00","created":"2024-01-01 00:00","suffix":"txt"},
            {"name":"a.txt","path":"x/a.txt","is_dir":false,"size":1,"modified":"2024-01-01 00:00","created":"2024-01-01 00:00","suffix":"txt"},
            {"name":"D1","path":"x/D1","is_dir":true,"size":0,"modified":"2024-02-02 00:00","created":"2024-02-02 00:00","suffix":""},
            {"name":"d1","path":"x/d1","is_dir":true,"size":0,"modified":"2024-02-02 00:00","created":"2024-02-02 00:00","suffix":""}
        ]"#;
        // mode 1 名称↓：文件先；B.txt/b.txt 同键（"b.txt"）保持输入序
        //（若按「升序+整体倒序」会得到 [b.txt, B.txt]——本断言区分该语义）。
        let mut entries = entries_from_json(json);
        sort_entries_impl(&mut entries, 1).unwrap();
        assert_eq!(
            names(&entries),
            vec!["B.txt", "b.txt", "a.txt", "D1", "d1"],
            "mode 1 equal-key 相对序必须保持输入序（Python reverse 语义）"
        );
        // mode 2 修改时间↓：全部文件 mtime 相同 → 同键保持输入序；
        // 目录 mtime 相同 → 保持输入序（D1, d1）。
        let mut entries = entries_from_json(json);
        sort_entries_impl(&mut entries, 2).unwrap();
        assert_eq!(
            names(&entries),
            vec!["B.txt", "b.txt", "a.txt", "D1", "d1"],
            "mode 2 equal-key 相对序必须保持输入序"
        );
        // mode 4 大小↓：全部文件 size 相同 → 输入序保持。
        let mut entries = entries_from_json(json);
        sort_entries_impl(&mut entries, 4).unwrap();
        assert_eq!(
            names(&entries),
            vec!["B.txt", "b.txt", "a.txt", "D1", "d1"],
            "mode 4 equal-key 相对序必须保持输入序"
        );
    }

    /// 非法 mode → `Err(STATUS_INVALID_ARG)`，且列表保持原样。
    #[test]
    fn invalid_modes_return_invalid_arg() {
        let mut entries = entries_from_json(SAMPLE);
        let original = names(&entries);
        for mode in [-99i32, -1, 8, 9, 100, i32::MAX] {
            assert_eq!(
                sort_entries_impl(&mut entries, mode),
                Err(STATUS_INVALID_ARG),
                "mode {mode} 应返回 Err(STATUS_INVALID_ARG)"
            );
            assert_eq!(names(&entries), original, "非法 mode 不得改动列表");
        }
    }

    /// 名称 `to_lowercase()` 与 Python `str.lower()` 在非 ASCII 特殊字符上
    /// 的逐码点一致性（Python 3.11.9 实测基准；任一不一致即列出码点）。
    #[test]
    fn name_lowercase_matches_python() {
        let cases: [(&str, &str); 6] = [
            // 'İ' U+0130 → 'i' U+0069 + U+0307 COMBINING DOT ABOVE
            ("\u{0130}", "\u{0069}\u{0307}"),
            // 'ß' U+00DF → 自身
            ("\u{00df}", "\u{00df}"),
            // 'Σ' U+03A3 → 'σ' U+03C3
            ("\u{03a3}", "\u{03c3}"),
            // 'ẞ' U+1E9E → 'ß' U+00DF
            ("\u{1e9e}", "\u{00df}"),
            // 'K' (KELVIN SIGN) U+212A → 'k' U+006B
            ("\u{212a}", "\u{006b}"),
            // 'ſ' U+017F → 自身
            ("\u{017f}", "\u{017f}"),
        ];
        for (input, expected) in cases {
            assert_eq!(
                input.to_lowercase(),
                expected,
                "to_lowercase(U+{}) 与 Python str.lower() 不一致，码点 {}",
                input.chars().next().map(|c| format!("{:04X}", c as u32)).unwrap_or_default(),
                expected
                    .chars()
                    .map(|c| format!("U+{:04X}", c as u32))
                    .collect::<Vec<_>>()
                    .join(" ")
            );
        }
    }

    /// 缺失字段容错：无 `name`/`modified`/`size`/`created`/`is_dir` 的
    /// 条目按 Python `x.get(..., 默认)` 语义参与排序，不 panic。
    #[test]
    fn missing_fields_fall_back_to_defaults() {
        let json = r#"[
            {"path":"x/one.txt"},
            {"name":"AAA","path":"x/AAA.txt","is_dir":false,"size":5,"modified":"2024-06-01 00:00","created":"2024-06-01 00:00","suffix":"txt"},
            {"name":"aaa.txt","path":"x/aaa.txt","is_dir":false,"size":5,"modified":"2024-06-01 00:00","created":"2024-06-01 00:00","suffix":"txt"}
        ]"#;
        let mut entries = entries_from_json(json);
        sort_entries_impl(&mut entries, 0).unwrap();
        // 缺 name → ""；"AAA" 小写 "aaa"，"aaa.txt" 小写 "aaa.txt"；
        // 升序："" < "aaa" < "aaa.txt"。
        assert_eq!(names(&entries), vec!["", "AAA", "aaa.txt"]);
    }

    /// `faf_sort_entries` FFI 往返：合法输入 → 非空指针 → 排序后 JSON 数组。
    #[test]
    fn ffi_sort_entries_roundtrip() {
        let json = CString::new(SAMPLE).unwrap();
        let raw = crate::faf_sort_entries(json.as_ptr(), 0);
        assert!(!raw.is_null(), "合法输入应返回非空指针");
        // SAFETY：raw 为 faf_sort_entries 刚分配的 NUL 终止串。
        let back = unsafe { CStr::from_ptr(raw) }
            .to_str()
            .expect("输出应为合法 UTF-8");
        let parsed: Value = serde_json::from_str(back).expect("输出应可解析为 JSON");
        let got: Vec<String> = parsed
            .as_array()
            .expect("输出应为 JSON 数组")
            .iter()
            .map(|v| v.get("name").and_then(Value::as_str).unwrap_or("").to_string())
            .collect();
        assert_eq!(got, EXPECTED_BY_MODE[0].to_vec());
        // 对称释放。
        crate::faf_free_message(raw);
    }

    /// `faf_sort_entries` FFI 错误路径：null 指针 / 坏 JSON / 非数组 /
    /// 非法 mode → 一律返回 null，不 panic。
    #[test]
    fn ffi_sort_entries_errors_return_null() {
        // null 指针。
        assert!(crate::faf_sort_entries(std::ptr::null(), 0).is_null());
        // 坏 JSON。
        let bad = CString::new("definitely not json").unwrap();
        assert!(crate::faf_sort_entries(bad.as_ptr(), 0).is_null());
        // 合法 JSON 但非数组。
        let obj = CString::new(r#"{"a":1}"#).unwrap();
        assert!(crate::faf_sort_entries(obj.as_ptr(), 0).is_null());
        // 非法 mode（合法 JSON 数组）。
        let json = CString::new(SAMPLE).unwrap();
        assert!(crate::faf_sort_entries(json.as_ptr(), 8).is_null());
        assert!(crate::faf_sort_entries(json.as_ptr(), -1).is_null());
        assert!(crate::faf_sort_entries(json.as_ptr(), 99).is_null());
    }

    // ── 边界测试（todo 8：1k 条目 8 模式性能回归 + 超长文件名）────────────

    /// 生成 1k 条混合目录/文件、大小写/时间/大小全异的条目（性能回归夹具）。
    fn make_1k_entries() -> Vec<Entry> {
        (0..1000u32)
            .map(|i| {
                let is_dir = i.is_multiple_of(7);
                let base = if is_dir {
                    format!("dir_{i:05}")
                } else {
                    format!("file_{i:05}.txt")
                };
                // 每 3 个取大写：制造大小写歧义键（to_lowercase 后部分重合）。
                let name = if i.is_multiple_of(3) {
                    base.to_uppercase()
                } else {
                    base
                };
                Entry::from_value(serde_json::json!({
                    "name": name,
                    "path": format!("x/{name}"),
                    "is_dir": is_dir,
                    "size": (i as i64 * 2_654_435_761) % 10_000_000,
                    "modified": format!("2024-{:02}-{:02} {:02}:{:02}", 1 + (i % 12), 1 + (i % 28), i % 24, i % 60),
                    "created": format!("2023-{:02}-{:02} 00:00", 1 + (i % 12), 1 + (i % 28)),
                    "suffix": if is_dir { "" } else { "txt" },
                }))
            })
            .collect()
    }

    /// 1k 条目 × 8 模式排序性能回归：单模式 <100ms（宽松阈值防 flaky），耗时打印。
    /// 附 dirs-first 语义抽查，确保性能测试非空转。
    #[test]
    fn sort_1k_entries_eight_modes_under_100ms() {
        let base = make_1k_entries();
        let mut worst = std::time::Duration::default();
        let mut total = std::time::Duration::default();
        for mode in 0..8 {
            let mut entries = base.clone();
            let start = std::time::Instant::now();
            sort_entries_impl(&mut entries, mode).expect("合法 mode 应返回 Ok");
            let elapsed = start.elapsed();
            total += elapsed;
            worst = worst.max(elapsed);
            assert_eq!(entries.len(), 1000, "排序不得增删条目");
            // reverse 模式（1/2/4/6）翻转 dirs-first → 文件在前；非 reverse → 目录在前。
            let reverse = matches!(mode, 1 | 2 | 4 | 6);
            assert_eq!(
                entries[0].is_dir(),
                !reverse,
                "mode {mode} 首条应为 {}",
                if reverse { "文件" } else { "目录" }
            );
            assert!(
                elapsed.as_millis() < 100,
                "mode {mode} 1k 排序耗时 {elapsed:?} 超过 100ms 预算"
            );
        }
        eprintln!("sort 1k x 8 modes: total = {total:?}, worst single-mode = {worst:?}");
    }

    /// 240 字符文件名（Windows 255 限制内）：大小写歧义 equal-key 稳定排序，不 panic。
    #[test]
    fn long_name_sorting_stable_and_within_budget() {
        let long_lower = format!("{}.txt", "a".repeat(236));
        let long_upper = format!("{}.TXT", "A".repeat(236));
        assert_eq!(long_lower.chars().count(), 240);
        assert_eq!(long_upper.chars().count(), 240);
        let json = format!(
            r#"[
                {{"name":"{long_upper}","path":"x/longU","is_dir":false,"size":1,"modified":"2024-01-01 00:00","created":"2024-01-01 00:00","suffix":"txt"}},
                {{"name":"b.txt","path":"x/b","is_dir":false,"size":1,"modified":"2024-01-01 00:00","created":"2024-01-01 00:00","suffix":"txt"}},
                {{"name":"{long_lower}","path":"x/longL","is_dir":false,"size":1,"modified":"2024-01-01 00:00","created":"2024-01-01 00:00","suffix":"txt"}}
            ]"#
        );
        let mut entries = entries_from_json(&json);
        let start = std::time::Instant::now();
        sort_entries_impl(&mut entries, 0).unwrap();
        let elapsed = start.elapsed();
        eprintln!("240 字符文件名排序: {elapsed:?}");
        assert!(elapsed.as_millis() < 100, "240 字符名排序耗时 {elapsed:?} 超过 100ms 预算");
        // mode 0（名称↑）：两 long name 小写键相等（a×236.txt）→ 稳定的输入序
        // （long_upper 在前）；且 "a"×236+".txt" < "b.txt"。
        assert_eq!(names(&entries), vec![long_upper, long_lower, "b.txt".to_string()]);
    }
}
