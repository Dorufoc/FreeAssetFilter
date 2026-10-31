"""fd 级 stdout/stderr 重定向捕获（原生层输出落盘）。

Python 层的 ``sys.stdout``/``sys.stderr`` 双写（TeeStream）捕获不到绕过
Python IO 栈的原生输出（如 Rust ``eprintln!``、MPV/FFmpeg 的 C 级写入，
它们走 OS 句柄 ``GetStdHandle``）。本模块在 fd 层面接管 fd 1/2：

``os.dup`` 备份原 fd → ``os.pipe`` + ``os.dup2`` 接管 fd 1/2 →
Windows 上同时 ``SetStdHandle`` 覆盖 OS 级标准句柄 →
每 fd 一个 daemon 转发线程排空管道（回显控制台 + 追加日志）。

转发线程约束（硬性）：
- 线程内禁止引用 ``sys.stdout``/``sys.stderr``/logger（防回环），
  只碰 ``saved_fd`` 与日志文件句柄；
- 回显失败或日志写失败时丢弃该数据但继续排空管道，
  线程绝不因 I/O 异常退出（否则管道满后原生写者永久阻塞）；
- 仅在 EOF（``os.read`` 返回 ``b''``）时冲刷残留缓冲后退出。

仅依赖标准库。MPV/FFmpeg 的覆盖为待实测假设，不做保证。
"""

import io
import os
import sys
import threading
from typing import Dict, Optional

_STDOUT_FD = 1
_STDERR_FD = 2
_STD_OUTPUT_HANDLE = -11
_STD_ERROR_HANDLE = -12
_READ_CHUNK_SIZE = 65536
_JOIN_TIMEOUT = 2.0

_FD_TO_PREFIX = {
    _STDOUT_FD: "[native-stdout] ",
    _STDERR_FD: "[native-stderr] ",
}

_FD_TO_STD_HANDLE_ID = {
    _STDOUT_FD: _STD_OUTPUT_HANDLE,
    _STDERR_FD: _STD_ERROR_HANDLE,
}

_state_lock = threading.Lock()
_installed = False
_saved_fds: Dict[int, Optional[int]] = {}
_saved_handles: Dict[int, object] = {}
_forward_threads: Dict[int, threading.Thread] = {}
_log_file_path: Optional[str] = None
_result: Dict[int, Optional[io.TextIOWrapper]] = {}

# 日志落盘共享句柄 + 写锁（Windows 必需）：
# 双转发线程若各持一个 open(path, 'a') 句柄并发写，各自文件指针均从
# 打开时的文件尾（常为 0）起算，后写者静默覆盖先写者的数据（write 照常
# 返回成功，文件里只剩一行）。因此日志文件只 open 一次、所有写操作持
# 同一把锁串行化（含 flush），从根本上消除覆盖丢失。
_log_lock = threading.Lock()
_log_stream: Optional[io.TextIOWrapper] = None


def _get_stream_encoding(fd: int) -> str:
    """获取 fd 对应原始流的编码，失败时回退到 utf-8。

    Args:
        fd: 文件描述符（1 或 2）。

    Returns:
        编码名称。
    """
    name = "__stdout__" if fd == _STDOUT_FD else "__stderr__"
    try:
        stream = getattr(sys, name, None)
        encoding = getattr(stream, "encoding", None)
        if encoding:
            return str(encoding)
    except (AttributeError, ValueError):
        pass
    return "utf-8"


def _make_saved_text_stream(saved_fd: int, encoding: str) -> Optional[io.TextIOWrapper]:
    """为已备份的 saved_fd 创建文本包装流（供 TeeStream 回显用）。

    Args:
        saved_fd: ``os.dup`` 备份的原始 fd。
        encoding: 文本编码（原流编码或 utf-8）。

    Returns:
        TextIOWrapper，失败时返回 None（不抛异常）。
    """
    try:
        raw = os.fdopen(os.dup(saved_fd), "wb")
        return io.TextIOWrapper(
            raw, encoding=encoding or "utf-8", errors="replace", write_through=True
        )
    except (OSError, ValueError, TypeError):
        return None


def _write_log_line(prefix: str, text: str) -> None:
    """经共享句柄追加一行日志（持锁串行化，失败只丢弃本行）。

    Args:
        prefix: 日志行前缀（[native-stdout] / [native-stderr]）。
        text: 已解码的行文本（不含换行）。
    """
    with _log_lock:
        if _log_stream is None:
            return
        try:
            _log_stream.write(prefix + text + "\n")
            _log_stream.flush()
        except (OSError, IOError, ValueError, TypeError):
            pass


def _forward_loop(read_fd: int, saved_fd: int, prefix: str) -> None:
    """转发线程主循环：排空管道，回显控制台 + 追加日志。

    字节累积进缓冲区，按 ``b'\\n'`` 切分（多字节 UTF-8 绝不跨块截断），
    完整行解码后经共享句柄落盘，不完整段保留到下一次。任何 I/O 异常
    只丢弃当批数据，线程继续排空；仅 EOF 时冲刷残留后退出。

    Args:
        read_fd: 管道读端。
        saved_fd: 备份的原始 fd（回显目标）。
        prefix: 日志行前缀。
    """
    buffer = b""
    try:
        while True:
            try:
                chunk = os.read(read_fd, _READ_CHUNK_SIZE)
            except (OSError, ValueError):
                continue
            if chunk == b"":
                break
            try:
                os.write(saved_fd, chunk)
            except (OSError, ValueError):
                pass
            buffer += chunk
            parts = buffer.split(b"\n")
            buffer = parts.pop()
            for line_bytes in parts:
                try:
                    text = line_bytes.decode("utf-8", errors="replace")
                except (ValueError, TypeError):
                    continue
                _write_log_line(prefix, text)
    finally:
        try:
            if buffer:
                text = buffer.decode("utf-8", errors="replace")
                _write_log_line(prefix, text)
        except (ValueError, TypeError):
            pass
        try:
            os.close(read_fd)
        except (OSError, ValueError):
            pass


