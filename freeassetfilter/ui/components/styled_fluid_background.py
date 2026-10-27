"""Styled fluid background component for audio preview mode.

FreeAssetFilter - 多功能文件预览与管理工具
Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.
"""
# allow: SIZE_OK — single UI component integrating the existing color API,
# palette helpers, GPU/CPU renderers and lifecycle as required by the
# music-previewer-layout plan todo 4.

from __future__ import annotations

import logging
import math
import os
import time
import weakref
from collections.abc import Callable
from typing import Any, ClassVar, NamedTuple

from PySide6.QtCore import QPointF, QRect, QTimer, Qt
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPaintEvent,
    QPixmap,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import QWidget

from components._styled_fluid_cpu import render_static_frame
from components._styled_fluid_math import hsv_shift, wrap_phase
from freeassetfilter.core.managers.heartbeat_manager import HeartbeatManager
from freeassetfilter.ui.theme import tm

logger = logging.getLogger(__name__)

#: 等待 GPU 渲染管线就绪的最长时间（秒）。QRhiWidget 在首次绘制时才创建
#: QRhi 并回调 initialize()（正常 0~1 帧内完成）。首次初始化可能夹在建窗后的
#: D3D11 设备创建、Mica/缩略图烘焙等主线程繁忙时刻之后，超时给得太短会让
#: 一次性延迟变成永久回退 CPU 静态帧（一旦回退不再重试），故留足 2s。
_GPU_READY_TIMEOUT_S = 2.0

try:
    from components._styled_fluid_gpu import _FluidGPUShaderWidget
except ImportError:  # pragma: no cover
    _FluidGPUShaderWidget = None  # type: ignore[misc,assignment]

#: RHI 预热标记控件的几何（逻辑像素）。它从不显示，只用于让顶层窗口在建窗
#: 时发现「层级内有 QRhiWidget」从而启用 RHI 合成后端。
_RHI_PREWARM_SIZE = 1


def prewarm_top_level_rhi(window: QWidget) -> QWidget | None:
    """在建窗之前，为 *window* 所属顶层窗口启用 RHI 合成后端。

    非原生（参与宿主合成）的 :class:`QRhiWidget` 的 QRhi 来自顶层窗口的合成
    后端，而顶层窗口**只在 QWindow 创建之前其层级里已经存在 QRhiWidget** 时
    才会选择 RHI 合成后端：实测在 ``winId()``（即建窗）之后再挂 QRhiWidget，
    该控件的 ``initialize()`` 永不回调、控件保持空白，只能回退 CPU。

    本项目音频模式的流体背景正是这种「窗口显示后才惰性创建」的 QRhiWidget
    （预览器由 ``MainWindow._build_panel`` 在窗口显示后用定时器构建），因此
    必须由主窗口在构造早期先调用本函数挂一个不可见的预热控件，把顶层窗口的
    合成后端定成 RHI。预热控件仅作为标记存在，从不显示、不渲染。

    Args:
        window: 顶层窗口，必须**尚未**访问过 ``winId()``（即 QWindow 尚未
            创建），否则预热无效。

    Returns:
        预热控件（调用方需持引用以免被 Python 侧回收）；``QRhiWidget``
        不可用时返回 ``None``。
    """
    if _FluidGPUShaderWidget is None:
        return None
    # 建窗后再预热不但无效，还会让预热控件自己报 "QRhiWidget: No QRhi"。
    # ``internalWinId()`` 只读缓存的 WId、不会像 ``winId()`` 那样强制建窗。
    try:
        if window.internalWinId() != 0:
            logger.warning(
                "RHI 合成预热晚于顶层窗口创建，流体背景将回退 CPU 静态帧；"
                "prewarm_top_level_rhi 必须在 show()/winId() 之前调用"
            )
            return None
    except (AttributeError, RuntimeError):  # pragma: no cover - 非 Qt 窗口对象
        pass
    try:
        warmup = _FluidGPUShaderWidget(window)
    except Exception:  # noqa: BLE001 - 预热失败只影响流体背景走 CPU 路径
        logger.exception("RHI 合成预热控件创建失败")
        return None
    warmup.setGeometry(0, 0, _RHI_PREWARM_SIZE, _RHI_PREWARM_SIZE)
    warmup.hide()
    return warmup


class _FluidTimeState(NamedTuple):
    """Immutable GPU animation state advanced once per HeartbeatManager tick."""

    time: float
    noise_offset: tuple[float, float]
    palette_phase: float
    blob_phases: tuple[float, ...]


