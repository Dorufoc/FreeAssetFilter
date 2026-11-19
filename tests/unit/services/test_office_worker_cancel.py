# -*- coding: utf-8 -*-
"""Office 转换 worker 取消路径的安全性回归。

背景（真实崩溃）：快速切换 Office 预览时，预览器 ``cleanup()`` 会调用
``worker.request_cancel()``。旧实现在 COM 后端（没有 soffice ``Popen``
句柄）时降级为 ``OfficeConverter._cleanup_orphan_processes`` —— 用
PowerShell ``Stop-Process -Force`` 杀掉「启动时间晚于任务开始且无主窗口」
的 EXCEL/WINWORD 进程。但该转换**仍在进行中**，正在使用那个实例，于是
后续 COM 调用抛 SEH 异常（0x80010108 / 0x800706be / 0x800706ba），
Python 捕获不到 → 进程直接崩溃。

本文件锁定取消路径的安全契约：

* COM 后端（拿不到 soffice Popen）取消时**不得**触发孤儿进程清理；
* LibreOffice 后端（拿得到 Popen）仍必须真实终止子进程；
* 取消标志始终置位，结果被抑制（不发 ``converted``）。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/services/test_office_worker_cancel.py -v
"""

from __future__ import annotations

import threading
from typing import Any, Optional

import pytest

from sopeek.services import office_converter_worker as worker_mod
from sopeek.services.office_converter import OfficeConverter
from sopeek.services.office_converter_worker import OfficeConverterWorker

pytestmark = pytest.mark.unit


class _FakePopen:
    """最小 Popen 替身：记录 terminate / wait / kill 调用。"""

    def __init__(self) -> None:
        self.terminated = 0
        self.killed = 0
        self.waited = 0
        self._alive = True

    def terminate(self) -> None:
        self.terminated += 1

    def wait(self, timeout: Optional[float] = None) -> int:
        self.waited += 1
        self._alive = False
        return 0

    def poll(self) -> Optional[int]:
        return None if self._alive else 0

    def kill(self) -> None:
        self.killed += 1
        self._alive = False


@pytest.fixture()
def worker() -> Any:
    """未启动的 worker（取消路径不需要真的跑线程）。"""
    return OfficeConverterWorker({"path": "x.docx", "suffix": "docx"})


@pytest.fixture()
def no_real_powershell(monkeypatch: pytest.MonkeyPatch) -> dict:
    """记录孤儿清理调用次数，并阻止真实 PowerShell 子进程。"""
    calls: dict = {"sweep": 0}

    def fake_cleanup(task_started_at) -> None:
        calls["sweep"] += 1

    monkeypatch.setattr(
        OfficeConverter,
        "_cleanup_orphan_processes",
        staticmethod(fake_cleanup),
    )
    return calls


def test_cancel_on_com_backend_does_not_sweep_orphans(
    worker: Any,
    monkeypatch: pytest.MonkeyPatch,
    no_real_powershell: dict,
) -> None:
    """COM 后端取消：拿不到 soffice Popen 时绝不能清理孤儿进程。

    否则会杀死当前转换正在使用的 Office 实例，触发 SEH 崩溃。
    """
    monkeypatch.setattr(
        worker_mod,
        "get_active_lo_popen",
        lambda thread_id=None: None,
    )
    monkeypatch.setattr(worker, "_CANCEL_POPEN_WAIT", 0.0)
    worker._thread_ident = threading.get_ident()

    worker._terminate_active_subprocess()

    assert no_real_powershell["sweep"] == 0


def test_cancel_on_libreoffice_backend_kills_popen(
    worker: Any,
    monkeypatch: pytest.MonkeyPatch,
    no_real_powershell: dict,
) -> None:
    """LibreOffice 后端取消：仍必须真实终止自己的 soffice 子进程。"""
    proc = _FakePopen()
    monkeypatch.setattr(
        worker_mod,
        "get_active_lo_popen",
        lambda thread_id=None: proc,
    )
    worker._thread_ident = threading.get_ident()

    worker._terminate_active_subprocess()

    assert proc.terminated == 1
    assert no_real_powershell["sweep"] == 0


def test_request_cancel_sets_flag_without_running_thread(worker: Any) -> None:
    """线程未运行时取消只置标志，不派生终止线程（幂等）。"""
    worker.request_cancel()
    assert worker._cancel_requested is True

    before = threading.active_count()
    worker.request_cancel()
    assert worker._cancel_requested is True
    assert threading.active_count() <= before


def test_request_cancel_stops_watchdog(worker: Any) -> None:
    """取消必须停掉超时看门狗（避免超时误报）。"""
    timer = threading.Timer(60, lambda: None)
    timer.daemon = True
    timer.start()
    worker._watchdog = timer

    worker.request_cancel()

    assert worker._watchdog is None
    assert timer.finished.is_set() or not timer.is_alive()


def test_cancel_suppresses_converted_result(
    worker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已请求取消时，run() 不得发射 converted（只发 failed）。"""
    converted: list = []
    failed: list = []
    worker.converted.connect(converted.append)
    worker.failed.connect(failed.append)
    worker._cancel_requested = True

    monkeypatch.setattr(
        OfficeConverter,
        "convert",
        classmethod(
            lambda cls, info: pytest.fail("取消后不应再调用 convert")
        ),
    )

    worker.run()

    assert converted == []
    assert failed and "取消" in failed[0]


def test_terminate_without_popen_is_safe_when_no_ident(
    worker: Any, monkeypatch: pytest.MonkeyPatch, no_real_powershell: dict
) -> None:
    """线程 ident 为空（尚未进入 run）时取消也安全，不触发清理。"""
    monkeypatch.setattr(
        worker_mod,
        "get_active_lo_popen",
        lambda thread_id=None: None,
    )
    monkeypatch.setattr(worker, "_CANCEL_POPEN_WAIT", 0.0)
    worker._thread_ident = None

    worker._terminate_active_subprocess()

    assert no_real_powershell["sweep"] == 0
