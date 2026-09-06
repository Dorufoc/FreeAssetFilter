"""fd_capture 模块测试：fd 1/2 重定向捕获原生层输出。

必须用 subprocess（pytest 自身占用 fd 1/2，直接在进程内 dup2 会劫持
测试运行器的输出并泄漏 daemon 线程）。每个用例启动一个子进程，
子进程内 install → os.write/WriteFile → uninstall，父进程断言
控制台回显（captured stdout/stderr）与日志文件（[native-*] 前缀）。

子进程脚本退出前必须调用 uninstall_fd_capture()（排空管道 + join），
否则转发线程未来得及落盘会导致 flaky。
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _run_child(script_lines: List[str], log_arg: str) -> subprocess.CompletedProcess:
    """运行子进程脚本，返回 CompletedProcess（text 模式，解码容错）。"""
    script = "\n".join(script_lines) + "\n"
    return subprocess.run(
        [sys.executable, "-c", script, log_arg],
        capture_output=True,
        text=True,
        errors="replace",
        cwd=str(ROOT),
        timeout=60,
    )


_CHILD_PREAMBLE = [
    "import os, sys",
    "log_path = sys.argv[1]",
    "from freeassetfilter.utils.fd_capture import install_fd_capture, uninstall_fd_capture",
]

_CHILD_MARKER = _CHILD_PREAMBLE + [
    "install_fd_capture(log_path)",
    'os.write(2, b"faf-native-marker-123\\n")',
    'os.write(1, b"faf-native-stdout-123\\n")',
    "uninstall_fd_capture()",
]

_CHILD_BIG = _CHILD_PREAMBLE + [
    "install_fd_capture(log_path)",
    # 超长单行（> 64KB pipe 读块），含多字节中文，强制跨 os.read 块切分。
    'payload = (("中文跨块验证行-" * 6000) + "\\n").encode("utf-8")',
    "os.write(2, payload)",
    # 分两次写、切在多字节字符中间，强制字节残段跨次拼接。
    'data = (("跨次拼接-" * 2000) + "\\n").encode("utf-8")',
    "cut = len(data) // 2 + 1",
    "os.write(2, data[:cut])",
    "os.write(2, data[cut:])",
    'os.write(2, "结尾标记行-faf-big-end\\n".encode("utf-8"))',
    "uninstall_fd_capture()",
]

_CHILD_WRITEFILE = _CHILD_PREAMBLE + [
    "import ctypes",
    "from ctypes import wintypes",
    "install_fd_capture(log_path)",
    "kernel32 = ctypes.windll.kernel32",
    "kernel32.GetStdHandle.argtypes = [wintypes.DWORD]",
    "kernel32.GetStdHandle.restype = wintypes.HANDLE",
    "kernel32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]",
    "kernel32.WriteFile.restype = wintypes.BOOL",
    "handle = kernel32.GetStdHandle(wintypes.DWORD(-12))",
    'buf = ctypes.create_string_buffer(b"faf-writefile-marker-456\\n")',
    "written = wintypes.DWORD(0)",
    "ok = kernel32.WriteFile(handle, buf, len(b\"faf-writefile-marker-456\\n\"), ctypes.byref(written), None)",
    "assert ok, 'WriteFile failed'",
    "uninstall_fd_capture()",
]

_CHILD_UNINSTALL = _CHILD_PREAMBLE + [
    "install_fd_capture(log_path)",
    'os.write(2, b"faf-before-uninstall\\n")',
    "uninstall_fd_capture()",
    'os.write(2, b"faf-after-uninstall\\n")',
]

_CHILD_BAD_PATH = _CHILD_PREAMBLE + [
    "# 日志路径为目录：open 失败 → 仅回显不落盘，但不得抛异常。",
    "d = install_fd_capture(log_path)",
    "assert d.get(1) is not None and d.get(2) is not None, d",
    'os.write(2, b"faf-echo-only-marker\\n")',
    "uninstall_fd_capture()",
]

_CHILD_IDEMPOTENT = _CHILD_PREAMBLE + [
    "d1 = install_fd_capture(log_path)",
    "d2 = install_fd_capture(log_path)",
    "assert d2 is d1, 'repeat install must return existing dict'",
    "uninstall_fd_capture()",
    "uninstall_fd_capture()",
    'os.write(2, b"faf-idempotent-ok\\n")',
    "print('FD_CAPTURE_IDEMPOTENT_OK')",
]


def test_os_write_marker_echo_and_log(tmp_path: Path) -> None:
    """os.write(2/1) 的 marker 同时回显控制台与落盘（带前缀）。"""
    log = tmp_path / "fd.log"
    proc = _run_child(_CHILD_MARKER, str(log))
    assert proc.returncode == 0, f"child failed: {proc.stderr}"
    assert "faf-native-marker-123" in proc.stderr
    assert "faf-native-stdout-123" in proc.stdout
    text = log.read_text(encoding="utf-8")
    assert "[native-stderr] faf-native-marker-123" in text
    assert "[native-stdout] faf-native-stdout-123" in text


def test_multibyte_long_line_no_corruption(tmp_path: Path) -> None:
    """超长行 + 中文跨块/跨次写入：无 U+FFFD，行完整且仅一条前缀。"""
    log = tmp_path / "fd.log"
    proc = _run_child(_CHILD_BIG, str(log))
    assert proc.returncode == 0, f"child failed: {proc.stderr}"
    text = log.read_text(encoding="utf-8")
    assert "\ufffd" not in text
    expected_big = "中文跨块验证行-" * 6000
    assert f"[native-stderr] {expected_big}" in text
    expected_split = "跨次拼接-" * 2000
    assert f"[native-stderr] {expected_split}" in text
    assert "[native-stderr] 结尾标记行-faf-big-end" in text


@pytest.mark.skipif(os.name != "nt", reason="GetStdHandle/WriteFile only on Windows")
def test_writefile_via_getstdhandle_goes_to_log(tmp_path: Path) -> None:
    """经 GetStdHandle(-12) + WriteFile 直写 OS 句柄同样进日志（Rust eprintln! 路径）。"""
    log = tmp_path / "fd.log"
    proc = _run_child(_CHILD_WRITEFILE, str(log))
    assert proc.returncode == 0, f"child failed: {proc.stderr}"
    assert "faf-writefile-marker-456" in proc.stderr
    text = log.read_text(encoding="utf-8")
    assert "[native-stderr] faf-writefile-marker-456" in text


def test_no_log_after_uninstall(tmp_path: Path) -> None:
    """uninstall 后 os.write 不再进日志（但仍回显控制台）。"""
    log = tmp_path / "fd.log"
    proc = _run_child(_CHILD_UNINSTALL, str(log))
    assert proc.returncode == 0, f"child failed: {proc.stderr}"
    assert "faf-before-uninstall" in proc.stderr
    assert "faf-after-uninstall" in proc.stderr
    text = log.read_text(encoding="utf-8")
    assert "[native-stderr] faf-before-uninstall" in text
    assert "faf-after-uninstall" not in text


def test_unwritable_log_path_echo_only_no_raise(tmp_path: Path) -> None:
    """failure QA：日志路径不可写时仍返回有效 saved streams，仅回显不落盘，不抛异常。"""
    proc = _run_child(_CHILD_BAD_PATH, str(tmp_path))
    assert proc.returncode == 0, f"child failed: {proc.stderr}"
    assert "faf-echo-only-marker" in proc.stderr


def test_install_uninstall_idempotent(tmp_path: Path) -> None:
    """重复 install 返回已有字典，重复 uninstall 无操作。"""
    log = tmp_path / "fd.log"
    proc = _run_child(_CHILD_IDEMPOTENT, str(log))
    assert proc.returncode == 0, f"child failed: {proc.stderr}"
    assert "FD_CAPTURE_IDEMPOTENT_OK" in proc.stdout
