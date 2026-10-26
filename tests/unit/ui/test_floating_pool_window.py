# -*- coding: utf-8 -*-
"""FloatingPoolWindow 窗口本体测试（折叠/展开两态 + 主题自绘 + 拖动定位）。

覆盖 Todo 1 的窗口骨架：

* 窗口标志（置顶 / 无边框 / Tool）与属性（半透明、显示不激活、关闭不退出）；
* 无父顶层窗口；
* 折叠 / 展开两态固定尺寸（展开态高度按屏幕可用高度 70% 钳制）；
* ``paintEvent`` 自绘不抛异常（经 ``grab()`` 触发渲染）；
* ``__init__`` 预声明的延后 Todo 状态属性（防抖引用 / 宿主窗口 / 主题连接）。

运行：

    QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/ui/test_floating_pool_window.py -v
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import (
    QEvent,
    QEasingCurve,
    QMimeData,
    QPoint,
    QPointF,
    QRect,
    QSize,
    Qt,
    QUrl,
)
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QMouseEvent,
    QCursor,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from freeassetfilter.ui.floating_pool_window import (
    COLLAPSED_SIZE,
    DRAG_HOVER_SIZE,
    ENTRANCE_SCALE_FROM,
    EXIT_BUDGET_MS,
    EXPANDED_HEIGHT_RATIO,
    EXPANDED_SIZE,
    FLOATING_DRAG_MIME,
    INITIAL_INSET,
    SETTLE_DELAY_MS,
    SNAP_DURATION_MS,
    SNAP_THRESHOLD,
    FloatingPoolWindow,
    _CARD_MARGIN,
    _PoolItemRow,
)
from freeassetfilter.ui.components.styled_scroll_area import (
    StyledScrollArea,
    StyledScrollBar,
)
from freeassetfilter.ui.theme import tm
from freeassetfilter.utils.screen_utils import derive_work_area, screen_work_area

pytestmark = pytest.mark.unit


def _expected_expanded_size() -> QSize:
    """按同款钳制公式从当前屏幕真实可用高度推导展开态期望尺寸。

    Returns:
        QSize: 宽度取 ``EXPANDED_SIZE.width()``，高度为
        ``min(EXPANDED_SIZE.height(), int(avail_h * EXPANDED_HEIGHT_RATIO))``。
    """
    screen = QApplication.screenAt(QCursor.pos())
    if screen is None:
        screen = QApplication.primaryScreen()
    assert screen is not None
    avail_h = screen_work_area(screen).height()
    clamped = min(EXPANDED_SIZE.height(), int(avail_h * EXPANDED_HEIGHT_RATIO))
    return QSize(EXPANDED_SIZE.width(), clamped)


def test_window_flags_and_attributes(qapp: QApplication) -> None:
    """窗口置顶 / 无边框 / Tool 标志齐备，且属性正确（关闭不退出进程）。"""
    window = FloatingPoolWindow()
    try:
        flags = window.windowFlags()
        assert flags & Qt.WindowStaysOnTopHint
        assert flags & Qt.Tool
        assert flags & Qt.FramelessWindowHint
        assert window.parent() is None
        assert window.testAttribute(Qt.WA_TranslucentBackground)
        assert window.testAttribute(Qt.WA_ShowWithoutActivating)
        assert not window.testAttribute(Qt.WA_QuitOnClose)
    finally:
        window.deleteLater()


def test_collapsed_initial_size(qapp: QApplication) -> None:
    """构造后默认处于折叠态，尺寸为 ``COLLAPSED_SIZE``。"""
    window = FloatingPoolWindow()
    try:
        assert window.size() == COLLAPSED_SIZE
    finally:
        window.deleteLater()


def test_set_expanded_true_clamps_height(qapp: QApplication) -> None:
    """``set_expanded(True)`` 后尺寸为按屏幕可用高度钳制的展开尺寸。"""
    window = FloatingPoolWindow()
    try:
        window.set_expanded(True)
        assert window.size() == _expected_expanded_size()
    finally:
        window.deleteLater()


def test_set_expanded_false_restores_collapsed(qapp: QApplication) -> None:
    """``set_expanded(False)`` 后尺寸恢复为 ``COLLAPSED_SIZE``。"""
    window = FloatingPoolWindow()
    try:
        window.set_expanded(True)
        window.set_expanded(False)
        assert window.size() == COLLAPSED_SIZE
    finally:
        window.deleteLater()


def _screen_and_available(window: FloatingPoolWindow) -> tuple:
    """返回窗口所在屏幕及其真实可用工作区（``screenAt`` → 主屏幕回退）。

    Args:
        window: 目标浮窗（以左上角全局坐标判定落在哪块屏幕）。

    Returns:
        tuple: ``(QScreen | None, QRect | None)``。
    """
    screen = QApplication.screenAt(window.pos())
    if screen is None:
        screen = QApplication.primaryScreen()
    if screen is None:
        return None, None
    return screen, screen_work_area(screen)


# ── 工作区推导（任务栏任意停靠侧）─────────────────────────────


def test_derive_work_area_left_docked_taskbar_at_150_percent() -> None:
    """任务栏在左（实测 150% 缩放）：左缩量取缩放值，右缘不越屏。"""
    geometry = QRect(0, 0, 1707, 1067)
    # Qt 实测输出：左缩量 72 是未缩放的物理像素（应为 48）
    available = QRect(72, 0, 1659, 1067)

    work = derive_work_area(geometry, available)

    assert work.left() == 48
    assert work.top() == 0
    assert work.width() == 1659
    assert work.height() == 1067
    assert work.right() == geometry.right()
    assert geometry.contains(work)


def test_derive_work_area_top_docked_taskbar_at_150_percent() -> None:
    """任务栏在上（150% 缩放）：上缩量取缩放值，下缘不越屏。"""
    geometry = QRect(0, 0, 1707, 1067)
    available = QRect(0, 60, 1707, 1027)  # 60 物理像素 → 40 逻辑像素

    work = derive_work_area(geometry, available)

    assert work.top() == 40
    assert work.height() == 1027
    assert work.bottom() == geometry.bottom()
    assert geometry.contains(work)


def test_derive_work_area_right_docked_taskbar_insets_right_edge() -> None:
    """任务栏在右：内缩量归右缘（左上角无偏移）。"""
    geometry = QRect(0, 0, 1920, 1080)
    available = QRect(0, 0, 1872, 1080)  # 48px 任务栏

    work = derive_work_area(geometry, available)

    assert work == QRect(0, 0, 1872, 1080)


def test_derive_work_area_bottom_taskbar_matches_qt() -> None:
    """任务栏在下（回归基线）：结果与原 Qt 可用区等价，行为不应变化。"""
    geometry = QRect(0, 0, 1920, 1080)
    available = QRect(0, 0, 1920, 1040)

    assert derive_work_area(geometry, available) == available


def test_derive_work_area_without_taskbar_returns_geometry() -> None:
    """无任务栏占位（自动隐藏 / 全屏）时工作区即物理屏幕。"""
    geometry = QRect(-1920, 0, 1920, 1080)

    assert derive_work_area(geometry, geometry) == geometry
    assert derive_work_area(geometry, QRect()) == geometry
    assert derive_work_area(QRect(), QRect(0, 0, 10, 10)) == QRect()


def test_initial_position_stays_inside_work_area(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """任务栏在左时首帧定位不得越出工作区（回归：右缘曾露到屏幕外）。"""
    import freeassetfilter.ui.floating_pool_window as fpw

    work = QRect(48, 0, 1659, 1067)  # 2560x1600 @150% + 左侧 72px 任务栏
    monkeypatch.setattr(fpw, "screen_work_area", lambda _screen: QRect(work))

    window = fpw.FloatingPoolWindow()
    try:
        geo = window.geometry()
        assert geo.left() >= work.left()
        assert geo.top() >= work.top()
        assert geo.right() <= work.right()
        assert geo.bottom() <= work.bottom()
        # 右缘留白与吸附口径一致（均为 INITIAL_INSET）
        assert geo.right() == work.right() - INITIAL_INSET
        assert geo.top() == work.top() + INITIAL_INSET
    finally:
        window.deleteLater()


def test_settle_clamps_inside_work_area_with_left_taskbar(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """任务栏在左 + 关闭吸附：拖到屏外后仍完整夹回工作区内。"""
    import freeassetfilter.ui.floating_pool_window as fpw

    work = QRect(48, 0, 1659, 1067)
    monkeypatch.setattr(fpw, "screen_work_area", lambda _screen: QRect(work))

    window = fpw.FloatingPoolWindow()
    try:
        final = _settle_at(window, work.right() + 200, work.bottom() + 200, snap=False)
        assert final.x() == work.right() - window.width() + 1
        assert final.y() == work.bottom() - window.height() + 1
        assert final.x() + window.width() - 1 <= work.right()
        assert final.y() + window.height() - 1 <= work.bottom()
    finally:
        window.deleteLater()


def test_set_expanded_stays_within_available_geometry(
    qapp: QApplication,
) -> None:
    """展开态窗口（默认右上角定位）不越过屏幕可用区域右缘。"""
    window = FloatingPoolWindow()
    try:
        window.set_expanded(True)
        _wait_move_animation(window)
        _screen, avail = _screen_and_available(window)
        assert avail is not None
        geo = window.geometry()
        assert geo.left() >= avail.left()
        assert geo.right() <= avail.right()
    finally:
        window.deleteLater()


def test_set_expanded_preserves_right_edge(qapp: QApplication) -> None:
    """默认定位下展开向左侧生长：右边缘在屏幕内容许时保持不变。"""
    window = FloatingPoolWindow()
    try:
        collapsed_right = window.x() + window.width()
        _screen, avail = _screen_and_available(window)
        assert avail is not None

        window.set_expanded(True)
        _wait_move_animation(window)

        expected = min(collapsed_right, avail.right() + 1)
        assert window.x() + window.width() == expected
    finally:
        window.deleteLater()


def test_set_expanded_grows_right_when_near_left_edge(qapp: QApplication) -> None:
    """贴工作区左缘时以左缘为固定边向右展开（左缘不动）。"""
    window = FloatingPoolWindow()
    try:
        _screen, avail = _screen_and_available(window)
        assert avail is not None
        start_x = avail.left() + INITIAL_INSET
        window.move(start_x, avail.top() + INITIAL_INSET)

        window.set_expanded(True)
        _wait_move_animation(window)

        assert window.x() == start_x, "左缘应为固定边，不得移动"
        assert window.x() + window.width() - 1 <= avail.right()
    finally:
        window.deleteLater()


@pytest.mark.parametrize(
    "corner", ["top-left", "top-right", "bottom-left", "bottom-right"]
)
def test_expanded_panel_anchors_to_nearest_edges(
    qapp: QApplication, corner: str
) -> None:
    """四个角：展开时固定边不动、整体完整落在真实工作区内。"""
    window = FloatingPoolWindow()
    try:
        _screen, work = _screen_and_available(window)
        assert work is not None
        near_right = "right" in corner
        near_bottom = "bottom" in corner
        x = (
            work.right() - window.width() + 1 - INITIAL_INSET
            if near_right
            else work.left() + INITIAL_INSET
        )
        y = (
            work.bottom() - window.height() + 1 - INITIAL_INSET
            if near_bottom
            else work.top() + INITIAL_INSET
        )
        window.move(x, y)
        fixed_right = window.x() + window.width() - 1
        fixed_bottom = window.y() + window.height() - 1

        window.set_expanded(True)
        _wait_move_animation(window)

        geo = window.geometry()
        assert work.contains(geo), f"展开后越出工作区：{geo} vs {work}"
        if near_right:
            assert geo.right() == fixed_right, "右缘为固定边，不得移动"
        else:
            assert geo.left() == x, "左缘为固定边，不得移动"
        if near_bottom:
            assert geo.bottom() == fixed_bottom, "下缘为固定边，不得移动"
        else:
            assert geo.top() == y, "上缘为固定边，不得移动"
    finally:
        window.deleteLater()


@pytest.mark.parametrize(
    "corner", ["top-left", "top-right", "bottom-left", "bottom-right"]
)
def test_collapse_returns_to_original_circle_position(
    qapp: QApplication, corner: str
) -> None:
    """展开再收拢：圆形回到原位（不滑到另一侧、整体无位移）。"""
    window = FloatingPoolWindow()
    try:
        _screen, work = _screen_and_available(window)
        assert work is not None
        window.set_snap_enabled(False)
        x = (
            work.right() - window.width() + 1 - INITIAL_INSET
            if "right" in corner
            else work.left() + INITIAL_INSET
        )
        y = (
            work.bottom() - window.height() + 1 - INITIAL_INSET
            if "bottom" in corner
            else work.top() + INITIAL_INSET
        )
        window.move(x, y)
        original = window.geometry()

        window.show()
        qapp.processEvents()
        window.set_expanded(True)
        assert _wait_until(lambda: window._morph >= 1.0)

        window.set_expanded(False)
        assert _wait_until(lambda: window.size() == COLLAPSED_SIZE)
        assert window.geometry() == original, "收拢后圆形位置发生偏移"
    finally:
        window.close()
        window.deleteLater()


def test_drag_hover_pill_grows_inward_when_near_left_edge(
    qapp: QApplication, tmp_path: Path
) -> None:
    """贴左缘时拖入胶囊以左缘为固定边向右拉伸，收回后位置不偏移。"""
    window = FloatingPoolWindow()
    try:
        _screen, work = _screen_and_available(window)
        assert work is not None
        start_x = work.left() + INITIAL_INSET
        window.move(start_x, work.top() + INITIAL_INSET)
        window.show()
        qapp.processEvents()

        target = tmp_path / "pill_left_growth.txt"
        target.write_text("x", encoding="utf-8")
        mime = _mime_for([str(target)])
        window.dragEnterEvent(
            QDragEnterEvent(
                QPoint(10, 10),
                Qt.CopyAction,
                mime,
                Qt.LeftButton,
                Qt.NoModifier,
            )
        )
        assert _wait_until(lambda: window.size() == DRAG_HOVER_SIZE), (
            "拖入后窗口未拉伸为胶囊"
        )
        assert window.x() == start_x, "左缘为固定边，不得向屏幕外生长"
        assert window.x() + window.width() - 1 <= work.right()

        window.dragLeaveEvent(QDragLeaveEvent())
        assert _wait_until(lambda: window.size() == COLLAPSED_SIZE)
        assert window.x() == start_x, "胶囊收回后圆形位置发生偏移"
    finally:
        window.close()
        window.deleteLater()


@pytest.mark.parametrize(
    ("anchor_right", "anchor_bottom"),
    [(True, False), (False, True), (False, False), (True, True)],
)
def test_morph_card_grows_from_anchored_corner(
    qapp: QApplication, anchor_right: bool, anchor_bottom: bool
) -> None:
    """形变卡片从锚定角扩散：固定边在窗口内保持不动，卡片不越出窗口。"""
    window = FloatingPoolWindow()
    try:
        window.set_expanded(True)  # 未上屏：同步落定展开几何与 morph=1
        window._anchor_right = anchor_right
        window._anchor_bottom = anchor_bottom
        window._morph = 0.5

        card = window._card_rect()
        assert window.rect().contains(card.toAlignedRect())
        assert card.width() < window.width() - 2 * _CARD_MARGIN
        assert card.height() < window.height() - 2 * _CARD_MARGIN
        if anchor_right:
            assert card.right() == pytest.approx(window.width() - _CARD_MARGIN)
        else:
            assert card.left() == pytest.approx(float(_CARD_MARGIN))
        if anchor_bottom:
            assert card.bottom() == pytest.approx(window.height() - _CARD_MARGIN)
        else:
            assert card.top() == pytest.approx(float(_CARD_MARGIN))
    finally:
        window.deleteLater()


def test_set_expanded_clamps_bottom_edge_when_near_screen_bottom(
    qapp: QApplication,
) -> None:
    """折叠态贴着可用区下缘时展开：y 一并钳制，展开下缘不越出屏幕。

    回归：``set_expanded`` 早期只钳 x 不钳 y，贴近屏幕底部的胶囊展开后
    （高度 48 → 360）下缘越出可用区下界；同时锁定水平 / 垂直都不越出工作区。
    展开改为原子 ``setGeometry`` 后**不得**再经位移动画（否则固定边外扩会把
    面板推出屏幕再滑回）。
    """
    window = FloatingPoolWindow()
    try:
        _screen, avail = _screen_and_available(window)
        assert avail is not None

        calls: list[QPoint] = []
        original_animate_move = window._animate_move

        def _spy_animate_move(target: QPoint) -> None:
            calls.append(target)
            original_animate_move(target)

        window._animate_move = _spy_animate_move

        # 折叠态下缘贴住可用区下缘（包含式：bottom() == y + height - 1）。
        start_y = avail.bottom() - window.height() + 1
        assert start_y > avail.top()
        window.move(300, start_y)

        window.set_expanded(True)
        _wait_move_animation(window)

        _screen_now, avail_now = _screen_and_available(window)
        assert avail_now is not None
        geo = window.geometry()
        # 下缘不越界（包含式边界）。
        assert window.y() + window.height() - 1 <= avail_now.bottom()
        # 上缘同样不越界。
        assert window.y() >= avail_now.top()
        # 精确落位：y 被钳到可用区下缘（包含式）。
        assert window.y() == avail_now.bottom() - window.height() + 1
        # 水平方向按就近锚定（此位置贴左侧 → 左缘固定），整体不越界。
        assert geo.left() >= avail_now.left()
        assert geo.right() <= avail_now.right()
        # 展开几何原子落定，不得再叠一层位移动画。
        assert calls == []
    finally:
        window.deleteLater()


def test_paint_event_does_not_raise(qapp: QApplication) -> None:
    """折叠态与展开态下 ``grab()`` 触发 ``paintEvent`` 均不抛异常。"""
    window = FloatingPoolWindow()
    try:
        window.show()
        qapp.processEvents()

        collapsed_pixmap = window.grab()
        assert not collapsed_pixmap.isNull()

        window.set_expanded(True)
        qapp.processEvents()
        expanded_pixmap = window.grab()
        assert not expanded_pixmap.isNull()
    finally:
        window.close()
        window.deleteLater()


def test_deferred_state_attributes(qapp: QApplication) -> None:
    """``__init__`` 预声明延后 Todo 依赖的状态属性与主题连接。"""
    window = FloatingPoolWindow()
    try:
        assert window._drag_active is False
        assert window._pending_items is None
        assert window._host_window is None
        assert window._theme_conn is not None
    finally:
        window.deleteLater()


# ── 外部拖入链路（Todo 2） ───────────────────────────────────────


def _mime_for(paths: list[str]) -> QMimeData:
    """构造携带本地文件 URL 的 ``QMimeData``。

    Args:
        paths: 本地文件 / 目录路径列表。

    Returns:
        QMimeData: 已 ``setUrls([QUrl.fromLocalFile(...)])`` 的 MIME 数据。
    """
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return mime


def _drop_event(paths: list[str]) -> tuple[QDropEvent, QMimeData]:
    """构造一个存放于窗口 (10, 10) 处的左键复制拖放事件。

    ``QMimeData`` 一并返回：``QDropEvent`` 不持有其所有权，调用方须在
    ``dropEvent`` 期间保持该引用存活（否则 MIME 数据被 GC 回收）。

    Args:
        paths: 本地文件 / 目录路径列表。

    Returns:
        tuple: ``(事件对象, 其 MIME 数据)``。
    """
    mime = _mime_for(paths)
    event = QDropEvent(
        QPointF(10.0, 10.0),
        Qt.CopyAction,
        mime,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    return event, mime


def test_drop_valid_file_emits_signal_once(
    qapp: QApplication, tmp_path
) -> None:
    """拖入有效文件 → 信号发射一次，负载 path / is_dir 正确。"""
    window = FloatingPoolWindow()
    received: list[dict] = []
    window.add_file_requested.connect(received.append)
    try:
        target = tmp_path / "sample.txt"
        target.write_text("hello", encoding="utf-8")

        event, _mime = _drop_event([str(target)])
        window.dropEvent(event)

        assert len(received) == 1
        assert Path(received[0]["path"]) == target
        assert received[0]["is_dir"] is False
    finally:
        window.deleteLater()


def test_drop_valid_directory_reports_is_dir(
    qapp: QApplication, tmp_path
) -> None:
    """拖入有效目录 → ``is_dir`` 为 True。"""
    window = FloatingPoolWindow()
    received: list[dict] = []
    window.add_file_requested.connect(received.append)
    try:
        target = tmp_path / "subdir"
        target.mkdir()

        event, _mime = _drop_event([str(target)])
        window.dropEvent(event)

        assert len(received) == 1
        assert Path(received[0]["path"]) == target
        assert received[0]["is_dir"] is True
    finally:
        window.deleteLater()


def test_drop_duplicate_url_emits_once(
    qapp: QApplication, tmp_path
) -> None:
    """同一次 drop 内重复的同一路径只发射一次。"""
    window = FloatingPoolWindow()
    received: list[dict] = []
    window.add_file_requested.connect(received.append)
    try:
        target = tmp_path / "dup.txt"
        target.write_text("x", encoding="utf-8")

        event, _mime = _drop_event([str(target), str(target)])
        window.dropEvent(event)

        assert len(received) == 1
        assert Path(received[0]["path"]) == target
    finally:
        window.deleteLater()


def test_drop_nonexistent_path_emits_nothing(
    qapp: QApplication, tmp_path
) -> None:
    """不存在的路径被跳过，不发射信号。"""
    window = FloatingPoolWindow()
    received: list[dict] = []
    window.add_file_requested.connect(received.append)
    try:
        missing = tmp_path / "missing.txt"
        assert not missing.exists()

        event, _mime = _drop_event([str(missing)])
        window.dropEvent(event)

        assert received == []
    finally:
        window.deleteLater()


def test_drop_non_local_url_emits_nothing(
    qapp: QApplication,
) -> None:
    """``toLocalFile()`` 为空的 URL（如 http 虚拟项）被跳过，不发射信号。"""
    window = FloatingPoolWindow()
    received: list[dict] = []
    window.add_file_requested.connect(received.append)
    try:
        mime = QMimeData()
        mime.setUrls([QUrl("https://example.com/file.txt")])
        assert mime.urls()[0].toLocalFile() == ""

        event = QDropEvent(
            QPointF(10.0, 10.0),
            Qt.CopyAction,
            mime,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        window.dropEvent(event)

        assert received == []
    finally:
        window.deleteLater()


def test_drop_mixed_non_local_and_valid_emits_only_valid(
    qapp: QApplication, tmp_path
) -> None:
    """混合载荷：非本地 URL 被跳过，有效本地文件仍正常发射一次。"""
    window = FloatingPoolWindow()
    received: list[dict] = []
    window.add_file_requested.connect(received.append)
    try:
        target = tmp_path / "mixed.txt"
        target.write_text("x", encoding="utf-8")

        mime = QMimeData()
        mime.setUrls(
            [
                QUrl("https://example.com/remote.txt"),
                QUrl.fromLocalFile(str(target)),
            ]
        )
        event = QDropEvent(
            QPointF(10.0, 10.0),
            Qt.CopyAction,
            mime,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        window.dropEvent(event)

        assert len(received) == 1
        assert Path(received[0]["path"]) == target
    finally:
        window.deleteLater()


def test_drag_move_logged_once_per_drag(
    qapp: QApplication, tmp_path
) -> None:
    """``dragMoveEvent`` 每次拖拽只记录一次：标志在 dragEnter/dragLeave 复位。"""
    window = FloatingPoolWindow()
    try:
        target = tmp_path / "move.txt"
        target.write_text("x", encoding="utf-8")
        mime = _mime_for([str(target)])

        enter = QDragEnterEvent(
            QPoint(10, 10),
            Qt.CopyAction,
            mime,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        window.dragEnterEvent(enter)
        assert window._drag_move_logged is False

        move = QDragMoveEvent(
            QPoint(10, 20),
            Qt.CopyAction,
            mime,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        window.dragMoveEvent(move)
        assert window._drag_move_logged is True
        assert move.isAccepted()

        # 同一次拖拽内后续移动事件：不再重复记录，但持续接受
        window.dragMoveEvent(move)
        assert window._drag_move_logged is True

        window.dragLeaveEvent(QDragLeaveEvent())
        assert window._drag_move_logged is False
    finally:
        window.deleteLater()


def test_drag_enter_and_leave_toggle_highlight(
    qapp: QApplication, tmp_path
) -> None:
    """``dragEnterEvent`` 置 ``dragActive`` 属性，``dragLeaveEvent`` 清除。"""
    window = FloatingPoolWindow()
    try:
        target = tmp_path / "a.txt"
        target.write_text("x", encoding="utf-8")

        mime = _mime_for([str(target)])
        enter = QDragEnterEvent(
            QPoint(10, 10),
            Qt.CopyAction,
            mime,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        window.dragEnterEvent(enter)
        assert window.property("dragActive")

        leave = QDragLeaveEvent()
        window.dragLeaveEvent(leave)
        assert not window.property("dragActive")
    finally:
        window.deleteLater()


def test_drag_enter_without_urls_logs_formats(
    qapp: QApplication, monkeypatch
) -> None:
    """无 URL 载荷的 ``dragEnterEvent`` 也留无条件日志（含 hasUrls + formats）。

    回归：原先唯一 ``debug`` 位于 ``if hasUrls():`` 内，载荷不含 URL 时无日志，
    无法区分「未被调用」与「被调用但 hasUrls 为 False」。此用例钉死无条件日志。
    """
    window = FloatingPoolWindow()
    try:
        mock_debug = Mock()
        monkeypatch.setattr(
            "freeassetfilter.ui.floating_pool_window.debug", mock_debug
        )

        # PySide6 陷阱：QDragEnterEvent 不持有 QMimeData 所有权，须保持引用存活。
        mime = QMimeData()
        mime.setText("plain text, no urls")
        assert mime.hasUrls() is False

        enter = QDragEnterEvent(
            QPoint(10, 10),
            Qt.CopyAction,
            mime,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        window.dragEnterEvent(enter)

        assert mock_debug.called
        assert any(
            isinstance(arg, str) and "hasUrls" in arg and "formats" in arg
            for call in mock_debug.call_args_list
            for arg in call.args
        )
    finally:
        window.deleteLater()


def test_drop_collapsed_auto_expands(
    qapp: QApplication, tmp_path
) -> None:
    """折叠态拖入有效文件后自动展开，且信号正常发射。"""
    window = FloatingPoolWindow()
    received: list[dict] = []
    window.add_file_requested.connect(received.append)
    try:
        target = tmp_path / "auto.txt"
        target.write_text("x", encoding="utf-8")
        assert window.is_expanded() is False

        event, _mime = _drop_event([str(target)])
        window.dropEvent(event)

        assert len(received) == 1
        assert window.is_expanded() is True
        assert not window.property("dragActive")
    finally:
        window.deleteLater()


def test_drop_expanded_still_emits(
    qapp: QApplication, tmp_path
) -> None:
    """已展开态拖入仍发射信号，展开状态保持不变。"""
    window = FloatingPoolWindow()
    received: list[dict] = []
    window.add_file_requested.connect(received.append)
    try:
        window.set_expanded(True)
        target = tmp_path / "expanded.txt"
        target.write_text("x", encoding="utf-8")

        event, _mime = _drop_event([str(target)])
        window.dropEvent(event)

        assert len(received) == 1
        assert Path(received[0]["path"]) == target
        assert window.is_expanded() is True
    finally:
        window.deleteLater()


# ── 展开内容列表（Todo 3） ───────────────────────────────────────


def _item(
    path: str,
    name: str | None = None,
    size: int | None = 1024,
    is_dir: bool = False,
) -> dict:
    """构造条目字典。

    Args:
        path: 文件路径。
        name: 可选的 ``name`` 字段。
        size: 可选的 ``size`` 字段（``None`` 表示不设置）。
        is_dir: 是否为目录。

    Returns:
        dict: 文件信息字典。
    """
    info: dict = {
        "path": path,
        "is_dir": is_dir,
        "suffix": Path(path).suffix.lstrip("."),
    }
    if name is not None:
        info["name"] = name
    if size is not None:
        info["size"] = size
    return info


def _flush_debounce() -> None:
    """泵事件循环，等待 0ms 防抖定时器触发重建。"""
    QTest.qWait(5)


def test_set_items_renders_rows_and_count(
    qapp: QApplication, tmp_path
) -> None:
    """``set_items`` 防抖后渲染对应条目行、计数标签正确、空态隐藏。"""
    window = FloatingPoolWindow()
    try:
        files = []
        for name in ("a.txt", "b.txt", "c.txt"):
            target = tmp_path / name
            target.write_text("x", encoding="utf-8")
            files.append(_item(str(target), name=name))

        window.set_items(files)
        _flush_debounce()

        assert len(window._rows) == 3
        assert window._count_label.text() == "存储池 (3)"
        assert window._empty_hint.isHidden() is True
        assert Path(window._rows[0].path) == tmp_path / "a.txt"
        # 图标逻辑尺寸 48 与取图管线一致；QLabel 不缩放，须 1:1 容器
        assert window._rows[0]._icon_label.size() == QSize(48, 48)
    finally:
        window.deleteLater()


def test_set_items_empty_shows_hint(qapp: QApplication) -> None:
    """空列表 → 计数为 0、空态提示可见、无条目行。"""
    window = FloatingPoolWindow()
    try:
        window.set_items([])
        _flush_debounce()

        assert window._rows == []
        assert window._count_label.text() == "存储池 (0)"
        assert window._empty_hint.isHidden() is False
    finally:
        window.deleteLater()


def test_set_items_same_turn_merges_into_one_rebuild(
    qapp: QApplication, tmp_path
) -> None:
    """同轮两次 ``set_items`` 只触发一次重建，且行来自最后一次列表。"""
    window = FloatingPoolWindow()
    try:
        fires: list[int] = []
        window._debounce_timer.timeout.connect(lambda: fires.append(1))

        first = [_item(str(tmp_path / "a.txt"))]
        second = [_item(str(tmp_path / "b.txt")), _item(str(tmp_path / "c.txt"))]
        window.set_items(first)
        window.set_items(second)
        _flush_debounce()

        assert len(fires) == 1
        assert len(window._rows) == 2
        assert window._count_label.text() == "存储池 (2)"
        assert Path(window._rows[0].path) == tmp_path / "b.txt"
    finally:
        window.deleteLater()


def test_set_items_rebuilds_not_appends(
    qapp: QApplication, tmp_path
) -> None:
    """先后两次 ``set_items`` 为重建而非追加（行数等于最后一次列表长度）。"""
    window = FloatingPoolWindow()
    try:
        window.set_items([_item(str(tmp_path / "a.txt"))])
        _flush_debounce()
        assert len(window._rows) == 1

        window.set_items(
            [_item(str(tmp_path / "b.txt")), _item(str(tmp_path / "c.txt"))]
        )
        _flush_debounce()
        assert len(window._rows) == 2
    finally:
        window.deleteLater()


def test_set_items_overflow_enables_scrolling(
    qapp: QApplication, tmp_path
) -> None:
    """条目超出可视高度时滚动范围生效（``verticalScrollBar().maximum() > 0``）。"""
    window = FloatingPoolWindow()
    try:
        window.set_expanded(True)
        items = [_item(str(tmp_path / f"f{i}.txt")) for i in range(30)]
        window.set_items(items)
        window.show()
        _flush_debounce()
        qapp.processEvents()

        assert len(window._rows) == 30
        assert window._scroll_area.verticalScrollBar().maximum() > 0
    finally:
        window.close()
        window.deleteLater()


def test_set_items_invalid_item_skipped(qapp: QApplication) -> None:
    """空 ``path`` 的非法条目被跳过：不崩溃、计数 0、空态提示可见。"""
    window = FloatingPoolWindow()
    try:
        window.set_items([{"path": ""}])
        _flush_debounce()

        assert window._rows == []
        assert window._count_label.text() == "存储池 (0)"
        assert window._empty_hint.isHidden() is False
    finally:
        window.deleteLater()


def test_rebuild_list_skips_non_dict_entry(
    qapp: QApplication, tmp_path
) -> None:
    """``set_items`` 列表中的非字典条目被跳过，仅有效字典条目渲染。"""
    window = FloatingPoolWindow()
    try:
        valid = _item(str(tmp_path / "valid.txt"), name="valid.txt")
        window.set_items([valid, "not-a-dict", 123, None, {"no": "path"}])
        _flush_debounce()

        assert len(window._rows) == 1
        assert window._count_label.text() == "存储池 (1)"
        assert Path(window._rows[0].path) == tmp_path / "valid.txt"
    finally:
        window.deleteLater()


# ── 主题/强调色刷新（colors_updated 链路） ───────────────────────────────


def test_colors_updated_refreshes_row_icons(
    qapp: QApplication, tmp_path
) -> None:
    """强调色单独变化（colors_updated）后，窗口即时重建全部条目行图标。

    回归背景：行图标在构造时 ``setPixmap`` 一次，而强调色变化只发
    ``colors_updated``（不发 ``theme_changed``）；历史实现下图标一直
    显示旧配色，鼠标扫过等重绘也无法刷新。
    """
    window = FloatingPoolWindow()
    original: str = tm.accent.name()
    try:
        target = tmp_path / "icon_me.png"
        target.write_bytes(b"fake-png")
        window.set_items([_item(str(target), name="icon_me.png")])
        _flush_debounce()
        assert len(window._rows) == 1

        first = window._rows[0]._icon_label.pixmap()
        assert not first.isNull(), "行图标应渲染非空"

        probe: str = "#FF00AA" if original.lower() != "#ff00aa" else "#22CC99"
        assert tm.set_color("accent.primary", probe) is True
        qapp.processEvents()

        second = window._rows[0]._icon_label.pixmap()
        assert not second.isNull()
        assert second.cacheKey() != first.cacheKey(), (
            "强调色变化后浮窗条目行图标应即时重建（colors_updated 未连线？）"
        )
    finally:
        tm.set_color("accent.primary", original)
        window.deleteLater()


def test_collapse_button_uses_minimize_dash_icon(qapp: QApplication) -> None:
    """标题栏折叠按钮用最小化短横线（不是展开方向的 chevron）。"""
    window = FloatingPoolWindow()
    try:
        button = window._collapse_button
        assert button.icon_name() == "minus", (
            f"折叠按钮图标应为最小化短横线，实际为 {button.icon_name()!r}"
        )
        assert "chevron" not in button.icon_name()
    finally:
        window.deleteLater()


def test_collapse_button_collapses(qapp: QApplication) -> None:
    """展开态点击折叠按钮 → 回到折叠态。"""
    window = FloatingPoolWindow()
    try:
        window.set_expanded(True)
        assert window.is_expanded() is True

        window._collapse_button.click()
        assert window.is_expanded() is False
    finally:
        window.deleteLater()


# ── 折叠态点击展开 / 拖动仲裁（Todo 3） ───────────────────────────


def _mouse_event(
    kind: QEvent.Type,
    pos: QPoint,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
) -> QMouseEvent:
    """构造指定类型的鼠标事件。

    Args:
        kind: 事件类型（按下 / 移动 / 释放）。
        pos: 窗口本地坐标。
        button: 触发按钮。
        buttons: 事件发生时被按住的按钮集合。

    Returns:
        QMouseEvent: 已构造的鼠标事件。
    """
    return QMouseEvent(
        kind, QPointF(pos), QPointF(pos), button, buttons, Qt.NoModifier
    )


def test_collapsed_press_release_expands(qapp: QApplication) -> None:
    """折叠态按下 + 原地释放（未超阈值）→ 展开且不触发系统移动。"""
    window = FloatingPoolWindow()
    try:
        calls: list[int] = []
        window._start_system_move = lambda: calls.append(1)

        point = QPoint(70, 24)
        window.mousePressEvent(
            _mouse_event(QEvent.Type.MouseButtonPress, point, Qt.LeftButton, Qt.LeftButton)
        )
        window.mouseReleaseEvent(
            _mouse_event(QEvent.Type.MouseButtonRelease, point, Qt.LeftButton, Qt.NoButton)
        )

        assert window.is_expanded() is True
        assert calls == []
    finally:
        window.deleteLater()


def test_collapsed_drag_beyond_threshold_moves_not_expands(
    qapp: QApplication,
) -> None:
    """折叠态拖动超过阈值 → 触发系统移动且不展开，随后释放仍不展开。"""
    window = FloatingPoolWindow()
    try:
        calls: list[int] = []
        window._start_system_move = lambda: calls.append(1)

        start = QPoint(70, 24)
        far = QPoint(70 + QApplication.startDragDistance() + 5, 24)
        window.mousePressEvent(
            _mouse_event(QEvent.Type.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
        )
        window.mouseMoveEvent(
            _mouse_event(QEvent.Type.MouseMove, far, Qt.NoButton, Qt.LeftButton)
        )

        assert calls == [1]
        assert window.is_expanded() is False

        window.mouseReleaseEvent(
            _mouse_event(QEvent.Type.MouseButtonRelease, far, Qt.LeftButton, Qt.NoButton)
        )
        assert window.is_expanded() is False
    finally:
        window.deleteLater()


def test_collapsed_small_move_then_release_still_expands(
    qapp: QApplication,
) -> None:
    """折叠态微移（未超阈值）后释放 → 仍展开且不触发系统移动。"""
    window = FloatingPoolWindow()
    try:
        calls: list[int] = []
        window._start_system_move = lambda: calls.append(1)

        start = QPoint(70, 24)
        near = QPoint(71, 25)
        window.mousePressEvent(
            _mouse_event(QEvent.Type.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
        )
        window.mouseMoveEvent(
            _mouse_event(QEvent.Type.MouseMove, near, Qt.NoButton, Qt.LeftButton)
        )
        window.mouseReleaseEvent(
            _mouse_event(QEvent.Type.MouseButtonRelease, near, Qt.LeftButton, Qt.NoButton)
        )

        assert window.is_expanded() is True
        assert calls == []
    finally:
        window.deleteLater()


def test_expanded_titlebar_press_starts_move(qapp: QApplication) -> None:
    """展开态标题栏按下 → 立即触发系统移动（钉死 Todo 1 行为）。"""
    window = FloatingPoolWindow()
    try:
        calls: list[int] = []
        window._start_system_move = lambda: calls.append(1)

        window.set_expanded(True)
        window.mousePressEvent(
            _mouse_event(
                QEvent.Type.MouseButtonPress, QPoint(100, 10), Qt.LeftButton, Qt.LeftButton
            )
        )

        assert calls == [1]
    finally:
        window.deleteLater()


# ── 拖出复制手势（Todo 4） ───────────────────────────────────────

CUSTOM_DRAG_FORMAT = FLOATING_DRAG_MIME
"""str: 浮窗条目拖出的自定义 MIME 判别格式（与 Todo 5 主池 dropEvent 同串）。"""


def _render_row(window: FloatingPoolWindow, path: str) -> _PoolItemRow:
    """把单条目列表交给窗口渲染并返回首个条目行。

    Args:
        window: 目标浮窗。
        path: 条目文件路径。

    Returns:
        _PoolItemRow: 渲染后的首行（经防抖定时器落定）。
    """
    window.set_items([_item(path, name=Path(path).name)])
    _flush_debounce()
    return window._rows[0]


def _press_and_move(
    row: _PoolItemRow, start: QPoint, end: QPoint
) -> None:
    """向条目行派发「左键按下 + 左键移动」合成手势。

    Args:
        row: 事件目标条目行（真实事件派发路径）。
        start: 按下点（行本地坐标）。
        end: 移动终点（行本地坐标）。
    """
    row.mousePressEvent(
        _mouse_event(
            QEvent.Type.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton
        )
    )
    row.mouseMoveEvent(
        _mouse_event(
            QEvent.Type.MouseMove, end, Qt.NoButton, Qt.LeftButton
        )
    )


def test_on_drag_finished_external_drop_emits_path(
    qapp: QApplication,
) -> None:
    """非 Qt 落点（``window_at`` 返回 None）→ 发射移除信号且路径正确。"""
    window = FloatingPoolWindow()
    received: list[str] = []
    window.remove_file_requested.connect(received.append)
    try:
        window._drag_source_path = "C:/tmp/drag-source.txt"

        window._on_drag_finished(
            Qt.CopyAction,
            window_at=lambda _p: None,
            cursor_pos=lambda: QPoint(0, 0),
        )

        assert received == ["C:/tmp/drag-source.txt"]
    finally:
        window.deleteLater()


def test_on_drag_finished_missing_source_path_does_not_emit(
    qapp: QApplication,
) -> None:
    """``_drag_source_path`` 为 None（无待决拖出）→ 即便落点外部也不发射。"""
    window = FloatingPoolWindow()
    received: list[str] = []
    window.remove_file_requested.connect(received.append)
    try:
        assert window._drag_source_path is None

        window._on_drag_finished(
            Qt.CopyAction,
            window_at=lambda _p: None,
            cursor_pos=lambda: QPoint(0, 0),
        )

        assert received == []
    finally:
        window.deleteLater()


def test_on_drag_finished_ignore_action_does_not_emit(
    qapp: QApplication,
) -> None:
    """``Qt.IgnoreAction``（目标拒绝）→ 不发射移除信号。"""
    window = FloatingPoolWindow()
    received: list[str] = []
    window.remove_file_requested.connect(received.append)
    try:
        window._drag_source_path = "C:/tmp/drag-source.txt"

        window._on_drag_finished(
            Qt.IgnoreAction,
            window_at=lambda _p: None,
            cursor_pos=lambda: QPoint(0, 0),
        )

        assert received == []
    finally:
        window.deleteLater()


def test_on_drag_finished_self_window_does_not_emit(
    qapp: QApplication,
) -> None:
    """落点为浮窗自身或其子控件 → 视为取消，不发射。"""
    window = FloatingPoolWindow()
    received: list[str] = []
    window.remove_file_requested.connect(received.append)
    child = QWidget(window._content)
    try:
        window._drag_source_path = "C:/tmp/drag-source.txt"

        window._on_drag_finished(
            Qt.CopyAction,
            window_at=lambda _p: window,
            cursor_pos=lambda: QPoint(0, 0),
        )
        window._on_drag_finished(
            Qt.CopyAction,
            window_at=lambda _p: child,
            cursor_pos=lambda: QPoint(0, 0),
        )

        assert received == []
    finally:
        window.deleteLater()


def test_on_drag_finished_host_window_does_not_emit(
    qapp: QApplication,
) -> None:
    """落点为主窗口（``_host_window``）子控件 → 视为取消，不发射。"""
    window = FloatingPoolWindow()
    received: list[str] = []
    window.remove_file_requested.connect(received.append)
    host = QWidget()
    child = QWidget(host)
    try:
        window._host_window = host
        window._drag_source_path = "C:/tmp/drag-source.txt"

        window._on_drag_finished(
            Qt.CopyAction,
            window_at=lambda _p: child,
            cursor_pos=lambda: QPoint(0, 0),
        )

        assert received == []
    finally:
        window.deleteLater()
        host.deleteLater()


def test_on_drag_finished_owned_dialog_does_not_emit(
    qapp: QApplication,
) -> None:
    """落点为主窗口 owned 对话框（``QDialog``）子控件 → 视为取消，不发射。"""
    window = FloatingPoolWindow()
    received: list[str] = []
    window.remove_file_requested.connect(received.append)
    host = QWidget()
    dialog = QDialog(host)
    child = QWidget(dialog)
    try:
        window._host_window = host
        window._drag_source_path = "C:/tmp/drag-source.txt"

        window._on_drag_finished(
            Qt.CopyAction,
            window_at=lambda _p: child,
            cursor_pos=lambda: QPoint(0, 0),
        )

        assert received == []
    finally:
        window.deleteLater()
        host.deleteLater()


def test_on_drag_finished_unrelated_widget_emits(
    qapp: QApplication,
) -> None:
    """落点为无关顶层控件 → 发射移除信号。"""
    window = FloatingPoolWindow()
    received: list[str] = []
    window.remove_file_requested.connect(received.append)
    foreign = QWidget()
    try:
        window._drag_source_path = "C:/tmp/drag-source.txt"

        window._on_drag_finished(
            Qt.CopyAction,
            window_at=lambda _p: foreign,
            cursor_pos=lambda: QPoint(0, 0),
        )

        assert received == ["C:/tmp/drag-source.txt"]
    finally:
        window.deleteLater()
        foreign.deleteLater()


def test_row_drag_mime_carries_url_and_custom_format(
    qapp: QApplication, tmp_path
) -> None:
    """条目行超阈值拖出 → QDrag 的 MIME 含文件 URL 与自定义判别格式。"""
    window = FloatingPoolWindow()
    try:
        target = tmp_path / "mime.txt"
        target.write_text("x", encoding="utf-8")
        row = _render_row(window, str(target))

        captured: dict = {}

        def _fake_run_drag(drag) -> Qt.DropAction:
            captured["mime"] = drag.mimeData()
            return Qt.IgnoreAction

        window._run_drag = _fake_run_drag

        start = QPoint(10, 10)
        far = QPoint(10 + QApplication.startDragDistance() + 10, 10)
        _press_and_move(row, start, far)

        assert "mime" in captured
        mime = captured["mime"]
        assert mime.hasUrls() is True
        assert Path(mime.urls()[0].toLocalFile()) == target
        assert mime.hasFormat(CUSTOM_DRAG_FORMAT) is True
        assert mime.data(CUSTOM_DRAG_FORMAT).data() == b"1"
    finally:
        window.deleteLater()


def test_row_move_below_threshold_does_not_start_drag(
    qapp: QApplication, tmp_path
) -> None:
    """合成移动未超 ``startDragDistance()`` → 不启动拖拽。"""
    window = FloatingPoolWindow()
    try:
        target = tmp_path / "near.txt"
        target.write_text("x", encoding="utf-8")
        row = _render_row(window, str(target))

        calls: list[int] = []

        def _fake_run_drag(drag) -> Qt.DropAction:
            calls.append(1)
            return Qt.IgnoreAction

        window._run_drag = _fake_run_drag
        window._on_drag_finished = lambda *a, **k: None

        start = QPoint(10, 10)
        near = QPoint(11, 11)  # 曼哈顿距离 2 < 默认 10
        _press_and_move(row, start, near)

        assert calls == []
    finally:
        window.deleteLater()


def test_row_move_beyond_threshold_starts_drag_and_clears_active(
    qapp: QApplication, tmp_path
) -> None:
    """超阈值拖出 → ``_run_drag`` 恰一次；期间 ``_drag_active`` True，finally 清 False。"""
    window = FloatingPoolWindow()
    try:
        target = tmp_path / "far.txt"
        target.write_text("x", encoding="utf-8")
        row = _render_row(window, str(target))

        observed: dict = {}
        calls: list[int] = []

        def _fake_run_drag(drag) -> Qt.DropAction:
            calls.append(1)
            observed["during"] = window._drag_active
            return Qt.IgnoreAction

        window._run_drag = _fake_run_drag
        window._on_drag_finished = lambda *a, **k: None

        start = QPoint(10, 10)
        far = QPoint(10 + QApplication.startDragDistance() + 10, 10)
        _press_and_move(row, start, far)

        assert calls == [1]
        assert observed["during"] is True
        assert window._drag_active is False
    finally:
        window.deleteLater()


def test_rebuild_list_skips_when_drag_active(
    qapp: QApplication, monkeypatch
) -> None:
    """``_drag_active`` 为 True 时防抖回调不自旋（不调 ``start``）。"""
    window = FloatingPoolWindow()
    try:
        starts: list[tuple] = []
        monkeypatch.setattr(
            window._debounce_timer,
            "start",
            lambda *args: starts.append(args),
        )
        window._drag_active = True
        window._pending_items = [_item("C:/tmp/pending.txt")]

        window._rebuild_list()

        assert starts == []
        assert window._pending_items is not None
    finally:
        window.deleteLater()


def test_row_drag_end_restarts_debounce_when_pending(
    qapp: QApplication, tmp_path, monkeypatch
) -> None:
    """拖拽结束且 ``_pending_items`` 非空 → finally ``start(0)`` 恰一次。"""
    window = FloatingPoolWindow()
    try:
        target = tmp_path / "pending.txt"
        target.write_text("x", encoding="utf-8")
        row = _render_row(window, str(target))

        starts: list[tuple] = []
        monkeypatch.setattr(
            window._debounce_timer,
            "start",
            lambda *args: starts.append(args),
        )
        window._pending_items = [_item(str(target))]
        window._run_drag = lambda drag: Qt.IgnoreAction
        window._on_drag_finished = lambda *a, **k: None

        far = QPoint(10 + QApplication.startDragDistance() + 10, 10)
        _press_and_move(row, QPoint(10, 10), far)

        assert starts == [(0,)]
        assert window._drag_active is False
    finally:
        window.deleteLater()


def test_row_drag_end_without_pending_does_not_restart(
    qapp: QApplication, tmp_path, monkeypatch
) -> None:
    """拖拽结束但 ``_pending_items`` 为 None → finally 不调 ``start``。"""
    window = FloatingPoolWindow()
    try:
        target = tmp_path / "nopending.txt"
        target.write_text("x", encoding="utf-8")
        row = _render_row(window, str(target))

        starts: list[tuple] = []
        monkeypatch.setattr(
            window._debounce_timer,
            "start",
            lambda *args: starts.append(args),
        )
        assert window._pending_items is None
        window._run_drag = lambda drag: Qt.IgnoreAction
        window._on_drag_finished = lambda *a, **k: None

        far = QPoint(10 + QApplication.startDragDistance() + 10, 10)
        _press_and_move(row, QPoint(10, 10), far)

        assert starts == []
        assert window._drag_active is False
    finally:
        window.deleteLater()


# ── 贴边吸附 + 松手夹回 + 惯性位移动画（Todo 8） ─────────────────


def _wait_move_animation(
    window: FloatingPoolWindow, timeout_ms: int = 2000
) -> None:
    """泵事件循环等待位移动画结束（``is_snapping()`` 归 False）。

    Args:
        window: 目标浮窗。
        timeout_ms: 防御性最长等待毫秒数（动画 220ms，正常远小于）。
    """
    waited = 0
    while window.is_snapping() and waited < timeout_ms:
        QTest.qWait(10)
        waited += 10
    assert window.is_snapping() is False
    QTest.qWait(10)


def _settle_at(
    window: FloatingPoolWindow,
    x: int,
    y: int,
    *,
    snap: bool | None = None,
) -> QPoint:
    """把窗口移到 ``(x, y)`` → 直接触发 ``_settle_and_snap`` → 等动画落定。

    Args:
        window: 目标浮窗。
        x: 目标左上角 x（全局坐标，可为屏外）。
        y: 目标左上角 y（全局坐标，可为屏外）。
        snap: 非 None 时先 ``set_snap_enabled(snap)`` 再结算。

    Returns:
        QPoint: 动画结束后的最终位置。
    """
    if snap is not None:
        window.set_snap_enabled(snap)
    window.move(x, y)
    window._settle_and_snap()
    _wait_move_animation(window)
    return window.pos()


def test_snap_enabled_api_default_and_toggle(qapp: QApplication) -> None:
    """默认启用吸附；``set_snap_enabled`` 可切换；初始 ``is_snapping`` 为 False。"""
    window = FloatingPoolWindow()
    try:
        assert window.is_snap_enabled() is True
        assert window.is_snapping() is False

        window.set_snap_enabled(False)
        assert window.is_snap_enabled() is False

        window.set_snap_enabled(True)
        assert window.is_snap_enabled() is True
    finally:
        window.deleteLater()


def test_set_expanded_applies_geometry_atomically(
    qapp: QApplication,
) -> None:
    """``set_expanded`` 尺寸与位置同帧落定（右缘锚定，不产生位移动画）。

    回归背景：卡片锚定在窗口右缘；若先 ``setFixedSize``（右缘外扩一个面板
    宽度）再位移动画滑回，面板会被推到屏幕外再滑入。展开改为一次
    ``setGeometry``，形变由 ``morphProgress`` 承担。
    """
    window = FloatingPoolWindow()
    try:
        right_edge = window.x() + window.width()

        window.set_expanded(True)

        assert window.is_snapping() is False
        assert window.size() == _expected_expanded_size()
        assert window.x() + window.width() == right_edge
    finally:
        window.deleteLater()


def test_snap_left_inside_threshold(qapp: QApplication) -> None:
    """左边距 ≤ ``SNAP_THRESHOLD`` → x 吸到 ``avail.left()+INITIAL_INSET``。"""
    window = FloatingPoolWindow()
    try:
        _screen, avail = _screen_and_available(window)
        assert avail is not None
        start_x = avail.left() + SNAP_THRESHOLD - 4

        final = _settle_at(window, start_x, 300)

        assert final.x() == avail.left() + INITIAL_INSET
        assert final.y() == 300
    finally:
        window.deleteLater()


def test_snap_left_outside_threshold(qapp: QApplication) -> None:
    """左边距 > ``SNAP_THRESHOLD`` → 不吸附，保持原位。"""
    window = FloatingPoolWindow()
    try:
        _screen, avail = _screen_and_available(window)
        assert avail is not None
        start_x = avail.left() + SNAP_THRESHOLD + 1

        final = _settle_at(window, start_x, 300)

        assert final.x() == start_x
        assert final.y() == 300
    finally:
        window.deleteLater()


def test_snap_right_inside_threshold(qapp: QApplication) -> None:
    """右边距 ≤ ``SNAP_THRESHOLD`` → 右缘吸到 ``avail.right()-INITIAL_INSET``。"""
    window = FloatingPoolWindow()
    try:
        _screen, avail = _screen_and_available(window)
        assert avail is not None
        margin = SNAP_THRESHOLD - 4
        start_x = avail.right() - margin - window.width() + 1

        final = _settle_at(window, start_x, 300)

        assert final.x() == avail.right() - INITIAL_INSET - window.width() + 1
        assert final.y() == 300
    finally:
        window.deleteLater()


def test_snap_right_outside_threshold(qapp: QApplication) -> None:
    """右边距 > ``SNAP_THRESHOLD`` → 不吸附，保持原位。"""
    window = FloatingPoolWindow()
    try:
        _screen, avail = _screen_and_available(window)
        assert avail is not None
        margin = SNAP_THRESHOLD + 1
        start_x = avail.right() - margin - window.width() + 1

        final = _settle_at(window, start_x, 300)

        assert final.x() == start_x
    finally:
        window.deleteLater()


def test_snap_top_inside_threshold(qapp: QApplication) -> None:
    """上边距 ≤ ``SNAP_THRESHOLD`` → y 吸到 ``avail.top()+INITIAL_INSET``。"""
    window = FloatingPoolWindow()
    try:
        _screen, avail = _screen_and_available(window)
        assert avail is not None
        start_y = avail.top() + SNAP_THRESHOLD - 4

        final = _settle_at(window, 300, start_y)

        assert final.y() == avail.top() + INITIAL_INSET
        assert final.x() == 300
    finally:
        window.deleteLater()


def test_snap_top_outside_threshold(qapp: QApplication) -> None:
    """上边距 > ``SNAP_THRESHOLD`` → 不吸附，保持原位。"""
    window = FloatingPoolWindow()
    try:
        _screen, avail = _screen_and_available(window)
        assert avail is not None
        start_y = avail.top() + SNAP_THRESHOLD + 1

        final = _settle_at(window, 300, start_y)

        assert final.y() == start_y
    finally:
        window.deleteLater()


def test_snap_bottom_inside_threshold(qapp: QApplication) -> None:
    """下边距 ≤ ``SNAP_THRESHOLD`` → 下边吸到 ``avail.bottom()-INITIAL_INSET``。"""
    window = FloatingPoolWindow()
    try:
        _screen, avail = _screen_and_available(window)
        assert avail is not None
        margin = SNAP_THRESHOLD - 4
        start_y = avail.bottom() - margin - window.height() + 1

        final = _settle_at(window, 300, start_y)

        assert final.y() == avail.bottom() - INITIAL_INSET - window.height() + 1
        assert final.x() == 300
    finally:
        window.deleteLater()


def test_snap_bottom_outside_threshold(qapp: QApplication) -> None:
    """下边距 > ``SNAP_THRESHOLD`` → 不吸附，保持原位。"""
    window = FloatingPoolWindow()
    try:
        _screen, avail = _screen_and_available(window)
        assert avail is not None
        margin = SNAP_THRESHOLD + 1
        start_y = avail.bottom() - margin - window.height() + 1

        final = _settle_at(window, 300, start_y)

        assert final.y() == start_y
    finally:
        window.deleteLater()


def test_clamp_back_left_when_offscreen(qapp: QApplication) -> None:
    """窗口越出左缘 → 完整夹回（吸附关闭时停在 ``avail.left()``）。"""
    window = FloatingPoolWindow()
    try:
        _screen, avail = _screen_and_available(window)
        assert avail is not None

        final = _settle_at(window, avail.left() - 50, 300, snap=False)

        assert final.x() == avail.left()
        assert final.y() == 300
    finally:
        window.deleteLater()


def test_clamp_back_right_when_offscreen(qapp: QApplication) -> None:
    """窗口越出右缘 → 完整夹回可用区右界。"""
    window = FloatingPoolWindow()
    try:
        _screen, avail = _screen_and_available(window)
        assert avail is not None

        final = _settle_at(window, avail.right() + 100, 300, snap=False)

        assert final.x() == avail.right() - window.width() + 1
    finally:
        window.deleteLater()


def test_clamp_back_top_when_offscreen(qapp: QApplication) -> None:
    """窗口越出上缘 → 完整夹回可用区上界。"""
    window = FloatingPoolWindow()
    try:
        _screen, avail = _screen_and_available(window)
        assert avail is not None

        final = _settle_at(window, 300, avail.top() - 50, snap=False)

        assert final.y() == avail.top()
    finally:
        window.deleteLater()


def test_clamp_back_bottom_when_offscreen(qapp: QApplication) -> None:
    """窗口越出下缘 → 完整夹回可用区下界。"""
    window = FloatingPoolWindow()
    try:
        _screen, avail = _screen_and_available(window)
        assert avail is not None

        final = _settle_at(window, 300, avail.bottom() + 100, snap=False)

        assert final.y() == avail.bottom() - window.height() + 1
    finally:
        window.deleteLater()


def test_clamp_back_bottom_right_corner_when_offscreen(
    qapp: QApplication,
) -> None:
    """窗口越出右下角 → 完整夹回右下角可用界。"""
    window = FloatingPoolWindow()
    try:
        _screen, avail = _screen_and_available(window)
        assert avail is not None

        final = _settle_at(
            window, avail.right() + 100, avail.bottom() + 100, snap=False
        )

        assert final.x() == avail.right() - window.width() + 1
        assert final.y() == avail.bottom() - window.height() + 1
    finally:
        window.deleteLater()


def test_clamp_back_then_snap_when_enabled(qapp: QApplication) -> None:
    """吸附开启时：越界先夹回边缘，再按阈值吸附进 ``INITIAL_INSET``。"""
    window = FloatingPoolWindow()
    try:
        _screen, avail = _screen_and_available(window)
        assert avail is not None

        final = _settle_at(window, avail.left() - 50, 300, snap=True)

        assert final.x() == avail.left() + INITIAL_INSET
    finally:
        window.deleteLater()


def test_snap_disabled_clamps_but_does_not_snap(qapp: QApplication) -> None:
    """``set_snap_enabled(False)``：不吸附，但仍把越界窗口夹回屏内。"""
    window = FloatingPoolWindow()
    try:
        _screen, avail = _screen_and_available(window)
        assert avail is not None

        # 夹回后左边距为 0（本会触发吸附），关闭吸附应停在 0 而非 16
        final = _settle_at(window, avail.left() - 50, 300, snap=False)

        assert final.x() == avail.left()
    finally:
        window.deleteLater()


def test_settle_and_snap_animates_with_inertia(qapp: QApplication) -> None:
    """结算位移经 ``_animate_move``：探测 ``is_snapping`` + 缓动/时长契约。"""
    window = FloatingPoolWindow()
    try:
        _screen, avail = _screen_and_available(window)
        assert avail is not None

        window.move(avail.left() - 50, 300)
        window._settle_and_snap()

        assert window.is_snapping() is True
        anim = window._move_anim
        assert anim is not None
        assert anim.duration() == SNAP_DURATION_MS
        assert anim.easingCurve().type() == QEasingCurve.InOutCubic

        _wait_move_animation(window)
        assert window.is_snapping() is False
        assert window.x() == avail.left() + INITIAL_INSET
    finally:
        window.deleteLater()


def test_settle_and_snap_noop_when_already_settled(
    qapp: QApplication,
) -> None:
    """目标位置与当前位置一致时不产生动画（``is_snapping`` 为 False）。"""
    window = FloatingPoolWindow()
    try:
        window.move(300, 300)
        window._settle_and_snap()

        assert window.is_snapping() is False
        assert window.pos() == QPoint(300, 300)
    finally:
        window.deleteLater()


def test_settle_and_snap_skips_while_internal_moving(
    qapp: QApplication,
) -> None:
    """``_internal_moving`` 为 True 时结算早退（不抢程序化移动的位置）。"""
    window = FloatingPoolWindow()
    try:
        window.move(-50, 300)
        window._internal_moving = True

        window._settle_and_snap()

        assert window.is_snapping() is False
        assert window.pos() == QPoint(-50, 300)
    finally:
        window.deleteLater()


def test_start_system_move_stops_inflight_animation(
    qapp: QApplication,
) -> None:
    """``_start_system_move`` 先停在途动画，把位置控制权交还系统。"""
    window = FloatingPoolWindow()
    try:
        window.move(-50, 300)
        window._settle_and_snap()
        assert window.is_snapping() is True

        window._start_system_move()

        assert window.is_snapping() is False
    finally:
        window.deleteLater()


def test_move_event_arms_settle_timer(qapp: QApplication) -> None:
    """真实移动事件（窗口可见）→ 重启静默定时器（松手启发式）。"""
    window = FloatingPoolWindow()
    try:
        window.show()
        qapp.processEvents()
        window._settle_timer.stop()

        window.move(200, 200)
        qapp.processEvents()

        assert window._settle_timer.isActive() is True
    finally:
        window.close()
        window.deleteLater()


def test_move_event_not_armed_while_internal_moving(
    qapp: QApplication,
) -> None:
    """程序化移动（``_internal_moving``）期间移动事件不重启静默定时器。"""
    window = FloatingPoolWindow()
    try:
        window.show()
        qapp.processEvents()
        window._settle_timer.stop()
        window._internal_moving = True

        window.move(210, 210)
        qapp.processEvents()

        assert window._settle_timer.isActive() is False
    finally:
        window.close()
        window.deleteLater()


def test_move_event_settle_timer_triggers_snap(qapp: QApplication) -> None:
    """移动后静默 ``SETTLE_DELAY_MS`` → 自动吸附到左上角 ``INITIAL_INSET``。"""
    window = FloatingPoolWindow()
    try:
        window.show()
        qapp.processEvents()
        window.move(5, 5)

        QTest.qWait(SETTLE_DELAY_MS + 120)
        _wait_move_animation(window)

        assert window.pos() == QPoint(INITIAL_INSET, INITIAL_INSET)
    finally:
        window.close()
        window.deleteLater()


# ── 视觉形态与动效（圆形入口 / 胶囊拉伸 / 形变 / 回弹） ─────────────────


def _wait_until(predicate, timeout_ms: int = 2500) -> bool:
    """泵事件循环等待条件成立。

    Args:
        predicate: 无参谓词（返回 True 即视为成立）。
        timeout_ms: 最长等待毫秒数。

    Returns:
        bool: 条件是否在超时前成立。
    """
    waited = 0
    while waited < timeout_ms:
        if predicate():
            return True
        QTest.qWait(10)
        waited += 10
    return bool(predicate())


def test_collapsed_card_is_perfect_circle(qapp: QApplication) -> None:
    """折叠态卡片为正方形，且圆角半径等于边长一半（完美圆形）。"""
    window = FloatingPoolWindow()
    try:
        card = window._card_rect()
        assert card.width() == pytest.approx(card.height())
        assert window._card_radius(card) == pytest.approx(card.height() / 2.0)
        # 卡片留白内缩：完整落入窗口，留给外发光 / 回弹缩放
        assert card.left() >= 1.0
        assert card.right() <= window.width() - 1.0
    finally:
        window.deleteLater()


def test_drag_enter_stretches_to_pill(qapp: QApplication, tmp_path) -> None:
    """折叠态拖入 → 横向拉伸为胶囊（圆角仍为高度一半）；离开后收回圆形。"""
    window = FloatingPoolWindow()
    try:
        window.show()
        qapp.processEvents()

        target = tmp_path / "pill.txt"
        target.write_text("x", encoding="utf-8")
        mime = _mime_for([str(target)])
        window.dragEnterEvent(
            QDragEnterEvent(
                QPoint(10, 10),
                Qt.CopyAction,
                mime,
                Qt.LeftButton,
                Qt.NoModifier,
            )
        )
        assert window.property("dragActive") is True
        assert _wait_until(lambda: window.size() == DRAG_HOVER_SIZE), (
            "拖入后窗口未拉伸为胶囊"
        )

        card = window._card_rect()
        assert card.height() == pytest.approx(
            DRAG_HOVER_SIZE.height() - 2 * _CARD_MARGIN
        )
        assert window._card_radius(card) == pytest.approx(card.height() / 2.0)

        window.dragLeaveEvent(QDragLeaveEvent())
        assert window.property("dragActive") is False
        assert _wait_until(lambda: window.size() == COLLAPSED_SIZE), (
            "拖拽离开后窗口未收回圆形"
        )
    finally:
        window.close()
        window.deleteLater()


def test_drag_enter_does_not_stretch_expanded_window(
    qapp: QApplication, tmp_path
) -> None:
    """已展开态拖入：不横向拉伸（面板本身就是完整接收区），仅点亮高亮。"""
    window = FloatingPoolWindow()
    try:
        window.show()
        window.set_expanded(True)
        expanded_size = window.size()

        target = tmp_path / "expanded_pill.txt"
        target.write_text("x", encoding="utf-8")
        mime = _mime_for([str(target)])
        window.dragEnterEvent(
            QDragEnterEvent(
                QPoint(10, 10),
                Qt.CopyAction,
                mime,
                Qt.LeftButton,
                Qt.NoModifier,
            )
        )
        QTest.qWait(60)

        assert window.property("dragActive") is True
        assert window.size() == expanded_size
        assert window._drag_progress == 0.0
    finally:
        window.close()
        window.deleteLater()


def test_expand_runs_morph_and_clears_content_mask(
    qapp: QApplication,
) -> None:
    """可见窗口展开：形变动画在途 → 完成后内容蒙版清空（逐步揭示复用）。"""
    window = FloatingPoolWindow()
    try:
        window.show()
        qapp.processEvents()

        window.set_expanded(True)
        assert window._morph_anim is not None, "展开未启动形变动画"
        assert not window._content.mask().isEmpty(), (
            "形变期间内容应被裁剪到卡片区域"
        )

        assert _wait_until(lambda: window._morph >= 1.0)
        assert window._content.mask().isEmpty(), (
            "形变完成后应清空内容蒙版（避免圆角边缘锯齿裁切）"
        )
    finally:
        window.close()
        window.deleteLater()


def test_expand_never_overshoots_terminal_values(
    qapp: QApplication,
) -> None:
    """展开形变缓动到终值即结束：形变 / 缩放均不得越过终值。

    回归背景：展开完成后曾串联 ``1.0 → 0.982 → 1.008 → 1.0`` 的落定回弹，
    其中 ``1.008`` 越过终态尺寸，实测表现为面板展开到末期又轻微鼓一下。
    """
    window = FloatingPoolWindow()
    try:
        window.show()
        qapp.processEvents()

        window.set_expanded(True)
        peak_morph = 0.0
        peak_pulse = 1.0
        # 采样窗覆盖形变（320ms）之后的收尾区间，才能抓到串联的落定回弹。
        for _ in range(90):
            peak_morph = max(peak_morph, window._morph)
            peak_pulse = max(peak_pulse, window._pulse)
            QTest.qWait(10)

        assert peak_morph <= 1.0 + 1e-6, f"形变进度越过终值：{peak_morph}"
        assert peak_pulse <= 1.0 + 1e-6, f"缩放越过终值（弹性溢出）：{peak_pulse}"
        assert window._morph == 1.0
        assert window._pulse == 1.0
        assert window._pulse_anim is None, "展开结束后不应再起缩放回弹"
    finally:
        window.close()
        window.deleteLater()


def test_expanded_drop_feedback_never_overshoots(
    qapp: QApplication, tmp_path: Path
) -> None:
    """已展开时拖入文件：下压确认仍在，但缩放全程不超过终值。"""
    window = FloatingPoolWindow()
    received: list[dict] = []
    window.add_file_requested.connect(received.append)
    try:
        window.show()
        qapp.processEvents()
        window.set_expanded(True)
        assert _wait_until(lambda: window._morph >= 1.0)

        target = tmp_path / "expanded_press.txt"
        target.write_text("x", encoding="utf-8")
        event, _mime = _drop_event([str(target)])
        window.dropEvent(event)

        assert len(received) == 1
        assert window._pulse_anim is not None, "展开态接收缺少确认反馈"

        peak = 1.0
        for _ in range(40):
            peak = max(peak, window._pulse)
            QTest.qWait(10)
        assert peak <= 1.0 + 1e-6, f"确认反馈缩放越过终值：{peak}"
        assert window._pulse == 1.0
    finally:
        window.close()
        window.deleteLater()


def test_collapse_defers_geometry_until_animation_finishes(
    qapp: QApplication,
) -> None:
    """可见窗口收起：状态立即为折叠，几何滞后到收拢动画结束才落定。"""
    window = FloatingPoolWindow()
    try:
        window.show()
        window.set_expanded(True)
        assert _wait_until(lambda: window._morph >= 1.0)
        right_edge = window.x() + window.width()

        window.set_expanded(False)

        assert window.is_expanded() is False
        assert window._collapse_pending is True
        assert window.size() != COLLAPSED_SIZE, "收拢动画期间几何不应立即跳变"

        assert _wait_until(lambda: window.size() == COLLAPSED_SIZE), (
            "收拢动画结束后窗口未缩回折叠尺寸"
        )
        assert window._morph == 0.0
        assert window._visual_expanded is False
        assert window._collapse_pending is False
        # 右缘锚定：圆形落在收拢动画终点，几何跳变不可见
        assert window.x() + window.width() == right_edge
    finally:
        window.close()
        window.deleteLater()


def test_collapse_with_hidden_window_is_immediate(
    qapp: QApplication,
) -> None:
    """不可见窗口收起：无动画可看，尺寸同步落定（既有语义）。"""
    window = FloatingPoolWindow()
    try:
        window.set_expanded(True)
        window.set_expanded(False)

        assert window.is_expanded() is False
        assert window._collapse_pending is False
        assert window.size() == COLLAPSED_SIZE
        assert window._morph == 0.0
    finally:
        window.deleteLater()


def test_drop_success_starts_bounce(
    qapp: QApplication, tmp_path
) -> None:
    """折叠态成功接收：回弹动画起跑且窗口立刻进入展开态（状态同步）。"""
    window = FloatingPoolWindow()
    received: list[dict] = []
    window.add_file_requested.connect(received.append)
    try:
        window.show()
        qapp.processEvents()

        target = tmp_path / "bounce.txt"
        target.write_text("x", encoding="utf-8")
        event, _mime = _drop_event([str(target)])
        window.dropEvent(event)

        assert len(received) == 1
        assert window.is_expanded() is True
        assert window._pulse_anim is not None, "成功接收未播放回弹动画"
    finally:
        window.close()
        window.deleteLater()


def test_count_badge_tracks_items(qapp: QApplication, tmp_path) -> None:
    """折叠态计数徽标跟随条目数（``_count`` 与列表重建同步）。"""
    window = FloatingPoolWindow()
    try:
        assert window._count == 0
        window.set_items(
            [
                _item(str(tmp_path / "a.txt")),
                _item(str(tmp_path / "b.txt")),
            ]
        )
        _flush_debounce()

        assert window._count == 2
    finally:
        window.deleteLater()


# ── 展开列表滚动条（StyledScrollBar 可点击 / 可拖动） ─────────────────


def _prepare_scrolled_window(
    window: FloatingPoolWindow, qapp: QApplication, count: int, tmp_path
) -> StyledScrollBar:
    """展开窗口并灌入 *count* 个条目，返回竖向滚动条。

    Args:
        window: 目标浮窗。
        qapp: 应用实例（泵事件循环用）。
        count: 条目数量。
        tmp_path: 临时目录。

    Returns:
        StyledScrollBar: 已布局完成的竖向滚动条。
    """
    window.show()
    window.set_expanded(True)
    window.set_items(
        [_item(str(tmp_path / f"row_{i}.txt"), name=f"row_{i}.txt") for i in range(count)]
    )
    _flush_debounce()
    qapp.processEvents()
    QTest.qWait(30)
    return window._scroll_area.verticalScrollBar()


def test_scroll_area_uses_visible_styled_scrollbar(
    qapp: QApplication,
) -> None:
    """竖向滚动条由 ``StyledScrollBar`` 接管且策略为按需显示（非原生条）。"""
    window = FloatingPoolWindow()
    try:
        area = window._scroll_area
        assert isinstance(area, StyledScrollArea)
        assert area.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
        assert isinstance(area.verticalScrollBar(), StyledScrollBar)
        # 透明 QSS 只作用于滚动区自身，不得泄漏到滚动条（否则样式接管原生绘制）
        assert area.verticalScrollBar().styleSheet() == ""
    finally:
        window.deleteLater()


def test_scrollbar_visible_only_when_content_overflows(
    qapp: QApplication, tmp_path
) -> None:
    """条目不足时滚动条隐藏；溢出后可见并占位（不再被 AlwaysOff 藏掉）。"""
    window = FloatingPoolWindow()
    try:
        bar = _prepare_scrolled_window(window, qapp, 3, tmp_path)
        assert bar.maximum() == 0
        assert bar.isVisible() is False
        wide_viewport = window._scroll_area.viewport().width()

        window.set_items(
            [
                _item(str(tmp_path / f"more_{i}.txt"), name=f"more_{i}.txt")
                for i in range(24)
            ]
        )
        _flush_debounce()
        qapp.processEvents()
        QTest.qWait(30)

        assert bar.maximum() > 0
        assert bar.isVisible() is True
        assert bar.width() > 0
        assert bar.height() > 0
        # 滚动条只在溢出时占位：视口变窄恰好一个滚动条宽度
        assert (
            window._scroll_area.viewport().width()
            == wide_viewport - bar.width()
        )
    finally:
        window.close()
        window.deleteLater()


def test_scrollbar_track_click_jumps(
    qapp: QApplication, tmp_path
) -> None:
    """单击滚动条轨道下半部 → 列表跳转（不再只能靠滚轮）。"""
    window = FloatingPoolWindow()
    try:
        bar = _prepare_scrolled_window(window, qapp, 24, tmp_path)
        assert bar.maximum() > 0
        bar.setValue(0)

        point = QPoint(bar.width() // 2, bar.height() - 6)
        bar.mousePressEvent(
            _mouse_event(
                QEvent.Type.MouseButtonPress, point, Qt.LeftButton, Qt.LeftButton
            )
        )

        assert bar.value() > 0
    finally:
        window.close()
        window.deleteLater()


def test_scrollbar_handle_drag_scrolls(
    qapp: QApplication, tmp_path
) -> None:
    """按住滑块向下拖动 → 列表随滑块滚动，释放后退出按下态。"""
    window = FloatingPoolWindow()
    try:
        bar = _prepare_scrolled_window(window, qapp, 24, tmp_path)
        assert bar.maximum() > 0
        bar.setValue(0)

        handle = bar._get_handle_rect()
        start = handle.center().toPoint()
        bar.mousePressEvent(
            _mouse_event(
                QEvent.Type.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton
            )
        )
        assert bar._dragging is True

        moved = QPoint(start.x(), start.y() + 40)
        bar.mouseMoveEvent(
            _mouse_event(
                QEvent.Type.MouseMove, moved, Qt.NoButton, Qt.LeftButton
            )
        )
        assert bar.value() > 0

        bar.mouseReleaseEvent(
            _mouse_event(
                QEvent.Type.MouseButtonRelease, moved, Qt.LeftButton, Qt.NoButton
            )
        )
        assert bar._pressed is False
        assert bar._dragging is False
    finally:
        window.close()
        window.deleteLater()


# ── 入场 / 出场（整体缩放 + 透明度）与预算兜底 ──────────────────


def test_first_show_plays_entrance_animation(qapp: QApplication) -> None:
    """首次显示播放「整体缩放 + 透明度」入场，结束后落定终态。"""
    window = FloatingPoolWindow()
    try:
        window.show()
        qapp.processEvents()

        assert window._entrance_anim is not None, "首次显示未启动入场动画"
        assert window._fade < 1.0
        assert window._pulse <= ENTRANCE_SCALE_FROM + 1e-6

        assert _wait_until(lambda: window._entrance_done), "入场动画未结束"
        assert window._fade == 1.0
        assert window._pulse == 1.0
        assert window._entrance_anim is None
    finally:
        window.close()
        window.deleteLater()


def test_entrance_budget_exceeded_shows_immediately(qapp: QApplication) -> None:
    """启动预算（5s）耗尽后：入场直接落定，不播任何动画。"""
    window = FloatingPoolWindow()
    try:
        window._on_entrance_budget_exceeded()

        window.show()
        qapp.processEvents()

        assert window._entrance_expired is True
        assert window._entrance_anim is None
        assert window._entrance_done is True
        assert window._fade == 1.0
        assert window._pulse == 1.0
    finally:
        window.close()
        window.deleteLater()


def test_exit_request_without_show_closes_immediately() -> None:
    """未上屏就请求关闭：不播出场动画，立即关闭并执行回调。"""
    window = FloatingPoolWindow()
    calls: list[int] = []
    try:
        window.request_close_with_animation(lambda: calls.append(1))

        assert window.is_exit_finished() is True
        assert window._exit_anim is None
        assert calls == [1]
    finally:
        window.deleteLater()


def test_exit_plays_fade_out_then_closes(qapp: QApplication) -> None:
    """已上屏时请求关闭：播缩放 + 淡出，动画结束才真正 close。"""
    window = FloatingPoolWindow()
    calls: list[int] = []
    try:
        window.show()
        qapp.processEvents()
        assert _wait_until(lambda: window._entrance_done)

        window.request_close_with_animation(lambda: calls.append(1))

        assert window.is_exit_finished() is False, "不应立即关闭"
        assert window._exit_anim is not None, "未启动出场动画"
        assert _wait_until(lambda: window.is_exit_finished()), "出场动画未收尾"
        assert window.isVisible() is False
        assert calls == [1]
    finally:
        window.deleteLater()


def test_exit_budget_forces_close(qapp: QApplication) -> None:
    """出场兜底（3s）触发时直接关闭，不等待动画。"""
    window = FloatingPoolWindow()
    try:
        window.show()
        qapp.processEvents()
        assert _wait_until(lambda: window._entrance_done)

        window.request_close_with_animation()
        assert window._exit_anim is not None

        window._finish_exit()  # 模拟 EXIT_BUDGET_MS 超时

        assert window.is_exit_finished() is True
        assert window._exit_anim is None
        assert window.isVisible() is False
    finally:
        window.deleteLater()


def test_wait_for_exit_animation_is_bounded(qapp: QApplication) -> None:
    """有界等待：动画自然结束时立即返回，总耗时远小于 3s 预算。"""
    window = FloatingPoolWindow()
    try:
        window.show()
        qapp.processEvents()
        assert _wait_until(lambda: window._entrance_done)

        window.request_close_with_animation()
        started = time.monotonic()
        assert window.wait_for_exit_animation(EXIT_BUDGET_MS) is True
        elapsed = time.monotonic() - started

        assert elapsed < 1.0, f"等待未受控：{elapsed:.2f}s"
        assert window.isVisible() is False
    finally:
        window.deleteLater()


def test_exit_while_expanded_collapses_before_fade(qapp: QApplication) -> None:
    """展开态退出：先收回圆形再淡出，内容不会与卡片错位。"""
    window = FloatingPoolWindow()
    try:
        window.show()
        qapp.processEvents()
        assert _wait_until(lambda: window._entrance_done)

        window.set_expanded(True)
        assert _wait_until(lambda: window._morph >= 1.0)

        window.request_close_with_animation()
        assert _wait_until(lambda: window.is_exit_finished(), timeout_ms=3000)
        assert window.is_expanded() is False
        assert window.isVisible() is False
    finally:
        window.deleteLater()


# ── 右键菜单 ──────────────────────────────────────────────────


def test_context_menu_items_and_flags(qapp: QApplication) -> None:
    """右键菜单三项齐备；清空项为危险态且无宿主（空池）时禁用。"""
    window = FloatingPoolWindow()
    try:
        menu = window._build_context_menu()
        labels = [a.text() for a in menu.actions() if not a.isSeparator()]
        assert labels == ["打开主窗口", "清空全部文件池内容", "本次启动期间隐藏"]

        actions = {a.text(): a for a in menu.actions() if not a.isSeparator()}
        assert actions["清空全部文件池内容"].property("danger") is True
        assert actions["清空全部文件池内容"].isEnabled() is False
        assert actions["打开主窗口"].isEnabled() is True
        assert actions["本次启动期间隐藏"].isEnabled() is True
    finally:
        window.deleteLater()


def test_context_menu_clear_delegates_to_host_pool(
    qapp: QApplication,
) -> None:
    """「清空全部文件池内容」走主池 ``clear_all``（由它弹确认对话框）。"""
    window = FloatingPoolWindow()
    host = QWidget()
    calls: list[str] = []

    class _Pool(QWidget):
        items = [{"path": "x"}]

        def clear_all(self) -> None:  # noqa: D401 - 测试探针
            calls.append("clear_all")

    host._file_pool = _Pool(host)
    window._host_window = host
    try:
        menu = window._build_context_menu()
        actions = {a.text(): a for a in menu.actions() if not a.isSeparator()}
        assert actions["清空全部文件池内容"].isEnabled() is True

        actions["清空全部文件池内容"].trigger()
        qapp.processEvents()  # _defer 的 singleShot(0)

        assert calls == ["clear_all"]
    finally:
        window.deleteLater()
        host.deleteLater()


def test_activate_host_window_restores_minimized(qapp: QApplication) -> None:
    """「打开主窗口」：最小化先还原，再 raise + activate。"""

    class _FakeHost:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def isMinimized(self) -> bool:  # noqa: N802 - 镜像 Qt 接口
            return True

        def showNormal(self) -> None:  # noqa: N802
            self.calls.append("showNormal")

        def raise_(self) -> None:
            self.calls.append("raise")

        def activateWindow(self) -> None:  # noqa: N802
            self.calls.append("activate")

        def windowHandle(self):  # noqa: N802
            return None

    window = FloatingPoolWindow()
    host = _FakeHost()
    window._host_window = host
    try:
        window._activate_host_window()
        assert host.calls == ["showNormal", "raise", "activate"]
    finally:
        window.deleteLater()


def test_hide_for_session_emits_and_exits(qapp: QApplication) -> None:
    """「本次启动期间隐藏」：先通知宿主，再播出场动画并最终销毁。"""
    window = FloatingPoolWindow()
    fired: list[int] = []
    destroyed: list[int] = []
    window.hide_for_session_requested.connect(lambda: fired.append(1))
    window.destroyed.connect(lambda *_args: destroyed.append(1))
    try:
        window.show()
        qapp.processEvents()
        assert _wait_until(lambda: window._entrance_done)

        window.hide_for_session()

        assert fired == [1], "未通知宿主（宿主无法停用本会话重建）"
        # 出场动画结束 → close → deleteLater，以 destroyed 作为最终事实
        assert _wait_until(lambda: bool(destroyed), timeout_ms=3000), (
            "浮窗未在出场动画后销毁"
        )
    finally:
        try:
            window.deleteLater()
        except RuntimeError:
            pass
