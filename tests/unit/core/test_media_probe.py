# -*- coding: utf-8 -*-
"""媒体探测模块单测（tests-comprehensive-refactor todo-9 补全）。

覆盖 ``freeassetfilter.core.native.bridges.media_probe``：

* ``get_ffprobe_path`` / ``get_ffmpeg_path`` 的 bundled 优先路径解析、
  ``get_subprocess_creationflags`` / ``get_subprocess_startupinfo``；
* ``run_ffprobe_json`` 全程 mock ``run_with_limited_output``——**绝不调用
  真实 ffprobe**，覆盖成功 / 非零退出 / 缺二进制(FileNotFoundError) /
  超时(TimeoutExpired) / 输出截断 / JSON 解析失败 / 注入字符与敏感路径
  拦截 / command 形状与 timeout 透传；
* ``get_video_stream_info`` / ``get_video_duration_seconds`` 的 mock
  payload 解析路径；
* ``_safe_float`` / ``_safe_int`` / ``_parse_fraction`` 边界;
* ``warmup_ffmpeg_tools`` 的缓存命中与 mock 命令路径。

设计纪律：任何子进程调用都被 monkeypatch 完全替换，绝不无超时调用真实
ffprobe/ffmpeg（见计划 MUST DO）。真实 ffprobe 存在与否不影响本文件结果。
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Dict, List

import pytest

from freeassetfilter.core.native.bridges import media_probe


pytestmark = pytest.mark.unit


# =============================================================================
# 测试上下文辅助
# =============================================================================
class _FakeCompleted:
    """模拟 ``run_with_limited_output`` 的返回对象（CompletedProcess 形状）。"""

    def __init__(
        self,
        returncode: int = 0,
        stdout: Any = "{}",
        stderr: Any = "",
        stdout_truncated: bool = False,
        stderr_truncated: bool = False,
    ) -> None:
        """构造一个假完成对象。

        Args:
            returncode: 模拟的进程返回码。
            stdout: 模拟 stdout（str 或 bytes）。
            stderr: 模拟 stderr。
            stdout_truncated: 模拟 stdout 超过上限被截断。
            stderr_truncated: 模拟 stderr 超过上限被截断。
        """
        self.args: List[str] = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.stdout_truncated = stdout_truncated
        self.stderr_truncated = stderr_truncated


@pytest.fixture(autouse=True)
def _clear_ffprobe_cache() -> None:
    """每个用例前后清空 ``_run_ffprobe_json_cached`` 的 LRU 缓存。"""
    media_probe._run_ffprobe_json_cached.cache_clear()
    yield
    media_probe._run_ffprobe_json_cached.cache_clear()


@pytest.fixture()
def _probe_file(tmp_path: Any) -> str:
    """生成一个存在但内容无意义的"媒体"文件（子进程被 mock，无需真实媒体）。"""
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"fake media bytes for mocked probing")
    return str(path)


# =============================================================================
# 工具路径解析
# =============================================================================
class TestToolPathResolution:
    """``get_ffprobe_path`` / ``get_ffmpeg_path`` 等纯路径函数。"""

    def test_get_ffprobe_path_returns_string(self) -> None:
        """返回非空字符串；bundled 存在时还指向实体文件。"""
        path = media_probe.get_ffprobe_path()
        assert isinstance(path, str)
        assert path
        if (media_probe._native_dir() / (os.name == "nt" and "ffprobe.exe" or "ffprobe")).exists():
            assert os.path.exists(path)

    def test_get_ffmpeg_path_returns_string(self) -> None:
        """返回非空字符串；bundled 存在时还指向实体文件。"""
        path = media_probe.get_ffmpeg_path()
        assert isinstance(path, str)
        assert path
        if (media_probe._native_dir() / (os.name == "nt" and "ffmpeg.exe" or "ffmpeg")).exists():
            assert os.path.exists(path)

    def test_path_resolution_prefers_bundled(self, monkeypatch: Any, tmp_path: Any) -> None:
        """bundled 目录中存在同名工具时返回 bundled 绝对路径而非裸命令名。"""
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir(parents=True)
        resource = fake_bin / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
        resource.write_bytes(b"")
        monkeypatch.setattr(media_probe, "_native_dir", lambda: fake_bin)
        assert media_probe.get_ffprobe_path() == str(resource)

    def test_get_subprocess_creationflags_is_int(self) -> None:
        """返回非负整数（无 CREATE_NO_WINDOW 平台为 0）。"""
        flags = media_probe.get_subprocess_creationflags()
        assert isinstance(flags, int)
        assert flags >= 0

    def test_get_subprocess_startupinfo(self) -> None:
        """win32 平台返回隐藏窗口的 STARTUPINFO，非 win32 为 None。"""
        startupinfo = media_probe.get_subprocess_startupinfo()
        if sys.platform == "win32":
            assert startupinfo is not None
            assert startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW
        else:
            assert startupinfo is None


# =============================================================================
# run_ffprobe_json：mock 子进程路径
# =============================================================================
class TestRunFfprobeJsonMocked:
    """``run_ffprobe_json`` 的 mock 成功 / 失败 / 边界路径。"""

    def test_success_returns_parsed_payload(
        self, monkeypatch: Any, _probe_file: str
    ) -> None:
        """returncode==0 且为合法 JSON 时返回解析后的 dict。"""
        captured: Dict[str, Any] = {}

        def _fake_run(*args: Any, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return _FakeCompleted(returncode=0, stdout='{"format": {"duration": "10.5"}}')

        monkeypatch.setattr(media_probe, "run_with_limited_output", _fake_run)
        payload = media_probe.run_ffprobe_json(_probe_file)
        assert payload == {"format": {"duration": "10.5"}}
        assert captured["timeout"] == media_probe.FFPROBE_TIMEOUT

    def test_custom_timeout_passed_through(
        self, monkeypatch: Any, _probe_file: str
    ) -> None:
        """显式 timeout 透传给子进程调用。"""
        captured: Dict[str, Any] = {}

        def _fake_run(*args: Any, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return _FakeCompleted(stdout="{}")

        monkeypatch.setattr(media_probe, "run_with_limited_output", _fake_run)
        media_probe.run_ffprobe_json(_probe_file, timeout=3)
        assert captured["timeout"] == 3

    def test_command_shape_contains_show_flags(
        self, monkeypatch: Any, _probe_file: str
    ) -> None:
        """命令包含 ffprobe 及 -show_format / -show_streams 标志。"""
        captured_args: List[list] = []

        def _fake_run(*args: Any, **kwargs: Any) -> Any:
            captured_args.append(list(args[0]))
            return _FakeCompleted(stdout="{}")

        monkeypatch.setattr(media_probe, "run_with_limited_output", _fake_run)
        media_probe.run_ffprobe_json(_probe_file)
        cmd = captured_args[0]
        assert os.path.basename(cmd[0]).lower().replace("\\", "/") in ("ffprobe", "ffprobe.exe")
        assert "-show_format" in cmd
        assert "-show_streams" in cmd

    def test_no_show_flags_when_disabled(
        self, monkeypatch: Any, _probe_file: str
    ) -> None:
        """show_format/show_streams 全 False 时命令不含 -show_* 与 -show_entries。"""
        captured_args: List[list] = []

        def _fake_run(*args: Any, **kwargs: Any) -> Any:
            captured_args.append(list(args[0]))
            return _FakeCompleted(stdout="{}")

        monkeypatch.setattr(media_probe, "run_with_limited_output", _fake_run)
        media_probe.run_ffprobe_json(_probe_file, show_format=False, show_streams=False)
        cmd = captured_args[0]
        assert "-show_format" not in cmd
        assert "-show_streams" not in cmd
        assert "-show_entries" not in cmd

    def test_extra_entries_in_show_entries(
        self, monkeypatch: Any, _probe_file: str
    ) -> None:
        """extra_entries 拼入 -show_entries 冒号连接字符串。"""
        captured_args: List[list] = []

        def _fake_run(*args: Any, **kwargs: Any) -> Any:
            captured_args.append(list(args[0]))
            return _FakeCompleted(stdout="{}")

        monkeypatch.setattr(media_probe, "run_with_limited_output", _fake_run)
        media_probe.run_ffprobe_json(
            _probe_file, extra_entries=["chapter", "error"]
        )
        cmd = captured_args[0]
        idx = cmd.index("-show_entries")
        assert cmd[idx + 1] == "format:stream:chapter:error"

    def test_nonzero_exit_returns_none(
        self, monkeypatch: Any, _probe_file: str
    ) -> None:
        """returncode!=0 时返回 None。"""
        monkeypatch.setattr(
            media_probe,
            "run_with_limited_output",
            lambda *a, **k: _FakeCompleted(returncode=1, stderr="boom"),
        )
        assert media_probe.run_ffprobe_json(_probe_file) is None

    def test_missing_binary_returns_none(
        self, monkeypatch: Any, _probe_file: str
    ) -> None:
        """FileNotFoundError（ffprobe 缺失）时返回 None。"""

        def _raise(*a: Any, **k: Any) -> Any:
            raise FileNotFoundError("ffprobe not found")

        monkeypatch.setattr(media_probe, "run_with_limited_output", _raise)
        assert media_probe.run_ffprobe_json(_probe_file) is None

    def test_timeout_returns_none(self, monkeypatch: Any, _probe_file: str) -> None:
        """subprocess.TimeoutExpired 被转换为 None 返回。"""

        def _raise(*a: Any, **k: Any) -> Any:
            raise subprocess.TimeoutExpired(cmd=["ffprobe"], timeout=8)

        monkeypatch.setattr(media_probe, "run_with_limited_output", _raise)
        assert media_probe.run_ffprobe_json(_probe_file) is None

    def test_stdout_truncated_returns_none(
        self, monkeypatch: Any, _probe_file: str
    ) -> None:
        """stdout 超限截断时拒绝解析并返回 None。"""
        monkeypatch.setattr(
            media_probe,
            "run_with_limited_output",
            lambda *a, **k: _FakeCompleted(stdout="{}", stdout_truncated=True),
        )
        assert media_probe.run_ffprobe_json(_probe_file) is None

    def test_invalid_json_returns_none(
        self, monkeypatch: Any, _probe_file: str
    ) -> None:
        """输出非合法 JSON 时返回 None。"""
        monkeypatch.setattr(
            media_probe,
            "run_with_limited_output",
            lambda *a, **k: _FakeCompleted(stdout="this is { not json"),
        )
        assert media_probe.run_ffprobe_json(_probe_file) is None


class TestRunFfprobeJsonSafety:
    """``run_ffprobe_json`` 的路径安全拦截（不触发子进程）。"""

    def test_injection_chars_blocked_without_subprocess(
        self, monkeypatch: Any, _probe_file: str
    ) -> None:
        """含换行符的路径被拦截并返回 None，子进程不被调用。"""
        called: List[Any] = []
        monkeypatch.setattr(
            media_probe,
            "run_with_limited_output",
            lambda *a, **k: called.append(a) or _FakeCompleted(),
        )
        assert media_probe.run_ffprobe_json(_probe_file + "\n") is None
        assert called == []

    def test_sensitive_windows_path_blocked(
        self, monkeypatch: Any
    ) -> None:
        """敏感系统路径（C:\\Windows 开头）被拦截，子进程不被调用。"""
        called: List[Any] = []
        monkeypatch.setattr(
            media_probe,
            "run_with_limited_output",
            lambda *a, **k: called.append(a) or _FakeCompleted(),
        )
        assert media_probe.run_ffprobe_json(r"C:\Windows\system32\cmd.exe") is None
        assert called == []


# =============================================================================
# 纯解析辅助函数
# =============================================================================
class TestNumericParsers:
    """``_safe_float`` / ``_safe_int`` / ``_parse_fraction`` 边界。"""

    def test_safe_float(self) -> None:
        """合法字符串转 float；None / 非数字 / 非正数返回 None。"""
        assert media_probe._safe_float("12.5") == 12.5
        assert media_probe._safe_float(None) is None
        assert media_probe._safe_float("abc") is None
        assert media_probe._safe_float("-5") is None
        assert media_probe._safe_float(0) is None

    def test_safe_int(self) -> None:
        """合法字符串转 int；None / 非数字返回 None。"""
        assert media_probe._safe_int("1920") == 1920
        assert media_probe._safe_int(None) is None
        assert media_probe._safe_int("1.5") is None

    def test_parse_fraction(self) -> None:
        """分数 / 浮点 / 特殊值解析。"""
        assert media_probe._parse_fraction("30000/1001") == pytest.approx(30000 / 1001)
        assert media_probe._parse_fraction("0/0") is None
        assert media_probe._parse_fraction("1/0") is None
        assert media_probe._parse_fraction(None) is None
        assert media_probe._parse_fraction("N/A") is None
        assert media_probe._parse_fraction("") is None
        assert media_probe._parse_fraction(5) == 5.0
        assert media_probe._parse_fraction("24.0") == 24.0


# =============================================================================
# get_video_stream_info：mock payload 解析
# =============================================================================
class TestGetVideoStreamInfo:
    """``get_video_stream_info`` 从 mock ffprobe payload 提取字段。"""

    def test_extracts_all_fields(
        self, monkeypatch: Any, _probe_file: str
    ) -> None:
        """含视频流的 payload 提取时长/宽高/fps/编码器/码率。"""
        payload: Dict[str, Any] = {
            "format": {"duration": "2.0", "bit_rate": "800000"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30000/1001",
                    "duration": "2.0",
                    "bit_rate": "700000",
                }
            ],
        }
        monkeypatch.setattr(media_probe, "run_ffprobe_json", lambda *a, **k: payload)
        info = media_probe.get_video_stream_info(_probe_file)
        assert info["duration_seconds"] == 2.0
        assert info["width"] == 1920
        assert info["height"] == 1080
        assert info["fps"] == pytest.approx(30000 / 1001)
        assert info["codec"] == "h264"
        assert info["bitrate"] == 700000

    def test_no_streams_uses_format_only(
        self, monkeypatch: Any, _probe_file: str
    ) -> None:
        """无视频流时仅输出 format 时长。"""
        monkeypatch.setattr(
            media_probe,
            "run_ffprobe_json",
            lambda *a, **k: {"format": {"duration": "3.5"}, "streams": []},
        )
        assert media_probe.get_video_stream_info(_probe_file) == {"duration_seconds": 3.5}

    def test_failed_probe_returns_empty(
        self, monkeypatch: Any, _probe_file: str
    ) -> None:
        """ffprobe 失败（payload None）返回空 dict。"""
        monkeypatch.setattr(media_probe, "run_ffprobe_json", lambda *a, **k: None)
        assert media_probe.get_video_stream_info(_probe_file) == {}

    def test_fraction_fallback_to_r_frame_rate(
        self, monkeypatch: Any, _probe_file: str
    ) -> None:
        """avg_frame_rate 缺失时回退 r_frame_rate。"""
        payload: Dict[str, Any] = {
            "format": {},
            "streams": [
                {"codec_type": "video", "r_frame_rate": "25/1", "width": 640, "height": 480}
            ],
        }
        monkeypatch.setattr(media_probe, "run_ffprobe_json", lambda *a, **k: payload)
        info = media_probe.get_video_stream_info(_probe_file)
        assert info["fps"] == pytest.approx(25.0)


# =============================================================================
# get_video_duration_seconds
# =============================================================================
class TestGetVideoDuration:
    """``get_video_duration_seconds`` 从 mock 输出提取时长。"""

    def test_duration_from_format(
        self, monkeypatch: Any, _probe_file: str
    ) -> None:
        """format.duration 存在时返回 float 时长。"""
        monkeypatch.setattr(
            media_probe,
            "run_ffprobe_json",
            lambda *a, **k: {"format": {"duration": "42.5"}, "streams": []},
        )
        assert media_probe.get_video_duration_seconds(_probe_file) == 42.5

    def test_missing_duration_returns_none(
        self, monkeypatch: Any, _probe_file: str
    ) -> None:
        """无可用时长时返回 None。"""
        monkeypatch.setattr(
            media_probe,
            "run_ffprobe_json",
            lambda *a, **k: {"format": {}, "streams": []},
        )
        assert media_probe.get_video_duration_seconds(_probe_file) is None

    def test_failed_probe_returns_none(
        self, monkeypatch: Any, _probe_file: str
    ) -> None:
        """ffprobe 失败返回 None。"""
        monkeypatch.setattr(media_probe, "run_ffprobe_json", lambda *a, **k: None)
        assert media_probe.get_video_duration_seconds(_probe_file) is None


# =============================================================================
# warmup_ffmpeg_tools（mock 命令，绝不真跑）
# =============================================================================
class TestWarmupTools:
    """``warmup_ffmpeg_tools`` 的缓存命中与 mock 命令路径。"""

    def test_fresh_run_calls_three_mocked_commands(self, monkeypatch: Any) -> None:
        """强制刷新时三条 mock 任务全部执行并汇总结果。"""
        media_probe._FFMPEG_WARMUP_RESULT = None
        calls: List[str] = []
        monkeypatch.setattr(
            media_probe,
            "_run_warmup_command",
            lambda command, label, timeout: calls.append(label) or True,
        )
        result = media_probe.warmup_ffmpeg_tools(force=True)
        assert set(result) == {"ffprobe_version", "ffmpeg_version", "ffmpeg_hwaccels"}
        assert all(result.values())
        # 生产代码传给 _run_warmup_command 的 label 是任务描述字符串
        expected_labels = ["ffprobe -version", "ffmpeg -version", "ffmpeg -hwaccels"]
        assert sorted(calls) == sorted(expected_labels)

    def test_cached_result_skips_reinvocation(self, monkeypatch: Any) -> None:
        """缓存存在时直接返回，不再调用子进程。"""
        media_probe._FFMPEG_WARMUP_RESULT = {"ffprobe_version": True}
        calls: List[str] = []

        def _collect(*a: Any, **k: Any) -> bool:
            calls.append("called")
            return True

        monkeypatch.setattr(media_probe, "_run_warmup_command", _collect)
        assert media_probe.warmup_ffmpeg_tools() == {"ffprobe_version": True}
        assert calls == []

    def test_worker_exception_recorded_as_false(self, monkeypatch: Any) -> None:
        """单个预热任务异常不影响整体返回，该项记为 False。"""
        media_probe._FFMPEG_WARMUP_RESULT = None

        def _flaky(command: list, label: str, timeout: int) -> bool:
            raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

        monkeypatch.setattr(media_probe, "_run_warmup_command", _flaky)
        result = media_probe.warmup_ffmpeg_tools(force=True)
        assert set(result) == {"ffprobe_version", "ffmpeg_version", "ffmpeg_hwaccels"}
        assert all(not value for value in result.values())