//! `archive.rs` —— 7z `-slt` 输出解析（todo 16：`faf_parse_7z_list`）。
//!
//! 语义 oracle：`freeassetfilter/core/native/bridges/py7z_core.py`
//! `_parse_list_output`（L333-439）与 `_parse_file_block`（L441-494）——逐语义
//! 复刻：`re.split(r'\n(?=Path = )', output, maxsplit=MAX_ARCHIVE_FILES)`
//!（L352，正向前瞻手工分块）、`Path = ` 块解析、目录集合、`os.path.basename`、
//! 隐藏项（`.` 前缀）排除、压缩包自身排除、`MAX_ARCHIVE_FILES=10000`（L41）
//! 截断、suffix 小写去点、modified ISO 串（`datetime.isoformat()` 的 `T`
//! 分隔符）。
//!
//! **不做文件 I/O、不调用 7z.exe**——`7z.exe` 子进程与命令执行/编码检测完全
//! 保留在 Python（`py7z_core._run_7z_command`/`_detect_encoding_from_output`/
//! `list_archive`）。todo 1 spike 裁决 KEEP：`regex` 不支持 lookahead，
//! `re.split` 的零宽断言 `\n(?=Path = )` 手工分块移植（见 [`split_blocks`]）。
//!
//! # 与 oracle 的对应实现要点（对拍校准）
//!
//! 1. **分块（`re.split`）**：分隔符为紧跟 `"Path = "` 行头的一个 `\n`
//!   （被消费、不进任一块），零宽 lookahead 仅作约束；`maxsplit` 语义 = 只
//!   发生前 `MAX_ARCHIVE_FILES` 次切分，剩余文本整体作为最后一块（行为与
//!   Python `re.split` 一致，见 [`split_blocks_with_max`] 的可测小参数）。
//! 2. **块解析（`_parse_file_block`）**：`re.search(..., re.MULTILINE)` 的
//!   「首个匹配」语义——各字段只在首次命中时取值（命中后不再被后续行覆盖）；
//!   `[^\n]+` 要求值非空（空值行不命中、继续向下找），值非空即定 path（纯
//!   空白值经 `strip()` 可为空，随后被 `_parse_list_output` 的空 path 过滤
//!   丢弃）；`Size = (\d+)` 要求整行数字否则 0；`Modified` 先按
//!   `strptime("%Y-%m-%d %H:%M:%S")` 解析、失败回 ""（成功输出
//!   `isoformat()` 的 `T` 分隔符串）；`Attributes` 含 `D` 判目录、缺省回退
//!   path 尾部 `/`；CRC 提取不进入最终条目（oracle 仅存入 `info_dict["crc"]`，
//!   输出条目不含）。
//! 3. **过滤与条目构建（`_parse_list_output`）**：自身排除（path ==
//!   `archive_path` 或 == `os.path.basename(archive_path)`）、隐藏排除
//!   （basename 首字符 `.`）、`current_path` 前缀过滤（`replace('/', '\\')`
//!   后要求 `prefix + '\\'` 前缀、再去前缀取 rel_path）；含分隔符路径 →
//!   **合成目录**条目（取 rel 首段、`dirs` 去重、path =
//!   `f"{current_path}/{sub_dir}"`）；无分隔符 → 真目录（`is_dir`）/文件条目；
//!   文件 suffix 用 `os.path.splitext` 语义（最后分隔符之后的最后一个 `.`
//!   起为扩展名、忽略基名前导点，小写去点）。
//! 4. **收尾**：按 name 去重（后见者胜）、`(not is_dir, name.lower())` 稳定
//!   排序（目录先行）。
//!
//! ⚠️ 任务书与桥 docstring 所记「7 键」为笔误：oracle 最终条目精确为 **6 键**
//! （`name/path/is_dir/size/modified/suffix`；`_parse_file_block` 内部提取的
//! `crc` 不进输出条目），以 oracle 源码为准。

use std::collections::{HashMap, HashSet};

use chrono::NaiveDateTime;
use serde_json::{json, Value};

/// `py7z_core.MAX_ARCHIVE_FILES = 10000`（L41）：分块 `maxsplit` 与条目截断上限。
const MAX_ARCHIVE_FILES: usize = 10000;

