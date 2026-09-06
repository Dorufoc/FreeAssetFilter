"""单层简约背景组件（MinimalistBackgroundWidget）。

QUIET 单层绘制约束（强制）：

- 整个控件只做一层不透明呈现：``paintEvent`` 向屏幕只做单次 ``fillRect``
  （ambient 纯色、交互态快速渐变、降级态）或单次 ``drawImage``
  （稳定态抖动缓存图、主题交叉过渡期的离屏混合帧）。
- 禁止多层叠加呈现：不得向屏幕先后多次 ``fillRect`` / ``drawPixmap`` /
  叠加半透明层，不得依赖下层透出或 ``WA_TranslucentBackground``。
  主题交叉过渡的混合在离屏 ``QImage`` 内完成（旧帧铺底 + 新帧按进度
  叠入），呈现仍是单次不透明 ``drawImage``，单层语义不变。
- 禁止半透明穿透：所有参与绘制的颜色 alpha 必须为 255，全不透明，
  不得依赖下层透出或 ``WA_TranslucentBackground``。

行为：

- ambient 关闭时全域填充 G1 纯色（``tm.surface``，不抖动）。
- ambient 开启（默认）时自下而上单层线性渐变，叠加强度按主题区分
  （预混合为全不透明色，混合比例不可改）：

  - 浅色主题：bottom=blend(G1, accent, 0.0)（accent 0% 不透明，
    即 100% 透明=G1），mid=blend(G1, accent, 0.1)（10% 不透明），
    top=blend(G1, accent, 0.2)（20% 不透明，即 80% 透明）。
  - 深色主题（更克制）：bottom=blend(G1, accent, 0.0)（0% 不透明，
    即 100% 透明=G1），mid=blend(G1, accent, 0.05)（5% 不透明），
    top=blend(G1, accent, 0.10)（10% 不透明，即 90% 透明）。

抗色带（banding）：

- 上述微弱大面积渐变在 8-bit 下仅几个 LSB，QPainter 直接量化会产生
  可见台阶。本组件复用云母 Mica 的抗色带思路
  （见 ``freeassetfilter/ui/mica/engine.py``）：交错梯度噪声 IGN
  （三常数 ``_IGN_C1`` / ``_IGN_C2`` / ``_IGN_K``，幅值 ``±0.7LSB``），
  抖动锚定窗口本地原点 ``(0, 0)``；float 全程、显示分辨率一次性 ``rint``
  量化（禁截断，截断会引入 -0.5LSB 系统性偏置）；1:1 呈现；
  预合成全程保持不透明。
- 单层语义不变：渐变先在离屏 ``QImage`` 中预合成（含抖动量化），
  ``paintEvent`` 稳定态只做单次 ``drawImage`` 呈现，无透明叠加、无第二层；
  抖动绝不加在小图再放大（避免块状噪点），只在显示分辨率上叠加 1px 颗粒。
- 交互期（窗口拖拽/缩放）走无抖动快速渐变保证流畅，settle 80ms 后
  （复用 ``custom_background.SETTLE_INTERVAL_MS`` 思路）切回抖动缓存；
  numpy 缺失时优雅降级为原渐变 ``fillRect``。
"""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING

from PySide6.QtCore import QElapsedTimer, QRect, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QWidget
from theme import tm

if TYPE_CHECKING:
    import numpy as np


#: 交错梯度噪声（Interleaved Gradient Noise, IGN）的两个方向频率与放大系数。
#: 与云母 Mica（``mica/engine.py``）同值：逐像素把 ``(x, y)`` 映射为
#: ``[0, 1)`` 上的低差异序列（Jorge Jimenez）。
_IGN_C1: float = 0.06711056
_IGN_C2: float = 0.00583715
_IGN_K: float = 52.9829189

#: 最终空间抖动幅值（LSB，±0.7 LSB，与 Mica 标定值一致）。
_DITHER_AMP_DEFAULT: float = 0.7

#: 抖动缓存条目上限（LRU，键为 ``(w, h, bottom, mid, top, amp)``）。
_DITHER_CACHE_MAX: int = 2

