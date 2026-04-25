import os
import time
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QEvent, QMimeData, QModelIndex, QPoint, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from freeassetfilter.core.settings_manager import SettingsManager
from freeassetfilter.utils.app_logger import debug
from freeassetfilter.utils.file_icon_helper import get_file_icon_path
from freeassetfilter.widgets.file_selector_model import FileListView, FileSelectorListModel


class FileStagingPoolListModel(FileSelectorListModel):
    DisplayNameRole = FileSelectorListModel.CardWidthRole + 1
    OriginalNameRole = DisplayNameRole + 1
    ModifiedRole = OriginalNameRole + 1
    IsMissingRole = ModifiedRole + 1
    SizeCalculatingRole = IsMissingRole + 1
    InfoTextRole = SizeCalculatingRole + 1
    ItemHeightRole = InfoTextRole + 1
    ItemSizeRole = ItemHeightRole + 1
    IsRemovingRole = ItemSizeRole + 1

    def __init__(self, dpi_scale=1.0, global_font=None, parent=None):
        super().__init__(dpi_scale=dpi_scale, global_font=global_font, parent=parent)
        self._card_width = max(240, int(320 * float(dpi_scale or 1.0)))
        self._card_height = max(52, int(64 * float(dpi_scale or 1.0)))
        self._max_cols = 1

    def _normalize_path(self, file_path: str) -> str:
        if not file_path:
            return ""
        return os.path.normcase(os.path.normpath(file_path))

    def _display_path(self, file_path: str) -> str:
        return os.path.normpath(file_path) if file_path else ""

    def _safe_exists(self, file_path: str) -> bool:
        try:
            return bool(file_path) and os.path.exists(file_path)
        except (OSError, PermissionError, RuntimeError, TypeError, ValueError):
            return False

    def _safe_is_dir(self, file_path: str) -> bool:
        try:
            return bool(file_path) and os.path.isdir(file_path)
        except (OSError, PermissionError, RuntimeError, TypeError, ValueError):
            return False

    def _extract_suffix(self, file_info: Dict[str, Any]) -> str:
        suffix = str(file_info.get("suffix", "") or "").lower().lstrip(".")
        if suffix:
            return suffix
        name = str(file_info.get("name", "") or "")
        if name:
            return os.path.splitext(name)[1].lower().lstrip(".")
        path = str(file_info.get("path", "") or "")
        return os.path.splitext(path)[1].lower().lstrip(".") if path else ""

    @staticmethod
    def _format_file_size(size_bytes) -> str:
        if size_bytes is None:
            return ""
        try:
            size_value = float(size_bytes)
        except (TypeError, ValueError):
            return ""
        if size_value < 0:
            size_value = 0.0
        units = ["B", "KB", "MB", "GB", "TB"]
        unit_index = 0
        while size_value >= 1024 and unit_index < len(units) - 1:
            size_value /= 1024.0
            unit_index += 1
        if unit_index == 0:
            return f"{int(size_value)} {units[unit_index]}"
        return f"{size_value:.2f} {units[unit_index]}"

    def _build_info_text(self, file_info: Dict[str, Any]) -> str:
        file_path = str(file_info.get("path", "") or "")
        if file_info.get("is_missing", False):
            return file_path
        if file_info.get("is_dir", False):
            if file_info.get("size_calculating", False):
                suffix = "正在计算大小..."
            else:
                suffix = self._format_file_size(file_info.get("size")) or "文件夹"
        else:
            suffix = self._format_file_size(file_info.get("size"))
        if file_path and suffix:
            return f"{file_path}  {suffix}"
        return file_path or suffix or ""

    def _visible_display_name(self, file_info: Dict[str, Any]) -> str:
        display_name = str(file_info.get("display_name") or file_info.get("name") or "")
        if not display_name:
            display_name = os.path.basename(str(file_info.get("path", "") or ""))
        if file_info.get("is_missing", False):
            return f"{display_name}（已移动或删除）"
        return display_name

    def _prepare_file_info(self, file_info: Dict[str, Any], current: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        prepared = (current or {}).copy()
        prepared.update(file_info or {})

        path = self._display_path(str(prepared.get("path", "") or ""))
        prepared["path"] = path
        exists = self._safe_exists(path)

        if "is_dir" in prepared:
            is_dir = bool(prepared.get("is_dir", False))
        else:
            is_dir = self._safe_is_dir(path) if exists else bool((current or {}).get("is_dir", False))
        prepared["is_dir"] = is_dir

        name = str(prepared.get("name", "") or "") or (os.path.basename(path) or path)
        prepared["name"] = name
        prepared["display_name"] = str(prepared.get("display_name", "") or "") or name
        prepared["original_name"] = str(prepared.get("original_name", "") or "") or name
        prepared["suffix"] = self._extract_suffix(prepared)
        prepared["is_selected"] = False
        prepared["is_previewing"] = bool(prepared.get("is_previewing", False))
        prepared["is_removing"] = bool(prepared.get("is_removing", False))

        if "is_missing" in file_info:
            prepared["is_missing"] = bool(file_info.get("is_missing", False))
        else:
            prepared["is_missing"] = not exists

        if prepared["is_dir"]:
            if prepared["is_missing"]:
                prepared["size_calculating"] = False
            elif "size_calculating" in prepared:
                prepared["size_calculating"] = bool(prepared.get("size_calculating", False))
            else:
                prepared["size_calculating"] = prepared.get("size") is None
        else:
            prepared["size_calculating"] = False

        info_text = str(file_info.get("info_text", "") or prepared.get("info_text", "") or "")
        prepared["info_text"] = info_text or self._build_info_text(prepared)
        return prepared

    def item_size(self) -> QSize:
        return QSize(self._card_width, self._card_height)

    def set_item_size(self, width: int, height: int) -> None:
        width = max(1, int(width))
        height = max(1, int(height))
        if self._card_width == width and self._card_height == height:
            return
        self._card_width = width
        self._card_height = height
        if self.rowCount() > 0:
            top = self.index(0, 0)
            bottom = self.index(self.rowCount() - 1, 0)
            self.dataChanged.emit(top, bottom, [Qt.SizeHintRole, self.CardWidthRole, self.ItemHeightRole, self.ItemSizeRole])

    def _emit_row_changed(self, row: int, roles: Optional[List[int]] = None) -> None:
        if row < 0 or row >= len(self._files):
            return
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx, roles or [Qt.DisplayRole, Qt.DecorationRole, Qt.SizeHintRole, Qt.ToolTipRole, self.IsSelectedRole, self.IsPreviewingRole, self.IsMissingRole, self.InfoTextRole, self.DisplayNameRole])

    def _resolve_icon_source(self, file_info: Dict[str, Any]):
        file_path = str(file_info.get("path", "") or "")
        if not file_path:
            return super()._resolve_icon_source(file_info)
        if file_info.get("is_missing", False) or not self._safe_exists(file_path):
            icon_path = get_file_icon_path(file_info) or ""
            return {
                "source_type": "file_icon",
                "normalized_path": self._normalize_path(icon_path),
                "mtime": self._safe_get_mtime(icon_path),
                "icon_path": icon_path,
                "thumbnail_path": "",
                "suffix": str(file_info.get("suffix", "") or "").lower(),
                "is_dir": bool(file_info.get("is_dir", False)),
            }
        return super()._resolve_icon_source(file_info)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._files):
            return None
        file_info = self._files[index.row()]
        if role == Qt.DisplayRole:
            return self._visible_display_name(file_info)
        if role == Qt.DecorationRole:
            return self._get_icon_pixmap(file_info)
        if role == Qt.SizeHintRole:
            return self.item_size()
        if role == Qt.ToolTipRole:
            display_name = self._visible_display_name(file_info)
            info_text = str(file_info.get("info_text", "") or file_info.get("path", "") or "")
            return f"{display_name}\n{info_text}" if info_text and info_text != display_name else display_name
        if role == self.DisplayNameRole:
            return str(file_info.get("display_name", "") or "")
        if role == self.OriginalNameRole:
            return str(file_info.get("original_name", "") or "")
        if role == self.ModifiedRole:
            return file_info.get("modified", "")
        if role == self.IsMissingRole:
            return bool(file_info.get("is_missing", False))
        if role == self.SizeCalculatingRole:
            return bool(file_info.get("size_calculating", False))
        if role == self.InfoTextRole:
            return str(file_info.get("info_text", "") or "")
        if role == self.ItemHeightRole:
            return self._card_height
        if role == self.ItemSizeRole:
            return self.item_size()
        if role == self.IsRemovingRole:
            return bool(file_info.get("is_removing", False))
        return super().data(index, role)

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:
        if not index.isValid() or index.row() >= len(self._files):
            return False
        path = str(self._files[index.row()].get("path", "") or "")
        if role == self.DisplayNameRole:
            return self.update_file(path, {"display_name": str(value or "")})
        if role == self.InfoTextRole:
            return self.update_file(path, {"info_text": str(value or "")})
        if role == self.IsMissingRole:
            return self.update_file(path, {"is_missing": bool(value)})
        if role == self.SizeCalculatingRole:
            return self.update_file(path, {"size_calculating": bool(value)})
        if role == self.IsRemovingRole:
            return self.update_file(path, {"is_removing": bool(value)})
        return super().setData(index, value, role)

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags
        if bool(index.data(self.IsRemovingRole)):
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled

    def roleNames(self) -> Dict[int, bytes]:
        roles = super().roleNames()
        roles.update({
            self.DisplayNameRole: b"displayName",
            self.OriginalNameRole: b"originalName",
            self.ModifiedRole: b"modified",
            self.IsMissingRole: b"isMissing",
            self.SizeCalculatingRole: b"sizeCalculating",
            self.InfoTextRole: b"infoText",
            self.ItemHeightRole: b"itemHeight",
            self.ItemSizeRole: b"itemSize",
            self.IsRemovingRole: b"isRemoving",
        })
        return roles

    def mimeTypes(self) -> List[str]:
        return ["text/uri-list"]

    def mimeData(self, indexes) -> QMimeData:
        mime_data = QMimeData()
        urls = []
        seen = set()
        for index in indexes:
            if not index.isValid():
                continue
            path = str(self.data(index, self.FilePathRole) or "")
            key = self._normalize_path(path)
            if not path or key in seen:
                continue
            seen.add(key)
            urls.append(QUrl.fromLocalFile(path))
        if urls:
            mime_data.setUrls(urls)
        return mime_data

    def supportedDragActions(self):
        return Qt.CopyAction | Qt.MoveAction

    def set_files(self, file_list: List[Dict[str, Any]]) -> None:
        items = []
        seen = set()
        for file_info in file_list:
            prepared = self._prepare_file_info(file_info)
            key = self._normalize_path(prepared.get("path", ""))
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            items.append(prepared)
        self.beginResetModel()
        self._files = items
        self._rebuild_path_index()
        self.endResetModel()

    def add_file(self, file_info: Dict[str, Any]) -> bool:
        prepared = self._prepare_file_info(file_info)
        key = self._normalize_path(prepared.get("path", ""))
        if key and key in self._path_to_row:
            return False
        row = len(self._files)
        self.beginInsertRows(QModelIndex(), row, row)
        self._files.append(prepared)
        if key:
            self._path_to_row[key] = row
        self.endInsertRows()
        return True

    def add_files(self, file_list: List[Dict[str, Any]]) -> int:
        added = 0
        for file_info in file_list:
            if self.add_file(file_info):
                added += 1
        return added

    def remove_file(self, file_path: str) -> Dict[str, Any]:
        row = self.get_row(file_path)
        if row < 0:
            return {}
        if self._files[row].get("is_removing", False):
            return {}
        self._files[row]["is_removing"] = True
        removed_info = self._files[row].copy()
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx, [self.IsRemovingRole])
        return removed_info

    def finalize_remove_file(self, file_path: str) -> Dict[str, Any]:
        row = self.get_row(file_path)
        if row < 0:
            return {}
        removed_info = self._files[row].copy()
        self.beginRemoveRows(QModelIndex(), row, row)
        self._files.pop(row)
        self.endRemoveRows()
        self._rebuild_path_index()
        return removed_info

    def update_file(self, file_path: str, updates: Dict[str, Any]) -> bool:
        """
        更新指定文件项，并在关键信息变化时按最新状态重建说明文本。

        Args:
            file_path (str): 待更新文件项的路径。
            updates (Dict[str, Any]): 需要合并到文件项中的字段。

        Returns:
            bool: 更新成功返回 True；目标项不存在或新路径冲突时返回 False。

        异常场景:
            本函数不主动抛出异常，异常状态通过返回 False 表示。
        """
        row = self.get_row(file_path)
        if row < 0:
            return False
        current = self._files[row]
        update_payload = updates or {}
        new_info = current.copy()
        new_info.update(update_payload)

        refresh_info_keys = {"size", "size_calculating", "is_missing", "is_dir", "path"}
        current_for_prepare = current
        if "info_text" not in update_payload and any(key in update_payload for key in refresh_info_keys):
            # 相关字段发生变化时，移除旧说明文本并在预处理阶段按最新状态重新生成。
            new_info.pop("info_text", None)
            current_for_prepare = current.copy()
            current_for_prepare.pop("info_text", None)

        prepared = self._prepare_file_info(new_info, current_for_prepare)
        old_key = self._normalize_path(current.get("path", ""))
        new_key = self._normalize_path(prepared.get("path", ""))
        if new_key and new_key != old_key and new_key in self._path_to_row:
            return False
        self._files[row] = prepared
        if new_key != old_key:
            self._rebuild_path_index()
        self._emit_row_changed(row)
        return True

    def rename_file(self, file_path: str, display_name: str) -> bool:
        name = str(display_name or "").strip()
        if not name:
            row = self.get_row(file_path)
            if row < 0:
                return False
            name = str(self._files[row].get("name", "") or "")
        return self.update_file(file_path, {"display_name": name})

    def has_path(self, file_path: str) -> bool:
        return self.get_row(file_path) >= 0

    def index_from_path(self, file_path: str) -> QModelIndex:
        row = self.get_row(file_path)
        return self.index(row, 0) if row >= 0 else QModelIndex()

    def get_file_info_by_path(self, file_path: str) -> Dict[str, Any]:
        row = self.get_row(file_path)
        return self._files[row].copy() if row >= 0 else {}

    def refresh_icon(self, file_path: str) -> bool:
        row = self.get_row(file_path)
        if row < 0:
            return False
        old_info = self._files[row]
        old_source = self._resolve_icon_source(old_info)
        refreshed_input = old_info.copy()
        refreshed_input.pop("is_missing", None)
        refreshed_input.pop("info_text", None)
        refreshed = self._prepare_file_info(refreshed_input, old_info)
        new_source = self._resolve_icon_source(refreshed)
        self.clear_caches(file_path)
        old_source_path = str(old_source.get("normalized_path", "") or "")
        new_source_path = str(new_source.get("normalized_path", "") or "")
        if old_source_path:
            self.clear_caches(old_source_path)
        if new_source_path and new_source_path != old_source_path:
            self.clear_caches(new_source_path)
        self._files[row] = refreshed
        self._emit_row_changed(row, [Qt.DecorationRole, self.IconPixmapRole, self.IsMissingRole, self.InfoTextRole])
        return True


