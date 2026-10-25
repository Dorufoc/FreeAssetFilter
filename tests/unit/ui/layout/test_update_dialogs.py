# -*- coding: utf-8 -*-
"""更新对话框与关于页更新检查测试（rust-native-updater）。

本文件当前覆盖 Todo 15 的关于页真实检查流程；Todo 16/17/18 会在同一文件
继续追加详情、进度与安装确认用例。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/layout/test_update_dialogs.py -k about -v
"""

from __future__ import annotations

import gc
import weakref
from pathlib import Path
from typing import Any, Callable

import pytest
from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

import freeassetfilter.ui.layout.settings_layout as sl_mod
import freeassetfilter.ui.layout.update_dialogs as ud_mod
from freeassetfilter.services.update_service import UpdateError, UpdateInfo
from freeassetfilter.utils.version_info import RELEASES_URL
from tests.support.qt_helpers import (
    drain_deferred_deletes,
    flush_widget_queue,
    safe_teardown,
)

pytestmark = pytest.mark.unit


class FakeUpdateService(QObject):
    """最小更新服务替身：信号与生产契约一致，行为完全可控。

    Attributes:
        available: ``is_available()`` 返回值。
        next_id: 下一次 ``check()`` 返回的请求 id。
        emit_started: 是否在 ``check()`` 内同步发 ``check_started``。
        emit_result: 可选的 ``(info, error)``；在 ``check()`` 内同步发结果。
        check_calls: 每次 ``check()`` 的 ``manual`` 参数。
        shutdown_calls: ``shutdown()`` 调用次数。
    """

    check_started = Signal(str, bool)
    check_finished = Signal(str, bool, object, object)
    download_started = Signal(str)
    download_progress = Signal(str, object, object, float)
    download_state_changed = Signal(str, str)
    download_pause_acked = Signal(str, bool)
    download_finished = Signal(str, str)
    download_failed = Signal(str, object)

    def __init__(self) -> None:
        super().__init__()
        self.available = True
        self.next_id = "check-1"
        self.emit_started = True
        self.emit_result: tuple[object, object] | None = None
        self.check_calls: list[bool] = []
        self.shutdown_calls = 0
        self.next_download_id = "download-1"
        self.start_download_calls: list[UpdateInfo] = []
        self.pause_calls: list[str] = []
        self.resume_calls: list[str] = []
        self.cancel_calls: list[str] = []
        self.download_states: dict[str, tuple[str, int, int]] = {}
        self.download_event_order: list[str] = []


    def is_available(self) -> bool:
        """返回可配置的可用性（不启动子进程）。"""
        return self.available

    def check(self, manual: bool = False) -> str:
        """记录手动检查并返回固定请求 id。"""
        self.check_calls.append(bool(manual))
        request_id = self.next_id
        if self.emit_started:
            self.check_started.emit(request_id, bool(manual))
        if self.emit_result is not None:
            info, error = self.emit_result
            self.check_finished.emit(request_id, bool(manual), info, error)
        return request_id

    def shutdown(self, timeout: float = 4.0) -> bool:
        """记录 shutdown 但不改变可用性（UAC 取消后仍可检查）。"""
        self.shutdown_calls += 1
        return True

    def start_download(self, info: UpdateInfo) -> str:
        """记录启动下载并返回固定的请求 id。"""
        self.download_event_order.append("start")
        self.start_download_calls.append(info)
        request_id = self.next_download_id
        if request_id not in self.download_states:
            size = int((info.asset or {}).get("size") or 0)
            self.download_states[request_id] = ("running", 0, size)
        return request_id

    def get_download_state(
        self, request_id: str
    ) -> tuple[str, int, int] | None:
        """返回测试预设的下载状态。"""
        self.download_event_order.append("state")
        return self.download_states.get(request_id)

    def pause_download(self, request_id: str) -> bool:
        """记录暂停请求。"""
        self.pause_calls.append(request_id)
        return True

    def resume_download(self, request_id: str) -> bool:
        """记录恢复请求。"""
        self.resume_calls.append(request_id)
        return True

    def cancel_download(self, request_id: str) -> None:
        """记录取消请求。"""
        self.cancel_calls.append(request_id)



def _info(
    *,
    update_available: bool = False,
    reason: str = "none",
    skipped_newer_tag: str | None = None,
    remote: dict[str, Any] | None = None,
    asset: dict[str, Any] | None = None,
) -> UpdateInfo:
    """构造一个稳定的 UpdateInfo 测试快照。"""
    return UpdateInfo(
        local_version="1.0.0-alpha.5",
        local_date="2026-05-22",
        update_available=update_available,
        reason=reason,
        skipped_newer_tag=skipped_newer_tag,
        remote=remote
        if remote is not None
        else {
            "version": "1.0.0-alpha.5",
            "tag": "v1.0.0-alpha.5",
            "date": "2026-05-22",
        },
        asset=asset,
    )


@pytest.fixture
def fake_service(qapp: QApplication) -> FakeUpdateService:
    """提供一个假的 UpdateService。"""
    return FakeUpdateService()


@pytest.fixture
def dialog_calls(monkeypatch: Any) -> dict[str, list[Any]]:
    """把 update_dialogs 的 show_* 与不可用提示替换为记录器。"""
    calls: dict[str, list[Any]] = {
        "no_update": [],
        "error": [],
        "available": [],
        "unavailable": [],
    }
    monkeypatch.setattr(
        ud_mod,
        "show_no_update",
        lambda info: calls["no_update"].append(info),
        raising=False,
    )
    monkeypatch.setattr(
        ud_mod,
        "show_check_error",
        lambda err, on_retry: calls["error"].append((err, on_retry)),
        raising=False,
    )
    monkeypatch.setattr(
        ud_mod,
        "show_update_available",
        lambda info, *args, **kwargs: calls["available"].append(info),
        raising=False,
    )
    monkeypatch.setattr(
        sl_mod,
        "create_basic_dialog",
        lambda **kwargs: calls["unavailable"].append(kwargs),
        raising=False,
    )
    return calls


@pytest.fixture
def about_page(
    qapp: QApplication,
    monkeypatch: Any,
    fake_service: FakeUpdateService,
) -> Any:
    """构造绑定假服务的关于页，并在用例后安全销毁。"""
    monkeypatch.setattr(
        sl_mod, "get_update_service", lambda: fake_service, raising=False
    )
    page = sl_mod.AboutSettingsPage()
    try:
        yield page
    finally:
        safe_teardown(page)
        drain_deferred_deletes()


def _make_page(
    monkeypatch: Any, fake_service: FakeUpdateService
) -> Any:
    """在测试体内重新构造关于页（用于构造期行为断言）。"""
    monkeypatch.setattr(
        sl_mod, "get_update_service", lambda: fake_service, raising=False
    )
    return sl_mod.AboutSettingsPage()


def _emit_result(
    fake_service: FakeUpdateService,
    request_id: str,
    *,
    info: UpdateInfo | None,
    error: UpdateError | None,
    manual: bool = True,
) -> None:
    """发射一次与生产签名一致的 check_finished。"""
    fake_service.check_finished.emit(request_id, manual, info, error)


