#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pytest fixtures for Qt GUI visual tests.
"""

import os
import sys
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "screenshots")


@pytest.fixture(scope="session")
def qapp():
    """Create a shared QApplication instance for the test session."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app.setProperty("test_mode", True)
        app.dpi_scale_factor = 1.0
        app.global_font = QFont("Microsoft YaHei UI", 9)
    yield app


@pytest.fixture(scope="session")
def screenshots_dir():
    """Return the screenshots output directory path."""
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    return SCREENSHOTS_DIR


@pytest.fixture(autouse=True)
def cleanup_after_test(qapp):
    """Process pending events after each test."""
    yield
    qapp.processEvents()
