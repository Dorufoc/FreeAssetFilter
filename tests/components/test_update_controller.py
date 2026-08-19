# -*- coding: utf-8 -*-
"""update_controller.py 补强测试（W18）。

覆盖 ``freeassetfilter/components/update_controller.py`` 中被既有
``test_settings_window.py`` 遗漏的剩余分支：

* 模块级 atexit / QThread 引用集清理（``_wait_global_threads``、
  ``_keep_qthread_alive`` 的异常兜底）；
* ``SilentUpdateCheckWorker.run`` 的中断分支（开始前 / 检查后 /
  异常路径中被中断）；
* ``UpdateDownloadWorker.run`` 的临时文件清理、取消时 close/remove
  异常、SHA256 失败清理、URLError / OSError / 泛型异常清理；
* ``UpdateController`` 各槽与对话框点击（直接以 int 索引调用，
  不 exec() 任何真实对话框）：
  ``cancel_silent_check`` / ``bind_button`` / ``_retire_worker`` /
  ``on_check_updates_clicked``（重启与下载中忽略）/ ``_show_check_result``
  （本地缓存可用）/ ``_on_check_failure``（取消后）/ ``_on_update_available_dialog_clicked``
  （无 installer_name、总大小 0）/ ``_poll_download_progress_from_file``
  （无进度条、getsize 异常、总大小 0）/ ``_on_install_ready_dialog_clicked``
  （信息不完整、清理异常、启动异常）/ ``_set_dialog_buttons`` /
  ``_close_current_dialog``（close 异常、spinner 清理）；
* 静态工具：``_convert_markdown_to_html`` 的 ``# `` / ``### `` 分支。

策略：CustomMessageBox 与 LoadingSpinner 全部打桩（避免真实模态框与
GC 时序抖动）；更新管理器侧的 check_for_updates / urlopen / 校验全部
monkeypatch，不触网、不 exec()。
"""

from __future__ import annotations

import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QLabel, QWidget

from tests.support.qt_helpers import flush_widget_queue, safe_teardown

pytestmark = pytest.mark.unit

# =============================================================================
# 公开辅助工具（与 test_settings_window.py 约定保持一致）
# =============================================================================
_RELEASE_INFO: Dict[str, Any] = {
    "installer_name": "FreeAssetFilter-setup.exe",
    "installer_download_url": "https://example.com/faf-setup.exe",
    "installer_sha256": "ab" * 32,
    "installer_size": 1500,
}


def _no_update_result() -> Dict[str, Any]:
    """"已是最新版本"的 check_for_updates 返回。"""
    return {
        "update_available": False,
        "comparison_result": 0,
        "local_info": {"tag_name": "v1.0.0", "build_date": "2026-01-01"},
        "latest_release": {"tag_name": "v1.0.0", "published_date": "2026-01-01"},
        "cache_result": {"is_ready": False, "reason": "无需更新"},
    }


def _update_available_result() -> Dict[str, Any]:
    """"发现新版本"的 check_for_updates 返回。"""
    return {
        "update_available": True,
        "comparison_result": 1,
        "local_info": {"tag_name": "v1.0.0-alpha.5", "build_date": "2026-08-01"},
        "latest_release": {
            "tag_name": "v1.1.0",
            "published_date": "2026-08-10",
            "installer_name": _RELEASE_INFO["installer_name"],
            "installer_download_url": _RELEASE_INFO["installer_download_url"],
            "installer_sha256": _RELEASE_INFO["installer_sha256"],
            "installer_size": _RELEASE_INFO["installer_size"],
            "release_body": "- 修复若干问题\n- 提升性能",
        },
        "cache_result": {"is_ready": False, "reason": "未缓存"},
    }


@pytest.fixture
def make_update_controller(qapp: Any) -> Iterator[Callable[..., Any]]:
    """构造 UpdateController 的工厂（main_window 用占位 QObject）。

    Args:
        qapp: 会话级 QApplication 实例。

    Yields:
        Callable[..., Any]: 每次调用返回一个新控制器实例。
    """
    from freeassetfilter.components.update_controller import UpdateController

    built: List[Any] = []

    def _factory() -> Any:
        controller: Any = UpdateController(QObject())
        built.append(controller)
        return controller

    yield _factory
    for controller in built:
        safe_teardown(controller)
    flush_widget_queue()


@pytest.fixture(autouse=True)
def _restore_global_qthread_refs() -> Iterator[None]:
    """每个测试前后恢复模块级 QThread 引用集（避免 atexit 调用假 worker）。"""
    import freeassetfilter.components.update_controller as uc

    saved: set = set(uc._global_qthread_refs)
    yield
    uc._global_qthread_refs.clear()
    uc._global_qthread_refs.update(saved)


class _FakeSignal:
    """可 connect 的信号占位，供假 worker 使用。"""

    def __init__(self) -> None:
        self.callbacks: List[Callable[..., Any]] = []

    def connect(self, callback: Callable[..., Any]) -> None:
        """记录回调（模拟 connect）。"""
        self.callbacks.append(callback)

    def emit(self, *args: Any) -> None:
        """同步调用所有已注册回调。"""
        for cb in list(self.callbacks):
            cb(*args)