class TestAboutPageCheckUpdate:
    """关于页手动检查：三态、同 id 过滤、重试与生命周期。"""

    def test_about_constructor_connects_check_finished_once(
        self,
        qapp: QApplication,
        monkeypatch: Any,
        fake_service: FakeUpdateService,
        dialog_calls: dict[str, list[Any]],
    ) -> None:
        """构造期一次性连接：check() 内同步发事件也能被页面槽收到。"""
        seen: list[tuple[str, bool]] = []
        original = sl_mod.AboutSettingsPage._on_check_finished

        def _spy(
            self: Any,
            request_id: str,
            manual: bool,
            info: object,
            error: object,
        ) -> None:
            seen.append((request_id, manual))
            original(self, request_id, manual, info, error)

        monkeypatch.setattr(
            sl_mod.AboutSettingsPage, "_on_check_finished", _spy
        )
        fake_service.emit_result = (_info(), None)
        page = _make_page(monkeypatch, fake_service)
        try:
            page._check_update()
            assert seen == [("check-1", True)]
            assert fake_service.check_calls == [True]
        finally:
            safe_teardown(page)
            drain_deferred_deletes()

    def test_about_click_disables_button_and_sets_progress(
        self,
        about_page: Any,
        fake_service: FakeUpdateService,
        monkeypatch: Any,
    ) -> None:
        """点击后按钮禁用并进入 0.0 进度；不允许走打开浏览器。"""
        progress_calls: list[float | None] = []
        original = about_page._check_update_btn.set_progress

        def _record(value: float | None) -> None:
            progress_calls.append(value)
            original(value)

        opened: list[Any] = []

        class _Desktop:
            @staticmethod
            def openUrl(url: Any) -> None:
                opened.append(url)

        monkeypatch.setattr(about_page._check_update_btn, "set_progress", _record)
        monkeypatch.setattr(sl_mod, "QDesktopServices", _Desktop)

        about_page._check_update()

        assert progress_calls == [0.0]
        assert about_page._check_update_btn.isEnabled() is False
        assert about_page._check_update_btn.progress() == 0.0
        assert fake_service.check_calls == [True]
        assert opened == []

    def test_about_same_id_manual_result_shows_no_update(
        self,
        about_page: Any,
        fake_service: FakeUpdateService,
        dialog_calls: dict[str, list[Any]],
    ) -> None:
        """同 id + manual=True + 无更新 → show_no_update 并恢复按钮。"""
        about_page._check_update()
        info = _info(reason="none")
        _emit_result(fake_service, "check-1", info=info, error=None)

        assert dialog_calls["no_update"] == [info]
        assert dialog_calls["error"] == []
        assert about_page._check_update_btn.isEnabled() is True
        assert about_page._check_update_btn.progress() is None

    def test_about_skipped_tag_is_handed_off_with_both_tags(
        self,
        about_page: Any,
        fake_service: FakeUpdateService,
        dialog_calls: dict[str, list[Any]],
    ) -> None:
        """skipped_newer_tag 非空时把被跳过 tag 与当前可用 tag 一并交给弹窗。

        可见文案由 Todo 16 的 ``show_no_update`` 生成；本任务保证它拿到的
        ``UpdateInfo`` 同时携带两个 tag，因而能输出「vX 暂无安装包，
        当前最新可用安装包为 vY」而不是误导性的「已是最新」。
        """
        about_page._check_update()
        info = _info(
            reason="local_newer",
            skipped_newer_tag="v1.0.0-alpha.7",
            remote={
                "version": "1.0.0-alpha.5",
                "tag": "v1.0.0-alpha.5",
                "date": "2026-05-22",
            },
        )
        _emit_result(fake_service, "check-1", info=info, error=None)

        assert len(dialog_calls["no_update"]) == 1
        handed = dialog_calls["no_update"][0]
        assert handed.skipped_newer_tag == "v1.0.0-alpha.7"
        assert handed.remote.get("tag") == "v1.0.0-alpha.5"
        # 关于页不会自行拼出「已是最新」文案（摘要由弹窗层负责）。
        assert "已是最新" not in about_page._links_label.text()
        assert handed.update_available is False

    def test_about_error_shows_retry_and_retry_rerequests_new_id(
        self,
        about_page: Any,
        fake_service: FakeUpdateService,
        dialog_calls: dict[str, list[Any]],
    ) -> None:
        """错误弹窗带重试；重试 check_started 更新 _request_id 并通过过滤。"""
        about_page._check_update()
        error = UpdateError("network")
        _emit_result(fake_service, "check-1", info=None, error=error)

        assert len(dialog_calls["error"]) == 1
        captured_error, on_retry = dialog_calls["error"][0]
        assert captured_error is error
        assert callable(on_retry)
        assert about_page._check_update_btn.isEnabled() is True

        fake_service.next_id = "check-2"
        on_retry()
        assert fake_service.check_calls == [True, True]
        assert about_page._request_id == "check-2"
        assert about_page._check_update_btn.isEnabled() is False

        info = _info(reason="none")
        _emit_result(fake_service, "check-2", info=info, error=None)
        assert dialog_calls["no_update"] == [info]

    def test_about_retry_callback_does_not_keep_page_alive(
        self,
        qapp: QApplication,
        monkeypatch: Any,
        fake_service: FakeUpdateService,
        dialog_calls: dict[str, list[Any]],
    ) -> None:
        """错误弹窗的重试回调不得强引用关于页，销毁后调用也不抛异常。"""
        page = _make_page(monkeypatch, fake_service)
        page._check_update()
        _emit_result(
            fake_service, "check-1", info=None, error=UpdateError("timeout")
        )
        on_retry: Callable[[], None] = dialog_calls["error"][0][1]
        page_ref = weakref.ref(page)

        safe_teardown(page)
        drain_deferred_deletes()
        del page
        gc.collect()

        assert page_ref() is None
        on_retry()  # 弱引用失效后安全 no-op

    def test_about_completion_restores_progress_and_button(
        self,
        about_page: Any,
        fake_service: FakeUpdateService,
        dialog_calls: dict[str, list[Any]],
        monkeypatch: Any,
    ) -> None:
        """完成时调用 set_progress(None) 并恢复按钮。"""
        progress_calls: list[float | None] = []
        original = about_page._check_update_btn.set_progress

        def _record(value: float | None) -> None:
            progress_calls.append(value)
            original(value)

        monkeypatch.setattr(about_page._check_update_btn, "set_progress", _record)
        about_page._check_update()
        _emit_result(fake_service, "check-1", info=_info(), error=None)

        assert progress_calls == [0.0, None]
        assert about_page._check_update_btn.isEnabled() is True
        assert about_page._check_update_btn.progress() is None

    def test_about_ignores_startup_results_and_errors(
        self,
        about_page: Any,
        fake_service: FakeUpdateService,
        dialog_calls: dict[str, list[Any]],
    ) -> None:
        """manual=False 的启动结果/错误不触发关于页任何 UI。"""
        _emit_result(
            fake_service,
            "check-1",
            info=_info(update_available=True),
            error=None,
            manual=False,
        )
        _emit_result(
            fake_service,
            "check-1",
            info=None,
            error=UpdateError("network"),
            manual=False,
        )

        assert dialog_calls["no_update"] == []
        assert dialog_calls["error"] == []
        assert dialog_calls["available"] == []
        assert dialog_calls["unavailable"] == []
        assert about_page._check_update_btn.isEnabled() is True
        assert about_page._check_update_btn.progress() is None

    def test_about_startup_in_flight_then_manual_click_handles_manual_result(
        self,
        about_page: Any,
        fake_service: FakeUpdateService,
        dialog_calls: dict[str, list[Any]],
    ) -> None:
        """启动检查在途 + 手动点击：最终收到 manual=True 结果并恢复按钮。"""
        fake_service.emit_started = False
        about_page._check_update()
        assert fake_service.check_calls == [True]
        assert about_page._request_id == "check-1"
        assert about_page._check_update_btn.isEnabled() is False

        info = _info(reason="none")
        _emit_result(fake_service, "check-1", info=info, error=None, manual=True)

        assert dialog_calls["no_update"] == [info]
        assert about_page._check_update_btn.isEnabled() is True

    def test_about_reopen_twice_handles_single_result_without_destroy_error(
        self,
        qapp: QApplication,
        monkeypatch: Any,
        fake_service: FakeUpdateService,
        dialog_calls: dict[str, list[Any]],
    ) -> None:
        """设置窗重开两次：旧页销毁后只剩新页处理一次结果且无回调异常。"""
        first = _make_page(monkeypatch, fake_service)
        first._check_update()
        safe_teardown(first)
        drain_deferred_deletes()
        del first
        gc.collect()

        second = _make_page(monkeypatch, fake_service)
        try:
            second._check_update()
            info = _info(reason="none")
            _emit_result(fake_service, "check-1", info=info, error=None)
            flush_widget_queue(qapp)
            assert dialog_calls["no_update"] == [info]
        finally:
            safe_teardown(second)
            drain_deferred_deletes()

    def test_about_double_click_same_instance_shows_single_dialog(
        self,
        about_page: Any,
        fake_service: FakeUpdateService,
        dialog_calls: dict[str, list[Any]],
    ) -> None:
        """同一实例连点两次只发起一次检查、只弹一个结果框。"""
        about_page._check_update()
        about_page._check_update()
        assert fake_service.check_calls == [True]

        info = _info(reason="none")
        _emit_result(fake_service, "check-1", info=info, error=None)

        assert dialog_calls["no_update"] == [info]

    def test_about_unavailable_only_skips_checking_state(
        self,
        about_page: Any,
        fake_service: FakeUpdateService,
        dialog_calls: dict[str, list[Any]],
        monkeypatch: Any,
    ) -> None:
        """仅 exe 缺失：提示不可用，不调用 check，也不进入检查态。"""
        fake_service.available = False
        progress_calls: list[float | None] = []
        original = about_page._check_update_btn.set_progress

        def _record(value: float | None) -> None:
            progress_calls.append(value)
            original(value)

        monkeypatch.setattr(about_page._check_update_btn, "set_progress", _record)
        about_page._check_update()

        assert fake_service.check_calls == []
        assert len(dialog_calls["unavailable"]) == 1
        assert "不可用" in dialog_calls["unavailable"][0]["title"]
        assert progress_calls == []
        assert about_page._check_update_btn.isEnabled() is True
        assert about_page._check_update_btn.progress() is None

    def test_about_can_check_again_after_uac_cancelled_shutdown(
        self,
        about_page: Any,
        fake_service: FakeUpdateService,
        dialog_calls: dict[str, list[Any]],
    ) -> None:
        """UAC 取消导致服务 shutdown 后 is_available 仍为 True，可再次检查。"""
        about_page._check_update()
        _emit_result(fake_service, "check-1", info=_info(), error=None)
        fake_service.shutdown()
        assert fake_service.available is True

        fake_service.next_id = "check-2"
        about_page._check_update()
        assert fake_service.check_calls == [True, True]
        assert about_page._request_id == "check-2"

        _emit_result(fake_service, "check-2", info=_info(), error=None)
        assert len(dialog_calls["no_update"]) == 2

    def test_about_update_available_hands_off_to_details(
        self,
        about_page: Any,
        fake_service: FakeUpdateService,
        dialog_calls: dict[str, list[Any]],
    ) -> None:
        """有更新时交给 Todo 16 的详情入口，本任务不实现下载。"""
        about_page._check_update()
        info = _info(
            update_available=True,
            reason="newer_version",
            remote={
                "version": "1.0.0-alpha.6",
                "tag": "v1.0.0-alpha.6",
                "date": "2026-06-01",
            },
            asset={
                "name": "FreeAssetFilter-1.0.0-alpha.6_win10_win11_x64_Setup.exe",
                "size": 172000000,
                "sha256": "a" * 64,
            },
        )
        _emit_result(fake_service, "check-1", info=info, error=None)

        assert dialog_calls["available"] == [info]
        assert dialog_calls["no_update"] == []
        assert about_page._check_update_btn.isEnabled() is True


