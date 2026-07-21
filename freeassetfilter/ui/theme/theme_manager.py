"""
ThemeManager — Singleton that reads colors from SettingsManagerV2 and provides:
- Properties: surface, mid, text, black, transparent
- Accent: accent, accent_hover, accent_active, accent_alpha()
- Semantic: danger, warning, info, purple
- Utility: alpha_of(color, pct), _darken(color, factor)
- Legacy: get_color(path), get_component_colors(), get_common_color(),
          render_qss(), as_stylesheet()
"""

import os
import re
from typing import Optional, Dict, Any
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor

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


def _qcolor_to_hex(color: QColor) -> str:
    """Convert QColor to #RRGGBB or #RRGGBBAA hex string."""
    if color.alpha() == 255:
        return color.name()
    return "#{:02x}{:02x}{:02x}{:02x}".format(
        color.red(), color.green(), color.blue(), color.alpha()
    )


class ThemeManager(QObject):
    """Singleton theme manager. Use ThemeManager() to get instance."""

    theme_changed = Signal(str)  # "dark" or "light"
    colors_updated = Signal(dict)  # current colors dict

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
        """
        from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2

        v2 = SettingsManagerV2()
        v2.load()
        colors = v2.get("appearance.colors", {})
        if not colors:
            v2.reset_to_defaults()
            colors = v2.get("appearance.colors", {})

        self._colors = colors
        self._dark_mode = (v2.get("appearance.theme", "dark") == "dark")
        saved_accent = v2.get("appearance.accent_color")
        if saved_accent and isinstance(self._colors.get("accent"), dict):
            self._colors["accent"]["primary"] = saved_accent

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
        """
        s = value.lstrip("#").strip()
        if len(s) == 8:
            # #RRGGBBAA → parse manually (QColor would interpret as #AARRGGBB)
            try:
                r = int(s[0:2], 16)
                g = int(s[2:4], 16)
                b = int(s[4:6], 16)
                a = int(s[6:8], 16)
                return QColor(r, g, b, a)
            except (ValueError, IndexError):
                return None
        # 6-digit, 3-digit, or named colors → delegate to QColor
        return QColor(value)

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
    # Theme switching
    # ------------------------------------------------------------------

    def set_theme(self, theme: str) -> None:
        """Set theme mode: 'dark' or 'light'."""
        if theme not in ("dark", "light"):
            return
        self._dark_mode = (theme == "dark")
        self.theme_changed.emit(theme)
        self.colors_updated.emit(self._colors)

    def toggle_theme(self) -> str:
        """Toggle between dark and light mode. Returns new theme name."""
        new_theme = "light" if self._dark_mode else "dark"
        self.set_theme(new_theme)
        return new_theme

    def is_dark_theme(self) -> bool:
        """Return True if current mode is dark."""
        return self._dark_mode

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
        c = self.accent
        return QColor.fromHsv(c.hue(), c.saturation(), int(c.value() * 0.9))

    @property
    def accent_active(self) -> QColor:
        """Accent at 80 % HSV brightness (active / pressed state)."""
        c = self.accent
        return QColor.fromHsv(c.hue(), c.saturation(), int(c.value() * 0.8))

    def accent_alpha(self, alpha: int) -> QColor:
        """Accent colour at a given alpha value (0–255)."""
        c = QColor(self.accent)
        c.setAlpha(max(0, min(255, alpha)))
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
        """Return *color* at a given opacity percentage (0–100)."""
        c = QColor(color)
        c.setAlpha(max(0, min(255, int(pct * 2.55))))
        return c

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
