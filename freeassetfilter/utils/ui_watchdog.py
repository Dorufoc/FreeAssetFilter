#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主线程卡顿哨兵（P6.1）。

为什么不能用 QTimer 单打独斗
----------------------------
主线程被阻塞时 ``QTimer`` **根本不会触发**，只能在卡顿结束后采到「超时了」，
拿不到「卡在哪一行」。因此本模块拆成两支：

* **漂移探针**（主线程，唯一常驻开销 = 1 个 QTimer）：用
  「期望触发时刻累加」而不是「每次重置」，能识别持续小卡顿的累积；
* **栈采样器**（独立 daemon 线程，不碰 Qt）：周期性抓取主线程
  ``sys._current_frames()``，只在发生卡顿的时间窗内归因。

默认关闭（``FAF_UI_WATCHDOG=0``）：关闭时 ``install()`` 不创建 QTimer、
不创建线程，仅一次模块级标志检查。

环境变量
--------
============================ ====== ============================================
变量                          默认   语义
============================ ====== ============================================
``FAF_UI_WATCHDOG``           ``0``  总开关
``FAF_UI_WATCHDOG_INTERVAL_MS`` ``100`` 漂移探针周期
``FAF_UI_WATCHDOG_STALL_MS``  ``200`` 卡顿阈值（≥ 即记一次）
``FAF_UI_WATCHDOG_STACK_MS``  ``25``  栈采样周期；``0`` = 只漂移不采样
``FAF_UI_WATCHDOG_AGGS``      ``200`` 聚合桶上限
============================ ====== ============================================

输出（经 ``perf_metrics`` 的 ``providers`` 段）::

    {
      "enabled": true, "interval_ms": 100, "stall_ms": 200,
      "stalls": {"warn": 2, "severe": 0, "critical": 0, "total": 2},
      "worst_ms": 431.2,
      "top_stacks": [{"frames": [...], "count": 1, "total_ms": 431.2, "max_ms": 431.2}]
    }

已知边界（写入报告，避免误读）：

* 若主线程卡在**持 GIL 的原生调用**里，采样线程拿不到 GIL，采到的是空气；
  此时只能看到「有卡顿但无归因」；
* PyInstaller ``console=False`` 下 ``sys.stderr`` 不可用；frozen 的
  ``co_filename`` 指向 ``_MEI*``，行号可能与源码错位——栈文本只作函数级证据。
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QTimer

from freeassetfilter.utils.app_logger import debug, warning
from freeassetfilter.utils.perf_metrics import (
    increment_global,
    record_duration,
    register_snapshot_provider,
    unregister_snapshot_provider,
)

#: 卡顿分级阈值（毫秒）。
_STALL_WARN_MS = 200.0
_STALL_SEVERE_MS = 500.0
_STALL_CRITICAL_MS = 2000.0
#: 卡顿事件环形缓冲上限。
_STALL_RING_MAX = 256
#: 栈采样环形缓冲上限。
_STACK_RING_MAX = 256
#: 栈聚合桶硬上限（超出只计数，不新增键）。
_AGG_MAX = 200
#: 单次采样向上追溯的最大帧数。
_STACK_DEPTH = 24
#: 聚合键保留的首尾帧数（中间层抖动大，直接丢弃）。
_STACK_EDGE = 6
#: 采样器自检：连续 N 拍的均值超过阈值即自动禁用。
_SELF_CHECK_SAMPLES = 20
_SELF_CHECK_BUDGET_MS = 2.0

#: 模块级单例（``install`` 幂等）。
_instance: Optional["UiWatchdog"] = None


def _truthy_env(name: str, default: str = "0") -> bool:
    """判断环境变量是否为真值。"""
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


class _StackAgg:
    """单个聚合键的统计（用 ``__slots__`` 控制内存）。"""

    __slots__ = ("count", "total_ms", "max_ms", "first_ts", "last_ts")

    def __init__(self, ts: float, duration_ms: float) -> None:
        self.count: int = 1
        self.total_ms: float = duration_ms
        self.max_ms: float = duration_ms
        self.first_ts: float = ts
        self.last_ts: float = ts

    def add(self, ts: float, duration_ms: float) -> None:
        """累加一次卡顿归因。"""
        self.count += 1
        self.total_ms += duration_ms
        self.max_ms = max(self.max_ms, duration_ms)
        self.last_ts = ts


