# -*- coding: utf-8 -*-
"""主题层单元测试（todo-23 批 3 / task-23）。

覆盖 ui/theme 下 2 个模块：
1. ``system_accent`` — 读取 Windows 系统强调色；DWM / 注册表均失败时
   回退默认值。
2. ``theme_manager`` — 单例 ThemeManager 的构造/主题切换/信号发射/accent
   解析；``theme_changed`` / ``colors_updated`` 信号先 connect 再触发
   （monkeypatch.setattr raising=True 默认）。

单项测试内自带主题单例重置（conftest 的 reset_singletons 不覆盖
ui/theme/theme_manager 的 ``_instance`` / ``_initialized``，
见 conftest.py:112-116 的明确约定）。

验证命令：
    python -m pytest tests/unit/ui/theme/test_ui_theme.py --timeout 60 -q
"""

# targets: ui.theme.system_accent, ui.theme.theme_manager

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtGui import QColor

# 模块内部使用短路径导入（from theme.system_accent import ...），
# 需要 freeassetfilter/ui 位于 sys.path。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.theme import system_accent
from freeassetfilter.ui.theme.theme_manager import ThemeManager, get_theme_manager

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_theme_singleton() -> None:
    """每个测试前后重置 ui/theme 的 ThemeManager 单例。

    conftest 的 reset_singletons 明确不重置 ui/theme/theme_manager
    （只有带单例的 core 模块被覆盖）；本 fixture 补齐该清单缺口，
    保证 set_theme/toggle_theme 的跨测试污染不泄漏。

    Returns:
        None。
    """
    yield
    ThemeManager._instance = None
    ThemeManager._initialized = False


# =============================================================================
# ui.theme.system_accent
# =============================================================================
class TestSystemAccent:
    """获取系统强调色：真实调用 + DWM/注册表双失败回退。"""

    def test_get_system_accent_returns_hex(self) -> None:
        """真实环境调用返回 ``#RRGGBB`` 字符串（两边都尝试过仍回退默认）。"""
        color = system_accent.get_system_accent_color()
        assert isinstance(color, str)
        assert color.startswith("#")
        assert len(color) >= 7

    def test_fallback_default_when_no_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DWM 与注册表均失败 → 返回传入的默认值。"""
        monkeypatch.setattr(system_accent, "_get_accent_color_from_dwm", lambda: None)
        monkeypatch.setattr(
            system_accent, "_get_accent_color_from_registry", lambda: None
        )
        assert system_accent.get_system_accent_color("#ABCDEF") == "#ABCDEF"

    def test_returns_dwm_color_first(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DWM 成功 → 优先返回 DWM 读取的颜色。"""
        monkeypatch.setattr(
            system_accent, "_get_accent_color_from_dwm", lambda: "#112233"
        )
        monkeypatch.setattr(
            system_accent, "_get_accent_color_from_registry", lambda: "#445566"
        )
        assert system_accent.get_system_accent_color("#ABCDEF") == "#112233"

    def test_registry_fallback_after_dwm_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DWM 失败、注册表成功 → 返回注册表颜色。"""
        monkeypatch.setattr(system_accent, "_get_accent_color_from_dwm", lambda: None)
        monkeypatch.setattr(
            system_accent, "_get_accent_color_from_registry", lambda: "#445566"
        )
        assert system_accent.get_system_accent_color("#ABCDEF") == "#445566"


# =============================================================================
# ui.theme.theme_manager
# =============================================================================
class TestThemeManagerSingleton:
    """单例构造：``ThemeManager()`` 始终返回同一实例。"""

    def test_singleton_identity(self) -> None:
        """两次调用返回同一实例（``__new__`` 单例）。"""
        assert ThemeManager() is ThemeManager()

    def test_singleton_initialized(self) -> None:
        """构造后已加载配色，提供核心颜色 token。"""
        tm = ThemeManager()
        assert tm._initialized is True
        assert tm.surface is not None
        assert isinstance(tm.surface, QColor)


class TestThemeManagerToggle:
    """主题切换：set_theme / toggle_theme / is_dark_theme。"""

    def test_set_theme_dark_and_light(self) -> None:
        """set_theme 在两个合法值间切换 dark 标志。"""
        tm = ThemeManager()
        tm.set_theme("dark")
        assert tm.is_dark_theme() is True
        tm.set_theme("light")
        assert tm.is_dark_theme() is False
        tm.set_theme("dark")
        assert tm.is_dark_theme() is True

    def test_set_theme_invalid_ignored(self) -> None:
        """非法主题名被忽略，保持当前模式。"""
        tm = ThemeManager()
        tm.set_theme("light")
        tm.set_theme("neon")
        assert tm.is_dark_theme() is False

    def test_toggle_theme_returns_new_mode(self) -> None:
        """toggle_theme 返回切换后的主题名。"""
        tm = ThemeManager()
        tm.set_theme("dark")
        assert tm.toggle_theme() == "light"
        assert tm.is_dark_theme() is False
        assert tm.toggle_theme() == "dark"
        assert tm.is_dark_theme() is True


class TestThemeManagerSignals:
    """信号发射：先 connect 再触发。"""

    def test_theme_changed_emitted(self) -> None:
        """set_theme 发射 theme_changed(str)。"""
        tm = ThemeManager()
        received: list[str] = []
        tm.theme_changed.connect(received.append)
        tm.set_theme("light")
        assert received == ["light"]
        tm.set_theme("dark")
        assert received == ["light", "dark"]

    def test_colors_updated_emitted(self) -> None:
        """set_theme 发射 colors_updated(dict)。"""
        tm = ThemeManager()
        received: list[dict] = []
        tm.colors_updated.connect(lambda colors: received.append(colors))
        tm.set_theme("dark")
        assert len(received) == 1
        assert isinstance(received[0], dict)

    def test_accent_property_returns_qcolor(self) -> None:
        """accent 解析为 QColor（主强调色）。"""
        tm = ThemeManager()
        accent = tm.accent
        assert isinstance(accent, QColor)
        assert accent.isValid()


class TestGetThemeManager:
    """全局工厂：get_theme_manager 懒创建单例并复用。"""

    def test_returns_initialized_singleton(self) -> None:
        """返回同一 ThemeManager 实例（模块级单例复用）。"""
        tm1 = get_theme_manager()
        tm2 = get_theme_manager()
        assert tm1 is tm2
        assert isinstance(tm1, ThemeManager)