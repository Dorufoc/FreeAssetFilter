#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sopeek 心跳管理器

主线程周期性任务的单例协调器。
提供双频率注册、优先级调度、跨线程请求队列和生命周期管理。

节拍来源统一为 :class:`~sopeek.core.managers.frame_scheduler.FrameScheduler`：
两个自建 ``QTimer`` 已移除，改为帧调度器的单个订阅。这样既消除了
"33 ms 被 Windows 15.625 ms 时钟网格量化成 46.9 ms（实测 21fps）"的老问题，
也让动画回调真正跑在显示器刷新率上（普通回调按目标帧率降采样）。

用法：
    hm = HeartbeatManager()
    hm.start()
    hm.register_tick_callback("my_cb", my_func, priority=2, owner=self)
    ...
    hm.stop_all()
"""

from __future__ import annotations

import heapq
import itertools
import threading
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Optional

from PySide6.QtCore import QMetaObject, QObject, Qt, Slot

from sopeek.core.managers.frame_scheduler import frame_scheduler
from sopeek.core.native.platform_timing import (
    begin_highres_timer,
    end_highres_timer,
    get_active_profile,
    highres_timer_enabled_by_env,
)
from sopeek.utils.app_logger import debug, info, warning

#: 历史普通 tick 间隔（毫秒）。``every_n_ticks`` 表达的是「N 个普通 tick」，
#: 而旧实现的普通 tick 固定 33ms，故这里按 33ms 折算成墙钟周期：
#: 升级到帧驱动后，``every_n_ticks=3`` 仍然是 ~99ms，不会变成 ~50ms。
LEGACY_NORMAL_TICK_MS: float = 33.0

#: 历史普通 tick 频率（≈30.3Hz）。既有的「每个 tick」回调原本就是 33ms 一次，
#: 这里作为分发器的最低节拍：既不会比旧版本更慢，也不会为了帧率白白唤醒。
LEGACY_NORMAL_HZ: float = 1000.0 / LEGACY_NORMAL_TICK_MS


class _OwnerRef:
    """QObject 所有者的线程安全弱引用包装。

    存储原始引用用于身份比较，提供存活检查而不保持 QObject 存活。
    """

    __slots__ = ("_ref", "_uid")

    def __init__(self, owner: QObject) -> None:
        self._ref: weakref.ref = weakref.ref(owner)
        self._uid: int = id(owner)

    @property
    def is_dead(self) -> bool:
        """检查引用的 QObject 是否已被删除"""
        return self._ref() is None

    @property
    def uid(self) -> int:
        return self._uid

    def matches(self, owner: QObject) -> bool:
        """检查此引用是否包装了指定的 QObject"""
        return self._uid == id(owner)


@dataclass
class _CallbackEntry:
    """已注册的 tick 回调的内部存储"""

    callback_id: str
    priority: int = 3
    every_n_ticks: int = 1
    owner_ref: Optional[_OwnerRef] = None
    use_fast_tick: bool = False

    # 根据回调类型填充其中一个
    callback: Optional[Callable] = None  # 强引用（非方法可调用对象）
    weak_method: Optional[weakref.WeakMethod] = None  # 弱引用（绑定方法）

    #: 墙钟周期（毫秒）。``> 0`` 时按真实时间触发，与帧率完全解耦；
    #: 为 0 时退回 ``every_n_ticks`` 的帧计数节流（旧语义）。
    interval_ms: float = field(default=0.0, repr=False)

    # every_n_ticks 的降级/恢复锚点由 _slow_since/_fast_since 记录，
    # 具体触发时刻由 _accum_ms 累积的墙钟时间决定。
    #: 距上次触发累积的节拍时间（毫秒）。用累积时间而不是"每 N 帧"判断：
    #: 分发节拍会随显示器刷新率、空闲降频、负载降级而变，只有累积的墙钟
    #: 时间能保证回调周期恒定。
    _accum_ms: float = field(default=0.0, repr=False)
    # P6.4：注销标记（tick 迭代中跳过，避免重建列表）
    dead: bool = field(default=False, repr=False)
    # P6.4：注册时的原始 every_n_ticks（降级后可恢复）
    base_every_n: int = field(default=1, repr=False)
    # P6.4：回调耗时的 EWMA（毫秒）
    cost_ms: float = field(default=0.0, repr=False)
    #: 连续超预算的起始时刻（0 表示当前没有连续超预算）
    _slow_since: float = field(default=0.0, repr=False)
    #: 连续"很便宜"的起始时刻，用于把 every_n_ticks 恢复回 base_every_n
    _fast_since: float = field(default=0.0, repr=False)

    def period_ms(self) -> float:
        """回调的墙钟触发周期（毫秒）。

        ``interval_ms`` 优先；否则 ``every_n_ticks`` 按历史普通 tick 间隔
        （``LEGACY_NORMAL_TICK_MS`` = 33ms）折算——保持「3 个 tick ≈ 99ms」
        这类既有节奏在帧率提升后完全不变。
        """
        if self.interval_ms > 0.0:
            return self.interval_ms
        return float(max(1, self.every_n_ticks)) * LEGACY_NORMAL_TICK_MS

    def resolve(self) -> Optional[Callable]:
        """解析可调用对象，弱引用失效时返回 None"""
        if self.weak_method is not None:
            cb = self.weak_method()
            if cb is None:
                return None
            return cb
        return self.callback


class FutureHandle:
    """request_main_thread 返回的轻量级 Future。

    提供：
        - result(timeout=None) -> Any
        - done() -> bool
        - add_done_callback(cb)
    """

    __slots__ = ("_done", "_result", "_exception", "_callbacks", "_event")

    def __init__(self) -> None:
        self._done: bool = False
        self._result: Any = None
        self._exception: Optional[BaseException] = None
        self._callbacks: list[Callable[["FutureHandle"], None]] = []
        self._event: threading.Event = threading.Event()

    def add_done_callback(
        self, callback: Callable[["FutureHandle"], None]
    ) -> None:
        """添加 future 完成时的回调"""
        if self._done:
            try:
                callback(self)
            except Exception as exc:
                debug(f"FutureHandle 完成回调失败：{exc}")
        else:
            self._callbacks.append(callback)

    def result(self, timeout: Optional[float] = None) -> Any:
        """阻塞直到结果可用，然后返回。

        如果可调用对象抛异常，则抛出存储的异常。
        """
        self._event.wait(timeout=timeout)
        if self._exception is not None:
            raise self._exception
        return self._result

    def done(self) -> bool:
        return self._done

    def _set_result(self, value: Any) -> None:
        self._result = value
        self._done = True
        self._event.set()
        self._run_done_callbacks()

    def _set_exception(self, exc: BaseException) -> None:
        self._exception = exc
        self._done = True
        self._event.set()
        self._run_done_callbacks()

    def _run_done_callbacks(self) -> None:
        for cb in self._callbacks:
            try:
                cb(self)
            except Exception as exc:
                debug(f"FutureHandle 完成回调失败：{exc}")


class HeartbeatManager(QObject):
    """主线程周期性任务的单例心跳协调器。

    节拍由 :class:`~sopeek.core.managers.frame_scheduler.FrameScheduler` 提供：

        - 快速 tick：每个显示帧一次（面板刷新率，最高 240/360Hz）；
        - 普通 tick：按目标帧率降采样（默认 ``min(面板, 60)`` fps），
          每条回调另有 ``every_n_ticks`` 俗称的帧计数节流，或
          ``interval_ms=`` 指定的**墙钟周期**（与帧率无关）。

    时长/监测窗口一律用墙钟时间表达（``interval_ms``、预算、降级/恢复
    窗口、清理间隔），因此提高面板帧率只增加动画平滑度，不改变任何
    既有操作的时长与触发时机。

    特性：
        - 每个 tick 内按优先级排序分发
        - 通过 weakref.WeakMethod 存储弱引用回调
        - 跨线程请求队列（线程安全 deque + 主线程消耗）
        - 所有者感知生命周期，销毁时自动清理
        - tick 超时检测和警告日志
        - 空 tick 优化：无回调且无待处理请求时**完全停表**（帧调度器零唤醒）
        - 成本自适应：单回调持续超预算时降频，恢复富余后自动回到基线频率
    """

    _instance: Optional["HeartbeatManager"] = None
    _lock: threading.Lock = threading.Lock()
    _initialized: bool = False

    #: 普通 tick 的目标最大帧率（面板更高时也不追高，避免无意义的 CPU 占用）。
    NORMAL_TARGET_HZ: int = 60
    #: 兼容旧常量：普通 tick 的理论间隔（毫秒）。实际间隔由帧调度器决定，
    #: 且**不再**作为任何时长/监测窗口的换算基准（见 ``LEGACY_NORMAL_TICK_MS``）。
    NORMAL_TICK_MS: int = 16
    #: 兼容旧常量：快速 tick 的理论间隔（毫秒，60Hz 面板上的值）。
    FAST_TICK_MS: int = 16
    #: 单条普通回调的耗时预算（毫秒）。与节拍无关的绝对值：
    #: 历史语义是「33ms 普通 tick 的一半」，改成帧驱动后仍保持 16.5ms，
    #: 以免提高帧率就悄悄改变了降级的判定门槛。
    NORMAL_TICK_BUDGET_MS: float = 16.5
    #: 连续超预算多久后降级该回调（秒）。
    DEGRADE_AFTER_S: float = 0.066
    #: 连续便宜多久后把降级折半退回基线（秒）。
    RECOVER_AFTER_S: float = 4.0
    #: 失效弱引用清理间隔（秒）。旧实现按 100 tick 计，33ms 档约 3.3s。
    PRUNING_INTERVAL_S: float = 3.3
    #: 超时告警日志的最小间隔（秒），卡顿期放大约束，避免 I/O 二次放大。
    OVERRUN_LOG_INTERVAL_S: float = 4.0
    #: 帧调度器订阅 id
    _SCHEDULER_ID: str = "heartbeat_dispatcher"

    def __new__(cls, parent: Optional[QObject] = None) -> "HeartbeatManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self, parent: Optional[QObject] = None) -> None:
        with self._lock:
            if HeartbeatManager._initialized:
                return
            HeartbeatManager._initialized = True

        super().__init__(parent)

        # Callback registry
        self._callbacks: dict[str, _CallbackEntry] = {}
        self._callback_lock: threading.RLock = threading.RLock()

        # Cross-thread dispatch queue
        self._pending_calls: list = []
        self._pending_calls_lock: threading.RLock = threading.RLock()
        # P6.4：有序回调缓存（注册/注销时置脏，tick 只迭代不复制不排序）
        self._ordered_normal: list[_CallbackEntry] = []
        self._ordered_fast: list[_CallbackEntry] = []
        self._ordered_dirty: bool = True
        self._resume_index: int = 0
        self._pending_seq = itertools.count()
        self._overrun_by_cb: dict[str, int] = {}

        # 帧调度器订阅状态
        self._subscribed: bool = False
        self._subscribed_hz: Optional[float] = None
        #: 普通 tick 的目标帧率（可被 set_normal_tick_rate 调整）
        self._normal_hz: int = self.NORMAL_TARGET_HZ
        #: 当前普通 tick 的实际间隔（毫秒），由帧间隔 × 降采样步长得出
        self._normal_tick_interval: float = 1000.0 / self.NORMAL_TARGET_HZ
        #: 快速 tick 的当前间隔（毫秒）
        self._fast_tick_interval: float = 1000.0 / 60.0
        #: 普通 tick 的帧计数（用于降采样）
        self._frame_counter: int = 0
        self._normal_stride: int = 1

        # Tick counters for pruning
        self._normal_tick_count: int = 0
        self._fast_tick_count: int = 0
        self._animation_callback_count: int = 0
        #: 上一次清理失效弱引用的墙钟时刻（秒）
        self._last_prune: float = time.monotonic()
        #: 下一次允许输出普通/快速 tick 超时告警的墙钟时刻（秒）
        self._next_normal_overrun_log: float = 0.0
        self._next_fast_overrun_log: float = 0.0

        # Running state
        self._running: bool = False

        # W5 高精度定时持有标记：fast-tick 动画窗口期持有
        # timeBeginPeriod(1)，窗口结束即释放（见 platform_timing 模块契约）。
        self._highres_timer_held: bool = False

        # 帧调度器的"硬需求"令牌：fast-tick 回调就是逐帧动画，动画在跑时
        # 不能被空闲降频压到 IDLE_HZ，否则用户不动鼠标时动画会掉到 30fps。
        self._fast_rate_token: str = "heartbeat.fast_animation"
        self._fast_rate_held: bool = False

        info("HeartbeatManager initialized (frame-scheduler driven)")

    # ================================================================
    # 生命周期
    # ================================================================

    def start(self) -> None:
        """启动心跳分发（空 tick 优化：无回调时不占用任何唤醒）。"""
        if self._running:
            return
        self._running = True
        self._sync_subscription()
        info("HeartbeatManager started")

    def stop(self) -> None:
        """停止心跳分发，保留已注册的回调"""
        self._running = False
        self._release_fast_rate()
        self._unsubscribe_scheduler()

    def stop_all(self) -> None:
        """停止分发并清除所有已注册的回调和待处理请求"""
        self.stop()
        with self._callback_lock:
            self._callbacks.clear()
        with self._pending_calls_lock:
            self._pending_calls.clear()
        self._animation_callback_count = 0
        self._ordered_dirty = True
        info("HeartbeatManager stopped all")

    # ================================================================
    # 回调注册
    # ================================================================

    def register_tick_callback(
        self,
        callback_id: str,
        callback: Callable,
        priority: int = 3,
        every_n_ticks: int = 1,
        owner: Optional[QObject] = None,
        use_fast_tick: bool = False,
        interval_ms: Optional[float] = None,
    ) -> str:
        """注册一个周期性回调。

        Args:
            callback_id: 该回调的唯一标识符。
            callback: 每次 tick 调用的可调用对象。
            priority: 0（最高）到 4（最低）。默认 3。
            every_n_ticks: 每 N 次普通 tick 触发一次（帧计数语义）。
                仅在未指定 ``interval_ms`` 时生效。
            owner: 用于所有者感知生命周期管理的 QObject。
            use_fast_tick: 若为 True，则每个显示帧都触发（面板刷新率）。
            interval_ms: 墙钟触发周期（毫秒）。指定后回调按真实时间触发，
                **与面板刷新率和普通 tick 目标帧率都无关**；这样「每 100ms
                泵一次信号」之类的既有节奏不会因为帧率提升而变快。

        Returns:
            作为注册令牌的 callback_id。

        Raises:
            ValueError: 如果 callback_id 已注册。
        """
        if not callable(callback):
            raise TypeError("callback must be callable")

        period_ms = 0.0
        if interval_ms is not None:
            try:
                period_ms = max(0.0, float(interval_ms))
            except (TypeError, ValueError):
                period_ms = 0.0

        with self._callback_lock:
            if callback_id in self._callbacks:
                raise ValueError(
                    f"Callback '{callback_id}' is already registered"
                )

            # 优先使用 WeakMethod 绑定方法，回退到强引用
            weak_method: Optional[weakref.WeakMethod] = None
            try:
                weak_method = weakref.WeakMethod(callback)
            except TypeError:
                pass

            owner_ref: Optional[_OwnerRef] = None
            if owner is not None:
                owner_ref = _OwnerRef(owner)
                try:
                    owner.destroyed.connect(self._on_owner_destroyed)
                except (RuntimeError, TypeError):
                    pass

            entry = _CallbackEntry(
                callback_id=callback_id,
                priority=max(0, min(4, priority)),
                every_n_ticks=max(1, every_n_ticks),
                base_every_n=max(1, every_n_ticks),
                owner_ref=owner_ref,
                use_fast_tick=use_fast_tick,
                callback=None if weak_method is not None else callback,
                weak_method=weak_method,
                interval_ms=period_ms,
            )
            self._callbacks[callback_id] = entry
            self._ordered_dirty = True

        if use_fast_tick:
            self._animation_callback_count += 1
            self._maybe_start_fast_timer()

        # 订阅帧调度器（空 tick 优化：没有回调时不会唤醒）
        self._sync_subscription()

        return callback_id

    def unregister_tick_callback(self, callback_id: str) -> bool:
        """取消注册之前注册的回调。

        Args:
            callback_id: 注册时使用的标识符。

        Returns:
            找到并移除返回 True，否则返回 False。
        """
        with self._callback_lock:
            entry = self._callbacks.pop(callback_id, None)
            if entry is not None:
                entry.dead = True
                self._ordered_dirty = True

        if entry is None:
            return False

        if entry.use_fast_tick:
            self._animation_callback_count -= 1
            self._maybe_stop_fast_timer()

        self._sync_subscription()

        return True

    def unregister_all_for_owner(self, owner: QObject) -> int:
        """取消注册指定所有者的所有回调。

        Args:
            owner: 需要移除回调的 QObject。

        Returns:
            移除的回调数量。
        """
        with self._callback_lock:
            cids = [
                cid
                for cid, entry in self._callbacks.items()
                if entry.owner_ref is not None and entry.owner_ref.matches(owner)
            ]

        count = 0
        for cid in cids:
            if self.unregister_tick_callback(cid):
                count += 1
        return count

    def set_normal_tick_rate(self, fps: int) -> None:
        """调整普通 tick 的目标帧率上限。

        这是**上限**而不是实际节拍：真实唤醒频率由各回调声明的墙钟周期决定，
        并且不低于 ``LEGACY_NORMAL_HZ``（≈30.3Hz，旧实现的 33ms 节拍）。
        因此调整该值只改变「允许的最快普通节拍」，不会改变任何回调的时长。

        Args:
            fps: 目标每秒帧数（最小 1）。
        """
        self._normal_hz = max(1, int(fps))
        self._normal_tick_interval = 1000.0 / self._normal_hz
        if self._running:
            self._sync_subscription()

    # ================================================================
    # 跨线程调度
    # ================================================================

    def request_main_thread(
        self, fn: Callable, priority: int = 5
    ) -> FutureHandle:
        """调度一个可调用对象在主线程执行。

        线程安全。可调用对象被排队并在下一个心跳 tick 中在主线程执行。

        Args:
            fn: 要在主线程执行的可调用对象。
            priority: 回调优先级（0=最高，5=最低）。默认 5。

        Returns:
            可调用对象完成时解析的 FutureHandle。
        """
        future = FutureHandle()
        with self._pending_calls_lock:
            heapq.heappush(
                self._pending_calls,
                (priority, next(self._pending_seq), fn, future),
            )

        # 确保分发在跑：通过 QueuedConnection 把唤醒投递到主线程
        if self._running:
            try:
                QMetaObject.invokeMethod(
                    self,
                    "_on_cross_thread_wake",
                    Qt.ConnectionType.QueuedConnection,
                )
            except (RuntimeError, TypeError):
                pass

        return future

    @Slot()
    def _on_cross_thread_wake(self) -> None:
        """跨线程唤醒槽：确保帧调度器在跑（主线程执行）。"""
        self._sync_subscription()

    # ================================================================
    # 内部：节拍订阅
    # ================================================================

    def _desired_hz(self) -> Optional[float]:
        """当前需要的调度频率；``None`` 表示"每个显示帧都要"。

        频率取「最快回调的墙钟周期」与历史节拍 ``LEGACY_NORMAL_HZ`` 的较大值
        （再受 ``NORMAL_TARGET_HZ`` 上限约束）：只会为了满足更快的回调提速，
        不会因为面板是 240Hz 就无谓地按 240Hz 唤醒主线程。
        """
        if self._animation_callback_count > 0:
            return None
        with self._callback_lock:
            periods = [
                entry.period_ms()
                for entry in self._callbacks.values()
                if not entry.dead and not entry.use_fast_tick
            ]
        need_hz = LEGACY_NORMAL_HZ
        if periods:
            fastest = min(periods)
            if fastest > 0.0:
                need_hz = max(need_hz, 1000.0 / fastest)
        return float(min(float(self._normal_hz), need_hz))

    def _sync_subscription(self) -> None:
        """按当前回调集合同步帧调度器订阅（空集合则完全停表）。"""
        if not self._running:
            return
        with self._callback_lock:
            has_callbacks = bool(self._callbacks)
        with self._pending_calls_lock:
            has_pending = bool(self._pending_calls)
        if not has_callbacks and not has_pending:
            self._unsubscribe_scheduler()
            return
        desired = self._desired_hz()
        if self._subscribed and desired == self._subscribed_hz:
            return
        frame_scheduler().subscribe(
            self._SCHEDULER_ID,
            self._on_frame,
            hz=desired,
            priority=0,
            owner=self,
        )
        self._subscribed = True
        self._subscribed_hz = desired

    def _unsubscribe_scheduler(self) -> None:
        """取消帧调度器订阅并释放高精度定时。"""
        if self._subscribed:
            try:
                frame_scheduler().unsubscribe(self._SCHEDULER_ID)
            except Exception:  # noqa: BLE001
                pass
        self._subscribed = False
        self._subscribed_hz = None
        self._release_highres_timer()

    # ================================================================
    # 内部：tick 处理
    # ================================================================

    def _on_frame(self) -> None:
        """帧调度器每个节拍调用一次：先跑快速回调，再按步长跑普通回调。"""
        if not self._running:
            return

        interval_ms = frame_scheduler().interval_ms()
        self._fast_tick_interval = interval_ms

        # 优先处理跨线程队列（每帧都排空，延迟 ≤ 一帧）
        self._drain_pending_queue()

        if self._animation_callback_count > 0:
            self._process_fast_tick()

        stride = self._compute_normal_stride(interval_ms)
        self._normal_stride = stride
        self._normal_tick_interval = interval_ms * stride
        self._frame_counter += 1
        if self._frame_counter % stride == 0:
            self._process_normal_tick()

        with self._callback_lock:
            has_callbacks = bool(self._callbacks)
        with self._pending_calls_lock:
            has_pending = bool(self._pending_calls)
        if not has_callbacks and not has_pending:
            self._unsubscribe_scheduler()

    def _compute_normal_stride(self, interval_ms: float) -> int:
        """把面板帧间隔降采样到普通 tick 的目标帧率。

        Args:
            interval_ms: 当前帧间隔（毫秒）。

        Returns:
            每隔多少帧跑一次普通 tick（≥ 1）。
        """
        if interval_ms <= 0.0:
            return 1
        target_interval = 1000.0 / max(1, self._normal_hz)
        return max(1, int(round(target_interval / interval_ms)))

    def _process_normal_tick(self) -> None:
        """处理一个普通 tick（P6.4：有序缓存 + 预算降级 + 断点续跑）。"""
        if not self._running:
            return

        # 优先处理跨线程队列
        self._drain_pending_queue()

        with self._callback_lock:
            if not self._callbacks:
                return
            if self._ordered_dirty:
                self._rebuild_ordered_locked()
            entries = self._ordered_normal

        self._normal_tick_count += 1
        if not entries:
            return

        start = time.monotonic()
        # 预算是绝对值（16.5ms = 旧 33ms tick 的一半）：改成帧驱动后如果沿用
        # 「当前间隔的一半」，面板越快门槛越紧，会凭空多出降级。
        budget_ms = self.NORMAL_TICK_BUDGET_MS
        cadence_ms = max(1.0, self._normal_tick_interval)
        dead_ids: list[str] = []
        start_index = self._resume_index % len(entries)
        self._resume_index = 0

        for offset in range(len(entries)):
            idx = (start_index + offset) % len(entries)
            entry = entries[idx]
            # 跳过已注销与快速 tick 条目（不重建列表）
            if entry.dead or entry.use_fast_tick:
                continue

            now = time.monotonic()

            # 周期 → 墙钟到期：用「累积经过的节拍时间」判断，放行后**减去**
            # 周期而不是清零，余量留到下一次，长期平均周期才不会因整数取整
            # 而缩水；允许 1/4 拍容差，避免 99ms 周期配 33.33ms 节拍时在
            # 「2 拍还是 3 拍」之间跳动（那会让周期忽快忽慢）。
            period_ms = entry.period_ms()
            entry._accum_ms += cadence_ms
            if entry._accum_ms + cadence_ms * 0.25 < period_ms:
                continue
            entry._accum_ms = max(0.0, entry._accum_ms - period_ms)

            cb = entry.resolve()
            if cb is None:
                entry.dead = True
                dead_ids.append(entry.callback_id)
                continue

            cb_start = time.monotonic()
            try:
                cb()
            except Exception as exc:
                warning(
                    f"Heartbeat: callback '{entry.callback_id}' raised "
                    f"{type(exc).__name__}: {exc}"
                )
                self._bump_overrun(entry.callback_id)
            cost_ms = (time.monotonic() - cb_start) * 1000.0
            entry.cost_ms = 0.8 * entry.cost_ms + 0.2 * cost_ms
            if entry.interval_ms > 0.0:
                # 墙钟周期的回调不参与帧计数降级：它的节奏由调用方声明。
                pass
            elif entry.cost_ms > budget_ms * 0.5:
                if entry._slow_since <= 0.0:
                    entry._slow_since = now
                entry._fast_since = 0.0
                if (
                    now - entry._slow_since >= self.DEGRADE_AFTER_S
                    and entry.every_n_ticks < 4
                ):
                    entry.every_n_ticks = min(4, entry.every_n_ticks * 2)
                    entry._slow_since = 0.0
                    self._note("heartbeat.degraded")
            else:
                entry._slow_since = 0.0
                # 恢复：连续便宜 RECOVER_AFTER_S 后把降级折半退回基线频率
                if entry.every_n_ticks > entry.base_every_n:
                    if entry._fast_since <= 0.0:
                        entry._fast_since = now
                    elif now - entry._fast_since >= self.RECOVER_AFTER_S:
                        entry.every_n_ticks = max(
                            entry.base_every_n, entry.every_n_ticks // 2
                        )
                        entry._fast_since = 0.0
                        self._note("heartbeat.recovered")
                else:
                    entry._fast_since = 0.0

            # 断点续跑：优先留给 priority ≤ 1 的回调，其余下次从断点继续。
            if (
                entry.priority > 1
                and (time.monotonic() - start) * 1000.0 > budget_ms
            ):
                self._resume_index = (idx + 1) % len(entries)
                self._note("heartbeat.overrun")
                break

        if dead_ids:
            with self._callback_lock:
                for cid in dead_ids:
                    entry = self._callbacks.pop(cid, None)
                    if entry and entry.use_fast_tick:
                        self._animation_callback_count -= 1
                self._ordered_dirty = True

        now_mono = time.monotonic()
        if now_mono - self._last_prune >= self.PRUNING_INTERVAL_S:
            self._last_prune = now_mono
            self._prune_dead_callbacks()

        elapsed_ms = (now_mono - start) * 1000
        self._note_duration("heartbeat.tick", elapsed_ms)
        if elapsed_ms > self._normal_tick_interval:
            self._note("heartbeat.overrun")
            # 时间节流：卡顿期日志 I/O 会二次放大卡顿。
            if now_mono >= self._next_normal_overrun_log:
                self._next_normal_overrun_log = (
                    now_mono + self.OVERRUN_LOG_INTERVAL_S
                )
                warning(
                    f"Heartbeat: normal tick overrun "
                    f"({elapsed_ms:.1f}ms > {self._normal_tick_interval:.1f}ms interval)"
                )

    def _process_fast_tick(self) -> None:
        """处理单个快速 tick（仅动画回调；P6.4 有序缓存）。"""
        if not self._running:
            return

        with self._callback_lock:
            if self._ordered_dirty:
                self._rebuild_ordered_locked()
            entries = self._ordered_fast

        if not entries:
            return

        self._fast_tick_count += 1
        start = time.monotonic()
        dead_ids: list[str] = []

        for entry in entries:
            if entry.dead:
                continue
            cb = entry.resolve()
            if cb is None:
                entry.dead = True
                dead_ids.append(entry.callback_id)
                continue

            try:
                cb()
            except Exception as exc:
                warning(
                    f"Heartbeat: fast callback '{entry.callback_id}' "
                    f"raised {type(exc).__name__}: {exc}"
                )

        if dead_ids:
            with self._callback_lock:
                for cid in dead_ids:
                    entry = self._callbacks.pop(cid, None)
                    if entry and entry.use_fast_tick:
                        self._animation_callback_count -= 1
                self._ordered_dirty = True

        now_mono = time.monotonic()
        elapsed_ms = (now_mono - start) * 1000
        if elapsed_ms > self._fast_tick_interval:
            # 与普通 tick 一致按时间节流，避免掉帧时日志刷屏。
            if now_mono >= self._next_fast_overrun_log:
                self._next_fast_overrun_log = (
                    now_mono + self.OVERRUN_LOG_INTERVAL_S
                )
                warning(
                    f"Heartbeat: fast tick overrun "
                    f"({elapsed_ms:.1f}ms > {self._fast_tick_interval:.1f}ms interval)"
                )

    def _drain_pending_queue(self) -> None:
        """在主线程执行所有排队的跨线程请求（heapq 保优先级 + FIFO）。"""
        with self._pending_calls_lock:
            if not self._pending_calls:
                return
            calls = list(self._pending_calls)
            self._pending_calls.clear()

        heapq.heapify(calls)
        while calls:
            _priority, _seq, fn, future = heapq.heappop(calls)
            try:
                result = fn()
                future._set_result(result)
            except BaseException as exc:
                future._set_exception(exc)

    # ================================================================
    # 内部：所有者生命周期
    # ================================================================

    def _rebuild_ordered_locked(self) -> None:
        """按优先级重建两份有序列表（调用方必须持有 ``_callback_lock``）。"""
        normal: list[_CallbackEntry] = []
        fast: list[_CallbackEntry] = []
        for entry in self._callbacks.values():
            if entry.dead:
                continue
            if entry.use_fast_tick:
                fast.append(entry)
            else:
                normal.append(entry)
        normal.sort(key=lambda e: e.priority)
        fast.sort(key=lambda e: e.priority)
        self._ordered_normal = normal
        self._ordered_fast = fast
        self._ordered_dirty = False

    @staticmethod
    def _note(counter_name: str) -> None:
        """累加一个 ``perf_metrics`` 全局计数（失败静默）。"""
        try:
            from sopeek.utils import perf_metrics as pm

            pm.increment_global(counter_name)
        except Exception:  # noqa: BLE001 - 埋点不得影响心跳
            pass

    @staticmethod
    def _note_duration(event_name: str, elapsed_ms: float) -> None:
        """记录一次耗时（失败静默）。"""
        try:
            from sopeek.utils import perf_metrics as pm

            pm.record_duration(event_name, elapsed_ms)
        except Exception:  # noqa: BLE001
            pass

    def _bump_overrun(self, callback_id: str) -> None:
        """记录单回调异常/超时次数（本地字典，避免热路径取锁）。"""
        self._overrun_by_cb[callback_id] = (
            self._overrun_by_cb.get(callback_id, 0) + 1
        )

    def overrun_by_callback(self) -> dict[str, int]:
        """返回单个回调的异常/超时次数副本（诊断用）。"""
        return dict(self._overrun_by_cb)

    def diagnostics(self) -> dict[str, Any]:
        """返回节拍诊断快照（日志/性能面板用）。"""
        with self._callback_lock:
            total = len(self._callbacks)
            fast = sum(1 for e in self._callbacks.values() if e.use_fast_tick)
        return {
            "running": self._running,
            "callbacks": total,
            "fast_callbacks": fast,
            "normal_hz": self._normal_hz,
            "normal_stride": self._normal_stride,
            "normal_interval_ms": round(self._normal_tick_interval, 2),
            "fast_interval_ms": round(self._fast_tick_interval, 2),
            "normal_ticks": self._normal_tick_count,
            "fast_ticks": self._fast_tick_count,
            "highres_held": self._highres_timer_held,
        }

    def _on_owner_destroyed(self) -> None:
        """连接到 owner.destroyed 信号的槽。

        扫描所有已注册回调，移除所有者 QObject 已销毁的条目（失效弱引用或已删除的 C++ 对象）。

        使用非阻塞锁获取以避免在 GC 期间发生死锁：
        若锁已被持有（例如在 tick 处理中），跳过此次清理，
        由 _prune_dead_callbacks（每 ``PRUNING_INTERVAL_S`` 秒一次）完成清理。
        """
        if not self._callback_lock.acquire(blocking=False):
            return
        try:
            dead: list[str] = []
            for cid, entry in self._callbacks.items():
                if entry.owner_ref is None:
                    continue
                # 检查弱引用是否存活
                if entry.owner_ref.is_dead:
                    dead.append(cid)
                    continue
                # 通过 QObject 存活状态二次确认
                owner = entry.owner_ref._ref()
                if owner is not None:
                    try:
                        owner.objectName()
                    except RuntimeError:
                        dead.append(cid)
        finally:
            self._callback_lock.release()

        for cid in dead:
            self.unregister_tick_callback(cid)

    # ================================================================
    # 内部：清理与辅助
    # ================================================================

    def _prune_dead_callbacks(self) -> None:
        """定期维护：移除失效弱引用或所有者已销毁的条目"""
        with self._callback_lock:
            dead: list[str] = []
            for cid, entry in self._callbacks.items():
                # 检查弱方法
                if entry.weak_method is not None and entry.weak_method() is None:
                    dead.append(cid)
                    continue
                # 检查所有者存活状态
                if entry.owner_ref is not None and entry.owner_ref.is_dead:
                    dead.append(cid)

            for cid in dead:
                entry = self._callbacks.pop(cid, None)
                if entry and entry.use_fast_tick:
                    self._animation_callback_count -= 1
            if dead:
                self._ordered_dirty = True

    def _maybe_start_fast_timer(self) -> None:
        """存在动画回调时把帧调度器抬到"每个显示帧"，并占住硬需求令牌。"""
        if self._animation_callback_count > 0:
            self._acquire_highres_timer()
            self._acquire_fast_rate()
            self._sync_subscription()

    def _maybe_stop_fast_timer(self) -> None:
        """无动画回调时释放硬需求令牌、高精度定时并回落到普通帧率。"""
        if self._animation_callback_count <= 0:
            self._fast_tick_count = 0
            self._release_fast_rate()
            self._release_highres_timer()
            self._sync_subscription()

    def _acquire_fast_rate(self) -> None:
        """为逐帧动画占住帧调度器的硬需求令牌（幂等）。

        与 ``_acquire_highres_timer`` 的区别：高精度定时只在显式 opt-in
        时生效，而"动画不被空闲降频"是默认行为，不依赖任何环境变量。
        """
        if self._fast_rate_held:
            return
        try:
            frame_scheduler().request_high_rate(self._fast_rate_token)
            self._fast_rate_held = True
        except Exception:
            warning("Heartbeat: request_high_rate failed, animation may idle-throttle")

    def _release_fast_rate(self) -> None:
        """释放逐帧动画的硬需求令牌（与 acquire 严格成对）。"""
        if not self._fast_rate_held:
            return
        self._fast_rate_held = False
        try:
            frame_scheduler().release_high_rate(self._fast_rate_token)
        except Exception:
            warning("Heartbeat: release_high_rate failed")

    def _highres_timer_allowed(self) -> bool:
        """W5 挂接门控：显式 opt-in 且非省电档才允许自动持有。

        默认关闭，保证基准/阻塞测试与 CI 永不开启系统全局
        timeBeginPeriod；todo 14 三档开关落地后由档位统一控制。
        """
        if not highres_timer_enabled_by_env():
            return False
        return get_active_profile() != "powersave"

    def _acquire_highres_timer(self) -> None:
        """动画窗口开启时持有一次高精度定时（幂等，引用计数在模块侧）。"""
        if self._highres_timer_held or not self._highres_timer_allowed():
            return
        try:
            if begin_highres_timer():
                self._highres_timer_held = True
        except Exception:
            warning("Heartbeat: begin_highres_timer failed, continuing without it")

    def _release_highres_timer(self) -> None:
        """动画窗口结束时释放持有的高精度定时（与 acquire 严格成对）。"""
        if not self._highres_timer_held:
            return
        self._highres_timer_held = False
        try:
            end_highres_timer()
        except Exception:
            warning("Heartbeat: end_highres_timer failed")
