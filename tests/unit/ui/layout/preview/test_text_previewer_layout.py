# -*- coding: utf-8 -*-
"""
TextPreviewerLayout 单元测试

在隔离环境中测试 freeassetfilter/ui/layout/preview/text_previewer_layout.py
的 TextPreviewerLayout，不依赖 PreviewerRegistry 或 UnifiedPreviewer。

覆盖：
1. 公共 API 表面
2. 纯文本 / Markdown / 代码视图模式切换
3. set_file() 读取临时文件
4. cleanup() 清理状态
5. update_theme() 主题更新
6. 顶栏固定高度
"""

import sys
from pathlib import Path
from typing import Any

# Match the sys.path bootstrap in text_previewer_layout.py so we can import
# components.styled_scroll_area without triggering the full freeassetfilter.ui
# package chain in some test environments.
_UI_ROOT = str(Path(__file__).resolve().parents[5] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

import pytest

from PySide6.QtCore import QPoint, QPointF, Qt, QPropertyAnimation
from PySide6.QtGui import QContextMenuEvent, QPixmap, QWheelEvent, QTextCursor
from PySide6.QtWidgets import QScrollerProperties

from freeassetfilter.ui.components.styled_scroll_area import (
    StyledScrollBar,
    StyledScrollArea,
    _WheelSmoothScrollFilter,
)
from freeassetfilter.ui.layout.preview import text_previewer_layout as tpl


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def text_previewer(qapp) -> tpl.TextPreviewerLayout:
    """创建 TextPreviewerLayout 实例并在测试结束后清理。"""
    layout = tpl.TextPreviewerLayout()
    try:
        yield layout
    finally:
        layout.close()
        layout.deleteLater()


# =============================================================================
# 1. API 表面
# =============================================================================


class TestTextPreviewerLayoutAPISurface:
    """测试公共 API 是否存在且可调用。"""

    def test_api_surface(self, qapp) -> None:
        """验证实例可创建，并暴露 set_file / set_text_content / cleanup / update_theme。"""
        layout = tpl.TextPreviewerLayout()
        try:
            assert callable(layout.set_file)
            assert callable(layout.set_text_content)
            assert callable(layout.cleanup)
            assert callable(layout.update_theme)
            assert hasattr(layout, "close_requested")
        finally:
            layout.close()
            layout.deleteLater()


# =============================================================================
# 2. 视图模式
# =============================================================================


class TestTextPreviewerLayoutModes:
    """测试文件扩展名驱动的视图模式。"""

    def test_plain_text_mode(self, text_previewer: tpl.TextPreviewerLayout) -> None:
        """.txt 文件应进入 plain 模式并显示源码视图（stack index 0）。"""
        text_previewer.set_text_content("hello", "sample.txt", "utf-8")

        assert text_previewer._current_mode == "plain"
        assert text_previewer._content_stack.currentIndex() == 0

    def test_markdown_mode_fallback_when_markdown_missing(
        self,
        qapp,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """MarkdownRenderer 不可用时，.md 应回退到源码视图并隐藏渲染切换按钮。"""

        class FakeMarkdownRenderer:
            @classmethod
            def is_available(cls) -> bool:
                return False

        monkeypatch.setattr(tpl, "_MarkdownRenderer", FakeMarkdownRenderer)
        monkeypatch.setattr(tpl, "MARKDOWN_AVAILABLE", False)

        layout = tpl.TextPreviewerLayout()
        try:
            layout.set_text_content("# Title", "sample.md", "utf-8")
            qapp.processEvents()

            assert layout._content_stack.currentIndex() == 0
            assert layout._render_toggle_btn.isVisible() is False
            assert layout._markdown_renderer is None
            assert "# Title" in layout._source_view._text_edit.toPlainText()
        finally:
            layout.close()
            layout.deleteLater()

    def test_markdown_mode_when_markdown_available(
        self,
        qapp,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """模拟 MarkdownRenderer 可用时，.md 应进入渲染视图并显示切换按钮。"""

        fake_html = (
            "<!DOCTYPE html><html><body>"
            "<h1>Title</h1>"
            "</body></html>"
        )

        class FakeMarkdownRenderer:
            def __init__(self, font_size: int = 14) -> None:
                self.font_size = font_size

            @classmethod
            def is_available(cls) -> bool:
                return True

            def render(self, text: str, file_path: str | None = None) -> str:
                return fake_html

            def set_font_size(self, size: int) -> None:
                self.font_size = size

        monkeypatch.setattr(tpl, "_MarkdownRenderer", FakeMarkdownRenderer)
        monkeypatch.setattr(tpl, "MARKDOWN_AVAILABLE", True)

        layout = tpl.TextPreviewerLayout()
        try:
            layout.set_text_content("# Title", "sample.md", "utf-8")
            layout.show()
            qapp.processEvents()

            assert layout._content_stack.currentIndex() == 1
            assert layout._render_toggle_btn.isVisible() is True
            rendered_html = layout._markdown_view._text_browser.toHtml()
            assert "<h1" in rendered_html
            assert "Title" in rendered_html

            # 切换到源码视图
            layout._render_toggle_btn.click()
            qapp.processEvents()
            assert layout._content_stack.currentIndex() == 0
            assert layout._render_toggle_btn.text() == "渲染"

            # 切回渲染视图
            layout._render_toggle_btn.click()
            qapp.processEvents()
            assert layout._content_stack.currentIndex() == 1
            rendered_html = layout._markdown_view._text_browser.toHtml()
            assert "<h1" in rendered_html
            assert "Title" in rendered_html
        finally:
            layout.close()
            layout.deleteLater()

    def test_markdown_renderer_failure_falls_back_to_source_view(
        self,
        qapp,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """MarkdownRenderer.render() 抛异常时，应回退到源码视图并保留原始 Markdown 源码。"""

        class FakeMarkdownRenderer:
            def __init__(self, font_size: int = 14) -> None:
                self.font_size = font_size

            @classmethod
            def is_available(cls) -> bool:
                return True

            def render(self, text: str, file_path: str | None = None) -> str:
                raise RuntimeError("forced render failure")

            def set_font_size(self, size: int) -> None:
                self.font_size = size

        monkeypatch.setattr(tpl, "_MarkdownRenderer", FakeMarkdownRenderer)
        monkeypatch.setattr(tpl, "MARKDOWN_AVAILABLE", True)

        layout = tpl.TextPreviewerLayout()
        try:
            layout.set_text_content("# Title", "sample.md", "utf-8")
            qapp.processEvents()

            assert layout._content_stack.currentIndex() == 0
            source = layout._source_view._text_edit.toPlainText()
            assert source == "# Title"
            assert "forced render failure" not in source
        finally:
            layout.close()
            layout.deleteLater()

    def test_code_mode(self, text_previewer: tpl.TextPreviewerLayout) -> None:
        """.py 文件应进入 code 模式并附加语法高亮器。"""
        text_previewer.set_text_content("x = 1\n", "sample.py", "utf-8")

        assert text_previewer._current_mode == "code"
        assert text_previewer._highlighter is not None


# =============================================================================
# 3. 文件加载
# =============================================================================


class TestTextPreviewerLayoutSetFile:
    """测试 set_file() 读取真实文件。"""

    def test_set_file_with_temp_file(
        self, qapp, tmp_path: Path
    ) -> None:
        """创建临时文本文件并通过 set_file() 加载，验证路径与内容。"""
        txt_file = tmp_path / "temp_sample.txt"
        txt_file.write_text("temporary content", encoding="utf-8")

        layout = tpl.TextPreviewerLayout()
        try:
            layout.set_file(str(txt_file))

            assert layout._current_file.endswith("temp_sample.txt")
            assert "temporary content" in layout._source_view._text_edit.toPlainText()
        finally:
            layout.close()
            layout.deleteLater()


# =============================================================================
# 4. 清理
# =============================================================================


class TestTextPreviewerLayoutCleanup:
    """测试 cleanup() 重置状态。"""

    def test_cleanup(self, text_previewer: tpl.TextPreviewerLayout) -> None:
        """cleanup() 后应回到覆盖层，并清空文本与文件状态。"""
        text_previewer.set_text_content("hello", "sample.txt", "utf-8")
        text_previewer.cleanup()

        assert text_previewer._content_stack.currentIndex() == 2
        assert text_previewer._source_view._text_edit.toPlainText() == ""
        assert text_previewer._markdown_view.toPlainText() == ""
        assert text_previewer._current_file == ""
        assert text_previewer._current_text == ""
        assert text_previewer._current_mode == "plain"


# =============================================================================
# 5. 主题更新
# =============================================================================


class TestTextPreviewerLayoutTheme:
    """测试 update_theme() 行为。"""

    def test_update_theme(self, text_previewer: tpl.TextPreviewerLayout) -> None:
        """update_theme() 不抛异常，并在代码模式下重建高亮器。"""
        text_previewer.set_text_content("x = 1\n", "sample.py", "utf-8")
        assert text_previewer._highlighter is not None

        original = text_previewer._highlighter
        text_previewer._highlighter = None

        text_previewer.update_theme()

        assert text_previewer._highlighter is not None
        assert text_previewer._highlighter is not original

    def test_code_mode_uses_vscode_dark_when_dark(
        self,
        text_previewer: tpl.TextPreviewerLayout,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """代码模式在深色主题下应使用 vscode_dark 配色方案。"""
        monkeypatch.setattr(tpl.tm, "is_dark_theme", lambda: True)
        text_previewer.set_text_content("x = 1\n", "sample.py", "utf-8")

        assert text_previewer._highlighter is not None
        assert text_previewer._highlighter.faf_highlighter.color_scheme.name == "vscode_dark"

    def test_code_mode_uses_vscode_light_when_light(
        self,
        text_previewer: tpl.TextPreviewerLayout,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """代码模式在浅色主题下应使用 vscode_light 配色方案。"""
        monkeypatch.setattr(tpl.tm, "is_dark_theme", lambda: False)
        text_previewer.set_text_content("x = 1\n", "sample.py", "utf-8")

        assert text_previewer._highlighter is not None
        assert text_previewer._highlighter.faf_highlighter.color_scheme.name == "vscode_light"

    def test_update_theme_reacts_to_runtime_dark_mode_change(
        self,
        text_previewer: tpl.TextPreviewerLayout,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """update_theme() 应根据 tm.is_dark_theme() 重新选择配色方案。"""
        monkeypatch.setattr(tpl.tm, "is_dark_theme", lambda: True)
        text_previewer.set_text_content("x = 1\n", "sample.py", "utf-8")
        assert text_previewer._highlighter.faf_highlighter.color_scheme.name == "vscode_dark"

        monkeypatch.setattr(tpl.tm, "is_dark_theme", lambda: False)
        text_previewer.update_theme()
        assert text_previewer._highlighter.faf_highlighter.color_scheme.name == "vscode_light"


# =============================================================================
# 6. Markdown 代码块 CSS
# =============================================================================


class TestMarkdownRendererCodeBlocks:
    """测试 MarkdownRenderer 生成的代码块 CSS 与 HTML 结构。"""

    def test_build_css_highlight_uses_fill_background_and_mid_border(self) -> None:
        """.highlight pre 规则应使用 tm.fill 作为背景色，并带有 1px tm.mid 边框；
        .highlight 容器仅负责块状排布与垂直间距。"""
        css = tpl._MarkdownRenderer()._build_css()

        highlight_section = css.split(".highlight {")[1].split("}")[0]
        assert "display: block;" in highlight_section
        assert "margin: 12px 0;" in highlight_section
        assert "background-color:" not in highlight_section
        assert "border:" not in highlight_section

        highlight_pre_section = css.split(".highlight pre {")[1].split("}")[0]
        assert f"background-color: {tpl.tm.fill.name()};" in highlight_pre_section
        assert f"border: 1px solid {tpl.tm.mid.name()};" in highlight_pre_section
        assert "padding: 12px;" in highlight_pre_section
        assert "border-radius: 6px;" in highlight_pre_section
        assert "margin: 0;" in highlight_pre_section

    def test_build_css_pre_is_transparent(self) -> None:
        """pre 与 pre code 应保持透明背景，无内边距与外边距。"""
        css = tpl._MarkdownRenderer()._build_css()
        pre_section = css.split("pre {")[1].split("}")[0]
        assert "background-color: transparent;" in pre_section
        assert "padding: 0;" in pre_section
        assert "border-radius: 0;" in pre_section
        assert "margin: 0;" in pre_section

        pre_code_section = css.split("pre code {")[1].split("}")[0]
        assert "background-color: transparent;" in pre_code_section
        assert "padding: 0;" in pre_code_section
        assert "border-radius: 0;" in pre_code_section

    def test_render_code_block_wrapped_in_highlight_div(self, qapp) -> None:
        """fenced code block 应渲染为 <div class='highlight'><pre><code>。"""
        if not tpl.MARKDOWN_AVAILABLE:
            pytest.skip("markdown and pygments are required")
        html = tpl._MarkdownRenderer().render(
            "```python\ndef hello():\n    pass\n```"
        )
        assert '<div class="highlight"><pre><span></span><code>' in html
        assert "</code></pre></div>" in html

    def test_custom_css_comes_after_pygments(self, qapp) -> None:
        """自定义 CSS 应输出在 Pygments CSS 之后，覆盖其 .highlight 背景。"""
        if not tpl.MARKDOWN_AVAILABLE:
            pytest.skip("markdown and pygments are required")
        html = tpl._MarkdownRenderer().render("# hello")
        style_start = html.find("<style>")
        pygments_highlight = html.find(".highlight { background:")
        assert pygments_highlight != -1
        assert style_start != -1
        assert pygments_highlight < style_start


# =============================================================================
# 7. Markdown 超链接右键菜单
# =============================================================================


class TestMarkdownLinkContextMenu:
    """测试 Markdown 渲染视图中超链接的右键上下文菜单。"""

    def test_context_menu_on_link_shows_actions(
        self, qapp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """右键命中链接时应弹出含"在浏览器中打开"和"复制链接"的菜单。"""
        browser = tpl._LinkTextBrowser()
        try:
            browser.setHtml('<a href="https://example.com">link</a>')

            captured: dict[str, Any] = {}

            def fake_exec(self, pos: QPoint) -> None:
                captured["menu"] = self
                captured["pos"] = pos

            monkeypatch.setattr(tpl.StyledContextMenu, "exec", fake_exec)
            # 强制让 anchorAt 返回一个链接，避免依赖布局坐标
            browser.anchorAt = lambda pos: "https://example.com"  # type: ignore[method-assign]

            event = QContextMenuEvent(
                QContextMenuEvent.Mouse, QPoint(0, 0), QPoint(100, 100)
            )
            browser.contextMenuEvent(event)

            assert "menu" in captured
            actions = [a.text() for a in captured["menu"].actions()]
            assert "在浏览器中打开" in actions
            assert "复制链接" in actions
        finally:
            browser.close()
            browser.deleteLater()

    def test_open_anchor_resolves_relative_link(
        self, qapp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """相对链接应基于当前 Markdown 文件目录解析为本地绝对路径。"""
        md_file = tmp_path / "folder" / "sample.md"
        md_file.parent.mkdir(parents=True, exist_ok=True)
        md_file.write_text("# Sample", encoding="utf-8")

        opened: list[str] = []
        monkeypatch.setattr(
            tpl.QDesktopServices, "openUrl", lambda url: opened.append(url.toString())
        )

        browser = tpl._LinkTextBrowser()
        try:
            browser.set_current_file(str(md_file))
            browser._open_anchor("./image.png")

            assert len(opened) == 1
            assert opened[0].endswith("folder/image.png")
        finally:
            browser.close()
            browser.deleteLater()

    def test_context_menu_without_link_shows_select_all(
        self, qapp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """未命中链接且无选区时，仍应弹出只含 全选 的 StyledContextMenu。"""
        browser = tpl._LinkTextBrowser()
        try:
            browser.setHtml("<p>plain text</p>")

            captured: dict[str, Any] = {}

            def fake_exec(self, pos: QPoint) -> None:
                captured["menu"] = self
                captured["pos"] = pos

            monkeypatch.setattr(tpl.StyledContextMenu, "exec", fake_exec)
            # 确保未命中链接
            browser.anchorAt = lambda pos: ""  # type: ignore[method-assign]

            event = QContextMenuEvent(
                QContextMenuEvent.Mouse, QPoint(0, 0), QPoint(100, 100)
            )
            browser.contextMenuEvent(event)

            assert "menu" in captured
            actions = [a.text() for a in captured["menu"].actions() if a.text()]
            assert actions == ["全选"]
        finally:
            browser.close()
            browser.deleteLater()

    def test_context_menu_with_selection_shows_copy_selected_text(
        self, qapp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """存在文本选区时，菜单应包含 复制选中文字 和 全选。"""
        browser = tpl._LinkTextBrowser()
        try:
            browser.setHtml("<p>select this text</p>")

            captured: dict[str, Any] = {}

            def fake_exec(self, pos: QPoint) -> None:
                captured["menu"] = self
                captured["pos"] = pos

            monkeypatch.setattr(tpl.StyledContextMenu, "exec", fake_exec)
            browser.anchorAt = lambda pos: ""  # type: ignore[method-assign]

            cursor = browser.textCursor()
            cursor.setPosition(0)
            cursor.setPosition(10, QTextCursor.KeepAnchor)
            browser.setTextCursor(cursor)
            assert browser.textCursor().hasSelection()

            event = QContextMenuEvent(
                QContextMenuEvent.Mouse, QPoint(0, 0), QPoint(100, 100)
            )
            browser.contextMenuEvent(event)

            assert "menu" in captured
            actions = [a.text() for a in captured["menu"].actions() if a.text()]
            assert "复制选中文字" in actions
            assert "全选" in actions
        finally:
            browser.close()
            browser.deleteLater()

    def test_context_menu_copy_selected_text_copies_to_clipboard(
        self, qapp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """点击 复制选中文字 应将选区文本写入剪贴板。"""
        browser = tpl._LinkTextBrowser()
        try:
            browser.setHtml("<p>hello world</p>")

            clip_text: list[str] = []
            monkeypatch.setattr(
                tpl.QApplication.clipboard(), "setText", clip_text.append
            )

            cursor = browser.textCursor()
            cursor.setPosition(1)
            cursor.setPosition(4, QTextCursor.KeepAnchor)
            browser.setTextCursor(cursor)

            browser._copy_selected_text()

            assert len(clip_text) == 1
            assert clip_text[0] == "ell"
        finally:
            browser.close()
            browser.deleteLater()


# =============================================================================
# 9. 顶栏高度
# =============================================================================


class TestTextPreviewerLayoutTopBar:
    """测试顶栏几何属性。"""

    def test_top_bar_height(self, qapp) -> None:
        """layout.show() 后顶栏高度应为 48px。"""
        layout = tpl.TextPreviewerLayout()
        try:
            layout.show()
            qapp.processEvents()

            assert layout._top_bar.height() == 48
        finally:
            layout.close()
            layout.deleteLater()


# =============================================================================
# 10. 统一滚动行为
# =============================================================================


class TestUnifiedScrolling:
    """测试源码/Markdown 视图使用统一的平滑滚动配置与滚动条。"""

    # Fixture-like helper -----------------------------------------------------

    @staticmethod
    def _setup_markdown_layout(
        qapp,
        monkeypatch: pytest.MonkeyPatch,
    ) -> tpl.TextPreviewerLayout:
        """Create a layout with a fake MarkdownRenderer so rendered view works."""

        class FakeMarkdownRenderer:
            def __init__(self, font_size: int = 14) -> None:
                self.font_size = font_size

            @classmethod
            def is_available(cls) -> bool:
                return True

            def render(self, text: str, file_path: str | None = None) -> str:
                # Wrap each line in a paragraph so the document is tall.
                body = "\n".join(f"<p>{line}</p>" for line in text.splitlines())
                return f"<!DOCTYPE html><html><body>{body}</body></html>"

            def set_font_size(self, size: int) -> None:
                self.font_size = size

        monkeypatch.setattr(tpl, "_MarkdownRenderer", FakeMarkdownRenderer)
        monkeypatch.setattr(tpl, "MARKDOWN_AVAILABLE", True)

        layout = tpl.TextPreviewerLayout()
        layout.show()
        qapp.processEvents()
        return layout

    @staticmethod
    def _send_wheel_down(viewport) -> None:
        """Post a downward QWheelEvent to *viewport* through the event loop."""
        event = QWheelEvent(
            QPointF(10, 10),
            QPointF(10, 10),
            QPoint(0, -120),
            QPoint(0, -120),
            Qt.NoButton,
            Qt.NoModifier,
            Qt.ScrollUpdate,
            False,
        )
        from PySide6.QtWidgets import QApplication

        QApplication.sendEvent(viewport, event)

    # StyledScrollBar exposure -------------------------------------------------

    def test_source_view_vertical_scrollbar_is_styled(self, text_previewer: tpl.TextPreviewerLayout) -> None:
        """源码视图的 verticalScrollBar() 应返回自定义 StyledScrollBar。"""
        vbar = text_previewer._source_view.verticalScrollBar()
        assert isinstance(vbar, StyledScrollBar)

    def test_markdown_view_vertical_scrollbar_is_styled(
        self,
        qapp,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Markdown 视图的 verticalScrollBar() 应返回自定义 StyledScrollBar。"""
        layout = self._setup_markdown_layout(qapp, monkeypatch)
        try:
            vbar = layout._markdown_view.verticalScrollBar()
            assert isinstance(vbar, StyledScrollBar)
        finally:
            layout.close()
            layout.deleteLater()

    # Wheel filter installed on viewport ----------------------------------------

    def test_source_view_wheel_filter_installed_on_viewport(
        self,
        qapp,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """源码视图应将 _wheel_filter 安装到 viewport() 上。"""
        original = qapp.__class__.installEventFilter
        installed: list[tuple[Any, Any]] = []

        def _patched_install(self, filter_obj) -> None:
            installed.append((self, filter_obj))
            original(self, filter_obj)

        monkeypatch.setattr("PySide6.QtCore.QObject.installEventFilter", _patched_install)

        layout = tpl.TextPreviewerLayout()
        try:
            viewport = layout._source_view._content_widget.viewport()
            wheel_filter = layout._source_view._wheel_filter
            assert wheel_filter is not None
            assert any(self is viewport and f is wheel_filter for self, f in installed)
        finally:
            layout.close()
            layout.deleteLater()

    def test_markdown_view_wheel_filter_installed_on_viewport(
        self,
        qapp,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Markdown 视图应将 _wheel_filter 安装到 viewport() 上。"""
        original = qapp.__class__.installEventFilter
        installed: list[tuple[Any, Any]] = []

        def _patched_install(self, filter_obj) -> None:
            installed.append((self, filter_obj))
            original(self, filter_obj)

        monkeypatch.setattr("PySide6.QtCore.QObject.installEventFilter", _patched_install)

        layout = self._setup_markdown_layout(qapp, monkeypatch)
        try:
            viewport = layout._markdown_view._content_widget.viewport()
            wheel_filter = layout._markdown_view._wheel_filter
            assert wheel_filter is not None
            assert any(self is viewport and f is wheel_filter for self, f in installed)
        finally:
            layout.close()
            layout.deleteLater()

    # Wheel event -> smooth scroll animation ----------------------------------

    def _fill_layout_and_send_wheel(
        self,
        layout: tpl.TextPreviewerLayout,
        qapp,
    ) -> None:
        """Make the layout visible, ensure content exists, send a wheel event."""
        layout.show()
        qapp.processEvents()
        qapp.processEvents()

    def test_wheel_event_triggers_smooth_scroll_in_plain_text_mode(
        self,
        qapp,
        text_previewer: tpl.TextPreviewerLayout,
    ) -> None:
        """纯文本模式下向 viewport 发送滚轮事件应启动平滑滚动动画。"""
        text_previewer.set_text_content("\n".join(f"line {i}" for i in range(200)), "sample.txt", "utf-8")
        self._fill_layout_and_send_wheel(text_previewer, qapp)

        source_view = text_previewer._source_view
        self._send_wheel_down(source_view._content_widget.viewport())

        anim = source_view._wheel_filter._vertical_animation
        assert anim is not None
        assert anim.state() == QPropertyAnimation.Running

    def test_wheel_event_triggers_smooth_scroll_in_code_mode(
        self,
        qapp,
        text_previewer: tpl.TextPreviewerLayout,
    ) -> None:
        """代码模式下向 viewport 发送滚轮事件应启动平滑滚动动画。"""
        text_previewer.set_text_content("\n".join(f"x = {i}" for i in range(200)), "sample.py", "utf-8")
        self._fill_layout_and_send_wheel(text_previewer, qapp)

        source_view = text_previewer._source_view
        self._send_wheel_down(source_view._content_widget.viewport())

        anim = source_view._wheel_filter._vertical_animation
        assert anim is not None
        assert anim.state() == QPropertyAnimation.Running

    def test_wheel_event_triggers_smooth_scroll_in_markdown_mode(
        self,
        qapp,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Markdown 模式下向 viewport 发送滚轮事件应启动平滑滚动动画。"""
        layout = self._setup_markdown_layout(qapp, monkeypatch)
        try:
            layout.set_text_content(
                "\n\n".join(f"paragraph {i}" for i in range(200)),
                "sample.md",
                "utf-8",
            )
            qapp.processEvents()

            md_view = layout._markdown_view
            self._send_wheel_down(md_view._content_widget.viewport())

            anim = md_view._wheel_filter._vertical_animation
            assert anim is not None
            assert anim.state() == QPropertyAnimation.Running
        finally:
            layout.close()
            layout.deleteLater()

    # Wheel step scale --------------------------------------------------------

    def test_source_view_wheel_step_scale_is_one(
        self,
        text_previewer: tpl.TextPreviewerLayout,
    ) -> None:
        """源码视图改为与 Markdown 视图一致的像素滚动，步长比例为 1.0。"""
        text_previewer.set_text_content("x", "sample.txt", "utf-8")
        scale = text_previewer._source_view._wheel_filter._wheel_step_scale
        assert isinstance(scale, float)
        assert scale == pytest.approx(1.0)

    def test_markdown_view_wheel_step_scale_is_one(
        self,
        qapp,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Markdown 视图滚轮步长比例应保持为 1.0。"""
        layout = self._setup_markdown_layout(qapp, monkeypatch)
        try:
            scale = layout._markdown_view._wheel_filter._wheel_step_scale
            assert isinstance(scale, float)
            assert scale == pytest.approx(1.0)
        finally:
            layout.close()
            layout.deleteLater()

    # QScroller profile -------------------------------------------------------

    def test_source_view_scroller_profile_matches_default(
        self,
        qapp,
        text_previewer: tpl.TextPreviewerLayout,
    ) -> None:
        """源码视图 QScrollerProperties 应与 StyledScrollArea.DEFAULT_PROFILE 一致。"""
        text_previewer.show()
        qapp.processEvents()

        props = tpl.QScroller.scroller(
            text_previewer._source_view._content_widget.viewport()
        ).scrollerProperties()
        profile = StyledScrollArea.DEFAULT_PROFILE

        assert props.scrollMetric(QScrollerProperties.DragVelocitySmoothingFactor) == pytest.approx(
            profile["drag_velocity_smoothing"]
        )
        assert props.scrollMetric(QScrollerProperties.DecelerationFactor) == pytest.approx(
            profile["deceleration"]
        )
        assert props.scrollMetric(QScrollerProperties.MaximumVelocity) == pytest.approx(
            profile["maximum_velocity"]
        )

    def test_markdown_view_scroller_profile_matches_default(
        self,
        qapp,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Markdown 视图 QScrollerProperties 应与 StyledScrollArea.DEFAULT_PROFILE 一致。"""
        layout = self._setup_markdown_layout(qapp, monkeypatch)
        try:
            props = tpl.QScroller.scroller(
                layout._markdown_view._content_widget.viewport()
            ).scrollerProperties()
            profile = StyledScrollArea.DEFAULT_PROFILE

            assert props.scrollMetric(QScrollerProperties.DragVelocitySmoothingFactor) == pytest.approx(
                profile["drag_velocity_smoothing"]
            )
            assert props.scrollMetric(QScrollerProperties.DecelerationFactor) == pytest.approx(
                profile["deceleration"]
            )
            assert props.scrollMetric(QScrollerProperties.MaximumVelocity) == pytest.approx(
                profile["maximum_velocity"]
            )
        finally:
            layout.close()
            layout.deleteLater()


# =============================================================================
# 11. 搜索侧边栏增强
# =============================================================================


class TestSearchSidebarEnhancement:
    """搜索侧边栏增强相关的回归测试。"""

    @staticmethod
    def _patch_checkbox_api(layout: tpl.TextPreviewerLayout) -> None:
        """为布局实例内的 StyledCheckbox 补充测试所需的 QCheckBox 兼容方法。"""
        for checkbox in (layout._regex_checkbox, layout._case_checkbox):
            checkbox.isChecked = lambda cb=checkbox: cb._checked  # type: ignore[method-assign]
            checkbox.setChecked = (  # type: ignore[method-assign]
                lambda value, cb=checkbox: cb.set_checked_no_signal(value)
            )

    def test_search_drawer_controls_exist(self, qapp) -> None:
        """搜索抽屉应包含输入框、搜索按钮、正则框和大小写框。"""
        layout = tpl.TextPreviewerLayout()
        try:
            layout.show()
            qapp.processEvents()
            layout._toggle_search_drawer()
            qapp.processEvents()

            assert layout._search_input is not None
            assert layout._search_action_btn is not None
            assert layout._regex_checkbox is not None
            assert layout._case_checkbox is not None
        finally:
            layout.close()
            layout.deleteLater()

    def test_literal_search_finds_expected_matches(self, qapp) -> None:
        """字面搜索应返回预期条数并更新状态标签。"""
        layout = tpl.TextPreviewerLayout()
        try:
            self._patch_checkbox_api(layout)
            layout.set_text_content("hello world hello", "sample.txt", "utf-8")
            layout._search_input.setText("hello")
            layout._regex_checkbox.setChecked(False)
            layout._case_checkbox.setChecked(False)
            layout._do_search()
            qapp.processEvents()

            assert layout._search_model.rowCount() == 2
            assert layout._search_status.text().startswith("找到")
        finally:
            layout.close()
            layout.deleteLater()

    def test_invalid_regex_falls_back_to_literal(self, qapp) -> None:
        """非法正则输入应回退为普通文本搜索，结果非空并提示回退；懒加载仍按字面模式继续。"""
        layout = tpl.TextPreviewerLayout()
        try:
            self._patch_checkbox_api(layout)
            layout.set_text_content("a [b] c", "sample.txt", "utf-8")
            layout._search_input.setText("[")
            layout._regex_checkbox.setChecked(True)
            layout._case_checkbox.setChecked(False)
            layout._do_search()
            qapp.processEvents()

            assert layout._search_model.rowCount() >= 1
            assert "正则语法错误" in layout._search_status.text()

            # 超过一批次的字面回退：150 个 `[` 应先返回 100 条，加载更多后全部 150 条。
            layout.set_text_content("[" * 150, "sample.txt", "utf-8")
            layout._search_input.setText("[")
            layout._regex_checkbox.setChecked(True)
            layout._case_checkbox.setChecked(False)
            layout._do_search()
            qapp.processEvents()

            assert layout._search_model.rowCount() == 100
            assert layout._search_state is not None
            assert layout._search_state.regex_enabled is False

            layout._load_more_results()
            qapp.processEvents()

            assert layout._search_model.rowCount() == 150
            assert layout._search_state.regex_enabled is False
        finally:
            layout.close()
            layout.deleteLater()

    def test_markdown_rendered_search_uses_plain_text(
        self,
        qapp,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Markdown 渲染视图下搜索的是渲染后纯文本，不含 Markdown 源码标记。"""

        class FakeMarkdownRenderer:
            def __init__(self, font_size: int = 14) -> None:
                self.font_size = font_size

            @classmethod
            def is_available(cls) -> bool:
                return True

            def render(self, text: str, file_path: str | None = None) -> str:
                return "<!DOCTYPE html><html><body><p>标题内容</p></body></html>"

            def set_font_size(self, size: int) -> None:
                self.font_size = size

        monkeypatch.setattr(tpl, "_MarkdownRenderer", FakeMarkdownRenderer)
        monkeypatch.setattr(tpl, "MARKDOWN_AVAILABLE", True)

        layout = tpl.TextPreviewerLayout()
        try:
            self._patch_checkbox_api(layout)
            layout.set_text_content("# 标题内容", "sample.md", "utf-8")
            qapp.processEvents()
            assert layout._content_stack.currentIndex() == 1

            layout._search_input.setText("标题")
            layout._regex_checkbox.setChecked(False)
            layout._case_checkbox.setChecked(False)
            layout._do_search()
            qapp.processEvents()
            assert layout._search_model.rowCount() >= 1

            layout._search_input.setText("# 标题")
            layout._do_search()
            qapp.processEvents()
            assert layout._search_model.rowCount() == 0
        finally:
            layout.close()
            layout.deleteLater()

    def test_click_result_selects_match_in_active_view(self, qapp) -> None:
        """点击搜索结果后，当前视图中的目标控件应选中对应范围。"""
        layout = tpl.TextPreviewerLayout()
        try:
            self._patch_checkbox_api(layout)
            layout.set_text_content("hello world hello", "sample.txt", "utf-8")
            layout._search_input.setText("world")
            layout._regex_checkbox.setChecked(False)
            layout._case_checkbox.setChecked(False)
            layout._do_search()
            qapp.processEvents()

            assert layout._search_model.rowCount() >= 1
            match = layout._search_model.match_at(0)
            assert match is not None

            index = layout._search_model.index(0, 0)
            layout._on_search_result_clicked(index)
            qapp.processEvents()

            cursor = layout._source_view._text_edit.textCursor()
            assert cursor.hasSelection()
            assert len(cursor.selectedText()) == match.end - match.start
        finally:
            layout.close()
            layout.deleteLater()
