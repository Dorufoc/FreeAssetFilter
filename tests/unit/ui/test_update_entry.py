# -*- coding: utf-8 -*-
"""UpdateEntryController 请求关联与弹窗状态分发单元测试。

用一个最小服务替身与一个非 QWidget 的弹窗替身，验证：

* 两个入口共用的单次检查与连点去重；
* manual 请求 id 认领、外部检查忽略、dispose 后不再处理；
* 检查结果 / 错误写入弹窗，关闭后结果到达重新建窗。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/test_update_entry.py -v
"""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from sopeek.services.update_service import UpdateError, UpdateInfo
from sopeek.ui.update_entry import UpdateEntryController
from tests.support.qt_helpers import drain_deferred_deletes

pytestmark = pytest.mark.unit


class FakeUpdateService(QObject):
    """最小更新服务替身：信号与生产契约一致，行为完全可控。"""

    check_started = Signal(str, bool)
    check_finished = Signal(str, bool, object, object)

    def __init__(self) -> None:
        super().__init__()
        self.available = True
        self.next_id = "check-1"
        self.emit_started = True
        self.check_calls: list[bool] = []

    def is_available(self) -> bool:
        """返回可配置的可用性（不启动子进程）。"""
        return self.available

    def check(self, manual: bool = False) -> str:
        """记录检查调用并按配置同步发 ``check_started``。"""
        self.check_calls.append(bool(manual))
        if self.emit_started:
            self.check_started.emit(self.next_id, bool(manual))
        return self.next_id


class FakeCenterDialog(QObject):
    """更新中心弹窗替身：只记录状态写入与显示次数。"""

    finished = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.state = ""
        self.checking_versions: list[str] = []
        self.results: list[object] = []
        self.errors: list[object] = []
        self.visible = False
        self.show_calls = 0
        self.raise_calls = 0
        self.deleted = False

    def set_checking(self, local_version: str = "") -> None:
        """记录检查中状态。"""
        self.state = "checking"
        self.checking_versions.append(local_version)

    def set_result(self, info: object) -> None:
        """记录结果状态。"""
        self.state = "result"
        self.results.append(info)

    def set_error(self, err: object) -> None:
        """记录错误状态。"""
        self.state = "error"
        self.errors.append(err)

    def isVisible(self) -> bool:  # noqa: N802 - 对齐 Qt API
        """返回替身可见状态。"""
        return self.visible

    def show_dialog(self) -> None:
        """标记为可见。"""
        self.visible = True
        self.show_calls += 1

    def raise_(self) -> None:  # noqa: A003 - 对齐 Qt API
        """记录前置调用。"""
        self.raise_calls += 1

    def activateWindow(self) -> None:  # noqa: N802 - 对齐 Qt API
        """空实现（替身无需激活）。"""

    def close_dialog(self) -> None:
        """模拟关闭并发出 ``finished``。"""
        self.visible = False
        self.finished.emit(0)

    def deleteLater(self) -> None:  # noqa: N802 - 对齐 Qt API
        """记录销毁请求。"""
        self.deleted = True


def _info() -> UpdateInfo:
    """构造一个「无更新」的稳定结果快照。"""
    return UpdateInfo(
        local_version="1.0.0-alpha.5",
        local_date="2026-05-22",
        update_available=False,
        reason="none",
        skipped_newer_tag=None,
        remote={
            "version": "1.0.0-alpha.5",
            "tag": "v1.0.0-alpha.5",
            "date": "2026-05-22",
        },
        asset=None,
    )


def _available_info() -> UpdateInfo:
    """构造一个「有新版本且可下载」的结果快照。"""
    return UpdateInfo(
        local_version="1.0.0-alpha.5",
        local_date="2026-05-22",
        update_available=True,
        reason="newer_version",
        skipped_newer_tag=None,
        remote={
            "version": "1.0.0-alpha.6",
            "tag": "v1.0.0-alpha.6",
            "date": "2026-06-01",
            "notes": "修复若干问题。",
        },
        asset={
            "name": "Sopeek-setup.exe",
            "size": 2 * 1024 * 1024,
            "sha256": "a" * 64,
        },
    )


@pytest.fixture
def fake_service(qapp: QApplication) -> FakeUpdateService:
    """提供一个假的更新服务。"""
    del qapp
    return FakeUpdateService()


@pytest.fixture
def dialogs(monkeypatch: Any) -> list[FakeCenterDialog]:
    """把控制器建窗替换为弹窗替身，并返回创建顺序列表。"""
    created: list[FakeCenterDialog] = []

    def _ensure(self: UpdateEntryController) -> FakeCenterDialog:
        if self._dialog is None:
            self._dialog = FakeCenterDialog()
            self._dialog.finished.connect(self._on_dialog_finished)
            created.append(self._dialog)
        return self._dialog

    monkeypatch.setattr(UpdateEntryController, "_ensure_dialog", _ensure)
    return created


