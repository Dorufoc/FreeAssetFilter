# -*- coding: utf-8 -*-
"""长按临时倍速状态机（``_TempSpeed``）单元测试。

覆盖用户诉求：长按倍速期间提示常显不自动隐藏，松手切回原倍速后再自动隐藏。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/layout/test_video_speed_shortcut.py -v
"""

from __future__ import annotations

from typing import Any, List

import pytest

pytestmark = pytest.mark.unit


class _StubPlayer:
    """``_TempSpeed`` 的鸭子类型桩：记录调用序列并维护倍速。"""

    def __init__(self, speed: float = 1.0) -> None:
        self.speed = float(speed)
        self.calls: List[Any] = []

    @property
    def current_speed(self) -> float:
        return self.speed

    def set_speed(self, speed: float) -> None:
        self.speed = float(speed)
        self.calls.append(("set_speed", float(speed)))

    def show_speed_osd_sticky(self, speed: float) -> None:
        self.calls.append(("sticky", float(speed)))

    def hide_speed_osd(self) -> None:
        self.calls.append(("hide",))

    def show_speed_osd(self, speed: float) -> None:
        self.calls.append(("osd", float(speed)))


def _temp_speed_cls():
    """函数内导入（沿 ``test_component_keys`` 模式，避免会话级 Qt 依赖）。"""
    from sopeek.ui.layout.preview.video_player_layout import _TempSpeed

    return _TempSpeed


def test_press_switches_speed_and_shows_sticky() -> None:
    """按下：记录原倍速、立即切速、常显提示（不自动隐藏）。"""
    player = _StubPlayer(1.0)
    state = _temp_speed_cls()(player)

    state.press(2.0)

    assert player.speed == 2.0
    assert player.calls == [("set_speed", 2.0), ("sticky", 2.0)]


def test_press_twice_keeps_original_speed() -> None:
    """autoRepeat 重复按下不得把原倍速覆盖成临时倍速。"""
    player = _StubPlayer(1.0)
    state = _temp_speed_cls()(player)

    state.press(2.0)
    state.press(2.0)

    state.release(long_pressed=True)
    assert player.speed == 1.0


def test_release_after_long_press_restores_and_hides_sticky() -> None:
    """长按松手：先收常显，再恢复原倍速（由 ``set_speed`` 出普通提示）。"""
    player = _StubPlayer(1.5)
    state = _temp_speed_cls()(player)

    state.press(3.0)
    state.release(long_pressed=True)

    assert player.speed == 1.5
    assert player.calls == [
        ("set_speed", 3.0),
        ("sticky", 3.0),
        ("hide",),
        ("set_speed", 1.5),
    ]


def test_release_after_short_press_keeps_new_speed() -> None:
    """短按松手：保持新倍速，并给一次普通 2 秒提示。"""
    player = _StubPlayer(1.0)
    state = _temp_speed_cls()(player)

    state.press(2.0)
    state.release(long_pressed=False)

    assert player.speed == 2.0
    assert player.calls[-2:] == [("hide",), ("osd", 2.0)]


def test_release_without_press_is_noop() -> None:
    """未按下就收到松开（迟到事件）时不得回滚或出提示。"""
    player = _StubPlayer(1.0)
    state = _temp_speed_cls()(player)

    state.release(long_pressed=True)

    assert player.calls == []
    assert player.speed == 1.0


def test_cancel_discards_late_release() -> None:
    """预览销毁时 ``cancel``：不改倍速、不出 OSD，迟到松开同样空操作。"""
    player = _StubPlayer(1.0)
    state = _temp_speed_cls()(player)

    state.press(2.0)
    calls_before = list(player.calls)
    state.cancel()
    state.release(long_pressed=True)

    assert player.calls == calls_before
    assert player.speed == 2.0
