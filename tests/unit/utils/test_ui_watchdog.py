# -*- coding: utf-8 -*-
"""主线程卡顿哨兵测试（P6.1）。

锁定四条契约：

1. 默认关闭时 ``install()`` **不创建** QTimer / 线程（零开销）；
2. 开启后主线程被阻塞能记录卡顿，并在卡顿窗口内做栈归因；
3. ``perf_metrics`` 的 provider 段可扩展，单个 provider 异常被隔离；
4. ``uninstall()`` 幂等且回收采样线程。

验证命令：
    python -m pytest tests/unit/utils/test_ui_watchdog.py -v
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication

from freeassetfilter.utils import perf_metrics as pm
from freeassetfilter.utils import ui_watchdog as wd

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_watchdog() -> Any:
    """每个用例前后确保哨兵已卸载。"""
    wd.uninstall()
    yield
    wd.uninstall()


def test_disabled_is_noop(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    """未设置 FAF_UI_WATCHDOG 时不创建任何探针或线程。"""
    monkeypatch.delenv("FAF_UI_WATCHDOG", raising=False)
    before = threading.active_count()

    assert wd.install(qapp) is None
    assert wd.get_watchdog() is None
    assert threading.active_count() == before
    assert qapp.findChildren(wd.UiWatchdog) == []


def test_enabled_records_stall_with_stack(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """主线程阻塞 450ms → 记录一次卡顿并带栈归因。"""
    monkeypatch.setenv("FAF_UI_WATCHDOG", "1")
    monkeypatch.setenv("FAF_UI_WATCHDOG_INTERVAL_MS", "100")
    monkeypatch.setenv("FAF_UI_WATCHDOG_STALL_MS", "200")
    monkeypatch.setenv("FAF_UI_WATCHDOG_STACK_MS", "10")

    watchdog = wd.install(qapp)
    assert watchdog is not None

    # 阻塞主线程但不触发事件循环 → 下一次 tick 必然迟到。
    time.sleep(0.45)
    qapp.processEvents()
    time.sleep(0.05)
    qapp.processEvents()

    snapshot = watchdog.provider()
    assert snapshot["enabled"] is True
    assert snapshot["stalls"]["total"] >= 1
    assert snapshot["worst_ms"] >= 200.0
    assert snapshot["top_stacks"], "卡顿窗口内应至少有一个栈聚合"
    first = snapshot["top_stacks"][0]
    assert first["count"] >= 1
    assert first["max_ms"] > 0
    assert any("test_ui_watchdog" in frame or "sleep" in frame for frame in first["frames"])

    # 全局计数器同步累加
    counters = pm.get_perf_snapshot()["global_counters"]
    assert counters.get("ui_watchdog.stalls", 0) >= 1


def test_install_is_idempotent(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """重复 install 返回同一实例，不重复建线程。"""
    monkeypatch.setenv("FAF_UI_WATCHDOG", "1")
    first = wd.install(qapp)
    threads_after_first = threading.active_count()
    second = wd.install(qapp)

    assert first is not None and first is second
    assert threading.active_count() == threads_after_first


def test_uninstall_reclaims_thread(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """uninstall 后采样线程退出且实例清空。"""
    monkeypatch.setenv("FAF_UI_WATCHDOG", "1")
    before = threading.active_count()
    watchdog = wd.install(qapp)
    assert watchdog is not None
    assert threading.active_count() > before or watchdog._thread is not None

    wd.uninstall()
    assert wd.get_watchdog() is None
    assert watchdog._thread is None
    assert pm.get_perf_snapshot()["providers"].get("ui_watchdog") is None


def test_provider_error_is_isolated() -> None:
    """单个 provider 抛异常只污染自己的段，不影响整份快照。"""

    def boom() -> dict:
        raise RuntimeError("boom")

    pm.register_snapshot_provider("p61_boom", boom)
    try:
        snapshot = pm.get_perf_snapshot()
        assert "error" in snapshot["providers"]["p61_boom"]
        assert "events" in snapshot and "global_counters" in snapshot
    finally:
        pm.unregister_snapshot_provider("p61_boom")


def test_snapshot_provider_roundtrip() -> None:
    """注册/注销 provider 的读写契约。"""
    pm.register_snapshot_provider("p61_echo", lambda: {"value": 7})
    try:
        assert pm.get_perf_snapshot()["providers"]["p61_echo"] == {"value": 7}
    finally:
        pm.unregister_snapshot_provider("p61_echo")
    assert "p61_echo" not in pm.get_perf_snapshot()["providers"]
