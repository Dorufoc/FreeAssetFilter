#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
subprocess_utils 单元测试

测试 freeassetfilter/utils/subprocess_utils.py 模块的：
  - _coerce_output_limit 输出限制值规范化
  - _decode_output 输出解码
  - run_with_limited_output 受限子进程运行
"""

from __future__ import annotations

import locale
import subprocess
import sys
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from freeassetfilter.utils.subprocess_utils import (
    DEFAULT_MAX_OUTPUT_BYTES,
    _coerce_output_limit,
    _decode_output,
    _read_limited_output,
    run_with_limited_output,
)


# =============================================================================
# _coerce_output_limit
# =============================================================================


class TestCoerceOutputLimit:
    """_coerce_output_limit 功能测试"""

    def test_none_returns_default(self) -> None:
        """None 输入返回 DEFAULT_MAX_OUTPUT_BYTES"""
        assert _coerce_output_limit(None) == DEFAULT_MAX_OUTPUT_BYTES

    def test_positive_int_returns_self(self) -> None:
        """正整数原样返回"""
        assert _coerce_output_limit(1024) == 1024

    def test_zero_returns_zero(self) -> None:
        """零值返回 0"""
        assert _coerce_output_limit(0) == 0

    def test_negative_returns_zero(self) -> None:
        """负数被钳位为 0"""
        assert _coerce_output_limit(-1) == 0
        assert _coerce_output_limit(-999999) == 0

    def test_none_string_returns_default(self) -> None:
        """字符串 'None' 无法转换为 int 时返回默认值"""
        # int("None") 会抛出 ValueError
        assert _coerce_output_limit("None") == DEFAULT_MAX_OUTPUT_BYTES

    def test_invalid_string_returns_default(self) -> None:
        """无效字符串返回默认值"""
        assert _coerce_output_limit("not_a_number") == DEFAULT_MAX_OUTPUT_BYTES

    def test_float_truncated_to_int(self) -> None:
        """浮点数被 int() 截断"""
        assert _coerce_output_limit(3.9) == 3

    def test_large_value_stays_large(self) -> None:
        """大值原样返回"""
        val = 8 * 1024 * 1024
        assert _coerce_output_limit(val) == val


# =============================================================================
# _decode_output
# =============================================================================


class TestDecodeOutput:
    """_decode_output 解码功能测试"""

    def test_text_false_returns_bytes_unchanged(self) -> None:
        """text=False 时原样返回 bytes"""
        raw = b"hello world \xff\xfe"
        result = _decode_output(raw, text=False, encoding=None, errors=None)
        assert result is raw
        assert isinstance(result, bytes)

    def test_text_true_decodes_utf8(self) -> None:
        """text=True 时正确解码 UTF-8 bytes -> str"""
        raw = "你好世界".encode("utf-8")
        result = _decode_output(raw, text=True, encoding="utf-8", errors="strict")
        assert isinstance(result, str)
        assert result == "你好世界"

    def test_text_true_with_explicit_encoding(self) -> None:
        """text=True 时使用指定 encoding 解码"""
        raw = "héllo".encode("latin-1")
        result = _decode_output(raw, text=True, encoding="latin-1", errors="strict")
        assert result == "héllo"

    def test_text_true_fallback_to_preferred_encoding(self) -> None:
        """encoding=None 时回退到 locale 编码"""
        raw = "abc".encode("utf-8")
        result = _decode_output(raw, text=True, encoding=None, errors="strict")
        preferred = locale.getpreferredencoding(False) or "utf-8"
        assert isinstance(result, str)
        # 对 ascii-only 内容任何编码都能正确解码
        assert result == "abc"

    def test_decode_errors_replace(self) -> None:
        """errors 为 'replace' 时不会抛出解码异常"""
        # 用 cp1252 编码，然后尝试用 utf-8 解码失效字节
        raw = b"\xff\xfe\x00\x01"
        result = _decode_output(raw, text=True, encoding="utf-8", errors="replace")
        assert isinstance(result, str)
        # 不应抛出异常

    def test_decode_errors_strict_raises(self) -> None:
        """errors 为 'strict' 时解码失败抛出 UnicodeDecodeError"""
        raw = b"\xff\xfe\x00\x01"
        with pytest.raises(UnicodeDecodeError):
            _decode_output(raw, text=True, encoding="utf-8", errors="strict")

    def test_empty_bytes(self) -> None:
        """空 bytes 解码返回空字符串"""
        result = _decode_output(b"", text=True, encoding="utf-8", errors="strict")
        assert result == ""

    def test_default_errors_is_replace(self) -> None:
        """errors=None 时默认使用 'replace'"""
        raw = b"\xff"
        result = _decode_output(raw, text=True, encoding="utf-8", errors=None)
        assert isinstance(result, str)
        # 替换字符 \ufffd 的存在说明走的是 replace 分支
        assert "\ufffd" in result


# =============================================================================
# run_with_limited_output — 基本调用
# =============================================================================


class TestRunWithLimitedOutputBasic:
    """run_with_limited_output 基本功能"""

    def test_simple_command(self) -> None:
        """运行简单命令并正常返回"""
        result = run_with_limited_output(
            [sys.executable, "-c", "print('hello')"],
        )
        assert result.returncode == 0

    def test_text_mode_stdout_is_str(self) -> None:
        """text=True 时 stdout 为 str"""
        result = run_with_limited_output(
            [sys.executable, "-c", "print('hello')"],
            text=True,
        )
        assert isinstance(result.stdout, str)
        assert "hello" in result.stdout

    def test_bytes_mode_stdout_is_bytes(self) -> None:
        """text=False（默认）时 stdout 为 bytes"""
        result = run_with_limited_output(
            [sys.executable, "-c", "print('hello')"],
        )
        assert isinstance(result.stdout, bytes)

    def test_custom_encoding(self) -> None:
        """指定 encoding 解码"""
        result = run_with_limited_output(
            [sys.executable, "-c", "print('héllo')"],
            text=True,
            encoding="utf-8",
        )
        assert isinstance(result.stdout, str)

    def test_stderr_captured(self) -> None:
        """标准错误输出被捕获"""
        result = run_with_limited_output(
            [sys.executable, "-c", "import sys; print('err', file=sys.stderr)"],
            text=True,
        )
        assert result.returncode == 0
        assert "err" in result.stderr

    def test_popen_kwargs_passed_through(self) -> None:
        """额外的 **popen_kwargs 透传给 Popen"""
        result = run_with_limited_output(
            [sys.executable, "-c", "print('hello')"],
            text=True,
            env={"TEST_FAF": "1"},
        )
        assert result.returncode == 0


# =============================================================================
# run_with_limited_output — check=True
# =============================================================================


class TestRunWithLimitedOutputCheck:
    """check=True 行为"""

    def test_check_true_zero_exit_ok(self) -> None:
        """check=True 且返回码 0 时不抛出异常"""
        result = run_with_limited_output(
            [sys.executable, "-c", "print('ok')"],
            check=True,
        )
        assert result.returncode == 0

    def test_check_true_nonzero_raises(self) -> None:
        """check=True 且返回码非零时抛出 CalledProcessError"""
        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            run_with_limited_output(
                [sys.executable, "-c", "exit(1)"],
                check=True,
            )
        assert exc_info.value.returncode == 1

    def test_check_false_nonzero_no_raise(self) -> None:
        """check=False（默认）即使返回码非零也不抛出"""
        result = run_with_limited_output(
            [sys.executable, "-c", "exit(1)"],
            check=False,
        )
        assert result.returncode == 1


# =============================================================================
# run_with_limited_output — timeout
# =============================================================================


class TestRunWithLimitedOutputTimeout:
    """timeout 超时处理"""

    def test_timeout_expired_raises(self) -> None:
        """超时后抛出 TimeoutExpired"""
        with pytest.raises(subprocess.TimeoutExpired) as exc_info:
            run_with_limited_output(
                [sys.executable, "-c", "import time; time.sleep(100)"],
                timeout=0.01,
            )
        assert exc_info.value.timeout == 0.01

    def test_timeout_expired_sets_stdout_attributes(self) -> None:
        """超时时 TimeoutExpired 对象带有 stdout/stderr 和 _truncated 属性"""
        with pytest.raises(subprocess.TimeoutExpired) as exc_info:
            run_with_limited_output(
                [sys.executable, "-c", "import time; time.sleep(100); print('never')"],
                timeout=0.01,
            )
        exc = exc_info.value
        # 至少不报 AttributeError
        _ = exc.stdout
        _ = exc.stderr
        assert hasattr(exc, "stdout_truncated")
        assert hasattr(exc, "stderr_truncated")

    def test_normal_completion_no_timeout(self) -> None:
        """正常完成的命令不触发超时"""
        result = run_with_limited_output(
            [sys.executable, "-c", "print('fast')"],
            timeout=30,
            text=True,
        )
        assert result.returncode == 0
        assert "fast" in result.stdout


# =============================================================================
# run_with_limited_output — 输出截断
# =============================================================================


class TestRunWithLimitedOutputTruncation:
    """输出截断验证"""

    def test_stdout_truncated_flag_set_when_truncated(self) -> None:
        """stdout 被截断时 stdout_truncated=True"""
        result = run_with_limited_output(
            [sys.executable, "-c", "print('x' * 10000)"],
            max_stdout_bytes=10,
        )
        assert result.stdout_truncated is True

    def test_stdout_truncated_flag_false_when_not_truncated(self) -> None:
        """stdout 未截断时 stdout_truncated=False"""
        result = run_with_limited_output(
            [sys.executable, "-c", "print('small')"],
            max_stdout_bytes=4 * 1024 * 1024,
        )
        assert result.stdout_truncated is False

    def test_stdout_actually_truncated(self) -> None:
        """stdout 内容确实被截断到指定大小"""
        result = run_with_limited_output(
            [sys.executable, "-c", "print('x' * 5000)"],
            max_stdout_bytes=100,
        )
        # 截断后的 stdout（包含换行符）应 <= 100
        assert len(result.stdout) <= 100

    def test_stderr_truncated_flag(self) -> None:
        """stderr 截断标志位"""
        code = "import sys; print('e' * 5000, file=sys.stderr)"
        result = run_with_limited_output(
            [sys.executable, "-c", code],
            max_stderr_bytes=50,
        )
        assert result.stderr_truncated is True
        assert len(result.stderr) <= 50

    def test_both_streams_truncated_independently(self) -> None:
        """stdout 和 stderr 独立截断"""
        code = (
            "import sys; "
            "print('o' * 5000); "
            "print('e' * 5000, file=sys.stderr)"
        )
        result = run_with_limited_output(
            [sys.executable, "-c", code],
            max_stdout_bytes=100,
            max_stderr_bytes=200,
        )
        assert result.stdout_truncated is True
        assert result.stderr_truncated is True
        assert len(result.stdout) <= 100
        assert len(result.stderr) <= 200

    def test_zero_limit_yields_empty_output(self) -> None:
        """max_bytes=0 时输出为空字符串"""
        result = run_with_limited_output(
            [sys.executable, "-c", "print('hello')"],
            max_stdout_bytes=0,
            text=True,
        )
        assert result.stdout == ""

    def test_truncated_attributes_exist_on_success(self) -> None:
        """成功返回的 CompletedProcess 对象带有 _truncated 和 _size 属性"""
        result = run_with_limited_output(
            [sys.executable, "-c", "print('hello')"],
        )
        assert hasattr(result, "stdout_truncated")
        assert hasattr(result, "stderr_truncated")
        assert hasattr(result, "stdout_size")
        assert hasattr(result, "stderr_size")


# =============================================================================
# run_with_limited_output — text + encoding 组合
# =============================================================================


class TestRunWithLimitedOutputTextEncoding:
    """text / encoding / errors 参数"""

    def test_text_true_utf8_content(self) -> None:
        """text=True 能正确解码 UTF-8 中的非 ASCII"""
        code = "print('\\u4f60\\u597d')"  # print('你好')
        env = {"PYTHONIOENCODING": "utf-8"}
        result = run_with_limited_output(
            [sys.executable, "-c", code],
            text=True,
            encoding="utf-8",
            env=env,
        )
        assert "你好" in result.stdout

    def test_errors_replace_handles_bad_data(self) -> None:
        """errors='replace' 不会因解码失败崩溃"""
        # 用 python 直接输出非法 UTF-8 字节
        code = "import sys; sys.stdout.buffer.write(b'\\xff\\xfe')"
        # text=True 时会尝试解码，但 errors='replace' 保证不抛异常
        result = run_with_limited_output(
            [sys.executable, "-c", code],
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert isinstance(result.stdout, str)


# =============================================================================
# run_with_limited_output — 边缘场景
# =============================================================================


class TestRunWithLimitedOutputEdgeCases:
    """边缘场景"""

    def test_no_output_command(self) -> None:
        """无输出的命令"""
        result = run_with_limited_output(
            [sys.executable, "-c", ""],
            text=True,
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_very_large_output_default_limit(self) -> None:
        """大量输出但不超过默认限制（4MB）时不截断"""
        # 产生 ~100KB 输出
        code = "print('x' * 100000)"
        result = run_with_limited_output(
            [sys.executable, "-c", code],
        )
        assert result.stdout_truncated is False

    def test_explicit_large_limit(self) -> None:
        """显式设置大的限制，验证不截断"""
        code = "print('x' * 50000)"
        result = run_with_limited_output(
            [sys.executable, "-c", code],
            max_stdout_bytes=10 * 1024 * 1024,
        )
        assert result.stdout_truncated is False


# =============================================================================
# _read_limited_output
# =============================================================================


class TestReadLimitedOutput:
    """_read_limited_output 内部辅助函数"""

    def test_reads_full_content_when_under_limit(self) -> None:
        """内容小于限制时完整读取"""
        # 构造一个临时 BytesIO 风格的读取对象
        buf = MagicMock()
        buf.flush = MagicMock()
        buf.seek = MagicMock()
        buf.tell = MagicMock(return_value=10)
        buf.read = MagicMock(return_value=b"small data")

        data, truncated, size = _read_limited_output(
            buf, text=False, encoding=None, errors=None, max_bytes=4096,
        )
        assert data == b"small data"
        assert truncated is False
        assert size == 10

    def test_reads_truncated_when_over_limit(self) -> None:
        """内容超过限制时截断"""
        buf = MagicMock()
        buf.flush = MagicMock()
        buf.seek = MagicMock()
        buf.tell = MagicMock(return_value=5000)
        buf.read = MagicMock(return_value=b"truncated data e")

        data, truncated, size = _read_limited_output(
            buf, text=False, encoding=None, errors=None, max_bytes=10,
        )
        assert truncated is True
        assert size == 5000

    def test_zero_limit_returns_empty_bytes(self) -> None:
        """max_bytes=0 时空 bytes"""
        buf = MagicMock()
        buf.flush = MagicMock()
        buf.seek = MagicMock()
        buf.tell = MagicMock(return_value=999)
        buf.read = MagicMock(return_value=b"should not be read")

        data, truncated, size = _read_limited_output(
            buf, text=False, encoding=None, errors=None, max_bytes=0,
        )
        assert data == b""
        assert truncated is True
        assert size == 999
        # 当 limit == 0 时不应调用 read
        buf.read.assert_not_called()


# =============================================================================
# 集成: 标准 subprocess.run 对比
# =============================================================================


class TestRunWithLimitedOutputIntegration:
    """与标准 subprocess.run 对比验证"""

    def test_equivalent_to_run_for_small_output(self) -> None:
        """小输出时行为与 subprocess.run 一致"""
        actual = run_with_limited_output(
            [sys.executable, "-c", "print('hello world')"],
            text=True,
        )
        expected = subprocess.run(
            [sys.executable, "-c", "print('hello world')"],
            capture_output=True,
            text=True,
        )
        assert actual.returncode == expected.returncode
        assert actual.stdout.strip() == expected.stdout.strip()
        assert actual.stderr == expected.stderr

    def test_non_zero_return_code_preserved(self) -> None:
        """非零返回码正确传递"""
        result = run_with_limited_output(
            [sys.executable, "-c", "exit(42)"],
        )
        assert result.returncode == 42
