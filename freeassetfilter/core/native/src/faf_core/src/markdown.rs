//! `markdown.rs` —— Markdown 渲染（todo 15：`faf_render_markdown`）。
//!
//! 语义 oracle：`freeassetfilter/utils/markdown_renderer.py`（Python 侧
//! python-markdown 现状）。本模块产出 **body 片段**（不含 `<html>/<head>`），
//! 由 FFI 包装为 `{"html": "<body 片段>"}`。
//!
//! 设计契约（C4 / todo 15 明文）：
//! - pulldown-cmark 选项：`ENABLE_TABLES | ENABLE_FOOTNOTES |
//!   ENABLE_TASKLISTS | ENABLE_STRIKETHROUGH`；**不启用**
//!   `ENABLE_HEADING_ATTRIBUTES`（heading-id 重写归 Python 侧共享后处理，
//!   见 todo 17）；不启用 `ENABLE_GFM`/`ENABLE_DEFINITION_LIST`/math 等
//!   新扩展（降级映射见 todo 17 扩展映射表）。
//! - **主题不跨界**：输出 HTML 不含任何颜色/CSS/`style` 属性（主题 CSS 由
//!   Python `_build_css` 注入）。
//! - fenced code 块（含语言标记）→ `<pre><code class="highlight">` 内逐 token
//!   `<span class="tok-<TYPE_NAME>">`（TYPE_NAME = `token_type` 索引对应的
//!   Python 枚举名，如 `tok-KEYWORD`）；syntect 内嵌经
//!   [`highlight::highlight_text_impl`] 复用（todo 11 交付的 SyntaxSet 单例 +
//!   token_type 模块）。无语言标记的 fence / 缩进代码块 → 纯 escaped 文本。
//! - 降级：admonition（`!!! note`）/def_list/abbr/toc 语法 pulldown-cmark
//!   不解析 → 按普通段落/原文渲染（与 todo 17 映射表一致），Rust 侧不实现
//!   新扩展。
//! - **不 panic**：损坏输入（未闭合 fence/截断/任意文本）返回可渲染 body；
//!   内部任何意外走兜底路径。
//! - 结构细节对齐 Python oracle（normalize_html.py 忽略 `id`/`class` 差异后
//!   核心元素等价）：任务列表 `<span class="task-checkbox checked">☑</span>`、
//!   脚注 `<sup><a href="#fn:{name}">N</a></sup>` + 末尾
//!   `<div class="footnote"><hr /><ol>…</ol></div>`、表格
//!   `<table><thead><tr><th>…</thead><tbody>…</tbody></table>`。

use std::collections::HashMap;

use pulldown_cmark::{
    Alignment, CodeBlockKind, Event, Options, Parser, Tag, TagEnd,
};

use crate::highlight::{TokenSpan, highlight_text_impl, token_type};

/// pulldown-cmark 选项（todo 15 明文四件套，heading-attributes 归 Python 后处理）。
/// bitflags 的 `BitOr` 非 const（bitflags 2.x），故用函数返回。
fn markdown_options() -> Options {
    Options::ENABLE_TABLES
        | Options::ENABLE_FOOTNOTES
        | Options::ENABLE_TASKLISTS
        | Options::ENABLE_STRIKETHROUGH
}

/// `token_type` 数字 → Python 枚举名（与 `syntax_highlighter.py` `TokenType`
/// 枚举 `name` 精确对齐），用于 `<span class="tok-<NAME>">`。
fn token_type_name(id: u8) -> &'static str {
    match id {
        token_type::KEYWORD => "KEYWORD",
        token_type::STRING => "STRING",
        token_type::NUMBER => "NUMBER",
        token_type::COMMENT => "COMMENT",
        token_type::FUNCTION => "FUNCTION",
        token_type::CLASS_TYPE => "CLASS_TYPE",
        token_type::OPERATOR => "OPERATOR",
        token_type::PUNCTUATION => "PUNCTUATION",
        token_type::VARIABLE => "VARIABLE",
        token_type::CONSTANT => "CONSTANT",
        token_type::TAG => "TAG",
        token_type::ATTRIBUTE => "ATTRIBUTE",
        token_type::VALUE => "VALUE",
        token_type::PREPROCESSOR => "PREPROCESSOR",
        token_type::DEFAULT => "DEFAULT",
        token_type::WHITESPACE => "WHITESPACE",
        _ => "DEFAULT",
    }
}

/// HTML 转义（文本与属性共用）：`&` `<` `>` `"`。不 panic。
fn escape_html(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            _ => out.push(c),
        }
    }
    out
}

/// fenced code 上下文。
#[derive(Default)]
struct CodeBlockCtx {
    lang: String,
    buf: String,
}

/// image 上下文（alt 文本来自子内容）。
struct ImageCtx {
    dest_url: String,
    title: String,
    alt: String,
}

/// 事件流 → body HTML 的单遍渲染器。
///
/// 脚注定义内容先收集（`footnote_defs`），文档末尾统一按 python 的
/// `<div class="footnote"><hr /><ol>…</ol></div>` 形态输出。
struct MarkdownHtml {
    out: String,
    /// 脚注名 → 序号（按首次引用顺序，python-markdown 语义）。
    footnote_numbers: HashMap<String, usize>,
    /// 脚注名 → 引用次数（每个引用一个 backref）。
    footnote_counts: HashMap<String, usize>,
    /// 脚注名 → 已渲染的引用计数（决定 `fnref:` / `fnref2:` / … 后缀，
    /// 与 python-markdown 多引用 disambiguation 一致）。
    footnote_ref_idx: HashMap<String, usize>,
    /// (脚注名, 已渲染内容)。
    footnote_defs: Vec<(String, String)>,
    /// 正在收集的脚注定义索引。
    active_def: Option<usize>,
    /// 当前代码块（fenced 内容收集完整后统一高亮）。
    code_block: Option<CodeBlockCtx>,
    /// 表格列对齐信息。
    table_aligns: Vec<Alignment>,
    table_col: usize,
    in_table_head: bool,
    /// 当前 image（收集 alt）。
    image: Option<ImageCtx>,
}

