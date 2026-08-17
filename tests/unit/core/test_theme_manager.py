# -*- coding: utf-8 -*-
# targets: core.managers.theme_manager
"""``ThemeManager``（core/managers/theme_manager.py）单元测试。

V3 审计要点：该模块**不是单例**（无 ``_instance``/``_initialized``），
测试一律注入临时 ``SettingsManager`` 实例（tmp_path 绑定），绝不依赖
真实 ``data/settings.json``，也**不测"单例重置"**。

覆盖（方法矩阵：happy + boundary/error 各至少一条）：

* ``theme_changed``（str）/ ``colors_updated``(dict) 信号（模块 L25-26）
* ``toggle_theme`` —— 深/浅色切换、设置落盘、信号发射
* ``update_color`` —— 有效键更新 + 无效键 no-op + 辅助色加深重算
* ``get_theme_colors`` / ``get_darkened_auxiliary_colors`` / ``is_dark_theme``
* ``_darken_color`` —— 浅色加深 / 深色变浅 / 0%~100% 边界 / 255 钳位

``custom_design_color`` 属 SettingsManager.BASE_COLOR_KEYS（多出
``panel_background`` 也属之）与 components/theme_editor.py 的应用逻辑，
**不在此模块测试**。
"""

from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtCore import Signal, QTimer
from PySide6.QtGui import QColor

from freeassetfilter.core.managers.theme_manager import ThemeManager

from tests.support.qt_helpers import wait_for_signal

_THEME_KEYS: List[str] = [
    "accent_color",
    "secondary_color",
    "normal_color",
    "auxiliary_color",
    "base_color",
    "panel_background",
]


def _parse_hex(color_hex: str) -> int:
    """把 ``#RRGGBB`` 解析为整数（用于大小比较断言）。"""
    return int(color_hex[1:], 16)


# =============================================================================
# 类契约（非单例 + 信号声明）
# =============================================================================
class TestClassContract:
    """ThemeManager 类级契约"""

    def test_theme_manager_is_not_singleton(self, settings_manager: Any) -> None:
        """V3 修正：ThemeManager 应该可以创建多个独立实例。"""
        tm1: ThemeManager = ThemeManager(settings_manager)
        tm2: ThemeManager = ThemeManager(settings_manager)
        assert tm1 is not tm2
        assert tm1 is not None

    def test_signals_declared_on_class(self) -> None:
        """信号在类级声明（L25-26）：theme_changed(str) / colors_updated(dict)。"""
        assert isinstance(ThemeManager.theme_changed, Signal)
        assert isinstance(ThemeManager.colors_updated, Signal)
        assert hasattr(ThemeManager, "theme_changed")
        assert hasattr(ThemeManager, "colors_updated")

    def test_initialization_loads_theme_colors(self, settings_manager: Any) -> None:
        """初始化即从设置的 appearance.colors 加载全部主题颜色。"""
        tm: ThemeManager = ThemeManager(settings_manager)
        assert tm.settings_manager is settings_manager
        assert isinstance(tm.theme_colors, dict)
        for key in _THEME_KEYS:
            assert key in tm.theme_colors, f"缺少主题色键: {key}"
            assert tm.theme_colors[key].startswith("#")

    def test_injected_settings_respected(self, tmp_path, settings_manager: Any) -> None:
        """注入 SettingsManager 后，ThemeManager 读写都走该实例。"""
        settings_manager.set_setting("appearance.colors.accent_color", "#FF0000")
        tm: ThemeManager = ThemeManager(settings_manager)
        assert tm.theme_colors["accent_color"] == "#FF0000"


