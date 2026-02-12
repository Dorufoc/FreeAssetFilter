#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter PSD预览弹窗组件
提供PSD文件处理时的进度显示和预览功能
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QSizePolicy, QApplication, QDialog, QLineEdit, 
    QScrollArea, QProgressBar
)
from PySide6.QtCore import Qt, QPoint, Signal, QRect, QSize
from PySide6.QtGui import QFont, QColor, QPainter, QPen, QBrush, QIcon, QPixmap, QImage
from PySide6.QtWidgets import QGraphicsDropShadowEffect


class PSDProgressDialog(QDialog):
    """
    PSD文件处理进度弹窗
    显示处理进度、当前操作和取消按钮
    """
    
    processing_complete = Signal(QImage)  # 处理完成信号
    processing_failed = Signal(str)  # 处理失败信号
    cancelled = Signal()  # 取消信号
    
    def __init__(self, parent=None, file_path=""):
        """
        初始化PSD进度弹窗
        
        Args:
            parent: 父窗口
            file_path: PSD文件路径
        """
        super().__init__(parent)
        
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        
        self.file_path = file_path
        self._cancelled = False
        
        self.dpi_scale = 1.0
        self.global_font = QFont()
        
        self._init_attributes()
        self._init_ui()
        self._apply_theme()
    
    def _init_attributes(self):
        """初始化属性"""
        app = QApplication.instance()
        if app:
            self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
            self.global_font = getattr(app, 'global_font', QFont())
        
        self.setFont(self.global_font)
    
    def _init_ui(self):
        """初始化UI"""
        scaled_radius = int(12 * self.dpi_scale)
        scaled_margin = int(15 * self.dpi_scale)
        scaled_padding = int(10 * self.dpi_scale)
        scaled_button_height = int(35 * self.dpi_scale)
        
        self.resize(int(400 * self.dpi_scale), int(200 * self.dpi_scale))
        self.setMinimumSize(int(350 * self.dpi_scale), int(180 * self.dpi_scale))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(scaled_margin, scaled_margin, scaled_margin, scaled_margin)
        main_layout.setSpacing(scaled_padding)
        
        self.window_body = QWidget()
        self.window_body.setObjectName("WindowBody")
        body_layout = QVBoxLayout(self.window_body)
        body_layout.setContentsMargins(scaled_radius, scaled_radius, scaled_radius, scaled_radius)
        body_layout.setSpacing(scaled_padding)
        
        title_layout = QHBoxLayout()
        title_layout.setSpacing(scaled_padding)
        
        self.icon_label = QLabel()
        icon_pixmap = self._create_processing_icon()
        self.icon_label.setPixmap(icon_pixmap)
        self.icon_label.setFixedSize(int(32 * self.dpi_scale), int(32 * self.dpi_scale))
        title_layout.addWidget(self.icon_label)
        
        self.title_label = QLabel("正在处理PSD文件")
        self.title_label.setObjectName("TitleLabel")
        self.title_label.setFont(QFont(self.global_font.family(), int(10 * self.dpi_scale), QFont.Bold))
        title_layout.addWidget(self.title_label)
        title_layout.addStretch()
        
        body_layout.addLayout(title_layout)
        
        self.file_label = QLabel(os.path.basename(self.file_path) if self.file_path else "")
        self.file_label.setObjectName("FileLabel")
        self.file_label.setAlignment(Qt.AlignCenter)
        self.file_label.setStyleSheet("color: #888;")
        body_layout.addWidget(self.file_label)
        
        self.status_label = QLabel("正在初始化...")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setAlignment(Qt.AlignCenter)
        body_layout.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(int(8 * self.dpi_scale))
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: #E0E0E0;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #4ECDC4;
                border-radius: 4px;
            }
        """)
        body_layout.addWidget(self.progress_bar)
        
        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("PercentLabel")
        self.percent_label.setAlignment(Qt.AlignRight)
        body_layout.addWidget(self.percent_label)
        
        button_layout = QHBoxLayout()
        button_layout.setSpacing(scaled_padding)
        button_layout.addStretch()
        
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setFixedSize(int(80 * self.dpi_scale), scaled_button_height)
        self.cancel_button.setFont(self.global_font)
        self.cancel_button.clicked.connect(self._on_cancel)
        button_layout.addWidget(self.cancel_button)
        
        body_layout.addLayout(button_layout)
        
        main_layout.addWidget(self.window_body)
    
    def _create_processing_icon(self):
        """
        创建处理中图标
        """
        size = int(32 * self.dpi_scale)
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        pen = QPen(QColor("#4ECDC4"))
        pen.setWidth(2)
        painter.setPen(pen)
        
        painter.drawEllipse(size//2 - 10, size//2 - 10, 20, 20)
        
        painter.end()
        return pixmap
    
    def _apply_theme(self):
        """应用主题"""
        app = QApplication.instance()
        
        bg_color = "#FFFFFF"
        border_color = "#E0E0E0"
        text_color = "#333333"
        
        if hasattr(app, 'settings_manager'):
            bg_color = app.settings_manager.get_setting("appearance.colors.base_color", bg_color)
            text_color = app.settings_manager.get_setting("appearance.colors.text_color", text_color)
        
        self.setStyleSheet(f"""
            QDialog {{
                background: transparent;
            }}
            #WindowBody {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 12px;
            }}
            #TitleLabel {{
                color: {text_color};
            }}
        """)
    
    def set_file_path(self, file_path):
        """
        设置文件路径
        
        Args:
            file_path: PSD文件路径
        """
        self.file_path = file_path
        if self.file_label:
            self.file_label.setText(os.path.basename(file_path))
    
    def update_progress(self, progress, status):
        """
        更新进度
        
        Args:
            progress: 进度值(0-100)
            status: 状态描述
        """
        self.progress_bar.setValue(progress)
        self.percent_label.setText(f"{progress}%")
        self.status_label.setText(status)
        
        QApplication.processEvents()
    
    def complete(self, qimage):
        """
        处理完成
        
        Args:
            qimage: 生成的图像
        """
        self.update_progress(100, "处理完成!")
        
        self.cancel_button.setText("关闭")
        self.cancel_button.clicked.disconnect()
        self.cancel_button.clicked.connect(self.accept)
        
        self.processing_complete.emit(qimage)
    
    def fail(self, error_msg):
        """
        处理失败
        
        Args:
            error_msg: 错误信息
        """
        self.status_label.setText(f"处理失败: {error_msg}")
        self.status_label.setStyleSheet("color: #FF5252;")
        
        self.processing_failed.emit(error_msg)
    
    def _on_cancel(self):
        """取消处理"""
        self._cancelled = True
        self.cancelled.emit()
        self.reject()
