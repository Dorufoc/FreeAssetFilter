"""
文件池布局 — 内容区（自适应拉伸）+ 底栏（固定高度）

基于 StyledInfoCard 列表，提供文件暂存池的完整交互：
- 卡片列表展示（StyledInfoCard 实例列表）
- 添加/删除/清空文件操作
- hover 悬浮操作按钮（重命名/删除）
- 自动备份保存/恢复
- 重命名对话框
- 主题切换适配
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QTimer, QUrl, QEvent, QRunnable, QThreadPool
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDragLeaveEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QApplication,
    QMenu,
    QInputDialog,
    QScrollArea,
    QFileDialog,
    QProgressDialog,
)

from theme import tm
from components.styled_button import StyledButton
from components.styled_info_card import StyledInfoCard
from freeassetfilter.utils.path_utils import get_app_data_path
from freeassetfilter.services.staging_pool_service import StagingPoolService
from freeassetfilter.utils.app_logger import warning
from freeassetfilter.widgets.D_widgets import CustomMessageBox


class _MD5CalculationTask(QRunnable):
    """在后台线程计算文件MD5，完成后在主线程调用回调。"""

    def __init__(
        self, file_path: str, callback
    ) -> None:
        super().__init__()
        self._file_path = file_path
        self._callback = callback

    def run(self) -> None:
        try:
            hash_md5 = hashlib.md5()
            with open(self._file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            result = hash_md5.hexdigest()
        except FileNotFoundError:
            result = None
        except (IOError, OSError, PermissionError):
            result = None
        if self._callback:
            self._callback(result)


class FilePoolLayout(QWidget):
    """文件池布局（中间栏）"""

    # ── 对外信号 ───────────────────────────────────────────────────────────

    item_left_clicked = Signal(dict)       # 左键点击某个池条目时发出
    item_right_clicked = Signal(dict)      # 右键点击某个池条目时发出
    preview_cancel_requested = Signal()    # 需要取消预览时发出
    update_progress = Signal(int)          # 进度更新信号（导出等操作）
    pool_changed = Signal()                # 池内容变更（添加/移除/清空），通知选择器刷新状态

    # ── 备份常量 ───────────────────────────────────────────────────────────

    _BACKUP_STRING_FIELDS = (
        "name",
        "display_name",
        "original_name",
        "modified",
        "created",
        "suffix",
        "info_text",
    )
    _BACKUP_BOOL_FIELDS = (
        "is_dir",
        "is_selected",
        "is_missing",
        "size_calculating",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 内容区（自适应拉伸）
        self._content_area = QFrame()
        self._content_area.setObjectName("FilePoolContent")
        layout.addWidget(self._content_area, stretch=1)

        # 底栏（固定高度）
        self._bottom_bar = QFrame()
        self._bottom_bar.setObjectName("FilePoolBottomBar")
        self._bottom_bar.setFixedHeight(48)
        self._build_bottom_bar()
        layout.addWidget(self._bottom_bar)

        self.setLayout(layout)

        # ── 运行状态 ────────────────────────────────────────────────────
        self.items: list[dict] = []
        self.previewing_file_path: Optional[str] = None
        self._card_widgets: dict[str, StyledInfoCard] = {}  # path → card

        # ── Ctrl+滚轮 卡片缩放 ──────────────────────────────────────────
        self._card_scale_min = 0.7
        self._card_scale_max = 1.6
        self._card_scale = 1.0

        # ── ScrollArea + StyledInfoCard 列表 ────────────────────────────
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll_area.setFrameShape(QFrame.NoFrame)
        self._scroll_area.viewport().installEventFilter(self)

        self._card_container = QWidget()
        self._card_container.setObjectName("FilePoolCardContainer")
        self._card_layout = QVBoxLayout(self._card_container)
        self._card_layout.setContentsMargins(6, 6, 6, 6)
        self._card_layout.setSpacing(4)
        self._card_layout.addStretch(1)  # 将所有卡片推至顶部
        self._scroll_area.setWidget(self._card_container)

        content_layout = QVBoxLayout(self._content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._scroll_area)

        # ── 备份系统 ────────────────────────────────────────────────────
        self.backup_file = os.path.join(get_app_data_path(), "staging_pool_backup.json")
        self._suspend_backup_save = False
        self._pending_backup_last_path = "All"
        self._backup_save_delay_ms = 1500
        self._backup_save_timer = QTimer(self)
        self._backup_save_timer.setSingleShot(True)
        self._backup_save_timer.timeout.connect(self._flush_pending_backup_save)

        # ── 允许外部拖放 ──────────────────────────────────────────────
        self.setAcceptDrops(True)

        # ── 主题切换 ────────────────────────────────────────────────────
        tm.theme_changed.connect(self._on_theme_changed)

    # ═════════════════════════════════════════════════════════════════════
    #  底栏（骨架保留部分）
    # ═════════════════════════════════════════════════════════════════════

    def _build_bottom_bar(self) -> None:
        """构建底栏：导入/导出数据 + 导出文件 + 删除"""
        icons_dir = Path(__file__).resolve().parent.parent.parent / "icons"
        bottom_layout = QHBoxLayout(self._bottom_bar)
        bottom_layout.setContentsMargins(10, 6, 10, 6)
        bottom_layout.setSpacing(6)

        # 左侧文字标签（纵向排列）
        info_container = QWidget()
        info_container.setFixedHeight(32)
        info_container.setStyleSheet("background: transparent; border: none;")
        info_layout = QVBoxLayout(info_container)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(0)

        self._count_label = QLabel("0个条目")
        self._count_label.setStyleSheet(
            "background: transparent; border: none;"
            f"color: {tm.text.name()}; font-size: 12px; font-weight: 600;"
        )
        info_layout.addWidget(self._count_label)

        self._size_label = QLabel("0.00MB")
        self._size_label.setStyleSheet(
            "background: transparent; border: none;"
            f"color: {tm.mid.name()}; font-size: 10px;"
        )
        info_layout.addWidget(self._size_label)

        bottom_layout.addWidget(info_container)

        # 竖分割线
        self._separator = QFrame()
        self._separator.setFrameShape(QFrame.VLine)
        self._separator.setFrameShadow(QFrame.Sunken)
        self._update_separator_color()
        self._separator.setFixedWidth(1)
        self._separator.setFixedHeight(20)
        bottom_layout.addWidget(self._separator)

        # 将按钮区域推到右侧
        bottom_layout.addStretch(1)

        # 图标按钮 — trash.svg
        trash_icon = str(icons_dir / "trash.svg")
        self._trash_btn = StyledButton("", variant="ghost", size="sm", icon=trash_icon)
        self._trash_btn.setFixedSize(32, 32)
        self._trash_btn.clicked.connect(self.clear_all)
        bottom_layout.addWidget(self._trash_btn)

        # 次要按钮 — 导入/导出数据
        self._import_export_btn = StyledButton(
            "导入/导出数据", variant="secondary", size="sm"
        )
        self._import_export_btn.clicked.connect(self.show_import_export_dialog)
        bottom_layout.addWidget(self._import_export_btn)

        # 强调按钮 — 导出文件
        self._export_btn = StyledButton(
            "导出文件", variant="primary", size="sm"
        )
        self._export_btn.clicked.connect(self.export_selected_files)
        bottom_layout.addWidget(self._export_btn)

    def set_section_styles(self, fill_color: str, border_color: str) -> None:
        """应用面板样式到内容区、底栏（主题切换时由 MainWindow 调用）"""
        section_style = f"""
            background-color: {fill_color};
            border: 1px solid {border_color};
            border-radius: 8px;
        """
        self._content_area.setStyleSheet(section_style)
        self._bottom_bar.setStyleSheet(section_style)

    def _update_separator_color(self) -> None:
        """刷新竖分割线颜色"""
        mid = tm.mid
        self._separator.setStyleSheet(
            "background: transparent; border: none;"
            f"border-left: 1px solid rgba({mid.red()},{mid.green()},{mid.blue()},0.25);"
        )

    def _on_theme_changed(self, theme: str) -> None:
        """主题切换时刷新标签文字颜色及池视图主题"""
        self._update_separator_color()
        self._count_label.setStyleSheet(
            "background: transparent; border: none;"
            f"color: {tm.text.name()}; font-size: 12px; font-weight: 600;"
        )
        self._size_label.setStyleSheet(
            "background: transparent; border: none;"
            f"color: {tm.mid.name()}; font-size: 10px;"
        )
        self._apply_pool_theme()

    def _apply_pool_theme(self) -> None:
        """为卡片容器和 scroll area 应用当前主题样式"""
        bg = tm.bg.name()
        self._scroll_area.setStyleSheet(
            f"background-color: {bg}; border: none;"
        )
        self._card_container.setStyleSheet(
            f"background-color: {bg};"
        )
        # 刷新所有卡片的颜色
        for card in self._card_widgets.values():
            card.update()

    # ═════════════════════════════════════════════════════════════════════
    #  Ctrl+滚轮 卡片缩放（匹配文件选择器行为）
    # ═════════════════════════════════════════════════════════════════════

    def eventFilter(self, obj, event):
        if obj is self._scroll_area.viewport():
            if event.type() == QEvent.Wheel:
                if event.modifiers() & Qt.ControlModifier:
                    self._handle_card_zoom(event)
                    return True
        return super().eventFilter(obj, event)

    def _handle_card_zoom(self, event) -> None:
        """Ctrl+滚轮：缩放所有 StyledInfoCard 卡片尺寸。"""
        delta = event.angleDelta().y()
        if delta > 0:
            new_scale = min(self._card_scale_max, self._card_scale + 0.1)
        elif delta < 0:
            new_scale = max(self._card_scale_min, self._card_scale - 0.1)
        else:
            return
        self._card_scale = new_scale
        for card in self._card_widgets.values():
            card.set_scale(new_scale)

    # ═════════════════════════════════════════════════════════════════════
    #  备份系统
    # ═════════════════════════════════════════════════════════════════════

    def _save_backup_if_needed(self, last_path: str = "All") -> None:
        """在允许的情况下请求保存备份（防抖）。"""
        self._pending_backup_last_path = last_path
        if self._suspend_backup_save:
            return
        if self._backup_save_timer.isActive():
            self._backup_save_timer.stop()
        self._backup_save_timer.start(self._backup_save_delay_ms)

    def _flush_pending_backup_save(self) -> None:
        """执行一次实际备份写入。"""
        if self._suspend_backup_save:
            return
        self.save_backup(self._pending_backup_last_path)

    def flush_backup_save_now(self, last_path: Optional[str] = None) -> None:
        """立即执行一次保存，通常用于退出前等必须落盘的场景。"""
        if last_path is not None:
            self._pending_backup_last_path = last_path
        if self._backup_save_timer.isActive():
            self._backup_save_timer.stop()
        self.save_backup(self._pending_backup_last_path)

    def save_backup(self, last_path: str = "All") -> None:
        """保存当前文件列表到备份文件。"""
        try:
            backup_data = self._build_backup_payload(last_path)
            with open(self.backup_file, "w", encoding="utf-8") as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2)
        except (IOError, OSError, TypeError, ValueError):
            pass  # 静默失败，不影响主流程

    @classmethod
    def _serialize_backup_item(cls, file_info: dict) -> Optional[dict]:
        """将运行时文件信息压缩为可安全写入 JSON 的备份结构。"""
        if not isinstance(file_info, dict):
            return None
        raw_path = file_info.get("path")
        if raw_path is None:
            return None
        path = os.path.normpath(str(raw_path).strip())
        if not path:
            return None
        serialized: dict = {"path": path}
        size = file_info.get("size")
        if isinstance(size, (int, float)) and not isinstance(size, bool):
            serialized["size"] = int(size)
        else:
            serialized["size"] = None
        for field in cls._BACKUP_STRING_FIELDS:
            value = file_info.get(field)
            serialized[field] = "" if value is None else str(value)
        for field in cls._BACKUP_BOOL_FIELDS:
            serialized[field] = bool(file_info.get(field, False))
        return serialized

    def _build_backup_payload(self, last_path: str = "All") -> dict:
        """构建统一的备份载荷，过滤不可序列化的运行时字段。"""
        items = []
        for file_info in self.items:
            serialized = self._serialize_backup_item(file_info)
            if serialized:
                items.append(serialized)
        return {
            "items": items,
            "selector_state": {
                "last_path": str(last_path or "All"),
            },
        }

    def load_backup(self) -> dict:
        """从备份文件加载文件列表。

        Returns:
            规范化后的备份数据，如果没有备份则返回空结构。
        """
        try:
            if os.path.exists(self.backup_file):
                with open(self.backup_file, "r", encoding="utf-8") as f:
                    raw_backup = json.load(f)
                if isinstance(raw_backup, dict):
                    items = raw_backup.get("items", [])
                    selector_state = raw_backup.get("selector_state", {})
                elif isinstance(raw_backup, list):
                    items = raw_backup
                    selector_state = {}
                else:
                    items = []
                    selector_state = {}
                normalized_items = []
                for file_info in items:
                    serialized = self._serialize_backup_item(file_info)
                    if serialized:
                        normalized_items.append(serialized)
                last_path = (
                    selector_state.get("last_path", "All")
                    if isinstance(selector_state, dict)
                    else "All"
                )
                return {
                    "items": normalized_items,
                    "selector_state": {"last_path": str(last_path or "All")},
                }
        except json.JSONDecodeError:
            pass
        except (IOError, OSError, TypeError, ValueError):
            pass
        return {"items": [], "selector_state": {"last_path": "All"}}

    # ═════════════════════════════════════════════════════════════════════
    #  文件操作
    # ═════════════════════════════════════════════════════════════════════

    def add_file(self, file_info: dict) -> None:
        """添加文件或文件夹到暂存池（创建 StyledInfoCard widget）。"""
        file_path = os.path.normpath(file_info["path"])
        if file_path in self._card_widgets:
            return
        file_info = dict(file_info)
        file_info.setdefault("display_name", file_info.get("name", os.path.basename(file_path)))
        file_info.setdefault("original_name", file_info.get("name", os.path.basename(file_path)))
        if file_info.get("is_dir") and "size_calculating" not in file_info:
            file_info["size_calculating"] = True
        if (self.previewing_file_path
                and os.path.normcase(file_path) == os.path.normcase(self.previewing_file_path)):
            file_info["is_previewing"] = True

        # 创建 StyledInfoCard
        display_name = file_info.get("display_name") or file_info.get("name") or os.path.basename(file_path)
        info_text = self._build_info_text(file_info)
        card = StyledInfoCard(
            layout_mode="horizontal",
            title=display_name,
            subtitle=info_text,
            overlay_enabled=True,
            size_overrides={
                "title_size": 10,
                "title_weight": 700,
                "subtitle_size": 9,
                "subtitle_weight": 400,
            },
            parent=self._card_container,
        )
        card.set_file_path(file_path)

        # 尝试加载缩略图/图标
        icon_pixmap = self._get_file_icon_pixmap(file_info)
        if icon_pixmap and not icon_pixmap.isNull():
            card.set_media_pixmap(icon_pixmap)

        # 添加 hover 操作按钮（StyledInfoCard 原生 overlay）
        norm_path = file_path
        card.add_action("重命名", callback=lambda fp=norm_path: self.rename_file_by_path(fp))
        card.add_action("删除", callback=lambda fp=norm_path: self.remove_file(fp))

        # 点击预览
        card.clicked.connect(self._handle_card_clicked)

        # 插入到 stretch 之前
        insert_idx = self._card_layout.count() - 1
        self._card_layout.insertWidget(insert_idx, card)
        self._card_widgets[file_path] = card

        self.items.append(file_info)
        self.update_stats()
        self._save_backup_if_needed()
        self.pool_changed.emit()

        # 如果是目录，异步计算实际大小
        if file_info.get("is_dir"):
            self._calculate_folder_size(file_path)

    def _build_info_text(self, file_info: dict) -> str:
        """构建文件信息文本（副标题）。"""
        file_path = file_info.get("path", "")
        if file_info.get("is_missing", False):
            return file_path
        if file_info.get("is_dir", False):
            if file_info.get("size_calculating", False):
                return "正在计算大小..."
            size_text = self._format_file_size(file_info.get("size")) if file_info.get("size") is not None else "文件夹"
            return size_text
        size_text = self._format_file_size(file_info.get("size")) if file_info.get("size") is not None else ""
        if file_path and size_text:
            return f"{file_path}  {size_text}"
        return file_path or size_text or ""

    def _get_file_icon_pixmap(self, file_info: dict) -> Optional[QPixmap]:
        """获取文件图标 QPixmap，与文件选择器 layout 使用相同的 FileIconManager 管线。

        管线优先级（FileIconManager 内部处理）：
        1. 目录 → 文件夹 SVG 图标
        2. 照片/视频 → 优先返回已存在的缩略图
        3. 系统图标（exe/lnk/url）→ SVG 占位符 + 触发异步加载
        4. 其他 → SVG 图标（含未知文件文字叠加）
        """
        try:
            if not file_info.get("path", ""):
                return None
            from freeassetfilter.services.file_icon_manager import FileIconManager
            dpr = self._get_device_pixel_ratio()
            pix = FileIconManager().get_icon_pixmap(file_info, 48, dpr)
            if pix and not pix.isNull():
                return pix
        except Exception:
            pass
        return None

    @staticmethod
    def _get_device_pixel_ratio() -> float:
        """获取设备像素比（DPI 缩放因子），与 FileListModel 实现一致。"""
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

    def remove_file(self, file_path: str) -> None:
        """从暂存池移除文件。"""
        normalized_path = os.path.normpath(file_path)
        if normalized_path not in self._card_widgets:
            return
        if (self.previewing_file_path
                and os.path.normcase(normalized_path) == os.path.normcase(self.previewing_file_path)):
            self.previewing_file_path = None
            self.preview_cancel_requested.emit()
        # 延迟后移除卡片（配合移出动画）
        QTimer.singleShot(300, lambda: self._finalize_remove(normalized_path))

    def _finalize_remove(self, file_path: str) -> None:
        """最终移除文件（动画完成后）。"""
        card = self._card_widgets.pop(file_path, None)
        if card:
            self._card_layout.removeWidget(card)
            card.deleteLater()
        self.items = [f for f in self.items if os.path.normpath(f.get("path", "")) != file_path]
        self.update_stats()
        self._save_backup_if_needed()
        self.pool_changed.emit()

    def clear_all(self) -> None:
        """清空所有项目（带确认）。"""
        confirm_msg = CustomMessageBox(self)
        confirm_msg.set_title("确认清空")
        confirm_msg.set_text("确定要清空所有项目吗？")
        confirm_msg.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])
        is_confirmed = False

        def on_confirm_clicked(button_index: int) -> None:
            nonlocal is_confirmed
            is_confirmed = (button_index == 0)
            confirm_msg.close()

        confirm_msg.buttonClicked.connect(on_confirm_clicked)
        confirm_msg.exec()
        if is_confirmed:
            self.clear_all_without_confirmation()

    def clear_all_without_confirmation(self) -> None:
        """不显示确认对话框，直接清空所有项目。"""
        for card in list(self._card_widgets.values()):
            self._card_layout.removeWidget(card)
            card.deleteLater()
        self._card_widgets.clear()
        self.items.clear()
        self.previewing_file_path = None
        self.update_stats()
        self._save_backup_if_needed()
        self.pool_changed.emit()

    def update_stats(self) -> None:
        """更新统计信息（条目数 + 总大小）。"""
        total_items = len(self.items)
        total_size = 0
        for item in self.items:
            size_calc = item.get("size_calculating")
            if not size_calc:
                sz = item.get("size")
                if sz is not None:
                    total_size += int(sz)
        self._count_label.setText(f"{total_items}个条目")
        self._size_label.setText(self._format_file_size(total_size))

    @staticmethod
    def _format_file_size(size_bytes: int) -> str:
        """将字节数格式化为可读的文件大小字符串。"""
        if not isinstance(size_bytes, (int, float)):
            return "0.00 MB"
        units = ["B", "KB", "MB", "GB", "TB"]
        index = 0
        size = float(size_bytes)
        while size >= 1024 and index < len(units) - 1:
            size /= 1024.0
            index += 1
        if index == 0:
            return f"{int(size)} {units[index]}"
        return f"{size:.2f} {units[index]}"

    # ═════════════════════════════════════════════════════════════════════
    #  视图信号处理
    # ═════════════════════════════════════════════════════════════════════

    def has_file(self, file_path: str) -> bool:
        """判断文件是否已在暂存池中。"""
        norm = os.path.normpath(file_path) if file_path else ""
        return norm in self._card_widgets

    def get_pool_paths(self) -> set[str]:
        """返回当前池中所有文件的路径集合。"""
        return set(self._card_widgets.keys())

    def _handle_card_clicked(self, file_path: str) -> None:
        """处理 StyledInfoCard 点击：如果正在预览则取消，否则发射预览信号。"""
        norm_path = os.path.normpath(file_path) if file_path else ""
        if (norm_path
                and self.previewing_file_path
                and os.path.normcase(norm_path) == os.path.normcase(self.previewing_file_path)):
            self.preview_cancel_requested.emit()
        else:
            # 查找对应的 file_info 并发射
            for fi in self.items:
                if fi.get("path") and os.path.normpath(str(fi["path"])) == norm_path:
                    self.item_left_clicked.emit(fi)
                    break

    # ═════════════════════════════════════════════════════════════════════
    #  重命名
    # ═════════════════════════════════════════════════════════════════════

    def rename_file_by_path(self, file_path: str) -> None:
        """重命名池中的文件（显示名）。"""
        norm_path = os.path.normpath(file_path) if file_path else ""
        # 在 self.items 中查找
        current_info = None
        for fi in self.items:
            p = fi.get("path")
            if p and os.path.normpath(str(p)) == norm_path:
                current_info = fi
                break
        if not current_info:
            return
        current_name = current_info.get("display_name") or current_info.get("name", "")
        new_name, ok = QInputDialog.getText(
            self,
            "重命名",
            "请输入新的显示名称：",
            text=current_name,
        )
        if not ok:
            return
        new_name = new_name.strip()
        # 合法性校验
        if not new_name:
            return
        if len(new_name) > 255:
            return
        illegal_chars = r'\/:*?"<>|'
        if any(c in new_name for c in illegal_chars):
            return

        # 更新 self.items
        current_info["display_name"] = new_name
        # 更新对应的 StyledInfoCard
        card = self._card_widgets.get(norm_path)
        if card:
            card.set_title(new_name)
        self.update_stats()
        self._save_backup_if_needed()

    # ═════════════════════════════════════════════════════════════════════
    #  预览状态管理
    # ═════════════════════════════════════════════════════════════════════

    def set_previewing_file(self, file_path: str) -> None:
        """标记指定路径为正在预览状态。"""
        self.previewing_file_path = os.path.normpath(file_path) if file_path else None
        # 更新 items 中的标记（StyledInfoCard 暂不支持预览高亮边框）

    def clear_previewing_state(self) -> None:
        """清除所有预览状态标记。"""
        self.previewing_file_path = None

    # ═════════════════════════════════════════════════════════════════════
    #  外部拖放支持（Phase 3）
    # ═════════════════════════════════════════════════════════════════════

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """接受外部 URL 拖入，显示蓝色虚线边框反馈。"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._content_area.setStyleSheet(
                self._content_area.styleSheet()
                + " border: 2px dashed #4a90d9;"
            )

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        """拖拽移动中持续接受。"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        """拖拽离开时恢复样式。"""
        self._restore_content_border()

    def dropEvent(self, event: QDropEvent) -> None:
        """处理从外部拖入的文件/文件夹。"""
        self._restore_content_border()
        if not event.mimeData().hasUrls():
            return
        urls = event.mimeData().urls()
        for url in urls:
            file_path = url.toLocalFile()
            if os.path.exists(file_path):
                self._add_dropped_item(file_path)
        event.acceptProposedAction()

    def _restore_content_border(self) -> None:
        """恢复内容区边框样式（移除虚线反馈）。"""
        current = self._content_area.styleSheet()
        # 移除临时添加的虚线边框
        lines = [l for l in current.split("\n") if "dashed" not in l]
        self._content_area.setStyleSheet("\n".join(lines))

    def _add_dropped_item(self, file_path: str) -> None:
        """构建文件信息并添加到暂存池。"""
        file_info = StagingPoolService.build_file_info(file_path)
        if file_info:
            self.add_file(file_info)

    # ═════════════════════════════════════════════════════════════════════
    #  导入/导出数据（Phase 3）
    # ═════════════════════════════════════════════════════════════════════

    def show_import_export_dialog(self) -> None:
        """导入/导出数据选择对话框。"""
        msg_box = CustomMessageBox(self)
        msg_box.set_title("导入/导出数据")
        msg_box.set_text("请选择操作：")
        msg_box.set_buttons(
            ["导入数据", "导出数据", "取消"],
            Qt.Horizontal,
            ["primary", "secondary", "normal"],
        )
        choice = -1

        def on_clicked(idx: int) -> None:
            nonlocal choice
            choice = idx
            msg_box.close()

        msg_box.buttonClicked.connect(on_clicked)
        msg_box.exec()

        if choice == 0:
            self.import_data()
        elif choice == 1:
            self.export_data()

    def import_data(self) -> None:
        """从 JSON 文件导入备份数据。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择导入文件", "", "JSON 文件 (*.json)"
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, IOError, OSError) as e:
            err_box = CustomMessageBox(self)
            err_box.set_title("导入失败")
            err_box.set_text(f"读取文件失败：{e}")
            err_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            err_box.exec()
            return

        # 支持两种格式：dict（含 items 键）或 列表
        if isinstance(raw, dict):
            items = raw.get("items", [])
        elif isinstance(raw, list):
            items = raw
        else:
            err_box = CustomMessageBox(self)
            err_box.set_title("导入失败")
            err_box.set_text("文件格式不正确，应为 JSON 数组或备份结构。")
            err_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            err_box.exec()
            return

        if not items:
            info_box = CustomMessageBox(self)
            info_box.set_title("导入提示")
            info_box.set_text("文件中没有有效的条目数据。")
            info_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            info_box.exec()
            return

        # 询问清空或追加
        confirm_box = CustomMessageBox(self)
        confirm_box.set_title("确认导入")
        confirm_box.set_text(f"即将导入 {len(items)} 个条目。是否清空现有条目？")
        confirm_box.set_buttons(
            ["清空并导入", "追加导入", "取消"],
            Qt.Horizontal,
            ["primary", "secondary", "normal"],
        )
        import_mode = -1

        def on_mode_clicked(idx: int) -> None:
            nonlocal import_mode
            import_mode = idx
            confirm_box.close()

        confirm_box.buttonClicked.connect(on_mode_clicked)
        confirm_box.exec()

        if import_mode == 2 or import_mode == -1:
            return

        if import_mode == 0:
            self.clear_all_without_confirmation()

        # 逐条导入，检查文件是否存在
        success_count = 0
        unlinked = []
        for item in items:
            if not isinstance(item, dict) or "path" not in item:
                continue
            item_path = item.get("path", "")
            if os.path.exists(item_path):
                self.add_file(item)
                success_count += 1
            else:
                unlinked.append(item)

        # 显示未链接文件处理
        if unlinked:
            self.show_unlinked_files_dialog(unlinked)

        # 显示结果
        result_box = CustomMessageBox(self)
        result_box.set_title("导入完成")
        msg = f"成功导入 {success_count} 个条目。"
        if unlinked:
            msg += f"\n{len(unlinked)} 个文件路径不存在（已单独列出）。"
        result_box.set_text(msg)
        result_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
        result_box.exec()

    def export_data(self) -> None:
        """将当前暂存池条目导出为 JSON 文件。"""
        if not self.items:
            info_box = CustomMessageBox(self)
            info_box.set_title("导出提示")
            info_box.set_text("暂存池中没有数据可导出。")
            info_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            info_box.exec()
            return

        from datetime import datetime

        default_name = f"FAF_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出数据", default_name, "JSON 文件 (*.json)"
        )
        if not file_path:
            return

        payload = self._build_backup_payload("All")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            info_box = CustomMessageBox(self)
            info_box.set_title("导出成功")
            info_box.set_text(f"成功导出 {len(self.items)} 个条目到：\n{file_path}")
            info_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            info_box.exec()
        except (IOError, OSError, PermissionError) as e:
            err_box = CustomMessageBox(self)
            err_box.set_title("导出失败")
            err_box.set_text(f"写入文件失败：{e}")
            err_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            err_box.exec()

    # ═════════════════════════════════════════════════════════════════════
    #  未链接文件对话框（Phase 3）
    # ═════════════════════════════════════════════════════════════════════

    def show_unlinked_files_dialog(self, unlinked_items: list) -> None:
        """显示未链接（路径不存在的）文件处理对话框。

        Args:
            unlinked_items: 路径不存在的条目字典列表。
        """
        msg_box = CustomMessageBox(self)
        names = "\n".join(
            f"• {item.get('display_name', item.get('name', '未知'))}"
            for item in unlinked_items[:20]
        )
        if len(unlinked_items) > 20:
            names += f"\n… 及其他 {len(unlinked_items) - 20} 个"
        msg_box.set_title("未链接文件")
        msg_box.set_text(
            f"以下 {len(unlinked_items)} 个文件路径不存在：\n\n{names}"
        )
        msg_box.set_buttons(
            ["手动链接", "忽略这些文件", "取消"],
            Qt.Horizontal,
            ["primary", "secondary", "normal"],
        )
        choice = -1

        def on_clicked(idx: int) -> None:
            nonlocal choice
            choice = idx
            msg_box.close()

        msg_box.buttonClicked.connect(on_clicked)
        msg_box.exec()

        if choice == 0:
            # 手动链接：选择替换目录
            dir_path = QFileDialog.getExistingDirectory(
                self, "选择包含替代文件的目录"
            )
            if dir_path:
                self._relink_files(unlinked_items, dir_path)
        elif choice == 1:
            pass  # 忽略，不导入这些条目
        # choice == 2 or -1 → 取消整个导入

    def _relink_files(self, unlinked_items: list, search_dir: str) -> list:
        """在指定目录中通过文件名匹配重新链接未链接的文件。

        Args:
            unlinked_items: 未链接条目的列表。
            search_dir: 要搜索的目录。

        Returns:
            成功重新链接的条目列表。
        """
        relinked = []
        for item in unlinked_items:
            target_name = item.get("display_name", item.get("name", ""))
            if not target_name:
                continue
            candidate = os.path.join(search_dir, target_name)
            if os.path.exists(candidate):
                item["path"] = candidate
                self.add_file(item)
                relinked.append(item)

        if relinked:
            info_box = CustomMessageBox(self)
            info_box.set_title("重新链接")
            info_box.set_text(f"成功重新链接 {len(relinked)} 个文件。")
            info_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            info_box.exec()
        return relinked

    # ═════════════════════════════════════════════════════════════════════
    #  导出文件（Phase 3）
    # ═════════════════════════════════════════════════════════════════════

    def export_selected_files(self) -> None:
        """导出暂存池中的文件（含模式选择、空间检查、进度显示）。"""
        if not self.items:
            info_box = CustomMessageBox(self)
            info_box.set_title("提示")
            info_box.set_text("暂存池中没有文件可导出。")
            info_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            info_box.exec()
            return

        # 模式选择
        mode_box = CustomMessageBox(self)
        mode_box.set_title("选择导出方式")
        mode_box.set_text("请选择导出模式：\n\n"
                          "平铺导出：所有文件直接复制到目标目录\n"
                          "分类导出：按原始文件夹分类存放")
        mode_box.set_buttons(
            ["平铺导出", "分类导出", "取消"],
            Qt.Vertical,
            ["primary", "primary", "normal"],
        )
        export_mode = -1

        def on_mode_clicked(idx: int) -> None:
            nonlocal export_mode
            export_mode = idx
            mode_box.close()

        mode_box.buttonClicked.connect(on_mode_clicked)
        mode_box.exec()

        if export_mode == 2 or export_mode == -1:
            return

        # 选择目标目录
        target_dir = QFileDialog.getExistingDirectory(self, "选择导出目标目录")
        if not target_dir:
            return

        # 计算总大小（同步，已知道的不再计算）
        total_size = 0
        for item in self.items:
            sz = item.get("size")
            if sz is not None and not item.get("size_calculating"):
                total_size += int(sz)
            elif os.path.isfile(item.get("path", "")):
                try:
                    total_size += os.path.getsize(item["path"])
                except (OSError, PermissionError):
                    pass

        # 空间检查
        check_ok = self._check_space_and_proceed(target_dir, total_size)
        if check_ok is False:
            return
        if check_ok == "reselect":
            self.export_selected_files()
            return

        self._do_export(list(self.items), target_dir, export_mode)

    def _check_space_and_proceed(
        self, target_dir: str, needed_bytes: int
    ) -> bool | str:
        """检查目标目录磁盘空间是否充足。

        Args:
            target_dir: 目标目录。
            needed_bytes: 所需空间（字节）。

        Returns:
            True: 继续；False: 取消；"reselect": 重新选择。
        """
        total, free = StagingPoolService().get_directory_space(target_dir)
        if total is None or free is None:
            warn_box = CustomMessageBox(self)
            warn_box.set_title("无法检测空间")
            warn_box.set_text("无法获取目标目录的空间信息，是否继续？")
            warn_box.set_buttons(
                ["继续", "重新选择", "取消"],
                Qt.Horizontal,
                ["primary", "normal", "normal"],
            )
            choice = -1

            def _on_click(idx: int) -> None:
                nonlocal choice
                choice = idx
                warn_box.close()

            warn_box.buttonClicked.connect(_on_click)
            warn_box.exec()
            return {0: True, 1: "reselect"}.get(choice, False)

        if free is not None and free < needed_bytes:
            err_box = CustomMessageBox(self)
            err_box.set_title("空间不足")
            err_box.set_text(
                f"所需空间：{FilePoolLayout._format_file_size(needed_bytes)}\n"
                f"可用空间：{FilePoolLayout._format_file_size(free)}\n"
                f"缺少：{FilePoolLayout._format_file_size(needed_bytes - free)}"
            )
            err_box.set_buttons(
                ["重新选择", "取消"],
                Qt.Horizontal,
                ["primary", "normal"],
            )
            choice = -1

            def _on_err_click(idx: int) -> None:
                nonlocal choice
                choice = idx
                err_box.close()

            err_box.buttonClicked.connect(_on_err_click)
            err_box.exec()
            return "reselect" if choice == 0 else False

        return True

    def _do_export(self, files: list, target_dir: str, mode: int) -> None:
        """执行导出：创建进度对话框并启动复制线程。

        Args:
            files: 文件信息列表。
            target_dir: 目标目录。
            mode: 0=平铺, 1=分类。
        """
        # 创建进度对话框
        progress = QProgressDialog("正在导出文件…", "取消", 0, len(files), self)
        progress.setWindowTitle("导出进度")
        progress.setMinimumDuration(0)
        progress.setValue(0)

        # 连接进度信号
        self.update_progress.connect(progress.setValue)

        def _on_finish(success: int, failed: int, errors: list) -> None:
            try:
                self.update_progress.disconnect(progress.setValue)
            except (TypeError, RuntimeError):
                pass
            progress.close()

            result_box = CustomMessageBox(self)
            if failed == 0:
                result_box.set_title("导出完成")
                result_box.set_text(f"成功导出 {success} 个文件。")
            else:
                detail = "\n".join(errors[:5])
                if len(errors) > 5:
                    detail += f"\n… 及其他 {len(errors) - 5} 个错误"
                result_box.set_title("导出结果")
                result_box.set_text(
                    f"成功 {success} 个，失败 {failed} 个。\n\n{detail}"
                )
            result_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            result_box.exec()

        # 在后台线程中执行复制
        def _copy_worker():
            try:
                if mode == 0:
                    s, f, e = self.copy_files(files, target_dir)
                else:
                    s, f, e = self.copy_files_categorized(files, target_dir)
                _on_finish(s, f, e)
            except Exception as ex:
                warning(f"导出线程异常: {ex}")

        t = threading.Thread(target=_copy_worker, daemon=True)
        t.start()

        # 显示进度对话框（模态）
        progress.exec()

    def copy_files(self, files: list, target_dir: str) -> tuple:
        """平铺导出：将所有文件直接复制到目标目录。

        Args:
            files: 文件信息列表。
            target_dir: 目标目录。

        Returns:
            (成功数, 失败数, 错误信息列表)
        """
        success = 0
        failed = 0
        errors = []
        for i, fi in enumerate(files):
            src = fi.get("path", "")
            dst = os.path.join(target_dir, fi.get("display_name", os.path.basename(src)))
            try:
                if fi.get("is_dir"):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
                success += 1
            except (IOError, OSError, PermissionError, shutil.Error) as e:
                failed += 1
                errors.append(f"{fi.get('display_name', '?')}: {e}")
            self.update_progress.emit(i + 1)
        return success, failed, errors

    def copy_files_categorized(
        self, files: list, target_dir: str
    ) -> tuple:
        """分类导出：按原始文件夹分类存放。

        Args:
            files: 文件信息列表。
            target_dir: 目标目录。

        Returns:
            (成功数, 失败数, 错误信息列表)
        """
        success = 0
        failed = 0
        errors = []
        for i, fi in enumerate(files):
            src = fi.get("path", "")
            source_dir = os.path.dirname(src)
            category = os.path.basename(source_dir) or "未分类"
            cat_dir = os.path.join(target_dir, category)
            try:
                os.makedirs(cat_dir, exist_ok=True)
            except (IOError, OSError) as e:
                failed += 1
                errors.append(f"{fi.get('display_name', '?')}: 创建分类目录失败 - {e}")
                self.update_progress.emit(i + 1)
                continue

            dst = os.path.join(cat_dir, fi.get("display_name", os.path.basename(src)))
            # 同名文件冲突处理
            dst = self._get_unique_target_path(cat_dir, os.path.basename(dst))
            try:
                if fi.get("is_dir"):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
                success += 1
            except (IOError, OSError, PermissionError, shutil.Error) as e:
                failed += 1
                errors.append(f"{fi.get('display_name', '?')}: {e}")
            self.update_progress.emit(i + 1)
        return success, failed, errors

    @staticmethod
    def _get_unique_target_path(directory: str, filename: str) -> str:
        """生成目标路径，避免文件名冲突。

        Args:
            directory: 目标目录。
            filename: 文件名。

        Returns:
            唯一的完整目标路径。
        """
        base, ext = os.path.splitext(filename)
        candidate = os.path.join(directory, filename)
        counter = 1
        while os.path.exists(candidate):
            candidate = os.path.join(directory, f"{base}_{counter}{ext}")
            counter += 1
        return candidate

    # ═════════════════════════════════════════════════════════════════════
    #  异步文件夹大小计算（Phase 3）
    # ═════════════════════════════════════════════════════════════════════

    def _calculate_folder_size(self, folder_path: str) -> None:
        """异步提交文件夹大小计算任务。"""
        service = StagingPoolService()
        service.calculate_folder_size_async(
            folder_path,
            callback=lambda size: self._on_folder_size_ready(folder_path, size),
        )

    def _on_folder_size_ready(self, folder_path: str, size) -> None:
        """文件夹大小计算完成后的回调，更新 items 和卡片副标题。"""
        if size is None:
            return
        norm_path = os.path.normpath(folder_path)
        updated = False
        for fi in self.items:
            p = fi.get("path")
            if p and os.path.normpath(str(p)) == norm_path:
                fi["size"] = int(size)
                fi["size_calculating"] = False
                updated = True
                break
        if updated:
            # 更新卡片的副标题
            card = self._card_widgets.get(norm_path)
            if card:
                card.set_subtitle(self._build_info_text({**fi, "size": int(size), "size_calculating": False}))
            self.update_stats()
            self._save_backup_if_needed()

    # ═════════════════════════════════════════════════════════════════════
    #  异步 MD5 计算（Phase 3）
    # ═════════════════════════════════════════════════════════════════════

    def calculate_md5_async(
        self, file_path: str, callback
    ) -> None:
        """异步计算文件 MD5 值。

        Args:
            file_path: 文件路径。
            callback: 回调函数，接收 MD5 字符串或 None。
        """
        task = _MD5CalculationTask(file_path, callback)
        QThreadPool.globalInstance().start(task)
