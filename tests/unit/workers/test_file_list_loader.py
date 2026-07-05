# -*- coding: utf-8 -*-
"""
Tests for FileListLoaderThread — background file scanning thread.

Covers:
  - Construction / parameter storage
  - ``run()`` with a normal directory (files, subdirs, hidden files)
  - ``run()`` with an empty directory
  - ``run()`` with a non-existent path → ``failed`` signal
  - ``run()`` with a symlink directory → ``failed`` signal
  - ``run()`` in "All" mode (drive/root enumeration)
  - PermissionError handling during stat
"""

import os
import sys
import pytest
from typing import Any, Dict, List

from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QSignalSpy

from freeassetfilter.core.workers.file_list_loader import FileListLoaderThread


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_files(tmp_path, names: List[str]) -> None:
    """Create zero-content files under *tmp_path*."""
    for n in names:
        (tmp_path / n).write_text("")


def _run_thread(thread: FileListLoaderThread, timeout_ms: int = 5000) -> FileListLoaderThread:
    """Start *thread*, wait for finish, and pump the Qt event loop.

    Pumping the event loop is necessary because ``loaded`` / ``failed``
    signals are emitted from inside ``QThread.run()`` and are queued for
    delivery on the main thread. Without ``processEvents()`` calls the
    ``QSignalSpy`` would not see them.

    Returns the thread for further inspection.
    """
    thread.start()
    finished = thread.wait(timeout_ms)
    # Deliver queued cross-thread signals to the spy.
    for _ in range(5):
        QCoreApplication.processEvents()
    assert finished, f"Thread did not finish within {timeout_ms}ms"
    return thread


# ===========================================================================
# TestFileListLoaderThreadConstruction
# ===========================================================================

class TestFileListLoaderThreadConstruction:
    """FileListLoaderThread creation and parameter storage."""

    def test_constructor_stores_current_path(self) -> None:
        """__init__ stores the *current_path* argument."""
        thread = FileListLoaderThread("/some/path")
        assert thread.current_path == "/some/path"

    def test_constructor_accepts_optional_parent(self, qapp) -> None:
        """__init__ accepts an optional parent QObject."""
        parent = qapp  # any QObject works
        thread = FileListLoaderThread("/p", parent=parent)
        assert thread.parent() is parent

    def test_default_parent_is_none(self) -> None:
        """When parent is omitted, parent() returns None."""
        thread = FileListLoaderThread("/p")
        assert thread.parent() is None


# ===========================================================================
# TestFileListLoaderThreadNormal
# ===========================================================================

