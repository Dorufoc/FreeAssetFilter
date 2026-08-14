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

from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame, QSplitter, QGridLayout
from PySide6.QtOpenGLWidgets import QOpenGLWidget
import ctypes
from ctypes import wintypes

from PySide6.QtCore import Qt, QEvent, QUrl, QTimer, QAbstractNativeEventFilter
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
# from theme import tm 与从 freeassetfilter.ui.theme import tm 指向同一实例
from theme import tm

from components.mica_material import MicaMaterial
from components.mica_window import DEFAULT_MICA_CONFIG
from components.styled_button import StyledButton
from components.theme_transition_overlay import ThemeTransitionOverlay

# 导入布局模块
from layout.file_selector_layout import FileSelectorLayout
from layout.file_pool_layout import FilePoolLayout
from layout.unified_previewer_layout import UnifiedPreviewerLayout
# SettingsLayout 仅设置窗口使用，延迟到 _open_settings_window / SettingsWindow
# 实例化时再导入，避免启动路径加载 styled_sidebar / color_picker 等组件。

from freeassetfilter.utils.path_utils import get_app_data_path
from freeassetfilter.utils.app_logger import debug, warning
from freeassetfilter.services.staging_pool_service import StagingPoolService


class _MicaBackgroundMixin:
    """
    MicaBackgroundWidget 的共享逻辑（GPU 与 CPU 两种实现复用）。

    宿主类须为 QWidget 子类（依赖 palette()/update()/backgroundRole() 等）。
    主题由 ThemeManager（tm）统一管理。
    """

    def _init_mica_common(
        self,
        blur_radius: int,
        tint_color: str,
        luminosity: float,
        contrast: float,
        saturation: float,
    ) -> None:
        """按当前主题设置 tint/luminosity，创建 MicaMaterial 并设置基底色。"""
        self._blur_radius = blur_radius
        self._contrast = contrast
        self._saturation = saturation
        if tm.is_dark_theme():
            self._tint_color = "#202020B4"
            self._luminosity = 0.65
        else:
            self._tint_color = "#FFFFFFB4"
            self._luminosity = 0.85

        self._mica = MicaMaterial(
            self,
            self._blur_radius,
            self._tint_color,
            self._luminosity,
            self._contrast,
            self._saturation,
            lazy=True,  # 延迟壁纸加载/模糊到窗口显示后（首帧提速，见 showEvent）
        )

        # 纯色不透明基底颜色（来自 tm.surface）
        palette = self.palette()
        palette.setColor(self.backgroundRole(), tm.surface)
        self.setPalette(palette)

    def sync_theme(self) -> None:
        """根据当前主题刷新 tint_color、luminosity 和基底颜色"""
        if tm.is_dark_theme():
            self._tint_color = "#202020B4"
            self._luminosity = 0.65
        else:
            self._tint_color = "#FFFFFFB4"
            self._luminosity = 0.85

        # 更新基底颜色
        palette = self.palette()
        palette.setColor(self.backgroundRole(), tm.surface)
        self.setPalette(palette)

        # 快速重烘焙 tint/luminosity（复用已模糊的 base，不再重新模糊）
        if self._mica is not None:
            self._mica.set_theme_tint(self._tint_color, self._luminosity)
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


