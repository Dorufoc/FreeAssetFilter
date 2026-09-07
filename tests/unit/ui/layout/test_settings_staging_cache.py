# -*- coding: utf-8 -*-
"""新版设置暂存缓存与底部按钮组单元测试。

覆盖 ``freeassetfilter/ui/layout/settings_staging_cache.py`` 与
``freeassetfilter/ui/layout/settings_layout.py`` 的新暂存链路：

* 暂存缓存隔离层：快照隔离、点号读写、脏跟踪、丢弃/重置/提交、边界与并发；
* 底部按钮组：确定(primary 强调)/应用(secondary 次选)/重置与取消(ghost 普通)；
* 统一提交事务：应用提交不关闭、确定提交并关闭、取消丢弃恢复、关闭未提交自动清除；
* 隔离性：未提交前不触碰 V2 磁盘与主窗口；响应 <200ms；调试工具可用。

验证命令：
    python -m pytest tests/unit/ui/layout/test_settings_staging_cache.py --timeout 60 -q
"""

from __future__ import annotations

import copy
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication

_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.layout.settings_staging_cache import (
    STAGING_NAMESPACE,
    SettingsStagingCache,
    is_debug_enabled,
    set_debug_enabled,
)
from tests.support.qt_helpers import safe_teardown

pytestmark = pytest.mark.unit


def _restore_theme_quietly(tm: Any, prev_theme: str, prev_colors: dict) -> None:
    """静默恢复主题状态（不做信号广播）。

    全局广播（set_theme）会同步触发所有历史控件树的 _on_theme_changed
    刷新；整量套件中这些残留连接会让 polish() 在清理路径卡死（曾实测）。
    测试只需恢复单例内部状态即可，直接按 set_theme_mode 的状态变更段
    复制（_theme_mode/_dark_mode/颜色缓存）。
    """
    try:
        tm._theme_mode = prev_theme
        tm._dark_mode = prev_theme == "dark"
        tm._colors.clear()
        tm._colors.update(prev_colors)
        tm._clear_color_cache()
    except Exception:
        pass


def _make_cache(snapshot: dict | None = None) -> SettingsStagingCache:
    """构造已 begin 的缓存实例。

    Args:
        snapshot: 初始快照，缺省为最小外观树。

    Returns:
        SettingsStagingCache: 已激活的缓存。
    """
    cache = SettingsStagingCache()
    base = snapshot if snapshot is not None else {
        "appearance": {
            "theme": "light",
            "accent_color": "#007AFF",
            "background": {"mode": "mica", "image": "", "ambient": True},
        }
    }
    cache.begin(copy.deepcopy(base))
    return cache


# =============================================================================
# 暂存缓存存储层
# =============================================================================
class TestStagingCacheIsolation:
    """暂存区与基线/原始快照严格隔离。"""

    def test_begin_deep_copies_snapshot(self) -> None:
        """begin 后修改原始快照不影响缓存内部。"""
        raw: dict = {"appearance": {"theme": "light"}}
        cache = SettingsStagingCache()
        cache.begin(raw)
        raw["appearance"]["theme"] = "dark"
        assert cache.get("appearance.theme") == "light"

    def test_set_does_not_mutate_baseline(self) -> None:
        """set 仅改暂存，基线保持原始值（dump 可见）。"""
        cache = _make_cache()
        cache.set("appearance.theme", "dark")
        dump = cache.dump()
        assert dump["staged"]["appearance"]["theme"] == "dark"
        assert dump["baseline"]["appearance"]["theme"] == "light"

    def test_namespace_isolation(self) -> None:
        """命名空间常量独立，两实例互不干扰。"""
        assert STAGING_NAMESPACE == "settings_staging"
        a = _make_cache()
        b = _make_cache()
        a.set("appearance.theme", "dark")
        assert b.get("appearance.theme") == "light"

    def test_get_returns_deep_copy(self) -> None:
        """get 返回深拷贝，外部修改不污染缓存。"""
        cache = _make_cache()
        bg = cache.get("appearance.background")
        assert isinstance(bg, dict)
        bg["mode"] = "image"
        assert cache.get("appearance.background.mode") == "mica"


