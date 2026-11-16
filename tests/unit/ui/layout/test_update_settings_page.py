# -*- coding: utf-8 -*-
"""检查更新页测试。

覆盖：
* 版本信息来自 ``SPKVERSION``（版本号 + 构建日期）；
* 「获取测试版」默认值跟随本地版本通道；
* 点击检查更新直接调用内联 session（不再弹确认框）；
* 检查/下载各状态的状态文案、进度条、更新详情与按钮状态；
* 「启用国内源加速」开关在 github / gitcode 之间切换并写入暂存；
* 「启动时检查更新」写入暂存并发出 ``staged_changed``；
* 关于Sopeek 页不再承载版本/更新控件。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/layout/test_update_settings_page.py -v
"""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

import sopeek.ui.layout.settings_layout as sl_mod
from sopeek.core.managers.settings_manager_v2 import DEFAULT_SETTINGS_V2
from sopeek.ui.layout.settings_staging_cache import SettingsStagingCache
from sopeek.utils.version_info import (
    RELEASES_URL,
    get_local_build_date,
    get_local_version,
)

pytestmark = pytest.mark.unit


def _make_cache() -> SettingsStagingCache:
    """创建一个以 V2 默认设置开启的暂存缓存。"""
    cache = SettingsStagingCache()
    cache.begin(copy.deepcopy(DEFAULT_SETTINGS_V2))
    return cache


