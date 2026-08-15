#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OfficeConverterWorker（T9）单元测试

通过注入「阻塞假 soffice」（真实 ``sys.executable -c "time.sleep(...)"`` 子进程，
镜像 T5 的 ``test_office_libreoffice_backend.py`` 模式）验证 worker 的取消 /
超时对**子进程真实有效**（Metis B3 —— 拒绝 ImageDecodeWorker 的 flag-only 取消）：

- 成功路径：假 soffice 写出 PDF → ``converted`` 发射**缓存驻留**的 PDF
  路径字符串（```convert()`` 在 LO/COM 后端成功后调用 ``put_cache``，返回
  缓存内路径；测试把缓存目录重定向到 ``tmp_path`` 下避免污染真实缓存）
- 降级内容：``converted`` 发射 ``{content_type}:{content}`` 标记字符串
- 取消路径：``request_cancel()`` 后 ≤3s ``isRunning()`` 为 False **且** soffice
  子进程已死（``created[0].poll() is not None``）；发射 ``failed`` 且含「取消」，
  且**不**发射 ``converted``（过期结果被抑制）
- 超时路径：worker 级 ``timeout`` 触发 → ``failed`` 消息含「超时」（Metis E3），
  子进程被 kill
- 双启动守卫：已运行再 ``start()`` 被忽略（转换只执行一次）
- COM best-effort 取消：无 LO Popen 时走 ``_cleanup_orphan_processes`` 僵尸清理
- 生命周期：先 ``request_cancel()`` + ``wait()`` 再 ``deleteLater()`` 不崩溃；
  ``wait(timeout)`` 返回布尔；``cleanup()`` 安全

所有测试无真实 GUI 依赖（QSignalSpy 走 Qt 事件循环，qapp 会话 fixture 提供）。
"""

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from freeassetfilter.services import office_cache
from freeassetfilter.services import office_converter as conv
from freeassetfilter.services.office_converter import (
    ConversionResult,
    OfficeConverter,
)
from freeassetfilter.services.office_converter_worker import OfficeConverterWorker

_PDF_BYTES = b"%PDF-1.4 fake\n"


@pytest.fixture(autouse=True)
def _qapp_session(qapp):
    """确保本模块测试拥有 QApplication（QSignalSpy.wait 需要事件循环投递信号）。"""
    yield qapp


# ===========================================================================
# 工具：安装阻塞 / 成功假 soffice + 强制 LO 分派（本机无 LibreOffice）
# ===========================================================================


def _install_fake_soffice(
    monkeypatch,
    behavior: str = "block",
    block_seconds: float = 60.0,
    created: list | None = None,
) -> list:
    """把模块内 ``subprocess.Popen`` 替换为真实子进程假 soffice。

    - ``behavior="block"``：子进程 ``time.sleep(block_seconds)``（用于取消/超时）。
    - ``behavior="success"``：子进程把 PDF 写入 ``--outdir/<stem>.pdf``。

    同时强制 ``_soffice_available()`` 为真、``_com_available()`` 为假，
    保证 ``convert()`` 分派到 LibreOffice 后端。
    """
    real_popen = subprocess.Popen
    created = created if created is not None else []

    def _fake_popen(*args, **kwargs):
        argv = [str(a) for a in (list(args[0]) if args and args[0] else [])]
        out_dir = None
        src_path = None
        idx = 0
        while idx < len(argv):
            if argv[idx] == "--outdir" and idx + 1 < len(argv):
                out_dir = argv[idx + 1]
                idx += 2
                continue
            if argv[idx].lower().endswith((".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt")):
                src_path = argv[idx]
            idx += 1

        if behavior == "block":
            code = f"import time; time.sleep({block_seconds})"
        elif out_dir and src_path:
            expected = Path(out_dir) / f"{Path(src_path).stem}.pdf"
            code = (
                "import pathlib; "
                f"pathlib.Path({expected.as_posix()!r}).write_bytes({_PDF_BYTES!r})"
            )
        else:
            code = "pass"

        popen = real_popen(
            [sys.executable, "-c", code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        created.append(popen)
        return popen

    monkeypatch.setattr(conv.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(conv, "_resolve_soffice_binary", lambda: Path(sys.executable))
    monkeypatch.setattr(OfficeConverter, "_soffice_available", lambda: True)
    monkeypatch.setattr(OfficeConverter, "_com_available", lambda: False)
    return created


def _make_source(tmp_path: Path, name: str = "sample.docx") -> Path:
    """创建假源 Office 文件（内容无关紧要）。"""
    src = tmp_path / name
    src.write_bytes(b"fake office bytes")
    return src


def _wait_until_lo_popen_registered(worker: OfficeConverterWorker, timeout: float = 3.0) -> None:
    """轮询直到 worker 线程的 soffice Popen 已注册到 T5 取消 seam。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        thread_id = worker._thread_ident
        if thread_id is not None and conv.get_active_lo_popen(thread_id) is not None:
            return
        time.sleep(0.01)
    raise AssertionError("soffice Popen 未在预期时间内注册到取消 seam")


def _wait_for_spy(spy: QSignalSpy, timeout_ms: int) -> bool:
    """Semantic equivalent of ``QSignalSpy.wait(timeout_ms)`` for this environment.

    ``QSignalSpy.wait()`` relies on ``QTestEventLoop::enterLoop`` spinning the Qt
    event loop; in PySide6 6.11.1 here it does NOT pump queued cross-thread signals,
    so it returns ``False`` even when a signal is genuinely delivered (verified: a
    manual ``processEvents()`` polling loop captures it). This helper reproduces the
    same waiting window / meaning by repeatedly pumping ``processEvents()`` until the
    spy received at least one emission or the deadline elapses.

    Parameters
    ----------
    spy : QSignalSpy
        The signal spy to poll.
    timeout_ms : int
        Maximum wait window in milliseconds (mirrors the removed ``wait(N)``).

    Returns
    -------
    bool
        ``True`` if the spy captured at least one emission within the window.
    """
    app = QApplication.instance()
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if spy.count() > 0:
            return True
        if app is not None:
            app.processEvents()
        time.sleep(0.005)
    return spy.count() > 0


# ===========================================================================
# 成功路径
# ===========================================================================


class TestSuccess:
    """假 soffice 成功写出 PDF → ``converted`` 发射 PDF 路径字符串。"""

    def test_lo_success_emits_converted_pdf_path(self, monkeypatch, tmp_path):
        src = _make_source(tmp_path, "sample.docx")
        # 缓存目录重定向到 tmp_path 下，避免测试写入真实 data/office_cache/。
        cache_dir = tmp_path / "office_cache"
        monkeypatch.setattr(office_cache, "office_cache_dir", lambda: cache_dir)
        _install_fake_soffice(monkeypatch, behavior="success")
        worker = OfficeConverterWorker({"path": str(src), "suffix": "docx"})
        converted_spy = QSignalSpy(worker.converted)
        failed_spy = QSignalSpy(worker.failed)
        try:
            worker.start()
            assert _wait_for_spy(converted_spy, 5000), "converted 信号未在 5s 内发射"
            assert worker.wait(3000)
            assert failed_spy.count() == 0
            payload = converted_spy.at(0)[0]
            assert isinstance(payload, str)
            # ``convert()`` 成功后 ``put_cache`` 把产物 PDF 拷入缓存并返回
            # 缓存驻留路径 —— 断言它是真实存在的、位于重定向缓存目录内的 PDF。
            assert Path(payload).is_file()
            assert Path(payload).suffix == ".pdf"
            assert Path(payload).parent == cache_dir
            assert not worker.is_running()
        finally:
            worker.cleanup()

    def test_degraded_content_emits_marker(self, monkeypatch):
        """纯 Python 降级内容 → ``converted`` 发射 ``html:...`` 标记。"""

        def _fake_convert(file_info):
            return ConversionResult(
                content_type="html",
                content="<p>hello</p>",
                backend_used="pure-python",
            )

        monkeypatch.setattr(OfficeConverter, "convert", _fake_convert)
        worker = OfficeConverterWorker({"path": "x.docx", "suffix": "docx"})
        converted_spy = QSignalSpy(worker.converted)
        failed_spy = QSignalSpy(worker.failed)
        try:
            worker.start()
            assert _wait_for_spy(converted_spy, 5000)
            assert worker.wait(3000)
            assert converted_spy.at(0)[0] == "html:<p>hello</p>"
            assert failed_spy.count() == 0
        finally:
            worker.cleanup()

    def test_error_result_emits_failed(self, monkeypatch):
        """``content_type="error"`` 的结果 → ``failed`` 发射结果消息。"""

        def _fake_convert(file_info):
            return ConversionResult(
                content_type="error",
                content="",
                backend_used="error",
                message="COM 转换失败：源文件不存在",
            )

        monkeypatch.setattr(OfficeConverter, "convert", _fake_convert)
        worker = OfficeConverterWorker({"path": "x.docx", "suffix": "docx"})
        failed_spy = QSignalSpy(worker.failed)
        converted_spy = QSignalSpy(worker.converted)
        try:
            worker.start()
            assert _wait_for_spy(failed_spy, 5000)
            assert worker.wait(3000)
            assert "源文件不存在" in failed_spy.at(0)[0]
            assert converted_spy.count() == 0
        finally:
            worker.cleanup()


# ===========================================================================
# 取消路径：真实杀死阻塞 soffice 子进程（Metis B3 验收）
# ===========================================================================


class TestCancel:
    """``request_cancel()`` 必须让 soffice 子进程真实死亡并快速停止 worker。"""

    def test_cancel_kills_blocking_soffice_child(self, monkeypatch, tmp_path):
        src = _make_source(tmp_path, "blocked.docx")
        created = _install_fake_soffice(monkeypatch, behavior="block")
        worker = OfficeConverterWorker({"path": str(src), "suffix": "docx"})
        failed_spy = QSignalSpy(worker.failed)
        converted_spy = QSignalSpy(worker.converted)
        try:
            worker.start()
            _wait_until_lo_popen_registered(worker)
            assert worker.is_running()
            assert len(created) == 1

            started = time.monotonic()
            worker.request_cancel()
            assert worker.wait(3000), "取消后 worker 未在 3s 内停止"

            elapsed = time.monotonic() - started
            assert elapsed <= 3.0, f"取消耗时 {elapsed:.2f}s 超过 3s"
            # soffice 子进程必须已死（T5 同款断言）。
            assert created[0].poll() is not None
            # 取消必须抑制过期结果：failed(取消) 而不是 converted。
            assert converted_spy.count() == 0
            assert _wait_for_spy(failed_spy, 1000)
            assert "取消" in failed_spy.at(0)[0]
            assert conv.get_active_lo_popen(worker._thread_ident or 0) is None
        finally:
            worker.cleanup()

    def test_cancel_before_start_emits_failed(self, monkeypatch):
        """``start()`` 前取消 → 快速失败路径，发射 failed(已取消)。"""

        def _fake_convert(file_info):
            time.sleep(5)
            return ConversionResult(
                content_type="html", content="late", backend_used="pure-python"
            )

        monkeypatch.setattr(OfficeConverter, "convert", _fake_convert)
        worker = OfficeConverterWorker({"path": "x.docx", "suffix": "docx"})
        failed_spy = QSignalSpy(worker.failed)
        try:
            worker.request_cancel()
            worker.start()
            assert _wait_for_spy(failed_spy, 2000)
            assert worker.wait(2000)
            assert "取消" in failed_spy.at(0)[0]
        finally:
            worker.cleanup()

    def test_com_cancel_runs_orphan_sweep(self, monkeypatch):
        """无 LO Popen（如 COM 后端）时取消 → best-effort 孤儿进程清理被调用。"""
        blocked = threading.Event()
        sweeps = {"n": 0}

        def _fake_convert(file_info):
            blocked.wait(10)
            return ConversionResult(
                content_type="pdf", content="", backend_used="com"
            )

        def _fake_sweep(task_started_at):
            sweeps["n"] += 1

        monkeypatch.setattr(OfficeConverter, "convert", _fake_convert)
        monkeypatch.setattr(OfficeConverter, "_cleanup_orphan_processes", _fake_sweep)
        worker = OfficeConverterWorker({"path": "x.docx", "suffix": "docx"})
        failed_spy = QSignalSpy(worker.failed)
        try:
            worker.start()
            time.sleep(0.2)  # 等 convert 进入阻塞
            assert worker.is_running()
            worker.request_cancel()
            assert sweeps["n"] == 1, "取消时应执行孤儿进程 sweep"
        finally:
            blocked.set()
            worker.wait(3000)
            worker.cleanup()
            assert failed_spy.count() > 0


# ===========================================================================
# 超时路径：worker 级 timeout 触发（Metis E3：消息含「超时」）
# ===========================================================================


class TestTimeout:
    """短 ``timeout`` 参数 → worker 看门狗终止子进程并发射含「超时」的 failed。"""

    def test_timeout_emits_failed_with_timeout_marker(self, monkeypatch, tmp_path):
        src = _make_source(tmp_path, "blocked.docx")
        created = _install_fake_soffice(monkeypatch, behavior="block")
        worker = OfficeConverterWorker({"path": str(src), "suffix": "docx"}, timeout=0.5)
        failed_spy = QSignalSpy(worker.failed)
        converted_spy = QSignalSpy(worker.converted)
        try:
            worker.start()
            assert _wait_for_spy(failed_spy, 5000), "超时路径未在 5s 内发射 failed"
            assert worker.wait(3000)
            assert "超时" in failed_spy.at(0)[0]
            # 看门狗 kill 了阻塞子进程 → 子进程必须已死。
            assert created[0].poll() is not None
            assert converted_spy.count() == 0
            assert conv.get_active_lo_popen(worker._thread_ident or 0) is None
        finally:
            worker.cleanup()

    def test_default_timeout_inherits_soffice_constant(self):
        """默认超时语义继承 ``SOFFICE_CONVERSION_TIMEOUT``（30 秒）。"""
        assert conv.SOFFICE_CONVERSION_TIMEOUT == 30.0
        worker = OfficeConverterWorker({"path": "x.docx", "suffix": "docx"})
        try:
            assert worker._timeout is None  # None = 依赖后端自身超时（30s）
        finally:
            worker.cleanup()


# ===========================================================================
# 线程生命周期守卫
# ===========================================================================


class TestLifecycle:
    """双启动守卫、wait(timeout)、先 cancel+wait 再 deleteLater 不崩溃。"""

    def test_double_start_is_ignored(self, monkeypatch):
        blocked = threading.Event()
        calls = {"n": 0}

        def _fake_convert(file_info):
            calls["n"] += 1
            blocked.wait(10)
            return ConversionResult(
                content_type="html", content="ok", backend_used="pure-python"
            )

        monkeypatch.setattr(OfficeConverter, "convert", _fake_convert)
        worker = OfficeConverterWorker({"path": "x.docx", "suffix": "docx"})
        try:
            worker.start()
            worker.start()  # 已运行 → 必须被忽略
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and calls["n"] == 0:
                time.sleep(0.01)
            assert calls["n"] == 1, "第二次 start() 不应触发第二次转换"
            assert worker.is_running()
        finally:
            blocked.set()
            worker.wait(3000)
            worker.cleanup()

    def test_wait_with_timeout_returns_bool(self, monkeypatch):
        blocked = threading.Event()

        def _fake_convert(file_info):
            blocked.wait(10)
            return ConversionResult(
                content_type="html", content="ok", backend_used="pure-python"
            )

        monkeypatch.setattr(OfficeConverter, "convert", _fake_convert)
        worker = OfficeConverterWorker({"path": "x.docx", "suffix": "docx"})
        try:
            worker.start()
            assert worker.is_running()
            assert worker.wait(100) is False  # 仍阻塞 → 超时返回 False
        finally:
            blocked.set()
            assert worker.wait(3000) is True  # 释放后线程结束 → 返回 True
            worker.cleanup()

    def test_cleanup_cancel_wait_delete_later_no_crash(self, monkeypatch, tmp_path):
        src = _make_source(tmp_path, "blocked.docx")
        created = _install_fake_soffice(monkeypatch, behavior="block")
        worker = OfficeConverterWorker({"path": str(src), "suffix": "docx"})
        worker.start()
        _wait_until_lo_popen_registered(worker)
        # QA 场景：预览关闭瞬间先 cancel+wait 再 deleteLater，不得崩溃。
        worker.cleanup()
        assert worker.isFinished()
        assert created[0].poll() is not None
