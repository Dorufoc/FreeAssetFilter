#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局鼠标监控组件

提供全局鼠标移动、点击、滚轮检测及空闲超时功能。
兼容原 MouseActivityMonitor 的常用接口，并保留更完整的全局监控能力。

功能特点：
- 使用 Windows 低级鼠标钩子 (WH_MOUSE_LL) 实现全局监控
- 同时支持鼠标移动、鼠标点击和滚轮事件检测
- 支持配置空闲超时时间
- 提供信号和回调函数两种通知方式
- 线程安全的实现
- 可独立启动和停止监控

使用示例：
```python
monitor = GlobalMouseMonitor(timeout=5000)
monitor.mouse_moved.connect(on_mouse_move)
monitor.mouse_clicked.connect(on_mouse_click)
monitor.timeout_reached.connect(on_timeout)
monitor.start()
```

Author: FreeAssetFilter
Date: 2025
"""

import ctypes
import threading
import time
from ctypes import wintypes
from PySide6.QtCore import QObject, Signal, QTimer, Slot

from freeassetfilter.utils.app_logger import info, debug, warning, error


class GlobalMouseMonitor(QObject):
    """
    全局鼠标监控器类

    用于检测全局鼠标移动、点击、滚轮事件，并支持空闲超时。
    当检测到鼠标活动时，会触发相应的信号或回调函数。

    Attributes:
        mouse_moved (Signal): 鼠标移动信号
        mouse_clicked (Signal): 鼠标点击信号
        mouse_scrolled (Signal): 鼠标滚轮信号
        timeout_reached (Signal): 空闲超时信号
    """

    _active_instances_lock = threading.Lock()
    _active_instances = set()

    mouse_moved = Signal()
    mouse_clicked = Signal()
    mouse_scrolled = Signal()
    timeout_reached = Signal()

    @classmethod
    def stop_all(cls):
        """
        停止所有活跃的 GlobalMouseMonitor 实例

        在应用程序退出前调用，确保所有 Windows 钩子被卸载，
        避免底层 native 线程（_DummyThread）阻止进程干净退出。
        """
        with cls._active_instances_lock:
            instances = list(cls._active_instances)

        for monitor in instances:
            try:
                monitor._disposed = True
                monitor.stop()
            except (RuntimeError, AttributeError, OSError) as e:
                debug(f"[GlobalMouseMonitor] 停止监控器实例时出错: {e}")

        with cls._active_instances_lock:
            cls._active_instances.clear()

        cls._cleanup_dummy_threads()

    @classmethod
    def _cleanup_dummy_threads(cls):
        """
        清理 threading._active 中残留的 _DummyThread 对象

        当 Windows 钩子回调被 native 线程调用时，Python 会自动创建
        _DummyThread 代理并注册到 threading._active。卸载钩子后，
        这些 _DummyThread 对象不会自动移除，需要手动清理。
        """
        try:
            with threading._active_limbo_lock:
                to_remove = [
                    ident for ident, thread in threading._active.items()
                    if isinstance(thread, threading._DummyThread)
                ]
                for ident in to_remove:
                    try:
                        del threading._active[ident]
                    except KeyError:
                        pass
        except (AttributeError, RuntimeError) as e:
            debug(f"[GlobalMouseMonitor] 清理 _DummyThread 失败: {e}")

    def __init__(self, parent=None, timeout=3000):
        """
        初始化全局鼠标监控器

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
        self._is_monitoring = False
        self._stopping = False
        self._disposed = False

        # 用于在钩子回调中安全地发射信号
        self._pending_move = False
        self._pending_click = False
        self._pending_scroll = False

        self._last_hook_emit_time = 0
        self._last_move_emit_time = 0

        # 定时器用于处理钩子回调中的信号发射
        self._signal_timer = QTimer(self)
        self._signal_timer.setInterval(10)
        self._signal_timer.timeout.connect(self._process_pending_signals)

        # 空闲超时定时器
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._on_timeout)

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
            value (callable): 可调用对象，会在检测到鼠标活动时调用
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
        if self._disposed:
            return False

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
                        if wParam == WM_MOUSEMOVE:
                            pt = wintypes.POINT()
                            user32.GetCursorPos(ctypes.byref(pt))
                            current_pos = (pt.x, pt.y)

                            if self._last_mouse_pos is None or self._last_mouse_pos != current_pos:
                                self._last_mouse_pos = current_pos
                                current_time = time.time() * 1000
                                if (current_time - self._last_hook_emit_time) >= 16:
                                    self._last_hook_emit_time = current_time
                                    self._pending_move = True

                        elif wParam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN, WM_XBUTTONDOWN):
                            self._pending_click = True

                        elif wParam in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
                            self._pending_scroll = True

                except (AttributeError, TypeError, OSError) as e:
                    debug(f"[GlobalMouseMonitor] 鼠标回调处理异常: {e}")

                return user32.CallNextHookEx(None, nCode, wParam, lParam)

            mouse_proc_func = ctypes.CFUNCTYPE(
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int
            )(mouse_proc)

            self._mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_proc_func, None, 0)
            if not self._mouse_hook:
                error_code = ctypes.get_last_error()
                error(f"[GlobalMouseMonitor] 安装鼠标钩子失败，错误码: {error_code}")
                return False

            self._mouse_proc_func = mouse_proc_func
            self._is_monitoring = True
            self._signal_timer.start()
            self._hide_timer.start(self._timeout)

            with GlobalMouseMonitor._active_instances_lock:
                GlobalMouseMonitor._active_instances.add(self)

            return True

        except OSError as e:
            error(f"[GlobalMouseMonitor] 启动监控失败 (系统错误): {e}")
            return False

    def stop(self):
        """
        停止监控鼠标活动
        """
        if self._stopping:
            return

        if not self._is_monitoring:
            self._pending_move = False
            self._pending_click = False
            self._pending_scroll = False
            return

        self._stopping = True

        try:
            self._signal_timer.stop()
            self._hide_timer.stop()

            if self._mouse_hook:
                try:
                    ctypes.windll.user32.UnhookWindowsHookEx(self._mouse_hook)
                except OSError as e:
                    error(f"[GlobalMouseMonitor] 卸载鼠标钩子失败: {e}")

            self._mouse_hook = None
            self._mouse_proc_func = None
            self._last_mouse_pos = None
            self._is_monitoring = False
            self._pending_move = False
            self._pending_click = False
            self._pending_scroll = False
            self._last_hook_emit_time = 0
            self._last_move_emit_time = 0

            with GlobalMouseMonitor._active_instances_lock:
                GlobalMouseMonitor._active_instances.discard(self)
        finally:
            self._stopping = False

    def reset_timer(self):
        """
        重置空闲计时器
        """
        if self._is_monitoring:
            self._hide_timer.stop()
            self._hide_timer.start(self._timeout)

    def _notify_activity(self):
        """统一处理鼠标活动后的计时器和回调逻辑"""
        if self._activity_callback:
            try:
                self._activity_callback()
            except Exception as e:
                error(f"[GlobalMouseMonitor] 活动回调函数执行失败: {e}")

        if self._is_monitoring:
            self._hide_timer.stop()
            self._hide_timer.start(self._timeout)

    @Slot()
    def _process_pending_signals(self):
        """处理待发射的信号"""
        if self._disposed or self._stopping or not self._is_monitoring:
            self._pending_move = False
            self._pending_click = False
            self._pending_scroll = False
            return

        if self._pending_move:
            current_time = time.time() * 1000
            if (current_time - self._last_move_emit_time) >= 50:
                self._last_move_emit_time = current_time
                self._pending_move = False
                self.mouse_moved.emit()
                self._notify_activity()
            else:
                self._pending_move = False
                self.reset_timer()

        if self._pending_click:
            self._pending_click = False
            self.mouse_clicked.emit()
            self._notify_activity()

        if self._pending_scroll:
            self._pending_scroll = False
            self.mouse_scrolled.emit()
            self._notify_activity()

    @Slot()
    def _on_timeout(self):
        """空闲超时处理"""
        if self._disposed or self._stopping:
            return

        self.timeout_reached.emit()

        if self._timeout_callback:
            try:
                self._timeout_callback()
            except Exception as e:
                error(f"[GlobalMouseMonitor] 超时回调函数执行失败: {e}")

    def __del__(self):
        """析构函数，确保清理资源"""
        self._disposed = True
        self.stop()
