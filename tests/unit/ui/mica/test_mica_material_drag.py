# -*- coding: utf-8 -*-
"""``ui.mica.material`` 的视口层拖动行为测试。

锁定的是「整块虚拟桌面持久化视口层 + 实时 blit」改造引入的可断言不变量
（全部 offscreen 安全、不 show 窗口）：

* **层烘焙状态** —— ``_on_bake_done`` 把 worker 结果应用为 ``_layer``
  （:class:`~ui.mica.drag.ViewportLayer`）与 ``_layer_pixmap``；
* **陈旧性守卫** —— 代际/key 不匹配的过期层结果被丢弃（绝不提交旧主题/旧区域）；
* **全局层无运动态重烘焙** —— 窗口在桌面内平移 / 缩放 / 跨监视器，
  ``begin_interaction`` 都**不**触发重烘焙（``_maybe_rebake`` 不被调用）；
* **实时 blit 快速路径** —— 层就绪时 ``begin_interaction`` 仅调度一次重绘
  （O(1)/事件，零探测、零重烘），背景严格跟随光标，无"贴窗"、无松手跳变；
* **绘制取材** —— ``_layer_blit`` 返回窗口子矩形；``paint`` 按层内子矩形绘制
  （层与虚拟桌面 1:1 ⇒ 真 1:1 blit，抖动锚定屏幕坐标不打散色带；非 1:1 ⇒
  亚像素平滑）。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any, Optional
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


def test_window_rect_uses_top_level_client_without_native_child(
    qapp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """子控件矩形由顶层客户区换算，不得把 Mica 内容子树原生化。"""
    window = QWidget()
    window.resize(1200, 800)
    widget = QWidget(window)
    widget.setGeometry(100, 50, 400, 300)
    mica = material_mod.MicaMaterial(widget, lazy=True)
    top_level_hwnd = int(window.winId())
    calls = []

    monkeypatch.setattr(material_mod.winapi, "IS_WINDOWS", True)
    monkeypatch.setattr(
        material_mod.winapi,
        "client_rect",
        lambda hwnd: calls.append(hwnd) or (380, 200, 1800, 1200),
    )

    try:
        assert widget.internalWinId() == 0
        assert mica._window_rect_tuple() == (530, 275, 600, 450)
        assert calls == [top_level_hwnd]
        assert widget.internalWinId() == 0
    finally:
        mica.dispose()
        window.deleteLater()


def test_com_ptr_release_calls_release_before_invalidating_pointer(monkeypatch) -> None:
    """COM Release 必须在指针标记无效前调用，并且重复释放幂等。"""
    com_ptr = material_mod.winapi.ComPtr(1234)
    calls = []

    def method(self, index, restype, *argtypes):
        assert self.valid()
        assert index == 2

        def release_fn(pointer):
            calls.append(pointer.value)
            return 0

        return release_fn

    monkeypatch.setattr(material_mod.winapi.ComPtr, "method", method)

    com_ptr.release()
    com_ptr.release()

    assert calls == [1234]
    assert com_ptr.valid() is False


def test_desktop_wallpaper_position_uses_output_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GetPosition 按 HRESULT + 输出参数读取壁纸放置枚举。"""
    fake_interface = mock.Mock()

    def get_position(_this, value_ptr):
        value = ctypes.cast(value_ptr, ctypes.POINTER(ctypes.c_int)).contents
        value.value = 4
        return 0

    fake_interface.method.return_value = get_position
    wallpaper = material_mod.winapi.DesktopWallpaperCom(fake_interface)

    assert wallpaper.position() == "Fill"
    fake_interface.method.assert_called_once()
    assert fake_interface.method.call_args.args[:2] == (
        material_mod.winapi._DW_GET_POSITION,
        material_mod.winapi._HRESULT,
    )


def test_desktop_wallpaper_position_falls_back_on_hresult_failure() -> None:
    """GetPosition 失败时回退到 Fill，不读取未初始化枚举。"""
    fake_interface = mock.Mock()
    fake_interface.method.return_value = lambda _this, _value_ptr: -1
    wallpaper = material_mod.winapi.DesktopWallpaperCom(fake_interface)

    assert wallpaper.position() == "Fill"


