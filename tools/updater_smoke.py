"""Real-network smoke test for the native updater (plan Todo 20).

The tool drives the production :class:`UpdateService` (and therefore the real
``spk_updater.exe`` sidecar) against GitHub, records the redirect chain of the
release asset, pauses a real download at a byte threshold, resumes it, and
verifies the SHA-256 digest.  It never launches the installer and never writes
inside the repository: the service download directory is redirected to a
temporary ``SPK_DATA_DIR`` for the whole run.

Typical usage (PowerShell)::

    $env:QT_QPA_PLATFORM='offscreen'
    python tools/updater_smoke.py --check
    python tools/updater_smoke.py --download --pause-after 20 --resume --verify

Both commands print one JSON object to stdout and exit non-zero when the run
does not prove a real success.  ``--evidence PATH`` appends a UTF-8 section with
the exact command line, timestamps and the full JSON payload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
    urlopen,
)

# Qt must be configured before PySide6 is imported, and the app-data override
# must exist before any ``sopeek`` module reads it.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _prepare_data_dir() -> Path:
    """Point ``SPK_DATA_DIR`` at a temporary directory outside the repo.

    Returns:
        Path: The effective application-data directory used by the service.
    """
    existing = os.environ.get("SPK_DATA_DIR", "").strip()
    if existing:
        return Path(existing)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = (
        Path(tempfile.gettempdir())
        / "spk_updater_smoke"
        / f"run-{stamp}-{os.getpid()}"
    )
    os.environ["SPK_DATA_DIR"] = str(directory)
    return directory


_DATA_DIR: Path = _prepare_data_dir()

from PySide6.QtCore import (  # noqa: E402 - env must be set before Qt import
    QCoreApplication,
    QEventLoop,
    QObject,
    QTimer,
    Slot,
)

from sopeek.services.update_service import (  # noqa: E402
    UpdateError,
    UpdateInfo,
    UpdateService,
    sanitize_asset_name,
)
from sopeek.utils.path_utils import get_app_data_path  # noqa: E402

#: Keeps the CLI-owned ``QCoreApplication`` alive for the whole process.
_QT_APP: Optional[QCoreApplication] = None

DEFAULT_PREFLIGHT: Path = (
    _REPO_ROOT / ".omo" / "evidence" / "rust-native-updater" / "preflight.txt"
)
RELEASES_API: str = (
    "https://api.github.com/repos/Dorufoc/Sopeek/releases?per_page=30"
)
USER_AGENT: str = "Sopeek-updater-smoke"
REDIRECT_STATUSES: frozenset[int] = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECT_HOPS: int = 10
MIB: int = 1024 * 1024
PREFLIGHT_RECOVERY_NOTE: str = (
    "preflight.txt was missing in the earlier session and was recovered "
    "read-only on 2026-10-25; it is used as the baseline for this run."
)
_SEMVER_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$", re.IGNORECASE
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------
def _utc_now() -> str:
    """Return the current UTC timestamp in ISO-8601 form.

    Returns:
        str: Timestamp with timezone offset.
    """
    return datetime.now(timezone.utc).isoformat()


def _as_int(value: Any, default: int = 0) -> int:
    """Coerce a signal payload value to a non-negative integer.

    Args:
        value: Raw value from a Qt signal.
        default: Fallback when conversion fails.

    Returns:
        int: Converted value.
    """
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _semver_key(tag: Any) -> Optional[tuple[int, int, int, tuple[Any, ...]]]:
    """Build a comparable SemVer key from a release tag.

    Args:
        tag: Tag such as ``v1.0.0-alpha.5``.

    Returns:
        Optional[tuple]: Comparable key, or ``None`` for invalid tags.
    """
    if not isinstance(tag, str):
        return None
    match = _SEMVER_RE.match(tag.strip())
    if match is None:
        return None
    major, minor, patch = (int(match.group(index)) for index in (1, 2, 3))
    prerelease = match.group(4)
    if prerelease is None:
        prerelease_key: tuple[Any, ...] = (1,)
    else:
        identifiers: list[tuple[int, Any]] = []
        for identifier in prerelease.split("."):
            if identifier.isdigit():
                identifiers.append((0, int(identifier)))
            else:
                identifiers.append((1, identifier))
        prerelease_key = (0, tuple(identifiers))
    return (major, minor, patch, prerelease_key)


def _normalize_tag(tag: Any) -> str:
    """Strip a leading ``v``/``V`` and whitespace from a tag.

    Args:
        tag: Raw tag or version string.

    Returns:
        str: Normalized tag (lowercase preserved otherwise).
    """
    if not isinstance(tag, str):
        return ""
    value = tag.strip()
    if value[:1] in {"v", "V"}:
        value = value[1:]
    return value


def _tags_equal(left: Any, right: Any) -> bool:
    """Compare two tags ignoring a leading ``v`` and case.

    Args:
        left: First tag.
        right: Second tag.

    Returns:
        bool: ``True`` when both normalize to the same value.
    """
    return _normalize_tag(left).lower() == _normalize_tag(right).lower()


def _normalize_digest(value: Any) -> str:
    """Normalize a GitHub digest (``sha256:<hex>`` or bare hex).

    Args:
        value: Raw digest string.

    Returns:
        str: Lowercase hex digest, or an empty string when invalid.
    """
    if not isinstance(value, str):
        return ""
    text = value.strip().lower()
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    if len(text) == 64 and all(character in "0123456789abcdef" for character in text):
        return text
    return ""


def _parse_date(value: Any) -> Optional[datetime]:
    """Parse a strict ``YYYY-MM-DD`` build date.

    Args:
        value: Raw date string.

    Returns:
        Optional[datetime]: Parsed date at midnight, or ``None``.
    """
    if not isinstance(value, str) or _DATE_RE.fullmatch(value.strip()) is None:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        return None


def _evaluate_update(
    local_version: Any,
    local_date: Any,
    remote_version: Any,
    remote_date: Any,
) -> dict[str, Any]:
    """Independently mirror the Rust semver/date update decision.

    Args:
        local_version: Local version string.
        local_date: Local build date.
        remote_version: Remote version string.
        remote_date: Remote build date.

    Returns:
        dict: ``{"available": bool|None, "reason": str}``.
    """
    local_key = _semver_key(local_version)
    remote_key = _semver_key(remote_version)
    if local_key is None or remote_key is None:
        return {"available": None, "reason": "invalid_version"}
    if remote_key > local_key:
        return {"available": True, "reason": "newer_version"}
    if remote_key < local_key:
        return {"available": False, "reason": "local_newer"}
    local_parsed = _parse_date(local_date)
    remote_parsed = _parse_date(remote_date)
    if (
        local_parsed is not None
        and remote_parsed is not None
        and remote_parsed > local_parsed
    ):
        return {"available": True, "reason": "rebuild"}
    return {"available": False, "reason": "none"}


def _host_allowed(host: str) -> bool:
    """Check a redirect host against the GitHub allowlist.

    Exact ``github.com`` / ``api.github.com`` and dot-boundary
    ``*.githubusercontent.com`` hosts are accepted.

    Args:
        host: Hostname from a URL.

    Returns:
        bool: ``True`` when the host is allowed.
    """
    normalized = (host or "").lower()
    if not normalized:
        return False
    if normalized in {"github.com", "api.github.com"}:
        return True
    return normalized.endswith(".githubusercontent.com")


class _NoRedirect(HTTPRedirectHandler):
    """Redirect handler that refuses to follow, keeping each hop visible."""

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        """Return ``None`` so urllib raises ``HTTPError`` for every 3xx."""
        return None


def _probe_hop(
    scheme: str,
    host: str,
    port: Optional[int],
    path: str,
    timeout: float,
) -> tuple[int, Optional[str]]:
    """Send a HEAD request (GET fallback) and return status + Location.

    The request goes through urllib's default opener, so an ``HTTPS_PROXY``
    environment variable is honoured (matching the Rust sidecar, which uses
    ``Proxy::try_from_env``). Redirects are never followed here because the
    caller records and validates every hop.

    Args:
        scheme: ``http`` or ``https``.
        host: Hostname.
        port: Optional explicit port.
        path: Request path including query string.
        timeout: Socket timeout in seconds.

    Returns:
        tuple[int, Optional[str]]: Status code and ``Location`` header.
    """
    authority = f"{host}:{port}" if port else host
    url = f"{scheme}://{authority}{path}"
    opener = build_opener(ProxyHandler(), _NoRedirect())

    def _request(method: str, extra_headers: dict[str, str]) -> tuple[int, Optional[str]]:
        request = Request(
            url,
            method=method,
            headers={"User-Agent": USER_AGENT, "Accept": "*/*", **extra_headers},
        )
        try:
            with opener.open(request, timeout=timeout) as response:
                return response.status, response.headers.get("Location")
        except HTTPError as exc:
            try:
                location = exc.headers.get("Location") if exc.headers else None
                return exc.code, location
            finally:
                exc.close()

    try:
        status, location = _request("HEAD", {})
        if status < 400:
            return status, location
    except (OSError, URLError):
        pass
    # Some signed blob URLs reject HEAD; a one-byte range GET still exposes the
    # status and the redirect chain without downloading the asset.
    return _request("GET", {"Range": "bytes=0-0"})


def _record_redirect_hops(url: str, timeout: float) -> list[dict[str, Any]]:
    """Walk a download URL hop by hop and record status/host/Location.

    Args:
        url: Browser download URL of the release asset.
        timeout: Per-hop socket timeout in seconds.

    Returns:
        list[dict]: One record per hop.

    Raises:
        ValueError: When a hop is malformed or exceeds the hop budget.
    """
    hops: list[dict[str, Any]] = []
    current = url
    for hop_index in range(1, MAX_REDIRECT_HOPS + 1):
        parts = urlsplit(current)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError(f"invalid redirect URL: {current}")
        host = parts.hostname
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        status, location = _probe_hop(
            parts.scheme, host, parts.port, path, timeout
        )
        hops.append(
            {
                "hop": hop_index,
                "url": current,
                "host": host,
                "status": status,
                "location": location,
                "host_allowed": _host_allowed(host),
            }
        )
        if status in REDIRECT_STATUSES:
            if not location:
                raise ValueError(f"HTTP {status} without Location at hop {hop_index}")
            current = urljoin(current, location)
            continue
        return hops
    raise ValueError(f"redirect chain exceeded {MAX_REDIRECT_HOPS} hops")


def _read_preflight(path: Path) -> dict[str, Any]:
    """Parse the recovered preflight baseline file.

    Args:
        path: Preflight artifact path.

    Returns:
        dict: Parsed keys plus ``present`` and ``path``.
    """
    result: dict[str, Any] = {"path": str(path), "present": path.is_file()}
    if not path.is_file():
        return result
    keys = {
        "latest_tag",
        "latest_usable_tag",
        "skipped_newer_tag",
        "selected_asset",
        "asset_size",
        "asset_digest",
        "browser_download_url",
        "VERDICT",
    }
    values: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("-") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in keys:
            stripped = value.strip()
            values[key] = None if stripped.lower() == "null" else stripped
    if isinstance(values.get("asset_size"), str):
        try:
            values["asset_size"] = int(values["asset_size"])
        except ValueError:
            values["asset_size"] = None
    result.update(values)
    return result


def _fetch_newest_tag(timeout: float) -> dict[str, Any]:
    """Query the GitHub releases API and compute the newest eligible tag.

    Args:
        timeout: HTTP timeout in seconds.

    Returns:
        dict: ``ok``/``error``/``tags``/``newest_tag``.
    """
    request = Request(
        RELEASES_API,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=max(1.0, timeout)) as response:
            raw = response.read()
    except (HTTPError, URLError, OSError, ValueError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "tags": []}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"invalid_json: {exc}", "tags": []}
    tags: list[str] = []
    if isinstance(payload, list):
        for release in payload:
            if not isinstance(release, dict) or release.get("draft"):
                continue
            tag = release.get("tag_name")
            if isinstance(tag, str) and _semver_key(tag) is not None:
                tags.append(tag)
    newest = max(tags, key=_semver_key) if tags else None
    return {"ok": True, "tags": tags, "newest_tag": newest}


def _sha256_file(path: Path) -> str:
    """Compute the SHA-256 digest of a file without loading it into memory.

    Args:
        path: File to hash.

    Returns:
        str: Lowercase hexadecimal digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(MIB), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Qt waiters
