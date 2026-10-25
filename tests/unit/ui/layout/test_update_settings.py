# -*- coding: utf-8 -*-
"""更新设置通用页开关的暂存路由测试（rust-native-updater todo 11）。

覆盖 ``freeassetfilter/core/managers/settings_manager_v2.py`` 的
``general.check_updates_on_startup`` 默认值 / 白名单合并，以及
``freeassetfilter/ui/layout/settings_layout.py`` 的 ``GeneralSettingsPage``
暂存写入、回填、取消恢复与主题刷新。

验证命令：
    QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/ui/layout/test_update_settings.py -v
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from freeassetfilter.core.managers.settings_manager_v2 import (
    DEFAULT_SETTINGS_V2,
    SettingsManagerV2,
)
from freeassetfilter.ui.layout.settings_layout import GeneralSettingsPage
from freeassetfilter.ui.layout.settings_staging_cache import SettingsStagingCache
from tests.support.qt_helpers import safe_teardown

pytestmark = pytest.mark.unit

_KEY = "general.check_updates_on_startup"


def _reset_v2_singleton_state() -> None:
    """防御性重置 V2 单例标记（当前实现无单例，保留兼容未来改造）。"""
    for attr, value in (("_instance", None), ("_initialized", False)):
        if hasattr(SettingsManagerV2, attr):
            setattr(SettingsManagerV2, attr, value)


@pytest.fixture(autouse=True)
def _isolate_v2_singleton() -> Any:
    """每个用例前后重置 V2 单例标记，避免跨用例状态泄漏。"""
    _reset_v2_singleton_state()
    yield
    _reset_v2_singleton_state()


def _make_cache(snapshot: dict | None = None) -> SettingsStagingCache:
    """构造已 begin 的暂存缓存。

    Args:
        snapshot: 初始快照；缺省为 V2 默认树深拷贝。

    Returns:
        SettingsStagingCache: 已开启的暂存缓存。
    """
    cache = SettingsStagingCache()
    base = copy.deepcopy(DEFAULT_SETTINGS_V2) if snapshot is None else snapshot
    cache.begin(base)
    return cache


def _make_page(cache: SettingsStagingCache) -> GeneralSettingsPage:
    """基于既有暂存缓存创建通用设置页（不触碰真实磁盘）。

    Args:
        cache: 已 begin 的暂存缓存。

    Returns:
        GeneralSettingsPage: 通用设置页实例。
    """
    return GeneralSettingsPage(staging_cache=cache)


def _write_settings_file(tmp_path: Path, payload: dict) -> str:
    """把测试配置写入临时 settings JSON 并返回路径。

    Args:
        tmp_path: pytest 临时目录。
        payload: 待写入的配置字典。

    Returns:
        str: 临时配置文件路径。
    """
    tmp_file = tmp_path / "settings_v2.json"
    tmp_file.write_text(json.dumps(payload), encoding="utf-8")
    return str(tmp_file)


class TestCheckUpdatesDefaultAndWhitelist:
    """默认值、白名单合并与旧文件兼容。"""

    def test_default_key_is_true_after_snap(self) -> None:
        """默认键紧跟在 floating_pool_snap_enabled 之后且为 True。"""
        general = DEFAULT_SETTINGS_V2["general"]
        assert general[_KEY.split(".")[-1]] is True
        keys = list(general.keys())
        assert keys.index(_KEY.split(".")[-1]) == keys.index(
            "floating_pool_snap_enabled"
        ) + 1

    def test_whitelist_accepts_false_from_disk(self, tmp_path: Path) -> None:
        """临时 JSON 中的 false 经白名单合并后保持 False。"""
        tmp_file = _write_settings_file(
            tmp_path, {"version": 2, "general": {"check_updates_on_startup": False}}
        )
        v2 = SettingsManagerV2(tmp_file)
        v2.load()
        assert v2.get(_KEY) is False

    @pytest.mark.parametrize("bad_value", ["false", 0, "", None, [], {}])
    def test_whitelist_rejects_invalid_values(
        self, tmp_path: Path, bad_value: Any
    ) -> None:
        """非法类型（字符串 "false"、0 等）保留默认 True。"""
        tmp_file = _write_settings_file(
            tmp_path,
            {"version": 2, "general": {"check_updates_on_startup": bad_value}},
        )
        v2 = SettingsManagerV2(tmp_file)
        v2.load()
        assert v2.get(_KEY) is True

    def test_old_file_missing_key_defaults_true(self, tmp_path: Path) -> None:
        """旧配置文件缺少该键时合并默认 True。"""
        tmp_file = _write_settings_file(
            tmp_path, {"version": 2, "general": {"layout_mode": "classic"}}
        )
        v2 = SettingsManagerV2(tmp_file)
        v2.load()
        assert v2.get(_KEY) is True


class TestCheckUpdatesToggleStaging:
    """开关只写暂存缓存，提交前 V2 不变。"""

    def test_toggle_stages_true_false_without_v2_write(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """切换开关写暂存 True/False，V2 内存值与磁盘均保持原值。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod

        tmp_file = tmp_path / "settings_v2.json"
        v2 = SettingsManagerV2(str(tmp_file))
        v2.load()
        monkeypatch.setattr(sl_mod, "SettingsManagerV2", lambda *a, **k: v2)

        page = GeneralSettingsPage()
        try:
            assert page._check_updates_toggle is not None
            assert page._check_updates_toggle.checked is True

            page._check_updates_toggle.checked = False
            assert page._staging_cache.get(_KEY) is False
            assert v2.get(_KEY) is True
            assert json.loads(tmp_file.read_text(encoding="utf-8"))[
                "general"
            ]["check_updates_on_startup"] is True

            page._check_updates_toggle.checked = True
            assert page._staging_cache.get(_KEY) is True
            assert v2.get(_KEY) is True
        finally:
            safe_teardown(page)

    def test_toggle_emits_staged_changed_once(
        self, qapp: QApplication
    ) -> None:
        """每次用户切换只发一次 staged_changed。"""
        cache = _make_cache()
        page = _make_page(cache)
        try:
            spy = QSignalSpy(page.staged_changed)
            page._check_updates_toggle.checked = False
            assert spy.count() == 1
            page._check_updates_toggle.checked = True
            assert spy.count() == 2
        finally:
            safe_teardown(page)

    def test_row_is_normal_row_after_snap(self, qapp: QApplication) -> None:
        """新行紧跟贴边吸附，且不是子选项。"""
        page = _make_page(_make_cache())
        try:
            assert page._check_updates_row is not None
            layout = page.layout()
            assert layout.indexOf(page._check_updates_row) == (
                layout.indexOf(page._floating_pool_snap_row) + 1
            )
            assert page._check_updates_row._sub_option is False
            assert "启动时检查更新" in page._check_updates_row.title_label.text()
        finally:
            safe_teardown(page)


