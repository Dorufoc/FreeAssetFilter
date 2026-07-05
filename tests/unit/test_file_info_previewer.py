# -*- coding: utf-8 -*-
"""
file_info_previewer 单元测试
测试 freeassetfilter/components/file_info_previewer.py 模块的功能
"""
import pytest
import os
from unittest.mock import MagicMock, patch


class TestFileInfoPreviewerCreation:
    """测试 FileInfoPreviewer 创建"""

    def test_previewer_can_be_created(self, qapp):
        """测试可以创建 FileInfoPreviewer 实例"""
        from freeassetfilter.components.file_info_previewer import FileInfoPreviewer
        previewer = FileInfoPreviewer()
        try:
            assert previewer is not None
        finally:
            previewer.deleteLater()

    def test_get_ui_returns_scroll_area(self, qapp):
        """测试 get_ui 返回 QScrollArea"""
        from PySide6.QtWidgets import QScrollArea
        from freeassetfilter.components.file_info_previewer import FileInfoPreviewer
        previewer = FileInfoPreviewer()
        try:
            ui = previewer.get_ui()
            assert isinstance(ui, QScrollArea)
        finally:
            previewer.deleteLater()

    def test_audio_info_loaded_signal_emits(self, qapp):
        """测试 audioInfoLoaded 信号发射字典数据"""
        from freeassetfilter.components.file_info_previewer import FileInfoPreviewer
        previewer = FileInfoPreviewer()
        try:
            receiver = MagicMock()
            previewer.audioInfoLoaded.connect(receiver)
            previewer.audioInfoLoaded.emit({"时长": "03:30", "比特率": "320 Kbps"})
            receiver.assert_called_once_with({"时长": "03:30", "比特率": "320 Kbps"})
        finally:
            previewer.deleteLater()


class TestFileInfoPreviewerFileLoading:
    """测试 FileInfoPreviewer 文件加载"""

    def test_set_file_with_valid_file(self, qapp, sample_file_info):
        """测试 set_file 传入有效文件更新信息"""
        from freeassetfilter.components.file_info_previewer import FileInfoPreviewer
        previewer = FileInfoPreviewer()
        try:
            previewer.get_ui()
            previewer.set_file(sample_file_info)
            assert previewer.file_info["basic"]["文件名"] == "test.txt"
        finally:
            previewer.deleteLater()

    def test_set_file_with_none_raises_type_error(self, qapp):
        """测试 set_file 传入 None 抛出 TypeError"""
        from freeassetfilter.components.file_info_previewer import FileInfoPreviewer
        previewer = FileInfoPreviewer()
        try:
            previewer.get_ui()
            with pytest.raises((TypeError, AttributeError)):
                previewer.set_file(None)
        finally:
            previewer.deleteLater()

    def test_set_file_with_missing_path_uses_fallback(self, qapp, tmp_path):
        """测试 set_file 不存在的文件路径使用回退值"""
        from freeassetfilter.components.file_info_previewer import FileInfoPreviewer
        previewer = FileInfoPreviewer()
        try:
            previewer.get_ui()
            info = {
                "name": "ghost.txt",
                "path": str(tmp_path / "ghost.txt"),
                "is_dir": False, "size": 0,
                "modified": "", "created": "", "suffix": "txt",
            }
            previewer.set_file(info)
            assert previewer.file_info["basic"]["文件大小"] == "无法获取"
        finally:
            previewer.deleteLater()

    def test_set_file_replaces_previous(self, qapp, temp_text_file):
        """测试多次 set_file 替换前一个文件的信息"""
        from freeassetfilter.components.file_info_previewer import FileInfoPreviewer
        previewer = FileInfoPreviewer()
        try:
            previewer.get_ui()
            txt_path = temp_text_file[0]
            file1 = {
                "name": "first.txt", "path": str(txt_path),
                "is_dir": False, "size": os.path.getsize(txt_path),
                "modified": "", "created": "", "suffix": "txt",
            }
            previewer.set_file(file1)
            assert previewer.current_file["name"] == "first.txt"
            file2 = dict(file1, name="second.txt")
            previewer.set_file(file2)
            assert previewer.current_file["name"] == "second.txt"
        finally:
            previewer.deleteLater()

    def test_empty_file_info_dict_does_not_crash(self, qapp):
        """测试 set_file 传入空字典不崩溃"""
        from freeassetfilter.components.file_info_previewer import FileInfoPreviewer
        previewer = FileInfoPreviewer()
        try:
            previewer.get_ui()
            previewer.set_file({})
            assert previewer.current_file == {}
        finally:
            previewer.deleteLater()

    def test_directory_file_type_detected(self, qapp, tmp_path):
        """测试目录文件的文件类型为 '目录'"""
        from freeassetfilter.components.file_info_previewer import FileInfoPreviewer
        previewer = FileInfoPreviewer()
        try:
            sub = tmp_path / "subdir"
            sub.mkdir()
            info = {
                "name": "subdir", "path": str(sub), "is_dir": True,
                "size": 0, "modified": "", "created": "", "suffix": "",
            }
            previewer.get_ui()
            previewer.set_file(info)
            assert previewer.file_info["basic"]["文件类型"] == "目录"
        finally:
            previewer.deleteLater()

    def test_ui_labels_updated_after_set_file(self, qapp, sample_file_info):
        """测试 set_file 后 basic_info_labels 控件文本被更新"""
        from freeassetfilter.components.file_info_previewer import FileInfoPreviewer
        previewer = FileInfoPreviewer()
        try:
            previewer.get_ui()
            previewer.set_file(sample_file_info)
            name_widget = previewer.basic_info_labels["文件名"]
            assert name_widget.toPlainText() == "test.txt"
        finally:
            previewer.deleteLater()


class TestFileInfoPreviewerEdgeCases:
    """测试 FileInfoPreviewer 边缘情况与依赖注入"""

    def test_default_constructor_parameters(self, qapp):
        """测试默认构造函数参数正确初始化"""
        from freeassetfilter.components.file_info_previewer import FileInfoPreviewer
        previewer = FileInfoPreviewer()
        try:
            assert previewer.dpi_scale == 1.0
            assert previewer._settings_manager is not None
        finally:
            previewer.deleteLater()

    def test_constructor_with_custom_settings_manager(self, qapp):
        """测试传入自定义 settings_manager"""
        from freeassetfilter.components.file_info_previewer import FileInfoPreviewer
        mock_settings = MagicMock()
        mock_settings.get_setting.return_value = "#000000"
        previewer = FileInfoPreviewer(settings_manager=mock_settings)
        try:
            assert previewer._settings_manager is mock_settings
        finally:
            previewer.deleteLater()

    @patch('freeassetfilter.components.file_info_previewer.mutagen_file', None)
    @patch('freeassetfilter.components.file_info_previewer.exifread', None)
    def test_missing_optional_deps_still_works(self, qapp, sample_file_info):
        """测试可选依赖（mutagen/exifread）缺失时不崩溃"""
        from freeassetfilter.components.file_info_previewer import FileInfoPreviewer
        previewer = FileInfoPreviewer()
        try:
            previewer.get_ui()
            previewer.set_file(sample_file_info)
            assert previewer.current_file is not None
        finally:
            previewer.deleteLater()

    @patch('freeassetfilter.components.file_info_previewer.get_7z_core')
    def test_7z_core_initialized_on_creation(self, mock_get_7z, qapp):
        """测试创建时初始化 7z core"""
        from freeassetfilter.components.file_info_previewer import FileInfoPreviewer
        previewer = FileInfoPreviewer()
        try:
            mock_get_7z.assert_called_once()
        finally:
            previewer.deleteLater()
