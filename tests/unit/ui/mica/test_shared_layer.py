# -*- coding: utf-8 -*-
"""MicaMaterial 共享视口层借用模式与设置窗口叠加背景测试。

锁定的不变量：

* 借用方不创建 ``WallpaperProvider``、不启动烘焙线程；
* 源材质交付新层时，借用方同步接管同一份 ``ViewportLayer`` / ``QPixmap``；
* 借用方的主题/参数更新不会反向修改源材质；
* 设置窗口只在宿主 ``mica`` 模式下显示共享背景，且强制走 CPU 光栅版。
"""

from __future__ import annotations

from unittest import mock

import pytest
from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QWidget

from freeassetfilter.ui.mica import material as material_mod
from freeassetfilter.ui.mica.drag import ViewportLayer

pytestmark = pytest.mark.unit

_REGION = (0, 0, 1920, 1080)
_WIN = (800, 600)


def _install_layer(mica, color: str = "#336699") -> tuple:
    """直接给材质装一块可断言的视口层（不触发真实壁纸/GPU 烘焙）。"""
    layer = ViewportLayer(
        region=_REGION,
        width=_REGION[2] // 10,
        height=_REGION[3] // 10,
        win_size=_WIN,
    )
    pixmap = QPixmap(8, 8)
    pixmap.fill(QColor(color))
    mica._layer = layer
    mica._layer_pixmap = pixmap
    mica._layer_key = ("shared-test", color)
    mica._has_shown = True
    mica._compositor.set_layer(layer, pixmap)
    return layer, pixmap


class TestSharedLayerMaterial:
    """``MicaMaterial(layer_source=...)`` 的借用语义。"""

    def test_borrowed_adopts_source_layer_without_provider(self, qapp) -> None:
        """源层变化后借用方共享同一层；自身不持有壁纸源/烘焙线程。"""
        source_widget = QWidget()
        borrowed_widget = QWidget()
        source = material_mod.MicaMaterial(source_widget, lazy=True)
        borrowed = material_mod.MicaMaterial(
            borrowed_widget, lazy=True, layer_source=source
        )
        try:
            layer, pixmap = _install_layer(source)
            source.layer_changed.emit()

            assert borrowed._borrowed is True
            assert borrowed._provider is None
            assert borrowed._worker_thread is None
            assert borrowed._layer is layer
            assert borrowed._layer_pixmap is pixmap
            assert borrowed._has_shown is True
        finally:
            borrowed.dispose()
            source.dispose()
            source_widget.deleteLater()
            borrowed_widget.deleteLater()

    def test_borrowed_refresh_forwards_to_source(self, qapp) -> None:
        """借用方 refresh 只请求源材质刷新，不自行烘焙。"""
        source_widget = QWidget()
        borrowed_widget = QWidget()
        source = material_mod.MicaMaterial(source_widget, lazy=True)
        borrowed = material_mod.MicaMaterial(
            borrowed_widget, lazy=True, layer_source=source
        )
        try:
            with mock.patch.object(
                material_mod.MicaMaterial, "refresh_async", autospec=True
            ) as refresh_async:
                borrowed.refresh()
            refresh_async.assert_called_once_with(source)
            assert borrowed._worker_thread is None
        finally:
            borrowed.dispose()
            source.dispose()
            source_widget.deleteLater()
            borrowed_widget.deleteLater()

    def test_borrowed_theme_update_does_not_mutate_source(self, qapp) -> None:
        """设置窗口主题刷新只更新自己的兜底底色，不反向改主窗口参数。"""
        source_widget = QWidget()
        borrowed_widget = QWidget()
        source = material_mod.MicaMaterial(source_widget, lazy=True)
        borrowed = material_mod.MicaMaterial(
            borrowed_widget, lazy=True, layer_source=source
        )
        try:
            _install_layer(source)
            source.layer_changed.emit()
            source_surface = QColor(source._surface_color)
            source_params = source._params

            borrowed.set_theme(
                "#FFFFFF",
                0.85,
                blur_radius=1,
                saturation=1.0,
                contrast=1.0,
                overlay_opacity=0.1,
            )

            assert source._surface_color == source_surface
            assert source._params == source_params
            assert borrowed._dark is False
            assert borrowed._layer is source._layer
        finally:
            borrowed.dispose()
            source.dispose()
            source_widget.deleteLater()
            borrowed_widget.deleteLater()

    def test_borrowed_dispose_keeps_source_alive(self, qapp) -> None:
        """设置窗口关闭只解除订阅；源材质仍归主窗口所有。"""
        source_widget = QWidget()
        borrowed_widget = QWidget()
        source = material_mod.MicaMaterial(source_widget, lazy=True)
        borrowed = material_mod.MicaMaterial(
            borrowed_widget, lazy=True, layer_source=source
        )
        try:
            _install_layer(source)
            source.layer_changed.emit()
            borrowed.dispose()

            assert borrowed._layer_source_ref is None
            assert source._disposed is False
            assert source._layer is not None
        finally:
            source.dispose()
            source_widget.deleteLater()
            borrowed_widget.deleteLater()


