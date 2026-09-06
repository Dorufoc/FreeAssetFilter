# -*- coding: utf-8 -*-
"""框选状态机与释放丢失守卫单元测试。

覆盖文件选择器左键框选与暂存池右键框选的收尾契约：

* 松开事件正常到达时，状态必须完全复位（选框隐藏、守卫停止）；
* 松开事件丢失时，``QTimer`` 守卫必须兜底收尾——这是"框选态粘连"与
  "幽灵框"的共同根因（既有清理全部依赖事件到达 viewport，事件一旦丢失
  且鼠标不回到列表区，状态将永久残留）；
* 真实按住按键期间，守卫不得误杀进行中的框选。

两个布局均为模块级共享实例：离屏环境下同进程反复构造布局 + 框选操作序列
存在既有段错误（详见 .workbuddy/memory/MEMORY.md），共享实例可规避。

验证命令：
    python -m pytest tests/unit/ui/layout/test_rubber_selection_guard.py --timeout 60 -q
"""

# targets: ui.layout.file_selector_layout, ui.layout.file_pool_layout

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

# 布局模块内部使用短路径导入（from theme import tm / components.*），
# 要求 freeassetfilter/ui 位于 sys.path。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.layout.file_pool_layout import FilePoolLayout
from freeassetfilter.ui.layout.file_selector_layout import FileSelectorLayout

pytestmark = pytest.mark.unit

_START = QPoint(20, 20)
_END = QPoint(320, 320)


def _sample_files(count: int = 16) -> List[dict]:
    """生成填充选择器用的假文件信息。

    Args:
        count: 文件数量。

    Returns:
        文件信息字典列表。
    """
    return [
        {
            "name": f"guard_file_{i}.txt",
            "path": f"C:/tmp/guard_file_{i}.txt",
            "is_dir": False,
            "size": 1024,
            "modified": "2026-01-01 00:00:00",
            "created": "2026-01-01 00:00:00",
            "suffix": "txt",
        }
        for i in range(count)
    ]


def _mouse_event(
    kind: QEvent.Type, pos: QPoint, button: Qt.MouseButton, buttons: Qt.MouseButton
) -> QMouseEvent:
    """构造合成鼠标事件（局部/全局坐标一致）。

    Args:
        kind: 事件类型（Press / Move / Release）。
        pos: 目标位置（viewport 坐标）。
        button: 触发本次事件的按键（Move 用 NoButton）。
        buttons: 当前处于按下态的按键集合。

    Returns:
        构造好的 QMouseEvent。
    """
    from PySide6.QtCore import QPointF

    return QMouseEvent(kind, QPointF(pos), QPointF(pos), button, buttons, Qt.NoModifier)


def _send(widget: Any, event: QMouseEvent) -> None:
    """向控件派发合成事件。

    Args:
        widget: 事件目标控件。
        event: 待派发的事件。
    """
    QApplication.sendEvent(widget, event)


@pytest.fixture(scope="module")
def selector(qapp: Any) -> FileSelectorLayout:
    """模块级共享的选择器布局（避免同进程反复构造布局触发离屏段错误）。

    Args:
        qapp: 会话级 QApplication fixture。

    Yields:
        已填充数据的 FileSelectorLayout。
    """
    layout = FileSelectorLayout()
    layout.resize(640, 760)
    layout.show()
    layout._file_model.set_files(_sample_files())
    QApplication.processEvents()
    try:
        layout._update_grid_size()
    except Exception:  # noqa: BLE001 - 探测性调用，失败不影响后续断言
        pass
    QApplication.processEvents()
    yield layout
    layout._abort_rubber_selection()


@pytest.fixture(scope="module")
def pool(qapp: Any) -> FilePoolLayout:
    """模块级共享的暂存池布局（挂起备份写盘，避免测试污染用户数据）。

    Args:
        qapp: 会话级 QApplication fixture。

    Yields:
        已填充卡片的 FilePoolLayout。
    """
    layout = FilePoolLayout()
    layout.resize(640, 760)
    layout.show()
    layout._suspend_backup_save = True
    for i in range(8):
        layout.add_file(
            {
                "name": f"guard_pool_{i}.txt",
                "path": f"C:/tmp/guard_pool_{i}.txt",
                "is_dir": False,
                "size": 512,
                "modified": "2026-01-01 00:00:00",
                "created": "2026-01-01 00:00:00",
                "suffix": "txt",
            }
        )
    QApplication.processEvents()
    yield layout
    layout._abort_pool_rubber_selection()


