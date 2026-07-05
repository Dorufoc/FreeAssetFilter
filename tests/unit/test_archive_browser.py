# -*- coding: utf-8 -*-
"""
archive_browser 组件测试
测试 freeassetfilter/components/archive_browser.py 的 ArchiveBrowser 组件

测试覆盖：
1. ArchiveBrowser 创建与基本属性（默认参数/自定义参数）
2. 信号存在性（path_changed, file_selected）
3. set_archive_path() 有效/无效路径
4. go_to_parent() 上级目录导航
5. refresh() 文件列表刷新
6. on_item_clicked / on_item_double_clicked 条目交互
"""

import pytest
import os
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QMessageBox


@pytest.fixture(autouse=True)
def _mock_7z_core():
    """为所有测试自动 mock get_7z_core，避免依赖真实 7z.exe"""
    patcher = patch("freeassetfilter.components.archive_browser.get_7z_core")
    mock_get_core = patcher.start()
    mock_core = MagicMock()
    mock_core.list_archive.return_value = []
    mock_core.is_encrypted.return_value = False
    mock_core.get_archive_type.return_value = "zip"
    mock_get_core.return_value = mock_core
    yield
    patcher.stop()


class TestArchiveBrowserCreation:
    """测试 ArchiveBrowser 创建"""

    def test_browser_can_be_created(self, qapp):
        """测试 ArchiveBrowser 可以正常创建并初始化"""
        from freeassetfilter.components.archive_browser import ArchiveBrowser

        browser = ArchiveBrowser()
        try:
            assert browser is not None
            assert browser.files_list is not None
            assert browser.archive_path is None
            assert browser.current_path == ""
            assert browser.archive_type is None
        finally:
            browser.close()
            browser.deleteLater()

    def test_browser_with_custom_params(self, qapp):
        """测试 ArchiveBrowser 使用自定义 dpi_scale / global_font / settings_manager 创建"""
        from freeassetfilter.components.archive_browser import ArchiveBrowser

        custom_font = QFont("Arial", 12)
        custom_dpi = 1.5

        browser = ArchiveBrowser(
            dpi_scale=custom_dpi,
            global_font=custom_font,
        )
        try:
            assert browser.dpi_scale == custom_dpi
            assert browser.global_font.family() == "Arial"
            assert browser.global_font.pointSize() == 12
        finally:
            browser.close()
            browser.deleteLater()

    def test_browser_signals_exist(self, qapp):
        """测试 ArchiveBrowser 包含必需的信号"""
        from freeassetfilter.components.archive_browser import ArchiveBrowser
        from PySide6.QtCore import Signal

        browser = ArchiveBrowser()
        try:
            assert hasattr(browser, "path_changed")
            assert hasattr(browser, "file_selected")
            assert isinstance(browser.path_changed, Signal)
            assert isinstance(browser.file_selected, Signal)
        finally:
            browser.close()
            browser.deleteLater()

    def test_browser_uses_mocked_7z_core(self, qapp):
        """测试 ArchiveBrowser 初始化时使用了 mock 的 7z core"""
        from freeassetfilter.components.archive_browser import ArchiveBrowser, get_7z_core

        browser = ArchiveBrowser()
        try:
            _ = get_7z_core
            assert browser._7z_core is not None
            assert hasattr(browser._7z_core, "list_archive")
            assert hasattr(browser._7z_core, "is_encrypted")
            assert hasattr(browser._7z_core, "get_archive_type")
        finally:
            browser.close()
            browser.deleteLater()