#: 交互停止后切回抖动缓存的延时（毫秒，复用 custom_background 80ms 思路）。
_SETTLE_INTERVAL_MS: int = 80

#: 主题交叉过渡时长（毫秒，对齐 Mica XFADE_DURATION_MS 与内容层过渡 280ms）。
XFADE_DURATION_MS: int = 280

#: 交叉过渡逐帧间隔（毫秒，约 60fps）。
XFADE_TICK_MS: int = 16


class _DitherUnavailableError(RuntimeError):
    """内部异常：抖动预合成不可用（numpy 缺失），调用方捕获后降级。"""


def blend_over(base: QColor, overlay: QColor, opacity: float) -> QColor:
    """不透明 alpha 混合（overlay 覆盖 base）。

    Args:
        base: 底层颜色（不被修改）。
        overlay: 顶层颜色（不被修改）。
        opacity: 顶层不透明度，钳制到 0~1 区间。

    Returns:
        QColor: 混合后的新颜色，alpha 恒为 255。
    """
    clamped: float = max(0.0, min(1.0, opacity))
    red: int = round(base.red() * (1.0 - clamped) + overlay.red() * clamped)
    green: int = round(base.green() * (1.0 - clamped) + overlay.green() * clamped)
    blue: int = round(base.blue() * (1.0 - clamped) + overlay.blue() * clamped)
    return QColor(red, green, blue, 255)


def compute_minimalist_gradient_colors() -> tuple[QColor, QColor, QColor]:
    """计算自下而上的单层渐变三色（叠加强度按主题区分）。

    从 ``theme.tm`` 取 G1（``tm.surface`` 拷贝）与强调色（``tm.accent`` 拷贝，
    auto 已由 tm 解析）；分支依据 ``tm.is_dark_theme()``：

    - 浅色主题：bottom=blend(G1, accent, 0.0)（accent 0% 不透明，
      即 100% 透明=G1），mid=blend(G1, accent, 0.1)（10% 不透明），
      top=blend(G1, accent, 0.2)（20% 不透明，即 80% 透明）。
    - 深色主题（更克制）：bottom=blend(G1, accent, 0.0)（0% 不透明，
      即 100% 透明=G1），mid=blend(G1, accent, 0.05)（5% 不透明），
      top=blend(G1, accent, 0.10)（10% 不透明，即 90% 透明）。

    单层不透明预混合：三者 alpha 均为 255。返回的三色直接喂给
    :func:`render_minimalist_image` 做离屏预合成，抖动在显示分辨率上以
    IGN（``±0.7LSB``、锚定窗口本地 ``(0, 0)``）一次性 ``rint`` 量化叠加。

    tm 返回的是缓存共享对象，调用方必须先 ``QColor()`` 拷贝，
    否则会污染缓存。

    Returns:
        tuple[QColor, QColor, QColor]: (bottom, mid, top) 三色。
    """
    base: QColor = QColor(tm.surface)
    accent: QColor = QColor(tm.accent)
    if tm.is_dark_theme():
        bottom: QColor = blend_over(base, accent, 0.0)
        mid: QColor = blend_over(base, accent, 0.05)
        top: QColor = blend_over(base, accent, 0.10)
    else:
        bottom = blend_over(base, accent, 0.0)
        mid = blend_over(base, accent, 0.1)
        top = blend_over(base, accent, 0.2)
    return (bottom, mid, top)


