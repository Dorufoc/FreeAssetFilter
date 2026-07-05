# -*- coding: utf-8 -*-
"""Regression tests for file_staging_pool business logic.

Tests core business operations:
- FileStagingPoolListModel.add_file / remove_file / has_path
- FileStagingPool._calculate_md5_sync
- FileStagingPool.get_directory_space
"""

import hashlib
import os

import pytest


# ── Model-level tests: add_file, remove_file, has_path ──────────────


class TestFileStagingPoolListModel:
    """Tests for FileStagingPoolListModel add/remove/has_path operations."""

    @pytest.fixture
    def model(self, qapp):  # noqa: ARG002 - qapp ensures QApplication exists
        """Create a fresh model instance for each test."""
        from freeassetfilter.widgets.file_staging_pool_model import (
            FileStagingPoolListModel,
        )

        return FileStagingPoolListModel()

    @pytest.fixture
    def temp_file(self, tmp_path):
        """Create a temporary file on disk."""
        f = tmp_path / "test.txt"
        f.write_text("test content")
        return str(f)

    # ── add_file ───────────────────────────────────────────────────

    def test_add_file_returns_true(self, model, temp_file):
        """add_file returns True for a new file."""
        result = model.add_file({"path": temp_file, "name": "test.txt"})
        assert result is True

    def test_add_file_exists_in_model(self, model, temp_file):
        """After add_file, has_path returns True and rowCount increases."""
        model.add_file({"path": temp_file, "name": "test.txt"})
        assert model.has_path(temp_file) is True
        assert model.rowCount() == 1

    def test_add_duplicate_returns_false(self, model, temp_file):
        """Adding the same file path twice returns False for the second call."""
        file_info = {"path": temp_file, "name": "test.txt"}
        assert model.add_file(file_info) is True
        assert model.add_file(file_info) is False

    def test_add_duplicate_does_not_increase_count(self, model, temp_file):
        """Duplicate add keeps rowCount at 1 (no phantom rows)."""
        file_info = {"path": temp_file, "name": "test.txt"}
        model.add_file(file_info)
        model.add_file(file_info)  # duplicate, should be ignored
        assert model.rowCount() == 1

    def test_add_multiple_files_increases_count(self, model, tmp_path):
        """Adding distinct files increases rowCount appropriately."""
        for i in range(3):
            f = tmp_path / f"test_{i}.txt"
            f.write_text(f"content {i}")
            model.add_file({"path": str(f), "name": f"test_{i}.txt"})
        assert model.rowCount() == 3

    def test_add_file_non_existent_path_still_adds(self, model, tmp_path):
        """A file that does not exist on disk is still added to the model (marked missing)."""
        path = str(tmp_path / "nonexistent.txt")
        result = model.add_file({"path": path, "name": "nonexistent.txt"})
        assert result is True
        assert model.has_path(path) is True
        info = model.get_file_info_by_path(path)
        assert info.get("is_missing") is True

    def test_add_file_empty_path_adds(self, model):
        """An empty-path entry is accepted (empty keys skip indexing, not rejected)."""
        result = model.add_file({"path": "", "name": "unnamed"})
        assert result is True

    # ── remove_file ────────────────────────────────────────────────

    def test_remove_existing_returns_info_dict(self, model, temp_file):
        """remove_file on an existing file returns its info dict."""
        model.add_file({"path": temp_file, "name": "test.txt"})
        result = model.remove_file(temp_file)
        assert isinstance(result, dict)
        assert result.get("name") == "test.txt"
        assert result.get("is_removing") is True

    def test_remove_nonexistent_returns_empty_dict(self, model):
        """remove_file on a file not in the model returns {}."""
        result = model.remove_file("/nonexistent/path/file.txt")
        assert result == {}

    def test_remove_twice_returns_empty_dict(self, model, temp_file):
        """Second remove_file call for the same path returns {} (already flagged)."""
        file_info = {"path": temp_file, "name": "test.txt"}
        model.add_file(file_info)
        first = model.remove_file(temp_file)
        assert first != {}
        second = model.remove_file(temp_file)
        assert second == {}

    # ── has_path ───────────────────────────────────────────────────

    def test_has_path_true_after_add(self, model, temp_file):
        """has_path returns True for a file that was just added."""
        model.add_file({"path": temp_file, "name": "test.txt"})
        assert model.has_path(temp_file) is True

    def test_has_path_false_before_add(self, model):
        """has_path returns False for a path that was never added."""
        assert model.has_path("/some/random/path.txt") is False

    def test_has_path_still_true_after_remove_mark(self, model, temp_file):
        """After remove_file the item is still in the model (just flagged), so has_path is True."""
        model.add_file({"path": temp_file, "name": "test.txt"})
        model.remove_file(temp_file)
        assert model.has_path(temp_file) is True