@pytest.fixture
def controller(
    qapp: QApplication,
    fake_service: FakeUpdateService,
    dialogs: list[FakeCenterDialog],
    monkeypatch: Any,
) -> UpdateEntryController:
    """构造注入假服务与假弹窗的控制器，并在用例后销毁。"""
    del qapp, dialogs
    monkeypatch.setattr(
        "sopeek.utils.version_info.get_local_version",
        lambda: "1.0.0-alpha.5",
    )
    instance = UpdateEntryController(service_factory=lambda: fake_service)
    try:
        yield instance
    finally:
        instance.dispose()


class TestRequestFlow:
    """发起检查与结果分发。"""

    def test_request_check_shows_checking(
        self,
        controller: UpdateEntryController,
        fake_service: FakeUpdateService,
        dialogs: list[FakeCenterDialog],
    ) -> None:
        """点击后立即显示检查中弹窗并记录请求 id。"""
        controller.request_check()

        assert fake_service.check_calls == [True]
        assert len(dialogs) == 1
        assert dialogs[0].state == "checking"
        assert dialogs[0].checking_versions == ["1.0.0-alpha.5"]
        assert dialogs[0].visible is True
        assert controller._request_id == "check-1"

    def test_repeat_click_does_not_duplicate_check(
        self,
        controller: UpdateEntryController,
        fake_service: FakeUpdateService,
        dialogs: list[FakeCenterDialog],
    ) -> None:
        """连点只派发一次检查，第二次仅前置弹窗。"""
        controller.request_check()
        controller.request_check()

        assert fake_service.check_calls == [True]
        assert len(dialogs) == 1
        assert dialogs[0].raise_calls >= 1

    def test_result_is_applied_and_busy_reset(
        self,
        controller: UpdateEntryController,
        fake_service: FakeUpdateService,
        dialogs: list[FakeCenterDialog],
        monkeypatch: Any,
    ) -> None:
        """同 id 的 manual 结果写入弹窗并复位忙闲状态。"""
        info = _info()
        controller.request_check()
        monkeypatch.setattr(controller, "_checking_shown_at", 0.0)

        fake_service.check_finished.emit("check-1", True, info, None)

        assert dialogs[0].state == "result"
        assert dialogs[0].results == [info]
        assert controller._busy is False

    def test_error_is_applied(
        self,
        controller: UpdateEntryController,
        fake_service: FakeUpdateService,
        dialogs: list[FakeCenterDialog],
        monkeypatch: Any,
    ) -> None:
        """错误结果写入弹窗的错误态。"""
        error = UpdateError("network")
        controller.request_check()
        monkeypatch.setattr(controller, "_checking_shown_at", 0.0)

        fake_service.check_finished.emit("check-1", True, None, error)

        assert dialogs[0].state == "error"
        assert dialogs[0].errors == [error]

    def test_unavailable_service_reports_error(
        self,
        controller: UpdateEntryController,
        fake_service: FakeUpdateService,
        dialogs: list[FakeCenterDialog],
    ) -> None:
        """更新器不可用时直接展示 unavailable 错误，不派发检查。"""
        fake_service.available = False

        controller.request_check()

        assert fake_service.check_calls == []
        assert len(dialogs) == 1
        assert dialogs[0].state == "error"
        assert getattr(dialogs[0].errors[0], "code", "") == "unavailable"


