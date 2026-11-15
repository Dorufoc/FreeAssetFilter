# -*- coding: utf-8 -*-
"""内联更新会话的测试版确认流程。

覆盖：
* 测试版更新只进入「等待确认」状态，不自动下载；
* 用户确认后才会派发下载；
* 跳过测试版不触发下载；
* 正式版更新保持原有的自动下载行为。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/test_update_inline.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import QObject, Signal

from sopeek.ui.update_inline import (
    STATE_DOWNLOADING,
    STATE_UPDATE_AVAILABLE,
    STATE_UPDATE_SKIPPED,
    InlineUpdateSession,
)

pytestmark = pytest.mark.unit


class FakeService(QObject):
    """更新服务替身：提供内联会话订阅所需的信号与最小 API。"""

    check_started = Signal(str, bool)
    check_finished = Signal(str, bool, object, object)
    download_progress = Signal(str, object, object, float)
    download_state_changed = Signal(str, str)
    download_finished = Signal(str, str)
    download_failed = Signal(str, object)

    def __init__(self) -> None:
        super().__init__()
        self.check_calls: list[tuple[bool, bool]] = []
        self.download_calls: list[object] = []

    def is_available(self) -> bool:
        """更新组件可用。"""
        return True

    def check(
        self, manual: bool = False, include_prerelease: bool = True
    ) -> str:
        """记录检查参数并返回固定请求 id。"""
        self.check_calls.append((bool(manual), bool(include_prerelease)))
        return "req-1"

    def start_download(self, info: object) -> str:
        """记录下载请求并返回固定下载 id。"""
        self.download_calls.append(info)
        return "dl-1"

    def get_download_state(self, request_id: str) -> tuple[str, int, int]:
        """返回初始下载进度。"""
        return ("running", 0, 100)


def _info(
    *, prerelease: bool = False, version: str = "v9.9.9"
) -> SimpleNamespace:
    """构造一个更新结果快照。"""
    return SimpleNamespace(
        update_available=True,
        local_version="2.0.0",
        remote={"version": version, "prerelease": prerelease},
        asset={
            "name": "Sopeek-Setup.exe",
            "sha256": "a" * 64,
            "size": 1024,
        },
        skipped_newer_tag=None,
    )


def _session(qapp: Any) -> tuple[InlineUpdateSession, FakeService]:
    """创建会话与可检查的服务替身。"""
    service = FakeService()
    session = InlineUpdateSession(service_factory=lambda: service)
    session.MIN_CHECKING_VISIBLE_MS = 0
    return session, service


def _start_and_finish(
    session: InlineUpdateSession,
    service: FakeService,
    info: object,
) -> None:
    """发起检查并注入检查结果。"""
    session.start_check(include_prerelease=True)
    service.check_finished.emit("req-1", True, info, None)


def test_prerelease_waits_for_confirmation(qapp: Any) -> None:
    """测试版只进入等待确认状态，不自动下载。"""
    session, service = _session(qapp)
    available: list[object] = []
    session.update_available.connect(available.append)

    info = _info(prerelease=True)
    _start_and_finish(session, service, info)

    assert session.snapshot()["state"] == STATE_UPDATE_AVAILABLE
    assert service.download_calls == []
    assert available == [info]


def test_prerelease_download_after_confirmation(qapp: Any) -> None:
    """确认下载后才派发测试版下载。"""
    session, service = _session(qapp)
    info = _info(prerelease=True)
    _start_and_finish(session, service, info)

    assert session.start_pending_download() is True
    assert session.snapshot()["state"] == STATE_DOWNLOADING
    assert service.download_calls == [info]


def test_prerelease_skip_does_not_download(qapp: Any) -> None:
    """跳过测试版不触发下载，并保留跳过状态。"""
    session, service = _session(qapp)
    skipped: list[object] = []
    session.update_skipped.connect(skipped.append)
    info = _info(prerelease=True)
    _start_and_finish(session, service, info)

    assert session.skip_pending_update() is True
    assert session.snapshot()["state"] == STATE_UPDATE_SKIPPED
    assert service.download_calls == []
    assert skipped == [info]


def test_stable_update_auto_downloads(qapp: Any) -> None:
    """正式版更新保持自动下载。"""
    session, service = _session(qapp)
    info = _info(prerelease=False)
    _start_and_finish(session, service, info)

    assert session.snapshot()["state"] == STATE_DOWNLOADING
    assert service.download_calls == [info]


def test_prerelease_detected_from_version_fallback(qapp: Any) -> None:
    """缺少 prerelease 字段时按版本号连字符识别测试版。"""
    session, service = _session(qapp)
    info = _info(prerelease=False, version="v9.9.9-alpha.1")
    _start_and_finish(session, service, info)

    assert session.snapshot()["state"] == STATE_UPDATE_AVAILABLE
    assert service.download_calls == []


def test_new_check_ignored_while_waiting(qapp: Any) -> None:
    """等待确认期间不重复发起检查。"""
    session, service = _session(qapp)
    _start_and_finish(session, service, _info(prerelease=True))

    session.start_check(include_prerelease=True)
    assert service.check_calls == [(True, True)]
