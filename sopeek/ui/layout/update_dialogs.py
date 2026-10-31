"""Update notification dialogs.

This module hosts all user-facing update dialogs built on
:class:`~sopeek.ui.components.styled_dialog.StyledDialog`:

* ``show_no_update`` — already up to date / skipped-tag notice
* ``show_check_error`` — manual check failure with retry
* ``show_update_available`` — release notes + download / release-page actions
* ``show_startup_update`` — non-modal startup "new version found" prompt
* ``show_download_progress`` — download progress with pause/resume/cancel
* ``show_install_confirm`` — synchronous install confirmation
* ``show_uac_cancelled`` — elevation cancelled notice
* ``UpdateCenterDialog`` — single-window check flow (checking / up to date /
  update available / failure), shared by the title bar and the About page

All dialogs listed above are implemented, including the download progress
dialog (``show_download_progress``), the synchronous install confirmation
(``show_install_confirm``), and the UAC-cancelled notice
(``show_uac_cancelled``).

Tracking contract:

* ``_active_dialogs`` holds every live dialog returned by a ``show_*``
  helper so callers can inspect/raise them.
* ``_active_progress_dialogs`` maps a download ``request_id`` to its single
  progress dialog (at most one dialog per request).
* Both ``finished`` and ``destroyed`` are wired to module-level
  ``_untrack_dialog``: no closure touches the dialog owner (settings /
  about page) and untracking is idempotent.
"""

from __future__ import annotations

import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Set

from PySide6.QtCore import QEventLoop, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLayout, QVBoxLayout, QWidget

from components.styled_dialog import StyledDialog
from components.styled_loading import StyledLoading
from components.styled_progress import StyledProgress
from components.styled_textarea import StyledTextarea
from theme import tm

from sopeek.services.installer_launcher import InstallerLauncher
from sopeek.services.update_service import get_update_service
from sopeek.ui.theme.app_stylesheet import register_widget_qss
from sopeek.utils.version_info import RELEASES_URL

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sopeek.services.update_service import UpdateInfo, UpdateService


# Dialogs returned by show_* helpers and still alive.
_active_dialogs: Set[StyledDialog] = set()

# Progress dialogs keyed by their download request id (one per request).
_active_progress_dialogs: Dict[str, StyledDialog] = {}

_RELEASES_PREFIX = f"{RELEASES_URL}/"
_NOTES_MAX_HEIGHT = 240


# ---------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------


def _track_dialog(dialog: StyledDialog, request_id: Optional[str] = None) -> None:
    """Register a dialog as active and auto-untrack it on close/destroy.

    Args:
        dialog: Dialog instance returned by a ``show_*`` helper.
        request_id: Download request id when this is a progress dialog;
            ``None`` tracks the dialog in ``_active_dialogs`` only.
    """
    _active_dialogs.add(dialog)
    if request_id is not None:
        _active_progress_dialogs[request_id] = dialog

    def _on_finished(*_args: object) -> None:
        _untrack_dialog(dialog, request_id)

    def _on_destroyed(*_args: object) -> None:
        _untrack_dialog(dialog, request_id)

    dialog.finished.connect(_on_finished)
    dialog.destroyed.connect(_on_destroyed)


def _untrack_dialog(
    dialog: StyledDialog, request_id: Optional[str] = None
) -> None:
    """Remove a dialog from tracking state (idempotent, identity based).

    A progress entry is only popped when it still points at ``dialog``;
    a different dialog sharing the same ``request_id`` cannot evict it.

    Args:
        dialog: Dialog instance to forget.
        request_id: Download request id used when the dialog was tracked.
    """
    _active_dialogs.discard(dialog)
    if request_id is not None and _active_progress_dialogs.get(request_id) is dialog:
        _active_progress_dialogs.pop(request_id, None)


# ---------------------------------------------------------------------------
# Data helpers (defensive: remote/asset come from a JSON sidecar)
# ---------------------------------------------------------------------------


def _remote(info: "UpdateInfo") -> dict[str, Any]:
    """Return the release metadata mapping, tolerating malformed values."""
    remote = getattr(info, "remote", None)
    return remote if isinstance(remote, dict) else {}


def _asset(info: "UpdateInfo") -> Optional[dict[str, Any]]:
    """Return the installer asset mapping, or ``None`` when unavailable."""
    asset = getattr(info, "asset", None)
    return asset if isinstance(asset, dict) else None


