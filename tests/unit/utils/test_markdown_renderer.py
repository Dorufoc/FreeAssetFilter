# -*- coding: utf-8 -*-
"""markdown_renderer.py（freeassetfilter/utils/markdown_renderer.py）单元测试。

覆盖标题（含 id 重写）、粗斜体、fenced code 代码块（Pygments 高亮 span）、
表格、任务列表（task-item / task-checkbox）、字号设置（含异常）与完整 HTML
文档结构；并验证渲染结果可注入 QTextDocument 且纯文本无损。
"""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtGui import QTextDocument

from freeassetfilter.utils.markdown_renderer import (
    MARKDOWN_AVAILABLE,
    MarkdownRenderer,
)

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def renderer() -> Any:
    """提供已完成可用性检查的渲染器实例。"""
    if not MARKDOWN_AVAILABLE:
        pytest.skip("markdown / pygments 依赖缺失，无法测试渲染")
    return MarkdownRenderer()


class TestAvailability:
    """依赖可用性与基础属性。"""

    def test_is_available(self) -> None:
        """依赖齐备时 is_available/available 返回 True。"""
        if not MARKDOWN_AVAILABLE:
            pytest.skip("markdown / pygments 依赖缺失")
        assert MarkdownRenderer.is_available() is True
        assert MarkdownRenderer.available() is True

    def test_set_font_size(self, renderer: Any) -> None:
        """字号设置会反映到 CSS。"""
        renderer.set_font_size(20)
        html = renderer.render("# 标题")
        assert "font-size: 20px" in html

    def test_set_font_size_non_int_raises(self, renderer: Any) -> None:
        """非整数字号 → TypeError。"""
        with pytest.raises(TypeError):
            renderer.set_font_size("18")  # type: ignore[arg-type]


class TestRendering:
    """Markdown 各语法片段渲染结果。"""

    def test_render_heading(self, renderer: Any) -> None:
        """标题带文档 id（与标题文本一致）并嵌入 h1。"""
        html = renderer.render("# 一级标题")
        assert html.startswith("<!DOCTYPE html>")
        assert "<html>" in html
        assert "<style>" in html
        assert '<h1 id="一级标题">一级标题</h1>' in html

    def test_render_bold_italic(self, renderer: Any) -> None:
        """粗体/斜体转成 strong/em 标签。"""
        html = renderer.render("**加粗**与*斜体*")
        assert "<strong>加粗</strong>" in html
        assert "<em>斜体</em>" in html

    def test_render_code_block(self, renderer: Any) -> None:
        """fenced code + codehilite → highlight/pre/code + Pygments span。"""
        html = renderer.render("```python\nprint('hello')\n```")
        assert 'class="highlight"' in html
        assert "<pre>" in html
        assert "<code>" in html
        assert "<span" in html  # Pygments 高亮片段非空

    def test_render_table(self, renderer: Any) -> None:
        """表格语法 → <table>/<th>/<td>。"""
        html = renderer.render("| a | b |\n|---|---|\n| 1 | 2 |")
        assert "<table>" in html
        assert "<th>a</th>" in html

    def test_render_task_list(self, renderer: Any) -> None:
        """任务列表 → task-item 与 checked/unchecked 复选框标记。"""
        html = renderer.render("- [x] 已完成\n- [ ] 待办")
        assert 'class="task-item"' in html
        assert 'class="task-checkbox checked"' in html
        assert 'class="task-checkbox unchecked"' in html
        assert "\u2611" in html  # ☑
        assert "\u2610" in html  # ☐

    def test_render_empty_text(self, renderer: Any) -> None:
        """空文本也能渲染出完整文档骨架。"""
        html = renderer.render("")
        assert html.startswith("<!DOCTYPE html>")
        assert "<body>" in html

    def test_render_accepts_file_path(self, renderer: Any) -> None:
        """file_path 参数不被拒绝（预留参数）。"""
        html = renderer.render("# X", file_path="sample.md")
        assert "<h1" in html


class TestQTextDocument:
    """渲染结果注入 QTextDocument。"""

    def test_html_loads_into_qtextdocument(self, renderer: Any, qapp: Any) -> None:
        """标题与代码块文本在 QTextDocument 中保留。"""
        html = renderer.render("# 一级标题\n\n```python\nprint('hi')\n```")
        doc = QTextDocument()
        doc.setHtml(html)
        plain = doc.toPlainText()
        assert "一级标题" in plain
        assert "print('hi')" in plain