impl MarkdownHtml {
    fn new(
        footnote_numbers: HashMap<String, usize>,
        footnote_counts: HashMap<String, usize>,
    ) -> Self {
        Self {
            out: String::new(),
            footnote_numbers,
            footnote_counts,
            footnote_ref_idx: HashMap::new(),
            footnote_defs: Vec::new(),
            active_def: None,
            code_block: None,
            table_aligns: Vec::new(),
            table_col: 0,
            in_table_head: false,
            image: None,
        }
    }

    /// 主输出 / 当前脚注定义缓冲 二选一写入。
    fn write(&mut self, s: &str) {
        if let Some(idx) = self.active_def {
            if let Some((_, buf)) = self.footnote_defs.get_mut(idx) {
                buf.push_str(s);
                return;
            }
        }
        self.out.push_str(s);
    }

    fn footnote_number(&self, name: &str) -> usize {
        self.footnote_numbers
            .get(name)
            .copied()
            .unwrap_or(self.footnote_numbers.len() + 1)
    }

    fn handle_event(&mut self, ev: Event) {
        match ev {
            Event::Start(tag) => self.handle_start(tag),
            Event::End(tag) => {
                if matches!(tag, TagEnd::Image) && self.image.is_some() {
                    self.finish_image();
                    return;
                }
                self.handle_end(tag);
            }
            Event::Text(t) => {
                if let Some(img) = self.image.as_mut() {
                    img.alt.push_str(&t);
                    return;
                }
                if let Some(cb) = self.code_block.as_mut() {
                    cb.buf.push_str(&t);
                    return;
                }
                self.write(&escape_html(&t));
            }
            Event::Code(c) => {
                self.write("<code>");
                self.write(&escape_html(&c));
                self.write("</code>");
            }
            Event::FootnoteReference(name) => {
                let num = self.footnote_number(&name);
                // python-markdown 多引用 disambiguation：首次引用 `fnref:{name}`，
                // 之后 `fnref2:{name}` / `fnref3:{name}` …（backref 据此定位）。
                let idx = self.footnote_ref_idx.entry(name.to_string()).or_insert(0);
                *idx += 1;
                let suffix = if *idx == 1 {
                    String::new()
                } else {
                    idx.to_string()
                };
                self.write(&format!(
                    "<sup id=\"fnref{}:{}\"><a href=\"#fn:{}\">{}</a></sup>",
                    suffix,
                    escape_html(&name),
                    escape_html(&name),
                    num
                ));
            }
            Event::SoftBreak => self.write("\n"),
            Event::HardBreak => self.write("<br />"),
            Event::Rule => self.write("<hr />"),
            Event::TaskListMarker(checked) => {
                if checked {
                    self.write("<span class=\"task-checkbox checked\">\u{2611}</span>");
                } else {
                    self.write("<span class=\"task-checkbox unchecked\">\u{2610}</span>");
                }
            }
            // 原始 HTML 透传（与 python-markdown 一致：markdown 文本可含 raw HTML）。
            Event::Html(h) | Event::InlineHtml(h) => self.write(&h),
            // 未启用扩展对应的变体：忽略（不 panic）。
            Event::InlineMath(_) | Event::DisplayMath(_) => {}
        }
    }

    fn handle_start(&mut self, tag: Tag) {
        match tag {
            Tag::Paragraph => self.write("<p>"),
            Tag::Heading { level, .. } => self.write(&format!("<h{}>", level as u8)),
            Tag::BlockQuote(_) => self.write("<blockquote>"),
            Tag::CodeBlock(kind) => {
                self.write("<pre><code class=\"highlight\">");
                self.code_block = Some(match kind {
                    CodeBlockKind::Fenced(info) => {
                        let lang = info.split(' ').next().unwrap_or("").trim().to_string();
                        CodeBlockCtx { lang, buf: String::new() }
                    }
                    CodeBlockKind::Indented => CodeBlockCtx {
                        lang: String::new(),
                        buf: String::new(),
                    },
                });
            }
            Tag::HtmlBlock => {}
            Tag::List(Some(start)) => {
                if start == 1 {
                    self.write("<ol>");
                } else {
                    self.write(&format!("<ol start=\"{}\">", start));
                }
            }
            Tag::List(None) => self.write("<ul>"),
            Tag::Item => self.write("<li>"),
            Tag::FootnoteDefinition(name) => {
                self.footnote_defs.push((name.to_string(), String::new()));
                self.active_def = Some(self.footnote_defs.len() - 1);
            }
            Tag::Table(aligns) => {
                self.table_aligns = aligns;
                self.table_col = 0;
                self.write("<table>");
            }
            Tag::TableHead => {
                self.in_table_head = true;
                // pulldown-cmark 的表头事件流不含 `TableRow`（默认渲染器把
                // `<tr>` 随 `<thead>` 一并输出）——此处对齐该语义与 Python oracle。
                self.write("<thead><tr>");
            }
            Tag::TableRow => {
                self.table_col = 0;
                self.write("<tr>");
            }
            Tag::TableCell => {
                let align = self.table_aligns.get(self.table_col).copied();
                self.table_col += 1;
                let tag = if self.in_table_head { "th" } else { "td" };
                match align {
                    Some(Alignment::Left) => self.write(&format!("<{tag} align=\"left\">")),
                    Some(Alignment::Center) => self.write(&format!("<{tag} align=\"center\">")),
                    Some(Alignment::Right) => self.write(&format!("<{tag} align=\"right\">")),
                    _ => self.write(&format!("<{tag}>")),
                }
            }
            Tag::Emphasis => self.write("<em>"),
            Tag::Strong => self.write("<strong>"),
            Tag::Strikethrough => self.write("<del>"),
            Tag::Link { dest_url, title, .. } => {
                let mut s = format!("<a href=\"{}\"", escape_html(&dest_url));
                if !title.is_empty() {
                    s.push_str(&format!(" title=\"{}\"", escape_html(&title)));
                }
                s.push('>');
                self.write(&s);
            }
            Tag::Image { dest_url, title, .. } => {
                self.image = Some(ImageCtx {
                    dest_url: dest_url.to_string(),
                    title: title.to_string(),
                    alt: String::new(),
                });
            }
            // 未启用扩展：忽略，内容仍会照常渲染（降级为普通文本）。
            Tag::Superscript
            | Tag::Subscript
            | Tag::MetadataBlock(_)
            | Tag::DefinitionList
            | Tag::DefinitionListTitle
            | Tag::DefinitionListDefinition => {}
        }
    }