# =============================================================================
# toggle_theme
# =============================================================================
class TestToggleTheme:
    """主题切换"""

    def test_toggle_theme_dark_updates_settings(self, settings_manager: Any) -> None:
        """深色切换：设置 theme=dark，各基础色写入设置。"""
        tm: ThemeManager = ThemeManager(settings_manager)
        tm.toggle_theme(True)

        assert settings_manager.get_setting("appearance.theme") == "dark"
        assert settings_manager.get_setting("appearance.colors.base_color") == "#212121"
        assert tm.get_theme_colors()["base_color"] == "#212121"

    def test_toggle_theme_light_updates_settings(self, settings_manager: Any) -> None:
        """浅色切换：设置 theme=default，各基础色回到浅色值。"""
        tm: ThemeManager = ThemeManager(settings_manager)
        tm.toggle_theme(False)

        assert settings_manager.get_setting("appearance.theme") == "default"
        assert settings_manager.get_setting("appearance.colors.base_color") == "#FFFFFF"
        assert tm.theme_colors["base_color"] == "#FFFFFF"

    def test_toggle_theme_emits_both_signals(self, settings_manager: Any) -> None:
        """toggle_theme 返回颜色字典，并同步发射两个信号。"""
        tm: ThemeManager = ThemeManager(settings_manager)
        received_themes: List[str] = []
        received_colors: List[Dict[str, Any]] = []

        tm.theme_changed.connect(received_themes.append)
        tm.colors_updated.connect(received_colors.append)
        result: Dict[str, Any] = tm.toggle_theme(True)

        assert result == tm.theme_colors
        assert received_themes == ["dark"]
        assert len(received_colors) == 1
        assert received_colors[0]["base_color"] == "#212121"

    def test_toggle_theme_signals_via_wait_for_signal(
        self, qapp: Any, settings_manager: Any
    ) -> None:
        """异步触发 toggle_theme 后 wait_for_signal 能捕获信号（有界等待）。"""
        tm: ThemeManager = ThemeManager(settings_manager)
        QTimer.singleShot(0, lambda: tm.toggle_theme(False))

        assert wait_for_signal(tm.theme_changed, timeout_ms=3000) is True

    def test_toggle_theme_saves_settings_file(self, settings_manager: Any) -> None:
        """切换后同步写盘，文件内容可见 theme 变更。"""
        tm: ThemeManager = ThemeManager(settings_manager)
        tm.toggle_theme(True)

        # save_settings 是同步写盘，直接读取文件即可。
        import json

        assert settings_manager._settings_file is not None
        with open(settings_manager._settings_file, "r", encoding="utf-8") as f:
            saved: Dict[str, Any] = json.load(f)
        assert saved["appearance"]["theme"] == "dark"


# =============================================================================
# _darken_color
# =============================================================================
class TestDarkenColor:
    """辅助色加深 / 变浅算法"""

    def test_light_mode_darkens(self, settings_manager: Any) -> None:
        """浅色模式下颜色加深（数值下降）。"""
        tm: ThemeManager = ThemeManager(settings_manager)
        result: str = tm._darken_color("#808080", 10)
        assert result.startswith("#")
        assert _parse_hex(result) < _parse_hex("#808080")

    def test_dark_mode_lightens(self, settings_manager: Any) -> None:
        """深色模式下颜色变浅（数值上升）。"""
        settings_manager.set_setting("appearance.theme", "dark")
        tm: ThemeManager = ThemeManager(settings_manager)
        result: str = tm._darken_color("#212121", 10)
        assert result.startswith("#")
        assert _parse_hex(result) > _parse_hex("#212121")

    def test_boundary_percent_zero_no_change(self, settings_manager: Any) -> None:
        """边界：0% 不变。"""
        tm: ThemeManager = ThemeManager(settings_manager)
        assert tm._darken_color("#808080", 0).lower() == "#808080"

    def test_boundary_percent_100_black_in_light(self, settings_manager: Any) -> None:
        """边界：浅色模式 100% 变黑。"""
        tm: ThemeManager = ThemeManager(settings_manager)
        assert tm._darken_color("#FFFFFF", 100).lower() == "#000000"

    def test_clamp_at_255_in_dark_mode(self, settings_manager: Any) -> None:
        """边界：深色模式变浅时钳位到 255。"""
        settings_manager.set_setting("appearance.theme", "dark")
        tm: ThemeManager = ThemeManager(settings_manager)
        result: str = tm._darken_color("#FFFFFF", 100)
        assert result.lower() == "#ffffff"

    def test_invalid_color_returns_string_without_raise(self, settings_manager: Any) -> None:
        """错误输入：无效十六进制不抛异常，返回合法格式字符串。"""
        tm: ThemeManager = ThemeManager(settings_manager)
        for invalid in ("not_a_color", "", "#GGGGGG", "#FFF"):
            result: str = tm._darken_color(invalid, 10)
            assert isinstance(result, str)
            assert len(result) == 7

    def test_auxiliary_darkened_variants_computed(self, settings_manager: Any) -> None:
        """初始化时即计算出辅助色加深 2% / 5% 的版本。"""
        tm: ThemeManager = ThemeManager(settings_manager)
        assert tm.auxiliary_color_darker_2.startswith("#")
        assert tm.auxiliary_color_darker_5.startswith("#")
        d2, d5 = tm.get_darkened_auxiliary_colors()
        assert d2 == tm.auxiliary_color_darker_2
        assert d5 == tm.auxiliary_color_darker_5


