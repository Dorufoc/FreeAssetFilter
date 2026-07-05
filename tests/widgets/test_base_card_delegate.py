# -*- coding: utf-8 -*-
"""
BaseCardDelegate 单元测试
测试 freeassetfilter/widgets/base_card_delegate.py 中 BaseCardDelegate 的公有方法。

BaseCardDelegate 是一个抽象基类（_paint_card 引发 NotImplementedError），
因此测试使用一个具体子类 _ConcreteTestDelegate 来实例化被测对象。
"""

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt, QRect, QSize, QModelIndex
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPixmap,
    QPalette,
)
from PySide6.QtWidgets import (
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QStyle,
    QAbstractItemView,
    QWidget,
)

from freeassetfilter.widgets.base_card_delegate import BaseCardDelegate


# ---------------------------------------------------------------------------
# Helper: 继承 BaseCardDelegate 的具体子类
# ---------------------------------------------------------------------------

class _ConcreteTestDelegate(BaseCardDelegate):
    """BaseCardDelegate 的具体子类，用于测试抽象基类。"""

    def _paint_card(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
        for_drag_preview: bool = False,
    ) -> None:
        """实现抽象方法，记录调用参数以供断言。"""
        self.last_paint_call = {
            "painter": painter,
            "option": option,
            "index": index,
            "for_drag_preview": for_drag_preview,
        }


class _MockSettingsManager:
    """模拟 SettingsManager，用于隔离测试。"""

    def __init__(self, overrides: dict | None = None) -> None:
        self._overrides = overrides or {}

    def get_setting(self, key: str, default=None):
        return self._overrides.get(key, default)


# ---------------------------------------------------------------------------
# 1. 构造函数初始化
# ---------------------------------------------------------------------------

