# -*- coding: utf-8 -*-
"""
FileHorizontalCardDelegate 单元测试

测试 freeassetfilter/widgets/file_horizontal_card_delegate.py 模块的
FileHorizontalCardDelegate 类。
"""

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem


# =============================================================================
# 辅助函数
# =============================================================================

def _make_mock_model(file_info: dict, card_width: int = 0):
    """创建一个模拟的 QAbstractItemModel，按 FileHorizontalCardDelegate 期望的角色返回数据。

    Args:
        file_info: 文件信息字典，包含 path/name/is_dir/size/created/suffix/icon_pixmap 等键。
        card_width: 卡片宽度 (UserRole+10)，0 表示使用默认值。

    Returns:
        MagicMock: 模拟的 model 对象。
    """
    model = MagicMock()
    role_map = {
        Qt.UserRole + 1: file_info.get("path", ""),
        Qt.UserRole + 2: file_info.get("name", ""),
        Qt.UserRole + 3: file_info.get("is_dir", False),
        Qt.UserRole + 4: file_info.get("size", 0),
        Qt.UserRole + 5: file_info.get("created", ""),
        Qt.UserRole + 6: file_info.get("suffix", ""),
        Qt.UserRole + 7: file_info.get("is_selected", False),
        Qt.UserRole + 8: file_info.get("is_previewing", False),
        Qt.UserRole + 9: file_info.get("icon_pixmap"),
        Qt.UserRole + 10: card_width,
    }

    def data(index, role):
        return role_map.get(role, None)

    model.data = data
    return model


def _make_mock_index(model=None):
    """创建一个模拟的 QModelIndex。

    Args:
        model: 可选的 mock model 对象。

    Returns:
        MagicMock: 模拟的 QModelIndex。
    """
    index = MagicMock()
    if model is not None:
        index.model.return_value = model
    else:
        index.model.return_value = None
    return index


def _make_pixmap(w: int = 32, h: int = 32, color: tuple = (255, 0, 0, 255)):
    """创建一个纯色 QPixmap 用于测试。

    Args:
        w: 宽度
        h: 高度
        color: RGBA 元组

    Returns:
        QPixmap
    """
    pixmap = QPixmap(w, h)
    pixmap.fill(QColor(*color))
    return pixmap


# =============================================================================
# 默认文件信息数据集
# =============================================================================

DEFAULT_FILE_INFO = {
    "path": "C:/test/document.txt",
    "name": "document.txt",
    "is_dir": False,
    "size": 2048,
    "created": "2025-06-15T10:30:00",
    "suffix": "txt",
    "is_selected": False,
    "is_previewing": False,
    "icon_pixmap": None,
}


# =============================================================================
# 测试委托创建
# =============================================================================