def _ign_offsets(
    w: int,
    h: int,
    ox: int = 0,
    oy: int = 0,
    amp: float = _DITHER_AMP_DEFAULT,
) -> np.ndarray:
    """生成窗口本地锚定的 IGN 抖动偏移 ``(h, w, 3)``，取值 ``±amp``。

    公式复用云母 Mica（``mica/engine.py::_ign_offsets``）：float64 一维坐标
    ``frac(K * frac(c1 * x + c2 * y)) * 2 - 1`` 再乘 ``amp``；RGB 三通道同值；
    无 RNG、完全确定性；``ox`` / ``oy`` 锚定窗口本地 ``(0, 0)``
    （本层固定于窗口客户区，不随屏幕移动，与 Mica 屏幕锚定的差异见模块文档）。

    一维部分保留 float64 精度，只有最后的广播加降为 float32，避免大图上的
    临时 float64 缓冲。

    Args:
        w: 目标宽度（像素）。
        h: 目标高度（像素）。
        ox: 锚定原点 x（窗口本地坐标，默认 0）。
        oy: 锚定原点 y（窗口本地坐标，默认 0）。
        amp: 抖动幅值（LSB，默认 ``_DITHER_AMP_DEFAULT`` 即 ±0.7）。

    Returns:
        float32 ``(h, w, 3)`` 偏移数组，可直接与 0..255 的像素值相加。

    Raises:
        ImportError: numpy 不可用时由函数内延迟导入抛出。
        ValueError: 尺寸非法时抛出。
    """
    import numpy as np

    width: int = int(w)
    height: int = int(h)
    if width <= 0 or height <= 0:
        raise ValueError(f"IGN 抖动尺寸非法: {(w, h)}")
    xs = (np.arange(width, dtype=np.float64) + float(ox)) * _IGN_C1
    ys = (np.arange(height, dtype=np.float64) + float(oy)) * _IGN_C2
    base = xs.astype(np.float32).reshape(1, -1) + ys.astype(np.float32).reshape(-1, 1)
    base -= np.floor(base)  # frac(c1·x + c2·y)
    base *= np.float32(_IGN_K)
    base -= np.floor(base)  # frac(K · frac(...))
    base -= np.float32(0.5)
    base *= np.float32(2.0 * float(amp))
    base = base.reshape(height, width, 1)
    offsets = np.empty((height, width, 3), dtype=np.float32)
    offsets[:] = base  # RGB 三通道同值
    return offsets


def render_minimalist_image(w: int, h: int, bottom: QColor, mid: QColor, top: QColor) -> QImage:
    """离屏预合成单层渐变 + IGN 抖动，返回全不透明 ``QImage``。

    管线：``QImage(Format_RGB32)`` 离屏单次画渐变 → numpy float32 加抖动 →
    clip → ``rint``（禁截断，截断会引入 -0.5LSB 系统性偏置）→ uint8 写回；
    ``bytesPerLine`` 按 stride 处理；alpha 通道不动（恒 255）。

    numpy 为函数内延迟导入：缺失时抛出 :class:`_DitherUnavailableError`，
    由调用方捕获并降级为原渐变 ``fillRect``。

    Args:
        w: 目标宽度（像素）。
        h: 目标高度（像素）。
        bottom: 渐变底部色（不透明）。
        mid: 渐变中部色（不透明）。
        top: 渐变顶部色（不透明）。

    Returns:
        QImage: ``Format_RGB32`` 全不透明抖动渐变图，可 1:1 ``drawImage`` 呈现。

    Raises:
        ValueError: 尺寸非法时抛出。
        _DitherUnavailableError: numpy 不可用时抛出。
    """
    import numpy as np

    width: int = int(w)
    height: int = int(h)
    if width <= 0 or height <= 0:
        raise ValueError(f"预合成尺寸非法: {(w, h)}")
    try:
        import numpy as np
    except ImportError as exc:
        raise _DitherUnavailableError("numpy 不可用，无法做抖动预合成") from exc

    image = QImage(width, height, QImage.Format_RGB32)
    painter = QPainter(image)
    gradient = QLinearGradient(0, height, 0, 0)
    gradient.setColorAt(0.0, bottom)
    gradient.setColorAt(0.5, mid)
    gradient.setColorAt(1.0, top)
    painter.fillRect(0, 0, width, height, QBrush(gradient))
    painter.end()

    stride: int = image.bytesPerLine()
    raw = np.frombuffer(image.bits(), dtype=np.uint8).reshape(height, stride)
    pixels = raw[:, : width * 4].reshape(height, width, 4)
    # Format_RGB32 小端内存序为 B/G/R/0xFF；三通道加同值抖动，与通道序无关。
    rgb = pixels[:, :, 0:3].astype(np.float32)
    rgb += _ign_offsets(width, height)
    np.clip(rgb, 0.0, 255.0, out=rgb)
    # 必须先 rint 再转 uint8：astype 是截断，会带来 -0.5LSB 偏置并退化抖动。
    pixels[:, :, 0:3] = np.rint(rgb).astype(np.uint8)
    # alpha 字节（索引 3）保持 0xFF 不动。
    return image


