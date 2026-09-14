//! `font.rs` —— 字体信息解析 FFI（todo 22：`faf_parse_font`）。
//!
//! 语义 oracle：`freeassetfilter/services/file_info_service.py` 的
//! `_font_name_rows`（L662-692）与 `_font_detail_rows`（L953-972）——两处
//! fontTools 解析合并为**单次 native 调用**（todo 26 接线），本模块产出
//! 两者所需全部字段。
//!
//! 设计契约（C6 / todo 22 明文）：
//! - **ttf-parser 读原始表**：`Face::parse(data, 0)` 后取
//!   `face.tables().hhea` 的 **raw ascender/descender/line_gap**（非统一缩放
//!   值，与 fontTools `font["hhea"]` 原值一致）+ `maxp` 的 `number_of_glyphs`。
//! - **name 表 1/2/3/4/5/6**：镜像 Python oracle 的逐记录解码链（先
//!   `decode("utf-8")`，失败回退 `decode("latin-1")`）+ 首记录优先 + 空值跳过 +
//!   `seen_values` 去重（与 `_font_name_rows` L683-687 语义逐字节一致）。
//! - **WOFF/WOFF2 裁决（todo 1 spike）**：`wOFF`/`wOF2` 魔数 → 显式返回
//!   [`STATUS_UNSUPPORTED`]，Python 回退 fontTools（ttf-parser 既不支持
//!   WOFF 也不支持 WOFF2，brotli 预解压需反变换 + C 依赖，成本/收益不合算）。
//! - **不 panic**：损坏字体/空文件/超限文件 → Err → FFI 返回 null；所有裸指针
//!   入参经 [`crate::guard_c_str`] 守卫；导出 `catch_to_ptr` 兜底。
//! - **不枚举 QFontDatabase**（Rust 侧只解析表数据，预览路径保留 Python）。
//!
//! 返回指针由 Rust 分配，调用方必须先拷贝内容再经 [`crate::faf_free_message`] 释放。

use std::collections::HashSet;
use std::ffi::c_char;
use std::path::Path;

use ttf_parser::Face;

use crate::{alloc_json_message, catch_to_ptr, guard_c_str};

/// 字体文件大小上限（64MB，远超任何真实字体；防止误喂大文件读入内存）。
const MAX_FONT_BYTES: usize = 64 * 1024 * 1024;

/// WOFF 魔数（`wOFF`）。
const WOFF_MAGIC: &[u8; 4] = b"wOFF";
/// WOFF2 魔数（`wOF2`）。
const WOFF2_MAGIC: &[u8; 4] = b"wOF2";

/// 解析字体字节为 JSON（内部实现，错误码不跨 FFI）。
///
/// - 成功：`{"name1".."name6","format","glyph_count","ascent","descent","line_gap"}`
///   （name 缺失键为 `null`）；
/// - WOFF/WOFF2 → `Err(STATUS_UNSUPPORTED)`（todo 1 裁决：Python 回退 fontTools）；
/// - 损坏/空/缺 hhea·maxp → `Err(STATUS_INTERNAL)`，不 panic。
fn parse_font_impl(data: &[u8]) -> Result<serde_json::Value, i32> {
    // WOFF/WOFF2 魔数 → 显式 STATUS_UNSUPPORTED（先于 ttf-parser，语义精确）。
    if data.len() >= 4 {
        let magic = &data[..4];
        if magic == WOFF_MAGIC || magic == WOFF2_MAGIC {
            return Err(crate::STATUS_UNSUPPORTED);
        }
    }
    // 损坏字体 / 空文件 / 缺必备表 → Err（不 panic）。
    let face = Face::parse(data, 0).map_err(|_| crate::STATUS_INTERNAL)?;
    let tables = face.tables();
    let format = if tables.cff.is_some() {
        "OpenType/CFF"
    } else {
        "TrueType"
    };

    let mut obj = serde_json::Map::new();
    obj.insert("format".to_string(), serde_json::Value::String(format.to_string()));
    obj.insert(
        "glyph_count".to_string(),
        serde_json::Value::from(tables.maxp.number_of_glyphs.get()),
    );
    // raw hhea 值（ttf-parser 读表原值，未统一缩放）。
    obj.insert("ascent".to_string(), serde_json::Value::from(tables.hhea.ascender));
    obj.insert("descent".to_string(), serde_json::Value::from(tables.hhea.descender));
    obj.insert("line_gap".to_string(), serde_json::Value::from(tables.hhea.line_gap));
    for (key, value) in extract_names(&face) {
        obj.insert(key, value);
    }
    Ok(serde_json::Value::Object(obj))
}

