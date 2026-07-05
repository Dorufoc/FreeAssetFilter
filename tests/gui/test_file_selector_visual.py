#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Visual tests for FileSelector card layout rendering.
"""

import os
import sys
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt, QSize

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.qt_capture import capture_widget


class TestFileSelectorVisual:
    """Test file selector card layout rendering and screenshot capture."""

    def test_file_block_card_render(self, qapp, screenshots_dir):
        """Test that FileBlockCard renders correctly with different states."""
        from freeassetfilter.widgets.file_block_card import FileBlockCard

        file_info = {
            "path": os.path.join("C:", "test", "sample.txt"),
            "name": "sample.txt",
            "is_dir": False,
            "size": 1024,
            "suffix": "txt",
        }
        card = FileBlockCard(file_info=file_info, dpi_scale=1.0)

        output_path = os.path.join(screenshots_dir, "file_block_card_default.png")
        pixmap = capture_widget(card, output_path=output_path)

        assert not pixmap.isNull(), "Card screenshot should not be null"
        assert pixmap.width() > 0, "Card should have positive width"
        assert pixmap.height() > 0, "Card should have positive height"

        card.deleteLater()

    def test_file_block_card_selected_state(self, qapp, screenshots_dir):
        """Test FileBlockCard selected state rendering."""
        from freeassetfilter.widgets.file_block_card import FileBlockCard

        file_info = {
            "path": os.path.join("C:", "test", "document.pdf"),
            "name": "document.pdf",
            "is_dir": False,
            "size": 204800,
            "suffix": "pdf",
        }
        card = FileBlockCard(file_info=file_info, dpi_scale=1.0)
        card.set_selected(True)

        output_path = os.path.join(screenshots_dir, "file_block_card_selected.png")
        pixmap = capture_widget(card, output_path=output_path)

        assert not pixmap.isNull(), "Selected card screenshot should not be null"
        assert pixmap.width() > 0
        assert pixmap.height() > 0

        card.deleteLater()

    def test_file_horizontal_card_render(self, qapp, screenshots_dir):
        """Test CustomFileHorizontalCard rendering."""
        from freeassetfilter.widgets.file_horizontal_card import CustomFileHorizontalCard

        card = CustomFileHorizontalCard(
            file_path=os.path.join("C:", "test", "folder"),
            display_name="Test Folder",
            enable_multiselect=False,
        )

        output_path = os.path.join(screenshots_dir, "file_horizontal_card_default.png")
        pixmap = capture_widget(card, output_path=output_path)

        assert not pixmap.isNull(), "Horizontal card screenshot should not be null"
        assert pixmap.width() > 0
        assert pixmap.height() > 0

        card.deleteLater()

    def test_card_alignment_consistency(self, qapp, screenshots_dir):
        """Test that multiple cards render with consistent alignment."""
        from freeassetfilter.widgets.file_block_card import FileBlockCard

        cards = []
        test_files = [
            {"path": os.path.join("C:", "test", "file1.jpg"), "name": "file1.jpg", "is_dir": False, "size": 500000, "suffix": "jpg"},
            {"path": os.path.join("C:", "test", "file2.mp4"), "name": "file2.mp4", "is_dir": False, "size": 10000000, "suffix": "mp4"},
            {"path": os.path.join("C:", "test", "file3.docx"), "name": "file3.docx", "is_dir": False, "size": 30000, "suffix": "docx"},
        ]

        for file_info in test_files:
            card = FileBlockCard(file_info=file_info, dpi_scale=1.0)
            cards.append(card)

        sizes = []
        for i, card in enumerate(cards):
            output_path = os.path.join(screenshots_dir, f"card_alignment_{i}.png")
            pixmap = capture_widget(card, output_path=output_path)
            sizes.append((pixmap.width(), pixmap.height()))

        for width, height in sizes:
            assert width == sizes[0][0], f"All cards should have same width: {width} != {sizes[0][0]}"
            assert height == sizes[0][1], f"All cards should have same height: {height} != {sizes[0][1]}"

        for card in cards:
            card.deleteLater()

    def test_screenshot_output_directory(self, screenshots_dir):
        """Test that screenshot output directory exists and is writable."""
        assert os.path.isdir(screenshots_dir), "Screenshots directory should exist"

        test_file = os.path.join(screenshots_dir, "test_write.txt")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
