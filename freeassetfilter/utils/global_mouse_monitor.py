#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局鼠标监控组件

提供全局鼠标移动和点击检测功能，可用于检测用户的鼠标活动。
支持独立监控鼠标移动和鼠标点击事件。

功能特点：
- 使用 Windows 低级鼠标钩子 (WH_MOUSE_LL) 实现全局监控
- 同时支持鼠标移动和鼠标点击事件检测
- 提供信号通知方式
- 线程安全的实现
- 可独立启动和停止监控

使用示例：
```python
# 创建全局鼠标监控器
monitor = GlobalMouseMonitor()

# 连接信号
monitor.mouse_moved.connect(on_mouse_move)
monitor.mouse_clicked.connect(on_mouse_click)

# 开始监控
monitor.start()

# 停止监控
monitor.stop()
```

Author: FreeAssetFilter
Date: 2025
"""

import ctypes
from ctypes import wintypes
from PySide6.QtCore import QObject, Signal, QTimer, Slot


class GlobalMouseMonitor(QObject):
    """
    全局鼠标监控器类

    用于检测全局鼠标移动和点击事件。
    当检测到鼠标移动或点击时，会触发相应的信号。

    Attributes:
        mouse_moved (Signal): 鼠标移动信号
        mouse_clicked (Signal): 鼠标点击信号
    """

    mouse_moved = Signal()
    """鼠标移动信号 - 当检测到鼠标位置变化时触发"""

    mouse_clicked = Signal()
    """鼠标点击信号 - 当检测到鼠标点击（按下）时触发"""

    mouse_scrolled = Signal()
    """鼠标滚轮信号 - 当检测到鼠标滚轮滚动时触发"""

    def __init__(self, parent=None):
        """
        初始化全局鼠标监控器

        Args:
            parent: 父QObject对象
        """
        super().__init__(parent)

        self._mouse_hook = None
        self._mouse_proc_func = None
        self._last_mouse_pos = None
        self._is_monitoring = False

        # 用于在钩子回调中安全地发射信号
        self._pending_move = False
        self._pending_click = False
        self._pending_scroll = False

        # 定时器用于处理钩子回调中的信号发射
        self._signal_timer = QTimer(self)
        self._signal_timer.setInterval(10)  # 10ms间隔
        self._signal_timer.timeout.connect(self._process_pending_signals)

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
            
            # 鼠标消息常量
            WM_MOUSEMOVE = 0x0200
            WM_LBUTTONDOWN = 0x0201
            WM_RBUTTONDOWN = 0x0204
            WM_MBUTTONDOWN = 0x0207
            WM_XBUTTONDOWN = 0x020B
            WM_MOUSEWHEEL = 0x020A
            WM_MOUSEHWHEEL = 0x020E

            def mouse_proc(nCode, wParam, lParam):
                """鼠标钩子回调函数"""
                try:
                    if nCode == 0:
                        # 处理鼠标移动
                        if wParam == WM_MOUSEMOVE:
                            pt = wintypes.POINT()
                            user32.GetCursorPos(ctypes.byref(pt))
                            current_pos = (pt.x, pt.y)

                            if self._last_mouse_pos is None or self._last_mouse_pos != current_pos:
                                self._last_mouse_pos = current_pos
                                self._pending_move = True
                        
                        # 处理鼠标点击（左键、右键、中键、X键按下）
                        elif wParam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN, WM_XBUTTONDOWN):
                            self._pending_click = True

                        # 处理鼠标滚轮滚动（垂直和水平滚轮）
                        elif wParam in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
                            self._pending_scroll = True

                except Exception:
                    pass

                return user32.CallNextHookEx(None, nCode, wParam, lParam)

            mouse_proc_func = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int)(mouse_proc)

            self._mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_proc_func, None, 0)
            if not self._mouse_hook:
                error_code = ctypes.get_last_error()
                print(f"[GlobalMouseMonitor] 安装鼠标钩子失败，错误码: {error_code}")
                return False

            self._mouse_proc_func = mouse_proc_func
            self._is_monitoring = True
            self._signal_timer.start()

            return True

        except Exception as e:
            print(f"[GlobalMouseMonitor] 启动监控失败: {e}")
            return False

    def stop(self):
        """
        停止监控鼠标活动
        """
        if not self._is_monitoring:
            return

        self._signal_timer.stop()

        if self._mouse_hook:
            try:
                ctypes.windll.user32.UnhookWindowsHookEx(self._mouse_hook)
            except Exception as e:
                print(f"[GlobalMouseMonitor] 卸载鼠标钩子失败: {e}")

        self._mouse_hook = None
        self._mouse_proc_func = None
        self._last_mouse_pos = None
        self._is_monitoring = False
        self._pending_move = False
        self._pending_click = False
        self._pending_scroll = False

    @Slot()
    def _process_pending_signals(self):
        """处理待发射的信号"""
        if self._pending_move:
            self._pending_move = False
            self.mouse_moved.emit()

        if self._pending_click:
            self._pending_click = False
            self.mouse_clicked.emit()

        if self._pending_scroll:
            self._pending_scroll = False
            self.mouse_scrolled.emit()

    def __del__(self):
        """析构函数，确保清理资源"""
        self.stop()