    fn handle_end(&mut self, tag: TagEnd) {
        match tag {
            TagEnd::Paragraph => self.write("</p>"),
            TagEnd::Heading(level) => self.write(&format!("</h{}>", level as u8)),
            TagEnd::BlockQuote(_) => self.write("</blockquote>"),
            TagEnd::CodeBlock => {
                if let Some(ctx) = self.code_block.take() {
                    if !ctx.lang.is_empty() {
                        match highlight_text_impl(&ctx.lang, &ctx.buf) {
                            Ok(spans) if !spans.is_empty() => {
                                self.write_highlighted(&ctx.buf, &spans)
                            }
                            _ => self.write(&escape_html(&ctx.buf)),
                        }
                    } else {
                        self.write(&escape_html(&ctx.buf));
                    }
                }
                self.write("</code></pre>");
            }
            TagEnd::HtmlBlock => {}
            TagEnd::List(is_ordered) => {
                if is_ordered {
                    self.write("</ol>");
                } else {
                    self.write("</ul>");
                }
            }
            TagEnd::Item => self.write("</li>"),
            TagEnd::FootnoteDefinition => {
                self.active_def = None;
            }
            TagEnd::Table => self.write("</tbody></table>"),
            TagEnd::TableHead => {
                self.in_table_head = false;
                self.write("</tr></thead><tbody>");
            }
            TagEnd::TableRow => self.write("</tr>"),
            TagEnd::TableCell => {
                if self.in_table_head {
                    self.write("</th>");
                } else {
                    self.write("</td>");
                }
            }
            TagEnd::Emphasis => self.write("</em>"),
            TagEnd::Strong => self.write("</strong>"),
            TagEnd::Strikethrough => self.write("</del>"),
            TagEnd::Link => self.write("</a>"),
            TagEnd::Image => self.finish_image(),
            TagEnd::Superscript
            | TagEnd::Subscript
            | TagEnd::MetadataBlock(_)
            | TagEnd::DefinitionList
            | TagEnd::DefinitionListTitle
            | TagEnd::DefinitionListDefinition => {}
        }
    }

    fn finish_image(&mut self) {
        if let Some(img) = self.image.take() {
            let mut s = format!(
                "<img alt=\"{}\" src=\"{}\"",
                escape_html(&img.alt),
                escape_html(&img.dest_url)
            );
            if !img.title.is_empty() {
                s.push_str(&format!(" title=\"{}\"", escape_html(&img.title)));
            }
            s.push_str(" />");
            self.write(&s);
        }
    }

    /// 把 syntect span 列表写成 `<span class="tok-<TYPE>">escaped</span>` 序列。
    ///
    /// span 为**字符偏移**且连续覆盖全文（highlight.rs 保证）；纯空白 span
    /// 跳过（对齐 Pygments 的裸空白行为，normalize 后等价）；**相邻同类型
    /// span 合并**（syntect 会把 `#` 与 ` COMMENT` 拆成相邻同类 span，而
    /// Pygments 是单个 span——合并后结构与 python-markdown oracle 对齐，
    /// 文本内容不变）。任何越界视为损坏输入 → 只输出已安全部分，不 panic。
    fn write_highlighted(&mut self, buf: &str, spans: &[TokenSpan]) {
        let mut bounds = Vec::with_capacity(buf.chars().count() + 1);
        let mut b = 0usize;
        for c in buf.chars() {
            bounds.push(b);
            b += c.len_utf8();
        }
        bounds.push(b);
        // 先过滤纯空白 span，再合并相邻同类型 span。
        let mut merged: Vec<TokenSpan> = Vec::new();
        for sp in spans {
            let start = sp.start;
            let end = start + sp.len;
            if end >= bounds.len() {
                break;
            }
            let seg = &buf[bounds[start]..bounds[end]];
            if seg.chars().all(|c| c.is_whitespace()) {
                continue;
            }
            if let Some(prev) = merged.last_mut() {
                if prev.token_type == sp.token_type && prev.start + prev.len == sp.start {
                    prev.len += sp.len;
                    continue;
                }
            }
            merged.push(*sp);
        }
        for sp in merged {
            let seg = &buf[bounds[sp.start]..bounds[sp.start + sp.len]];
            self.write(&format!(
                "<span class=\"tok-{}\">{}</span>",
                token_type_name(sp.token_type),
                escape_html(seg)
            ));
        }
    }

