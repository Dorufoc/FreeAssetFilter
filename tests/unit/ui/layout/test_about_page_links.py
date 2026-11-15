# -*- coding: utf-8 -*-
"""关于页外链测试。

覆盖：

* 链接行只保留「仓库页面 / 第三方组件许可 / 开源许可」三个外链；
* 三个地址均指向当前仓库 ``Dorufoc/FreeAssetFilter`` 的 ``main-v2`` 分支；
* 点击链接经 ``QDesktopServices.openUrl`` 打开对应网页；
* 「联系我们」入口与联系面板已移除。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/layout/test_about_page_links.py -v
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest

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


def test_about_links_point_to_current_repo(
    page: sl_mod.AboutSettingsPage,
) -> None:
    """三个链接文案与地址均对应当前仓库和文档。"""
    assert page._repo_link is not None
    assert page._third_party_link is not None
    assert page._license_link is not None

    assert page._repo_link.text() == "仓库页面"
    assert page._third_party_link.text() == "第三方组件许可"
    assert page._license_link.text() == "开源许可"

    assert page._repo_link.toolTip() == (
        "https://github.com/Dorufoc/FreeAssetFilter"
    )
    assert page._third_party_link.toolTip() == (
        "https://github.com/Dorufoc/FreeAssetFilter/blob/main-v2/"
        "src/sopeek/resources/docs/THIRD_PARTY_NOTICES.md"
    )
    assert page._license_link.toolTip() == (
        "https://github.com/Dorufoc/FreeAssetFilter/blob/main-v2/LICENSE"
    )


def test_contact_entry_is_removed(
    page: sl_mod.AboutSettingsPage,
) -> None:
    """关于页不再保留联系入口、联系面板或展开状态。"""
    assert not hasattr(page, "_contact_link")
    assert not hasattr(page, "_contact_box")
    assert not hasattr(page, "_contact_visible")
    assert page.findChild(sl_mod.QWidget, "AboutContactBox") is None


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
