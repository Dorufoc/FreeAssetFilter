"""
ThemeManager — Singleton that loads colors.json and provides:
- Properties: surface, mid, text, black, transparent
- Accent: accent, accent_hover, accent_active, accent_alpha()
- Semantic: danger, warning, info, purple
- Utility: alpha_of(color, pct), _darken(color, factor)
- Legacy: get_color(path), get_component_colors(), get_common_color(),
          render_qss(), as_stylesheet()
"""

import json
import os
import re
from typing import Optional, Dict, Any
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor

# =============================================================================
# Full color data for backward compatibility during migration.
# Preserves the original colors.json structure so get_color() and render_qss()
# still resolve old-style paths (e.g. "button.primary.bg").
# After all call sites are migrated, this fallback can be removed.
# =============================================================================
_FULL_COLORS = json.loads("""\
{
  "common": {
    "background": {
      "primary": "#1a1a1a",
      "tertiary": "#2a2a2a",
      "card": "#2d2d2d",
      "card_hover": "#333333",
      "input": "#3a3a3a",
      "input_hover": "#424242",
      "panel": "#222222"
    },
    "text": {
      "primary": "#e8e8e8",
      "secondary": "#a0a0a0",
      "tertiary": "#6b6b6b",
      "disabled": "#4a4a4a"
    },
    "border": {
      "default": "#3a3a3a",
      "light": "#333333",
      "divider": "#383838"
    },
    "accent": {
      "primary": "#07c160",
      "hover": "#06ad56",
      "active": "#059a4c",
      "secondary": "#3b82f6",
      "warning": "#f59e0b",
      "danger": "#ef4444",
      "info": "#3b82f6",
      "purple": "#8b5cf6",
      "success": "#07c160",
      "default": "#a0a0a0"
    },
    "state": {
      "disabled": {
        "text": "#4a4a4a",
        "bg": "#3a3a3a"
      },
      "hover": {
        "bg": "#2a2a2a"
      },
      "selected": {
        "bg": "#2d2d2d"
      }
    }
  },
  "mica": {
    "tint_color": "#202020B4",
    "fallback_fill": "#202020"
  },
  "button": {
    "primary": {
      "bg": "#07c160",
      "bg_hover": "#06ad56",
      "bg_active": "#059a4c",
      "text": "#ffffff",
      "shadow": "#07C1604C"
    },
    "secondary": {
      "bg": "#3a3a3a",
      "bg_hover": "#424242",
      "bg_active": "#2a2a2a",
      "text": "#a0a0a0",
      "text_hover": "#e8e8e8",
      "border": "#3a3a3a",
      "border_hover": "#6b6b6b"
    },
    "ghost": {
      "bg": "#00000000",
      "bg_hover": "#2a2a2a",
      "bg_active": "#2a2a2a",
      "text": "#a0a0a0",
      "text_hover": "#e8e8e8"
    },
    "danger": {
      "bg": "#00000000",
      "bg_hover": "#EF44441A",
      "bg_active": "#EF44441A",
      "text": "#ef4444"
    },
    "info": {
      "bg": "#00000000",
      "bg_hover": "#3B82F61A",
      "bg_active": "#3B82F61A",
      "text": "#3b82f6"
    },
    "disabled": {
      "bg": "#3a3a3a",
      "text": "#4a4a4a"
    }
  },
  "checkbox": {
    "border": "#3a3a3a",
    "accent": "#07c160",
    "checkmark": "#ffffff",
    "label_text": "#e8e8e8",
    "label_disabled": "#E8E8E880"
  },
  "radio": {
    "border": "#3a3a3a",
    "accent": "#07c160",
    "label_text": "#e8e8e8"
  },
  "toggle": {
    "track_off": "#555555",
    "track_on": "#07c160",
    "thumb": "#ffffff",
    "shadow": "#0000004C",
    "thumb_disabled": "#6b6b6b",
    "track_disabled": "#3a3a3a"
  },
  "slider": {
    "track_bg": "#444444",
    "track_fill": "#07c160",
    "thumb": "#ffffff",
    "thumb_shadow": "#00000066",
    "tick_fill": "#FFFFFF4D",
    "tick_empty": "#6B6B6B66"
  },
  "sidebar": {
    "bg": "#1a1a1a",
    "text_active": "#e8e8e8",
    "text_inactive": "#a0a0a0",
    "icon_inactive": "#a0a0a0",
    "icon_active": "#07c160",
    "indicator": "#4a4a4a",
    "indicator_hover": "#5a5a5a",
    "section_label_expanded": "#e8e8e8",
    "section_label_collapsed": "#a0a0a0",
    "item_bg_normal": "#2A2A2A00",
    "item_bg_hover": "#2a2a2a"
  },
  "accordion": {
    "text_primary": "#e8e8e8",
    "text_tertiary": "#6b6b6b",
    "divider": "#383838",
    "bg_hover": "#2a2a2a",
    "border": "#3a3a3a"
  },
  "breadcrumb": {
    "text_primary": "#e8e8e8",
    "text_secondary": "#a0a0a0",
    "text_tertiary": "#6b6b6b",
    "hover_bg": "#2a2a2a",
    "active_bg": "#1e1e1e",
    "border": "#3a3a3a",
    "container_bg": "#2a2a2a",
    "icon": "#6b6b6b"
  },
  "cascader": {
    "bg": "#2d2d2d",
    "border": "#3a3a3a",
    "text": "#e8e8e8",
    "text_secondary": "#888888",
    "text_disabled": "#555555",
    "divider": "#333333",
    "accent": "#07c160",
    "input_bg_closed": "#2a2a2a",
    "input_border_closed": "#2d2d2d",
    "arrow_closed": "#444444",
    "arrow_open": "#777777",
    "tick": "#888888"
  },
  "carousel": {
    "accent": "#07c160",
    "chevron": "#ffffff",
    "arrow_bg": "#00000080",
    "arrow_hover": "#000000B3",
    "dot_inactive": "#FFFFFF66",
    "dot_hover": "#FFFFFFB3",
    "dot_out": "#2a2a2a",
    "dot_border": "#3a3a3a",
    "slide_bg": "#1e1e1e"
  },
  "combobox": {
    "selected_text": "#ffffff"
  },
  "context_menu": {
    "danger_text": "#ef4444",
    "panel_bg": "#2d2d2d",
    "text": "#e8e8e8",
    "border": "#3a3a3a",
    "item_hover_bg": "#333333",
    "item_disabled_text": "#4a4a4a",
    "separator": "#383838"
  },
  "date_picker": {
    "accent": "#07c160",
    "border": "#3a3a3a",
    "bg_card": "#2a2a2a",
    "bg_input": "#323232",
    "bg_input_hover": "#3c3c3c",
    "divider": "#404040",
    "text_primary": "#e8e8e8",
    "text_secondary": "#9a9a9a",
    "text_tertiary": "#6b6b6b",
    "shadow": "#00000050",
    "panel_bg": "#2a2a2a",
    "panel_border": "#3a3a3a",
    "selected_text": "#ffffff",
    "outside_text": "#6b6b6b",
    "time_colon": "#6b6b6b",
    "time_ampm": "#9a9a9a"
  },
  "dialog": {
    "body_bg": "#1a1a1a",
    "body_border": "#2a2a2a",
    "shadow": "#00000080",
    "footer_border": "#2a2a2a",
    "close_text": "#a0a0a0",
    "close_hover_bg": "#2a2a2a",
    "close_hover_text": "#e8e8e8",
    "message_text": "#a0a0a0",
    "about_product": "#e8e8e8",
    "about_version": "#a0a0a0",
    "about_copyright": "#6b6b6b",
    "type_colors": {
      "default": {
        "title": "#e8e8e8",
        "icon_bg": "#2a2a2a",
        "icon_color": "#a0a0a0"
      },
      "success": {
        "title": "#07c160",
        "icon_bg": "#07C16026",
        "icon_color": "#07c160"
      },
      "danger": {
        "title": "#ef4444",
        "icon_bg": "#EF444426",
        "icon_color": "#ef4444"
      },
      "info": {
        "title": "#3b82f6",
        "icon_bg": "#3B82F626",
        "icon_color": "#3b82f6"
      }
    }
  },
  "divider": {
    "line": "#383838",
    "text": "#6b6b6b"
  },
  "drawer": {
    "backdrop": "#00000099",
    "shadow": "#00000080",
    "header_border": "#383838",
    "header_title": "#e8e8e8",
    "footer_border": "#383838"
  },
  "file_picker": {
    "disabled_bg": "#3a3a3a",
    "disabled_text": "#4a4a4a",
    "disabled_border": "#333333",
    "drop_bg": "#2a2a2a",
    "drop_text": "#e8e8e8",
    "drop_border": "#555555",
    "hover_bg": "#383838",
    "hover_text": "#e8e8e8",
    "hover_border": "#6b6b6b",
    "error_bg": "#3a3a3a",
    "error_text": "#a0a0a0",
    "error_border": "#3a3a3a",
    "dragover_bg": "#07C1600C",
    "dragover_border": "#07c160",
    "drag_icon": "#07c160",
    "browse_text": "#6b6b6b"
  },
  "info_card": {
    "bg": "#1e1e1e",
    "bg_hover": "#252525",
    "border": "#2e2e2e",
    "media_bg": "#2a2a2a",
    "title": "#e8e8e8",
    "subtitle": "#a0a0a0",
    "desc": "#6b6b6b",
    "icon": "#a0a0a0",
    "overlay_bg": "#0000007F",
    "shadow": "#00000028",
    "disabled_media": "#444444",
    "disabled_icon": "#666666",
    "disabled_title": "#666666",
    "disabled_subtitle": "#666666",
    "disabled_desc": "#666666"
  },
  "lineedit": {
    "border_error": "#ef4444",
    "border": "#3a3a3a",
    "focus_border": "#07c160",
    "focus_border_error": "#ef4444",
    "bg": "#3a3a3a",
    "text": "#e8e8e8",
    "selection_bg": "#07c160",
    "selection_text": "#ffffff",
    "disabled_text": "#4a4a4a",
    "disabled_border": "#333333"
  },
  "notification_badge": {
    "panel_bg": "#2d2d2d",
    "panel_border": "#3a3a3a",
    "divider": "#383838",
    "text_primary": "#e8e8e8",
    "text_secondary": "#a0a0a0",
    "text_tertiary": "#6b6b6b",
    "hover_bg": "#3a3a3a",
    "accent_green": "#07c160",
    "count_bg": "#EF444426",
    "count_text": "#ef4444",
    "unread_dot": "#07c160",
    "icon_success": "#07c160",
    "icon_warning": "#f59e0b",
    "icon_error": "#ef4444",
    "icon_info": "#3b82f6"
  },
  "number_input": {
    "arrow": "#a0a0a0",
    "text": "#e8e8e8",
    "selection_bg": "#07c160",
    "selection_text": "#ffffff",
    "container_bg": "#3a3a3a",
    "error_bg_tint": "#EF444426",
    "error_border": "#ef4444",
    "focus_border": "#07c160",
    "border": "#3a3a3a",
    "disabled_border": "#3a3a3a"
  },
  "pagination": {
    "bg": "#3a3a3a",
    "bg_hover": "#424242",
    "bg_active": "#07c160",
    "text": "#a0a0a0",
    "text_hover": "#e8e8e8",
    "text_active": "#ffffff",
    "text_ellipsis": "#6b6b6b"
  },
  "player_bar": {
    "bar_bg": "#2D2D2DF2",
    "bar_border": "#2e2e2e",
    "popup_bg": "#1e1e1e",
    "popup_border": "#2e2e2e",
    "speed_selected_bg": "#07C1601E",
    "speed_selected_text": "#07c160",
    "speed_normal_text": "#a0a0a0",
    "value_text": "#e8e8e8",
    "label_text": "#6b6b6b",
    "volume_fill": "#07C16019",
    "volume_value": "#07c160",
    "volume_label": "#a0a0a0"
  },
  "progress": {
    "track_bg": "#3a3a3a",
    "stripe": "#FFFFFF26",
    "label_text": "#a0a0a0"
  },
  "progress_circle": {
    "track_bg": "#3a3a3a",
    "center_text": "#e8e8e8"
  },
  "steps": {
    "pending": {
      "border": "#3a3a3a",
      "bg": "#3a3a3a",
      "text": "#6b6b6b"
    },
    "current": {
      "border": "#07c160",
      "bg": "#07C16019",
      "text": "#07c160"
    },
    "completed": {
      "border": "#07c160",
      "bg": "#07c160",
      "text": "#ffffff"
    },
    "error": {
      "border": "#ef4444",
      "bg": "#EF444419",
      "text": "#ef4444"
    },
    "connector_pending": "#3a3a3a",
    "connector_completed": "#07c160"
  },
  "table": {
    "status_active": "#07c160",
    "status_inactive": "#a0a0a0",
    "status_error": "#ef4444",
    "status_warning": "#f59e0b",
    "bg": "#2d2d2d",
    "border": "#333333",
    "gridline": "#383838",
    "header_text": "#e8e8e8",
    "header_bg": "#333333",
    "alt_row_bg": "#2a2a2a",
    "alt_row_text": "#a0a0a0",
    "cell_border_bottom": "#333333",
    "cell_border_right": "#383838",
    "selected_row_bg": "#2d2d2d",
    "selected_row_text": "#e8e8e8",
    "empty_text": "#6b6b6b"
  },
  "tabs": {
    "text_secondary": "#a0a0a0",
    "text_primary": "#e8e8e8",
    "accent": "#07c160",
    "disabled": "#4a4a4a",
    "divider": "#383838"
  },
  "tag": {
    "default_bg": "#2a2a2a",
    "default_text": "#a0a0a0",
    "default_border": "#3a3a3a",
    "primary_bg": "#07C16026",
    "primary_text": "#07c160",
    "primary_border": "#07C1604C",
    "warning_bg": "#F59E0B26",
    "warning_text": "#f59e0b",
    "warning_border": "#F59E0B4C",
    "danger_bg": "#EF444426",
    "danger_text": "#ef4444",
    "danger_border": "#EF44444C",
    "info_bg": "#3B82F626",
    "info_text": "#3b82f6",
    "info_border": "#3B82F64C",
    "close_fallback": "#a0a0a0"
  },
  "textarea": {
    "disabled_bg": "#2a2a2a",
    "hover_bg": "#424242",
    "bg": "#3a3a3a",
    "border_error": "#ef4444",
    "border": "#3a3a3a",
    "focus_border_error": "#ef4444",
    "focus_border": "#07c160",
    "text": "#e8e8e8",
    "selection_bg": "#07c160",
    "selection_text": "#ffffff",
    "disabled_text": "#4a4a4a",
    "disabled_border": "#333333",
    "label_text": "#e8e8e8",
    "desc_text": "#6b6b6b",
    "counter_error": "#ef4444",
    "counter_normal": "#6b6b6b"
  },
  "timeline": {
    "line": "#383838",
    "text_primary": "#e8e8e8",
    "text_secondary": "#a0a0a0",
    "text_tertiary": "#6b6b6b"
  },
  "tooltip": {
    "bubble_bg": "#2a2a2a",
    "bubble_border": "#3a3a3a",
    "text": "#e8e8e8"
  }
}
""")

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
        """Load colors from SettingsManagerV2 first, fall back to colors.json.

        V2 是配置的唯一真实来源（single source of truth）。
        colors.json 仅作为首次运行 / V2 缺失时的回退。
        """
        try:
            from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2
            v2 = SettingsManagerV2()
            v2.load()
            colors = v2.get("appearance.colors")
            if isinstance(colors, dict) and "accent" in colors:
                self._colors = colors
                # 同步 theme 模式（确保重启后恢复用户上次选择的主题）
                saved_theme = v2.get("appearance.theme", "light")
                self._dark_mode = (saved_theme == "dark")
                # 同步 accent_color（确保 colors.accent.primary 一致）
                saved_accent = v2.get("appearance.accent_color")
                if saved_accent and "accent" in self._colors:
                    self._colors["accent"]["primary"] = saved_accent
                print(
                    f"ThemeManager: loaded from V2 (theme={saved_theme}, "
                    f"accent={saved_accent})"
                )
                return
        except Exception:
            pass

        colors_path = os.path.join(self._theme_dir, "colors.json")
        if not os.path.exists(colors_path):
            raise FileNotFoundError(f"Theme colors file not found: {colors_path}")
        with open(colors_path, "r", encoding="utf-8") as f:
            self._colors = json.load(f)
        count = self._count_tokens(self._colors)
        print(f"ThemeManager: loaded {count} color tokens from {colors_path}")

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
    # All gray levels sourced from colors.json["gray"].

    @property
    def surface(self) -> QColor:
        """Primary surface background color from colors.json (gray.g1 / gray_light.g1)."""
        key = "gray" if self._dark_mode else "gray_light"
        return self._parse_hex_color(self._colors[key]["g1"])

    @property
    def fill(self) -> QColor:
        """Base space fill color from colors.json (gray.g2 / gray_light.g2) for card backgrounds, elevated panels."""
        key = "gray" if self._dark_mode else "gray_light"
        return self._parse_hex_color(self._colors[key]["g2"])

    @property
    def mid(self) -> QColor:
        """Mid-tone gray from colors.json (gray.g3 / gray_light.g3) for secondary content."""
        key = "gray" if self._dark_mode else "gray_light"
        return self._parse_hex_color(self._colors[key]["g3"])

    @property
    def text(self) -> QColor:
        """Primary text color from colors.json (gray.g4 / gray_light.g4)."""
        key = "gray" if self._dark_mode else "gray_light"
        return self._parse_hex_color(self._colors[key]["g4"])

    @property
    def black(self) -> QColor:
        """Pure black from colors.json (gray.black / gray_light.black)."""
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
    # Accent properties (loaded from colors.json)
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
        Resolve a dot-notation path to a QColor.

        Tries the simplified ``colors.json`` first, then falls back to the
        full colour map so old call sites (e.g. ``get_color("button.primary.bg")``)
        continue to work during migration.

        Returns None if path not found.
        """
        value = self._resolve_path(path)
        if value is None:
            value = self._resolve_path(path, _FULL_COLORS)
        if value is None or not isinstance(value, str):
            return None
        try:
            return self._parse_hex_color(value)
        except Exception:
            return None

    def get_component_colors(self, component: str) -> Dict[str, Any]:
        """Get the entire colour dict for a component (e.g. 'button').

        Falls back to the full colour map for backward compat.
        """
        result = self._resolve_path(component)
        if result is None:
            result = self._resolve_path(component, _FULL_COLORS)
        return result or {}

    def get_common_color(self, category: str, token: str) -> Optional[QColor]:
        """Shorthand for ``get_color(f'common.{category}.{token}')``."""
        return self.get_color(f"common.{category}.{token}")

    def render_qss(self, template_path: Optional[str] = None) -> str:
        """
        Read a QSS template file and replace ``{{TOKEN.PATH}}`` placeholders
        with actual color values.

        Resolution order:
        1. Simplified ``colors.json`` (``self._colors``)
        2. Full colour fallback (backward compat)
        3. New property-based tokens (``{{surface}}``, ``{{accent.primary}}``, …)

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

            # 1. Simplified colours
            value = self._resolve_path(token_path)
            if value is None:
                # 2. Full fallback
                value = self._resolve_path(token_path, _FULL_COLORS)
            if value is not None and isinstance(value, str):
                return value

            # 3. New property tokens
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
