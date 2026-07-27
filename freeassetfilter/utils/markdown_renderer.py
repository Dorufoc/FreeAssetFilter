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
        """
        if not MARKDOWN_AVAILABLE:
            raise RuntimeError("markdown and pygments are required for rendering")

        md = self._create_markdown()
        # Allow Markdown inside <details>/<summary> and block-level <div>
        # containers by marking them as parseable by the md_in_html extension.
        text = re.sub(r'<details\b', '<details markdown="1"', text)
        text = re.sub(r'<div(\s)', r'<div markdown="1"\1', text)
        body_html = md.convert(text)

        # QTextBrowser/QTextDocument does not honor the HTML align attribute on
        # <div>; convert it to an inline style statement for center/left/right.
        body_html = re.sub(
            r'<div\b([^>]*)align=["\']([^"\']+)["\']([^>]*)>',
            r'<div\1style="text-align: \2;"\3>',
            body_html,
            flags=re.IGNORECASE,
        )

        # Make heading ids match the heading text so internal anchors like
        # [功能预览](#功能预览) actually scroll to the heading.
        def _rewrite_heading_id(match: "re.Match[str]") -> str:
            level = match.group(1)
            content = match.group(2).strip()
            # Strip any inline HTML tags from the id text.
            plain_id = re.sub(r"<[^>]+>", "", content).strip()
            return f'<h{level} id="{plain_id}">{content}</h{level}>'

        body_html = re.sub(
            r'<h([1-6])\b[^>]*>(.*?)</h\1>',
            _rewrite_heading_id,
            body_html,
            flags=re.DOTALL,
        )
        # READMEs sometimes generate anchors with a leading hyphen; normalize.
        body_html = re.sub(
            r'href=["\']#-([^"\']+)["\']',
            r'href="#\1"',
            body_html,
        )
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
        bg = tm.surface.name()
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
    background-color: {bg};
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
