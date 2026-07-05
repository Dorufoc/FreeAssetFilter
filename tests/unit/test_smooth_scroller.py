# -*- coding: utf-8 -*-
"""
smooth_scroller 单元测试
测试 freeassetfilter/widgets/smooth_scroller.py 模块的功能
"""
import pytest
import os
import sys
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QObject, QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget


class _MappedSettingsManager:
    def __init__(self, overrides=None):
        self._overrides = overrides or {}

    def get_setting(self, key, default=None):
        return self._overrides.get(key, default)


class TestSmoothScrollerBasic:
    """测试 SmoothScroller 基本功能"""
    
    def test_module_import(self):
        """测试模块可以导入"""
        from freeassetfilter.widgets.smooth_scroller import SmoothScroller
        assert SmoothScroller is not None
    
    def test_module_has_required_attributes(self):
        """测试模块有必要的属性"""
        from freeassetfilter.widgets import smooth_scroller
        # 检查模块存在
        assert smooth_scroller is not None


class TestSmoothScrollerRobustness:
    """测试 SmoothScroller 鲁棒性"""
    
    def test_module_handles_errors_gracefully(self):
        """测试模块能优雅处理错误"""
        # 基础错误处理测试
        pass


class TestSmoothScrollerIntegration:
    """测试 SmoothScroller 集成"""
    
    def test_module_integration(self):
        """测试模块集成"""
        # 集成测试
        pass

    def test_apply_removes_existing_wheel_filter_when_smooth_scrolling_disabled(self, qt_app, monkeypatch):
        from freeassetfilter.widgets.smooth_scroller import SmoothScroller

        monkeypatch.setattr(
            qt_app,
            "settings_manager",
            _MappedSettingsManager({"appearance.animations.smooth_scrolling": False}),
            raising=False,
        )

        widget = QWidget()
        wheel_filter = QObject(widget)
        widget._smooth_wheel_filter = wheel_filter
        widget.installEventFilter(wheel_filter)

        try:
            SmoothScroller.apply(widget)
            assert widget._smooth_wheel_filter is None
        finally:
            widget.close()


