//! `svg.rs` —— SVG 图标换色（todo 11：`faf_replace_svg_colors`）。
//!
//! 语义 oracle：`freeassetfilter/core/preview/svg_renderer.py`
//! `_RE_*` 18 条预编译正则（L35-55）与 `_replace_svg_colors`（L68-137）替换
//! 顺序、`_convert_rgba_to_hex`/`rgba_to_hex`（L174-213）。返回替换后的 SVG
//! 文本（NUL 终止 `c_char*`；经既有输出契约 [`crate::alloc_json_message`]）。
//!
//! # 颜色契约（重要）
//!
//! FFI 签名 `faf_replace_svg_colors(svg_text, invert_white_to_black,
//! force_black_to_base)` **固定三入参**（todo 2/3 已定，不携带主题色参数），
//! 且 todo 11 明确「不访问主题、不返回颜色」。故本模块用**编译期常量**
//! 镜像应用默认深色主题（`ui/theme/colors.json` `gray.g2/g3/g4` +
//! `accent.primary`，`ThemeManager` 深色模式实测值）：
//!
//! | Python token | 本模块常量 | 值（QColor.name() 小写） |
//! |---|---|---|
//! | `tm.accent.name()` | [`ACCENT_COLOR`] | `#3a9dcb` |
//! | `tm.fill.name()`（base） | [`BASE_COLOR`] | `#3e3e3e` |
//! | `tm.text.name()`（secondary） | [`SECONDARY_COLOR`] | `#ffffff` |
//! | `tm.mid.name()`（normal） | [`NORMAL_COLOR`] | `#888888` |
//!
//! Python 对拍要求**逐字节一致**：对拍 harness 把 `svg_renderer.tm` stub 成
//! 与上述常量一致的色值（与 `tests/unit/core/test_svg_renderer.py` 的
//! monkeypatch 范式相同），native 与 Python 输出即严格相等。
//!
//! # `_RE_PATH_NO_FILL` 的 lookahead 手工移植
//!
//! `regex` crate 1.x **不支持 lookahead**（todo 1 spike 实证）。Python 原式
//! `<path\b(?!.*\bfill\s*=)(?!.*\bclass\s*=)`（IGNORECASE）语义为：`<path` +
//! 词边界，且**后面本行内**不出现 `\bfill\s*=` 或 `\bclass\s*=`（注意 `.` 不跨
//! 行 → 只在当前行内检查），命中即注入 `fill="#000000"`。手工等价实现见
//! [`insert_fill_for_paths_without_fill`]（逐字节扫描 `<path`（大小写不敏感）
//! + 词边界 + 行内 `\bfill\s*=` / `\bclass\s*=` 存在性检查）。
//!
//! # `_RE_CSS_FILL_*` 的 `\1` 保留语义
//!
//! `_RE_CSS_FILL_WHITE`/`_RE_CSS_FILL_WHITE_SHORT` 的 **invert 分支**替换为
//! `\1#000000`（保留 `fill:` 后原样空白）；`_RE_CSS_FILL_BLACK*`（else 分支）
//! 替换为 `fill: {color}`（吃掉空白，统一为单空格）。regex crate 用 `$1`
//! 表示捕获组（`\1` 语法为 grep/PCRE 风格，不适用）。
//!
//! # 替换顺序（对齐 `_replace_svg_colors` L96-129，顺序敏感）
//!
//! 1. `_RE_PATH_NO_FILL`（先注入 `fill="#000000"` → 可能被后续 fill-black
//!    规则再替换）；
//! 2. stroke 组（invert：白→黑；else：白→base、黑→black_replacement）；
//! 3. fill 组（同上）；
//! 4. CSS-fill 组（invert：白→`\1#000000`；else：白→base、黑→black_replacement）；
//! 5. `#0a59f7` → accent（IGNORECASE，任意位置）；
//! 6. normal 组（`#cecece` → `tm.mid`，stroke/fill/CSS-fill/CSS-stroke）。
//!
//! `black_replacement_color = base if force_black_to_base else secondary`
//!（L92）。不 panic、不做文件 I/O；非 UTF-8 与空指针由 FFI 边界（`lib.rs`
//! `guard_c_str`/`to_str`）在进入本函数前拦截。

use once_cell::sync::Lazy;
use regex::Regex;

