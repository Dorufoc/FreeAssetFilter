#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Visual tests for UnifiedPreviewer placeholder display.
"""

import os
import sys
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.qt_capture import capture_widget


class TestPreviewerVisual:
    """Test previewer placeholder display and screenshot verification."""

    def test_unified_previewer_placeholder(self, qapp, screenshots_dir):
        """Test that UnifiedPreviewer shows placeholder when no file is selected."""
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer

        previewer = UnifiedPreviewer()
        previewer.setMinimumSize(400, 300)

        output_path = os.path.join(screenshots_dir, "previewer_placeholder.png")
        pixmap = capture_widget(previewer, output_path=output_path, size=(400, 300))

        assert not pixmap.isNull(), "Previewer screenshot should not be null"
        assert pixmap.width() >= 400, "Previewer should have minimum width"
        assert pixmap.height() >= 300, "Previewer should have minimum height"

        previewer.deleteLater()

    def test_file_info_previewer_render(self, qapp, screenshots_dir):
        """Test FileInfoPreviewer initializes correctly."""
        from freeassetfilter.components.file_info_previewer import FileInfoPreviewer

        previewer = FileInfoPreviewer()

        assert hasattr(previewer, 'current_file'), "FileInfoPreviewer should have current_file attribute"

    def test_previewer_screenshot_not_empty(self, qapp, screenshots_dir):
        """Test that previewer screenshot contains visible content."""
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer

        previewer = UnifiedPreviewer()

        output_path = os.path.join(screenshots_dir, "previewer_content_check.png")
        pixmap = capture_widget(previewer, output_path=output_path, size=(400, 300))

        image = pixmap.toImage()
        has_content = False
        for y in range(image.height()):
            for x in range(image.width()):
                pixel = image.pixel(x, y)
                if pixel != 0:
                    has_content = True
                    break
            if has_content:
                break

        assert has_content, "Previewer screenshot should contain visible content"

        previewer.deleteLater()