class TestFileHorizontalCardDelegateCreation:
    """测试 FileHorizontalCardDelegate 的实例化"""

    def test_create_default(self, qapp):
        """使用默认参数创建委托。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()
        assert delegate is not None
        assert delegate._dpi_scale == 1.0
        assert delegate._global_font is None
        assert delegate._view is None

    def test_create_with_dpi_scale(self, qapp):
        """使用自定义 dpi_scale 创建委托。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate(dpi_scale=1.5)
        assert delegate._dpi_scale == 1.5

    def test_create_with_custom_font(self, qapp):
        """使用自定义字体创建委托。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        font = QFont("Arial", 12)
        delegate = FileHorizontalCardDelegate(global_font=font)
        assert delegate._global_font is font

    def test_create_with_parent(self, qapp):
        """指定父对象创建委托。"""
        from PySide6.QtWidgets import QWidget
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        parent = QWidget()
        delegate = FileHorizontalCardDelegate(parent=parent)
        assert delegate.parent() is parent
        parent.deleteLater()

    def test_create_with_settings_manager(self, qapp, settings_manager):
        """使用自定义 SettingsManager 创建委托。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate(settings_manager=settings_manager)
        # 验证 settings_manager 已被使用（颜色初始化应当已读取）
        assert delegate._settings_manager is settings_manager

    def test_subclass_of_base_card_delegate(self, qapp):
        """确认继承层次正确。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        from freeassetfilter.widgets.base_card_delegate import BaseCardDelegate
        assert issubclass(FileHorizontalCardDelegate, BaseCardDelegate)


# =============================================================================
# 测试 _init_fonts
# =============================================================================

class TestFileHorizontalCardDelegateInitFonts:
    """测试 _init_fonts 字体初始化"""

    def test_init_fonts_sets_all_fonts(self, qapp):
        """验证字体初始化后各字体属性正确设置。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()
        assert delegate.name_font is not None
        assert delegate.small_font is not None
        assert delegate.name_font.bold() is True
        assert delegate.name_font_metrics is not None
        assert delegate.small_font_metrics is not None

    def test_init_fonts_uses_app_global_font(self, qapp):
        """验证字体从 qapp.global_font 继承。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        # 设置一个特别的全局字体
        original_font = getattr(qapp, "global_font", None)
        test_font = QFont("Courier New", 14)
        qapp.global_font = test_font

        delegate = FileHorizontalCardDelegate()
        assert delegate.global_font.family() == "Courier New"
        assert delegate.name_font.family() == "Courier New"

        # 恢复
        qapp.global_font = original_font


# =============================================================================
# 测试 _get_file_info
# =============================================================================

class TestFileHorizontalCardDelegateGetFileInfo:
    """测试 _get_file_info 从模型索引获取文件信息"""

    def test_get_file_info_full(self, qapp):
        """从模型获取完整的文件信息。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()
        model = _make_mock_model(DEFAULT_FILE_INFO)
        index = _make_mock_index(model)

        info = delegate._get_file_info(index)
        assert info["name"] == "document.txt"
        assert info["path"] == "C:/test/document.txt"
        assert info["is_dir"] is False
        assert info["size"] == 2048
        assert info["suffix"] == "txt"

    def test_get_file_info_null_model(self, qapp):
        """模型为 None 时返回空字典。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()
        index = _make_mock_index(model=None)

        info = delegate._get_file_info(index)
        assert info == {}

    def test_get_file_info_minimal(self, qapp):
        """模型只有部分数据时不会崩溃。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()
        model = _make_mock_model({"name": "orphan.txt"})
        index = _make_mock_index(model)

        info = delegate._get_file_info(index)
        assert info["name"] == "orphan.txt"
        # 未提供的键应当返回默认值（空字符串 / False / 0）
        assert info["path"] == ""
        assert info["is_dir"] is False
        assert info["size"] == 0

    def test_get_file_info_suffix_lowercased(self, qapp):
        """suffix 自动转为小写。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()
        model = _make_mock_model({"suffix": "TXT", "name": "a.TXT"})
        index = _make_mock_index(model)

        info = delegate._get_file_info(index)
        assert info["suffix"] == "txt"


# =============================================================================
# 测试 _calculate_geometry
# =============================================================================

class TestFileHorizontalCardDelegateCalculateGeometry:
    """测试 _calculate_geometry 几何计算"""

    def test_calculate_geometry_basic(self, qapp):
        """基本几何参数计算。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()
        rect = QRect(0, 0, 400, 48)

        geo = delegate._calculate_geometry(rect)
        assert "border_width" in geo
        assert "radius" in geo
        assert "icon_rect" in geo
        assert "content_rect" in geo
        icon_rect = geo["icon_rect"]
        assert icon_rect.width() == 28  # icon_size = int(28 * 1.0)
        assert icon_rect.height() == 28
        assert geo["border_width"] >= 1
        assert geo["radius"] >= 1

    def test_calculate_geometry_with_dpi(self, qapp):
        """高 DPI 下的几何计算。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate(dpi_scale=2.0)
        rect = QRect(0, 0, 400, 48)

        geo = delegate._calculate_geometry(rect)
        assert geo["icon_rect"].width() == 56  # int(28 * 2.0)
        assert geo["icon_rect"].height() == 56
        assert geo["border_width"] == 2
        assert geo["radius"] == 16  # int(8 * 2.0)

    def test_calculate_geometry_small_rect(self, qapp):
        """非常小的矩形不应导致负值或崩溃。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()
        rect = QRect(0, 0, 10, 10)

        geo = delegate._calculate_geometry(rect)
        assert geo["border_width"] >= 1
        assert geo["icon_rect"].width() > 0
        assert geo["name_font_height"] > 0


