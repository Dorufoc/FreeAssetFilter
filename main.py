#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v0.1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

1. 个人非商业使用：需保留本注释及开发者署名；
项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE
FreeAssetFilter 主程序
核心功能应用程序，不包含视频播放器功能
"""





import sys
import os
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
        self.setWindowTitle("FreeAssetFilter")
        self.setGeometry(100, 100, 1200, 800)
        
        # 设置程序图标
        icon_path = os.path.join(os.path.dirname(__file__), 'freeassetfilter', 'icons', 'FAF-main.ico')
        self.setWindowIcon(QIcon(icon_path))
        
        # 用于生成唯一的文件选择器实例ID
        self.file_selector_counter = 0
        
        # 获取全局字体
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        #print(f"\n[DEBUG] 主窗口获取到的全局字体: {self.global_font.family()}")
        
        # 设置窗口字体
        self.setFont(self.global_font)
        
        # 创建UI
        self.init_ui()
    
    def closeEvent(self, event):
        """
        主窗口关闭事件，确保保存文件选择器的当前路径和文件存储池状态
        """
        # 保存文件选择器A的当前路径
        if hasattr(self, 'file_selector_a'):
            self.file_selector_a.save_current_path()
        # 保存文件存储池状态
        if hasattr(self, 'file_staging_pool'):
            self.file_staging_pool.save_backup()
        # 调用父类的closeEvent
        super().closeEvent(event)
    
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
        self.setCentralWidget(central_widget)
        
        # 创建主布局：标题 + 三列
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        

        
        # 创建三列布局，使用QSplitter实现可拖动分割
        splitter = QSplitter(Qt.Horizontal)
        splitter.setContentsMargins(0, 0, 0, 0)
        
        # 左侧列：文件选择器A
        left_column = QWidget()
        left_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_column.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc; border-radius: 8px;")
        left_layout = QVBoxLayout(left_column)
        

        
        # 内嵌文件选择器A
        self.file_selector_a = self._create_file_selector_widget()
        left_layout.addWidget(self.file_selector_a)
        
        # 中间列：文件临时存储池
        middle_column = QWidget()
        middle_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        middle_column.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc; border-radius: 8px;")
        middle_layout = QVBoxLayout(middle_column)
        
        # 添加文件临时存储池组件
        self.file_staging_pool = FileStagingPool()
        middle_layout.addWidget(self.file_staging_pool)
        
        # 右侧列：统一文件预览器
        right_column = QWidget()
        right_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_column.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc; border-radius: 8px;")
        right_layout = QVBoxLayout(right_column)
        

        
        # 统一文件预览器
        self.unified_previewer = UnifiedPreviewer()
        right_layout.addWidget(self.unified_previewer, 1)
        
        # 将三列添加到分割器，调整初始比例
        splitter.addWidget(left_column)
        splitter.addWidget(middle_column)
        splitter.addWidget(right_column)
        
        # 设置初始大小比例，对应原来的1:1:2
        splitter.setSizes([300, 300, 600])
        
        # 连接文件选择器的信号到预览器
        self.file_selector_a.file_right_clicked.connect(self.unified_previewer.set_file)
        # 添加左键点击信号连接，用于预览
        self.file_selector_a.file_selected.connect(self.unified_previewer.set_file)
        
        # 连接文件选择器的信号到文件临时存储池，根据选择状态自动添加/删除文件
        self.file_selector_a.file_selection_changed.connect(self.handle_file_selection_changed)
        
        # 连接文件临时存储池的信号到预览器
        self.file_staging_pool.item_right_clicked.connect(self.unified_previewer.set_file)
        
        # 连接文件临时存储池的信号到处理方法，用于从文件选择器中删除文件
        self.file_staging_pool.remove_from_selector.connect(self.handle_remove_from_selector)
        
        # 添加分割器到主布局
        main_layout.addWidget(splitter, 1)
        
        # 状态标签
        self.status_label = QLabel("FreeAssetFilter Alpha | By Dorufoc & renmoren | 遵循MIT协议开源")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFont(self.global_font)
        self.status_label.setStyleSheet("font-size: 12px; color: #666; margin-top: 10px;")
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
    
    def show_custom_window_demo(self):
        """
        演示自定义窗口的使用
        """
        # 创建自定义窗口实例
        custom_window = CustomWindow("自定义窗口演示", self)
        custom_window.setGeometry(200, 200, 400, 300)
        
        # 添加示例控件
        
        # 1. 添加标题标签
        title_label = QLabel("这是一个自定义窗口")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: 600;
                color: #333333;
                margin-bottom: 16px;
                text-align: center;
            }
        """)
        custom_window.add_widget(title_label)
        
        # 2. 添加说明文本
        info_label = QLabel("这个窗口具有以下特点：\n\n" \
                            "• 纯白圆角矩形外观\n" \
                            "• 右上角圆形关闭按钮\n" \
                            "• 可拖拽移动（通过标题栏）\n" \
                            "• 支持内嵌其他控件\n" \
                            "• 带阴影效果")
        info_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                color: #666666;
                line-height: 1.6;
                margin-bottom: 24px;
            }
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
                        widget.setStyleSheet("""
                            QWidget#FileCard {
                                background-color: #ffffff;
                                border: 2px solid #e0e0e0;
                                border-radius: 8px;
                                padding: 8px;
                                text-align: center;
                            }
                            QWidget#FileCard:hover {
                                border-color: #4a7abc;
                                background-color: #f0f8ff;
                            }
                        """)
                        # 恢复标签样式
                        widget.name_label.setStyleSheet("background: transparent; border: none; color: #333333;")
                        widget.detail_label.setStyleSheet("background: transparent; border: none; color: #666666;")
                        if hasattr(widget, 'modified_label'):
                            widget.modified_label.setStyleSheet("background: transparent; border: none; color: #888888;")
    
    def check_and_restore_backup(self):
        """
        检查是否存在备份文件，并询问用户是否要恢复上次的文件列表
        """
        from PyQt5.QtWidgets import QMessageBox
        import os
        import json
        
        # 备份文件路径
        backup_file = os.path.join(os.path.dirname(__file__), 'data', 'staging_pool_backup.json')
        
        # 检查备份文件是否存在
        if os.path.exists(backup_file):
            # 读取备份文件，检查是否有内容
            with open(backup_file, 'r', encoding='utf-8') as f:
                backup_data = json.load(f)
            
            if backup_data:
                # 询问用户是否恢复
                reply = QMessageBox.question(
                    self, "恢复文件列表", 
                    f"检测到上次有 {len(backup_data)} 个文件在文件存储池中，是否要恢复？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                
                if reply == QMessageBox.Yes:
                    self.restore_backup(backup_data)
    
    def restore_backup(self, backup_data):
        """
        从备份数据恢复文件列表，包含文件存在性校验
        
        Args:
            backup_data (list): 备份的文件列表数据
        """
        import os
        
        # 恢复文件到存储池，并检查文件是否存在
        success_count = 0
        unlinked_files = []
        
        for file_info in backup_data:
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
        
        # 更新文件选择器的选中文件计数
        #current_selected = len(self.file_selector_a.selected_files.get(self.file_selector_a.current_path, set()))
        #total_selected = sum(len(files) for files in self.file_selector_a.selected_files.values())
        #self.file_selector_a.selected_count_label.setText(f"当前目录: {current_selected} 个，所有目录: {total_selected} 个")
        
        # 刷新当前目录的文件显示，确保选中状态正确
        if hasattr(self.file_selector_a, 'current_path'):
            # 调用refresh_files方法，使用异步方式刷新文件列表
            # 这将确保文件选择器使用后台线程读取文件，避免阻塞主线程
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

# 主程序入口
if __name__ == "__main__":
    print("=== FreeAssetFilter 主程序 ===")
    
    # 修改sys.argv[0]以确保Windows任务栏显示正确图标
    sys.argv[0] = os.path.abspath(__file__)
    
    # 在Windows系统上设置应用程序身份，确保任务栏显示正确图标
    if sys.platform == 'win32':
        import ctypes
        # 加载Windows API库
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FreeAssetFilter.App")
    
    app = QApplication(sys.argv)
    
    # 设置应用程序图标，用于任务栏显示
    icon_path = os.path.join(os.path.dirname(__file__), 'freeassetfilter', 'icons', 'FAF-main.ico')
    app.setWindowIcon(QIcon(icon_path))
    
    # 检测并设置全局字体为微软雅黑，如果系统不包含则使用默认字体
    from PyQt5.QtGui import QFontDatabase, QFont
    font_db = QFontDatabase()
    font_families = font_db.families()
    
    # 检查系统是否包含微软雅黑字体（支持Microsoft YaHei和Microsoft YaHei UI两种名称）
    yahei_fonts = ["Microsoft YaHei", "Microsoft YaHei UI"]
    selected_font = None
    for font_name in yahei_fonts:
        if font_name in font_families:
            selected_font = font_name
            break
    
    if selected_font:
        # 设置全局字体为微软雅黑
        app.setFont(QFont(selected_font))
        # 设置全局字体变量
        global_font = QFont(selected_font)
    else:
        # 使用系统默认字体
        global_font = QFont()
    
    # 将全局字体存储到app对象中，方便其他组件访问
    app.global_font = global_font
    
    window = FreeAssetFilterApp()
    window.show()
    # 窗口显示后再检查并恢复文件列表，确保主面板先显示
    window.check_and_restore_backup()
    sys.exit(app.exec_())