#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全 UI 唯一的帧时钟（FrameScheduler）。

## 为什么需要它

修复前，界面动画的节拍由四套互不相关的固定毫秒值决定：

* ``HeartbeatManager``：普通 33 ms、动画 16 ms（且都是 Qt 默认
  ``CoarseTimer``，被 Windows 15.625 ms 系统时钟网格量化成 46.9 / 15.6 ms，
  实测只有 21 fps / 62 fps）；
* 各组件自建 ``QTimer``：16 / 30 / 33 / 50 ms；
* Qt 内置动画定时器（``QUnifiedTimer``）：固定约 16 ms → 所有
  ``QPropertyAnimation`` 只有约 63 fps；
* ``ViewportCompositor``：下限写死 16 ms。

这四套在 240Hz 面板上分别只能跑到 21、16~32、63、62 fps，与面板上限相差
4~11 倍。本模块把"每秒要出多少帧"收敛成**一个**时钟：

    panel_hz（:mod:`sopeek.core.managers.display_timing` 探测）
        ↓ 被订阅需求抬高/压低
    cadence_hz = min(panel_hz, max(订阅需求, 硬需求))
        ↓ 空闲降频 / 过载降级
    QTimer(PreciseTimer, ~1000/cadence_hz ms)

## 语义

* ``subscribe(cb, hz=None)``：每个帧回调一次。``hz=30`` 表示最多 30Hz 调用。
* ``hz=None`` 的订阅者算"每帧都要"，会把 cadence 抬到面板刷新率。
* :meth:`request_high_rate` 持有的令牌表示"此刻必须保持满帧"（播放中的视频、
  正在交互的拖拽、正在跑的动画）。**空闲降频不会压低硬需求**。
* 空闲降频：``IDLE_AFTER_MS`` 内没有任何键鼠/滚轮/触控活动且没有硬需求时，
  cadence 压到 :data:`IDLE_HZ`——界面不再空转 240fps，省电且不烫。
* 过载降级：实测每帧回调耗时（含定时器迟到）持续超过预算就按 1/2 逐级降档，
  有富余后再逐级恢复。宁可稳定 120fps，也不要抖动掉帧的 240fps。
* 没有任何订阅者时**完全停表**（0 次唤醒）。