# =============================================================================
# 测试 _calculate_right_item_rects
# =============================================================================

class TestFileHorizontalCardDelegateCalculateRightItemRects:
    """测试 _calculate_right_item_rects 右侧元素位置计算"""

    def test_calculate_right_item_rects_basic(self, qapp):
        """基本右侧元素位置计算。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()
        rect = QRect(0, 0, 400, 48)
        geometry = delegate._calculate_geometry(rect)

        right_items = delegate._calculate_right_item_rects(
            geometry, type_text="文本文档", size_text="2 KB", date_text="2025-06-15",
        )
        assert "type_rect" in right_items
        assert "date_rect" in right_items
        assert "size_rect" in right_items
        assert "name_max_width" in right_items
        # 右侧元素应当位于 rect 右半部分
        assert right_items["size_rect"].x() > 0
        assert right_items["name_max_width"] > 0

    def test_calculate_right_item_rects_empty_text(self, qapp):
        """空文本时对应矩形宽度为 0。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()
        rect = QRect(0, 0, 400, 48)
        geometry = delegate._calculate_geometry(rect)

        right_items = delegate._calculate_right_item_rects(
            geometry, type_text="", size_text="", date_text="",
        )
        assert right_items["size_rect"].width() == 0
        assert right_items["date_rect"].width() == 0
        assert right_items["type_rect"].width() == 0

    def test_calculate_right_item_rects_name_max_width(self, qapp):
        """验证 name_max_width 为正值。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()
        rect = QRect(0, 0, 200, 48)
        geometry = delegate._calculate_geometry(rect)

        right_items = delegate._calculate_right_item_rects(
            geometry, type_text="文件", size_text="1 MB", date_text="2025-01-01",
        )
        # 在有可用空间时 name_max_width 应 > 30
        assert right_items["name_max_width"] >= 30

    def test_calculate_right_item_rects_spacing(self, qapp):
        """验证 right_item 之间有间隔。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()
        rect = QRect(0, 0, 500, 48)
        geometry = delegate._calculate_geometry(rect)

        right_items = delegate._calculate_right_item_rects(
            geometry, type_text="PDF 文档", size_text="10 MB", date_text="2025-06-15",
        )
        # 三个矩形从左到右排列：type > date > size
        assert right_items["type_rect"].x() >= 0
        assert right_items["date_rect"].x() >= right_items["type_rect"].x()
        assert right_items["size_rect"].x() >= right_items["date_rect"].x()


# =============================================================================
# 测试 _resolve_card_rect
# =============================================================================