# ---------------------------------------------------------------------------
class _CheckWaiter(QObject):
    """Collect ``check_finished`` on the GUI thread and quit a loop."""

    def __init__(self, loop: QEventLoop) -> None:
        """Store the loop that must be quit when the signal arrives.

        Args:
            loop: Event loop owned by the caller.
        """
        super().__init__()
        self._loop = loop
        self.done = False
        self.request_id = ""
        self.manual = False
        self.info: Optional[UpdateInfo] = None
        self.error: Optional[UpdateError] = None

    @Slot(str, bool, object, object)
    def on_finished(
        self,
        request_id: str,
        manual: bool,
        info: object,
        error: object,
    ) -> None:
        """Record the check result and stop the loop.

        Args:
            request_id: Service request id.
            manual: Whether the check was manual.
            info: ``UpdateInfo`` on success.
            error: ``UpdateError`` on failure.
        """
        if self.done:
            return
        if self.request_id and request_id != self.request_id:
            return
        self.done = True
        self.request_id = request_id
        self.manual = manual
        self.info = info if isinstance(info, UpdateInfo) else None
        self.error = error if isinstance(error, UpdateError) else None
        self._loop.quit()


class _DownloadWaiter(QObject):
    """Collect download signals and drive the pause threshold."""

    def __init__(self, service: UpdateService, pause_threshold: int) -> None:
        """Wire every download signal to this receiver.

        Args:
            service: Live update service.
            pause_threshold: Byte offset at which to request a pause (0 = off).
        """
        super().__init__()
        self._service = service
        self._threshold = pause_threshold
        self._loop: Optional[QEventLoop] = None
        self._phase = "idle"
        self._timed_out = False

        self.request_id = ""
        self.started = False
        self.terminal: Optional[dict[str, Any]] = None
        self.progress_events = 0
        self.last_progress: Optional[tuple[int, int, float]] = None
        self.pause_requested = False
        self.pause_requested_at: Optional[int] = None
        self.pause_ack: Optional[bool] = None
        self.pause_ready = False
        self.state_events: list[str] = []
        self.resume_started = False
        self.resume_progress_events = 0
        self.first_resume_progress: Optional[int] = None
        self.min_resume_progress: Optional[int] = None

        service.download_started.connect(self.on_started)
        service.download_progress.connect(self.on_progress)
        service.download_state_changed.connect(self.on_state_changed)
        service.download_pause_acked.connect(self.on_pause_acked)
        service.download_finished.connect(self.on_finished)
        service.download_failed.connect(self.on_failed)

    def detach(self) -> None:
        """Disconnect every signal from this receiver."""
        for signal, slot in (
            (self._service.download_started, self.on_started),
            (self._service.download_progress, self.on_progress),
            (self._service.download_state_changed, self.on_state_changed),
            (self._service.download_pause_acked, self.on_pause_acked),
            (self._service.download_finished, self.on_finished),
            (self._service.download_failed, self.on_failed),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def _matches(self, request_id: str) -> bool:
        """Return whether a signal belongs to the active request.

        Args:
            request_id: Signal request id.

        Returns:
            bool: ``True`` for the active request.
        """
        return not self.request_id or request_id == self.request_id

    def _quit_if_ready(self) -> None:
        """Quit the current loop when the phase's completion condition holds."""
        if self._loop is None:
            return
        if self._phase == "pause":
            if self.pause_ready or self.terminal is not None:
                self._loop.quit()
            return
        if self.terminal is not None:
            self._loop.quit()

    @Slot(str)
    def on_started(self, request_id: str) -> None:
        """Mark the download as started.

        Args:
            request_id: Signal request id.
        """
        if self._matches(request_id):
            self.started = True

    @Slot(str, object, object, float)
    def on_progress(
        self,
        request_id: str,
        downloaded: object,
        total: object,
        speed: float,
    ) -> None:
        """Track progress, pause at the threshold, and record resume offsets.

        Args:
            request_id: Signal request id.
            downloaded: Bytes written so far.
            total: Expected total bytes.
            speed: Bytes per second reported by Rust.
        """
        if not self._matches(request_id):
            return
        offset = _as_int(downloaded)
        expected = _as_int(total)
        self.progress_events += 1
        try:
            rate = float(speed)
        except (TypeError, ValueError):
            rate = 0.0
        self.last_progress = (offset, expected, rate)
        if self.resume_started:
            self.resume_progress_events += 1
            if self.first_resume_progress is None:
                self.first_resume_progress = offset
            if self.min_resume_progress is None:
                self.min_resume_progress = offset
            else:
                self.min_resume_progress = min(self.min_resume_progress, offset)
        if (
            not self.resume_started
            and self._threshold > 0
            and not self.pause_requested
            and offset >= self._threshold
            and self.terminal is None
        ):
            self.pause_requested = True
            self.pause_requested_at = offset
            self._service.pause_download(self.request_id)

    @Slot(str, str)
    def on_state_changed(self, request_id: str, state: str) -> None:
        """Record state transitions and unlock the pause phase.

        Args:
            request_id: Signal request id.
            state: New state name.
        """
        if not self._matches(request_id):
            return
        self.state_events.append(state)
        if state == "paused" and not self.resume_started:
            self.pause_ready = True
        self._quit_if_ready()

    @Slot(str, bool)
    def on_pause_acked(self, request_id: str, accepted: bool) -> None:
        """Record the pause acknowledgement.

        Args:
            request_id: Signal request id.
            accepted: Whether the pause was accepted.
        """
        if not self._matches(request_id):
            return
        self.pause_ack = accepted
        if accepted and not self.resume_started:
            self.pause_ready = True
        self._quit_if_ready()

    @Slot(str, str)
    def on_finished(self, request_id: str, path: str) -> None:
        """Record a successful terminal result.

        Args:
            request_id: Signal request id.
            path: Final downloaded file path.
        """
        if not self._matches(request_id) or self.terminal is not None:
            return
        self.terminal = {"kind": "finished", "path": path}
        self._quit_if_ready()

    @Slot(str, object)
    def on_failed(self, request_id: str, error: object) -> None:
        """Record a failed terminal result.

        Args:
            request_id: Signal request id.
            error: ``UpdateError`` payload.
        """
        if not self._matches(request_id) or self.terminal is not None:
            return
        code = error.code if isinstance(error, UpdateError) else "unknown"
        message = error.message if isinstance(error, UpdateError) else str(error)
        self.terminal = {"kind": "failed", "code": code, "message": message}
        self._quit_if_ready()

    def _on_timeout(self) -> None:
        """Mark the loop as timed out and stop it."""
        self._timed_out = True
        if self._loop is not None:
            self._loop.quit()

    def _exec(self, timeout: float) -> bool:
        """Run one bounded event loop for the current phase.

        Args:
            timeout: Wall-clock budget in seconds.

        Returns:
            bool: ``False`` when the timer fired before completion.
        """
        self._timed_out = False
        self._loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(self._on_timeout)
        timer.start(max(1, int(timeout * 1000)))
        self._loop.exec()
        timer.stop()
        self._loop = None
        return not self._timed_out

    def wait_pause_or_terminal(self, timeout: float) -> bool:
        """Wait until the download is paused or reaches a terminal state.

        Args:
            timeout: Wall-clock budget in seconds.

        Returns:
            bool: ``False`` on timeout.
        """
        self._phase = "pause"
        if self.pause_ready or self.terminal is not None:
            return True
        return self._exec(timeout)

    def wait_terminal(self, timeout: float) -> bool:
        """Wait until a terminal download signal arrives.

        Args:
            timeout: Wall-clock budget in seconds.

        Returns:
            bool: ``False`` on timeout.
        """
        self._phase = "terminal"
        if self.terminal is not None:
            return True
        return self._exec(timeout)


def _exec_loop(loop: QEventLoop, timeout: float) -> bool:
    """Run a loop with a single-shot timeout.

    Args:
        loop: Loop to execute.
        timeout: Wall-clock budget in seconds.

    Returns:
        bool: ``False`` when the timeout fired.
    """
    timed_out = {"value": False}

    def _on_timeout() -> None:
        timed_out["value"] = True
        loop.quit()

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(_on_timeout)
    timer.start(max(1, int(timeout * 1000)))
    loop.exec()
    timer.stop()
    return not timed_out["value"]


def _drain_events(milliseconds: int = 250) -> None:
    """Process pending Qt events for a short bounded period.

    Args:
        milliseconds: Total drain budget in milliseconds.
    """
    application = QCoreApplication.instance()
    if application is None:
        return
    deadline = time.monotonic() + milliseconds / 1000.0
    while time.monotonic() < deadline:
        application.processEvents(QEventLoop.AllEvents, 50)
        time.sleep(0.02)


# ---------------------------------------------------------------------------
# Check phase
# ---------------------------------------------------------------------------
def _run_check(
    service: UpdateService,
    preflight: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    """Execute a real manual check and compare it with the baseline.

    Args:
        service: Live update service.
        preflight: Parsed preflight baseline.
        timeout: Check wall-clock budget in seconds.

    Returns:
        dict: Check result payload.
    """
    started = time.monotonic()
    loop = QEventLoop()
    waiter = _CheckWaiter(loop)
    service.check_finished.connect(waiter.on_finished)
    request_id = ""
    completed = False
    try:
        request_id = service.check(manual=True)
        waiter.request_id = request_id
        completed = _exec_loop(loop, timeout)
    except Exception as exc:  # noqa: BLE001 - CLI must report check failures as JSON
        return {
            "ok": False,
            "elapsed_s": round(time.monotonic() - started, 3),
            "request_id": request_id,
            "code": "internal",
            "message": f"{type(exc).__name__}: {exc}",
        }
    finally:
        try:
            service.check_finished.disconnect(waiter.on_finished)
        except (RuntimeError, TypeError):
            pass
    elapsed = round(time.monotonic() - started, 3)

    if waiter.error is not None:
        return {
            "ok": False,
            "elapsed_s": elapsed,
            "request_id": request_id,
            "code": waiter.error.code,
            "message": waiter.error.message,
            "error_retryable": waiter.error.retryable,
        }
    if not waiter.done or waiter.info is None:
        return {
            "ok": False,
            "elapsed_s": elapsed,
            "request_id": request_id,
            "code": "timeout" if not completed else "internal",
            "message": (
                f"check_finished not received within {timeout:.0f}s"
                if not completed
                else "check_finished arrived without UpdateInfo"
            ),
        }

    info = waiter.info
    remote = info.remote if isinstance(info.remote, dict) else {}
    asset = info.asset if isinstance(info.asset, dict) else {}
    expected = _evaluate_update(
        info.local_version,
        info.local_date,
        remote.get("version"),
        remote.get("date"),
    )
    update_consistent = (
        expected["available"] is not None
        and expected["available"] == info.update_available
        and expected["reason"] == info.reason
    )

    remaining = max(1.0, timeout - (time.monotonic() - started))
    newest = _fetch_newest_tag(min(10.0, remaining))
    newest_tag = newest.get("newest_tag")
    newest_source = "github_api" if newest.get("ok") else "check_result"
    if newest_tag is None:
        newest_tag = info.skipped_newer_tag or remote.get("tag")
    skipped_consistent: Optional[bool]
    if newest_tag is None:
        skipped_consistent = None
    elif _tags_equal(newest_tag, remote.get("version")):
        skipped_consistent = info.skipped_newer_tag is None
    else:
        skipped_consistent = _tags_equal(info.skipped_newer_tag, newest_tag)

    preflight_match: Optional[bool] = None
    preflight_skipped_consistent: Optional[bool] = None
    if preflight.get("present") and preflight.get("latest_usable_tag"):
        preflight_match = _tags_equal(
            remote.get("version"), preflight.get("latest_usable_tag")
        )
        if preflight.get("latest_tag") and not _tags_equal(
            preflight.get("latest_tag"), preflight.get("latest_usable_tag")
        ):
            preflight_skipped_consistent = _tags_equal(
                info.skipped_newer_tag, preflight.get("latest_tag")
            )
        else:
            preflight_skipped_consistent = info.skipped_newer_tag is None

    digest_matches_preflight: Optional[bool] = None
    if preflight.get("asset_digest"):
        digest_matches_preflight = _normalize_digest(
            asset.get("sha256")
        ) == _normalize_digest(preflight.get("asset_digest"))
    size_matches_preflight: Optional[bool] = None
    if isinstance(preflight.get("asset_size"), int):
        size_matches_preflight = _as_int(asset.get("size")) == preflight["asset_size"]

    checks = [update_consistent, skipped_consistent]
    if preflight_match is not None:
        checks.append(preflight_match)
    if preflight_skipped_consistent is not None:
        checks.append(preflight_skipped_consistent)
    if digest_matches_preflight is not None:
        checks.append(digest_matches_preflight)
    if size_matches_preflight is not None:
        checks.append(size_matches_preflight)
    ok = all(checks)

    return {
        "ok": ok,
        "elapsed_s": elapsed,
        "request_id": request_id,
        "manual": waiter.manual,
        "local": {"version": info.local_version, "date": info.local_date},
        "remote": {
            "version": remote.get("version"),
            "tag": remote.get("tag"),
            "date": remote.get("date"),
            "published_at": remote.get("published_at"),
            "prerelease": remote.get("prerelease"),
            "html_url": remote.get("html_url"),
        },
        "asset": {
            "name": asset.get("name"),
            "size": asset.get("size"),
            "sha256": asset.get("sha256"),
            "download_url": asset.get("download_url"),
        },
        "update_available": info.update_available,
        "reason": info.reason,
        "skipped_newer_tag": info.skipped_newer_tag,
        "expected_decision": expected,
        "update_available_consistent": update_consistent,
        "newest_tag_seen": newest_tag,
        "newest_tag_source": newest_source,
        "newest_tag_api_error": newest.get("error"),
        "skipped_newer_tag_consistent": skipped_consistent,
        "preflight": preflight,
        "preflight_match": preflight_match,
        "preflight_skipped_consistent": preflight_skipped_consistent,
        "digest_matches_preflight": digest_matches_preflight,
        "size_matches_preflight": size_matches_preflight,
    }


# ---------------------------------------------------------------------------
# Download phase
# ---------------------------------------------------------------------------
def _cleanup_artifacts(paths: list[Path]) -> dict[str, list[str]]:
    """Delete the downloaded final file, part, meta and sidecar.

    Args:
        paths: Candidate artifact paths.

    Returns:
        dict: Removed and already-absent paths.
    """
    removed: list[str] = []
    missing: list[str] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            path.unlink()
            removed.append(key)
        except FileNotFoundError:
            missing.append(key)
        except OSError as exc:
            missing.append(f"{key} ({exc})")
    return {"removed": removed, "missing": missing}


def _run_download(
    service: UpdateService,
    info: UpdateInfo,
    preflight: dict[str, Any],
    pause_after_mb: Optional[float],
    download_timeout: float,
    resume_requested: bool,
    keep_files: bool,
) -> dict[str, Any]:
    """Download the real asset, pause at the threshold, resume and verify.

    Args:
        service: Live update service.
        info: Successful check result.
        preflight: Parsed preflight baseline.
        pause_after_mb: Pause threshold in MiB (``None`` disables pausing).
        download_timeout: Per-phase wall-clock budget in seconds.
        resume_requested: Resume after the pause instead of stopping there.
        keep_files: Keep the downloaded artifacts instead of deleting them.

    Returns:
        dict: Download result payload.
    """
    asset = info.asset if isinstance(info.asset, dict) else {}
    digest = _normalize_digest(asset.get("sha256"))
    expected_size = _as_int(asset.get("size"))
    name = sanitize_asset_name(asset.get("name"))
    download_url = asset.get("download_url")
    base: dict[str, Any] = {
        "ok": False,
        "asset_name": name,
        "expected_size": expected_size,
        "expected_sha256": digest,
        "download_url": download_url,
    }
    if not digest:
        base.update(verdict="checksum_missing", message="asset digest is empty")
        return base
    if not name:
        base.update(verdict="bad_asset_name", message="asset name is unusable")
        return base
    if not isinstance(download_url, str) or not download_url:
        base.update(verdict="bad_download_url", message="asset download_url is empty")
        return base

    started = time.monotonic()
    download_dir = Path(get_app_data_path()) / "download"
    dest = download_dir / name
    part = dest.with_name(dest.name + ".part")
    part_meta = dest.with_name(dest.name + ".part.json")
    legacy_meta = dest.with_name(dest.name + ".meta")
    base["download_dir"] = str(download_dir)
    base["dest_path"] = str(dest)

    # 1. Record the real redirect chain with manual handling.
    try:
        hops = _record_redirect_hops(download_url, timeout=15.0)
    except (ValueError, OSError, URLError) as exc:
        base.update(
            verdict="redirect_probe_failed",
            message=f"{type(exc).__name__}: {exc}",
            elapsed_s=round(time.monotonic() - started, 3),
        )
        return base
    hops_ok = all(bool(hop.get("host_allowed")) for hop in hops)
    base["redirect_hops"] = hops
    base["redirect_hosts_allowed"] = hops_ok
    base["redirect_hosts"] = [hop["host"] for hop in hops]
    if not hops_ok:
        base.update(
            verdict="unsafe_redirect",
            message="redirect chain left the GitHub host allowlist",
            elapsed_s=round(time.monotonic() - started, 3),
        )
        return base

    # 2. Drive the real download.
    threshold = int(round(pause_after_mb * MIB)) if pause_after_mb else 0
    waiter = _DownloadWaiter(service, threshold)
    request_id = ""
    paused_offset = 0
    try:
        request_id = service.start_download(info)
        waiter.request_id = request_id
        base["request_id"] = request_id

        if threshold > 0:
            pause_completed = waiter.wait_pause_or_terminal(download_timeout)
            base["pause_requested"] = waiter.pause_requested
            base["pause_requested_at"] = waiter.pause_requested_at
            base["pause_ack"] = waiter.pause_ack
            base["state_events_before_pause"] = list(waiter.state_events)
            base["progress_events_before_pause"] = waiter.progress_events

            if not pause_completed:
                service.cancel_download(request_id)
                base.update(
                    verdict="timeout",
                    message="no pause acknowledgement or terminal result in time",
                    elapsed_s=round(time.monotonic() - started, 3),
                )
                return base

            if waiter.terminal is not None and not waiter.pause_ready:
                if waiter.terminal["kind"] == "finished":
                    base.update(
                        verdict="pause_too_late",
                        message="download finished before the pause threshold",
                        terminal=waiter.terminal,
                        elapsed_s=round(time.monotonic() - started, 3),
                    )
                else:
                    base.update(
                        verdict="download_failed",
                        terminal=waiter.terminal,
                        elapsed_s=round(time.monotonic() - started, 3),
                    )
                return base

            if not waiter.pause_ready:
                service.cancel_download(request_id)
                base.update(
                    verdict="pause_not_acknowledged",
                    message="pause signal missing after progress threshold",
                    elapsed_s=round(time.monotonic() - started, 3),
                )
                return base

            # 3. Capture the real pause offset and the retained part file.
            _drain_events(250)
            state = service.get_download_state(request_id)
            base["state_at_pause"] = list(state) if state else None
            paused_offset = _as_int(state[1]) if state else 0
            if paused_offset <= 0 and waiter.last_progress is not None:
                paused_offset = waiter.last_progress[0]
            base["paused_offset"] = paused_offset
            base["pause_threshold_bytes"] = threshold
            base["part_exists_at_pause"] = part.is_file()
            base["part_size_at_pause"] = part.stat().st_size if part.is_file() else None
            base["part_meta_exists_at_pause"] = part_meta.is_file()
            if paused_offset < threshold:
                service.cancel_download(request_id)
                base.update(
                    verdict="pause_below_threshold",
                    message=(
                        f"paused at {paused_offset} bytes, below threshold {threshold}"
                    ),
                    elapsed_s=round(time.monotonic() - started, 3),
                )
                return base

            # 4. Resume and prove the byte offset did not restart at zero.
            if not resume_requested:
                service.cancel_download(request_id)
                base.update(
                    verdict="paused_only",
                    message="pause captured; --resume was not requested",
                    elapsed_s=round(time.monotonic() - started, 3),
                )
                return base
            waiter.resume_started = True
            resumed = service.resume_download(request_id)
            base["resume_accepted"] = bool(resumed)
            if not resumed:
                service.cancel_download(request_id)
                base.update(
                    verdict="resume_rejected",
                    message="resume_download returned False",
                    elapsed_s=round(time.monotonic() - started, 3),
                )
                return base

        # 5. Wait for the terminal result (direct download or resumed one).
        terminal_completed = waiter.wait_terminal(download_timeout)
        base["resume_progress_events"] = waiter.resume_progress_events
        base["first_resume_progress"] = waiter.first_resume_progress
        base["min_resume_progress"] = waiter.min_resume_progress
        base["progress_events_total"] = waiter.progress_events
        base["state_events_total"] = list(waiter.state_events)

        if not terminal_completed:
            service.cancel_download(request_id)
            base.update(
                verdict="timeout",
                message="download did not finish in time",
                elapsed_s=round(time.monotonic() - started, 3),
            )
            return base
        if waiter.terminal is None:
            base.update(
                verdict="internal",
                message="terminal wait returned without a terminal event",
                elapsed_s=round(time.monotonic() - started, 3),
            )
            return base
        if waiter.terminal["kind"] == "failed":
            base.update(
                verdict="download_failed",
                terminal=waiter.terminal,
                elapsed_s=round(time.monotonic() - started, 3),
            )
            return base

        # 6. Verify the real bytes on disk.
        final_path = Path(str(waiter.terminal["path"]))
        base["finished_path"] = str(final_path)
        base["final_exists"] = final_path.is_file()
        base["final_size"] = final_path.stat().st_size if final_path.is_file() else None
        final_sha = _sha256_file(final_path) if final_path.is_file() else ""
        base["final_sha256"] = final_sha
        base["size_matches_asset"] = base["final_size"] == expected_size
        base["size_matches_preflight"] = (
            base["final_size"] == preflight.get("asset_size")
            if isinstance(preflight.get("asset_size"), int)
            else None
        )
        base["sha256_matches_asset"] = final_sha == digest
        base["sha256_matches_preflight"] = (
            final_sha == _normalize_digest(preflight.get("asset_digest"))
            if preflight.get("asset_digest")
            else None
        )
        if threshold > 0:
            resume_ok: Optional[bool] = (
                waiter.resume_progress_events > 0
                and waiter.first_resume_progress is not None
                and waiter.first_resume_progress >= paused_offset
            )
        else:
            resume_ok = None
        base["resume_without_restart"] = resume_ok
        checks: list[bool] = [
            bool(base["final_exists"]),
            bool(base["size_matches_asset"]),
            bool(base["sha256_matches_asset"]),
        ]
        if resume_ok is not None:
            checks.append(resume_ok)
        if base["size_matches_preflight"] is not None:
            checks.append(bool(base["size_matches_preflight"]))
        if base["sha256_matches_preflight"] is not None:
            checks.append(bool(base["sha256_matches_preflight"]))
        base["ok"] = all(checks)
        base["verdict"] = "PASS" if base["ok"] else "FAIL"
        base["elapsed_s"] = round(time.monotonic() - started, 3)
        return base
    finally:
        waiter.detach()
        cleanup_paths = [dest, part, part_meta, legacy_meta]
        finished_path = None
        if waiter.terminal and waiter.terminal.get("kind") == "finished":
            finished_path = waiter.terminal.get("path")
        if finished_path:
            cleanup_paths.append(Path(str(finished_path)))
        if keep_files:
            base["cleanup"] = {"kept": True, "paths": [str(path) for path in cleanup_paths]}
        else:
            base["cleanup"] = _cleanup_artifacts(cleanup_paths)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser.

    Returns:
        argparse.ArgumentParser: Configured parser.
    """
    parser = argparse.ArgumentParser(
        description="Real-network smoke test for the Sopeek updater.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run a real manual GitHub update check (default when no mode is given).",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Check, then download the real installer asset.",
    )
    parser.add_argument(
        "--pause-after",
        type=float,
        metavar="MB",
        default=None,
        help="Pause the download after this many MiB (requires --download).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a paused download and wait for completion.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify the final file size and SHA-256 against the asset digest.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=27.0,
        metavar="SECONDS",
        help="Check wall-clock budget (default: 27s, inside the 30s plan budget).",
    )
    parser.add_argument(
        "--download-timeout",
        type=float,
        default=900.0,
        metavar="SECONDS",
        help="Per-phase download wall-clock budget (default: 900s).",
    )
    parser.add_argument(
        "--preflight",
        type=Path,
        default=DEFAULT_PREFLIGHT,
        help="Recovered preflight baseline used for dynamic comparison.",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=None,
        help="Append a UTF-8 evidence section to this file.",
    )
    parser.add_argument(
        "--keep-files",
        action="store_true",
        help="Keep the downloaded final/part/meta files after the run.",
    )
    return parser


def _append_evidence(path: Path, payload: dict[str, Any]) -> None:
    """Append a timestamped UTF-8 evidence section.

    Args:
        path: Evidence file path.
        payload: JSON-serializable payload for this run.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "",
        "=" * 78,
        f"UTC: {payload.get('finished_utc')}",
        f"Command: {sys.executable} {' '.join(sys.argv)}",
        f"CWD: {Path.cwd()}",
        f"Python: {platform.python_version()} ({platform.platform()})",
        f"QT_QPA_PLATFORM: {os.environ.get('QT_QPA_PLATFORM')}",
        f"SPK_DATA_DIR: {os.environ.get('SPK_DATA_DIR')}",
        f"Mode: {payload.get('mode')}",
        f"Verdict: {payload.get('verdict')}",
        "-" * 78,
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        "",
    ]
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))


