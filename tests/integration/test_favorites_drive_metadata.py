# -*- coding: utf-8 -*-
"""
Integration tests for favorites management, drive detection, and metadata extraction.

Tests are isolated via mocks: no real file system scanning, no real thread pools,
no real mutagen/audio decoding.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QTimer


# =============================================================================
# Favorites
# =============================================================================


class TestFavoritesLoad:
    """_load_favorites — reading favorites from disk."""

    @pytest.fixture(autouse=True)
    def _reset_favorites(self, file_selector):
        file_selector._favorites_loaded = False
        file_selector.favorites = []
        file_selector._favorites_save_timer = QTimer()
        return file_selector

    # --- happy path -----------------------------------------------------------

    def test_load_from_valid_file(self, file_selector, tmp_path):
        """Load favorites from a well-formed JSON list (new string format)."""
        fav_file = tmp_path / "favorites.json"
        data = ["C:\\docs\\a.txt", "D:\\pics\\b.png"]
        fav_file.write_text(json.dumps(data), encoding="utf-8")
        file_selector.favorites_file = str(fav_file)

        result = file_selector._load_favorites()

        expected = [
            {"path": "C:\\docs\\a.txt", "name": "a.txt"},
            {"path": "D:\\pics\\b.png", "name": "b.png"},
        ]
        assert result == expected
        assert file_selector.favorites == expected
        assert file_selector._favorites_loaded is True

    def test_load_from_non_existent_file(self, file_selector, tmp_path):
        """Non‑existent file → empty list."""
        file_selector.favorites_file = str(tmp_path / "missing.json")

        result = file_selector._load_favorites()

        assert result == []
        assert file_selector.favorites == []

    # --- degraded inputs ------------------------------------------------------

    def test_load_corrupted_json(self, file_selector, tmp_path):
        """Unparseable JSON → graceful empty list, no crash."""
        fav_file = tmp_path / "favorites.json"
        fav_file.write_text("{bad json", encoding="utf-8")
        file_selector.favorites_file = str(fav_file)

        result = file_selector._load_favorites()

        assert result == []
        assert file_selector.favorites == []

    def test_load_not_a_list(self, file_selector, tmp_path):
        """JSON value that is not a list → empty list."""
        fav_file = tmp_path / "favorites.json"
        fav_file.write_text('{"key": "value"}', encoding="utf-8")
        file_selector.favorites_file = str(fav_file)

        result = file_selector._load_favorites()

        assert result == []
        assert file_selector.favorites == []

    # --- caching --------------------------------------------------------------

    def test_load_already_loaded_returns_cached(self, file_selector):
        """Second call returns in‑memory list without re‑reading the file."""
        file_selector._favorites_loaded = True
        file_selector.favorites = [{"path": "cached", "name": "cached"}]
        original_file = file_selector.favorites_file

        result = file_selector._load_favorites()

        assert result == [{"path": "cached", "name": "cached"}]
        # file path hasn't changed — if it re-read it would produce different data
        assert file_selector.favorites_file == original_file


class TestFavoritesSave:
    """_save_favorites / _flush_favorites_save — persisting to disk."""

    @pytest.fixture(autouse=True)
    def _setup_timer_and_pool(self, file_selector):
        file_selector._favorites_loaded = True
        file_selector._favorites_save_timer = QTimer()
        file_selector._favorites_save_timer.setSingleShot(True)
        return file_selector

    # --- save triggers timer --------------------------------------------------

    def test_save_starts_debounce_timer(self, file_selector):
        """_save_favorites starts the single‑shot timer."""
        timer_mock = MagicMock(spec=QTimer)
        file_selector._favorites_save_timer = timer_mock

        file_selector._save_favorites()

        timer_mock.start.assert_called_once()

    # --- flush writes correct data --------------------------------------------

    def test_flush_saves_via_favorites_service(
        self, file_selector, tmp_path
    ):
        """_flush_favorites_save calls FavoritesService.save() with paths."""
        fav_file = tmp_path / "favorites.json"
        file_selector.favorites_file = str(fav_file)
        file_selector.favorites = [
            {"path": "C:\\keep\\me.txt", "name": "me.txt"},
        ]

        with patch.object(file_selector._favorites_service, "save") as mock_save:
            file_selector._flush_favorites_save()

            mock_save.assert_called_once_with(["C:\\keep\\me.txt"])

    @patch("freeassetfilter.components.file_selector.QThreadPool")
    def test_flush_loads_if_not_yet_loaded(
        self, mock_tp_class, file_selector, tmp_path
    ):
        """_flush_favorites_save triggers _load_favorites when _favorites_loaded is False."""
        fav_file = tmp_path / "favorites.json"
        fav_file.write_text(
            json.dumps([{"path": "C:\\loaded.txt", "name": "loaded.txt"}]),
            encoding="utf-8",
        )
        file_selector.favorites_file = str(fav_file)
        file_selector._favorites_loaded = False

        mock_pool = MagicMock()
        mock_tp_class.globalInstance.return_value = mock_pool

        file_selector._flush_favorites_save()

        assert file_selector._favorites_loaded is True
        assert file_selector.favorites == [
            {"path": "C:\\loaded.txt", "name": "loaded.txt"},
        ]


class TestFavoritesAddRemove:
    """Add / remove / find operations on the in‑memory favorites list."""

    @pytest.fixture(autouse=True)
    def _seed_favorites(self, file_selector):
        file_selector.favorites = [
            {"path": "C:\\keep\\a.txt", "name": "a.txt"},
            {"path": "D:\\keep\\b.txt", "name": "b.txt"},
            {"path": "E:\\keep\\c.txt", "name": "c.txt"},
        ]
        file_selector._favorites_loaded = True
        return file_selector

    # --- find ----------------------------------------------------------------

    def test_find_favorite_by_path_found(self, file_selector):
        """_find_favorite_by_path returns the matching item."""
        result = file_selector._find_favorite_by_path("C:\\keep\\a.txt")
        assert result == {"path": "C:\\keep\\a.txt", "name": "a.txt"}

    def test_find_favorite_by_path_not_found(self, file_selector):
        """_find_favorite_by_path returns None for non‑existent path."""
        assert file_selector._find_favorite_by_path("Z:\\missing.txt") is None

    def test_find_favorite_by_path_normalizes(self, file_selector):
        """Path normalisation is applied (mixed separators)."""
        result = file_selector._find_favorite_by_path("C:/keep/a.txt")
        assert result == {"path": "C:\\keep\\a.txt", "name": "a.txt"}

    def test_find_favorite_by_path_empty(self, file_selector):
        """Empty string → None."""
        assert file_selector._find_favorite_by_path("") is None

    # --- add ----------------------------------------------------------------

    def test_append_favorite(self, file_selector):
        """Appending an item grows the list."""
        new_item = {"path": "F:\\new\\d.txt", "name": "d.txt"}
        file_selector.favorites.append(new_item)
        assert len(file_selector.favorites) == 4
        assert file_selector.favorites[-1] == new_item

    def test_add_duplicate_path(self, file_selector):
        """Appending a duplicate path is allowed (caller de‑duplicates)."""
        dup = {"path": "C:\\keep\\a.txt", "name": "a.txt"}
        file_selector.favorites.append(dup)
        assert len(file_selector.favorites) == 4

    # --- remove -------------------------------------------------------------

    def test_remove_favorite_by_filter(self, file_selector):
        """Filtering out a path removes it from the list."""
        file_selector.favorites = [
            f for f in file_selector.favorites if f["path"] != "D:\\keep\\b.txt"
        ]
        assert len(file_selector.favorites) == 2
        assert all(f["path"] != "D:\\keep\\b.txt" for f in file_selector.favorites)

    def test_remove_favorite_not_found_is_noop(self, file_selector):
        """Removing a non‑existent path leaves the list unchanged."""
        original_len = len(file_selector.favorites)
        file_selector.favorites = [
            f for f in file_selector.favorites if f["path"] != "Z:\\ghost.txt"
        ]
        assert len(file_selector.favorites) == original_len


# =============================================================================
# Drive Detection
# =============================================================================


class TestDriveBuildItems:
    """_build_drive_items — combining local drives and network locations."""

    @pytest.fixture(autouse=True)
    def _prevent_drive_thread(self, file_selector):
        """Prevent any actual thread from starting in setUp."""
        with patch.object(file_selector, "_update_drive_list"):
            yield

    def test_local_drives_only(self, file_selector):
        items = file_selector._build_drive_items(["C:", "D:", "E:"], [])
        assert items == ["All", "C:", "D:", "E:"]

    def test_with_network_locations(self, file_selector):
        items = file_selector._build_drive_items(
            ["C:", "D:"], ["\\\\server\\share", "\\\\nas\\vol1"]
        )
        assert items == [
            "All",
            "C:",
            "D:",
            "--- 网络位置 ---",
            "\\\\server\\share",
            "\\\\nas\\vol1",
        ]

    def test_empty_lists(self, file_selector):
        items = file_selector._build_drive_items([], [])
        assert items == ["All"]

    def test_network_without_local(self, file_selector):
        items = file_selector._build_drive_items([], ["\\\\remote\\path"])
        assert items == ["All", "--- 网络位置 ---", "\\\\remote\\path"]


class TestDriveApplyList:
    """_apply_drive_list — updating the drive combo box."""

    def _make_drive_combo_mock(self):
        """Create a drive_combo mock with the nested list_widget chain."""
        combo = MagicMock()
        # _apply_drive_list calls: drive_combo.list_widget.list_widget.sizeHintForRow(0)
        list_widget_inner = MagicMock()
        list_widget_inner.sizeHintForRow.return_value = 20
        list_widget_outer = MagicMock()
        list_widget_outer.list_widget = list_widget_inner
        combo.list_widget = list_widget_outer
        return combo

    def test_applies_items_with_inferred_default(self, file_selector):
        file_selector.drive_combo = self._make_drive_combo_mock()
        file_selector.current_path = "D:\\some\\folder"

        file_selector._apply_drive_list(["All", "C:", "D:", "E:"])

        file_selector.drive_combo.set_items.assert_called_once_with(
            ["All", "C:", "D:", "E:"], default_item="D:"
        )
        file_selector.drive_combo.set_max_visible_items.assert_called_once_with(4)

    def test_applies_items_with_explicit_default(self, file_selector):
        file_selector.drive_combo = self._make_drive_combo_mock()
        file_selector.current_path = "C:\\some\\folder"

        file_selector._apply_drive_list(
            ["All", "C:", "D:"], default_item="D:"
        )

        file_selector.drive_combo.set_items.assert_called_once_with(
            ["All", "C:", "D:"], default_item="D:"
        )

    def test_empty_list_is_noop(self, file_selector):
        file_selector.drive_combo = MagicMock()

        file_selector._apply_drive_list([])

        file_selector.drive_combo.set_items.assert_not_called()


class TestDriveUpdateList:
    """_update_drive_list / _on_drive_list_loaded."""

    def test_update_uses_cached_drives_first(self, file_selector):
        """DriveService fast path applies drives, then a thread is started."""
        file_selector._apply_drive_list = MagicMock()

        with patch(
            "freeassetfilter.components.file_selector.DriveListLoaderThread"
        ) as mock_thread_cls, patch.object(
            file_selector._drive_service, "list_drives",
            return_value=["C:", "D:"],
        ):
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            file_selector._drive_list_thread = None

            file_selector._update_drive_list()

            file_selector._apply_drive_list.assert_called_with(["All", "C:", "D:"])
            mock_thread.start.assert_called_once()

    def test_update_skips_second_thread_if_running(self, file_selector):
        """If _drive_list_thread is already running, do not start another."""
        running_thread = MagicMock()
        running_thread.isRunning.return_value = True
        file_selector._drive_list_thread = running_thread

        with patch(
            "freeassetfilter.components.file_selector.DriveListLoaderThread"
        ) as mock_thread_cls:
            file_selector._update_drive_list()

            mock_thread_cls.assert_not_called()

    def test_on_drive_list_loaded_updates_cache_and_applies(self, file_selector):
        file_selector._apply_drive_list = MagicMock()
        file_selector._build_drive_items = MagicMock(
            return_value=["All", "C:", "D:", "E:"]
        )

        file_selector._on_drive_list_loaded(
            ["C:", "D:", "E:"], ["\\\\server\\path"]
        )

        assert file_selector._cached_local_drives == ["C:", "D:", "E:"]
        assert file_selector._cached_network_locations == ["\\\\server\\path"]
        file_selector._apply_drive_list.assert_called_once_with(
            ["All", "C:", "D:", "E:"]
        )


class TestDriveGetCurrentItem:
    """_get_current_drive_item."""

    def test_on_windows_drive(self, file_selector):
        file_selector.current_path = "C:\\Users\\test"
        result = file_selector._get_current_drive_item(["All", "C:", "D:"])
        assert result == "C:"

    def test_on_all_view(self, file_selector):
        file_selector.current_path = "All"
        result = file_selector._get_current_drive_item(["All", "C:", "D:"])
        assert result == "All"


# =============================================================================
# Metadata Extraction
# =============================================================================


class TestAudioCoverExtraction:
    """VideoPlayer._extract_audio_cover — extracting cover art from audio files."""

    # --- no mutagen -----------------------------------------------------------

    def test_no_mutagen_module(self, video_player):
        """When mutagen is not installed, return None."""
        with patch("os.path.isfile", return_value=True), patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file", None
        ):
            result = video_player._extract_audio_cover("track.mp3")
        assert result is None

    # --- method 1: known cover key --------------------------------------------

    def test_cover_via_cover_key_jpeg(self, video_player):
        """JPEG cover found via 'cover' key in tags."""
        fake_cover = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        mock_audio = MagicMock()
        mock_audio.tags = {"cover": MagicMock(data=fake_cover)}

        with patch("os.path.isfile", return_value=True), patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            return_value=mock_audio,
        ):
            result = video_player._extract_audio_cover("track.mp3")
        assert result == fake_cover

    def test_cover_via_apic_key(self, video_player):
        """Cover found via 'APIC:' key (ID3v2)."""
        fake_cover = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        mock_audio = MagicMock()
        mock_audio.tags = {"APIC:": MagicMock(data=fake_cover)}

        with patch("os.path.isfile", return_value=True), patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            return_value=mock_audio,
        ):
            result = video_player._extract_audio_cover("track.mp3")
        assert result == fake_cover

    def test_cover_via_covr_key(self, video_player):
        """Cover found via 'covr' key (MP4)."""
        fake_cover = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        mock_audio = MagicMock()
        mock_audio.tags = {"covr": MagicMock(data=fake_cover)}

        with patch("os.path.isfile", return_value=True), patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            return_value=mock_audio,
        ):
            result = video_player._extract_audio_cover("track.m4a")
        assert result == fake_cover

    def test_non_bytes_data_skipped(self, video_player):
        """Tag value whose .data is not bytes is skipped by method 1."""
        fake_cover = b"\xff\xd8\xff\xe0" + b"\x00" * 80
        mock_audio = MagicMock()
        # 'cover' key exists but .data is not bytes → skip → fall through
        mock_audio.tags = {
            "cover": MagicMock(data="string_not_bytes"),
            "APIC:": MagicMock(data=fake_cover),
        }

        with patch("os.path.isfile", return_value=True), patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            return_value=mock_audio,
        ):
            result = video_player._extract_audio_cover("track.mp3")
        assert result == fake_cover

    # --- method 2: scan all tags by image signature --------------------------

    def test_fallback_scan_finds_jpeg(self, video_player):
        """Fallback tag iteration finds a JPEG image by magic bytes."""
        fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 50
        tag = MagicMock()
        tag.data = fake_jpeg
        mock_audio = MagicMock()
        mock_audio.tags = {"APIC": tag}

        with patch("os.path.isfile", return_value=True), patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            return_value=mock_audio,
        ):
            result = video_player._extract_audio_cover("track.mp3")
        assert result == fake_jpeg

    def test_fallback_scan_finds_png(self, video_player):
        """Fallback tag iteration finds a PNG image by magic bytes."""
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        tag = MagicMock()
        tag.data = fake_png
        mock_audio = MagicMock()
        mock_audio.tags = {"XXXX": tag}  # non‑standard key

        with patch("os.path.isfile", return_value=True), patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            return_value=mock_audio,
        ):
            result = video_player._extract_audio_cover("track.mp3")
        assert result == fake_png

    def test_fallback_data_too_short_skipped(self, video_player):
        """Data blob shorter than 10 bytes is skipped by method 2."""
        tag = MagicMock()
        tag.data = b"\xff\xd8\xff"  # only 3 bytes
        mock_audio = MagicMock()
        mock_audio.tags = {"APIC": tag}

        with patch("os.path.isfile", return_value=True), patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            return_value=mock_audio,
        ):
            result = video_player._extract_audio_cover("track.mp3")
        assert result is None

    def test_fallback_tag_no_data_attr_skipped(self, video_player):
        """Tag object without a .data attribute is skipped."""
        mock_audio = MagicMock()
        mock_audio.tags = {"APIC": object()}  # no .data

        with patch("os.path.isfile", return_value=True), patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            return_value=mock_audio,
        ):
            result = video_player._extract_audio_cover("track.mp3")
        assert result is None

    # --- no cover ------------------------------------------------------------

    def test_audio_with_no_tags(self, video_player):
        """Audio with no tags → None."""
        mock_audio = MagicMock()
        mock_audio.tags = {}

        with patch("os.path.isfile", return_value=True), patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            return_value=mock_audio,
        ):
            result = video_player._extract_audio_cover("track.mp3")
        assert result is None

    def test_audio_returns_none(self, video_player):
        """mutagen_file returns None → None."""
        with patch("os.path.isfile", return_value=True), patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            return_value=None,
        ):
            result = video_player._extract_audio_cover("track.mp3")
        assert result is None

    # --- exception -----------------------------------------------------------

    def test_mutagen_raises_exception(self, video_player):
        """Any exception is caught and None is returned."""
        with patch("os.path.isfile", return_value=True), patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            side_effect=RuntimeError("boom"),
        ):
            result = video_player._extract_audio_cover("track.mp3")
        assert result is None


class TestFileInfoExtraction:
    """FileInfoPreviewer — extracting file and directory metadata."""

    # --- basic file info -----------------------------------------------------

    def test_get_basic_info_file(self, qapp, tmp_path):
        """Basic info for a regular file contains all expected fields."""
        from freeassetfilter.components.file_info_previewer import (
            FileInfoPreviewer,
        )

        previewer = FileInfoPreviewer()
        try:
            f = tmp_path / "report.txt"
            f.write_text("Hello, World!")

            info = previewer._get_basic_info(str(f))

            assert info["文件名"] == "report.txt"
            assert info["文件路径"] == str(f)
            assert info["文件类型"] == "文件"
            assert "文件大小" in info
            assert info["文件大小"] != "无法获取"
            assert info["创建时间"] != "无法获取"
            assert info["修改时间"] != "无法获取"
            assert "权限" in info
        finally:
            previewer.deleteLater()

    def test_get_basic_info_directory(self, qapp, tmp_path):
        """Basic info for a directory reports '目录' as type."""
        from freeassetfilter.components.file_info_previewer import (
            FileInfoPreviewer,
        )

        previewer = FileInfoPreviewer()
        try:
            d = tmp_path / "my_folder"
            d.mkdir()

            info = previewer._get_basic_info(str(d))

            assert info["文件类型"] == "目录"
        finally:
            previewer.deleteLater()

    def test_get_basic_info_unreachable_path(self, qapp):
        """Unreachable path → all fields gracefully report failure."""
        from freeassetfilter.components.file_info_previewer import (
            FileInfoPreviewer,
        )

        previewer = FileInfoPreviewer()
        try:
            info = previewer._get_basic_info(
                "Z:\\does\\not\\exist\\file.txt"
            )

            assert info["文件大小"] == "无法获取"
            assert info["创建时间"] == "无法获取"
            assert info["修改时间"] == "无法获取"
        finally:
            previewer.deleteLater()

    # --- set_file + extract_file_info integration ----------------------------

    def test_set_file_populates_basic_info(self, qapp, tmp_path):
        """set_file → extract_file_info → file_info['basic'] is populated."""
        from freeassetfilter.components.file_info_previewer import (
            FileInfoPreviewer,
        )

        previewer = FileInfoPreviewer()
        try:
            # init_ui just sets pass → need get_ui() to create widgets first
            previewer.get_ui()

            f = tmp_path / "data.csv"
            f.write_text("a,b,c\n1,2,3")
            file_info = {
                "name": "data.csv",
                "path": str(f),
                "is_dir": False,
                "size": f.stat().st_size,
                "suffix": "csv",
            }

            previewer.set_file(file_info)

            basic = previewer.file_info["basic"]
            assert basic["文件名"] == "data.csv"
            assert basic["文件路径"] == str(f)
        finally:
            previewer.deleteLater()

    # --- directory info ------------------------------------------------------

    def test_get_directory_info(self, qapp, tmp_path):
        """Directory info reports file and sub‑directory counts."""
        from freeassetfilter.components.file_info_previewer import (
            FileInfoPreviewer,
        )

        previewer = FileInfoPreviewer()
        try:
            d = tmp_path / "parent"
            d.mkdir()
            (d / "f1.txt").write_text("x")
            (d / "f2.txt").write_text("y")
            (d / "sub").mkdir()

            info = previewer._get_directory_info(str(d))

            assert info["文件数"] == 2
            assert info["子目录数"] == 1
        finally:
            previewer.deleteLater()

    def test_get_directory_info_unreachable(self, qapp):
        """Unreachable directory → gracefully reports failure."""
        from freeassetfilter.components.file_info_previewer import (
            FileInfoPreviewer,
        )

        previewer = FileInfoPreviewer()
        try:
            info = previewer._get_directory_info(
                "Z:\\nonexistent_dir"
            )
            assert info["子目录数"] == "无法访问"
            assert info["文件数"] == "无法访问"
        finally:
            previewer.deleteLater()

    def test_get_directory_info_empty(self, qapp, tmp_path):
        """Empty directory → zero counts."""
        from freeassetfilter.components.file_info_previewer import (
            FileInfoPreviewer,
        )

        previewer = FileInfoPreviewer()
        try:
            d = tmp_path / "empty"
            d.mkdir()

            info = previewer._get_directory_info(str(d))

            assert info["文件数"] == 0
            assert info["子目录数"] == 0
        finally:
            previewer.deleteLater()