class TestFileHorizontalCardDelegateResolveCardRect:
    """测试 _resolve_card_rect 卡片矩形解析"""

    def test_resolve_card_rect_normal(self, qapp):
        """普通情况下正确计算卡片居中矩形。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        model = _make_mock_model(DEFAULT_FILE_INFO, card_width=300)
        index = _make_mock_index(model)

        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 400, 60)

        result = delegate._resolve_card_rect(option, index, for_drag_preview=False)
        assert isinstance(result, QRect)
        # 宽度应当 <= container_width (400)
        assert result.width() <= 400
        # 高度应当 <= option.rect.height() (60)
        assert result.height() <= 60
        # 应当是居中的
        assert result.x() >= 0
        assert result.y() >= 0

    def test_resolve_card_rect_drag_preview(self, qapp):
        """拖拽预览模式下直接返回 option.rect。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        option = QStyleOptionViewItem()
        option.rect = QRect(10, 20, 200, 50)

        result = delegate._resolve_card_rect(option, None, for_drag_preview=True)
        assert result == QRect(10, 20, 200, 50)

    def test_resolve_card_rect_centers_valid_size(self, qapp):
        """当 sizeHint 返回有效大小时，卡片在矩形内居中。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        # model=None 时 sizeHint 仍然返回有效尺寸 (w=200, h=38)
        index = _make_mock_index(model=None)
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 200, 48)

        result = delegate._resolve_card_rect(option, index)
        # container_width=200, target_width=200, offset_x=0
        # rect.height=48, target_height=38, offset_y=(48-38)//2=5
        assert result == QRect(0, 5, 200, 38)


# =============================================================================
# 测试 sizeHint
# =============================================================================

class TestFileHorizontalCardDelegateSizeHint:
    """测试 sizeHint 大小提示"""

    def test_size_hint_returns_qsize(self, qapp):
        """sizeHint 返回 QSize 类型的值。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        model = _make_mock_model(DEFAULT_FILE_INFO, card_width=300)
        index = _make_mock_index(model)

        option = QStyleOptionViewItem()

        size = delegate.sizeHint(option, index)
        assert isinstance(size, QSize)
        assert size.width() > 0
        assert size.height() > 0

    def test_size_hint_with_card_width(self, qapp):
        """当模型提供 card_width 时使用指定宽度。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        model = _make_mock_model(DEFAULT_FILE_INFO, card_width=350)
        index = _make_mock_index(model)

        option = QStyleOptionViewItem()

        size = delegate.sizeHint(option, index)
        assert size.width() == 350

    def test_size_hint_default_width(self, qapp):
        """没有 card_width 时使用默认最小宽度。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        model = _make_mock_model(DEFAULT_FILE_INFO, card_width=0)
        index = _make_mock_index(model)

        option = QStyleOptionViewItem()

        size = delegate.sizeHint(option, index)
        assert size.width() >= 150  # max(200, 150)

    def test_size_hint_no_model(self, qapp):
        """没有 model 时仍然返回有效的 QSize。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        index = _make_mock_index(model=None)
        option = QStyleOptionViewItem()

        size = delegate.sizeHint(option, index)
        assert isinstance(size, QSize)
        assert size.width() > 0
        assert size.height() > 0

    def test_size_hint_height_consistency(self, qapp):
        """高度在不同配置下保持一致的计算方式。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        model = _make_mock_model(DEFAULT_FILE_INFO, card_width=300)
        index = _make_mock_index(model)
        option = QStyleOptionViewItem()

        size = delegate.sizeHint(option, index)
        # 高度由 border + margins + icon_size 决定
        # 2 * border_width + 2 * icon_left_margin + icon_size
        # = 2*1 + 2*4 + 28 = 38
        assert size.height() == 38


# =============================================================================
# 测试 paint
# =============================================================================

