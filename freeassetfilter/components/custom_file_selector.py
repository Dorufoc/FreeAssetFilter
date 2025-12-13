#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
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
from datetime import datetime

# 添加项目根目录到Python路径，解决直接运行时的导入问题
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QDialog, QApplication,
    QPushButton, QLabel, QComboBox, QLineEdit, QScrollArea,
    QHeaderView, QGroupBox, QGridLayout, QMenu, QAction,
    QFrame, QSplitter, QSizePolicy, QInputDialog, QListWidget, QProgressBar,
    QProgressDialog
)
from PyQt5.QtCore import (
    Qt, pyqtSignal, QThread, QObject, QEvent, QTimer,
    QFileInfo, QDateTime, QPoint, QSize, QRect, QRectF, QUrl
)
from PyQt5.QtGui import (
    QIcon, QPixmap, QFont, QFontMetrics, QColor, QCursor,
    QBrush, QPainter, QPen, QPalette, QImage, QFontDatabase
)
from PyQt5.QtSvg import QSvgRenderer, QSvgWidget
from freeassetfilter.utils.svg_renderer import SvgRenderer
from freeassetfilter.widgets.custom_widgets import CustomButton


class CustomFileSelector(QWidget):
    """
    自定义文件选择器组件
    使用卡片式布局，实现鼠标悬停高亮和点击选择功能
    """
    
    # 定义信号
    file_selected = pyqtSignal(dict)  # 当文件被选中时发出
    file_right_clicked = pyqtSignal(dict)  # 当文件被右键点击时发出
    file_selection_changed = pyqtSignal(dict, bool)  # 当文件选择状态改变时发出
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 获取全局字体
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        #print(f"[DEBUG] CustomFileSelector获取到的全局字体: {self.global_font.family()}")
        
        # 设置组件字体
        self.setFont(self.global_font)
        
        # 设置最小宽度，确保能容纳3列卡片
        # 计算方式：基于_calculate_max_columns方法的逻辑
        # 3个卡片实际宽度(150*3) + 左右边距(20) = 450 + 20 = 470
        # 卡片实际宽度=卡片宽度(140)+右侧间距(10)
        self.setMinimumWidth(520)
        
        # 初始化配置
        self.current_path = "All"  # 默认路径为"All"
        self.selected_files = {}  # 存储每个目录下的选中文件 {directory: {file_path1, file_path2}}]
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
        
        # 添加防抖定时器，用于减少刷新频率（在init_ui之前初始化，避免_clear_files_layout访问时出错）
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.setInterval(150)  # 150毫秒延迟，平衡响应速度和刷新频率
        self.resize_timer.timeout.connect(self.refresh_files)  # 定时器超时后刷新
        
        # 初始化UI
        self.init_ui()
        
        # 无论上次保存的路径是什么，都默认显示"All"界面
        self.current_path = "All"
        
        # 初始化文件列表
        self.refresh_files()
    
    def load_last_path(self):
        """
        从文件中加载上次打开的路径
        """
        try:
            if os.path.exists(self.save_path_file):
                with open(self.save_path_file, 'r') as f:
                    data = json.load(f)
                    # 只有当上次保存的路径存在且不是无效路径时才使用
                    if "last_path" in data:
                        last_path = data["last_path"]
                        # 检查路径是否有效（普通路径需要存在，"All"是特殊路径）
                        if last_path == "All" or os.path.exists(last_path):
                            self.current_path = last_path
        except Exception as e:
            print(f"加载上次路径失败: {e}")
            # 如果加载失败，确保默认显示"All"
            self.current_path = "All"
    
    def save_current_path(self):
        """
        保存当前路径到文件
        """
        try:
            with open(self.save_path_file, 'w') as f:
                json.dump({"last_path": self.current_path}, f)
        except Exception as e:
            print(f"保存路径失败: {e}")
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 创建主布局
        main_layout = QVBoxLayout(self)
        self.setStyleSheet("background-color: #ffffff;")
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 创建顶部控制面板
        control_panel = self._create_control_panel()
        main_layout.addWidget(control_panel)
        
        # 创建文件列表区域
        files_area = self._create_files_area()
        main_layout.addWidget(files_area, 1)
        
        # 创建底部状态栏
        status_bar = self._create_status_bar()
        main_layout.addWidget(status_bar)
    
    def _create_control_panel(self):
        """
        创建控制面板
        """
        panel = QGroupBox()
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        # 使用垂直布局来容纳多行控件
        main_layout = QVBoxLayout(panel)
        main_layout.setSpacing(5)
        main_layout.setContentsMargins(5, 5, 5, 5)
        
        # 第一行：目录选择功能
        dir_layout = QHBoxLayout()
        dir_layout.setSpacing(5)
        
        # 盘符选择器
        self.drive_combo = QComboBox()
        # 设置固定宽度，增加盘符选择器的宽度
        self.drive_combo.setFixedWidth(80)
        # 动态获取当前系统存在的盘符
        self._update_drive_list()
        self.drive_combo.activated.connect(self._on_drive_changed)
        dir_layout.addWidget(self.drive_combo)
        
        # 目录显示区域（可编辑）
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("输入路径")
        self.path_edit.returnPressed.connect(self.go_to_path)
        dir_layout.addWidget(self.path_edit, 1)
        
        # 前往按钮
        go_btn = CustomButton("前往", button_type="normal")
        go_btn.clicked.connect(self.go_to_path)
        dir_layout.addWidget(go_btn)
        
        # 收藏夹按钮
        self.favorites_btn = CustomButton("收藏夹", button_type="normal")
        self.favorites_btn.clicked.connect(self._show_favorites_dialog)
        dir_layout.addWidget(self.favorites_btn)
        
        # 返回上一次退出所在目录按钮
        self.last_path_btn = CustomButton("上次目录", button_type="normal")
        self.last_path_btn.clicked.connect(self._go_to_last_path)
        dir_layout.addWidget(self.last_path_btn)
        
        main_layout.addLayout(dir_layout)
        
        # 第二行：返回上级和刷新按钮
        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(5)
        
        # 返回上级文件夹按钮
        self.parent_btn = CustomButton("返回上级文件夹", button_type="normal")
        self.parent_btn.clicked.connect(self.go_to_parent)
        nav_layout.addWidget(self.parent_btn)
        
        # 刷新按钮
        refresh_btn = CustomButton("刷新", button_type="normal")
        refresh_btn.clicked.connect(self.refresh_files)
        nav_layout.addWidget(refresh_btn)
        
        # 添加拉伸空间
        nav_layout.addStretch(1)
        
        main_layout.addLayout(nav_layout)
        
        # 第三行：文件筛选和排序功能
        filter_sort_layout = QHBoxLayout()
        filter_sort_layout.setSpacing(5)
        
        # 文件筛选功能（正则表达式）
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("正则表达式筛选")
        self.filter_edit.returnPressed.connect(self.apply_filter)
        filter_sort_layout.addWidget(self.filter_edit, 1)
        
        # 筛选按钮
        self.filter_btn = CustomButton("筛选", button_type="normal")
        self.filter_btn.clicked.connect(self.apply_filter)
        filter_sort_layout.addWidget(self.filter_btn)
        
        # 排序形式选择
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["名称升序", "名称降序", "大小升序", "大小降序", "创建时间升序", "创建时间降序"])
        self.sort_combo.currentIndexChanged.connect(self.change_sort)
        filter_sort_layout.addWidget(self.sort_combo)
        
        main_layout.addLayout(filter_sort_layout)
        
        return panel
    
    def _create_files_area(self):
        """
        创建文件列表区域
        """
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 关闭水平滚动条
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # 垂直滚动条按需显示
        
        # 创建文件容器
        self.files_container = QWidget()
        self.files_layout = QGridLayout(self.files_container)
        self.files_layout.setSpacing(10)  # 卡片间距
        self.files_layout.setContentsMargins(10, 10, 10, 10)
        # 左对齐，以便填充整个宽度
        self.files_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        
        scroll_area.setWidget(self.files_container)
        
        # 使用事件过滤器监听滚动区域大小变化
        scroll_area.viewport().installEventFilter(self)
        # 同时监听文件容器的大小变化
        self.files_container.installEventFilter(self)
        
        return scroll_area
    
    def _create_status_bar(self):
        """
        创建状态栏
        """
        status_bar = QFrame()
        status_bar.setFrameShape(QFrame.HLine)
        status_bar.setFrameShadow(QFrame.Sunken)
        
        layout = QHBoxLayout(status_bar)
        

        
        # 生成缩略图按钮
        self.generate_thumbnails_btn = CustomButton("生成缩略图", button_type="primary")
        self.generate_thumbnails_btn.clicked.connect(self._generate_thumbnails)
        layout.addWidget(self.generate_thumbnails_btn)
        
        # 清理缩略图缓存按钮
        self.clear_thumbnails_btn = CustomButton("清理缩略图缓存", button_type="secondary")
        self.clear_thumbnails_btn.clicked.connect(self._clear_thumbnail_cache)
        layout.addWidget(self.clear_thumbnails_btn)
        
        # 选中文件计数
        #self.selected_count_label = QLabel("当前目录: 0 个，所有目录: 0 个")
        #layout.addWidget(self.selected_count_label, 1, Qt.AlignRight)
        
        return status_bar
    
    def _generate_thumbnails(self):
        """
        生成当前目录下所有照片和视频的缩略图
        """
        # 获取当前目录下的所有文件
        files = self._get_files()
        
        # 筛选出需要生成缩略图的文件（图片和视频）
        media_files = []
        # 支持的图片格式
        image_formats = ["jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "svg", "avif", "cr2", "cr3", "nef", "arw", "dng", "orf"]
        # 支持的视频格式
        video_formats = ["mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "m4v", "mpeg", "mpg", "mxf"]
        
        for file in files:
            if not file["is_dir"]:
                suffix = file["suffix"].lower()  # 转换为小写，确保不区分大小写
                # 只有图片和视频格式才生成缩略图
                if suffix in image_formats or suffix in video_formats:
                    media_files.append(file)
        
        if not media_files:
            # 当前目录下没有需要生成缩略图的媒体文件
            from freeassetfilter.widgets.custom_widgets import CustomMessageBox
            info_msg = CustomMessageBox(self)
            info_msg.set_title("提示")
            info_msg.set_text("当前目录下没有需要生成缩略图的媒体文件")
            info_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            info_msg.buttonClicked.connect(info_msg.close)
            info_msg.exec_()
            return
        
        # 筛选出需要生成缩略图的文件（缩略图不存在的文件）
        files_to_generate = []
        for file in media_files:
            thumbnail_path = self._get_thumbnail_path(file["path"])
            if not os.path.exists(thumbnail_path):
                files_to_generate.append(file)
        
        if not files_to_generate:
            # 所有文件都已有缩略图，无需重新生成
            from freeassetfilter.widgets.custom_widgets import CustomMessageBox
            info_msg = CustomMessageBox(self)
            info_msg.set_title("提示")
            info_msg.set_text("所有文件都已有缩略图，无需重新生成")
            info_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            info_msg.buttonClicked.connect(info_msg.close)
            info_msg.exec_()
            return
        
        # 使用自定义提示窗口来显示进度
        from freeassetfilter.widgets.custom_widgets import CustomMessageBox, CustomProgressBar
        
        # 创建自定义提示窗口
        progress_msg = CustomMessageBox(self)
        progress_msg.set_title("生成缩略图")
        progress_msg.set_text(f"正在生成缩略图... (0/{len(files_to_generate)})")
        
        # 创建并配置自定义进度条
        progress_bar = CustomProgressBar()
        progress_bar.setRange(0, len(files_to_generate))
        progress_bar.setValue(0)
        progress_bar.setInteractive(False)  # 禁用交互，只用于显示进度
        progress_msg.set_progress(progress_bar)
        
        # 设置只有一个取消按钮
        progress_msg.set_buttons(["取消"], Qt.Horizontal, ["normal"])
        
        # 记录是否取消的标志
        is_canceled = False
        
        # 连接取消按钮的信号
        def on_cancel_clicked():
            nonlocal is_canceled
            is_canceled = True
        
        progress_msg.buttonClicked.connect(on_cancel_clicked)
        
        # 显示自定义提示窗口
        progress_msg.show()
        
        # 开始生成缩略图
        generated_count = 0
        success_count = 0
        
        for i, file in enumerate(files_to_generate):
            # 检查是否取消
            if is_canceled:
                break
            
            try:
                # 生成缩略图
                result = self._create_thumbnail(file["path"])
                generated_count += 1
                if result:
                    success_count += 1
                
                # 更新进度条和文本
                progress_bar.setValue(generated_count)
                progress_msg.set_text(f"正在生成缩略图... ({generated_count}/{len(files_to_generate)})")
                
                # 处理事件，防止界面冻结
                QApplication.processEvents()
            except Exception as e:
                print(f"生成缩略图失败: {file['path']}, 错误: {e}")
                generated_count += 1
                progress_bar.setValue(generated_count)
                progress_msg.set_text(f"正在生成缩略图... ({generated_count}/{len(files_to_generate)})")
                QApplication.processEvents()
        
        # 关闭自定义提示窗口
        progress_msg.close()
        
        # 显示结果
        result_msg = CustomMessageBox(self)
        result_msg.set_title("提示")
        result_msg.set_text(f"缩略图生成完成！成功: {success_count}, 总数: {generated_count}")
        result_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
        result_msg.buttonClicked.connect(result_msg.close)
        result_msg.exec_()
        
        # 刷新文件列表，显示新生成的缩略图
        self.refresh_files()
        
    def _clear_thumbnail_cache(self):
        """
        清理缩略图缓存，删除所有本地存储的缩略图文件，并刷新页面显示
        """
        import shutil
        from freeassetfilter.widgets.custom_widgets import CustomMessageBox
        
        # 确认对话框
        confirm_msg = CustomMessageBox(self)
        confirm_msg.set_title("确认清理")
        confirm_msg.set_text("确定要清理所有缩略图缓存吗？这将删除所有生成的缩略图，并恢复默认图标显示。")
        confirm_msg.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])
        
        # 记录确认结果
        is_confirmed = False
        
        def on_confirm_clicked(button_index):
            nonlocal is_confirmed
            is_confirmed = (button_index == 0)  # 0表示确定按钮
            confirm_msg.close()
        
        confirm_msg.buttonClicked.connect(on_confirm_clicked)
        confirm_msg.exec_()
        
        if is_confirmed:
            try:
                # 获取缩略图存储目录
                thumb_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "thumbnails")
                
                # 检查目录是否存在
                if os.path.exists(thumb_dir):
                    # 计算要删除的文件数量
                    import glob
                    thumbnail_files = glob.glob(os.path.join(thumb_dir, "*.png"))
                    file_count = len(thumbnail_files)
                    
                    if file_count > 0:
                        # 删除目录下所有.png文件
                        for file_path in thumbnail_files:
                            if os.path.isfile(file_path):
                                os.remove(file_path)
                        
                        # 刷新文件列表，恢复默认图标显示
                        self.refresh_files()
                        
                        # 清理成功提示
                        success_msg = CustomMessageBox(self)
                        success_msg.set_title("清理成功")
                        success_msg.set_text(f"已成功清理 {file_count} 个缩略图缓存文件。")
                        success_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                        
                        def on_success_ok_clicked():
                            success_msg.close()
                        
                        success_msg.buttonClicked.connect(on_success_ok_clicked)
                        success_msg.exec_()
                    else:
                        # 缓存目录为空提示
                        empty_msg = CustomMessageBox(self)
                        empty_msg.set_title("提示")
                        empty_msg.set_text("缩略图缓存目录为空，无需清理。")
                        empty_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                        
                        def on_empty_ok_clicked():
                            empty_msg.close()
                        
                        empty_msg.buttonClicked.connect(on_empty_ok_clicked)
                        empty_msg.exec_()
                else:
                    # 缓存目录不存在提示
                    not_exist_msg = CustomMessageBox(self)
                    not_exist_msg.set_title("提示")
                    not_exist_msg.set_text("缩略图缓存目录不存在，无需清理。")
                    not_exist_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                    
                    def on_not_exist_ok_clicked():
                        not_exist_msg.close()
                    
                    not_exist_msg.buttonClicked.connect(on_not_exist_ok_clicked)
                    not_exist_msg.exec_()
            except Exception as e:
                print(f"清理缩略图缓存失败: {e}")
                # 清理失败错误提示
                error_msg = CustomMessageBox(self)
                error_msg.set_title("错误")
                error_msg.set_text(f"清理缩略图缓存失败: {e}")
                error_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                
                def on_error_ok_clicked():
                    error_msg.close()
                
                error_msg.buttonClicked.connect(on_error_ok_clicked)
                error_msg.exec_()
    
    def _create_thumbnail(self, file_path):
        """
        为单个文件创建缩略图
        """
        try:
            import cv2
            
            suffix = os.path.splitext(file_path)[1].lower()
            thumbnail_path = self._get_thumbnail_path(file_path)
            
            image_formats = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".svg", ".avif"]
            # 支持的raw格式
            raw_formats = [".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf"]
            
            if suffix in image_formats or suffix in raw_formats:
                # 处理图片文件
                try:
                    from PIL import Image, ImageDraw
                    
                    if suffix in raw_formats:
                        # 使用rawpy处理raw图像
                        import rawpy
                        import numpy as np
                        
                        with rawpy.imread(file_path) as raw:
                            # 处理raw图像，使用默认参数
                            rgb = raw.postprocess()
                        
                        # 将numpy数组转换为PIL Image
                        img = Image.fromarray(rgb)
                    else:
                        # 使用PIL打开普通图片
                        img = Image.open(file_path)
                    
                    # 转换为RGBA模式，支持透明背景
                    img = img.convert("RGBA")
                    
                    # 计算原始宽高比
                    original_width, original_height = img.size
                    aspect_ratio = original_width / original_height
                    
                    # 计算新尺寸，保持原始比例，最大尺寸为128x128
                    if aspect_ratio > 1:
                        # 宽图，以宽度为基准
                        new_width = 128
                        new_height = int(new_width / aspect_ratio)
                    else:
                        # 高图或正方形，以高度为基准
                        new_height = 128
                        new_width = int(new_height * aspect_ratio)
                    
                    # 调整大小，保持原始比例
                    resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    
                    # 创建一个128x128的透明背景
                    thumbnail = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
                    
                    # 将调整大小后的图片居中绘制到透明背景上
                    draw = ImageDraw.Draw(thumbnail)
                    x_offset = (128 - new_width) // 2
                    y_offset = (128 - new_height) // 2
                    thumbnail.paste(resized_img, (x_offset, y_offset), resized_img)
                    
                    # 保存缩略图为PNG格式
                    thumbnail.save(thumbnail_path, format='PNG', quality=85)
                    print(f"已生成图片缩略图 (PIL保持比例): {file_path}")
                    return True
                except Exception as pil_e:
                    print(f"无法生成缩略图: {file_path}, PIL处理失败: {pil_e}")
                    return False
            # 处理所有视频文件格式
            else:
                print(f"开始生成视频缩略图: {file_path}")
                cap = cv2.VideoCapture(file_path)
                if cap.isOpened():
                    try:
                        # 获取视频总帧数
                        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                        print(f"视频总帧数: {total_frames}")
                        
                        # 定义尝试的帧位置列表
                        frame_positions = []
                        
                        # 计算有效的帧位置，确保不使用第0帧
                        min_valid_frame = 1  # 最小有效帧（不使用第0帧）
                        max_valid_frame = max(min_valid_frame, total_frames - 1) if total_frames > 1 else min_valid_frame
                        
                        # 如果能获取到有效帧数，添加多个帧位置，优先使用中间帧
                        if total_frames > 10:
                            # 优先使用中间帧
                            middle_frame = total_frames // 2
                            frame_positions.append(middle_frame)  # 中间帧
                            
                            # 添加其他优质帧位置
                            frame_positions.append(middle_frame - 10)  # 中间帧前10帧
                            frame_positions.append(middle_frame + 10)  # 中间帧后10帧
                            frame_positions.append(total_frames // 3)  # 1/3处
                            frame_positions.append(total_frames // 4)  # 1/4处
                            frame_positions.append(total_frames // 5 * 4)  # 4/5处
                        elif total_frames > 5:
                            # 帧数较少时，尝试多个位置
                            frame_positions.append(total_frames // 2)  # 中间帧
                            frame_positions.append(total_frames // 3)  # 1/3处
                            frame_positions.append(total_frames - 1)  # 最后一帧
                        
                        # 添加安全的fallback帧位置，不使用第0帧
                        frame_positions.append(1)   # 第1帧
                        frame_positions.append(5)   # 第5帧
                        frame_positions.append(10)  # 第10帧
                        
                        # 过滤无效帧位置，确保只尝试有效的帧
                        valid_frame_positions = []
                        for pos in frame_positions:
                            # 确保帧位置在有效范围内
                            if pos >= min_valid_frame and pos <= max_valid_frame:
                                valid_frame_positions.append(pos)
                        
                        # 去重
                        valid_frame_positions = list(set(valid_frame_positions))
                        
                        # 优先使用中间帧，将中间帧放在列表开头
                        if total_frames > 10:
                            middle_frame = total_frames // 2
                            if middle_frame in valid_frame_positions:
                                # 移除中间帧并将其放在列表开头
                                valid_frame_positions.remove(middle_frame)
                                valid_frame_positions.insert(0, middle_frame)
                        
                        print(f"尝试的有效帧位置: {valid_frame_positions}")
                        
                        # 尝试从不同位置读取帧
                        success = False
                        for frame_pos in valid_frame_positions:
                            # 设置帧位置
                            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
                            
                            # 读取帧
                            ret, frame = cap.read()
                            if ret and frame is not None and frame.shape[0] > 0 and frame.shape[1] > 0:
                                try:
                                    # 计算原始宽高比
                                    original_height, original_width = frame.shape[:2]
                                    aspect_ratio = original_width / original_height
                                    
                                    # 计算新尺寸，保持原始比例，最大尺寸为128x128
                                    if aspect_ratio > 1:
                                        # 宽图，以宽度为基准
                                        new_width = 128
                                        new_height = int(new_width / aspect_ratio)
                                    else:
                                        # 高图或正方形，以高度为基准
                                        new_height = 128
                                        new_width = int(new_height * aspect_ratio)
                                    
                                    # 调整大小，保持原始比例
                                    resized_frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)
                                    
                                    # 使用PIL处理，避免cv2.zeros错误
                                    from PIL import Image, ImageDraw
                                    
                                    # 将OpenCV图像转换为PIL图像
                                    # OpenCV图像是BGR格式，需要转换为RGB格式
                                    frame_pil = Image.fromarray(cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB))
                                    
                                    # 创建一个128x128的透明背景
                                    thumbnail = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
                                    
                                    # 将调整大小后的帧居中绘制到透明背景上
                                    x_offset = (128 - new_width) // 2
                                    y_offset = (128 - new_height) // 2
                                    thumbnail.paste(frame_pil, (x_offset, y_offset))
                                    
                                    # 保存缩略图
                                    thumbnail.save(thumbnail_path, format='PNG', quality=85)
                                    print(f"✓ 使用PIL保存缩略图成功")
                                    print(f"✓ 已生成视频缩略图: {file_path}, 使用第 {frame_pos} 帧，保持原始比例")
                                    success = True
                                    return True
                                except Exception as e:
                                    print(f"✗ 处理视频时出错: {file_path}, 错误: {e}")
                                break
                        
                        if not success:
                            # 如果所有尝试都失败，尝试使用相对位置
                            print(f"所有固定帧位置尝试失败，尝试使用相对位置")
                            # 尝试从视频中间位置读取（使用不同方法）
                            cap.set(cv2.CAP_PROP_POS_AVI_RATIO, 0.5)  # 设置到视频中间位置
                            ret, frame = cap.read()
                            if ret and frame is not None and frame.shape[0] > 0 and frame.shape[1] > 0:
                                try:
                                    # 计算原始宽高比
                                    original_height, original_width = frame.shape[:2]
                                    aspect_ratio = original_width / original_height
                                    
                                    # 计算新尺寸，保持原始比例，最大尺寸为128x128
                                    if aspect_ratio > 1:
                                        # 宽图，以宽度为基准
                                        new_width = 128
                                        new_height = int(new_width / aspect_ratio)
                                    else:
                                        # 高图或正方形，以高度为基准
                                        new_height = 128
                                        new_width = int(new_height * aspect_ratio)
                                    
                                    # 调整大小，保持原始比例
                                    resized_frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)
                                    
                                    # 使用PIL处理，避免cv2.zeros错误
                                    from PIL import Image, ImageDraw
                                    
                                    # 将OpenCV图像转换为PIL图像
                                    # OpenCV图像是BGR格式，需要转换为RGB格式
                                    frame_pil = Image.fromarray(cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB))
                                    
                                    # 创建一个128x128的透明背景
                                    thumbnail = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
                                    
                                    # 将调整大小后的帧居中绘制到透明背景上
                                    x_offset = (128 - new_width) // 2
                                    y_offset = (128 - new_height) // 2
                                    thumbnail.paste(frame_pil, (x_offset, y_offset))
                                    
                                    # 保存缩略图
                                    thumbnail.save(thumbnail_path, format='PNG', quality=85)
                                    print(f"✓ 已生成视频缩略图: {file_path}, 使用中间位置相对帧")
                                    return True
                                except Exception as e:
                                    print(f"✗ 使用PIL处理视频帧失败: {e}")
                            else:
                                print(f"✗ 无法读取视频任何有效帧")
                    except Exception as e:
                        print(f"✗ 处理视频时出错: {file_path}, 错误: {e}")
                        # 尝试使用相对位置作为最后的 fallback
                        try:
                            cap.set(cv2.CAP_PROP_POS_AVI_RATIO, 0.5)  # 设置到视频中间位置
                            ret, frame = cap.read()
                            if ret and frame is not None and frame.shape[0] > 0 and frame.shape[1] > 0:
                                # 计算原始宽高比
                                original_height, original_width = frame.shape[:2]
                                aspect_ratio = original_width / original_height
                                
                                # 计算新尺寸，保持原始比例，最大尺寸为128x128
                                if aspect_ratio > 1:
                                    # 宽图，以宽度为基准
                                    new_width = 128
                                    new_height = int(new_width / aspect_ratio)
                                else:
                                    # 高图或正方形，以高度为基准
                                    new_height = 128
                                    new_width = int(new_height * aspect_ratio)
                                
                                # 调整大小，保持原始比例
                                resized_frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)
                                
                                # 使用PIL处理
                                try:
                                    from PIL import Image, ImageDraw
                                    
                                    # 将OpenCV图像转换为PIL图像
                                    # OpenCV图像是BGR格式，需要转换为RGB格式
                                    frame_pil = Image.fromarray(cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB))
                                    
                                    # 创建一个128x128的透明背景
                                    thumbnail_pil = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
                                    
                                    # 将调整大小后的帧居中绘制到透明背景上
                                    x_offset = (128 - new_width) // 2
                                    y_offset = (128 - new_height) // 2
                                    thumbnail_pil.paste(frame_pil, (x_offset, y_offset))
                                    
                                    # 保存缩略图
                                    thumbnail_pil.save(thumbnail_path, format='PNG', quality=85)
                                    print(f"✓ 已生成视频缩略图: {file_path}, 使用相对位置帧")
                                    return True
                                except Exception as pil_e:
                                    print(f"✗ 使用PIL处理视频帧失败: {pil_e}")
                            else:
                                print(f"✗ 无法读取视频任何有效帧")
                        except Exception as fallback_e:
                            print(f"✗ Fallback尝试也失败: {fallback_e}")
                    finally:
                        # 确保释放资源
                        cap.release()
                else:
                    print(f"✗ 无法打开视频文件: {file_path}")
        except ImportError:
            # 如果没有安装OpenCV，跳过缩略图生成
            print("OpenCV is not installed")
        except Exception as e:
            # 处理其他可能的错误
            print(f"生成缩略图失败: {file_path}, 错误: {e}")
        return False
    
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
            self.current_path = "All"
            self.refresh_files()
        else:
            # 否则，执行原有的返回上级目录逻辑
            parent_dir = os.path.dirname(self.current_path)
            if parent_dir and parent_dir != self.current_path:
                self.current_path = parent_dir
                self.refresh_files()
    
    def _load_favorites(self):
        """
        从文件中加载收藏夹列表
        """
        try:
            if os.path.exists(self.favorites_file):
                with open(self.favorites_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载收藏夹失败: {e}")
        return []
    
    def _save_favorites(self):
        """
        保存收藏夹列表到文件
        """
        try:
            with open(self.favorites_file, 'w', encoding='utf-8') as f:
                json.dump(self.favorites, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存收藏夹失败: {e}")
    
    def _show_favorites_dialog(self):
        """
        显示收藏夹对话框
        """
        # 创建对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("收藏夹")
        dialog.setMinimumSize(400, 300)
        
        # 创建布局
        layout = QVBoxLayout(dialog)
        
        # 创建收藏夹列表
        favorites_list = QListWidget()
        for favorite in self.favorites:
            favorites_list.addItem(favorite['name'] + ' - ' + favorite['path'])
        
        # 双击列表项跳转到对应路径
        favorites_list.itemDoubleClicked.connect(lambda item: self._on_favorite_double_clicked(item, dialog))
        
        # 右键菜单
        favorites_list.setContextMenuPolicy(Qt.CustomContextMenu)
        favorites_list.customContextMenuRequested.connect(lambda pos: self._show_favorite_context_menu(pos, favorites_list))
        
        layout.addWidget(favorites_list)
        
        # 创建底部按钮布局
        btn_layout = QHBoxLayout()
        
        # 添加当前路径到收藏夹按钮
        add_btn = QPushButton("添加当前路径到收藏夹")
        font = add_btn.font()
        font.setPointSize(8)
        add_btn.setFont(font)
        add_btn.clicked.connect(lambda: self._add_current_path_to_favorites(dialog, favorites_list))
        btn_layout.addWidget(add_btn)
        
        # 关闭按钮
        close_btn = QPushButton("关闭")
        font = close_btn.font()
        font.setPointSize(8)
        close_btn.setFont(font)
        close_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
        
        # 显示对话框
        dialog.exec_()
    
    def _on_favorite_double_clicked(self, item, dialog):
        """
        双击收藏夹项时跳转到对应路径
        """
        text = item.text()
        # 提取路径（假设格式为 "名称 - 路径"）
        if ' - ' in text:
            path = text.split(' - ', 1)[1]
            if os.path.exists(path):
                self.current_path = path
                self.refresh_files()
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
                    # 弹出输入框获取新名称
                    new_name, ok = QInputDialog.getText(self, "重命名", "请输入新名称:", text=old_name)
                    if ok and new_name:
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
            from freeassetfilter.widgets.custom_widgets import CustomMessageBox
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
            confirm_msg.exec_()
            
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
                from freeassetfilter.widgets.custom_widgets import CustomMessageBox
                info_msg = CustomMessageBox(self)
                info_msg.set_title("提示")
                info_msg.set_text("该路径已在收藏夹中")
                info_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                info_msg.buttonClicked.connect(info_msg.close)
                info_msg.exec_()
                return
        
        # 弹出输入框获取名称
        name, ok = QInputDialog.getText(self, "添加到收藏夹", "请输入收藏名称:", text=default_name)
        if ok and name:
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
        self.load_last_path()
        self.refresh_files()
    
    def _update_drive_list(self):
        """
        动态获取当前系统存在的盘符列表和网络位置并更新到下拉框
        """
        # 清空现有选项
        self.drive_combo.clear()
        
        local_drives = []
        network_locations = []
        if sys.platform == 'win32':
            # Windows系统：遍历A-Z，检查存在的盘符
            for drive in range(65, 91):  # A-Z
                drive_letter = chr(drive) + ':/'
                if os.path.exists(drive_letter):
                    local_drives.append(drive_letter[:-1])  # 显示为 "C:" 而不是 "C:/"
            
            # 获取网络映射驱动器
            try:
                import ctypes
                from ctypes import wintypes
                
                # 定义Windows API函数
                mpr = ctypes.WinDLL('mpr')
                
                # 定义结构体
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
                
                # 定义常量
                RESOURCE_CONNECTED = 1
                RESOURCETYPE_ANY = 0
                
                # 调用WNetOpenEnum获取网络资源枚举句柄
                hEnum = wintypes.HANDLE()
                if mpr.WNetOpenEnumW(RESOURCE_CONNECTED, RESOURCETYPE_ANY, 0, None, ctypes.byref(hEnum)) == 0:
                    # 枚举网络资源
                    while True:
                        # 第一次调用获取需要的缓冲区大小
                        buf_size = wintypes.DWORD(0)
                        count = wintypes.DWORD(0)
                        if mpr.WNetEnumResourceW(hEnum, ctypes.byref(count), None, ctypes.byref(buf_size)) != 234:  # ERROR_MORE_DATA
                            break
                        
                        # 分配缓冲区
                        buf = ctypes.create_string_buffer(buf_size.value)
                        
                        # 再次调用获取网络资源
                        if mpr.WNetEnumResourceW(hEnum, ctypes.byref(count), buf, ctypes.byref(buf_size)) != 0:
                            break
                        
                        # 解析结果
                        resources = []
                        ptr = ctypes.cast(buf, ctypes.POINTER(NETRESOURCE))
                        for i in range(count.value):
                            res = ptr[i]
                            if res.lpLocalName and res.lpRemoteName:
                                # 添加网络映射驱动器
                                local_name = ctypes.wstring_at(res.lpLocalName)
                                if local_name and local_name not in drives:
                                    drives.append(local_name)  # 如 "Z:"
                                # 直接添加网络位置（UNC路径）
                                remote_name = ctypes.wstring_at(res.lpRemoteName)
                                if remote_name and remote_name not in drives:
                                    drives.append(remote_name)  # 如 "\\server\share"
                        
                # 关闭枚举句柄
                mpr.WNetCloseEnum(hEnum)
            except Exception as e:
                print(f"获取网络映射驱动器失败: {e}")
                # 使用net use命令作为备选方案
                try:
                    import subprocess
                    result = subprocess.run(['net', 'use'], capture_output=True, text=True, encoding='gbk')
                    if result.returncode == 0:
                        lines = result.stdout.strip().split('\n')
                        for line in lines[6:]:  # 跳过前6行标题和分隔线
                            line = line.strip()
                            if not line:
                                continue
                            # 解析net use命令输出
                            # 示例输出: "Z:        \\server\share     Microsoft Windows Network"
                            parts = line.split()
                            if len(parts) >= 2:
                                local_name = parts[0]
                                remote_name = parts[1]
                                if local_name and local_name not in local_drives:
                                    local_drives.append(local_name)
                                if remote_name and remote_name not in network_locations:
                                    network_locations.append(remote_name)
                except Exception as e:
                    print(f"使用net use命令获取网络位置失败: {e}")
        else:
            # Linux/macOS系统：根目录
            local_drives = ['/']
        
        # 对网络位置进行去重和排序
        network_locations = list(set(network_locations))
        network_locations.sort()
        
        # 先添加"All"选项，然后添加本地驱动器，最后添加网络位置
        all_drives = ["All"] + local_drives.copy()
        if network_locations:
            # 添加一个分隔符，区分本地驱动器和网络位置
            all_drives.append("--- 网络位置 ---")
            all_drives.extend(network_locations)
        
        # 添加到下拉框
        if all_drives:
            self.drive_combo.addItems(all_drives)
            
            # 设置默认选中项为当前路径所在的盘符
            if sys.platform == 'win32':
                # Windows系统：提取当前路径的盘符，如 "C:\path\to\dir" -> "C:"
                current_drive = os.path.splitdrive(self.current_path)[0]
                # 如果当前路径是UNC路径，直接使用完整路径作为当前盘符
                if not current_drive and self.current_path.startswith('\\'):
                    # 查找包含当前路径的网络位置
                    for drive in all_drives:
                        if drive != "--- 网络位置 ---" and self.current_path.startswith(drive):
                            current_drive = drive
                            break
            else:
                # Linux/macOS系统：根目录
                current_drive = '/'
            
            # 在盘符列表中查找并设置默认选中项
            index = self.drive_combo.findText(current_drive)
            if index != -1:
                self.drive_combo.setCurrentIndex(index)
    
    def _on_drive_changed(self, index):
        """
        当盘符选择改变时的处理
        
        Args:
            index (int): 选中的盘符索引
        """
        # 获取选中的盘符文本
        drive = self.drive_combo.itemText(index)
        
        # 跳过分隔符选项
        if drive == "--- 网络位置 ---":
            return
        
        # 处理"All"选项
        if drive == "All":
            # 设置一个特殊的路径标识，表示当前处于"All"视图
            self.current_path = "All"
            self.refresh_files()
            return
        
        if sys.platform == 'win32':
            # 处理Windows系统
            if drive.startswith('\\'):  # UNC路径，如 \\server\share
                # 直接使用UNC路径作为当前路径
                drive_path = drive
            else:  # 本地盘符，如 C:
                # 确保路径格式为 "D:\\"
                drive_path = drive + '\\'
        else:
            # Linux/macOS系统：根目录
            drive_path = drive
        
        # 确保路径存在且是绝对路径
        if os.path.exists(drive_path) and os.path.isabs(drive_path):
            self.current_path = drive_path
            self.refresh_files()
    
    def go_forward(self):
        """
        前进到导航历史中的下一个路径
        """
        if self.history_index < len(self.nav_history) - 1:
            self.history_index += 1
            self.current_path = self.nav_history[self.history_index]
            self.refresh_files()
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
        if path and os.path.exists(path):
            self.current_path = path
            self.refresh_files()
        else:
            from freeassetfilter.widgets.custom_widgets import CustomMessageBox
            warning_msg = CustomMessageBox(self)
            warning_msg.set_title("警告")
            warning_msg.set_text("无效的路径")
            warning_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            warning_msg.buttonClicked.connect(warning_msg.close)
            warning_msg.exec_()
    
    def apply_filter(self):
        """
        应用筛选器
        """
        filter_pattern = self.filter_edit.text().strip()
        self.filter_pattern = filter_pattern if filter_pattern else "*"
        self.refresh_files()
    
    def change_sort(self, index):
        """
        改变排序方式
        """
        # 排序选项映射，索引对应：0-名称升序，1-名称降序，2-大小升序，3-大小降序，4-创建时间升序，5-创建时间降序
        sort_mapping = [
            ("name", "asc"),
            ("name", "desc"),
            ("size", "asc"),
            ("size", "desc"),
            ("created", "asc"),
            ("created", "desc")
        ]
        
        self.sort_by, self.sort_order = sort_mapping[index]
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
            index = self.drive_combo.findText("All")
        elif sys.platform == 'win32':
            # Windows系统：提取当前路径的盘符，如 "C:\path\to\dir" -> "C:"
            current_drive = os.path.splitdrive(self.current_path)[0]
            # 在盘符列表中查找并设置默认选中项
            index = self.drive_combo.findText(current_drive)
        else:
            # Linux/macOS系统：根目录
            current_drive = '/'
            # 在盘符列表中查找并设置默认选中项
            index = self.drive_combo.findText(current_drive)
        
        if index != -1:
            self.drive_combo.setCurrentIndex(index)
    
    def refresh_files(self):
        """
        刷新文件列表
        """
        # 更新路径输入框
        self.path_edit.setText(self.current_path)
        
        # 更新盘符选择器
        self._update_drive_selector()
        
        # 清空现有文件卡片
        self._clear_files_layout()
        
        # 获取文件列表
        files = self._get_files()
        
        # 应用排序
        files = self._sort_files(files)
        
        # 应用筛选
        files = self._filter_files(files)
        
        # 创建文件卡片
        self._create_file_cards(files)
        
        # 更新选中文件计数
        #self._update_selected_count()
    
    def _clear_files_layout(self):
        """
        彻底清空文件布局，确保所有旧卡片被删除
        """
        # 首先停止所有正在运行的定时器，避免在清空过程中触发刷新
        self.resize_timer.stop()
        
        # 遍历所有布局项，按相反顺序删除，确保索引稳定
        while self.files_layout.count() > 0:
            # 获取布局项
            item = self.files_layout.itemAt(0)
            if item is not None:
                # 移除布局项
                self.files_layout.removeItem(item)
                
                # 如果是widget项，彻底删除
                widget = item.widget()
                if widget is not None:
                    # 断开所有信号连接
                    widget.disconnect()
                    # 删除widget
                    widget.deleteLater()
        
        # 重置布局状态，确保后续添加卡片时从正确位置开始
        self.files_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
    
    def _get_files(self):
        """
        获取当前目录下的文件列表
        """
        files = []
        
        # 处理"All"视图
        if self.current_path == "All":
            if sys.platform == 'win32':
                # Windows系统：遍历A-Z，检查存在的盘符
                for drive in range(65, 91):  # A-Z
                    drive_letter = chr(drive) + ':/'
                    if os.path.exists(drive_letter):
                        drive_name = chr(drive) + ':'
                        drive_path = drive_letter
                        file_info = QFileInfo(drive_path)
                        
                        # 构建磁盘驱动器信息字典
                        file_dict = {
                            "name": drive_name,
                            "path": drive_path,
                            "is_dir": True,
                            "size": 0,  # 磁盘大小暂不获取
                            "modified": file_info.lastModified().toString(Qt.ISODate),
                            "created": file_info.birthTime().toString(Qt.ISODate),
                            "suffix": ""
                        }
                        
                        files.append(file_dict)
            else:
                # Linux/macOS系统：显示根目录
                root_path = "/"
                file_info = QFileInfo(root_path)
                file_dict = {
                    "name": root_path,
                    "path": root_path,
                    "is_dir": True,
                    "size": 0,
                    "modified": file_info.lastModified().toString(Qt.ISODate),
                    "created": file_info.birthTime().toString(Qt.ISODate),
                    "suffix": ""
                }
                files.append(file_dict)
        else:
            # 正常目录视图
            try:
                # 获取当前目录下的所有文件和文件夹
                entries = os.listdir(self.current_path)
                
                for entry in entries:
                    entry_path = os.path.join(self.current_path, entry)
                    file_info = QFileInfo(entry_path)
                    
                    # 跳过隐藏文件
                    if entry.startswith(".") or file_info.isHidden():
                        continue
                    
                    # 构建文件信息字典
                    file_dict = {
                        "name": entry,
                        "path": entry_path,
                        "is_dir": file_info.isDir(),
                        "size": file_info.size(),
                        "modified": file_info.lastModified().toString(Qt.ISODate),
                        "created": file_info.birthTime().toString(Qt.ISODate),
                        "suffix": file_info.suffix().lower()
                    }
                    
                    files.append(file_dict)
            except Exception as e:
                print(f"[ERROR] CustomFileSelector - _get_files: 读取目录失败: {e}")
                from freeassetfilter.widgets.custom_widgets import CustomMessageBox
                error_msg = CustomMessageBox(self)
                error_msg.set_title("错误")
                error_msg.set_text(f"读取目录失败: {e}")
                error_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                error_msg.buttonClicked.connect(error_msg.close)
                error_msg.exec_()
        
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
        """
        if self.filter_pattern == "*":
            return files
        
        filtered = []
        pattern = self.filter_pattern.replace("*", ".*")
        pattern = pattern.replace(".", "\\.")
        pattern = f"^{pattern}$"
        
        regex = re.compile(pattern, re.IGNORECASE)
        
        for file in files:
            if regex.match(file["name"]):
                filtered.append(file)
        
        return filtered
    
    def _on_viewport_resized(self, event):
        """
        当视口大小变化时，重新排列文件卡片
        """
        # 直接重新生成文件列表，以适应新的宽度
        self.refresh_files()
    
    def _calculate_max_columns(self):
        """
        根据当前视口宽度精确计算每行卡片数量
        实时捕获窗口宽度，通过数值运算确定卡片数量
        完全基于视口宽度动态计算，没有固定限制
        """
        # 使用滚动区域的视口宽度而非文件容器宽度，确保计算准确
        # 滚动区域是父级容器，其宽度不会因内容变化而改变
        scroll_area = self.files_container.parent().parent()  # 获取滚动区域
        viewport_width = scroll_area.viewport().width()
        
        # 定义卡片属性
        card_width = 140  # 卡片固定宽度
        spacing = 10  # 卡片之间的间距
        margin = 20  # 左右边距总和（10*2）
        
        # 可用宽度 = 视口宽度 - 左右边距
        available_width = viewport_width - margin
        
        # 计算单张卡片占用的实际宽度（卡片宽度 + 右侧间距）
        card_actual_width = card_width + spacing
        
        # 完全基于可用宽度和卡片实际宽度计算列数
        # 不设置任何固定限制，确保最小为1列
        columns = max(1, available_width // card_actual_width)
        
        # 打印调试信息，便于监控计算过程
        #print(f"视口宽度: {viewport_width}px, 可用宽度: {available_width}px, 卡片实际宽度: {card_actual_width}px, 计算列数: {columns}")
        
        return columns
    
    def _create_file_cards(self, files):
        """
        创建文件卡片
        """
        row = 0
        col = 0
        
        # 根据视口宽度计算每行最大卡片数量
        max_cols = self._calculate_max_columns()
        
        for file in files:
            card = self._create_file_card(file)
            self.files_layout.addWidget(card, row, col)
            
            col += 1
            if col >= max_cols:
                col = 0
                row += 1
    
    def event(self, event):
        """
        处理鼠标硬件按钮事件
        """
        if event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.BackButton:
                # 鼠标后退按钮事件 - 返回上级文件夹
                self.go_to_parent()
                return True
        return super().event(event)
    
    def _create_file_card(self, file_info):
        """
        创建单个文件卡片
        """
        # 创建卡片容器
        card = QWidget()
        card.setObjectName("FileCard")
        card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        card.setMinimumSize(140, 180)
        card.setMaximumSize(140, 180)
        
        # 设置卡片样式
        card.setStyleSheet("""
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
        
        # 保存文件信息到卡片
        card.file_info = file_info
        
        # 检查文件是否已被选中
        file_path = file_info["path"]
        file_dir = os.path.dirname(file_path)
        card.is_selected = False
        
        if file_dir in self.selected_files and file_path in self.selected_files[file_dir]:
            card.is_selected = True
        
        # 创建卡片布局
        layout = QVBoxLayout(card)
        layout.setSpacing(5)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setAlignment(Qt.AlignCenter)
        
        # 设置图标或缩略图
        icon_display = self._set_file_icon(file_info)
        # 设置固定大小
        icon_display.setFixedSize(120, 120)
        # 确保标签透明，仅显示图标或缩略图
        if hasattr(icon_display, 'setStyleSheet'):
            icon_display.setStyleSheet('background: transparent; border: none;')
        # 添加到布局
        layout.addWidget(icon_display, alignment=Qt.AlignCenter)
        
        # 创建文件名标签
        name_label = QLabel()
        # 设置文本
        text = file_info["name"]
        # 使用全局字体计算文本宽度
        temp_font = QFont(self.global_font)  # 复制全局字体
        temp_font.setPointSize(9)  # 设置字体大小
        font_metrics = QFontMetrics(temp_font)
        # 限制文本宽度，根据卡片宽度调整
        max_width = 110  # 最大宽度，考虑到卡片宽度
        elided_text = font_metrics.elidedText(text, Qt.ElideRight, max_width)
        name_label.setText(elided_text)
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setWordWrap(False)
        name_label.setMaximumHeight(20)
        # 使用全局字体，并设置字体大小
        name_label.setFont(temp_font)
        #print(f"[DEBUG] 文件卡片文件名标签设置字体: {name_label.font().family()}, 大小: {name_label.font().pointSize()}")
        # 确保标签透明，仅显示文本
        name_label.setStyleSheet("background: transparent; border: none; color: #333333;")
        layout.addWidget(name_label, alignment=Qt.AlignCenter)
        
        # 创建文件大小标签
        size_label = QLabel()
        if file_info["is_dir"]:
            size_label.setText("文件夹")
        else:
            size_label.setText(self._format_size(file_info["size"]))
        size_label.setAlignment(Qt.AlignCenter)
        # 使用全局字体，并设置字体大小
        temp_font = QFont(self.global_font)
        temp_font.setPointSize(8)
        size_label.setFont(temp_font)
        #print(f"[DEBUG] 文件卡片大小标签设置字体: {size_label.font().family()}, 大小: {size_label.font().pointSize()}")
        # 确保标签透明，仅显示文本
        size_label.setStyleSheet("background: transparent; border: none; color: #666666;")
        layout.addWidget(size_label, alignment=Qt.AlignCenter)
        
        # 创建修改时间标签
        modified_label = QLabel()
        modified_time = QDateTime.fromString(file_info["modified"], Qt.ISODate)
        modified_label.setText(modified_time.toString("yyyy-MM-dd"))
        modified_label.setAlignment(Qt.AlignCenter)
        # 使用全局字体，并设置字体大小
        temp_font = QFont(self.global_font)
        temp_font.setPointSize(7)
        modified_label.setFont(temp_font)
        #print(f"[DEBUG] 文件卡片修改时间标签设置字体: {modified_label.font().family()}, 大小: {modified_label.font().pointSize()}")
        # 确保标签透明，仅显示文本
        modified_label.setStyleSheet("background: transparent; border: none; color: #888888;")
        layout.addWidget(modified_label, alignment=Qt.AlignCenter)
        
        # 保存标签引用到卡片对象
        card.name_label = name_label
        card.detail_label = size_label
        card.modified_label = modified_label
        card.icon_display = icon_display
        
        # 根据is_selected属性设置初始样式
        if card.is_selected:
            card.setStyleSheet("""
                QWidget#FileCard {
                    background-color: #e6f7ff;
                    border: 2px solid #1890ff;
                    border-radius: 8px;
                    padding: 8px;
                }
            """)
        else:
            card.setStyleSheet("""
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
        
        # 安装事件过滤器，用于处理鼠标事件
        card.installEventFilter(self)
        
        return card
    
    def _set_file_icon(self, file_info):
        """
        设置文件图标或缩略图，返回一个QWidget
        """
        # 首先尝试显示缩略图（如果存在）
        thumbnail_path = self._get_thumbnail_path(file_info["path"])
        if os.path.exists(thumbnail_path):
            # 创建标签显示缩略图
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            
            # 加载缩略图
            pixmap = QPixmap(thumbnail_path)
            # 缩放缩略图以适应120x120的大小
            scaled_pixmap = pixmap.scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
            # 创建一个新的Pixmap，用于绘制叠加图标
            combined_pixmap = QPixmap(120, 120)
            combined_pixmap.fill(Qt.transparent)
            
            # 创建画家
            painter = QPainter(combined_pixmap)
            
            # 绘制缩略图
            painter.drawPixmap((120 - scaled_pixmap.width()) // 2, (120 - scaled_pixmap.height()) // 2, scaled_pixmap)
            
            # 加载并绘制对应的文件类型图标
            try:
                # 使用现有的_get_file_type_pixmap方法获取文件类型图标
                file_type_pixmap = self._get_file_type_pixmap(file_info, icon_size=24)
                
                # 绘制缩小的图标在右下角
                icon_size = 24  # 图标大小
                margin = 4  # 边距
                
                # 计算绘制位置，右下角对齐
                x = 120 - icon_size - margin
                y = 120 - icon_size - margin
                
                # 绘制文件类型图标
                painter.drawPixmap(x, y, file_type_pixmap)
            except Exception as e:
                # 如果叠加图标失败，不影响主要缩略图显示
                print(f"叠加文件类型图标失败: {e}")
            finally:
                painter.end()
            
            # 设置最终的叠加图标
            label.setPixmap(combined_pixmap)
            return label
        
        # 定义文件类型映射
        image_formats = ["jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "svg", "cr2", "cr3", "nef", "arw", "dng", "orf"]
        video_formats = ["mp4", "avi", "mov", "mkv", "m4v", "mxf", "wmv", "flv", "webm", "3gp", "mpg", "mpeg", "vob", "m2ts", "ts"]
        audio_formats = ["mp3", "wav", "flac", "ogg", "wma", "aac", "m4a", "opus"]
        document_formats = ["pdf", "txt", "md", "rst", "doc", "docx", "xls", "xlsx", "ppt", "pptx"]
        font_formats = ["ttf", "otf", "woff", "woff2", "eot", "svg"]
        archive_formats = ["zip", "rar", "7z", "tar", "gz", "bz2", "xz", "lzma", "tar.gz", "tar.bz2", "tar.xz", "tar.lzma", "iso", "cab", "arj", "lzh", "ace", "z"]
        
        # 确定要使用的SVG图标
        icon_path = None
        icon_dir = os.path.join(os.path.dirname(__file__), "..", "icons")
        
        if file_info["is_dir"]:
            # 文件夹使用文件夹图标
            icon_path = os.path.join(icon_dir, "文件夹.svg")
        else:
            suffix = file_info["suffix"]
            
            if suffix in video_formats:
                # 视频文件使用视频图标
                icon_path = os.path.join(icon_dir, "视频.svg")
            elif suffix in image_formats:
                # 图像文件使用图像图标
                icon_path = os.path.join(icon_dir, "图像.svg")
            elif suffix in document_formats:
                # 文档文件使用对应图标
                if suffix == "pdf":
                    # PDF文件使用专门的PDF图标
                    icon_path = os.path.join(icon_dir, "PDF.svg")
                elif suffix in ["ppt", "pptx", "ppsx"]:
                    # PowerPoint文件使用PPT图标
                    icon_path = os.path.join(icon_dir, "PPT.svg")
                elif suffix in ["xls", "xlsx", "csv"]:
                    # Excel文件使用表格图标
                    icon_path = os.path.join(icon_dir, "表格.svg")
                elif suffix in ["doc", "docx", "wps"]:
                    # Word文件使用Word文档图标
                    icon_path = os.path.join(icon_dir, "Word文档.svg")
                else:
                    # 其他文档使用默认文档图标
                    icon_path = os.path.join(icon_dir, "文档.svg")
            elif suffix in font_formats:
                # 字体文件使用字体图标
                icon_path = os.path.join(icon_dir, "字体.svg")
            elif suffix in audio_formats:
                # 音频文件使用音频图标
                icon_path = os.path.join(icon_dir, "音乐.svg")
            elif suffix in archive_formats:
                # 压缩文件使用压缩文件图标
                icon_path = os.path.join(icon_dir, "压缩文件.svg")
            else:
                # 未知文件类型使用未知底板图标
                icon_path = os.path.join(icon_dir, "未知底板.svg")
        
        # 加载并显示SVG图标
        if icon_path and os.path.exists(icon_path):
            # 创建一个透明的QLabel
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            label.setFixedSize(120, 120)
            
            # 使用改进的QSvgRenderer实现
            svg_renderer = QSvgRenderer(icon_path)
            
            # 创建一个QImage，使用ARGB32_Premultiplied格式以支持正确的透明度
            image = QImage(120, 120, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)  # 使用透明背景
            
            # 创建画家
            painter = QPainter(image)
            
            # 设置最高质量的渲染提示
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            painter.setRenderHint(QPainter.HighQualityAntialiasing, True)
            
            # 渲染SVG图标
            svg_renderer.render(painter)
            
            # 如果是未知文件类型，在图标上显示后缀名
            if icon_path.endswith("未知底板.svg"):
                # 获取后缀名
                suffix = file_info["suffix"].upper()
                
                # 限制后缀名长度，最多5个字符
                if len(suffix) > 6:
                    suffix = "FILE"
                
                # 加载指定字体
                font_path = os.path.join(os.path.dirname(__file__), "..", "icons", "庞门正道标题体.ttf")
                font = QFont()
                
                # 尝试加载字体文件，如果失败则使用默认字体
                if os.path.exists(font_path):
                    font_id = QFontDatabase.addApplicationFont(font_path)
                    if font_id != -1:
                        font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
                        font.setFamily(font_family)
                
                # 设置字体大小，初始值为40
                font_size = 40
                font.setPointSize(font_size)
                font.setBold(True)
                
                # 自适应调整字体大小，确保文字不超出图标边界
                font_metrics = QFontMetrics(font)
                text_width = font_metrics.width(suffix)
                text_height = font_metrics.height()
                
                # 调整字体大小，确保文字在图标内居中显示
                max_text_width = 60  # 最大文本宽度
                while text_width > max_text_width and font_size > 10:
                    font_size -= 1
                    font.setPointSize(font_size)
                    font_metrics = QFontMetrics(font)
                    text_width = font_metrics.width(suffix)
                
                # 设置字体
                painter.setFont(font)
                
                # 设置文字颜色为纯黑色
                painter.setPen(QPen(QColor(0, 0, 0), 1, Qt.SolidLine))
                
                # 计算文字位置，确保整个文本在图标正中心显示
                x = (120 - text_width) // 2
                
                # 获取字体的ascent和descent，用于准确计算垂直居中位置
                ascent = font_metrics.ascent()
                descent = font_metrics.descent()
                
                # 计算文本的实际高度（ascent + descent）
                actual_text_height = ascent + descent
                
                # 计算y坐标，确保整个文本块在图标中心
                # y坐标是基线位置，所以需要调整为：(图标高度 + ascent - descent) // 2
                y = (120 + ascent - descent) // 2
                
                # 绘制文字
                painter.drawText(x, y, suffix)
            
            painter.end()
            
            # 将QImage转换为QPixmap，确保透明度正确
            pixmap = QPixmap.fromImage(image)
            
            if not pixmap.isNull():
                label.setPixmap(pixmap)
            else:
                # 如果加载失败，创建一个默认的透明图标
                pixmap = QPixmap(120, 120)
                pixmap.fill(Qt.transparent)
                label.setPixmap(pixmap)
            
            return label
        else:
            # 如果没有对应的SVG图标，创建一个默认的透明图标
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            label.setFixedSize(120, 120)
            pixmap = QPixmap(120, 120)
            pixmap.fill(Qt.transparent)
            label.setPixmap(pixmap)
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
        image_formats = ["jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "svg", "cr2", "cr3", "nef", "arw", "dng", "orf"]
        video_formats = ["mp4", "avi", "mov", "mkv", "m4v", "mxf", "wmv", "flv", "webm", "3gp", "mpg", "mpeg", "vob", "m2ts", "ts"]
        audio_formats = ["mp3", "wav", "flac", "ogg", "wma", "aac", "m4a", "opus"]
        document_formats = ["pdf", "txt", "md", "rst", "doc", "docx", "xls", "xlsx", "ppt", "pptx"]
        font_formats = ["ttf", "otf", "woff", "woff2", "eot", "svg"]
        archive_formats = ["zip", "rar", "7z", "tar", "gz", "bz2", "xz", "lzma", "tar.gz", "tar.bz2", "tar.xz", "tar.lzma", "iso", "cab", "arj", "lzh", "ace", "z"]
        
        # 确定要使用的SVG图标
        icon_path = None
        icon_dir = os.path.join(os.path.dirname(__file__), "..", "icons")
        
        if file_info["is_dir"]:
            # 文件夹使用文件夹图标
            icon_path = os.path.join(icon_dir, "文件夹.svg")
        else:
            suffix = file_info["suffix"]
            
            if suffix in video_formats:
                # 视频文件使用视频图标
                icon_path = os.path.join(icon_dir, "视频.svg")
            elif suffix in image_formats:
                # 图像文件使用图像图标
                icon_path = os.path.join(icon_dir, "图像.svg")
            elif suffix in document_formats:
                # 文档文件使用对应图标
                if suffix == "pdf":
                    # PDF文件使用专门的PDF图标
                    icon_path = os.path.join(icon_dir, "PDF.svg")
                elif suffix in ["ppt", "pptx", "ppsx"]:
                    # PowerPoint文件使用PPT图标
                    icon_path = os.path.join(icon_dir, "PPT.svg")
                elif suffix in ["xls", "xlsx", "csv"]:
                    # Excel文件使用表格图标
                    icon_path = os.path.join(icon_dir, "表格.svg")
                elif suffix in ["doc", "docx", "wps"]:
                    # Word文件使用Word文档图标
                    icon_path = os.path.join(icon_dir, "Word文档.svg")
                else:
                    # 其他文档使用默认文档图标
                    icon_path = os.path.join(icon_dir, "文档.svg")
            elif suffix in font_formats:
                # 字体文件使用字体图标
                icon_path = os.path.join(icon_dir, "字体.svg")
            elif suffix in audio_formats:
                # 音频文件使用音频图标
                icon_path = os.path.join(icon_dir, "音乐.svg")
            elif suffix in archive_formats:
                # 压缩文件使用压缩文件图标
                icon_path = os.path.join(icon_dir, "压缩文件.svg")
            else:
                # 未知文件类型使用未知底板图标
                icon_path = os.path.join(icon_dir, "未知底板.svg")

        # 使用SvgRenderer工具渲染SVG图标为QPixmap
        return SvgRenderer.render_svg_to_pixmap(icon_path, icon_size)
    
    def _get_thumbnail_path(self, file_path):
        """
        获取文件的缩略图路径
        """
        # 缩略图存储在临时目录
        thumb_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "thumbnails")
        os.makedirs(thumb_dir, exist_ok=True)
        
        # 使用更稳定的哈希算法，确保在不同进程中生成相同的哈希值
        import hashlib
        
        # 计算文件路径的MD5哈希值，并使用前16位作为文件名
        md5_hash = hashlib.md5(file_path.encode('utf-8'))
        file_hash = md5_hash.hexdigest()[:16]  # 使用前16位十六进制字符串
        
        return os.path.join(thumb_dir, f"{file_hash}.png")
    
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
        """
        事件过滤器，处理文件卡片的鼠标事件和滚动区域的大小变化事件
        """
        # 处理文件卡片的鼠标事件
        if obj.objectName() == "FileCard":
            if event.type() == QEvent.MouseButtonPress:
                # 处理鼠标点击事件
                if event.button() == Qt.LeftButton:
                    # 左键点击：如果是文件则预览，文件夹则打开
                    # 生成带时间戳的debug信息
                    import datetime
                    def debug(msg):
                        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                        print(f"[{timestamp}] [CustomFileSelector] {msg}")
                    
                    if obj.file_info["is_dir"]:
                        # 文件夹：打开文件夹，不发出预览信号
                        debug("左键点击文件夹，准备打开")
                        self._open_file(obj)
                    else:
                        # 文件：打开文件并发出预览信号
                        debug("左键点击文件，准备打开并预览")
                        self._open_file(obj)
                        # 发出文件选择信号用于预览
                        debug(f"发出file_selected信号，文件信息: {obj.file_info}")
                        self.file_selected.emit(obj.file_info)
                    return True
                elif event.button() == Qt.RightButton:
                    # 右键点击：选中/取消选中，不发出预览信号
                    if obj.file_info["is_dir"]:
                        # 文件夹：选中/取消选中
                        self._toggle_selection(obj)
                    else:
                        # 文件：选中/取消选中
                        self._toggle_selection(obj)
                    return True
        # 处理大小变化事件：包括视口和文件容器的大小变化
        elif event.type() == QEvent.Resize:
            # 使用防抖机制，避免频繁刷新
            self.resize_timer.start()
            return True
        
        return super().eventFilter(obj, event)
    
    def _toggle_selection(self, card, emit_preview=False):
        """
        切换文件的选中状态
        
        Args:
            card: 文件卡片对象
            emit_preview: 是否发出预览信号，默认为False
        """
        file_path = card.file_info["path"]
        file_dir = os.path.dirname(file_path)
        
        # 如果当前目录不在selected_files中，添加它
        if file_dir not in self.selected_files:
            self.selected_files[file_dir] = set()
        
        # 切换选中状态
        if file_path in self.selected_files[file_dir]:
            # 取消选中
            self.selected_files[file_dir].discard(file_path)
            card.is_selected = False
            # 更新样式
            card.setStyleSheet("""
                QWidget#FileCard {
                    background-color: #ffffff;
                    border: 2px solid #e0e0e0;
                    border-radius: 8px;
                    padding: 8px;
                }
                QWidget#FileCard:hover {
                    border-color: #4a7abc;
                    background-color: #f0f8ff;
                }
            """)
            # 发出选择状态改变信号
            self.file_selection_changed.emit(card.file_info, False)
        else:
            # 选中文件
            self.selected_files[file_dir].add(file_path)
            card.is_selected = True
            # 更新样式
            card.setStyleSheet("""
                QWidget#FileCard {
                    background-color: #e6f7ff;
                    border: 2px solid #1890ff;
                    border-radius: 8px;
                    padding: 8px;
                }
            """)
            # 发出选择信号（仅当emit_preview为True时）
            if emit_preview:
                self.file_selected.emit(card.file_info)
            # 发出选择状态改变信号
            self.file_selection_changed.emit(card.file_info, True)
        
        # 更新选中文件计数
        #self._update_selected_count()
    
    def _show_context_menu(self, card, pos):
        """
        显示上下文菜单
        """
        menu = QMenu(self)
        
        # 打开文件
        open_action = QAction("打开文件", self)
        open_action.triggered.connect(lambda: self._open_file(card))
        menu.addAction(open_action)
        
        # 查看属性
        properties_action = QAction("查看属性", self)
        properties_action.triggered.connect(lambda: self._show_properties(card))
        menu.addAction(properties_action)
        
        # 发出右键点击信号
        self.file_right_clicked.emit(card.file_info)
        
        # 显示菜单
        menu.exec_(card.mapToGlobal(pos))
    
    def _open_file(self, card):
        """
        打开文件
        """
        # 生成带时间戳的debug信息
        import datetime
        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            print(f"[{timestamp}] [CustomFileSelector] {msg}")
        
        file_path = card.file_info["path"]
        debug(f"打开文件: {file_path}, 是否为目录: {card.file_info['is_dir']}")
        
        if os.path.exists(file_path):
            if card.file_info["is_dir"]:
                debug(f"打开目录，进入新路径: {file_path}")
                # 如果是目录，进入该目录
                self.current_path = file_path
                self.refresh_files()
            else:
                debug(f"打开文件，文件信息: {card.file_info}")
    
    def _show_properties(self, card):
        """
        显示文件属性
        """
        file_info = card.file_info
        
        # 创建属性对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("文件属性")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        # 创建属性表格
        group_box = QGroupBox("基本信息")
        grid = QGridLayout(group_box)
        
        # 添加属性行
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
        
        # 添加关闭按钮
        close_btn = QPushButton("关闭")
        font = close_btn.font()
        font.setPointSize(8)
        close_btn.setFont(font)
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, 0, Qt.AlignRight)
        
        # 显示对话框
        dialog.exec_()
    



# 测试代码
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("自定义文件选择器")
    window.setGeometry(100, 100, 800, 600)
    
    selector = CustomFileSelector()
    window.setCentralWidget(selector)
    
    window.show()
    sys.exit(app.exec_())
