# -*- coding: utf-8 -*-
"""关于页外链测试。

覆盖：

* 链接行只保留「仓库页面 / 第三方组件许可 / 开源许可」三个外链；
* 三个地址均指向当前仓库 ``Dorufoc/FreeAssetFilter`` 的 ``main-v2`` 分支；
* 点击链接经 ``QDesktopServices.openUrl`` 打开对应网页；
* 三个链接不显示鼠标悬浮说明（tooltip），其他控件不受影响；
* 链接默认无按钮底色，hover / 键盘 focus 时才进入胶囊高亮态；
* 链接之间使用 1px 发丝竖线，而不是「·」；
* 「联系我们」入口与联系面板已移除。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/layout/test_about_page_links.py -v
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from PySide6.QtCore import QEvent

import sopeek.ui.layout.settings_layout as sl_mod

pytestmark = pytest.mark.unit


@pytest.fixture
def page(qapp: Any) -> Iterator[sl_mod.AboutSettingsPage]:
    """创建关于页并在用例结束后销毁。"""
    widget = sl_mod.AboutSettingsPage()
    try:
        yield widget
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def test_about_link_texts_and_no_tooltips(
    page: sl_mod.AboutSettingsPage,
) -> None:
    """三个链接文案正确，且不显示鼠标悬浮说明。"""
    assert page._repo_link is not None
    assert page._third_party_link is not None
    assert page._license_link is not None

    assert page._repo_link.text() == "仓库页面"
    assert page._third_party_link.text() == "第三方组件许可"
    assert page._license_link.text() == "开源许可"

    assert page._repo_link.toolTip() == ""
    assert page._third_party_link.toolTip() == ""
    assert page._license_link.toolTip() == ""


def test_about_links_are_flat_until_highlighted(
    page: sl_mod.AboutSettingsPage,
) -> None:
    """链接默认不显示按钮样式，hover 时进入高亮态、离开后恢复。"""
    for attr in ("_repo_link", "_third_party_link", "_license_link"):
        link = getattr(page, attr)
        assert link.highlighted is False

    link = page._repo_link
    sl_mod.QApplication.sendEvent(link, QEvent(QEvent.Enter))
    assert link.highlighted is True

    sl_mod.QApplication.sendEvent(link, QEvent(QEvent.Leave))
    assert link.highlighted is False


def test_about_link_separators_are_hairlines(
    page: sl_mod.AboutSettingsPage,
) -> None:
    """链接行分隔符是 1px 发丝竖线，不再是「·」文本。"""
    assert len(page._link_separators) == 2
    for separator in page._link_separators:
        assert separator.width() == sl_mod.LINK_ACTION_SEPARATOR_WIDTH
        assert separator.height() == sl_mod.LINK_ACTION_SEPARATOR_HEIGHT
        assert separator.frameShape() == sl_mod.QFrame.NoFrame

    assert all(
        label.text() != "·" for label in page.findChildren(sl_mod.QLabel)
    )


def test_about_divider_sits_between_tagline_and_link_row(
    page: sl_mod.AboutSettingsPage,
    qapp: Any,
) -> None:
    """发丝线长度介于简介与链接行之间，形成上宽下窄的层级。"""
    page.resize(814, 577)
    page.show()
    page.layout().activate()
    qapp.processEvents()

    links_width = sum(link.width() for link in page._link_widgets)
    links_width += 2 * (
        2 * sl_mod.LINK_ACTION_SEPARATOR_GAP
        + sl_mod.LINK_ACTION_SEPARATOR_WIDTH
    )
    assert page._tagline_label.width() > page._divider.width() > links_width


def test_contact_entry_is_removed(
    page: sl_mod.AboutSettingsPage,
) -> None:
    """关于页不再保留联系入口、联系面板或展开状态。"""
    assert not hasattr(page, "_contact_link")
    assert not hasattr(page, "_contact_box")
    assert not hasattr(page, "_contact_visible")
    assert page.findChild(sl_mod.QWidget, "AboutContactBox") is None


def test_version_and_update_controls_are_moved_out(
    page: sl_mod.AboutSettingsPage,
) -> None:
    """版本信息与检查更新交互已迁移到「检查更新」页。"""
    assert not hasattr(page, "_version_label")
    assert not hasattr(page, "_check_update_action")
    assert not hasattr(page, "_update_status")
    assert not hasattr(page, "_update_session")
    assert page.findChild(sl_mod.QWidget, "AboutUpdateStatus") is None


@pytest.mark.parametrize(
    ("attr", "url_attr"),
    [
        ("_repo_link", "ABOUT_REPO_URL"),
        ("_third_party_link", "ABOUT_THIRD_PARTY_URL"),
        ("_license_link", "ABOUT_LICENSE_URL"),
    ],
)
def test_about_link_opens_web_url(
    page: sl_mod.AboutSettingsPage,
    monkeypatch: pytest.MonkeyPatch,
    attr: str,
    url_attr: str,
) -> None:
    """点击外链时通过系统默认浏览器打开对应网页。"""
    opened: list[str] = []

    class _FakeDesktopServices:
        @staticmethod
        def openUrl(url: Any) -> None:
            opened.append(url.toString())

    monkeypatch.setattr(sl_mod, "QDesktopServices", _FakeDesktopServices)
    link = getattr(page, attr)
    link.clicked.emit()

    assert opened == [getattr(sl_mod, url_attr)]
