#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

Office 转换异步工作线程
封装 ``OfficeConverter.convert()``（T4）以在后台线程执行转换，避免阻塞 UI
主线程。镜像 ``image_decode_worker.py`` 的「每次任务新建 QThread」结构，但
取消 / 超时对子进程与 COM **真实有效**（Metis B3）：

- LibreOffice 场景：通过 T5 取消 seam（``get_active_lo_popen(thread_id)``）
  拿到活跃 soffice ``Popen`` 并 ``terminate()`` → 短暂宽限 → ``kill()`` →
  ``poll()``，确保子进程死亡后才报告线程结束；
- COM 场景：best-effort —— ``_convert_with_com`` 自身的 ``finally: app.Quit()``
  负责退出，worker 取消时额外复用 ``OfficeConverter._cleanup_orphan_processes``
  做僵尸进程兜底清理；
- 超时：可配置 ``timeout`` 参数（``None`` = 依赖后端自身的
  ``SOFFICE_CONVERSION_TIMEOUT`` 30 秒）。超时后发射 ``failed`` 且消息含
  「超时」（Metis E3）。

信号在 worker 线程发射，Qt AutoConnection 自动排队投递给 GUI 线程。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

from PySide6.QtCore import QThread, Signal

from freeassetfilter.services.office_converter import (
    ConversionResult,
    OfficeConverter,
    SOFFICE_CONVERSION_TIMEOUT,
    get_active_lo_popen,
)
from freeassetfilter.utils.app_logger import warning