class TestBaseCardDelegateInit:
    """测试构造函数初始化。"""

    def test_default_construction(self, qt_app) -> None:
        """无参构建：默认值正确，内部状态正确初始化。"""
        delegate = _ConcreteTestDelegate()
        assert delegate is not None
        assert isinstance(delegate, QStyledItemDelegate)
        # 默认参数
        assert delegate._dpi_scale == 1.0
        assert delegate._global_font is None
        assert delegate.parent() is None
        # 内部状态
        assert delegate._view is None
        assert delegate._dragging_file_path is None
        assert delegate._animation_states == {}
        assert delegate._active_animation_keys == set()
        assert len(delegate._shadow_pixmap_cache) == 0
        # 颜色已初始化（具体值取决于 SettingsManager 默认设置）
        assert hasattr(delegate, "base_color")
        assert delegate.base_color
        assert isinstance(delegate._normal_bg, QColor)
        # 基础 QColor 对象已创建（基于读取到的颜色）
        assert isinstance(delegate._normal_border, QColor)
        assert isinstance(delegate._hover_bg, QColor)
        assert isinstance(delegate._selected_bg, QColor)
        assert isinstance(delegate._text_color, QColor)
        # 字体已初始化
        assert hasattr(delegate, "name_font")
        assert isinstance(delegate.name_font, QFont)
        assert delegate.name_font.bold()
        assert hasattr(delegate, "small_font")

    def test_construction_with_dpi_scale(self, qt_app) -> None:
        """传入 dpi_scale 参数。"""
        delegate = _ConcreteTestDelegate(dpi_scale=2.0)
        assert delegate._dpi_scale == 2.0

    def test_construction_with_global_font(self, qt_app) -> None:
        """传入 global_font 参数。"""
        font = QFont("Arial", 14)
        delegate = _ConcreteTestDelegate(global_font=font)
        assert delegate._global_font is font
        # 字体应从 global_font 继承（系统字体可能覆盖，验证有效即可）
        assert delegate.name_font.family() != ""

    def test_construction_with_parent(self, qt_app) -> None:
        """传入 parent widget。"""
        parent = QWidget()
        delegate = _ConcreteTestDelegate(parent=parent)
        assert delegate.parent() is parent
        parent.deleteLater()

    def test_construction_with_settings_manager(self, qt_app) -> None:
        """传入自定义 settings_manager，颜色应从 manager 读取。"""
        sm = _MockSettingsManager({
            "appearance.colors.base_color": "#FF0000",
            "appearance.colors.auxiliary_color": "#00FF00",
            "appearance.colors.normal_color": "#0000FF",
            "appearance.colors.accent_color": "#FFFF00",
            "appearance.colors.secondary_color": "#000000",
        })
        delegate = _ConcreteTestDelegate(settings_manager=sm)
        assert delegate.base_color == "#FF0000"
        assert delegate.auxiliary_color == "#00FF00"
        assert delegate.normal_color == "#0000FF"
        assert delegate.accent_color == "#FFFF00"
        assert delegate.secondary_color == "#000000"

    def test_settings_manager_fallback(self, qt_app) -> None:
        """未传入 settings_manager 时自动使用 SettingsManager 单例。"""
        from freeassetfilter.core.settings_manager import SettingsManager
        delegate = _ConcreteTestDelegate()
        assert delegate._settings_manager is not None
        assert isinstance(delegate._settings_manager, SettingsManager)

    def test_init_colors_error_handling(self, qt_app) -> None:
        """_init_colors 在 settings_manager.get_setting 异常时使用默认值。"""
        faulty_sm = _MockSettingsManager({})

        def failing_get(key: str, default=None):
            raise RuntimeError("test error")

        faulty_sm.get_setting = failing_get

        delegate = _ConcreteTestDelegate(settings_manager=faulty_sm)
        assert delegate.base_color == "#212121"
        assert delegate.auxiliary_color == "#3D3D3D"
        assert delegate.normal_color == "#717171"
        assert delegate.accent_color == "#B036EE"
        assert delegate.secondary_color == "#FFFFFF"

    def test_init_fonts_uses_global_font(self, qt_app) -> None:
        """_init_fonts 使用传入的 global_font。"""
        custom_font = QFont("Courier New", 16)
        delegate = _ConcreteTestDelegate(global_font=custom_font)
        assert delegate.name_font.family() != ""
        assert delegate.small_font is not None

    def test_init_fonts_fallback(self, qt_app, monkeypatch) -> None:
        """当 QApplication.instance() 返回 None 且无 global_font 时回退到空 QFont。"""
        # 模拟 QApplication.instance() 返回 None
        with patch.object(type(qt_app), "instance", return_value=None):
            delegate = _ConcreteTestDelegate(global_font=None)
            assert delegate.global_font is not None
            assert isinstance(delegate.global_font, QFont)


# ---------------------------------------------------------------------------
# 2. 视图管理
# ---------------------------------------------------------------------------

