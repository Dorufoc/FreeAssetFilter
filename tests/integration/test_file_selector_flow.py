#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件选择器流程集成测试
"""

import os
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt, QEventLoop


class TestFileLoadingProcess:
    def test_file_selector_initialization(self, file_selector):
        assert file_selector is not None
        assert hasattr(file_selector, 'files_scroll_area')

    def test_initial_path_exists(self, file_selector):
        assert hasattr(file_selector, 'current_path')
        assert file_selector.current_path is not None

    def test_load_valid_directory(self, file_selector, tmp_path):
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()
        file_selector._navigate_to_path(str(test_dir))
        assert file_selector.current_path == str(test_dir)


class TestFileFilteringByType:
    def test_filter_pattern_default(self, file_selector):
        assert file_selector.filter_pattern == "*"

    def test_filter_pattern_after_apply(self, file_selector):
        file_selector.filter_pattern = "*.txt"
        assert file_selector.filter_pattern == "*.txt"

    def test_filter_accepts_all_files(self, file_selector):
        file_selector.filter_pattern = "*"
        all_files = [
            {"name": "test.txt", "path": "/test.txt", "is_dir": False},
            {"name": "test.jpg", "path": "/test.jpg", "is_dir": False},
            {"name": "test.mp4", "path": "/test.mp4", "is_dir": False},
        ]
        filtered = file_selector._filter_files(all_files)
        assert len(filtered) == 3

    def test_filter_specific_extension(self, file_selector):
        file_selector.filter_pattern = "*.txt"
        all_files = [
            {"name": "test.txt", "path": "/test.txt", "is_dir": False},
            {"name": "test.jpg", "path": "/test.jpg", "is_dir": False},
        ]
        filtered = file_selector._filter_files(all_files)
        assert len(filtered) == 1
        assert filtered[0]["name"] == "test.txt"


class TestThumbnailGenerationFlow:
    def test_thumbnail_button_exists(self, file_selector):
        assert hasattr(file_selector, 'generate_thumbnails_btn')

    def test_clear_thumbnail_button_exists(self, file_selector):
        assert hasattr(file_selector, 'clear_thumbnails_btn')

    def test_thumbnail_thread_not_running_initially(self, file_selector):
        assert file_selector._thumbnail_thread is None

    def test_is_media_file_recognition(self, file_selector):
        from freeassetfilter.core.thumbnail_manager import get_thumbnail_manager
        thumbnail_manager = get_thumbnail_manager(file_selector.dpi_scale)
        assert thumbnail_manager.is_media_file("test.jpg")
        assert thumbnail_manager.is_media_file("test.png")
        assert thumbnail_manager.is_media_file("test.mp4")
        assert not thumbnail_manager.is_media_file("test.txt")


class TestCardRenderingPipeline:
    def test_file_model_exists(self, file_selector):
        assert file_selector.file_model is not None

    def test_card_delegate_exists(self, file_selector):
        assert file_selector.card_delegate is not None

    def test_scroll_area_exists(self, file_selector):
        scroll_area = file_selector.files_scroll_area
        assert scroll_area is not None

    def test_control_panel_exists(self, file_selector):
        assert hasattr(file_selector, 'control_panel')

    def test_status_bar_exists(self, file_selector):
        assert hasattr(file_selector, 'status_bar')

    def test_path_edit_exists(self, file_selector):
        assert hasattr(file_selector, 'path_edit')

    def test_drive_combo_exists(self, file_selector):
        assert hasattr(file_selector, 'drive_combo')