class MicaBackgroundWidgetGL(QOpenGLWidget, _MicaBackgroundMixin):
    """
    GPU 合成版 Mica 背景（QOpenGLWidget）。

    背景在 GPU 上以「带缓存纹理的四边形」绘制，每帧成本与窗口大小近乎无关，
    最大化 / 多屏拖动依旧跟手。三栏面板作为子控件位于其上，透明区域正确
    透出 GL 背景。视觉与 CPU 版严格一致（同一 _bake() 纹理 + 抖动）。
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        blur_radius: int = 200,
        tint_color: str = "#202020B4",
        luminosity: float = 0.65,
        contrast: float = 1.5,
        saturation: float = 4.5,
    ) -> None:
        # 应用级防护（静态属性，重复设置无副作用）：阻止原生子窗（MPV 视频面等）
        # 连带把兄弟控件原生化。否则嵌入视频时本 GL 背景被原生化→合成失效→
        # 客户区未绘制像素在 DWM 玻璃板上直接透出桌面（窗口“全透明”bug）。
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings, True)
        super().__init__(parent)
        self._init_mica_common(blur_radius, tint_color, luminosity, contrast, saturation)
        # 背景恒不透明并铺满整窗，声明不透明绘制
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def paintGL(self) -> None:
        """在 GPU 光栅引擎上绘制 Mica 背景（烘焙纹理的子区域 blit）"""
        painter = QPainter(self)
        self._mica.paint_gpu(painter)
        painter.end()

    def handle_window_resize(self) -> None:
        """处理窗口大小改变（由 MainWindow 调用）——GPU 重绘廉价，直接刷新"""
        self.update()

    def handle_window_move(self) -> None:
        """处理窗口移动（由 MainWindow 调用）——GPU 重绘廉价，直接刷新"""
        self.update()


class MicaBackgroundWidgetCpu(QWidget, _MicaBackgroundMixin):
    """
    CPU 光栅版 Mica 背景（QWidget）——OpenGL 不可用时的回退实现。

    行为与历史实现一致：paintEvent 走 MicaMaterial.paint（含交互态快速缩放
    与沉降定时器）；拖动大窗口可能有残留掉帧，但保证无 GPU 环境可用。
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        blur_radius: int = 200,
        tint_color: str = "#202020B4",
        luminosity: float = 0.65,
        contrast: float = 1.5,
        saturation: float = 4.5,
    ) -> None:
        super().__init__(parent)
        # 纯色不透明基底（挡住 win32 控件）
        self.setAutoFillBackground(True)
        self._init_mica_common(blur_radius, tint_color, luminosity, contrast, saturation)
        # 烘焙后 paint 始终铺满整个 rect 且不透明，声明不透明绘制
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制 Mica 效果（模糊壁纸 + 半透明遮罩）"""
        painter = QPainter(self)
        self._mica.paint(painter, event)
        painter.end()

    def handle_window_resize(self) -> None:
        """处理窗口大小改变（由 MainWindow 调用）"""
        if self._mica is not None:
            self._mica.begin_interaction()

    def handle_window_move(self) -> None:
        """处理窗口移动（由 MainWindow 调用）"""
        if self._mica is not None:
            self._mica.begin_interaction()


def _opengl_available() -> bool:
    """检测能否创建 OpenGL 上下文（决定 Mica 背景用 GPU 还是 CPU 实现）。"""
    try:
        from PySide6.QtGui import QOpenGLContext
        return bool(QOpenGLContext().create())
    except Exception:
        return False


def make_mica_background(
    parent: Optional[QWidget] = None,
    blur_radius: int = 200,
    tint_color: str = "#202020B4",
    luminosity: float = 0.65,
    contrast: float = 1.5,
    saturation: float = 4.5,
) -> QWidget:
    """
    创建 Mica 背景控件：默认 CPU 光栅版，环境变量 ``FAF_USE_GL_MICA=1`` 强制 GPU 版。

    为什么默认 CPU 版（2026-08 实测结论）：
    - 在 Windows 上 QOpenGLWidget 需要把 GL 表面与 raster 内容合成到同一窗口，
      每次 resize 都有 FBO 重建 + 纹理合成等待，实测每步多出 ~8-13ms，
      且 GL 内容滞后时窗口边缘会露出未绘制底板（DWM 玻璃板透出桌面）。
    - CPU 版交互路径（fast scaling blit 模糊纹理）在 1200x800 与 2560x1440
      下均更快，且与内容层同属 raster 引擎、同步绘制、无合成滞后。
    - GPU 版保留：设置 FAF_USE_GL_MICA=1 且 OpenGL 可用时启用（大窗口
      低内存带宽机器可手动选择）。

    两者公共 API 一致（sync_theme / refresh_background / handle_window_resize /
    handle_window_move / _mica），调用方无需区分。
    """
    use_gl = os.environ.get("FAF_USE_GL_MICA", "") == "1"
    cls = MicaBackgroundWidgetGL if (use_gl and _opengl_available()) else MicaBackgroundWidgetCpu
    return cls(
        parent,
        blur_radius=blur_radius,
        tint_color=tint_color,
        luminosity=luminosity,
        contrast=contrast,
        saturation=saturation,
    )


# 向后兼容别名：默认指向工厂（含 OpenGL 回退）；调用 MicaBackgroundWidget(...) 等价于 make_mica_background(...)
MicaBackgroundWidget = make_mica_background


class _EdgeHitTestPassthroughFilter(QAbstractNativeEventFilter):
    """
    原生子窗口覆盖窗口边缘时，让 WM_NCHITTEST 命中测试穿透回主窗口。

    背景：qframelesswindow 的边缘拖拽缩放依赖顶层窗口（主窗口）收到
    ``WM_NCHITTEST`` 并返回 ``HTLEFT/HTRIGHT/...`` 命中码，之后由系统以
    原生 ``WM_SYSCOMMAND/SC_SIZE`` 通道执行缩放。当视频播放布局嵌入 MPV 时，
    视频渲染面（``WA_NativeWindow`` 原生子窗口）铺满预览器区域，会覆盖主窗口
    的右边缘（及视频面所在的下边缘）；鼠标移到这些位置时，``WM_NCHITTEST``
    发送给子窗口而非主窗口，子窗口默认返回 ``HTCLIENT``，于是该段边缘无法
    拖拽缩放。

    本过滤器在应用级原生消息层（QAbstractNativeEventFilter，等价于 win32
    消息钩子，不改动任何控件类）拦截 ``WM_NCHITTEST``：
    1. 消息目标不是主窗口本身（主窗口的命中测试仍由 qframelesswindow 的
       ``nativeEvent`` 原样处理），而是主窗口的原生后代子窗口；
    2. 鼠标屏幕坐标落在主窗口边缘带（与 qframelesswindow 的 BORDER_WIDTH
       一致）内；
    则返回 ``HTTRANSPARENT``——系统会把命中测试继续交给同线程的下层窗口
    （即主窗口），由 qframelesswindow 原有逻辑返回正确的边缘命中码。

    结果：边缘缩放完全复用 qframelesswindow + win32 原生缩放通道，不引入
    任何 Qt 事件层面的手动拖拽逻辑；视频面内部（非边缘带）不受影响。
    """

    # WM_NCHITTEST / HTTRANSPARENT（让系统向同线程下层窗口继续发送命中测试）
    WM_NCHITTEST = 0x0084
    HTTRANSPARENT = -1

    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self._window = window

    def nativeEventFilter(self, eventType: bytes, message: object) -> tuple:
        """拦截 WM_NCHITTEST，边缘命中穿透回主窗口。"""
        if eventType != b"windows_generic_MSG":
            return False, 0
        try:
            msg = wintypes.MSG.from_address(int(message))
        except Exception:
            return False, 0
        if msg.message != self.WM_NCHITTEST or not msg.hWnd:
            return False, 0

        window = self._window
        main_hwnd = int(window.winId())
        hwnd = int(msg.hWnd)
        if hwnd == main_hwnd:
            # 主窗口自身的命中测试交给 qframelesswindow.nativeEvent 处理
            return False, 0

        # 仅处理主窗口的原生后代（视频面等嵌入子窗口），不干扰其他顶层窗口
        if not _is_native_descendant(hwnd, main_hwnd):
            return False, 0

        # lParam 高 16 位为屏幕 Y，低 16 位为屏幕 X（带符号，支持负坐标副屏）
        lp = int(msg.lParam)
        x = ctypes.c_short(lp & 0xFFFF).value
        y = ctypes.c_short((lp >> 16) & 0xFFFF).value

        rect = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(main_hwnd, ctypes.byref(rect))
        border = 5  # 与 qframelesswindow WindowsFramelessWindowBase.BORDER_WIDTH 一致
        in_edge = (
            x - rect.left < border
            or rect.right - x < border
            or y - rect.top < border
            or rect.bottom - y < border
        )
        if in_edge:
            # 穿透：系统会向同线程下层窗口（主窗口）重新发送 WM_NCHITTEST
            return True, self.HTTRANSPARENT
        return False, 0


def _is_native_descendant(hwnd: int, ancestor: int) -> bool:
    """判断 hwnd 是否为 ancestor 的原生后代窗口（沿父链上溯）。"""
    cur = ctypes.windll.user32.GetAncestor(hwnd, 1)  # GA_PARENT
    while cur:
        if cur == ancestor:
            return True
        cur = ctypes.windll.user32.GetAncestor(cur, 1)
    return False


class _FramelessNativeEffectsMixin:
    """在 GPU 表面导致 HWND 重建后，重新应用 qframelesswindow 的原生窗口效果。

    QOpenGLWidget / QRhiWidget 等「渲染到纹理」控件在附加 GPU 表面时，会让 Qt
    重建顶层原生窗口（HWND）。这发生在 qframelesswindow 于 __init__ 阶段设置好
    WS_THICKFRAME（边框缩放）/ WS_CAPTION 样式与 DwmExtendFrameIntoClientArea
    （窗口阴影 + Win11 圆角）之后——重建后的新 HWND 会丢失这些原生能力，且
    qframelesswindow 不会自动重新应用。

    本 Mixin 监听 QEvent.WinIdChange：每当 HWND 变化，就在新句柄上重新应用窗口
    动画样式与 DWM 阴影/圆角，并触发一次非客户区重算。这样即可在保留 GPU 合成
    Mica 背景的同时，完整保留边框拖拽拉伸、最大化/最小化动画、窗口阴影与圆角。

    注意：该问题对 QOpenGLWidget 与 QRhiWidget 一致（两者都会触发 HWND 重建），
    因此此修复与底层图形 API 无关，切换到 QRhi 也仍需同样的重应用逻辑。
    """

    def event(self, e: QEvent) -> bool:
        if e.type() == QEvent.Type.WinIdChange:
            self._reapply_native_window_effects()
        return super().event(e)

    def _install_edge_hit_test_passthrough(self) -> None:
        """安装 WM_NCHITTEST 边缘穿透过滤器（幂等）。

        让覆盖窗口边缘的原生子窗口（如 MPV 视频面）不再截胡边缘命中测试，
        恢复 qframelesswindow 的 win32 原生边缘拖拽缩放。见
        :class:`_EdgeHitTestPassthroughFilter` 的说明。
        """
        if getattr(self, "_edge_hit_test_filter", None) is not None:
            return
        app = QApplication.instance()
        if app is None:
            return
        self._edge_hit_test_filter = _EdgeHitTestPassthroughFilter(self)
        app.installNativeEventFilter(self._edge_hit_test_filter)

    def _reapply_native_window_effects(self) -> None:
        """在当前 HWND 上重新应用 win32 窗口样式与 DWM 阴影/圆角。"""
        # windowEffect 仅存在于 Windows 原生 frameless 实现；回退到普通 QMainWindow 时跳过
        window_effect = getattr(self, "windowEffect", None)
        if window_effect is None:
            return
        try:
            hwnd = int(self.winId())
        except Exception:
            return
        if not hwnd:
            return
        try:
            window_effect.addWindowAnimation(hwnd)  # 恢复 WS_THICKFRAME / 最大化最小化动画样式
            window_effect.addShadowEffect(hwnd)      # 恢复 DWM 阴影 + Win11 圆角
            # 触发非客户区重算（SWP_FRAMECHANGED），让样式与 frame 立即生效
            swp_flags = 0x0002 | 0x0001 | 0x0004 | 0x0020  # NOMOVE|NOSIZE|NOZORDER|FRAMECHANGED
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, swp_flags)
        except Exception:
            # 原生效果重应用失败不应影响窗口正常使用
            pass


class MainWindow(_FramelessNativeEffectsMixin, FramelessMainWindow):
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
        self._root = None
        self._content = None
        self._panels = []
        self._splitter = None
        # 三栏布局延迟构建，先置 None 避免提前访问未定义属性
        self._file_selector = None
        self._file_pool = None
        self._previewer = None
        # 面板占位标签（加载中…），真实布局构建后移除
        self._panel_left_placeholder = None
        self._panel_center_placeholder = None
        self._panel_right_placeholder = None
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

        # 安装 WM_NCHITTEST 边缘穿透过滤器：嵌入 MPV 等原生子窗口覆盖窗口
        # 边缘时，仍由 qframelesswindow + win32 原生通道执行边缘拖拽缩放
        self._install_edge_hit_test_passthrough()

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
        # 中央部件用纯 QWidget，保留 qframelesswindow 的原生窗口特性
        # （边框拖拽拉伸 / 窗口阴影 / 最大化动画 / Aero Snap 均由顶层 HWND 处理）。
        # Mica 背景与内容作为它的两个叠放子层——避免让 GPU 表面占据窗口边缘、
        # 干扰 WM_NCHITTEST 的缩放边框命中。
        self._root = QWidget(self)
        self.setCentralWidget(self._root)
        # 不透明兜底：正常时被 Mica 层完全盖住；若 GL 合成因任何原因缺画，
        # 窗口显示主题表面色而非透出桌面（DWM 玻璃板上未绘制像素会全透明）
        root_palette = self._root.palette()
        root_palette.setColor(self._root.backgroundRole(), tm.surface)
        self._root.setPalette(root_palette)
        self._root.setAutoFillBackground(True)

        overlay = QGridLayout(self._root)
        overlay.setContentsMargins(0, 0, 0, 0)
        overlay.setSpacing(0)

        # 层 1：Mica 背景（GPU 合成，OpenGL 不可用时回退 CPU），内嵌在 frameless 窗口内。
        # 设为鼠标穿透，使窗口边缘事件仍落到顶层窗口，保证边框拉伸/系统菜单等原生行为。
        self._mica_background = make_mica_background(
            self._root,
            blur_radius=self._blur_radius,
            tint_color=self._tint_color,
            luminosity=self._luminosity,
            contrast=self._contrast,
            saturation=self._saturation,
        )
        self._mica_background.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # 层 2：内容层（透明容器，叠在 Mica 之上）
        self._content = QWidget(self._root)

        # 两层叠放在同一网格单元：Mica 在下、内容在上
        overlay.addWidget(self._mica_background, 0, 0)
        overlay.addWidget(self._content, 0, 0)
        self._mica_background.lower()
        self._content.raise_()

        # 创建主布局（内容层作为根容器）
        main_layout = QVBoxLayout(self._content)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

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

        # 三栏面板：先创建空 QFrame（含"加载中"占位），延后到窗口显示后
        # 再构建重型布局，使窗口先以主题色外壳 + 标题栏快速出现，避免白屏等加载。
        self._panel_left = QFrame()
        self._panel_left.setObjectName("PanelLeft")
        self._panel_left.setStyleSheet("background-color: transparent; border: none;")
        self._panel_left_layout = QVBoxLayout(self._panel_left)
        self._panel_left_layout.setContentsMargins(0, 0, 0, 0)
        self._panel_left_layout.setSpacing(0)
        self._panel_left_placeholder = self._make_panel_placeholder()
        self._panel_left_layout.addWidget(self._panel_left_placeholder)

        self._panel_center = QFrame()
        self._panel_center.setObjectName("PanelCenter")
        self._panel_center.setStyleSheet("background-color: transparent; border: none;")
        self._panel_center_layout = QVBoxLayout(self._panel_center)
        self._panel_center_layout.setContentsMargins(0, 0, 0, 0)
        self._panel_center_layout.setSpacing(0)
        self._panel_center_placeholder = self._make_panel_placeholder()
        self._panel_center_layout.addWidget(self._panel_center_placeholder)

        self._panel_right = QFrame()
        self._panel_right.setObjectName("PanelRight")
        self._panel_right.setStyleSheet("background-color: transparent; border: none;")
        self._panel_right_layout = QVBoxLayout(self._panel_right)
        self._panel_right_layout.setContentsMargins(0, 0, 0, 0)
        self._panel_right_layout.setSpacing(0)
        self._panel_right_placeholder = self._make_panel_placeholder()
        self._panel_right_layout.addWidget(self._panel_right_placeholder)

        self._panels = [self._panel_left, self._panel_center, self._panel_right]
        for panel in self._panels:
            self._splitter.addWidget(panel)

        # 窗口显示后再分阶段构建三栏重型布局（首屏提速，见 _build_panels_deferred）
        QTimer.singleShot(0, self._build_panels_deferred)

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

    # ──── 分阶段延迟构建三栏（首屏提速） ─────────────────────────────────

    def _make_panel_placeholder(self) -> QLabel:
        """生成面板加载占位标签（'加载中…'），真实布局构建后移除。"""
        label = QLabel("加载中…", self)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(
            f"color: {tm.text.name()}; background-color: transparent; font-size: 13px;"
        )
        return label

    def _build_panels_deferred(self) -> None:
        """窗口显示后分阶段构建三栏重型布局，避免启动白屏/长阻塞。

        左栏（文件选择器，最重）优先构建并显示，中/右栏随后补齐；
        全部就绪后连接跨栏信号、刷新样式并等分三栏。
        """
        QTimer.singleShot(0, lambda: self._build_panel("left"))
        QTimer.singleShot(30, lambda: self._build_panel("center"))
        QTimer.singleShot(60, lambda: self._build_panel("right"))
        QTimer.singleShot(90, self._finalize_panels)

    def _build_panel(self, side: str) -> None:
        """构建指定栏的真实布局，替换占位标签。单栏失败不应拖垮整体启动。"""
        try:
            if side == "left":
                self._file_selector = FileSelectorLayout(self._panel_left)
                self._panel_left_layout.removeWidget(self._panel_left_placeholder)
                self._panel_left_placeholder.deleteLater()
                self._panel_left_placeholder = None
                self._panel_left_layout.addWidget(self._file_selector)
            elif side == "center":
                self._file_pool = FilePoolLayout(self._panel_center)
                self._panel_center_layout.removeWidget(self._panel_center_placeholder)
                self._panel_center_placeholder.deleteLater()
                self._panel_center_placeholder = None
                self._panel_center_layout.addWidget(self._file_pool)
            elif side == "right":
                self._previewer = UnifiedPreviewerLayout(self._panel_right)
                self._panel_right_layout.removeWidget(self._panel_right_placeholder)
                self._panel_right_placeholder.deleteLater()
                self._panel_right_placeholder = None
                self._panel_right_layout.addWidget(self._previewer)
        except Exception as exc:  # 单栏构建失败不应拖垮整个启动
            warning(f"面板构建失败（{side}）: {exc}")
            return
        # 该栏刚就绪即刷新其边框/填充：即使其它栏尚未构建，也能让已就绪栏正确显示
        self._refresh_panel_styles()

    def _finalize_panels(self) -> None:
        """三栏全部就绪后：连接跨栏信号、刷新样式、等分三栏。

        右栏预览器较重，90ms 时可能仍未构建完成；故逐栏守卫连接已就绪者，
        并在仍有栏缺失时延后重试，确保跨栏信号最终全部连上（边框/填充已由
        _build_panel 渐进套用，不受此影响）。
        """
        if self._file_selector is not None:
            # 信号连接：文件选择器 → 文件池
            self._file_selector.add_to_pool_requested.connect(self._on_add_to_pool_requested)
            self._file_selector.toggle_pool_requested.connect(self._on_toggle_pool_requested)
            self._file_selector.file_selected.connect(self._on_file_selected)
            self._file_selector.preview_cancel_requested.connect(self._on_preview_cancelled)
        if self._file_pool is not None:
            # 信号连接：文件池 → 文件选择器（同步"已在池中"边框标记）
            self._file_pool.pool_changed.connect(self._on_pool_contents_changed)
            # 信号连接：文件池 → 统一预览器（左键点击文件池卡片时预览）
            self._file_pool.item_left_clicked.connect(self._on_pool_item_clicked)
            # 信号连接：文件池再次点击当前预览卡片 → 取消预览
            self._file_pool.preview_cancel_requested.connect(self._on_preview_cancelled)
            # 信号连接：文件池右键点击 → 移除文件池并取消选中
            self._file_pool.item_right_clicked.connect(self._on_pool_item_right_clicked)

        self._refresh_panel_styles()

        # 仍有栏尚未就绪：延后重试连接（样式已由 _build_panel 渐进套用）
        if self._file_selector is None or self._file_pool is None or self._previewer is None:
            QTimer.singleShot(60, self._finalize_panels)
            return
        QTimer.singleShot(0, self._equalize_splitter)

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

        # 主题切换按钮（SVG图标，dark=深色图标，light=浅色图标）
        light_icon_path = Path(__file__).resolve().parent.parent / "icons" / "title_light.svg"
        self._theme_btn = StyledButton(
            "", variant="ghost", size="sm",
            icon=str(light_icon_path) if light_icon_path.exists() else ""
        )
        self._theme_btn.setFixedSize(32, 32)
        self._theme_btn.setStyleSheet(self._title_bar_button_style())
        self._theme_btn.setToolTip("切换主题")
        self._theme_btn.clicked.connect(self._on_theme_toggle)
        header_layout.addWidget(self._theme_btn)

        # 最小化按钮（SVG图标）
        mini_icon_path = Path(__file__).resolve().parent.parent / "icons" / "title_mini.svg"
        self._minimize_btn = StyledButton(
            "", variant="ghost", size="sm",
            icon=str(mini_icon_path) if mini_icon_path.exists() else ""
        )
        self._minimize_btn.setFixedSize(32, 32)
        self._minimize_btn.setStyleSheet(self._title_bar_button_style())
        self._minimize_btn.clicked.connect(self.showMinimized)
        header_layout.addWidget(self._minimize_btn)

        # 最大化/还原按钮（SVG图标，max_1=最大化，max_2=还原）
        max_1_path = Path(__file__).resolve().parent.parent / "icons" / "title_max_1.svg"
        self._maximize_btn = StyledButton(
            "", variant="ghost", size="sm",
            icon=str(max_1_path) if max_1_path.exists() else ""
        )
        self._maximize_btn.setFixedSize(32, 32)
        self._maximize_btn.setStyleSheet(self._title_bar_button_style())
        self._maximize_btn.clicked.connect(self._toggle_maximize)
        header_layout.addWidget(self._maximize_btn)

        # 关闭按钮（SVG图标）
        close_icon_path = Path(__file__).resolve().parent.parent / "icons" / "title_close.svg"
        self._close_btn = StyledButton(
            "", variant="ghost", size="sm",
            icon=str(close_icon_path) if close_icon_path.exists() else ""
        )
        self._close_btn.setFixedSize(32, 32)
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
        max_1_path = Path(__file__).resolve().parent.parent / "icons" / "title_max_1.svg"
        max_2_path = Path(__file__).resolve().parent.parent / "icons" / "title_max_2.svg"
        if self.isMaximized():
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            # 窗口已还原，显示最大化图标（max_1）
            if max_1_path.exists():
                self._maximize_btn.set_svg_icon(str(max_1_path))
        else:
            ctypes.windll.user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            # 窗口已最大化，显示还原图标（max_2）
            if max_2_path.exists():
                self._maximize_btn.set_svg_icon(str(max_2_path))
    
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
        # 先捕获当前窗口快照并启动过渡遮罩，再切换主题，
        # 使新旧主题之间通过交叉淡化平滑过渡。
        # 使用 grabWindow(HWND) 而非 grab()，避免 OpenGL Mica 背景合成花屏。
        overlay = ThemeTransitionOverlay.from_widget(self)
        overlay.start()

        tm.toggle_theme()
        # 同步持久化到 SettingsManagerV2（重启后恢复）
        try:
            from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2
            v2 = SettingsManagerV2()
            v2.load()
            theme = "dark" if tm.is_dark_theme() else "light"
            v2.set("appearance.theme", theme)
            v2.set("appearance.colors", dict(tm._colors))
            v2.save()
        except Exception:
            pass
        # 按钮图标和 tooltip 在 _on_theme_changed 中更新

    def _on_theme_changed(self, theme_name: str) -> None:
        """主题切换后的处理"""
        # 更新 Mica 背景（快速重烘焙 tint/luminosity，复用已模糊的 base，不再重建/重新模糊）
        if self._mica_background is not None:
            self._mica_background.sync_theme()
        # 更新按钮图标和 tooltip（SVG，light=浅色，dark=深色）
        light_icon_path = Path(__file__).resolve().parent.parent / "icons" / "title_light.svg"
        dark_icon_path = Path(__file__).resolve().parent.parent / "icons" / "title_dark.svg"
        if theme_name == "light":
            # 当前浅色→点击切换为深色，显示深色图标
            if dark_icon_path.exists():
                self._theme_btn.set_svg_icon(str(dark_icon_path))
            self._theme_btn.setToolTip("切换为深色")
        else:
            # 当前深色→点击切换为浅色，显示浅色图标
            if light_icon_path.exists():
                self._theme_btn.set_svg_icon(str(light_icon_path))
            self._theme_btn.setToolTip("切换为浅色")
        # 刷新标题文字颜色
        if self._title_label is not None:
            self._title_label.setStyleSheet(f'font-size: 14px; font-weight: 600; color: {tm.text.name()};')
        # 刷新所有标题栏按钮的 styleSheet（tm 颜色值已变化）
        self._github_btn.setStyleSheet(self._title_bar_button_style())
        self._settings_btn.setStyleSheet(self._title_bar_button_style())
        self._theme_btn.setStyleSheet(self._title_bar_button_style())
        self._minimize_btn.setStyleSheet(self._title_bar_button_style())
        self._maximize_btn.setStyleSheet(self._title_bar_button_style())
        self._close_btn.setStyleSheet(self._title_bar_close_style())
        # 刷新 QSS 样式
        self.style().unpolish(self)
        self.style().polish(self)
        # 刷新三栏面板样式
        self._refresh_panel_styles()

    def _refresh_panel_styles(self) -> None:
        """刷新三个面板的 styleSheet（主题切换 / 延迟构建逐栏就绪时调用）。

        逐栏守卫：仅对当前已构建的栏套用边框/填充，因此可在三栏尚未全部就绪时
        被 ``_build_panel`` 渐进调用——已就绪栏立即正确显示，缺失栏留待其构建后
        的调用补齐（无需等三栏齐了才一次性刷新）。

        注意：延迟构建时本方法在窗口已显示之后被调用，而对已显示控件设置
        styleSheet 不会自动重绘，必须对各分区控件强制 unpolish/polish 才能让
        边框/填充生效（与主题切换路径一致）。
        """
        mid = tm.mid
        txt = tm.text
        # QColor.name() 不包含 alpha, 需要用 rgba() 格式保留透明度
        fill_color = f"rgba({txt.red()},{txt.green()},{txt.blue()},{5 / 100})"
        border_color = f"rgba({mid.red()},{mid.green()},{mid.blue()},{50 / 100})"

        if self._file_selector is not None:
            # 左侧栏 PanelLeft — 完全透明，样式下放给 FileSelectorLayout 内部
            self._panel_left.setStyleSheet("background-color: transparent; border: none;")
            self._file_selector.set_section_styles(fill_color, border_color)
        if self._file_pool is not None:
            # 中间栏 PanelCenter — 完全透明，样式下放给 FilePoolLayout 内部
            self._panel_center.setStyleSheet("background-color: transparent; border: none;")
            self._file_pool.set_section_styles(fill_color, border_color)
        if self._previewer is not None:
            # 右侧栏 PanelRight — 完全透明，样式下放给 UnifiedPreviewerLayout 内部
            self._panel_right.setStyleSheet("background-color: transparent; border: none;")
            self._previewer.set_section_styles(fill_color, border_color)

        # 整窗级重刷（与主题切换路径一致，作为兜底确保所有已显示控件套用样式）
        self.style().unpolish(self)
        self.style().polish(self)

    def _equalize_splitter(self) -> None:
        """等分三栏为 1:1:1（窗口完成布局后调用）"""
        total = self._splitter.width()
        # 扣除两个分隔条宽度（handleWidth=10×2）
        available = max(0, total - 20)
        third = available // 3
        self._splitter.setSizes([third, third, third])

    def _on_colors_updated(self, colors: dict) -> None:
        """配色加载完成后的处理：重新套用三栏面板样式（确保颜色就绪后边框/填充正确）。"""
        self._refresh_panel_styles()

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
        """处理文件选择器的文件选中事件，同步预览态到文件池与自身卡片"""
        file_path = file_info.get("path", "")
        self._file_selector.set_previewing_file(file_path)
        self._file_pool.set_previewing_file(file_path)
        self._previewer.set_file(file_info)

    def _on_pool_item_clicked(self, file_info: dict) -> None:
        """处理文件池卡片的左键点击事件，预览该文件"""
        file_path = file_info.get("path", "")
        self._file_selector.set_previewing_file(file_path)
        self._file_pool.set_previewing_file(file_path)
        self._previewer.set_file(file_info)

    def _on_preview_cancelled(self) -> None:
        """处理预览取消事件：清除卡片预览态并清空预览器"""
        self._file_selector.clear_previewing_state()
        self._file_pool.clear_previewing_state()
        self._previewer.clear_preview()

    def _on_pool_item_right_clicked(self, file_info: dict) -> None:
        """右键点击文件池卡片：移除文件池并取消文件选择器内的选中"""
        file_path = file_info.get("path", "")
        self._file_pool.remove_file(file_path)
        self._sync_selection_to_selector(file_path, False)

    def _sync_selection_to_selector(self, file_path: str, selected: bool) -> None:
        """同步选中状态到文件选择器"""
        pool_paths = self._file_pool.get_pool_paths()
        self._file_selector.sync_pool_status(pool_paths)

    # ──── 备份恢复 ─────────────────────────────────────────────────────

    def showEvent(self, event: QEvent) -> None:
        """窗口显示时检查备份恢复"""
        super().showEvent(event)
        if not hasattr(self, '_restore_started'):
            self._restore_started = True
            QTimer.singleShot(100, self._check_and_restore_backup)

        # 首帧提速：Mica 壁纸加载/高斯模糊/烘焙在 __init__ 阶段被延迟
        # （MicaMaterial lazy=True），这里在窗口显示后的第一轮事件循环里
        # 再执行。窗口先以纯色主题背景出现，模糊完成后无缝替换为 Mica。
        if not getattr(self, '_mica_refresh_started', False) and self._mica_background is not None:
            self._mica_refresh_started = True
            QTimer.singleShot(0, self._start_mica_refresh)

    def _start_mica_refresh(self) -> None:
        """延迟在后台线程执行 Mica 壁纸处理（不阻塞主线程/UI）。"""
        mica = getattr(self._mica_background, "_mica", None)
        if mica is not None:
            mica.refresh_async()

    def _dispose_mica(self) -> None:
        """回收后台 Mica 刷新线程，避免退出时残留野线程。"""
        mica = getattr(self._mica_background, "_mica", None)
        if mica is not None and hasattr(mica, "dispose"):
            mica.dispose()

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
        """窗口关闭时刷新备份保存到磁盘，释放服务资源，并回收后台 Mica 线程。"""
        self._dispose_mica()
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


class SettingsWindow(_FramelessNativeEffectsMixin, FramelessMainWindow):
    """
    设置窗口 — 独立窗口，tm.surface 纯色背景（不使用 Mica）

    不构造 Mica（壁纸加载+模糊+烘焙开销大），以加快窗口打开速度；
    背景色与 styled 弹窗 DialogContent 一致（tm.surface）。
    点击主窗口标题栏的设置按钮后弹出
    """

    def __init__(self, parent=None):
        # 先初始化属性，防止父类初始化期间触发的事件访问未定义属性
        self._mica_background = None  # 设置窗口不使用 Mica，保留属性做防御
        self._root = None
        self._title_label = None
        self._close_btn = None

        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumSize(700, 400)
        self.resize(700, 500)

        # 中央部件用纯 QWidget，保留 qframelesswindow 原生窗口特性；
        # tm.surface 不透明纯色背景（styled 弹窗同款），无 Mica 开销
        self._root = QWidget(self)
        self.setCentralWidget(self._root)
        root_palette = self._root.palette()
        root_palette.setColor(self._root.backgroundRole(), tm.surface)
        self._root.setPalette(root_palette)
        self._root.setAutoFillBackground(True)

        # 主布局直接建在根容器上
        layout = QVBoxLayout(self._root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏（仅关闭按钮）
        self._create_title_bar(layout)

        # 设置内容区
        from layout.settings_layout import SettingsLayout  # 延迟导入（启动提速）

        self._settings_layout = SettingsLayout(self._root)
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
        """主题切换时刷新背景色和标题栏样式"""
        self._sync_theme()

    def showEvent(self, event) -> None:
        """窗口显示/重新显示时刷新全量主题样式"""
        super().showEvent(event)
        self._sync_theme()

    def _sync_theme(self) -> None:
        """强制刷新当前主题下的所有样式"""
        # 纯色背景（tm.surface 随主题变化）
        if self._root is not None:
            palette = self._root.palette()
            palette.setColor(self._root.backgroundRole(), tm.surface)
            self._root.setPalette(palette)
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

        # 退出兜底：确保后台 Mica 线程在应用退出时被回收，避免野线程残留
        app.aboutToQuit.connect(window._dispose_mica)

        print("启动事件循环...")
        return app.exec()
    except Exception as e:
        print(f"发生错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())