class TestBaseCardDelegateViewManagement:
    """测试视图管理方法。"""

    def test_set_view(self, qt_app) -> None:
        """set_view 关联视图并启用鼠标追踪。"""
        delegate = _ConcreteTestDelegate()
        mock_view = MagicMock(spec=QAbstractItemView)
        delegate.set_view(mock_view)
        assert delegate._view is mock_view
        mock_view.setMouseTracking.assert_called_once_with(True)

    def test_set_view_none(self, qt_app) -> None:
        """set_view(None) 不影响视图引用。"""
        delegate = _ConcreteTestDelegate()
        delegate.set_view(None)
        assert delegate._view is None

    def test_clear_caches(self, qt_app) -> None:
        """clear_caches 清空动画/缓存状态并刷新视图。"""
        delegate = _ConcreteTestDelegate()
        delegate._animation_states["test"] = {"dummy": True}
        delegate._active_animation_keys.add("test")
        delegate._dragging_file_path = "some/path"

        mock_view = MagicMock(spec=QAbstractItemView)
        mock_view.viewport.return_value = MagicMock()
        delegate.set_view(mock_view)

        delegate.clear_caches()

        assert delegate._animation_states == {}
        assert delegate._active_animation_keys == set()
        assert delegate._dragging_file_path is None
        assert len(delegate._shadow_pixmap_cache) == 0
        mock_view.viewport.return_value.update.assert_called_once()

    def test_clear_caches_no_view(self, qt_app) -> None:
        """clear_caches 在无视图时不崩溃。"""
        delegate = _ConcreteTestDelegate()
        delegate._animation_states["test"] = {"dummy": True}
        delegate.clear_caches()
        assert delegate._animation_states == {}

    def test_update_theme(self, qt_app) -> None:
        """update_theme 重新初始化颜色/字体并清空缓存。"""
        delegate = _ConcreteTestDelegate()
        delegate._animation_states["test"] = {"dummy": True}
        delegate._active_animation_keys.add("test")

        old_name_font = delegate.name_font
        delegate.update_theme()

        # 颜色已重新初始化
        assert hasattr(delegate, "_normal_bg")
        # 字体已重新初始化
        assert hasattr(delegate, "name_font")
        # 缓存已清空
        assert delegate._animation_states == {}
        assert delegate._active_animation_keys == set()

    def test_set_dragging_file_path(self, qt_app) -> None:
        """set_dragging_file_path 更新拖拽路径并刷新视图。"""
        import os

        delegate = _ConcreteTestDelegate()
        mock_view = MagicMock(spec=QAbstractItemView)
        mock_view.viewport.return_value = MagicMock()
        delegate.set_view(mock_view)

        delegate.set_dragging_file_path("C:\\test\\file.txt")
        expected = os.path.normpath("C:\\test\\file.txt")
        assert delegate._dragging_file_path == expected
        mock_view.viewport.return_value.update.assert_called_once()

    def test_set_dragging_file_path_same_path_skips_update(self, qt_app) -> None:
        """设置相同路径跳过重复刷新。"""
        delegate = _ConcreteTestDelegate()
        mock_view = MagicMock(spec=QAbstractItemView)
        mock_view.viewport.return_value = MagicMock()
        delegate.set_view(mock_view)
        delegate.set_dragging_file_path("C:\\test\\file.txt")
        mock_view.viewport.return_value.update.reset_mock()

        delegate.set_dragging_file_path("C:\\test\\file.txt")
        mock_view.viewport.return_value.update.assert_not_called()

    def test_set_dragging_file_path_none(self, qt_app) -> None:
        """set_dragging_file_path(None) 将路径置空。"""
        delegate = _ConcreteTestDelegate()
        delegate.set_dragging_file_path(None)
        assert delegate._dragging_file_path is None

    def test_set_dragging_file_path_no_view(self, qt_app) -> None:
        """无视图时 set_dragging_file_path 不崩溃。"""
        delegate = _ConcreteTestDelegate()
        delegate.set_dragging_file_path("/some/path")
        assert delegate._dragging_file_path is not None


# ---------------------------------------------------------------------------
# 3. 动画引擎
# ---------------------------------------------------------------------------

