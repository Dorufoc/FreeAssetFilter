# -*- coding: utf-8 -*-
"""
FileSelectorDelegate 单元测试
测试 freeassetfilter/widgets/file_selector_delegate.py 模块的功能
"""

import pytest

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem, QWidget


# ---------------------------------------------------------------------------
# 辅助工具
# ---------------------------------------------------------------------------

class _DummySettingsManager:
    """最小化 SettingsManager 桩，返回默认值。"""
    def get_setting(self, key, default=None):
        return default


def _make_delegate(dpi_scale=1.0, global_font=None, parent=None, settings_manager=None):
    """创建 FileBlockCardDelegate 实例的快捷方法。"""
    from freeassetfilter.widgets.file_selector_delegate import FileBlockCardDelegate
    return FileBlockCardDelegate(
        dpi_scale=dpi_scale,
        global_font=global_font or QFont(),
        parent=parent,
        settings_manager=settings_manager,
    )


def _make_model_with_files(qapp, files):
    """创建带文件数据的 FileSelectorListModel。"""
    from freeassetfilter.widgets.file_selector_model import FileSelectorListModel

    setattr(qapp, "settings_manager", _DummySettingsManager())
    model = FileSelectorListModel(dpi_scale=1.0)
    model.set_card_width(150, 100, 3)
    model.set_files(files)
    return model


# ===========================================================================
# 模块基本测试
# ===========================================================================

class TestFileSelectorDelegateModule:
    """测试模块导入和导出。"""

    def test_module_import(self):
        """测试模块可以正常导入。"""
        from freeassetfilter.widgets.file_selector_delegate import (
            FileBlockCardDelegate,
            _get_file_type_display,
            _format_file_size_compact,
        )
        assert FileBlockCardDelegate is not None
        assert callable(_get_file_type_display)
        assert callable(_format_file_size_compact)

    def test_module_has_required_attributes(self):
        """测试模块包含必要的属性。"""
        from freeassetfilter import widgets
        from freeassetfilter.widgets import file_selector_delegate
        assert hasattr(file_selector_delegate, "FileBlockCardDelegate")
        assert hasattr(file_selector_delegate, "_get_file_type_display")
        assert hasattr(file_selector_delegate, "_format_file_size_compact")


# ===========================================================================
# 文件类型映射
# ===========================================================================

class TestGetFileTypeDisplay:
    """测试 _get_file_type_display() 函数。"""

    def test_directory(self):
        """目录应返回 '文件夹'。"""
        from freeassetfilter.widgets.file_selector_delegate import _get_file_type_display
        assert _get_file_type_display("", is_dir=True) == "文件夹"
        assert _get_file_type_display("txt", is_dir=True) == "文件夹"

    def test_no_suffix(self):
        """无后缀文件应返回 '文件'。"""
        from freeassetfilter.widgets.file_selector_delegate import _get_file_type_display
        assert _get_file_type_display(None, is_dir=False) == "文件"
        assert _get_file_type_display("", is_dir=False) == "文件"

    def test_known_suffix(self):
        """已知后缀应返回映射值。"""
        from freeassetfilter.widgets.file_selector_delegate import _get_file_type_display
        cases = [
            ("py", "Python 源文件"),
            ("js", "JavaScript 源文件"),
            ("html", "HTML 文档"),
            ("json", "JSON 文件"),
            ("jpg", "JPEG 图像"),
            ("png", "PNG 图像"),
            ("mp4", "MP4 视频"),
            ("mp3", "MP3 音频"),
            ("pdf", "PDF 文档"),
            ("zip", "Zip 压缩文件"),
            ("exe", "应用程序"),
        ]
        for suffix, expected in cases:
            assert _get_file_type_display(suffix) == expected, f"suffix={suffix!r}"

    def test_case_insensitive(self):
        """后缀匹配应大小写不敏感。"""
        from freeassetfilter.widgets.file_selector_delegate import _get_file_type_display
        assert _get_file_type_display("PY") == "Python 源文件"
        assert _get_file_type_display("Png") == "PNG 图像"
        assert _get_file_type_display("ZIP") == "Zip 压缩文件"
        assert _get_file_type_display("JPG") == "JPEG 图像"

    def test_unknown_suffix(self):
        """未知后缀应返回大写后缀 + ' 文件'。"""
        from freeassetfilter.widgets.file_selector_delegate import _get_file_type_display
        assert _get_file_type_display("xyz") == "XYZ 文件"
        assert _get_file_type_display("abc123") == "ABC123 文件"

    def test_edge_case_empty_string_suffix(self):
        """空字符串后缀应返回 '文件'。"""
        from freeassetfilter.widgets.file_selector_delegate import _get_file_type_display
        assert _get_file_type_display("") == "文件"


