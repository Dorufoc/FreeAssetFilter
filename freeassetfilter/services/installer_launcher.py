"""Install-flow service for a downloaded update installer.

The flow is deliberately split into two halves:

* A single :class:`QRunnable` performs the native verification, shuts the
  updater sidecar down, and independently rechecks the installer with Python
  ``hashlib`` plus a Windows read-only file identity.  It runs on a private
  ``QThreadPool`` and never touches Qt widgets.
* :meth:`InstallerLauncher.handle_result` runs on the GUI thread and turns the
  worker result into a launch decision: path validation, ``ShellExecuteW``
  elevation, application quit, or a readable failure/UAC notice.

The public :attr:`InstallerLauncher.finished` signal always carries exactly one
fixed seven-tuple::

    (installer_path, verified, shutdown_ok, recheck_ok, handle, identity, error)

``error`` is ``None`` only when every check succeeded.  ``handle`` is the raw
``CreateFileW`` handle kept open across ``ShellExecuteW``; the GUI handler
closes it on every path.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtWidgets import QApplication

from freeassetfilter.utils.app_logger import debug, warning
from freeassetfilter.utils.path_utils import get_app_data_path, is_path_within_base

# Windows constants used by the independent recheck and elevation launch.
GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
SW_SHOWNORMAL = 1
ERROR_CANCELLED = 1223
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_READ_CHUNK = 1024 * 1024

#: Download directory is the only allowed installer source.
DOWNLOAD_DIRNAME = "download"


class _FILETIME(ctypes.Structure):
    """Win32 ``FILETIME`` (two ``DWORD`` halves)."""

    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    """Win32 ``BY_HANDLE_FILE_INFORMATION`` (only identity fields are read)."""

    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", _FILETIME),
        ("ftLastAccessTime", _FILETIME),
        ("ftLastWriteTime", _FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


def _kernel32() -> Any:
    """Return a ``kernel32`` DLL loaded with ``use_last_error``."""
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _get_file_information(handle: int) -> _BY_HANDLE_FILE_INFORMATION:
    """Return Win32 metadata for an already-open handle.

    Args:
        handle: Raw ``CreateFileW`` handle.

    Returns:
        _BY_HANDLE_FILE_INFORMATION: Metadata including attributes and identity.

    Raises:
        OSError: When ``GetFileInformationByHandle`` fails.
    """
    kernel32 = _kernel32()
    get_info = kernel32.GetFileInformationByHandle
    get_info.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION),
    ]
    get_info.restype = wintypes.BOOL

    info = _BY_HANDLE_FILE_INFORMATION()
    ok = get_info(wintypes.HANDLE(handle), ctypes.byref(info))
    if not ok:
        raise OSError(ctypes.get_last_error(), "读取安装包文件标识失败")
    return info


def _open_installer_handle(path: Path) -> int:
    """Open ``path`` read-only, denying write/delete sharing.

    Args:
        path: Installer file to open.

    Returns:
        int: Raw ``CreateFileW`` handle.

    Raises:
        OSError: When Windows refuses to open the file.
    """
    kernel32 = _kernel32()
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
        GENERIC_READ,
        FILE_SHARE_READ,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    raw_handle = handle.value if hasattr(handle, "value") else handle
    if not raw_handle or int(raw_handle) == _INVALID_HANDLE_VALUE:
        raise OSError(ctypes.get_last_error(), f"无法打开安装包: {path}")
    raw_handle = int(raw_handle)
    try:
        info = _get_file_information(raw_handle)
    except OSError:
        _close_handle(raw_handle)
        raise
    if info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT:
        _close_handle(raw_handle)
        raise OSError(
            f"安装包不能是符号链接或目录联接: {path}"
        )
    return raw_handle


def _close_handle(handle: Optional[int]) -> None:
    """Close a raw Windows handle (no-op for ``None``)."""
    if handle is None:
        return
    try:
        kernel32 = _kernel32()
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        close_handle(wintypes.HANDLE(handle))
    except Exception as exc:  # noqa: BLE001 - closing must never raise
        warning(f"关闭安装包句柄失败: {exc!r}")


def _compute_sha256(handle: int) -> str:
    """Compute SHA-256 by reading the already-open handle.

    Reading through the same handle avoids a close-then-reopen window between
    the hash and the identity checks.

    Args:
        handle: Raw ``CreateFileW`` handle positioned at the file start.

    Returns:
        str: Lower-case hex digest.

    Raises:
        OSError: When ``ReadFile`` fails.
    """
    kernel32 = _kernel32()
    read_file = kernel32.ReadFile
    read_file.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPDWORD,
        wintypes.LPVOID,
    ]
    read_file.restype = wintypes.BOOL

    digest = hashlib.sha256()
    buffer = ctypes.create_string_buffer(_READ_CHUNK)
    read = wintypes.DWORD(0)
    while True:
        ok = read_file(
            wintypes.HANDLE(handle),
            buffer,
            _READ_CHUNK,
            ctypes.byref(read),
            None,
        )
        if not ok:
            raise OSError(ctypes.get_last_error(), "读取安装包失败")
        if read.value == 0:
            break
        digest.update(buffer.raw[: read.value])
    return digest.hexdigest()


def _file_identity(handle: int) -> tuple[int, int]:
    """Return ``(volume_serial, file_index)`` for an open handle.

    Args:
        handle: Raw ``CreateFileW`` handle.

    Returns:
        tuple[int, int]: Volume serial number and 64-bit file index.

    Raises:
        OSError: When ``GetFileInformationByHandle`` fails.
    """
    info = _get_file_information(handle)
    file_index = (int(info.nFileIndexHigh) << 32) | int(info.nFileIndexLow)
    return int(info.dwVolumeSerialNumber), file_index


def _python_recheck(
    path: Path,
    expected_sha256: str,
    rust_identity: tuple[int, int],
) -> tuple[int, tuple[int, int], bool]:
    """Independently hash and identify the installer from one open handle.

    Args:
        path: Installer path to open.
        expected_sha256: Digest expected by the release metadata.
        rust_identity: ``(volume_serial, file_index)`` reported by Rust.

    Returns:
        tuple[int, tuple[int, int], bool]: Open handle, Python identity, and
        whether both the hash and the identity matched.

    Raises:
        OSError: When the file cannot be opened, read, or inspected.
    """
    handle = _open_installer_handle(path)
    try:
        digest = _compute_sha256(handle)
        identity = _file_identity(handle)
        hash_ok = digest.strip().lower() == str(expected_sha256).strip().lower()
        identity_ok = identity == (
            int(rust_identity[0]),
            int(rust_identity[1]),
        )
        return handle, identity, bool(hash_ok and identity_ok)
    except BaseException:
        _close_handle(handle)
        raise


def _safe_delete(path: Optional[Path]) -> None:
    """Delete an installer quietly (missing files are not an error)."""
    if path is None:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        warning(f"删除安装包失败: {exc!r}")


def _launch_path(path_text: str) -> Optional[Path]:
    """Resolve and validate an installer path before elevation.

    The path must live under ``<app_data>/download`` (realpath boundary),
    be a regular file, and have an exact ``.exe`` suffix.

    Args:
        path_text: Candidate installer path.

    Returns:
        Optional[Path]: Resolved path when safe, otherwise ``None``.
    """
    if not path_text:
        return None
    try:
        candidate = Path(path_text)
        if not candidate.is_absolute():
            return None
        base = Path(get_app_data_path()) / DOWNLOAD_DIRNAME
        if not is_path_within_base(str(candidate), str(base)):
            return None
        resolved = Path(os.path.realpath(str(candidate)))
        base_resolved = Path(os.path.realpath(str(base)))
        if not resolved.is_relative_to(base_resolved):
            return None
        if resolved.suffix.lower() != ".exe":
            return None
        if not resolved.is_file():
            return None
        return resolved
    except (OSError, ValueError) as exc:
        debug(f"安装包路径校验失败: {exc!r}")
        return None


def launch_installer(path: Path | str) -> int:
    """Elevate and run the installer through ``ShellExecuteW``.

    Args:
        path: Already validated installer path.

    Returns:
        int: ``ShellExecuteW`` return value; ``None`` becomes ``0``.
    """
    installer = Path(path)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell_execute_w = shell32.ShellExecuteW
    shell_execute_w.argtypes = [
        wintypes.HWND,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_int,
    ]
    shell_execute_w.restype = ctypes.c_void_p
    ctypes.set_last_error(0)
    result = shell_execute_w(
        None,
        "runas",
        str(installer),
        None,
        str(installer.parent),
        SW_SHOWNORMAL,
    )
    return int(result or 0)


def _shell_execute(path: Path | str) -> int:
    """Backward-compatible wrapper around :func:`launch_installer`."""
    return launch_installer(path)


def _get_last_error() -> int:
    """Return the calling thread's last Win32 error."""
    return int(ctypes.get_last_error())


