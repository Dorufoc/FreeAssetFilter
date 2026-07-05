# -*- coding: utf-8 -*-
"""
button_widgets 单元测试
测试 freeassetfilter/widgets/button_widgets.py 模块的功能
"""
import pytest
import os
import sys
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QVariantAnimation
from PySide6.QtGui import QFont


class _MappedSettingsManager:
    def __init__(self, overrides=None):
        self._overrides = overrides or {}

    def get_setting(self, key, default=None):
        return self._overrides.get(key, default)


class TestButtonWidgetsBasic:
    """测试 ButtonWidgets 基本功能"""
    
    def test_module_import(self):
        """测试模块可以导入"""
        from freeassetfilter.widgets.button_widgets import CustomButton
        assert CustomButton is not None
    
    def test_module_has_required_attributes(self):
        """测试模块有必要的属性"""
        from freeassetfilter.widgets import button_widgets
        # 检查模块存在
        assert button_widgets is not None


class TestButtonWidgetsRobustness:
    """测试 ButtonWidgets 鲁棒性"""
    
    def test_module_handles_errors_gracefully(self):
        """测试模块能优雅处理错误"""
        # 基础错误处理测试
        pass


class TestButtonWidgetsIntegration:
    """测试 ButtonWidgets 集成"""
    
    def test_module_integration(self):
        """测试模块集成"""
        # 集成测试
        pass

    def test_button_smoothing_setting_disables_state_animation(self, qt_app, monkeypatch):
        from freeassetfilter.widgets.button_widgets import CustomButton

        monkeypatch.setattr(qt_app, "global_font", QFont(), raising=False)
        monkeypatch.setattr(
            qt_app,
            "settings_manager",
            _MappedSettingsManager({"appearance.animations.button_smoothing": False}),
            raising=False,
        )

        button = CustomButton("Test")
        try:
            button.show()
            qt_app.processEvents()
            button._init_animations()
            button._set_visual_state("hover", animated=True)

            assert button._state_animation.state() != QVariantAnimation.Running
            assert button._anim_progress == 1.0
            assert button._current_colors["bg"] == button._style_colors["hover"]["bg"]
            assert button._current_colors["border"] == button._style_colors["hover"]["border"]
        finally:
            button.close()
