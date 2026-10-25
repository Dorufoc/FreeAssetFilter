# -*- coding: utf-8 -*-
"""UpdateCenterDialog 四态弹窗单元测试。

覆盖检查中 / 已是最新 / 发现新版本 / 检查失败四态的内容与按钮可见性、
body 子控件不累积、以及 ``remeasure()`` 随内容改变窗口高度。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/test_update_center_dialog.py -v
"""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtWidgets import QApplication

import freeassetfilter.ui.layout.update_dialogs as ud_mod
from freeassetfilter.services.update_service import UpdateError, UpdateInfo
from freeassetfilter.ui.layout.update_dialogs import UpdateCenterDialog
from tests.support.qt_helpers import drain_deferred_deletes, safe_teardown

pytestmark = pytest.mark.unit


def _info(
    *,
    update_available: bool = True,
    sha256: str | None = "a" * 64,
) -> UpdateInfo:
    """构造一个稳定的 UpdateInfo 快照。

    Args:
        update_available: 服务判定是否有更新。
        sha256: 安装包校验值；``None`` 表示发布信息缺少校验值。

    Returns:
        UpdateInfo: 测试用更新结果。
    """
    asset: dict[str, Any] | None = None
    if sha256 is not None:
        asset = {
            "name": "FreeAssetFilter-1.0.0-alpha.6_win10_win11_x64_Setup.exe",
            "size": 2 * 1024 * 1024,
            "sha256": sha256,
            "download_url": (
                "https://github.com/Dorufoc/FreeAssetFilter/releases/download/"
                "v1.0.0-alpha.6/FreeAssetFilter-setup.exe"
            ),
        }
    return UpdateInfo(
        local_version="1.0.0-alpha.5",
        local_date="2026-05-22",
        update_available=update_available,
        reason="newer_version" if update_available else "none",
        skipped_newer_tag=None,
        remote={
            "version": "1.0.0-alpha.6",
            "tag": "v1.0.0-alpha.6",
            "date": "2026-06-01",
            "notes": "修复若干问题。",
            "notes_truncated": False,
            "html_url": (
                "https://github.com/Dorufoc/FreeAssetFilter/releases/"
                "tag/v1.0.0-alpha.6"
            ),
        },
        asset=asset,
    )


@pytest.fixture
def dialog(qapp: QApplication) -> Any:
    """构造一个绑定空回调的更新中心弹窗。"""
    instance = UpdateCenterDialog(
        on_download=lambda info: None,
        on_retry=lambda: None,
    )
    try:
        yield instance
    finally:
        safe_teardown(instance)
        drain_deferred_deletes(qapp)


class TestStates:
    """四态内容与按钮可见性。"""

    def test_checking_shows_loading_and_local_version(self, dialog: Any) -> None:
        """检查中：加载动画 + 当前版本 + 仅关闭按钮可见。"""
        dialog.set_checking("1.0.0-alpha.5")

        assert dialog.current_state() == UpdateCenterDialog.STATE_CHECKING
        assert dialog._loading_widget is not None
        assert "v1.0.0-alpha.5" in dialog._version_label.text()
        assert dialog._close_button.isHidden() is False
        assert dialog._close_button.text() == "关闭"
        assert dialog._download_button.isHidden() is True
        assert dialog._retry_button.isHidden() is True
        assert dialog._release_button.isHidden() is True
        assert dialog._later_button.isHidden() is True

    def test_available_shows_details_and_actions(self, dialog: Any) -> None:
        """发现新版本：版本/日期/说明/下载大小与三个按钮。"""
        dialog.set_result(_info())

        assert dialog.current_state() == UpdateCenterDialog.STATE_AVAILABLE
        assert dialog._version_label.text() == "版本：v1.0.0-alpha.6"
        assert dialog._notes_area is not None
        assert dialog._notes_area.text == "修复若干问题。"
        assert dialog._notes_area.read_only is True
        assert dialog._download_button.isHidden() is False
        assert dialog._download_button.isEnabled() is True
        assert "2.0 MB" in dialog._download_button.text()
        assert dialog._release_button.isHidden() is False
        assert dialog._later_button.isHidden() is False
        assert dialog._later_button.text() == "稍后"
        assert dialog._close_button.isHidden() is True
        assert dialog._retry_button.isHidden() is True

    def test_available_without_sha256_disables_download(self, dialog: Any) -> None:
        """缺少校验值：下载禁用并给出手动下载提示。"""
        dialog.set_result(_info(sha256=None))

        assert dialog._download_button.isEnabled() is False
        hints = [
            child.text()
            for child in dialog._body.findChildren(ud_mod.QLabel)
            if "校验值" in child.text()
        ]
        assert hints, "应显示缺少安装包校验值的提示"

    def test_no_update_reuses_close_button_as_know(self, dialog: Any) -> None:
        """已是最新：关闭按钮改文案，下载/发布页/重试全部隐藏。"""
        dialog.set_result(_info(update_available=False))

        assert dialog.current_state() == UpdateCenterDialog.STATE_NO_UPDATE
        assert dialog._close_button.text() == "知道了"
        assert dialog._download_button.isHidden() is True
        assert dialog._release_button.isHidden() is True
        assert dialog._retry_button.isHidden() is True
        assert dialog._later_button.isHidden() is True
        assert "v1.0.0-alpha.5" in dialog._version_label.text()

    def test_error_shows_retry(self, dialog: Any) -> None:
        """检查失败：显示错误文案与重试按钮。"""
        dialog.set_error(UpdateError("network"))

        assert dialog.current_state() == UpdateCenterDialog.STATE_ERROR
        assert dialog._retry_button.isHidden() is False
        assert dialog._download_button.isHidden() is True
        assert dialog._later_button.isHidden() is True
        messages = [
            child.text()
            for child in dialog._body.findChildren(ud_mod.QLabel)
            if "网络" in child.text()
        ]
        assert messages, "应显示网络错误文案"


