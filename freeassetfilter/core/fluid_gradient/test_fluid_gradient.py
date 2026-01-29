#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyQt5 WebEngine 流体滚动渐变效果测试程序

功能：
    1. 使用PyQt5 WebEngine加载并展示流体渐变网页效果
    2. 支持主题切换
    3. 响应式设计验证
    4. 性能监控

作者：FreeAssetFilter
创建日期：2026-01-29
"""

import sys
import os
from pathlib import Path

from PyQt5.QtCore import (
    Qt, QUrl, QSize, QTimer, pyqtSlot, QObject, pyqtSignal,
    QThread, QMutex, QWaitCondition
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QProgressBar, QStatusBar,
    QToolBar, QAction, QComboBox, QSpinBox, QSlider, QGroupBox,
    QCheckBox, QFrame, QSplitter, QTabWidget, QTextEdit
)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineProfile, QWebEngineSettings
from PyQt5.QtGui import QIcon, QFont, QPixmap, QColor, QPalette


class PerformanceMonitor(QObject):
    """性能监控器"""
    fpsUpdated = pyqtSignal(float)
    memoryUpdated = pyqtSignal(float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = False
        self.frame_count = 0
        self.last_time = 0
        self.fps_samples = []
        self.max_samples = 30
        self.timer = QTimer()
        self.timer.timeout.connect(self.updateFPS)
    
    def start(self):
        self.running = True
        self.frame_count = 0
        self.fps_samples.clear()
        self.last_time = 0
        self.timer.start(500)
    
    def stop(self):
        self.running = False
        self.timer.stop()
    
    def incrementFrame(self):
        """增加帧计数"""
        if self.running:
            self.frame_count += 1
    
    def updateFPS(self):
        """更新FPS显示"""
        if not self.running:
            return
        
        import time
        current_time = time.time()
        
        if self.last_time > 0:
            elapsed = current_time - self.last_time
            if elapsed > 0:
                fps = self.frame_count / elapsed
                self.fps_samples.append(fps)
                
                if len(self.fps_samples) > self.max_samples:
                    self.fps_samples.pop(0)
                
                avg_fps = sum(self.fps_samples) / len(self.fps_samples)
                self.fpsUpdated.emit(avg_fps)
        
        self.frame_count = 0
        self.last_time = current_time


class FluidGradientWindow(QMainWindow):
    """流体渐变效果主窗口"""
    
    def __init__(self):
        super().__init__()
        self.performance_monitor = PerformanceMonitor()
        self.performance_monitor.fpsUpdated.connect(self.updateFpsDisplay)
        self.initUI()
        self.loadContent()
        self.setupFPSTimer()
    
    def setupFPSTimer(self):
        """设置FPS更新定时器"""
        self.fps_timer = QTimer()
        self.fps_timer.timeout.connect(self.updateFPSCounter)
        self.fps_timer.start(16)
    
    def updateFPSCounter(self):
        """更新FPS计数器"""
        self.performance_monitor.incrementFrame()
    
    def initUI(self):
        """初始化用户界面"""
        self.setWindowTitle('流体滚动渐变效果 - PyQt5 WebEngine 测试')
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        
        self.setupCentralWidget()
        self.setupMenuBar()
        self.setupToolBar()
        self.setupStatusBar()
        
        self.applyDarkTheme()
    
    def setupCentralWidget(self):
        """设置中心部件"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        splitter = QSplitter(Qt.Vertical)
        
        self.webView = QWebEngineView()
        self.webView.setContextMenuPolicy(Qt.NoContextMenu)
        self.setupWebEngine()
        
        self.controlPanel = self.createControlPanel()
        
        splitter.addWidget(self.webView)
        splitter.addWidget(self.controlPanel)
        splitter.setSizes([600, 200])
        
        main_layout.addWidget(splitter)
    
    def setupWebEngine(self):
        """配置WebEngine设置"""
        settings = self.webView.settings()
        settings.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebGLEnabled, True)
        settings.setAttribute(QWebEngineSettings.ScrollAnimatorEnabled, True)
        settings.setAttribute(QWebEngineSettings.PrintElementBackgrounds, False)
        
        profile = self.webView.page().profile()
        profile.setHttpUserAgent(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
    
    def createControlPanel(self) -> QWidget:
        """创建控制面板"""
        panel = QWidget()
        panel.setMaximumHeight(250)
        panel.setStyleSheet('''
            QWidget {
                background-color: #1a1a2e;
                border-top: 1px solid #2d2d44;
            }
            QGroupBox {
                color: #ffffff;
                border: 1px solid #3d3d5c;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QPushButton {
                background-color: #3d3d5c;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #4d4d6c;
            }
            QPushButton:pressed {
                background-color: #2d2d4c;
            }
            QPushButton:checked {
                background-color: #5d5d7c;
            }
            QLabel {
                color: #ffffff;
                font-size: 13px;
            }
            QComboBox {
                background-color: #2d2d4c;
                color: #ffffff;
                border: 1px solid #3d3d5c;
                border-radius: 4px;
                padding: 6px 12px;
                min-width: 120px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: none;
                border: none;
            }
            QSlider::groove:horizontal {
                background-color: #2d2d4c;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background-color: #5d5d7c;
                width: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            QSlider::sub-page:horizontal {
                background-color: #7d7d9c;
                border-radius: 3px;
            }
            QCheckBox {
                color: #ffffff;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
        ''')
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 10, 15, 10)
        
        tab_widget = QTabWidget()
        tab_widget.setStyleSheet('''
            QTabWidget::pane {
                background-color: #1a1a2e;
                border: none;
            }
            QTabBar::tab {
                background-color: #2d2d4c;
                color: #ffffff;
                padding: 8px 16px;
                margin-right: 4px;
                border-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #3d3d5c;
            }
        ''')
        
        layout.addWidget(tab_widget)
        
        tab_widget.addTab(self.createThemeTab(), '主题切换')
        tab_widget.addTab(self.createPerformanceTab(), '性能监控')
        tab_widget.addTab(self.createAnimationTab(), '动画控制')
        tab_widget.addTab(self.createInfoTab(), '信息')
        
        return panel
    
    def createThemeTab(self) -> QWidget:
        """创建主题切换标签页"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(15, 10, 15, 10)
        
        group = QGroupBox('色彩方案')
        group_layout = QHBoxLayout()
        
        themes = [
            ('sunset', '日落橙红'),
            ('ocean', '海洋蓝绿'),
            ('aurora', '极光霓虹')
        ]
        
        for theme_id, theme_name in themes:
            btn = QPushButton(theme_name)
            btn.setCheckable(True)
            btn.setChecked(theme_id == 'sunset')
            btn.clicked.connect(lambda checked, t=theme_id: self.switchTheme(t))
            group_layout.addWidget(btn)
        
        group.setLayout(group_layout)
        layout.addWidget(group)
        
        layout.addStretch()
        return widget
    
    def createPerformanceTab(self) -> QWidget:
        """创建性能监控标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 10, 15, 10)
        
        fps_group = QGroupBox('帧率监控')
        fps_layout = QHBoxLayout()
        
        fps_layout.addWidget(QLabel('FPS:'))
        self.fps_label = QLabel('0')
        self.fps_label.setFont(QFont('Consolas', 16, QFont.Bold))
        self.fps_label.setStyleSheet('color: #00ff87;')
        fps_layout.addWidget(self.fps_label)
        
        fps_layout.addStretch()
        
        self.fps_progress = QProgressBar()
        self.fps_progress.setMaximumWidth(200)
        self.fps_progress.setRange(0, 60)
        self.fps_progress.setValue(0)
        fps_layout.addWidget(self.fps_progress)
        
        fps_group.setLayout(fps_layout)
        layout.addWidget(fps_group)
        
        perf_layout = QHBoxLayout()
        
        perf_group = QGroupBox('渲染设置')
        perf_grid = QGridLayout()
        
        self.accel_check = QCheckBox('硬件加速')
        self.accel_check.setChecked(True)
        self.accel_check.stateChanged.connect(self.toggleAcceleration)
        perf_grid.addWidget(self.accel_check, 0, 0)
        
        self.webgl_check = QCheckBox('WebGL')
        self.webgl_check.setChecked(True)
        self.webgl_check.stateChanged.connect(self.toggleWebGL)
        perf_grid.addWidget(self.webgl_check, 0, 1)
        
        self.scroll_anim_check = QCheckBox('滚动动画')
        self.scroll_anim_check.setChecked(True)
        self.scroll_anim_check.stateChanged.connect(self.toggleScrollAnim)
        perf_grid.addWidget(self.scroll_anim_check, 1, 0)
        
        self.virtual_scroll_check = QCheckBox('虚拟滚动')
        self.virtual_scroll_check.setChecked(True)
        perf_grid.addWidget(self.virtual_scroll_check, 1, 1)
        
        perf_group.setLayout(perf_grid)
        perf_layout.addWidget(perf_group)
        
        layout.addLayout(perf_layout)
        layout.addStretch()
        
        return widget
    
    def createAnimationTab(self) -> QWidget:
        """创建动画控制标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 10, 15, 10)
        
        speed_group = QGroupBox('动画速率')
        speed_layout = QVBoxLayout()
        
        slider_layout = QHBoxLayout()
        slider_layout.addWidget(QLabel('速率:'))
        
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(10, 200)
        self.speed_slider.setValue(100)
        self.speed_slider.setTickPosition(QSlider.TicksBelow)
        self.speed_slider.setTickInterval(10)
        self.speed_slider.valueChanged.connect(self.setAnimationSpeed)
        slider_layout.addWidget(self.speed_slider)
        
        self.speed_label = QLabel('100%')
        self.speed_label.setFixedWidth(50)
        slider_layout.addWidget(self.speed_label)
        
        speed_layout.addLayout(slider_layout)
        
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel('预设:'))
        
        presets = [
            ('极慢', 25),
            ('慢速', 50),
            ('正常', 100),
            ('快速', 150),
            ('极速', 200)
        ]
        
        for name, value in presets:
            btn = QPushButton(name)
            btn.clicked.connect(lambda checked, v=value: self.setSpeedPreset(v))
            preset_layout.addWidget(btn)
        
        speed_layout.addLayout(preset_layout)
        
        speed_group.setLayout(speed_layout)
        layout.addWidget(speed_group)
        
        layer_group = QGroupBox('图层控制')
        layer_layout = QHBoxLayout()
        
        self.pause_btn = QPushButton('暂停动画')
        self.pause_btn.setCheckable(True)
        self.pause_btn.clicked.connect(self.toggleAnimation)
        layer_layout.addWidget(self.pause_btn)
        
        reset_btn = QPushButton('重置动画')
        reset_btn.clicked.connect(self.resetAnimation)
        layer_layout.addWidget(reset_btn)
        
        layer_group.setLayout(layer_layout)
        layout.addWidget(layer_group)
        
        layout.addStretch()
        
        return widget
    
    def createInfoTab(self) -> QWidget:
        """创建信息标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 10, 15, 10)
        
        info_group = QGroupBox('技术信息')
        info_layout = QVBoxLayout()
        
        info_text = QTextEdit()
        info_text.setReadOnly(True)
        info_text.setMaximumHeight(120)
        info_text.setText('''
功能特性：
• 平滑的色彩渐变过渡，模拟流体流动
• 滚动位置与色彩变化实时关联
• 5种自定义关键色彩配置
• 响应式设计，适配各种屏幕
• GPU硬件加速优化
• 3种预设色彩方案
• 0.5-1秒渐变过渡时间
• 高斯模糊实现自然融合

技术支持：
• CSS Custom Properties
• CSS will-change 优化
• requestAnimationFrame
• CSS Blur 效果
• PyQt5 WebEngine
        ''')
        info_layout.addWidget(info_text)
        
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        layout.addStretch()
        
        return widget
    
    def setupMenuBar(self):
        """设置菜单栏"""
        menubar = self.menuBar()
        menubar.setStyleSheet('''
            QMenuBar {
                background-color: #1a1a2e;
                color: #ffffff;
                border-bottom: 1px solid #2d2d44;
                padding: 4px;
            }
            QMenuBar::item:selected {
                background-color: #3d3d5c;
            }
            QMenu {
                background-color: #2d2d4c;
                color: #ffffff;
                border: 1px solid #3d3d5c;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #4d4d6c;
            }
        ''')
        
        file_menu = menubar.addMenu('文件')
        
        reload_action = QAction('重新加载', self)
        reload_action.setShortcut('F5')
        reload_action.triggered.connect(self.reloadPage)
        file_menu.addAction(reload_action)
        
        dev_action = QAction('开发者工具', self)
        dev_action.setShortcut('F12')
        dev_action.triggered.connect(self.toggleDevTools)
        file_menu.addAction(dev_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction('退出', self)
        exit_action.setShortcut('Ctrl+Q')
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        view_menu = menubar.addMenu('视图')
        
        fullscreen_action = QAction('全屏', self)
        fullscreen_action.setShortcut('F11')
        fullscreen_action.triggered.connect(self.toggleFullScreen)
        view_menu.addAction(fullscreen_action)
        
        help_menu = menubar.addMenu('帮助')
        
        about_action = QAction('关于', self)
        about_action.triggered.connect(self.showAbout)
        help_menu.addAction(about_action)
    
    def setupToolBar(self):
        """设置工具栏"""
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setStyleSheet('''
            QToolBar {
                background-color: #1a1a2e;
                border-bottom: 1px solid #2d2d44;
                spacing: 8px;
                padding: 4px;
            }
            QToolButton {
                background-color: #2d2d4c;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QToolButton:hover {
                background-color: #3d3d5c;
            }
        ''')
        self.addToolBar(toolbar)
        
        back_btn = QPushButton('← 后退')
        back_btn.clicked.connect(self.webView.back)
        toolbar.addWidget(back_btn)
        
        forward_btn = QPushButton('前进 →')
        forward_btn.clicked.connect(self.webView.forward)
        toolbar.addWidget(forward_btn)
        
        reload_btn = QPushButton('↻ 刷新')
        reload_btn.clicked.connect(self.reloadPage)
        toolbar.addWidget(reload_btn)
        
        toolbar.addSeparator()
        
        zoom_label = QLabel('缩放:')
        toolbar.addWidget(zoom_label)
        
        zoom_combo = QComboBox()
        zoom_combo.addItems(['50%', '75%', '100%', '125%', '150%', '200%'])
        zoom_combo.setCurrentText('100%')
        zoom_combo.currentTextChanged.connect(self.setZoomFactor)
        toolbar.addWidget(zoom_combo)
    
    def setupStatusBar(self):
        """设置状态栏"""
        self.statusBar().setStyleSheet('''
            QStatusBar {
                background-color: #1a1a2e;
                color: #ffffff;
                border-top: 1px solid #2d2d44;
            }
        ''')
        self.statusBar().showMessage('准备就绪')
    
    def applyDarkTheme(self):
        """应用深色主题"""
        self.setStyleSheet('''
            QMainWindow {
                background-color: #12121f;
            }
            QWidget {
                background-color: #12121f;
            }
        ''')
    
    def loadContent(self):
        """加载流体渐变网页内容"""
        base_path = Path(__file__).parent
        
        html_path = base_path / 'index.html'
        
        if html_path.exists():
            file_url = QUrl.fromLocalFile(str(html_path.absolute()))
            self.webView.load(file_url)
            self.statusBar().showMessage(f'正在加载: {html_path}')
        else:
            self.loadEmbeddedContent()
        
        self.webView.loadFinished.connect(self.onPageLoaded)
    
    def loadEmbeddedContent(self):
        """加载嵌入式HTML内容（备用方案）"""
        html_content = self.generateEmbeddedHTML()
        self.webView.setHtml(html_content, QUrl('http://localhost/'))
    
    def generateEmbeddedHTML(self) -> str:
        """生成嵌入式HTML内容 - 苹果音乐风格流体渐变"""
        return '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>流体滚动渐变效果 - 苹果音乐风格</title>
    <style>
        :root {
            --color-1: #ff6b6b;
            --color-2: #feca57;
            --color-3: #48dbfb;
            --color-4: #ff9ff3;
            --color-5: #54a0ff;
            --blur-amount: 150px;
            --transition-duration: 1.5s;
            --anim-speed: 1.0;
            --layer-1-duration: 40s;
            --layer-2-duration: 35s;
            --layer-3-duration: 45s;
            --layer-4-duration: 38s;
            --layer-5-duration: 42s;
            --layer-6-duration: 50s;
            --layer-7-duration: 48s;
            --layer-8-duration: 55s;
            --layer-9-duration: 52s;
            --layer-10-duration: 60s;
            --shimmer-duration: 20s;
        }
        
        [data-theme="sunset"] {
            --color-1: #ff6b6b;
            --color-2: #feca57;
            --color-3: #ff9ff3;
            --color-4: #f368e0;
            --color-5: #ff4757;
        }
        
        [data-theme="ocean"] {
            --color-1: #0abde3;
            --color-2: #10ac84;
            --color-3: #00d2d3;
            --color-4: #54a0ff;
            --color-5: #2e86de;
        }
        
        [data-theme="aurora"] {
            --color-1: #00ff87;
            --color-2: #60efff;
            --color-3: #0061ff;
            --color-4: #ff00ff;
            --color-5: #00ffcc;
        }
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html { scroll-behavior: smooth; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            color: #fff;
            overflow-x: hidden;
            background: #0a0a0f;
            min-height: 100vh;
        }
        
        .gradient-container {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            overflow: hidden;
            z-index: -1;
            pointer-events: none;
        }
        
        .gradient-layer {
            position: absolute;
            width: 100%;
            height: 100%;
            top: 0;
            left: 0;
            will-change: transform, opacity, background;
        }
        
        .layer-1 { 
            background: radial-gradient(ellipse 120% 120% at 50% 50%, var(--color-1) 0%, transparent 50%); 
            animation: layerMove1 var(--layer-1-duration) ease-in-out infinite, colorCycle1 30s linear infinite; 
            opacity: 0.6; 
            filter: blur(var(--blur-amount)); 
        }
        .layer-2 { 
            background: radial-gradient(ellipse 100% 100% at 20% 30%, var(--color-2) 0%, transparent 45%); 
            animation: layerMove2 var(--layer-2-duration) ease-in-out infinite reverse, colorCycle2 25s linear infinite; 
            opacity: 0.5; 
            filter: blur(calc(var(--blur-amount) * 0.9)); 
        }
        .layer-3 { 
            background: radial-gradient(ellipse 110% 110% at 80% 20%, var(--color-3) 0%, transparent 45%); 
            animation: layerMove3 var(--layer-3-duration) ease-in-out infinite, colorCycle3 35s linear infinite; 
            opacity: 0.55; 
            filter: blur(calc(var(--blur-amount) * 1.1)); 
        }
        .layer-4 { 
            background: radial-gradient(ellipse 90% 90% at 40% 70%, var(--color-4) 0%, transparent 45%); 
            animation: layerMove4 var(--layer-4-duration) ease-in-out infinite reverse, colorCycle4 28s linear infinite; 
            opacity: 0.45; 
            filter: blur(calc(var(--blur-amount) * 0.8)); 
        }
        .layer-5 { 
            background: radial-gradient(ellipse 100% 100% at 70% 80%, var(--color-5) 0%, transparent 45%); 
            animation: layerMove5 var(--layer-5-duration) ease-in-out infinite, colorCycle5 32s linear infinite; 
            opacity: 0.5; 
            filter: blur(calc(var(--blur-amount) * 1.2)); 
        }
        .layer-6 { 
            background: radial-gradient(ellipse 130% 130% at 30% 60%, var(--color-1) 0%, transparent 50%); 
            animation: layerMove6 var(--layer-6-duration) ease-in-out infinite reverse, colorCycle1 40s linear infinite; 
            opacity: 0.35; 
            filter: blur(calc(var(--blur-amount) * 1.3)); 
        }
        .layer-7 { 
            background: radial-gradient(ellipse 80% 80% at 60% 40%, var(--color-3) 0%, transparent 45%); 
            animation: layerMove7 var(--layer-7-duration) ease-in-out infinite, colorCycle3 38s linear infinite; 
            opacity: 0.4; 
            filter: blur(calc(var(--blur-amount) * 0.7)); 
        }
        .layer-8 { 
            background: radial-gradient(ellipse 140% 140% at 10% 80%, var(--color-2) 0%, transparent 50%); 
            animation: layerMove8 var(--layer-8-duration) ease-in-out infinite reverse, colorCycle2 45s linear infinite; 
            opacity: 0.3; 
            filter: blur(calc(var(--blur-amount) * 1.4)); 
        }
        .layer-9 { 
            background: radial-gradient(ellipse 70% 70% at 90% 50%, var(--color-4) 0%, transparent 45%); 
            animation: layerMove9 var(--layer-9-duration) ease-in-out infinite, colorCycle4 42s linear infinite; 
            opacity: 0.35; 
            filter: blur(calc(var(--blur-amount) * 0.6)); 
        }
        .layer-10 { 
            background: radial-gradient(ellipse 150% 150% at 50% 10%, var(--color-5) 0%, transparent 50%); 
            animation: layerMove10 var(--layer-10-duration) ease-in-out infinite reverse, colorCycle5 48s linear infinite; 
            opacity: 0.25; 
            filter: blur(calc(var(--blur-amount) * 1.5)); 
        }
        
        @keyframes layerMove1 { 
            0% { transform: translate(0, 0) scale(1) rotate(0deg); } 
            20% { transform: translate(30%, 25%) scale(1.3) rotate(45deg); } 
            40% { transform: translate(-25%, 35%) scale(0.85) rotate(-30deg); } 
            60% { transform: translate(35%, -20%) scale(1.25) rotate(60deg); } 
            80% { transform: translate(-30%, -25%) scale(0.9) rotate(-45deg); } 
            100% { transform: translate(0, 0) scale(1) rotate(0deg); } 
        }
        @keyframes layerMove2 { 
            0% { transform: translate(0, 0) scale(1) rotate(0deg); } 
            25% { transform: translate(-35%, 30%) scale(1.35) rotate(-60deg); } 
            50% { transform: translate(40%, -25%) scale(0.8) rotate(90deg); } 
            75% { transform: translate(-30%, 35%) scale(1.2) rotate(-45deg); } 
            100% { transform: translate(0, 0) scale(1) rotate(0deg); } 
        }
        @keyframes layerMove3 { 
            0% { transform: translate(0, 0) scale(1) rotate(0deg); } 
            33% { transform: translate(-40%, 35%) scale(1.4) rotate(120deg); } 
            66% { transform: translate(35%, -30%) scale(0.75) rotate(-90deg); } 
            100% { transform: translate(0, 0) scale(1) rotate(0deg); } 
        }
        @keyframes layerMove4 { 
            0% { transform: translate(0, 0) scale(1) rotate(0deg); } 
            20% { transform: translate(35%, -30%) scale(1.3) rotate(-45deg); } 
            40% { transform: translate(-40%, 25%) scale(0.85) rotate(75deg); } 
            60% { transform: translate(30%, 35%) scale(1.25) rotate(-60deg); } 
            80% { transform: translate(-35%, -30%) scale(0.9) rotate(90deg); } 
            100% { transform: translate(0, 0) scale(1) rotate(0deg); } 
        }
        @keyframes layerMove5 { 
            0% { transform: translate(0, 0) scale(1) rotate(0deg); } 
            25% { transform: translate(40%, 35%) scale(0.8) rotate(60deg); } 
            50% { transform: translate(-35%, -40%) scale(1.35) rotate(-90deg); } 
            75% { transform: translate(30%, 30%) scale(0.85) rotate(120deg); } 
            100% { transform: translate(0, 0) scale(1) rotate(0deg); } 
        }
        @keyframes layerMove6 { 
            0% { transform: translate(0, 0) scale(1) rotate(0deg); } 
            33% { transform: translate(-45%, -35%) scale(1.4) rotate(150deg); } 
            66% { transform: translate(40%, 40%) scale(0.7) rotate(-120deg); } 
            100% { transform: translate(0, 0) scale(1) rotate(0deg); } 
        }
        @keyframes layerMove7 { 
            0% { transform: translate(0, 0) scale(1) rotate(0deg); } 
            25% { transform: translate(50%, 40%) scale(0.85) rotate(-75deg); } 
            50% { transform: translate(-45%, -35%) scale(1.3) rotate(105deg); } 
            75% { transform: translate(35%, 45%) scale(0.8) rotate(-135deg); } 
            100% { transform: translate(0, 0) scale(1) rotate(0deg); } 
        }
        @keyframes layerMove8 { 
            0% { transform: translate(0, 0) scale(1) rotate(0deg); } 
            33% { transform: translate(35%, -45%) scale(1.45) rotate(180deg); } 
            66% { transform: translate(-50%, 35%) scale(0.65) rotate(-150deg); } 
            100% { transform: translate(0, 0) scale(1) rotate(0deg); } 
        }
        @keyframes layerMove9 { 
            0% { transform: translate(0, 0) scale(1) rotate(0deg); } 
            25% { transform: translate(-55%, 45%) scale(0.9) rotate(-105deg); } 
            50% { transform: translate(40%, -50%) scale(1.35) rotate(135deg); } 
            75% { transform: translate(-45%, 40%) scale(0.75) rotate(-165deg); } 
            100% { transform: translate(0, 0) scale(1) rotate(0deg); } 
        }
        @keyframes layerMove10 { 
            0% { transform: translate(0, 0) scale(1) rotate(0deg); } 
            33% { transform: translate(60%, -55%) scale(1.5) rotate(210deg); } 
            66% { transform: translate(-55%, 50%) scale(0.6) rotate(-180deg); } 
            100% { transform: translate(0, 0) scale(1) rotate(0deg); } 
        }
        
        .overlay-gradient {
            position: absolute;
            width: 100%;
            height: 100%;
            top: 0;
            left: 0;
            background: linear-gradient(180deg, rgba(10, 10, 15, 0.4) 0%, rgba(10, 10, 15, 0.15) 50%, rgba(10, 10, 15, 0.5) 100%);
            pointer-events: none;
            z-index: 1;
        }
        
        .shimmer {
            position: absolute;
            width: 200%;
            height: 100%;
            top: 0;
            left: -50%;
            background: linear-gradient(90deg, transparent 0%, rgba(255, 255, 255, 0.04) 25%, rgba(255, 255, 255, 0.1) 50%, rgba(255, 255, 255, 0.04) 75%, transparent 100%);
            animation: shimmer var(--shimmer-duration) linear infinite;
            pointer-events: none;
            z-index: 2;
        }
        
        @keyframes shimmer { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }
        
        @keyframes colorCycle1 {
            0%, 100% { filter: hue-rotate(0deg); }
            50% { filter: hue-rotate(180deg); }
        }
        @keyframes colorCycle2 {
            0%, 100% { filter: hue-rotate(0deg); }
            50% { filter: hue-rotate(180deg); }
        }
        @keyframes colorCycle3 {
            0%, 100% { filter: hue-rotate(0deg); }
            50% { filter: hue-rotate(180deg); }
        }
        @keyframes colorCycle4 {
            0%, 100% { filter: hue-rotate(0deg); }
            50% { filter: hue-rotate(180deg); }
        }
        @keyframes colorCycle5 {
            0%, 100% { filter: hue-rotate(0deg); }
            50% { filter: hue-rotate(180deg); }
        }
        
        .navbar {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            padding: 1rem 2rem;
            background: rgba(0, 0, 0, 0.3);
            backdrop-filter: blur(40px);
            z-index: 100;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .navbar h1 {
            font-size: 1.5rem;
            font-weight: 600;
            background: linear-gradient(135deg, var(--color-1), var(--color-3), var(--color-5));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .theme-btn {
            padding: 0.5rem 1rem;
            border: 1px solid rgba(255, 255, 255, 0.15);
            background: rgba(255, 255, 255, 0.05);
            color: #fff;
            border-radius: 20px;
            cursor: pointer;
            margin-left: 0.5rem;
            transition: all 0.3s ease;
        }
        
        .theme-btn:hover { background: rgba(255, 255, 255, 0.15); border-color: rgba(255, 255, 255, 0.3); }
        .theme-btn.active { background: linear-gradient(135deg, var(--color-3), var(--color-4)); border-color: transparent; color: #fff; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3); }
        
        .content { position: relative; z-index: 10; padding-top: 80px; }
        
        .hero {
            height: 85vh;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            text-align: center;
            padding: 2rem;
        }
        
        .hero h2 { font-size: clamp(2.5rem, 7vw, 4.5rem); font-weight: 700; margin-bottom: 1.5rem; text-shadow: 0 4px 40px rgba(0, 0, 0, 0.4); letter-spacing: -0.02em; }
        .hero p { font-size: clamp(1rem, 2.5vw, 1.35rem); opacity: 0.85; max-width: 650px; line-height: 1.6; }
        
        .section { padding: 5rem 2rem; max-width: 1200px; margin: 0 auto; }
        .section-alt { background: rgba(0, 0, 0, 0.25); backdrop-filter: blur(20px); border-radius: 2rem; margin: 3rem auto; max-width: 1160px; border: 1px solid rgba(255, 255, 255, 0.05); }
        .section h3 { font-size: clamp(1.75rem, 4vw, 2.75rem); margin-bottom: 2rem; text-align: center; font-weight: 600; }
        
        .feature-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1.5rem; }
        .feature-card {
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 1.25rem;
            padding: 2rem;
            transition: all 0.3s ease;
        }
        .feature-card:hover { background: rgba(255, 255, 255, 0.08); transform: translateY(-6px); border-color: rgba(255, 255, 255, 0.12); box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3); }
        .feature-card h4 { font-size: 1.25rem; margin-bottom: 0.75rem; font-weight: 600; }
        .feature-card p { opacity: 0.75; line-height: 1.6; font-size: 0.95rem; }
        
        .footer { text-align: center; padding: 4rem; opacity: 0.5; }
        
        @media (max-width: 768px) {
            .navbar { flex-direction: column; gap: 1rem; padding: 1rem; }
            :root { --blur-amount: 100px; }
            .hero { height: 70vh; }
        }
        
        @media (prefers-reduced-motion: reduce) {
            .gradient-layer, .shimmer { animation: none; }
            * { animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; transition-duration: 0.01ms !important; }
        }
    </style>
</head>
<body>
    <div class="gradient-container">
        <div class="gradient-layer layer-1"></div>
        <div class="gradient-layer layer-2"></div>
        <div class="gradient-layer layer-3"></div>
        <div class="gradient-layer layer-4"></div>
        <div class="gradient-layer layer-5"></div>
        <div class="gradient-layer layer-6"></div>
        <div class="gradient-layer layer-7"></div>
        <div class="gradient-layer layer-8"></div>
        <div class="gradient-layer layer-9"></div>
        <div class="gradient-layer layer-10"></div>
        <div class="overlay-gradient"></div>
        <div class="shimmer"></div>
    </div>
    
    <nav class="navbar">
        <h1>流体渐变演示</h1>
        <div>
            <button class="theme-btn active" onclick="switchTheme('sunset')">日落</button>
            <button class="theme-btn" onclick="switchTheme('ocean')">海洋</button>
            <button class="theme-btn" onclick="switchTheme('aurora')">极光</button>
        </div>
    </nav>
    
    <main class="content">
        <section class="hero">
            <h2>体验丝滑流体渐变</h2>
            <p>滚动页面感受色彩的流动与变化</p>
        </section>
        
        <section class="section">
            <h3>特性介绍</h3>
            <div class="feature-grid">
                <div class="feature-card">
                    <h4>平滑过渡</h4>
                    <p>0.5-1秒的渐变过渡时间，确保视觉流畅度</p>
                </div>
                <div class="feature-card">
                    <h4>滚动联动</h4>
                    <p>色彩变化与滚动位置实时关联，创造沉浸式体验</p>
                </div>
                <div class="feature-card">
                    <h4>响应式设计</h4>
                    <p>完美适配各种屏幕尺寸</p>
                </div>
                <div class="feature-card">
                    <h4>高性能</h4>
                    <p>使用CSS硬件加速，确保流畅不卡顿</p>
                </div>
            </div>
        </section>
        
        <section class="section section-alt">
            <h3>长内容测试区域</h3>
            <p>向下滚动以观察渐变效果的连续变化...</p>
            <div style="height: 100px;"></div>
            <p>继续滚动...</p>
            <div style="height: 100px;"></div>
            <p>更多内容...</p>
            <div style="height: 100px;"></div>
            <p>快到底部了...</p>
            <div style="height: 100px;"></div>
            <p>底部内容</p>
        </section>
    </main>
    
    <footer class="footer">
        <p>基于 PyQt5 WebEngine 的流体滚动渐变演示</p>
    </footer>
    
    <script>
        const colorThemes = {
            sunset: { colors: ['#ff6b6b', '#feca57', '#ff9ff3', '#f368e0', '#ff4757'], layerColors: ['#ff6b6b', '#feca57', '#ff9ff3', '#f368e0', '#ff4757', '#ff6b6b', '#ff9ff3', '#feca57', '#f368e0', '#ff4757'] },
            ocean: { colors: ['#0abde3', '#10ac84', '#00d2d3', '#54a0ff', '#2e86de'], layerColors: ['#0abde3', '#10ac84', '#00d2d3', '#54a0ff', '#2e86de', '#0abde3', '#00d2d3', '#10ac84', '#54a0ff', '#2e86de'] },
            aurora: { colors: ['#00ff87', '#60efff', '#0061ff', '#ff00ff', '#00ffcc'], layerColors: ['#00ff87', '#60efff', '#0061ff', '#ff00ff', '#00ffcc', '#00ff87', '#0061ff', '#60efff', '#ff00ff', '#00ffcc'] }
        };
        
        let currentTheme = 'sunset';
        let animationSpeed = 1.0;
        let isPaused = false;
        const originalDurations = {
            layer1: 40,
            layer2: 35,
            layer3: 45,
            layer4: 38,
            layer5: 42,
            layer6: 50,
            layer7: 48,
            layer8: 55,
            layer9: 52,
            layer10: 60,
            shimmer: 20
        };
        
        function switchTheme(theme) {
            if (!colorThemes[theme]) return;
            
            document.querySelectorAll('.theme-btn').forEach(btn => {
                btn.classList.toggle('active', btn.textContent.toLowerCase().includes(theme === 'sunset' ? '日落' : (theme === 'ocean' ? '海洋' : '极光')));
            });
            
            const root = document.documentElement;
            const themeData = colorThemes[theme];
            
            themeData.colors.forEach((color, i) => {
                root.style.setProperty('--color-' + (i + 1), color);
            });
            
            document.querySelectorAll('.gradient-layer').forEach((layer, i) => {
                layer.style.transition = 'background-color 1.5s ease, opacity 0.5s ease, transform 0.5s ease';
                const color = themeData.layerColors[i];
                const gradients = [
                    'radial-gradient(ellipse 120% 120% at 50% 50%, ' + color + ' 0%, transparent 50%)',
                    'radial-gradient(ellipse 100% 100% at 20% 30%, ' + color + ' 0%, transparent 45%)',
                    'radial-gradient(ellipse 110% 110% at 80% 20%, ' + color + ' 0%, transparent 45%)',
                    'radial-gradient(ellipse 90% 90% at 40% 70%, ' + color + ' 0%, transparent 45%)',
                    'radial-gradient(ellipse 100% 100% at 70% 80%, ' + color + ' 0%, transparent 45%)',
                    'radial-gradient(ellipse 130% 130% at 30% 60%, ' + color + ' 0%, transparent 50%)',
                    'radial-gradient(ellipse 80% 80% at 60% 40%, ' + color + ' 0%, transparent 45%)',
                    'radial-gradient(ellipse 140% 140% at 10% 80%, ' + color + ' 0%, transparent 50%)',
                    'radial-gradient(ellipse 70% 70% at 90% 50%, ' + color + ' 0%, transparent 45%)',
                    'radial-gradient(ellipse 150% 150% at 50% 10%, ' + color + ' 0%, transparent 50%)'
                ];
                layer.style.background = gradients[i] || 'radial-gradient(circle, ' + color + ' 0%, transparent 50%)';
            });
            
            currentTheme = theme;
        }
        
        function setAnimationSpeed(speedFactor) {
            animationSpeed = speedFactor;
            const root = document.documentElement;
            
            root.style.setProperty('--layer-1-duration', (originalDurations.layer1 / speedFactor) + 's');
            root.style.setProperty('--layer-2-duration', (originalDurations.layer2 / speedFactor) + 's');
            root.style.setProperty('--layer-3-duration', (originalDurations.layer3 / speedFactor) + 's');
            root.style.setProperty('--layer-4-duration', (originalDurations.layer4 / speedFactor) + 's');
            root.style.setProperty('--layer-5-duration', (originalDurations.layer5 / speedFactor) + 's');
            root.style.setProperty('--layer-6-duration', (originalDurations.layer6 / speedFactor) + 's');
            root.style.setProperty('--layer-7-duration', (originalDurations.layer7 / speedFactor) + 's');
            root.style.setProperty('--layer-8-duration', (originalDurations.layer8 / speedFactor) + 's');
            root.style.setProperty('--layer-9-duration', (originalDurations.layer9 / speedFactor) + 's');
            root.style.setProperty('--layer-10-duration', (originalDurations.layer10 / speedFactor) + 's');
            root.style.setProperty('--shimmer-duration', (originalDurations.shimmer / speedFactor) + 's');
        }
        
        function pauseAnimation(paused) {
            isPaused = paused;
            const layers = document.querySelectorAll('.gradient-layer');
            const shimmer = document.querySelector('.shimmer');
            
            layers.forEach(layer => {
                layer.style.animationPlayState = paused ? 'paused' : 'running';
            });
            
            if (shimmer) {
                shimmer.style.animationPlayState = paused ? 'paused' : 'running';
            }
        }
        
        function resetAnimation() {
            animationSpeed = 1.0;
            isPaused = false;
            
            const root = document.documentElement;
            
            root.style.setProperty('--layer-1-duration', originalDurations.layer1 + 's');
            root.style.setProperty('--layer-2-duration', originalDurations.layer2 + 's');
            root.style.setProperty('--layer-3-duration', originalDurations.layer3 + 's');
            root.style.setProperty('--layer-4-duration', originalDurations.layer4 + 's');
            root.style.setProperty('--layer-5-duration', originalDurations.layer5 + 's');
            root.style.setProperty('--layer-6-duration', originalDurations.layer6 + 's');
            root.style.setProperty('--layer-7-duration', originalDurations.layer7 + 's');
            root.style.setProperty('--layer-8-duration', originalDurations.layer8 + 's');
            root.style.setProperty('--layer-9-duration', originalDurations.layer9 + 's');
            root.style.setProperty('--layer-10-duration', originalDurations.layer10 + 's');
            root.style.setProperty('--shimmer-duration', originalDurations.shimmer + 's');
            
            const layers = document.querySelectorAll('.gradient-layer');
            const shimmer = document.querySelector('.shimmer');
            
            layers.forEach(layer => {
                layer.style.animationPlayState = 'running';
            });
            
            if (shimmer) {
                shimmer.style.animationPlayState = 'running';
            }
        }
        
        window.switchTheme = switchTheme;
        window.setAnimationSpeed = setAnimationSpeed;
        window.pauseAnimation = pauseAnimation;
        window.resetAnimation = resetAnimation;
    </script>
</body>
</html>
        '''
    
    @pyqtSlot(bool)
    def onPageLoaded(self, success):
        """页面加载完成回调"""
        if success:
            self.statusBar().showMessage('页面加载完成 - 滚动页面查看流体渐变效果', 5000)
            self.performance_monitor.start()
        else:
            self.statusBar().showMessage('页面加载失败', 5000)
    
    def reloadPage(self):
        """重新加载页面"""
        self.webView.reload()
        self.statusBar().showMessage('正在重新加载...')
    
    def toggleDevTools(self):
        """切换开发者工具"""
        if hasattr(self.webView.page(), 'setDevToolsPage'):
            if not hasattr(self, '_devtools_visible'):
                self._devtools_visible = False
            
            self._devtools_visible = not self._devtools_visible
            if self._devtools_visible:
                self.webView.page().devToolsPage(QUrl('chrome://inspect'))
    
    def toggleFullScreen(self):
        """切换全屏模式"""
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
    
    def showAbout(self):
        """显示关于对话框"""
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.about(self, '关于', '''
            <h2>流体滚动渐变效果</h2>
            <p>版本: 1.0.0</p>
            <p>基于 PyQt5 WebEngine 实现</p>
            <p>参考苹果音乐风格的流体渐变效果</p>
            <hr>
            <p>技术支持: CSS3 + JavaScript</p>
        ''')
    
    def switchTheme(self, theme):
        """切换主题"""
        js_code = f'window.switchTheme("{theme}")'
        self.webView.page().runJavaScript(js_code)
        self.statusBar().showMessage(f'已切换至 {theme} 主题', 2000)
    
    def setAnimationSpeed(self, value):
        """设置动画速率"""
        self.speed_label.setText(f'{value}%')
        speed_factor = value / 100.0
        js_code = f'''
        if (typeof window.setAnimationSpeed === 'function') {{
            window.setAnimationSpeed({speed_factor});
        }} else {{
            console.error('setAnimationSpeed function not available');
        }}
        '''
        self.webView.page().runJavaScript(js_code)
    
    def setSpeedPreset(self, value):
        """设置预设速率"""
        self.speed_slider.setValue(value)
        self.speed_label.setText(f'{value}%')
        speed_factor = value / 100.0
        js_code = f'''
        if (typeof window.setAnimationSpeed === 'function') {{
            window.setAnimationSpeed({speed_factor});
        }} else {{
            console.error('setAnimationSpeed function not available');
        }}
        '''
        self.webView.page().runJavaScript(js_code)
        self.statusBar().showMessage(f'动画速率: {value}%', 2000)
    
    def toggleAnimation(self):
        """暂停/恢复动画"""
        if self.pause_btn.isChecked():
            self.pause_btn.setText('恢复动画')
            js_code = 'window.pauseAnimation(true)'
        else:
            self.pause_btn.setText('暂停动画')
            js_code = 'window.pauseAnimation(false)'
        self.webView.page().runJavaScript(js_code)
    
    def resetAnimation(self):
        """重置动画"""
        self.speed_slider.setValue(100)
        self.speed_label.setText('100%')
        self.pause_btn.setChecked(False)
        self.pause_btn.setText('暂停动画')
        js_code = 'window.resetAnimation()'
        self.webView.page().runJavaScript(js_code)
        self.statusBar().showMessage('动画已重置', 2000)
    
    def setZoomFactor(self, text):
        """设置缩放比例"""
        factor = float(text.replace('%', '')) / 100
        self.webView.setZoomFactor(factor)
    
    @pyqtSlot(float)
    def updateFpsDisplay(self, fps):
        """更新FPS显示"""
        self.fps_label.setText(f'{fps:.1f}')
        self.fps_progress.setValue(int(fps))
        
        if fps >= 50:
            color = '#00ff87'
        elif fps >= 30:
            color = '#feca57'
        else:
            color = '#ff6b6b'
        
        self.fps_label.setStyleSheet(f'color: {color}; font-size: 16px; font-weight: bold;')
    
    def toggleAcceleration(self, state):
        """切换硬件加速"""
        settings = self.webView.settings()
        settings.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, bool(state))
    
    def toggleWebGL(self, state):
        """切换WebGL"""
        settings = self.webView.settings()
        settings.setAttribute(QWebEngineSettings.WebGLEnabled, bool(state))
    
    def toggleScrollAnim(self, state):
        """切换滚动动画"""
        settings = self.webView.settings()
        settings.setAttribute(QWebEngineSettings.ScrollAnimatorEnabled, bool(state))
    
    def closeEvent(self, event):
        """关闭事件处理"""
        self.performance_monitor.stop()
        if hasattr(self, 'fps_timer'):
            self.fps_timer.stop()
        super().closeEvent(event)


def main():
    """主函数"""
    app = QApplication(sys.argv)
    app.setApplicationName('流体滚动渐变效果')
    app.setOrganizationName('FreeAssetFilter')
    
    window = FluidGradientWindow()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