/// 解析 7z `-slt` 列表输出为 JSON 数组（todo 16 填实现）。
///
/// 语义对齐 `py7z_core._parse_list_output`/`_parse_file_block`：条目 JSON
/// 数组（6 键：`name/path/is_dir/size/modified/suffix`）。畸形/空输出返回
/// 空数组（`Ok`），**不 panic、不做文件 I/O、不调用 7z.exe**。
///
/// `Err` 分支在正常路径不产生（oracle 无失败路径）；保留 `Result` 形态以
/// 契合 FFI 导出契约。
pub fn parse_7z_list_impl(
    output: &str,
    current_path: &str,
    archive_path: &str,
) -> Result<Value, i32> {
    // `os.path.basename(archive_path)`：Windows 按 `/` 与 `\` 同时切分取末段。
    let archive_name = basename(archive_path);

    // `current_path.replace('/', '\\')`（空串保持空）。
    let current_path_normalized = current_path.replace('/', "\\");
    let current_path_prefix = if current_path_normalized.is_empty() {
        String::new()
    } else {
        format!("{current_path_normalized}\\")
    };

    let mut files: Vec<Entry> = Vec::new();
    let mut dirs: HashSet<String> = HashSet::new();

    for block in split_blocks(output) {
        let block = py_strip(block);
        if block.is_empty() || !block.starts_with("Path = ") {
            continue;
        }
        if files.len() >= MAX_ARCHIVE_FILES {
            break;
        }

        let Some(file_info) = parse_file_block(block) else {
            continue;
        };
        let file_path = file_info.path;
        if file_path.is_empty() {
            continue;
        }
        // 压缩包自身排除（archive_path 或 os.path.basename(archive_path)）。
        if file_path == archive_path || file_path == archive_name {
            continue;
        }
        // `os.path.basename(file_path.rstrip('\\/'))`。
        let base = basename(file_path.trim_end_matches(['\\', '/']));
        if base.starts_with('.') {
            continue;
        }

        let rel_path: String = if current_path_prefix.is_empty() {
            file_path.clone()
        } else if file_path.starts_with(&current_path_prefix) {
            file_path[current_path_prefix.len()..].to_string()
        } else {
            continue;
        };
        if rel_path.is_empty() {
            continue;
        }

        let rel_path_normalized = rel_path.replace('\\', "/");
        let file_path_normalized = file_path.replace('\\', "/");

        if rel_path.contains('\\') || rel_path.contains('/') {
            // 含分隔符路径 → 合成目录条目（取 rel 首段，`dirs` 去重）。
            let sub_dir = rel_path_normalized.split('/').next().unwrap_or_default();
            if !sub_dir.is_empty() && !dirs.contains(sub_dir) {
                dirs.insert(sub_dir.to_string());
                files.push(Entry {
                    name: sub_dir.to_string(),
                    path: if current_path.is_empty() {
                        sub_dir.to_string()
                    } else {
                        format!("{current_path}/{sub_dir}")
                    },
                    is_dir: true,
                    size: 0,
                    modified: String::new(),
                    suffix: String::new(),
                });
            }
        } else if file_info.is_dir {
            // 无分隔符的真目录条目。
            dirs.insert(rel_path_normalized.clone());
            files.push(Entry {
                name: rel_path_normalized.clone(),
                path: file_path_normalized,
                is_dir: true,
                size: 0,
                modified: String::new(),
                suffix: String::new(),
            });
        } else {
            // 无分隔符的文件条目。
            files.push(Entry {
                name: rel_path_normalized.clone(),
                path: file_path_normalized,
                is_dir: false,
                size: file_info.size,
                modified: file_info.modified,
                suffix: splitext_suffix(&rel_path_normalized),
            });
        }
    }

    // 按 name 去重（后见者胜）。
    let mut unique: HashMap<String, Entry> = HashMap::new();
    for entry in files {
        unique.insert(entry.name.clone(), entry);
    }

    // `sorted(unique.values(), key=lambda x: (not x["is_dir"], x["name"].lower()))`
    //（稳定排序，目录先行）。
    let mut results: Vec<Entry> = unique.into_values().collect();
    results.sort_by(|a, b| {
        let a_key = (!a.is_dir, a.name.to_lowercase());
        let b_key = (!b.is_dir, b.name.to_lowercase());
        a_key.cmp(&b_key)
    });

    Ok(Value::Array(results.into_iter().map(entry_to_value).collect()))
}

/// 单条输出条目（与 oracle 6 键精确对齐）。
#[derive(Debug, Clone)]
struct Entry {
    name: String,
    path: String,
    is_dir: bool,
    size: i64,
    modified: String,
    suffix: String,
}

