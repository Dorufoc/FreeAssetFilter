# -*- coding: utf-8 -*-
"""
photo_viewer 组件测试
测试 freeassetfilter/components/photo_viewer.py 的 PhotoViewer 组件

测试覆盖：
1. PhotoViewer 创建与基本属性
2. set_file() 加载图片（返回 True, 无效路径返回 False）
3. ImageWidget 缩放功能（scale_factor, calculate_fit_scale, wheelEvent）
4. 全屏模式（进入/退出）
5. reset_view 视图重置（平移偏移清除, 缩放因子重算）
"""

import pytest
import os
from PySide6.QtCore import Qt, QPoint, QPointF, QSize
from PySide6.QtGui import QImage, QWheelEvent, QPixmap
from PySide6.QtTest import QTest


class TestPhotoViewerCreation:
    """测试 PhotoViewer 创建"""

    def test_photo_viewer_can_be_created(self, qapp):
        """测试 PhotoViewer 可以正常创建并初始化"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            assert viewer is not None
            assert viewer.image_widget is not None
            assert viewer.scroll_area is not None
            assert viewer.windowTitle() == "照片查看器"
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_photo_viewer_has_required_components(self, qapp):
        """测试 PhotoViewer 包含必需的子组件"""
        from freeassetfilter.components.photo_viewer import (
            PhotoViewer,
            ImageWidget,
        )
        from PySide6.QtWidgets import QScrollArea

        viewer = PhotoViewer()
        try:
            assert isinstance(viewer.scroll_area, QScrollArea)
            assert isinstance(viewer.image_widget, ImageWidget)
        finally:
            viewer.close()
            viewer.deleteLater()


class TestPhotoViewerSetFile:
    """测试 PhotoViewer.set_file 加载图片功能"""

    def test_set_file_returns_true(self, qapp, temp_image_file):
        """测试 set_file 对有效图片路径返回 True（启动异步加载）"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            png_path = temp_image_file[0]
            # set_file 返回 True 表示成功启动了异步加载
            result = viewer.set_file(png_path)
            assert result is True
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_set_file_with_invalid_path_returns_false(self, qapp):
        """测试 set_file 对无效路径返回 False"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            result = viewer.set_file("/nonexistent/path/image.png")
            assert result is False
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_set_file_with_empty_path_returns_false(self, qapp):
        """测试 set_file 对空路径返回 False"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            result = viewer.set_file("")
            assert result is False
        finally:
            viewer.close()
            viewer.deleteLater()


class TestImageWidgetDirectImage:
    """测试 ImageWidget 直接操作图片（不依赖异步加载）"""

    @staticmethod
    def _make_test_image():
        """创建一个 100x100 的 QImage 测试图片"""
        image = QImage(100, 100, QImage.Format_RGB32)
        image.fill(Qt.blue)
        return image

    def test_direct_set_image_updates_source(self, qapp):
        """测试直接设置图片后 source_image 正确更新"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            widget = viewer.image_widget
            image = self._make_test_image()

            widget.source_image = image
            widget._apply_rotation()

            assert widget.source_image is not None
            assert widget.source_image.isNull() is False
            assert widget.original_image is not None
            assert widget.original_image.width() == 100
            assert widget.original_image.height() == 100
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_rotate_clockwise_updates_rotation_steps(self, qapp):
        """测试顺时针旋转增加 rotation_steps"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            widget = viewer.image_widget
            image = self._make_test_image()
            widget.source_image = image
            widget._apply_rotation()

            assert widget.rotation_steps == 0
            widget.rotate_clockwise()
            assert widget.rotation_steps == 1
            widget.rotate_clockwise()
            assert widget.rotation_steps == 2
            widget.rotate_clockwise()
            assert widget.rotation_steps == 3
            widget.rotate_clockwise()
            assert widget.rotation_steps == 0  # wraps around
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_get_pixel_info_returns_defaults(self, qapp):
        """测试未加载图片时 get_pixel_info 返回默认值"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            info = viewer.image_widget.get_pixel_info()
            assert info['x'] == 0
            assert info['y'] == 0
            assert info['hex'] == '#000000'
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_reset_view_clears_pan_offset(self, qapp):
        """测试 reset_view 重置平移偏移为零"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            widget = viewer.image_widget
            widget.source_image = self._make_test_image()
            widget._apply_rotation()

            # 设置平移偏移
            widget.pan_offset = QPoint(50, 30)
            assert widget.pan_offset != QPoint(0, 0)

            # 重置视图
            widget.reset_view()

            assert widget.pan_offset == QPoint(0, 0)
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_is_valid_pixel_position_without_image(self, qapp):
        """测试无图片时 is_valid_pixel_position 返回 False"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            assert viewer.image_widget.is_valid_pixel_position(QPoint(0, 0)) is False
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_current_file_path_updates(self, qapp):
        """测试 current_file_path 正确更新"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            widget = viewer.image_widget
            image = self._make_test_image()
            test_path = "/test/path/image.png"

            widget._set_loaded_image(image, test_path)
            assert widget.current_file_path == test_path
        finally:
            viewer.close()
            viewer.deleteLater()


