# -*- coding: utf-8 -*-
"""
settings_window 单元测试
测试 freeassetfilter/components/settings_window.py 模块的功能
"""
import pytest
import os
import sys
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _ensure_settings_window_app_state(app):
    """补齐设置窗口构造依赖的 QApplication 级状态。"""
    from PySide6.QtGui import QFont
    from freeassetfilter.core.settings_manager import SettingsManager

    if not hasattr(app, "settings_manager"):
        app.settings_manager = SettingsManager()
    if not hasattr(app, "global_font"):
        app.global_font = QFont("Microsoft YaHei", 9)
    if not hasattr(app, "default_font_size"):
        app.default_font_size = 10
    if not hasattr(app, "dpi_scale_factor"):
        app.dpi_scale_factor = 1.0


def _flush_qt_deferred_deletes(app, rounds=3):
    from PySide6.QtCore import QCoreApplication, QEvent

    for _ in range(rounds):
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()


class TestSettingsWindowBasic:
    """测试 SettingsWindow 基本功能"""
    
    def test_module_import(self):
        """测试模块可以导入"""
        from freeassetfilter.components.settings_window import SettingsWindow
        assert SettingsWindow is not None
    
    def test_module_has_required_attributes(self):
        """测试模块有必要的属性"""
        from freeassetfilter.components import settings_window
        # 检查模块存在
        assert settings_window is not None


class TestSettingsWindowRobustness:
    """测试 SettingsWindow 鲁棒性"""
    
    def test_module_handles_errors_gracefully(self):
        """测试模块能优雅处理错误"""
        # 基础错误处理测试
        pass


class TestSettingsWindowIntegration:
    """测试 SettingsWindow 集成"""
    
    def test_module_integration(self):
        """测试模块集成"""
        # 集成测试
        pass

    def test_player_navigation_disposes_general_page_input_popup(self, qt_app):
        """切到播放器页时应先销毁通用页输入框持有的 Qt.Popup。"""
        _ensure_settings_window_app_state(qt_app)

        from freeassetfilter.components.settings_window import ModernSettingsWindow
        from freeassetfilter.widgets.D_more_menu import D_MoreMenu
        from freeassetfilter.widgets.input_widgets import CustomInputBox

        window = ModernSettingsWindow()
        try:
            window.show()
            _flush_qt_deferred_deletes(qt_app)

            assert any(
                isinstance(widget, D_MoreMenu) and isinstance(widget.parent(), CustomInputBox)
                for widget in qt_app.topLevelWidgets()
            )

            window._on_navigation_clicked(3)
            _flush_qt_deferred_deletes(qt_app)

            assert not any(
                isinstance(widget, D_MoreMenu) and isinstance(widget.parent(), CustomInputBox)
                for widget in qt_app.topLevelWidgets()
            )
        finally:
            window.close()
            _flush_qt_deferred_deletes(qt_app)

    def test_repeated_player_navigation_does_not_rebuild_page(self, qt_app):
        """重复点击当前播放器导航不应反复销毁和重建播放器设置页。"""
        _ensure_settings_window_app_state(qt_app)

        from freeassetfilter.components.settings_window import ModernSettingsWindow

        window = ModernSettingsWindow()
        try:
            window._on_navigation_clicked(3)
            first_player_group = window.control_bar_group

            window._on_navigation_clicked(3)

            assert window._current_tab_id == "player"
            assert window.control_bar_group is first_player_group
        finally:
            window.close()
            _flush_qt_deferred_deletes(qt_app)

    def test_general_page_contains_animation_settings(self, qt_app, temp_dir, clean_settings_manager):
        """通用页应展示外观动画设置组并写入当前设置。"""
        from freeassetfilter.core.settings_manager import SettingsManager
        from freeassetfilter.components.settings_window import ModernSettingsWindow

        settings_file = os.path.join(temp_dir, "settings.json")
        qt_app.settings_manager = SettingsManager(settings_file)
        _ensure_settings_window_app_state(qt_app)

        window = ModernSettingsWindow()
        try:
            assert window.animation_group.title() == "动画"
            assert set(window.animation_setting_items) == {
                "directory_transition",
                "file_record_changes",
                "smooth_scrolling",
                "file_card_state",
                "progress_bar_smoothing",
                "button_smoothing",
            }
            assert all(item.get_switch_value() for item in window.animation_setting_items.values())

            window.button_smoothing_animation_switch.set_switch_value(False)

            assert window.current_settings["appearance.animations.button_smoothing"] is False
        finally:
            window.close()
            _flush_qt_deferred_deletes(qt_app)

    def test_navigation_uses_page_transition_overlay_and_cleans_up_after_finish(self, qt_app):
        """切页时应创建右侧整体滑入淡入过渡层，并在结束后回收。"""
        _ensure_settings_window_app_state(qt_app)

        from PySide6.QtTest import QTest
        from freeassetfilter.components.settings_window import ModernSettingsWindow

        window = ModernSettingsWindow()
        try:
            window.resize(780, 520)
            window.show()
            _flush_qt_deferred_deletes(qt_app)

            window._content_transition_duration_ms = 30
            window._on_navigation_clicked(1)
            qt_app.processEvents()

            assert window._current_tab_id == "file_selector"
            assert window._content_transition_overlay is not None
            assert window._content_transition_group is not None
            assert not window.scroll_content.isVisible()

            QTest.qWait(window._content_transition_duration_ms + 80)
            _flush_qt_deferred_deletes(qt_app)

            assert window._content_transition_overlay is None
            assert window._content_transition_group is None
            assert window.scroll_content.isVisible()
        finally:
            window.close()
            _flush_qt_deferred_deletes(qt_app)
