# -*- coding: utf-8 -*-
"""
MediaMetadataService 单元测试
测试 freeassetfilter/services/media_metadata_service.py 模块的功能。
"""

import os
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from freeassetfilter.services.media_metadata_service import (
    MediaMetadataService,
)


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def service() -> MediaMetadataService:
    """创建一个已初始化的 MediaMetadataService 实例。"""
    svc = MediaMetadataService()
    svc.initialize()
    yield svc
    svc.dispose()


@pytest.fixture
def temp_audio_file(tmp_path) -> str:
    """创建一个空的伪装音频文件（仅用于路径测试，不含真实内容）。"""
    p = tmp_path / "test_song.mp3"
    p.write_bytes(b'\xff\xfb' + b'\x00' * 100)
    return str(p)


@pytest.fixture
def temp_text_file(tmp_path) -> str:
    """创建一个普通文本文件。"""
    p = tmp_path / "notes.txt"
    p.write_text("hello world")
    return str(p)


@pytest.fixture
def temp_dir(tmp_path) -> str:
    """创建一个临时目录。"""
    d = tmp_path / "some_dir"
    d.mkdir()
    return str(d)


# =========================================================================
# Mock helpers
# =========================================================================


def _make_mock_audio(
    length: float = 180.0,
    bitrate: int = 320000,
    channels: int = 2,
    sample_rate: int = 44100,
    cover_data: bytes | None = None,
) -> MagicMock:
    """构建一个模拟的 mutagen 音频对象。"""
    audio = MagicMock()

    # info 属性
    info = MagicMock()
    info.length = length
    info.bitrate = bitrate
    info.channels = channels
    info.sample_rate = sample_rate
    audio.info = info

    # tags —— 仅当需要封面时注入
    if cover_data:
        tag_entry = MagicMock()
        tag_entry.data = cover_data
        audio.tags = {"APIC:": tag_entry}
    else:
        audio.tags = {}

    return audio


# =========================================================================
# 基础 & 生命周期
# =========================================================================


class TestMediaMetadataServiceLifecycle:
    """测试 MediaMetadataService 生命周期。"""

    def test_module_import(self):
        """模块导出 MediaMetadataService。"""
        from freeassetfilter.services import MediaMetadataService
        assert MediaMetadataService is not None

    def test_initialize_and_dispose(self):
        """initialize / dispose 可以安全调用多次。"""
        svc = MediaMetadataService()
        assert svc.is_initialized is False

        assert svc.initialize() is True
        assert svc.is_initialized is True
        # 重复 initialize 返回 True 且不报错
        assert svc.initialize() is True

        svc.dispose()
        assert svc.is_initialized is False
        # 重复 dispose 不报错
        svc.dispose()

    def test_default_state(self, service: MediaMetadataService):
        """服务初始化后处于可用状态。"""
        assert service.is_initialized is True


# =========================================================================
# extract_audio_cover
# =========================================================================


class TestExtractAudioCover:
    """测试 extract_audio_cover() 方法。"""

    def test_file_not_found(self, service: MediaMetadataService):
        """不存在文件返回 None。"""
        assert service.extract_audio_cover(r"C:\nonexistent\file.mp3") is None

    def test_non_audio_file(self, service: MediaMetadataService, temp_text_file: str):
        """非音频文件（且 mutagen_file 可用时）返回 None。"""
        with patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            return_value=None,
        ):
            assert service.extract_audio_cover(temp_text_file) is None

    def test_cover_extracted_jpeg(self, service: MediaMetadataService, temp_audio_file: str):
        """JPEG 封面被正确提取。"""
        jpeg_header = b'\xff\xd8\xff\xe0' + b'\x00' * 50
        mock_audio = _make_mock_audio(cover_data=jpeg_header)

        with patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            return_value=mock_audio,
        ):
            result = service.extract_audio_cover(temp_audio_file)
            assert result == jpeg_header

    def test_cover_extracted_png(self, service: MediaMetadataService, temp_audio_file: str):
        """PNG 封面被正确提取。"""
        png_header = b'\x89PNG\r\n\x1a\n' + b'\x00' * 50
        mock_audio = _make_mock_audio(cover_data=png_header)

        with patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            return_value=mock_audio,
        ):
            result = service.extract_audio_cover(temp_audio_file)
            assert result == png_header

    def test_no_cover(self, service: MediaMetadataService, temp_audio_file: str):
        """音频文件无封面时返回 None。"""
        mock_audio = _make_mock_audio()  # cover_data 为空

        with patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            return_value=mock_audio,
        ):
            assert service.extract_audio_cover(temp_audio_file) is None

    def test_mutagen_not_installed(
        self, service: MediaMetadataService, temp_audio_file: str
    ):
        """mutagen 未安装时返回 None。"""
        with patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            None,
        ):
            assert service.extract_audio_cover(temp_audio_file) is None

    def test_mutagen_raises_exception(
        self, service: MediaMetadataService, temp_audio_file: str
    ):
        """mutagen 抛出异常时优雅降级返回 None。"""
        with patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            side_effect=RuntimeError("意外错误"),
        ):
            assert service.extract_audio_cover(temp_audio_file) is None


