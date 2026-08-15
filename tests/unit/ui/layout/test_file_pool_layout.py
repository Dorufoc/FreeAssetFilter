"""
FilePoolLayout 浮动滚动条回归测试

覆盖滚动条「完全浮动、不占用布局空间、不改变卡片边缘位置」的行为，
与 FileSelectorLayout 的恒定对称边距逻辑保持一致。

背景：_update_pool_card_margins 曾根据滚动条状态动态重分配左右边距
（有滚动条时 left=6/right=14），导致滚动条出现时 info card 向左挤压。
修复后边距恒定 (10*dpi, 6, 10*dpi, 6)，卡片永不移动。
"""

import sys
import time
from pathlib import Path

# Match the sys.path bootstrap used by sibling layout tests so that the
# ui-relative imports (`from theme import tm`, `from components.*`) resolve.
_UI_ROOT = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

import pytest

from freeassetfilter.ui.layout.file_pool_layout import FilePoolLayout


@pytest.fixture
def pool(qapp) -> FilePoolLayout:
    """创建 FilePoolLayout 实例并在测试结束后清理。"""
    layout = FilePoolLayout()
    layout.resize(420, 620)
    layout.show()
    qapp.processEvents()
    try:
        yield layout
    finally:
        layout.close()
        layout.deleteLater()


def _add_items(pool: FilePoolLayout, qapp, count: int = 20) -> None:
    """添加条目并等待布局/动画稳定，确保滚动范围出现。"""
    for i in range(count):
        pool.add_file(
            {
                "path": rf"D:\tmp\faf_pool_test_{i}.png",
                "display_name": f"faf_pool_test_{i}.png",
            }
        )
    for _ in range(50):
        qapp.processEvents()
        time.sleep(0.02)


class TestPoolFloatingScrollbar:
    """浮动滚动条不占用布局空间、不改变卡片边缘位置。"""

    def test_empty_pool_geometry(self, pool, qapp) -> None:
        """空池：边距 (10,6,10,6)、scroll_area 全宽、滚动条浮动于右缘。"""
        m = pool._card_layout.contentsMargins()
        assert (m.left(), m.top(), m.right(), m.bottom()) == (10, 6, 10, 6)
        assert pool._scroll_area.width() == 420
        assert pool._pool_scrollbar.parent() is pool._content_area
        # 滚动条悬浮覆盖在右侧（8px 宽贴右缘），不参与布局
        assert pool._pool_scrollbar.x() == 420 - pool._pool_scrollbar.width()
        assert pool._pool_scrollbar.y() == 10

    def test_scrolled_pool_margins_constant(self, pool, qapp) -> None:
        """滚动条出现后：边距仍 (10,6,10,6)，卡片 x 不左移，scroll_area 保持全宽。"""
        _add_items(pool, qapp)
        vbar = pool._scroll_area.verticalScrollBar()
        assert vbar.maximum() > 0, "测试前提：应已触发滚动范围"

        m = pool._card_layout.contentsMargins()
        assert (m.left(), m.top(), m.right(), m.bottom()) == (10, 6, 10, 6)

        first_card = next(iter(pool._card_widgets.values()))
        assert first_card.x() == 10, "卡片左缘不应因滚动条出现而移动"

        assert pool._scroll_area.width() == 420
        assert pool._pool_scrollbar.x() == 420 - pool._pool_scrollbar.width()
        assert pool._pool_scrollbar.y() == 10

    def test_margins_identical_before_and_after_scroll(self, pool, qapp) -> None:
        """滚动条出现前后边距完全一致（卡片边缘位置不变）。"""
        m_before = pool._card_layout.contentsMargins()
        _add_items(pool, qapp)
        m_after = pool._card_layout.contentsMargins()
        assert (m_before.left(), m_before.right()) == (m_after.left(), m_after.right())

    def test_update_pool_card_margins_idempotent(self, pool, qapp) -> None:
        """手动触发边距重算不改变现有值（幂等，避免无谓布局刷新）。"""
        m_before = pool._card_layout.contentsMargins()
        pool._update_pool_card_margins()
        m_after = pool._card_layout.contentsMargins()
        assert m_before == m_after