class StyledFluidBackground(QWidget):
    """Styled fluid background component.

    Manages an internal 5-color palette and renders an Apple Music-style fluid
    background. The palette can be supplied explicitly via
    :meth:`set_custom_colors` or derived from the current theme's accent
    color via :meth:`use_accent_theme`. When using the accent theme, the
    component automatically rebuilds the palette whenever ``tm.colors_updated``
    is emitted.

    Rendering:
        - 默认走 GPU 路径：``_FluidGPUShaderWidget``（QRhiWidget，D3D11 后端）
          加载 ``shaders/fluid.vert.qsb`` / ``fluid.frag.qsb`` 渲染动画。
          用 QRhiWidget 而非 QOpenGLWidget，是因为后者会把顶层窗口切到
          OwnDC 窗口类，导致拖拽缩放每步整窗重绘；且该控件参与宿主合成
          而不原生化，缩放时与窗口其余内容同一次合成、不产生错位闪烁
          （两条理由详见 ``_styled_fluid_gpu`` 模块头注释）。
        - GPU 路径注册 HeartbeatManager tick 驱动 uniform 动画；构造或管线
          创建失败时回退 CPU 静态烘焙 ``QPixmap``。
        - CPU 路径也会在 ``FAF_FORCE_FLUID_CPU=1``、检测到同布局原生兄弟
          窗口、``QRhiWidget`` 不可用时强制启用。
    """

    _PALETTE_SIZE = 5

    #: P7.4：存活实例弱集合。主窗口最小化/失焦宽限时对整个集合调用
    #: :meth:`suspend` / :meth:`resume`，无需逐个布局接线。
    _LIVE_INSTANCES: ClassVar["weakref.WeakSet"] = weakref.WeakSet()

    # Angular velocity of the circular noise-offset drift in radians per
    # second (one lap every ~16 s). Constant speed keeps the domain warp
    # evolving uniformly with no periodic sprint.
    _NOISE_ORBIT_RAD_PER_SEC = 2.0 * math.pi / 16.0

    # Palette breathing rate in phase cycles per second (~8 s per
    # inhale-exhale cycle) and drift amplitudes. These are tuned so the
    # color wash visibly breathes within a few seconds of playback.
    _PALETTE_BREATH_PER_SEC = 0.12
    _PALETTE_DRIFT_HUE = 18.0
    _PALETTE_DRIFT_SAT = 10.0
    _PALETTE_DRIFT_VAL = 7.0

    # Parameters for analogous palette generation from a single seed color.
    # Tuned for Apple Music-like backgrounds: high saturation, deep-to-mid
    # values so blobs read as rich color washes instead of pale tints.
    _HUE_SHIFTS = (-24, 0, 22, 46, -48)
    _SAT_MULS = (1.30, 1.38, 1.22, 1.15, 1.45)
    _VAL_MULS = (0.78, 0.92, 1.00, 0.66, 0.58)

    # Normalised blob parameters for the GPU/CPU shared model. ``speed`` is
    # in orbit cycles per second; ~8-15 s per lap so blobs drift with a
    # clearly visible lava-lamp flow instead of an almost-static wash.
    _FLUID_BLOBS: ClassVar[list[dict[str, Any]]] = [
        {"base": QPointF(0.16, 0.20), "orbit": QPointF(0.14, 0.10),
         "radius": 0.46, "scale_x": 1.34, "scale_y": 1.06,
         "phase": 0.0, "speed": 0.105, "opacity": 0.72, "color_index": 0},
        {"base": QPointF(0.84, 0.24), "orbit": QPointF(0.13, 0.11),
         "radius": 0.40, "scale_x": 1.20, "scale_y": 1.34,
         "phase": 1.1, "speed": 0.090, "opacity": 0.62, "color_index": 1},
        {"base": QPointF(0.30, 0.80), "orbit": QPointF(0.11, 0.12),
         "radius": 0.42, "scale_x": 1.28, "scale_y": 1.20,
         "phase": 2.2, "speed": 0.075, "opacity": 0.56, "color_index": 2},
        {"base": QPointF(0.78, 0.72), "orbit": QPointF(0.14, 0.10),
         "radius": 0.36, "scale_x": 1.42, "scale_y": 1.10,
         "phase": 3.0, "speed": 0.100, "opacity": 0.54, "color_index": 3},
        {"base": QPointF(0.50, 0.46), "orbit": QPointF(0.10, 0.10),
         "radius": 0.38, "scale_x": 1.10, "scale_y": 1.52,
         "phase": 4.1, "speed": 0.065, "opacity": 0.44, "color_index": 4},
        {"base": QPointF(0.60, 0.16), "orbit": QPointF(0.09, 0.08),
         "radius": 0.28, "scale_x": 1.30, "scale_y": 0.88,
         "phase": 0.8, "speed": 0.115, "opacity": 0.42, "color_index": 2},
        {"base": QPointF(0.20, 0.58), "orbit": QPointF(0.10, 0.06),
         "radius": 0.26, "scale_x": 0.96, "scale_y": 1.24,
         "phase": 2.8, "speed": 0.110, "opacity": 0.38, "color_index": 1},
        {"base": QPointF(0.84, 0.52), "orbit": QPointF(0.07, 0.09),
         "radius": 0.22, "scale_x": 1.12, "scale_y": 1.12,
         "phase": 5.0, "speed": 0.125, "opacity": 0.34, "color_index": 0},
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # P7.4：登记存活实例，主窗口最小化/失焦宽限时统一挂起（无需逐布局接线）。
        type(self)._LIVE_INSTANCES.add(self)
        # 宿主只负责承载 CPU/GPU 渲染层，未覆盖区域必须透出下方内容，
        # 不能让 QWidget 的系统默认背景（通常为白色）参与合成。
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._palette: list[QColor] = []
        self._mode = "accent"
        self._loaded = False
        self._suspended = False
        self._renderer: str | None = None
        self._gpu_attempted = False
        self._gpu_widget: QWidget | None = None
        self._static_pixmap: QPixmap | None = None
        self._tick_count = 0
        self._last_tick_wall = 0.0
        self._time_state: _FluidTimeState | None = None
        self._parent_layout_slot: int | None = None
        self._theme_changed_slot: Callable | None = None
        self._colors_updated_slot: Callable | None = None
        self._last_overlay_color: QColor | None = None
        self._last_baked_palette: list[QColor] | None = None
        #: 上一次因顶层窗口切换而重建 GPU 控件的时间（节流，避免 show/hide 抖动）
        self._last_gpu_rebuild_at: float = 0.0
        self.use_accent_theme()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def colors(self) -> list[QColor]:
        """Return a shallow copy of the current 5-color palette.

        Returns:
            list[QColor]: The currently active palette.
        """
        return [QColor(c) for c in self._palette]

    def set_custom_colors(self, colors: list[QColor]) -> None:
        """Set a custom palette from 1-5 QColor values.

        The input colors are mapped to an internal palette of exactly 5
        colors:

        - 5 colors are preserved as-is.
        - 4 colors are kept and a subtle derived color is appended.
        - 3 colors are placed at positions 0, 2, 4 and intermediate colors
          are interpolated.
        - 2 colors are expanded to a 5-stop RGB gradient.
        - 1 color is expanded to an analogous 5-color palette.

        Empty or invalid input falls back to :meth:`use_accent_theme`.

        Args:
            colors: A list of 1-5 QColor objects.
        """
        if not self._is_valid_color_list(colors):
            self.use_accent_theme()
            return

        self._palette = self._build_palette(colors)
        self._mode = "custom"
        self._rebuild_if_cpu()
        self.update()

    def use_accent_theme(self) -> None:
        """Derive the 5-color palette from ``tm.accent``.

        The class-level colors_updated slot is kept so that it can be
        disconnected reliably in :meth:`unload`. Theme signal connections
        themselves are established in :meth:`load` using
        ``Qt.UniqueConnection``.
        """
        self._palette = self._build_from_seed(tm.accent)
        self._mode = "accent"
        slot = self._on_colors_updated
        try:
            tm.colors_updated.connect(slot, type=Qt.UniqueConnection)
        except RuntimeError:
            pass
        self._colors_updated_slot = slot
        self._rebuild_if_cpu()
        self.update()

    def renderer(self) -> str | None:
        """Return the active renderer name.

        Returns:
            ``"gpu"``, ``"cpu"`` or ``None`` if :meth:`load` has not been
            called.
        """
        return self._renderer

    def load(self, parent_layout_slot: int | None = None) -> None:
        """Prepare rendering and start the appropriate animation path.

        GPU path registers a normal-tick HeartbeatManager callback to drive
        shader uniforms; CPU path bakes a single static pixmap and does not
        register any tick. Theme signals are connected with
        ``Qt.UniqueConnection`` so that the accent palette and overlay stay in
        sync with the active theme.

        Args:
            parent_layout_slot: Optional caller-provided layout index or
                identifier. Stored for diagnostic purposes but not used by
                the component itself.
        """
        self._parent_layout_slot = parent_layout_slot
        self._loaded = True
        self._connect_theme_signals()
        self._renderer = self._choose_renderer()
        if self._renderer == "gpu":
            self._start_animation()
            # Push palette/overlay uniforms immediately so the first visible
            # frame is already scrimmed instead of waiting for the first tick.
            self._sync_gpu_widget()
        elif self._renderer == "gpu_pending":
            # P6.3：GPU 管线就绪前先用 CPU 静态帧占位（不再阻塞主线程）。
            self._bake_static_frame()
        elif self._renderer == "cpu":
            self._bake_static_frame()
        self.update()

    def suspend(self) -> None:
        """挂起渲染：停 tick + 释放 GPU 纹理/静态帧（P7.4，可逆）。

        最小化时调用；不销毁控件、不断开主题信号，因此 :meth:`resume`
        可以直接重建。释放的显存是流体纹理（``w×h×4``，4K 下约 33MB）。
        """
        if not self._loaded:
            return
        self._suspended = True
        self._stop_animation()
        self._release_gpu_widget()
        self._static_pixmap = None
        self.update()

    def resume(self) -> None:
        """从 :meth:`suspend` 恢复（P7.4）：重选渲染器并重建首帧。"""
        if not self._loaded or not getattr(self, "_suspended", False):
            return
        self._suspended = False
        self._renderer = self._choose_renderer()
        if self._renderer == "gpu":
            self._start_animation()
            self._sync_gpu_widget()
        elif self._renderer in {"gpu_pending", "cpu"}:
            self._bake_static_frame()
        self.update()

    @classmethod
    def suspend_all(cls) -> int:
        """挂起所有存活实例（P7.4）；返回实际挂起的实例数。"""
        count = 0
        for widget in list(cls._LIVE_INSTANCES):
            try:
                if widget._loaded and not getattr(widget, "_suspended", False):
                    widget.suspend()
                    count += 1
            except RuntimeError:
                # C++ 对象已销毁（弱集滞后一拍），跳过
                continue
        return count

    @classmethod
    def resume_all(cls) -> int:
        """恢复所有被挂起的实例（P7.4）；返回实际恢复的实例数。"""
        count = 0
        for widget in list(cls._LIVE_INSTANCES):
            try:
                if getattr(widget, "_suspended", False):
                    widget.resume()
                    count += 1
            except RuntimeError:
                continue
        return count

    def unload(self) -> None:
        """Stop animation, release the renderer, and schedule cleanup.

        Unregisters the HeartbeatManager tick callback on GPU path, destroys
        the GPU child widget if present, clears the static CPU pixmap,
        disconnects both ``tm.theme_changed`` and ``tm.colors_updated``,
        reparents the widget out of its current layout, and calls
        ``deleteLater()``.
        """
        self._loaded = False
        self._stop_animation()
        self._release_gpu_widget()
        self._static_pixmap = None
        self._renderer = None
        self._disconnect_theme_signals()
        type(self)._LIVE_INSTANCES.discard(self)
        self.setParent(None)
        self.deleteLater()

    # ------------------------------------------------------------------
    # Theme signal handlers
    # ------------------------------------------------------------------

    def _on_theme_changed(self, theme: str) -> None:
        """React to a dark/light mode switch.

        Args:
            theme: New theme name emitted by ThemeManager.
        """
        del theme
        self._refresh_for_theme()

    def _on_colors_updated(self, colors: dict) -> None:
        """React to theme color dictionary updates.

        Args:
            colors: Current color dictionary emitted by ThemeManager.
        """
        del colors
        if self._mode != "accent":
            return
        self._refresh_for_theme()

    # ------------------------------------------------------------------
    # Palette helpers
    # ------------------------------------------------------------------

    @classmethod
    def _is_valid_color_list(cls, colors: object) -> bool:
        """Return True when *colors* is a usable list of QColor values.

        A usable list contains between 1 and ``cls._PALETTE_SIZE`` entries,
        and every entry is a valid ``QColor``.

        Args:
            colors: The value to validate.

        Returns:
            True if *colors* can be used to build a custom palette.
        """
        if (
            not isinstance(colors, list)
            or len(colors) == 0
            or len(colors) > cls._PALETTE_SIZE
        ):
            return False
        return all(isinstance(c, QColor) and c.isValid() for c in colors)

    @classmethod
    def _build_palette(cls, colors: list[QColor]) -> list[QColor]:
        n = len(colors)
        if n == cls._PALETTE_SIZE:
            return [QColor(c) for c in colors]
        if n == 1:
            return cls._build_from_seed(colors[0])
        if n == 2:
            c0, c1 = colors
            return [
                QColor(c0),
                cls._mix(c0, c1, 0.25),
                cls._mix(c0, c1, 0.5),
                cls._mix(c0, c1, 0.75),
                QColor(c1),
            ]
        if n == 3:
            c0, c1, c2 = colors
            return [
                QColor(c0),
                cls._mix(c0, c1, 0.5),
                QColor(c1),
                cls._mix(c1, c2, 0.5),
                QColor(c2),
            ]
        # n == 4
        c0, c1, c2, c3 = colors
        return [
            QColor(c0),
            QColor(c1),
            QColor(c2),
            QColor(c3),
            cls._build_from_seed(c3)[1],
        ]

    @classmethod
    def _build_from_seed(cls, seed: QColor) -> list[QColor]:
        """Create a 5-color analogous palette from a single seed color.

        Args:
            seed: Base color (typically ``tm.accent``).

        Returns:
            list[QColor]: 5-color analogous palette.
        """
        h, s, v, a = seed.getHsv()
        if h < 0:
            h = 280

        palette: list[QColor] = []
        for hue_shift, sat_mul, val_mul in zip(
            cls._HUE_SHIFTS, cls._SAT_MULS, cls._VAL_MULS
        ):
            new_h = (h + hue_shift) % 360
            new_s = max(0, min(255, int(s * sat_mul)))
            new_v = max(0, min(255, int(v * val_mul)))
            palette.append(QColor.fromHsv(new_h, new_s, new_v, a))
        return palette

    @staticmethod
    def _mix(a: QColor, b: QColor, t: float) -> QColor:
        """Linearly interpolate two colors in RGBA space.

        Args:
            a: Start color.
            b: End color.
            t: Interpolation factor in the range [0.0, 1.0].

        Returns:
            QColor: Interpolated color.
        """
        inv = 1.0 - t
        return QColor(
            round(a.red() * inv + b.red() * t),
            round(a.green() * inv + b.green() * t),
            round(a.blue() * inv + b.blue() * t),
            round(a.alpha() * inv + b.alpha() * t),
        )

    # ------------------------------------------------------------------
    # Renderer lifecycle and animation
    # ------------------------------------------------------------------

    def _connect_theme_signals(self) -> None:
        """Connect theme_changed/colors_updated slots once per load()."""
        theme_slot = self._on_theme_changed
        try:
            tm.theme_changed.connect(theme_slot, type=Qt.UniqueConnection)
        except RuntimeError:
            pass
        self._theme_changed_slot = theme_slot

        color_slot = self._on_colors_updated
        try:
            tm.colors_updated.connect(color_slot, type=Qt.UniqueConnection)
        except RuntimeError:
            pass
        self._colors_updated_slot = color_slot

    def _disconnect_theme_signals(self) -> None:
        """Disconnect the theme slots recorded by :meth:`_connect_theme_signals`."""
        if self._theme_changed_slot is not None:
            try:
                tm.theme_changed.disconnect(self._theme_changed_slot)
            except RuntimeError:
                pass
        if self._colors_updated_slot is not None:
            try:
                tm.colors_updated.disconnect(self._colors_updated_slot)
            except RuntimeError:
                pass

    def _gpu_geometry(self) -> QRect:
        """Return the host rect verbatim, without any inflation.

        GPU 子控件与宿主逐像素重合：纹理由顶层合成器按控件几何铺满，几何一旦
        比宿主大出 1 个逻辑像素，流体就会盖住相邻控件（例如播放器下方 52px
        的播放控制栏），并在 fractional DPI 下随取整在 1~2 物理像素之间抖动，
        窗口缩放时表现为流体边缘错位闪烁。

        旧实现把尺寸 ``+1`` 膨胀，是为补偿 ``QOpenGLWidget`` 原生 GL 表面按
        「逻辑尺寸 × DPR」截断取整产生的 1 物理像素短差。改用 ``QRhiWidget``
        后纹理尺寸由 Qt 按 ``qRound`` 生成并由顶层合成器缩放铺满控件区域
        （渲染尺寸始终取 ``colorTexture().pixelSize()``，见
        ``_styled_fluid_gpu``），短差已被覆盖，无需再膨胀。

        Returns:
            QRect: 与宿主完全一致的子控件几何。
        """
        return self.rect()

    def _choose_renderer(self) -> str:
        """Select GPU or CPU renderer based on environment and capability.

        CPU fallback is forced when any of the following is true:

        - ``FAF_FORCE_FLUID_CPU`` equals ``"1"``.
        - A visible sibling in the parent layout has ``Qt.WA_NativeWindow`` set
          and a non-zero ``winId()``.
        - ``QRhiWidget`` 不可用。
        - 着色器资源缺失或渲染管线创建失败。

        Returns:
            ``"gpu"`` or ``"cpu"``.
        """
        self._gpu_attempted = True
        if os.environ.get("FAF_FORCE_FLUID_CPU") == "1":
            self._release_gpu_widget()
            return "cpu"
        if self._has_native_sibling():
            self._release_gpu_widget()
            return "cpu"
        if _FluidGPUShaderWidget is None:
            self._release_gpu_widget()
            return "cpu"

        # 复用已存在的 GPU 控件（切歌等重复 load 场景）：每次重建会泄漏
        # 旧的 RHI 资源（残留上一首的颜色盖在下层），且新控件在部分驱动下
        # 呈现空白；复用还避免了重复创建管线与着色器的开销。
        existing = self._gpu_widget
        if existing is not None:
            try:
                if existing.is_ready():
                    existing.setGeometry(self._gpu_geometry())
                    if not existing.isVisible():
                        existing.show()
                    return "gpu"
            except RuntimeError:
                pass
            self._release_gpu_widget()

        gpu: QWidget | None = None
        try:
            gpu = _FluidGPUShaderWidget(parent=self)
            gpu.setGeometry(self._gpu_geometry())
            gpu.show()
            self._gpu_widget = gpu
            # P6.3：**不做同步等待**。QRhiWidget 在首次显示并收到平台绘制
            # 事件后才回调 initialize()；原实现用嵌套 QEventLoop 轮询，会
            # 在主线程阻塞最长 500ms 并重入事件循环。现在先返回 pending，
            # 由 ``_poll_gpu_ready`` 在后续事件循环中轮询，期间 paintEvent
            # 画 CPU 静态帧占位。
            if gpu.is_ready():
                try:
                    gpu.setGeometry(self._gpu_geometry())
                except RuntimeError:
                    pass
                return "gpu"
            self._gpu_deadline = time.monotonic() + _GPU_READY_TIMEOUT_S
            QTimer.singleShot(16, self._poll_gpu_ready)
            return "gpu_pending"
        except Exception:
            logger.exception(
                "GPU fluid background initialization failed; falling back to CPU"
            )
            if gpu is not None:
                gpu.setParent(None)
                gpu.deleteLater()
            self._gpu_widget = None
            return "cpu"

    def _poll_gpu_ready(self) -> None:
        """轮询 GPU 管线就绪（P6.3：非阻塞替代嵌套 QEventLoop）。"""
        if not self._loaded or self._renderer != "gpu_pending":
            return
        gpu = self._gpu_widget
        if gpu is None:
            self._renderer = "cpu"
            self.update()
            return
        try:
            ready = gpu.is_ready()
        except RuntimeError:
            ready = False
        if ready:
            self._renderer = "gpu"
            try:
                gpu.setGeometry(self._gpu_geometry())
            except RuntimeError:
                pass
            self._static_pixmap = None
            self._start_animation()
            self._sync_gpu_widget()
            self.update()
            return
        deadline = getattr(self, "_gpu_deadline", 0.0)
        if time.monotonic() >= deadline:
            logger.warning("GPU fluid renderer not ready in time; falling back to CPU")
            self._release_gpu_widget()
            self._renderer = "cpu"
            if self._static_pixmap is None:
                self._bake_static_frame()
            self.update()
            return
        QTimer.singleShot(16, self._poll_gpu_ready)

    def _has_native_sibling(self) -> bool:
        """Detect a native-window sibling in the same parent layout."""
        parent = self.parentWidget()
        if parent is None:
            return False
        layout = parent.layout()
        if layout is None:
            return False
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item is None:
                continue
            sibling = item.widget()
            if sibling is None or sibling is self:
                continue
            if (
                sibling.isVisible()
                and sibling.testAttribute(Qt.WA_NativeWindow)
                and sibling.winId() != 0
            ):
                return True
        return False

    def _release_gpu_widget(self) -> None:
        """Destroy the GPU child widget if it exists."""
        if self._gpu_widget is not None:
            self._gpu_widget.setParent(None)
            self._gpu_widget.deleteLater()
            self._gpu_widget = None

    def _start_animation(self) -> None:
        """Register the ~30 FPS HeartbeatManager tick callback."""
        self._time_state = self._create_time_state()
        # Reset the wall-clock baseline so the first post-start delta
        # measures from here instead of from an arbitrarily old tick.
        self._last_tick_wall = time.monotonic()
        hm = HeartbeatManager()
        try:
            hm.register_tick_callback(
                self._tick_id(),
                self._on_tick,
                priority=3,
                every_n_ticks=1,
                owner=self,
            )
        except ValueError:
            pass

    def _create_time_state(self) -> _FluidTimeState:
        """Return the initial GPU animation state.

        ``noise_offset`` is seeded with the t=0 value of the circular drift
        formula so the first advanced tick does not visibly jump.
        """
        return _FluidTimeState(
            time=0.0,
            noise_offset=(0.0, 0.5),
            palette_phase=0.0,
            blob_phases=tuple(0.0 for _ in range(len(self._FLUID_BLOBS))),
        )

    def _advance_time_state(self, state: _FluidTimeState, delta: float = 0.033) -> _FluidTimeState:
        """Advance the GPU animation state by one tick.

        All periodic quantities move at constant velocity. The previous
        implementation eased the noise offset and (via the sync step) the
        blob orbits, which produced a pause-sprint-pause rhythm: every cycle
        the whole pattern lurched during the fast mid-phase and then
        "snapped back" to calm motion — visible as a periodic twitch.

        Args:
            state: Current animation state.
            delta: Real elapsed seconds since the previous tick. Using wall
                time (instead of a fixed step) keeps the flow at 1x speed
                even when the shared heartbeat runs slower than 30fps.

        Returns:
            _FluidTimeState: New state with updated time, palette phase,
            per-blob phases and noise offset.
        """
        delta = max(0.0, min(0.25, float(delta)))
        new_time = state.time + delta
        new_palette_phase = wrap_phase(
            state.palette_phase + self._PALETTE_BREATH_PER_SEC * delta
        )
        new_blob_phases = tuple(
            wrap_phase(phase + blob["speed"] * delta)
            for phase, blob in zip(state.blob_phases, self._FLUID_BLOBS)
        )

        noise_angle = new_time * self._NOISE_ORBIT_RAD_PER_SEC
        noise_offset = (
            math.sin(noise_angle) * 0.5,
            math.cos(noise_angle) * 0.5,
        )

        return _FluidTimeState(
            time=new_time,
            noise_offset=noise_offset,
            palette_phase=new_palette_phase,
            blob_phases=new_blob_phases,
        )

    def _stop_animation(self) -> None:
        """Unregister the HeartbeatManager tick callback."""
        HeartbeatManager().unregister_tick_callback(self._tick_id())

    def _tick_id(self) -> str:
        """Return the stable HeartbeatManager callback id for this widget."""
        return f"styled_fluid_bg_{id(self)}"

    def _on_tick(self) -> None:
        """Advance animation state and request a repaint (GPU path only)."""
        if not self._loaded or self._renderer != "gpu" or self._gpu_widget is None:
            return
        now = time.monotonic()
        last = self._last_tick_wall
        self._last_tick_wall = now
        delta = now - last if last > 0.0 else 0.033
        self._tick_count += 1
        if self._time_state is None:
            self._time_state = self._create_time_state()
        else:
            self._time_state = self._advance_time_state(self._time_state, delta)
        self._sync_gpu_widget()
        self._gpu_widget.update()

    def _sync_gpu_widget(self) -> None:
        """Upload the current animation state to the GPU shader widget."""
        if self._gpu_widget is None or not self._palette or self._time_state is None:
            return

        state = self._time_state
        # Sinusoidal drift: hue/sat/value breathe smoothly and return to the
        # base palette each cycle, avoiding the visible color snap a linear
        # wrapped phase would produce.
        drift = math.sin(state.palette_phase * 2.0 * math.pi)
        drifted_palette = [
            hsv_shift(
                color,
                drift * self._PALETTE_DRIFT_HUE,
                drift * self._PALETTE_DRIFT_SAT,
                drift * self._PALETTE_DRIFT_VAL,
            )
            for color in self._palette
        ]

        blob_centers: list[tuple[float, float]] = []
        blob_radii: list[float] = []
        blob_colors: list[int] = []

        for i, blob in enumerate(self._FLUID_BLOBS[:4]):
            # Constant angular velocity. Easing here made every (initially
            # phase-synchronized) blob sweep its whole orbit in a short
            # mid-cycle burst, so the first cycle end twitched the entire
            # scene at once before the phases drifted apart.
            angle = blob["phase"] + state.blob_phases[i] * 2.0 * math.pi
            cx = blob["base"].x() + math.sin(angle) * blob["orbit"].x()
            cy = blob["base"].y() + math.cos(angle) * blob["orbit"].y()
            blob_centers.append((cx, cy))
            blob_radii.append(float(blob["radius"]))
            blob_colors.append(int(blob["color_index"]) % self._PALETTE_SIZE)

        self._gpu_widget.update_uniforms(
            time=state.time,
            palette=drifted_palette,
            blob_centers=blob_centers,
            blob_radii=blob_radii,
            blob_colors=blob_colors,
            noise_offset=state.noise_offset,
            overlay_color=self._overlay_color(),
        )

    # ------------------------------------------------------------------
    # Theme overlay and CPU bake
    # ------------------------------------------------------------------

    def _overlay_color(self) -> QColor:
        """Return the translucent overlay colour for the current theme.

        Dark mode applies a ~30% black overlay; light mode applies a ~25%
        white overlay. This mimics the darkening/lightening scrim used by
        Apple Music-style fluid backgrounds so text remains readable.
        """
        pct = 30.0 if tm.is_dark_theme() else 25.0
        base = tm.black if tm.is_dark_theme() else tm.white
        return tm.alpha_of(base, pct)

    def _refresh_for_theme(self) -> None:
        """Rebuild palette/overlay as needed and refresh the active renderer.

        CPU path only re-bakes when the effective overlay color or accent
        palette actually changes. This prevents a single ``tm.set_theme``
        call (which emits both ``theme_changed`` and ``colors_updated``)
        from baking the CPU pixmap twice.
        """
        if self._mode == "accent":
            self._palette = self._build_from_seed(tm.accent)

        if not self._loaded:
            self.update()
            return

        overlay = self._overlay_color()
        overlay_changed = (
            self._last_overlay_color is None
            or self._last_overlay_color.rgba() != overlay.rgba()
        )
        palette_changed = (
            self._mode == "accent"
            and self._last_baked_palette is not None
            and len(self._last_baked_palette) == len(self._palette)
            and any(
                a.rgba() != b.rgba()
                for a, b in zip(self._last_baked_palette, self._palette)
            )
        )

        if self._renderer == "gpu":
            self._sync_gpu_widget()
            if self._gpu_widget is not None:
                self._gpu_widget.update()
        elif self._renderer == "cpu" and (overlay_changed or palette_changed):
            self._bake_static_frame()
        else:
            # Theme change produced no baked-output delta; still repaint
            # so any small widget state is consistent.
            self.update()

    def _bake_static_frame(self) -> None:
        """Render the current CPU path static pixmap at the widget size."""
        width = self.width()
        height = self.height()
        if width <= 0 or height <= 0 or not self._palette:
            self._static_pixmap = QPixmap()
            return

        overlay = self._overlay_color()
        self._static_pixmap = render_static_frame(
            width=width,
            height=height,
            palette=self._palette,
            noise_seed=0,
            time=0.0,
            overlay_color=overlay,
        )
        self._last_overlay_color = QColor(overlay)
        self._last_baked_palette = [QColor(c) for c in self._palette]
        self.update()

    def _rebuild_if_cpu(self) -> None:
        """Re-bake the static pixmap when the CPU renderer is active."""
        if self._renderer == "cpu":
            self._bake_static_frame()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent | None = None) -> None:
        """Keep the GPU child widget sized to the host geometry.

        The child is sized to the host rect verbatim (see
        :meth:`_gpu_geometry`), so the render target always matches the host
        region pixel for pixel. Resizing stays cheap because
        ``_FluidGPUShaderWidget.initialize`` is idempotent (a texture rebuild
        no longer recreates the pipeline or shaders), not because the render
        target size is decoupled from the widget.
        """
        super().resizeEvent(event)
        if self._gpu_widget is not None:
            self._gpu_widget.setGeometry(self._gpu_geometry())

    def showEvent(self, event: QShowEvent | None = None) -> None:
        """显示时校验 GPU 渲染器仍然有效（顶层窗口迁移后可能失效）。

        独立预览宿主（``PreviewFullscreenHost``）会把整个预览器迁移到新的
        顶层窗口。旧 ``QRhiWidget`` 归属于原窗口的 QRhi，迁移后 Qt 只会
        ``releaseResources()`` 而不再回调 ``initialize()``（新窗口若本就没有
        RHI 合成则彻底拿不到 QRhi）。此时 ``_renderer`` 仍是 ``gpu``，而
        ``paintEvent`` 在 GPU 模式不绘制任何内容，于是流体区域整块露出宿主
        底色（或只剩迁移前的残留纹理）——视觉上就是一块与四周割裂的矩形。

        这里在每次显示时校验一次：未就绪则重建 GPU 控件，让它在当前顶层
        窗口的 RHI 上重新初始化。
        """
        super().showEvent(event)
        self._ensure_gpu_renderer_after_show()

    def _ensure_gpu_renderer_after_show(self) -> None:
        """GPU 控件未就绪时重建（节流 1s，避免 show/hide 抖动反复重建）。"""
        if not self._loaded or self._suspended or self._renderer != "gpu":
            return
        gpu = self._gpu_widget
        if gpu is not None:
            try:
                if gpu.is_ready():
                    return
            except RuntimeError:
                pass
        now = time.monotonic()
        if now - self._last_gpu_rebuild_at < 1.0:
            return
        self._last_gpu_rebuild_at = now
        self._release_gpu_widget()
        self._renderer = self._choose_renderer()
        if self._renderer == "gpu":
            self._start_animation()
            self._sync_gpu_widget()
        elif self._renderer in {"gpu_pending", "cpu"}:
            self._bake_static_frame()
        self.update()

    def paintEvent(self, event: QPaintEvent | None = None) -> None:
        """Paint the fluid background or a solid placeholder.

        Before :meth:`load` is called the widget fills itself with the first
        palette color so the component is still visible in designer-like
        contexts. After :meth:`load`, the CPU path draws the baked static
        pixmap scaled to widget size; the GPU path delegates drawing to the
        child OpenGL widget and only paints a fallback fill.

        Args:
            event: Paint event.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if self._loaded and self._renderer == "cpu":
            pixmap = self._static_pixmap
            if pixmap is not None and not pixmap.isNull():
                painter.drawPixmap(self.rect(), pixmap, pixmap.rect())
        # GPU 模式由子 QRhiWidget 完整绘制；宿主层保持透明，不能再用
        # palette[0] 绘制兜底底色，否则尺寸边缘会露出一圈非流体颜色。
        painter.end()
