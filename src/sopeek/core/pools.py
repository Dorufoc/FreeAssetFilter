#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""进程级线程预算与命名线程池（P6.2）。

背景
----
``QThreadPool.globalInstance()`` 全仓曾被打到 30+ 处，且 ``setMaxThreadCount``
从未被调用（默认 = 逻辑核数）。长任务（目录流式/导出）会把短任务（预览首帧）
饿死。本模块把后台工作拆成**五个命名池 + 一个批处理执行器**，并用一个
进程级预算把它们与两个 Rust rayon 池一起约束在 32 线程以内。

预算公式（24 核示例）
---------------------
::

    THREAD_CEILING = 32
    RESERVED       = 6      # 2 Qt + 1 MPV + 1 Mica 瞬时 + 2 fd_capture
    shared         = 26
    rayon_per_pool = clamp(2, cpu//8, 4) = 3   # spk_core + thumbnail_rust
    python_total   = 20
    interactive=6 decode=6 io=3 net=3 background=1 → 19 ≤ 20

约束
----
* **禁止**猴子补丁 ``QThreadPool.globalInstance``（C++ 静态方法，PySide6 下
  不生效且会让 Qt 内部行为不可控）。调用方一律改为 ``pools.start(...)``。
* 池一律 ``QThreadPool(parent=None)`` 并在 ``shutdown()`` 中 ``waitForDone``；
  退出链由 ``MainWindow.closeEvent`` / ``aboutToQuit`` 调用。
* 线程命名走 ``SetThreadDescription``（Win10 1607+）；失败静默降级。
"""

from __future__ import annotations

import ctypes
import itertools
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from PySide6.QtCore import QRunnable, QThreadPool

from sopeek.utils.app_logger import debug, warning

#: 进程级线程硬上限（可用 ``SPK_THREAD_BUDGET`` 覆盖，QA/低配机用）。
THREAD_CEILING: int = max(8, int(os.environ.get("SPK_THREAD_BUDGET", "32")))
#: 不被本模块管理的常驻线程预留（Qt 主线程/平台、MPV、Mica 瞬时、fd_capture）。
RESERVED_INPROC: int = 6

_CPU: int = max(1, os.cpu_count() or 1)


def _clamp(low: int, value: int, high: int) -> int:
    """把 ``value`` 夹在 ``[low, high]``。"""
    return max(low, min(int(value), high))


#: 两个 Rust DLL 各自的 rayon 池线程数（与 ``RAYON_NUM_THREADS`` 对齐）。
RAYON_PER_POOL: int = _clamp(2, _CPU // 8, 4)
#: 可供 Python 池分配的线程总数。
PYTHON_TOTAL: int = max(
    6, THREAD_CEILING - RESERVED_INPROC - 2 * RAYON_PER_POOL
)

_INTERACTIVE: int = _clamp(3, _CPU // 4, 6)
_DECODE: int = _clamp(2, _CPU // 4, 6)
_IO: int = _clamp(2, _CPU // 8, 3)
_NET: int = 3
_BACKGROUND: int = 1

#: 池名 → 线程数（构建时再按预算收敛）。
_BUDGETS: Dict[str, int] = {
    "interactive": _INTERACTIVE,
    "decode": _DECODE,
    "io": _IO,
    "net": _NET,
    "background": _BACKGROUND,
}


def _enforce_ceiling() -> None:
    """按 ``decode → interactive → io`` 顺序收敛，直到不超预算。"""
    ordered = ["interactive", "decode", "io", "net", "background"]
    minimums = {"interactive": 2, "decode": 2, "io": 1, "net": 1, "background": 1}
    while sum(_BUDGETS.values()) > PYTHON_TOTAL:
        changed = False
        for name in ordered:
            if _BUDGETS[name] > minimums[name]:
                _BUDGETS[name] -= 1
                changed = True
                if sum(_BUDGETS.values()) <= PYTHON_TOTAL:
                    break
        if not changed:
            warning(
                "[pools] 线程预算无法收敛："
                f"python={sum(_BUDGETS.values())} > {PYTHON_TOTAL}"
            )
            break


_enforce_ceiling()

_POOLS: Dict[str, QThreadPool] = {}
_EXECUTORS: Dict[str, ThreadPoolExecutor] = {}
_LOCK = threading.Lock()
#: 线程命名序号（同一线程 id 稳定同名）。
_THREAD_SEQ = itertools.count(1)
_THREAD_NAMES: Dict[int, str] = {}
_NAMED = threading.local()

_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
try:  # pragma: no cover - 旧系统无此 API
    _SET_THREAD_DESCRIPTION = _KERNEL32.SetThreadDescription
    _SET_THREAD_DESCRIPTION.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    _SET_THREAD_DESCRIPTION.restype = ctypes.c_long
    _GET_CURRENT_THREAD = _KERNEL32.GetCurrentThread
    _GET_CURRENT_THREAD.restype = ctypes.c_void_p
except AttributeError:  # pragma: no cover
    _SET_THREAD_DESCRIPTION = None
    _GET_CURRENT_THREAD = None


def set_thread_description(name: str) -> bool:
    """把当前线程的 OS 名称设为 ``name``（失败静默）。

    Args:
        name: 线程名（建议 ``spk/<pool>/<idx>``）。

    Returns:
        bool: 是否设置成功。
    """
    if _SET_THREAD_DESCRIPTION is None or _GET_CURRENT_THREAD is None:
        return False
    try:
        handle = _GET_CURRENT_THREAD()
        return _SET_THREAD_DESCRIPTION(handle, name) >= 0
    except Exception:  # noqa: BLE001 - 诊断能力不得影响任务
        return False


def _ensure_named(pool_name: str) -> None:
    """为当前工作线程分配稳定名称（每线程一次）。"""
    if getattr(_NAMED, "done", False):
        return
    ident = threading.get_ident()
    with _LOCK:
        name = _THREAD_NAMES.get(ident)
        if name is None:
            name = f"spk/{pool_name}/{next(_THREAD_SEQ):02d}"
            _THREAD_NAMES[ident] = name
    set_thread_description(name)
    _NAMED.done = True


class _NamedRunnable(QRunnable):
    """给内部 runnable 套一层线程命名（不改其语义）。"""

    def __init__(self, inner: QRunnable, pool_name: str) -> None:
        super().__init__()
        self._inner = inner
        self._pool_name = pool_name
        self.setAutoDelete(False)

    def run(self) -> None:  # noqa: D102 - QRunnable 接口
        _ensure_named(self._pool_name)
        self._inner.run()


def pool(name: str = "interactive") -> QThreadPool:
    """获取（惰性创建）命名线程池。

    Args:
        name: 池名（``interactive``/``decode``/``io``/``net``/``background``）。

    Returns:
        QThreadPool: 该池的单例。
    """
    with _LOCK:
        existing = _POOLS.get(name)
        if existing is not None:
            return existing
        created = QThreadPool()
        created.setObjectName(f"spk-{name}")
        created.setMaxThreadCount(_BUDGETS.get(name, 1))
        created.setExpiryTimeout(30_000)
        _POOLS[name] = created
        debug(f"[pools] created {name} max={created.maxThreadCount()}")
        return created


def start(
    runnable: QRunnable,
    *,
    pool_name: str = "interactive",
    priority: int = 0,
) -> None:
    """把 runnable 投递到命名池（替代 ``QThreadPool.globalInstance().start``）。

    Args:
        runnable: 待执行任务。
        pool_name: 目标池名。
        priority: Qt 队列内优先级（越大越先出队；对已运行任务无抢占效果）。
    """
    pool(pool_name).start(_NamedRunnable(runnable, pool_name), priority)


def executor(name: str = "io") -> ThreadPoolExecutor:
    """获取（惰性创建）批处理执行器。

    Args:
        name: 执行器名（用于线程名前缀）。

    Returns:
        ThreadPoolExecutor: 该名字的单例。
    """
    with _LOCK:
        existing = _EXECUTORS.get(name)
        if existing is not None:
            return existing
        workers = max(1, min(_BUDGETS.get(name, 2), PYTHON_TOTAL))
        created = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix=f"spk-{name}"
        )
        _EXECUTORS[name] = created
        return created


def budget(name: str) -> int:
    """返回某个池的线程预算。"""
    return int(_BUDGETS.get(name, 0))


def all_pools() -> List[QThreadPool]:
    """返回已创建的全部池（供退出链排空）。"""
    with _LOCK:
        return list(_POOLS.values())


def shutdown(timeout_ms: int = 2000) -> None:
    """排空并关闭全部池与执行器（幂等）。

    Args:
        timeout_ms: 每个池等待上限（毫秒）。
    """
    with _LOCK:
        pools = list(_POOLS.values())
        executors = list(_EXECUTORS.values())
        _POOLS.clear()
        _EXECUTORS.clear()
        _THREAD_NAMES.clear()
    for item in pools:
        try:
            item.waitForDone(timeout_ms)
        except RuntimeError:
            pass
    for pool_exec in executors:
        try:
            pool_exec.shutdown(wait=True, cancel_futures=True)
        except TypeError:  # pragma: no cover - Python < 3.9
            pool_exec.shutdown(wait=True)
        except Exception:  # noqa: BLE001 - 退出路径不得抛
            pass
    if pools or executors:
        debug(f"[pools] shutdown {len(pools)} pools / {len(executors)} executors")


def reset_for_tests() -> None:
    """重置单例（测试用；会先关闭已有池）。"""
    shutdown(timeout_ms=500)


def snapshot() -> Dict[str, Any]:
    """线程账本快照（供 ``perf_metrics`` provider 使用）。

    ``os_threads`` 暂以 ``threading.active_count()`` 近似（仅 Python 线程）；
    Win32 Toolhelp 全量计数在 P7.1 接入（实测 105ms/次，只能按需采样）。

    Returns:
        dict: 各池上限/活跃数、预算与 Python 线程数。
    """
    with _LOCK:
        pools = {
            name: {
                "max": item.maxThreadCount(),
                "active": item.activeThreadCount(),
                "queued": item.activeThreadCount(),
            }
            for name, item in _POOLS.items()
        }
        executors = sorted(_EXECUTORS.keys())
    return {
        "pools": pools,
        "executors": executors,
        "os_threads_python_only": threading.active_count(),
        "budget": {
            "ceiling": THREAD_CEILING,
            "reserved": RESERVED_INPROC,
            "python_total": PYTHON_TOTAL,
            "rayon_per_pool": RAYON_PER_POOL,
            "allocations": dict(_BUDGETS),
        },
    }