class TestPhotoViewerZoom:
    """测试缩放功能"""

    @staticmethod
    def _make_test_image():
        """创建一个 100x100 的 QImage 测试图片"""
        image = QImage(100, 100, QImage.Format_RGB32)
        image.fill(Qt.blue)
        return image

    def _setup_with_image(self, viewer):
        """为 viewer 的 image_widget 设置测试图片并渲染"""
        widget = viewer.image_widget
        widget.source_image = self._make_test_image()
        widget._apply_rotation()
        widget.calculate_fit_scale()
        widget.update_image()
        return widget

    def test_initial_scale_factor_is_one(self, qapp):
        """测试初始 scale_factor 为 1.0"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            assert viewer.image_widget.scale_factor == 1.0
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_calculate_fit_scale_returns_positive(self, qapp):
        """测试 calculate_fit_scale 返回正数缩放因子"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            viewer.show()
            qapp.processEvents()
            widget = self._setup_with_image(viewer)

            assert widget.scale_factor > 0
            # 100x100 图片在较大视口中应缩放到 <= 1.0
            assert widget.scale_factor <= 1.0
            # 不小于最小缩放限制
            assert widget.scale_factor >= widget.min_scale
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_scale_factor_can_be_increased_and_decreased(self, qapp):
        """测试 scale_factor 可以手动增减"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            widget = self._setup_with_image(viewer)
            original = widget.scale_factor

            # 放大
            widget.scale_factor = original * 2
            assert widget.scale_factor > original

            # 缩小回原值
            widget.scale_factor = original
            assert abs(widget.scale_factor - original) < 0.001
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_min_max_scale_bounds(self, qapp):
        """测试缩放因子限制在有效范围内"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            assert viewer.image_widget.min_scale == 0.1
            assert viewer.image_widget.max_scale == 10.0
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_wheel_event_zooms_in(self, qapp):
        """测试鼠标滚轮向上滚动时放大图片"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            viewer.show()
            qapp.processEvents()
            widget = self._setup_with_image(viewer)
            initial_scale = widget.scale_factor

            # 模拟滚轮向上（放大）
            wheel = QWheelEvent(
                QPointF(50, 50),
                QPointF(100, 100),
                QPoint(0, 0),
                QPoint(0, 120),
                Qt.NoButton,
                Qt.NoModifier,
                Qt.ScrollBegin,
                False,
            )
            widget.wheelEvent(wheel)

            assert widget.scale_factor > initial_scale
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_wheel_event_zooms_out(self, qapp):
        """测试鼠标滚轮向下滚动时缩小图片"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            viewer.show()
            qapp.processEvents()
            widget = self._setup_with_image(viewer)

            # 先放大确保有缩小空间
            widget.scale_factor = 2.0
            widget.update_image()
            initial_scale = widget.scale_factor

            # 模拟滚轮向下（缩小）
            wheel = QWheelEvent(
                QPointF(50, 50),
                QPointF(100, 100),
                QPoint(0, 0),
                QPoint(0, -120),
                Qt.NoButton,
                Qt.NoModifier,
                Qt.ScrollBegin,
                False,
            )
            widget.wheelEvent(wheel)

            assert widget.scale_factor < initial_scale
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_update_image_creates_pixmap(self, qapp):
        """测试 update_image 后 pixmap 被创建"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            widget = self._setup_with_image(viewer)

            assert widget.pixmap is not None
            assert widget.pixmap.isNull() is False
            assert widget.scaled_image is not None
            assert widget.scaled_image.isNull() is False
        finally:
            viewer.close()
            viewer.deleteLater()


class TestPhotoViewerFullScreen:
    """测试全屏模式"""

    def test_show_and_hide_fullscreen(self, qapp):
        """测试进入和退出全屏模式"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            viewer.show()
            qapp.processEvents()

            assert viewer.isVisible()
            assert not viewer.isFullScreen()

            # 进入全屏
            viewer.showFullScreen()
            qapp.processEvents()
            assert viewer.isFullScreen()

            # 退出全屏
            viewer.showNormal()
            qapp.processEvents()
            assert not viewer.isFullScreen()
        finally:
            viewer.close()
            viewer.deleteLater()


class TestPhotoViewerResetView:
    """测试视图重置功能"""

    @staticmethod
    def _make_test_image():
        image = QImage(100, 100, QImage.Format_RGB32)
        image.fill(Qt.blue)
        return image

    def test_reset_view_clears_pan_offset(self, qapp):
        """测试 PhotoViewer.reset_view 重置平移偏移"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            widget = viewer.image_widget
            widget.source_image = self._make_test_image()
            widget._apply_rotation()

            widget.pan_offset = QPoint(50, 30)
            assert widget.pan_offset != QPoint(0, 0)

            viewer.reset_view()

            assert widget.pan_offset == QPoint(0, 0)
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_reset_view_recalculates_scale(self, qapp):
        """测试 reset_view 重新计算缩放因子为自适应大小"""
        from freeassetfilter.components.photo_viewer import PhotoViewer

        viewer = PhotoViewer()
        try:
            viewer.show()
            qapp.processEvents()
            widget = viewer.image_widget
            widget.source_image = self._make_test_image()
            widget._apply_rotation()
            widget.calculate_fit_scale()
            widget.update_image()

            # 放大图片
            widget.scale_factor = 2.0
            widget.update_image()

            # 重置视图应重新计算为自适应缩放
            viewer.reset_view()

            # 100x100 图片在较大视口中 fit scale 应 <= 1.0
            assert widget.scale_factor <= 1.0
            assert widget.scale_factor > 0
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_image_widget_reset_view_clears_pan(self, qapp):
        """测试 ImageWidget.reset_view 清除平移偏移"""
        from freeassetfilter.components.photo_viewer import (
            PhotoViewer,
            ImageWidget,
        )

        viewer = PhotoViewer()
        try:
            widget = viewer.image_widget
            assert isinstance(widget, ImageWidget)

            widget.pan_offset = QPoint(100, 200)
            widget.reset_view()

            assert widget.pan_offset == QPoint(0, 0)
        finally:
            viewer.close()
            viewer.deleteLater()
