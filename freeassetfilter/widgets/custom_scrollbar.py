#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

自定义滚动条组件
自绘渲染，与父控件的内部 QScrollBar 同步，支持悬停膨胀动画。
"""

from PySide6.QtCore import Qt, QEasingCurve, Property, QPropertyAnimation, QRectF, QSize, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QWidget


class FileScrollBar(QWidget):
    """
    自定义滚动条

    自绘渲染，位于视口右侧空白区域，与内部 QScrollBar 同步。
    支持鼠标悬浮平滑膨胀动画和拖拽滚动。
    """

    valueChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

        app = QApplication.instance()
        self._dpi_scale = getattr(app, 'dpi_scale_factor', 1.0) if app else 1.0

        self._minimum = 0
        self._maximum = 0
        self._value = 0
        self._page_step = 1
        self._single_step = 1
        self._dragging = False
        self._drag_start_y = 0
        self._drag_start_value = 0
        self._hovered = False

        self._bar_width_normal = max(3, int(4 * self._dpi_scale))
        self._bar_width_hovered = max(3, int(self._bar_width_normal * 1.5))
        self._bar_width = self._bar_width_normal
        self._thumb_min_height = max(20, int(20 * self._dpi_scale))
        self._thumb_max_ratio = 0.75
        self._padding = max(1, int(2 * self._dpi_scale))

        self._thumb_color = QColor("#666666")
        self._thumb_color.setAlpha(160)
        self._thumb_hover_color = QColor("#666666")
        self._thumb_hover_color.setAlpha(220)

        self._hover_animation = QPropertyAnimation(self, b"bar_width", self)
        self._hover_animation.setDuration(150)
        self._hover_animation.setEasingCurve(QEasingCurve.OutCubic)

        self.setMouseTracking(True)

    def _get_bar_width(self):
        return self._bar_width

    def _set_bar_width(self, w):
        self._bar_width = max(1, int(round(w)))
        self.update()

    bar_width = Property(int, _get_bar_width, _set_bar_width)

    def _start_hover_animation(self, hovered):
        target = self._bar_width_hovered if hovered else self._bar_width_normal
        if self._bar_width == target and self._hover_animation.state() != QPropertyAnimation.Running:
            return
        self._hover_animation.stop()
        self._hover_animation.setStartValue(self._bar_width)
        self._hover_animation.setEndValue(target)
        self._hover_animation.start()

    def configure(self, bar_width_normal=None, bar_width_hovered=None,
                  thumb_color=None, thumb_hover_color=None, padding=None):
        if bar_width_normal is not None:
            self._bar_width_normal = max(3, int(bar_width_normal))
            self._bar_width_hovered = max(3, int(self._bar_width_normal * 1.5))
            self._bar_width = self._bar_width_normal
        if bar_width_hovered is not None:
            self._bar_width_hovered = max(3, int(bar_width_hovered))
        if thumb_color is not None:
            self._thumb_color = QColor(thumb_color)
        if thumb_hover_color is not None:
            self._thumb_hover_color = QColor(thumb_hover_color)
        if padding is not None:
            self._padding = max(0, padding)
        self.update()

    def sizeHint(self):
        return QSize(self._bar_width + 2 * self._padding, 0)

    def set_padding(self, padding):
        self._padding = max(0, padding)
        self.update()

    def setRange(self, min_val, max_val):
        self._minimum = min_val
        self._maximum = max_val
        self.update()

    def setValue(self, value):
        new_value = max(self._minimum, min(self._maximum, value))
        if new_value != self._value:
            self._value = new_value
            self.update()

    def setPageStep(self, step):
        self._page_step = max(1, step)

    def setSingleStep(self, step):
        self._single_step = max(1, step)

    def _thumb_length(self):
        if self._maximum <= self._minimum:
            return 0
        total = self._maximum - self._minimum
        track_height = max(0, self.height() - 2 * self._padding)
        ratio = self._page_step / max(total, 1)
        return min(
            max(self._thumb_min_height, int(track_height * min(ratio, 1.0))),
            int(track_height * self._thumb_max_ratio)
        )

    def _value_to_y(self, value):
        if self._maximum <= self._minimum:
            return self._padding
        track_height = max(1, self.height() - 2 * self._padding)
        thumb_h = self._thumb_length()
        available = max(1, track_height - thumb_h)
        ratio = (value - self._minimum) / max(1, self._maximum - self._minimum)
        return self._padding + int(ratio * available)

    def _y_to_value(self, y):
        track_height = max(1, self.height() - 2 * self._padding)
        thumb_h = self._thumb_length()
        available = max(1, track_height - thumb_h)
        ratio = (y - self._padding) / available
        return int(self._minimum + ratio * (self._maximum - self._minimum))

    def _is_point_in_pill(self, px, py, rx, ry, rw, rh, radius):
        if px < rx or px > rx + rw or py < ry or py > ry + rh:
            return False
        if radius <= 0:
            return True
        if py < ry + radius:
            cx = rx + rw / 2
            return (px - cx) ** 2 + (py - (ry + radius)) ** 2 <= radius ** 2
        if py > ry + rh - radius:
            cx = rx + rw / 2
            return (px - cx) ** 2 + (py - (ry + rh - radius)) ** 2 <= radius ** 2
        return True

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        thumb_h = self._thumb_length()
        if thumb_h <= 0:
            painter.end()
            return

        thumb_y = self._value_to_y(self._value)
        radius = max(1, int(self._bar_width // 2))
        thumb_rect = QRectF(
            self.width() - self._padding - self._bar_width,
            thumb_y,
            self._bar_width,
            thumb_h,
        )
        if self._dragging or self._hovered:
            painter.setBrush(self._thumb_hover_color)
        else:
            painter.setBrush(self._thumb_color)
        painter.drawRoundedRect(thumb_rect, radius, radius)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        thumb_y = self._value_to_y(self._value)
        thumb_h = self._thumb_length()
        radius = max(1, int(self._bar_width // 2))

        if self._is_point_in_pill(
            event.position().x(), event.position().y(),
            self.width() - self._padding - self._bar_width,
            thumb_y,
            self._bar_width,
            thumb_h,
            radius,
        ):
            self._dragging = True
            self._drag_start_y = event.position().y()
            self._drag_start_value = self._value

    def mouseMoveEvent(self, event):
        if self._dragging:
            delta_y = event.position().y() - self._drag_start_y
            track_height = max(1, self.height() - 2 * self._padding)
            thumb_h = self._thumb_length()
            available = max(1, track_height - thumb_h)
            value_delta = int((delta_y / available) * (self._maximum - self._minimum))
            new_val = max(self._minimum, min(self._maximum, self._drag_start_value + value_delta))
            if new_val != self._value:
                self._value = new_val
                self.valueChanged.emit(self._value)
                self.update()
        else:
            thumb_y = self._value_to_y(self._value)
            thumb_h = self._thumb_length()
            radius = max(1, int(self._bar_width // 2))
            pos = event.position().toPoint()
            hovered = self._is_point_in_pill(
                pos.x(), pos.y(),
                self.width() - self._padding - self._bar_width,
                thumb_y,
                self._bar_width,
                thumb_h,
                radius,
            )
            if hovered != self._hovered:
                self._hovered = hovered
                if hovered:
                    self.setCursor(Qt.PointingHandCursor)
                else:
                    self.setCursor(Qt.ArrowCursor)
                self._start_hover_animation(self._hovered)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self.update()
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        thumb_y = self._value_to_y(self._value)
        thumb_h = self._thumb_length()
        radius = max(1, int(self._bar_width // 2))
        pos = event.position().toPoint()
        hovered = self._is_point_in_pill(
            pos.x(), pos.y(),
            self.width() - self._padding - self._bar_width,
            thumb_y,
            self._bar_width,
            thumb_h,
            radius,
        )
        if hovered != self._hovered:
            self._hovered = hovered
            if hovered:
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
            self._start_hover_animation(self._hovered)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.setCursor(Qt.ArrowCursor)
        self._start_hover_animation(False)
        super().leaveEvent(event)

    def wheelEvent(self, event):
        viewport = None
        p = self.parent()
        if p and hasattr(p, 'viewport'):
            viewport = p.viewport()
        if viewport:
            QApplication.sendEvent(viewport, event)
            event.accept()
        else:
            super().wheelEvent(event)