class TestBaseCardDelegateAnimation:
    """测试动画相关方法。"""

    def test_are_state_animations_enabled_default(self, qt_app) -> None:
        """默认返回 True。"""
        delegate = _ConcreteTestDelegate()
        with patch(
            "freeassetfilter.widgets.base_card_delegate.is_animation_enabled",
            return_value=True,
        ):
            assert delegate._are_state_animations_enabled() is True

    def test_are_state_animations_enabled_disabled(self, qt_app) -> None:
        """全局关闭后返回 False。"""
        delegate = _ConcreteTestDelegate()
        with patch(
            "freeassetfilter.widgets.base_card_delegate.is_animation_enabled",
            return_value=False,
        ):
            assert delegate._are_state_animations_enabled() is False

    def test_default_anim_state_structure(self, qt_app) -> None:
        """_default_anim_state 返回完整的初始状态字典。"""
        delegate = _ConcreteTestDelegate()
        state = delegate._default_anim_state()
        assert isinstance(state, dict)
        assert state["is_hovered"] is False
        assert state["is_selected"] is False
        assert state["is_previewing"] is False
        assert state["animating"] is False
        assert state["animation_start_time"] == 0.0
        assert state["animation_duration"] == 0
        assert state["easing"] == "out_cubic"
        assert "bg_color" in state
        assert "border_color" in state
        assert "shadow_color" in state
        assert "shadow_blur" in state

    def test_get_animation_key_from_path(self, qt_app) -> None:
        """通过文件路径生成动画键。"""
        delegate = _ConcreteTestDelegate()
        file_info = {"path": "/test/dir/file.txt", "name": "file.txt"}
        key = delegate._get_animation_key(file_info)
        import os
        assert os.path.normpath("/test/dir/file.txt") in key

    def test_get_animation_key_rowless(self, qt_app) -> None:
        """无路径时基于名称生成键。"""
        delegate = _ConcreteTestDelegate()
        file_info = {"name": "orphan.txt"}
        key = delegate._get_animation_key(file_info)
        assert "orphan.txt" in key

    def test_get_animation_state_creates_default(self, qt_app) -> None:
        """获取不存在的键自动创建默认状态。"""
        delegate = _ConcreteTestDelegate()
        state = delegate._get_animation_state("new_key")
        assert "new_key" in delegate._animation_states
        assert state["is_hovered"] is False

    def test_sync_animation_state_no_transition(self, qt_app) -> None:
        """状态不变时直接设置目标值，不启动画。"""
        delegate = _ConcreteTestDelegate()
        key = "test_key"
        file_info = {"path": "/test/path"}

        state = delegate._sync_animation_state(key, file_info, False, False, False)
        assert state["is_hovered"] is False
        assert state["is_selected"] is False
        assert state["is_previewing"] is False
        assert state["animating"] is False
        assert key not in delegate._active_animation_keys

    def test_sync_animation_state_with_transition(self, qt_app) -> None:
        """状态变化时启动画并注册心跳回调。"""
        delegate = _ConcreteTestDelegate()
        key = "test_key"
        file_info = {"path": "/test/path"}

        with patch.object(delegate, "_are_state_animations_enabled", return_value=True):
            with patch(
                "freeassetfilter.core.heartbeat_manager.HeartbeatManager"
            ) as mock_hm_cls:
                mock_hm_cls.return_value = MagicMock()
                state = delegate._sync_animation_state(key, file_info, True, False, False)

        assert state["is_hovered"] is True
        assert state["animating"] is True
        assert state["animation_duration"] > 0
        assert key in delegate._active_animation_keys

    def test_sync_animation_state_transition_disabled(self, qt_app) -> None:
        """动画关闭时状态变化直接跳转目标值。"""
        delegate = _ConcreteTestDelegate()
        key = "test_key"
        file_info = {"path": "/test/path"}

        with patch.object(delegate, "_are_state_animations_enabled", return_value=False):
            state = delegate._sync_animation_state(key, file_info, True, False, False)

        assert state["is_hovered"] is True
        assert state["animating"] is False
        assert key not in delegate._active_animation_keys

    def test_ease_functions(self, qt_app) -> None:
        """各类缓动曲线在端点处行为正确。"""
        delegate = _ConcreteTestDelegate()
        # 所有曲线 t=0 返回 0, t=1 返回 1
        for curve in ("out_cubic", "in_out_quad", "out_quint", "in_out_cubic"):
            assert delegate._ease(curve, 0.0) == 0.0
            assert delegate._ease(curve, 1.0) == 1.0
            assert 0.0 < delegate._ease(curve, 0.5) < 1.0

    def test_interpolate_color(self, qt_app) -> None:
        """颜色插值在中间点正确。"""
        delegate = _ConcreteTestDelegate()
        red = QColor(255, 0, 0)
        blue = QColor(0, 0, 255)
        result = delegate._interpolate_color(red, blue, 0.5)
        assert result.red() == 127
        assert result.blue() == 127
        assert result.green() == 0
        # 端点
        assert delegate._interpolate_color(red, blue, 0.0) == red
        assert delegate._interpolate_color(red, blue, 1.0) == blue

    def test_interpolate_value(self, qt_app) -> None:
        """数值插值计算正确。"""
        delegate = _ConcreteTestDelegate()
        assert delegate._interpolate_value(0.0, 10.0, 0.5) == 5.0
        assert delegate._interpolate_value(0.0, 10.0, 0.0) == 0.0
        assert delegate._interpolate_value(0.0, 10.0, 1.0) == 10.0
        assert delegate._interpolate_value(-5.0, 5.0, 0.5) == 0.0

    def test_target_visuals_for_flags(self, qt_app) -> None:
        """不同状态返回对应的目标视觉属性。"""
        delegate = _ConcreteTestDelegate()
        # Hovered
        bg, border, shadow, blur = delegate._target_visuals_for_flags(True, False, False)
        assert bg == delegate._hover_bg
        assert border == delegate._hover_border
        # Selected
        bg, border, shadow, blur = delegate._target_visuals_for_flags(False, True, False)
        assert blur == 8.0 * delegate._dpi_scale
        # Previewing
        bg, border, shadow, blur = delegate._target_visuals_for_flags(False, False, True)
        assert blur == 0.0
        # Idle
        bg, border, shadow, blur = delegate._target_visuals_for_flags(False, False, False)
        assert bg == delegate._normal_bg

    def test_on_animation_tick_completes(self, qt_app) -> None:
        """动画 tick 到期后跳转到目标值并清除 active key。"""
        delegate = _ConcreteTestDelegate()
        key = "test_key"
        delegate._active_animation_keys.add(key)
        state = delegate._default_anim_state()
        state["animating"] = True
        state["animation_start_time"] = 0.0
        state["animation_duration"] = 1  # 极短
        delegate._animation_states[key] = state

        with patch.object(delegate, "_are_state_animations_enabled", return_value=True):
            with patch(
                "freeassetfilter.core.heartbeat_manager.HeartbeatManager"
            ) as mock_hm_cls:
                mock_hm_cls.return_value = MagicMock()
                delegate._on_animation_tick()

        assert state["animating"] is False
        assert key not in delegate._active_animation_keys

    def test_on_animation_tick_disabled_clears_all(self, qt_app) -> None:
        """动画全局关闭时，所有动画状态跳转到目标值。"""
        delegate = _ConcreteTestDelegate()
        key = "test_key"
        delegate._active_animation_keys.add(key)
        state = delegate._default_anim_state()
        state["animating"] = True
        delegate._animation_states[key] = state

        with patch.object(delegate, "_are_state_animations_enabled", return_value=False):
            with patch(
                "freeassetfilter.core.heartbeat_manager.HeartbeatManager"
            ) as mock_hm_cls:
                mock_hm_cls.return_value = MagicMock()
                delegate._on_animation_tick()

        assert state["animating"] is False
        assert delegate._active_animation_keys == set()