所有时间量都以 ``time.perf_counter()`` 的真实经过时间为准，不做
"固定步长累加"，因此定时器精度变化不会让动画速度漂移。
"""

from __future__ import annotations

import os
import threading
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Optional

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QMetaObject,
    QObject,
    Qt,
    QTimer,
    Slot,
)
from PySide6.QtGui import QGuiApplication

from sopeek.core.managers.display_timing import DisplayTiming, frame_interval_ms
from sopeek.utils.app_logger import debug, info, warning

#: 判定"用户离开"的时间（毫秒）。超过该时长无键鼠活动即进入空闲档。
IDLE_AFTER_MS: float = 1200.0
#: 空闲档帧率。界面静止时降到该值，省电又不至于让残留动效显得卡死。
IDLE_HZ: float = 30.0
#: 任何情况下都不低于该帧率（低于此值动画会明显一顿一顿）。
MIN_HZ: float = 24.0
#: 过载降级的最大档数（240 → 120 → 60 → 30 → 24）。
MAX_PENALTY: int = 3
#: 每帧回调耗时 EMA 的新样本权重。
_WORK_EMA_ALPHA: float = 0.15
#: 每帧回调耗时超过该比例的目标帧时长 → 视为过载。
_OVERLOAD_RATIO: float = 0.75
#: 定时器实际间隔超过该倍数的目标帧时长 → 也视为过载（主线程被别的工作占住）。
#:
#: 帧间隔超过目标帧时长的多少倍即视为"主线程画不过来"。
#:
#: 这里看的是 ``_achieved_ms``（帧间隔的 EWMA）而不是单帧 ``dt``：真实窗口
#: 里一次整窗重绘要 8~20ms，单帧 dt 会来回跳，但 EWMA 能稳定反映"渲染能力"。
#: 取 1.35 而不是 2.5：实测主线程每次整窗重绘 ~21ms 时，240Hz 的请求会把
#: 事件循环灌满，交互延迟 p90 到 40~140ms、动画有效帧率掉到 15~25fps；
#: 只有让档位快速落到"画得出来"的频率，交互才跟手。
_LATE_RATIO: float = 1.6
#: 单帧抖动超过目标帧时长的多少倍即视为尖峰（不等 EWMA 收敛就降档）。
_SPIKE_RATIO: float = 6.0
#: 连续过载多少帧后降一档（30 帧 ≈ 0.12s @240Hz；严重过载时快速降档）。
_OVERLOAD_FRAMES: int = 30
#: 连续富余多少帧后升一档（120 帧 ≈ 0.5s @240Hz，避免档位抖动）。
_RECOVER_FRAMES: int = 120

#: 时钟泵等待上限（毫秒）。到点返回 `-3` 后线程重新进入等待，便于响应 `stop()`。
_CLOCK_WAIT_MS: int = 200
#: 没有订阅者后等待多久才真正停表（毫秒）。悬停/过渡动画常常首尾相接，
#: 立刻停钟会让每次都付出"停线程 + join + resume"的代价。
_STOP_GRACE_MS: int = 1200
#: 档位需要稳定多久才落地（秒）。需求抖动时避免反复改 native 时钟。
_RATE_SETTLE_S: float = 0.12
#: 允许"已投递但主线程还没处理"的帧数上限（背压上限）。
_CLOCK_MAX_INFLIGHT: int = 2

#: 视为"用户活动"的事件类型（只做集合查表，热路径开销极低）。
_ACTIVITY_EVENTS: frozenset[int] = frozenset(
    int(getattr(QEvent.Type, name))
    for name in (
        "MouseMove",
        "MouseButtonPress",
        "MouseButtonRelease",
        "MouseButtonDblClick",
        "Wheel",
        "Scroll",
        "KeyPress",
        "KeyRelease",
        "TouchBegin",
        "TouchUpdate",
        "TouchEnd",
        "NativeGesture",
        "HoverMove",
        "Enter",
        "WindowActivate",
        "ApplicationActivate",
    )
    if hasattr(QEvent.Type, name)
)


@dataclass
class _Subscriber:
    """一个逐帧订阅者。"""

    callback_id: str
    callback: Optional[Callable[[], None]] = None
    weak_method: Optional[weakref.WeakMethod] = None
    hz: Optional[float] = None
    priority: int = 3
    owner_ref: Optional[weakref.ref] = None
    dead: bool = field(default=False, repr=False)
    _accum_ms: float = field(default=0.0, repr=False)

    def resolve(self) -> Optional[Callable[[], None]]:
        """解析可调用对象；弱引用失效时返回 ``None``。"""
        if self.weak_method is not None:
            return self.weak_method()
        return self.callback


class FrameScheduler(QObject):
    """主线程帧调度器（单例）。

    用法::

        fs = frame_scheduler()
        fs.subscribe("fluid", self._on_frame)          # 每帧
        fs.subscribe("clock", self._on_clock, hz=1.0)  # 每秒一次
        fs.unsubscribe("fluid")
    """

    _instance: Optional["FrameScheduler"] = None

    def __new__(cls) -> "FrameScheduler":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_ready", False):
            return
        super().__init__()
        self._ready = True

        self._timer: Optional[QTimer] = None
        self._subscribers: dict[str, _Subscriber] = {}
        self._ordered: list[_Subscriber] = []
        self._ordered_dirty: bool = True
        self._pending_frames: list[Callable[[], None]] = []

        self._running: bool = False
        self._frame_index: int = 0
        self._interval_ms: float = frame_interval_ms(60.0)
        self._cadence_hz: float = 60.0
        self._panel_hz: float = 60.0
        self._last_frame: float = 0.0

        self._high_rate: dict[int, float] = {}

        self._last_activity: float = time.perf_counter()
        self._idle: bool = False
        self._penalty: int = 0
        self._work_ema_ms: float = 0.0
        self._achieved_ms: float = 0.0
        #: 是否"落后于目标帧率"（EWMA 帧间隔显著超目标）。动画补丁据此跳过本帧
        #: 的可视更新，避免在画不过来时继续堆积重绘请求。
        self._behind: bool = False
        self._overload_streak: int = 0
        self._recover_streak: int = 0
        self._filter_installed: bool = False

        # vsync 时钟泵（Rust ``spk_frameclock``）：可用时用它替代 QTimer 驱动
        # ``_on_frame``，让每帧落在真实 vblank 上而不是自由跑的定时器网格上。
        # 必须早于 DisplayTiming 创建：``DisplayTiming.refresh()`` 会立刻发
        # ``refresh_changed``，槽里读这些字段，晚初始化会 AttributeError。
        self._clock_handle: int = 0
        self._clock_thread: Optional[threading.Thread] = None
        self._clock_stop: threading.Event = threading.Event()
        self._clock_slot_event: threading.Event = threading.Event()
        self._clock_lock: threading.Lock = threading.Lock()
        self._clock_inflight: int = 0
        self._clock_failed: bool = False
        self._clock_rate_hz: float = 0.0

        self._timing: DisplayTiming = DisplayTiming()
        self._timing.refresh_changed.connect(self._on_panel_changed)
        try:
            self._panel_hz = self._timing.refresh()
        except Exception:  # noqa: BLE001 - 探测失败不阻断 UI
            self._panel_hz = 60.0
        self._cadence_hz = self._panel_hz
        self._interval_ms = frame_interval_ms(self._panel_hz)

        # 停表宽限期：动画接力（结束→开始）时避免反复停钟/起钟。
        self._stop_grace: QTimer = QTimer(self)
        self._stop_grace.setSingleShot(True)
        self._stop_grace.timeout.connect(self._stop_after_grace)
        # 档位落地去抖（见 ``_retune``）。
        self._pending_hz: Optional[float] = None
        self._pending_since: float = 0.0

    # ================================================================
    # 订阅
    # ================================================================

    def subscribe(
        self,
        callback_id: str,
        callback: Callable[[], None],
        *,
        hz: Optional[float] = None,
        priority: int = 3,
        owner: Optional[QObject] = None,
    ) -> None:
        """注册一个逐帧回调。

        Args:
            callback_id: 唯一标识（重复注册直接覆盖，不抛异常——组件重建
                时更安全）。
            callback: 每帧调用的可调用对象（绑定方法用弱引用保存）。
            hz: 期望调用频率；``None`` 表示"每帧都要"（把 cadence 抬到面板
                刷新率）。给定 ``hz`` 时按时间累积节流，不改变全局节拍。
            priority: 0（最高）到 4（最低），同帧内按此顺序执行。
            owner: 生命周期所有者；析构后自动注销。
        """
        if not callable(callback):
            raise TypeError("callback must be callable")
        weak_method: Optional[weakref.WeakMethod] = None
        try:
            weak_method = weakref.WeakMethod(callback)  # type: ignore[arg-type]
        except TypeError:
            pass
        was_first = not self._subscribers
        owner_ref: Optional[weakref.ref] = None
        if owner is not None:
            owner_ref = weakref.ref(owner)
        self._subscribers[callback_id] = _Subscriber(
            callback_id=callback_id,
            callback=None if weak_method is not None else callback,
            weak_method=weak_method,
            hz=hz,
            priority=max(0, min(4, priority)),
            owner_ref=owner_ref,
        )
        self._ordered_dirty = True
        # 新订阅要求满帧时视为一次活动：否则「程序自己触发」的动画（对话框滑入、
        # 卡片入场、页面过渡）会在空闲档被压到 IDLE_HZ，表现为「不动鼠标就掉帧」。
        if self._idle and (hz is None or float(hz) > IDLE_HZ):
            self.note_user_activity()
        # 需求大幅跃升（30Hz → 满帧）时立即生效，别让新动画先掉几帧；
        # 小幅变化仍走去抖（见 ``_retune``）。
        wanted = self._wanted_hz()
        self._refresh_demand(force=was_first or wanted > self._cadence_hz * 1.5)

    def _refresh_demand(self, *, force: bool = False) -> None:
        """订阅集合变化后重算节拍（在跑时立即生效，否则启动）。"""
        if not self._running:
            self.ensure_running()
            return
        self._retune(force=force)
        # 只有走 QTimer 路径时才需要确保定时器在跑：时钟泵接管期间若这里再
        # start()，两条驱动会同时投递帧，帧率凭空翻倍（每帧被跑两次）。
        if (
            self._timer is not None
            and not self._clock_handle
            and not self._timer.isActive()
        ):
            self._timer.start(max(1, int(round(self._interval_ms))))

    def unsubscribe(self, callback_id: str) -> bool:
        """注销逐帧回调。

        Args:
            callback_id: 注册时使用的标识符。

        Returns:
            找到并移除返回 ``True``。
        """
        entry = self._subscribers.pop(callback_id, None)
        if entry is None:
            return False
        entry.dead = True
        self._ordered_dirty = True
        self._maybe_stop()
        return True

    def unsubscribe_for_owner(self, owner: QObject) -> int:
        """注销某个 QObject 拥有的全部逐帧回调。

        Args:
            owner: 所有者对象。

        Returns:
            移除的订阅数量。
        """
        stale = [
            cid
            for cid, entry in self._subscribers.items()
            if entry.owner_ref is not None and entry.owner_ref() is owner
        ]
        for cid in stale:
            self.unsubscribe(cid)
        return len(stale)

    def is_subscribed(self, callback_id: str) -> bool:
        """指定标识是否仍然注册。"""
        return callback_id in self._subscribers

    # ================================================================
    # 硬需求 / 空闲
    # ================================================================

    def request_high_rate(self, token: object, hz: Optional[float] = None) -> None:
        """持有"必须满帧"的需求令牌。

        用于播放中的视频、进行中的拖拽、正在跑的高刷动画。空闲降频不会压低
        硬需求，且持有令牌本身即视为用户活动。

        Args:
            token: 需求持有者（任意可哈希对象，通常传控件自身或字符串）。
            hz: 需要的帧率；``None`` 表示面板刷新率。
        """
        self._high_rate[id(token)] = (
            self._panel_hz if hz is None else float(hz)
        )
        self.note_user_activity()
        self._refresh_demand()

    def release_high_rate(self, token: object) -> None:
        """释放硬需求令牌。

        Args:
            token: 与 :meth:`request_high_rate` 相同的对象。
        """
        self._high_rate.pop(id(token), None)
        self._maybe_stop()

    def note_user_activity(self) -> None:
        """记录一次用户活动（键鼠/滚轮/触控），立即退出空闲档。"""
        self._last_activity = time.perf_counter()
        if self._idle:
            self._idle = False
            debug("FrameScheduler: leaving idle cadence")
            self._retune()

    def request_frame(self, callback: Callable[[], None]) -> None:
        """把回调排到下一帧执行（不参与节流）。

        Args:
            callback: 下一帧要执行的可调用对象。
        """
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._pending_frames.append(callback)
        self.ensure_running()

    # ================================================================
    # 生命周期
    # ================================================================

    def ensure_running(self) -> None:
        """确保帧时钟在跑（有订阅者/待执行请求时）。"""
        self._cancel_stop_grace()
        if self._running:
            # 已在跑（可能先前因 DLL 未就绪/失败而走了 QTimer）：若 vsync 时钟
            # 现在可用，升级过去并停掉 QTimer，避免两条驱动同时跑或永久停在
            # 定时器路径（单例场景下这一点尤其容易被一次早期失败钉死）。
            self._maybe_upgrade_to_clock()
            return
        if not self._subscribers and not self._pending_frames and not self._high_rate:
            return
        if QCoreApplication.instance() is None:
            # 没有事件循环（纯单元测试）时只登记状态，不启动定时器。
            return
        if self._timer is None:
            timer = QTimer(self)
            timer.setTimerType(Qt.TimerType.PreciseTimer)
            timer.timeout.connect(self._on_frame)
            self._timer = timer
        self._install_activity_filter()
        self._running = True
        self._last_frame = 0.0
        # 先按订阅需求定好 cadence，再决定用哪条驱动路径：时钟创建时就带着
        # 正确帧率，省掉一次「先用 60Hz 建、再改档」的抖动。
        self._retune(force=True)
        clock_started = self._clock_start()
        if clock_started:
            self._clock_apply_rate()
        elif self._timer is not None:
            self._timer.start(max(1, int(round(self._interval_ms))))

    def stop(self) -> None:
        """停止帧时钟（保留订阅者；vsync 句柄保留待下次恢复）。"""
        self._cancel_stop_grace()
        self._running = False
        if self._timer is not None and self._timer.isActive():
            self._timer.stop()
        self._clock_pause()
        self._release_activity_filter()

    def shutdown(self) -> None:
        """清空订阅者并停表（测试/退出清理用）。"""
        self.stop()
        self._clock_shutdown()
        # 显式 shutdown 之后允许重新尝试 vsync 时钟：失败标记只在"本次运行"
        # 内有效（例如 DLL 不可用），否则单例被复用（测试、切换设备）后会永久
        # 卡在 QTimer 路径。
        self._clock_failed = False
        self._subscribers.clear()
        self._pending_frames.clear()
        self._high_rate.clear()
        self._ordered = []
        self._ordered_dirty = True

    def _maybe_stop(self) -> None:
        """没有工作可做时延时停表（0 次唤醒）。

        不立刻停：悬停/过渡动画会频繁地"最后一帧结束 → 下一帧开始"，如果每次
        都停钟再起钟（`frameclock_stop` + 线程 join + resume），主线程会被反复
        卡住，交互直接掉帧。留一段宽限期，动画接力时连停表都不会发生。
        """
        if self._subscribers or self._pending_frames or self._high_rate:
            self._cancel_stop_grace()
            return
        if not self._running or self._stop_grace.isActive():
            return
        self._stop_grace.start(_STOP_GRACE_MS)

    def _cancel_stop_grace(self) -> None:
        """取消待执行的停表（有新工作回来了）。"""
        if self._stop_grace.isActive():
            self._stop_grace.stop()

    def _stop_after_grace(self) -> None:
        """宽限期到点：仍然没有工作才真正停表。"""
        if self._subscribers or self._pending_frames or self._high_rate:
            return
        self.stop()

    # ================================================================
    # 查询
    # ================================================================

    @property
    def panel_hz(self) -> float:
        """面板刷新率（Hz）。"""
        return self._panel_hz

    @property
    def cadence_hz(self) -> float:
        """当前实际帧率（Hz，含空闲降频与过载降级）。"""
        return self._cadence_hz

    def interval_ms(self) -> float:
        """当前目标帧间隔（毫秒）。"""
        return self._interval_ms

    def is_idle(self) -> bool:
        """当前是否处于空闲降频档。"""
        return self._idle

    @property
    def behind(self) -> bool:
        """主线程是否已经落后于目标帧率（画不过来）。

        动画补丁用它跳过本帧的可视更新：动画时间轴仍按墙钟推进（时长不变），
        但不会再往事件循环里塞"这一帧画不出来的重绘请求"。
        """
        return self._behind

    def stats(self) -> dict[str, Any]:
        """返回诊断快照（日志/性能面板用）。"""
        return {
            "panel_hz": round(self._panel_hz, 2),
            "cadence_hz": round(self._cadence_hz, 2),
            "interval_ms": round(self._interval_ms, 2),
            "idle": self._idle,
            "penalty": self._penalty,
            "work_ms": round(self._work_ema_ms, 3),
            "achieved_ms": round(self._achieved_ms, 3),
            "behind": self._behind,
            "subscribers": len(self._subscribers),
            "running": self._running,
            "frames": self._frame_index,
            "vsync_clock": self._clock_handle != 0,
        }

    # ================================================================
    # 内部：节拍计算
    # ================================================================

    def _on_panel_changed(self, _hz: float) -> None:
        """面板刷新率变化（换屏/热插拔）后重新定档。"""
        self._panel_hz = self._timing.hz
        self._retune(force=True)

    def _wanted_hz(self) -> float:
        """根据订阅需求与硬需求算出想要的基础帧率（未含降级）。"""
        if not self._subscribers and not self._high_rate:
            # 瞬间没有订阅者：保持当前档位，别掉到 MIN_HZ（停表由宽限期负责）。
            return max(MIN_HZ, self._cadence_hz or self._panel_hz)
        wanted = MIN_HZ
        for entry in self._subscribers.values():
            if entry.dead:
                continue
            wanted = max(wanted, self._panel_hz if entry.hz is None else entry.hz)
        for hz in self._high_rate.values():
            wanted = max(wanted, hz)
        if self._idle and not self._high_rate:
            wanted = min(wanted, IDLE_HZ)
        return max(MIN_HZ, min(self._panel_hz, wanted))

    def _retune(self, force: bool = False) -> None:
        """按当前需求重算帧率与定时器间隔。"""
        base = self._wanted_hz()
        if base <= IDLE_HZ:
            # 需求本来就很低（心跳 30Hz）时不再叠加降级：继续往下压只会让
            # 档位在 24/30Hz 之间来回跳（每次跳动都要改 native 时钟），
            # 反而制造抖动。
            effective = base
        else:
            # 降级不能让动画掉到「肉眼看得出卡」的档位：主线程忙时应该**少画**
            # （见 ``behind`` 与 ``frame_pacing`` 的跳帧），而不是把节拍压到
            # 30Hz —— 实测 24Hz 的节拍比少画几帧更难受。
            floor = min(IDLE_HZ * 2.0, base)
            effective = max(floor, base / (2 ** self._penalty))
        effective = min(effective, self._panel_hz)
        interval = frame_interval_ms(effective)
        changed = (
            force
            or abs(effective - self._cadence_hz) > 0.01
            or abs(interval - self._interval_ms) > 0.01
        )
        if not changed:
            return
        if not force:
            # 需求抖动（悬停动画 60Hz ↔ 滑动动画 240Hz ↔ 短暂空档）不应每帧
            # 都改一次档：每次改档都要让 native 时钟重算 divisor、重锚相位，
            # 实测 3 秒内能抖出 79 次 resync，画面反而顿。等档位稳定一小会儿
            # 再落地。
            now = time.perf_counter()
            if self._pending_hz is None or abs(effective - self._pending_hz) > 0.01:
                self._pending_hz = effective
                self._pending_since = now
                return
            if (now - self._pending_since) < _RATE_SETTLE_S:
                return
        self._pending_hz = None
        self._cadence_hz = effective
        self._interval_ms = interval
        if self._clock_handle:
            # 时钟泵在跑：让 native 侧改档（它会重算 divisor 并重锚相位）。
            self._clock_apply_rate()
        elif self._timer is not None and self._running:
            ms = max(1, int(round(interval)))
            if self._timer.interval() != ms:
                self._timer.setInterval(ms)
        if force:
            return
        info(
            "FrameScheduler: cadence "
            f"{effective:.1f}Hz (panel {self._panel_hz:.1f}Hz, "
            f"idle={self._idle}, penalty={self._penalty})"
        )

    # ================================================================
    # 内部：vsync 时钟泵
    # ================================================================

    def _clock_enabled_by_env(self) -> bool:
        """环境变量开关：``SPK_FRAME_CLOCK=0`` 强制回到 QTimer 路径。"""
        return os.environ.get("SPK_FRAME_CLOCK", "1").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }

    def _clock_bridge(self) -> Any:
        """取原生桥（不可用/旧 DLL 时返回 ``None``）。"""
        try:
            from sopeek.core.native.bridges.spk_core_bridge import (
                get_spk_core_bridge,
            )

            bridge = get_spk_core_bridge()
            if bridge is None or not bridge.supports_frame_clock:
                return None
            return bridge
        except Exception as e:  # noqa: BLE001 - 原生层任何问题都退回 QTimer
            debug(f"FrameScheduler: 帧时钟不可用 ({e})，使用 QTimer")
            return None

    def _maybe_upgrade_to_clock(self) -> None:
        """已在用 QTimer 时尝试升级到 vsync 时钟（幂等，失败即保持原状）。"""
        if self._clock_thread is not None:
            return
        if not self._clock_start():
            return
        if self._timer is not None and self._timer.isActive():
            self._timer.stop()
        self._clock_apply_rate()

    def _clock_start(self) -> bool:
        """启动时钟泵线程。

        Returns:
            bool: ``True`` 表示已由 native vsync 时钟驱动（不再需要 QTimer）。
        """
        if self._clock_thread is not None:
            if self._clock_thread.is_alive():
                return self._clock_handle > 0
            # 线程已退出但记录未清（暂停超时/异常路径）：清掉后按"未启动"处理，
            # 否则单例（见 __new__）会永久停在 QTimer 路径。
            self._clock_thread = None
        if self._clock_failed:
            return False
        if not self._clock_enabled_by_env():
            return False
        bridge = self._clock_bridge()
        if bridge is None:
            return False
        if self._clock_handle:
            # 之前只是暂停（stop() 不释放句柄），恢复即可。
            try:
                bridge.frameclock_resume(self._clock_handle)
            except Exception as e:  # noqa: BLE001
                debug(f"FrameScheduler: 恢复帧时钟失败 ({e})")
                self._clock_release_handle()
        else:
            handle = 0
            try:
                handle = bridge.frameclock_create(max(MIN_HZ, self._cadence_hz))
            except Exception as e:  # noqa: BLE001
                debug(f"FrameScheduler: 帧时钟创建失败 ({e})")
            if not handle:
                return False
            self._clock_handle = handle
        self._clock_rate_hz = max(MIN_HZ, self._cadence_hz)
        # 每个线程用自己的停止事件：暂停时只 set 自己那一个，旧线程绝不会因为
        # 下一次启动清标志而"复活"成第二个时钟泵（那会让帧率凭空翻倍）。
        stop_event = threading.Event()
        self._clock_stop = stop_event
        self._clock_slot_event.clear()
        thread = threading.Thread(
            target=self._clock_loop,
            args=(self._clock_handle, stop_event),
            name="spk-frame-clock",
            daemon=True,
        )
        self._clock_thread = thread
        thread.start()
        # 诊断信息不可用不能影响接管本身：旧 DLL / 假桥可能没有 stats 导出。
        try:
            stats = bridge.frameclock_stats(self._clock_handle) or {}
        except Exception:  # noqa: BLE001
            stats = {}
        debug(
            "FrameScheduler: vsync 时钟已接管 "
            f"(handle={self._clock_handle}, mode={stats.get('mode')}, "
            f"panel={stats.get('panel_hz')}Hz, divisor={stats.get('divisor')})"
        )
        return True

    def _clock_apply_rate(self) -> None:
        """把当前 cadence 同步给 native 时钟（幂等；变化不大就跳过）。"""
        if not self._clock_handle:
            return
        target = max(MIN_HZ, self._cadence_hz)
        if abs(target - self._clock_rate_hz) < 0.01:
            return
        bridge = self._clock_bridge()
        if bridge is None:
            return
        try:
            bridge.frameclock_set_rate(self._clock_handle, target)
            self._clock_rate_hz = target
        except Exception as e:  # noqa: BLE001
            warning(f"FrameScheduler: 切换时钟帧率失败 ({e})")

    def _clock_release_handle(self) -> None:
        """释放 native 句柄（不碰线程）。"""
        handle = self._clock_handle
        self._clock_handle = 0
        self._clock_rate_hz = 0.0
        if not handle:
            return
        bridge = self._clock_bridge()
        if bridge is not None:
            try:
                bridge.frameclock_free(handle)
            except Exception:  # noqa: BLE001, S110
                pass

    def _clock_pause(self) -> None:
        """暂停时钟泵：停线程但保留句柄（下次 ``ensure_running`` 直接恢复）。"""
        thread = self._clock_thread
        stop_event = self._clock_stop
        self._clock_thread = None
        if thread is None:
            return
        stop_event.set()
        bridge = self._clock_bridge()
        if bridge is not None and self._clock_handle:
            try:
                bridge.frameclock_stop(self._clock_handle)
            except Exception:  # noqa: BLE001, S110
                pass
        self._clock_slot_event.set()
        # join 只在主线程上、且必须很短：线程在 ``wait`` 里最多阻塞一个
        # ``_CLOCK_WAIT_MS``，``frameclock_stop`` 会让它在下一个 vblank 返回。
        # 长时间 join 会直接卡住界面（旧实现 1.0s，悬停动画一停一开就是一次卡顿）。
        thread.join(timeout=0.25)
        if thread.is_alive():
            # 线程卡在 native 里时不能复用它：标记失败让主线程改走 QTimer，
            # 否则旧线程会在下一次启动后继续投递，帧率翻倍。
            warning("FrameScheduler: 时钟泵线程未能及时退出，放弃 vsync 时钟")
            self._clock_failed = True
        self._clock_slot_event.clear()
        with self._clock_lock:
            self._clock_inflight = 0

    def _clock_shutdown(self) -> None:
        """停线程并释放 native 句柄（退出/失败清理用，幂等）。"""
        self._clock_pause()
        self._clock_release_handle()

    def _clock_loop(self, handle: int, stop_event: threading.Event) -> None:
        """时钟泵线程：每次 ``wait`` 返回一帧就投递到主线程。

        投递用队列调用（主线程执行 ``_on_clock_frame``），并用 ``_clock_inflight``
        做背压：主线程还没消化完时线程在事件上等待，不会把事件队列灌爆。
        """
        bridge = self._clock_bridge()
        if bridge is None or not handle:
            return
        while not stop_event.is_set():
            try:
                seq = bridge.frameclock_wait(handle, _CLOCK_WAIT_MS)
            except Exception as e:  # noqa: BLE001
                warning(f"FrameScheduler: 时钟等待异常 ({e})，回退 QTimer")
                self._clock_fail()
                return
            if stop_event.is_set():
                return
            if seq == -4:  # 已停止（可能是我们自己的 stop）
                if stop_event.is_set():
                    return
                continue
            if seq == -3:  # 等待超时，重新进入（顺便检查停止标志）
                continue
            if seq < 0:
                self._clock_fail()
                return
            # 背压：等主线程把上一帧处理掉再投递下一帧。
            while not stop_event.is_set():
                with self._clock_lock:
                    if self._clock_inflight < _CLOCK_MAX_INFLIGHT:
                        self._clock_inflight += 1
                        break
                self._clock_slot_event.wait(0.05)
                self._clock_slot_event.clear()
            if stop_event.is_set():
                return
            try:
                QMetaObject.invokeMethod(
                    self, "_on_clock_frame", Qt.ConnectionType.QueuedConnection
                )
            except Exception as e:  # noqa: BLE001
                warning(f"FrameScheduler: 投递帧失败 ({e})，回退 QTimer")
                with self._clock_lock:
                    self._clock_inflight = max(0, self._clock_inflight - 1)
                self._clock_fail()
                return

    def _clock_fail(self) -> None:
        """时钟泵异常退出：标记失败并请主线程切回 QTimer。"""
        self._clock_failed = True
        try:
            QMetaObject.invokeMethod(
                self, "_on_clock_failed", Qt.ConnectionType.QueuedConnection
            )
        except Exception:  # noqa: BLE001, S110
            pass

    @Slot()
    def _on_clock_frame(self) -> None:
        """主线程收到一个 vsync 帧（来自时钟泵线程）。"""
        with self._clock_lock:
            self._clock_inflight = max(0, self._clock_inflight - 1)
        self._clock_slot_event.set()
        if not self._running:
            return
        self._on_frame()

    @Slot()
    def _on_clock_failed(self) -> None:
        """时钟路径失败后的主线程清理：释放句柄并重启 QTimer。"""
        if not self._running:
            self._clock_shutdown()
            return
        self._clock_shutdown()
        if self._timer is None:
            timer = QTimer(self)
            timer.setTimerType(Qt.TimerType.PreciseTimer)
            timer.timeout.connect(self._on_frame)
            self._timer = timer
        self._retune(force=True)
        if self._timer is not None:
            self._timer.start(max(1, int(round(self._interval_ms))))
        warning("FrameScheduler: vsync 时钟不可用，已回退 QTimer 精确计时")

    # ================================================================
    # 内部：每帧
    # ================================================================

    def _on_frame(self) -> None:
        """一个帧节拍：重算档位 → 分发订阅者 → 执行待办 → 更新治理状态。"""
        if not self._running:
            return
        now = time.perf_counter()
        dt_ms = (
            (now - self._last_frame) * 1000.0 if self._last_frame else self._interval_ms
        )
        self._last_frame = now
        self._frame_index += 1
        self._achieved_ms = 0.9 * self._achieved_ms + 0.1 * dt_ms
        self._behind = self._achieved_ms > self._interval_ms * _LATE_RATIO

        if not self._idle and (now - self._last_activity) * 1000.0 >= IDLE_AFTER_MS:
            self._idle = True
            debug("FrameScheduler: entering idle cadence")
        self._retune()

        if self._ordered_dirty:
            self._rebuild_ordered()
        entries = self._ordered

        start = time.perf_counter()
        dead_ids: list[str] = []
        for entry in entries:
            if entry.dead:
                continue
            if entry.hz is not None:
                # 累积到周期就放行；放行后**减去**周期而不是清零，多出来的
                # 余量留给下一次，长期平均频率才不会因每帧的取整而缩水。
                # 容差取 1/4 帧：定时器间隔被取整成整数毫秒后，实测 dt 常常
                # 比声明周期小零点几毫秒（如 33.33→32.9），没有容差就会
                # 「一帧放行、一帧跳过」，30Hz 的订阅掉成 15Hz。
                period_ms = 1000.0 / max(0.01, entry.hz)
                entry._accum_ms += dt_ms
                if entry._accum_ms + self._interval_ms * 0.25 < period_ms:
                    continue
                entry._accum_ms = max(0.0, entry._accum_ms - period_ms)
            callback = entry.resolve()
            if callback is None or (
                entry.owner_ref is not None and entry.owner_ref() is None
            ):
                entry.dead = True
                dead_ids.append(entry.callback_id)
                continue
            try:
                callback()
            except RuntimeError as exc:
                # 绑定的 C++ 对象已被销毁：静默注销，避免每帧刷日志。
                entry.dead = True
                dead_ids.append(entry.callback_id)
                debug(
                    f"FrameScheduler: subscriber '{entry.callback_id}' dropped "
                    f"({type(exc).__name__}: {exc})"
                )
            except Exception as exc:  # noqa: BLE001 - 单个订阅者失败不得中断帧循环
                warning(
                    f"FrameScheduler: subscriber '{entry.callback_id}' raised "
                    f"{type(exc).__name__}: {exc}"
                )

        if self._pending_frames:
            pending = self._pending_frames
            self._pending_frames = []
            for callback in pending:
                try:
                    callback()
                except Exception as exc:  # noqa: BLE001
                    warning(
                        f"FrameScheduler: deferred frame raised "
                        f"{type(exc).__name__}: {exc}"
                    )

        if dead_ids:
            for cid in dead_ids:
                entry = self._subscribers.pop(cid, None)
                if entry is not None:
                    entry.dead = True
            self._ordered_dirty = True

        work_ms = (time.perf_counter() - start) * 1000.0
        self._work_ema_ms = (
            work_ms
            if self._work_ema_ms <= 0.0
            else self._work_ema_ms * (1.0 - _WORK_EMA_ALPHA) + work_ms * _WORK_EMA_ALPHA
        )
        self._update_governor(work_ms, dt_ms)

        if not self._subscribers and not self._pending_frames and not self._high_rate:
            self._maybe_stop()

    def _rebuild_ordered(self) -> None:
        """按优先级重建分发列表。"""
        self._ordered = sorted(
            (e for e in self._subscribers.values() if not e.dead),
            key=lambda e: e.priority,
        )
        self._ordered_dirty = False

    def _update_governor(self, work_ms: float, dt_ms: float) -> None:
        """过载降级 / 富余升档。

        只有"持续"跟不上才降档：回调本身算不完，或实际间隔长期远超目标帧时长。
        单帧的绘制尖峰（窗口重绘 8~20ms）不算过载，否则会把整机动画误压到半速。

        Args:
            work_ms: 本帧订阅者回调耗时（毫秒）。
            dt_ms: 本帧与上一帧的实际间隔（毫秒）。
        """
        interval = self._interval_ms
        # 只把「我们自己的回调太慢」和「整帧被卡死」当作需要降级的信号。
        # ``_achieved_ms``（相邻两帧的墙钟间隔）会被主线程重绘、I/O、GC 拉长，
        # 拿它降级会造成死亡螺旋：界面越忙 → 档位越低 → 更卡（实测一路掉到
        # 24Hz，正是用户看到的「远低于 30 帧」）。
        overloaded = work_ms > interval * _OVERLOAD_RATIO or dt_ms > interval * _SPIKE_RATIO
        if overloaded:
            self._overload_streak += 1
            self._recover_streak = 0
        else:
            self._overload_streak = 0

        if self._overload_streak >= _OVERLOAD_FRAMES and self._penalty < MAX_PENALTY:
            self._penalty += 1
            self._overload_streak = 0
            self._note("frame_scheduler.degraded")
            warning(
                "FrameScheduler: overloaded, cadence stepped down "
                f"(penalty={self._penalty}, work={work_ms:.2f}ms, "
                f"dt={dt_ms:.2f}ms)"
            )
            self._retune(force=True)
            return

        if not overloaded and work_ms < interval * 0.30 and self._penalty > 0:
            self._recover_streak += 1
            if self._recover_streak >= _RECOVER_FRAMES:
                self._penalty -= 1
                self._recover_streak = 0
                self._note("frame_scheduler.recovered")
                info(f"FrameScheduler: cadence stepped up (penalty={self._penalty})")
                self._retune(force=True)
        elif overloaded:
            self._recover_streak = 0

    @staticmethod
    def _note(counter_name: str) -> None:
        """累加 ``perf_metrics`` 全局计数（失败静默）。"""
        try:
            from sopeek.utils import perf_metrics as pm

            pm.increment_global(counter_name)
        except Exception:  # noqa: BLE001
            pass

    # ================================================================
    # 内部：用户活动探测
    # ================================================================

    def _install_activity_filter(self) -> None:
        """安装应用级事件过滤器（键鼠活动 → 退出空闲档）。"""
        if self._filter_installed:
            return
        app = QCoreApplication.instance()
        if app is None:
            return
        try:
            app.installEventFilter(self)
            self._filter_installed = True
        except Exception:  # noqa: BLE001
            self._filter_installed = False

    def _release_activity_filter(self) -> None:
        """移除事件过滤器。"""
        if not self._filter_installed:
            return
        app = QCoreApplication.instance()
        if app is not None:
            try:
                app.removeEventFilter(self)
            except Exception:  # noqa: BLE001
                pass
        self._filter_installed = False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        """只观察键鼠/触控活动，从不吞事件。"""
        try:
            if int(event.type()) in _ACTIVITY_EVENTS:
                self.note_user_activity()
        except RuntimeError:
            pass
        return False


def frame_scheduler() -> FrameScheduler:
    """返回 :class:`FrameScheduler` 单例。"""
    return FrameScheduler()


def panel_frame_ms() -> float:
    """返回当前面板的一帧毫秒数（供合成器等自行排程的模块使用）。"""
    return frame_interval_ms(DisplayTiming().hz)


__all__ = [
    "FrameScheduler",
    "frame_scheduler",
    "panel_frame_ms",
    "IDLE_AFTER_MS",
    "IDLE_HZ",
    "MIN_HZ",
    "MAX_PENALTY",
]
