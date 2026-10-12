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
import time
from typing import Any, Callable, Optional, Sequence, Tuple


DEFAULT_MAX_OUTPUT_BYTES = 4 * 1024 * 1024


class SubprocessCancelled(Exception):
    """子进程被 ``should_stop`` 回调主动取消（已 kill，输出不可用）。"""


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


def _wait_with_cancel(
    process: subprocess.Popen,
    timeout: Optional[float],
    should_stop: Callable[[], bool],
    poll_interval: float,
) -> int:
    """轮询等待子进程结束（仅 ``should_stop`` 路径使用）。

    - ``should_stop()`` 命中：kill 进程并抛 :class:`SubprocessCancelled`；
    - 超时：抛 ``subprocess.TimeoutExpired``（由调用方统一 kill/读输出/附加
      属性，与 ``process.wait(timeout)`` 的既有语义一致）。

    Returns:
        int: 子进程退出码。
    """
    poll = max(0.05, float(poll_interval))
    deadline = (
        time.monotonic() + max(0.0, float(timeout))
        if timeout is not None
        else None
    )
    while True:
        if should_stop():
            process.kill()
            try:
                process.wait(timeout=2)
            except Exception:
                pass
            raise SubprocessCancelled(f"子进程已取消: {process.args!r}")
        wait_for = poll
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(cmd=process.args, timeout=timeout)
            wait_for = min(poll, remaining)
        try:
            return process.wait(timeout=wait_for)
        except subprocess.TimeoutExpired:
            continue


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
    should_stop: Optional[Callable[[], bool]] = None,
    poll_interval: float = 0.2,
    **popen_kwargs,
) -> subprocess.CompletedProcess:
    """
    运行子进程并限制最终返回的 stdout/stderr 大小。

    输出先写入临时文件，完成后只读取指定字节数，避免 capture_output=True
    在异常输出过大时把内容完整载入内存。

    可选 ``should_stop`` 回调：轮询等待期间每次检查，返回 True 时 kill
    子进程并抛出 :class:`SubprocessCancelled`（长耗时解压等场景的协作式
    取消）。不传时等待语义与历史实现完全一致（含超时 kill）。
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
            if should_stop is None:
                returncode = process.wait(timeout=timeout)
            else:
                returncode = _wait_with_cancel(
                    process, timeout, should_stop, poll_interval
                )
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
