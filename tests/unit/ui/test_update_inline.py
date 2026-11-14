# -*- coding: utf-8 -*-
"""关于页内联更新会话测试。"""

from __future__ import annotations

import time
from typing import Any

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import sopeek.ui.update_inline as ui_mod
from sopeek.services.update_service import UpdateError, UpdateInfo
from sopeek.ui.update_inline import InlineUpdateSession

pytestmark = pytest.mark.unit


class FakeUpdateService(QObject):
    """与生产契约一致的最小更新服务替身。"""

    check_started = Signal(str, bool)
    check_finished = Signal(str, bool, object, object)
    download_progress = Signal(str, object, object, float)
    download_state_changed = Signal(str, str)
    download_finished = Signal(str, str)
    download_failed = Signal(str, object)

    def __init__(self) -> None:
        super().__init__()
        self.available = True
        self.next_check_id = "check-1"
        self.next_download_id = "download-1"
        self.emit_started = True
        self.check_calls: list[bool] = []
        self.include_prerelease_calls: list[bool] = []
        self.start_download_calls: list[UpdateInfo] = []
        self.download_states: dict[str, tuple[str, int, int]] = {}
        self.cleared = False

    def is_available(self) -> bool:
        return self.available

    def check(self, manual: bool = False, include_prerelease: bool = True) -> str:
        self.check_calls.append(bool(manual))
        self.include_prerelease_calls.append(bool(include_prerelease))
        if self.emit_started:
            self.check_started.emit(self.next_check_id, bool(manual))
        return self.next_check_id

    def start_download(self, info: UpdateInfo) -> str:
        self.start_download_calls.append(info)
        request_id = self.next_download_id
        size = int((info.asset or {}).get("size") or 0)
        self.download_states[request_id] = ("running", 0, size)
        return request_id

    def get_download_state(
        self, request_id: str
    ) -> tuple[str, int, int] | None:
        return self.download_states.get(request_id)


def _info(
    *,
    update_available: bool = False,
    version: str = "1.0.0-alpha.6",
    asset: dict[str, Any] | None = ...,
) -> UpdateInfo:
    """构造更新快照。"""
    resolved_asset = (
        {
            "name": "Sopeek_Setup.exe",
            "size": 100,
            "sha256": "a" * 64,
        }
        if asset is ...
        else asset
    )
    return UpdateInfo(
        local_version="1.0.0-alpha.5",
        local_date="2026-05-22",
        update_available=update_available,
        reason="newer_version" if update_available else "none",
        skipped_newer_tag=None,
        remote={"version": version, "tag": f"v{version}"},
        asset=resolved_asset,
    )


@pytest.fixture
def service(qapp: QApplication) -> FakeUpdateService:
    del qapp
    return FakeUpdateService()


@pytest.fixture
def marker(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, str]]:
    """替换待安装标记写入并记录调用。"""
    calls: list[tuple[Any, str]] = []
    monkeypatch.setattr(
        ui_mod,
        "write_pending_update",
        lambda info, path: calls.append((info, path)) or True,
    )
    return calls


@pytest.fixture
def session(
    qapp: QApplication, service: FakeUpdateService
) -> InlineUpdateSession:
    del qapp
    instance = InlineUpdateSession(service_factory=lambda: service)
    instance.MIN_CHECKING_VISIBLE_MS = 0
    try:
        yield instance
    finally:
        instance.dispose()


def _finish_check(
    service: FakeUpdateService,
    session: InlineUpdateSession,
    *,
    info: UpdateInfo | None,
    error: UpdateError | None = None,
    request_id: str = "check-1",
) -> None:
    """清除最短展示时长后发送检查结果。"""
    session._checking_shown_at = 0.0
    service.check_finished.emit(request_id, True, info, error)