def _capture_original_std_handle(std_handle_id: int) -> object:
    """用 GetStdHandle 捕获当前 OS 标准句柄（Windows）。

    Args:
        std_handle_id: -11（stdout）或 -12（stderr）。

    Returns:
        原句柄，失败时返回 None（不抛异常）。
    """
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel32.GetStdHandle.restype = wintypes.HANDLE
        return kernel32.GetStdHandle(wintypes.DWORD(std_handle_id))
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def _set_std_handle(std_handle_id: int, handle: object) -> None:
    """用 SetStdHandle 设置 OS 标准句柄（Windows），失败不抛异常。

    Args:
        std_handle_id: -11（stdout）或 -12（stderr）。
        handle: 要设置的新句柄。
    """
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
        kernel32.SetStdHandle.restype = wintypes.BOOL
        kernel32.SetStdHandle(wintypes.DWORD(std_handle_id), handle)
    except (OSError, ValueError, AttributeError, TypeError):
        pass


def _redirect_fd(fd: int) -> Optional[io.TextIOWrapper]:
    """接管单个 fd，启动转发线程。

    Args:
        fd: 1 或 2。

    Returns:
        saved 文本流，失败时返回 None（不抛异常）。
    """
    try:
        saved_fd = os.dup(fd)
    except (OSError, ValueError):
        _saved_fds[fd] = None
        return None

    read_fd = -1
    try:
        read_fd, write_fd = os.pipe()
        try:
            os.dup2(write_fd, fd)
        finally:
            try:
                os.close(write_fd)
            except (OSError, ValueError):
                pass
    except (OSError, ValueError):
        try:
            if read_fd >= 0:
                os.close(read_fd)
        except (OSError, ValueError):
            pass
        try:
            os.close(saved_fd)
        except (OSError, ValueError):
            pass
        _saved_fds[fd] = None
        return None

    _saved_fds[fd] = saved_fd

    if os.name == "nt":
        std_handle_id = _FD_TO_STD_HANDLE_ID[fd]
        original = _capture_original_std_handle(std_handle_id)
        _saved_handles[fd] = original
        try:
            import msvcrt

            _set_std_handle(std_handle_id, msvcrt.get_osfhandle(fd))
        except (OSError, IOError, ValueError):
            pass

    encoding = _get_stream_encoding(fd)
    saved_stream = _make_saved_text_stream(saved_fd, encoding)

    thread = threading.Thread(
        target=_forward_loop,
        args=(read_fd, saved_fd, _FD_TO_PREFIX[fd]),
        name=f"fd-capture-{fd}",
        daemon=True,
    )
    _forward_threads[fd] = thread
    thread.start()
    return saved_stream


def install_fd_capture(log_file_path: str) -> Dict[int, Optional[io.TextIOWrapper]]:
    """安装 fd 1/2 重定向捕获原生层输出。

    幂等：重复调用返回已有句柄字典。任何单 fd 失败只降级该 fd
    （该项为 None），不抛异常。

    Args:
        log_file_path: 日志文件路径（转发线程追加写入）。

    Returns:
        ``{1: saved_stdout_text_stream_or_None, 2: saved_stderr_text_stream_or_None}``。
    """
    global _installed, _log_file_path, _result, _log_stream
    with _state_lock:
        if _installed:
            return _result
        _log_file_path = log_file_path
        try:
            _log_stream = open(log_file_path, "a", encoding="utf-8", buffering=1)
        except (OSError, IOError, ValueError, TypeError):
            _log_stream = None
        _result = {
            _STDOUT_FD: _redirect_fd(_STDOUT_FD),
            _STDERR_FD: _redirect_fd(_STDERR_FD),
        }
        _installed = True
        return _result


def uninstall_fd_capture() -> None:
    """恢复 fd 1/2 与 OS 标准句柄，排空管道后关闭备份。

    ``os.dup2(saved_fd, fd)`` 释放管道写端全部引用，读线程读到 EOF
    后冲刷残留并退出；``join(timeout=2)`` 后关闭 saved fd。
    幂等：重复调用无操作，不抛异常。
    """
    global _installed, _log_file_path, _result, _log_stream
    with _state_lock:
        if not _installed:
            return
        for fd in (_STDOUT_FD, _STDERR_FD):
            saved_fd = _saved_fds.get(fd)
            if saved_fd is not None:
                try:
                    os.dup2(saved_fd, fd)
                except (OSError, ValueError):
                    pass
            if os.name == "nt":
                original = _saved_handles.get(fd)
                if original is not None:
                    _set_std_handle(_FD_TO_STD_HANDLE_ID[fd], original)
        for fd in (_STDOUT_FD, _STDERR_FD):
            thread = _forward_threads.get(fd)
            if thread is not None:
                try:
                    thread.join(timeout=_JOIN_TIMEOUT)
                except (OSError, ValueError, RuntimeError):
                    pass
        for fd in (_STDOUT_FD, _STDERR_FD):
            saved_fd = _saved_fds.get(fd)
            if saved_fd is not None:
                try:
                    os.close(saved_fd)
                except (OSError, ValueError):
                    pass
        with _log_lock:
            try:
                if _log_stream is not None:
                    _log_stream.close()
            except (OSError, IOError, ValueError, TypeError):
                pass
            _log_stream = None
        _saved_fds.clear()
        _saved_handles.clear()
        _forward_threads.clear()
        _log_file_path = None
        _result = {}
        _installed = False
