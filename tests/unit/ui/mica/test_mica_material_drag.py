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
from PySide6.QtCore import QRectF, QThread
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


def test_layer_blit_samples_clamped_on_resize(qapp, monkeypatch) -> None:
    """resize（窗口尺寸 != layer.win_size）时 ``_layer_blit`` 仍返回层 + 非 None 子矩形。

    严格 ``layer_to_source`` 对尺寸不匹配判 ``None``；钳制版 ``layer_to_source_clamped``
    必须对 resize / 越界窗口返回一个合法子矩形 —— Mica 不因 resize 而消失。当层存在时，
    ``_layer_blit`` 绝不返回 ``(None, None, ...)``。
    """
    widget, mica = _widget_with_mica(qapp)
    layer = ViewportLayer(region=MONITOR_A, width=512, height=288, win_size=WIN)
    mica._layer = layer
    mica._layer_pixmap = QPixmap(512, 288)
    mica._pixmap = QPixmap(WIN[0], WIN[1])  # 兜底应被忽略（层存在）
    # 窗口 resize 到 1800x1000（与 layer.win_size 不一致）且部分越界到负 x。
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (-50, 88, 1800, 1000))

    try:
        pixmap, src, smooth = mica._layer_blit()
        assert pixmap is mica._layer_pixmap  # 绝不是 (None, None, ...)
        assert src is not None
        assert len(src) == 4
        assert src[0] >= 0.0 and src[1] >= 0.0   # 越界后钳制到层边界（非负）
        assert src[2] == pytest.approx(1800 * (512 / 2560), abs=1e-6)
        assert src[3] == pytest.approx(1000 * (288 / 1440), abs=1e-6)
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


# ---------------------------------------------------------------------------
# 拖动期快速路径（逐帧零重绘）与松手收敛（settle 淡化 / 跨屏等待新层）
# ---------------------------------------------------------------------------


def _ready_mica(widget, mica, *, region=MONITOR_A, pix_w=512, pix_h=288) -> None:
    """把 MicaMaterial 置为“层就绪”状态（1:1 整数裁剪路径）。"""
    mica._layer = ViewportLayer(region=region, width=pix_w, height=pix_h, win_size=WIN)
    mica._layer_pixmap = QPixmap(pix_w, pix_h)
    mica._layer_key = ("params", True, "sig", region, 2560)
    mica._layer_display_long = 2560


def test_fast_path_pure_move_no_update_no_probe(qapp, monkeypatch) -> None:
    """纯移动（层就绪、尺寸不变）：``begin_interaction`` 零重绘、零探测、零重烘。"""
    widget, mica = _widget_with_mica(qapp)
    _ready_mica(widget, mica)
    updates = mock.Mock()
    widget.update = updates
    monitor_spy = mock.Mock(return_value=MONITOR_A)
    key_spy = mock.Mock(return_value=mica._layer_key)
    rebake_mock = mock.Mock()
    monkeypatch.setattr(mica, "_monitor_rect_for", monitor_spy)
    monkeypatch.setattr(mica, "_layer_key_for", key_spy)
    monkeypatch.setattr(mica, "_maybe_rebake", rebake_mock)
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (300, 400, *WIN))

    try:
        mica.begin_interaction()
        rebake_mock.assert_not_called()
        monitor_spy.assert_not_called()  # 快速路径不做 COM 探测
        key_spy.assert_not_called()
        updates.assert_not_called()  # 快速路径不触发整窗重绘
    finally:
        mica.dispose()
        widget.deleteLater()


def test_fast_path_monitor_cross_rebakes_once_when_idle(qapp, monkeypatch) -> None:
    """跨监视器且无在途烘焙：首个越区事件触发恰好一次 ``_maybe_rebake(force=True)``。"""
    widget, mica = _widget_with_mica(qapp)
    _ready_mica(widget, mica)
    updates = mock.Mock()
    widget.update = updates
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (300, 1800, *WIN))
    rebake_mock = mock.Mock()
    monkeypatch.setattr(mica, "_maybe_rebake", rebake_mock)

    try:
        mica.begin_interaction()
        rebake_mock.assert_called_once_with(force=True)
        updates.assert_not_called()
    finally:
        mica.dispose()
        widget.deleteLater()


