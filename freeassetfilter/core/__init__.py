"""FreeAssetFilter Core — reorganised into functional sub-packages.

This module provides backward-compatible lazy re-exports for all modules
that were moved to sub-packages (``managers/``, ``preview/``,
``native/bridges/``).

Usage:

    # Old flat-module import (returns the module object)
    from freeassetfilter.core import settings_manager
    from freeassetfilter.core.heartbeat_manager import HeartbeatManager

    # Direct symbol import (returns the object)
    from freeassetfilter.core import SettingsManager, HeartbeatManager
"""

from __future__ import annotations

import importlib
import sys
import types

# ---------------------------------------------------------------------------
# Module map: old flat name → new sub-package dotted path
# ---------------------------------------------------------------------------
_MODULE_MAP: dict[str, str] = {
    "settings_manager": "freeassetfilter.core.managers.settings_manager",
    "theme_manager": "freeassetfilter.core.managers.theme_manager",
    "heartbeat_manager": "freeassetfilter.core.managers.heartbeat_manager",
    "update_manager": "freeassetfilter.core.managers.update_manager",
    "thumbnail_manager": "freeassetfilter.core.managers.thumbnail_manager",
    "media_probe": "freeassetfilter.core.native.bridges.media_probe",
    "color_extractor": "freeassetfilter.core.native.bridges.color_extractor",
    "image_color_utils": "freeassetfilter.core.preview.image_color_utils",
    "lut_preview_generator": "freeassetfilter.core.native.bridges.lut_preview_generator",
    "svg_renderer": "freeassetfilter.core.preview.svg_renderer",
    "mpv_manager": "freeassetfilter.core.managers.mpv_manager",
    "mpv_player_core": "freeassetfilter.core.native.bridges.mpv_player_core",
    "py7z_core": "freeassetfilter.core.native.bridges.py7z_core",
    "rust_thumbnail_bridge": "freeassetfilter.core.native.bridges.rust_thumbnail_bridge",
}

# ---------------------------------------------------------------------------
# Symbol map: commonly imported top-level symbols → their new module path
# ---------------------------------------------------------------------------
_SYMBOL_MAP: dict[str, str] = {
    # heartbeat_manager
    "HeartbeatManager": "freeassetfilter.core.managers.heartbeat_manager",
    "FutureHandle": "freeassetfilter.core.managers.heartbeat_manager",
    # settings_manager
    "SettingsManager": "freeassetfilter.core.managers.settings_manager",
    # theme_manager
    "ThemeManager": "freeassetfilter.core.managers.theme_manager",
    # update_manager
    "UpdateError": "freeassetfilter.core.managers.update_manager",
    "UpdateCancelled": "freeassetfilter.core.managers.update_manager",
    # color_extractor — all public functions
    "extract_cover_colors": "freeassetfilter.core.native.bridges.color_extractor",
    "extract_cover_colors_from_path": "freeassetfilter.core.native.bridges.color_extractor",
    "color_distance": "freeassetfilter.core.native.bridges.color_extractor",
    "rgb_to_hex": "freeassetfilter.core.native.bridges.color_extractor",
    "hex_to_qcolor": "freeassetfilter.core.native.bridges.color_extractor",
    "sort_colors_by_brightness": "freeassetfilter.core.native.bridges.color_extractor",
    "adjust_colors_for_gradient": "freeassetfilter.core.native.bridges.color_extractor",
    # thumbnail_manager
    "ThumbnailManager": "freeassetfilter.core.managers.thumbnail_manager",
    # svg_renderer
    "SvgRenderer": "freeassetfilter.core.preview.svg_renderer",
    # lut_preview_generator
    "LUTPreviewGenerator": "freeassetfilter.core.native.bridges.lut_preview_generator",
    # media_probe — commonly used public functions
    "get_ffprobe_path": "freeassetfilter.core.native.bridges.media_probe",
    "get_ffmpeg_path": "freeassetfilter.core.native.bridges.media_probe",
    "warmup_ffmpeg_tools": "freeassetfilter.core.native.bridges.media_probe",
    "run_ffprobe_json": "freeassetfilter.core.native.bridges.media_probe",
    "get_video_stream_info": "freeassetfilter.core.native.bridges.media_probe",
    "get_video_duration_seconds": "freeassetfilter.core.native.bridges.media_probe",
    # mpv_manager
    "MPVManager": "freeassetfilter.core.managers.mpv_manager",
    # mpv_player_core
    "MPVPlayerCore": "freeassetfilter.core.native.bridges.mpv_player_core",
    # py7z_core
    "Py7zCore": "freeassetfilter.core.native.bridges.py7z_core",
    # rust_thumbnail_bridge
    "RustThumbnailBridge": "freeassetfilter.core.native.bridges.rust_thumbnail_bridge",
}