/// 提取 name 表 nameID 1/2/3/4/5/6，逐字节镜像 Python
/// `_font_name_rows`（L671-688）语义：
/// 每 nameID 取首个可解码且 strip 后非空、且未被前面 nameID 用过的值；
/// 解码链 = UTF-8 → latin-1（每字节映射 U+00xx，恒成功）。
fn extract_names(face: &Face) -> Vec<(String, serde_json::Value)> {
    let mut seen: HashSet<String> = HashSet::new();
    let mut out = Vec::new();
    for name_id in 1..=6u16 {
        let mut picked: Option<String> = None;
        for name in face.names() {
            if name.name_id != name_id {
                continue;
            }
            let decoded = if let Ok(s) = std::str::from_utf8(name.name) {
                s.to_string()
            } else {
                // latin-1 回退：`u8 as char` 即 U+00xx 映射。
                name.name.iter().map(|&b| b as char).collect()
            };
            let stripped = decoded.trim().to_string();
            if stripped.is_empty() {
                // Python: `if not value: continue`（跳过该记录，看下一条）。
                continue;
            }
            if seen.contains(&stripped) {
                // Python: `if value in seen_values: break`（该 nameID 无值）。
                break;
            }
            seen.insert(stripped.clone());
            picked = Some(stripped);
            break;
        }
        out.push((
            format!("name{}", name_id),
            match picked {
                Some(v) => serde_json::Value::String(v),
                None => serde_json::Value::Null,
            },
        ));
    }
    out
}

/// 解析字体文件（todo 22：`faf_parse_font`），返回
/// `{"name1".."name6","format","glyph_count","ascent","descent","line_gap"}`。
///
/// - 成功：非空 NUL 终止 JSON（`alloc_json_message` 分配，经
///   [`crate::faf_free_message`] 释放）；
/// - WOFF/WOFF2 / 损坏字体 / 空文件 / 超限 / 读取失败 / null·非 UTF-8 路径：
///   返回 null，不 panic。
///
/// `#[allow(clippy::not_unsafe_ptr_arg_deref)]`：FFI 边界保持 `safe extern "C"`
///（与 crate 其余导出契约一致）；入参经 [`crate::guard_c_str`] null 守卫，
/// 指针来源限定为本 crate 调用方（ctypes `c_char_p`），故不标记 `unsafe`。
#[allow(clippy::not_unsafe_ptr_arg_deref)]
#[no_mangle]
pub extern "C" fn faf_parse_font(path: *const c_char) -> *mut c_char {
    catch_to_ptr(|| {
        // SAFETY：guard_c_str 已做 null 守卫；NUL 终止性由 ctypes c_char_p 契约保证。
        let Ok(path_cstr) = (unsafe { guard_c_str(path) }) else {
            return std::ptr::null_mut();
        };
        let Ok(path_str) = path_cstr.to_str() else {
            return std::ptr::null_mut();
        };
        let data = match std::fs::read(Path::new(path_str)) {
            Ok(d) => d,
            Err(_) => return std::ptr::null_mut(),
        };
        if data.len() > MAX_FONT_BYTES {
            return std::ptr::null_mut();
        }
        match parse_font_impl(&data) {
            Ok(value) => alloc_json_message(&value.to_string()),
            Err(_) => std::ptr::null_mut(),
        }
    })
}

