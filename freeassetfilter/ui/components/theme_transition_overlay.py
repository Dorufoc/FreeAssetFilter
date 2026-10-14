"""Theme transition overlay - radial reveal / crossfade snapshot on theme change."""

from __future__ import annotations

import math
from typing import Optional

from PySide6.QtWidgets import QWidget, QApplication
from PySide6.QtCore import (
    Qt,
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPixmap


def _max_corner_distance(rect: QRect, center: QPoint) -> float:
    """返回 *center* 到 *rect* 四角的最大距离（覆盖整幅所需半径）。

    Args:
        rect: 目标区域（组件逻辑坐标）。
        center: 扩散圆心（逻辑坐标）。

    Returns:
        float: 最大距离（像素）；退化尺寸返回 0.0。
    """
    if rect.isEmpty():
        return 0.0
    corners = (
        (rect.left(), rect.top()),
        (rect.right(), rect.top()),
        (rect.left(), rect.bottom()),
        (rect.right(), rect.bottom()),
    )
    return max(
        math.hypot(cx - center.x(), cy - center.y()) for cx, cy in corners
    )


class _SnapshotTransitionOverlay(QWidget):
    """主题过渡遮罩基类：旧外观快照 + 两种揭示动画。

    两种模式由构造参数 ``origin`` 决定：

    - **径向揭示（origin 给定）**：以 ``origin`` 为圆心、半径从 0 扩张到
      覆盖整幅的最大距离；整幅以旧外观快照打底，圆内透明露出已切换好的
      新主题——web 式 ``clip-path: circle()`` 扩散效果，明暗切换自按钮
      向外扩散。半径 0 时即整幅旧外观（点击瞬间不发新主题闪现）；每像素
      同一时刻只显示「旧」或「新」一个版本，无交叉淡入的双重曝光叠印
      （文字不糊）。
    - **透明度淡出（origin 缺省，兼容回退）**：快照按透明度 1.0→0 淡出，
      行为与历史一致。

    公共约定：

    - 遮罩必须带透明通道（``WA_TranslucentBackground``）：揭示圆洞（透明）
      与淡出路径依赖遮罩的透明区透出下方新主题；快照本体可含不透明像素
      （整窗抓拍），但其透明像素必须有 alpha 输出，不能以实体底色覆盖；
    - ``WA_TransparentForMouseEvents`` 鼠标穿透，过渡不阻塞界面交互；
    - 快照由调用方传入并按 ``devicePixelRatio`` 生成物理分辨率
      （高分屏不失真），本类绘制期按逻辑坐标自适配；
    - **快照位图由遮罩接管**：径向揭示会在其上挖洞（``DestinationOut``），
      调用方构造后不得复用该位图；
    - 过渡中父级尺寸变化（缩放窗口）时立即收尾，避免快照与控件错位；
    - ``finish_now`` 幂等，快速连续切换时用于去重清理。
    """

    DEFAULT_DURATION_MS: int = 450

    def __init__(
        self,
        parent: QWidget,
        snapshot: QPixmap,
        duration_ms: int,
        origin: Optional[QPoint] = None,
    ) -> None:
        """初始化遮罩。

        Args:
            parent: 覆盖目标控件（遮罩几何贴合其 rect）。
            snapshot: 过渡前抓取的旧外观快照。
            duration_ms: 动画时长（毫秒，内部钳到下限 50）。
            origin: 径向揭示圆心（父级逻辑坐标）；None 走透明度淡出。
        """
        super().__init__(parent)
        self._snapshot = snapshot
        self._duration_ms = max(50, int(duration_ms))
        self._opacity: float = 1.0
        self._reveal_center: Optional[QPoint] = QPoint(origin) if origin is not None else None
        self._revealed_radius: float = 0.0
        self._max_radius: float = 0.0
        # 已挖洞半径：洞只增不减，绘制期只在半径扩张时增量重挖快照位图。
        self._punched_radius: float = 0.0
        self._finished: bool = False
        # 动画激活标志：仅激活期收到父级 resize 才收尾。构造/测试渲染阶段
        # 的几何事件（如 render 传送的尺寸事件）不得误结束过渡。
        self._active: bool = False
        # 已启动标志：start() 幂等（连点去重路径会先 finish_now 再替换）。
        self._started: bool = False

        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # 遮罩必须带透明通道：揭示圆洞与淡出路径都靠遮罩透明区透出下方
        # 新主题/背景；若绘制成不透明实底，过渡期会把新主题盖死。
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setAutoFillBackground(False)
        self.setGeometry(parent.rect())
        # 尺寸变化守卫：过渡中缩放窗口则立即收尾（快照与父级错位无意义）。
        parent.installEventFilter(self)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(self._duration_ms)
        self._anim.valueChanged.connect(self._on_value_changed)
        self._anim.finished.connect(self._on_finished)

    # ── 动画 ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """显示遮罩、布置动画参数，并把起钟推迟到下一事件循环拍。

        起钟推迟（见 :meth:`_start_animation_if_live`）的原因：调用方
        （主题切换链路）在本调用后会**同步**执行主题翻转与 QSS 全树重刷
        （实测 ~50ms）；若立即 ``_anim.start()``，动画时钟从翻转前开始计，
        前段扩散会被同步段吃掉（450ms 实际只剩 ~370ms 可见）。推迟一拍后
        时钟从内容全部就绪起算，揭示时长完整、扩散观感均匀；期间遮罩已
        以整幅旧外观呈现（半径 0），界面状态与点击前一致，无闪变。

        幂等：已启动/已结束的实例直接忽略。
        """
        if self._started or self._finished:
            return
        self._started = True
        self.show()
        self.raise_()
        if self._reveal_center is not None:
            self._max_radius = _max_corner_distance(
                self.rect(), self._reveal_center
            )
            if self._max_radius <= 0.0:
                # 退化几何（空尺寸）：无扩散可言，直接收尾。
                self._on_finished()
                return
            self._anim.setEasingCurve(QEasingCurve.InOutCubic)
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(self._max_radius)
        else:
            self._anim.setEasingCurve(QEasingCurve.InOutCubic)
            self._anim.setStartValue(1.0)
            self._anim.setEndValue(0.0)
        self._active = True
        QTimer.singleShot(0, self._start_animation_if_live)

    def _start_animation_if_live(self) -> None:
        """延迟起钟回调（见 :meth:`start`）：已结束/已销毁实例静默跳过。"""
        try:
            if self._finished:
                return
            self._anim.start()
        except RuntimeError:
            pass

    def finish_now(self) -> None:
        """立即结束过渡并清理（快速连续切换时的去重路径，幂等）。"""
        self._on_finished()

    def _on_value_changed(self, value: object) -> None:
        """动画帧回调：更新揭示半径 / 透明度并触发重绘。

        Args:
            value: 动画当前值（径向=半径 0→max；淡出=透明度 1.0→0.0）。
        """
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return
        if self._reveal_center is not None:
            self._revealed_radius = max(0.0, number)
        else:
            self._opacity = max(0.0, min(1.0, number))
        self.update()

    def _on_finished(self) -> None:
        """动画结束清理：停动画、隐藏并调度销毁（幂等）。"""
        if self._finished:
            return
        self._finished = True
        self._active = False
        # 解绑父级事件过滤器：遮罩销毁后不留悬空过滤钩子。
        parent = self.parentWidget()
        if parent is not None:
            try:
                parent.removeEventFilter(self)
            except (RuntimeError, TypeError):
                pass
        try:
            self._anim.stop()
        except RuntimeError:
            pass
        self.hide()
        self.deleteLater()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt 命名
        """过渡激活期间父级尺寸变化 → 立即收尾（快照与父级错位无意义）。"""
        if event.type() == QEvent.Resize and self._active and not self._finished:
            self._on_finished()
        return super().eventFilter(watched, event)

    # ── 绘制 ─────────────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt 命名
        """按当前模式自绘旧外观快照（单次 blit，无效果过滤管线）。"""
        if self._snapshot.isNull():
            return
        if self._reveal_center is not None:
            self._paint_reveal()
        else:
            self._paint_fade()

    def _paint_fade(self) -> None:
        """透明度淡出（历史行为）：整幅快照按当前透明度绘制。"""
        if self._opacity <= 0.0:
            return
        painter = QPainter(self)
        try:
            # 快照按原生 DPR 保留；dpr 为小数时遮罩目标尺寸非快照物理像素的
            # 整数倍，保持平滑过滤避免缩放发糊。
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.setOpacity(self._opacity)
            painter.drawPixmap(self.rect(), self._snapshot)
        finally:
            painter.end()

    def _paint_reveal(self) -> None:
        """径向揭示：整幅旧外观打底，自圆心挖出扩张圆洞透出新主题。

        洞直接挖在**快照位图**上（``DestinationOut`` 增量、抗锯齿），再整幅
        以 ``SourceOver`` 绘制到控件：

        - 不触碰控件背景存储——Qt 对子控件的绘制是就地合成，破坏性合成
          模式会连下层内容一起清掉（实测 ``CompositionMode_Source`` 会把
          父级像素一并覆盖）；且每帧重绘会先把下层按新主题重画，快照
          ``SourceOver`` 覆盖后圆内透明处自然透出新主题；
        - 洞只增不减：每帧按当前半径重挖（幂等），未扩张时不重复动作；
        - 半径 0 时洞为空，整幅旧外观——点击瞬间不发新主题闪现；
        - 抗锯齿圆缘由 ``DestinationOut`` 的椭圆覆盖率给出，与下方新主题
          平滑过渡，无锯齿硬边。
        """
        center = self._reveal_center
        if center is None:
            return
        radius = self._revealed_radius
        if radius > self._punched_radius and not self._snapshot.isNull():
            self._punch_reveal_hole(center, radius)
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.drawPixmap(self.rect(), self._snapshot)
        finally:
            painter.end()

    def _punch_reveal_hole(self, center: QPoint, radius: float) -> None:
        """在快照位图上挖出半径 *radius* 的圆洞（增量、抗锯齿）。

        Args:
            center: 圆心（快照逻辑坐标，与控件坐标一致）。
            radius: 当前揭示半径（逻辑像素）。
        """
        self._ensure_snapshot_alpha()
        painter = QPainter(self._snapshot)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setCompositionMode(QPainter.CompositionMode_DestinationOut)
            painter.setBrush(QColor(0, 0, 0))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(center), radius, radius)
        finally:
            painter.end()
        self._punched_radius = radius

    def _ensure_snapshot_alpha(self) -> None:
        """确保快照带 alpha 通道（``DestinationOut`` 挖洞的前提）。

        裸 ``QPixmap(w, h)`` 无 alpha 通道（RGB32），在其上做破坏性合成会
        得到不透明黑洞；调用方常规路径已铺透明底，此处兜底转换一次，
        保证任何来源的快照（含测试替身）都能正确揭示。
        """
        try:
            if self._snapshot.hasAlphaChannel():
                return
        except RuntimeError:
            return
        converted = QPixmap(self._snapshot.size())
        converted.setDevicePixelRatio(self._snapshot.devicePixelRatio())
        converted.fill(Qt.transparent)
        painter = QPainter(converted)
        try:
            painter.drawPixmap(QPoint(0, 0), self._snapshot)
        finally:
            painter.end()
        self._snapshot = converted


class ThemeTransitionOverlay(_SnapshotTransitionOverlay):
    """整窗主题过渡遮罩（设置窗口「确定」提交等场景）。

    快照经 ``QScreen.grabWindow(HWND)`` 从原生窗口句柄抓取（正确合成
    OpenGL 背景），动画为径向揭示（传 ``origin``）或透明度淡出（缺省）。

    Usage:
        snapshot = screen.grabWindow(int(window.winId()))
        overlay = ThemeTransitionOverlay(window, snapshot, origin=point)
        overlay.start()
        # Apply theme change immediately after start(); the overlay reveals
        # the newly themed window underneath.
    """

    DEFAULT_DURATION_MS: int = 450

    def __init__(
        self,
        parent: QWidget,
        snapshot: QPixmap,
        duration_ms: int = DEFAULT_DURATION_MS,
        origin: Optional[QPoint] = None,
    ) -> None:
        super().__init__(parent, snapshot, duration_ms, origin)

    @classmethod
    def from_widget(
        cls,
        window: QWidget,
        duration_ms: int = DEFAULT_DURATION_MS,
        origin: Optional[QPoint] = None,
    ) -> "ThemeTransitionOverlay":
        """Capture a top-level window via its native handle and create an overlay.

        ``QScreen.grabWindow(HWND)`` correctly composites OpenGL-backed children
        (e.g. the Mica background) where ``QWidget.grab()`` produces corrupted
        artifacts on some GPU drivers.

        Args:
            window: 目标顶层窗口。
            duration_ms: 动画时长（毫秒）。
            origin: 径向揭示圆心（窗口逻辑坐标）；None 走透明度淡出。

        Returns:
            ThemeTransitionOverlay: 已构造未启动的遮罩。
        """
        screen = window.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        # WId is the native window handle (HWND on Windows).
        snapshot = screen.grabWindow(int(window.winId()))
        return cls(window, snapshot, duration_ms, origin)


class ContentTransitionOverlay(_SnapshotTransitionOverlay):
    """主窗口主题过渡遮罩：整窗旧外观快照打底、径向揭示 / 淡出。

    与 :class:`ThemeTransitionOverlay`（``QScreen.grabWindow`` 截屏）的分工：

    - 快照由调用方传入（主窗口对 ``_root``（背景层 + 内容层）``render``：
      不透明整窗旧外观，逐像素还原切换前画面；默认 CPU 光栅背景无 GL 依赖，
      GL 版 Mica 由调用方补画帧缓冲）；面板填充多为低 alpha，仅抓内容子树
      无法还原旧外观，揭示对比度不成立（见调用方抓拍说明）；
    - 默认径向揭示：``origin`` 通常为主题切换按钮中心，旧外观整幅打底、
      自按钮向外挖出扩张圆洞露出新主题，每像素只显示一份旧/新外观，
      消除淡出模式的文字双重曝光叠印；
    - ``origin`` 缺省时退化为透明度淡出（历史行为，供异常路径兜底）。

    快照为整窗外观（含背景层），揭示期间背景层自身的交叉淡入被遮罩盖住、
    随揭示同步露出；未显示窗口（测试/最小化）不创建遮罩。
    """

    DEFAULT_DURATION_MS: int = 450  # 对齐 ui/mica/config.XFADE_DURATION_MS

    def __init__(
        self,
        parent: QWidget,
        snapshot: QPixmap,
        duration_ms: int = DEFAULT_DURATION_MS,
        origin: Optional[QPoint] = None,
    ) -> None:
        super().__init__(parent, snapshot, duration_ms, origin)
