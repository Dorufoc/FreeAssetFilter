#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

缩略图控制层
以 QThreadPool + QRunnable（外层仅编排，批量接口内部自带线程池）
调度 ThumbnailManager 的批量生成与缓存清除任务，通过 Qt 信号把
节流后的进度、就绪文件批与统计结果回传 UI 线程。
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from freeassetfilter.core.managers.thumbnail_manager import (
    clear_all_thumbnails,
    get_thumbnail_manager,
    has_thumbnail,
    is_media_file,
)


def _extract_file_path(file_data: str | dict) -> str:
    """从批量回调透传的文件项中提取文件路径。

    与 ThumbnailManager 批量接口的宽容输入对齐：str 直接返回，
    dict 依次按 "path" / "file_path" 键提取。

    Args:
        file_data: 批量回调透传的原始文件项。

    Returns:
        str: 文件路径；无法提取时返回空字符串。
    """
    if isinstance(file_data, str):
        return file_data
    if isinstance(file_data, dict):
        return str(file_data.get("path") or file_data.get("file_path") or "")
    return ""


class _GenerationTask(QRunnable):
    """生成任务 QRunnable：内部持有世代 token 与取消 Event。

    由 :meth:`ThumbnailController.start_generation` 投递到
    ``QThreadPool.globalInstance()``；``run()`` 委托控制器执行体
    ``_run_generation``，token 失效丢弃结果与节流发射保持原语义
    （线程池持有引用，``run`` 结束后 AutoDelete 释放）。

    Args:
        controller: 所属 ThumbnailController（任务收尾与信号发射经由它）。
        file_paths: 待生成缩略图的文件路径列表。
        token: 任务启动时的世代快照。
        cancel_event: 与控制器共享的取消 Event（``cancel()`` 置位）。
        started: 启动交会 Event，进入批量阻塞调用前置位。
    """

    def __init__(
        self,
        controller: ThumbnailController,
        file_paths: list[str],
        token: int,
        cancel_event: threading.Event,
        started: threading.Event,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._controller = controller
        self._file_paths = file_paths
        self._token = token
        self._cancel_event = cancel_event
        self._started = started

    def run(self) -> None:
        self._controller._run_generation(
            self._file_paths, self._token, self._cancel_event, self._started
        )


class _ClearTask(QRunnable):
    """清除任务 QRunnable：内部持有世代 token（清除任务无取消语义）。

    由 :meth:`ThumbnailController.start_clear` 投递到
    ``QThreadPool.globalInstance()``。

    Args:
        controller: 所属 ThumbnailController（任务收尾与信号发射经由它）。
        token: 任务启动时的世代快照。
        started: 启动交会 Event，进入磁盘删除前置位。
    """

    def __init__(
        self, controller: ThumbnailController, token: int, started: threading.Event
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._controller = controller
        self._token = token
        self._started = started

    def run(self) -> None:
        self._controller._run_clear(self._token, self._started)


class ThumbnailController(QObject):
    """缩略图生成 / 清除的后台编排控制器。

    封装 ``ThumbnailManager.create_thumbnails_batch``（同步阻塞、内部
    自带线程池）与 ``clear_all_thumbnails``，以 QRunnable 投
    ``QThreadPool.globalInstance()`` 编排，UI 层只与本类交互：

    * 生成与清除互斥（``is_busy`` 为 True 时 ``start_*`` 返回 False）；
    * ``cancel()`` 置取消 Event 并释放互斥，旧任务的过期事件经
      世代 token 比对后直接丢弃，允许立即启动新任务（目录切换场景）；
    * progress_callback 与就绪文件批按 ≥200ms 时间间隔或每 8 个文件
      合并节流后发射 ``files_ready`` / ``progress_emitted``；
    * 后台任务内的异常经 ``failed`` 信号回传，不向 UI 线程泄漏。

    信号命名刻意避开 QThread 内置的 ``finished`` 重名坑。
    """

    # 节流发射的最小时间间隔（秒）
    _PROGRESS_EMIT_INTERVAL = 0.2
    # 就绪文件批的合并上限（达到即立即发射）
    _READY_BATCH_SIZE = 8

    # 信号定义避开 QThread 内置 finished 重名坑
    progress_emitted = Signal(int, int)
    files_ready = Signal(list)
    batch_finished = Signal(int, int)
    clear_finished = Signal(int)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        """初始化控制器。

        Args:
            parent: 可选的父 QObject。
        """
        super().__init__(parent)
        self._lock = threading.Lock()
        self._generation_token = 0
        # 协作式取消 Event（等价旧实现 _cancel_flag：start_* 时 clear，cancel() 时 set）
        self._cancel_event = threading.Event()
        self._busy = False
        # 裸 Thread 时代的后台线程引用表（retired refs 模式）。
        # QThreadPool 接管任务持有（AutoDelete）后不再追加，恒为空；
        # 仅保留属性供外部 introspection 兼容（空任务短路断言等）。
        self._worker_threads: list[threading.Thread] = []

    @property
    def is_busy(self) -> bool:
        """bool: 是否有生成/清除任务正在进行。"""
        with self._lock:
            return self._busy

    def start_generation(self, file_paths: list[str]) -> bool:
        """启动批量缩略图生成（QThreadPool 后台任务）。

        收集阶段过滤非媒体文件与已有缩略图的文件（保序去重）；空任务
        不投递任务，直接发射 ``batch_finished(0, 0)``。

        Args:
            file_paths: 候选文件路径列表。

        Returns:
            bool: 成功启动返回 True；已有任务进行中返回 False。
        """
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            self._generation_token += 1
            token = self._generation_token
            self._cancel_event.clear()

        pending_files = self._collect_pending_files(file_paths)
        if not pending_files:
            self._finish_task(token)
            self.batch_finished.emit(0, 0)
            return True

        # 启动交会：等价旧实现 Thread.start() 的线程引导保证——
        # 旧实现 start() 返回前工作线程已开始执行，调用方紧随其后的
        # 状态断言/释放操作不会跑在任务启动之前。线程池投递无此保证，
        # 故在此有界等待任务进入阻塞调用（超时则放行，永不挂起 UI）。
        started = threading.Event()
        QThreadPool.globalInstance().start(
            _GenerationTask(self, pending_files, token, self._cancel_event, started)
        )
        started.wait(timeout=10.0)
        return True

    def start_clear(self) -> bool:
        """启动全部缩略图缓存清除（QThreadPool 后台任务）。

        清除为一次性磁盘删除操作，无取消语义。

        Returns:
            bool: 成功启动返回 True；已有任务进行中返回 False。
        """
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            self._generation_token += 1
            token = self._generation_token
            self._cancel_event.clear()

        # 启动交会（同 start_generation）：有界等待清除任务进入磁盘删除，
        # 超时放行，永不挂起调用方。
        started = threading.Event()
        QThreadPool.globalInstance().start(_ClearTask(self, token, started))
        started.wait(timeout=10.0)
        return True

    def cancel(self) -> None:
        """请求协作式取消当前生成任务。

        置取消 Event（经 cancel_check 感知）并释放互斥，允许调用方立即
        启动新任务；同时递增世代 token，使旧任务的后续事件与收尾统计
        （含 batch_finished(0, 0) 类空收尾）被丢弃，避免污染新状态。
        清除任务无取消语义。
        """
        with self._lock:
            self._cancel_event.set()
            self._busy = False
            self._generation_token += 1

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _collect_pending_files(self, file_paths: list[str]) -> list[str]:
        """收集阶段过滤：仅保留尚无缩略图的媒体文件（保序去重）。

        Args:
            file_paths: 候选文件路径列表。

        Returns:
            list[str]: 待生成缩略图的文件路径列表。
        """
        seen: set[str] = set()
        pending: list[str] = []
        for file_path in file_paths:
            if not file_path or file_path in seen:
                continue
            seen.add(file_path)
            if is_media_file(file_path) and not has_thumbnail(file_path):
                pending.append(file_path)
        return pending

    def _run_generation(
        self,
        file_paths: list[str],
        token: int,
        cancel_event: threading.Event,
        started: threading.Event,
    ) -> None:
        """生成任务执行体（由 QRunnable 在线程池线程中调用）。

        Args:
            file_paths: 待生成缩略图的文件路径列表。
            token: 任务启动时的世代快照，失效后丢弃全部事件。
            cancel_event: 与控制器共享的取消 Event（``cancel()`` 置位）。
            started: 启动交会 Event，进入批量阻塞调用前置位。
        """
        ready_buffer: list[str] = []
        last_emit_time = time.monotonic()

        def _on_item_processed(
            done_count: int, total_count: int, file_data: str | dict, success: bool
        ) -> None:
            """单文件完成回调：按节流策略合并发射就绪批与进度。

            Args:
                done_count: 已处理文件数。
                total_count: 总文件数。
                file_data: 批量接口透传的原始文件项。
                success: 该文件缩略图是否生成成功。
            """
            nonlocal ready_buffer, last_emit_time
            if not self._token_is_current(token):
                return  # 过期世代事件直接丢弃

            if success:
                file_path = _extract_file_path(file_data)
                if file_path:
                    ready_buffer.append(file_path)

            now = time.monotonic()
            should_emit = (
                len(ready_buffer) >= self._READY_BATCH_SIZE
                or now - last_emit_time >= self._PROGRESS_EMIT_INTERVAL
            )
            if not should_emit:
                return
            if ready_buffer:
                self.files_ready.emit(list(ready_buffer))
                ready_buffer.clear()
            self.progress_emitted.emit(done_count, total_count)
            last_emit_time = now

        def _cancel_check() -> bool:
            """协作式取消检查：显式取消（Event 置位）或世代失效均视为取消。"""
            return cancel_event.is_set() or not self._token_is_current(token)

        try:
            manager = get_thumbnail_manager()
            started.set()
            success_count, processed_count = manager.create_thumbnails_batch(
                file_paths,
                progress_callback=_on_item_processed,
                cancel_check=_cancel_check,
            )
            if not self._token_is_current(token):
                return
            if ready_buffer:
                self.files_ready.emit(list(ready_buffer))
                ready_buffer.clear()
            self.batch_finished.emit(success_count, processed_count)
        except Exception as exc:  # noqa: BLE001  # 后台任务兜底，经 failed 信号回传
            if self._token_is_current(token):
                self.failed.emit(str(exc))
        finally:
            self._finish_task(token)

    def _run_clear(self, token: int, started: threading.Event) -> None:
        """清除任务执行体（由 QRunnable 在线程池线程中调用，无取消语义）。

        Args:
            token: 任务启动时的世代快照，失效后丢弃结果。
            started: 启动交会 Event，进入磁盘删除前置位。
        """
        try:
            started.set()
            deleted_count = clear_all_thumbnails()
            if self._token_is_current(token):
                self.clear_finished.emit(deleted_count)
        except Exception as exc:  # noqa: BLE001  # 后台任务兜底，经 failed 信号回传
            if self._token_is_current(token):
                self.failed.emit(str(exc))
        finally:
            self._finish_task(token)

    def _token_is_current(self, token: int) -> bool:
        """判断世代 token 是否仍指向当前任务。

        Args:
            token: 任务启动时的世代快照。

        Returns:
            bool: token 与当前世代一致返回 True。
        """
        # int 读取依赖 GIL 原子性，无需额外加锁
        return token == self._generation_token

    def _finish_task(self, token: int) -> None:
        """任务收尾：世代未失效时释放互斥标记。

        Args:
            token: 任务启动时的世代快照。
        """
        with self._lock:
            if token == self._generation_token:
                self._busy = False


__all__ = ["ThumbnailController"]
