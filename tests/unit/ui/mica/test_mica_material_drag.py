# -*- coding: utf-8 -*-
"""``ui.mica.material`` 的视口层拖动行为测试。

锁定的是「逐监视器持久化视口层」改造引入的可断言不变量（全部 offscreen 安全、
不 show 窗口）：

* **层烘焙状态** —— ``_on_bake_done`` 把 worker 结果应用为 ``_layer``
  （:class:`~ui.mica.drag.ViewportLayer`）与 ``_layer_pixmap``；
* **陈旧性守卫** —— 代际/key 不匹配的过期层结果被丢弃（绝不提交旧主题/旧区域）；
* **层内无重烘焙** —— 窗口在监视器内平移 ``begin_interaction`` 不触发重烘焙
  （``_maybe_rebake`` 不被调用）；
* **跨监视器重烘焙一次** —— 窗口跨监视器时 ``_maybe_rebake(force=True)`` 恰一次；
* **绘制取材** —— ``_layer_blit`` 返回窗口子矩形；``paint`` 按层内子矩形绘制
  （1:1 整数 ⇒ 真 blit；浮点 ⇒ 亚像素平滑）。
"""

from __future__ import annotations

from typing import Optional
from unittest import mock

import numpy as np
import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from freeassetfilter.ui.mica import material as material_mod
from freeassetfilter.ui.mica.drag import ViewportLayer, layer_to_source

#: 两块相邻监视器（虚拟桌面坐标）。
MONITOR_A = (0, 0, 2560, 1440)
MONITOR_B = (0, 1440, 2560, 1440)
#: 窗口尺寸。
WIN = (1600, 1000)


def _widget_with_mica(qapp, **kw) -> tuple:
    """构造一个 offscreen 安全、懒烘焙的 MicaMaterial 门面。"""
    widget = QWidget()
    mica = material_mod.MicaMaterial(widget, lazy=True, **kw)
    return widget, mica


def _layer_for(
    monitor: tuple,
    win: tuple,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> ViewportLayer:
    """构造一块与指定监视器/窗口一致的视口层（默认 1:1 于虚拟区域）。"""
    return ViewportLayer(
        region=monitor,
        width=width if width is not None else monitor[2],
        height=height if height is not None else monitor[3],
        win_size=win,
    )


# ---------------------------------------------------------------------------
# 层烘焙状态
# ---------------------------------------------------------------------------


def test_on_bake_done_applies_layer(qapp, monkeypatch) -> None:
    """``_on_bake_done`` 把匹配 key/gen 的 worker 结果应用为层与层 pixmap。"""
    widget, mica = _widget_with_mica(qapp)
    region = MONITOR_A
    layer_display_long = material_mod._layer_display_long(region)
    key = ("params", True, "sig", region, layer_display_long)
    mica._layer_key = key
    mica._layer_gen = 1
    display = np.zeros((288, 512, 3), dtype=np.uint8)
    layer_info = _layer_for(region, WIN, width=512, height=288)

    try:
        mica._on_bake_done((display, layer_info, key, 1))
        assert mica._layer is layer_info
        assert mica._layer_pixmap is not None and not mica._layer_pixmap.isNull()
        assert mica._layer_key == key
    finally:
        mica.dispose()
        widget.deleteLater()


def test_on_bake_done_drops_stale_generation(qapp, monkeypatch) -> None:
    """代际不匹配的过期层结果被丢弃，不触发大图转换。"""
    widget, mica = _widget_with_mica(qapp)
    region = MONITOR_A
    key = ("params", True, "sig", region, 2560)
    pixmap_mock = mock.Mock(return_value=QPixmap())
    monkeypatch.setattr(material_mod, "_pixmap_from_rgb", pixmap_mock)
    mica._layer_key = key
    mica._layer_gen = 5
    display = np.zeros((288, 512, 3), dtype=np.uint8)
    layer_info = _layer_for(region, WIN, width=512, height=288)

    try:
        # gen 4 != 5 -> 过期 -> 丢弃，不转换。
        mica._on_bake_done((display, layer_info, key, 4))
        assert mica._layer is None
        assert pixmap_mock.call_count == 0

        # gen 5 匹配 -> 正常应用。
        mica._on_bake_done((display, layer_info, key, 5))
        assert mica._layer is layer_info
        assert pixmap_mock.call_count == 1
    finally:
        mica.dispose()
        widget.deleteLater()


# ---------------------------------------------------------------------------
# 交互期重烘焙判定
# ---------------------------------------------------------------------------


def test_begin_interaction_no_rebake_within_monitor(qapp, monkeypatch) -> None:
    """窗口在监视器内平移：``begin_interaction`` 不触发层重烘焙。"""
    widget, mica = _widget_with_mica(qapp)
    key = ("params", True, "sig", MONITOR_A, 2560)
    mica._layer = _layer_for(MONITOR_A, WIN, width=512, height=288)
    mica._layer_key = key
    mica._layer_display_long = 2560
    monkeypatch.setattr(mica, "_monitor_rect_for", lambda window_rect: MONITOR_A)
    monkeypatch.setattr(mica, "_layer_key_for", lambda region, dl: key)
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (300, 400, *WIN))
    rebake_mock = mock.Mock()
    monkeypatch.setattr(mica, "_maybe_rebake", rebake_mock)

    try:
        mica.begin_interaction()
        rebake_mock.assert_not_called()
    finally:
        mica.dispose()
        widget.deleteLater()