@pytest.fixture(autouse=True)
def _reset_state(selector: FileSelectorLayout, pool: FilePoolLayout) -> None:
    """每个用例前复位两侧框选状态与选中态，保证用例互不影响。

    Args:
        selector: 共享选择器实例。
        pool: 共享暂存池实例。
    """
    selector._abort_rubber_selection()
    selector._clear_selector_selection()
    pool._abort_pool_rubber_selection()
    QApplication.processEvents()


def _assert_selector_clean(layout: FileSelectorLayout) -> None:
    """断言选择器框选状态已完全复位。

    Args:
        layout: 被测选择器布局。
    """
    band_visible = bool(
        layout._rubber_band is not None and layout._rubber_band.isVisible()
    )
    guard_running = bool(
        layout._rubber_guard_timer is not None and layout._rubber_guard_timer.isActive()
    )
    assert not layout._rubber_active
    assert layout._rubber_start_pos is None
    assert layout._rubber_rect is None
    assert layout._rubber_last_pos is None
    assert not band_visible
    assert not guard_running


def _assert_pool_clean(layout: FilePoolLayout) -> None:
    """断言暂存池框选状态已复位。

    Args:
        layout: 被测暂存池布局。
    """
    band_visible = bool(
        layout._pool_rubber_band is not None and layout._pool_rubber_band.isVisible()
    )
    guard_running = bool(
        layout._pool_rubber_guard_timer is not None
        and layout._pool_rubber_guard_timer.isActive()
    )
    assert not layout._pool_rubber_active
    assert layout._pool_rubber_start_pos is None
    assert not band_visible
    assert not guard_running


class TestSelectorRubberRelease:
    """文件选择器左键框选的收尾契约。"""

    def test_release_normal_cleans_state(self, selector: FileSelectorLayout) -> None:
        """按下 → 拖拽 → 松开：入池触发且状态完全复位。"""
        added: List[dict] = []
        selector.add_to_pool_requested.connect(added.append)
        viewport = selector._file_list.viewport()

        _send(viewport, _mouse_event(QEvent.MouseButtonPress, _START, Qt.LeftButton, Qt.LeftButton))
        _send(viewport, _mouse_event(QEvent.MouseMove, _END, Qt.NoButton, Qt.LeftButton))
        assert selector._rubber_active
        _send(viewport, _mouse_event(QEvent.MouseButtonRelease, _END, Qt.LeftButton, Qt.NoButton))

        assert added, "框选收尾应把命中的卡片送入暂存池"
        assert not selector._file_model.get_selected_rows(), "收尾后选择器选中态应清空"
        _assert_selector_clean(selector)

    def test_release_lost_guard_finalizes(self, selector: FileSelectorLayout) -> None:
        """松开事件丢失时，守卫必须兜底收尾并清空状态。"""
        added: List[dict] = []
        selector.add_to_pool_requested.connect(added.append)
        viewport = selector._file_list.viewport()

        _send(viewport, _mouse_event(QEvent.MouseButtonPress, _START, Qt.LeftButton, Qt.LeftButton))
        _send(viewport, _mouse_event(QEvent.MouseMove, _END, Qt.NoButton, Qt.LeftButton))
        # 此刻处于"粘连"态：左键实际已松开，但松开事件从未到达
        assert selector._rubber_active
        assert selector._rubber_start_pos is not None

        selector._on_rubber_guard_tick()

        assert added, "守卫收尾应沿用最后一次拖拽位置完成入池"
        assert not selector._file_model.get_selected_rows()
        _assert_selector_clean(selector)

    def test_card_click_clears_state(self, selector: FileSelectorLayout) -> None:
        """卡片起点单击（未超过拖拽阈值）：状态复位且守卫不残留。"""
        viewport = selector._file_list.viewport()
        _send(viewport, _mouse_event(QEvent.MouseButtonPress, _START, Qt.LeftButton, Qt.LeftButton))
        _send(viewport, _mouse_event(QEvent.MouseButtonRelease, _START, Qt.LeftButton, Qt.NoButton))
        _assert_selector_clean(selector)

    def test_blank_click_clears_state(self, selector: FileSelectorLayout) -> None:
        """空白起点单击：状态复位。"""
        viewport = selector._file_list.viewport()
        blank = QPoint(4, max(4, viewport.height() - 4))
        _send(viewport, _mouse_event(QEvent.MouseButtonPress, blank, Qt.LeftButton, Qt.LeftButton))
        _send(viewport, _mouse_event(QEvent.MouseButtonRelease, blank, Qt.LeftButton, Qt.NoButton))
        _assert_selector_clean(selector)

    def test_guard_keeps_selection_while_button_held(self, selector: FileSelectorLayout) -> None:
        """真实按住左键并跨过多个守卫周期时，守卫不得提前收尾。"""
        viewport = selector._file_list.viewport()
        QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, QPoint(20, 20), 0)
        QTest.mouseMove(viewport, QPoint(320, 320), 0)
        try:
            assert selector._rubber_active, "拖拽超过阈值后应进入框选态"
            assert QApplication.mouseButtons() & Qt.LeftButton, "QTest 应反映真实按键状态"
            # 跨过两个守卫周期（interval=100ms）
            QTest.qWait(260)
            assert selector._rubber_active, "按住期间守卫不得误杀进行中的框选"
        finally:
            QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, QPoint(320, 320), 0)
        _assert_selector_clean(selector)