class TestCheckUpdatesRefreshAndDiscard:
    """refresh_from_staging 回填、非法值回退与取消恢复。"""

    def test_refresh_fills_toggle_without_signal(
        self, qapp: QApplication
    ) -> None:
        """暂存 False 回填控件且 refresh 不发射 staged_changed。"""
        cache = _make_cache()
        page = _make_page(cache)
        try:
            cache.set(_KEY, False)
            spy = QSignalSpy(page.staged_changed)
            page.refresh_from_staging()
            assert page._check_updates is False
            assert page._check_updates_toggle.checked is False
            assert spy.count() == 0
        finally:
            safe_teardown(page)

    @pytest.mark.parametrize("bad_value", ["false", 0, None])
    def test_refresh_invalid_value_falls_back_true(
        self, qapp: QApplication, bad_value: Any
    ) -> None:
        """暂存非法值 refresh 后回退 True。"""
        cache = _make_cache()
        page = _make_page(cache)
        try:
            cache.set(_KEY, bad_value)
            page.refresh_from_staging()
            assert page._check_updates is True
            assert page._check_updates_toggle.checked is True
        finally:
            safe_teardown(page)

    def test_discard_and_refresh_restore_baseline(
        self, qapp: QApplication
    ) -> None:
        """先关后取消：discard + refresh 恢复 True 且基线未变。"""
        cache = _make_cache()
        page = _make_page(cache)
        try:
            page._check_updates_toggle.checked = False
            assert cache.get(_KEY) is False
            cache.discard()
            page.refresh_from_staging()
            assert cache.get(_KEY) is True
            assert page._check_updates is True
            assert page._check_updates_toggle.checked is True
        finally:
            safe_teardown(page)


