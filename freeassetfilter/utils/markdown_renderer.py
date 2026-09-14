#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Markdown 渲染器

将 Markdown 文本渲染为包含主题 CSS 与 Pygments 语法高亮的自包含 HTML 文档。
"""

from __future__ import annotations

import re
from typing import Optional

from freeassetfilter.ui.theme import tm


try:
    import markdown

    _HAS_MARKDOWN = True
except Exception:  # pragma: no cover - dependency guard
    _HAS_MARKDOWN = False
    markdown = None  # type: ignore[assignment]

try:
    import pygments
    from pygments.formatters import HtmlFormatter

    _HAS_PYGMENTS = True
except Exception:  # pragma: no cover - dependency guard
    _HAS_PYGMENTS = False
    pygments = None  # type: ignore[assignment]
    HtmlFormatter = None  # type: ignore[assignment,misc]

MARKDOWN_AVAILABLE = _HAS_MARKDOWN and _HAS_PYGMENTS

if MARKDOWN_AVAILABLE:
    from markdown.treeprocessors import Treeprocessor
    from markdown.extensions import Extension
    from xml.etree.ElementTree import Element

    class _TaskListTreeProcessor(Treeprocessor):
        """After list parsing, turn ``[ ]`` / ``[x]`` task markers into checkbox symbols."""

        _PATTERN = re.compile(r"^\[([ xX])\]\s+(.*)$")

        def run(self, root) -> None:
            for li in root.iter("li"):
                first = li.text or ""
                match = self._PATTERN.match(first)
                if not match:
                    continue
                checked = match.group(1).strip().lower() == "x"
                symbol = "☑" if checked else "☐"
                li.set("class", "task-item")
                li.text = ""
                span = Element("span")
                span.set("class", f'task-checkbox {"checked" if checked else "unchecked"}')
                span.text = symbol
                span.tail = " " + match.group(2)
                li.insert(0, span)

    class _TaskListExtension(Extension):
        """Lightweight GitHub-style task list extension without external dependencies."""

        def extendMarkdown(self, md: "markdown.Markdown") -> None:
            md.treeprocessors.register(_TaskListTreeProcessor(md), "tasklist", 15)


# =============================================================================
# 两引擎共享的源文本准备 / body 后处理（todo-17：python-markdown 路径与
# faf_core native 路径统一调用，保证输出行为一致）。
# =============================================================================

_DETAILS_MD_IN_HTML_RE = re.compile(r"<details\b")
_DIV_MD_IN_HTML_RE = re.compile(r"<div(\s)")

# `<div align=...>` → 内联 style：QTextBrowser/QTextDocument 不识别 HTML
# align 属性，转成内联 `style="text-align: ..."` 才能实现居中。
_ALIGN_DIV_RE = re.compile(
    r'<div\b([^>]*)align=["\']([^"\']+)["\']([^>]*)>',
    flags=re.IGNORECASE,
)

# 标题 id 重写：`<hN>正文</hN>` → `<hN id="正文">正文</hN>`，使
# `[标题](#标题)` 式内部锚点可滚动到对应标题。
_HEADING_ID_RE = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", flags=re.DOTALL)

# README 式 `#-xxx` 锚点归一化为 `#xxx`。
_HYPHEN_ANCHOR_RE = re.compile(r'href=["\']#-([^"\']+)["\']')

# 任务列表 item 类吸收：native 的任务列表 `<li>` 不携带 `task-item` 类
# （python-markdown 的 ``_TaskListTreeProcessor`` 会打该类，``li.task-item``
# CSS 依赖它去除项符号）；已带类的 python 输出不命中（幂等）。
_TASK_ITEM_CLASS_RE = re.compile(
    r'(?i)<li>(\s*)<span class="task-checkbox'
)

# md_in_html 标记属性剥离：``inject_md_in_html`` 注入的 ``markdown="1"`` 在
# python-markdown 侧被 md_in_html 扩展消费（输出剥离），而 native 引擎按 raw
# HTML 透传会保留该属性——共享后处理统一剥离（对 python 输出幂等）。
_MD_IN_HTML_MARKER_RE = re.compile(r'(?i)(<details\b[^>]*?)\s+markdown="1"')
_DIV_MD_IN_HTML_MARKER_RE = re.compile(r'(?i)(<div\b[^>]*?)\s+markdown="1"')

# native 代码块 `<pre><code class="highlight">` → python-markdown codehilite
# 的 `<div class="highlight"><pre><code>` 包装形态（着色 CSS 依赖 `.highlight
# pre` 统一样式；python 的 `<span></span>` 行号占位在 normalize_html 时被
# 裁剪、class 差异被忽略——结构归一后两引擎等价）。lookbehind 防对 python
# 已包裹输出二次包裹（幂等）。
_PRE_CODE_HIGHLIGHT_RE = re.compile(
    r'(?<!<div class="highlight">)<pre><code class="highlight">(.*?)</code></pre>',
    flags=re.DOTALL,
)


def inject_md_in_html(text: str) -> str:
    """为源文本注入 md_in_html 容器标记（渲染前，两引擎共用）。

    python-markdown 的 ``md_in_html`` 扩展依据 `markdown="1"` 属性把容器内
    内容按 markdown 解析；native（pulldown-cmark）对 ``<details>/<div>`` 容器
    内容本身就按 CommonMark 解析，注入的标记属性会随 raw HTML 透传，随后由
    :func:`apply_shared_postprocessing` 统一剥离。两引擎渲染前**都**调用本
    函数，保证输入路径一致。

    Args:
        text: 原始 Markdown 源文本。

    Returns:
        str: 注入 ``markdown="1"`` 标记后的文本。
    """
    text = _DETAILS_MD_IN_HTML_RE.sub('<details markdown="1"', text)
    text = _DIV_MD_IN_HTML_RE.sub(r'<div markdown="1"\1', text)
    return text


def _rewrite_heading_id_match(match: "re.Match[str]") -> str:
    """把 heading 标签重写为带与正文一致的 id（内部锚点可跳转）。"""
    level = match.group(1)
    content = match.group(2).strip()
    # Strip any inline HTML tags from the id text.
    plain_id = re.sub(r"<[^>]+>", "", content).strip()
    return f'<h{level} id="{plain_id}">{content}</h{level}>'


def apply_shared_postprocessing(body_html: str) -> str:
    """两引擎共享的 body 后处理（渲染后统一应用，顺序明确）。

    处理项（python-markdown 与 native 路径都调用，保证输出行为一致）：

    1. 剥离 ``markdown="1"`` 容器标记（native raw-HTML 透传残留；python
       已由 md_in_html 消费，幂等）；
    2. native 代码块包装归一为 ``<div class="highlight"><pre><code>``
       （着色 CSS 契约；python 输出因 lookbehind 幂等）；
    3. ``<div align=...>`` → 内联 ``style="text-align: ...;"``
       （QTextBrowser 不识别 align 属性）；
    4. 任务列表 ``<li>`` 吸收 ``task-item`` 类（native 缺失，CSS 依赖）；
    5. heading id 重写并令 id 与正文一致；
    6. ``#-xxx`` 锚点归一化为 ``#xxx``。

    Args:
        body_html: 引擎产出的 body 片段。

    Returns:
        str: 后处理后的 body 片段。
    """
    # 1. md_in_html 标记剥离（对 native 透传的 markdown="1" 生效）。
    body_html = _MD_IN_HTML_MARKER_RE.sub(r"\1", body_html)
    body_html = _DIV_MD_IN_HTML_MARKER_RE.sub(r"\1", body_html)
    # 2. 代码块包装归一。
    body_html = _PRE_CODE_HIGHLIGHT_RE.sub(
        r'<div class="highlight"><pre><code>\1</code></pre></div>',
        body_html,
    )
    # 3. align → inline style。
    body_html = _ALIGN_DIV_RE.sub(
        r'<div\1style="text-align: \2;"\3>',
        body_html,
    )
    # 4. task-item 类吸收。
    body_html = _TASK_ITEM_CLASS_RE.sub(
        r'<li class="task-item">\1<span class="task-checkbox',
        body_html,
    )
    # 5. heading id 重写。
    body_html = _HEADING_ID_RE.sub(_rewrite_heading_id_match, body_html)
    # 6. #- 锚点归一化。
    body_html = _HYPHEN_ANCHOR_RE.sub(r'href="#\1"', body_html)
    return body_html


class MarkdownRenderer:
    """Render Markdown text into a themed, self-contained HTML document."""

    _DEFAULT_FONT_SIZE = 14

    def __init__(self, font_size: int = _DEFAULT_FONT_SIZE) -> None:
        """Initialize renderer with a base font size.

        Args:
            font_size: Base body font size in pixels. Defaults to 14.
        """
        self._font_size = font_size

    @classmethod
    def is_available(cls) -> bool:
        """Return ``True`` when both ``markdown`` and ``pygments`` are usable."""
        return MARKDOWN_AVAILABLE

    @classmethod
    def available(cls) -> bool:
        """Alias for :meth:`is_available`.

        Returns:
            ``True`` when both required libraries are importable.
        """
        return MARKDOWN_AVAILABLE

    def set_font_size(self, size: int) -> None:
        """Update the base body font size.

        Args:
            size: New font size in pixels.

        Raises:
            TypeError: If ``size`` is not an integer.
        """
        if not isinstance(size, int):
            raise TypeError(f"font size must be int, got {type(size).__name__}")
        self._font_size = size

    def render(self, text: str, file_path: Optional[str] = None) -> str:
        """Render Markdown *text* into a full HTML document string.

        Args:
            text: Markdown source.
            file_path: Optional path to the source file. Reserved for callers
                that need to set search paths or base URLs separately.

        Returns:
            A complete ``<!DOCTYPE html>`` document as a string.

        Raises:
            RuntimeError: If Markdown/Pygments libraries are unavailable.

        Notes:
            faf_core 原生引擎（``faf_render_markdown``，桥可用时）为可选
            高优先级路径：输出经 :func:`apply_shared_postprocessing` 共享后处理
            后组装完整文档；桥不可用（DLL 缺失 / 旧版 DLL 无导出 / FFI 失败）
            时回退 python-markdown 现状路径，同样过共享后处理——两路径输出
            行为一致。
        """
        if not MARKDOWN_AVAILABLE:
            raise RuntimeError("markdown and pygments are required for rendering")

        # 渲染前源文本准备：md_in_html 容器标记注入（两引擎共用）。
        prepared = inject_md_in_html(text)

        # native 高优先级路径：桥可用 → 原生 body；不可用 → python-markdown。
        body_html: str
        native_body = self._render_native_body(prepared)
        if native_body is not None:
            body_html = native_body
        else:
            body_html = self._create_markdown().convert(prepared)

        # 两引擎共享的 body 后处理（align→style、heading-id、代码块包装等）。
        body_html = apply_shared_postprocessing(body_html)

        css = self._build_css()
        pygments_css = self._pygments_style_defs(tm.is_dark_theme())

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{pygments_css}
{css}
</head>
<body>
{body_html}
</body>
</html>"""

    def _render_native_body(self, text: str) -> Optional[str]:
        """尝试经 faf_core 原生引擎渲染 body 片段（不可用返回 ``None``）。

        桥可用且 ``_supports_render_markdown`` 为真时调用
        ``bridge.render_markdown(text)`` 取 ``{"html": ...}`` body 片段；
        任何失败（DLL 缺失 / 绑定缺失 / 非法载荷 / 异常）均返回 ``None``，
        由 :meth:`render` 回退 python-markdown 现状路径。

        Args:
            text: 已注入 md_in_html 标记的 Markdown 源文本。

        Returns:
            Optional[str]: native body 片段；不可用时 ``None``。
        """
        try:
            from freeassetfilter.core.native.bridges.faf_core_bridge import (
                get_faf_core_bridge,
            )

            bridge = get_faf_core_bridge()
            if bridge is None or not bridge.available:
                return None
            if not getattr(bridge, "_supports_render_markdown", False):
                return None
            result = bridge.render_markdown(text)
            if not isinstance(result, dict):
                return None
            html = result.get("html")
            if not isinstance(html, str):
                return None
            return html
        except Exception:  # noqa: BLE001  # FFI/导入边界：任何异常都回退 python
            return None

    def _create_markdown(self) -> "markdown.Markdown":
        """Return a fresh ``markdown.Markdown`` instance.

        Creating a new instance per render avoids state leakage from the
        ``toc`` and ``footnotes`` extensions when switching documents.
        ``fenced_code`` is placed before ``codehilite`` as required.
        """
        return markdown.Markdown(
            extensions=[
                "tables",
                "fenced_code",
                "md_in_html",
                "toc",
                "sane_lists",
                "footnotes",
                "def_list",
                "abbr",
                "admonition",
                "codehilite",
                _TaskListExtension(),
            ],
            extension_configs={
                "codehilite": {
                    "css_class": "highlight",
                    "use_pygments": True,
                }
            },
        )

    def _build_css(self) -> str:
        """Build a conservative ``<style>`` block using current theme colors.

        Selectors are kept simple to maximize compatibility with
        ``QTextBrowser`` / ``QTextDocument`` CSS support.
        """
        fg = tm.text.name()
        mid = tm.mid.name()
        fill = tm.fill.name()
        accent = tm.accent.name()
        danger = tm.danger.name()
        warning = tm.warning.name()
        info = tm.info.name()

        toc_bg = tm.alpha_of(tm.mid, 10).name()
        admonition_bg = tm.alpha_of(tm.accent, 10).name()
        warning_bg = tm.alpha_of(tm.warning, 10).name()
        danger_bg = tm.alpha_of(tm.danger, 10).name()
        info_bg = tm.alpha_of(tm.info, 10).name()

        return f"""<style>
body {{
    background-color: transparent;
    color: {fg};
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: {self._font_size}px;
    line-height: 1.6;
    padding: 16px;
    margin: 0;
}}
h1, h2, h3, h4, h5, h6 {{
    color: {fg};
    margin-top: 16px;
    margin-bottom: 8px;
    line-height: 1.3;
}}
p {{
    margin-top: 8px;
    margin-bottom: 8px;
}}
ul, ol {{
    padding-left: 24px;
    margin-top: 8px;
    margin-bottom: 8px;
}}
li {{
    margin-bottom: 4px;
}}
a {{
    color: {accent};
    text-decoration: none;
}}
hr {{
    border: none;
    border-top: 1px solid {mid};
    margin: 16px 0;
}}
details {{
    border: 1px solid {mid};
    border-radius: 6px;
    padding: 12px;
    margin: 12px 0;
    background-color: {tm.alpha_of(tm.fill, 30).name()};
}}
summary {{
    font-weight: bold;
    cursor: default;
    color: {fg};
}}
code {{
    font-family: "Fira Code", Consolas, monospace;
    background-color: {fill};
    border: 1px solid {mid};
    padding: 1px 4px;
    border-radius: 3px;
}}
.highlight {{
    display: block;
    margin: 12px 0;
}}
pre {{
    background-color: transparent;
    padding: 0;
    border-radius: 0;
    margin: 0;
    overflow-x: auto;
}}
.highlight pre {{
    background-color: {fill};
    border: 1px solid {mid};
    padding: 12px;
    border-radius: 6px;
    margin: 0;
    line-height: 1.0;
}}
.highlight pre code {{
    background-color: transparent;
    border: none;
    padding: 0;
    border-radius: 0;
    line-height: 1.0;
}}
pre code {{
    background-color: transparent;
    border: none;
    padding: 0;
    border-radius: 0;
}}
blockquote {{
    border-left: 4px solid {accent};
    margin: 8px 0;
    padding-left: 12px;
    color: {mid};
}}
table {{
    border-collapse: collapse;
    width: 100%;
    margin: 12px 0;
}}
th, td {{
    border: 1px solid {fg};
    padding: 6px 10px;
    text-align: left;
    vertical-align: middle;
}}
th {{
    background-color: transparent;
}}
img {{
    max-width: 100%;
    height: auto;
}}
.toc {{
    background-color: {toc_bg};
    border: 1px solid {mid};
    border-radius: 6px;
    padding: 12px 16px;
    margin-bottom: 16px;
}}
.toc ul {{
    list-style-type: none;
    padding-left: 16px;
    margin: 0;
}}
.toc > ul {{
    padding-left: 0;
}}
.toc a {{
    color: {accent};
}}
.admonition {{
    background-color: {admonition_bg};
    border-left: 4px solid {accent};
    border-radius: 4px;
    padding: 12px 16px;
    margin: 12px 0;
}}
.admonition-title {{
    font-weight: bold;
    margin-bottom: 4px;
    color: {fg};
}}
.admonition.note {{
    background-color: {info_bg};
    border-left-color: {info};
}}
.admonition.warning {{
    background-color: {warning_bg};
    border-left-color: {warning};
}}
.admonition.danger {{
    background-color: {danger_bg};
    border-left-color: {danger};
}}
.footnote {{
    font-size: 0.85em;
    color: {mid};
    border-top: 1px solid {mid};
    margin-top: 16px;
    padding-top: 8px;
}}
.footnote ol {{
    padding-left: 20px;
}}
.footnote a {{
    color: {accent};
}}
li.task-item {{
    list-style-type: none;
    margin-left: -18px;
}}
.task-checkbox {{
    font-family: "Segoe UI Symbol", "Apple Color Emoji", sans-serif;
    margin-right: 6px;
    color: {mid};
}}
.task-checkbox.checked {{
    color: {accent};
}}
</style>"""

    def _pygments_style_defs(self, is_dark: bool) -> str:
        """Return Pygments CSS style definitions for the current theme mode."""
        style = "monokai" if is_dark else "default"
        return HtmlFormatter(style=style).get_style_defs(".highlight")
