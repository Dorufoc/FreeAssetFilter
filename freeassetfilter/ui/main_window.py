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

from PySide6.QtCore import Qt, QEvent, QPoint, QUrl, QTimer, QAbstractNativeEventFilter
from PySide6.QtGui import QDesktopServices
from PySide6.QtGui import QPainter, QPaintEvent, QPixmap, QRegion, QResizeEvent, QMoveEvent, QMouseEvent, QColor, QCursor

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

from components.custom_background import BACKGROUND_DIR_NAME, CustomImageBackgroundWidget
from components.mica_material import MicaMaterial
from components.mica_window import DEFAULT_MICA_CONFIG
from components.styled_button import StyledButton
# 内容层主题过渡遮罩（旧外观快照自绘淡出，轻量自绘替代整窗遮罩的两处卡顿源）
from components.theme_transition_overlay import ContentTransitionOverlay
# 实验性原生 DWM 云母开关的底层桥接（dwmapi 薄封装，惰性加载，零 COM 初始化）
from freeassetfilter.ui.mica import winapi as mica_winapi

# 导入布局模块
from layout.file_selector_layout import FileSelectorLayout
from layout.file_pool_layout import FilePoolLayout
from layout.unified_previewer_layout import UnifiedPreviewerLayout
# SettingsLayout 仅设置窗口使用，延迟到 _open_settings_window / SettingsWindow
# 实例化时再导入，避免启动路径加载 styled_sidebar / color_picker 等组件。

from freeassetfilter.utils.path_utils import get_app_data_path
from freeassetfilter.utils.app_logger import debug, warning
from freeassetfilter.services.staging_pool_service import StagingPoolService

# 简约背景层（try 包裹：组件 PR 合并前主窗口仍可导入，各调用点配合 getattr 守卫）
try:
    from components.minimalist_background import MinimalistBackgroundWidget
except ImportError:
    MinimalistBackgroundWidget = None  # type: ignore[assignment,misc]


# ── 米卡效果固定参数（按深浅色主题各一组） ─────────────────────────────
# 设置页不再提供米卡滑动条：参数为产品定值，随主题自动切换。
# 亮色模式 → 饱和度 8×、对比度 1×、模糊 200px、透明度 100%；
# 深色模式 → 饱和度 2×、对比度 1×、模糊 200px、透明度 80%。
FIXED_MICA_PARAMS: dict = {
    "light": {
        "blur_radius": 200,
        "saturation": 8.0,
        "contrast": 1.0,
        "tint_opacity": 100,
    },
    "dark": {
        "blur_radius": 200,
        "saturation": 2.0,
        "contrast": 1.0,
        "tint_opacity": 80,
    },
}


def fixed_mica_params() -> dict:
    """按当前主题返回固定的米卡效果参数（深浅色各一组）。

    Returns:
        dict: {"blur_radius": int, "saturation": float,
               "contrast": float, "tint_opacity": int}
    """
    return dict(FIXED_MICA_PARAMS["dark" if tm.is_dark_theme() else "light"])


