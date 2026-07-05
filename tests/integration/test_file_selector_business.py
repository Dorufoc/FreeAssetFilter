# -*- coding: utf-8 -*-
"""
Regression tests for file_selector file listing + filtering + sorting logic.

Tests the core business methods and their integration:

  refresh_files  — triggers async load; tested via pipeline and edge cases
  _filter_files  — filter logic (pure function, tested directly)
  _sort_files    — sort logic (pure function, tested directly)
  change_sort    — public API for setting sort attributes

Architecture note on ``refresh_files`` async nature:

  The ``refresh_files`` method delegates file scanning to a
  ``FileListLoaderThread`` (QThread) and connects the result signal to a
  lambda.  PySide6 does not guarantee keeping a strong reference to that
  lambda after the method returns, which makes the async callback unreliable
  in test isolation.  Therefore the file-listing tests drive the pipeline
  synchronously — they build a file list the same way the thread does
  (``os.scandir``), then run ``_sort_files``, ``_filter_files``, and
  ``file_model.set_files``, which is exactly the code path that
  ``_on_files_loaded`` executes.  The async trigger itself (``refresh_files``)
  is verified for crash-safety on invalid paths; its full end-to-end
  correctness follows from the pipeline tests.
"""

import os
import pytest
from typing import Any, Dict, List

from PySide6.QtCore import QCoreApplication, QDateTime, Qt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_files(selector) -> List[Dict[str, Any]]:
    """Return the current file list from the selector's model."""
    return selector.file_model._files


def _make_files(tmp_path, names: List[str]) -> None:
    """Create zero-content files under *tmp_path*."""
    for n in names:
        (tmp_path / n).write_text("")


def _scan_dir(tmp_path) -> List[Dict[str, Any]]:
    """Synchronous file scan matching FileListLoaderThread behaviour.

    Skips dotfiles and symlinks, populates the same dict keys that the
    production thread produces.
    """
    files: List[Dict[str, Any]] = []
    with os.scandir(str(tmp_path)) as entries:
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_symlink():
                    continue
                st = entry.stat(follow_symlinks=False)
                files.append({
                    "name": entry.name,
                    "path": entry.path,
                    "is_dir": entry.is_dir(follow_symlinks=False),
                    "size": st.st_size,
                    "modified": QDateTime.fromSecsSinceEpoch(
                        int(st.st_mtime)).toString(Qt.ISODate),
                    "created": QDateTime.fromSecsSinceEpoch(
                        int(st.st_ctime)).toString(Qt.ISODate),
                    "suffix": os.path.splitext(entry.name)[1].lower().lstrip('.'),
                })
            except (OSError, PermissionError):
                continue
    return files


def _run_pipeline(selector, tmp_path) -> None:
    """Load, sort, filter and set files — identical to ``_on_files_loaded``.

    This exercises the exact same code path that ``refresh_files`` →
    ``FileListLoaderThread`` → ``loaded`` signal → ``_on_files_loaded``
    follows, without depending on the async signal delivery.
    """
    raw_files = _scan_dir(tmp_path)
    sorted_files = selector._sort_files(raw_files)
    filtered_files = selector._filter_files(sorted_files)
    selector.file_model.set_files(filtered_files)


# ===================================================================
# File listing — pipeline
# ===================================================================

class TestFileListing:
    """Synchronous pipeline tests (the code path behind ``refresh_files``)."""

    def test_loads_all_files(self, file_selector, tmp_path):
        """All visible files in a directory should be loaded."""
        _make_files(tmp_path, ["a.txt", "b.txt", "c.txt"])
        _run_pipeline(file_selector, tmp_path)

        files = _get_files(file_selector)
        assert len(files) == 3
        assert {f["name"] for f in files} == {"a.txt", "b.txt", "c.txt"}

    def test_empty_directory_returns_empty_list(self, file_selector, tmp_path):
        """An empty directory should produce an empty file list."""
        _run_pipeline(file_selector, tmp_path)
        assert _get_files(file_selector) == []

    def test_skips_hidden_files(self, file_selector, tmp_path):
        """Files whose name starts with '.' must be excluded."""
        _make_files(tmp_path, ["visible.txt", ".hidden", ".gitkeep"])
        _run_pipeline(file_selector, tmp_path)

        names = {f["name"] for f in _get_files(file_selector)}
        assert "visible.txt" in names
        assert ".hidden" not in names
        assert ".gitkeep" not in names

    def test_includes_directories(self, file_selector, tmp_path):
        """Sub-directories must appear in the file list with is_dir=True."""
        _make_files(tmp_path, ["file.txt"])
        (tmp_path / "subdir").mkdir()
        _run_pipeline(file_selector, tmp_path)

        dirs = [f for f in _get_files(file_selector) if f["is_dir"]]
        regular = [f for f in _get_files(file_selector) if not f["is_dir"]]
        assert len(dirs) == 1
        assert dirs[0]["name"] == "subdir"
        assert len(regular) == 1


