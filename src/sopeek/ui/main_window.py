#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sopeek 主窗口
基于 PySideSix-Frameless-Window 和项目自定义 Mica 效果的无边框主窗口
"""

import sys
import time
import warnings
from typing import Optional
import os

from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
import ctypes
from ctypes import wintypes

from PySide6.QtCore import (
    Qt,
    QEvent,
    QObject,
    QPoint,
    QRect,
    QTimer,
    Signal,
    QAbstractNativeEventFilter,
    QPropertyAnimation,
    QEasingCurve,
)
from PySide6.QtGui import QPainter, QPaintEvent, QPixmap, QRegion, QResizeEvent, QMoveEvent, QMouseEvent, QKeyEvent, QColor, QCursor, QPalette

# UI 短路径导入（components/theme/...）由 sopeek.ui 包在导入时注入，
# 见 sopeek/ui/__init__.py；包本身可导入说明源码根已在 sys.path 上。
import sopeek.ui  # noqa: F401  (副作用：把 sopeek/ui 加入 sys.path)

try:
    from sopeek.ui.frameless_window import (
        _EDGE_BORDER,
        _get_user32,
        FramelessMainWindow,
    )
except ImportError:
    # 极端回退：如果本地无边框基类不可用，使用普通 QMainWindow
    from PySide6.QtWidgets import QMainWindow as FramelessMainWindow

    _EDGE_BORDER = 8  # 与 frameless_window 的默认值保持一致

    def _get_user32():
        """回退实现：无本地无边框基类时 user32 原型表不可用。"""
        return None

from sopeek.ui.elevated_drop import ElevatedDropFallbackMixin

# tm 别名已在 theme/__init__.py 中注册
# from theme import tm 与从 sopeek.ui.theme import tm 指向同一实例
from theme import tm

from components.custom_background import CustomImageBackgroundWidget
from components.app_logo import app_logo_pixmap
# MicaMaterial（sopeek.ui.mica.material）不在模块级导入：它经
# mica.engine 连带 numpy，导入约 0.16s，属「窗口出现前」关键路径。材质改为
# 窗口显示后惰性创建（见 _MicaBackgroundMixin._ensure_mica_material），与既有
# lazy=True「首帧纯色、后台烘焙」策略同源。
# 默认配置常量从纯数据模块 mica.config 取，避免连带 numpy（material 仍再导出）。
from sopeek.ui.mica.config import DEFAULT_MICA_CONFIG
from components.styled_button import StyledButton
from components.modal_guard import MODAL_PASSTHROUGH_PROPERTY, get_modal_guard
from components.styled_fluid_background import prewarm_top_level_rhi
# 启动加载覆盖层：铺满整个客户区、垫在标题栏之下只显示一个旋转圆环
# （见 MainWindow._setup_startup_overlay / _mount_startup_overlay）
from components.styled_loading import StyledLoading
from components.styled_dialog import close_active_dialogs
# 内容层主题过渡遮罩（旧外观快照自绘淡出，轻量自绘替代整窗遮罩的两处卡顿源）
# 与背景层交叉过渡遮罩（设置页切换窗口背景：旧背景帧淡出、新层实时在底）
from components.theme_transition_overlay import (
    BackgroundTransitionOverlay,
    ContentTransitionOverlay,
)
# 设置窗口过渡：窗口内快照等比缩放（弹出感）+ 关闭原地淡出
from components.window_transition import (
    SETTINGS_WINDOW_CLOSE_MS,
    SETTINGS_WINDOW_OPEN_MS,
    SETTINGS_WINDOW_OPEN_SCALE,
    SettingsWindowSnapshotLayer,
    TransitionInputBlocker,
    client_snapshot_geometry,
)
# 实验性原生 DWM 云母开关的底层桥接（dwmapi 薄封装，惰性加载，零 COM 初始化）
from sopeek.ui.mica import winapi as mica_winapi

# 主题切换「目标外观就绪」等待上限（毫秒）：遮罩起钟前若目标主题外观
# （QSS/调色板/内容重绘）尚未完成，最多等待此时间；超时强制放行，避免
# 极端情况下观察器收不到 Paint 事件导致遮罩永不揭幕（见就绪观察器）。
THEME_READY_TIMEOUT_MS: int = 350

# 三栏布局模块（FileSelectorLayout / FilePoolLayout / UnifiedPreviewerLayout）
# 不在模块级导入：它们连同 thumbnail_manager / file_card_delegate / numpy 等
# 约 0.2s 的重型依赖会被算进「窗口出现前」的关键路径。三栏本就在窗口显示后
# 才由 _build_panel 构建，故改为调用点局部导入（见 _build_panel）。
# SettingsLayout 同理：仅设置窗口使用，延迟到 _open_settings_window /
# SettingsWindow 实例化时再导入，避免启动路径加载 styled_sidebar /
# color_picker 等组件。

from sopeek._paths import backgrounds_dir, icons_dir
from sopeek.utils.animation_settings import is_animation_enabled
from sopeek.utils.app_logger import debug, info, warning
from sopeek.utils.win32_foreground import (
    force_foreground_window,
    is_foreground_window,
)
# perf_metrics / StagingPoolService 同为首屏关键路径让位：分别由绘制埋点
# （MicaBackgroundWidgetCpu.paintEvent）与 closeEvent 局部导入。
from sopeek.ui.theme.app_stylesheet import (
    apply_app_stylesheet,
    register_widget_qss,
)

# 简约背景层（try 包裹：组件 PR 合并前主窗口仍可导入，各调用点配合 getattr 守卫）
try:
    from components.minimalist_background import MinimalistBackgroundWidget
except ImportError:
    MinimalistBackgroundWidget = None  # type: ignore[assignment,misc]


# ── 米卡效果固定参数（按深浅色主题各一组） ─────────────────────────────

FIXED_MICA_PARAMS: dict = {
    "light": {
        "blur_radius": 200,
        "saturation": 8.0,
        "contrast": 1.0,
        "tint_opacity": 98,
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


class _MicaChainPreloader(QObject):
    """Mica 依赖链预导入的完成通知（延迟导入 → 记账回调）。

    依赖链（``sopeek.ui.mica.material`` → ``mica.engine`` → numpy 等）首次导入
    实测约 0.16s。历史实现丢到后台线程导入以避开首帧，但 PySide6 6.10 下
    「后台线程导入 + 主线程 Qt 事件处理」存在原生竞态（进程 Aborted / 挂死，
    见 ``_start_mica_chain_preload`` 说明），现改为主线程 ``QTimer`` 延迟导入，
    本信号仅用于通知记账方（刷新请求早于导入完成时等待）。
    """

    ready = Signal()


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
        layer_source=None,
    ) -> None:
        """按当前主题设置纯色背景/luminosity，创建 MicaMaterial 并设置基底色。

        Args:
            layer_source: 可选的源 ``MicaMaterial``；非空时本背景控件不烘焙，
                只共享源材质的视口层（设置窗口沿用主窗口 Mica 背景用）。
        """
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
        #: 共享层借用模式的源材质；``None`` 表示普通（自烘焙）背景控件。
        #: 设置窗口由 make_mica_background(..., layer_source=主窗口材质) 传入。
        self._mica_layer_source = layer_source

        # 材质（MicaMaterial）延迟到窗口显示后创建（见 _ensure_mica_material）：
        # 其导入链含 numpy（约 0.12s），不应计入窗口出现前的关键路径；材质本就
        # lazy=True（首帧纯色、烘焙在窗口显示后的后台线程完成），故后移不改观感。
        self._mica = None

        # 纯色不透明基底颜色：深色纯黑 / 浅色纯白（不再使用 tm.surface 灰色调）
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor(self._surface_color))
        self.setPalette(palette)

    def _ensure_mica_material(self):
        """惰性创建 MicaMaterial（窗口显示后由 _start_mica_refresh 首次触发）。

        延迟原因：``ui.mica.material`` → ``mica.engine`` → numpy 的导入
        约 0.16s，属「窗口出现前」关键路径；而材质本就 ``lazy=True``（首帧以
        纯色呈现、壁纸模糊在窗口显示后的后台线程完成），整体后移不改变首帧观感。
        材质未就位期间由 :meth:`_paint_solid_fallback` 铺同色基底。

        Returns:
            MicaMaterial: 已创建（或已存在）的材质实例。
        """
        if self._mica is not None:
            return self._mica
        from sopeek.ui.mica.material import MicaMaterial

        self._mica = MicaMaterial(
            self,
            self._blur_radius,
            surface_color=self._surface_color,
            luminosity=self._luminosity,
            contrast=self._contrast,
            saturation=self._saturation,
            overlay_opacity=self._tint_opacity / 100.0,
            lazy=True,  # 延迟壁纸加载/模糊到窗口显示后（首帧提速，见 showEvent）
            layer_source=self._mica_layer_source,
        )
        return self._mica

    @staticmethod
    def _paint_solid_fallback(painter: QPainter, rect) -> None:
        """材质未就位时的纯色兜底填充（与材质未烘焙时的底色一致）。

        材质 ``_background_fill_color`` 在未烘焙时铺当前主题 G1（深 #1a1a1a /
        浅 #f5f5f5，即 ``tm.surface``），此处取同色，材质就位后无缝接替。

        Args:
            painter: 当前绘制器。
            rect: 待填充区域。
        """
        painter.fillRect(rect, QColor(tm.surface))

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
            # 翻转瞬间先用旧层快照起钟（与控件 450ms 揭示同窗口对齐），再提交
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
        # 材质惰性化后此处可能尚未创建（窗口显示后首轮事件循环才建），
        # 显式确保：refresh 请求本身就是「需要材质」的语义。
        self._ensure_mica_material().refresh()


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
        layer_source=None,
    ) -> None:
        # 应用级防护（静态属性，重复设置无副作用）：阻止原生子窗（MPV 视频面等）
        # 连带把兄弟控件原生化。否则嵌入视频时本 GL 背景被原生化→合成失效→
        # 客户区未绘制像素在 DWM 玻璃板上直接透出桌面（窗口“全透明”bug）。
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings, True)
        super().__init__(parent)
        self._init_mica_common(
            blur_radius, surface_color, luminosity, contrast, saturation,
            tint_opacity, layer_source=layer_source,
        )
        # 背景恒不透明并铺满整窗，声明不透明绘制
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def paintGL(self) -> None:
        """在 GPU 光栅引擎上绘制 Mica 背景（烘焙纹理的子区域 blit）"""
        painter = QPainter(self)
        mica = self._mica
        if mica is None:
            # 材质尚未创建（窗口显示后的首轮事件循环才建，见
            # _ensure_mica_material）：先铺同色纯色基底，材质就位后无缝接替
            self._paint_solid_fallback(painter, self.rect())
        else:
            mica.paint_gpu(painter)
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
        layer_source=None,
    ) -> None:
        super().__init__(parent)
        # 纯色不透明基底（挡住 win32 控件）
        self.setAutoFillBackground(True)
        self._init_mica_common(
            blur_radius, surface_color, luminosity, contrast, saturation,
            tint_opacity, layer_source=layer_source,
        )
        # 烘焙后 paint 始终铺满整个 rect 且不透明，声明不透明绘制
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制 Mica 效果（纯色背景 + 按透明度叠加的模糊壁纸）"""
        # 局部导入：perf_metrics 自身模块级初始化约 50ms，不应计入窗口出现前
        # 的关键路径（首帧提速；sys.modules 缓存后每次绘制仅字典查找）。
        from sopeek.utils.perf_metrics import begin_frame, end_frame

        _frame_token = begin_frame()
        try:
            painter = QPainter(self)
            mica = self._mica
            if mica is None:
                # 材质尚未创建（窗口显示后的首轮事件循环才建，见
                # _ensure_mica_material）：先铺同色纯色基底，材质就位后无缝接替
                self._paint_solid_fallback(painter, self.rect())
            else:
                mica.paint(painter, event)
            painter.end()
        finally:
            end_frame(_frame_token)

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
    surface_color: str = "#000000",
    luminosity: float = 0.65,
    contrast: float = 1.5,
    saturation: float = 4.5,
    tint_opacity: int = 70,
    *,
    layer_source=None,
    force_cpu: bool = False,
) -> QWidget:
    """
    创建 Mica 背景控件：默认 CPU 光栅版，环境变量 ``SPK_USE_GL_MICA=1`` 强制 GPU 版。

    为什么默认 CPU 版（2026-08 实测结论）：
    - 在 Windows 上 QOpenGLWidget 需要把 GL 表面与 raster 内容合成到同一窗口，
      每次 resize 都有 FBO 重建 + 纹理合成等待，实测每步多出 ~8-13ms，
      且 GL 内容滞后时窗口边缘会露出未绘制底板（DWM 玻璃板透出桌面）。
    - CPU 版交互路径（fast scaling blit 模糊纹理）在 1200x800 与 2560x1440
      下均更快，且与内容层同属 raster 引擎、同步绘制、无合成滞后。
    - GPU 版保留：设置 SPK_USE_GL_MICA=1 且 OpenGL 可用时启用（大窗口
      低内存带宽机器可手动选择）。

    两者公共 API 一致（sync_theme / refresh_background / handle_window_resize /
    handle_window_move / _mica），调用方无需区分。

    Args:
        layer_source: 共享层借用模式的源 ``MicaMaterial``（设置窗口叠加在主窗口
            背景之上时传入）。
        force_cpu: 强制使用 CPU 光栅版。设置窗口必须走此路径：QOpenGLWidget 会
            新建 GL 上下文/表面，与主窗口的背景控件叠加时容易触发合成问题。
    """
    use_gl = os.environ.get("SPK_USE_GL_MICA", "") == "1" and not force_cpu
    cls = MicaBackgroundWidgetGL if (use_gl and _opengl_available()) else MicaBackgroundWidgetCpu
    return cls(
        parent,
        blur_radius=blur_radius,
        surface_color=surface_color,
        luminosity=luminosity,
        contrast=contrast,
        saturation=saturation,
        tint_opacity=tint_opacity,
        layer_source=layer_source,
    )


# 向后兼容别名：默认指向工厂（含 OpenGL 回退）；调用 MicaBackgroundWidget(...) 等价于 make_mica_background(...)
MicaBackgroundWidget = make_mica_background


