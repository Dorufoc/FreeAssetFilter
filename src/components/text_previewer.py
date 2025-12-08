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
独立的文本预览器组件
提供文本文件预览、Markdown渲染和代码语法高亮功�?
"""

import sys
import os
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QFileDialog, QLabel, QScrollArea, QGroupBox, QGridLayout,
    QTextEdit, QComboBox
)
from PyQt5.QtGui import (
    QFont, QIcon
)
from PyQt5.QtCore import (
    Qt, QUrl
)
from PyQt5.QtWebEngineWidgets import QWebEngineView
import markdown
from pygments import highlight
from pygments.lexers import get_lexer_for_filename, TextLexer
from pygments.formatters import HtmlFormatter


class TextPreviewWidget(QWidget):
    """
    文本预览部件，支持Markdown渲染和代码高�?
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 获取全局字体
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QFont
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        #print(f"[DEBUG] TextPreviewWidget获取到的全局字体: {self.global_font.family()}")
        
        # 设置组件字体
        self.setFont(self.global_font)
        
        # 文件数据
        self.current_file_path = ""
        self.file_content = ""
        
        # 预览模式
        self.preview_mode = "auto"  # auto, text, markdown, code
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化预览部件UI
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 设置背景�?
        self.setStyleSheet("background-color: #f5f5f5;")
        
        # 预览模式选择
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(10)
        
        mode_label = QLabel("预览模式:")
        mode_label.setFont(self.global_font)
        mode_label.setStyleSheet("font-size: 14px; color: #333; font-weight: 500;")
        
        self.mode_selector = QComboBox()
        self.mode_selector.addItems(["自动检测", "纯文本", "Markdown", "代码高亮"])
        self.mode_selector.currentTextChanged.connect(self.change_preview_mode)
        self.mode_selector.setFont(self.global_font)
        self.mode_selector.setStyleSheet('''.QComboBox {
            background-color: white;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 8px 12px;
            font-size: 14px;
            color: #333;
        }
        .QComboBox:hover {
            border-color: #1976d2;
        }
        .QComboBox:focus {
            border-color: #1976d2;
            outline: none;
        }''')
        
        mode_layout.addWidget(mode_label)
        mode_layout.addWidget(self.mode_selector)
        mode_layout.addStretch()
        layout.addLayout(mode_layout)
        
        # 预览区域
        self.web_view = QWebEngineView()
        self.web_view.setMinimumHeight(500)
        self.web_view.setStyleSheet("background-color: white; border: 1px solid #e0e0e0; border-radius: 8px;")
        layout.addWidget(self.web_view)
        print(f"[DEBUG] TextPreviewWidget UI组件设置字体: {self.global_font.family()}")
    
    def set_file(self, file_path):
        """
        设置要预览的文本文件
        
        Args:
            file_path (str): 文本文件路径
        """
        if os.path.exists(file_path):
            self.current_file_path = file_path
            
            # 读取文件内容
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.file_content = f.read()
            except UnicodeDecodeError:
                # 尝试使用其他编码
                with open(file_path, 'r', encoding='gbk') as f:
                    self.file_content = f.read()
            
            # 更新预览
            self.update_preview()
            return True
        return False
    
    def change_preview_mode(self, mode_text):
        """
        切换预览模式
        """
        mode_map = {
            "自动检测": "auto",
            "纯文本": "text",
            "Markdown": "markdown",
            "代码高亮": "code"
        }
        self.preview_mode = mode_map[mode_text]
        self.update_preview()
    
    def update_preview(self):
        """
        更新预览内容
        """
        if not self.file_content:
            return
        
        # 自动检测模�?
        if self.preview_mode == "auto":
            # 根据文件扩展名判�?
            ext = os.path.splitext(self.current_file_path)[1].lower()
            if ext in ['.txt']:
                # txt文件使用纯文本模�?
                html_content = self.render_plain_text(self.file_content)
            elif ext in ['.md', '.markdown', '.mdown', '.mkd']:
                # Markdown文件使用Markdown模式
                html_content = self.render_markdown(self.file_content)
            else:
                # 其他代码源文件使用代码高亮模�?
                html_content = self.render_code(self.file_content, self.current_file_path)
        
        # 纯文本模�?
        elif self.preview_mode == "text":
            html_content = self.render_plain_text(self.file_content)
        
        # Markdown模式
        elif self.preview_mode == "markdown":
            html_content = self.render_markdown(self.file_content)
        
        # 代码高亮模式
        elif self.preview_mode == "code":
            html_content = self.render_code(self.file_content, self.current_file_path)
        
        # 设置HTML内容
        self.web_view.setHtml(html_content)
    
    def render_plain_text(self, content):
        """
        渲染纯文�?
        
        Args:
            content (str): 纯文本内�?
        
        Returns:
            str: HTML格式的文�?
        """
        # 转义HTML特殊字符
        content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        content = content.replace('"', '&quot;').replace("'", '&#39;')
        # 替换换行�?
        content = content.replace('\n', '<br>')
        
        # 使用普通字符串拼接，避免f-string中的大括号冲�?
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {
                    font-family: Arial, sans-serif;
                    font-size: 14px;
                    line-height: 1.6;
                    color: #333;
                    margin: 20px;
                    background-color: #fff;
                    word-wrap: break-word;
                    word-break: break-word;
                }
                pre {
                    white-space: pre-wrap;
                    word-wrap: break-word;
                    margin: 0;
                }
            </style>
        </head>
        <body>
            <pre>""" + content + """
            </pre>
        </body>
        </html>
        """
        
        return html
    
    def render_markdown(self, content):
        """
        渲染Markdown
        
        Args:
            content (str): Markdown内容
        
        Returns:
            str: HTML格式的Markdown
        """
        # 使用markdown库将Markdown转换为HTML
        rendered_markdown = markdown.markdown(content, extensions=[
            'markdown.extensions.extra',
            'markdown.extensions.codehilite',
            'markdown.extensions.toc'
        ])
        
        # 添加CSS样式，使用字符串拼接避免f-string冲突
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {
                    font-family: Arial, sans-serif;
                    font-size: 16px;
                    line-height: 1.8;
                    color: #333;
                    margin: 20px;
                    background-color: #fff;
                    word-wrap: break-word;
                    word-break: break-word;
                    overflow-x: hidden;
                }
                h1, h2, h3, h4, h5, h6 {
                    color: #2c3e50;
                    margin-top: 1.5em;
                    margin-bottom: 0.5em;
                    word-wrap: break-word;
                }
                code {
                    background-color: #f0f0f0;
                    padding: 2px 4px;
                    border-radius: 3px;
                    font-family: Consolas, Monaco, 'Andale Mono', monospace;
                    word-wrap: break-word;
                }
                pre {
                    background-color: #f8f8f8;
                    border: 1px solid #e8e8e8;
                    border-radius: 5px;
                    padding: 15px;
                    white-space: pre-wrap;
                    word-wrap: break-word;
                    overflow-x: auto;
                }
                pre code {
                    background-color: transparent;
                    padding: 0;
                }
                blockquote {
                    border-left: 4px solid #ddd;
                    margin-left: 0;
                    padding-left: 20px;
                    color: #666;
                    word-wrap: break-word;
                }
                table {
                    border-collapse: collapse;
                    width: 100%;
                    margin: 20px 0;
                    word-wrap: break-word;
                }
                th, td {
                    border: 1px solid #ddd;
                    padding: 8px 12px;
                    text-align: left;
                    word-wrap: break-word;
                }
                th {
                    background-color: #f0f0f0;
                }
                img {
                    max-width: 100%;
                    height: auto;
                }
            </style>
        </head>
        <body>
        """ + rendered_markdown + """
        </body>
        </html>
        """
        
        return html
    
    def render_code(self, content, filename):
        """
        渲染代码高亮
        
        Args:
            content (str): 代码内容
            filename (str): 文件名，用于自动检测语言
        
        Returns:
            str: HTML格式的高亮代�?
        """
        try:
            # 尝试根据文件名获取合适的词法分析�?
            lexer = get_lexer_for_filename(filename)
        except:
            # 如果无法获取，使用文本词法分析器
            lexer = TextLexer()
        
        # 创建HTML格式化器，不生成完整HTML文档
        formatter = HtmlFormatter(
            style='default',
            linenos=True,
            full=False,
            cssclass='highlight'
        )
        
        # 生成高亮HTML
        highlighted_code = highlight(content, lexer, formatter)
        
        # 获取CSS样式
        css = formatter.get_style_defs('.highlight')
        
        # 创建完整HTML文档，添加自动换行样�?
        # 使用普通字符串拼接，避免f-string中的大括号冲�?
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
        """ + css + """
                body {
                    font-family: Arial, sans-serif;
                    font-size: 14px;
                    line-height: 1.6;
                    color: #333;
                    margin: 20px;
                    background-color: #fff;
                    word-wrap: break-word;
                    word-break: break-word;
                    overflow-x: hidden;
                }
                .highlight {
                    background-color: #f8f8f8;
                    border: 1px solid #e8e8e8;
                    border-radius: 5px;
                    padding: 15px;
                    overflow-x: auto;
                }
                .highlight pre {
                    margin: 0;
                    white-space: pre-wrap;
                    word-wrap: break-word;
                }
                .highlight table {
                    width: 100%;
                    word-wrap: break-word;
                }
                .highlight td {
                    vertical-align: top;
                    word-wrap: break-word;
                }
                .highlight code {
                    font-family: Consolas, Monaco, 'Andale Mono', monospace;
                    font-size: 13px;
                    word-wrap: break-word;
                }
            </style>
        </head>
        <body>
        """ + highlighted_code + """
        </body>
        </html>
        """
        
        return html


class TextPreviewer(QMainWindow):
    """
    文本预览器主窗口
    """
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("文本预览器")
        self.setGeometry(100, 100, 1000, 800)
        
        # 获取全局字体
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QFont
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        #print(f"[DEBUG] TextPreviewer获取到的全局字体: {self.global_font.family()}")
        
        # 设置窗口字体
        self.setFont(self.global_font)
        
        # 创建UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化用户界�?
        """
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 设置整体背景�?
        self.setStyleSheet("background-color: #f5f5f5;")
        
        # 文本预览区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("background-color: transparent;")
        
        self.text_widget = TextPreviewWidget()
        scroll_area.setWidget(self.text_widget)
        
        main_layout.addWidget(scroll_area, 1)
    
    def open_file(self):
        """
        打开文本文件
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self, "打开文本文件", "", 
            "文本文件 (*.txt *.md *.markdown *.mdown *.mkd *.py *.js *.html *.css *.json *.yaml *.yml *.xml *.java *.c *.cpp *.h *.hpp *.go *.rs);;所有文�?(*)"
        )
        
        if file_path:
            self.load_file_from_path(file_path)
    
    def load_file_from_path(self, file_path):
        """
        从外部路径加载文本文�?
        
        Args:
            file_path (str): 文本文件路径
        """
        if self.text_widget.set_file(file_path):
            # 更新窗口标题
            file_name = os.path.basename(file_path)
            self.setWindowTitle(f"文本预览�?- {file_name}")
            
            return True
        return False
    
    def set_file(self, file_path):
        """
        设置要显示的文本文件
        
        Args:
            file_path (str): 文本文件路径
        """
        self.load_file_from_path(file_path)


# 命令行参数支�?
if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = TextPreviewer()
    
    # 如果提供了文件路径参数，直接加载
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        viewer.load_file_from_path(file_path)
    
    viewer.show()
    sys.exit(app.exec_())

