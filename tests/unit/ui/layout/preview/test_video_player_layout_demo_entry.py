# -*- coding: utf-8 -*-
"""Standalone demo entry tests for ``VideoPlayerLayout``.

These tests exercise the module-level helpers used by
``if __name__ == '__main__':`` without launching the application event loop.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture(scope="module")
def _vpl(qapp: Any):  # noqa: ANN201
    """Import the module under test after the QApplication exists."""
    from freeassetfilter.ui.layout.preview import video_player_layout as vpl

    return vpl


class TestAudioExtensionInference:
    """Extension-based audio inference used by the standalone entry."""

    @pytest.mark.parametrize(
        "ext",
        [
            ".mp3",
            ".MP3",
            ".wav",
            ".flac",
            ".ogg",
            ".m4a",
            ".aac",
            ".wma",
            ".opus",
            ".aiff",
        ],
    )
    def test_known_audio_extensions_recognized(
        self, _vpl: Any, ext: str
    ) -> None:
        """Known audio suffixes should be inferred as audio."""
        assert _vpl._is_audio_file(f"path/to/song{ext}") is True

    @pytest.mark.parametrize(
        "ext",
        [".txt", ".mp4", ".avi", ".mkv", ".png", ".", ""],
    )
    def test_non_audio_extensions_rejected(self, _vpl: Any, ext: str) -> None:
        """Non-audio suffixes must not trigger audio mode."""
        assert _vpl._is_audio_file(f"path/to/file{ext}") is False


class TestSupportedMediaInference:
    """Extension whitelist used to keep unsupported files on the overlay."""

    @pytest.mark.parametrize(
        "ext",
        [
            ".mp3",
            ".mp4",
            ".avi",
            ".mkv",
            ".mov",
            ".wmv",
            ".flv",
            ".webm",
            ".mpg",
            ".mpeg",
        ],
    )
    def test_audio_and_video_extensions_supported(self, _vpl: Any, ext: str) -> None:
        """Both audio and video suffixes belong to the supported set."""
        assert _vpl._is_supported_media_file(f"path/to/file{ext}") is True

    @pytest.mark.parametrize("ext", [".txt", ".md", ".pdf", ".png", ".zip", ""])
    def test_unsupported_extensions_rejected(self, _vpl: Any, ext: str) -> None:
        """Non-media extensions must stay on the placeholder overlay."""
        assert _vpl._is_supported_media_file(f"path/to/file{ext}") is False


class TestPlayableFileFilter:
    """The file dialog filter used by ``_on_browse_file``."""

    def test_filter_contains_audio_extensions(self, _vpl: Any) -> None:
        """Audio extensions from the plan acceptance criteria are present."""
        for ext in (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"):
            assert f"*{ext}" in _vpl.PLAYABLE_FILE_FILTER

    def test_filter_contains_video_extensions(self, _vpl: Any) -> None:
        """Video extensions from the original filter remain present."""
        for ext in (".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".mpg", ".mpeg"):
            assert f"*{ext}" in _vpl.PLAYABLE_FILE_FILTER

    def test_filter_is_chinese_and_grouped(self, _vpl: Any) -> None:
        """The filter string uses the friendly Chinese prefix and has both groups."""
        assert "播放文件" in _vpl.PLAYABLE_FILE_FILTER
        assert "所有文件 (*.*)" in _vpl.PLAYABLE_FILE_FILTER
        assert _vpl.PLAYABLE_FILE_FILTER.count(";;") == 1


class TestAudioExtensionsConstant:
    """Coverage for the module-level audio extension set."""

    def test_expected_audio_extensions_present(self, _vpl: Any) -> None:
        """The plan acceptance criteria audio list is implemented."""
        expected = {
            ".mp3",
            ".wav",
            ".flac",
            ".ogg",
            ".m4a",
            ".aac",
            ".wma",
            ".opus",
            ".aiff",
        }
        assert _vpl.AUDIO_EXTENSIONS == expected
