# -*- coding: utf-8 -*-
"""本地无边框基类（``ui.frameless_window.FramelessMainWindow``）的单元测试。

背景：项目自研无边框基类替代外部依赖 PySideSix-Frameless-Window，底层为
Qt 6.10+ 原生 ``Qt.ExpandedClientAreaHint`` 方案（经 _frameless_modern_demo.py
多模式人工验证）。

本测试验证不依赖真实显示的纯逻辑契约：

* 窗口标志包含 ``Qt.Window | Qt.ExpandedClientAreaHint | Qt.NoTitleBarBackgroundHint``；
* 显式关闭 ``WA_ContentsMarginsRespectsSafeArea``，消除 ExpandedClientAreaHint
  的内容下推（safeAreaMargins 21px 问题）；
* ``_hide_qt_titlebar`` 在非 Windows / 无 HWND 时安全跳过；在 Windows 且 HWND
  有效时调用 ``SetParent(HWND_MESSAGE=(HWND)-3)+SW_HIDE`` 隐藏 Qt 的
  ``_q_titlebar`` 系统标题栏子窗口；
* ``_calc_client_rect_wparam0`` 纯函数：按 Qt 的数学给出扩展后的客户区
  （非最大化顶边不缩、其余三边内缩；最大化四边都缩），用于接管
  ``WM_NCCALCSIZE(wParam==FALSE)``，避免系统按标准窗口画出原生标题栏；
* ``reapply_native_window_effects`` 会调用 ``SetWindowPos(SWP_FRAMECHANGED)``
  强制重算帧；
* ``_hit_test_code`` 纯函数：边缘缩放带返回原生 HT* 缩放码，其余返回 HTCLIENT
  （系统按钮命中失效），最大化时边缘带归零。

运行：
    python -m pytest tests/unit/ui/test_frameless_window.py -v
"""

import ctypes
import sys
from ctypes import wintypes

import pytest
from PySide6.QtCore import Qt

import freeassetfilter.ui.frameless_window as fw
from freeassetfilter.ui.frameless_window import (
    _EDGE_BORDER,
    _HTBOTTOM,
    _HTBOTTOMLEFT,
    _HTBOTTOMRIGHT,
    _HTCLIENT,
    _HTLEFT,
    _HTRIGHT,
    _HTTOP,
    _HTTOPLEFT,
    _HTTOPRIGHT,
    _SWP_FRAME_RECALC,
    FramelessMainWindow,
    _calc_client_rect_wparam0,
    _hit_test_code,
    _parse_version,
    frameless_runtime_status,
)

# 固定窗口矩形（与测试坐标一致）
_RECT = dict(left=100, top=100, right=700, bottom=500)
_EDGE = 8


class _FakeUser32:
    """记录调用的假 user32（模拟 FindWindowExW / SetParent / ShowWindow 等）。"""

    def __init__(self):
        self.find_called = False
        self.setparent_args = None
        self.showwindow_args = None
        self.setwindowpos_args = None
        self.is_zoomed = False
        self._hwnd = 0

    def FindWindowExW(self, parent, child, class_name, window_name):
        self.find_called = True
        return self._hwnd

    def SetParent(self, hwnd, parent):
        self.setparent_args = (hwnd, parent)
        return 0

    def ShowWindow(self, hwnd, cmd):
        self.showwindow_args = (hwnd, cmd)

    def IsZoomed(self, hwnd):
        return self.is_zoomed

    def GetWindowRect(self, hwnd, rect_ptr):
        return 1

    def SetWindowPos(self, hwnd, after, x, y, cx, cy, flags):
        self.setwindowpos_args = (hwnd, after, x, y, cx, cy, flags)
        return 1


class _Msg:
    """最小 MSG 替身（仅供 nativeEvent 相关逻辑读取 message/wParam/lParam）。"""

    def __init__(self, message: int, w_param: int = 0, l_param: int = 0) -> None:
        self.message = message
        self.wParam = w_param
        self.lParam = l_param


@pytest.fixture
def frameless_win(qapp):
    """构造一个基类实例（qapp 由 conftest 提供）。"""
    win = FramelessMainWindow()
    yield win
    win.close()


@pytest.fixture
def fake_user32(monkeypatch):
    """把模块级 user32 缓存替换为假实现（并保证测试后复原）。"""
    fake = _FakeUser32()
    monkeypatch.setattr(fw, "_user32", fake)
    return fake


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
    monkeypatch.setattr(fw, "_user32", None)
    frameless_win._hide_qt_titlebar()  # 不抛异常即可


def test_hide_titlebar_noop_when_no_hwnd(frameless_win, fake_user32, monkeypatch) -> None:
    """HWND 为 0（winId 不可用）时安全跳过。"""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(frameless_win, "winId", lambda: 0)
    frameless_win._hide_qt_titlebar()
    assert not fake_user32.find_called


def test_hide_titlebar_calls_setparent_and_hide(
    frameless_win, fake_user32, monkeypatch
) -> None:
    """Windows 下找到 _q_titlebar 后调用 SetParent(HWND_MESSAGE) + SW_HIDE。"""
    monkeypatch.setattr(sys, "platform", "win32")
    fake_user32._hwnd = 0x1234
    monkeypatch.setattr(frameless_win, "winId", lambda: 0xABCD)
    frameless_win._hide_qt_titlebar()
    assert fake_user32.find_called
    setparent_hwnd, setparent_parent = fake_user32.setparent_args
    assert int(setparent_hwnd) == 0x1234
    # HWND_MESSAGE 必须是 (HWND)-3；0xFFFFFFFF 是无效句柄，SetParent 会以
    # ERROR_INVALID_WINDOW_HANDLE(1400) 失败（本次修复的缺陷之一）。
    assert ctypes.c_ssize_t(setparent_parent.value).value == -3
    show_hwnd, show_cmd = fake_user32.showwindow_args
    assert int(show_hwnd) == 0x1234
    assert show_cmd == 0  # SW_HIDE