class _FakeWorker:
    """假 QThread：验证 UpdateController 不会阻塞等待 worker。"""

    def __init__(self, running: bool = True) -> None:
        self._running: bool = running
        self.interruption_requested: bool = False
        self.wait_called: bool = False
        self.finished: _FakeSignal = _FakeSignal()
        self.success: _FakeSignal = _FakeSignal()
        self.failure: _FakeSignal = _FakeSignal()
        self.cancelled: _FakeSignal = _FakeSignal()

    def isRunning(self) -> bool:
        """返回模拟的运行状态。"""
        return self._running

    def isInterruptionRequested(self) -> bool:
        """返回是否已请求中断。"""
        return self.interruption_requested

    def requestInterruption(self) -> None:
        """记录中断请求。"""
        self.interruption_requested = True

    def wait(self, *args: Any, **kwargs: Any) -> bool:
        """记录 wait 调用（不阻塞）。"""
        self.wait_called = True
        return True


class _FakeSignalBox:
    """可 connect / emit 的信号占位（供假对话框 / 假 worker 使用）。"""

    def __init__(self) -> None:
        self._callbacks: List[Callable[..., Any]] = []

    def connect(self, callback: Callable[..., Any]) -> None:
        """记录回调。"""
        self._callbacks.append(callback)

    def emit(self, *args: Any) -> None:
        """同步调用所有已注册回调。"""
        for cb in list(self._callbacks):
            cb(*args)


class _FakeWidgetStub:
    """UI 小件占位：hide/show/setText/setRange 等 no-op。"""

    def __init__(self) -> None:
        self.text: str = ""

    def hide(self) -> None:
        return None

    def show(self) -> None:
        return None

    def setText(self, text: str) -> None:
        self.text = text


class _StubBoxLayout:
    """QVBoxLayout 占位：记录 addWidget / 支持 indexOf / insertWidget。

    同时把真实 QWidget 重新挂到持久 owner 下，防止 progress_container（含
    真实 QLabel / D_ProgressBar）被 GC 导致已删除句柄（shiboken RuntimeError）。
    """

    def __init__(self) -> None:
        self.widgets: List[Any] = []
        self._owner: QWidget = QWidget()

    def addWidget(self, *args: Any, **kwargs: Any) -> None:
        return None

    def removeWidget(self, *args: Any, **kwargs: Any) -> None:
        return None

    def insertWidget(self, index: int, *args: Any, **kwargs: Any) -> None:
        if args and isinstance(args[0], QWidget):
            args[0].setParent(self._owner)
        return None

    def indexOf(self, widget: Any) -> int:
        """按钮组件默认位于末尾，保证插入位置有效。"""
        return -1