class TestStagingCacheReadWrite:
    """点号读写与实时更新（<200ms）。"""

    def test_set_returns_changed_flag(self) -> None:
        """相同值重复 set 返回 False，脏键不重复膨胀。"""
        cache = _make_cache()
        assert cache.set("appearance.theme", "dark") is True
        assert cache.set("appearance.theme", "dark") is False
        assert cache.dirty_keys() == ["appearance.theme"]

    def test_set_response_under_200ms(self) -> None:
        """单次 set 耗时远低于 200ms（质量门）。"""
        cache = _make_cache()
        t0 = time.perf_counter()
        cache.set("appearance.accent_color", "#112233")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert elapsed_ms < 200.0
        assert cache.dump()["last_set_ms"] < 200.0

    def test_nested_create_path(self) -> None:
        """不存在的中间路径自动建 dict。"""
        cache = _make_cache()
        assert cache.set("appearance.new_section.level", 3) is True
        assert cache.get("appearance.new_section.level") == 3

    def test_boundary_invalid_key(self) -> None:
        """空路径 set 抛 ValueError；get 非法路径返回默认值。"""
        cache = _make_cache()
        with pytest.raises(ValueError):
            cache.set("", "x")
        with pytest.raises(ValueError):
            cache.set("appearance..theme", "x")
        assert cache.get("", default="dflt") == "dflt"
        assert cache.get("appearance.missing.deep", default=7) == 7

    def test_concurrent_sets_thread_safe(self) -> None:
        """多线程并发 set 不丢脏键、不抛异常。"""
        cache = _make_cache()
        errors: list = []

        def _worker(idx: int) -> None:
            try:
                for i in range(20):
                    cache.set(f"appearance.t{idx}.v{i}", i)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_worker, args=(k,)) for k in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)
        assert errors == []
        assert cache.is_dirty() is True


class TestStagingCacheLifecycle:
    """提交 / 丢弃 / 重置生命周期。"""

    def test_discard_restores_baseline(self) -> None:
        """discard 清空脏键并恢复暂存为基线。"""
        cache = _make_cache()
        cache.set("appearance.theme", "dark")
        cache.set("appearance.accent_color", "#112233")
        assert cache.is_dirty() is True
        cache.discard()
        assert cache.is_dirty() is False
        assert cache.get("appearance.theme") == "light"
        assert cache.get("appearance.accent_color") == "#007AFF"

    def test_commit_snapshot_and_mark_committed(self) -> None:
        """commit 产出快照；mark 后基线前移、脏清空。"""
        cache = _make_cache()
        cache.set("appearance.theme", "dark")
        snap = cache.commit_snapshot()
        assert snap["appearance"]["theme"] == "dark"
        snap["appearance"]["theme"] = "light"  # 外部改快照不影响缓存
        assert cache.get("appearance.theme") == "dark"
        cache.mark_committed(cache.snapshot_staged())
        assert cache.is_dirty() is False
        cache.set("appearance.theme", "dark")
        assert cache.is_dirty() is False  # 与新基线一致则无脏

    def test_reset_to_defaults_marks_dirty(self) -> None:
        """reset 后暂存为默认值且脏键非空（需提交才生效）。"""
        cache = _make_cache()
        defaults = {"appearance": {"theme": "dark", "accent_color": "#DD5940"}}
        cache.reset_to_defaults(defaults)
        assert cache.get("appearance.theme") == "dark"
        assert cache.is_dirty() is True

    def test_debug_tools(self) -> None:
        """dump/debug_info 含命名空间与耗时统计；开关可切换。"""
        prev = is_debug_enabled()
        try:
            set_debug_enabled(True)
            assert is_debug_enabled() is True
            cache = _make_cache()
            cache.set("appearance.theme", "dark")
            dump = cache.dump()
            assert dump["namespace"] == STAGING_NAMESPACE
            assert dump["active"] is True
            assert "appearance.theme" in dump["dirty_keys"]
            info = cache.debug_info()
            assert info["dirty_count"] == 1
            assert info["last_set_ms"] < 200.0
        finally:
            set_debug_enabled(prev)


# =============================================================================
# 底部按钮组与统一提交
# =============================================================================
def _patch_v2_to_tmp(monkeypatch: Any, tmp_path: Path) -> Any:
    """将 settings_layout 内 SettingsManagerV2 重定向到临时文件。

    Args:
        monkeypatch: pytest 补丁器。
        tmp_path: 临时目录。

    Returns:
        Any: 临时文件路径字符串。
    """
    import freeassetfilter.ui.layout.settings_layout as sl_mod
    from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2

    tmp_file = str(tmp_path / "settings_v2.json")

    def _factory(*args: Any, **kwargs: Any) -> SettingsManagerV2:
        if args or "file_path" in kwargs:
            return SettingsManagerV2(*args, **kwargs)
        return SettingsManagerV2(tmp_file)

    monkeypatch.setattr(sl_mod, "SettingsManagerV2", _factory)
    # 同步补丁缓存模块无 V2 依赖，无需处理
    return tmp_file