/// `tm.accent.name()` 镜像常量（颜色契约，见模块文档）。
pub(crate) const ACCENT_COLOR: &str = "#3a9dcb";
/// `tm.fill.name()` 镜像常量（base_color）。
pub(crate) const BASE_COLOR: &str = "#3e3e3e";
/// `tm.text.name()` 镜像常量（secondary_color）。
pub(crate) const SECONDARY_COLOR: &str = "#ffffff";
/// `tm.mid.name()` 镜像常量（normal_color）。
pub(crate) const NORMAL_COLOR: &str = "#888888";

// 17 条字面量正则（`_RE_PATH_NO_FILL` 之外的全部），`(?i)` 复刻 `re.IGNORECASE`。
// 用普通字符串常量（含转义）规避 raw-string 的 `"#` / 尾引号终止坑。
// 类型为 `Lazy<Result<Regex, regex::Error>>`（F2 门禁：业务路径禁函数式 panic 抽取）
// 编译期字面量恒 `Ok`，调用处（`sub_all`/`convert_rgba_to_hex`）对 `Err` 优雅跳过。
static RE_STROKE_WHITE: Lazy<Result<Regex, regex::Error>> =
    Lazy::new(|| Regex::new("(?i)stroke=\"#FFFFFF\""));
static RE_STROKE_WHITE_SHORT: Lazy<Result<Regex, regex::Error>> =
    Lazy::new(|| Regex::new("(?i)stroke=\"#FFF\""));
static RE_STROKE_BLACK: Lazy<Result<Regex, regex::Error>> =
    Lazy::new(|| Regex::new("(?i)stroke=\"#000000\""));
static RE_STROKE_BLACK_SHORT: Lazy<Result<Regex, regex::Error>> =
    Lazy::new(|| Regex::new("(?i)stroke=\"#000\""));
static RE_FILL_WHITE: Lazy<Result<Regex, regex::Error>> =
    Lazy::new(|| Regex::new("(?i)fill=\"#FFFFFF\""));
static RE_FILL_WHITE_SHORT: Lazy<Result<Regex, regex::Error>> =
    Lazy::new(|| Regex::new("(?i)fill=\"#FFF\""));
static RE_FILL_BLACK: Lazy<Result<Regex, regex::Error>> =
    Lazy::new(|| Regex::new("(?i)fill=\"#000000\""));
static RE_FILL_BLACK_SHORT: Lazy<Result<Regex, regex::Error>> =
    Lazy::new(|| Regex::new("(?i)fill=\"#000\""));
static RE_CSS_FILL_WHITE: Lazy<Result<Regex, regex::Error>> =
    Lazy::new(|| Regex::new("(?i)(fill:\\s*)#FFFFFF"));
static RE_CSS_FILL_WHITE_SHORT: Lazy<Result<Regex, regex::Error>> =
    Lazy::new(|| Regex::new("(?i)(fill:\\s*)#FFF"));
static RE_CSS_FILL_BLACK: Lazy<Result<Regex, regex::Error>> =
    Lazy::new(|| Regex::new("(?i)(fill:\\s*)#000000"));
static RE_CSS_FILL_BLACK_SHORT: Lazy<Result<Regex, regex::Error>> =
    Lazy::new(|| Regex::new("(?i)(fill:\\s*)#000\\b"));
static RE_ACCENT: Lazy<Result<Regex, regex::Error>> =
    Lazy::new(|| Regex::new("(?i)#0a59f7"));
static RE_STROKE_NORMAL: Lazy<Result<Regex, regex::Error>> =
    Lazy::new(|| Regex::new("(?i)stroke=\"#cecece\""));
static RE_FILL_NORMAL: Lazy<Result<Regex, regex::Error>> =
    Lazy::new(|| Regex::new("(?i)fill=\"#cecece\""));
static RE_CSS_FILL_NORMAL: Lazy<Result<Regex, regex::Error>> =
    Lazy::new(|| Regex::new("(?i)(fill:\\s*)#cecece"));
static RE_CSS_STROKE_NORMAL: Lazy<Result<Regex, regex::Error>> =
    Lazy::new(|| Regex::new("(?i)(stroke:\\s*)#cecece"));
// `_convert_rgba_to_hex` 的 `rgba\(([^\)]+)\)`（**无** IGNORECASE，Python 原样）。
static RE_RGBA: Lazy<Result<Regex, regex::Error>> =
    Lazy::new(|| Regex::new(r"rgba\(([^)]+)\)"));