class TestWheelSmoothScrollBoundaries:
    """测试滚轮平滑滚动在边界处不会保留越界目标。"""

    def test_scrollbar_size_hint_collapses_when_scrollbar_is_not_needed(self, qt_app):
        from freeassetfilter.widgets.smooth_scroller import D_ScrollBar

        scrollbar = D_ScrollBar(Qt.Vertical)
        scrollbar.set_default_width(6)

        try:
            scrollbar.setRange(0, 0)
            scrollbar.update_width_immediately()
            assert scrollbar.sizeHint().width() == 0
            assert scrollbar.minimumSizeHint().width() == 0

            scrollbar.setRange(0, 100)
            scrollbar.update_width_immediately()
            assert scrollbar.sizeHint().width() == 6
            assert scrollbar.minimumSizeHint().width() == 6
        finally:
            scrollbar.close()

    def test_content_overscroll_effect_accepts_pyside_pixmap_result(self, qt_app):
        from freeassetfilter.widgets.smooth_scroller import _ContentOverscrollEffect

        pixmap = QPixmap(4, 4)

        result_pixmap, source_offset = _ContentOverscrollEffect._split_source_pixmap_result(pixmap)

        assert result_pixmap is pixmap
        assert source_offset == QPoint(0, 0)

    def test_content_overscroll_effect_accepts_tuple_source_result(self, qt_app):
        from freeassetfilter.widgets.smooth_scroller import _ContentOverscrollEffect

        pixmap = QPixmap(4, 4)
        offset = QPoint(2, 3)

        result_pixmap, source_offset = _ContentOverscrollEffect._split_source_pixmap_result((pixmap, offset))

        assert result_pixmap is pixmap
        assert source_offset == offset

    def test_pending_target_is_clamped_at_bottom_before_reverse_scroll(self, qt_app):
        from freeassetfilter.widgets.smooth_scroller import D_ScrollBar, _WheelSmoothScrollFilter

        host = QWidget()
        target = QWidget()
        scrollbar = D_ScrollBar(Qt.Vertical, host)
        scrollbar.setRange(0, 100)
        scrollbar.setValue(90)
        wheel_filter = _WheelSmoothScrollFilter(host, target)

        try:
            assert wheel_filter._calculate_target_value(scrollbar, scrollbar.value(), -40) == 100
            assert wheel_filter._pending_vertical_target == 100

            scrollbar.setValue(100)
            assert wheel_filter._calculate_target_value(scrollbar, scrollbar.value(), 20) == 80
            assert wheel_filter._pending_vertical_target == 80
        finally:
            scrollbar.close()
            host.close()
            target.close()

    def test_bottom_overscroll_triggers_elastic_feedback(self, qt_app, monkeypatch):
        from freeassetfilter.widgets.smooth_scroller import D_ScrollBar, _WheelSmoothScrollFilter

        monkeypatch.setattr(
            qt_app,
            "settings_manager",
            _MappedSettingsManager({"appearance.animations.smooth_scrolling": True}),
            raising=False,
        )

        host = QWidget()
        target = QWidget()
        scrollbar = D_ScrollBar(Qt.Vertical, host)
        scrollbar.setRange(0, 100)
        scrollbar.setValue(100)
        wheel_filter = _WheelSmoothScrollFilter(host, target)
        calls = []
        content_calls = []
        monkeypatch.setattr(scrollbar, "trigger_elastic_overscroll", lambda direction, strength=1.0: calls.append((direction, strength)))
        monkeypatch.setattr(
            wheel_filter._content_overscroll,
            "trigger",
            lambda orientation, direction, strength=1.0: content_calls.append((orientation, direction, strength)),
        )

        try:
            assert wheel_filter._trigger_elastic_overscroll_if_needed(scrollbar, scrollbar.value(), -20)
            assert calls == [(1, 7.0)]
            assert content_calls == [(Qt.Vertical, 1, 11.0)]
        finally:
            scrollbar.close()
            host.close()
            target.close()

    def test_top_overscroll_triggers_elastic_feedback(self, qt_app, monkeypatch):
        from freeassetfilter.widgets.smooth_scroller import D_ScrollBar, _WheelSmoothScrollFilter

        monkeypatch.setattr(
            qt_app,
            "settings_manager",
            _MappedSettingsManager({"appearance.animations.smooth_scrolling": True}),
            raising=False,
        )

        host = QWidget()
        target = QWidget()
        scrollbar = D_ScrollBar(Qt.Vertical, host)
        scrollbar.setRange(0, 100)
        scrollbar.setValue(0)
        wheel_filter = _WheelSmoothScrollFilter(host, target)
        calls = []
        content_calls = []
        monkeypatch.setattr(scrollbar, "trigger_elastic_overscroll", lambda direction, strength=1.0: calls.append((direction, strength)))
        monkeypatch.setattr(
            wheel_filter._content_overscroll,
            "trigger",
            lambda orientation, direction, strength=1.0: content_calls.append((orientation, direction, strength)),
        )

        try:
            assert wheel_filter._trigger_elastic_overscroll_if_needed(scrollbar, scrollbar.value(), 20)
            assert calls == [(-1, 7.0)]
            assert content_calls == [(Qt.Vertical, -1, 11.0)]
        finally:
            scrollbar.close()
            host.close()
            target.close()

    def test_scrollbar_elastic_overscroll_accumulates_with_damping(self, qt_app, monkeypatch):
        from freeassetfilter.widgets.smooth_scroller import D_ScrollBar

        monkeypatch.setattr(
            qt_app,
            "settings_manager",
            _MappedSettingsManager({"appearance.animations.smooth_scrolling": True}),
            raising=False,
        )

        scrollbar = D_ScrollBar(Qt.Vertical)
        scrollbar.resize(12, 180)
        scrollbar.setRange(0, 100)
        captured_targets = []
        starts = []
        monkeypatch.setattr(scrollbar._elastic_overscroll_anim, "setKeyValueAt", lambda step, value: captured_targets.append(float(value)))
        monkeypatch.setattr(scrollbar._elastic_overscroll_anim, "start", lambda: starts.append(1))

        try:
            assert scrollbar._elastic_overscroll_anim.duration() == 380

            scrollbar.trigger_elastic_overscroll(1, strength=14.0)
            scrollbar._elastic_overscroll_value = 8.0
            scrollbar.trigger_elastic_overscroll(1, strength=14.0)

            assert len(starts) == 2
            assert captured_targets[1] > captured_targets[0]
            assert captured_targets[1] <= scrollbar._get_elastic_overscroll_limit()
        finally:
            scrollbar.close()

    def test_non_boundary_scroll_does_not_trigger_elastic_feedback(self, qt_app, monkeypatch):
        from freeassetfilter.widgets.smooth_scroller import D_ScrollBar, _WheelSmoothScrollFilter

        monkeypatch.setattr(
            qt_app,
            "settings_manager",
            _MappedSettingsManager({"appearance.animations.smooth_scrolling": True}),
            raising=False,
        )

        host = QWidget()
        target = QWidget()
        scrollbar = D_ScrollBar(Qt.Vertical, host)
        scrollbar.setRange(0, 100)
        scrollbar.setValue(50)
        wheel_filter = _WheelSmoothScrollFilter(host, target)
        calls = []
        content_calls = []
        monkeypatch.setattr(scrollbar, "trigger_elastic_overscroll", lambda direction, strength=1.0: calls.append((direction, strength)))
        monkeypatch.setattr(
            wheel_filter._content_overscroll,
            "trigger",
            lambda orientation, direction, strength=1.0: content_calls.append((orientation, direction, strength)),
        )

        try:
            assert not wheel_filter._trigger_elastic_overscroll_if_needed(scrollbar, scrollbar.value(), 20)
            assert calls == []
            assert content_calls == []
        finally:
            scrollbar.close()
            host.close()
            target.close()

    def test_smooth_scrolling_setting_disables_elastic_feedback(self, qt_app, monkeypatch):
        from freeassetfilter.widgets.smooth_scroller import D_ScrollBar, _WheelSmoothScrollFilter

        monkeypatch.setattr(
            qt_app,
            "settings_manager",
            _MappedSettingsManager({"appearance.animations.smooth_scrolling": False}),
            raising=False,
        )

        host = QWidget()
        target = QWidget()
        scrollbar = D_ScrollBar(Qt.Vertical, host)
        scrollbar.setRange(0, 100)
        scrollbar.setValue(100)
        wheel_filter = _WheelSmoothScrollFilter(host, target)
        calls = []
        content_calls = []
        monkeypatch.setattr(scrollbar, "trigger_elastic_overscroll", lambda direction, strength=1.0: calls.append((direction, strength)))
        monkeypatch.setattr(
            wheel_filter._content_overscroll,
            "trigger",
            lambda orientation, direction, strength=1.0: content_calls.append((orientation, direction, strength)),
        )

        try:
            assert not wheel_filter._trigger_elastic_overscroll_if_needed(scrollbar, scrollbar.value(), -20)
            assert calls == []
            assert content_calls == []
        finally:
            scrollbar.close()
            host.close()
            target.close()

    def test_scrollbar_elastic_overscroll_resets_when_smooth_scrolling_disabled(self, qt_app, monkeypatch):
        from freeassetfilter.widgets.smooth_scroller import D_ScrollBar

        monkeypatch.setattr(
            qt_app,
            "settings_manager",
            _MappedSettingsManager({"appearance.animations.smooth_scrolling": False}),
            raising=False,
        )

        scrollbar = D_ScrollBar(Qt.Vertical)
        scrollbar.resize(12, 180)
        scrollbar.setRange(0, 100)
        starts = []
        monkeypatch.setattr(scrollbar._elastic_overscroll_anim, "start", lambda: starts.append(1))
        scrollbar._elastic_overscroll_value = 8.0
        scrollbar._elastic_overscroll_target_value = 14.0

        try:
            scrollbar.trigger_elastic_overscroll(1, strength=14.0)

            assert starts == []
            assert scrollbar._elastic_overscroll_value == 0.0
            assert scrollbar._elastic_overscroll_target_value == 0.0
        finally:
            scrollbar.close()

    def test_pending_target_is_clamped_at_top_before_reverse_scroll(self, qt_app):
        from freeassetfilter.widgets.smooth_scroller import D_ScrollBar, _WheelSmoothScrollFilter

        host = QWidget()
        target = QWidget()
        scrollbar = D_ScrollBar(Qt.Vertical, host)
        scrollbar.setRange(0, 100)
        scrollbar.setValue(10)
        wheel_filter = _WheelSmoothScrollFilter(host, target)

        try:
            assert wheel_filter._calculate_target_value(scrollbar, scrollbar.value(), 40) == 0
            assert wheel_filter._pending_vertical_target == 0

            scrollbar.setValue(0)
            assert wheel_filter._calculate_target_value(scrollbar, scrollbar.value(), -20) == 20
            assert wheel_filter._pending_vertical_target == 20
        finally:
            scrollbar.close()
            host.close()
            target.close()


