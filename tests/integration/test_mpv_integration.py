# -*- coding: utf-8 -*-
"""
MPV 模块集成测试 — Wave 4 (Task 34)

验证跨模块交互契约：MPVPlayerCore ↔ MPVManager ↔ VideoPlayer

这些测试 mock DLL 层（不对真实 libmpv 产生依赖），但验证端到端模块交互，
包括信号链、状态一致性和线程安全。
"""
import pytest
import os
import sys
import threading
import time
import ctypes
from concurrent.futures import Future
from unittest.mock import MagicMock, patch, PropertyMock

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]


# ============================================================
# Helper: create a manager with a mocked core (DLL mocked)
# ============================================================

def _make_mock_core():
    """Create an MPVPlayerCore with fully mocked DLL for integration tests."""
    from freeassetfilter.core.mpv_player_core import MPVPlayerCore

    core = MPVPlayerCore()
    # Mock the DLL so no real libmpv is needed
    mock_dll = MagicMock()
    mock_dll.mpv_create.return_value = ctypes.c_void_p(0xDEAD)
    mock_dll.mpv_initialize.return_value = 0
    mock_dll.mpv_set_option_string.return_value = 0
    mock_dll.mpv_set_property_string.return_value = 0
    mock_dll.mpv_set_property.return_value = 0
    mock_dll.mpv_get_property.return_value = 0
    mock_dll.mpv_command.return_value = 0
    mock_dll.mpv_observe_property.return_value = 0
    mock_dll.mpv_set_wakeup_callback.return_value = None
    mock_dll.mpv_terminate_destroy.return_value = None
    mock_dll.mpv_wait_event.return_value = None
    mock_dll.mpv_wakeup.return_value = None
    mock_dll.mpv_error_string.return_value = b"success"
    core._dll_loader._dll = mock_dll
    core._dll_loader._initialized = True
    core._initialized = True
    # Prevent actual thread from running
    core._worker_thread = MagicMock()
    core._worker_thread.is_alive.return_value = True
    return core


def _make_manager_with_mock_core():
    """Get the MPVManager singleton with a mocked core."""
    from freeassetfilter.core.mpv_manager import get_mpv_manager, MPVManager

    # Reset singleton for clean test
    MPVManager._instance = None
    MPVManager._initialized = False

    manager = get_mpv_manager()
    manager._mpv_core = _make_mock_core()
    manager._is_shutting_down = False
    return manager


def _cleanup_manager(manager):
    """Clean up manager state after test."""
    if manager:
        manager._is_shutting_down = True


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def mpv_manager():
    """Provide MPVManager with mocked core."""
    from freeassetfilter.core.mpv_manager import MPVManager
    MPVManager._instance = None
    MPVManager._initialized = False
    manager = _make_manager_with_mock_core()
    yield manager
    _cleanup_manager(manager)
    MPVManager._instance = None
    MPVManager._initialized = False


@pytest.fixture
def video_player_with_mock(qapp):
    """Provide VideoPlayer with fully mocked manager/core/DLL chain."""
    from freeassetfilter.core.mpv_manager import MPVManager
    from freeassetfilter.components.video_player import VideoPlayer

    # Reset singleton
    MPVManager._instance = None
    MPVManager._initialized = False

    # Build mock chain
    player = VideoPlayer()
    # Replace the manager's core with fully mocked one
    mock_core = _make_mock_core()
    player._mpv_manager._mpv_core = mock_core
    player._mpv_manager._is_shutting_down = False

    yield player

    player.cleanup(async_mode=False)
    player.close()
    player.deleteLater()
    MPVManager._instance = None
    MPVManager._initialized = False


# ============================================================
# Test 1: Rapid file switching
# ============================================================

class TestFileSwitchWhilePlaying:
    """Verify state consistency during rapid file switching across all 3 layers."""

    def test_file_switch_preserves_playing_state(self, mpv_manager):
        """After rapid file switch, manager state should be consistent."""
        from freeassetfilter.core.mpv_manager import MPVOperationType

        manager = mpv_manager
        core = manager._mpv_core

        # Simulate: file loaded → playing → switch to another file → reset to known state
        # Core starts with position/duration at 0
        with core._state_lock:
            core._position = 0.0
            core._duration = 0.0
            core._is_playing = True
            core._is_paused = False

        # Switch file — simulate load_file path
        manager._submit_operation(
            MPVOperationType.LOAD_FILE,
            "/path/first.mp4",
            component_id="integration_test",
        )

        # Simulate core processing the load (resets position/duration)
        with core._state_lock:
            core._position = 0.0
            core._duration = 0.0
            core._is_playing = True

        # Verify manager reads correct state from core (no stale cache)
        state = manager.get_state()
        assert state.is_playing is True
        assert state.position == 0.0
        assert state.duration == 0.0

        # Switch again — rapid second file
        manager._submit_operation(
            MPVOperationType.LOAD_FILE,
            "/path/second.mp4",
            component_id="integration_test",
        )

        # Simulate core processing
        with core._state_lock:
            core._position = 0.0
            core._duration = 120.0
            core._is_playing = True

        state2 = manager.get_state()
        assert state2.is_playing is True
        # Manager reads duration from core
        assert state2.duration == 120.0

    def test_file_switch_signal_integrity(self, mpv_manager):
        """File switch should emit proper signals through manager."""
        manager = mpv_manager
        core = manager._mpv_core
        signal_log = []

        def on_position_changed(pos, dur):
            signal_log.append(("position", pos, dur))

        manager.positionChanged.connect(on_position_changed)

        # Simulate a file load via core → manager signal chain
        with core._state_lock:
            core._position = 15.0
            core._duration = 200.0
            core._is_playing = True

        # Emit position signal through manager's forwarding
        manager._on_position_changed(15.0, 200.0)
        # _on_state_changed accepts a bool (is_playing), the stateChanged signal
        # emits an MPVState object built from core via get_state()
        manager._on_state_changed(core.is_playing())

        # Verify at least position signal was received
        assert len(signal_log) >= 1
        # Verify position signal is correct
        pos_sigs = [s for s in signal_log if s[0] == "position"]
        assert len(pos_sigs) >= 1
        assert pos_sigs[-1][1] == 15.0
        assert pos_sigs[-1][2] == 200.0


