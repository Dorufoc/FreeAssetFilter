#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

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

# 尝试导入依赖检查所需的模块
exportlib_metadata_available = False

# 尝试使用importlib.metadata（Python 3.8+内置）
try:
    import importlib.metadata
    exportlib_metadata_available = True
except ImportError:
    # 如果内置的不可用，尝试使用importlib_metadata包（Python 3.7及以下需要）
    try:
        import importlib_metadata
        # 动态创建importlib.metadata别名
        import sys
        sys.modules['importlib.metadata'] = importlib_metadata
        exportlib_metadata_available = True
    except ImportError:
        # 如果所有方法都失败，依赖检查将无法正常工作
        exportlib_metadata_available = False

# 尝试导入版本解析模块
try:
    from packaging.version import parse
except ImportError:
    # 如果packaging不可用，使用简单的版本比较
    def parse(version_str):
        return tuple(map(int, version_str.split('.')[:3]))


def check_dependencies():
    """
    检查项目依赖是否已安装，根据requirements.txt文件
    
    Returns:
        tuple: (success, missing_deps, version_issues)
            success: bool - 是否所有依赖都满足
            missing_deps: list - 缺失的依赖列表
            version_issues: list - 版本不符合要求的依赖列表
    """
    requirements_file = os.path.join(os.path.dirname(__file__), 'requirements.txt')
    missing_deps = []
    version_issues = []
    
    try:
        with open(requirements_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        for line in lines:
            # 跳过注释行和空行
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # 移除依赖项后面的注释（如：library>=version # comment）
            if '#' in line:
                line = line.split('#', 1)[0].strip()
            
            # 解析依赖项，支持格式如：library>=version
            if '>=' in line:
                lib_name, required_version = line.split('>=', 1)
                lib_name = lib_name.strip()
                required_version = required_version.strip()
            elif '>' in line:
                lib_name, required_version = line.split('>', 1)
                lib_name = lib_name.strip()
                required_version = required_version.strip()
            elif '<=' in line:
                lib_name, required_version = line.split('<=', 1)
                lib_name = lib_name.strip()
                required_version = required_version.strip()
            elif '<' in line:
                lib_name, required_version = line.split('<', 1)
                lib_name = lib_name.strip()
                required_version = required_version.strip()
            elif '==' in line:
                lib_name, required_version = line.split('==', 1)
                lib_name = lib_name.strip()
                required_version = required_version.strip()
            else:
                # 没有版本要求
                lib_name = line.strip()
                required_version = None
            
            # 检查依赖是否已安装
            try:
                installed_version = importlib.metadata.version(lib_name)
                # 检查版本是否符合要求
                if required_version:
                    if parse(installed_version) < parse(required_version):
                        version_issues.append((lib_name, installed_version, required_version))
            except (importlib.metadata.PackageNotFoundError, NameError):
                missing_deps.append((lib_name, required_version))
            except Exception as e:
                missing_deps.append((lib_name, required_version))
        
        success = len(missing_deps) == 0 and len(version_issues) == 0
        return success, missing_deps, version_issues
        
    except Exception as e:
        print(f"读取requirements.txt文件时出错: {e}")
        return False, [], []


def show_dependency_error(missing_deps, version_issues):
    """
    显示依赖错误信息，提示用户安装缺失的依赖
    
    Args:
        missing_deps: list - 缺失的依赖列表
        version_issues: list - 版本不符合要求的依赖列表
    """
    message = "检测到项目依赖问题，请安装或更新以下依赖：\n\n"
    
    if missing_deps:
        message += "缺失的依赖：\n"
        for lib, version in missing_deps:
            if version:
                message += f"  - {lib}>= {version}\n"
            else:
                message += f"  - {lib}\n"
        message += "\n"
    
    if version_issues:
        message += "版本不符合要求的依赖：\n"
        for lib, installed, required in version_issues:
            message += f"  - {lib}: 已安装 {installed}, 要求 >= {required}\n"
    
    message += "\n安装命令：\npip install -r requirements.txt"
    
    # 使用简单的print输出，避免依赖PyQt5
    print("\n" + "="*50)
    print("依赖错误")
    print("="*50)
    print(message)
    print("="*50 + "\n")
    
    # 尝试使用PyQt5消息框显示错误
    try:
        app = QApplication.instance()
        if not app:
            # 不要在这里创建新的QApplication实例，避免与主程序冲突
            pass
        else:
            QMessageBox.warning(
                None, 
                "依赖警告", 
                message,
                QMessageBox.Ok
            )
    except Exception as e:
        # 如果PyQt5不可用，只使用print输出
        pass
    
    # 不要强制退出，让应用程序继续运行
    print("[警告] 依赖检查失败，但应用程序将继续运行，某些功能可能不可用。")

# 导入自定义文件选择器组件
from src.components.custom_file_selector import CustomFileSelector
# 导入统一文件预览器组件
from src.components.unified_previewer import UnifiedPreviewer
# 导入文件临时存储池组件
from src.components.file_staging_pool import FileStagingPool


class FreeAssetFilterApp(QMainWindow):
    """
    FreeAssetFilter 主应用程序类
    提供核心功能的主界面
    """
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FreeAssetFilter")
        self.setGeometry(100, 100, 1200, 800)
        
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
        self.status_label = QLabel("FreeAssetFilter v1.0 Alpha | BY Dorufoc & renmoren | 遵循MIT协议开源")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFont(self.global_font)
        self.status_label.setStyleSheet("font-size: 12px; color: #666; margin-top: 10px;")
        main_layout.addWidget(self.status_label)
        #print(f"[DEBUG] 状态标签设置字体: {self.status_label.font().family()}")
        
        # 初始化完成后，检查是否需要恢复上次的文件列表
        self.check_and_restore_backup()
    
    def show_info(self, title, message):
        """
        显示信息提示
        
        Args:
            title (str): 提示标题
            message (str): 提示消息
        """
        # 简单的信息显示，使用状态标签
        self.status_label.setText(f"{title}: {message}")
    
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
            current_selected = len(self.file_selector_a.selected_files.get(self.file_selector_a.current_path, set()))
            total_selected = sum(len(files) for files in self.file_selector_a.selected_files.values())
            self.file_selector_a.selected_count_label.setText(f"当前目录: {current_selected} 个，所有目录: {total_selected} 个")
        
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
        current_selected = len(self.file_selector_a.selected_files.get(self.file_selector_a.current_path, set()))
        total_selected = sum(len(files) for files in self.file_selector_a.selected_files.values())
        self.file_selector_a.selected_count_label.setText(f"当前目录: {current_selected} 个，所有目录: {total_selected} 个")
        
        # 刷新当前目录的文件显示，确保选中状态正确
        if hasattr(self.file_selector_a, 'current_path'):
            # 获取当前目录的文件列表
            current_files = self.file_selector_a._get_files()
            # 应用排序和筛选
            current_files = self.file_selector_a._sort_files(current_files)
            current_files = self.file_selector_a._filter_files(current_files)
            # 重新创建文件卡片，确保选中状态正确
            self.file_selector_a._clear_files_layout()
            self.file_selector_a._create_file_cards(current_files)
    
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
    # 检查依赖
    success, missing_deps, version_issues = check_dependencies()
    if not success:
        show_dependency_error(missing_deps, version_issues)
    
    app = QApplication(sys.argv)
    
    # 检测并设置全局字体为微软雅黑，如果系统不包含则使用默认字体
    from PyQt5.QtGui import QFontDatabase, QFont
    font_db = QFontDatabase()
    font_families = font_db.families()
    
    # 调试信息：打印系统支持的所有字体
    #print(f"[DEBUG] 系统支持的字体数量: {len(font_families)}")
    #print(f"[DEBUG] 系统字体列表: {font_families[:10]}...")  # 只打印前10个字体
    
    # 检查系统是否包含微软雅黑字体（支持Microsoft YaHei和Microsoft YaHei UI两种名称）
    yahei_fonts = ["Microsoft YaHei", "Microsoft YaHei UI"]
    selected_font = None
    for font_name in yahei_fonts:
        if font_name in font_families:
            selected_font = font_name
            break
    
    if selected_font:
        # 设置全局字体为微软雅黑
        #print(f"[DEBUG] 系统包含微软雅黑字体 ({selected_font})，设置为全局字体")
        app.setFont(QFont(selected_font))
        # 设置全局字体变量
        global_font = QFont(selected_font)
    else:
        #print(f"[DEBUG] 系统不包含微软雅黑字体，使用系统默认字体")
        # 使用系统默认字体
        global_font = QFont()
    
    # 将全局字体存储到app对象中，方便其他组件访问
    app.global_font = global_font
    
    window = FreeAssetFilterApp()
    window.show()
    sys.exit(app.exec_())