# =============================================================================
# Todo 16 — 更新详情 / 启动提示 / 无更新 / 错误
# =============================================================================

_VALID_RELEASE_URL = (
    "https://github.com/Dorufoc/FreeAssetFilter/releases/tag/v1.0.0-alpha.6"
)


def _available_info(
    *,
    version: str = "1.0.0-alpha.6",
    tag: str = "v1.0.0-alpha.6",
    date: str = "2026-06-01",
    notes: str | None = "修复若干问题。",
    notes_truncated: bool = False,
    html_url: str | None = _VALID_RELEASE_URL,
    skipped: str | None = None,
    asset: Any = ...,
) -> UpdateInfo:
    """构造“有可用更新”的 UpdateInfo 快照。

    Args:
        version: ``remote.version``。
        tag: ``remote.tag``。
        date: ``remote.date``。
        notes: ``remote.notes``；``None`` 表示缺键。
        notes_truncated: 是否标记说明被截断。
        html_url: ``remote.html_url``；``None`` 表示缺键。
        skipped: 被跳过的更新 tag。
        asset: 安装包字典；``...`` 表示使用默认有效资产，``None`` 表示无资产。

    Returns:
        UpdateInfo: 测试快照。
    """
    remote: dict[str, Any] = {"version": version, "tag": tag, "date": date}
    if notes is not None:
        remote["notes"] = notes
    if notes_truncated:
        remote["notes_truncated"] = True
    if html_url is not None:
        remote["html_url"] = html_url
    resolved_asset = (
        {
            "name": "FreeAssetFilter-setup.exe",
            "size": 1024 * 1024,
            "sha256": "a" * 64,
            "download_url": f"{_VALID_RELEASE_URL}/setup.exe",
        }
        if asset is ...
        else asset
    )
    return UpdateInfo(
        local_version="1.0.0-alpha.5",
        local_date="2026-05-22",
        update_available=True,
        reason="newer_version",
        skipped_newer_tag=skipped,
        remote=remote,
        asset=resolved_asset,
    )


