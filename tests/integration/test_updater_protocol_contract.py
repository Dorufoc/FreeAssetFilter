# -*- coding: utf-8 -*-
"""Protocol contract against the real ``spk_updater.exe`` sidecar.

The sidecar downloads from a loopback ``ThreadingHTTPServer`` stub with Range
support. No real network, installer, UAC prompt or repository mutation is
involved. The real executable is a hard prerequisite: missing => pytest.fail.
"""

from __future__ import annotations

import hashlib
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest

from sopeek.core.native.bridges.spk_updater_bridge import SpkUpdaterBridge

pytestmark = pytest.mark.integration

_EXE = (
    Path(__file__).resolve().parents[2]
    / "sopeek"
    / "core"
    / "native"
    / "bin"
    / "spk_updater.exe"
)
_ETAG = '"contract-etag"'
_PAYLOAD = bytes((index * 7 + 11) % 256 for index in range(2 * 1024 * 1024))
_SHA256 = hashlib.sha256(_PAYLOAD).hexdigest()
_CHUNK = 16 * 1024


class _RangeHandler(BaseHTTPRequestHandler):
    """Serve ``_PAYLOAD`` with byte-range resume support."""

    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *args: Any) -> None:
        """Keep pytest output quiet."""
        return

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        server = self.server
        payload: bytes = server.payload  # type: ignore[attr-defined]
        delay: float = server.delay  # type: ignore[attr-defined]
        requests: list[dict[str, Any]] = server.requests  # type: ignore[attr-defined]
        lock: threading.Lock = server.lock  # type: ignore[attr-defined]
        total = len(payload)
        raw_range = self.headers.get("Range")
        start = 0
        if raw_range:
            try:
                start = int(raw_range.split("=", 1)[1].split("-", 1)[0])
            except (IndexError, ValueError):
                self.send_error(400, "bad range")
                return
        with lock:
            requests.append(
                {
                    "path": self.path,
                    "range": raw_range,
                    "if_range": self.headers.get("If-Range"),
                }
            )
        if start >= total:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{total}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        status = 206 if start > 0 else 200
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(total - start))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("ETag", _ETAG)
        self.send_header("Content-Encoding", "identity")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{total - 1}/{total}")
        self.end_headers()

        try:
            for position in range(start, total, _CHUNK):
                block = payload[position : position + _CHUNK]
                self.wfile.write(block)
                self.wfile.flush()
                if delay:
                    time.sleep(delay)
        except (BrokenPipeError, ConnectionResetError):
            return


