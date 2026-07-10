#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

轻量文件列表数据模型
继承 QAbstractListModel，提供 10 个自定义角色和 O(1) 路径→行号索引。
"""

from typing import Any, Dict, List, Optional

from PySide6.QtCore import QAbstractListModel, QModelIndex, QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from freeassetfilter.services.file_icon_manager import FileIconManager

# ── 自定义角色 ──────────────────────────────────────────────────────────────

# 角色值从 Qt.UserRole + 1 开始递增
FileNameRole: int = Qt.UserRole + 1
FilePathRole: int = Qt.UserRole + 2
IsDirRole: int = Qt.UserRole + 3
FileSizeRole: int = Qt.UserRole + 4
ModifiedRole: int = Qt.UserRole + 5
CreatedRole: int = Qt.UserRole + 6
SuffixRole: int = Qt.UserRole + 7
IsSelectedRole: int = Qt.UserRole + 8
IsPreviewingRole: int = Qt.UserRole + 9
IconPixmapRole: int = Qt.UserRole + 10
CardWidthRole: int = Qt.UserRole + 11
GridOffsetRole: int = Qt.UserRole + 12


class FileListModel(QAbstractListModel):
    """    轻量文件列表数据模型。

    提供 12 个自定义角色用于视图数据访问，维护 O(1) 路径→行号索引。
    不包含异步加载、缓存池或后台线程逻辑。

    角色列表：
        FileNameRole (str):      文件名
        FilePathRole (str):      完整路径
        IsDirRole (bool):       是否目录
        FileSizeRole (int):     文件大小（字节）
        ModifiedRole (str):     修改时间（格式化）
        CreatedRole (str):      创建时间（格式化）
        SuffixRole (str):       后缀（小写，无点号）
        IsSelectedRole (bool):  是否选中
        IsPreviewingRole (bool): 是否正在预览
        IconPixmapRole (QPixmap): 文件图标
        CardWidthRole (int):    卡片动态宽度
        GridOffsetRole (int):   卡片网格水平偏移量（用于居中）
    """

    def __init__(self, parent: Optional[object] = None) -> None:
        """初始化 FileListModel。

        Args:
            parent: 父对象，通常为 QObject。
        """
        super().__init__(parent)
        self._files: List[Dict[str, Any]] = []
        self._path_to_row: Dict[str, int] = {}
        self._card_width: int = 180
        self._card_height: int = 100
        self._grid_offset_x: int = 0
        self._icon_size: int = 48
        FileIconManager().system_icon_loaded.connect(self._on_system_icon_loaded)

    # ── 公共方法 ────────────────────────────────────────────────────────────

    def set_files(self, file_list: List[Dict[str, Any]]) -> None:
        """设置文件列表，替换现有数据。

        使用 beginResetModel/endResetModel 安全重置模型。
        每个文件信息字典应包含以下键：
            name (str):     文件名
            path (str):     完整路径
            is_dir (bool):  是否目录
            size (int):     文件大小（字节）
            modified (str): 修改时间（格式化）
            created (str):  创建时间（格式化）
            suffix (str):   后缀（小写，无点号）

        Args:
            file_list: 文件信息字典列表。
        """
        self.beginResetModel()
        self._files = []
        for info in file_list:
            entry: Dict[str, Any] = {
                "name": info.get("name", ""),
                "path": info.get("path", ""),
                "is_dir": info.get("is_dir", False),
                "size": info.get("size", 0),
                "modified": info.get("modified", ""),
                "created": info.get("created", ""),
                "suffix": info.get("suffix", "").lower(),
                "is_selected": False,
                "is_previewing": False,
            }
            self._files.append(entry)
        self._rebuild_path_index()
        self.endResetModel()

    def get_row(self, file_path: str) -> int:
        """获取指定文件路径对应的行号。

        使用字典索引实现 O(1) 查找。

        Args:
            file_path: 文件完整路径。

        Returns:
            行号（0-based），如果路径不存在则返回 -1。
        """
        return self._path_to_row.get(file_path, -1)

    def toggle_selected(self, file_path: str) -> bool:
        """切换指定文件的选中状态。

        Args:
            file_path: 文件完整路径。

        Returns:
            切换后的选中状态（True 为选中，False 为未选中）。
            如果路径不存在则返回 False。
        """
        row = self.get_row(file_path)
        if row < 0:
            return False
        new_state = not self._files[row].get("is_selected", False)
        self._files[row]["is_selected"] = new_state
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx, [IsSelectedRole])
        return new_state

    def set_selected(self, file_path: str, is_selected: bool) -> bool:
        """设置指定文件的选中状态。

        Args:
            file_path: 文件完整路径。
            is_selected: 目标选中状态。

        Returns:
            如果路径存在且状态已更新则返回 True，否则返回 False。
        """
        row = self.get_row(file_path)
        if row < 0:
            return False
        if self._files[row].get("is_selected", False) != is_selected:
            self._files[row]["is_selected"] = is_selected
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx, [IsSelectedRole])
        return True

    def get_selected_files(self) -> List[str]:
        """获取所有选中文件的路径列表。

        Returns:
            选中文件的完整路径列表。
        """
        return [f["path"] for f in self._files if f.get("is_selected", False)]

    def clear(self) -> None:
        """清空文件列表和路径索引。"""
        self.beginResetModel()
        self._files.clear()
        self._path_to_row.clear()
        self.endResetModel()

    def set_card_width(self, width: int, height: int) -> None:
        """更新卡片尺寸并通知视图刷新。

        Args:
            width: 卡片宽度。
            height: 卡片高度。
        """
        if self._card_width == width and self._card_height == height:
            return
        self._card_width = width
        self._card_height = height
        if self.rowCount() > 0:
            top = self.index(0, 0)
            bottom = self.index(self.rowCount() - 1, 0)
            self.dataChanged.emit(top, bottom, [CardWidthRole])

    def set_grid_offset_x(self, offset: int) -> None:
        """设置卡片网格水平偏移量，用于整体居中。

        Args:
            offset: 水平偏移像素值。
        """
        if self._grid_offset_x == offset:
            return
        self._grid_offset_x = offset
        if self.rowCount() > 0:
            top = self.index(0, 0)
            bottom = self.index(self.rowCount() - 1, 0)
            self.dataChanged.emit(top, bottom, [GridOffsetRole])

    def update_geometry(self, card_width: int, card_height: int) -> None:
        """兼容接口：委托给 set_card_width。"""
        self.set_card_width(card_width, card_height)

    def update_theme(self) -> None:
        """主题变更时刷新所有图标。

        清空 FileIconManager 缓存（主题色敏感的缓存键会触发重新生成），
        然后发射 dataChanged 让视图重新请求图标。
        """
        FileIconManager().clear_cache()
        if self.rowCount() > 0:
            top = self.index(0, 0)
            bottom = self.index(self.rowCount() - 1, 0)
            self.dataChanged.emit(top, bottom, [IconPixmapRole])

    def get_file_info(self, index: QModelIndex) -> Dict[str, Any]:
        """获取索引对应的文件信息字典。

        Args:
            index: 模型索引。

        Returns:
            文件信息字典，无效索引返回空字典。
        """
        if not index.isValid() or index.row() >= len(self._files):
            return {}
        return {
            "name": self._files[index.row()].get("name", ""),
            "path": self._files[index.row()].get("path", ""),
            "is_dir": self._files[index.row()].get("is_dir", False),
            "size": self._files[index.row()].get("size", 0),
            "modified": self._files[index.row()].get("modified", ""),
            "created": self._files[index.row()].get("created", ""),
            "suffix": self._files[index.row()].get("suffix", ""),
            "is_selected": self._files[index.row()].get("is_selected", False),
            "is_previewing": self._files[index.row()].get("is_previewing", False),
            "card_width": self._card_width,
        }

    # ── QAbstractListModel 接口 ────────────────────────────────────────────

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """返回模型中的行数。

        Args:
            parent: 父索引（仅有效索引返回 0）。

        Returns:
            文件数量。
        """
        if parent.isValid():
            return 0
        return len(self._files)

    def sizeHint(self) -> QSize:
        """返回模型建议的项尺寸。"""
        return QSize(self._card_width, self._card_height)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        """返回指定索引和角色的数据。

        Args:
            index: 模型索引。
            role: 请求的角色。

        Returns:
            对应角色的数据，无效索引返回 None。
        """
        if not index.isValid() or index.row() >= len(self._files):
            return None

        file_info = self._files[index.row()]

        if role == Qt.DisplayRole:
            return file_info.get("name", "")
        if role == FileNameRole:
            return file_info.get("name", "")
        if role == FilePathRole:
            return file_info.get("path", "")
        if role == IsDirRole:
            return file_info.get("is_dir", False)
        if role == FileSizeRole:
            return file_info.get("size", 0)
        if role == ModifiedRole:
            return file_info.get("modified", "")
        if role == CreatedRole:
            return file_info.get("created", "")
        if role == SuffixRole:
            return file_info.get("suffix", "").lower()
        if role == IsSelectedRole:
            return file_info.get("is_selected", False)
        if role == IsPreviewingRole:
            return file_info.get("is_previewing", False)
        if role == IconPixmapRole:
            return self._get_icon_pixmap(file_info)
        if role == CardWidthRole:
            return self._card_width
        if role == GridOffsetRole:
            return self._grid_offset_x

        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.EditRole) -> bool:
        """设置指定索引和角色的数据。

        Args:
            index: 模型索引。
            value: 要设置的值。
            role: 目标角色。

        Returns:
            设置成功返回 True，否则返回 False。
        """
        if not index.isValid() or index.row() >= len(self._files):
            return False

        if role == IsSelectedRole:
            self._files[index.row()]["is_selected"] = bool(value)
            self.dataChanged.emit(index, index, [role])
            return True

        if role == IsPreviewingRole:
            self._files[index.row()]["is_previewing"] = bool(value)
            self.dataChanged.emit(index, index, [role])
            return True

        return False

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        """返回指定索引的标志位。

        Args:
            index: 模型索引。

        Returns:
            项目标志位组合。
        """
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable

    # ── 内部方法 ────────────────────────────────────────────────────────────

    def _rebuild_path_index(self) -> None:
        """重建路径→行号索引，实现 O(1) 查找。"""
        self._path_to_row.clear()
        for row, file_info in enumerate(self._files):
            path = file_info.get("path", "")
            if path:
                self._path_to_row[path] = row

    def _get_icon_pixmap(self, file_info: Dict[str, Any]) -> QPixmap:
        """获取文件图标像素图，委托给 FileIconManager。

        通过 FileIconManager 单例获取 SVG 主题图标，支持：
        - 12 种文件类型的 SVG 图标
        - 缩略图回退（图片/视频）
        - 系统图标异步加载（exe/lnk/url）
        - 双层缓存

        Args:
            file_info: 文件信息字典。

        Returns:
            文件图标 QPixmap。
        """
        if not file_info.get("path", ""):
            return QPixmap()

        icon_size = self._icon_size  # 使用专用图标尺寸（默认 48px，匹配 media_size=52 留出内边距）
        dpr = self._get_device_pixel_ratio()
        return FileIconManager().get_icon_pixmap(file_info, icon_size, dpr)

    def _get_device_pixel_ratio(self) -> float:
        """获取设备像素比（DPI 缩放因子）。

        Returns:
            设备像素比，始终为正数。
        """
        try:
            app = QApplication.instance()
            if app:
                screen = app.primaryScreen()
                if screen:
                    ratio = float(screen.devicePixelRatio())
                    if ratio > 0:
                        return ratio
        except (RuntimeError, AttributeError, TypeError, ValueError):
            pass
        return 1.0

    def _on_system_icon_loaded(self, file_path: str) -> None:
        """系统图标异步加载完成回调 — 触发对应行的视图刷新。

        当 FileIconManager 完成 .exe/.lnk/.url 文件的系统图标提取后，
        此回调查找对应的行并发射 dataChanged 信号，触发委托重绘。

        Args:
            file_path: 已加载系统图标的文件路径。
        """
        row = self.get_row(file_path)
        if row < 0:
            return
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx, [IconPixmapRole])