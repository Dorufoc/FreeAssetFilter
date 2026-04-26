#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

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
from collections import deque
from datetime import datetime

# 添加项目根目录到Python路径，解决直接运行时的导入问题
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# 导入日志模块
from freeassetfilter.utils.app_logger import info, debug, warning, error

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QDialog, QApplication,
    QPushButton, QLabel, QComboBox, QLineEdit, QScrollArea, QListView,
    QHeaderView, QGroupBox, QGridLayout, QMenu,
    QFrame, QSplitter, QSizePolicy, QInputDialog, QListWidget, QProgressBar,
    QProgressDialog, QAbstractItemView
)
from PySide6.QtCore import (
    Qt, Signal, QThread, QObject, QEvent, QTimer,
    QFileInfo, QDateTime, QPoint, QSize, QRect, QRectF, QUrl
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
from freeassetfilter.core.svg_renderer import SvgRenderer
from freeassetfilter.widgets import CustomButton, CustomInputBox, CustomWindow, CustomMessageBox
from freeassetfilter.widgets.file_block_card import FileBlockCard
from freeassetfilter.widgets.file_horizontal_card import CustomFileHorizontalCard
from freeassetfilter.widgets.list_widgets import CustomSelectList
from freeassetfilter.widgets.dropdown_menu import CustomDropdownMenu
from freeassetfilter.widgets.hover_tooltip import HoverTooltip
from freeassetfilter.widgets.smooth_scroller import D_ScrollBar
from freeassetfilter.widgets.smooth_scroller import SmoothScroller
from freeassetfilter.components.auto_timeline import AutoTimeline
from freeassetfilter.utils.file_icon_helper import get_file_icon_path
from freeassetfilter.core.thumbnail_manager import get_thumbnail_manager, get_existing_thumbnail_path, is_media_file
from freeassetfilter.widgets.file_selector_model import FileSelectorListModel, FileListView
from freeassetfilter.widgets.file_selector_delegate import FileBlockCardDelegate


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
        local_drives = []
        network_locations = []

        if sys.platform == 'win32':
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                drives_bitmask = kernel32.GetLogicalDrives()
                for drive in range(26):
                    if drives_bitmask & (1 << drive):
                        local_drives.append(chr(65 + drive) + ':')
            except Exception as e:
                warning(f"获取本地盘符失败: {e}")

            try:
                import ctypes
                from ctypes import wintypes
                mpr = ctypes.WinDLL('mpr')

                class NETRESOURCE(ctypes.Structure):
                    _fields_ = [
                        ('dwScope', wintypes.DWORD),
                        ('dwType', wintypes.DWORD),
                        ('dwDisplayType', wintypes.DWORD),
                        ('dwUsage', wintypes.DWORD),
                        ('lpLocalName', wintypes.LPWSTR),
                        ('lpRemoteName', wintypes.LPWSTR),
                        ('lpComment', wintypes.LPWSTR),
                        ('lpProvider', wintypes.LPWSTR)
                    ]

                resource_connected = 1
                resource_type_any = 0
                h_enum = wintypes.HANDLE()

                if mpr.WNetOpenEnumW(resource_connected, resource_type_any, 0, None, ctypes.byref(h_enum)) == 0:
                    try:
                        while True:
                            buf_size = wintypes.DWORD(16384)
                            count = wintypes.DWORD(0xFFFFFFFF)
                            buf = ctypes.create_string_buffer(buf_size.value)
                            result = mpr.WNetEnumResourceW(h_enum, ctypes.byref(count), buf, ctypes.byref(buf_size))
                            if result != 0:
                                break

                            ptr = ctypes.cast(buf, ctypes.POINTER(NETRESOURCE))
                            for i in range(count.value):
                                res = ptr[i]
                                if res.lpLocalName:
                                    local_name = ctypes.wstring_at(res.lpLocalName)
                                    if local_name and local_name not in local_drives:
                                        local_drives.append(local_name)
                                if res.lpRemoteName:
                                    remote_name = ctypes.wstring_at(res.lpRemoteName)
                                    if remote_name and remote_name not in network_locations:
                                        network_locations.append(remote_name)
                    finally:
                        mpr.WNetCloseEnum(h_enum)
            except Exception as e:
                debug(f"获取网络位置失败，保留本地盘符列表: {e}")
        else:
            local_drives = ['/']

        local_drives = sorted(set(local_drives))
        network_locations = sorted(set(network_locations))
        self.loaded.emit(local_drives, network_locations)


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

                with os.scandir(self.current_path) as entries:
                    for entry in entries:
                        if entry.name.startswith("."):
                            continue

                        try:
                            if entry.is_symlink():
                                continue

                            stat = entry.stat(follow_symlinks=False)
                            files.append({
                                "name": entry.name,
                                "path": entry.path,
                                "is_dir": entry.is_dir(follow_symlinks=False),
                                "size": stat.st_size,
                                "modified": QDateTime.fromSecsSinceEpoch(int(stat.st_mtime)).toString(Qt.ISODate),
                                "created": QDateTime.fromSecsSinceEpoch(int(stat.st_ctime)).toString(Qt.ISODate),
                                "suffix": os.path.splitext(entry.name)[1].lower().lstrip('.')
                            })
                        except (OSError, PermissionError):
                            continue

            self.loaded.emit(self.current_path, files)
        except Exception as e:
            self.failed.emit(self.current_path, str(e))


class CustomFileSelector(QWidget):
    """
    自定义文件选择器组件
    使用卡片式布局，实现鼠标悬停高亮和点击选择功能
    """
    
    # 定义信号
    file_selected = Signal(dict)  # 当文件被选中时发出
    file_right_clicked = Signal(dict)  # 当文件被右键点击时发出
    file_selection_changed = Signal(dict, bool)  # 当文件选择状态改变时发出
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 获取应用实例和DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 获取全局字体
        self.global_font = getattr(app, 'global_font', QFont())
        
        # 设置组件字体
        self.setFont(self.global_font)
        
        # 计算卡片基础宽度（与 FileBlockCard 保持一致）
        card_width = self._calculate_card_base_width()
        spacing = int(5 * self.dpi_scale)  # 卡片间距
        margin = int(5 * self.dpi_scale)  # 单边边距
        scrollbar_width = int(10 * self.dpi_scale)  # 滚动条宽度估计值
        
        # 3列卡片总宽度 = 3*卡片宽度 + 2*间距（因为3列只有2个间距）
        cards_total_width = 3 * card_width + 2 * spacing
        # 左右边距总和
        margins_total = 2 * margin
        # 总最小宽度 = 卡片总宽度 + 边距总和 + 滚动条宽度
        min_three_columns_width = cards_total_width + margins_total + scrollbar_width
        
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
        
        # 保存当前路径到文件
        self.save_path_file = os.path.join(os.path.dirname(__file__), "..", "..", "data", "last_path.json")
        
        # 收藏夹配置文件
        self.favorites_file = os.path.join(os.path.dirname(__file__), "..", "..", "config", "favorites.json")
        self.favorites = self._load_favorites()
        
        # 确保数据目录存在
        os.makedirs(os.path.dirname(self.save_path_file), exist_ok=True)
        os.makedirs(os.path.dirname(self.favorites_file), exist_ok=True)
        
        # 添加防抖定时器，用于减少刷新频率
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.setInterval(300)
        self.resize_timer.timeout.connect(self._on_resize_timeout)
        
        # 文件选择器 Model/View 架构相关
        self.file_model = FileSelectorListModel(self.dpi_scale, self.global_font)
        self.card_delegate = FileBlockCardDelegate(self.dpi_scale, self.global_font)
        self.files_scroll_area = None
        self._is_loading = False
        self._drive_list_thread = None
        self._file_loader_thread = None
        self._refresh_request_id = 0
        self._cached_local_drives = []
        self._cached_network_locations = []
        self._pending_path_transition_direction = 0
        self._pending_path_transition_token = 0
        
        # 首次显示标志位，用于避免初始化时卡片重叠
        self._first_show = True
        self._thumbnail_thread = None
        
        # 初始化悬浮详细信息组件
        self.hover_tooltip = HoverTooltip(self)
        
        # 初始化UI
        self.init_ui()
        
        # 启用拖拽功能
        self.setAcceptDrops(True)
        self.files_scroll_area.setAcceptDrops(True)
        
        # 获取应用实例
        app = QApplication.instance()
        # 初始化设置管理器
        from freeassetfilter.core.settings_manager import SettingsManager
        settings_manager = getattr(app, 'settings_manager', SettingsManager())
        
        # 根据设置决定是否加载上次的路径
        if settings_manager.get_setting("file_selector.restore_last_path", True):
            # 加载上次保存的路径
            self.load_last_path()
        else:
            # 默认显示"All"界面
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
        从文件中加载上次打开的路径
        """
        try:
            if os.path.exists(self.save_path_file):
                with open(self.save_path_file, 'r') as f:
                    data = json.load(f)
                    last_accessible_path = data.get("last_accessible_path")
                    if self._is_valid_selector_path(last_accessible_path):
                        self._last_accessible_path = last_accessible_path
                        self._navigation_recovery_path = last_accessible_path

                    # 只有当上次保存的路径存在且不是无效路径时才使用
                    if "last_path" in data:
                        last_path = data["last_path"]
                        # 检查路径是否有效（普通路径需要存在，"All"是特殊路径）
                        if self._is_valid_selector_path(last_path):
                            self.current_path = last_path
        except Exception as e:
            warning(f"加载上次路径失败: {e}")
            # 如果加载失败，确保默认显示"All"
            self.current_path = "All"
    
    def save_current_path(self, path=None):
        """
        保存当前路径到文件
        """
        try:
            last_accessible_path = getattr(self, "_last_accessible_path", "All")
            if path is None:
                current_path = getattr(self, "current_path", "All")
                if self._same_selector_path(current_path, last_accessible_path):
                    path_to_save = current_path
                else:
                    path_to_save = getattr(self, "_navigation_recovery_path", None) or last_accessible_path or "All"
            else:
                path_to_save = path

            with open(self.save_path_file, 'w') as f:
                json.dump({
                    "last_path": path_to_save,
                    "last_accessible_path": last_accessible_path,
                }, f)
        except Exception as e:
            warning(f"保存路径失败: {e}")
    
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
            background_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#f1f3f5")
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
            base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#212121")
        
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
        
        # 返回上一次退出所在目录按钮
        # 使用arrow_counterclockwise_clock.svg图标替换文字，样式为普通样式
        import os
        last_path_icon_path = os.path.join(os.path.dirname(__file__), "..", "icons", "arrow_counterclockwise_clock.svg")
        self.last_path_btn = CustomButton(last_path_icon_path, button_type="normal", display_mode="icon", tooltip_text="返回上一次退出程序时的目录")
        self.last_path_btn.clicked.connect(self._go_to_last_path)
        nav_layout.addWidget(self.last_path_btn)
        # 添加到悬浮信息目标控件
        self.hover_tooltip.set_target_widget(self.last_path_btn)
        
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
        list_bullet_icon_path = os.path.join(os.path.dirname(__file__), "..", "icons", "list_bullet.svg")
        self.sort_btn = CustomButton(list_bullet_icon_path, button_type="normal", display_mode="icon", tooltip_text="排序方式")
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
        
        # 时间线按钮 - 移到第二行最后
        self.timeline_btn = CustomButton("时间线", button_type="primary")
        self.timeline_btn.clicked.connect(self._show_timeline_window)
        nav_layout.addWidget(self.timeline_btn)

        # 根据设置控制时间线按钮的显示/隐藏
        self._update_timeline_button_visibility()
        
        main_layout.addLayout(nav_layout)
        
        return panel
    
    def _create_files_area(self):
        """
        创建文件列表区域 - 使用 Model/View 架构
        """
        app = QApplication.instance()
        base_color = "#212121"
        auxiliary_color = "#313131"
        normal_color = "#717171"
        secondary_color = "#FFFFFF"
        accent_color = "#F0C54D"
        
        if hasattr(app, 'settings_manager'):
            base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#212121")
            auxiliary_color = app.settings_manager.get_setting("appearance.colors.auxiliary_color", "#313131")
            normal_color = app.settings_manager.get_setting("appearance.colors.normal_color", "#717171")
            secondary_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#FFFFFF")
            accent_color = app.settings_manager.get_setting("appearance.colors.accent_color", "#F0C54D")
        
        self._card_spacing = int(5 * self.dpi_scale)
        self._card_margin = int(3 * self.dpi_scale)

        # 使用 QListView 替代 QScrollArea + QGridLayout
        self.files_scroll_area = FileListView(self)
        self.files_scroll_area.setObjectName("fileListView")
        
        # 设置 Model 和 Delegate
        self.files_scroll_area.setModel(self.file_model)
        self.files_scroll_area.setItemDelegate(self.card_delegate)
        self.card_delegate.set_view(self.files_scroll_area)
        
        # 配置 QListView 属性
        self.files_scroll_area.setViewMode(QListView.IconMode)
        self.files_scroll_area.setResizeMode(QListView.Adjust)
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
        
        # 替换垂直滚动条为 D_ScrollBar
        self.files_scroll_area.setVerticalScrollBar(D_ScrollBar(self.files_scroll_area, Qt.Vertical))
        self.files_scroll_area.verticalScrollBar().apply_theme_from_settings()
        
        # 应用平滑滚动
        # 注意：这里必须禁用 LeftMouseButtonGesture，
        # 否则会与文件卡片的长按拖拽手势竞争，导致长按拖拽异常。
        SmoothScroller.apply(self.files_scroll_area, enable_mouse_drag=False)
        
        # 设置像素级滚动模式
        self.files_scroll_area.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.files_scroll_area.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

        # 滚动区域样式（与原来保持一致）
        scaled_padding = int(3 * self.dpi_scale)
        scrollbar_style = f"""
            QListView {{
                border: 1px solid {normal_color};
                border-radius: 8px;
                background-color: {base_color};
                padding: {scaled_padding}px;
            }}
        """
        self.files_scroll_area.setStyleSheet(scrollbar_style)

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
            base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF")
        
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
        
        # 选中文件计数
        #self.selected_count_label = QLabel("当前目录: 0 个，所有目录: 0 个")
        #layout.addWidget(self.selected_count_label, 1, Qt.AlignRight)
        
        return status_bar

    def _get_theme_colors(self):
        """
        获取当前主题颜色
        """
        app = QApplication.instance()
        colors = {
            "base_color": "#212121",
            "auxiliary_color": "#313131",
            "normal_color": "#717171",
            "secondary_color": "#FFFFFF",
            "accent_color": "#F0C54D",
        }

        if hasattr(app, "settings_manager"):
            colors["base_color"] = app.settings_manager.get_setting("appearance.colors.base_color", colors["base_color"])
            colors["auxiliary_color"] = app.settings_manager.get_setting("appearance.colors.auxiliary_color", colors["auxiliary_color"])
            colors["normal_color"] = app.settings_manager.get_setting("appearance.colors.normal_color", colors["normal_color"])
            colors["secondary_color"] = app.settings_manager.get_setting("appearance.colors.secondary_color", colors["secondary_color"])
            colors["accent_color"] = app.settings_manager.get_setting("appearance.colors.accent_color", colors["accent_color"])

        return colors

    def update_theme(self):
        """
        增量刷新文件选择器主题，不重建文件列表
        """
        FileBlockCard._clear_shared_caches()
        self.file_model.clear_caches(emit_change=True)
        self.card_delegate.update_theme()
        colors = self._get_theme_colors()

        self.setStyleSheet(f"background-color: {colors['secondary_color']};")

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
            scrollbar_style = f"""
                QListView {{
                    border: 1px solid {colors['normal_color']};
                    border-radius: 8px;
                    background-color: {colors['base_color']};
                    padding: {scaled_padding}px;
                }}
            """
            self.files_scroll_area.setStyleSheet(scrollbar_style)
            scrollbar = self.files_scroll_area.verticalScrollBar()
            if hasattr(scrollbar, "apply_theme_from_settings"):
                scrollbar.apply_theme_from_settings()
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
            "last_path_btn",
            "filter_btn",
            "sort_btn",
            "timeline_btn",
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
        从文件中加载收藏夹列表
        """
        try:
            if os.path.exists(self.favorites_file):
                with open(self.favorites_file, 'r', encoding='utf-8') as f:
                    favorites_data = json.load(f)
                    # 确保返回的数据是列表类型
                    if isinstance(favorites_data, list):
                        return favorites_data
                    else:
                        warning(f"收藏夹数据格式错误，预期列表类型，实际为 {type(favorites_data).__name__}")
        except Exception as e:
            warning(f"加载收藏夹失败: {e}")
        return []
    
    def _save_favorites(self):
        """
        保存收藏夹列表到文件
        """
        try:
            with open(self.favorites_file, 'w', encoding='utf-8') as f:
                json.dump(self.favorites, f, ensure_ascii=False, indent=2)
        except Exception as e:
            warning(f"保存收藏夹失败: {e}")
    
    def _show_favorites_dialog(self):
        """
        显示收藏夹对话框
        """
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 9)
        scaled_font_size = int(default_font_size * self.dpi_scale)
        
        base_color = "#FFFFFF"
        auxiliary_color = "#E6E6E6"
        normal_color = "#808080"
        secondary_color = "#333333"
        accent_color = "#1890ff"
        
        if hasattr(app, 'settings_manager'):
            base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF")
            auxiliary_color = app.settings_manager.get_setting("appearance.colors.auxiliary_color", "#E6E6E6")
            normal_color = app.settings_manager.get_setting("appearance.colors.normal_color", "#808080")
            secondary_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
            accent_color = app.settings_manager.get_setting("appearance.colors.accent_color", "#1890ff")
        
        dialog = CustomMessageBox(self)
        dialog.set_title("收藏夹")
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        scroll_area.setVerticalScrollBar(D_ScrollBar(scroll_area, Qt.Vertical))
        scroll_area.verticalScrollBar().apply_theme_from_settings()
        
        SmoothScroller.apply_to_scroll_area(scroll_area)
        
        scrollbar_style = f"""
            QScrollArea {{
                border: 1px solid {normal_color};
                border-radius: 8px;
                background-color: {base_color};
                padding: 3px;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {base_color};
            }}
        """
        scroll_area.setStyleSheet(scrollbar_style)
        scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scroll_area.setMinimumWidth(int(400 * self.dpi_scale))
        
        list_content = QWidget()
        list_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        list_content_layout = QVBoxLayout(list_content)
        list_content_layout.setContentsMargins(0, 0, 0, 0)
        list_content_layout.setSpacing(int(4 * self.dpi_scale))
        
        favorites_cards = []

        for favorite in self.favorites:
            # 检查路径是否存在
            path_exists = os.path.exists(favorite['path'])

            card = CustomFileHorizontalCard(
                file_path=favorite['path'],
                parent=list_content,
                enable_multiselect=False,
                display_name=favorite['name'],
                single_line_mode=False
            )
            # 设置路径存在状态
            card.set_path_exists(path_exists)

            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            list_content_layout.addWidget(card)
            favorites_cards.append({'card': card, 'favorite': favorite})

            card.clicked.connect(lambda path, fav=favorite, d=dialog: self._on_favorite_card_clicked(path, fav, d, favorites_cards))
            card.renameRequested.connect(lambda p, f=favorite, d=dialog, fc=favorites_cards: self._on_favorite_rename(f, d, fc))
            card.deleteRequested.connect(lambda p, f=favorite, d=dialog, fc=favorites_cards: self._on_favorite_delete(f, d, fc))
        
        list_content.setLayout(list_content_layout)
        
        scroll_area.setWidget(list_content)
        dialog.list_layout.addWidget(scroll_area)
        dialog.list_widget.show()
        
        def refresh_favorites_display():
            while list_content_layout.count():
                item = list_content_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            favorites_cards.clear()

            for favorite in self.favorites:
                # 检查路径是否存在
                path_exists = os.path.exists(favorite['path'])

                card = CustomFileHorizontalCard(
                    file_path=favorite['path'],
                    parent=list_content,
                    enable_multiselect=False,
                    display_name=favorite['name'],
                    single_line_mode=False
                )
                # 设置路径存在状态
                card.set_path_exists(path_exists)

                card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                list_content_layout.addWidget(card)
                favorites_cards.append({'card': card, 'favorite': favorite})

                card.clicked.connect(lambda path, fav=favorite, d=dialog: self._on_favorite_card_clicked(path, fav, d, favorites_cards))
                card.renameRequested.connect(lambda p, f=favorite, d=dialog, fc=favorites_cards: self._on_favorite_rename(f, d, fc))
                card.deleteRequested.connect(lambda p, f=favorite, d=dialog, fc=favorites_cards: self._on_favorite_delete(f, d, fc))
        
        dialog.set_buttons(["添加当前路径到收藏夹", "关闭"], Qt.Horizontal, ["primary", "secondary"])
        
        def on_button_clicked(button_index):
            if button_index == 0:
                self._add_current_path_to_favorites_custom(dialog, refresh_favorites_display)
            elif button_index == 1:
                dialog.close()
        
        dialog.buttonClicked.connect(on_button_clicked)
        
        dialog.exec()
    
    def _on_favorite_card_clicked(self, path, favorite, dialog, favorites_cards):
        """
        点击收藏夹卡片时跳转到对应路径
        """
        if os.path.exists(favorite['path']):
            self._navigate_to_path(favorite['path'])
            dialog.close()
    
    def _on_favorite_rename(self, favorite, dialog, favorites_cards):
        """
        重命名收藏夹项
        """
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
                
                for item in favorites_cards:
                    if item['favorite']['path'] == favorite['path'] and item['favorite']['name'] == favorite['name']:
                        item['favorite']['name'] = new_name.strip()
                        item['card'].set_file_path(favorite['path'], new_name.strip())
                        break
    
    def _on_favorite_delete(self, favorite, dialog, favorites_cards):
        """
        删除收藏夹项
        """
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
            
            for item in favorites_cards:
                if item['favorite']['path'] == favorite['path'] and item['favorite']['name'] == favorite['name']:
                    item['card'].deleteLater()
                    favorites_cards.remove(item)
                    break
    
    def _add_current_path_to_favorites_custom(self, dialog, refresh_callback):
        """
        添加当前路径到收藏夹（卡片版本）
        """
        current_path = self.current_path
        
        for favorite in self.favorites:
            if favorite['path'] == current_path:
                from freeassetfilter.widgets.D_widgets import CustomMessageBox
                msg_box = CustomMessageBox(self)
                msg_box.set_title("提示")
                msg_box.set_text("该路径已在收藏夹中")
                msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                msg_box.buttonClicked.connect(msg_box.close)
                msg_box.exec()
                return
        
        default_name = os.path.basename(current_path) or current_path
        
        from freeassetfilter.widgets.D_widgets import CustomMessageBox
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
                refresh_callback()
                
                success_msg = CustomMessageBox(self)
                success_msg.set_title("添加成功")
                success_msg.set_text(f"已添加 '{name.strip()}' 到收藏夹")
                success_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                
                def on_success_ok():
                    success_msg.close()
                    dialog.close()
                
                success_msg.buttonClicked.connect(on_success_ok)
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
        item = favorites_list.itemAt(pos)
        if not item:
            return
        
        menu = QMenu(self)
        
        # 重命名菜单项
        rename_action = QAction("重命名", self)
        rename_action.triggered.connect(lambda: self._rename_favorite(item, favorites_list))
        menu.addAction(rename_action)
        
        # 删除菜单项
        delete_action = QAction("删除", self)
        delete_action.triggered.connect(lambda: self._delete_favorite(item, favorites_list))
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
    
    def _go_to_last_path(self):
        """
        跳转到上次退出时的目录
        """
        previous_path = self.current_path
        self.load_last_path()
        target_path = self.current_path
        self.current_path = previous_path
        self._navigate_to_path(target_path)

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
    
    def _is_drive_available(self, drive_path):
        """
        检测盘符是否可用（可以正常访问）
        
        Args:
            drive_path: 盘符路径，如 "C:\\" 或 "D:"
            
        Returns:
            bool: 如果盘符可用返回True，否则返回False
        """
        try:
            # 确保路径格式正确
            if not drive_path.endswith(('\\', '/')):
                drive_path = drive_path + '\\'
            
            # 方法1: 尝试获取盘符信息
            import os
            if not os.path.exists(drive_path):
                debug(f"盘符 {drive_path} 不存在")
                return False
            
            # 方法2: 尝试列出根目录内容，这是最可靠的检测方式
            try:
                # 快速检查，只列出第一个条目
                with os.scandir(drive_path) as it:
                    next(it, None)
                return True
            except (OSError, PermissionError) as e:
                debug(f"检测盘符 {drive_path} 可用性时出错: {e}")
                return False
            except StopIteration:
                # 目录存在但是空的，这也算可用
                return True
                
        except Exception as e:
            debug(f"检测盘符 {drive_path} 可用性时发生异常: {e}")
            return False
    
    def _update_drive_list(self):
        """
        动态获取当前系统存在的盘符列表和网络位置并更新到下拉框
        """
        cached_items = self._build_drive_items(self._cached_local_drives, self._cached_network_locations)
        if cached_items:
            self._apply_drive_list(cached_items)

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
        self.refresh_files()
    
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
            self._file_loader_thread.loaded.connect(lambda loaded_path, files: self._on_files_loaded(request_id, loaded_path, files, callback, scroll_to_top))
            self._file_loader_thread.failed.connect(lambda failed_path, message: self._on_files_load_failed(request_id, failed_path, message))
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
            self._update_file_selection_state()
            self._check_and_apply_preview_state()

            if scroll_to_top and hasattr(self, 'files_scroll_area') and self.files_scroll_area:
                scrollbar = self.files_scroll_area.verticalScrollBar()
                scrollbar.setValue(0)

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
            QTimer.singleShot(0, lambda: self._finish_files_path_transition_deferred(token, direction))
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
            # 正常目录视图 - 使用 os.scandir() 替代 os.listdir() + QFileInfo
            try:
                if os.path.islink(self.current_path):
                    raise OSError("拒绝扫描符号链接目录")

                # os.scandir() 返回的 DirEntry 对象已经缓存了文件元数据，性能更好
                with os.scandir(self.current_path) as entries:
                    for entry in entries:
                        # 跳过隐藏文件
                        if entry.name.startswith("."):
                            continue
                        
                        try:
                            if entry.is_symlink():
                                continue

                            # 使用 DirEntry 的 stat() 方法获取文件信息（缓存的，不触发额外系统调用）
                            stat = entry.stat(follow_symlinks=False)
                            
                            # 构建文件信息字典
                            file_dict = {
                                "name": entry.name,
                                "path": entry.path,
                                "is_dir": entry.is_dir(follow_symlinks=False),
                                "size": stat.st_size,
                                "modified": QDateTime.fromSecsSinceEpoch(int(stat.st_mtime)).toString(Qt.ISODate),
                                "created": QDateTime.fromSecsSinceEpoch(int(stat.st_ctime)).toString(Qt.ISODate),
                                "suffix": os.path.splitext(entry.name)[1].lower().lstrip('.')
                            }
                            
                            files.append(file_dict)
                        except (OSError, PermissionError):
                            # 跳过无法访问的文件
                            continue

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
        if self.sort_by == "name":
            files.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        elif self.sort_by == "size":
            files.sort(key=lambda x: (not x["is_dir"], x["size"]))
        elif self.sort_by == "modified":
            files.sort(key=lambda x: (not x["is_dir"], x["modified"]))
        elif self.sort_by == "created":
            files.sort(key=lambda x: (not x["is_dir"], x["created"]))
        
        if self.sort_order == "desc":
            files.reverse()
        
        return files
    
    def _filter_files(self, files):
        """
        应用筛选器
        支持通配符 * 和 ?，对无效的正则表达式进行错误处理
        """
        if self.filter_pattern == "*":
            return files
        
        filtered = []
        # 将通配符转换为正则表达式
        pattern = self.filter_pattern.replace(".", "\\.")
        pattern = pattern.replace("*", ".*")
        pattern = pattern.replace("?", ".")
        pattern = f"^{pattern}$"
        
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            # 正则表达式无效，返回空列表
            return []
        
        for file in files:
            if regex.match(file["name"]):
                filtered.append(file)
        
        return filtered
    
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
        margin = self._card_margin * 2

        available_width = max(0, viewport_width - margin)

        columns = 1
        max_possible_columns = 0

        while True:
            total_width = columns * cell_width
            if total_width <= available_width:
                max_possible_columns = columns
                columns += 1
            else:
                break

        return max(1, max_possible_columns)
    
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
        margin = self._card_margin * 2

        available_width = max(0, viewport_width - margin)
        total_spacing = max_cols * spacing

        if max_cols <= 0:
            return card_base_width

        card_width = (available_width - total_spacing) // max_cols

        return max(card_width, card_base_width)
    
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
        list_view = getattr(self, 'files_scroll_area', None)
        if not list_view or not self.file_model:
            return

        viewport_width = list_view.viewport().width()
        if viewport_width <= 0:
            return

        # 计算边距（与 _card_margin 保持一致）
        margin = self._card_margin * 2
        available_width = viewport_width - margin

        # 计算卡片基础宽度
        card_base_width = self._calculate_card_base_width()
        spacing = self._card_spacing

        # 计算最大列数
        max_cols = 1
        while True:
            total_width = max_cols * (card_base_width + spacing)
            if total_width > available_width:
                max_cols -= 1
                break
            max_cols += 1
            if max_cols > 100:  # 防止死循环
                break
        
        max_cols = max(1, max_cols)

        # 计算每个卡片的实际宽度
        total_spacing = max_cols * spacing
        card_width = max((available_width - total_spacing) // max_cols, card_base_width)

        # 卡片高度
        card_height = int(75 * self.dpi_scale)

        # gridSize 表示单元格尺寸，包含为卡片矩阵留出的外边距；
        # delegate 会在单元格内部居中绘制真实卡片。
        list_view.setSpacing(0)
        grid_size = QSize(card_width + spacing, card_height + spacing)
        list_view.setGridSize(grid_size)

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
        # import datetime
        # def debug(msg):
        #     timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        #     pass

        # debug(f"卡片拖拽开始: {file_info.get('name', '')}")
    
    def _on_card_drag_ended(self, file_info, drop_target):
        """
        处理卡片拖拽结束
        根据放置目标执行相应操作

        Args:
            file_info (dict): 文件信息
            drop_target (str): 放置目标类型 ('staging_pool', 'previewer', 'none')
        """
        # import datetime
        # from freeassetfilter.utils.app_logger import debug as logger_debug
        # def debug(msg):
        #     timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        #     logger_debug(f"[{timestamp}] [CustomFileSelector._on_card_drag_ended] {msg}")

        file_path = file_info.get('path', '')
        file_path_norm = os.path.normpath(file_path)
        file_dir_norm = os.path.normpath(os.path.dirname(file_path))

        # debug(f"卡片拖拽结束: {file_info.get('name', '')}, 目标: {drop_target}")

        if drop_target == 'staging_pool':
            # 拖拽到存储池，选中文件
            # debug(f"拖拽到存储池，选中文件: {file_path_norm}")

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
                # debug(f"文件已添加到存储池")
            # else:
                # debug(f"文件已在存储池中，跳过")

        elif drop_target == 'previewer':
            # 拖拽到预览器，预览文件
            # debug(f"拖拽到预览器，预览文件: {file_path_norm}")
            # 发出文件选中信号，启动预览
            self.file_selected.emit(file_info)
            # debug(f"预览信号已发出")

        # else:
            # 未放置到有效区域
            # debug(f"未放置到有效区域")
    
    def _handle_card_clicked_signal(self, file_info):
        """处理卡片左键点击，始终基于信号携带的当前 file_info。"""
        if file_info.get("is_dir"):
            self._on_folder_clicked(file_info["path"])
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
    
    #def _update_selected_count(self):
        """
        更新选中文件计数
        """
       # current_selected = len(self.selected_files.get(self.current_path, set()))
        #total_selected = sum(len(files) for files in self.selected_files.values())
        #self.selected_count_label.setText(f"当前目录: {current_selected} 个，所有目录: {total_selected} 个")
    
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
                        secondary_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#f1f3f5")
                        accent_color = app.settings_manager.get_setting("appearance.colors.accent_color", "#1890ff")
                    self.setStyleSheet(f"background-color: {secondary_color}; border: 3px dashed {accent_color}; border-radius: {int(8 * self.dpi_scale)}px;")
                    return True
            elif event.type() == QEvent.DragLeave:
                app = QApplication.instance()
                secondary_color = "#f1f3f5"
                if hasattr(app, 'settings_manager'):
                    secondary_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#f1f3f5")
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
        # import datetime
        # from freeassetfilter.utils.app_logger import debug as logger_debug
        # def debug(msg):
        #     timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        #     logger_debug(f"[{timestamp}] [CustomFileSelector] {msg}")

        is_dir = os.path.isdir(file_path)
        # debug(f"打开文件: {file_path}, 是否为目录: {is_dir}")

        if os.path.exists(file_path):
            if is_dir:
                # debug(f"打开目录，进入新路径: {file_path}")
                self._navigate_to_path(file_path)
            # else:
                # debug(f"打开文件: {file_path}")
    
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
        # import datetime
        # from freeassetfilter.utils.app_logger import debug as logger_debug
        # def debug(msg):
        #     timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        #     logger_debug(f"[{timestamp}] [CustomFileSelector.dropEvent] {msg}")

        # debug("=== DROP EVENT START ===")

        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            # debug(f"拖拽的URL数量: {len(urls)}")

            for url in urls:
                file_path = url.toLocalFile()
                # debug(f"处理拖拽的文件路径（原始）: {file_path}")

                # 规范化文件路径，确保路径分隔符一致
                normalized_file_path = os.path.normpath(file_path)
                # debug(f"处理拖拽的文件路径（规范化后）: {normalized_file_path}")

                if os.path.isfile(normalized_file_path):
                    # 单个文件：自动导航至该文件所在的目录路径，并在文件选择器中高亮选中该文件
                    # debug(f"文件类型: 文件")
                    file_dir = os.path.normpath(os.path.dirname(normalized_file_path))
                    # debug(f"文件所在目录（规范化后）: {file_dir}")

                    # 将文件选择器当前路径设置为文件所在目录
                    self._remember_navigation_source(file_dir)
                    self.current_path = file_dir
                    # debug(f"设置当前路径为: {file_dir}")

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
                        # debug(f"检查目录 {file_dir} 是否在selected_files中")
                        if file_dir not in self.selected_files:
                            # debug(f"目录 {file_dir} 不存在于selected_files中，创建新条目")
                            self.selected_files[file_dir] = set()
                            # debug(f"创建后的selected_files: {self.selected_files}")
                            pass
                        # else:
                            # debug(f"目录已存在，当前selected_files[{file_dir}]: {self.selected_files[file_dir]}")

                        file_already_selected = dropped_file_path in self._selected_file_paths
                        # debug(f"文件是否已选中: {file_already_selected}")

                        if not file_already_selected:
                            # debug(f"添加文件到选中列表")
                            self.selected_files[file_dir].add(dropped_file_path)
                            self._selected_file_paths.add(dropped_file_path)
                            # debug(f"添加后的selected_files[{file_dir}]: {self.selected_files[file_dir]}")
                            # debug(f"完整的selected_files: {self.selected_files}")

                            # 发出文件选择信号用于预览（立即发出，确保预览器能及时响应）
                            # debug(f"发出file_selected信号，启动统一预览器")
                            self.file_selected.emit(file_info)
                        # else:
                            # debug(f"文件已在选中列表中，跳过重复添加")
                            # debug(f"当前selected_files[{file_dir}]: {self.selected_files[file_dir]}")
                    except Exception as e:
                        # debug(f"处理文件信息时出错: {e}")
                        warning(f"处理拖拽文件信息失败: {e}")
                        return

                    # 使用回调函数确保在文件卡片生成完成并更新UI选中状态后，再通知储存池
                    # 使用默认参数将变量绑定到函数，避免闭包作用域问题
                    def on_files_refreshed(file_info=file_info, file_already_selected=file_already_selected):
                        # debug("文件卡片生成完成，更新UI选中状态")
                        self._update_file_selection_state()

                        # 只有在文件尚未选中的情况下才发出file_selection_changed信号
                        # 这样可以确保UI状态刷新后，储存池才添加文件
                        if not file_already_selected:
                            # debug(f"UI状态刷新完成，发出file_selection_changed信号到储存池")
                            self.file_selection_changed.emit(file_info, True)

                        self._update_file_selection_state()

                    # 刷新文件列表，显示文件所在目录的内容
                    # debug(f"调用refresh_files刷新文件列表，完成后调用回调函数")
                    self.refresh_files(callback=on_files_refreshed)

            event.acceptProposedAction()
            # debug(f"接受拖拽提议的操作")
        else:
            event.ignore()

        # 以下代码已被注释，因为根据用户需求，从外部拖入文件到文件选择器时不执行任何操作
        # if False and event.mimeData().hasUrls():
        #     urls = event.mimeData().urls()
        #     debug(f"拖拽的URL数量: {len(urls)}")
        #
        #     if len(urls) == 1:
        #         # 单个文件或文件夹
        #         url = urls[0]
        #         file_path = url.toLocalFile()
        #         debug(f"拖拽的文件路径: {file_path}")
        #
        #         if os.path.isfile(file_path):
        #             # 单个文件：自动导航至该文件所在的目录路径，并在文件选择器中高亮选中该文件
        #             debug(f"文件类型: 文件")
        #             file_dir = os.path.normpath(os.path.dirname(file_path))
        #             debug(f"文件所在目录: {file_dir}")
        #
        #             self.current_path = file_dir
        #             debug(f"设置当前路径为: {file_dir}")
        #
        #             # 保存文件路径，用于回调函数
        #             dropped_file_path = file_path
        #
        #             # 使用回调函数确保在文件卡片生成完成后再进行后续操作
        #             def on_files_refreshed():
        #                 debug("文件卡片生成完成，开始后续操作")
        #                 # 选中该文件
        #                 if file_dir in self.selected_files:
        #                     debug(f"目录 {file_dir} 已存在于selected_files中")
        #                     self.selected_files[file_dir].add(dropped_file_path)
        #                 else:
        #                     debug(f"目录 {file_dir} 不存在于selected_files中，创建新条目")
        #                     self.selected_files[file_dir] = {dropped_file_path}
        #
        #                 debug(f"selected_files内容: {self.selected_files}")
        #
        #                 # 更新UI显示选中状态
        #                 self._update_file_selection_state()
        #                 debug(f"调用_update_file_selection_state更新选中状态")
        #
        #                 # 创建文件信息字典
        #                 try:
        #                     file_stat = os.stat(dropped_file_path)
        #                     file_name = os.path.basename(dropped_file_path)
        #                     file_info = {
        #                         "name": file_name,
        #                         "path": dropped_file_path,
        #                         "is_dir": os.path.isdir(dropped_file_path),
        #                         "size": file_stat.st_size,
        #                         "modified": datetime.datetime.fromtimestamp(file_stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        #                         "created": datetime.datetime.fromtimestamp(file_stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
        #                         "suffix": os.path.splitext(file_name)[1].lower()[1:] if os.path.splitext(file_name)[1] else ""
        #                     }
        #
        #                     # 发出文件选择信号用于预览
        #                     debug(f"发出file_selected信号，启动统一预览器")
        #                     self.file_selected.emit(file_info)
        #                 except Exception as e:
        #                     debug(f"创建文件信息失败: {e}")
        #
        #             self.refresh_files(callback=on_files_refreshed)
        #             debug(f"调用refresh_files刷新文件列表，完成后调用回调函数")
        #         elif os.path.isdir(file_path):
        #             # 单个文件夹：自动导航并展开至该文件夹内部路径
        #             debug(f"文件类型: 文件夹")
        #             self.current_path = file_path
        #             debug(f"设置当前路径为: {file_path}")
        #             self.refresh_files()
        #             debug(f"调用refresh_files刷新文件列表")
        #
        #     event.acceptProposedAction()
        #     debug(f"接受拖拽提议的操作")
    
    def _handle_dropped_file(self, file_path):
        """
        处理拖拽的文件，同时实现两个功能：
        1. 将文件添加到存储池
        2. 模拟右键选择行为

        Args:
            file_path (str): 文件路径
        """
        # import datetime
        # from freeassetfilter.utils.app_logger import debug as logger_debug
        # def debug(msg):
        #     timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        #     logger_debug(f"[{timestamp}] [CustomFileSelector._handle_dropped_file] {msg}")

        # debug(f"开始处理拖拽的文件: {file_path}")

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

            # debug(f"创建的文件信息: {file_info}")

            # 1. 更新文件选择器内部的选中状态，避免重复添加
            # debug(f"更新文件选择器内部的选中状态")
            if file_dir not in self.selected_files:
                self.selected_files[file_dir] = set()
            file_path_norm = os.path.normpath(file_path)
            # 检查文件是否已经被选中，如果是则跳过
            if file_path_norm in self._selected_file_paths:
                # debug(f"文件 {file_path} 已经被选中，跳过处理")
                return
            # 添加到选中文件列表
            self.selected_files[file_dir].add(file_path_norm)
            self._selected_file_paths.add(file_path_norm)

            # 2. 发出文件选择状态变化信号，将文件添加到存储池
            # debug(f"发出file_selection_changed信号，将文件添加到存储池")
            self.file_selection_changed.emit(file_info, True)

            # 3. 发出文件右键点击信号，模拟右键选择行为
            # debug(f"发出file_right_clicked信号，模拟右键选择")
            self.file_right_clicked.emit(file_info)

            # 4. 更新UI显示选中状态
            # debug(f"更新UI显示选中状态")
            self._update_file_selection_state()

            # debug(f"成功处理拖拽的文件: {file_path}")
        except Exception as e:
            # debug(f"处理文件时出错: {e}")
            warning(f"处理拖拽文件失败: {e}")

        # debug(f"完成处理拖拽的文件: {file_path}")
    
    def _update_timeline_button_visibility(self):
        """
        根据设置更新时间线按钮的显示/隐藏状态
        """
        app = QApplication.instance()
        if hasattr(app, 'settings_manager') and hasattr(self, 'timeline_btn'):
            timeline_enabled = app.settings_manager.get_setting("file_selector.timeline_view_enabled", False)
            self.timeline_btn.setVisible(timeline_enabled)

    def _show_timeline_window(self):
        """
        显示时间线窗口：先生成CSV文件，再显示时间线
        """
        from freeassetfilter.components.auto_timeline import AutoTimeline
        from freeassetfilter.widgets.progress_widgets import D_ProgressBar
        from freeassetfilter.core.timeline_generator import FolderScanner
        
        # 创建自定义提示弹窗
        progress_dialog = CustomMessageBox(self)
        progress_dialog.setModal(True)
        progress_dialog.set_title("生成CSV文件")
        progress_dialog.set_text("正在生成CSV文件，请稍候...")
        
        # 创建进度条
        progress_bar = D_ProgressBar(is_interactive=False)
        progress_bar.setRange(0, 1000)
        progress_bar.setValue(0)
        progress_dialog.set_progress(progress_bar)
        
        # 添加取消按钮
        progress_dialog.set_buttons(["取消"], orientations=Qt.Horizontal)
        
        # 初始化结果变量
        csv_path = ""
        events = []
        cancel_flag = False
        
        def on_progress_update(current, total):
            """更新进度条"""
            if total > 0:
                progress = int((current / total) * 100)
                progress_bar.setValue(progress)
        
        def on_csv_generated(result_events, result_csv_path, json_path):
            """CSV文件生成完成"""
            nonlocal csv_path, events
            if not cancel_flag:
                csv_path = result_csv_path
                events = result_events
                progress_dialog.close()
        
        def on_button_clicked(button_index):
            """处理按钮点击事件"""
            nonlocal cancel_flag
            if button_index == 0:  # 取消按钮
                cancel_flag = True
                scanner.terminate()  # 停止FolderScanner线程
                progress_dialog.close()
        
        # 连接按钮点击信号
        progress_dialog.buttonClicked.connect(on_button_clicked)
        
        # 创建并启动FolderScanner线程
        scanner = FolderScanner(self.current_path)
        scanner.scan_finished.connect(on_csv_generated)
        scanner.progress.connect(on_progress_update)
        scanner.start()
        
        # 显示进度对话框
        progress_dialog.exec()
        
        # 如果CSV文件生成成功，显示时间线组件
        if csv_path:
            # 创建并显示时间线窗口 - 使用实例变量防止垃圾回收
            self.timeline_window = AutoTimeline()
            self.timeline_window.setWindowFlags(Qt.Window)
            self.timeline_window.show()
            
            # 直接导入生成的CSV文件
            self.timeline_window.import_csv(csv_path)
    
    def set_previewing_file(self, file_path):
        self.previewing_file_path = os.path.normpath(file_path) if file_path else None
        self.clear_previewing_state()
        if self.previewing_file_path:
            self.file_model.set_previewing(self.previewing_file_path, True)
    
    def clear_previewing_state(self):
        self.file_model.clear_previewing()
    
    def scroll_to_file(self, file_info):
        """
        滚动到指定文件的位置，将目标卡片滚动到显示区域的第一行
        如果滚动范围不足，则滚动到最底部
        """
        if not file_info or 'path' not in file_info:
            return

        target_path = os.path.normpath(file_info['path'])

        row = self.file_model.get_row(target_path)
        if row < 0:
            return

        list_view = getattr(self, 'files_scroll_area', None)
        if not list_view:
            return

        vertical_scrollbar = list_view.verticalScrollBar()
        max_cols = self._calculate_max_columns()
        if max_cols <= 0:
            max_cols = 3

        # 计算目标视觉行号
        target_row = row // max_cols
        spacing = int(5 * self.dpi_scale)
        card_height = int(75 * self.dpi_scale)

        # 计算滚动位置：目标行 * (卡片高度 + 间距)
        desired_scroll_pos = target_row * (card_height + spacing)

        viewport_height = list_view.viewport().height()
        max_scroll = vertical_scrollbar.maximum()

        # 如果卡片高度大于视口高度（单卡片超出一屏），调整滚动位置
        if card_height > viewport_height:
            desired_scroll_pos = target_row * (card_height + spacing) + card_height - viewport_height

        # 限制在有效范围内
        desired_scroll_pos = max(0, min(desired_scroll_pos, max_scroll))

        from PySide6.QtCore import QPropertyAnimation, QEasingCurve

        if hasattr(self, "_scroll_to_file_animation") and self._scroll_to_file_animation:
            self._scroll_to_file_animation.stop()

        self._scroll_to_file_animation = QPropertyAnimation(vertical_scrollbar, b"value", self)
        self._scroll_to_file_animation.setDuration(220)
        self._scroll_to_file_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._scroll_to_file_animation.setStartValue(vertical_scrollbar.value())
        self._scroll_to_file_animation.setEndValue(desired_scroll_pos)
        self._scroll_to_file_animation.start()

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