def _shutdown(service: Optional[UpdateService]) -> dict[str, Any]:
    """Stop the sidecar and release the service thread pools.

    Args:
        service: Service instance, or ``None``.

    Returns:
        dict: Shutdown outcome flags.
    """
    if service is None:
        return {"shutdown_ok": None, "close_ok": None}
    shutdown_ok: Optional[bool] = None
    close_ok: Optional[bool] = None
    try:
        shutdown_ok = bool(service.shutdown(timeout=4.0))
    except Exception as exc:  # noqa: BLE001 - CLI teardown must not crash
        shutdown_ok = False
        print(f"shutdown failed: {exc!r}", file=sys.stderr)
    try:
        service.close()
        close_ok = True
    except Exception as exc:  # noqa: BLE001
        close_ok = False
        print(f"close failed: {exc!r}", file=sys.stderr)
    return {"shutdown_ok": shutdown_ok, "close_ok": close_ok}


def main(argv: Optional[list[str]] = None) -> int:
    """Run the requested smoke phases and emit one JSON document.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv[1:]``).

    Returns:
        int: ``0`` on PASS, ``2`` for BLOCKED_NETWORK, ``3`` for
        ``checksum_missing``, ``1`` otherwise.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.check and not args.download:
        args.check = True
    if args.resume and args.pause_after is None:
        parser.error("--resume requires --pause-after MB")
    if (args.resume or args.verify) and not args.download:
        parser.error("--resume/--verify require --download")

    global _QT_APP
    _QT_APP = QCoreApplication.instance() or QCoreApplication([sys.argv[0]])

    started_utc = _utc_now()
    started = time.monotonic()
    preflight = _read_preflight(args.preflight)
    payload: dict[str, Any] = {
        "tool": "updater_smoke",
        "mode": "download" if args.download else "check",
        "started_utc": started_utc,
        "preflight": preflight,
        "preflight_recovery_note": PREFLIGHT_RECOVERY_NOTE,
        "data_dir": str(_DATA_DIR),
        "download_dir": str(Path(get_app_data_path()) / "download"),
        "ok": False,
        "verdict": "FAIL",
    }

    service: Optional[UpdateService] = None
    try:
        service = UpdateService()
        check = _run_check(service, preflight, args.timeout)
        payload["check"] = check
        if not check.get("ok"):
            code = str(check.get("code") or "")
            if code in {"timeout", "network"}:
                payload["verdict"] = "BLOCKED_NETWORK"
                payload["blocked_reason"] = (
                    f"check failed with {code}: {check.get('message')}"
                )
            else:
                payload["verdict"] = "FAIL"
                payload["failure_reason"] = (
                    f"check failed with {code or 'unknown'}: {check.get('message')}"
                )
        elif not args.download:
            payload["ok"] = True
            payload["verdict"] = "PASS"
        else:
            info: Optional[UpdateInfo] = None
            # Re-run the check result through the service so the download uses
            # the exact UpdateInfo instance the signal delivered.
            info = _check_info_from_payload(check)
            if info is None:
                payload["verdict"] = "FAIL"
                payload["failure_reason"] = "check payload missing UpdateInfo fields"
            else:
                download = _run_download(
                    service,
                    info,
                    preflight,
                    args.pause_after,
                    args.download_timeout,
                    args.resume,
                    args.keep_files,
                )
                payload["download"] = download
                if download.get("verdict") == "checksum_missing":
                    payload["verdict"] = "checksum_missing"
                elif download.get("ok"):
                    payload["ok"] = True
                    payload["verdict"] = "PASS"
                else:
                    payload["verdict"] = "FAIL"
                    payload["failure_reason"] = download.get(
                        "message", download.get("verdict")
                    )
    except Exception as exc:  # noqa: BLE001 - CLI must always emit JSON
        payload["verdict"] = "FAIL"
        payload["failure_reason"] = f"{type(exc).__name__}: {exc}"
        print(f"unexpected failure: {exc!r}", file=sys.stderr)
    finally:
        payload["service_shutdown"] = _shutdown(service)

    payload["finished_utc"] = _utc_now()
    payload["elapsed_s"] = round(time.monotonic() - started, 3)
    if args.evidence is not None:
        try:
            _append_evidence(args.evidence, payload)
        except OSError as exc:
            print(f"evidence write failed: {exc!r}", file=sys.stderr)

    print(json.dumps(payload, ensure_ascii=True, indent=2, default=str))
    if payload["verdict"] == "PASS":
        return 0
    if payload["verdict"] == "BLOCKED_NETWORK":
        return 2
    if payload["verdict"] == "checksum_missing":
        return 3
    return 1


def _check_info_from_payload(check: dict[str, Any]) -> Optional[UpdateInfo]:
    """Rebuild an ``UpdateInfo`` from the JSON check payload.

    Args:
        check: Payload returned by :func:`_run_check`.

    Returns:
        Optional[UpdateInfo]: Reconstructed info, or ``None`` when incomplete.
    """
    if not check.get("ok"):
        return None
    remote = check.get("remote")
    asset = check.get("asset")
    if not isinstance(remote, dict) or not isinstance(asset, dict):
        return None
    local = check.get("local")
    if not isinstance(local, dict):
        return None
    return UpdateInfo(
        local_version=str(local.get("version") or ""),
        local_date=local.get("date"),
        update_available=bool(check.get("update_available")),
        reason=str(check.get("reason") or "none"),
        skipped_newer_tag=check.get("skipped_newer_tag"),
        remote=remote,
        asset=asset,
    )


if __name__ == "__main__":
    sys.exit(main())
