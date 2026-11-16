# -*- coding: utf-8 -*-
"""侧栏导航点击热区与高亮条同步测试。

覆盖：

* 行两侧留白 / 高亮条竖槽 / 图标 / 文字 / 右侧空白都能选中对应标签；
* 行间 2px 间隔不属于任何标签，点击不改变选中项；
* 连续快速点击后，高亮条最终停在最后一次选中的标签上
  （历史缺陷：动画期间后续点击只改活动项，高亮条停在旧目标）；
* 重复点击已激活项时高亮条保持对齐。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/components/test_styled_sidebar.py -v
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from sopeek.ui.components.styled_sidebar import StyledSidebar

pytestmark = pytest.mark.unit

LABELS = ("通用", "外观", "检查更新", "关于 Sopeek")


@pytest.fixture
def sidebar(qapp: Any) -> Iterator[StyledSidebar]:
    """创建 4 项侧栏并显示（离屏后端）。"""
    host = QWidget()
    host.resize(300, 420)
    outer = QVBoxLayout(host)
    outer.setContentsMargins(0, 0, 0, 0)
    widget = StyledSidebar(width=220, transparent=True)
    for label in LABELS:
        widget.add_item(label)
    outer.addWidget(widget)
    host.show()
    qapp.processEvents()
    try:
        yield widget
    finally:
        host.close()
        host.deleteLater()
        qapp.processEvents()


def _row_y(sidebar: StyledSidebar, index: int, qapp: Any) -> int:
    """返回侧栏坐标系中第 *index* 行的高度中线。"""
    item = sidebar._items[index]
    qapp.processEvents()
    return item.mapTo(sidebar, QPoint(0, item.height() // 2)).y()


def _click_sidebar_point(
    sidebar: StyledSidebar, x: int, y: int, qapp: Any
) -> None:
    """按真实鼠标路由点击侧栏内的一点（先找最深层控件再点击）。

    ``QTest.mouseClick(sidebar, ...)`` 只会把事件直接发给侧栏本身，
    无法验证子控件/容器的事件路由；这里用 ``QApplication.widgetAt``
    模拟真实命中测试。
    """
    global_pos = sidebar.mapToGlobal(QPoint(x, y))
    target = QApplication.widgetAt(global_pos)
    assert target is not None
    QTest.mouseClick(
        target, Qt.LeftButton, pos=target.mapFromGlobal(global_pos)
    )
    qapp.processEvents()


def _wait_settled(qapp: Any, ms: int = 900) -> None:
    """等待高亮条两段动画（180ms × 2）与切页动画完全结束。"""
    QTest.qWait(ms)
    qapp.processEvents()


def _assert_bar_at_active(sidebar: StyledSidebar) -> None:
    """断言高亮条几何与当前活动标签一致。"""
    assert sidebar.active_index >= 0
    _, expected_top, expected_bottom = sidebar._get_item_bar_rect(
        sidebar.active_index
    )
    assert sidebar._highlight_bar._top_y == pytest.approx(expected_top, abs=0.6)
    assert sidebar._highlight_bar._bottom_y == pytest.approx(
        expected_bottom, abs=0.6
    )
    assert sidebar._animating is False


def test_whole_row_is_clickable_including_side_gutters(
    sidebar: StyledSidebar, qapp: Any
) -> None:
    """整行（含左右留白与高亮条竖槽）都能选中对应标签。"""
    selected: list[int] = []
    sidebar.item_selected.connect(
        lambda index, _label: selected.append(index)
    )

    first = sidebar._items[0]
    second = sidebar._items[1]
    y = _row_y(sidebar, 1, qapp)
    label = second._label_widget
    label_center = label.mapTo(sidebar, label.rect().center()).x()
    item_left = second.mapTo(sidebar, QPoint(0, 0)).x()
    item_right = second.mapTo(sidebar, QPoint(second.width(), 0)).x()

    click_xs = [
        0,                      # 左留白
        5,                      # 高亮条竖槽
        11,                     # 左留白紧贴行
        item_left,              # 行左缘
        second._icon_widget.mapTo(sidebar, second._icon_widget.rect().center()).x(),
        label_center,           # 文字
        item_right - 2,         # 行内右侧空白
        item_right + 4,         # 右留白
        sidebar.width() - 1,    # 侧栏右缘
    ]
    for x in click_xs:
        before = len(selected)
        _click_sidebar_point(sidebar, x, y, qapp)
        assert sidebar.active_index == 1, f"x={x} 未命中第 2 行"
        assert len(selected) == before + 1
        assert selected[-1] == 1

    # 行间 2px 间隔不属于任何标签：点击不改变选中项。
    gap_y = first.mapTo(sidebar, QPoint(0, first.height())).y() + 1
    _click_sidebar_point(sidebar, item_left, gap_y, qapp)
    assert sidebar.active_index == 1


def test_rapid_clicks_keep_highlight_on_latest_target(
    sidebar: StyledSidebar, qapp: Any
) -> None:
    """连点后高亮条必须停在最后一次选中项（截图错位的回归用例）。"""
    items = sidebar._items

    # 复现截图场景：先点「关于」，20ms 内再点「检查更新」。
    QTest.mouseClick(items[3], Qt.LeftButton, pos=items[3].rect().center())
    qapp.processEvents()
    QTest.qWait(20)
    QTest.mouseClick(items[2], Qt.LeftButton, pos=items[2].rect().center())
    qapp.processEvents()

    assert sidebar.active_index == 2
    _wait_settled(qapp)
    _assert_bar_at_active(sidebar)

    # 更密集的来回切换：最后一次目标仍必须生效。
    for index in (1, 3, 0, 2, 3, 1, 0, 2):
        QTest.mouseClick(
            items[index], Qt.LeftButton, pos=items[index].rect().center()
        )
        qapp.processEvents()
        QTest.qWait(5)

    assert sidebar.active_index == 2
    _wait_settled(qapp)
    _assert_bar_at_active(sidebar)


def test_clicking_active_item_keeps_bar_aligned(
    sidebar: StyledSidebar, qapp: Any
) -> None:
    """重复点击已激活项不应让高亮条漂移。"""
    item = sidebar._items[0]
    for _ in range(3):
        QTest.mouseClick(item, Qt.LeftButton, pos=item.rect().center())
        qapp.processEvents()
    _wait_settled(qapp)
    assert sidebar.active_index == 0
    _assert_bar_at_active(sidebar)
