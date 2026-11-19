#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sopeek v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/Sopeek
许可协议：https://github.com/Dorufoc/Sopeek/blob/main/LICENSE

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

import os
import threading
import time
import traceback
from datetime import datetime
from typing import Any

from PySide6.QtCore import QThread, Signal

from sopeek.services.office_converter import (
    ConversionResult,
    OfficeConverter,
    SOFFICE_CONVERSION_TIMEOUT,
    get_active_lo_popen,
)
from sopeek.services.office_error_report import build_office_error_report
from sopeek.utils.app_logger import debug, warning


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
            降级内容（html/outline）时为 ``"{content_type}:{content}"``
            标记字符串。
        failed: ``(str)`` —— 错误 / 取消 / 超时消息。取消消息含「取消」；超时
            消息必含「超时」（Metis E3）。保留该信号供旧调用方兼容。
        failed_with_report: ``(str, str)`` —— ``(展示消息, 完整错误报告)``。
            预览器连接此信号以获得「复制错误信息」所需的完整上下文
            （版本 / 文件 / 后端 / 技术详情 / 日志路径）。
    """

    converted = Signal(str)
    failed = Signal(str)
    failed_with_report = Signal(str, str)

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
        """请求取消当前转换并异步终止活跃子进程（**不在调用线程等待**）。

        幂等：已取消时直接返回。置取消标志 + 停看门狗后，把
        ``_terminate_active_subprocess`` 放到 daemon 线程执行：该函数可能
        轮询等待 Popen 注册（最长 2s）并 terminate/wait/kill，放到后台可
        避免快速切换预览时卡住 UI 线程。worker 的 ``run()`` 在转换返回后
        根据 ``_cancel_requested`` 抑制成功结果。

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
            threading.Thread(
                target=self._terminate_active_subprocess_bg,
                args=(grace,),
                name="OfficeCancelTerminate",
                daemon=True,
            ).start()

    def _terminate_active_subprocess_bg(self, grace: float | None) -> None:
        """后台终止入口（吞掉退出阶段的任意异常，避免线程 traceback 噪音）。"""
        try:
            self._terminate_active_subprocess(grace)
        except Exception:  # noqa: BLE001 — 后台尽力而为
            pass

    def retire(self) -> None:
        """非阻塞回收：请求取消，并在线程结束后 deleteLater。

        供预览器快速切换/清理路径调用；调用方须先断开结果信号连接。
        若线程已结束则直接安排删除。
        """
        if self.isRunning():
            self.finished.connect(self.deleteLater)
        self.request_cancel()
        if not self.isRunning():
            self.deleteLater()

    def cleanup(self, wait_ms: int = 0) -> None:
        """取消并回收在途 worker，然后安全调度删除。

        P6.3：默认**不阻塞调用线程**（``wait_ms=0``）——``request_cancel()``
        已终止 soffice 子进程，线程会自然结束；用 ``finished → deleteLater``
        代替同步 ``wait()``。仅在 ``wait_ms > 0`` 或
        ``SPK_OFFICE_BLOCKING_CLEANUP=1`` 时保留旧的有界等待（退出路径）。

        Parameters
        ----------
        wait_ms : int
            等待线程结束的最大毫秒数（默认 0 = 不阻塞）。
        """
        blocking = wait_ms > 0 or os.environ.get(
            "SPK_OFFICE_BLOCKING_CLEANUP", ""
        ).strip().lower() in {"1", "true", "yes", "on"}
        if self.isRunning():
            self.request_cancel()
            if blocking:
                self.wait(wait_ms or 300)
            else:
                try:
                    self.finished.connect(self.deleteLater)
                except Exception:  # noqa: BLE001 - 已销毁对象
                    pass
                return
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

        失败时同时发射 ``failed``（短消息）与 ``failed_with_report``
        （短消息 + 完整报告）；后者供预览器「一键复制错误信息」使用。
        """
        self._thread_ident = threading.get_ident()
        result: ConversionResult | None = None
        exc_message = ""
        exc_detail = ""
        try:
            if self._cancel_requested:
                pass  # 取消快速失败路径：跳过转换，但仍走到下面的发射区发射 failed(取消)
            else:
                self._start_watchdog()
                try:
                    result = OfficeConverter.convert(self._file_info)
                except Exception as e:
                    exc_message = f"Office 转换异常：{e}"
                    exc_detail = traceback.format_exc()
                finally:
                    self._stop_watchdog()
        finally:
            self._thread_ident = None
            self._done = True

        if self._cancel_requested:
            self._emit_failure(self._cancel_message(), "")
        elif self._timed_out:
            self._emit_failure(self._timeout_message(), "")
        elif result is None:
            self._emit_failure(
                exc_message or "Office 转换失败：未知错误",
                exc_detail,
            )
        elif result.content_type == "error":
            self._emit_failure(
                result.message,
                result.detail,
                result.failed_backend,
            )
        else:
            self.converted.emit(self._encode_content(result))

    def _emit_failure(
        self,
        message: str,
        detail: str,
        backend: str = "",
    ) -> None:
        """发射 ``failed`` 与 ``failed_with_report`` 两个兼容信号。

        报告构建本身失败时降级为短消息，绝不让错误提示因报告异常而丢失。
        """
        self.failed.emit(message)
        try:
            report = build_office_error_report(
                message,
                detail=detail,
                file_path=str(self._file_info.get("path", "") or ""),
                suffix=str(self._file_info.get("suffix", "") or "")
                .lower()
                .lstrip("."),
                backend=backend,
            )
        except Exception:  # noqa: BLE001 - 报告失败不得阻断错误提示
            report = message
        self.failed_with_report.emit(message, report)

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
        """终止正在进行的转换：只终止**本次转换自己的** soffice 子进程。

        关键安全约束（崩溃修复）：只有通过 T5 seam 按本 worker 线程 ident
        拿到 ``Popen`` 时才终止子进程。拿不到说明当前后端是 COM（没有
        ``Popen`` 句柄），此时**绝不做孤儿进程清理**——COM 转换仍在
        ``_com_convert_in_task`` 中同步使用着 Excel/Word 实例，从外部
        ``Stop-Process -Force`` 掉它会触发 RPC 断开（``0x80010108`` /
        ``0x800706be`` / ``0x800706ba``）这类 SEH 异常，Python 捕获不到，
        直接让整个进程崩溃（实测日志 `QThread: Destroyed` + 进程 abort）。

        COM 场景的取消语义退化为「标记 ``_cancel_requested`` + 抑制结果
        发射」：转换自行走完 ``finally``（``app.Quit()`` 关闭实例），
        失败/退出不干净时的孤儿清理由 ``_com_convert_in_task`` 的
        ``finally`` 负责——那里实例已不再被使用，清理是安全的。

        Args:
            grace: terminate() 后的宽限秒数；``None`` 用 ``_KILL_GRACE``。
        """
        if grace is None:
            grace = self._KILL_GRACE
        proc = self._wait_for_active_popen(self._CANCEL_POPEN_WAIT)
        if proc is not None:
            self._kill_popen(proc, grace)
            return
        # COM 后端：不做孤儿清理（会杀死正在使用的 Office 实例 → 进程崩溃）。
        debug(
            "[OfficeConverterWorker] 取消：当前后端无 soffice 子进程（COM），"
            "跳过孤儿进程清理以避免终止正在使用的 Office 实例"
        )

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
        except Exception as exc:
            debug(f"终止子进程失败：{exc}")
        try:
            proc.wait(timeout=grace)
        except Exception as exc:
            debug(f"等待子进程退出失败/超时：{exc}")
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception as exc:
                debug(f"强杀子进程失败：{exc}")
            try:
                proc.wait(timeout=grace)
            except Exception as exc:
                debug(f"等待强杀后子进程退出失败/超时：{exc}")

    def _sweep_orphan_processes(self) -> None:
        """COM 场景的 best-effort 僵尸进程清理（复用 office_converter 守卫）。"""
        try:
            OfficeConverter._cleanup_orphan_processes(self._task_started_at)
        except Exception as exc:
            debug(f"孤儿进程清理失败（可能残留 soffice/Office 进程）：{exc}")

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
        - 降级内容（html/outline）：「``{content_type}:{content}``」标记。
        """
        if result.content_type == "pdf":
            return str(result.content)
        return f"{result.content_type}:{result.content}"


__all__ = [
    "OfficeConverterWorker",
]