def test_begin_interaction_rebakes_once_on_monitor_cross(qapp, monkeypatch) -> None:
    """窗口跨到另一块监视器：``_maybe_rebake(force=True)`` 恰好一次。"""
    widget, mica = _widget_with_mica(qapp)
    mica._layer = _layer_for(MONITOR_A, WIN, width=512, height=288)
    mica._layer_key = ("params", True, "sig", MONITOR_A, 2560)
    mica._layer_display_long = 2560
    monkeypatch.setattr(mica, "_monitor_rect_for", lambda window_rect: MONITOR_B)

    def key_for(region, layer_display_long):
        return ("params", True, "sig", region, int(layer_display_long))

    monkeypatch.setattr(mica, "_layer_key_for", key_for)
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (300, 1800, *WIN))
    rebake_mock = mock.Mock()
    monkeypatch.setattr(mica, "_maybe_rebake", rebake_mock)

    try:
        mica.begin_interaction()
        rebake_mock.assert_called_once_with(force=True)
    finally:
        mica.dispose()
        widget.deleteLater()


# ---------------------------------------------------------------------------
# 绘制取材
# ---------------------------------------------------------------------------


def test_layer_blit_returns_window_subrect_float(qapp, monkeypatch) -> None:
    """层分辨率与虚拟区域不同 → 返回浮点子矩形（亚像素平滑绘制）。"""
    widget, mica = _widget_with_mica(qapp)
    layer = ViewportLayer(region=MONITOR_A, width=512, height=288, win_size=WIN)
    mica._layer = layer
    mica._layer_pixmap = QPixmap(512, 288)
    mica._pixmap = QPixmap(WIN[0], WIN[1])
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (192, 88, *WIN))

    try:
        pixmap, src, smooth = mica._layer_blit()
        assert pixmap is mica._layer_pixmap
        expected = layer_to_source(layer, (192, 88, *WIN))
        assert src is not None and all(isinstance(v, float) for v in src)
        assert src == pytest.approx(expected, abs=1e-6)
        assert smooth is True
    finally:
        mica.dispose()
        widget.deleteLater()


def test_layer_blit_returns_1to1_integer(qapp, monkeypatch) -> None:
    """层与虚拟区域 1:1 且坐标整型 → 返回整型子矩形（真 blit，无重采样）。"""
    widget, mica = _widget_with_mica(qapp)
    layer = _layer_for(MONITOR_A, WIN)  # 1:1
    mica._layer = layer
    mica._layer_pixmap = QPixmap(MONITOR_A[2], MONITOR_A[3])
    mica._pixmap = QPixmap(WIN[0], WIN[1])
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (0, 0, *WIN))

    try:
        pixmap, src, smooth = mica._layer_blit()
        assert pixmap is mica._layer_pixmap
        assert src == (0, 0, WIN[0], WIN[1])
        assert all(isinstance(v, int) for v in src)
        assert smooth is False
    finally:
        mica.dispose()
        widget.deleteLater()


