#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一预览器集成测试
"""

import os
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt, QEventLoop, QTimer


class TestPreviewRoutingLogic:
    def test_previewer_initialization(self, unified_previewer):
        assert unified_previewer is not None
        assert unified_previewer.current_file_info is None
        assert unified_previewer.current_preview_widget is None

    def test_text_file_routing(self, unified_previewer, sample_file_info):
        unified_previewer.set_file(sample_file_info)
        assert unified_previewer.current_file_info == sample_file_info

    def test_directory_file_routing(self, unified_previewer, sample_dir_info):
        unified_previewer.set_file(sample_dir_info)
        assert unified_previewer.current_file_info == sample_dir_info

    def test_video_file_routing(self, unified_previewer, tmp_path):
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"\x00" * 100)
        file_info = {
            "name": "test.mp4",
            "path": str(video_file),
            "is_dir": False,
            "size": 100,
            "modified": "",
            "created": "",
            "suffix": "mp4",
        }
        unified_previewer.set_file(file_info)
        assert unified_previewer.current_file_info["suffix"] == "mp4"

    def test_image_file_routing(self, unified_previewer, tmp_path):
        img_file = tmp_path / "test.jpg"
        img_file.write_bytes(b"\x00" * 100)
        file_info = {
            "name": "test.jpg",
            "path": str(img_file),
            "is_dir": False,
            "size": 100,
            "modified": "",
            "created": "",
            "suffix": "jpg",
        }
        unified_previewer.set_file(file_info)
        assert unified_previewer.current_file_info["suffix"] == "jpg"

    def test_pdf_file_routing(self, unified_previewer, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"\x00" * 100)
        file_info = {
            "name": "test.pdf",
            "path": str(pdf_file),
            "is_dir": False,
            "size": 100,
            "modified": "",
            "created": "",
            "suffix": "pdf",
        }
        unified_previewer.set_file(file_info)
        assert unified_previewer.current_file_info["suffix"] == "pdf"

    def test_font_file_routing(self, unified_previewer, tmp_path):
        font_file = tmp_path / "test.ttf"
        font_file.write_bytes(b"\x00" * 100)
        file_info = {
            "name": "test.ttf",
            "path": str(font_file),
            "is_dir": False,
            "size": 100,
            "modified": "",
            "created": "",
            "suffix": "ttf",
        }
        unified_previewer.set_file(file_info)
        assert unified_previewer.current_file_info["suffix"] == "ttf"

    def test_audio_file_routing(self, unified_previewer, tmp_path):
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"\x00" * 100)
        file_info = {
            "name": "test.mp3",
            "path": str(audio_file),
            "is_dir": False,
            "size": 100,
            "modified": "",
            "created": "",
            "suffix": "mp3",
        }
        unified_previewer.set_file(file_info)
        assert unified_previewer.current_file_info["suffix"] == "mp3"

    def test_archive_file_routing(self, unified_previewer, tmp_path):
        archive_file = tmp_path / "test.zip"
        archive_file.write_bytes(b"\x00" * 100)
        file_info = {
            "name": "test.zip",
            "path": str(archive_file),
            "is_dir": False,
            "size": 100,
            "modified": "",
            "created": "",
            "suffix": "zip",
        }
        unified_previewer.set_file(file_info)
        assert unified_previewer.current_file_info["suffix"] == "zip"


class TestSetFileMethod:
    def test_set_file_updates_current_file_info(self, unified_previewer, sample_file_info):
        unified_previewer.set_file(sample_file_info)
        assert unified_previewer.current_file_info is not None
        assert unified_previewer.current_file_info["name"] == "test.txt"

    def test_set_file_emits_preview_started_signal(self, unified_previewer, sample_file_info, qtbot):
        with qtbot.waitSignal(unified_previewer.preview_started, timeout=1000) as blocker:
            unified_previewer.set_file(sample_file_info)
        assert blocker.args[0] == sample_file_info

    def test_set_file_with_none(self, unified_previewer):
        unified_previewer.set_file(None)
        assert unified_previewer.current_file_info is None
        assert unified_previewer.current_preview_widget is None

    def test_set_file_update_file_info_viewer(self, unified_previewer, sample_file_info):
        unified_previewer.set_file(sample_file_info)
        assert unified_previewer.file_info_viewer.current_file is not None


class TestPreviewClearing:
    def test_clear_preview_removes_widget(self, unified_previewer, sample_file_info):
        unified_previewer.set_file(sample_file_info)
        unified_previewer._clear_preview()
        assert unified_previewer.current_preview_widget is None

    def test_clear_preview_emits_signal(self, unified_previewer, qtbot):
        with qtbot.waitSignal(unified_previewer.preview_cleared, timeout=1000):
            unified_previewer._clear_preview()

    def test_clear_preview_button_exists(self, unified_previewer):
        assert hasattr(unified_previewer, 'clear_preview_button')

    def test_clear_preview_button_click(self, unified_previewer, sample_file_info, qtbot):
        unified_previewer.set_file(sample_file_info)
        assert unified_previewer.current_file_info is not None
        unified_previewer.clear_preview_button.click()
        assert unified_previewer.current_file_info is None
        assert unified_previewer.current_preview_widget is None


class TestComponentSwitching:
    def test_switch_from_text_to_dir(self, unified_previewer, sample_file_info, sample_dir_info, tmp_path):
        unified_previewer.set_file(sample_file_info)
        assert unified_previewer.current_file_info is not None
        unified_previewer.is_loading_preview = False
        unified_previewer.set_file(sample_dir_info)
        assert unified_previewer.current_file_info is not None
        assert unified_previewer.current_file_info["is_dir"] == True

    def test_switch_between_same_type(self, unified_previewer, tmp_path):
        file1 = tmp_path / "file1.txt"
        file1.write_text("content1")
        file_info1 = {
            "name": "file1.txt",
            "path": str(file1),
            "is_dir": False,
            "size": 8,
            "modified": "",
            "created": "",
            "suffix": "txt",
        }
        file2 = tmp_path / "file2.txt"
        file2.write_text("content2")
        file_info2 = {
            "name": "file2.txt",
            "path": str(file2),
            "is_dir": False,
            "size": 8,
            "modified": "",
            "created": "",
            "suffix": "txt",
        }
        unified_previewer.set_file(file_info1)
        assert unified_previewer.current_file_info["name"] == "file1.txt"
        unified_previewer.is_loading_preview = False
        unified_previewer.set_file(file_info2)
        assert unified_previewer.current_file_info["name"] == "file2.txt"