class OfficeConverterWorker(QThread):
    """异步 Office 转换工作线程（每次任务新建实例）。

    ​``run()`` 在后台线程调用 :meth:`OfficeConverter.convert`，通过信号返回
    结果。不支持 `flag-only 取消`：``request_cancel()`` 会对活跃的 soffice
    子进程 ``terminate()``/``kill()``，并对 COM 做 best-effort 孤儿清理。

    Usage::

        worker = OfficeConverterWorker({"path": "a.docx", "suffix": "docx"})
        worker.converted.connect(self._on_converted)
        worker.failed.connect(self._on_failed)
        worker.start()
        # worker.request_cancel()   # 随时取消（真实杀死 soffice）
        # worker.cleanup()          # 关闭预览时：cancel + wait + deleteLater

    Signals:
        converted: ``(str)`` —— ``content_type == "pdf"`` 时为 PDF 路径字符串；
            降级内容（html/outline/table）时为 ``"{content_type}:{content}"``
            标记字符串。
        failed: ``(str)`` —— 错误 / 取消 / 超时消息。取消消息含「取消」；超时
            消息必含「超时」（Metis E3）。
    """

    converted = Signal(str)
    failed = Signal(str)

    # 取消时轮询等待 Popen 注册进 T5 seam 的最长时间（秒）。
    _CANCEL_POPEN_WAIT: float = 2.0
    # terminate() 后等待进程退出的宽限期（秒），超期则 kill()。
    _KILL_GRACE: float = 0.5

    def __init__(
        self,
        file_info: dict,
        timeout: float | None = None,
        parent: Any = None,
    ) -> None:
        """初始化工作线程。

        Parameters
        ----------
        file_info : dict
            与 ``OfficeConverter.convert`` 契约一致的文件信息，至少含
            ``"path"`` 与 ``"suffix"``。
        timeout : float | None
            worker 级转换超时秒数；``None`` 表示依赖后端自身的超时
            （``SOFFICE_CONVERSION_TIMEOUT``，LibreOffice 默认 30 秒）。
        parent : QObject or None
            Qt 父对象（可选）。
        """
        super().__init__(parent)
        self._file_info: dict = dict(file_info or {})
        self._timeout: float | None = timeout
        self._cancel_requested: bool = False
        self._timed_out: bool = False
        self._done: bool = False
        self._thread_ident: int | None = None
        self._task_started_at: datetime = datetime.now()
        self._watchdog: threading.Timer | None = None

    # ── 公共 API ─────────────────────────────────────────────────────

    def start(self, priority: QThread.Priority = QThread.InheritPriority) -> None:
        """启动 worker 线程，带双启动守卫。

        线程已在运行时再次调用 ``start()`` 被忽略（仅记录告警），避免重复
        转换。

        Parameters
        ----------
        priority : QThread.Priority
            线程优先级，默认继承调用线程的优先级。
        """
        if self.isRunning():
            warning("[OfficeConverterWorker] start 忽略：worker 已在运行")
            return
        super().start(priority)

    def is_running(self) -> bool:
        """线程是否仍在运行。"""
        return self.isRunning()

    def request_cancel(self, grace: float | None = None) -> None:
        """请求取消当前转换并真实终止活跃子进程。

        幂等：已取消时直接返回。若 LibreOffice 转换正在进行，通过 T5 seam
        拿到线程注册的 ``Popen`` 并 ``terminate()`` → 宽限 *grace* 秒 → 仍
        存活则 ``kill()`` → ``wait()``，确保子进程死亡；若未发现 LO 子进程
        （如 COM 后端 / 尚未启动），则做 best-effort 孤儿进程清理。

        Parameters
        ----------
        grace : float | None
            terminate() 后的宽限秒数；``None`` 使用 ``_KILL_GRACE``（0.5s）。
        """
        if self._cancel_requested:
            return
        self._cancel_requested = True
        self._stop_watchdog()
        if self.isRunning():
            self._terminate_active_subprocess(grace)

    def cleanup(self, wait_ms: int = 3000) -> None:
        """取消并回收在途 worker，然后安全调度删除。

        QA 场景（预览关闭瞬间）：先 ``request_cancel()`` + ``wait()`` 等待
        线程结束，再 ``deleteLater()`` —— 保证信号不会发射到已销毁对象。

        Parameters
        ----------
        wait_ms : int
            等待线程结束的最大毫秒数（默认 3000）。
        """
        if self.isRunning():
            self.request_cancel()
            self.wait(wait_ms)
        self.deleteLater()

    # ── 线程入口 ─────────────────────────────────────────────────────

    def run(self) -> None:
        """后台线程：调用 ``OfficeConverter.convert()`` 并发射信号。

        执行步骤：
        1. 记录当前线程 ident（T5 seam 按线程键控 Popen 注册表）；
        2. 取消快速失败路径 —— 已请求取消直接发射 failed(已取消)；
        3. 启动看门狗（仅当配置了 ``timeout``）；
        4. 调用 ``convert()``（耗时操作；LO 过程中 Popen 被注册到 seam）；
        5. ``finally`` 停看门狗、清 ident，标记完成；
        6. 按「取消 → 超时 → 错误 → 成功」顺序发射结果信号。取消 / 超时
           必须抑制过期转换结果（绝不发射 ``converted``）。
        """
        self._thread_ident = threading.get_ident()
        result: ConversionResult | None = None
        exc_message = ""
        try:
            if self._cancel_requested:
                pass  # 取消快速失败路径：跳过转换，但仍走到下面的发射区发射 failed(取消)
            else:
                self._start_watchdog()
                try:
                    result = OfficeConverter.convert(self._file_info)
                except Exception as e:
                    exc_message = f"Office 转换异常：{e}"
                finally:
                    self._stop_watchdog()
        finally:
            self._thread_ident = None
            self._done = True

        if self._cancel_requested:
            self.failed.emit(self._cancel_message())
        elif self._timed_out:
            self.failed.emit(self._timeout_message())
        elif result is None:
            self.failed.emit(exc_message)
        elif result.content_type == "error":
            self.failed.emit(result.message)
        else:
            self.converted.emit(self._encode_content(result))

    # ── 超时看门狗 ───────────────────────────────────────────────────

    def _start_watchdog(self) -> None:
        """按 ``timeout`` 参数启动一次性超时定时器（``None`` = 不启动）。"""
        if self._timeout is None:
            return
        self._watchdog = threading.Timer(self._timeout, self._on_watchdog_expiry)
        self._watchdog.daemon = True
        self._watchdog.start()

    def _stop_watchdog(self) -> None:
        """取消超时定时器（可重复调用）。"""
        if self._watchdog is not None:
            self._watchdog.cancel()
            self._watchdog = None

    def _on_watchdog_expiry(self) -> None:
        """超时回调：标记超时并终止活跃子进程（运行在定时器线程）。"""
        if self._cancel_requested or self._done:
            return
        self._timed_out = True
        self._terminate_active_subprocess()

    # ── 取消 / 超时的真实终止机制 ────────────────────────────────────

    def _terminate_active_subprocess(self, grace: float | None = None) -> None:
        """终止正在进行的转换：LO 子进程 kill，或 COM 孤儿清理。

        优先通过 T5 seam 按本 worker 线程 ident 找到注册的 soffice ``Popen``
        并杀死；未找到（COM 后端 / 尚未启动 / 已结束）则降级为 best-effort
        孤儿进程清理（COM 场景）。
        """
        if grace is None:
            grace = self._KILL_GRACE
        proc = self._wait_for_active_popen(self._CANCEL_POPEN_WAIT)
        if proc is not None:
            self._kill_popen(proc, grace)
        else:
            self._sweep_orphan_processes()

    def _wait_for_active_popen(self, timeout: float) -> Any:
        """轮询等待本 worker 线程的 soffice ``Popen`` 注册进 T5 seam。

        取消可能发生在转换启动过程中（Popen 尚未注册）；轮询 *timeout* 秒
        直到子进程句柄出现或超时，返回 ``None`` 表示当前无 LO 子进程。
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            thread_id = self._thread_ident
            if thread_id is not None:
                proc = get_active_lo_popen(thread_id)
                if proc is not None:
                    return proc
            time.sleep(0.01)
        return None

    @staticmethod
    def _kill_popen(proc: Any, grace: float) -> None:
        """terminate → 宽限 → kill → wait，确保子进程已死（绝不抛出）。"""
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=grace)
        except Exception:
            pass
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=grace)
            except Exception:
                pass

    def _sweep_orphan_processes(self) -> None:
        """COM 场景的 best-effort 僵尸进程清理（复用 office_converter 守卫）。"""
        try:
            OfficeConverter._cleanup_orphan_processes(self._task_started_at)
        except Exception:
            pass

    # ── 消息与编码 ───────────────────────────────────────────────────

    def _timeout_message(self) -> str:
        """超时失败消息 —— 消息必须含「超时」（Metis E3）。"""
        secs = (
            self._timeout
            if self._timeout is not None
            else SOFFICE_CONVERSION_TIMEOUT
        )
        return f"Office 转换超时（超过 {secs} 秒），已终止转换进程"

    @staticmethod
    def _cancel_message() -> str:
        """取消失败消息。"""
        return "Office 转换已取消"

    def _encode_content(self, result: ConversionResult) -> str:
        """把成功 / 降级结果编码为 ``converted`` 信号负载。

        - ``content_type == "pdf"``：PDF 产物路径字符串；
        - 降级内容（html/outline/table）：「``{content_type}:{content}``」标记。
        """
        if result.content_type == "pdf":
            return str(result.content)
        return f"{result.content_type}:{result.content}"


__all__ = [
    "OfficeConverterWorker",
]