def _clean_text(value: object) -> str:
    """Normalize an optional text value to a stripped string."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value.replace("\r\n", "\n").strip()


def _with_v(value: object) -> str:
    """Normalize a version/tag to the display form ``vX.Y.Z``."""
    text = _clean_text(value)
    if not text:
        return ""
    return text if text.lower().startswith("v") else f"v{text}"


def _remote_version(info: "UpdateInfo") -> str:
    """Return the remote version with a ``v`` prefix."""
    remote = _remote(info)
    return _with_v(remote.get("version") or remote.get("tag"))


def _remote_tag(info: "UpdateInfo") -> str:
    """Return the remote release tag with a ``v`` prefix."""
    remote = _remote(info)
    return _with_v(remote.get("tag") or remote.get("version"))


def _local_tag(info: "UpdateInfo") -> str:
    """Return the local version with a ``v`` prefix."""
    return _with_v(getattr(info, "local_version", ""))


def _remote_date(info: "UpdateInfo") -> str:
    """Return a human-readable release date (``date`` then ``published_at``)."""
    remote = _remote(info)
    date = _clean_text(remote.get("date"))
    if not date:
        published = _clean_text(remote.get("published_at"))
        date = published.split("T", 1)[0] if published else ""
    return date or "未知"


def _notes(info: "UpdateInfo") -> str:
    """Return cleaned release notes (empty when absent)."""
    return _clean_text(_remote(info).get("notes"))


def _notes_truncated(info: "UpdateInfo") -> bool:
    """Whether the release notes were truncated by the updater."""
    return bool(_remote(info).get("notes_truncated"))


def _format_size(value: object) -> str:
    """Format an installer byte count as ``x.x MB`` (or KB for tiny files)."""
    try:
        size = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    megabytes = size / (1024 * 1024)
    if megabytes < 0.1:
        return f"{size / 1024:.0f} KB"
    return f"{megabytes:.1f} MB"


def _sha256(info: "UpdateInfo") -> str:
    """Return the installer SHA-256 digest, or an empty string."""
    asset = _asset(info)
    return _clean_text(asset.get("sha256")) if asset else ""


def _as_int(value: object) -> int:
    """Coerce a byte counter to a non-negative int (defensive)."""
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0


def _as_float(value: object) -> float:
    """Coerce a speed value to a non-negative float (defensive)."""
    try:
        return max(0.0, float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _format_mb(value: object) -> str:
    """Format a byte count as ``x.x MB`` for download statistics."""
    return f"{_as_int(value) / (1024 * 1024):.1f} MB"


def _format_speed(value: object) -> str:
    """Format a byte-per-second speed as ``x.x MB/s``."""
    return f"{_as_float(value) / (1024 * 1024):.1f} MB/s"


def _error_code(error: object) -> str:
    """Extract a stable error code from an ``UpdateError`` or mapping."""
    if isinstance(error, dict):
        return _clean_text(error.get("code"))
    return _clean_text(getattr(error, "code", ""))


def _error_text(error: object) -> str:
    """Extract a user-readable error message (never a traceback)."""
    if isinstance(error, dict):
        message = _clean_text(error.get("message"))
    else:
        message = _clean_text(getattr(error, "message", "")) or _clean_text(
            str(error)
        )
    if not message or "Traceback" in message:
        return "下载失败，请重试。"
    return message


def _skipped_tag_message(info: "UpdateInfo") -> str:
    """Explain why a newer tag was skipped (empty when nothing was skipped)."""
    skipped = _with_v(getattr(info, "skipped_newer_tag", None))
    if not skipped:
        return ""
    latest = _remote_tag(info)
    if latest:
        return f"{skipped} 暂无安装包，当前最新可用安装包为 {latest}"
    return f"{skipped} 暂无安装包。"


def _release_url(info: "UpdateInfo") -> str:
    """Return an allow-listed release URL, falling back to the releases page.

    Only HTTPS URLs under the project's own ``/releases/`` path are accepted;
    ``file://``, external hosts and whitespace-bearing values are rejected so
    a compromised sidecar cannot turn the button into an arbitrary opener.
    """
    candidate = _clean_text(_remote(info).get("html_url"))
    if not candidate:
        return RELEASES_URL
    if any(char.isspace() for char in candidate) or "\\" in candidate:
        return RELEASES_URL
    if not candidate.lower().startswith(_RELEASES_PREFIX.lower()):
        return RELEASES_URL
    return candidate


def _open_url(url: str) -> None:
    """Open an already-validated URL through the platform desktop service."""
    QDesktopServices.openUrl(QUrl(url))


def _weak_callback(
    callback: Optional[Callable[[], None]],
) -> Optional[Callable[[], None]]:
    """Wrap a bound method weakly so dialogs never keep their owner alive.

    Plain callables (lambdas, functions, ``functools.partial``) cannot be
    weak-referenced reliably; they are returned unchanged, which is safe
    because only page-bound methods carry a widget reference.
    """
    if callback is None:
        return None
    try:
        reference = weakref.WeakMethod(callback)  # type: ignore[arg-type]
    except TypeError:
        return callback

    def _call() -> None:
        target = reference()
        if target is not None:
            target()

    return _call


# ---------------------------------------------------------------------------
# Widget helpers
# ---------------------------------------------------------------------------


def _label(
    layout: QVBoxLayout,
    text: str,
    object_name: str,
    *,
    font_size: int = 13,
    bold: bool = False,
    hint: bool = False,
) -> QLabel:
    """Create, style and append a selectable wrapped label."""
    label = QLabel(text)
    label.setObjectName(object_name)
    label.setWordWrap(True)
    label.setTextFormat(Qt.PlainText)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    color = tm.qss_color(tm.text_hint) if hint else tm.text.name()
    weight = "600" if bold else "400"
    register_widget_qss(
        label,
        (
            f"font-size: {font_size}px; font-weight: {weight}; "
            f"color: {color}; background: transparent;"
        ),
    )
    layout.addWidget(label)
    return label


def _body() -> tuple[QWidget, QVBoxLayout]:
    """Create the transparent body container used by every dialog."""
    widget = QWidget()
    widget.setObjectName("UpdateDialogBody")
    register_widget_qss(widget, "background: transparent; border: none;")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    return widget, layout


def _dialog(title: str, body: QWidget, size: str = "default") -> StyledDialog:
    """Build a non-animated dialog (deterministic close/untrack in tests)."""
    return StyledDialog(
        size=size,
        dialog_type="default",
        title=title,
        body_widget=body,
        animate=False,
    )


def _present(dialog: StyledDialog) -> StyledDialog:
    """Track and show a dialog, keeping it alive for non-modal use."""
    _track_dialog(dialog)
    dialog.show_dialog()
    return dialog


def _place_over_parent(dialog: StyledDialog, parent: Optional[QWidget]) -> None:
    """Center a dialog over its owner without retaining the owner."""
    if parent is None:
        return
    try:
        anchor = parent.window()
    except RuntimeError:
        return
    if anchor is None or not anchor.isVisible():
        return
    dialog.move(anchor.frameGeometry().center() - dialog.rect().center())


# ---------------------------------------------------------------------------
# Public dialogs
# ---------------------------------------------------------------------------


def show_no_update(info: "UpdateInfo") -> StyledDialog:
    """Show the "already up to date" / skipped-newer-tag notice.

    Args:
        info: Result of the completed update check (may carry
            ``skipped_newer_tag`` for the skipped-tag wording).

    Returns:
        StyledDialog: The non-modal notice dialog.
    """
    skipped_message = _skipped_tag_message(info)
    local = _local_tag(info) or "未知"
    if skipped_message:
        title = "暂无可用的新版本"
        message = f"当前版本：{local}\n{skipped_message}"
    else:
        title = "已是最新版本"
        message = f"当前版本：{local}\n当前已是最新版本。"

    body, layout = _body()
    message_label = _label(layout, message, "UpdateNoUpdateMessage")
    layout.addStretch(1)

    dialog = _dialog(title, body)
    dialog._message_label = message_label  # type: ignore[attr-defined]
    later = dialog.add_footer_button("知道了", variant="primary")
    later.setObjectName("UpdateNoUpdateButton")
    later.clicked.connect(dialog.close_dialog)
    return _present(dialog)


def show_check_error(
    err: Exception, on_retry: Callable[[], None]
) -> StyledDialog:
    """Show a manual update-check failure with a retry action.

    Args:
        err: The error raised by the update check.
        on_retry: Callback invoked when the user presses retry.

    Returns:
        StyledDialog: The non-modal error dialog.
    """
    raw_message = _clean_text(getattr(err, "message", "")) or _clean_text(str(err))
    message = raw_message or "更新检查失败，请稍后重试。"
    # Never surface a traceback or exception class name to the user.
    if "Traceback" in message:
        message = "更新检查失败，请稍后重试。"

    body, layout = _body()
    message_label = _label(layout, message, "UpdateErrorMessage")
    _label(
        layout,
        "你可以点击“重试”重新检查。",
        "UpdateErrorHint",
        hint=True,
        font_size=12,
    )
    layout.addStretch(1)

    dialog = _dialog("检查更新失败", body)
    dialog._message_label = message_label  # type: ignore[attr-defined]

    close_button = dialog.add_footer_button("关闭", variant="secondary")
    close_button.setObjectName("UpdateErrorCloseButton")
    close_button.clicked.connect(dialog.close_dialog)

    retry_callback = _weak_callback(on_retry)
    retry_button = dialog.add_footer_button("重试", variant="primary")
    retry_button.setObjectName("UpdateRetryButton")
    dialog._retry_button = retry_button  # type: ignore[attr-defined]

    if retry_callback is not None:
        retry_button.clicked.connect(retry_callback)
    retry_button.clicked.connect(dialog.close_dialog)
    return _present(dialog)


def show_update_available(
    info: "UpdateInfo",
    on_download: Optional[Callable[[], None]] = None,
    on_open_release: Optional[Callable[[], None]] = None,
) -> StyledDialog:
    """Show release details for an available update.

    Args:
        info: Update metadata (version, notes, asset, ...).
        on_download: Callback for the download action.
        on_open_release: Callback for opening the release page.

    Returns:
        StyledDialog: The non-modal update dialog.
    """
    version = _remote_version(info) or "未知"
    asset = _asset(info)
    digest = _sha256(info)
    size_text = _format_size(asset.get("size") if asset else None)
    skipped_message = _skipped_tag_message(info)

    body, layout = _body()
    version_label = _label(
        layout,
        f"版本：{version}",
        "UpdateVersionLabel",
        font_size=15,
        bold=True,
    )
    date_label = _label(
        layout,
        f"构建日期：{_remote_date(info)}",
        "UpdateDateLabel",
        font_size=12,
        hint=True,
    )

    skipped_label: Optional[QLabel] = None
    if skipped_message:
        skipped_label = _label(
            layout,
            skipped_message,
            "UpdateSkippedTagLabel",
            font_size=12,
            hint=True,
        )

    _label(layout, "更新说明", "UpdateNotesTitleLabel", bold=True)

    notes_area = StyledTextarea(
        text=_notes(info),
        placeholder="该版本未提供更新说明",
        read_only=True,
    )
    notes_area.setObjectName("UpdateNotesTextarea")
    notes_area.setMaximumHeight(_NOTES_MAX_HEIGHT)
    layout.addWidget(notes_area)

    truncated_label: Optional[QLabel] = None
    if _notes_truncated(info):
        truncated_label = _label(
            layout,
            "更新说明过长，已截断，仅显示部分内容。",
            "UpdateNotesTruncatedLabel",
            font_size=12,
            hint=True,
        )

    download_enabled = on_download is not None and bool(digest)
    manual_hint_label: Optional[QLabel] = None
    if not download_enabled:
        if not digest:
            hint_text = (
                "该版本缺少安装包校验值，无法在应用内下载，"
                "请前往发布页手动下载。"
            )
        else:
            hint_text = "下载功能暂不可用，请前往发布页手动下载安装包。"
        manual_hint_label = _label(
            layout,
            hint_text,
            "UpdateManualDownloadHint",
            font_size=12,
            hint=True,
        )

    layout.addStretch(1)

    title = f"发现新版本 {version}" if version != "未知" else "发现新版本"
    dialog = _dialog(title, body, size="lg")

    # Attributes exposed for callers/tests that need to inspect or drive the UI.
    dialog._version_label = version_label  # type: ignore[attr-defined]
    dialog._date_label = date_label  # type: ignore[attr-defined]
    dialog._skipped_label = skipped_label  # type: ignore[attr-defined]
    dialog._notes_area = notes_area  # type: ignore[attr-defined]
    dialog._notes_truncated_label = truncated_label  # type: ignore[attr-defined]
    dialog._manual_hint_label = manual_hint_label  # type: ignore[attr-defined]

    later = dialog.add_footer_button("稍后", variant="secondary")
    later.setObjectName("UpdateLaterButton")
    later.clicked.connect(dialog.close_dialog)
    dialog._later_button = later  # type: ignore[attr-defined]

    open_button = dialog.add_footer_button("前往发布页", variant="secondary")
    open_button.setObjectName("UpdateOpenReleaseButton")
    dialog._open_release_button = open_button  # type: ignore[attr-defined]

    open_release_callback = _weak_callback(on_open_release)

    def _on_open_release() -> None:
        if open_release_callback is not None:
            open_release_callback()
        else:
            _open_url(_release_url(info))

    open_button.clicked.connect(_on_open_release)

    download_text = (
        f"下载更新（{size_text}）" if size_text else "下载更新"
    )
    download_button = dialog.add_footer_button(download_text, variant="primary")
    download_button.setObjectName("UpdateDownloadButton")
    download_button.setEnabled(download_enabled)
    dialog._download_button = download_button  # type: ignore[attr-defined]

    download_callback = _weak_callback(on_download)
    if download_enabled and download_callback is not None:
        download_button.clicked.connect(download_callback)
        download_button.clicked.connect(dialog.close_dialog)

    return _present(dialog)


def show_startup_update(parent: "QWidget", info: "UpdateInfo") -> StyledDialog:
    """Show the startup "new version available" prompt.

    Args:
        parent: Owner widget used for positioning.
        info: Update metadata for the newly available version.

    Returns:
        StyledDialog: The non-modal startup prompt.
    """
    local = _local_tag(info) or "未知"
    remote = _remote_version(info) or "未知"
    body_text = f"当前版本：{local}\n新版本：{remote}"
    skipped_message = _skipped_tag_message(info)
    if skipped_message:
        body_text = f"{body_text}\n{skipped_message}"

    body, layout = _body()
    body_label = _label(layout, body_text, "StartupUpdateBody")
    layout.addStretch(1)

    title = f"发现新版本 {remote}" if remote != "未知" else "发现新版本"
    dialog = _dialog(title, body)
    dialog._body_label = body_label  # type: ignore[attr-defined]

    later = dialog.add_footer_button("稍后", variant="secondary")
    later.setObjectName("StartupLaterButton")
    later.clicked.connect(dialog.close_dialog)
    dialog._later_button = later  # type: ignore[attr-defined]

    details = dialog.add_footer_button("查看详情", variant="primary")
    details.setObjectName("StartupDetailsButton")
    dialog._details_button = details  # type: ignore[attr-defined]

    details.clicked.connect(dialog.close_dialog)
    details.clicked.connect(lambda: show_update_available(info))

    _track_dialog(dialog)
    dialog.show_dialog()
    _place_over_parent(dialog, parent)
    return dialog


# ---------------------------------------------------------------------------
# Download progress (Todo 17)
# ---------------------------------------------------------------------------


class _DownloadProgressDialog(StyledDialog):
    """Single download progress dialog bound to one ``request_id``.

    Built once in ``__init__`` (no runtime widget add/remove). All six
    download signals are filtered by ``request_id``; resume keeps the same
    id so no rebinding is ever needed.

    Closing while the download is still active hides the dialog, detaches
    from the service, untracks it and asks the service to pause so the
    ``.part`` file survives for a later resume. In that path the dialog
    deliberately does NOT emit ``finished``: it is not a user-confirmed
    completion. Terminal paths (done/cancelled/failed) release tracking
    before closing and emit ``finished`` exactly once.
    """

    def __init__(
        self,
        info: "UpdateInfo",
        service: "UpdateService",
        request_id: str,
        *,
        animate: bool = False,
    ) -> None:
        self._info = info
        self._service = service
        self._request_id = request_id
        self._download_active = True
        self._closing = False
        self._finished_emitted = False
        self._state = "running"
        self._download_index = 0
        self._download_total = _as_int(_asset_size(info))
        self._download_speed = 0.0
        self._pause_ack_received = False
        self._connections: list[tuple[object, object]] = []
        self._pending_installer_path: str | None = None

        body, layout = _body()
        version = _remote_version(info) or ""
        title = f"正在下载 {version}" if version else "正在下载更新"

        self._progress = StyledProgress(
            value=0.0,
            size="default",
            label_title="下载进度",
            label_value="0%",
        )
        layout.addWidget(self._progress)

        self._stats_label = _label(
            layout, "0.0 MB / 0.0 MB · 0.0 MB/s", "DownloadStats", font_size=12
        )
        self._state_label = _label(
            layout, "下载中", "DownloadState", font_size=13, bold=True
        )
        self._hint_label = _label(
            layout, "", "DownloadHint", font_size=12, hint=True
        )
        self._hint_label.hide()
        self._error_label = QLabel("")
        self._error_label.setObjectName("DownloadError")
        self._error_label.setWordWrap(True)
        self._error_label.setTextFormat(Qt.PlainText)
        self._error_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        register_widget_qss(
            self._error_label,
            (
                f"font-size: 13px; font-weight: 600; "
                f"color: {tm.qss_color(tm.danger)}; background: transparent;"
            ),
        )
        self._error_label.hide()
        layout.addWidget(self._error_label)
        layout.addStretch(1)

        super().__init__(
            size="default",
            dialog_type="default",
            title=title,
            body_widget=body,
            animate=animate,
            show_close=False,
        )

        self._cancel_button = self.add_footer_button("取消", variant="secondary")
        self._cancel_button.setObjectName("DownloadCancelButton")
        self._retry_button = self.add_footer_button("重试", variant="primary")
        self._retry_button.setObjectName("DownloadRetryButton")
        self._retry_button.hide()
        self._pause_button = self.add_footer_button("暂停", variant="primary")
        self._pause_button.setObjectName("DownloadPauseButton")

        self._pause_button.clicked.connect(self._on_control_clicked)
        self._retry_button.clicked.connect(self._request_retry)
        self._cancel_button.clicked.connect(self._request_cancel)

        self._subscribe()
        self._apply_initial_state()

        self.finished.connect(self._mark_finished_emitted)
        self.finished.connect(self.deleteLater)

    # -- construction ---------------------------------------------------

    def _apply_initial_state(self) -> None:
        """Initialize progress/labels/buttons from the service snapshot."""
        snapshot = self._service.get_download_state(self._request_id)
        if snapshot is None:
            state, downloaded, total = "running", 0, self._download_total
        else:
            state, downloaded, total = snapshot
        self._set_progress(downloaded, total, 0.0)

        if state == "paused":
            self._state = "paused"
            self._pause_ack_received = True
            self._state_label.setText("已暂停")
            self._pause_button.setText("继续")
            self._pause_button.setEnabled(True)
        elif state == "verifying":
            self._state = "verifying"
            self._state_label.setText("校验中…")
            self._pause_button.setEnabled(False)
        else:
            self._state = "running"
            self._state_label.setText("下载中")
            self._pause_button.setEnabled(True)

    # -- service subscription ------------------------------------------

    def _subscribe(self) -> None:
        """Connect all six download signals to id-filtered slots."""
        self._connections = [
            (self._service.download_started, self._on_download_started),
            (
                self._service.download_progress,
                self._on_download_progress,
            ),
            (
                self._service.download_state_changed,
                self._on_download_state_changed,
            ),
            (
                self._service.download_pause_acked,
                self._on_download_pause_acked,
            ),
            (self._service.download_finished, self._on_download_finished),
            (self._service.download_failed, self._on_download_failed),
        ]
        for signal, slot in self._connections:
            signal.connect(slot)

    def _disconnect_service(self) -> None:
        """Detach every service signal (idempotent)."""
        for signal, slot in self._connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                continue
        self._connections.clear()

    # -- rendering ------------------------------------------------------

    def _set_progress(
        self, downloaded: object, total: object, speed: object
    ) -> None:
        """Update the progress bar and the MB/percent/speed labels."""
        self._download_index = _as_int(downloaded)
        self._download_total = _as_int(total) or self._download_total
        self._download_speed = _as_float(speed)

        if self._download_total > 0:
            value = min(1.0, self._download_index / self._download_total)
        else:
            value = 0.0
        percent = f"{int(value * 100)}%"
        self._progress.value = value
        self._progress.set_label("下载进度", percent)
        self._stats_label.setText(
            f"{_format_mb(self._download_index)} / "
            f"{_format_mb(self._download_total)} · "
            f"{_format_speed(self._download_speed)}"
        )

    # -- signal slots ---------------------------------------------------

    def _on_download_started(self, request_id: str) -> None:
        if request_id != self._request_id or not self._download_active:
            return
        if self._state == "paused":
            return
        self._state = "running"
        self._state_label.setText("下载中")
        self._pause_button.setText("暂停")
        self._pause_button.setEnabled(True)
        self._hint_label.hide()

    def _on_download_progress(
        self,
        request_id: str,
        downloaded: object,
        total: object,
        speed: float,
    ) -> None:
        if request_id != self._request_id or not self._download_active:
            return
        if self._state in ("paused", "verifying"):
            return
        self._set_progress(downloaded, total, speed)
        self._state_label.setText("下载中")

    def _on_download_state_changed(self, request_id: str, state: str) -> None:
        if request_id != self._request_id or not self._download_active:
            return
        if state == "paused":
            self._state = "paused"
            self._state_label.setText("已暂停")
            self._apply_pause_button()
        elif state == "verifying":
            self._state = "verifying"
            self._state_label.setText("校验中…")
            self._pause_button.setText("暂停")
            self._pause_button.setEnabled(False)
        elif state in ("running", "resumed"):
            self._state = "running"
            self._pause_ack_received = False
            self._state_label.setText("下载中")
            self._pause_button.setText("暂停")
            self._pause_button.setEnabled(True)
            self._hint_label.hide()

    def _on_download_pause_acked(self, request_id: str, accepted: bool) -> None:
        if request_id != self._request_id or not self._download_active:
            return
        if accepted:
            self._pause_ack_received = True
            self._apply_pause_button()
            return
        self._pause_ack_received = False
        self._pause_button.setText("暂停")
        self._pause_button.setEnabled(self._state != "verifying")
        self._hint_label.setText("校验中，无法暂停")
        self._hint_label.show()

    def _on_download_finished(self, request_id: str, _path: str) -> None:
        if request_id != self._request_id:
            return
        # A paused or already-closed dialog must not react to a late terminal
        # signal: the next "download" click re-checks the cache instead.
        if not self._download_active or self._state == "paused":
            return
        self._state = "done"
        self._download_active = False
        installer_path = _clean_text(_path)
        self._pending_installer_path = installer_path or None
        self._disconnect_service()
        _untrack_dialog(self, self._request_id)
        self._progress.value = 1.0
        self._progress.set_label("下载进度", "100%")
        self.close()

    def _on_download_failed(self, request_id: str, error: object) -> None:
        if request_id != self._request_id:
            return
        if not self._download_active:
            return
        self._download_active = False
        self._disconnect_service()
        _untrack_dialog(self, self._request_id)
        if _error_code(error) == "cancelled":
            # Cancellation is user-initiated: close silently, no error UI.
            self.close()
            return
        self._show_error(error)

    def _show_error(self, error: object) -> None:
        """Switch the dialog to its error/retry presentation."""
        self._state = "error"
        self._error_label.setText(_error_text(error))
        self._error_label.show()
        self._progress.hide()
        self._stats_label.hide()
        self._hint_label.hide()
        self._state_label.setText("下载失败")
        self._pause_button.hide()
        self._pause_button.setEnabled(False)
        self._retry_button.show()
        self._retry_button.setEnabled(True)
        self._cancel_button.setText("关闭")

    def _apply_pause_button(self) -> None:
        """Show "继续" only after both a true ack and a paused state."""
        if self._state == "paused" and self._pause_ack_received:
            self._pause_button.setText("继续")
            self._pause_button.setEnabled(True)
            self._hint_label.hide()
        else:
            self._pause_button.setText("暂停中…")
            self._pause_button.setEnabled(False)

    # -- user actions ---------------------------------------------------

    def _on_control_clicked(self) -> None:
        """Dispatch the shared pause/resume button by current state."""
        if self._state == "paused":
            self._request_resume()
        else:
            self._request_pause()

    def _request_pause(self) -> None:
        if not self._download_active or self._state in (
            "paused",
            "verifying",
        ):
            return
        self._pause_ack_received = False
        self._pause_button.setText("暂停中…")
        self._pause_button.setEnabled(False)
        service = self._service
        request_id = self._request_id
        QTimer.singleShot(0, lambda: service.pause_download(request_id))

    def _request_resume(self) -> None:
        if not self._download_active:
            return
        self._pause_button.setText("继续中…")
        self._pause_button.setEnabled(False)
        service = self._service
        request_id = self._request_id
        reference = weakref.ref(self)

        def _resume() -> None:
            accepted = service.resume_download(request_id)
            dialog = reference()
            if dialog is not None:
                dialog._on_resume_result(accepted)

        QTimer.singleShot(0, _resume)

    def _on_resume_result(self, accepted: bool) -> None:
        """Reflect a successful resume; keep the paused state otherwise."""
        if accepted:
            self._state = "running"
            self._pause_ack_received = False
            self._state_label.setText("下载中")
            self._pause_button.setText("暂停")
            self._pause_button.setEnabled(True)
            self._hint_label.hide()
        elif self._state == "paused":
            self._pause_button.setText("继续")
            self._pause_button.setEnabled(True)

    def _request_cancel(self) -> None:
        if self._state == "error":
            self.close_dialog()
            return
        if not self._download_active:
            return
        self._cancel_button.setEnabled(False)
        service = self._service
        request_id = self._request_id
        QTimer.singleShot(0, lambda: service.cancel_download(request_id))

    def _request_retry(self) -> None:
        self._retry_button.setEnabled(False)
        info = self._info
        service = self._service
        self._download_active = False
        _untrack_dialog(self, self._request_id)
        QTimer.singleShot(
            0, lambda: show_download_progress(info, service)
        )
        self.close_dialog()

    # -- finished tracking / close -------------------------------------

    def _mark_finished_emitted(self, *_args: object) -> None:
        """Record ``finished`` and hand a completed download to install UI.

        The hook runs only when ``_on_download_finished`` stored a path; manual
        close, cancel, error and close-as-pause therefore never launch the
        installer confirmation.
        """
        self._finished_emitted = True
        installer_path = self._pending_installer_path
        self._pending_installer_path = None
        if installer_path:
            show_install_confirm(self._info, installer_path)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Close-as-pause while active; otherwise delegate to the base class."""
        if self._download_active:
            if self._closing:
                event.ignore()
                return
            self._closing = True
            self.hide()
            self._disconnect_service()
            _untrack_dialog(self, self._request_id)
            service = self._service
            request_id = self._request_id
            QTimer.singleShot(0, lambda: service.pause_download(request_id))
            event.ignore()
            self.deleteLater()
            return
        if self._finished_emitted:
            event.accept()
            return
        super().closeEvent(event)


