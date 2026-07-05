# -*- coding: utf-8 -*-
"""
folder_content_list 组件测试
测试 freeassetfilter/components/folder_content_list.py 的 FolderContentList 组件

测试覆盖：
1. FolderContentList 创建与基本属性
2. 自定义参数创建（dpi_scale, global_font, settings_manager）
3. 信号存在性与发射
4. set_path() 路径设置（有效目录/不存在路径/文件路径）
5. load_folder_content 多次调用
6. 路径显示更新
"""

import os
import tempfile
from unittest.mock import MagicMock

import pytest


class TestFolderContentListCreation:
    """测试 FolderContentList 创建与基本属性"""

    def test_widget_can_be_created_with_default_params(self, qapp):
        """测试 FolderContentList 可以使用默认参数创建"""
        from freeassetfilter.components.folder_content_list import FolderContentList

        widget = FolderContentList(settings_manager=MagicMock())
        try:
            assert widget is not None
            assert hasattr(widget, "open_in_selector_requested")
            assert isinstance(widget.current_path, str)
        finally:
            widget.close()
            widget.deleteLater()

    def test_widget_can_be_created_with_custom_params(self, qapp):
        """测试 FolderContentList 可以使用自定义参数创建"""
        from PySide6.QtGui import QFont
        from freeassetfilter.components.folder_content_list import FolderContentList

        settings_mock = MagicMock()
        settings_mock.get_setting.side_effect = lambda key, default=None: default
        font = QFont("Arial", 12)
        widget = FolderContentList(
            dpi_scale=1.5,
            global_font=font,
            settings_manager=settings_mock,
        )
        try:
            assert widget.dpi_scale == 1.5
            assert widget.global_font == font
            assert widget._settings_manager is settings_mock
        finally:
            widget.close()
            widget.deleteLater()


class TestFolderContentListSignals:
    """测试 FolderContentList 信号"""

    def test_open_in_selector_requested_signal_exists(self, qapp):
        """测试 open_in_selector_requested 信号存在并可连接"""
        from freeassetfilter.components.folder_content_list import FolderContentList

        widget = FolderContentList(settings_manager=MagicMock())
        try:
            assert hasattr(widget, "open_in_selector_requested")
            receiver = lambda path, file_info: None
            widget.open_in_selector_requested.connect(receiver)
            widget.open_in_selector_requested.disconnect(receiver)
        finally:
            widget.close()
            widget.deleteLater()

    def test_open_in_selector_requested_emitted_on_button_click(self, qapp):
        """测试点击'在文件选择器中打开'按钮时发射 open_in_selector_requested"""
        from freeassetfilter.components.folder_content_list import FolderContentList

        settings_mock = MagicMock()
        settings_mock.get_setting.side_effect = lambda key, default=None: default
        widget = FolderContentList(settings_manager=settings_mock)
        try:
            widget.show()
            qapp.processEvents()

            received_args = []
            widget.open_in_selector_requested.connect(
                lambda path, file_info: received_args.append((path, file_info))
            )

            # 默认路径为用户主目录(存在), 按钮点击应发射信号
            widget._on_open_in_selector_clicked()
            qapp.processEvents()

            assert len(received_args) == 1
            assert received_args[0][0] == widget.current_path
            assert received_args[0][1]["is_directory"] is True
        finally:
            widget.close()
            widget.deleteLater()


class TestFolderContentListSetPath:
    """测试 FolderContentList.set_path 方法"""

    def test_set_path_with_valid_directory_updates_path(self, qapp):
        """测试 set_path 设置有效目录时更新 current_path 和路径编辑框"""
        from freeassetfilter.components.folder_content_list import FolderContentList

        settings_mock = MagicMock()
        settings_mock.get_setting.side_effect = lambda key, default=None: default
        widget = FolderContentList(settings_manager=settings_mock)
        try:
            widget.show()
            qapp.processEvents()

            with tempfile.TemporaryDirectory() as tmpdir:
                widget.set_path(tmpdir)
                assert widget.current_path == tmpdir
                assert widget.path_edit.get_text() == tmpdir
        finally:
            widget.close()
            widget.deleteLater()

    def test_set_path_with_nonexistent_path_does_not_crash(self, qapp):
        """测试 set_path 传入不存在的路径不会崩溃且不改变当前路径"""
        from freeassetfilter.components.folder_content_list import FolderContentList

        settings_mock = MagicMock()
        settings_mock.get_setting.side_effect = lambda key, default=None: default
        widget = FolderContentList(settings_manager=settings_mock)
        try:
            old_path = widget.current_path
            widget.set_path("/nonexistent/path/that/does/not/exist_xyz")
            assert widget.current_path == old_path
        finally:
            widget.close()
            widget.deleteLater()

    def test_set_path_with_file_path_does_not_crash(self, qapp):
        """测试 set_path 传入文件路径（非目录）不会崩溃"""
        from freeassetfilter.components.folder_content_list import FolderContentList

        settings_mock = MagicMock()
        settings_mock.get_setting.side_effect = lambda key, default=None: default
        widget = FolderContentList(settings_manager=settings_mock)
        try:
            old_path = widget.current_path

            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
                tmpfile = f.name
            try:
                widget.set_path(tmpfile)
                # 文件路径不是目录，current_path 不应改变
                assert widget.current_path == old_path
            finally:
                os.unlink(tmpfile)
        finally:
            widget.close()
            widget.deleteLater()


class TestFolderContentListState:
    """测试 FolderContentList 状态与显示"""

    def test_current_path_defaults_to_home_directory(self, qapp):
        """测试默认 current_path 为用户主目录"""
        from freeassetfilter.components.folder_content_list import FolderContentList

        widget = FolderContentList(settings_manager=MagicMock())
        try:
            assert widget.current_path == os.path.expanduser("~")
        finally:
            widget.close()
            widget.deleteLater()

    def test_path_edit_displays_current_path(self, qapp):
        """测试路径编辑框显示内容与 current_path 一致"""
        from freeassetfilter.components.folder_content_list import FolderContentList

        widget = FolderContentList(settings_manager=MagicMock())
        try:
            assert widget.path_edit.get_text() == widget.current_path
        finally:
            widget.close()
            widget.deleteLater()

    def test_load_folder_can_be_called_repeatedly(self, qapp):
        """测试多次调用 load_folder_content 不会崩溃"""
        from freeassetfilter.components.folder_content_list import FolderContentList

        widget = FolderContentList(settings_manager=MagicMock())
        try:
            widget.show()
            qapp.processEvents()

            for _ in range(3):
                widget.load_folder_content()
                qapp.processEvents()
        finally:
            widget.close()
            widget.deleteLater()