/// `_RE_PATH_NO_FILL` lookahead 中 `\bfill\s*=` / `\bclass\s*=` 的存在性检查。
///
/// Python 原式 `.` **不跨行**（无 DOTALL）→ 注入判据只看 `<path` 之后的
/// **当前行**。此处限定扫描上界为行尾 `\n`；`\s*`（谓词中可含换行）在命中
/// `fill`/`class` 后再向后吞（对齐 Python `\s` 含 `\n` 的语义），但命中点本身
/// 必在本行内。词边界按 ASCII `[A-Za-z0-9_]` 近似（SVG 标签均为 ASCII）。
fn line_has_fill_or_class_eq(input: &str, from: usize) -> bool {
    let bytes = input.as_bytes();
    let mut line_end = from;
    while line_end < input.len() && bytes[line_end] != b'\n' {
        line_end += 1;
    }
    for attr in ["fill", "class"] {
        let a = attr.as_bytes();
        let mut j = from;
        while j < input.len() && j < line_end {
            if j + a.len() <= input.len()
                && j > from
                && bytes[j..j + a.len()]
                    .iter()
                    .zip(a.iter())
                    .all(|(x, y)| x.eq_ignore_ascii_case(y))
                && !bytes[j - 1].is_ascii_alphanumeric()
                && bytes[j - 1] != b'_'
            {
                // `\s*` 后须跟 `=`（`\s` 含换行，Python 语义；`.*` 前已限本行，
                // 因此 `fill` 必在本行内）。
                let mut k = j + a.len();
                while k < input.len() && bytes[k].is_ascii_whitespace() {
                    k += 1;
                }
                if k < input.len() && bytes[k] == b'=' {
                    return true;
                }
            }
            j += 1;
        }
    }
    false
}

/// `_RE_PATH_NO_FILL` 手工移植：给无 `fill=`/`class=` 的 `<path>` 注入
/// `<path fill="#000000"`（IGNORECASE + 词边界 + 仅检查当前行）。
///
/// 逐字节扫描 `<path` 字面量（大小写不敏感）；非 ASCII 多字节字符按 UTF-8
/// 序列整体跳读，保证任意合法 `&str` 输入安全（不 panic、不产出非法输出）。
fn insert_fill_for_paths_without_fill(input: &str) -> String {
    let bytes = input.as_bytes();
    let mut out = String::with_capacity(input.len());
    let mut i = 0usize;
    while i < input.len() {
        // `<path` 大小写不敏感字面量。
        let path_at = i + 5 <= input.len()
            && bytes[i] == b'<'
            && (bytes[i + 1] == b'p' || bytes[i + 1] == b'P')
            && (bytes[i + 2] == b'a' || bytes[i + 2] == b'A')
            && (bytes[i + 3] == b't' || bytes[i + 3] == b'T')
            && (bytes[i + 4] == b'h' || bytes[i + 4] == b'H');
        if path_at {
            let after = i + 5;
            // `\b`：后一字符须非词字符（或无后续）。
            let has_boundary = after >= input.len()
                || !(bytes[after].is_ascii_alphanumeric() || bytes[after] == b'_');
            if has_boundary && !line_has_fill_or_class_eq(input, after) {
                out.push_str("<path fill=\"#000000\"");
                i = after;
                continue;
            }
        }
        // 未命中注入点：按 UTF-8 首字节长度拷贝当前字符（多字节安全）。
        let next = i + utf8_len(bytes[i]) + 1;
        out.push_str(&input[i..next]);
        i = next;
    }
    out
}

/// UTF-8 首字节的序列长度（续字节数：单字节 0、双字节 1、三字节 2、四字节 3；
/// ASCII 断言已由 `b < 0x80` 覆盖）。非法续字节按 1 处理，保证不越界。
fn utf8_len(b: u8) -> usize {
    if b < 0x80 {
        0
    } else if (0xC0..=0xDF).contains(&b) {
        1
    } else if (0xE0..=0xEF).contains(&b) {
        2
    } else if (0xF0..=0xF7).contains(&b) {
        3
    } else {
        0
    }
}

/// `regex` crate 的 `re.sub`。`replace_all(...).into_owned()` 语义与 Python 相同。
///
/// 静态正则存为 `Result`（F2 门禁：业务路径禁函数式 panic 抽取）；编译期字面量
/// 恒 `Ok`，理论不可达的 `Err` 分支优雅跳过替换（原样返回文本），不 panic。
fn sub_all(re: &Result<Regex, regex::Error>, text: &str, repl: &str) -> String {
    re.as_ref().map_or_else(
        |_| text.to_string(),
        |re| re.replace_all(text, repl).into_owned(),
    )
}

