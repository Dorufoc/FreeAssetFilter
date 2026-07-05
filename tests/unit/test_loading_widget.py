# -*- coding: utf-8 -*-
"""
LoadingSpinner paint regressions.
"""

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap


def _render_spinner(spinner, image):
    painter = QPainter(image)
    spinner.render(painter, QPoint(0, 0))
    painter.end()


def test_loading_spinner_clears_previous_transparent_frame(qt_app):
    from freeassetfilter.widgets.loading_widget import LoadingSpinner

    spinner = LoadingSpinner(icon_size=48, dpi_scale=1.0)

    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.transparent)
    pixmap_painter = QPainter(pixmap)
    pixmap_painter.fillRect(QRect(22, 0, 4, 4), QColor("#0a59f7"))
    pixmap_painter.end()
    spinner._loading_pixmap = pixmap

    image = QImage(48, 48, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)

    spinner._rotation_value = 0
    _render_spinner(spinner, image)
    assert image.pixelColor(24, 2).alpha() > 0

    spinner._rotation_value = 90
    _render_spinner(spinner, image)
    assert image.pixelColor(24, 2).alpha() == 0


def test_loading_spinner_can_clear_previous_frame_with_solid_background(qt_app):
    from freeassetfilter.widgets.loading_widget import LoadingSpinner

    spinner = LoadingSpinner(icon_size=48, dpi_scale=1.0)
    spinner.set_background_color("#202020")

    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.transparent)
    pixmap_painter = QPainter(pixmap)
    pixmap_painter.fillRect(QRect(22, 0, 4, 4), QColor("#0a59f7"))
    pixmap_painter.end()
    spinner._loading_pixmap = pixmap

    image = QImage(48, 48, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)

    spinner._rotation_value = 0
    _render_spinner(spinner, image)
    assert image.pixelColor(24, 2).blue() > 200

    spinner._rotation_value = 90
    _render_spinner(spinner, image)
    assert image.pixelColor(24, 2) == QColor("#202020")
