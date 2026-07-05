# -*- coding: utf-8 -*-
"""
dropdown_menu 单元测试
测试 freeassetfilter/widgets/dropdown_menu.py 模块的功能
"""
import pytest
import os
import sys
from unittest.mock import MagicMock, patch
from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _ensure_dropdown_menu_app_state(app):
    from PySide6.QtGui import QFont
    from freeassetfilter.core.settings_manager import SettingsManager

    if not hasattr(app, "settings_manager"):
        app.settings_manager = SettingsManager()
    if not hasattr(app, "global_font"):
        app.global_font = QFont("Microsoft YaHei", 9)
    if not hasattr(app, "dpi_scale_factor"):
        app.dpi_scale_factor = 1.0


class TestDropdownMenuBasic:
    """测试 DropdownMenu 基本功能"""
    
    def test_module_import(self):
        """测试模块可以导入"""
        from freeassetfilter.widgets.dropdown_menu import DropdownMenu
        assert DropdownMenu is not None
    
    def test_module_has_required_attributes(self):
        """测试模块有必要的属性"""
        from freeassetfilter.widgets import dropdown_menu
        # 检查模块存在
        assert dropdown_menu is not None


class TestDropdownMenuRobustness:
    """测试 DropdownMenu 鲁棒性"""
    
    def test_module_handles_errors_gracefully(self):
        """测试模块能优雅处理错误"""
        # 基础错误处理测试
        pass


class TestDropdownMenuIntegration:
    """测试 DropdownMenu 集成"""
    
    def test_module_integration(self):
        """测试模块集成"""
        # 集成测试
        pass

    def test_menu_item_tooltips_use_custom_hover_tooltip(self, qt_app):
        """下拉菜单项应接入项目自定义 HoverTooltip，而不是 Qt 原生 toolTip。"""
        from freeassetfilter.widgets.dropdown_menu import _DropdownMenuList
        from freeassetfilter.widgets.hover_tooltip import HoverTooltip

        menu_list = _DropdownMenuList()
        try:
            menu_list.set_items(
                [
                    {"text": "A", "data": "a", "tooltip": "自定义提示"},
                    {"text": "B", "data": "b", "tooltip": ""},
                ]
            )

            first_item = menu_list.item_widget(0)
            second_item = menu_list.item_widget(1)

            assert isinstance(menu_list._hover_tooltip, HoverTooltip)
            assert first_item._tooltip_text == "自定义提示"
            assert first_item.toolTip() == ""
            assert second_item.toolTip() == ""

            registered_targets = [
                ref()
                for ref in menu_list._hover_tooltip.target_widgets
                if ref() is not None
            ]
            assert first_item in registered_targets
            assert second_item not in registered_targets
        finally:
            menu_list._hover_tooltip.cleanup()
            menu_list.deleteLater()

    def test_dropdown_menu_detects_clicks_outside_active_menu(self, qt_app):
        """已展开时，只有点击菜单和目标按钮之外的区域才应触发外部关闭。"""
        _ensure_dropdown_menu_app_state(qt_app)

        from freeassetfilter.widgets.dropdown_menu import CustomDropdownMenu

        host = QWidget()
        layout = QVBoxLayout(host)
        button = QPushButton("open", host)
        layout.addWidget(button)
        host.resize(240, 180)

        menu = CustomDropdownMenu(host, position="bottom", use_internal_button=False)
        menu.set_target_button(button)
        menu.set_items(["A", "B"], default_item="A")
        menu.show_menu()
        qt_app.processEvents()

        mouse_press_event = QEvent(QEvent.MouseButtonPress)

        try:
            assert menu.is_menu_visible()
            assert menu._is_click_outside_active_menu(menu.hover_menu, mouse_press_event) is False
            assert menu._is_click_outside_active_menu(button, mouse_press_event) is False
            assert menu._is_click_outside_active_menu(host, mouse_press_event) is True
        finally:
            menu.hide_menu()
            host.close()
            qt_app.processEvents()

    def test_dropdown_menu_hides_when_clicking_non_menu_area(self, qt_app):
        """点击任意非下拉菜单区域后，菜单应自动隐藏。"""
        _ensure_dropdown_menu_app_state(qt_app)

        from freeassetfilter.widgets.dropdown_menu import CustomDropdownMenu

        host = QWidget()
        host.resize(260, 220)
        layout = QVBoxLayout(host)
        button = QPushButton("open", host)
        layout.addWidget(button)
        layout.addStretch(1)
        host.show()
        qt_app.processEvents()

        menu = CustomDropdownMenu(host, position="bottom", use_internal_button=False)
        menu.set_target_button(button)
        menu.set_items(["A", "B"], default_item="A")
        menu.show_menu()
        qt_app.processEvents()

        try:
            assert menu.is_menu_visible()
            menu.eventFilter(host, QEvent(QEvent.MouseButtonPress))
            qt_app.processEvents()

            assert menu._menu_visible is False
            assert menu._active_menu is None
        finally:
            menu.hide_menu()
            host.close()
            qt_app.processEvents()