@pytest.fixture(autouse=True)
def _cleanup_tracked_dialogs(qapp: QApplication):
    """隔离 update_dialogs 的模块级跟踪表，避免顶层窗口跨测试泄漏。

    Args:
        qapp: 会话级 QApplication。
    """
    ud_mod._active_dialogs.clear()
    ud_mod._active_progress_dialogs.clear()
    yield
    for dialog in list(ud_mod._active_dialogs):
        try:
            dialog._animate = False
            dialog.close()
        except RuntimeError:  # C++ 对象已销毁
            continue
    drain_deferred_deletes(qapp)
    ud_mod._active_dialogs.clear()
    ud_mod._active_progress_dialogs.clear()


class TestUpdateDetailsDialog:
    """show_update_available：详情正文、按钮、URL 与生命周期。"""

    def test_details_title_version_date_and_size(
        self, qapp: QApplication
    ) -> None:
        """标题/版本/构建日期/大小格式正确，notes 以只读纯文本呈现。"""
        dialog = ud_mod.show_update_available(
            _available_info(), on_download=lambda: None
        )

        assert dialog._size == "lg"
        assert "发现新版本" in dialog.windowTitle()
        assert "v1.0.0-alpha.6" in dialog.windowTitle()
        assert dialog._version_label.text() == "版本：v1.0.0-alpha.6"
        assert dialog._date_label.text() == "构建日期：2026-06-01"
        assert "下载更新" in dialog._download_button.text()
        assert "1.0 MB" in dialog._download_button.text()
        assert dialog._download_button.isEnabled() is True
        assert dialog._notes_area.read_only is True
        assert dialog._notes_area.text == "修复若干问题。"
        assert dialog._notes_area.maximumHeight() == 240
        assert dialog in ud_mod._active_dialogs

    def test_details_empty_notes_use_placeholder(self) -> None:
        """空/缺失 notes 显示“该版本未提供更新说明”占位。"""
        for notes in ("", None):
            dialog = ud_mod.show_update_available(
                _available_info(notes=notes), on_download=lambda: None
            )
            assert dialog._notes_area.text == ""
            assert dialog._notes_area.placeholder == "该版本未提供更新说明"
            dialog.close()

    def test_details_notes_truncated_hint(self) -> None:
        """notes_truncated=True 时追加截断提示。"""
        dialog = ud_mod.show_update_available(
            _available_info(notes_truncated=True), on_download=lambda: None
        )

        assert dialog._notes_truncated_label is not None
        assert "截断" in dialog._notes_truncated_label.text()

    @pytest.mark.parametrize(
        "asset",
        [
            None,
            {
                "name": "FreeAssetFilter-setup.exe",
                "size": 1024 * 1024,
                "sha256": None,
                "download_url": "https://example.invalid/setup.exe",
            },
        ],
    )
    def test_details_missing_asset_or_hash_disables_download(
        self, asset: Any
    ) -> None:
        """asset=None / 无 sha256：下载禁用 + 手动下载提示，不抛异常。"""
        dialog = ud_mod.show_update_available(
            _available_info(asset=asset), on_download=lambda: None
        )

        assert dialog._download_button.isEnabled() is False
        assert dialog._manual_hint_label is not None
        assert "手动下载" in dialog._manual_hint_label.text()

    def test_details_without_download_callback_is_safe(self) -> None:
        """on_download=None 时仍渲染按钮但禁用，不崩溃。"""
        dialog = ud_mod.show_update_available(_available_info())

        assert dialog._download_button.isEnabled() is False
        assert dialog._manual_hint_label is not None

    def test_details_each_callback_fires_exactly_once(self) -> None:
        """on_open_release / on_download 各触发一次；下载后关闭对话框。"""
        calls: list[str] = []
        dialog = ud_mod.show_update_available(
            _available_info(),
            on_download=lambda: calls.append("download"),
            on_open_release=lambda: calls.append("open"),
        )

        dialog._open_release_button.click()
        assert calls == ["open"]

        dialog._download_button.click()
        assert calls == ["open", "download"]
        assert dialog not in ud_mod._active_dialogs

    def test_details_later_closes_without_callbacks(self) -> None:
        """稍后按钮只关闭，不触发下载/发布页回调。"""
        calls: list[str] = []
        dialog = ud_mod.show_update_available(
            _available_info(),
            on_download=lambda: calls.append("download"),
            on_open_release=lambda: calls.append("open"),
        )

        dialog._later_button.click()

        assert calls == []
        assert dialog not in ud_mod._active_dialogs

    def test_details_unsafe_html_url_falls_back_to_releases_url(
        self, monkeypatch: Any
    ) -> None:
        """file:/// URL 被拒绝，openUrl 只收到版本常量。"""
        opened: list[str] = []

        class _Desktop:
            @staticmethod
            def openUrl(url: Any) -> None:
                opened.append(url.toString())

        monkeypatch.setattr(ud_mod, "QDesktopServices", _Desktop)

        dialog = ud_mod.show_update_available(
            _available_info(html_url="file:///C:/evil.exe")
        )
        dialog._open_release_button.click()

        assert opened == [RELEASES_URL]

    def test_details_allowlisted_html_url_is_used(
        self, monkeypatch: Any
    ) -> None:
        """允许列表内的 releases 详情 URL 原样打开。"""
        opened: list[str] = []

        class _Desktop:
            @staticmethod
            def openUrl(url: Any) -> None:
                opened.append(url.toString())

        monkeypatch.setattr(ud_mod, "QDesktopServices", _Desktop)

        dialog = ud_mod.show_update_available(
            _available_info(html_url=_VALID_RELEASE_URL)
        )
        dialog._open_release_button.click()

        assert opened == [_VALID_RELEASE_URL]

    def test_details_skipped_tag_appended(
        self, qapp: QApplication
    ) -> None:
        """skipped_newer_tag 非空时详情追加被跳过/当前可用 tag 说明。"""
        info = _available_info(
            version="1.0.0-alpha.5",
            tag="v1.0.0-alpha.5",
            skipped="v1.0.0-alpha.7",
        )
        dialog = ud_mod.show_update_available(info)

        assert dialog._skipped_label is not None
        text = dialog._skipped_label.text()
        assert "v1.0.0-alpha.7" in text
        assert "v1.0.0-alpha.5" in text
        assert "暂无安装包" in text

    def test_details_returned_dialog_stays_alive_and_untracks(
        self, qapp: QApplication
    ) -> None:
        """返回后仍在 _active_dialogs；关闭/销毁后自动移除。"""
        dialog = ud_mod.show_update_available(_available_info())
        assert dialog in ud_mod._active_dialogs

        dialog._animate = False
        dialog.close()
        assert dialog not in ud_mod._active_dialogs

        destroyed = ud_mod.show_update_available(_available_info())
        assert destroyed in ud_mod._active_dialogs
        destroyed.deleteLater()
        drain_deferred_deletes(qapp)
        assert destroyed not in ud_mod._active_dialogs

    def test_details_callbacks_survive_about_page_destruction(
        self,
        monkeypatch: Any,
        fake_service: FakeUpdateService,
    ) -> None:
        """销毁关于页后点击详情按钮不抛异常（闭包不捕获 QWidget）。"""
        opened: list[str] = []

        class _Desktop:
            @staticmethod
            def openUrl(url: Any) -> None:
                opened.append(url.toString())

        monkeypatch.setattr(ud_mod, "QDesktopServices", _Desktop)
        page = _make_page(monkeypatch, fake_service)
        dialog = ud_mod.show_update_available(_available_info())

        safe_teardown(page)
        drain_deferred_deletes()
        del page
        gc.collect()

        dialog._open_release_button.click()
        dialog._later_button.click()
        assert dialog not in ud_mod._active_dialogs
        assert opened == [_VALID_RELEASE_URL]

    def test_details_bound_page_callbacks_are_weak(
        self,
        qapp: QApplication,
        monkeypatch: Any,
        fake_service: FakeUpdateService,
    ) -> None:
        """详情回调为页面绑定方法时按弱引用保存，页面销毁后点击安全。"""
        opened: list[str] = []

        class _Desktop:
            @staticmethod
            def openUrl(url: Any) -> None:
                opened.append(url.toString())

        monkeypatch.setattr(ud_mod, "QDesktopServices", _Desktop)
        page = _make_page(monkeypatch, fake_service)
        info = _available_info()
        dialog = ud_mod.show_update_available(
            info,
            on_download=page._retry_check,
            on_open_release=page._retry_check,
        )

        safe_teardown(page)
        drain_deferred_deletes()
        del page
        gc.collect()

        dialog._open_release_button.click()
        dialog._download_button.click()
        assert dialog not in ud_mod._active_dialogs
        assert opened == []


