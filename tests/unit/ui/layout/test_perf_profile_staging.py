# -*- coding: utf-8 -*-
"""性能档位三段选择器暂存隔离测试（todo 14）。

覆盖 ``freeassetfilter/ui/layout/settings_layout.py`` 的性能档位链路，
遵循设置页暂存铁律（AGENTS.md）：

* (1) 暂存写入：选择器切换只写 ``SettingsStagingCache``，
  不触碰 V2 磁盘与三钩子（spy 断言钩子未被调用）；
* (2) 提交应用：``_submit_settings`` 调用三钩子并落盘；
* (3) 提交落盘：V2 文件含 ``performance.profile``；
* (4) 取消恢复：``discard()`` 丢弃暂存并恢复 UI，钩子未被调用
  （misleading success 对抗：cancel 路径必须被证伪式覆盖）；
* 回滚：钩子抛异常时提交返回 False 且定时器档位恢复。

验证命令：
    python -m pytest tests/unit/ui/layout/test_perf_profile_staging.py -q --timeout 120
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication

from tests.support.qt_helpers import safe_teardown

pytestmark = pytest.mark.unit


def _patch_v2_to_tmp(monkeypatch: Any, tmp_path: Path) -> str:
    """将 settings_layout 内的 V2 绑定到临时文件。"""
    import freeassetfilter.ui.layout.settings_layout as sl_mod
    from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2

    tmp_file = str(tmp_path / "settings_v2.json")

    def _factory(*args: Any, **kwargs: Any) -> SettingsManagerV2:
        if args or "file_path" in kwargs:
            return SettingsManagerV2(*args, **kwargs)
        return SettingsManagerV2(tmp_file)

    monkeypatch.setattr(sl_mod, "SettingsManagerV2", _factory)
    return tmp_file


def _patch_overlay_noop(monkeypatch: Any) -> None:
    """将主题过渡遮罩打桩为 no-op（离屏测试提速）。"""
    import freeassetfilter.ui.layout.settings_layout as sl_mod

    class _NoopOverlay:
        @staticmethod
        def from_widget(_w: Any) -> "_NoopOverlay":
            return _NoopOverlay()

        def start(self) -> None:
            return None

    monkeypatch.setattr(sl_mod, "ThemeTransitionOverlay", _NoopOverlay)


def _patch_hook_spies(monkeypatch: Any) -> dict[str, list]:
    """将三钩子打桩为记录调用的 spy（默认成功语义）。"""
    import freeassetfilter.ui.layout.settings_layout as sl_mod

    calls: dict[str, list] = {"gpu": [], "power": [], "timing": []}

    def _fake_gpu(mode: str) -> bool:
        calls["gpu"].append(mode)
        return True

    def _fake_power(mode: str) -> bool:
        calls["power"].append(mode)
        return True

    def _fake_set_timing(profile: str) -> None:
        calls["timing"].append(profile)

    monkeypatch.setattr(sl_mod, "apply_gpu_profile", _fake_gpu)
    monkeypatch.setattr(sl_mod, "apply_process_power_policy", _fake_power)
    monkeypatch.setattr(sl_mod, "_set_timing_active_profile", _fake_set_timing)
    return calls


def _make_layout(
    qapp: QApplication, monkeypatch: Any, tmp_path: Path
) -> Any:
    """构造 V2 隔离的 SettingsLayout。"""
    from freeassetfilter.ui.layout.settings_layout import SettingsLayout

    _patch_v2_to_tmp(monkeypatch, tmp_path)
    _patch_overlay_noop(monkeypatch)
    layout = SettingsLayout()
    qapp.processEvents()
    return layout


def _restore_tm_quietly(tm: Any, prev_mode: str, prev_colors: dict) -> None:
    """静默恢复主题单例内部状态（不广播，避免历史控件树卡死）。"""
    try:
        tm._theme_mode = prev_mode
        tm._dark_mode = prev_mode == "dark"
        tm._colors.clear()
        tm._colors.update(prev_colors)
        tm._clear_color_cache()
    except Exception:
        pass


class TestProfileSelectorStaging:
    """(1) 暂存写入：选择器只写缓存，不碰磁盘与钩子。"""

    def test_segment_change_stages_only(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """切换档位 → 暂存有值；V2 磁盘仍为初值；三钩子零调用。"""
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = _patch_v2_to_tmp(monkeypatch, tmp_path)
        _patch_overlay_noop(monkeypatch)
        calls = _patch_hook_spies(monkeypatch)
        from freeassetfilter.ui.layout.settings_layout import SettingsLayout

        layout = SettingsLayout()
        try:
            page = layout._appearance_page
            assert page._perf_profile == "balanced"
            page._perf_segmented.set_current_index(0)  # 性能
            qapp.processEvents()
            assert page._perf_profile == "performance"
            assert page._staging_cache.get("performance.profile") == "performance"
            # 铁律：磁盘未被触碰。
            fresh = SettingsManagerV2(tmp_file)
            fresh.load()
            assert fresh.get("performance.profile") == "balanced"
            # 铁律：三钩子零调用。
            assert calls == {"gpu": [], "power": [], "timing": []}
        finally:
            safe_teardown(layout)

    def test_invalid_mode_ignored(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """非法档位直接忽略，暂存保持原值。"""
        layout = _make_layout(qapp, monkeypatch, tmp_path)
        try:
            page = layout._appearance_page
            page._apply_perf_profile("turbo-ultra")
            assert page._perf_profile == "balanced"
            assert page._staging_cache.get("performance.profile") != "turbo-ultra"
        finally:
            safe_teardown(layout)


class TestProfileSubmit:
    """(2)(3) 提交应用 + 落盘：三钩子被调用，V2 持久化。"""

    def test_submit_applies_hooks_and_persists(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """暂存 performance → 确定 → 三钩子各被调用一次 + V2 落盘。"""
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )
        from theme import tm

        tmp_file = _patch_v2_to_tmp(monkeypatch, tmp_path)
        _patch_overlay_noop(monkeypatch)
        calls = _patch_hook_spies(monkeypatch)
        from freeassetfilter.ui.layout.settings_layout import SettingsLayout

        prev_mode = tm.get_theme_mode()
        prev_colors = copy.deepcopy(tm._colors)
        layout = SettingsLayout()
        try:
            page = layout._appearance_page
            page._perf_segmented.set_current_index(0)  # 性能
            qapp.processEvents()
            ok = layout._submit_settings(close_after=False)
            assert ok is True
            assert calls["timing"] == ["performance"]
            assert calls["power"] == ["performance"]
            assert calls["gpu"] == ["performance"]
            fresh = SettingsManagerV2(tmp_file)
            fresh.load()
            assert fresh.get("performance.profile") == "performance"
            assert layout._staging_cache.is_dirty() is False
        finally:
            safe_teardown(layout)
            _restore_tm_quietly(tm, prev_mode, prev_colors)

    def test_submit_invalid_profile_falls_back_balanced(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """暂存非法值 → 提交按 balanced 应用（三钩子收到 balanced）。"""
        from theme import tm

        _patch_v2_to_tmp(monkeypatch, tmp_path)
        _patch_overlay_noop(monkeypatch)
        calls = _patch_hook_spies(monkeypatch)
        from freeassetfilter.ui.layout.settings_layout import SettingsLayout

        prev_mode = tm.get_theme_mode()
        prev_colors = copy.deepcopy(tm._colors)
        layout = SettingsLayout()
        try:
            layout._staging_cache.set("performance.profile", "turbo-ultra")
            ok = layout._submit_settings(close_after=False)
            assert ok is True
            assert calls["timing"] == ["balanced"]
        finally:
            safe_teardown(layout)
            _restore_tm_quietly(tm, prev_mode, prev_colors)

    def test_submit_rollback_on_hook_failure(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """钩子抛异常 → 提交返回 False，定时器档位回滚。

        tm 广播（theme_changed → 全量 repolish）在全量套件进程中会
        挂起（已知真机长组合运行不稳定性，见 task-5），故本用例把
        tm 的两个写方法打桩为记录式 fake：既不断言广播语义，也不触发
        广播；只验证回滚被调用。
        """
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from theme import tm

        _patch_v2_to_tmp(monkeypatch, tmp_path)
        _patch_overlay_noop(monkeypatch)
        timing_calls: list[str] = []
        tm_calls: list[tuple[str, str]] = []

        def _fake_set_timing(profile: str) -> None:
            timing_calls.append(profile)

        def _boom(_mode: str) -> bool:
            raise RuntimeError("simulated power-policy failure")

        monkeypatch.setattr(sl_mod, "_set_timing_active_profile", _fake_set_timing)
        monkeypatch.setattr(sl_mod, "apply_process_power_policy", _boom)
        monkeypatch.setattr(
            sl_mod,
            "_get_timing_active_profile",
            lambda: "balanced",
        )

        prev_mode = tm.get_theme_mode()
        prev_theme = "dark" if tm.is_dark_theme() else "light"
        monkeypatch.setattr(
            tm, "set_theme_mode", lambda m: tm_calls.append(("mode", m))
        )
        monkeypatch.setattr(tm, "set_theme", lambda t: tm_calls.append(("theme", t)))

        from freeassetfilter.ui.layout.settings_layout import SettingsLayout

        layout = SettingsLayout()
        try:
            page = layout._appearance_page
            page._perf_segmented.set_current_index(0)
            qapp.processEvents()
            ok = layout._submit_settings(close_after=False)
            assert ok is False
            # 定时器档位：应用一次 + 回滚一次（回到 balanced）。
            assert timing_calls[0] == "performance"
            assert timing_calls[-1] == "balanced"
            # tm 回滚被调用（写方法打桩记录，不触发广播）。
            assert ("mode", prev_mode) in tm_calls
            assert ("theme", prev_theme) in tm_calls
        finally:
            safe_teardown(layout)


class TestProfileDiscard:
    """(4) 取消恢复：discard 丢弃暂存，钩子零调用，UI 恢复。"""

    def test_cancel_discards_without_touching_hooks(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """切换档位 → 取消 → 钩子零调用 + 暂存回基线 + 分段控件恢复。"""
        layout = _make_layout(qapp, monkeypatch, tmp_path)
        try:
            calls = _patch_hook_spies(monkeypatch)
            page = layout._appearance_page
            page._perf_segmented.set_current_index(2)  # 省电
            qapp.processEvents()
            assert page._staging_cache.get("performance.profile") == "powersave"
            assert layout._staging_cache.is_dirty() is True

            layout._on_cancel_clicked()
            qapp.processEvents()
            # misleading-success 对抗：取消路径钩子必须零调用。
            assert calls == {"gpu": [], "power": [], "timing": []}
            assert layout._staging_cache.is_dirty() is False
            assert page._perf_profile == "balanced"
            assert page._perf_segmented.current_index == 1
        finally:
            safe_teardown(layout)

    def test_host_closing_restores_ui(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """直接关闭宿主（未提交）→ discard + UI 恢复。"""
        layout = _make_layout(qapp, monkeypatch, tmp_path)
        try:
            page = layout._appearance_page
            page._perf_segmented.set_current_index(0)
            qapp.processEvents()
            assert layout._staging_cache.is_dirty() is True
            layout.on_host_closing()
            qapp.processEvents()
            assert layout._staging_cache.is_dirty() is False
            assert page._perf_profile == "balanced"
        finally:
            safe_teardown(layout)

    def test_reset_restores_default_profile(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """重置 → 暂存回默认值并刷新界面（不直接落盘）。"""
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = _patch_v2_to_tmp(monkeypatch, tmp_path)
        layout = _make_layout(qapp, monkeypatch, tmp_path)
        try:
            page = layout._appearance_page
            page._perf_segmented.set_current_index(2)
            qapp.processEvents()
            layout._on_reset_clicked()
            qapp.processEvents()
            assert page._perf_profile == "balanced"
            # 重置不直接落盘：磁盘仍为初值。
            fresh = SettingsManagerV2(tmp_file)
            fresh.load()
            assert fresh.get("performance.profile") == "balanced"
        finally:
            safe_teardown(layout)
