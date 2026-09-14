//! `highlight.rs` —— 代码语法高亮（todo 11：`faf_highlight_text`）。
//!
//! 方案 B（task-1-decisions.md §1.4 裁决）：syntect **内置默认语法集**
//! （`SyntaxSet::load_defaults_newlines()`，OnceLock 单例，随 crate 静态
//! 内嵌），**不加载 `utils/syntax/` 的 57 个 TextMate JSON**（syntect 5.x
//! 无 TextMate loader，57/57 不可加载，见 spike）。
//!
//! 语义契约（与 `freeassetfilter/utils/syntax_highlighter.py` 对齐）：
//! - 输出 `[{start,len,token_type}]`，**start/len 为字符偏移**（非 byte；
//!   byte 偏移在非 ASCII 文本下与 QTextDocument 字符位置不符）；
//! - **span 连续覆盖全文**：∑len == text 字符数；换行符单独成段（采用行尾
//!   scope 栈映射的类型）；syntect 未覆盖间隙由段逻辑天然补满；
//! - `token_type` 索引 = `syntax_highlighter.py:76-93` `TokenType(Enum)` 的
//!   精确顺序（KEYWORD=1 … WHITESPACE=16），见 [`token_type`] 模块；
//! - **逐语言回退路由**：应用语言在映射表中但 syntect 默认集不含其语法 →
//!   `Err(STATUS_UNSUPPORTED)`，Python 侧路由 Pygments（不许静默子集）；
//!   完全未知语言（不在映射表、无扩展名）→ `Ok(vec![])`（Python 保默认
//!   样式）；空文本/空语言 → `Ok(vec![])`；损坏输入不 panic。
//!
//! scope 栈 → TokenType 映射规则（参考 Pygments 语义，按优先级自上而下，
//! 每个 scope 从最具体（栈顶）到最通用检查，首个命中生效）：
//!
//! | 优先级 | scope 含子串 | TokenType |
//! |--------|--------------|-----------|
//! | 1 | `string` | STRING |
//! | 2 | `comment` | COMMENT |
//! | 3 | `numeric` | NUMBER |
//! | 4 | `keyword.operator` / `operator` | OPERATOR |
//! | 5 | `entity.name.function` | FUNCTION |
//! | 6 | `entity.name.type` / `support.type` / `storage.type` | CLASS_TYPE |
//! | 7 | `entity.name.tag` | TAG |
//! | 8 | `entity.other.attribute-name` | ATTRIBUTE |
//! | 9 | `constant.language` / `support.constant` | VALUE |
//! | 10 | `preprocessor` | PREPROCESSOR |
//! | 11 | `punctuation` | PUNCTUATION |
//! | 12 | `keyword` | KEYWORD |
//! | 13 | `variable` | VARIABLE |
//! | 14 | `constant` | CONSTANT |
//! | 15 | `function` | FUNCTION |
//! | 16 | `class` | CLASS_TYPE |
//! | 17 | `tag` | TAG |
//! | 18 | `attribute` | ATTRIBUTE |
//! | 19 | `whitespace` | WHITESPACE |
//! | 20 | 其余 | DEFAULT |

use std::sync::OnceLock;

use syntect::parsing::{ParseState, ScopeStack, ScopeStackOp, SyntaxSet};

use crate::STATUS_UNSUPPORTED;

/// TokenType 枚举索引 —— 与 `freeassetfilter/utils/syntax_highlighter.py:76-93`
/// `class TokenType(Enum)` 的 `auto()` 顺序**精确对齐**（Python 从 1 开始）。
///
/// 修改任何值时必须先核对 Python 侧枚举，禁止拍脑袋改索引。
pub mod token_type {
    pub const KEYWORD: u8 = 1; // 关键字
    pub const STRING: u8 = 2; // 字符串
    pub const NUMBER: u8 = 3; // 数字
    pub const COMMENT: u8 = 4; // 注释
    pub const FUNCTION: u8 = 5; // 函数名
    pub const CLASS_TYPE: u8 = 6; // 类名/类型
    pub const OPERATOR: u8 = 7; // 运算符
    pub const PUNCTUATION: u8 = 8; // 标点符号
    pub const VARIABLE: u8 = 9; // 变量
    pub const CONSTANT: u8 = 10; // 常量
    pub const TAG: u8 = 11; // XML/HTML 标签
    pub const ATTRIBUTE: u8 = 12; // 属性名
    pub const VALUE: u8 = 13; // 属性值
    pub const PREPROCESSOR: u8 = 14; // 预处理指令
    pub const DEFAULT: u8 = 15; // 默认文本
    pub const WHITESPACE: u8 = 16; // 空白字符
}

