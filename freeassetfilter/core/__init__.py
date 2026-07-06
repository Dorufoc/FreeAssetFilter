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

# ---------------------------------------------------------------------------
# Eagerly install module aliases into sys.modules so that
# ``from freeassetfilter.core.settings_manager import SettingsManager``
# (sub-module import pattern) resolves correctly.  Python's ``__getattr__``
# is only called for *attribute* access on the package, not for
# sub-module import resolution.
# ---------------------------------------------------------------------------
for _old_name, _new_path in _MODULE_MAP.items():
    try:
        _mod = importlib.import_module(_new_path)
        sys.modules[f"freeassetfilter.core.{_old_name}"] = _mod
    except ImportError:
        pass
del _old_name, _new_path, _mod


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