/// `_replace_svg_colors`（L68-137）替换顺序 + `_convert_rgba_to_hex`（Rust 版）。
///
/// - `invert_white_to_black`：白 → `#000000`（stroke/fill/CSS-fill 三分支）；
/// - `force_black_to_base`：黑 → [`BASE_COLOR`]，否则 → [`SECONDARY_COLOR`]。
///
/// 成功返回替换后的完整 SVG 文本；不访问主题、不 panic、不做文件 I/O。
pub fn replace_svg_colors_impl(
    svg_text: &str,
    invert_white_to_black: bool,
    force_black_to_base: bool,
) -> Result<String, i32> {
    let black_replacement = if force_black_to_base {
        BASE_COLOR
    } else {
        SECONDARY_COLOR
    };

    // 1. _RE_PATH_NO_FILL：无 fill/class 的 <path> 注入 fill="#000000"。
    let mut out = insert_fill_for_paths_without_fill(svg_text);

    // 2. stroke 组。
    if invert_white_to_black {
        out = sub_all(&RE_STROKE_WHITE, &out, "stroke=\"#000000\"");
        out = sub_all(&RE_STROKE_WHITE_SHORT, &out, "stroke=\"#000000\"");
    } else {
        out = sub_all(&RE_STROKE_WHITE, &out, &format!("stroke=\"{BASE_COLOR}\""));
        out = sub_all(&RE_STROKE_WHITE_SHORT, &out, &format!("stroke=\"{BASE_COLOR}\""));
        out = sub_all(&RE_STROKE_BLACK, &out, &format!("stroke=\"{black_replacement}\""));
        out = sub_all(&RE_STROKE_BLACK_SHORT, &out, &format!("stroke=\"{black_replacement}\""));
    }

    // 3. fill 组。
    if invert_white_to_black {
        out = sub_all(&RE_FILL_WHITE, &out, "fill=\"#000000\"");
        out = sub_all(&RE_FILL_WHITE_SHORT, &out, "fill=\"#000000\"");
    } else {
        out = sub_all(&RE_FILL_WHITE, &out, &format!("fill=\"{BASE_COLOR}\""));
        out = sub_all(&RE_FILL_WHITE_SHORT, &out, &format!("fill=\"{BASE_COLOR}\""));
        out = sub_all(&RE_FILL_BLACK, &out, &format!("fill=\"{black_replacement}\""));
        out = sub_all(&RE_FILL_BLACK_SHORT, &out, &format!("fill=\"{black_replacement}\""));
    }

    // 4. CSS-fill 组。
    if invert_white_to_black {
        out = sub_all(&RE_CSS_FILL_WHITE, &out, "$1#000000");
        out = sub_all(&RE_CSS_FILL_WHITE_SHORT, &out, "$1#000000");
    } else {
        out = sub_all(&RE_CSS_FILL_WHITE, &out, &format!("fill: {BASE_COLOR}"));
        out = sub_all(&RE_CSS_FILL_WHITE_SHORT, &out, &format!("fill: {BASE_COLOR}"));
        out = sub_all(&RE_CSS_FILL_BLACK, &out, &format!("fill: {black_replacement}"));
        out = sub_all(&RE_CSS_FILL_BLACK_SHORT, &out, &format!("fill: {black_replacement}"));
    }

    // 5. accent（#0a59f7，IGNORECASE，任意位置）。
    out = sub_all(&RE_ACCENT, &out, ACCENT_COLOR);

    // 6. normal 组（#cecece → tm.mid）。
    out = sub_all(&RE_STROKE_NORMAL, &out, &format!("stroke=\"{NORMAL_COLOR}\""));
    out = sub_all(&RE_FILL_NORMAL, &out, &format!("fill=\"{NORMAL_COLOR}\""));
    out = sub_all(&RE_CSS_FILL_NORMAL, &out, &format!("fill: {NORMAL_COLOR}"));
    out = sub_all(&RE_CSS_STROKE_NORMAL, &out, &format!("stroke: {NORMAL_COLOR}"));

    // _convert_rgba_to_hex：`rgba(r, g, b, a)` → `#rrggbbaa`。
    out = convert_rgba_to_hex(&out);
    Ok(out)
}