class TestArchiveBrowserSetArchivePath:
    """测试 ArchiveBrowser.set_archive_path"""

    def test_set_archive_path_with_valid_path(self, qapp, tmp_path):
        """测试 set_archive_path 对有效路径设置正确"""
        from freeassetfilter.components.archive_browser import ArchiveBrowser

        archive_file = tmp_path / "test.zip"
        archive_file.write_text("fake zip content")

        browser = ArchiveBrowser()
        try:
            browser.set_archive_path(str(archive_file))
            assert browser.archive_path == str(archive_file)
            assert browser.archive_type == "zip"
            assert browser.current_path == ""
        finally:
            browser.close()
            browser.deleteLater()

    @patch("freeassetfilter.components.archive_browser.QMessageBox.warning")
    def test_set_archive_path_with_invalid_path(self, mock_warning, qapp):
        """测试 set_archive_path 对无效路径保持 None 且不崩溃"""
        from freeassetfilter.components.archive_browser import ArchiveBrowser

        browser = ArchiveBrowser()
        try:
            browser.set_archive_path("/nonexistent/archive.zip")
            assert browser.archive_path is None
            mock_warning.assert_called_once()
        finally:
            browser.close()
            browser.deleteLater()

    @patch("freeassetfilter.components.archive_browser.QMessageBox.warning")
    def test_set_archive_path_with_empty_string(self, mock_warning, qapp):
        """测试 set_archive_path 对空字符串保持 None 且不崩溃"""
        from freeassetfilter.components.archive_browser import ArchiveBrowser

        browser = ArchiveBrowser()
        try:
            browser.set_archive_path("")
            assert browser.archive_path is None
            mock_warning.assert_called_once()
        finally:
            browser.close()
            browser.deleteLater()

    def test_set_archive_path_emits_path_changed(self, qapp, tmp_path):
        """测试 set_archive_path 有效时触发 path_changed 信号"""
        from freeassetfilter.components.archive_browser import ArchiveBrowser

        archive_file = tmp_path / "test.zip"
        archive_file.write_text("fake zip content")

        browser = ArchiveBrowser()
        try:
            received = []
            browser.path_changed.connect(received.append)

            browser.set_archive_path(str(archive_file))

            # refresh() emits path_changed with current_path (empty string)
            assert received == [""]
        finally:
            browser.close()
            browser.deleteLater()

    @patch("freeassetfilter.components.archive_browser.QMessageBox.warning")
    def test_set_archive_path_invalid_no_signal(self, mock_warning, qapp):
        """测试 set_archive_path 无效时不触发 path_changed"""
        from freeassetfilter.components.archive_browser import ArchiveBrowser

        browser = ArchiveBrowser()
        try:
            received = []
            browser.path_changed.connect(received.append)

            browser.set_archive_path("/nonexistent/archive.zip")
            assert received == []
        finally:
            browser.close()
            browser.deleteLater()


class TestArchiveBrowserRefresh:
    """测试 ArchiveBrowser.refresh"""

    def test_refresh_without_archive_is_noop(self, qapp):
        """测试无压缩包时 refresh 不崩溃"""
        from freeassetfilter.components.archive_browser import ArchiveBrowser

        browser = ArchiveBrowser()
        try:
            browser.refresh()
            assert browser.archive_content == []
        finally:
            browser.close()
            browser.deleteLater()

    def test_refresh_populates_files_list(self, qapp, tmp_path):
        """测试 refresh 正确填充文件列表"""
        from freeassetfilter.components.archive_browser import ArchiveBrowser

        archive_file = tmp_path / "test.zip"
        archive_file.write_text("fake zip content")

        browser = ArchiveBrowser()
        browser._7z_core.list_archive.return_value = [
            {"name": "folder", "path": "folder", "is_dir": True, "size": 0, "modified": "", "suffix": ""},
            {"name": "readme.txt", "path": "readme.txt", "is_dir": False, "size": 100, "modified": "2024-01-01", "suffix": "txt"},
        ]

        browser.set_archive_path(str(archive_file))

        try:
            assert browser.files_list.count() == 2
        finally:
            browser.close()
            browser.deleteLater()

    def test_refresh_emits_path_changed(self, qapp, tmp_path):
        """测试 refresh 触发 path_changed 信号"""
        from freeassetfilter.components.archive_browser import ArchiveBrowser

        archive_file = tmp_path / "test.zip"
        archive_file.write_text("fake zip content")

        browser = ArchiveBrowser()
        browser.set_archive_path(str(archive_file))

        try:
            received = []
            browser.path_changed.connect(received.append)

            browser.refresh()
            # refresh() emits path_changed with the current path
            assert received == [""]
        finally:
            browser.close()
            browser.deleteLater()