/// 单个高亮 span（**字符偏移**，非 byte）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TokenSpan {
    pub start: usize,
    pub len: usize,
    pub token_type: u8,
}

/// SyntaxSet 单例（`load_defaults_newlines()`，syntect feature `default-syntaxes`）。
static SYNTAX_SET: OnceLock<SyntaxSet> = OnceLock::new();

/// 取全局语法集（惰性初始化一次，线程安全）。
fn syntax_set() -> &'static SyntaxSet {
    SYNTAX_SET.get_or_init(SyntaxSet::load_defaults_newlines)
}

/// 应用语言名 → syntect 语法名 映射表。
///
/// 覆盖 `freeassetfilter/ui/layout/preview/text_previewer_layout.py:120-192`
/// `CODE_EXTENSIONS` 的**全部**应用语言。表中映射目标**不在 syntect 默认集内**
/// 的语言（`TypeScript`/`Visual Basic`/`SCSS`/`SASS`/`LESS`/`INI`/
/// `PowerShell`/`TOML`/`Swift`/`Kotlin`/`Vue`/`Svelte` 等）经
/// [`highlight_text_impl`] 返回 `Err(STATUS_UNSUPPORTED)`，Python 侧路由
/// Pygments——保证「逐语言回退路由、不许静默子集」。
fn language_to_syntax_name(app_lang: &str) -> Option<&'static str> {
    match app_lang {
        // C/C++ 系（text_previewer_layout: .c/.cpp/.cxx/.cc/.h/.hpp/.hxx）
        "c" => Some("C"),
        "cpp" => Some("C++"),
        "csharp" => Some("C#"),
        "java" => Some("Java"),
        "javascript" => Some("JavaScript"),
        // syntect 默认集不含 TypeScript → 路由 Pygments（-6）
        "typescript" => Some("TypeScript"),
        "python" => Some("Python"),
        "go" => Some("Go"),
        "rust" => Some("Rust"),
        "sql" => Some("SQL"),
        "php" => Some("PHP"),
        "r" => Some("R"),
        "lua" => Some("Lua"),
        // 不在 syntect 默认集 → 路由 Pygments（-6）
        "vb" => Some("Visual Basic"),
        // Web 前端
        "html" => Some("HTML"),
        "css" => Some("CSS"),
        // 不在 syntect 默认集 → 路由 Pygments（-6）
        "scss" => Some("SCSS"),
        "sass" => Some("SASS"),
        "less" => Some("LESS"),
        // 数据 / 标记
        "json" => Some("JSON"),
        "xml" => Some("XML"),
        "yaml" => Some("YAML"),
        "markdown" => Some("Markdown"),
        "rst" => Some("reStructuredText"),
        // 不在 syntect 默认集 → 路由 Pygments（-6）
        "toml" => Some("TOML"),
        "ini" => Some("INI"),
        // 脚本 / Shell
        // 默认集含 bash 专用语法 "Bourne Again Shell (bash)"（实测 dump）
        "bash" => Some("Bourne Again Shell (bash)"),
        "batch" => Some("Batch File"),
        // 不在 syntect 默认集 → 路由 Pygments（-6）
        "powershell" => Some("PowerShell"),
        // 其他
        "ruby" => Some("Ruby"),
        // 不在 syntect 默认集 → 路由 Pygments（-6）
        "swift" => Some("Swift"),
        "kotlin" => Some("Kotlin"),
        "vue" => Some("Vue"),
        "svelte" => Some("Svelte"),
        _ => None,
    }
}

/// 解析语言 → 语法：
/// 1. 映射表命中 → `find_syntax_by_name`；语法缺失 → `Err(STATUS_UNSUPPORTED)`
///    （Python 路由 Pygments）；
/// 2. 映射表未命中 → `find_syntax_by_extension(app_lang)`；
/// 3. 都未命中 → `Ok(None)`（未知语言，返回空 token，Python 保默认样式）。
fn resolve_syntax(language: &str) -> Result<Option<&'static syntect::parsing::SyntaxReference>, i32> {
    let ss = syntax_set();
    if let Some(name) = language_to_syntax_name(language) {
        return ss
            .find_syntax_by_name(name)
            .map(Some)
            .ok_or(STATUS_UNSUPPORTED);
    }
    Ok(ss.find_syntax_by_extension(language))
}