class TestFiltering:
    """请求 id 与关闭/销毁边界。"""

    def test_external_manual_check_is_ignored(
        self,
        controller: UpdateEntryController,
        fake_service: FakeUpdateService,
        dialogs: list[FakeCenterDialog],
        monkeypatch: Any,
    ) -> None:
        """非本入口发起的 manual 检查不认领、不弹窗。"""
        monkeypatch.setattr(controller, "_checking_shown_at", 0.0)
        fake_service.check_started.emit("check-9", True)
        fake_service.check_finished.emit("check-9", True, _info(), None)

        assert dialogs == []
        assert controller._dialog is None

    def test_non_manual_result_is_ignored(
        self,
        controller: UpdateEntryController,
        fake_service: FakeUpdateService,
        dialogs: list[FakeCenterDialog],
        monkeypatch: Any,
    ) -> None:
        """启动检查（manual=False）的结果不触碰手动弹窗。"""
        controller.request_check()
        monkeypatch.setattr(controller, "_checking_shown_at", 0.0)
        fake_service.check_finished.emit("check-1", False, _info(), None)

        assert dialogs[0].state == "checking"

    def test_closed_dialog_is_recreated_on_result(
        self,
        controller: UpdateEntryController,
        fake_service: FakeUpdateService,
        dialogs: list[FakeCenterDialog],
        monkeypatch: Any,
    ) -> None:
        """检查中关闭弹窗后，结果到达重新建窗显示。"""
        controller.request_check()
        dialogs[0].close_dialog()
        assert controller._dialog is None

        info = _info()
        monkeypatch.setattr(controller, "_checking_shown_at", 0.0)
        fake_service.check_finished.emit("check-1", True, info, None)

        assert len(dialogs) == 2
        assert dialogs[1].state == "result"
        assert dialogs[1].results == [info]

    def test_dispose_ignores_late_result(
        self,
        controller: UpdateEntryController,
        fake_service: FakeUpdateService,
        dialogs: list[FakeCenterDialog],
        monkeypatch: Any,
    ) -> None:
        """dispose 之后到达的结果不再建窗、不抛异常。"""
        controller.request_check()
        monkeypatch.setattr(controller, "_checking_shown_at", 0.0)
        controller.dispose()

        fake_service.check_finished.emit("check-1", True, _info(), None)

        assert len(dialogs) == 1
        assert dialogs[0].state == "checking"

    def test_minimum_checking_visible_delay(
        self,
        controller: UpdateEntryController,
        fake_service: FakeUpdateService,
        dialogs: list[FakeCenterDialog],
        monkeypatch: Any,
    ) -> None:
        """结果在最小展示时长内到达时由定时器延后写入。"""
        controller.request_check()
        # 刚显示不足 250ms：应安排定时器而非立即切换，忙闲保持到切换完成
        fake_service.check_finished.emit("check-1", True, _info(), None)

        assert dialogs[0].state == "checking"
        assert controller._busy is True

    def test_startup_in_flight_manual_click_claims_result(
        self,
        controller: UpdateEntryController,
        fake_service: FakeUpdateService,
        dialogs: list[FakeCenterDialog],
        monkeypatch: Any,
    ) -> None:
        """启动检查在途时点击：用 check() 返回值补齐 id 并接管结果。"""
        fake_service.emit_started = False
        fake_service.check_started.emit("check-1", False)

        controller.request_check()
        assert controller._request_id == "check-1"

        monkeypatch.setattr(controller, "_checking_shown_at", 0.0)
        info = _info()
        fake_service.check_finished.emit("check-1", True, info, None)

        assert dialogs[0].results == [info]

    def test_retry_starts_a_new_check(
        self,
        controller: UpdateEntryController,
        fake_service: FakeUpdateService,
        dialogs: list[FakeCenterDialog],
        monkeypatch: Any,
    ) -> None:
        """错误后再次点击（等价重试）会发起第二次检查。"""
        controller.request_check()
        monkeypatch.setattr(controller, "_checking_shown_at", 0.0)
        fake_service.check_finished.emit(
            "check-1", True, None, UpdateError("network")
        )
        assert dialogs[0].state == "error"

        fake_service.next_id = "check-2"
        controller.request_check()

        assert fake_service.check_calls == [True, True]
        assert dialogs[0].state == "checking"

    def test_download_closes_center_and_opens_progress(
        self,
        controller: UpdateEntryController,
        fake_service: FakeUpdateService,
        dialogs: list[FakeCenterDialog],
        monkeypatch: Any,
    ) -> None:
        """下载动作关闭中心弹窗并交给既有进度弹窗。"""
        opened: list[tuple[object, object]] = []
        monkeypatch.setattr(
            "sopeek.ui.layout.update_dialogs.show_download_progress",
            lambda info, service: opened.append((info, service)),
        )

        controller.request_check()
        info = _available_info()
        controller._on_download(info)

        assert opened == [(info, fake_service)]
        assert controller._dialog is None
        assert dialogs[0].deleted is True


class TestRealDialogIntegration:
    """不替换建窗方法，验证控制器与真实 UpdateCenterDialog 的接线。"""

    def test_real_dialog_switches_states(
        self,
        qapp: QApplication,
        fake_service: FakeUpdateService,
        monkeypatch: Any,
    ) -> None:
        """真实弹窗从 checking 切到 no_update 并保持同一实例。"""
        monkeypatch.setattr(
            "sopeek.utils.version_info.get_local_version",
            lambda: "1.0.0-alpha.5",
        )
        controller = UpdateEntryController(service_factory=lambda: fake_service)
        try:
            controller.request_check()
            dialog = controller._dialog
            assert dialog is not None
            assert dialog.current_state() == dialog.STATE_CHECKING

            monkeypatch.setattr(controller, "_checking_shown_at", 0.0)
            fake_service.check_finished.emit("check-1", True, _info(), None)

            assert controller._dialog is dialog
            assert dialog.current_state() == dialog.STATE_NO_UPDATE
        finally:
            controller.dispose()
            drain_deferred_deletes(qapp)