class TestArchiveBrowserNavigation:
    """测试 ArchiveBrowser 导航功能"""

    def test_go_to_parent_at_root_does_nothing(self, qapp, tmp_path):
        """测试根目录下 go_to_parent 不改变 current_path"""
        from freeassetfilter.components.archive_browser import ArchiveBrowser

        archive_file = tmp_path / "test.zip"
        archive_file.write_text("fake zip content")

        browser = ArchiveBrowser()
        browser.set_archive_path(str(archive_file))
        try:
            assert browser.current_path == ""
            browser.go_to_parent()
            assert browser.current_path == ""
        finally:
            browser.close()
            browser.deleteLater()

    def test_go_to_parent_from_subdirectory(self, qapp, tmp_path):
        """测试子目录下 go_to_parent 返回上级"""
        from freeassetfilter.components.archive_browser import ArchiveBrowser

        archive_file = tmp_path / "test.zip"
        archive_file.write_text("fake zip content")

        browser = ArchiveBrowser()
        browser.set_archive_path(str(archive_file))
        try:
            browser.current_path = "subdir"
            browser.go_to_parent()
            assert browser.current_path == ""
        finally:
            browser.close()
            browser.deleteLater()

    def test_go_to_parent_nested_directory(self, qapp, tmp_path):
        """测试多层嵌套时 go_to_parent 返回上一层"""
        from freeassetfilter.components.archive_browser import ArchiveBrowser

        archive_file = tmp_path / "test.zip"
        archive_file.write_text("fake zip content")

        browser = ArchiveBrowser()
        browser.set_archive_path(str(archive_file))
        try:
            browser.current_path = "a/b"
            browser.go_to_parent()
            assert browser.current_path == "a"
        finally:
            browser.close()
            browser.deleteLater()


class TestArchiveBrowserItemSelection:
    """测试 ArchiveBrowser 条目交互"""

    def test_on_item_clicked_emits_file_selected(self, qapp, tmp_path):
        """测试点击文件条目触发 file_selected 信号"""
        from freeassetfilter.components.archive_browser import ArchiveBrowser
        from PySide6.QtWidgets import QListWidgetItem

        archive_file = tmp_path / "test.zip"
        archive_file.write_text("fake zip content")

        browser = ArchiveBrowser()
        browser.set_archive_path(str(archive_file))
        try:
            file_info = {
                "name": "test.txt",
                "path": "test.txt",
                "is_dir": False,
                "size": 42,
                "modified": "",
                "suffix": "txt",
            }
            item = QListWidgetItem("test.txt")
            item.setData(Qt.UserRole, file_info)

            received = []
            browser.file_selected.connect(received.append)

            browser.on_item_clicked(item)
            assert received == [file_info]
        finally:
            browser.close()
            browser.deleteLater()

    def test_on_item_double_clicked_dir_navigates(self, qapp, tmp_path):
        """测试双击目录条目进入子目录"""
        from freeassetfilter.components.archive_browser import ArchiveBrowser
        from PySide6.QtWidgets import QListWidgetItem

        archive_file = tmp_path / "test.zip"
        archive_file.write_text("fake zip content")

        browser = ArchiveBrowser()
        browser.set_archive_path(str(archive_file))
        try:
            dir_info = {
                "name": "subdir",
                "path": "subdir",
                "is_dir": True,
                "size": 0,
                "modified": "",
                "suffix": "",
            }
            item = QListWidgetItem("subdir")
            item.setData(Qt.UserRole, dir_info)

            browser.on_item_double_clicked(item)
            assert browser.current_path == "subdir"
        finally:
            browser.close()
            browser.deleteLater()

    def test_on_item_double_clicked_file_does_not_navigate(self, qapp, tmp_path):
        """测试双击文件条目不导航"""
        from freeassetfilter.components.archive_browser import ArchiveBrowser
        from PySide6.QtWidgets import QListWidgetItem

        archive_file = tmp_path / "test.zip"
        archive_file.write_text("fake zip content")

        browser = ArchiveBrowser()
        browser.set_archive_path(str(archive_file))
        try:
            file_info = {
                "name": "test.txt",
                "path": "test.txt",
                "is_dir": False,
                "size": 42,
                "modified": "",
                "suffix": "txt",
            }
            item = QListWidgetItem("test.txt")
            item.setData(Qt.UserRole, file_info)

            browser.current_path = ""
            browser.on_item_double_clicked(item)
            assert browser.current_path == ""
        finally:
            browser.close()
            browser.deleteLater()
