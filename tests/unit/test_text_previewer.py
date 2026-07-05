# -*- coding: utf-8 -*-
"""
text_previewer 组件测试
测试 freeassetfilter/components/text_previewer.py 的 TextPreviewer / TextPreviewWidget

测试覆盖：
1. TextPreviewer 创建与基本属性
2. set_file() 加载文本文件（有效/无效路径）
3. 内容显示（纯文本、Markdown、代码高亮）
4. 查找/搜索功能
5. cleanup 清理资源
"""

import pytest
from unittest.mock import MagicMock, patch


class TestTextPreviewerCreation:
    """测试 TextPreviewer 创建"""

    def test_previewer_can_be_created(self, qapp):
        """测试 TextPreviewer 可以正常创建并初始化"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            assert viewer is not None
            assert viewer.preview_widget is not None
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_previewer_has_text_edit(self, qapp):
        """测试 TextPreviewer 包含 text_edit 组件"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            assert hasattr(widget, "text_edit")
            assert widget.text_edit is not None
            assert widget.text_edit.isReadOnly() is True
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_previewer_has_search_bar_initially_hidden(self, qapp):
        """测试搜索栏初始状态为隐藏"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            assert hasattr(widget, "search_bar")
            assert widget.search_bar.isVisible() is False
            assert widget.search_info_label.text() == "0/0"
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_previewer_has_font_size_slider(self, qapp):
        """测试字体大小滑块已初始化"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            assert hasattr(widget, "font_size_slider")
            # D_ProgressBar 使用 _minimum/_maximum 私有属性存储范围
            assert widget.font_size_slider._minimum == 4
            assert widget.font_size_slider._maximum == 40
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_previewer_initial_state_empty(self, qapp):
        """测试初始状态为空"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            assert widget.current_file_path == ""
            assert widget.current_encoding == "auto"
            assert widget.is_markdown is False
            assert widget.file_content == ""
        finally:
            viewer.close()
            viewer.deleteLater()


class TestTextPreviewerSetFile:
    """测试 TextPreviewer.set_file 加载文本文件功能"""

    def test_set_file_with_valid_path(self, qapp, tmp_path):
        """测试 set_file 对有效路径设置 current_file_path"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        # 创建临时文本文件
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Hello, World!", encoding="utf-8")

        viewer = TextPreviewer()
        try:
            # 拦截异步加载以避免线程问题
            with patch.object(
                viewer.preview_widget, "_load_file_async"
            ) as mock_load:
                viewer.set_file(str(txt_file))
                mock_load.assert_called_once()
                assert viewer.preview_widget.current_file_path == str(txt_file)
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_set_file_with_invalid_path_no_crash(self, qapp):
        """测试 set_file 对无效路径不崩溃"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            # 无效路径应该静默返回，不触发异步加载
            with patch.object(
                viewer.preview_widget, "_load_file_async"
            ) as mock_load:
                viewer.set_file("/nonexistent/path/file.txt")
                mock_load.assert_not_called()
                assert viewer.preview_widget.current_file_path == ""
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_set_file_with_empty_path_no_crash(self, qapp):
        """测试 set_file 对空路径不崩溃"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            with patch.object(
                viewer.preview_widget, "_load_file_async"
            ) as mock_load:
                viewer.set_file("")
                mock_load.assert_not_called()
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_set_file_triggers_reset_and_loading(self, qapp, tmp_path):
        """测试 set_file 触发状态重置和加载动画"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        txt_file = tmp_path / "test.txt"
        txt_file.write_text("content", encoding="utf-8")

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            with patch.object(widget, "_reset_display_state") as mock_reset, \
                 patch.object(widget, "_start_loading") as mock_start:
                viewer.set_file(str(txt_file))
                mock_reset.assert_called_once()
                mock_start.assert_called_once()
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_set_file_stops_previous_thread(self, qapp, tmp_path):
        """测试 set_file 在加载新文件前停止旧线程（abort 可能被多次调用）"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        txt_file = tmp_path / "test.txt"
        txt_file.write_text("content", encoding="utf-8")

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            # 模拟一个正在运行的线程
            mock_thread = MagicMock()
            mock_thread.isRunning.return_value = True
            widget._thread = mock_thread

            viewer.set_file(str(txt_file))
            # set_file 和 _load_file_async 都可能调用 abort，
            # 至少被调用一次即可验证线程被停止
            assert mock_thread.abort.called
            assert mock_thread.wait.called
        finally:
            viewer.close()
            viewer.deleteLater()