class TestStartupUpdateDialog:
    """show_startup_update：启动提示、查看详情与稍后。"""

    def test_startup_title_and_body(
        self, qapp: QApplication
    ) -> None:
        """标题为“发现新版本 vX”，正文含当前/新版本。"""
        parent = QWidget()
        try:
            dialog = ud_mod.show_startup_update(
                parent,
                _available_info(version="1.0.0-alpha.6", tag="v1.0.0-alpha.6"),
            )
        finally:
            safe_teardown(parent)

        assert "发现新版本" in dialog.windowTitle()
        assert "v1.0.0-alpha.6" in dialog.windowTitle()
        assert "v1.0.0-alpha.5" in dialog._body_label.text()
        assert "v1.0.0-alpha.6" in dialog._body_label.text()
        assert dialog in ud_mod._active_dialogs

    def test_startup_view_details_opens_details(
        self, qapp: QApplication, monkeypatch: Any
    ) -> None:
        """查看详情复用 show_update_available 并关闭启动提示。"""
        received: list[UpdateInfo] = []
        monkeypatch.setattr(
            ud_mod,
            "show_update_available",
            lambda info: received.append(info),
        )
        info = _available_info()
        parent = QWidget()
        try:
            dialog = ud_mod.show_startup_update(parent, info)
            dialog._details_button.click()
        finally:
            safe_teardown(parent)

        assert received == [info]
        assert dialog not in ud_mod._active_dialogs

    def test_startup_later_does_not_open_details(
        self, qapp: QApplication, monkeypatch: Any
    ) -> None:
        """稍后关闭提示且不打开详情。"""
        received: list[UpdateInfo] = []
        monkeypatch.setattr(
            ud_mod,
            "show_update_available",
            lambda info: received.append(info),
        )
        parent = QWidget()
        try:
            dialog = ud_mod.show_startup_update(parent, _available_info())
            dialog._later_button.click()
        finally:
            safe_teardown(parent)

        assert received == []
        assert dialog not in ud_mod._active_dialogs

    def test_startup_skipped_tag_appended(self, qapp: QApplication) -> None:
        """启动提示同样追加 skipped/current tag 说明。"""
        info = _available_info(
            version="1.0.0-alpha.5",
            tag="v1.0.0-alpha.5",
            skipped="v1.0.0-alpha.7",
        )
        parent = QWidget()
        try:
            dialog = ud_mod.show_startup_update(parent, info)
        finally:
            safe_teardown(parent)

        text = dialog._body_label.text()
        assert "v1.0.0-alpha.7" in text
        assert "v1.0.0-alpha.5" in text
        assert "暂无安装包" in text


class TestNoUpdateDialog:
    """show_no_update：版本与 skipped tag 文案。"""

    def test_no_update_includes_current_version(self) -> None:
        """无 skipped tag：正文含当前版本与“已是最新”。"""
        dialog = ud_mod.show_no_update(_info(reason="none"))

        text = dialog._message_label.text()
        assert "v1.0.0-alpha.5" in text
        assert "已是最新" in text
        assert dialog in ud_mod._active_dialogs

    def test_no_update_skipped_tag_does_not_claim_latest(self) -> None:
        """skipped tag 非空：同时报两个 tag，且不宣称“已是最新”。"""
        info = _info(
            reason="local_newer",
            skipped_newer_tag="v1.0.0-alpha.7",
            remote={
                "version": "1.0.0-alpha.5",
                "tag": "v1.0.0-alpha.5",
                "date": "2026-05-22",
            },
        )
        dialog = ud_mod.show_no_update(info)

        text = dialog._message_label.text()
        assert "v1.0.0-alpha.7" in text
        assert "v1.0.0-alpha.5" in text
        assert "暂无安装包" in text
        assert "已是最新" not in text
        assert "已是最新" not in dialog.windowTitle()


class TestCheckErrorDialog:
    """show_check_error：可读错误、重试与弱引用。"""

    def test_error_shows_readable_message_and_retry(
        self, qapp: QApplication
    ) -> None:
        """错误文案用户可读（无 traceback），重试恰触发一次并关闭。"""
        calls: list[str] = []
        dialog = ud_mod.show_check_error(
            UpdateError("network"), lambda: calls.append("retry")
        )

        text = dialog._message_label.text()
        assert "网络连接失败" in text
        assert "Traceback" not in text

        dialog._retry_button.click()
        assert calls == ["retry"]
        assert dialog not in ud_mod._active_dialogs

    def test_error_retry_uses_weak_bound_method(
        self,
        qapp: QApplication,
        monkeypatch: Any,
        fake_service: FakeUpdateService,
    ) -> None:
        """绑定方法按弱引用保存：关于页销毁后点击重试安全 no-op。"""
        page = _make_page(monkeypatch, fake_service)
        dialog = ud_mod.show_check_error(
            UpdateError("timeout"), page._retry_check
        )

        safe_teardown(page)
        drain_deferred_deletes()
        del page
        gc.collect()

        dialog._retry_button.click()
        assert dialog not in ud_mod._active_dialogs


# =============================================================================
# Todo 17 — 下载进度 / 暂停 / 继续 / 取消
# =============================================================================


def _download_dialog(
    service: FakeUpdateService,
    info: UpdateInfo | None = None,
    *,
    state: tuple[str, int, int] | None = None,
    request_id: str = "download-1",
) -> Any:
    """构造进度对话框并准备服务状态。

    Args:
        service: 假更新服务。
        info: 下载元数据；``None`` 使用默认有效资产。
        state: 可选的 ``(state, downloaded, total)`` 初始化状态。
        request_id: 假服务返回的请求 id。

    Returns:
        Any: 已显示并登记的进度对话框。
    """
    service.next_download_id = request_id
    if state is not None:
        service.download_states[request_id] = state
    return ud_mod.show_download_progress(info or _available_info(), service)


