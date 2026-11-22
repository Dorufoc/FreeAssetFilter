# -*- coding: utf-8 -*-
"""主题切换遮罩「目标外观就绪后再起钟」回归。

背景：冷启动首次点击标题栏明暗切换按钮时，目标主题外观（QSS/调色板/
内容重绘）尚未准备好，旧实现的圆形遮罩/透明度动画提前起钟，导致视觉卡顿
与「遮罩已过半、新界面才刚出现」的闪现。修复后：

* :class:`_SnapshotTransitionOverlay` 支持 ``start(defer_animation=True)``——
  仅显示旧外观静态快照、不起钟；``mark_ready()`` 才排定起钟；
* ``MainWindow.begin_theme_transition`` 以暂缓模式启动内容层遮罩，并布设
  「就绪观察器」（Paint 事件 + 超时兜底），目标界面准备好后放行起钟；
* 主题翻转仍是非阻塞的，dissolve/背景/布局链路不受影响。

本文件用轻量替身直接驱动组件与观察器方法，避免构造完整 MainWindow（依赖
预览器/托盘等重资源），只锁定上述契约。

验证：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/test_theme_transition_readiness.py -v
"""

from __future__ import annotations

from typing import Optional

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QWidget

from sopeek.ui.components.theme_transition_overlay import ContentTransitionOverlay
from sopeek.ui.main_window import MainWindow

pytestmark = pytest.mark.unit


def _make_overlay(parent: QWidget) -> ContentTransitionOverlay:
    """构造一枚带有效快照的径向揭示遮罩（测试夹具）。

    PySide 的父对象 ownership 会把 QObject 的 C++ 生命周期绑到 parent 上；
    测试里内联创建的 ``parent`` 若无 Python 引用会被 GC 连带删掉遮罩。
    把 parent 挂在遮罩属性上保活，确保测试期间 C++ 对象一直可用。
    """
    snapshot = QPixmap(40, 30)
    snapshot.fill(QColor("#336699"))
    overlay = ContentTransitionOverlay(parent, snapshot, 450, QPoint(5, 5))
    overlay._test_parent = parent  # type: ignore[attr-defined]  # 保活 parent
    return overlay


class _Host(QObject):
    """承载 MainWindow 就绪观察器方法的轻量替身（无需完整主窗口）。"""

    def __init__(self, content: Optional[QWidget], overlay: ContentTransitionOverlay) -> None:
        super().__init__()
        self._content = content
        self._content_theme_overlay = overlay
        self._theme_ready_seq: int = 0
        self._theme_ready_filter: Optional[QObject] = None
        self._theme_ready_timer: Optional[object] = None
        # 绑定真实方法（取消绑定后以替身作为 self 调用）。必须用 MainWindow
        # 内部的真实方法名，因为 _arm/_on_ready 内部按这些名字互相调用。
        self._arm_theme_ready = MainWindow._arm_theme_ready.__get__(self)
        self._on_theme_ready = MainWindow._on_theme_ready.__get__(self)
        self._disarm_theme_ready = MainWindow._disarm_theme_ready.__get__(self)
        self.arm = self._arm_theme_ready
        self.on_ready = self._on_theme_ready
        self.disarm = self._disarm_theme_ready


class _BeginStub(QObject):
    """驱动 ``begin_theme_transition`` 的最小宿主替身。"""

    def __init__(self, overlay: ContentTransitionOverlay, *, fail: bool = False) -> None:
        super().__init__()
        self._overlay = overlay
        self._fail = fail
        self.calls: list[tuple] = []

    def _start_content_theme_transition(
        self, mode: str = "reveal", defer_until_ready: bool = False
    ) -> Optional[ContentTransitionOverlay]:
        self.calls.append(("start", mode, defer_until_ready))
        if self._fail:
            raise RuntimeError("snapshot failed")
        return self._overlay

    def _capture_background_pre_theme_state(self) -> None:
        self.calls.append(("background",))

    def _arm_theme_ready(self, overlay: ContentTransitionOverlay) -> None:
        self.calls.append(("arm", overlay))


class TestOverlayDeferral:
    """遮罩层：默认起钟、暂缓起钟、mark_ready 放行、幂等与结束竞态。"""

    def test_default_start_schedules_animation(self, qapp) -> None:
        """默认 start 仍走一拍推迟起钟（历史行为不变）。"""
        parent = QWidget()
        overlay = _make_overlay(parent)
        try:
            assert overlay._start_scheduled is False
            overlay.start()
            assert overlay._started is True
            assert overlay._active is True
            assert overlay._start_scheduled is True
            assert overlay.is_finished() is False
        finally:
            overlay.finish_now()

    def test_deferred_start_does_not_schedule(self, qapp) -> None:
        """暂缓模式只显示静态快照、不起钟。"""
        parent = QWidget()
        overlay = _make_overlay(parent)
        try:
            overlay.start(defer_animation=True)
            assert overlay._started is True
            assert overlay._active is True
            assert overlay._start_scheduled is False
            assert overlay.is_finished() is False
        finally:
            overlay.finish_now()

    def test_mark_ready_schedules_and_is_idempotent(self, qapp) -> None:
        """mark_ready 仅排定一次起钟，重复调用安全。"""
        parent = QWidget()
        overlay = _make_overlay(parent)
        try:
            overlay.start(defer_animation=True)
            assert overlay._start_scheduled is False
            overlay.mark_ready()
            assert overlay._start_scheduled is True
            overlay.mark_ready()
            assert overlay._start_scheduled is True
            assert overlay.is_finished() is False
        finally:
            overlay.finish_now()

    def test_mark_ready_after_finish_is_noop(self, qapp) -> None:
        """暂缓遮罩先结束再 mark_ready：不留悬空动画启动。"""
        parent = QWidget()
        overlay = _make_overlay(parent)
        overlay.start(defer_animation=True)
        overlay.finish_now()
        assert overlay.is_finished() is True
        overlay.mark_ready()
        assert overlay.is_finished() is True
        assert overlay._start_scheduled is False

    def test_start_is_idempotent(self, qapp) -> None:
        """重复 start 不重置已排定状态。"""
        parent = QWidget()
        overlay = _make_overlay(parent)
        try:
            overlay.start()
            overlay.start(defer_animation=True)
            assert overlay._start_scheduled is True
        finally:
            overlay.finish_now()