def test_hide_titlebar_swallows_exception(frameless_win, monkeypatch) -> None:
    """user32 调用异常时静默吞掉，不影响窗口使用。"""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(frameless_win, "winId", lambda: 0xABCD)

    class _Boom:
        def FindWindowExW(self, *a, **k):
            raise OSError("boom")

    monkeypatch.setattr(fw, "_user32", _Boom())
    frameless_win._hide_qt_titlebar()  # 不抛异常即可


# ---------------------------------------------------------------------------
# reapply_native_window_effects：隐藏标题栏 + 强制重算帧
# ---------------------------------------------------------------------------


def test_reapply_hides_titlebar_and_refreshes_frame(
    frameless_win, fake_user32, monkeypatch
) -> None:
    """reapply 必须既隐藏 _q_titlebar，又调用 SetWindowPos(SWP_FRAMECHANGED)。

    后者是修复「快速拖拽缩放时右上角闪出原生系统按钮」的关键：窗口创建 /
    HWND 重建时的 WM_NCCALCSIZE(wParam=FALSE) 若未被接管，系统会算出完整
    标题栏；带 SWP_FRAMECHANGED 的 SetWindowPos 会再触发一次
    WM_NCCALCSIZE(wParam=TRUE)，让 Qt 重新扩展客户区。
    """
    monkeypatch.setattr(sys, "platform", "win32")
    fake_user32._hwnd = 0x1234
    monkeypatch.setattr(frameless_win, "winId", lambda: 0xABCD)

    frameless_win.reapply_native_window_effects()

    assert fake_user32.find_called  # 隐藏了 Qt 标题栏
    assert fake_user32.setwindowpos_args is not None
    flags = fake_user32.setwindowpos_args[6]
    assert flags == _SWP_FRAME_RECALC
    assert flags & 0x0020  # SWP_FRAMECHANGED
    assert flags & 0x0002  # SWP_NOMOVE
    assert flags & 0x0001  # SWP_NOSIZE
    assert flags & 0x0004  # SWP_NOZORDER
    assert flags & 0x0010  # SWP_NOACTIVATE


# ---------------------------------------------------------------------------
# _calc_client_rect_wparam0 纯函数：按 Qt 数学扩展客户区
# ---------------------------------------------------------------------------


def test_calc_client_rect_non_maximized_top_not_inset() -> None:
    """非最大化：左/右/下内缩 8，顶边不缩（内容可画到原标题栏区）。"""
    assert _calc_client_rect_wparam0(100, 100, 700, 500, _EDGE, False) == (
        108, 100, 692, 492,
    )


def test_calc_client_rect_maximized_all_sides_inset() -> None:
    """最大化：四边都内缩 8，避免内容被边框裁掉。"""
    assert _calc_client_rect_wparam0(100, 100, 700, 500, _EDGE, True) == (
        108, 108, 692, 492,
    )


def test_calc_client_rect_zero_border_is_noop() -> None:
    """border<=0 时原样返回。"""
    assert _calc_client_rect_wparam0(100, 100, 700, 500, 0, False) == (
        100, 100, 700, 500,
    )


def test_apply_client_rect_wparam0_writes_rect(
    frameless_win, fake_user32, monkeypatch
) -> None:
    """_apply_client_rect_wparam0 就地改写 lParam 指向的 RECT。"""
    rect = wintypes.RECT(100, 100, 700, 500)
    msg = _Msg(0x0083, w_param=0, l_param=ctypes.addressof(rect))
    monkeypatch.setattr(frameless_win, "winId", lambda: 0xABCD)
    fake_user32.is_zoomed = False

    assert frameless_win._apply_client_rect_wparam0(msg) is True
    assert (rect.left, rect.top, rect.right, rect.bottom) == (108, 100, 692, 492)


def test_apply_client_rect_wparam0_maximized_top_inset(
    frameless_win, fake_user32, monkeypatch
) -> None:
    """最大化时顶边一并内缩。"""
    rect = wintypes.RECT(100, 100, 700, 500)
    msg = _Msg(0x0083, w_param=0, l_param=ctypes.addressof(rect))
    monkeypatch.setattr(frameless_win, "winId", lambda: 0xABCD)
    fake_user32.is_zoomed = True

    assert frameless_win._apply_client_rect_wparam0(msg) is True
    assert (rect.left, rect.top, rect.right, rect.bottom) == (108, 108, 692, 492)


# ---------------------------------------------------------------------------
# Qt 版本检测
# ---------------------------------------------------------------------------


def test_parse_version() -> None:
    """版本串宽松解析。"""
    assert _parse_version("6.10.3") == (6, 10, 3)
    assert _parse_version("6.10.0") == (6, 10, 0)
    assert _parse_version("6.11.1") == (6, 11, 1)
    assert _parse_version("") == ()


def test_runtime_status_supports_current_qt() -> None:
    """当前测试环境（Qt>=6.10）应判定为受支持；旧 Qt（无该标志）应判定为退化。"""
    supported, detail = frameless_runtime_status()
    assert detail
    if hasattr(Qt, "ExpandedClientAreaHint"):
        # 测试机的 Qt/PySide6 满足要求
        assert supported is True
    else:
        assert supported is False


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
