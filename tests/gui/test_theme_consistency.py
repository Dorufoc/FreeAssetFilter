#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Visual tests for theme switching color consistency.
"""

import os
import sys
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.qt_capture import capture_widget


class TestThemeConsistency:
    """Test theme switching color consistency and screenshot before/after comparison."""

    def test_theme_manager_initialization(self, qapp):
        """Test that ThemeManager initializes correctly."""
        from freeassetfilter.core.theme_manager import ThemeManager

        tm = ThemeManager()
        colors = tm.get_theme_colors()

        assert "accent_color" in colors
        assert "secondary_color" in colors
        assert "normal_color" in colors
        assert "auxiliary_color" in colors
        assert "base_color" in colors

    def test_theme_toggle_color_consistency(self, qapp):
        """Test that theme toggle produces consistent color sets."""
        from freeassetfilter.core.theme_manager import ThemeManager

        tm = ThemeManager()

        initial_colors = tm.get_theme_colors()

        tm.toggle_theme(is_dark=True)
        dark_colors = tm.get_theme_colors()

        tm.toggle_theme(is_dark=False)
        light_colors = tm.get_theme_colors()

        assert set(initial_colors.keys()) == set(dark_colors.keys())
        assert set(initial_colors.keys()) == set(light_colors.keys())

    def test_dark_theme_colors_are_different(self, qapp):
        """Test that dark theme colors differ from light theme."""
        from freeassetfilter.core.theme_manager import ThemeManager

        tm = ThemeManager()

        tm.toggle_theme(is_dark=False)
        light_colors = tm.get_theme_colors()

        tm.toggle_theme(is_dark=True)
        dark_colors = tm.get_theme_colors()

        assert dark_colors["base_color"] != light_colors["base_color"], \
            "Base color should differ between dark and light themes"

        tm.toggle_theme(is_dark=False)

    def test_widget_theme_colors_valid(self, qapp):
        """Test that widget theme colors are valid hex values."""
        from freeassetfilter.core.theme_manager import ThemeManager

        tm = ThemeManager()
        colors = tm.get_theme_colors()

        for key, value in colors.items():
            assert value.startswith("#"), f"Color {key} should be hex format: {value}"
            assert len(value) == 7, f"Color {key} should be 7 chars: {value}"
            QColor(value).isValid(), f"Color {key} should be valid QColor"

    def test_previewer_theme_update(self, qapp, screenshots_dir):
        """Test that UnifiedPreviewer updates theme consistently."""
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer

        previewer = UnifiedPreviewer()

        previewer.update_theme()

        output_path = os.path.join(screenshots_dir, "previewer_theme_update.png")
        pixmap = capture_widget(previewer, output_path=output_path, size=(400, 300))

        assert not pixmap.isNull(), "Previewer theme update screenshot should not be null"

        previewer.deleteLater()
