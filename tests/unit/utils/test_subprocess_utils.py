# -*- coding: utf-8 -*-
"""test_subprocess_utils: subprocess_utils.py 覆盖测试（todo-10, unit/utils 批 1）。

覆盖：run_with_limited_output 正常/超时/check/大输出截断/编码、
_coerce_output_limit 边界、_decode_output 编码处理。
"""

from __future__ import annotations

import locale
import os
import subprocess
import sys
from typing import Any

import pytest

from freeassetfilter.utils.subprocess_utils import (
    DEFAULT_MAX_OUTPUT_BYTES,
    _coerce_output_limit,
    _decode_output,
    run_with_limited_output,
)

#: 子进程运行时注入的编码环境，保证非 ASCII 输出可预期解码。
_SUBPROCESS_ENV: dict = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _py_code(statement: str) -> list:
    """构造 ``python -c <statement>`` 参数列表。

    Args:
        statement: 子进程执行的 Python 语句。

    Returns:
        list: Popen 用参数列表。
    """
    return [sys.executable, "-c", statement]


class TestNormalRun:
    """正常子进程输出捕获。"""

    def test_text_mode_stdout(self) -> None:
        """text=True 解码 stdout。"""
        result = run_with_limited_output(
            _py_code("print('hello world')"), text=True, encoding="utf-8", env=_SUBPROCESS_ENV
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "hello world"

    def test_bytes_mode_default(self) -> None:
        """默认（text=False）返回原始字节。"""
        result = run_with_limited_output(_py_code("print('hello world')"), env=_SUBPROCESS_ENV)
        assert isinstance(result.stdout, bytes)
        assert b"hello world" in result.stdout

    def test_stderr_captured_separately(self) -> None:
        """stderr 与 stdout 分离捕获。"""
        result = run_with_limited_output(
            _py_code("import sys; print('out'); sys.stderr.write('err')"),
            text=True,
            encoding="utf-8",
            env=_SUBPROCESS_ENV,
        )
        assert result.stdout.strip() == "out"
        assert "err" in result.stderr

    def test_completed_process_attrs(self) -> None:
        """CompletedProcess 附带截断元信息。"""
        result = run_with_limited_output(_py_code("print('hi')"), env=_SUBPROCESS_ENV)
        assert hasattr(result, "stdout_truncated")
        assert hasattr(result, "stdout_size")
        assert result.stdout_truncated is False


class TestTimeout:
    """超时场景。"""

    def test_timeout_raises_timeout_expired(self) -> None:
        """超时抛 TimeoutExpired 且不泄漏进程。"""
        with pytest.raises(subprocess.TimeoutExpired) as exc_info:
            run_with_limited_output(
                _py_code("import time; time.sleep(60)"),
                timeout=1.0,
                env=_SUBPROCESS_ENV,
            )
        exc = exc_info.value
        # run_with_limited_output 为异常附加读取后的输出。
        assert hasattr(exc, "stdout")
        assert hasattr(exc, "stdout_truncated")


class TestCheckTrue:
    """check=True 的非零退出处理。"""

    def test_nonzero_raises_called_process_error(self) -> None:
        """非零退出码抛 CalledProcessError。"""
        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            run_with_limited_output(
                _py_code("import sys; sys.exit(3)"),
                check=True,
                text=True,
                encoding="utf-8",
                env=_SUBPROCESS_ENV,
            )
        assert exc_info.value.returncode == 3

    def test_zero_exit_no_raise(self) -> None:
        """零退出码不抛异常。"""
        result = run_with_limited_output(
            _py_code("import sys; sys.exit(0)"),
            check=True,
            env=_SUBPROCESS_ENV,
        )
        assert result.returncode == 0


class TestLargeOutputTruncation:
    """大输出截断（避免内存爆炸）。"""

    def test_large_stdout_truncated(self) -> None:
        """超过 max_stdout_bytes 的 stdout 被截断。"""
        result = run_with_limited_output(
            _py_code("print('x' * 200000)"),
            max_stdout_bytes=1024,
            env=_SUBPROCESS_ENV,
        )
        assert result.stdout_truncated is True
        assert len(result.stdout) == 1024
        assert result.stdout_size >= 200000

    def test_large_stderr_truncated(self) -> None:
        """超过 max_stderr_bytes 的 stderr 被截断。"""
        result = run_with_limited_output(
            _py_code("import sys; sys.stderr.write('e' * 50000)"),
            max_stderr_bytes=1024,
            env=_SUBPROCESS_ENV,
        )
        assert result.stderr_truncated is True
        assert len(result.stderr) == 1024
        assert result.stderr_size == 50000
        assert result.stdout_truncated is False
        assert result.stdout_size == 0

    def test_zero_limit_returns_empty(self) -> None:
        """max_bytes=0 不读任何输出但保留总大小。"""
        result = run_with_limited_output(
            _py_code("print('1234567890')"),
            max_stdout_bytes=0,
            env=_SUBPROCESS_ENV,
        )
        assert result.stdout == b""
        assert result.stdout_truncated is True
        # 子进程实际写出的字节数（print 可能附加换行符）。
        assert result.stdout_size >= 10


class TestEncoding:
    """编码与错误处理。"""

    def test_utf8_non_ascii(self) -> None:
        """UTF-8 中文输出正确解码。"""
        result = run_with_limited_output(
            _py_code("print('你好世界')"),
            text=True,
            encoding="utf-8",
            env=_SUBPROCESS_ENV,
        )
        assert result.stdout.strip() == "你好世界"

    def test_errors_replace(self) -> None:
        """解码错误用替换字符填充。"""
        result = run_with_limited_output(
            _py_code("print('你好世界')"),
            text=True,
            encoding="ascii",
            errors="replace",
            env=_SUBPROCESS_ENV,
        )
        assert "\ufffd" in result.stdout


class TestInternalHelpers:
    """内部辅助函数边界。"""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, DEFAULT_MAX_OUTPUT_BYTES),
            (1024, 1024),
            (0, 0),
            (-5, 0),
            ("123", 123),
            ("abc", DEFAULT_MAX_OUTPUT_BYTES),
            (1.5, 1),  # int() 截断而非四舍五入
        ],
        ids=["none", "int", "zero", "negative", "numeric-str", "invalid-str", "float"],
    )
    def test_coerce_output_limit(self, raw: Any, expected: int) -> None:
        """_coerce_output_limit 归一化逻辑。

        Args:
            raw: 输入值。
            expected: 期望结果。
        """
        assert _coerce_output_limit(raw) == expected

    def test_decode_output_bytes_mode(self) -> None:
        """text=False 时不解码，返回原字节。"""
        data = b"\x00\xff"
        result = _decode_output(data, text=False, encoding=None, errors=None)
        assert result is data

    def test_decode_output_with_encoding(self) -> None:
        """text=True 且指定编码时按编码解码。"""
        result = _decode_output("你好".encode(), text=True, encoding="utf-8", errors=None)
        assert result == "你好"

    def test_decode_output_without_encoding(self) -> None:
        """text=True 且未指定编码时回退 locale 首选编码。"""
        data = "hello".encode(locale.getpreferredencoding(False))
        result = _decode_output(data, text=True, encoding=None, errors=None)
        assert result == "hello"