def _asset_size(info: "UpdateInfo") -> object:
    """Return the asset size when present (0 otherwise)."""
    asset = _asset(info)
    return asset.get("size") if asset else 0


def show_download_progress(
    info: "UpdateInfo", service: "UpdateService"
) -> StyledDialog:
    """Show (or re-raise) the download progress dialog for a request.

    The download is started before the dialog is built so the constructor
    can read ``get_download_state`` for an accurate initial state (notably a
    paused request reopened after closing). At most one dialog exists per
    ``request_id``; a second call re-raises the live instance.

    Args:
        info: Update metadata for the asset being downloaded.
        service: Update service used to start/subscribe to the download.

    Returns:
        StyledDialog: The live progress dialog for the download request.
    """
    request_id = service.start_download(info)

    existing = _active_progress_dialogs.get(request_id)
    if existing is not None:
        try:
            if not existing.isVisible():
                existing.show()
            existing.raise_()
            existing.activateWindow()
        except RuntimeError:
            _active_progress_dialogs.pop(request_id, None)
        else:
            return existing

    dialog = _DownloadProgressDialog(info, service, request_id)
    _track_dialog(dialog, request_id)
    dialog.show_dialog()
    return dialog


class _InstallConfirmDialog(StyledDialog):
    """Install confirmation dialog that keeps working while the worker runs."""

    confirmed = Signal()

    def __init__(
        self,
        info: "UpdateInfo",
        installer_path: str,
        *,
        missing_data: bool = False,
    ) -> None:
        """Build the confirmation dialog.

        Args:
            info: Update metadata for the downloaded version.
            installer_path: Downloaded installer path.
            missing_data: Whether required asset metadata is missing.
        """
        body, layout = _body()
        super().__init__(
            title="安装更新",
            body_widget=body,
            show_close=False,
            animate=False,
            parent=None,
        )
        self._confirm_requested = False
        self._allow_close = False
        self._missing_data = missing_data

        version = _remote_version(info) or _remote_tag(info) or "未知版本"
        asset = getattr(info, "asset", None) or {}
        size = asset.get("size") if isinstance(asset, dict) else None

        self._version_label = _label(
            layout, f"版本：{version}", "InstallVersionLabel"
        )
        self._path_label = _label(
            layout,
            f"安装包：{installer_path or '未提供'}",
            "InstallPathLabel",
            font_size=12,
            hint=True,
        )
        self._size_label = _label(
            layout,
            f"大小：{_format_size(size) if isinstance(size, int) else '未知'}",
            "InstallSizeLabel",
            font_size=12,
            hint=True,
        )
        self._status_label = _label(
            layout,
            (
                "安装包校验信息不完整，无法安装。"
                if missing_data
                else "确认后将校验安装包并关闭更新组件。"
            ),
            "InstallStatusLabel",
            font_size=12,
            hint=True,
        )
        layout.addStretch(1)

        self._cancel_button = self.add_footer_button(
            "取消", variant="secondary"
        )
        self._cancel_button.setObjectName("InstallCancelButton")
        self._confirm_button = self.add_footer_button(
            "安装", variant="primary"
        )
        self._confirm_button.setObjectName("InstallConfirmButton")
        self._confirm_button.setEnabled(not missing_data)
        self._cancel_button.clicked.connect(self.close_dialog)
        self._confirm_button.clicked.connect(self._request_confirm)

    def _request_confirm(self) -> None:
        """Emit ``confirmed`` once and disable both footer buttons."""
        if self._confirm_requested:
            return
        self._confirm_requested = True
        self._confirm_button.setEnabled(False)
        self._cancel_button.setEnabled(False)
        self.confirmed.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Treat Escape as cancellation, except while a launch is running."""
        if event.key() == Qt.Key.Key_Escape:
            if self._confirm_requested and not self._allow_close:
                event.ignore()
                return
            self.close_dialog(0)
            event.accept()
            return
        super().keyPressEvent(event)

    def finish_close(self, result: int = 0) -> None:
        """Allow the terminal close after the launcher reaches a result."""
        self._allow_close = True
        self.close_dialog(result)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Keep the dialog open while the launcher worker is running."""
        if self._confirm_requested and not self._allow_close:
            event.ignore()
            return
        super().closeEvent(event)