    /// 收尾：追加脚注定义区（python-markdown `<div class="footnote">` 形态）。
    fn finish(mut self) -> String {
        if !self.footnote_defs.is_empty() {
            self.write("<div class=\"footnote\">\n<hr />\n<ol>\n");
            let defs: Vec<(String, String)> = self.footnote_defs.clone();
            for (name, content) in defs {
                let num = self.footnote_number(&name);
                let count = self.footnote_counts.get(&name).copied().unwrap_or(0).max(1);
                // python-markdown backref 列表：首个 `#fnref:{name}`，后续按
                // `#fnref{i}:{name}`（i=2,3,…）指向各引用 sup。
                let backrefs: String = (1..=count)
                    .map(|i| {
                        let href = if i == 1 {
                            format!("#fnref:{}", escape_html(&name))
                        } else {
                            format!("#fnref{}:{}", i, escape_html(&name))
                        };
                        format!(
                            "<a class=\"footnote-backref\" href=\"{}\" title=\"Jump back to footnote {} in the text\">\u{21A9}</a>",
                            href, num
                        )
                    })
                    .collect();
                let insert = format!("\u{00A0}{}", backrefs);
                let li_content = match content.find("</p>") {
                    Some(idx) => {
                        format!("{}{}{}", &content[..idx], insert, &content[idx..])
                    }
                    None => format!("{}{}", content, insert),
                };
                self.write(&format!(
                    "<li id=\"fn:{}\">\n{}\n</li>\n",
                    escape_html(&name),
                    li_content
                ));
            }
            self.write("</ol>\n</div>");
        }
        self.out
    }
}

