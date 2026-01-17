#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter - 桌面EXE图标获取与显示测试

功能：获取桌面上所有.exe文件的图标，并在PyQt5界面中显示
"""

import os
import sys

# 添加项目根目录到Python路径，确保能导入freeassetfilter模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QGridLayout, QLabel, QScrollArea, QFrame
)
from PyQt5.QtGui import QPixmap, QFont
from PyQt5.QtCore import Qt

# 导入项目中的图标处理工具
from freeassetfilter.utils.icon_utils import get_highest_resolution_icon, get_all_icons_from_exe, hicon_to_pixmap, DestroyIcon

class DesktopExeIconViewer(QMainWindow):
    """
    桌面EXE图标查看器主窗口类
    """
    
    def __init__(self):
        super().__init__()
        
        # 设置窗口标题
        self.setWindowTitle("桌面EXE图标查看器")
        
        # 设置窗口大小
        self.setGeometry(100, 100, 1000, 700)
        
        # 创建中央部件
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        # 创建主布局
        self.main_layout = QVBoxLayout(self.central_widget)
        
        # 创建标题标签
        self.title_label = QLabel("桌面上的EXE文件图标")
        self.title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setMargin(10)
        self.main_layout.addWidget(self.title_label)
        
        # 创建滚动区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.main_layout.addWidget(self.scroll_area)
        
        # 创建滚动区域的内容部件
        self.scroll_content = QWidget()
        self.scroll_area.setWidget(self.scroll_content)
        
        # 创建网格布局用于显示图标
        self.icon_grid = QGridLayout(self.scroll_content)
        self.icon_grid.setSpacing(10)
        self.icon_grid.setContentsMargins(10, 10, 10, 10)
        
        # 获取并显示桌面可执行文件和快捷方式图标
        self.display_desktop_executable_icons()
    
    def get_desktop_path(self):
        """
        获取当前用户的桌面路径
        
        返回:
            str: 桌面路径
        """
        return os.path.join(os.path.expanduser("~"), "Desktop")
    
    def get_desktop_exe_files(self):
        """
        获取桌面上所有的.exe和.lnk文件
        
        返回:
            list: 可执行文件和快捷方式的路径列表
        """
        desktop_path = self.get_desktop_path()
        target_files = []
        
        try:
            # 遍历桌面目录
            for filename in os.listdir(desktop_path):
                file_path = os.path.join(desktop_path, filename)
                
                # 检查是否为文件且扩展名是.exe或.lnk
                if os.path.isfile(file_path):
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in [".exe", ".lnk"]:
                        target_files.append(file_path)
        except Exception as e:
            print(f"获取桌面文件时出错: {e}")
        
        return target_files
    
    def display_desktop_executable_icons(self):
        """
        获取并显示桌面可执行文件和快捷方式的所有可用图标
        """
        # 获取桌面可执行文件和快捷方式
        exe_files = self.get_desktop_exe_files()
        
        if not exe_files:
            no_files_label = QLabel("桌面上没有找到EXE文件或快捷方式")
            no_files_label.setFont(QFont("Microsoft YaHei", 14))
            no_files_label.setAlignment(Qt.AlignCenter)
            self.icon_grid.addWidget(no_files_label, 0, 0)
            return
        
        # 创建应用实例引用
        app = QApplication.instance()
        
        total_icons = 0
        processed_files = 0
        
        # 显示图标
        row = 0
        col = 0
        max_cols = 4  # 每行最多显示4个图标
        
        for file_path in exe_files:
            processed_files += 1
            try:
                # 获取文件名（不含路径和扩展名）
                filename = os.path.basename(file_path)
                name_without_ext = os.path.splitext(filename)[0]
                
                # 获取文件扩展名
                _, ext = os.path.splitext(file_path)
                ext = ext.lower()
                
                if ext == '.lnk':
                    # 处理快捷方式文件
                    # 获取最高分辨率的图标
                    hicon = get_highest_resolution_icon(file_path, desired_size=256)
                    
                    if hicon:
                        # 将HICON转换为QPixmap
                        pixmap = hicon_to_pixmap(hicon, 256, app)
                        
                        # 释放图标句柄
                        DestroyIcon(hicon)
                        
                        if pixmap:
                            # 获取图标的原始尺寸
                            orig_width = pixmap.width()
                            orig_height = pixmap.height()
                            
                            # 创建图标显示部件
                            icon_widget = QWidget()
                            icon_widget.setFixedSize(180, 220)
                            icon_layout = QVBoxLayout(icon_widget)
                            
                            # 创建图标标签
                            icon_label = QLabel()
                            icon_label.setPixmap(pixmap)
                            icon_label.setAlignment(Qt.AlignCenter)
                            icon_label.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
                            icon_label.setFixedSize(128, 128)
                            
                            # 创建文件名标签
                            name_label = QLabel(f"{name_without_ext} (.lnk)")
                            name_label.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
                            name_label.setAlignment(Qt.AlignCenter)
                            name_label.setWordWrap(True)
                            name_label.setFixedWidth(170)
                            
                            # 创建图标尺寸标签
                            size_label = QLabel(f"{orig_width}x{orig_height}")
                            size_label.setFont(QFont("Microsoft YaHei", 9))
                            size_label.setAlignment(Qt.AlignCenter)
                            size_label.setStyleSheet("color: #888888;")
                            size_label.setFixedWidth(170)
                            
                            # 添加到布局
                            icon_layout.addWidget(icon_label)
                            icon_layout.addWidget(name_label)
                            icon_layout.addWidget(size_label)
                            icon_layout.setAlignment(Qt.AlignCenter)
                            
                            # 添加到网格布局
                            self.icon_grid.addWidget(icon_widget, row, col)
                            
                            # 更新行列位置
                            col += 1
                            if col >= max_cols:
                                col = 0
                                row += 1
                            
                            total_icons += 1
                elif ext == '.exe':
                    # 处理EXE文件，获取所有可用图标
                    all_icons = get_all_icons_from_exe(file_path)
                    
                    # 如果获取失败，回退到单个图标获取
                    if not all_icons:
                        hicon = get_highest_resolution_icon(file_path, desired_size=256)
                        if hicon:
                            # 将HICON转换为QPixmap
                            pixmap = hicon_to_pixmap(hicon, 256, app)
                            
                            # 获取图标的原始尺寸
                            orig_width = pixmap.width()
                            orig_height = pixmap.height()
                            
                            # 创建临时图标信息
                            icon_info = {"hicon": hicon, "index": 0, "width": orig_width, "height": orig_height}
                            all_icons = [icon_info]
                            
                            # 注意：这里不释放hicon，因为后面会在循环中处理释放
                    
                    if all_icons:
                        # 去重处理，避免显示相同尺寸的重复图标
                        seen_sizes = set()
                        unique_icons = []
                        
                        for icon_info in all_icons:
                            size_key = (icon_info["width"], icon_info["height"])
                            if size_key not in seen_sizes:
                                seen_sizes.add(size_key)
                                unique_icons.append(icon_info)
                        
                        for i, icon_info in enumerate(unique_icons):
                            # 将HICON转换为QPixmap
                            pixmap = hicon_to_pixmap(icon_info["hicon"], max(icon_info["width"], icon_info["height"]), app)
                            
                            # 释放图标句柄
                            DestroyIcon(icon_info["hicon"])
                            
                            if pixmap:
                                # 创建图标显示部件
                                icon_widget = QWidget()
                                icon_widget.setFixedSize(180, 220)
                                icon_layout = QVBoxLayout(icon_widget)
                                
                                # 创建图标标签
                                icon_label = QLabel()
                                icon_label.setPixmap(pixmap)
                                icon_label.setAlignment(Qt.AlignCenter)
                                icon_label.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
                                icon_label.setFixedSize(128, 128)
                                
                                # 创建文件名标签
                                if len(unique_icons) == 1:
                                    name_text = f"{name_without_ext} (.exe)"
                                else:
                                    name_text = f"{name_without_ext} (图标{i})"
                                
                                name_label = QLabel(name_text)
                                name_label.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
                                name_label.setAlignment(Qt.AlignCenter)
                                name_label.setWordWrap(True)
                                name_label.setFixedWidth(170)
                                
                                # 创建图标尺寸标签
                                size_label = QLabel(f"{icon_info['width']}x{icon_info['height']}")
                                size_label.setFont(QFont("Microsoft YaHei", 9))
                                size_label.setAlignment(Qt.AlignCenter)
                                size_label.setStyleSheet("color: #888888;")
                                size_label.setFixedWidth(170)
                                
                                # 添加到布局
                                icon_layout.addWidget(icon_label)
                                icon_layout.addWidget(name_label)
                                icon_layout.addWidget(size_label)
                                icon_layout.setAlignment(Qt.AlignCenter)
                                
                                # 添加到网格布局
                                self.icon_grid.addWidget(icon_widget, row, col)
                                
                                # 更新行列位置
                                col += 1
                                if col >= max_cols:
                                    col = 0
                                    row += 1
                                
                                total_icons += 1
            
            except Exception as e:
                print(f"处理文件 {file_path} 时出错: {e}")
                continue
        
        # 更新标题标签
        self.title_label.setText(f"桌面上的图标: {processed_files} 个文件, 共 {total_icons} 个图标")

def main():
    """
    主函数
    """
    # 在创建QApplication之前设置DPI缩放
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    
    # 创建应用实例
    app = QApplication(sys.argv)
    
    # 创建窗口实例
    window = DesktopExeIconViewer()
    
    # 显示窗口
    window.show()
    
    # 运行应用
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
