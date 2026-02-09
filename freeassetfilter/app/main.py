#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0.0
master
Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

FreeAssetFilter 主程序
核心功能应用程序，不包含视频播放器功能
"""

# 导入必要的模块用于异常处理
import sys
import os
import warnings
import time
import traceback
import faulthandler

# 启用faulthandler，捕获C++层崩溃
faulthandler.enable()

# 定义异常处理函数
def handle_exception(exc_type, exc_value, exc_traceback):
    """
    处理未捕获的Python异常
    
    Args:
        exc_type: 异常类型
        exc_value: 异常值
        exc_traceback: 异常回溯信息
    """
    if issubclass(exc_type, KeyboardInterrupt):
        # 如果是用户中断，使用系统默认的异常处理
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    print("\n=== 检测到未捕获的异常 ===")
    print(f"异常类型: {exc_type.__name__}")
    print(f"异常值: {exc_value}")
    print("异常堆栈:")
    traceback.print_tb(exc_traceback)
    print("==========================\n")

# 将系统异常钩子绑定到自定义处理函数
sys.excepthook = handle_exception

# 忽略sipPyTypeDict相关的弃用警告
warnings.filterwarnings("ignore", category=DeprecationWarning, module="PyQt5")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*sipPyTypeDict.*")

# 添加父目录到Python路径，确保包能被正确导入
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    import pillow_avif
except ImportError:
    pass

from freeassetfilter.utils.path_utils import get_resource_path, get_app_data_path, get_config_path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGroupBox, QGridLayout, QSizePolicy, QSplitter, QMessageBox
)
from PyQt5.QtCore import Qt, QUrl, QEvent
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtGui import QFont, QIcon

# 导入自定义控件库
from freeassetfilter.widgets.D_widgets import CustomWindow, CustomButton



# 导入自定义文件选择器组件
from freeassetfilter.components.file_selector import CustomFileSelector
# 导入统一文件预览器组件
from freeassetfilter.components.unified_previewer import UnifiedPreviewer
# 导入文件临时存储池组件
from freeassetfilter.components.file_staging_pool import FileStagingPool
# 导入SVG渲染器，用于主题更新时清除SVG颜色缓存
from freeassetfilter.core.svg_renderer import SvgRenderer


class FreeAssetFilterApp(QMainWindow):
    """
    FreeAssetFilter 主应用程序类
    提供核心功能的主界面
    """
    
    def __init__(self):
        super().__init__()
        
        # 获取应用实例
        app = QApplication.instance()
        
        # 获取屏幕尺寸
        screen = QApplication.primaryScreen()
        
        # 使用逻辑像素设置窗口大小，Qt会自动处理DPI
        base_window_width = 850  # 基础逻辑像素（100%缩放时的大小）
        
        # 获取系统缩放因子并设置为1.5倍
        screen = QApplication.primaryScreen()
        logical_dpi = screen.logicalDotsPerInch()
        physical_dpi = screen.physicalDotsPerInch()
        system_scale = physical_dpi / logical_dpi if logical_dpi > 0 else 1.0
        
        # 设置默认大小为系统缩放的1.5倍
        window_width = int(base_window_width * system_scale * 1.5)
        window_height = int(window_width * (10/16))
        
        # 获取可用屏幕尺寸（逻辑像素）
        available_geometry = screen.availableGeometry()
        available_width_logical = available_geometry.width()
        available_height_logical = available_geometry.height()
        
        # 确保窗口大小不超过屏幕可用尺寸（使用逻辑像素）
        self.window_width = min(window_width, available_width_logical - 20)  # 留20px边距
        self.window_height = min(window_height, available_height_logical - 20)  # 留20px边距
        
        self.setWindowTitle("FreeAssetFilter")
        
        # 设置窗口大小
        self.resize(int(self.window_width), int(self.window_height))
        
        # 使用PyQt5内置方法将窗口居中到可用屏幕区域
        # 获取窗口的几何尺寸
        window_geometry = self.frameGeometry()
        # 获取屏幕可用区域的中心点
        center_point = screen.availableGeometry().center()
        # 将窗口的中心移动到屏幕可用区域的中心
        window_geometry.moveCenter(center_point)
        # 设置窗口位置（自动处理物理像素和逻辑像素的转换）
        self.move(window_geometry.topLeft())
        
        # 设置程序图标
        icon_path = get_resource_path('freeassetfilter/icons/FAF-main.ico')
        self.setWindowIcon(QIcon(icon_path))
        
        # 用于生成唯一的文件选择器实例ID
        self.file_selector_counter = 0
        
        # 主题更新状态标志，防止重复调用
        self._update_theme_in_progress = False
        self._theme_update_queued = False
        
        # 获取全局字体
        global_font = getattr(app, 'global_font', QFont())
        # 创建全局字体的副本，避免修改全局字体对象
        self.global_font = QFont(global_font)
        #print(f"\n[DEBUG] 主窗口获取到的全局字体: {self.global_font.family()}, 缩放后大小: {self.global_font.pointSize()}")
        
        # 设置窗口字体
        self.setFont(self.global_font)
        
        # 创建UI
        self.init_ui()

        # 启用窗口激活事件监听，用于焦点管理
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, False)

        # 应用窗口标题栏深色模式（根据当前主题设置）
        self._apply_title_bar_theme()

    def changeEvent(self, event):
        """
        窗口状态变化事件
        当主窗口获得焦点且存在分离的视频窗口时，将焦点还给分离窗口
        """
        if event.type() == event.WindowStateChange or event.type() == event.ActivationChange:
            # 检查是否有分离的视频窗口
            if hasattr(self, 'unified_previewer'):
                try:
                    from freeassetfilter.components.video_player import VideoPlayer
                    if isinstance(self.unified_previewer.current_preview_widget, VideoPlayer):
                        video_player = self.unified_previewer.current_preview_widget
                        # 如果视频播放器处于分离状态，将焦点还给分离窗口
                        if hasattr(video_player, '_is_detached') and video_player._is_detached:
                            if hasattr(video_player, '_detached_window') and video_player._detached_window:
                                # 使用定时器延迟执行，避免焦点争夺导致的闪烁
                                from PyQt5.QtCore import QTimer
                                QTimer.singleShot(50, lambda: self._restore_detached_window_focus(video_player))
                except ImportError:
                    pass
        super().changeEvent(event)

    def _restore_detached_window_focus(self, video_player):
        """
        恢复分离窗口的焦点和置顶状态
        """
        try:
            if (hasattr(video_player, '_detached_window') and
                video_player._detached_window and
                hasattr(video_player, '_is_detached') and
                video_player._is_detached):

                detached_window = video_player._detached_window

                # 将分离窗口置顶
                detached_window.raise_()
                detached_window.activateWindow()

                # 在Windows上使用Win32 API确保窗口置顶
                try:
                    import ctypes
                    from ctypes import wintypes

                    # 获取窗口句柄
                    hwnd = int(detached_window.winId())

                    # 使用SetWindowPos将窗口置顶（但不使用TOPMOST，避免真正的置顶）
                    # SWP_NOMOVE | SWP_NOSIZE = 0x0001 | 0x0002 = 0x0003
                    # HWND_TOP = 0
                    ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                                                       0x0003 | 0x0010 | 0x0040)

                    # 强制激活窗口
                    ctypes.windll.user32.SetForegroundWindow(hwnd)

                except Exception as e:
                    print(f"[MainWindow] Win32 API调用失败: {e}")

        except Exception as e:
            print(f"[MainWindow] 恢复分离窗口焦点失败: {e}")

    def closeEvent(self, event):
        """
        主窗口关闭事件，确保保存文件选择器的当前路径和文件存储池状态
        并关闭所有子窗口（包括全局设置窗口）
        """
        # 关闭所有子窗口，确保全局设置窗口等随主窗口关闭而销毁
        from PyQt5.QtWidgets import QDialog
        for widget in self.findChildren(QDialog):
            widget.close()
        
        # 保存文件选择器A的当前路径
        last_path = 'All'
        if hasattr(self, 'file_selector_a'):
            self.file_selector_a.save_current_path()
            last_path = self.file_selector_a.current_path
        # 保存文件存储池状态，传递文件选择器的当前路径
        if hasattr(self, 'file_staging_pool'):
            self.file_staging_pool.save_backup(last_path)
        
        # 检查并执行缩略图缓存自动清理
        app = QApplication.instance()
        if hasattr(app, 'settings_manager') and app.settings_manager.get_setting("file_selector.auto_clear_thumbnail_cache", True):
            from freeassetfilter.core.thumbnail_cleaner import get_thumbnail_cleaner
            thumbnail_cleaner = get_thumbnail_cleaner()
            deleted_count, remaining_count = thumbnail_cleaner.clean_thumbnails()
            #print(f"[DEBUG] 退出前自动清理缩略图缓存: 删除了 {deleted_count} 个文件，剩余 {remaining_count} 个文件")

        # 关闭分离的视频播放窗口（如果存在）
        if hasattr(self, 'unified_previewer'):
            try:
                from freeassetfilter.components.video_player import VideoPlayer
                # 检查统一预览器的当前预览组件是否是视频播放器
                if isinstance(self.unified_previewer.current_preview_widget, VideoPlayer):
                    video_player = self.unified_previewer.current_preview_widget
                    # 如果视频播放器处于分离状态，先合并回主窗口
                    if hasattr(video_player, '_is_detached') and video_player._is_detached:
                        if hasattr(video_player, '_detached_window') and video_player._detached_window:
                            video_player._detached_window.close()
            except ImportError:
                pass

        # 清理统一预览器中的临时PDF文件
        if hasattr(self, 'unified_previewer'):
            # 先停止任何正在运行的预览线程
            if hasattr(self.unified_previewer, '_preview_thread') and self.unified_previewer._preview_thread:
                if self.unified_previewer._preview_thread.isRunning():
                    self.unified_previewer._preview_thread.cancel()
                    self.unified_previewer._preview_thread.wait(500)
                    if self.unified_previewer._preview_thread.isRunning():
                        self.unified_previewer._preview_thread.terminate()
                        self.unified_previewer._preview_thread.wait(100)
            # 然后清理预览
            self.unified_previewer._clear_preview()
        
        # 统一清理：删除整个temp文件夹
        import shutil
        import os
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        temp_dir = os.path.join(project_root, "data", "temp")
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                #print(f"已删除临时文件夹: {temp_dir}")
            except Exception as e:
                print(f"删除临时文件夹失败: {e}")
                pass
        
        # 调用父类的closeEvent
        super().closeEvent(event)
    
    def keyPressEvent(self, event):
        """
        主窗口键盘按键事件处理
        - 空格键：控制视频播放/暂停，无论焦点在哪个组件
        """
        if event.key() == Qt.Key_Space:
            # 检查是否存在统一预览器
            if hasattr(self, 'unified_previewer'):
                try:
                    from freeassetfilter.components.video_player import VideoPlayer
                    # 检查统一预览器的当前预览组件是否是视频播放器
                    if isinstance(self.unified_previewer.current_preview_widget, VideoPlayer):
                        # 调用视频播放器的播放/暂停方法
                        self.unified_previewer.current_preview_widget.toggle_play_pause()
                    else:
                        # 如果不是视频播放器，调用父类的默认处理
                        super().keyPressEvent(event)
                except ImportError:
                    # 如果无法导入VideoPlayer，调用父类的默认处理
                    super().keyPressEvent(event)
            else:
                # 如果没有统一预览器，调用父类的默认处理
                super().keyPressEvent(event)
        else:
            # 其他按键事件，交给父类处理
            super().keyPressEvent(event)
    
    def _apply_title_bar_theme(self):
        """
        应用窗口标题栏主题（深色/浅色模式）
        使用 Windows DWM API 设置标题栏颜色跟随系统/应用主题
        """
        try:
            import ctypes
            from ctypes import wintypes

            # 获取窗口句柄
            hwnd = int(self.winId())

            # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Windows 10 1903+)
            # DWMWA_USE_IMMERSIVE_DARK_MODE = 19 (Windows 10 1809)
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20

            # 获取当前主题模式
            app = QApplication.instance()
            is_dark_mode = False
            if hasattr(app, 'settings_manager'):
                is_dark_mode = app.settings_manager.get_setting("appearance.theme", "default") == "dark"

            # 设置深色模式属性 (1 = 启用深色, 0 = 禁用深色/使用浅色)
            dark_mode_value = wintypes.BOOL(1 if is_dark_mode else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(dark_mode_value),
                ctypes.sizeof(dark_mode_value)
            )

        except Exception as e:
            # 如果设置失败（非Windows系统或DWM API不可用），静默忽略
            pass

    def focusInEvent(self, event):
        """
        处理焦点进入事件
        - 确保组件获得焦点时能够接收键盘事件
        """
        super().focusInEvent(event)
        
    def resizeEvent(self, event):
        """
        处理窗口大小变化事件
        - Qt会自动处理DPI变化
        - 监听窗口尺寸变化，稳定后重新计算卡片尺寸
        """
        super().resizeEvent(event)
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(50, self._on_resize_stabilized)
    
    def _on_resize_stabilized(self):
        """
        窗口尺寸稳定后的回调
        - 使用连续检测机制确保窗口尺寸已完全稳定
        """
        self._check_and_update_cards(retry_count=0)
    
    def _check_and_update_cards(self, retry_count=0):
        """
        检测并更新卡片尺寸
        - 连续检测窗口尺寸是否稳定
        """
        if not hasattr(self, 'file_selector_a') or not self.file_selector_a:
            return
        
        if not hasattr(self.file_selector_a, '_update_all_cards_width'):
            return
        
        container = self.file_selector_a.files_container
        current_width = container.width()
        
        if current_width <= 0:
            max_retries = 15
            if retry_count < max_retries:
                from PyQt5.QtCore import QTimer
                from PyQt5.QtWidgets import QApplication
                QApplication.processEvents()
                QTimer.singleShot(30, lambda: self._check_and_update_cards(retry_count + 1))
            return
        
        self.file_selector_a._update_all_cards_width()
    
    def changeEvent(self, event):
        """
        处理窗口状态变化事件
        - 监听窗口最大化/窗口化状态变化
        - 状态变化时重新计算文件选择器卡片尺寸
        """
        if event.type() == QEvent.WindowStateChange:
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(200, self._on_window_state_changed)
        super().changeEvent(event)
    
    def _on_window_state_changed(self):
        """
        窗口状态变化后的回调
        - 延迟执行确保布局完成
        - 连续检测直到窗口尺寸稳定
        """
        from PyQt5.QtWidgets import QApplication
        QApplication.processEvents()
        self._check_and_update_cards(retry_count=0)
    
    def _create_file_selector_widget(self):
        """
        创建内嵌式文件选择器组件
        
        Returns:
            QWidget: 内嵌式文件选择器组件
        """
        # 直接返回自定义文件选择器组件实例
        return CustomFileSelector()
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 创建中央部件
        self.central_widget = QWidget()
        # 获取主题颜色
        app = QApplication.instance()
        auxiliary_color = "#f1f3f5"  # 默认辅助色
        normal_color = "#e0e0e0"  # 默认普通色
        base_color = "#212121"  # 默认基础色
        if hasattr(app, 'settings_manager'):
            auxiliary_color = app.settings_manager.get_setting("appearance.colors.auxiliary_color", "#f1f3f5")  # 辅助色
            normal_color = app.settings_manager.get_setting("appearance.colors.normal_color", "#e0e0e0")  # 普通色
            base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#212121")  # 基础色
        self.central_widget.setStyleSheet(f"background-color: {auxiliary_color};")
        self.setCentralWidget(self.central_widget)
        
        # 创建主布局：标题 + 三列
        main_layout = QVBoxLayout(self.central_widget)
        # 设置间距和边距
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)



        # 创建三列布局，使用QSplitter实现可拖动分割
        splitter = QSplitter(Qt.Horizontal)
        splitter.setContentsMargins(0, 0, 0, 0)
        
        # 左侧列：文件选择器A
        self.left_column = QWidget()
        self.left_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 设置边框圆角
        border_radius = 8
        self.left_column.setStyleSheet(f"background-color: {base_color}; border: 1px solid {normal_color}; border-radius: {border_radius}px;")
        left_layout = QVBoxLayout(self.left_column)


        
        # 内嵌文件选择器A
        self.file_selector_a = self._create_file_selector_widget()
        left_layout.addWidget(self.file_selector_a)
        
        # 中间列：文件临时存储池
        self.middle_column = QWidget()
        self.middle_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.middle_column.setStyleSheet(f"background-color: {base_color}; border: 1px solid {normal_color}; border-radius: {border_radius}px;")
        middle_layout = QVBoxLayout(self.middle_column)
        
        # 添加文件临时存储池组件
        self.file_staging_pool = FileStagingPool()
        middle_layout.addWidget(self.file_staging_pool)
        
        # 右侧列：统一文件预览器
        self.right_column = QWidget()
        self.right_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.right_column.setStyleSheet(f"background-color: {base_color}; border: 1px solid {normal_color}; border-radius: {border_radius}px;")
        right_layout = QVBoxLayout(self.right_column)
        
        # 统一文件预览器
        self.unified_previewer = UnifiedPreviewer(self)
        right_layout.addWidget(self.unified_previewer, 1)
        
        # 将三列添加到分割器，调整初始比例
        splitter.addWidget(self.left_column)
        splitter.addWidget(self.middle_column)
        splitter.addWidget(self.right_column)
        
        # 设置分割器初始大小，将三个板块宽度默认值设定为比值334（3:3:4）
        # 计算总宽度（使用逻辑像素）
        total_width = self.window_width - 40  # 减去边距和边框宽度
        # 根据3:3:4的比例分配宽度
        left_width = int(total_width * (3/10))
        middle_width = int(total_width * (3/10))
        right_width = int(total_width * (4/10))
        sizes = [left_width, middle_width, right_width]
        #print(f"[DEBUG] 三列初始宽度比例: 3:3:4")
        #print(f"[DEBUG] 三列初始宽度: {left_width}, {middle_width}, {right_width}")
        splitter.setSizes(sizes)
        
        # 连接文件选择器的左键点击信号到预览器
        self.file_selector_a.file_selected.connect(self.unified_previewer.set_file)
        
        # 连接文件选择器的选中状态变化信号到存储池（自动添加/移除）
        self.file_selector_a.file_selection_changed.connect(self.handle_file_selection_changed)
        
        # 连接文件临时存储池的信号到预览器
        self.file_staging_pool.item_right_clicked.connect(self.unified_previewer.set_file)
        # 添加左键点击信号连接，用于预览
        self.file_staging_pool.item_left_clicked.connect(self.unified_previewer.set_file)
        
        # 连接文件临时存储池的信号到处理方法，用于从文件选择器中删除文件
        self.file_staging_pool.remove_from_selector.connect(self.handle_remove_from_selector)
        
        # 连接文件临时存储池的信号到处理方法，用于通知文件选择器文件已被添加到储存池
        self.file_staging_pool.file_added_to_pool.connect(self.handle_file_added_to_pool)
        
        # 连接文件临时存储池的导航信号到处理方法，用于更新文件选择器的路径
        self.file_staging_pool.navigate_to_path.connect(self.handle_navigate_to_path)
        
        # 添加分割器到主布局
        main_layout.addWidget(splitter, 1)
        
        # 创建状态标签和全局设置按钮的布局
        status_container = QWidget()
        status_container_layout = QVBoxLayout(status_container)
        status_container_layout.setContentsMargins(0, 0, 0, 0)
        status_container_layout.setAlignment(Qt.AlignCenter)
        
        # 创建状态标签和全局设置按钮的水平布局
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建GitHub按钮，使用svg图标
        from freeassetfilter.widgets.button_widgets import CustomButton
        github_icon_path = get_resource_path('freeassetfilter/icons/github.svg')
        self.github_button = CustomButton(github_icon_path, button_type="normal", display_mode="icon", height=20, tooltip_text="跳转项目主页")
        self.github_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        # 连接到GitHub跳转函数
        def open_github():
            import webbrowser
            webbrowser.open("https://github.com/Dorufoc/FreeAssetFilter")
        self.github_button.clicked.connect(open_github)
        status_layout.addWidget(self.github_button)
        
        # 添加左侧占位符，将状态标签推到居中位置
        status_layout.addStretch()
        
        # 状态标签
        self.status_label = QLabel("FreeAssetFilter Alpha | By Dorufoc & renmoren | 遵循MIT协议开源")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFont(self.global_font)
        # 设置字体大小和边距，应用DPI缩放因子
        app = QApplication.instance()
        dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        font_size = int(8 * dpi_scale)
        margin = 0
        self.status_label.setStyleSheet(f"font-size: {font_size}px; color: #888888; margin-top: {margin}px;")
        status_layout.addWidget(self.status_label)
        
        # 添加右侧占位符，将全局设置按钮推到右侧
        status_layout.addStretch()
        
        # 创建全局设置按钮，使用svg图标
        from freeassetfilter.widgets.button_widgets import CustomButton
        setting_icon_path = get_resource_path('freeassetfilter/icons/setting.svg')
        self.global_settings_button = CustomButton(setting_icon_path, button_type="normal", display_mode="icon", height=20, tooltip_text="全局设置")
        self.global_settings_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        # 连接到全局设置函数
        def open_global_settings():
            if hasattr(self, 'unified_previewer') and hasattr(self.unified_previewer, '_open_global_settings'):
                self.unified_previewer._open_global_settings()
        self.global_settings_button.clicked.connect(open_global_settings)
        status_layout.addWidget(self.global_settings_button)
        
        # 将水平布局添加到容器的垂直布局中
        status_container_layout.addLayout(status_layout)
        
        # 添加状态容器到主布局
        main_layout.addWidget(status_container)
        
        # 初始化自定义悬浮提示
        from freeassetfilter.widgets.hover_tooltip import HoverTooltip
        self.hover_tooltip = HoverTooltip(self)
        # 将GitHub按钮和全局设置按钮添加为目标控件
        self.hover_tooltip.set_target_widget(self.github_button)
        self.hover_tooltip.set_target_widget(self.global_settings_button)
        #print(f"[DEBUG] 状态标签设置字体: {self.status_label.font().family()}")
        
        # 自定义窗口演示按钮已移至组件启动器，此处隐藏
        
        # 初始化完成后，检查是否需要恢复上次的文件列表
        # 移到window.show()之后执行，确保主面板先显示
        
        # 应用主题设置
        self.update_theme()
    
    def show_info(self, title, message):
        """
        显示信息提示
        
        Args:
            title (str): 提示标题
            message (str): 提示消息
        """
        # 简单的信息显示，使用状态标签
        self.status_label.setText(f"{title}: {message}")
    
    def _backup_ui_state(self):
        """
        备份当前UI状态到JSON文件，包括文件选择器路径和文件存储池信息
        
        Returns:
            bool: 是否成功备份
        """
        import json
        import os
        from datetime import datetime
        
        try:
            backup_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
            os.makedirs(backup_dir, exist_ok=True)
            
            backup_file = os.path.join(backup_dir, 'ui_state_backup.json')
            
            backup_data = {
                'timestamp': datetime.now().isoformat(),
                'file_selector': {
                    'current_path': None,
                    'selected_files': {}
                },
                'file_staging_pool': {
                    'items': []
                },
                'splitter_sizes': [100, 100, 100]
            }
            
            old_file_selector = getattr(self, 'file_selector_a', None)
            old_staging_pool = getattr(self, 'file_staging_pool', None)
            
            if old_file_selector:
                try:
                    if hasattr(old_file_selector, 'current_path'):
                        backup_data['file_selector']['current_path'] = old_file_selector.current_path
                    if hasattr(old_file_selector, 'selected_files'):
                        selected = old_file_selector.selected_files
                        if isinstance(selected, dict):
                            backup_data['file_selector']['selected_files'] = {
                                k: list(v) for k, v in selected.items()
                            }
                except (RuntimeError, AttributeError):
                    pass
            
            if old_staging_pool:
                try:
                    if hasattr(old_staging_pool, 'items'):
                        backup_data['file_staging_pool']['items'] = list(old_staging_pool.items)
                except (RuntimeError, AttributeError):
                    pass
            
            if hasattr(self, '_splitter'):
                try:
                    backup_data['splitter_sizes'] = list(self._splitter.sizes())
                except (RuntimeError, AttributeError):
                    pass
            
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception:
            return False
    
    def _restore_ui_state(self):
        """
        从JSON文件恢复UI状态，包括文件选择器路径和文件存储池信息
        
        Returns:
            bool: 是否成功恢复
        """
        import json
        import os
        
        try:
            backup_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'ui_state_backup.json')
            
            if not os.path.exists(backup_file):
                return False
            
            with open(backup_file, 'r', encoding='utf-8') as f:
                backup_data = json.load(f)
            
            new_file_selector = getattr(self, 'file_selector_a', None)
            new_staging_pool = getattr(self, 'file_staging_pool', None)
            
            if new_file_selector:
                try:
                    if 'current_path' in backup_data['file_selector']:
                        new_file_selector.current_path = backup_data['file_selector']['current_path']
                    if 'selected_files' in backup_data['file_selector']:
                        raw_selected = backup_data['file_selector']['selected_files']
                        if isinstance(raw_selected, dict):
                            new_file_selector.selected_files = {
                                k: set(v) if isinstance(v, list) else v
                                for k, v in raw_selected.items()
                            }
                    if hasattr(new_file_selector, '_refresh_file_list'):
                        new_file_selector._refresh_file_list()
                except (RuntimeError, AttributeError):
                    pass
            
            if new_staging_pool:
                try:
                    if 'items' in backup_data['file_staging_pool']:
                        items_data = backup_data['file_staging_pool']['items']
                        if hasattr(new_staging_pool, 'add_file'):
                            for item_data in items_data:
                                try:
                                    if isinstance(item_data, dict) and 'path' in item_data:
                                        if item_data not in new_staging_pool.items:
                                            new_staging_pool.add_file(item_data)
                                except Exception:
                                    continue
                except (RuntimeError, AttributeError):
                    pass
            
            if 'splitter_sizes' in backup_data and hasattr(self, '_splitter'):
                try:
                    old_sizes = backup_data['splitter_sizes']
                    if sum(old_sizes) > 0:
                        self._splitter.setSizes(old_sizes)
                except (RuntimeError, AttributeError):
                    pass
            
            return True
        except Exception:
            return False
    
    def _rebuild_main_layout(self):
        """
        重建主布局，用于主题切换时确保所有组件使用正确样式
        """
        app = QApplication.instance()
        if app is None:
            return False
        
        if not self.isVisible():
            return False
        
        if hasattr(app, 'global_font'):
            self.global_font = QFont(app.global_font)
            self.setFont(self.global_font)
        
        self._backup_ui_state()
        
        auxiliary_color = app.settings_manager.get_setting("appearance.colors.auxiliary_color", "#f1f3f5")
        normal_color = app.settings_manager.get_setting("appearance.colors.normal_color", "#e0e0e0")
        base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#212121")
        border_radius = 8
        
        old_central_widget = getattr(self, 'central_widget', None)
        old_staging_pool = getattr(self, 'file_staging_pool', None)
        old_file_selector = getattr(self, 'file_selector_a', None)
        old_preview_items = []
        old_selected_files = []

        if old_staging_pool and hasattr(old_staging_pool, '_all_items'):
            try:
                old_preview_items = list(old_staging_pool._all_items)
            except (RuntimeError, AttributeError):
                pass
        
        if old_file_selector and hasattr(old_file_selector, 'selected_files'):
            try:
                old_selected_files = list(old_file_selector.selected_files)
            except (RuntimeError, AttributeError):
                pass
        
        old_splitter_sizes = [100, 100, 100]
        if hasattr(self, '_splitter'):
            try:
                old_splitter_sizes = list(self._splitter.sizes())
            except (RuntimeError, AttributeError):
                pass
        
        try:
            if old_central_widget:
                old_central_widget.deleteLater()
        except (RuntimeError, AttributeError):
            pass
        
        self.central_widget = QWidget()
        self.central_widget.setStyleSheet(f"background-color: {auxiliary_color};")
        self.setCentralWidget(self.central_widget)
        
        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        splitter = QSplitter(Qt.Horizontal)
        splitter.setContentsMargins(0, 0, 0, 0)
        self._splitter = splitter
        
        self.left_column = QWidget()
        self.left_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.left_column.setStyleSheet(f"background-color: {base_color}; border: 1px solid {normal_color}; border-radius: {border_radius}px;")
        left_layout = QVBoxLayout(self.left_column)
        
        self.file_selector_a = self._create_file_selector_widget()
        left_layout.addWidget(self.file_selector_a)
        
        self.middle_column = QWidget()
        self.middle_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.middle_column.setStyleSheet(f"background-color: {base_color}; border: 1px solid {normal_color}; border-radius: {border_radius}px;")
        middle_layout = QVBoxLayout(self.middle_column)
        
        self.file_staging_pool = FileStagingPool()
        middle_layout.addWidget(self.file_staging_pool)
        
        self.right_column = QWidget()
        self.right_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.right_column.setStyleSheet(f"background-color: {base_color}; border: 1px solid {normal_color}; border-radius: {border_radius}px;")
        right_layout = QVBoxLayout(self.right_column)
        
        self.unified_previewer = UnifiedPreviewer(self)
        right_layout.addWidget(self.unified_previewer, 1)
        
        splitter.addWidget(self.left_column)
        splitter.addWidget(self.middle_column)
        splitter.addWidget(self.right_column)
        
        total_width = self.window_width - 40
        left_width = int(total_width * (3/10))
        middle_width = int(total_width * (3/10))
        right_width = int(total_width * (4/10))
        splitter.setSizes([left_width, middle_width, right_width])
        
        self.file_selector_a.file_selected.connect(self.unified_previewer.set_file)
        self.file_selector_a.file_selection_changed.connect(self.handle_file_selection_changed)
        self.file_staging_pool.item_right_clicked.connect(self.unified_previewer.set_file)
        self.file_staging_pool.item_left_clicked.connect(self.unified_previewer.set_file)
        self.file_staging_pool.remove_from_selector.connect(self.handle_remove_from_selector)
        
        main_layout.addWidget(splitter, 1)
        
        status_container = QWidget()
        status_container_layout = QVBoxLayout(status_container)
        status_container_layout.setContentsMargins(0, 0, 0, 0)
        status_container_layout.setAlignment(Qt.AlignCenter)
        
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)
        
        from freeassetfilter.widgets.button_widgets import CustomButton
        github_icon_path = get_resource_path('freeassetfilter/icons/github.svg')
        self.github_button = CustomButton(github_icon_path, button_type="normal", display_mode="icon", height=20, tooltip_text="跳转项目主页")
        self.github_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        def open_github():
            import webbrowser
            webbrowser.open("https://github.com/Dorufoc/FreeAssetFilter")
        self.github_button.clicked.connect(open_github)
        status_layout.addWidget(self.github_button)
        
        status_layout.addStretch()
        
        self.status_label = QLabel("FreeAssetFilter Alpha | By Dorufoc & renmoren | 遵循MIT协议开源")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFont(self.global_font)
        # 设置字体大小，应用DPI缩放因子
        app = QApplication.instance()
        dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        font_size = int(8 * dpi_scale)
        self.status_label.setStyleSheet(f"font-size: {font_size}px; color: #888888; margin-top: 0px;")
        status_layout.addWidget(self.status_label)
        
        status_layout.addStretch()
        
        setting_icon_path = get_resource_path('freeassetfilter/icons/setting.svg')
        self.global_settings_button = CustomButton(setting_icon_path, button_type="normal", display_mode="icon", height=20, tooltip_text="全局设置")
        self.global_settings_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        def open_global_settings():
            if hasattr(self, 'unified_previewer') and hasattr(self.unified_previewer, '_open_global_settings'):
                self.unified_previewer._open_global_settings()
        self.global_settings_button.clicked.connect(open_global_settings)
        status_layout.addWidget(self.global_settings_button)
        
        status_container_layout.addLayout(status_layout)
        main_layout.addWidget(status_container)
        
        from freeassetfilter.widgets.hover_tooltip import HoverTooltip
        self.hover_tooltip = HoverTooltip(self)
        self.hover_tooltip.set_target_widget(self.github_button)
        self.hover_tooltip.set_target_widget(self.global_settings_button)
        
        try:
            if old_preview_items:
                for item in old_preview_items:
                    if hasattr(self.file_staging_pool, '_all_items'):
                        if item not in self.file_staging_pool._all_items:
                            try:
                                self.file_staging_pool._all_items.append(item)
                                self.file_staging_pool._update_staging_area()
                            except (RuntimeError, AttributeError):
                                pass
            
            if old_selected_files and hasattr(self.file_selector_a, 'selected_files'):
                try:
                    self.file_selector_a.selected_files = list(old_selected_files)
                    self.file_selector_a._refresh_file_list()
                except (RuntimeError, AttributeError):
                    pass
            
            if sum(old_splitter_sizes) > 0:
                splitter.setSizes(old_splitter_sizes)
        except (RuntimeError, AttributeError):
            pass
        
        self._restore_ui_state()
        
        return True
    
    def update_theme(self, delayed=False):
        """
        更新应用主题，通过重建主布局确保所有组件使用正确样式
        
        Args:
            delayed: 是否延迟执行，用于防止在窗口关闭时调用
        """
        if not delayed and self._update_theme_in_progress:
            if not self._theme_update_queued:
                self._theme_update_queued = True
                QTimer.singleShot(50, lambda: self.update_theme(delayed=True))
            return
        
        self._update_theme_in_progress = True
        self._theme_update_queued = False
        
        # 清除SVG颜色缓存，确保新组件使用最新的主题颜色
        SvgRenderer._invalidate_color_cache()

        try:
            success = self._rebuild_main_layout()
            if not success:
                self._update_theme_in_progress = False
                return
        except (RuntimeError, AttributeError):
            pass
        finally:
            self._update_theme_in_progress = False

        # 更新窗口标题栏主题
        self._apply_title_bar_theme()
    
    def show_custom_window_demo(self):
        """
        演示自定义窗口的使用
        """
        # 设置窗口大小
        window_width = 400
        window_height = 300
        
        # 创建自定义窗口实例，并将其赋值给self，防止被垃圾回收
        self.custom_window = CustomWindow("自定义窗口演示", self)
        self.custom_window.setGeometry(200, 200, window_width, window_height)
        
        # 添加示例控件
        
        # 1. 添加标题标签
        title_label = QLabel("这是一个自定义窗口")
        title_size = 18
        title_margin = 16
        title_label.setStyleSheet(f"""
            QLabel {{
                font-size: {title_size}px;
                font-weight: 600;
                color: #333333;
                margin-bottom: {title_margin}px;
                text-align: center;
            }}
        """)
        self.custom_window.add_widget(title_label)
        
        # 2. 添加说明文本
        info_label = QLabel("这个窗口具有以下特点：\n\n" \
                            "• 纯白圆角矩形外观\n" \
                            "• 右上角圆形关闭按钮\n" \
                            "• 可拖拽移动（通过标题栏）\n" \
                            "• 支持内嵌其他控件\n" \
                            "• 带阴影效果")
        info_size = 14
        info_margin = 24
        info_label.setStyleSheet(f"""
            QLabel {{
                font-size: {info_size}px;
                color: #666666;
                line-height: 1.6;
                margin-bottom: {info_margin}px;
            }}
        """)
        info_label.setWordWrap(True)
        self.custom_window.add_widget(info_label)
        
        # 3. 添加自定义按钮
        demo_button = CustomButton("示例按钮")
        demo_button.clicked.connect(lambda: QMessageBox.information(self.custom_window, "提示", "自定义按钮被点击了！"))
        self.custom_window.add_widget(demo_button)
        
        # 显示窗口
        self.custom_window.show()
    
    def handle_file_selection_changed(self, file_info, is_selected):
        """
        处理文件选择状态变化事件
        
        Args:
            file_info (dict): 文件信息
            is_selected (bool): 是否被选中
        """
        import datetime
        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            print(f"[{timestamp}] [handle_file_selection_changed] {msg}")
        
        file_path = os.path.normpath(file_info['path'])
        debug(f"文件选择状态变化: 路径={file_path}, 选中={is_selected}")
        
        if is_selected:
            existing_paths = [os.path.normpath(item['path']) for item in self.file_staging_pool.items]
            debug(f"储存池现有路径: {existing_paths}")
            if file_path not in existing_paths:
                debug(f"文件不在储存池中，准备添加")
                self.file_staging_pool.add_file(file_info)
            else:
                debug(f"文件已在储存池中，跳过添加")
        else:
            debug(f"取消选中，准备从储存池移除")
            self.file_staging_pool.remove_file(file_path)
    
    def handle_remove_from_selector(self, file_info):
        """
        从文件选择器中删除文件（取消选中状态）
        
        Args:
            file_info (dict): 文件信息
        """
        import datetime
        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            print(f"[{timestamp}] [handle_remove_from_selector] {msg}")
        
        file_path = os.path.normpath(file_info['path'])
        file_dir = os.path.normpath(os.path.dirname(file_path))
        debug(f"从选择器移除文件: 路径={file_path}, 目录={file_dir}")
        debug(f"移除前的selected_files: {self.file_selector_a.selected_files}")
        
        if file_dir in self.file_selector_a.selected_files:
            self.file_selector_a.selected_files[file_dir].discard(file_path)
            debug(f"从集合中移除文件，剩余文件: {self.file_selector_a.selected_files[file_dir]}")
            
            if not self.file_selector_a.selected_files[file_dir]:
                del self.file_selector_a.selected_files[file_dir]
                debug(f"目录集合为空，删除目录条目")
        
        debug(f"移除后的selected_files: {self.file_selector_a.selected_files}")
        debug(f"调用_update_file_selection_state")
        self.file_selector_a._update_file_selection_state()
    
    def handle_navigate_to_path(self, path, file_info=None):
        """
        处理导航到指定路径的请求，更新文件选择器的当前路径
        
        Args:
            path (str): 要导航到的路径
            file_info (dict, optional): 文件信息，如果提供则导航后将其添加到暂存池
        """
        if hasattr(self, 'file_selector_a') and self.file_selector_a:
            path = os.path.normpath(path)
            self.file_selector_a.current_path = path
            
            def on_files_refreshed():
                if file_info:
                    self.file_staging_pool.add_file(file_info)
                self.file_selector_a._update_file_selection_state()
            
            self.file_selector_a.refresh_files(callback=on_files_refreshed)
    
    def handle_file_added_to_pool(self, file_info):
        """
        处理文件被添加到储存池的事件，将文件添加到文件选择器的选中文件列表中
        
        Args:
            file_info (dict): 文件信息
        """
        file_path = os.path.normpath(file_info['path'])
        file_dir = os.path.normpath(os.path.dirname(file_path))
        
        if file_dir not in self.file_selector_a.selected_files:
            self.file_selector_a.selected_files[file_dir] = set()
        
        if file_path not in self.file_selector_a.selected_files[file_dir]:
            self.file_selector_a.selected_files[file_dir].add(file_path)
            
            def on_files_refreshed():
                self.file_selector_a._update_file_selection_state()
            
            if self.file_selector_a.current_path == file_dir:
                if self.file_selector_a._is_loading:
                    self.file_selector_a._refresh_callback = on_files_refreshed
                else:
                    self.file_selector_a._update_file_selection_state()
            else:
                self.file_selector_a._update_file_selection_state()
    
    def check_and_restore_backup(self):
        """
        检查是否存在备份文件，并根据设置决定是否自动恢复或询问用户
        注意：只恢复文件存储池，文件选择器的状态由其他模块处理
        """
        from freeassetfilter.widgets.D_widgets import CustomMessageBox
        import os
        import json

        backup_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'staging_pool_backup.json')

        if os.path.exists(backup_file):
            with open(backup_file, 'r', encoding='utf-8') as f:
                backup_data = json.load(f)

            items = backup_data.get('items', []) if isinstance(backup_data, dict) else backup_data

            if items:
                auto_restore = True
                app = QApplication.instance()
                if hasattr(app, 'settings_manager'):
                    auto_restore = app.settings_manager.get_setting("file_staging.auto_restore_records", True)

                if auto_restore:
                    self.restore_backup(backup_data)
                else:
                    confirm_msg = CustomMessageBox(self)
                    confirm_msg.set_title("恢复上次选中内容")
                    confirm_msg.set_text(f"检测到上次有 {len(items)} 个文件在文件存储池中，是否恢复？")
                    confirm_msg.set_buttons(["是", "否"], Qt.Horizontal, ["primary", "normal"])

                    is_confirmed = False

                    def on_confirm_clicked(button_index):
                        nonlocal is_confirmed
                        is_confirmed = (button_index == 0)
                        confirm_msg.close()

                    confirm_msg.buttonClicked.connect(on_confirm_clicked)
                    confirm_msg.exec_()

                    if is_confirmed:
                        self.restore_backup(backup_data)
    
    def restore_backup(self, backup_data):
        """
        从备份数据恢复文件存储池内容，包含文件存在性校验
        注意：只恢复文件存储池，不处理文件选择器的状态
        
        Args:
            backup_data (dict or list): 备份数据，可以是包含items和selector_state的字典，或旧格式的文件列表
        """
        import os
        
        # 处理不同格式的备份数据
        items = backup_data.get('items', []) if isinstance(backup_data, dict) else backup_data
        
        # 恢复文件到存储池，并检查文件是否存在
        success_count = 0
        unlinked_files = []
        
        for file_info in items:
            # 检查文件是否存在
            if os.path.exists(file_info["path"]):
                # 添加到文件存储池
                self.file_staging_pool.add_file(file_info)
                success_count += 1
            else:
                # 添加到未链接文件列表
                unlinked_files.append({
                    "original_file_info": file_info,
                    "status": "unlinked",  # unlinked, ignored, linked
                    "new_path": None,
                    "md5": self.file_staging_pool.calculate_md5(file_info["path"]) if os.path.exists(file_info["path"]) else None
                })
        
        # 如果有未链接文件，显示处理对话框
        if unlinked_files:
            self.file_staging_pool.show_unlinked_files_dialog(unlinked_files)
    
    def show_info(self, title, message):
        """
        显示信息提示
        
        Args:
            title (str): 提示标题
            message (str): 提示消息
        """
        # 简单的信息显示，使用状态标签
        self.status_label.setText(f"{title}: {message}")

def main():
    """
    主程序入口函数
    """
    print("=== FreeAssetFilter 主程序 ===")
    
    # 修改sys.argv[0]以确保Windows任务栏显示正确图标
    sys.argv[0] = os.path.abspath(__file__)
    
    # 在Windows系统上设置应用程序身份，确保任务栏显示正确图标
    if sys.platform == 'win32':
        import ctypes
        # 加载Windows API库
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FreeAssetFilter.App")
        
        # 设置DPI感知级别
        try:
            # 尝试设置为每显示器DPI感知v2（Windows 10 1607及以上版本支持）
            user32 = ctypes.windll.user32
            # PROCESS_PER_MONITOR_DPI_AWARE_V2 = 2
            # PROCESS_PER_MONITOR_DPI_AWARE = 1
            # PROCESS_SYSTEM_DPI_AWARE = 1
            # PROCESS_DPI_UNAWARE = 0
            
            # 尝试使用SetProcessDpiAwarenessContext API（Windows 10 1607及以上版本）
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = 0x3
            SetProcessDpiAwarenessContext = user32.SetProcessDpiAwarenessContext
            SetProcessDpiAwarenessContext.restype = ctypes.c_void_p
            SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = 0x3
            result = SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
            if result == 0:
                # 如果失败，尝试使用SetProcessDpiAwareness API（Windows 8.1及以上版本）
                shcore = ctypes.windll.shcore
                SetProcessDpiAwareness = shcore.SetProcessDpiAwareness
                SetProcessDpiAwareness.restype = ctypes.c_long
                SetProcessDpiAwareness.argtypes = [ctypes.c_int]
                PROCESS_PER_MONITOR_DPI_AWARE = 2
                SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
                #print("[DEBUG] 设置为每显示器DPI感知模式")
            else:
                1==1
                #print("[DEBUG] 设置为每显示器DPI感知v2模式")
        except (AttributeError, OSError) as e:
            # 如果上述API都不可用，尝试使用SetProcessDPIAware（Windows Vista及以上版本）
            try:
                user32 = ctypes.windll.user32
                SetProcessDPIAware = user32.SetProcessDPIAware
                SetProcessDPIAware.restype = ctypes.c_bool
                SetProcessDPIAware()
                #print("[DEBUG] 设置为系统DPI感知模式")
            except (AttributeError, OSError) as e2:
                1==1
                #print(f"[DEBUG] 设置DPI感知失败: {e2}")
    
    # 设置DPI相关属性
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    
    app = QApplication(sys.argv)
    
    # 设置全局DPI缩放因子为系统缩放的1.5倍
    screen = QApplication.primaryScreen()
    logical_dpi = screen.logicalDotsPerInch()
    physical_dpi = screen.physicalDotsPerInch()
    system_scale = physical_dpi / logical_dpi if logical_dpi > 0 else 1.0
    app.dpi_scale_factor = system_scale * 1.5
    
    # 设置应用程序图标，用于任务栏显示
    icon_path = get_resource_path('freeassetfilter/icons/FAF-main.ico')
    app.setWindowIcon(QIcon(icon_path))
    
    # 导入设置管理器
    from freeassetfilter.core.settings_manager import SettingsManager
    
    # 检测并设置全局字体
    from PyQt5.QtGui import QFontDatabase, QFont
    font_db = QFontDatabase()
    font_families = font_db.families()
    
    # 加载 FiraCode-VF 字体（用于代码高亮显示）
    firacode_font_path = get_resource_path('freeassetfilter/icons/FiraCode-VF.ttf')
    firacode_font_family = None
    if os.path.exists(firacode_font_path):
        font_id = QFontDatabase.addApplicationFont(firacode_font_path)
        if font_id != -1:
            firacode_font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
    
    # 初始化设置管理器
    settings_manager = SettingsManager()
    
    # 从设置管理器中获取字体设置
    DEFAULT_FONT_SIZE = settings_manager.get_setting("font.size", 8)  # 基础字体大小，可统一调整
    saved_font_style = settings_manager.get_setting("font.style", "Microsoft YaHei")  # 从设置中获取保存的字体样式
    
    # 检查保存的字体是否可用，如果不可用则回退到微软雅黑
    selected_font = saved_font_style
    if selected_font not in font_families:
        # 保存的字体不可用，尝试使用微软雅黑
        yahei_fonts = ["Microsoft YaHei", "Microsoft YaHei UI"]
        for font_name in yahei_fonts:
            if font_name in font_families:
                selected_font = font_name
                break
        
        # 如果微软雅黑也不可用，则使用系统默认字体
        if selected_font not in font_families:
            selected_font = None
    
    if selected_font:
        # 设置全局字体，使用Regular字重(QFont.Normal)
        app.setFont(QFont(selected_font, DEFAULT_FONT_SIZE, QFont.Normal))
        # 设置全局字体变量
        global_font = QFont(selected_font, DEFAULT_FONT_SIZE, QFont.Normal)
    else:
        # 使用系统默认字体
        global_font = QFont()
        global_font.setPointSize(DEFAULT_FONT_SIZE)
        global_font.setWeight(QFont.Normal)
    
    # 将默认字体大小存储到app对象中，方便其他组件访问
    app.default_font_size = DEFAULT_FONT_SIZE
    
    # 将设置管理器存储到app对象中，方便其他组件访问
    app.settings_manager = settings_manager
    
    # 将全局字体存储到app对象中，方便其他组件访问
    app.global_font = global_font
    
    # 将 FiraCode 字体族名存储到app对象中，供代码高亮模式使用
    app.firacode_font_family = firacode_font_family
    
    # 根据当前主题动态设置全局滚动条样式
    theme = settings_manager.get_setting("appearance.theme", "default")
    if theme == "dark":
        scroll_area_bg = "#2D2D2D"
        scrollbar_bg = "#3C3C3C"
        scrollbar_handle = "#555555"
        scrollbar_handle_hover = "#666666"
    else:
        scroll_area_bg = "#ffffff"
        scrollbar_bg = "#f0f0f0"
        scrollbar_handle = "#c0c0c0"
        scrollbar_handle_hover = "#a0a0a0"
    
    # 生成滚动条样式
    scrollbar_style = """
        /* 滚动区域样式 */
        QScrollArea {
            background-color: %s;
            border: none;
        }
        
        /* 垂直滚动条样式 */
        QScrollBar:vertical {
            width: 8px;
            background: %s;
            border-radius: 3px;
        }
        
        QScrollBar::handle:vertical {
            background: %s;
            border-radius: 3px;
        }
        
        QScrollBar::handle:vertical:hover {
            background: %s;
        }
        
        QScrollBar::sub-line:vertical,
        QScrollBar::add-line:vertical {
            height: 0px;
        }
        
        /* 水平滚动条样式 */
        QScrollBar:horizontal {
            height: 8px;
            background: %s;
            border-radius: 3px;
        }
        
        QScrollBar::handle:horizontal {
            background: %s;
            border-radius: 3px;
        }
        
        QScrollBar::handle:horizontal:hover {
            background: %s;
        }
        
        QScrollBar::sub-line:horizontal,
        QScrollBar::add-line:horizontal {
            width: 0px;
        }
    """ % (scroll_area_bg, scrollbar_bg, scrollbar_handle, scrollbar_handle_hover, 
              scrollbar_bg, scrollbar_handle, scrollbar_handle_hover)
    
    # 设置全局滚动条样式
    app.setStyleSheet(scrollbar_style)
    
    # 检查并执行缩略图缓存自动清理
    if settings_manager.get_setting("file_selector.auto_clear_thumbnail_cache", True):
        from freeassetfilter.core.thumbnail_cleaner import get_thumbnail_cleaner
        thumbnail_cleaner = get_thumbnail_cleaner()
        
        # 获取缓存清理周期（天）
        cache_cleanup_period = settings_manager.get_setting("file_selector.cache_cleanup_period", 7)
        
        # 获取上次清理时间
        last_cleanup_time = settings_manager.get_setting("file_selector.last_cleanup_time", None)
        
        # 获取当前时间
        current_time = time.time()
        
        # 检查是否需要清理缓存
        if last_cleanup_time is None or (current_time - last_cleanup_time) > (cache_cleanup_period * 86400):
            # 执行缓存清理
            deleted_count, remaining_count = thumbnail_cleaner.clean_thumbnails(cleanup_period_days=cache_cleanup_period)
            #print(f"[DEBUG] 自动清理缩略图缓存: 删除了 {deleted_count} 个文件，剩余 {remaining_count} 个文件")
            
            # 更新上次清理时间
            settings_manager.set_setting("file_selector.last_cleanup_time", current_time)
            settings_manager.save_settings()
    
    window = FreeAssetFilterApp()
    # 应用主题设置
    window.update_theme()
    # 窗口启动时窗口化显示
    window.show()
    # 窗口显示后再检查并恢复文件列表，确保主面板先显示
    window.check_and_restore_backup()
    
    # 应用程序退出前记录当前时间
    def on_app_exit():
        import json
        import os
        
        # 记录程序退出时间
        exit_time = time.time()
        
        # 直接操作JSON文件，只更新app.last_exit_time字段，避免保存整个设置文件
        settings_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'settings.json')
        
        try:
            # 如果设置文件存在，只更新app.last_exit_time字段
            if os.path.exists(settings_file):
                with open(settings_file, 'r', encoding='utf-8') as f:
                    settings_data = json.load(f)
                
                # 确保app部分存在
                if 'app' not in settings_data:
                    settings_data['app'] = {}
                
                # 更新退出时间
                settings_data['app']['last_exit_time'] = exit_time
                
                # 保存更新后的设置
                with open(settings_file, 'w', encoding='utf-8') as f:
                    json.dump(settings_data, f, indent=4, ensure_ascii=False)
            else:
                # 文件不存在时，仍然记录时间但不创建文件（遵循原有逻辑）
                settings_manager.set_setting("app.last_exit_time", exit_time)
                
        except Exception as e:
            # 发生错误时，使用原有方式记录时间（不保存）
            settings_manager.set_setting("app.last_exit_time", exit_time)
            print(f"保存退出时间失败: {e}")
            pass
    
    # 连接应用程序退出信号
    app.aboutToQuit.connect(on_app_exit)
    
    sys.exit(app.exec_())

# 主程序入口
if __name__ == "__main__":
    main()