class UiWatchdog(QObject):
    """主线程卡顿哨兵（漂移探针 + 栈采样器）。"""

    def __init__(self, parent: Optional[QObject] = None) -> None:
        """创建探针（不启动）。

        Args:
            parent: 可选 QObject 父对象（通常传 QApplication）。
        """
        super().__init__(parent)
        self._interval_ms = max(
            10, int(os.environ.get("FAF_UI_WATCHDOG_INTERVAL_MS", "100"))
        )
        self._stall_ms = max(
            50.0, float(os.environ.get("FAF_UI_WATCHDOG_STALL_MS", "200"))
        )
        self._stack_ms = max(0, int(os.environ.get("FAF_UI_WATCHDOG_STACK_MS", "25")))
        self._agg_max = max(10, int(os.environ.get("FAF_UI_WATCHDOG_AGGS", "200")))

        self._timer = QTimer(self)
        self._timer.setInterval(self._interval_ms)
        self._timer.timeout.connect(self._on_tick)
        self._expected: Optional[float] = None

        self._stalls: Deque[Tuple[float, float, str]] = deque(maxlen=_STALL_RING_MAX)
        self._stack_ring: Deque[Tuple[float, Tuple[Any, ...]]] = deque(
            maxlen=_STACK_RING_MAX
        )
        self._aggs: Dict[Tuple[Any, ...], _StackAgg] = {}
        self._code_refs: Dict[int, Any] = {}
        self._overflow_aggs: int = 0

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._sample_costs: Deque[float] = deque(maxlen=_SELF_CHECK_SAMPLES)
        self._sampler_disabled: bool = False
        self._running: bool = False

    # ── 生命周期 ──────────────────────────────────────────────────────────
    def start(self) -> None:
        """启动漂移探针（可选栈采样器）；重复调用幂等。"""
        if self._running:
            return
        self._running = True
        self._expected = time.monotonic() + self._interval_ms / 1000.0
        self._timer.start()
        if self._stack_ms > 0:
            self._thread = threading.Thread(
                target=self._sample_loop,
                name="faf-ui-watchdog",
                daemon=True,
            )
            self._thread.start()
        debug(
            f"[ui_watchdog] started interval={self._interval_ms}ms "
            f"stall={self._stall_ms}ms stack={self._stack_ms}ms"
        )

    def stop(self) -> None:
        """停止探针与采样线程（幂等）。"""
        if not self._running:
            return
        self._running = False
        self._timer.stop()
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.5)
        self._thread = None
        debug("[ui_watchdog] stopped")

    # ── 漂移探针 ──────────────────────────────────────────────────────────
    def _on_tick(self) -> None:
        """QTimer 回调：计算相对「期望触发时刻」的漂移。"""
        now = time.monotonic()
        if self._expected is None:
            self._expected = now + self._interval_ms / 1000.0
            return
        interval = self._interval_ms / 1000.0
        lag_ms = (now - self._expected) * 1000.0
        self._expected += interval
        if lag_ms > 5.0 * self._interval_ms:
            # 被跳过多拍（系统休眠/调试断点）：重锚，避免误报一次巨值。
            self._expected = now + interval
        if lag_ms < self._stall_ms:
            return
        start_ts = now - lag_ms / 1000.0
        if lag_ms >= _STALL_CRITICAL_MS:
            kind = "critical"
        elif lag_ms >= _STALL_SEVERE_MS:
            kind = "severe"
        else:
            kind = "warn"
        self._record_stall(start_ts, now, lag_ms, kind)

    def _record_stall(
        self, start_ts: float, end_ts: float, duration_ms: float, kind: str
    ) -> None:
        """记录一次卡顿并做栈归因。"""
        self._stalls.append((start_ts, duration_ms, kind))
        increment_global("ui_watchdog.stalls")
        increment_global(f"ui_watchdog.stalls.{kind}")
        record_duration("ui_watchdog.stall", duration_ms, success=False)
        self._attribute_stacks(start_ts, end_ts, duration_ms)

    def _attribute_stacks(
        self, start_ts: float, end_ts: float, duration_ms: float
    ) -> None:
        """把卡顿窗口内的栈样本累加到聚合桶。"""
        if not self._stack_ring:
            return
        hits = [key for ts, key in self._stack_ring if start_ts <= ts <= end_ts]
        if not hits:
            return
        share = duration_ms / len(hits)
        for key in hits:
            agg = self._aggs.get(key)
            if agg is None:
                if len(self._aggs) >= min(self._agg_max, _AGG_MAX):
                    self._overflow_aggs += 1
                    continue
                self._aggs[key] = _StackAgg(end_ts, share)
            else:
                agg.add(end_ts, share)

    # ── 栈采样器 ──────────────────────────────────────────────────────────
    def _sample_loop(self) -> None:
        """采样线程主循环（不碰 Qt，不格式化字符串）。"""
        main_ident = threading.main_thread().ident
        period = self._stack_ms / 1000.0
        while not self._stop_event.wait(period):
            started = time.perf_counter()
            frames = sys._current_frames()
            frame = frames.get(main_ident) if main_ident is not None else None
            if frame is not None:
                key = self._make_stack_key(frame)
                self._stack_ring.append((time.monotonic(), key))
            cost_ms = (time.perf_counter() - started) * 1000.0
            self._sample_costs.append(cost_ms)
            if (
                len(self._sample_costs) == _SELF_CHECK_SAMPLES
                and sum(self._sample_costs) / _SELF_CHECK_SAMPLES
                > _SELF_CHECK_BUDGET_MS
            ):
                self._sampler_disabled = True
                warning(
                    "[ui_watchdog] 采样开销超预算，自动禁用栈采样"
                    f"（均值 {sum(self._sample_costs) / _SELF_CHECK_SAMPLES:.2f}ms/拍）"
                )
                return

    def _make_stack_key(self, frame: Any) -> Tuple[Any, ...]:
        """把主线程栈归一为聚合键（外 6 层 + … + 内 6 层）。

        Args:
            frame: ``sys._current_frames()`` 返回的栈帧。

        Returns:
            tuple: ``(id(code), lineno)`` 元组序列（中间层折叠）。
        """
        collected: List[Tuple[int, int]] = []
        current = frame
        depth = 0
        while current is not None and depth < _STACK_DEPTH:
            code = current.f_code
            self._code_refs[id(code)] = code
            collected.append((id(code), current.f_lineno))
            current = current.f_back
            depth += 1
        if len(collected) > _STACK_EDGE * 2:
            return (
                tuple(collected[:_STACK_EDGE])
                + (("…", 0),)
                + tuple(collected[-_STACK_EDGE:])
            )
        return tuple(collected)

    def _describe_frame(self, token: Tuple[Any, int]) -> str:
        """把 ``(id(code), lineno)`` 还原为可读文本。"""
        code_id, lineno = token
        if code_id == "…":
            return "…"
        code = self._code_refs.get(code_id)
        if code is None:
            return f"<unknown>:{lineno}"
        return f"{code.co_filename}:{lineno} in {code.co_name}"

    # ── 导出 ──────────────────────────────────────────────────────────────
    def provider(self) -> Dict[str, Any]:
        """构造 ``perf_metrics`` 快照的 ``ui_watchdog`` 段。

        Returns:
            dict: 计数、最差值与前 20 个栈聚合。
        """
        counts = {"warn": 0, "severe": 0, "critical": 0, "total": len(self._stalls)}
        worst = 0.0
        for _ts, duration_ms, kind in self._stalls:
            counts[kind] = counts.get(kind, 0) + 1
            worst = max(worst, duration_ms)
        ranked = sorted(
            self._aggs.items(), key=lambda item: item[1].max_ms, reverse=True
        )[:20]
        top_stacks = [
            {
                "frames": [self._describe_frame(token) for token in key],
                "count": agg.count,
                "total_ms": round(agg.total_ms, 3),
                "max_ms": round(agg.max_ms, 3),
            }
            for key, agg in ranked
        ]
        return {
            "enabled": self._running,
            "interval_ms": self._interval_ms,
            "stall_ms": self._stall_ms,
            "stack_sample_ms": self._stack_ms,
            "sampler_disabled": self._sampler_disabled,
            "stalls": counts,
            "worst_ms": round(worst, 3),
            "unattributed_overflow": self._overflow_aggs,
            "top_stacks": top_stacks,
        }

    def reset(self) -> None:
        """清空累计（测试用）。"""
        self._stalls.clear()
        self._stack_ring.clear()
        self._aggs.clear()
        self._overflow_aggs = 0