class TestTextPreviewerContent:
    """测试文本内容显示"""

    def test_on_file_loaded_plain_text(self, qapp):
        """测试文件加载完成后纯文本显示"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            # 设置文件路径使 file_type 检测为纯文本
            widget.current_file_path = "/fake/file.txt"

            # 模拟异步加载成功的回调
            widget._on_file_loaded("Hello\nWorld\nLine 3", True)

            assert widget.file_content == "Hello\nWorld\nLine 3"
            assert widget.is_markdown is False
            # 文本内容应已在 text_edit 中
            assert "Hello" in widget.text_edit.toPlainText()
            assert "World" in widget.text_edit.toPlainText()
            assert "Line 3" in widget.text_edit.toPlainText()
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_on_file_loaded_failure(self, qapp):
        """测试文件加载失败时内容不变"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            widget.current_file_path = "/fake/file.txt"

            # 成功加载先设置内容
            widget._on_file_loaded("Initial content", True)
            assert widget.file_content == "Initial content"

            # 失败回调不应影响已有内容
            widget._on_file_loaded("", False)
            # file_content 不会更新
            assert widget.file_content == "Initial content"
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_on_file_loaded_markdown(self, qapp):
        """测试 Markdown 文件加载（按 markdown 库是否可用自适应）"""
        from freeassetfilter.components.text_previewer import (
            TextPreviewer,
            MARKDOWN_AVAILABLE,
        )

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            widget.current_file_path = "/fake/file.md"

            widget._on_file_loaded("# Title\n\n**bold** text", True)

            if MARKDOWN_AVAILABLE:
                assert widget.is_markdown is True
                rendered = widget.text_edit.toPlainText()
                assert "Title" in rendered
            else:
                # 无 markdown 库时回退为纯文本渲染
                assert widget.is_markdown is False
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_on_file_loaded_python_code(self, qapp):
        """测试 Python 代码文件加载后创建语法高亮器"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            widget.current_file_path = "/fake/script.py"

            widget._on_file_loaded("def hello():\n    pass", True)

            # 代码文件应创建高亮器
            assert widget.current_highlighter is not None
            assert widget.is_markdown is False
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_file_type_detection(self, qapp):
        """测试文件类型检测"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget

            assert widget._detect_file_type("file.md") == "markdown"
            assert widget._detect_file_type("file.markdown") == "markdown"
            assert widget._detect_file_type("file.txt") == "text"
            assert widget._detect_file_type("file.py") == "code"
            assert widget._detect_file_type("file.json") in ("code", "text")
            assert widget._detect_file_type("file.unknown") == "text"
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_encoding_selection_triggers_reload(self, qapp, tmp_path):
        """测试切换编码触发重新加载"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        txt_file = tmp_path / "test.txt"
        txt_file.write_text("test", encoding="utf-8")

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            widget.current_file_path = str(txt_file)

            with patch.object(widget, "set_file") as mock_set_file:
                widget._on_encoding_selected("UTF-8")
                mock_set_file.assert_called_once_with(str(txt_file))
        finally:
            viewer.close()
            viewer.deleteLater()


class TestTextPreviewerSearch:
    """测试查找/搜索功能"""

    def _setup_content(self, widget):
        """为搜索测试准备内容（直接注入）"""
        widget.current_file_path = "/fake/search.txt"
        widget._on_file_loaded(
            "apple banana cherry\nbanana orange\napple pie banana", True
        )

    def test_search_finds_matches(self, qapp):
        """测试搜索找到匹配项"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            self._setup_content(widget)

            # 触发搜索
            widget.search_input.setText("banana")
            widget._perform_search()

            assert len(widget._search_results) > 0
            assert widget._current_search_index >= 0
            assert "banana" in widget._search_term
            # 搜索信息标签显示匹配数
            assert "/" in widget.search_info_label.text()
            total = int(widget.search_info_label.text().split("/")[1])
            assert total >= 2
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_search_no_matches(self, qapp):
        """测试搜索无匹配项"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            self._setup_content(widget)

            widget.search_input.setText("nonexistent")
            widget._perform_search()

            assert len(widget._search_results) == 0
            assert widget.search_info_label.text() == "0/0"
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_search_clear(self, qapp):
        """测试清除搜索状态"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            self._setup_content(widget)

            # 先执行搜索
            widget.search_input.setText("banana")
            widget._perform_search()
            assert len(widget._search_results) > 0

            # 清除搜索
            widget._clear_search()
            assert widget._search_term == ""
            assert len(widget._search_results) == 0
            assert widget._current_search_index == -1
            assert widget.search_info_label.text() == "0/0"
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_search_navigation(self, qapp):
        """测试搜索上/下一个导航"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            self._setup_content(widget)

            widget.search_input.setText("banana")
            widget._perform_search()

            assert widget._search_results is not None
            initial_index = widget._current_search_index

            # 下一个
            widget._go_to_next_match()
            assert widget._current_search_index == (
                initial_index + 1
            ) % len(widget._search_results)

            # 上一个
            widget._go_to_previous_match()
            assert widget._current_search_index == initial_index
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_search_empty_text_clears(self, qapp):
        """测试空搜索文本清除搜索结果"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            self._setup_content(widget)

            widget.search_input.setText("banana")
            widget._perform_search()
            assert len(widget._search_results) > 0

            # 空文本应清除搜索
            widget.search_input.setText("")
            widget._on_search_text_changed("")
            # _on_search_text_changed 调用 _clear_search
            assert widget._search_term == ""
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_search_toggle_visibility(self, qapp):
        """测试搜索栏切换显示/隐藏（使用 isHidden 判断本地可见性）"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            viewer.show()
            qapp.processEvents()
            widget = viewer.preview_widget
            # 初始隐藏
            assert widget.search_bar.isHidden() is True

            # 显示搜索栏
            widget._toggle_search()
            assert widget.search_bar.isHidden() is False

            # 隐藏搜索栏
            widget._toggle_search()
            assert widget.search_bar.isHidden() is True
        finally:
            viewer.close()
            viewer.deleteLater()


class TestTextPreviewerCleanup:
    """测试清理功能"""

    def test_cleanup_clears_search_state(self, qapp):
        """测试 cleanup 清除搜索状态"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            # 设置一些搜索状态
            widget._search_term = "test"
            widget._search_results = [0, 5, 10]
            widget._current_search_index = 1

            widget.cleanup()

            assert widget._search_term == ""
            assert widget._search_results == []
            assert widget._current_search_index == -1
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_cleanup_aborts_active_thread(self, qapp):
        """测试 cleanup 终止活动线程"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            mock_thread = MagicMock()
            mock_thread.isRunning.return_value = True
            widget._thread = mock_thread

            widget.cleanup()

            mock_thread.abort.assert_called_once()
            mock_thread.wait.assert_called_once_with(2000)
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_cleanup_without_thread(self, qapp):
        """测试无活动线程时 cleanup 不崩溃"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            widget._thread = None
            # 不应抛出异常
            widget.cleanup()
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_text_previewer_cleanup_delegates(self, qapp):
        """测试 TextPreviewer.cleanup 委托给 preview_widget"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            with patch.object(viewer.preview_widget, "cleanup") as mock_cleanup:
                viewer.cleanup()
                mock_cleanup.assert_called_once()
        finally:
            viewer.close()
            viewer.deleteLater()


class TestTextPreviewerFontAndEncoding:
    """测试字体和编码功能"""

    def test_font_size_change(self, qapp):
        """测试字体大小变化"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            # 模拟文件已加载
            widget.file_content = "test"
            widget.current_file_path = "/fake/test.txt"

            original_size = widget.text_edit.font().pointSize()

            # 改变字体大小
            widget._change_font_size("16")
            new_size = widget.text_edit.font().pointSize()
            assert new_size == 16
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_font_size_change_with_invalid_value(self, qapp):
        """测试字体大小无效值不崩溃"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            original_size = widget.text_edit.font().pointSize()

            widget._change_font_size("not_a_number")
            # 大小应保持不变
            assert widget.text_edit.font().pointSize() == original_size
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_hex_to_rgba(self, qapp):
        """测试十六进制颜色转 RGBA"""
        from freeassetfilter.components.text_previewer import TextPreviewer

        viewer = TextPreviewer()
        try:
            widget = viewer.preview_widget
            result = widget._hex_to_rgba("#336699", 0.5)
            assert result == "rgba(51, 102, 153, 0.5)"
        finally:
            viewer.close()
            viewer.deleteLater()
