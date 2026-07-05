#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

Media Probe 模块单元测试
"""

import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from freeassetfilter.core.media_probe import (
    run_ffprobe_json,
    get_video_stream_info,
    get_video_duration_seconds,
    get_ffprobe_path,
    get_ffmpeg_path,
    warmup_ffmpeg_tools,
    _safe_float,
    _safe_int,
    _parse_fraction,
    _native_dir,
    _resolve_tool_path,
    FFPROBE_TIMEOUT,
    FFMPEG_TIMEOUT,
)


class TestSafeFloat:
    def test_valid_float_string(self):
        assert _safe_float("3.14") == 3.14

    def test_valid_float(self):
        assert _safe_float(2.5) == 2.5

    def test_valid_int(self):
        assert _safe_float(5) == 5.0

    def test_none_value(self):
        assert _safe_float(None) is None

    def test_empty_string(self):
        assert _safe_float("") is None

    def test_invalid_string(self):
        assert _safe_float("abc") is None

    def test_zero(self):
        assert _safe_float(0) is None

    def test_negative(self):
        assert _safe_float(-1.5) is None


class TestSafeInt:
    def test_valid_int_string(self):
        assert _safe_int("42") == 42

    def test_valid_int(self):
        assert _safe_int(100) == 100

    def test_none_value(self):
        assert _safe_int(None) is None

    def test_empty_string(self):
        assert _safe_int("") is None

    def test_invalid_string(self):
        assert _safe_int("abc") is None

    def test_zero(self):
        assert _safe_int(0) == 0


class TestParseFraction:
    def test_simple_fraction(self):
        result = _parse_fraction("30/1")
        assert result == 30.0

    def test_fraction_with_decimal(self):
        result = _parse_fraction("30000/1001")
        assert abs(result - 29.97002997002997) < 0.0001

    def test_zero_denominator(self):
        assert _parse_fraction("1/0") is None

    def test_none_value(self):
        assert _parse_fraction(None) is None

    def test_empty_string(self):
        assert _parse_fraction("") is None

    def test_zero_div_zero(self):
        assert _parse_fraction("0/0") is None

    def test_na(self):
        assert _parse_fraction("N/A") is None

    def test_integer_input(self):
        assert _parse_fraction(30) == 30.0

    def test_float_input(self):
        assert _parse_fraction(29.97) == 29.97

    def test_plain_string_number(self):
        assert _safe_float("30.0") == 30.0


class TestResolveToolPath:
    def test_resolve_ffprobe(self):
        path = get_ffprobe_path()
        assert path is not None
        assert isinstance(path, str)

    def test_resolve_ffmpeg(self):
        path = get_ffmpeg_path()
        assert path is not None
        assert isinstance(path, str)

    def test_native_dir(self):
        native = _native_dir()
        assert native.exists()
        assert native.is_dir()

    def test_resolve_tool_path_existing(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix='.exe', dir=os.path.dirname(os.path.dirname(__file__))) as f:
            temp_path = f.name
            f.write(b'dummy')

        try:
            with patch('freeassetfilter.core.media_probe._native_dir') as mock_dir:
                mock_dir.return_value = Path(temp_path).parent
                result = _resolve_tool_path(Path(temp_path).name)
                assert result == temp_path
        finally:
            import gc
            gc.collect()
            import time
            time.sleep(0.1)
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except (PermissionError, OSError):
                pass


class TestRunFfprobeJson:
    def test_nonexistent_file(self):
        result = run_ffprobe_json(r"E:\nonexistent\file.mp4")
        assert result is None

    def test_injection_chars_blocked(self):
        with patch('freeassetfilter.core.media_probe.contains_injection_chars', return_value=True):
            result = run_ffprobe_json("file.mp4")
            assert result is None

    def test_sensitive_path_blocked(self):
        with patch('freeassetfilter.core.media_probe.contains_injection_chars', return_value=False):
            with patch('freeassetfilter.core.media_probe.is_sensitive_path', return_value=True):
                result = run_ffprobe_json(r"C:\Windows\system32\file.mp4")
                assert result is None

    def test_successful_probe(self):
        mock_payload = {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30/1",
                    "codec_name": "h264",
                    "bit_rate": "5000000"
                }
            ],
            "format": {
                "duration": "120.5",
                "bit_rate": "5000000"
            }
        }

        with patch('freeassetfilter.core.media_probe.run_with_limited_output') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = json.dumps(mock_payload)
            mock_result.stdout_truncated = False
            mock_run.return_value = mock_result

            with patch('freeassetfilter.core.media_probe.contains_injection_chars', return_value=False):
                with patch('freeassetfilter.core.media_probe.is_sensitive_path', return_value=False):
                    result = run_ffprobe_json(r"E:\test\video.mp4")
                    assert result is not None
                    assert "streams" in result
                    assert "format" in result

    def test_probe_timeout(self):
        import subprocess
        with patch('freeassetfilter.core.media_probe.run_with_limited_output') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("ffprobe", 8)
            with patch('freeassetfilter.core.media_probe.contains_injection_chars', return_value=False):
                with patch('freeassetfilter.core.media_probe.is_sensitive_path', return_value=False):
                    result = run_ffprobe_json(r"E:\test\video.mp4")
                    assert result is None

    def test_probe_file_not_found(self):
        with patch('freeassetfilter.core.media_probe.run_with_limited_output') as mock_run:
            mock_run.side_effect = FileNotFoundError()
            with patch('freeassetfilter.core.media_probe.contains_injection_chars', return_value=False):
                with patch('freeassetfilter.core.media_probe.is_sensitive_path', return_value=False):
                    result = run_ffprobe_json(r"E:\test\video.mp4")
                    assert result is None

    def test_probe_nonzero_exit(self):
        with patch('freeassetfilter.core.media_probe.run_with_limited_output') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stderr = "Error: invalid file"
            mock_run.return_value = mock_result
            with patch('freeassetfilter.core.media_probe.contains_injection_chars', return_value=False):
                with patch('freeassetfilter.core.media_probe.is_sensitive_path', return_value=False):
                    result = run_ffprobe_json(r"E:\test\video.mp4")
                    assert result is None

    def test_probe_json_parse_failure(self):
        with patch('freeassetfilter.core.media_probe.run_with_limited_output') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "invalid json{"
            mock_result.stdout_truncated = False
            mock_run.return_value = mock_result
            with patch('freeassetfilter.core.media_probe.contains_injection_chars', return_value=False):
                with patch('freeassetfilter.core.media_probe.is_sensitive_path', return_value=False):
                    result = run_ffprobe_json(r"E:\test\video.mp4")
                    assert result is None

    def test_probe_output_truncated(self):
        with patch('freeassetfilter.core.media_probe.run_with_limited_output') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "{}"
            mock_result.stdout_truncated = True
            mock_run.return_value = mock_result
            with patch('freeassetfilter.core.media_probe.contains_injection_chars', return_value=False):
                with patch('freeassetfilter.core.media_probe.is_sensitive_path', return_value=False):
                    result = run_ffprobe_json(r"E:\test\video.mp4")
                    assert result is None

    def test_probe_with_extra_entries(self):
        mock_payload = {"streams": [], "format": {}}
        with patch('freeassetfilter.core.media_probe.run_with_limited_output') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = json.dumps(mock_payload)
            mock_result.stdout_truncated = False
            mock_run.return_value = mock_result
            with patch('freeassetfilter.core.media_probe.contains_injection_chars', return_value=False):
                with patch('freeassetfilter.core.media_probe.is_sensitive_path', return_value=False):
                    result = run_ffprobe_json(
                        r"E:\test\video.mp4",
                        show_format=False,
                        show_streams=False,
                        extra_entries=["chapter"]
                    )
                    assert result is not None


class TestGetVideoStreamInfo:
    def test_successful_video_info(self):
        mock_payload = {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30/1",
                    "codec_name": "h264",
                    "bit_rate": "5000000"
                }
            ],
            "format": {
                "duration": "120.5",
                "bit_rate": "5000000"
            }
        }

        with patch('freeassetfilter.core.media_probe.run_ffprobe_json') as mock_probe:
            mock_probe.return_value = mock_payload
            result = get_video_stream_info(r"E:\test\video.mp4")

            assert "duration_seconds" in result
            assert "width" in result
            assert "height" in result
            assert "fps" in result
            assert "codec" in result
            assert "bitrate" in result
            assert result["width"] == 1920
            assert result["height"] == 1080
            assert result["codec"] == "h264"

    def test_video_info_probe_failure(self):
        with patch('freeassetfilter.core.media_probe.run_ffprobe_json') as mock_probe:
            mock_probe.return_value = None
            result = get_video_stream_info(r"E:\test\video.mp4")
            assert result == {}

    def test_video_info_no_video_stream(self):
        mock_payload = {
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "aac"
                }
            ],
            "format": {
                "duration": "120.5",
                "bit_rate": "128000"
            }
        }

        with patch('freeassetfilter.core.media_probe.run_ffprobe_json') as mock_probe:
            mock_probe.return_value = mock_payload
            result = get_video_stream_info(r"E:\test\audio.mp3")
            assert "duration_seconds" in result
            assert "width" not in result
            assert "height" not in result

    def test_video_info_fallback_bitrate(self):
        mock_payload = {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "codec_name": "h264"
                }
            ],
            "format": {
                "duration": "120.5",
                "bit_rate": "5000000"
            }
        }

        with patch('freeassetfilter.core.media_probe.run_ffprobe_json') as mock_probe:
            mock_probe.return_value = mock_payload
            result = get_video_stream_info(r"E:\test\video.mp4")
            assert "bitrate" in result
            assert result["bitrate"] == 5000000

    def test_video_info_stream_duration_priority(self):
        mock_payload = {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "duration": "125.0",
                    "codec_name": "h264"
                }
            ],
            "format": {
                "duration": "120.5"
            }
        }

        with patch('freeassetfilter.core.media_probe.run_ffprobe_json') as mock_probe:
            mock_probe.return_value = mock_payload
            result = get_video_stream_info(r"E:\test\video.mp4")
            assert result["duration_seconds"] == 125.0


class TestGetVideoDurationSeconds:
    def test_successful_duration(self):
        mock_info = {
            "duration_seconds": 120.5,
            "width": 1920,
            "height": 1080
        }

        with patch('freeassetfilter.core.media_probe.get_video_stream_info') as mock_info_fn:
            mock_info_fn.return_value = mock_info
            result = get_video_duration_seconds(r"E:\test\video.mp4")
            assert result == 120.5

    def test_duration_missing(self):
        with patch('freeassetfilter.core.media_probe.get_video_stream_info') as mock_info_fn:
            mock_info_fn.return_value = {}
            result = get_video_duration_seconds(r"E:\test\video.mp4")
            assert result is None

    def test_duration_zero(self):
        with patch('freeassetfilter.core.media_probe.get_video_stream_info') as mock_info_fn:
            mock_info_fn.return_value = {"duration_seconds": 0}
            result = get_video_duration_seconds(r"E:\test\video.mp4")
            assert result is None

    def test_duration_negative(self):
        with patch('freeassetfilter.core.media_probe.get_video_stream_info') as mock_info_fn:
            mock_info_fn.return_value = {"duration_seconds": -1.0}
            result = get_video_duration_seconds(r"E:\test\video.mp4")
            assert result is None


class TestWarmupFfmpegTools:
    def test_warmup_calls_functions(self):
        with patch('freeassetfilter.core.media_probe._run_warmup_command') as mock_warmup:
            mock_warmup.return_value = True
            result = warmup_ffmpeg_tools(force=True)
            assert "ffprobe_version" in result
            assert "ffmpeg_version" in result
            assert "ffmpeg_hwaccels" in result

    def test_warmup_uses_cached_result(self):
        with patch('freeassetfilter.core.media_probe._run_warmup_command') as mock_warmup:
            mock_warmup.return_value = True
            result1 = warmup_ffmpeg_tools(force=True)
            result2 = warmup_ffmpeg_tools(force=False)
            assert result1 == result2
            assert mock_warmup.call_count == 3