# =========================================================================
# extract_basic_info
# =========================================================================


class TestExtractBasicInfo:
    """测试 extract_basic_info() 方法。"""

    def test_nonexistent_file(self, service: MediaMetadataService):
        """不存在的文件返回仅含 name/path 的字典。"""
        path = r"C:\nonexistent\missing.zip"
        info = service.extract_basic_info(path)
        assert info["file_name"] == "missing.zip"
        assert info["file_path"] == path
        assert "file_size" not in info

    def test_text_file(self, service: MediaMetadataService, temp_text_file: str):
        """普通文本文件返回文件系统属性。"""
        info = service.extract_basic_info(temp_text_file)
        assert info["file_name"] == "notes.txt"
        assert info["file_path"] == temp_text_file
        assert info["extension"] == "txt"
        assert info["is_dir"] is False
        assert info["file_size"] > 0
        assert "file_size_str" in info
        assert "created_time" in info
        assert "modified_time" in info
        # 普通文件不返回媒体字段
        assert "duration" not in info

    def test_directory(self, service: MediaMetadataService, temp_dir: str):
        """目录返回 is_dir=True。"""
        info = service.extract_basic_info(temp_dir)
        assert info["is_dir"] is True
        assert info["extension"] == ""

    def test_audio_metadata(
        self, service: MediaMetadataService, temp_audio_file: str
    ):
        """音频文件通过 mutagen 返回媒体属性。"""
        mock_audio = _make_mock_audio(
            length=234.5,
            bitrate=256000,
            channels=2,
            sample_rate=48000,
        )

        with patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            return_value=mock_audio,
        ):
            info = service.extract_basic_info(temp_audio_file)
            assert info["duration"] == 234.5
            assert info["duration_str"] == "03:54"
            assert info["bitrate"] == 256000
            assert info["bitrate_str"] == "256.0 Kbps"
            assert info["channels"] == 2
            assert info["sample_rate"] == 48000

    def test_audio_no_mutagen(
        self, service: MediaMetadataService, temp_audio_file: str
    ):
        """mutagen 不可用时音频文件仅返回文件系统属性。"""
        with patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            None,
        ):
            info = service.extract_basic_info(temp_audio_file)
            assert info["file_name"] == "test_song.mp3"
            assert "duration" not in info

    def test_mutagen_returns_none(
        self, service: MediaMetadataService, temp_audio_file: str
    ):
        """mutagen 对不支持格式返回 None 时优雅降级。"""
        with patch(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            return_value=None,
        ):
            info = service.extract_basic_info(temp_audio_file)
            assert info["extension"] == "mp3"
            assert "duration" not in info


# =========================================================================
# 辅助方法
# =========================================================================


class TestFormatSize:
    """测试 _format_size 静态方法。"""

    def test_bytes(self):
        assert MediaMetadataService._format_size(512) == "512.0 B"

    def test_kilobytes(self):
        assert MediaMetadataService._format_size(2048) == "2.0 KB"

    def test_megabytes(self):
        assert MediaMetadataService._format_size(5_242_880) == "5.0 MB"

    def test_gigabytes(self):
        assert MediaMetadataService._format_size(5_368_709_120) == "5.0 GB"

    def test_negative(self):
        assert MediaMetadataService._format_size(-1) == "无法获取"


class TestFormatDuration:
    """测试 _format_duration 静态方法。"""

    def test_seconds_only(self):
        assert MediaMetadataService._format_duration(45) == "00:45"

    def test_minutes(self):
        assert MediaMetadataService._format_duration(125) == "02:05"

    def test_hours(self):
        assert MediaMetadataService._format_duration(3661) == "01:01:01"

    def test_negative(self):
        assert MediaMetadataService._format_duration(-5) == "无法获取"


class TestFormatBitrate:
    """测试 _format_bitrate 静态方法。"""

    def test_bps(self):
        assert MediaMetadataService._format_bitrate(500) == "500 bps"

    def test_kbps(self):
        assert MediaMetadataService._format_bitrate(128000) == "128.0 Kbps"

    def test_mbps(self):
        assert MediaMetadataService._format_bitrate(2_000_000) == "2.0 Mbps"

    def test_negative(self):
        assert MediaMetadataService._format_bitrate(-1) == "无法获取"


class TestLooksLikeImage:
    """测试 _looks_like_image 静态方法。"""

    def test_jpeg(self):
        assert MediaMetadataService._looks_like_image(b'\xff\xd8\xff\xe0')

    def test_png(self):
        assert MediaMetadataService._looks_like_image(b'\x89PNG\r\n')

    def test_bmp(self):
        assert MediaMetadataService._looks_like_image(b'BM\x00\x00')

    def test_gif(self):
        assert MediaMetadataService._looks_like_image(b'GI')

    def test_too_short(self):
        assert MediaMetadataService._looks_like_image(b'\x00' * 5) is False

    def test_not_image(self):
        assert MediaMetadataService._looks_like_image(b'\x00' * 20) is False