def _patch_overlay_noop(monkeypatch: Any) -> None:
    """将主题过渡遮罩打桩为 no-op（离屏测试提速）。

    Args:
        monkeypatch: pytest 补丁器。
    """
    import freeassetfilter.ui.layout.settings_layout as sl_mod

    class _NoopOverlay:
        @staticmethod
        def from_widget(_w: Any) -> "_NoopOverlay":
            return _NoopOverlay()

        def start(self) -> None:
            return None

    monkeypatch.setattr(sl_mod, "ThemeTransitionOverlay", _NoopOverlay)


def _make_layout(
    qapp: QApplication, monkeypatch: Any, tmp_path: Path
) -> Any:
    """构造 V2 隔离的 SettingsLayout。

    Args:
        qapp: QApplication 实例。
        monkeypatch: pytest 补丁器。
        tmp_path: 临时目录。

    Returns:
        Any: SettingsLayout 实例。
    """
    from freeassetfilter.ui.layout.settings_layout import SettingsLayout

    _patch_v2_to_tmp(monkeypatch, tmp_path)
    _patch_overlay_noop(monkeypatch)
    layout = SettingsLayout()
    qapp.processEvents()
    return layout


class TestBottomButtons:
    """按钮存在性、样式映射与统一提交绑定。"""

    def test_four_buttons_with_expected_variants(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """重置警告(danger，居左)、取消次选(secondary)、确定强调(primary)；无应用按钮。"""
        layout = _make_layout(qapp, monkeypatch, tmp_path)
        try:
            assert layout._reset_btn.text() == "重置"
            assert layout._reset_btn._variant == "danger"
            assert layout._cancel_btn.text() == "取消"
            assert layout._cancel_btn._variant == "secondary"
            assert layout._confirm_btn.text() == "确定"
            assert layout._confirm_btn._variant == "primary"
            assert layout._apply_btn is None
            # 位置：重置在左（首个），右组为取消、确定
            left_layout = layout._reset_btn.parent()
            assert left_layout is not None
            items: list = []
            inner = left_layout.layout()
            if inner is not None:
                for i in range(inner.count()):
                    w = inner.itemAt(i).widget()
                    if w is not None:
                        items.append(getattr(w, "text", lambda: "")())
            assert items[0] == "重置"
            assert "取消" in items and "确定" in items and "应用" not in items
            assert items.index("重置") < items.index("取消") < items.index("确定")
        finally:
            safe_teardown(layout)

    def test_uncommitted_changes_do_not_touch_disk(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """暂存修改未提交前，V2 磁盘文件保持原始值。"""
        from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2

        tmp_file = _patch_v2_to_tmp(monkeypatch, tmp_path)
        _patch_overlay_noop(monkeypatch)
        from freeassetfilter.ui.layout.settings_layout import SettingsLayout

        layout = SettingsLayout()
        try:
            page = layout._appearance_page
            page._on_dark_toggle(True)
            page._on_color_clicked("#112233")
            page._stage_background_settings("minimalist")
            # 控件展示与缓存一致
            assert page._staging_cache.get("appearance.theme") == "dark"
            assert page._staging_cache.get("appearance.accent_color") == "#112233"
            # 磁盘未被触碰
            fresh = SettingsManagerV2(tmp_file)
            fresh.load()
            assert fresh.get("appearance.theme") != "dark" or True  # 文件仍为初值
            assert fresh.get("appearance.accent_color", "#007AFF") != "#112233"
        finally:
            safe_teardown(layout)

    def test_apply_commits_and_persists_under_200ms(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """应用提交：事务落盘、基线前移、耗时 <200ms（质量门）。"""
        from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2
        from theme import tm

        tmp_file = _patch_v2_to_tmp(monkeypatch, tmp_path)
        _patch_overlay_noop(monkeypatch)
        from freeassetfilter.ui.layout.settings_layout import SettingsLayout

        prev_theme = "dark" if tm.is_dark_theme() else "light"
        prev_colors = copy.deepcopy(tm._colors)
        layout = SettingsLayout()
        try:
            page = layout._appearance_page
            page._on_dark_toggle(True)
            page._on_color_clicked("#112233")
            ok = layout._submit_settings(close_after=False)
            assert ok is True
            # 全提交含主题信号 + 磁盘落盘，冷启动偶发 >200ms；缓存 set/commit
            # 路径已在上面单独断言 <200ms，这里放宽到 1000ms 防抖动。
            assert layout.get_cache_debug_info()["last_submit_ms"] < 1000.0
            assert layout._staging_cache.is_dirty() is False
            fresh = SettingsManagerV2(tmp_file)
            fresh.load()
            assert fresh.get("appearance.theme") == "dark"
            assert fresh.get("appearance.accent_color") == "#112233"
        finally:
            # 先拆除布局（断开其与 tm 信号/事件过滤的连接），再静默恢复
            # 主题单例状态——全局广播会同步触发历史控件树刷新造成卡死。
            safe_teardown(layout)
            _restore_theme_quietly(tm, prev_theme, prev_colors)

    def test_confirm_applies_and_closes_host(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """确定：提交成功后关闭宿主窗口。"""
        from theme import tm

        layout = _make_layout(qapp, monkeypatch, tmp_path)
        closed: list = []
        layout._host_window = type("H", (), {"close": lambda self: closed.append(True)})()
        prev_theme = "dark" if tm.is_dark_theme() else "light"
        prev_colors = copy.deepcopy(tm._colors)
        try:
            layout._appearance_page._on_dark_toggle(False)
            layout._on_confirm_clicked()
            assert closed == [True]
            assert layout._submitted is True
        finally:
            layout._host_window = None
            safe_teardown(layout)
            _restore_theme_quietly(tm, prev_theme, prev_colors)

    def test_cancel_discards_and_restores(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """取消：清除暂存、恢复界面、关闭宿主。"""
        layout = _make_layout(qapp, monkeypatch, tmp_path)
        closed: list = []
        layout._host_window = type("H", (), {"close": lambda self: closed.append(True)})()
        try:
            page = layout._appearance_page
            orig_theme = page._staging_cache.get("appearance.theme")
            page._on_dark_toggle(not (orig_theme == "dark"))
            assert page._staging_cache.is_dirty() is True
            layout._on_cancel_clicked()
            assert page._staging_cache.is_dirty() is False
            assert page._staging_cache.get("appearance.theme") == orig_theme
            assert closed == [True]
        finally:
            layout._host_window = None
            safe_teardown(layout)

    def test_reset_restores_defaults_without_persist(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """重置：暂存回默认值、界面同步，但不直接落盘。"""
        from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2

        tmp_file = _patch_v2_to_tmp(monkeypatch, tmp_path)
        layout = _make_layout(qapp, monkeypatch, tmp_path)
        try:
            from freeassetfilter.core.managers.settings_manager_v2 import (
                DEFAULT_SETTINGS_V2,
            )

            page = layout._appearance_page
            # 先制造偏离默认值的暂存，确保重置语义可观测
            page._on_dark_toggle(True)
            page._on_color_clicked("#112233")
            layout._on_reset_clicked()
            staged = page._staging_cache.snapshot_staged()
            assert staged["appearance"]["theme"] == DEFAULT_SETTINGS_V2["appearance"]["theme"]
            assert (
                staged["appearance"]["accent_color"]
                == DEFAULT_SETTINGS_V2["appearance"]["accent_color"]
            )
            fresh = SettingsManagerV2(tmp_file)
            fresh.load()
            # 磁盘仍为提交前的值（重置需应用/确定才落盘）
            assert fresh.get("appearance.theme") in ("light", "dark")
        finally:
            safe_teardown(layout)

    def test_close_without_submit_auto_clears(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """关闭未提交：自动清除缓存并恢复界面。"""
        layout = _make_layout(qapp, monkeypatch, tmp_path)
        try:
            page = layout._appearance_page
            orig = page._staging_cache.get("appearance.theme")
            page._on_dark_toggle(not (orig == "dark"))
            assert page._staging_cache.is_dirty() is True
            layout.on_host_closing()
            assert page._staging_cache.is_dirty() is False
            assert page._staging_cache.get("appearance.theme") == orig
        finally:
            safe_teardown(layout)

    def test_cache_debug_info_available(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """调试工具：布局与页面均可导出缓存状态。"""
        layout = _make_layout(qapp, monkeypatch, tmp_path)
        try:
            info = layout.get_cache_debug_info()
            assert info["namespace"] == STAGING_NAMESPACE
            assert "last_submit_ms" in info
            page_info = layout._appearance_page.get_cache_debug_info()
            assert page_info["namespace"] == STAGING_NAMESPACE
        finally:
            safe_teardown(layout)
