# -*- coding: utf-8 -*-
"""Windows 原生前台激活工具回归。

背景：从终端 / IDE 启动时，Windows 前台锁会拒绝直接
``SetForegroundWindow``；Qt 的 ``activateWindow()`` 只更新内部激活状态，
键盘事件仍发往启动器。``win32_foreground`` 通过临时
``AttachThreadInput`` 兜底，本文件锁定其调用顺序与失败降级契约。

验证：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/utils/test_win32_foreground.py -v
"""

from __future__ import annotations

from typing import Any, List, Tuple

import pytest

from sopeek.utils import win32_foreground as fg

pytestmark = pytest.mark.unit

_TARGET_HWND = 0x2222
_OTHER_HWND = 0x1111


class _FakeUser32:
    """记录前台切换调用顺序的最小 user32 替身。"""

    def __init__(
        self,
        *,
        foreground: int = _OTHER_HWND,
        foreground_tid: int = 200,
        set_ok: bool = True,
        attach_ok: bool = True,
        raise_on_set: bool = False,
        raise_on_detach: bool = False,
        require_attach: bool = False,
    ) -> None:
        self.foreground = foreground
        self.foreground_tid = foreground_tid
        self.set_ok = set_ok
        self.attach_ok = attach_ok
        self.raise_on_set = raise_on_set
        self.raise_on_detach = raise_on_detach
        #: True 模拟前台锁：未附加线程时直接 SetForegroundWindow 失败。
        self.require_attach = require_attach
        self.attached = False
        self.attach_calls: List[Tuple[int, int, bool]] = []
        self.set_calls: List[int] = []

    def GetForegroundWindow(self) -> int:
        return self.foreground

    def GetWindowThreadProcessId(self, hwnd: Any, _process_id: Any) -> int:
        return self.foreground_tid

    def AttachThreadInput(
        self, foreground_tid: int, current_tid: int, attach: bool
    ) -> bool:
        self.attach_calls.append((foreground_tid, current_tid, bool(attach)))
        if attach:
            self.attached = self.attach_ok
        else:
            self.attached = False
            if self.raise_on_detach:
                raise OSError("detach failed")
        return self.attach_ok

    def SetForegroundWindow(self, hwnd: int) -> bool:
        self.set_calls.append(int(hwnd))
        if self.raise_on_set and (not self.require_attach or self.attached):
            raise OSError("foreground denied")
        if self.require_attach and not self.attached:
            return False
        if self.set_ok:
            self.foreground = int(hwnd)
        return self.set_ok


class _FakeKernel32:
    """固定当前线程 ID 的 kernel32 替身。"""

    def __init__(self, current_tid: int = 100) -> None:
        self.current_tid = current_tid

    def GetCurrentThreadId(self) -> int:
        return self.current_tid


@pytest.fixture()
def fake_win32(monkeypatch: pytest.MonkeyPatch):
    """注入假 user32 / kernel32，绕过真实 DLL 加载。"""
    user32 = _FakeUser32()
    kernel32 = _FakeKernel32()
    monkeypatch.setattr(fg, "_IS_WINDOWS", True)
    monkeypatch.setattr(fg, "_user32", user32)
    monkeypatch.setattr(fg, "_kernel32", kernel32)
    monkeypatch.setattr(fg, "_bindings_ready", True)
    return user32, kernel32


def test_is_foreground_window_matches(fake_win32) -> None:
    """当前前台句柄与目标一致时返回 True。"""
    user32, _ = fake_win32
    user32.foreground = _TARGET_HWND

    assert fg.is_foreground_window(_TARGET_HWND) is True
    assert fg.is_foreground_window(_OTHER_HWND) is False


def test_force_returns_true_without_calls_when_already_foreground(fake_win32) -> None:
    """已经在前台：不附加线程、不重复调用 SetForegroundWindow。"""
    user32, _ = fake_win32
    user32.foreground = _TARGET_HWND

    assert fg.force_foreground_window(_TARGET_HWND) is True
    assert user32.attach_calls == []
    assert user32.set_calls == []


def test_force_direct_success_skips_attach(fake_win32) -> None:
    """直接切前台成功（正常双击启动）：不额外附加前台线程。"""
    user32, _ = fake_win32

    assert fg.force_foreground_window(_TARGET_HWND) is True
    assert user32.set_calls == [_TARGET_HWND]
    assert user32.attach_calls == []


def test_force_attaches_and_detaches_on_success(fake_win32) -> None:
    """直接切换被前台锁拒绝：附加线程后重试，成功后必须解除附加。"""
    user32, _ = fake_win32
    user32.require_attach = True

    assert fg.force_foreground_window(_TARGET_HWND) is True
    assert user32.set_calls == [_TARGET_HWND, _TARGET_HWND]
    assert user32.attach_calls == [
        (200, 100, True),
        (200, 100, False),
    ]
    assert user32.foreground == _TARGET_HWND


def test_force_skips_attach_when_same_thread(fake_win32) -> None:
    """前台窗口属于当前线程：直接切前台，不做无意义的附加。"""
    user32, _ = fake_win32
    user32.foreground_tid = 100

    assert fg.force_foreground_window(_TARGET_HWND) is True
    assert user32.attach_calls == []
    assert user32.set_calls == [_TARGET_HWND]


def test_force_returns_false_when_attach_fails_and_direct_blocked(
    fake_win32,
) -> None:
    """附加失败且直接切换也被拒绝：返回 False，不误报成功。"""
    user32, _ = fake_win32
    user32.require_attach = True
    user32.attach_ok = False

    assert fg.force_foreground_window(_TARGET_HWND) is False
    assert user32.attach_calls == [(200, 100, True)]
    assert user32.set_calls == [_TARGET_HWND, _TARGET_HWND]


def test_force_detaches_when_retry_raises(fake_win32) -> None:
    """附加后的重试抛异常时也必须解除附加，且不向上抛。"""
    user32, _ = fake_win32
    user32.require_attach = True
    user32.raise_on_set = True

    assert fg.force_foreground_window(_TARGET_HWND) is False
    assert user32.attach_calls == [
        (200, 100, True),
        (200, 100, False),
    ]


def test_force_returns_false_when_set_blocked(fake_win32) -> None:
    """系统拒绝前台切换时返回 False，调用方据此记录降级日志。"""
    user32, _ = fake_win32
    user32.require_attach = True
    user32.set_ok = False

    assert fg.force_foreground_window(_TARGET_HWND) is False


def test_force_ignores_detach_failure(fake_win32) -> None:
    """解除附加失败不得覆盖已经成功的激活结果。"""
    user32, _ = fake_win32
    user32.require_attach = True
    user32.raise_on_detach = True

    assert fg.force_foreground_window(_TARGET_HWND) is True
    assert user32.foreground == _TARGET_HWND


def test_force_and_query_are_safe_without_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非 Windows / DLL 不可用：查询返回 False，激活静默降级。"""
    monkeypatch.setattr(fg, "_IS_WINDOWS", False)
    monkeypatch.setattr(fg, "_user32", None)
    monkeypatch.setattr(fg, "_kernel32", None)
    monkeypatch.setattr(fg, "_bindings_ready", False)

    assert fg.is_foreground_window(_TARGET_HWND) is False
    assert fg.force_foreground_window(_TARGET_HWND) is False
