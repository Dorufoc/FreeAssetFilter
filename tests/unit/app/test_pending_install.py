# -*- coding: utf-8 -*-
"""启动前待安装更新处理器测试。"""

from __future__ import annotations

from typing import Any

import pytest

import sopeek.app.pending_update as pending_app
from sopeek.services.update_pending import PendingUpdateResult

pytestmark = pytest.mark.unit


def test_launched_returns_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """安装器已拉起时返回 True，由调用方退出当前进程。"""
    messages: list[str] = []
    monkeypatch.setattr(
        pending_app,
        "apply_pending_update",
        lambda: PendingUpdateResult(launched=True),
    )
    monkeypatch.setattr(
        pending_app, "_show_failure", lambda detail: messages.append(detail)
    )

    assert pending_app.handle_pending_update() is True
    assert messages == []


def test_no_pending_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有待安装更新时静默继续启动。"""
    messages: list[str] = []
    monkeypatch.setattr(
        pending_app,
        "apply_pending_update",
        lambda: PendingUpdateResult(launched=False),
    )
    monkeypatch.setattr(
        pending_app, "_show_failure", lambda detail: messages.append(detail)
    )

    assert pending_app.handle_pending_update() is False
    assert messages == []


def test_failure_shows_message_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """启动失败时提示原因，但继续正常启动。"""
    messages: list[str] = []
    monkeypatch.setattr(
        pending_app,
        "apply_pending_update",
        lambda: PendingUpdateResult(
            launched=False, detail="UAC 已取消"
        ),
    )
    monkeypatch.setattr(
        pending_app, "_show_failure", lambda detail: messages.append(detail)
    )

    assert pending_app.handle_pending_update() is False
    assert messages == ["UAC 已取消"]


def test_apply_exception_is_contained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """处理器自身异常不得阻断启动。"""
    def boom() -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(pending_app, "apply_pending_update", boom)

    assert pending_app.handle_pending_update() is False