__all__ = sorted(list(_MODULE_MAP.keys()) + list(_SYMBOL_MAP.keys()))


class _LazyModuleAlias(types.ModuleType):
    """延迟导入的旧式扁平模块别名（代替原先的 eager 导入循环）。

    原先在包导入时强制导入全部 14 个核心模块，连锁拉入 PIL / numpy /
    QtSvg 等重依赖（数百 ms），拖慢应用首屏。本类在 ``sys.modules`` 中
    注册一个占位模块：首次属性访问（如 ``from
    freeassetfilter.core.settings_manager import SettingsManager`` 的
    ``getattr``）时才真正导入目标模块，并把 ``sys.modules`` 条目替换为
    真实模块，使后续导入直接命中真实模块，行为与 eager 完全一致。
    """

    def __init__(self, name: str, target: str) -> None:
        super().__init__(name)
        self._target_module = target

    def __getattr__(self, name: str) -> object:
        # dunder/内省属性（如 inspect 检查的 __file__、__name__ 等）绝不
        # 触发真实导入：模块加载早期 logging/inspect 的 hasattr 探测若
        # 无条件导入会制造循环（如 perf_metrics 半初始化时被拉入）。
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(
                f"module {self.__name__!r} has no attribute {name!r}"
            )
        target = self.__dict__.get("_target_module")
        if not target:
            raise AttributeError(
                f"module {self.__name__!r} has no attribute {name!r}"
            )
        module = importlib.import_module(target)
        if sys.modules.get(self.__name__) is self:
            sys.modules[self.__name__] = module
        return getattr(module, name)


# ---------------------------------------------------------------------------
# Install lazy module aliases into sys.modules so that
# ``from freeassetfilter.core.settings_manager import SettingsManager``
# (sub-module import pattern) resolves correctly.  Python's ``__getattr__``
# is only called for *attribute* access on the package, not for
# sub-module import resolution — hence the placeholder modules above.
# ---------------------------------------------------------------------------
for _old_name, _new_path in _MODULE_MAP.items():
    sys.modules[f"freeassetfilter.core.{_old_name}"] = _LazyModuleAlias(
        f"freeassetfilter.core.{_old_name}", _new_path
    )
del _old_name, _new_path


def __getattr__(name: str) -> types.ModuleType | object:
    """Lazy backward-compatible attribute access.

    Supports both:

    * ``from freeassetfilter.core import settings_manager`` → returns the
      module from its new location.
    * ``from freeassetfilter.core import SettingsManager`` → returns the
      class/function directly (via symbol resolution).
    """
    # 1) Module names → import the whole module
    if name in _MODULE_MAP:
        module_path = _MODULE_MAP[name]
        module = importlib.import_module(module_path)
        # Install into sys.modules so ``from freeassetfilter.core.X import Y``
        # works — Python looks up ``freeassetfilter.core.X`` in sys.modules
        # and finds the module.
        sys.modules[f"freeassetfilter.core.{name}"] = module
        return module

    # 2) Symbol names → import the module and extract the attribute
    if name in _SYMBOL_MAP:
        module_path = _SYMBOL_MAP[name]
        module = importlib.import_module(module_path)
        return getattr(module, name)

    # 3) Unknown attribute
    raise AttributeError(f"module 'freeassetfilter.core' has no attribute {name!r}")


def __dir__() -> list[str]:
    """List available backward-compatible names."""
    return __all__