class TestFileListLoaderThreadNormal:
    """run() — normal directory scanning."""

    def test_loads_all_files(self, qapp, tmp_path) -> None:
        """All visible files in a directory appear in the loaded signal."""
        _make_files(tmp_path, ["a.txt", "b.jpg", "c.png"])
        thread = FileListLoaderThread(str(tmp_path))
        spy = QSignalSpy(thread.loaded)
        _run_thread(thread)

        assert spy.count() == 1
        path, files = spy.at(0)
        assert path == str(tmp_path)
        assert {f["name"] for f in files} == {"a.txt", "b.jpg", "c.png"}

    def test_file_entry_has_expected_keys(self, qapp, tmp_path) -> None:
        """Each file entry dict contains all required keys."""
        (tmp_path / "hello.txt").write_text("hello")
        thread = FileListLoaderThread(str(tmp_path))
        spy = QSignalSpy(thread.loaded)
        _run_thread(thread)

        _, files = spy.at(0)
        entry = files[0]
        assert set(entry.keys()) == {
            "name", "path", "is_dir", "size",
            "modified", "created", "suffix",
        }

    def test_file_entry_values_match_disk(self, qapp, tmp_path) -> None:
        """File entry values reflect the actual on-disk file."""
        (tmp_path / "hello.txt").write_text("hello")
        thread = FileListLoaderThread(str(tmp_path))
        spy = QSignalSpy(thread.loaded)
        _run_thread(thread)

        _, files = spy.at(0)
        entry = files[0]
        assert entry["name"] == "hello.txt"
        assert entry["path"] == os.path.join(str(tmp_path), "hello.txt")
        assert entry["is_dir"] is False
        assert entry["size"] == 5  # "hello" is 5 bytes
        assert entry["suffix"] == "txt"

    def test_includes_subdirectories(self, qapp, tmp_path) -> None:
        """Sub-directories appear with is_dir=True and suffix empty."""
        _make_files(tmp_path, ["f.txt"])
        (tmp_path / "sub").mkdir()
        thread = FileListLoaderThread(str(tmp_path))
        spy = QSignalSpy(thread.loaded)
        _run_thread(thread)

        _, files = spy.at(0)
        dirs = [f for f in files if f["is_dir"]]
        regular = [f for f in files if not f["is_dir"]]
        assert len(dirs) == 1
        assert dirs[0]["name"] == "sub"
        assert dirs[0]["suffix"] == ""
        assert len(regular) == 1
        assert regular[0]["name"] == "f.txt"

    def test_skips_hidden_files(self, qapp, tmp_path) -> None:
        """Files whose name starts with '.' are excluded."""
        _make_files(tmp_path, ["visible.txt", ".hidden", ".gitkeep"])
        thread = FileListLoaderThread(str(tmp_path))
        spy = QSignalSpy(thread.loaded)
        _run_thread(thread)

        _, files = spy.at(0)
        names = {f["name"] for f in files}
        assert "visible.txt" in names
        assert ".hidden" not in names
        assert ".gitkeep" not in names

    @pytest.mark.skipif(sys.platform == "win32", reason="os.chmod permissions not reliable on Windows")
    def test_handles_permission_error_gracefully(self, qapp, tmp_path) -> None:
        """A file that raises PermissionError during stat is skipped."""
        _make_files(tmp_path, ["good.txt", "bad.txt", "also_good.txt"])

        bad_path = tmp_path / "bad.txt"
        os.chmod(str(bad_path), 0o000)

        thread = FileListLoaderThread(str(tmp_path))
        spy = QSignalSpy(thread.loaded)
        _run_thread(thread)

        _, files = spy.at(0)
        names = {f["name"] for f in files}
        assert "good.txt" in names
        assert "bad.txt" not in names  # skipped due to PermissionError
        assert "also_good.txt" in names

        # Restore permissions so tmp_path cleanup can delete the file.
        os.chmod(str(bad_path), 0o644)

    def test_suffix_is_lowercase_and_stripped(self, qapp, tmp_path) -> None:
        """suffix is lower-cased and the leading dot is removed."""
        (tmp_path / "Photo.JPG").write_text("")
        (tmp_path / "readme.TXT").write_text("")
        thread = FileListLoaderThread(str(tmp_path))
        spy = QSignalSpy(thread.loaded)
        _run_thread(thread)

        _, files = spy.at(0)
        suffixes = {f["name"]: f["suffix"] for f in files}
        assert suffixes == {"Photo.JPG": "jpg", "readme.TXT": "txt"}

    def test_modified_and_created_are_non_empty_strings(self, qapp, tmp_path) -> None:
        """modified and created fields contain ISO date strings."""
        (tmp_path / "test.txt").write_text("data")
        thread = FileListLoaderThread(str(tmp_path))
        spy = QSignalSpy(thread.loaded)
        _run_thread(thread)

        _, files = spy.at(0)
        entry = files[0]
        assert isinstance(entry["modified"], str)
        assert len(entry["modified"]) > 0
        assert isinstance(entry["created"], str)
        assert len(entry["created"]) > 0


# ===========================================================================
# TestFileListLoaderThreadEmpty
# ===========================================================================