def show_install_confirm(info: "UpdateInfo", installer_path: str) -> bool:
    """Ask the user to confirm installing a downloaded update.

    The dialog stays visible while the installer is verified and the updater
    sidecar is shut down.  Confirming closes the dialog only after the
    launcher reaches a terminal state.

    Args:
        info: Update metadata for the downloaded version.
        installer_path: Path to the downloaded installer.

    Returns:
        bool: True when the user confirms the installation.
    """
    path_text = _clean_text(installer_path)
    asset = getattr(info, "asset", None) or {}
    sha256 = ""
    size: Any = None
    if isinstance(asset, dict):
        raw_sha = asset.get("sha256")
        if isinstance(raw_sha, str):
            sha256 = raw_sha.strip()
        size = asset.get("size")

    missing_data = (
        not path_text
        or not sha256
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size <= 0
    )

    dialog = _InstallConfirmDialog(info, path_text, missing_data=missing_data)
    _track_dialog(dialog)
    confirmed = [False]
    launchers: list[InstallerLauncher] = []
    loop = QEventLoop()
    loop_finished = [False]

    def _close_loop(*_args: Any) -> None:
        loop_finished[0] = True
        loop.quit()

    def _on_confirm() -> None:
        if missing_data:
            dialog._status_label.setText("安装包校验信息不完整，无法安装。")
            show_install_failure("安装包校验信息不完整，无法安装。")
            QTimer.singleShot(0, lambda: dialog.finish_close(0))
            return
        try:
            service = get_update_service()
            launcher = InstallerLauncher(service)
        except Exception as exc:  # noqa: BLE001 - keep dialog usable
            dialog._status_label.setText(f"无法启动安装流程：{exc}")
            QTimer.singleShot(0, lambda: dialog.finish_close(0))
            return

        launchers.append(launcher)
        launcher.finished.connect(_on_launcher_finished)
        dialog._status_label.setText("正在校验安装包并关闭更新组件…")
        try:
            started = launcher.start(path_text, sha256)
        except Exception as exc:  # noqa: BLE001 - keep dialog usable
            dialog._status_label.setText(f"无法启动安装流程：{exc}")
            QTimer.singleShot(0, lambda: dialog.finish_close(0))
            return
        confirmed[0] = True
        if started is False:
            confirmed[0] = False
            dialog._status_label.setText("安装流程未能启动，已取消安装。")
            QTimer.singleShot(0, lambda: dialog.finish_close(0))

    def _on_launcher_finished(*_args: Any) -> None:
        dialog.finish_close(0)

    dialog.confirmed.connect(_on_confirm)
    dialog.finished.connect(_close_loop)
    dialog.destroyed.connect(_close_loop)
    dialog.show_dialog()
    if not loop_finished[0]:
        loop.exec()
    return confirmed[0]


