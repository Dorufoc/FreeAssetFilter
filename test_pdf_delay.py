#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 PDF 延迟计算缩放功能"""

import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt

app = QApplication(sys.argv)

# 设置全局属性（模拟主应用）
app.dpi_scale_factor = 1.0
app.global_font = app.font()
app.default_font_size = 10

print("[TEST] 测试 PDF 延迟计算缩放功能...")

test_pdf_path = "test_delay.pdf"

try:
    from freeassetfilter.components.pdf_previewer import PDFPreviewer
    print("[TEST] PDFPreviewer 导入成功")
    
    # 创建主窗口
    window = QMainWindow()
    window.setWindowTitle("PDF延迟计算测试")
    window.setGeometry(100, 100, 1000, 700)  # 更大的窗口
    
    # 创建中央部件
    central_widget = QWidget()
    window.setCentralWidget(central_widget)
    
    # 创建布局
    layout = QVBoxLayout(central_widget)
    
    # 添加一个按钮用于重新加载PDF
    button_layout = QHBoxLayout()
    reload_button = QPushButton("重新加载PDF")
    button_layout.addWidget(reload_button)
    button_layout.addStretch()
    layout.addLayout(button_layout)
    
    print("[TEST] 创建 PDFPreviewer 实例...")
    # 创建PDF预览器
    pdf_previewer = PDFPreviewer()
    print("[TEST] PDFPreviewer 实例创建成功")
    
    layout.addWidget(pdf_previewer)
    print("[TEST] PDFPreviewer 添加到布局成功")
    
    # 创建一个测试PDF（横向A4页面）
    try:
        import fitz
        doc = fitz.open()
        # 创建横向A4页面 (842 x 595 点)
        page = doc.new_page(width=842, height=595)
        page.insert_text((100, 100), "Test PDF - Landscape A4 Page")
        page.insert_text((100, 150), "This is a test page to verify delayed zoom calculation")
        doc.save(test_pdf_path)
        doc.close()
        print(f"[TEST] 创建横向A4测试PDF: {test_pdf_path}")
        
    except Exception as e:
        print(f"[TEST] 创建测试PDF失败: {e}")
        traceback.print_exc()
    
    def load_pdf():
        """加载PDF文件"""
        print("[TEST] 加载测试PDF...")
        pdf_previewer.load_file_from_path(test_pdf_path)
        print(f"[TEST] 测试PDF加载完成")
    
    # 连接按钮信号
    reload_button.clicked.connect(load_pdf)
    
    # 显示窗口后再加载PDF
    window.show()
    print("[TEST] 窗口显示成功")
    
    # 延迟加载PDF，确保窗口完全显示
    from PySide6.QtCore import QTimer
    QTimer.singleShot(500, load_pdf)
    
    def cleanup():
        """清理测试文件"""
        try:
            if os.path.exists(test_pdf_path):
                os.remove(test_pdf_path)
                print(f"[TEST] 清理测试文件: {test_pdf_path}")
        except Exception as e:
            print(f"[TEST] 清理测试文件失败: {e}")
        app.quit()
    
    QTimer.singleShot(8000, cleanup)
    
    print("[TEST] 进入事件循环...")
    app.exec()
    print("[TEST] 测试完成")
    
except Exception as e:
    print(f"[TEST] 错误: {e}")
    traceback.print_exc()
    # 清理测试文件
    try:
        if os.path.exists(test_pdf_path):
            os.remove(test_pdf_path)
    except (OSError, IOError) as e:
        print(f"[TEST] 清理测试文件失败: {e}")