class _MicaBackgroundMixin:
    """
    MicaBackgroundWidget 的共享逻辑（GPU 与 CPU 两种实现复用）。

    宿主类须为 QWidget 子类（依赖 palette()/update()/backgroundRole() 等）。
    主题由 ThemeManager（tm）统一管理。
    """

    def _init_mica_common(
        self,
        blur_radius: int,
        surface_color: str,
        luminosity: float,
        contrast: float,
        saturation: float,
        tint_opacity: int = 70,
    ) -> None:
        """按当前主题设置纯色背景/luminosity，创建 MicaMaterial 并设置基底色。"""
        self._blur_radius = blur_radius
        self._contrast = contrast
        self._saturation = saturation
        # 用户可调的模糊图像叠加透明度（%，0-100），绘制期生效（见 MicaMaterial.paint）
        self._tint_opacity = max(0, min(100, int(tint_opacity)))
        if tm.is_dark_theme():
            self._luminosity = 0.65
        else:
            self._luminosity = 0.85
        self._surface_color = self._theme_surface_color()

        self._mica = MicaMaterial(
            self,
            self._blur_radius,
            surface_color=self._surface_color,
            luminosity=self._luminosity,
            contrast=self._contrast,
            saturation=self._saturation,
            overlay_opacity=self._tint_opacity / 100.0,
            lazy=True,  # 延迟壁纸加载/模糊到窗口显示后（首帧提速，见 showEvent）
        )

        # 纯色不透明基底颜色：深色纯黑 / 浅色纯白（不再使用 tm.surface 灰色调）
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor(self._surface_color))
        self.setPalette(palette)

    def _theme_surface_color(self) -> str:
        """按当前系统深浅色模式返回纯色基底（完全不透明）。

        基底固定为两种纯色，随系统深浅色模式自动切换：
        - 深色模式 → 纯黑 #000000
        - 浅色模式 → 纯白 #FFFFFF
        用途：烘焙混合基色（render_display 的 overlay 预合成）与宿主 palette。
        模糊图像的显示状态由叠加层透明度（tint_opacity，0-100%）控制。

        注意：**绘制期兜底填充**（失焦暂停 / 无产物 / 淡入淡出底色）不使用
        本色 —— 由 MicaMaterial 以当前主题 G1 呈现（深 #1a1a1a / 浅 #f5f5f5，
        见 ``MicaMaterial._background_fill_color``）。
        """
        return "#000000" if tm.is_dark_theme() else "#FFFFFF"

    def apply_mica_parameters(
        self,
        blur_radius: Optional[int] = None,
        saturation: Optional[float] = None,
        contrast: Optional[float] = None,
        tint_opacity: Optional[int] = None,
    ) -> None:
        """更新米卡效果参数（设置窗口滑动条实时预览入口）。

        叠加层透明度（模糊图像绘制透明度）绘制期即时生效（仅触发重绘，
        不重烘焙）；模糊半径/饱和度/对比度在后台线程重建（不阻塞 UI）。
        未指定的参数保持不变。
        """
        if blur_radius is not None:
            self._blur_radius = max(0, int(blur_radius))
        if saturation is not None:
            self._saturation = max(0.0, float(saturation))
        if contrast is not None:
            self._contrast = max(0.0, float(contrast))
        if tint_opacity is not None:
            self._tint_opacity = max(0, min(100, int(tint_opacity)))
        if self._mica is None:
            return
        self._mica.set_effect_parameters(
            blur_radius=self._blur_radius if blur_radius is not None else None,
            overlay_opacity=(
                self._tint_opacity / 100.0
                if tint_opacity is not None else None
            ),
            saturation=self._saturation if saturation is not None else None,
            contrast=self._contrast if contrast is not None else None,
        )

    def sync_theme(self) -> None:
        """根据当前主题刷新纯色背景、luminosity 和基底颜色"""
        if tm.is_dark_theme():
            self._luminosity = 0.65
        else:
            self._luminosity = 0.85
        # 背景色随主题切换（深色纯黑 / 浅色纯白），完全不透明
        self._surface_color = self._theme_surface_color()

        # 更新基底颜色
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor(self._surface_color))
        self.setPalette(palette)

        # 快速重烘焙 luminosity（复用已模糊的 base，不再重新模糊）；
        # 背景色为绘制期读取，切换主题仅需重绘
        if self._mica is not None:
            # 翻转瞬间先用旧层快照起钟（与控件 280ms 过渡同窗口对齐），再提交
            # 后台重烘焙；新层交付时只换靶、不重启时钟（见
            # MicaMaterial.begin_theme_transition），两者同起同止。
            try:
                self._mica.begin_theme_transition()
            except Exception:  # noqa: BLE001 - 预起钟失败则退化为交付时过渡
                pass
            # 米卡参数按主题固定：与主题色 / 深浅标志一并在 key 计算前折入
            # set_theme —— 主题切换只起**一次**烘焙（单次收敛，替代旧的
            # 「set_theme 起烘 → 参数变更作废重烘」双烘链，等待期减半）。
            fixed = fixed_mica_params()
            self._mica.set_theme(
                self._surface_color,
                self._luminosity,
                blur_radius=fixed["blur_radius"],
                saturation=fixed["saturation"],
                contrast=fixed["contrast"],
                overlay_opacity=fixed["tint_opacity"] / 100.0,
            )
            # 原生 DWM 云母模式：深浅色属性随主题对齐（自研层停用，无需重烘焙）
            self._sync_native_dark_mode()
            self.update()

    def apply_native_mica(self, enabled: bool) -> bool:
        """实验开关：切换「原生 DWM 云母」（最佳努力，失败时自研层继续接管）。

        开启：``DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE=2, ...)`` +
        ``DwmExtendFrameIntoClientArea(margins=-1)``（帧扩展到整个客户区）+
        ``DWMWA_USE_IMMERSIVE_DARK_MODE`` 对齐当前主题深浅色；随后自研 Mica
        层停用（客户区铺纯黑，由 DWM 呈现原生云母，主线程零自研渲染开销）。
        任一 DWM 调用失败（非 Win11 / dwmapi 缺失）则保持自研层不变。

        关闭：背景类型置回 ``DWMSBT_DISABLED``、收回帧扩展，自研层重新
        接管并即时重烘焙。

        Args:
            enabled: 是否启用原生 DWM 云母。

        Returns:
            开关是否实际生效（``enabled=True`` 时代表 DWM 调用成功）。
        """
        enabled = bool(enabled)
        if self._mica is None:
            return False
        top = self.window()
        hwnd = 0
        try:
            if top is not None:
                hwnd = int(top.winId())
        except (TypeError, RuntimeError, ValueError):
            hwnd = 0
        if enabled:
            applied = False
            if hwnd:
                applied = mica_winapi.set_native_mica(hwnd, True)
                if applied:
                    # 深浅色正确性：让 DWM 按当前主题色调绘制原生云母。
                    mica_winapi.dwm_use_dark_mode(hwnd, tm.is_dark_theme())
            # 原生调用失败时保持自研层（applied=False → 不停用），避免整窗纯黑。
            self._mica.set_native_backdrop(applied)
            return applied
        # 关闭：无论原生是否曾生效，都恢复自研层。
        if hwnd:
            mica_winapi.set_native_mica(hwnd, False)
        self._mica.set_native_backdrop(False)
        return True

    def _sync_native_dark_mode(self) -> None:
        """主题切换时把 DWM 深浅色属性与当前主题对齐（仅原生云母模式需要）。"""
        if self._mica is None or not getattr(self._mica, "_native_backdrop", False):
            return
        top = self.window()
        try:
            hwnd = int(top.winId())
        except (TypeError, RuntimeError, ValueError, AttributeError):
            return
        mica_winapi.dwm_use_dark_mode(hwnd, tm.is_dark_theme())

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
        surface_color: str = "#000000",
        luminosity: float = 0.65,
        contrast: float = 1.5,
        saturation: float = 4.5,
        tint_opacity: int = 70,
    ) -> None:
        # 应用级防护（静态属性，重复设置无副作用）：阻止原生子窗（MPV 视频面等）
        # 连带把兄弟控件原生化。否则嵌入视频时本 GL 背景被原生化→合成失效→
        # 客户区未绘制像素在 DWM 玻璃板上直接透出桌面（窗口“全透明”bug）。
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings, True)
        super().__init__(parent)
        self._init_mica_common(blur_radius, surface_color, luminosity, contrast, saturation, tint_opacity)
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
        surface_color: str = "#000000",
        luminosity: float = 0.65,
        contrast: float = 1.5,
        saturation: float = 4.5,
        tint_opacity: int = 70,
    ) -> None:
        super().__init__(parent)
        # 纯色不透明基底（挡住 win32 控件）
        self.setAutoFillBackground(True)
        self._init_mica_common(blur_radius, surface_color, luminosity, contrast, saturation, tint_opacity)
        # 烘焙后 paint 始终铺满整个 rect 且不透明，声明不透明绘制
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制 Mica 效果（纯色背景 + 按透明度叠加的模糊壁纸）"""
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


class _GLSurfaceWarmupWidget(QOpenGLWidget):
    """1x1 透明 GL 占位：在主窗口首次显示前占据 GL 表面名额。

    背景：QOpenGLWidget 在**已显示**的顶层窗口中首次创建时，会迫使 Qt
    销毁并重建整个顶层 HWND（窗口类从普通 raster 类切换为 OwnDC 类）。
    音频预览的流体背景（StyledFluidBackground GPU 路径）正是在窗口显示后
    动态创建 QOpenGLWidget——这就是播放音频时主窗口消失、原地冒出一个
    同尺寸黑窗的根因（重建后的新 HWND 丢失无边框样式/DWM 扩展帧，
    内容来不及重绘便保持纯黑；MPV 音频不受影响故后台继续播放）。

    本占位在主窗口 ``show()`` 之前就已存在并可见，顶层窗口从创建之初
    就是 OwnDC 类，后续再创建流体背景等 GL 控件时不再触发 HWND 重建。
    控件本身 1x1 全透明、鼠标穿透、压在最底层，无视觉与交互影响。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(1, 1)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def paintGL(self) -> None:
        """仅清为全透明，不绘制任何内容。"""
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.end()


