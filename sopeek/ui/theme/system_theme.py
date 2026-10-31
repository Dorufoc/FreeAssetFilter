"""Windows 系统深浅色主题检测与监听。

读取个性化注册表判断系统当前为深色还是浅色，并在跟随系统模式下
通过轮询实时感知系统主题变化。

注册表键（Windows 10 1809+）：
    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize
    - AppsUseLightTheme    (REG_DWORD, 0 = 深色 / 1 = 浅色，应用主题)
    - SystemUsesLightTheme (REG_DWORD, 同上，系统主题，回退用)

非 Windows 平台或读取失败时回退为浅色（"light"），调用方无需判空。
"""

from __future__ import annotations

import sys

from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal


_PERSONALIZE_SUBKEY: str = (
    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
)

_VALID_THEMES: frozenset[str] = frozenset({"dark", "light"})


def _read_personalize_value(value_name: str) -> Optional[int]:
    """读取个性化注册表 DWORD 值。

    Args:
        value_name: 注册表值名（如 AppsUseLightTheme）。

    Returns:
        DWORD 整数值；非 Windows 平台或读取失败时返回 None。
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _PERSONALIZE_SUBKEY,
            0,
            winreg.KEY_READ,
        ) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
            return int(value)
    except Exception:
        return None


def get_windows_system_theme() -> str:
    """返回当前 Windows 系统主题。

    优先读取 AppsUseLightTheme，缺失时回退 SystemUsesLightTheme，
    均不可用时回退为 "light"。

    Returns:
        系统主题名："dark" 或 "light"。
    """
    apps_light = _read_personalize_value("AppsUseLightTheme")
    if apps_light is not None:
        return "light" if apps_light else "dark"
    system_light = _read_personalize_value("SystemUsesLightTheme")
    if system_light is not None:
        return "light" if system_light else "dark"
    return "light"


def is_windows_system_dark() -> bool:
    """返回系统当前是否为深色模式。

    Returns:
        深色模式返回 True，否则返回 False。
    """
    return get_windows_system_theme() == "dark"


class SystemThemeWatcher(QObject):
    """系统主题变化轮询监听器。

    Windows 未提供稳定的 Qt 原生主题变更信号，因此采用 QTimer 轮询
    注册表（默认 2 秒），变化时发射 ``system_theme_changed`` 信号。
    仅在跟随系统模式下由调用方消费，普通手动模式可保持停止以零开销。
    """

    system_theme_changed = Signal(str)  # "dark" or "light"

    def __init__(
        self, parent: Optional[QObject] = None, interval_ms: int = 2000
    ) -> None:
        """初始化监听器。

        Args:
            parent: 父对象。
            interval_ms: 轮询间隔毫秒数。
        """
        super().__init__(parent)
        self._interval_ms: int = max(500, int(interval_ms))
        self._last_theme: str = get_windows_system_theme()
        self._timer = QTimer(self)
        self._timer.setInterval(self._interval_ms)
        self._timer.timeout.connect(self.check_now)

    def start(self) -> None:
        """启动轮询（幂等）。"""
        self._last_theme = get_windows_system_theme()
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        """停止轮询（幂等）。"""
        if self._timer.isActive():
            self._timer.stop()

    def is_running(self) -> bool:
        """返回轮询是否运行中。

        Returns:
            运行中返回 True，否则返回 False。
        """
        return self._timer.isActive()

    def current_theme(self) -> str:
        """返回最近一次缓存的系统主题。

        Returns:
            "dark" 或 "light"。
        """
        return self._last_theme

    def check_now(self) -> bool:
        """立即检测一次系统主题，变化时发射信号。

        Returns:
            发生切换返回 True，否则返回 False。
        """
        current = get_windows_system_theme()
        if current not in _VALID_THEMES:
            return False
        if current != self._last_theme:
            self._last_theme = current
            self.system_theme_changed.emit(current)
            return True
        return False


_watcher_instance: Optional[SystemThemeWatcher] = None


def get_system_theme_watcher() -> SystemThemeWatcher:
    """返回进程级单例监听器。

    Returns:
        SystemThemeWatcher: 全局唯一的系统主题监听器。
    """
    global _watcher_instance
    if _watcher_instance is None:
        _watcher_instance = SystemThemeWatcher()
    return _watcher_instance
