"""自研合成器 —— 「整块虚拟桌面云母层 + 窗口视口」的呈现层。

问题
----
快速拖动窗口时，背景必须**每帧**按新的屏幕位置重新取样（云母纹理锚定在壁纸
上，不随窗口平移）。但 Qt Widgets 的背存（backing store）是**顶层窗口共用**的：
某块区域一变脏，``QWidgetBackingStore::sync()`` 会让所有与该区域相交的控件
自底向上重绘。Mica 背景是最底层、覆盖全窗的控件，对它做整窗 ``update()``
等于**把整个 UI（侧边栏 / 文件列表 / 工具条…）拖进来一起重绘**。

实测（窗口 1600×1000、上层 5 个内容控件，见 ``scripts/diag_mica_repaint.py``）：

=================  ============  ==================  ==================
失效策略           单帧耗时      上层 UI 重绘面积    相对基线
=================  ============  ==================  ==================
整窗 ``update()``  0.805 ms      100 % 全窗×帧        398×
32px 条带          0.041 ms       3.2 % 全窗×帧       20×
完全不失效         0.002 ms       0 %                  1×
=================  ============  ==================  ==================

即：**拖动的成本不在 Mica 自己（1:1 blit 仅 0.32 ms / 6.1 MB），而在被连带
重绘的上层 UI**。合成器的职责就是把这个连带成本压到可控。

思路：整块层 + 视口取样 + 自适应呈现
----------------------------------
1. **层（sheet）覆盖整块虚拟桌面**，以 1:1 屏幕分辨率渲染一次；窗口只是一个
   "窗户"，按当前屏幕矩形从层里取一块子矩形 —— 纯函数 ``sheet[win]``，
   **不检查运动状态**（无速度/加速度/方向判定，无拖动场、无越界续烘）。
   位移、跨屏、缩放、最大化统统是同一个映射，因此不存在"松手跳变"。
2. **1:1 整型 blit**：层与虚拟桌面同分辨率时源矩形恰为整数，走 Qt 的
   ``memcpy`` 快路径（实测 18.5 GB/s），且**不重采样** —— 1px 颗粒的抖动
   图案被原样保留，不会被双线性抹平（这是消除渐变色带的前提）。
3. **自适应呈现调度**：交互期的每个 move/resize 事件先问合成器
   :meth:`ViewportCompositor.advise`，只有确实需要时才整窗重绘：

   * 取样结果未变（亚像素抖动/原地微动）⇒ **跳过**；
   * 窗口位置跳变（最大化 / 吸附 / 还原 / 跨屏瞬移）⇒ **立即**呈现，
     不留延迟（满足"位置跳变时必须及时刷新"）；
   * 常规拖动 ⇒ 按**实测绘制成本**自适应节流，使重绘占用的主线程时间不超过
     :data:`PRESENT_BUDGET`。绘制便宜时等同逐帧（16 ms ≈ 一个显示帧，无感知
     延迟）；昂贵时才降频。

   为什么降频不会"看出来"：云母色调场是极低频量（实测网格级相邻像素差分
   0.005 LSB），一次 40 ms 的降频只让背景位置滞后约 60 屏幕像素 ≈ 0.06 LSB，
   远低于 8-bit 量化步长 —— 肉眼不可辨，而省下的是整窗 UI 重绘。

本模块只依赖 Qt 的绘制原语与 :mod:`ui.mica.drag` 的纯几何，可在无 GUI 环境
下对调度逻辑完整单元测试。
"""

from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import QElapsedTimer, QRect, QRectF
from PySide6.QtGui import QColor, QPainter, QPixmap

from .drag import ViewportLayer, layer_to_source_clamped

__all__ = [
    "PRESENT_BUDGET",
    "PRESENT_DEFER",
    "PRESENT_NOW",
    "PRESENT_SKIP",
    "JUMP_THRESHOLD_PX",
    "MIN_PRESENT_INTERVAL_MS",
    "ViewportCompositor",
]


# ---------------------------------------------------------------------------
# 呈现决策
# ---------------------------------------------------------------------------

#: 无需呈现（取样结果未变 / 层未就绪）。
PRESENT_SKIP: int = 0
#: 立即呈现（首次 / 位置跳变 / 已过节流窗口）。
PRESENT_NOW: int = 1
#: 处于节流窗口内，稍后需补一次（由调用方按 :meth:`defer_delay_ms` 排定时器）。
PRESENT_DEFER: int = 2

#: 交互期允许重绘占用的主线程时间比例。绘制成本 / 该比例 = 目标呈现间隔。
#: 0.3 表示"最坏也只花 30% 主线程时间做背景重绘"，其余留给输入与业务逻辑。
PRESENT_BUDGET: float = 0.30

