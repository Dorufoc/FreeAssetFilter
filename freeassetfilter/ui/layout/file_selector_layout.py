"""
文件选择器布局 — 顶栏（固定高度）+ 内容区（自适应拉伸）+ 底栏（固定高度）
"""

import ctypes
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QListView, QLabel, QAbstractItemView, QApplication
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QEvent
from PySide6.QtGui import QFont, QFontMetrics

from theme import tm
from components.styled_button import StyledButton
from components.styled_lineedit import StyledLineEdit
from components.styled_scroll_area import StyledScrollBar, StyledScrollArea
from components.file_list_model import FileListModel, FilePathRole, FileNameRole, IsDirRole, FileSizeRole, ModifiedRole, CreatedRole, SuffixRole
from components.file_card_delegate import FileCardDelegate, CARD_CONFIG, LIST_CONFIG


class FileSelectorLayout(QWidget):
    """文件选择器布局（左侧栏）"""

    file_selected = Signal(dict)
    file_selection_changed = Signal(dict, bool)
    preview_cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 顶栏区域（固定高度，包含两行）
        self._top_bar = QFrame()
        self._top_bar.setObjectName("FileSelectorTopBar")
        self._top_bar.setFixedHeight(88)
        self._build_top_bar()
        layout.addWidget(self._top_bar)

        # 内容区（自适应拉伸）
        self._content_area = QFrame()
        self._content_area.setObjectName("FileSelectorContent")
        layout.addWidget(self._content_area, stretch=1)

        # 底栏（固定高度）
        self._bottom_bar = QFrame()
        self._bottom_bar.setObjectName("FileSelectorBottomBar")
        self._bottom_bar.setFixedHeight(48)
        self._build_bottom_bar()
        layout.addWidget(self._bottom_bar)

        self.setLayout(layout)

        # 设置最小宽度，确保至少能显示 3 列卡片（与旧 file_selector.py 保持一致）
        self._update_minimum_width()

        # ── 文件列表模型 + 委托 + 视图 ──
        self._file_model = FileListModel(self)
        self._card_delegate = FileCardDelegate(self)
        self._file_list = QListView()
        self._file_list.setViewMode(QListView.IconMode)
        self._file_list.setWrapping(True)
        self._file_list.setResizeMode(QListView.Fixed)
        self._file_list.setMovement(QListView.Static)
        self._file_list.setFlow(QListView.LeftToRight)
        self._file_list.setSpacing(0)
        self._file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._file_list.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._file_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._file_list.setUniformItemSizes(True)
        self._file_list.setLayoutMode(QListView.Batched)
        self._file_list.setBatchSize(50)
        # QListView 自身隐藏默认滚动条，由同级的 StyledScrollBar 接管
        self._file_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._file_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._file_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._file_list.setMouseTracking(True)
        self._file_list.setModel(self._file_model)
        self._file_list.setItemDelegate(self._card_delegate)
        self._file_list.setFrameShape(QFrame.NoFrame)
        self._file_list.setStyleSheet("""
            QListView {
                background: transparent;
                border: none;
                padding: 0px;
            }
            QListView::item {
                background: transparent;
            }
        """)

        # 防递归守卫（与旧 file_selector.py 一致——旧代码无守卫，这里仅防止极端递归）
        self._updating_grid: bool = False

        # 文件列表独占内容区全宽，滚动条作为浮动覆盖层
        content_layout = QHBoxLayout(self._content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._file_list, stretch=1)

        # 滚动条作为浮动子控件覆盖在内容区右侧，置于文件列表之上
        self._file_scrollbar = StyledScrollBar(self._content_area)
        self._file_scrollbar.setFixedWidth(max(6, int(8 * self._get_dpi_scale())))
        self._file_scrollbar.raise_()

        # 将 StyledScrollBar 连接至 QListView 的垂直滚动
        list_vbar = self._file_list.verticalScrollBar()
        self._file_scrollbar.setRange(
            list_vbar.minimum(), list_vbar.maximum()
        )
        self._file_scrollbar.setSingleStep(list_vbar.singleStep())
        self._file_scrollbar.setPageStep(list_vbar.pageStep())
        list_vbar.rangeChanged.connect(self._sync_scrollbar_range)
        self._file_scrollbar.valueChanged.connect(list_vbar.setValue)
        list_vbar.valueChanged.connect(self._file_scrollbar.setValue)

        # 应用平滑滚动 + 触摸手势
        StyledScrollArea.apply_to(self._file_list, enable_mouse_drag=False)

        # 导航状态
        self._current_path: str = "All"
        self._view_mode: str = "card"
        self._nav_history: List[str] = []
        self._history_index: int = -1
        self._sort_mode: int = 0
        self._first_show: bool = True

        # ── 信号连接 ──
        self._path_input.returnPressed.connect(self._navigate_to_input_path)
        self._arrow_btn.clicked.connect(self._navigate_to_input_path)
        self._refresh_btn.clicked.connect(self._reload_directory)
        self._undo_btn.clicked.connect(self._go_back)
        self._sort_btn.clicked.connect(self._cycle_sort_mode)
        self._card_btn.clicked.connect(self._toggle_view_mode)
        self._file_list.clicked.connect(self._on_file_clicked)

        # 占位 / 初次导航
        self._tool_star_btn.clicked.connect(lambda: None)
        self._sift_btn.clicked.connect(lambda: None)
        self._driver_btn.clicked.connect(self._navigate_to_all)
        self._star_btn.clicked.connect(lambda: None)
        self._gen_thumb_btn.clicked.connect(lambda: None)
        self._clean_btn.clicked.connect(lambda: None)

        self._sort_btn.setToolTip("排序: 名称↑")
        self._card_btn.setToolTip("切换为列表视图")

        # 监听 viewport 和 file_list 自身的 resize（与旧 file_selector.py 一致）
        self._file_list.viewport().installEventFilter(self)
        self._file_list.installEventFilter(self)

    # ── 事件过滤器：在 QListView resize 前更新网格 ──────────────────────

    def eventFilter(self, obj, event):
        # 同时监听 viewport 和 QListView 的 Resize（与旧 file_selector.py 一致）
        if obj is self._file_list.viewport() or obj is self._file_list:
            if event.type() == QEvent.Resize:
                self._update_grid_size()
        return super().eventFilter(obj, event)

    # ── 首次加载 ──────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            QTimer.singleShot(50, self._init_navigation)

    def _init_navigation(self) -> None:
        app = QApplication.instance()
        initial_navigate_path = getattr(app, "initial_navigate_path", None)
        if initial_navigate_path and os.path.exists(initial_navigate_path):
            self._navigate_to(initial_navigate_path)
            return
        if self._try_restore_last_path():
            return
        self._navigate_to_all()

    # ── All 视图 ──────────────────────────────────────────────────────────

    def _navigate_to_all(self) -> None:
        self._load_all()
        self._current_path = "All"
        self._update_path_input("All")
        self._nav_history.append("All")
        self._history_index = len(self._nav_history) - 1

    def _load_all(self) -> None:
        entries: List[Dict[str, Any]] = []
        if sys.platform == "win32":
            kernel32 = ctypes.windll.kernel32
            drives_bitmask = kernel32.GetLogicalDrives()
            for drive in range(26):
                if drives_bitmask & (1 << drive):
                    drive_name = chr(65 + drive) + ":"
                    drive_path = drive_name + "\\"
                    try:
                        st = os.stat(drive_path)
                        modified = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
                        created = datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M")
                    except OSError:
                        modified = ""
                        created = ""
                    entries.append({
                        "name": drive_name, "path": drive_path, "is_dir": True,
                        "size": 0, "modified": modified, "created": created, "suffix": "",
                    })
        else:
            entries.append({
                "name": "/", "path": "/", "is_dir": True,
                "size": 0, "modified": "", "created": "", "suffix": "",
            })
        self._update_grid_size()
        self._file_model.set_files(entries)
        self._update_file_count(len(entries))
        self._file_list.update()

    # ── 上次路径恢复 ─────────────────────────────────────────────────────

    def _try_restore_last_path(self) -> bool:
        save_file = Path(__file__).resolve().parent.parent.parent / "data" / "last_path.json"
        try:
            if not save_file.exists():
                return False
            import json
            with open(save_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            last_path = data.get("last_path")
            if last_path and os.path.exists(last_path):
                self._navigate_to(last_path)
                return True
        except Exception:
            pass
        return False

    # ── UI 构建 ──────────────────────────────────────────────────────────

    def _build_top_bar(self):
        icons_dir = Path(__file__).resolve().parent.parent.parent / "icons"
        top_layout = QVBoxLayout(self._top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)

        nav_row = QHBoxLayout()
        nav_row.setContentsMargins(8, 4, 8, 0)
        nav_row.setSpacing(4)

        driver_icon = str(icons_dir / "driver.svg")
        self._driver_btn = StyledButton("", variant="ghost", size="sm", icon=driver_icon)
        self._driver_btn.setFixedSize(32, 32)
        nav_row.addWidget(self._driver_btn)

        self._path_input = StyledLineEdit(size="default")
        self._path_input.setPlaceholderText("输入路径...")
        nav_row.addWidget(self._path_input, stretch=1)

        arrow_icon = str(icons_dir / "arrow_right.svg")
        self._arrow_btn = StyledButton("", variant="ghost", size="sm", icon=arrow_icon)
        self._arrow_btn.setFixedSize(32, 32)
        nav_row.addWidget(self._arrow_btn)

        star_icon = str(icons_dir / "star.svg")
        self._star_btn = StyledButton("", variant="ghost", size="sm", icon=star_icon)
        self._star_btn.setFixedSize(32, 32)
        nav_row.addWidget(self._star_btn)

        top_layout.addLayout(nav_row)

        tool_row = QHBoxLayout()
        tool_row.setContentsMargins(5, 4, 5, 4)
        tool_row.setSpacing(2)

        unto_icon = str(icons_dir / "unto.svg")
        self._undo_btn = StyledButton("", variant="ghost", size="sm", icon=unto_icon)
        self._undo_btn.setFixedSize(28, 28)
        tool_row.addWidget(self._undo_btn)

        refresh_icon = str(icons_dir / "refresh.svg")
        self._refresh_btn = StyledButton("", variant="ghost", size="sm", icon=refresh_icon)
        self._refresh_btn.setFixedSize(28, 28)
        tool_row.addWidget(self._refresh_btn)

        star_icon = str(icons_dir / "star.svg")
        self._tool_star_btn = StyledButton("", variant="ghost", size="sm", icon=star_icon)
        self._tool_star_btn.setFixedSize(28, 28)
        tool_row.addWidget(self._tool_star_btn)

        sift_icon = str(icons_dir / "sift.svg")
        self._sift_btn = StyledButton("", variant="ghost", size="sm", icon=sift_icon)
        self._sift_btn.setFixedSize(28, 28)
        tool_row.addWidget(self._sift_btn)

        sort_icon = str(icons_dir / "sort.svg")
        self._sort_btn = StyledButton("", variant="ghost", size="sm", icon=sort_icon)
        self._sort_btn.setFixedSize(28, 28)
        tool_row.addWidget(self._sort_btn)

        card_icon = str(icons_dir / "card.svg")
        self._card_btn = StyledButton("", variant="ghost", size="sm", icon=card_icon)
        self._card_btn.setFixedSize(28, 28)
        tool_row.addWidget(self._card_btn)

        top_layout.addLayout(tool_row)

    def _build_bottom_bar(self) -> None:
        icons_dir = Path(__file__).resolve().parent.parent.parent / "icons"
        bottom_layout = QHBoxLayout(self._bottom_bar)
        bottom_layout.setContentsMargins(8, 6, 8, 6)
        bottom_layout.setSpacing(6)

        self._file_count_label = QLabel("0 个条目")
        self._file_count_label.setStyleSheet("background: transparent; border: none; font-size: 11px;")
        bottom_layout.addWidget(self._file_count_label)

        self._gen_thumb_btn = StyledButton("生成缩略图", variant="primary", size="sm")
        bottom_layout.addWidget(self._gen_thumb_btn, stretch=1)

        clean_icon = str(icons_dir / "clean.svg")
        self._clean_btn = StyledButton("", variant="ghost", size="sm", icon=clean_icon)
        self._clean_btn.setFixedSize(32, 32)
        bottom_layout.addWidget(self._clean_btn)

        bottom_layout.addStretch()

    # ── 目录加载 ──────────────────────────────────────────────────────────

    def _load_directory(self, path: str) -> None:
        try:
            entries: List[Dict[str, Any]] = []
            for name in os.listdir(path):
                full_path = os.path.join(path, name)
                try:
                    st = os.stat(full_path)
                    is_dir = os.path.isdir(full_path)
                    suffix = os.path.splitext(name)[1].lower().lstrip(".") if not is_dir else ""
                    modified = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
                    created = datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M")
                    entries.append({
                        "name": name, "path": full_path, "is_dir": is_dir,
                        "size": st.st_size, "modified": modified, "created": created, "suffix": suffix,
                    })
                except (PermissionError, OSError):
                    continue
            entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
            self._apply_sort(entries)
            self._update_grid_size()
            self._file_model.set_files(entries)
            self._current_path = path
            self._update_path_input(path)
            self._update_file_count(len(entries))
            self._file_list.update()
        except (PermissionError, FileNotFoundError, OSError):
            self._file_model.clear()
            self._current_path = ""
            self._update_file_count(0)
            self._file_list.update()

    def _apply_sort(self, entries: List[Dict[str, Any]]) -> None:
        mode = self._sort_mode
        if mode == 0:
            entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        elif mode == 1:
            entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()), reverse=True)
        elif mode == 2:
            entries.sort(key=lambda x: (not x["is_dir"], x.get("modified", "")), reverse=True)
        elif mode == 3:
            entries.sort(key=lambda x: (not x["is_dir"], x.get("modified", "")))
        elif mode == 4:
            entries.sort(key=lambda x: (not x["is_dir"], x.get("size", 0)), reverse=True)
        elif mode == 5:
            entries.sort(key=lambda x: (not x["is_dir"], x.get("size", 0)))

    # ── 导航 ──────────────────────────────────────────────────────────────

    def _navigate_to(self, path: str) -> None:
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            return
        self._load_directory(path)
        if self._history_index >= 0 and self._history_index < len(self._nav_history) - 1:
            self._nav_history = self._nav_history[:self._history_index + 1]
        self._nav_history.append(path)
        self._history_index = len(self._nav_history) - 1

    def _navigate_to_input_path(self) -> None:
        path = self._path_input.text().strip()
        if path:
            self._navigate_to(path)

    def _reload_directory(self) -> None:
        if self._current_path:
            self._load_directory(self._current_path)

    def _go_back(self) -> None:
        if self._history_index > 0:
            self._history_index -= 1
            path = self._nav_history[self._history_index]
            self._load_directory(path)

    # ── 文件选择 ──────────────────────────────────────────────────────────

    def _on_file_clicked(self, index) -> None:
        file_path = self._file_model.data(index, FilePathRole)
        if not file_path:
            return
        is_dir = bool(self._file_model.data(index, IsDirRole))
        if is_dir:
            self._navigate_to(file_path)
            return
        is_selected = self._file_model.toggle_selected(file_path)
        info = {
            "name": self._file_model.data(index, FileNameRole) or "",
            "path": file_path,
            "is_dir": False,
            "size": int(self._file_model.data(index, FileSizeRole) or 0),
            "modified": self._file_model.data(index, ModifiedRole) or "",
            "created": self._file_model.data(index, CreatedRole) or "",
            "suffix": (self._file_model.data(index, SuffixRole) or "").lower(),
        }
        self.file_selection_changed.emit(info, is_selected)
        if is_selected:
            self.file_selected.emit(info)
        else:
            self.preview_cancel_requested.emit()

    # ── UI 更新 ────────────────────────────────────────────────────────────

    def _update_path_input(self, path: str) -> None:
        self._path_input.setText(path)

    def _update_file_count(self, count: int) -> None:
        self._file_count_label.setText(f"{count} 个条目")
        self._file_count_label.setStyleSheet(
            "background: transparent; border: none;"
            f"color: {tm.mid.name()}; font-size: 11px;"
        )

    # ── 滚动条同步 ────────────────────────────────────────────────────────

    def _sync_scrollbar_range(self) -> None:
        """当 QListView 内部滚动范围变化时，同步 StyledScrollBar 的范围。"""
        list_vbar = self._file_list.verticalScrollBar()
        maximum = list_vbar.maximum()
        self._file_scrollbar.setRange(list_vbar.minimum(), maximum)
        self._file_scrollbar.setSingleStep(list_vbar.singleStep())
        self._file_scrollbar.setPageStep(list_vbar.pageStep())

    # ── 网格布局 ──────────────────────────────────────────────────────────

    def _get_dpi_scale(self) -> float:
        """获取 DPI 缩放因子。"""
        app = QApplication.instance()
        return getattr(app, 'dpi_scale_factor', 1.0) if app else 1.0

    # ── Debug 计数器（每次 resize 递增） ──────────────────────────────────

    _grid_debug_seq: int = 0

    def _grid_debug(self, msg: str, *args) -> None:
        """输出带序列号的 debug 信息，方便过滤。"""
        seq = self._grid_debug_seq
        print(f"[GRID-DEBUG #{seq}] {msg}", *args)

    # ── 网格布局 ──────────────────────────────────────────────────────────

    def _update_grid_size(self) -> None:
        """
        自适应网格布局：根据视口宽度动态计算卡片宽度和每行数量。
        防递归守卫防止 margins 改变引发的布局震荡。
        """
        if self._updating_grid:
            self._grid_debug("_update_grid_size 被递归拦截")
            return
        self._updating_grid = True
        self._grid_debug_seq += 1
        try:
            self._do_update_grid_size()
        finally:
            self._updating_grid = False

    def _do_update_grid_size(self) -> None:
        if self._view_mode == "list":
            self._update_list_grid()
            return

        viewport = self._file_list.viewport()
        if not viewport or viewport.width() <= 0:
            self._grid_debug(f"跳过：viewport 不可用 (width={viewport.width() if viewport else 'None'})")
            return

        self._grid_debug(f"viewport.width()={viewport.width()}")

        # 直接计算并设置 gridSize，不加 setUpdatesEnabled 包裹（与旧代码一致）
        self._apply_grid_layout(viewport)
        self._file_list.update()

    # ── 卡片尺寸与列数计算（移植自旧 CustomFileSelector）────────────────────

    def _calculate_card_base_width(self) -> int:
        """计算卡片的基础宽度（基于日期文本宽度），与旧 file_selector.py 保持一致。"""
        dpi = self._get_dpi_scale()
        base_min_width = int(50 * dpi)

        small_font = QFont(self.font())
        small_font.setPointSize(int(self.font().pointSize() * 0.85))
        small_font_metrics = QFontMetrics(small_font)

        date_text = "2024-12-31"
        date_text_width = small_font_metrics.horizontalAdvance(date_text)
        char_width = small_font_metrics.horizontalAdvance("W")
        horizontal_margins = int(4 * dpi) * 2
        border_width = int(1 * dpi) * 2

        required_width = date_text_width + char_width + horizontal_margins + border_width
        return max(required_width, base_min_width)

    def _update_minimum_width(self) -> None:
        """设置最小宽度，确保至少能显示 3 列卡片（与旧 file_selector.py 一致）。"""
        dpi = self._get_dpi_scale()
        card_width = self._calculate_card_base_width()
        spacing = int(4 * dpi)
        margin = int(5 * dpi)
        cards_total_width = 3 * card_width + 2 * spacing
        margins_total = 2 * margin
        min_filelist_width = cards_total_width + margins_total

        # 滚动条为浮动覆盖层，不计入最小宽度
        self.setMinimumWidth(min_filelist_width)

    def _apply_grid_layout(self, viewport) -> None:
        """卡片模式网格布局：基于 file_list 全宽居中卡片网格，滚动条浮动覆盖在右侧边距中。"""
        dpi = self._get_dpi_scale()

        # 滚动条为浮动覆盖层，file_list 独占 content_area 全宽
        file_list_width = self._file_list.width()
        if file_list_width <= 0:
            return

        edge_padding = int(10 * dpi)
        card_base_width = self._calculate_card_base_width()
        spacing = int(4 * dpi)
        margin = edge_padding

        available_width = max(0, file_list_width - 2 * margin)
        cell_base_width = card_base_width + spacing
        max_cols = max(1, available_width // max(1, cell_base_width))

        # 先确定列数，再在该列数内部平滑放大卡片，避免 resize 时列数来回抖动
        cell_width = max(cell_base_width, available_width // max_cols)
        card_width = max(card_base_width, cell_width - spacing)

        _, card_height = FileCardDelegate._calc_card_size(CARD_CONFIG)
        grid_cell_width = card_width + spacing
        grid_cell_height = card_height + spacing

        # 让 viewport 宽度刚好容纳 max_cols 个 grid cell。
        # +1 补偿 Qt QListView IconMode 换行边界检查的 off-by-one：
        # Qt 使用 >= 而非 > 判断换行，导致 viewport == cols * grid_cell_width 时提前换行。
        desired_viewport_width = max_cols * grid_cell_width + 1
        total_side_margin = max(0, file_list_width - desired_viewport_width)
        left_margin = total_side_margin // 2
        right_margin = total_side_margin - left_margin

        self._grid_debug(
            f"file_list={file_list_width} avail={available_width} card={card_width} "
            f"cols={max_cols} grid_total={desired_viewport_width} margins=({left_margin},{right_margin})"
        )

        self._file_list.setSpacing(0)
        self._file_list.setGridSize(QSize(grid_cell_width, grid_cell_height))
        self._file_list.setViewportMargins(left_margin, edge_padding, right_margin, edge_padding)
        # 保持 grid_offset_x=0，避免 hover 时卡片绘制超出自身 grid cell 产生残影
        self._file_model.set_grid_offset_x(0)
        self._file_model.set_card_width(card_width, card_height)

        # 滚动条作为浮动覆盖层，定位在右侧边距内（贴右边缘）
        scrollbar_w = self._file_scrollbar.width()
        scrollbar_x = file_list_width - scrollbar_w
        scrollbar_y = edge_padding
        scrollbar_h = max(0, self._file_list.height() - 2 * edge_padding)
        self._file_scrollbar.setGeometry(scrollbar_x, scrollbar_y, scrollbar_w, scrollbar_h)

    def _update_list_grid(self) -> None:
        """列表模式布局（移植自旧 CustomFileSelector._update_list_layout）。"""
        viewport = self._file_list.viewport()
        if not viewport or viewport.width() <= 0:
            return
        dpi = self._get_dpi_scale()
        viewport_width = viewport.width()
        edge_padding = int(10 * dpi)
        card_width = max(200, viewport_width - 2 * edge_padding)
        border_w = max(1, int(1 * dpi))
        icon_lm = int(4 * dpi)
        icon_sz = int(28 * dpi)
        card_height = int(2 * border_w + 2 * icon_lm + icon_sz)
        gap = int(4 * dpi)
        self._file_list.setGridSize(QSize(viewport_width, card_height + gap))
        self._file_list.setViewportMargins(0, 0, 0, 0)
        self._file_model.set_grid_offset_x(0)
        self._file_model.set_card_width(card_width, card_height)

        # 滚动条定位在右侧边缘
        scrollbar_w = self._file_scrollbar.width()
        scrollbar_x = self._file_list.width() - scrollbar_w
        scrollbar_y = 0
        scrollbar_h = max(0, self._file_list.height())
        self._file_scrollbar.setGeometry(scrollbar_x, scrollbar_y, scrollbar_w, scrollbar_h)

    # ── 排序与视图 ────────────────────────────────────────────────────────

    def _cycle_sort_mode(self) -> None:
        self._sort_mode = (self._sort_mode + 1) % 6
        mode_names = {
            0: "名称↑", 1: "名称↓", 2: "修改时间↓",
            3: "修改时间↑", 4: "大小↓", 5: "大小↑",
        }
        self._sort_btn.setToolTip(f"排序: {mode_names[self._sort_mode]}")
        if self._current_path:
            self._reload_directory()

    def _toggle_view_mode(self) -> None:
        if self._view_mode == "card":
            self._view_mode = "list"
            self._card_delegate.set_list_mode()
            self._file_list.setViewMode(QListView.ListMode)
            self._file_list.setWrapping(False)
            self._card_btn.setToolTip("切换为卡片视图")
        else:
            self._view_mode = "card"
            self._card_delegate.set_card_mode()
            self._file_list.setViewMode(QListView.IconMode)
            self._file_list.setWrapping(True)
            self._card_btn.setToolTip("切换为列表视图")
        self._update_grid_size()
        self._file_list.update()

    def set_section_styles(self, fill_color: str, border_color: str) -> None:
        section_style = f"""
            background-color: {fill_color};
            border: 1px solid {border_color};
            border-radius: 8px;
        """
        self._top_bar.setStyleSheet(section_style)
        self._content_area.setStyleSheet(section_style)
        self._bottom_bar.setStyleSheet(section_style)
