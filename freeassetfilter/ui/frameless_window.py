#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地无边框窗口基类（替代外部依赖 PySideSix-Frameless-Window / qframelesswindow）

基于 Qt 6.10+ 原生方案（经 _frameless_modern_demo.py M6 组合人工验证）：

    Qt.Window | Qt.ExpandedClientAreaHint | Qt.NoTitleBarBackgroundHint

适用版本：``PySide6>=6.10.0``。这两个标志虽是 Qt 6.9 引入，但 Qt 6.9 的
``fixTopLevelWindowFlags`` 用 ``switch (flags)`` 精确匹配整个 flags，带上
``ExpandedClientAreaHint|NoTitleBarBackgroundHint`` 后不再命中裸
``Qt::Window``，不会自动补全 title hints → ``WS_CAPTION`` 等样式位全缺 →
最大化动画消失 / Win7 边框；Qt 6.10 加了 ``clientAreaHints`` 排除逻辑
（``switch (flags & ~clientAreaHints)``）才修复（详见 AGENTS.md）。

设计要点（与 win32 原生能力的关系）：
1. 窗口标志
   - ``Qt.Window`` 触发 Qt 在 Windows 平台自动补全
     ``WindowTitleHint|WindowSystemMenuHint|WindowMinimizeButtonHint|
     WindowMaximizeButtonHint|WindowCloseButtonHint``（见 qtbase
     qwindowswindow.cpp ``fixTopLevelWindowFlags``），原生 ``WS_CAPTION|
     WS_SYSMENU|WS_THICKFRAME|WS_MINIMIZEBOX|WS_MAXIMIZEBOX`` 样式位全部
     保留 → 最大化/最小化动画、Aero Snap 贴靠、八向原生缩放俱在。
   - ``Qt.ExpandedClientAreaHint`` 让 WM_NCCALCSIZE 返回 0 把客户区扩展到
     整个窗口（非客户区仅剩 ~8px 缩放边框），内容可绘制到原标题栏区域；
     同时 Qt 自动 ``DwmExtendFrameIntoClientArea(-1)`` 保留圆角与阴影。
   - ``Qt.NoTitleBarBackgroundHint`` 让 Qt 的标题栏子窗口不画背景。
2. 隐藏 Qt 标题栏子窗口
   Qt 6.9+ 为 ExpandedClientAreaHint 窗口创建独立子窗口 ``_q_titlebar``
   （WS_EX_LAYERED|WS_EX_TRANSPARENT|WS_EX_NOACTIVATE）用于绘制系统
   标题文本与最小化/最大化/关闭按钮。本项目标题栏完全自绘，故按 Qt 官方
   隐藏逻辑（``SetParent(HWND_MESSAGE) + SW_HIDE``）将其撤下，系统按钮
   图形与命中一并消失。
3. safeArea 下推消除
   ExpandedClientAreaHint 会让平台层返回 ``safeAreaMargins=(0, 标题栏高,
   0, 0)``，且顶层窗口默认自动开启 ``WA_ContentsMarginsRespectsSafeArea``，
   导致整个内容层被下推一个标题栏高度（实测 21px）。此处显式关闭该属性
   （显式 setAttribute 会标记 explicit，阻止 Qt 的默认自动开启）。
4. WM_NCHITTEST 拦截
   尽管样式位保留，仍拦截 WM_NCHITTEST：8px 边缘缩放带返回原生 HT* 缩放
   码，其余（含顶部标题栏区域）一律返回 HTCLIENT —— 系统按钮命中彻底失效，
   拖拽移动交给自绘标题栏的 ``windowHandle().startSystemMove()``（该路径
   仍走系统移动循环，Aero Snap 保留）。

使用：
    class MainWindow(_FramelessNativeEffectsMixin, FramelessMainWindow): ...