class TestThemeReadyObserver:
    """就绪观察器：Paint/超时放行、代际失效、幂等拆除、无内容立即放行。"""

    def test_arm_installs_filter_and_timer(self, qapp) -> None:
        """布设后过滤器与定时器就位，动画仍未起钟。"""
        content = QWidget()
        overlay = _make_overlay(content)
        overlay.start(defer_animation=True)
        host = _Host(content, overlay)
        try:
            host.arm(overlay)
            assert host._theme_ready_filter is not None
            assert host._theme_ready_timer is not None
            assert overlay._start_scheduled is False
        finally:
            host.disarm()
            overlay.finish_now()

    def test_ready_releases_animation_and_disarms(self, qapp) -> None:
        """当前代际就绪：放行起钟并拆除观察器。"""
        content = QWidget()
        overlay = _make_overlay(content)
        overlay.start(defer_animation=True)
        host = _Host(content, overlay)
        try:
            host.arm(overlay)
            seq = host._theme_ready_seq
            host.on_ready(seq)
            assert overlay._start_scheduled is True
            assert host._theme_ready_filter is None
            assert host._theme_ready_timer is None
        finally:
            overlay.finish_now()

    def test_stale_generation_is_ignored(self, qapp) -> None:
        """过期代际回调被丢弃，不放行也不拆观察器。"""
        content = QWidget()
        overlay = _make_overlay(content)
        overlay.start(defer_animation=True)
        host = _Host(content, overlay)
        try:
            host.arm(overlay)
            host.on_ready(host._theme_ready_seq - 1)
            assert overlay._start_scheduled is False
            assert host._theme_ready_filter is not None
        finally:
            host.disarm()
            overlay.finish_now()

    def test_disarm_increments_generation(self, qapp) -> None:
        """每次拆除递增代际，使上一轮定时器回调失效。"""
        content = QWidget()
        overlay = _make_overlay(content)
        overlay.start(defer_animation=True)
        host = _Host(content, overlay)
        try:
            host.arm(overlay)
            old_seq = host._theme_ready_seq
            host.disarm()
            assert host._theme_ready_seq > old_seq
            host.on_ready(old_seq)
            assert overlay._start_scheduled is False
        finally:
            overlay.finish_now()

    def test_no_content_releases_immediately(self, qapp) -> None:
        """内容层缺失时直接放行（无 Paint 可等）。"""
        overlay = _make_overlay(QWidget())
        overlay.start(defer_animation=True)
        host = _Host(None, overlay)
        try:
            host.arm(overlay)
            assert overlay._start_scheduled is True
            assert host._theme_ready_filter is None
            assert host._theme_ready_timer is None
        finally:
            overlay.finish_now()

    def test_paint_event_filter_triggers_release(self, qapp) -> None:
        """模拟内容层 Paint 事件：过滤器放行起钟（链通事件 → 回调）。"""
        content = QWidget()
        overlay = _make_overlay(content)
        overlay.start(defer_animation=True)
        host = _Host(content, overlay)
        try:
            host.arm(overlay)
            filter_obj = host._theme_ready_filter
            assert filter_obj is not None
            # 直接派发事件过滤器回调，避免真实 Paint 需要 painter 的副作用。
            ignored = filter_obj.eventFilter(content, QEvent(QEvent.Paint))
            assert ignored is False  # 过滤器不吞事件
            assert overlay._start_scheduled is True
            assert host._theme_ready_filter is None
        finally:
            overlay.finish_now()

    def test_overlay_missing_disarms(self, qapp) -> None:
        """目标遮罩已不存在时回调安全拆除观察器。"""
        content = QWidget()
        overlay = _make_overlay(content)
        host = _Host(content, overlay)
        host._content_theme_overlay = None
        host.arm(overlay)
        host.on_ready(host._theme_ready_seq)
        assert host._theme_ready_filter is None
        assert host._theme_ready_timer is None


class TestBeginThemeTransition:
    """入口链路：begin_theme_transition 以暂缓模式启动并布设观察器。"""

    def test_begin_defers_and_arms(self, qapp) -> None:
        """入口传 defer_until_ready=True、布设观察器、抓背景（顺序正确）。"""
        parent = QWidget()
        overlay = _make_overlay(parent)
        stub = _BeginStub(overlay)
        try:
            MainWindow.begin_theme_transition(stub)
            assert stub.calls == [
                ("start", "reveal", True),
                ("arm", overlay),
                ("background",),
            ]
        finally:
            overlay.finish_now()

    def test_begin_snapshot_failure_still_captures_background(self, qapp) -> None:
        """快照失败不布设观察器、不阻塞背景抓拍与主题切换本身。"""
        parent = QWidget()
        overlay = _make_overlay(parent)
        stub = _BeginStub(overlay, fail=True)
        MainWindow.begin_theme_transition(stub)
        assert stub.calls == [("start", "reveal", True), ("background",)]
        overlay.finish_now()
