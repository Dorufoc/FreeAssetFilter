"""Styled Loading component — Windows 11 风格圆圈旋转加载动画。"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from theme import tm


class StyledLoading(QWidget):
    """Windows 11 风格的圆圈旋转加载动画（纯色圆角弧，弧长呼吸式伸缩 + 整体旋转）。

    尺寸：sm (16px) / default (24px) / lg (32px)
    颜色变体：default / success / warning / danger
    形态：普通内联（固定正方形）与 overlay 遮罩覆盖层（铺满父控件、圆环居中）
    遮罩底色：dim（半透明黑色压暗，局部/弹窗加载）/ opaque（主题表面色实色，启动屏）

    运动模型：头尾两端各自在一个周期内平均转过 360°，叠加一对反相正弦速度
    调制（头快则尾慢），因此两端角速度恒为正 —— 头部始终向前、拖尾只追赶不
    倒退，弧长在 MIN/MAX 之间平滑伸缩且周期首尾无缝。无轨道底环、无渐变。

    颜色一律在 ``paintEvent`` 内通过 ``tm`` 现取，并订阅
    ``tm.theme_changed`` 触发重绘，与其它 styled 组件一致。

    Example:
        >>> inline = StyledLoading(size="lg", variant="danger")
        >>> overlay = StyledLoading(overlay=True, parent=card)
        >>> overlay.fit_to_parent()
        >>> splash = StyledLoading(size="lg", overlay=True, backdrop="opaque", parent=host)
    """

    VARIANTS = ("default", "success", "warning", "danger")

    SIZE_CONFIG = {
        "sm": {"size": 16, "stroke": 2.0},
        "default": {"size": 24, "stroke": 2.5},
        "lg": {"size": 32, "stroke": 3.0},
    }

    # 弧长伸缩（呼吸）周期，毫秒；一个周期内圆环平均转过一圈
    CYCLE_MS = 1400
    # 定时器间隔（约 60fps）
    TICK_INTERVAL_MS = 16
    # 弧长伸缩的上下限（角度）；振幅受正弦调制约束，MAX-MIN 需小于 229°
    MIN_SWEEP_DEG = 40.0
    MAX_SWEEP_DEG = 200.0
    # 遮罩覆盖层压暗强度（0-255）；沿用 styled_drawer 遮罩的黑色压暗约定
    OVERLAY_ALPHA = 128
    #: 遮罩样式：dim = 半透明黑色压暗（局部/弹窗加载）；opaque = 主题表面色实色（启动屏）
    BACKDROPS = ("dim", "opaque")

    def __init__(
        self,
        size: str = "default",
        variant: str = "default",
        overlay: bool = False,
        backdrop: str = "dim",
        auto_start: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        """初始化加载动画。

        Args:
            size: 尺寸档位，``"sm"`` / ``"default"`` / ``"lg"``，非法值回落 ``"default"``。
            variant: 颜色变体，``"default"`` / ``"success"`` / ``"warning"`` /
                ``"danger"``，非法值回落 ``"default"``。
            overlay: 是否作为遮罩覆盖层（铺满父控件、遮罩 + 居中圆环）。
            backdrop: 遮罩样式，``"dim"`` / ``"opaque"``（仅 overlay 模式生效），
                非法值回落 ``"dim"``。
            auto_start: 是否自动开始旋转（隐藏时自动暂停以省电）。
            parent: 父控件。
        """
        super().__init__(parent)
        self._size = size if size in self.SIZE_CONFIG else "default"
        self._variant = variant if variant in self.VARIANTS else "default"
        self._overlay = bool(overlay)
        self._backdrop = backdrop if backdrop in self.BACKDROPS else "dim"
        self._auto_start = bool(auto_start)
        self._user_stopped = not self._auto_start
        self._phase_ms = 0.0
        self._last_tick = time.perf_counter()
        self._timer: QTimer | None = None
        self._overlay_parent: QWidget | None = None

        if not self._overlay:
            self._apply_size()

        # 主题切换时按新配色重绘（颜色在 paintEvent 内现取）
        tm.theme_changed.connect(self._on_theme_changed)

        # 构造期尚未显示：真正的启动交给 showEvent，避免不可见时白烧 CPU
        if self._auto_start and self.isVisible():
            self._start_timer()

    # ------------------------------------------------------------------
    # 尺寸 / 变体
    # ------------------------------------------------------------------

    def _apply_size(self) -> None:
        """按当前尺寸档位固定为正方形。"""
        diameter = self.SIZE_CONFIG[self._size]["size"]
        self.setFixedSize(diameter, diameter)

    @property
    def size_variant(self) -> str:
        """当前尺寸档位。"""
        return self._size

    @size_variant.setter
    def size_variant(self, value: str) -> None:
        if value not in self.SIZE_CONFIG:
            return
        self._size = value
        if not self._overlay:
            self._apply_size()
        self.update()

    @property
    def variant(self) -> str:
        """当前颜色变体。"""
        return self._variant

    @variant.setter
    def variant(self, value: str) -> None:
        if value not in self.VARIANTS:
            return
        self._variant = value
        self.update()

    @property
    def overlay(self) -> bool:
        """是否处于遮罩覆盖层模式（只读）。"""
        return self._overlay

    @property
    def backdrop(self) -> str:
        """当前遮罩样式（只读）。"""
        return self._backdrop

    def sizeHint(self) -> QSize:
        """返回建议尺寸：普通模式为圆周直径，遮罩模式为最小可读尺寸。"""
        if self._overlay:
            return QSize(64, 64)
        diameter = self.SIZE_CONFIG[self._size]["size"]
        return QSize(diameter, diameter)

    # ------------------------------------------------------------------
    # 旋转控制
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """是否正在旋转（只读）。"""
        return self._timer is not None and self._timer.isActive()

    def start(self) -> None:
        """开始（或恢复）旋转，幂等。"""
        self._user_stopped = False
        self._start_timer()

    def stop(self) -> None:
        """停止旋转，幂等；停留在当前形态（角度与弧长都不再变化）。"""
        self._user_stopped = True
        self._stop_timer()
        self.update()

    def set_running(self, running: bool) -> None:
        """统一入口：按布尔值开始 / 停止旋转。

        Args:
            running: True 调用 :meth:`start`，False 调用 :meth:`stop`。
        """
        if running:
            self.start()
        else:
            self.stop()

    def _start_timer(self) -> None:
        """启动旋转定时器（已激活时直接返回）。"""
        if self._timer is not None and self._timer.isActive():
            return
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.setInterval(self.TICK_INTERVAL_MS)
            self._timer.timeout.connect(self._on_tick)
        self._last_tick = time.perf_counter()
        self._timer.start()

    def _stop_timer(self) -> None:
        """停止旋转定时器并结算已经过的时间。"""
        if self._timer is None or not self._timer.isActive():
            return
        self._advance()
        self._timer.stop()

    def _advance(self) -> None:
        """按真实经过时间推进周期相位（恒定节奏，与定时器抖动解耦）。"""
        now = time.perf_counter()
        elapsed_ms = (now - self._last_tick) * 1000.0
        self._phase_ms = (self._phase_ms + elapsed_ms) % self.CYCLE_MS
        self._last_tick = now

    def _on_tick(self) -> None:
        """定时器回调：推进相位并请求重绘。"""
        self._advance()
        self.update()

    def showEvent(self, event) -> None:
        """显示时按需恢复旋转。"""
        super().showEvent(event)
        if self._auto_start and not self._user_stopped:
            self._start_timer()

    def hideEvent(self, event) -> None:
        """隐藏时暂停旋转（不可见不烧 CPU）。"""
        self._stop_timer()
        super().hideEvent(event)

    # ------------------------------------------------------------------
    # 遮罩覆盖层
    # ------------------------------------------------------------------

    def fit_to_parent(self) -> None:
        """遮罩模式：铺满父控件，并在父控件缩放时自动跟随。

        非遮罩模式下为空操作。可重复调用，不会重复安装事件过滤器。
        """
        if not self._overlay:
            return
        parent = self.parentWidget()
        if parent is None:
            return
        if parent is not self._overlay_parent:
            if self._overlay_parent is not None:
                self._overlay_parent.removeEventFilter(self)
            self._overlay_parent = parent
            parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self.raise_()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """跟随遮罩父控件的尺寸变化同步几何。"""
        if (
            obj is self._overlay_parent
            and self._overlay_parent is not None
            and event.type() == QEvent.Type.Resize
        ):
            self.setGeometry(self._overlay_parent.rect())
        return False

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后重绘（颜色在绘制期现取）。"""
        self.update()

    def _variant_color(self) -> QColor:
        """当前变体的弧线颜色（绘制期现取，跟随主题与强调色变化）。"""
        # success 与 default 同取强调色，与 StyledProgress / StyledProgressCircle
        # 的 COLOR_CONFIG 约定保持一致
        if self._variant == "warning":
            return tm.warning
        if self._variant == "danger":
            return tm.danger
        return tm.accent

    def _backdrop_color(self) -> QColor:
        """当前遮罩填充色（绘制期现取，跟随主题与强调色变化）。"""
        if self._backdrop == "opaque":
            return QColor(tm.surface)
        return tm.with_alpha(tm.black, self.OVERLAY_ALPHA)

    def _sweep_state(self) -> tuple[float, float]:
        """由周期相位算出运动弧的头部角度（Qt 角度约定）与当前扫角。

        以「距 12 点钟的顺时针行程」建模：头尾各自在一个周期内平均转过 360°，
        叠加一对反相正弦速度调制（头快则尾慢），因此：

        1. 两端角速度恒为正 —— 头部始终向前、拖尾只会追赶，不会倒退；
        2. 扫角在 ``MIN_SWEEP_DEG`` / ``MAX_SWEEP_DEG`` 之间平滑往返；
        3. 周期首尾状态一致，衔接无缝。

        Returns:
            tuple[float, float]: ``(头部角度, 扫角)``。头部角度为 Qt 角度
            （0° 在 3 点钟、逆时针为正），扫角为沿顺时针方向的弧长（度）。
        """
        phase = (self._phase_ms / self.CYCLE_MS) % 1.0
        wave = math.sin(2.0 * math.pi * phase)
        mid = (self.MIN_SWEEP_DEG + self.MAX_SWEEP_DEG) / 2.0
        amplitude = (self.MAX_SWEEP_DEG - self.MIN_SWEEP_DEG) / 4.0
        head_travel = 360.0 * phase + mid - amplitude * wave
        tail_travel = 360.0 * phase + amplitude * wave
        head_deg = (90.0 - head_travel) % 360.0
        return head_deg, head_travel - tail_travel

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制遮罩（可选）与旋转圆环。"""
        painter = QPainter(self)
        if not painter.isActive():
            return

        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            if self._overlay:
                # 遮罩底色：dim 半透明黑色压暗（在同色卡片/浅色内容上都能看出
                # 「内容被遮住」）/ opaque 主题表面色实色（启动屏，只留圆环可见）
                painter.fillRect(self.rect(), self._backdrop_color())

            self._paint_spinner(painter)
        finally:
            if painter.isActive():
                painter.end()

    def _paint_spinner(self, painter: QPainter) -> None:
        """在控件中心绘制纯色圆角运动弧。"""
        config = self.SIZE_CONFIG[self._size]
        stroke = float(config["stroke"])
        diameter = float(config["size"])

        # 空间不足时等比缩小，避免圆环被裁切（遮罩模式下父控件可能较小）
        available = float(min(self.width(), self.height())) - stroke
        if available < diameter:
            ratio = max(0.0, available / diameter)
            diameter *= ratio
            stroke = max(1.0, stroke * ratio)
        if diameter <= 0:
            return
        # 笔宽不超过半径，避免自交
        stroke = min(stroke, diameter / 2.0)

        radius = (diameter - stroke) / 2.0
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        circle_rect = QRectF(cx - radius, cy - radius, radius * 2.0, radius * 2.0)

        painter.setBrush(Qt.BrushStyle.NoBrush)

        # 纯色圆角弧：头部（起点）位于顺时针前进侧，弧体逆时针向后延伸当前扫角。
        # 无轨道底环、无透明度渐变 —— Win11 ProgressRing 的观感即
        # 「实色弧 + 两端 RoundCap + 弧长呼吸式伸缩 + 整体旋转」。
        head_deg, sweep = self._sweep_state()
        painter.setPen(
            QPen(
                self._variant_color(),
                stroke,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawArc(
            circle_rect,
            int(round(head_deg * 16)),
            int(round(sweep * 16)),
        )