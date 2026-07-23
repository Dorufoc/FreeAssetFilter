#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 主窗口
基于 PySideSix-Frameless-Window 和项目自定义 Mica 效果的无边框主窗口
"""

import sys
from pathlib import Path
from typing import Optional
import os

from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame, QSplitter
import ctypes
from ctypes import wintypes

from PySide6.QtCore import Qt, QEvent, QUrl, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtGui import QPainter, QPaintEvent, QResizeEvent, QMoveEvent, QMouseEvent, QColor, QCursor

# 确保 ui 目录在 sys.path 中（组件 __init__.py 使用短路径导入）
_ui_root = Path(__file__).resolve().parent
if str(_ui_root) not in sys.path:
    sys.path.insert(0, str(_ui_root))

# 添加项目根目录到 sys.path，使 freeassetfilter 包可导入
_project_root = _ui_root.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    from qframelesswindow import FramelessMainWindow
except ImportError:
    # 如果没有安装 PySideSix-Frameless-Window，使用普通 QMainWindow
    from PySide6.QtWidgets import QMainWindow as FramelessMainWindow

# tm 别名已在 theme/__init__.py 中注册
# from theme import tm 与 from freeassetfilter.ui.theme import tm 指向同一实例
from theme import tm

from components.mica_material import MicaMaterial
from components.mica_window import DEFAULT_MICA_CONFIG
from components.styled_button import StyledButton

# 导入布局模块
from layout.file_selector_layout import FileSelectorLayout
from layout.file_pool_layout import FilePoolLayout
from layout.unified_previewer_layout import UnifiedPreviewerLayout
from layout.settings_layout import SettingsLayout

from freeassetfilter.utils.path_utils import get_app_data_path
from freeassetfilter.utils.app_logger import debug, warning
from freeassetfilter.services.staging_pool_service import StagingPoolService


class MicaBackgroundWidget(QWidget):
    """
    Mica 背景 Widget - 负责绘制模糊壁纸和半透明遮罩
    
    层级结构：
    1. 纯色不透明基底（挡住 win32 控件）
    2. 自绘模糊壁纸（Mica 层）
    3. 半透明遮罩（tint_color + luminosity）
    
    主题由 ThemeManager（tm）统一管理
    """
    
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        blur_radius: int = 200,
        tint_color: str = "#202020E8",
        luminosity: float = 0.65,
        contrast: float = 1.5,
        saturation: float = 4.0,
    ) -> None:
        super().__init__(parent)
        
        # Mica 效果参数 — tint_color 和 luminosity 根据当前主题动态设置
        self._blur_radius = blur_radius
        self._contrast = contrast
        self._saturation = saturation
        if tm.is_dark_theme():
            self._tint_color = "#202020E8"
            self._luminosity = 0.65
        else:
            self._tint_color = "#FFFFFFE8"
            self._luminosity = 0.85
        
        # 创建 Mica 效果
        self._mica = MicaMaterial(
            self,
            self._blur_radius,
            self._tint_color,
            self._luminosity,
            self._contrast,
            self._saturation,
        )
        
        # 设置纯色不透明基底（挡住 win32 控件），颜色来自 tm.surface
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), tm.surface)
        self.setPalette(palette)
    
    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制 Mica 效果（模糊壁纸 + 半透明遮罩）"""
        painter = QPainter(self)
        # 先绘制纯色基底（已通过 palette 设置）
        # 然后绘制 Mica 效果（模糊壁纸 + 半透明遮罩）
        self._mica.paint(painter, event)
        painter.end()

    def sync_theme(self) -> None:
        """根据当前主题刷新 tint_color、luminosity 和基底颜色"""
        if tm.is_dark_theme():
            self._tint_color = "#202020E8"
            self._luminosity = 0.65
        else:
            self._tint_color = "#FFFFFFE8"
            self._luminosity = 0.85

        # 更新 MicaMaterial 的 tint/luminosity
        self._mica._tint_color = self._parse_tint(self._tint_color)
        self._mica._luminosity = max(0.0, min(1.0, self._luminosity))

        # 更新基底颜色
        palette = self.palette()
        palette.setColor(self.backgroundRole(), tm.surface)
        self.setPalette(palette)

        # 刷新背景并重绘
        if self._mica is not None:
            self._mica.invalidate_cache()
            self._mica.refresh()
            self.update()

    @staticmethod
    def _parse_tint(value: str) -> QColor:
        """将 #RRGGBBAA 格式解析为 QColor"""
        s = value.lstrip("#")
        if len(s) == 8:
            r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
            a = int(s[6:8], 16)
            return QColor(r, g, b, a)
        return QColor(32, 32, 32, 160)

    def refresh_background(self) -> None:
        """刷新背景（例如壁纸更改后）"""
        if self._mica is not None:
            self._mica.refresh()
    
    def handle_window_resize(self) -> None:
        """处理窗口大小改变（由 MainWindow 调用）"""
        if self._mica is not None:
            self._mica.invalidate_cache()
            self.update()
    
    def handle_window_move(self) -> None:
        """处理窗口移动（由 MainWindow 调用）"""
        if self._mica is not None:
            self._mica.invalidate_cache()
            self.update()