class TestCheckFlow:
    """检查阶段状态与结果过滤。"""

    def test_start_check_emits_checking(
        self, session: InlineUpdateSession, service: FakeUpdateService
    ) -> None:
        seen: list[bool] = []
        session.checking.connect(lambda: seen.append(True))

        session.start_check()

        assert seen == [True]
        assert service.check_calls == [True]
        assert session.snapshot()["state"] == ui_mod.STATE_CHECKING
        assert session._request_id == "check-1"

    def test_repeat_start_is_ignored(
        self, session: InlineUpdateSession, service: FakeUpdateService
    ) -> None:
        session.start_check()
        session.start_check()

        assert service.check_calls == [True]

    def test_up_to_date_result(
        self, session: InlineUpdateSession, service: FakeUpdateService
    ) -> None:
        results: list[UpdateInfo] = []
        session.up_to_date.connect(results.append)
        session.start_check()

        _finish_check(service, session, info=_info())

        assert results and results[0].update_available is False
        assert session.snapshot()["state"] == ui_mod.STATE_UP_TO_DATE

    def test_check_error(
        self, session: InlineUpdateSession, service: FakeUpdateService
    ) -> None:
        errors: list[UpdateError] = []
        session.check_failed.connect(errors.append)
        session.start_check()

        _finish_check(
            service, session, info=None, error=UpdateError("network")
        )

        assert errors and errors[0].code == "network"
        assert session.snapshot()["state"] == ui_mod.STATE_CHECK_FAILED

    def test_unavailable_service_reports_error(
        self, session: InlineUpdateSession, service: FakeUpdateService
    ) -> None:
        errors: list[UpdateError] = []
        session.check_failed.connect(errors.append)
        service.available = False

        session.start_check()

        assert service.check_calls == []
        assert errors and errors[0].code == "unavailable"

    def test_minimum_checking_duration(
        self, session: InlineUpdateSession, service: FakeUpdateService
    ) -> None:
        session.MIN_CHECKING_VISIBLE_MS = 120
        session.start_check()
        service.check_finished.emit("check-1", True, _info(), None)

        assert session.snapshot()["state"] == ui_mod.STATE_CHECKING
        deadline = time.monotonic() + 2.0
        while (
            session.snapshot()["state"] == ui_mod.STATE_CHECKING
            and time.monotonic() < deadline
        ):
            QTest.qWait(20)
        assert session.snapshot()["state"] == ui_mod.STATE_UP_TO_DATE