class TestCheckUpdatesThemeAndGuard:
    """refresh_theme 覆盖新行；编程式同步守卫抑制写暂存。"""

    def test_refresh_theme_includes_new_row(
        self, qapp: QApplication, monkeypatch: Any
    ) -> None:
        """refresh_theme 的 row 元组包含新行并按统一 token 重注册。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod

        refreshed: list[Any] = []
        monkeypatch.setattr(
            sl_mod,
            "_refresh_settings_item_text",
            lambda row: refreshed.append(row),
        )
        page = _make_page(_make_cache())
        try:
            page.refresh_theme()
            assert page._check_updates_row in refreshed
        finally:
            safe_teardown(page)

    def test_sync_general_toggles_guard_suppresses_write(
        self, qapp: QApplication
    ) -> None:
        """_sync_general_toggles 内 toggle 变化被 _general_updating 守卫吞掉。"""
        cache = _make_cache()
        page = _make_page(cache)
        try:
            cache.set(_KEY, True)
            page._check_updates = False
            spy = QSignalSpy(page.staged_changed)
            page._sync_general_toggles()
            assert page._check_updates_toggle.checked is False
            assert cache.get(_KEY) is True
            assert spy.count() == 0
        finally:
            safe_teardown(page)


def _patch_update_submit_env(
    monkeypatch: Any,
    tmp_path: Path,
    initial_payload: dict | None = None,
) -> tuple[str, list[SettingsManagerV2]]:
    """把 ``settings_layout`` 的 V2 工厂绑定到临时文件并隔离提交副作用。

    同时把主题过渡遮罩、性能档位钩子与主窗口查找打成无副作用实现，
    使 ``_submit_settings`` 可以离屏独立运行。

    Args:
        monkeypatch: pytest monkeypatch 夹具。
        tmp_path: pytest 临时目录。
        initial_payload: 构造布局前预写入的 settings JSON；``None`` 时
            保持文件不存在（由首次 load 写默认树）。

    Returns:
        tuple[str, list[SettingsManagerV2]]: 临时文件路径与工厂创建的
        管理器实例列表（按创建顺序）。
    """
    import freeassetfilter.ui.layout.settings_layout as sl_mod

    tmp_file = tmp_path / "settings_v2.json"
    if initial_payload is not None:
        tmp_file.write_text(json.dumps(initial_payload), encoding="utf-8")
    created: list[SettingsManagerV2] = []

    def _factory(*args: Any, **kwargs: Any) -> SettingsManagerV2:
        manager = (
            SettingsManagerV2(*args, **kwargs)
            if args or kwargs
            else SettingsManagerV2(str(tmp_file))
        )
        created.append(manager)
        return manager

    class _NoopOverlay:
        """主题过渡遮罩 no-op 替身。"""

        @staticmethod
        def from_widget(
            _w: Any, duration_ms: Any = None, origin: Any = None
        ) -> "_NoopOverlay":
            return _NoopOverlay()

        def start(self) -> None:
            return None

    monkeypatch.setattr(sl_mod, "SettingsManagerV2", _factory)
    monkeypatch.setattr(sl_mod, "ThemeTransitionOverlay", _NoopOverlay)
    monkeypatch.setattr(
        sl_mod.SettingsLayout,
        "_apply_staged_perf_profile",
        lambda self, profile: None,
    )
    monkeypatch.setattr(
        sl_mod.AppearanceSettingsPage, "find_main_window", lambda self: None
    )
    return str(tmp_file), created


def _restore_tm_quietly(tm: Any, prev_mode: str, prev_colors: dict) -> None:
    """静默恢复主题单例内部状态（不广播，避免历史控件树卡死）。"""
    try:
        tm._theme_mode = prev_mode
        tm._dark_mode = prev_mode == "dark"
        tm._colors.clear()
        tm._colors.update(prev_colors)
        tm._clear_color_cache()
    except Exception:
        pass  # teardown 还原主题内部状态失败：忽略


def _make_submit_layout(
    qapp: QApplication,
    monkeypatch: Any,
    tmp_path: Path,
    initial_payload: dict | None = None,
) -> tuple[Any, str, list[SettingsManagerV2]]:
    """构造 V2 隔离的 ``SettingsLayout``（提交链路专用）。

    Args:
        qapp: session 级 QApplication。
        monkeypatch: pytest monkeypatch 夹具。
        tmp_path: pytest 临时目录。
        initial_payload: 构造前预写入的 settings JSON。

    Returns:
        tuple[Any, str, list[SettingsManagerV2]]: 布局实例、临时文件路径与
        工厂创建的管理器实例列表。
    """
    from freeassetfilter.ui.layout.settings_layout import SettingsLayout

    tmp_file, created = _patch_update_submit_env(
        monkeypatch, tmp_path, initial_payload
    )
    layout = SettingsLayout()
    qapp.processEvents()
    return layout, tmp_file, created


class TestCheckUpdatesSubmit:
    """``_submit_settings`` 校验、落盘、服务隔离与失败回滚。"""

    def test_submit_persists_false(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """暂存 False → 提交落盘；新建 manager 读取为 False。"""
        from theme import tm

        prev_mode = tm.get_theme_mode()
        prev_colors = copy.deepcopy(tm._colors)
        layout, tmp_file, _created = _make_submit_layout(
            qapp, monkeypatch, tmp_path
        )
        try:
            layout._staging_cache.set(_KEY, False)
            assert layout._submit_settings() is True
            fresh = SettingsManagerV2(tmp_file)
            fresh.load()
            assert fresh.get(_KEY) is False
            assert layout._staging_cache.is_dirty() is False
        finally:
            safe_teardown(layout)
            _restore_tm_quietly(tm, prev_mode, prev_colors)

    @pytest.mark.parametrize("bad_value", ["false", 0, None])
    def test_submit_invalid_staged_value_persists_true(
        self,
        qapp: QApplication,
        monkeypatch: Any,
        tmp_path: Path,
        bad_value: Any,
    ) -> None:
        """暂存非法类型 → 提交按 True 落盘（bool 严格校验）。"""
        from theme import tm

        prev_mode = tm.get_theme_mode()
        prev_colors = copy.deepcopy(tm._colors)
        layout, tmp_file, _created = _make_submit_layout(
            qapp, monkeypatch, tmp_path
        )
        try:
            layout._staging_cache.set(_KEY, bad_value)
            assert layout._submit_settings() is True
            fresh = SettingsManagerV2(tmp_file)
            fresh.load()
            assert fresh.get(_KEY) is True
        finally:
            safe_teardown(layout)
            _restore_tm_quietly(tm, prev_mode, prev_colors)

    def test_submit_missing_staged_key_persists_true(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """暂存缺少该键 → 提交按 True 落盘。"""
        from theme import tm

        prev_mode = tm.get_theme_mode()
        prev_colors = copy.deepcopy(tm._colors)
        layout, tmp_file, _created = _make_submit_layout(
            qapp, monkeypatch, tmp_path
        )
        try:
            # 模拟旧暂存快照缺少该键（Todo 11 之前的基线）。
            snapshot = copy.deepcopy(DEFAULT_SETTINGS_V2)
            snapshot["general"].pop(_KEY.split(".")[-1], None)
            layout._staging_cache.begin(snapshot)
            assert layout._staging_cache.get(_KEY, None) is None
            assert layout._submit_settings() is True
            fresh = SettingsManagerV2(tmp_file)
            fresh.load()
            assert fresh.get(_KEY) is True
        finally:
            safe_teardown(layout)
            _restore_tm_quietly(tm, prev_mode, prev_colors)

    def test_submit_never_touches_update_service(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """提交本身不调用更新服务（构造期一次性订阅除外），也不触发网络。"""
        import freeassetfilter.services.update_service as us_mod

        calls: list[str] = []
        monkeypatch.setattr(
            us_mod, "get_update_service", lambda *a, **k: calls.append("get")
        )
        monkeypatch.setattr(
            us_mod, "UpdateService", lambda *a, **k: calls.append("ctor")
        )

        from theme import tm

        prev_mode = tm.get_theme_mode()
        prev_colors = copy.deepcopy(tm._colors)
        layout, _tmp_file, _created = _make_submit_layout(
            qapp, monkeypatch, tmp_path
        )
        try:
            # 关于页构造期会订阅更新服务信号（Todo 15）；提交路径不得新增调用。
            calls.clear()
            layout._staging_cache.set(_KEY, False)
            assert layout._submit_settings() is True
            assert calls == []
        finally:
            safe_teardown(layout)
            _restore_tm_quietly(tm, prev_mode, prev_colors)

    def test_save_failure_rolls_back_memory_and_disk(
        self, qapp: QApplication, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """``save()`` 抛异常 → 返回 False，内存与磁盘均保持旧值。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod

        initial = {
            "version": 2,
            "general": {"check_updates_on_startup": False},
        }
        dialog_titles: list[str] = []
        monkeypatch.setattr(
            sl_mod,
            "create_danger_dialog",
            lambda *a, **k: dialog_titles.append(str(k.get("title", ""))),
        )
        set_calls: list[tuple[str, Any]] = []
        original_set = SettingsManagerV2.set

        def _record_set(self: SettingsManagerV2, key_path: str, value: Any) -> bool:
            set_calls.append((key_path, value))
            return original_set(self, key_path, value)

        def _boom_save(self: SettingsManagerV2) -> None:
            raise OSError("simulated disk failure")

        monkeypatch.setattr(SettingsManagerV2, "set", _record_set)
        monkeypatch.setattr(SettingsManagerV2, "save", _boom_save)

        from theme import tm

        prev_mode = tm.get_theme_mode()
        prev_colors = copy.deepcopy(tm._colors)
        layout, tmp_file, created = _make_submit_layout(
            qapp, monkeypatch, tmp_path, initial_payload=initial
        )
        try:
            layout._staging_cache.set(_KEY, True)
            assert layout._submit_settings() is False
            submit_v2 = created[-1]
            # 内存回滚到旧值 False，且回滚调用发生在最后一次 set。
            assert submit_v2.get(_KEY) is False
            assert (_KEY, True) in set_calls
            assert set_calls[-1] == (_KEY, False)
            # 磁盘保持旧值（save 失败，未写入）。
            fresh = SettingsManagerV2(tmp_file)
            fresh.load()
            assert fresh.get(_KEY) is False
            assert dialog_titles == ["保存失败"]
            assert layout._staging_cache.is_dirty() is True
        finally:
            safe_teardown(layout)
            _restore_tm_quietly(tm, prev_mode, prev_colors)