#: 呈现间隔下限（毫秒）—— 约一个 60Hz 显示帧。绘制足够便宜时逐帧呈现，
#: 用户感知不到任何延迟；只有绘制昂贵时才按成本自动降频。
MIN_PRESENT_INTERVAL_MS: float = 16.0

#: 呈现间隔上限（毫秒）—— 降频的地板（约 20Hz），保证背景位置不会离屏太远。
MAX_PRESENT_INTERVAL_MS: float = 50.0

#: 判定"位置跳变"的位移阈值（虚拟桌面像素）。超过即在**首个事件**立即呈现，
#: 使最大化 / Win+方向键吸附 / 还原 / 跨屏瞬移等场景零延迟刷新。
JUMP_THRESHOLD_PX: int = 96

#: 绘制成本的指数滑动平均权重（新样本占比）。
_COST_EMA_ALPHA: float = 0.3
#: 成本 EMA 初值（毫秒）—— 保守取"较贵"，避免首帧就过度乐观地高频重绘。
_COST_EMA_INIT_MS: float = 6.0


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _is_integer(value: float) -> bool:
    """判定 ``value`` 是否为（近似）整数。"""
    return abs(value - round(value)) < 1e-6


def _same_rect(a: Tuple[float, float, float, float],
               b: Tuple[float, float, float, float], tol: float = 0.5) -> bool:
    """两个源矩形在半个像素内视为相同（取整后画面一致）。"""
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# 合成器
# ---------------------------------------------------------------------------