# ===========================================================================
# 文件大小格式化
# ===========================================================================

class TestFormatFileSizeCompact:
    """测试 _format_file_size_compact() 函数。"""

    def test_zero_bytes(self):
        """0 字节应返回 '0 B'。"""
        from freeassetfilter.widgets.file_selector_delegate import _format_file_size_compact
        assert _format_file_size_compact(0) == "0 B"

    def test_bytes(self):
        """小于 1024 字节应返回 'N B'。"""
        from freeassetfilter.widgets.file_selector_delegate import _format_file_size_compact
        assert _format_file_size_compact(1) == "1 B"
        assert _format_file_size_compact(512) == "512 B"
        assert _format_file_size_compact(1023) == "1023 B"

    def test_kilobytes(self):
        """小于 1024*1024 字节应返回 'N KB'（向上取整）。"""
        from freeassetfilter.widgets.file_selector_delegate import _format_file_size_compact
        assert _format_file_size_compact(1024) == "1 KB"
        # 1025=2KB (向上取整)
        assert _format_file_size_compact(1025) == "2 KB"
        assert _format_file_size_compact(2048) == "2 KB"

    def test_megabytes(self):
        """小于 1024*1024*1024 字节应返回 'N MB'（向上取整）。"""
        from freeassetfilter.widgets.file_selector_delegate import _format_file_size_compact
        assert _format_file_size_compact(1024 * 1024) == "1 MB"
        assert _format_file_size_compact(2 * 1024 * 1024) == "2 MB"
        # boundary
        val = 1024 * 1024 + 1
        expected_kb = (val + 1023) // 1024  # ceil
        expected_mb = (expected_kb + 1023) // 1024
        assert _format_file_size_compact(val) == f"{expected_mb} MB"

    def test_gigabytes(self):
        """大于等于 1024*1024*1024 字节应返回 'N GB'。"""
        from freeassetfilter.widgets.file_selector_delegate import _format_file_size_compact
        assert _format_file_size_compact(1024 * 1024 * 1024) == "1 GB"
        assert _format_file_size_compact(2 * 1024 * 1024 * 1024) == "2 GB"

    def test_terabytes(self):
        """超过 10000 GB（ceil >= 10000）应返回 'N TB'。"""
        from freeassetfilter.widgets.file_selector_delegate import _format_file_size_compact
        # 10000 GB → ceil=10000 → 10000 >= 10000 → 10000//1024 = 9 TB
        val = 10000 * 1024 * 1024 * 1024
        assert _format_file_size_compact(val) == "9 TB"
        # 10240 GB → ceil=10240 → 10240 >= 10000 → 10240//1024 = 10 TB
        val2 = 10240 * 1024 * 1024 * 1024
        assert _format_file_size_compact(val2) == "10 TB"
        # 9999 GB → ceil=9999 → 9999 < 10000 → 仍以 GB 显示
        val3 = 9999 * 1024 * 1024 * 1024
        assert _format_file_size_compact(val3) == "9999 GB"

    def test_negative_size(self):
        """负数应视为 0 字节。"""
        from freeassetfilter.widgets.file_selector_delegate import _format_file_size_compact
        assert _format_file_size_compact(-1) == "0 B"
        assert _format_file_size_compact(-9999) == "0 B"


# ===========================================================================
# FileBlockCardDelegate 创建
# ===========================================================================

