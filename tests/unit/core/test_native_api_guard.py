# -*- coding: utf-8 -*-
"""native 门面 X6 主线程 FFI 守卫测试。

锁定三条契约：

1. 主线程单次 FFI 超预算 → 记一条 ``ui.main_thread_block`` 时长样本；
2. 未超预算 / 非主线程 / 守卫关闭 → 零样本零计数；
3. 守卫本身不得改变 native 返回値，也不得向上抛异常。

验证命令：
    python -m pytest tests/unit/core/test_native_api_guard.py -v
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

import pytest

from freeassetfilter.core.native import api as native_api
from freeassetfilter.utils import perf_metrics

pytestmark = pytest.mark.unit


class _FakeBridge:
    """最小的桥替身：``scan_directory`` 可控耗时并返回固定列表。"""

    def __init__(self, sleep_s: float = 0.0) -> None:
        self.available = True
        self._supports_scan = True
        self._sleep_s = sleep_s

    def scan_directory(self, path: str) -> Optional[List[Dict[str, Any]]]:
        import time

        if self._sleep_s:
            time.sleep(self._sleep_s)
        return [{"name": path}]


@pytest.fixture()
def fake_bridge(monkeypatch: pytest.MonkeyPatch) -> Any:
    """把门面的 ``bridge`` 替换为可注入耗时的替身。"""
    holder: Dict[str, _FakeBridge] = {"inst": _FakeBridge()}

    def _bridge() -> _FakeBridge:
        return holder["inst"]

    monkeypatch.setattr(native_api, "bridge", _bridge)
    return holder


def _block_stats() -> Dict[str, Any]:
    """读 ``ui.main_thread_block`` 的聚合统计（经全局快照，不触内部结构）。"""
    snapshot = perf_metrics.get_perf_snapshot()
    return (snapshot.get("events") or {}).get("ui.main_thread_block") or {}


def _block_samples() -> List[float]:
    """兼容旧断言的样本计数（元素值无意义，只看长度）。"""
    return [0.0] * int(_block_stats().get("sample_count", 0) or 0)


def test_slow_main_thread_ffi_records_block_sample(
    fake_bridge: Dict[str, _FakeBridge],
) -> None:
    """主线程 FFI 超预算 → 记一条 ``ui.main_thread_block``。"""
    before = len(_block_samples())
    fake_bridge["inst"] = _FakeBridge(sleep_s=0.02)  # 20ms > 5ms 预算
    rows = native_api.scan_directory("C:/x")
    assert rows == [{"name": "C:/x"}]
    samples = _block_samples()
    assert len(samples) == before + 1
    assert float(_block_stats().get("max_ms", 0.0)) >= 5.0


def test_fast_main_thread_ffi_records_nothing(
    fake_bridge: Dict[str, _FakeBridge],
) -> None:
    """未超预算 → 零样本（不污染 P99）。"""
    before = len(_block_samples())
    fake_bridge["inst"] = _FakeBridge(sleep_s=0.0)
    assert native_api.scan_directory("C:/y") == [{"name": "C:/y"}]
    assert len(_block_samples()) == before


def test_worker_thread_ffi_records_nothing(
    fake_bridge: Dict[str, _FakeBridge],
) -> None:
    """非主线程即使较慢也不记 ``ui.main_thread_block``（只关心 UI 线程）。"""
    before = len(_block_samples())
    fake_bridge["inst"] = _FakeBridge(sleep_s=0.02)
    result: List[Any] = []

    def _worker() -> None:
        result.append(native_api.scan_directory("C:/z"))

    thread = threading.Thread(target=_worker)
    thread.start()
    thread.join()
    assert result == [[{"name": "C:/z"}]]
    assert len(_block_samples()) == before


def test_guard_can_be_disabled(
    fake_bridge: Dict[str, _FakeBridge], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_MAIN_THREAD_GUARD=False`` 时完全不测量。"""
    monkeypatch.setattr(native_api, "_MAIN_THREAD_GUARD", False)
    before = len(_block_samples())
    fake_bridge["inst"] = _FakeBridge(sleep_s=0.02)
    assert native_api.scan_directory("C:/w") == [{"name": "C:/w"}]
    assert len(_block_samples()) == before


def test_note_cost_ignores_non_main_thread() -> None:
    """直接调用埋点函数：工作线程不记录。"""
    before = len(_block_samples())
    done = threading.Event()

    def _worker() -> None:
        native_api._note_main_thread_cost("scan", 0.5)
        done.set()

    thread = threading.Thread(target=_worker)
    thread.start()
    assert done.wait(2.0)
    assert len(_block_samples()) == before
