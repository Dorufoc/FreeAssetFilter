# -*- coding: utf-8 -*-
"""``MD5CalculationTask``（core/workers/staging_tasks.py）单元测试。

覆盖（happy + boundary/error 各至少一条）：

* 正常文件 —— 计算结果与 ``hashlib.md5`` 一致；回调携带 hex 值
* 空文件 —— MD5 of empty = ``d41d8...``
* 文件缺失 —— ``FileNotFoundError`` → 回调 ``None``
* IO/OSError —— ``PermissionError`` 等 → 回调 ``None``
* 跨线程契约 —— QRunnable 在后台线程计算，回调经 ``HeartbeatManager``
  ``request_main_thread`` 回到**主线程**执行（记录线程 id 断言）

设计要点：

* 主线程回调断言：用 conftest ``heartbeat_manager`` fixture（真实启动
  心跳），``QThreadPool`` 跑 QRunnable，再以 ``process_qt_events`` 泵
  事件直至回调落地，校验 ``threading.get_ident()`` == 主线程 id。全程
  有界等待（2s 上限），绝不无限等待。
* 简单场景为避免心跳时序依赖，monkeypatch ``HeartbeatManager`` 单例的
  ``request_main_thread`` 为直接执行回调的替身（行为等价但即时）。
"""
from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from typing import Any, Callable, List, Optional

import pytest
from PySide6.QtCore import QThreadPool

from freeassetfilter.core.managers.heartbeat_manager import HeartbeatManager
from freeassetfilter.core.workers.staging_tasks import MD5CalculationTask
from tests.support.qt_helpers import process_qt_events

pytestmark = pytest.mark.unit

#: 空文件的标准 MD5（RFC 1321 常数）。
EMPTY_MD5: str = "d41d8cd98f00b204e9800998ecf8427e"


def _expected_md5(content: bytes) -> str:
    """计算期望的 MD5 hex 串。

    Args:
        content: 文件字节内容。

    Returns:
        str: 十六进制摘要。
    """
    return hashlib.md5(content).hexdigest()


def _patch_heartbeat_sync(monkeypatch) -> None:
    """把 HeartbeatManager.request_main_thread 替换为立即执行回调。

    Args:
        monkeypatch: pytest monkeypatch fixture。
    """
    def _immediate(self: HeartbeatManager, fn: Any, priority: int = 5) -> Any:
        """替身：在调用线程直接执行回调（跳过真实心跳排队）。"""
        del priority
        fn()
        return None

    monkeypatch.setattr(HeartbeatManager, "request_main_thread", _immediate)


def _wait_until(
    condition_fn: Callable[[], bool],
    qapp: Any,
    timeout_ms: int = 2000,
) -> bool:
    """有界等待 condition 为真（泵 Qt 事件）。

    Args:
        condition_fn: 返回 bool 的条件函数。
        qapp: QApplication 实例（用于泵事件）。
        timeout_ms: 最大等待毫秒数。

    Returns:
        bool: 超时前条件满足返回 True，否则 False。
    """
    deadline: float = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        process_qt_events(qapp, 10)
        if condition_fn():
            return True
    return False


def test_md5_normal_file(monkeypatch, tmp_path: Path) -> None:
    """happy：正常文件 MD5 与 hashlib 一致，回调携带 hex 值。

    Args:
        monkeypatch: pytest monkeypatch fixture。
        tmp_path: 临时目录。
    """
    content: bytes = b"FreeAssetFilter staging md5 payload"
    target: Path = tmp_path / "data.bin"
    target.write_bytes(content)

    results: List[Optional[str]] = []
    _patch_heartbeat_sync(monkeypatch)

    task: MD5CalculationTask = MD5CalculationTask(
        str(target), lambda result: results.append(result)
    )
    task.run()
    assert results == [_expected_md5(content)]


def test_md5_empty_file(monkeypatch, tmp_path: Path) -> None:
    """boundary：空文件返回标准 EMPTY_MD5。

    Args:
        monkeypatch: pytest monkeypatch fixture。
        tmp_path: 临时目录。
    """
    target: Path = tmp_path / "empty.bin"
    target.write_bytes(b"")

    results: List[Optional[str]] = []
    _patch_heartbeat_sync(monkeypatch)

    task: MD5CalculationTask = MD5CalculationTask(
        str(target), lambda result: results.append(result)
    )
    task.run()
    assert results == [EMPTY_MD5]


def test_md5_missing_file(monkeypatch, tmp_path: Path) -> None:
    """error：文件缺失时回调 None（FileNotFoundError 分支）。

    Args:
        monkeypatch: pytest monkeypatch fixture。
        tmp_path: 临时目录。
    """
    missing: str = str(tmp_path / "missing.bin")
    results: List[Optional[str]] = []
    _patch_heartbeat_sync(monkeypatch)

    task: MD5CalculationTask = MD5CalculationTask(
        missing, lambda result: results.append(result)
    )
    task.run()
    assert results == [None]


def test_md5_io_error_path(monkeypatch, tmp_path: Path) -> None:
    """error：IO/OSError（不可读路径）时回调 None。

    test_manual: 传入一个**目录**路径触发 ``open()`` 的 OSError 分支，
    无需真实权限设置即可稳定复现。
    """
    results: List[Optional[str]] = []
    _patch_heartbeat_sync(monkeypatch)

    # 目录不可按 rb 打开，Python 抛 IsADirectoryError/PermissionError
    task: MD5CalculationTask = MD5CalculationTask(
        str(tmp_path), lambda result: results.append(result)
    )
    task.run()
    assert results == [None]


def test_md5_callback_on_main_thread(qapp: Any, heartbeat_manager: HeartbeatManager, tmp_path: Path) -> None:
    """happy（跨线程）：QRunnable 后台计算，回调回归主线程执行。

    test_manual: 真实启动心跳（heartbeat_manager fixture），QThreadPool
    执行 QRunnable；回调记录 ``threading.get_ident()``，断言与主线程 id
    一致。数据库建立后 stop_all，teardown 无线程泄漏。
    """
    content: bytes = b"main thread dispatch payload"
    target: Path = tmp_path / "dispatch.bin"
    target.write_bytes(content)

    main_thread_id: int = threading.get_ident()
    results: List[Optional[str]] = []
    thread_ids: List[int] = []

    task: MD5CalculationTask = MD5CalculationTask(
        str(target),
        lambda result: (results.append(result), thread_ids.append(threading.get_ident())),
    )

    pool: QThreadPool = QThreadPool.globalInstance()
    pool.start(task)  # 后台线程执行 run()

    # 心跳 tick 会把 request_main_thread 的回调调度到主线程；泵事件等待
    assert _wait_until(lambda: bool(results), qapp, timeout_ms=2000), "回调未在心跳周期内落地"
    assert results == [_expected_md5(content)]
    assert thread_ids == [main_thread_id]

    # 线程纪律：等待线程池排空，避免遗留任务污染后续测试
    pool.waitForDone(2000)  # type: ignore[attr-defined]
    # heartbeat_manager fixture teardown 已 stop_all，此处不再重复