@pytest.fixture
def page(qapp: Any) -> Iterator[sl_mod.UpdateSettingsPage]:
    """创建检查更新页并在用例结束后销毁。"""
    widget = sl_mod.UpdateSettingsPage(staging_cache=_make_cache())
    try:
        yield widget
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def _info(**overrides: Any) -> SimpleNamespace:
    """构造一个接近 UpdateInfo 的轻量替身。"""
    data = {
        "local_version": get_local_version(),
        "remote": {
            "version": "v9.9.9",
            "date": "2026-11-14",
            "notes": "- 修复若干问题\n- 优化更新流程",
            "notes_truncated": False,
            "html_url": (
                "https://github.com/Dorufoc/Sopeek/releases/tag/v9.9.9"
            ),
        },
        "asset": {"size": 12 * 1024 * 1024},
        "skipped_newer_tag": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _error(code: str = "network", message: str = "网络连接失败，请稍后重试。") -> SimpleNamespace:
    """构造一个可读的更新错误替身。"""
    return SimpleNamespace(code=code, message=message)


def test_version_info_uses_spkversion(
    page: sl_mod.UpdateSettingsPage,
) -> None:
    """版本号显示自 SPKVERSION，构建日期放在提示中不占说明行。"""
    assert page._version_value_label.text() == f"v{get_local_version()}"
    assert not hasattr(page._version_row, "desc_label")
    build_date = get_local_build_date()
    tip = page._version_value_label.toolTip()
    if build_date:
        assert build_date in tip
    else:
        assert "构建日期未知" in tip
    assert not hasattr(page, "_release_row")
    assert not hasattr(page, "_release_link")
    assert not hasattr(page, "_detail_label")
    assert page._release_link_button.isHidden() is True
    assert page._release_link_button.text() == "前往Github查看此更新"
    assert not hasattr(page._check_row, "desc_label")
    assert not hasattr(page._source_row, "desc_label")
    assert page._source_row.title_label.text() == "启用国内源加速"
    assert page._source_toggle.checked is False
    assert hasattr(page._prerelease_row, "desc_label")
    assert hasattr(page._startup_row, "desc_label")


def test_prerelease_toggle_defaults_to_local_channel(
    qapp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """本地为预发布版本时默认勾选「获取测试版」。"""
    monkeypatch.setattr(
        sl_mod, "get_local_version", lambda: "2.0.0.nightly-20261114"
    )
    widget = sl_mod.UpdateSettingsPage(staging_cache=_make_cache())
    try:
        assert widget._prerelease_toggle.checked is True
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


class FakeInlineSession:
    """内联会话替身：记录检查与待确认操作的调用。"""

    def __init__(self) -> None:
        self.start_calls: list[bool] = []
        self.pending_download_calls = 0
        self.skip_calls = 0
        self.disposed = False

    def start_check(self, include_prerelease: bool = False) -> None:
        self.start_calls.append(bool(include_prerelease))

    def start_pending_download(self) -> bool:
        self.pending_download_calls += 1
        return True

    def skip_pending_update(self) -> bool:
        self.skip_calls += 1
        return True


def test_check_button_starts_session_directly(
    page: sl_mod.UpdateSettingsPage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """点击检查更新直接开始检查，并透传「获取测试版」。"""
    session = FakeInlineSession()
    monkeypatch.setattr(
        sl_mod.UpdateSettingsPage,
        "_ensure_update_session",
        lambda self: session,
    )

    page._check_button.click()
    assert session.start_calls == [False]

    page._prerelease_toggle.checked = True
    page._check_button.click()
    assert session.start_calls == [False, True]


def test_check_button_unavailable_component(
    page: sl_mod.UpdateSettingsPage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """更新组件不可用时显示可重试的失败状态。"""
    monkeypatch.setattr(
        sl_mod.UpdateSettingsPage,
        "_ensure_update_session",
        lambda self: None,
    )
    page._check_button.click()
    assert page._status_label.text() == "检查失败 · 更新组件不可用，请重新安装应用。"
    assert page._check_button.text() == "重试"


def test_checking_state(page: sl_mod.UpdateSettingsPage) -> None:
    """检查中：加载动画可见、按钮禁用且文案切换。"""
    page._on_inline_checking()
    assert page._status_label.text() == "正在检查更新…"
    assert page._status_spinner.isHidden() is False
    assert page._check_button.isEnabled() is False
    assert page._check_button.text() == "正在检查…"
    assert page._progress.isHidden() is True


def test_up_to_date_state(page: sl_mod.UpdateSettingsPage) -> None:
    """无更新：显示当前版本已是最新。"""
    page._on_inline_up_to_date(_info())
    assert page._status_label.text() == "当前已是最新版本"
    assert page._check_button.isEnabled() is True
    assert page._check_button.text() == "检查更新"
    assert page._release_link_button.isHidden() is True
    assert page._details_meta_label.isHidden() is True


def test_up_to_date_with_skipped_tag(page: sl_mod.UpdateSettingsPage) -> None:
    """更高版本缺安装包时显示跳过原因。"""
    page._on_inline_up_to_date(
        _info(skipped_newer_tag="9.9.10")
    )
    assert page._status_label.text().startswith("当前已是最新可用版本")
    assert "9.9.10" in page._status_label.text()
    assert "暂无安装包" in page._status_label.text()


def test_check_failed_state(page: sl_mod.UpdateSettingsPage) -> None:
    """检查失败：显示原因并允许重试。"""
    page._on_inline_check_failed(_error())
    assert page._status_label.text() == "检查失败 · 网络连接失败，请稍后重试。"
    assert page._check_button.text() == "重试"
    assert page._check_button.isEnabled() is True


def test_download_progress_and_details(
    page: sl_mod.UpdateSettingsPage,
) -> None:
    """下载中：版本信息、发布页链接与进度条均可见。"""
    info = _info()
    page._on_inline_download_started(info)
    assert "v9.9.9" in page._status_label.text()
    assert page._check_button.isEnabled() is False
    assert page._progress.isHidden() is False
    assert page._pending_actions.isHidden() is True
    assert "v9.9.9" in page._details_meta_label.text()
    assert "12.0 MB" in page._details_meta_label.text()
    assert page._release_link_button.isHidden() is False
    assert page._release_link_button.toolTip() == info.remote["html_url"]
    assert not hasattr(page, "_notes_area")

    page._on_inline_download_progress(50, 100)
    assert page._progress.value == pytest.approx(0.5)


def test_downloaded_state(page: sl_mod.UpdateSettingsPage) -> None:
    """下载完成：进度 100%，提示下次启动安装。"""
    page._on_inline_downloaded(_info(), "C:/tmp/setup.exe")
    assert page._status_label.text() == "更新包下载完成 · 将在下次启动时自动安装"
    assert page._progress.value == pytest.approx(1.0)
    assert page._check_button.isEnabled() is True


def test_download_failed_keeps_details(
    page: sl_mod.UpdateSettingsPage,
) -> None:
    """下载失败：显示原因、保留详情并允许重试。"""
    info = _info()
    page._on_inline_download_failed(info, _error("io", "写入安装包失败。"))
    assert page._status_label.text() == "下载失败 · 写入安装包失败。"
    assert page._progress.isHidden() is True
    assert page._release_link_button.isHidden() is False
    assert page._check_button.text() == "重试"


def _prerelease_info() -> SimpleNamespace:
    """构造一个测试版更新结果。"""
    info = _info()
    info.remote["prerelease"] = True
    return info


def test_prerelease_update_waits_for_confirmation(
    page: sl_mod.UpdateSettingsPage,
) -> None:
    """测试版不自动下载：保留版本信息与发布页链接，并显示操作按钮。"""
    info = _prerelease_info()
    page._on_inline_update_available(info)

    assert page._status_label.text() == "发现测试版 v9.9.9"
    assert page._details_meta_label.isHidden() is False
    assert page._release_link_button.isHidden() is False
    assert page._release_link_button.text() == "前往Github查看此更新"
    assert "github.svg" in (page._release_link_button._svg_icon_path or "")
    assert page._release_link_button._icon_anchor == "Github"
    assert page._pending_actions.isHidden() is False
    assert page._skip_button.isHidden() is False
    assert page._download_button.isHidden() is False
    assert page._check_button.isEnabled() is False
    assert page._check_button.text() == "等待确认"


def test_release_link_opens_update_page(
    page: sl_mod.UpdateSettingsPage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """点击第三行链接打开当前更新对应的 GitHub 发布页。"""
    opened: list[str] = []

    class _FakeDesktopServices:
        @staticmethod
        def openUrl(url: Any) -> None:
            opened.append(url.toString())

    monkeypatch.setattr(sl_mod, "QDesktopServices", _FakeDesktopServices)
    info = _prerelease_info()
    page._on_inline_update_available(info)

    page._release_link_button.click()
    assert opened == [info.remote["html_url"]]


@pytest.mark.parametrize(
    "html_url",
    ["", "https://evil.example/releases/tag/v9.9.9"],
)
def test_release_link_falls_back_to_releases_page(
    page: sl_mod.UpdateSettingsPage, html_url: str
) -> None:
    """缺失或非法发布页地址回退到 GitHub Releases 首页。"""
    info = _info(
        remote={"version": "v9.9.9", "date": "2026-11-14", "html_url": html_url}
    )
    page._on_inline_update_available(info)
    assert page._release_link_button.toolTip() == RELEASES_URL


def test_prerelease_download_action(
    page: sl_mod.UpdateSettingsPage,
) -> None:
    """点击「下载更新」把确认结果交给内联会话。"""
    session = FakeInlineSession()
    page._update_session = session
    page._on_inline_update_available(_prerelease_info())

    page._download_button.click()
    assert session.pending_download_calls == 1


def test_prerelease_skip_action(
    page: sl_mod.UpdateSettingsPage,
) -> None:
    """点击「跳过此版本」把跳过结果交给内联会话。"""
    session = FakeInlineSession()
    page._update_session = session
    page._on_inline_update_available(_prerelease_info())

    page._skip_button.click()
    assert session.skip_calls == 1


def test_prerelease_skipped_state(
    page: sl_mod.UpdateSettingsPage,
) -> None:
    """跳过测试版后收起详情并恢复检查按钮。"""
    info = _prerelease_info()
    page._on_inline_update_skipped(info)

    assert page._status_label.text() == "已跳过此版本 · v9.9.9"
    assert page._release_link_button.isHidden() is True
    assert page._details_meta_label.isHidden() is True
    assert page._pending_actions.isHidden() is True
    assert page._check_button.isEnabled() is True
    assert page._check_button.text() == "检查更新"


def test_prerelease_actions_are_stacked_vertically(
    page: sl_mod.UpdateSettingsPage,
) -> None:
    """测试版操作按钮在状态区右上角纵向排列。"""
    layout = page._pending_actions.layout()
    assert layout is not None
    assert layout.count() == 3
    assert layout.itemAt(0).widget() is page._skip_button
    assert layout.itemAt(1).spacerItem() is not None
    assert layout.itemAt(2).widget() is page._download_button
    assert page._skip_button.minimumWidth() == page._download_button.minimumWidth()

    page._on_inline_update_available(_prerelease_info())
    assert page._details_meta_label.isHidden() is False
    assert page._release_link_button.isHidden() is False
    assert page._pending_actions.isHidden() is False


def test_update_available_snapshot_restores_actions(
    page: sl_mod.UpdateSettingsPage,
) -> None:
    """页面重新显示时恢复等待确认的测试版操作区。"""
    page._render_update_snapshot(
        {
            "state": "update_available",
            "info": _prerelease_info(),
            "error": None,
            "downloaded": 0,
            "total": 0,
        }
    )
    assert page._status_label.text() == "发现测试版 v9.9.9"
    assert page._pending_actions.isHidden() is False
    assert page._release_link_button.isHidden() is False
    assert page._check_button.isEnabled() is False


def test_snapshot_restores_downloading_state(
    page: sl_mod.UpdateSettingsPage,
) -> None:
    """页面重新显示时按 session 快照恢复下载状态。"""
    page._render_update_snapshot(
        {
            "state": "downloading",
            "info": _info(),
            "error": None,
            "downloaded": 25,
            "total": 100,
        }
    )
    assert "v9.9.9" in page._status_label.text()
    assert page._progress.value == pytest.approx(0.25)
    assert page._check_button.isEnabled() is False


def test_domestic_source_toggle_writes_staging(
    page: sl_mod.UpdateSettingsPage,
) -> None:
    """国内源开关：开启写 gitcode，关闭回默认 github，并发出变更信号。"""
    cache = page._staging_cache
    assert cache is not None
    emitted: list[bool] = []
    page.staged_changed.connect(lambda: emitted.append(True))

    page._source_toggle.checked = True
    assert cache.get("update.source") == "gitcode"
    assert emitted == [True]

    page._source_toggle.checked = False
    assert cache.get("update.source") == "github"
    assert emitted == [True, True]


def test_refresh_from_staging_restores_domestic_source_toggle(
    page: sl_mod.UpdateSettingsPage,
) -> None:
    """重置/取消后按暂存恢复国内源开关，且不反向写回暂存。"""
    cache = page._staging_cache
    assert cache is not None
    emitted: list[bool] = []
    page.staged_changed.connect(lambda: emitted.append(True))

    cache.set("update.source", "gitcode")
    page.refresh_from_staging()
    assert page._source_toggle.checked is True
    assert emitted == []

    cache.set("update.source", "github")
    page.refresh_from_staging()
    assert page._source_toggle.checked is False
    assert emitted == []


def test_startup_toggle_writes_staging(page: sl_mod.UpdateSettingsPage) -> None:
    """启动时检查更新开关只写暂存并发出变更信号。"""
    cache = page._staging_cache
    assert cache is not None
    emitted: list[bool] = []
    page.staged_changed.connect(lambda: emitted.append(True))

    page._startup_toggle.checked = False

    assert cache.get("general.check_updates_on_startup") is False
    assert emitted == [True]


def test_refresh_from_staging_restores_startup_toggle(
    page: sl_mod.UpdateSettingsPage,
) -> None:
    """重置/取消后按暂存恢复开关，且不反向写回暂存。"""
    cache = page._staging_cache
    assert cache is not None
    cache.set("general.check_updates_on_startup", False)
    emitted: list[bool] = []
    page.staged_changed.connect(lambda: emitted.append(True))

    page.refresh_from_staging()

    assert page._startup_toggle.checked is False
    assert emitted == []


def test_about_page_no_version_or_update_controls(qapp: Any) -> None:
    """关于Sopeek 页只保留身份区、外链与版权。"""
    widget = sl_mod.AboutSettingsPage()
    try:
        assert not hasattr(widget, "_version_label")
        assert not hasattr(widget, "_check_update_action")
        assert not hasattr(widget, "_update_status")
        assert not hasattr(widget, "_update_session")
        assert widget.findChild(sl_mod.QWidget, "AboutUpdateStatus") is None
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()
