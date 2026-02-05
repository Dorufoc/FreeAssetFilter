#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 文本预览器测试脚本
测试文本预览组件的各项功能
"""

import sys
import os
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QLabel, QScrollArea, QGroupBox,
    QTextEdit, QComboBox, QSlider, QFrame
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QSize

from freeassetfilter.components.text_previewer import TextPreviewWidget, TextPreviewer
from freeassetfilter.widgets.dropdown_menu import CustomDropdownMenu


class TextPreviewTestWindow(QMainWindow):
    """测试窗口"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("文本预览器测试")
        self.setGeometry(100, 100, 1200, 800)
        
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())
        self.setFont(self.global_font)
        
        self._init_ui()
    
    def _init_ui(self):
        """初始化UI"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        left_panel = QWidget()
        left_panel.setFixedWidth(int(200 * self.dpi_scale))
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(10)
        
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(5)
        
        self.create_test_file_btn = QPushButton("创建测试文件")
        self.create_test_file_btn.clicked.connect(self._create_test_files)
        btn_layout.addWidget(self.create_test_file_btn)
        
        self.load_file_btn = QPushButton("加载文件")
        self.load_file_btn.clicked.connect(self._load_file)
        btn_layout.addWidget(self.load_file_btn)
        
        self.clear_btn = QPushButton("清除预览")
        self.clear_btn.clicked.connect(self._clear_preview)
        btn_layout.addWidget(self.clear_btn)
        
        left_layout.addLayout(btn_layout)
        
        file_type_label = QLabel("选择文件类型:")
        left_layout.addWidget(file_type_label)
        
        self.file_type_dropdown = CustomDropdownMenu(use_internal_button=True)
        file_types = [
            "纯文本 (.txt)",
            "Python (.py)",
            "JSON (.json)",
            "XML (.xml)",
            "Markdown (.md)",
            "HTML (.html)",
            "JavaScript (.js)",
            "配置文件 (.ini)"
        ]
        self.file_type_dropdown.set_items(file_types, file_types[0])
        self.file_type_dropdown.main_button.setText("文件类型")
        self.file_type_dropdown.itemClicked.connect(self._on_file_type_selected)
        left_layout.addWidget(self.file_type_dropdown)
        
        left_layout.addStretch()
        
        main_layout.addWidget(left_panel)
        
        preview_frame = QFrame()
        preview_frame.setFrameStyle(QFrame.StyledPanel)
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)
        
        self.preview_widget = TextPreviewWidget()
        preview_layout.addWidget(self.preview_widget)
        
        main_layout.addWidget(preview_frame)
        
        self.status_label = QLabel("就绪")
        self.status_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.status_label)
    
    def _create_test_files(self):
        """创建测试文件"""
        test_dir = os.path.join(os.path.dirname(__file__), 'test_files')
        os.makedirs(test_dir, exist_ok=True)
        
        test_files = {
            "纯文本 (.txt)": (
                os.path.join(test_dir, "test.txt"),
                """这是一个纯文本文件测试。
支持多行显示。
用于测试文本预览器的基本功能。

第三行测试。
"""
            ),
            "Python (.py)": (
                os.path.join(test_dir, "test.py"),
                '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Python 文件测试
"""

def example_function(param1, param2):
    """示例函数"""
    result = []
    for i in range(param1):
        if i % 2 == 0:
            result.append(i * param2)
    return result

class ExampleClass:
    """示例类"""
    
    def __init__(self, name):
        self.name = name
        self.items = []
    
    def add_item(self, item):
        """添加项目"""
        self.items.append(item)
        return len(self.items)

if __name__ == "__main__":
    obj = ExampleClass("Test")
    print(obj.add_item(1))
'''
            ),
            "JSON (.json)": (
                os.path.join(test_dir, "test.json"),
                '''{
    "name": "FreeAssetFilter",
    "version": "1.0.0",
    "description": "Free Asset Filter - A powerful file management tool",
    "features": [
        "File preview",
        "Batch processing",
        "Format conversion",
        "Metadata extraction"
    ],
    "settings": {
        "theme": "dark",
        "language": "zh-CN",
        "dpi_scale": 1.0,
        "auto_save": true
    },
    "author": {
        "name": "Dorufoc",
        "email": "qpdrfc123@gmail.com"
    }
}
'''
            ),
            "XML (.xml)": (
                os.path.join(test_dir, "test.xml"),
                '''<?xml version="1.0" encoding="UTF-8"?>
<root>
    <application name="FreeAssetFilter">
        <version>1.0.0</version>
        <description>A powerful file management tool</description>
        <features>
            <feature>File preview</feature>
            <feature>Batch processing</feature>
            <feature>Format conversion</feature>
        </features>
        <settings theme="dark" language="zh-CN">
            <option name="auto_save" value="true"/>
        </settings>
    </application>
</root>
'''
            ),
            "Markdown (.md)": (
                os.path.join(test_dir, "test.md"),
                '''# FreeAssetFilter 文档

## 简介

**FreeAssetFilter** 是一款强大的文件管理工具，支持多种文件格式的预览和处理。

## 主要功能

- 文件预览
- 批量处理
- 格式转换
- 元数据提取