def test_fast_path_skips_rebake_while_bake_inflight(qapp, monkeypatch) -> None:
    """跨监视器但已有在途烘焙：不再重复提交（避免逐事件探测 / 重烘）。"""
    widget, mica = _widget_with_mica(qapp)
    _ready_mica(widget, mica)
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (300, 1800, *WIN))
    rebake_mock = mock.Mock()
    monkeypatch.setattr(mica, "_maybe_rebake", rebake_mock)
    mica._worker_thread = QThread()

    try:
        mica.begin_interaction()
        rebake_mock.assert_not_called()
    finally:
        mica.dispose()
        widget.deleteLater()


def test_drag_live_env_restores_legacy_update(qapp, monkeypatch) -> None:
    """``FAF_MICA_DRAG_LIVE=1``：恢复逐事件重绘 / 探测的旧行为（回归对照）。"""
    monkeypatch.setenv("FAF_MICA_DRAG_LIVE", "1")
    widget, mica = _widget_with_mica(qapp)
    _ready_mica(widget, mica)
    updates = mock.Mock()
    widget.update = updates
    monitor_spy = mock.Mock(return_value=MONITOR_A)
    key_spy = mock.Mock(return_value=mica._layer_key)
    rebake_mock = mock.Mock()
    monkeypatch.setattr(mica, "_monitor_rect_for", monitor_spy)
    monkeypatch.setattr(mica, "_layer_key_for", key_spy)
    monkeypatch.setattr(mica, "_maybe_rebake", rebake_mock)
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (300, 400, *WIN))

    try:
        mica.begin_interaction()
        updates.assert_called_once()  # LIVE：每事件重绘
        monitor_spy.assert_called_once()  # LIVE：逐事件探测
        rebake_mock.assert_not_called()
    finally:
        mica.dispose()
        widget.deleteLater()


def test_on_settle_same_monitor_starts_settle_fade(qapp, monkeypatch) -> None:
    """松手仍在同一监视器：启动旧裁剪 → 新裁剪的 settle 淡化。"""
    widget, mica = _widget_with_mica(qapp)
    _ready_mica(widget, mica)
    mica._last_painted_win = (100, 100, *WIN)
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (300, 400, *WIN))
    monkeypatch.setattr(mica, "_monitor_rect_for", lambda w: MONITOR_A)
    monkeypatch.setattr(mica, "_needs_layer_rebake", lambda *a: False)
    rebake_mock = mock.Mock()
    monkeypatch.setattr(mica, "_maybe_rebake", rebake_mock)
    updates = mock.Mock()
    widget.update = updates

    try:
        mica._on_settle()
        assert mica._interacting is False
        assert mica._hide_until_new_layer is False
        assert mica._settle_fade_active() is True
        rebake_mock.assert_called_once_with(force=False)
        updates.assert_called_once()
    finally:
        mica.dispose()
        widget.deleteLater()


def test_on_settle_same_spot_skips_fade(qapp, monkeypatch) -> None:
    """松手位置与最近绘制位置几乎重合：跳过淡化，仅单次重绘。"""
    widget, mica = _widget_with_mica(qapp)
    _ready_mica(widget, mica)
    mica._last_painted_win = (300, 400, *WIN)
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (300, 401, *WIN))
    monkeypatch.setattr(mica, "_monitor_rect_for", lambda w: MONITOR_A)
    monkeypatch.setattr(mica, "_needs_layer_rebake", lambda *a: False)
    monkeypatch.setattr(mica, "_maybe_rebake", mock.Mock())
    updates = mock.Mock()
    widget.update = updates

    try:
        mica._on_settle()
        assert mica._settle_fade_active() is False
        updates.assert_called_once()
    finally:
        mica.dispose()
        widget.deleteLater()


