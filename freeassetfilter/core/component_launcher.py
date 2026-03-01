#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

组件启动器
用于快速启动项目中的各个独立组件
"""

import sys
import os
import shutil
import re
from datetime import datetime, timedelta
import chardet
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QVBoxLayout,
    QWidget, QLabel, QGroupBox, QTextEdit,
    QScrollArea, QHBoxLayout, QMessageBox, QSizePolicy,
    QDialog, QDialogButtonBox, QComboBox, QCheckBox
)

# 导入日志模块
from freeassetfilter.utils.app_logger import info, debug, warning, error

# 导入自定义输入框组件
from freeassetfilter.widgets.input_widgets import CustomInputBox
from freeassetfilter.widgets.smooth_scroller import SmoothScroller
from freeassetfilter.core.settings_manager import SettingsManager
from PySide6.QtCore import Qt, QProcess, QTimer
from PySide6.QtGui import QFont, QColor

class ComponentLauncher(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("组件启动器")
        self.setGeometry(100, 100, 900, 800)
        self.setMinimumSize(800, 600)
        
        # 从设置管理器获取字体设置
        self.settings_manager = SettingsManager()
        font_size = self.settings_manager.get_setting("font.size", 10)
        font_style = self.settings_manager.get_setting("font.style", "Microsoft YaHei")
        font = QFont(font_style, font_size)
        QApplication.setFont(font)
        
        # 组件配置
        self.components = [
            {
                "name": "主应用程序",
                "command": [sys.executable, "freeassetfilter/app/main.py"],
                "description": "主应用程序，包含完整的文件管理和预览功能"
            },
            {
                "name": "自定义控件演示",
                "command": [sys.executable, "freeassetfilter/app/demo_custom_widgets.py"],
                "description": "演示自定义窗口和按钮控件的使用，展示纯白圆角矩形外观和右上角圆形关闭按钮"
            },
            {
                "name": "照片查看器",
                "command": [sys.executable, "freeassetfilter/components/photo_viewer.py"],
                "description": "照片查看器组件，实现缩放/自适应/拖动/右键菜单功能"
            },
            {
                "name": "视频播放器",
                "command": [sys.executable, "freeassetfilter/components/video_player.py"],
                "description": "视频播放器组件，支持播放/暂停/音量控制"
            },
            {
                "name": "PDF预览器",
                "command": [sys.executable, "freeassetfilter/components/pdf_previewer.py"],
                "description": "PDF预览器组件，支持PDF文件实时浏览渲染"
            },
            {
                "name": "文本预览器",
                "command": [sys.executable, "freeassetfilter/components/text_previewer.py"],
                "description": "文本预览器组件，支持Markdown渲染和代码语法高亮"
            },
            {
                "name": "统一文件预览器",
                "command": [sys.executable, "freeassetfilter/components/unified_previewer.py"],
                "description": "统一文件预览器，根据文件类型动态调用对应预览组件"
            },
            {
                "name": "自动时间线",
                "command": [sys.executable, "freeassetfilter/components/auto_timeline.py"],
                "description": "自动时间线组件，用于多媒体资产管理与行为分析的核心可视化工具"
            },
            {
                "name": "中文日志测试",
                "command": [sys.executable, "freeassetfilter/app/test_chinese_log.py"],
                "description": "测试中文日志输出是否正常"
            },
            {
                "name": "数值控制条演示",
                "command": [sys.executable, "freeassetfilter/app/demo_custom_value_bar.py"],
                "description": "演示新创建的数值控制条组件，复用可交互进度条逻辑，滑块图标替换为进度条按钮"
            }
        ]
        
        # 存储运行中的进程
        self.running_processes = {}
        
        # 日志配置
        self.log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        self.current_log_level = "INFO"
        self.log_pattern = re.compile(r'\[(\d{2}:\d{2}:\d{2})\] \[(\w+)\] \[(\w+)\] (.+)')
        
        # 错误类型分析
        self.error_types = {
            "AttributeError": "属性错误，尝试访问不存在的对象属性",
            "ImportError": "导入错误，无法导入模块或对象",
            "ValueError": "值错误，传入的参数类型正确但值不合法",
            "TypeError": "类型错误，传入的参数类型不合法",
            "IndexError": "索引错误，访问列表或元组时索引超出范围",
            "KeyError": "键错误，访问字典时键不存在",
            "FileNotFoundError": "文件不存在错误，尝试访问不存在的文件",
            "PermissionError": "权限错误，没有足够的权限执行操作",
            "ZeroDivisionError": "除零错误，尝试除以零",
            "SyntaxError": "语法错误，代码语法不符合Python规范"
        }
        
        # 日志目录设置
        self.log_dir = "logs"
        self.current_log_file = None
        self.last_save_time = datetime.now()
        self.last_clear_time = datetime.now()
        
        # 创建日志目录
        self._create_log_dir()
        
        # 初始化定时器
        self.save_timer = QTimer(self)
        self.save_timer.timeout.connect(self._save_logs)
        self.save_timer.start(3600000)  # 每小时保存一次日志
        
        self.clear_timer = QTimer(self)
        self.clear_timer.timeout.connect(self._clear_logs)
        self.clear_timer.start(86400000)  # 每天清空一次日志
        
        # 自动清理旧日志
        self._clean_old_logs()
        
        self.init_ui()
    
    def init_ui(self):
        # 创建主布局
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # 添加标题
        title_label = QLabel("组件启动器")
        title_label.setAlignment(Qt.AlignCenter)
        title_font = QFont(self.settings_manager.get_setting("font.style", "Microsoft YaHei"), self.settings_manager.get_setting("font.size", 10))
        title_font.setPointSize(int(self.settings_manager.get_setting("font.size", 10) * 1.4))
        title_font.setWeight(QFont.Bold)
        title_label.setFont(title_font)
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
        
        SmoothScroller.apply_to_scroll_area(components_scroll)
        
        main_layout.addWidget(components_scroll, 2)
        
        # 创建日志区域
        log_group = QGroupBox("组件日志")
        log_group.setStyleSheet("font-weight: bold; padding: 10px;")
        log_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        log_layout = QVBoxLayout()
        
        # 日志过滤和搜索区域
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(10)
        
        # 日志级别过滤
        level_label = QLabel("日志级别:")
        filter_layout.addWidget(level_label)
        
        self.level_combo = QComboBox()
        self.level_combo.addItems(self.log_levels)
        self.level_combo.setCurrentText(self.current_log_level)
        self.level_combo.currentTextChanged.connect(self._filter_logs)
        filter_layout.addWidget(self.level_combo)
        
        # 日志搜索
        search_label = QLabel("搜索:")
        filter_layout.addWidget(search_label)
        
        self.search_edit = CustomInputBox(placeholder_text="输入搜索关键词...")
        self.search_edit.textChanged.connect(self._filter_logs)
        filter_layout.addWidget(self.search_edit)
        
        # 显示所有日志复选框
        self.show_all_check = QCheckBox("显示所有日志")
        self.show_all_check.setChecked(True)
        self.show_all_check.stateChanged.connect(self._filter_logs)
        filter_layout.addWidget(self.show_all_check)
        
        # 复制日志按钮
        copy_button = QPushButton("复制最近日志")
        copy_button.clicked.connect(self._copy_recent_logs)
        filter_layout.addWidget(copy_button)
        
        filter_layout.addStretch()
        log_layout.addLayout(filter_layout)
        
        # 日志显示区域
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("组件输出日志将显示在这里...")
        self.log_text.setMinimumHeight(200)
        self.log_text.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; font-family: Courier;")
        self.log_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
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
        name_font = QFont(self.settings_manager.get_setting("font.style", "Microsoft YaHei"), self.settings_manager.get_setting("font.size", 10))
        name_font.setPointSize(int(self.settings_manager.get_setting("font.size", 10) * 1.1))
        name_font.setWeight(QFont.Bold)
        name_label.setFont(name_font)
        name_label.setStyleSheet("color: #2c3e50; background-color: #f8f9fa; padding: 5px; border-radius: 3px;")
        layout.addWidget(name_label)
        
        # 组件描述
        desc_label = QLabel(component["description"])
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #555555;")
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
            self._log(f"已停止组件", component=component_name, level="INFO")
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
                    self._log(f"已启动组件", component=component_name, level="INFO")
                else:
                    self._log(f"启动失败", component=component_name, level="ERROR")
                    from freeassetfilter.widgets.D_widgets import CustomMessageBox
                    msg_box = CustomMessageBox(self)
                    msg_box.set_title("启动失败")
                    msg_box.set_text(f"无法启动组件: {component_name}")
                    msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                    msg_box.exec()
            except Exception as e:
                # 解析错误信息
                error_info = self._parse_error(str(e))
                if error_info:
                    self._log(
                        f"启动错误: {str(e)} - {error_info['error_desc']}",
                        component=component_name,
                        level="ERROR",
                        file=error_info['file'],
                        line=error_info['line']
                    )
                else:
                    self._log(f"启动错误: {str(e)}", component=component_name, level="ERROR")
                from freeassetfilter.widgets.D_widgets import CustomMessageBox
                msg_box = CustomMessageBox(self)
                msg_box.set_title("启动错误")
                msg_box.set_text(f"启动组件时发生错误: {component_name}\n{str(e)}")
                msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
                msg_box.exec()
    
    def _read_process_output(self, process, component_name):
        """读取进程输出"""
        try:
            data = process.readAllStandardOutput().data()
            # 使用chardet检测编码
            result = chardet.detect(data)
            encoding = result['encoding'] or 'utf-8'
            output = data.decode(encoding, errors='replace')
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
            self._log(f"组件正常退出", component=component_name, level="INFO")
        else:
            self._log(f"组件异常退出 (退出码: {exit_code})", component=component_name, level="ERROR")
    
    def _show_component_logs(self, component):
        """显示指定组件的日志"""
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{component['name']} 日志")
        dialog.setGeometry(200, 200, 800, 500)
        
        layout = QVBoxLayout()
        
        log_text = QTextEdit()
        log_text.setReadOnly(True)
        log_text.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; font-family: Courier;")
        
        # 提取指定组件的日志
        logs = self.log_text.toPlainText()
        component_logs = []
        component_name = component['name']
        
        for line in logs.split('\n'):
            if f"[{component_name}]" in line:
                component_logs.append(line)
        
        log_text.setPlainText('\n'.join(component_logs))
        layout.addWidget(log_text)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Save)
        buttons.accepted.connect(dialog.accept)
        buttons.button(QDialogButtonBox.Save).clicked.connect(lambda: self._save_component_logs(component_name, component_logs))
        layout.addWidget(buttons)
        
        dialog.setLayout(layout)
        dialog.exec()
    
    def _save_component_logs(self, component_name, logs):
        """保存组件日志到文件"""
        try:
            log_filename = f"{component_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            log_path = os.path.join(self.log_dir, log_filename)
            
            with open(log_path, "w", encoding="utf-8") as f:
                f.write('\n'.join(logs) + '\n')
            
            self._log(f"组件日志已保存到 {log_path}", component=component_name, level="INFO")
            from freeassetfilter.widgets.D_widgets import CustomMessageBox
            msg_box = CustomMessageBox(self)
            msg_box.set_title("保存成功")
            msg_box.set_text(f"日志已成功保存到:\n{log_path}")
            msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            msg_box.exec()
        except Exception as e:
            self._log(f"保存日志失败: {str(e)}", component=component_name, level="ERROR")
            from freeassetfilter.widgets.D_widgets import CustomMessageBox
            msg_box = CustomMessageBox(self)
            msg_box.set_title("保存失败")
            msg_box.set_text(f"保存日志时发生错误:\n{str(e)}")
            msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            msg_box.exec()
    
    def _copy_recent_logs(self):
        """复制最近一次启动的日志"""
        try:
            # 获取所有日志文本
            all_logs = self.log_text.toPlainText()
            log_lines = all_logs.split('\n')
            
            # 查找最后一次启动的日志行
            start_index = 0
            for i, line in enumerate(log_lines):
                if "组件启动器已启动" in line:
                    start_index = i
            
            # 提取最近一次启动的日志
            recent_logs = '\n'.join(log_lines[start_index:])
            
            # 复制到剪贴板
            clipboard = QApplication.clipboard()
            clipboard.setText(recent_logs)
            
            # 显示成功消息
            from freeassetfilter.widgets.D_widgets import CustomMessageBox
            msg_box = CustomMessageBox(self)
            msg_box.set_title("复制成功")
            msg_box.set_text("最近一次启动的日志已复制到剪贴板！")
            msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            msg_box.exec()
            self._log("已复制最近一次启动的日志", level="INFO")
        except Exception as e:
            self._log(f"复制日志失败: {str(e)}", level="ERROR")
            from freeassetfilter.widgets.D_widgets import CustomMessageBox
            msg_box = CustomMessageBox(self)
            msg_box.set_title("复制失败")
            msg_box.set_text(f"复制日志时发生错误:\n{str(e)}")
            msg_box.set_buttons(["确定"], Qt.Horizontal, ["primary"])
            msg_box.exec()
    
    def _log(self, message, level="INFO", component="Launcher", file="", line=""):
        """添加日志信息"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 错误定位信息
        location = f"[{file}:{line}] " if file and line else ""
        
        # 格式化日志消息
        log_message = f"[{timestamp}] [{component}] [{level}] {location}{message}"
        
        # 根据日志级别设置颜色
        color = self._get_log_color(level)
        
        # 添加带有颜色的日志
        self.log_text.setTextColor(color)
        self.log_text.append(log_message)
        self.log_text.setTextColor(QColor(0, 0, 0))  # 恢复默认颜色
        
        # 自动滚动到底部
        self.log_text.moveCursor(self.log_text.textCursor().End)
        
        # 保存日志到文件
        self._save_log_to_file(log_message)
    
    def _get_log_color(self, level):
        """根据日志级别获取颜色"""
        colors = {
            "DEBUG": QColor(128, 128, 128),  # 灰色
            "INFO": QColor(0, 0, 0),  # 黑色
            "WARNING": QColor(255, 165, 0),  # 橙色
            "ERROR": QColor(255, 0, 0),  # 红色
            "CRITICAL": QColor(139, 0, 0)  # 深红色
        }
        return colors.get(level, QColor(0, 0, 0))
    
    def _save_log_to_file(self, message):
        """保存日志到文件"""
        try:
            if not self.current_log_file:
                # 创建新的日志文件
                log_filename = f"launcher_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
                self.current_log_file = os.path.join(self.log_dir, log_filename)
            
            with open(self.current_log_file, "a", encoding="utf-8") as f:
                f.write(message + "\n")
        except Exception as e:
            # 日志保存失败，不影响主程序运行
            pass
    
    def _save_logs(self):
        """定期保存日志"""
        self._log("定期保存日志", level="INFO")
        self.current_log_file = None  # 强制创建新的日志文件
        self.last_save_time = datetime.now()
    
    def _clear_logs(self):
        """定期清空日志"""
        self._log("定期清空日志", level="INFO")
        self.log_text.clear()
        self.last_clear_time = datetime.now()
    
    def _filter_logs(self):
        """过滤日志"""
        # 这里简单实现，实际项目中可以优化
        pass
    
    def _parse_error(self, error_message):
        """解析错误信息，提取文件名、行号和错误类型"""
        # 匹配常见的Python错误格式
        error_pattern = re.compile(r'File "([^"]+)", line (\d+),.*?([A-Za-z]+Error):')
        match = error_pattern.search(error_message)
        
        if match:
            file = match.group(1)
            line = match.group(2)
            error_type = match.group(3)
            
            # 获取错误类型描述
            error_desc = self.error_types.get(error_type, "未知错误类型")
            
            return {
                "file": file,
                "line": line,
                "error_type": error_type,
                "error_desc": error_desc
            }
        
        return None
    
    def _create_log_dir(self):
        """创建日志目录"""
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
            
            # 添加.gitignore文件，确保日志文件不被git追踪
            gitignore_path = os.path.join(self.log_dir, ".gitignore")
            with open(gitignore_path, "w") as f:
                f.write("*\n")
    
    def _clean_old_logs(self):
        """清理旧日志文件，保留最近7天的日志"""
        try:
            # 获取所有日志文件
            log_files = [f for f in os.listdir(self.log_dir) if f.endswith(".log")]
            
            # 计算7天前的日期
            seven_days_ago = datetime.now() - timedelta(days=7)
            
            for log_file in log_files:
                log_path = os.path.join(self.log_dir, log_file)
                # 获取文件创建时间
                create_time = datetime.fromtimestamp(os.path.getctime(log_path))
                
                # 如果文件超过7天，删除
                if create_time < seven_days_ago:
                    os.remove(log_path)
        except Exception as e:
            # 清理日志失败，不影响主程序运行
            pass
    
    def _read_process_output(self, process, component_name):
        """读取进程输出"""
        try:
            data = process.readAllStandardOutput().data()
            # 使用chardet检测编码
            result = chardet.detect(data)
            encoding = result['encoding'] or 'utf-8'
            output = data.decode(encoding, errors='replace')
            if output:
                # 分割多行输出，每行单独记录
                for line in output.strip().split('\n'):
                    if line.strip():
                        # 解析错误信息
                        error_info = self._parse_error(line)
                        if error_info:
                            # 错误日志
                            self._log(
                                f"{error_info['error_type']}: {line} - {error_info['error_desc']}",
                                level="ERROR",
                                component=component_name,
                                file=error_info['file'],
                                line=error_info['line']
                            )
                        else:
                            # 普通日志
                            self._log(line.strip(), component=component_name)
        except Exception as e:
            self._log(f"日志读取错误: {str(e)}", level="ERROR")
    
    def closeEvent(self, event):
        """窗口关闭事件，停止所有运行中的进程"""
        if self.running_processes:
            count = len(self.running_processes)
            from freeassetfilter.widgets.D_widgets import CustomMessageBox
            confirm_msg = CustomMessageBox(self)
            confirm_msg.set_title("确认关闭")
            confirm_msg.set_text(f"还有 {count} 个组件正在运行，确定要关闭启动器并停止所有组件吗？")
            confirm_msg.set_buttons(["是", "否"], Qt.Horizontal, ["primary", "normal"])
            
            # 记录确认结果
            is_confirmed = False
            
            def on_confirm_clicked(button_index):
                nonlocal is_confirmed
                is_confirmed = (button_index == 0)  # 0表示确定按钮
                confirm_msg.close()
            
            confirm_msg.buttonClicked.connect(on_confirm_clicked)
            confirm_msg.exec()
            
            if is_confirmed:
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
    sys.exit(app.exec())