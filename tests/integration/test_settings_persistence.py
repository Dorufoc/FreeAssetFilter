# -*- coding: utf-8 -*-
# targets: freeassetfilter.core.managers.settings_manager, freeassetfilter.core.managers.theme_manager
"""integration 批 1（W6/todo-24）：设置写盘 → 防抖保存 → 重载读回 + 主题切换信号闭环。

QA 验收点（计划 todo-24）：

1. ``SettingsManager`` 写盘后**新实例读回**同一值（round-trip）；
2. 0.35s 防抖机制：``schedule_save`` 延迟写盘会真正落盘（用短延迟
   ``delay=0.05`` 与手动 ``_flush_scheduled_save`` 触发，**不真实等待 350ms**）；
3. ``ThemeManager.toggle_theme`` 发射 ``theme_changed(str)`` 与
   ``colors_updated(dict)``，并将主题值持久化到同一设置文件。

测试纪律（计划 todo-24）：

* 所有设置文件都在 ``tmp_path``，**绝不触碰真实 data/ 或用户设置**；
* 单例重建必须显式 ``_instance = None; _initialized = False``；
* 等待一律有界（短延迟 + 轮询 / 手动 flush），绝无真实 350ms 长等待。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest
from PySide6.QtWidgets import QApplication

from freeassetfilter.core.managers.settings_manager import SettingsManager

from tests.support.qt_helpers import process_qt_events

pytestmark = pytest.mark.integration


# =============================================================================
# helper
# =============================================================================
def _reload_settings(settings_file: Path) -> Any:
    """重置单例并用同一文件重建 SettingsManager，模拟进程重启后读回。

    Args:
        settings_file: 设置文件路径。

    Returns:
        Any: 绑定同一文件的 SettingsManager 新实例。
    """
    SettingsManager._instance = None
    SettingsManager._initialized = False
    return SettingsManager(settings_file=str(settings_file))


def _file_has_key_value(settings_file: Path, key_path: str, value: Any) -> bool:
    """直接解析 JSON 文件，判断键路径是否等于给定值（轮询用）。

    Args:
        settings_file: 设置文件路径。
        key_path: 点分键路径，如 ``player.last_volume``。
        value: 期望值。

    Returns:
        bool: 文件已包含该键值对。
    """
    try:
        with open(settings_file, "r", encoding="utf-8") as fh:
            data: Dict[str, Any] = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return False

    node: Any = data
    for part in key_path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return node == value


# =============================================================================
# SettingsManager 持久化
# =============================================================================
class TestSettingsPersistence:
    """SettingsManager 写盘 / 防抖 / 重载读回。"""

    def test_setting_round_trip_via_sync_save(
        self, settings_manager: Any, tmp_path: Path
    ) -> None:
        """同步 save_settings 后，同文件新实例读回相同值。"""
        sm: Any = settings_manager
        assert sm.set_setting("appearance.theme", "dark") is True

        sm.save_settings()
        assert (tmp_path / "test_settings.json").is_file(), "设置文件应已写盘"

        fresh: Any = _reload_settings(tmp_path / "test_settings.json")
        assert fresh.get_setting("appearance.theme") == "dark"

    def test_debounced_flush_persists(
        self, settings_manager: Any, tmp_path: Path
    ) -> None:
        """save_player_volume 走 schedule_save 防抖路径；手动 flush 后落盘。"""
        sm: Any = settings_manager
        sm.save_player_volume(66)  # set_setting + schedule_save（默认 0.35s）

        assert sm._save_pending is True, "应有待保存标记"
        sm._flush_scheduled_save()  # 手动触发 timer 到期逻辑，避免真实 350ms
        assert sm._save_timer is None, "flush 后不应残留计时器"

        fresh: Any = _reload_settings(tmp_path / "test_settings.json")
        assert fresh.get_setting("player.last_volume") == 66
        # get_player_volume 不走 use_default 时返回 last_volume
        assert fresh.get_player_volume() == 66

    def test_short_delay_schedule_save_real_timer(
        self, qapp: QApplication, settings_manager: Any, tmp_path: Path
    ) -> None:
        """短延迟（0.05s）真实触发 threading.Timer 落盘，验证防抖真正写文件。"""
        sm: Any = settings_manager
        sm.set_setting("player.last_speed", 1.5)
        sm.schedule_save(delay=0.05)  # 短防抖，而非默认 0.35s

        midi: Path = tmp_path / "test_settings.json"
        deadline: float = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            process_qt_events(qapp, ms=20)
            if _file_has_key_value(midi, "player.last_speed", 1.5):
                break
        assert _file_has_key_value(midi, "player.last_speed", 1.5), "防抖写盘应完成"

        fresh: Any = _reload_settings(midi)
        assert fresh.get_setting("player.last_speed") == 1.5


# =============================================================================
# ThemeManager 信号闭环
# =============================================================================
class TestThemeManagerSignals:
    """toggle_theme 发射 theme_changed + colors_updated，并持久化主题。"""

    def test_toggle_theme_emits_signals_and_persists(
        self, settings_manager: Any, tmp_path: Path
    ) -> None:
        """切换为深色：双信号发射且参数正确；主题与颜色持久化到同一文件。"""
        from freeassetfilter.core.managers.theme_manager import ThemeManager

        sm: Any = settings_manager
        tm: Any = ThemeManager(settings_manager=sm)

        themes: List[str] = []
        colors: List[Dict[str, Any]] = []
        tm.theme_changed.connect(themes.append)
        tm.colors_updated.connect(colors.append)

        result = tm.toggle_theme(True)  # 深色

        assert themes == ["dark"], "theme_changed 应发射 'dark'"
        # 注意：PySide6 的 Signal(dict) 接收端拿到的是副本（键已按字典序
        # 重排），因此用相等比较而非 is。
        assert colors and colors[-1] == tm.theme_colors, "colors_updated 应携带颜色字典"
        assert result is tm.theme_colors
        assert sm.get_setting("appearance.theme") == "dark"
        assert tm.is_dark_theme() is True

        # 持久化到同一文件（toggle_theme 内部 save_settings）
        midi: Path = tmp_path / "test_settings.json"
        fresh: Any = _reload_settings(midi)
        assert fresh.get_setting("appearance.theme") == "dark"
        assert fresh.get_setting("appearance.colors.base_color") == "#212121"

    def test_toggle_theme_round_trip_light_after_dark(
        self, settings_manager: Any, tmp_path: Path
    ) -> None:
        """深→浅两次切换均持久化，重载实例读到最终主题（浅色）。"""
        from freeassetfilter.core.managers.theme_manager import ThemeManager

        sm: Any = settings_manager
        tm: Any = ThemeManager(settings_manager=sm)

        captured: List[str] = []
        tm.theme_changed.connect(captured.append)

        tm.toggle_theme(True)
        tm.toggle_theme(False)  # 浅色

        assert captured == ["dark", "default"]
        assert sm.get_setting("appearance.theme") == "default"

        midi: Path = tmp_path / "test_settings.json"
        fresh: Any = _reload_settings(midi)
        assert fresh.get_setting("appearance.theme") == "default"
        assert fresh.get_setting("appearance.colors.base_color") == "#FFFFFF"