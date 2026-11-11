# -*- coding: utf-8 -*-
"""设置窗口过渡辅助组件的行为测试（窗口内快照 / 收缩归位 / 输入挡板）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "sopeek" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from components.window_transition import (  # noqa: E402
    SETTINGS_WINDOW_CLOSE_MS,
    SETTINGS_WINDOW_OPEN_MS,
    SETTINGS_WINDOW_OPEN_SCALE,
    SettingsWindowSnapshotLayer,
    TransitionInputBlocker,
)

pytestmark = pytest.mark.components


class TestTransitionConstants:
    """过渡参数保持「轻微缩放 + 快速完成」的产品约束。"""

    def test_start_scale_is_slightly_above_one(self) -> None:
        """起始比例必须 >1：收缩时四周才不会露出窗口底色。"""
        assert 1.0 < SETTINGS_WINDOW_OPEN_SCALE <= 1.15

    def test_durations_are_valid(self) -> None:
        """打开动画已开启且必须短促；关闭淡出仍可单独关闭。"""
        assert 100 <= SETTINGS_WINDOW_OPEN_MS <= 250
        assert 0 <= SETTINGS_WINDOW_CLOSE_MS <= 250


class TestSettingsWindowSnapshotLayer:
    """窗口内快照层：只缩放内容，窗口几何全程不动。"""

    def _snapshot(self) -> QPixmap:
        pixmap = QPixmap(160, 120)
        pixmap.fill(QColor(200, 40, 40))
        return pixmap

    def _layer(self, duration_ms: int = 20) -> SettingsWindowSnapshotLayer:
        layer = SettingsWindowSnapshotLayer(
            self._snapshot(), duration_ms=duration_ms
        )
        layer.resize(160, 120)
        return layer

    def test_scales_content_and_emits_finished(self, qapp: QApplication) -> None:
        layer = self._layer(1)
        finished: list[bool] = []
        layer.finished.connect(lambda: finished.append(True))
        layer.show()
        layer.start()
        QTest.qWait(80)
        assert layer.get_progress() == 1.0
        assert finished == [True]
        # 末帧铺满：中心与四角都是快照内容，没有露底色。
        image = layer.grab().toImage()
        assert image.pixelColor(80, 60).red() > 150
        assert image.pixelColor(2, 2).red() > 150

        layer.close()
        layer.deleteLater()
        qapp.processEvents()

    def test_start_frame_covers_whole_client_area(
        self, qapp: QApplication
    ) -> None:
        """进度 0（104%）时内容仍覆盖整块客户区，不露窗口底色。"""
        layer = self._layer(20)
        layer.set_progress(0.0)
        layer.show()
        qapp.processEvents()
        image = layer.grab().toImage()
        # 四角都必须是快照内容（不透明红），否则收缩时会看到窗口底色。
        for x, y in ((1, 1), (158, 1), (1, 118), (158, 118)):
            corner = image.pixelColor(x, y)
            assert corner.alpha() == 255
            assert corner.red() > 150

        layer.finish_now()
        layer.close()
        layer.deleteLater()
        qapp.processEvents()

    def test_honors_source_rect_for_client_crop(
        self, qapp: QApplication
    ) -> None:
        """source 矩形按设备像素裁剪，用于对齐 Win32 可见客户区。"""
        pixmap = QPixmap(200, 160)
        pixmap.fill(QColor(200, 40, 40))
        layer = SettingsWindowSnapshotLayer(
            pixmap, QRectF(2.0, 2.0, 160.0, 120.0)
        )
        layer.resize(160, 120)
        layer.set_progress(1.0)
        layer.show()
        qapp.processEvents()
        image = layer.grab().toImage()
        assert image.pixelColor(80, 60).red() > 150
        layer.close()
        layer.deleteLater()
        qapp.processEvents()

    def test_takes_focus_to_block_input(self, qapp: QApplication) -> None:
        """过渡期间快照层接管焦点，避免误触真实设置项。"""
        layer = self._layer()
        assert layer.focusPolicy() == Qt.StrongFocus
        layer.close()
        layer.deleteLater()
        qapp.processEvents()


class TestTransitionInputBlocker:
    """过渡挡板不绘制像素、可接管输入焦点。"""

    def test_paints_nothing_and_takes_focus(self, qapp: QApplication) -> None:
        """挡板可拦截鼠标/键盘，但 grab() 全透明。"""
        host = QWidget()
        host.resize(100, 100)
        blocker = TransitionInputBlocker(host)
        blocker.resize(100, 100)

        assert blocker.focusPolicy() == Qt.StrongFocus
        image = blocker.grab().toImage()
        assert image.pixelColor(50, 50).alpha() == 0

        blocker.deleteLater()
        host.deleteLater()
        qapp.processEvents()