class MinimalistBackgroundWidget(QWidget):
    """单层简约背景层（含 IGN 抗色带抖动）。

    QUIET 单层绘制：ambient 关闭时全域 G1 纯色（不抖动）；开启时自下而上
    单层渐变。``paintEvent`` 内只做单次呈现（稳定态单次 ``drawImage`` 抖动
    缓存图，交互态/降级态单次 ``fillRect`` 原渐变），无多层叠加、无 alpha
    穿透（全不透明）。作为独立背景层使用：鼠标事件穿透。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """初始化背景层，默认开启 ambient 渐变。

        Args:
            parent: 父控件（通常为主窗口的内容层容器）。
        """
        super().__init__(parent)
        self._ambient_enabled: bool = True
        self._interacting: bool = False
        self._dither_cache: OrderedDict[tuple[int, int, int, int, int, float], QImage] = OrderedDict()
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_INTERVAL_MS)
        self._settle_timer.timeout.connect(self._on_settle)
        # 主题交叉过渡状态（仿 MicaMaterial._start_xfade 材质内淡入）：
        # _pending_backdrop 由切换前抓拍暂存，sync_theme 时转为正式底图；
        # 混合在离屏 QImage 内完成，呈现仍是单次不透明 drawImage。
        self._pending_backdrop: QPixmap | None = None
        self._xfade_backdrop: QPixmap | None = None
        self._xfade_active: bool = False
        self._xfade_clock = QElapsedTimer()
        self._xfade_timer = QTimer(self)
        self._xfade_timer.setInterval(XFADE_TICK_MS)
        self._xfade_timer.timeout.connect(self._on_xfade_tick)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    @property
    def ambient_enabled(self) -> bool:
        """当前是否开启 ambient 渐变（关闭时为 G1 纯色）。

        Returns:
            bool: ambient 开关状态。
        """
        return self._ambient_enabled

    def set_ambient_enabled(self, enabled: bool) -> None:
        """设置 ambient 开关并触发重绘。

        Args:
            enabled: True 开启渐变，False 使用 G1 纯色。
        """
        self._ambient_enabled = bool(enabled)
        self.update()

    def sync_theme(self) -> None:
        """主题切换同步入口：以旧帧为底图启动材质内交叉淡入（保留抖动缓存）。

        缓存键已包含渐变三色，新主题天然 miss 后按需预合成；保留旧主题
        缓存可供切回时命中。若切换前已抓拍（见 capture_pre_theme_state），
        旧帧在重绘间隙始终参与混合呈现，不漏出 _root G1 兜底；无抓拍时
        仅触发重绘（与之前一致）。
        """
        pending = self._pending_backdrop
        self._pending_backdrop = None
        if pending is not None and not pending.isNull():
            self._start_xfade(pending)
        self.update()

    def capture_pre_theme_state(self) -> None:
        """主题翻转前抓拍当前背景帧（由主窗口在 tm 切换前调用）。

        用 ``grab()`` 渲染当前屏上状态；过渡中连切时抓到的是当前混合态，
        新过渡从屏幕现状连续出发（同 Mica _capture_visual_state 连切语义）。
        未显示或抓拍失败时不暂存，sync_theme 退化为普通重绘。
        """
        if not self.isVisible():
            return
        try:
            snapshot = self.grab()
        except Exception:  # noqa: BLE001 - 抓拍失败不阻塞主题切换
            return
        if snapshot.isNull():
            return
        self._pending_backdrop = snapshot

    def refresh_background(self) -> None:
        """按当前主题重新绘制背景（触发一次重绘）。"""
        self.update()

    def handle_window_resize(self) -> None:
        """窗口尺寸变化入口（由 MainWindow 的 resizeEvent 转发）。

        进入交互态：重启 settle 定时器并重绘，交互期间 ``paintEvent`` 走
        无抖动快速渐变保证拖拽流畅（复用 custom_background 80ms 思路）。
        """
        self._interacting = True
        self._settle_timer.start()  # 运行中则重启
        self.update()

    def _on_settle(self) -> None:
        """交互停止：退出交互态并重绘（走抖动缓存呈现）。"""
        self._interacting = False
        self.update()

    # ------------------------------------------------------------------
    # 主题交叉过渡（仿 MicaMaterial._start_xfade 材质内淡入，单层呈现）
    # ------------------------------------------------------------------

    def _xfade_progress(self) -> float:
        """交叉过渡进度（0~1）；未激活时恒为 1.0。"""
        if not self._xfade_active or not self._xfade_clock.isValid():
            return 1.0
        t = self._xfade_clock.elapsed() / float(XFADE_DURATION_MS)
        if t < 0.0:
            return 0.0
        return 1.0 if t > 1.0 else t

    def _start_xfade(self, backdrop: QPixmap) -> None:
        """以旧背景帧为底图启动交叉过渡：新帧自进度 0 淡入（280ms）。"""
        self._xfade_backdrop = backdrop
        self._xfade_active = True
        self._xfade_clock.restart()
        if not self._xfade_timer.isActive():
            self._xfade_timer.start()

    def _finish_xfade(self) -> None:
        """结束并清理交叉过渡：释放旧帧、停机。"""
        self._xfade_active = False
        self._xfade_backdrop = None
        if self._xfade_timer.isActive():
            self._xfade_timer.stop()

    def _on_xfade_tick(self) -> None:
        """交叉过渡逐帧推进：到时即清理（此后一帧按全进度呈现新帧）。"""
        if not self._xfade_active:
            if self._xfade_timer.isActive():
                self._xfade_timer.stop()
            return
        if self._xfade_progress() >= 1.0:
            self._finish_xfade()
        self.update()

    def _render_frame_image(self, width: int, height: int) -> QImage | None:
        """渲染当前主题下的背景帧为离屏 QImage（全不透明）。

        ambient 关闭时为 G1 纯色图；开启时优先抖动缓存图，降级时把原渐变
        画进 QImage。宽高非法时返回 None。

        Args:
            width: 目标宽度（像素）。
            height: 目标高度（像素）。

        Returns:
            QImage | None: 当前帧图像；非法尺寸时返回 None。
        """
        if width <= 0 or height <= 0:
            return None
        if not self._ambient_enabled:
            image = QImage(width, height, QImage.Format_RGB32)
            base: QColor = QColor(tm.surface)
            base.setAlpha(255)
            image.fill(base.rgb())
            return image
        bottom, mid, top = compute_minimalist_gradient_colors()
        if not self._interacting:
            cached = self._dithered_image(width, height, bottom, mid, top)
            if cached is not None:
                return cached
        image = QImage(width, height, QImage.Format_RGB32)
        painter = QPainter(image)
        try:
            gradient = QLinearGradient(0, height, 0, 0)
            gradient.setColorAt(0.0, bottom)
            gradient.setColorAt(0.5, mid)
            gradient.setColorAt(1.0, top)
            painter.fillRect(0, 0, width, height, QBrush(gradient))
        finally:
            painter.end()
        return image

    def _dither_key(
        self, width: int, height: int, bottom: QColor, mid: QColor, top: QColor
    ) -> tuple[int, int, int, int, int, float]:
        """构造抖动缓存键 ``(w, h, bottom, mid, top, amp)``。

        Args:
            width: 目标宽度（像素）。
            height: 目标高度（像素）。
            bottom: 渐变底部色。
            mid: 渐变中部色。
            top: 渐变顶部色。

        Returns:
            tuple[int, int, int, int, int, float]: 可哈希的缓存键
                （颜色取 ``rgb()`` 整数，含 alpha 恒 255）。
        """
        return (
            int(width),
            int(height),
            int(bottom.rgb()),
            int(mid.rgb()),
            int(top.rgb()),
            float(_DITHER_AMP_DEFAULT),
        )

    def _dithered_image(
        self, width: int, height: int, bottom: QColor, mid: QColor, top: QColor
    ) -> QImage | None:
        """取抖动缓存图（命中 LRU 前移，未命中则预合成；存取均为深拷贝）。

        Args:
            width: 目标宽度（像素）。
            height: 目标高度（像素）。
            bottom: 渐变底部色。
            mid: 渐变中部色。
            top: 渐变顶部色。

        Returns:
            QImage | None: 抖动渐变图（调用方可安全使用，不污染缓存）；
                numpy 缺失等预合成失败时返回 None，调用方降级为原渐变。
        """
        key = self._dither_key(width, height, bottom, mid, top)
        cached = self._dither_cache.get(key)
        if cached is not None:
            self._dither_cache.move_to_end(key)
            return cached.copy()
        try:
            image = render_minimalist_image(width, height, bottom, mid, top)
        except (_DitherUnavailableError, ValueError, RuntimeError, MemoryError, TypeError):
            return None
        self._dither_cache[key] = image.copy()
        while len(self._dither_cache) > _DITHER_CACHE_MAX:
            self._dither_cache.popitem(last=False)
        return image

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制单层不透明背景（含 IGN 抗色带）。

        ambient 关闭时全域填充 G1（不抖动）；开启时渐变三色由
        ``compute_minimalist_gradient_colors`` 按主题生成
        （浅色 0.0/0.1/0.2，深色更克制的 0.0/0.05/0.10），呈现分两态：

        - 稳定态：单次 ``drawImage`` 抖动缓存图——离屏已预合成全不透明
          （IGN ``±0.7LSB``、锚定窗口本地 ``(0, 0)``、一次性 ``rint``、
          1:1 呈现），仍是单层呈现，无透明叠加。
        - 交互态（拖拽/缩放中）或降级态（numpy 缺失）：单次 ``fillRect``
          原渐变，无抖动，保证拖拽流畅。
        - 主题交叉过渡期（切换后 280ms 内）：旧帧铺底 + 新帧按进度离屏混合，
          混合帧单次不透明 ``drawImage`` 呈现（仿 MicaMaterial._draw_layer，
          但混合在离屏完成，屏幕仍只见一层），旧像素在重绘间隙始终可见。

        宽高全零时直接返回守卫。

        Args:
            event: Qt 绘制事件。
        """
        width: int = self.width()
        height: int = self.height()
        if width <= 0 or height <= 0:
            return
        backdrop = self._xfade_backdrop
        if (
            self._xfade_active
            and backdrop is not None
            and not backdrop.isNull()
        ):
            t = self._xfade_progress()
            # 注意：不比较 backdrop.size() == self.size()——grab() 返回物理
            # 像素（逻辑尺寸 × devicePixelRatio），缩放≠100% 时恒不相等，
            # 严格比较会直接 _finish_xfade() 跳过渡（生硬直切）。此处按目标
            # 矩形缩放铺底，分辨率无关（仿 CustomImageBackgroundWidget）。
            if t < 1.0:
                new_frame = self._render_frame_image(width, height)
                if new_frame is not None and not new_frame.isNull():
                    blended = QImage(width, height, QImage.Format_RGB32)
                    mixer = QPainter(blended)
                    try:
                        mixer.setOpacity(1.0)
                        mixer.drawPixmap(0, 0, width, height, backdrop)
                        mixer.setOpacity(max(0.0, min(1.0, t)))
                        mixer.drawImage(0, 0, new_frame)
                    finally:
                        mixer.end()
                    painter = QPainter(self)
                    try:
                        painter.drawImage(0, 0, blended)
                    finally:
                        painter.end()
                    return
            self._finish_xfade()
        painter = QPainter(self)
        if not self._ambient_enabled:
            base: QColor = QColor(tm.surface)
            base.setAlpha(255)
            painter.fillRect(self.rect(), base)
            painter.end()
            return
        bottom, mid, top = compute_minimalist_gradient_colors()
        if not self._interacting:
            cached = self._dithered_image(width, height, bottom, mid, top)
            if cached is not None:
                painter.drawImage(0, 0, cached)
                painter.end()
                return
        gradient = QLinearGradient(0, height, 0, 0)
        gradient.setColorAt(0.0, bottom)
        gradient.setColorAt(0.5, mid)
        gradient.setColorAt(1.0, top)
        painter.fillRect(self.rect(), QBrush(gradient))
        painter.end()
