from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import QPixmap

from freeassetfilter.utils.icon_utils import (
    DestroyIcon,
    get_highest_resolution_icon,
    hicon_to_pixmap,
    get_cached_icon_path,
    save_icon_to_cache,
)

_DEBUG_PRINT = None


def _debug(msg: str) -> None:
    global _DEBUG_PRINT
    if _DEBUG_PRINT is None:
        try:
            from freeassetfilter.utils.app_logger import debug
            _DEBUG_PRINT = debug
        except ImportError:
            _DEBUG_PRINT = lambda msg: None
    _DEBUG_PRINT(f"[AsyncIconLoader] {msg}")


class _IconLoadSignals(QObject):
    finished = Signal(str, object)


class _IconLoadRunnable(QRunnable):
    def __init__(
        self,
        file_path: str,
        icon_size: int,
        signals: _IconLoadSignals,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.file_path = file_path
        self.icon_size = icon_size
        self.signals = signals
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        if self._cancelled:
            return

        _debug(f"开始加载图标: {self.file_path}")
        hicon = None
        pixmap = None

        cached_path = get_cached_icon_path(self.file_path)
        if cached_path:
            try:
                pixmap = QPixmap(cached_path)
                if pixmap and not pixmap.isNull():
                    _debug(f"从文件缓存加载图标: {self.file_path}")
                    self.signals.finished.emit(self.file_path, pixmap)
                    return
            except Exception as e:
                _debug(f"加载缓存图标失败，尝试重新获取: {self.file_path}, {e}")

        try:
            hicon = get_highest_resolution_icon(self.file_path)
            if hicon and not self._cancelled:
                pixmap = hicon_to_pixmap(hicon, self.icon_size, None)
                if pixmap and not pixmap.isNull():
                    save_icon_to_cache(self.file_path, pixmap)
                    _debug(f"图标已保存到缓存: {self.file_path}")
        except Exception as e:
            _debug(f"加载图标异常: {self.file_path}, {e}")
        finally:
            if hicon:
                try:
                    DestroyIcon(hicon)
                except Exception as e:
                    _debug(f"释放HICON异常: {e}")

        if self._cancelled:
            return

        _debug(f"图标加载完成: {self.file_path}")
        self.signals.finished.emit(self.file_path, pixmap)


class AsyncIconLoader:
    _instance: Optional["AsyncIconLoader"] = None

    def __init__(self) -> None:
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(max(2, min(os.cpu_count() or 4, 8)))
        self._signals = _IconLoadSignals()
        self._callbacks: dict[str, Callable[[str, Optional[QPixmap]], None]] = {}
        self._runnables: dict[str, _IconLoadRunnable] = {}

        self._signals.finished.connect(self._on_finished)

    @classmethod
    def instance(cls) -> "AsyncIconLoader":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load_icon(
        self,
        file_path: str,
        callback: Callable[[str, Optional[QPixmap]], None],
        icon_size: int = 256,
    ) -> None:
        self.cancel_load(file_path)

        # Keep a strong reference until completion; callers often pass
        # short-lived closures that would otherwise be collected immediately.
        self._callbacks[file_path] = callback

        runnable = _IconLoadRunnable(file_path, icon_size, self._signals)
        self._runnables[file_path] = runnable
        self._pool.start(runnable)
        _debug(f"提交图标加载任务: {file_path}")

    def cancel_load(self, file_path: str) -> None:
        runnable = self._runnables.pop(file_path, None)
        if runnable is not None:
            runnable.cancel()
        self._callbacks.pop(file_path, None)

    def clear(self) -> None:
        for runnable in self._runnables.values():
            runnable.cancel()
        self._runnables.clear()
        self._callbacks.clear()
        _debug("清理所有待处理任务")

    def _on_finished(self, file_path: str, pixmap: Optional[QPixmap]) -> None:
        self._runnables.pop(file_path, None)
        callback = self._callbacks.pop(file_path, None)
        if callback is not None:
            try:
                callback(file_path, pixmap)
            except Exception as e:
                _debug(f"执行回调异常: {file_path}, {e}")