class ViewportCompositor:
    """整块虚拟桌面云母层 + 窗口视口取样 + 自适应呈现调度。

    用法::

        comp = ViewportCompositor()
        comp.set_layer(layer, pixmap)          # 烘焙完成后提交一次
        # 交互（move / resize）事件：
        decision = comp.advise(win_rect)
        if decision == PRESENT_NOW:
            widget.update()
        elif decision == PRESENT_DEFER:
            QTimer.singleShot(comp.defer_delay_ms(), widget.update)
        # 绘制：
        comp.paint(painter, widget.rect(), win_rect, dpr, opacity, surface)

    状态机只有三个字段（已呈现的源矩形 / 已呈现的窗口矩形 / 绘制成本 EMA），
    **不跟踪速度、方向、拖动会话** —— 窗口位置是唯一输入。
    """

    def __init__(self) -> None:
        self._layer: Optional[ViewportLayer] = None
        self._pixmap: Optional[QPixmap] = None
        self._src: Optional[Tuple[float, float, float, float]] = None
        self._win: Optional[Tuple[int, int, int, int]] = None
        self._cost_ema: float = _COST_EMA_INIT_MS
        self._clock = QElapsedTimer()
        self._clock.start()
        self._defer_pending: bool = False

    # -- 层（sheet）生命周期 ------------------------------------------------

    def set_layer(self, layer: ViewportLayer, pixmap: QPixmap) -> None:
        """提交一块新的云母层（烘焙完成后调用；此后取样为纯几何运算）。

        Args:
            layer: 层几何（覆盖整块虚拟桌面）。
            pixmap: 层在显示分辨率上的像素（与层 ``width/height`` 一致）。
        """
        self._layer = layer
        self._pixmap = pixmap
        # 新层 ⇒ 上次呈现的源矩形失效，强制下一次 advise 立即呈现。
        self._src = None
        self._win = None

    def set_geometry(self, layer: Optional[ViewportLayer]) -> None:
        """仅替换层几何（像素保留），并作废呈现锚点。

        供 :class:`~ui.mica.material.MicaMaterial` 的 ``_layer`` 属性 setter
        使用 —— 保持 ``material._layer = ...`` 的旧字段读写契约，同时把层状态
        收敛到合成器单一数据源（避免两份拷贝漂移）。

        Args:
            layer: 新层几何；``None`` 表示清除。
        """
        self._layer = layer
        self.invalidate_anchor()

    def set_pixels(self, pixmap: Optional[QPixmap]) -> None:
        """仅替换层像素（几何保留），并作废呈现锚点。

        Args:
            pixmap: 新层像素；``None`` 表示清除。
        """
        self._pixmap = pixmap
        self.invalidate_anchor()

    def clear(self) -> None:
        """丢弃层（dispose / 降级到纯色时调用）。"""
        self._layer = None
        self._pixmap = None
        self._src = None
        self._win = None
        self._defer_pending = False

    @property
    def layer(self) -> Optional[ViewportLayer]:
        """当前层几何。"""
        return self._layer

    @property
    def pixmap(self) -> Optional[QPixmap]:
        """当前层像素。"""
        return self._pixmap

    @property
    def ready(self) -> bool:
        """层与像素是否均已就绪（可取样）。"""
        return (
            self._layer is not None
            and self._pixmap is not None
            and not self._pixmap.isNull()
        )

    # -- 取样 --------------------------------------------------------------

    def source_rect(
        self, win: Tuple[int, int, int, int]
    ) -> Optional[Tuple[float, float, float, float]]:
        """窗口矩形 → 层内源子矩形（分辨率无关，永不返回 ``None``）。

        映射：``源 = (win − region_origin) × layer_px / region_px``。
        窗口部分/完全落在层区域之外时把该轴钳制到层边缘 —— 保证任何时刻都能
        从层里取到内容，绝不退化成纯色（Mica 消失）。缩放中同样可用（按当前
        尺寸映射），真正的密度修正由稳定后的重烘焙完成。

        Args:
            win: ``(x, y, w, h)`` 窗口矩形（虚拟桌面像素）。

        Returns:
            ``(sx, sy, sw, sh)``；层未就绪时 ``None``。
        """
        if not self.ready:
            return None
        return layer_to_source_clamped(self._layer, win)  # type: ignore[arg-type]

    # -- 呈现调度 ----------------------------------------------------------

    def interval_ms(self) -> float:
        """当前目标呈现间隔（毫秒）：由实测绘制成本自适应得出。

        取 ``成本 EMA / PRESENT_BUDGET``，并钳制到
        ``[MIN_PRESENT_INTERVAL_MS, MAX_PRESENT_INTERVAL_MS]``。绘制只要够便宜
        （< 4.8 ms）就锁定在下限 16 ms —— 即逐帧呈现，无感知延迟。

        Returns:
            目标间隔（毫秒）。
        """
        raw = self._cost_ema / PRESENT_BUDGET
        return max(MIN_PRESENT_INTERVAL_MS, min(MAX_PRESENT_INTERVAL_MS, raw))

    def advise(self, win: Tuple[int, int, int, int]) -> int:
        """询问"此刻是否需要把窗口背景重新呈现一次"。

        判定只依赖**窗口矩形本身**（无运动状态）：

        1. 层未就绪 ⇒ ``PRESENT_SKIP``（交给兜底静态场）；
        2. 取样结果与上次呈现一致（半像素内）⇒ ``PRESENT_SKIP`` —— 亚像素
           微动 / 原地抖动不产生任何重绘；
        3. **位置跳变**（首次 / 尺寸变化 / 单轴位移 > :data:`JUMP_THRESHOLD_PX`）
           ⇒ ``PRESENT_NOW`` —— 最大化、吸附、还原、跨屏瞬移零延迟刷新；
        4. 距上次呈现已超过 :meth:`interval_ms` ⇒ ``PRESENT_NOW``；
        5. 否则 ⇒ ``PRESENT_DEFER``（节流窗口内，稍后补一次即可）。

        Args:
            win: ``(x, y, w, h)`` 窗口当前矩形（虚拟桌面像素）。

        Returns:
            :data:`PRESENT_SKIP` / :data:`PRESENT_NOW` / :data:`PRESENT_DEFER`。
        """
        if not self.ready:
            return PRESENT_SKIP
        src = self.source_rect(win)
        if src is None:
            return PRESENT_SKIP

        if self._src is None or self._win is None:
            return PRESENT_NOW
        if _same_rect(src, self._src):
            return PRESENT_SKIP
        if self._is_jump(win):
            return PRESENT_NOW
        if self._clock.elapsed() >= self.interval_ms():
            return PRESENT_NOW
        self._defer_pending = True
        return PRESENT_DEFER

    def defer_delay_ms(self) -> int:
        """``PRESENT_DEFER`` 后应等待多少毫秒再补一次呈现。

        Returns:
            剩余等待时间（毫秒，向上取整），恒 ≥ 1。
        """
        remain = self.interval_ms() - self._clock.elapsed()
        return max(1, int(remain + 0.999))

    def _is_jump(self, win: Tuple[int, int, int, int]) -> bool:
        """相对上次呈现，窗口是否发生了"跳变"（而非连续拖动）。

        判据：尺寸变化，或任一轴位移超过 :data:`JUMP_THRESHOLD_PX`。
        连续快速拖动在单个 move 事件上的位移通常远小于该阈值（60Hz 下拖
        1500 px/s 也只有 25 px/事件），因此不会误判为跳变。

        Args:
            win: ``(x, y, w, h)`` 窗口当前矩形。

        Returns:
            是跳变则 ``True``。
        """
        last = self._win
        if last is None:
            return True
        if int(win[2]) != int(last[2]) or int(win[3]) != int(last[3]):
            return True
        return (
            abs(int(win[0]) - int(last[0])) > JUMP_THRESHOLD_PX
            or abs(int(win[1]) - int(last[1])) > JUMP_THRESHOLD_PX
        )

    def note_presented(
        self,
        win: Tuple[int, int, int, int],
        cost_ms: Optional[float] = None,
    ) -> None:
        """记录一次真实呈现（更新锚点与成本 EMA）。

        Args:
            win: 本次呈现所用的窗口矩形。
            cost_ms: 本次绘制耗时（毫秒）；``None`` 时不更新成本 EMA。
        """
        src = self.source_rect(win)
        if src is not None:
            self._src = tuple(float(v) for v in src)
        self._win = tuple(int(v) for v in win)
        self._defer_pending = False
        self._clock.restart()
        if cost_ms is not None and cost_ms >= 0.0:
            a = _COST_EMA_ALPHA
            self._cost_ema = self._cost_ema * (1.0 - a) + float(cost_ms) * a

    def invalidate_anchor(self) -> None:
        """作废呈现锚点，使下一次 :meth:`advise` 必然返回 ``PRESENT_NOW``。

        用于层内容变化（新烘焙 / 主题 / 参数）之外的"必须立刻重画"场景，
        例如淡入淡出开始、窗口重新可见。
        """
        self._src = None
        self._win = None

    # -- 绘制 --------------------------------------------------------------

    def paint(
        self,
        painter: QPainter,
        rect: QRect,
        win: Tuple[int, int, int, int],
        dpr: float = 1.0,
        opacity: float = 1.0,
        surface_color: Optional[QColor] = None,
    ) -> bool:
        """把层按窗口位置取样绘制到 ``rect``（1:1 时走 memcpy 快路径）。

        两条快路径，按是否严格 1:1 自动选择：

        * **整型 1:1**（层分辨率 == 虚拟桌面分辨率，且源矩形恰落在整像素）
          ⇒ ``SmoothPixmapTransform=False`` + ``QRect`` 绘制。Qt 光栅引擎识别
          为纯平移，退化为逐行 ``memcpy``（实测 18.5 GB/s）；且**不重采样**，
          1px 颗粒的抖动图案被原样保留 —— 这是渐变无色彩断层的前提。
        * **亚像素 / 缩放** ⇒ ``SmoothPixmapTransform=True`` + ``QRectF`` 绘制，
          双线性取样，避免台阶式跳动。

        绘制全程**不透明**（混合已在 worker 端预合成进层像素），避免第二次
        8-bit 量化（banding 根因之一）；只有当 ``opacity < 1.0``（淡入淡出）
        或取样区域不足以铺满时才先铺一层实色底。

        Args:
            painter: 画笔（调用方负责生命周期）。
            rect: 目标矩形（控件 ``rect()``，逻辑像素）。
            win: ``(x, y, w, h)`` 窗口矩形（虚拟桌面像素）。
            dpr: 控件的设备像素比，用于判定是否严格 1:1。
            opacity: 绘制不透明度（淡入淡出用），1.0 为完全不透明。
            surface_color: 需要打底时的实色；``None`` 表示不打底。

        Returns:
            成功从层取样绘制返回 ``True``；层未就绪返回 ``False``。
        """
        if not self.ready:
            return False
        src = self.source_rect(win)
        if src is None:
            return False

        sx, sy, sw, sh = src
        pixmap = self._pixmap
        # 目标在**设备像素**下的尺寸（画笔的设备变换含 dpr）。
        dev_w = float(rect.width()) * float(dpr)
        dev_h = float(rect.height()) * float(dpr)
        integral = (
            all(_is_integer(v) for v in (sx, sy, sw, sh))
            and abs(sw - dev_w) < 0.5
            and abs(sh - dev_h) < 0.5
        )
        covers = (
            opacity >= 0.999
            and sw >= dev_w - 0.5
            and sh >= dev_h - 0.5
        )

        # 只有在不透明且完全覆盖时才省掉整窗实色填充（省一次全窗写）。
        if surface_color is not None and not covers:
            painter.fillRect(rect, surface_color)

        painter.setRenderHint(QPainter.SmoothPixmapTransform, not integral)
        if opacity < 0.999:
            painter.setOpacity(opacity)
        try:
            if integral:
                painter.drawPixmap(
                    QRect(rect), pixmap, QRect(int(sx), int(sy), int(sw), int(sh))
                )
            else:
                painter.drawPixmap(QRectF(rect), pixmap, QRectF(sx, sy, sw, sh))
        finally:
            if opacity < 0.999:
                painter.setOpacity(1.0)
        return True