/// 渲染 markdown 文本为 **body 片段**（不含 `<html>/<head>`，不含任何颜色/CSS）。
///
/// - `Ok(body)`：任何输入（含空文本、未闭合 fence、截断、任意垃圾）都返回
///   可渲染 body，不 panic；
/// - `Err(_)`：预留错误路径（当前实现不会触发；保留签名供上层统一处理）。
pub fn render_markdown_impl(text: &str) -> Result<String, i32> {
    let events: Vec<Event> = Parser::new_ext(text, markdown_options()).collect();
    // pass 1：脚注序号（按首次引用顺序）与引用计数。
    let mut footnote_numbers: HashMap<String, usize> = HashMap::new();
    let mut footnote_counts: HashMap<String, usize> = HashMap::new();
    for ev in &events {
        if let Event::FootnoteReference(name) = ev {
            let name_s = name.to_string();
            *footnote_counts.entry(name_s.clone()).or_insert(0) += 1;
            if !footnote_numbers.contains_key(&name_s) {
                footnote_numbers.insert(name_s, footnote_numbers.len() + 1);
            }
        }
    }
    let mut renderer = MarkdownHtml::new(footnote_numbers, footnote_counts);
    for ev in events {
        renderer.handle_event(ev);
    }
    Ok(renderer.finish())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn render(text: &str) -> String {
        render_markdown_impl(text).expect("渲染不应失败")
    }

    /// 标题 h1-h6。
    #[test]
    fn headings_all_levels() {
        let md = "# h1\n## h2\n### h3\n#### h4\n##### h5\n###### h6\n";
        let out = render(md);
        for level in 1..=6 {
            assert!(
                out.contains(&format!("<h{level}>h{level}</h{level}>")),
                "缺少 <h{level}>：{out}"
            );
        }
    }

    /// 段落 / 粗体 / 斜体 / 行内代码 / 删除线。
    #[test]
    fn paragraph_bold_italic_code_strikethrough() {
        let out = render("**加粗**与*斜体*与`code`与~~删除~~");
        assert!(out.contains("<p>"));
        assert!(out.contains("<strong>加粗</strong>"));
        assert!(out.contains("<em>斜体</em>"));
        assert!(out.contains("<code>code</code>"));
        assert!(out.contains("<del>删除</del>"));
        assert!(out.contains("</p>"));
    }

    /// 表格结构：thead/th + tbody/td。
    #[test]
    fn table_structure() {
        let md = "| 名称 Name | 类型 Type |\n| --- | --- |\n| alpha | 文件 |\n";
        let out = render(md);
        assert!(out.contains("<table>"));
        assert!(out.contains("<thead>"));
        assert!(out.contains("<th>名称 Name</th>"));
        assert!(out.contains("</thead><tbody>"));
        assert!(out.contains("<td>alpha</td>"));
        assert!(out.contains("</tbody></table>"));
        // 无对齐声明 → 无 align 属性。
        assert!(!out.contains("align="), "无对齐不应输出 align：{out}");
    }

    /// 表格对齐：`:---`/`:---:`/`---:` → align 属性。
    #[test]
    fn table_alignment_attributes() {
        let md = "| a | b | c |\n| :--- | :---: | ---: |\n| 1 | 2 | 3 |\n";
        let out = render(md);
        assert!(out.contains("<th align=\"left\">a</th>"));
        assert!(out.contains("<th align=\"center\">b</th>"));
        assert!(out.contains("<th align=\"right\">c</th>"));
    }

    /// fenced code + 语言 → `<pre><code class="highlight">` + `tok-<TYPE>` span；
    /// 内容 HTML 转义（`<script>` 不得原样注入）。
    #[test]
    fn fenced_code_with_language_highlight_spans() {
        let md = "```python\n# COMMENT\nprint(\"hi\")\n```\n";
        let out = render(md);
        assert!(out.contains("<pre><code class=\"highlight\">"), "{out}");
        assert!(out.contains("</code></pre>"), "{out}");
        assert!(out.contains("tok-COMMENT"), "应含 COMMENT token：{out}");
        assert!(out.contains("tok-STRING"), "应含 STRING token：{out}");
        assert!(!out.contains("<script"), "代码内容必须转义：{out}");
        assert!(out.contains("&quot;"), "双引号必须转义：{out}");
    }

    /// 相邻同类型 span 合并：`#` 与 ` COMMENT` 应合并为一个 COMMENT span
    /// （对齐 Pygments 单 span，normalized diff 缩小）。
    #[test]
    fn fenced_code_adjacent_same_type_spans_merged() {
        let md = "```python\n# COMMENT\n```\n";
        let out = render(md);
        assert!(
            out.contains("<span class=\"tok-COMMENT\"># COMMENT"),
            "相邻同类型 span 应合并：# COMMENT 单 span：{out}"
        );
        assert!(
            !out.contains("#</span>"),
            "不应出现同类型 span 拆分的 `#</span>`：{out}"
        );
    }

    /// 无语言标记的 fence → 纯 escaped，无 span。
    #[test]
    fn fenced_code_without_language_plain_escaped() {
        let md = "```\nplain <fence> & text\n```\n";
        let out = render(md);
        assert!(out.contains("<pre><code class=\"highlight\">"));
        assert!(!out.contains("tok-"), "无语言不应内嵌 token：{out}");
        assert!(out.contains("plain &lt;fence&gt; &amp; text"), "{out}");
    }

    /// fenced 语言标记解析：info 串取首个空白分词。
    #[test]
    fn fenced_language_parsing_first_token() {
        let md = "```python linenums=\"1\"\nx = 1\n```\n";
        let out = render(md);
        assert!(out.contains("tok-"), "应解析出 python 语言：{out}");
    }

    /// 未知语言 → 纯 escaped（不 panic、无 span）。
    #[test]
    fn fenced_unknown_language_plain_escaped() {
        let md = "```notalangxyz\nsome text\n```\n";
        let out = render(md);
        assert!(out.contains("<pre><code class=\"highlight\">"));
        assert!(!out.contains("tok-"), "未知语言不应内嵌 token：{out}");
    }

    /// 任务列表 → ☑/☐ 复选框 span。
    #[test]
    fn task_list_checkboxes() {
        let md = "- [x] 已完成\n- [ ] 待办\n";
        let out = render(md);
        assert!(out.contains("<ul>"), "{out}");
        assert!(out.contains("<span class=\"task-checkbox checked\">\u{2611}</span>"));
        assert!(out.contains("<span class=\"task-checkbox unchecked\">\u{2610}</span>"));
        assert!(out.contains("已完成"));
        assert!(out.contains("待办"));
    }

    /// 无序/有序列表 + 嵌套。
    #[test]
    fn ordered_and_unordered_lists() {
        let out = render("- a\n- b\n  - nested\n\n1. one\n2. two\n");
        assert!(out.contains("<ul>"));
        assert!(out.contains("<ol>"));
        assert!(out.contains("<li>a</li>"));
        assert!(out.contains("<li>one</li>"));
        // 2 空格缩进嵌套项 → pulldown 内嵌 <ul>（CommonMark 行为）。
        assert!(out.contains("<li>b<ul><li>nested</li></ul></li>"), "{out}");
    }

    /// 有序列表非 1 起始 → `start` 属性。
    #[test]
    fn ordered_list_start_attribute() {
        let out = render("3. three\n4. four\n");
        assert!(out.contains("<ol start=\"3\">"), "{out}");
        assert!(out.contains("<li>three</li>"));
    }

    /// 引用块。
    #[test]
    fn blockquote() {
        let out = render("> 引用第一行\n> 引用第二行\n");
        assert!(out.contains("<blockquote>"));
        assert!(out.contains("</blockquote>"));
        assert!(out.contains("<p>引用第一行"));
        assert!(out.contains("引用第二行"));
    }

    /// 脚注：正文 `<sup><a href="#fn:...">N</a></sup>` + 末尾 footnote 区。
    #[test]
    fn footnotes_reference_and_definition_section() {
        let md = "正文引用[^1]与[^note]。\n\n[^1]: 脚注一 one.\n[^note]: 脚注二 two.\n";
        let out = render(md);
        assert!(out.contains("<sup id=\"fnref:1\"><a href=\"#fn:1\">1</a></sup>"), "{out}");
        assert!(out.contains("<sup id=\"fnref:note\"><a href=\"#fn:note\">2</a></sup>"), "{out}");
        assert!(out.contains("<div class=\"footnote\">"));
        assert!(out.contains("<hr />"));
        assert!(out.contains("<li id=\"fn:1\">"));
        assert!(out.contains("脚注一 one."));
        assert!(out.contains("脚注二 two."));
        assert!(out.contains("footnote-backref"));
        assert!(out.contains("\u{21A9}"), "backref 箭头 ↩");
    }

    /// 脚注多引用：python-markdown 语义 —— 首次引用 `fnref:`，后续 `fnref2:`；
    /// backref 列表 `#fnref:` + `#fnref2:` 分别指向各引用。
    #[test]
    fn footnote_multi_reference_disambiguation_suffixes() {
        let md = "引用[^a]两次[^a]。\n\n[^a]: 脚注 a.\n";
        let out = render(md);
        // 首次引用 → fnref:a；第二次 → fnref2:a。
        assert!(out.contains("<sup id=\"fnref:a\">"), "{out}");
        assert!(out.contains("<sup id=\"fnref2:a\">"), "{out}");
        // backref 列表：[fnref:a, fnref2:a]。
        assert!(out.contains("href=\"#fnref:a\""), "{out}");
        assert!(out.contains("href=\"#fnref2:a\""), "{out}");
        assert!(!out.contains("fnref3"), "{out}");
    }

    /// 链接 + 图片。
    #[test]
    fn links_and_images() {
        let out = render("[示例](https://example.com) ![图](https://e.com/i.png)");
        assert!(out.contains("<a href=\"https://example.com\">示例</a>"), "{out}");
        assert!(
            out.contains("<img alt=\"图\" src=\"https://e.com/i.png\" />"),
            "{out}"
        );
        // 属性转义。
        let out2 = render(r#"[a](https://e.com/?q="x"&y=1)"#);
        assert!(out2.contains("&quot;x&quot;"), "{out2}");
    }

    /// 链接 title。
    #[test]
    fn link_title_attribute() {
        let out = render(r#"[a](https://e.com "the title")"#);
        assert!(out.contains("title=\"the title\""), "{out}");
    }

    /// 空文本 → 空 body（Ok 且非 panic）。
    #[test]
    fn empty_text_renders_empty_body() {
        assert_eq!(render(""), "");
        assert_eq!(render("\n\n\n"), "");
        assert_eq!(render("   "), "");
    }

    /// 损坏输入不 panic：未闭合 fence、截断表格、孤引用、任意垃圾。
    #[test]
    fn corrupted_input_does_not_panic() {
        let nasty = vec![
            "```python\nunclosed fence".to_string(),
            "```\n```\n``".to_string(),
            "| a | b\n| --- |\n| 1".to_string(),
            "[^1]: orphan def".to_string(),
            "正文引用[^missing]未定义".to_string(),
            "# 标题\n- [x] 任务\n> 引用\n\n```\ncode".to_string(),
            "![img](https://e.com".to_string(),
            "[link](https://e.com".to_string(),
            "a\x00b".to_string(),
            "<div markdown=\"1\">\n**x**\n".to_string(),
            format!("{}", "x".repeat(100_000)), // 超长
        ];
        for text in nasty {
            let out = render(&text);
            assert!(!out.contains("tok-UNKNOWN"), "未知 token 类型不应出现：{out}");
        }
        // 未闭合 fence 不应 panic，且应产出可渲染的 pre/code。
        assert!(render("```python\ncode\n").contains("<pre><code"));
    }

    /// HTML 注入防护：`<script>`/`<img onerror>` 在代码与行内代码中转义。
    #[test]
    fn html_injection_escaped_in_code_contexts() {
        let md = "```html\n<script>alert(1)</script>\n```\n\n`<img onerror=\"x\">`\n";
        let out = render(md);
        assert!(!out.contains("<script>"), "script 标签不得原样注入：{out}");
        assert!(out.contains("&lt;"), "代码中的 `<` 必须转义：{out}");
        assert!(out.contains("&gt;"), "代码中的 `>` 必须转义：{out}");
        assert!(!out.contains("<img onerror"), "img onerror 不得原样注入：{out}");
        assert!(out.contains("&lt;img onerror"), "{out}");
    }

    /// 原始 HTML 透传（与 python-markdown 一致），但 raw HTML 之外的文本仍转义。
    #[test]
    fn raw_html_passthrough() {
        let out = render("<details>\n<summary>x</summary>\n</details>\n");
        assert!(out.contains("<details>"), "{out}");
        assert!(out.contains("<summary>x</summary>"));
    }

    /// 水平线 / 硬换行。
    #[test]
    fn rule_and_hard_break() {
        let out = render("a  \nb\n\n---\n");
        assert!(out.contains("<br />"), "{out}");
        assert!(out.contains("<hr />"), "{out}");
    }

    /// 输出不含任何 CSS/颜色/style。
    #[test]
    fn no_css_or_colors_in_output() {
        let md = "# t\n\n```python\nx=1\n```\n\n| a |\n|---|\n| 1 |\n";
        let out = render(md);
        assert!(!out.contains("<style"), "不应含 <style>：{out}");
        assert!(!out.contains("color:"), "不应含颜色：{out}");
        assert!(!out.contains("style="), "不应含 style 属性：{out}");
    }

    /// fenced code 的 syntect token 文本拼接 == 原文（除空白 span 跳过）。
    #[test]
    fn highlighted_code_preserves_text_content() {
        let md = "```python\nfor i in range(3):\n    print(i)\n```\n";
        let out = render(md);
        // 代码文本内容必须保留（拼接各 span 文本）。
        let code_plain = out
            .replace("<pre><code class=\"highlight\">", "")
            .replace("</code></pre>", "");
        for expected in ["for", "i", "in", "range", "print"] {
            assert!(code_plain.contains(expected), "代码文本丢失 {expected}：{out}");
        }
    }

    /// FFI 往返：合法输入 → `{"html": ...}` 可解析；null → null。
    #[test]
    fn ffi_render_markdown_roundtrip() {
        use std::ffi::CStr;
        let text = std::ffi::CString::new("# 标题 Heading\n\n- [x] done\n").unwrap();
        let raw = crate::faf_render_markdown(text.as_ptr());
        assert!(!raw.is_null(), "合法输入应返回非空指针");
        // SAFETY：raw 为 faf_render_markdown 刚分配的 NUL 终止串。
        let back = unsafe { CStr::from_ptr(raw) }.to_str().unwrap();
        let parsed: serde_json::Value = serde_json::from_str(back).expect("应可解析为 JSON");
        let html = parsed["html"].as_str().expect("应含 html 字段");
        assert!(html.contains("<h1>"));
        assert!(html.contains("task-checkbox checked"));
        // 对称释放。
        crate::faf_free_message(raw);
    }

    /// FFI 错误路径：null 指针 → null；非 UTF-8 → null；不崩溃。
    #[test]
    fn ffi_render_markdown_null_and_bad_input() {
        assert!(crate::faf_render_markdown(std::ptr::null()).is_null());
        let bad = std::ffi::CString::new(vec![0xFFu8, 0xFE, b'x']).unwrap();
        assert!(crate::faf_render_markdown(bad.as_ptr()).is_null());
        // 合法但损坏的 markdown → 正常返回（不崩溃）。
        let text = std::ffi::CString::new("```python\nunclosed").unwrap();
        let raw = crate::faf_render_markdown(text.as_ptr());
        assert!(!raw.is_null());
        crate::faf_free_message(raw);
    }

    // ── todo 16：扩展边界 / 代码块语言映射 / 超长文本 ──────────────────────────

    /// 表格扩展边界：混合对齐（左/右/无）、无分隔行（非表格 → 段落降级）、
    /// 仅表头（分隔行后无表体）。
    #[test]
    fn table_extension_boundary_variants() {
        // 混合对齐 + 表体对齐列。
        let out = render("| a | b | c |\n| :--- | --- | ---: |\n| 1 | 2 | 3 |\n");
        assert!(out.contains("<th align=\"left\">a</th>"), "{out}");
        assert!(out.contains("<th align=\"right\">c</th>"), "{out}");
        assert!(out.contains("<td align=\"right\">3</td>"), "{out}");
        // 无分隔行（`---` 缺失）→ 非表格 → 段落原文，不 panic。
        let out2 = render("| alpha | beta |\n| 1 | 2 |\n");
        assert!(!out2.contains("<table>"), "无分隔行不应成表：{out2}");
        assert!(out2.contains("alpha"), "{out2}");
        // 仅表头（分隔行后直接结束）→ 空表体，不 panic。
        let out3 = render("| h1 | h2 |\n| --- | --- |\n");
        assert!(out3.contains("<table>"), "{out3}");
        assert!(out3.contains("<th>h1</th>"), "{out3}");
        assert!(out3.contains("</tbody></table>"), "{out3}");
    }

    /// 脚注扩展边界：单次引用、引用但无定义（sup 仍输出、无 backref）、
    /// 定义但无引用（不 panic、内容保留）。
    #[test]
    fn footnote_extension_boundary_variants() {
        // 单次引用 + 定义。
        let out = render("正文[^x]。\n\n[^x]: 定义内容。\n");
        assert!(out.contains("<sup id=\"fnref:x\"><a href=\"#fn:x\">1</a></sup>"), "{out}");
        assert!(out.contains("<li id=\"fn:x\">"), "{out}");
        // 引用但无定义 → pulldown-cmark 不解析（实测按原文保留 `[^missing]`），
        // 不 panic、不产出 sup/backref。
        let out2 = render("正文引用[^missing]。\n");
        assert!(out2.contains("[^missing]"), "无定义引用应按原文保留：{out2}");
        assert!(!out2.contains("fnref"), "无定义不应产出 sup：{out2}");
        // 定义但无引用 → 不 panic，文本内容保留。
        let out3 = render("[^orphan]: 孤儿定义。\n");
        assert!(out3.contains("孤儿定义"), "孤儿定义文本应保留：{out3}");
    }

    /// 任务列表扩展边界：勾选/未勾选/嵌套/含行内代码；普通列表项无复选框。
    #[test]
    fn tasklist_extension_boundary_variants() {
        let md = "- [x] 已完成\n- [ ] 待办\n  - [x] 嵌套已完成\n- [x] 带 `code` 项\n";
        let out = render(md);
        assert!(out.contains("<span class=\"task-checkbox checked\">\u{2611}</span>"), "{out}");
        assert!(out.contains("<span class=\"task-checkbox unchecked\">\u{2610}</span>"), "{out}");
        assert!(out.contains("嵌套已完成"), "{out}");
        assert!(out.contains("<code>code</code>"), "{out}");
        // 4 个任务项 → 恰好 4 个复选框 span；`- [x] 带 code 项` 也算任务项。
        assert_eq!(
            out.matches("task-checkbox").count(),
            4,
            "每个任务项应恰有一个复选框 span：{out}"
        );
    }

    /// 删除线扩展边界：删除线内嵌强调/代码（内容嵌套不破坏 del 配对）。
    #[test]
    fn strikethrough_extension_boundary_variants() {
        // 各形态独立成段，避免相邻 `~~` 的引擎特定配对歧义（pulldown-cmark 对
        // `~~a~~与~~b~~` 的配对与 python-markdown 不同，不做精确嵌套断言）。
        let out = render("~~删除线~~\n\n~~**加粗删除**~~\n\n~~`code`~~\n");
        assert!(out.contains("<del>删除线</del>"), "{out}");
        assert!(out.contains("加粗删除"), "{out}");
        assert!(out.contains("<code>code</code>"), "{out}");
        assert!(!out.contains("<del><del>"), "不应出现嵌套 del：{out}");
    }

    /// 降级扩展边界：admonition（`!!! note`）/def_list（`: term`）/abbr/toc 语法
    /// pulldown-cmark 不解析 → 按普通段落/原文渲染，不 panic、不产出专用容器
    ///（与 todo 17 扩展映射表 degraded 项一致）。
    #[test]
    fn degraded_extension_syntax_renders_as_plain_text() {
        // admonition：`!!! note` → 普通段落文本。
        let out = render("!!! note \"标题\"\n    这是一条注意信息。\n");
        assert!(!out.contains("admonition"), "不应实现 admonition 容器：{out}");
        assert!(out.contains("!!! note"), "admonition 语法应按原文保留：{out}");
        assert!(out.contains("这是一条注意信息"), "{out}");
        // def_list：`: term` → 普通段落（无 <dl>/<dt>/<dd>）。
        let out = render("Apple\n:   Pomaceous fruit\n\nOrange\n:   Citrus fruit\n");
        assert!(!out.contains("<dl"), "不应实现 definition list：{out}");
        assert!(out.contains("Apple"), "{out}");
        assert!(out.contains("Pomaceous fruit"), "{out}");
        // abbr：`*[HTML]: ...` → 原文，无 <abbr>。
        let out = render("*[HTML]: Hyper Text Markup Language\n\nHTML 规范。\n");
        assert!(!out.contains("<abbr"), "不应实现 abbr 扩展：{out}");
        assert!(out.contains("HTML"), "{out}");
        // toc：`[TOC]` → 原文/链接，无 toc 容器。
        let out = render("[TOC]\n\n# 标题\n");
        assert!(!out.contains("class=\"toc\""), "不应实现 toc 容器：{out}");
        assert!(out.contains("TOC"), "{out}");
    }

    /// 代码块语言映射：fenced 语言标记 → `<pre><code class="highlight">` 内产出
    /// `tok-<TYPE>` span（KEYWORD 等关键类型）。
    #[test]
    fn fenced_language_mapping_produces_token_spans() {
        // (语言标记, 代码, 必须出现的 span 类)。
        // 注：syntect 把 `const`（JS）/`fn`（Rust）/`func`（Go）归 storage.type →
        // CLASS_TYPE，而非 keyword；`return` 恒为 keyword.control → KEYWORD。
        let cases: &[(&str, &str, &str)] = &[
            ("python", "import os\nx = 1\n", "tok-KEYWORD"),
            ("javascript", "return true;\n", "tok-KEYWORD"),
            ("rust", "return 1;\n", "tok-KEYWORD"),
            ("go", "return true\n", "tok-KEYWORD"),
            ("sql", "SELECT * FROM t;\n", "tok-KEYWORD"),
            ("lua", "return x\n", "tok-KEYWORD"),
        ];
        for (lang, code, must_span) in cases {
            let md = format!("```{lang}\n{code}```\n");
            let out = render(&md);
            assert!(
                out.contains("<pre><code class=\"highlight\">"),
                "{lang} 缺 pre/code 容器：{out}"
            );
            assert!(
                out.contains(must_span),
                "{lang} 应产出 {must_span} span：{out}"
            );
        }
    }

    /// 映射表内但 syntect 默认集缺失的语言（typescript 等 → Err(-6)）→
    /// markdown 侧降级纯 escaped：不 panic、无 span、代码文本保留。
    #[test]
    fn fenced_mapped_language_missing_syntax_degrades_escaped() {
        for lang in ["typescript", "powershell", "kotlin", "swift", "vue", "svelte"] {
            let md = format!("```{lang}\nconst x: number = 1;\n```\n");
            let out = render(&md);
            assert!(
                out.contains("<pre><code class=\"highlight\">"),
                "{lang}：{out}"
            );
            assert!(
                !out.contains("tok-"),
                "{lang} 应降级纯 escaped（无 span）：{out}"
            );
            assert!(
                out.contains("const x: number = 1;"),
                "{lang} 代码内容应保留：{out}"
            );
        }
    }

    /// 超长文本（≥1MB 重复段落 + 小代码块）：不 OOM、不 panic、输出可解析；
    /// 耗时打印实测 + 宽松阈值（CI 慢机不 flaky）。
    #[test]
    fn long_text_over_1mb_renders_without_panic() {
        use std::time::Instant;
        let para = "这是超长文本压测段落：**加粗**、*斜体*、`code` 与 [链接](https://e.com)。\n\n";
        let code = "```python\nx = 1\n# comment\n```\n\n";
        let mut md = String::with_capacity(1_200_000);
        while md.len() < 1_048_576 {
            md.push_str(para);
            md.push_str(code);
        }
        assert!(md.len() >= 1_048_576, "输入必须 ≥1MB（实际 {}B）", md.len());
        let start = Instant::now();
        let out = render(&md);
        let elapsed = start.elapsed();
        println!(
            "[long_text_over_1mb] input={}B output={}B elapsed={elapsed:?}",
            md.len(),
            out.len()
        );
        assert!(!out.is_empty());
        assert!(out.contains("<p>"), "应含段落");
        assert!(out.contains("tok-COMMENT"), "应含代码高亮 span");
        // 可解析性：段落标签平衡。
        let p_open = out.matches("<p>").count();
        let p_close = out.matches("</p>").count();
        assert_eq!(
            p_open, p_close,
            "段落标签应平衡（open={p_open} close={p_close}）"
        );
        // 宽松阈值：正常 <1s；慢机放宽到 30s（实测值已打印）。
        assert!(elapsed.as_secs() < 30, "超长渲染应宽松在 30s 内（实测 {elapsed:?}）");
    }

    /// 单个超大 fenced 代码块（≥1MB）：syntect 逐行高亮 + span 写入不 OOM/不 panic。
    ///
    /// 用 ~500 字符的长行构造 ≥1MB（少行数→避免 debug 下逐行 parse 开销拖慢，
    /// 本机实测 34s→2s 级，CI 更稳）。
    #[test]
    fn huge_single_code_block_renders_without_panic() {
        use std::time::Instant;
        let line = format!("{}<\n", "x = value < 1  # filler comment ".repeat(20));
        assert!(line.len() > 500, "行长应 ~500 字符（实际 {}）", line.len());
        let mut code = String::with_capacity(1_100_000);
        while code.len() < 1_048_576 {
            code.push_str(&line);
        }
        let md = format!("```python\n{code}```\n");
        let start = Instant::now();
        let out = render(&md);
        let elapsed = start.elapsed();
        println!(
            "[huge_single_code_block] code={}B lines={} output={}B elapsed={elapsed:?}",
            code.len(),
            code.lines().count(),
            out.len()
        );
        assert!(out.contains("tok-COMMENT"), "应产出 COMMENT span");
        assert!(out.contains("&lt;"), "代码中的 `<` 必须转义");
        // debug 下 syntect 解析 1MB 代码实测 ~25s（release 1s 级）；CI 慢机
        // 再放宽到 90s（实测值已打印）。
        assert!(elapsed.as_secs() < 90, "超大代码块应宽松在 90s 内（实测 {elapsed:?}）");
    }
}
