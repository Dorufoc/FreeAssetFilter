# -*- coding: utf-8 -*-
"""主题层单元测试（todo-23 批 3 / task-23）。

覆盖 ui/theme 下 2 个模块：
1. ``system_accent`` — 读取 Windows 系统强调色（AccentColorMenu / DWM
   AccentColor / AccentPalette / ColorizationColor）；全部数据源失败或
   颜色不可辨识时回退默认值。
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

import copy
import sys
from pathlib import Path

import pytest
from PySide6.QtGui import QColor

# 模块内部使用短路径导入（from theme.system_accent import ...），
# 需要 sopeek/ui 位于 sys.path。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "sopeek" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from sopeek.ui.theme import system_accent
from sopeek.ui.theme.theme_manager import ThemeManager, get_theme_manager

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
def _silence_all_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """切断全部真实数据源，避免宿主机强调色污染断言。

    Args:
        monkeypatch: pytest 打补丁工具。
    """
    monkeypatch.setattr(
        system_accent, "_get_accent_color_from_accent_registry", lambda: None
    )
    monkeypatch.setattr(
        system_accent, "_get_accent_color_from_dwm_accent", lambda: None
    )
    monkeypatch.setattr(system_accent, "_read_accent_palette", lambda: [])
    monkeypatch.setattr(system_accent, "_get_accent_color_from_dwm", lambda: None)
    monkeypatch.setattr(
        system_accent, "_get_accent_color_from_registry", lambda: None
    )


class TestSystemAccent:
    """获取系统强调色：数据源优先级、ABGR 解码与优雅降级。"""

    def test_get_system_accent_returns_hex(self) -> None:
        """真实环境调用返回可直接用于配色的 ``#RRGGBB`` 字符串。"""
        color = system_accent.get_system_accent_color()
        assert isinstance(color, str)
        assert color.startswith("#")
        assert len(color) == 7
        assert system_accent._is_usable_accent(color)

    def test_fallback_default_when_no_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """全部数据源失败 → 返回传入的默认值。"""
        _silence_all_sources(monkeypatch)
        assert system_accent.get_system_accent_color("#ABCDEF") == "#ABCDEF"

    def test_returns_accent_menu_first(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """强调色本体（AccentColorMenu）优先于 DWM 记录值。"""
        _silence_all_sources(monkeypatch)
        monkeypatch.setattr(
            system_accent, "_get_accent_color_from_accent_registry", lambda: "#3366CC"
        )
        monkeypatch.setattr(
            system_accent, "_get_accent_color_from_dwm_accent", lambda: "#445566"
        )
        assert system_accent.get_system_accent_color("#ABCDEF") == "#3366CC"

    def test_dwm_accent_used_when_menu_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AccentColorMenu 缺失时使用 DWM AccentColor（同为 ABGR）。"""
        _silence_all_sources(monkeypatch)
        monkeypatch.setattr(
            system_accent, "_get_accent_color_from_dwm_accent", lambda: "#303F4E"
        )
        assert system_accent.get_system_accent_color("#ABCDEF") == "#303F4E"

    def test_dark_colored_accent_uses_lighter_shade(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """过暗但有色的强调色 → 取同源色阶中最亮的可用档位。"""
        _silence_all_sources(monkeypatch)
        monkeypatch.setattr(
            system_accent, "_get_accent_color_from_accent_registry", lambda: "#101828"
        )
        monkeypatch.setattr(
            system_accent,
            "_read_accent_palette",
            lambda: ["#516B84", "#303F4E"],
        )
        assert system_accent.get_system_accent_color("#ABCDEF") == "#516B84"

    def test_black_accent_ignores_grayscale_palette(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """纯黑强调色的同源色阶全是灰阶 → 不取灰色，回退默认色。"""
        _silence_all_sources(monkeypatch)
        monkeypatch.setattr(
            system_accent, "_get_accent_color_from_accent_registry", lambda: "#000000"
        )
        monkeypatch.setattr(
            system_accent,
            "_read_accent_palette",
            lambda: ["#6B6B6B", "#141414"],
        )
        assert system_accent.get_system_accent_color("#ABCDEF") == "#ABCDEF"

    def test_black_accent_without_palette_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """纯黑强调色且无可用色阶 → 回退默认色，绝不返回纯黑。"""
        _silence_all_sources(monkeypatch)
        monkeypatch.setattr(
            system_accent, "_get_accent_color_from_accent_registry", lambda: "#000000"
        )
        assert system_accent.get_system_accent_color("#ABCDEF") == "#ABCDEF"

    def test_light_accent_uses_darkest_usable_shade(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """过亮但有色的强调色 → 取同源色阶中最暗的可用档位。"""
        _silence_all_sources(monkeypatch)
        monkeypatch.setattr(
            system_accent, "_get_accent_color_from_accent_registry", lambda: "#FFFFCC"
        )
        monkeypatch.setattr(
            system_accent,
            "_read_accent_palette",
            lambda: ["#AAAA44", "#444422"],
        )
        assert system_accent.get_system_accent_color("#ABCDEF") == "#444422"

    def test_invalid_default_normalized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """非法/不可辨识的默认值 → 使用内置兜底色 ``#007AFF``。"""
        _silence_all_sources(monkeypatch)
        assert system_accent.get_system_accent_color("not-a-color") == "#007AFF"
        assert system_accent.get_system_accent_color("#000000") == "#007AFF"

    def test_dwm_api_fallback_after_primary_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """主数据源与色阶均缺失 → 使用 DwmGetColorizationColor 近似值。"""
        _silence_all_sources(monkeypatch)
        monkeypatch.setattr(
            system_accent, "_get_accent_color_from_dwm", lambda: "#3366CC"
        )
        assert system_accent.get_system_accent_color("#ABCDEF") == "#3366CC"

    def test_registry_fallback_after_dwm_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DWM API 失败、ColorizationColor 注册表成功 → 返回注册表颜色。"""
        _silence_all_sources(monkeypatch)
        monkeypatch.setattr(
            system_accent, "_get_accent_color_from_registry", lambda: "#445566"
        )
        assert system_accent.get_system_accent_color("#ABCDEF") == "#445566"

    def test_registry_reader_without_winreg(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """winreg 缺失（非 Windows 守卫）→ 注册表读取安全返回 None 并回退默认。"""
        monkeypatch.setattr(system_accent, "winreg", None)
        assert system_accent._get_accent_color_from_registry() is None
        _silence_all_sources(monkeypatch)
        assert system_accent.get_system_accent_color("#ABCDEF") == "#ABCDEF"

    def test_abgr_decoding(self) -> None:
        """ABGR DWORD（0xAABBGGRR）→ 正确的 ``#RRGGBB``。"""
        assert system_accent._abgr_to_hex(0xFF4E3F30) == "#303F4E"
        assert system_accent._abgr_to_hex(0) is None
        assert system_accent._abgr_to_hex(0x00112233) is None

    def test_argb_decoding(self) -> None:
        """ARGB DWORD（0xAARRGGBB）→ 正确的 ``#RRGGBB``。"""
        assert system_accent._argb_to_hex(0xFF0078D4) == "#0078D4"
        assert system_accent._argb_to_hex(0) is None
        assert system_accent._argb_to_hex(0x00112233) is None

    def test_palette_parsing_ignores_sentinel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AccentPalette 只取前 7 条 RGB，忽略固定哨兵 ``88 17 98 00``。"""
        raw = bytes(
            [
                0x51, 0x6B, 0x84, 0xFF,
                0x43, 0x59, 0x6E, 0xFF,
                0x3A, 0x4C, 0x5E, 0xFF,
                0x30, 0x3F, 0x4E, 0xFF,
                0x26, 0x33, 0x3F, 0xFF,
                0x1D, 0x26, 0x2F, 0xFF,
                0x0F, 0x14, 0x19, 0xFF,
                0x88, 0x17, 0x98, 0x00,
            ]
        )
        monkeypatch.setattr(
            system_accent, "_read_registry_value", lambda subkey, name: raw
        )
        assert system_accent._read_accent_palette() == [
            "#516B84",
            "#43596E",
            "#3A4C5E",
            "#303F4E",
            "#26333F",
            "#1D262F",
            "#0F1419",
        ]


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


class TestSemanticTokens:
    """浅色语义色阶：深色取历史值、浅色分支生效、QSS 序列化与可读前景。"""

    def test_dark_tokens_match_historical_values(self) -> None:
        """深色 token 与历史口径一致（改浅色不得影响深色）。"""
        tm = ThemeManager()
        tm.set_theme("dark")
        assert tm.panel_fill == tm.alpha_of(tm.text, 5)
        assert tm.bar_fill == tm.alpha_of(tm.text, 5)
        assert tm.card_fill == tm.alpha_of(tm.surface, 85)
        assert tm.card_border == tm.alpha_of(tm.mid, 30)
        assert tm.control_border == tm.alpha_of(tm.mid, 30)
        assert tm.control_border_strong == tm.alpha_of(tm.mid, 50)
        assert tm.hover_veil == tm.alpha_of(tm.mid, 25)
        assert tm.track_fill == tm.alpha_of(tm.mid, 40)
        assert tm.divider == tm.alpha_of(tm.mid, 30)
        assert tm.scrim == tm.with_alpha(tm.black, 128)
        assert tm.text_secondary == tm.mid
        assert tm.text_hint == tm.alpha_of(tm.mid, 60)
        assert tm.text_disabled == tm.alpha_of(tm.mid, 40)
        assert tm.accent_text == tm.accent
        assert tm.scroll_handle_alphas == (102, 204, 255)

    def test_light_tokens_branch(self) -> None:
        """浅色表面使用亮色，同时与深色对应 token 保持相同 alpha。"""
        tm = ThemeManager()
        tm.set_theme("light")
        assert tm.panel_fill == tm.alpha_of(tm.surface, 5)
        assert tm.bar_fill == tm.alpha_of(tm.surface, 5)
        assert tm.card_fill == tm.alpha_of(tm.white, 85)
        assert tm.card_border == tm.alpha_of(tm.text, 30)
        assert tm.control_border == tm.alpha_of(tm.text, 30)
        assert tm.control_border_strong == tm.alpha_of(tm.text, 50)
        assert tm.panel_border == tm.alpha_of(tm.mid, 50)
        assert tm.hover_veil == tm.alpha_of(tm.text, 25)
        assert tm.subtle_fill == tm.alpha_of(tm.text, 20)
        assert tm.track_fill == tm.alpha_of(tm.text, 40)
        assert tm.divider == tm.alpha_of(tm.text, 30)
        assert tm.scrim == tm.with_alpha(tm.surface, 128)
        assert tm.text_secondary == tm.alpha_of(tm.text, 60)
        assert tm.text_hint == tm.alpha_of(tm.text, 55)
        assert tm.text_disabled == tm.alpha_of(tm.text, 38)
        assert tm.scroll_handle_alphas == (140, 191, 242)
        # 浅色强调文字：压暗以提升白底对比（值必须低于原 accent）
        assert tm.accent_text.value() < tm.accent.value()

    def test_qss_color_keeps_owner_alpha(self) -> None:
        """qss_color 按 QColor 自身 alpha 序列化（qss_rgba 需另传百分比）。"""
        tm = ThemeManager()
        tm.set_theme("light")
        assert tm.qss_color(tm.card_fill).startswith("rgba(255,255,255,")
        assert tm.qss_color(tm.surface).endswith(",1.000)")

    def test_readable_on_picks_contrast(self) -> None:
        """readable_on：浅底（warning）转近黑，深底保持白字。"""
        tm = ThemeManager()
        assert tm.readable_on(QColor("#f59e0b")).red() < 128
        assert tm.readable_on(QColor("#1a1a1a")).red() > 128
        assert tm.readable_on(QColor("#000000")).red() > 128


class TestThemeManagerAutoAccent:
    """启动期解析：``appearance.accent_color == "auto"`` 必须实时取系统色。"""

    @staticmethod
    def _install_fake_v2(
        monkeypatch: pytest.MonkeyPatch,
        accent: object,
        colors: dict | None = None,
    ) -> None:
        """把 ``_load_colors`` 使用的 SettingsManagerV2 替换为内存替身。

        Args:
            monkeypatch: pytest 打补丁工具。
            accent: ``appearance.accent_color`` 的模拟值。
            colors: ``appearance.colors`` 的模拟值；缺省为普通具体色。
        """
        import sopeek.core.managers.settings_manager_v2 as sv2_mod

        initial_colors = (
            copy.deepcopy(colors)
            if colors is not None
            else {"accent": {"primary": "#3A9DCB"}}
        )

        class _FakeV2:
            def load(self) -> dict:
                return {}

            def get(self, key_path: str, default: object = None) -> object:
                if key_path == "appearance.colors":
                    return initial_colors
                if key_path == "appearance.theme_mode":
                    return "dark"
                if key_path == "appearance.theme":
                    return "dark"
                if key_path == "appearance.accent_color":
                    return accent
                return default

            def reset_to_defaults(self) -> None:
                return None

        monkeypatch.setattr(sv2_mod, "SettingsManagerV2", _FakeV2)

    @staticmethod
    def _fresh_theme_manager() -> ThemeManager:
        """在干净单例状态下构造 ThemeManager（触发一次 ``_load_colors``）。"""
        ThemeManager._instance = None
        ThemeManager._initialized = False
        return ThemeManager()

    def test_auto_resolved_from_system(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``"auto"`` → 启动期调用系统强调色解析并写入 accent.primary。"""
        self._install_fake_v2(monkeypatch, "auto")
        monkeypatch.setattr(
            system_accent, "get_system_accent_color", lambda: "#3366CC"
        )
        tm = self._fresh_theme_manager()
        assert tm._colors["accent"]["primary"] == "#3366CC"

    def test_auto_is_case_insensitive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """历史/外部写入的 ``"AUTO"`` 同样按自动模式解析。"""
        self._install_fake_v2(monkeypatch, "AUTO")
        monkeypatch.setattr(
            system_accent, "get_system_accent_color", lambda: "#8A1538"
        )
        tm = self._fresh_theme_manager()
        assert tm._colors["accent"]["primary"] == "#8A1538"

    def test_restart_picks_latest_system_accent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """同一份 auto 配置，两次启动分别读取当时最新的系统强调色。"""
        self._install_fake_v2(monkeypatch, "auto")
        monkeypatch.setattr(
            system_accent, "get_system_accent_color", lambda: "#111111"
        )
        first = self._fresh_theme_manager()
        assert first._colors["accent"]["primary"] == "#111111"

        monkeypatch.setattr(
            system_accent, "get_system_accent_color", lambda: "#222222"
        )
        second = self._fresh_theme_manager()
        assert second._colors["accent"]["primary"] == "#222222"

    def test_concrete_accent_kept_without_system_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """手动预设色启动时原样保留，且不触发系统色读取。"""
        self._install_fake_v2(monkeypatch, "#8A1538")
        called: list[int] = []
        monkeypatch.setattr(
            system_accent,
            "get_system_accent_color",
            lambda: called.append(1) or "#3366CC",
        )
        tm = self._fresh_theme_manager()
        assert tm._colors["accent"]["primary"] == "#8A1538"
        assert called == []

    def test_colors_primary_auto_when_accent_key_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``accent_color`` 缺失但 colors.primary 为 auto 时同样解析（旧配置兼容）。"""
        self._install_fake_v2(monkeypatch, None, {"accent": {"primary": "auto"}})
        monkeypatch.setattr(
            system_accent, "get_system_accent_color", lambda: "#4477AA"
        )
        tm = self._fresh_theme_manager()
        assert tm._colors["accent"]["primary"] == "#4477AA"

    def test_invalid_accent_value_does_not_override_colors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """非字符串 accent_color（脏配置）不得污染 accent.primary。"""
        self._install_fake_v2(monkeypatch, {"bad": "value"})
        tm = self._fresh_theme_manager()
        assert tm._colors["accent"]["primary"] == "#3A9DCB"

    def test_legacy_theme_migrated_to_three_state_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """旧配置只有 appearance.theme、无 theme_mode 时仍能迁移为三态偏好。"""
        import sopeek.core.managers.settings_manager_v2 as sv2_mod

        class _LegacyV2:
            def load(self) -> dict:
                return {}

            def get(self, key_path: str, default: object = None) -> object:
                if key_path == "appearance.colors":
                    return {"accent": {"primary": "#3A9DCB"}}
                if key_path == "appearance.accent_color":
                    return "#3A9DCB"
                if key_path == "appearance.theme":
                    return "light"
                return default

            def reset_to_defaults(self) -> None:
                return None

        monkeypatch.setattr(sv2_mod, "SettingsManagerV2", _LegacyV2)
        tm = self._fresh_theme_manager()
        assert tm.get_theme_mode() == "light"
        assert tm.is_dark_theme() is False