def test_on_settle_cross_monitor_waits_new_layer(qapp, monkeypatch) -> None:
    """跨监视器松手且新层烘焙在途：隐藏（纯色底）直到新层到达。"""
    widget, mica = _widget_with_mica(qapp)
    _ready_mica(widget, mica)
    mica._layer_key = ("params", True, "sig", MONITOR_A, 2560)
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (300, 1800, *WIN))
    monkeypatch.setattr(mica, "_monitor_rect_for", lambda w: MONITOR_B)
    monkeypatch.setattr(mica, "_needs_layer_rebake", lambda *a: True)
    monkeypatch.setattr(
        mica, "_layer_key_for", lambda region, dl: ("params", True, "sig", region, int(dl))
    )
    updates = mock.Mock()
    widget.update = updates
    mica._worker_thread = QThread()  # 在途烘焙（B 层）

    try:
        mica._on_settle()
        assert mica._hide_until_new_layer is True
        assert mica._settle_fade_active() is False
        updates.assert_called_once()
    finally:
        mica.dispose()
        widget.deleteLater()


def test_on_settle_cross_monitor_releases_when_no_bake_pending(qapp, monkeypatch) -> None:
    """跨监视器松手但无在途烘焙且 key 未变（极端）：立即解除隐藏，不停纯色底。"""
    widget, mica = _widget_with_mica(qapp)
    _ready_mica(widget, mica)
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (300, 1800, *WIN))
    monkeypatch.setattr(mica, "_monitor_rect_for", lambda w: MONITOR_B)
    monkeypatch.setattr(mica, "_needs_layer_rebake", lambda *a: True)
    monkeypatch.setattr(mica, "_layer_key_for", lambda region, dl: mica._layer_key)
    updates = mock.Mock()
    widget.update = updates

    try:
        mica._on_settle()
        assert mica._hide_until_new_layer is False
        updates.assert_called_once()
    finally:
        mica.dispose()
        widget.deleteLater()


def test_settle_fade_ticks_until_done(qapp, monkeypatch) -> None:
    """settle 淡化按节拍推进并在时长耗尽后停机（回落到常规帧）。"""
    widget, mica = _widget_with_mica(qapp)
    try:
        _ready_mica(widget, mica)
        mica._last_painted_win = (100, 100, *WIN)
        mica._settle_fade_ms = 120
        mica._start_settle_fade((300, 400, *WIN))
        assert mica._settle_fade_active() is True
        assert mica._settle_fade_ticks == 0

        for _ in range(8):  # 8 × 16ms = 128ms ≥ 120ms
            mica._on_settle_fade_tick()
        assert mica._settle_fade_active() is False
        assert mica._settle_fade_old_src is None
    finally:
        mica.dispose()
        widget.deleteLater()


def test_paint_during_settle_fade_draws_old_then_new(qapp, monkeypatch) -> None:
    """淡化帧绘制两笔：旧裁剪（不透明打底）+ 新裁剪（按进度叠入）。"""
    widget, mica = _widget_with_mica(qapp)
    _ready_mica(widget, mica)
    mica._fade_alpha = 1.0
    mica._settle_fade_ms = 120
    mica._settle_fade_old_src = (5.0, 5.0, 300.0, 200.0)
    mica._settle_fade_ticks = 2  # t ≈ 32/120
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (192, 88, *WIN))
    draw_calls = []
    orig_draw = QPainter.drawPixmap

    def recorder(self, *args, **kwargs):
        draw_calls.append(args)
        return orig_draw(self, *args, **kwargs)

    monkeypatch.setattr(QPainter, "drawPixmap", recorder)

    try:
        img = QImage(widget.rect().width(), widget.rect().height(), QImage.Format_RGB32)
        img.fill(QColor(0, 0, 0))
        painter = QPainter(img)
        try:
            mica.paint(painter, None)
        finally:
            painter.end()
    finally:
        mica.dispose()
        widget.deleteLater()

    assert len(draw_calls) == 2, "淡化帧应绘制旧、新两笔裁剪"
    assert all(isinstance(c[2], QRectF) for c in draw_calls)