/// `_convert_rgba_to_hex`/`rgba_to_hex` 语义（`svg_renderer.py:174-213`）。
/// 解析任一分量失败时**保持原样**（不 panic；合法输入不含此类畸形）。
/// 正则自身存 `Result`（门禁）——编译期字面量恒 `Ok`，`Err` 时原样返回。
fn convert_rgba_to_hex(svg_content: &str) -> String {
    let Ok(re) = RE_RGBA.as_ref() else {
        return svg_content.to_string();
    };
re.replace_all(svg_content, |caps: &regex::Captures<'_>| {
        let inner = caps.get(1).map(|m| m.as_str()).unwrap_or_default();
        let parts: Vec<&str> = inner.split(',').collect();
        if parts.len() != 4 {
            return caps[0].to_string();
        }
        let mut channels = [0f64; 3];
        for (i, c) in channels.iter_mut().enumerate() {
            let raw = match parse_channel(parts[i], false) {
                Some(v) => v,
                None => return caps[0].to_string(),
            };
            *c = raw.clamp(0.0, 255.0);
        }
        let alpha = match parse_channel(parts[3], true) {
            Some(v) => v.clamp(0.0, 1.0),
            None => return caps[0].to_string(),
        };
        let (r, g, b) = (channels[0] as u32, channels[1] as u32, channels[2] as u32);
        let a = (alpha * 255.0) as u32;
        format!("#{r:02x}{g:02x}{b:02x}{a:02x}")
    })
    .into_owned()
}

