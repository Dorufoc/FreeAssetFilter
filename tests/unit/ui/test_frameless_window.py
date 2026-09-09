# -*- coding: utf-8 -*-
"""本地无边框基类（``ui.frameless_window.FramelessMainWindow``）的单元测试。

背景：项目自研无边框基类替代外部依赖 PySideSix-Frameless-Window，底层为
Qt 6.9+ 原生 ``Qt.ExpandedClientAreaHint`` 方案（经 _frameless_modern_demo.py
多模式人工验证）。

本测试验证不依赖真实显示的纯逻辑契约：

* 窗口标志包含 ``Qt.Window | Qt.ExpandedClientAreaHint | Qt.NoTitleBarBackgroundHint``；
* 显式关闭 ``WA_ContentsMarginsRespectsSafeArea``，消除 ExpandedClientAreaHint
  的内容下推（safeAreaMargins 21px 问题）；
* ``_hide_qt_titlebar`` 在非 Windows / 无 HWND 时安全跳过；在 Windows 且 HWND
  有效时调用 user32 的 ``SetParent(HWND_MESSAGE)+SW_HIDE`` 隐藏 Qt 的
  ``_q_titlebar`` 系统标题栏子窗口；
* ``_hit_test_code`` 纯函数：边缘缩放带返回原生 HT* 缩放码，其余返回 HTCLIENT
  （系统按钮命中失效），最大化时边缘带归零。

运行：
    python -m pytest tests/unit/ui/test_frameless_window.py -v
"""

import ctypes
import sys

import pytest
from PySide6.QtCore import Qt

from freeassetfilter.ui.frameless_window import (
    _HTBOTTOM,
    _HTBOTTOMLEFT,
    _HTBOTTOMRIGHT,
    _HTCLIENT,
    _HTLEFT,
    _HTRIGHT,
    _HTTOP,
    _HTTOPLEFT,
    _HTTOPRIGHT,
    FramelessMainWindow,
    _hit_test_code,
)

# 固定窗口矩形（与测试坐标一致）
_RECT = dict(left=100, top=100, right=700, bottom=500)
_EDGE = 8


class _FakeUser32:
    """记录调用的假 user32（模拟 FindWindowExW / SetParent / ShowWindow）。"""

    def __init__(self):
        self.find_called = False
        self.setparent_args = None
        self.showwindow_args = None
        self._hwnd = 0

    def FindWindowExW(self, parent, child, class_name, window_name):
        self.find_called = True
        return self._hwnd

    def SetParent(self, hwnd, parent):
        self.setparent_args = (hwnd, parent)

    def ShowWindow(self, hwnd, cmd):
        self.showwindow_args = (hwnd, cmd)


@pytest.fixture
def frameless_win(qapp):
    """构造一个基类实例（qapp 由 conftest 提供）。"""
    win = FramelessMainWindow()
    yield win
    win.close()


# ---------------------------------------------------------------------------
# 窗口标志契约
# ---------------------------------------------------------------------------


def test_window_flags_include_native_hints(frameless_win) -> None:
    """标志必须包含 Qt.Window + ExpandedClientAreaHint + NoTitleBarBackgroundHint。"""
    flags = frameless_win.windowFlags()
    assert flags & Qt.Window
    if hasattr(Qt, "ExpandedClientAreaHint"):
        assert flags & Qt.ExpandedClientAreaHint
    if hasattr(Qt, "NoTitleBarBackgroundHint"):
        assert flags & Qt.NoTitleBarBackgroundHint


def test_safe_area_respect_disabled(frameless_win) -> None:
    """显式关闭 WA_ContentsMarginsRespectsSafeArea，消除内容下推。"""
    if hasattr(Qt.WidgetAttribute, "WA_ContentsMarginsRespectsSafeArea"):
        assert not frameless_win.testAttribute(
            Qt.WidgetAttribute.WA_ContentsMarginsRespectsSafeArea
        )


# ---------------------------------------------------------------------------
# _hide_qt_titlebar 安全性与行为
# ---------------------------------------------------------------------------


def test_hide_titlebar_noop_on_non_windows(frameless_win, monkeypatch) -> None:
    """非 Windows 平台 _hide_qt_titlebar 安全跳过。"""
    monkeypatch.setattr(sys, "platform", "linux")
    frameless_win._hide_qt_titlebar()  # 不抛异常即可


