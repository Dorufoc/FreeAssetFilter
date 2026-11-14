"""
ThemeManager — Singleton that reads colors from SettingsManagerV2 and provides:
- Properties: surface, mid, text, black, transparent
- Accent: accent, accent_hover, accent_active, accent_alpha()
- Semantic: danger, warning, info, purple
- Light/dark semantic tokens（浅色语义色阶；深色取值与历史观感一致）:
  text_secondary / text_hint / text_disabled / accent_text、
  panel_fill / bar_fill / panel_border / card_fill / card_border、
  control_border / control_border_strong、hover_veil / subtle_fill / divider /
  track_fill / scrim / scroll_handle_alphas
- Utility: alpha_of(color, pct), with_alpha(color, alpha), qss_rgba(color, alpha_pct),
  qss_color(color), readable_on(background), _darken(color, factor)
- Legacy: get_color(path), get_component_colors(), get_common_color(),
          render_qss(), as_stylesheet()
"""

import copy
import os
import re
from typing import Optional, Dict, Any
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor

from sopeek.utils.app_logger import debug

# Mapping from old-style template token paths to new property names.
# Render_qss() uses this to resolve {{surface}}, {{accent.primary}} etc.
_TOKEN_TO_PROP: Dict[str, str] = {
    "surface": "surface",
    "fill": "fill",
    "mid": "mid",
    "text": "text",
    "black": "black",
    "transparent": "transparent",
    "accent": "accent",
    "accent.primary": "accent",
    "accent_hover": "accent_hover",
    "accent_active": "accent_active",
    "danger": "danger",
    "accent.danger": "danger",
    "warning": "warning",
    "accent.warning": "warning",
    "info": "info",
    "accent.info": "info",
    "purple": "purple",
    "accent.purple": "purple",
}

# 颜色解析缓存：hex 字符串 → QColor。主题颜色在主题切换前恒定不变，
# 拖拽 resize 等高频重绘路径（delegate/按钮 paintEvent）会反复访问
# tm.surface/mid/text 等属性，缓存可消除大量重复字符串解析。
# 注意：返回的 QColor 为共享对象，调用方如需修改必须先行拷贝
# （如 QColor(color) 后再 setAlpha），否则会污染缓存。
_HEX_COLOR_CACHE: Dict[str, Optional[QColor]] = {}

# alpha_of / accent_alpha / with_alpha 缓存：(rgba, alpha) → QColor（共享对象，同上）。
_ALPHA_COLOR_CACHE: Dict[tuple, QColor] = {}

# qss_rgba 缓存：(rgba, alpha_pct) → "rgba(r,g,b,a)" 字符串。
_QSS_RGBA_CACHE: dict[tuple, str] = {}

# qss_color 缓存：rgba → "rgba(r,g,b,a)" 字符串（alpha 取自 QColor 自身）。
_QSS_COLOR_CACHE: dict[int, str] = {}


def _qcolor_to_hex(color: QColor) -> str:
    """Convert QColor to #RRGGBB or #RRGGBBAA hex string."""
    if color.alpha() == 255:
        return color.name()
    return "#{:02x}{:02x}{:02x}{:02x}".format(
        color.red(), color.green(), color.blue(), color.alpha()
    )


