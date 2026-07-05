#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件存储池集成测试
"""

import os
import json
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt, QEventLoop, QTimer, QMimeData, QUrl


class TestFileDragAndDropHandling:
    def test_staging_pool_initialization(self, file_staging_pool):
        assert file_staging_pool is not None
        assert hasattr(file_staging_pool, 'items')
        assert isinstance(file_staging_pool.items, list)

    def test_accept_drops_enabled(self, file_staging_pool):
        assert file_staging_pool.acceptDrops()

    def test_add_file(self, file_staging_pool, sample_file_info):
        file_staging_pool.add_file(sample_file_info)
        assert len(file_staging_pool.items) == 1
        assert file_staging_pool.items[0]['path'] == sample_file_info['path']

    def test_add_duplicate_file(self, file_staging_pool, sample_file_info):
        file_staging_pool.add_file(sample_file_info)
        file_staging_pool.add_file(sample_file_info)
        assert len(file_staging_pool.items) == 1

    def test_add_folder(self, file_staging_pool, sample_dir_info):
        file_staging_pool.add_file(sample_dir_info)
        assert len(file_staging_pool.items) == 1
        assert file_staging_pool.items[0]['is_dir'] == True


class TestStateManagement:
    def test_items_list_empty_initially(self, file_staging_pool):
        assert len(file_staging_pool.items) == 0

    def test_add_multiple_files(self, file_staging_pool, tmp_path):
        files = []
        for i in range(3):
            f = tmp_path / f"test{i}.txt"
            f.write_text(f"content{i}")
            files.append({
                "name": f"test{i}.txt",
                "path": str(f),
                "is_dir": False,
                "size": f.stat().st_size,
                "modified": "",
                "created": "",
                "suffix": "txt",
            })
        for f in files:
            file_staging_pool.add_file(f)
        assert len(file_staging_pool.items) == 3

    def test_update_stats(self, file_staging_pool, sample_file_info):
        file_staging_pool.add_file(sample_file_info)
        file_staging_pool.update_stats()
        assert file_staging_pool.stats_label is not None

    def test_pool_view_exists(self, file_staging_pool):
        assert hasattr(file_staging_pool, 'pool_view')
        assert file_staging_pool.pool_view is not None

    def test_pool_model_exists(self, file_staging_pool):
        assert hasattr(file_staging_pool, 'pool_model')
        assert file_staging_pool.pool_model is not None


class TestCardOperations:
    def test_remove_file(self, file_staging_pool, sample_file_info):
        file_staging_pool.add_file(sample_file_info)
        assert len(file_staging_pool.items) == 1
        file_staging_pool.remove_file(sample_file_info['path'])
        assert len(file_staging_pool.items) == 0

    def test_clear_all_without_confirmation(self, file_staging_pool, tmp_path):
        for i in range(2):
            f = tmp_path / f"test{i}.txt"
            f.write_text(f"content{i}")
            file_staging_pool.add_file({
                "name": f"test{i}.txt",
                "path": str(f),
                "is_dir": False,
                "size": f.stat().st_size,
                "modified": "",
                "created": "",
                "suffix": "txt",
            })
        assert len(file_staging_pool.items) == 2
        file_staging_pool.clear_all_without_confirmation()
        assert len(file_staging_pool.items) == 0

    def test_rename_file(self, file_staging_pool, sample_file_info):
        file_staging_pool.add_file(sample_file_info)
        file_staging_pool._rename_file(sample_file_info['path'], "renamed.txt")
        updated = [item for item in file_staging_pool.items if item['name'] == "renamed.txt"]
        assert len(updated) == 1

    def test_clear_all_shows_confirmation(self, file_staging_pool):
        file_staging_pool.clear_all()

    def test_file_added_signal_emitted(self, file_staging_pool, sample_file_info, qtbot):
        with qtbot.waitSignal(file_staging_pool.file_added_to_pool, timeout=1000) as blocker:
            file_staging_pool.add_file(sample_file_info)
        assert blocker.args[0] is not None


class TestBackupSaveRestore:
    def test_backup_file_path_exists(self, file_staging_pool):
        assert hasattr(file_staging_pool, 'backup_file')
        assert file_staging_pool.backup_file is not None

    def test_save_backup(self, file_staging_pool, sample_file_info, tmp_path):
        file_staging_pool.backup_file = str(tmp_path / "backup.json")
        file_staging_pool.add_file(sample_file_info)
        file_staging_pool.save_backup("All")
        assert os.path.exists(file_staging_pool.backup_file)

    def test_load_backup(self, file_staging_pool, sample_file_info, tmp_path):
        backup_path = tmp_path / "backup.json"
        file_staging_pool.backup_file = str(backup_path)
        file_staging_pool.add_file(sample_file_info)
        file_staging_pool.save_backup("All")
        file_staging_pool.clear_all_without_confirmation()
        assert len(file_staging_pool.items) == 0
        file_staging_pool.load_backup()
        assert len(file_staging_pool.items) >= 1

    def test_flush_backup_save_now(self, file_staging_pool, sample_file_info, tmp_path):
        file_staging_pool.backup_file = str(tmp_path / "backup.json")
        file_staging_pool.add_file(sample_file_info)
        file_staging_pool.flush_backup_save_now("All")
        assert os.path.exists(file_staging_pool.backup_file)

    def test_backup_file_contains_correct_data(self, file_staging_pool, sample_file_info, tmp_path):
        file_staging_pool.backup_file = str(tmp_path / "backup.json")
        file_staging_pool.add_file(sample_file_info)
        file_staging_pool.save_backup("All")
        with open(file_staging_pool.backup_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert "items" in data
        assert "last_path" in data
        assert len(data["items"]) == 1

    def test_import_export_dialog_exists(self, file_staging_pool):
        assert hasattr(file_staging_pool, 'show_import_export_dialog')
        assert callable(file_staging_pool.show_import_export_dialog)

    def test_export_selected_files_exists(self, file_staging_pool):
        assert hasattr(file_staging_pool, 'export_selected_files')
        assert callable(file_staging_pool.export_selected_files)
