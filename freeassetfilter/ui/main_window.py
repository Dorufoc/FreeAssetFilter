#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 主窗口
基于 PySideSix-Frameless-Window 和项目自定义 Mica 效果的无边框主窗口
"""

import sys
import time
import warnings
from pathlib import Path
from typing import Optional
import os

from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame, QSplitter, QGridLayout, QGraphicsOpacityEffect
from PySide6.QtOpenGLWidgets import QOpenGLWidget
import ctypes
from ctypes import wintypes

from PySide6.QtCore import (
    Qt,
    QEvent,
    QObject,
    QPoint,
    QTimer,
    Signal,
    QAbstractNativeEventFilter,
    QPropertyAnimation,
    QEasingCurve,
    QSize,
)
from PySide6.QtGui import QPainter, QPaintEvent, QPixmap, QRegion, QResizeEvent, QMoveEvent, QMouseEvent, QKeyEvent, QColor, QCursor, QPalette

# 确保 ui 目录在 sys.path 中（组件 __init__.py 使用短路径导入）
_ui_root = Path(__file__).resolve().parent
if str(_ui_root) not in sys.path:
    sys.path.insert(0, str(_ui_root))

# 添加项目根目录到 sys.path，使 freeassetfilter 包可导入
_project_root = _ui_root.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    from freeassetfilter.ui.frameless_window import (
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

# tm 别名已在 theme/__init__.py 中注册
# from theme import tm 与从 freeassetfilter.ui.theme import tm 指向同一实例
from theme import tm

from components.custom_background import BACKGROUND_DIR_NAME, CustomImageBackgroundWidget
# components.mica_material（MicaMaterial）不在模块级导入：它经 mica.engine
# 连带 numpy，导入约 0.16s，属「窗口出现前」关键路径。材质改为窗口显示后
# 惰性创建（见 _MicaBackgroundMixin._ensure_mica_material），与既有
# lazy=True「首帧纯色、后台烘焙」策略同源。
# 默认配置常量同样避开 components.mica_window shim（它再导出 mica.material →
# numpy），改从纯数据模块 mica.config 取（定义已迁至彼处，material 仍再导出）。
from freeassetfilter.ui.mica.config import DEFAULT_MICA_CONFIG
from components.styled_button import StyledButton
from components.styled_fluid_background import prewarm_top_level_rhi
# 启动加载覆盖层：铺满整个客户区、垫在标题栏之下只显示一个旋转圆环
# （见 MainWindow._setup_startup_overlay / _mount_startup_overlay）
from components.styled_loading import StyledLoading
# 内容层主题过渡遮罩（旧外观快照自绘淡出，轻量自绘替代整窗遮罩的两处卡顿源）
# 与背景层交叉过渡遮罩（设置页切换窗口背景：旧背景帧淡出、新层实时在底）
from components.theme_transition_overlay import (
    BackgroundTransitionOverlay,
    ContentTransitionOverlay,
)
# 实验性原生 DWM 云母开关的底层桥接（dwmapi 薄封装，惰性加载，零 COM 初始化）
from freeassetfilter.ui.mica import winapi as mica_winapi

# 三栏布局模块（FileSelectorLayout / FilePoolLayout / UnifiedPreviewerLayout）
# 不在模块级导入：它们连同 thumbnail_manager / file_card_delegate / numpy 等
# 约 0.2s 的重型依赖会被算进「窗口出现前」的关键路径。三栏本就在窗口显示后
# 才由 _build_panel 构建，故改为调用点局部导入（见 _build_panel）。
# SettingsLayout 同理：仅设置窗口使用，延迟到 _open_settings_window /
# SettingsWindow 实例化时再导入，避免启动路径加载 styled_sidebar /
# color_picker 等组件。

from freeassetfilter.utils.path_utils import get_app_data_path
from freeassetfilter.core._paths import icons_dir
from freeassetfilter.utils.animation_settings import is_animation_enabled
from freeassetfilter.utils.app_logger import debug, warning
# perf_metrics / StagingPoolService 同为首屏关键路径让位：分别由绘制埋点
# （MicaBackgroundWidgetCpu.paintEvent）与 closeEvent 局部导入。
from freeassetfilter.ui.theme.app_stylesheet import (
    apply_app_stylesheet,
    register_widget_qss,
)

# 简约背景层（try 包裹：组件 PR 合并前主窗口仍可导入，各调用点配合 getattr 守卫）
try:
    from components.minimalist_background import MinimalistBackgroundWidget
except ImportError:
    MinimalistBackgroundWidget = None  # type: ignore[assignment,misc]


# ── 米卡效果固定参数（按深浅色主题各一组） ─────────────────────────────
# 设置页不再提供米卡滑动条：参数为产品定值，随主题自动切换。
# 亮色模式 → 饱和度 1×、对比度 1×、模糊 200px、透明度 65%；
# 深色模式 → 饱和度 2×、对比度 1×、模糊 200px、透明度 80%。
# 亮色底板收敛：浅色底亮度高，壁纸色满强度 + 高饱和会把整窗染成壁纸色
# （面板被整体染色、层次消失），故大幅降饱和、降透明，只保留极淡的
# 壁纸色相与明暗起伏（磨砂玻璃质感仍来自亮度场）。
FIXED_MICA_PARAMS: dict = {
    "light": {
        "blur_radius": 200,
        "saturation": 1.0,
        "contrast": 1.0,
        "tint_opacity": 65,
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

    依赖链（``components.mica_material`` → ``mica.engine`` → numpy 等）首次导入
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

        延迟原因：``components.mica_material`` → ``mica.engine`` → numpy 的导入
        约 0.16s，属「窗口出现前」关键路径；而材质本就 ``lazy=True``（首帧以
        纯色呈现、壁纸模糊在窗口显示后的后台线程完成），整体后移不改变首帧观感。
        材质未就位期间由 :meth:`_paint_solid_fallback` 铺同色基底。

        Returns:
            MicaMaterial: 已创建（或已存在）的材质实例。
        """
        if self._mica is not None:
            return self._mica
        from components.mica_material import MicaMaterial

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
    ) -> None:
        super().__init__(parent)
        # 纯色不透明基底（挡住 win32 控件）
        self.setAutoFillBackground(True)
        self._init_mica_common(blur_radius, surface_color, luminosity, contrast, saturation, tint_opacity)
        # 烘焙后 paint 始终铺满整个 rect 且不透明，声明不透明绘制
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制 Mica 效果（纯色背景 + 按透明度叠加的模糊壁纸）"""
        # 局部导入：perf_metrics 自身模块级初始化约 50ms，不应计入窗口出现前
        # 的关键路径（首帧提速；sys.modules 缓存后每次绘制仅字典查找）。
        from freeassetfilter.utils.perf_metrics import begin_frame, end_frame

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


class MainWindow(_FramelessNativeEffectsMixin, FramelessMainWindow):
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
    STARTUP_OVERLAY_MIN_MS = 400
    STARTUP_OVERLAY_MAX_MS = 8000
    STARTUP_OVERLAY_FADE_MS = 200

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
        # 全局存储池浮窗：实例引用 + 三个信号连接对象。连接对象必须存引用
        # （供 set_floating_pool_enabled(False) 精确断开——lambda 槽无法按
        # 方法断连）；唯一创建入口为 _ensure_floating_pool。
        self._floating_pool = None
        self._floating_pool_conn_add = None
        self._floating_pool_conn_remove = None
        self._floating_pool_conn_pool_changed = None
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
        self._layout_toggle_btn = None
        self._reset_layout_btn = None
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
        # 布局切换代际计数：新一轮切换递增，作废上一轮未收尾的恢复回调
        self._layout_transition_generation: int = 0
        # 背景层交叉过渡遮罩（单实例去重引用；见 _start_background_transition）
        self._background_transition_overlay: QWidget | None = None
        # 系统主题监听器（跟随系统模式的实时链路；见 _start_system_theme_watcher）
        self._system_theme_watcher = None

        # 配置 Mica 参数（提前计算）：显式参数 > V2 保存值 > 项目默认
        cfg = DEFAULT_MICA_CONFIG
        mica_saved = self._load_mica_settings()
        background_saved = self._load_background_settings()
        # 主界面布局模式（general.layout_mode；非法值回退 workspace）
        self._layout_mode = self._load_layout_settings()
        # 通用功能开关（general.enable_ai_entry / general.include_remote_drives /
        # general.blank_right_click_go_back / general.show_hidden_files /
        # general.show_system_files / general.floating_pool_enabled /
        # general.floating_pool_snap_enabled；前三者非法值一律回退 False，
        # 隐藏/系统文件非法值回退 False，全局浮窗与贴边吸附非法值回退 True，
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

        # 合成后端预热：默认构造路径（不延迟初始化）仍在建窗前预热，保持历史
        # 行为一致；正式入口则把它移到首帧之后，避免 QRhi 初始化阻塞窗口出现。
        self._rhi_prewarm = None
        if not self._defer_heavy_init:
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
                from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2
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
        ``general.floating_pool_snap_enabled``（浮窗贴边吸附）。前五个开关
        缺失、类型非法一律回退 False（与 DEFAULT_SETTINGS_V2 默认一致）；
        全局浮窗与贴边吸附是 ``general`` 下默认开启的布尔，缺失、类型非法
        回退 True。隐藏/系统开关的 AND 语义由过滤层判定，此处不做归一化。

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
        floating_pool = True
        floating_pool_snap = True
        try:
            app = QApplication.instance()
            v2 = getattr(app, "settings_manager", None)
            if v2 is None:
                from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2
                v2 = SettingsManagerV2()
                v2.load()
            saved_ai = v2.get("general.enable_ai_entry", False)
            saved_remote = v2.get("general.include_remote_drives", False)
            saved_blank_back = v2.get(
                "general.blank_right_click_go_back", False
            )
            saved_hidden = v2.get("general.show_hidden_files", False)
            saved_system = v2.get("general.show_system_files", False)
            saved_floating = v2.get("general.floating_pool_enabled", True)
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
                saved_floating if isinstance(saved_floating, bool) else True
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
        self._rhi_prewarm = prewarm_top_level_rhi(self)
        # 内容是在 showEvent 之后创建的，因此手动补齐原本由 showEvent
        # 负责的首帧后工作，避免 Mica/覆盖层停留在未启动状态。
        if self._startup_overlay is not None:
            self._mount_startup_overlay()
            if self._startup_overlay_timer is not None:
                self._startup_overlay_timer.start(self.STARTUP_OVERLAY_MAX_MS)
        if self._background_mode == "mica" and self._mica_background is not None:
            self._start_mica_chain_preload()
            QTimer.singleShot(0, self._start_mica_refresh)

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
            background_image_path = os.path.join(
                get_app_data_path(), BACKGROUND_DIR_NAME, self._background_image_name
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
        self._startup_overlay_animation = animation  # 持引用防止提前回收
        animation.start()

    def _make_panel_placeholder(self) -> QLabel:
        """生成面板加载占位标签（'加载中…'），真实布局构建后移除。"""
        label = QLabel("加载中…", self)
        label.setAlignment(Qt.AlignCenter)
        register_widget_qss(label,(
            f"color: {tm.text.name()}; background-color: transparent; font-size: 13px;"
        ))
        return label

    def _build_panels_deferred(self) -> None:
        """窗口显示后分阶段构建各区域重型布局，避免启动白屏/长阻塞。

        文件选择器（最重）优先构建并显示，预览区、储存池、信息面板随后补齐；
        全部就绪后连接跨栏信号、刷新样式并应用默认比例（16:9 / 半高上限）。
        """
        QTimer.singleShot(0, lambda: self._build_panel("selector"))
        QTimer.singleShot(30, lambda: self._build_panel("preview"))
        QTimer.singleShot(60, lambda: self._build_panel("pool"))
        QTimer.singleShot(90, lambda: self._build_panel("info"))
        QTimer.singleShot(120, self._finalize_panels)

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
        """
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
            self._refresh_panel_styles()
            return

        try:
            zone = self._zones.get(side)
            if zone is None:
                warning(f"未知面板区域: {side!r}")
                return
            if side == "selector":
                from layout.file_selector_layout import FileSelectorLayout

                self._file_selector = FileSelectorLayout(zone)
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
        # 该区域刚就绪即刷新其边框/填充：即使其它区域尚未构建，也能让已就绪区正确显示
        self._refresh_panel_styles()

    def _finalize_panels(self) -> None:
        """全部区域就绪后：连接跨栏信号、刷新样式、应用默认比例。

        预览器较重，120ms 时可能仍未构建完成；故逐区域守卫连接已就绪者，
        并在仍有区域缺失时延后重试，确保跨栏信号最终全部连上（边框/填充已由
        _build_panel 渐进套用，不受此影响）。
        """
        if self._file_selector is not None:
            # 信号连接：文件选择器 → 文件池
            self._file_selector.toggle_pool_requested.connect(self._on_toggle_pool_requested)
            self._file_selector.add_files_to_pool_requested.connect(self._on_add_files_to_pool_requested)
            self._file_selector.remove_files_from_pool_requested.connect(self._on_remove_files_from_pool_requested)
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
            # 信号连接：预览器内层条目选中 → 文件信息面板联动
            #（文件夹预览器选中条目时面板显示该条目信息；取消时恢复）
            self._previewer.entry_selected.connect(self._on_previewer_entry_selected)

        self._refresh_panel_styles()

        # 文件池就绪且跨栏信号已连接后再触发一次暂存池恢复。原实现在
        # showEvent 里按固定 100ms 延时触发，与 _build_panels_deferred 的
        # 分阶段构建存在时序竞态：FilePoolLayout 构造较重时 _file_pool 仍为
        # None，会让 load_backup() 抛 AttributeError 并中断整条恢复流程。
        if self._file_pool is not None and not getattr(self, "_restore_started", False):
            self._restore_started = True
            QTimer.singleShot(0, self._check_and_restore_backup)

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
        self._apply_leaf_minimums()
        self._apply_previewer_minimums()
        self._apply_window_minimums()
        QTimer.singleShot(0, self._apply_default_layout)
        # 全部真实布局已就绪：按需创建全局存储池浮窗（唯一入口，幂等 +
        # 启用门；与上方恢复调度同为 singleShot(0)，让建窗落在事件循环
        # 下一拍、不阻塞 finalize 收尾）
        QTimer.singleShot(0, self._ensure_floating_pool)
        # 全部真实布局已就绪：撤下启动加载覆盖层
        # （后台 FFmpeg/LUT 预热、缓存清理继续在背后跑，不阻塞使用）
        self._dismiss_startup_overlay()

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
        # 局部导入：浮窗依赖暂存池服务等模块，创建时才加载
        from freeassetfilter.ui.floating_pool_window import FloatingPoolWindow

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
        floating._host_window = self
        # 初始快照：建窗时池内可能已有条目（恢复批），立即灌入防丢失
        floating.set_items(self._file_pool.items)
        # 应用贴边吸附意图（窗口侧 API 由 Todo 8 提供；失败不阻断建窗）
        try:
            floating.set_snap_enabled(self._floating_pool_snap_enabled)
        except Exception as exc:  # noqa: BLE001 - 吸附意图下发失败不阻断建窗
            warning(f"浮窗贴边吸附意图应用失败: {exc}")
        floating.show()

    def _teardown_floating_pool(self) -> None:
        """断开浮窗信号连接、停用定时器、关闭并调度销毁（幂等；``None`` 安全）。

        先断开三个业务连接与浮窗自身的主题连接（``_theme_conn`` 由全局
        ``tm`` 持有，若不断开会把已弃浮窗经绑定槽引用保活），停掉 ``set_items``
        防抖定时器（避免销毁后仍触发 ``_rebuild_list``），再 ``close()`` 并
        ``deleteLater()``，最后清空实例引用与连接记账。
        """
        floating = self._floating_pool
        if floating is None:
            return
        for attr in (
            "_floating_pool_conn_add",
            "_floating_pool_conn_remove",
            "_floating_pool_conn_pool_changed",
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
        timer = getattr(floating, "_debounce_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                pass
        try:
            floating.close()
        except RuntimeError:
            pass
        try:
            floating.deleteLater()
        except RuntimeError:
            pass
        self._floating_pool = None

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

        # 标题文字
        self._title_label = QLabel("FreeAssetFilter")
        register_widget_qss(self._title_label,(f'font-size: 14px; font-weight: 600; color: {tm.text.name()};'))
        header_layout.addWidget(self._title_label)
        header_layout.addStretch()

        # 布局切换按钮（SVG图标）：在「预览优先 / 经典三栏」两种布局间切换
        self._layout_toggle_btn = StyledButton(
            "", variant="ghost", size="sm", icon=""
        )
        self._layout_toggle_btn.setFixedSize(32, 32)
        register_widget_qss(self._layout_toggle_btn,(self._title_bar_button_style()))
        self._layout_toggle_btn.clicked.connect(self._toggle_layout_mode)
        header_layout.addWidget(self._layout_toggle_btn)
        self._update_layout_toggle_button()

        # 重置布局按钮（SVG图标）：把各区域位置大小恢复到默认值
        reset_icon_path = icons_dir() / "refresh.svg"
        self._reset_layout_btn = StyledButton(
            "",
            variant="ghost",
            size="sm",
            icon=str(reset_icon_path) if reset_icon_path.exists() else ""
        )
        self._reset_layout_btn.setFixedSize(32, 32)
        register_widget_qss(self._reset_layout_btn,(self._title_bar_button_style()))
        self._reset_layout_btn.setToolTip("重置布局")
        self._reset_layout_btn.clicked.connect(self._reset_layout)
        header_layout.addWidget(self._reset_layout_btn)

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
    
    def _reset_layout(self) -> None:
        """把主界面各区域的位置大小恢复为当前布局模式的默认值（渐变过渡）"""
        if self._main_layout is None:
            return
        self._main_layout.apply_default_ratios(
            animated=is_animation_enabled("layout_reset", default=True)
        )

    def _toggle_layout_mode(self) -> None:
        """布局切换按钮：在「预览优先」与「经典三栏」两种布局间即时切换。

        与设置页「通用 → 界面布局」同一链路：先预抓拍旧外观快照（250ms
        溶解过渡，受 layout_switch 动画门控），再 ``set_layout_mode``
        即时重组布局，最后延迟写盘 ``general.layout_mode``，避免同步磁盘
        IO 推迟过渡动画启动。按钮图标与提示由 ``set_layout_mode`` 内的
        ``_update_layout_toggle_button`` 统一刷新，本方法不重复维护。
        """
        target = "classic" if self._layout_mode == "workspace" else "workspace"
        self.begin_layout_transition()
        if not self.set_layout_mode(target):
            return
        self._persist_layout_mode()

    def _update_layout_toggle_button(self) -> None:
        """按当前布局模式刷新切换按钮的图标与提示（图标=点击后的目标模式）。"""
        btn = self._layout_toggle_btn
        if btn is None:
            return
        if self._layout_mode == "workspace":
            # 当前预览优先 → 点击切为经典三栏，显示经典布局图标
            icon_path = icons_dir() / "layout_classic.svg"
            btn.setToolTip("切换为经典三栏布局")
        else:
            icon_path = icons_dir() / "layout_workspace.svg"
            btn.setToolTip("切换为预览优先布局")
        if icon_path.exists():
            btn.set_svg_icon(str(icon_path))

    def _persist_layout_mode(self) -> None:
        """延迟写盘布局偏好到 SettingsManagerV2（general.layout_mode）。

        延迟到下一事件循环拍执行，避免同步磁盘 IO 推迟过渡动画启动；
        回调内读取最新 ``_layout_mode``，快速连点只落最终值。失败仅告警，
        不阻塞布局切换。
        """

        def _deferred_save() -> None:
            try:
                app = QApplication.instance()
                v2 = getattr(app, "settings_manager", None)
                if v2 is None:
                    from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2
                    v2 = SettingsManagerV2()
                    v2.load()
                v2.set("general.layout_mode", self._layout_mode)
                v2.save()
            except Exception as exc:  # noqa: BLE001 - 延迟写盘失败仅告警
                warning(f"布局设置保存失败（重启后可能回退）：{exc}")

        QTimer.singleShot(0, _deferred_save)

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
        # 窗口子树销毁会清空其 QSS 片段条目：``destroyed`` 在子控件销毁
        # **之前**触发，因此推迟到下一事件循环拍再剪枝（此时子树已真正析构），
        # 使注册表规模回到存活控件数（避免反复开关后表项堆积）。
        QTimer.singleShot(0, self._prune_qss_registrations)

    @staticmethod
    def _prune_qss_registrations() -> None:
        """清掉 QSS 注册表中已销毁控件的片段条目（失败不影响生命周期）。"""
        try:
            from freeassetfilter.ui.theme.app_stylesheet import (
                prune_dead_registrations,
            )

            prune_dead_registrations()
        except Exception as exc:  # noqa: BLE001 - 剪枝失败不影响窗口生命周期
            debug(f"关闭后 QSS 注册表剪枝失败：{exc}")

    def _start_content_theme_transition(self, mode: str = "reveal") -> None:
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

        快照抓取 ``_root``（背景层 + 内容层）而非仅内容子树：面板填充
        多为 5%~72% alpha，内容层单独抓拍几乎全透明，铺到已切换的新内容
        上还原不出旧外观（实测与真实旧外观平均通道差 205/255），揭示对比
        度不成立；含背景的整体快照为不透明、逐像素还原（实测差 0/255）。
        默认 CPU 光栅 Mica 走 ``render()`` 无 GL 依赖；实验性 GL 版 Mica
        （``FAF_USE_GL_MICA=1``）不经 ``render()``，补画其帧缓冲。
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
            return
        # 单实例去重：上一过渡未结束则立即完成，避免连点叠加多层遮罩
        prev = self._content_theme_overlay
        if prev is not None:
            from shiboken6 import isValid

            if isValid(prev):
                prev.finish_now()
            self._content_theme_overlay = None
        size = content.size()
        if size.isEmpty():
            return
        snapshot = self._capture_theme_snapshot(size, content.devicePixelRatioF())
        if snapshot is None or snapshot.isNull():
            return
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
        overlay.start()

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
        """
        try:
            self._start_content_theme_transition()
        except Exception:  # noqa: BLE001 - 快照失败不阻塞主题切换本身
            pass
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
        # 门控：布局切换动画关闭时跳过过渡（与 _reset_layout 的 layout_reset 同款）
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
        ``QWidget.grab()``；实验性 GL 云母（``FAF_USE_GL_MICA=1``）经
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
            from freeassetfilter.ui.theme.system_theme import (
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
            register_widget_qss(self._layout_toggle_btn,(self._title_bar_button_style()))
            register_widget_qss(self._reset_layout_btn,(self._title_bar_button_style()))
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

    def _refresh_panel_styles(self) -> None:
        """刷新各区域组件的 styleSheet（主题切换 / 延迟构建逐区就绪时调用）。

        逐区守卫：仅对当前已构建的区域套用边框/填充，因此可在尚未全部就绪时
        被 ``_build_panel`` 渐进调用——已就绪区立即正确显示，缺失区留待其构建后
        的调用补齐（无需等全部齐了才一次性刷新）。

        注意：延迟构建时本方法在窗口已显示之后被调用，而对已显示控件设置
        styleSheet 不会自动重绘，必须对各分区控件强制 unpolish/polish 才能让
        边框/填充生效（与主题切换路径一致）。
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

        # 整窗级重刷（与主题切换路径一致，作为兜底确保所有已显示控件套用样式）
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
        """Esc：清除文件选择器 / 文件储存池的框选选中态。

        键盘事件冒泡到主窗口说明当前焦点控件未消费 Esc（全屏预览、弹窗等
        在各自控件内处理并接受事件），因此不会与其 Esc 语义冲突。
        """
        if event.key() == Qt.Key_Escape:
            if self._file_selector is not None:
                self._file_selector.clear_box_selection()
            if self._file_pool is not None:
                self._file_pool.clear_box_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_pool_contents_changed(self) -> None:
        """文件池内容变更时，同步路径集合到文件选择器 delegate（边框标记）。"""
        pool_paths = self._file_pool.get_pool_paths()
        self._file_selector.sync_pool_status(pool_paths)

    def _show_preview(self, file_info: dict) -> None:
        """统一预览入口：同步驱动预览器与文件信息面板（任一缺失时守卫跳过）。"""
        if self._previewer is not None:
            self._previewer.set_file(file_info)
        if self._info_panel is not None:
            self._info_panel.set_file(file_info)

    def _on_file_selected(self, file_info: dict) -> None:
        """处理文件选择器的文件选中事件，同步预览态到文件池与自身卡片"""
        file_path = file_info.get("path", "")
        self._file_selector.set_previewing_file(file_path)
        self._file_pool.set_previewing_file(file_path)
        self._show_preview(file_info)

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
        try:
            import components.mica_material  # noqa: F401 - 仅预热导入
        except Exception as e:  # noqa: BLE001 - 预热失败留主线程兜底导入
            warning(f"云母依赖链预导入失败（回退主线程导入）: {e}")
        finally:
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
        # 全局浮窗：先于 flush_backup/dispose 关闭。计划契约——closeEvent 只
        # close 不置 None（置 None 仅限 set_floating_pool_enabled(False) 路径），
        # 故推导会持有自身引用的测试（断言 isHidden）不被销毁干扰。
        if self._floating_pool is not None:
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
        # 局部导入：暂存池服务依赖文件池/缩略图等重型模块，退出路径再加载
        from freeassetfilter.services.staging_pool_service import StagingPoolService

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
        if (
            mode != getattr(self, "_background_mode", "mica")
            and self._can_transition_background()
        ):
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
            self._update_layout_toggle_button()
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
        # 顶栏布局切换按钮随模式刷新（设置页切换与按钮点击同链路）
        self._update_layout_toggle_button()
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
        src_layout: "MainLayout", dst_layout: "MainLayout"
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

        self.setWindowTitle("设置")
        self.setMinimumSize(700, 400)
        self.resize(700, 500)

        # 定位：owned 窗口不显式定位时由 Windows 级联放置（落在屏幕右下），
        # 这里居中到宿主主窗口；无宿主时回退到鼠标所在屏幕中心。
        self._center_on_host()

        # 中央部件用纯 QWidget，保留本地无边框基类原生窗口特性；
        # tm.surface 不透明纯色背景（styled 弹窗同款），无 Mica 开销
        self._root = QWidget(self)
        self.setCentralWidget(self._root)
        _apply_theme_palette(self._root)
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
        # 样式下发兜底：widget 模式下每次 ``register_widget_qss`` 已把片段
        # 直接下发到控件自身，本窗口首帧天然带自己的样式（历史"首帧无片段
        # 回退到不含本窗片段的旧全表"缺陷不再存在）；此处仅补发 teardown
        # 窗口等未能即时下发的积压项，以及进程生命周期内首次调用的全量
        # 重下发（等价旧实现启动时那次应用级统一下发，让 Qt 重算布局缓存）。
        apply_app_stylesheet()

    def _sync_theme(self) -> None:
        """强制刷新当前主题下的所有样式"""
        # 纯色背景（tm.surface 随主题变化）
        if self._root is not None:
            _apply_theme_palette(self._root)
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
        except Exception as exc:
            debug(f"设置窗口关闭钩子失败（暂存缓存可能未清理）：{exc}")
        super().closeEvent(event)
