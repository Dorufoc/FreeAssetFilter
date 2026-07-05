# -*- coding: utf-8 -*-
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_limited_subprocess_output_truncates_stdout_and_stderr():
    from freeassetfilter.utils.subprocess_utils import run_with_limited_output

    script = (
        "import sys; "
        "sys.stdout.write('x' * 1024); "
        "sys.stderr.write('y' * 1024)"
    )

    result = run_with_limited_output(
        [sys.executable, "-c", script],
        text=True,
        encoding="utf-8",
        timeout=5,
        max_stdout_bytes=16,
        max_stderr_bytes=12,
    )

    assert result.returncode == 0
    assert result.stdout == "x" * 16
    assert result.stderr == "y" * 12
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True


def test_media_probe_rejects_injection_path_before_spawning(monkeypatch):
    from freeassetfilter.core import media_probe

    def fail_run(*args, **kwargs):
        raise AssertionError("ffprobe should not be spawned for unsafe paths")

    monkeypatch.setattr(media_probe, "run_with_limited_output", fail_run)

    assert media_probe.run_ffprobe_json("movie$(calc).mp4") is None


def test_media_probe_rejects_sensitive_system_path_before_spawning(monkeypatch):
    from freeassetfilter.core import media_probe

    def fail_run(*args, **kwargs):
        raise AssertionError("ffprobe should not be spawned for sensitive paths")

    monkeypatch.setattr(media_probe, "run_with_limited_output", fail_run)

    assert media_probe.run_ffprobe_json(r"C:\Windows\win.ini") is None


def test_media_probe_validates_and_uses_limited_output(monkeypatch, tmp_path):
    from freeassetfilter.core import media_probe

    media_file = tmp_path / "clip.mp4"
    media_file.write_bytes(b"fake")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        completed = subprocess.CompletedProcess(command, 0, stdout=json.dumps({"format": {}}), stderr="")
        completed.stdout_truncated = False
        completed.stderr_truncated = False
        return completed

    monkeypatch.setattr(media_probe, "get_ffprobe_path", lambda: "ffprobe")
    monkeypatch.setattr(media_probe, "run_with_limited_output", fake_run)

    assert media_probe.run_ffprobe_json(str(media_file)) == {"format": {}}
    assert calls
    command, kwargs = calls[0]
    assert command[-1] == os.path.realpath(str(media_file))
    assert kwargs["max_stdout_bytes"] == media_probe.FFPROBE_MAX_OUTPUT_BYTES
    assert kwargs["max_stderr_bytes"] == media_probe.FFPROBE_MAX_OUTPUT_BYTES


def test_media_probe_rejects_truncated_json(monkeypatch, tmp_path):
    from freeassetfilter.core import media_probe

    media_file = tmp_path / "clip.mp4"
    media_file.write_bytes(b"fake")

    def fake_run(command, **kwargs):
        completed = subprocess.CompletedProcess(command, 0, stdout='{"format": {}', stderr="")
        completed.stdout_truncated = True
        completed.stderr_truncated = False
        return completed

    monkeypatch.setattr(media_probe, "get_ffprobe_path", lambda: "ffprobe")
    monkeypatch.setattr(media_probe, "run_with_limited_output", fake_run)

    assert media_probe.run_ffprobe_json(str(media_file)) is None


def test_safe_json_loads_rejects_long_string_before_parse():
    from freeassetfilter.core.settings_manager import JSONValueExceededError, safe_json_loads

    with pytest.raises(JSONValueExceededError):
        safe_json_loads('{"path": "%s"}' % ("x" * 32), max_string_length=8)


def test_safe_json_loads_rejects_excessive_depth_before_parse():
    from freeassetfilter.core.settings_manager import JSONDepthExceededError, safe_json_loads

    with pytest.raises(JSONDepthExceededError):
        safe_json_loads("[[[[[]]]]]", max_depth=3)


def test_app_logger_formatter_redacts_paths_and_secrets():
    from freeassetfilter.utils.app_logger import ComponentSourceFormatter

    formatter = ComponentSourceFormatter("%(message)s")
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=r"path=C:\Users\Alice\secret\file.txt token=abc123",
        args=(),
        exc_info=None,
    )

    formatted = formatter.format(record)

    assert "Alice" not in formatted
    assert "abc123" not in formatted
    assert "[USER_HOME]" in formatted
    assert "token=[REDACTED]" in formatted


def test_file_loader_skips_symbolic_links(tmp_path):
    pytest.importorskip("PySide6")
    from freeassetfilter.components.file_selector import FileListLoaderThread

    real_file = tmp_path / "real.txt"
    real_file.write_text("ok", encoding="utf-8")
    link_path = tmp_path / "linked.txt"

    try:
        link_path.symlink_to(real_file)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建符号链接")

    captured = []
    errors = []
    loader = FileListLoaderThread(str(tmp_path))
    loader.loaded.connect(lambda _path, files: captured.append(files))
    loader.failed.connect(lambda _path, message: errors.append(message))

    loader.run()

    assert not errors
    assert captured
    names = {item["name"] for item in captured[0]}
    assert "real.txt" in names
    assert "linked.txt" not in names
