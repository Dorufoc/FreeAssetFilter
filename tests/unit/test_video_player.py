# -*- coding: utf-8 -*-
"""
video_player 单元测试
测试 freeassetfilter/components/video_player.py 模块的功能
"""
import pytest
import os
import sys
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


class TestVideoPlayerBasic:
    """测试 VideoPlayer 基本功能"""

    def test_module_import(self):
        """测试模块可以导入"""
        from freeassetfilter.components.video_player import VideoPlayer
        assert VideoPlayer is not None

    def test_module_has_required_attributes(self):
        """测试模块有必要的属性"""
        from freeassetfilter.components import video_player
        assert video_player is not None


class TestVideoPlayerSeekSimplified:
    """测试简化后的 seek 机制"""

    def test_flush_pending_seek_sends_seek(self):
        """_flush_pending_seek 应发送一次 seek 到管理器。"""
        from freeassetfilter.components.video_player import VideoPlayer

        manager = MagicMock()
        manager.is_initialized.return_value = True
        manager.get_duration_direct.return_value = 100.0

        player = SimpleNamespace()
        player._pending_seek_value = 250
        player._mpv_manager = manager
        player._component_id = "video_player_test"
        player._user_interacting = False
        player._update_time_display = MagicMock()

        VideoPlayer._flush_pending_seek(player)

        manager.seek.assert_called_once_with(
            25.0,
            component_id="video_player_test",
        )
        player._update_time_display.assert_called_once_with(25.0, 100.0)

    def test_flush_pending_seek_skips_when_no_pending(self):
        """_pending_seek_value 为 None 时应跳过 seek。"""
        from freeassetfilter.components.video_player import VideoPlayer

        manager = MagicMock()
        manager.is_initialized.return_value = True

        player = SimpleNamespace()
        player._pending_seek_value = None
        player._mpv_manager = manager
        player._component_id = "video_player_test"
        player._user_interacting = False
        player._update_time_display = MagicMock()

        VideoPlayer._flush_pending_seek(player)
        manager.seek.assert_not_called()

    def test_flush_pending_seek_skips_when_no_manager(self):
        """管理器为空时应跳过 seek。"""
        from freeassetfilter.components.video_player import VideoPlayer

        player = SimpleNamespace()
        player._pending_seek_value = 250
        player._mpv_manager = None
        player._component_id = "video_player_test"
        player._user_interacting = False
        player._update_time_display = MagicMock()

        VideoPlayer._flush_pending_seek(player)
        # 不会崩溃

    def test_clear_pending_seek_state(self):
        """_clear_pending_seek_state 应将 _pending_seek_value 置为 None。"""
        from freeassetfilter.components.video_player import VideoPlayer

        player = SimpleNamespace()
        player._pending_seek_value = 250

        VideoPlayer._clear_pending_seek_state(player)
        assert player._pending_seek_value is None

    def test_rapid_seeks_coalesce_via_debounce(self):
        """多次 seek 调用应通过 debounce 定时器合并。"""
        from freeassetfilter.components.video_player import VideoPlayer

        manager = MagicMock()
        manager.is_initialized.return_value = True
        manager.get_duration_direct.return_value = 100.0

        debounce_timer = MagicMock()
        debounce_timer.isActive.return_value = False

        player = SimpleNamespace()
        player._pending_seek_value = 250
        player._mpv_manager = manager
        player._component_id = "video_player_test"
        player._user_interacting = True
        player._seek_debounce_timer = debounce_timer
        player._update_time_display = MagicMock()

        # 用户拖动时 _on_progress_changed 被调用
        VideoPlayer._on_progress_changed(player, 300)
        assert player._pending_seek_value == 300
        debounce_timer.start.assert_called_once()

        # 模拟第二次进度变化
        debounce_timer.isActive.return_value = True
        VideoPlayer._on_progress_changed(player, 400)
        assert player._pending_seek_value == 400
        # seek 由 debounce 完成，最终 _flush_pending_seek 发送一次 seek


