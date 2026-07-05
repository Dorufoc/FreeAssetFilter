#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Visual tests for LoadingSpinner animation.
"""

import os
import sys
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QEvent

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.qt_capture import capture_widget


class TestLoadingAnimation:
    """Test loading spinner visual and animation frame capture."""

    def test_loading_spinner_render(self, qapp, screenshots_dir):
        """Test that LoadingSpinner renders correctly."""
        from freeassetfilter.widgets.loading_widget import LoadingSpinner

        spinner = LoadingSpinner(icon_size=48, dpi_scale=1.0)

        output_path = os.path.join(screenshots_dir, "loading_spinner_default.png")
        pixmap = capture_widget(spinner, output_path=output_path)

        assert not pixmap.isNull(), "LoadingSpinner screenshot should not be null"
        assert pixmap.width() > 0
        assert pixmap.height() > 0

        spinner.deleteLater()

    def test_loading_spinner_start_animation(self, qapp, screenshots_dir):
        """Test LoadingSpinner animation after start."""
        from freeassetfilter.widgets.loading_widget import LoadingSpinner

        spinner = LoadingSpinner(icon_size=64, dpi_scale=1.0)
        spinner.start()

        qapp.processEvents()

        output_path = os.path.join(screenshots_dir, "loading_spinner_running.png")
        pixmap = capture_widget(spinner, output_path=output_path)

        assert not pixmap.isNull(), "Running spinner screenshot should not be null"
        assert spinner.is_running(), "Spinner should be running after start()"

        spinner.stop()
        spinner.deleteLater()

    def test_loading_spinner_stop_animation(self, qapp):
        """Test LoadingSpinner stops correctly."""
        from freeassetfilter.widgets.loading_widget import LoadingSpinner

        spinner = LoadingSpinner(icon_size=48, dpi_scale=1.0)
        spinner.start()
        assert spinner.is_running()

        spinner.stop()
        assert not spinner.is_running()

        spinner.deleteLater()

    def test_loading_spinner_different_sizes(self, qapp, screenshots_dir):
        """Test LoadingSpinner renders correctly at different sizes."""
        from freeassetfilter.widgets.loading_widget import LoadingSpinner

        sizes = [32, 48, 64, 80]
        spinners = []

        for size in sizes:
            spinner = LoadingSpinner(icon_size=size, dpi_scale=1.0)
            spinners.append((size, spinner))

            output_path = os.path.join(screenshots_dir, f"loading_spinner_size_{size}.png")
            pixmap = capture_widget(spinner, output_path=output_path)

            assert not pixmap.isNull(), f"Spinner size {size} screenshot should not be null"
            assert pixmap.width() == size
            assert pixmap.height() == size

        for _, spinner in spinners:
            spinner.deleteLater()

    def test_loading_spinner_animation_frames(self, qapp, screenshots_dir):
        """Test capturing multiple animation frames."""
        from freeassetfilter.widgets.loading_widget import LoadingSpinner

        spinner = LoadingSpinner(icon_size=64, dpi_scale=1.0)
        spinner.start()

        frames_dir = os.path.join(screenshots_dir, "spinner_frames")
        os.makedirs(frames_dir, exist_ok=True)

        frame_count = 5
        frames_captured = 0

        for i in range(frame_count):
            qapp.processEvents()
            QTimer.singleShot(50, qapp.processEvents)

            output_path = os.path.join(frames_dir, f"frame_{i:03d}.png")
            pixmap = capture_widget(spinner, output_path=output_path)

            assert not pixmap.isNull(), f"Frame {i} should not be null"
            frames_captured += 1

        assert frames_captured == frame_count, f"Should capture {frame_count} frames"

        spinner.stop()
        spinner.deleteLater()

    def test_loading_spinner_svg_icon_loaded(self, qapp):
        """Test that LoadingSpinner successfully loads SVG icon."""
        from freeassetfilter.widgets.loading_widget import LoadingSpinner

        spinner = LoadingSpinner(icon_size=48, dpi_scale=1.0)

        assert not spinner._loading_pixmap.isNull(), "SVG icon should be loaded"

        spinner.deleteLater()

    def test_loading_spinner_set_accent_color(self, qapp, screenshots_dir):
        """Test LoadingSpinner accent color change."""
        from freeassetfilter.widgets.loading_widget import LoadingSpinner

        spinner = LoadingSpinner(icon_size=48, dpi_scale=1.0)

        original_color = spinner._accent_color
        spinner.set_accent_color("#FF0000")

        assert spinner._accent_color != original_color

        output_path = os.path.join(screenshots_dir, "loading_spinner_red_accent.png")
        pixmap = capture_widget(spinner, output_path=output_path)

        assert not pixmap.isNull()

        spinner.deleteLater()
