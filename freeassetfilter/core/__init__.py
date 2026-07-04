# FreeAssetFilter 核心功能模块

def __getattr__(name):
    if name in __all__:
        if name in ('HeartbeatManager', 'FutureHandle'):
            from .heartbeat_manager import HeartbeatManager, FutureHandle
            globals().update(locals())
            return globals()[name]
        from .color_extractor import (
            extract_cover_colors,
            extract_cover_colors_from_path,
            color_distance,
            rgb_to_hex,
            hex_to_qcolor,
            sort_colors_by_brightness,
            adjust_colors_for_gradient
        )
        # Make available as module attribute for subsequent access
        globals().update(locals())
        return globals()[name]
    raise AttributeError(f"module 'freeassetfilter.core' has no attribute {name!r}")

__all__ = [
    'extract_cover_colors',
    'extract_cover_colors_from_path',
    'color_distance',
    'rgb_to_hex',
    'hex_to_qcolor',
    'sort_colors_by_brightness',
    'adjust_colors_for_gradient',
    'HeartbeatManager',
    'FutureHandle',
]