"""

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QMainWindow

# WM_NCHITTEST 命中码（仅本模块使用）
_HTCLIENT = 1
_HTTOP = 12
_HTTOPLEFT = 13
_HTTOPRIGHT = 14
_HTBOTTOM = 15
_HTBOTTOMLEFT = 16
_HTBOTTOMRIGHT = 17
_HTLEFT = 10
_HTRIGHT = 11

# 边缘缩放带宽度：与 WS_THICKFRAME 边框一致（DPI 无关，系统缩放由命中码驱动）
_EDGE_BORDER = 8


def _hit_test_code(x: int, y: int, left: int, top: int, right: int, bottom: int,
                   border: int) -> int:
    """计算 WM_NCHITTEST 命中码（纯函数，便于单测）。

    窗口矩形为 (left, top, right, bottom)，边缘缩放带宽度为 ``border``：
    - 落入边缘带的坐标返回对应 HT* 缩放码（HTTOPLEFT/HTTOP/HTLEFT...）；
    - 其余一律返回 HTCLIENT（含顶部标题栏区域，系统按钮命中失效）。
    """
    lx = x - left < border
    rx = right - x < border
    ty = y - top < border
    by = bottom - y < border
    if lx and ty:
        return _HTTOPLEFT
    if rx and by:
        return _HTBOTTOMRIGHT
    if rx and ty:
        return _HTTOPRIGHT
    if lx and by:
        return _HTBOTTOMLEFT
    if ty:
        return _HTTOP
    if by:
        return _HTBOTTOM
    if lx:
        return _HTLEFT
    if rx:
        return _HTRIGHT
    return _HTCLIENT


class FramelessMainWindow(QMainWindow):
    """基于 Qt 6.9+ 原生 ExpandedClientAreaHint 方案的无边框主窗口基类。

    替代 qframelesswindow.FramelessMainWindow：不依赖外部无边框库，完整
    保留原生窗口能力（动画 / Aero Snap / 缩放），并彻底移除系统按钮的
    图形与命中。自绘标题栏由子类负责（拖拽经 startSystemMove）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        flags = Qt.Window
        if hasattr(Qt, "ExpandedClientAreaHint"):
            flags |= Qt.ExpandedClientAreaHint
        if hasattr(Qt, "NoTitleBarBackgroundHint"):
            flags |= Qt.NoTitleBarBackgroundHint
        self.setWindowFlags(flags)

        # 关闭 safeArea 内容下推（ExpandedClientAreaHint 默认会让平台返回
        # safeAreaMargins=(0, 标题栏高, 0, 0)，顶层窗口默认自动开启
        # WA_ContentsMarginsRespectsSafeArea 把内容推下一个标题栏高度）。
        # 显式 setAttribute 会标记 explicitContentsMarginsRespectsSafeArea，
        # 阻止 Qt 的默认自动开启（qtbase qwidget.cpp:1209-1220 / 11406-11410）。
        if hasattr(Qt.WidgetAttribute, "WA_ContentsMarginsRespectsSafeArea"):
            self.setAttribute(Qt.WidgetAttribute.WA_ContentsMarginsRespectsSafeArea, False)

        # 若构造阶段 HWND 已存在（winId 被提前访问），立即隐藏 Qt 标题栏
        self._hide_qt_titlebar()

    # ---- 事件钩子 ----
    def showEvent(self, event) -> None:
        """窗口显示时确保 Qt 标题栏子窗口被隐藏。"""
        super().showEvent(event)
        self._hide_qt_titlebar()

    def event(self, e: QEvent) -> bool:
        """监听 WinIdChange：HWND 重建（GPU 表面附着等）后新 _q_titlebar
        子窗口会重新出现，需再次隐藏。"""
        if e.type() == QEvent.Type.WinIdChange:
            self._hide_qt_titlebar()
        return super().event(e)

    def nativeEvent(self, eventType: bytes, message: object) -> tuple:
        """拦截 WM_NCHITTEST：边缘缩放带保留原生缩放码，其余一律 HTCLIENT。"""
        if sys.platform != "win32":
            return super().nativeEvent(eventType, message)
        if eventType != b"windows_generic_MSG":
            return super().nativeEvent(eventType, message)
        try:
            msg = wintypes.MSG.from_address(int(message))
        except Exception:
            return super().nativeEvent(eventType, message)
        if msg.message != 0x0084:  # WM_NCHITTEST
            return super().nativeEvent(eventType, message)

        lp = int(msg.lParam)
        x = ctypes.c_short(lp & 0xFFFF).value
        y = ctypes.c_short((lp >> 16) & 0xFFFF).value

        rect = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(
            ctypes.c_void_p(int(self.winId())), ctypes.byref(rect)
        )
        # 最大化/全屏时无缩放边框，边缘带归零
        border = 0 if self.isMaximized() or self.isFullScreen() else _EDGE_BORDER
        code = _hit_test_code(x, y, rect.left, rect.top, rect.right, rect.bottom, border)
        return True, code

    # ---- 原生辅助 ----
    def _hide_qt_titlebar(self) -> None:
        """隐藏 Qt 的 `_q_titlebar` 独立标题栏子窗口（Qt 6.9+ 内部实现）。

        对应 qtbase qwindowswindow.cpp：
          - 创建: CreateWindowEx(WS_EX_LAYERED|WS_EX_TRANSPARENT|
            WS_EX_NOACTIVATE, "_q_titlebar", ...)
          - 官方隐藏: SetParent(hwndTitlebar, HWND_MESSAGE) + ShowWindow(SW_HIDE)
        """
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())
        except (TypeError, RuntimeError, ValueError):
            return
        if not hwnd:
            return
        try:
            user32 = ctypes.windll.user32
            tb = user32.FindWindowExW(ctypes.c_void_p(hwnd), None, "_q_titlebar", None)
            if not tb:
                return
            user32.SetParent(ctypes.c_void_p(int(tb)), ctypes.c_void_p(0xFFFFFFFF))  # HWND_MESSAGE
            user32.ShowWindow(ctypes.c_void_p(int(tb)), 0)  # SW_HIDE
        except Exception:
            # 隐藏失败不影响窗口正常使用（仅系统按钮绘制层残留）
            pass

    def reapply_native_window_effects(self) -> None:
        """HWND 重建后重新应用原生窗口效果（与旧 Mixin 同名语义）。

        旧实现依赖 qframelesswindow.windowEffect 重新设置 WS_THICKFRAME /
        DWM 阴影——新方案下这些由 Qt 的 ExpandedClientAreaHint 在窗口创建
        时自动应用，此处只需确保 Qt 标题栏子窗口保持隐藏。
        """
        self._hide_qt_titlebar()