class _RangeServer(ThreadingHTTPServer):
    """Threaded HTTP server carrying the payload/request log."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, payload: bytes, *, delay: float) -> None:
        self.payload = payload
        self.delay = delay
        self.requests: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        super().__init__(("127.0.0.1", 0), _RangeHandler)

    @property
    def base_url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"


@pytest.fixture(scope="module")
def updater_exe() -> Path:
    """Hard-gate the real sidecar; never skip when it is missing."""
    if not _EXE.is_file():
        pytest.fail(f"必需的真实 spk_updater.exe 不存在: {_EXE}")
    return _EXE


@pytest.fixture
def bridge(updater_exe: Path) -> Iterator[SpkUpdaterBridge]:
    """Start the real sidecar and always reap it."""
    instance = SpkUpdaterBridge(executable=updater_exe)
    try:
        assert instance.ensure_started() is True
        hello = instance.request("hello", {}, timeout=5.0)
        assert hello["ok"] is True
        assert hello["result"]["protocol"] == 1
        yield instance
    finally:
        try:
            instance.stop(timeout=2.0)
        finally:
            instance.close()
    assert instance.is_running() is False


@pytest.fixture
def range_server() -> Iterator[_RangeServer]:
    """Run a loopback Range server with continuous, bounded progress."""
    server = _RangeServer(_PAYLOAD, delay=0.006)
    thread = threading.Thread(
        target=server.serve_forever,
        name="contract-range-server",
        daemon=True,
    )
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)
        assert not thread.is_alive()


def _assert_ack(response: dict[str, Any], target_id: str) -> None:
    """Assert the control ack envelope and that it is not the download id."""
    assert response["ok"] is True
    assert isinstance(response["id"], str) and response["id"]
    assert response["id"] != target_id
    assert response["result"]["accepted"] is True


def _params(
    server: _RangeServer, dest: Path, *, expected_size: int = len(_PAYLOAD)
) -> dict[str, Any]:
    """Build legal download parameters for the loopback stub."""
    return {
        "source_url": f"{server.base_url}/asset.exe",
        "dest_path": str(dest),
        "expected_sha256": _SHA256,
        "expected_size": expected_size,
        "allow_insecure_localhost": True,
    }


def _artifact_paths(dest: Path) -> tuple[Path, Path]:
    """Return ``(.part, .part.json)`` for ``dest``."""
    return Path(str(dest) + ".part"), Path(str(dest) + ".part.json")


class TestUpdaterProtocolContract:
    """Real sidecar: download -> pause -> resume -> cancel -> verify."""

    def test_download_pause_resume_cancel_verify_and_default_idle(
        self,
        bridge: SpkUpdaterBridge,
        range_server: _RangeServer,
        tmp_path: Path,
    ) -> None:
        """Exercise the full protocol and continuous-progress idle behavior."""
        dest = tmp_path / "download" / "installer.exe"
        part, meta = _artifact_paths(dest)
        params = _params(range_server, dest)

        first_progress = threading.Event()

        def _on_first(event: dict[str, Any]) -> None:
            if event.get("event") == "progress" and int(event.get("downloaded", 0)) > 0:
                first_progress.set()

        bridge.download_begin(params, _on_first, "contract-active")
        assert first_progress.wait(10.0), "download never produced progress"
        pause_ack = bridge.pause("contract-active")
        _assert_ack(pause_ack, "contract-active")
        paused = bridge.download_wait("contract-active", timeout=15.0)
        assert paused["ok"] is True
        assert paused["result"]["state"] == "paused"
        assert part.exists()
        assert meta.exists()

        # Resume the same request id; the server must receive a Range request.
        resumed = threading.Event()

        def _on_resumed(event: dict[str, Any]) -> None:
            if event.get("event") == "progress" and int(event.get("downloaded", 0)) > 0:
                resumed.set()

        bridge.download_begin(params, _on_resumed, "contract-active")
        assert resumed.wait(10.0), "resume never produced progress"
        assert any(item["range"] for item in range_server.requests)

        cancel_ack = bridge.cancel("contract-active")
        _assert_ack(cancel_ack, "contract-active")
        cancelled = bridge.download_wait("contract-active", timeout=15.0)
        assert cancelled["ok"] is True
        assert cancelled["result"]["state"] == "cancelled"
        assert not part.exists()
        assert not meta.exists()

        # A fresh download under continuous progress with timeout=None must
        # not hit the default 300 s idle timeout.
        started = time.monotonic()
        bridge.download_begin(params, None, "contract-done")
        done = bridge.download_wait("contract-done", timeout=None)
        elapsed = time.monotonic() - started
        assert done["ok"] is True
        assert done["result"]["state"] == "done"
        assert elapsed < 60.0
        assert dest.is_file()
        assert dest.stat().st_size == len(_PAYLOAD)
        assert hashlib.sha256(dest.read_bytes()).hexdigest() == _SHA256
        assert not part.exists()
        assert not meta.exists()

        verified = bridge.verify({"path": str(dest), "sha256": _SHA256})
        assert verified["ok"] is True
        assert verified["result"]["match"] is True
        assert isinstance(verified["result"]["volume_serial"], int)
        assert isinstance(verified["result"]["file_index"], int)

        # The real sidecar speaks NDJSON and accepts the documented envelope.
        assert range_server.requests
