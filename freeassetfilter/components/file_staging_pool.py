#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文件临时存储池组件
用于展示和管理从左侧素材区添加的文件/文件夹项目
"""

import os
import tempfile
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QScrollArea, QGroupBox, QListWidget, QListWidgetItem, 
    QSizePolicy, QCheckBox, QMenu, QAction, QProgressBar, QFileDialog
)

# 导入自定义控件
from freeassetfilter.widgets.custom_widgets import CustomButton, CustomMessageBox, CustomProgressBar
from PyQt5.QtCore import (
    Qt, pyqtSignal, QFileInfo
)
from PyQt5.QtGui import QIcon, QColor, QPixmap, QFont

# 尝试导入PIL库，用于生成缩略图
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

class FileStagingPool(QWidget):
    """
    文件临时存储池组件
    用于展示和管理从左侧素材区添加的文件/文件夹项目
    """
    
    # 定义信号
    item_right_clicked = pyqtSignal(dict)  # 当项目被右键点击时发出
    remove_from_selector = pyqtSignal(dict)  # 当需要从选择器中移除文件时发出
    update_progress = pyqtSignal(int)  # 更新进度条信号
    export_finished = pyqtSignal(int, int, list)  # 导出完成信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 获取全局字体
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QFont
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        #print(f"[DEBUG] FileStagingPool获取到的全局字体: {self.global_font.family()}")
        
        # 设置组件字体
        self.setFont(self.global_font)
        
        # 初始化数据
        self.items = []  # 存储所有添加的文件/文件夹项目
        
        # 备份文件路径
        self.backup_file = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'staging_pool_backup.json')
        # 确保数据目录存在
        os.makedirs(os.path.dirname(self.backup_file), exist_ok=True)
        
        # 初始化UI
        self.init_ui()
        
        # 连接信号
        self.update_progress.connect(self.on_update_progress)
        self.export_finished.connect(self.on_export_finished)
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 创建主布局
        main_layout = QVBoxLayout(self)
        self.setStyleSheet("background-color: #ffffff;")
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 创建标题和控制区
        title_layout = QHBoxLayout()
        
        # 标题
        #title_label = QLabel("文件临时存储池")
        # 只设置字体大小和粗细，不指定字体名称，使用全局字体
        font = QFont("", 12, QFont.Bold)
        #title_label.setFont(font)
        #title_layout.addWidget(title_label)
        
        main_layout.addLayout(title_layout)
        
        # 创建项目列表
        self.items_list = QListWidget()
        self.items_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.items_list.itemDoubleClicked.connect(self.on_item_double_clicked)
        # 设置列表为可调整大小，使其能随父容器变化
        self.items_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 隐藏水平滚动条，避免出现水平滑块
        self.items_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 连接窗口大小变化事件，更新列表项宽度
        self.resizeEvent = self.on_resize
        
        main_layout.addWidget(self.items_list, 1)
        
        # 创建导出功能区
        export_layout = QHBoxLayout()
        
        # 控制按钮
        clear_btn = CustomButton("清空所有", button_type="secondary")
        clear_btn.clicked.connect(self.clear_all)
        export_layout.addWidget(clear_btn)
        
        # 导出按钮
        self.export_btn = CustomButton("导出文件", button_type="primary")
        self.export_btn.clicked.connect(self.export_selected_files)
        export_layout.addWidget(self.export_btn)
        
        # 导入/导出数据按钮
        self.import_export_btn = CustomButton("导入/导出数据", button_type="normal")
        self.import_export_btn.clicked.connect(self.show_import_export_dialog)
        export_layout.addWidget(self.import_export_btn)
        
        # 进度条
        self.progress_bar = CustomProgressBar()
        self.progress_bar.setInteractive(False)  # 禁用交互，只用于显示进度
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        export_layout.addWidget(self.progress_bar, 1)
        
        main_layout.addLayout(export_layout)
        
        # 创建统计信息
        self.stats_label = QLabel("当前项目数: 0")
        self.stats_label.setAlignment(Qt.AlignRight)
        main_layout.addWidget(self.stats_label)
    
    def add_file(self, file_info):
        """
        添加文件到临时存储池
        
        Args:
            file_info (dict): 文件信息字典
        """
        # 检查文件是否已存在
        for item in self.items:
            if item["path"] == file_info["path"]:
                return  # 文件已存在，不重复添加
        
        # 添加前端显示文件名字段，默认为原始文件名（如果不存在）
        if "display_name" not in file_info:
            file_info["display_name"] = file_info["name"]
        # 添加原始文件名字段，用于保存原始文件名和重命名记录（如果不存在）
        if "original_name" not in file_info:
            file_info["original_name"] = file_info["name"]
        
        # 添加到项目列表
        self.items.append(file_info)
        
        # 创建列表项
        list_item = QListWidgetItem()
        list_item.setData(Qt.UserRole, file_info)
        
        # 创建自定义widget
        item_widget = self.create_item_widget(file_info)
        # 设置列表项大小
        list_item.setSizeHint(item_widget.sizeHint())
        
        # 添加到列表
        self.items_list.addItem(list_item)
        self.items_list.setItemWidget(list_item, item_widget)
        
        # 更新列表项宽度
        self.update_list_item_widths()
        
        # 更新统计信息
        self.update_stats()
        
        # 实时保存备份
        self.save_backup()
    
    def on_resize(self, event):
        """
        处理窗口大小变化事件，更新所有列表项的宽度
        
        Args:
            event (QResizeEvent): 窗口大小变化事件
        """
        # 更新所有列表项的宽度
        self.update_list_item_widths()
        # 调用父类的resizeEvent
        super().resizeEvent(event)
    
    def update_list_item_widths(self):
        """
        更新所有列表项的宽度，使其适应列表宽度
        """
        # 获取列表的可见宽度，减去滚动条和边距
        list_width = self.items_list.width()
        
        # 遍历所有列表项，更新它们的大小
        for i in range(self.items_list.count()):
            list_item = self.items_list.item(i)
            if list_item:
                item_widget = self.items_list.itemWidget(list_item)
                if item_widget:
                    # 获取widget的布局
                    layout = item_widget.layout()
                    if layout:
                        # 重新设置widget的最小和最大宽度
                        item_widget.setMinimumWidth(list_width - 20)
                        item_widget.setMaximumWidth(list_width - 20)
                        
                        # 调整布局中的各个部件
                        for j in range(layout.count()):
                            widget = layout.itemAt(j).widget()
                            if widget:
                                # 对于信息布局中的标签，确保它们能够自动换行
                                if isinstance(widget, QLabel):
                                    widget.setWordWrap(True)
                        
                        # 强制布局更新
                        item_widget.updateGeometry()
                        
                    # 更新列表项的大小提示
                    list_item.setSizeHint(item_widget.sizeHint())
    
    def remove_file(self, file_path):
        """
        从临时存储池移除文件
        
        Args:
            file_path (str): 文件路径
        """
        # 查找并移除项目
        for i, item in enumerate(self.items):
            if item["path"] == file_path:
                # 保存文件信息用于发出信号
                removed_file = item
                self.items.pop(i)
                # 从列表中移除对应的项
                list_item = self.items_list.item(i)
                if list_item:
                    self.items_list.takeItem(i)
                # 发出信号通知文件选择器取消选中
                self.remove_from_selector.emit(removed_file)
                break
        
        # 更新统计信息
        self.update_stats()
        
        # 实时保存备份
        self.save_backup()
    
    def clear_all(self):
        """
        清空所有项目
        """
        # 确认对话框
        confirm_msg = CustomMessageBox(self)
        confirm_msg.set_title("确认清空")
        confirm_msg.set_text("确定要清空所有项目吗？")
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
            # 保存当前项目列表的副本，因为清空操作会修改原列表
            items_to_remove = self.items.copy()
            
            # 发出信号通知文件选择器取消所有选中
            for item in items_to_remove:
                self.remove_from_selector.emit(item)
            
            # 清空列表
            self.items.clear()
            self.items_list.clear()
            # 更新统计信息
            self.update_stats()
            
            # 实时保存备份
            self.save_backup()
    
    def create_item_widget(self, file_info):
        """
        创建项目widget
        
        Args:
            file_info (dict): 文件信息字典
        
        Returns:
            QWidget: 项目widget
        """
        # 创建widget和布局
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setSpacing(8)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # 添加图标
        icon_label = QLabel()
        icon_label.setFixedSize(32, 32)
        
        # 设置图标
        is_dir = file_info.get("is_dir", False)
        if is_dir:
            icon = QIcon.fromTheme("folder")
            icon_label.setPixmap(icon.pixmap(24, 24))
        else:
            # 为不同类型的文件设置不同的图标
            suffix = file_info.get("suffix", "")
            if suffix in ["jpg", "jpeg", "png", "gif", "bmp"]:
                icon = QIcon.fromTheme("image")
            elif suffix in ["mp4", "avi", "mov", "mkv"]:
                icon = QIcon.fromTheme("video")
            elif suffix in ["mp3", "wav", "flac", "ogg"]:
                icon = QIcon.fromTheme("audio")
            elif suffix in ["pdf"]:
                icon = QIcon.fromTheme("application-pdf")
            elif suffix in ["txt", "md", "rst"]:
                icon = QIcon.fromTheme("text")
            elif suffix in ["py", "java", "cpp", "js"]:
                icon = QIcon.fromTheme("code")
            else:
                icon = QIcon.fromTheme("application")
            
            icon_label.setPixmap(icon.pixmap(24, 24))
        
        layout.addWidget(icon_label)
        
        # 添加文件信息
        info_layout = QVBoxLayout()
        
        # 文件名 - 使用前端显示文件名
        name_label = QLabel(file_info["display_name"])
        name_label.setStyleSheet("font-weight: bold;")
        name_label.setWordWrap(True)
        # 存储label引用，方便后续更新
        name_label.setObjectName("name_label")
        info_layout.addWidget(name_label)
        
        # 文件路径（仅显示部分）
        path_label = QLabel(file_info["path"])
        path_label.setStyleSheet("font-size: 8pt; color: #666;")
        path_label.setWordWrap(True)
        info_layout.addWidget(path_label)
        
        layout.addLayout(info_layout, 1)
        
        # 创建按钮布局
        buttons_layout = QVBoxLayout()
        buttons_layout.setSpacing(4)
        
        # 添加重命名按钮
        rename_btn = QPushButton("重命名")
        rename_btn.setFixedWidth(60)
        rename_btn.setStyleSheet("background-color: #4488ff; color: white; border: none; border-radius: 4px;")
        rename_btn.clicked.connect(lambda _, fi=file_info, w=widget: self.rename_file(fi, w))
        # 默认隐藏重命名按钮
        rename_btn.setVisible(False)
        buttons_layout.addWidget(rename_btn)
        
        # 添加删除按钮
        delete_btn = QPushButton("删除")
        delete_btn.setFixedWidth(60)
        delete_btn.setStyleSheet("background-color: #ff4444; color: white; border: none; border-radius: 4px;")
        delete_btn.clicked.connect(lambda _, fi=file_info: self.remove_file(fi["path"]))
        # 默认隐藏删除按钮
        delete_btn.setVisible(False)
        buttons_layout.addWidget(delete_btn)
        
        layout.addLayout(buttons_layout)
        
        # 添加事件过滤器，监听鼠标进入和离开事件
        widget.setMouseTracking(True)
        widget.installEventFilter(self)
        # 存储按钮引用到widget上，方便事件处理
        widget.delete_btn = delete_btn
        widget.rename_btn = rename_btn
        widget.file_info = file_info
        
        return widget
    
    def update_stats(self):
        """
        更新统计信息
        """
        total_items = len(self.items)
        self.stats_label.setText(f"当前项目数: {total_items}")
    
    def on_item_double_clicked(self, item):
        """
        双击项目事件处理
        
        Args:
            item (QListWidgetItem): 双击的项目
        """
        file_info = item.data(Qt.UserRole)
        if file_info:
            self.open_file(file_info)
    
    def rename_file(self, file_info, widget):
        """
        重命名文件（仅修改前端显示名称，保持原始后缀名）
        
        Args:
            file_info (dict): 文件信息字典
            widget (QWidget): 文件卡片widget
        """
        from PyQt5.QtWidgets import QInputDialog
        
        # 获取当前显示名称
        current_name = file_info["display_name"]
        
        # 分离文件名主体和后缀名
        if "." in current_name:
            # 有后缀名的情况
            name_parts = current_name.rsplit(".", 1)
            name_base = name_parts[0]
            name_ext = name_parts[1]
        else:
            # 没有后缀名的情况
            name_base = current_name
            name_ext = ""
        
        # 定义文件名非法字符
        illegal_chars = '<>:"/\\|?*' + ''.join([chr(c) for c in range(32)])
        
        while True:
            # 弹出输入对话框，只显示和允许修改文件名主体
            new_name_input, ok = QInputDialog.getText(
                self, "重命名", "请输入新的文件名：",
                text=name_base
            )
            
            if not ok:
                # 用户取消操作
                return
            
            if not new_name_input:
                # 文件名不能为空
                warning_msg = CustomMessageBox(self)
                warning_msg.set_title("错误")
                warning_msg.set_text("文件名不能为空！")
                warning_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                warning_msg.buttonClicked.connect(warning_msg.close)
                warning_msg.exec_()
                continue
            
            if new_name_input == current_name:
                # 文件名未改变
                return
            
            # 检查是否包含非法字符
            if any(char in new_name_input for char in illegal_chars):
                warning_msg = CustomMessageBox(self)
                warning_msg.set_title("错误")
                warning_msg.set_text("文件名包含非法字符！请避免使用：< > : \" / \\ | ? * 以及控制字符")
                warning_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                warning_msg.buttonClicked.connect(warning_msg.close)
                warning_msg.exec_()
                continue
            
            # 生成新的文件名
            # 不管用户输入是否包含后缀名，都保留所有用户输入内容，然后加上原始后缀名
            # 这样可以确保用户想在文件名中使用的点号被保留
            if name_ext:
                new_name = f"{new_name_input}.{name_ext}"
            else:
                new_name = new_name_input
            
            # 检查路径长度，确保加上可能的导出路径后不超过MAX_PATH
            # Windows系统的MAXPATH限制为260字符
            MAX_PATH = 260
            # 这里使用一个保守的估计：假设导出目录路径长度为150字符
            # 实际使用时会根据用户选择的导出目录动态计算
            estimated_total_length = len(new_name) + 150  # 150字符用于估计的导出路径
            if estimated_total_length > MAX_PATH:
                warning_msg = CustomMessageBox(self)
                warning_msg.set_title("错误")
                warning_msg.set_text(f"文件名过长！加上路径后可能超过Windows系统的{MAX_PATH}字符限制。\n"
                                    f"当前估计总长度：{estimated_total_length}字符，建议缩短文件名。")
                warning_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                warning_msg.buttonClicked.connect(warning_msg.close)
                warning_msg.exec_()
                continue
            
            # 更新文件信息中的显示名称
            file_info["display_name"] = new_name
            
            # 更新UI上的显示
            name_label = widget.findChild(QLabel, "name_label")
            if name_label:
                name_label.setText(new_name)
            
            # 更新列表项的数据
            for i in range(self.items_list.count()):
                item = self.items_list.item(i)
                if item.data(Qt.UserRole)["path"] == file_info["path"]:
                    item.setData(Qt.UserRole, file_info)
                    break
            
            # 实时保存备份
            self.save_backup()
            break
    
    def open_file(self, file_info):
        """
        打开文件
        
        Args:
            file_info (dict): 文件信息
        """
        file_path = file_info["path"]
        if os.path.exists(file_path):
            if file_info["is_dir"]:
                # 如果是目录，发出信号
                pass
            else:
                # 如果是文件，使用默认应用打开
                os.startfile(file_path)
    
    def export_selected_files(self):
        """
        导出所有文件到指定目录
        """
        # 检查是否有文件可以导出
        if not self.items:
            info_msg = CustomMessageBox(self)
            info_msg.set_title("提示")
            info_msg.set_text("文件临时存储池中没有文件可以导出")
            info_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            info_msg.buttonClicked.connect(info_msg.close)
            info_msg.exec_()
            return
        
        # 选择目标目录
        target_dir = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not target_dir:
            return
        
        # 获取所有文件信息
        all_files = self.items
        
        # Windows系统的MAXPATH限制为260字符
        MAX_PATH = 260
        
        # 检查每个文件的实际导出路径长度
        for file_info in all_files:
            # 生成目标文件路径
            target_path = os.path.join(target_dir, file_info["display_name"])
            
            # 检查路径长度
            if len(target_path) > MAX_PATH:
                warning_msg = CustomMessageBox(self)
                warning_msg.set_title("错误")
                warning_msg.set_text(f"导出路径过长！\n"
                                    f"文件：{file_info['display_name']}\n"
                                    f"路径：{target_path}\n"
                                    f"长度：{len(target_path)}字符，超过Windows系统{MAX_PATH}字符限制。")
                warning_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                warning_msg.buttonClicked.connect(warning_msg.close)
                warning_msg.exec_()
                return
        
        # 创建带进度条的自定义提示窗口
        progress_msg_box = CustomMessageBox(self)
        progress_msg_box.set_title("导出进度")
        progress_msg_box.set_text("正在导出文件，请稍候...")
        
        # 创建并配置进度条
        export_progress_bar = CustomProgressBar()
        export_progress_bar.setInteractive(False)  # 禁用交互
        export_progress_bar.setRange(0, len(all_files))
        export_progress_bar.setValue(0)
        
        # 设置进度条到提示窗口
        progress_msg_box.set_progress(export_progress_bar)
        
        # 设置取消按钮，但暂时不连接槽函数（需要处理线程终止）
        progress_msg_box.set_buttons(["取消"], Qt.Horizontal, ["normal"])
        
        # 保存引用以便在进度更新和完成时访问
        self.current_progress_msg_box = progress_msg_box
        self.current_export_progress_bar = export_progress_bar
        
        # 连接进度更新信号到新的进度条
        self.update_progress.connect(self.on_update_export_progress)
        
        # 开始复制文件
        self.copy_files(all_files, target_dir)
        
        # 显示提示窗口
        progress_msg_box.exec_()
    
    def on_update_progress(self, value):
        """
        更新进度条
        
        Args:
            value (int): 进度值
        """
        self.progress_bar.setValue(value)
    
    def on_update_export_progress(self, value):
        """
        更新导出提示框中的进度条
        
        Args:
            value (int): 进度值
        """
        if hasattr(self, 'current_export_progress_bar'):
            self.current_export_progress_bar.setValue(value)
    
    def on_export_finished(self, success_count, error_count, errors):
        """
        处理导出完成
        
        Args:
            success_count (int): 成功导出的文件数
            error_count (int): 失败的文件数
            errors (list): 错误信息列表
        """
        # 断开进度更新信号的连接
        self.update_progress.disconnect(self.on_update_export_progress)
        
        # 关闭进度提示窗口
        if hasattr(self, 'current_progress_msg_box'):
            self.current_progress_msg_box.close()
            # 清理引用
            delattr(self, 'current_progress_msg_box')
            delattr(self, 'current_export_progress_bar')
        
        # 显示导出结果
        result_msg = CustomMessageBox(self)
        if error_count == 0:
            result_msg.set_title("导出完成")
            result_msg.set_text(f"成功导出 {success_count} 个文件")
        else:
            result_msg.set_title("导出结果")
            error_msg = f"成功导出 {success_count} 个文件，失败 {error_count} 个文件\n\n失败详情：\n" + "\n".join(errors[:5])
            if len(errors) > 5:
                error_msg += f"\n\n还有 {len(errors) - 5} 个错误未显示"
            result_msg.set_text(error_msg)
        result_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
        result_msg.buttonClicked.connect(result_msg.close)
        result_msg.exec_()
    
    def eventFilter(self, obj, event):
        """
        事件过滤器，用于处理鼠标进入和离开事件
        
        Args:
            obj (QObject): 事件对象
            event (QEvent): 事件类型
        
        Returns:
            bool: 是否处理了事件
        """
        if event.type() == event.Enter:
            # 鼠标进入时显示删除和重命名按钮
            if hasattr(obj, 'delete_btn'):
                obj.delete_btn.setVisible(True)
            if hasattr(obj, 'rename_btn'):
                obj.rename_btn.setVisible(True)
        elif event.type() == event.Leave:
            # 鼠标离开时隐藏删除和重命名按钮
            if hasattr(obj, 'delete_btn'):
                obj.delete_btn.setVisible(False)
            if hasattr(obj, 'rename_btn'):
                obj.rename_btn.setVisible(False)
        return super().eventFilter(obj, event)
    
    def save_backup(self, last_path='All'):
        """
        保存当前文件列表到备份文件
        
        Args:
            last_path (str): 文件选择器的当前路径
        """
        import json
        try:
            # 构建备份数据，包含文件列表和选择器状态
            backup_data = {
                'items': self.items,
                'selector_state': {
                    'last_path': last_path
                }
            }
            with open(self.backup_file, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2)
            print(f"[DEBUG] 保存备份成功，路径: {self.backup_file}, 项目数: {len(self.items)}, 最后路径: {last_path}")
        except Exception as e:
            print(f"保存文件列表备份失败: {e}")
    
    def show_import_export_dialog(self):
        """
        显示导入/导出数据对话框
        """
        # 使用自定义提示窗口实现导入/导出选择
        msg_box = CustomMessageBox(self)
        msg_box.set_title("导入/导出数据")
        msg_box.set_text("请选择操作:")
        
        # 设置按钮，使用垂直排列
        msg_box.set_buttons(["导入数据", "导出数据", "取消"], Qt.Vertical, ["normal", "normal", "normal"])
        
        # 记录用户选择
        user_choice = -1
        
        def on_button_clicked(button_index):
            nonlocal user_choice
            user_choice = button_index
            msg_box.close()
        
        msg_box.buttonClicked.connect(on_button_clicked)
        msg_box.exec_()
        
        # 根据用户选择执行相应操作
        if user_choice == 0:  # 导入数据
            # 创建一个临时对话框实例用于传递给import_data方法
            from PyQt5.QtWidgets import QDialog
            temp_dialog = QDialog(self)
            self.import_data(temp_dialog)
        elif user_choice == 1:  # 导出数据
            # 创建一个临时对话框实例用于传递给export_data方法
            from PyQt5.QtWidgets import QDialog
            temp_dialog = QDialog(self)
            self.export_data(temp_dialog)
        # 否则取消操作，不做任何处理
    
    def import_data(self, dialog):
        """
        导入数据功能
        
        Args:
            dialog (QDialog): 父对话框
        """
        from PyQt5.QtWidgets import QFileDialog
        import json
        
        # 打开文件选择对话框，选择JSON文件
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择导入文件", "", "JSON文件 (*.json)"
        )
        
        if file_path:
            try:
                # 读取JSON文件
                with open(file_path, 'r', encoding='utf-8') as f:
                    import_data = json.load(f)
                
                # 验证数据格式
                if not isinstance(import_data, list):
                    warning_msg = CustomMessageBox(self)
                    warning_msg.set_title("导入失败")
                    warning_msg.set_text("文件格式不正确，应为JSON数组格式")
                    warning_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                    warning_msg.buttonClicked.connect(warning_msg.close)
                    warning_msg.exec_()
                    return
                
                # 询问用户是否要清空现有数据
                confirm_msg = CustomMessageBox(self)
                confirm_msg.set_title("确认导入")
                confirm_msg.set_text(f"即将导入 {len(import_data)} 个文件，是否要清空现有数据？")
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
                    # 清空现有数据
                    self.clear_all_without_confirmation()
                
                # 导入数据并检查文件是否存在
                success_count = 0
                unlinked_files = []
                
                for file_info in import_data:
                    # 验证文件信息格式
                    if isinstance(file_info, dict) and "path" in file_info and "name" in file_info:
                        # 检查文件是否存在
                        if os.path.exists(file_info["path"]):
                            self.add_file(file_info)
                            success_count += 1
                        else:
                            # 添加到未链接文件列表
                            unlinked_files.append({
                                "original_file_info": file_info,
                                "status": "unlinked",  # unlinked, ignored, linked
                                "new_path": None,
                                "md5": self.calculate_md5(file_info["path"]) if os.path.exists(file_info["path"]) else None
                            })
                
                # 如果有未链接文件，显示处理对话框
                if unlinked_files:
                    self.show_unlinked_files_dialog(unlinked_files)
                
                # 显示导入结果
                info_msg = CustomMessageBox(self)
                info_msg.set_title("导入完成")
                info_msg.set_text(f"成功导入 {success_count} 个文件，{len(unlinked_files)} 个文件需要手动链接")
                info_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                info_msg.buttonClicked.connect(info_msg.close)
                info_msg.exec_()
                
                # 关闭对话框
                dialog.accept()
            except json.JSONDecodeError:
                warning_msg = CustomMessageBox(self)
                warning_msg.set_title("导入失败")
                warning_msg.set_text("JSON文件格式不正确")
                warning_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                warning_msg.buttonClicked.connect(warning_msg.close)
                warning_msg.exec_()
            except Exception as e:
                warning_msg = CustomMessageBox(self)
                warning_msg.set_title("导入失败")
                warning_msg.set_text(f"导入过程中发生错误: {str(e)}")
                warning_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                warning_msg.buttonClicked.connect(warning_msg.close)
                warning_msg.exec_()
    
    def calculate_md5(self, file_path):
        """
        计算文件的MD5值
        
        Args:
            file_path (str): 文件路径
            
        Returns:
            str: 文件的MD5值，如果文件不存在则返回None
        """
        import hashlib
        try:
            if not os.path.exists(file_path):
                return None
            
            hash_md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            print(f"计算MD5失败: {e}")
            return None
    
    def show_unlinked_files_dialog(self, unlinked_files):
        """
        显示未链接文件处理对话框
        
        Args:
            unlinked_files (list): 未链接文件列表
        """
        from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                                     QListWidget, QListWidgetItem, QMenu, QAction, 
                                     QFileDialog, QLabel, QGridLayout)
        
        # 创建对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("处理未链接文件")
        dialog.setMinimumSize(600, 400)
        
        # 创建布局
        main_layout = QVBoxLayout(dialog)
        
        # 添加标题
        title_label = QLabel(f"有 {len(unlinked_files)} 个文件需要手动链接:")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # 创建未链接文件列表
        self.unlinked_list_widget = QListWidget()
        self.unlinked_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.unlinked_list_widget.customContextMenuRequested.connect(lambda pos: self.show_unlinked_context_menu(pos, unlinked_files))
        
        # 添加未链接文件到列表
        for i, file_item in enumerate(unlinked_files):
            list_item = QListWidgetItem()
            file_info = file_item["original_file_info"]
            display_text = f"{file_info['name']} - {file_info['path']} ({file_item['status']})"
            list_item.setText(display_text)
            list_item.setData(Qt.UserRole, i)  # 存储索引
            self.unlinked_list_widget.addItem(list_item)
        
        main_layout.addWidget(self.unlinked_list_widget)
        
        # 创建按钮布局
        button_layout = QHBoxLayout()
        
        # 手动链接按钮
        manual_link_btn = CustomButton("手动链接", button_type="normal")
        manual_link_btn.clicked.connect(lambda: self.manual_link_files(unlinked_files, self.unlinked_list_widget))
        button_layout.addWidget(manual_link_btn)
        
        # 忽略所有按钮
        ignore_all_btn = CustomButton("忽略所有", button_type="normal")
        ignore_all_btn.clicked.connect(lambda: self.ignore_all_files(unlinked_files))
        button_layout.addWidget(ignore_all_btn)
        
        # 完成按钮
        finish_btn = CustomButton("完成", button_type="primary")
        finish_btn.clicked.connect(lambda: self.finish_unlinked_files_dialog(dialog, unlinked_files))
        button_layout.addWidget(finish_btn)
        
        main_layout.addLayout(button_layout)
        
        # 显示对话框
        dialog.exec_()
        
        # 处理已链接的文件
        for file_item in unlinked_files:
            if file_item["status"] == "linked" and file_item["new_path"]:
                # 更新文件信息
                new_file_info = file_item["original_file_info"].copy()
                new_file_info["path"] = file_item["new_path"]
                new_file_info["name"] = os.path.basename(file_item["new_path"])
                # 添加到文件存储池
                self.add_file(new_file_info)
    
    def show_unlinked_context_menu(self, pos, unlinked_files):
        """
        显示未链接文件的右键菜单
        
        Args:
            pos (QPoint): 鼠标位置
            unlinked_files (list): 未链接文件列表
        """
        from PyQt5.QtWidgets import QMenu, QAction
        
        # 获取当前选中的项
        selected_items = self.unlinked_list_widget.selectedItems()
        if not selected_items:
            return
        
        # 创建菜单
        menu = QMenu()
        
        # 忽略此项
        ignore_action = menu.addAction("忽略此项")
        ignore_action.triggered.connect(lambda: self.ignore_selected_files(unlinked_files, selected_items))
        
        # 手动链接此项
        link_action = menu.addAction("手动链接此文件")
        link_action.triggered.connect(lambda: self.manual_link_selected_files(unlinked_files, selected_items))
        
        # 显示菜单
        menu.exec_(self.unlinked_list_widget.mapToGlobal(pos))
    
    def manual_link_files(self, unlinked_files, list_widget):
        """
        手动链接文件
        
        Args:
            unlinked_files (list): 未链接文件列表
            list_widget (QListWidget): 列表控件
        """
        from PyQt5.QtWidgets import QFileDialog
        
        # 选择一个目录
        dir_path = QFileDialog.getExistingDirectory(self, "选择文件目录")
        if not dir_path:
            return
        
        # 遍历目录下所有文件
        matched_count = 0
        for root, dirs, files in os.walk(dir_path):
            for file in files:
                file_path = os.path.join(root, file)
                file_md5 = self.calculate_md5(file_path)
                
                # 查找匹配的未链接文件
                for file_item in unlinked_files:
                    if file_item["status"] == "unlinked":
                        original_file_info = file_item["original_file_info"]
                        original_name = original_file_info["name"]
                        original_md5 = self.calculate_md5(original_file_info["path"])
                        
                        # 优先匹配MD5
                        if file_md5 and original_md5 and file_md5 == original_md5:
                            file_item["status"] = "linked"
                            file_item["new_path"] = file_path
                            matched_count += 1
                            break
                        # 其次匹配文件名
                        elif file == original_name:
                            # 询问用户是否接受仅文件名匹配
                            confirm_msg = CustomMessageBox(self)
                            confirm_msg.set_title("文件名匹配")
                            confirm_msg.set_text(f"找到文件名匹配的文件，但MD5不匹配。\n"
                                                f"原始文件: {original_name}\n"
                                                f"找到文件: {file_path}\n"
                                                f"是否接受仅文件名匹配？")
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
                                file_item["status"] = "linked"
                                file_item["new_path"] = file_path
                                matched_count += 1
                                break
        
        # 更新列表显示
        self.update_unlinked_list(unlinked_files)
        
        info_msg = CustomMessageBox(self)
        info_msg.set_title("匹配完成")
        info_msg.set_text(f"成功匹配 {matched_count} 个文件")
        info_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
        info_msg.buttonClicked.connect(info_msg.close)
        info_msg.exec_()
    
    def manual_link_selected_files(self, unlinked_files, selected_items):
        """
        手动链接选中的文件
        
        Args:
            unlinked_files (list): 未链接文件列表
            selected_items (list): 选中的列表项
        """
        from PyQt5.QtWidgets import QFileDialog
        
        for item in selected_items:
            index = item.data(Qt.UserRole)
            file_item = unlinked_files[index]
            
            if file_item["status"] == "unlinked":
                # 让用户选择文件
                file_path, _ = QFileDialog.getOpenFileName(
                    self, "选择文件", "", "所有文件 (*.*)"
                )
                
                if file_path:
                    # 检查文件名是否匹配
                    original_name = file_item["original_file_info"]["name"]
                    new_name = os.path.basename(file_path)
                    
                    if original_name != new_name:
                        # 询问用户是否接受不同文件名
                        confirm_msg = CustomMessageBox(self)
                        confirm_msg.set_title("文件名不匹配")
                        confirm_msg.set_text(f"选中文件的文件名与原始文件不同。\n"
                                            f"原始文件名: {original_name}\n"
                                            f"选中文件名: {new_name}\n"
                                            f"是否继续？")
                        confirm_msg.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])
                        
                        # 记录确认结果
                        is_confirmed = False
                        
                        def on_confirm_clicked(button_index):
                            nonlocal is_confirmed
                            is_confirmed = (button_index == 0)  # 0表示确定按钮
                            confirm_msg.close()
                        
                        confirm_msg.buttonClicked.connect(on_confirm_clicked)
                        confirm_msg.exec_()
                        
                        if not is_confirmed:
                            continue
                    
                    # 更新文件状态
                    file_item["status"] = "linked"
                    file_item["new_path"] = file_path
        
        # 更新列表显示
        self.update_unlinked_list(unlinked_files)
    
    def ignore_selected_files(self, unlinked_files, selected_items):
        """
        忽略选中的文件
        
        Args:
            unlinked_files (list): 未链接文件列表
            selected_items (list): 选中的列表项
        """
        for item in selected_items:
            index = item.data(Qt.UserRole)
            file_item = unlinked_files[index]
            file_item["status"] = "ignored"
        
        # 更新列表显示
        self.update_unlinked_list(unlinked_files)
    
    def ignore_all_files(self, unlinked_files):
        """
        忽略所有未链接文件
        
        Args:
            unlinked_files (list): 未链接文件列表
        """

        
        # 确认忽略所有对话框
        confirm_msg = CustomMessageBox(self)
        confirm_msg.set_title("确认忽略所有")
        confirm_msg.set_text("确定要忽略所有未链接的文件吗？")
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
            for file_item in unlinked_files:
                file_item["status"] = "ignored"
            
            # 更新列表显示
            self.update_unlinked_list(unlinked_files)
    
    def update_unlinked_list(self, unlinked_files):
        """
        更新未链接文件列表显示
        
        Args:
            unlinked_files (list): 未链接文件列表
        """
        self.unlinked_list_widget.clear()
        
        for i, file_item in enumerate(unlinked_files):
            list_item = QListWidgetItem()
            file_info = file_item["original_file_info"]
            display_text = f"{file_info['name']} - {file_info['path']} ({file_item['status']})"
            list_item.setText(display_text)
            list_item.setData(Qt.UserRole, i)
            self.unlinked_list_widget.addItem(list_item)
    
    def finish_unlinked_files_dialog(self, dialog, unlinked_files):
        """
        完成未链接文件处理
        
        Args:
            dialog (QDialog): 对话框实例
            unlinked_files (list): 未链接文件列表
        """

        
        # 检查是否还有未处理的文件
        has_unlinked = any(item["status"] == "unlinked" for item in unlinked_files)
        
        if has_unlinked:
            confirm_msg = CustomMessageBox(self)
            confirm_msg.set_title("还有未处理文件")
            confirm_msg.set_text("还有未链接的文件，确定要完成吗？未处理的文件将被忽略。")
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
                # 忽略所有未处理的文件
                for file_item in unlinked_files:
                    if file_item["status"] == "unlinked":
                        file_item["status"] = "ignored"
                dialog.accept()
        else:
            dialog.accept()
    
    def export_data(self, dialog):
        """
        导出数据功能
        
        Args:
            dialog (QDialog): 父对话框
        """
        from PyQt5.QtWidgets import QFileDialog
        import json
        from datetime import datetime
        
        # 检查是否有数据可导出
        if not self.items:
            info_msg = CustomMessageBox(self)
            info_msg.set_title("导出提示")
            info_msg.set_text("文件存储池中没有数据可以导出")
            info_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            info_msg.buttonClicked.connect(info_msg.close)
            info_msg.exec_()
            return
        
        # 生成带时间戳的默认文件名
        current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        default_filename = f"FAF_{current_time}.json"
        
        # 打开文件保存对话框，选择保存路径
        file_path, _ = QFileDialog.getSaveFileName(
            self, "选择导出文件", default_filename, "JSON文件 (*.json)"
        )
        
        if file_path:
            try:
                # 导出数据到JSON文件
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.items, f, ensure_ascii=False, indent=2)
                
                info_msg = CustomMessageBox(self)
                info_msg.set_title("导出成功")
                info_msg.set_text(f"成功导出 {len(self.items)} 个文件的数据到 {file_path}")
                info_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                info_msg.buttonClicked.connect(lambda: [info_msg.close(), dialog.accept()])
                info_msg.exec_()
                
                # 关闭对话框
                dialog.accept()
            except Exception as e:
                warning_msg = CustomMessageBox(self)
                warning_msg.set_title("导出失败")
                warning_msg.set_text(f"导出过程中发生错误: {str(e)}")
                warning_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                warning_msg.buttonClicked.connect(warning_msg.close)
                warning_msg.exec_()
    
    def clear_all_without_confirmation(self):
        """
        不显示确认对话框，直接清空所有项目
        """
        # 保存当前项目列表的副本，因为清空操作会修改原列表
        items_to_remove = self.items.copy()
        
        # 发出信号通知文件选择器取消所有选中
        for item in items_to_remove:
            self.remove_from_selector.emit(item)
        
        # 清空列表
        self.items.clear()
        self.items_list.clear()
        # 更新统计信息
        self.update_stats()
        
        # 实时保存备份
        self.save_backup()
    
    def load_backup(self):
        """
        从备份文件加载文件列表
        
        Returns:
            list: 加载的文件列表，如果没有备份则返回空列表
        """
        import json
        try:
            if os.path.exists(self.backup_file):
                with open(self.backup_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载文件列表备份失败: {e}")
        return []
    
    def copy_files(self, files, target_dir):
        """
        复制文件到目标目录
        
        Args:
            files (list): 文件信息列表
            target_dir (str): 目标目录路径
        """
        import shutil
        import threading
        
        def copy_thread():
            """复制文件的线程函数"""
            success_count = 0
            error_count = 0
            errors = []
            
            for i, file_info in enumerate(files):
                source_path = file_info["path"]
                # 使用前端显示的文件名作为目标文件名
                target_path = os.path.join(target_dir, file_info["display_name"])
                
                try:
                    if file_info["is_dir"]:
                        # 复制目录
                        shutil.copytree(source_path, target_path)
                    else:
                        # 复制文件
                        shutil.copy2(source_path, target_path)
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    errors.append(f"{file_info['display_name']}: {str(e)}")
                
                # 发送进度更新信号
                progress = i + 1
                self.update_progress.emit(progress)
            
            # 发送导出完成信号
            self.export_finished.emit(success_count, error_count, errors)
        
        # 启动复制线程
        thread = threading.Thread(target=copy_thread)
        thread.daemon = True  # 设置为守护线程，防止程序退出时线程还在运行
        thread.start()

# 测试代码
if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication, QMainWindow
    
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("文件临时存储池测试")
    window.setGeometry(100, 100, 600, 400)
    
    pool = FileStagingPool()
    window.setCentralWidget(pool)
    
    # 测试添加文件
    test_file = {
        "name": "test.txt",
        "path": "C:/test.txt",
        "is_dir": False,
        "size": 1024,
        "modified": "2023-01-01T12:00:00",
        "created": "2023-01-01T12:00:00",
        "suffix": "txt"
    }
    pool.add_file(test_file)
    
    window.show()
    sys.exit(app.exec_())
