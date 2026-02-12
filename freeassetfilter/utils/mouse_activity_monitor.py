#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
鼠标活动监控组件

提供全局鼠标移动检测功能，可用于检测用户是否在使用鼠标。
支持配置空闲超时时间，超时后触发相应的回调函数。

功能特点：
- 使用 Windows 低级鼠标钩子 (WH_MOUSE_LL) 实现全局监控
- 支持配置空闲超时时间
- 提供信号和回调函数两种通知方式
- 线程安全的实现
- 可独立启动和停止监控

使用示例：
```python
# 创建监控器并设置5秒超时
monitor = MouseActivityMonitor(timeout=5000)

# 使用回调函数
def on_activity():
    print("检测到鼠标活动")

monitor.activity_callback = on_activity
monitor.start()

# 停止监控
monitor.stop()
```

Author: FreeAssetFilter
Date: 2025
"""

import sys
import os
import ctypes
from ctypes import wintypes
from PySide6.QtCore import QObject, Signal, QTimer, Slot


class MouseActivityMonitor(QObject):
    """
    鼠标活动监控器类

    用于检测全局鼠标移动，支持配置空闲超时时间。
    当检测到鼠标移动时，会触发相应的信号或回调函数。

    Attributes:
        timeout (int): 空闲超时时间（毫秒），默认3000ms
        activity_callback (callable): 鼠标活动时的回调函数
        timeout_callback (callable): 空闲超时时的回调函数
    """

    mouse_moved = Signal()
    """鼠标移动信号"""

    timeout_reached = Signal()
    """空闲超时信号"""

    def __init__(self, parent=None, timeout=3000):
        """
        初始化鼠标活动监控器

        Args:
            parent: 父QObject对象
            timeout (int): 空闲超时时间（毫秒），默认3000ms
        """
        super().__init__(parent)

        self._timeout = timeout
        self._activity_callback = None
        self._timeout_callback = None
        self._mouse_hook = None
        self._mouse_proc_func = None
        self._last_mouse_pos = None
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._on_timeout)
        self._is_monitoring = False

    @property
    def timeout(self):
        """
        获取超时时间（毫秒）

        Returns:
            int: 超时时间
        """
        return self._timeout

    @timeout.setter
    def timeout(self, value):
        """
        设置超时时间

        Args:
            value (int): 超时时间（毫秒）
        """
        self._timeout = value
        if self._is_monitoring:
            self._hide_timer.start(self._timeout)

    @property
    def activity_callback(self):
        """获取鼠标活动回调函数"""
        return self._activity_callback

    @activity_callback.setter
    def activity_callback(self, value):
        """
        设置鼠标活动回调函数

        Args:
            value (callable): 可调用对象，会在检测到鼠标移动时调用
        """
        self._activity_callback = value

    @property
    def timeout_callback(self):
        """获取空闲超时回调函数"""
        return self._timeout_callback

    @timeout_callback.setter
    def timeout_callback(self, value):
        """
        设置空闲超时回调函数

        Args:
            value (callable): 可调用对象，会在空闲超时时调用
        """
        self._timeout_callback = value

    def is_monitoring(self):
        """
        检查是否正在监控

        Returns:
            bool: 是否正在监控
        """
        return self._is_monitoring

    def start(self):
        """
        开始监控鼠标活动

        Returns:
            bool: 是否成功启动监控
        """
        if self._is_monitoring:
            return True

        try:
            user32 = ctypes.windll.user32
            WH_MOUSE_LL = 14

            def mouse_proc(nCode, wParam, lParam):
                """鼠标钩子回调函数"""
                try:
                    if nCode == 0 and wParam == 0x200:
                        pt = wintypes.POINT()
                        user32.GetCursorPos(ctypes.byref(pt))
                        current_pos = (pt.x, pt.y)

                        if self._last_mouse_pos is None or self._last_mouse_pos != current_pos:
                            self._last_mouse_pos = current_pos
                            QTimer.singleShot(0, self._on_mouse_moved)
                except Exception:
                    pass

                return user32.CallNextHookEx(None, nCode, wParam, lParam)

            mouse_proc_func = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int)(mouse_proc)

            self._mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_proc_func, None, 0)
            if not self._mouse_hook:
                error_code = ctypes.get_last_error()
                print(f"[MouseActivityMonitor] 安装鼠标钩子失败，错误码: {error_code}")
                return False

            self._mouse_proc_func = mouse_proc_func
            self._is_monitoring = True
            self._hide_timer.start(self._timeout)

            return True

        except Exception as e:
            print(f"[MouseActivityMonitor] 启动监控失败: {e}")
            return False

    def stop(self):
        """
        停止监控鼠标活动
        """
        if not self._is_monitoring:
            return

        self._hide_timer.stop()

        if self._mouse_hook:
            try:
                ctypes.windll.user32.UnhookWindowsHookEx(self._mouse_hook)
            except Exception as e:
                print(f"[MouseActivityMonitor] 卸载鼠标钩子失败: {e}")

        self._mouse_hook = None
        self._mouse_proc_func = None
        self._last_mouse_pos = None
        self._is_monitoring = False

    def reset_timer(self):
        """
        重置空闲计时器

        手动重置计时器，适用于需要在检测到活动后立即重置的场景。
        """
        if self._is_monitoring:
            self._hide_timer.stop()
            self._hide_timer.start(self._timeout)

    @Slot()
    def _on_mouse_moved(self):
        """鼠标移动时的处理"""
        self.mouse_moved.emit()

        if self._activity_callback:
            try:
                self._activity_callback()
            except Exception as e:
                print(f"[MouseActivityMonitor] 回调函数执行失败: {e}")

        if self._is_monitoring:
            self._hide_timer.stop()
            self._hide_timer.start(self._timeout)

    @Slot()
    def _on_timeout(self):
        """空闲超时处理"""
        self.timeout_reached.emit()

        if self._timeout_callback:
            try:
                self._timeout_callback()
            except Exception as e:
                print(f"[MouseActivityMonitor] 超时回调函数执行失败: {e}")

    def __del__(self):
        """析构函数，确保清理资源"""
        self.stop()