def make_mica_background(
    parent: Optional[QWidget] = None,
    blur_radius: int = 200,
    surface_color: str = "#000000",
    luminosity: float = 0.65,
    contrast: float = 1.5,
    saturation: float = 4.5,
    tint_opacity: int = 70,
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
        surface_color=surface_color,
        luminosity=luminosity,
        contrast=contrast,
        saturation=saturation,
        tint_opacity=tint_opacity,
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
        surface_color: Optional[str] = None,
        luminosity: Optional[float] = None,
        contrast: Optional[float] = None,
        saturation: Optional[float] = None,
    ) -> None:
        """
        初始化主窗口

        Args:
            parent: 父窗口
            blur_radius: Mica 模糊半径（默认使用项目配置）
            surface_color: Mica 纯色背景（深色纯黑/浅色纯白，默认使用主题决定）
            luminosity: Mica 亮度值（默认使用项目配置）
            contrast: Mica 对比度（默认使用项目配置）
            saturation: Mica 饱和度（默认使用项目配置）
        """
        # 先初始化属性，防止父类初始化期间触发的事件访问未定义属性
        self._mica_background = None
        self._gl_warmup = None
        self._custom_background = None
        self._minimalist_background = None
        self._background_mode = "mica"
        self._background_image_name = ""
        self._background_ambient = True
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
        # 设置窗口实例引用：防止局部变量被 GC 后窗口闪退；
        # 仅在设置窗口存活期间持有，关闭销毁后清空
        self._settings_window = None
        # 设置窗口代际计数器：destroyed 信号发自 ~QObject，槽收到的 obj
        # 是基类包装（实测为 'QWidget'），`is obj` 身份比对恒失败；
        # 故创建窗口时递增代际并绑定到槽，槽内按代际比对清空引用
        self._settings_window_gen = 0
        # 内容层主题过渡遮罩（单实例去重引用；见 _start_content_theme_transition）
        self._content_theme_overlay: QWidget | None = None
        # 系统主题监听器（跟随系统模式的实时链路；见 _start_system_theme_watcher）
        self._system_theme_watcher = None

        # 配置 Mica 参数（提前计算）：显式参数 > V2 保存值 > 项目默认
        cfg = DEFAULT_MICA_CONFIG
        mica_saved = self._load_mica_settings()
        background_saved = self._load_background_settings()
        self._background_mode = background_saved.get("mode", "mica")
        self._background_image_name = background_saved.get("image", "")
        self._background_ambient = bool(background_saved.get("ambient", True))
        self._background_blur = background_saved.get("blur", 0.0)
        self._background_transparency = background_saved.get("transparency", 80)
        self._blur_radius = blur_radius if blur_radius is not None else mica_saved["blur_radius"]
        # 背景色仅作回退默认值；实际绘制由 mixin 按主题决定（深色纯黑/浅色纯白）
        self._surface_color = surface_color if surface_color is not None else cfg["surface_color"]
        self._luminosity = luminosity if luminosity is not None else cfg["luminosity"]
        self._contrast = contrast if contrast is not None else mica_saved["contrast"]
        self._saturation = saturation if saturation is not None else mica_saved["saturation"]
        self._tint_opacity = mica_saved["tint_opacity"]

        # 应用级防护（须在创建任何子控件前设置）：阻止某个子控件原生化时
        # 连带把兄弟控件全部原生化。原生子窗口的位置由 Qt 异步同步，启动期
        # 曾出现子 HWND 被摆到错误坐标（内容整体偏移右下、左上露出主窗口
        # 残留的早期 raster 帧），且 Qt 侧几何数据完全正常、极难排查；
        # 拖动触发重摆放后才恢复。MPV 视频面等显式 WA_NativeWindow 的控件
        # 不受此属性影响，仍可正常嵌入。
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings, True)

        # 调用父类初始化
        super().__init__(parent)

        # 隐藏 qframelesswindow 默认 TitleBar 覆盖层：它叠在自绘标题栏区域，
        # 会拦截按钮点击/干扰命中（本项目标题栏完全自绘，见 _create_title_bar）。
        # 普通 QMainWindow 回退路径没有该属性，用 getattr 兜底。
        default_title_bar = getattr(self, "titleBar", None)
        if default_title_bar is not None:
            default_title_bar.hide()

        # 安装 WM_NCHITTEST 边缘穿透过滤器：嵌入 MPV 等原生子窗口覆盖窗口
        # 边缘时，仍由 qframelesswindow + win32 原生通道执行边缘拖拽缩放
        self._install_edge_hit_test_passthrough()

        # 设置窗口属性
        self._setup_window()

        # 创建内容布局
        self._setup_content()

        # 将窗口定位到鼠标所在屏幕的中心
        self._center_on_mouse_screen()

    @staticmethod
    def _load_mica_settings() -> dict:
        """返回当前主题固定的米卡效果参数（参数为产品定值，不再从设置读取）。

        历史上此处从 ``SettingsManagerV2`` 恢复 ``appearance.mica`` 保存值；
        参数固定后仅按深浅色主题返回对应定值（见 :data:`FIXED_MICA_PARAMS`），
        设置页的米卡滑动条已移除。

        Returns:
            dict: {"blur_radius": int, "saturation": float,
                   "contrast": float, "tint_opacity": int}
        """
        return fixed_mica_params()

    @staticmethod
    def _load_background_settings() -> dict:
        """启动时从 SettingsManagerV2 恢复自定义背景设置。

        读取 ``appearance.background`` 节点：mode 仅接受 "mica" / "image" /
        "minimalist"（非法值回退 "mica"），image 为持久化目录
        （data/backgrounds/）下的文件名（空字符串表示未设置，统一转为 str），
        ambient 缺失时默认 True（经 bool() 归一），blur 钳制到 0~200px
        整数（默认 0），transparency 归一到 0~100（默认 80，很透明）。
        中间版本的 opacity（不透明度 %）键按 transparency = 100 - opacity
        迁移（V2 合并层已处理，此处仅作读取兜底）。

        Returns:
            dict: {"mode": str, "image": str, "ambient": bool,
                "blur": int, "transparency": int}
        """
        defaults = {
            "mode": "mica",
            "image": "",
            "ambient": True,
            "blur": 0,
            "transparency": 80,
        }
        try:
            # 优先复用应用引导层提前加载的设置管理器（app/main.py 在
            # MainWindow 构造前已初始化），避免启动期二次磁盘加载；
            # 独立运行（无 app.settings_manager）时自建实例。
            app = QApplication.instance()
            v2 = getattr(app, "settings_manager", None)
            if v2 is None:
                from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2
                v2 = SettingsManagerV2()
                v2.load()
            saved = v2.get("appearance.background", {})
            if isinstance(saved, dict):
                mode = saved.get("mode", "mica")
                if mode not in ("mica", "image", "minimalist"):
                    mode = "mica"
                try:
                    blur = int(round(float(saved.get("blur", 0))))
                except (TypeError, ValueError):
                    blur = 0
                blur = max(0, min(200, blur))
                if "transparency" in saved:
                    raw_transparency = saved.get("transparency", 80)
                else:
                    # 兼容中间版本的 opacity（不透明度 %）
                    try:
                        legacy = int(round(float(saved.get("opacity", 20))))
                    except (TypeError, ValueError):
                        legacy = 20
                    raw_transparency = 100 - legacy
                try:
                    transparency = int(round(float(raw_transparency)))
                except (TypeError, ValueError):
                    transparency = 80
                transparency = max(0, min(100, transparency))
                return {
                    "mode": mode,
                    "image": str(saved.get("image", "")),
                    "ambient": bool(saved.get("ambient", True)),
                    "blur": blur,
                    "transparency": transparency,
                }
        except Exception:
            pass
        return defaults

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
        # 不透明兜底：正常时被背景层完全盖住；若合成因任何原因缺画，
        # 显示主题表面色（tm.surface = G1）而非透出桌面。与各背景层
        # 绘制期兜底同源：Mica _background_fill_color（G1）、简约层
        # bottom（blend 0% = G1）、图像层无图兜底。之前用纯黑/纯白，
        # 浅色下纯白 #FFFFFF 与 G1 灰白存在亮度差，主题切换重绘间隙
        # 会透出一帧纯白形成闪现。注意：Mica 烘焙混合基色仍用纯色
        # （见 _theme_surface_color），此处只改视觉兜底，不影响烘焙。
        main_surface = QColor(tm.surface)
        root_palette = self._root.palette()
        root_palette.setColor(self._root.backgroundRole(), main_surface)
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
            surface_color=self._surface_color,
            luminosity=self._luminosity,
            contrast=self._contrast,
            saturation=self._saturation,
            tint_opacity=self._tint_opacity,
        )
        self._mica_background.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # 层 1.5：自定义图像背景层（image 模式下覆盖云母层；鼠标穿透由组件自设）
        self._custom_background = CustomImageBackgroundWidget(self._root)

        # 层 1.75：简约背景层（minimalist 模式下盖住云母/图像层；组件不可用时为 None）
        if MinimalistBackgroundWidget is not None:
            self._minimalist_background = MinimalistBackgroundWidget(self._root)
            self._minimalist_background.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        else:
            self._minimalist_background = None

        # 层 2：内容层（透明容器，叠在云母之上）
        self._content = QWidget(self._root)

        # 三层叠放在同一网格单元（单元格内按添加顺序决定 z-order）：
        # 云母在最下、自定义图像居中、简约在内容之下最上、内容在最上
        overlay.addWidget(self._mica_background, 0, 0)
        overlay.addWidget(self._custom_background, 0, 0)
        if self._minimalist_background is not None:
            overlay.addWidget(self._minimalist_background, 0, 0)
        overlay.addWidget(self._content, 0, 0)
        self._mica_background.lower()
        self._content.raise_()
        if self._minimalist_background is not None:
            self._minimalist_background.stackUnder(self._content)

        # GL 表面预热（必须在窗口首次 show() 之前）：占据一个 GL 表面名额，
        # 使顶层 HWND 从创建起就是 OwnDC 类。否则音频预览的流体背景在窗口
        # 显示后动态创建首个 QOpenGLWidget，会触发顶层 HWND 销毁重建，
        # 表现为播放音频时主窗口消失、原地出现同尺寸黑窗。无头/无 GL 环境
        # 跳过（流体背景届时自动走 CPU 路径，不创建 GL 表面）。
        self._gl_warmup: Optional[QWidget] = None
        try:
            if os.environ.get("QT_QPA_PLATFORM", "").strip().lower() != "offscreen" and _opengl_available():
                self._gl_warmup = _GLSurfaceWarmupWidget(self._root)
                overlay.addWidget(self._gl_warmup, 0, 0)
                self._gl_warmup.lower()
        except Exception:
            self._gl_warmup = None

        # 启动恢复：按持久化文件名拼绝对路径加载自定义背景；文件缺失时
        # 组件内部回退纯色并记日志，不抛异常（见 CustomImageBackgroundWidget.set_image）
        if self._background_image_name:
            background_image_path = os.path.join(
                get_app_data_path(), BACKGROUND_DIR_NAME, self._background_image_name
            )
            self._custom_background.set_image(background_image_path)
        # 启动恢复图像可调参数（模糊度/透明度，无图时仅存状态不绘制）
        try:
            self._custom_background.set_blur_radius(self._background_blur)
        except Exception:
            pass
        try:
            self._custom_background.set_opacity(
                1.0 - self._background_transparency / 100.0
            )
        except Exception:
            pass

        # 初始可见性：三模式互斥，仅当前模式层可见
        self._custom_background.setVisible(self._background_mode == "image")
        if self._background_mode == "image":
            self._mica_background.setVisible(False)
        elif self._background_mode == "minimalist":
            self._mica_background.setVisible(False)
            self._custom_background.setVisible(False)
        minimalist = getattr(self, "_minimalist_background", None)
        if minimalist is not None:
            minimalist.setVisible(self._background_mode == "minimalist")
            minimalist.set_ambient_enabled(self._background_ambient)

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

        # 连接主题切换信号（生效值变化刷新顶栏图标/面板）
        tm.theme_changed.connect(self._on_theme_changed)
        tm.colors_updated.connect(self._on_colors_updated)

        # 跟随系统：启动系统主题轮询监听，系统变化时自动跟随切换。
        self._start_system_theme_watcher()

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
        if self._previewer is not None:
            # 信号连接：统一预览器底栏 → 定位到所在目录 / 清除预览
            self._previewer.locate_requested.connect(self._on_previewer_locate_requested)
            self._previewer.clear_requested.connect(self._on_preview_cancelled)

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
        """打开设置窗口（每次新建，关闭即销毁，不缓存窗口实例）。

        设置窗口以主窗口为 parent（Windows owned 窗口），从而：
        - 始终相对主窗口置顶（主窗口激活/点击不会盖住设置窗口）；
        - 主窗口关闭/退出时，设置窗口随宿主一并关闭销毁。
        窗口实例保存在 self._settings_window：若仅用函数局部变量持有，
        PySide6 会在函数返回后因 Python GC 销毁无父窗口的顶层窗口，
        导致设置窗口闪现后立即消失；destroyed 后释放引用以便下次重建。
        """
        win = self._settings_window
        if win is not None:
            try:
                visible = win.isVisible()
            except RuntimeError:
                # 兜底：C++ 对象已销毁但引用尚未清空，视为已关闭
                visible = False
            if visible:
                # 已打开 → 聚焦到前台
                win.raise_()
                win.activateWindow()
                return
            # 防御：引用未随 destroyed 清空时手动兜底
            self._settings_window = None

        window = SettingsWindow(self)
        self._settings_window = window
        self._settings_window_gen += 1
        gen = self._settings_window_gen
        window.setAttribute(Qt.WA_DeleteOnClose, True)
        window.destroyed.connect(lambda _obj=None, _gen=gen: self._on_settings_window_closed(_gen))
        window.show()
        window.raise_()
        window.activateWindow()

    def _on_settings_window_closed(self, gen: object = None) -> None:
        """设置窗口被关闭/销毁（含主窗口关闭连带销毁）后释放引用。

        Args:
            gen: 触发 destroyed 的窗口代际（创建窗口时绑定的计数器值）。
                仅当传入代际与当前代际一致（或无代际参数的直接调用）时
                才清空，防止旧窗口销毁事件晚到时误清已重建的新窗口引用。
                注意：不得改回 `is obj` 身份比对——destroyed 发自 ~QObject，
                槽收到的 obj 是基类包装，身份比对恒失败。
        """
        if gen is not None and gen != self._settings_window_gen:
            return
        self._settings_window = None

    def _start_content_theme_transition(self) -> None:
        """启动内容层主题过渡：切前抓内容子树快照，切后旧外观淡出。

        恢复此前被移除的整窗遮罩所承担的「组件渐变过渡」职责，但仅针对
        内容层（``_content``），且旧遮罩的两处卡顿源均已消除：

        - 快照用带透明通道的手动渲染（透明底 + 仅 ``DrawChildren``）绘制
          内容子树——不含 OpenGL 的 Mica 背景兄弟层，无 GL 花屏风险；
          也没有 ``QScreen.grabWindow(HWND)`` 的整窗同步截屏阻塞。
          关键：``QWidget.grab()`` 会用默认窗口底色填充透明区，使快照整幅
          不透明，遮罩淡出期间会把下方的图像/简约背景层严严盖住 280ms
          （即“图像先消失、动画后才回来”）。手动渲染跳过顶层自身背景，
          透明区保持透明，背景层全程可见；
        - 淡出由 :class:`ContentTransitionOverlay` 自绘（每帧单次
          ``drawPixmap``），替代 ``QGraphicsOpacityEffect`` 的逐帧全窗
          效果过滤合成。

        Mica 背景过渡由 ``MicaMaterial._start_xfade`` 材质级交叉过渡承担：
        遮罩只盖内容层、不遮背景层，两者独立并行、互不影响。未显示窗口
        （测试/最小化）无过渡——与 Mica 交叉过渡的 ``isVisible`` 守卫语义
        一致。
        """
        content = self._content
        if content is None or not content.isVisible():
            return
        # 单实例去重：上一过渡未结束则立即完成，避免连点叠加多层遮罩
        prev = self._content_theme_overlay
        if prev is not None:
            from shiboken6 import isValid

            if isValid(prev):
                prev.finish_now()
            self._content_theme_overlay = None
        try:
            size = content.size()
            if size.isEmpty():
                return
            snapshot = QPixmap(size)
            if snapshot.isNull():
                return
            snapshot.fill(Qt.transparent)
            snapshot_painter = QPainter(snapshot)
            try:
                content.render(
                    snapshot_painter,
                    QPoint(),
                    QRegion(),
                    QWidget.RenderFlag.DrawChildren,
                )
            finally:
                snapshot_painter.end()
        except Exception:  # noqa: BLE001 - 快照失败不阻塞主题切换本身
            return
        if snapshot.isNull():
            return
        overlay = ContentTransitionOverlay(content, snapshot)
        self._content_theme_overlay = overlay
        overlay.start()

    def _capture_background_pre_theme_state(self) -> None:
        """主题翻转前抓拍可见背景帧（tm 切换前调用）。

        仿云母 ``_capture_visual_state`` 的“过渡从屏幕现状出发”语义：把旧背景
        帧暂存进背景层，层在 ``sync_theme``（信号槽内同步触发）时以此为底图
        启动材质内交叉淡入。过渡中连切时抓到的是当前混合态，新过渡连续出发。
        mica 模式跳过（``MicaMaterial`` 在新层交付时自行捕获旧层）。
        """
        mode = getattr(self, "_background_mode", "mica")
        try:
            if mode == "image":
                target = getattr(self, "_custom_background", None)
                if target is not None:
                    target.capture_pre_theme_state()
            elif mode == "minimalist":
                target = getattr(self, "_minimalist_background", None)
                if target is not None:
                    target.capture_pre_theme_state()
        except Exception:  # noqa: BLE001 - 抓拍失败不阻塞主题切换
            pass

    def begin_theme_transition(self) -> None:
        """主题翻转前预抓拍内容与背景旧帧（供所有切换链路复用）。

        顶栏立即切换、系统跟随切换、设置页暂存提交三条链路在调用
        ``tm.set_theme*/set_theme_mode/apply_system_theme`` 之前都必须先调
        用本方法，否则背景层 ``sync_theme`` 因无 ``_pending_backdrop`` 退化
        为裸 ``update()``，重绘间隙漏出 ``_root`` 形成闪现。
        """
        try:
            self._start_content_theme_transition()
        except Exception:  # noqa: BLE001 - 快照失败不阻塞主题切换本身
            pass
        try:
            self._capture_background_pre_theme_state()
        except Exception:  # noqa: BLE001 - 抓拍失败不阻塞主题切换
            pass

    def _on_theme_toggle(self) -> None:
        """主题切换按钮点击事件（浅色↔深色立即切换，并固定为手动偏好）。

        按钮永远反映当前实际生效值：跟随系统模式下显示系统当前实际
        明暗；点击后翻转生效值，同时把设置页偏好从「跟随系统」自动
        切为对应手动值（「白天」/「夜晚」），保证两处状态同步。
        """
        # 内容+背景过渡预抓拍：切前抓内容层快照与背景旧帧，切后旧外观
        # 淡出、背景层以旧帧为底做 280ms 交叉淡入（见 begin_theme_transition）。
        self.begin_theme_transition()

        # 显式翻转生效值并固定为手动偏好（set_theme 语义即手动化，
        # 跟随模式点击后自动脱离跟随）。
        new_theme = "light" if tm.is_dark_theme() else "dark"
        tm.set_theme(new_theme)
        # 同步持久化到 SettingsManagerV2（偏好 + 生效值，重启后恢复）
        self._persist_theme_state()
        # 按钮图标和 tooltip 在 _on_theme_changed 中更新（按实际生效值）

    def _persist_theme_state(self) -> None:
        """持久化当前主题偏好与生效值到 SettingsManagerV2（重启后恢复）。

        同时写 ``appearance.theme_mode``（白天/夜晚/跟随系统）与
        ``appearance.theme``（实际生效深浅）及 ``appearance.colors`` 快照。
        失败静默忽略，不阻塞主题切换。
        """
        try:
            # 复用应用引导层加载的设置管理器（存在时），避免每次切换
            # 主题都新建实例 + 重新读盘。
            app = QApplication.instance()
            v2 = getattr(app, "settings_manager", None)
            if v2 is None:
                from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2
                v2 = SettingsManagerV2()
                v2.load()
            try:
                mode = tm.get_theme_mode()
            except Exception:
                mode = "dark" if tm.is_dark_theme() else "light"
            try:
                effective = tm.effective_theme()
            except Exception:
                effective = "dark" if tm.is_dark_theme() else "light"
            v2.set("appearance.theme_mode", mode)
            v2.set("appearance.theme", effective)
            v2.set("appearance.colors", dict(tm._colors))
            v2.save()
        except Exception:
            pass

    def _schedule_mica_opposite_prebake(self) -> None:
        """主题切换 settled 后空闲预烘对偶主题云母层（mica 模式）。

        真实烘焙与 280ms 过渡错开 2.5s，避免抢 CPU；触发时若条件已变
        （又一切换 / 切离 mica 模式）则跳过。预烘结果只进材质层缓存，
        下次回切命中即零等待呈现，与控件过渡同起。
        无头环境（offscreen，通常为测试）永不调度：预烘是真机优化，
        且后台线程会扰动测试进程。
        """
        try:
            if os.environ.get("QT_QPA_PLATFORM", "").strip().lower() == "offscreen":
                return
            if self._background_mode != "mica":
                return
            if getattr(self, "_mica_background", None) is None:
                return
            seq = getattr(self, "_theme_toggle_seq", 0) + 1
            self._theme_toggle_seq = seq
            QTimer.singleShot(2500, lambda: self._maybe_prebake_opposite(seq))
        except Exception:  # noqa: BLE001 - 预烘调度失败不影响已应用的主题
            pass

    def _maybe_prebake_opposite(self, seq: int) -> None:
        """空闲回调：条件未变才提交对偶主题预烘（见 _schedule_mica_opposite_prebake）。

        Args:
            seq: 调度时的切换代际；与当前不一致说明期间又发生切换，直接跳过。
        """
        try:
            if seq != getattr(self, "_theme_toggle_seq", -1):
                return
            if self._background_mode != "mica":
                return
            try:
                active = self.isActiveWindow()
            except Exception:
                active = False
            if not active:
                # 非激活窗口（最小化/切后台/无头测试）：不做后台预烘，
                # 避免无谓 CPU 与测试进程扰动；回切仍有层缓存加速。
                return
            mica_widget = getattr(self, "_mica_background", None)
            material = getattr(mica_widget, "_mica", None) if mica_widget is not None else None
            if material is None:
                return
            other = "light" if tm.is_dark_theme() else "dark"
            fixed = FIXED_MICA_PARAMS[other]
            material.prebake_theme_variant(
                surface_color="#FFFFFF" if other == "light" else "#000000",
                luminosity=0.85 if other == "light" else 0.65,
                blur_radius=fixed["blur_radius"],
                saturation=fixed["saturation"],
                contrast=fixed["contrast"],
                overlay_opacity=fixed["tint_opacity"] / 100.0,
            )
        except Exception:  # noqa: BLE001 - 预烘失败静默跳过
            pass

    def _start_system_theme_watcher(self) -> None:
        """启动 Windows 系统主题监听（跟随模式的实时跟随链路）。

        轮询到达且偏好为「跟随系统」时自动切换生效值并持久化；
        手动偏好下系统变化不做任何处理。启动失败静默忽略。
        """
        try:
            from freeassetfilter.ui.theme.system_theme import (
                get_system_theme_watcher,
            )

            watcher = get_system_theme_watcher()
            try:
                watcher.system_theme_changed.disconnect(
                    self._on_system_theme_changed
                )
            except Exception:
                pass
            watcher.system_theme_changed.connect(
                self._on_system_theme_changed
            )
            # 挂到主窗口，随窗口销毁自动回收。
            try:
                watcher.setParent(self)
            except Exception:
                pass
            watcher.start()
            self._system_theme_watcher = watcher
        except Exception:
            self._system_theme_watcher = None

    def _on_system_theme_changed(self, system_theme: str) -> None:
        """系统主题变化回调 — 仅跟随模式下跟随切换。

        Args:
            system_theme: 系统当前主题，"dark" 或 "light"。
        """
        try:
            mode = tm.get_theme_mode()
        except Exception:
            return
        if mode != "system":
            return
        try:
            current = tm.effective_theme()
        except Exception:  # noqa: BLE001 - 取不到生效值则按会变化处理
            current = ""
        if current == system_theme:
            return
        # 跟随切前同样预抓拍，否则主窗背景层无底图退化为裸重绘而闪现。
        self.begin_theme_transition()
        try:
            changed = tm.apply_system_theme(system_theme)
        except Exception:
            return
        if changed:
            self._persist_theme_state()

    def _on_theme_changed(self, theme_name: str) -> None:
        """主题切换后的处理。

        Args:
            theme_name: 新主题名（"light" 或 "dark"）。
        """
        # 冻结 _root 更新：把兜底切色、背景层 sync、QSS 换肤合并为一次重绘，
        # 消除 unpolish/polish 中间无样式白帧与背景层逐层重绘间隙。
        root = self._root
        updates_frozen = False
        if root is not None:
            try:
                root.setUpdatesEnabled(False)
                updates_frozen = True
            except Exception:  # noqa: BLE001 - 冻结失败则按普通路径继续
                updates_frozen = False
        try:
            # 兜底层（root）先切到主题表面色（tm.surface = G1），与各背景层
            # 绘制期兜底同源；必须先于背景层 sync，否则重绘间隙漏出旧色。
            # （见 _setup_content）。
            if root is not None:
                root_palette = root.palette()
                root_palette.setColor(
                    root.backgroundRole(),
                    QColor(tm.surface),
                )
                root.setPalette(root_palette)
            # 更新云母背景（重烘焙 luminosity，背景色绘制期生效，复用已模糊 base）
            if self._mica_background is not None:
                self._mica_background.sync_theme()
            # 同步自定义图像背景层（兜底色绘制期动态读取，仅需触发重绘）
            if self._custom_background is not None:
                self._custom_background.sync_theme()
            # 同步简约背景层（按新主题实时重算渐变）
            minimalist = getattr(self, "_minimalist_background", None)
            if minimalist is not None:
                minimalist.sync_theme()
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
            # 刷新三栏面板样式（内部含全窗级 unpolish/polish 兜底，此处不再
            # 单独做一次，避免连续两次无样式中间帧放大白闪）。
            self._refresh_panel_styles()
            # 空闲预烘对偶主题云母层（mica 模式）：下次回切零等待，与控件同起。
            self._schedule_mica_opposite_prebake()
        finally:
            if updates_frozen and root is not None:
                try:
                    root.setUpdatesEnabled(True)
                except Exception:  # noqa: BLE001 - 解冻失败不影响已应用的主题
                    pass

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
        """配色加载完成后的处理：重新套用三栏面板样式（确保颜色就绪后边框/填充正确）。

        Args:
            colors: 更新后的配色字典。
        """
        self._refresh_panel_styles()
        # 同步简约背景层（按新配色实时重算渐变）
        minimalist = getattr(self, "_minimalist_background", None)
        if minimalist is not None:
            minimalist.sync_theme()

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

    def _on_previewer_locate_requested(self, file_info: dict) -> None:
        """处理统一预览器底栏"定位到所在目录"请求：导航左侧选择器并高亮文件"""
        if self._file_selector is not None and file_info:
            self._file_selector.locate_file(file_info)

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

        # 首帧提速：云母壁纸加载/高斯模糊/烘焙在 __init__ 阶段被延迟
        # （MicaMaterial lazy=True），这里在窗口显示后的第一轮事件循环里
        # 再执行。窗口先以纯色主题背景出现，模糊完成后无缝替换为云母。
        # image/minimalist 模式启动时云母层被隐藏，跳过壁纸后台刷新以节省资源
        # （切回 mica 模式时由 set_background_mode 补刷）。
        if (
            not getattr(self, '_mica_refresh_started', False)
            and self._mica_background is not None
            and self._background_mode == "mica"
        ):
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

        # 检查 auto_restore 设置（新版 V2 设置树；默认自动恢复）
        app = QApplication.instance()
        auto_restore = True
        sm = getattr(app, 'settings_manager', None)
        if sm is not None:
            try:
                auto_restore = bool(sm.get("file_staging.auto_restore_records", True))
            except Exception:
                auto_restore = True

        if auto_restore:
            self._start_restore_backup(backup_data)
        # auto_restore=False：静默不恢复（原「是否恢复」确认弹窗已随
        # 2026-09 重构移除；自动恢复本体保留）。

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
        # 连带关闭设置窗口：设置窗口是主窗口的 owned 子窗口，原生层会随宿主
        # 关闭，此处显式 close 使其走 WA_DeleteOnClose 及时销毁并释放引用，
        # 避免隐藏后残留孤儿实例
        if self._settings_window is not None:
            try:
                from shiboken6 import isValid

                if isValid(self._settings_window):
                    self._settings_window.close()
            except RuntimeError:
                pass
            finally:
                self._settings_window = None
        self._dispose_mica()
        try:
            self._file_pool.flush_backup_save_now()
        except Exception:
            pass
        try:
            if self._previewer is not None:
                self._previewer.cleanup()
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
        """刷新背景（例如壁纸更改后）。

        云母/图像/简约三层各按自身逻辑重算（简约层按当前主题重算渐变）。
        """
        if self._mica_background is not None:
            self._mica_background.refresh_background()
        if self._custom_background is not None:
            self._custom_background.refresh_background()
        minimalist = getattr(self, "_minimalist_background", None)
        if minimalist is not None:
            minimalist.refresh_background()

    def set_background_mode(self, mode: str) -> None:
        """切换背景模式（mica / image / minimalist）。

        只切换背景层可见性、不销毁重建控件（三个背景层常驻，切换零构建成本）：

        - "image"：显示自定义图像层、隐藏云母层与简约层；
        - "minimalist"：显示简约层、隐藏云母层与自定义图像层，并把当前
          氛围开关同步给简约层；
        - "mica"：隐藏自定义图像层与简约层、显示云母层；若本次会话尚未执行过
          云母壁纸后台刷新（image/minimalist 模式启动时 showEvent 跳过了调度），
          这里补一次，避免云母层停留在未烘焙的纯色状态。

        Args:
            mode: 目标模式："mica"、"image" 或 "minimalist"；非法值记 warning 后忽略。
        """
        if mode not in ("mica", "image", "minimalist"):
            warning(f"忽略非法背景模式: {mode!r}（仅支持 'mica' / 'image' / 'minimalist'）")
            return
        self._background_mode = mode
        minimalist = getattr(self, "_minimalist_background", None)
        if mode == "image":
            self._custom_background.setVisible(True)
            self._mica_background.setVisible(False)
            if minimalist is not None:
                minimalist.setVisible(False)
        elif mode == "minimalist":
            self._custom_background.setVisible(False)
            self._mica_background.setVisible(False)
            if minimalist is not None:
                minimalist.setVisible(True)
                minimalist.set_ambient_enabled(self._background_ambient)
        else:
            self._custom_background.setVisible(False)
            if minimalist is not None:
                minimalist.setVisible(False)
            self._mica_background.setVisible(True)
            # image/minimalist 模式启动时 showEvent 跳过了云母后台刷新，这里补一次
            if not getattr(self, "_mica_refresh_started", False):
                self._mica_refresh_started = True
                self._start_mica_refresh()

    def set_ambient_enabled(self, enabled: bool) -> None:
        """设置简约背景的氛围开关并转发给简约层。

        Args:
            enabled: True 开启氛围渐变，False 使用纯色；经 bool() 归一后记录。
        """
        self._background_ambient = bool(enabled)
        minimalist = getattr(self, "_minimalist_background", None)
        if minimalist is not None:
            minimalist.set_ambient_enabled(self._background_ambient)

    def get_background_mode(self) -> str:
        """返回当前背景模式（供设置页实时联动与测试）。

        Returns:
            str: "mica"、"image" 或 "minimalist" 之一。
        """
        return self._background_mode

    def is_ambient_enabled(self) -> bool:
        """返回当前氛围开关状态（供设置页实时联动与测试）。

        Returns:
            bool: True 表示简约层氛围渐变开启。
        """
        return bool(self._background_ambient)

    def set_custom_background_image(self, path: str) -> bool:
        """设置自定义背景图片（转发给背景层组件）。

        Args:
            path: 图片文件绝对路径。

        Returns:
            bool: 加载成功返回 True；路径无效或无法解码返回 False
            （组件内部已记录日志并回退纯色兜底）。
        """
        return self._custom_background.set_image(path)

    def set_image_background_params(self, blur: float, opacity: float) -> None:
        """设置自定义图像背景的模糊度与不透明度（转发给背景层组件）。

        同步更新主窗口侧的记忆状态（``_background_blur`` /
        ``_background_transparency``），供后续模式切换与提交链路读取。

        Args:
            blur: 模糊半径 px（整数 0~200，越界钳制）。
            opacity: 不透明度 0~1（越界钳制；调用方需自行由透明度换算）。
        """
        try:
            blur_value = int(round(float(blur)))
        except (TypeError, ValueError):
            return
        blur_value = max(0, min(200, blur_value))
        try:
            opacity_value = max(0.0, min(1.0, float(opacity)))
        except (TypeError, ValueError):
            return
        self._background_blur = blur_value
        self._background_transparency = int(round((1.0 - opacity_value) * 100))
        layer = getattr(self, "_custom_background", None)
        if layer is None:
            return
        try:
            layer.set_blur_radius(blur_value)
        except Exception:
            pass
        try:
            layer.set_opacity(opacity_value)
        except Exception:
            pass
    
    # ---- 窗口事件处理 ----
    
    def resizeEvent(self, event: QResizeEvent) -> None:
        """窗口大小改变事件。

        Args:
            event: Qt 缩放事件。
        """
        super().resizeEvent(event)
        # 通知 MicaBackgroundWidget 刷新
        if self._mica_background is not None:
            self._mica_background.handle_window_resize()
        # 通知自定义图像背景层刷新（进入交互态，settle 后重建平滑缓存）
        if self._custom_background is not None:
            self._custom_background.handle_window_resize()
        # 通知简约背景层刷新（渐变固定于客户区，按新尺寸重绘）
        minimalist = getattr(self, "_minimalist_background", None)
        if minimalist is not None:
            minimalist.handle_window_resize()

    def moveEvent(self, event: QMoveEvent) -> None:
        """窗口移动事件"""
        super().moveEvent(event)
        # 通知 MicaBackgroundWidget 刷新
        if self._mica_background is not None:
            self._mica_background.handle_window_move()
        # 注意：不把移动事件转发给自定义图像层与简约层——图像/渐变固定于
        # 窗口客户区、不随窗口屏幕位置偏移或重新裁切（这是与云母按屏幕位置
        # 裁切的核心差异），无需刷新；组件的 handle_window_move 亦为空操作。