# ---------------------------------------------------------------------------
# 4. 阴影渲染
# ---------------------------------------------------------------------------

class TestBaseCardDelegateShadow:
    """测试阴影渲染方法。"""

    def test_draw_shadow_skipped_blur_too_small(self, qt_app) -> None:
        """shadow_blur <= 0.5 时跳过阴影绘制。"""
        delegate = _ConcreteTestDelegate()
        pixmap = QPixmap(100, 100)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)

        try:
            delegate._draw_shadow(painter, QRect(0, 0, 50, 50), 5.0, QColor(255, 0, 0), 0.4)
        finally:
            painter.end()
        # 不崩溃即通过

    def test_draw_shadow_skipped_alpha_zero(self, qt_app) -> None:
        """阴影颜色 alpha=0 时跳过绘制。"""
        delegate = _ConcreteTestDelegate()
        pixmap = QPixmap(100, 100)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)

        try:
            delegate._draw_shadow(painter, QRect(0, 0, 50, 50), 5.0, QColor(0, 0, 0, 0), 10.0)
        finally:
            painter.end()

    def test_draw_shadow_normal(self, qt_app) -> None:
        """正常参数下阴影绘制不崩溃。"""
        delegate = _ConcreteTestDelegate()
        pixmap = QPixmap(100, 100)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)

        try:
            delegate._draw_shadow(painter, QRect(0, 0, 50, 50), 5.0, QColor(255, 0, 0, 50), 8.0)
        finally:
            painter.end()

    def test_get_real_shadow_pixmap_basic(self, qt_app) -> None:
        """_get_real_shadow_pixmap 返回有效的阴影像素图。"""
        delegate = _ConcreteTestDelegate()
        shadow_pixmap, margin = delegate._get_real_shadow_pixmap(
            50, 50, 5.0, QColor(255, 0, 0, 100), 8.0, 1.0,
        )
        assert shadow_pixmap is not None
        assert not shadow_pixmap.isNull()
        assert margin >= 2

    def test_shadow_pixmap_cache_hit(self, qt_app) -> None:
        """相同缓存键命中时返回同一像素图实例。"""
        delegate = _ConcreteTestDelegate()
        color = QColor(100, 100, 100, 50)
        result1, margin1 = delegate._get_real_shadow_pixmap(50, 50, 5.0, color, 8.0, 1.0)
        result2, margin2 = delegate._get_real_shadow_pixmap(50, 50, 5.0, color, 8.0, 1.0)

        assert result1 is result2
        assert margin1 == margin2

    def test_shadow_pixmap_cache_max_entries(self, qt_app) -> None:
        """缓存容量达到 _SHADOW_CACHE_MAX_ENTRIES 后淘汰旧条目。"""
        delegate = _ConcreteTestDelegate()
        color = QColor(100, 100, 100, 50)
        max_entries = delegate._SHADOW_CACHE_MAX_ENTRIES

        # 塞入超过最大值的条目
        for i in range(max_entries + 5):
            delegate._get_real_shadow_pixmap(
                10 + i, 10 + i, 5.0, color, 8.0, 1.0,
            )

        assert len(delegate._shadow_pixmap_cache) <= max_entries

    def test_draw_scaled_pixmap_null_skipped(self, qt_app) -> None:
        """null 像素图时 _draw_scaled_pixmap 跳过绘制。"""
        delegate = _ConcreteTestDelegate()
        pixmap = QPixmap(100, 100)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)

        try:
            delegate._draw_scaled_pixmap(painter, QRect(0, 0, 50, 50), QPixmap(), 1.0)
        finally:
            painter.end()

    def test_draw_scaled_pixmap_valid(self, qt_app) -> None:
        """有效像素图绘制不崩溃。"""
        delegate = _ConcreteTestDelegate()
        pixmap = QPixmap(100, 100)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)

        try:
            source = QPixmap(20, 20)
            source.fill(Qt.red)
            delegate._draw_scaled_pixmap(painter, QRect(10, 10, 40, 40), source, 0.8)
        finally:
            painter.end()

    def test_draw_scaled_pixmap_zero_dimension(self, qt_app) -> None:
        """目标 rect 宽或高为 0 时跳过。"""
        delegate = _ConcreteTestDelegate()
        pixmap = QPixmap(100, 100)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)

        try:
            source = QPixmap(20, 20)
            source.fill(Qt.red)
            delegate._draw_scaled_pixmap(painter, QRect(0, 0, 0, 50), source, 1.0)
            delegate._draw_scaled_pixmap(painter, QRect(0, 0, 50, 0), source, 1.0)
        finally:
            painter.end()
        # 不崩溃即通过