class _FakeHost(QWidget):
    """设置窗口测试用的最小宿主：背景模式 API + 真实源材质。"""

    background_mode_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._mode = "mica"
        self.source = material_mod.MicaMaterial(self, lazy=True)
        # 供 SettingsLayout.find_main_window 的鸭子类型识别；设置窗口自身
        # 保持 _mica_background=None，不会被误判为主窗口。
        self._mica_background = self

    def get_background_mode(self) -> str:
        return self._mode

    def _ensure_mica_material(self):
        return self.source


class TestSettingsWindowSharedBackground:
    """设置窗口按宿主背景模式显示/隐藏共享 Mica。"""

    def test_mica_mode_uses_cpu_shared_view(self, qapp, monkeypatch) -> None:
        """即使强制 GL 环境变量开启，设置窗口背景仍必须是 CPU 借用版。"""
        monkeypatch.setenv("FAF_USE_GL_MICA", "1")
        from freeassetfilter.ui.main_window import (
            MicaBackgroundWidgetCpu,
            MicaBackgroundWidgetGL,
            SettingsWindow,
        )

        host = _FakeHost()
        window = None
        try:
            window = SettingsWindow(host)
            view = window._mica_view
            assert view is not None
            assert isinstance(view, MicaBackgroundWidgetCpu)
            assert not isinstance(view, MicaBackgroundWidgetGL)
            assert view._mica is not None
            assert view._mica._borrowed is True
            assert view._mica._provider is None
            assert host.source._disposed is False
        finally:
            if window is not None:
                window.close()
                window.deleteLater()
            host.source.dispose()
            host.deleteLater()

    def test_follows_host_background_mode(self, qapp) -> None:
        """切到 image/minimalist 时隐藏共享层，切回 mica 时恢复。"""
        from freeassetfilter.ui.main_window import SettingsWindow

        host = _FakeHost()
        window = None
        try:
            window = SettingsWindow(host)
            view = window._mica_view
            assert view is not None
            assert view.isHidden() is False

            host._mode = "image"
            host.background_mode_changed.emit("image")
            assert view.isHidden() is True

            host._mode = "minimalist"
            host.background_mode_changed.emit("minimalist")
            assert view.isHidden() is True

            host._mode = "mica"
            host.background_mode_changed.emit("mica")
            assert view.isHidden() is False
        finally:
            if window is not None:
                window.close()
                window.deleteLater()
            host.source.dispose()
            host.deleteLater()

    def test_content_is_transparent_over_shared_layer(self, qapp) -> None:
        """内容容器必须透出共享层，而不是用 palette.Window 铺满整窗。"""
        from freeassetfilter.ui.main_window import SettingsWindow

        host = _FakeHost()
        window = None
        try:
            window = SettingsWindow(host)
            window.show()
            qapp.processEvents()

            layer = ViewportLayer(
                region=_REGION,
                width=_REGION[2] // 10,
                height=_REGION[3] // 10,
                win_size=_WIN,
            )
            pixmap = QPixmap(
                _REGION[2] // 10, _REGION[3] // 10
            )
            pixmap.fill(QColor(255, 0, 0))
            host.source._layer = layer
            host.source._layer_pixmap = pixmap
            host.source._layer_key = ("visual-test", "red")
            host.source._has_shown = True
            host.source._compositor.set_layer(layer, pixmap)
            host.source.layer_changed.emit()
            qapp.processEvents()

            image = window.grab().toImage()
            dpr = image.devicePixelRatio()
            # 侧边栏区域（x=20, y=200）应直接看到共享层红色，而非 tm.surface。
            color = image.pixelColor(int(20 * dpr), int(200 * dpr))
            assert color.red() > 200
            assert color.green() < 60
            assert color.blue() < 60
        finally:
            if window is not None:
                window.close()
                window.deleteLater()
            host.source.dispose()
            host.deleteLater()