/// 高亮整块文本（span-only，不涉及颜色/主题）。
///
/// - `Ok(spans)`：spans 按 `start` 升序且连续覆盖全文（∑len == 文本字符数）；
///   未知语言 / 空文本 / 空语言 → `Ok(vec![])`；
/// - `Err(STATUS_UNSUPPORTED)`：应用语言映射命中但 syntect 默认集缺失其语法。
///
/// 不 panic：任何内部错误（语法解析失败等）都走兜底路径。
pub fn highlight_text_impl(language: &str, text: &str) -> Result<Vec<TokenSpan>, i32> {
    match resolve_syntax(language)? {
        None => Ok(Vec::new()),
        Some(syntax) => Ok(highlight_with_syntax(syntax, text)),
    }
}

/// 用指定语法高亮文本（逐行经 `ParseState`，跨行状态保持——多行注释/字符串
/// 正确贯穿）。
///
/// **行切分必须保留行尾 `\n`**：syntect 默认语法（Sublime schema）的注释
/// 上下文用 `$\n?`/`\n` 类模式在**行尾弹出**——若剥离 `\n` 再解析，注释
/// 上下文会在后续整行泄漏（全部行被映射为 COMMENT）。因此每行含换行符一起
/// 交给 `parse_line`，换行符也随段覆盖进 span（保证 ∑len == 文本字符数）。
fn highlight_with_syntax(syntax: &'static syntect::parsing::SyntaxReference, text: &str) -> Vec<TokenSpan> {
    let ss = syntax_set();
    let mut state = ParseState::new(syntax);
    let mut scope_stack = ScopeStack::new();
    let mut spans: Vec<TokenSpan> = Vec::new();
    let mut char_pos = 0usize;

    let mut rest = text;
    while !rest.is_empty() {
        // 按 '\n' 切行并**保留换行符**；最后一段可能无 '\n'。
        let (line, tail) = match rest.find('\n') {
            Some(idx) => (&rest[..=idx], &rest[idx + 1..]),
            None => (rest, ""),
        };
        rest = tail;

        match state.parse_line(line, ss) {
            Ok(ops) => process_ops(line, &ops, &mut scope_stack, &mut char_pos, &mut spans),
            // 损坏输入：整行 DEFAULT 兜底，不 panic。
            Err(_) => {
                if !line.is_empty() {
                    spans.push(TokenSpan {
                        start: char_pos,
                        len: line.chars().count(),
                        token_type: token_type::DEFAULT,
                    });
                    char_pos += line.chars().count();
                }
            }
        }
    }
    spans
}

/// 把 `ParseState::parse_line` 的 `(byte_offset, ScopeStackOp)` 变更序列翻译为
/// 字符偏移的 span 列表。语义与 syntect `RangedHighlightIterator` 一致：
/// **先以当前 scope 栈快照产出 `[byte_cursor, at)` 段，再应用该 op**；
/// 最后以行尾当前栈补 `[byte_cursor, content.len())`。
fn process_ops(
    content: &str,
    ops: &[(usize, ScopeStackOp)],
    scope_stack: &mut ScopeStack,
    char_pos: &mut usize,
    spans: &mut Vec<TokenSpan>,
) {
    let mut byte_cursor = 0usize;
    for (at, command) in ops {
        // 防御钳位：位置必须单调且在行内（损坏输入不 panic）。
        let end = (*at).clamp(byte_cursor, content.len());
        if end > byte_cursor {
            let seg = &content[byte_cursor..end];
            spans.push(TokenSpan {
                start: *char_pos,
                len: seg.chars().count(),
                token_type: scope_stack_to_token_type(scope_stack),
            });
            *char_pos += seg.chars().count();
        }
        // 应用 op（`ScopeStack::apply` 维护 push/pop/clear/restore）；错误忽略
        //（损坏输入不 panic，后续段用当前栈继续）。
        let _ = scope_stack.apply(command);
        byte_cursor = end;
    }
    if byte_cursor < content.len() {
        let seg = &content[byte_cursor..];
        spans.push(TokenSpan {
            start: *char_pos,
            len: seg.chars().count(),
            token_type: scope_stack_to_token_type(scope_stack),
        });
        *char_pos += seg.chars().count();
    }
}