def test_hide_titlebar_noop_when_no_hwnd(frameless_win, monkeypatch) -> None:
    """HWND 为 0（winId 不可用）时安全跳过。"""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(frameless_win, "winId", lambda: 0)
    frameless_win._hide_qt_titlebar()  # 不抛异常即可


def test_hide_titlebar_calls_setparent_and_hide(frameless_win, monkeypatch) -> None:
    """Windows 下找到 _q_titlebar 后调用 SetParent(HWND_MESSAGE) + SW_HIDE。"""
    monkeypatch.setattr(sys, "platform", "win32")
    fake = _FakeUser32()
    fake._hwnd = 0x1234
    monkeypatch.setattr(
        "freeassetfilter.ui.frameless_window.ctypes.windll.user32", fake
    )
    monkeypatch.setattr(frameless_win, "winId", lambda: 0xABCD)
    frameless_win._hide_qt_titlebar()
    assert fake.find_called
    # 基类用 c_void_p 包装句柄：断言底层值
    setparent_hwnd, setparent_parent = fake.setparent_args
    assert int(setparent_hwnd.value) == 0x1234
    assert int(setparent_parent.value) == 0xFFFFFFFF  # HWND_MESSAGE
    show_hwnd, show_cmd = fake.showwindow_args
    assert int(show_hwnd.value) == 0x1234
    assert show_cmd == 0  # SW_HIDE


def test_hide_titlebar_swallows_exception(frameless_win, monkeypatch) -> None:
    """user32 调用异常时静默吞掉，不影响窗口使用。"""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(frameless_win, "winId", lambda: 0xABCD)

    class _Boom:
        def FindWindowExW(self, *a, **k):
            raise OSError("boom")

    monkeypatch.setattr(
        "freeassetfilter.ui.frameless_window.ctypes.windll.user32", _Boom()
    )
    frameless_win._hide_qt_titlebar()  # 不抛异常即可


# ---------------------------------------------------------------------------
# _hit_test_code 纯函数：边缘缩放带 vs HTCLIENT
# ---------------------------------------------------------------------------


def test_hit_client_on_titlebar_area() -> None:
    """顶部标题栏区域（边缘带外）返回 HTCLIENT——系统按钮命中失效。"""
    # 距顶 16px > 8px 边缘带 → HTCLIENT
    code = _hit_test_code(x=400, y=116, border=_EDGE, **_RECT)
    assert code == _HTCLIENT


def test_hit_top_on_top_edge() -> None:
    """上边缘缩放带返回 HTTOP（原生缩放保留）。"""
    code = _hit_test_code(x=400, y=102, border=_EDGE, **_RECT)  # 距顶 2px
    assert code == _HTTOP


def test_hit_corners_and_sides() -> None:
    """四角与四边缩放带分别返回对应 HT* 码。"""
    assert _hit_test_code(x=102, y=102, border=_EDGE, **_RECT) == _HTTOPLEFT
    assert _hit_test_code(x=698, y=102, border=_EDGE, **_RECT) == _HTTOPRIGHT
    assert _hit_test_code(x=102, y=498, border=_EDGE, **_RECT) == _HTBOTTOMLEFT
    assert _hit_test_code(x=698, y=498, border=_EDGE, **_RECT) == _HTBOTTOMRIGHT
    assert _hit_test_code(x=400, y=498, border=_EDGE, **_RECT) == _HTBOTTOM
    assert _hit_test_code(x=102, y=300, border=_EDGE, **_RECT) == _HTLEFT
    assert _hit_test_code(x=698, y=300, border=_EDGE, **_RECT) == _HTRIGHT


def test_hit_zero_border_when_maximized() -> None:
    """最大化时边缘带归零（border=0），顶部一律 HTCLIENT。"""
    # 距顶 2px，但 border=0 → 无边缘带 → HTCLIENT
    code = _hit_test_code(x=400, y=102, border=0, **_RECT)
    assert code == _HTCLIENT
    # 中心区域始终 HTCLIENT
    assert _hit_test_code(x=400, y=300, border=_EDGE, **_RECT) == _HTCLIENT