class TestFileListLoaderThreadEmpty:
    """run() — empty directory."""

    def test_empty_directory_returns_empty_list(self, qapp, tmp_path) -> None:
        """An empty directory emits loaded with an empty file list."""
        thread = FileListLoaderThread(str(tmp_path))
        spy = QSignalSpy(thread.loaded)
        _run_thread(thread)

        assert spy.count() == 1
        path, files = spy.at(0)
        assert path == str(tmp_path)
        assert files == []


# ===========================================================================
# TestFileListLoaderThreadFailure
# ===========================================================================

class TestFileListLoaderThreadFailure:
    """run() — error paths."""

    def test_nonexistent_path_emits_failed(self, qapp, tmp_path) -> None:
        """A non-existent directory emits failed (not loaded)."""
        bad_path = str(tmp_path / "does_not_exist")
        thread = FileListLoaderThread(bad_path)
        spy_loaded = QSignalSpy(thread.loaded)
        spy_failed = QSignalSpy(thread.failed)
        _run_thread(thread)

        assert spy_loaded.count() == 0, "loaded must not be emitted on failure"
        assert spy_failed.count() == 1
        path, error = spy_failed.at(0)
        assert path == bad_path
        assert isinstance(error, str)
        assert len(error) > 0

    def test_symlink_directory_emits_failed(self, qapp, tmp_path) -> None:
        """A symlink pointing to a directory emits failed."""
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        link_path = tmp_path / "link_to_real"

        try:
            os.symlink(str(real_dir), str(link_path), target_is_directory=True)
        except (PermissionError, OSError, NotImplementedError):
            pytest.skip("Cannot create symlinks on this system")

        thread = FileListLoaderThread(str(link_path))
        spy_failed = QSignalSpy(thread.failed)
        _run_thread(thread)

        assert spy_failed.count() == 1
        path, error = spy_failed.at(0)
        assert path == str(link_path)
        # The Chinese error message from the source: "拒绝扫描符号链接目录"
        assert "符号链接" in error or "symlink" in error.lower()


# ===========================================================================
# TestFileListLoaderThreadAll
# ===========================================================================

class TestFileListLoaderThreadAll:
    """run() — "All" mode (drive / root enumeration)."""

    def test_all_mode_emits_loaded(self, qapp) -> None:
        """'All' mode emits the loaded signal."""
        thread = FileListLoaderThread("All")
        spy = QSignalSpy(thread.loaded)
        _run_thread(thread)

        assert spy.count() == 1
        path, files = spy.at(0)
        assert path == "All"

    def test_all_mode_on_windows_returns_drives(self, qapp) -> None:
        """On Windows 'All' should list logical drives (C:, D:, etc.)."""
        thread = FileListLoaderThread("All")
        spy = QSignalSpy(thread.loaded)
        _run_thread(thread)

        _, files = spy.at(0)
        if sys.platform == "win32":
            # At minimum C: should be present on any Windows system.
            names = {f["name"] for f in files}
            assert len(files) > 0
            assert "C:" in names, "Expected at least drive C: in drive list"
            # All entries should be marked as directories with no suffix.
            assert all(f["is_dir"] for f in files), "All drive entries must be directories"
            assert all(f["suffix"] == "" for f in files), "Drive entries must have empty suffix"
        else:
            # On non-Windows, "All" returns a single entry for "/".
            assert len(files) == 1
            assert files[0]["name"] == "/"
            assert files[0]["path"] == "/"
            assert files[0]["is_dir"] is True

    def test_all_mode_drive_entry_structure(self, qapp) -> None:
        """Each drive entry from 'All' mode has the expected keys."""
        thread = FileListLoaderThread("All")
        spy = QSignalSpy(thread.loaded)
        _run_thread(thread)

        _, files = spy.at(0)
        assert len(files) > 0, "At least one drive entry expected"
        entry = files[0]
        expected_keys = {
            "name", "path", "is_dir", "size",
            "modified", "created", "suffix",
        }
        assert set(entry.keys()) == expected_keys
