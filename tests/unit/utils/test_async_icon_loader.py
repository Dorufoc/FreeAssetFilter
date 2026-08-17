# -*- coding: utf-8 -*-
"""async_icon_loader.py（freeassetfilter/utils/async_icon_loader.py）单元测试。

覆盖回调生命周期（requester 被 GC 后回调仍完成）、多线程并发 load_icon、
``_callbacks`` / ``_runnables`` 完成后无泄漏、取消（cancel_load/clear）后
回调不再触发，以及 runnable 的 **finally 中 HICON 释放**（hicon_to_pixmap
抛异常时 DestroyIcon 仍被调用）。Windows Shell 相关调用一律用 monkeypatch
桩替掉，保证测试确定、快速、无真实系统副作用。
"""

from __future__ import annotations

import gc
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import pytest
from PySide6.QtWidgets import QApplication

from freeassetfilter.utils import async_icon_loader as ail

pytestmark = pytest.mark.unit


def _spin_until(
    condition: Callable[[], bool],
    timeout: float = 8.0,
    period: float = 0.02,
) -> bool:
    """有界地泵 Qt 事件直到条件成立或超时。

    Args:
        condition: 返回真值即为完成的条件函数。
        timeout: 最长等待秒数。
        period: 每次泵事件的间隔秒数。

    Returns:
        bool: 超时前成立返回 True，否则 False。
    """
    app: Optional[QApplication] = QApplication.instance()  # type: ignore[assignment]
    deadline: float = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        if app is not None:
            app.processEvents()
        time.sleep(period)
    if app is not None:
        app.processEvents()
    return bool(condition())


def _install_fast_icon_patch(monkeypatch: Any) -> None:
    """把缓存/Shell 图标获取全部桩为快速返回，避免真实系统调用。"""
    monkeypatch.setattr(ail, "get_cached_icon_path", lambda _p: "")
    monkeypatch.setattr(ail, "get_highest_resolution_icon", lambda _p: None)


class TestSingleton:
    """模块级单例语义。"""

    def test_instance_returns_same_object(self) -> None:
        """instance() 幂等返回同一实例。"""
        first = ail.AsyncIconLoader.instance()
        try:
            second = ail.AsyncIconLoader.instance()
            assert first is second
        finally:
            first.clear()


class TestCallbackLifecycle:
    """回调生命周期与 _callbacks 清理。"""

    def test_callback_survives_requester_gc(
        self, qapp: Any, monkeypatch: Any
    ) -> None:
        """释放 requester 引用后回调仍完成（loader 持有强引用）。"""
        _install_fast_icon_patch(monkeypatch)
        called: Dict[str, Any] = {}

        class _Requester:
            def __init__(self, path: str) -> None:
                self.path = path

            def on_result(self, path: str, pixmap: Optional[Any]) -> None:
                called["path"] = path
                called["pixmap"] = pixmap

        loader = ail.AsyncIconLoader()
        requester = _Requester("gc_file.png")
        loader.load_icon("gc_file.png", requester.on_result)
        del requester
        gc.collect()

        assert _spin_until(lambda: "path" in called), "回调应在 GC 后仍完成"
        assert called["path"] == "gc_file.png"
        assert called["pixmap"] is None
        # 完成后 dict 不泄漏
        assert "gc_file.png" not in loader._callbacks
        assert "gc_file.png" not in loader._runnables

    def test_success_path_cleans_dicts(
        self, qapp: Any, monkeypatch: Any
    ) -> None:
        """正常完成路径：回调收到结果，_callbacks/_runnables 清空。"""
        _install_fast_icon_patch(monkeypatch)
        received: List[str] = []
        loader = ail.AsyncIconLoader()
        loader.load_icon("ok.png", lambda p, pix: received.append(p))
        assert _spin_until(lambda: bool(received))
        assert received == ["ok.png"]
        assert loader._callbacks == {}
        assert loader._runnables == {}

    def test_load_icon_same_path_uses_latest_callback(
        self, qapp: Any, monkeypatch: Any
    ) -> None:
        """同一路径重复 load：首个回调被取消，只执行最新回调。"""
        monkeypatch.setattr(ail, "get_cached_icon_path", lambda _p: "")
        monkeypatch.setattr(
            ail, "get_highest_resolution_icon", lambda _p: time.sleep(0.3) or None
        )
        called: List[str] = []
        loader = ail.AsyncIconLoader()
        loader.load_icon("dup.png", lambda p, pix: called.append("first"))
        loader.load_icon("dup.png", lambda p, pix: called.append("second"))
        assert _spin_until(lambda: bool(called))
        assert called == ["second"]
        assert loader._callbacks == {}