class TestContentOverscroll:
    """测试滚动内容本身的边界回弹。"""

    def test_content_overscroll_applies_temporary_graphics_effect(self, qt_app, monkeypatch):
        from freeassetfilter.widgets.smooth_scroller import _ElasticContentOverscrollController

        monkeypatch.setattr(
            qt_app,
            "settings_manager",
            _MappedSettingsManager({"appearance.animations.smooth_scrolling": True}),
            raising=False,
        )

        target = QWidget()
        target.resize(200, 160)
        controller = _ElasticContentOverscrollController(target)
        monkeypatch.setattr(controller._animation, "start", lambda: None)

        try:
            assert controller.trigger(Qt.Vertical, -1, strength=12.0)
            assert target.graphicsEffect() is controller._effect

            controller._set_offset(12.0)
            assert controller._effect._offset.y() == 12
            assert controller._effect._offset.x() == 0

            controller._set_offset(0.0)
            controller._release_effect_if_idle()
            assert target.graphicsEffect() is None
        finally:
            target.close()

    def test_content_overscroll_respects_smooth_scrolling_setting(self, qt_app, monkeypatch):
        from freeassetfilter.widgets.smooth_scroller import _ElasticContentOverscrollController

        monkeypatch.setattr(
            qt_app,
            "settings_manager",
            _MappedSettingsManager({"appearance.animations.smooth_scrolling": False}),
            raising=False,
        )

        target = QWidget()
        target.resize(200, 160)
        controller = _ElasticContentOverscrollController(target)
        controller._ensure_effect()
        controller._offset_value = 12.0
        controller._target_offset_value = 20.0

        try:
            assert not controller.trigger(Qt.Vertical, -1, strength=12.0)
            assert target.graphicsEffect() is None
            assert controller._offset_value == 0.0
            assert controller._target_offset_value == 0.0
        finally:
            target.close()

    def test_apply_resets_content_overscroll_when_smooth_scrolling_disabled(self, qt_app, monkeypatch):
        from freeassetfilter.widgets.smooth_scroller import SmoothScroller, _WheelSmoothScrollFilter

        monkeypatch.setattr(
            qt_app,
            "settings_manager",
            _MappedSettingsManager({"appearance.animations.smooth_scrolling": False}),
            raising=False,
        )

        host = QWidget()
        target = host
        wheel_filter = _WheelSmoothScrollFilter(host, target)
        target._smooth_wheel_filter = wheel_filter
        target.installEventFilter(wheel_filter)
        wheel_filter._content_overscroll._ensure_effect()
        wheel_filter._content_overscroll._offset_value = 12.0
        wheel_filter._content_overscroll._target_offset_value = 20.0

        try:
            SmoothScroller.apply(host)

            assert target._smooth_wheel_filter is None
            assert target.graphicsEffect() is None
            assert wheel_filter._content_overscroll._offset_value == 0.0
            assert wheel_filter._content_overscroll._target_offset_value == 0.0
        finally:
            host.close()

    def test_content_overscroll_accumulates_with_stronger_edge_damping(self, qt_app, monkeypatch):
        from freeassetfilter.widgets.smooth_scroller import _ElasticContentOverscrollController

        monkeypatch.setattr(
            qt_app,
            "settings_manager",
            _MappedSettingsManager({"appearance.animations.smooth_scrolling": True}),
            raising=False,
        )

        target = QWidget()
        target.resize(200, 400)
        controller = _ElasticContentOverscrollController(target)
        captured_targets = []
        starts = []
        monkeypatch.setattr(controller._animation, "setKeyValueAt", lambda step, value: captured_targets.append(float(value)))
        monkeypatch.setattr(controller._animation, "start", lambda: starts.append(1))

        try:
            assert controller._animation.duration() == 380

            assert controller.trigger(Qt.Vertical, 1, strength=20.0)
            controller._offset_value = -10.0
            assert controller.trigger(Qt.Vertical, 1, strength=20.0)
            first_increment = abs(captured_targets[1]) - abs(captured_targets[0])

            controller._offset_value = -30.0
            controller._target_offset_value = -30.0
            assert controller.trigger(Qt.Vertical, 1, strength=20.0)
            near_limit_increment = abs(captured_targets[2]) - 30.0

            assert len(starts) == 3
            assert abs(captured_targets[1]) > abs(captured_targets[0])
            assert near_limit_increment < first_increment
            assert abs(captured_targets[2]) <= controller._get_overscroll_limit(Qt.Vertical)
        finally:
            target.close()