class FileStagingPoolItemDelegate(QStyledItemDelegate):
    def __init__(self, dpi_scale=1.0, global_font=None, parent=None):
        super().__init__(parent)
        self._dpi_scale = float(dpi_scale or 1.0)
        self._global_font = global_font
        self._dragging_file_path = ""

    def set_dragging_file_path(self, file_path: Optional[str]) -> None:
        self._dragging_file_path = os.path.normcase(os.path.normpath(file_path)) if file_path else ""

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        model = index.model()
        if isinstance(model, FileStagingPoolListModel):
            return model.item_size()
        return QSize(320, 64)

    def _colors(self):
        app = QApplication.instance()
        settings_manager = getattr(app, "settings_manager", None) if app else None
        if settings_manager is None:
            settings_manager = SettingsManager()
        return {
            "base": settings_manager.get_setting("appearance.colors.base_color", "#212121"),
            "aux": settings_manager.get_setting("appearance.colors.auxiliary_color", "#313131"),
            "normal": settings_manager.get_setting("appearance.colors.normal_color", "#717171"),
            "accent": settings_manager.get_setting("appearance.colors.accent_color", "#B036EE"),
            "secondary": settings_manager.get_setting("appearance.colors.secondary_color", "#FFFFFF"),
        }

    def build_drag_pixmap(self, index: QModelIndex, preview_size: QSize, palette) -> QPixmap:
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, preview_size.width(), preview_size.height())
        pixmap = QPixmap(preview_size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, option, index)
        painter.end()
        return pixmap

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        model = index.model()
        if not isinstance(model, FileStagingPoolListModel):
            super().paint(painter, option, index)
            return

        colors = self._colors()
        rect = option.rect.adjusted(2, 2, -2, -2)
        file_path = str(index.data(model.FilePathRole) or "")
        path_key = os.path.normcase(os.path.normpath(file_path)) if file_path else ""
        is_dragging = bool(self._dragging_file_path and path_key == self._dragging_file_path)
        is_selected = bool(index.data(model.IsSelectedRole))
        is_previewing = bool(index.data(model.IsPreviewingRole))
        is_missing = bool(index.data(model.IsMissingRole))
        display_name = str(index.data(model.DisplayNameRole) or index.data(Qt.DisplayRole) or "")
        info_text = str(index.data(model.InfoTextRole) or "")
        icon = index.data(Qt.DecorationRole)

        bg = QColor(colors["base"])
        border = QColor(colors["normal"])
        text = QColor(colors["secondary"])
        sub_text = QColor(colors["normal"])
        if is_selected:
            bg = QColor(colors["accent"])
            bg.setAlpha(36)
            border = QColor(colors["accent"])
        if is_previewing:
            bg = QColor(colors["accent"])
            bg.setAlpha(52)
            border = QColor(colors["secondary"])
        if is_missing:
            sub_text = QColor(colors["secondary"])
            sub_text.setAlpha(170)
            text = QColor(colors["secondary"])
            text.setAlpha(210)
            if not is_selected and not is_previewing:
                bg = QColor(colors["aux"])
        if is_dragging:
            bg.setAlpha(max(18, bg.alpha() // 2 or 18))
            text.setAlpha(120)
            sub_text.setAlpha(100)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = border
        if is_missing:
            painter.setPen(QColor(border))
            dash_pen = painter.pen()
            dash_pen.setColor(border)
            dash_pen.setStyle(Qt.DashLine)
            painter.setPen(dash_pen)
        else:
            painter.setPen(border)
        painter.setBrush(bg)
        painter.drawRoundedRect(QRectF(rect), 8.0, 8.0)

        icon_size = max(28, int(38 * self._dpi_scale))
        margin_x = max(8, int(10 * self._dpi_scale))
        icon_rect = QRect(rect.left() + margin_x, rect.center().y() - icon_size // 2, icon_size, icon_size)
        if isinstance(icon, QPixmap) and not icon.isNull():
            painter.drawPixmap(icon_rect, icon)

        text_left = icon_rect.right() + max(8, int(10 * self._dpi_scale))
        text_rect = QRect(text_left, rect.top() + max(6, int(7 * self._dpi_scale)), rect.right() - text_left - margin_x, rect.height() - max(12, int(14 * self._dpi_scale)))

        title_font = QFont(self._global_font) if self._global_font else QFont()
        title_font.setBold(True)
        title_font.setPixelSize(max(12, int(13 * self._dpi_scale)))
        info_font = QFont(self._global_font) if self._global_font else QFont()
        info_font.setPixelSize(max(10, int(11 * self._dpi_scale)))

        title_metrics = QFontMetrics(title_font)
        info_metrics = QFontMetrics(info_font)
        title_text = title_metrics.elidedText(display_name, Qt.ElideRight, text_rect.width())
        info_text = info_metrics.elidedText(info_text, Qt.ElideMiddle, text_rect.width())

        title_height = title_metrics.height()
        info_height = info_metrics.height()
        title_rect = QRect(text_rect.left(), text_rect.top(), text_rect.width(), title_height)
        info_rect = QRect(text_rect.left(), text_rect.bottom() - info_height, text_rect.width(), info_height)

        painter.setFont(title_font)
        painter.setPen(text)
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, title_text)
        painter.setFont(info_font)
        painter.setPen(sub_text)
        painter.drawText(info_rect, Qt.AlignLeft | Qt.AlignVCenter, info_text)
        painter.restore()


class FileStagingPoolListView(FileListView):
    item_left_clicked = Signal(dict)
    item_right_clicked = Signal(dict)
    item_double_clicked = Signal(dict)
    drag_started = Signal(dict)
    drag_ended = Signal(dict, str)

    def __init__(self, dpi_scale=1.0, global_font=None, parent=None):
        self._dpi_scale = float(dpi_scale or 1.0)
        self._global_font = global_font
        self._delegate = None
        self._action_press_index = QModelIndex()
        self._card_motion_model = None
        self._card_motion_items: Dict[str, Dict[str, Any]] = {}
        self._card_motion_exit_items: List[Dict[str, Any]] = []
        self._card_motion_pending_insert_rects: Dict[str, QRect] = {}
        self._card_motion_pending_insert_keys = set()
        self._card_motion_insert_finalize_scheduled = False
        self._card_motion_pending_removals: List[Dict[str, Any]] = []
        self._card_motion_pending_finalize_keys = set()
        self._card_motion_manual_finalize_active = False
        self._card_motion_start_ms = 0.0
        self._card_motion_capturing = False
        self._card_motion_enabled = True
        self._card_motion_duration_ms = 105
        super().__init__(parent)
        self._card_motion_timer = QTimer(self)
        self._card_motion_timer.setInterval(16)
        self._card_motion_timer.timeout.connect(self._advance_card_motion)
        self._delegate = FileStagingPoolItemDelegate(self._dpi_scale, self._global_font, self)
        self.setItemDelegate(self._delegate)
        self.file_clicked.connect(self.item_left_clicked.emit)
        self.file_right_clicked.connect(self.item_right_clicked.emit)
        self.file_double_clicked.connect(self.item_double_clicked.emit)
        self.file_drag_started.connect(self.drag_started.emit)
        self.file_drag_ended.connect(self.drag_ended.emit)
        self._sync_item_size()

    def _setup_view(self) -> None:
        self.setViewMode(QListView.ListMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setSelectionMode(QListView.NoSelection)
        self.setUniformItemSizes(True)
        self.setLayoutMode(QListView.Batched)
        self.setWrapping(False)
        self.setFlow(QListView.TopToBottom)
        self.setSpacing(max(2, int(4 * self._dpi_scale)))
        self.setEditTriggers(QListView.NoEditTriggers)
        self.setSelectionRectVisible(False)
        self.setSelectionBehavior(QListView.SelectRows)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        self.setDropIndicatorShown(False)
        self.setDefaultDropAction(Qt.CopyAction)

    def _load_interaction_settings(self) -> None:
        app = QApplication.instance()
        settings_manager = getattr(app, "settings_manager", None) if app else None
        if settings_manager is None:
            settings_manager = SettingsManager()
        try:
            staging_touch = settings_manager.get_setting("file_staging.touch_optimization", None)
            staging_swap = settings_manager.get_setting("file_staging.mouse_buttons_swap", None)
            selector_touch = settings_manager.get_setting("file_selector.touch_optimization", True)
            selector_swap = settings_manager.get_setting("file_selector.mouse_buttons_swap", False)
            self._touch_optimization_enabled = bool(selector_touch if staging_touch is None else staging_touch)
            self._mouse_buttons_swapped = bool(selector_swap if staging_swap is None else staging_swap)
        except (RuntimeError, TypeError, ValueError) as error:
            debug(f"加载暂存池交互设置失败: {error}")
            self._touch_optimization_enabled = True
            self._mouse_buttons_swapped = False
        self._touch_drag_threshold = int(10 * self._dpi_scale)
        self._long_press_duration = 500

    def _detect_drop_target(self, global_pos) -> str:
        main_window = self.window()
        if not main_window:
            return "none"
        selector = getattr(main_window, "file_selector_a", None) or getattr(main_window, "file_selector", None)
        if selector and selector.isVisible():
            selector_rect = QRect(selector.mapToGlobal(selector.rect().topLeft()), selector.rect().size())
            if selector_rect.contains(global_pos):
                return "file_selector"
        previewer = getattr(main_window, "unified_previewer", None)
        if previewer and previewer.isVisible():
            previewer_rect = QRect(previewer.mapToGlobal(previewer.rect().topLeft()), previewer.rect().size())
            if previewer_rect.contains(global_pos):
                return "previewer"
        return "none"

    def _resolve_action_delegate(self, index: QModelIndex):
        if not index.isValid():
            return None
        delegate = self.itemDelegateForIndex(index) or self.itemDelegate()
        if delegate is None:
            return None
        if not hasattr(delegate, "action_at") or not hasattr(delegate, "editorEvent"):
            return None
        return delegate

    def _create_action_option(self, index: QModelIndex) -> QStyleOptionViewItem:
        option = QStyleOptionViewItem()
        if hasattr(self, "initViewItemOption"):
            self.initViewItemOption(option)
        option.rect = self.visualRect(index)
        option.widget = self.viewport()
        option.state |= QStyle.State_MouseOver
        return option

    def _action_at_pos(self, index: QModelIndex, pos, require_visible: bool = False):
        delegate = self._resolve_action_delegate(index)
        if delegate is None:
            return None
        option = self._create_action_option(index)
        try:
            return delegate.action_at(option, index, pos, require_visible=require_visible)
        except Exception as error:
            debug(f"命中文件存储池操作按钮失败: {error}")
            return None

    def _dispatch_action_delegate_event(self, event, index: QModelIndex) -> bool:
        delegate = self._resolve_action_delegate(index)
        model = self.model()
        if delegate is None or model is None:
            return False
        option = self._create_action_option(index)
        try:
            return bool(delegate.editorEvent(event, model, option, index))
        except Exception as error:
            debug(f"分发文件存储池操作按钮事件失败: {error}")
            return False

    @staticmethod
    def _event_pos(event) -> QPoint:
        if hasattr(event, "position"):
            try:
                return event.position().toPoint()
            except (RuntimeError, TypeError, ValueError):
                pass
        if hasattr(event, "pos"):
            try:
                return event.pos()
            except (RuntimeError, TypeError, ValueError):
                pass
        return QPoint(-1, -1)

    def setModel(self, model) -> None:
        self._disconnect_card_motion_model()
        self.cancel_card_motion(update=False)
        super().setModel(model)
        self._connect_card_motion_model(model)
        self._sync_item_size()

    def _connect_card_motion_model(self, model) -> None:
        if not isinstance(model, FileStagingPoolListModel):
            self._card_motion_model = None
            return

        self._card_motion_model = model
        model.rowsAboutToBeInserted.connect(self._on_rows_about_to_be_inserted)
        model.rowsInserted.connect(self._on_rows_inserted)
        model.rowsAboutToBeRemoved.connect(self._on_rows_about_to_be_removed)
        model.rowsRemoved.connect(self._on_rows_removed)
        model.dataChanged.connect(self._on_model_data_changed)
        model.modelAboutToBeReset.connect(self._on_model_about_to_reset)

    def _disconnect_card_motion_model(self) -> None:
        model = self._card_motion_model
        if model is None:
            return

        for signal, slot in (
            (model.rowsAboutToBeInserted, self._on_rows_about_to_be_inserted),
            (model.rowsInserted, self._on_rows_inserted),
            (model.rowsAboutToBeRemoved, self._on_rows_about_to_be_removed),
            (model.rowsRemoved, self._on_rows_removed),
            (model.dataChanged, self._on_model_data_changed),
            (model.modelAboutToBeReset, self._on_model_about_to_reset),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._card_motion_model = None

    def _card_motion_now_ms(self) -> float:
        return time.monotonic() * 1000.0

    def _normalize_motion_path(self, file_path: str) -> str:
        return os.path.normcase(os.path.normpath(file_path)) if file_path else ""

    def _motion_key_for_index(self, index: QModelIndex) -> str:
        if not index.isValid():
            return ""
        model = index.model()
        if not isinstance(model, FileStagingPoolListModel):
            return ""
        file_path = str(model.data(index, FileStagingPoolListModel.FilePathRole) or "")
        return self._normalize_motion_path(file_path)

    def _visible_row_window(self, extra_rows: int = 3) -> tuple[int, int]:
        model = self.model()
        if not isinstance(model, FileStagingPoolListModel):
            return 0, -1

        row_count = model.rowCount()
        if row_count <= 0:
            return 0, -1

        row_height = max(1, self.gridSize().height() or model.item_size().height() + self.spacing())
        scroll_value = self.verticalScrollBar().value() if self.verticalScrollBar() is not None else 0
        first = max(0, int(scroll_value // row_height) - extra_rows)
        last = min(row_count - 1, int((scroll_value + self.viewport().height()) // row_height) + extra_rows)
        return first, last

    def _snapshot_visible_item_rects(self, extra_rows: int = 3) -> Dict[str, QRect]:
        model = self.model()
        if not isinstance(model, FileStagingPoolListModel):
            return {}

        first, last = self._visible_row_window(extra_rows)
        if last < first:
            return {}

        guard = self.viewport().rect().adjusted(0, -self.gridSize().height() * extra_rows, 0, self.gridSize().height() * extra_rows)
        rects: Dict[str, QRect] = {}
        for row in range(first, last + 1):
            index = model.index(row, 0)
            key = self._motion_key_for_index(index)
            if not key:
                continue
            rect = self.visualRect(index)
            if rect.isValid() and rect.intersects(guard):
                rects[key] = QRect(rect)
        return rects

    def _slide_offset_for_rect(self, rect: QRect) -> int:
        width = rect.width() if rect.isValid() else self.viewport().width()
        return max(28, min(96, int(width * 0.18)))

    def _ease_card_motion(self, progress: float, curve: str = "out_cubic") -> float:
        t = max(0.0, min(1.0, float(progress)))
        if curve == "in_cubic":
            return t * t * t
        if curve == "in_out_cubic":
            if t < 0.5:
                return 4.0 * t * t * t
            return 1.0 - pow(-2.0 * t + 2.0, 3) / 2.0
        if curve == "out_quint":
            return 1.0 - pow(1.0 - t, 5)
        return 1.0 - pow(1.0 - t, 3)

    def _card_motion_progress(self, duration_ms: int = None) -> float:
        if self._card_motion_start_ms <= 0.0:
            return 1.0
        duration = max(1.0, float(duration_ms or self._card_motion_duration_ms))
        elapsed = self._card_motion_now_ms() - self._card_motion_start_ms
        return max(0.0, min(1.0, elapsed / duration))

    def _render_exit_pixmap(self, index: QModelIndex, source_rect: QRect) -> QPixmap:
        if not index.isValid() or not source_rect.isValid() or source_rect.width() <= 0 or source_rect.height() <= 0:
            return QPixmap()

        viewport = self.viewport()
        dpr = max(1.0, float(viewport.devicePixelRatioF()))
        pixmap = QPixmap(max(1, int(source_rect.width() * dpr)), max(1, int(source_rect.height() * dpr)))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.transparent)

        option = QStyleOptionViewItem()
        if hasattr(self, "initViewItemOption"):
            self.initViewItemOption(option)
        option.rect = QRect(0, 0, source_rect.width(), source_rect.height())
        option.widget = viewport
        option.state |= QStyle.State_Enabled

        delegate = self.itemDelegateForIndex(index) or self.itemDelegate()
        if delegate is None:
            return pixmap

        painter = QPainter(pixmap)
        self._card_motion_capturing = True
        try:
            delegate.paint(painter, option, index)
        finally:
            self._card_motion_capturing = False
            painter.end()
        return pixmap

    def _make_move_animation(self, start_rect: QRect, end_rect: QRect) -> Dict[str, Any]:
        return {
            "start_rect": QRect(start_rect),
            "end_rect": QRect(end_rect),
            "start_opacity": 1.0,
            "end_opacity": 1.0,
            "easing": "in_out_cubic",
        }

    def _make_enter_animation(self, end_rect: QRect) -> Dict[str, Any]:
        start_rect = QRect(end_rect)
        start_rect.translate(-self._slide_offset_for_rect(end_rect), 0)
        return {
            "start_rect": start_rect,
            "end_rect": QRect(end_rect),
            "start_opacity": 0.0,
            "end_opacity": 1.0,
            "easing": "out_quint",
        }

    def _start_card_motion(self) -> None:
        if not self._card_motion_enabled or not self.isVisible():
            self.cancel_card_motion(update=False)
            return
        if not self._card_motion_items and not self._card_motion_exit_items:
            return
        self._card_motion_start_ms = self._card_motion_now_ms()
        if not self._card_motion_timer.isActive():
            self._card_motion_timer.start()
        self.viewport().update()

    def cancel_card_motion(self, update: bool = True) -> None:
        timer = getattr(self, "_card_motion_timer", None)
        if timer is not None:
            timer.stop()
        self._card_motion_items.clear()
        self._card_motion_exit_items.clear()
        self._card_motion_pending_insert_rects = {}
        self._card_motion_pending_insert_keys.clear()
        self._card_motion_insert_finalize_scheduled = False
        self._card_motion_pending_removals.clear()
        self._card_motion_pending_finalize_keys.clear()
        self._card_motion_manual_finalize_active = False
        self._card_motion_start_ms = 0.0
        if update and self.viewport() is not None:
            self.viewport().update()

    def _advance_card_motion(self) -> None:
        if not self._card_motion_items and not self._card_motion_exit_items:
            self.cancel_card_motion(update=False)
            return

        if self._card_motion_progress() >= 1.0:
            self.cancel_card_motion(update=True)
            return

        self.viewport().update()

    def card_motion_paint_parameters(self, index: QModelIndex, current_rect: QRect):
        if self._card_motion_capturing or not self._card_motion_items:
            return None

        animation = self._card_motion_items.get(self._motion_key_for_index(index))
        if not animation:
            return None

        progress = self._card_motion_progress()
        eased = self._ease_card_motion(progress, animation.get("easing", "out_cubic"))
        start_rect = animation["start_rect"]
        end_rect = animation["end_rect"]
        x = start_rect.x() + (end_rect.x() - start_rect.x()) * eased
        y = start_rect.y() + (end_rect.y() - start_rect.y()) * eased
        opacity = animation["start_opacity"] + (animation["end_opacity"] - animation["start_opacity"]) * eased
        return {
            "dx": int(round(x - current_rect.x())),
            "dy": int(round(y - current_rect.y())),
            "opacity": max(0.0, min(1.0, opacity)),
        }

    def _on_rows_about_to_be_inserted(self, _parent: QModelIndex, _first: int, _last: int) -> None:
        if self._card_motion_insert_finalize_scheduled:
            return
        self.cancel_card_motion(update=False)
        self._card_motion_pending_insert_rects = self._snapshot_visible_item_rects()

    def _on_rows_inserted(self, _parent: QModelIndex, first: int, last: int) -> None:
        model = self.model()
        if isinstance(model, FileStagingPoolListModel):
            for row in range(max(0, first), min(model.rowCount() - 1, last) + 1):
                key = self._motion_key_for_index(model.index(row, 0))
                if key:
                    self._card_motion_pending_insert_keys.add(key)

        if self._card_motion_insert_finalize_scheduled:
            return

        self._card_motion_insert_finalize_scheduled = True
        QTimer.singleShot(0, self._finish_pending_insert_card_motion)

    def _finish_pending_insert_card_motion(self) -> None:
        old_rects = dict(self._card_motion_pending_insert_rects)
        inserted_keys = set(self._card_motion_pending_insert_keys)
        self._card_motion_pending_insert_rects = {}
        self._card_motion_pending_insert_keys.clear()
        self._card_motion_insert_finalize_scheduled = False

        model = self.model()
        if not isinstance(model, FileStagingPoolListModel):
            return

        animations: Dict[str, Dict[str, Any]] = {}
        new_rects = self._snapshot_visible_item_rects()
        for key, end_rect in new_rects.items():
            if key in inserted_keys:
                animations[key] = self._make_enter_animation(end_rect)
                continue
            start_rect = old_rects.get(key)
            if start_rect is not None and start_rect != end_rect:
                animations[key] = self._make_move_animation(start_rect, end_rect)

        self._card_motion_items = animations
        self._card_motion_exit_items = []
        self._start_card_motion()

    def _on_rows_about_to_be_removed(self, _parent: QModelIndex, first: int, last: int) -> None:
        if self._card_motion_manual_finalize_active:
            return

        self.cancel_card_motion(update=False)
        self._card_motion_pending_removals.append(
            self._build_remove_card_motion_pending(first, last, capture_exit=True)
        )

    def _build_remove_card_motion_pending(self, first: int, last: int, capture_exit: bool) -> Dict[str, Any]:
        pending = {
            "old_rects": {},
            "exit_items": [],
            "move_items": {},
        }

        model = self.model()
        if not isinstance(model, FileStagingPoolListModel):
            return pending

        old_rects = self._snapshot_visible_item_rects()
        guard = self.viewport().rect().adjusted(0, -self.gridSize().height(), 0, self.gridSize().height())
        exit_items = []
        removed_span_height = 0
        move_items: Dict[str, Dict[str, QRect]] = {}
        for row in range(max(0, first), min(model.rowCount() - 1, last) + 1):
            index = model.index(row, 0)
            if capture_exit is False or bool(model.data(index, FileStagingPoolListModel.IsRemovingRole)):
                rect = self.visualRect(index)
                if rect.isValid():
                    removed_span_height += max(1, rect.height() + self.spacing())
                continue
            rect = self.visualRect(index)
            if not rect.isValid() or not rect.intersects(guard):
                continue
            removed_span_height += max(1, rect.height() + self.spacing())
            pixmap = self._render_exit_pixmap(index, rect)
            if not pixmap.isNull():
                exit_items.append({
                    "rect": QRect(rect),
                    "pixmap": pixmap,
                    "easing": "in_cubic",
                })

        if removed_span_height <= 0:
            grid_height = self.gridSize().height()
            removed_span_height = max(1, grid_height or int((last - first + 1) * (self.spacing() + 1)))

        for row in range(max(0, last + 1), model.rowCount()):
            index = model.index(row, 0)
            key = self._motion_key_for_index(index)
            start_rect = old_rects.get(key)
            if start_rect is None:
                start_rect = QRect(self.visualRect(index))
            if not key or start_rect is None or not start_rect.isValid() or not start_rect.intersects(guard):
                continue
            end_rect = QRect(start_rect)
            end_rect.translate(0, -removed_span_height)
            move_items[key] = {
                "start_rect": QRect(start_rect),
                "end_rect": end_rect,
            }

        pending = {
            "old_rects": old_rects,
            "exit_items": exit_items,
            "move_items": move_items,
        }
        return pending

    def _on_rows_removed(self, _parent: QModelIndex, _first: int, _last: int) -> None:
        if self._card_motion_manual_finalize_active:
            return

        pending = self._card_motion_pending_removals.pop(0) if self._card_motion_pending_removals else {"old_rects": {}, "exit_items": []}
        self.doItemsLayout()
        self._finish_remove_card_motion(pending)

    def _finish_remove_card_motion(self, pending: Dict[str, Any]) -> None:
        model = self.model()
        if not isinstance(model, FileStagingPoolListModel):
            return

        animations: Dict[str, Dict[str, Any]] = {}
        move_items = pending.get("move_items", {})
        for key, rects in move_items.items():
            start_rect = rects.get("start_rect")
            end_rect = rects.get("end_rect")
            if start_rect is not None and end_rect is not None and start_rect != end_rect:
                animations[key] = self._make_move_animation(start_rect, end_rect)

        old_rects = pending.get("old_rects", {})
        new_rects = self._snapshot_visible_item_rects()
        for key, end_rect in new_rects.items():
            if key in animations:
                continue
            start_rect = old_rects.get(key)
            if start_rect is not None and start_rect != end_rect:
                animations[key] = self._make_move_animation(start_rect, end_rect)

        self._card_motion_items = animations
        self._card_motion_exit_items = list(pending.get("exit_items", []))
        self._start_card_motion()

    def _make_exit_animation(self, start_rect: QRect) -> Dict[str, Any]:
        end_rect = QRect(start_rect)
        end_rect.translate(-self._slide_offset_for_rect(start_rect), 0)
        return {
            "start_rect": QRect(start_rect),
            "end_rect": end_rect,
            "start_opacity": 1.0,
            "end_opacity": 0.0,
            "easing": "in_cubic",
        }

    def _on_model_data_changed(self, top_left: QModelIndex, bottom_right: QModelIndex, roles=None) -> None:
        model = self.model()
        if not isinstance(model, FileStagingPoolListModel):
            return

        if roles and FileStagingPoolListModel.IsRemovingRole not in roles:
            return

        animations = dict(self._card_motion_items)
        needs_motion = False
        for row in range(top_left.row(), bottom_right.row() + 1):
            index = model.index(row, 0)
            if not index.isValid() or not bool(model.data(index, FileStagingPoolListModel.IsRemovingRole)):
                continue

            key = self._motion_key_for_index(index)
            if not key or key in self._card_motion_pending_finalize_keys:
                continue

            rect = self.visualRect(index)
            if rect.isValid():
                animations[key] = self._make_exit_animation(rect)
                needs_motion = True
            self._card_motion_pending_finalize_keys.add(key)
            file_path = str(model.data(index, FileStagingPoolListModel.FilePathRole) or "")
            QTimer.singleShot(
                self._card_motion_duration_ms,
                lambda path=file_path, key=key: self._finalize_marked_removal(path, key),
            )

        if needs_motion:
            self._card_motion_items = animations
            self._card_motion_exit_items = []
            self._start_card_motion()

    def _finalize_marked_removal(self, file_path: str, key: str) -> None:
        self._card_motion_pending_finalize_keys.discard(key)
        model = self.model()
        if not isinstance(model, FileStagingPoolListModel):
            return

        row = model.get_row(file_path)
        if row < 0:
            return

        pending = self._build_remove_card_motion_pending(row, row, capture_exit=False)
        self._card_motion_manual_finalize_active = True
        try:
            model.finalize_remove_file(file_path)
        finally:
            self._card_motion_manual_finalize_active = False
        self.doItemsLayout()
        self._finish_remove_card_motion(pending)

    def _on_model_about_to_reset(self) -> None:
        self.cancel_card_motion(update=False)

    def _paint_card_exit_overlays(self) -> None:
        if self._card_motion_capturing or not self._card_motion_exit_items:
            return

        progress = self._card_motion_progress()
        painter = QPainter(self.viewport())
        try:
            for item in self._card_motion_exit_items:
                rect = item["rect"]
                pixmap = item["pixmap"]
                eased = self._ease_card_motion(progress, item.get("easing", "in_cubic"))
                dx = -int(round(self._slide_offset_for_rect(rect) * eased))
                opacity = max(0.0, min(1.0, 1.0 - self._ease_card_motion(progress, "out_cubic")))
                if opacity <= 0.0:
                    continue
                painter.save()
                painter.setOpacity(opacity)
                painter.drawPixmap(rect.topLeft() + QPoint(dx, 0), pixmap)
                painter.restore()
        finally:
            painter.end()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if getattr(self, "_path_transition_active", False) or getattr(self, "_path_transition_waiting_for_incoming", False):
            return
        self._paint_card_exit_overlays()

    def _sync_item_size(self) -> None:
        model = self.model()
        if not isinstance(model, FileStagingPoolListModel):
            return
        width = max(240, self.viewport().width() - 4)
        height = model.item_size().height()
        model.set_item_size(width, height)
        self.setGridSize(QSize(width, height + self.spacing()))

    def resizeEvent(self, event) -> None:
        self.cancel_card_motion(update=False)
        self._sync_item_size()
        super().resizeEvent(event)

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        if dx or dy:
            self.cancel_card_motion(update=False)
        super().scrollContentsBy(dx, dy)

    def mousePressEvent(self, event) -> None:
        event_pos = self._event_pos(event)
        index = self.indexAt(event_pos)
        logical_button = self._current_action_button(event.button())
        if logical_button == Qt.LeftButton and index.isValid():
            action = self._action_at_pos(index, event_pos, require_visible=False)
            if action:
                # FileListView 会提前消费左键按下/抬起流程，这里先把按钮事件交给委托，
                # 避免按钮点击被普通卡片点击或长按拖拽逻辑吞掉。
                self._cleanup_press_state()
                self._action_press_index = index
                self._dispatch_action_delegate_event(event, index)
                event.accept()
                return

        self._action_press_index = QModelIndex()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        event_pos = self._event_pos(event)
        target_index = self._action_press_index if self._action_press_index.isValid() else self.indexAt(event_pos)
        if target_index.isValid():
            self._dispatch_action_delegate_event(event, target_index)
        else:
            self.viewport().unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        logical_button = self._current_action_button(event.button())
        if logical_button == Qt.LeftButton and self._action_press_index.isValid():
            pressed_index = self._action_press_index
            self._action_press_index = QModelIndex()
            self._dispatch_action_delegate_event(event, pressed_index)
            self._cleanup_press_state()
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        if self._action_press_index.isValid():
            pressed_index = self._action_press_index
            self._action_press_index = QModelIndex()
            self._dispatch_action_delegate_event(QEvent(QEvent.Leave), pressed_index)
        self.viewport().unsetCursor()
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:
        self.cancel_card_motion(update=False)
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self.cancel_card_motion(update=False)
        super().closeEvent(event)

    def refresh_icon(self, file_path: str) -> bool:
        model = self.model()
        if not isinstance(model, FileStagingPoolListModel):
            return False
        result = model.refresh_icon(file_path)
        if result:
            self.viewport().update()
        return result

    def set_previewing_path(self, file_path: str) -> None:
        model = self.model()
        if isinstance(model, FileStagingPoolListModel):
            model.set_previewing(file_path)

    def build_default_model(self) -> FileStagingPoolListModel:
        return FileStagingPoolListModel(dpi_scale=self._dpi_scale, global_font=self._global_font, parent=self)
