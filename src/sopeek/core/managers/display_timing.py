#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""显示器刷新率探测。

UI 的帧率上限来自显示器自身刷新率，但项目此前把动画节拍写死成
16 / 30 / 33 / 50 ms，在 120Hz、144Hz、240Hz 面板上只能跑到上限的
1/4 ~ 1/11。本模块只回答一个问题——**当前窗口所在屏幕的刷新率是多少**，
然后把"面板帧间隔"交给 :mod:`sopeek.core.managers.frame_scheduler`
统一换算。

设计约束：
    - 无 GUI（纯单元测试 / 早期启动阶段）时静默回退 :data:`DEFAULT_REFRESH_HZ`；
    - 刷新率随窗口跨屏、显示器热插拔变化，故提供 :class:`DisplayTiming`
      缓存与 ``refresh()`` 主动重采样（由帧调度器每秒节流调用一次）；
    - 不写任何系统设置（DWM / 显卡控制面板），纯只读探测。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication, QScreen, QWindow
from PySide6.QtWidgets import QWidget

from sopeek.utils.app_logger import debug

#: 探测失败时的回退刷新率（Hz）。
DEFAULT_REFRESH_HZ: float = 60.0
#: 合理的刷新率下界（低于此值视为探测噪声）。
MIN_REFRESH_HZ: float = 24.0
#: 合理的刷新率上界（覆盖 480/500Hz 电竞屏，防异常值把定时器压到 0ms）。
MAX_REFRESH_HZ: float = 500.0

#: 常见面板档位。探测值落在某档位 ±1.5% 内即吸附，消除 239.76 /
#: 59.94 这类由像素时钟推导出的浮点噪声。
KNOWN_REFRESH_STEPS: tuple[float, ...] = (
    24.0, 25.0, 30.0, 48.0, 50.0, 60.0, 72.0, 75.0, 90.0, 100.0,
    120.0, 144.0, 165.0, 180.0, 200.0, 240.0, 280.0, 300.0, 360.0,
    480.0, 500.0,
)

#: 吸附容差（相对误差）。
_SNAP_TOLERANCE: float = 0.015


def sanitize_refresh_hz(
    value: object, fallback: float = DEFAULT_REFRESH_HZ
) -> float:
    """把任意探测结果规范化为可用的刷新率。

    Args:
        value: 原始探测值（``QScreen.refreshRate()`` 返回 ``float``，
            异常时可能是 ``0.0`` / ``None``）。
        fallback: 不可用时返回的刷新率。

    Returns:
        吸附到 :data:`KNOWN_REFRESH_STEPS` 或原值，范围
        ``[MIN_REFRESH_HZ, MAX_REFRESH_HZ]``。
    """
    try:
        hz = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    if hz != hz or hz <= 0.0:  # NaN 或非正数
        return fallback
    for step in KNOWN_REFRESH_STEPS:
        if abs(hz - step) <= step * _SNAP_TOLERANCE:
            return step
    return max(MIN_REFRESH_HZ, min(MAX_REFRESH_HZ, hz))


def screen_refresh_hz(screen: Optional[QScreen] = None) -> float:
    """返回指定屏幕（``None`` = 主屏）的刷新率。

    Args:
        screen: 目标屏幕；``None`` 时取 ``QGuiApplication.primaryScreen()``。

    Returns:
        刷新率（Hz）；无 GUI 或探测失败时返回 :data:`DEFAULT_REFRESH_HZ`。
    """
    app = QGuiApplication.instance()
    if app is None:
        return DEFAULT_REFRESH_HZ
    target = screen if screen is not None else QGuiApplication.primaryScreen()
    if target is None:
        return DEFAULT_REFRESH_HZ
    try:
        return sanitize_refresh_hz(target.refreshRate())
    except RuntimeError:  # 屏幕对象已被销毁
        return DEFAULT_REFRESH_HZ


def frame_interval_ms(hz: float) -> float:
    """把刷新率换算成帧间隔（毫秒）。

    Args:
        hz: 刷新率（Hz）。

    Returns:
        一帧的毫秒数，恒为正。
    """
    safe_hz = max(MIN_REFRESH_HZ, min(MAX_REFRESH_HZ, float(hz)))
    return 1000.0 / safe_hz


class DisplayTiming(QObject):
    """当前 UI 面板刷新率的缓存与变化广播（单例）。

    帧调度器不直接调用 ``QScreen.refreshRate()``：该调用是平台查询，
    放在每帧热路径上没有必要。这里缓存一份，按需（约每秒一次）重采样，
    变化时发 :attr:`refresh_changed`。
    """

    #: 面板刷新率变化（Hz）。
    refresh_changed = Signal(float)

    _instance: Optional["DisplayTiming"] = None

    def __new__(cls) -> "DisplayTiming":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_ready", False):
            return
        super().__init__()
        self._ready = True
        self._hz: float = DEFAULT_REFRESH_HZ
        self._window: Optional[QWindow] = None
        self._sampled: bool = False

    # -- 采样 ---------------------------------------------------------------

    def follow_window(self, window: Optional[QWidget | QWindow]) -> None:
        """让刷新率跟随指定窗口所在屏幕。

        Args:
            window: 主窗口（``QWidget`` 或 ``QWindow``）；``None`` 表示
                回退到主屏。
        """
        handle: Optional[QWindow] = None
        if isinstance(window, QWidget):
            handle = window.windowHandle()
            if handle is None and window.isVisible():
                handle = window.window().windowHandle()
        elif isinstance(window, QWindow):
            handle = window
        if handle is self._window:
            return
        if self._window is not None:
            try:
                self._window.screenChanged.disconnect(self._on_screen_changed)
            except (RuntimeError, TypeError):
                pass
        self._window = handle
        if handle is not None:
            try:
                handle.screenChanged.connect(self._on_screen_changed)
            except (RuntimeError, TypeError):
                pass
        self.refresh()

    def _on_screen_changed(self, _screen: Optional[QScreen]) -> None:
        """窗口跨屏后立即重采样（不等轮询）。"""
        self.refresh()

    def refresh(self, force: bool = False) -> float:
        """重新采样并广播变化。

        Args:
            force: 即使缓存已存在也重新查询平台。

        Returns:
            当前刷新率（Hz）。
        """
        if self._sampled and not force:
            return self._hz
        screen: Optional[QScreen] = None
        if self._window is not None:
            try:
                screen = self._window.screen()
            except RuntimeError:
                self._window = None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        hz = screen_refresh_hz(screen)
        self._sampled = True
        if abs(hz - self._hz) > 0.01:
            previous = self._hz
            self._hz = hz
            debug(f"DisplayTiming: refresh rate {previous:.2f}Hz -> {hz:.2f}Hz")
            self.refresh_changed.emit(hz)
        return self._hz

    # -- 查询 ---------------------------------------------------------------

    @property
    def hz(self) -> float:
        """当前面板刷新率（Hz）。"""
        return self._hz

    @property
    def interval_ms(self) -> float:
        """当前面板帧间隔（毫秒）。"""
        return frame_interval_ms(self._hz)


def display_timing() -> DisplayTiming:
    """返回 :class:`DisplayTiming` 单例。"""
    return DisplayTiming()