/// 解析 rgba 单分量：含 `%` 时 r/g/b ×2.55、a ÷100（对齐 Python 浮点语义）。
fn parse_channel(part: &str, is_alpha: bool) -> Option<f64> {
    let trimmed = part.trim();
    if trimmed.is_empty() {
        return None;
    }
    if is_alpha {
        if trimmed.ends_with('%') {
            trimmed
                .trim_end_matches('%')
                .trim()
                .parse::<f64>()
                .ok()
                .map(|v| v / 100.0)
        } else {
            trimmed.parse::<f64>().ok()
        }
    } else if trimmed.ends_with('%') {
        trimmed
            .trim_end_matches('%')
            .trim()
            .parse::<f64>()
            .ok()
            .map(|v| v * 2.55)
    } else {
        trimmed.parse::<f64>().ok()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // ------------------------------------------------------------------
    // 18 条正则各命中的针对性断言（与 _replace_svg_colors 单规则语义对齐）
    // ------------------------------------------------------------------

/// _RE_PATH_NO_FILL：无 fill/class 的 <path> 注入 fill（词边界 + 行内检查）。
    /// 用 invert 模式隔离注入（黑度规则不运行，注射的 `#000000` 原样保留）。
    #[test]
    fn path_no_fill_injects_into_bare_path() {
        let out = replace_svg_colors_impl("<svg><path d=\"M0 0z\"/></svg>", true, false).unwrap();
        assert_eq!(out, "<svg><path fill=\"#000000\" d=\"M0 0z\"/></svg>");
    }

    /// _RE_PATH_NO_FILL：同一行内已有 `fill=`（任意大小写）不注入。
    #[test]
    fn path_no_fill_skips_when_line_has_fill() {
        let out = replace_svg_colors_impl(
            "<svg><path d=\"M0 0z\" fill=\"#FFFFFF\"/></svg>",
            false,
            false,
        )
        .unwrap();
        // fill="#FFFFFF" 被 fill-white 规则替换为 base，path 不再注入。
        assert_eq!(out, "<svg><path d=\"M0 0z\" fill=\"#3e3e3e\"/></svg>");
    }

/// _RE_PATH_NO_FILL：`fill=` 位于后续行时（`.` 不跨行）仍需注入（Python 怪癖）。
    /// `invert=True` 时黑度规则不运行，可观测注入的 `#000000` 原样保留。
    #[test]
    fn path_no_fill_crosses_line_like_python_dot() {
        let svg = "<svg>\n<path d=\"M0 0z\"\n fill=\"#000\"/>\n</svg>";
        let out = replace_svg_colors_impl(svg, true, false).unwrap();
        assert!(out.contains("<path fill=\"#000000\" d=\"M0 0z\"\n fill=\"#000\"/>"));
    }

    /// _RE_STROKE_WHITE：全大写 `#FFFFFF` → base。
    #[test]
    fn stroke_white_replaced() {
        let out = replace_svg_colors_impl(
            "<svg><rect stroke=\"#FFFFFF\"/></svg>",
            false,
            false,
        )
        .unwrap();
        assert_eq!(out, "<svg><rect stroke=\"#3e3e3e\"/></svg>");
    }

    /// _RE_STROKE_WHITE_SHORT：`#FFF` → base。
    #[test]
    fn stroke_white_short_replaced() {
        let out = replace_svg_colors_impl("<svg><rect stroke=\"#FFF\"/></svg>", false, false)
            .unwrap();
        assert_eq!(out, "<svg><rect stroke=\"#3e3e3e\"/></svg>");
    }

    /// _RE_STROKE_BLACK：`#000000` → secondary（默认）。
    #[test]
    fn stroke_black_replaced() {
        let out = replace_svg_colors_impl(
            "<svg><rect stroke=\"#000000\"/></svg>",
            false,
            false,
        )
        .unwrap();
        assert_eq!(out, "<svg><rect stroke=\"#ffffff\"/></svg>");
    }

    /// _RE_STROKE_BLACK_SHORT：`#000` → secondary（默认）。
    #[test]
    fn stroke_black_short_replaced() {
        let out = replace_svg_colors_impl("<svg><rect stroke=\"#000\"/></svg>", false, false)
            .unwrap();
        assert_eq!(out, "<svg><rect stroke=\"#ffffff\"/></svg>");
    }

    /// _RE_FILL_WHITE：`fill="#FFFFFF"` → base。
    #[test]
    fn fill_white_replaced() {
        let out = replace_svg_colors_impl("<svg><rect fill=\"#FFFFFF\"/></svg>", false, false)
            .unwrap();
        assert_eq!(out, "<svg><rect fill=\"#3e3e3e\"/></svg>");
    }

    /// _RE_FILL_WHITE_SHORT：`fill="#FFF"` → base。
    #[test]
    fn fill_white_short_replaced() {
        let out = replace_svg_colors_impl("<svg><rect fill=\"#FFF\"/></svg>", false, false).unwrap();
        assert_eq!(out, "<svg><rect fill=\"#3e3e3e\"/></svg>");
    }

    /// _RE_FILL_BLACK：`fill="#000000"` → secondary（默认）。
    #[test]
    fn fill_black_replaced() {
        let out = replace_svg_colors_impl("<svg><rect fill=\"#000000\"/></svg>", false, false)
            .unwrap();
        assert_eq!(out, "<svg><rect fill=\"#ffffff\"/></svg>");
    }

    /// _RE_FILL_BLACK_SHORT：`fill="#000"` → secondary（默认）。
    #[test]
    fn fill_black_short_replaced() {
        let out = replace_svg_colors_impl("<svg><rect fill=\"#000\"/></svg>", false, false).unwrap();
        assert_eq!(out, "<svg><rect fill=\"#ffffff\"/></svg>");
    }

/// _RE_CSS_FILL_WHITE：`style="fill:  #FFFFFF"` → `fill: base`（吃掉空白）。
    /// `<path style=...>` 无 `fill=` 属性 → 先被 PATH_NO_FILL 注入
    /// `fill="#000000"`（行内无 `fill=`），随后 fill-black 规则转成 `#ffffff`。
    #[test]
    fn css_fill_white_replaced() {
        let out = replace_svg_colors_impl(
            "<svg><path style=\"fill:  #FFFFFF\"/></svg>",
            false,
            false,
        )
        .unwrap();
        assert_eq!(out, "<svg><path fill=\"#ffffff\" style=\"fill: #3e3e3e\"/></svg>");
    }

    /// _RE_CSS_FILL_WHITE_SHORT：`fill: #FFF` → base。
    #[test]
    fn css_fill_white_short_replaced() {
        let out = replace_svg_colors_impl(
            "<svg><path style=\"fill: #FFF\"/></svg>",
            false,
            false,
        )
        .unwrap();
        assert_eq!(out, "<svg><path fill=\"#ffffff\" style=\"fill: #3e3e3e\"/></svg>");
    }

    /// _RE_CSS_FILL_BLACK：`fill: #000000` → secondary。
    #[test]
    fn css_fill_black_replaced() {
        let out = replace_svg_colors_impl(
            "<svg><path style=\"fill: #000000\"/></svg>",
            false,
            false,
        )
        .unwrap();
        assert_eq!(out, "<svg><path fill=\"#ffffff\" style=\"fill: #ffffff\"/></svg>");
    }

    /// _RE_CSS_FILL_BLACK_SHORT：`fill: #000` → secondary（`\b` 不截 `#0000`）。
    #[test]
    fn css_fill_black_short_replaced() {
        let out = replace_svg_colors_impl(
            "<svg><path style=\"fill: #000\"/></svg>",
            false,
            false,
        )
        .unwrap();
        assert_eq!(out, "<svg><path fill=\"#ffffff\" style=\"fill: #ffffff\"/></svg>");
    }

    /// _RE_ACCENT：`#0a59f7`（任意大小写）→ accent。
    #[test]
    fn accent_replaced() {
        let out = replace_svg_colors_impl(
            "<svg><circle fill=\"#0A59F7\"/></svg>",
            false,
            false,
        )
        .unwrap();
        assert_eq!(out, "<svg><circle fill=\"#3a9dcb\"/></svg>");
    }

    /// _RE_STROKE_NORMAL：`stroke="#cecece"` → normal。
    #[test]
    fn stroke_normal_replaced() {
        let out = replace_svg_colors_impl(
            "<svg><rect stroke=\"#cecece\"/></svg>",
            false,
            false,
        )
        .unwrap();
        assert_eq!(out, "<svg><rect stroke=\"#888888\"/></svg>");
    }

    /// _RE_FILL_NORMAL：`fill="#cecece"` → normal。
    #[test]
    fn fill_normal_replaced() {
        let out = replace_svg_colors_impl("<svg><rect fill=\"#cecece\"/></svg>", false, false)
            .unwrap();
        assert_eq!(out, "<svg><rect fill=\"#888888\"/></svg>");
    }

/// _RE_CSS_FILL_NORMAL：`fill: #cecece` → normal。
    #[test]
    fn css_fill_normal_replaced() {
        let out = replace_svg_colors_impl(
            "<svg><path style=\"fill: #cecece\"/></svg>",
            false,
            false,
        )
        .unwrap();
        assert_eq!(out, "<svg><path fill=\"#ffffff\" style=\"fill: #888888\"/></svg>");
    }

    /// _RE_CSS_STROKE_NORMAL：`stroke: #cecece` → normal。
    #[test]
    fn css_stroke_normal_replaced() {
        let out = replace_svg_colors_impl(
            "<svg><path style=\"stroke: #cecece\"/></svg>",
            false,
            false,
        )
        .unwrap();
        assert_eq!(out, "<svg><path fill=\"#ffffff\" style=\"stroke: #888888\"/></svg>");
    }

    // ------------------------------------------------------------------
    // 开关分支
    // ------------------------------------------------------------------

    /// invert_white_to_black：白 → `#000000`，黑保持 `#000000`（stroke/fill/css）。
    #[test]
    fn invert_white_to_black_branch() {
        let out = replace_svg_colors_impl(
            "<svg><rect stroke=\"#FFFFFF\" fill=\"#FFF\" style=\"fill: #FFFFFF\"/></svg>",
            true,
            false,
        )
        .unwrap();
        assert_eq!(
            out,
            "<svg><rect stroke=\"#000000\" fill=\"#000000\" style=\"fill: #000000\"/></svg>"
        );
    }

    /// force_black_to_base：黑 → base，白 → base。
    #[test]
    fn force_black_to_base_branch() {
        let out = replace_svg_colors_impl(
            "<svg><rect stroke=\"#000\" fill=\"#FFFFFF\"/></svg>",
            false,
            true,
        )
        .unwrap();
        assert_eq!(out, "<svg><rect stroke=\"#3e3e3e\" fill=\"#3e3e3e\"/></svg>");
    }

    // ------------------------------------------------------------------
    // rgba → hex（_convert_rgba_to_hex / rgba_to_hex）
    // ------------------------------------------------------------------

    #[test]
    fn rgba_to_hex_basic() {
        let out = replace_svg_colors_impl(
            "<path fill=\"rgba(255, 0, 0, 1)\"/>",
            false,
            false,
        )
        .unwrap();
        assert_eq!(out, "<path fill=\"#ff0000ff\"/>");
    }

    #[test]
    fn rgba_to_hex_percentage() {
        let out = replace_svg_colors_impl(
            "<path fill=\"rgba(100%, 0%, 0%, 50%)\"/>",
            false,
            false,
        )
        .unwrap();
        assert_eq!(out, "<path fill=\"#fe00007f\"/>");
    }

    #[test]
    fn rgba_to_hex_clamping() {
        let out = replace_svg_colors_impl(
            "<path fill=\"rgba(300, -10, 128, 2)\"/>",
            false,
            false,
        )
        .unwrap();
        assert_eq!(out, "<path fill=\"#ff0080ff\"/>");
    }

    #[test]
    fn rgba_to_hex_no_rgba_unchanged() {
        let svg = "<path fill=\"#ff0000\"/>";
        let out = replace_svg_colors_impl(svg, false, false).unwrap();
        assert_eq!(out, svg);
    }

    // ------------------------------------------------------------------
    // 无命中 / 空文本 / 大小写不敏感
    // ------------------------------------------------------------------

    #[test]
    fn no_match_returned_verbatim() {
        let svg = "<svg><path d=\"M0 0z\" fill=\"#123456\"/></svg>";
        let out = replace_svg_colors_impl(svg, false, false).unwrap();
        assert_eq!(out, svg);
    }

    #[test]
    fn empty_text_returns_empty() {
        let out = replace_svg_colors_impl("", false, false).unwrap();
        assert_eq!(out, "");
    }

/// _RE_* 大小写不敏感：大写属性名/色值同样命中，但整段被替换（`stroke=` 变
    /// 小写——Python `re.sub` 替换的是整段匹配，含属性名）。
    #[test]
    fn case_insensitive_upper_attrs() {
        let out = replace_svg_colors_impl(
            "<svg><rect STROKE=\"#FFFFFF\" FILL=\"#FFF\"/></svg>",
            false,
            false,
        )
        .unwrap();
        assert_eq!(out, "<svg><rect stroke=\"#3e3e3e\" fill=\"#3e3e3e\"/></svg>");
    }

    // ------------------------------------------------------------------
    // 顺序敏感（PATH_NO_FILL 注入先于 fill-black；CSS 吃空白）
    // ------------------------------------------------------------------

    #[test]
    fn path_injected_fill_then_black_replaced() {
        let out = replace_svg_colors_impl("<svg><path d=\"M0 0z\"/></svg>", false, false).unwrap();
        // 注入 `#000000` 后被 fill-black 规则 → secondary。
        assert_eq!(out, "<svg><path fill=\"#ffffff\" d=\"M0 0z\"/></svg>");
    }

#[test]
    fn css_fill_white_keeps_whitespace_in_invert() {
        let out = replace_svg_colors_impl(
            "<svg><path style=\"fill:   #FFFFFF\"/></svg>",
            true,
            false,
        )
        .unwrap();
// invert 分支是 `\1#000000`：保留原空白；且黑度规则不运行，注入的
        // `fill="#000000"` 原样保留。
        assert_eq!(out, "<svg><path fill=\"#000000\" style=\"fill:   #000000\"/></svg>");
    }

    /// 非 UTF-8 输入：FFI 层 `faf_replace_svg_colors` 经 `to_str()` 拒绝后
    /// 返回 null（不 panic，桥侧回退 Python）。svg.rs 的 `&str` 入参本身
    /// 保证合法 UTF-8；此用例覆盖导出的入口守卫。
    #[test]
    fn ffi_rejects_non_utf8_input() {
        let bad = std::ffi::CString::new(vec![0xFFu8, 0xFEu8, 0x41u8]).unwrap();
        // SAFETY：指针有效且 NUL 终止；导出为 catch_to_ptr 兜底，不 panic。
        let ptr = crate::faf_replace_svg_colors(bad.as_ptr(), 0, 0);
        assert!(ptr.is_null());
    }

    /// 空文本经 FFI：空置换文本返回非空 NUL 终止串开头（`<svg/>` 无命中时
    /// 为原样文本）；本用例补充 FFI 层非 panic 冒烟。
    #[test]
    fn ffi_accepts_valid_utf8_svg() {
        let ok = std::ffi::CString::new("<svg><path d=\"M0 0z\"/></svg>").unwrap();
        // SAFETY：指针有效且 NUL 终止；导出内部 catch_to_ptr 兜底。
        let ptr = crate::faf_replace_svg_colors(ok.as_ptr(), 0, 0);
        assert!(!ptr.is_null());
        unsafe {
            drop(std::ffi::CString::from_raw(ptr));
        }
    }

    /// 空文本经 FFI：`CString` 空串分配后不可为 null（与 impl 空串返回一致）。
    #[test]
    fn ffi_empty_text_returns_non_null_empty_string() {
        let empty = std::ffi::CString::new("").unwrap();
        // SAFETY：指针有效且 NUL 终止；导出内部 catch_to_ptr 兜底。
        let ptr = crate::faf_replace_svg_colors(empty.as_ptr(), 0, 0);
        assert!(!ptr.is_null());
        unsafe {
            let c = std::ffi::CString::from_raw(ptr);
            assert_eq!(c.to_bytes(), b"");
            drop(c);
        }
    }
}