class _EdgeHitTestPassthroughFilter(QAbstractNativeEventFilter):
    """
    原生子窗口覆盖窗口边缘时，让 WM_NCHITTEST 命中测试穿透回主窗口。

    背景：本地无边框基类（FramelessMainWindow）的边缘拖拽缩放依赖顶层窗口
    （主窗口）收到 ``WM_NCHITTEST`` 并返回 ``HTLEFT/HTRIGHT/...`` 命中码，
    之后由系统以原生 ``WM_SYSCOMMAND/SC_SIZE`` 通道执行缩放。当视频播放布局
    嵌入 MPV 时，视频渲染面（``WA_NativeWindow`` 原生子窗口）铺满预览器区域，
    会覆盖主窗口的右边缘（及视频面所在的下边缘）；鼠标移到这些位置时，
    ``WM_NCHITTEST`` 发送给子窗口而非主窗口，子窗口默认返回 ``HTCLIENT``，
    于是该段边缘无法拖拽缩放。

    本过滤器在应用级原生消息层（QAbstractNativeEventFilter，等价于 win32
    消息钩子，不改动任何控件类）拦截 ``WM_NCHITTEST``：
    1. 消息目标不是主窗口本身（主窗口的命中测试仍由本地无边框基类的
       ``nativeEvent`` 原样处理），而是主窗口的原生后代子窗口；
    2. 鼠标屏幕坐标落在主窗口边缘带（与本地无边框基类的 _EDGE_BORDER
       一致）内；
    则返回 ``HTTRANSPARENT``——系统会把命中测试继续交给同线程的下层窗口
    （即主窗口），由本地无边框基类原有逻辑返回正确的边缘命中码。

    结果：边缘缩放完全复用本地无边框基类 + win32 原生缩放通道，不引入
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
            # 主窗口自身的命中测试交给本地无边框基类 nativeEvent 处理
            return False, 0

        # 仅处理主窗口的原生后代（视频面等嵌入子窗口），不干扰其他顶层窗口
        if not _is_native_descendant(hwnd, main_hwnd):
            return False, 0

        # lParam 高 16 位为屏幕 Y，低 16 位为屏幕 X（带符号，支持负坐标副屏）
        lp = int(msg.lParam)
        x = ctypes.c_short(lp & 0xFFFF).value
        y = ctypes.c_short((lp >> 16) & 0xFFFF).value

        rect = wintypes.RECT()
        user32 = _get_user32()
        if user32 is None or not user32.GetWindowRect(main_hwnd, ctypes.byref(rect)):
            return False, 0
        border = _EDGE_BORDER  # 与本地无边框基类一致（WS_THICKFRAME 边框宽，物理 8px）
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
    """判断 hwnd 是否为 ancestor 的原生后代窗口（沿父链上溯）。

    经 :func:`frameless_window._get_user32` 取已声明 argtypes 的 user32，
    避免 64 位 HWND 被默认 c_int 截断（审查 3.1#24）。
    """
    user32 = _get_user32()
    if user32 is None:
        return False
    cur = user32.GetAncestor(hwnd, 1)  # GA_PARENT
    while cur:
        if int(cur) == ancestor:
            return True
        cur = user32.GetAncestor(cur, 1)
    return False


class _FramelessNativeEffectsMixin:
    """在 GPU 表面导致 HWND 重建后，重新应用本地无边框窗口的原生效果。

    QOpenGLWidget / QRhiWidget 等「渲染到纹理」控件在附加 GPU 表面时，会让 Qt
    重建顶层原生窗口（HWND）。新方案下 WS_THICKFRAME/WS_CAPTION 样式与
    DwmExtendFrameIntoClientArea 由 Qt 的 ExpandedClientAreaHint 在窗口创建
    时自动应用，重建后 Qt 会一并恢复；需要手动补充的是 Qt 6.9+ 为
    ExpandedClientAreaHint 创建的系统标题栏子窗口 ``_q_titlebar``，以及重建
    瞬间系统按标准窗口算出的原生标题栏——两者均由基类
    :meth:`FramelessMainWindow.reapply_native_window_effects` 处理，其
    ``WinIdChange``/``showEvent`` 钩子已覆盖本场景，故此处不再重复。

    本 Mixin 只负责安装 WM_NCHITTEST 边缘穿透过滤器（见
    :class:`_EdgeHitTestPassthroughFilter`），让 MPV 等原生子窗口覆盖边缘时
    仍可原生缩放。

    注意：该问题对 QOpenGLWidget 与 QRhiWidget 一致（两者都会触发 HWND 重建），
    因此此修复与底层图形 API 无关，切换到 QRhi 也仍需同样的重应用逻辑。
    """

    def _install_edge_hit_test_passthrough(self) -> None:
        """安装 WM_NCHITTEST 边缘穿透过滤器（幂等）。

        让覆盖窗口边缘的原生子窗口（如 MPV 视频面）不再截胡边缘命中测试，
        恢复本地无边框窗口的 win32 原生边缘拖拽缩放。见
        :class:`_EdgeHitTestPassthroughFilter` 的说明。
        """
        if getattr(self, "_edge_hit_test_filter", None) is not None:
            return
        app = QApplication.instance()
        if app is None:
            return
        self._edge_hit_test_filter = _EdgeHitTestPassthroughFilter(self)
        app.installNativeEventFilter(self._edge_hit_test_filter)


class MainWindow(ElevatedDropFallbackMixin, _FramelessNativeEffectsMixin, FramelessMainWindow):
    """
    主窗口类 - 使用无边框窗口和 Mica 效果

    Features:
        - 无边框窗口设计
        - Mica 模糊背景效果
        - Windows 11 现代化风格
        - 完全不透明的基底，遮挡 win32 原生控件
    """

    #: 启动加载覆盖层：最短展示时长（避免启动过快时一闪而过）/ 最长存活兜底
    #: （三栏构建异常时仍会撤下遮罩）/ 淡出时长；单位毫秒
    #: 启动覆盖层最短展示时长（避免启动过快时一闪而过，也避免“已经好了还在转”）。
    #: 400ms 在旧启动耗下刚好不闪；启动路径优化后它反而成为束缚尾延迟，
    #: 降到 250ms 仍能防“闪一下”，同时缩短感知的转圈时间。
    STARTUP_OVERLAY_MIN_MS = 250
    STARTUP_OVERLAY_MAX_MS = 8000
    STARTUP_OVERLAY_FADE_MS = 200

    #: 标题栏软件图标（位于软件名称左侧）的逻辑像素边长。
    TITLE_BAR_LOGO_SIZE = 20
    #: 软件图标与标题文字之间的水平间距（px）。
    TITLE_BAR_LOGO_GAP = 8

    #: 背景模式真正变化后发出（参数为目标模式）。设置窗口据此只在 mica
    #: 模式下显示共享层背景，切到 image / minimalist 时立即隐藏。
    background_mode_changed = Signal(str)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        blur_radius: Optional[int] = None,
        surface_color: Optional[str] = None,
        luminosity: Optional[float] = None,
        contrast: Optional[float] = None,
        saturation: Optional[float] = None,
        defer_heavy_init: bool = False,
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
            defer_heavy_init: 正式启动时延后非必要的图形预热，优先显示窗口框架。
        """
        self._defer_heavy_init = bool(defer_heavy_init)
        self._deferred_content_ready = False
        # 先初始化属性，防止父类初始化期间触发的事件访问未定义属性
        self._mica_background = None
        self._custom_background = None
        self._minimalist_background = None
        self._background_mode = "mica"
        self._background_image_name = ""
        self._background_ambient = True
        self._root = None
        self._content = None
        # 主布局装配（classic / workspace 两种组装；延迟构建，先置 None）
        self._layout_mode = "workspace"
        self._main_layout = None
        self._zones = {}
        # 区域占位标签（加载中…），真实布局构建后移除；键：selector/preview/pool/info
        self._zone_placeholders = {}
        # 四个叶子组件延迟构建，先置 None 避免提前访问未定义属性
        self._file_selector = None
        self._file_pool = None
        self._previewer = None
        self._info_panel = None
        self._info_card = None
        # 内容尚未构建时收到的外部打开请求（资源管理器右键菜单），
        # 由 initialize_deferred_content 末尾消费（见 open_external_path）。
        self._pending_external_open_path = None
        # 预览器尚未构建时收到的预览请求：_show_preview 只暂存，等
        # initialize_deferred_content 末尾统一兑现（否则右键菜单在启动早期
        # 打开文件时 previewer 还是 None，请求会被静默丢掉）。
        self._pending_preview_file_info = None
        # 信息面板比预览器更晚构建；预览已生效但信息面板还不存在时暂存一份，
        # 由 _finalize_panels 在面板齐备后补填（否则右侧信息区会一直是空的）。
        self._pending_info_file_info = None
        # 快捷键派发器安装标记（幂等安装/卸载，见 _install_shortcut_dispatcher）
        self._shortcut_installed: bool = False
        # 快捷键派发器实例（由 _install_shortcut_dispatcher 赋值）
        self._shortcuts = None
        # 快捷键处理器是否已接线（见 _setup_shortcuts）
        self._shortcuts_wired: bool = False
        # 进入预览器前的焦点区（path/selector/pool/info）：压缩包/文件夹
        # 预览器在根目录再按 Esc 时据此把焦点交还（见 _on_preview_root_escape）
        self._zone_before_preview: str = ""
        # 最近一次真正绘制过焦点描边的区域：鼠标点击据此去重，避免
        # focusChanged 先把快捷键区域改到点击处后导致「跨区点击不高亮」，
        # 同时保证同一焦点区内连续点击不重复闪烁（见 _sync_region_from_click）。
        self._last_flash_zone: str = ""
        # 「预览 / 储存 / 信息全空」时，从文件选择器切区的第一次按键先停在
        # 选择器并高亮它；下一次才继续到路径框（见 _focus_next_zone）。
        self._empty_cycle_selector_stay: bool = False
        # 启动默认焦点是否已补（正式启动先显示轻量外壳，窗口激活时四区尚未
        # 构建；见 _focus_selector_on_startup）
        self._startup_focus_applied: bool = False
        # 启动期是否已尝试切到 Windows 原生前台（见 ensure_startup_foreground）
        self._startup_foreground_done: bool = False
        # 倍速键按下前的倍速（长按回滚用）
        self._media_prev_speed: float = 1.0
        # 全局存储池浮窗：实例引用 + 三个信号连接对象。连接对象必须存引用
        # （供 set_floating_pool_enabled(False) 精确断开——lambda 槽无法按
        # 方法断连）；唯一创建入口为 _ensure_floating_pool。
        self._floating_pool = None
        self._floating_pool_conn_add = None
        self._floating_pool_conn_remove = None
        self._floating_pool_conn_pool_changed = None
        self._floating_pool_conn_hide = None
        # closeEvent 重入保护（退场动画期间的有界事件循环会放行其他事件）。
        self._close_in_progress = False
        # 强制退出标记：托盘「彻底退出」或用户在关闭询问中选择退出时置 True，
        # 使 closeEvent 跳过关闭询问与托盘挂起，直接走清理路径（见 closeEvent）。
        self._force_quit = False
        # 关闭询问弹窗是否正在显示：防重入，弹窗期间再次关闭按「取消」处理。
        self._close_dialog_open = False
        # 系统托盘状态：控制器实例、是否已判定不可用（避免反复重试创建）、
        # 是否已挂起（隐藏窗口并卸载预览/背景渲染资源），以及挂起前的
        # 预览器与信息面板文件快照（恢复时据此重新加载，见 _suspend_for_tray）。
        self._tray_controller = None
        self._tray_unavailable = False
        self._tray_suspended = False
        self._tray_preview_file = None
        self._tray_info_file = None
        # 启动加载覆盖层：唯一加载动画，铺满整个客户区并垫在标题栏之下，
        # 三栏就绪后淡出（见 _setup_startup_overlay / _dismiss_startup_overlay）
        self._startup_overlay = None
        self._startup_overlay_timer = None
        self._startup_overlay_animation = None
        self._startup_overlay_started_at = 0.0
        self._splitter_container = None
        # 自绘标题栏 QFrame：启动加载覆盖层据它做 stackUnder，使遮罩不透明底
        # 铺到标题栏区域、而标题栏文字与按钮仍留在遮罩之上（见 _mount_startup_overlay）
        self._title_bar_header = None
        self._settings_btn = None
        self._theme_btn = None
        self._minimize_btn = None
        self._maximize_btn = None
        self._title_label = None
        self._title_icon_label = None
        self._close_btn = None
        # 设置窗口实例引用：防止局部变量被 GC 后窗口闪退；
        # 仅在设置窗口存活期间持有，关闭销毁后清空
        self._settings_window = None
        # 设置窗口首次打开预热标记：启动加载层期间预建一次，避免用户首次
        # 点击设置时再付 QSS/布局的一次性成本（实测约 0.3~0.5s）。
        self._settings_prewarm_done = False
        # 设置窗口代际计数器：destroyed 信号发自 ~QObject，槽收到的 obj
        # 是基类包装（实测为 'QWidget'），`is obj` 身份比对恒失败；
        # 故创建窗口时递增代际并绑定到槽，槽内按代际比对清空引用
        self._settings_window_gen = 0
        # 内容层主题过渡遮罩（单实例去重引用；见 _start_content_theme_transition）
        self._content_theme_overlay: QWidget | None = None
        # 主题切换「目标外观就绪」观察器（冷启动首次点击时遮罩暂缓起钟，
        # 待内容层完成一次实际重绘后再放行；见 _arm_theme_ready）
        self._theme_ready_seq: int = 0
        self._theme_ready_filter: QObject | None = None
        self._theme_ready_timer: QTimer | None = None
        # 布局切换代际计数：新一轮切换递增，作废上一轮未收尾的恢复回调
        self._layout_transition_generation: int = 0
        # 背景层交叉过渡遮罩（单实例去重引用；见 _start_background_transition）
        self._background_transition_overlay: QWidget | None = None
        # P7.4：失焦宽限期定时器（30s 后释放流体/Mica 纹理）
        self._idle_texture_timer: QTimer | None = None
        # 系统主题监听器（跟随系统模式的实时链路；见 _start_system_theme_watcher）
        self._system_theme_watcher = None

        # 配置 Mica 参数（提前计算）：显式参数 > V2 保存值 > 项目默认
        cfg = DEFAULT_MICA_CONFIG
        mica_saved = self._load_mica_settings()
        background_saved = self._load_background_settings()
        # 主界面布局模式（general.layout_mode；非法值回退 workspace）
        self._layout_mode = self._load_layout_settings()
        # 关闭主窗口行为（general.close_action；非法值回退 "ask"）：
        # "ask"（每次询问） | "tray"（最小化到系统托盘） | "quit"（直接退出）。
        # 启动值在下方通用开关解包之后从 V2 读取；提交时经
        # set_close_action 即时生效（落盘由设置页完成）。
        self._close_action: str = "ask"
        # 通用功能开关（general.enable_ai_entry / general.include_remote_drives /
        # general.blank_right_click_go_back / general.show_hidden_files /
        # general.show_system_files / general.floating_pool_enabled /
        # general.floating_pool_snap_enabled；非法值回退：浮窗 False（默认关闭）、
        # 贴边吸附 True（浮窗子选项），其余一律 False；
        # 提交时经 set_ai_entry_enabled / set_include_remote_drives /
        # set_blank_right_click_go_back / set_show_hidden_files /
        # set_show_system_files / set_floating_pool_enabled /
        # set_floating_pool_snap_enabled 即时生效）
        (
            self._ai_entry_enabled,
            self._include_remote_drives,
            self._blank_right_click_go_back,
            self._show_hidden_files,
            self._show_system_files,
            self._floating_pool_enabled,
            self._floating_pool_snap_enabled,
        ) = self._load_general_toggles()
        self._close_action = self._load_close_action()
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

        # Mica 依赖链预导入（numpy 等，首次约 0.16s）：只做准备，实际安排在
        # 窗口显示后（见 showEvent → _start_mica_chain_preload），且导入动作
        # 本身在主线程延迟执行——历史后台线程方案在 PySide6 6.10 下与主线程
        # Qt 事件处理存在原生竞态（进程 Aborted / 挂死），详见该方法说明。
        self._mica_chain_ready = False
        self._mica_refresh_pending = False
        self._mica_preload_started = False
        self._mica_chain_preloader = _MicaChainPreloader(self)
        self._mica_chain_preloader.ready.connect(self._on_mica_chain_ready)

        # 合成后端预热：**必须在顶层窗口建窗（show()/winId()）之前完成**。
        # 顶层窗口只在 QWindow 创建前其层级内已存在 QRhiWidget 时才选 RHI
        # 合成后端；晚于建窗再挂预热控件，之后创建的 QRhiWidget 永远拿不到
        # QRhi（实测控制台仅打印 "QRhiWidget: No QRhi"），流体背景只能回退
        # CPU 静态帧。预热控件 1x1 且隐藏、从不渲染，因此不会推迟首帧，
        # 两条构造路径（defer_heavy_init 与否）都必须在这里创建。
        self._rhi_prewarm = prewarm_top_level_rhi(self)

        # 隐藏 Qt 6.9+ 的 `_q_titlebar` 系统标题栏子窗口（由本地无边框基类
        # FramelessMainWindow 在 __init__/showEvent/WinIdChange 自动处理，
        # 此处不再需要手动隐藏 titleBar 覆盖层）。

        # 安装 WM_NCHITTEST 边缘穿透过滤器：嵌入 MPV 等原生子窗口覆盖窗口
        # 边缘时，仍由本地无边框基类 + win32 原生通道执行边缘拖拽缩放
        self._install_edge_hit_test_passthrough()

        # 设置窗口属性
        self._setup_window()

        # 创建内容布局。正式入口只创建轻量 shell，避免重型背景/分栏构建
        # 阻塞首帧；默认路径保持原有同步构造契约。
        if self._defer_heavy_init:
            self._setup_lightweight_content()
        else:
            self._setup_content()

        # 快捷键派发器：内容就绪后安装（幂等）。同时挂到 destroyed 做兜底
        # 卸载——未经 closeEvent 的销毁路径（测试/异常）不得在全局
        # QApplication 上残留过滤器；槽内含 try/except RuntimeError 防御
        # 析构中途调用（此时 C++ 对象已在拆除）。
        self.destroyed.connect(lambda *_: self._uninstall_shortcut_dispatcher())
        self._install_shortcut_dispatcher()

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
        （assets/backgrounds/）下的文件名（空字符串表示未设置，统一转为 str），
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
                from sopeek.core.managers.settings_manager_v2 import SettingsManagerV2
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
        except Exception as exc:
            debug(f"读取背景设置失败（回退默认值）：{exc}")
        return defaults

    @staticmethod
    def _load_layout_settings() -> str:
        """启动时读取主界面布局模式（``general.layout_mode``）。

        取值 "classic"（经典三栏）或 "workspace"（预览优先，新布局）；
        缺失/非法一律回退 "workspace"（与 DEFAULT_SETTINGS_V2 默认一致）。

        Returns:
            str: 布局模式："classic" 或 "workspace"。
        """
        try:
            # 优先复用应用引导层提前加载的设置管理器（与背景设置同模式），
            # 避免启动期二次磁盘加载。
            app = QApplication.instance()
            v2 = getattr(app, "settings_manager", None)
            if v2 is None:
                from sopeek.core.managers.settings_manager_v2 import SettingsManagerV2
                v2 = SettingsManagerV2()
                v2.load()
            mode = v2.get("general.layout_mode", "workspace")
        except Exception:
            mode = "workspace"
        return mode if mode in ("classic", "workspace") else "workspace"

    @staticmethod
    def _load_general_toggles() -> tuple[bool, bool, bool, bool, bool, bool, bool]:
        """启动时读取通用功能开关。

        读取 ``general.enable_ai_entry``（AI 入口）、
        ``general.include_remote_drives``（网络盘/光驱）、
        ``general.blank_right_click_go_back``（空白区右键返回上一级）、
        ``general.show_hidden_files``（显示隐藏文件）、
        ``general.show_system_files``（显示系统文件）、
        ``general.floating_pool_enabled``（全局存储池浮窗）与
        ``general.floating_pool_snap_enabled``（浮窗贴边吸附）。前六个开关
        缺失、类型非法一律回退 False（与 DEFAULT_SETTINGS_V2 默认一致）；
        全局浮窗默认关闭、贴边吸附默认开启，缺失与类型非法分别回退
        False / True。隐藏/系统开关的 AND 语义由过滤层判定（系统开关只影响
        同时带「隐藏+系统」双重位的条目），此处不做归一化。

        Returns:
            tuple[bool, bool, bool, bool, bool, bool, bool]: (AI 入口开关,
            网络盘与光驱开关, 空白区右键返回开关, 显示隐藏文件开关,
            显示系统文件开关, 全局浮窗开关, 贴边吸附开关)。
        """
        ai_entry = False
        include_remote = False
        blank_right_click_go_back = False
        show_hidden = False
        show_system = False
        floating_pool = False
        floating_pool_snap = True
        try:
            app = QApplication.instance()
            v2 = getattr(app, "settings_manager", None)
            if v2 is None:
                from sopeek.core.managers.settings_manager_v2 import SettingsManagerV2
                v2 = SettingsManagerV2()
                v2.load()
            saved_ai = v2.get("general.enable_ai_entry", False)
            saved_remote = v2.get("general.include_remote_drives", False)
            saved_blank_back = v2.get(
                "general.blank_right_click_go_back", False
            )
            saved_hidden = v2.get("general.show_hidden_files", False)
            saved_system = v2.get("general.show_system_files", False)
            saved_floating = v2.get("general.floating_pool_enabled", False)
            saved_floating_snap = v2.get(
                "general.floating_pool_snap_enabled", True
            )
            ai_entry = saved_ai if isinstance(saved_ai, bool) else False
            include_remote = (
                saved_remote if isinstance(saved_remote, bool) else False
            )
            blank_right_click_go_back = (
                saved_blank_back if isinstance(saved_blank_back, bool) else False
            )
            show_hidden = saved_hidden if isinstance(saved_hidden, bool) else False
            show_system = saved_system if isinstance(saved_system, bool) else False
            floating_pool = (
                saved_floating if isinstance(saved_floating, bool) else False
            )
            floating_pool_snap = (
                saved_floating_snap
                if isinstance(saved_floating_snap, bool)
                else True
            )
        except Exception as exc:
            debug(f"读取功能开关设置失败（按默认值处理）：{exc}")
        return (
            ai_entry,
            include_remote,
            blank_right_click_go_back,
            show_hidden,
            show_system,
            floating_pool,
            floating_pool_snap,
        )

    @staticmethod
    def _load_close_action() -> str:
        """启动时读取关闭主窗口行为（``general.close_action``）。

        取值 "ask"（每次询问）、"tray"（最小化到系统托盘）或 "quit"
        （直接退出）；缺失/非法一律回退 "ask"（与 DEFAULT_SETTINGS_V2
        默认一致）。

        Returns:
            str: 关闭行为："ask"、"tray" 或 "quit"。
        """
        try:
            # 优先复用应用引导层提前加载的设置管理器，避免启动期二次磁盘加载。
            app = QApplication.instance()
            v2 = getattr(app, "settings_manager", None)
            if v2 is None:
                from sopeek.core.managers.settings_manager_v2 import SettingsManagerV2
                v2 = SettingsManagerV2()
                v2.load()
            behavior = v2.get("general.close_action", "ask")
        except Exception:
            behavior = "ask"
        return behavior if behavior in ("ask", "tray", "quit") else "ask"

    def _setup_window(self) -> None:
        """设置窗口基本属性"""
        self.setWindowTitle("Sopeek")
        self.resize(1200, 800)
        # 顶层窗口自身也要有主题底色：延迟构建/替换 central widget 的间隙，
        # 否则会露出 QMainWindow 的系统默认底色（深色系统 + 浅色主题 = 整窗闪黑）。
        # 轻量壳/完整内容各自的 root palette 只覆盖 central widget，盖不住这里。
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(tm.surface))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        # 同步原生擦除底色（WM_ERASEBKGND 路径，普通代码路径提前写入；
        # 原生消息处理中不回调 Qt）。
        if hasattr(self, "set_erase_background_color"):
            self.set_erase_background_color(QColor(tm.surface))

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

    def _setup_lightweight_content(self) -> None:
        """创建首帧所需的轻量窗口外壳。

        这里刻意不创建 Mica、图片背景、分栏和任何业务布局；窗口可以先
        ``show()``，进入事件循环后再由 :meth:`initialize_deferred_content`
        替换为完整内容。
        """
        self._root = QWidget(self)
        self.setCentralWidget(self._root)
        palette = self._root.palette()
        palette.setColor(self._root.backgroundRole(), QColor(tm.surface))
        self._root.setPalette(palette)
        self._root.setAutoFillBackground(True)

        root_layout = QVBoxLayout(self._root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self._content = QWidget(self._root)
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self._create_title_bar(content_layout)

        self._splitter_container = QWidget(self._content)
        container_layout = QVBoxLayout(self._splitter_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        placeholder = QLabel("正在加载…", self._splitter_container)
        placeholder.setAlignment(Qt.AlignCenter)
        register_widget_qss(
            placeholder,
            f"color: {tm.text.name()}; background-color: {tm.surface.name()}; font-size: 13px;",
        )
        container_layout.addWidget(placeholder)
        content_layout.addWidget(self._splitter_container, stretch=1)
        root_layout.addWidget(self._content)
        self._setup_startup_overlay()

    def initialize_deferred_content(self) -> None:
        """在首帧后构建完整内容；可重复调用且只执行一次。"""
        if not self._defer_heavy_init or getattr(self, "_deferred_content_ready", False):
            return
        self._deferred_content_ready = True
        old_root = self._root
        if old_root is not None:
            old_root.deleteLater()
        old_overlay_timer = self._startup_overlay_timer
        if old_overlay_timer is not None:
            old_overlay_timer.stop()
        self._mica_background = None
        self._custom_background = None
        self._minimalist_background = None
        self._splitter_container = None
        self._startup_overlay = None
        self._startup_overlay_timer = None
        self._setup_content()
        # RHI 合成后端已在 __init__ 建窗之前预热（见那里注释）；此时窗口早已
        # show()，再挂预热控件只会得到 "QRhiWidget: No QRhi"，因此不再重复。
        # 内容是在 showEvent 之后创建的，因此手动补齐原本由 showEvent
        # 负责的首帧后工作，避免 Mica/覆盖层停留在未启动状态。
        if self._startup_overlay is not None:
            self._mount_startup_overlay()
            if self._startup_overlay_timer is not None:
                self._startup_overlay_timer.start(self.STARTUP_OVERLAY_MAX_MS)
        if self._background_mode == "mica" and self._mica_background is not None:
            # Mica 依赖链（numpy 等，约 0.15s）不在此处导入：它落在加载圈
            # 可见期会直接造成一次 150ms 级停顿。改由 _finalize_panels 在
            # 遮罩淡出后再安排（见 _schedule_mica_startup_refresh）。
            self._mica_refresh_pending = True
        # 内容构建期间收到的右键菜单打开请求在此兑现：文件选择器此时才存在，
        # 之前只能暂存（见 open_external_path）。
        pending_open = self._pending_external_open_path
        self._pending_external_open_path = None
        if pending_open:
            self.open_external_path(pending_open)
        # 预览器此前尚不存在而暂存的预览请求，此刻兑现（见 _show_preview）；
        # 预览器仍未就绪时 _flush_pending_preview 会按帧退避重试。
        self._flush_pending_preview()

    def _flush_pending_preview(self, attempt: int = 0) -> None:
        """兑现暂存的预览请求（右键菜单在预览器就绪前打开文件时用）。

        面板由 ``QTimer`` 分帧构建，因此「内容已初始化」不等于「预览器已存在」：
        暂存后要按 120ms 步进重试，最多约 3s，仍失败则丢弃并记日志。

        Args:
            attempt: 内部重试计数。
        """
        info = self._pending_preview_file_info
        if info is None:
            return
        if self._previewer is None:
            if attempt < 25:
                QTimer.singleShot(120, lambda: self._flush_pending_preview(attempt + 1))
            else:
                warning(f"预览放弃（预览器始终未就绪）: {info.get('path', '')}")
            return
        self._pending_preview_file_info = None
        debug(
            f"兑现延后预览: {info.get('path', '')} "
            f"previewer={type(self._previewer).__name__} attempt={attempt}"
        )
        self._previewer.set_file(info)
        if self._info_panel is not None:
            self._info_panel.set_file(info)
        else:
            self._pending_info_file_info = info
        getter = getattr(self._previewer, "current_file_info", None)
        try:
            debug(f"兑现后预览器当前文件: {(getter() or {}).get('path', '') if callable(getter) else 'n/a'}")
        except Exception as exc:  # noqa: BLE001 - 仅诊断日志
            debug(f"兑现后读取预览器状态失败: {exc}")

    def _setup_content(self) -> None:
        """设置窗口内容"""
        # 中央部件用纯 QWidget，保留本地无边框基类的原生窗口特性
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

        # 启动恢复：按持久化文件名拼绝对路径加载自定义背景；文件缺失时
        # 组件内部回退纯色并记日志，不抛异常（见 CustomImageBackgroundWidget.set_image）
        if self._background_image_name:
            background_image_path = str(
                backgrounds_dir() / self._background_image_name
            )
            self._custom_background.set_image(background_image_path)
        # 启动恢复图像可调参数（模糊度/透明度，无图时仅存状态不绘制）
        try:
            self._custom_background.set_blur_radius(self._background_blur)
        except Exception as exc:
            debug(f"启动恢复背景模糊度失败：{exc}")
        try:
            self._custom_background.set_opacity(
                1.0 - self._background_transparency / 100.0
            )
        except Exception as exc:
            debug(f"启动恢复背景透明度失败：{exc}")

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

        # 主布局装配（classic / workspace 两种组装；workspace = 预览优先新布局）。
        # 4 个区域先放「加载中…」占位，窗口显示后再分阶段构建重型叶子组件
        # （首屏提速，见 _build_panels_deferred）。
        from layout.main_layout import MainLayout

        self._main_layout = MainLayout(self._layout_mode)
        self._zones = self._main_layout.zones
        self._zone_placeholders = {}
        for key, zone in self._zones.items():
            placeholder = self._make_panel_placeholder()
            zone.layout().addWidget(placeholder)
            self._zone_placeholders[key] = placeholder

        # 窗口显示后再分阶段构建各区域重型布局
        QTimer.singleShot(0, self._build_panels_deferred)

        # 外层容器提供四周 10px 边距（持有引用：启动加载覆盖层挂载在它上面）
        self._splitter_container = QWidget()
        register_widget_qss(self._splitter_container,("background-color: transparent;"))
        container_layout = QHBoxLayout(self._splitter_container)
        container_layout.setContentsMargins(10, 0, 10, 10)
        container_layout.setSpacing(0)
        container_layout.addWidget(self._main_layout)
        main_layout.addWidget(self._splitter_container, stretch=1)

        # 启动加载覆盖层：实色底铺满整个客户区（含自绘标题栏背后的区域，
        # 标题栏文字/按钮仍在其上），只显示一个旋转圆环；三栏真实布局就绪后
        # 淡出（见 _dismiss_startup_overlay）。
        self._setup_startup_overlay()

        # 连接主题切换信号（生效值变化刷新顶栏图标/面板）
        tm.theme_changed.connect(self._on_theme_changed)
        tm.colors_updated.connect(self._on_colors_updated)

        # 跟随系统：启动系统主题轮询监听，系统变化时自动跟随切换。
        self._start_system_theme_watcher()

    # ──── 分阶段延迟构建三栏（首屏提速） ─────────────────────────────────

    def _setup_startup_overlay(self) -> None:
        """创建启动加载覆盖层（铺满整个客户区、只显示旋转圆环）与撤销定时器。

        覆盖层挂在 ``_content``（=整个客户区）而非 ``_splitter_container``：这样
        不透明遮罩底色才能覆盖到自绘标题栏所在的区域，否则标题栏会透出云母/壁纸
        等背景层，与下方实色内容区形成一条断色带。挂载时 ``stackUnder`` 标题栏
        （见 :meth:`_mount_startup_overlay`），标题栏文字/按钮仍留在遮罩之上，
        保持可见可交互（可拖动/最小化/关闭），只有标题栏以下的区域被实色盖住。
        三栏真实布局全部就绪后由 :meth:`_dismiss_startup_overlay` 淡出；构建异常
        时的兜底见 ``STARTUP_OVERLAY_MAX_MS``。创建失败不影响启动（回退到
        「加载中…」占位）。

        必须在 ``_setup_content`` 内同步完成：此时早于 ``main.py`` 的
        ``window.show()``，覆盖层才能出现在首帧。
        """
        # 单发定时器兼顾两个角色：展示期是「最长存活兜底」，三栏就绪后被改写为
        # 「补齐最短展示时长」，超时槽同为淡出。parent=self → 窗口销毁即随之失效。
        self._startup_overlay_timer = QTimer(self)
        self._startup_overlay_timer.setSingleShot(True)
        self._startup_overlay_timer.timeout.connect(self._fade_out_startup_overlay)
        try:
            self._startup_overlay = StyledLoading(
                size="lg",
                overlay=True,
                backdrop="opaque",
                parent=self._content,
            )
            self._mount_startup_overlay()
            self._startup_overlay_started_at = time.perf_counter()
        except Exception as exc:  # 覆盖层失败不影响启动
            warning(f"启动加载覆盖层创建失败（回退占位标签）: {exc}")
            self._startup_overlay = None

    def _mount_startup_overlay(self) -> None:
        """把启动加载覆盖层铺满 ``_content`` 并垫在自绘标题栏之下。

        ``fit_to_parent`` 会 ``raise_`` 覆盖层。要使最终 z 序为「标题栏 → 覆盖层
        → 内容区」，必须先 ``header.raise_()`` 把标题栏提到最上层，再
        ``overlay.stackUnder(header)``——``stackUnder`` 只把覆盖层放到标题栏
        **正下方**，若标题栏本身还在栈底（标题栏先于内容容器创建），覆盖层会被
        一并压到内容容器之下、反而盖不住。幂等，可重复调用（内容层重建后会再挂一次）。
        """
        overlay = self._startup_overlay
        if overlay is None:
            return
        overlay.fit_to_parent()
        header = getattr(self, "_title_bar_header", None)
        if header is not None:
            header.raise_()
            overlay.stackUnder(header)

    def _dismiss_startup_overlay(self) -> None:
        """三栏就绪后撤下启动加载覆盖层（不足最短展示时长则补齐后再淡出）。

        幂等：三栏就绪与兜底超时可能先后到达，只有第一次生效。
        """
        if self._startup_overlay is None:
            return
        elapsed_ms = (time.perf_counter() - self._startup_overlay_started_at) * 1000.0
        remain_ms = int(max(0.0, self.STARTUP_OVERLAY_MIN_MS - elapsed_ms))
        if remain_ms <= 0:
            self._fade_out_startup_overlay()
            return
        if self._startup_overlay_timer is not None:
            self._startup_overlay_timer.start(remain_ms)

    def _fade_out_startup_overlay(self) -> None:
        """启动加载覆盖层淡出并销毁（幂等）。"""
        overlay = self._startup_overlay
        if overlay is None:
            return
        self._startup_overlay = None
        if self._startup_overlay_timer is not None:
            self._startup_overlay_timer.stop()

        # 子控件淡出走 QGraphicsOpacityEffect + QPropertyAnimation（windowOpacity
        # 只对顶层窗口生效）；缓动沿用全项目统一的 InOutCubic，禁用弹簧效果。
        effect = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", overlay)
        animation.setDuration(self.STARTUP_OVERLAY_FADE_MS)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        animation.finished.connect(overlay.hide)
        animation.finished.connect(overlay.deleteLater)
        # 收尾链（Mica / 浮窗 / 设置预热）必须等遮罩**真正淡出完**再启动：
        # 遮罩仍在屏上时跑 numpy 导入与烘焙提交，会直接冻结转圈的加载动画。
        animation.finished.connect(self._start_post_startup_chain)
        self._startup_overlay_animation = animation  # 持引用防止提前回收
        animation.start()

    def _start_post_startup_chain(self) -> None:
        """遮罩淡出完成后启动收尾链（幂等）。

        与 ``_run_post_startup_chain`` 分离的原因：本方法挂在淡出动画的
        ``finished`` 上，只在该动画真正结束时触发一次；而 ``_dismiss_startup_overlay``
        可能因为「最短展示时长」把淡出推迟到几百毫秒之后，那时若已提前起跑
        收尾链，就会和还在转圈的加载动画抢主线程。
        """
        if getattr(self, "_post_startup_chain_started", False):
            return
        self._post_startup_chain_started = True
        self._run_post_startup_chain()

    def _make_panel_placeholder(self) -> QLabel:
        """生成面板加载占位标签（'加载中…'），真实布局构建后移除。"""
        label = QLabel("加载中…", self)
        label.setAlignment(Qt.AlignCenter)
        register_widget_qss(label,(
            f"color: {tm.text.name()}; background-color: transparent; font-size: 13px;"
        ))
        return label

    #: 面板构建之间的强制让出间隔（ms）。面板构建是同步的，若四个都预排到
    #: 同一轮事件循环（原来的 0/8/16/24ms 网格），加载圈一次绘制机会都拿不到，
    #: 视觉上就是「圈停住 300ms」。改为链式：建完一个再排下一个，间隔 24ms
    #: 保证加载圈至少能画一帧。
    PANEL_BUILD_GAP_MS = 24

    def _build_panels_deferred(self) -> None:
        """窗口显示后分阶段构建各区域重型布局，避免启动白屏/长阻塞。

        文件选择器（最重）优先构建并显示，预览区、储存池、信息面板随后补齐；
        全部就绪后连接跨栏信号、刷新样式并应用默认比例（16:9 / 半高上限）。

        构建**链式串行**：每次只排下一个面板，且间隔 ``PANEL_BUILD_GAP_MS``，
        让加载圈在两次构建之间真正获得绘制机会（预排四个定时器会让它们在同
        一轮事件循环里连续执行，形成一次 300ms 级的可见卡顿）。
        """
        self._build_panel_chain(["selector", "preview", "pool", "info"], 0)
        # 兜底：四区齐备时由 _build_panel 立即收尾（见 _dispatch_panels_ready_if_complete）；
        # 这个定时器只应对“某个面板构建失败、链提前断掉”的异常路径。
        QTimer.singleShot(300, self._finalize_panels)

    def _build_panel_chain(self, sides: list, index: int) -> None:
        """按序构建面板：建完一个再排下一个，保证中间让出绘制。

        Args:
            sides: 待构建区域键序列。
            index: 当前序号。
        """
        if index >= len(sides):
            return
        self._build_panel(sides[index])
        if index + 1 < len(sides):
            QTimer.singleShot(
                self.PANEL_BUILD_GAP_MS,
                lambda: self._build_panel_chain(sides, index + 1),
            )

    def _replace_zone_placeholder(self, key: str, widget: QWidget) -> None:
        """移除指定区域的加载占位，并放入真实组件。"""
        zone = self._zones.get(key)
        if zone is None:
            return
        placeholder = self._zone_placeholders.get(key)
        if placeholder is not None:
            zone.layout().removeWidget(placeholder)
            placeholder.deleteLater()
            self._zone_placeholders[key] = None
        zone.layout().addWidget(widget)

    def _build_panel(self, side: str) -> None:
        """构建指定区域（selector/preview/pool/info）的真实布局，替换占位标签。

        单区域失败不应拖垮整体启动。布局模块在此处局部导入：本方法总在窗口
        显示后（``_build_panels_deferred``）才被调用，把它们的重型依赖留到
        首帧之后再加载（见模块顶部注释）。

        “四区齐备即收尾”的判断放在本包装层而非实现体末尾：``info`` 分支在
        实现体内提前 ``return``，判断若留在实现体末尾，最后一个面板永远不会
        触发收尾，只能等兜底定时器（曾导致加载圈多转约 2 秒）。
        """
        _panel_started = time.perf_counter()
        try:
            self._build_panel_impl(side)
        finally:
            debug(
                f"[启动耗时] 面板构建 {side}: "
                f"{(time.perf_counter() - _panel_started) * 1000:.0f}ms"
            )
        self._dispatch_panels_ready_if_complete()

    def _dispatch_panels_ready_if_complete(self) -> None:
        """四区齐备且尚未派发时，立即安排收尾（幂等）。"""
        if getattr(self, "_panels_ready_dispatched", False):
            return
        if all(
            widget is not None
            for widget in (
                self._file_selector,
                self._file_pool,
                self._previewer,
                self._info_panel,
            )
        ):
            self._panels_ready_dispatched = True
            QTimer.singleShot(0, self._finalize_panels)

    def _build_panel_impl(self, side: str) -> None:
        """``_build_panel`` 的实现体（外层负责耗时统计）。"""
        if side == "info":
            # 信息面板：外面包一层卡片 QFrame（面板自绘且透明，卡片负责
            # 填充/描边/圆角，与统一预览器旧 PreviewerBottom 视觉一致）
            try:
                from layout.preview.file_info_panel import FileInfoPanel

                zone = self._zones.get(side)
                if zone is None:
                    return
                self._info_card = QFrame(zone)
                self._info_card.setObjectName("InfoPanelCard")
                card_layout = QVBoxLayout(self._info_card)
                card_layout.setContentsMargins(0, 0, 0, 0)
                card_layout.setSpacing(0)
                self._info_panel = FileInfoPanel(self._info_card)
                card_layout.addWidget(self._info_panel)
                self._replace_zone_placeholder(side, self._info_card)
            except Exception as exc:  # 单区域构建失败不应拖垮整个启动
                warning(f"面板构建失败（{side}）: {exc}")
                return
            self._refresh_panel_styles(full_refresh=False)
            return

        try:
            zone = self._zones.get(side)
            if zone is None:
                warning(f"未知面板区域: {side!r}")
                return
            if side == "selector":
                from layout.file_selector_layout import FileSelectorLayout

                self._file_selector = FileSelectorLayout(zone)
                # 立即连接 file_selected：首次导航在下方提前派发，右键菜单
                # （--open-path 传文件）的「定位 + 预览」可能在 _finalize_panels
                # 之前就发出信号；那时尚未连接会让请求静默丢失（实测现象：
                # 卡片进入预览态，但预览区与文件信息区都是空白）。
                try:
                    self._file_selector.file_selected.connect(self._on_file_selected)
                    self._selector_file_selected_connected = True
                    # 告知选择器「预览信号已有人接收」：它据此决定是否可以
                    # 立即发出右键菜单的定位+预览，否则会按 200ms 退避重试。
                    self._file_selector.set_preview_sink_ready(True)
                except Exception as exc:  # noqa: BLE001 - 连接失败不阻塞构建
                    warning(f"文件选中信号提前连接失败: {exc}")
                # 网络盘/光驱开关随启动读取结果下发（「All」视图盘符过滤）
                try:
                    self._file_selector.set_include_remote_drives(
                        self._include_remote_drives
                    )
                except Exception as exc:  # noqa: BLE001 - 开关下发失败不阻塞构建
                    warning(f"网络盘/光驱开关下发失败: {exc}")
                # 空白区右键返回开关随启动读取结果下发（默认关闭）
                try:
                    self._file_selector.set_blank_right_click_go_back(
                        self._blank_right_click_go_back
                    )
                except Exception as exc:  # noqa: BLE001 - 开关下发失败不阻塞构建
                    warning(f"空白区右键返回开关下发失败: {exc}")
                # 显示隐藏/系统文件开关随启动读取结果下发（默认关闭）
                try:
                    self._file_selector.set_show_hidden_files(
                        self._show_hidden_files
                    )
                    self._file_selector.set_show_system_files(
                        self._show_system_files
                    )
                except Exception as exc:  # noqa: BLE001 - 开关下发失败不阻塞构建
                    warning(f"显示隐藏/系统文件开关下发失败: {exc}")
                self._replace_zone_placeholder(side, self._file_selector)
                # 提前派发首次导航：扫描在后台跑，不等 showEvent（那要等整窗
                # 布局完成），可与其余三区构建并行，缩短“转圈结束后才出条目”。
                try:
                    self._file_selector.start_initial_navigation()
                except Exception as exc:  # noqa: BLE001 - 提前导航失败不阻塞构建
                    warning(f"首次导航提前派发失败: {exc}")
            elif side == "preview":
                from layout.unified_previewer_layout import UnifiedPreviewerLayout

                self._previewer = UnifiedPreviewerLayout(zone)
                # AI 入口开关随启动读取结果下发（关闭时预览器完全不创建 AI 控件）
                try:
                    self._previewer.set_ai_entry_enabled(self._ai_entry_enabled)
                except Exception as exc:  # noqa: BLE001 - 开关下发失败不阻塞构建
                    warning(f"AI 入口开关下发失败: {exc}")
                # 显示隐藏/系统文件开关随启动读取结果下发（文件夹预览器消费；默认关闭）
                try:
                    self._previewer.set_show_hidden_files(self._show_hidden_files)
                    self._previewer.set_show_system_files(self._show_system_files)
                except Exception as exc:  # noqa: BLE001 - 开关下发失败不阻塞构建
                    warning(f"显示隐藏/系统文件开关下发失败: {exc}")
                # 统一操作按钮承载方式：New 布局走预览器顶栏（经典走底部栏）
                self._previewer.set_actions_mode(self._layout_mode == "workspace")
                # 经典布局：底部操作栏挂到右列槽位（信息面板下方，整列最底部）
                if self._layout_mode == "classic" and self._main_layout is not None:
                    slot = self._main_layout.classic_action_slot()
                    if slot is not None:
                        self._previewer.set_bottom_bar_host(slot)
                self._replace_zone_placeholder(side, self._previewer)
                # 预览器最小尺寸随模式（workspace 内容区 640×360；classic 清除）
                self._apply_previewer_minimums()
            elif side == "pool":
                from layout.file_pool_layout import FilePoolLayout

                self._file_pool = FilePoolLayout(zone)
                # 池子视图随布局模式：New = 网格（竖向卡片），经典 = 列表
                self._file_pool.set_view_mode(
                    "grid" if self._layout_mode == "workspace" else "list"
                )
                self._replace_zone_placeholder(side, self._file_pool)
        except Exception as exc:  # 单区域构建失败不应拖垮整个启动
            warning(f"面板构建失败（{side}）: {exc}")
            return
        # 该区域刚就绪即刷新其边框/填充：即使其它区域尚未构建，也能让已就绪区正确显示。
        # 启动期不做整窗 repolish（加载圈可见，全树 polish 每次 20~50ms）；
        # 整窗兜底刷新统一由 _finalize_panels 收尾时执行一次。
        self._refresh_panel_styles(full_refresh=False)

    def _finalize_panels(self) -> None:
        """全部区域就绪后：连接跨栏信号、刷新样式、应用默认比例。

        预览器较重，120ms 时可能仍未构建完成；故逐区域守卫连接已就绪者，
        并在仍有区域缺失时延后重试，确保跨栏信号最终全部连上（边框/填充已由
        _build_panel 渐进套用，不受此影响）。

        幂等：四区齐备后可能被“提前收尾”与“120ms 网格”各调一次，
        ``_panels_finalized`` 保证最小尺寸/默认比例/覆盖层只结算一次。
        """
        if getattr(self, "_panels_finalized", False):
            return
        # 四区齐备的那一次调用即“结算点”：先把标志立起来，避免“提前收尾”
        # 与“120ms 网格/60ms 重试”重复连信号（Qt 默认允许重复连接）。
        all_ready = all(
            widget is not None
            for widget in (
                self._file_selector,
                self._file_pool,
                self._previewer,
                self._info_panel,
            )
        )
        if all_ready:
            self._panels_finalized = True
        if self._info_panel is not None and self._pending_info_file_info is not None:
            pending_info = self._pending_info_file_info
            self._pending_info_file_info = None
            debug(f"补填信息面板: {pending_info.get('path', '')}")
            self._info_panel.set_file(pending_info)
        if self._previewer is not None:
            # 预览器就绪即兑现启动期暂存的预览请求（右键菜单在构建过程中
            # 打开文件时会走这里），避免等到下一次点击才显示内容。
            self._flush_pending_preview()
        if self._file_selector is not None:
            # 信号连接：文件选择器 → 文件池
            self._file_selector.toggle_pool_requested.connect(self._on_toggle_pool_requested)
            self._file_selector.add_files_to_pool_requested.connect(self._on_add_files_to_pool_requested)
            # 缩略图按路径回填：池内卡片同步刷新（Q 生成后不再显示旧图标）。
            # 必须守卫 _file_pool：本方法可能在池区尚未建成时被调用（WinIdChange
            # 早于 _build_panel 触发），此时直接取 .refresh_thumbnails 会抛
            # AttributeError 并中断后续所有跨栏连接；池区就绪后的下一次
            # _finalize_panels 调用会补上这两条连接。
            if self._file_pool is not None:
                self._file_selector.thumbnails_ready.connect(
                    self._file_pool.refresh_thumbnails
                )
                # 缩略图被清除：池内卡片回落类型图标（Shift+Q 后不再显示旧缩略图）
                self._file_selector.thumbnails_cleared.connect(
                    self._file_pool.refresh_thumbnails
                )
            self._file_selector.remove_files_from_pool_requested.connect(self._on_remove_files_from_pool_requested)
            if not getattr(self, "_selector_file_selected_connected", False):
                self._file_selector.file_selected.connect(self._on_file_selected)
                self._selector_file_selected_connected = True
            self._file_selector.set_preview_sink_ready(True)
            self._file_selector.preview_cancel_requested.connect(self._on_preview_cancelled)
            # Enter 预览文件 → 焦点移交预览器（防重复连接：按实例判等）
            if getattr(self, "_preview_focus_selector", None) is not self._file_selector:
                self._preview_focus_selector = self._file_selector
                self._file_selector.preview_focus_requested.connect(
                    self._on_preview_focus_requested
                )
        if self._file_pool is not None:
            # Enter 预览池内文件 → 焦点移交预览器（防重复连接：按实例判等）
            if getattr(self, "_preview_focus_pool", None) is not self._file_pool:
                self._preview_focus_pool = self._file_pool
                self._file_pool.preview_focus_requested.connect(
                    self._on_preview_focus_requested
                )
            # 信号连接：文件池 → 文件选择器（同步"已在池中"边框标记）
            self._file_pool.pool_changed.connect(self._on_pool_contents_changed)
            # 信号连接：文件池 → 统一预览器（左键点击文件池卡片时预览）
            self._file_pool.item_left_clicked.connect(self._on_pool_item_clicked)
            # 信号连接：文件池再次点击当前预览卡片 → 取消预览
            self._file_pool.preview_cancel_requested.connect(self._on_preview_cancelled)
            # 信号连接：文件池右键点击 → 移除文件池并取消选中
            self._file_pool.item_right_clicked.connect(self._on_pool_item_right_clicked)
            # 空池收走焦点 → 回退到文件选择器并高亮（防重复连接：按实例判等）
            if getattr(self, "_pool_focus_fallback", None) is not self._file_pool:
                self._pool_focus_fallback = self._file_pool
                self._file_pool.focus_exhausted.connect(
                    self._on_leaf_focus_exhausted
                )
        if self._info_panel is not None:
            # 信息面板被清空且焦点原本在面板内 → 回退到文件选择器并高亮
            if getattr(self, "_info_focus_fallback", None) is not self._info_panel:
                self._info_focus_fallback = self._info_panel
                self._info_panel.focus_exhausted.connect(
                    self._on_leaf_focus_exhausted
                )
        if self._previewer is not None:
            # 信号连接：统一预览器底栏 → 定位到所在目录 / 清除预览
            self._previewer.locate_requested.connect(self._on_previewer_locate_requested)
            self._previewer.clear_requested.connect(self._on_preview_cancelled)
            # 信号连接：预览器内层条目选中 → 文件信息面板联动
            #（文件夹预览器选中条目时面板显示该条目信息；取消时恢复）
            self._previewer.entry_selected.connect(self._on_previewer_entry_selected)
            # 信号连接：预览器请求切上/下一个文件（图像 ←→）→ 文件选择器推进
            self._previewer.file_nav_requested.connect(self._on_previewer_file_nav)
            # 根目录 Esc（压缩包/文件夹预览器）→ 焦点交还进入预览器前的焦点区
            self._previewer.set_root_escape_handler(self._on_preview_root_escape)

        # 快捷键处理器接线（全局 / 焦点区 / 媒体委托）。幂等：四区齐备可能
        # 触发两次 finalize（提前收尾 + 兜底定时器），内部有 _shortcuts_wired 守卫。
        self._setup_shortcuts()
        # 储存池布局模式（三栏禁缩放）随构建结果下发一次
        self._apply_pool_layout_mode()

        # 整窗样式兜底只在四区齐备后做一次（启动期逐区构建已跳过整树 polish）。
        self._refresh_panel_styles(full_refresh=all_ready)

        # 文件池就绪且跨栏信号已连接后再触发一次暂存池恢复。原实现在
        # showEvent 里按固定 100ms 延时触发，与 _build_panels_deferred 的
        # 分阶段构建存在时序竞态：FilePoolLayout 构造较重时 _file_pool 仍为
        # None，会让 load_backup() 抛 AttributeError 并中断整条恢复流程。
        if self._file_pool is not None and not getattr(self, "_restore_started", False):
            self._restore_started = True
            # 延后到遮罩淡出之后：备份恢复要读文件 + 建卡片，落在加载圈
            # 可见期会再叠一段阻塞。
            QTimer.singleShot(
                self.STARTUP_OVERLAY_FADE_MS + 400,
                self._check_and_restore_backup,
            )

        # 仍有区域尚未就绪：延后重试连接（样式已由 _build_panel 渐进套用）
        if (
            self._file_selector is None
            or self._file_pool is None
            or self._previewer is None
            or self._info_panel is None
        ):
            QTimer.singleShot(60, self._finalize_panels)
            return
        # 全部就绪：聚合叶子实测下限（底行最小高 / 预览器最小总高）→ 预览器
        # 最小尺寸 → 主窗口最小尺寸，再应用默认比例
        _t0 = time.perf_counter()
        self._apply_leaf_minimums()
        self._apply_previewer_minimums()
        self._apply_window_minimums()
        debug(f"[启动耗时] 最小尺寸聚合: {(time.perf_counter() - _t0) * 1000:.0f}ms")
        QTimer.singleShot(0, self._apply_default_layout)
        # 首次启动补默认焦点：正式启动先显示轻量外壳，窗口激活时四区尚未
        # 构建，ActivationChange 的兜底拿不到文件选择器；若不补一次，启动
        # 完成后 focusWidget() 为空，方向键 / Enter 导航不可用。延后一帧，
        # 等默认比例应用完、列表完成首次布局再落焦点。
        QTimer.singleShot(0, self._focus_selector_on_startup)
        # 兜底：遮罩创建失败 / 被提前移除时淡出动画不会发出 finished，
        # 收尾链（Mica、浮窗、设置预热）就永远不会启动。这里补一个延时兜底，
        # `_start_post_startup_chain` 幂等，正常情况下不会重复执行。
        # **必须在任何可能抛异常的步骤之前挂上**：此前一次改动漏了方法定义，
        # `_preload_mica_chain_during_overlay` 抛 AttributeError 直接跳过了
        # 兜底与撤遮罩，加载圈只能等 8 秒超时，表现为「转圈近 10 秒」。
        QTimer.singleShot(
            self.STARTUP_OVERLAY_MIN_MS + self.STARTUP_OVERLAY_FADE_MS + 100,
            self._start_post_startup_chain,
        )
        # 遮罩仍在屏上时先做 Mica 依赖链的**导入**（主线程约 70~90ms）：
        # 用户此时本来就在看转圈的加载动画，这段成本被自然吸收；烘焙提交与
        # 浮窗/预热仍等淡出动画真正结束（见 _start_post_startup_chain）。
        try:
            self._preload_mica_chain_during_overlay()
        except Exception as exc:  # noqa: BLE001 - 预导入失败不得阻断收尾
            warning(f"Mica 依赖链预调度失败（不阻断启动收尾）: {exc}")
        # 全部真实布局已就绪：撤下启动加载覆盖层。
        # 收尾链（Mica 烘焙 / 浮窗 / 设置预热）由淡出动画的 finished 触发：
        # 遮罩仍在屏上时跑这些同步成本会冻结转圈的加载动画。
        _t0 = time.perf_counter()
        try:
            self._dismiss_startup_overlay()
        except Exception as exc:  # noqa: BLE001 - 撤遮罩失败也要收尾
            warning(f"撤下加载遮罩失败（改由兜底定时器收尾）: {exc}")
        debug(f"[启动耗时] 撤下加载遮罩: {(time.perf_counter() - _t0) * 1000:.0f}ms")

    #: 收尾链内各段相对链起点的间隔（ms）。三段各为 70~500ms 的同步成本，
    #: 必须错开：Mica 最先（决定纯色期长短），浮窗让到揭示动画之后，
    #: 设置预热最长放最后。
    POST_STARTUP_MICA_DELAY_MS = 0
    POST_STARTUP_FLOATING_DELAY_MS = 1800
    POST_STARTUP_PREWARM_DELAY_MS = 2600

    def _run_post_startup_chain(self) -> None:
        """遮罩淡出完成后的串行收尾：Mica 烘焙 → 全局浮窗 → 设置窗口预热。

        顺序与原因：

        1. **Mica 烘焙**最先且不等：它是主窗口**自身**的视觉。遮罩淡出后
           用户看到的是主题 G1 纯色底，云母层烘焙完才会渐显；越早提交烘焙，
           纯色期越短。依赖链导入已在遮罩期完成（见
           ``_preload_mica_chain_during_overlay``），这里只付提交成本。
        2. **全局浮窗**次之，延到 1800ms：它创建时会阻塞 60~70ms，若与
           Mica 层交付/揭示动画重叠，会把渐变打断成「闪一下变过去」。让到
           揭示动画（烘焙交付后 900ms 渐入）结束之后再建。
        3. **设置窗口预热**最后：完整构造约 480ms，是三者中唯一可能被
           用户感知的一次停顿，因此排在最后、且再等 2.6 秒，让用户先拿到
           可操作的主界面。

        三段之间用定时器串行排队而非同步连做：连做会叠加成一次长冻结。
        """
        QTimer.singleShot(
            self.POST_STARTUP_MICA_DELAY_MS,
            self._schedule_mica_startup_refresh,
        )
        QTimer.singleShot(
            self.POST_STARTUP_FLOATING_DELAY_MS,
            self._ensure_floating_pool,
        )
        QTimer.singleShot(
            self.POST_STARTUP_PREWARM_DELAY_MS,
            self._prewarm_settings_window,
        )

    def _preload_mica_chain_during_overlay(self) -> None:
        """加载遮罩仍在屏上时只做 Mica 依赖链导入（不提交烘焙）。

        烘焙耗时实测 700ms 量级（后台线程），越早起跑越好；但主线程侧的
        numpy 导入约 70~90ms，不能落在遮罩淡出之后——那时用户已看到主界面，
        会被感知为一次卡顿。这里把**导入**安排在遮罩仍在转圈的阶段（用户
        本来就在等），烘焙提交仍由遮罩淡出后的收尾链触发。

        幂等：``_start_mica_chain_preload`` 自身带 ``_mica_preload_started``
        守卫；重复调用零成本。
        """
        if self._mica_background is None or self._background_mode != "mica":
            return
        _t0 = time.perf_counter()
        self._start_mica_chain_preload()
        # 真实导入耗时由 _preload_mica_chain 自己的日志给出；这里只记录调度成本。
        debug(
            f"[启动耗时] Mica 依赖链预调度（遮罩期）: "
            f"{(time.perf_counter() - _t0) * 1000:.0f}ms"
        )

    def _schedule_mica_startup_refresh(self) -> None:
        """遮罩淡出后预热 Mica 依赖链并触发首次烘焙（启动期不占加载圈）。"""
        if self._mica_background is None or self._background_mode != "mica":
            return
        _t0 = time.perf_counter()
        self._start_mica_chain_preload()
        debug(
            f"[启动耗时] Mica 依赖链调度: "
            f"{(time.perf_counter() - _t0) * 1000:.0f}ms"
        )
        QTimer.singleShot(0, self._start_mica_refresh)

    def _ensure_floating_pool(self) -> None:
        """按需创建全局存储池浮窗（唯一创建入口；幂等 + 启用门）。

        ``_finalize_panels`` 是重试函数、``set_floating_pool_enabled`` 可被
        反复调用，故首行守卫保证只创建一次；禁用时（设置关闭）直接跳过。
        创建前守卫文件池就绪——浮窗的拖入/拖出信号全部桥接到文件池。

        接线（lambda 槽的连接对象一律存引用，供 teardown 精确断开）：
        ``add_file_requested → file_pool.add_file``、
        ``remove_file_requested → file_pool.remove_file``、
        ``file_pool.pool_changed → 浮窗.set_items(file_pool.items)``。
        随后写 ``_host_window``（拖出落点自窗归属判定依赖）、灌入初始快照
        （防恢复批在途丢失）、应用贴边吸附意图（``set_snap_enabled``，
        与启动读取的 ``_floating_pool_snap_enabled`` 一致），最后 ``show()``
        （启动路径经 helper 也须可见）。
        """
        if self._floating_pool is not None or not self._floating_pool_enabled:
            return
        if self._file_pool is None:
            return
        _t0 = time.perf_counter()
        # 局部导入：浮窗依赖暂存池服务等模块，创建时才加载
        from sopeek.ui.floating_pool_window import FloatingPoolWindow

        floating = FloatingPoolWindow()
        self._floating_pool = floating
        self._floating_pool_conn_add = floating.add_file_requested.connect(
            self._file_pool.add_file
        )
        self._floating_pool_conn_remove = floating.remove_file_requested.connect(
            self._file_pool.remove_file
        )
        self._floating_pool_conn_pool_changed = (
            self._file_pool.pool_changed.connect(
                lambda: floating.set_items(self._file_pool.items)
            )
        )
        # 「本次启动期间隐藏」：只关内存意图，不落盘（下次启动仍按设置加载）
        self._floating_pool_conn_hide = (
            floating.hide_for_session_requested.connect(
                self._on_floating_pool_hide_for_session
            )
        )
        floating._host_window = self
        # 初始快照：建窗时池内可能已有条目（恢复批），立即灌入防丢失
        floating.set_items(self._file_pool.items)
        # 应用贴边吸附意图（窗口侧 API 由 Todo 8 提供；失败不阻断建窗）
        try:
            floating.set_snap_enabled(self._floating_pool_snap_enabled)
        except Exception as exc:  # noqa: BLE001 - 吸附意图下发失败不阻断建窗
            warning(f"浮窗贴边吸附意图应用失败: {exc}")
        floating.show()
        debug(
            f"[启动耗时] 全局浮窗创建: {(time.perf_counter() - _t0) * 1000:.0f}ms"
        )

    def _elevated_drop_accepts_point(self, x: int, y: int) -> bool:
        """提权兜底命中测试：仅文件池区域内的落点接受。

        原生兜底安装后（``RevokeDragDrop`` 撤销顶层 OLE 投放）整个主窗口都会
        收到 ``WM_DROPFILES``，故这里按文件池控件矩形收窄语义，池外丢弃。

        Args:
            x: 主窗口客户区逻辑 X 坐标。
            y: 主窗口客户区逻辑 Y 坐标。

        Returns:
            bool: 落点位于文件池控件矩形内返回 ``True``。
        """
        pool = self._file_pool
        if pool is None:
            return False
        local = pool.mapFrom(self, QPoint(x, y))
        return pool.rect().contains(local)

    def _elevated_drop_accept_paths(self, paths: list[str]) -> None:
        """提权兜底入口：把原生 ``WM_DROPFILES`` 路径注入文件池。

        与 ``FilePoolLayout.dropEvent`` 共用
        :meth:`FilePoolLayout.add_dropped_paths` 的同款过滤语义。

        Args:
            paths: 原生兜底解析出的本地路径列表。
        """
        debug(f"主窗口提权兜底拖入：收到路径数={len(paths)}")
        pool = self._file_pool
        if pool is None:
            return
        pool.add_dropped_paths(paths)

    def _teardown_floating_pool(self) -> None:
        """断开浮窗信号连接、停用定时器、关闭并调度销毁（幂等；``None`` 安全）。

        先经 :meth:`_disconnect_floating_pool` 断开业务 / 主题连接并存 ``set_items``
        防抖定时器，再同步 ``close()`` + ``deleteLater()``（设置页关闭路径不播
        出场动画），最后清空实例引用与连接记账。
        """
        floating = self._floating_pool
        if floating is None:
            return
        self._disconnect_floating_pool()
        # 设置页关闭浮窗（非程序退出）走同步拆卸：需立即 close + deleteLater，
        # 不播出场动画（出场动画只属于程序退出路径，见 closeEvent）。
        try:
            floating.close()
        except RuntimeError:
            pass
        try:
            floating.deleteLater()
        except RuntimeError:
            pass
        self._floating_pool = None

    def _disconnect_floating_pool(self) -> None:
        """断开浮窗的全部业务 / 主题信号连接（幂等；不动窗口本体）。

        四个业务连接（含「本次启动期间隐藏」）与浮窗自身的主题连接
        （``_theme_conn`` 由全局 ``tm`` 持有，不断开会把已弃浮窗经绑定槽
        引用保活）一并断开，并停掉 ``set_items`` 防抖定时器。
        """
        floating = self._floating_pool
        if floating is None:
            return
        for attr in (
            "_floating_pool_conn_add",
            "_floating_pool_conn_remove",
            "_floating_pool_conn_pool_changed",
            "_floating_pool_conn_hide",
        ):
            conn = getattr(self, attr, None)
            if conn is not None:
                # PySide6 的 connect() 返回 QMetaObject.Connection，无实例
                # .disconnect()；经 QObject.disconnect(connection) 断开
                try:
                    QObject.disconnect(conn)
                except (RuntimeError, TypeError):
                    pass
                setattr(self, attr, None)
        theme_conn = getattr(floating, "_theme_conn", None)
        if theme_conn is not None:
            try:
                QObject.disconnect(theme_conn)
            except (RuntimeError, TypeError):
                pass
        colors_conn = getattr(floating, "_colors_conn", None)
        if colors_conn is not None:
            try:
                QObject.disconnect(colors_conn)
            except (RuntimeError, TypeError):
                pass
        timer = getattr(floating, "_debounce_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                pass

    def _on_floating_pool_hide_for_session(self) -> None:
        """浮窗请求「本次启动期间隐藏」：仅停用本会话意图并释放引用。

        **不写入设置**（下次启动仍按用户设置正常加载）。浮窗自身负责播出场
        动画与销毁，故这里不调 ``close()``；只断开信号并关闭内存开关，
        防止本会话任何重建路径（如 ``_finalize_panels`` 重试）把浮窗建回来。
        """
        self._floating_pool_enabled = False
        self._disconnect_floating_pool()
        self._floating_pool = None
        debug("[floating_pool] 用户选择本次启动期间隐藏，已停用本会话重建")

    def _create_title_bar(self, parent_layout: QVBoxLayout) -> None:
        """创建标题栏"""
        # 标题栏容器（完全透明，让 MicaBackgroundWidget 的效果覆盖）
        header = QFrame()
        header.setObjectName("TitleBar")
        header.setFixedHeight(48)
        # 持有引用：启动加载覆盖层按它 stackUnder，把实色遮罩铺到标题栏区域
        # 之下（标题栏文字/按钮仍留在最上层），避免标题栏透出云母/壁纸背景
        # 与下方实色内容区形成断色（见 _mount_startup_overlay）。
        self._title_bar_header = header
        # 完全透明，让下面的 Mica 效果（基底 + 模糊壁纸 + 遮罩）覆盖整个区域
        register_widget_qss(header,("""
            #TitleBar {
                background-color: transparent;
            }
        """))
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 8, 16, 8)
        header_layout.setSpacing(0)

        # 软件图标（位于软件名称左侧）：SPK-main.png 按 DPR 缩放；资源缺失时
        # 跳过图标显示，标题文字保持原有起始位置（见 components.app_logo）。
        logo = app_logo_pixmap(self.TITLE_BAR_LOGO_SIZE)
        if not logo.isNull():
            self._title_icon_label = QLabel()
            self._title_icon_label.setObjectName("TitleBarLogo")
            self._title_icon_label.setFixedSize(
                self.TITLE_BAR_LOGO_SIZE, self.TITLE_BAR_LOGO_SIZE
            )
            self._title_icon_label.setAlignment(Qt.AlignCenter)
            register_widget_qss(
                self._title_icon_label,
                "#TitleBarLogo { background: transparent; border: none; }",
            )
            self._title_icon_label.setPixmap(logo)
            header_layout.addWidget(self._title_icon_label, 0, Qt.AlignVCenter)
            header_layout.addSpacing(self.TITLE_BAR_LOGO_GAP)

        # 标题文字
        self._title_label = QLabel("Sopeek")
        register_widget_qss(self._title_label,(f'font-size: 14px; font-weight: 600; color: {tm.text.name()};'))
        header_layout.addWidget(self._title_label)
        header_layout.addStretch()

        # 设置按钮（SVG图标）
        settings_icon_path = icons_dir() / "setting.svg"
        self._settings_btn = StyledButton(
            "",
            variant="ghost",
            size="sm",
            icon=str(settings_icon_path) if settings_icon_path.exists() else ""
        )
        self._settings_btn.setFixedSize(32, 32)
        register_widget_qss(self._settings_btn,(self._title_bar_button_style()))
        self._settings_btn.clicked.connect(self._open_settings_window)
        header_layout.addWidget(self._settings_btn)

        # 主题切换按钮（SVG图标，dark=深色图标，light=浅色图标）
        light_icon_path = icons_dir() / "title_light.svg"
        self._theme_btn = StyledButton(
            "", variant="ghost", size="sm",
            icon=str(light_icon_path) if light_icon_path.exists() else ""
        )
        self._theme_btn.setFixedSize(32, 32)
        register_widget_qss(self._theme_btn,(self._title_bar_button_style()))
        self._theme_btn.setToolTip("切换主题")
        self._theme_btn.clicked.connect(self._on_theme_toggle)
        header_layout.addWidget(self._theme_btn)

        # 最小化按钮（SVG图标）
        mini_icon_path = icons_dir() / "title_mini.svg"
        self._minimize_btn = StyledButton(
            "", variant="ghost", size="sm",
            icon=str(mini_icon_path) if mini_icon_path.exists() else ""
        )
        self._minimize_btn.setFixedSize(32, 32)
        register_widget_qss(self._minimize_btn,(self._title_bar_button_style()))
        self._minimize_btn.clicked.connect(self.showMinimized)
        header_layout.addWidget(self._minimize_btn)

        # 最大化/还原按钮（SVG图标，max_1=最大化，max_2=还原）
        max_1_path = icons_dir() / "title_max_1.svg"
        self._maximize_btn = StyledButton(
            "", variant="ghost", size="sm",
            icon=str(max_1_path) if max_1_path.exists() else ""
        )
        self._maximize_btn.setFixedSize(32, 32)
        register_widget_qss(self._maximize_btn,(self._title_bar_button_style()))
        self._maximize_btn.clicked.connect(self._toggle_maximize)
        header_layout.addWidget(self._maximize_btn)

        # 关闭按钮（SVG图标）
        close_icon_path = icons_dir() / "title_close.svg"
        self._close_btn = StyledButton(
            "", variant="ghost", size="sm",
            icon=str(close_icon_path) if close_icon_path.exists() else ""
        )
        self._close_btn.setFixedSize(32, 32)
        register_widget_qss(self._close_btn,(self._title_bar_close_style()))
        # 弹窗模态期间仍放行 ✕：否则用户会被弹窗锁住、无法关闭主界面
        # （见 components.modal_guard.MODAL_PASSTHROUGH_PROPERTY）。
        self._close_btn.setProperty(MODAL_PASSTHROUGH_PROPERTY, True)
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
        user32 = _get_user32()
        if user32 is None:
            return
        hwnd = int(self.winId())
        max_1_path = icons_dir() / "title_max_1.svg"
        max_2_path = icons_dir() / "title_max_2.svg"
        if self.isMaximized():
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            # 窗口已还原，显示最大化图标（max_1）
            if max_1_path.exists():
                self._maximize_btn.set_svg_icon(str(max_1_path))
        else:
            user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            # 窗口已最大化，显示还原图标（max_2）
            if max_2_path.exists():
                self._maximize_btn.set_svg_icon(str(max_2_path))

    def _open_settings_window(self) -> None:
        """打开设置窗口（每次新建，关闭即销毁，不缓存窗口实例）。

        设置窗口以主窗口为 parent（Windows owned 窗口），从而：
        - 始终相对主窗口置顶（主窗口激活/点击不会盖住设置窗口）；
        - 主窗口关闭/退出时，设置窗口随宿主一并关闭销毁。
        窗口实例保存在 self._settings_window：若仅用函数局部变量持有，
        PySide6 会在函数返回后因 Python GC 销毁无父窗口的顶层窗口，
        导致设置窗口闪现后立即消失；destroyed 后释放引用以便下次重建。

        显示交给 :meth:`SettingsWindow.present`：透明显示完成首帧后抓取
        最终内容快照，在固定几何的窗口内从 104% 轻微收缩归位，既避免原生
        窗口先露出空白底，也不会在缩放中重排设置页；首次打开还会在启动
        加载层期间预热一次设置窗口。
        """
        # 用户已经主动打开设置：不要再做启动期预热（若尚未开始）。
        self._settings_prewarm_done = True
        win = self._settings_window
        if win is not None:
            # 若正在播放关闭淡出，窗口仍处于 isVisible() 状态；必须先立即
            # 收尾，否则会把正在消失的旧窗口重新聚焦，表现为点击设置无反应。
            finish_close = getattr(win, "finish_close_animation_now", None)
            if callable(finish_close):
                try:
                    finish_close()
                except RuntimeError:
                    pass
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
        window.present()

    def _prewarm_settings_window(self) -> None:
        """启动完成后预建一次设置窗口，摊薄首次点击的样式/布局成本。

        设置窗口每次打开都会新建，首次构造 + 原生 show 需要一次性完成
        Qt 样式 polish / 字体度量 / 原生窗口创建（实测 0.3~0.5s）。这段
        成本无法在点击后拆开，故在启动遮罩撤下、主界面稳定后用**不映射**
        的屏外窗口预热一次；预热结束后销毁，不参与真实设置窗口的生命周期。

        注意：本方法必须晚于启动遮罩淡出调用。同步构造会占满主线程，
        若在加载圈仍可见时执行，会让圆圈明显卡顿。
        """
        if self._settings_prewarm_done or self._settings_window is not None:
            return
        try:
            if not self.isVisible() or QApplication.closingDown():
                return
        except (RuntimeError, AttributeError):
            return
        self._settings_prewarm_done = True
        # offscreen/minimal（测试/无显示器）不预热，避免额外窗口与耗时。
        try:
            if QApplication.platformName().strip().lower() in ("offscreen", "minimal"):
                return
        except Exception:  # noqa: BLE001 - 平台查询失败按不预热处理
            return
        prewarm = None
        prewarm_started = time.perf_counter()
        try:
            prewarm = SettingsWindow(self)
            self._prepare_settings_prewarm_window(prewarm)
            prewarm.destroyed.connect(
                lambda _obj=None: QTimer.singleShot(0, self._prune_qss_registrations)
            )
            prewarm.show()
            # WA_DontShowOnScreen 下 show() 只做布局/样式，不映射像素；
            # 再强制一次原生 HWND 创建，保留建窗预热，但不会闪出窗口边框。
            prewarm.winId()
            debug(
                "设置窗口启动预热完成: "
                f"{(time.perf_counter() - prewarm_started) * 1000:.0f}ms"
            )
        except Exception as exc:  # noqa: BLE001 - 预热失败不能影响启动
            debug(f"设置窗口启动预热失败：{exc}")
        finally:
            if prewarm is not None:
                QTimer.singleShot(60, lambda w=prewarm: self._finish_settings_prewarm(w))

    @staticmethod
    def _prepare_settings_prewarm_window(prewarm: QWidget) -> None:
        """把预热设置窗口配置成透明、屏外且不抢焦点。

        关键回归：``SettingsWindow`` 继承 ``FramelessMainWindow``，窗口标志
        默认带 ``Qt.ExpandedClientAreaHint``。Win11 + Qt 6.10 实测：带该 hint
        的 owned 窗口即使设置了 ``WA_ShowWithoutActivating``，从屏外
        ``show()`` 仍会让整个应用失活（``QApplication.applicationState()``
        变为 ``ApplicationInactive``）。主窗口随后收不到 ``WindowActivate``，
        Mica 的失焦防抖会把背景淡出并暂停，启动画面停在 G1 纯色，直到用户
        点击主窗口才恢复。

        预热只关心样式/布局/字体度量与原生建窗，因此去掉该 hint 即可：仍会
        创建原生 HWND 并完成控件构建预热，只是不进入扩展客户区路径，从而
        不影响主窗口的激活状态。

        Args:
            prewarm: 待 ``show()`` 的预热设置窗口。
        """
        prewarm.setAttribute(Qt.WA_DeleteOnClose, False)
        prewarm.setAttribute(Qt.WA_ShowWithoutActivating, True)
        # 永不映射像素：show() 只做布局/样式/原生建窗预热，避免 DWM 在
        # 屏幕左上角先画一帧 700x500 的窗口边框（预热窗口一闪而过的根因）。
        prewarm.setAttribute(Qt.WA_DontShowOnScreen, True)
        if hasattr(Qt, "ExpandedClientAreaHint"):
            prewarm.setWindowFlags(
                prewarm.windowFlags() & ~Qt.WindowType.ExpandedClientAreaHint
            )
        prewarm.setWindowOpacity(0.0)
        prewarm.move(-10000, -10000)

    def _finish_settings_prewarm(self, window) -> None:
        """销毁启动期预热窗口（透明、屏外，不参与真实设置窗口状态）。"""
        try:
            window._close_pre_cleanup_done = True
            window._skip_close_animation = True
            window._revealed = True
            window.close()
            window.deleteLater()
        except RuntimeError:
            pass

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
        # 窗口子树销毁会清空其 QSS 片段条目：``destroyed`` 在子控件销毁
        # **之前**触发，因此推迟到下一事件循环拍再剪枝（此时子树已真正析构），
        # 使注册表规模回到存活控件数（避免反复开关后表项堆积）。
        QTimer.singleShot(0, self._prune_qss_registrations)

    @staticmethod
    def _prune_qss_registrations() -> None:
        """清掉 QSS 注册表中已销毁控件的片段条目（失败不影响生命周期）。"""
        try:
            from sopeek.ui.theme.app_stylesheet import (
                prune_dead_registrations,
            )

            prune_dead_registrations()
        except Exception as exc:  # noqa: BLE001 - 剪枝失败不影响窗口生命周期
            debug(f"关闭后 QSS 注册表剪枝失败：{exc}")

    def _start_content_theme_transition(
        self, mode: str = "reveal", defer_until_ready: bool = False
    ) -> Optional[ContentTransitionOverlay]:
        """启动内容层过渡：切前抓整窗外观快照，切后按模式揭示/淡出/玻璃扫过。

        Args:
            mode: 过渡模式（字符串，未知值回退 ``"fade"``）：

                - ``"reveal"``（默认，主题链路）：web 式 ``clip-path: circle()``
                  扩散——以主题切换按钮中心为圆心，整幅以旧外观快照打底、
                  自圆心挖出扩张圆洞露出已切好的新主题。半径 0 时即整幅旧
                  外观（点击瞬间不发新主题闪现）；每像素同一时刻只显示
                  「旧」或「新」一个版本，消除交叉淡入的双重曝光叠印
                  （文字发糊的根因）。
                - ``"fade"``：不传扩散圆心，旧外观快照整体渐隐（异常兜底；
                  主题按钮缺失时 ``"reveal"`` 也退化为本模式）。
                - ``"dissolve"``（布局切换链路，见 :meth:`begin_layout_transition`）：
                  整窗旧外观快照 1→0 线性淡出、露出已切好的实时新布局。时长
                  ``ContentTransitionOverlay.DISSOLVE_DURATION_MS``（250ms），
                  缓动 ``QEasingCurve.Linear``。

            defer_until_ready: 是否暂缓遮罩动画起钟直到目标主题外观就绪
                （仅对 reveal/fade 有效；dissolve 始终立即起播）。主题切换
                本身非阻塞——此参数只决定遮罩何时开演，不影响主题翻转时序。

        Returns:
            已创建并启动的遮罩实例；无内容窗口/快照失败时返回 None。

        快照抓取 ``_root``（背景层 + 内容层）而非仅内容子树：面板填充
        多为 5%~72% alpha，内容层单独抓拍几乎全透明，铺到已切换的新内容
        上还原不出旧外观（实测与真实旧外观平均通道差 205/255），揭示对比
        度不成立；含背景的整体快照为不透明、逐像素还原（实测差 0/255）。
        默认 CPU 光栅 Mica 走 ``render()`` 无 GL 依赖；实验性 GL 版 Mica
        （``SPK_USE_GL_MICA=1``）不经 ``render()``，补画其帧缓冲。
        渲染失败时回退为内容层透明底快照（历史行为，观感较弱但可用）。

        快照按 ``devicePixelRatio`` 以物理分辨率渲染（高分屏缩放显示下
        与屏幕 1:1，不糊）；旧实现按逻辑尺寸 1x 抓拍再拉伸到物理像素，
        是文字模糊的另一来源。

        未显示窗口（测试/最小化）无过渡——与 Mica 交叉过渡的 ``isVisible``
        守卫语义一致。
        """
        mode_name = str(mode or "").strip().lower()
        if mode_name not in ("reveal", "fade", "dissolve"):
            mode_name = "fade"
        content = self._content
        if content is None or not content.isVisible():
            return None
        # 单实例去重：上一过渡未结束则立即完成，避免连点叠加多层遮罩
        prev = self._content_theme_overlay
        if prev is not None:
            from shiboken6 import isValid

            if isValid(prev):
                prev.finish_now()
            self._content_theme_overlay = None
        size = content.size()
        if size.isEmpty():
            return None
        snapshot = self._capture_theme_snapshot(size, content.devicePixelRatioF())
        if snapshot is None or snapshot.isNull():
            return None
        # dissolve 始终立即起播（布局切换链路目标是实时新布局、无 QSS 刷新等待）；
        # reveal/fade 走主题链路时按 defer_until_ready 决定是否暂缓起钟。
        defer = defer_until_ready and mode_name != "dissolve"
        if mode_name == "dissolve":
            # 布局切换：整窗快照 250ms 线性溶解，不依赖主题按钮几何
            overlay = ContentTransitionOverlay(
                content,
                snapshot,
                duration_ms=ContentTransitionOverlay.DISSOLVE_DURATION_MS,
                easing=QEasingCurve.Linear,
            )
        elif mode_name == "reveal":
            # 扩散圆心：主题按钮中心（内容层坐标）；按钮缺失/几何无效时
            # 传 None 退化为历史透明度淡出，不影响切换本身。
            origin = self._theme_toggle_origin(content)
            overlay = ContentTransitionOverlay(content, snapshot, origin=origin)
        else:
            # 透明度淡出：整幅平滑渐隐（异常/显式兜底路径）
            overlay = ContentTransitionOverlay(content, snapshot)
        self._content_theme_overlay = overlay
        overlay.start(defer_animation=defer)
        return overlay

    def _capture_theme_snapshot(
        self, size, dpr: float
    ) -> Optional[QPixmap]:
        """抓取切换前的整窗外观快照（遮罩打底位图，物理分辨率）。

        优先渲染 ``_root``（背景层 + 内容层，不透明旧外观）：默认 CPU 光栅
        Mica / 图像 / 简约背景均为普通控件，``render()`` 全量可渲染；GL 版
        Mica（实验路径，``paintGL`` 不经 ``render()``）额外补画其帧缓冲。
        整段失败时回退为内容层透明底快照（历史行为：观感弱但不阻塞切换）。

        Args:
            size: 内容层逻辑尺寸（与 ``_root`` 同尺寸，铺满客户区）。
            dpr: 设备像素比（快照按物理分辨率生成，高分屏不糊）。

        Returns:
            Optional[QPixmap]: 已抓拍快照；整体失败返回 None。
        """
        root = self._root
        target = root if (root is not None and not root.size().isEmpty()) else self._content
        if target is None:
            return None
        snapshot = QPixmap(
            int(round(size.width() * dpr)),
            int(round(size.height() * dpr)),
        )
        if snapshot.isNull():
            return None
        snapshot.setDevicePixelRatio(dpr)
        try:
            # 先铺透明底赋予 alpha 通道（揭示期在快照上 DestinationOut 挖洞
            # 需要；裸 QPixmap 无 alpha 通道时挖洞会得到不透明黑块），
            # 再以目标自身调色板底色（G1）不透明打底——GL 层缺失时该区域
            # 呈主题表面色而非透明/黑块。
            snapshot.fill(Qt.transparent)
            base = target.palette().color(target.backgroundRole())
            snapshot.fill(base)
            painter = QPainter(snapshot)
            try:
                target.render(
                    painter,
                    QPoint(),
                    QRegion(),
                    QWidget.RenderFlag.DrawChildren,
                )
                self._blit_gl_mica_into(painter)
            finally:
                painter.end()
            return snapshot
        except Exception:  # noqa: BLE001 - 整窗抓拍失败回退内容层快照
            pass
        try:
            snapshot.fill(Qt.transparent)
            painter = QPainter(snapshot)
            try:
                self._content.render(
                    painter,
                    QPoint(),
                    QRegion(),
                    QWidget.RenderFlag.DrawChildren,
                )
            finally:
                painter.end()
            return snapshot
        except Exception:  # noqa: BLE001 - 快照失败不阻塞主题切换本身
            return None

    def _arm_theme_ready(self, overlay: ContentTransitionOverlay) -> None:
        """布设「目标外观就绪」观察器：等内容层完成一次真实重绘再放行遮罩起钟。

        与遮罩 ``start(defer_animation=True)`` 配套（见 ``begin_theme_transition``）：

        - 事件过滤器挂在 ``self._content`` 上监听 :class:`QEvent.Paint`：主题翻转
          （``tm.set_theme``）同步刷新 QSS/调色板后，内容层在其后第一次实际
          重绘即视为「目标界面已准备好」，此时才 ``overlay.mark_ready()`` 放行
          圆形遮罩/透明度动画——避免冷启动首击「遮罩先动、新界面后到」的卡顿。
        - 超时兜底：极端情况下若收不到 Paint（内容隐藏/被遮挡等），用
          ``THEME_READY_TIMEOUT_MS`` 定时器强制放行，保证遮罩终会揭幕。

        只持弱观察引用（不过度延长遮罩寿命），并在下一次 ``_arm`` 或
        ``_disarm`` 时替换/拆除上一轮观察器；不在此处调用 ``processEvents``，
        主题翻转仍由调用方同步完成，本方法纯被动观察。每轮 ``_arm`` 会先
        ``_disarm``（递增代际作废旧回调），再取新代际号绑定本轮的过滤器/定时器。

        Args:
            overlay: 已以 ``defer_animation=True`` 启动的内容层遮罩。
        """
        self._disarm_theme_ready()
        seq = self._theme_ready_seq
        content = self._content
        if content is None:
            overlay.mark_ready()
            return

        class _ThemeReadyFilter(QObject):
            """监听目标控件绘制事件的临时过滤器（无状态，回调转交主窗口）。"""

            def __init__(self, owner: "MainWindow", target_seq: int) -> None:
                super().__init__(owner)
                self._owner = owner
                self._seq = target_seq

            def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt 命名
                if event.type() == QEvent.Paint and watched is self._owner._content:
                    self._owner._on_theme_ready(self._seq)
                return False

        filter_obj = _ThemeReadyFilter(self, seq)
        self._theme_ready_filter = filter_obj
        content.installEventFilter(filter_obj)

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setObjectName("theme_ready_timeout")
        timer.timeout.connect(lambda: self._on_theme_ready(seq))
        self._theme_ready_timer = timer
        timer.start(THEME_READY_TIMEOUT_MS)

    def _on_theme_ready(self, seq: int) -> None:
        """就绪回调（Paint 事件或超时触发）：代际有效则放行遮罩起钟并拆观察器。"""
        if seq != self._theme_ready_seq:
            return
        overlay = self._content_theme_overlay
        if overlay is None:
            self._disarm_theme_ready()
            return
        from shiboken6 import isValid

        if not isValid(overlay):
            self._disarm_theme_ready()
            return
        if not overlay.is_finished():
            overlay.mark_ready()
        self._disarm_theme_ready()

    def _disarm_theme_ready(self) -> None:
        """拆除主题就绪观察器（事件过滤器 + 定时器），幂等；递增代际使旧回调失效。"""
        self._theme_ready_seq += 1
        filter_obj = self._theme_ready_filter
        if filter_obj is not None:
            content = self._content
            if content is not None:
                try:
                    content.removeEventFilter(filter_obj)
                except (RuntimeError, TypeError):
                    pass
            try:
                filter_obj.deleteLater()
            except RuntimeError:
                pass
            self._theme_ready_filter = None
        timer = self._theme_ready_timer
        if timer is not None:
            try:
                timer.stop()
                timer.deleteLater()
            except RuntimeError:
                pass
            self._theme_ready_timer = None

    def _blit_gl_mica_into(self, painter: QPainter) -> None:
        """把 GL 版 Mica 背景的帧缓冲补画进快照（CPU 版已由 render 覆盖）。

        ``QOpenGLWidget`` 内容经 ``paintGL`` 绘制、不在 ``QWidget.render()``
        输出内；此处按其几何位置取帧缓冲补画。失败静默跳过（该区域保留
        底色），不影响主题切换。

        Args:
            painter: 目标快照画笔（DIP 与快照 DPR 对齐）。
        """
        widget = getattr(self, "_mica_background", None)
        if widget is None or not isinstance(widget, QOpenGLWidget):
            return
        try:
            if not widget.isVisible():
                return
            image = widget.grabFramebuffer()
            if image.isNull():
                return
            painter.drawImage(QRect(widget.geometry()), image)
        except Exception:  # noqa: BLE001 - GL 读取失败不阻塞切换（留底色）
            pass

    def _theme_toggle_origin(self, content: QWidget) -> Optional[QPoint]:
        """主题按钮中心映射到 *content* 坐标（无效时返回 None 走淡出）。

        Args:
            content: 内容层控件（遮罩父级）。

        Returns:
            Optional[QPoint]: 扩散圆心；按钮未就绪/几何为空时 None。
        """
        btn = self._theme_btn
        if btn is None or content is None:
            return None
        try:
            rect = btn.rect()
            if rect.isEmpty():
                return None
            return btn.mapTo(content, rect.center())
        except Exception:  # noqa: BLE001 - 映射失败退化为淡出
            return None

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

        内容层遮罩以 ``defer_animation=True`` 启动（静态快照立刻铺住旧外观），
        但圆形遮罩/透明度动画起钟交给「目标外观就绪」观察器：待主题翻转同步
        刷新 QSS/调色板、内容层完成一次真实重绘后才 ``mark_ready()`` 放行，
        消除冷启动首击「遮罩先动、新界面后到」的视觉卡顿。主题翻转本身仍是非
        阻塞的——本方法只布设观察器，不等待、不 ``processEvents``。快照失败时
        遮罩未创建、观察器也不布设，切换照常进行。
        """
        overlay: ContentTransitionOverlay | None = None
        try:
            overlay = self._start_content_theme_transition(defer_until_ready=True)
        except Exception:  # noqa: BLE001 - 快照失败不阻塞主题切换本身
            pass
        if overlay is not None:
            self._arm_theme_ready(overlay)
        try:
            self._capture_background_pre_theme_state()
        except Exception:  # noqa: BLE001 - 抓拍失败不阻塞主题切换
            pass

    def begin_layout_transition(self) -> None:
        """布局切换前预抓拍旧外观快照：切换后整窗快照线性溶解完成过渡。

        与 :meth:`begin_theme_transition` 的区别：不传扩散圆心、不依赖主题
        按钮几何，遮罩走「快照溶解」模式——整窗旧外观快照以
        ``ContentTransitionOverlay.DISSOLVE_DURATION_MS``（250ms）+
        ``QEasingCurve.Linear`` 自 1→0 淡出，露出已切好的实时新布局。本
        方法受 ``layout_switch`` 动画设置门控（默认开启）；关闭时整段过渡
        直接跳过（无快照、无遮罩、瞬时切换——真正的布局切换发生在其后的
        设置流程中，不受影响）。快照抓取/isVisible 守卫/单实例去重与主题
        链路共用；未显示窗口（测试/最小化）不建遮罩，快照失败静默跳过、
        不阻塞布局切换本身。
        """
        # 新一轮布局切换：递增代际，作废上一轮过渡未收尾的恢复回调
        self._layout_transition_generation += 1
        # 门控：布局切换动画关闭时跳过过渡（与双击分隔条重置的 layout_reset 同款）
        if not is_animation_enabled("layout_switch", default=True):
            return
        try:
            self._start_content_theme_transition("dissolve")
        except Exception:  # noqa: BLE001 - 快照失败不阻塞布局切换本身
            pass

    # ──── 背景模式过渡（设置页切换窗口背景的 450ms 交叉淡入） ───────────

    def _can_transition_background(self) -> bool:
        """背景过渡前置条件：窗口在屏、未最小化、根容器尺寸有效。

        与内容层主题过渡的 ``isVisible`` 守卫同语义（测试/启动阶段不建
        遮罩）；最小化时动画不可见，直接跳过省一次抓拍与动画。

        Returns:
            bool: 满足全部条件返回 True。
        """
        content = getattr(self, "_content", None)
        root = getattr(self, "_root", None)
        if content is None or root is None:
            return False
        try:
            if not content.isVisible():
                return False
            if self.isMinimized():
                return False
            return not root.rect().isEmpty()
        except Exception:  # noqa: BLE001 - 判定失败按不做过渡处理
            return False

    def _capture_background_frame(self) -> Optional[QPixmap]:
        """抓拍当前可见背景层的帧（背景过渡遮罩的快照来源）。

        按 ``_background_mode`` 取对应层：CPU 云母 / 图像 / 简约层走
        ``QWidget.grab()``；实验性 GL 云母（``SPK_USE_GL_MICA=1``）经
        ``grabFramebuffer()`` 取帧缓冲（``QWidget.render()`` 不含 GL 内容）。
        未显示 / 空帧 / 抓取异常时返回 None，调用方跳过过渡、不阻塞切换。

        Returns:
            Optional[QPixmap]: 当前可见背景层的帧；不可用时 None。
        """
        mode = getattr(self, "_background_mode", "mica")
        if mode == "image":
            layer = getattr(self, "_custom_background", None)
        elif mode == "minimalist":
            layer = getattr(self, "_minimalist_background", None)
        else:
            layer = getattr(self, "_mica_background", None)
        if layer is None:
            return None
        try:
            # 以 isHidden()（未被显式隐藏）判定模式层可用：离屏/未 show 的
            # 窗口 isVisible() 恒 False，但其模式层语义上「在屏」；整窗不可见
            # 的情况已由 _can_transition_background 提前拦截。
            if layer.isHidden():
                return None
            if isinstance(layer, QOpenGLWidget):
                image = layer.grabFramebuffer()
                if image.isNull():
                    return None
                snapshot = QPixmap.fromImage(image)
                if snapshot.isNull():
                    return None
                snapshot.setDevicePixelRatio(float(layer.devicePixelRatioF()))
                return snapshot
            snapshot = layer.grab()
        except Exception as exc:  # noqa: BLE001 - 抓拍失败跳过过渡，不阻塞切换
            debug(f"背景过渡抓拍失败（跳过过渡）：{exc}")
            return None
        if snapshot.isNull():
            return None
        return snapshot

    def _prepare_background_frame(self) -> Optional[QPixmap]:
        """抓拍「当前屏幕背景现状」帧（连切时从现状连续出发）。

        常规场景等价于 :meth:`_capture_background_frame`；若上一背景过渡
        仍在起播/播放中，则把其快照按当前透明度叠加到新层帧之上——得到
        与屏幕逐像素一致的混合态，新过渡从中连续出发（对齐 Mica 材质
        「连切从屏幕现状出发」的语义），避免中途跳变。

        Returns:
            Optional[QPixmap]: 合成后的现状帧；抓拍不可用时 None。
        """
        frame = self._capture_background_frame()
        if frame is None:
            return None
        overlay = getattr(self, "_background_transition_overlay", None)
        if overlay is None:
            return frame
        try:
            from shiboken6 import isValid

            if not isValid(overlay):
                self._background_transition_overlay = None
                return frame
            backdrop = overlay.snapshot_pixmap()
            if backdrop is None or backdrop.isNull():
                return frame
            t = float(overlay.current_opacity())
            if t >= 1.0:
                # 起播瞬间（动画尚未推进）：屏幕此刻完整呈现旧帧。
                return backdrop.copy()
            if t <= 0.0:
                return frame
            canvas = QPixmap(frame.size())
            if canvas.isNull():
                return frame
            canvas.setDevicePixelRatio(frame.devicePixelRatio())
            painter = QPainter(canvas)
            try:
                painter.setOpacity(1.0)
                painter.drawPixmap(0, 0, frame)
                painter.setOpacity(t)
                painter.drawPixmap(0, 0, backdrop)
            finally:
                painter.end()
            return canvas
        except Exception as exc:  # noqa: BLE001 - 合成失败退回裸帧
            debug(f"背景过渡连切合成失败（退回裸帧）：{exc}")
            return frame

    def _start_background_transition(self, snapshot: QPixmap) -> None:
        """启动背景层交叉过渡：旧背景帧 450ms 淡出、新背景层实时在底。

        遮罩压在三背景层之上、内容层之下（``stack_below=_content``）：内容
        保持实时交互，仅背景区域做交叉淡入。单实例去重：上一过渡未结束先
        收尾（连切时已合成屏幕现状，不产生跳变）；创建失败仅告警，不阻塞
        背景切换本身。

        Args:
            snapshot: 切换前背景现状帧（:meth:`_prepare_background_frame` 产物）。
        """
        root = getattr(self, "_root", None)
        content = getattr(self, "_content", None)
        if root is None or content is None or snapshot is None or snapshot.isNull():
            return
        if root.rect().isEmpty():
            return
        self._finish_background_transition()
        try:
            overlay = BackgroundTransitionOverlay(
                root, snapshot, stack_below=content
            )
            self._background_transition_overlay = overlay
            overlay.start()
        except Exception as exc:  # noqa: BLE001 - 遮罩失败不阻塞背景切换
            debug(f"背景过渡遮罩启动失败：{exc}")
            self._background_transition_overlay = None

    def _finish_background_transition(self) -> None:
        """立即收尾进行中的背景过渡遮罩（幂等；连切去重/外部强制收尾用）。"""
        prev = getattr(self, "_background_transition_overlay", None)
        self._background_transition_overlay = None
        if prev is None:
            return
        try:
            from shiboken6 import isValid

            if isValid(prev):
                prev.finish_now()
        except Exception:  # noqa: BLE001 - 已销毁引用按无需收尾处理
            pass

    def _on_theme_toggle(self) -> None:
        """主题切换按钮点击事件（浅色↔深色立即切换，并固定为手动偏好）。

        按钮永远反映当前实际生效值：跟随系统模式下显示系统当前实际
        明暗；点击后翻转生效值，同时把设置页偏好从「跟随系统」自动
        切为对应手动值（「白天」/「夜晚」），保证两处状态同步。
        """
        # 内容+背景过渡预抓拍：切前抓内容层快照与背景旧帧；切后遮罩以整幅
        # 旧外观覆盖、自按钮向外径向揭示新主题，背景层以旧帧为底做 450ms
        # 交叉淡入（见 begin_theme_transition）。
        self.begin_theme_transition()

        # 显式翻转生效值并固定为手动偏好（set_theme 语义即手动化，
        # 跟随模式点击后自动脱离跟随）。
        new_theme = "light" if tm.is_dark_theme() else "dark"
        tm.set_theme(new_theme)
        # 持久化写盘推迟到本拍事件循环末：同步磁盘 IO（读盘合并 + 原子写）
        # 实测 17-20ms，放在点击同步段会推迟扩散动画启动形成卡顿手感。
        self._persist_theme_state(defer_save=True)
        # 按钮图标和 tooltip 在 _on_theme_changed 中更新（按实际生效值）

    def _persist_theme_state(self, defer_save: bool = False) -> None:
        """持久化当前主题偏好与生效值到 SettingsManagerV2（重启后恢复）。

        同时写 ``appearance.theme_mode``（白天/夜晚/跟随系统）与
        ``appearance.theme``（实际生效深浅）及 ``appearance.colors`` 快照。
        失败静默忽略，不阻塞主题切换。

        Args:
            defer_save: True 时仅更新内存设置树，磁盘写入延迟到本拍事件
                循环末（``QTimer.singleShot(0)``），避免磁盘 IO 阻塞
                主题切换点击回调；代际计数保证连点只落一次最新写盘。
        """
        try:
            # 复用应用引导层加载的设置管理器（存在时），避免每次切换
            # 主题都新建实例 + 重新读盘。
            app = QApplication.instance()
            v2 = getattr(app, "settings_manager", None)
            if v2 is None:
                from sopeek.core.managers.settings_manager_v2 import SettingsManagerV2
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
            colors = tm.snapshot_colors()
            saved_accent = v2.get("appearance.accent_color")
            raw_primary = v2.get("appearance.colors.accent.primary")
            auto_accent = (
                isinstance(saved_accent, str) and saved_accent.lower() == "auto"
            ) or (
                isinstance(raw_primary, str) and raw_primary.lower() == "auto"
            )
            if auto_accent and isinstance(colors.get("accent"), dict):
                # 「自动」偏好必须以字面量落盘：本次启动解析出的系统色
                # 只用于运行时，写回配置会让下次启动不再跟随系统强调色。
                # 旧配置可能只在 colors.primary 标记 auto，此处一并归一化。
                colors["accent"]["primary"] = "auto"
                v2.set("appearance.accent_color", "auto")
            v2.set("appearance.colors", colors)
            if not defer_save:
                v2.save()
                return
            self._theme_persist_gen = getattr(self, "_theme_persist_gen", 0) + 1
            gen = self._theme_persist_gen

            def _deferred_save() -> None:
                # 代际守卫：期间又切换过则只落最新一次
                if gen != getattr(self, "_theme_persist_gen", -1):
                    return
                try:
                    v2.save()
                except Exception as exc:  # noqa: BLE001 - 延迟写盘失败仅告警
                    warning(f"主题设置保存失败（重启后可能回退）：{exc}")

            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(0)
            timer.timeout.connect(_deferred_save)
            timer.start()
        except Exception as exc:
            warning(f"主题设置保存失败（重启后可能回退）：{exc}")

    def _schedule_mica_opposite_prebake(self) -> None:
        """主题切换 settled 后空闲预烘对偶主题云母层（mica 模式）。

        真实烘焙与 450ms 过渡错开 2.5s，避免抢 CPU；触发时若条件已变
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
            from sopeek.ui.theme.system_theme import (
                get_system_theme_watcher,
            )

            watcher = get_system_theme_watcher()
            # 幂等重连：PySide6 对「未连接的信号执行 disconnect」会在 C++ 层
            # 打 RuntimeWarning/SystemError（进程退出时 watcher 已被释放），
            # 用 catch_warnings 静默已知无害的断开告警后安全重连。
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    watcher.system_theme_changed.disconnect(
                        self._on_system_theme_changed
                    )
                except (RuntimeError, TypeError, SystemError):
                    pass
            watcher.system_theme_changed.connect(
                self._on_system_theme_changed
            )
            # 挂到主窗口，随窗口销毁自动回收。
            try:
                watcher.setParent(self)
            except Exception as exc:
                debug(f"主题监听器挂父窗口失败（生命周期改由创建者维护）：{exc}")
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
            # 顶层窗口底色同步主题：延迟替换 central widget 时盖住系统默认底色。
            top_palette = self.palette()
            top_palette.setColor(QPalette.Window, QColor(tm.surface))
            self.setPalette(top_palette)
            if hasattr(self, "set_erase_background_color"):
                self.set_erase_background_color(QColor(tm.surface))
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
            light_icon_path = icons_dir() / "title_light.svg"
            dark_icon_path = icons_dir() / "title_dark.svg"
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
                register_widget_qss(self._title_label,(f'font-size: 14px; font-weight: 600; color: {tm.text.name()};'))
            # 刷新所有标题栏按钮的 styleSheet（tm 颜色值已变化）
            register_widget_qss(self._settings_btn,(self._title_bar_button_style()))
            register_widget_qss(self._theme_btn,(self._title_bar_button_style()))
            register_widget_qss(self._minimize_btn,(self._title_bar_button_style()))
            register_widget_qss(self._maximize_btn,(self._title_bar_button_style()))
            register_widget_qss(self._close_btn,(self._title_bar_close_style()))
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

    def _refresh_panel_styles(self, full_refresh: bool = True) -> None:
        """刷新各区域组件的 styleSheet（主题切换 / 延迟构建逐区就绪时调用）。

        逐区守卫：仅对当前已构建的区域套用边框/填充，因此可在尚未全部就绪时
        被 ``_build_panel`` 渐进调用——已就绪区立即正确显示，缺失区留待其构建后
        的调用补齐（无需等全部齐了才一次性刷新）。

        注意：延迟构建时本方法在窗口已显示之后被调用，而对已显示控件设置
        styleSheet 不会自动重绘，必须对各分区控件强制 unpolish/polish 才能让
        边框/填充生效（与主题切换路径一致）。

        Args:
            full_refresh: 是否附带整窗 ``unpolish/polish`` 兜底。启动期逐区
                构建时传 ``False``：此时只有刚建好的那个面板需要套样式，整窗
                重刷会在加载圈可见期间重复付出全树 polish 成本（实测每次
                20~50ms，逐区 5 次即造成明显卡顿）。启动收尾时统一做一次
                整窗刷新即可（见 ``_finalize_panels``）。
        """
        # 语义 token：浅深模式 alpha 一致，仅按主题反转颜色亮度。
        fill_color = tm.qss_color(tm.panel_fill)
        bar_color = tm.qss_color(tm.bar_fill)
        border_color = tm.qss_color(tm.panel_border)

        if self._file_selector is not None:
            # 区域容器保持透明，样式下放给 FileSelectorLayout 内部
            self._file_selector.set_section_styles(
                fill_color, border_color, bar_fill_color=bar_color
            )
        if self._file_pool is not None:
            # 区域容器保持透明，样式下放给 FilePoolLayout 内部
            self._file_pool.set_section_styles(
                fill_color, border_color, bar_fill_color=bar_color
            )
        if self._previewer is not None:
            # 区域容器保持透明，样式下放给 UnifiedPreviewerLayout 内部
            self._previewer.set_section_styles(fill_color, border_color)
        if self._info_card is not None:
            # 信息面板卡片（FileInfoPanel 自绘且透明，卡片负责填充/描边/圆角）
            register_widget_qss(self._info_card,(f"""
                QFrame#InfoPanelCard {{
                    background-color: {fill_color};
                    border: 1px solid {border_color};
                    border-radius: 8px;
                }}
            """))
            self._info_card.style().unpolish(self._info_card)
            self._info_card.style().polish(self._info_card)

        # 整窗级重刷（与主题切换路径一致，作为兜底确保所有已显示控件套用样式）。
        # 启动期逐区构建传 full_refresh=False 跳过：整树 polish 是加载圈卡顿的
        # 主要来源之一，改由 _finalize_panels 收尾时统一做一次。
        if full_refresh:
            self.style().unpolish(self)
            self.style().polish(self)

    def _apply_default_layout(self) -> None:
        """应用当前布局模式的默认比例（窗口完成布局后调用）。

        - workspace：左 1/3、预览画布 16:9（半高上限/底行下限钳制）、底行 50:50；
        - classic：三栏 1:1:1、右栏各半、信息区 ≤ 半高。
        """
        if self._main_layout is not None:
            self._main_layout.apply_default_ratios()

    # ──── 最小尺寸聚合（叶子实测 → 主布局 / 预览器 / 主窗口） ─────────────

    def _apply_leaf_minimums(self) -> None:
        """聚合叶子实测下限并下发主布局（底行最小高 / 预览器最小总高）。

        口径：

        - 底行最小高 = max(储存池一行卡片 + 其底栏, 信息面板最小高)
          （workspace；见 ``FilePoolLayout.minimum_row_height`` /
          ``FileInfoPanel.minimum_content_height``）；
        - 预览器最小总高 = 内容区 360 + 顶栏 48（``WORKSPACE_PREVIEW_MIN_CONTENT_H``
          + ``PREVIEW_CHROME_PX``）。

        仅 workspace 组装消费这两个下限（classic 无底行概念、预览器自然最小），
        但统一按当前叶子实测值下发，切换布局后无需重算。
        """
        if self._main_layout is None:
            return
        from layout.main_layout import (
            PREVIEW_CHROME_PX,
            WORKSPACE_PREVIEW_MIN_CONTENT_H,
        )

        pool_h = 0
        if self._file_pool is not None:
            try:
                pool_h = int(self._file_pool.minimum_row_height())
            except (AttributeError, RuntimeError):
                pool_h = 0
        info_h = 0
        if self._info_panel is not None:
            try:
                info_h = int(self._info_panel.minimum_content_height())
            except (AttributeError, RuntimeError):
                info_h = 0
        self._main_layout.set_leaf_minimums(
            max(pool_h, info_h),
            WORKSPACE_PREVIEW_MIN_CONTENT_H + PREVIEW_CHROME_PX,
        )

    def _apply_previewer_minimums(self) -> None:
        """按当前布局模式设置预览器最小尺寸。

        - workspace：内容区（画布）最小 640×360（16:9，含底行情况 1 平分
          恒成立），预览器最小尺寸 = 640 × (360 + 顶栏 48)；
        - classic：清除显式下限（恢复自然最小），使信息面板高度范围可以
          完整覆盖（预览区高度范围由信息面板高度范围反推）。
        """
        if self._previewer is None:
            return
        from layout.main_layout import (
            PREVIEW_CHROME_PX,
            WORKSPACE_PREVIEW_MIN_CONTENT_H,
            WORKSPACE_PREVIEW_MIN_CONTENT_W,
        )

        try:
            if self._layout_mode == "workspace":
                self._previewer.setMinimumSize(
                    WORKSPACE_PREVIEW_MIN_CONTENT_W,
                    WORKSPACE_PREVIEW_MIN_CONTENT_H + PREVIEW_CHROME_PX,
                )
            else:
                self._previewer.setMinimumSize(0, 0)
        except RuntimeError:  # 控件已销毁（极端时序）：忽略
            pass

    def _apply_window_minimums(self) -> None:
        """按当前布局模式刷新主窗口最小尺寸（各区域最小尺寸的聚合 + 窗口装饰）。

        布局最小尺寸口径（不含标题栏 / 容器边距）：

        - workspace：宽 = 选择器最小宽 + 分隔条 + max(预览器最小宽 640,
          底行最小宽〔储存 + 分隔条 + 信息〕)；高 = 预览器最小总高（360 + 48）
          + 分隔条 + 底行最小高〔max(储存池一行 + 底栏, 信息面板最小高)〕；
        - classic：宽 = 选择器 + 分隔条 + 储存池 + 分隔条 + 右列最小宽
          〔max(预览器自然最小, 信息面板最小宽, 底栏最小宽)〕；高 = 右区最小高
          〔max(2×信息面板最小高 + 分隔条, 预览器自然最小高 + 分隔条 + 信息最小高)〕
          + 分隔条 + 底部操作栏槽位。

        叶子尚未就绪时不施加（保持窗口自然尺寸）；就绪后由 ``_finalize_panels``
        或 ``set_layout_mode`` 重新调用。窗口小于此尺寸时布局会被压到不可用，
        故主窗口最小尺寸按上述聚合 + 自绘标题栏 / 容器边距换算。
        """
        if self._main_layout is None:
            return
        from layout.main_layout import (
            CLASSIC_ACTION_SLOT_PX,
            HANDLE_WIDTH,
            PREVIEW_CHROME_PX,
            WORKSPACE_PREVIEW_MIN_CONTENT_H,
            WORKSPACE_PREVIEW_MIN_CONTENT_W,
        )

        def _min_width(widget) -> int:
            if widget is None:
                return 0
            try:
                return max(
                    int(widget.minimumWidth()), int(widget.minimumSizeHint().width())
                )
            except RuntimeError:
                return 0

        def _min_height(widget) -> int:
            if widget is None:
                return 0
            try:
                return max(
                    int(widget.minimumHeight()), int(widget.minimumSizeHint().height())
                )
            except RuntimeError:
                return 0

        selector_w = _min_width(self._file_selector)
        pool_w = _min_width(self._file_pool)
        info_w = _min_width(self._info_panel)
        preview_w = _min_width(self._previewer)
        info_h = _min_height(self._info_panel)
        pool_h = _min_height(self._file_pool)

        if self._layout_mode == "workspace":
            preview_min_w = max(preview_w, WORKSPACE_PREVIEW_MIN_CONTENT_W)
            preview_min_h = WORKSPACE_PREVIEW_MIN_CONTENT_H + PREVIEW_CHROME_PX
            bottom_min_w = pool_w + HANDLE_WIDTH + info_w
            bottom_min_h = max(pool_h, info_h)
            width = selector_w + HANDLE_WIDTH + max(preview_min_w, bottom_min_w)
            height = preview_min_h + HANDLE_WIDTH + bottom_min_h
        else:
            slot = self._main_layout.classic_action_slot()
            right_min_w = max(preview_w, info_w, _min_width(slot))
            width = selector_w + 2 * HANDLE_WIDTH + pool_w + right_min_w
            info_span_h = 2 * info_h + HANDLE_WIDTH if info_h > 0 else 0
            right_area_h = max(
                info_span_h,
                _min_height(self._previewer) + HANDLE_WIDTH + info_h,
            )
            height = right_area_h + HANDLE_WIDTH + CLASSIC_ACTION_SLOT_PX

        # 加上窗口装饰：容器四周边距 + 自绘标题栏高度
        chrome_w = 0
        chrome_h = 0
        container = self._splitter_container
        if container is not None and container.layout() is not None:
            margins = container.layout().contentsMargins()
            chrome_w = margins.left() + margins.right()
            chrome_h = margins.top() + margins.bottom()
        header = getattr(self, "_title_bar_header", None)
        if header is not None:
            chrome_h += max(0, int(header.minimumHeight()))

        self.setMinimumSize(max(0, width + chrome_w), max(0, height + chrome_h))

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

    def _on_toggle_pool_requested(self, file_info: dict) -> None:
        """右键直连：已在池中则移除，否则添加。"""
        file_path = file_info.get("path", "")
        if self._file_pool.has_file(file_path):
            self._file_pool.remove_file(file_path)
        else:
            self._file_pool.add_file(file_info)

    def _on_add_files_to_pool_requested(self, file_infos: list) -> None:
        """文件选择器框选批量入池：逐个添加（已在池中的路径由 add_file 幂等跳过）。"""
        for file_info in file_infos or []:
            if file_info:
                self._file_pool.add_file(file_info)

    def _on_remove_files_from_pool_requested(self, file_infos: list) -> None:
        """文件选择器框选批量移出储存池：逐个移除（不在池/已在移除动画中的路径幂等跳过）。"""
        for file_info in file_infos or []:
            path = str(file_info.get("path") or "") if file_info else ""
            if path:
                self._file_pool.remove_file(path)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Esc：退出储存池重命名编辑态 / 清除框选选中态。

        键盘事件冒泡到主窗口说明当前焦点控件未消费 Esc（全屏预览、弹窗等
        在各自控件内处理并接受事件），因此不会与其 Esc 语义冲突。
        """
        if event.key() == Qt.Key_Escape:
            if self._file_selector is not None:
                self._file_selector.clear_box_selection()
            if self._file_pool is not None:
                if self._file_pool.is_rename_mode():
                    self._file_pool.set_rename_edit_mode(False)
                self._file_pool.clear_box_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_pool_contents_changed(self) -> None:
        """文件池内容变更时，同步路径集合到文件选择器 delegate（边框标记）。"""
        pool_paths = self._file_pool.get_pool_paths()
        self._file_selector.sync_pool_status(pool_paths)

    def _show_preview(self, file_info: dict) -> None:
        """统一预览入口：同步驱动预览器与文件信息面板（任一缺失时守卫跳过）。

        内容尚未构建（``_previewer is None``）时不能直接丢弃：右键菜单可能在
        启动早期就把文件交进来，此时选择器已能定位但预览器还没创建。请求先
        暂存，由 ``initialize_deferred_content`` 末尾兑现。
        """
        if self._previewer is None:
            self._pending_preview_file_info = file_info
            debug(f"预览延后（预览器未就绪）: {file_info.get('path', '')}")
            # 内容已构建完成后预览器仍可能缺失（面板由定时器/分帧构建），此时
            # initialize_deferred_content 的末尾兑现已经跑过，必须自己排一次重试，
            # 否则请求永远躺在暂存里（实测：卡片进入预览态但预览区空白）。
            if getattr(self, "_deferred_content_ready", False):
                QTimer.singleShot(120, lambda: self._flush_pending_preview())
            return
        self._pending_preview_file_info = None
        debug(
            f"应用预览: {file_info.get('path', '')} previewer={type(self._previewer).__name__} "
            f"info_panel={'yes' if self._info_panel is not None else 'no'}"
        )
        if self._previewer is not None:
            self._previewer.set_file(file_info)
        if self._info_panel is not None:
            self._info_panel.set_file(file_info)
        else:
            # 信息面板后建：先记账，面板就绪时由 _finalize_panels 补填。
            self._pending_info_file_info = file_info

    def _on_file_selected(self, file_info: dict) -> None:
        """处理文件选择器的文件选中事件，同步预览态到文件池与自身卡片。

        必须容忍「面板尚未构建完」的早期选中：右键菜单的定位+预览可能在
        ``_finalize_panels`` 之前就发出 ``file_selected``，此时文件池 / 预览器
        仍是 ``None``；直接调用会抛 ``AttributeError`` 并中断整个处理链，表现
        为「卡片进入预览态但预览区与信息区空白」（实测）。
        """
        file_path = file_info.get("path", "")
        debug(f"选中文件: {file_path} previewer={type(self._previewer).__name__ if self._previewer else 'None'}")
        if self._file_selector is not None:
            self._file_selector.set_previewing_file(file_path)
        if self._file_pool is not None:
            self._file_pool.set_previewing_file(file_path)
        getter = getattr(self._previewer, "current_file_info", None) if self._previewer is not None else None
        if callable(getter):
            try:
                current = getter()
            except Exception:  # noqa: BLE001 - 预览器状态读取失败时按"无当前文件"处理，继续刷新预览
                current = None
            if isinstance(current, dict):
                cur = current.get("path", "")
                if cur and os.path.normcase(os.path.normpath(cur)) == os.path.normcase(os.path.normpath(file_info.get("path", ""))):
                    debug(f"选中文件跳过预览（已是当前文件）: {cur}")
                    return
        self._show_preview(file_info)

    def _on_preview_focus_requested(self) -> None:
        """选择器 / 储存池 Enter 预览后，把键盘焦点移交给预览器。

        必须延后一帧：文件类型切换时预览器控件在 ``set_file`` 里刚被创建，
        此时尚未完成布局，同步 ``setFocus()`` 会因不可见而失效（实测焦点
        留在原列表）。延后一帧后由 ``_focus_zone`` 统一做真实焦点校验与
        预览区焦点描边；预览器不可聚焦时静默保持原焦点。
        """
        from sopeek.core.shortcuts import defer_call

        defer_call(lambda: self._focus_zone("preview"))

    def _on_pool_item_clicked(self, file_info: dict) -> None:
        """处理文件池卡片的左键点击事件，预览该文件"""
        file_path = file_info.get("path", "")
        self._file_selector.set_previewing_file(file_path)
        self._file_pool.set_previewing_file(file_path)
        self._show_preview(file_info)

    def _on_preview_cancelled(self) -> None:
        """处理预览取消事件：清除卡片预览态并清空预览器与信息面板"""
        self._file_selector.clear_previewing_state()
        self._file_pool.clear_previewing_state()
        if self._previewer is not None:
            self._previewer.clear_preview()
        if self._info_panel is not None:
            self._info_panel.clear()
        self._release_preview_shortcut_region()
        self._restore_selector_focus_after_cancel()

    def _release_preview_shortcut_region(self) -> None:
        """取消预览后把快捷键区域从 ``preview.*`` 收回选择器（幂等）。

        为什么不能只依赖焦点转移：区域由 ``QApplication.focusChanged`` 驱动，
        而取消预览会销毁内层预览器（其 handler 已注销）。若焦点因平台差异
        没有真正改变（Qt 仍认为焦点在预览器外壳 / 顶层窗口重分配延迟），
        ``focusChanged`` 不发射，``region()`` 就**陈旧地停留在 ``preview.*``**。
        此时方向键按预览区查表，找不到任何 handler，也不会回落到 selector，
        表现为「取消预览后按方向键完全没反应」。

        因此在取消预览时无条件把区域收回 ``selector``：预览已不存在，任何
        预览区语义都已失效，方向键理应操作左侧文件卡片。
        """
        shortcuts = getattr(self, "_shortcuts", None)
        if shortcuts is None:
            return
        try:
            region = str(shortcuts.region())
            if region.startswith("preview.") or region == "fullscreen":
                shortcuts.replace_region("selector")
        except RuntimeError:
            pass

    def _restore_selector_focus_after_cancel(self) -> None:
        """取消预览后把焦点兜底回文件列表（幂等，控件缺失时静默）。

        取消预览的常见触发点是预览器顶/底栏的「清除预览」按钮——这些按钮
        是 ``NoFocus`` 控件，预览器随即被销毁，Qt 会按 Tab 顺序把焦点交给
        主窗口第一个可聚焦控件，也就是选择器的路径框。焦点一旦落在路径框，
        方向键会被输入框吃掉（``selector.nav_*`` 根本不派发），用户就会看到
        「取消预览后按方向键没反应」。

        因此这里在焦点「不在任何既有面板」时兜底到文件列表；已经落在
        储存池（仍有卡片）/ 选择器内的焦点保持不变（例如再次点击储存池卡片
        取消预览，不应把焦点从池里抢走）。信息面板会随取消预览一并清空，
        空面板不是焦点区：它通过 ``focus_exhausted`` 先行回退到文件选择器
        并高亮，不会把焦点留在空信息区。

        预览器控件走 ``deleteLater()``：真正销毁发生在下一轮事件循环，销毁
        时 Qt 仍可能把焦点塞回预览区或路径框（顶层窗口销毁后的焦点重分配）。
        故在当拍兜底一次后，再于下一轮事件循环复查一次（同样幂等）。
        """
        if not self._move_focus_out_of_dead_preview():
            return
        try:
            QTimer.singleShot(0, self._move_focus_out_of_dead_preview)
        except RuntimeError:
            pass

    def _on_leaf_focus_exhausted(self) -> None:
        """空池 / 空信息面板收走焦点后，回退到文件选择器并高亮。

        信号只在「焦点原本在该叶子内、且叶子已经变空」时发出。弹层/关闭
        过程中不抢焦点：此时焦点的归属由弹层或窗口关闭链负责。
        """
        try:
            if QApplication.activePopupWidget() is not None:
                return
        except RuntimeError:
            return
        if getattr(self, "_close_in_progress", False):
            return
        self._focus_selector_with_flash()

    def _move_focus_out_of_dead_preview(self) -> bool:
        """焦点不在既有面板时把它交给文件列表，并高亮回退目标。

        预览器销毁后焦点可能被 Qt 甩到路径框或顶层窗口；此时回退到文件
        列表并闪一次选择器描边，让用户看见焦点落点（用户要求：焦点直接
        回退，高亮回退到的焦点范围）。

        Returns:
            bool: 本次确实请求了文件列表聚焦返回 True。
        """
        selector = self._file_selector
        if selector is None:
            return False
        try:
            if QApplication.activePopupWidget() is not None:
                return False
            if getattr(self, "_close_in_progress", False):
                return False
            for zone in ("selector", "pool", "info"):
                if self._zone_has_keyboard_focus(zone):
                    return False
            return self._focus_selector_with_flash()
        except RuntimeError:
            return False

    def _on_previewer_locate_requested(self, file_info: dict) -> None:
        """处理统一预览器底栏"定位到所在目录"请求：导航左侧选择器并高亮文件"""
        if self._file_selector is not None and file_info:
            self._file_selector.locate_file(file_info)

    def _on_previewer_entry_selected(self, entry: object) -> None:
        """处理预览器内层条目选中变化：联动文件信息面板。

        - 选中条目（文件夹预览器内单击文件/文件夹）→ 信息面板显示该条目；
        - 取消选中（None，含点击空白与扫描后清空）→ 恢复当前预览文件的
          信息；当前无预览文件时清空面板；
        - 面板缺失或设置失败时静默降级（不影响预览本身）。
        """
        if self._info_panel is None:
            return
        if isinstance(entry, dict) and entry:
            try:
                self._info_panel.set_file(dict(entry))
            except Exception as exc:  # noqa: BLE001 - 联动失败不影响预览
                warning(f"信息面板联动失败: {exc}")
            return
        # 取消选中：尝试恢复当前预览文件的信息
        current = None
        if self._previewer is not None:
            getter = getattr(self._previewer, "current_file_info", None)
            if callable(getter):
                try:
                    current = getter()
                except Exception:  # noqa: BLE001 - 获取失败按无预览处理
                    current = None
        try:
            if isinstance(current, dict) and current:
                self._info_panel.set_file(current)
            else:
                self._info_panel.clear()
        except Exception as exc:  # noqa: BLE001 - 联动失败不影响预览
            warning(f"信息面板恢复失败: {exc}")

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
        """窗口显示时安排背景懒加载。

        暂存池恢复不在此按固定延时触发：它与面板分阶段构建存在时序竞态
        （见 :meth:`_finalize_panels`），改由文件池就绪后触发。
        """
        super().showEvent(event)

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
            # 依赖链预导入此刻才安排：窗口已经显示，导入排到首帧事件之后
            # （主线程延迟执行，见 _start_mica_chain_preload），随后的刷新
            # 请求若早于链就绪则记账等待。
            self._start_mica_chain_preload()
            QTimer.singleShot(0, self._start_mica_refresh)

        # 启动加载覆盖层：显示时同步一次几何（构造期布局尚未跑过，容器尺寸还是
        # 默认值），并启动最长存活兜底（三栏构建异常时遮罩仍会撤下）
        if self._startup_overlay is not None:
            self._mount_startup_overlay()
            if self._startup_overlay_timer is not None:
                self._startup_overlay_timer.start(self.STARTUP_OVERLAY_MAX_MS)

    def _start_mica_chain_preload(self) -> None:
        """安排 Mica 依赖链的预导入（幂等，默认只在窗口显示后调用）。

        历史实现用后台 daemon 线程导入以避免与首帧争 GIL；但实测在
        PySide6 6.10 环境下「后台线程导入 numpy/PySide 链 + 主线程 Qt 事件
        处理」会发生原生竞态：进程 Aborted 或挂死（``test_main_window``
        全文件运行稳定复现，独立脚本亦概率复现；禁用线程/仅导入 numpy 的
        对照实验均指向该线程）。

        现改为**主线程延迟导入**：``QTimer.singleShot(0)`` 排在首帧事件
        之后执行，导入期间短暂阻塞主线程（冻结环境实测约 0.1~0.2s），
        但不再有跨线程导入竞态；材质构造与刷新流程不变。
        """
        if self._mica_preload_started:
            return
        self._mica_preload_started = True
        QTimer.singleShot(0, self._preload_mica_chain)

    def _preload_mica_chain(self) -> None:
        """主线程预导入 Mica 依赖链（numpy 等），随后通知记账方。

        只做导入（不构造 Qt 对象）；与 :meth:`_start_mica_chain_preload`
        的说明一致——原后台线程方案存在跨线程导入竞态，已废弃。
        """
        _t0 = time.perf_counter()
        try:
            import sopeek.ui.mica.material  # noqa: F401 - 仅预热导入
        except Exception as e:  # noqa: BLE001 - 预热失败留主线程兜底导入
            warning(f"云母依赖链预导入失败（回退主线程导入）: {e}")
        finally:
            debug(
                f"[启动耗时] Mica 依赖链预导入: "
                f"{(time.perf_counter() - _t0) * 1000:.0f}ms"
            )
            try:
                self._mica_chain_preloader.ready.emit()
            except RuntimeError:
                pass  # 包装对象已随窗口销毁

    def _on_mica_chain_ready(self) -> None:
        """主线程槽：依赖链就绪，补做启动期挂起的材质创建与烘焙请求。"""
        self._mica_chain_ready = True
        if self._mica_refresh_pending:
            self._start_mica_refresh()

    def _start_mica_refresh(self) -> None:
        """延迟在后台线程执行 Mica 壁纸处理（不阻塞主线程/UI）。"""
        if self._mica_background is None:
            return
        if not self._mica_chain_ready:
            # 依赖链预导入尚未执行：先记账，完成回调里再执行。此处直接同步
            # 导入会占住主线程并推迟首帧绘制（见 _start_mica_chain_preload）。
            # 兼容运行期才切到 mica 模式（此时 showEvent 已错过预导入安排）：
            # 补安排延迟导入，保证记账不会无人兑现。
            self._start_mica_chain_preload()
            self._mica_refresh_pending = True
            return
        self._mica_refresh_pending = False
        mica = self._mica_background._ensure_mica_material()
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
        # 重入保护：收尾阶段会为浮窗出场动画跑一段有界事件循环，期间用户
        # 再次触发关闭不得让清理流程执行第二遍。
        if self._close_in_progress:
            event.accept()
            return
        # 关闭分流：托盘挂起 / 直接退出 / 询问用户。判定放在重入保护之后、
        # 清理之前——「托盘挂起」只隐藏窗口（ignore 事件），绝不执行清理；
        # 应用已在退出（closingDown / 会话保存）或已强制退出时不再询问。
        bypass_prompt = bool(self._force_quit) or QApplication.closingDown()
        if not bypass_prompt:
            is_saving_session = getattr(QApplication, "isSavingSession", None)
            if callable(is_saving_session):
                try:
                    bypass_prompt = bool(is_saving_session())
                except (RuntimeError, TypeError):
                    pass
        if not bypass_prompt:
            action = self._close_action
            if action == "tray":
                if self._enter_tray_mode():
                    event.ignore()
                    return
                warning("系统托盘不可用，关闭窗口改为直接退出")
                self._force_quit = True
            elif action == "quit":
                self._force_quit = True
            else:
                # "ask" 及任何非法值：询问用户
                choice = self._ask_close_choice()
                if choice == "cancel":
                    event.ignore()
                    return
                if choice == "tray":
                    if self._enter_tray_mode():
                        event.ignore()
                        return
                    warning("系统托盘不可用，关闭窗口改为直接退出")
                    self._force_quit = True
                else:
                    self._force_quit = True
        self._close_in_progress = True
        # 真正退出前先销毁托盘图标，避免退出后桌面残留托盘项。
        self._dispose_tray()
        # 先回收所有浮动弹窗（筛选/收藏夹/提示/更新等）：它们是独立顶层
        # 窗口，若残留会让 quitOnLastWindowClosed 不触发，表现为「主界面关
        # 了、弹窗还浮在桌面上」。
        self._close_floating_dialogs()
        # 卸载快捷键派发器与焦点监听（幂等），避免全局过滤器在窗口销毁后残留
        self._uninstall_shortcut_dispatcher()
        # 连带关闭设置窗口：设置窗口是主窗口的 owned 子窗口，原生层会随宿主
        # 关闭，此处显式 close 使其走 WA_DeleteOnClose 及时销毁并释放引用，
        # 避免隐藏后残留孤儿实例
        self._close_settings_window_now()
        # Mica 释放统一放在 closeEvent 末尾（所有清理完成后，见下方
        # _dispose_mica）：预览器 cleanup / 浮窗退场都会触发局部重绘，提前
        # dispose 会让重绘区域先露出主题 G1 纯色再关窗。
        # 全局浮窗：先于 flush_backup/dispose 关闭。计划契约——closeEvent 只
        # close 不置 None（置 None 仅限 set_floating_pool_enabled(False) 路径），
        # 故推导会持有自身引用的测试（断言 isHidden）不被销毁干扰。
        # 出场动画（整体缩放 + 淡出）此处非阻塞启动，真正等待放在清理末尾。
        if self._floating_pool is not None:
            try:
                self._floating_pool.request_close_with_animation()
            except (RuntimeError, AttributeError):
                try:
                    self._floating_pool.close()
                except RuntimeError:
                    pass
        try:
            if self._file_pool is not None:
                self._file_pool.flush_backup_save_now()
        except Exception as exc:
            warning(f"退出时保存存储池备份失败（下次启动可能丢失列表）：{exc}")
        try:
            if self._previewer is not None:
                self._previewer.cleanup()
        except Exception as exc:
            debug(f"退出时预览器清理失败：{exc}")
        try:
            if self._info_panel is not None:
                self._info_panel.stop()
        except Exception as exc:
            debug(f"退出时信息面板停止失败：{exc}")
        # 关闭更新弹窗/内联更新会话并停止 spk_updater 边车，避免退出后残留子进程。
        try:
            if "sopeek.ui.update_inline" in sys.modules:
                from sopeek.ui.update_inline import reset_inline_update_session

                reset_inline_update_session()
        except Exception as exc:  # noqa: BLE001 - 退出路径不允许更新组件阻断
            debug(f"退出时关闭内联更新会话失败：{exc}")
        try:
            from sopeek.ui.update_entry import reset_update_entry_controller

            reset_update_entry_controller()
        except Exception as exc:  # noqa: BLE001 - 退出路径不允许更新组件阻断
            debug(f"退出时关闭更新弹窗失败：{exc}")
        try:
            from sopeek.services.update_service import UpdateService

            update_service = UpdateService.get_update_service_if_exists()
            if update_service is not None:
                update_service.shutdown(timeout=1.5)
        except Exception as exc:  # noqa: BLE001 - 退出路径不允许更新组件阻断
            debug(f"退出时关闭更新组件失败：{exc}")
        # 局部导入：暂存池服务依赖文件池/缩略图等重型模块，退出路径再加载
        from sopeek.services.staging_pool_service import StagingPoolService

        StagingPoolService().dispose()
        # 浮窗出场动画收尾：清理均已完成，这里做**有界**等待（正常 ~200ms，
        # 硬上限 EXIT_BUDGET_MS=3s）。超时直接放行，绝不因单个浮窗拖累退出。
        if self._floating_pool is not None:
            try:
                self._floating_pool.wait_for_exit_animation()
            except (RuntimeError, AttributeError):
                pass
        # Mica 必须活到所有清理 / 退场动画结束：预览区摘除控件、浮窗淡出等
        # 局部重绘仍要取到有效视口层，否则会在窗口真正关闭前先闪一帧 G1。
        self._dispose_mica()
        super().closeEvent(event)

    def _close_settings_window_now(self) -> None:
        """立即关闭设置窗口（跳过关闭淡出动画，幂等且不抛异常）。

        设置窗口是主窗口的 owned 子窗口，关闭主窗口 / 进入托盘挂起前都要
        显式收尾：先 ``finish_close_animation_now`` 结束视觉过渡，再 ``close``
        使其走 ``WA_DeleteOnClose`` 及时销毁，最后清空引用避免孤儿实例。
        """
        window = self._settings_window
        if window is None:
            return
        try:
            from shiboken6 import isValid

            if isValid(window):
                # 若正在播放关闭淡出，先立即收尾：退出 / 托盘挂起不能被
                # 150ms 的视觉过渡拖住，也避免隐藏窗口残留。
                finish_close = getattr(
                    window, "finish_close_animation_now", None
                )
                if callable(finish_close):
                    finish_close()
                window.close()
        except RuntimeError:
            pass
        finally:
            self._settings_window = None

    @staticmethod
    def _close_floating_dialogs() -> None:
        """关闭所有存活的浮动弹窗（退出/关闭路径专用，幂等且不抛异常）。

        这些弹窗是独立顶层窗口（``Qt.FramelessWindowHint`` / ``Qt.Dialog``），
        不会随主窗口销毁而消失；残留会让 ``quitOnLastWindowClosed`` 判定
        「还有窗口可见」，进程因此不退出。
        """
        try:
            close_active_dialogs()
        except Exception as exc:  # noqa: BLE001 - 关闭路径绝不被弹窗拖累
            debug(f"关闭浮动弹窗失败（可能有窗口残留）：{exc}")
        try:
            get_modal_guard().clear()
        except Exception:  # noqa: BLE001 - 无 QApplication 的极端场景
            pass

    @staticmethod
    def _application_is_active() -> bool:
        """当前应用是否处于前台激活态（不是单个窗口是否 active）。

        设置窗 / 收藏夹 / 筛选 / 菜单 / 工具浮层都是本应用的独立顶层窗口；
        它们获得焦点时主窗口 ``isActiveWindow()`` 为 False，但应用仍在前台，
        主窗口的 Mica 与后台渲染缓存不应被当作“切到后台”处理。

        Returns:
            bool: ``QApplication.applicationState()`` 为 ``ApplicationActive``。
            无 QApplication 或查询失败时保守返回 False（沿用原失焦语义）；
            offscreen / minimal 无窗口系统时按 True 处理，保留离屏渲染语义。
        """
        app = QApplication.instance()
        if app is None:
            return False
        try:
            # offscreen / minimal 无真实窗口系统，applicationState 恒为
            # Inactive；按“活跃”处理以保留离屏渲染 / 截图语义。
            if QApplication.platformName().strip().lower() in ("offscreen", "minimal"):
                return True
            return app.applicationState() == Qt.ApplicationState.ApplicationActive
        except (RuntimeError, AttributeError):
            return False

    def _restore_default_focus_if_needed(self) -> None:
        """主窗口激活且完全没有焦点控件时，把默认焦点落到文件列表。

        Qt 在顶层窗口激活时若 ``focusWidget()`` 为空，会自动聚焦 Tab 顺序
        第一个可聚焦控件；主窗口里该控件是文件选择器的路径框。用户关闭
        设置窗/对话框后路径框会因此「被动获焦」。这里在激活事件内显式指定
        默认落点（文件列表），不改动任何已有焦点。

        仅在无焦点且没有活动弹出窗口时生效；控件未就绪时静默跳过。
        """
        try:
            if getattr(self, "_close_in_progress", False):
                return
            if self.focusWidget() is not None:
                return
            if QApplication.activePopupWidget() is not None:
                return
            selector = self._file_selector
            if selector is None:
                return
            focus_file_list = getattr(selector, "focus_file_list", None)
            if callable(focus_file_list):
                focus_file_list()
        except RuntimeError:
            pass

    def ensure_startup_foreground(self) -> None:
        """启动首帧后把窗口切到 Windows 原生前台（一次性）。

        从终端 / IDE 启动时，启动器通常仍持有 Windows 前台；前台锁会让
        Qt 的 ``activateWindow()`` / ``raise_()`` 只更新 Qt 内部激活状态，
        ``GetForegroundWindow()`` 仍指向启动器。键盘事件按原生前台窗口
        路由，方向键因此进不了本窗口。这里在首帧揭示后补一次原生激活。

        只执行一次，后续用户 Alt+Tab 离开时不会再次抢焦点；关闭中 /
        不可见 / 最小化 / 离屏测试环境 / 已有活动弹层时静默跳过。
        """
        if getattr(self, "_startup_foreground_done", False):
            return
        self._startup_foreground_done = True
        try:
            if getattr(self, "_close_in_progress", False):
                return
            if QApplication.closingDown():
                return
            if not self.isVisible() or self.isMinimized():
                return
            if sys.platform != "win32":
                return
            if QApplication.platformName().strip().lower() in ("offscreen", "minimal"):
                return
            if QApplication.activePopupWidget() is not None:
                return
            hwnd = int(self.winId())
            if not hwnd:
                return
            # 正常双击启动时系统通常已给前台权限，Qt 这一步即成功；从终端 /
            # IDE 启动时会被前台锁拒绝，再由原生兜底重试。
            self.raise_()
            self.activateWindow()
            if is_foreground_window(hwnd):
                debug("[启动] 原生前台已是主窗口")
                return
            if force_foreground_window(hwnd):
                info("[启动] 原生前台激活成功")
            else:
                warning("[启动] 原生前台激活失败：键盘输入可能仍发往前台窗口")
        except (RuntimeError, AttributeError) as exc:
            debug(f"[启动] 原生前台激活异常: {exc!r}")

    def _focus_selector_on_startup(self) -> None:
        """首次完整布局后把默认焦点落到文件选择器（一次性）。

        正式启动先显示轻量外壳，窗口激活时四区尚未构建，``ActivationChange``
        的默认焦点兜底拿不到 ``_file_selector``；若不再补一次，启动完成后
        ``focusWidget()`` 为空，方向键 / Enter 文件导航不可用。

        只纠正「无焦点」与「路径框被动获焦」：用户或其它区域已建立的真实
        焦点不抢。控件未就绪 / 关闭中 / 有活动弹层时静默跳过。
        """
        if getattr(self, "_startup_focus_applied", False):
            return
        self._startup_focus_applied = True
        try:
            if getattr(self, "_close_in_progress", False):
                return
            if QApplication.activePopupWidget() is not None:
                return
            selector = self._file_selector
            if selector is None:
                return
            path_input = getattr(selector, "_path_input", None)
            current = self.focusWidget()
            if current is not None and current is not path_input:
                return
            focus_file_list = getattr(selector, "focus_file_list", None)
            if callable(focus_file_list):
                focus_file_list()
        except RuntimeError:
            pass

    def changeEvent(self, event: QEvent) -> None:
        """窗口状态变化：失活时重置文件选择器的方向键导航状态。

        Alt+Tab 切走时若正处于按住方向键的手势中，选择器的导航游标必须
        复位，避免回到窗口后的一次释放用陈旧游标加载预览（无 wedged 状态）。

        Args:
            event: 触发的窗口事件。
        """
        super().changeEvent(event)
        # 从「无焦点」状态重新激活（典型：设置窗/对话框关闭、Alt+Tab 回窗）
        # 时，Qt 会把焦点自动交给 Tab 顺序第一个可聚焦控件——即路径框。
        # 在激活的当拍先落到文件列表，避免路径框被动获焦，并保证方向键
        # 文件导航立即可用；已有焦点时不做任何改动。
        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            self._restore_default_focus_if_needed()
        if (
            event.type() == QEvent.ActivationChange
            and not self.isActiveWindow()
            and self._file_selector is not None
        ):
            self._file_selector.reset_nav_state()
        # P7.4：应用失焦（非最小化）只停 tick，30s 宽限后才释放纹理——
        # 重建管线约 4ms，立即释放会在快速切窗/截图时闪一帧。
        #
        # 判据必须是「整个应用是否前台」而不是「主窗口是否 active」：
        # 打开设置窗 / 对话框 / 菜单时主窗口会失活，但应用仍在前台，主窗口
        # 仍可见并需要 Mica。若按 isActiveWindow 释放，30s 后主窗口可见区域
        # 会退化成主题 G1（局部重绘处尤其明显），且要等主窗口自己再次激活
        # 才会重建。
        if event.type() == QEvent.ActivationChange:
            try:
                if (
                    self.isActiveWindow()
                    or self.isMinimized()
                    or self._application_is_active()
                ):
                    self._cancel_idle_texture_release()
                    # 宽限期可能已经到期并执行过 suspend（释放了流体 GPU 控件）：
                    # 回到前台必须恢复，否则 `_renderer` 仍是 `gpu` 而
                    # `_gpu_widget` 已被销毁，`paintEvent` 不绘制任何内容，
                    # 音频页只剩一块与四周割裂的残留区域。
                    self._resume_background_renderers()
                else:
                    self._schedule_idle_texture_release()
            except Exception:  # noqa: BLE001 - 调度失败不影响窗口状态
                pass
        # P7.5：最小化时释放可回收缓存（QPixmap / 视频帧 / SVG），
        # 恢复时各控件按需重填；避免后台驻留时白占内存与显存。
        # P7.4：同时挂起流体（释放颜色纹理）与 Mica（释放整桌面层 QPixmap）。
        if event.type() == QEvent.WindowStateChange:
            try:
                if self.isMinimized():
                    from sopeek.core.memory_budget import get_memory_budget

                    get_memory_budget().release_caches()
                    self._suspend_background_renderers()
                else:
                    self._cancel_idle_texture_release()
                    self._resume_background_renderers()
            except Exception:  # noqa: BLE001 - 释放失败不影响窗口状态
                pass

    # ── 显存释放（P7.4）──────────────────────────────────────────────

    def _suspend_background_renderers(self) -> None:
        """挂起流体背景（停 tick + 释放颜色纹理）并释放 Mica 层像素。"""
        try:
            from components.styled_fluid_background import StyledFluidBackground

            StyledFluidBackground.suspend_all()
        except Exception:  # noqa: BLE001 - 可选组件
            pass
        mica = self._mica_material()
        if mica is not None:
            try:
                mica.release_cached_layers()
            except Exception:  # noqa: BLE001 - 释放失败降级为下次重烘焙
                pass

    def _resume_background_renderers(self) -> None:
        """恢复流体背景（重建首帧）；Mica 释放过的视口层在此按需重建。

        P7.4 的应用失活宽限 / 最小化会 ``release_cached_layers()`` 清掉整块
        视口层。回到前台时必须显式 ``ensure_layer()``：仅恢复流体时 Mica 没有
        任何重烘焙入口，绘制端会永久停留在主题 G1 兜底。
        """
        try:
            from components.styled_fluid_background import StyledFluidBackground

            StyledFluidBackground.resume_all()
        except Exception:  # noqa: BLE001 - 可选组件
            pass
        try:
            mica = self._mica_material()
        except Exception as exc:  # noqa: BLE001 - 退出/重建期控件可能已析构
            debug(f"[背景恢复] 获取 Mica 材质失败：{exc}")
            mica = None
        ensure = getattr(mica, "ensure_layer", None)
        if callable(ensure):
            try:
                ensure()
            except Exception as exc:  # noqa: BLE001 - 恢复失败不影响窗口状态
                debug(f"[背景恢复] Mica 层重建失败：{exc}")

    def _mica_material(self):
        """取主窗口 Mica 材质实例（GL/内置两条实现都兼容）。"""
        background = getattr(self, "_mica_background", None)
        if background is None:
            return None
        for attr in ("mica", "_mica", "_material"):
            candidate = getattr(background, attr, None)
            if candidate is not None and hasattr(candidate, "release_cached_layers"):
                return candidate
        if hasattr(background, "release_cached_layers"):
            return background
        return None

    def _schedule_idle_texture_release(self) -> None:
        """应用失焦后 30s 释放纹理（P7.4）；重复调度不叠加。"""
        if getattr(self, "_idle_texture_timer", None) is not None:
            return
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._on_idle_texture_timeout)
        self._idle_texture_timer = timer
        timer.start(30000)

    def _cancel_idle_texture_release(self) -> None:
        """取消待执行的显存释放并清空计时器（P7.4）。"""
        timer = getattr(self, "_idle_texture_timer", None)
        if timer is None:
            return
        self._idle_texture_timer = None
        try:
            timer.stop()
            timer.deleteLater()
        except RuntimeError:
            pass

    def _on_idle_texture_timeout(self) -> None:
        """宽限期到期：仅当应用仍失活且窗口未最小化时释放纹理（P7.4）。

        主窗口失活不等于应用失活：打开设置窗 / 对话框 / 菜单时应用仍在前台，
        主窗口仍可见，必须保留 Mica 视口层（且设置窗共享同一块层，强行释放
        也省不到内存，只会让主窗口可见区域退化成 G1）。
        """
        self._idle_texture_timer = None
        try:
            if self.isMinimized() or self._application_is_active():
                return
        except RuntimeError:
            return
        self._suspend_background_renderers()

    def eventFilter(self, obj: QWidget, event: QEvent) -> bool:
        """事件过滤器 - 标题栏拖拽（快捷键已迁至 ShortcutDispatcher）。

        本过滤器只挂在自绘标题栏 header 上，负责「在标题栏空白区按下左键时
        启动系统窗口拖动」。方向键文件导航已由
        :class:`sopeek.core.shortcuts.dispatcher.ShortcutDispatcher` 的
        区域栈接管，此处不再处理键盘事件。

        Args:
            obj: 事件接收对象。
            event: 待过滤事件。

        Returns:
            bool: True 表示事件已被本过滤器消费。
        """
        # ---- 鼠标 / 标题栏拖拽逻辑 ----
        # 应用级过滤下 obj 可能是非 QWidget（如 QApplication）：负向守卫兜底，
        # 且本方法任何路径都必须显式返回 bool（返回 None 会让 PySide6 对每个
        # 未捕获的全局事件报 RuntimeWarning）。
        if not (isinstance(event, QMouseEvent) and isinstance(obj, QWidget)):
            return False

        # 只处理鼠标按下事件
        if event.type() != QEvent.Type.MouseButtonPress:
            return False

        # 鼠标点击主窗口内任意位置（含按钮/卡片）：把快捷键区域切到点击所在
        # 区域；仅当焦点区实际发生变化时才闪一次描边。必须放在「按钮提前
        # return」之前，否则点按钮时区域不会跟随。
        self._sync_region_from_click(obj, button=event.button())

        # 点击路径框以外区域时释放其焦点：NoFocus 功能按钮不会接管焦点，
        # 若不释放，后续打开/关闭弹窗时 Qt 会把焦点原样还给路径框。
        # 可聚焦目标在鼠标事件到达前已由 Qt 接管焦点，此处只处理 NoFocus
        # 控件/空白区域；释放后把默认落点交给文件列表。
        try:
            if (
                not getattr(self, "_close_in_progress", False)
                and obj.window() is self
            ):
                selector = self._file_selector
                if selector is not None:
                    release = getattr(
                        selector, "release_path_focus_on_outside_click", None
                    )
                    if callable(release) and release(obj):
                        selector.focus_file_list()
        except RuntimeError:
            pass

        # 只处理左键
        if event.button() != Qt.LeftButton:
            return False

        # 检查是否点击在按钮上
        child = obj.childAt(event.position().toPoint())
        if child is not None and isinstance(child, StyledButton):
            return False  # 让按钮正常工作

        # 在标题栏上拖拽移动窗口（只处理本窗口；应用级过滤器也会看到
        # 设置窗口的标题栏，不能让它去拖主窗口）
        if (
            obj.objectName() == "TitleBar"
            and obj.window() is self
            and self.windowHandle()
        ):
            self.windowHandle().startSystemMove()
            return True

        return False

    def _sync_region_from_click(
        self, obj: QWidget, *, button: Qt.MouseButton = Qt.LeftButton
    ) -> None:
        """鼠标点击时把快捷键区域同步到点击所在区域，并按需闪一次描边。

        去重依据是「上一次已经高亮过的区域」，而不是当前的快捷键区域：
        点击可聚焦控件时 Qt 会先发 ``focusChanged``（``_on_shortcut_focus_changed``
        已把区域改到点击处），若与当前区域比较会误判为「没变化」而漏掉高亮。
        同一焦点区内连续点击时区域不变，因此不会重复闪烁；跨区点击或键盘
        切换仍会正常高亮。

        左键点击**空的**预览区 / 储存池 / 信息面板的空白内容面时不切换区域：
        这些空区域不是焦点区，直接回退到文件选择器并高亮选择器（回退目标
        必须与真实焦点一致）。

        Args:
            obj: 鼠标事件目标控件。
            button: 触发的鼠标按键；只有左键执行空区焦点回退。
        """
        shortcuts = getattr(self, "_shortcuts", None)
        if shortcuts is None or not isinstance(obj, QWidget):
            return
        try:
            if obj.window() is not self:
                return
        except RuntimeError:
            return
        is_left_click = button == Qt.LeftButton
        if is_left_click:
            # 鼠标建立了新的焦点语境：下一次键盘切区重新从「先停在选择器」
            # 开始判断（见 _focus_next_zone）。
            self._empty_cycle_selector_stay = False
            clicked_zone = self._click_zone_name(obj)
            if (
                clicked_zone in ("preview", "pool", "info")
                and not self._zone_can_take_focus(clicked_zone)
                and self._is_blank_click_in_zone(obj, clicked_zone)
            ):
                self._focus_selector_with_flash(
                    flash=getattr(self, "_last_flash_zone", "") != "selector"
                )
                return
        region = self._resolve_shortcut_region(obj)
        if region is None or region == "app":
            return
        self._remember_zone_before_preview(region)
        zone_name = {
            "path": "path",
            "selector": "selector",
            "pool": "pool",
            "info": "info",
        }.get(region)
        if zone_name is None and str(region).startswith("preview."):
            zone_name = "preview"
        if region != shortcuts.region():
            shortcuts.replace_region(region)
        if zone_name and zone_name != getattr(self, "_last_flash_zone", ""):
            self._flash_zone_focus(zone_name)

    def _click_zone_name(self, obj: QWidget) -> str:
        """按控件归属解析点击所在焦点区（空区域也返回其区名）。

        与 :meth:`_resolve_shortcut_region` 的区别：后者对空预览区会回退成
        ``selector``，而这里必须先认出「用户点的其实是空预览区」，才能走
        焦点回退与选择器高亮。

        Args:
            obj: 鼠标事件目标控件。

        Returns:
            str: ``path`` / ``selector`` / ``preview`` / ``pool`` / ``info``；
                不属于主界面四个叶子区时返回空串。
        """
        if self._is_descendant_of(obj, self._previewer):
            return "preview"
        if self._is_descendant_of(obj, self._file_pool):
            return "pool"
        if self._is_descendant_of(obj, self._info_panel) or self._is_descendant_of(
            obj, getattr(self, "_info_card", None)
        ):
            return "info"
        if self._is_descendant_of(obj, self._file_selector):
            path_input = getattr(self._file_selector, "_path_input", None)
            return "path" if obj is path_input else "selector"
        return ""

    def _is_blank_click_in_zone(self, obj: QWidget, zone_name: str) -> bool:
        """点击是否落在指定空区域的内容面（而非按钮/输入框等控件）上。

        只有内容面的空白点击才触发“回退到文件选择器”。空池底栏的「导入/
        导出数据」等按钮属于可操作控件，点它们不应把焦点抢走。

        Args:
            obj: 鼠标事件目标控件。
            zone_name: ``preview`` / ``pool`` / ``info``。

        Returns:
            bool: 空白内容面返回 True。
        """
        try:
            if zone_name == "pool":
                pool = self._file_pool
                if pool is None:
                    return False
                return obj in (
                    pool,
                    pool._scroll_area,
                    pool._scroll_area.viewport(),
                    pool._card_container,
                    pool._empty_hint,
                    self._zones.get("pool"),
                )
            if zone_name == "info":
                panel = self._info_panel
                if panel is None:
                    return False
                return obj in (
                    panel,
                    panel._scroll_area,
                    panel._scroll_area.viewport(),
                    panel._canvas,
                    getattr(self, "_info_card", None),
                    self._zones.get("info"),
                )
            if zone_name == "preview":
                previewer = self._previewer
                if previewer is None:
                    return False
                return obj in (
                    previewer,
                    previewer._content_top,
                    previewer._placeholder_label,
                    self._zones.get("preview"),
                )
        except (AttributeError, RuntimeError):
            return False
        return False

    def _zone_can_take_focus(self, name: str) -> bool:
        """指定区域当前是否有可接收键盘焦点的内容。

        “空池 / 空信息面板 / 空预览区”不是焦点区；键盘切区与鼠标点击回退
        都以此为准，不能只看「区域存在」或「控件已构建」。

        Args:
            name: 区名（path/selector/preview/pool/info）。

        Returns:
            bool: 当前可聚焦返回 True。
        """
        try:
            if name == "path":
                selector = self._file_selector
                path_input = getattr(selector, "_path_input", None)
                return path_input is not None and path_input.isVisible()
            if name == "selector":
                file_list = getattr(self._file_selector, "_file_list", None)
                return file_list is not None and file_list.isVisible()
            if name == "preview":
                previewer = self._previewer
                return bool(
                    previewer is not None and previewer.has_active_preview()
                )
            if name == "pool":
                pool = self._file_pool
                return bool(pool is not None and pool.has_items())
            if name == "info":
                panel = self._info_panel
                return bool(panel is not None and panel.has_file())
        except (AttributeError, RuntimeError):
            return False
        return False

    def _focus_selector_with_flash(self, *, flash: bool = True) -> bool:
        """把焦点回退到文件选择器，并把快捷键区域切回 ``selector``。

        空区域点击 / 区域失去内容 / 三块全空时键盘切区的统一回退入口。
        可选择是否闪一次选择器描边（同一焦点区内连续点击时调用方会关掉
        闪烁，沿用既有的描边去重口径）。

        Args:
            flash: True 时闪一次选择器分区描边。

        Returns:
            bool: 文件选择器存在并已请求聚焦返回 True。
        """
        selector = self._file_selector
        if selector is None:
            return False
        focus_file_list = getattr(selector, "focus_file_list", None)
        if not callable(focus_file_list):
            return False
        try:
            focus_file_list()
        except RuntimeError:
            return False
        shortcuts = getattr(self, "_shortcuts", None)
        if shortcuts is not None:
            try:
                shortcuts.replace_region("selector")
            except RuntimeError:
                pass
        if flash:
            self._flash_zone_focus("selector")
        return True

    # ──── 快捷键派发器（作用域栈 + 焦点区遍历） ────────────────────

    #: New（预览优先）布局的焦点区顺序。
    _ZONE_ORDER_WORKSPACE = ("path", "selector", "preview", "pool", "info")
    #: 经典三栏布局的焦点区顺序。
    _ZONE_ORDER_CLASSIC = ("path", "selector", "pool", "preview", "info")

    def _install_shortcut_dispatcher(self) -> None:
        """幂等安装快捷键派发器并连接区域解析。

        派发器是**应用级**事件过滤器（装在 ``QApplication``），因为需要覆盖
        全屏宿主、设置窗口等独立顶层窗口。区域由 ``focusChanged`` 实时维护。
        """
        if getattr(self, "_shortcut_installed", False):
            return
        try:
            app = QApplication.instance()
            if app is None:
                return
            from sopeek.core.shortcuts import shortcut_dispatcher

            self._shortcuts = shortcut_dispatcher()
            self._shortcuts.install(app)
            app.focusChanged.connect(self._on_shortcut_focus_changed)
            # 应用整体失活（切到别的程序）时兜底收尾长按：否则倍速会一直
            # 停在临时值。这是唯一保留的「非松手」收尾入口。
            app.applicationStateChanged.connect(self._on_app_state_changed)
            # 主窗口自身的鼠标过滤器也挂到应用级：点击 NoFocus 按钮 / 卡片时
            # 焦点不会变化，只有应用级过滤才能看到点击并把区域切过去。
            app.installEventFilter(self)
            self._window_filter_installed = True
            self._shortcut_installed = True
        except Exception as exc:  # noqa: BLE001 - 快捷键系统失败不阻塞启动
            warning(f"快捷键派发器安装失败: {exc}")

    def _uninstall_shortcut_dispatcher(self) -> None:
        """幂等卸载派发器与焦点监听（``destroyed`` 槽中调用，容错 RuntimeError）。"""
        if not getattr(self, "_shortcut_installed", False):
            return
        self._shortcut_installed = False
        app = QApplication.instance()
        if app is not None:
            if getattr(self, "_window_filter_installed", False):
                self._window_filter_installed = False
                try:
                    app.removeEventFilter(self)
                except RuntimeError:
                    pass
            try:
                app.focusChanged.disconnect(self._on_shortcut_focus_changed)
            except (RuntimeError, TypeError):
                pass
            try:
                app.applicationStateChanged.disconnect(self._on_app_state_changed)
            except (RuntimeError, TypeError):
                pass
        try:
            from sopeek.core.shortcuts import shortcut_dispatcher

            dispatcher = shortcut_dispatcher()
            # 子组件也各自登记过 handler：主窗口关闭时一并注销，
            # 避免同一进程内重建主窗口（测试 / 重新登录）时残留旧控件引用。
            for child in (
                getattr(self, "_file_selector", None),
                getattr(self, "_file_pool", None),
                getattr(self, "_info_panel", None),
            ):
                unregister = getattr(child, "_unregister_shortcuts", None)
                if callable(unregister):
                    try:
                        unregister()
                    except RuntimeError:
                        pass
            dispatcher.handlers.unregister_owner(self)
            dispatcher.uninstall()
        except Exception:  # noqa: BLE001 - 拆除阶段忽略
            pass

    def _on_app_state_changed(self, state) -> None:
        """应用激活状态变化：失活时兜底收尾长按（恢复临时倍速）。

        点击音量按钮 / 移动鼠标只改变窗口内焦点，**不会**触发这里；只有
        整个应用失去激活（切到别的程序）才会收尾。
        """
        try:
            from PySide6.QtCore import Qt as _Qt

            if state == _Qt.ApplicationState.ApplicationInactive:
                shortcuts = getattr(self, "_shortcuts", None)
                if shortcuts is not None:
                    shortcuts.finish_long_press_if_any()
        except (RuntimeError, AttributeError):
            pass

    def _on_shortcut_focus_changed(self, _old, new) -> None:
        """焦点变化：重算区域栈。

        注意**不**在此处收尾长按：长按倍速期间点击音量按钮 / 移动鼠标都会
        触发焦点变化，若强制收尾会让倍速「自己恢复」（用户实测反馈）。
        长按只由真实 ``KeyRelease``、预览器 ``cleanup`` 或主窗口失活收尾。
        """
        shortcuts = getattr(self, "_shortcuts", None)
        if shortcuts is None:
            return
        region = self._resolve_shortcut_region(new)
        if region is None:
            return
        self._remember_zone_before_preview(region)
        if region != shortcuts.region():
            shortcuts.replace_region(region)

    def _resolve_shortcut_region(self, widget: Optional[QWidget]):
        """按焦点归属解析快捷键区域（自上而下，先命中先返回）。

        Args:
            widget: 当前焦点控件（可为 ``None``）。

        Returns:
            str | None: 区域名；``None`` 表示「不在本窗口内，保持原区域」。
        """
        if widget is None:
            return "app"
        try:
            if (
                self._settings_window is not None
                and widget.window() is self._settings_window
            ):
                return "settings"
            if widget.window() is not self:
                # 全屏宿主等其它顶层窗口由进出全屏的代码显式 push/pop。
                return None
        except RuntimeError:
            return None
        if self._is_descendant_of(widget, self._file_selector):
            path_input = getattr(self._file_selector, "_path_input", None)
            if path_input is not None and widget is path_input:
                return "path"
            return "selector"
        if self._is_descendant_of(widget, self._file_pool):
            return "pool"
        if self._is_descendant_of(widget, self._info_panel):
            return "info"
        if self._is_descendant_of(widget, self._previewer):
            # 预览器已清空（无当前内层预览器）：预览区只剩占位符，方向键没有
            # 可操作对象。归属按「文件选择器」处理，让取消预览后焦点残留在
            # 预览区时，方向键仍能落到左侧卡片，而不是变成无响应的死键。
            # 只对「空预览器」生效：未知类型的预览器仍走 _preview_region_of
            # 的 app 回落，避免影响 Office 等未登记预览器的既有行为。
            if getattr(self._previewer, "_current_preview_type", None) is None:
                return "selector"
            return self._preview_region_of(self._previewer)
        return "app"

    @staticmethod
    def _is_descendant_of(
        widget: QWidget, ancestor: Optional[QWidget]
    ) -> bool:
        """``widget`` 是否等于 ``ancestor`` 或位于其子树（``None`` 安全）。

        Args:
            widget: 待判定控件。
            ancestor: 祖先控件。

        Returns:
            bool: 位于子树内返回 True。
        """
        if ancestor is None or widget is None:
            return False
        try:
            return widget is ancestor or ancestor.isAncestorOf(widget)
        except RuntimeError:
            return False

    @staticmethod
    def _preview_region_of(previewer) -> str:
        """把当前内层预览器类映射为区域名（未知类回退 ``app``）。

        Args:
            previewer: ``UnifiedPreviewerLayout`` 实例。

        Returns:
            str: 区域名。
        """
        mapping = {
            "VideoPlayerLayout": "preview.media",
            "ImagePreviewerLayout": "preview.image",
            "PdfPreviewerLayout": "preview.pdf",
            "TextPreviewerLayout": "preview.text",
            "FontPreviewerLayout": "preview.font",
            "ArchivePreviewerLayout": "preview.archive",
            "FolderPreviewerLayout": "preview.folder",
            "UnsupportedPreviewerLayout": "preview.unsupported",
        }
        cls = getattr(previewer, "_current_preview_type", None)
        return mapping.get(getattr(cls, "__name__", ""), "app")

    # ── 焦点区遍历 ──────────────────────────────────────────────

    #: 可作为「预览器 Esc 回跳目标」的焦点区（含卡片的区域）。
    _ZONE_REGIONS = ("path", "selector", "pool", "info")

    def _remember_zone_before_preview(self, region) -> None:
        """记录最近一次非预览焦点区（预览器根目录 Esc 的回跳目标）。

        预览器自身切换（``preview.*``）不覆盖记录，因此记录值始终是「进入
        预览器之前」的焦点区；``app`` / ``settings`` / ``fullscreen`` 同样
        不覆盖（它们不是卡片区）。

        Args:
            region: 本次解析出的快捷键区域名。
        """
        if region in self._ZONE_REGIONS:
            self._zone_before_preview = str(region)

    def _current_zone_name(self) -> str:
        """把当前区域映射为焦点区名（path/selector/preview/pool/info）。"""
        shortcuts = getattr(self, "_shortcuts", None)
        region = shortcuts.region() if shortcuts is not None else "app"
        if region in ("path", "selector", "pool", "info"):
            return region
        if region.startswith("preview.") or region == "fullscreen":
            return "preview"
        return ""

    def _focus_next_zone(self, step: int) -> bool:
        """按当前布局顺序把焦点切到上/下一个**可聚焦**区域。

        空预览区 / 空储存池 / 空信息面板不是焦点区：逐区尝试时直接跳过。
        当右侧三区全空时：

        - 第一次从文件选择器切区：停在文件选择器并高亮它（没有别处可去，
          仍要给出可见反馈）；
        - 再按一次：继续到路径框，保证路径框始终可达。

        当前区域本身已失去内容（例如池刚被清空）时，先回退到文件选择器并
        高亮，而不是把焦点留在失效区域。

        Args:
            step: +1 下一个 / -1 上一个。

        Returns:
            bool: 发生了一次焦点切换或选择器回退高亮返回 True。
        """
        order = (
            self._ZONE_ORDER_CLASSIC
            if getattr(self, "_layout_mode", "workspace") == "classic"
            else self._ZONE_ORDER_WORKSPACE
        )
        content_zones = ("preview", "pool", "info")
        all_empty = not any(
            self._zone_can_take_focus(zone) for zone in content_zones
        )
        if not all_empty:
            self._empty_cycle_selector_stay = False
        current = self._current_zone_name()
        # 当前区已无内容（焦点残留在刚清空的池/信息面板/预览区）：回退到
        # 文件选择器并高亮；若三区全空，下一次按键再去路径框。
        if current in content_zones and not self._zone_can_take_focus(current):
            self._empty_cycle_selector_stay = all_empty
            return self._focus_selector_with_flash()
        # 三区全空：从文件选择器切区的第一次按键先停在选择器并高亮，
        # 下一次才继续到路径框（用户明确要求的「先停一下」语义）。
        if all_empty and current == "selector":
            if self._empty_cycle_selector_stay:
                self._empty_cycle_selector_stay = False
                if self._focus_zone("path"):
                    return True
                return self._focus_selector_with_flash()
            self._empty_cycle_selector_stay = True
            return self._focus_selector_with_flash()
        try:
            index = order.index(current)
        except ValueError:
            index = -1
        for offset in range(1, len(order) + 1):
            target = order[(index + step * offset) % len(order)]
            if target == current:
                continue
            if self._focus_zone(target):
                if all_empty and target == "selector":
                    # 从路径框切回文件选择器后，下一次按键直接去路径框，
                    # 避免在同一个选择器上重复“停一下”。
                    self._empty_cycle_selector_stay = True
                return True
        # 找不到其它可聚焦区：至少把焦点收回文件选择器并高亮，不能静默
        # 无响应（用户看到按键没反应会以为快捷键失效）。
        return self._focus_selector_with_flash()

    def _on_preview_root_escape(self) -> bool:
        """压缩包/文件夹预览器已在根目录再按 Esc：焦点交还进入前的焦点区。

        回跳目标按「记录区 → 文件选择器 → 储存池 → 信息面板」去重顺序尝试：
        目标区不可聚焦（空池 / 无信息条目）时继续找下一个可聚焦区。光标
        刷新到目标区第一个卡片，并闪一次焦点描边（由 ``_focus_zone`` 完成）。

        Returns:
            bool: 有区域成功接管焦点返回 True（Esc 随之消费）。
        """
        preferred = getattr(self, "_zone_before_preview", "") or "selector"
        if preferred not in self._ZONE_REGIONS:
            preferred = "selector"
        candidates = [preferred]
        for fallback in ("selector", "pool", "info"):
            if fallback not in candidates:
                candidates.append(fallback)
        for name in candidates:
            if self._focus_zone(name, first=True):
                return True
        return False

    def _flash_zone_focus(self, zone_name: str) -> None:
        """在指定区域闪一次焦点描边（焦点区实际发生切换时调用）。

        同时记录本次高亮区域，供 :meth:`_sync_region_from_click` 去重：
        键盘切换后再用鼠标点击同一区域不会重复高亮。

        Args:
            zone_name: ``path`` / ``selector`` / ``preview`` / ``pool`` / ``info``。
                ``path`` 只高亮路径输入框本身，不覆盖整个左栏。
        """
        layout = self._main_layout
        if layout is None:
            return
        if zone_name == "path":
            path_input = getattr(self._file_selector, "_path_input", None)
            if path_input is None:
                return
            flash_widget = getattr(layout, "flash_widget", None)
            if callable(flash_widget):
                try:
                    flash_widget(path_input)
                except RuntimeError:
                    return
            self._last_flash_zone = zone_name
            return
        flash = getattr(layout, "flash_zone_focus", None)
        if callable(flash):
            try:
                flash(zone_name)
            except RuntimeError:
                return
            self._last_flash_zone = zone_name

    def _focus_zone(self, name: str, *, first: bool = False) -> bool:
        """把键盘焦点交给指定区域。

        Args:
            name: 区名（path/selector/pool/preview/info）。
            first: True 时把该区键盘光标刷新到第一个卡片（预览器根目录
                Esc 回跳用）；储存池 / 信息面板的聚焦方法本身即回首卡。

        Returns:
            bool: 成功聚焦返回 True。
        """
        mapping = {
            "path": lambda: self._file_selector._path_input.setFocus(),
            "selector": lambda: (
                self._file_selector.focus_first_entry()
                if first
                else self._file_selector.focus_file_list()
            ),
            "pool": lambda: self._file_pool.focus_first_card(),
            "preview": lambda: self._previewer.focus_active_previewer(),
            "info": lambda: self._info_panel.focus_canvas(),
        }
        fn = mapping.get(name)
        if fn is None:
            return False
        try:
            fn()
        except (AttributeError, RuntimeError) as exc:
            debug(f"焦点区切换失败（{name}）: {exc}")
            return False
        # 目标区可能「方法返回 True 但实际没拿到焦点」（空池 / 无预览器）：
        # 必须以真实焦点归属判定，否则 _focus_next_zone 会停在原地。
        if not self._zone_has_keyboard_focus(name):
            return False
        self._flash_zone_focus(name)
        return True

    def _zone_has_keyboard_focus(self, name: str) -> bool:
        """当前真实键盘焦点是否落在指定区域。

        Args:
            name: 区域名（path/selector/pool/preview/info）。

        Returns:
            bool: 焦点在该区域内返回 True。
        """
        widget = QApplication.focusWidget()
        if widget is None:
            return False
        try:
            if name == "path":
                return widget is self._file_selector._path_input
            if name == "selector":
                return (
                    self._is_descendant_of(widget, self._file_selector)
                    and widget is not self._file_selector._path_input
                )
            if name == "pool":
                return self._is_descendant_of(widget, self._file_pool)
            if name == "preview":
                return self._is_descendant_of(widget, self._previewer)
            if name == "info":
                return self._is_descendant_of(widget, self._info_panel)
        except (AttributeError, RuntimeError):
            return False
        return False

    # ── 快捷键处理器接线 ────────────────────────────────────────

    #: 选择器 / 储存池共用、需委托给「当前预览器」的媒体动作。
    _MEDIA_DELEGATION = (
        ("play_pause", "toggle_play_pause"),
        ("seek_back", "seek_backward"),
        ("seek_forward", "seek_forward"),
        ("volume_up", "volume_up"),
        ("volume_down", "volume_down"),
    )

    #: 倍速动作 → 目标倍速。
    _MEDIA_SPEEDS = (
        ("speed_1", 1.0),
        ("speed_2", 2.0),
        ("speed_3", 3.0),
        ("speed_half", 0.5),
    )

    def _setup_shortcuts(self) -> None:
        """登记主窗口层的快捷键处理器（全局 / 焦点区 / 媒体委托）。

        选择器、储存池、信息面板、各预览器的处理器由各自
        ``_register_shortcuts()`` 登记；本方法只处理「跨组件转发方」。
        """
        if getattr(self, "_shortcuts_wired", False):
            return
        try:
            from sopeek.core.shortcuts import shortcut_dispatcher

            dispatcher = shortcut_dispatcher()
            self._shortcuts = dispatcher
            dispatcher.handlers.register_many(
                {
                    "global.open_settings": self._shortcut_open_settings,
                    "global.open_in_explorer": self._shortcut_open_in_explorer,
                    "global.open_with_default": self._shortcut_open_with_default,
                    "global.locate_in_app": self._shortcut_locate_in_app,
                    "nav.next_zone": lambda: self._focus_next_zone(+1),
                    "nav.prev_zone": lambda: self._focus_next_zone(-1),
                    "nav.next_zone_f6": lambda: self._focus_next_zone(+1),
                    "nav.prev_zone_f6": lambda: self._focus_next_zone(-1),
                },
                owner=self,
            )

            for prefix in ("selector", "pool"):
                for action, method in self._MEDIA_DELEGATION:
                    dispatcher.handlers.register(
                        f"{prefix}.{action}",
                        self._make_media_call(method),
                        owner=self,
                    )
                for action, speed in self._MEDIA_SPEEDS:
                    dispatcher.handlers.register(
                        f"{prefix}.{action}.press",
                        self._make_media_speed_press(speed),
                        owner=self,
                    )
                    dispatcher.handlers.register(
                        f"{prefix}.{action}.release",
                        self._make_media_speed_release(),
                        owner=self,
                    )

            # 储存池的缩略图动作委托给文件选择器的控制器执行（池内无控制器）
            dispatcher.handlers.register_many(
                {
                    "pool.gen_thumbs": self._shortcut_pool_gen_thumbs,
                    "pool.clear_thumbs": self._shortcut_pool_clear_thumbs,
                },
                owner=self,
            )

            # 全屏切换在非预览器区域也生效：注册表已把 5 个 *.fullscreen 动作
            # 声明到 app / selector / pool / info / path，这里为每个区域补一份
            # 「转发到当前预览器」的备用 handler（派发器优先取 {id}@{region}）。
            for region in ("app", "selector", "pool", "info", "path"):
                for action_id in (
                    "preview.media.fullscreen",
                    "preview.image.fullscreen",
                    "preview.pdf.fullscreen",
                    "preview.text.fullscreen",
                    "preview.font.fullscreen",
                ):
                    dispatcher.handlers.register(
                        f"{action_id}@{region}",
                        self._shortcut_toggle_fullscreen,
                        owner=self,
                    )

            # 预览器抽屉 / 内联搜索键：焦点在文件选择器或储存池时也应生效，
            # 且必须是真正的 toggle（第二次按下关闭）。
            for region in ("app", "selector", "pool", "info", "path", "fullscreen"):
                for action_id in (
                    "preview.pdf.toggle_index",
                    "preview.text.toggle_search",
                    "preview.archive.toggle_search",
                ):
                    dispatcher.handlers.register(
                        f"{action_id}@{region}",
                        lambda a=action_id: self._shortcut_toggle_preview_ui(a),
                        owner=self,
                    )
            self._shortcuts_wired = True
        except Exception as exc:  # noqa: BLE001 - 快捷键接线失败不阻塞主界面
            warning(f"快捷键处理器接线失败: {exc}")

    # ── 媒体委托 ────────────────────────────────────────────────

    def _shortcut_pool_gen_thumbs(self) -> bool:
        """``Q``（池内）：为储存池中的全部文件生成缩略图。"""
        if self._file_selector is None or self._file_pool is None:
            return True
        return self._file_selector.generate_thumbnails_for_paths(
            self._file_pool.thumbnail_paths(), scope="pool"
        )

    def _shortcut_pool_clear_thumbs(self) -> bool:
        """``Shift+Q``（池内）：清除储存池中全部文件的缩略图缓存。"""
        if self._file_selector is None or self._file_pool is None:
            return True
        return self._file_selector.clear_thumbnails_for_paths(
            self._file_pool.thumbnail_paths()
        )

    def _active_media_previewer(self):
        """返回当前内层预览器（非媒体时同样返回，调用方按属性判断）。"""
        previewer = self._previewer
        if previewer is None:
            return None
        return getattr(previewer, "_current_preview_widget", None)

    def _make_media_call(self, method: str):
        """生成「转发到当前预览器某方法」的零参处理器。

        Args:
            method: 预览器上的方法名（如 ``toggle_play_pause``）。

        Returns:
            Callable[[], None]: 处理器；无媒体预览器时静默无操作。
        """

        def _call() -> None:
            target = self._active_media_previewer()
            fn = getattr(target, method, None)
            if callable(fn):
                try:
                    fn()
                except RuntimeError:
                    pass

        return _call

    def _current_media_speed(self) -> float:
        """读取当前预览器倍速（无媒体预览器时回退 1.0）。"""
        target = self._active_media_previewer()
        value = getattr(target, "current_speed", None)
        try:
            return float(value) if value is not None else 1.0
        except (TypeError, ValueError):
            return 1.0

    def _apply_media_speed(self, speed: float) -> None:
        """把目标倍速下发给当前预览器（无媒体预览器时无操作）。"""
        target = self._active_media_previewer()
        fn = getattr(target, "set_speed", None)
        if callable(fn):
            try:
                fn(speed)
            except RuntimeError:
                pass

    def _make_media_speed_press(self, speed: float):
        """生成倍速键「按下」处理器（立即生效，保证短按零延迟）。

        优先走预览器的 ``begin_temp_speed``（切速 + 常显 OSD，长按期间提示
        不自动隐藏）；预览器未提供该接口时回退为纯切速。

        Args:
            speed: 目标倍速。

        Returns:
            Callable[[], None]: 处理器。
        """

        def _press() -> None:
            self._media_prev_speed = self._current_media_speed()
            target = self._active_media_previewer()
            fn = getattr(target, "begin_temp_speed", None)
            if callable(fn):
                try:
                    fn(speed)
                    return
                except (RuntimeError, TypeError):
                    pass
            self._apply_media_speed(speed)

        return _press

    def _make_media_speed_release(self):
        """生成倍速键「释放」处理器（长按回滚 + 收掉常显提示）。

        优先走预览器的 ``end_temp_speed``（结束常显 → 长按回滚 / 短按保持，
        随后普通提示自动隐藏）；未提供时回退为「仅长按回滚」。

        Returns:
            Callable[[bool], None]: 接收 ``long_pressed`` 的处理器。
        """

        def _release(long_pressed: bool) -> None:
            target = self._active_media_previewer()
            fn = getattr(target, "end_temp_speed", None)
            if callable(fn):
                try:
                    fn(bool(long_pressed))
                    return
                except (RuntimeError, TypeError):
                    pass
            if long_pressed:
                self._apply_media_speed(getattr(self, "_media_prev_speed", 1.0))

        return _release

    # ── 全局动作 ────────────────────────────────────────────────

    def _shortcut_toggle_fullscreen(self) -> bool:
        """``Ctrl+\\``：对当前预览器切换全屏（任何区域都可触发）。

        延后一帧执行：全屏进出会把预览器 reparent 到独立顶层窗口，
        在按键事件链内直接做会触发原生窗口重建期崩溃。

        Returns:
            bool: 有可全屏预览器并已排程返回 True。
        """
        previewer = self._previewer
        widget = (
            getattr(previewer, "_current_preview_widget", None)
            if previewer is not None
            else None
        )
        toggle = getattr(widget, "_on_maxsize_toggle", None)
        if not callable(toggle):
            return False
        from sopeek.core.shortcuts import defer_call

        defer_call(toggle)
        return True

    def _shortcut_toggle_preview_ui(self, action_id: str) -> bool:
        """把预览器抽屉 / 内联搜索键转发给当前预览器（任何区域可用）。

        Args:
            action_id: 预览器动作 id。

        Returns:
            bool: 当前预览器支持该动作并已调用返回 True。
        """
        previewer = self._previewer
        widget = (
            getattr(previewer, "_current_preview_widget", None)
            if previewer is not None
            else None
        )
        if widget is None:
            return False
        method_name = {
            "preview.pdf.toggle_index": "_toggle_index_drawer",
            "preview.text.toggle_search": "_toggle_search_drawer",
            "preview.archive.toggle_search": "_toggle_search",
        }.get(action_id)
        if method_name is None:
            return False
        method = getattr(widget, method_name, None)
        if not callable(method):
            return False
        try:
            method()
        except RuntimeError:
            return False
        return True

    def _apply_pool_layout_mode(self) -> None:
        """把当前布局模式下发给储存池（三栏禁用卡片缩放）。幂等。"""
        pool = self._file_pool
        if pool is None:
            return
        setter = getattr(pool, "set_layout_mode", None)
        if callable(setter):
            try:
                setter(self._layout_mode)
            except RuntimeError:
                pass

    def _on_previewer_file_nav(self, step: int) -> None:
        """预览器请求切上/下一个文件（图像 ``←→``）。

        光标推进交给文件选择器（同一份光标状态），但**跳过文件夹**：
        预览器应连续停留在同类内容上，不应因为遇到文件夹而切换预览器类型。

        Args:
            step: +1 下一个 / -1 上一个。
        """
        selector = self._file_selector
        if selector is None:
            return
        try:
            info = selector.advance_cursor(step, skip_dirs=True)
        except Exception as exc:  # noqa: BLE001 - 导航失败不影响当前预览
            debug(f"预览器切文件失败: {exc}")
            return
        if info:
            self._show_preview(info)

    def _shortcut_open_settings(self) -> bool:
        """``Ctrl+I``：打开设置；已打开则关闭（对称切换）。

        全屏时先退出全屏再打开设置——全屏宿主是独立顶层窗口，直接在其上叠
        设置窗口会打乱窗口层级与生命周期（实测闪退）。

        Returns:
            bool: 始终返回 True（消费事件）。
        """
        window = getattr(self, "_settings_window", None)
        visible = False
        if window is not None:
            try:
                visible = bool(window.isVisible())
            except RuntimeError:
                window = None
                visible = False
        if visible:
            try:
                window.close()
            except RuntimeError:
                pass
            return True

        # 全屏中：先退出全屏（延后一帧，避免在按键事件链内 reparent），
        # 再打开设置窗口。
        if self._is_fullscreen_active():
            from sopeek.core.shortcuts import defer_call

            defer_call(self._leave_fullscreen_then_open_settings)
            return True

        self._open_settings_window()
        return True

    def _is_fullscreen_active(self) -> bool:
        """当前是否有预览器处于全屏。

        Returns:
            bool: 有全屏预览器返回 True。
        """
        shortcuts = getattr(self, "_shortcuts", None)
        if shortcuts is not None and shortcuts.region() == "fullscreen":
            return True
        previewer = self._previewer
        widget = (
            getattr(previewer, "_current_preview_widget", None)
            if previewer is not None
            else None
        )
        return bool(getattr(widget, "_fullscreen", False))

    def _leave_fullscreen_then_open_settings(self) -> None:
        """退出当前全屏预览器，然后打开设置窗口（供 ``Ctrl+I`` 全屏路径使用）。"""
        previewer = self._previewer
        widget = (
            getattr(previewer, "_current_preview_widget", None)
            if previewer is not None
            else None
        )
        exit_fn = getattr(widget, "_exit_fullscreen", None)
        if callable(exit_fn):
            try:
                exit_fn()
            except Exception as exc:  # noqa: BLE001 - 退出全屏失败仍要能开设置
                debug(f"退出全屏失败（继续打开设置）: {exc}")
        self._open_settings_window()

    def _current_preview_path(self) -> str:
        """返回当前预览文件的绝对路径（无预览时为空串）。"""
        previewer = self._previewer
        if previewer is None:
            return ""
        getter = getattr(previewer, "current_file_info", None)
        if not callable(getter):
            return ""
        try:
            info = getter()
        except Exception:  # noqa: BLE001 - 读取失败按无预览处理
            return ""
        if not isinstance(info, dict):
            return ""
        path = str(info.get("path") or "")
        return os.path.abspath(path) if path else ""

    def _shortcut_open_in_explorer(self) -> bool:
        """``Ctrl+M``：在系统文件资源管理器中打开并选中当前文件。

        归档内文件 / 已删除文件的路径在磁盘上不存在，``explorer /select,``
        会静默失败。此时回退到「打开最近的已存在父目录」，至少让用户看到
        所在位置，而不是按键毫无反应。
        """
        path = self._current_preview_path()
        if not path or not os.path.isabs(path):
            return True
        import subprocess

        if os.path.exists(path):
            try:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            except Exception as exc:  # noqa: BLE001 - 打开失败仅记录
                warning(f"在资源管理器中打开失败: {exc}")
            return True

        # 回退：逐级向上找到第一个存在的目录
        fallback_dir = os.path.dirname(os.path.normpath(path))
        while fallback_dir and not os.path.isdir(fallback_dir):
            parent = os.path.dirname(fallback_dir)
            if parent == fallback_dir:
                fallback_dir = ""
                break
            fallback_dir = parent
        if not fallback_dir:
            warning(f"在资源管理器中打开失败：路径不存在 {path}")
            return True
        try:
            subprocess.Popen(["explorer", os.path.normpath(fallback_dir)])
        except Exception as exc:  # noqa: BLE001 - 打开失败仅记录
            warning(f"在资源管理器中打开目录失败: {exc}")
        return True

    def _shortcut_open_with_default(self) -> bool:
        """``Ctrl+K``：用系统默认方式打开当前文件。"""
        path = self._current_preview_path()
        if not path or not os.path.exists(path):
            return True
        try:
            os.startfile(path)  # noqa: S606 - Windows 平台预期行为
        except Exception as exc:  # noqa: BLE001 - 打开失败仅记录
            warning(f"使用系统默认方式打开失败: {exc}")
        return True

    def _shortcut_locate_in_app(self) -> bool:
        """``Ctrl+O``：文件选择器跳转到当前文件所在目录并高亮。"""
        path = self._current_preview_path()
        if not path:
            return True
        previewer = self._previewer
        getter = getattr(previewer, "current_file_info", None) if previewer else None
        info = None
        if callable(getter):
            try:
                info = getter()
            except Exception:  # noqa: BLE001 - 读取失败按无预览处理
                info = None
        if not isinstance(info, dict):
            info = {"path": path}
        try:
            self._file_selector.locate_file(dict(info))
        except Exception as exc:  # noqa: BLE001 - 定位失败仅记录
            warning(f"应用内定位失败: {exc}")
        return True

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

        只切换背景层可见性、不销毁重建控件（三个背景层常驻，切换零构建成本）；
        模式真正变化且窗口在屏时，额外做 450ms 背景交叉淡入（切前抓当前
        可见层帧、切后旧帧淡出露出新层，见 ``_capture_background_frame`` /
        ``_start_background_transition``）——内容层保持实时，仅背景区域
        平滑过渡；抓拍/遮罩失败静默跳过，切换本身不受影响。

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
        # 过渡预抓拍：模式真正变化且在屏时才抓旧帧（新层切换后全量在底，
        # 旧帧淡出即交叉淡入；连切合成屏幕现状，见 _prepare_background_frame）。
        backdrop = None
        mode_changed = mode != getattr(self, "_background_mode", "mica")
        if mode_changed and self._can_transition_background():
            backdrop = self._prepare_background_frame()
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
        if mode_changed:
            # 设置窗口等观察者据此同步背景可见性；在层可见性落定后发。
            self.background_mode_changed.emit(mode)
        if backdrop is not None:
            self._start_background_transition(backdrop)

    def set_ambient_enabled(self, enabled: bool) -> None:
        """设置简约背景的氛围开关并转发给简约层。

        已处于「简约」模式且该层在屏时，氛围值真正变化也走 450ms 交叉淡入
        （切前抓旧渐变帧、切换后淡出）；其余场景（层未显示/同值重复）仅
        记录并转发，由 ``set_background_mode`` 的过渡统一覆盖，不会双重过渡。

        Args:
            enabled: True 开启氛围渐变，False 使用纯色；经 bool() 归一后记录。
        """
        enabled = bool(enabled)
        backdrop = None
        minimalist = getattr(self, "_minimalist_background", None)
        if (
            enabled != bool(getattr(self, "_background_ambient", True))
            and minimalist is not None
            and getattr(self, "_background_mode", "mica") == "minimalist"
            and self._can_transition_background()
        ):
            try:
                if not minimalist.isHidden():
                    backdrop = self._prepare_background_frame()
            except Exception:  # noqa: BLE001 - 判定失败按不做过渡处理
                backdrop = None
        self._background_ambient = enabled
        if minimalist is not None:
            minimalist.set_ambient_enabled(self._background_ambient)
        if backdrop is not None:
            self._start_background_transition(backdrop)

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

    # ──── 主界面布局模式 ───────────────────────────────────────────────

    def get_layout_mode(self) -> str:
        """返回当前主界面布局模式（供设置页联动与测试）。

        Returns:
            str: "classic"（经典三栏）或 "workspace"（预览优先）。
        """
        return self._layout_mode

    def set_ai_entry_enabled(self, enabled: bool) -> None:
        """运行时切换 AI 功能入口（设置提交路径调用；幂等）。

        开启后 PDF / 文本预览器显示 AI 按钮与侧边抽屉；关闭时移除按钮并
        关闭抽屉（已构建的预览器由宿主 ``set_ai_entry_enabled`` 逐级下发，
        尚未构建的预览器在创建时读取本开关）。AI 实际能力为长期规划。

        Args:
            enabled: True 显示入口；False 完全隐藏。
        """
        self._ai_entry_enabled = bool(enabled)
        if self._previewer is not None:
            try:
                self._previewer.set_ai_entry_enabled(self._ai_entry_enabled)
            except Exception as exc:  # noqa: BLE001 - 开关应用失败不抛给调用方
                warning(f"AI 入口开关应用失败: {exc}")

    def set_include_remote_drives(self, enabled: bool) -> None:
        """运行时切换网络/映射盘与光驱加载（设置提交路径调用；幂等）。

        开启后文件选择器「All」视图额外列出 DRIVE_REMOTE 与 DRIVE_CDROM；
        若当前正停留在「All」视图，立即重新加载盘符列表。

        Args:
            enabled: True 包含网络/映射盘与光驱；False 仅物理磁盘。
        """
        self._include_remote_drives = bool(enabled)
        if self._file_selector is not None:
            try:
                self._file_selector.set_include_remote_drives(
                    self._include_remote_drives
                )
            except Exception as exc:  # noqa: BLE001 - 开关应用失败不抛给调用方
                warning(f"网络盘/光驱开关应用失败: {exc}")

    def set_blank_right_click_go_back(self, enabled: bool) -> None:
        """运行时切换空白区右键返回上一级（设置提交路径调用；幂等）。

        开启后文件选择器空白位右键在「页面无需滚动且点击落在空卡片位」
        时返回上一级；关闭时空白区右键不做导航（默认关闭）。

        Args:
            enabled: True 开启空白区右键返回；False 关闭。
        """
        self._blank_right_click_go_back = bool(enabled)
        if self._file_selector is not None:
            try:
                self._file_selector.set_blank_right_click_go_back(
                    self._blank_right_click_go_back
                )
            except Exception as exc:  # noqa: BLE001 - 开关应用失败不抛给调用方
                warning(f"空白区右键返回开关应用失败: {exc}")

    def set_show_hidden_files(self, enabled: bool) -> None:
        """运行时切换「显示隐藏文件」（设置提交路径调用；幂等）。

        关闭时同步关闭「显示系统文件」（系统文件可见性以隐藏文件开关为
        前提）；文件选择器与文件夹预览器若在当前视图会立即重扫。

        Args:
            enabled: True 显示隐藏文件；False 隐藏（默认）。
        """
        self._show_hidden_files = bool(enabled)
        if not self._show_hidden_files:
            self._show_system_files = False
        if self._file_selector is not None:
            try:
                self._file_selector.set_show_hidden_files(
                    self._show_hidden_files
                )
            except Exception as exc:  # noqa: BLE001 - 开关应用失败不抛给调用方
                warning(f"显示隐藏文件开关应用失败: {exc}")
        if self._previewer is not None:
            try:
                self._previewer.set_show_hidden_files(
                    self._show_hidden_files
                )
            except Exception as exc:  # noqa: BLE001 - 开关应用失败不抛给调用方
                warning(f"显示隐藏文件开关应用失败（预览器）: {exc}")

    def set_show_system_files(self, enabled: bool) -> None:
        """运行时切换「显示系统文件」（设置提交路径调用；幂等）。

        仅当「显示隐藏文件」亦开启时生效（AND 语义）；文件选择器与文件夹
        预览器若在当前视图会立即重扫。

        Args:
            enabled: True 显示系统文件；False 隐藏（默认）。
        """
        self._show_system_files = bool(enabled) and self._show_hidden_files
        if self._file_selector is not None:
            try:
                self._file_selector.set_show_system_files(
                    self._show_system_files
                )
            except Exception as exc:  # noqa: BLE001 - 开关应用失败不抛给调用方
                warning(f"显示系统文件开关应用失败: {exc}")
        if self._previewer is not None:
            try:
                self._previewer.set_show_system_files(
                    self._show_system_files
                )
            except Exception as exc:  # noqa: BLE001 - 开关应用失败不抛给调用方
                warning(f"显示系统文件开关应用失败（预览器）: {exc}")

    def set_floating_pool_enabled(self, enabled: bool) -> None:
        """运行时开关全局存储池浮窗（设置提交路径调用；幂等）。

        开启时经唯一入口 ``_ensure_floating_pool`` 创建（已存在则保留原
        实例）；关闭时断开信号连接、关闭并释放浮窗。重复调用同一值安全
        （开启两次不会创建第二个实例，关闭两次也不会抛异常）。

        Args:
            enabled: True 显示全局浮窗；False 关闭并释放。
        """
        self._floating_pool_enabled = bool(enabled)
        if self._floating_pool_enabled:
            self._ensure_floating_pool()
            return
        self._teardown_floating_pool()

    def set_floating_pool_snap_enabled(self, enabled: bool) -> None:
        """运行时开关全局浮窗贴边吸附（设置提交路径调用；幂等）。

        始终记录意图 ``_floating_pool_snap_enabled``——建窗路径
        ``_ensure_floating_pool`` 会按意图初始化（重启/重建后仍一致）；
        浮窗已存在时同步调用窗口侧 ``set_snap_enabled`` 即时生效（窗口侧
        API 缺失或失败仅记录 warning，不抛出）。重复调用同一值安全。

        Args:
            enabled: True 拖动浮窗靠近屏幕边缘时自动吸附；False 仅夹回屏内。
        """
        self._floating_pool_snap_enabled = bool(enabled)
        floating = self._floating_pool
        if floating is None:
            return
        try:
            floating.set_snap_enabled(self._floating_pool_snap_enabled)
        except Exception as exc:  # noqa: BLE001 - 吸附开关下发失败不抛给调用方
            warning(f"浮窗贴边吸附开关应用失败: {exc}")

    def set_close_action(self, behavior: str) -> None:
        """运行时更新关闭主窗口行为（设置提交路径调用；幂等）。

        仅更新内存态 ``_close_action``，不落盘（落盘由设置页提交完成）。
        非法值按 "ask" 处理，调用方无需预先校验。

        Args:
            behavior: 关闭行为，"ask" | "tray" | "quit"。
        """
        valid = behavior in ("ask", "tray", "quit")
        self._close_action = behavior if valid else "ask"
        debug(f"关闭主窗口行为已更新: {self._close_action}")

    # ── 关闭询问 / 系统托盘 ─────────────────────────────────────────────

    def _ask_close_choice(self) -> str:
        """弹出关闭询问弹窗并阻塞等待用户选择。

        用 ``StyledDialog`` 手动构建（``ask_custom_dialog`` 不支持勾选框）：
        说明文字 + 「记住我的选择」勾选框 + 三个按钮。用户勾选记住时立即
        持久化到 ``general.close_action``（绝不落盘 "ask"）。

        Returns:
            str: "tray"（最小化到托盘）、"quit"（直接退出）或 "cancel"
            （取消 / ESC / 关闭按钮 / 异常兜底）。
        """
        if getattr(self, "_close_dialog_open", False):
            return "cancel"
        if QApplication.instance() is None:
            return "cancel"

        self._close_dialog_open = True
        dlg = None
        try:
            from PySide6.QtCore import QEventLoop

            from components.styled_checkbox import StyledCheckbox
            from components.styled_dialog import (
                FOOTER_STACKED,
                StyledDialog,
                _show_dialog,
            )

            body = QWidget()
            register_widget_qss(body, "background: transparent;")
            body_layout = QVBoxLayout(body)
            body_layout.setContentsMargins(0, 0, 0, 0)
            body_layout.setSpacing(12)
            message = QLabel(
                "选择直接退出程序，或最小化到系统托盘继续运行；"
                "全局悬浮窗会保持可用。"
            )
            message.setWordWrap(True)
            register_widget_qss(
                message,
                f"font-size: 13.5px; color: {tm.qss_color(tm.text_secondary)};"
                " background: transparent;",
            )
            body_layout.addWidget(message)
            remember = StyledCheckbox(text="记住我的选择")
            body_layout.addWidget(remember)
            body_layout.addStretch(1)

            dlg = StyledDialog(
                title="关闭 Sopeek",
                body_widget=body,
                footer_type=FOOTER_STACKED,
                show_close=False,
                animate=True,
                parent=self,
                modal=True,
            )
            dlg.add_footer_button("最小化到托盘", "primary").clicked.connect(
                lambda: dlg.close_dialog(10)
            )
            dlg.add_footer_button("直接退出", "danger").clicked.connect(
                lambda: dlg.close_dialog(20)
            )
            dlg.add_footer_button("取消", "ghost").clicked.connect(
                lambda: dlg.close_dialog(0)
            )

            result = [0]
            loop = QEventLoop()

            def _record(code: int) -> None:
                result[0] = int(code)
                if loop.isRunning():
                    loop.quit()

            # ``closing`` 在关闭动作开始时发射（含 ESC / 关闭按钮路径），
            # ``finished`` 在退场动画结束后补发；两者都连以覆盖全部路径。
            dlg.closing.connect(_record)
            dlg.finished.connect(_record)
            _show_dialog(dlg)
            loop.exec()

            choice = {10: "tray", 20: "quit"}.get(result[0], "cancel")
            if remember.checked and choice in ("tray", "quit"):
                self._persist_close_action(choice)
            return choice
        except Exception as exc:  # noqa: BLE001 - 询问失败按取消处理，不阻断关闭
            warning(f"关闭询问弹窗失败（按取消处理）：{exc}")
            return "cancel"
        finally:
            self._close_dialog_open = False
            if dlg is not None:
                # 延迟销毁：等退场动画播完再回收，避免弹窗突然消失。
                def _dispose_dialog() -> None:
                    try:
                        dlg.deleteLater()
                    except RuntimeError:
                        pass

                QTimer.singleShot(400, _dispose_dialog)

    def _persist_close_action(self, behavior: str) -> None:
        """把「记住我的选择」立即落盘到 ``general.close_action``。

        Args:
            behavior: 仅接受 "tray" / "quit"；其它值直接忽略（绝不落盘 ask）。
        """
        if behavior not in ("tray", "quit"):
            return
        try:
            from sopeek.core.managers.settings_manager_v2 import SettingsManagerV2

            v2 = SettingsManagerV2()
            v2.set("general.close_action", behavior)
            v2.save()
            self._close_action = behavior
        except Exception as exc:  # noqa: BLE001 - 落盘失败不影响本次关闭
            warning(f"保存关闭主窗口行为失败：{exc}")

    def _create_tray_controller(self) -> QObject:
        """创建托盘控制器（单点构造入口，测试可 monkeypatch）。

        Returns:
            QObject: ``TrayController`` 实例（父对象为主窗口）。
        """
        from sopeek.ui.tray_controller import TrayController

        return TrayController(parent=self)

    def _ensure_tray_controller(self) -> Optional[QObject]:
        """惰性创建并接线托盘控制器；不可用时记录状态并返回 None。

        托盘不可用（无桌面会话 / 无托盘区 / 构造失败）时置
        ``_tray_unavailable``，后续调用直接返回 None，避免反复重试。

        Returns:
            Optional[QObject]: 可用的托盘控制器；不可用时为 None。
        """
        if getattr(self, "_tray_unavailable", False):
            return None
        controller = getattr(self, "_tray_controller", None)
        if controller is not None:
            return controller
        try:
            controller = self._create_tray_controller()
        except Exception as exc:  # noqa: BLE001 - 托盘创建失败按不可用降级
            warning(f"系统托盘创建失败（关闭将直接退出）：{exc}")
            self._tray_unavailable = True
            return None
        if controller is None or not getattr(controller, "is_available", False):
            warning("系统托盘不可用（关闭将直接退出）")
            self._tray_unavailable = True
            return None
        try:
            controller.open_requested.connect(self.restore_main_window)
            controller.quit_requested.connect(self.quit_from_tray)
        except (RuntimeError, AttributeError) as exc:
            warning(f"系统托盘信号接线失败（关闭将直接退出）：{exc}")
            self._tray_unavailable = True
            return None
        self._tray_controller = controller
        try:
            controller.show()
        except RuntimeError:
            pass
        return controller

    def _enter_tray_mode(self) -> bool:
        """关闭设置窗、挂起预览与背景渲染后隐藏主窗口，进入托盘运行。

        Returns:
            bool: 成功进入托盘模式返回 True；托盘不可用 / 隐藏失败返回 False。
        """
        if self._ensure_tray_controller() is None:
            return False
        try:
            self._close_settings_window_now()
        except Exception as exc:  # noqa: BLE001 - 设置窗收尾失败不阻断挂起
            debug(f"进入托盘前关闭设置窗口失败：{exc}")
        # 隐藏后残留的独立顶层弹窗（筛选/收藏夹/提示等）会继续浮在桌面上，
        # 与「退居托盘」语义冲突，故一并回收（幂等）。
        self._close_floating_dialogs()
        try:
            self._suspend_for_tray()
        except Exception as exc:  # noqa: BLE001 - 挂起失败仍继续隐藏
            warning(f"进入托盘前挂起预览失败：{exc}")
        try:
            QApplication.setQuitOnLastWindowClosed(False)
            self.hide()
        except (RuntimeError, TypeError) as exc:
            warning(f"进入系统托盘失败（恢复直接退出）：{exc}")
            try:
                QApplication.setQuitOnLastWindowClosed(True)
            except (RuntimeError, TypeError):
                pass
            return False
        return True

    def _dispose_tray(self) -> None:
        """销毁托盘控制器并清空引用（幂等，真正退出时调用）。"""
        controller = getattr(self, "_tray_controller", None)
        self._tray_controller = None
        if controller is None:
            return
        try:
            controller.dispose()
        except RuntimeError:
            pass

    def _suspend_for_tray(self) -> None:
        """挂起预览器 / 信息面板与后台渲染资源，供托盘模式长期驻留。

        记录当前预览与信息面板文件快照后清空预览（释放视频/文档占用），
        再释放内存缓存与流体/Mica 纹理。重复调用不重复执行。
        """
        if getattr(self, "_tray_suspended", False):
            return
        previewer = getattr(self, "_previewer", None)
        info_panel = getattr(self, "_info_panel", None)

        preview_info = (
            self._read_current_file_info(previewer) if previewer is not None else None
        )
        self._tray_preview_file = preview_info

        # 信息面板没有独立的“当前文件”接口，沿用预览文件快照；若未来提供
        # 同形态读取入口则优先使用其自身值。
        info_file = preview_info
        if info_panel is not None:
            panel_file = self._read_current_file_info(info_panel)
            if panel_file is not None:
                info_file = panel_file
        self._tray_info_file = info_file

        if previewer is not None:
            try:
                previewer.clear_preview()
            except (RuntimeError, AttributeError) as exc:
                debug(f"进入托盘时清空预览失败：{exc}")
        if info_panel is not None:
            try:
                info_panel.stop()
            except (RuntimeError, AttributeError) as exc:
                debug(f"进入托盘时停止信息面板失败：{exc}")
        try:
            from sopeek.core.memory_budget import get_memory_budget

            get_memory_budget().release_caches()
        except Exception as exc:  # noqa: BLE001 - 缓存释放失败不影响挂起
            debug(f"进入托盘时释放内存缓存失败：{exc}")
        try:
            self._suspend_background_renderers()
        except Exception as exc:  # noqa: BLE001 - 渲染挂起失败不影响挂起
            debug(f"进入托盘时挂起背景渲染失败：{exc}")
        self._tray_suspended = True

    @staticmethod
    def _read_current_file_info(owner: object) -> Optional[dict]:
        """读取控件当前文件信息（兼容属性与 ``current_file_info()`` 方法）。

        Args:
            owner: 预览器 / 信息面板等可能暴露当前文件的控件。

        Returns:
            Optional[dict]: 文件信息副本；无当前文件或读取失败返回 None。
        """
        try:
            raw = getattr(owner, "current_file_info", None)
            if callable(raw):
                raw = raw()
        except (RuntimeError, AttributeError, TypeError):
            return None
        return dict(raw) if isinstance(raw, dict) else None

    def _resume_from_tray(self) -> None:
        """从托盘挂起态恢复：还原退出策略、后台渲染与预览内容。

        仅在确实挂起过时执行（避免重复加载）；恢复后清空快照记录。
        """
        if not getattr(self, "_tray_suspended", False):
            return
        try:
            QApplication.setQuitOnLastWindowClosed(True)
        except (RuntimeError, TypeError):
            pass
        try:
            self._resume_background_renderers()
        except Exception as exc:  # noqa: BLE001 - 恢复失败不影响窗口显示
            debug(f"从托盘恢复背景渲染失败：{exc}")

        preview_info = getattr(self, "_tray_preview_file", None)
        previewer = getattr(self, "_previewer", None)
        if preview_info is not None and previewer is not None:
            try:
                previewer.set_file(preview_info)
            except (RuntimeError, AttributeError) as exc:
                debug(f"从托盘恢复预览失败：{exc}")
        info_file = getattr(self, "_tray_info_file", None)
        info_panel = getattr(self, "_info_panel", None)
        if info_file is not None and info_panel is not None:
            try:
                info_panel.set_file(info_file)
            except (RuntimeError, AttributeError) as exc:
                debug(f"从托盘恢复信息面板失败：{exc}")

        self._tray_preview_file = None
        self._tray_info_file = None
        self._tray_suspended = False

    def restore_main_window(self) -> None:
        """从托盘挂起态唤回主窗口（托盘「打开主界面」/ 第二实例唤回共用）。

        先恢复挂起期间卸载的预览与渲染资源，再显示、抬升并激活窗口；
        Windows 桌面上补一次原生前台激活（与启动期 ``ensure_startup_foreground``
        同一守卫口径，离屏环境不调用）。
        """
        if getattr(self, "_close_in_progress", False):
            return
        if getattr(self, "_tray_suspended", False):
            try:
                self._resume_from_tray()
            except Exception as exc:  # noqa: BLE001 - 恢复失败仍显示窗口
                warning(f"从托盘恢复预览失败：{exc}")
        try:
            if self.isMinimized():
                self.showNormal()
            elif not self.isVisible():
                self.show()
        except RuntimeError:
            return
        try:
            self.raise_()
            self.activateWindow()
        except RuntimeError:
            pass
        try:
            if sys.platform != "win32":
                return
            if QApplication.platformName().strip().lower() in ("offscreen", "minimal"):
                return
            hwnd = int(self.internalWinId())
            if hwnd:
                force_foreground_window(hwnd)
        except (RuntimeError, AttributeError, TypeError) as exc:
            debug(f"从托盘唤回时原生前台激活失败：{exc}")

    def open_external_path(self, path: str) -> bool:
        """导航到外部请求的路径（资源管理器右键菜单）。

        文件夹 → 直接进入该目录；普通文件 → 进入其所在目录并选中、滚动到
        该文件。内容尚未构建（启动早期）时先暂存，由
        :meth:`initialize_deferred_content` 末尾消费。

        Args:
            path: 右键菜单传入的绝对路径（目录或文件）。

        Returns:
            已立即处理返回 True；暂存待稍后处理、路径无效或选择器不可用时
            返回 False（不抛异常）。
        """
        if not isinstance(path, str) or not path.strip():
            return False
        normalized = os.path.normpath(path)
        if not os.path.exists(normalized):
            warning(f"外部打开请求的路径不存在：{normalized}")
            return False
        if not getattr(self, "_deferred_content_ready", False):
            self._pending_external_open_path = normalized
            return False
        selector = self._file_selector
        if selector is None:
            self._pending_external_open_path = normalized
            return False
        try:
            selector.open_external_path(normalized)
        except (RuntimeError, ValueError, OSError) as exc:
            warning(f"外部打开请求导航失败：{exc}")
            return False
        return True

    def quit_from_tray(self) -> None:
        """从托盘彻底退出（幂等）：销毁托盘、关闭主窗口并结束事件循环。"""
        self._force_quit = True
        self._dispose_tray()
        try:
            self.close()
        except RuntimeError:
            pass
        # closeEvent 可能因重入保护直接 accept；无论如何都确保事件循环退出。
        app = QApplication.instance()
        if app is not None:
            try:
                app.quit()
            except RuntimeError:
                pass

    def set_layout_mode(self, mode: str) -> bool:
        """切换主界面布局模式（运行时重组，叶子组件重新挂载、不销毁重建）。

        - ``classic``：经典三栏〔选择 | 储存 | 预览+信息〕；
        - ``workspace``：预览优先〔选择 | 〔预览 / 〔储存 | 信息〕〕〕。

        说明：

        - 幂等：重复传入当前模式直接返回 True；
        - 记忆态保留：储存池内容、选择器路径、滚动位置等均在原组件实例内保留；
        - 播放挂起/恢复：切换前挂起当前视频/音频预览（快照文件、进度与
          播放态）并停止渲染，避免 MPV 原生子窗跨父级迁移导致闪烁；
          切换后待溶解过渡遮罩收尾再自动重新加载并还原进度与播放/暂停
          态（避免恢复动作与动画争抢主线程），失败时静默降级；
        - 失败兜底：迁移异常时把内容回迁旧布局并返回 False；
        - 轻量启动外壳阶段（主布局尚未构建）：仅记录偏好，由
          ``initialize_deferred_content`` 后的构建路径应用。

        Args:
            mode: 目标布局模式："classic" 或 "workspace"；非法值返回 False。

        Returns:
            bool: 是否已处于（或成功切换到）目标模式。
        """
        if mode not in ("classic", "workspace"):
            return False
        if self._main_layout is None or self._splitter_container is None:
            # 轻量启动外壳阶段：仅记录偏好，构建时应用
            self._layout_mode = mode
            self._apply_pool_layout_mode()
            return True
        if mode == self._layout_mode:
            return True

        # 播放守卫：挂起当前预览器的视频/音频播放并记录快照（具备挂起能力
        # 时切换后自动恢复；否则退回仅停止播放）
        suspended_preview = None
        if self._previewer is not None:
            try:
                current = getattr(self._previewer, "_current_preview_widget", None)
                if current is not None:
                    if hasattr(current, "suspend_for_layout_switch"):
                        current.suspend_for_layout_switch()
                        suspended_preview = current
                    elif hasattr(current, "stop_playback"):
                        current.stop_playback()
            except Exception:  # noqa: BLE001 - 播放挂起失败不阻塞切换
                suspended_preview = None

        # 底部操作栏先归位到预览器内部：随预览器一起迁移到新布局，
        # 且避免随旧布局（经典组装时槽位在旧布局内）被一并销毁
        if self._previewer is not None:
            self._previewer.set_bottom_bar_host(None)

        from layout.main_layout import MainLayout

        old_layout = self._main_layout
        new_layout = MainLayout(mode, self._splitter_container)
        container_layout = self._splitter_container.layout()
        try:
            self._migrate_zone_contents(old_layout, new_layout)
            # 容器内替换主布局（先加新、再摘旧，避免瞬时空白）
            container_layout.addWidget(new_layout)
            container_layout.removeWidget(old_layout)
        except Exception as exc:  # noqa: BLE001 - 迁移失败回滚到旧布局
            warning(f"布局切换失败（{mode}）: {exc}")
            try:
                self._migrate_zone_contents(new_layout, old_layout)
                container_layout.addWidget(old_layout)
                container_layout.removeWidget(new_layout)
            except Exception:  # noqa: BLE001 - 回滚保护
                pass
            new_layout.deleteLater()
            # 回滚后恢复被挂起的预览（文件、进度与播放态；溶解过渡收尾后执行）
            self._schedule_preview_resume_after_layout_switch(suspended_preview)
            return False

        old_layout.deleteLater()
        self._main_layout = new_layout
        self._zones = new_layout.zones
        self._layout_mode = mode
        # 储存池：三栏布局禁用 Ctrl+滚轮 缩放（New 布局保留）
        self._apply_pool_layout_mode()
        # 统一操作按钮承载方式随布局切换（经典=底部栏 / New=预览器顶栏）
        if self._previewer is not None:
            self._previewer.set_actions_mode(mode == "workspace")
            # 经典布局：底栏挂到右列槽位（信息面板下方，整列最底部）
            if mode == "classic":
                slot = new_layout.classic_action_slot()
                if slot is not None:
                    self._previewer.set_bottom_bar_host(slot)
        # 池子视图随布局切换（经典=列表 / New=网格）
        if self._file_pool is not None:
            self._file_pool.set_view_mode(
                "grid" if mode == "workspace" else "list"
            )
        # 预览器最小尺寸随模式（workspace 内容区 640×360；classic 清除）
        self._apply_previewer_minimums()
        self._refresh_panel_styles()
        # 新布局尚未经历首次布局时 QWidget 停留在默认幽灵尺寸（100×30），
        # 而迁移/挂载过程已可能触发过该尺寸下的比例应用；这里先显式赋真实
        # 几何，再应用默认比例，保证三等分 / 左 1/3 + 16:9 基于真实尺寸计算
        try:
            margins = container_layout.contentsMargins()
            inner = self._splitter_container.rect().adjusted(
                margins.left(),
                margins.top(),
                -margins.right(),
                -margins.bottom(),
            )
            if inner.width() > 0 and inner.height() > 0:
                new_layout.setGeometry(inner)
        except Exception:  # noqa: BLE001 - 几何赋值失败则退化为 resizeEvent 兜底
            pass
        # 叶子实测下限下发到新布局实例（底行最小高 / 预览器最小总高），
        # 再应用默认比例；最后聚合刷新主窗口最小尺寸
        self._apply_leaf_minimums()
        new_layout.apply_default_ratios()
        self._apply_window_minimums()
        # 迁移完成后恢复被挂起的预览（文件、进度与播放态；溶解过渡收尾后执行）
        self._schedule_preview_resume_after_layout_switch(suspended_preview)
        return True

    def _schedule_preview_resume_after_layout_switch(
        self, preview_widget: object
    ) -> None:
        """在内容过渡遮罩收尾后再恢复被挂起的预览（无遮罩时立即恢复）。

        布局切换的溶解过渡期间，立即执行恢复（load_file + play 为阻塞
        调用）会与动画争抢主线程、破坏过渡观感；故把恢复动作挂到遮罩
        ``finished`` 信号上，动画收尾后再执行。代际计数保证快速连续切换
        时只有最新一轮的遮罩回调生效（旧遮罩被打断收尾时其回调作废）。
        """
        from shiboken6 import isValid

        if preview_widget is None:
            return
        overlay = self._content_theme_overlay
        if overlay is not None and isValid(overlay) and not overlay.is_finished():
            generation = self._layout_transition_generation

            def _on_overlay_finished() -> None:
                if generation != self._layout_transition_generation:
                    return
                self._resume_preview_after_layout_switch(preview_widget)

            overlay.finished.connect(_on_overlay_finished)
            return
        self._resume_preview_after_layout_switch(preview_widget)

    @staticmethod
    def _resume_preview_after_layout_switch(widget: object) -> None:
        """布局切换收尾恢复被挂起的预览（无挂起或恢复失败时静默跳过）。"""
        if widget is None:
            return
        try:
            resume = getattr(widget, "resume_after_layout_switch", None)
            if callable(resume):
                resume()
        except Exception as exc:  # noqa: BLE001 - 恢复失败不阻塞布局切换
            warning(f"布局切换后恢复预览失败: {exc}")

    @staticmethod
    def _migrate_zone_contents(
        src_layout: "MainLayout", dst_layout: "MainLayout"  # noqa: F821 - 前向引用，运行时由 layout.main_layout 提供
    ) -> None:
        """把源布局各区域内的内容控件搬入目标布局同名区域（不销毁组件）。"""
        for key, src_zone in src_layout.zones.items():
            dst_zone = dst_layout.zones.get(key)
            if dst_zone is None:
                continue
            src_zone_layout = src_zone.layout()
            while src_zone_layout.count():
                item = src_zone_layout.takeAt(0)
                widget = item.widget()
                if widget is None:
                    continue
                widget.setParent(dst_zone)
                dst_zone.layout().addWidget(widget)

    def set_custom_background_image(self, path: str) -> bool:
        """设置自定义背景图片（转发给背景层组件）。

        已处于「图像」模式且该层在屏时，更换图片也走 450ms 交叉淡入
        （切前抓旧图帧、切换后淡出）；其余场景（层未显示，如云母→图像
        首次切入）只更新内容，由 ``set_background_mode`` 的过渡统一覆盖，
        不会双重过渡。

        Args:
            path: 图片文件绝对路径。

        Returns:
            bool: 加载成功返回 True；路径无效或无法解码返回 False
            （组件内部已记录日志并回退纯色兜底）。
        """
        layer = getattr(self, "_custom_background", None)
        if layer is None:
            return False
        backdrop = None
        if (
            getattr(self, "_background_mode", "mica") == "image"
            and self._can_transition_background()
        ):
            try:
                if not layer.isHidden() and layer.has_image():
                    backdrop = self._prepare_background_frame()
            except Exception:  # noqa: BLE001 - 判定失败按不做过渡处理
                backdrop = None
        changed = bool(layer.set_image(path))
        if changed and backdrop is not None:
            self._start_background_transition(backdrop)
        return changed

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
        except Exception as exc:
            debug(f"设置背景层模糊度失败：{exc}")
        try:
            layer.set_opacity(opacity_value)
        except Exception as exc:
            debug(f"设置背景层透明度失败：{exc}")
    
    # ---- 窗口事件处理 ----
    
    def resizeEvent(self, event: QResizeEvent) -> None:
        """窗口大小改变事件（P0 节流：仅转发可见背景层）。

        拖拽期间 Win32 每像素产生数十个 resize，三层全量
        ``handle_window_resize`` 会造成 3 倍 ``update()`` 风暴。
        三背景层互斥可见，仅转发可见层即可保持交互态快路，
        不可见层跳过（其 settle 定时器与缓存不受影响）。

        Args:
            event: Qt 缩放事件。
        """
        super().resizeEvent(event)
        # 通知 MicaBackgroundWidget 刷新（仅可见时）
        if self._mica_background is not None:
            try:
                if self._mica_background.isVisible():
                    self._mica_background.handle_window_resize()
            except Exception as exc:
                debug(f"云母背景 resize 通知失败：{exc}")
        # 通知自定义图像背景层刷新（进入交互态，settle 后重建平滑缓存）
        if self._custom_background is not None:
            try:
                if self._custom_background.isVisible():
                    self._custom_background.handle_window_resize()
            except Exception as exc:
                debug(f"自定义背景 resize 通知失败：{exc}")
        # 通知简约背景层刷新（渐变固定于客户区，按新尺寸重绘）
        minimalist = getattr(self, "_minimalist_background", None)
        if minimalist is not None:
            try:
                if minimalist.isVisible():
                    minimalist.handle_window_resize()
            except Exception as exc:
                debug(f"简约背景 resize 通知失败：{exc}")

    def moveEvent(self, event: QMoveEvent) -> None:
        """窗口移动事件"""
        super().moveEvent(event)
        # 通知 MicaBackgroundWidget 刷新
        if self._mica_background is not None:
            self._mica_background.handle_window_move()
        # 注意：不把移动事件转发给自定义图像层与简约层——图像/渐变固定于
        # 窗口客户区、不随窗口屏幕位置偏移或重新裁切（这是与云母按屏幕位置
        # 裁切的核心差异），无需刷新；组件的 handle_window_move 亦为空操作。


def _apply_theme_palette(widget: QWidget) -> None:
    """把当前主题色写入 *widget* 的调色板（全角色，而非仅 Window），并注册
    同色 QSS 背景片段。

    应用主题只靠 QSS 实现、未设应用级调色板；本函数用于纯色背景顶层窗口
    的根容器。只覆盖 ``Window`` 角色时，未被打上 QSS 的后代（QScrollArea
    viewport、尚未注册的 QLabel 等）仍会回落到系统调色板——系统深色下
    浅色主题就会闪现深底白字。补齐 Base/Text/WindowText 等角色后，
    「样式下发前的空窗帧」也能呈现当前主题色。

    注意（调色板不抗 QSS 重刷）：任何 ``setStyleSheet`` 下发都会把控件调色板
    还原为「上次应用样式时」的值——仅靠 ``setPalette`` 的窗口背景在下发后
    仍停留在旧主题（实测：设置窗口切到浅色后根容器仍是深色 G1，卡片等浅色
    QSS 全部画在深底上；许可证窗口同理）。因此这里同时注册
    ``background-color`` 片段，由下发到控件自身的样式片段主导稳态绘制；
    调色板仅兜底首帧前的空窗帧。

    Args:
        widget: 目标根容器（通常为窗口的 central widget）。
    """
    palette = widget.palette()
    surface = tm.surface
    text = tm.text
    palette.setColor(QPalette.Window, surface)
    palette.setColor(QPalette.Base, surface)
    palette.setColor(QPalette.AlternateBase, surface)
    palette.setColor(QPalette.Button, surface)
    palette.setColor(QPalette.WindowText, text)
    palette.setColor(QPalette.Text, text)
    palette.setColor(QPalette.ButtonText, text)
    widget.setPalette(palette)
    # 稳态背景由 QSS 片段主导（重刷安全，见 docstring）；窗口销毁后
    # 片段随 weakref 注册项自动回收。
    register_widget_qss(widget, f"background-color: {tm.qss_color(surface)};")


class SettingsWindow(_FramelessNativeEffectsMixin, FramelessMainWindow):
    """
    设置窗口 — 主窗口的 owned 子窗口，跟随主窗口背景模式

    - 主窗口处于 ``mica`` 模式：叠加一层 CPU 光栅 Mica 视图，**借用**主窗口
      已烘焙的整块虚拟桌面视口层，按设置窗口自身的屏幕矩形取子矩形绘制。
      不新建壁纸源、不启动烘焙线程、不创建第二个 OpenGL 上下文。
    - ``image`` / ``minimalist`` 模式：隐藏共享视图，使用与 styled 弹窗
      DialogContent 一致的 ``tm.surface`` 纯色兜底背景。

    点击主窗口标题栏的设置按钮后弹出；以主窗口为 parent（Windows owned
    窗口）——始终相对主窗口置顶，主窗口关闭时设置窗口一并关闭销毁。
    """

    def __init__(self, parent=None):
        # 先初始化属性，防止父类初始化期间触发的事件访问未定义属性
        self._mica_background = None  # 设置窗口自身不是主窗口；保留属性做鸭子类型防御
        self._mica_view = None  # 共享主窗口视口层的 CPU 背景（仅 mica 模式显示）
        self._settings_background_mode = ""
        self._host_signal_connected = False
        self._root = None
        self._content_container = None
        self._overlay_layout = None
        self._title_label = None
        self._close_btn = None
        # ── 呈现/关闭过渡状态（见 present / closeEvent） ──
        self._presented = False  # present() 只执行一次（避免重复 show 重播动画）
        self._revealed = False  # 真实窗口是否已从透明态揭开
        self._open_start_timer = None
        self._open_snapshot_layer = None
        self._open_target_geometry = None
        self._open_animation_active = False
        self._open_animation_enabled = False
        self._open_input_blocker = None
        self._close_fade = None
        self._close_fade_timer = None
        self._close_input_blocker = None
        self._close_animation_active = False
        self._skip_close_animation = False
        self._close_pre_cleanup_done = False
        self._close_resource_cleanup_done = False

        super().__init__(parent)

        self.setWindowTitle("设置")
        self.setMinimumSize(700, 400)
        self.resize(700, 500)

        # 定位：owned 窗口不显式定位时由 Windows 级联放置（落在屏幕右下），
        # 这里居中到宿主主窗口；无宿主时回退到鼠标所在屏幕中心。
        self._center_on_host()

        # 顶层窗口自身的背景也必须设成主题色：Qt 在首次绘制完成前会用
        # 顶层窗口的 palette 兜底填充，若沿用系统默认 palette（深色下是
        # #1e1e1e、浅色下接近纯白），就会出现「打开时闪一下」的观感。
        # 参见 _apply_theme_palette 的说明：QPalette::Window 是正式绘制前
        # 的底层颜色，必须与主题一致。
        _apply_theme_palette(self)
        self.setAutoFillBackground(True)

        # 中央部件用纯 QWidget，保留本地无边框基类原生窗口特性；
        # tm.surface 不透明纯色背景（styled 弹窗同款），同时作为 mica 视图
        # 未启用/被隐藏时的兜底背景。
        self._root = QWidget(self)
        self.setCentralWidget(self._root)
        _apply_theme_palette(self._root)
        self._root.setAutoFillBackground(True)

        # 叠层布局：内容层在上，共享 Mica 背景视图在下方（按需创建）。
        # 不把 Mica 视图放进内容容器，才能覆盖标题栏区域。
        self._overlay_layout = QGridLayout(self._root)
        self._overlay_layout.setContentsMargins(0, 0, 0, 0)
        self._overlay_layout.setSpacing(0)
        self._content_container = QWidget(self._root)
        # 内容容器必须显式透明：Qt 会给带样式表父级的子 QWidget 置
        # WA_StyledBackground，默认会用 palette.Window 铺一层 tm.surface，
        # 把下方的共享 Mica 完全盖住（表现为设置页仍是纯色）。
        register_widget_qss(
            self._content_container, "background: transparent; border: none;"
        )
        self._overlay_layout.addWidget(self._content_container, 0, 0)

        # 主布局建在内容容器上
        layout = QVBoxLayout(self._content_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏（仅关闭按钮）
        self._create_title_bar(layout)

        # 设置内容区
        from layout.settings_layout import SettingsLayout  # 延迟导入（启动提速）

        self._settings_layout = SettingsLayout(self._content_container, host_window=self)
        layout.addWidget(self._settings_layout)

        # 监听主题变化以刷新背景和按钮颜色
        tm.theme_changed.connect(self._on_theme_changed)
        # 跟随主机背景模式：仅 mica 时启用共享层；创建时先按当前模式同步一次。
        self._connect_host_background()

    def _center_on_host(self) -> None:
        """居中到宿主主窗口；无宿主时回退到鼠标所在屏幕中心。

        注意：必须按**真实外框尺寸**（``frameGeometry``）计算。构造期
        ``resize(700, 500)`` 只是逻辑尺寸，原生扩展帧会让实际外框变成
        707×532；若用 ``width()/height()`` 居中，show 后窗口会再上移/右移
        十几像素（表现为「从下往上抖一下」）。
        """
        host = self.parentWidget()
        try:
            frame = self.frameGeometry()
            frame_w = max(1, frame.width())
            frame_h = max(1, frame.height())
            # 外框相对 widget 左上角的偏移（扩展帧会带来负边距）。
            off_x = frame.x() - self.x()
            off_y = frame.y() - self.y()
        except RuntimeError:
            return
        if host is not None and host.isVisible():
            geo = host.geometry()
            x = geo.x() + (geo.width() - frame_w) // 2
            y = geo.y() + (geo.height() - frame_h) // 2
            self.move(x - off_x, y - off_y)
            return
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        geo = screen.geometry()
        x = geo.x() + (geo.width() - frame_w) // 2
        y = geo.y() + (geo.height() - frame_h) // 2
        self.move(x - off_x, y - off_y)

    # ── 呈现 / 缩放淡入与关闭淡出 ────────────────────────────────────

    @staticmethod
    def _window_animation_supported() -> bool:
        """当前平台是否支持真实窗口过渡（offscreen/测试不播）。"""
        try:
            platform_name = QApplication.platformName().strip().lower()
        except Exception:  # noqa: BLE001 - 平台查询失败按不支持处理
            return False
        return platform_name not in ("offscreen", "minimal")

    def _window_animation_enabled(self) -> bool:
        """设置窗口淡入淡出是否启用（平台支持 + 用户动画开关）。"""
        if not self._window_animation_supported():
            return False
        try:
            app = QApplication.instance()
            manager = getattr(app, "settings_manager", None) if app is not None else None
            return is_animation_enabled(
                "settings_window", default=True, settings_manager=manager
            )
        except Exception as exc:  # noqa: BLE001 - 设置读取失败按默认开启
            debug(f"读取设置窗口动画开关失败（按开启处理）：{exc}")
            return True

    def present(self) -> None:
        """显示设置窗口。

        关键约束：**窗口第一次对用户可见时，几何与内容都必须已经是终态**。

        踩过的坑：
        - 屏外 ``(-10000,-10000)`` 先 show 再移回主屏：DWM 会按另一块屏幕
          计算扩展帧（705×532），移回后才异步重算成 707×532，导致「完全
          弹出后又向右扩一小段」。
        - 可见后再 ``raise_``/``activateWindow``：会再触发 1px 客户区微调。
        - ``show()`` 之后才绘制首帧：DWM 会先用扩展帧的浅色玻璃底板填充
          客户区，形成一帧灰白（深色主题下非常明显），表现为「闪白/卡顿」。
          实测该白帧亮度 ~122（正常深色内容 ~29），持续约 33ms。

        因此这里：在最终位置完成主题同步与样式下发，再以 ``opacity=0``
        显示，让 Qt 在透明状态下完成首帧；随后在不移动窗口的前提下恢复
        不透明。动画开启时，首帧完成后先挂窗口内快照层，再让窗口与快照
        同时出现，由快照层完成 104% → 100% 的内容收缩（见
        :meth:`_start_open_animation`）。
        """
        if self._presented:
            self.raise_()
            self.activateWindow()
            return
        self._presented = True
        # offscreen/minimal（测试/无显示器）：保持即时显示语义。
        if not self._window_animation_supported():
            self._center_on_host()
            self.show()
            self._revealed = True
            return
        self._open_animation_enabled = self._window_animation_enabled()
        try:
            # 关键：**不要碰 windowOpacity，也不要移动窗口**。
            #
            # 实测三条硬约束（150% DPI）：
            # 1. 先移到屏外 (-10000,-10000) 再移回：DWM 按另一块屏幕算扩展帧，
            #    移回后异步重算成 707×532 → 可见后仍 resize。
            # 2. show 之后再 move/raise/activate：触发 1px 客户区修正 → 抖动。
            # 3. 切换 windowOpacity（哪怕 0→1）：同样触发 1px 位移 + 707 重算。
            #
            # 另外：``show()`` 之前先完成主题同步与全量样式下发（首次约
            # 135ms），否则窗口已可见但内容还没画完，会露出空白。
            #
            # 实测排除项（不要重复尝试）：
            # - ``repaint()`` 在隐藏窗口上不会真正绘制（PrintWindow 抓到纯黑）。
            # - ``root.render()`` + 覆盖层会把未就绪的 Mica 渲染成白图贴在最上层，
            #   导致整窗持续白屏 3 秒。
            # - ``WM_ERASEBKGND`` 在设置窗口打开时一次都没到达，拦截它无效。
            # - ``DWMWA_TRANSITIONS_FORCEDISABLED``：禁用 DWM 淡入后，Qt 首帧
            #   尚未绘制的白色表面会被瞬间完全暴露，实测 3/3 次纯白（255），
            #   比不禁用更严重。
            #
            # 正确做法：``show()`` 前设 opacity=0，让窗口在透明状态下完成首帧
            # 绘制，再恢复不透明。实测 8/8 次无白帧。
            self.setWindowOpacity(0.0)
            self._center_on_host()
            self._prepare_before_show()
            self.show()
            # 首帧在透明状态下完成后再决定：直接揭开，或播放内容收缩动画。
            # 注意：这里不能提前把 ``_revealed`` 置真，否则动画分支会被
            # ``_start_open_animation`` 的状态守卫当成已完成而跳过。
            QTimer.singleShot(32, self._reveal_after_first_frame)
        except Exception as exc:  # noqa: BLE001 - 过渡失败必须退回可用状态
            debug(f"设置窗口呈现失败，退回普通显示：{exc}")
            self._cancel_open_animation()
            self._reveal_now()

    def _reveal_after_first_frame(self) -> None:
        """首帧绘制完成后揭开窗口，或启动内容收缩动画。

        ``present()`` 在 ``show()`` 前把窗口设为 ``opacity=0``：窗口以透明
        状态完成首次布局与绘制，避免 Qt 还没画好内容时白色表面被 DWM 合成
        出来（实测这是「打开闪白」的真正来源）。

        - 动画开启且时长 > 0：先让出一拍，等首帧与原生边框状态稳定后由
          :meth:`_start_open_animation` 挂快照层，再恢复不透明。
        - 否则：直接恢复不透明并标记揭开。

        若窗口已在关闭流程中则跳过。
        """
        if getattr(self, "_skip_close_animation", False):
            return
        if getattr(self, "_close_animation_active", False):
            return
        try:
            if not self.isVisible():
                return
        except RuntimeError:
            return
        if self._open_animation_enabled and int(SETTINGS_WINDOW_OPEN_MS) > 0:
            self._schedule_open_animation()
            return
        try:
            self.setWindowOpacity(1.0)
        except RuntimeError:
            pass
        self._revealed = True

    def _prime_first_frame(self) -> None:
        """（已废弃）保留入口以兼容旧调用，当前不做任何事。

        历史尝试与实测结论：

        - ``repaint()``：隐藏窗口上不会真正绘制（PrintWindow 抓到纯黑）。
        - ``root.render()`` + 覆盖层：会把尚未就绪的 Mica 渲染成白图贴到最
          上层，导致整窗持续白屏数秒——实测确认必须移除。
        - ``WM_ERASEBKGND``：设置窗口打开时该消息一次都没到达，拦截无效。

        因此现在把"准备首帧"简化为：在 ``show()`` 前完成主题同步与样式
        下发（见 :meth:`_prepare_before_show`），不再做任何预渲染。
        """
        return

    def _schedule_open_animation(self) -> None:
        """下一事件循环拍起播快照动画。

        ``show()`` 已同步完成首次布局；这里只让出一拍，让首帧绘制与原生
        边框状态先稳定，再抓快照，避免抓到半成品内容。
        """
        timer = self._open_start_timer
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._start_open_animation)
            self._open_start_timer = timer
        timer.start(0)

    def _start_open_animation(self) -> None:
        """抓最终内容快照，在**固定几何**的窗口内做轻微收缩弹出。

        窗口几何全程不动：既没有 DWM 边框/阴影后补，也不存在 150% DPI 下
        左右边缘落在半个物理像素、Qt 分别取整导致的横向抖动（实测中心会
        左右摆 0.5~1.5 物理像素）。

        缩放只发生在绘制期，且起始比例 >1，收缩过程中四周不会露出底色或
        重排后的真实内容；末帧与真实内容逐像素一致，撤层无跳变。
        """
        if (
            self._revealed
            or self._open_animation_active
            or self._close_animation_active
            or self._skip_close_animation
        ):
            return
        duration = max(0, int(SETTINGS_WINDOW_OPEN_MS))
        scale = max(1.0, float(SETTINGS_WINDOW_OPEN_SCALE))
        try:
            if not self.isVisible():
                self._reveal_now()
                return
            # 窗口已在 present() 中定位到最终位置；这里绝不能再 move，
            # 否则会在窗口可见后触发 DWM 扩展帧重算（1px 抖动）。
            target = QRect(self.geometry())
        except RuntimeError:
            return
        if target.isEmpty() or duration <= 0:
            self._reveal_now()
            return
        self._open_target_geometry = QRect(target)
        layer = None
        try:
            self.repaint()
            snapshot = self.grab()
            if snapshot.isNull():
                self._reveal_now()
                return
            # 按 Win32 真实客户区定位/裁剪快照：grab() 含 DWM 扩展帧覆盖
            # 的边缘，直接铺满 widget 会在揭开时产生约 1px 的内容位移。
            layer_rect, source_rect = client_snapshot_geometry(self, snapshot)
            layer = SettingsWindowSnapshotLayer(
                snapshot, source_rect, duration, scale, parent=self._root
            )
            layer.setGeometry(layer_rect)
            layer.show()
            layer.raise_()
            layer.setFocus(Qt.OtherFocusReason)
            self._open_snapshot_layer = layer
            layer.finished.connect(self._on_open_animation_finished)

            # 先在透明状态下把快照层的第一帧（104%）画进后备缓冲，再恢复
            # 不透明；否则 DWM 可能先合成一帧未缩放的实时内容，表现为
            # 「100% → 104% → 收缩」的闪跳。
            layer.repaint()
            self.repaint()
            # 窗口直接以最终几何、完全不透明出现；只有内容做收缩。
            # 注意：不要在这里 ``raise_``/``activateWindow``——窗口已可见，
            # 再调用会触发客户区 1px 微调（横向抖动回归）。
            self.setWindowOpacity(1.0)
            self._open_animation_active = True
            layer.start()
        except Exception as exc:  # noqa: BLE001 - 动画失败直接显示
            debug(f"设置窗口打开动画创建失败，直接显示：{exc}")
            self._open_animation_active = False
            if layer is not None:
                try:
                    layer.finished.disconnect(self._on_open_animation_finished)
                except (RuntimeError, TypeError):
                    pass
                try:
                    layer.hide()
                    layer.close()
                    layer.deleteLater()
                except RuntimeError:
                    pass
            self._open_snapshot_layer = None
            self._reveal_now()

    def _on_open_animation_finished(self) -> None:
        """缩放完成：撤掉快照层（幂等）。"""
        if self._revealed:
            return
        self._reveal_now()

    def _remove_open_snapshot_layer(self) -> None:
        """销毁窗口内快照层（幂等）。

        不主动 ``disconnect``：本方法可能在 ``finished`` 信号发射过程中被
        调用，Qt 会对「发射中断连」发出警告；``_revealed`` 守卫已足够防止
        重入，层销毁后连接也会随之释放。
        """
        layer = self._open_snapshot_layer
        self._open_snapshot_layer = None
        if layer is None:
            return
        try:
            layer.hide()
            layer.close()
            layer.deleteLater()
        except RuntimeError:
            pass

    def _stop_open_start_timer(self) -> None:
        """停止打开动画起播定时器（幂等）。"""
        timer = self._open_start_timer
        self._open_start_timer = None
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                pass

    def _cancel_open_animation(self) -> None:
        """取消进行中的进入过渡（关闭/异常路径；幂等）。"""
        self._open_animation_active = False
        self._open_animation_enabled = False
        self._stop_open_start_timer()
        self._remove_open_snapshot_layer()
        self._open_target_geometry = None

    def _reveal_now(self) -> None:
        """撤掉快照层并揭开真实窗口（幂等）。

        窗口几何全程不动，因此这里不做 ``setGeometry``；末帧快照与真实
        内容逐像素一致，直接撤层即可。
        """
        if self._revealed:
            return
        if self._close_animation_active or self._skip_close_animation:
            return
        self._revealed = True
        self._open_animation_active = False
        self._open_animation_enabled = False
        self._stop_open_start_timer()
        self._open_target_geometry = None
        try:
            self.setWindowOpacity(1.0)
        except RuntimeError:
            self._remove_open_snapshot_layer()
            return
        if self._open_snapshot_layer is not None:
            # 让窗口先绘制一帧（快照层仍盖着），下一拍再撤层。
            QTimer.singleShot(0, self._finish_reveal)

    def _finish_reveal(self) -> None:
        """撤掉快照层（最终揭开；幂等）。

        这里不调用 ``raise_``/``activateWindow``：窗口已经可见，再次置顶会
        触发客户区 1px 微调，正是本次动画要避开的横向抖动。
        """
        self._remove_open_snapshot_layer()

    def _host_background_mode(self) -> str:
        """读取宿主主窗口当前背景模式；无宿主/非主窗口时返回空串。"""
        host = self.parentWidget()
        getter = getattr(host, "get_background_mode", None)
        if not callable(getter):
            return ""
        try:
            return str(getter())
        except Exception:  # noqa: BLE001 - 宿主处于销毁流程按非 mica 处理
            return ""

    def _connect_host_background(self) -> None:
        """订阅宿主背景模式变化，并按当前模式同步一次设置窗口背景。"""
        host = self.parentWidget()
        signal = getattr(host, "background_mode_changed", None)
        if signal is not None:
            try:
                signal.connect(self._on_host_background_mode_changed)
                self._host_signal_connected = True
            except (TypeError, RuntimeError) as exc:
                debug(f"设置窗口订阅背景模式失败：{exc}")
        self._on_host_background_mode_changed(self._host_background_mode())

    def _on_host_background_mode_changed(self, mode: str) -> None:
        """宿主背景模式变化：仅 mica 显示共享层，image/minimalist 恢复纯色。"""
        self._settings_background_mode = str(mode or "")
        if self._settings_background_mode == "mica":
            if not self._ensure_settings_mica_view():
                return
            view = self._mica_view
            if view is None:
                return
            try:
                view.sync_theme()
                view.show()
                view.lower()
                # 未显示的设置窗口不要提前取 winId（会强制原生化并打断
                # 无边框基类的首个 WinIdChange 路径）；首次显示时由
                # showEvent / resizeEvent 做几何同步。
                if self.isVisible():
                    view.handle_window_resize()
                view.update()
            except (RuntimeError, AttributeError) as exc:
                debug(f"设置窗口 Mica 背景同步失败：{exc}")
            return
        # 非 mica：隐藏共享层，由根容器的 tm.surface 纯色兜底。
        view = self._mica_view
        if view is not None:
            try:
                view.hide()
            except RuntimeError:
                self._mica_view = None

    def _ensure_settings_mica_view(self) -> bool:
        """惰性创建共享主窗口视口层的 CPU 背景视图。

        Returns:
            bool: 视图已可用返回 True；宿主没有可借用的 Mica 材质时 False。
        """
        if self._mica_view is not None:
            return True
        host = self.parentWidget()
        host_bg = getattr(host, "_mica_background", None)
        ensure = getattr(host_bg, "_ensure_mica_material", None)
        if not callable(ensure):
            return False
        try:
            source = ensure()
        except Exception as exc:  # noqa: BLE001 - 设置窗口打开不应因 Mica 失败
            debug(f"设置窗口获取主窗口 Mica 材质失败：{exc}")
            return False
        if source is None:
            return False

        fixed = fixed_mica_params()
        dark = tm.is_dark_theme()
        try:
            view = make_mica_background(
                self._root,
                blur_radius=fixed["blur_radius"],
                surface_color="#000000" if dark else "#FFFFFF",
                luminosity=0.65 if dark else 0.85,
                contrast=fixed["contrast"],
                saturation=fixed["saturation"],
                tint_opacity=fixed["tint_opacity"],
                layer_source=source,
                force_cpu=True,  # 绝不在设置窗口新建第二个 GL 上下文
            )
        except Exception as exc:  # noqa: BLE001 - 降级为纯色背景
            debug(f"设置窗口创建共享 Mica 背景失败：{exc}")
            return False

        view.setObjectName("SettingsMicaBackground")
        view.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        view.setFocusPolicy(Qt.NoFocus)
        self._overlay_layout.addWidget(view, 0, 0)
        view.lower()
        self._mica_view = view
        try:
            # 立即建立借用材质并请求源材质刷新（源已在烘焙时幂等合并）。
            view._ensure_mica_material()
            view.refresh_background()
        except Exception as exc:  # noqa: BLE001 - 背景异步失败不影响设置页
            debug(f"设置窗口启动共享 Mica 刷新失败：{exc}")
        return True

    def _dispose_settings_mica_view(self) -> None:
        """释放共享层材质订阅（源材质属于主窗口，绝不能在此 dispose）。"""
        view = self._mica_view
        self._mica_view = None
        if view is None:
            return
        mica = getattr(view, "_mica", None)
        if mica is not None:
            try:
                mica.dispose()
            except (RuntimeError, AttributeError) as exc:
                debug(f"设置窗口释放 Mica 材质失败：{exc}")
        try:
            view.hide()
        except RuntimeError:
            pass

    def _create_title_bar(self, parent_layout: QVBoxLayout) -> None:
        """创建标题栏（仅标题文字和关闭按钮）"""
        header = QFrame()
        header.setObjectName("SettingsTitleBar")
        header.setFixedHeight(48)
        register_widget_qss(header,("""
            #SettingsTitleBar {
                background-color: transparent;
            }
        """))
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 8, 16, 8)
        header_layout.setSpacing(0)

        # 标题文字
        self._title_label = QLabel("设置")
        register_widget_qss(self._title_label,(
            f'font-size: 14px; font-weight: 600; color: {tm.text.name()};'
        ))
        header_layout.addWidget(self._title_label)
        header_layout.addStretch()

        # 关闭按钮
        self._close_btn = StyledButton("", variant="ghost", size="sm")
        self._close_btn.setFixedSize(32, 32)
        self._close_btn.setText("✕")
        register_widget_qss(self._close_btn,(self._close_button_style()))
        # 弹窗模态期间仍放行 ✕（与主窗口标题栏一致，见 modal_guard）
        self._close_btn.setProperty(MODAL_PASSTHROUGH_PROPERTY, True)
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
        """窗口显示/重新显示时刷新主题样式。

        注意：这里**不能**做耗时操作。首次 ``apply_app_stylesheet()`` 实测
        阻塞 135ms，若放在 showEvent 里，窗口已交给 DWM 但内容还没画出来，
        用户会看到一帧空白（深色主题下就是闪白/卡顿）。

        因此主题同步与全量样式下发都提前到 :meth:`present` 的 ``show()``
        之前完成；这里只补发显示后才就绪的轻量项。
        """
        super().showEvent(event)
        # 共享层取样几何需要窗口已显示（此前不取 winId，避免提前原生化）。
        view = getattr(self, "_mica_view", None)
        if view is not None and not view.isHidden():
            try:
                view.handle_window_resize()
            except (RuntimeError, AttributeError):
                pass

    def _prepare_before_show(self) -> None:
        """在 ``show()`` 之前完成主题同步与全量样式下发。

        这两步在首次打开时合计约 135ms（``apply_app_stylesheet`` 的首次
        全量重下发）。必须在窗口可见前做完，否则会阻塞首帧、露出空白。
        """
        try:
            self._sync_theme()
        except Exception as exc:  # noqa: BLE001 - 主题同步失败不应阻塞显示
            debug(f"设置窗口显示前同步主题失败：{exc}")
        try:
            apply_app_stylesheet()
        except Exception as exc:  # noqa: BLE001 - 样式下发失败不应阻塞显示
            debug(f"设置窗口显示前下发样式失败：{exc}")

    def _sync_theme(self) -> None:
        """强制刷新当前主题下的所有样式"""
        # 顶层窗口兜底背景（首帧/QSS 未覆盖区域的底色）
        _apply_theme_palette(self)
        self.setAutoFillBackground(True)
        # 纯色背景（tm.surface 随主题变化）
        if self._root is not None:
            _apply_theme_palette(self._root)
        # 共享 Mica 背景：仅更新本地兜底底色；新层由源材质 layer_changed 交付。
        view = getattr(self, "_mica_view", None)
        if view is not None:
            try:
                view.sync_theme()
                view.update()
            except (RuntimeError, AttributeError) as exc:
                debug(f"设置窗口同步 Mica 主题失败：{exc}")
        # 标题栏文字
        if self._title_label is not None:
            register_widget_qss(self._title_label,(
                f'font-size: 14px; font-weight: 600; color: {tm.text.name()};'
            ))
        # 关闭按钮
        if self._close_btn is not None:
            register_widget_qss(self._close_btn,(self._close_button_style()))
        # 设置内容区（侧边栏 + 卡片）
        if hasattr(self, '_settings_layout') and self._settings_layout is not None:
            self._settings_layout.refresh_theme()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """窗口缩放后让共享 Mica 背景按新客户区重新取样（不重烘焙）。"""
        super().resizeEvent(event)
        # 打开动画期间窗口几何不变，但客户区仍可能在首帧微调：让快照层
        # 跟随真实可见客户区，避免边缘露出。
        layer = getattr(self, "_open_snapshot_layer", None)
        if layer is not None:
            try:
                rect, _src = client_snapshot_geometry(self, layer.snapshot)
                layer.setGeometry(rect)
                layer.raise_()
            except (RuntimeError, AttributeError):
                pass
        view = getattr(self, "_mica_view", None)
        if view is not None and view.isVisible():
            try:
                view.handle_window_resize()
            except (RuntimeError, AttributeError):
                pass

    def moveEvent(self, event: QMoveEvent) -> None:
        """窗口移动后更新共享层取样位置（层覆盖整块虚拟桌面，O(1) 重绘）。"""
        super().moveEvent(event)
        view = getattr(self, "_mica_view", None)
        if view is not None and view.isVisible():
            try:
                view.handle_window_move()
            except (RuntimeError, AttributeError):
                pass

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
        """设置窗口关闭时触发暂存生命周期，并按需播放固定尺寸淡出。

        右上角 ``✕`` 等同于「取消」：丢弃暂存并恢复界面至原始状态。

        播放关闭过渡时：
        1. 先跑原有暂存/外观清理；
        2. 保持 Mica 与真实窗口外观不变，启动 ``windowOpacity 1→0`` 淡出；
        3. 淡出结束后再释放 Mica / 断开宿主信号并真正 ``close()``
           （``WA_DeleteOnClose`` 销毁）。

        主窗口退出、offscreen/测试、动画关闭时仍走同步关闭，不拖慢退出。
        """
        # 设置窗口拥有的弹窗（危险确认等）随宿主一起关闭，避免残留顶层窗口。
        try:
            close_active_dialogs(self)
        except Exception as exc:  # noqa: BLE001 - 关闭路径绝不被弹窗拖累
            debug(f"关闭设置窗口弹窗失败：{exc}")
        try:
            get_modal_guard().pop_owner(self)
        except Exception:  # noqa: BLE001 - 无 QApplication 的极端场景
            pass
        if self._skip_close_animation:
            # 淡出收尾后的真实关闭：只接受事件，不再重复清理。
            self._cancel_open_animation()
            self._run_close_resource_cleanup_once()
            event.accept()
            super().closeEvent(event)
            return
        if self._close_animation_active:
            # 关闭过渡已在播放：忽略重复关闭请求（收尾回调会自行 close）。
            event.ignore()
            return

        self._run_close_pre_cleanup_once()
        if not self._can_animate_close():
            self._cancel_open_animation()
            self._run_close_resource_cleanup_once()
            event.accept()
            super().closeEvent(event)
            return

        event.ignore()
        self._cancel_open_animation()
        if not self._start_close_fade():
            self._finish_close_animation()

    # ── 关闭清理 / 收尾 ─────────────────────────────────────────────

    def _run_close_pre_cleanup_once(self) -> None:
        """执行关闭前暂存钩子（幂等；淡出开始之前调用）。"""
        if self._close_pre_cleanup_done:
            return
        self._close_pre_cleanup_done = True
        try:
            layout = getattr(self, "_settings_layout", None)
            if layout is not None and hasattr(layout, "on_host_closing"):
                layout.on_host_closing()
        except Exception as exc:  # noqa: BLE001 - 关闭路径绝不抛出
            debug(f"设置窗口关闭钩子失败（暂存缓存可能未清理）：{exc}")

    def _run_close_resource_cleanup_once(self) -> None:
        """释放共享层订阅与宿主信号（幂等；淡出结束/立即关闭前调用）。"""
        if self._close_resource_cleanup_done:
            return
        self._close_resource_cleanup_done = True
        # 先解除共享层订阅并释放借用材质，再让窗口树析构（QPixmap 必须在
        # Qt 对象仍有效时清理；源材质属于主窗口，dispose 内部只断连不销毁）。
        try:
            self._dispose_settings_mica_view()
        except Exception as exc:  # noqa: BLE001 - 关闭路径绝不抛出
            debug(f"设置窗口释放共享背景失败：{exc}")
        if self._host_signal_connected:
            host = self.parentWidget()
            signal = getattr(host, "background_mode_changed", None)
            if signal is not None:
                try:
                    signal.disconnect(self._on_host_background_mode_changed)
                except (TypeError, RuntimeError):
                    pass
            self._host_signal_connected = False

    def _can_animate_close(self) -> bool:
        """当前是否应播放关闭淡出过渡。"""
        if self._skip_close_animation or self._close_animation_active:
            return False
        # 关闭淡出时长 <= 0：同步关闭（当前默认）。
        if int(SETTINGS_WINDOW_CLOSE_MS) <= 0:
            return False
        # 只有经 present() 正常打开的窗口才播关闭过渡；测试/调试中直接
        # show() 的窗口保持旧同步关闭语义。
        if not self._presented:
            return False
        # 进入过渡尚未揭开真实窗口时直接关闭：此时窗口本身不可见，
        # 再播淡出没有意义。
        if not self._revealed:
            return False
        if not self._window_animation_enabled():
            return False
        try:
            if QApplication.closingDown():
                return False
        except Exception:  # noqa: BLE001 - 退出期查询失败按可动画处理
            pass
        try:
            if not self.isVisible():
                return False
        except RuntimeError:
            return False
        host = self.parentWidget()
        if host is not None and getattr(host, "_close_in_progress", False):
            # 主窗口正在退出：owned 窗口随宿主销毁，不播过渡、不拖延退出。
            return False
        return True

    def _start_close_fade(self) -> bool:
        """启动固定尺寸淡出；成功返回 True（几何全程不变）。"""
        if self._skip_close_animation or self._close_animation_active:
            return False
        duration = max(0, int(SETTINGS_WINDOW_CLOSE_MS))
        if duration <= 0:
            return False
        fade = None
        try:
            fade = QPropertyAnimation(self, b"windowOpacity", self)
            fade.setDuration(duration)
            fade.setStartValue(max(0.0, min(1.0, float(self.windowOpacity()))))
            fade.setEndValue(0.0)
            fade.setEasingCurve(QEasingCurve.Type.InCubic)
            fade.finished.connect(self._on_close_fade_finished)
            self._close_fade = fade
            self._close_animation_active = True
            self._close_input_blocker = self._install_transition_input_blocker()
            # 兜底：个别平台/合成器可能不派发 finished；时间到后强制收尾，
            # 绝不让设置窗口卡在淡出中途无法关闭。
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._on_close_fade_timeout)
            timer.start(duration + 200)
            self._close_fade_timer = timer
            fade.start()
            return True
        except Exception as exc:  # noqa: BLE001 - 动画失败按普通关闭处理
            debug(f"设置窗口淡出创建失败，直接关闭：{exc}")
            self._close_animation_active = False
            self._close_fade = None
            timer = self._close_fade_timer
            self._close_fade_timer = None
            if timer is not None:
                try:
                    timer.stop()
                except RuntimeError:
                    pass
            if fade is not None:
                try:
                    fade.stop()
                    fade.deleteLater()
                except RuntimeError:
                    pass
            self._remove_transition_input_blocker("_close_input_blocker")
            return False

    def _install_transition_input_blocker(
        self,
    ) -> Optional[TransitionInputBlocker]:
        """创建覆盖客户区的透明输入挡板（失败返回 None）。

        打开淡入与关闭淡出期间都使用：窗口仍是真实窗口，若不拦截，用户
        可能在过渡的百毫秒内误点内部控件。
        """
        try:
            blocker = TransitionInputBlocker(self)
            blocker.setGeometry(self.rect())
            blocker.show()
            blocker.raise_()
            blocker.setFocus(Qt.OtherFocusReason)
            return blocker
        except (RuntimeError, AttributeError) as exc:
            debug(f"设置窗口过渡挡板创建失败：{exc}")
            return None

    def _remove_transition_input_blocker(self, attr: str) -> None:
        """移除指定过渡挡板（幂等）。"""
        blocker = getattr(self, attr, None)
        setattr(self, attr, None)
        if blocker is not None:
            try:
                blocker.hide()
                blocker.deleteLater()
            except RuntimeError:
                pass

    def _on_close_fade_finished(self) -> None:
        """淡出完成：进入真正关闭收尾（幂等）。"""
        if self._skip_close_animation:
            return
        self._finish_close_animation()

    def _on_close_fade_timeout(self) -> None:
        """兜底：淡出动画未发 finished 时强制收尾（幂等）。"""
        self._close_fade_timer = None
        if not self._close_animation_active or self._skip_close_animation:
            return
        debug("设置窗口淡出等待超时，强制关闭")
        self._finish_close_animation()

    def _finish_close_animation(self) -> None:
        """关闭过渡结束：释放资源并真正关闭窗口（幂等）。"""
        if self._skip_close_animation:
            return
        self._close_animation_active = False
        timer = self._close_fade_timer
        self._close_fade_timer = None
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                pass
        fade = self._close_fade
        self._close_fade = None
        if fade is not None:
            try:
                fade.stop()
                fade.deleteLater()
            except RuntimeError:
                pass
        self._remove_transition_input_blocker("_close_input_blocker")
        try:
            self.setWindowOpacity(0.0)
        except RuntimeError:
            pass
        self._run_close_resource_cleanup_once()
        self._skip_close_animation = True
        try:
            self.close()
        except RuntimeError:
            pass

    def finish_close_animation_now(self) -> None:
        """立即收尾进行中的关闭过渡（再次打开/主窗口退出时调用）。"""
        if self._close_animation_active:
            self._finish_close_animation()