// ---------------------------------------------------------------------------
// 单测（todo 22 必写：ttf/otf 字段、woff/woff2 → -6、损坏/空 → Err、null 守卫）
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::CStr;

    /// 字体夹具（todo 5 生成：ttf=ANTQUAB、otf=CFFTest、woff/woff2 由 ttf
    /// flavor 转换、corrupt=破坏魔数截断）。
    const TTF: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/font_samples/sample_regular.ttf");
    const OTF: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/font_samples/sample_regular.otf");
    const WOFF: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/font_samples/sample_regular.woff");
    const WOFF2: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/font_samples/sample_regular.woff2");
    const CORRUPT: &[u8] =
        include_bytes!("../../../../../../tests/support/faf_core_fixtures/font_samples/sample_corrupt.ttf");

    /// 内部解析（直接断言错误码）。
    fn parse(data: &[u8]) -> Result<serde_json::Value, i32> {
        parse_font_impl(data)
    }

    /// 读取 FFI 返回的 JSON 并释放（模拟 Python `string_at` + `free`）。
    fn read_json(raw: *mut c_char) -> Option<serde_json::Value> {
        if raw.is_null() {
            return None;
        }
        // SAFETY：raw 为 faf_parse_font 刚分配的 NUL 终止串。
        let text = unsafe { CStr::from_ptr(raw) }
            .to_str()
            .expect("输出应为合法 UTF-8");
        let parsed: serde_json::Value =
            serde_json::from_str(text).expect("输出应可解析为 JSON");
        crate::faf_free_message(raw);
        Some(parsed)
    }

    /// TTF：字段与 fontTools 原值一致（见 oracle 探针：
    /// hhea 1891/-578/0、maxp numGlyphs 669、name1..6 如右）。
    #[test]
    fn ttf_fields_match_fonttools() {
        let v = parse(TTF).expect("合法 TTF 应解析成功");
        assert_eq!(v["format"], "TrueType");
        assert_eq!(v["glyph_count"], 669);
        assert_eq!(v["ascent"], 1891);
        assert_eq!(v["descent"], -578);
        assert_eq!(v["line_gap"], 0);
        assert_eq!(v["name1"], "Book Antiqua");
        assert_eq!(v["name2"], "Bold");
        assert_eq!(v["name3"], "Book Antiqua Bold : 1991");
        assert_eq!(v["name4"], "Book Antiqua Bold");
        assert_eq!(v["name5"], "Version 2.35");
        assert_eq!(v["name6"], "BookAntiqua-Bold");
    }

    /// OTF（CFF-OpenType）：format=OpenType/CFF、字段与 fontTools 原值一致；
    /// name4/name6 因值 `CFFTest` 已被 name1 用过 → 镜像 oracle 去重 → null。
    #[test]
    fn otf_fields_match_fonttools() {
        let v = parse(OTF).expect("合法 OTF 应解析成功");
        assert_eq!(v["format"], "OpenType/CFF");
        assert_eq!(v["glyph_count"], 5);
        assert_eq!(v["ascent"], 800);
        assert_eq!(v["descent"], 0);
        assert_eq!(v["line_gap"], 90);
        assert_eq!(v["name1"], "CFFTest");
        assert_eq!(v["name2"], "Regular");
        assert_eq!(v["name3"], "FontForge : CFFTest : 9-12-2016");
        // oracle 去重（`value in seen_values → break`）→ 无值。
        assert_eq!(v["name4"], serde_json::Value::Null);
        assert_eq!(v["name5"], "Version 001.000");
        assert_eq!(v["name6"], serde_json::Value::Null);
    }

    /// WOFF → 显式 `STATUS_UNSUPPORTED`（todo 1 裁决：回退 fontTools）。
    #[test]
    fn woff_returns_unsupported() {
        assert_eq!(parse(WOFF).unwrap_err(), crate::STATUS_UNSUPPORTED);
    }

    /// WOFF2 → 显式 `STATUS_UNSUPPORTED`（todo 1 裁决：回退 fontTools）。
    #[test]
    fn woff2_returns_unsupported() {
        assert_eq!(parse(WOFF2).unwrap_err(), crate::STATUS_UNSUPPORTED);
    }

    /// 损坏字体 → Err 而非 panic。
    #[test]
    fn corrupt_font_returns_error_not_panic() {
        let result = std::panic::catch_unwind(|| parse(CORRUPT));
        assert!(result.is_ok(), "损坏字体解析不应 panic");
        assert!(result.unwrap().is_err(), "损坏字体应返回 Err");
    }

    /// 空输入 / 仅 4 字节魔数前缀 → Err（不 panic）。
    #[test]
    fn empty_and_tiny_inputs_error_safely() {
        assert!(parse(&[]).is_err(), "空输入应 Err");
        assert!(parse(b"wOF2").is_err() || parse(b"wOF2").unwrap_err() == crate::STATUS_UNSUPPORTED);
        // 3 字节不足魔数但仍是损坏输入 → Err（不 panic）
        assert!(parse(b"abc").is_err());
    }

    /// FFI：null 路径 → null（`faf_parse_font` 为 `safe extern "C"`，
    /// null 入参是 `guard_c_str` 的被测场景——返回 null 且不解引用）。
    #[test]
    fn ffi_null_path_returns_null() {
        assert!(faf_parse_font(std::ptr::null()).is_null());
    }

    /// FFI：不存在的文件 → null。
    #[test]
    fn ffi_missing_file_returns_null() {
        let path = std::env::temp_dir().join("faf_core_does_not_exist_9f4a.ttf");
        // CString 保证 NUL 终止（FFI 契约）。
        let c_path = std::ffi::CString::new(path.to_str().unwrap()).unwrap();
        let raw = faf_parse_font(c_path.as_ptr());
        assert!(raw.is_null());
    }

    /// FFI 往返：TTF 写临时文件 → 解析 → JSON 字段正确（模拟 Python 桥路径）。
    #[test]
    fn ffi_ttf_roundtrip_via_temp_file() {
        let path = std::env::temp_dir().join("faf_core_font_test_ttf.ttf");
        std::fs::write(&path, TTF).expect("写临时 TTF 应成功");
        let c_path = std::ffi::CString::new(path.to_str().unwrap()).unwrap();
        let raw = faf_parse_font(c_path.as_ptr());
        let v = read_json(raw).expect("合法 TTF 路径应返回 JSON");
        assert_eq!(v["format"], "TrueType");
        assert_eq!(v["glyph_count"], 669);
        assert_eq!(v["ascent"], 1891);
        assert_eq!(v["name1"], "Book Antiqua");
        let _ = std::fs::remove_file(&path);
    }

    /// FFI 往返：WOFF2 → null（Python 走 fontTools 回退）。
    #[test]
    fn ffi_woff2_returns_null_via_temp_file() {
        let path = std::env::temp_dir().join("faf_core_font_test_woff2.woff2");
        std::fs::write(&path, WOFF2).expect("写临时 WOFF2 应成功");
        let c_path = std::ffi::CString::new(path.to_str().unwrap()).unwrap();
        let raw = faf_parse_font(c_path.as_ptr());
        assert!(raw.is_null(), "WOFF2 应返回 null（STATUS_UNSUPPORTED 语义）");
        let _ = std::fs::remove_file(&path);
    }

    // ---- todo 23 补全：空文件 / 仅头 / 截断表 / 缺表 / UTF-16 name ----

    /// 解析 sfnt 表目录，返回 (tag, offset, length) 记录列表。
    fn sfnt_table_records(data: &[u8]) -> Vec<([u8; 4], u32, u32)> {
        assert!(data.len() >= 12, "至少应有 sfnt 头部");
        let num = u16::from_be_bytes([data[4], data[5]]) as usize;
        assert!(data.len() >= 12 + num * 16, "目录应在文件内");
        let mut out = Vec::with_capacity(num);
        for i in 0..num {
            let base = 12 + i * 16;
            let mut tag = [0u8; 4];
            tag.copy_from_slice(&data[base..base + 4]);
            let offset = u32::from_be_bytes(data[base + 8..base + 12].try_into().unwrap());
            let length = u32::from_be_bytes(data[base + 12..base + 16].try_into().unwrap());
            out.push((tag, offset, length));
        }
        out
    }

    /// 改写指定 tag 表的目录记录的 offset/length（不触碰表数据）。
    fn patch_table_dir(mut data: Vec<u8>, tag: &[u8; 4], offset: u32, length: u32) -> Vec<u8> {
        let num = u16::from_be_bytes([data[4], data[5]]) as usize;
        for i in 0..num {
            let base = 12 + i * 16;
            if &data[base..base + 4] == tag {
                data[base + 8..base + 12].copy_from_slice(&offset.to_be_bytes());
                data[base + 12..base + 16].copy_from_slice(&length.to_be_bytes());
                return data;
            }
        }
        panic!("表 {tag:?} 不存在于目录");
    }

    /// 构造仅含一条 Windows/Unicode UTF-16BE name 记录的 name 表
    ///（format=0，count=1，stringOffset=18，record，字符串 "TestName" UTF-16BE）。
    fn build_utf16be_name_table() -> Vec<u8> {
        let mut t = Vec::new();
        t.extend_from_slice(&[0x00, 0x00]); // format 0
        t.extend_from_slice(&[0x00, 0x01]); // count = 1
        t.extend_from_slice(&[0x00, 0x12]); // stringOffset = 6 + 12 = 18
        // record：platform=3(Windows), encoding=1(Unicode BMP), lang=0x0409,
        // nameID=1, length=16, offset=0
        t.extend_from_slice(&[
            0x00, 0x03, 0x00, 0x01, 0x04, 0x09, 0x00, 0x01, 0x00, 0x10, 0x00, 0x00,
        ]);
        // "TestName" UTF-16BE（每字符 2 字节，高字节 0x00）
        for c in "TestName".encode_utf16() {
            t.extend_from_slice(&c.to_be_bytes());
        }
        t
    }

    /// 空文件 / 仅头 / 半目录 / 逐步截断表：**不 panic**（Err 或合法 JSON）。
    /// 覆盖计划「空文件 / 仅头 / 截断表」边界。
    #[test]
    fn truncated_tables_never_panic() {
        let cutoffs = [12usize, 13, 14, 16, 32, 64, 128, 512, 4096];
        for &cut in &cutoffs {
            let truncated = &TTF[..cut.min(TTF.len())];
            let result = std::panic::catch_unwind(|| parse(truncated));
            assert!(result.is_ok(), "截断至 {cut}B 不应 panic");
            if let Ok(Ok(v)) = result {
                assert!(
                    v.get("format").is_some() && v.get("glyph_count").is_some(),
                    "截断至 {cut}B 的意外成功路径也应产出完整字段"
                );
            }
        }
    }

    /// 缺 hhea / 缺 maxp 表（目录记录指向文件末尾外）→ 不 panic，
    /// 按错误（Err）或回退（合法 JSON）处理。
    #[test]
    fn missing_hhea_or_maxp_handled_safely() {
        let eof = TTF.len() as u32;
        for (name, tag) in [("hhea", *b"hhea"), ("maxp", *b"maxp")] {
            let patched = patch_table_dir(TTF.to_vec(), &tag, eof, 0);
            let result = std::panic::catch_unwind(|| parse(&patched));
            assert!(result.is_ok(), "缺 {name} 表不应 panic");
            match result.unwrap() {
                Err(_) => {}
                Ok(v) => {
                    assert!(
                        v.get("format").is_some() && v.get("glyph_count").is_some(),
                        "缺 {name} 表的回退路径也应产出完整字段"
                    );
                }
            }
        }
    }

    /// UTF-16BE name 记录（Windows/Unicode，真实字体最常见的 name 形态）：
    /// 不 panic；解码走 utf-8→latin-1 链（`u8 as char` 逐字节映射 U+00xx，
    /// 与 Python `decode('latin-1')` 回退语义逐字节一致），非 UTF-8 的
    /// nameID 1 得 "\0T\0e..."，其余 nameID 无记录 → null。
    #[test]
    fn utf16be_name_record_falls_back_to_latin1() {
        // 在真实 TTF 的 name 表区域原位写入最小 UTF-16BE name 表，
        // 其余表（head/hhea/maxp/glyf…）不动，字体整体仍合法。
        let name_table = build_utf16be_name_table();
        let (_, name_off, _) = sfnt_table_records(TTF)
            .into_iter()
            .find(|(tag, _, _)| tag == b"name")
            .expect("TTF 应含 name 表");
        let name_off = name_off as usize;
        assert!(
            name_off + name_table.len() <= TTF.len(),
            "name 表区域应可写入最小表"
        );
        let mut patched = TTF.to_vec();
        patched[name_off..name_off + name_table.len()].copy_from_slice(&name_table);
        patched = patch_table_dir(patched, b"name", name_off as u32, name_table.len() as u32);

        let result = std::panic::catch_unwind(|| parse(&patched));
        assert!(result.is_ok(), "UTF-16 name 变体不应 panic");
        let v = result
            .unwrap()
            .expect("替换 name 表后字体应仍可解析");
        // latin-1 逐字节映射："T"→"\0T"，"e"→"\0e"，……
        assert_eq!(v["name1"], "\0T\0e\0s\0t\0N\0a\0m\0e");
        assert_eq!(v["name2"], serde_json::Value::Null);
        assert_eq!(v["name3"], serde_json::Value::Null);
        assert_eq!(v["name4"], serde_json::Value::Null);
        assert_eq!(v["name5"], serde_json::Value::Null);
        assert_eq!(v["name6"], serde_json::Value::Null);
        // 其它表不受影响：hhea/maxp 原值保持。
        assert_eq!(v["glyph_count"], 669);
        assert_eq!(v["ascent"], 1891);
    }

    /// FFI：空文件路径 → null（不 panic，Python 占位符回退）。
    #[test]
    fn ffi_empty_file_returns_null_via_temp_file() {
        let path = std::env::temp_dir().join("faf_core_font_test_empty.ttf");
        std::fs::write(&path, []).expect("写空文件应成功");
        let c_path = std::ffi::CString::new(path.to_str().unwrap()).unwrap();
        let raw = faf_parse_font(c_path.as_ptr());
        assert!(raw.is_null(), "空文件应返回 null");
        let _ = std::fs::remove_file(&path);
    }
}