class TestConcurrency:
    """多线程并发 load_icon。"""

    def test_concurrent_load_from_threads(
        self, qapp: Any, monkeypatch: Any
    ) -> None:
        """6 个线程各自发起加载，全部回调都完成且路径正确。"""
        _install_fast_icon_patch(monkeypatch)
        loader = ail.AsyncIconLoader()
        results: Dict[str, Any] = {}
        errors: List[BaseException] = []

        def _task(path: str) -> None:
            try:
                loader.load_icon(path, lambda p, pix: results.__setitem__(p, pix))
            except BaseException as exc:  # pragma: no cover - 并发容错
                errors.append(exc)

        paths = [f"concurrent_file_{i}.png" for i in range(6)]
        threads = [threading.Thread(target=_task, args=(p,)) for p in paths]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert _spin_until(lambda: len(results) == 6)
        assert not errors
        assert set(results) == set(paths)
        assert all(v is None for v in results.values())
        assert loader._callbacks == {}
        assert loader._runnables == {}


class TestCancellation:
    """取消语义与 HICON finally 释放。"""

    def test_cancel_load_prevents_callback(
        self, qapp: Any, monkeypatch: Any
    ) -> None:
        """cancel_load 后已排队的任务不再触达回调。"""
        monkeypatch.setattr(ail, "get_cached_icon_path", lambda _p: "")
        monkeypatch.setattr(
            ail, "get_highest_resolution_icon", lambda _p: time.sleep(0.4) or None
        )
        called: List[str] = []
        loader = ail.AsyncIconLoader()
        loader.load_icon("slow.png", lambda p, pix: called.append(p))
        loader.cancel_load("slow.png")
        assert "slow.png" not in loader._callbacks
        assert "slow.png" not in loader._runnables
        assert _spin_until(lambda: bool(called), timeout=1.5) is False

    def test_clear_removes_all_pending(
        self, qapp: Any, monkeypatch: Any
    ) -> None:
        """clear() 取消全部任务并清空两张表。"""
        monkeypatch.setattr(ail, "get_cached_icon_path", lambda _p: "")
        monkeypatch.setattr(
            ail, "get_highest_resolution_icon", lambda _p: time.sleep(0.4) or None
        )
        called: List[str] = []
        loader = ail.AsyncIconLoader()
        loader.load_icon("slow_a.png", lambda p, pix: called.append(p))
        loader.load_icon("slow_b.png", lambda p, pix: called.append(p))
        loader.clear()
        assert loader._callbacks == {}
        assert loader._runnables == {}
        assert _spin_until(lambda: bool(called), timeout=1.5) is False

    def test_runnable_releases_hicon_in_finally_on_error(
        self, qapp: Any, monkeypatch: Any
    ) -> None:
        """hicon_to_pixmap 抛异常时 finally 仍释放 HICON。

        AGENTS.md 的 QRunnable + finally 清理模式：即使图标加工中途失败，
        ``DestroyIcon(hicon)`` 也必须在 finally 中执行，句柄不得泄漏。
        """
        fake_hicon = object()
        released: List[object] = []

        def _boom(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("forced icon processing failure")

        monkeypatch.setattr(ail, "get_cached_icon_path", lambda _p: "")
        monkeypatch.setattr(
            ail, "get_highest_resolution_icon", lambda _p: fake_hicon
        )
        monkeypatch.setattr(ail, "hicon_to_pixmap", _boom)
        monkeypatch.setattr(
            ail, "DestroyIcon", lambda h: released.append(h) or True
        )

        received: Dict[str, Any] = {}
        loader = ail.AsyncIconLoader()
        loader.load_icon("boom.png", lambda p, pix: received.__setitem__("done", True))
        assert _spin_until(lambda: bool(received))
        assert released == [fake_hicon], "异常路径下 HICON 仍应在 finally 释放"
        assert loader._callbacks == {}