class ThemeManager(QObject):
    """Singleton theme manager. Use ThemeManager() to get instance."""

    theme_changed = Signal(str)  # "dark" or "light" (实际生效值)
    colors_updated = Signal(dict)  # current colors dict
    theme_mode_changed = Signal(str)  # "light" | "dark" | "system" (用户偏好值)

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, theme_dir: Optional[str] = None):
        if self._initialized:
            return
        self._dark_mode = True
        self._theme_mode: str = "dark"
        self._initialized = True
        super().__init__()

        if theme_dir is None:
            theme_dir = os.path.join(os.path.dirname(__file__))

        self._theme_dir = theme_dir
        self._colors: Dict[str, Any] = {}
        self._load_colors()

    # ------------------------------------------------------------------
    # Color loading & resolution
    # ------------------------------------------------------------------

    def _load_colors(self):
        """从 SettingsManagerV2 加载配色配置（唯一配色配置源）。

        V2 的 ``DEFAULT_SETTINGS_V2`` 已内嵌全部默认配色，
        ``settings_v2.json`` 丢失时自动以此模板生成。

        ``appearance.accent_color == "auto"`` 时在启动期实时解析当前
        Windows 系统强调色（仅写入运行时 ``self._colors``，不落盘），
        保证每次实际启动都跟随系统强调色的最新值。
        """
        from sopeek.core.managers.settings_manager_v2 import SettingsManagerV2

        v2 = SettingsManagerV2()
        v2.load()
        colors = v2.get("appearance.colors", {})
        if not colors:
            v2.reset_to_defaults()
            colors = v2.get("appearance.colors", {})

        self._colors = colors
        # 三态偏好：appearance.theme_mode (light|dark|system)，缺失时由
        # 旧 appearance.theme (dark/light) 迁移，保证存量配置无感升级。
        raw_mode = v2.get("appearance.theme_mode", None)
        if raw_mode not in ("light", "dark", "system"):
            legacy = v2.get("appearance.theme", "dark")
            raw_mode = "dark" if legacy == "dark" else "light"
        self._theme_mode = raw_mode
        if self._theme_mode == "system":
            try:
                from sopeek.ui.theme.system_theme import (
                    get_windows_system_theme,
                )

                self._dark_mode = (
                    get_windows_system_theme() == "dark"
                )
            except Exception:
                self._dark_mode = (
                    v2.get("appearance.theme", "dark") == "dark"
                )
        else:
            self._dark_mode = (self._theme_mode == "dark")
        saved_accent = v2.get("appearance.accent_color")
        if (
            isinstance(saved_accent, str)
            and saved_accent
            and isinstance(self._colors.get("accent"), dict)
        ):
            self._colors["accent"]["primary"] = saved_accent

        # 若强调色为 "auto"，在启动期实时解析当前 Windows 系统强调色。
        # 解析结果只写入运行时配色，绝不回写 V2——否则下次启动会退化为
        # 固定颜色，无法跟随系统强调色变化。
        if isinstance(self._colors.get("accent"), dict):
            primary = self._colors["accent"].get("primary", "")
            if isinstance(primary, str) and primary.lower() == "auto":
                self._colors["accent"]["primary"] = self._resolve_system_accent()

    @staticmethod
    def _resolve_system_accent() -> str:
        """解析当前 Windows 系统强调色（启动期 ``"auto"`` 专用）。

        Returns:
            str: 可直接用于主题配色的 ``#RRGGBB``；
                :func:`get_system_accent_color` 自身保证合法与兜底。
        """
        try:
            from sopeek.ui.theme.system_accent import (
                get_system_accent_color,
            )
        except ImportError:  # 兼容短路径别名（sys.modules['theme']）
            from theme.system_accent import get_system_accent_color

        return get_system_accent_color()

    def _count_tokens(self, d: dict, prefix: str = "") -> int:
        """Count leaf (string) values in nested dict."""
        count = 0
        for k, v in d.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                count += self._count_tokens(v, path)
            elif isinstance(v, str) and v.startswith("#"):
                count += 1
        return count

    def _resolve_path(
        self, path: str, data: Optional[Dict[str, Any]] = None
    ) -> Optional[Any]:
        """Resolve dot-notation path like 'button.primary.bg' to value.

        When *data* is provided, resolve against that dict instead of
        ``self._colors``.  Used internally for backward-compat fallback.
        """
        parts = path.split(".")
        current = data if data is not None else self._colors
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    @staticmethod
    def _parse_hex_color(value: str) -> Optional[QColor]:
        """
        Parse a hex color string to QColor.

        PySide6's QColor(str) interprets 8-digit hex as #AARRGGBB (Qt 5 legacy),
        but colors.json stores colors as #RRGGBBAA (web standard).
        This method handles both correctly.

        Results are cached (theme colors are constant until the next
        ``set_theme``); the returned QColor is a shared object and must be
        copied before modification (e.g. ``QColor(color)`` then ``setAlpha``).
        """
        cached = _HEX_COLOR_CACHE.get(value)
        if value in _HEX_COLOR_CACHE:
            return cached
        s = value.lstrip("#").strip()
        if len(s) == 8:
            # #RRGGBBAA → parse manually (QColor would interpret as #AARRGGBB)
            try:
                r = int(s[0:2], 16)
                g = int(s[2:4], 16)
                b = int(s[4:6], 16)
                a = int(s[6:8], 16)
                color = QColor(r, g, b, a)
            except (ValueError, IndexError):
                color = None
        else:
            # 6-digit, 3-digit, or named colors → delegate to QColor
            color = QColor(value)
        _HEX_COLOR_CACHE[value] = color
        return color

    @classmethod
    def _clear_color_cache(cls) -> None:
        """清空颜色解析缓存（主题/配色变更时调用）。"""
        _HEX_COLOR_CACHE.clear()
        _ALPHA_COLOR_CACHE.clear()
        _QSS_RGBA_CACHE.clear()
        _QSS_COLOR_CACHE.clear()

    # ------------------------------------------------------------------
    # New property-based API — surface / fill / mid / text / black / transparent
    # All gray levels sourced from V2 appearance.colors.gray / gray_light.

    @property
    def surface(self) -> QColor:
        """Primary surface background color (gray.g1 / gray_light.g1)."""
        key = "gray" if self._dark_mode else "gray_light"
        return self._parse_hex_color(self._colors[key]["g1"])

    @property
    def fill(self) -> QColor:
        """Base space fill color (gray.g2 / gray_light.g2) for card backgrounds, elevated panels."""
        key = "gray" if self._dark_mode else "gray_light"
        return self._parse_hex_color(self._colors[key]["g2"])

    @property
    def mid(self) -> QColor:
        """Mid-tone gray (gray.g3 / gray_light.g3) for secondary content."""
        key = "gray" if self._dark_mode else "gray_light"
        return self._parse_hex_color(self._colors[key]["g3"])

    @property
    def text(self) -> QColor:
        """Primary text color (gray.g4 / gray_light.g4)."""
        key = "gray" if self._dark_mode else "gray_light"
        return self._parse_hex_color(self._colors[key]["g4"])

    @property
    def black(self) -> QColor:
        """Pure black (gray.black / gray_light.black)."""
        key = "gray" if self._dark_mode else "gray_light"
        return self._parse_hex_color(self._colors[key]["black"])

    @property
    def transparent(self) -> QColor:
        """Fully transparent (0, 0, 0, 0)."""
        return QColor(0, 0, 0, 0)

    @property
    def white(self) -> QColor:
        """Pure white (#FFFFFF) — 用于强调按钮文字等固定白色场景。"""
        return QColor("#FFFFFF")

    # ------------------------------------------------------------------
    # Semantic tokens — 浅深模式使用相同 alpha，仅反转语义颜色亮度。
    #
    # 背景底板可能来自 Mica、图像或简约渐变，因此面板、卡片、描边及
    # 各类叠层必须保持统一透明度口径，避免浅色模式的半透明区域变成
    # 过实的白块。文字和滚动条手柄属于可读性专用参数，保留独立配置。
    #
    # 全部返回缓存共享 QColor：调用方如需改 alpha 必须先 QColor() 拷贝。
    # ------------------------------------------------------------------

    @property
    def text_secondary(self) -> QColor:
        """次要文字（路径、标签、副标题、计数）：浅色 text ≈60%（≈4.5:1），深色 mid。"""
        if self._dark_mode:
            return self.mid
        return self.alpha_of(self.text, 60)

    @property
    def text_hint(self) -> QColor:
        """提示/占位文字（空状态、placeholder、说明）：浅色 text ≈55%，深色 mid ≈60%。"""
        if self._dark_mode:
            return self.alpha_of(self.mid, 60)
        return self.alpha_of(self.text, 55)

    @property
    def text_disabled(self) -> QColor:
        """禁用文字：浅色 text ≈38%，深色 mid ≈40%。"""
        if self._dark_mode:
            return self.alpha_of(self.mid, 40)
        return self.alpha_of(self.text, 38)

    @property
    def accent_text(self) -> QColor:
        """用于文字/小图标的强调色：浅色压暗到 ≈4.9:1，深色原 accent。"""
        if self._dark_mode:
            return self.accent
        return self._darken(self.accent, 0.72)

    @property
    def panel_fill(self) -> QColor:
        """三栏/面板底：两种模式保持 5% alpha，仅反转颜色亮度。"""
        if self._dark_mode:
            return self.alpha_of(self.text, 5)
        return self.alpha_of(self.surface, 5)

    @property
    def bar_fill(self) -> QColor:
        """面板内工具栏/底栏底：两种模式保持 5% alpha。"""
        if self._dark_mode:
            return self.alpha_of(self.text, 5)
        return self.alpha_of(self.surface, 5)

    @property
    def card_fill(self) -> QColor:
        """卡片底：两种模式保持 85% alpha，仅反转颜色亮度。"""
        if self._dark_mode:
            return self.alpha_of(self.surface, 85)
        return self.alpha_of(self.white, 85)

    @property
    def card_border(self) -> QColor:
        """卡片描边：两种模式保持 30% alpha。"""
        if self._dark_mode:
            return self.alpha_of(self.mid, 30)
        return self.alpha_of(self.text, 30)

    @property
    def control_border(self) -> QColor:
        """输入类控件默认描边：两种模式保持 30% alpha。"""
        if self._dark_mode:
            return self.alpha_of(self.mid, 30)
        return self.alpha_of(self.text, 30)

    @property
    def control_border_strong(self) -> QColor:
        """输入类控件 hover/focus 描边：两种模式保持 50% alpha。"""
        if self._dark_mode:
            return self.alpha_of(self.mid, 50)
        return self.alpha_of(self.text, 50)

    @property
    def panel_border(self) -> QColor:
        """主区域面板描边：两种模式均使用 mid，保持 50% alpha。"""
        return self.alpha_of(self.mid, 50)

    @property
    def hover_veil(self) -> QColor:
        """悬停覆盖层：两种模式保持 25% alpha。"""
        if self._dark_mode:
            return self.alpha_of(self.mid, 25)
        return self.alpha_of(self.text, 25)

    @property
    def subtle_fill(self) -> QColor:
        """轻量填充：两种模式保持 20% alpha。"""
        if self._dark_mode:
            return self.alpha_of(self.mid, 20)
        return self.alpha_of(self.text, 20)

    @property
    def divider(self) -> QColor:
        """分隔线：两种模式保持 30% alpha。"""
        if self._dark_mode:
            return self.alpha_of(self.mid, 30)
        return self.alpha_of(self.text, 30)

    @property
    def track_fill(self) -> QColor:
        """轨道/滑块槽/未选中底：两种模式保持 40% alpha。"""
        if self._dark_mode:
            return self.alpha_of(self.mid, 40)
        return self.alpha_of(self.text, 40)

    @property
    def scrim(self) -> QColor:
        """加载遮罩底板：浅深模式保持约 50% alpha，仅反转颜色亮度。"""
        if self._dark_mode:
            return self.with_alpha(self.black, 128)
        return self.with_alpha(self.surface, 128)

    @property
    def scroll_handle_alphas(self) -> tuple:
        """滚动条手柄三档 alpha（idle, hover, pressed）：浅色整体更实一档。"""
        if self._dark_mode:
            return (102, 204, 255)  # 40 / 80 / 100（历史值）
        return (140, 191, 242)      # 55 / 75 / 95

    @staticmethod
    def qss_color(color: QColor) -> str:
        """Serialize *color* as a QSS ``rgba(r,g,b,a)`` string from its own alpha.

        与 :meth:`qss_rgba` 的区别：alpha 直接取 QColor 自身（0-255 → 0-1），
        适用于语义 token（其 alpha 已烘焙在颜色里）直接落到 QSS 的场景。
        """
        cached = _QSS_COLOR_CACHE.get(color.rgba())
        if cached is not None:
            return cached
        s = (
            f"rgba({color.red()},{color.green()},{color.blue()},"
            f"{color.alpha() / 255:.3f})"
        )
        _QSS_COLOR_CACHE[color.rgba()] = s
        return s

    @staticmethod
    def readable_on(background: QColor) -> QColor:
        """返回在 *background* 上可读的前景色（固定白或近黑）。

        阈值取 WCAG 相对亮度 ``0.35``：白字对比 ``1.05/(L+0.05) ≥ 2.6:1``
        时保持白字（与主按钮"强调色实底 + 白字"的产品口径一致），
        更亮的底色（如 warning #f59e0b L≈0.47，白字仅 2.0:1）自动转近黑
        （≈8:1）。用于语义色实底（勾选符号 / badge / tag 实底）等
        "底色决定前景"场景，避免浅色 accent 下固定白字不可读。
        """
        def _lin(v: int) -> float:
            c = v / 255.0
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        luminance = (
            0.2126 * _lin(background.red())
            + 0.7152 * _lin(background.green())
            + 0.0722 * _lin(background.blue())
        )
        if luminance >= 0.35:
            return QColor(26, 26, 26)
        return QColor(255, 255, 255)

    # ------------------------------------------------------------------
    # Theme switching
    # ------------------------------------------------------------------

    def set_theme(self, theme: str) -> None:
        """设置手动主题并同步偏好（顶栏切换入口）。

        等价于 ``set_theme_mode(theme)`` 的手动分支：偏好切为对应手动值，
        立即生效并广播。跟随系统模式下的顶栏点击应走此方法，从而自动
        脱离跟随（切为白天/夜晚）。

        Args:
            theme: 目标主题，"dark" 或 "light"，非法值直接忽略。
        """
        if theme not in ("dark", "light"):
            return
        self.set_theme_mode(theme)

    def toggle_theme(self) -> str:
        """在实际生效值上翻转（浅色↔深色），并固定为手动偏好。

        Returns:
            翻转后的实际主题名。
        """
        new_theme = "light" if self._dark_mode else "dark"
        self.set_theme(new_theme)
        return new_theme

    def is_dark_theme(self) -> bool:
        """返回当前实际生效是否为深色（跟随模式下为系统解析结果）。

        Returns:
            深色返回 True，否则返回 False。
        """
        return self._dark_mode

    def get_theme_mode(self) -> str:
        """返回用户主题偏好。

        Returns:
            偏好值："light"（白天）| "dark"（夜晚）| "system"（跟随系统）。
        """
        if self._theme_mode not in ("light", "dark", "system"):
            return "dark" if self._dark_mode else "light"
        return self._theme_mode

    def effective_theme(self) -> str:
        """返回当前实际生效主题。

        Returns:
            "dark" 或 "light"。
        """
        return "dark" if self._dark_mode else "light"

    def set_theme_mode(self, mode: str) -> None:
        """设置主题偏好并立即生效。

        - 手动模式（light/dark）：直接生效；
        - 跟随系统（system）：实时读取 Windows 系统主题后生效。

        每次合法调用均发射 ``theme_mode_changed``（偏好值）、
        ``theme_changed``（实际生效值）与 ``colors_updated``——与历史
        ``set_theme`` 的"调用即广播"契约一致，订阅者幂等刷新即可。

        Args:
            mode: 偏好值，"light" | "dark" | "system"，非法值直接忽略。
        """
        if mode not in ("light", "dark", "system"):
            return
        self._theme_mode = mode
        if mode == "system":
            try:
                from sopeek.ui.theme.system_theme import (
                    get_windows_system_theme,
                )

                self._dark_mode = (
                    get_windows_system_theme() == "dark"
                )
            except Exception as exc:
                debug(f"读取系统主题失败（保持当前明暗值）：{exc}")
        else:
            self._dark_mode = (mode == "dark")
        self._clear_color_cache()
        self.theme_mode_changed.emit(mode)
        self.theme_changed.emit(self.effective_theme())
        self.colors_updated.emit(self._colors)

    def refresh_system_theme(self) -> bool:
        """跟随模式下重新读取系统主题并应用。

        仅当偏好为 system 且系统实际值发生变化时翻转生效值。

        Returns:
            发生切换返回 True，否则返回 False。
        """
        if self._theme_mode != "system":
            return False
        try:
            from sopeek.ui.theme.system_theme import (
                get_windows_system_theme,
            )

            system_theme = get_windows_system_theme()
        except Exception:
            return False
        if system_theme not in ("dark", "light"):
            return False
        should_dark = (system_theme == "dark")
        if should_dark == self._dark_mode:
            return False
        self._dark_mode = should_dark
        self._clear_color_cache()
        self.theme_changed.emit(system_theme)
        self.colors_updated.emit(self._colors)
        return True

    def apply_system_theme(self, theme: str) -> bool:
        """应用外部传入的系统主题值（Watcher 回调入口）。

        仅在偏好为 system 时生效，避免手动模式被系统变化冲掉。

        Args:
            theme: 系统主题值，"dark" 或 "light"。

        Returns:
            发生切换返回 True，否则返回 False。
        """
        if self._theme_mode != "system":
            return False
        if theme not in ("dark", "light"):
            return False
        should_dark = (theme == "dark")
        if should_dark == self._dark_mode:
            return False
        self._dark_mode = should_dark
        self._clear_color_cache()
        self.theme_changed.emit(theme)
        self.colors_updated.emit(self._colors)
        return True

    # ------------------------------------------------------------------
    # Accent properties (loaded from V2 appearance.colors.accent)
    # ------------------------------------------------------------------

    @property
    def accent(self) -> QColor:
        """Primary accent color from colors.json."""
        return self._parse_hex_color(self._colors["accent"]["primary"])

    @property
    def accent_hover(self) -> QColor:
        """Accent at 90 % HSV brightness (hover state)."""
        return self._darken(self.accent, 0.9)

    @property
    def accent_active(self) -> QColor:
        """Accent at 80 % HSV brightness (active / pressed state)."""
        return self._darken(self.accent, 0.8)

    def accent_alpha(self, alpha: int) -> QColor:
        """Accent colour at a given alpha value (0–255)."""
        key = (self.accent.rgba(), max(0, min(255, alpha)))
        cached = _ALPHA_COLOR_CACHE.get(key)
        if cached is not None:
            return cached
        c = QColor(self.accent)
        c.setAlpha(key[1])
        _ALPHA_COLOR_CACHE[key] = c
        return c

    # ------------------------------------------------------------------
    # Semantic colours
    # ------------------------------------------------------------------

    @property
    def danger(self) -> QColor:
        """Semantic danger / error colour."""
        return self._parse_hex_color(self._colors["accent"]["danger"])

    @property
    def warning(self) -> QColor:
        """Semantic warning colour."""
        return self._parse_hex_color(self._colors["accent"]["warning"])

    @property
    def info(self) -> QColor:
        """Semantic info colour."""
        return self._parse_hex_color(self._colors["accent"]["info"])

    @property
    def purple(self) -> QColor:
        """Semantic purple colour."""
        return self._parse_hex_color(self._colors["accent"]["purple"])

    # ------------------------------------------------------------------
    # Colour utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _darken(color: QColor, factor: float) -> QColor:
        """Return a darkened copy of *color* scaled by *factor* (0.0–1.0).

        Uses HSV brightness so the hue and saturation are preserved.
        """
        return QColor.fromHsv(
            color.hue(), color.saturation(), int(color.value() * factor)
        )

    @staticmethod
    def alpha_of(color: QColor, pct: float) -> QColor:
        """Return *color* at a given opacity percentage (0–100).

        Cached by (rgba, alpha): shared result object — callers must copy
        before mutating.
        """
        alpha = max(0, min(255, int(pct * 2.55)))
        key = (color.rgba(), alpha)
        cached = _ALPHA_COLOR_CACHE.get(key)
        if cached is not None:
            return cached
        c = QColor(color)
        c.setAlpha(alpha)
        _ALPHA_COLOR_CACHE[key] = c
        return c

    @staticmethod
    def with_alpha(color: QColor, alpha: int) -> QColor:
        """Return *color* with an absolute alpha value (0–255).

        Same construction as ``QColor(r, g, b, alpha)`` but cached by
        (rgba, alpha): shared result object — callers must copy
        before mutating.
        """
        alpha = max(0, min(255, int(alpha)))
        key = (color.rgba(), alpha)
        cached = _ALPHA_COLOR_CACHE.get(key)
        if cached is not None:
            return cached
        c = QColor(color)
        c.setAlpha(alpha)
        _ALPHA_COLOR_CACHE[key] = c
        return c

    @staticmethod
    def qss_rgba(color: QColor, alpha_pct: float) -> str:
        """Serialize *color* as a QSS ``rgba(r,g,b,a)`` string.

        *alpha_pct* is a percentage (0–100); the emitted alpha is the
        ``alpha_pct / 100`` fraction (e.g. ``5`` → ``"0.05"``).
        """
        key = (color.rgba(), alpha_pct)
        cached = _QSS_RGBA_CACHE.get(key)
        if cached is not None:
            return cached
        s = (
            f"rgba({color.red()},{color.green()},{color.blue()},"
            f"{alpha_pct / 100})"
        )
        _QSS_RGBA_CACHE[key] = s
        return s

    # ------------------------------------------------------------------
    # Legacy backward-compatible API
    # ------------------------------------------------------------------

    def get_color(self, path: str) -> Optional[QColor]:
        """
        Resolve a dot-notation path to a QColor from the current color dict.

        All colour data is sourced from SettingsManagerV2 at load time.

        Returns None if path not found.
        """
        value = self._resolve_path(path)
        if value is None or not isinstance(value, str):
            return None
        try:
            return self._parse_hex_color(value)
        except Exception:
            return None

    def get_component_colors(self, component: str) -> Dict[str, Any]:
        """Get the entire colour dict for a component (e.g. 'button')."""
        result = self._resolve_path(component)
        return result or {}

    def get_common_color(self, category: str, token: str) -> Optional[QColor]:
        """Shorthand for ``get_color(f'common.{category}.{token}')``."""
        return self.get_color(f"common.{category}.{token}")

    # ------------------------------------------------------------------
    # 公共写入 API（审查 3.1#23：替代外部直写 _colors 的私有访问）
    # ------------------------------------------------------------------

    def set_color(self, path: str, value: str) -> bool:
        """按点号路径写入配色值并广播 ``colors_updated``。

        Args:
            path: 点号路径，如 ``"accent.primary"``。
            value: 颜色值（``"#RRGGBB"`` / ``"#RRGGBBAA"``）。

        Returns:
            写入成功返回 True；路径不存在 / value 为空返回 False。
        """
        if not path or not value:
            return False
        parts = [part for part in str(path).split(".") if part]
        if not parts:
            return False
        node: Any = self._colors
        for part in parts[:-1]:
            child = node.get(part) if isinstance(node, dict) else None
            if not isinstance(child, dict):
                return False
            node = child
        node[parts[-1]] = value
        self.colors_updated.emit(self._colors)
        return True

    def replace_colors(self, colors: Dict[str, Any]) -> None:
        """整体合并替换配色字典并广播（事务回滚等场景）。

        与直接 ``self._colors.update(colors)`` 等价，但不暴露私有字典。
        """
        if not isinstance(colors, dict):
            return
        self._colors.update(colors)
        self.colors_updated.emit(self._colors)

    def snapshot_colors(self) -> Dict[str, Any]:
        """返回当前配色字典的深拷贝（事务暂存 / 回滚快照用）。"""
        return copy.deepcopy(self._colors)

    def render_qss(self, template_path: Optional[str] = None) -> str:
        """
        Read a QSS template file and replace ``{{TOKEN.PATH}}`` placeholders
        with actual color values.

        Resolution order:
        1. ``self._colors`` (loaded from SettingsManagerV2 at init)
        2. New property-based tokens (``{{surface}}``, ``{{accent.primary}}``, …)

        If template_path is None, looks for 'global.qss.tpl' in the theme dir.
        If template file doesn't exist, returns empty string.
        """
        if template_path is None:
            template_path = os.path.join(
                os.path.dirname(self._theme_dir),
                "styles", "global.qss.tpl"
            )
            alt_path = os.path.join(self._theme_dir, "global.qss.tpl")
            if not os.path.exists(template_path) and os.path.exists(alt_path):
                template_path = alt_path

        if not os.path.exists(template_path):
            return ""

        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()

        def replace_token(match):
            token_path = match.group(1)

            # 1. Current colour dict (contains both simplified + full colours)
            value = self._resolve_path(token_path)
            if value is not None and isinstance(value, str):
                return value

            # 2. New property tokens ({{surface}}, {{accent.primary}}, …)
            prop_name = _TOKEN_TO_PROP.get(token_path)
            if prop_name is not None:
                prop_value = getattr(self, prop_name, None)
                if isinstance(prop_value, QColor):
                    return _qcolor_to_hex(prop_value)

            return match.group(0)  # leave unchanged if not found

        rendered = re.sub(r"\{\{([\w.]+)\}\}", replace_token, content)
        return rendered

    def as_stylesheet(self) -> str:
        """Convenience: render the default global QSS template."""
        return self.render_qss()

    # ------------------------------------------------------------------
    # SVG color processing
    # ------------------------------------------------------------------

    _RE_FILL_WHITE = re.compile(r'fill="#FFFFFF"', re.IGNORECASE)
    _RE_FILL_WHITE_SHORT = re.compile(r'fill="#FFF"', re.IGNORECASE)
    _RE_FILL_BLACK = re.compile(r'fill="#000000"', re.IGNORECASE)
    _RE_FILL_BLACK_SHORT = re.compile(r'fill="#000"', re.IGNORECASE)
    _RE_STROKE_WHITE = re.compile(r'stroke="#FFFFFF"', re.IGNORECASE)
    _RE_STROKE_WHITE_SHORT = re.compile(r'stroke="#FFF"', re.IGNORECASE)
    _RE_STROKE_BLACK = re.compile(r'stroke="#000000"', re.IGNORECASE)
    _RE_STROKE_BLACK_SHORT = re.compile(r'stroke="#000"', re.IGNORECASE)
    _RE_CSS_FILL_WHITE = re.compile(r'(fill:\s*)#FFFFFF', re.IGNORECASE)
    _RE_CSS_FILL_WHITE_SHORT = re.compile(r'(fill:\s*)#FFF\b', re.IGNORECASE)
    _RE_CSS_FILL_BLACK = re.compile(r'(fill:\s*)#000000', re.IGNORECASE)
    _RE_CSS_FILL_BLACK_SHORT = re.compile(r'(fill:\s*)#000\b', re.IGNORECASE)
    _RE_CSS_STROKE_WHITE = re.compile(r'(stroke:\s*)#FFFFFF', re.IGNORECASE)
    _RE_CSS_STROKE_WHITE_SHORT = re.compile(r'(stroke:\s*)#FFF\b', re.IGNORECASE)
    _RE_CSS_STROKE_BLACK = re.compile(r'(stroke:\s*)#000000', re.IGNORECASE)
    _RE_CSS_STROKE_BLACK_SHORT = re.compile(r'(stroke:\s*)#000\b', re.IGNORECASE)

    def process_svg(self, svg_content: str) -> str:
        """Pre-process SVG XML, replacing #FFF→surface (G1) and #000→text (G4).

        Uses the current theme mode (dark/light) to pick the correct gray
        values, so icons automatically adapt to theme changes.

        Args:
            svg_content: Raw SVG XML string.

        Returns:
            Processed SVG string with colors replaced.
        """
        surface_hex = self.surface.name()   # G1: #1a1a1a (dark) / #f5f5f5 (light)
        text_hex = self.text.name()         # G4: #e8e8e8 (dark) / #1a1a1a (light)

        # fill="#FFFFFF" → fill="{surface_hex}"
        svg_content = self._RE_FILL_WHITE.sub(f'fill="{surface_hex}"', svg_content)
        svg_content = self._RE_FILL_WHITE_SHORT.sub(f'fill="{surface_hex}"', svg_content)
        # fill="#000000" → fill="{text_hex}"
        svg_content = self._RE_FILL_BLACK.sub(f'fill="{text_hex}"', svg_content)
        svg_content = self._RE_FILL_BLACK_SHORT.sub(f'fill="{text_hex}"', svg_content)

        # stroke="#FFFFFF" → stroke="{surface_hex}"
        svg_content = self._RE_STROKE_WHITE.sub(f'stroke="{surface_hex}"', svg_content)
        svg_content = self._RE_STROKE_WHITE_SHORT.sub(f'stroke="{surface_hex}"', svg_content)
        # stroke="#000000" → stroke="{text_hex}"
        svg_content = self._RE_STROKE_BLACK.sub(f'stroke="{text_hex}"', svg_content)
        svg_content = self._RE_STROKE_BLACK_SHORT.sub(f'stroke="{text_hex}"', svg_content)

        # CSS fill: #FFFFFF → fill: {surface_hex}
        svg_content = self._RE_CSS_FILL_WHITE.sub(rf'\1{surface_hex}', svg_content)
        svg_content = self._RE_CSS_FILL_WHITE_SHORT.sub(rf'\1{surface_hex}', svg_content)
        # CSS fill: #000000 → fill: {text_hex}
        svg_content = self._RE_CSS_FILL_BLACK.sub(rf'\1{text_hex}', svg_content)
        svg_content = self._RE_CSS_FILL_BLACK_SHORT.sub(rf'\1{text_hex}', svg_content)

        # CSS stroke: #FFFFFF → stroke: {surface_hex}
        svg_content = self._RE_CSS_STROKE_WHITE.sub(rf'\1{surface_hex}', svg_content)
        svg_content = self._RE_CSS_STROKE_WHITE_SHORT.sub(rf'\1{surface_hex}', svg_content)
        # CSS stroke: #000000 → stroke: {text_hex}
        svg_content = self._RE_CSS_STROKE_BLACK.sub(rf'\1{text_hex}', svg_content)
        svg_content = self._RE_CSS_STROKE_BLACK_SHORT.sub(rf'\1{text_hex}', svg_content)

        return svg_content


# Module-level singleton getter
_theme_manager: Optional[ThemeManager] = None


def get_theme_manager() -> ThemeManager:
    global _theme_manager
    if _theme_manager is None:
        _theme_manager = ThemeManager()
    return _theme_manager