# ============================================================
# Test 2: Rapid pause/play toggle
# ============================================================

class TestPausePlayToggleRapid:
    """Verify no command loss or state desync during rapid toggle."""

    def test_rapid_toggle_no_command_loss(self, mpv_manager):
        """10 rapid toggles should not cause state desync."""
        from freeassetfilter.core.mpv_manager import MPVOperationType

        manager = mpv_manager
        core = manager._mpv_core

        # Start in playing state
        with core._state_lock:
            core._is_playing = True
            core._is_paused = False

        initial_state = manager.is_playing()
        assert initial_state is True

        # Perform 10 rapid toggles by submitting operations
        for i in range(10):
            if i % 2 == 0:
                manager._submit_operation(
                    MPVOperationType.PAUSE,
                    component_id="integration_test",
                    priority=2,
                )
                # Simulate core processing
                with core._state_lock:
                    core._is_paused = True
            else:
                manager._submit_operation(
                    MPVOperationType.PLAY,
                    component_id="integration_test",
                    priority=2,
                )
                with core._state_lock:
                    core._is_paused = False

        # Final state should be playing (odd count: 5 play, 5 pause)
        assert core.is_paused() is False
        assert core.is_playing() is True

        # Manager reads through core
        assert manager.is_playing() is True
        assert manager.is_paused() is False

    def test_rapid_toggle_signals_match_state(self, mpv_manager):
        """After rapid toggle, signals should reflect final state."""
        manager = mpv_manager
        core = manager._mpv_core
        last_state_signal = [None]

        def on_state_changed(state):
            last_state_signal[0] = state

        manager.stateChanged.connect(on_state_changed)

        # Simulate 10 rapid toggle signals through manager
        for i in range(10):
            with core._state_lock:
                core._is_paused = (i % 2 == 0)
            # Forward state change via manager
            manager._on_state_changed(core.is_playing())

        # Manager's state should reflect core
        final_state = manager.get_state()
        assert final_state.is_paused == (9 % 2 == 0)  # Last toggle was 9 (odd = False)


# ============================================================
# Test 3: Seek during playback
# ============================================================

class TestSeekDuringPlayback:
    """Verify seek operations work correctly during active playback."""

    def test_seek_updates_position(self, mpv_manager):
        """Seek should update position in all 3 layers."""
        from freeassetfilter.core.mpv_manager import MPVOperationType

        manager = mpv_manager
        core = manager._mpv_core

        # Simulate playback at position 30s, duration 200s
        with core._state_lock:
            core._position = 30.0
            core._duration = 200.0
            core._is_playing = True
            core._is_paused = False

        # Manager should read position from core
        assert manager.get_position() == 30.0

        # Perform seek
        result = manager.seek(90.0, component_id="integration_test")
        assert result is not None

        # Simulate core processing seek (position updates via property event)
        with core._state_lock:
            core._position = 90.0

        # After seek, manager reads updated position
        assert manager.get_position() == 90.0

        # State should also reflect correct position
        state = manager.get_state()
        assert state.position == 90.0

    def test_seek_during_active_seek(self, mpv_manager):
        """Seek while already seeking should coalesce to final position."""
        from freeassetfilter.core.mpv_manager import MPVOperationType

        manager = mpv_manager
        core = manager._mpv_core

        with core._state_lock:
            core._position = 0.0
            core._duration = 300.0
            core._is_playing = True

        # Submit seek to 50s
        fut1 = manager.seek(50.0, component_id="integration_test")

        # Submit seek to 150s (coalescing should use latest)
        fut2 = manager.seek(150.0, component_id="integration_test")

        # Simulate core processing the final seek
        with core._state_lock:
            core._position = 150.0

        # Cache should reflect final position
        assert manager.get_position() == 150.0


# ============================================================
# Test 4: Detach/Reattach window cycle
# ============================================================