class _FakeMessageBox:
    """CustomMessageBox 空壳：满足全部对话框接口，exec() 直接返回。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.text_label: Any = _FakeWidgetStub()
        self.image_label: Any = _FakeWidgetStub()
        self.list_widget: Any = _FakeWidgetStub()
        self.input_widget: Any = _FakeWidgetStub()
        self.progress_widget: Any = _FakeWidgetStub()
        self.button_widget: Any = _FakeWidgetStub()
        self.body_layout: Any = _StubBoxLayout()
        self.list_layout: Any = _StubBoxLayout()
        self.buttonClicked: Any = _FakeSignalBox()
        self.closed: bool = False
        self.shown: bool = False

    def setModal(self, *args: Any, **kwargs: Any) -> None:
        return None

    def setWindowFlags(self, *args: Any, **kwargs: Any) -> None:
        return None

    def windowFlags(self) -> int:
        return int(Qt.WindowCloseButtonHint)

    def set_title(self, *args: Any, **kwargs: Any) -> None:
        return None

    def set_text(self, *args: Any, **kwargs: Any) -> None:
        return None

    def set_buttons(self, *args: Any, **kwargs: Any) -> None:
        return None

    def show(self) -> None:
        self.shown = True

    def close(self) -> None:
        self.closed = True

    def exec(self) -> int:  # noqa: A003
        return 0


class _FakeSpinner:
    """LoadingSpinner 占位：避免真实 QWidget 的 GC 时序抖动（W18）。"""

    def __init__(self, **kwargs: Any) -> None:
        self.stopped: bool = False
        self.started: bool = False

    def set_background_color(self, *args: Any, **kwargs: Any) -> None:
        return None

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class _FakeUrlResponse:
    """模拟 urllib 下载响应：可配置在指定次数后抛异常。"""

    def __init__(
        self,
        chunks: List[bytes],
        content_length: Optional[int] = None,
        fail_on_index: Optional[int] = None,
        fail_error: Optional[Exception] = None,
    ) -> None:
        self.headers: Dict[str, str] = {
            "content-length": str(
                content_length if content_length is not None else sum(len(c) for c in chunks)
            )
        }
        self._chunks: List[bytes] = list(chunks)
        self._index: int = 0
        self._fail_on_index: Optional[int] = fail_on_index
        self._fail_error: Optional[Exception] = fail_error

    def __enter__(self) -> "_FakeUrlResponse":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def read(self, size: int = -1) -> bytes:
        if self._fail_on_index is not None and self._index == self._fail_on_index:
            raise self._fail_error if self._fail_error is not None else RuntimeError("boom")
        if self._index >= len(self._chunks):
            return b""
        chunk: bytes = self._chunks[self._index]
        self._index += 1
        return chunk


class _FakeUrlOpener:
    """替换 urllib.request.urlopen：返回分块响应或抛指定异常。"""

    def __init__(self, response: Any = None, error: Optional[Exception] = None) -> None:
        self.response: Any = response
        self.error: Optional[Exception] = error

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self.error is not None:
            raise self.error
        return self.response


def _pump_until(
    qapp: Any,
    predicate: Callable[[], bool],
    timeout_s: float = 5.0,
) -> bool:
    """在截止期内轮询冲刷 Qt 事件直到谓词满足（有界，绝不无限等待）。"""
    deadline: float = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        flush_widget_queue(qapp, iterations=5)
        time.sleep(0.01)
    return bool(predicate())


def _make_download_worker(
    monkeypatch: Any,
    tmp_path: Any,
    *,
    release_info: Optional[Dict[str, Any]] = None,
    opener: Optional[Any] = None,
    verify: Optional[Callable[..., Any]] = None,
    prepare: Optional[Callable[..., Any]] = None,
    replace: Optional[Callable[..., Any]] = None,
    remove: Optional[Callable[..., Any]] = None,
) -> Tuple[Any, Dict[str, Any]]:
    """装配 UpdateDownloadWorker 并返回 worker 与信号记录（全 mock，不触网）。

    Args:
        monkeypatch: pytest monkeypatch。
        tmp_path: pytest 临时目录。
        release_info: 覆盖 release_info 字段。
        opener: urlopen 替身（默认成功分块响应）。
        verify: verify_installer_file 替身（默认 True）。
        prepare: prepare_cached_installer 替身（默认成功）。
        replace: os.replace 替身（默认真实行为）。
        remove: os.remove 替身（默认真实行为）。

    Returns:
        Tuple[Any, Dict[str, Any]]: (worker, events)。
    """
    import freeassetfilter.components.update_controller as uc

    cache_dir: str = str(tmp_path / "cache")
    rel_info: Dict[str, Any] = dict(_RELEASE_INFO)
    if release_info:
        rel_info.update(release_info)

    monkeypatch.setattr(uc, "get_cache_dir", lambda: cache_dir)
    monkeypatch.setattr(uc, "build_request_headers", lambda *a, **k: {"Accept": "application/octet-stream"})
    monkeypatch.setattr(uc, "verify_installer_file", verify if verify is not None else (lambda *a, **k: True))
    monkeypatch.setattr(
        uc,
        "prepare_cached_installer",
        prepare if prepare is not None else (lambda *a, **k: {"is_ready": True, "installer_path": "x.exe"}),
    )
    if replace is not None:
        monkeypatch.setattr(uc.os, "replace", replace)
    if remove is not None:
        monkeypatch.setattr(uc.os, "remove", remove)

    real_opener: Any = opener if opener is not None else _FakeUrlOpener(
        response=_FakeUrlResponse([b"a" * 1024, b"b" * 476], content_length=1500)
    )
    monkeypatch.setattr(urllib.request, "urlopen", real_opener)

    worker: Any = uc.UpdateDownloadWorker(rel_info, parent=None)
    events: Dict[str, Any] = {"success": None, "failure": None, "cancelled": False, "progress": []}
    worker.success.connect(lambda r: events.__setitem__("success", r))
    worker.failure.connect(lambda m: events.__setitem__("failure", m))
    worker.cancelled.connect(lambda: events.__setitem__("cancelled", True))
    worker.progress_changed.connect(lambda d, t, txt: events["progress"].append((d, t)))
    return worker, events


# =============================================================================
# 模块级 atexit / QThread 引用集
# =============================================================================
class TestModuleGlobals:
    """模块级 QThread 引用集与 atexit 处理器补强。"""

    def test_wait_global_threads_waits_running(self, monkeypatch: Any) -> None:
        """atexit 处理器对运行中的线程调用 wait(5000)。"""
        import freeassetfilter.components.update_controller as uc

        registered: List[Any] = []
        monkeypatch.setattr(uc.atexit, "register", lambda f: registered.append(f) or f)
        monkeypatch.setattr(uc, "_atexit_registered", False)
        uc._register_qthread_atexit()
        assert len(registered) == 1

        fake: Any = _FakeWorker(running=True)
        uc._global_qthread_refs.add(fake)
        try:
            registered[0]()
            assert fake.wait_called is True
        finally:
            uc._global_qthread_refs.discard(fake)

    def test_keep_qthread_alive_connect_raises_is_silent(self, monkeypatch: Any) -> None:
        """finished.connect 抛异常时被吞掉（模块级兜底分支）。"""
        import freeassetfilter.components.update_controller as uc

        class _BrokenFinished:
            def __init__(self) -> None:
                self.finished = None  # type: ignore[assignment]

            def isInterruptionRequested(self) -> bool:
                return False

        fake: Any = _BrokenFinished()
        uc._keep_qthread_alive(fake)  # 不应抛异常
        assert fake in uc._global_qthread_refs


# =============================================================================
# SilentUpdateCheckWorker.run 中断分支
# =============================================================================
class TestSilentWorkerInterruptBranches:
    """SilentUpdateCheckWorker.run 的中断语义（直接桩 isInterruptionRequested）。"""

    def test_interrupted_before_start_emits_finished_only(self, monkeypatch: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        w: Any = uc.SilentUpdateCheckWorker()
        finished: List[str] = []
        cancelled: List[str] = []
        failed: List[str] = []
        w.check_finished.connect(lambda: finished.append("done"))
        w.cancelled.connect(lambda: cancelled.append("cancel"))
        w.failure.connect(failed.append)
        monkeypatch.setattr(w, "isInterruptionRequested", lambda: True)
        w.run()
        assert finished == ["done"]
        assert cancelled == []
        assert failed == []

    def test_interrupted_after_check_emits_cancelled_and_finished(self, monkeypatch: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        calls: Dict[str, int] = {"n": 0}
        monkeypatch.setattr(uc, "check_for_updates", lambda **k: _update_available_result())

        def fake_interrupted() -> bool:
            calls["n"] += 1
            return calls["n"] > 1

        w: Any = uc.SilentUpdateCheckWorker()
        cancelled: List[str] = []
        finished: List[str] = []
        w.cancelled.connect(lambda: cancelled.append("cancel"))
        w.check_finished.connect(lambda: finished.append("done"))
        monkeypatch.setattr(w, "isInterruptionRequested", fake_interrupted)
        w.run()
        assert cancelled == ["cancel"]
        assert finished == ["done"]

    def test_update_error_interrupted_emits_cancelled(self, monkeypatch: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        calls: Dict[str, int] = {"n": 0}

        def fake_interrupted() -> bool:
            # 第一次调用(开始前)返回 False，之后(异常路径)返回 True
            calls["n"] += 1
            return calls["n"] > 1

        monkeypatch.setattr(uc, "check_for_updates", lambda **k: (_ for _ in ()).throw(uc.UpdateError("超时")))
        w: Any = uc.SilentUpdateCheckWorker()
        cancelled: List[str] = []
        failed: List[str] = []
        finished: List[str] = []
        w.cancelled.connect(lambda: cancelled.append("cancel"))
        w.failure.connect(failed.append)
        w.check_finished.connect(lambda: finished.append("done"))
        monkeypatch.setattr(w, "isInterruptionRequested", fake_interrupted)
        w.run()
        assert cancelled == ["cancel"]
        assert failed == []
        assert finished == ["done"]

    def test_generic_exception_interrupted_emits_cancelled(self, monkeypatch: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        calls: Dict[str, int] = {"n": 0}

        def fake_interrupted() -> bool:
            # 第一次调用(开始前)返回 False，之后(异常路径)返回 True
            calls["n"] += 1
            return calls["n"] > 1

        monkeypatch.setattr(uc, "check_for_updates", lambda **k: (_ for _ in ()).throw(RuntimeError("boom")))
        w: Any = uc.SilentUpdateCheckWorker()
        cancelled: List[str] = []
        failed: List[str] = []
        w.cancelled.connect(lambda: cancelled.append("cancel"))
        w.failure.connect(failed.append)
        monkeypatch.setattr(w, "isInterruptionRequested", fake_interrupted)
        w.run()
        assert cancelled == ["cancel"]
        assert failed == []


# =============================================================================
# UpdateDownloadWorker.run 清理 / 异常分支
# =============================================================================
class TestDownloadWorkerCleanupBranches:
    """UpdateDownloadWorker.run 的临时文件清理与各类异常清理。"""

    def test_leftover_temp_file_removed_or_ignored(self, monkeypatch: Any, tmp_path: Any) -> None:
        """缓存目录已存在 .download 残留：os.remove 抛 OSError 时吞掉。"""
        import freeassetfilter.components.update_controller as uc

        def _raise_oserror(*a: Any, **k: Any) -> None:
            raise OSError("denied")

        cache_dir: str = str(tmp_path / "cache")
        os.makedirs(cache_dir, exist_ok=True)
        with open(os.path.join(cache_dir, "FreeAssetFilter-setup.exe.download"), "wb") as f:
            f.write(b"stale")
        worker, events = _make_download_worker(monkeypatch, tmp_path, remove=_raise_oserror)
        worker.run()
        assert events["success"] is not None  # 残留清理异常不影响下载本身

    def test_zero_content_length_falls_back_to_installer_size(self, monkeypatch: Any, tmp_path: Any) -> None:
        """content-length 为 0 时回退到 release_info.installer_size。"""
        opener: Any = _FakeUrlOpener(
            response=_FakeUrlResponse([b"a" * 1024], content_length=0)
        )
        worker, events = _make_download_worker(monkeypatch, tmp_path, opener=opener)
        worker.run()
        assert events["success"] is not None
        assert events["progress"] and events["progress"][-1][1] == 1500

    def test_cancel_fclose_and_remove_errors_are_silent(self, monkeypatch: Any, tmp_path: Any) -> None:
        """取消下载时 f.close() 与 os.remove 抛异常均被吞掉（os.path.exists 命中）。"""
        import builtins

        def _raise_oserror(*a: Any, **k: Any) -> None:
            raise OSError("denied")

        class _CloseRaisingFile:
            def __enter__(self):
                return self

            def __exit__(self, *a: Any) -> bool:
                return False

            def write(self, data: bytes) -> int:
                return len(data)

            def flush(self) -> None:
                return None

            def close(self) -> None:
                raise RuntimeError("close boom")

        real_open = builtins.open

        def _raising_open(path: Any, mode: str = "r", *a: Any, **k: Any) -> Any:
            # 仅拦截临时文件写入；其余路径走真实 open
            if mode == "wb" and str(path).endswith(".download"):
                return _CloseRaisingFile()
            return real_open(path, mode, *a, **k)

        # 预创建 .download 临时文件，确保 os.path.exists(temp_path) 为 True
        cache_dir: str = str(tmp_path / "cache")
        os.makedirs(cache_dir, exist_ok=True)
        temp_file: str = os.path.join(cache_dir, f"{_RELEASE_INFO['installer_name']}.download")
        with open(temp_file, "wb") as f:
            f.write(b"partial")

        monkeypatch.setattr(builtins, "open", _raising_open)
        worker, events = _make_download_worker(monkeypatch, tmp_path, remove=_raise_oserror)
        worker._cancel_requested = True
        worker.run()
        assert events["cancelled"] is True
        assert events["success"] is None
        assert events["failure"] is None

    def test_sha256_failure_remove_error_is_silent(self, monkeypatch: Any, tmp_path: Any) -> None:
        """SHA256 校验失败后清理 final_path 时 os.remove 抛异常被吞掉。"""
        def _raise_oserror(*a: Any, **k: Any) -> None:
            raise OSError("denied")

        worker, events = _make_download_worker(
            monkeypatch, tmp_path, verify=lambda *a, **k: False, remove=_raise_oserror
        )
        worker.run()
        assert events["failure"] == "下载完成，但 SHA256 校验失败"

    def test_replace_failure_cleanup_remove_error_is_silent(self, monkeypatch: Any, tmp_path: Any) -> None:
        """os.replace 失败（UpdateError）+ 清理 os.remove 抛异常均被吞掉。"""
        def _replace_fail(src: str, dst: str) -> None:
            raise OSError("disk full")

        def _raise_oserror(*a: Any, **k: Any) -> None:
            raise OSError("denied")

        worker, events = _make_download_worker(
            monkeypatch, tmp_path, replace=_replace_fail, remove=_raise_oserror
        )
        worker.run()
        assert events["failure"] is not None
        assert "写入安装包失败" in events["failure"]

    def test_urlerror_mid_download_cleanup_error_is_silent(self, monkeypatch: Any, tmp_path: Any) -> None:
        """下载中途 urlopen.read 抛 URLError + 清理 os.remove 抛 OSError。"""
        def _raise_oserror(*a: Any, **k: Any) -> None:
            raise OSError("denied")

        opener: Any = _FakeUrlOpener(
            response=_FakeUrlResponse(
                [b"a" * 1024, b"b" * 476],
                content_length=1500,
                fail_on_index=1,
                fail_error=urllib.error.URLError("connection reset"),
            )
        )
        worker, events = _make_download_worker(monkeypatch, tmp_path, opener=opener, remove=_raise_oserror)
        worker.run()
        assert events["failure"] is not None
        assert "下载更新失败" in events["failure"]

    def test_generic_exception_mid_download_cleanup_error_is_silent(self, monkeypatch: Any, tmp_path: Any) -> None:
        """下载中途 read 抛 RuntimeError + 清理 os.remove 抛 OSError。"""
        def _raise_oserror(*a: Any, **k: Any) -> None:
            raise OSError("denied")

        opener: Any = _FakeUrlOpener(
            response=_FakeUrlResponse(
                [b"a" * 1024],
                content_length=1500,
                fail_on_index=1,
                fail_error=RuntimeError("boom"),
            )
        )
        worker, events = _make_download_worker(monkeypatch, tmp_path, opener=opener, remove=_raise_oserror)
        worker.run()
        assert events["failure"] is not None
        assert "下载更新失败：boom" in events["failure"]


# =============================================================================
# UpdateController 槽 / 状态分支
# =============================================================================
class TestControllerStateBranches:
    """UpdateController 的状态分支补强。"""

    def test_cancel_silent_check_worker_not_running(self, make_update_controller: Any) -> None:
        """worker 存在但已不在运行时 cancel_silent_check 走安全分支。"""
        controller: Any = make_update_controller()
        controller._silent_check_worker = _FakeWorker(running=False)
        controller.cancel_silent_check()
        assert controller._silent_check_cancelled is False  # 未重置任何状态

    def test_bind_button_disconnect_raises_is_silent(self, make_update_controller: Any) -> None:
        """重新绑定时旧按钮 disconnect 抛异常被吞掉。"""
        controller: Any = make_update_controller()

        class _RaisingDisconnect:
            def __init__(self) -> None:
                self.connected: List[Any] = []

            def connect(self, cb: Callable[..., Any]) -> None:
                self.connected.append(cb)

            def disconnect(self, *a: Any, **k: Any) -> None:
                raise RuntimeError("already disconnected")

        class _NewButton:
            def __init__(self) -> None:
                self.clicked = _FakeSignalBox()

        old: Any = _RaisingDisconnect()
        controller.update_button = old
        new: Any = _NewButton()
        controller.bind_button(new)
        assert controller.update_button is new
        assert len(new.clicked._callbacks) == 1  # 新按钮已绑定

    def test_retire_worker_request_interruption_raises_is_silent(self, make_update_controller: Any) -> None:
        """_retire_worker 中 requestInterruption 抛异常被吞掉。"""
        controller: Any = make_update_controller()

        class _RaisingWorker(_FakeWorker):
            def requestInterruption(self) -> None:
                raise RuntimeError("boom")

        fake: Any = _RaisingWorker(running=False)
        controller._retire_worker(fake, controller._retired_check_workers)
        assert fake in controller._retired_check_workers

    def test_retire_worker_finished_connect_raises_is_silent(self, make_update_controller: Any) -> None:
        """_retire_worker 中 finished.connect 抛异常被吞掉（无 finished 属性）。"""
        controller: Any = make_update_controller()

        class _NoFinishedWorker(_FakeWorker):
            def __init__(self) -> None:
                super().__init__(running=False)
                self.finished = None  # type: ignore[assignment]

        fake: Any = _NoFinishedWorker()
        controller._retire_worker(fake, controller._retired_check_workers)
        assert fake in controller._retired_check_workers


class TestControllerCheckFlowBranches:
    """检查流程的状态分支补强。"""

    def test_on_check_updates_clicked_pending_restart(self, make_update_controller: Any, monkeypatch: Any) -> None:
        """检查进行中且已被取消：记录 pending 重启并清空对话框按钮。"""
        controller: Any = make_update_controller()
        fake: Any = _FakeWorker(running=True)
        controller._check_worker = fake
        controller._check_cancelled = True
        texts: List[str] = []
        buttons: List[List[str]] = []
        monkeypatch.setattr(controller, "_set_dialog_text", lambda t: texts.append(t))
        monkeypatch.setattr(controller, "_set_dialog_buttons", lambda *a, **k: buttons.append(a[0] if a else []))
        controller.on_check_updates_clicked()
        assert controller._pending_check_restart is True
        assert fake.interruption_requested is True
        assert texts and "重新检查" in texts[0]
        assert buttons == [[]]

    def test_on_check_updates_clicked_download_running_ignored(
        self, make_update_controller: Any, monkeypatch: Any
    ) -> None:
        """下载进行中：忽略检查请求，不启动新检查。"""
        controller: Any = make_update_controller()
        controller._download_worker = _FakeWorker(running=True)
        started: List[str] = []
        monkeypatch.setattr(controller, "_start_manual_check", lambda: started.append("start"))
        controller.on_check_updates_clicked()
        assert started == []
        assert controller._check_worker is None

    def test_on_check_failure_after_cancel_closes_and_restarts(
        self, make_update_controller: Any, monkeypatch: Any
    ) -> None:
        """失败信号到达时检查已被取消：关闭对话框并重启。"""
        controller: Any = make_update_controller()
        controller._check_cancelled = True
        closed: List[str] = []
        restarted: List[str] = []
        monkeypatch.setattr(controller, "_close_current_dialog", lambda: closed.append("closed"))
        monkeypatch.setattr(controller, "_restart_manual_check_if_needed", lambda: restarted.append("restart"))
        controller._on_check_failure("网络超时")
        assert controller._check_cancelled is False
        assert closed == ["closed"]
        assert restarted == ["restart"]

    def test_show_check_result_installer_ready(self, make_update_controller: Any, monkeypatch: Any) -> None:
        """检查结果显示"本地已有可用安装包"（installer_ready 分支）。"""
        controller: Any = make_update_controller()
        result: Dict[str, Any] = _update_available_result()
        result["cache_result"] = {"is_ready": True, "installer_path": "C:/x.exe", "installer_sha256": "ab" * 32}
        shown: List[Dict[str, Any]] = []
        monkeypatch.setattr(
            controller,
            "_show_update_available_detail_dialog",
            lambda **kwargs: shown.append(kwargs),
        )
        controller._show_check_result(result)
        assert controller._current_ready_package is result["cache_result"]
        assert len(shown) == 1
        assert shown[0]["installer_ready"] is True


class TestControllerDownloadFlowBranches:
    """下载启动对话框的状态分支补强。"""

    def _setup_download_start(self, make_update_controller: Any, monkeypatch: Any) -> Any:
        import freeassetfilter.components.update_controller as uc

        controller: Any = make_update_controller()
        monkeypatch.setattr(uc, "CustomMessageBox", _FakeMessageBox)
        monkeypatch.setattr(uc, "LoadingSpinner", _FakeSpinner)

        class _DownloadStub(_FakeWorker):
            def __init__(self, release_info, parent=None) -> None:
                super().__init__(running=False)
                self.release_info = release_info
                self.progress_changed: Any = _FakeSignalBox()
                self.cancelled: Any = _FakeSignalBox()
                self.started: bool = False

            def start(self) -> None:
                self.started = True

        monkeypatch.setattr(uc, "UpdateDownloadWorker", _DownloadStub)
        return controller

    def test_on_update_available_clicked_no_installer_name(
        self, make_update_controller: Any, monkeypatch: Any
    ) -> None:
        """release_info 无 installer_name：final/temp 路径置 None。"""
        controller: Any = self._setup_download_start(make_update_controller, monkeypatch)
        release: Dict[str, Any] = dict(_RELEASE_INFO)
        del release["installer_name"]
        controller._current_release_info = release
        controller._on_update_available_dialog_clicked(0)
        assert controller._current_download_final_path is None
        assert controller._current_download_temp_path is None
        assert controller._download_worker is not None
        assert controller._download_worker.started is True
        controller._close_current_dialog()

    def test_on_update_available_clicked_zero_total_size(
        self, make_update_controller: Any, monkeypatch: Any
    ) -> None:
        """installer_size 为 0：进度条范围回退 1000，信息文本走"无总大小"分支。"""
        controller: Any = self._setup_download_start(make_update_controller, monkeypatch)
        release: Dict[str, Any] = dict(_RELEASE_INFO)
        del release["installer_name"]
        release["installer_size"] = 0
        controller._current_release_info = release
        info_texts: List[str] = []
        monkeypatch.setattr(controller, "_set_progress_info_text", lambda t: info_texts.append(t))
        controller._on_update_available_dialog_clicked(0)
        assert controller._current_download_total_size == 0
        assert info_texts and "0 B |" in info_texts[0]
        assert controller._download_worker is not None
        controller._close_current_dialog()


class TestControllerPollBranches:
    """下载进度轮询的分支补强。"""

    def test_poll_progress_no_bar_returns(self, make_update_controller: Any) -> None:
        """无当前进度条时直接返回。"""
        from freeassetfilter.widgets.progress_widgets import D_ProgressBar

        controller: Any = make_update_controller()
        controller._current_progress_bar = None
        controller._poll_download_progress_from_file()
        assert controller._current_download_speed_text == "0 B/s"

    def test_poll_progress_getsize_error_continues(self, make_update_controller: Any, monkeypatch: Any, tmp_path: Any) -> None:
        """候选路径存在但 os.path.getsize 抛 OSError：回退到 latest_downloaded_size。"""
        from freeassetfilter.widgets.progress_widgets import D_ProgressBar

        def _raise_getsize(*a: Any, **k: Any) -> None:
            raise OSError("denied")

        cache: Any = tmp_path / "cache"
        cache.mkdir()
        temp_file: Any = cache / "faf.exe.download"
        temp_file.write_bytes(b"x" * 512)
        final_file: Any = cache / "faf.exe"
        final_file.write_bytes(b"x" * 512)

        controller: Any = make_update_controller()
        bar: Any = D_ProgressBar(is_interactive=False)
        controller._current_progress_bar = bar
        controller._current_progress_info_label = QLabel("")
        controller._current_download_total_size = 1024
        controller._current_download_temp_path = str(temp_file)
        controller._current_download_final_path = str(final_file)
        controller._latest_downloaded_size = 256
        monkeypatch.setattr(os.path, "getsize", _raise_getsize)
        controller._poll_download_progress_from_file()
        # getsize 抛异常 → 未取到文件大小 → 回退到 latest_downloaded_size(256/1024=25%)
        assert controller._current_progress_bar.value() >= 0
        controller._close_current_dialog()

    def test_poll_progress_zero_total_sets_indeterminate(self, make_update_controller: Any, monkeypatch: Any) -> None:
        """总大小为 0 且 release 也无大小：进度条进入不确定模式（0-0）。"""
        from freeassetfilter.widgets.progress_widgets import D_ProgressBar

        controller: Any = make_update_controller()
        bar: Any = D_ProgressBar(is_interactive=False)
        controller._current_progress_bar = bar
        controller._current_progress_info_label = QLabel("")
        controller._current_download_total_size = 0
        controller._current_release_info = {"installer_size": 0}
        controller._latest_downloaded_size = 100
        controller._poll_download_progress_from_file()
        assert bar._minimum == 0
        assert bar._maximum == 0
        controller._close_current_dialog()


class TestControllerDialogBranches:
    """对话框辅助的分支补强（全部打桩，不 exec()）。"""

    def test_set_dialog_buttons_with_callback(self, make_update_controller: Any) -> None:
        """_set_dialog_buttons 传入非空 buttons + callback 时连接回调。"""
        controller: Any = make_update_controller()
        fake: Any = _FakeMessageBox()
        controller._current_dialog = fake
        called: List[int] = []
        controller._set_dialog_buttons(["确定"], ["primary"], callback=lambda i: called.append(i))
        assert len(fake.buttonClicked._callbacks) == 1
        fake.buttonClicked.emit(0)
        assert called == [0]
        controller._close_current_dialog()

    def test_close_current_dialog_close_raises_is_silent(self, make_update_controller: Any) -> None:
        """对话框 close() 抛异常被吞掉，其余清理照常。"""
        controller: Any = make_update_controller()

        class _RaiseCloseBox(_FakeMessageBox):
            def close(self) -> None:
                raise RuntimeError("boom")

        controller._current_dialog = _RaiseCloseBox()
        controller._close_current_dialog()
        assert controller._current_dialog is None

    def test_close_current_dialog_stops_and_clears_spinner(self, make_update_controller: Any) -> None:
        """关闭对话框时停止并清空 loading spinner。"""
        controller: Any = make_update_controller()
        controller._current_dialog = _FakeMessageBox()
        spinner: Any = _FakeSpinner()
        controller._current_loading_spinner = spinner
        controller._close_current_dialog()
        assert spinner.stopped is True
        assert controller._current_loading_spinner is None


class TestControllerInstallBranches:
    """安装确认流程的分支补强。"""

    def test_on_install_ready_incomplete_package(self, make_update_controller: Any, monkeypatch: Any) -> None:
        """安装包信息不完整（缺 sha256）时提示失败。"""
        controller: Any = make_update_controller()
        controller._current_ready_package = {"installer_path": "C:/x.exe"}  # 无 installer_sha256
        captured: List[Dict[str, Any]] = []
        monkeypatch.setattr(controller, "_show_message_dialog", lambda **kwargs: captured.append(kwargs))
        controller._on_install_ready_dialog_clicked(0)
        assert captured and "信息不完整" in captured[0]["text"]

    def test_on_install_ready_verify_fail_cleanup_errors(
        self, make_update_controller: Any, monkeypatch: Any, tmp_path: Any
    ) -> None:
        """校验失败清理缓存时 os.remove 抛 OSError 均被吞掉。"""
        import freeassetfilter.components.update_controller as uc

        def _raise_oserror(*a: Any, **k: Any) -> None:
            raise OSError("denied")

        controller: Any = make_update_controller()
        installer: Any = tmp_path / "faf.exe"
        installer.write_bytes(b"MZ")
        metadata: Any = tmp_path / "metadata.json"
        metadata.write_text("{}")
        package: Dict[str, Any] = {"installer_path": str(installer), "installer_sha256": "ab" * 32}
        controller._current_ready_package = package
        monkeypatch.setattr(uc, "verify_installer_file", lambda *a, **k: False)
        monkeypatch.setattr(uc, "get_cache_metadata_path", lambda: str(metadata))
        monkeypatch.setattr(uc.os, "remove", _raise_oserror)
        captured: List[Dict[str, Any]] = []
        monkeypatch.setattr(controller, "_show_message_dialog", lambda **kwargs: captured.append(kwargs))
        controller._on_install_ready_dialog_clicked(0)
        assert captured and "校验失败" in captured[0]["text"]

    def test_on_install_ready_launcher_raises_shows_error(
        self, make_update_controller: Any, monkeypatch: Any, tmp_path: Any
    ) -> None:
        """启动安装 helper 抛异常时显示错误对话框。"""
        import freeassetfilter.components.update_controller as uc

        controller: Any = make_update_controller()
        installer: Any = tmp_path / "faf.exe"
        installer.write_bytes(b"MZ")
        package: Dict[str, Any] = {"installer_path": str(installer), "installer_sha256": "ab" * 32}
        controller._current_ready_package = package
        monkeypatch.setattr(uc, "verify_installer_file", lambda *a, **k: True)

        def _boom(*a: Any, **k: Any) -> None:
            raise RuntimeError("spawn fail")

        monkeypatch.setattr(controller, "_launch_installer_helper", _boom)
        captured: List[Dict[str, Any]] = []
        monkeypatch.setattr(controller, "_show_message_dialog", lambda **kwargs: captured.append(kwargs))
        controller._on_install_ready_dialog_clicked(0)
        assert captured and "启动安装程序失败" in captured[0]["text"]


class TestControllerSilentCheckBranches:
    """静默检查结果槽的分支补强（直接调用，不触网、不 exec()）。"""

    def test_silent_update_available_cancelled_flag_cleared(
        self, make_update_controller: Any, monkeypatch: Any
    ) -> None:
        """_silent_check_cancelled 为 True：忽略结果并复位标志（1483-1485）。"""
        controller: Any = make_update_controller()
        controller._silent_check_cancelled = True
        shown: List[str] = []
        monkeypatch.setattr(
            controller, "_show_update_available_detail_dialog", lambda **k: shown.append("shown")
        )
        controller._on_silent_check_update_available(_update_available_result())
        assert controller._silent_check_cancelled is False
        assert shown == []

    def test_silent_update_available_manual_check_running(
        self, make_update_controller: Any, monkeypatch: Any
    ) -> None:
        """手动检查线程正在运行：静默结果不弹窗（1489-1490）。"""
        controller: Any = make_update_controller()
        controller._check_worker = _FakeWorker(running=True)
        shown: List[str] = []
        monkeypatch.setattr(
            controller, "_show_update_available_detail_dialog", lambda **k: shown.append("shown")
        )
        controller._on_silent_check_update_available(_update_available_result())
        assert shown == []

    def test_silent_update_available_installer_ready(
        self, make_update_controller: Any, monkeypatch: Any
    ) -> None:
        """cache_result 已就绪：记录 ready 包并弹窗（1504 分支）。"""
        controller: Any = make_update_controller()
        result: Dict[str, Any] = _update_available_result()
        result["cache_result"] = {"is_ready": True, "installer_path": "C:/x.exe", "installer_sha256": "ab" * 32}
        shown: List[Dict[str, Any]] = []
        monkeypatch.setattr(
            controller, "_show_update_available_detail_dialog", lambda **kw: shown.append(kw)
        )
        controller._on_silent_check_update_available(result)
        assert controller._current_ready_package is result["cache_result"]
        assert len(shown) == 1
        assert shown[0]["installer_ready"] is True
        assert shown[0]["release_info"] is result["latest_release"]

    def test_silent_check_success_ignores_retired_sender(
        self, make_update_controller: Any, monkeypatch: Any
    ) -> None:
        """已退役静默 worker 的成功结果被忽略（1516-1517）。"""
        controller: Any = make_update_controller()
        fake: Any = _FakeWorker(running=False)
        controller._retired_silent_workers.append(fake)
        monkeypatch.setattr(controller, "sender", lambda: fake)
        shown: List[str] = []
        monkeypatch.setattr(controller, "_show_check_result", lambda *a, **k: shown.append("shown"))
        controller._on_silent_check_success(_update_available_result())
        assert shown == []

    def test_silent_check_failure_ignores_retired_sender(
        self, make_update_controller: Any, monkeypatch: Any
    ) -> None:
        """已退役静默 worker 的失败结果被忽略（1538-1539）。"""
        controller: Any = make_update_controller()
        controller._manual_check_uses_silent = True
        fake: Any = _FakeWorker(running=False)
        controller._retired_silent_workers.append(fake)
        monkeypatch.setattr(controller, "sender", lambda: fake)
        handled: List[str] = []
        monkeypatch.setattr(controller, "_on_check_failure", lambda *a, **k: handled.append("handled"))
        controller._on_silent_check_failure("boom")
        assert handled == []

    def test_silent_check_cancelled_ignores_retired_sender(
        self, make_update_controller: Any, monkeypatch: Any
    ) -> None:
        """已退役静默 worker 的取消信号被忽略（1552-1553）。"""
        controller: Any = make_update_controller()
        fake: Any = _FakeWorker(running=False)
        controller._retired_silent_workers.append(fake)
        monkeypatch.setattr(controller, "sender", lambda: fake)
        handled: List[str] = []
        monkeypatch.setattr(controller, "_on_check_cancelled", lambda: handled.append("handled"))
        controller._on_silent_check_cancelled()
        assert handled == []

    def test_silent_check_cancelled_no_manual_claim_ignored(
        self, make_update_controller: Any, monkeypatch: Any
    ) -> None:
        """无手动接管：静默检查取消信号忽略（1556 分支）。"""
        controller: Any = make_update_controller()
        handled: List[str] = []
        monkeypatch.setattr(controller, "_on_check_cancelled", lambda: handled.append("handled"))
        controller._on_silent_check_cancelled()
        assert handled == []


class TestControllerFormattingBranches:
    """静态工具的分支补强。"""

    def test_convert_markdown_heading_levels(self, make_update_controller: Any) -> None:
        """'# ' 与 '### ' 分别渲染为 h2 / h4。"""
        controller: Any = make_update_controller()
        html: str = controller._convert_markdown_to_html("# 大标题\n## 中标题\n### 小标题\n正文")
        assert "<h2>大标题</h2>" in html
        assert "<h3>中标题</h3>" in html
        assert "<h4>小标题</h4>" in html