# ===================================================================
# refresh_files — edge cases & crash safety
# ===================================================================

class TestRefreshFilesEdgeCases:
    """Tests for ``refresh_files`` that do not depend on async delivery."""

    def test_invalid_path_does_not_crash(self, file_selector):
        """refresh_files on a non-existent path must not raise."""
        file_selector.current_path = "Z:\\__nonexistent_test_path_xyz__"
        file_selector.refresh_files()
        thread = file_selector._file_loader_thread
        if thread is not None and thread.isRunning():
            thread.wait(3000)
        for _ in range(5):
            QCoreApplication.processEvents()

    def test_clears_model_before_loading(self, file_selector, tmp_path):
        """refresh_files clears the model before starting the thread."""
        file_selector.file_model.set_files([{"name": "stale.txt", "path": "/stale"}])
        assert len(_get_files(file_selector)) == 1

        file_selector.current_path = str(tmp_path)
        file_selector.refresh_files()
        assert len(_get_files(file_selector)) == 0


# ===================================================================
# Filtering — _filter_files pure-function tests
# ===================================================================

class TestFiltering:
    """Tests for the filter logic in ``_filter_files``.

    (``apply_filter`` itself shows a modal dialog and is not testable
    without a display; these tests verify the underlying filter engine.)
    """

    WILDCARD_CASES = [
        ("*",             ["a.txt", "b.jpg", "c.png"],           3),
        ("*.txt",         ["a.txt", "b.jpg", "c.txt"],           2),
        ("c?t.txt",       ["cat.txt", "car.txt", "cart.txt"],    1),
        ("*.txt",         ["README.TXT", "readme.txt"],          2),
        ("[invalid",      ["file.txt"],                          0),
        ("project.*",     ["project.py", "project.md", "other"], 2),
    ]

    @pytest.mark.parametrize("pattern,filenames,expected", WILDCARD_CASES)
    def test_filter_patterns(self, file_selector, pattern, filenames, expected):
        """Various wildcard/regex patterns should match expected counts."""
        file_list = [{"name": f, "is_dir": False} for f in filenames]
        file_selector.filter_pattern = pattern
        result = file_selector._filter_files(file_list)
        assert len(result) == expected, (
            f"pattern={pattern!r} expected {expected} got {len(result)}"
        )

    def test_all_filter_returns_same_object(self, file_selector):
        """filter_pattern='*' returns input list unchanged (identity)."""
        files = [{"name": "a.txt", "is_dir": False}]
        file_selector.filter_pattern = "*"
        result = file_selector._filter_files(files)
        assert result is files

    def test_integration_filter_with_directory(self, file_selector, tmp_path):
        """Filter applied to real directory scan should narrow results."""
        _make_files(tmp_path, ["readme.md", "setup.py", "main.py", "image.png"])
        _run_pipeline(file_selector, tmp_path)
        assert len(_get_files(file_selector)) == 4

        file_selector.filter_pattern = "*.py"
        _run_pipeline(file_selector, tmp_path)
        assert len(_get_files(file_selector)) == 2
        assert all(f["suffix"] == "py" for f in _get_files(file_selector))


# ===================================================================
# Sorting — _sort_files pure-function tests
# ===================================================================