class TestFileHorizontalCardDelegatePaint:
    """测试 paint 绘制方法"""

    def test_paint_calls_paint_card(self, qapp):
        """paint 调用 _paint_card 并传递 for_drag_preview=False。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        model = _make_mock_model(DEFAULT_FILE_INFO)
        index = _make_mock_index(model)

        pixmap = QPixmap(400, 60)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)

        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 400, 60)
        option.widget = None
        option.state = QStyle.State_Enabled

        # 不应抛出异常
        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()

    def test_paint_with_selected(self, qapp):
        """选中状态下的绘制不应抛出异常。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        info = dict(DEFAULT_FILE_INFO)
        info["is_selected"] = True
        model = _make_mock_model(info)
        index = _make_mock_index(model)

        pixmap = QPixmap(400, 60)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)

        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 400, 60)
        option.widget = None
        option.state = QStyle.State_Enabled | QStyle.State_Selected

        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()

    def test_paint_with_previewing(self, qapp):
        """预览中状态下的绘制不应抛出异常。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        info = dict(DEFAULT_FILE_INFO)
        info["is_previewing"] = True
        model = _make_mock_model(info)
        index = _make_mock_index(model)

        pixmap = QPixmap(400, 60)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)

        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 400, 60)
        option.widget = None
        option.state = QStyle.State_Enabled

        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()

    def test_paint_with_mouse_over(self, qapp):
        """鼠标悬停状态下的绘制不应抛出异常。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        model = _make_mock_model(DEFAULT_FILE_INFO)
        index = _make_mock_index(model)

        pixmap = QPixmap(400, 60)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)

        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 400, 60)
        option.widget = None
        option.state = QStyle.State_Enabled | QStyle.State_MouseOver

        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()

    def test_paint_with_icon(self, qapp):
        """带有图标 pixmap 的绘制不应抛出异常。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        info = dict(DEFAULT_FILE_INFO)
        info["icon_pixmap"] = _make_pixmap(32, 32)
        model = _make_mock_model(info)
        index = _make_mock_index(model)

        pixmap = QPixmap(400, 60)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)

        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 400, 60)
        option.widget = None
        option.state = QStyle.State_Enabled

        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()

    def test_paint_dir(self, qapp):
        """目录类型文件的绘制不应抛出异常。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        dir_info = dict(DEFAULT_FILE_INFO)
        dir_info["is_dir"] = True
        dir_info["name"] = "MyFolder"
        dir_info["suffix"] = ""
        model = _make_mock_model(dir_info)
        index = _make_mock_index(model)

        pixmap = QPixmap(400, 60)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)

        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 400, 60)
        option.widget = None
        option.state = QStyle.State_Enabled

        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()

    def test_paint_empty_file_info(self, qapp):
        """空白文件信息也不应抛出异常。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        model = _make_mock_model({})
        index = _make_mock_index(model)

        pixmap = QPixmap(400, 60)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)

        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 400, 60)
        option.widget = None
        option.state = QStyle.State_Enabled

        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()


# =============================================================================
# 测试辅助方法
# =============================================================================

class TestFileHorizontalCardDelegateHelpers:
    """测试委托中的辅助方法"""

    def test_set_view(self, qapp):
        """set_view 正确设置视图。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        view = MagicMock()
        delegate.set_view(view)
        assert delegate._view is view
        view.setMouseTracking.assert_called_once_with(True)

    def test_clear_caches(self, qapp):
        """clear_caches 正常调用不抛出异常。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        # 给缓存填充一些数据
        delegate._animation_states["key1"] = {}
        delegate._active_animation_keys.add("key1")

        delegate.clear_caches()
        assert len(delegate._animation_states) == 0
        assert len(delegate._active_animation_keys) == 0

    def test_update_theme(self, qapp):
        """update_theme 正常调用不抛出异常。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        # 不应抛出异常
        delegate.update_theme()

    def test_set_dragging_file_path(self, qapp):
        """set_dragging_file_path 正常调用。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        delegate.set_dragging_file_path("C:/test/file.txt")
        # 不抛出异常即为通过

    def test_set_dragging_file_path_none(self, qapp):
        """set_dragging_file_path(None) 正常调用。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        delegate.set_dragging_file_path(None)
        assert delegate._dragging_file_path is None

    def test_build_drag_pixmap(self, qapp):
        """build_drag_pixmap 返回 QPixmap。"""
        from freeassetfilter.widgets.file_horizontal_card_delegate import (
            FileHorizontalCardDelegate,
        )
        delegate = FileHorizontalCardDelegate()

        model = _make_mock_model(DEFAULT_FILE_INFO)
        index = _make_mock_index(model)

        pixmap = delegate.build_drag_pixmap(index, QSize(200, 48), qapp.palette())
        assert isinstance(pixmap, QPixmap)
        assert not pixmap.isNull()