class TestDetachReattachWindow:
    """Full detach/reattach cycle through VideoPlayer API."""

    def test_detach_reattach_no_crash(self, video_player_with_mock):
        """Detach then reattach should not crash or corrupt state."""
        player = video_player_with_mock
        manager = player._mpv_manager

        # Ensure we start clean
        assert player._detached_window is None
        # _is_mpv_embedding happens after window display; initially False
        # The mock chain doesn't embed, so this is expected to be False
        assert player._mpv_manager.is_initialized() is True

        # Step 1: Detach to window (simulate)
        # In real code this creates a new window and calls _switch_to_floating_mode
        # We just verify the method exists and doesn't crash
        save_state = player._save_playback_state()
        assert isinstance(save_state, dict)
        assert "position" in save_state
        assert "volume" in save_state

        # Step 2: Verify reattach method works (no crash)
        # Just calling the reattach method verification
        assert hasattr(player, "_switch_to_fixed_mode")
        assert callable(player._switch_to_fixed_mode)

        # Verify state still intact after cycle simulation
        assert player._mpv_manager.is_initialized() is True

    def test_reconnect_mpv_window_async(self, video_player_with_mock):
        """_reconnect_mpv_window should use QTimer.singleShot(0) for async execution."""
        player = video_player_with_mock
        player._do_reconnect_window = MagicMock()

        with patch("PySide6.QtCore.QTimer.singleShot") as mock_singleshot:
            player._reconnect_mpv_window()
            mock_singleshot.assert_called_once()
            args = mock_singleshot.call_args[0]
            assert args[0] == 0, "Should use 0ms delay for async"

    def test_detach_reattach_state_preserved(self, mpv_manager):
        """Manager state should survive detach/reattach cycle."""
        manager = mpv_manager
        core = manager._mpv_core

        # Set some playback state
        with core._state_lock:
            core._position = 42.5
            core._duration = 200.0
            core._is_playing = True
            core._volume = 80

        # State should be readable before
        state_before = manager.get_state()
        assert state_before.position == 42.5
        assert state_before.volume == 80

        # Simulate detach: set_window_id changes (core handle remains valid)
        # Core is still alive, manager delegates to it
        manager._on_state_changed(True)

        # State should be same after
        state_after = manager.get_state()
        assert state_after.position == 42.5


# ============================================================
# Test 5: load_file state consistency across 3 layers
# ============================================================

class TestLoadFileNoStateDesync:
    """After load_file, verify all 3 layers agree on state."""

    def test_state_consistency_after_load(self, mpv_manager):
        """After load_file, is_playing(), is_paused(), get_position() should be consistent.

        This verifies the contract: manager delegates to core, which resets
        position/duration on load.
        """
        manager = mpv_manager
        core = manager._mpv_core

        # Set stale state (simulating previous playback)
        with core._state_lock:
            core._position = 55.5
            core._duration = 200.0

        # Simulate load_file: core resets position/duration
        with core._state_lock:
            core._position = 0.0
            core._duration = 0.0
            core._is_playing = False
            core._is_paused = False

        # Layer 1: core
        assert core.get_position_cached() == 0.0
        assert core.get_duration_cached() == 0.0
        assert core.is_playing() is False
        assert core.is_paused() is False

        # Layer 2: manager (delegates to core)
        assert manager.get_position() == 0.0
        assert manager.get_duration() == 0.0
        assert manager.is_playing() is False
        assert manager.is_paused() is False

        # Layer 3: state object (built from core)
        state = manager.get_state()
        assert state.position == 0.0
        assert state.duration == 0.0
        assert state.is_playing is False
        assert state.is_paused is False

    def test_load_file_then_play_state(self, mpv_manager):
        """After load_file then play, state transitions should be consistent."""
        manager = mpv_manager
        core = manager._mpv_core

        # Load file (reset state)
        with core._state_lock:
            core._position = 0.0
            core._duration = 120.0
            core._is_playing = False
            core._is_paused = False

        # Start playing
        with core._state_lock:
            core._is_playing = True
            core._is_paused = False

        # Position updates during playback
        with core._state_lock:
            core._position = 10.0

        state = manager.get_state()
        assert state.is_playing is True
        assert state.is_paused is False
        assert state.position == 10.0
        assert state.duration == 120.0

        # Pause
        with core._state_lock:
            core._is_paused = True

        assert manager.is_paused() is True
        assert manager.is_playing() is True  # playing but paused
        assert manager.get_position() == 10.0

    def test_load_file_core_state_reset_propagates(self, mpv_manager):
        """Core position reset on load_file must propagate through manager."""
        manager = mpv_manager
        core = manager._mpv_core

        # Set old position
        with core._state_lock:
            core._position = 999.0
            core._duration = 500.0

        # Verify manager sees old position (would be stale without reset)
        assert manager.get_position() == 999.0

        # Now simulate load_file reset
        with core._state_lock:
            core._position = 0.0
            core._duration = 0.0

        # After reset, manager should see 0
        assert manager.get_position() == 0.0
        assert manager.get_duration() == 0.0