# ---------------------------------------------------------------------------
# 5. paint() 方法
# ---------------------------------------------------------------------------

class TestBaseCardDelegatePainting:
    """测试绘制相关方法。"""

    def test_paint_delegates_to_paint_card(self, qt_app) -> None:
        """paint() 委托给 _paint_card。"""
        delegate = _ConcreteTestDelegate()
        pixmap = QPixmap(200, 200)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)

        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 200, 200)
        option.state = QStyle.State_Enabled
        index = QModelIndex()

        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()

        assert hasattr(delegate, "last_paint_call")
        assert delegate.last_paint_call["painter"] is painter
        assert delegate.last_paint_call["option"] is option
        assert delegate.last_paint_call["index"] == index
        assert delegate.last_paint_call["for_drag_preview"] is False

    def test_paint_does_not_crash(self, qt_app) -> None:
        """paint() 基本调用不崩溃（含 hover/selected 等状态）。"""
        delegate = _ConcreteTestDelegate()
        pixmap = QPixmap(200, 200)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)

        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 200, 200)
        option.state = QStyle.State_Enabled | QStyle.State_MouseOver
        index = QModelIndex()

        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()

    def test_build_drag_pixmap_returns_valid_pixmap(self, qt_app) -> None:
        """build_drag_pixmap 返回有效非空像素图。"""
        delegate = _ConcreteTestDelegate()
        palette = QPalette()
        index = QModelIndex()

        pixmap = delegate.build_drag_pixmap(index, QSize(100, 100), palette)
        assert pixmap is not None
        assert not pixmap.isNull()

    def test_build_drag_pixmap_for_drag_preview_flag(self, qt_app) -> None:
        """build_drag_pixmap 传入 for_drag_preview=True。"""
        delegate = _ConcreteTestDelegate()
        palette = QPalette()
        index = QModelIndex()

        delegate.build_drag_pixmap(index, QSize(100, 100), palette)
        assert hasattr(delegate, "last_paint_call")
        assert delegate.last_paint_call["for_drag_preview"] is True

    def test_build_drag_pixmap_with_view(self, qt_app) -> None:
        """当 _view 已设置时 build_drag_pixmap 使用 option.initFrom。"""
        delegate = _ConcreteTestDelegate()
        from PySide6.QtWidgets import QWidget
        mock_view = MagicMock(spec=QAbstractItemView)
        mock_view.viewport.return_value = QWidget()
        delegate.set_view(mock_view)

        palette = QPalette()
        index = QModelIndex()
        pixmap = delegate.build_drag_pixmap(index, QSize(100, 100), palette)
        assert not pixmap.isNull()

    def test_get_paint_colors_normal(self, qt_app) -> None:
        """普通状态的绘制颜色包含 6 个返回值。"""
        delegate = _ConcreteTestDelegate()
        anim_state = delegate._default_anim_state()
        geometry = {"border_width": 2, "preview_border_width": 3}
        result = delegate._get_paint_colors(geometry, False, False, anim_state)
        assert len(result) == 6
        bg, border, shadow, blur, border_width, opacity = result
        assert opacity == 1.0

    def test_get_paint_colors_dragging_source(self, qt_app) -> None:
        """拖拽源状态时 opacity 为 0.4。"""
        delegate = _ConcreteTestDelegate()
        geometry = {"border_width": 2, "preview_border_width": 3}
        anim_state = delegate._default_anim_state()
        result = delegate._get_paint_colors(
            geometry, False, False, anim_state, is_dragging_source=True,
        )
        assert result[5] == 0.4  # opacity

    def test_get_paint_colors_drag_preview(self, qt_app) -> None:
        """拖拽预览时 opacity 为 1.0。"""
        delegate = _ConcreteTestDelegate()
        geometry = {"border_width": 2, "preview_border_width": 3}
        anim_state = delegate._default_anim_state()
        result = delegate._get_paint_colors(
            geometry, False, False, anim_state, for_drag_preview=True,
        )
        assert result[5] == 1.0  # opacity

    def test_resolve_card_rect_basic(self, qt_app) -> None:
        """_resolve_card_rect 对有效 option 返回 QRect。"""
        delegate = _ConcreteTestDelegate()
        option = QStyleOptionViewItem()
        option.rect = QRect(10, 20, 300, 100)
        index = QModelIndex()

        rect = delegate._resolve_card_rect(option, index)
        assert isinstance(rect, QRect)
        assert rect.width() >= 0

    def test_resolve_card_rect_drag_preview(self, qt_app) -> None:
        """拖拽预览时直接返回 option.rect。"""
        delegate = _ConcreteTestDelegate()
        option = QStyleOptionViewItem()
        option.rect = QRect(10, 20, 300, 100)
        index = QModelIndex()

        rect = delegate._resolve_card_rect(option, index, for_drag_preview=True)
        assert rect == option.rect


