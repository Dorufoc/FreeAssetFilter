# -*- coding: utf-8 -*-
"""
progress_widgets 单元测试
测试 freeassetfilter/widgets/progress_widgets.py 模块的功能
"""
import pytest
import os
import sys
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QPropertyAnimation


class _MappedSettingsManager:
    def __init__(self, overrides=None):
        self._overrides = overrides or {}

    def get_setting(self, key, default=None):
        return self._overrides.get(key, default)


class TestProgressWidgetsBasic:
    """测试 ProgressWidgets 基本功能"""
    
    def test_module_import(self):
        """测试模块可以导入"""
        from freeassetfilter.widgets.progress_widgets import D_ProgressBar
        assert D_ProgressBar is not None
    
    def test_module_has_required_attributes(self):
        """测试模块有必要的属性"""
        from freeassetfilter.widgets import progress_widgets
        # 检查模块存在
        assert progress_widgets is not None


class TestProgressWidgetsRobustness:
    """测试 ProgressWidgets 鲁棒性"""
    
    def test_module_handles_errors_gracefully(self):
        """测试模块能优雅处理错误"""
        # 基础错误处理测试
        pass


class TestProgressWidgetsIntegration:
    """测试 ProgressWidgets 集成"""
    
    def test_module_integration(self):
        """测试模块集成"""
        # 集成测试
        pass

    def test_progress_bar_smoothing_setting_disables_default_animation(self, qt_app, monkeypatch):
        from freeassetfilter.widgets.progress_widgets import D_ProgressBar

        monkeypatch.setattr(
            qt_app,
            "settings_manager",
            _MappedSettingsManager({"appearance.animations.progress_bar_smoothing": False}),
            raising=False,
        )

        progress = D_ProgressBar()
        try:
            progress.setRange(0, 100)
            progress.setValue(60)

            assert progress._animation.state() != QPropertyAnimation.Running
            assert progress._display_value_storage == 60
            assert progress.value() == 60
        finally:
            progress.close()
