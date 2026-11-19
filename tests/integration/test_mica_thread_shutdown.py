# -*- coding: utf-8 -*-
"""Mica 烘焙线程退出回收回归。

背景：``MicaMaterial`` 每次异步烘焙都会新建 ``QThread``，窗口关闭时只
``quit()`` 不等待。若线程仍在 ``gpu_bake`` 里，而 Python 侧包装先被回收，
Qt 会 ``qFatal("QThread: Destroyed while thread is still running")`` →
``abort()``，Windows 退出码 ``0xC0000409``（单跑
``tests/integration/test_shortcut_integration.py`` 实测退出阶段崩溃）。

修复契约：退场线程由模块级强引用表托管，``shutdown_worker_threads()``
在进程收尾前 join；本文件验证该契约，而不是断言退出码。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/integration/test_mica_thread_shutdown.py -v
"""

from __future__ import annotations

import time
from typing import Any, List

import pytest

from sopeek.ui.mica import material

pytestmark = pytest.mark.integration


def _safe_is_running(thread: Any) -> bool:
    """线程包装可能已失效：判断失败一律视为「不在运行」。"""
    try:
        return bool(thread.isRunning())
    except RuntimeError:
        return False


def _running_retired_threads() -> List[Any]:
    """返回登记表中仍在运行的线程快照。"""
    with material._RETIRED_THREADS_LOCK:
        return [t for t in material._RETIRED_THREADS if _safe_is_running(t)]


def test_shutdown_joins_retired_thread(qapp: Any) -> None:
    """已 quit 但仍在跑的线程会被 join，并移出登记表。"""
    from PySide6.QtCore import QThread

    class _SlowThread(QThread):
        def run(self) -> None:  # noqa: D401 - 线程体
            time.sleep(0.5)

    thread = _SlowThread()
    thread.start()
    qapp.processEvents()
    try:
        assert _safe_is_running(thread) is True
        material._retire_thread(thread)
        with material._RETIRED_THREADS_LOCK:
            assert any(item is thread for item in material._RETIRED_THREADS)

        material.shutdown_worker_threads(5000)

        assert _safe_is_running(thread) is False
        with material._RETIRED_THREADS_LOCK:
            assert all(item is not thread for item in material._RETIRED_THREADS)
    finally:
        thread.wait(5000)
        thread.deleteLater()
        qapp.processEvents()


def test_retire_thread_is_idempotent(qapp: Any) -> None:
    """重复登记同一线程不会重复入表（防 finished 多次触发时重复删除）。"""
    from PySide6.QtCore import QThread

    thread = QThread()
    try:
        material._retire_thread(thread)
        material._retire_thread(thread)
        with material._RETIRED_THREADS_LOCK:
            assert sum(1 for item in material._RETIRED_THREADS if item is thread) == 1
    finally:
        with material._RETIRED_THREADS_LOCK:
            try:
                material._RETIRED_THREADS.remove(thread)
            except ValueError:
                pass
        thread.deleteLater()
        qapp.processEvents()


def test_quick_close_leaves_no_running_bake_thread(qapp: Any) -> None:
    """主窗口快速关闭后，退出 join 不残留运行中的烘焙线程。"""
    from PySide6.QtTest import QTest

    from sopeek.core.shortcuts import reset_dispatcher_for_tests
    from sopeek.ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    QTest.qWait(100)
    qapp.processEvents()

    mica = getattr(win._mica_background, "_mica", None)
    if mica is None:
        win.close()
        win.deleteLater()
        qapp.processEvents()
        reset_dispatcher_for_tests()
        pytest.skip("当前平台未启用 Mica 背景")

    # 主动提交一次异步烘焙，并尽快关窗，让线程在途时走退场路径。
    mica.refresh_async()
    QTest.qWait(50)
    win.close()
    qapp.processEvents()
    win.deleteLater()
    qapp.processEvents()
    reset_dispatcher_for_tests()

    material.shutdown_worker_threads(15000)

    assert _running_retired_threads() == []
