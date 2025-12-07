#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeMediaClub
许可协议：https://github.com/Dorufoc/FreeMediaClub/blob/main/LICENSE

组件启动器
用于快速启动项目中的各个独立组件
"""

import sys
import os
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QVBoxLayout, 
    QWidget, QLabel, QGroupBox, QTextEdit, 
    QScrollArea, QHBoxLayout, QMessageBox, QSizePolicy,
    QDialog, QDialogButtonBox
)
from PyQt5.QtCore import Qt, QProcess
from PyQt5.QtGui import QFont

class ComponentLauncher(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("组件启动器")
        self.setGeometry(100, 100, 700, 800)
        self.setMinimumSize(600, 600)
        
        # 设置字体
        font = QFont()
        QApplication.setFont(font)
        
        # 组件配置
        self.components = [
            {
                "name": "主应用程序",
                "command": [sys.executable, "main.py"],
                "description": "主应用程序，包含完整的文件管理和预览功能"
            },
            {
                "name": "照片查看器",
                "command": [sys.executable, "src/components/photo_viewer.py"],
                "description": "照片查看器组件，实现缩放/自适应/拖动/右键菜单功能"
            },
            {
                "name": "视频播放器",
                "command": [sys.executable, "src/components/video_player.py"],
                "description": "视频播放器组件，支持播放/暂停/音量控制"
            },
            {
                "name": "PDF预览器",
                "command": [sys.executable, "src/components/pdf_previewer.py"],
                "description": "PDF预览器组件，支持PDF文件实时浏览渲染"
            },
            {
                "name": "文本预览器",
                "command": [sys.executable, "src/components/text_previewer.py"],
                "description": "文本预览器组件，支持Markdown渲染和代码语法高亮"
            },
            {
                "name": "统一文件预览器",
                "command": [sys.executable, "src/components/unified_previewer.py"],
                "description": "统一文件预览器，根据文件类型动态调用对应预览组件"
            }
        ]
        
        # 存储运行中的进程
        self.running_processes = {}
        
        self.init_ui()
    
    def init_ui(self):
        # 创建主布局
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # 添加标题
        title_label = QLabel("组件启动器")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setFont(QFont("Arial", 14, QFont.Bold))
        title_label.setStyleSheet("color: #000000; background-color: #f0f0f0; padding: 8px;")
        title_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        main_layout.addWidget(title_label)
        
        # 添加说明文本
        desc_label = QLabel("点击下方按钮启动对应的组件，再次点击可停止组件。")
        desc_label.setAlignment(Qt.AlignCenter)
        desc_label.setStyleSheet("color: #333333; padding: 5px;")
        desc_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        main_layout.addWidget(desc_label)
        
        # 创建组件按钮区域
        components_group = QGroupBox("可用组件")
        components_group.setStyleSheet("font-weight: bold; padding: 10px;")
        components_layout = QVBoxLayout()
        components_layout.setSpacing(15)
        components_layout.setAlignment(Qt.AlignTop)
        components_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # 为每个组件创建按钮
        for component in self.components:
            component_widget = self._create_component_widget(component)
            components_layout.addWidget(component_widget)
        
        components_group.setLayout(components_layout)
        
        # 添加滚动区域，确保所有组件都可见
        components_scroll = QScrollArea()
        components_scroll.setWidgetResizable(True)
        components_scroll.setWidget(components_group)
        components_scroll.setMinimumHeight(300)
        components_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        main_layout.addWidget(components_scroll, 2)
        
        # 添加日志区域
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("组件输出日志将显示在这里...")
        self.log_text.setMinimumHeight(150)
        self.log_text.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; font-family: Courier; font-size: 9pt;")
        self.log_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        log_group = QGroupBox("组件日志")
        log_group.setStyleSheet("font-weight: bold; padding: 10px;")
        log_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        log_layout = QVBoxLayout()
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group, 1)
        
        # 设置中心窗口
        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
        
        # 添加初始日志
        self._log("组件启动器已启动，点击按钮启动组件。")
    
    def _create_component_widget(self, component):
        """创建单个组件的控件"""
        widget = QWidget()
        widget.setMinimumHeight(100)
        widget.setMaximumHeight(200)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        widget.setStyleSheet(
            "background-color: #ffffff; "
            "border: 2px solid #4a7abc; "
            "border-radius: 8px; "
            "padding: 15px; "
            "margin: 5px;"
        )
        
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        
        # 组件标题
        name_label = QLabel(component["name"])
        name_label.setFont(QFont("Arial", 11, QFont.Bold))
        name_label.setStyleSheet("color: #2c3e50; background-color: #f8f9fa; padding: 5px; border-radius: 3px;")
        layout.addWidget(name_label)
        
        # 组件描述
        desc_label = QLabel(component["description"])
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #555555; font-size: 9pt;")
        desc_label.setMinimumHeight(30)
        desc_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(desc_label)
        
        # 控制按钮
        control_layout = QHBoxLayout()
        control_layout.setSpacing(10)
        
        start_stop_btn = QPushButton("启动")
        start_stop_btn.setFixedWidth(80)
        start_stop_btn.setStyleSheet(
            "background-color: #4CAF50; "
            "color: white; "
            "border: none; "
            "padding: 8px 12px; "
            "border-radius: 4px; "
            "font-weight: bold;"
        )
        start_stop_btn.clicked.connect(lambda checked, comp=component: self._toggle_component(comp, start_stop_btn))
        control_layout.addWidget(start_stop_btn)
        
        # 输出按钮
        log_btn = QPushButton("查看日志")
        log_btn.setFixedWidth(100)
        log_btn.setStyleSheet(
            "background-color: #2196F3; "
            "color: white; "
            "border: none; "
            "padding: 8px 12px; "
            "border-radius: 4px;"
        )
        log_btn.clicked.connect(lambda checked, comp=component: self._show_component_logs(comp))
        control_layout.addWidget(log_btn)
        
        layout.addLayout(control_layout)
        
        return widget
    
    def _toggle_component(self, component, button):
        """启动或停止组件"""
        component_name = component["name"]
        
        if component_name in self.running_processes:
            # 停止组件
            process = self.running_processes[component_name]
            process.terminate()
            if not process.waitForFinished(2000):
                process.kill()
            del self.running_processes[component_name]
            button.setText("启动")
            button.setStyleSheet(
                "background-color: #4CAF50; "
                "color: white; "
                "border: none; "
                "padding: 8px 12px; "
                "border-radius: 4px; "
                "font-weight: bold;"
            )
            self._log(f"已停止组件: {component_name}")
        else:
            # 启动组件
            process = QProcess()
            process.setProcessChannelMode(QProcess.MergedChannels)
            process.readyReadStandardOutput.connect(lambda proc=process, name=component_name: self._read_process_output(proc, name))
            process.finished.connect(lambda exit_code, exit_status, name=component_name, btn=button: self._process_finished(exit_code, exit_status, name, btn))
            
            # 启动进程
            try:
                cmd = component["command"]
                process.start(cmd[0], cmd[1:])
                if process.waitForStarted(2000):
                    self.running_processes[component_name] = process
                    button.setText("停止")
                    button.setStyleSheet(
                        "background-color: #f44336; "
                        "color: white; "
                        "border: none; "
                        "padding: 8px 12px; "
                        "border-radius: 4px; "
                        "font-weight: bold;"
                    )
                    self._log(f"已启动组件: {component_name}")
                else:
                    self._log(f"启动失败: {component_name}")
                    QMessageBox.warning(self, "启动失败", f"无法启动组件: {component_name}")
            except Exception as e:
                self._log(f"启动错误: {component_name} - {str(e)}")
                QMessageBox.critical(self, "启动错误", f"启动组件时发生错误: {component_name}\n{str(e)}")
    
    def _read_process_output(self, process, component_name):
        """读取进程输出"""
        try:
            output = process.readAllStandardOutput().data().decode('utf-8', errors='replace')
            if output:
                # 分割多行输出，每行单独记录
                for line in output.strip().split('\n'):
                    if line.strip():
                        self._log(f"[{component_name}] {line.strip()}")
        except Exception as e:
            self._log(f"[日志读取错误] {str(e)}")
    
    def _process_finished(self, exit_code, exit_status, component_name, button):
        """进程结束回调"""
        # 确保组件已从运行列表中移除
        if component_name in self.running_processes:
            del self.running_processes[component_name]
        
        # 恢复按钮状态
        button.setText("启动")
        button.setStyleSheet(
            "background-color: #4CAF50; "
            "color: white; "
            "border: none; "
            "padding: 8px 12px; "
            "border-radius: 4px; "
            "font-weight: bold;"
        )
        
        # 记录退出日志
        if exit_code == 0:
            self._log(f"组件正常退出: {component_name}")
        else:
            self._log(f"组件异常退出: {component_name} (退出码: {exit_code})")
    
    def _show_component_logs(self, component):
        """显示指定组件的日志"""
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{component['name']} 日志")
        dialog.setGeometry(200, 200, 600, 400)
        
        layout = QVBoxLayout()
        
        log_text = QTextEdit()
        log_text.setReadOnly(True)
        
        # 提取指定组件的日志
        logs = self.log_text.toPlainText()
        component_logs = []
        component_name = component['name']
        
        for line in logs.split('\n'):
            if f"[{component_name}]" in line or f"组件" in line and component_name in line:
                component_logs.append(line)
        
        log_text.setPlainText('\n'.join(component_logs))
        layout.addWidget(log_text)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        
        dialog.setLayout(layout)
        dialog.exec_()
    
    def _log(self, message):
        """添加日志信息"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        # 自动滚动到底部
        self.log_text.moveCursor(self.log_text.textCursor().End)
    
    def closeEvent(self, event):
        """窗口关闭事件，停止所有运行中的进程"""
        if self.running_processes:
            count = len(self.running_processes)
            reply = QMessageBox.question(
                self, "确认关闭", 
                f"还有 {count} 个组件正在运行，确定要关闭启动器并停止所有组件吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # 停止所有进程
                for name, process in list(self.running_processes.items()):
                    process.terminate()
                    if not process.waitForFinished(1000):
                        process.kill()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    launcher = ComponentLauncher()
    launcher.show()
    sys.exit(app.exec_())