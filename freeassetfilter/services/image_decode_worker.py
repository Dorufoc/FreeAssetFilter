#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

异步图片解码工作线程
封装 ImageDecoderService.decode_to_qimage() 以在后台线程解码图片，
避免阻塞 UI 主线程。支持超时、取消、以及通过信号返回结果。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QThread, Signal, QTimer

from freeassetfilter.services.image_decoder_service import ImageDecoderService
from freeassetfilter.utils.app_logger import warning

# ── 解码超时（毫秒）─────────────────────────────────────────────────────

_DECODE_TIMEOUT_MS: int = 60_000  # 60 秒


class ImageDecodeWorker(QThread):
    """异步图片解码工作线程。

    调用 :meth:`ImageDecoderService.decode_to_qimage` 在后台解码图片，
    通过信号返回结果。支持取消和超时。

    Usage::

        worker = ImageDecodeWorker("photo.cr2")
        worker.decoded.connect(self._on_decoded)
        worker.failed.connect(self._on_failed)
        worker.start_with_timeout()
        # worker.cancel()  # 随时取消

    Signals:
        decoded: ``(QImage, file_path)`` 解码成功
        failed: ``(error_message)`` 解码失败
    """

    decoded = Signal(object, str)  # QImage as object to avoid metatype issues
    failed = Signal(str)

    def __init__(self, file_path: str, parent: Optional = None) -> None:
        """初始化工作线程。

        Parameters
        ----------
        file_path : str
            要解码的图片文件路径。
        parent : QObject or None
            Qt 父对象（可选）。
        """
        super().__init__(parent)
        self.file_path = file_path
        self._is_cancelled: bool = False
        self._timeout_timer: Optional[QTimer] = None

    # ── 公共 API ─────────────────────────────────────────────────────

    def start_with_timeout(
        self,
        priority: QThread.Priority = QThread.InheritPriority,
    ) -> None:
        """启动 worker 线程，60 秒超时后自动终止。

        使用 ``QTimer.singleShot`` 风格的单次定时器实现超时检测。
        timer 在 worker ``finished`` 时自动停止，避免 timer 泄漏。

        Parameters
        ----------
        priority : QThread.Priority
            线程优先级，默认继承调用线程的优先级。
        """
        self.start(priority)
        self._timeout_timer = QTimer()
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)
        self._timeout_timer.start(_DECODE_TIMEOUT_MS)
        # 确保 timer 在 worker 完成时停止，避免 timer 泄漏
        self.finished.connect(self._timeout_timer.stop)

    def cancel(self) -> None:
        """请求取消当前解码。

        设置取消标志 + ``quit()`` + 最多等待 2 秒。
        注意：如果线程卡在 rawpy/LibRaw 的 C 扩展中，wait 可能超时，
        这是已知限制（与 ``RawProcessor.cancel()`` 行为一致）。
        """
        self._is_cancelled = True
        self.quit()
        if not self.wait(2000):
            warning(
                "[ImageDecodeWorker] cancel: wait timed out, "
                "thread may be stuck in native code"
            )

    # ── 内部方法 ─────────────────────────────────────────────────────

    def run(self) -> None:
        """后台线程：调用 ImageDecoderService 解码。

        执行步骤：
        1. 检查取消标志（快速失败路径）
        2. 调用 ``decode_to_qimage()``（耗时操作）
        3. 再次检查取消标志（避免发出已取消的结果）
        4. 根据结果发射 ``decoded`` 或 ``failed`` 信号
        """
        if self._is_cancelled:
            return

        success, result = ImageDecoderService.decode_to_qimage(self.file_path)

        if self._is_cancelled:
            return

        if success:
            self.decoded.emit(result, self.file_path)
        else:
            self.failed.emit(str(result))

    def _on_timeout(self) -> None:
        """超时回调：发射 failed 信号并取消线程。"""
        if self.isRunning():
            self.failed.emit(
                f"解码超时（超过 {_DECODE_TIMEOUT_MS // 1000} 秒）"
            )
            self.cancel()


__all__ = [
    "ImageDecodeWorker",
]
