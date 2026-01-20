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
import sys
import tempfile

# 添加项目根目录到Python路径，解决直接运行时的导入问题
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QScrollArea, QGroupBox, QListWidget, QListWidgetItem, 
    QSizePolicy, QCheckBox, QMenu, QAction, QProgressBar, QFileDialog, QApplication
)

# 导入自定义控件
from freeassetfilter.widgets.D_widgets import CustomButton, CustomMessageBox, CustomProgressBar
from freeassetfilter.widgets.file_horizontal_card import CustomFileHorizontalCard
from freeassetfilter.widgets.hover_tooltip import HoverTooltip
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
    item_left_clicked = pyqtSignal(dict)  # 当项目被左键点击时发出
    remove_from_selector = pyqtSignal(dict)  # 当需要从选择器中移除文件时发出
    update_progress = pyqtSignal(int)  # 更新进度条信号
    export_finished = pyqtSignal(int, int, list)  # 导出完成信号
    folder_size_calculated = pyqtSignal(dict)  # 文件夹体积计算完成信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 获取应用实例和DPI缩放因子
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QFont
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 获取全局字体
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
        
        # 启用拖拽功能
        self.setAcceptDrops(True)
        self.cards_container.setAcceptDrops(True)
        
        # 连接信号
        self.update_progress.connect(self.on_update_progress)
        self.export_finished.connect(self.on_export_finished)
        self.folder_size_calculated.connect(self.on_folder_size_calculated)
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 应用DPI缩放因子到布局参数（调整为原始的一半）
        scaled_spacing = int(5 * self.dpi_scale)
        scaled_margin = int(5 * self.dpi_scale)
        
        # 创建主布局
        main_layout = QVBoxLayout(self)
        # 获取主题颜色
        app = QApplication.instance()
        background_color = "#2D2D2D"  # 默认窗口背景色
        if hasattr(app, 'settings_manager'):
            background_color = app.settings_manager.get_setting("appearance.colors.window_background", "#2D2D2D")
        self.setStyleSheet(f"background-color: {background_color};")
        main_layout.setSpacing(scaled_spacing)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        
        # 创建标题和控制区
        title_layout = QHBoxLayout()
        
        # 标题
        #title_label = QLabel("文件临时存储池")
        # 只设置字体大小和粗细，不指定字体名称，使用全局字体
        font = QFont("", 12, QFont.Bold)
        #title_label.setFont(font)
        #title_layout.addWidget(title_label)
        
        main_layout.addLayout(title_layout)
        
        # 创建滚动区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        app = QApplication.instance()
        base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#212121")
        auxiliary_color = app.settings_manager.get_setting("appearance.colors.auxiliary_color", "#313131")
        normal_color = app.settings_manager.get_setting("appearance.colors.normal_color", "#717171")
        secondary_color = app.settings_manager.get_setting("appearance.colors.secondary_color", "#FFFFFF")
        accent_color = app.settings_manager.get_setting("appearance.colors.accent_color", "#F0C54D")
        
        scrollbar_style = f"""
            QScrollArea {{
                border: 0px solid transparent;
                background-color: {base_color};
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {base_color};
            }}
            QScrollBar:vertical {{
                width: 6px;
                background-color: {auxiliary_color};
                border: 0px solid transparent;
                border-radius: 0px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {normal_color};
                min-height: 15px;
                border-radius: 3px;
                border: none;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {secondary_color};
                border: none;
            }}
            QScrollBar::handle:vertical:pressed {{
                background-color: {accent_color};
                border: none;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0px;
                border: none;
            }}
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{
                background: none;
                border: 0px solid transparent;
                border: none;
            }}
        """
        self.scroll_area.setStyleSheet(scrollbar_style)
        
        # 创建卡片容器和布局
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setSpacing(int(5 * self.dpi_scale))
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        # 设置布局上对齐
        self.cards_layout.setAlignment(Qt.AlignTop)
        # 添加拉伸因子，确保卡片上对齐且不被拉伸
        self.cards_layout.addStretch(1)
        
        # 将卡片容器放入滚动区域
        self.scroll_area.setWidget(self.cards_container)
        
        # 添加到主布局
        main_layout.addWidget(self.scroll_area, 1)
        
        # 存储卡片对象
        self.cards = []
        
        # 创建统计信息容器
        stats_container = QWidget()
        stats_container.setStyleSheet("background-color: transparent; border: none;")
        stats_container_layout = QHBoxLayout(stats_container)
        stats_container_layout.setContentsMargins(0, 0, 0, 0)
        stats_container_layout.setSpacing(0)
        
        self.stats_label = QLabel("0个条目")
        self.stats_label.setAlignment(Qt.AlignCenter)
        # 使用全局字体，不单独设置过大的字体大小
        self.stats_label.setFont(self.global_font)
        # 使用 secondary_color 作为文本颜色
        self.stats_label.setStyleSheet(f"color: {secondary_color};")
        stats_container_layout.addWidget(self.stats_label)
        
        main_layout.addWidget(stats_container)
        
        # 创建导出功能区
        export_layout = QHBoxLayout()
        
        # 导入/导出数据按钮
        self.import_export_btn = CustomButton("导入/导出数据", button_type="secondary")
        self.import_export_btn.clicked.connect(self.show_import_export_dialog)
        export_layout.addWidget(self.import_export_btn)
        
        # 导出按钮
        self.export_btn = CustomButton("导出文件", button_type="primary")
        self.export_btn.clicked.connect(self.export_selected_files)
        export_layout.addWidget(self.export_btn)
        
        # 控制按钮
        import os
        trash_icon_path = os.path.join(os.path.dirname(__file__), "..", "icons", "trash.svg")
        clear_btn = CustomButton(trash_icon_path, button_type="normal", display_mode="icon", tooltip_text="清空所有项目")
        clear_btn.clicked.connect(self.clear_all)
        export_layout.addWidget(clear_btn)
        
        # 进度条
        self.progress_bar = CustomProgressBar()
        self.progress_bar.setInteractive(False)  # 禁用交互，只用于显示进度
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        export_layout.addWidget(self.progress_bar, 1)
        
        main_layout.addLayout(export_layout)
        
        # 初始化悬浮详细信息组件
        self.hover_tooltip = HoverTooltip(self)
        
        # 将按钮添加到悬浮信息目标控件
        self.hover_tooltip.set_target_widget(self.import_export_btn)
        self.hover_tooltip.set_target_widget(self.export_btn)
        self.hover_tooltip.set_target_widget(clear_btn)
    
    def add_file(self, file_info):
        """
        添加文件或文件夹到临时存储池
        
        Args:
            file_info (dict): 文件或文件夹信息字典
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
        
        # 创建横向卡片，传递display_name
        card = CustomFileHorizontalCard(file_info["path"], display_name=file_info["display_name"])
        
        # 连接信号
        card.clicked.connect(lambda path: self.on_card_clicked(path, card, file_info))
        card.doubleClicked.connect(lambda path: self.on_item_double_clicked(path))
        card.selectionChanged.connect(lambda selected, path: self.on_card_selection_changed(selected, path, file_info))
        card.renameRequested.connect(lambda path: self.on_card_rename_requested(path, file_info))
        card.deleteRequested.connect(lambda path: self.on_card_delete_requested(path, file_info))
        
        # 在拉伸因子之前添加卡片，确保拉伸因子始终在最后
        # 先移除拉伸因子
        if self.cards_layout.count() > 0 and self.cards_layout.itemAt(self.cards_layout.count() - 1).spacerItem():
            self.cards_layout.takeAt(self.cards_layout.count() - 1)
        
        # 添加到卡片布局
        self.cards_layout.addWidget(card)
        
        # 重新添加拉伸因子
        self.cards_layout.addStretch(1)
        
        # 存储卡片对象
        self.cards.append((card, file_info))
        
        # 如果是文件夹，启动线程计算体积
        if file_info["is_dir"]:
            self._calculate_folder_size(file_info["path"])
        
        # 更新统计信息
        self.update_stats()
        
        # 实时保存备份
        self.save_backup()
    

    
    def remove_file(self, file_path):
        """
        从临时存储池移除文件
        
        Args:
            file_path (str): 文件路径
        """
        # 查找并移除项目
        for i, (card, file_info) in enumerate(self.cards):
            if file_info["path"] == file_path:
                # 保存文件信息用于发出信号
                removed_file = file_info
                
                # 从项目列表中移除
                self.items.pop(i)
                
                # 从卡片布局中移除
                self.cards_layout.removeWidget(card)
                card.deleteLater()
                
                # 从卡片列表中移除
                self.cards.pop(i)
                
                # 发出信号通知文件选择器取消选中
                self.remove_from_selector.emit(removed_file)
                break
        
        # 确保拉伸因子存在
        has_stretch = any(self.cards_layout.itemAt(i).spacerItem() for i in range(self.cards_layout.count()))
        if not has_stretch:
            self.cards_layout.addStretch(1)
        
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
            
            # 移除所有卡片，但保留拉伸因子
            while self.cards_layout.count() > 0:
                item = self.cards_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.spacerItem():
                    # 保留拉伸因子，将其重新添加回布局
                    self.cards_layout.addItem(item)
                    break
            
            # 发出信号通知文件选择器取消所有选中
            for item in items_to_remove:
                self.remove_from_selector.emit(item)
            
            # 清空列表
            self.items.clear()
            self.cards.clear()
            # 更新统计信息
            self.update_stats()
            
            # 确保拉伸因子存在
            if not any(self.cards_layout.itemAt(i).spacerItem() for i in range(self.cards_layout.count())):
                self.cards_layout.addStretch(1)
            
            # 实时保存备份
            self.save_backup()
    

    
    def _format_file_size(self, size_bytes):
        """
        将文件大小转换为自适应单位(B、KB、MB、GB、TB)
        
        Args:
            size_bytes (int): 文件大小，单位字节
            
        Returns:
            str: 格式化后的文件大小字符串
        """
        if size_bytes == 0:
            return "0 B"
        
        # 定义单位顺序和转换因子
        units = ["B", "KB", "MB", "GB", "TB"]
        index = 0
        size = float(size_bytes)
        
        # 转换到合适的单位
        while size >= 1024 and index < len(units) - 1:
            size /= 1024
            index += 1
        
        # 格式化输出，保留两位小数
        if index == 0:
            return f"{int(size)} {units[index]}"
        else:
            return f"{size:.2f} {units[index]}"
    
    def update_stats(self):
        """
        更新统计信息
        """
        total_items = len(self.items)
        
        # 计算所有文件大小总和
        total_size = 0
        for item in self.items:
            if "size" in item and item["size"] is not None:
                total_size += item["size"]
        
        formatted_size = self._format_file_size(total_size)
        self.stats_label.setText(f" {total_items}个条目 | {formatted_size}")
    
    def on_card_clicked(self, path, card, file_info):
        """
        处理卡片点击事件
        
        Args:
            path: 文件路径
            card: 卡片对象
            file_info: 文件信息字典
        """
        # 发出左键点击信号，用于调用统一预览器
        self.item_left_clicked.emit(file_info)
    
    def on_card_selection_changed(self, selected, path, file_info):
        """
        处理卡片选中状态变化事件
        
        Args:
            selected: 是否选中
            path: 文件路径
            file_info: 文件信息字典
        """
        # 可以在这里添加选中状态变化后的处理逻辑
        pass
    
    def on_card_rename_requested(self, path, file_info):
        """
        处理卡片重命名请求
        
        Args:
            path: 文件路径
            file_info: 文件信息字典
        """
        # 调用现有的重命名方法
        # 由于重命名方法需要widget参数，我们可以传入None或者修改重命名方法
        # 这里我们修改重命名方法来适应新的调用方式
        self.rename_file(file_info, None)
    
    def on_card_delete_requested(self, path, file_info):
        """
        处理卡片删除请求
        
        Args:
            path: 文件路径
            file_info: 文件信息字典
        """
        # 调用现有的删除方法
        self.remove_file(path)
    
    def on_item_double_clicked(self, path):
        """
        双击项目事件处理
        
        Args:
            path: 文件路径
        """
        # 查找对应的文件信息
        for file_info in self.items:
            if file_info["path"] == path:
                self.open_file(file_info)
                break
    
    def rename_file(self, file_info, widget=None):
        """
        重命名文件（仅修改前端显示名称，保持原始后缀名）
        
        Args:
            file_info (dict): 文件信息字典
            widget (QWidget): 不再使用，保留参数以保持向后兼容
        """
        from freeassetfilter.widgets.D_widgets import CustomInputBox
        
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
            # 弹出自定义输入对话框，只显示和允许修改文件名主体
            input_box = CustomMessageBox(self)
            input_box.set_title("重命名")
            input_box.set_text("请输入新的文件名：")
            input_box.set_input(name_base)
            input_box.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])
            
            # 连接按钮点击信号
            button_clicked = None
            def on_button_clicked(index):
                nonlocal button_clicked
                button_clicked = index
                input_box.close()
            
            input_box.buttonClicked.connect(on_button_clicked)
            input_box.exec_()
            
            ok = button_clicked == 0
            new_name_input = input_box.get_input() if ok else ""
            
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
            
            # 更新卡片的显示
            for card, card_file_info in self.cards:
                if card_file_info["path"] == file_info["path"]:
                    # 更新卡片的文件信息
                    card_file_info["display_name"] = new_name
                    # 更新卡片的显示，传递新的display_name
                    card.set_file_path(file_info["path"], display_name=new_name)
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
        
        # 计算待导出文件的总大小
        total_file_size = self.calculate_total_file_size(all_files)
        
        # 获取目标目录的总容量和可用空间
        total_space, free_space = self.get_directory_space(target_dir)
        
        if total_space is None or free_space is None:
            # 获取空间信息失败，可能是网络存储或远程目录
            warning_msg = CustomMessageBox(self)
            warning_msg.set_title("警告")
            warning_msg.set_text("无法获取目标目录的可用空间信息，可能是网络存储或远程目录。\n"
                                "是否继续导出操作？")
            warning_msg.set_buttons(["继续", "取消"], Qt.Horizontal, ["primary", "normal"])
            
            user_choice = -1
            def on_button_clicked(button_index):
                nonlocal user_choice
                user_choice = button_index
                warning_msg.close()
            
            warning_msg.buttonClicked.connect(on_button_clicked)
            warning_msg.exec_()
            
            if user_choice != 0:  # 0表示继续
                return
        else:
            # 检查可用空间是否足够
            if free_space < total_file_size:
                # 空间不足，显示错误提示
                error_msg = CustomMessageBox(self)
                error_msg.set_title("空间不足")
                error_msg.set_text(f"目标目录可用空间不足！\n"
                                f"待导出文件总大小：{self._format_file_size(total_file_size)}\n"
                                f"目标目录可用空间：{self._format_file_size(free_space)}\n"
                                f"所需额外空间：{self._format_file_size(total_file_size - free_space)}")
                error_msg.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                error_msg.buttonClicked.connect(error_msg.close)
                error_msg.exec_()
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
    
    def on_folder_size_calculated(self, file_info):
        """
        处理文件夹体积计算完成信号
        
        Args:
            file_info (dict): 计算完成的文件夹信息
        """
        # 更新UI显示
        self.update_stats()
        
        # 更新卡片显示
        for card, card_file_info in self.cards:
            if card_file_info["path"] == file_info["path"]:
                card.set_file_path(file_info["path"], display_name=file_info["display_name"])
                break
        
        # 实时保存备份
        self.save_backup()
    
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
        from datetime import datetime
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
        
        # 移除所有卡片，但保留拉伸因子
        while self.cards_layout.count() > 0:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.spacerItem():
                # 保留拉伸因子，将其重新添加回布局
                self.cards_layout.addItem(item)
                break
        
        # 发出信号通知文件选择器取消所有选中
    
    def dragEnterEvent(self, event):
        """
        处理拖拽进入事件
        
        Args:
            event (QDragEnterEvent): 拖拽进入事件
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            # 添加拖拽视觉反馈
            self.setStyleSheet(f"background-color: #e8f4fc; border: 2px dashed #4a7abc; border-radius: {int(8 * self.dpi_scale)}px;")
    
    def dragMoveEvent(self, event):
        """
        处理拖拽移动事件
        
        Args:
            event (QDragMoveEvent): 拖拽移动事件
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def dragLeaveEvent(self, event):
        """
        处理拖拽离开事件
        
        Args:
            event (QDragLeaveEvent): 拖拽离开事件
        """
        # 恢复原始样式
        self.setStyleSheet("background-color: #ffffff;")
    
    def dropEvent(self, event):
        """
        处理拖拽释放事件
        
        Args:
            event (QDropEvent): 拖拽释放事件
        """
        # 恢复原始样式
        self.setStyleSheet("background-color: #ffffff;")
        
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            
            # 处理每个拖拽的文件/文件夹
            for url in urls:
                file_path = url.toLocalFile()
                
                if os.path.exists(file_path):
                    # 直接在储存池中导入该文件/文件夹
                    self._add_dropped_item(file_path)
            
            event.acceptProposedAction()
    
    def _add_dropped_item(self, file_path):
        """
        添加拖拽的文件或文件夹到储存池
        
        Args:
            file_path (str): 文件或文件夹路径
        """
        if os.path.isfile(file_path):
            # 单个文件
            file_info = self._get_file_info(file_path)
            if file_info:
                self.add_file(file_info)
        elif os.path.isdir(file_path):
            # 文件夹：直接添加文件夹到存储池
            file_info = self._get_file_info(file_path)
            if file_info:
                self.add_file(file_info)
    
    def _get_file_info(self, file_path):
        """
        获取文件或文件夹信息
        
        Args:
            file_path (str): 文件或文件夹路径
        
        Returns:
            dict: 文件或文件夹信息字典
        """
        from datetime import datetime
        try:
            file_stat = os.stat(file_path)
            file_name = os.path.basename(file_path)
            is_dir = os.path.isdir(file_path)
            
            file_info = {
                "name": file_name,
                "path": file_path,
                "is_dir": is_dir,
                "size": None if is_dir else file_stat.st_size,
                "modified": datetime.fromtimestamp(file_stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "created": datetime.fromtimestamp(file_stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
                "suffix": os.path.splitext(file_name)[1].lower() if not is_dir else "",
                "display_name": file_name,
                "original_name": file_name
            }
            
            return file_info
        except Exception as e:
            print(f"获取文件/文件夹信息失败: {e}")
            return None
    
    def _add_folder_contents(self, folder_path):
        """
        递归添加文件夹中的所有文件到储存池
        
        Args:
            folder_path (str): 文件夹路径
        """
        try:
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    file_info = self._get_file_info(file_path)
                    if file_info:
                        self.add_file(file_info)
        except Exception as e:
            print(f"添加文件夹内容失败: {e}")
        self.items.clear()
        self.cards.clear()
        # 更新统计信息
        self.update_stats()
        
        # 确保拉伸因子存在
        if not any(self.cards_layout.itemAt(i).spacerItem() for i in range(self.cards_layout.count())):
            self.cards_layout.addStretch(1)
        
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
    
    def get_directory_space(self, directory):
        """
        获取目录所在磁盘的总容量和可用空间
        
        Args:
            directory (str): 目录路径
            
        Returns:
            tuple: (总容量字节数, 可用空间字节数)，如果获取失败返回(None, None)
        """
        try:
            if sys.platform == "win32":
                # Windows系统
                import ctypes
                free_bytes = ctypes.c_ulonglong(0)
                total_bytes = ctypes.c_ulonglong(0)
                # 调用Windows API获取磁盘空间
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(directory), None, ctypes.byref(total_bytes), ctypes.byref(free_bytes))
                return total_bytes.value, free_bytes.value
            else:
                # Linux/macOS系统
                statvfs = os.statvfs(directory)
                total_bytes = statvfs.f_frsize * statvfs.f_blocks
                free_bytes = statvfs.f_frsize * statvfs.f_bavail
                return total_bytes, free_bytes
        except Exception as e:
            print(f"获取目录空间失败: {str(e)}")
            return None, None
    
    def _calculate_folder_size(self, folder_path):
        """
        计算文件夹体积的线程函数
        
        Args:
            folder_path (str): 文件夹路径
        """
        import threading
        import os
        
        def calculate_size_thread():
            """实际计算文件夹大小的线程函数"""
            total_size = 0
            try:
                for root, dirs, files in os.walk(folder_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        try:
                            total_size += os.path.getsize(file_path)
                        except Exception as e:
                            print(f"计算文件 {file_path} 大小失败: {str(e)}")
            except Exception as e:
                print(f"计算文件夹 {folder_path} 大小失败: {str(e)}")
            
            # 查找对应的文件信息并发送信号
            for file_info in self.items:
                if file_info["path"] == folder_path:
                    file_info["size"] = total_size
                    self.folder_size_calculated.emit(file_info)
                    break
        
        # 启动线程
        thread = threading.Thread(target=calculate_size_thread)
        thread.daemon = True
        thread.start()
    
    def calculate_total_file_size(self, files):
        """
        计算待导出文件的总大小
        
        Args:
            files (list): 文件信息列表
            
        Returns:
            int: 总大小字节数
        """
        total_size = 0
        for file_info in files:
            if "size" in file_info and file_info["size"] is not None:
                total_size += file_info["size"]
            else:
                # 如果没有size信息，尝试获取
                try:
                    if os.path.isfile(file_info["path"]):
                        file_size = os.path.getsize(file_info["path"])
                        total_size += file_size
                    elif os.path.isdir(file_info["path"]):
                        # 递归计算目录大小
                        for root, dirs, files_in_dir in os.walk(file_info["path"]):
                            for file in files_in_dir:
                                file_path = os.path.join(root, file)
                                total_size += os.path.getsize(file_path)
                except Exception as e:
                    print(f"计算文件大小失败: {str(e)}")
        return total_size
    
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
