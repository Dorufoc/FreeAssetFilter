#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
subprocess 安全辅助函数。

该模块提供受限输出捕获，避免外部程序 stdout/stderr 过大时直接占用大量内存。
"""

from __future__ import annotations

import locale
import subprocess
import tempfile
from typing import Any, Optional, Sequence, Tuple


DEFAULT_MAX_OUTPUT_BYTES = 4 * 1024 * 1024


def _coerce_output_limit(value: Optional[int]) -> int:
    try:
        limit = int(value if value is not None else DEFAULT_MAX_OUTPUT_BYTES)
    except (TypeError, ValueError):
        limit = DEFAULT_MAX_OUTPUT_BYTES
    return max(0, limit)


def _decode_output(data: bytes, *, text: bool, encoding: Optional[str], errors: Optional[str]) -> Any:
    if not text:
        return data

    decode_encoding = encoding or locale.getpreferredencoding(False) or "utf-8"
    decode_errors = errors or "replace"
    return data.decode(decode_encoding, errors=decode_errors)


def _read_limited_output(
    stream,
    *,
    text: bool,
    encoding: Optional[str],
    errors: Optional[str],
    max_bytes: Optional[int],
) -> Tuple[Any, bool, int]:
    limit = _coerce_output_limit(max_bytes)
    stream.flush()
    stream.seek(0, 2)
    total_size = stream.tell()
    stream.seek(0)

    data = stream.read(limit) if limit > 0 else b""
    truncated = total_size > limit
    return _decode_output(data, text=text, encoding=encoding, errors=errors), truncated, total_size


def run_with_limited_output(
    args: Sequence[str],
    *,
    timeout: Optional[float] = None,
    text: bool = False,
    encoding: Optional[str] = None,
    errors: Optional[str] = None,
    check: bool = False,
    max_stdout_bytes: Optional[int] = None,
    max_stderr_bytes: Optional[int] = None,
    **popen_kwargs,
) -> subprocess.CompletedProcess:
    """
    运行子进程并限制最终返回的 stdout/stderr 大小。

    输出先写入临时文件，完成后只读取指定字节数，避免 capture_output=True
    在异常输出过大时把内容完整载入内存。
    """
    stdout_limit = _coerce_output_limit(max_stdout_bytes)
    stderr_limit = _coerce_output_limit(max_stderr_bytes)

    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            args,
            stdout=stdout_file,
            stderr=stderr_file,
            stdin=subprocess.DEVNULL,
            **popen_kwargs,
        )

        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            try:
                process.wait(timeout=2)
            except Exception:
                pass

            stdout, stdout_truncated, stdout_size = _read_limited_output(
                stdout_file,
                text=text,
                encoding=encoding,
                errors=errors,
                max_bytes=stdout_limit,
            )
            stderr, stderr_truncated, stderr_size = _read_limited_output(
                stderr_file,
                text=text,
                encoding=encoding,
                errors=errors,
                max_bytes=stderr_limit,
            )
            exc.stdout = stdout
            exc.output = stdout
            exc.stderr = stderr
            exc.stdout_truncated = stdout_truncated
            exc.stderr_truncated = stderr_truncated
            exc.stdout_size = stdout_size
            exc.stderr_size = stderr_size
            raise

        stdout, stdout_truncated, stdout_size = _read_limited_output(
            stdout_file,
            text=text,
            encoding=encoding,
            errors=errors,
            max_bytes=stdout_limit,
        )
        stderr, stderr_truncated, stderr_size = _read_limited_output(
            stderr_file,
            text=text,
            encoding=encoding,
            errors=errors,
            max_bytes=stderr_limit,
        )

    completed = subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)
    completed.stdout_truncated = stdout_truncated
    completed.stderr_truncated = stderr_truncated
    completed.stdout_size = stdout_size
    completed.stderr_size = stderr_size

    if check and returncode != 0:
        raise subprocess.CalledProcessError(returncode, args, output=stdout, stderr=stderr)

    return completed
