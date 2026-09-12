# -*- coding: utf-8 -*-
"""W9/W10 平台监视器单元测试（todo 14）。

覆盖 ``freeassetfilter/core/native/platform_monitor.py``：

* W10 句柄预算：``check_gui_resource_budget`` 纯函数阈值逻辑
  （正常 / 警告水位 / 越过上限 / 缺失值降级）；
* ``sample_gui_resources`` 返回形状（键齐全；本机 Windows 下为整数计数，
  非 Windows 下为 None 降级——两分支均接受，断言 warn 标志自洽）；
* W9 DWM 探测：``probe_dwm_present_parameters`` 恒返回 ``"probe-only"``，
  产物 fail-close（文件缺失或内容缺关键行即失败）；
* ``perf_metrics.snapshot()`` 加法式扩展：既有键不动，新增
  ``gui_resources`` 段。

验证命令：
    python -m pytest tests/unit/core/test_platform_monitor.py -q --timeout 60
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from freeassetfilter.core.native import platform_monitor as pm

pytestmark = pytest.mark.unit


class TestGuiResourceBudget:
    """check_gui_resource_budget 纯函数阈值逻辑（与平台无关）。"""

    def test_all_clear_below_warn(self) -> None:
        """双计数低于水位：ok 且无警告。"""
        result = pm.check_gui_resource_budget(
            {"user_objects": 100, "gdi_objects": 200}
        )
        assert result["ok"] is True
        assert result["warnings"] == []

    def test_user_warn_band(self) -> None:
        """USER 计数进入 [8000, 10000)：警告但仍 ok。"""
        result = pm.check_gui_resource_budget(
            {"user_objects": 8000, "gdi_objects": 100}
        )
        assert result["ok"] is True
        assert any("user_objects" in w for w in result["warnings"])

    def test_gdi_warn_band(self) -> None:
        """GDI 计数进入 [8000, 10000)：警告但仍 ok。"""
        result = pm.check_gui_resource_budget(
            {"user_objects": 100, "gdi_objects": 9500}
        )
        assert result["ok"] is True
        assert any("gdi_objects" in w for w in result["warnings"])

    def test_user_over_cap_fails(self) -> None:
        """USER 计数 >= 10000：ok 为 False（上限铁律）。"""
        result = pm.check_gui_resource_budget(
            {"user_objects": 10000, "gdi_objects": 100}
        )
        assert result["ok"] is False
        assert any("cap" in w for w in result["warnings"])

    def test_gdi_over_cap_fails(self) -> None:
        """GDI 计数 >= 10000：ok 为 False。"""
        result = pm.check_gui_resource_budget(
            {"user_objects": 100, "gdi_objects": 12000}
        )
        assert result["ok"] is False

    def test_missing_counts_degrade(self) -> None:
        """计数字段为 None（非 Windows 降级）：ok，不抛异常。"""
        result = pm.check_gui_resource_budget(
            {"user_objects": None, "gdi_objects": None}
        )
        assert result["ok"] is True
        assert result["warnings"] == []

    def test_threshold_constants(self) -> None:
        """阈值常量与任务规格一致：上限 1 万，警告 8000。"""
        assert pm.USER_OBJECT_CAP == 10000
        assert pm.USER_OBJECT_WARN == 8000
        assert pm.GDI_OBJECT_CAP == 10000
        assert pm.GDI_OBJECT_WARN == 8000


class TestSampleGuiResources:
    """sample_gui_resources 返回形状（平台自适应）。"""

    def test_shape_keys(self) -> None:
        """返回字典键齐全，warn/over_cap 标志自洽。"""
        sample = pm.sample_gui_resources()
        for key in (
            "user_objects",
            "gdi_objects",
            "user_warn",
            "gdi_warn",
            "user_over_cap",
            "gdi_over_cap",
            "platform",
        ):
            assert key in sample
        user = sample["user_objects"]
        gdi = sample["gdi_objects"]
        if isinstance(user, int):
            assert sample["user_warn"] == (user >= pm.USER_OBJECT_WARN)
            assert sample["user_over_cap"] == (user >= pm.USER_OBJECT_CAP)
        else:
            assert user is None
            assert sample["user_warn"] is False
        if isinstance(gdi, int):
            assert sample["gdi_warn"] == (gdi >= pm.GDI_OBJECT_WARN)
            assert sample["gdi_over_cap"] == (gdi >= pm.GDI_OBJECT_CAP)
        else:
            assert gdi is None
            assert sample["gdi_warn"] is False

    def test_never_raises(self) -> None:
        """采样永不抛异常（降级字典代替）。"""
        sample = pm.sample_gui_resources()  # 无异常即通过
        assert isinstance(sample, dict)


class TestDwmProbe:
    """W9 DWM 探测：诚实 probe-only + 产物 fail-close。"""

    def test_probe_returns_probe_only(self, tmp_path: Path) -> None:
        """探测恒返回 probe-only（永不伪造 applied）。"""
        artifact = str(tmp_path / "w14_dwm_probe.txt")
        assert pm.probe_dwm_present_parameters(artifact) == "probe-only"

    def test_probe_artifact_fail_close(self, tmp_path: Path) -> None:
        """产物 fail-close：缺失或缺关键行即失败。"""
        artifact = tmp_path / "w14_dwm_probe.txt"
        # 未探测前产物必须不存在（若存在说明测试隔离泄漏，照样失败）。
        assert not artifact.exists()
        pm.probe_dwm_present_parameters(str(artifact))
        # 探测后产物必须存在且非空，否则失败。
        assert artifact.exists()
        text = artifact.read_text(encoding="utf-8")
        assert len(text.strip()) > 0
        assert "dwm_probe=probe-only" in text
        assert "reason=" in text
        assert "timestamp=" in text

    def test_default_artifact_path_shape(self) -> None:
        """默认产物路径指向 task-14 证据目录。"""
        path = pm.default_probe_artifact_path()
        assert path.endswith("w14_dwm_probe.txt")
        assert "task-14" in path


class TestPerfSnapshotWiring:
    """perf_metrics.snapshot() 加法式扩展不断既有键。"""

    def test_snapshot_has_gui_resources(self) -> None:
        """快照含 gui_resources 段，且既有键齐全。"""
        from freeassetfilter.utils.perf_metrics import get_perf_snapshot

        snapshot = get_perf_snapshot()
        assert "enabled" in snapshot
        assert "global_counters" in snapshot
        assert "events" in snapshot
        assert "frame_times" in snapshot
        assert "gui_resources" in snapshot
        gui: Any = snapshot["gui_resources"]
        assert "user_objects" in gui and "gdi_objects" in gui