def show_install_failure(message: str) -> StyledDialog:
    """Show a non-modal, readable install failure notice.

    Args:
        message: Failure detail; an empty value falls back to generic text.

    Returns:
        StyledDialog: The tracked failure dialog.
    """
    text = _clean_text(message) or "安装更新失败，请稍后重试。"
    body, layout = _body()
    message_label = _label(layout, text, "InstallFailureMessage")
    layout.addStretch(1)

    dialog = _dialog("无法安装更新", body)
    dialog._message_label = message_label
    close_button = dialog.add_footer_button("知道了", variant="primary")
    close_button.setObjectName("InstallFailureCloseButton")
    close_button.clicked.connect(dialog.close_dialog)
    dialog._close_button = close_button
    return _present(dialog)


def show_uac_cancelled(path: str) -> StyledDialog:
    """Show the elevation-cancelled notice.

    The notice is non-modal and deliberately does not retry or launch the
    installer; it only offers the containing folder.

    Args:
        path: Installer path whose elevation was cancelled.

    Returns:
        StyledDialog: The non-modal notice dialog.
    """
    path_text = _clean_text(path)
    body, layout = _body()
    _label(
        layout,
        "安装程序需要管理员权限，但权限请求已取消。"
        "应用将继续运行，你可以稍后重试。",
        "UacCancelledMessage",
    )
    path_label = _label(
        layout,
        f"安装包：{path_text or '未提供'}",
        "UacCancelledPath",
        font_size=12,
        hint=True,
    )
    layout.addStretch(1)

    dialog = _dialog("已取消权限请求", body)
    dialog._path_label = path_label
    open_button = dialog.add_footer_button("打开文件夹", variant="secondary")
    open_button.setObjectName("UacOpenFolderButton")
    open_button.clicked.connect(lambda: _open_installer_folder(path_text))
    close_button = dialog.add_footer_button("关闭", variant="primary")
    close_button.setObjectName("UacCloseButton")
    close_button.clicked.connect(dialog.close_dialog)
    dialog._open_folder_button = open_button
    dialog._close_button = close_button
    return _present(dialog)


