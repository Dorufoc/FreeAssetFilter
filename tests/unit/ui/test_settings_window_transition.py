# -*- coding: utf-8 -*-
"""设置窗口显示/关闭状态机测试（offscreen）。

当前产品状态：打开动画为窗口内快照从 104% 收缩归位（160ms），关闭淡出
仍为 0（同步关闭）。本文件锁定两条关键回归：

- 窗口几何不得在可见后变化；
- 打开动画不得碰 ``windowOpacity`` 或移动真实窗口。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete as shiboken_delete
from shiboken6 import isValid

_UI_ROOT: str = str(Path(__file__).resolve().parents[3] / "sopeek" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

import sopeek.ui.main_window as mw  # noqa: E402
from sopeek.ui.main_window import SettingsWindow  # noqa: E402

pytestmark = pytest.mark.unit


class _TrackedSettingsWindow(SettingsWindow):
    """记录每次 resize / move 时窗口是否已经揭开。"""

    def __init__(self, *args, **kwargs) -> None:
        self.resize_events: list[tuple[int, int, bool]] = []
        self.move_events: list[tuple[int, int, bool]] = []
        super().__init__(*args, **kwargs)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        try:
            self.resize_events.append((self.width(), self.height(), self._revealed))
        except AttributeError:
            # 父类构造早期 resize 时过渡状态尚未建立。
            pass

    def moveEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().moveEvent(event)
        try:
            self.move_events.append((self.x(), self.y(), self._revealed))
        except AttributeError:
            pass


@pytest.fixture
def window(qapp: QApplication) -> SettingsWindow:
    """构造设置窗口并在测试结束时强制销毁（避免深层控件树拖慢清道夫）。"""
    win = _TrackedSettingsWindow()
    win.setAttribute(Qt.WA_DeleteOnClose, True)
    try:
        yield win
    finally:
        try:
            win._cancel_open_animation()
            win._close_pre_cleanup_done = True
            win._skip_close_animation = True
            win._close_animation_active = False
            win._revealed = True
            win.close()
        except RuntimeError:
            pass
        try:
            if isValid(win):
                shiboken_delete(win)
        except Exception:  # noqa: BLE001 - 已销毁时跳过
            pass
        qapp.processEvents()


def _force_transition_supported(
    monkeypatch: pytest.MonkeyPatch, enabled: bool = True
) -> None:
    """让 offscreen 测试走真实平台分支。"""
    monkeypatch.setattr(
        SettingsWindow, "_window_animation_supported", staticmethod(lambda: True)
    )
    monkeypatch.setattr(
        SettingsWindow, "_window_animation_enabled", lambda self: enabled
    )


class TestPresentOffscreen:
    """offscreen/测试环境保持即时显示语义。"""

    def test_present_shows_immediately(
        self, window: SettingsWindow, qapp: QApplication
    ) -> None:
        """无显示器环境直接可见，且没有任何过渡残留状态。"""
        assert window._window_animation_supported() is False
        window.present()
        qapp.processEvents()
        assert window.isVisible() is True
        assert window._revealed is True
        assert window._open_snapshot_layer is None
        assert window._open_animation_active is False
        assert window.minimumSize().width() == 700


class TestOpenSnapshotAnimation:
    """打开：窗口固定几何，快照层把内容从 104% 收缩归位。"""

    def test_snapshot_layer_plays_without_moving_window(
        self,
        window: _TrackedSettingsWindow,
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """可见之后不得再出现任何 move / resize（横向抖动回归）。

        历史缺陷：窗口先移到屏外 show，再移回主屏；DWM 会异步重算扩展帧
        （705→707），且 windowOpacity 切换还会带来 1px 位移——两者都发生在
        窗口可见之后，表现为抖动。现在窗口只出现一次，动画全部发生在
        窗口内的快照层上。
        """
        _force_transition_supported(monkeypatch, enabled=True)

        window.present()
        qapp.processEvents()
        assert window.isVisible() is True
        final = QRect(window.geometry())
        assert final.width() >= 700
        assert final.height() >= 400

        # 首帧等待（32ms）+ 起播定时器之后，快照层应已接管内容。
        QTest.qWait(100)
        assert window._revealed is False
        assert window._open_snapshot_layer is not None
        assert window._open_animation_active is True
        assert window.geometry() == final
        # 快照层必须铺满客户区，否则收缩时四周会露出实时内容。
        assert window._open_snapshot_layer.geometry() == window._root.rect()

        QTest.qWait(int(mw.SETTINGS_WINDOW_OPEN_MS) + 200)
        assert window._revealed is True
        assert window._open_snapshot_layer is None
        assert window._open_animation_active is False
        assert window.geometry() == final

        # 记录"已揭开"之后的事件数，再等一段时间确认没有新增。
        resize_after = len([e for e in window.resize_events if e[2]])
        move_after = len([e for e in window.move_events if e[2]])
        QTest.qWait(150)
        assert len([e for e in window.resize_events if e[2]]) == resize_after
        assert len([e for e in window.move_events if e[2]]) == move_after

    def test_geometry_is_final_when_first_visible(
        self,
        window: _TrackedSettingsWindow,
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """窗口第一次可见时的几何就是最终几何。"""
        _force_transition_supported(monkeypatch, enabled=True)
        window.present()
        qapp.processEvents()
        final = QRect(window.geometry())
        assert final.width() >= 700
        assert final.height() >= 400
        QTest.qWait(int(mw.SETTINGS_WINDOW_OPEN_MS) + 200)
        assert window.geometry() == final

    def test_animation_disabled_reveals_without_snapshot(
        self,
        window: SettingsWindow,
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """动画开关关闭：不挂快照层，首帧等待后直接揭开。"""
        _force_transition_supported(monkeypatch, enabled=False)
        window.present()
        qapp.processEvents()
        assert window.isVisible() is True

        QTest.qWait(80)
        assert window._revealed is True
        assert window._open_snapshot_layer is None
        assert window._open_animation_active is False
        assert window.windowOpacity() == 1.0


class TestCloseWithoutAnimation:
    """关闭：动画已关闭，同步关闭。"""

    def test_close_does_not_start_fade(
        self,
        window: SettingsWindow,
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """关闭淡出时长为 0 时不得启动淡出动画。"""
        _force_transition_supported(monkeypatch, enabled=True)
        # 本用例只关注关闭路径：关掉打开动画，避免等待收缩动画结束。
        monkeypatch.setattr(mw, "SETTINGS_WINDOW_OPEN_MS", 0)
        monkeypatch.setattr(mw, "SETTINGS_WINDOW_CLOSE_MS", 0)
        window.present()
        qapp.processEvents()
        QTest.qWait(80)
        assert window._revealed is True

        window._close_pre_cleanup_done = True
        window.close()
        qapp.processEvents()
        assert window._close_animation_active is False
        assert window._close_fade is None
        assert isValid(window) is False or window.isHidden() is True

    def test_close_cancels_active_open_animation(
        self,
        window: SettingsWindow,
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """打开动画进行中关闭：必须撤层并清理过渡状态。"""
        _force_transition_supported(monkeypatch, enabled=True)
        # 拉长打开动画，确保关闭时快照层一定处于活动状态。
        monkeypatch.setattr(mw, "SETTINGS_WINDOW_OPEN_MS", 600)
        window.present()
        qapp.processEvents()
        QTest.qWait(180)
        assert window._open_snapshot_layer is not None
        assert window._open_animation_active is True

        window._close_pre_cleanup_done = True
        window.close()
        qapp.processEvents()
        assert window._open_snapshot_layer is None
        assert window._open_animation_active is False
        assert isValid(window) is False or window.isHidden() is True