def install(app: Optional[QObject] = None) -> Optional[UiWatchdog]:
    """按环境变量安装哨兵（幂等）。

    ``FAF_UI_WATCHDOG`` 未开启时**不创建任何 QTimer 或线程**。

    Args:
        app: 可选 QObject 父对象（通常 QApplication）。

    Returns:
        Optional[UiWatchdog]: 已安装实例；未开启时返回 ``None``。
    """
    global _instance
    if not _truthy_env("FAF_UI_WATCHDOG"):
        return None
    if _instance is not None:
        return _instance
    watchdog = UiWatchdog(app)
    watchdog.start()
    _instance = watchdog
    register_snapshot_provider("ui_watchdog", watchdog.provider)
    return watchdog


def uninstall() -> None:
    """卸载哨兵并从快照 provider 注销（幂等）。"""
    global _instance
    if _instance is None:
        return
    _instance.stop()
    unregister_snapshot_provider("ui_watchdog")
    _instance = None


def get_watchdog() -> Optional[UiWatchdog]:
    """返回当前已安装实例（未安装为 ``None``）。"""
    return _instance


def capture_hint(owner: str, callback_id: str) -> Optional[str]:
    """为其它模块的硬超时提供一条「当前主线程栈」提示（可选）。

    Args:
        owner: 触发方标识（如 ``heartbeat``）。
        callback_id: 回调标识。

    Returns:
        Optional[str]: 最内层 3 帧的可读文本；哨兵未启用或采样失败返回 ``None``。
    """
    if _instance is None:
        return None
    try:
        frame = sys._current_frames().get(threading.main_thread().ident or 0)
        if frame is None:
            return None
        tokens = _instance._make_stack_key(frame)  # noqa: SLF001 - 同模块协作
        tail = [t for t in tokens[-3:] if t[0] != "…"]
        text = " <- ".join(_instance._describe_frame(t) for t in tail)  # noqa: SLF001
        return f"{owner}:{callback_id}: {text}"
    except Exception:  # noqa: BLE001 - 诊断路径不得抛
        return None