# ── FileStagingPool business methods: MD5 calculation ───────────────


class TestMD5Calculation:
    """Tests for FileStagingPool._calculate_md5_sync."""

    # Note: _calculate_md5_sync is defined twice in file_staging_pool.py;
    # the second definition (line 1375) shadows the first; both have the
    # same implementation.  Tests here exercise whichever is live.

    def test_md5_valid_file(self, file_staging_pool, tmp_path):
        """MD5 of a valid file matches hashlib.md5 reference."""
        f = tmp_path / "md5_test.dat"
        content = b"test content for md5 validation"
        f.write_bytes(content)
        expected = hashlib.md5(content).hexdigest()
        result = file_staging_pool._calculate_md5_sync(str(f))
        assert result == expected

    def test_md5_empty_file(self, file_staging_pool, tmp_path):
        """MD5 of an empty file matches the well-known empty-string hash."""
        f = tmp_path / "empty.txt"
        f.write_text("")
        expected = hashlib.md5(b"").hexdigest()
        result = file_staging_pool._calculate_md5_sync(str(f))
        assert result == expected

    def test_md5_binary_content(self, file_staging_pool, tmp_path):
        """MD5 of binary content (all 256 byte values) is computed correctly."""
        f = tmp_path / "binary.dat"
        content = bytes(range(256))
        f.write_bytes(content)
        expected = hashlib.md5(content).hexdigest()
        result = file_staging_pool._calculate_md5_sync(str(f))
        assert result == expected

    def test_md5_nonexistent_file_returns_none(self, file_staging_pool):
        """_calculate_md5_sync returns None when the file does not exist."""
        result = file_staging_pool._calculate_md5_sync(
            "/nonexistent_md5_test_file_xyz.dat"
        )
        assert result is None

    def test_md5_large_file(self, file_staging_pool, tmp_path):
        """MD5 of a ~1 MB file is computed without error (streaming chunk path)."""
        f = tmp_path / "large.bin"
        # 1 MB of pseudo-random-ish data
        content = os.urandom(1024 * 1024)
        f.write_bytes(content)
        expected = hashlib.md5(content).hexdigest()
        result = file_staging_pool._calculate_md5_sync(str(f))
        assert result == expected


# ── FileStagingPool business methods: get_directory_space ───────────


class TestGetDirectorySpace:
    """Tests for FileStagingPool.get_directory_space."""

    def test_valid_directory_returns_values(self, file_staging_pool, tmp_path):
        """get_directory_space returns (total_bytes, free_bytes) with total > 0."""
        total, free = file_staging_pool.get_directory_space(str(tmp_path))
        assert total is not None
        assert free is not None
        assert isinstance(total, int)
        assert isinstance(free, int)
        assert total > 0

    def test_free_not_exceeds_total(self, file_staging_pool, tmp_path):
        """Constrains that free <= total (no more space than exists)."""
        total, free = file_staging_pool.get_directory_space(str(tmp_path))
        assert free <= total

    def test_invalid_directory_handled_gracefully(self, file_staging_pool, tmp_path):
        """get_directory_space does not crash on a non-existent directory.

        Expected return:
        - Windows (ctypes): (0, 0)  — the API fails silently, zero-initialised.
        - POSIX (statvfs):  (None, None) — exception caught.
        Either is acceptable graceful handling.
        """
        total, free = file_staging_pool.get_directory_space(
            str(tmp_path / "nonexistent_dir_xyz_12345")
        )
        assert isinstance(total, int | type(None))
        assert isinstance(free, int | type(None))
        # Both-None and both-zero are graceful; anything else is surprising
        assert (total is None and free is None) or (total == 0 and free == 0)

    def test_empty_string_handled_gracefully(self, file_staging_pool):
        """get_directory_space with an empty string does not crash."""
        total, free = file_staging_pool.get_directory_space("")
        assert isinstance(total, int | type(None))
        assert isinstance(free, int | type(None))
        assert (total is None and free is None) or (total == 0 and free == 0)

    def test_root_directory_returns_values(self, file_staging_pool):
        """get_directory_space for the system root succeeds (platform-agnostic)."""
        root = os.path.abspath(os.sep)  # e.g. C:\\ on Windows, / on POSIX
        total, free = file_staging_pool.get_directory_space(root)
        assert total is not None
        assert free is not None
        assert isinstance(total, int)
        assert isinstance(free, int)
        assert total > 0
        assert free > 0