## 代码示例

```python
def hello():
    print("Hello, World!")
```

## 表格示例

| 功能 | 描述 | 状态 |
|------|------|------|
| 预览 | 支持多种格式 | 完成 |
| 处理 | 批量操作 | 进行中 |
| 转换 | 格式转换 | 计划 |

## 引用示例

> 这是一个引用文本。
> 用于测试 Markdown 渲染效果。

- 列表项 1
- 列表项 2
  - 子项 2.1
  - 子项 2.2
- 列表项 3
'''
            ),
            "HTML (.html)": (
                os.path.join(test_dir, "test.html"),
                '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>测试页面</title>
</head>
<body>
    <h1>这是一个 HTML 测试页面</h1>
    <p>用于测试 HTML 语法高亮功能。</p>
    
    <div class="container">
        <p>容器内的段落。</p>
        <a href="https://example.com">链接示例</a>
    </div>
    
    <script>
        function test() {
            console.log("Hello");
            var x = 10;
            return x * 2;
        }
    </script>
</body>
</html>
'''
            ),
            "JavaScript (.js)": (
                os.path.join(test_dir, "test.js"),
                '''// JavaScript 文件测试
class TextPreviewer {
    constructor() {
        this.content = "";
        this.encoding = "utf-8";
    }
    
    loadFile(path) {
        try {
            const fs = require('fs');
            this.content = fs.readFileSync(path, this.encoding);
            return true;
        } catch (error) {
            console.error("Error:", error.message);
            return false;
        }
    }
    
    getLineCount() {
        return this.content.split('\n').length;
    }
    
    search(keyword, caseSensitive = false) {
        const flags = caseSensitive ? 'g' : 'gi';
        const regex = new RegExp(keyword, flags);
        return this.content.match(regex) || [];
    }
}

const previewer = new TextPreviewer();
previewer.loadFile("test.txt");
console.log("Lines:", previewer.getLineCount());
'''
            ),
            "配置文件 (.ini)": (
                os.path.join(test_dir, "test.ini"),
                '''[Settings]
theme = dark
language = zh-CN
dpi_scale = 1.0
auto_save = true

[Preview]
default_font = Arial
font_size = 12
line_numbers = true
word_wrap = false

[Paths]
cache_dir = ./cache
temp_dir = ./temp
log_file = ./logs/app.log

[Features]
file_preview = enabled
batch_processing = enabled
format_conversion = disabled
metadata_extraction = enabled
'''
            )
        }
        
        current_item = self.file_type_dropdown._current_item
        if isinstance(current_item, dict):
            file_type = current_item.get('text', '')
        else:
            file_type = current_item if current_item else file_types[0]
        
        if file_type in test_files:
            file_path, content = test_files[file_type]
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self.status_label.setText(f"创建测试文件: {file_path}")
            print(f"Test file created: {file_path}")
    
    def _on_file_type_selected(self, item):
        """文件类型选择回调"""
        if isinstance(item, dict):
            file_type = item.get('text', '')
        else:
            file_type = item
        print(f"Selected file type: {file_type}")
    
    def _load_file(self):
        """加载文件"""
        test_dir = os.path.join(os.path.dirname(__file__), 'test_files')
        
        current_item = self.file_type_dropdown._current_item
        if isinstance(current_item, dict):
            file_type = current_item.get('text', '')
        else:
            file_type = current_item if current_item else file_types[0]
        
        extension_map = {
            "纯文本 (.txt)": ".txt",
            "Python (.py)": ".py",
            "JSON (.json)": ".json",
            "XML (.xml)": ".xml",
            "Markdown (.md)": ".md",
            "HTML (.html)": ".html",
            "JavaScript (.js)": ".js",
            "配置文件 (.ini)": ".ini"
        }
        
        if file_type in extension_map:
            file_path = os.path.join(test_dir, "test" + extension_map[file_type])
            if os.path.exists(file_path):
                self.preview_widget.set_file(file_path)
                self.status_label.setText(f"加载文件: {file_path}")
                print(f"Loading file: {file_path}")
            else:
                self.status_label.setText(f"文件不存在，请先创建测试文件")
                print("File not found, please create test files first")
        else:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "选择文件", test_dir,
                "所有文件 (*);;文本文件 (*.txt);;Python (*.py);;JSON (*.json)"
            )
            if file_path:
                self.preview_widget.set_file(file_path)
                self.status_label.setText(f"加载文件: {file_path}")
                print(f"Loading file: {file_path}")
    
    def _clear_preview(self):
        """清除预览"""
        self.preview_widget.text_edit.clear()
        self.status_label.setText("预览已清除")
        print("Preview cleared")


def main():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    
    app.setStyleSheet("""
        QMainWindow {
            background-color: #F5F5F5;
        }
        QWidget {
            font-family: Arial, sans-serif;
        }
        QPushButton {
            padding: 8px 16px;
            border-radius: 4px;
            background-color: #007AFF;
            color: white;
            border: none;
        }
        QPushButton:hover {
            background-color: #0056B3;
        }
        QComboBox {
            padding: 6px 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
        }
    """)
    
    window = TextPreviewTestWindow()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