class TestFileBlockCardDelegateCreation:
    """测试 FileBlockCardDelegate 的构造。"""

    def test_default_creation(self, qapp):
        """使用默认参数创建不应抛出异常。"""
        delegate = _make_delegate()
        assert delegate is not None
        assert delegate._dpi_scale == 1.0

    def test_creation_with_parent(self, qapp):
        """传入 parent widget 时 parent 应正确绑定。"""
        parent = QWidget()
        try:
            delegate = _make_delegate(parent=parent)
            assert delegate.parent() is parent
        finally:
            parent.deleteLater()

    def test_custom_dpi_scale(self, qapp):
        """dpi_scale 参数应影响内部布局计算。"""
        delegate_1x = _make_delegate(dpi_scale=1.0)
        delegate_2x = _make_delegate(dpi_scale=2.0)
        assert delegate_1x._dpi_scale == 1.0
        assert delegate_2x._dpi_scale == 2.0
        # dpi_scale 影响字体初始化
        assert delegate_1x.name_font is not None
        assert delegate_2x.name_font is not None

    def test_creation_with_custom_settings_manager(self, qapp):
        """传入自定义 settings_manager 应被使用。"""
        sm = _DummySettingsManager()
        delegate = _make_delegate(settings_manager=sm)
        assert delegate._settings_manager is sm


# ===========================================================================
# sizeHint
# ===========================================================================

class TestFileBlockCardDelegateSizeHint:
    """测试 sizeHint() 方法。"""

    def test_sizeHint_returns_qsize(self, qapp):
        """sizeHint 应返回有效的 QSize。"""
        delegate = _make_delegate()
        option = QStyleOptionViewItem()
        # 创建最小模型以便获取 QModelIndex
        from freeassetfilter.widgets.file_selector_model import FileSelectorListModel
        setattr(qapp, "settings_manager", _DummySettingsManager())
        model = FileSelectorListModel(dpi_scale=1.0)
        model.set_card_width(150, 100, 3)
        model.set_files([{
            "name": "test.txt",
            "path": "/fake/test.txt",
            "is_dir": False,
            "size": 1024,
            "created": "2024-01-15T10:30:00",
            "suffix": "txt",
        }])
        index = model.index(0, 0)
        size = delegate.sizeHint(option, index)
        assert isinstance(size, QSize)
        assert size.isValid()

    def test_sizeHint_positive_dimensions(self, qapp):
        """sizeHint 返回的宽高应大于 0。"""
        delegate = _make_delegate()
        option = QStyleOptionViewItem()
        from freeassetfilter.widgets.file_selector_model import FileSelectorListModel
        setattr(qapp, "settings_manager", _DummySettingsManager())
        model = FileSelectorListModel(dpi_scale=1.0)
        model.set_card_width(150, 100, 3)
        model.set_files([{
            "name": "test.txt",
            "path": "/fake/test.txt",
            "is_dir": False,
            "size": 2048,
            "created": "2024-06-15T14:30:00",
            "suffix": "txt",
        }])
        index = model.index(0, 0)
        size = delegate.sizeHint(option, index)
        assert size.width() > 0
        assert size.height() > 0

    def test_sizeHint_with_card_width_from_model(self, qapp):
        """当模型提供 CardWidthRole 时，width 应使用该值。"""
        delegate = _make_delegate()
        option = QStyleOptionViewItem()
        from freeassetfilter.widgets.file_selector_model import FileSelectorListModel
        setattr(qapp, "settings_manager", _DummySettingsManager())
        model = FileSelectorListModel(dpi_scale=1.0)
        model.set_card_width(200, 100, 3)
        model.set_files([{
            "name": "wide.txt",
            "path": "/fake/wide.txt",
            "is_dir": False,
            "size": 4096,
            "created": "2024-01-15T10:30:00",
            "suffix": "txt",
        }])
        index = model.index(0, 0)
        size = delegate.sizeHint(option, index)
        # CardWidthRole is 200, so width should be 200
        assert size.width() == 200


# ===========================================================================
# paint 方法
# ===========================================================================