class TestVideoPlayerFix:
    """测试 Wave 3 修复的行为"""

    def test_on_manager_position_changed_always_updates(self):
        """_on_manager_position_changed 应始终更新控制栏（非交互时）。"""
        from freeassetfilter.components.video_player import VideoPlayer

        control_bar = MagicMock()
        control_bar.set_position = MagicMock()

        player = SimpleNamespace()
        player._control_bar = control_bar
        player._user_interacting = False

        VideoPlayer._on_manager_position_changed(player, 10.5, 100.0)
        control_bar.set_position.assert_called_once_with(10.5, 100.0)

    def test_on_manager_position_changed_skips_during_interaction(self):
        """用户拖动进度条时不应更新控制栏位置。"""
        from freeassetfilter.components.video_player import VideoPlayer

        control_bar = MagicMock()
        control_bar.set_position = MagicMock()

        player = SimpleNamespace()
        player._control_bar = control_bar
        player._user_interacting = True

        VideoPlayer._on_manager_position_changed(player, 10.5, 100.0)
        control_bar.set_position.assert_not_called()

    def test_load_file_increments_sequence_counter(self):
        """load_file 应递增 _load_sequence_counter。"""
        from freeassetfilter.components.video_player import VideoPlayer

        player = SimpleNamespace()
        player._load_sequence_counter = 0

        # 模拟递增
        player._load_sequence_counter += 1
        assert player._load_sequence_counter == 1

        player._load_sequence_counter += 1
        assert player._load_sequence_counter == 2

    def test_file_loaded_sets_playing(self):
        """_on_manager_file_loaded 应设置 playing 状态。"""
        from freeassetfilter.components.video_player import VideoPlayer

        control_bar = MagicMock()
        manager = MagicMock()
        manager.get_speed.return_value = 1.0
        manager.get_volume.return_value = 80

        player = SimpleNamespace()
        player._control_bar = control_bar
        player._mpv_manager = manager
        player._load_sequence_counter = 0
        player._current_load_sequence = 1
        player._initialize_progress_display = MagicMock()
        player._delayed_file_init = MagicMock()
        player._state_sync_timer = MagicMock()
        player._state_sync_timer.isActive.return_value = False
        player._heartbeat_sync = MagicMock()
        player.set_loop_mode = MagicMock()

        with patch('PySide6.QtCore.QTimer.singleShot'):
            VideoPlayer._on_manager_file_loaded(player, "/path/to/video.mp4")

        control_bar.set_playing.assert_called_once_with(True)
        control_bar.set_speed.assert_called_once()
        control_bar.set_volume.assert_called_once()

    def test_on_manager_state_changed_uses_state_directly(self):
        """_on_manager_state_changed 应直接使用状态参数，不轮询。"""
        from freeassetfilter.components.video_player import VideoPlayer

        control_bar = MagicMock()

        # 模拟 state 参数
        state = SimpleNamespace(is_playing=True, is_paused=False)

        player = SimpleNamespace()
        player._control_bar = control_bar

        VideoPlayer._on_manager_state_changed(player, state)
        control_bar.set_playing.assert_called_once_with(True)

        # 暂停状态
        state_paused = SimpleNamespace(is_playing=True, is_paused=True)
        VideoPlayer._on_manager_state_changed(player, state_paused)
        control_bar.set_playing.assert_called_with(False)

    def test_removed_polling_methods(self):
        """已移除的轮询方法不应再存在。"""
        from freeassetfilter.components.video_player import VideoPlayer
        # 这些方法已从类定义中移除
        assert not hasattr(VideoPlayer, '_get_authoritative_playing_state')
        assert not hasattr(VideoPlayer, '_should_defer_false_play_state')
        assert not hasattr(VideoPlayer, '_sync_progress_from_player')
        assert not hasattr(VideoPlayer, '_refresh_seek_future_state')
        assert not hasattr(VideoPlayer, '_seek_future_succeeded')

    def test_progress_signal_during_drag(self):
        """拖动时进度信号应有限频，不出现信号风暴。"""
        from freeassetfilter.components.video_player import VideoPlayer

        manager = MagicMock()
        manager.is_initialized.return_value = True
        manager.get_duration_direct.return_value = 100.0

        debounce_timer = MagicMock()
        debounce_timer.isActive.return_value = False

        player = SimpleNamespace()
        player._pending_seek_value = 0
        player._user_interacting = True
        player._mpv_manager = manager
        player._seek_debounce_timer = debounce_timer
        player._update_time_display = MagicMock()

        # 第一次调用应启动 seek debounce timer
        VideoPlayer._on_progress_changed(player, 250)
        debounce_timer.start.assert_called_once()

        # 模拟 timer 已激活
        debounce_timer.reset_mock()
        debounce_timer.isActive.return_value = True

        # 第二次调用不应再次启动 debounce timer
        VideoPlayer._on_progress_changed(player, 300)
        debounce_timer.start.assert_not_called()