def test_client_rect_returns_physical_client_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Win32 客户区原点与尺寸组合为虚拟桌面物理矩形。"""
    fake_user32 = mock.Mock()

    def get_client_rect(hwnd: Any, rect_ptr: Any) -> int:
        rect = ctypes.cast(rect_ptr, ctypes.POINTER(wintypes.RECT)).contents
        rect.left, rect.top, rect.right, rect.bottom = 0, 0, 1800, 1200
        return 1

    def client_to_screen(hwnd: Any, point_ptr: Any) -> int:
        point = ctypes.cast(point_ptr, ctypes.POINTER(wintypes.POINT)).contents
        point.x, point.y = 380, 200
        return 1

    fake_user32.GetClientRect.side_effect = get_client_rect
    fake_user32.ClientToScreen.side_effect = client_to_screen
    monkeypatch.setattr(material_mod.winapi, "IS_WINDOWS", True)
    monkeypatch.setattr(material_mod.winapi, "_user32", fake_user32)

    assert material_mod.winapi.client_rect(1234) == (380, 200, 1800, 1200)
    fake_user32.GetClientRect.assert_called_once()
    fake_user32.ClientToScreen.assert_called_once()


@pytest.mark.parametrize("get_ok, screen_ok", [(False, True), (True, False)])
def test_client_rect_returns_zero_on_win32_failure(
    monkeypatch: pytest.MonkeyPatch, get_ok: bool, screen_ok: bool
) -> None:
    """任一 Win32 几何查询失败时返回零矩形，交由上层回退。"""
    fake_user32 = mock.Mock()
    fake_user32.GetClientRect.return_value = int(get_ok)
    fake_user32.ClientToScreen.return_value = int(screen_ok)
    monkeypatch.setattr(material_mod.winapi, "IS_WINDOWS", True)
    monkeypatch.setattr(material_mod.winapi, "_user32", fake_user32)

    assert material_mod.winapi.client_rect(1234) == (0, 0, 0, 0)


def test_window_rect_falls_back_to_qt_geometry_when_client_query_fails(
    qapp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """客户区查询不可用时，材质层回退到 Qt 屏幕几何。"""
    window = QWidget()
    window.move(40, 60)
    window.resize(1200, 800)
    widget = QWidget(window)
    widget.setGeometry(100, 50, 400, 300)
    mica = material_mod.MicaMaterial(widget, lazy=True)
    monkeypatch.setattr(material_mod.winapi, "IS_WINDOWS", True)
    monkeypatch.setattr(material_mod.winapi, "client_rect", lambda hwnd: (0, 0, 0, 0))

    try:
        actual = mica._window_rect_tuple()
        expected_top_left = widget.mapToGlobal(widget.rect().topLeft())
        assert actual == (
            expected_top_left.x(),
            expected_top_left.y(),
            widget.width(),
            widget.height(),
        )
    finally:
        mica.dispose()
        window.deleteLater()


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
    mica._layer_pixmap = QPixmap(512, 288)
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
    """整块虚拟桌面层下跨监视器**不**触发重烘焙（层全局覆盖，与位置无关）。"""
    widget, mica = _widget_with_mica(qapp)
    mica._layer = _layer_for(MONITOR_A, WIN, width=512, height=288)
    mica._layer_pixmap = QPixmap(512, 288)
    mica._layer_key = ("params", True, "sig", MONITOR_A, 2560)
    mica._layer_display_long = 2560
    monkeypatch.setattr(mica, "_monitor_rect_for", lambda window_rect: MONITOR_B)
    rebake_mock = mock.Mock()
    monkeypatch.setattr(mica, "_maybe_rebake", rebake_mock)
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (300, 1800, *WIN))

    try:
        mica.begin_interaction()
        rebake_mock.assert_not_called()
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


def test_fast_path_pure_move_schedules_update_no_rebake(qapp, monkeypatch) -> None:
    """纯移动（层就绪）：``begin_interaction`` 仅调度一次重绘，零重烘焙、零探测、零 key 计算。"""
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
        # 实时 blit 快速路径：调度一次重绘（让背景跟随光标），但不重烘焙 / 不探测。
        updates.assert_called_once()
        rebake_mock.assert_not_called()
        monitor_spy.assert_not_called()
        key_spy.assert_not_called()
    finally:
        mica.dispose()
        widget.deleteLater()


def test_fast_path_resize_no_rebake(qapp, monkeypatch) -> None:
    """缩放（窗口尺寸变化）：整块虚拟桌面层与尺寸无关，仍不触发重烘焙。"""
    widget, mica = _widget_with_mica(qapp)
    _ready_mica(widget, mica)
    updates = mock.Mock()
    widget.update = updates
    rebake_mock = mock.Mock()
    monkeypatch.setattr(mica, "_maybe_rebake", rebake_mock)
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (300, 400, 2400, 1400))

    try:
        mica.begin_interaction()
        updates.assert_called_once()
        rebake_mock.assert_not_called()
    finally:
        mica.dispose()
        widget.deleteLater()


def test_fast_path_unready_triggers_rebake_and_update(qapp, monkeypatch) -> None:
    """层未就绪（启动首帧 / 降级）：``begin_interaction`` 确保异步烘焙在途并刷新。"""
    widget, mica = _widget_with_mica(qapp)
    # 不调用 _ready_mica：层为空。
    mica._layer = None
    mica._layer_pixmap = None
    updates = mock.Mock()
    widget.update = updates
    rebake_mock = mock.Mock()
    monkeypatch.setattr(mica, "_maybe_rebake", rebake_mock)
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (300, 400, *WIN))

    try:
        mica.begin_interaction()
        updates.assert_called_once()
        rebake_mock.assert_called_once_with(force=False)
    finally:
        mica.dispose()
        widget.deleteLater()


def test_on_settle_same_spot_skips_fade(qapp, monkeypatch) -> None:
    """松手位置与最近绘制位置几乎重合：不启动任何淡化，仅单次重绘（幂等）。"""
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


def test_on_settle_is_idempotent_no_rebake(qapp, monkeypatch) -> None:
    """整块虚拟桌面层下，松手回调不触发重烘焙（背景已由实时 blit 正确跟随）。"""
    widget, mica = _widget_with_mica(qapp)
    _ready_mica(widget, mica)
    rebake_mock = mock.Mock()
    monkeypatch.setattr(mica, "_maybe_rebake", rebake_mock)
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (300, 1800, *WIN))

    try:
        mica._on_settle()
        assert mica._interacting is False
        rebake_mock.assert_not_called()
    finally:
        mica.dispose()
        widget.deleteLater()


def test_layer_display_long_is_screen_1to1(qapp, monkeypatch) -> None:
    """层显示长边 == 虚拟桌面长边（≤8192 的常见配置）⇒ 1:1 屏幕分辨率。

    这是抹掉色彩断层的核心不变量：层以 1:1 渲染、抖动锚定绝对屏幕坐标，blit
    时才不被双线性重采样抹平。超过 8192 的极端虚拟桌面才会轻微降采样。
    """
    region_small = (0, 0, 2560, 1440)
    region_4k = (0, 0, 3840, 2160)
    region_dual = (-1920, 0, 7680, 2160)
    assert material_mod._layer_display_long(region_small) == 2560
    assert material_mod._layer_display_long(region_4k) == 3840
    assert material_mod._layer_display_long(region_dual) == 7680

    region_triple = (0, 0, 11520, 2160)  # 三 4K：超过上限，封顶 8192。
    assert material_mod._layer_display_long(region_triple) == 8192


def test_paint_blits_1to1_when_layer_matches_screen(qapp, monkeypatch) -> None:
    """层与虚拟桌面 1:1（常见配置）⇒ ``_layer_blit`` 返回整型子矩形、``smooth=False``。

    这是抹掉色彩断层的关键不变量：1:1 blit 不做重采样，抖动图案被原样保留、
    锚定在绝对屏幕坐标，渐变区不再出现色带。
    """
    widget, mica = _widget_with_mica(qapp)
    region = (0, 0, 2560, 1440)
    layer = ViewportLayer(region=region, width=2560, height=1440, win_size=WIN)
    mica._layer = layer
    mica._layer_pixmap = QPixmap(2560, 1440)
    mica._pixmap = QPixmap(WIN[0], WIN[1])
    monkeypatch.setattr(mica, "_window_rect_tuple", lambda: (640, 360, *WIN))

    try:
        pixmap, src, smooth = mica._layer_blit()
        assert pixmap is mica._layer_pixmap
        # 窗口在 (640,360)：相对虚拟原点的整型偏移。
        assert src == (640, 360, WIN[0], WIN[1])
        assert all(isinstance(v, int) for v in src)
        assert smooth is False
    finally:
        mica.dispose()
        widget.deleteLater()


# ---------------------------------------------------------------------------
# 合成器状态单一数据源（_layer/_layer_pixmap property 委托）
# ---------------------------------------------------------------------------


def test_layer_attributes_delegate_to_compositor(qapp) -> None:
    """``_layer`` / ``_layer_pixmap`` 读写委托到合成器（状态单一数据源）。

    属性 setter 同步替换合成器几何 / 像素并作废呈现锚点；``dispose`` 后
    合成器同样被清空，不留悬空引用。
    """
    widget, mica = _widget_with_mica(qapp)
    layer = _layer_for(MONITOR_A, WIN, width=512, height=288)
    pixmap = QPixmap(512, 288)

    try:
        mica._layer = layer
        mica._layer_pixmap = pixmap
        assert mica._compositor.layer is layer
        assert mica._compositor.pixmap is pixmap
        assert mica._compositor.ready is True
        assert mica._layer is layer
        assert mica._layer_pixmap is pixmap

        mica.dispose()
        assert mica._compositor.ready is False
        assert mica._layer is None
        assert mica._layer_pixmap is None
    finally:
        widget.deleteLater()


# ---------------------------------------------------------------------------
# 实验开关：原生 DWM 云母（set_native_backdrop）
# ---------------------------------------------------------------------------


def test_native_backdrop_stops_custom_layer_and_paints_black(qapp, monkeypatch) -> None:
    """开启原生模式：层清空、烘焙停用、绘制只铺纯黑、交互 O(1) 零重绘。"""
    widget, mica = _widget_with_mica(qapp)
    _ready_mica(widget, mica)
    updates = mock.Mock()
    widget.update = updates
    rebake_mock = mock.Mock()
    monkeypatch.setattr(mica, "_maybe_rebake", rebake_mock)

    try:
        mica.set_native_backdrop(True)
        assert mica._native_backdrop is True
        assert mica._layer is None and mica._layer_pixmap is None
        assert mica._paused is True
        # 切换本身触发一次重绘（切到纯黑呈现），此后交互期零重绘。
        assert updates.call_count == 1

        # move/resize 事件：O(1) 记账，零重绘（DWM 自行重绘系统背景）。
        mica.begin_interaction()
        assert updates.call_count == 1

        # 不再起任何后台烘焙线程。
        mica.refresh_async()
        assert mica._worker_thread is None

        # paint：客户区铺纯黑（扩展帧约定，由 DWM 呈现原生云母）。
        img = QImage(64, 48, QImage.Format_RGB32)
        painter = QPainter(img)
        try:
            mica.paint(painter, None)
        finally:
            painter.end()
        assert img.pixelColor(10, 10) == QColor(0, 0, 0)
    finally:
        mica.dispose()
        widget.deleteLater()


def test_native_backdrop_disable_restores_custom_layer(qapp, monkeypatch) -> None:
    """关闭原生模式：恢复自研层并强制重烘焙一次视口层。"""
    widget, mica = _widget_with_mica(qapp)
    _ready_mica(widget, mica)
    rebake_mock = mock.Mock()
    monkeypatch.setattr(mica, "_maybe_rebake", rebake_mock)

    try:
        mica.set_native_backdrop(True)
        mica.set_native_backdrop(False)
        assert mica._native_backdrop is False
        assert mica._paused is False
        rebake_mock.assert_called_with(force=True)
    finally:
        mica.dispose()
        widget.deleteLater()


def test_native_backdrop_toggle_is_idempotent(qapp) -> None:
    """重复设置同一状态为 no-op（不重复清层 / 重复重烘焙）。"""
    widget, mica = _widget_with_mica(qapp)
    _ready_mica(widget, mica)
    layer = mica._layer

    try:
        mica.set_native_backdrop(False)
        # 状态未变：层不被清除。
        assert mica._layer is layer
        mica.set_native_backdrop(True)
        cleared = mica._layer is None
        mica.set_native_backdrop(True)
        assert cleared and mica._layer is None
    finally:
        mica.dispose()
        widget.deleteLater()
