"""可复用的假 `spk_updater` 边车，用于 Python 桥与下载流程测试。

该脚本通过 ``python tests/support/fake_updater.py`` 启动，严格镜像真实
`spk_updater.exe` 的 NDJSON 线路形状（一行一个 JSON 对象、UTF-8、响应回显
请求 ``id``）：

* ``hello`` / ``check`` / ``verify`` / ``shutdown``
* ``check``/``verify`` 在 worker 线程执行，支持 ``delay``（秒）、``crash``
  （写 stderr 后 ``os._exit(3)``）、``stderr_flood``（写 N 字节 stderr）、
  ``bad_json``（先写一条畸形行再写合法响应）以及 ``echo``（UTF-8 往返）。
* ``download`` 在 worker 线程执行，实现未来的下载契约：``<dest>.part``
  增量写入、``<dest>.part.json`` 元数据；paused/shutdown 保留两者；done
  原子改名并删除 meta；cancel/error 删除两者。
* ``pause``/``cancel`` 校验 ``params.target`` 与当前下载 id；不匹配时返回
  ``accepted:false`` 且不改变任何状态。
* abort 模式：控制请求携带 ``"abort": true`` 或环境变量
  ``SPK_FAKE_ABORT`` 非空时，写 ack → 写 paused/cancelled 终态 →
  ``os._exit(0)``（模拟真实边车的 watchdog 强制退出）。
* ``SPK_FAKE_IGNORE_SHUTDOWN`` 非空时，`shutdown` 不写 ack 且主循环继续
  读取 stdin，用于验证桥的 terminate/kill 预算分支。
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Optional

PROTOCOL_VERSION = 1
VERSION = "0.0.0-fake"
CHUNK_DEFAULT = 64 * 1024


def _env_int(name: str, default: int) -> int:
    """读取整数环境变量；非法或缺失时返回默认值。"""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    """读取浮点环境变量；非法或缺失时返回默认值。"""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default

_write_lock = threading.Lock()
_state_lock = threading.Lock()
_current: Optional[dict[str, Any]] = None
_download_thread: Optional[threading.Thread] = None
_exiting = False


def _write_value(value: dict[str, Any]) -> None:
    """序列化并 flush 一条 NDJSON 响应/事件。"""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    _write_raw(text)


def _write_raw(text: str) -> None:
    """写入一行原始文本（用于畸形 JSON 行测试）。"""
    try:
        with _write_lock:
            sys.stdout.write(text)
            if not text.endswith("\n"):
                sys.stdout.write("\n")
            sys.stdout.flush()
    except OSError:
        os._exit(0)


def _write_stderr(text: str) -> None:
    """写入 stderr 并 flush。"""
    try:
        sys.stderr.write(text)
        sys.stderr.flush()
    except OSError:
        pass


def _success(request_id: str, result: Any) -> None:
    _write_value({"id": request_id, "ok": True, "result": result})


def _failure(request_id: str, code: str, message: str) -> None:
    _write_value(
        {
            "id": request_id,
            "ok": False,
            "error": {
                "code": code,
                "message": message,
                "retryable": code in {"timeout", "network", "http_status"},
            },
        }
    )


def _maybe_bad_json(params: dict[str, Any]) -> None:
    """按参数先写一条畸形行，验证桥的跳过逻辑。"""
    if params.get("bad_json"):
        _write_raw('{"id":"broken", "ok":')


def _abort_requested(params: dict[str, Any]) -> Optional[str]:
    """解析 abort 模式（暂停/取消）；未启用时返回 ``None``。"""
    raw = params.get("abort")
    if raw is None:
        raw = os.environ.get("SPK_FAKE_ABORT")
    if not raw:
        return None
    text = str(raw).strip().lower()
    if text in {"cancel", "cancelled", "canceled"}:
        return "cancelled"
    return "paused"


def _body_for(params: dict[str, Any]) -> bytes:
    """根据参数生成下载正文（绝不访问网络）。"""
    body = params.get("body")
    if isinstance(body, str):
        return body.encode("utf-8")
    if isinstance(body, list):
        return bytes(int(part) & 0xFF for part in body)
    size = params.get("body_size")
    if size is None:
        size = params.get("expected_size", 1024 * 1024)
    total = max(0, int(size))
    return bytes((index % 251) for index in range(total))


def _meta_path(dest: Path) -> Path:
    """``<dest>.part.json``。"""
    return Path(str(dest) + ".part.json")


def _part_path(dest: Path) -> Path:
    """``<dest>.part``。"""
    return Path(str(dest) + ".part")


def _remove_quietly(path: Path) -> None:
    """删除文件，忽略不存在。"""
    try:
        path.unlink()
    except OSError:
        pass


def _cleanup_artifacts(dest: Path) -> None:
    """删除 part 与 meta。"""
    _remove_quietly(_part_path(dest))
    _remove_quietly(_meta_path(dest))


def _write_meta(
    dest: Path,
    params: dict[str, Any],
    total: int,
    sha256: str,
) -> None:
    """原子写入 ``<dest>.part.json``（tmp + replace）。"""
    meta = {
        "schema": 1,
        "source_url": str(params.get("source_url", "")),
        "etag": params.get("etag"),
        "total": total,
        "sha256": sha256,
        "expected_size": int(params.get("expected_size", total)),
    }
    target = _meta_path(dest)
    temp = Path(str(target) + ".tmp")
    temp.write_text(json.dumps(meta), encoding="utf-8")
    os.replace(temp, target)


def _claim_terminal(state: dict[str, Any]) -> bool:
    """抢占某次下载的唯一终态输出权。"""
    with _state_lock:
        if state.get("terminal_claimed"):
            return False
        state["terminal_claimed"] = True
        return True


def _state_snapshot(
    state: dict[str, Any],
    token: int,
) -> tuple[bool, bool, bool]:
    """返回 (cancelled, paused, token_current)。"""
    with _state_lock:
        return (
            bool(state.get("cancelled")),
            bool(state.get("paused")),
            token == state.get("live_token"),
        )


def _emit_event(request_id: str, event: dict[str, Any]) -> None:
    """写一条异步事件。"""
    payload = {"event": event.pop("event"), "id": request_id}
    payload.update(event)
    _write_value(payload)


def _terminal(
    state: dict[str, Any],
    state_name: str,
    *,
    downloaded: int,
    sha256: Optional[str],
) -> None:
    """写下载终态响应（每个下载只允许一次）。"""
    if not _claim_terminal(state):
        return
    dest: Path = state["dest"]
    if state_name in {"done", "paused", "cancelled"}:
        with _state_lock:
            state["finished"] = state_name != "paused"
            if state_name == "paused":
                state["paused"] = True
    _success(
        state["id"],
        {
            "state": state_name,
            "path": str(dest),
            "downloaded": downloaded,
            "sha256": sha256,
        },
    )


def _download_worker(
    state: dict[str, Any],
    params: dict[str, Any],
    token: int,
) -> None:
    """执行一次假下载（支持暂停/取消与断点续传）。"""
    request_id = state["id"]
    dest: Path = state["dest"]
    body: bytes = state["body"]
    total = len(body)
    expected = str(params.get("expected_sha256") or hashlib.sha256(body).hexdigest())
    part = _part_path(dest)
    meta = _meta_path(dest)
    chunk_size = max(1, _env_int("SPK_FAKE_CHUNK_SIZE", int(params.get("chunk_size", CHUNK_DEFAULT))))
    delay = max(0.0, _env_float("SPK_FAKE_CHUNK_DELAY", float(params.get("chunk_delay", 0.0))))
    crash_at = _env_int("SPK_FAKE_CRASH_AT", 0)

    _emit_event(request_id, {"event": "state", "state": "resolving"})
    dest.parent.mkdir(parents=True, exist_ok=True)

    offset = 0
    if part.exists() and meta.exists():
        try:
            offset = min(part.stat().st_size, total)
        except OSError:
            offset = 0
    _write_meta(dest, params, total, expected)
    _emit_event(request_id, {"event": "state", "state": "downloading"})

    abort_mode = state.get("abort_mode")
    with open(part, "ab" if offset else "wb") as handle:
        position = offset
        while position < total:
            cancelled, paused, current = _state_snapshot(state, token)
            if not current:
                return
            if cancelled:
                handle.flush()
                # Windows 上打开中的文件无法删除：先关闭句柄再清理工件。
                handle.close()
                _cleanup_artifacts(dest)
                _terminal(state, "cancelled", downloaded=0, sha256=None)
                return
            if paused:
                handle.flush()
                os.fsync(handle.fileno())
                _terminal(state, "paused", downloaded=position, sha256=None)
                return
            take = min(chunk_size, total - position)
            handle.write(body[position : position + take])
            handle.flush()
            position += take
            _emit_event(
                request_id,
                {
                    "event": "progress",
                    "downloaded": position,
                    "total": total,
                    "speed_bps": 0,
                },
            )
            if crash_at and position >= crash_at:
                _write_stderr("fake updater download crash: simulated native failure\n")
                _write_stderr("fake updater download crash: stderr tail marker\n")
                os._exit(3)
            if abort_mode:
                handle.flush()
                os.fsync(handle.fileno())
                _terminal(
                    state,
                    str(abort_mode),
                    downloaded=position,
                    sha256=None,
                )
                _force_exit()
            if delay:
                time.sleep(delay)

    cancelled, paused, current = _state_snapshot(state, token)
    if not current:
        return
    if cancelled:
        _cleanup_artifacts(dest)
        _terminal(state, "cancelled", downloaded=0, sha256=None)
        return
    if paused:
        _terminal(state, "paused", downloaded=position, sha256=None)
        return

    _emit_event(request_id, {"event": "state", "state": "verifying"})
    digest = hashlib.sha256()
    with open(part, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_DEFAULT), b""):
            digest.update(block)
    actual = digest.hexdigest()
    if params.get("error") == "checksum" or actual != expected:
        _cleanup_artifacts(dest)
        if _claim_terminal(state):
            with _state_lock:
                state["finished"] = True
            _failure(request_id, "checksum_mismatch", "sha256 不匹配")
        return
    os.replace(part, dest)
    _remove_quietly(meta)
    _terminal(state, "done", downloaded=total, sha256=actual)


def _force_exit() -> None:
    """立即退出进程，模拟边车 watchdog 的 abort 退出。"""
    global _exiting
    _exiting = True
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def _handle_download(request_id: str, params: dict[str, Any]) -> None:
    """登记并启动下载 worker。"""
    global _current, _download_thread

    dest_raw = params.get("dest_path")
    if not isinstance(dest_raw, str) or not dest_raw:
        _failure(request_id, "bad_params", "download.dest_path 缺失或不是字符串")
        return
    dest = Path(dest_raw)
    body = _body_for(params)
    abort_mode = _abort_requested(params)
    if abort_mode:
        abort_mode = "cancelled" if abort_mode == "cancelled" else "paused"

    busy = False
    stale_dest: Optional[Path] = None
    with _state_lock:
        current = _current
        if current is not None:
            if current["id"] == request_id and current.get("paused") and not current.get(
                "finished"
            ):
                current["paused"] = False
                current["cancelled"] = False
                current["terminal_claimed"] = False
                current["token"] += 1
                current["live_token"] = current["token"]
                current["body"] = body
                current["abort_mode"] = abort_mode
                state = current
            elif not current.get("finished") and not current.get("paused"):
                busy = True
                state = current
            else:
                if current["id"] != request_id:
                    stale_dest = current["dest"]
                    current["finished"] = True
                    current["live_token"] += 1
                state = {
                    "id": request_id,
                    "dest": dest,
                    "body": body,
                    "paused": False,
                    "cancelled": False,
                    "finished": False,
                    "terminal_claimed": False,
                    "token": 1,
                    "live_token": 1,
                    "abort_mode": abort_mode,
                }
                _current = state
        else:
            state = {
                "id": request_id,
                "dest": dest,
                "body": body,
                "paused": False,
                "cancelled": False,
                "finished": False,
                "terminal_claimed": False,
                "token": 1,
                "live_token": 1,
                "abort_mode": abort_mode,
            }
            _current = state
        if not busy:
            token = int(state["token"])
            _download_thread = threading.Thread(
                target=_download_worker,
                args=(state, dict(params), token),
                name=f"fake-download-{request_id}",
                daemon=True,
            )
            worker = _download_thread

    if busy:
        _failure(request_id, "busy", "已有下载在进行中")
        return
    if stale_dest is not None:
        _cleanup_artifacts(stale_dest)
    worker.start()


def _handle_control(request_id: str, cmd: str, params: dict[str, Any]) -> None:
    """处理 pause/cancel，校验 target 并可选强制退出。"""
    global _current
    target = params.get("target")
    if not isinstance(target, str) or not target:
        _failure(request_id, "bad_params", f"{cmd}.params.target 缺失或不是非空字符串")
        return

    accepted = False
    cleanup_now: Optional[Path] = None
    abort_reason = _abort_requested(params)
    state_for_abort: Optional[dict[str, Any]] = None

    with _state_lock:
        current = _current
        if current is not None and current["id"] == target and not current.get("finished"):
            if cmd == "pause":
                if current.get("paused"):
                    accepted = True
                else:
                    current["paused"] = True
                    accepted = True
                    state_for_abort = current
            else:
                accepted = True
                if os.environ.get("SPK_FAKE_IGNORE_CANCEL"):
                    # 模拟取消与完成竞态：ack 已接受但 worker 继续跑完。
                    pass
                elif current.get("paused"):
                    # 已暂停的下载立即删除工件；不会再有终态行。
                    cleanup_now = current["dest"]
                    current["finished"] = True
                    current["cancelled"] = True
                else:
                    current["cancelled"] = True
                    state_for_abort = current

    if cleanup_now is not None:
        _cleanup_artifacts(cleanup_now)

    _success(request_id, {"accepted": accepted})

    if accepted and state_for_abort is not None and abort_reason:
        dest = state_for_abort["dest"]
        downloaded = 0
        part = _part_path(dest)
        try:
            downloaded = part.stat().st_size
        except OSError:
            downloaded = 0
        _terminal(
            state_for_abort,
            str(abort_reason),
            downloaded=downloaded,
            sha256=None,
        )
        _force_exit()
        return


def _real_identity(path: Path) -> tuple[int, int]:
    """返回真实 Windows 文件标识 ``(volume_serial, file_index)``。"""
    class _Info(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        0x80000000,  # GENERIC_READ
        0x00000001,  # FILE_SHARE_READ
        None,
        3,  # OPEN_EXISTING
        0x80,  # FILE_ATTRIBUTE_NORMAL
        None,
    )
    raw = getattr(handle, "value", handle)
    if not raw or int(raw) == -1:
        raise OSError(ctypes.get_last_error(), f"无法打开文件: {path}")
    try:
        get_info = kernel32.GetFileInformationByHandle
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Info)]
        get_info.restype = wintypes.BOOL
        info = _Info()
        if not get_info(wintypes.HANDLE(raw), ctypes.byref(info)):
            raise OSError(ctypes.get_last_error(), "读取文件标识失败")
        index = (int(info.nFileIndexHigh) << 32) | int(info.nFileIndexLow)
        return int(info.dwVolumeSerialNumber), index
    finally:
        close = kernel32.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        close(wintypes.HANDLE(raw))


def _worker_check(request_id: str, cmd: str, params: dict[str, Any]) -> None:
    """在 worker 线程执行 check/verify/sleep。"""
    try:
        delay = float(params.get("delay", 0.0))
    except (TypeError, ValueError):
        delay = 0.0
    if delay > 0:
        time.sleep(delay)
    if params.get("crash"):
        _write_stderr("fake updater crash: simulated native failure\n")
        _write_stderr("fake updater crash: stderr tail marker\n")
        os._exit(3)
    flood = params.get("stderr_flood")
    if flood:
        remaining = max(0, int(flood))
        block = b"e" * 4096
        while remaining > 0:
            take = min(remaining, len(block))
            sys.stderr.write(block[:take].decode("ascii"))
            remaining -= take
        sys.stderr.flush()
    _maybe_bad_json(params)
    if cmd == "verify":
        path = Path(str(params.get("path", "")))
        expected = str(params.get("sha256", ""))
        if os.environ.get("SPK_FAKE_REAL_VERIFY"):
            try:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                identity = _real_identity(path)
                match = actual.lower() == expected.lower()
            except OSError:
                actual = ""
                identity = (0, 0)
                match = False
        else:
            actual = expected
            identity = (1, 1)
            match = True
        _success(
            request_id,
            {
                "match": match,
                "path": str(path),
                "actual": actual,
                "volume_serial": identity[0],
                "file_index": identity[1],
            },
        )
        return
    if cmd == "check":
        result_path = os.environ.get("SPK_FAKE_CHECK_RESULT")
        if result_path and Path(result_path).is_file():
            try:
                payload = json.loads(Path(result_path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict):
                _success(request_id, payload)
                return
    _success(
        request_id,
        {
            "echo": params.get("echo"),
            "delay": delay,
            "cmd": cmd,
        },
    )


def _handle_shutdown(request_id: str) -> bool:
    """请求暂停、等待 worker（≤1.5s）、写 ack 并让主循环退出。

    Returns:
        bool: 已接受 shutdown 并写出 ack 时为 ``True``；被
        ``SPK_FAKE_IGNORE_SHUTDOWN`` 抑制时为 ``False``，调用方必须继续
        读取 stdin，让进程保持存活直到被 terminate/kill。
    """
    global _exiting
    if os.environ.get("SPK_FAKE_IGNORE_SHUTDOWN"):
        # 测试 stop() 的 terminate/kill 预算分支：故意不 ack、不退出。
        return False
    with _state_lock:
        current = _current
        if current is not None and not current.get("finished"):
            current["paused"] = True
        worker = _download_thread
    if worker is not None and worker.is_alive():
        worker.join(timeout=1.5)
    _success(request_id, {})
    _exiting = True
    return True


def _main() -> int:
    """NDJSON 主循环。"""
    global _current, _exiting
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(request, dict):
            continue
        request_id = request.get("id")
        cmd = request.get("cmd")
        params = request.get("params")
        if not isinstance(request_id, str) or not isinstance(cmd, str):
            continue
        if not isinstance(params, dict):
            params = {}

        if cmd == "hello":
            _maybe_bad_json(params)
            _success(
                request_id,
                {"protocol": PROTOCOL_VERSION, "version": VERSION},
            )
        elif cmd in {"check", "verify", "sleep"}:
            _maybe_bad_json(params)
            threading.Thread(
                target=_worker_check,
                args=(request_id, cmd, dict(params)),
                name=f"fake-{cmd}-{request_id}",
                daemon=True,
            ).start()
        elif cmd == "download":
            _maybe_bad_json(params)
            _handle_download(request_id, params)
        elif cmd in {"pause", "cancel"}:
            _handle_control(request_id, cmd, params)
        elif cmd == "shutdown":
            if _handle_shutdown(request_id):
                break
        else:
            _maybe_bad_json(params)
            _failure(request_id, "bad_command", f"未知命令：{cmd}")

    if not _exiting:
        with _state_lock:
            current = _current
            if current is not None and not current.get("finished"):
                current["paused"] = True
            worker = _download_thread
        if worker is not None and worker.is_alive():
            worker.join(timeout=1.5)
    return 0


def main() -> None:
    """进程入口：强制 UTF-8 管线后进入 NDJSON 循环。"""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        sys.exit(_main())
    except KeyboardInterrupt:
        sys.exit(0)
    except BrokenPipeError:
        os._exit(0)


if __name__ == "__main__":
    main()
