#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0 — 设置管理器 V2

全新的设置分类树（v2），专注于核心配置项目的持久化存储与管理。
与 v1 SettingsManager 完全独立，使用独立的 JSON 文件和分类结构。

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, Optional


# =============================================================================
# 全量组件配色 — 用于向后兼容 legacy get_color() / render_qss() 调用
# 内嵌 JSON 字符串，settings_v2.json 丢失时作为自动生成的模板。
# =============================================================================
_DEFAULT_COLORS_JSON = json.loads("""\
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


def _build_default_colors() -> Dict[str, Any]:
    """构建完整默认配色：简化配色 + 全量组件配色（顶层键无重叠）。"""
    colors: Dict[str, Any] = {
        "accent": {
            "primary": "#3A9DCB",
            "danger": "#ef4444",
            "warning": "#f59e0b",
            "info": "#3b82f6",
            "purple": "#8b5cf6",
        },
        "gray": {
            "g1": "#1a1a1a",
            "g2": "#3e3e3e",
            "g3": "#888888",
            "g4": "#ffffff",
            "black": "#000000",
        },
        "gray_light": {
            "g1": "#f5f5f5",
            "g2": "#e0e0e0",
            "g3": "#888888",
            "g4": "#1a1a1a",
            "black": "#000000",
        },
    }
    colors.update(_DEFAULT_COLORS_JSON)
    return colors


# 性能档位取值（与 core/native 三钩子对齐）。
PERFORMANCE_PROFILES: tuple[str, str, str] = (
    "performance",
    "balanced",
    "powersave",
)

#: 默认性能档位：均衡。
DEFAULT_PERFORMANCE_PROFILE: str = "balanced"


# ── V2 分类树默认值 ──────────────────────────────────────────────
# "分类树 v2" — 全新的扁平化配置参数结构，按功能域分组。
# colors 包含所有配色数据（简化 + 全量组件），settings_v2.json 丢失时
# 自动以此为模板生成。
DEFAULT_SETTINGS_V2: Dict[str, Any] = {
    "version": 2,
    "appearance": {
        "theme": "dark",           # 实际生效值："light" | "dark"（跟随模式下为系统解析结果）
        "theme_mode": "dark",      # 用户偏好："light"（白天） | "dark"（夜晚） | "system"（跟随系统）
        "accent_color": "#3A9DCB",
        "colors": _build_default_colors(),
        # 背景米卡效果可调参数（设置窗口「外观」页滑动条）
        "mica": {
            "blur_radius": 200,    # 背景模糊半径（px）
            "saturation": 4.5,     # 背景色饱和度倍率（1.0 = 原始）
            "contrast": 1.5,       # 背景色对比度倍率（1.0 = 原始）
            "tint_opacity": 70,    # 叠加层透明度（%，0-100）
        },
        # 自定义窗口背景（设置窗口「外观」页「窗口背景」区块）
        "background": {
            "mode": "mica",   # 背景模式："mica"（云母） | "image"（图像） | "minimalist"（简约）
            "image": "",      # 自定义图片文件名（位于 data/backgrounds/ 下，空字符串 = 未设置）
            "ambient": True,  # 弥散氛围开关（简约模式下将主题色作为背景氛围层，默认开启）
            "blur": 0,        # 图像模式模糊半径（整数 px，0-200，默认不模糊）
            "transparency": 80,  # 图像模式透明度（%，0-100，默认 80% 很透明）
        },
    },
    "performance": {
        # 性能档位（设置页「性能档位」三段选择）：
        # "performance"（性能） | "balanced"（均衡，默认） | "powersave"（省电）。
        # 提交时经 SettingsLayout._submit_settings 下发到三钩子
        #（platform_gpu.apply_gpu_profile / platform_threads
        # .apply_process_power_policy / platform_timing.set_active_profile）。
        # 注意：工作线程钩子（MMCSS/钉核）在线程入口注册，只影响
        # 新建/下轮工作线程会话，不追溯已在跑的线程。
        "profile": "balanced",
    },
}


def _project_root() -> str:
    """返回项目根目录的绝对路径。"""
    return str(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
        )
    )


def _default_settings_path() -> str:
    """返回默认的 V2 设置文件路径 ``data/settings_v2.json``。"""
    return os.path.join(_project_root(), "data", "settings_v2.json")


class SettingsManagerV2:
    """全新的设置管理器 V2。

    管理独立的 V2 分类树配置，与旧版 SettingsManager 完全解耦。
    支持点号分隔的 key 路径读写（如 ``appearance.theme``）。
    线程安全：内部使用可重入锁（``RLock``）保护所有读写操作。

    存储位置：``data/settings_v2.json``（原子写盘 + 大小校验）。
    """

    #: 设置文件大小上限（10MB）：超出视为损坏，加载时回退默认树并重写。
    MAX_SETTINGS_FILE_BYTES: int = 10 * 1024 * 1024

    def __init__(self, file_path: Optional[str] = None) -> None:
        """初始化 V2 设置管理器。

        Args:
            file_path: JSON 文件路径。为 ``None`` 时使用
                ``data/settings_v2.json``。
        """
        # 使用可重入锁：get()/get_all() 在持锁状态下会调用 load()，
        # 非重入 Lock 会在此自锁死锁（历史缺陷，2026-09 修复）。
        self._lock = threading.RLock()
        self._file_path: str = file_path if file_path is not None else _default_settings_path()
        self._settings: Dict[str, Any] = {}
        self._loaded = False

    # ── 属性 ─────────────────────────────────────────────────────

    @property
    def file_path(self) -> str:
        """当前 V2 设置文件路径。"""
        return self._file_path

    # ── 加载 / 保存 ───────────────────────────────────────────────

    def load(self) -> Dict[str, Any]:
        """从磁盘加载 V2 设置。

        若文件不存在或损坏，返回默认 V2 分类树并写盘。
        多次调用安全——首次加载后返回缓存。

        Returns:
            Dict[str, Any]: V2 设置字典。
        """
        with self._lock:
            if self._loaded:
                return self._settings

            if not os.path.exists(self._file_path):
                self._settings = self._copy_defaults()
                self._loaded = True
                self._write()
                return self._settings

            try:
                # 大小校验：异常巨大的文件视为损坏（防手误/损坏写盘）。
                if os.path.getsize(self._file_path) > self.MAX_SETTINGS_FILE_BYTES:
                    raise ValueError("settings file too large")
                with open(self._file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("invalid root type")
                self._settings = self._merge_with_defaults(data)
            except (json.JSONDecodeError, OSError, ValueError):
                self._settings = self._copy_defaults()
                self._write()

            self._loaded = True
            return self._settings

    def save(self) -> None:
        """将当前内存中的 V2 设置写入磁盘。"""
        with self._lock:
            self._write()

    def get_all(self) -> Dict[str, Any]:
        """获取完整的 V2 设置字典副本。"""
        with self._lock:
            if not self._loaded:
                self.load()
            return dict(self._settings)  # shallow copy

    def reset_to_defaults(self) -> None:
        """将 V2 设置重置为默认值并立即写盘。"""
        with self._lock:
            self._settings = self._copy_defaults()
            self._write()

    # ── 点号路径读写 ──────────────────────────────────────────────

    def get(self, key_path: str, default: Any = None) -> Any:
        """通过点号路径读取 V2 设置值。

        Args:
            key_path: 点号路径，如 ``"appearance.theme"``。
            default: 路径不存在时的默认值。

        Returns:
            Any: 设置值，路径不存在时返回 *default*。
        """
        with self._lock:
            if not self._loaded:
                self.load()

            keys = key_path.split(".")
            value = self._settings
            try:
                for key in keys:
                    value = value[key]
                return value
            except (KeyError, TypeError):
                return default

    def set(self, key_path: str, value: Any) -> bool:
        """通过点号路径设置 V2 设置值（仅更新内存）。

        调用 :meth:`save` 将变更写盘。

        Args:
            key_path: 点号路径，如 ``"appearance.theme"``。
            value: 要设置的值。

        Returns:
            bool: 值有变更返回 ``True``，无变化返回 ``False``。
        """
        with self._lock:
            if not self._loaded:
                self.load()

            keys = key_path.split(".")
            target = self._settings
            for key in keys[:-1]:
                if key not in target or not isinstance(target[key], dict):
                    target[key] = {}
                target = target[key]

            if keys[-1] in target and target[keys[-1]] == value:
                return False

            target[keys[-1]] = value
            return True

    # ── 内部方法 ──────────────────────────────────────────────────

    @staticmethod
    def _deep_merge_colors(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """深度合并配色字典，*override* 中的值优先。

        适用于旧版 V2 文件缺少全量配色字段时的平滑迁移：
        确保默认中的全量组件配色不会被旧文件覆盖丢失。
        """
        result = dict(base)
        for key, val in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(val, dict):
                result[key] = SettingsManagerV2._deep_merge_colors(result[key], val)
            else:
                result[key] = val
        return result

    def _write(self) -> None:
        """将 ``self._settings`` 原子写入 JSON 文件（已处于锁内）。

        先写 ``<file>.tmp`` 再 ``os.replace`` 原子替换，避免进程崩溃/
        断电时截断 settings_v2.json 导致用户配置丢失。
        """
        settings_dir = os.path.dirname(self._file_path)
        if settings_dir:
            os.makedirs(settings_dir, exist_ok=True)
        tmp_path = f"{self._file_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._settings, f, ensure_ascii=False, indent=4)
        os.replace(tmp_path, self._file_path)

    def _copy_defaults(self) -> Dict[str, Any]:
        """深拷贝默认 V2 设置。"""
        return json.loads(json.dumps(DEFAULT_SETTINGS_V2))

    def _merge_with_defaults(self, loaded: Dict[str, Any]) -> Dict[str, Any]:
        """将加载的设置与默认值合并，确保所有键存在。"""
        merged = self._copy_defaults()

        if not isinstance(loaded, dict):
            return merged

        # 合并 version
        if "version" in loaded and isinstance(loaded["version"], int):
            merged["version"] = loaded["version"]

        # 逐域合并（嵌套 dict 整体替换，不含逐叶合并）
        if "appearance" in loaded and isinstance(loaded["appearance"], dict):
            app_loaded = loaded["appearance"]
            for key in merged["appearance"]:
                if key in app_loaded:
                    # colors 需要深度合并以保留默认全量组件配色
                    if key == "colors" and isinstance(app_loaded[key], dict):
                        merged["appearance"][key] = self._deep_merge_colors(
                            merged["appearance"][key], app_loaded[key]
                        )
                    # background 浅合并：旧文件缺 blur/transparency 时以
                    # 后续版本默认值补齐，已有值保持不变；中间版本的
                    # opacity（不透明度 %）按 transparency = 100 - opacity
                    # 迁移后清理（两者语义互补，视觉保持一致）。
                    elif key == "background" and isinstance(
                        app_loaded[key], dict
                    ):
                        loaded_bg = app_loaded[key]
                        merged_bg = dict(merged["appearance"][key])
                        merged_bg.update(loaded_bg)
                        # 注意：缺键检测必须看落盘原始数据（loaded_bg），不能看
                        # 合并后的 merged_bg——后者已被默认值预填 transparency。
                        if "transparency" not in loaded_bg and (
                            "opacity" in loaded_bg
                        ):
                            try:
                                legacy = int(
                                    round(float(loaded_bg.get("opacity", 20)))
                                )
                            except (TypeError, ValueError):
                                legacy = 20
                            merged_bg["transparency"] = max(
                                0, min(100, 100 - legacy)
                            )
                        merged_bg.pop("opacity", None)
                        merged_bg.setdefault("blur", 0)
                        merged_bg.setdefault("transparency", 80)
                        merged["appearance"][key] = merged_bg
                    # mica 浅合并：旧文件只写入了部分 mica 参数时，缺失
                    # 参数以当前版本默认值补齐（如 saturation/contrast）。
                    elif key == "mica" and isinstance(app_loaded[key], dict):
                        merged_mica = dict(merged["appearance"][key])
                        merged_mica.update(app_loaded[key])
                        merged["appearance"][key] = merged_mica
                    else:
                        merged["appearance"][key] = app_loaded[key]

        # performance 域合并：profile 为扁平键，只接受三档合法值；
        # 旧文件缺键或非法值时回退默认 balanced（不抛异常）。
        if "performance" in loaded and isinstance(loaded["performance"], dict):
            perf_loaded = loaded["performance"]
            staged_profile = perf_loaded.get("profile", None)
            if isinstance(staged_profile, str) and (
                staged_profile in PERFORMANCE_PROFILES
            ):
                merged["performance"]["profile"] = staged_profile

        return merged