class TestFileBlockCardDelegatePaint:
    """测试 paint() 方法基本调用。"""

    def test_paint_does_not_crash(self, qapp):
        """调用 paint 不应抛出异常。"""
        delegate = _make_delegate()
        pixmap = QPixmap(200, 150)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        option = QStyleOptionViewItem()
        option.rect = pixmap.rect()
        option.state = QStyle.State_Enabled

        from freeassetfilter.widgets.file_selector_model import FileSelectorListModel
        setattr(qapp, "settings_manager", _DummySettingsManager())
        model = FileSelectorListModel(dpi_scale=1.0)
        model.set_card_width(150, 100, 3)
        model.set_files([{
            "name": "test.txt",
            "path": "/fake/test.txt",
            "is_dir": False,
            "size": 1024,
            "created": "2024-01-15T10:30:00",
            "suffix": "txt",
        }])
        index = model.index(0, 0)

        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()

    def test_paint_directory_item(self, qapp):
        """绘制目录项不应抛出异常。"""
        delegate = _make_delegate()
        pixmap = QPixmap(200, 150)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        option = QStyleOptionViewItem()
        option.rect = pixmap.rect()
        option.state = QStyle.State_Enabled

        from freeassetfilter.widgets.file_selector_model import FileSelectorListModel
        setattr(qapp, "settings_manager", _DummySettingsManager())
        model = FileSelectorListModel(dpi_scale=1.0)
        model.set_card_width(150, 100, 3)
        model.set_files([{
            "name": "my_folder",
            "path": "/fake/my_folder",
            "is_dir": True,
            "size": 0,
            "created": "2024-03-20T09:00:00",
            "suffix": "",
        }])
        index = model.index(0, 0)

        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()

    def test_paint_with_hover_state(self, qapp):
        """hover 状态下 paint 不应抛出异常。"""
        delegate = _make_delegate()
        pixmap = QPixmap(200, 150)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        option = QStyleOptionViewItem()
        option.rect = pixmap.rect()
        option.state = QStyle.State_Enabled | QStyle.State_MouseOver

        from freeassetfilter.widgets.file_selector_model import FileSelectorListModel
        setattr(qapp, "settings_manager", _DummySettingsManager())
        model = FileSelectorListModel(dpi_scale=1.0)
        model.set_card_width(150, 100, 3)
        model.set_files([{
            "name": "hovered.py",
            "path": "/fake/hovered.py",
            "is_dir": False,
            "size": 5120,
            "created": "2024-05-10T16:45:00",
            "suffix": "py",
        }])
        index = model.index(0, 0)

        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()

    def test_paint_with_selected_state(self, qapp):
        """selected 状态下 paint 不应抛出异常。"""
        delegate = _make_delegate()
        pixmap = QPixmap(200, 150)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        option = QStyleOptionViewItem()
        option.rect = pixmap.rect()
        option.state = QStyle.State_Enabled | QStyle.State_Selected

        from freeassetfilter.widgets.file_selector_model import FileSelectorListModel
        setattr(qapp, "settings_manager", _DummySettingsManager())
        model = FileSelectorListModel(dpi_scale=1.0)
        model.set_card_width(150, 100, 3)
        model.set_files([{
            "name": "selected.jpg",
            "path": "/fake/selected.jpg",
            "is_dir": False,
            "size": 65536,
            "created": "2024-07-01T12:00:00",
            "suffix": "jpg",
            "is_selected": True,
        }])
        index = model.index(0, 0)

        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()


# ===========================================================================
# 内部方法 — _format_file_size（实例方法）
# ===========================================================================

class TestFileBlockCardDelegateFormatFileSize:
    """测试 FileBlockCardDelegate._format_file_size() 实例方法。"""

    def test_format_file_size_bytes(self, qapp):
        """小于 1024 字节应返回 'N B'。"""
        delegate = _make_delegate()
        assert delegate._format_file_size(0) == "0 B"
        assert delegate._format_file_size(512) == "512 B"
        assert delegate._format_file_size(1023) == "1023 B"

    def test_format_file_size_kb(self, qapp):
        """小于 1024*1024 应返回 'N.N KB'（保留一位小数）。"""
        delegate = _make_delegate()
        assert delegate._format_file_size(1024) == "1.0 KB"
        assert delegate._format_file_size(1536) == "1.5 KB"

    def test_format_file_size_mb(self, qapp):
        """小于 1024*1024*1024 应返回 'N.N MB'（保留一位小数）。"""
        delegate = _make_delegate()
        assert delegate._format_file_size(1024 * 1024) == "1.0 MB"
        assert delegate._format_file_size(2 * 1024 * 1024) == "2.0 MB"

    def test_format_file_size_gb(self, qapp):
        """大于等于 1024*1024*1024 应返回 'N.N GB'（保留一位小数）。"""
        delegate = _make_delegate()
        assert delegate._format_file_size(1024 * 1024 * 1024) == "1.0 GB"
        assert delegate._format_file_size(3 * 1024 * 1024 * 1024) == "3.0 GB"

    def test_format_file_size_negative(self, qapp):
        """负数应视为 0。"""
        delegate = _make_delegate()
        assert delegate._format_file_size(-100) == "0 B"
