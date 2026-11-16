# -*- coding: utf-8 -*-
"""设置页标签切换回归测试。

覆盖：

* 单次点击仍保留切页快照动画，并在结束后恢复实时内页；
* 连续快速点击时不叠加快照层：标签、内容页与实时内页立即一致，
  不会出现「标签已切换、内容仍是旧页」；
* 遮罩的 ``finished`` 丢失时看门狗会强制收尾，实时页不会永久隐藏；
* 切页遮罩保持鼠标穿透，不阻塞页面交互；
* 侧栏点击热区包含行两侧留白（经真实事件路由验证）。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/layout/test_settings_page_switch.py -v
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

import sopeek.ui.layout.settings_layout as sl_mod

pytestmark = pytest.mark.unit


@pytest.fixture
def layout(qapp: Any) -> Iterator[sl_mod.SettingsLayout]:
    """在离屏宿主窗口中创建并显示设置布局。"""
    host = QWidget()
    host.resize(1060, 780)
    outer = QVBoxLayout(host)
    outer.setContentsMargins(0, 0, 0, 0)
    widget = sl_mod.SettingsLayout(host, host_window=host)
    outer.addWidget(widget)
    host.show()
    qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()
    try:
        yield widget
    finally:
        host.close()
        host.deleteLater()
        qapp.processEvents()


def _click_item(
    layout: sl_mod.SettingsLayout, index: int, qapp: Any
) -> None:
    """点击侧栏第 *index* 项的中心。"""
    item = layout._sidebar._items[index]
    QTest.mouseClick(item, Qt.LeftButton, pos=item.rect().center())
    qapp.processEvents()


def _click_sidebar_point(
    layout: sl_mod.SettingsLayout, x: int, y: int, qapp: Any
) -> None:
    """按真实命中路由点击侧栏内一点（含行两侧留白）。"""
    sidebar = layout._sidebar
    global_pos = sidebar.mapToGlobal(QPoint(x, y))
    target = QApplication.widgetAt(global_pos)
    assert target is not None
    QTest.mouseClick(
        target, Qt.LeftButton, pos=target.mapFromGlobal(global_pos)
    )
    qapp.processEvents()


def _assert_content_in_sync(layout: sl_mod.SettingsLayout) -> None:
    """断言栈页 == 侧栏选中页，且实时内页可见、没有遗留遮罩。"""
    index = layout._stack.currentIndex()
    assert layout._sidebar.active_index == index
    inner = layout._page_inner_widget(index)
    assert inner is not None
    assert inner.isVisible()
    assert layout._page_transition_overlay is None
    assert layout._transition_hidden_inner is None


def test_single_switch_animates_then_restores(
    layout: sl_mod.SettingsLayout, qapp: Any
) -> None:
    """单次切页播放一层快照动画，结束后实时页恢复且遮罩释放。"""
    _click_item(layout, 2, qapp)

    overlay = layout._page_transition_overlay
    assert overlay is not None
    assert overlay.isVisible()
    assert overlay.testAttribute(Qt.WA_TransparentForMouseEvents)
    # 动画期间实时新页被快照接管（避免新旧文字重叠）。
    assert layout._page_inner_widget(2).isVisible() is False

    QTest.qWait(450)
    qapp.processEvents()
    _assert_content_in_sync(layout)
    assert layout._stack.currentIndex() == 2


def test_rapid_clicks_switch_instantly_without_stale_content(
    layout: sl_mod.SettingsLayout, qapp: Any
) -> None:
    """连点时第二次及之后的切页立即生效，不叠加快照、不显示旧页。"""
    _click_item(layout, 1, qapp)
    assert layout._stack.currentIndex() == 1

    QTest.qWait(20)
    _click_item(layout, 2, qapp)
    # 第二次点击应已瞬时切到目标页，且实时内容可见。
    _assert_content_in_sync(layout)
    assert layout._stack.currentIndex() == 2

    # 继续密集切换：每一步都必须与标签一致。
    for index in (3, 0, 2, 1, 3, 0):
        QTest.qWait(10)
        _click_item(layout, index, qapp)
        _assert_content_in_sync(layout)
        assert layout._stack.currentIndex() == index

    # 停止点击后，高亮条最终落到最后一项。
    QTest.qWait(900)
    qapp.processEvents()
    active = layout._sidebar.active_index
    _, top, bottom = layout._sidebar._get_item_bar_rect(active)
    assert layout._sidebar._highlight_bar._top_y == pytest.approx(top, abs=0.6)
    assert layout._sidebar._highlight_bar._bottom_y == pytest.approx(
        bottom, abs=0.6
    )
    assert layout._sidebar._animating is False


def test_watchdog_restores_page_if_finish_signal_is_lost(
    layout: sl_mod.SettingsLayout, qapp: Any
) -> None:
    """遮罩动画不结束时，看门狗强制收尾并恢复实时页。"""
    QTest.qWait(250)
    _click_item(layout, 1, qapp)
    overlay = layout._page_transition_overlay
    assert overlay is not None
    assert layout._page_switch_watchdog.isActive()

    # 等延迟起钟落地后再中断动画，确保模拟的是「动画不结束」而非
    # 起播前的空档（起播回调若尚未执行，stop 不会改变其后续启动）。
    QTest.qWait(30)
    qapp.processEvents()
    assert overlay.is_finished() is False
    overlay._anim.stop()
    QTest.qWait(sl_mod.SETTINGS_PAGE_SWITCH_WATCHDOG_MS + 250)
    qapp.processEvents()

    assert layout._page_transition_overlay is None
    assert layout._transition_hidden_inner is None
    assert layout._page_inner_widget(layout._stack.currentIndex()).isVisible()
    assert layout._stack.currentIndex() == 1


def test_sidebar_gutter_clicks_reach_pages(
    layout: sl_mod.SettingsLayout, qapp: Any
) -> None:
    """行左右留白与高亮条竖槽点击同样能切换设置页。"""
    QTest.qWait(250)
    sidebar = layout._sidebar
    item = sidebar._items[2]
    y = item.mapTo(sidebar, QPoint(0, item.height() // 2)).y()

    for x in (0, 5, 11, sidebar.width() - 1):
        # 先离开目标页，确保每次点击都发生实际切换。
        if layout._stack.currentIndex() == 2:
            _click_item(layout, 0, qapp)
            QTest.qWait(450)
            qapp.processEvents()
        _click_sidebar_point(layout, x, y, qapp)
        assert layout._stack.currentIndex() == 2, f"x={x} 未切换页面"
        QTest.qWait(450)
        qapp.processEvents()
        _assert_content_in_sync(layout)
