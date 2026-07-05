"""
FreeAssetFilter 业务逻辑服务层

采用四层分层架构（UI → Services → Workers/Repositories → Core）：
- Services: 纯业务逻辑，无 Qt 依赖
- Workers: 后台线程（QThread/QRunnable），与 Services 协作
- Repositories: 数据访问层，封装 JSON 文件读写
- Core: 现有单例管理器

所有新服务通过构造参数注入依赖，保持向后兼容。
"""

from freeassetfilter.services.base import BaseService
from freeassetfilter.services.drive_service import DriveService
from freeassetfilter.services.favorites_service import FavoritesService
from freeassetfilter.services.favorites_repository import FavoritesRepository
from freeassetfilter.services.file_service import FileService
from freeassetfilter.services.media_metadata_service import MediaMetadataService
from freeassetfilter.services.previewer_registry import PreviewerRegistry
from freeassetfilter.services.settings_repository import SettingsRepository
from freeassetfilter.services.staging_pool_service import StagingPoolService

__all__ = [
    "BaseService",
    "DriveService",
    "FavoritesService",
    "FavoritesRepository",
    "FileService",
    "MediaMetadataService",
    "PreviewerRegistry",
    "SettingsRepository",
    "StagingPoolService",
]