/// scope 栈 → TokenType：从最具体（栈顶）到最通用（栈底）逐 scope 检查，
/// 首个命中返回；全栈未命中 → DEFAULT。
fn scope_stack_to_token_type(stack: &ScopeStack) -> u8 {
    for scope in stack.as_slice().iter().rev() {
        if let Some(ty) = scope_string_to_token_type(&scope.to_string()) {
            return ty;
        }
    }
    token_type::DEFAULT
}

/// 单个 scope 字符串 → TokenType（规则见模块文档，顺序即优先级）。
fn scope_string_to_token_type(s: &str) -> Option<u8> {
    if s.contains("string") {
        return Some(token_type::STRING);
    }
    if s.contains("comment") {
        return Some(token_type::COMMENT);
    }
    if s.contains("numeric") {
        return Some(token_type::NUMBER);
    }
    if s.contains("keyword.operator") || s.contains("operator") {
        return Some(token_type::OPERATOR);
    }
    if s.contains("entity.name.function") {
        return Some(token_type::FUNCTION);
    }
    if s.contains("entity.name.type") || s.contains("support.type") || s.contains("storage.type") {
        return Some(token_type::CLASS_TYPE);
    }
    if s.contains("entity.name.tag") {
        return Some(token_type::TAG);
    }
    if s.contains("entity.other.attribute-name") {
        return Some(token_type::ATTRIBUTE);
    }
    if s.contains("constant.language") || s.contains("support.constant") {
        return Some(token_type::VALUE);
    }
    if s.contains("preprocessor") {
        return Some(token_type::PREPROCESSOR);
    }
    if s.contains("punctuation") {
        return Some(token_type::PUNCTUATION);
    }
    if s.contains("keyword") {
        return Some(token_type::KEYWORD);
    }
    if s.contains("variable") {
        return Some(token_type::VARIABLE);
    }
    if s.contains("constant") {
        return Some(token_type::CONSTANT);
    }
    if s.contains("function") {
        return Some(token_type::FUNCTION);
    }
    if s.contains("class") {
        return Some(token_type::CLASS_TYPE);
    }
    if s.contains("tag") {
        return Some(token_type::TAG);
    }
    if s.contains("attribute") {
        return Some(token_type::ATTRIBUTE);
    }
    if s.contains("whitespace") {
        return Some(token_type::WHITESPACE);
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 把 spans 按 (start, len) 从原文切片并拼接——连续性 & 字符偏移的双重断言。
    fn reconstruct(text: &str, spans: &[TokenSpan]) -> String {
        let mut out = String::new();
        let mut cur = 0usize;
        for sp in spans {
            assert_eq!(
                sp.start, cur,
                "span 必须紧接前一段（无间隙）"
            );
            let seg: String = text.chars().skip(cur).take(sp.len).collect();
            out.push_str(&seg);
            cur += sp.len;
        }
        assert_eq!(cur, text.chars().count(), "spans 必须覆盖全文");
        out
    }

    fn assert_span_continuity(text: &str, spans: &[TokenSpan]) {
        let joined = reconstruct(text, spans);
        assert_eq!(joined, text, "join(span_text) 必须等于原文");
        // start/len 必须落在字符边界内。
        for sp in spans {
            assert!(sp.start <= text.chars().count());
            assert!(sp.start + sp.len <= text.chars().count());
            assert!(sp.len > 0);
        }
    }

    /// TokenType 索引与 Python `syntax_highlighter.py:76-93` 枚举顺序精确对齐。
    #[test]
    fn token_type_indices_match_python_enum_order() {
        assert_eq!(token_type::KEYWORD, 1);
        assert_eq!(token_type::STRING, 2);
        assert_eq!(token_type::NUMBER, 3);
        assert_eq!(token_type::COMMENT, 4);
        assert_eq!(token_type::FUNCTION, 5);
        assert_eq!(token_type::CLASS_TYPE, 6);
        assert_eq!(token_type::OPERATOR, 7);
        assert_eq!(token_type::PUNCTUATION, 8);
        assert_eq!(token_type::VARIABLE, 9);
        assert_eq!(token_type::CONSTANT, 10);
        assert_eq!(token_type::TAG, 11);
        assert_eq!(token_type::ATTRIBUTE, 12);
        assert_eq!(token_type::VALUE, 13);
        assert_eq!(token_type::PREPROCESSOR, 14);
        assert_eq!(token_type::DEFAULT, 15);
        assert_eq!(token_type::WHITESPACE, 16);
    }

    /// 映射表必须覆盖 CODE_EXTENSIONS（text_previewer_layout.py:120-192）的全部
    /// 应用语言（含路由 Pygments 的 -6 组）——「不许静默子集」。
    #[test]
    fn mapping_table_covers_all_code_extensions_languages() {
        for lang in [
            "python", "c", "cpp", "java", "javascript", "typescript", "csharp", "go", "rust",
            "sql", "php", "r", "lua", "vb", "html", "css", "scss", "sass", "less", "json",
            "xml", "bash", "batch", "powershell", "yaml", "ini", "toml", "markdown", "rst",
            "ruby", "swift", "kotlin", "vue", "svelte",
        ] {
            assert!(
                language_to_syntax_name(lang).is_some(),
                "应用语言 {lang} 必须在映射表中"
            );
        }
    }

    /// 高亮组语言：映射目标必须在 syntect 默认集内（否则测试会暴露假阴性路由）。
    /// 名字清单来自 `load_defaults_newlines()` 实测 dump（2026-09-13）。
    #[test]
    fn highlight_group_syntax_names_present_in_default_set() {
        let ss = syntax_set();
        for name in [
            "Python", "C", "C++", "Java", "JavaScript", "C#", "Go", "Rust",
            "SQL", "PHP", "R", "Lua", "HTML", "CSS", "JSON", "XML", "YAML",
            "Markdown", "reStructuredText", "Ruby", "Bourne Again Shell (bash)",
            "Batch File",
        ] {
            assert!(
                ss.find_syntax_by_name(name).is_some(),
                "syntect 默认集缺少高亮语法 {name}——映射表需修正或改走 -6 路由"
            );
        }
    }

    /// -6 路由组语言：映射目标**不在** syntect 默认集内（Python 侧走 Pygments）。
    #[test]
    fn unsupported_group_syntax_names_absent_from_default_set() {
        let ss = syntax_set();
        for name in [
            "TypeScript", "Visual Basic", "SCSS", "SASS", "LESS", "INI",
            "PowerShell", "TOML", "Swift", "Kotlin", "Vue", "Svelte",
        ] {
            assert!(
                ss.find_syntax_by_name(name).is_none(),
                "映射目标 {name} 意外出现在默认集——应回退 Pygments 而非静默高亮"
            );
        }
    }

    // ── 语言样本（tests/support/faf_core_fixtures/code_samples/ 的 Rust 内联版）──

    const PY: &str = "\"\"\"Parity sample: python.\"\"\"\n\
import os  # keyword: import\n\
\n\
CONSTANT = 42  # NUMBER 42\n\
\n\
def greet(name: str) -> str:\n\
    message = f\"hello {name}\"  # STRING f-string\n\
    if len(name) > 0:  # keyword: if\n\
        return message\n\
    return \"empty\"  # STRING\n";

    const JS: &str = "// Parity sample: javascript\n\
const MAX_RETRY = 3; // NUMBER 3\n\
\n\
function fetchData(url) {\n\
  const label = \"loading\"; // STRING\n\
  for (let i = 0; i < MAX_RETRY; i++) {\n\
    console.log(`${label}: ${url}`);\n\
  }\n\
  return null;\n\
}\n";

    const RS: &str = "// Parity sample: rust\n\
const LIMIT: u32 = 100; // NUMBER 100\n\
\n\
fn classify(n: u32) -> &'static str {\n\
    if n > LIMIT { // keyword: if\n\
        \"too big\" // STRING\n\
    } else {\n\
        \"ok\" // STRING\n\
    }\n\
}\n";

    /// span 连续性（ASCII 样本）+ KEYWORD/STRING/NUMBER/COMMENT 出现断言。
    #[test]
    fn python_spans_cover_full_text_with_key_tokens() {
        let spans = highlight_text_impl("python", PY).unwrap();
        assert_span_continuity(PY, &spans);
        let types: Vec<u8> = spans.iter().map(|s| s.token_type).collect();
        assert!(types.contains(&token_type::KEYWORD), "应出现 KEYWORD");
        assert!(types.contains(&token_type::STRING), "应出现 STRING");
        assert!(types.contains(&token_type::NUMBER), "应出现 NUMBER");
        assert!(types.contains(&token_type::COMMENT), "应出现 COMMENT");
    }

    #[test]
    fn javascript_spans_cover_full_text_with_key_tokens() {
        let spans = highlight_text_impl("javascript", JS).unwrap();
        assert_span_continuity(JS, &spans);
        let types: Vec<u8> = spans.iter().map(|s| s.token_type).collect();
        assert!(types.contains(&token_type::KEYWORD));
        assert!(types.contains(&token_type::STRING));
        assert!(types.contains(&token_type::NUMBER));
        assert!(types.contains(&token_type::COMMENT));
    }

    #[test]
    fn rust_spans_cover_full_text_with_key_tokens() {
        let spans = highlight_text_impl("rust", RS).unwrap();
        assert_span_continuity(RS, &spans);
        let types: Vec<u8> = spans.iter().map(|s| s.token_type).collect();
        assert!(types.contains(&token_type::KEYWORD));
        assert!(types.contains(&token_type::STRING));
        assert!(types.contains(&token_type::NUMBER));
        assert!(types.contains(&token_type::COMMENT));
    }

    /// 中文/emoji 多字节文本：span 必须按**字符偏移**连续覆盖全文。
    #[test]
    fn cjk_and_emoji_text_span_continuity() {
        let text = "// 中文注释：你好，世界 🚀 测试\n\
s = \"中文\" + \"🇨🇳\"  # 行尾中文\n\
# emoji 😀 in comment\n\
\n";
        let spans = highlight_text_impl("python", text).unwrap();
        assert_span_continuity(text, &spans);
    }

    /// 行尾/空行/制表符/无尾换行边界。
    #[test]
    fn line_endings_tabs_and_no_trailing_newline() {
        // 制表符 + 空行 + 结尾无换行。
        let text = "def f():\n\treturn 1\n\nx = 2";
        let spans = highlight_text_impl("python", text).unwrap();
        assert_span_continuity(text, &spans);
        // 空字符串。
        assert_eq!(highlight_text_impl("python", "").unwrap(), vec![]);
        // 只含换行。
        let spans = highlight_text_impl("python", "\n\n").unwrap();
        assert_span_continuity("\n\n", &spans);
        // CRLF。
        let text = "a = 1\r\nb = 2\r\n";
        let spans = highlight_text_impl("python", text).unwrap();
        assert_span_continuity(text, &spans);
    }

    /// 未知语言 → 空 token（Python 保默认样式）；空语言 → 空 token。
    #[test]
    fn unknown_language_returns_empty() {
        assert_eq!(highlight_text_impl("notalang", "hello").unwrap(), vec![]);
        assert_eq!(highlight_text_impl("", "hello").unwrap(), vec![]);
        assert_eq!(highlight_text_impl("notalang", "").unwrap(), vec![]);
    }

    /// 映射表内但 syntect 默认集缺失 → -6（Python 路由 Pygments）。
    #[test]
    fn mapped_but_missing_syntax_returns_unsupported() {
        for lang in [
            "typescript", "powershell", "kotlin", "swift", "vb", "scss", "vue", "svelte",
            "toml", "ini",
        ] {
            assert_eq!(
                highlight_text_impl(lang, "some text"),
                Err(STATUS_UNSUPPORTED),
                "语言 {lang} 应返回 -6 而非静默高亮"
            );
        }
    }

    /// 扩展名回退：不在映射表但扩展名可解析的语言（如 "lua"→Lua 语法）。
    #[test]
    fn extension_fallback_resolves_known_language() {
        // "lua" 在映射表中，这里用映射表外的语言名但可经扩展名解析。
        let spans = highlight_text_impl("Lua", "x = 1").unwrap_or_default();
        // 若 "Lua" 无扩展名解析则回退空；此处仅断言不 panic 且结果合法。
        let _ = spans;
        // 明确映射语言走扩展名同义路径：c 文件用扩展名 "h" 解析。
        let text = "int x = 1; // c\n";
        // "h" 不在映射表但扩展名存在 → 应高亮（非空）。
        let spans = highlight_text_impl("h", text).unwrap();
        assert_span_continuity(text, &spans);
        assert!(!spans.is_empty(), "扩展名 h 应解析到 C 语法");
    }

    /// 损坏/异常输入不 panic：控制字符、NUL、超长单行、仅空白。
    #[test]
    fn corrupted_input_does_not_panic() {
        let nasty = vec![
            "a\x00b".to_string(),
            "\t\t  \n  \n\t".to_string(),
            "\\\"'`${}".to_string(),
            format!("x = \"{}\"", "y".repeat(100_000)), // 超长单行
            "\u{feff}".to_string(),                     // BOM
        ];
        for text in nasty {
            let spans = highlight_text_impl("python", &text);
            if let Ok(spans) = spans {
                assert_span_continuity(&text, &spans);
            }
        }
        // 空/极短。
        assert_eq!(highlight_text_impl("python", "").unwrap(), vec![]);
        assert!(!highlight_text_impl("python", "x").unwrap().is_empty());
    }

    /// 多行注释/字符串跨行状态保持（ParseState 跨行）。
    #[test]
    fn multiline_string_and_comment_state_persists() {
        let text = "s = \"\"\"multi\nline\nstring\"\"\"\n# comment\nx = 1\n";
        let spans = highlight_text_impl("python", text).unwrap();
        assert_span_continuity(text, &spans);
        // 多行字符串内容行应以 STRING 为主。
        let string_types: usize = spans
            .iter()
            .filter(|s| s.token_type == token_type::STRING)
            .map(|s| s.len)
            .sum();
        assert!(string_types >= 15, "多行字符串应映射为 STRING（当前总长 {string_types}）");
    }

    /// FFI 往返：合法输入 → 非空指针 → JSON 数组可解析、连续性可复验。
    #[test]
    fn ffi_highlight_text_roundtrip() {
        use std::ffi::CStr;
        let lang = std::ffi::CString::new("python").unwrap();
        let text = std::ffi::CString::new(PY).unwrap();
        let raw = crate::faf_highlight_text(lang.as_ptr(), text.as_ptr());
        assert!(!raw.is_null(), "合法输入应返回非空指针");
        // SAFETY：raw 为 faf_highlight_text 刚分配的 NUL 终止串。
        let back = unsafe { CStr::from_ptr(raw) }.to_str().unwrap();
        let parsed: serde_json::Value = serde_json::from_str(back).expect("应可解析为 JSON");
        let arr = parsed.as_array().expect("应为 JSON 数组");
        assert!(!arr.is_empty());
        let spans: Vec<TokenSpan> = arr
            .iter()
            .map(|v| TokenSpan {
                start: v["start"].as_u64().unwrap() as usize,
                len: v["len"].as_u64().unwrap() as usize,
                token_type: v["token_type"].as_u64().unwrap() as u8,
            })
            .collect();
        assert_span_continuity(PY, &spans);
        // 对称释放。
        crate::faf_free_message(raw);
    }

    /// FFI 错误路径：null 指针 / 未知语言（空数组）/ 映射表外（null）→ 不崩溃。
    #[test]
    fn ffi_highlight_text_errors_return_null_or_empty() {
        use std::ffi::{CStr, CString};
        // null 指针 → null。
        assert!(crate::faf_highlight_text(std::ptr::null(), std::ptr::null()).is_null());
        let lang = CString::new("python").unwrap();
        assert!(crate::faf_highlight_text(lang.as_ptr(), std::ptr::null()).is_null());
        assert!(crate::faf_highlight_text(std::ptr::null(), lang.as_ptr()).is_null());
        // 非 UTF-8 → null。
        let bad = CString::new(vec![0xFFu8, 0xFE, b'x']).unwrap();
        assert!(crate::faf_highlight_text(bad.as_ptr(), bad.as_ptr()).is_null());
        // 未知语言 → 空数组 "[]"。
        let unknown = CString::new("notalang").unwrap();
        let raw = crate::faf_highlight_text(unknown.as_ptr(), lang.as_ptr());
        assert!(!raw.is_null());
        // SAFETY：raw 为刚分配的 NUL 终止串。
        let back = unsafe { CStr::from_ptr(raw) }.to_str().unwrap();
        assert_eq!(back, "[]");
        crate::faf_free_message(raw);
        // 映射表外语言（syntect 缺语法）→ null。
        let ps = CString::new("powershell").unwrap();
        assert!(crate::faf_highlight_text(ps.as_ptr(), lang.as_ptr()).is_null());
    }

    // ── 多语言真实样本（tests/support/faf_core_fixtures/code_samples/，include_str!
    //    编译期嵌入——无运行期文件 IO，样本固定不漂移）──────────────────────────

    /// (应用语言名, 真实样本, 必须出现的关键 token 类型)。
    ///
    /// - python / javascript / go / rust → KEYWORD/STRING/NUMBER/COMMENT
    ///   （与 todo 11 对拍一致）；
    /// - json → STRING/NUMBER（JSON 语法无 keyword scope，键名/数字字面量为主，
    ///   `true`/`false` 走 constant → VALUE，故不强求 KEYWORD/COMMENT）；
    /// - markdown → PUNCTUATION/CONSTANT（不强求 KEYWORD/STRING/NUMBER/COMMENT：
    ///   syntect 默认 Markdown 语法整文件路径不内嵌 fence 内容，见下方注释）。
    const FIXTURE_SAMPLES: &[(&str, &str, &[u8])] = &[
        (
            "python",
            include_str!("../../../../../../tests/support/faf_core_fixtures/code_samples/sample_python.py"),
            &[token_type::KEYWORD, token_type::STRING, token_type::NUMBER, token_type::COMMENT],
        ),
        (
            "javascript",
            include_str!("../../../../../../tests/support/faf_core_fixtures/code_samples/sample_javascript.js"),
            &[token_type::KEYWORD, token_type::STRING, token_type::NUMBER, token_type::COMMENT],
        ),
        (
            "go",
            include_str!("../../../../../../tests/support/faf_core_fixtures/code_samples/sample_go.go"),
            &[token_type::KEYWORD, token_type::STRING, token_type::NUMBER, token_type::COMMENT],
        ),
        (
            "rust",
            include_str!("../../../../../../tests/support/faf_core_fixtures/code_samples/sample_rust.rs"),
            &[token_type::KEYWORD, token_type::STRING, token_type::NUMBER, token_type::COMMENT],
        ),
        (
            "json",
            include_str!("../../../../../../tests/support/faf_core_fixtures/code_samples/sample_config.json"),
            &[token_type::STRING, token_type::NUMBER],
        ),
        (
            "markdown",
            include_str!("../../../../../../tests/support/faf_core_fixtures/code_samples/sample_doc.md"),
            // 实测（2026-09-14，syntect 5.3 默认 Markdown 语法）：整文件路径
            // **不内嵌 fence 内容**（fence 体为 DEFAULT），只产出 PUNCTUATION
            // （`#` 标题标记 / ``` 围栏标记）+ CONSTANT（fence info 语言名
            // `python`）。STRING/NUMBER/COMMENT 由 markdown.rs 的逐 fence 路径
            // （对 fence 内容调 highlight_text_impl("python", …)）产出。
            &[token_type::PUNCTUATION, token_type::CONSTANT],
        ),
    ];

    /// 6 语言真实样本：join(span)==原文（字符偏移）、关键 token 类型出现、
    /// spans 升序且互不重叠（连续覆盖全文）。
    #[test]
    fn fixture_samples_six_languages_cover_full_text() {
        for (lang, src, must_types) in FIXTURE_SAMPLES {
            let spans = highlight_text_impl(lang, src)
                .unwrap_or_else(|code| panic!("语言 {lang} 不应返回错误（code {code}）"));
            assert_span_continuity(src, &spans);
            // spans 显式复验：严格升序且互不重叠（连续性已隐含，此处独立断言）。
            for w in spans.windows(2) {
                assert!(
                    w[0].start + w[0].len <= w[1].start,
                    "语言 {lang} 的 spans 必须升序且不重叠（{w:?}）"
                );
            }
            let types: std::collections::HashSet<u8> =
                spans.iter().map(|s| s.token_type).collect();
            for need in *must_types {
                assert!(
                    types.contains(need),
                    "语言 {lang} 应出现 token_type {need}（实际: {types:?}）"
                );
            }
        }
    }

    /// 行尾/空行/制表符精确边界（plan todo 12 枚举字面量）：
    /// `"code\n"`（结尾换行）、`"\n\n\n"`（连续空行）、`"\tindent"`（tab 缩进）、
    /// `"a\r\nb"`（CRLF）、`"single"`（无换行结尾）——不 panic、连续性成立、
    /// 换行符计入 span（∑len==字符数，`assert_span_continuity` 隐含断言）。
    #[test]
    fn line_ending_edge_cases_do_not_panic() {
        for text in ["code\n", "\n\n\n", "\tindent", "a\r\nb", "single"] {
            let spans = highlight_text_impl("python", text)
                .unwrap_or_else(|code| panic!("文本 {text:?} 不应返回错误（code {code}）"));
            assert_span_continuity(text, &spans);
            // 含换行的输入：换行符必须被某段覆盖。
            if text.contains('\n') {
                let covered: usize = spans.iter().map(|s| s.len).sum();
                assert_eq!(covered, text.chars().count(), "换行必须计入 span");
            }
        }
    }
}