class SettingsWindow(_FramelessNativeEffectsMixin, FramelessMainWindow):
    """
    设置窗口 — 主窗口的 owned 子窗口，tm.surface 纯色背景（不使用 Mica）

    不构造 Mica（壁纸加载+模糊+烘焙开销大），以加快窗口打开速度；
    背景色与 styled 弹窗 DialogContent 一致（tm.surface）。
    点击主窗口标题栏的设置按钮后弹出；以主窗口为 parent（Windows owned
    窗口）——始终相对主窗口置顶，主窗口关闭时设置窗口一并关闭销毁。
    """

    def __init__(self, parent=None):
        # 先初始化属性，防止父类初始化期间触发的事件访问未定义属性
        self._mica_background = None  # 设置窗口不使用 Mica，保留属性做防御
        self._root = None
        self._title_label = None
        self._close_btn = None

        super().__init__(parent)

        # 隐藏 qframelesswindow 默认 TitleBar 覆盖层（同 MainWindow，避免拦截
        # 自绘标题栏的点击/命中）。普通 QMainWindow 回退路径没有该属性。
        default_title_bar = getattr(self, "titleBar", None)
        if default_title_bar is not None:
            default_title_bar.hide()

        self.setWindowTitle("设置")
        self.setMinimumSize(700, 400)
        self.resize(700, 500)

        # 定位：owned 窗口不显式定位时由 Windows 级联放置（落在屏幕右下），
        # 这里居中到宿主主窗口；无宿主时回退到鼠标所在屏幕中心。
        self._center_on_host()

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

        self._settings_layout = SettingsLayout(self._root, host_window=self)
        layout.addWidget(self._settings_layout)

        # 监听主题变化以刷新背景和按钮颜色
        tm.theme_changed.connect(self._on_theme_changed)

    def _center_on_host(self) -> None:
        """居中到宿主主窗口；无宿主时回退到鼠标所在屏幕中心"""
        host = self.parentWidget()
        if host is not None and host.isVisible():
            geo = host.geometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2
            self.move(x, y)
            return
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        geo = screen.geometry()
        self.move(
            geo.x() + (geo.width() - self.width()) // 2,
            geo.y() + (geo.height() - self.height()) // 2,
        )

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

    def closeEvent(self, event) -> None:
        """设置窗口关闭时触发暂存生命周期：未提交则自动清除缓存。

        右上角 ``✕`` 等同于「取消」：丢弃暂存并恢复界面至原始状态。
        """
        try:
            layout = getattr(self, "_settings_layout", None)
            if layout is not None and hasattr(layout, "on_host_closing"):
                layout.on_host_closing()
        except Exception:
            pass
        super().closeEvent(event)


def main() -> int:
    """
    调试用独立入口（保留便于单独运行窗口调试）。

    注意：正式启动入口是 ``freeassetfilter.app.main``（含日志捕获 /
    单实例 / 启动任务调度 / 退出链等完整引导设施）。本入口只创建
    QApplication + MainWindow，两个入口共享同一 MainWindow 实现，
    应保持观感一致；后续若决定合并入口，请删除本函数与下方
    ``__main__`` 块及相关注释。

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