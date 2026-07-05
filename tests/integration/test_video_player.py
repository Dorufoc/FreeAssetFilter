#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频播放器集成测试
"""

import os
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt, QEventLoop, QTimer


class TestPlayerCreation:
    def test_video_player_initialization(self, video_player):
        assert video_player is not None
        assert video_player._playback_mode == "video"

    def test_video_player_audio_mode(self, qapp):
        from freeassetfilter.components.video_player import VideoPlayer
        player = VideoPlayer(playback_mode="audio")
        assert player._playback_mode == "audio"
        player.cleanup(async_mode=False)
        player.close()
        player.deleteLater()

    def test_video_player_has_control_bar(self, video_player):
        assert hasattr(video_player, '_control_bar')
        assert video_player._control_bar is not None

    def test_video_player_has_mpv_manager(self, video_player):
        assert hasattr(video_player, '_mpv_manager')
        assert video_player._mpv_manager is not None

    def test_video_player_has_video_surface(self, video_player):
        assert hasattr(video_player, '_video_surface')
        assert video_player._video_surface is not None

    def test_video_player_detached_window_initially_none(self, video_player):
        assert video_player._detached_window is None


class TestPlaybackControlFlow:
    def test_play_method_exists(self, video_player):
        assert hasattr(video_player, 'play')
        assert callable(video_player.play)

    def test_pause_method_exists(self, video_player):
        assert hasattr(video_player, 'pause')
        assert callable(video_player.pause)

    def test_stop_method_exists(self, video_player):
        assert hasattr(video_player, 'stop')
        assert callable(video_player.stop)

    def test_toggle_play_pause_exists(self, video_player):
        assert hasattr(video_player, 'toggle_play_pause')
        assert callable(video_player.toggle_play_pause)

    def test_seek_method_exists(self, video_player):
        assert hasattr(video_player, 'seek')
        assert callable(video_player.seek)

    def test_is_playing_initially_false(self, video_player):
        assert video_player.is_playing() == False

    def test_get_current_file_initially_empty(self, video_player):
        assert video_player.get_current_file() == ""


class TestVolumeControl:
    def test_set_volume_method_exists(self, video_player):
        assert hasattr(video_player, 'set_volume')
        assert callable(video_player.set_volume)

    def test_volume_up_method_exists(self, video_player):
        assert hasattr(video_player, 'volume_up')
        assert callable(video_player.volume_up)

    def test_volume_down_method_exists(self, video_player):
        assert hasattr(video_player, 'volume_down')
        assert callable(video_player.volume_down)

    def test_set_mute_method_exists(self, video_player):
        assert hasattr(video_player, 'set_mute')
        assert callable(video_player.set_mute)


class TestSpeedControl:
    def test_set_speed_method_exists(self, video_player):
        assert hasattr(video_player, 'set_speed')
        assert callable(video_player.set_speed)

    def test_get_position_initially_zero(self, video_player):
        assert video_player.get_position() == 0.0

    def test_get_duration_initially_zero(self, video_player):
        assert video_player.get_duration() == 0.0


class TestDetachedWindowBehavior:
    def test_detach_button_visible_when_enabled(self, qapp):
        from freeassetfilter.components.video_player import VideoPlayer
        player = VideoPlayer(show_detach_button=True)
        assert player._show_detach_button == True
        player.cleanup(async_mode=False)
        player.close()
        player.deleteLater()

    def test_detach_button_hidden_when_disabled(self, qapp):
        from freeassetfilter.components.video_player import VideoPlayer
        player = VideoPlayer(show_detach_button=False)
        assert player._show_detach_button == False
        player.cleanup(async_mode=False)
        player.close()
        player.deleteLater()

    def test_detach_to_window_method_exists(self, video_player):
        assert hasattr(video_player, '_detach_to_window')
        assert callable(video_player._detach_to_window)

    def test_reattach_to_parent_method_exists(self, video_player):
        assert hasattr(video_player, '_reattach_to_parent')
        assert callable(video_player._reattach_to_parent)

    def test_floating_mode_switch_exists(self, video_player):
        assert hasattr(video_player, '_switch_to_floating_mode')
        assert callable(video_player._switch_to_floating_mode)
        assert hasattr(video_player, '_switch_to_fixed_mode')
        assert callable(video_player._switch_to_fixed_mode)

    def test_save_playback_state(self, video_player):
        state = video_player._save_playback_state()
        assert isinstance(state, dict)
        assert 'position' in state
        assert 'volume' in state
        assert 'speed' in state
        assert 'playing' in state

    def test_load_media_method_exists(self, video_player):
        assert hasattr(video_player, 'load_media')
        assert callable(video_player.load_media)

    def test_load_file_method_exists(self, video_player):
        assert hasattr(video_player, 'load_file')
        assert callable(video_player.load_file)

    def test_set_loop_mode_method_exists(self, video_player):
        assert hasattr(video_player, 'set_loop_mode')
        assert callable(video_player.set_loop_mode)

    def test_seek_forward_method_exists(self, video_player):
        assert hasattr(video_player, 'seek_forward')
        assert callable(video_player.seek_forward)

    def test_seek_backward_method_exists(self, video_player):
        assert hasattr(video_player, 'seek_backward')
        assert callable(video_player.seek_backward)