class TestDownloadFlow:
    """自动下载、进度、完成登记与失败映射。"""

    def test_update_available_starts_download(
        self,
        session: InlineUpdateSession,
        service: FakeUpdateService,
        marker: list[tuple[Any, str]],
    ) -> None:
        started: list[UpdateInfo] = []
        progress: list[tuple[int, int]] = []
        session.download_started.connect(started.append)
        session.download_progress.connect(
            lambda downloaded, total: progress.append((downloaded, total))
        )
        info = _info(update_available=True)
        session.start_check()

        _finish_check(service, session, info=info)

        assert service.start_download_calls == [info]
        assert started == [info]
        assert progress[-1] == (0, 100)
        assert session.snapshot()["state"] == ui_mod.STATE_DOWNLOADING
        assert marker == []

    def test_progress_and_finished_writes_marker(
        self,
        session: InlineUpdateSession,
        service: FakeUpdateService,
        marker: list[tuple[Any, str]],
    ) -> None:
        progress: list[tuple[int, int]] = []
        completed: list[tuple[UpdateInfo, str]] = []
        session.download_progress.connect(
            lambda downloaded, total: progress.append((downloaded, total))
        )
        session.downloaded.connect(
            lambda info, path: completed.append((info, path))
        )
        info = _info(update_available=True)
        session.start_check()
        _finish_check(service, session, info=info)

        service.download_progress.emit("download-1", 45, 100, 1.0)
        service.download_finished.emit("download-1", "C:/download/Setup.exe")

        assert progress[-1] == (45, 100)
        assert completed == [(info, "C:/download/Setup.exe")]
        assert marker == [(info, "C:/download/Setup.exe")]
        assert session.snapshot()["state"] == ui_mod.STATE_DOWNLOADED

    def test_download_failed_keeps_reason(
        self, session: InlineUpdateSession, service: FakeUpdateService
    ) -> None:
        failures: list[tuple[Any, UpdateError]] = []
        session.download_failed.connect(
            lambda info, error: failures.append((info, error))
        )
        session.start_check()
        _finish_check(
            service, session, info=_info(update_available=True)
        )

        error = UpdateError("network")
        service.download_failed.emit("download-1", error)

        assert failures and failures[0][1] is error
        assert session.snapshot()["state"] == ui_mod.STATE_DOWNLOAD_FAILED

    def test_missing_asset_fails_without_download(
        self, session: InlineUpdateSession, service: FakeUpdateService
    ) -> None:
        failures: list[tuple[Any, UpdateError]] = []
        session.download_failed.connect(
            lambda info, error: failures.append((info, error))
        )
        session.start_check()
        _finish_check(
            service,
            session,
            info=_info(update_available=True, asset=None),
        )

        assert service.start_download_calls == []
        assert failures
        assert failures[0][1].code == "no_installer_asset"
        assert failures[0][1].message == "该版本没有可用的安装包"

    def test_marker_write_failure_is_download_failure(
        self,
        session: InlineUpdateSession,
        service: FakeUpdateService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            ui_mod, "write_pending_update", lambda *_args: False
        )
        failures: list[tuple[Any, UpdateError]] = []
        session.download_failed.connect(
            lambda info, error: failures.append((info, error))
        )
        session.start_check()
        _finish_check(
            service, session, info=_info(update_available=True)
        )

        service.download_finished.emit("download-1", "C:/download/Setup.exe")

        assert failures
        assert "无法登记下次启动安装" in failures[0][1].message
        assert session.snapshot()["state"] == ui_mod.STATE_DOWNLOAD_FAILED

    def test_verifying_reports_100_percent(
        self,
        session: InlineUpdateSession,
        service: FakeUpdateService,
        marker: list[tuple[Any, str]],
    ) -> None:
        progress: list[tuple[int, int]] = []
        session.download_progress.connect(
            lambda downloaded, total: progress.append((downloaded, total))
        )
        session.start_check()
        _finish_check(
            service, session, info=_info(update_available=True)
        )

        service.download_state_changed.emit("download-1", "verifying")

        assert progress[-1] == (100, 100)


class TestSessionLifecycle:
    """快照、销毁与外部检查过滤。"""

    def test_snapshot_reports_error_and_progress(
        self,
        session: InlineUpdateSession,
        service: FakeUpdateService,
        marker: list[tuple[Any, str]],
    ) -> None:
        session.start_check()
        _finish_check(
            service, session, info=_info(update_available=True)
        )
        service.download_progress.emit("download-1", 70, 100, 0.0)

        snapshot = session.snapshot()

        assert snapshot["state"] == ui_mod.STATE_DOWNLOADING
        assert snapshot["downloaded"] == 70
        assert snapshot["total"] == 100

    def test_external_manual_result_is_ignored(
        self, session: InlineUpdateSession, service: FakeUpdateService
    ) -> None:
        results: list[Any] = []
        session.up_to_date.connect(results.append)
        session.start_check()

        service.check_finished.emit("check-9", True, _info(), None)

        assert results == []
        assert session.snapshot()["state"] == ui_mod.STATE_CHECKING

    def test_dispose_ignores_late_result(
        self, session: InlineUpdateSession, service: FakeUpdateService
    ) -> None:
        results: list[Any] = []
        session.up_to_date.connect(results.append)
        session.start_check()
        session.dispose()

        service.check_finished.emit("check-1", True, _info(), None)

        assert results == []