def _quit_app() -> None:
    """Quit the application once a successful elevation was requested."""
    app = QApplication.instance()
    if app is not None:
        app.quit()


class _InstallVerifySignals(QObject):
    """Signal emitter owned by :class:`InstallerLauncher`.

    ``finished`` is emitted from the worker thread with the fixed seven-tuple
    and queued back to the launcher's GUI thread before any launch work starts.
    """

    finished = Signal(object)


# Backward-compatible alias used by older tests/imports.
InstallerSignals = _InstallVerifySignals


class _VerifyTask(QRunnable):
    """One-shot worker: native verify -> sidecar shutdown -> Python recheck."""

    def __init__(
        self,
        signals: _InstallVerifySignals,
        service: Any,
        path: Path,
        sha256: str,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._signals = signals
        self._service = service
        self._path = path
        self._sha256 = sha256

    def run(self) -> None:
        """Execute the verification pipeline and emit exactly one result."""
        try:
            result = _run_verification(
                self._service, self._path, self._sha256
            )
        except BaseException as exc:  # noqa: BLE001 - worker boundary
            result = (
                str(self._path),
                False,
                False,
                False,
                None,
                None,
                f"安装流程异常：{exc}",
            )
        self._signals.finished.emit(result)


def _run_verification(
    service: Any,
    path: Path,
    sha256: str,
) -> tuple[str, bool, bool, bool, Optional[int], Optional[tuple[int, int]], Optional[str]]:
    """Run verify -> shutdown -> recheck and return the fixed seven-tuple.

    The service instance is captured by the caller on the GUI thread; this
    function never resolves the singleton itself (the sidecar is already
    shutting down).

    Args:
        service: Captured ``UpdateService`` instance.
        path: Installer path.
        sha256: Expected digest from the release asset.

    Returns:
        tuple: ``(path, verified, shutdown_ok, recheck_ok, handle, identity,
        error)``.
    """
    verified = False
    shutdown_ok = False
    recheck_ok = False
    handle: Optional[int] = None
    identity: Optional[tuple[int, int]] = None
    rust_identity = (0, 0)
    error: Optional[str] = None

    try:
        try:
            verified, volume_serial, file_index = service.verify_installer(
                path, sha256
            )
            rust_identity = (int(volume_serial), int(file_index))
        except Exception as exc:  # noqa: BLE001 - worker boundary
            error = f"安装包校验失败：{exc}"

        try:
            shutdown_ok = bool(service.shutdown(timeout=4.0))
        except Exception as exc:  # noqa: BLE001 - worker boundary
            shutdown_ok = False
            if error is None:
                error = f"关闭更新组件失败：{exc}"

        if error is None and verified and shutdown_ok:
            try:
                handle, identity, recheck_ok = _python_recheck(
                    path, sha256, rust_identity
                )
            except Exception as exc:  # noqa: BLE001 - worker boundary
                handle = None
                error = f"安装包复核失败：{exc}"
    except BaseException as exc:  # noqa: BLE001 - never leave the dialog stuck
        handle = None
        if error is None:
            error = f"安装流程异常：{exc}"
    finally:
        if error is not None and handle is not None:
            _close_handle(handle)
            handle = None
        if error is None:
            if not verified:
                error = "安装包签名或哈希校验未通过，已取消安装。"
            elif not shutdown_ok:
                error = "更新组件未能关闭，已取消安装。"
            elif not recheck_ok:
                error = "安装包复核失败（哈希或文件标识不一致），已取消安装。"
        result = (
            str(path),
            bool(verified),
            bool(shutdown_ok),
            bool(recheck_ok),
            handle,
            identity,
            error,
        )
    return result


class InstallerLauncher(QObject):
    """Single owner of the install flow for one confirmed installer.

    Construct on the GUI thread with the already-captured ``UpdateService``.
    Call :meth:`start` exactly once.  :attr:`finished` is emitted on the GUI
    thread after the launch decision, with the fixed seven-tuple result.
    """

    finished = Signal(object)

    def __init__(
        self,
        service: Any,
        *,
        pool: Optional[QThreadPool] = None,
    ) -> None:
        """Create the launcher and its private single-worker pool.

        Args:
            service: Captured ``UpdateService`` instance (GUI thread).
            pool: Optional pool override for tests.
        """
        super().__init__()
        self._service = service
        self._task_pool = pool if pool is not None else QThreadPool(self)
        if pool is None:
            self._task_pool.setMaxThreadCount(1)
            self._task_pool.setObjectName("faf-installer-launcher")
        self._signals = _InstallVerifySignals(self)
        self._signals.finished.connect(
            self.handle_result, Qt.ConnectionType.QueuedConnection
        )
        self._tasks: list[_VerifyTask] = []
        self._started = False
        self._result_handled = False
        self._finished_emitted = False
        self._bridge_ensured = False

    def start(self, installer_path: str, sha256: str) -> bool:
        """Submit exactly one verification task.

        Args:
            installer_path: Downloaded installer path.
            sha256: Expected SHA-256 digest.

        Returns:
            bool: ``True`` when a worker was scheduled.
        """
        if self._started:
            return False
        self._started = True
        path_text = str(installer_path or "").strip()
        digest = str(sha256 or "").strip()
        if not path_text or not digest:
            self._signals.finished.emit(
                (
                    path_text,
                    False,
                    False,
                    False,
                    None,
                    None,
                    "安装包校验信息不完整，已取消安装。",
                )
            )
            return False

        task = _VerifyTask(self._signals, self._service, Path(path_text), digest)
        self._tasks.append(task)
        self._task_pool.start(task)
        return True

    def handle_result(self, result: object) -> None:
        """Apply a worker result on the GUI thread and emit ``finished`` once.

        Args:
            result: Fixed seven-tuple produced by ``_run_verification``.
        """
        if self._result_handled:
            return
        self._result_handled = True
        try:
            payload = _normalize_result(result)
            (
                path_text,
                verified,
                shutdown_ok,
                recheck_ok,
                handle,
                identity,
                error,
            ) = payload
            path = Path(path_text) if path_text else None
            try:
                if not verified:
                    _close_handle(handle)
                    handle = None
                    _safe_delete(path)
                    self._ensure_bridge_once()
                    self._notify_failure(
                        error or "安装包校验未通过，已取消安装。"
                    )
                    return
                if not shutdown_ok:
                    _close_handle(handle)
                    handle = None
                    self._ensure_bridge_once()
                    self._notify_failure(
                        error or "更新组件未能关闭，已取消安装。"
                    )
                    return
                if not recheck_ok:
                    _close_handle(handle)
                    handle = None
                    _safe_delete(path)
                    self._ensure_bridge_once()
                    self._notify_failure(
                        error or "安装包复核失败，已取消安装。"
                    )
                    return

                resolved = _launch_path(path_text)
                if resolved is None:
                    _close_handle(handle)
                    handle = None
                    self._ensure_bridge_once()
                    self._notify_failure("安装包路径无效，已取消安装。")
                    return

                try:
                    ret = _shell_execute(resolved)
                    # Capture the thread-local last error before CloseHandle:
                    # CloseHandle itself may overwrite it, which would turn a
                    # real UAC cancel (1223) into a generic failure.
                    last_error = _get_last_error()
                finally:
                    # The handle stays open for the whole ShellExecuteW call
                    # and is closed immediately after it returns.
                    _close_handle(handle)
                    handle = None

                if ret > 32:
                    _quit_app()
                    return

                self._ensure_bridge_once()
                if last_error == ERROR_CANCELLED:
                    self._notify_uac_cancelled(str(resolved))
                else:
                    self._notify_failure(
                        f"无法启动安装程序（错误码 {last_error or ret}），"
                        "请检查管理员权限后重试。"
                    )
            finally:
                if handle is not None:
                    _close_handle(handle)
                    handle = None
        except Exception as exc:  # noqa: BLE001 - GUI boundary
            self._ensure_bridge_once()
            self._notify_failure(f"安装启动失败：{exc}")
        finally:
            self._emit_finished_once(_normalize_result(result))

    def _ensure_bridge_once(self) -> None:
        """Bring the sidecar back exactly once after a failed launch."""
        if self._bridge_ensured:
            return
        self._bridge_ensured = True
        try:
            self._service.ensure_bridge()
        except Exception as exc:  # noqa: BLE001 - notification path
            debug(f"恢复更新组件失败: {exc!r}")

    def _notify_failure(self, message: str) -> None:
        """Show a readable non-modal install failure."""
        try:
            from freeassetfilter.ui.layout import update_dialogs

            update_dialogs.show_install_failure(message)
        except Exception as exc:  # noqa: BLE001 - never block finished
            warning(f"显示安装失败提示失败: {exc!r}")

    def _notify_uac_cancelled(self, path: str) -> None:
        """Show the UAC-cancelled notice without retrying or launching."""
        try:
            from freeassetfilter.ui.layout import update_dialogs

            update_dialogs.show_uac_cancelled(path)
        except Exception as exc:  # noqa: BLE001 - never block finished
            warning(f"显示 UAC 取消提示失败: {exc!r}")

    def _emit_finished_once(self, result: object) -> None:
        """Emit the public ``finished`` signal at most once."""
        if self._finished_emitted:
            return
        self._finished_emitted = True
        self.finished.emit(result)


def _normalize_result(
    result: object,
) -> tuple[str, bool, bool, bool, Optional[int], Optional[tuple[int, int]], Optional[str]]:
    """Coerce an arbitrary worker payload into the fixed seven-tuple."""
    if isinstance(result, tuple) and len(result) == 7:
        return result  # type: ignore[return-value]
    return (
        "",
        False,
        False,
        False,
        None,
        None,
        "安装流程内部错误，已取消安装。",
    )
