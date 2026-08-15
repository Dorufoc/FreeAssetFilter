#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for MarkdownRenderer.

Verifies availability detection, rendering output structure, font size and
theme switching, Markdown extensions, and per-render state isolation.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from freeassetfilter.utils import markdown_renderer as md_renderer_module
from freeassetfilter.utils.markdown_renderer import (
    MARKDOWN_AVAILABLE,
    MarkdownRenderer,
)


# =============================================================================
# Availability
# =============================================================================


class TestAvailability:
    """Availability detection."""

    def test_markdown_available_module_flag(self) -> None:
        """Module flag matches the current environment."""
        assert MARKDOWN_AVAILABLE is (MarkdownRenderer.is_available() is True)

    def test_is_available_matches_available(self) -> None:
        """is_available and available return the same value."""
        assert MarkdownRenderer.is_available() == MarkdownRenderer.available()

    def test_is_available_false_when_markdown_missing(self, monkeypatch) -> None:
        """Returns False when markdown is missing."""
        monkeypatch.setattr(md_renderer_module, "_HAS_MARKDOWN", False)
        monkeypatch.setattr(md_renderer_module, "_HAS_PYGMENTS", True)
        monkeypatch.setattr(md_renderer_module, "MARKDOWN_AVAILABLE", False)

        assert MarkdownRenderer.is_available() is False

    def test_is_available_false_when_pygments_missing(self, monkeypatch) -> None:
        """Returns False when pygments is missing."""
        monkeypatch.setattr(md_renderer_module, "_HAS_MARKDOWN", True)
        monkeypatch.setattr(md_renderer_module, "_HAS_PYGMENTS", False)
        monkeypatch.setattr(md_renderer_module, "MARKDOWN_AVAILABLE", False)

        assert MarkdownRenderer.is_available() is False


# =============================================================================
# Render structure
# =============================================================================


@pytest.mark.skipif(not MARKDOWN_AVAILABLE, reason="markdown + pygments required")
class TestRenderStructure:
    """Rendered HTML document structure."""

    def test_render_returns_full_html_document(self, qapp) -> None:
        """render returns a complete DOCTYPE html document."""
        renderer = MarkdownRenderer(font_size=14)
        html = renderer.render("# hello")

        assert html.strip().startswith("<!DOCTYPE html>")
        assert "<html>" in html
        assert "</html>" in html
        assert "<head>" in html
        assert "<body>" in html

    def test_render_contains_theme_style_block(self, qapp) -> None:
        """Output contains a themed CSS style block."""
        html = MarkdownRenderer().render("# hello")

        assert "<style>" in html
        assert "</style>" in html
        assert "background-color:" in html

    def test_render_contains_pygments_style_defs(self, qapp) -> None:
        """Output contains Pygments highlight CSS."""
        html = MarkdownRenderer().render("```\nfoo\n```")

        assert ".highlight" in html

    def test_render_generates_heading(self, qapp) -> None:
        """Headings produce expected tags."""
        html = MarkdownRenderer().render("# Title\n\n## Subtitle")

        assert "<h1" in html
        assert "Title" in html
        assert "<h2" in html
        assert "Subtitle" in html

    def test_render_generates_unordered_list(self, qapp) -> None:
        """Unordered lists produce ul/li tags."""
        html = MarkdownRenderer().render("- a\n- b")

        assert "<ul>" in html
        assert "<li" in html

    def test_render_generates_table(self, qapp) -> None:
        """Tables extension produces table tags."""
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        html = MarkdownRenderer().render(md)

        assert "<table>" in html
        assert "<th" in html
        assert "<td" in html

    def test_render_generates_blockquote(self, qapp) -> None:
        """Blockquotes produce blockquote tags."""
        html = MarkdownRenderer().render("> quoted")

        assert "<blockquote>" in html
        assert "quoted" in html

    def test_render_generates_code_highlight(self, qapp) -> None:
        """Fenced code blocks are highlighted by codehilite/pygments."""
        html = MarkdownRenderer().render('```python\nprint(1)\n```')

        assert '<div class="highlight">' in html
        assert "<pre" in html
        assert "<span" in html

    def test_render_generates_toc(self, qapp) -> None:
        """toc extension generates a table of contents for [TOC]."""
        html = MarkdownRenderer().render("[TOC]\n\n# Section\n\n## Sub")

        assert '<div class="toc">' in html
        assert "#section" in html

    def test_render_generates_admonition(self, qapp) -> None:
        """admonition extension generates styled admonition blocks."""
        md = "!!! note\\n    This is a note."
        html = MarkdownRenderer().render(md)

        assert "admonition" in html
        assert "note" in html

    def test_render_generates_footnote(self, qapp) -> None:
        """footnotes extension generates footnote markup."""
        md = "Text[^1].\n\n[^1]: Footnote text."
        html = MarkdownRenderer().render(md)

        assert '<div class="footnote">' in html
        assert "Footnote text" in html

    def test_render_respects_file_path_argument(self, qapp) -> None:
        """file_path is accepted and does not break rendering."""
        html = MarkdownRenderer().render("# hello", file_path="/tmp/test.md")

        assert "<h1" in html

    def test_render_generates_task_list(self, qapp) -> None:
        """GitHub-style task list markers produce checkbox symbols and CSS classes."""
        md = "- [x] Done item\n- [ ] Todo item"
        html = MarkdownRenderer().render(md)

        assert 'class="task-item"' in html
        assert 'class="task-checkbox checked"' in html
        assert 'class="task-checkbox unchecked"' in html
        assert "☑" in html
        assert "☐" in html
        assert "Done item" in html
        assert "Todo item" in html