class TestLifecycle:
    """body 重建与窗口尺寸。"""

    def test_body_children_do_not_accumulate(self, dialog: Any) -> None:
        """连续切换四态后 body 直接子项数量保持单态水平。"""
        counts: list[int] = []
        for _ in range(2):
            dialog.set_checking("1.0.0-alpha.5")
            counts.append(dialog._body_layout.count())
            dialog.set_result(_info())
            counts.append(dialog._body_layout.count())
            dialog.set_error(UpdateError("timeout"))
            counts.append(dialog._body_layout.count())
            dialog.set_result(_info(update_available=False))
            counts.append(dialog._body_layout.count())

        assert max(counts) <= 6, f"body 子项累积：{counts}"

    def test_footer_buttons_are_prebuilt(self, dialog: Any) -> None:
        """四态反复切换不调用 add_footer_button（否则抛 RuntimeError）。"""
        download_button = dialog._download_button
        for _ in range(2):
            dialog.set_checking()
            dialog.set_result(_info())
            dialog.set_error(UpdateError("internal"))
        assert dialog._download_button is download_button

    def test_remeasure_grows_with_content(
        self, dialog: Any, qapp: QApplication
    ) -> None:
        """检查中 → 发现新版本后窗口高度增大。"""
        dialog.set_checking("1.0.0-alpha.5")
        dialog.show_dialog()
        qapp.processEvents()
        small = dialog.height()

        dialog.set_result(_info())
        qapp.processEvents()
        large = dialog.height()

        assert large > small, f"高度未随内容增长：{small} -> {large}"


class TestActions:
    """footer 动作回调。"""

    def test_download_button_passes_info_to_callback(
        self, qapp: QApplication
    ) -> None:
        """下载按钮把当前 UpdateInfo 原样交给回调。"""
        received: list[object] = []
        dialog = UpdateCenterDialog(
            on_download=received.append,
            on_retry=lambda: None,
        )
        try:
            info = _info()
            dialog.set_result(info)
            dialog._download_button.click()
            assert received == [info]
        finally:
            safe_teardown(dialog)
            drain_deferred_deletes(qapp)

    def test_retry_button_closes_and_calls_callback(
        self, qapp: QApplication
    ) -> None:
        """重试按钮关闭弹窗并调用重试回调。"""
        calls: list[bool] = []
        dialog = UpdateCenterDialog(
            on_download=lambda info: None,
            on_retry=lambda: calls.append(True),
        )
        try:
            dialog.set_error(UpdateError("network"))
            dialog.show_dialog()
            dialog._retry_button.click()
            qapp.processEvents()

            assert calls == [True]
            assert dialog.isVisible() is False
        finally:
            safe_teardown(dialog)
            drain_deferred_deletes(qapp)


class TestReleaseUrl:
    """发布页地址白名单。"""

    def test_external_url_falls_back_to_releases_page(
        self, dialog: Any, monkeypatch: Any
    ) -> None:
        """非项目 /releases/ 前缀的地址被替换为发布页根地址。"""
        opened: list[str] = []
        monkeypatch.setattr(ud_mod, "_open_url", lambda url: opened.append(url))

        info = _info()
        info.remote["html_url"] = "https://evil.example.com/payload.exe"
        dialog.set_result(info)
        dialog._open_release_page()

        assert opened == [ud_mod.RELEASES_URL]