class TestDownloadProgressDialog:
    """进度对话框：初始化、信号、暂停/继续/取消与关闭语义。"""

    def test_progress_starts_download_before_construct(
        self, qapp: QApplication, fake_service: FakeUpdateService
    ) -> None:
        """先 start_download，再读取状态构造并跟踪。"""
        info = _available_info()
        dialog = _download_dialog(fake_service, info)

        assert fake_service.start_download_calls == [info]
        assert fake_service.download_event_order[:2] == ["start", "state"]
        assert dialog._request_id == "download-1"
        assert dialog in ud_mod._active_dialogs
        assert ud_mod._active_progress_dialogs["download-1"] is dialog
        assert dialog.isVisible() is True

    def test_progress_single_dialog_per_request_is_reused(
        self, qapp: QApplication, fake_service: FakeUpdateService
    ) -> None:
        """同一 request_id 只创建一个对话框，第二次调用原样返回。"""
        first = _download_dialog(fake_service)
        second = ud_mod.show_download_progress(_available_info(), fake_service)

        assert second is first
        assert len(fake_service.start_download_calls) == 2
        assert list(ud_mod._active_progress_dialogs) == ["download-1"]
        assert ud_mod._active_progress_dialogs["download-1"] is first

    def test_progress_paused_initial_state_preserves_downloaded(
        self, qapp: QApplication, fake_service: FakeUpdateService
    ) -> None:
        """paused 初始化：显示继续、保留已下载字节与进度。"""
        dialog = _download_dialog(
            fake_service,
            state=("paused", 512 * 1024, 1024 * 1024),
        )

        assert dialog._state == "paused"
        assert dialog._progress.value == pytest.approx(0.5)
        assert dialog._progress._value_label.text() == "50%"
        assert "0.5 MB" in dialog._stats_label.text()
        assert "1.0 MB" in dialog._stats_label.text()
        assert dialog._state_label.text() == "已暂停"
        assert dialog._pause_button.text() == "继续"
        assert dialog._pause_button.isEnabled() is True

    def test_progress_signal_updates_progress_percent_and_speed(
        self, qapp: QApplication, fake_service: FakeUpdateService
    ) -> None:
        """进度信号更新百分比、MB 与速度标签。"""
        dialog = _download_dialog(fake_service)
        fake_service.download_started.emit("download-1")
        fake_service.download_progress.emit(
            "download-1", 512 * 1024, 1024 * 1024, 1024 * 1024
        )

        assert dialog._progress.value == pytest.approx(0.5)
        assert dialog._progress._value_label.text() == "50%"
        stats = dialog._stats_label.text()
        assert "0.5 MB" in stats
        assert "1.0 MB" in stats
        assert "1.0 MB/s" in stats
        assert dialog._state_label.text() == "下载中"

    def test_progress_ignores_signals_for_other_request_ids(
        self, qapp: QApplication, fake_service: FakeUpdateService
    ) -> None:
        """其他 request_id 的进度/状态信号不得影响本对话框。"""
        dialog = _download_dialog(fake_service)
        fake_service.download_progress.emit(
            "download-9", 1024 * 1024, 1024 * 1024, 0.0
        )
        fake_service.download_state_changed.emit("download-9", "verifying")

        assert dialog._progress.value == pytest.approx(0.0)
        assert dialog._state == "running"
        assert dialog._pause_button.isEnabled() is True

    def test_progress_pause_pending_until_ack_and_paused_state(
        self, qapp: QApplication, fake_service: FakeUpdateService
    ) -> None:
        """暂停先变“暂停中…”并异步调用；ack+state 后才显示继续。"""
        dialog = _download_dialog(fake_service)
        fake_service.download_started.emit("download-1")

        dialog._pause_button.click()
        assert dialog._pause_button.text() == "暂停中…"
        assert dialog._pause_button.isEnabled() is False
        assert fake_service.pause_calls == []

        qapp.processEvents()
        assert fake_service.pause_calls == ["download-1"]

        fake_service.download_pause_acked.emit("download-1", True)
        assert dialog._pause_button.text() == "暂停中…"

        fake_service.download_state_changed.emit("download-1", "paused")
        assert dialog._pause_button.text() == "继续"
        assert dialog._pause_button.isEnabled() is True
        assert dialog._state_label.text() == "已暂停"

    def test_progress_pause_ack_false_restores_and_hints(
        self, qapp: QApplication, fake_service: FakeUpdateService
    ) -> None:
        """accepted=False 恢复“暂停”并提示校验中无法暂停。"""
        dialog = _download_dialog(fake_service)
        fake_service.download_started.emit("download-1")
        dialog._pause_button.click()
        qapp.processEvents()

        fake_service.download_pause_acked.emit("download-1", False)

        assert dialog._pause_button.text() == "暂停"
        assert dialog._pause_button.isEnabled() is True
        assert dialog._hint_label.isVisible() is True
        assert "校验中，无法暂停" in dialog._hint_label.text()
        assert dialog._state != "paused"

    def test_progress_verifying_disables_pause(
        self, qapp: QApplication, fake_service: FakeUpdateService
    ) -> None:
        """verifying 阶段禁用暂停；随后 false ack 仍保持禁用。"""
        dialog = _download_dialog(fake_service)
        fake_service.download_state_changed.emit("download-1", "verifying")

        assert dialog._pause_button.isEnabled() is False
        assert "校验中" in dialog._state_label.text()

        fake_service.download_pause_acked.emit("download-1", False)
        assert dialog._pause_button.text() == "暂停"
        assert dialog._pause_button.isEnabled() is False

    def test_progress_resume_uses_same_request_id_async(
        self, qapp: QApplication, fake_service: FakeUpdateService
    ) -> None:
        """继续异步调用 resume_download，使用同一 id 且不创建新对话框。"""
        dialog = _download_dialog(
            fake_service,
            state=("paused", 512 * 1024, 1024 * 1024),
        )

        dialog._pause_button.click()
        assert fake_service.resume_calls == []
        qapp.processEvents()

        assert fake_service.resume_calls == ["download-1"]
        assert dialog._request_id == "download-1"
        assert ud_mod._active_progress_dialogs["download-1"] is dialog
        assert dialog._state == "running"
        assert dialog._pause_button.text() == "暂停"
        assert dialog._pause_button.isEnabled() is True

    def test_progress_cancel_async_and_cancelled_closes_silently(
        self,
        qapp: QApplication,
        fake_service: FakeUpdateService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """取消异步调用；cancelled 静默关闭且不显示错误、不触发安装。"""
        install_calls: list[tuple[object, str]] = []
        monkeypatch.setattr(
            ud_mod,
            "show_install_confirm",
            lambda info, path: install_calls.append((info, path)),
        )
        dialog = _download_dialog(fake_service)
        finished_calls: list[int] = []
        dialog.finished.connect(finished_calls.append)

        dialog._cancel_button.click()
        assert fake_service.cancel_calls == []
        qapp.processEvents()
        assert fake_service.cancel_calls == ["download-1"]
        assert dialog._cancel_button.isEnabled() is False

        fake_service.download_failed.emit(
            "download-1", UpdateError("cancelled")
        )

        assert dialog._download_active is False
        assert dialog not in ud_mod._active_dialogs
        assert "download-1" not in ud_mod._active_progress_dialogs
        assert dialog._error_label.text() == ""
        assert finished_calls == [0]
        assert install_calls == []


    def test_progress_close_while_active_pauses_without_finished(
        self, qapp: QApplication, fake_service: FakeUpdateService
    ) -> None:
        """下载中关闭：隐藏、断开、解除跟踪、异步暂停，且不发 finished。"""
        dialog = _download_dialog(fake_service)
        finished_calls: list[int] = []
        dialog.finished.connect(finished_calls.append)

        dialog.close()
        assert dialog.isVisible() is False
        assert dialog not in ud_mod._active_dialogs
        assert "download-1" not in ud_mod._active_progress_dialogs

        # _closing 守卫：再次收到关闭事件仍 ignore，且不重复暂停。
        second = QCloseEvent()
        dialog.closeEvent(second)
        assert second.isAccepted() is False

        qapp.processEvents()
        assert fake_service.pause_calls == ["download-1"]
        assert finished_calls == []

    def test_progress_close_does_not_deliver_late_finished(
        self,
        qapp: QApplication,
        fake_service: FakeUpdateService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """关闭后迟到的 download_finished 不重开、不安装。"""
        install_calls: list[tuple[object, str]] = []
        monkeypatch.setattr(
            ud_mod,
            "show_install_confirm",
            lambda info, path: install_calls.append((info, path)),
        )
        dialog = _download_dialog(fake_service)
        dialog.close()
        assert dialog.isVisible() is False
        qapp.processEvents()

        fake_service.download_finished.emit("download-1", r"C:\tmp\setup.exe")

        assert ud_mod._active_dialogs == set()
        assert ud_mod._active_progress_dialogs == {}
        assert install_calls == []

    def test_progress_paused_late_finished_is_ignored(

        self, qapp: QApplication, fake_service: FakeUpdateService
    ) -> None:
        """已暂停的对话框收到迟到 finished 不关闭、不进入完成态。"""
        dialog = _download_dialog(
            fake_service,
            state=("paused", 512 * 1024, 1024 * 1024),
        )

        fake_service.download_finished.emit("download-1", r"C:\tmp\setup.exe")

        assert dialog._download_active is True
        assert ud_mod._active_progress_dialogs["download-1"] is dialog
        assert dialog._state == "paused"
        assert dialog._state_label.text() == "已暂停"

    def test_progress_reopen_after_close_uses_same_paused_state(
        self, qapp: QApplication, fake_service: FakeUpdateService
    ) -> None:
        """关闭后重开拿到同一 paused id，并按已下载字节初始化。"""
        first = _download_dialog(
            fake_service,
            state=("paused", 512 * 1024, 1024 * 1024),
        )
        first.close()
        qapp.processEvents()

        second = ud_mod.show_download_progress(_available_info(), fake_service)

        assert second is not first
        assert second._request_id == "download-1"
        assert ud_mod._active_progress_dialogs["download-1"] is second
        assert second._state_label.text() == "已暂停"
        assert second._pause_button.text() == "继续"
        assert second._progress.value == pytest.approx(0.5)
        assert dialog_state_text(second) == "50%"

    def test_progress_finished_closes_and_emits_finished_once(
        self,
        qapp: QApplication,
        fake_service: FakeUpdateService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """磁盘完成：先解除活动/跟踪再关闭，恰好一次 finished，并交给安装确认。"""
        install_calls: list[tuple[object, str]] = []
        monkeypatch.setattr(
            ud_mod,
            "show_install_confirm",
            lambda info, path: install_calls.append((info, path)),
        )
        info = _available_info()
        dialog = _download_dialog(fake_service, info=info)
        finished_calls: list[int] = []
        dialog.finished.connect(finished_calls.append)

        installer_path = r"C:\tmp\FreeAssetFilter-setup.exe"
        fake_service.download_finished.emit("download-1", installer_path)

        assert dialog._download_active is False
        assert dialog not in ud_mod._active_dialogs
        assert "download-1" not in ud_mod._active_progress_dialogs
        assert finished_calls == [0]
        assert install_calls == [(info, installer_path)]

        dialog.close()
        assert finished_calls == [0]
        assert install_calls == [(info, installer_path)]

    def test_progress_finished_single_emission_with_animate_true(
        self,
        qapp: QApplication,
        fake_service: FakeUpdateService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """animate=True：首次关闭忽略、动画结束只发一次 finished 并确认安装。"""
        install_calls: list[tuple[object, str]] = []
        monkeypatch.setattr(
            ud_mod,
            "show_install_confirm",
            lambda info, path: install_calls.append((info, path)),
        )
        info = _available_info()
        dialog = ud_mod._DownloadProgressDialog(
            info, fake_service, "download-1", animate=True
        )
        dialog.show()
        dialog._download_active = True
        finished_calls: list[int] = []
        dialog.finished.connect(finished_calls.append)

        installer_path = r"C:\tmp\FreeAssetFilter-setup.exe"
        fake_service.download_finished.emit("download-1", installer_path)
        assert finished_calls == []
        assert install_calls == []

        QTest.qWait(400)
        assert finished_calls == [0]
        assert install_calls == [(info, installer_path)]


    def test_progress_failed_shows_error_and_retry(
        self, qapp: QApplication, fake_service: FakeUpdateService
    ) -> None:
        """失败显示中文错误与重试；关闭失败对话框不调用暂停。"""
        dialog = _download_dialog(fake_service)

        fake_service.download_failed.emit(
            "download-1", UpdateError("checksum_mismatch")
        )

        assert dialog._download_active is False
        assert dialog not in ud_mod._active_dialogs
        assert "download-1" not in ud_mod._active_progress_dialogs
        assert dialog._error_label.isVisible() is True
        assert "校验失败" in dialog._error_label.text()
        assert dialog._retry_button.isVisible() is True
        assert dialog._retry_button.isEnabled() is True
        assert dialog._pause_button.isVisible() is False
        assert dialog._state_label.text() == "下载失败"
        assert dialog._cancel_button.text() == "关闭"

        dialog._cancel_button.click()
        dialog.close()
        qapp.processEvents()
        assert fake_service.pause_calls == []

    def test_progress_failure_retry_starts_new_download(
        self, qapp: QApplication, fake_service: FakeUpdateService
    ) -> None:
        """重试关闭旧对话框并重新 start_download（新 id）。"""
        dialog = _download_dialog(fake_service)
        fake_service.download_failed.emit(
            "download-1", UpdateError("network")
        )
        fake_service.next_download_id = "download-2"

        dialog._retry_button.click()
        qapp.processEvents()

        assert len(fake_service.start_download_calls) == 2
        assert "download-2" in ud_mod._active_progress_dialogs
        assert dialog not in ud_mod._active_dialogs


class _FakeInstallerLauncher(QObject):
    """可观察的 InstallerLauncher 替身。"""

    finished = Signal(object)
    instances: list["_FakeInstallerLauncher"] = []

    def __init__(self, service: object) -> None:
        super().__init__()
        self.service = service
        self.start_calls: list[tuple[str, str]] = []
        self.instances.append(self)

    def start(self, installer_path: str, sha256: str) -> bool:
        """记录启动参数并返回成功。"""
        self.start_calls.append((installer_path, sha256))
        return True


def _confirm_dialog() -> Any:
    """返回当前活动的安装确认对话框。"""
    for dialog in ud_mod._active_dialogs:
        if isinstance(dialog, ud_mod._InstallConfirmDialog):
            return dialog
    raise AssertionError("install confirm dialog not found")


class TestInstallConfirmDialog:
    """安装确认：取消、ESC、缺数据、有效确认与等待 worker。"""

    def test_cancel_returns_false(self, qapp: QApplication) -> None:
        """取消按钮关闭对话框并返回 False。"""
        def cancel() -> None:
            _confirm_dialog()._cancel_button.click()

        QTimer.singleShot(0, cancel)
        assert ud_mod.show_install_confirm(
            _available_info(), r"C:\tmp\setup.exe"
        ) is False

    def test_escape_cancels(self, qapp: QApplication) -> None:
        """ESC 等价取消并发出 finished。"""
        dialog = ud_mod._InstallConfirmDialog(
            _available_info(), r"C:\tmp\setup.exe"
        )
        finished: list[int] = []
        dialog.finished.connect(finished.append)
        dialog.show_dialog()

        event = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.NoModifier
        )
        dialog.keyPressEvent(event)

        assert event.isAccepted() is True
        assert finished == [0]
        assert dialog.isVisible() is False

    def test_missing_asset_disables_confirm(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """资产缺 sha/size 时确认禁用，取消返回 False 且不创建 launcher。"""
        info = _available_info(asset=None)
        failures: list[str] = []
        monkeypatch.setattr(ud_mod, "show_install_failure", failures.append)
        _FakeInstallerLauncher.instances.clear()
        monkeypatch.setattr(
            ud_mod, "InstallerLauncher", _FakeInstallerLauncher
        )
        observed: dict[str, Any] = {}

        def inspect_and_cancel() -> None:
            dialog = _confirm_dialog()
            observed["enabled"] = dialog._confirm_button.isEnabled()
            observed["status"] = dialog._status_label.text()
            dialog._cancel_button.click()

        QTimer.singleShot(0, inspect_and_cancel)
        assert ud_mod.show_install_confirm(info, r"C:\tmp\setup.exe") is False

        assert observed["enabled"] is False
        assert "不完整" in observed["status"]
        assert failures == []
        assert _FakeInstallerLauncher.instances == []

    @pytest.mark.parametrize(
        "asset",
        [
            {"size": 1024},
            {"sha256": "a" * 64},
        ],
    )
    def test_missing_sha_or_size_disables_confirm(
        self,
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
        asset: dict[str, Any],
    ) -> None:
        """只缺 sha256 或只缺 size 时同样禁用确认。"""
        info = _available_info(asset=asset)
        _FakeInstallerLauncher.instances.clear()
        monkeypatch.setattr(
            ud_mod, "InstallerLauncher", _FakeInstallerLauncher
        )
        observed: dict[str, Any] = {}

        def inspect_and_cancel() -> None:
            dialog = _confirm_dialog()
            observed["enabled"] = dialog._confirm_button.isEnabled()
            observed["status"] = dialog._status_label.text()
            dialog._cancel_button.click()

        QTimer.singleShot(0, inspect_and_cancel)
        assert ud_mod.show_install_confirm(info, r"C:\tmp\setup.exe") is False

        assert observed["enabled"] is False
        assert "不完整" in observed["status"]
        assert _FakeInstallerLauncher.instances == []

    def test_synchronous_finished_does_not_reenter_loop(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """launcher 在 start 内同步 emit 时不再进入第二个事件循环。"""

        class _SyncLauncher(_FakeInstallerLauncher):
            def start(self, installer_path: str, sha256: str) -> bool:
                self.start_calls.append((installer_path, sha256))
                self.finished.emit(
                    (installer_path, True, True, True, None, None, None)
                )
                return True

        info = _available_info()
        monkeypatch.setattr(ud_mod, "get_update_service", lambda: object())
        _FakeInstallerLauncher.instances.clear()
        monkeypatch.setattr(ud_mod, "InstallerLauncher", _SyncLauncher)

        QTimer.singleShot(0, lambda: _confirm_dialog()._confirm_button.click())
        assert ud_mod.show_install_confirm(info, r"C:\tmp\setup.exe") is True

    def test_valid_starts_launcher_and_waits_for_finish(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """有效确认创建 launcher；对话框保持到 finished 后才关闭。"""
        info = _available_info()
        service = object()
        monkeypatch.setattr(ud_mod, "get_update_service", lambda: service)
        _FakeInstallerLauncher.instances.clear()
        monkeypatch.setattr(
            ud_mod, "InstallerLauncher", _FakeInstallerLauncher
        )
        observed: dict[str, Any] = {}

        def confirm() -> None:
            dialog = _confirm_dialog()
            dialog._confirm_button.click()
            launcher = _FakeInstallerLauncher.instances[-1]
            observed["dialog"] = dialog
            observed["visible"] = dialog.isVisible()
            observed["start"] = list(launcher.start_calls)
            observed["service"] = launcher.service
            QTimer.singleShot(0, lambda: launcher.finished.emit((None,) * 7))

        QTimer.singleShot(0, confirm)
        result = ud_mod.show_install_confirm(info, r"C:\tmp\setup.exe")

        assert result is True
        assert observed["visible"] is True
        assert observed["start"] == [(r"C:\tmp\setup.exe", "a" * 64)]
        assert observed["service"] is service
        assert observed["dialog"].isVisible() is False


class TestInstallNotices:
    """安装失败与 UAC 取消提示。"""

    def test_failure_dialog_is_readable_and_closes(
        self, qapp: QApplication
    ) -> None:
        """失败提示显示原文并可关闭。"""
        dialog = ud_mod.show_install_failure("磁盘空间不足")

        assert dialog.isVisible() is True
        assert dialog in ud_mod._active_dialogs
        assert dialog._message_label.text() == "磁盘空间不足"

        dialog._close_button.click()
        assert dialog not in ud_mod._active_dialogs

    def test_uac_cancelled_opens_only_folder(
        self,
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Any,
    ) -> None:
        """UAC 取消提示非模态，只提供打开所在文件夹。"""
        opened: list[Any] = []

        class FakeDesktop:
            @staticmethod
            def openUrl(url: Any) -> None:
                opened.append(url)

        monkeypatch.setattr(ud_mod, "QDesktopServices", FakeDesktop)
        path = tmp_path / "download" / "setup.exe"
        dialog = ud_mod.show_uac_cancelled(str(path))

        assert dialog.isVisible() is True
        assert dialog in ud_mod._active_dialogs
        assert "setup.exe" in dialog._path_label.text()

        dialog._open_folder_button.click()
        assert len(opened) == 1
        assert Path(opened[0].toLocalFile()) == (tmp_path / "download").resolve()

        dialog._close_button.click()
        assert dialog not in ud_mod._active_dialogs


def dialog_state_text(dialog: Any) -> str:
    """返回 StyledProgress 顶部值标签文本。"""
    return dialog._progress._value_label.text()