# =============================================================================
# Font size
# =============================================================================


@pytest.mark.skipif(not MARKDOWN_AVAILABLE, reason="markdown + pygments required")
class TestFontSize:
    """Font size configuration."""

    def test_default_font_size(self, qapp) -> None:
        """Default font size is 14 px."""
        renderer = MarkdownRenderer()
        html = renderer.render("x")

        assert "font-size: 14px" in html

    def test_set_font_size_updates_output(self, qapp) -> None:
        """set_font_size is reflected on the next render."""
        renderer = MarkdownRenderer()
        renderer.set_font_size(18)
        html = renderer.render("x")

        assert "font-size: 18px" in html
        assert "font-size: 14px" not in html

    def test_set_font_size_rejects_non_int(self, qapp) -> None:
        """Non-int font size raises TypeError."""
        renderer = MarkdownRenderer()

        with pytest.raises(TypeError):
            renderer.set_font_size("large")  # type: ignore[arg-type]


# =============================================================================
# Theme / Pygments style selection
# =============================================================================


@pytest.mark.skipif(not MARKDOWN_AVAILABLE, reason="markdown + pygments required")
class TestThemeHighlighting:
    """Theme-driven Pygments style selection."""

    def test_dark_theme_uses_monokai(self, qapp, monkeypatch) -> None:
        """Dark theme selects monokai style."""
        from freeassetfilter.ui.theme import tm
        from pygments.formatters import HtmlFormatter

        monkeypatch.setattr(tm, "is_dark_theme", lambda: True)

        renderer = MarkdownRenderer()
        defs = renderer._pygments_style_defs(tm.is_dark_theme())
        expected = HtmlFormatter(style="monokai").get_style_defs(".highlight")

        assert defs == expected

    def test_light_theme_uses_default(self, qapp, monkeypatch) -> None:
        """Light theme selects default style."""
        from freeassetfilter.ui.theme import tm
        from pygments.formatters import HtmlFormatter

        monkeypatch.setattr(tm, "is_dark_theme", lambda: False)

        renderer = MarkdownRenderer()
        defs = renderer._pygments_style_defs(tm.is_dark_theme())
        expected = HtmlFormatter(style="default").get_style_defs(".highlight")

        assert defs == expected

    def test_pygments_defs_differ_between_themes(self, qapp) -> None:
        """Dark and light theme produce different style definitions."""
        renderer = MarkdownRenderer()

        dark_defs = renderer._pygments_style_defs(True)
        light_defs = renderer._pygments_style_defs(False)

        assert dark_defs != light_defs


# =============================================================================
# State isolation
# =============================================================================


@pytest.mark.skipif(not MARKDOWN_AVAILABLE, reason="markdown + pygments required")
class TestStateIsolation:
    """Per-render Markdown instance isolation."""

    def test_new_markdown_instance_per_render(self, qapp) -> None:
        """_create_markdown returns a fresh instance each call."""
        renderer = MarkdownRenderer()
        md1 = renderer._create_markdown()
        md2 = renderer._create_markdown()

        assert md1 is not md2

    def test_toc_does_not_leak_across_renders(self, qapp) -> None:
        """TOC state does not leak from one render to the next."""
        renderer = MarkdownRenderer()

        html1 = renderer.render("[TOC]\n\n# First\n\n## One")
        html2 = renderer.render("[TOC]\n\n# Second\n\n## Two")

        assert "second" in html2.lower()
        assert "first" not in html2.lower()
        assert "first" in html1.lower()
        assert "second" not in html1.lower()


# =============================================================================
# Error paths
# =============================================================================


class TestErrorPaths:
    """Failure handling."""

    def test_render_raises_when_dependencies_missing(self, monkeypatch, qapp) -> None:
        """render raises RuntimeError when dependencies are unavailable."""
        monkeypatch.setattr(md_renderer_module, "MARKDOWN_AVAILABLE", False)

        renderer = MarkdownRenderer()
        with pytest.raises(RuntimeError):
            renderer.render("# hello")