def _open_installer_folder(path_text: str) -> None:
    """Open only the folder containing ``path_text``.

    Args:
        path_text: Installer path; empty opens the current directory.
    """
    folder = Path(path_text).resolve().parent if path_text else Path.cwd()
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


class UpdateCenterDialog(StyledDialog):
    """Single-window update center with four visual states.

    The dialog shell is built once. Every footer button is created before
    the first ``show()`` because the public footer API freezes afterwards;
    state switches only toggle visibility and rebuild the body children,
    then call :meth:`StyledDialog.remeasure` so the fixed window size
    follows the content.
    """

    STATE_CHECKING = "checking"
    STATE_NO_UPDATE = "no_update"
    STATE_AVAILABLE = "available"
    STATE_ERROR = "error"

    #: Release notes viewport height (same cap as ``show_update_available``).
    NOTES_MAX_HEIGHT = 240

    def __init__(
        self,
        on_download: Optional[Callable[["UpdateInfo"], None]] = None,
        on_retry: Optional[Callable[[], None]] = None,
    ) -> None:
        """Build the dialog shell and its footer actions.

        Args:
            on_download: Called with the ``UpdateInfo`` when the user asks
                to download the available installer.
            on_retry: Called when the user asks to run the check again.
        """
        self._on_download = on_download
        self._on_retry = on_retry
        self._state = ""
        self._info: Optional["UpdateInfo"] = None
        self._body, self._body_layout = _body()
        self._loading_widget: Optional[StyledLoading] = None
        self._version_label: Optional[QLabel] = None
        self._notes_area: Optional[StyledTextarea] = None

        super().__init__(
            size="default",
            dialog_type="default",
            title="检查更新",
            body_widget=self._body,
            animate=False,
            show_close=True,
        )

        # add_footer_button() is only legal before the first show(); create
        # every action now and let each state toggle visibility.
        self._close_button = self.add_footer_button("关闭", variant="secondary")
        self._later_button = self.add_footer_button("稍后", variant="secondary")
        self._release_button = self.add_footer_button("前往发布页", variant="secondary")
        self._retry_button = self.add_footer_button("重试", variant="primary")
        self._download_button = self.add_footer_button("下载更新", variant="primary")

        self._close_button.clicked.connect(self.close_dialog)
        self._later_button.clicked.connect(self.close_dialog)
        self._release_button.clicked.connect(self._open_release_page)
        self._retry_button.clicked.connect(self._request_retry)
        self._download_button.clicked.connect(self._request_download)

        for button in (
            self._close_button,
            self._later_button,
            self._release_button,
            self._retry_button,
            self._download_button,
        ):
            button.hide()

    # -- State API -----------------------------------------------------

    def current_state(self) -> str:
        """Return the state currently rendered by the dialog.

        Returns:
            str: One of ``checking`` / ``no_update`` / ``available`` /
            ``error``; an empty string before the first state is applied.
        """
        return self._state

    def set_checking(self, local_version: str = "") -> None:
        """Render the "checking for updates" state.

        Args:
            local_version: Local version shown below the spinner.
        """
        self._info = None
        self._apply_state(
            self.STATE_CHECKING,
            lambda: self._build_checking(local_version),
        )

    def set_result(self, info: "UpdateInfo") -> None:
        """Render a completed check result.

        Args:
            info: Result snapshot produced by the update service.
        """
        self._info = info
        if bool(getattr(info, "update_available", False)):
            self._apply_state(self.STATE_AVAILABLE, self._build_available)
        else:
            self._apply_state(self.STATE_NO_UPDATE, self._build_no_update)

    def set_error(self, err: object) -> None:
        """Render a manual check failure with a retry action.

        Args:
            err: Error object raised by the update check (``UpdateError``
                is a frozen dataclass, not an ``Exception`` subclass).
        """
        self._info = None
        self._apply_state(self.STATE_ERROR, lambda: self._build_error(err))

    # -- State plumbing ------------------------------------------------

    def _apply_state(self, state: str, builder: Callable[[], None]) -> None:
        """Clear the body, rebuild it and resize the dialog.

        Args:
            state: New state name.
            builder: Callable that appends the body widgets for ``state``.
        """
        self._state = state
        self._clear_body()
        builder()
        self._sync_buttons()
        # Widgets created after the dialog is already visible are not polished
        # and still carry the hidden flag, so both their sizeHint() and the
        # layout contribution are zero until the next event-loop turn. Polish
        # and show the rebuilt subtree so the measurement below is accurate.
        self._body.ensurePolished()
        for child in self._body.findChildren(QWidget):
            child.ensurePolished()
            child.show()
        self._body_layout.invalidate()
        self._body_layout.activate()
        self._body.updateGeometry()
        self.remeasure()

    def _clear_body(self) -> None:
        """Delete every widget/layout previously added to the body."""
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Detach before deleteLater so the stale widget is no longer
                # returned by findChildren() during the next state rebuild.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
                continue
            child = item.layout()
            if child is not None:
                self._clear_nested_layout(child)

    @staticmethod
    def _clear_nested_layout(layout: QLayout) -> None:
        """Delete all items of a nested layout and the layout itself.

        Args:
            layout: Layout to drain and delete.
        """
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
                continue
            child = item.layout()
            if child is not None:
                UpdateCenterDialog._clear_nested_layout(child)
        layout.deleteLater()

    def _sync_buttons(self) -> None:
        """Toggle the pre-created footer buttons for the current state."""
        state = self._state
        info = self._info

        self._close_button.setVisible(
            state in (self.STATE_CHECKING, self.STATE_NO_UPDATE, self.STATE_ERROR)
        )
        self._close_button.setText(
            "知道了" if state == self.STATE_NO_UPDATE else "关闭"
        )
        self._later_button.setVisible(state == self.STATE_AVAILABLE)
        self._release_button.setVisible(state == self.STATE_AVAILABLE)
        self._retry_button.setVisible(state == self.STATE_ERROR)
        self._download_button.setVisible(state == self.STATE_AVAILABLE)

        download_enabled = (
            state == self.STATE_AVAILABLE
            and info is not None
            and bool(_sha256(info))
            and self._on_download is not None
        )
        self._download_button.setEnabled(download_enabled)
        if state == self.STATE_AVAILABLE and info is not None:
            asset = _asset(info)
            size_text = _format_size(asset.get("size") if asset else None)
            self._download_button.setText(
                f"下载更新（{size_text}）" if size_text else "下载更新"
            )

    # -- Body builders -------------------------------------------------

    def _build_checking(self, local_version: str) -> None:
        """Append the checking state body.

        Args:
            local_version: Local version shown under the spinner.
        """
        loading_row = QHBoxLayout()
        loading_row.setContentsMargins(0, 0, 0, 0)
        loading_row.setSpacing(12)
        self._loading_widget = StyledLoading(size="default", auto_start=True)
        loading_row.addWidget(self._loading_widget)

        title = QLabel("正在检查更新…")
        title.setTextFormat(Qt.PlainText)
        register_widget_qss(
            title,
            (
                f"font-size: 14px; font-weight: 600; "
                f"color: {tm.text.name()}; background: transparent;"
            ),
        )
        loading_row.addWidget(title, 1)
        self._body_layout.addLayout(loading_row)

        self._version_label = _label(
            self._body_layout,
            f"当前版本：v{local_version}" if local_version else "当前版本：未知",
            "UpdateCenterVersion",
            font_size=12,
            hint=True,
        )
        _label(
            self._body_layout,
            "正在连接 GitHub 获取最新发布信息。",
            "UpdateCenterHint",
            font_size=12,
            hint=True,
        )
        self._body_layout.addStretch(1)

    def _build_no_update(self) -> None:
        """Append the already-up-to-date state body."""
        info = self._info
        local = _local_tag(info) if info is not None else ""
        skipped_message = _skipped_tag_message(info) if info is not None else ""

        _label(
            self._body_layout,
            "暂无可用的新版本" if skipped_message else "已是最新版本",
            "UpdateCenterTitle",
            font_size=14,
            bold=True,
        )
        self._version_label = _label(
            self._body_layout,
            f"当前版本：{local or '未知'}",
            "UpdateCenterVersion",
            font_size=13,
        )
        if skipped_message:
            _label(
                self._body_layout,
                skipped_message,
                "UpdateSkippedTagLabel",
                font_size=12,
                hint=True,
            )
        else:
            _label(
                self._body_layout,
                "当前已是最新版本。",
                "UpdateCenterMessage",
                font_size=12,
                hint=True,
            )
        self._body_layout.addStretch(1)

    def _build_available(self) -> None:
        """Append the update-available state body."""
        info = self._info
        if info is None:
            return
        digest = _sha256(info)
        skipped_message = _skipped_tag_message(info)

        self._version_label = _label(
            self._body_layout,
            f"版本：{_remote_version(info) or '未知'}",
            "UpdateVersionLabel",
            font_size=15,
            bold=True,
        )
        _label(
            self._body_layout,
            f"构建日期：{_remote_date(info)}",
            "UpdateDateLabel",
            font_size=12,
            hint=True,
        )
        if skipped_message:
            _label(
                self._body_layout,
                skipped_message,
                "UpdateSkippedTagLabel",
                font_size=12,
                hint=True,
            )

        _label(self._body_layout, "更新说明", "UpdateNotesTitleLabel", bold=True)
        self._notes_area = StyledTextarea(
            text=_notes(info),
            placeholder="该版本未提供更新说明",
            read_only=True,
        )
        self._notes_area.setObjectName("UpdateNotesTextarea")
        self._notes_area.setMaximumHeight(self.NOTES_MAX_HEIGHT)
        self._body_layout.addWidget(self._notes_area)

        if _notes_truncated(info):
            _label(
                self._body_layout,
                "更新说明过长，已截断，仅显示部分内容。",
                "UpdateNotesTruncatedLabel",
                font_size=12,
                hint=True,
            )
        if not digest:
            _label(
                self._body_layout,
                "该版本缺少安装包校验值，无法在应用内下载，请前往发布页手动下载。",
                "UpdateManualDownloadHint",
                font_size=12,
                hint=True,
            )
        elif self._on_download is None:
            _label(
                self._body_layout,
                "下载功能暂不可用，请前往发布页手动下载安装包。",
                "UpdateManualDownloadHint",
                font_size=12,
                hint=True,
            )
        self._body_layout.addStretch(1)

    def _build_error(self, err: object) -> None:
        """Append the check-failure state body.

        Args:
            err: Error object raised by the update check.
        """
        raw_message = _clean_text(getattr(err, "message", "")) or _clean_text(
            str(err)
        )
        message = raw_message or "更新检查失败，请稍后重试。"
        if "Traceback" in message:
            message = "更新检查失败，请稍后重试。"

        _label(
            self._body_layout,
            message,
            "UpdateErrorMessage",
            font_size=13,
            bold=True,
        )
        _label(
            self._body_layout,
            "你可以点击“重试”重新检查。",
            "UpdateErrorHint",
            font_size=12,
            hint=True,
        )
        self._body_layout.addStretch(1)

    # -- Actions -------------------------------------------------------

    def _open_release_page(self) -> None:
        """Open the allow-listed release page for the current release."""
        if self._info is not None:
            _open_url(_release_url(self._info))
        else:
            _open_url(RELEASES_URL)

    def _request_retry(self) -> None:
        """Close the dialog and hand control back to the retry callback."""
        callback = self._on_retry
        self.close_dialog()
        if callback is not None:
            QTimer.singleShot(0, callback)

    def _request_download(self) -> None:
        """Hand the current update info to the download callback."""
        callback = self._on_download
        info = self._info
        if callback is None or info is None:
            return
        callback(info)