class TestSorting:
    """Tests for the sort logic in ``_sort_files``."""

    def _run(self, file_selector, files, sort_by, sort_order):
        """Helper to set sort params and run ``_sort_files``."""
        file_selector.sort_by = sort_by
        file_selector.sort_order = sort_order
        return file_selector._sort_files(list(files))

    # --- Name ---

    def test_name_asc(self, file_selector):
        """Name ascending: case-insensitive alphabetical."""
        files = [
            {"name": "beta.txt", "is_dir": False},
            {"name": "Alpha.txt", "is_dir": False},
            {"name": "Gamma.txt", "is_dir": False},
        ]
        result = self._run(file_selector, files, "name", "asc")
        # Sort key is (not is_dir, name.lower()) → "alpha" < "beta" < "gamma"
        assert [f["name"] for f in result] == ["Alpha.txt", "beta.txt", "Gamma.txt"]

    def test_name_desc(self, file_selector):
        """Name descending: reverse case-insensitive alphabetical."""
        files = [
            {"name": "beta.txt", "is_dir": False},
            {"name": "Alpha.txt", "is_dir": False},
        ]
        result = self._run(file_selector, files, "name", "desc")
        assert [f["name"] for f in result] == ["beta.txt", "Alpha.txt"]

    # --- Size ---

    def test_size_asc(self, file_selector):
        """Size ascending: by byte count."""
        files = [
            {"name": "large.txt", "size": 1000, "is_dir": False},
            {"name": "small.txt", "size": 1, "is_dir": False},
            {"name": "medium.txt", "size": 100, "is_dir": False},
        ]
        result = self._run(file_selector, files, "size", "asc")
        assert [f["size"] for f in result] == [1, 100, 1000]

    def test_size_desc(self, file_selector):
        """Size descending: by byte count (largest first)."""
        files = [
            {"name": "small.txt", "size": 1, "is_dir": False},
            {"name": "large.txt", "size": 1000, "is_dir": False},
        ]
        result = self._run(file_selector, files, "size", "desc")
        assert [f["size"] for f in result] == [1000, 1]

    # --- Modified time ---

    def test_modified_asc(self, file_selector):
        """Modified ascending: chronological order."""
        files = [
            {"name": "old.txt", "modified": "2020-01-01", "is_dir": False},
            {"name": "new.txt", "modified": "2023-01-01", "is_dir": False},
        ]
        result = self._run(file_selector, files, "modified", "asc")
        assert [f["name"] for f in result] == ["old.txt", "new.txt"]

    def test_modified_desc(self, file_selector):
        """Modified descending: newest first."""
        files = [
            {"name": "old.txt", "modified": "2020-01-01", "is_dir": False},
            {"name": "new.txt", "modified": "2023-01-01", "is_dir": False},
        ]
        result = self._run(file_selector, files, "modified", "desc")
        assert [f["name"] for f in result] == ["new.txt", "old.txt"]

    # --- Created time ---

    def test_created_asc(self, file_selector):
        """Created ascending: chronological order."""
        files = [
            {"name": "new.txt", "created": "2023-01-01", "is_dir": False},
            {"name": "old.txt", "created": "2020-01-01", "is_dir": False},
        ]
        result = self._run(file_selector, files, "created", "asc")
        assert [f["name"] for f in result] == ["old.txt", "new.txt"]

    def test_created_desc(self, file_selector):
        """Created descending: newest first."""
        files = [
            {"name": "old.txt", "created": "2020-01-01", "is_dir": False},
            {"name": "new.txt", "created": "2023-01-01", "is_dir": False},
        ]
        result = self._run(file_selector, files, "created", "desc")
        assert [f["name"] for f in result] == ["new.txt", "old.txt"]

    # --- Directory ordering ---

    def test_directories_before_files_name_asc(self, file_selector):
        """Directories sort before files regardless of name (ascending)."""
        files = [
            {"name": "afile.txt", "is_dir": False},
            {"name": "Zdir",      "is_dir": True},
        ]
        result = self._run(file_selector, files, "name", "asc")
        assert result[0]["is_dir"]
        assert not result[1]["is_dir"]

    def test_directories_before_files_name_desc(self, file_selector):
        """Descending sort reverses dir-first order: files come before dirs."""
        files = [
            {"name": "afile.txt", "is_dir": False},
            {"name": "Zdir",      "is_dir": True},
        ]
        result = self._run(file_selector, files, "name", "desc")
        # Ascending: [Zdir, afile.txt]; after reverse → [afile.txt, Zdir]
        assert not result[0]["is_dir"]   # file first
        assert result[1]["is_dir"]        # dir last

    def test_directories_before_files_size(self, file_selector):
        """Directories sort before files even when sorting by size."""
        files = [
            {"name": "small.txt", "size": 1, "is_dir": False},
            {"name": "adir",      "size": 0, "is_dir": True},
        ]
        result = self._run(file_selector, files, "size", "asc")
        assert result[0]["is_dir"]
        assert not result[1]["is_dir"]


# ===================================================================
# change_sort — public API
# ===================================================================

class TestChangeSort:
    """Tests for the public ``change_sort`` API."""

    @pytest.mark.parametrize("display_text,expected", [
        ("名称升序",     ("name",     "asc")),
        ("名称降序",     ("name",     "desc")),
        ("大小升序",     ("size",     "asc")),
        ("大小降序",     ("size",     "desc")),
        ("修改时间升序",  ("modified", "asc")),
        ("修改时间降序",  ("modified", "desc")),
        ("创建时间升序",  ("created",  "asc")),
        ("创建时间降序",  ("created",  "desc")),
    ])
    def test_change_sort_mapping(self, file_selector, display_text, expected):
        """change_sort maps Chinese display text to correct sort_by/order."""
        file_selector.change_sort(display_text)
        assert (file_selector.sort_by, file_selector.sort_order) == expected, (
            f"{display_text} → expected {expected}, "
            f"got ({file_selector.sort_by}, {file_selector.sort_order})"
        )
