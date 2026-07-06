#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

自定义文件选择器组件
使用卡片式布局，实现鼠标悬停高亮和点击选择功能
"""

import sys
import os
import re
import json
import traceback
import weakref
from collections import deque
from datetime import datetime

# 添加项目根目录到Python路径，解决直接运行时的导入问题
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# 导入日志模块
from freeassetfilter.utils.app_logger import debug, warning, error
from freeassetfilter.core.managers.heartbeat_manager import HeartbeatManager

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QDialog, QApplication,
    QPushButton, QLabel, QComboBox, QLineEdit, QScrollArea, QListView,
    QHeaderView, QGroupBox, QGridLayout, QMenu,
    QFrame, QSplitter, QSizePolicy, QInputDialog, QListWidget, QProgressBar,
    QProgressDialog, QAbstractItemView
)
from PySide6.QtCore import (
    Qt, Signal, QThread, QObject, QEvent, QTimer,
    QFileInfo, QDateTime, QPoint, QSize, QRect, QRectF, QUrl,
    QRunnable, QThreadPool,
)

class ProgressThrottler(QObject):
    def __init__(self, min_interval_ms=50, parent=None):
        super().__init__(parent)
        self._min_interval = min_interval_ms
        self._last_update_time = 0
        self._pending_current = 0
        self._pending_total = 0
        self._pending_file_data = None
        self._update_func = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._do_update)

    def update(self, current, total, file_data, update_func):
        self._pending_current = current
        self._pending_total = total
        self._pending_file_data = file_data
        self._update_func = update_func

        import time
        current_time_ms = int(time.time() * 1000)
        if current_time_ms - self._last_update_time >= self._min_interval:
            self._do_update()
        elif not self._timer.isActive():
            self._timer.start(self._min_interval)

    def _do_update(self):
        import time
        self._last_update_time = int(time.time() * 1000)
        if self._update_func:
            self._update_func(self._pending_current, self._pending_total, self._pending_file_data)


from PySide6.QtGui import (
    QIcon, QPixmap, QFont, QFontMetrics, QColor, QCursor,
    QBrush, QPainter, QPen, QPalette, QImage, QFontDatabase, QAction
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QSvgWidget
from freeassetfilter.core.preview.svg_renderer import SvgRenderer
from freeassetfilter.widgets import CustomButton, CustomInputBox, CustomWindow, CustomMessageBox
from freeassetfilter.widgets.file_block_card import FileBlockCard
from freeassetfilter.widgets.file_staging_pool_model import FileStagingPoolListModel
from freeassetfilter.widgets.file_staging_pool_delegate import FileStagingPoolCardDelegate
from freeassetfilter.widgets.list_widgets import CustomSelectList
from freeassetfilter.widgets.dropdown_menu import CustomDropdownMenu
from freeassetfilter.widgets.hover_tooltip import HoverTooltip
from freeassetfilter.widgets.smooth_scroller import SmoothScroller
from freeassetfilter.utils.file_icon_helper import get_file_icon_path
from freeassetfilter.core.managers.thumbnail_manager import get_thumbnail_manager, get_existing_thumbnail_path, is_media_file
from freeassetfilter.widgets.file_selector_model import FileSelectorListModel, FileListView
from freeassetfilter.widgets.file_selector_delegate import FileBlockCardDelegate
from freeassetfilter.widgets.file_horizontal_card_delegate import FileHorizontalCardDelegate
from freeassetfilter.services.file_service import FileService
from freeassetfilter.services.favorites_service import FavoritesService
from freeassetfilter.services.drive_service import DriveService


class ThumbnailGeneratorThread(QThread):
    """
    缩略图生成后台线程
    在后台线程中生成缩略图，避免阻塞UI
    """
    progress_updated = Signal(int, int, dict)  # 当前索引、总數、文件信息
    thumbnail_created = Signal(dict)  # 文件信息
    finished = Signal(int, int)  # 成功数、总數
    error_occurred = Signal(str, Exception)  # 文件路径、错误

    def __init__(self, thumbnail_manager, files_to_generate):
        super().__init__()
        self.thumbnail_manager = thumbnail_manager
        self.files_to_generate = files_to_generate
        self._is_cancelled = False

    def run(self):
        total_count = len(self.files_to_generate)

        if total_count <= 0:
            self.finished.emit(0, 0)
            return

        def _on_progress(current, total, file_data, success):
            if success:
                self.thumbnail_created.emit(file_data)
            self.progress_updated.emit(current, total, file_data)

        def _cancel_check():
            return self._is_cancelled

        try:
            success_count, processed_count = self.thumbnail_manager.create_thumbnails_batch(
                self.files_to_generate,
                progress_callback=_on_progress,
                cancel_check=_cancel_check
            )
            final_total = processed_count if self._is_cancelled else total_count
            self.finished.emit(success_count, final_total)
        except Exception as e:
            self.error_occurred.emit("batch_generate", e)
            self.finished.emit(0, 0)

    def cancel(self):
        self._is_cancelled = True


class DriveListLoaderThread(QThread):
    loaded = Signal(list, list)

    def run(self):
        try:
            local_drives = []
            network_locations = []

            if sys.platform == 'win32':
                try:
                    local_drives = DriveService._list_windows_drives()
                    network_locations = DriveService._list_windows_network_locations()
                except Exception as e:
                    warning(f"获取盘符列表失败: {e}")
            else:
                local_drives = ['/']

            local_drives = sorted(set(local_drives))
            network_locations = sorted(set(network_locations))
            self.loaded.emit(local_drives, network_locations)
        except Exception:
            error(f"DriveListLoaderThread.run() 异常: {traceback.format_exc()}")


class FileListLoaderThread(QThread):
    loaded = Signal(str, list)
    failed = Signal(str, str)

    def __init__(self, current_path, parent=None):
        super().__init__(parent)
        self.current_path = current_path

    def run(self):
        files = []

        try:
            if self.current_path == "All":
                if sys.platform == 'win32':
                    import ctypes
                    kernel32 = ctypes.windll.kernel32
                    drives_bitmask = kernel32.GetLogicalDrives()
                    for drive in range(26):
                        if drives_bitmask & (1 << drive):
                            drive_name = chr(65 + drive) + ':'
                            drive_path = drive_name + '\\'
                            try:
                                stat = os.stat(drive_path)
                                modified = QDateTime.fromSecsSinceEpoch(int(stat.st_mtime)).toString(Qt.ISODate)
                                created = QDateTime.fromSecsSinceEpoch(int(stat.st_ctime)).toString(Qt.ISODate)
                            except OSError:
                                modified = ""
                                created = ""

                            files.append({
                                "name": drive_name,
                                "path": drive_path,
                                "is_dir": True,
                                "size": 0,
                                "modified": modified,
                                "created": created,
                                "suffix": ""
                            })
                else:
                    root_path = "/"
                    try:
                        stat = os.stat(root_path)
                        modified = QDateTime.fromSecsSinceEpoch(int(stat.st_mtime)).toString(Qt.ISODate)
                        created = QDateTime.fromSecsSinceEpoch(int(stat.st_ctime)).toString(Qt.ISODate)
                    except OSError:
                        modified = ""
                        created = ""

                    files.append({
                        "name": root_path,
                        "path": root_path,
                        "is_dir": True,
                        "size": 0,
                        "modified": modified,
                        "created": created,
                        "suffix": ""
                    })
            else:
                if os.path.islink(self.current_path):
                    raise OSError("拒绝扫描符号链接目录")

                file_service = FileService()
                files = file_service.scan_directory(self.current_path)

            self.loaded.emit(self.current_path, files)
        except Exception as e:
            self.failed.emit(self.current_path, str(e))


class _JsonWriteRunnable(QRunnable):
    """JSON 写操作后台任务（异步触发，不等待结果）"""
    def __init__(self, filepath, data_func):
        super().__init__()
        self._filepath = filepath
        self._data_func = data_func

    def run(self):
        try:
            os.makedirs(os.path.dirname(self._filepath), exist_ok=True)
            with open(self._filepath, 'w', encoding='utf-8') as f:
                json.dump(self._data_func(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            warning(f"后台JSON写入失败 {self._filepath}: {e}")


class _JsonReadSignals(QObject):
    finished = Signal(object)  # 数据字典或 None


class _JsonReadRunnable(QRunnable):
    """JSON 读操作后台任务"""
    def __init__(self, filepath, signals):
        super().__init__()
        self._filepath = filepath
        self._signals = signals

    def run(self):
        try:
            data = None
            if os.path.exists(self._filepath):
                with open(self._filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
        except Exception:
            data = None
        self._signals.finished.emit(data)


class _DriveAvailabilitySignals(QObject):
    """盘符可用性检查完成信号桥接器，用于 QRunnable。"""
    finished = Signal(str, bool)  # drive_path, available


class _DriveAvailabilityCheckRunnable(QRunnable):
    """后台盘符可用性检查，使用 os.scandir()。"""

    def __init__(self, drive_path: str, signals: _DriveAvailabilitySignals):
        super().__init__()
        self._drive_path = drive_path
        self._signals = signals

    def run(self):
        available = False
        try:
            drive_path = self._drive_path
            if not drive_path.endswith(('\\', '/')):
                drive_path = drive_path + '\\'
            if os.path.exists(drive_path):
                with os.scandir(drive_path) as it:
                    next(it, None)
                available = True
        except StopIteration:
            # 空目录——仍然可用
            available = True
        except (OSError, PermissionError):
            available = False
        except Exception:
            available = False
        self._signals.finished.emit(self._drive_path, available)


class CustomFileSelector(QWidget):
    """
    自定义文件选择器组件
    使用卡片式布局，实现鼠标悬停高亮和点击选择功能
    """
    
    # 定义信号
    file_selected = Signal(dict)  # 当文件被选中时发出
    file_right_clicked = Signal(dict)  # 当文件被右键点击时发出
    file_selection_changed = Signal(dict, bool)  # 当文件选择状态改变时发出
    preview_cancel_requested = Signal()  # 当点击正在预览的卡片时发出，用于取消预览
    drive_availability_changed = Signal(str, bool)  # drive_path, available — from background check
    
    def __init__(self, parent=None, global_font=None, dpi_scale=None, settings_manager=None):
        super().__init__(parent)
        
        # 获取应用实例和DPI缩放因子
        if dpi_scale is not None:
            self.dpi_scale = dpi_scale
        else:
            self.dpi_scale = getattr(QApplication.instance(), 'dpi_scale_factor', 1.0)
        
        # 获取全局字体
        app = QApplication.instance()
        if global_font is not None:
            self.global_font = global_font
        else:
            self.global_font = getattr(app, 'global_font', QFont())

        # 初始化设置管理器
        if settings_manager is not None:
            self._settings_manager = settings_manager
        else:
            from freeassetfilter.core.managers.settings_manager import SettingsManager
            self._settings_manager = SettingsManager()
        
        # 设置组件字体
        self.setFont(self.global_font)
        
        # 计算卡片基础宽度（与 FileBlockCard 保持一致）
        card_width = self._calculate_card_base_width()
        spacing = int(4 * self.dpi_scale)  # 卡片间距
        margin = int(5 * self.dpi_scale)  # 单边边距
        # 3列卡片总宽度 = 3*卡片宽度 + 2*间距（因为3列只有2个间距）
        cards_total_width = 3 * card_width + 2 * spacing
        # 左右边距总和
        margins_total = 2 * margin
        # 总最小宽度 = 卡片总宽度 + 边距总和
        min_three_columns_width = cards_total_width + margins_total
        
        # 设置文件选择器的最小宽度，确保能显示3列卡片
        self.setMinimumWidth(min_three_columns_width)
        
        # 初始化配置
        self.current_path = "All"  # 默认路径为"All"
        self._last_accessible_path = "All"  # 最近一次成功加载的目录，用于读取失败后恢复
        self._navigation_recovery_path = "All"  # 当前导航请求失败时应返回的来源目录
        self.selected_files = {}  # 存储每个目录下的选中文件 {directory: {file_path1, file_path2}}]
        self._selected_file_paths = set()  # 扁平化选中集合（规范化路径），用于 O(1) 选中判断
        self.previewing_file_path = None  # 当前处于预览态的文件路径
        self.filter_pattern = "*"  # 默认显示所有文件
        self.sort_by = "name"  # 默认按名称排序
        self.sort_order = "asc"  # 默认升序
        self.view_mode = "card"  # 默认卡片视图
        self.save_view_mode_file = os.path.join(os.path.dirname(__file__), "..", "..", "data", "view_mode.json")
        self._view_mode_loaded = False
        
        # 保存当前路径到文件
        self.save_path_file = os.path.join(os.path.dirname(__file__), "..", "..", "data", "last_path.json")
        
        # 收藏夹配置文件（延迟加载）
        self.favorites_file = os.path.join(os.path.dirname(__file__), "..", "..", "data", "favorites.json")
        self.favorites = []
        self._favorites_loaded = False
        
        # 初始化服务实例
        self._file_service = FileService()
        self._favorites_service = FavoritesService(self.favorites_file)
        self._drive_service = DriveService()
        
        # 确保数据目录存在
        os.makedirs(os.path.dirname(self.save_path_file), exist_ok=True)
        os.makedirs(os.path.dirname(self.favorites_file), exist_ok=True)
        
        # JSON 读取信号对象
        self._json_read_signals = None
        self._pending_path_data = None
        self._pending_view_mode = None
        
        # 文件选择器 Model/View 架构相关
        self.file_model = FileSelectorListModel(self.dpi_scale, self.global_font)
        self.card_delegate = FileBlockCardDelegate(self.dpi_scale, self.global_font)
        self.list_delegate = FileHorizontalCardDelegate(self.dpi_scale, self.global_font)
        self.files_scroll_area = None
        self._is_loading = False
        self._drive_list_thread = None
        self._file_loader_thread = None
        self._refresh_request_id = 0
        self._cached_local_drives = []
        self._cached_network_locations = []
        self._drive_availability_cache: dict[str, tuple[bool, float]] = {}  # drive_path -> (available, timestamp)
        self._drive_availability_cache_ttl = 5.0  # seconds
        self._pending_path_transition_direction = 0
        self._pending_path_transition_token = 0
        
        # 首次显示标志位，用于避免初始化时卡片重叠
        self._first_show = True
        self._thumbnail_thread = None
        
        # 初始化悬浮详细信息组件
        self.hover_tooltip = HoverTooltip(self)
        
        # 初始化UI
        self.init_ui()
        
        # 应用已恢复的视图模式（列表/网格）
        self._apply_view_mode()
        
        # 启用拖拽功能
        self.setAcceptDrops(True)
        self.files_scroll_area.setAcceptDrops(True)
        
        # 检查是否有右键菜单传入的初始导航路径
        app = QApplication.instance()
        initial_navigate_path = getattr(app, 'initial_navigate_path', None)
        if initial_navigate_path and self._is_valid_selector_path(initial_navigate_path):
            self.current_path = initial_navigate_path
            self._last_accessible_path = initial_navigate_path
            self._navigation_recovery_path = initial_navigate_path
        elif self._settings_manager.get_setting("file_selector.restore_last_path", True):
            self.load_last_path()
        else:
            self.current_path = "All"
        
        # 为路径输入框添加悬浮信息功能
        self.hover_tooltip.set_target_widget(self.path_edit)

        
        # 初始化按钮样式
        self._update_filter_button_style()
        # 不在这里初始化文件列表，而是在showEvent中初始化，避免卡片重叠
    
    def showEvent(self, event):
        """
        窗口显示事件处理
        - 首次显示时才初始化文件列表，避免初始化时卡片重叠
        """
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            # 延迟一点时间确保布局已经完成
            from PySide6.QtCore import QTimer
            QTimer.singleShot(50, self.refresh_files)
    
    def load_last_path(self):
        """
        从文件中异步加载上次打开的路径（后台线程读取）
        """
        signals = _JsonReadSignals()
        # 保持强引用直到信号触发
        signals.finished.connect(self._on_last_path_loaded)
        QThreadPool.globalInstance().start(_JsonReadRunnable(self.save_path_file, signals))

    def _on_last_path_loaded(self, data):
        """处理异步加载的上次路径结果"""
        if data is None:
            return
        try:
            last_accessible_path = data.get("last_accessible_path")
            if self._is_valid_selector_path(last_accessible_path):
                self._last_accessible_path = last_accessible_path
                self._navigation_recovery_path = last_accessible_path

            if "last_path" in data:
                last_path = data["last_path"]
                if self._is_valid_selector_path(last_path):
                    self.current_path = last_path
        except Exception as e:
            warning(f"处理上次路径数据失败: {e}")

    def save_current_path(self, path=None):
        """
        异步防抖保存当前路径到文件（后台线程写入）
        """
        last_accessible_path = getattr(self, "_last_accessible_path", "All")
        if path is None:
            current_path = getattr(self, "current_path", "All")
            if self._same_selector_path(current_path, last_accessible_path):
                path_to_save = current_path
            else:
                path_to_save = getattr(self, "_navigation_recovery_path", None) or last_accessible_path or "All"
        else:
            path_to_save = path

        self._pending_path_data = {
            "last_path": path_to_save,
            "last_accessible_path": last_accessible_path,
        }
        HeartbeatManager().request_main_thread(self._flush_path_save, priority=4)

    def _flush_path_save(self):
        """防抖到期后实际执行路径保存"""
        data = self._pending_path_data
        if data is None:
            return
        self._pending_path_data = None
        QThreadPool.globalInstance().start(
            _JsonWriteRunnable(self.save_path_file, lambda: data)
        )

    def _load_view_mode(self):
        if self._view_mode_loaded:
            return
        self._view_mode_loaded = True
        signals = _JsonReadSignals()
        signals.finished.connect(self._on_view_mode_loaded)
        QThreadPool.globalInstance().start(_JsonReadRunnable(self.save_view_mode_file, signals))

    def _on_view_mode_loaded(self, data):
        """处理异步加载的视图模式结果"""
        if data is None:
            return
        try:
            mode = data.get("view_mode", "card")
            if mode in ("card", "list"):
                self.view_mode = mode
        except Exception as e:
            warning(f"处理视图模式数据失败: {e}")

    def save_view_mode(self):
        """
        异步防抖保存视图模式到文件（后台线程写入）
        """
        self._pending_view_mode = self.view_mode
        HeartbeatManager().request_main_thread(self._flush_view_mode_save, priority=4)

    def _flush_view_mode_save(self):
        """防抖到期后实际执行视图模式保存"""
        mode = self._pending_view_mode
        if mode is None:
            return
        self._pending_view_mode = None
        QThreadPool.globalInstance().start(
            _JsonWriteRunnable(self.save_view_mode_file, lambda: {"view_mode": mode})
        )

    def init_ui(self):
        """
        初始化用户界面
        """
        # 创建主布局
        main_layout = QVBoxLayout(self)
        # 获取主题颜色
        app = QApplication.instance()
        background_color = "#f1f3f5"  # 默认窗口背景色
        if hasattr(app, 'settings_manager'):
            background_color = self._settings_manager.get_setting("appearance.colors.panel_background", "#f1f3f5")
        self.setStyleSheet(f"background-color: {background_color};")
        # 应用DPI缩放因子到布局参数
        scaled_spacing = int(2.5 * self.dpi_scale)
        scaled_margin = int(2.5 * self.dpi_scale)
        main_layout.setSpacing(scaled_spacing)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        
        # 创建顶部控制面板
        control_panel = self._create_control_panel()
        self.control_panel = control_panel
        main_layout.addWidget(control_panel)
        
        # 创建文件列表区域
        files_area = self._create_files_area()
        self.files_area = files_area
        main_layout.addWidget(files_area, 1)
        
        # 创建底部状态栏
        status_bar = self._create_status_bar()
        self.status_bar = status_bar
        main_layout.addWidget(status_bar)
    
    def _create_control_panel(self):
        """
        创建控制面板
        """
        panel = QGroupBox()
        
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        # 获取设置管理器中的颜色值
        app = QApplication.instance()
        base_color = "#212121"  # 默认base_color
        if hasattr(app, 'settings_manager'):
            base_color = self._settings_manager.get_setting("appearance.colors.base_color", "#212121")
        
        # 设置面板样式：隐藏边框，使用base_color作为背景色
        panel.setStyleSheet(f"QGroupBox {{ border: none; background-color: {base_color}; }}")
        
        # 使用垂直布局来容纳多行控件
        main_layout = QVBoxLayout(panel)
        main_layout.setSpacing(5)
        main_layout.setContentsMargins(5, 5, 5, 5)
        
        # 第一行：目录选择功能
        dir_layout = QHBoxLayout()
        dir_layout.setSpacing(5)
        
        # 盘符选择器 - 使用外部按钮+下拉菜单模式
        # 创建盘符选择按钮，使用driver.svg图标
        import os
        driver_icon_path = os.path.join(os.path.dirname(__file__), "..", "icons", "driver.svg")
        self.drive_btn = CustomButton(driver_icon_path, button_type="normal", display_mode="icon", tooltip_text="选择盘符")
        # 创建下拉菜单（不使用内部按钮）
        self.drive_combo = CustomDropdownMenu(self, position="bottom", use_internal_button=False)
        # 设置外部目标按钮
        self.drive_combo.set_target_button(self.drive_btn)
        # 盘符菜单使用特殊模式：不使用滚动布局，条目完整显示
        self.drive_combo.set_use_scroll_layout(False)
        # 盘符菜单宽度改为按内容自适应，不再设置固定宽度
        # 动态获取当前系统存在的盘符
        self._apply_drive_list(["All"], default_item="All")
        self._update_drive_list()
        self.drive_combo.itemClicked.connect(self._on_drive_changed)
        # 连接菜单即将打开信号，在显示菜单前刷新盘符列表
        self.drive_combo.menuOpening.connect(self._update_drive_list)
        # 连接按钮点击事件到下拉菜单的toggle_menu
        self.drive_btn.clicked.connect(self.drive_combo.toggle_menu)
        dir_layout.addWidget(self.drive_btn)
        
        # 目录显示区域（可编辑）
        self.path_edit = CustomInputBox(
            placeholder_text="输入路径",
            height=20
        )
        self.path_edit.line_edit.returnPressed.connect(self.go_to_path)
        dir_layout.addWidget(self.path_edit, 1)
        
        # 前往按钮
        import os
        arrow_right_icon_path = os.path.join(os.path.dirname(__file__), "..", "icons", "arrow_right.svg")
        go_btn = CustomButton(arrow_right_icon_path, button_type="normal", display_mode="icon", tooltip_text="前往")
        self.go_btn = go_btn
        go_btn.clicked.connect(self.go_to_path)
        dir_layout.addWidget(go_btn)
        # 添加到悬浮信息目标控件
        self.hover_tooltip.set_target_widget(go_btn)
        
        # 添加当前路径到收藏夹按钮（路径栏最右侧）
        star_icon_path = os.path.join(os.path.dirname(__file__), "..", "icons", "star.svg")
        self.add_fav_btn = CustomButton(star_icon_path, button_type="normal", display_mode="icon", tooltip_text="添加当前路径到收藏夹")
        self.add_fav_btn.clicked.connect(self._add_current_path_to_favorites_standalone)
        dir_layout.addWidget(self.add_fav_btn)
        self.hover_tooltip.set_target_widget(self.add_fav_btn)
        
        main_layout.addLayout(dir_layout)
        
        # 第二行：返回上级和刷新按钮
        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(5)
        
        # 返回上级文件夹按钮
        import os
        unto_icon_path = os.path.join(os.path.dirname(__file__), "..", "icons", "unto.svg")
        self.parent_btn = CustomButton(unto_icon_path, button_type="normal", display_mode="icon", tooltip_text="返回上级文件夹")
        self.parent_btn.clicked.connect(self.go_to_parent)
        nav_layout.addWidget(self.parent_btn)
        # 添加到悬浮信息目标控件
        self.hover_tooltip.set_target_widget(self.parent_btn)
        
        # 刷新按钮
        import os
        refresh_icon_path = os.path.join(os.path.dirname(__file__), "..", "icons", "refresh.svg")
        refresh_btn = CustomButton(refresh_icon_path, button_type="normal", display_mode="icon", tooltip_text="刷新")
        self.refresh_btn = refresh_btn
        refresh_btn.clicked.connect(self.refresh_files)
        nav_layout.addWidget(refresh_btn)
        # 添加到悬浮信息目标控件
        self.hover_tooltip.set_target_widget(refresh_btn)
        
        # 收藏夹按钮
        import os
        star_icon_path = os.path.join(os.path.dirname(__file__), "..", "icons", "star.svg")
        self.favorites_btn = CustomButton(star_icon_path, button_type="normal", display_mode="icon", tooltip_text="收藏夹")
        self.favorites_btn.clicked.connect(self._show_favorites_dialog)
        nav_layout.addWidget(self.favorites_btn)
        # 添加到悬浮信息目标控件
        self.hover_tooltip.set_target_widget(self.favorites_btn)
        
        # 筛选按钮
        import os
        sift_icon_path = os.path.join(os.path.dirname(__file__), "..", "icons", "sift.svg")
        self.filter_btn = CustomButton(sift_icon_path, button_type="normal", display_mode="icon", tooltip_text="筛选")
        self.filter_btn.clicked.connect(self.apply_filter)
        nav_layout.addWidget(self.filter_btn)
        # 添加到悬浮信息目标控件
        self.hover_tooltip.set_target_widget(self.filter_btn)
        
        # 排序方式按钮
        import os
        sort_icon_path = os.path.join(os.path.dirname(__file__), "..", "icons", "sort.svg")
        self.sort_btn = CustomButton(sort_icon_path, button_type="normal", display_mode="icon", tooltip_text="排序方式")
        nav_layout.addWidget(self.sort_btn)
        # 添加到悬浮信息目标控件
        self.hover_tooltip.set_target_widget(self.sort_btn)
        
        # 排序方式下拉菜单（使用外部按钮，不创建内部按钮）
        self.sort_menu = CustomDropdownMenu(self, position="bottom", use_internal_button=False)
        # 排序菜单保持内容自适应宽度，不设置固定宽度
        sort_items = [
            {"text": "名称升序", "data": ("name", "asc")},
            {"text": "名称降序", "data": ("name", "desc")},
            {"text": "大小升序", "data": ("size", "asc")},
            {"text": "大小降序", "data": ("size", "desc")},
            {"text": "修改时间升序", "data": ("modified", "asc")},
            {"text": "修改时间降序", "data": ("modified", "desc")},
            {"text": "创建时间升序", "data": ("created", "asc")},
            {"text": "创建时间降序", "data": ("created", "desc")}
        ]
        self.sort_menu.set_items(sort_items, default_item=sort_items[0])
        self.sort_menu.set_target_button(self.sort_btn)
        self.sort_menu.itemClicked.connect(self._on_sort_item_clicked)
        
        def show_sort_menu():
            self.sort_menu.set_target_button(self.sort_btn)
            self.sort_menu.show_menu()
        
        self.sort_btn.clicked.connect(show_sort_menu)
        
        # 视图模式切换按钮
        card_icon_path = os.path.join(os.path.dirname(__file__), "..", "icons", "card.svg")
        self.view_mode_btn = CustomButton(card_icon_path, button_type="normal", display_mode="icon", tooltip_text="网格视图")
        self.view_mode_btn._primary_icon_name = "list.svg"
        self.view_mode_btn._alt_icon_name = "card.svg"
        self.view_mode_btn.clicked.connect(self._toggle_view_mode)
        nav_layout.addWidget(self.view_mode_btn)
        self.hover_tooltip.set_target_widget(self.view_mode_btn)

        main_layout.addLayout(nav_layout)
        
        return panel
    
    def _create_files_area(self):
        """
        创建文件列表区域 - 使用 Model/View 架构
        """
        app = QApplication.instance()
        panel_bg_color = "#f1f3f5"
        auxiliary_color = "#313131"
        normal_color = "#717171"
        secondary_color = "#FFFFFF"
        accent_color = "#F0C54D"
        
        if hasattr(app, 'settings_manager'):
            panel_bg_color = self._settings_manager.get_setting("appearance.colors.panel_background", "#f1f3f5")
            auxiliary_color = self._settings_manager.get_setting("appearance.colors.auxiliary_color", "#313131")
            normal_color = self._settings_manager.get_setting("appearance.colors.normal_color", "#717171")
            secondary_color = self._settings_manager.get_setting("appearance.colors.secondary_color", "#FFFFFF")
            accent_color = self._settings_manager.get_setting("appearance.colors.accent_color", "#F0C54D")
        
        self._card_spacing = int(4 * self.dpi_scale)

        # 使用 QListView 替代 QScrollArea + QGridLayout
        self.files_scroll_area = FileListView(self)
        self.files_scroll_area.setObjectName("fileListView")
        
        # 设置 Model 和 Delegate
        self.files_scroll_area.setModel(self.file_model)
        self.files_scroll_area.setItemDelegate(self.card_delegate)
        self.card_delegate.set_view(self.files_scroll_area)
        self.list_delegate.set_view(self.files_scroll_area)
        
        # 配置 QListView 属性
        self.files_scroll_area.setViewMode(QListView.IconMode)
        self.files_scroll_area.setResizeMode(QListView.Fixed)
        self.files_scroll_area.setMovement(QListView.Static)
        self.files_scroll_area.setSelectionMode(QListView.ExtendedSelection)
        self.files_scroll_area.setUniformItemSizes(True)
        self.files_scroll_area.setLayoutMode(QListView.Batched)
        self.files_scroll_area.setWrapping(True)
        self.files_scroll_area.setFlow(QListView.LeftToRight)
        # 卡片之间的外边距由 gridSize 中预留的单元格空白提供，
        # 不再额外叠加 QListView.spacing，避免布局口径再次分裂。
        self.files_scroll_area.setSpacing(0)
        self.files_scroll_area.setBatchSize(50)
        
        # 禁用垂直滚动条
        self.files_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # 应用平滑滚动
        # 注意：这里必须禁用 LeftMouseButtonGesture，
        # 否则会与文件卡片的长按拖拽手势竞争，导致长按拖拽异常。
        SmoothScroller.apply(self.files_scroll_area, enable_mouse_drag=False)
        
        # 设置像素级滚动模式
        self.files_scroll_area.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.files_scroll_area.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

        # 滚动区域样式（与原来保持一致）
        scaled_padding = int(3 * self.dpi_scale)
        container_style = f"""
            QListView {{
                border: 1px solid {normal_color};
                border-radius: 8px;
                background-color: {panel_bg_color};
                padding: {scaled_padding}px;
            }}
        """
        self.files_scroll_area.setStyleSheet(container_style)

        self.files_container = self.files_scroll_area
        
        # 连接信号
        self.files_scroll_area.file_clicked.connect(self._handle_card_clicked_signal)
        self.files_scroll_area.file_double_clicked.connect(self._handle_card_double_clicked_signal)
        self.files_scroll_area.file_right_clicked.connect(self._handle_card_right_clicked_signal)
        self.files_scroll_area.file_selection_changed.connect(self._handle_card_selection_changed_signal)
        self.files_scroll_area.file_drag_started.connect(self._on_card_drag_started)
        self.files_scroll_area.file_drag_ended.connect(self._on_card_drag_ended)
        self.files_scroll_area.navigate_parent_requested.connect(self.go_to_parent)
        
        # 安装事件过滤器
        self.files_scroll_area.viewport().installEventFilter(self)
        self.files_scroll_area.installEventFilter(self)
        self.hover_tooltip.set_target_widget(self.files_scroll_area)
        self.hover_tooltip.set_target_widget(self.files_scroll_area.viewport())

        return self.files_scroll_area
    
    def _create_status_bar(self):
        """
        创建状态栏
        """
        status_bar = QFrame()
        status_bar.setFrameShape(QFrame.HLine)
        status_bar.setFrameShadow(QFrame.Sunken)
        
        app = QApplication.instance()
        base_color = "#FFFFFF"
        if hasattr(app, 'settings_manager'):
            base_color = self._settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF")
        
        status_bar.setStyleSheet(f"QFrame {{ border: none; background-color: {base_color}; }}")
        layout = QHBoxLayout(status_bar)
        

        
        # 生成缩略图按钮
        self.generate_thumbnails_btn = CustomButton("生成缩略图", button_type="primary")
        self.generate_thumbnails_btn.clicked.connect(self._generate_thumbnails)
        layout.addWidget(self.generate_thumbnails_btn)
        
        # 清理缩略图缓存按钮
        # 使用clean.svg图标替换文字
        import os
        clean_icon_path = os.path.join(os.path.dirname(__file__), "..", "icons", "clean.svg")
        self.clear_thumbnails_btn = CustomButton(clean_icon_path, button_type="normal", display_mode="icon", tooltip_text="清理缩略图缓存")
        self.clear_thumbnails_btn.clicked.connect(self._clear_thumbnail_cache)
        layout.addWidget(self.clear_thumbnails_btn)
        # 添加到悬浮信息目标控件
        self.hover_tooltip.set_target_widget(self.clear_thumbnails_btn)
        
        return status_bar

    def _get_theme_colors(self):
        """
        获取当前主题颜色
        """
        app = QApplication.instance()
        colors = {
            "base_color": "#212121",
            "auxiliary_color": "#f1f3f5",
            "normal_color": "#717171",
            "secondary_color": "#FFFFFF",
            "accent_color": "#F0C54D",
            "panel_background": "#f1f3f5",
        }

        if hasattr(app, "settings_manager"):
            colors["base_color"] = self._settings_manager.get_setting("appearance.colors.base_color", colors["base_color"])
            colors["auxiliary_color"] = self._settings_manager.get_setting("appearance.colors.auxiliary_color", colors["auxiliary_color"])
            colors["normal_color"] = self._settings_manager.get_setting("appearance.colors.normal_color", colors["normal_color"])
            colors["secondary_color"] = self._settings_manager.get_setting("appearance.colors.secondary_color", colors["secondary_color"])
            colors["accent_color"] = self._settings_manager.get_setting("appearance.colors.accent_color", colors["accent_color"])
            colors["panel_background"] = self._settings_manager.get_setting("appearance.colors.panel_background", colors["panel_background"])

        return colors

    def update_theme(self):
        """
        增量刷新文件选择器主题，不重建文件列表
        """
        FileBlockCard._clear_shared_caches()
        self.file_model.clear_caches(emit_change=True)
        self.card_delegate.update_theme()
        self.list_delegate.update_theme()
        colors = self._get_theme_colors()

        self.setStyleSheet(f"background-color: {colors['panel_background']};")

        if hasattr(self, "control_panel") and self.control_panel:
            self.control_panel.setStyleSheet(
                f"QGroupBox {{ border: none; background-color: {colors['base_color']}; }}"
            )

        if hasattr(self, "path_edit") and self.path_edit and hasattr(self.path_edit, "update_theme"):
            try:
                self.path_edit.update_theme()
            except Exception:
                pass

        if hasattr(self, "status_bar") and self.status_bar:
            self.status_bar.setStyleSheet(
                f"QFrame {{ border: none; background-color: {colors['base_color']}; }}"
            )

        if hasattr(self, "files_scroll_area") and self.files_scroll_area:
            scaled_padding = int(3 * self.dpi_scale)
            container_style = f"""
                QListView {{
                    border: 1px solid {colors['normal_color']};
                    border-radius: 8px;
                    background-color: {colors['panel_background']};
                    padding: {scaled_padding}px;
                }}
            """
            self.files_scroll_area.setStyleSheet(container_style)
            if hasattr(self.files_scroll_area, "refresh_interaction_settings"):
                try:
                    self.files_scroll_area.refresh_interaction_settings()
                except Exception:
                    pass

        for button_name in (
            "drive_btn",
            "go_btn",
            "parent_btn",
            "refresh_btn",
            "favorites_btn",
            "filter_btn",
            "sort_btn",
            "view_mode_btn",
            "generate_thumbnails_btn",
            "clear_thumbnails_btn",
        ):
            button = getattr(self, button_name, None)
            if button and hasattr(button, "update_theme"):
                try:
                    button.update_theme()
                except Exception:
                    pass

        for menu_name in ("drive_combo", "sort_menu"):
            menu = getattr(self, menu_name, None)
            if menu and hasattr(menu, "update_theme"):
                try:
                    menu.update_theme()
                except Exception:
                    pass

        if hasattr(self, "hover_tooltip") and self.hover_tooltip:
            try:
                self.hover_tooltip.update()
            except Exception:
                pass

        self.files_scroll_area.update()
    
    def _generate_thumbnails(self):
        """
        生成当前目录下所有照片和视频的缩略图
        同时也为文件存储池中的照片和视频生成缩略图
        使用后台线程处理，避免阻塞UI
        """
        if self._thumbnail_thread and self._thumbnail_thread.isRunning():
            from freeassetfilter.widgets.D_widgets import CustomMessageBox
            info_msg = CustomMessageBox(self)
            info_msg.set_title("提示")
            info_msg.set_text("已有缩略图生成任务正在进行，请等待当前任务完成。")
            info_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            info_msg.buttonClicked.connect(info_msg.close)
            info_msg.exec()
            return

        # 获取缩略图管理器
        thumbnail_manager = get_thumbnail_manager(self.dpi_scale)

        files_to_generate = []

        files = self._get_files()
        for file in files:
            if not file["is_dir"]:
                if thumbnail_manager.is_media_file(file["path"]):
                    if not thumbnail_manager.has_thumbnail(file["path"]):
                        files_to_generate.append({
                            "path": file["path"],
                            "name": file["name"],
                            "source": "selector"
                        })

        staging_pool_files = []
        staging_pool = self._get_staging_pool()
        if staging_pool and hasattr(staging_pool, 'items'):
            for item in staging_pool.items:
                if not item.get("is_dir", False):
                    file_path = item.get("path", "")
                    if not file_path:
                        continue

                    if thumbnail_manager.is_media_file(file_path):
                        if not thumbnail_manager.has_thumbnail(file_path):
                            staging_pool_files.append({
                                "path": file_path,
                                "name": item.get("name", os.path.basename(file_path)),
                                "source": "staging_pool"
                            })

        if staging_pool_files:
            files_to_generate.extend(staging_pool_files)

        if not files_to_generate:
            from freeassetfilter.widgets.D_widgets import CustomMessageBox
            info_msg = CustomMessageBox(self)
            info_msg.set_title("提示")
            info_msg.set_text("所有文件都已有缩略图，无需重新生成")
            info_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            info_msg.buttonClicked.connect(info_msg.close)
            info_msg.exec()
            return

        from freeassetfilter.widgets.D_widgets import CustomMessageBox
        from freeassetfilter.widgets.progress_widgets import D_ProgressBar

        progress_msg = CustomMessageBox(self)
        progress_msg.set_title("生成缩略图")
        progress_msg.set_text(f"正在生成缩略图... (0/{len(files_to_generate)})")

        progress_bar = D_ProgressBar()
        progress_bar.setRange(0, len(files_to_generate))
        progress_bar.setValue(0)
        progress_bar.setInteractive(False)
        progress_msg.set_progress(progress_bar)

        progress_msg.set_buttons(["取消"], Qt.Horizontal, ["normal"])

        is_canceled = False

        def on_cancel_clicked():
            nonlocal is_canceled
            is_canceled = True
            self.generate_thumbnails_btn.setEnabled(True)
            if self._thumbnail_thread and self._thumbnail_thread.isRunning():
                self._thumbnail_thread.cancel()
            progress_msg.close()

        progress_msg.buttonClicked.connect(on_cancel_clicked)

        progress_msg.show()

        self.generate_thumbnails_btn.setEnabled(False)
        self._thumbnail_thread = ThumbnailGeneratorThread(thumbnail_manager, files_to_generate)

        progress_throttler = ProgressThrottler(min_interval_ms=50)

        def _do_progress_update(current, total, file_data):
            progress_bar.setValue(current, use_animation=False)
            progress_msg.set_text(f"正在生成缩略图... ({current}/{total})")

        def on_progress_updated(current, total, file_data):
            progress_throttler.update(current, total, file_data, _do_progress_update)

        def on_thumbnail_created(file_data):
            file_path = file_data.get("path")
            FileBlockCard._clear_shared_caches(file_path)
            self.file_model.clear_caches(file_path=file_path, emit_change=True)
            if file_data["source"] == "staging_pool":
                self._refresh_staging_pool_card(file_path)
            self.files_scroll_area.update()

        def on_error_occurred(file_path, error):
            warning(f"生成缩略图失败: {file_path}, 错误: {error}")

        def on_finished(success_count, total_count):
            finished_thread = self._thumbnail_thread
            self.generate_thumbnails_btn.setEnabled(True)
            self._thumbnail_thread = None
            if finished_thread:
                finished_thread.deleteLater()

            # 用户取消后不再弹完成提示
            if is_canceled:
                return

            progress_msg.close()

            staging_pool_count = len([f for f in files_to_generate if f["source"] == "staging_pool"])
            selector_count = len([f for f in files_to_generate if f["source"] == "selector"])

            result_parts = []
            if selector_count > 0:
                result_parts.append(f"当前目录: {selector_count} 个")
            if staging_pool_count > 0:
                result_parts.append(f"存储池: {staging_pool_count} 个")

            result_text = f"缩略图生成完成！成功: {success_count}, 总数: {total_count}"
            if result_parts:
                result_text += f"\n（{'，'.join(result_parts)}）"

            FileBlockCard._clear_shared_caches()
            self.file_model.clear_caches(emit_change=True)
            self.refresh_files()
            staging_pool_for_refresh = self._get_staging_pool()
            if staging_pool_for_refresh:
                self._refresh_staging_pool_thumbnails(staging_pool_for_refresh)

            result_msg = CustomMessageBox(self)
            result_msg.set_title("提示")
            result_msg.set_text(result_text)
            result_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            result_msg.buttonClicked.connect(result_msg.close)
            result_msg.exec()

        self._thumbnail_thread.progress_updated.connect(on_progress_updated)
        self._thumbnail_thread.thumbnail_created.connect(on_thumbnail_created)
        self._thumbnail_thread.error_occurred.connect(on_error_occurred)
        self._thumbnail_thread.finished.connect(on_finished)

        self._thumbnail_thread.start()

    def _get_staging_pool(self):
        """获取文件存储池组件"""
        try:
            parent = self.parent()
            while parent:
                if hasattr(parent, 'file_staging_pool'):
                    return parent.file_staging_pool
                parent = parent.parent()
        except Exception as e:
            error(f"获取文件存储池失败: {e}")
        return None

    def _refresh_staging_pool_thumbnails(self, staging_pool):
        """刷新存储池中的卡片显示

        完全重载所有横向卡片，类似于应用启动时的初始化
        确保主题变更或设置更新后卡片显示完全刷新
        """
        import os
        try:
            # 调用存储池的reload_all_cards方法进行完全重载
            if hasattr(staging_pool, 'reload_all_cards'):
                staging_pool.reload_all_cards()
            else:
                # 兼容旧版本：仅刷新缩略图
                for i, (card, file_info) in enumerate(staging_pool.cards):
                    card.refresh_thumbnail()
        except Exception as e:
            error(f"刷新存储池卡片失败: {e}")

    def _refresh_staging_pool_card(self, file_path):
        """刷新存储池中指定文件的卡片缩略图"""
        try:
            staging_pool = self._get_staging_pool()
            if not staging_pool:
                return
            
            for card, file_info in staging_pool.cards:
                if file_info.get("path") == file_path:
                    card.refresh_thumbnail()
                    break
        except Exception as e:
            error(f"刷新存储池单个卡片缩略图失败: {e}")
        
    def _clear_thumbnail_cache(self):
        """
        清理缩略图缓存，删除所有本地存储的缩略图文件，并刷新页面显示
        """
        from freeassetfilter.widgets.D_widgets import CustomMessageBox

        if not self or not hasattr(self, 'isVisible') or not self.isVisible():
            return

        confirm_msg = CustomMessageBox(self)
        confirm_msg.set_title("确认清理")
        confirm_msg.set_text("确定要清理所有缩略图缓存吗？这将删除所有生成的缩略图，并恢复默认图标显示。")
        confirm_msg.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])

        is_confirmed = False

        def on_confirm_clicked(button_index):
            nonlocal is_confirmed
            is_confirmed = (button_index == 0)
            confirm_msg.close()

        confirm_msg.buttonClicked.connect(on_confirm_clicked)
        confirm_msg.exec()

        if is_confirmed:
            if not self or not hasattr(self, 'isVisible') or not self.isVisible():
                return

            try:
                # 使用缩略图管理器清理缓存
                thumbnail_manager = get_thumbnail_manager(self.dpi_scale)
                file_count = thumbnail_manager.clear_all_thumbnails()

                if file_count > 0:
                    FileBlockCard._clear_shared_caches()
                    if hasattr(self, 'file_model') and self.file_model:
                        try:
                            self.file_model.clear_caches(emit_change=True)
                        except RuntimeError as e:
                            debug(f"清空文件模型缓存失败: {e}")
                    if self and hasattr(self, 'refresh_files'):
                        try:
                            self.refresh_files()
                        except RuntimeError as e:
                            debug(f"刷新文件列表失败: {e}")

                    staging_pool = None
                    if self and hasattr(self, '_get_staging_pool'):
                        try:
                            staging_pool = self._get_staging_pool()
                        except RuntimeError as e:
                            debug(f"获取暂存池失败: {e}")

                    if staging_pool and hasattr(staging_pool, 'cards'):
                        try:
                            self._refresh_staging_pool_thumbnails(staging_pool)
                        except RuntimeError as e:
                            debug(f"刷新暂存池缩略图失败: {e}")

                    if self and hasattr(self, 'isVisible') and self.isVisible():
                        success_msg = CustomMessageBox(self)
                        success_msg.set_title("清理成功")
                        success_msg.set_text(f"已成功清理 {file_count} 个缩略图缓存文件。")
                        success_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])

                        def on_success_ok_clicked():
                            success_msg.close()

                        success_msg.buttonClicked.connect(on_success_ok_clicked)
                        success_msg.exec()
                else:
                    if self and hasattr(self, 'isVisible') and self.isVisible():
                        empty_msg = CustomMessageBox(self)
                        empty_msg.set_title("提示")
                        empty_msg.set_text("缩略图缓存目录为空，无需清理。")
                        empty_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])

                        def on_empty_ok_clicked():
                            empty_msg.close()

                        empty_msg.buttonClicked.connect(on_empty_ok_clicked)
                        empty_msg.exec()
            except Exception as e:
                warning(f"清理缩略图缓存失败: {e}")
                # 清理失败错误提示
                error_msg = CustomMessageBox(self)
                error_msg.set_title("错误")
                error_msg.set_text(f"清理缩略图缓存失败: {e}")
                error_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                
                def on_error_ok_clicked():
                    error_msg.close()
                
                error_msg.buttonClicked.connect(on_error_ok_clicked)
                error_msg.exec()
    
    def go_to_parent(self):
        """
        返回当前目录的上一级
        """
        # 检查当前是否已经在磁盘根目录
        is_root_dir = False
        
        if sys.platform == 'win32':
            # Windows系统：检查是否为磁盘根目录，如 "C:\"
            drive, path = os.path.splitdrive(self.current_path)
            if path in ['\\', '/']:
                is_root_dir = True
        else:
            # Linux/macOS系统：检查是否为根目录 "/"
            if self.current_path == '/':
                is_root_dir = True
        
        # 如果是磁盘根目录，返回到All页面
        if is_root_dir:
            self._navigate_to_path("All")
        else:
            # 否则，执行原有的返回上级目录逻辑
            parent_dir = os.path.dirname(self.current_path)
            if parent_dir and parent_dir != self.current_path:
                self._navigate_to_path(parent_dir)
    
    def _load_favorites(self):
        """
        从文件中加载收藏夹列表（延迟加载，首次访问时读取文件）
        首次读取同步执行（一次性的小文件开销）。
        """
        if self._favorites_loaded:
            return self.favorites
        self._favorites_loaded = True
        try:
            # 同步 FavoritesService 的文件路径（测试可能覆盖 favorites_file）
            if self._favorites_service.favorites_file != self.favorites_file:
                self._favorites_service.favorites_file = self.favorites_file
                self._favorites_service._loaded = False
            items = self._favorites_service.load()
            # 向后兼容：新格式存储 List[str]（纯路径），旧格式存储 List[Dict]
            self.favorites = []
            for item in items:
                if isinstance(item, str):
                    self.favorites.append(
                        {"path": item, "name": os.path.basename(item)}
                    )
                elif isinstance(item, dict) and "path" in item:
                    self.favorites.append(item)
        except Exception as e:
            warning(f"加载收藏夹失败: {e}")
        return self.favorites
    
    def _save_favorites(self):
        """
        异步防抖保存收藏夹列表到文件（后台线程写入）
        """
        self._favorites_save_timer.start()

    def _flush_favorites_save(self):
        """防抖到期后实际执行收藏夹保存"""
        if not self._favorites_loaded:
            self._load_favorites()
        try:
            paths = [f["path"] for f in self.favorites if "path" in f]
            self._favorites_service.save(paths)
        except Exception as e:
            warning(f"保存收藏夹失败: {e}")
    
    def _show_favorites_dialog(self):
        """
        显示收藏夹对话框
        """
        weak_self = weakref.ref(self)
        self._load_favorites()
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 9)
        scaled_font_size = int(default_font_size * self.dpi_scale)
        
        base_color = "#FFFFFF"
        auxiliary_color = "#E6E6E6"
        normal_color = "#808080"
        secondary_color = "#333333"
        accent_color = "#1890ff"
        
        if hasattr(app, 'settings_manager'):
            base_color = self._settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF")
            auxiliary_color = self._settings_manager.get_setting("appearance.colors.auxiliary_color", "#E6E6E6")
            normal_color = self._settings_manager.get_setting("appearance.colors.normal_color", "#808080")
            secondary_color = self._settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
            accent_color = self._settings_manager.get_setting("appearance.colors.accent_color", "#1890ff")
        
        dialog = CustomMessageBox(self)
        dialog.set_title("收藏夹")
        dialog.setMinimumSize(int(300 * self.dpi_scale), int(400 * self.dpi_scale))
        dialog.resize(int(300 * self.dpi_scale), int(450 * self.dpi_scale))

        # 创建模型 — 使用 FileStagingPoolListModel
        model = FileStagingPoolListModel(
            dpi_scale=self.dpi_scale,
            global_font=self.global_font,
            parent=dialog,
        )
        fav_items = []
        for fav in self.favorites:
            fav_items.append({
                "path": fav["path"],
                "name": fav["name"],
                "display_name": fav["name"],
            })
        model.set_files(fav_items)

        # 创建视图 — 可滚动
        view = QListView()
        view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.setViewMode(QListView.ListMode)
        view.setResizeMode(QListView.Adjust)
        view.setSelectionMode(QListView.NoSelection)
        view.setMouseTracking(True)
        view.setVerticalScrollMode(QListView.ScrollPerPixel)
        view.setSpacing(int(3 * self.dpi_scale))
        view.setUniformItemSizes(True)
        view.setEditTriggers(QListView.NoEditTriggers)
        view.setDragEnabled(False)
        SmoothScroller.apply(view)

        # 创建委托 — 使用文件储存池卡片样式
        delegate = FileStagingPoolCardDelegate(
            dpi_scale=self.dpi_scale,
            global_font=self.global_font,
            enable_delete_action=True,
            parent=view,
        )
        view.setModel(model)
        view.setItemDelegate(delegate)
        delegate.set_view(view)

        # 点击收藏项 → 跳转路径
        view.clicked.connect(lambda idx: (s := weak_self()) and s._on_favorite_clicked(
            model.data(idx, model.FilePathRole), dialog
        ))

        # 重命名 / 删除
        delegate.renameRequested.connect(
            lambda path: (s := weak_self()) and s._on_favorite_rename_dlg(path, model, dialog)
        )
        delegate.deleteRequested.connect(
            lambda path: (s := weak_self()) and s._on_favorite_delete_dlg(path, model, dialog)
        )

        dialog.list_layout.addWidget(view)
        dialog.list_widget.show()

        dialog.set_buttons(["关闭"], Qt.Horizontal, ["secondary"])
        
        def on_button_clicked(button_index):
            if button_index == 0:
                dialog.close()
        
        dialog.buttonClicked.connect(on_button_clicked)
        
        dialog.exec()
    
    def _on_favorite_clicked(self, file_path, dialog):
        """
        点击收藏夹项时跳转到对应路径
        """
        if file_path and os.path.exists(file_path):
            self._navigate_to_path(file_path)
            dialog.close()

    def _on_favorite_rename_dlg(self, file_path, model, dialog):
        """
        重命名收藏夹项
        """
        favorite = self._find_favorite_by_path(file_path)
        if not favorite:
            return

        input_dialog = CustomMessageBox(self)
        input_dialog.set_title("重命名收藏夹")
        input_dialog.set_text("请输入新名称:")
        input_dialog.set_input(text=favorite['name'])
        input_dialog.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])
        
        result = None
        def on_button_clicked(button_index):
            nonlocal result
            result = button_index
            input_dialog.close()
        
        input_dialog.buttonClicked.connect(on_button_clicked)
        input_dialog.exec()
        
        if result == 0:
            new_name = input_dialog.get_input()
            if new_name.strip():
                for f in self.favorites:
                    if f['path'] == favorite['path'] and f['name'] == favorite['name']:
                        f['name'] = new_name.strip()
                        break
                self._save_favorites()
                model.update_file(file_path, {"display_name": new_name.strip()})

    def _on_favorite_delete_dlg(self, file_path, model, dialog):
        """
        删除收藏夹项
        """
        favorite = self._find_favorite_by_path(file_path)
        if not favorite:
            return

        msg_box = CustomMessageBox(self)
        msg_box.set_title("删除收藏夹")
        msg_box.set_text(f"确定要删除收藏夹项 '{favorite['name']}' 吗?")
        msg_box.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])
        
        result = None
        def on_button_clicked(button_index):
            nonlocal result
            result = button_index
            msg_box.close()
        
        msg_box.buttonClicked.connect(on_button_clicked)
        msg_box.exec()
        
        if result == 0:
            self.favorites = [f for f in self.favorites if not (f['path'] == favorite['path'] and f['name'] == favorite['name'])]
            self._save_favorites()
            model.finalize_remove_file(file_path)

    def _find_favorite_by_path(self, file_path):
        """根据路径在收藏夹列表中查找对应项"""
        normalized = os.path.normpath(file_path) if file_path else ""
        for f in self.favorites:
            if os.path.normpath(f['path']) == normalized:
                return f
        return None
    
    def _add_current_path_to_favorites_standalone(self):
        """
        添加当前路径到收藏夹（独立版本，从路径栏星标按钮触发）
        """
        current_path = self.current_path
        self._load_favorites()
        
        for favorite in self.favorites:
            if favorite['path'] == current_path:
                msg_box = CustomMessageBox(self)
                msg_box.set_title("提示")
                msg_box.set_text("该路径已在收藏夹中")
                msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                msg_box.buttonClicked.connect(msg_box.close)
                msg_box.exec()
                return
        
        default_name = os.path.basename(current_path) or current_path
        
        input_dialog = CustomMessageBox(self)
        input_dialog.set_title("添加到收藏夹")
        input_dialog.set_text("请输入收藏名称:")
        input_dialog.set_input(text=default_name)
        input_dialog.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])
        
        result = None
        def on_button_clicked(button_index):
            nonlocal result
            result = button_index
            input_dialog.close()
        
        input_dialog.buttonClicked.connect(on_button_clicked)
        input_dialog.exec()
        
        if result == 0:
            name = input_dialog.get_input()
            if name.strip():
                self.favorites.append({
                    'name': name.strip(),
                    'path': current_path
                })
                self._save_favorites()
                
                success_msg = CustomMessageBox(self)
                success_msg.set_title("添加成功")
                success_msg.set_text(f"已添加 '{name.strip()}' 到收藏夹")
                success_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                success_msg.buttonClicked.connect(success_msg.close)
                success_msg.exec()
    
    def _on_favorite_double_clicked(self, item, dialog):
        """
        双击收藏夹项时跳转到对应路径
        """
        text = item.text()
        # 提取路径（假设格式为 "名称 - 路径"）
        if ' - ' in text:
            path = text.split(' - ', 1)[1]
            if os.path.exists(path):
                self._navigate_to_path(path)
                # 关闭收藏夹对话框
                dialog.accept()
    
    def _show_favorite_context_menu(self, pos, favorites_list):
        """
        显示收藏夹项的右键菜单
        """
        weak_self = weakref.ref(self)
        item = favorites_list.itemAt(pos)
        if not item:
            return
        
        menu = QMenu(self)
        
        # 重命名菜单项
        rename_action = QAction("重命名", self)
        rename_action.triggered.connect(lambda: (s := weak_self()) and s._rename_favorite(item, favorites_list))
        menu.addAction(rename_action)
        
        # 删除菜单项
        delete_action = QAction("删除", self)
        delete_action.triggered.connect(lambda: (s := weak_self()) and s._delete_favorite(item, favorites_list))
        menu.addAction(delete_action)
        
        # 显示菜单
        menu.exec_(favorites_list.mapToGlobal(pos))
    
    def _rename_favorite(self, item, favorites_list):
        """
        重命名收藏夹项
        """
        text = item.text()
        if ' - ' in text:
            old_name, path = text.split(' - ', 1)
            
            # 获取旧收藏夹项
            for i, favorite in enumerate(self.favorites):
                if favorite['path'] == path and favorite['name'] == old_name:
                    # 使用CustomMessageBox的输入模式获取新名称
                    from freeassetfilter.widgets.D_widgets import CustomMessageBox
                    input_dialog = CustomMessageBox(self)
                    input_dialog.set_title("重命名")
                    input_dialog.set_text("请输入新名称:")
                    input_dialog.set_input(text=old_name)
                    input_dialog.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])
                    
                    # 记录结果
                    result = None
                    def on_button_clicked(button_index):
                        nonlocal result
                        result = button_index
                        input_dialog.close()
                    
                    input_dialog.buttonClicked.connect(on_button_clicked)
                    input_dialog.exec()
                    
                    if result == 0:  # 0表示确定按钮
                        new_name = input_dialog.get_input()
                        if new_name:
                            self.favorites[i]['name'] = new_name
                            self._save_favorites()
                            # 更新列表
                            item.setText(new_name + ' - ' + path)
                    break
    
    def _delete_favorite(self, item, favorites_list):
        """
        删除收藏夹项
        """
        text = item.text()
        if ' - ' in text:
            name, path = text.split(' - ', 1)
            
            # 确认删除
            from freeassetfilter.widgets.D_widgets import CustomMessageBox
            confirm_msg = CustomMessageBox(self)
            confirm_msg.set_title("确认删除")
            confirm_msg.set_text(f"确定要删除收藏夹项 '{name}' 吗?")
            confirm_msg.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])
            
            # 记录确认结果
            is_confirmed = False
            
            def on_delete_clicked(button_index):
                nonlocal is_confirmed
                is_confirmed = (button_index == 0)  # 0表示确定按钮
                confirm_msg.close()
            
            confirm_msg.buttonClicked.connect(on_delete_clicked)
            confirm_msg.exec()
            
            if is_confirmed:
                # 从收藏夹列表中删除
                self.favorites = [f for f in self.favorites if not (f['path'] == path and f['name'] == name)]
                self._save_favorites()
                # 更新列表
                favorites_list.takeItem(favorites_list.row(item))
    
    def _add_current_path_to_favorites(self, dialog, favorites_list):
        """
        添加当前路径到收藏夹
        """
        # 获取当前路径
        current_path = self.current_path
        
        # 生成默认名称（使用目录名）
        default_name = os.path.basename(current_path)
        if not default_name:
            default_name = current_path
        
        # 检查是否已存在
        for favorite in self.favorites:
            if favorite['path'] == current_path:
                from freeassetfilter.widgets.D_widgets import CustomMessageBox
                info_msg = CustomMessageBox(self)
                info_msg.set_title("提示")
                info_msg.set_text("该路径已在收藏夹中")
                info_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                info_msg.buttonClicked.connect(info_msg.close)
                info_msg.exec()
                return
        
        # 使用CustomMessageBox的输入模式获取收藏夹名称
        from freeassetfilter.widgets.D_widgets import CustomMessageBox
        input_dialog = CustomMessageBox(self)
        input_dialog.set_title("添加到收藏夹")
        input_dialog.set_text("请输入收藏名称:")
        input_dialog.set_input(text=default_name)
        input_dialog.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])
        
        # 记录结果
        result = None
        def on_button_clicked(button_index):
            nonlocal result
            result = button_index
            input_dialog.close()
        
        input_dialog.buttonClicked.connect(on_button_clicked)
        input_dialog.exec()
        
        if result == 0:  # 0表示确定按钮
            name = input_dialog.get_input()
            if name:
                # 添加到收藏夹
                self.favorites.append({
                    'name': name,
                    'path': current_path,
                    'added_time': datetime.now().isoformat()
                })
                self._save_favorites()
                
                # 更新列表
                favorites_list.addItem(name + ' - ' + current_path)
    
    def _is_valid_selector_path(self, path):
        if path == "All":
            return True
        if not path:
            return False
        try:
            return os.path.exists(path)
        except (OSError, PermissionError, TypeError, ValueError):
            return False

    def _get_recovery_source_for_navigation(self):
        current_path = getattr(self, "current_path", "All")
        if self._is_valid_selector_path(current_path):
            return current_path

        last_accessible_path = getattr(self, "_last_accessible_path", "All")
        if self._is_valid_selector_path(last_accessible_path):
            return last_accessible_path

        return "All"

    def _remember_navigation_source(self, target_path):
        if self._same_selector_path(getattr(self, "current_path", None), target_path):
            return

        recovery_path = self._get_recovery_source_for_navigation()
        self._navigation_recovery_path = recovery_path
        self._last_accessible_path = recovery_path
        self.save_current_path(path=recovery_path)

    def _navigate_to_path(self, target_path, callback=None, scroll_to_top=True, update_path_edit=True):
        self._begin_files_path_transition(target_path)
        self._remember_navigation_source(target_path)
        self.current_path = target_path

        if update_path_edit and hasattr(self, "path_edit") and self.path_edit:
            self.path_edit.setText(target_path)

        self.refresh_files(callback=callback, scroll_to_top=scroll_to_top)
    
    def _is_drive_available(self, drive_path: str) -> bool:
        """
        检测盘符是否可用（可以正常访问）
        使用缓存避免重复阻塞主线程，缓存过期后在后台线程刷新。

        Args:
            drive_path: 盘符路径，如 "C:\\" 或 "D:"

        Returns:
            bool: 如果盘符可用返回True，否则返回False
        """
        # 确保路径格式统一用于缓存键
        norm_path = drive_path.rstrip('\\/') + '\\'

        import time
        now = time.time()

        # 检查缓存
        cached = self._drive_availability_cache.get(norm_path)
        if cached is not None:
            available, timestamp = cached
            if now - timestamp < self._drive_availability_cache_ttl:
                return available

        # 缓存过期或不存在 — 在后台刷新可用性
        self._schedule_drive_availability_check(norm_path)

        # 返回乐观值（True）或最近一次的缓存值
        if cached is not None:
            return cached[0]
        return True

    def _schedule_drive_availability_check(self, drive_path: str) -> None:
        """在 QThreadPool 后台检查盘符可用性并更新缓存。"""
        # 避免对同一盘符发起重复的后台检查
        if not hasattr(self, '_pending_drive_checks'):
            self._pending_drive_checks: set[str] = set()

        if drive_path in self._pending_drive_checks:
            return
        self._pending_drive_checks.add(drive_path)

        weak_self = weakref.ref(self)
        signals = _DriveAvailabilitySignals()
        signals.finished.connect(lambda path, available: (s := weak_self()) and s._on_drive_availability_result(path, available))

        runnable = _DriveAvailabilityCheckRunnable(drive_path, signals)
        QThreadPool.globalInstance().start(runnable)

    def _on_drive_availability_result(self, drive_path: str, available: bool) -> None:
        """后台检查完成回调 — 更新缓存并发出信号。"""
        import time
        old_value = self._drive_availability_cache.get(drive_path)
        self._drive_availability_cache[drive_path] = (available, time.time())

        if hasattr(self, '_pending_drive_checks'):
            self._pending_drive_checks.discard(drive_path)

        # 仅在值发生变化时发出信号
        if old_value is None or old_value[0] != available:
            debug(f"盘符 {drive_path} 可用性变更为: {available}")
            self.drive_availability_changed.emit(drive_path, available)
    
    def _update_drive_list(self):
        """
        动态获取当前系统存在的盘符列表和网络位置并更新到下拉框
        """
        # 尝试使用 DriveService 同步获取盘符（快速路径）
        try:
            all_drives = self._drive_service.list_drives()
            if all_drives:
                self._apply_drive_list(["All"] + all_drives)
        except Exception:
            pass

        # 异步加载（完整路径，包括网络位置）
        if self._drive_list_thread and self._drive_list_thread.isRunning():
            return

        self._drive_list_thread = DriveListLoaderThread(self)
        self._drive_list_thread.loaded.connect(self._on_drive_list_loaded)
        self._drive_list_thread.finished.connect(self._on_drive_list_thread_finished)
        self._drive_list_thread.start()

    def _build_drive_items(self, local_drives, network_locations):
        all_drives = ["All"] + list(local_drives)
        if network_locations:
            all_drives.append("--- 网络位置 ---")
            all_drives.extend(network_locations)
        return all_drives

    def _get_current_drive_item(self, all_drives):
        if self.current_path == "All":
            return "All"

        if sys.platform == 'win32':
            current_drive = os.path.splitdrive(self.current_path)[0]
            if not current_drive and self.current_path.startswith('\\'):
                for drive in all_drives:
                    if drive != "--- 网络位置 ---" and self.current_path.startswith(drive):
                        return drive
            return current_drive or "All"

        return '/'

    def _apply_drive_list(self, all_drives, default_item=None):
        if not all_drives:
            return

        current_drive = default_item or self._get_current_drive_item(all_drives)
        self.drive_combo.set_items(all_drives, default_item=current_drive)

        visible_drive_count = max(1, len(all_drives))
        self.drive_combo.set_max_visible_items(visible_drive_count)

        estimated_row_height = self.drive_combo.list_widget.list_widget.sizeHintForRow(0)
        estimated_row_height = max(int(19 * self.dpi_scale), estimated_row_height)
        full_menu_height = visible_drive_count * estimated_row_height + int(6 * self.dpi_scale)
        self.drive_combo.set_max_height(full_menu_height)

    def _on_drive_list_loaded(self, local_drives, network_locations):
        self._cached_local_drives = local_drives
        self._cached_network_locations = network_locations
        self._apply_drive_list(self._build_drive_items(local_drives, network_locations))

    def _on_drive_list_thread_finished(self):
        self._drive_list_thread = None
    
    def _on_drive_changed(self, drive):
        """
        当盘符选择改变时的处理
        
        Args:
            drive (str): 选中的盘符文本
        """
        drive = drive.strip()
        
        # 跳过分隔符选项
        if drive == "--- 网络位置 ---":
            return
        
        # 处理"All"选项
        if drive == "All":
            # 设置一个特殊的路径标识，表示当前处于"All"视图
            self._navigate_to_path("All")
            return
        
        if sys.platform == 'win32':
            if drive.startswith('\\'):
                drive_path = drive
            else:
                drive_path = drive + '\\'
        else:
            drive_path = drive

        if os.path.isabs(drive_path):
            self._navigate_to_path(drive_path)
    
    def go_forward(self):
        """
        前进到导航历史中的下一个路径
        """
        if self.history_index < len(self.nav_history) - 1:
            self.history_index += 1
            self._navigate_to_path(self.nav_history[self.history_index])
            # 更新按钮状态
            self.back_btn.setEnabled(self.history_index > 0)
            self.forward_btn.setEnabled(self.history_index < len(self.nav_history) - 1)
    
    def _update_history(self):
        """
        更新导航历史记录
        """
        # 确保当前路径不在历史记录的最后位置，或者与最后位置的路径不同
        if not self.nav_history:
            # 初始化历史记录
            self.nav_history.append(self.current_path)
            self.history_index = 0
        elif self.current_path != self.nav_history[self.history_index]:
            # 如果当前不是在历史记录的最后位置，删除后面的历史记录
            if self.history_index < len(self.nav_history) - 1:
                self.nav_history = self.nav_history[:self.history_index + 1]
            
            # 添加新路径到历史记录
            self.nav_history.append(self.current_path)
            self.history_index = len(self.nav_history) - 1
        
        # 更新按钮状态
        self.back_btn.setEnabled(self.history_index > 0)
        self.forward_btn.setEnabled(self.history_index < len(self.nav_history) - 1)
    
    def go_to_path(self):
        """
        跳转到指定路径
        """
        path = self.path_edit.text().strip()
        if not path or path.lower() == "all":
            self._navigate_to_path("All")
            return

        normalized_path = os.path.abspath(os.path.normpath(path)) if not path.startswith('\\') else os.path.normpath(path)
        if os.path.isabs(normalized_path):
            self._navigate_to_path(normalized_path)
        else:
            from freeassetfilter.widgets.D_widgets import CustomMessageBox
            warning_msg = CustomMessageBox(self)
            warning_msg.set_title("警告")
            warning_msg.set_text("无效的路径")
            warning_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            warning_msg.buttonClicked.connect(warning_msg.close)
            warning_msg.exec()
    
    def _has_active_filter(self):
        pattern = str(getattr(self, "filter_pattern", "")).strip()
        return bool(pattern and pattern != "*")

    def _update_filter_button_style(self):
        """
        根据筛选条件状态更新筛选按钮的样式
        - 当筛选条件非空时，使用强调样式（primary）
        - 当筛选条件为空时，使用普通样式（normal）
        """
        if not hasattr(self, "filter_btn"):
            return

        new_button_type = "primary" if self._has_active_filter() else "normal"
        current_button_type = getattr(self.filter_btn, "button_type", None)
        if current_button_type == new_button_type:
            return

        if hasattr(self.filter_btn, "set_button_type"):
            self.filter_btn.set_button_type(new_button_type)
        else:
            self.filter_btn.button_type = new_button_type
            if hasattr(self.filter_btn, "update_theme"):
                self.filter_btn.update_theme()
        self.filter_btn.update()

    def apply_filter(self):
        """
        应用文件筛选
        """
        from freeassetfilter.widgets.D_widgets import CustomMessageBox
        
        # 创建自定义提示窗口
        filter_dialog = CustomMessageBox(self)
        filter_dialog.set_title("文件筛选")
        filter_dialog.set_text("请输入正则表达式筛选条件，留空表示显示所有文件")
        
        # 设置输入框，使用当前筛选条件作为默认值
        current_pattern = self.filter_pattern if self.filter_pattern != "*" else ""
        filter_dialog.set_input(text=current_pattern, placeholder="正则表达式筛选条件")
        
        # 设置确认、移除筛选和取消按钮
        filter_dialog.set_buttons(["确认", "移除筛选", "取消"], Qt.Horizontal, ["primary", "secondary", "normal"])
        
        # 记录结果
        result = None
        
        def on_button_clicked(button_index):
            nonlocal result
            result = button_index
            filter_dialog.close()
        
        filter_dialog.buttonClicked.connect(on_button_clicked)
        filter_dialog.exec()
        
        if result == 0:  # 0表示确认按钮
            filter_pattern = filter_dialog.get_input().strip()
            self.filter_pattern = filter_pattern if filter_pattern else "*"
            # 更新筛选按钮样式
            self._update_filter_button_style()
            self.refresh_files()
        elif result == 1:  # 1表示移除筛选按钮
            # 移除筛选条件
            self.filter_pattern = "*"
            # 更新筛选按钮样式
            self._update_filter_button_style()
            self.refresh_files()
    
    def change_sort(self, sort_text):
        """
        改变排序方式
        """
        sort_mapping = {
            "名称升序": ("name", "asc"),
            "名称降序": ("name", "desc"),
            "大小升序": ("size", "asc"),
            "大小降序": ("size", "desc"),
            "修改时间升序": ("modified", "asc"),
            "修改时间降序": ("modified", "desc"),
            "创建时间升序": ("created", "asc"),
            "创建时间降序": ("created", "desc")
        }
        
        self.sort_by, self.sort_order = sort_mapping.get(sort_text, ("name", "asc"))
        self.refresh_files()
    
    def _on_sort_item_clicked(self, item_data):
        """
        处理排序选项点击事件
        
        Args:
            item_data: 点击的排序选项数据，格式为 (sort_by, sort_order)
        """
        if isinstance(item_data, tuple) and len(item_data) == 2:
            self.sort_by, self.sort_order = item_data
            self.refresh_files()
    
    def change_view_mode(self, index):
        """
        改变视图模式
        """
        view_options = ["card", "list"]
        self.view_mode = view_options[index]
        self._apply_view_mode()
        self.refresh_files()

    def _toggle_view_mode(self):
        """切换视图模式"""
        index = 1 if self.view_mode == "card" else 0
        self.change_view_mode(index)

    def _set_view_mode_button_text(self):
        """更新视图模式按钮的图标"""
        if not hasattr(self, "view_mode_btn"):
            return
        icon_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons')
        if self.view_mode == "list":
            icon_name = self.view_mode_btn._primary_icon_name or "表格.svg"
            self.view_mode_btn._tooltip_text = "网格视图"
        else:
            icon_name = self.view_mode_btn._alt_icon_name or "list_bullet.svg"
            self.view_mode_btn._tooltip_text = "列表视图"
        icon_path = os.path.join(icon_dir, icon_name)
        self.view_mode_btn._icon_path = icon_path
        self.view_mode_btn._icon_render_signature = None
        self.view_mode_btn._render_icon(force=True)
        self.view_mode_btn.update()

    def _apply_view_mode(self):
        """应用当前视图模式的 delegate 和 QListView 设置（先确保已加载）"""
        self._load_view_mode()
        if not self.files_scroll_area:
            return
        if self.view_mode == "list":
            self.files_scroll_area.setItemDelegate(self.list_delegate)
            self.files_scroll_area.setWrapping(False)
            self.files_scroll_area.setFlow(QListView.TopToBottom)
        else:
            self.files_scroll_area.setItemDelegate(self.card_delegate)
            self.files_scroll_area.setWrapping(True)
            self.files_scroll_area.setFlow(QListView.LeftToRight)
        self.files_scroll_area.update()
        self._set_view_mode_button_text()

    def _update_list_layout(self):
        """列表模式下卡片居中显示，左右各留 10px 间距，滚动条覆盖在卡片之上"""
        list_view = self.files_scroll_area
        if not list_view or not self.file_model:
            return
        viewport_width = list_view.viewport().width()
        if viewport_width <= 0:
            return
        edge_padding = int(10 * self.dpi_scale)
        card_width = max(200, viewport_width - 2 * edge_padding)
        border_w = max(1, int(1 * self.dpi_scale))
        icon_lm = int(4 * self.dpi_scale)
        icon_sz = int(28 * self.dpi_scale)
        card_height = int(2 * border_w + 2 * icon_lm + icon_sz)
        gap = int(4 * self.dpi_scale)
        list_view.setGridSize(QSize(viewport_width, card_height + gap))
        self.file_model.set_grid_offset_x(0)
        self.file_model.set_card_width(card_width, card_height, 1)
    
    def _update_drive_selector(self):
        """
        更新盘符选择器的选中项，根据当前路径自动选择对应的盘符
        """
        # 检查当前是否处于"All"视图
        if self.current_path == "All":
            # 选中"All"选项
            self.drive_combo.set_current_item("All")
        elif sys.platform == 'win32':
            # Windows系统：提取当前路径的盘符，如 "C:\path\to\dir" -> "C:"
            current_drive = os.path.splitdrive(self.current_path)[0]
            # 设置当前盘符为选中项
            self.drive_combo.set_current_item(current_drive)
        else:
            # Linux/macOS系统：根目录
            current_drive = '/'
            # 设置当前盘符为选中项
            self.drive_combo.set_current_item(current_drive)
    
    def refresh_files(self, callback=None, scroll_to_top=True):
        """
        刷新文件列表
        
        Args:
            callback (callable, optional): 文件卡片生成完成后的回调函数
            scroll_to_top (bool, optional): 是否滚动到顶端，默认为True
        """
        try:
            self._refresh_request_id += 1
            request_id = self._refresh_request_id
            self._is_loading = True
            self.path_edit.setText(self.current_path)
            self._update_drive_selector()
            self.file_model.set_files([])

            if self._file_loader_thread and self._file_loader_thread.isRunning():
                self._file_loader_thread.loaded.disconnect()
                self._file_loader_thread.failed.disconnect()
                self._file_loader_thread.quit()
                self._file_loader_thread.wait(100)

            self._file_loader_thread = FileListLoaderThread(self.current_path, self)
            weak_self = weakref.ref(self)
            self._file_loader_thread.loaded.connect(lambda loaded_path, files: (s := weak_self()) and s._on_files_loaded(request_id, loaded_path, files, callback, scroll_to_top))
            self._file_loader_thread.failed.connect(lambda failed_path, message: (s := weak_self()) and s._on_files_load_failed(request_id, failed_path, message))
            self._file_loader_thread.finished.connect(self._on_file_loader_finished)
            self._file_loader_thread.start()
        except Exception as e:
            self._is_loading = False
            self._cancel_files_path_transition()
            error(f"刷新文件列表失败: {e}")

    def _on_files_loaded(self, request_id, loaded_path, files, callback, scroll_to_top):
        if request_id != self._refresh_request_id or loaded_path != self.current_path:
            return

        try:
            self._is_loading = False
            self._last_accessible_path = loaded_path
            self.save_current_path()
            files = self._sort_files(files)
            files = self._filter_files(files)
            self.file_model.set_files(files)

            # 目录已变更，清除动画状态字典以防 _animation_states 无限增长
            self.card_delegate.clear_caches()
            self.list_delegate.clear_caches()

            self._update_file_selection_state()
            self._check_and_apply_preview_state()

            if scroll_to_top and hasattr(self, 'files_scroll_area') and self.files_scroll_area:
                self.files_scroll_area.scrollToTop()

            self._update_grid_size()
            self.files_scroll_area.update()

            if callback:
                callback()
            self._finish_files_path_transition()
        except Exception as e:
            self._cancel_files_path_transition()
            error(f"应用文件列表失败: {e}")

    def _on_files_load_failed(self, request_id, failed_path, message):
        if request_id != self._refresh_request_id or failed_path != self.current_path:
            return

        self._is_loading = False
        self._cancel_files_path_transition()
        error(f"读取目录失败: {message}")

        allow_elevated_restart = sys.platform == 'win32' and self._looks_like_permission_denied(message)
        from freeassetfilter.widgets.D_widgets import CustomMessageBox
        error_msg = CustomMessageBox(self)
        error_msg.set_title("目录无法访问")
        if allow_elevated_restart:
            error_msg.set_text(
                f"读取目录失败: {message}\n\n"
                "这通常是 Windows 权限或 UAC 限制造成的。当前进程不能原地提升权限，"
                "可以选择以管理员身份重新启动程序后再尝试访问。"
            )
            error_msg.set_buttons(["以管理员身份重启", "确定"], Qt.Horizontal, ["warning", "primary"])
        else:
            error_msg.set_text(f"读取目录失败: {message}")
            error_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])

        clicked_button = None

        def on_error_button_clicked(button_index):
            nonlocal clicked_button
            clicked_button = button_index
            error_msg.close()

        error_msg.buttonClicked.connect(on_error_button_clicked)
        error_msg.exec()

        if allow_elevated_restart and clicked_button == 0:
            launched, launch_message = self._restart_application_as_admin()
            if launched:
                return
            self._show_elevated_restart_failed_dialog(launch_message)

        self._recover_after_directory_load_failure(failed_path)

    def _on_file_loader_finished(self):
        self._file_loader_thread = None

    def _looks_like_permission_denied(self, message):
        text = str(message).lower()
        permission_markers = (
            "permission",
            "access is denied",
            "拒绝访问",
            "权限",
            "winerror 5",
            "errno 13",
        )
        return any(marker in text for marker in permission_markers)

    def _same_selector_path(self, left, right):
        if left == right:
            return True
        if not left or not right or left == "All" or right == "All":
            return False
        try:
            return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))
        except (TypeError, ValueError):
            return False

    def _is_descendant_selector_path(self, candidate_path, base_path):
        if not candidate_path or not base_path or candidate_path == "All" or base_path == "All":
            return False

        try:
            candidate = os.path.normcase(os.path.normpath(candidate_path))
            base = os.path.normcase(os.path.normpath(base_path))
            if candidate == base:
                return False
            return os.path.commonpath([candidate, base]) == base
        except (OSError, TypeError, ValueError):
            return False

    def _infer_navigation_direction(self, source_path, target_path):
        if self._same_selector_path(source_path, target_path):
            return 0
        if source_path == "All" and target_path != "All":
            return 1
        if target_path == "All":
            return -1
        if self._is_descendant_selector_path(target_path, source_path):
            return 1
        if self._is_descendant_selector_path(source_path, target_path):
            return -1
        return 1

    def _begin_files_path_transition(self, target_path):
        self._pending_path_transition_direction = 0

        list_view = getattr(self, "files_scroll_area", None)
        if not list_view or not hasattr(list_view, "begin_path_transition"):
            return

        direction = self._infer_navigation_direction(getattr(self, "current_path", "All"), target_path)
        if direction == 0:
            return

        try:
            if list_view.begin_path_transition(direction):
                self._pending_path_transition_direction = direction
                self._pending_path_transition_token += 1
        except Exception as transition_error:
            debug(f"启动文件选择器路径切换动画失败: {transition_error}")

    def _finish_files_path_transition(self):
        direction = getattr(self, "_pending_path_transition_direction", 0)
        if direction == 0:
            return

        self._pending_path_transition_direction = 0
        list_view = getattr(self, "files_scroll_area", None)
        if not list_view or not hasattr(list_view, "finish_path_transition"):
            return

        try:
            token = getattr(self, "_pending_path_transition_token", 0)
            list_view.doItemsLayout()
            list_view.viewport().update()
            weak_self = weakref.ref(self)
            QTimer.singleShot(0, lambda: (s := weak_self()) and s._finish_files_path_transition_deferred(token, direction))
        except Exception as transition_error:
            debug(f"完成文件选择器路径切换动画失败: {transition_error}")

    def _finish_files_path_transition_deferred(self, token, direction):
        if direction == 0:
            return

        if token != getattr(self, "_pending_path_transition_token", 0):
            return

        list_view = getattr(self, "files_scroll_area", None)
        if not list_view or not hasattr(list_view, "finish_path_transition"):
            return

        try:
            list_view.doItemsLayout()
            list_view.finish_path_transition(direction)
        except Exception as transition_error:
            debug(f"延迟完成文件选择器路径切换动画失败: {transition_error}")

    def _cancel_files_path_transition(self):
        self._pending_path_transition_direction = 0
        self._pending_path_transition_token += 1
        list_view = getattr(self, "files_scroll_area", None)
        if list_view and hasattr(list_view, "cancel_path_transition"):
            try:
                list_view.cancel_path_transition()
            except Exception as transition_error:
                debug(f"取消文件选择器路径切换动画失败: {transition_error}")

    def _get_directory_load_failure_recovery_path(self, failed_path):
        recovery_path = (
            getattr(self, "_navigation_recovery_path", None)
            or getattr(self, "_last_accessible_path", None)
            or "All"
        )
        if self._same_selector_path(recovery_path, failed_path):
            return "All"
        return recovery_path

    def _recover_after_directory_load_failure(self, failed_path):
        recovery_path = self._get_directory_load_failure_recovery_path(failed_path)
        self._last_accessible_path = recovery_path
        self._navigation_recovery_path = recovery_path
        self.current_path = recovery_path

        if hasattr(self, "path_edit") and self.path_edit:
            self.path_edit.setText(recovery_path)

        self.save_current_path()
        self.refresh_files()

    def _restart_application_as_admin(self):
        if sys.platform != 'win32':
            return False, "当前平台不支持 Windows UAC 提权重启"

        try:
            import ctypes
            import subprocess

            executable = sys.executable
            if getattr(sys, "frozen", False):
                relaunch_args = sys.argv[1:]
            else:
                relaunch_args = sys.argv

            parameters = subprocess.list2cmdline(relaunch_args)
            result = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                executable,
                parameters,
                os.getcwd(),
                1,
            )
            if result <= 32:
                return False, f"系统拒绝启动管理员进程，错误码: {result}"

            app = QApplication.instance()
            if app:
                app.quit()
            return True, ""
        except Exception as e:
            return False, str(e)

    def _show_elevated_restart_failed_dialog(self, message):
        from freeassetfilter.widgets.D_widgets import CustomMessageBox
        restart_msg = CustomMessageBox(self)
        restart_msg.set_title("管理员重启失败")
        restart_msg.set_text(f"无法以管理员身份重新启动程序：\n{message}")
        restart_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
        restart_msg.buttonClicked.connect(restart_msg.close)
        restart_msg.exec()

    
    def _get_files(self):
        """
        获取当前目录下的文件列表
        优化版本：使用 os.scandir() 替代 os.listdir() + QFileInfo，减少磁盘 I/O
        """
        files = []
        
        # 处理"All"视图
        if self.current_path == "All":
            if sys.platform == 'win32':
                # Windows系统：使用 GetLogicalDrives 获取可用盘符，更高效
                try:
                    import ctypes
                    kernel32 = ctypes.windll.kernel32
                    drives_bitmask = kernel32.GetLogicalDrives()
                    for drive in range(26):  # A-Z
                        if drives_bitmask & (1 << drive):
                            drive_name = chr(65 + drive) + ':'
                            drive_path = drive_name + '\\'
                            
                            # 首先检测盘符是否可用
                            if not self._is_drive_available(drive_name):
                                debug(f"跳过不可用的盘符: {drive_name}")
                                continue
                            
                            # 使用 os.scandir 获取驱动器信息，避免 QFileInfo 阻塞
                            try:
                                stat = os.stat(drive_path)
                                modified = QDateTime.fromSecsSinceEpoch(int(stat.st_mtime)).toString(Qt.ISODate)
                                created = QDateTime.fromSecsSinceEpoch(int(stat.st_ctime)).toString(Qt.ISODate)
                            except OSError as e:
                                debug(f"获取驱动器 {drive_path} 信息失败: {e}")
                                modified = ""
                                created = ""

                            file_dict = {
                                "name": drive_name,
                                "path": drive_path,
                                "is_dir": True,
                                "size": 0,
                                "modified": modified,
                                "created": created,
                                "suffix": ""
                            }
                            files.append(file_dict)
                except Exception as e:
                    error(f"获取驱动器列表失败: {e}")
            else:
                # Linux/macOS系统：显示根目录
                root_path = "/"
                try:
                    stat = os.stat(root_path)
                    modified = QDateTime.fromSecsSinceEpoch(int(stat.st_mtime)).toString(Qt.ISODate)
                    created = QDateTime.fromSecsSinceEpoch(int(stat.st_ctime)).toString(Qt.ISODate)
                except OSError as e:
                    debug(f"获取根目录 {root_path} 信息失败: {e}")
                    modified = ""
                    created = ""

                file_dict = {
                    "name": root_path,
                    "path": root_path,
                    "is_dir": True,
                    "size": 0,
                    "modified": modified,
                    "created": created,
                    "suffix": ""
                }
                files.append(file_dict)
        else:
            # 使用 FileService 扫描目录
            try:
                if os.path.islink(self.current_path):
                    raise OSError("拒绝扫描符号链接目录")

                files = self._file_service.scan_directory(self.current_path)

            except Exception as e:
                error(f"读取目录失败: {e}")
                from freeassetfilter.widgets.D_widgets import CustomMessageBox
                error_msg = CustomMessageBox(self)
                error_msg.set_title("错误")
                error_msg.set_text(f"读取目录失败: {e}")
                error_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                error_msg.buttonClicked.connect(error_msg.close)
                error_msg.exec()
        
        return files
    
    def _sort_files(self, files):
        """
        对文件列表进行排序
        """
        return self._file_service.sort_files(
            files, key=self.sort_by, reverse=(self.sort_order == "desc")
        )
    
    def _filter_files(self, files):
        """
        应用筛选器
        支持通配符 * 和 ?，对无效的正则表达式进行错误处理
        """
        if not self.filter_pattern or self.filter_pattern == "*":
            return files
        return self._file_service.filter_files(files, pattern=self.filter_pattern)
    
    def _calculate_card_base_width(self):
        """
        计算卡片的基础宽度（基于日期文本宽度）
        
        逻辑与 FileBlockCard._calculate_optimal_width 保持一致：
        1. 计算日期文本（最后一行）的宽度
        2. 加上1个英文字符的宽度作为额外空间
        3. 加上水平边距和边框
        4. 与原固定宽度（50 * DPI缩放）比较，确保不会过小
        
        Returns:
            int: 计算后的卡片基础宽度
        """
        base_min_width = int(50 * self.dpi_scale)
        
        small_font = QFont(self.global_font)
        small_font.setPointSize(int(self.global_font.pointSize() * 0.85))
        small_font_metrics = QFontMetrics(small_font)
        
        date_text = "2024-12-31"
        date_text_width = small_font_metrics.horizontalAdvance(date_text)
        
        char_width = small_font_metrics.horizontalAdvance("W")
        
        horizontal_margins = int(4 * self.dpi_scale) * 2
        border_width = int(1 * self.dpi_scale) * 2
        
        required_width = date_text_width + char_width + horizontal_margins + border_width
        
        return max(required_width, base_min_width)

    def _calculate_max_columns(self):
        """
        根据当前视口宽度精确计算每行卡片数量
        """
        list_view = getattr(self, "files_scroll_area", None)
        if not list_view:
            return 1

        viewport_width = list_view.viewport().width()
        if viewport_width <= 0:
            return 1

        card_width = self._calculate_card_base_width()
        spacing = self._card_spacing
        cell_width = card_width + spacing
        leading_edge = spacing // 2
        # QListView 在首个卡片前会保留约半个 spacing 的起始偏移。
        # 列数阈值必须按这条真实布局规则计算，否则会出现列数先切换，
        # 又因卡片宽度重算被挤回原列数的抖动。
        available_width = max(0, viewport_width - leading_edge)
        return max(1, available_width // max(1, cell_width))
    
    def _calculate_card_width(self):
        """
        计算每个卡片可用的动态宽度
        """
        list_view = getattr(self, "files_scroll_area", None)
        if not list_view:
            return self._calculate_card_base_width()

        viewport_width = list_view.viewport().width()
        max_cols = self._calculate_max_columns()

        card_base_width = self._calculate_card_base_width()
        spacing = self._card_spacing
        leading_edge = spacing // 2
        available_width = max(0, viewport_width - leading_edge)

        if max_cols <= 0:
            return card_base_width

        cell_base_width = card_base_width + spacing
        cell_width = max(cell_base_width, available_width // max_cols)
        return max(card_base_width, cell_width - spacing)
    
    def _schedule_grid_size_update(self, *_args):
        if hasattr(self, 'files_scroll_area') and self.files_scroll_area:
            self._update_grid_size()
            self.files_scroll_area.update()

    def _on_resize_timeout(self):
        if hasattr(self, 'files_scroll_area') and self.files_scroll_area:
            self._update_grid_size()
            self.files_scroll_area.update()
    
    def _update_grid_size(self):
        """
        更新 QListView 的网格尺寸，实现卡片宽度和列数的自适应
        
        根据视口宽度动态计算：
        1. 计算当前视口能容纳的最大列数
        2. 计算每个卡片的实际宽度
        3. 更新 gridSize 和 Model 的卡片宽度
        """
        if getattr(self, 'view_mode', 'card') == 'list':
            self._update_list_layout()
            return
        list_view = getattr(self, 'files_scroll_area', None)
        if not list_view or not self.file_model:
            return

        viewport_width = list_view.viewport().width()
        if viewport_width <= 0:
            return

        # 卡片网格使用完整视口宽度，滚动条为覆盖层，不占用布局空间
        edge_padding = int(10 * self.dpi_scale)
        card_base_width = self._calculate_card_base_width()
        spacing = self._card_spacing
        margin = edge_padding
        # 列数阈值与卡片宽度都必须按 QListView 的真实起始偏移计算，
        # 这样 resize 时不会出现"先换列，再因宽度变化切回去"的反馈抖动。
        available_width = max(0, viewport_width - 2 * margin)

        cell_base_width = card_base_width + spacing
        max_cols = max(1, available_width // max(1, cell_base_width))

        # 先确定列数，再在该列数内部平滑放大卡片。
        # 这样宽度变化不会反过来重新触发列数回跳。
        cell_width = max(cell_base_width, available_width // max_cols)
        card_width = max(card_base_width, cell_width - spacing)

        # 卡片高度
        card_height = int(75 * self.dpi_scale)

        # gridSize 表示单元格尺寸，包含为卡片矩阵留出的外边距
        # delegate 会在单元格内部居中绘制真实卡片
        list_view.setSpacing(0)
        grid_size = QSize(card_width + spacing, card_height + spacing)
        list_view.setGridSize(grid_size)

        # 计算网格水平居中偏移
        total_grid_width = max_cols * (card_width + spacing) - spacing
        left_margin = max(edge_padding, (viewport_width - total_grid_width) // 2)
        grid_offset_x = left_margin - spacing // 2
        self.file_model.set_grid_offset_x(grid_offset_x)

        # 更新 Model 的卡片宽度，以便 Delegate 绘制时使用
        self.file_model.set_card_width(card_width, card_height, max_cols)

    
    def _update_file_selection_state(self):
        for row in range(self.file_model.rowCount()):
            file_path = self.file_model.index(row, 0).data(self.file_model.FilePathRole)
            if file_path:
                normalized_path = os.path.normpath(file_path)
                is_selected = normalized_path in self._selected_file_paths
                self.file_model.set_selected(normalized_path, is_selected)
    
    def _check_and_apply_preview_state(self):
        if self.previewing_file_path:
            self.file_model.set_previewing(self.previewing_file_path, True)
        else:
            self.file_model.clear_previewing()
    
    def _find_visible_card_by_path(self, file_path):
        normalized_path = os.path.normpath(file_path)
        row = self.file_model.get_row(normalized_path)
        if row < 0:
            return None
        return self.file_model.get_file_info(self.file_model.index(row, 0))
    
    def event(self, event):
        """
        处理鼠标硬件按钮事件
        """
        if event.type() == QEvent.MouseButtonPress:
            if self._is_back_navigation_button(event.button()):
                # 鼠标后退按钮事件 - 返回上级文件夹
                self.go_to_parent()
                return True
        return super().event(event)

    @staticmethod
    def _is_back_navigation_button(button):
        for button_name in ("BackButton", "XButton1", "ExtraButton1"):
            back_button = getattr(Qt, button_name, None)
            if back_button is not None and button == back_button:
                return True
        return False
    
    def _on_card_drag_started(self, file_info):
        """
        处理卡片拖拽开始
        
        Args:
            file_info (dict): 文件信息
        """
    
    def _on_card_drag_ended(self, file_info, drop_target):
        """
        处理卡片拖拽结束
        根据放置目标执行相应操作

        Args:
            file_info (dict): 文件信息
            drop_target (str): 放置目标类型 ('staging_pool', 'previewer', 'none')
        """
        file_path = file_info.get('path', '')
        file_path_norm = os.path.normpath(file_path)
        file_dir_norm = os.path.normpath(os.path.dirname(file_path))

        if drop_target == 'staging_pool':
            # 设置卡片选中状态
            if file_dir_norm not in self.selected_files:
                self.selected_files[file_dir_norm] = set()

            if file_path_norm not in self.selected_files[file_dir_norm]:
                self.selected_files[file_dir_norm].add(file_path_norm)
                self._selected_file_paths.add(file_path_norm)
                # 更新卡片UI状态
                self._update_file_selection_state()
                # 发出选择变化信号，将文件添加到存储池
                self.file_selection_changed.emit(file_info, True)
            else:
                pass

        elif drop_target == 'previewer':
            # 发出文件选中信号，启动预览
            self.file_selected.emit(file_info)
    
    def _handle_card_clicked_signal(self, file_info):
        """处理卡片左键点击，始终基于信号携带的当前 file_info。"""
        if file_info.get("is_dir"):
            self._on_folder_clicked(file_info["path"])
        else:
            file_path = os.path.normpath(file_info.get("path", ""))
            if self.previewing_file_path and file_path == self.previewing_file_path:
                self.preview_cancel_requested.emit()
            else:
                self.file_selected.emit(file_info)
    
    def _on_folder_clicked(self, file_path):
        """处理文件夹左键点击 - 直接进入目录"""
        self.path_edit.setText(file_path)
        self.go_to_path()
    
    def _handle_card_right_clicked_signal(self, file_info):
        """处理卡片右键点击，始终基于信号携带的当前 file_info。"""
        self.file_right_clicked.emit(file_info)
    
    def _handle_card_selection_changed_signal(self, file_info, is_selected):
        """
        处理卡片选中状态变化
        使用信号传入的实时 file_info，避免虚拟化复用后仍使用旧闭包中的 file_path/file_info。
        
        Args:
            file_info (dict): 文件信息
            is_selected (bool): 是否选中
        """
        file_path = file_info.get("path", "")
        file_path_norm = os.path.normpath(file_path)
        file_dir_norm = os.path.normpath(os.path.dirname(file_path))
        
        if is_selected:
            if file_dir_norm not in self.selected_files:
                self.selected_files[file_dir_norm] = set()
            if file_path_norm not in self.selected_files[file_dir_norm]:
                self.selected_files[file_dir_norm].add(file_path_norm)
                self._selected_file_paths.add(file_path_norm)
                self.file_selection_changed.emit(file_info, is_selected)
        else:
            if file_dir_norm in self.selected_files and file_path_norm in self.selected_files[file_dir_norm]:
                self.selected_files[file_dir_norm].discard(file_path_norm)
                self._selected_file_paths.discard(file_path_norm)
                self.file_selection_changed.emit(file_info, is_selected)
    
    def _handle_card_double_clicked_signal(self, file_info):
        """处理卡片双击，始终基于信号携带的当前 file_info。"""
        if file_info.get("is_dir"):
            self.path_edit.setText(file_info["path"])
            self.go_to_path()
        else:
            self._open_file_by_path(file_info["path"])
    
    def _set_file_icon(self, file_info):
        """
        设置文件图标或缩略图，返回一个QWidget
        优化版本：对exe/lnk文件使用异步加载，避免阻塞UI
        """
        from PySide6.QtSvgWidgets import QSvgWidget

        if not file_info["is_dir"]:
            suffix = file_info["suffix"].lower()
            if suffix in ["lnk", "exe"]:
                return self._create_async_system_icon_widget(file_info)

        thumbnail_path = self._get_thumbnail_path(file_info["path"])

        suffix = file_info["suffix"].lower() if not file_info["is_dir"] else ""
        is_photo = suffix in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'tiff', 'avif', 'cr2', 'cr3', 'nef', 'arw', 'dng', 'orf', 'psd', 'psb']
        is_video = suffix in ['mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm', 'm4v', 'mpeg', 'mpg', 'mxf']

        use_thumbnail = False
        if (is_photo or is_video) and os.path.exists(thumbnail_path):
            use_thumbnail = True

        if use_thumbnail:
            base_icon_size = int(40 * self.dpi_scale)

            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            label.setFixedSize(base_icon_size, base_icon_size)

            pixmap = QPixmap(thumbnail_path)

            actual_size = int(base_icon_size * self.devicePixelRatio())

            scaled_pixmap = pixmap.scaled(
                actual_size, actual_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            scaled_pixmap.setDevicePixelRatio(self.devicePixelRatio())

            combined_pixmap = QPixmap(base_icon_size, base_icon_size)
            combined_pixmap.fill(Qt.transparent)

            painter = QPainter(combined_pixmap)

            draw_x = (base_icon_size - scaled_pixmap.width() // self.devicePixelRatio()) // 2
            draw_y = (base_icon_size - scaled_pixmap.height() // self.devicePixelRatio()) // 2

            painter.drawPixmap(draw_x, draw_y, scaled_pixmap)

            try:
                scaled_overlay_icon_size = int(24 * self.dpi_scale)
                scaled_margin = int(4 * self.dpi_scale)

                file_type_pixmap = self._get_file_type_pixmap(file_info, icon_size=scaled_overlay_icon_size)

                x = base_icon_size - scaled_overlay_icon_size - scaled_margin
                y = base_icon_size - scaled_overlay_icon_size - scaled_margin

                painter.drawPixmap(x, y, file_type_pixmap)
            except Exception as e:
                warning(f"叠加文件类型图标失败: {e}")
            finally:
                painter.end()

            label.setPixmap(combined_pixmap)
            return label

        icon_path = get_file_icon_path(file_info)

        if icon_path and os.path.exists(icon_path):
            scaled_icon_size = int(40 * self.dpi_scale)

            suffix_text = ""
            if icon_path.endswith("未知底板.svg") or icon_path.endswith("压缩文件.svg"):
                if icon_path.endswith("压缩文件.svg"):
                    suffix_text = "." + file_info["suffix"]
                else:
                    suffix_text = file_info["suffix"].upper()

                if not suffix_text or len(suffix_text) >= 5:
                    suffix_text = "FILE"

            if icon_path.endswith("未知底板.svg") or icon_path.endswith("压缩文件.svg"):
                return SvgRenderer.render_unknown_file_icon(icon_path, suffix_text, scaled_icon_size, 1.0)
            else:
                try:
                    with open(icon_path, 'r', encoding='utf-8') as f:
                        svg_content = f.read()

                    svg_content = SvgRenderer._replace_svg_colors(svg_content)

                    svg_widget = QSvgWidget()
                    svg_widget.load(svg_content.encode('utf-8'))
                    svg_widget.setFixedSize(scaled_icon_size, scaled_icon_size)
                    svg_widget.setStyleSheet('background: transparent; border: none;')
                    return svg_widget
                except Exception as svg_e:
                    warning(f"使用QSvgWidget渲染SVG图标失败: {svg_e}")
                    base_pixmap = SvgRenderer.render_svg_to_pixmap(icon_path, 120, self.dpi_scale)

                    label = QLabel()
                    label.setAlignment(Qt.AlignCenter)
                    label.setFixedSize(scaled_icon_size, scaled_icon_size)
                    label.setPixmap(base_pixmap)

                    return label

    def _create_async_system_icon_widget(self, file_info):
        """
        创建异步加载系统图标的widget（用于exe/lnk文件）
        先显示SVG占位图标，后台异步加载系统图标后替换
        """
        from freeassetfilter.utils.async_icon_loader import AsyncIconLoader
        from freeassetfilter.utils.icon_utils import hicon_to_pixmap, DestroyIcon
        from PySide6.QtGui import QGuiApplication

        base_icon_size = int(40 * self.dpi_scale)
        scaled_icon_size = int(base_icon_size * 0.8)

        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        label.setFixedSize(base_icon_size, base_icon_size)
        label.setObjectName("AsyncSystemIconLabel")

        file_path = file_info["path"]

        icon_path = get_file_icon_path(file_info)
        if icon_path and os.path.exists(icon_path):
            try:
                from PySide6.QtSvgWidgets import QSvgWidget
                svg_widget = SvgRenderer.render_svg_to_exact_pixmap(
                    icon_path,
                    icon_width=scaled_icon_size,
                    icon_height=scaled_icon_size,
                    replace_colors=True,
                    device_pixel_ratio=self.devicePixelRatio(),
                )
                if svg_widget and not svg_widget.isNull():
                    label.setPixmap(svg_widget)
            except Exception:
                pass

        def on_icon_loaded(loaded_path, pixmap):
            if pixmap and not pixmap.isNull():
                try:
                    scaled = pixmap.scaled(
                        base_icon_size * label.devicePixelRatio(),
                        base_icon_size * label.devicePixelRatio(),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                    scaled.setDevicePixelRatio(label.devicePixelRatio())
                    label.setPixmap(scaled)
                    label.update()
                except RuntimeError:
                    pass

        loader = AsyncIconLoader.instance()
        loader.load_icon(file_path, on_icon_loaded, icon_size=scaled_icon_size)

        return label
    
    def _get_file_type_pixmap(self, file_info, icon_size=24):
        """
        获取文件类型图标的QPixmap，复用现有的图标渲染逻辑
        
        Args:
            file_info (dict): 文件信息字典
            icon_size (int): 图标大小，默认24x24
            
        Returns:
            QPixmap: 文件类型图标
        """
        # 定义文件类型映射
        image_formats = ["jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "svg", "avif", "cr2", "cr3", "nef", "arw", "dng", "orf", "psd", "psb"]
        video_formats = ["mp4", "avi", "mov", "mkv", "m4v", "mxf", "wmv", "flv", "webm", "3gp", "mpg", "mpeg", "vob", "m2ts", "ts", "mts"]
        audio_formats = ["mp3", "wav", "flac", "ogg", "wma", "aac", "m4a", "opus"]
        document_formats = ["pdf", "txt", "md", "rst", "doc", "docx", "xls", "xlsx", "ppt", "pptx"]
        font_formats = ["ttf", "otf", "woff", "woff2", "eot", "svg"]
        archive_formats = ["zip", "rar", "7z", "tar", "gz", "bz2", "xz", "lzma", "tar.gz", "tar.bz2", "tar.xz", "tar.lzma", "iso", "cab", "arj", "lzh", "ace", "z"]

        # 确定要使用的SVG图标
        icon_path = get_file_icon_path(file_info)

        # 对于未知文件类型和压缩文件类型，需要传递后缀名信息
        if icon_path and (icon_path.endswith("未知底板.svg") or icon_path.endswith("未知底板 – 1.svg") or icon_path.endswith("压缩文件.svg") or icon_path.endswith("压缩文件 – 1.svg")):
            suffix_text = ""
            if icon_path.endswith("压缩文件.svg") or icon_path.endswith("压缩文件 – 1.svg"):
                suffix_text = "." + file_info["suffix"]
            else:
                suffix_text = file_info["suffix"].upper()
                if len(suffix_text) > 6:
                    suffix_text = "FILE"
            
            widget = SvgRenderer.render_unknown_file_icon(icon_path, suffix_text, icon_size, 1.0)
            pixmap = widget.grab(widget.rect())
            return pixmap

        # 使用SvgRenderer工具渲染SVG图标为QPixmap，传递DPI缩放因子
        return SvgRenderer.render_svg_to_pixmap(icon_path, icon_size, self.dpi_scale)
    
    def _get_thumbnail_path(self, file_path):
        """
        获取文件当前实际可用的缩略图路径。
        优先使用 WebP；若不存在则回退 PNG。
        """
        thumbnail_path = get_existing_thumbnail_path(file_path)
        if thumbnail_path:
            return thumbnail_path

        thumbnail_manager = get_thumbnail_manager(self.dpi_scale)
        return thumbnail_manager.get_thumbnail_path(file_path)
    
    def _format_size(self, size):
        """
        格式化文件大小
        """
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.1f} GB"
    
    def eventFilter(self, obj, event):
        if obj == self.files_scroll_area.viewport() or obj == self.files_scroll_area:
            if event.type() == QEvent.Resize:
                self._on_resize_timeout()
            if event.type() == QEvent.DragEnter or event.type() == QEvent.DragMove:
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    app = QApplication.instance()
                    secondary_color = "#f1f3f5"
                    accent_color = "#1890ff"
                    if hasattr(app, 'settings_manager'):
                        secondary_color = self._settings_manager.get_setting("appearance.colors.secondary_color", "#f1f3f5")
                        accent_color = self._settings_manager.get_setting("appearance.colors.accent_color", "#1890ff")
                    self.setStyleSheet(f"background-color: {secondary_color}; border: 3px dashed {accent_color}; border-radius: {int(8 * self.dpi_scale)}px;")
                    return True
            elif event.type() == QEvent.DragLeave:
                app = QApplication.instance()
                secondary_color = "#f1f3f5"
                if hasattr(app, 'settings_manager'):
                    secondary_color = self._settings_manager.get_setting("appearance.colors.secondary_color", "#f1f3f5")
                self.setStyleSheet(f"background-color: {secondary_color}; border: none;")
                return True
            elif event.type() == QEvent.Drop:
                self.dropEvent(event)
                return True
        elif event.type() == QEvent.Resize:
            target_width = 0
            if hasattr(self, 'files_scroll_area') and self.files_scroll_area:
                target_width = self.files_scroll_area.viewport().width()

            if target_width > 0:
                self.resize_timer.start()

            return False
        
        return super().eventFilter(obj, event)
    
    def _show_context_menu(self, file_info, pos):
        menu = QMenu(self)
        
        open_action = QAction("打开文件", self)
        open_action.triggered.connect(lambda: self._open_file_by_path(file_info["path"]))
        menu.addAction(open_action)
        
        properties_action = QAction("查看属性", self)
        properties_action.triggered.connect(lambda: self._show_properties(file_info))
        menu.addAction(properties_action)
        
        file_path = file_info["path"]
        file_path_norm = os.path.normpath(file_path)
        is_selected = file_path_norm in self._selected_file_paths
        
        if is_selected:
            remove_from_pool_action = QAction("从暂存池移除", self)
            remove_from_pool_action.triggered.connect(lambda: self._remove_from_staging_pool(file_info))
            menu.addAction(remove_from_pool_action)
        
        self.file_right_clicked.emit(file_info)
        
        menu.exec_(self.mapToGlobal(pos))
    
    def _open_file(self, file_info):
        file_path = file_info["path"]

        if os.path.exists(file_path):
            if file_info["is_dir"]:
                self._navigate_to_path(file_path)

    def _open_file_by_path(self, file_path):
        """
        通过文件路径打开文件或文件夹

        Args:
            file_path: 文件或文件夹路径
        """
        is_dir = os.path.isdir(file_path)

        if os.path.exists(file_path):
            if is_dir:
                self._navigate_to_path(file_path)
    
    def _show_properties(self, file_info):
        dialog = QDialog(self)
        dialog.setWindowTitle("文件属性")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        group_box = QGroupBox("基本信息")
        grid = QGridLayout(group_box)
        
        properties = [
            ("名称", file_info["name"]),
            ("路径", file_info["path"]),
            ("类型", "文件夹" if file_info["is_dir"] else "文件"),
            ("大小", self._format_size(file_info["size"])),
            ("修改时间", file_info["modified"]),
            ("创建时间", file_info["created"]),
        ]
        
        for i, (label, value) in enumerate(properties):
            grid.addWidget(QLabel(label + ":"), i, 0, Qt.AlignRight)
            value_label = QLabel(value)
            value_label.setWordWrap(True)
            grid.addWidget(value_label, i, 1)
        
        layout.addWidget(group_box)
        
        close_btn = QPushButton("关闭")
        close_btn.setFont(self.global_font)
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, 0, Qt.AlignRight)
        
        dialog.exec()
    
    def _remove_from_staging_pool(self, file_info):
        file_path = file_info["path"]
        file_path_norm = os.path.normpath(file_path)
        file_dir = os.path.normpath(os.path.dirname(file_path))
        
        if file_dir in self.selected_files:
            self.selected_files[file_dir].discard(file_path_norm)
            self._selected_file_paths.discard(file_path_norm)
            
            if not self.selected_files[file_dir]:
                del self.selected_files[file_dir]
            
            self.file_model.set_selected(file_path_norm, False)
            
            self.file_selection_changed.emit(file_info, False)
    
    def dragEnterEvent(self, event):
        """
        处理拖拽进入事件
        
        Args:
            event (QDragEnterEvent): 拖拽进入事件
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dragMoveEvent(self, event):
        """
        处理拖拽移动事件
        
        Args:
            event (QDragMoveEvent): 拖拽移动事件
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dragLeaveEvent(self, event):
        """
        处理拖拽离开事件
        
        Args:
            event (QDragLeaveEvent): 拖拽离开事件
        """
        # 根据用户需求，从外部拖入文件到文件选择器时不执行任何操作
        pass
    
    def dropEvent(self, event):
        """
        处理拖拽释放事件

        Args:
            event (QDropEvent): 拖拽释放事件
        """
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()

            for url in urls:
                file_path = url.toLocalFile()

                # 规范化文件路径，确保路径分隔符一致
                normalized_file_path = os.path.normpath(file_path)

                if os.path.isfile(normalized_file_path):
                    file_dir = os.path.normpath(os.path.dirname(normalized_file_path))

                    # 将文件选择器当前路径设置为文件所在目录
                    self._remember_navigation_source(file_dir)
                    self.current_path = file_dir

                    # 保存文件路径，用于回调函数
                    dropped_file_path = normalized_file_path

                    # 立即创建文件信息并更新选中状态，确保卡片创建时能正确显示选中状态
                    try:
                        file_name = os.path.basename(dropped_file_path)
                        file_stat = os.stat(dropped_file_path)
                        file_info = {
                            "name": file_name,
                            "path": dropped_file_path,
                            "is_dir": os.path.isdir(dropped_file_path),
                            "size": file_stat.st_size,
                            "modified": datetime.datetime.fromtimestamp(file_stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                            "created": datetime.datetime.fromtimestamp(file_stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
                            "suffix": os.path.splitext(file_name)[1].lower()[1:] if os.path.splitext(file_name)[1] else ""
                        }

                        # 选中该文件（如果尚未选中）
                        if file_dir not in self.selected_files:
                            self.selected_files[file_dir] = set()

                        file_already_selected = dropped_file_path in self._selected_file_paths

                        if not file_already_selected:
                            self.selected_files[file_dir].add(dropped_file_path)
                            self._selected_file_paths.add(dropped_file_path)

                            # 发出文件选择信号用于预览（立即发出，确保预览器能及时响应）
                            self.file_selected.emit(file_info)
                    except Exception as e:
                        warning(f"处理拖拽文件信息失败: {e}")
                        return

                    # 使用回调函数确保在文件卡片生成完成并更新UI选中状态后，再通知储存池
                    # 使用默认参数将变量绑定到函数，避免闭包作用域问题
                    def on_files_refreshed(file_info=file_info, file_already_selected=file_already_selected):
                        self._update_file_selection_state()

                        # 只有在文件尚未选中的情况下才发出file_selection_changed信号
                        # 这样可以确保UI状态刷新后，储存池才添加文件
                        if not file_already_selected:
                            self.file_selection_changed.emit(file_info, True)

                        self._update_file_selection_state()

                    # 刷新文件列表，显示文件所在目录的内容
                    self.refresh_files(callback=on_files_refreshed)

            event.acceptProposedAction()
        else:
            event.ignore()

        # 以下代码已被注释，因为根据用户需求，从外部拖入文件到文件选择器时不执行任何操作
    
    def _handle_dropped_file(self, file_path):
        """
        处理拖拽的文件，同时实现两个功能：
        1. 将文件添加到存储池
        2. 模拟右键选择行为

        Args:
            file_path (str): 文件路径
        """

        # 直接创建文件信息，而不是在files_layout中查找
        try:
            file_stat = os.stat(file_path)
            file_name = os.path.basename(file_path)
            file_dir = os.path.dirname(file_path)

            # 创建文件信息字典
            file_info = {
                "name": file_name,
                "path": file_path,
                "is_dir": os.path.isdir(file_path),
                "size": file_stat.st_size,
                "modified": datetime.datetime.fromtimestamp(file_stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "created": datetime.datetime.fromtimestamp(file_stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
                "suffix": os.path.splitext(file_name)[1].lower()[1:] if os.path.splitext(file_name)[1] else ""
            }

            # 1. 更新文件选择器内部的选中状态，避免重复添加
            if file_dir not in self.selected_files:
                self.selected_files[file_dir] = set()
            file_path_norm = os.path.normpath(file_path)
            # 检查文件是否已经被选中，如果是则跳过
            if file_path_norm in self._selected_file_paths:
                return
            # 添加到选中文件列表
            self.selected_files[file_dir].add(file_path_norm)
            self._selected_file_paths.add(file_path_norm)

            # 2. 发出文件选择状态变化信号，将文件添加到存储池
            self.file_selection_changed.emit(file_info, True)

            # 3. 发出文件右键点击信号，模拟右键选择行为
            self.file_right_clicked.emit(file_info)

            # 4. 更新UI显示选中状态
            self._update_file_selection_state()

        except Exception as e:
            warning(f"处理拖拽文件失败: {e}")
    
    def set_previewing_file(self, file_path):
        self.previewing_file_path = os.path.normpath(file_path) if file_path else None
        self.clear_previewing_state()
        if self.previewing_file_path:
            self.file_model.set_previewing(self.previewing_file_path, True)
    
    def clear_previewing_state(self):
        self.file_model.clear_previewing()
    
    def scroll_to_file(self, file_info):
        if not file_info or 'path' not in file_info:
            return

        target_path = os.path.normpath(file_info['path'])
        row = self.file_model.get_row(target_path)
        if row < 0:
            return

        list_view = getattr(self, 'files_scroll_area', None)
        if not list_view:
            return

        index = self.file_model.index(row, 0)
        list_view.scrollTo(index, QAbstractItemView.PositionAtTop)

# 使用项目中的自定义提示弹窗实现CSV生成进度显示

# 测试代码
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("自定义文件选择器")
    window.setGeometry(100, 100, 800, 600)
    
    selector = CustomFileSelector()
    window.setCentralWidget(selector)
    
    window.show()
    sys.exit(app.exec())
