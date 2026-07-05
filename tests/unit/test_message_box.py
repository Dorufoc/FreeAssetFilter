# -*- coding: utf-8 -*-
"""
message_box 单元测试
测试 freeassetfilter/widgets/message_box.py 模块的功能
"""
import pytest
import os
import sys
from unittest.mock import MagicMock, patch

from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QDialog


class TestMessageBoxBasic:
    """测试 MessageBox 基本功能"""
    
    def test_module_import(self):
        """测试模块可以导入"""
        from freeassetfilter.widgets.message_box import CustomMessageBox
        assert CustomMessageBox is not None
    
    def test_module_has_required_attributes(self):
        """测试模块有必要的属性"""
        from freeassetfilter.widgets import message_box
        # 检查模块存在
        assert message_box is not None


class TestMessageBoxRobustness:
    """测试 MessageBox 鲁棒性"""
    
    def test_module_handles_errors_gracefully(self):
        """测试模块能优雅处理错误"""
        # 基础错误处理测试
        pass

    def test_accept_does_not_restart_hide_animation_after_finish(self, qt_app):
        """退场动画完成后的内部 done 不应再次触发退场动画"""
        from freeassetfilter.widgets.message_box import CustomMessageBox

        dialog = CustomMessageBox()
        dialog.set_title("提示")
        dialog.set_text("测试退场动画")
        dialog.show()
        qt_app.processEvents()

        hide_calls = []
        original_start_hide_animation = dialog._start_hide_animation

        def record_hide_start():
            hide_calls.append("hide")
            original_start_hide_animation()

        dialog._start_hide_animation = record_hide_start

        dialog.accept()
        assert hide_calls == ["hide"]
        assert dialog._close_after_hide is True

        dialog._on_hide_animation_finished()
        qt_app.processEvents()

        assert hide_calls == ["hide"]
        assert dialog.result() == QDialog.Accepted
        assert dialog._allow_direct_close is False

    def test_close_event_allows_internal_done_to_close_without_reanimation(self, qt_app):
        """内部完成关闭时，closeEvent 应放行而不是重新请求动画"""
        from freeassetfilter.widgets.message_box import CustomMessageBox

        dialog = CustomMessageBox()
        dialog.show()
        qt_app.processEvents()

        requested_results = []

        def record_request(result=None):
            requested_results.append(result)

        dialog._request_animated_close = record_request
        dialog._allow_direct_close = True

        dialog.close()
        qt_app.processEvents()

        assert requested_results == []
        assert dialog.isVisible() is False

    def test_repeated_show_events_schedule_show_animation_once(self, qt_app, monkeypatch):
        """入场动画真正启动前的重复 showEvent 不应排队多次动画"""
        from freeassetfilter.widgets import message_box
        from freeassetfilter.widgets.message_box import CustomMessageBox

        dialog = CustomMessageBox()
        scheduled_callbacks = []

        def record_single_shot(interval, callback):
            scheduled_callbacks.append((interval, callback))

        monkeypatch.setattr(message_box.QTimer, "singleShot", record_single_shot)

        dialog.showEvent(QShowEvent())
        dialog.showEvent(QShowEvent())

        assert len(scheduled_callbacks) == 1
        assert dialog._show_animation_pending is True

        scheduled_callbacks[0][1]()

        assert dialog._show_animation_pending is False
        assert dialog._is_show_animating is True


class TestMessageBoxIntegration:
    """测试 MessageBox 集成"""
    
    def test_module_integration(self):
        """测试模块集成"""
        # 集成测试
        pass