fn entry_to_value(e: Entry) -> Value {
    json!({
        "name": e.name,
        "path": e.path,
        "is_dir": e.is_dir,
        "size": e.size,
        "modified": e.modified,
        "suffix": e.suffix,
    })
}

/// `re.split(r'\n(?=Path = )', output, maxsplit=MAX_ARCHIVE_FILES)` 手工移植。
///
/// 分隔符为紧跟 `"Path = "` 行头的一个 `\n`（被消费、不进任一块）；只发生前
/// `MAX_ARCHIVE_FILES` 次切分，剩余文本整体作为最后一块。
fn split_blocks(output: &str) -> Vec<&str> {
    split_blocks_with_max(output, MAX_ARCHIVE_FILES)
}

/// [`split_blocks`] 的可测泛型版：`max_split` 为 `re.split` 的 `maxsplit`。
fn split_blocks_with_max(output: &str, max_split: usize) -> Vec<&str> {
    let mut blocks = Vec::new();
    let bytes = output.as_bytes();
    let mut start = 0usize;
    let mut split_count = 0usize;
    let mut i = 0usize;
    while i < bytes.len() && split_count < max_split {
        if bytes[i] == b'\n' && output[i + 1..].starts_with("Path = ") {
            blocks.push(&output[start..i]);
            start = i + 1;
            split_count += 1;
        }
        i += 1;
    }
    blocks.push(&output[start..]);
    blocks
}

/// `py7z_core._parse_file_block` 语义（L441-494）：解析单个文件信息块。
///
/// 返回 `None` 当且仅当块内无「非空值的 `Path = ` 行」（oracle 的
/// `^Path = ([^\n]+)$` 不命中）。各字段按 `re.search` 的**首个命中**取值。
#[derive(Debug)]
struct FileBlock {
    path: String,
    size: i64,
    modified: String,
    is_dir: bool,
}

fn parse_file_block(block: &str) -> Option<FileBlock> {
    let mut path: Option<String> = None;
    let mut size: Option<i64> = None;
    let mut modified_seen = false;
    let mut modified = String::new();
    let mut attr_seen = false;
    let mut is_dir = false;

    for line in block.lines() {
        if let Some(rest) = line.strip_prefix("Path = ") {
            if path.is_none() && !rest.is_empty() {
                path = Some(py_strip(rest).to_string());
            }
        } else if let Some(rest) = line.strip_prefix("Size = ") {
            if size.is_none() {
                if let Ok(n) = rest.parse::<i64>() {
                    size = Some(n);
                }
            }
        } else if let Some(rest) = line.strip_prefix("Modified = ") {
            if !modified_seen && !rest.is_empty() {
                modified_seen = true;
                modified = iso_modified(py_strip(rest));
            }
        } else if let Some(rest) = line.strip_prefix("Attributes = ") {
            if !attr_seen && !rest.is_empty() {
                attr_seen = true;
                is_dir = py_strip(rest).contains('D');
            }
        }
    }

    let path = path?;
    if !attr_seen {
        is_dir = path.ends_with('/');
    }
    Some(FileBlock {
        path,
        size: size.unwrap_or_default(),
        modified,
        is_dir,
    })
}

/// `datetime.strptime(s, "%Y-%m-%d %H:%M:%S").isoformat()` 复刻：
/// 解析失败（含空串/乱码/多余内容）返回空串。
fn iso_modified(s: &str) -> String {
    match NaiveDateTime::parse_from_str(s, "%Y-%m-%d %H:%M:%S") {
        Ok(dt) => dt.format("%Y-%m-%dT%H:%M:%S").to_string(),
        Err(_) => String::new(),
    }
}

/// `os.path.splitext(p)[1].lower()[1:]`（仅当 `'.' in p` 时计算）语义复刻。
///
/// 扩展名 = 最后分隔符之后最后一个 `.` 起至末尾；基名前导点（如
/// `".hidden"`）、分隔符之后无点（如 `"dir.with.dot/file"`）均视为无扩展名。
fn splitext_suffix(path: &str) -> String {
    if !path.contains('.') {
        return String::new();
    }
    // `ntpath.splitext`：`sepIndex` = 最后分隔符位置（未命中为 -1）。
    let sep_index = path.rfind('/').map_or(-1isize, |i| i as isize);
    let dot_index = path.rfind('.').map_or(-1isize, |i| i as isize);
    if dot_index <= sep_index {
        return String::new();
    }
    // 跳过 sepIndex 之后的前导分隔符（"///a.b" → 无扩展名）。
    let bytes = path.as_bytes();
    let mut filename_index = sep_index + 1;
    while (filename_index as usize) < dot_index as usize {
        if bytes[filename_index as usize] != b'/' {
            break;
        }
        filename_index += 1;
    }
    if (filename_index as usize) >= dot_index as usize {
        return String::new();
    }
    path[(dot_index as usize)..].to_lowercase()[1..].to_string()
}

