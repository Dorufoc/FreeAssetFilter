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

import time

from PySide6.QtCore import (
    Qt, Signal, QTimer, QUrl, QEvent, QRunnable, QThreadPool, QEventLoop,
    QRect, QEasingCurve, QPropertyAnimation, QParallelAnimationGroup,
    QAbstractAnimation,
)
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDragLeaveEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QApplication,
    QMenu,
    QScrollArea,
    QFileDialog,
    QProgressDialog,
    QSpacerItem,
    QSizePolicy,
)

from theme import tm
from components.styled_button import StyledButton
from components.styled_info_card import StyledInfoCard
from components.file_card_delegate import LIST_CONFIG
from components.styled_scroll_area import StyledScrollBar, StyledScrollArea
from components.styled_dialog import create_input_dialog, create_custom_dialog
from freeassetfilter.utils.path_utils import get_app_data_path
from freeassetfilter.services.staging_pool_service import StagingPoolService
from freeassetfilter.utils.animation_settings import is_animation_enabled
from freeassetfilter.utils.app_logger import warning


def _show_custom_dialog(parent, title, message, buttons, variants=None, vertical=False, dialog_type="default"):
    """Styled 弹窗包装，仿 CustomMessageBox 接口（同步阻塞、返回按钮索引）。

    文件池弹窗统一不显示右上角关闭按钮（所有场景都有"取消"按钮作为退出路径）。
    """
    dlg = create_custom_dialog(
        title=title,
        message=message,
        buttons=list(buttons),
        variants=list(variants) if variants else None,
        vertical=vertical,
        dialog_type=dialog_type,
        show_close=False,
    )
    result = [0]
    loop = QEventLoop()

    def _on_finished(r: int) -> None:
        result[0] = r
        loop.quit()

    dlg.finished.connect(_on_finished)
    # 兜底：用户用 ESC / 关闭按钮时 finished 可能不发射
    dlg.destroyed.connect(loop.quit)
    loop.exec()
    return result[0]


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
    _export_finished = Signal(int, int, object)  # 导出完成信号（成功数, 失败数, 错误列表）
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
        # 图标目录（_build_bottom_bar 与 add_file 都需要使用，必须在 _build_bottom_bar 之前初始化）
        self._icons_dir = Path(__file__).resolve().parent.parent.parent / "icons"

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
        self._removing_paths: set[str] = set()  # 正在播放移除动画的路径

        # ── InfoCard 创建/移除动画 ──────────────────────────────────────
        self._card_motion_duration_ms = 100
        self._card_motion_min_slide = 28
        self._card_motion_max_slide = 96
        self._card_motion_slide_ratio = 0.18
        self._active_card_animations: dict[str, dict] = {}  # path → {"group": ..., "on_finished": ..., "kind": ...}
        self._entry_spacers: dict[str, QSpacerItem] = {}  # path → 创建动画期间占位 spacer
        self._active_remove_motion_groups: dict[str, QParallelAnimationGroup] = {}  # path → 占位控件折叠动画组（驱动下方卡片整体上移）

        # ── Ctrl+滚轮 卡片缩放 ──────────────────────────────────────────
        self._card_scale_min = 0.7
        self._card_scale_max = 1.6
        self._card_scale = 1.0
        # 卡片 base size_overrides（_card_scale=1.0 时的设计值，作为缩放基准）。
        # 直接派生自文件选择器 list 模式 LIST_CONFIG（单一事实来源），
        # 保证暂存池卡片与文件选择器横向卡片的高度、图标、文字排列完全一致。
        self._card_base_overrides: dict = dict(LIST_CONFIG)

        # ── ScrollArea + StyledInfoCard 列表 ────────────────────────────
        # 与 FileSelectorLayout 一致：隐藏 QScrollArea 自带滚动条，
        # 改用独立的 StyledScrollBar 作为浮动覆盖层（自绘圆角条形 + hover 动画）。
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_area.setFrameShape(QFrame.NoFrame)
        # 内部子布局必须保持透明，让基础底层（_content_area）的半透明 section fill 单一透出，
        # 防止多层半透明背景叠加。主题切换由 _apply_pool_theme 再次刷新。
        self._scroll_area.setStyleSheet(
            "background-color: transparent; border: none;"
        )
        self._scroll_area.viewport().installEventFilter(self)

        self._card_container = QWidget()
        self._card_container.setObjectName("FilePoolCardContainer")
        self._card_container.setStyleSheet("background-color: transparent;")
        self._card_layout = QVBoxLayout(self._card_container)
        # 防递归守卫：水平边距动态计算时避免 setContentsMargins 触发的布局重入
        self._updating_pool_margins = False
        # 初始左右边距用「无滚动条居中」默认值（10*dpi），后续由
        # _update_pool_card_margins 根据滚动条状态动态覆盖；上下边距保留 6
        _init_pad = int(10 * self._get_dpi_scale())
        self._card_layout.setContentsMargins(_init_pad, 6, _init_pad, 6)
        # 卡片间距与文件选择器 list 模式一致（其卡片间隙基准值为 5）
        self._card_layout.setSpacing(5)
        self._card_layout.addStretch(1)  # 将所有卡片推至顶部
        self._scroll_area.setWidget(self._card_container)

        content_layout = QVBoxLayout(self._content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._scroll_area)

        # 浮动覆盖层滚动条（贴 _content_area 右侧，覆盖在 _scroll_area 之上）
        self._pool_scrollbar = StyledScrollBar(self._content_area)
        self._pool_scrollbar.setFixedWidth(max(6, int(8 * self._get_dpi_scale())))
        self._pool_scrollbar.raise_()

        # 同步浮动滚动条与 _scroll_area 垂直滚动条的范围/值
        area_vbar = self._scroll_area.verticalScrollBar()
        self._pool_scrollbar.setRange(area_vbar.minimum(), area_vbar.maximum())
        self._pool_scrollbar.setSingleStep(area_vbar.singleStep())
        self._pool_scrollbar.setPageStep(area_vbar.pageStep())
        area_vbar.rangeChanged.connect(self._sync_pool_scrollbar_range)
        self._pool_scrollbar.valueChanged.connect(area_vbar.setValue)
        area_vbar.valueChanged.connect(self._pool_scrollbar.setValue)

        # 滚动时刷新所有卡片的 overlay（修复 StyledInfoCard 的 QGraphicsEffect
        # 缓存导致 hover overlay 在滚动时不同步跟随）。使用 singleShot 节流，
        # 避免范围变化触发的连续 valueChanged 导致所有卡片反复重绘。
        self._pending_scroll_overlay_update = False
        area_vbar.valueChanged.connect(self._on_pool_scrolled)

        # 应用平滑滚动 + 边界回弹 + 触摸手势（与 FileSelectorLayout 一致）
        StyledScrollArea.apply_to(self._scroll_area, enable_mouse_drag=False)

        # 内容区尺寸变化时重新定位浮动滚动条
        self._content_area.installEventFilter(self)

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
        icons_dir = self._icons_dir
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
        """为卡片容器和 scroll area 应用当前主题样式（保持透明，避免多层半透明叠加）"""
        # 内部子布局（_scroll_area、_card_container）必须保持透明，
        # 让基础底层（_content_area / _bottom_bar）的半透明 section fill 透出，
        # 防止多层半透明背景叠加。
        self._scroll_area.setStyleSheet(
            "background-color: transparent; border: none;"
        )
        self._card_container.setStyleSheet(
            "background-color: transparent;"
        )
        # 刷新所有卡片的颜色
        for card in self._card_widgets.values():
            card.update()

    # ═════════════════════════════════════════════════════════════════════
    #  Ctrl+滚轮 卡片缩放（匹配文件选择器行为）
    # ═════════════════════════════════════════════════════════════════════

    def eventFilter(self, obj, event):
        if obj is self._content_area and event.type() == QEvent.Resize:
            # 内容区尺寸变化时重新定位浮动滚动条
            self._update_pool_scrollbar_geometry()
            # 宽度/高度变化后同步重算卡片左右边距
            self._update_pool_card_margins()
        if obj is self._scroll_area.viewport():
            if event.type() == QEvent.Wheel:
                if event.modifiers() & Qt.ControlModifier:
                    self._handle_card_zoom(event)
                    return True
        return super().eventFilter(obj, event)

    def _get_dpi_scale(self) -> float:
        """获取 DPI 缩放因子（与 FileSelectorLayout 行为一致）。"""
        app = QApplication.instance()
        return getattr(app, 'dpi_scale_factor', 1.0) if app else 1.0

    def _sync_pool_scrollbar_range(self, min_val: int, max_val: int) -> None:
        """当 _scroll_area 内部滚动范围变化时，同步浮动 StyledScrollBar 的范围。"""
        self._pool_scrollbar.setRange(min_val, max_val)
        area_vbar = self._scroll_area.verticalScrollBar()
        self._pool_scrollbar.setSingleStep(area_vbar.singleStep())
        self._pool_scrollbar.setPageStep(area_vbar.pageStep())
        # 范围变化时也重定位（隐藏/显示逻辑通过 maximum==0 处理）
        self._update_pool_scrollbar_geometry()
        # 滚动条出现/消失时重算卡片左右边距（延迟到 Qt 布局稳定后执行）
        QTimer.singleShot(0, self._update_pool_card_margins)

    def _update_pool_scrollbar_geometry(self) -> None:
        """将浮动滚动条定位到内层 _scroll_area 的右侧边缘（与 FileSelectorLayout 行为一致）。

        参照系用内层 _scroll_area 而非外层 _content_area：_scroll_area 以 0 边距填充
        _content_area 的 contentsRect，天然被 _content_area 的 1px QSS 边框内缩，等价于
        FileSelectorLayout 中滚动条参照 _file_list.width()。这样滚动条落在边框内侧，
        与文件选择器右侧间距逐像素一致，而不会压住 1px 边框与圆角。
        """
        if not hasattr(self, "_pool_scrollbar") or not hasattr(self, "_scroll_area"):
            return
        if self._scroll_area.width() <= 0 or self._scroll_area.height() <= 0:
            return
        edge_padding = int(10 * self._get_dpi_scale())
        scrollbar_w = self._pool_scrollbar.width()
        scrollbar_x = self._scroll_area.width() - scrollbar_w
        scrollbar_y = edge_padding
        scrollbar_h = max(0, self._scroll_area.height() - 2 * edge_padding)
        self._pool_scrollbar.setGeometry(scrollbar_x, scrollbar_y, scrollbar_w, scrollbar_h)
        self._pool_scrollbar.raise_()

    def _update_pool_card_margins(self) -> None:
        """根据垂直滚动条状态动态调整卡片容器左右边距。

        复刻 FileSelectorLayout._update_list_grid 的滚动条感知边距逻辑：
        - 有滚动条：总边距 20*dpi，左右按滚动条宽度分配，使「卡片左缘到容器左缘」
          与「卡片右缘到滚动条左缘」间距相等；
        - 无滚动条：左右各 10*dpi，卡片水平居中。
        仅调整左右边距，上下边距原样保留；仅当值变化时才写入，避免无谓布局刷新。
        """
        if self._updating_pool_margins:
            return
        self._updating_pool_margins = True
        try:
            dpi = self._get_dpi_scale()
            scrollbar_w = self._pool_scrollbar.width()
            needs_scroll = self._scroll_area.verticalScrollBar().maximum() > 0
            if needs_scroll:
                total_margin = int(20 * dpi)
                left = max(0, (total_margin - scrollbar_w) // 2)
                right = total_margin - left
            else:
                left = int(10 * dpi)
                right = int(10 * dpi)
            m = self._card_layout.contentsMargins()
            if (m.left(), m.right()) != (left, right):
                self._card_layout.setContentsMargins(left, m.top(), right, m.bottom())
        finally:
            self._updating_pool_margins = False


    def _on_pool_scrolled(self, _value: int) -> None:
        """滚动时让所有卡片的 overlay 重新绘制（修复 QGraphicsEffect 缓存不同步）。"""
        if self._pending_scroll_overlay_update:
            return
        self._pending_scroll_overlay_update = True

        def _update() -> None:
            self._pending_scroll_overlay_update = False
            for card in self._card_widgets.values():
                card.update_overlay()

        QTimer.singleShot(0, _update)

    def showEvent(self, event) -> None:
        """首次显示时定位浮动滚动条。"""
        super().showEvent(event)
        self._update_pool_scrollbar_geometry()
        self._update_pool_card_margins()

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
        # 传入 _card_base_overrides 作为缩放基准（派生自选择器 LIST_CONFIG），
        # 保证已存在卡片缩放后仍与新加入卡片尺寸一致。
        for card in self._card_widgets.values():
            card.set_scale(new_scale, base_overrides=self._card_base_overrides)

    # 仅这些尺寸键参与缩放；weight/radius 等键必须原样保留，
    # 否则 title_weight=700 会被放大为非法字重（与 StyledInfoCard.set_scale 行为对齐）。
    _SCALABLE_SIZE_KEYS = ("padding", "gap", "media_size", "icon_size",
                           "title_size", "subtitle_size", "desc_size")

    def _build_card_size_overrides(self) -> dict:
        """根据当前 _card_scale 构建 size_overrides（与 set_scale + base_overrides 等价）。"""
        scale = self._card_scale
        return {
            key: max(1, int(value * scale)) if key in self._SCALABLE_SIZE_KEYS else value
            for key, value in self._card_base_overrides.items()
        }

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
        # size_overrides 基于当前 _card_scale 动态计算，使新加入卡片继承用户最新的缩放
        card = StyledInfoCard(
            layout_mode="horizontal",
            title=display_name,
            subtitle=info_text,
            overlay_enabled=True,
            size_overrides=self._build_card_size_overrides(),
            parent=self._card_container,
        )
        card.set_file_path(file_path)

        # 尝试加载缩略图/图标
        icon_pixmap = self._get_file_icon_pixmap(file_info)
        if icon_pixmap and not icon_pixmap.isNull():
            card.set_media_pixmap(icon_pixmap)

        # 添加 hover 操作按钮（StyledInfoCard 原生 overlay，使用 StyledButton）
        norm_path = file_path
        trash_icon = str(self._icons_dir / "trash.svg")
        card.add_action(
            "重命名",
            variant="secondary",
            size="sm",
            callback=lambda fp=norm_path: self.rename_file_by_path(fp),
        )
        card.add_action(
            "",
            icon=trash_icon,
            variant="danger",
            size="sm",
            callback=lambda fp=norm_path: self.remove_file(fp),
        )

        # 点击预览
        card.clicked.connect(self._handle_card_clicked)

        # 立即完成其它进行中的入口动画，确保它们的占位 spacer 被真实卡片替换，
        # 避免新卡片插入到尚未释放的占位位置导致重叠。
        self._finalize_entry_animations()

        # 在插入 layout 之前预设为完全透明，避免卡片在动画启动前以完全不透明
        # 状态被绘制一次（这会导致整个列表因新卡片突然占位而抽搐闪烁）。
        # 动画禁用时由 _animate_card_entry 立即恢复为 1.0。
        if is_animation_enabled("file_record_changes", default=True):
            card.card_opacity = 0.0

        # 插入到 stretch 之前。用 setUpdatesEnabled 包裹，强制 layout 同步计算，
        # 避免 QScrollArea 异步更新 _card_container geometry 时产生中间状态，
        # 导致已有卡片视觉位置跳变（抽搐）。
        insert_idx = self._card_layout.count() - 1
        self._card_container.setUpdatesEnabled(False)
        try:
            self._card_layout.insertWidget(insert_idx, card)
            self._card_layout.activate()
        finally:
            self._card_container.setUpdatesEnabled(True)
            self._card_container.update()
        self._card_widgets[file_path] = card

        self.items.append(file_info)
        self.update_stats()
        self._save_backup_if_needed()
        self.pool_changed.emit()

        # 播放创建动画（淡入 + 从左侧滑入）
        QTimer.singleShot(
            0,
            lambda c=card, fp=file_path: self._animate_card_entry(c, fp),
        )

        # 如果是目录，异步计算实际大小
        if file_info.get("is_dir"):
            self._calculate_folder_size(file_path)

    def _slide_offset_for_rect(self, rect: QRect) -> int:
        """计算水平滑入/滑出偏移量（viewport 宽度的 18%，限制在 28~96px）。"""
        width = rect.width() if rect.isValid() else self._card_container.width()
        if width <= 0:
            width = self._card_container.width()
        return max(
            self._card_motion_min_slide,
            min(self._card_motion_max_slide, int(width * self._card_motion_slide_ratio)),
        )

    def _animate_card_entry(self, card: StyledInfoCard, file_path: str) -> None:
        """播放卡片创建动画：从左侧淡入并滑入最终位置。

        卡片保持在 layout 中，通过 paint-level 属性实现淡入 + 从左侧滑入，
        不触发 removeWidget/insertWidget，避免 layout 重排导致其它卡片抖动。
        卡片在 add_file 中已被预设为 card_opacity=0.0，因此不会在动画启动前
        闪现完全不透明状态。
        """
        if not is_animation_enabled("file_record_changes", default=True):
            # 动画禁用：直接恢复为完全不透明
            card.card_opacity = 1.0
            return
        if file_path in self._removing_paths:
            # 该卡片已被请求移除，清理可能已存在的 spacer 后让退出动画负责
            self._remove_entry_spacer(file_path)
            return
        if card is None or card.isHidden() or not self._card_widgets:
            return

        # 若该路径已有动画在运行，先完成它，确保旧卡片的 on_finished 得到执行
        self._finalize_card_animation(file_path)
        self._remove_entry_spacer(file_path)

        card.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        target_rect = card.geometry()
        if not target_rect.isValid():
            card.setAttribute(Qt.WA_TransparentForMouseEvents, False)
            card.card_opacity = 1.0
            return

        slide = self._slide_offset_for_rect(target_rect)
        # 卡片已被预设为 card_opacity=0.0，这里只需设置 x_offset 并启动动画。
        # 不调用 processEvents()，避免中间状态被绘制导致抖动。
        card.x_offset = -slide

        self._run_card_motion(
            file_path=file_path,
            card=card,
            start_rect=QRect(
                target_rect.x() - slide, target_rect.y(),
                target_rect.width(), target_rect.height(),
            ),
            end_rect=target_rect,
            start_opacity=0.0,
            end_opacity=1.0,
            duration=self._card_motion_duration_ms,
            easing=QEasingCurve.OutCubic,
            on_finished=lambda: self._finish_card_entry(card, file_path),
            kind="entry",
        )

    def _finish_card_entry(self, card: StyledInfoCard, file_path: str) -> None:
        """创建动画结束：恢复卡片交互状态。"""
        if card is None:
            return
        card.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        card.card_opacity = 1.0
        card.x_offset = 0

    def _remove_entry_spacer(self, file_path: str) -> None:
        """移除并清理指定路径的创建动画占位 spacer。"""
        spacer = self._entry_spacers.pop(file_path, None)
        if spacer is not None:
            try:
                self._card_layout.removeItem(spacer)
            except RuntimeError:
                pass

    def _stop_card_animation(self, file_path: str) -> None:
        """停止并清理指定路径的卡片动画（不执行其 on_finished 回调）。"""
        info = self._active_card_animations.pop(file_path, None)
        if info is None:
            return
        group = info.get("group")
        if group is not None:
            try:
                group.stop()
                group.deleteLater()
            except RuntimeError:
                pass

    def _finalize_card_animation(self, file_path: str) -> None:
        """强制完成指定路径的卡片动画并执行其 on_finished 回调。"""
        info = self._active_card_animations.pop(file_path, None)
        if info is None:
            return
        group = info.get("group")
        if group is not None:
            # 暂时断开 finished 信号，避免 start 后 stop 触发 _cleanup 导致重复执行
            try:
                group.finished.disconnect()
            except (TypeError, RuntimeError):
                pass
            try:
                group.stop()
            except RuntimeError:
                pass
            try:
                group.deleteLater()
            except RuntimeError:
                pass
        on_finished = info.get("on_finished")
        if on_finished is not None:
            try:
                on_finished()
            except Exception:
                pass

    def _finalize_entry_animations(self) -> None:
        """立即完成所有进行中的创建（入口）动画，确保状态恢复。"""
        for path in list(self._active_card_animations.keys()):
            info = self._active_card_animations.get(path)
            if info is not None and info.get("kind") == "entry":
                self._finalize_card_animation(path)

    def _run_card_motion(
        self,
        file_path: str,
        card: StyledInfoCard,
        start_rect: QRect,
        end_rect: QRect,
        start_opacity: float,
        end_opacity: float,
        duration: int,
        easing: QEasingCurve,
        on_finished=None,
        kind: str = "motion",
    ) -> None:
        """同时播放 geometry 与透明度动画。"""
        if card is None:
            return

        # 停止同路径旧动画，避免属性与状态冲突；旧动画的 on_finished 会恢复
        # 卡片状态，因此要确保在启动新动画前被调用。
        self._finalize_card_animation(file_path)

        # 入场动画不再驱动 geometry（卡片保持在 layout 中），改用 x_offset
        # 属性实现水平滑入，避免 remove/insert 导致的 layout 抖动。
        animations: list[QPropertyAnimation] = []
        if kind == "entry":
            x_anim = QPropertyAnimation(card, b"x_offset")
            x_anim.setDuration(duration)
            x_anim.setStartValue(start_rect.x() - end_rect.x())
            x_anim.setEndValue(0)
            x_anim.setEasingCurve(easing)
            animations.append(x_anim)
        else:
            geom_anim = QPropertyAnimation(card, b"geometry")
            geom_anim.setDuration(duration)
            geom_anim.setStartValue(start_rect)
            geom_anim.setEndValue(end_rect)
            geom_anim.setEasingCurve(easing)
            animations.append(geom_anim)

        # 使用 StyledInfoCard 的 paint-level 透明度属性，避免 QGraphicsOpacityEffect
        # 与 overlay 子控件的 effect 嵌套导致的 painter 冲突。
        card.card_opacity = start_opacity
        opacity_anim = QPropertyAnimation(card, b"card_opacity")
        opacity_anim.setDuration(duration)
        opacity_anim.setStartValue(start_opacity)
        opacity_anim.setEndValue(end_opacity)
        opacity_anim.setEasingCurve(
            QEasingCurve.OutCubic if end_opacity > start_opacity else QEasingCurve.InCubic
        )
        animations.append(opacity_anim)

        group = QParallelAnimationGroup(self)
        for anim in animations:
            group.addAnimation(anim)
        self._active_card_animations[file_path] = {
            "group": group,
            "on_finished": on_finished,
            "kind": kind,
        }

        def _cleanup():
            self._active_card_animations.pop(file_path, None)
            if on_finished is not None:
                on_finished()

        group.finished.connect(_cleanup)
        group.start(QAbstractAnimation.DeleteWhenStopped)

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
        if normalized_path in self._removing_paths:
            return
        if (self.previewing_file_path
                and os.path.normcase(normalized_path) == os.path.normcase(self.previewing_file_path)):
            self.previewing_file_path = None
            self.preview_cancel_requested.emit()

        if not is_animation_enabled("file_record_changes", default=True):
            self._finalize_remove(normalized_path)
            return

        self._removing_paths.add(normalized_path)
        # 先结束其它进行中的移除位移动画，避免 y_offset 叠加导致位置计算错误
        self._cancel_all_remove_motions()
        QTimer.singleShot(
            0, lambda p=normalized_path: self._animate_card_exit(p)
        )

    def _animate_card_exit(self, file_path: str) -> None:
        """播放卡片移除动画：向左滑出并淡出；退出完成后再带动下方卡片整体上移。"""
        card = self._card_widgets.get(file_path)
        if card is None:
            self._removing_paths.discard(file_path)
            return

        # 若该卡片正在播放创建动画，先完成它，避免创建动画的 cleanup 干扰退出动画
        self._finalize_card_animation(file_path)
        self._remove_entry_spacer(file_path)

        QApplication.processEvents()
        start_rect = card.geometry()
        if not start_rect.isValid():
            self._finalize_remove(file_path)
            return

        removed_index = self._card_layout.indexOf(card)

        # 在目标位置预先插入一个等高的透明占位控件。
        # 退出动画期间目标卡片仍在视觉上占据原位置，下方卡片不会提前上移，
        # 避免与被移除卡片发生重叠。
        placeholder: Optional[QWidget] = None
        if removed_index >= 0:
            placeholder = QWidget(self._card_container)
            placeholder.setFixedHeight(start_rect.height())
            placeholder.setStyleSheet("background: transparent; border: none;")
            self._card_layout.insertWidget(removed_index, placeholder)

        self._card_layout.removeWidget(card)
        card.setGeometry(start_rect)
        card.raise_()

        def _on_exit_finished() -> None:
            self._finalize_remove(file_path)
            if placeholder is not None:
                self._collapse_placeholder(file_path, placeholder)

        slide = self._slide_offset_for_rect(start_rect)
        end_rect = QRect(
            start_rect.x() - slide, start_rect.y(),
            start_rect.width(), start_rect.height(),
        )
        self._run_card_motion(
            file_path=file_path,
            card=card,
            start_rect=start_rect,
            end_rect=end_rect,
            start_opacity=1.0,
            end_opacity=0.0,
            duration=self._card_motion_duration_ms,
            easing=QEasingCurve.InCubic,
            on_finished=_on_exit_finished,
            kind="exit",
        )

    def _finalize_remove(self, file_path: str) -> None:
        """最终移除文件（动画完成后）。"""
        self._removing_paths.discard(file_path)
        card = self._card_widgets.pop(file_path, None)
        if card is not None:
            card.deleteLater()
        self.items = [f for f in self.items if os.path.normpath(f.get("path", "")) != file_path]
        self.update_stats()
        self._save_backup_if_needed()
        self.pool_changed.emit()

    def _collapse_placeholder(
        self, removed_path: str, placeholder: QWidget
    ) -> None:
        """将占位控件高度动画到 0，通过 layout 驱动下方卡片作为整体向上平移。

        占位控件仍保留在 layout 中，因此下方卡片由 layout 自动同步推动，
        不会出现单张卡片被父容器裁切的问题。
        """
        if not is_animation_enabled("file_record_changes", default=True):
            try:
                placeholder.setParent(None)
                placeholder.deleteLater()
            except RuntimeError:
                pass
            return

        start_height = placeholder.height()
        if start_height <= 0:
            try:
                placeholder.setParent(None)
                placeholder.deleteLater()
            except RuntimeError:
                pass
            return

        placeholder.setMinimumHeight(0)
        placeholder.setMaximumHeight(start_height)

        group = QParallelAnimationGroup(self)
        for prop in (b"minimumHeight", b"maximumHeight"):
            anim = QPropertyAnimation(placeholder, prop)
            anim.setDuration(self._card_motion_duration_ms)
            anim.setStartValue(start_height)
            anim.setEndValue(0)
            anim.setEasingCurve(QEasingCurve.InOutCubic)
            group.addAnimation(anim)

        group._placeholder = placeholder

        def _cleanup() -> None:
            self._active_remove_motion_groups.pop(removed_path, None)
            try:
                placeholder.setParent(None)
                placeholder.deleteLater()
            except RuntimeError:
                pass

        group.finished.connect(_cleanup)
        self._active_remove_motion_groups[removed_path] = group
        group.start(QAbstractAnimation.DeleteWhenStopped)

    def _cancel_remove_motion(self, removed_path: str) -> None:
        """停止指定路径关联的位移动画并清理占位控件。"""
        group = self._active_remove_motion_groups.pop(removed_path, None)
        if group is None:
            return
        try:
            group.stop()
        except RuntimeError:
            pass
        # 清理关联的占位控件
        placeholder = getattr(group, "_placeholder", None)
        if placeholder is not None:
            try:
                placeholder.setParent(None)
                placeholder.deleteLater()
            except RuntimeError:
                pass
        try:
            group.deleteLater()
        except RuntimeError:
            pass

    def _cancel_all_remove_motions(self) -> None:
        """停止所有进行中的移除位移动画。"""
        for path in list(self._active_remove_motion_groups.keys()):
            self._cancel_remove_motion(path)

    def clear_all(self) -> None:
        """清空所有项目（带确认）。"""
        is_confirmed = _show_custom_dialog(
            self,
            "确认清空",
            "确定要清空所有项目吗？",
            ["确定", "取消"],
            ["primary", "normal"],
        ) == 0
        if is_confirmed:
            self.clear_all_without_confirmation()

    def clear_all_without_confirmation(self) -> None:
        """不显示确认对话框，直接清空所有项目。"""
        if not is_animation_enabled("file_record_changes", default=True):
            self._clear_all_immediate()
            return

        cards = list(self._card_widgets.values())
        paths = list(self._card_widgets.keys())
        if not cards:
            self._clear_all_immediate()
            return

        # 停止所有可能正在进行的动画（创建动画 + 移除位移动画）
        for path in paths:
            self._stop_card_animation(path)
        self._cancel_all_remove_motions()
        for path in list(self._entry_spacers.keys()):
            self._remove_entry_spacer(path)

        QApplication.processEvents()
        rects = {card: QRect(card.geometry()) for card in cards}
        for card in cards:
            self._card_layout.removeWidget(card)
            card.setGeometry(rects[card])

        # 清空数据状态
        self._card_widgets.clear()
        self.items.clear()
        self.previewing_file_path = None
        self.update_stats()
        self._save_backup_if_needed()
        self.pool_changed.emit()

        # 统一播放淡出左移动画
        for idx, card in enumerate(cards):
            start_rect = rects[card]
            slide = self._slide_offset_for_rect(start_rect)
            end_rect = QRect(
                start_rect.x() - slide, start_rect.y(),
                start_rect.width(), start_rect.height(),
            )
            self._run_card_motion(
                file_path=f"__clear_all_{idx}__",
                card=card,
                start_rect=start_rect,
                end_rect=end_rect,
                start_opacity=1.0,
                end_opacity=0.0,
                duration=self._card_motion_duration_ms,
                easing=QEasingCurve.InCubic,
                on_finished=lambda c=card: c.deleteLater(),
                kind="exit",
            )

    def _clear_all_immediate(self) -> None:
        """立即清空所有项目（无动画）。"""
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
        """重命名池中的文件（显示名）。使用 styled 弹窗（create_input_dialog）输入新名称。"""
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

        # styled 弹窗（create_input_dialog：原生的 StyledDialog + QLineEdit 主题化输入框）
        rename_dialog = create_input_dialog(
            title="重命名",
            message="请输入新的显示名称：",
            placeholder="输入新的文件名",
            cancel_text="取消",
            confirm_text="确定",
        )
        # 预填当前显示名（QLineEdit 主题化样式在 create_input_dialog 中已设置）
        rename_dialog._input_field.setText(current_name)
        rename_dialog._input_field.selectAll()

        # StyledDialog 继承自 QWidget（不是 QDialog），没有 exec()，需要用 show() + QEventLoop 阻塞等待 finished
        result: list[int] = [0]
        loop = QEventLoop()
        rename_dialog.finished.connect(lambda r: result.__setitem__(0, r))
        rename_dialog.finished.connect(loop.quit)
        # 兜底：用户用 ESC / 关闭按钮时 finished 可能不发射，监听 closeEvent
        rename_dialog.destroyed.connect(loop.quit)
        rename_dialog.show()
        loop.exec()

        if result[0] != 1:
            return
        new_name = rename_dialog._input_field.text().strip()

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
        choice = _show_custom_dialog(
            self,
            "导入/导出数据",
            "请选择操作：",
            ["导入数据", "导出数据", "取消"],
            ["primary", "secondary", "normal"],
        )

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
            _show_custom_dialog(
                self, "导入失败", f"读取文件失败：{e}",
                ["确定"], ["primary"], dialog_type="danger",
            )
            return

        # 支持两种格式：dict（含 items 键）或 列表
        if isinstance(raw, dict):
            items = raw.get("items", [])
        elif isinstance(raw, list):
            items = raw
        else:
            _show_custom_dialog(
                self, "导入失败", "文件格式不正确，应为 JSON 数组或备份结构。",
                ["确定"], ["primary"], dialog_type="danger",
            )
            return

        if not items:
            _show_custom_dialog(
                self, "导入提示", "文件中没有有效的条目数据。",
                ["确定"], ["primary"], dialog_type="info",
            )
            return

        # 询问清空或追加
        import_mode = _show_custom_dialog(
            self,
            "确认导入",
            f"即将导入 {len(items)} 个条目。是否清空现有条目？",
            ["清空并导入", "追加导入", "取消"],
            ["primary", "secondary", "normal"],
        )

        if import_mode == 2:
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
        msg = f"成功导入 {success_count} 个条目。"
        if unlinked:
            msg += f"\n{len(unlinked)} 个文件路径不存在（已单独列出）。"
        _show_custom_dialog(
            self, "导入完成", msg,
            ["确定"], ["primary"], dialog_type="success",
        )

    def export_data(self) -> None:
        """将当前暂存池条目导出为 JSON 文件。"""
        if not self.items:
            _show_custom_dialog(
                self, "导出提示", "暂存池中没有数据可导出。",
                ["确定"], ["primary"], dialog_type="info",
            )
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
            _show_custom_dialog(
                self, "导出成功",
                f"成功导出 {len(self.items)} 个条目到：\n{file_path}",
                ["确定"], ["primary"], dialog_type="success",
            )
        except (IOError, OSError, PermissionError) as e:
            _show_custom_dialog(
                self, "导出失败", f"写入文件失败：{e}",
                ["确定"], ["primary"], dialog_type="danger",
            )

    # ═════════════════════════════════════════════════════════════════════
    #  未链接文件对话框（Phase 3）
    # ═════════════════════════════════════════════════════════════════════

    def show_unlinked_files_dialog(self, unlinked_items: list) -> None:
        """显示未链接（路径不存在的）文件处理对话框。

        Args:
            unlinked_items: 路径不存在的条目字典列表。
        """
        names = "\n".join(
            f"• {item.get('display_name', item.get('name', '未知'))}"
            for item in unlinked_items[:20]
        )
        if len(unlinked_items) > 20:
            names += f"\n… 及其他 {len(unlinked_items) - 20} 个"
        choice = _show_custom_dialog(
            self,
            "未链接文件",
            f"以下 {len(unlinked_items)} 个文件路径不存在：\n\n{names}",
            ["手动链接", "忽略这些文件", "取消"],
            ["primary", "secondary", "normal"],
        )

        if choice == 0:
            # 手动链接：选择替换目录
            dir_path = QFileDialog.getExistingDirectory(
                self, "选择包含替代文件的目录"
            )
            if dir_path:
                self._relink_files(unlinked_items, dir_path)
        elif choice == 1:
            pass  # 忽略，不导入这些条目
        # choice == 2 → 取消整个导入

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
            _show_custom_dialog(
                self, "重新链接", f"成功重新链接 {len(relinked)} 个文件。",
                ["确定"], ["primary"], dialog_type="success",
            )
        return relinked

    # ═════════════════════════════════════════════════════════════════════
    #  导出文件（Phase 3）
    # ═════════════════════════════════════════════════════════════════════

    def export_selected_files(self) -> None:
        """导出暂存池中的文件（含模式选择、空间检查、进度显示）。"""
        if not self.items:
            _show_custom_dialog(
                self, "提示", "暂存池中没有文件可导出。",
                ["确定"], ["primary"], dialog_type="info",
            )
            return

        # 模式选择
        export_mode = _show_custom_dialog(
            self,
            "选择导出方式",
            "请选择导出模式：\n\n"
            "平铺导出：所有文件直接复制到目标目录\n"
            "分类导出：按原始文件夹分类存放",
            ["平铺导出", "分类导出", "取消"],
            ["primary", "primary", "normal"],
            vertical=True,
        )

        if export_mode == 2:
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
            choice = _show_custom_dialog(
                self,
                "无法检测空间",
                "无法获取目标目录的空间信息，是否继续？",
                ["继续", "重新选择", "取消"],
                ["primary", "normal", "normal"],
            )
            return {0: True, 1: "reselect"}.get(choice, False)

        if free is not None and free < needed_bytes:
            choice = _show_custom_dialog(
                self,
                "空间不足",
                f"所需空间：{FilePoolLayout._format_file_size(needed_bytes)}\n"
                f"可用空间：{FilePoolLayout._format_file_size(free)}\n"
                f"缺少：{FilePoolLayout._format_file_size(needed_bytes - free)}",
                ["重新选择", "取消"],
                ["primary", "normal"],
                dialog_type="danger",
            )
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
            try:
                self._export_finished.disconnect(_on_finish)
            except (TypeError, RuntimeError):
                pass
            progress.close()

            if failed == 0:
                _show_custom_dialog(
                    self, "导出完成", f"成功导出 {success} 个文件。",
                    ["确定"], ["primary"], dialog_type="success",
                )
            else:
                detail = "\n".join(errors[:5])
                if len(errors) > 5:
                    detail += f"\n… 及其他 {len(errors) - 5} 个错误"
                _show_custom_dialog(
                    self, "导出结果",
                    f"成功 {success} 个，失败 {failed} 个。\n\n{detail}",
                    ["确定"], ["primary"], dialog_type="danger",
                )

        # 连接完成信号（在主线程处理结果）
        self._export_finished.connect(_on_finish)

        # 在后台线程中执行复制
        def _copy_worker():
            try:
                if mode == 0:
                    s, f, e = self.copy_files(files, target_dir)
                else:
                    s, f, e = self.copy_files_categorized(files, target_dir)
                self._export_finished.emit(s, f, e)
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
            display_name = fi.get("display_name", os.path.basename(src))
            dst = self._get_unique_target_path(target_dir, display_name)
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
        service.initialize()
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