# =============================================================================
# update_color
# =============================================================================
class TestUpdateColor:
    """单色更新"""

    def test_update_color_valid_key_updates_and_emits(self, settings_manager: Any) -> None:
        """有效键更新 theme_colors、设置并发射 colors_updated。"""
        tm: ThemeManager = ThemeManager(settings_manager)
        received: List[Dict[str, Any]] = []
        tm.colors_updated.connect(received.append)

        tm.update_color("base_color", "#101010")

        assert tm.theme_colors["base_color"] == "#101010"
        assert settings_manager.get_setting("appearance.colors.base_color") == "#101010"
        assert len(received) == 1
        assert received[0]["base_color"] == "#101010"

    def test_update_color_invalid_key_noop(self, settings_manager: Any) -> None:
        """边界：无效键不发信号、不改设置、不抛异常。"""
        tm: ThemeManager = ThemeManager(settings_manager)
        received: List[Dict[str, Any]] = []
        tm.colors_updated.connect(received.append)

        tm.update_color("not_a_real_key", "#00FF00")

        assert received == []
        assert settings_manager.get_setting(
            "appearance.colors.not_a_real_key", None
        ) is None

    def test_update_color_auxiliary_recomputes_darkers(self, settings_manager: Any) -> None:
        """更新辅助色时重新计算加深变体。"""
        tm: ThemeManager = ThemeManager(settings_manager)
        tm.update_color("auxiliary_color", "#808080")
        assert tm.auxiliary_color_darker_2 != tm.theme_colors["auxiliary_color"]
        # 浅色模式加深：darker_2 < auxiliary。
        assert _parse_hex(tm.auxiliary_color_darker_2) < _parse_hex("#808080")


# =============================================================================
# 查询类方法
# =============================================================================
class TestQueryMethods:
    """get_theme_colors / is_dark_theme / _load_theme_colors"""

    def test_get_theme_colors_matches_settings(self, settings_manager: Any) -> None:
        """get_theme_colors 返回设置内存中的 colors 字典相。"""
        tm: ThemeManager = ThemeManager(settings_manager)
        assert tm.get_theme_colors() == settings_manager.get_colors_dict()

    def test_get_theme_colors_dict_shape(self, settings_manager: Any) -> None:
        """返回字典包含全部 BASE_COLOR_KEYS 中的主题色区段。"""
        tm: ThemeManager = ThemeManager(settings_manager)
        colors: Dict[str, Any] = tm.get_theme_colors()
        assert isinstance(colors, dict)
        for key in _THEME_KEYS:
            assert key in colors

    def test_is_dark_theme_true_after_dark_toggle(self, settings_manager: Any) -> None:
        """happy：深色切换后 is_dark_theme 为 True。"""
        tm: ThemeManager = ThemeManager(settings_manager)
        tm.toggle_theme(True)
        assert tm.is_dark_theme() is True

    def test_is_dark_theme_false_by_default(self, settings_manager: Any) -> None:
        """边界：默认主题下 is_dark_theme 为 False。"""
        tm: ThemeManager = ThemeManager(settings_manager)
        assert tm.is_dark_theme() is False

    def test_load_theme_colors_picks_up_settings_change(
        self, settings_manager: Any
    ) -> None:
        """settings 颜色变更后 _load_theme_colors 能刷新内存。"""
        tm: ThemeManager = ThemeManager(settings_manager)
        settings_manager.set_setting("appearance.colors.accent_color", "#FF0000")
        tm._load_theme_colors()
        assert tm.theme_colors["accent_color"] == "#FF0000"


def test_qcolor_parsing() -> None:
    """QColor 对 #RRGGBB 的解析（辅助断言依赖的 Qt 事实）。"""
    color: QColor = QColor("#FF5733")
    assert color.red() == 255
    assert color.green() == 87
    assert color.blue() == 51