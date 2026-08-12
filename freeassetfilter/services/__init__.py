"""
FreeAssetFilter 业务逻辑服务层

采用四层分层架构（UI → Services → Workers/Repositories → Core）：
- Services: 纯业务逻辑，无 Qt 依赖
- Workers: 后台线程（QThread/QRunnable），与 Services 协作
- Repositories: 数据访问层，封装 JSON 文件读写
- Core: 现有单例管理器

所有新服务通过构造参数注入依赖，保持向后兼容。

聚合导出已惰性化：原先 eager 导入全部服务会把 file_icon_manager
（连锁导入 core 管理器 + PIL/QtSvg）等重模块一并拖入启动路径，
现在改为首次访问时才按需导入（``__getattr__``）。
"""

from __future__ import annotations

import importlib
import sys
import types

# 旧式聚合符号 → 所属子模块（惰性解析用）。子模块名按 `from .X import Y`
# 的原始声明一一对应，保证 ``from freeassetfilter.services import Y``
# 与 ``from freeassetfilter.services.X import Y`` 解析到同一对象。
_SYMBOL_TO_MODULE: dict[str, str] = {
    "BaseService": "base",
    "DriveService": "drive_service",
    "FavoritesService": "favorites_service",
    "FavoritesRepository": "favorites_repository",
    "FileService": "file_service",
    "MediaMetadataService": "media_metadata_service",
    "FileIconManager": "file_icon_manager",
    "PreviewerRegistry": "previewer_registry",
    "SettingsRepository": "settings_repository",
    "StagingPoolService": "staging_pool_service",
}

__all__ = [
    "BaseService",
    "DriveService",
    "FavoritesService",
    "FavoritesRepository",
    "FileIconManager",
    "FileService",
    "MediaMetadataService",
    "PreviewerRegistry",
    "SettingsRepository",
    "StagingPoolService",
]


def __getattr__(name: str) -> types.ModuleType | object:
    """惰性向后兼容导出。

    Supports both old import patterns:

    * ``from freeassetfilter.services import media_metadata_service``
      → returns the sub-module.
    * ``from freeassetfilter.services import MediaMetadataService``
      → returns the service class directly.
    """
    # 1) Sub-module name (lowercase, real file) → import it directly.
    try:
        module = importlib.import_module(f"{__name__}.{name}")
    except ModuleNotFoundError as exc:
        # 仅当确实找不到该子模块本身时才继续；子模块内部依赖缺失
        # 属于真实错误，向上抛出以免被误吞。
        if exc.name != f"{__name__}.{name}":
            raise
    else:
        sys.modules[f"{__name__}.{name}"] = module
        return module

    # 2) Symbol name → import owning module and extract the attribute.
    module_name = _SYMBOL_TO_MODULE.get(name)
    if module_name is not None:
        module = importlib.import_module(f"{__name__}.{module_name}")
        return getattr(module, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """List available backward-compatible names."""
    return sorted(set(__all__) | set(_SYMBOL_TO_MODULE.keys()))
