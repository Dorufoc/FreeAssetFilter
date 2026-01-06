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





import sys
import os
import warnings

# 忽略sipPyTypeDict相关的弃用警告
warnings.filterwarnings("ignore", category=DeprecationWarning, module="PyQt5")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*sipPyTypeDict.*")

# 添加父目录到Python路径，确保包能被正确导入
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from freeassetfilter.utils.path_utils import get_resource_path, get_app_data_path, get_config_path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGroupBox, QGridLayout, QSizePolicy, QSplitter, QMessageBox
)
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtGui import QFont, QIcon

# 导入自定义控件库
from freeassetfilter.widgets.custom_widgets import CustomWindow, CustomButton



# 导入自定义文件选择器组件
from freeassetfilter.components.custom_file_selector import CustomFileSelector
# 导入统一文件预览器组件
from freeassetfilter.components.unified_previewer import UnifiedPreviewer
# 导入文件临时存储池组件
from freeassetfilter.components.file_staging_pool import FileStagingPool


class FreeAssetFilterApp(QMainWindow):
    """
    FreeAssetFilter 主应用程序类
    提供核心功能的主界面
    """
    
    def __init__(self):
        super().__init__()
        
        # 获取应用实例和DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 获取屏幕尺寸
        screen = QApplication.primaryScreen()
        # 获取整个屏幕尺寸用于居中计算
        full_geometry = screen.geometry()
        full_screen_width = full_geometry.width()
        full_screen_height = full_geometry.height()
        # 获取可用屏幕尺寸用于限制窗口大小
        available_geometry = screen.availableGeometry()
        available_width = available_geometry.width()
        available_height = available_geometry.height()
        
        # 使用DPI缩放因子调整窗口大小，但不超过屏幕可用尺寸
        # 调整为更合理的基础宽度，确保有足够空间显示3列卡片，同时避免出现过多空白区域（调整为原始的一半）
        window_width = int(850 * self.dpi_scale)
        # 计算16:10比例的高度，保持宽度不变
        window_height = int(window_width * (10/16))
        
        # 确保窗口大小不超过屏幕可用尺寸
        window_width = min(window_width, available_width - 20)  # 留20px边距
        window_height = min(window_height, available_height - 20)  # 留20px边距
        
        # 计算窗口居中位置（使用整个屏幕尺寸）
        x = (full_screen_width - window_width) // 2
        y = (full_screen_height - window_height) // 2
        
        # 确保窗口不会超出可用区域
        x = max(x, available_geometry.left())
        y = max(y, available_geometry.top())
        x = min(x, available_width - window_width - 10)  # 留10px右边距
        y = min(y, available_height - window_height - 10)  # 留10px底边距
        
        self.setWindowTitle("FreeAssetFilter")
        self.setGeometry(x, y, window_width, window_height)
        
        # 设置程序图标
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons', 'FAF-main.ico')
        self.setWindowIcon(QIcon(icon_path))
        
        # 用于生成唯一的文件选择器实例ID
        self.file_selector_counter = 0
        
        # 获取全局字体并应用DPI缩放
        global_font = getattr(app, 'global_font', QFont())
        # 创建全局字体的副本，避免修改全局字体对象
        self.global_font = QFont(global_font)
        # 根据DPI缩放因子调整字体大小
        font_size = self.global_font.pointSize()
        if font_size > 0:
            scaled_size = int(font_size * self.dpi_scale)
            self.global_font.setPointSize(scaled_size)
        #print(f"\n[DEBUG] 主窗口获取到的全局字体: {self.global_font.family()}, 缩放后大小: {self.global_font.pointSize()}")
        
        # 设置窗口字体
        self.setFont(self.global_font)
        
        # 创建UI
        self.init_ui()
    
    def closeEvent(self, event):
        """
        主窗口关闭事件，确保保存文件选择器的当前路径和文件存储池状态
        """
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
            print(f"[DEBUG] 退出前自动清理缩略图缓存: 删除了 {deleted_count} 个文件，剩余 {remaining_count} 个文件")

        # 清理统一预览器中的临时PDF文件
        if hasattr(self, 'unified_previewer'):
            self.unified_previewer._clear_preview()
        
        # 统一清理：删除整个temp文件夹
        import shutil
        import os
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        temp_dir = os.path.join(project_root, "data", "temp")
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                print(f"已删除临时文件夹: {temp_dir}")
            except Exception as e:
                print(f"删除临时文件夹失败: {e}")
        
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
    
    def focusInEvent(self, event):
        """
        处理焦点进入事件
        - 确保组件获得焦点时能够接收键盘事件
        """
        super().focusInEvent(event)
    
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
        central_widget = QWidget()
        # 获取主题颜色
        app = QApplication.instance()
        background_color = "#2D2D2D"  # 默认窗口背景色
        border_color = "#3C3C3C"  # 默认窗口边框色
        if hasattr(app, 'settings_manager'):
            background_color = app.settings_manager.get_setting("appearance.colors.window_background", "#2D2D2D")
            border_color = app.settings_manager.get_setting("appearance.colors.window_border", "#3C3C3C")
        central_widget.setStyleSheet(f"background-color: {background_color};")
        self.setCentralWidget(central_widget)
        
        # 创建主布局：标题 + 三列
        main_layout = QVBoxLayout(central_widget)
        # 使用DPI缩放因子调整间距和边距
        scaled_spacing = int(10 * self.dpi_scale)
        scaled_margin = int(10 * self.dpi_scale)
        main_layout.setSpacing(scaled_spacing)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        

        
        # 创建三列布局，使用QSplitter实现可拖动分割
        splitter = QSplitter(Qt.Horizontal)
        splitter.setContentsMargins(0, 0, 0, 0)
        
        # 左侧列：文件选择器A
        left_column = QWidget()
        left_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 应用DPI缩放因子到边框圆角
        scaled_border_radius = int(8 * self.dpi_scale)
        left_column.setStyleSheet(f"background-color: {background_color}; border: 1px solid {border_color}; border-radius: {scaled_border_radius}px;")
        left_layout = QVBoxLayout(left_column)


        
        # 内嵌文件选择器A
        self.file_selector_a = self._create_file_selector_widget()
        left_layout.addWidget(self.file_selector_a)
        
        # 中间列：文件临时存储池
        middle_column = QWidget()
        middle_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        middle_column.setStyleSheet(f"background-color: {background_color}; border: 1px solid {border_color}; border-radius: {scaled_border_radius}px;")
        middle_layout = QVBoxLayout(middle_column)
        
        # 添加文件临时存储池组件
        self.file_staging_pool = FileStagingPool()
        middle_layout.addWidget(self.file_staging_pool)
        
        # 右侧列：统一文件预览器
        right_column = QWidget()
        right_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_column.setStyleSheet(f"background-color: {background_color}; border: 1px solid {border_color}; border-radius: {scaled_border_radius}px;")
        right_layout = QVBoxLayout(right_column)
        
        # 统一文件预览器
        self.unified_previewer = UnifiedPreviewer()
        right_layout.addWidget(self.unified_previewer, 1)
        
        # 将三列添加到分割器，调整初始比例
        splitter.addWidget(left_column)
        splitter.addWidget(middle_column)
        splitter.addWidget(right_column)
        
        # 使用DPI缩放因子调整分割器初始大小，确保文件选择器有足够宽度显示3列卡片（调整为原始的一半）
        # 确保文件选择器的初始宽度足够显示3列卡片
        # 中间临时存储池：适中大小
        # 右侧预览器：较大宽度，适合预览
        scaled_sizes = [int(200 * self.dpi_scale), int(150 * self.dpi_scale), int(300 * self.dpi_scale)]
        splitter.setSizes(scaled_sizes)
        
        # 连接文件选择器的信号到预览器
        self.file_selector_a.file_right_clicked.connect(self.unified_previewer.set_file)
        # 添加左键点击信号连接，用于预览
        self.file_selector_a.file_selected.connect(self.unified_previewer.set_file)
        
        # 连接文件选择器的信号到文件临时存储池，根据选择状态自动添加/删除文件
        self.file_selector_a.file_selection_changed.connect(self.handle_file_selection_changed)
        
        # 连接文件临时存储池的信号到预览器
        self.file_staging_pool.item_right_clicked.connect(self.unified_previewer.set_file)
        # 添加左键点击信号连接，用于预览
        self.file_staging_pool.item_left_clicked.connect(self.unified_previewer.set_file)
        
        # 连接文件临时存储池的信号到处理方法，用于从文件选择器中删除文件
        self.file_staging_pool.remove_from_selector.connect(self.handle_remove_from_selector)
        
        # 添加分割器到主布局
        main_layout.addWidget(splitter, 1)
        
        # 状态标签
        self.status_label = QLabel("FreeAssetFilter Alpha | By Dorufoc & renmoren | 遵循MIT协议开源")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFont(self.global_font)
        # 使用DPI缩放因子调整字体大小和边距
        scaled_font_size = int(12 * self.dpi_scale)
        scaled_margin = int(10 * self.dpi_scale)
        self.status_label.setStyleSheet(f"font-size: {scaled_font_size}px; color: #666; margin-top: {scaled_margin}px;")
        main_layout.addWidget(self.status_label)
        #print(f"[DEBUG] 状态标签设置字体: {self.status_label.font().family()}")
        
        # 自定义窗口演示按钮已移至组件启动器，此处隐藏
        
        # 初始化完成后，检查是否需要恢复上次的文件列表
        # 移到window.show()之后执行，确保主面板先显示
    
    def show_info(self, title, message):
        """
        显示信息提示
        
        Args:
            title (str): 提示标题
            message (str): 提示消息
        """
        # 简单的信息显示，使用状态标签
        self.status_label.setText(f"{title}: {message}")
    
    def update_theme(self):
        """
        更新应用主题，当主题颜色更改时调用
        """
        # 获取应用实例
        app = QApplication.instance()
        
        # 更新中央部件的背景色
        if hasattr(self, 'central_widget'):
            background_color = app.settings_manager.get_setting("appearance.colors.window_background", "#2D2D2D")
            border_color = app.settings_manager.get_setting("appearance.colors.window_border", "#3C3C3C")
            self.central_widget.setStyleSheet(f"background-color: {background_color};")
            
        # 更新三列的背景色
        columns = [getattr(self, 'left_column', None), getattr(self, 'middle_column', None), getattr(self, 'right_column', None)]
        for column in columns:
            if column:
                background_color = app.settings_manager.get_setting("appearance.colors.window_background", "#2D2D2D")
                border_color = app.settings_manager.get_setting("appearance.colors.window_border", "#3C3C3C")
                scaled_border_radius = int(8 * self.dpi_scale)
                column.setStyleSheet(f"background-color: {background_color}; border: 1px solid {border_color}; border-radius: {scaled_border_radius}px;")
        
        # 递归更新所有子组件的样式
        def update_child_widgets(widget):
            for child in widget.findChildren(QWidget):
                # 检查子组件是否有update_style方法
                if hasattr(child, 'update_style') and callable(child.update_style):
                    child.update_style()
                # 递归更新子组件的子组件
                update_child_widgets(child)
        
        update_child_widgets(self.central_widget)
        
        # 如果有统一预览器，更新其样式
        if hasattr(self, 'unified_previewer'):
            self.unified_previewer.update_style()
        
        # 如果有文件临时存储池，更新其样式
        if hasattr(self, 'file_staging_pool'):
            self.file_staging_pool.update_style()
        
        # 如果有文件选择器，更新其样式
        if hasattr(self, 'file_selector_a'):
            self.file_selector_a.update_style()
    
    def show_custom_window_demo(self):
        """
        演示自定义窗口的使用
        """
        # 使用DPI缩放因子调整窗口大小
        window_width = int(400 * self.dpi_scale)
        window_height = int(300 * self.dpi_scale)
        
        # 创建自定义窗口实例
        custom_window = CustomWindow("自定义窗口演示", self)
        custom_window.setGeometry(200, 200, window_width, window_height)
        
        # 添加示例控件
        
        # 1. 添加标题标签
        title_label = QLabel("这是一个自定义窗口")
        scaled_title_size = int(18 * self.dpi_scale)
        scaled_title_margin = int(16 * self.dpi_scale)
        title_label.setStyleSheet(f"""
            QLabel {{
                font-size: {scaled_title_size}px;
                font-weight: 600;
                color: #333333;
                margin-bottom: {scaled_title_margin}px;
                text-align: center;
            }}
        """)
        custom_window.add_widget(title_label)
        
        # 2. 添加说明文本
        info_label = QLabel("这个窗口具有以下特点：\n\n" \
                            "• 纯白圆角矩形外观\n" \
                            "• 右上角圆形关闭按钮\n" \
                            "• 可拖拽移动（通过标题栏）\n" \
                            "• 支持内嵌其他控件\n" \
                            "• 带阴影效果")
        scaled_info_size = int(14 * self.dpi_scale)
        scaled_info_margin = int(24 * self.dpi_scale)
        info_label.setStyleSheet(f"""
            QLabel {{
                font-size: {scaled_info_size}px;
                color: #666666;
                line-height: 1.6;
                margin-bottom: {scaled_info_margin}px;
            }}
        """)
        info_label.setWordWrap(True)
        custom_window.add_widget(info_label)
        
        # 3. 添加自定义按钮
        demo_button = CustomButton("示例按钮")
        demo_button.clicked.connect(lambda: QMessageBox.information(custom_window, "提示", "自定义按钮被点击了！"))
        custom_window.add_widget(demo_button)
        
        # 显示窗口
        custom_window.show()
    
    def handle_file_selection_changed(self, file_info, is_selected):
        """
        处理文件选择状态变化事件
        
        Args:
            file_info (dict): 文件信息
            is_selected (bool): 是否被选中
        """
        if is_selected:
            # 文件被选中，添加到临时存储池
            self.file_staging_pool.add_file(file_info)
        else:
            # 文件被取消选择，从临时存储池移除
            self.file_staging_pool.remove_file(file_info['path'])
    
    def handle_remove_from_selector(self, file_info):
        """
        从文件选择器中删除文件（取消选中状态）
        
        Args:
            file_info (dict): 文件信息
        """
        file_path = file_info['path']
        file_dir = os.path.dirname(file_path)
        
        # 1. 首先从selected_files中移除文件，无论是否在当前目录
        if file_dir in self.file_selector_a.selected_files:
            self.file_selector_a.selected_files[file_dir].discard(file_path)
            
            # 如果目录下没有选中的文件了，删除该目录的键
            if not self.file_selector_a.selected_files[file_dir]:
                del self.file_selector_a.selected_files[file_dir]
            
            # 更新文件选择器的选中文件计数
            #current_selected = len(self.file_selector_a.selected_files.get(self.file_selector_a.current_path, set()))
            #total_selected = sum(len(files) for files in self.file_selector_a.selected_files.values())
            #self.file_selector_a.selected_count_label.setText(f"当前目录: {current_selected} 个，所有目录: {total_selected} 个")
        
        # 2. 如果文件在当前目录显示，直接更新文件卡片的视觉状态
        if self.file_selector_a.current_path == file_dir:
            # 遍历当前目录显示的所有文件卡片，找到对应文件的卡片
            for i in range(self.file_selector_a.files_layout.count()):
                widget = self.file_selector_a.files_layout.itemAt(i).widget()
                if widget is not None and hasattr(widget, 'file_info'):
                    # 检查是否是目标文件
                    if widget.file_info['path'] == file_path:
                        # 直接更新卡片的选中状态和样式，不调用toggle_selection
                        widget.is_selected = False
                        # 应用DPI缩放因子到文件卡片样式
                        scaled_border_radius = int(8 * self.dpi_scale)
                        scaled_border_width = int(2 * self.dpi_scale)
                        scaled_padding = int(8 * self.dpi_scale)
                        widget.setStyleSheet(f"""
                            QWidget#FileCard {{
                                background-color: #f1f3f5;
                                border: {scaled_border_width}px solid #e0e0e0;
                                border-radius: {scaled_border_radius}px;
                                padding: {scaled_padding}px;
                                text-align: center;
                            }}
                            QWidget#FileCard:hover {{
                                border-color: #4a7abc;
                                background-color: #f0f8ff;
                            }}
                        """)
                        # 恢复标签样式
                        widget.name_label.setStyleSheet("background: transparent; border: none; color: #333333;")
                        widget.detail_label.setStyleSheet("background: transparent; border: none; color: #666666;")
                        if hasattr(widget, 'modified_label'):
                            widget.modified_label.setStyleSheet("background: transparent; border: none; color: #888888;")
    
    def check_and_restore_backup(self):
        """
        检查是否存在备份文件，并询问用户是否要恢复上次的文件列表和文件选择器目录
        """
        # 导入自定义消息框
        from freeassetfilter.widgets.custom_widgets import CustomMessageBox
        import os
        import json
        
        # 备份文件路径
        backup_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'staging_pool_backup.json')
        print(f"[DEBUG] 检查备份文件路径: {backup_file}")
        
        # 检查备份文件是否存在
        if os.path.exists(backup_file):
            # 读取备份文件，检查是否有内容
            with open(backup_file, 'r', encoding='utf-8') as f:
                backup_data = json.load(f)
            
            # 检查备份数据格式和内容
            items = backup_data.get('items', []) if isinstance(backup_data, dict) else backup_data
            selector_state = backup_data.get('selector_state', {}) if isinstance(backup_data, dict) else {}
            
            if items:
                # 使用自定义消息框询问用户是否恢复
                confirm_msg = CustomMessageBox(self)
                confirm_msg.set_title("恢复文件列表和目录")
                confirm_msg.set_text(f"检测到上次有 {len(items)} 个文件在文件存储池中，是否要恢复文件列表和上次打开的目录？")
                confirm_msg.set_buttons(["是", "否"], Qt.Horizontal, ["primary", "normal"])
                
                # 记录确认结果
                is_confirmed = False
                
                def on_confirm_clicked(button_index):
                    nonlocal is_confirmed
                    is_confirmed = (button_index == 0)  # 0表示确定按钮
                    confirm_msg.close()
                
                confirm_msg.buttonClicked.connect(on_confirm_clicked)
                confirm_msg.exec_()
                
                if is_confirmed:
                    self.restore_backup(backup_data)
    
    def restore_backup(self, backup_data):
        """
        从备份数据恢复文件列表和文件选择器目录，包含文件存在性校验
        
        Args:
            backup_data (dict or list): 备份数据，可以是包含items和selector_state的字典，或旧格式的文件列表
        """
        import os
        
        # 处理不同格式的备份数据
        items = backup_data.get('items', []) if isinstance(backup_data, dict) else backup_data
        selector_state = backup_data.get('selector_state', {}) if isinstance(backup_data, dict) else {}
        
        # 恢复文件到存储池，并检查文件是否存在
        success_count = 0
        unlinked_files = []
        
        for file_info in items:
            # 检查文件是否存在
            if os.path.exists(file_info["path"]):
                # 添加到文件存储池
                self.file_staging_pool.add_file(file_info)
                
                # 更新文件选择器的选中状态
                file_path = file_info['path']
                file_dir = os.path.dirname(file_path)
                
                # 确保文件选择器的selected_files字典中存在该目录
                if file_dir not in self.file_selector_a.selected_files:
                    self.file_selector_a.selected_files[file_dir] = set()
                
                # 添加到选中文件集合
                self.file_selector_a.selected_files[file_dir].add(file_path)
                
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
        
        # 检查设置是否允许恢复上次路径
        app = QApplication.instance()
        settings_manager = getattr(app, 'settings_manager')
        if settings_manager.get_setting("file_selector.restore_last_path", True):
            # 恢复文件选择器的目录
            last_path = selector_state.get('last_path', 'All')
            if last_path and (last_path == 'All' or os.path.exists(last_path)):
                self.file_selector_a.current_path = last_path
                # 刷新文件列表，显示恢复的目录内容
                self.file_selector_a.refresh_files()
            else:
                # 如果恢复的目录不存在，刷新当前目录的文件显示，确保选中状态正确
                if hasattr(self.file_selector_a, 'current_path'):
                    # 调用refresh_files方法，使用异步方式刷新文件列表
                    # 这将确保文件选择器使用后台线程读取文件，避免阻塞主线程
                    self.file_selector_a.refresh_files()
        else:
            # 如果设置不允许恢复上次路径，确保显示All界面
            self.file_selector_a.current_path = "All"
            self.file_selector_a.refresh_files()
    
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
    
    # 设置DPI相关属性
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    QApplication.setAttribute(Qt.AA_Use96Dpi)
    
    app = QApplication(sys.argv)
    
    # 设置应用程序图标，用于任务栏显示
    icon_path = get_resource_path('freeassetfilter/icons/FAF-main.ico')
    app.setWindowIcon(QIcon(icon_path))
    
    # 设置全局滚动条样式，应用到所有滚动条
    app.setStyleSheet("""
        /* 滚动区域样式 */
        QScrollArea {
            background-color: #ffffff;
            border: none;
        }
        
        /* 垂直滚动条样式 */
        QScrollBar:vertical {
            width: 8px;
            background: #f0f0f0;
            border-radius: 3px;
        }
        
        QScrollBar::handle:vertical {
            background: #c0c0c0;
            border-radius: 3px;
        }
        
        QScrollBar::handle:vertical:hover {
            background: #a0a0a0;
        }
        
        QScrollBar::sub-line:vertical,
        QScrollBar::add-line:vertical {
            height: 0px;
        }
        
        /* 水平滚动条样式 */
        QScrollBar:horizontal {
            height: 8px;
            background: #f0f0f0;
            border-radius: 3px;
        }
        
        QScrollBar::handle:horizontal {
            background: #c0c0c0;
            border-radius: 3px;
        }
        
        QScrollBar::handle:horizontal:hover {
            background: #a0a0a0;
        }
        
        QScrollBar::sub-line:horizontal,
        QScrollBar::add-line:horizontal {
            width: 0px;
        }
    """)
    
    # 导入设置管理器
    from freeassetfilter.core.settings_manager import SettingsManager
    
    # 检测并设置全局字体
    from PyQt5.QtGui import QFontDatabase, QFont
    font_db = QFontDatabase()
    font_families = font_db.families()
    
    # 初始化设置管理器
    settings_manager = SettingsManager()
    
    # 从设置管理器中获取字体设置
    DEFAULT_FONT_SIZE = settings_manager.get_setting("font.size", 20)  # 基础字体大小，可统一调整
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
    
    # 计算DPI缩放因子
    
    # 固定DPI缩放因子为0.5，禁用根据屏幕分辨率自动识别的功能
    app.dpi_scale_factor = 1.0
    # 输出调试信息
    print(f"[DEBUG] 当前DPI缩放因子: {app.dpi_scale_factor:.2f}")
    
    # 将设置管理器存储到app对象中，方便其他组件访问
    app.settings_manager = settings_manager
    
    # 将全局字体存储到app对象中，方便其他组件访问
    app.global_font = global_font
    
    # 检查并执行缩略图缓存自动清理
    if settings_manager.get_setting("file_selector.auto_clear_thumbnail_cache", True):
        from freeassetfilter.core.thumbnail_cleaner import get_thumbnail_cleaner
        thumbnail_cleaner = get_thumbnail_cleaner()
        deleted_count, remaining_count = thumbnail_cleaner.clean_thumbnails()
        print(f"[DEBUG] 自动清理缩略图缓存: 删除了 {deleted_count} 个文件，剩余 {remaining_count} 个文件")
    
    window = FreeAssetFilterApp()
    # 窗口启动时窗口化显示
    window.show()
    # 窗口显示后再检查并恢复文件列表，确保主面板先显示
    window.check_and_restore_backup()
    sys.exit(app.exec_())

# 主程序入口
if __name__ == "__main__":
    main()