# ---------------------------------------------------------------------------
# 6. 工具方法
# ---------------------------------------------------------------------------

class TestBaseCardDelegateUtilities:
    """测试辅助工具方法。"""

    def test_normalize_path(self, qt_app) -> None:
        """_normalize_path 标准化路径分隔符。"""
        import os
        delegate = _ConcreteTestDelegate()
        result = delegate._normalize_path("C:\\test\\dir\\file.txt")
        expected = os.path.normpath("C:\\test\\dir\\file.txt")
        assert result == expected

    def test_normalize_path_empty(self, qt_app) -> None:
        """_normalize_path 对空字符串返回空。"""
        delegate = _ConcreteTestDelegate()
        assert delegate._normalize_path("") == ""
        assert delegate._normalize_path(None) == ""

    def test_format_created_text_empty(self, qt_app) -> None:
        """空或 None 的创建时间返回空字符串。"""
        delegate = _ConcreteTestDelegate()
        assert delegate._format_created_text("") == ""
        assert delegate._format_created_text(None) == ""

    def test_format_created_text_valid_iso(self, qt_app) -> None:
        """有效 ISO 日期格式化为 yyyy-MM-dd。"""
        delegate = _ConcreteTestDelegate()
        result = delegate._format_created_text("2024-01-15T10:30:00")
        assert result == "2024-01-15"

    def test_format_created_text_fallback(self, qt_app) -> None:
        """非 ISO 但长度足够的字符串截取前 10 字符。"""
        delegate = _ConcreteTestDelegate()
        result = delegate._format_created_text("2024/01/15_foo")
        assert result == "2024/01/15"
        # 长度不足 10 的原文返回
        short = "short"
        assert delegate._format_created_text(short) == short

    def test_transition_meta_hover(self, qt_app) -> None:
        """_transition_meta hover 进入动画为 180ms out_quint。"""
        delegate = _ConcreteTestDelegate()
        duration, easing = delegate._transition_meta(False, False, False, True, False, False)
        assert duration == 180
        assert easing == "out_quint"

    def test_transition_meta_selected(self, qt_app) -> None:
        """_transition_meta selected 进入动画为 190ms out_quint。"""
        delegate = _ConcreteTestDelegate()
        duration, easing = delegate._transition_meta(False, False, False, False, True, False)
        assert duration == 190
        assert easing == "out_quint"

    def test_transition_meta_preview(self, qt_app) -> None:
        """_transition_meta preview 进入动画为 220ms out_quint。"""
        delegate = _ConcreteTestDelegate()
        duration, easing = delegate._transition_meta(False, False, False, False, False, True)
        assert duration == 220
        assert easing == "out_quint"

    def test_transition_meta_unhover(self, qt_app) -> None:
        """_transition_meta hover 退出动画为 220ms in_out_cubic。"""
        delegate = _ConcreteTestDelegate()
        duration, easing = delegate._transition_meta(True, False, False, False, False, False)
        assert duration == 220
        assert easing == "in_out_cubic"
