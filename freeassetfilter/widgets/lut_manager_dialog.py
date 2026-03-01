#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

LUT管理弹窗
使用CustomMessageBox作为基础，CustomFileHorizontalCard显示LUT文件
"""

import os
import time
import uuid
from pathlib import Path
from typing import Optional, List, Callable

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QFileDialog, QLineEdit, QSizePolicy, QApplication
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPixmap

from freeassetfilter.widgets.message_box import CustomMessageBox
from freeassetfilter.widgets.file_horizontal_card import CustomFileHorizontalCard
from freeassetfilter.widgets.smooth_scroller import SmoothScroller, D_ScrollBar
from freeassetfilter.utils.lut_utils import (
    LUTInfo, validate_lut_file, copy_lut_file, remove_lut_file,
    get_lut_display_name, load_lut_from_settings, save_lut_to_settings,
    remove_lut_from_settings, get_lut_storage_dir, get_lut_preview_dir
)
from freeassetfilter.core.lut_preview_generator import generate_lut_preview, create_default_reference_image
from freeassetfilter.utils.app_logger import info, debug, warning, error


class LutManagerDialog(CustomMessageBox):
    """
    LUT管理弹窗
    基于CustomMessageBox，使用CustomFileHorizontalCard显示LUT文件列表
    """
    
    # 信号定义
    lutSelected = Signal(str)  # LUT选择信号（LUT文件路径）
    lutCleared = Signal()  # LUT清除信号
    
    def __init__(self, parent: Optional[QWidget] = None, settings_manager=None):
        """
        初始化LUT管理弹窗
        
        Args:
            parent: 父窗口
            settings_manager: 设置管理器实例
        """
        super().__init__(parent)
        
        self.settings_manager = settings_manager
        self.lut_list: List[LUTInfo] = []
        self.lut_cards = []  # 存储卡片和对应的LUT信息
        self.selected_lut_id: Optional[str] = None
        self.active_lut_id: Optional[str] = None
        self._clicked_button_index: int = -1
        
        # 获取DPI缩放因子
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 创建参考图像（如果不存在）
        self._ensure_reference_image()
        
        # 初始化UI
        self._init_ui()
        
        # 加载LUT列表
        self._load_lut_list()
    
    def _ensure_reference_image(self):
        """确保参考图像存在"""
        base_dir = Path(__file__).parent.parent.parent
        reference_path = base_dir / "data" / "reference.png"
        
        if not reference_path.exists():
            create_default_reference_image(str(reference_path))
    
    def _init_ui(self):
        """初始化UI"""
        # 设置标题
        self.set_title("LUT管理")
        
        # 创建滚动区域（参考收藏夹弹窗的实现）
        self._create_scroll_area()
        
        # 设置按钮
        self.set_buttons(
            ["添加新LUT", "关闭LUT", "取消"],
            orientations=Qt.Horizontal,
            button_types=["primary", "secondary", "normal"]
        )
        
        # 连接按钮信号
        self.buttonClicked.connect(self._on_button_clicked)
        
        # 设置弹窗大小（横向宽度缩小为原来的一半）
        self.setMinimumSize(int(300 * self.dpi_scale), int(400 * self.dpi_scale))
        self.resize(int(300 * self.dpi_scale), int(450 * self.dpi_scale))
    
    def _create_scroll_area(self):
        """创建滚动区域（参考收藏夹弹窗）"""
        # 获取颜色设置
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        
        if hasattr(app, 'settings_manager'):
            settings_manager = app.settings_manager
            base_color = settings_manager.get_setting("appearance.colors.base_color", "#1E1E1E")
            normal_color = settings_manager.get_setting("appearance.colors.normal_color", "#808080")
            secondary_color = settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
            auxiliary_color = settings_manager.get_setting("appearance.colors.auxiliary_color", "#2D2D2D")
        else:
            base_color = "#1E1E1E"
            normal_color = "#808080"
            secondary_color = "#333333"
            auxiliary_color = "#2D2D2D"
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # 设置滚动条
        scroll_area.setVerticalScrollBar(D_ScrollBar(scroll_area, Qt.Vertical))
        scroll_area.verticalScrollBar().apply_theme_from_settings()
        
        # 应用平滑滚动
        SmoothScroller.apply_to_scroll_area(scroll_area)
        
        # 设置样式
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
        scroll_area.setMinimumWidth(0)  # 允许滚动区域随窗口缩小
        
        # 创建列表内容容器
        list_content = QWidget()
        list_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        list_content.setMinimumWidth(0)  # 允许内容容器随窗口缩小
        list_content_layout = QVBoxLayout(list_content)
        list_content_layout.setContentsMargins(0, 0, 0, 0)
        list_content_layout.setSpacing(int(4 * self.dpi_scale))
        
        self.list_content = list_content
        self.list_content_layout = list_content_layout
        
        scroll_area.setWidget(list_content)
        
        # 添加到CustomMessageBox的list_layout
        self.list_layout.addWidget(scroll_area)
        self.list_widget.show()
    
    def _load_lut_list(self):
        """加载LUT列表"""
        if self.settings_manager:
            self.lut_list = load_lut_from_settings(self.settings_manager)
            self.active_lut_id = self.settings_manager.get_setting("video.active_lut_id", None)
        
        self._refresh_lut_cards()
    
    def _refresh_lut_cards(self):
        """刷新LUT卡片显示"""
        # 清除现有卡片
        while self.list_content_layout.count():
            item = self.list_content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.lut_cards.clear()
        
        # 创建新卡片
        for lut_info in self.lut_list:
            card = self._create_lut_card(lut_info)
            self.list_content_layout.addWidget(card)
            self.lut_cards.append({'card': card, 'lut_info': lut_info})
        
        # 添加弹性空间
        self.list_content_layout.addStretch()
    
    def _create_lut_card(self, lut_info: LUTInfo) -> CustomFileHorizontalCard:
        """
        创建LUT卡片（参考收藏夹实现）
        
        Args:
            lut_info: LUT信息
            
        Returns:
            CustomFileHorizontalCard: LUT卡片
        """
        # 创建卡片，传入显示名称
        card = CustomFileHorizontalCard(
            file_path=lut_info.path,
            parent=self.list_content,
            enable_multiselect=False,
            display_name=lut_info.name,
            single_line_mode=False
        )
        
        # 设置路径存在状态
        card.set_path_exists(os.path.exists(lut_info.path))
        
        # 设置卡片尺寸策略，允许收缩以适应窄窗口
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        card.setMinimumWidth(0)
        
        # 设置自定义第二行文本显示UUID
        card.set_custom_info_text(f"UUID: {lut_info.id}")
        
        # 使用LUT预览图作为图标
        preview_dir = get_lut_preview_dir()
        preview_path = os.path.join(preview_dir, f"{lut_info.id}_preview.png")
        if os.path.exists(preview_path):
            try:
                from PySide6.QtGui import QPixmap, QImage
                scaled_icon_size = int(40 * self.dpi_scale)
                image = QImage(preview_path)
                if not image.isNull():
                    pixmap = QPixmap.fromImage(image)
                    card._set_icon_pixmap(pixmap, scaled_icon_size)
            except Exception as e:
                warning(f"设置LUT预览图失败: {e}")
        
        # 连接卡片信号（参考收藏夹实现）
        card.clicked.connect(lambda path, lut=lut_info: self._on_lut_card_clicked(lut))
        card.renameRequested.connect(lambda path, lut=lut_info: self._on_lut_rename_requested(lut.id, path))
        card.deleteRequested.connect(lambda path, lut=lut_info: self._on_lut_delete_requested(lut.id, path))
        
        return card
    
    def _on_lut_card_clicked(self, lut_info: LUTInfo):
        """LUT卡片点击处理"""
        # 更新选中状态
        self.selected_lut_id = lut_info.id
        
        # 发射选择信号
        self.lutSelected.emit(lut_info.path)
        
        # 保存激活状态
        if self.settings_manager:
            self.settings_manager.set_setting("video.active_lut_id", lut_info.id)
            self.settings_manager.save_settings()
        
        # 关闭对话框
        self.accept()
    
    def _on_lut_rename_requested(self, lut_id: str, file_path: str):
        """LUT重命名请求处理"""
        # 查找LUT信息
        lut_info = None
        for info in self.lut_list:
            if info.id == lut_id:
                lut_info = info
                break
        
        if not lut_info:
            return
        
        # 使用CustomMessageBox显示输入对话框
        input_dialog = CustomMessageBox(self)
        input_dialog.set_title("重命名LUT")
        input_dialog.set_text("请输入新名称:")
        input_dialog.set_input(text=lut_info.name)
        input_dialog.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])
        
        def on_button_clicked(idx):
            if idx == 0:
                new_name = input_dialog.get_input().strip()
                if new_name:
                    self._rename_lut(lut_id, new_name)
            input_dialog.close()
        
        input_dialog.buttonClicked.connect(on_button_clicked)
        input_dialog.exec()
    
    def _rename_lut(self, lut_id: str, new_name: str):
        """重命名LUT"""
        # 查找LUT信息
        for lut_info in self.lut_list:
            if lut_info.id == lut_id:
                # 更新名称
                lut_info.name = new_name
                
                # 保存到设置
                if self.settings_manager:
                    save_lut_to_settings(self.settings_manager, lut_info)
                
                # 刷新显示
                self._refresh_lut_cards()
                break
    
    def _on_lut_delete_requested(self, lut_id: str, file_path: str):
        """LUT删除请求处理"""
        # 使用CustomMessageBox显示确认对话框
        confirm_dialog = CustomMessageBox(self)
        confirm_dialog.set_title("确认删除")
        confirm_dialog.set_text(f"确定要删除这个LUT吗？\n此操作不可恢复。")
        confirm_dialog.set_buttons(["删除", "取消"], Qt.Horizontal, ["danger", "normal"])
        
        def on_confirm_button_clicked(idx):
            if idx == 0:
                self._delete_lut(lut_id, file_path)
            confirm_dialog.close()
        
        confirm_dialog.buttonClicked.connect(on_confirm_button_clicked)
        confirm_dialog.exec()
    
    def _delete_lut(self, lut_id: str, file_path: str):
        """删除LUT"""
        # 删除文件
        remove_lut_file(file_path)
        
        # 删除预览图缓存
        preview_path = Path(get_lut_storage_dir()).parent / "lut_previews" / f"{lut_id}_preview.png"
        if preview_path.exists():
            try:
                preview_path.unlink()
            except:
                pass
        
        # 从设置中移除
        if self.settings_manager:
            remove_lut_from_settings(self.settings_manager, lut_id)
        
        # 从列表中移除
        self.lut_list = [lut for lut in self.lut_list if lut.id != lut_id]
        
        # 清除选中状态
        if self.selected_lut_id == lut_id:
            self.selected_lut_id = None
        
        # 刷新显示
        self._refresh_lut_cards()
    
    def _on_button_clicked(self, button_index: int):
        """
        按钮点击处理
        
        Args:
            button_index: 按钮索引 (0=添加新LUT, 1=关闭LUT, 2=取消)
        """
        # 保存按钮索引用于exec方法中判断
        self._clicked_button_index = button_index
        
        if button_index == 0:
            # 添加新LUT - 打开文件选择对话框
            self._add_new_lut()
        elif button_index == 1:
            # 关闭LUT - 检查当前是否有激活的LUT
            self._close_or_cancel_lut()
        elif button_index == 2:
            # 取消 - 直接关闭弹窗
            self.reject()
    
    def _add_new_lut(self):
        """添加新LUT（带进度条）"""
        _debug_log("开始添加 LUT")
        
        # 打开文件选择对话框
        _debug_log("打开文件选择对话框")
        _t_start = time.perf_counter()
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择LUT文件",
            "",
            "LUT Files (*.cube);;All Files (*)"
        )
        _t_end = time.perf_counter()
        _debug_log(f"getOpenFileName 返回，耗时: {(_t_end-_t_start)*1000:.1f}ms")
        
        if not file_path:
            _debug_log("用户取消选择文件")
            return
        
        _debug_log(f"用户选择了文件: {file_path}")
        
        # 验证LUT文件
        _debug_log("开始验证 LUT 文件")
        _t0 = time.perf_counter()
        is_valid, error_msg = validate_lut_file(file_path)
        _t1 = time.perf_counter()
        _debug_log(f"LUT 文件验证完成，耗时: {(_t1-_t0)*1000:.1f}ms")
        if not is_valid:
            _debug_log(f"LUT 文件验证失败: {error_msg}")
            # 显示错误信息
            error_dialog = CustomMessageBox(self)
            error_dialog.set_title("错误")
            error_dialog.set_message(f"无效的LUT文件:\n{error_msg}")
            error_dialog.set_buttons(["确定"], orientations=Qt.Horizontal, button_types=["primary"])
            error_dialog.exec()
            return
        
        _debug_log("LUT 文件验证通过")
        
        # 创建进度弹窗
        _debug_log("创建进度弹窗")
        from freeassetfilter.widgets.progress_widgets import D_ProgressBar
        progress_dialog = CustomMessageBox(self)
        progress_dialog.set_title("导入LUT")
        progress_dialog.set_text("正在导入LUT文件...")
        
        # 创建进度条
        progress_bar = D_ProgressBar()
        progress_bar.setRange(0, 4)
        progress_bar.setValue(0)
        progress_bar.setInteractive(False)
        progress_dialog.set_progress(progress_bar)
        
        # 禁用关闭按钮，防止用户在处理过程中关闭
        progress_dialog.setWindowFlags(progress_dialog.windowFlags() & ~Qt.WindowCloseButtonHint)
        
        progress_dialog.show()
        
        # 处理事件以确保进度条显示
        QApplication.processEvents()
        
        # 生成LUT ID
        lut_id = str(uuid.uuid4())
        _debug_log(f"生成 LUT ID: {lut_id}")
        
        # 更新进度：复制文件
        progress_bar.setValue(1)
        QApplication.processEvents()
        
        # 复制LUT文件到应用目录
        _debug_log("开始复制 LUT 文件")
        success, result = copy_lut_file(file_path, lut_id)
        if not success:
            progress_dialog.close()
            _debug_log(f"复制 LUT 文件失败: {result}")
            # 显示错误信息
            error_dialog = CustomMessageBox(self)
            error_dialog.set_title("错误")
            error_dialog.set_message(f"复制LUT文件失败:\n{result}")
            error_dialog.set_buttons(["确定"], orientations=Qt.Horizontal, button_types=["primary"])
            error_dialog.exec()
            return
        
        _debug_log(f"LUT 文件已复制到: {result}")
        
        # 更新进度：解析LUT
        progress_bar.setValue(2)
        QApplication.processEvents()
        
        # 获取LUT信息
        _debug_log("开始解析 LUT 信息")
        from freeassetfilter.utils.lut_utils import CubeLUTParser
        parser = CubeLUTParser(result)
        parser.parse()
        info = parser.get_info()
        _debug_log(f"LUT 解析完成: size={info.get('size')}, is_3d={info.get('is_3d')}")
        
        # 更新进度：生成预览图
        progress_bar.setValue(3)
        QApplication.processEvents()

        # 生成LUT预览图
        debug("开始生成 LUT 预览图")
        try:
            from freeassetfilter.core.lut_preview_generator import generate_lut_preview
            generate_lut_preview(result, lut_id)
            debug("LUT 预览图生成完成")
        except Exception as e:
            warning(f"生成LUT预览图失败: {e}")
        
        # 创建LUT信息
        display_name = get_lut_display_name(file_path)
        lut_info = LUTInfo(
            id=lut_id,
            name=display_name,
            path=result,
            preview_path="",
            size=info.get('size', 0),
            is_3d=info.get('is_3d', True)
        )
        
        # 添加到列表
        self.lut_list.append(lut_info)
        
        # 保存到设置
        if self.settings_manager:
            save_lut_to_settings(self.settings_manager, lut_info)
        
        # 更新进度：完成
        progress_bar.setValue(4)
        QApplication.processEvents()
        
        # 短暂延迟让用户看到完成状态
        from PySide6.QtCore import QTimer
        QTimer.singleShot(200, progress_dialog.close)
        
        # 刷新显示
        self._refresh_lut_cards()
    
    def _close_or_cancel_lut(self):
        """
        关闭LUT或取消操作
        如果当前有激活的LUT效果，则关闭它；否则执行取消操作
        """
        # 检查是否有激活的LUT
        if self.active_lut_id:
            # 有激活的LUT，关闭它
            self.lutCleared.emit()
            # 清除激活状态
            if self.settings_manager:
                self.settings_manager.set_setting("video.active_lut_id", None)
                self.settings_manager.save_settings()
            self.accept()
        else:
            # 没有激活的LUT，执行取消操作
            self.reject()
    
    def get_selected_lut(self) -> Optional[LUTInfo]:
        """
        获取选中的LUT信息
        
        Returns:
            Optional[LUTInfo]: 选中的LUT信息，未选择则返回None
        """
        if not self.selected_lut_id:
            return None
        
        for lut_info in self.lut_list:
            if lut_info.id == self.selected_lut_id:
                return lut_info
        
        return None
    
    def exec(self):
        """执行对话框"""
        result = super().exec()
        
        # 检查点击的是哪个按钮
        if self._clicked_button_index == 0:
            # 添加新LUT按钮 - 已经在_add_new_lut中处理
            pass
        elif self._clicked_button_index == 1:
            # 关闭LUT按钮 - 已经在_on_button_clicked中处理
            pass
        elif self._clicked_button_index == 2:
            # 取消按钮 - 直接关闭，不做任何操作
            pass
        else:
            # 其他情况（如用户点击X关闭）- 检查是否有选中的LUT
            selected_lut = self.get_selected_lut()
            if selected_lut:
                self.lutSelected.emit(selected_lut.path)
                # 保存激活状态
                if self.settings_manager:
                    self.settings_manager.set_setting("video.active_lut_id", selected_lut.id)
                    self.settings_manager.save_settings()
        
        return result