class MainWindow(FramelessMainWindow):
    """
    主窗口类 - 使用无边框窗口和 Mica 效果

    Features:
        - 无边框窗口设计
        - Mica 模糊背景效果
        - Windows 11 现代化风格
        - 完全不透明的基底，遮挡 win32 原生控件
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        blur_radius: Optional[int] = None,
        tint_color: Optional[str] = None,
        luminosity: Optional[float] = None,
        contrast: Optional[float] = None,
        saturation: Optional[float] = None,
    ) -> None:
        """
        初始化主窗口

        Args:
            parent: 父窗口
            blur_radius: Mica 模糊半径（默认使用项目配置）
            tint_color: Mica 覆盖色（默认使用项目配置）
            luminosity: Mica 亮度值（默认使用项目配置）
            contrast: Mica 对比度（默认使用项目配置）
            saturation: Mica 饱和度（默认使用项目配置）
        """
        # 先初始化属性，防止父类初始化期间触发的事件访问未定义属性
        self._mica_background = None
        self._panels = []
        self._splitter = None
        self._github_btn = None
        self._settings_btn = None
        self._theme_btn = None
        self._minimize_btn = None
        self._maximize_btn = None
        self._title_label = None
        self._close_btn = None

        # 配置 Mica 参数（提前计算）
        cfg = DEFAULT_MICA_CONFIG
        self._blur_radius = blur_radius if blur_radius is not None else cfg["blur_radius"]
        self._tint_color = tint_color if tint_color is not None else cfg["tint_color"]
        self._luminosity = luminosity if luminosity is not None else cfg["luminosity"]
        self._contrast = contrast if contrast is not None else cfg["contrast"]
        self._saturation = saturation if saturation is not None else cfg["saturation"]

        # 调用父类初始化
        super().__init__(parent)

        # 设置窗口属性
        self._setup_window()

        # 创建内容布局
        self._setup_content()

        # 将窗口定位到鼠标所在屏幕的中心
        self._center_on_mouse_screen()

    def _setup_window(self) -> None:
        """设置窗口基本属性"""
        self.setWindowTitle("FreeAssetFilter")
        self.resize(1200, 800)

    def _center_on_mouse_screen(self) -> None:
        """将窗口定位到鼠标指针所在屏幕的中心"""
        # 获取鼠标当前位置
        mouse_pos = QCursor.pos()
        
        # 获取鼠标所在的屏幕
        screen = QApplication.screenAt(mouse_pos)
        if screen is None:
            # 如果找不到屏幕，使用主屏幕
            screen = QApplication.primaryScreen()
        
        # 获取屏幕几何信息
        screen_geometry = screen.geometry()
        
        # 计算窗口应该出现的位置（屏幕中心）
        window_width = self.width()
        window_height = self.height()
        
        center_x = screen_geometry.x() + (screen_geometry.width() - window_width) // 2
        center_y = screen_geometry.y() + (screen_geometry.height() - window_height) // 2
        
        # 移动窗口到屏幕中心
        self.move(center_x, center_y)

    def _setup_content(self) -> None:
        """设置窗口内容"""
        # 创建 Mica 背景 Widget（层级 1-3：纯色基底 + 模糊壁纸 + 半透明遮罩）
        self._mica_background = MicaBackgroundWidget(
            self,
            blur_radius=self._blur_radius,
            tint_color=self._tint_color,
            luminosity=self._luminosity,
            contrast=self._contrast,
            saturation=self._saturation,
        )
        
        # 创建主布局（Mica 背景 Widget 作为根容器）
        main_layout = QVBoxLayout(self._mica_background)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 设置 Mica 背景 Widget 为中央部件
        self.setCentralWidget(self._mica_background)

        # 创建标题栏（层级 5：上方控件）
        self._create_title_bar(main_layout)

        # 三栏可拖拽分割布局 — 四周 10px 边距，栏间 10px 间距
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setHandleWidth(10)  # 10px 间距作为分隔条宽度
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: transparent;
                width: 10px;
            }}
        """)

        self._panel_left = QFrame()
        self._panel_left.setObjectName("PanelLeft")
        # 最小尺寸由内部 layout 的子控件自动决定（确保所有按钮完整显示）
        # 嵌入文件选择器布局
        self._file_selector = FileSelectorLayout(self._panel_left)
        panel_left_layout = QVBoxLayout(self._panel_left)
        panel_left_layout.setContentsMargins(0, 0, 0, 0)
        panel_left_layout.setSpacing(0)
        panel_left_layout.addWidget(self._file_selector)

        self._panel_center = QFrame()
        self._panel_center.setObjectName("PanelCenter")
        # 最小尺寸由内部 FilePoolLayout 的子控件自动决定
        # 嵌入文件池布局
        self._file_pool = FilePoolLayout(self._panel_center)
        panel_center_layout = QVBoxLayout(self._panel_center)
        panel_center_layout.setContentsMargins(0, 0, 0, 0)
        panel_center_layout.setSpacing(0)
        panel_center_layout.addWidget(self._file_pool)

        self._panel_right = QFrame()
        self._panel_right.setObjectName("PanelRight")
        # 最小尺寸由内部 UnifiedPreviewerLayout 的子控件自动决定
        # 嵌入统一预览器布局
        self._previewer = UnifiedPreviewerLayout(self._panel_right)
        panel_right_layout = QVBoxLayout(self._panel_right)
        panel_right_layout.setContentsMargins(0, 0, 0, 0)
        panel_right_layout.setSpacing(0)
        panel_right_layout.addWidget(self._previewer)

        # 信号连接：文件选择器 → 文件池
        self._file_selector.add_to_pool_requested.connect(self._on_add_to_pool_requested)
        self._file_selector.toggle_pool_requested.connect(self._on_toggle_pool_requested)
        self._file_selector.file_selected.connect(self._on_file_selected)
        self._file_selector.preview_cancel_requested.connect(self._on_preview_cancelled)
        # 信号连接：文件池 → 文件选择器（同步"已在池中"边框标记）
        self._file_pool.pool_changed.connect(self._on_pool_contents_changed)

        self._panels = [self._panel_left, self._panel_center, self._panel_right]

        self._refresh_panel_styles()

        for panel in self._panels:
            self._splitter.addWidget(panel)

        # 窗口完成布局后等分三栏为 1:1:1
        QTimer.singleShot(0, self._equalize_splitter)

        # 外层容器提供四周 10px 边距
        splitter_container = QWidget()
        splitter_container.setStyleSheet("background-color: transparent;")
        container_layout = QHBoxLayout(splitter_container)
        container_layout.setContentsMargins(10, 0, 10, 10)
        container_layout.setSpacing(0)
        container_layout.addWidget(self._splitter)
        main_layout.addWidget(splitter_container, stretch=1)

        # 连接主题切换信号
        tm.theme_changed.connect(self._on_theme_changed)
        tm.colors_updated.connect(self._on_colors_updated)

    def _create_title_bar(self, parent_layout: QVBoxLayout) -> None:
        """创建标题栏"""
        # 标题栏容器（完全透明，让 MicaBackgroundWidget 的效果覆盖）
        header = QFrame()
        header.setObjectName("TitleBar")
        header.setFixedHeight(48)
        # 完全透明，让下面的 Mica 效果（基底 + 模糊壁纸 + 遮罩）覆盖整个区域
        header.setStyleSheet("""
            #TitleBar {
                background-color: transparent;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 8, 16, 8)
        header_layout.setSpacing(0)

        # 标题文字
        self._title_label = QLabel("FreeAssetFilter")
        self._title_label.setStyleSheet(f'font-size: 14px; font-weight: 600; color: {tm.text.name()};')
        header_layout.addWidget(self._title_label)
        header_layout.addStretch()

        # GitHub 按钮（SVG图标）
        github_icon_path = Path(__file__).resolve().parent.parent / "icons" / "github.svg"
        self._github_btn = StyledButton(
            "",
            variant="ghost",
            size="sm",
            icon=str(github_icon_path) if github_icon_path.exists() else ""
        )
        self._github_btn.setFixedSize(32, 32)
        self._github_btn.setStyleSheet(self._title_bar_button_style())
        self._github_btn.clicked.connect(self._open_github)
        header_layout.addWidget(self._github_btn)

        # 设置按钮（SVG图标）
        settings_icon_path = Path(__file__).resolve().parent.parent / "icons" / "setting.svg"
        self._settings_btn = StyledButton(
            "",
            variant="ghost",
            size="sm",
            icon=str(settings_icon_path) if settings_icon_path.exists() else ""
        )
        self._settings_btn.setFixedSize(32, 32)
        self._settings_btn.setStyleSheet(self._title_bar_button_style())
        self._settings_btn.clicked.connect(self._open_settings_window)
        header_layout.addWidget(self._settings_btn)

        # 主题切换按钮
        self._theme_btn = StyledButton("🌙", variant="ghost", size="sm")
        self._theme_btn.setFixedSize(32, 32)
        self._theme_btn.setStyleSheet(self._title_bar_button_style(font_size="14px"))
        self._theme_btn.setToolTip("切换主题")
        self._theme_btn.clicked.connect(self._on_theme_toggle)
        header_layout.addWidget(self._theme_btn)

        # 最小化按钮
        self._minimize_btn = StyledButton("", variant="ghost", size="sm")
        self._minimize_btn.setFixedSize(32, 32)
        self._minimize_btn.setText("−")
        self._minimize_btn.setStyleSheet(self._title_bar_button_style(font_size="16px"))
        self._minimize_btn.clicked.connect(self.showMinimized)
        header_layout.addWidget(self._minimize_btn)

        # 最大化/还原按钮
        self._maximize_btn = StyledButton("", variant="ghost", size="sm")
        self._maximize_btn.setFixedSize(32, 32)
        self._maximize_btn.setText("▢")
        self._maximize_btn.setStyleSheet(self._title_bar_button_style(font_size="16px"))
        self._maximize_btn.clicked.connect(self._toggle_maximize)
        header_layout.addWidget(self._maximize_btn)

        # 关闭按钮
        self._close_btn = StyledButton("", variant="ghost", size="sm")
        self._close_btn.setFixedSize(32, 32)
        self._close_btn.setText("✕")
        self._close_btn.setStyleSheet(self._title_bar_close_style())
        self._close_btn.clicked.connect(self.close)
        header_layout.addWidget(self._close_btn)

        # 安装事件过滤器用于拖拽
        header.installEventFilter(self)
        parent_layout.addWidget(header)

    def _title_bar_button_style(self, font_size: str = "14px") -> str:
        """生成标题栏按钮的 styleSheet（使用 tm 当前颜色值）"""
        return f"""
            QPushButton {{ background: transparent; border: none; color: {tm.text.name()}; font-size: {font_size}; }}
            QPushButton:hover {{ background: {tm.alpha_of(tm.text, 15).name()}; color: {tm.text.name()}; }}
        """

    def _title_bar_close_style(self) -> str:
        """生成标题栏关闭按钮的 styleSheet（使用 tm 当前颜色值）"""
        return f"""
            QPushButton {{ background: transparent; border: none; color: {tm.text.name()}; font-size: 16px; }}
            QPushButton:hover {{ background: {tm.danger.name()}; color: {tm.text.name()}; }}
        """

    def _toggle_maximize(self) -> None:
        """通过 Win32 ShowWindow 切换最大化/还原，保留原生窗口动画和特性"""
        hwnd = int(self.winId())
        if self.isMaximized():
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            self._maximize_btn.setText("▢")
        else:
            ctypes.windll.user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            self._maximize_btn.setText("❐")
    
    def _open_github(self) -> None:
        """打开 GitHub 项目页面"""
        QDesktopServices.openUrl(QUrl("https://github.com/Dorufoc/FreeAssetFilter"))

    def _open_settings_window(self) -> None:
        """打开设置窗口（每次新建，关闭即销毁，不缓存窗口实例）"""
        window = SettingsWindow()
        window.setAttribute(Qt.WA_DeleteOnClose, True)
        window.show()
        window.raise_()
        window.activateWindow()

    def _on_theme_toggle(self) -> None:
        """主题切换按钮点击事件"""
        tm.toggle_theme()
        # 按钮图标和 tooltip 在 _on_theme_changed 中更新

    def _on_theme_changed(self, theme_name: str) -> None:
        """主题切换后的处理"""
        # 更新 Mica 背景参数
        if self._mica_background is not None:
            if theme_name == "dark":
                self._mica_background._tint_color = "#202020E8"
                self._mica_background._luminosity = 0.65
            else:
                self._mica_background._tint_color = "#FFFFFFE8"
                self._mica_background._luminosity = 0.85
            # 更新基底色
            palette = self._mica_background.palette()
            palette.setColor(self._mica_background.backgroundRole(), tm.surface)
            self._mica_background.setPalette(palette)
            # 重建 Mica 效果
            self._mica_background._mica = MicaMaterial(
                self._mica_background,
                self._mica_background._blur_radius,
                self._mica_background._tint_color,
                self._mica_background._luminosity,
                self._mica_background._contrast,
                self._mica_background._saturation,
            )
            self._mica_background.update()
        # 更新按钮图标和 tooltip
        self._theme_btn.setText("☀️" if theme_name == "light" else "🌙")
        self._theme_btn.setToolTip("切换为深色" if theme_name == "light" else "切换为浅色")
        # 刷新标题文字颜色
        if self._title_label is not None:
            self._title_label.setStyleSheet(f'font-size: 14px; font-weight: 600; color: {tm.text.name()};')
        # 刷新所有标题栏按钮的 styleSheet（tm 颜色值已变化）
        self._github_btn.setStyleSheet(self._title_bar_button_style())
        self._settings_btn.setStyleSheet(self._title_bar_button_style())
        self._theme_btn.setStyleSheet(self._title_bar_button_style(font_size="14px"))
        self._minimize_btn.setStyleSheet(self._title_bar_button_style(font_size="16px"))
        self._maximize_btn.setStyleSheet(self._title_bar_button_style(font_size="16px"))
        self._close_btn.setStyleSheet(self._title_bar_close_style())
        # 刷新 QSS 样式
        self.style().unpolish(self)
        self.style().polish(self)
        # 刷新三栏面板样式
        self._refresh_panel_styles()

    def _refresh_panel_styles(self) -> None:
        """刷新三个面板的 styleSheet（主题切换时调用）"""
        mid = tm.mid
        txt = tm.text
        # QColor.name() 不包含 alpha, 需要用 rgba() 格式保留透明度
        fill_color = f"rgba({txt.red()},{txt.green()},{txt.blue()},{5 / 100})"
        border_color = f"rgba({mid.red()},{mid.green()},{mid.blue()},{50 / 100})"

        # 左侧栏 PanelLeft — 完全透明，样式下放给 FileSelectorLayout 内部
        self._panel_left.setStyleSheet("background-color: transparent; border: none;")

        # 中间栏 PanelCenter — 完全透明，样式下放给 FilePoolLayout 内部
        self._panel_center.setStyleSheet("background-color: transparent; border: none;")

        # 右侧栏 PanelRight — 完全透明，样式下放给 UnifiedPreviewerLayout 内部
        self._panel_right.setStyleSheet("background-color: transparent; border: none;")

        # 将面板样式下发给各 Layout 内部区域
        self._file_selector.set_section_styles(fill_color, border_color)
        self._file_pool.set_section_styles(fill_color, border_color)
        self._previewer.set_section_styles(fill_color, border_color)
        self._file_pool.set_section_styles(fill_color, border_color)

    def _equalize_splitter(self) -> None:
        """等分三栏为 1:1:1（窗口完成布局后调用）"""
        total = self._splitter.width()
        # 扣除两个分隔条宽度（handleWidth=10×2）
        available = max(0, total - 20)
        third = available // 3
        self._splitter.setSizes([third, third, third])

    def _on_colors_updated(self, colors: dict) -> None:
        """颜色更新后的处理（预留）"""
        pass

    # ──── 信号处理 ─────────────────────────────────────────────────────

    def _on_add_to_pool_requested(self, file_info: dict) -> None:
        """处理文件选择器右键"添加到文件池"请求"""
        self._file_pool.add_file(file_info)

    def _on_toggle_pool_requested(self, file_info: dict) -> None:
        """右键直连：已在池中则移除，否则添加。"""
        file_path = file_info.get("path", "")
        if self._file_pool.has_file(file_path):
            self._file_pool.remove_file(file_path)
        else:
            self._file_pool.add_file(file_info)

    def _on_pool_contents_changed(self) -> None:
        """文件池内容变更时，同步路径集合到文件选择器 delegate（边框标记）。"""
        pool_paths = self._file_pool.get_pool_paths()
        self._file_selector.sync_pool_status(pool_paths)

    def _on_file_selected(self, file_info: dict) -> None:
        """处理文件选择器的文件选中事件，同步预览态到文件池"""
        self._file_pool.set_previewing_file(file_info.get("path", ""))

    def _on_preview_cancelled(self) -> None:
        """处理预览取消事件"""
        self._file_pool.clear_previewing_state()

    # ──── 备份恢复 ─────────────────────────────────────────────────────

    def showEvent(self, event: QEvent) -> None:
        """窗口显示时检查备份恢复"""
        super().showEvent(event)
        if not hasattr(self, '_restore_started'):
            self._restore_started = True
            QTimer.singleShot(100, self._check_and_restore_backup)

    def _check_and_restore_backup(self) -> None:
        """检查备份文件并恢复"""
        backup_data = self._file_pool.load_backup()
        items = backup_data.get("items", [])
        if not items:
            return

        # 检查 auto_restore 设置
        app = QApplication.instance()
        auto_restore = True
        if hasattr(app, 'settings_manager') and app.settings_manager is not None:
            auto_restore = app.settings_manager.get_setting(
                "file_staging.auto_restore_records", True
            )

        if auto_restore:
            self._start_restore_backup(backup_data)
        else:
            self._ask_restore_backup(backup_data)

    def _ask_restore_backup(self, backup_data: dict) -> None:
        """询问用户是否恢复备份"""
        from freeassetfilter.widgets.D_widgets import CustomMessageBox
        items = backup_data.get("items", [])
        msg_box = CustomMessageBox(self)
        msg_box.set_title("恢复上次选中内容")
        msg_box.set_text(f"检测到上次有 {len(items)} 个文件在文件存储池中，是否恢复？")
        msg_box.set_buttons(["是", "否"], Qt.Horizontal, ["primary", "normal"])

        result = [False]
        def on_click(btn_idx: int) -> None:
            result[0] = (btn_idx == 0)
            msg_box.close()
        msg_box.buttonClicked.connect(on_click)
        msg_box.exec()

        if result[0]:
            self._start_restore_backup(backup_data)

    def _start_restore_backup(self, backup_data: dict) -> None:
        """启动分批恢复"""
        items = backup_data.get("items", [])
        if not items:
            return

        # 恢复期间暂停自动备份保存
        self._file_pool._suspend_backup_save = True

        self._restore_items = list(items)
        self._restore_success_count = 0
        self._restore_total_count = len(items)

        QTimer.singleShot(0, self._process_restore_batch)

    def _process_restore_batch(self) -> None:
        """分批处理恢复项"""
        batch_size = 10
        batch = self._restore_items[:batch_size]
        self._restore_items = self._restore_items[batch_size:]

        for file_info in batch:
            if isinstance(file_info, dict) and "path" in file_info:
                file_path = file_info["path"]
                if os.path.exists(file_path):
                    self._file_pool.add_file(file_info)
                    self._restore_success_count += 1

        if self._restore_items:
            QTimer.singleShot(0, self._process_restore_batch)
        else:
            self._finish_restore_backup()

    def _finish_restore_backup(self) -> None:
        """完成恢复流程"""
        self._file_pool._suspend_backup_save = False
        self._file_pool.flush_backup_save_now()

        if self._restore_success_count > 0:
            debug(f"备份恢复完成: {self._restore_success_count}/{self._restore_total_count} 项")

    # ──── 窗口事件 ─────────────────────────────────────────────────────

    def closeEvent(self, event: QEvent) -> None:
        """窗口关闭时刷新备份保存到磁盘，释放服务资源"""
        try:
            self._file_pool.flush_backup_save_now()
        except Exception:
            pass
        StagingPoolService().dispose()
        super().closeEvent(event)

    def eventFilter(self, obj: QWidget, event: QEvent) -> bool:
        """事件过滤器 - 处理标题栏拖拽"""
        if not isinstance(event, QMouseEvent):
            return False

        # 只处理鼠标按下事件
        if event.type() != QEvent.Type.MouseButtonPress:
            return False

        # 只处理左键
        if event.button() != Qt.LeftButton:
            return False

        # 检查是否点击在按钮上
        child = obj.childAt(event.position().toPoint())
        if child is not None and isinstance(child, StyledButton):
            return False  # 让按钮正常工作

        # 在标题栏上拖拽移动窗口
        if obj.objectName() == "TitleBar" and self.windowHandle():
            self.windowHandle().startSystemMove()
            return True

        return False

    # ---- Public API ----

    def refresh_background(self) -> None:
        """刷新背景（例如壁纸更改后）"""
        if self._mica_background is not None:
            self._mica_background.refresh_background()
    
    # ---- 窗口事件处理 ----
    
    def resizeEvent(self, event: QResizeEvent) -> None:
        """窗口大小改变事件"""
        super().resizeEvent(event)
        # 通知 MicaBackgroundWidget 刷新
        if self._mica_background is not None:
            self._mica_background.handle_window_resize()
    
    def moveEvent(self, event: QMoveEvent) -> None:
        """窗口移动事件"""
        super().moveEvent(event)
        # 通知 MicaBackgroundWidget 刷新
        if self._mica_background is not None:
            self._mica_background.handle_window_move()


class SettingsWindow(FramelessMainWindow):
    """
    设置窗口 — 独立窗口，使用 Mica 效果
    
    点击主窗口标题栏的设置按钮后弹出
    """

    def __init__(self, parent=None):
        # 先初始化属性，防止父类初始化期间触发的事件访问未定义属性
        self._mica_background = None
        self._title_label = None
        self._close_btn = None

        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumSize(700, 400)
        self.resize(700, 500)

        # Mica 背景
        self._mica_background = MicaBackgroundWidget(self)
        self.setCentralWidget(self._mica_background)

        # 主布局
        layout = QVBoxLayout(self._mica_background)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏（仅关闭按钮）
        self._create_title_bar(layout)

        # 设置内容区
        self._settings_layout = SettingsLayout(self._mica_background)
        layout.addWidget(self._settings_layout)

        # 监听主题变化以刷新背景和按钮颜色
        tm.theme_changed.connect(self._on_theme_changed)

    def _create_title_bar(self, parent_layout: QVBoxLayout) -> None:
        """创建标题栏（仅标题文字和关闭按钮）"""
        header = QFrame()
        header.setObjectName("SettingsTitleBar")
        header.setFixedHeight(48)
        header.setStyleSheet("""
            #SettingsTitleBar {
                background-color: transparent;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 8, 16, 8)
        header_layout.setSpacing(0)

        # 标题文字
        self._title_label = QLabel("设置")
        self._title_label.setStyleSheet(
            f'font-size: 14px; font-weight: 600; color: {tm.text.name()};'
        )
        header_layout.addWidget(self._title_label)
        header_layout.addStretch()

        # 关闭按钮
        self._close_btn = StyledButton("", variant="ghost", size="sm")
        self._close_btn.setFixedSize(32, 32)
        self._close_btn.setText("✕")
        self._close_btn.setStyleSheet(self._close_button_style())
        self._close_btn.clicked.connect(self.close)
        header_layout.addWidget(self._close_btn)

        # 安装事件过滤器用于拖拽
        header.installEventFilter(self)
        parent_layout.addWidget(header)

    def _close_button_style(self) -> str:
        """生成关闭按钮的 styleSheet"""
        return f"""
            QPushButton {{ background: transparent; border: none; color: {tm.text.name()}; font-size: 16px; }}
            QPushButton:hover {{ background: {tm.danger.name()}; color: {tm.text.name()}; }}
        """

    def _on_theme_changed(self, _theme: str) -> None:
        """主题切换时刷新 Mica 效果和标题栏样式"""
        self._sync_theme()

    def showEvent(self, event) -> None:
        """窗口显示/重新显示时刷新全量主题样式"""
        super().showEvent(event)
        self._sync_theme()

    def _sync_theme(self) -> None:
        """强制刷新当前主题下的所有样式"""
        # Mica 背景（同步 tint/luminosity/基底颜色 + 刷新壁纸）
        if self._mica_background is not None:
            self._mica_background.sync_theme()
        # 标题栏文字
        if self._title_label is not None:
            self._title_label.setStyleSheet(
                f'font-size: 14px; font-weight: 600; color: {tm.text.name()};'
            )
        # 关闭按钮
        if self._close_btn is not None:
            self._close_btn.setStyleSheet(self._close_button_style())
        # 设置内容区（侧边栏 + 卡片）
        if hasattr(self, '_settings_layout') and self._settings_layout is not None:
            self._settings_layout.refresh_theme()

    def eventFilter(self, obj: QWidget, event: QEvent) -> bool:
        """事件过滤器 - 处理标题栏拖拽"""
        if not isinstance(event, QMouseEvent):
            return False

        if event.type() != QEvent.Type.MouseButtonPress:
            return False

        if event.button() != Qt.LeftButton:
            return False

        # 检查是否点击在按钮上
        child = obj.childAt(event.position().toPoint())
        if child is not None and isinstance(child, StyledButton):
            return False  # 让按钮正常工作

        # 在标题栏上拖拽移动窗口
        if obj.objectName() == "SettingsTitleBar" and self.windowHandle():
            self.windowHandle().startSystemMove()
            return True

        return False

    def moveEvent(self, event) -> None:
        """窗口移动时刷新背景"""
        super().moveEvent(event)
        if self._mica_background is not None:
            self._mica_background.handle_window_move()

    def resizeEvent(self, event) -> None:
        """窗口调整大小时刷新背景"""
        super().resizeEvent(event)
        if self._mica_background is not None:
            self._mica_background.handle_window_resize()


def main() -> int:
    """
    应用程序入口函数

    Returns:
        int: 应用程序退出代码
    """
    try:
        print("正在启动应用程序...")
        app = QApplication(sys.argv)
        print("QApplication 创建成功")

        print("正在创建主窗口...")
        window = MainWindow()
        print("主窗口创建成功")

        print("正在显示窗口...")
        window.show()
        print("窗口已显示")

        print("启动事件循环...")
        return app.exec()
    except Exception as e:
        print(f"发生错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())