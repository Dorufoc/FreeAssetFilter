# -*- coding: utf-8 -*-
"""关于页「检查更新」确认弹窗测试。

覆盖：

* 弹窗默认不勾选「获取测试版」——取消 / 直接确认都只检查正式版；
* 勾选后确认返回 ``True``（检查包含 GitHub 预发布版）；
* 弹窗内容、模态与样式组件来源；
* 关于页点击动作时把弹窗结果透传给内联会话。

弹窗是同步模态（内部 QEventLoop），因此测试用 ``QTimer.singleShot`` 在弹窗
出现后驱动按钮，并保证任何异常路径都会关闭弹窗释放事件循环。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/layout/test_update_check_prompt.py -v
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QLabel

import sopeek.ui.layout.settings_layout as sl_mod
import sopeek.ui.layout.update_dialogs as ud_mod
from components.styled_button import StyledButton
from components.styled_checkbox import StyledCheckbox
from components.styled_dialog import StyledDialog
from tests.support.qt_helpers import drain_deferred_deletes, safe_teardown

pytestmark = pytest.mark.unit

DIALOG_OBJECT_NAME = "UpdateCheckPromptDialog"


def _prompt_dialog() -> Optional[StyledDialog]:
    """在顶层窗口里找到确认弹窗（不依赖模块内部存活表）。"""
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, StyledDialog) and widget.objectName() == DIALOG_OBJECT_NAME:
            return widget
    return None


def _button(dialog: StyledDialog, object_name: str) -> StyledButton:
    """按 objectName 找到弹窗底部按钮。"""
    for button in dialog.findChildren(StyledButton):
        if button.objectName() == object_name:
            return button
    raise AssertionError(f"button not found: {object_name}")


def _drive_prompt(
    action: str,
    *,
    check_box: bool = False,
    inspect: Optional[Callable[[StyledDialog], None]] = None,
) -> Callable[[], None]:
    """返回定时器回调：驱动弹窗，且无论成功失败都保证关闭它。"""

    def _interact() -> None:
        dialog = _prompt_dialog()
        if dialog is None:
            return
        try:
            if inspect is not None:
                inspect(dialog)
            box = dialog._prerelease_checkbox  # type: ignore[attr-defined]
            if check_box:
                box.checked = True
            if action == "cancel":
                _button(dialog, "UpdateCheckPromptCancel").click()
            elif action == "confirm":
                _button(dialog, "UpdateCheckPromptConfirm").click()
        finally:
            # 兜底：断言失败或按钮缺失时也必须结束模态循环。
            if dialog.isVisible():
                dialog.close_dialog(0)

    return _interact


def _run_prompt(
    qapp: QApplication,
    action: str,
    *,
    check_box: bool = False,
    inspect: Optional[Callable[[StyledDialog], None]] = None,
) -> Any:
    """驱动弹窗并返回 ``show_check_update_prompt`` 的结果。"""
    QTimer.singleShot(
        0, _drive_prompt(action, check_box=check_box, inspect=inspect)
    )
    value = ud_mod.show_check_update_prompt(None)
    qapp.processEvents()
    return value


class TestCheckUpdatePrompt:
    """确认弹窗的返回值与内容。"""

    def test_default_confirm_checks_stable_only(self, qapp: QApplication) -> None:
        """未勾选「获取测试版」时确认 → False（仅正式版）。"""
        assert _run_prompt(qapp, "confirm") is False
        drain_deferred_deletes()

    def test_checked_prerelease_returns_true(self, qapp: QApplication) -> None:
        """勾选「获取测试版」后确认 → True（包含预发布版）。"""
        assert _run_prompt(qapp, "confirm", check_box=True) is True
        drain_deferred_deletes()

    def test_cancel_returns_none(self, qapp: QApplication) -> None:
        """取消 → None，调用方据此不发起任何检查。"""
        assert _run_prompt(qapp, "cancel") is None
        drain_deferred_deletes()

    def test_dialog_content_and_modal(self, qapp: QApplication) -> None:
        """弹窗由 styled 组件构成，带勾选框且为应用级模态。"""
        seen: dict[str, Any] = {}

        def _inspect(dialog: StyledDialog) -> None:
            seen["modal"] = dialog.windowModality() == Qt.ApplicationModal
            seen["checkboxes"] = [
                child.text for child in dialog.findChildren(StyledCheckbox)
            ]
            seen["message"] = dialog.findChild(QLabel, "UpdateCheckPromptMessage")
            seen["hint"] = dialog.findChild(QLabel, "UpdateCheckPromptHint")
            seen["cancel"] = dialog.findChild(StyledButton, "UpdateCheckPromptCancel")
            seen["confirm"] = dialog.findChild(StyledButton, "UpdateCheckPromptConfirm")

        assert _run_prompt(qapp, "cancel", inspect=_inspect) is None
        qapp.processEvents()
        assert seen["modal"] is True
        assert seen["checkboxes"] == ["获取测试版"]
        assert seen["message"] is not None
        assert "GitHub" in seen["message"].text()
        assert seen["hint"] is not None
        assert "测试版" in seen["hint"].text()
        assert seen["cancel"] is not None
        assert seen["confirm"] is not None
        assert seen["confirm"].text() == "检查更新"
        assert seen["cancel"].text() == "取消"
        drain_deferred_deletes()


class FakeInlineSession:
    """内联会话替身：只记录 ``start_check`` 的入参。"""

    def __init__(self) -> None:
        self.start_calls: list[bool] = []
        self.disposed = False

    def start_check(self, include_prerelease: bool = False) -> None:
        self.start_calls.append(bool(include_prerelease))


class TestAboutPageUsesPrompt:
    """关于页点击动作必须先经弹窗，并把选择透传给会话。"""

    @pytest.fixture
    def page_and_session(
        self, qapp: QApplication, monkeypatch: Any
    ) -> Any:
        session = FakeInlineSession()
        monkeypatch.setattr(
            sl_mod.AboutSettingsPage,
            "_ensure_update_session",
            lambda self: session,
        )
        page = sl_mod.AboutSettingsPage()
        try:
            yield page, session
        finally:
            safe_teardown(page)

    def test_prompt_true_starts_check_with_prerelease(
        self, monkeypatch: Any, page_and_session: tuple[Any, FakeInlineSession]
    ) -> None:
        """弹窗返回 True → 会话以 include_prerelease=True 启动检查。"""
        page, session = page_and_session
        monkeypatch.setattr(
            ud_mod, "show_check_update_prompt", lambda parent=None: True
        )
        page._check_update()
        assert session.start_calls == [True]

    def test_prompt_false_starts_check_without_prerelease(
        self, monkeypatch: Any, page_and_session: tuple[Any, FakeInlineSession]
    ) -> None:
        """弹窗返回 False → 只检查正式版。"""
        page, session = page_and_session
        monkeypatch.setattr(
            ud_mod, "show_check_update_prompt", lambda parent=None: False
        )
        page._check_update()
        assert session.start_calls == [False]

    def test_cancel_never_starts_check(
        self, monkeypatch: Any, page_and_session: tuple[Any, FakeInlineSession]
    ) -> None:
        """取消 → 完全不发起检查，动作保持空闲。"""
        page, session = page_and_session
        monkeypatch.setattr(
            ud_mod, "show_check_update_prompt", lambda parent=None: None
        )
        page._check_update()
        assert session.start_calls == []
        assert (
            page._check_update_action is None
            or page._check_update_action.is_busy is False
        )
