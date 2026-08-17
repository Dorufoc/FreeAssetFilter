# -*- coding: utf-8 -*-
# targets: core.managers.heartbeat_manager, core.managers.settings_manager
"""跨模块并发安全集成测试（todo-25 integration 批 2 / test_thread_safety）。

验证多个单例管理器在真实并发压力下的线程安全契约：

* ``SettingsManager``：50 个普通线程经 ``threading.Barrier`` 同步后并发
  ``set_setting``/``get_setting``——不同 key 各自完整、同一 key 最终值必为
  某次写入值之一，全程零异常；
* ``HeartbeatManager``：50 线程并发 ``register_tick_callback`` +
  ``unregister_tick_callback``，无死锁、无重复 id 冲突异常；
* ``QRunnable`` 生命周期（执行 / 取消 / 清理）：以产品
  ``utils/async_icon_loader.py`` 的 ``_IconLoadRunnable`` 取消+AutoDelete
  模式为蓝本，在专用 ``QThreadPool`` 上走通 execute / cancel / cleanup。

资源纪律：

* 每个线程 join 均通过自定义 ``_join_thread`` 包装（默认 5s 超时），任何
  死锁都转化为 AssertionError 快速失败，绝不无限等待；
* 整个文件总时长须 <10s（验收 QA 口径）；
* 全部单例状态交给 conftest autouse ``reset_singletons`` 处理，测试内只做
  必要的显式 stop 与线程回收。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from tests.support.qt_helpers import process_qt_events


pytestmark = pytest.mark.integration


# =============================================================================
# 工具
# =============================================================================
def _join_thread(thread: threading.Thread, timeout: float = 5.0) -> None:
    """带硬超时的线程 join；超时未退出即判死锁（快速失败）。

    Args:
        thread: 待回收的线程。
        timeout: join 上限秒数。
    """
    thread.join(timeout=timeout)
    assert not thread.is_alive(), (
        f"线程 {thread.name} 在 {timeout}s 内未退出（疑似死锁）"
    )


def _run_concurrently(
    num_workers: int,
    target: Callable[[int], None],
    join_timeout: float = 5.0,
    barrier_timeout: float = 5.0,
) -> Tuple[List[int], List[Tuple[int, str]]]:
    """启动 num_workers 个 daemon 线程经 Barrier 同步后并发跑 target。

    Args:
        num_workers: 并发线程数。
        target: 每线程工作函数（参数为 0..num_workers-1）。
        join_timeout: 每线程 join 超时秒数。
        barrier_timeout: Barrier 等待超时秒数。

    Returns:
        tuple[list[int], list[(int, str)]]: (成功序号列表, 失败(序号, 原因))。
    """
    barrier: threading.Barrier = threading.Barrier(num_workers)
    results: List[int] = []
    errors: List[Tuple[int, str]] = []
    lock: threading.Lock = threading.Lock()
    threads: List[threading.Thread] = []

    def _wrapped(idx: int) -> None:
        try:
            barrier.wait(timeout=barrier_timeout)
            target(idx)
            with lock:
                results.append(idx)
        except Exception as exc:  # noqa: BLE001 - 并发测试需收集全部失败
            with lock:
                errors.append((idx, repr(exc)))

    for i in range(num_workers):
        t = threading.Thread(
            target=_wrapped, args=(i,), name=f"faf_concurrent_{i}", daemon=True
        )
        t.start()
        threads.append(t)

    for t in threads:
        _join_thread(t, timeout=join_timeout)

    return results, errors


# =============================================================================
# SettingsManager 并发读写
# =============================================================================
class TestSettingsManagerConcurrency:
    """SettingsManager 并发 set/get 的键隔离与最终一致性。"""

    def test_disjoint_keys_all_intact(
        self, tmp_path: Any, qapp: Any
    ) -> None:
        """50 线程各写各的 key，join 后每个 key 都保有各自写入值。"""
        from freeassetfilter.core.managers.settings_manager import SettingsManager

        start: float = time.monotonic()

        SettingsManager._instance = None  # noqa: SLF001
        SettingsManager._initialized = False  # noqa: SLF001
        manager = SettingsManager(settings_file=str(tmp_path / "thr_safe.json"))

        def _worker(idx: int) -> None:
            key: str = f"thread_key_{idx}"
            # 每轮写入不同值：set_setting 对"值未变化"返回 False（幂等 no-op），
            # 只有值变化才返回 True——因此不能连写相同值。
            for round_idx in range(5):
                value: str = f"value_{idx}_r{round_idx}"
                assert manager.set_setting(key, value, auto_save=False) is True
                assert manager.get_setting(key) == value

        results, errors = _run_concurrently(50, _worker)
        assert errors == [], f"并发写入出现异常: {errors}"
        assert len(results) == 50

        for idx in range(50):
            assert manager.get_setting(f"thread_key_{idx}") == f"value_{idx}_r4"

        elapsed: float = time.monotonic() - start
        assert elapsed < 10.0, f"并发 test 超过 10s 预算: {elapsed:.2f}s"
        process_qt_events(qapp, ms=0)

    def test_same_key_final_value_is_one_of_written(
        self, tmp_path: Any, qapp: Any
    ) -> None:
        """50 线程写同一 key，最终值必属于写入值集合（最后写入者胜）。"""
        from freeassetfilter.core.managers.settings_manager import SettingsManager

        SettingsManager._instance = None  # noqa: SLF001
        SettingsManager._initialized = False  # noqa: SLF001
        manager = SettingsManager(settings_file=str(tmp_path / "thr_race.json"))
        written: set[str] = {f"race_{i}" for i in range(50)}

        def _worker(idx: int) -> None:
            manager.set_setting("contended_key", f"race_{idx}", auto_save=False)

        results, errors = _run_concurrently(50, _worker)
        assert errors == [], f"并发写入同一 key 出现异常: {errors}"
        assert len(results) == 50

        final: Optional[Any] = manager.get_setting("contended_key")
        assert final in written, f"最终值 {final!r} 不属于写入值集合"
        process_qt_events(qapp, ms=0)


# =============================================================================
# HeartbeatManager 并发注册/注销
# =============================================================================
class TestHeartbeatManagerConcurrency:
    """HeartbeatManager 并发 register/unregister 无死锁、无冲突。"""

    def test_concurrent_register_unregister(self, qapp: Any) -> None:
        """50 线程各注册唯一 id 再注销；全部成功、零异常。"""
        from freeassetfilter.core.managers.heartbeat_manager import HeartbeatManager

        HeartbeatManager._instance = None  # noqa: SLF001
        HeartbeatManager._initialized = False  # noqa: SLF001
        hm = HeartbeatManager()

        def _worker(idx: int) -> None:
            callback_id: str = f"hb_thread_{idx}"
            cid: str = hm.register_tick_callback(
                callback_id, lambda: None, priority=4, owner=None
            )
            assert cid == callback_id
            hm.unregister_tick_callback(callback_id)

        results, errors = _run_concurrently(50, _worker)
        hm.stop_all()
        HeartbeatManager._instance = None  # noqa: SLF001
        HeartbeatManager._initialized = False  # noqa: SLF001

        assert errors == [], f"并发注册/注销异常: {errors}"
        assert len(results) == 50
        process_qt_events(qapp, ms=0)

    def test_duplicate_id_raises_valueerror_concurrently(self, qapp: Any) -> None:
        """并发注册同一 id：恰好一次成功，其余全部 ValueError 且不挂死。"""
        from freeassetfilter.core.managers.heartbeat_manager import HeartbeatManager

        HeartbeatManager._instance = None  # noqa: SLF001
        HeartbeatManager._initialized = False  # noqa: SLF001
        hm = HeartbeatManager()
        successes: List[int] = []
        value_errors: List[int] = []
        lock: threading.Lock = threading.Lock()

        def _worker(idx: int) -> None:
            try:
                hm.register_tick_callback("dup_id", lambda: None, owner=None)
                with lock:
                    successes.append(idx)
            except ValueError:
                with lock:
                    value_errors.append(idx)

        results, errors = _run_concurrently(20, _worker)
        hm.unregister_tick_callback("dup_id")
        hm.stop_all()
        HeartbeatManager._instance = None  # noqa: SLF001
        HeartbeatManager._initialized = False  # noqa: SLF001

        assert errors == []
        assert len(successes) == 1, f"同一 id 应恰好一次注册成功: {successes}"
        assert len(value_errors) == 19
        process_qt_events(qapp, ms=0)


# =============================================================================
# QRunnable 生命周期
# =============================================================================
class _RunnableSignals(QObject):
    """携带完成信号的 QRunnable 辅助对象（镜像 async_icon_loader 模式）。"""

    finished = Signal()


class _TestRunnable(QRunnable):
    """可取消的测试 QRunnable：run 内检查取消标志后执行或短路。

    Args:
        label: 任务名（用于断言追踪）。
    """

    def __init__(self, label: str) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.label: str = label
        self._cancelled: threading.Event = threading.Event()
        self.ran: bool = False
        self.signals: _RunnableSignals = _RunnableSignals()

    def run(self) -> None:
        """AutoDelete 工作体：被取消则短路，否则置 ran 并发射完成信号。"""
        if self._cancelled.is_set():
            return
        self.ran = True
        self.signals.finished.emit()

    def cancel(self) -> None:
        """请求取消（提交前调用即保证 run 不执行）。"""
        self._cancelled.set()


class TestQRunnableLifecycle:
    """QRunnable 的执行 / 取消 / 清理三条路径。"""

    def test_execute_runs_and_emits_finished(self, qapp: Any) -> None:
        """正常提交：run 执行、工作标志置位、完成信号被发射。"""
        pool: QThreadPool = QThreadPool()
        pool.setMaxThreadCount(2)
        runnable: _TestRunnable = _TestRunnable(label="execute")
        emitted: List[bool] = []

        def _on_finished() -> None:
            emitted.append(True)

        runnable.signals.finished.connect(_on_finished)
        pool.start(runnable)
        assert pool.waitForDone(5000) is True, "waitForDone 5s 内未完成"
        process_qt_events(qapp, ms=30)
        pool.clear()

        assert runnable.ran is True, "QRunnable 应已被执行"
        assert emitted == [True], f"完成信号应恰好发射一次: {emitted}"

    def test_cancel_before_run_short_circuits(self, qapp: Any) -> None:
        """提交前 cancel：run 被短路，不置 ran 也不发射完成信号。"""
        pool: QThreadPool = QThreadPool()
        pool.setMaxThreadCount(2)
        runnable: _TestRunnable = _TestRunnable(label="cancel")
        emitted: List[bool] = []

        def _on_finished() -> None:
            emitted.append(True)

        runnable.signals.finished.connect(_on_finished)
        runnable.cancel()
        pool.start(runnable)
        assert pool.waitForDone(5000) is True, "waitForDone 5s 内未完成"
        process_qt_events(qapp, ms=30)
        pool.clear()

        assert runnable.ran is False, "被取消的 QRunnable 不应执行 run 工作体"
        assert emitted == [], f"被取消任务不应发射完成信号: {emitted}"

    def test_pool_clear_no_task_leak(self, qapp: Any) -> None:
        """连续提交多批后 clear 排空，无遗留未完成任务（无泄漏等待）。"""
        pool: QThreadPool = QThreadPool()
        pool.setMaxThreadCount(4)
        runnables: List[_TestRunnable] = []
        for i in range(12):
            r: _TestRunnable = _TestRunnable(label=f"leak_{i}")
            runnables.append(r)
            pool.start(r)
        assert pool.waitForDone(5000) is True, "waitForDone 5s 内未完成"
        process_qt_events(qapp, ms=30)
        pool.clear()

        assert all(r.ran for r in runnables), "全部 12 个任务都应被执行"
        assert pool.activeThreadCount() == 0, "clear 后不应有活动线程"
