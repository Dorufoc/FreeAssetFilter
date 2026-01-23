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

2. 商业使用：需联系 qpdrfc123@gmail.com 获取书面授权�?
项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE
独立的字体预览器组件
提供字体文件预览、示例文本展示和字体信息查看功能
"""

import sys
import os

# 添加项目根目录到Python路径，解决直接运行时的导入问题
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QFileDialog, QLabel, QScrollArea, QGroupBox, QGridLayout,
    QTextEdit, QSlider, QComboBox, QMessageBox
)
from PyQt5.QtGui import (
    QFont, QFontDatabase, QPainter, QPen, QColor, QCursor,
    QIcon, QTextCursor
)
from PyQt5.QtCore import (
    Qt, QPoint, QRect, QSize, QTimer, pyqtSignal
)




class FontPreviewWidget(QWidget):
    """
    字体预览部件，支持显示不同样式的示例文本
    """
    font_info_changed = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        
        # 获取应用实例和DPI缩放因子
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 字体数据
        self.current_font_path = ""
        self.current_font_id = -1
        self.current_font = QFont()
        self.font_size = 24
        self.font_style = "Regular"
        
        # 示例文本
        self.sample_texts = {
            "全部示例": "ABCDEFGHIJKLMNOPQRSTUVWXYZ\nabcdefghijklmnopqrstuvwxyz\n\n0123456789\n\n!@#$%^&*()_+-=[]{}|;:,.<>?'\"'\n\n天地玄黄，宇宙洪荒。日月盈昃，辰宿列张。寒来暑往，秋收冬藏。闰余成岁，律吕调阳。",
            "英文大小写": "ABCDEFGHIJKLMNOPQRSTUVWXYZ\nabcdefghijklmnopqrstuvwxyz",
            "阿拉伯数字": "0123456789",
            "常见标点符号": "!@#$%^&*()_+-=[]{}|;:,.<>?'\"'",
            "中文汉字示例": "天地玄黄，宇宙洪荒。日月盈昃，辰宿列张。寒来暑往，秋收冬藏。闰余成岁，律吕调阳。"
        }
        self.current_sample_type = "全部示例"
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化预览部件UI
        """
        layout = QVBoxLayout(self)
        
        # 应用DPI缩放因子到边距和间距
        scaled_margin = int(10 * self.dpi_scale)
        scaled_spacing = int(5 * self.dpi_scale)
        layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        layout.setSpacing(scaled_spacing)
        
        # 示例文本选择
        self.sample_selector = QComboBox()
        self.sample_selector.addItems(self.sample_texts.keys())
        self.sample_selector.currentTextChanged.connect(self.change_sample_text)
        layout.addWidget(self.sample_selector)
        
        # 字体大小滑块
        size_layout = QHBoxLayout()
        size_layout.setSpacing(scaled_spacing)
        size_label = QLabel("字体大小:")
        self.size_value_label = QLabel(str(self.font_size))
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(8, 72)
        self.size_slider.setValue(self.font_size)
        self.size_slider.valueChanged.connect(self.change_font_size)
        
        size_layout.addWidget(size_label)
        size_layout.addWidget(self.size_slider)
        size_layout.addWidget(self.size_value_label)
        size_layout.addStretch()
        layout.addLayout(size_layout)
        
        # 预览文本区域
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setStyleSheet("background-color: white; color: black; font-family: Arial;")
        scaled_min_height = int(200 * self.dpi_scale)
        self.preview_text.setMinimumHeight(scaled_min_height)
        self.preview_text.setPlainText(self.sample_texts[self.current_sample_type])
        layout.addWidget(self.preview_text)
    
    def set_font(self, font_path):
        """
        设置要预览的字体
        
        Args:
            font_path (str): 字体文件路径
        """
        if os.path.exists(font_path):
            # 加载字体文件
            font_db = QFontDatabase()
            self.current_font_id = font_db.addApplicationFont(font_path)
            
            if self.current_font_id != -1:
                # 获取字体家族名称
                font_families = font_db.applicationFontFamilies(self.current_font_id)
                if font_families:
                    self.current_font_path = font_path
                    self.current_font = QFont(font_families[0], self.font_size)
                    self.update_preview()
                    self.update_font_info()
                    return True
        return False
    
    def change_sample_text(self, sample_type):
        """
        切换示例文本类型
        """
        self.current_sample_type = sample_type
        self.preview_text.setPlainText(self.sample_texts[sample_type])
        self.update_preview()
    
    def change_font_size(self, size):
        """
        改变字体大小
        """
        self.font_size = size
        self.size_value_label.setText(str(size))
        self.current_font.setPointSize(size)
        self.update_preview()
    
    def update_preview(self):
        """
        更新预览文本的字体样�?
        """
        cursor = self.preview_text.textCursor()
        self.preview_text.selectAll()
        self.preview_text.setCurrentFont(self.current_font)
        self.preview_text.setTextCursor(cursor)
    
    def update_font_info(self):
        """
        更新字体信息并发送信�?
        """
        font_info = {
            "family": self.current_font.family(),
            "size": self.font_size,
            "style": self.font_style,
            "path": self.current_font_path,
            "file_name": os.path.basename(self.current_font_path)
        }
        self.font_info_changed.emit(font_info)
    
    def clear_font(self):
        """
        清除当前字体，恢复默认状�?
        """
        if self.current_font_id != -1:
            font_db = QFontDatabase()
            font_db.removeApplicationFont(self.current_font_id)
            self.current_font_id = -1
        
        self.current_font_path = ""
        self.current_font = QFont("Arial", self.font_size)
        self.update_preview()
        self.update_font_info()


