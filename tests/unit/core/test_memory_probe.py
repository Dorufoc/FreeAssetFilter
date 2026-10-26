# -*- coding: utf-8 -*-
"""内存探针测试（P7.1）。

锁定三条契约：

1. 进程内存可读（RSS > 0）且字段齐全；
2. 系统物理内存可读（总量 > 0）；
3. 显存查询为**安全降级**（``available=False``），不得崩溃。

验证命令：
    python -m pytest tests/unit/core/test_memory_probe.py -v
"""

from __future__ import annotations

import pytest

from freeassetfilter.core.native import memory_probe

pytestmark = pytest.mark.unit


def test_read_process_memory() -> None:
    """进程内存字段齐全且 RSS 为正。"""
    result = memory_probe.read_process_memory()
    assert set(result) == {
        "rss_bytes",
        "private_bytes",
        "peak_rss_bytes",
        "pagefile_bytes",
    }
    assert result["rss_bytes"] is not None and result["rss_bytes"] > 0
    assert result["private_bytes"] is not None and result["private_bytes"] > 0
    assert result["peak_rss_bytes"] >= result["rss_bytes"]


def test_read_system_memory() -> None:
    """系统物理内存可读。"""
    result = memory_probe.read_system_memory()
    assert result["total_phys_bytes"] is not None and result["total_phys_bytes"] > 0
    assert result["avail_phys_bytes"] is not None
    assert 0 <= (result["load_percent"] or 0) <= 100


def test_read_gpu_memory_is_safe_fallback() -> None:
    """显存查询为安全降级（不调用 DXGI COM）。"""
    result = memory_probe.read_gpu_memory()
    assert result["available"] is False
    assert "reason" in result
    assert result["dedicated_bytes"] is None


def test_snapshot_shape() -> None:
    """快照包含 process/system/gpu 三段。"""
    snapshot = memory_probe.snapshot()
    assert set(snapshot) == {"process", "system", "gpu"}
    assert snapshot["process"]["rss_bytes"] > 0
    assert snapshot["system"]["total_phys_bytes"] > 0