/// `os.path.basename`（Windows：按 `/` 与 `\` 同时切分取末段）。
fn basename(path: &str) -> &str {
    path.rsplit(['/', '\\']).next().unwrap_or(path)
}

/// Python `str.strip()` 的 ASCII 空白语义（` \t\n\r\x0b\x0c`）逐字节裁剪。
/// 空白字符全在 ASCII 区，裁剪边界必然落在字符边界上（UTF-8 安全）。
fn py_strip(s: &str) -> &str {
    let bytes = s.as_bytes();
    let mut start = 0usize;
    let mut end = bytes.len();
    while start < end && is_py_space(bytes[start]) {
        start += 1;
    }
    while end > start && is_py_space(bytes[end - 1]) {
        end -= 1;
    }
    &s[start..end]
}

fn is_py_space(b: u8) -> bool {
    matches!(b, b' ' | b'\t' | b'\n' | b'\r' | 0x0b | 0x0c)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// todo 5 的 utf8 夹具全文（`tests/support/faf_core_fixtures/seven_zip_samples/`
    /// `slt_output_utf8.txt`），用于 cargo 内对拍等价断言。
    const SLT_UTF8: &str = r#"Path = sample_archive.7z
Size = 0
Type = 7z
Physical Size = 4096
Headers Size = 172
Method = LZMA2:24
Solid = +
Blocks = 1

----------
Path = docs\
Folder = +
Size = 0
Packs = 0
Attributes = D_....A
Encrypted = -
Method = 
Block = 0

----------
Path = docs\readme_中文.txt
Size = 256
Packs = 256
Attributes = ...._A
Encrypted = -
Method = LZMA2:24
Block = 0
CRC = 12345678
Modified = 2026-09-05 10:30:00

----------
Path = docs\说明文档.txt
Size = 512
Packs = 512
Attributes = ...._A
Encrypted = -
Method = LZMA2:24
Block = 0
CRC = 9ABCDEF0
Modified = 2026-09-05 10:35:00

----------
Path = docs\.hidden_config
Size = 64
Packs = 64
Attributes = ...._A
Encrypted = -
Method = LZMA2:24
Block = 0
CRC = 11111111
Modified = 2026-09-05 10:40:00

----------
Path = docs\sub\
Folder = +
Size = 0
Packs = 0
Attributes = D_....A
Encrypted = -
Method = 
Block = 0

----------
Path = docs\sub\data.csv
Size = 128
Packs = 128
Attributes = ...._A
Encrypted = -
Method = LZMA2:24
Block = 0
CRC = 22222222
Modified = 2026-09-05 10:45:00

----------
Path = src\
Folder = +
Size = 0
Packs = 0
Attributes = D_....A
Encrypted = -
Method = 
Block = 0

----------
Path = src\main.py
Size = 1024
Packs = 1024
Attributes = ...._A
Encrypted = -
Method = LZMA2:24
Block = 0
CRC = 33333333
Modified = 2026-09-05 10:50:00

----------
Path = license.txt
Size = 2048
Packs = 2048
Attributes = ...._A
Encrypted = -
Method = LZMA2:24
Block = 0
CRC = AABBCCDD
Modified = 2026-09-05 11:00:00

----------
Path = sample_archive.7z
Size = 4096
Packs = 4096
Attributes = ...._A
Encrypted = -
Method = LZMA2:24
Block = 0
CRC = 44444444
Modified = 2026-09-05 09:00:00"#;

    fn names(result: &Value) -> Vec<String> {
        result
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v["name"].as_str().unwrap().to_string())
            .collect()
    }

    /// happy：utf8 夹具（中文/目录/隐藏/自身/子目录）逐字段对齐 Python oracle
    /// 手工推演结果。
    ///
    /// ⚠️ oracle 关键怪癖（已实测校准）：**含分隔符的 rel_path 只产生「合成
    /// 目录」条目，文件本身不进结果**（`_parse_list_output` L398-409 无 else
    /// 分支）——子目录内文件在进入该子目录（current_path 过滤）后才出现。
    /// 故根层（current_path=""）仅 3 条：docs、src、license.txt。
    #[test]
    fn parses_utf8_sample_like_oracle() {
        let result =
            parse_7z_list_impl(SLT_UTF8, "", "C:/x/sample_archive.7z").unwrap();
        let arr = result.as_array().unwrap();
        assert_eq!(arr.len(), 3);

        let expected: [(bool, &str, &str, i64, &str, &str); 3] = [
            (true, "docs", "docs", 0, "", ""),
            (true, "src", "src", 0, "", ""),
            (false, "license.txt", "license.txt", 2048, "2026-09-05T11:00:00", "txt"),
        ];
        for (i, (is_dir, name, path, size, modified, suffix)) in expected.iter().enumerate() {
            let v = &arr[i];
            assert_eq!(v["is_dir"].as_bool().unwrap(), *is_dir, "item {i} is_dir");
            assert_eq!(v["name"].as_str().unwrap(), *name, "item {i} name");
            assert_eq!(v["path"].as_str().unwrap(), *path, "item {i} path");
            assert_eq!(v["size"].as_i64().unwrap(), *size, "item {i} size");
            assert_eq!(v["modified"].as_str().unwrap(), *modified, "item {i} modified");
            assert_eq!(v["suffix"].as_str().unwrap(), *suffix, "item {i} suffix");
        }
    }

    /// happy：`current_path` 前缀过滤 + 合成目录 path 拼接（`f"{current_path}/{sub}"`）。
    ///（进入 docs 子目录后，中文/CSV 文件才作为无分隔符条目出现。）
    #[test]
    fn filters_by_current_path_and_builds_prefixed_dirs() {
        let result = parse_7z_list_impl(SLT_UTF8, "docs", "C:/x/sample_archive.7z").unwrap();
        assert_eq!(
            names(&result),
            vec![
                "sub".to_string(),
                "readme_中文.txt".to_string(),
                "说明文档.txt".to_string(),
            ]
        );
        let dir = result.as_array().unwrap()[0].clone();
        assert_eq!(dir["path"].as_str().unwrap(), "docs/sub");
        assert!(dir["is_dir"].as_bool().unwrap());
        // docs\readme_中文.txt 与 docs\说明文档.txt 的字段（oracle 中文路径对拍）。
        // name = rel_path（去 current_path 前缀）；path = 全路径（保留前缀）。
        let file = &result.as_array().unwrap()[1];
        assert_eq!(file["name"].as_str().unwrap(), "readme_中文.txt");
        assert_eq!(file["path"].as_str().unwrap(), "docs/readme_中文.txt");
        assert_eq!(file["size"].as_i64().unwrap(), 256);
        assert_eq!(file["modified"].as_str().unwrap(), "2026-09-05T10:30:00");
        assert_eq!(file["suffix"].as_str().unwrap(), "txt");
    }

    /// failure：空输出 / 纯空白 / 无 Path 行的畸形输出 → 空数组，不 panic。
    #[test]
    fn malformed_or_empty_outputs_yield_empty_list() {
        assert_eq!(parse_7z_list_impl("", "", "x.7z").unwrap(), json!([]));
        assert_eq!(parse_7z_list_impl("   \n\t\n", "", "x.7z").unwrap(), json!([]));
        assert_eq!(
            parse_7z_list_impl("no path lines here\nSize = 3\n", "", "x.7z").unwrap(),
            json!([])
        );
        // 仅"Path = "空值行 → _parse_file_block 无 path → 跳过。
        assert_eq!(parse_7z_list_impl("Path = \nSize = 1", "", "x.7z").unwrap(), json!([]));
    }

    /// failure：畸形块（含非法 Size/Modified/空 Attributes）不 panic，字段回落。
    ///（rel_path 含分隔符 → 仅合成目录条目；Size/Modified 非法 → 默认回落。）
    #[test]
    fn malformed_block_fields_fall_back() {
        let out = "Path = bad\\file.txt\n\
                   Size = not_a_number\n\
                   Modified = garbage\n\
                   Attributes = X_....A\n";
        let result = parse_7z_list_impl(out, "", "x.7z").unwrap();
        let arr = result.as_array().unwrap();
        assert_eq!(arr.len(), 1);
        let v = &arr[0];
        assert_eq!(v["name"].as_str().unwrap(), "bad");
        assert_eq!(v["path"].as_str().unwrap(), "bad");
        assert!(v["is_dir"].as_bool().unwrap());
        assert_eq!(v["size"].as_i64().unwrap(), 0);
        assert_eq!(v["modified"].as_str().unwrap(), "");
        assert_eq!(v["suffix"].as_str().unwrap(), "");
    }

    /// 隐藏项（`.` 前缀 basename）排除。
    #[test]
    fn hidden_entries_skipped() {
        let out = "Path = docs\\.hidden_config\nSize = 64\n\n\
                   Path = .dotfile_at_root\nSize = 1\n\n\
                   Path = docs\\visible.txt\nSize = 2\n";
        let result = parse_7z_list_impl(out, "", "x.7z").unwrap();
        assert_eq!(names(&result), vec!["docs".to_string()]);
    }

    /// 压缩包自身排除（archive_name 与 archive_path 两种形态）。
    #[test]
    fn archive_self_entries_skipped() {
        let out = "Path = x.7z\nSize = 1\n\n\
                   Path = C:/arc/y.7z\nSize = 2\n\n\
                   Path = real.txt\nSize = 3\n";
        // archive_name = x.7z → 首个跳过；"C:/arc/y.7z" 含分隔符 → 合成目录 "C:"。
        let result = parse_7z_list_impl(out, "", "C:/x.7z").unwrap();
        assert_eq!(names(&result), vec!["C:".to_string(), "real.txt".to_string()]);
        // archive_path 精确匹配也跳过。
        let result2 = parse_7z_list_impl(out, "", "C:/arc/y.7z").unwrap();
        assert_eq!(names(&result2), vec!["real.txt".to_string(), "x.7z".to_string()]);
    }

    /// suffix：无点文件 / 点号在目录名 / 基名前导点 / 多段点 / 大写扩展名。
    #[test]
    fn suffix_matches_splitext_semantics() {
        let out = "Path = noext\nPath = dir.with.dot\\file\nPath = .hidden\n\
                   Path = b.TXT\nPath = c.d.e\n";
        let result = parse_7z_list_impl(out, "", "x.7z").unwrap();
        let arr = result.as_array().unwrap();
        // 目录先行；文件按 name.lower()：b.TXT < c.d.e < noext。
        assert_eq!(arr.len(), 4); // "dir.with.dot\\file" 仅贡献合成目录 "dir.with.dot"
        assert_eq!(arr[0]["name"].as_str().unwrap(), "dir.with.dot");
        assert_eq!(arr[0]["suffix"].as_str().unwrap(), "");
        assert_eq!(arr[1]["name"].as_str().unwrap(), "b.TXT");
        assert_eq!(arr[1]["suffix"].as_str().unwrap(), "txt");
        assert_eq!(arr[2]["name"].as_str().unwrap(), "c.d.e");
        assert_eq!(arr[2]["suffix"].as_str().unwrap(), "e");
        assert_eq!(arr[3]["name"].as_str().unwrap(), "noext");
        assert_eq!(arr[3]["suffix"].as_str().unwrap(), ""); // 无点 → 无后缀
    }

    /// modified：合法零填充 → ISO T 分隔符；非法 → 空串。
    #[test]
    fn modified_iso_and_fallback() {
        assert_eq!(iso_modified("2026-09-05 10:30:00"), "2026-09-05T10:30:00");
        assert_eq!(iso_modified("2026-09-05 10:30:00.123"), "");
        assert_eq!(iso_modified("garbage"), "");
        assert_eq!(iso_modified(""), "");
    }

    /// 无分隔符的真目录（Attributes 含 D）与带尾部 `/` 的目录（走合成分支）。
    #[test]
    fn bare_dir_entries_without_separator() {
        // path 尾部 '/' → 含分隔符 → 合成目录条目（name 取首段、无尾斜杠）。
        let out = "Path = folder/\nFolder = +\nSize = 0\n";
        let result = parse_7z_list_impl(out, "", "x.7z").unwrap();
        let v = &result.as_array().unwrap()[0];
        assert_eq!(v["name"].as_str().unwrap(), "folder");
        assert_eq!(v["path"].as_str().unwrap(), "folder");
        assert!(v["is_dir"].as_bool().unwrap());
        // 无分隔符 + Attributes 含 D → 真目录条目（is_dir 分支）。
        let out2 = "Path = folderdir\nSize = 0\nAttributes = D_....A\n";
        let result2 = parse_7z_list_impl(out2, "", "x.7z").unwrap();
        let v2 = &result2.as_array().unwrap()[0];
        assert_eq!(v2["name"].as_str().unwrap(), "folderdir");
        assert!(v2["is_dir"].as_bool().unwrap());
    }

    /// 合成目录去重：同 sub_dir 多个文件只产生一个目录条目（子文件被 oracle
    /// 丢弃，进入子目录后才出现）。
    #[test]
    fn synthetic_dir_dedup() {
        let out = "Path = a\\x.txt\nPath = a\\y.txt\nPath = b\\z.txt\n";
        let result = parse_7z_list_impl(out, "", "x.7z").unwrap();
        assert_eq!(names(&result), vec!["a".to_string(), "b".to_string()]);
        // 进入 a 子目录后，文件才出现。
        let result_a = parse_7z_list_impl(out, "a", "x.7z").unwrap();
        assert_eq!(names(&result_a), vec!["x.txt".to_string(), "y.txt".to_string()]);
    }

    /// 超限截断：10001 条仅产出 MAX（10000）条，第 10001 条不进入结果。
    #[test]
    fn truncates_at_max_archive_files() {
        let mut output = String::new();
        for i in 0..=MAX_ARCHIVE_FILES {
            output.push_str(&format!("Path = f{i:05}.txt\nSize = {i}\n\n"));
        }
        let result = parse_7z_list_impl(&output, "", "x.7z").unwrap();
        let arr = result.as_array().unwrap();
        assert_eq!(arr.len(), MAX_ARCHIVE_FILES);
        assert_eq!(arr.last().unwrap()["name"].as_str().unwrap(), "f09999.txt");
        assert!(arr
            .iter()
            .all(|v| v["name"].as_str().unwrap() != "f10000.txt"));
    }

    /// split 的 maxsplit 语义：只切前 max 次，剩余文本整体作为最后一块
    ///（镜像 `re.split(r'\n(?=Path = )', out, maxsplit=2)` 实测）。
    #[test]
    fn split_blocks_matches_re_split_maxsplit() {
        let out = "Path = 1\n\nPath = 2\n\nPath = 3\n\nPath = 4";
        assert_eq!(
            split_blocks_with_max(out, 2),
            vec!["Path = 1\n", "Path = 2\n", "Path = 3\n\nPath = 4"]
        );
        let out2 =
            "H\n\nPath = a\nSize = 1\n\n----------\n\nPath = b\nSize = 2\n\nPath = c\nSize = 3";
        let blocks = split_blocks_with_max(out2, 100);
        assert_eq!(blocks.len(), 4);
        assert_eq!(blocks[0], "H\n");
        assert_eq!(blocks[1], "Path = a\nSize = 1\n\n----------\n");
        assert_eq!(blocks[2], "Path = b\nSize = 2\n");
        assert_eq!(blocks[3], "Path = c\nSize = 3");
    }

    /// split 超限合并：>MAX 条路径时最后一块含多条 Path = 行（oracle 只解析首条）。
    #[test]
    fn split_merges_remainder_beyond_max() {
        let mut output = String::new();
        for i in 0..(MAX_ARCHIVE_FILES + 2) {
            output.push_str(&format!("Path = m{i}\n\n"));
        }
        let blocks = split_blocks(&output);
        assert_eq!(blocks.len(), MAX_ARCHIVE_FILES + 1);
        let last = blocks.last().unwrap();
        assert!(last.contains("Path = m10000"));
        assert!(last.contains("Path = m10001"));
        // 整链：仍只产出 MAX 条。
        let result = parse_7z_list_impl(&output, "", "x.7z").unwrap();
        assert_eq!(result.as_array().unwrap().len(), MAX_ARCHIVE_FILES);
    }

    /// py_strip 精确匹配 Python `str.strip()` 的 ASCII 空白语义。
    #[test]
    fn py_strip_matches_python() {
        assert_eq!(py_strip("  a b  "), "a b");
        assert_eq!(py_strip("\r\n\t x \x0b\x0c"), "x");
        assert_eq!(py_strip(""), "");
        assert_eq!(py_strip("   "), "");
        assert_eq!(py_strip("中文 保 留 "), "中文 保 留");
    }
}