class TestPoolRubberRelease:
    """暂存池右键框选的收尾契约。"""

    def test_release_normal_removes_cards(self, pool: FilePoolLayout, monkeypatch) -> None:
        """右键拖拽松开：移除框内卡片且状态复位。"""
        removed: List[str] = []
        monkeypatch.setattr(pool, "remove_file", lambda path: removed.append(path))
        viewport = pool._scroll_area.viewport()

        _send(viewport, _mouse_event(QEvent.MouseButtonPress, QPoint(10, 10), Qt.RightButton, Qt.RightButton))
        _send(viewport, _mouse_event(QEvent.MouseMove, _END, Qt.NoButton, Qt.RightButton))
        assert pool._pool_rubber_active
        _send(viewport, _mouse_event(QEvent.MouseButtonRelease, _END, Qt.RightButton, Qt.NoButton))

        assert removed, "框选收尾应移除框内卡片"
        _assert_pool_clean(pool)

    def test_release_lost_guard_finalizes(self, pool: FilePoolLayout, monkeypatch) -> None:
        """右键松开事件丢失时，守卫必须兜底收尾。"""
        removed: List[str] = []
        monkeypatch.setattr(pool, "remove_file", lambda path: removed.append(path))
        viewport = pool._scroll_area.viewport()

        _send(viewport, _mouse_event(QEvent.MouseButtonPress, QPoint(10, 10), Qt.RightButton, Qt.RightButton))
        _send(viewport, _mouse_event(QEvent.MouseMove, _END, Qt.NoButton, Qt.RightButton))
        assert pool._pool_rubber_active

        pool._on_pool_rubber_guard_tick()

        assert removed, "守卫收尾应沿用最后一次拖拽位置移除卡片"
        _assert_pool_clean(pool)

    def test_guard_stops_after_abort(self, pool: FilePoolLayout) -> None:
        """abort 后守卫定时器必须停止，避免空转。"""
        viewport = pool._scroll_area.viewport()
        _send(viewport, _mouse_event(QEvent.MouseButtonPress, QPoint(10, 10), Qt.RightButton, Qt.RightButton))
        _send(viewport, _mouse_event(QEvent.MouseMove, _END, Qt.NoButton, Qt.RightButton))
        timer = pool._pool_rubber_guard_timer
        assert timer is not None and timer.isActive(), "进入框选态应启动守卫"

        pool._abort_pool_rubber_selection()
        assert not timer.isActive(), "abort 后守卫必须停止"