class FontPreviewer(QMainWindow):
    """
    字体预览器主窗口
    """
    
    def __init__(self):
        super().__init__()
        
        # 获取应用实例和DPI缩放因子
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        self.setWindowTitle("字体预览器")
        
        # 应用DPI缩放因子到窗口大小
        scaled_width = int(500 * self.dpi_scale)
        scaled_height = int(400 * self.dpi_scale)
        self.setGeometry(100, 100, scaled_width, scaled_height)
        
        # 创建UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化用户界�?
        """
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 应用DPI缩放因子到布局参数
        scaled_margin = int(10 * self.dpi_scale)
        scaled_spacing = int(10 * self.dpi_scale)
        scaled_small_spacing = int(5 * self.dpi_scale)
        scaled_panel_min_width = int(140 * self.dpi_scale)
        scaled_radius = int(6 * self.dpi_scale)
        scaled_padding = int(10 * self.dpi_scale)
        
        # 创建主布局
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        main_layout.setSpacing(scaled_spacing)
        
        # 设置窗口背景色
        # 获取主题颜色
        app = QApplication.instance()
        background_color = "#2D2D2D"  # 默认窗口背景色
        if hasattr(app, 'settings_manager'):
            background_color = app.settings_manager.get_setting("appearance.colors.window_background", "#2D2D2D")
        self.setStyleSheet(f"background-color: {background_color};")
        
        # 1. 字体预览区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
        .QScrollArea {
            background-color: transparent;
            border: none;
        }
        .QScrollArea > QWidget > QWidget {
            background-color: transparent;
        }
        """)
        
        self.font_widget = FontPreviewWidget()
        self.font_widget.font_info_changed.connect(self.update_font_info)
        scroll_area.setWidget(self.font_widget)
        
        from freeassetfilter.widgets.smooth_scroller import SmoothScroller
        SmoothScroller.apply_to_scroll_area(scroll_area)
        
        main_layout.addWidget(scroll_area, 1)
        
        # 2. 信息和控制面�?
        control_panel = QWidget()
        control_panel.setMinimumWidth(scaled_panel_min_width)
        control_panel.setStyleSheet(f"background-color: white; border-radius: {scaled_radius}px; padding: {scaled_padding}px;")
        control_layout = QVBoxLayout(control_panel)
        control_layout.setSpacing(scaled_spacing)
        
        # 文件操作区域
        file_group = QGroupBox("文件操作")
        
        # 应用DPI缩放因子到组框样式
        # 使用全局默认字体大小
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 18)
        scaled_group_font_size = int(default_font_size * self.dpi_scale)
        scaled_group_border_radius = int(8 * self.dpi_scale)
        scaled_group_padding = int(15 * self.dpi_scale)
        scaled_group_title_left = int(8 * self.dpi_scale)
        scaled_group_title_top = int(5 * self.dpi_scale)
        scaled_group_title_padding = int(4 * self.dpi_scale)
        
        file_group.setStyleSheet(f"""
        .QGroupBox {
            font-size: {scaled_group_font_size}px;
            font-weight: bold;
            color: #333;
            border: 1px solid #e0e0e0;
            border-radius: {scaled_group_border_radius}px;
            padding: {scaled_group_padding}px;
            background-color: #fafafa;
        }
        .QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: {scaled_group_title_left}px;
            top: -{scaled_group_title_top}px;
            padding: 0 {scaled_group_title_padding}px;
            background-color: #fafafa;
        }
        """)
        file_layout = QVBoxLayout()
        file_layout.setSpacing(scaled_small_spacing)
        
        self.open_button = QPushButton("打开字体文件")
        self.open_button.clicked.connect(self.open_file)
        
        # 应用DPI缩放因子到按钮样式
        scaled_button_radius = int(4 * self.dpi_scale)
        scaled_button_padding_v = int(6 * self.dpi_scale)
        scaled_button_padding_h = int(10 * self.dpi_scale)
        # 使用全局默认字体大小
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 18)
        scaled_button_font_size = int(default_font_size * self.dpi_scale)
        
        self.open_button.setStyleSheet(f"""
        .QPushButton {
            background-color: #1976d2;
            color: white;
            border: none;
            border-radius: {scaled_button_radius}px;
            padding: {scaled_button_padding_v}px {scaled_button_padding_h}px;
            font-size: {scaled_button_font_size}px;
            font-weight: 500;
        }
        .QPushButton:hover {
            background-color: #1565c0;
        }
        .QPushButton:pressed {
            background-color: #0d47a1;
        }
        """)
        file_layout.addWidget(self.open_button)
        
        self.clear_button = QPushButton("清除字体")
        self.clear_button.clicked.connect(self.clear_font)
        self.clear_button.setStyleSheet(f"""
        .QPushButton {
            background-color: #f5f5f5;
            color: #333;
            border: 1px solid #e0e0e0;
            border-radius: {scaled_button_radius}px;
            padding: {scaled_button_padding_v}px {scaled_button_padding_h}px;
            font-size: {scaled_button_font_size}px;
            font-weight: 500;
        }
        .QPushButton:hover {
            background-color: #e0e0e0;
        }
        .QPushButton:pressed {
            background-color: #bdbdbd;
        }
        """)
        file_layout.addWidget(self.clear_button)
        
        file_group.setLayout(file_layout)
        control_layout.addWidget(file_group)
        
        # 字体信息区域
        info_group = QGroupBox("字体信息")
        info_group.setStyleSheet(f"""
        .QGroupBox {
            font-size: {scaled_group_font_size}px;
            font-weight: bold;
            color: #333;
            border: 1px solid #e0e0e0;
            border-radius: {scaled_group_border_radius}px;
            padding: {scaled_group_padding}px;
            background-color: #fafafa;
        }
        .QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: {scaled_group_title_left}px;
            top: -{scaled_group_title_top}px;
            padding: 0 {scaled_group_title_padding}px;
            background-color: #fafafa;
        }
        """)
        self.info_layout = QGridLayout()
        self.info_layout.setSpacing(scaled_small_spacing)
        
        # 初始化字体信息显�?
        self.font_info_labels = {
            "文件名称": QLabel("未选择文件"),
            "字体家族": QLabel("-"),
            "字体大小": QLabel("-"),
            "字体样式": QLabel("-"),
            "文件路径": QLabel("-"),
        }
        
        # 应用DPI缩放因子到标签样式
        # 使用全局默认字体大小
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 18)
        scaled_label_font_size = int(default_font_size * self.dpi_scale)
        scaled_label_radius = int(2 * self.dpi_scale)
        scaled_label_padding = int(3 * self.dpi_scale)
        
        row = 0
        for key, label in self.font_info_labels.items():
            key_label = QLabel(key + ":")
            key_label.setStyleSheet("font-weight: bold; color: #555;")
            self.info_layout.addWidget(key_label, row, 0)
            label.setWordWrap(True)
            label.setStyleSheet(f"color: #333; background-color: white; border: 1px solid #e0e0e0; border-radius: {scaled_label_radius}px; padding: {scaled_label_padding}px; font-size: {scaled_label_font_size}px;")
            self.info_layout.addWidget(label, row, 1)
            row += 1
        
        info_group.setLayout(self.info_layout)
        control_layout.addWidget(info_group)
        
        # 使用说明区域
        help_group = QGroupBox("使用说明")
        help_group.setStyleSheet(f"""
        .QGroupBox {
            font-size: {scaled_group_font_size}px;
            font-weight: bold;
            color: #333;
            border: 1px solid #e0e0e0;
            border-radius: {scaled_group_border_radius}px;
            padding: {scaled_group_padding}px;
            background-color: #fafafa;
        }
        .QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: {scaled_group_title_left}px;
            top: -{scaled_group_title_top}px;
            padding: 0 {scaled_group_title_padding}px;
            background-color: #fafafa;
        }
        """)
        help_layout = QVBoxLayout()
        
        help_text = QLabel(
            "操作说明：\n"
            "• 选择不同的示例文本类型查看效果\n"
            "• 使用滑块调整字体大小\n"
            "• 支持TTF、OTF等常见字体格式\n"
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet(f"color: #555; font-size: {scaled_label_font_size}px; line-height: 1.5;")
        help_layout.addWidget(help_text)
        
        help_group.setLayout(help_layout)
        control_layout.addWidget(help_group)
        
        control_layout.addStretch(1)
        
        main_layout.addWidget(control_panel)
    
    def open_file(self):
        """
        打开字体文件
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self, "打开字体文件", "", 
            "字体文件 (*.ttf *.otf *.ttc *.woff *.woff2);;所有文�?(*)"
        )
        
        if file_path:
            if self.font_widget.set_font(file_path):
                # 更新窗口标题
                file_name = os.path.basename(file_path)
                self.setWindowTitle(f"字体预览�?- {file_name}")
            else:
                # 字体加载失败
                from freeassetfilter.widgets.D_widgets import CustomMessageBox
                msg_box = CustomMessageBox(self)
                msg_box.set_title("错误")
                msg_box.set_text("无法加载字体文件")
                msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                msg_box.exec_()
    
    def clear_font(self):
        """
        清除当前字体
        """
        self.font_widget.clear_font()
        self.setWindowTitle("字体预览器")
    
    def update_font_info(self, font_info):
        """
        更新字体信息显示
        """
        self.font_info_labels["文件名称"].setText(font_info["file_name"])
        self.font_info_labels["字体家族"].setText(font_info["family"])
        self.font_info_labels["字体大小"].setText(str(font_info["size"]))
        self.font_info_labels["字体样式"].setText(font_info["style"])
        self.font_info_labels["文件路径"].setText(font_info["path"])
    
    def load_font_from_path(self, font_path):
        """
        从外部路径加载字�?
        
        Args:
            font_path (str): 字体文件路径
        """
        if self.font_widget.set_font(font_path):
            # 更新窗口标题
            file_name = os.path.basename(font_path)
            self.setWindowTitle(f"字体预览�?- {file_name}")
            return True
        return False
    
    def set_file(self, file_path):
        """
        设置要显示的字体文件
        
        Args:
            file_path (str): 字体文件路径
        """
        self.load_font_from_path(file_path)


# 命令行参数支�?
if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = FontPreviewer()
    
    # 如果提供了字体路径参数，直接加载
    if len(sys.argv) > 1:
        font_path = sys.argv[1]
        viewer.load_font_from_path(font_path)
    
    viewer.show()
    sys.exit(app.exec_())

