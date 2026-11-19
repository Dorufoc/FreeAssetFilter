#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows 原生前台窗口激活工具。

背景：从终端 / IDE 启动 GUI 程序时，启动器通常仍是 Windows 的前台进程。
Windows 的前台锁会拒绝新进程直接调用 ``SetForegroundWindow``；Qt 的
``activateWindow()`` / ``raise_()`` 在这种情况下只会更新 Qt 内部的激活
状态，``GetForegroundWindow()`` 仍指向启动器。键盘事件按原生前台窗口
路由，于是方向键等输入会发给启动器，主窗口里的控件收不到。

本模块提供最小化的原生兜底：先尝试直接切前台，失败后把当前线程临时
附加到前台窗口线程（``AttachThreadInput``），再调用
``SetForegroundWindow``，最后在 ``finally`` 中解除附加。

仅用于启动首帧后的**一次性**激活；不要在每次窗口激活 / 用户切窗时调用，
否则会变成主动抢焦点。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Any

#: 当前平台是否 Windows。模块级常量便于单测替换。
_IS_WINDOWS = sys.platform == "win32"

#: 惰性加载的 Win32 绑定（None 表示尚未加载或当前平台不可用）。
_user32: Any = None
_kernel32: Any = None
#: 是否已经尝试过加载绑定（失败后不反复加载）。
_bindings_ready = False


def _ensure_bindings() -> bool:
    """加载并声明本模块需要的 user32 / kernel32 原型（幂等）。

    Returns:
        bool: 绑定可用返回 True；非 Windows / DLL 加载失败返回 False。
    """
    global _user32, _kernel32, _bindings_ready
    if _user32 is not None and _kernel32 is not None:
        return True
    if _bindings_ready or not _IS_WINDOWS:
        return False
    _bindings_ready = True
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except OSError:  # pragma: no cover - 仅异常环境触发
        return False

    # 显式声明原型：默认 restype 是 32 位 c_long，64 位 HWND 会被截断。
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.BOOL,
    ]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    _user32 = user32
    _kernel32 = kernel32
    return True


def is_foreground_window(hwnd: int) -> bool:
    """判断指定窗口是否已是 Windows 原生前台窗口。

    Args:
        hwnd: 顶层窗口句柄（``QWidget.winId()``）。

    Returns:
        bool: 已是前台返回 True；非 Windows / 句柄无效 / 查询失败返回 False。
    """
    if not hwnd:
        return False
    try:
        if not _ensure_bindings():
            return False
        foreground = int(_user32.GetForegroundWindow() or 0)
        return foreground == int(hwnd)
    except Exception:  # noqa: BLE001 - 原生查询失败按“不是前台”处理
        return False


def force_foreground_window(hwnd: int) -> bool:
    """尝试把指定窗口切到 Windows 原生前台。

    先直接调用 ``SetForegroundWindow``；若被前台锁拒绝，则把当前线程
    临时附加到当前前台窗口线程后重试。附加状态无论成功失败都会解除。

    Args:
        hwnd: 顶层窗口句柄（``QWidget.winId()``）。

    Returns:
        bool: 调用结束后该窗口确实成为前台返回 True；否则返回 False。
    """
    if not hwnd:
        return False
    try:
        if not _ensure_bindings():
            return False
        target = int(hwnd)
        user32 = _user32
        kernel32 = _kernel32

        if int(user32.GetForegroundWindow() or 0) == target:
            return True

        # 1) 直接尝试：正常双击启动时系统通常已给前台权限，这一步即可成功。
        user32.SetForegroundWindow(target)
        if int(user32.GetForegroundWindow() or 0) == target:
            return True

        # 2) 被前台锁拒绝（典型：从终端 / IDE 启动）：把当前线程临时附加到
        #    当前前台窗口线程，再重试。无论成功失败都必须解除附加。
        foreground = int(user32.GetForegroundWindow() or 0)
        foreground_tid = 0
        if foreground:
            process_id = wintypes.DWORD()
            foreground_tid = int(
                user32.GetWindowThreadProcessId(
                    foreground, ctypes.byref(process_id)
                )
                or 0
            )
        current_tid = int(kernel32.GetCurrentThreadId())

        attached = False
        if foreground_tid and foreground_tid != current_tid:
            attached = bool(
                user32.AttachThreadInput(foreground_tid, current_tid, True)
            )
        try:
            user32.SetForegroundWindow(target)
        finally:
            if attached:
                # 解除附加失败不应覆盖真实的激活结果；Qt 主线程后续仍可
                # 正常处理输入，这里只做尽力清理。
                try:
                    user32.AttachThreadInput(foreground_tid, current_tid, False)
                except Exception:  # noqa: BLE001 - 清理阶段不得再抛
                    pass

        # SetForegroundWindow 在部分受限场景会返回成功但只闪任务栏，
        # 以实际 GetForegroundWindow 结果为准。
        return int(user32.GetForegroundWindow() or 0) == target
    except Exception:  # noqa: BLE001 - 启动路径不得因原生激活失败而中断
        return False