def test_layer_blit_falls_back_to_static_pixmap(qapp, monkeypatch) -> None:
    """层未就绪时回退到整窗静态场（``src=None``，整幅绘制）。"""
    widget, mica = _widget_with_mica(qapp)
    mica._layer = None
    mica._layer_pixmap = None
    mica._pixmap = QPixmap(WIN[0], WIN[1])
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (192, 88, *WIN))

    try:
        pixmap, src, smooth = mica._layer_blit()
        assert pixmap is mica._pixmap
        assert src is None
        assert smooth is True
    finally:
        mica.dispose()
        widget.deleteLater()


def test_paint_draws_window_subrect(qapp, monkeypatch) -> None:
    """``paint`` 从层里按窗口位置取子矩形做一次 blit（平滑双线性）。"""
    widget, mica = _widget_with_mica(qapp)
    widget.resize(WIN[0], WIN[1])
    layer = ViewportLayer(region=MONITOR_A, width=512, height=288, win_size=WIN)
    mica._layer = layer
    mica._layer_pixmap = QPixmap(512, 288)
    mica._pixmap = QPixmap(WIN[0], WIN[1])
    mica._fade_alpha = 1.0
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (192, 88, *WIN))
    draw_calls = []
    orig_draw = QPainter.drawPixmap

    def recorder(self, *args, **kwargs):
        draw_calls.append(args)
        return orig_draw(self, *args, **kwargs)

    monkeypatch.setattr(QPainter, "drawPixmap", recorder)

    try:
        img = QImage(WIN[0], WIN[1], QImage.Format_RGB32)
        img.fill(QColor(0, 0, 0))
        painter = QPainter(img)
        try:
            mica.paint(painter, None)
        finally:
            painter.end()
    finally:
        mica.dispose()
        widget.deleteLater()

    assert draw_calls, "paint 必须至少绘制一次"
    src_rect = draw_calls[0][2]
    assert isinstance(src_rect, QRectF)
    assert src_rect.x() == pytest.approx(38.4, abs=1e-6)
    assert src_rect.y() == pytest.approx(17.6, abs=1e-6)
    assert src_rect.width() == pytest.approx(320.0, abs=1e-6)
    assert src_rect.height() == pytest.approx(200.0, abs=1e-6)


# ---------------------------------------------------------------------------
# overlay 防抖 & 绘制端不透明度（仍适用的既有不变量）
# ---------------------------------------------------------------------------


def test_overlay_change_arms_debounce_and_rebuild(qapp, monkeypatch) -> None:
    """overlay 变更触发防抖（pending=True + timer 启），静置后重建并复位。"""
    widget, mica = _widget_with_mica(qapp)
    monkeypatch.setattr(mica, "_request_rebuild", mock.Mock())

    try:
        mica.set_effect_parameters(overlay_opacity=0.5)
        assert mica._opacity_render_pending is True
        assert mica._opacity_timer.isActive() is True

        # 同值再次调用：不重置 pending（也不会二次启动计时）。
        mica.set_effect_parameters(overlay_opacity=0.5)
        assert mica._opacity_render_pending is True

        mica._on_opacity_settle()
        assert mica._opacity_render_pending is False
    finally:
        mica.dispose()
        widget.deleteLater()


def test_paint_steady_state_draws_opaque(qapp, monkeypatch) -> None:
    """绘制端稳态全不透明：opacity 只等于 fade_alpha，不再乘 overlay（banding 根因）。"""
    widget, mica = _widget_with_mica(qapp)
    values = []
    orig_setopacity = QPainter.setOpacity

    def recorder(self, opacity):
        values.append(opacity)
        return orig_setopacity(self, opacity)

    monkeypatch.setattr(QPainter, "setOpacity", recorder)

    try:
        mica._paused = False
        mica._pixmap = QPixmap(4, 4)
        mica._pixmap.fill(QColor(255, 255, 255))
        mica._overlay_opacity = 0.7
        mica._fade_alpha = 1.0
        monkeypatch.setattr(mica, "_layer_blit", lambda: (QPixmap(4, 4), None, True))

        img = QImage(widget.rect().width(), widget.rect().height(), QImage.Format_RGB32)
        img.fill(QColor(0, 0, 0))
        painter = QPainter(img)
        try:
            mica.paint(painter, None)
        finally:
            painter.end()

        assert 0.7 not in values
        assert values
        assert all(v == 1.0 for v in values)
    finally:
        mica.dispose()
        widget.deleteLater()
