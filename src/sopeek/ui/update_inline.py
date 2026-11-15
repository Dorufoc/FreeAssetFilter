"""设置页「检查更新」页的内联更新检查/下载编排。

检查更新页不再打开更新中心弹窗，而是通过本模块的进程级 session 直接订阅
``UpdateService``：检查中、检查结果与自动下载进度都通过信号交给设置页
内联展示。

设计边界：

* session 不持有任何 QWidget，设置窗口关闭后仍可继续下载并登记待安装更新；
* 只认领 ``manual=True`` 且 request id 匹配的检查结果；
* 正式版更新保持自动下载；GitHub 预发布版（测试版）只进入等待确认状态，
  由设置页展示版本与更新说明后，用户选择「下载更新」或「跳过此版本」；
* 下载完成后只写 ``pending_update.json``，实际安装由下次启动的引导层完成；
* 保持 :class:`sopeek.ui.update_entry.UpdateEntryController` 的单弹窗契约
  不变；本模块不改变其行为。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from sopeek.services.update_pending import write_pending_update
from sopeek.services.update_service import UpdateError
from sopeek.utils.app_logger import warning

#: 检查中状态的最短展示时长（毫秒），避免检查瞬间完成时闪一下。
MIN_CHECKING_VISIBLE_MS = 250

STATE_IDLE = "idle"
STATE_CHECKING = "checking"
STATE_UP_TO_DATE = "up_to_date"
STATE_CHECK_FAILED = "check_failed"
STATE_UPDATE_AVAILABLE = "update_available"
STATE_UPDATE_SKIPPED = "update_skipped"
STATE_DOWNLOADING = "downloading"
STATE_DOWNLOADED = "downloaded"
STATE_DOWNLOAD_FAILED = "download_failed"


def _is_prerelease_update(info: object) -> bool:
    """判断更新结果是否为 GitHub 预发布版（测试版）。

    优先读取原生更新器返回的 ``remote.prerelease``；缺失时回退按版本号
    中的连字符（如 ``1.0.0-alpha.5`` / ``2.0.0.nightly-20261114``）判断。
    """
    remote = getattr(info, "remote", None)
    if not isinstance(remote, dict):
        remote = {}
    if bool(remote.get("prerelease")):
        return True
    version = str(remote.get("version") or remote.get("tag") or "").strip()
    return "-" in version


def _positive_int(value: Any) -> int:
    """把任意值安全转为正整数；非法/非正数返回 0。"""
    if isinstance(value, bool):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return number if number > 0 else 0


class InlineUpdateSession(QObject):
    """进程级内联更新会话。

    必须在 GUI 主线程构造。首次 :meth:`start_check` 时才惰性创建
    ``UpdateService``，因此仅打开设置页不会触碰更新组件。
    """

    checking = Signal()
    up_to_date = Signal(object)
    check_failed = Signal(object)
    update_available = Signal(object)
    update_skipped = Signal(object)
    download_started = Signal(object)
    download_progress = Signal(int, int)
    downloaded = Signal(object, str)
    download_failed = Signal(object, object)

    MIN_CHECKING_VISIBLE_MS = MIN_CHECKING_VISIBLE_MS

    def __init__(
        self,
        service_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        """初始化会话。

        Args:
            service_factory: 可注入的更新服务工厂（测试用）；省略时使用
                :func:`sopeek.services.update_service.get_update_service`。
        """
        super().__init__()
        self._service_factory = service_factory
        self._service: Any = None
        self._subscribed = False
        self._disposed = False

        self._state = STATE_IDLE
        self._info: Any = None
        self._error: Any = None
        self._installer_path = ""
        self._downloaded = 0
        self._total = 0

        self._request_id: Optional[str] = None
        self._pending_claim = False
        self._checking_shown_at = 0.0
        self._download_id: Optional[str] = None

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------

    @property
    def disposed(self) -> bool:
        """会话是否已销毁。"""
        return self._disposed

    def start_check(self, include_prerelease: bool = False) -> None:
        """发起或加入一次手动检查；检查/下载在途时忽略重复调用。

        Args:
            include_prerelease: 是否把 GitHub 预发布版纳入检查。默认 ``False``，
                设置页「检查更新」页按「获取测试版」开关传入。
        """
        if self._disposed or self._state == STATE_CHECKING:
            return
        if self._state == STATE_UPDATE_AVAILABLE:
            return
        if self._download_id is not None:
            return

        self._info = None
        self._error = None
        self._installer_path = ""
        self._downloaded = 0
        self._total = 0
        self._state = STATE_CHECKING
        self._checking_shown_at = time.monotonic()
        self._pending_claim = True
        self.checking.emit()

        service = self._ensure_service()
        if service is None or not self._subscribe():
            self._schedule_check_error(UpdateError("unavailable"))
            return

        try:
            available = bool(service.is_available())
        except Exception:  # noqa: BLE001 - 探测失败按不可用处理
            available = False
        if not available:
            self._schedule_check_error(UpdateError("unavailable"))
            return

        try:
            request_id = service.check(
                manual=True, include_prerelease=bool(include_prerelease)
            )
        except Exception:  # noqa: BLE001 - 派发失败给出可重试错误
            self._schedule_check_error(UpdateError("internal"))
            return
        if not isinstance(request_id, str) or not request_id:
            self._schedule_check_error(UpdateError("internal"))
            return
        # 启动检查在途时 service 不会补发 check_started，用返回值补齐 id。
        if self._pending_claim and self._request_id is None:
            self._request_id = request_id

    def snapshot(self) -> dict[str, Any]:
        """返回当前状态快照（供设置页重新打开时恢复展示）。"""
        return {
            "state": self._state,
            "info": self._info,
            "error": self._error,
            "downloaded": self._downloaded,
            "total": self._total,
            "installer_path": self._installer_path,
        }

    def start_pending_download(self) -> bool:
        """下载当前等待确认的测试版更新。

        Returns:
            bool: 存在等待确认的更新并已派发下载返回 ``True``；否则 ``False``。
        """
        if self._disposed or self._state != STATE_UPDATE_AVAILABLE:
            return False
        info = self._info
        if info is None or self._download_id is not None:
            return False
        self._state = STATE_DOWNLOADING
        self._error = None
        self._downloaded = 0
        self._total = 0
        self._installer_path = ""
        self._start_download(info)
        return True

    def skip_pending_update(self) -> bool:
        """跳过当前等待确认的测试版更新，不下载、不安装。

        Returns:
            bool: 存在等待确认的更新并已跳过返回 ``True``；否则 ``False``。
        """
        if self._disposed or self._state != STATE_UPDATE_AVAILABLE:
            return False
        info = self._info
        self._state = STATE_UPDATE_SKIPPED
        self._error = None
        self._downloaded = 0
        self._total = 0
        self._installer_path = ""
        self.update_skipped.emit(info)
        return True

    def dispose(self) -> None:
        """断开服务订阅并标记会话不可用（幂等）。"""
        if self._disposed:
            return
        self._disposed = True
        self._disconnect_service()
        self._request_id = None
        self._pending_claim = False
        self._download_id = None

    # ------------------------------------------------------------------
    # 服务关联
    # ------------------------------------------------------------------

    def _ensure_service(self) -> Any:
        """惰性取得更新服务；失败时返回 ``None`` 并在下次调用重试。"""
        if self._service is not None:
            return self._service
        try:
            if self._service_factory is not None:
                self._service = self._service_factory()
            else:
                from sopeek.services.update_service import get_update_service

                self._service = get_update_service()
        except Exception as exc:  # noqa: BLE001 - 服务不可用降级为错误结果
            warning(f"创建更新服务失败：{exc!r}")
            self._service = None
        return self._service

    def _subscribe(self) -> bool:
        """连接更新服务信号（幂等）。"""
        if self._subscribed:
            return True
        service = self._service
        if service is None:
            return False
        try:
            connections = (
                ("check_started", self._on_check_started),
                ("check_finished", self._on_check_finished),
                ("download_progress", self._on_download_progress),
                ("download_state_changed", self._on_download_state_changed),
                ("download_finished", self._on_download_finished),
                ("download_failed", self._on_download_failed),
            )
            for signal_name, slot in connections:
                signal = getattr(service, signal_name, None)
                if signal is None:
                    continue
                signal.connect(slot)
        except (AttributeError, RuntimeError, TypeError) as exc:
            warning(f"订阅更新服务信号失败：{exc!r}")
            return False
        self._subscribed = True
        return True

    def _disconnect_service(self) -> None:
        """断开全部服务信号（幂等）。"""
        service = self._service
        if service is None or not self._subscribed:
            self._subscribed = False
            return
        for signal_name, slot in (
            ("check_started", self._on_check_started),
            ("check_finished", self._on_check_finished),
            ("download_progress", self._on_download_progress),
            ("download_state_changed", self._on_download_state_changed),
            ("download_finished", self._on_download_finished),
            ("download_failed", self._on_download_failed),
        ):
            signal = getattr(service, signal_name, None)
            if signal is None:
                continue
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                continue
        self._subscribed = False

    # ------------------------------------------------------------------
    # 检查
    # ------------------------------------------------------------------

    def _on_check_started(self, request_id: str, manual: bool) -> None:
        """认领本会话发起的手动检查请求 id。"""
        if self._disposed or not manual or not self._pending_claim:
            return
        self._request_id = request_id

    def _on_check_finished(
        self,
        request_id: str,
        manual: bool,
        info: object,
        error: object,
    ) -> None:
        """按请求 id 过滤并应用检查结果。"""
        if self._disposed or not manual:
            return
        if self._request_id is None or request_id != self._request_id:
            return
        self._request_id = None
        self._pending_claim = False

        delay_ms = self._remaining_checking_ms()
        if delay_ms > 0:
            QTimer.singleShot(
                delay_ms,
                lambda: self._apply_check_result(info, error),
            )
        else:
            self._apply_check_result(info, error)

    def _schedule_check_error(self, error: object) -> None:
        """在最短检查展示时长后应用一个无请求 id 的检查错误。"""
        self._pending_claim = False
        self._request_id = None
        delay_ms = self._remaining_checking_ms()
        if delay_ms > 0:
            QTimer.singleShot(
                delay_ms,
                lambda: self._apply_check_result(None, error),
            )
        else:
            self._apply_check_result(None, error)

    def _remaining_checking_ms(self) -> int:
        """返回检查中状态还需保持的最小展示时长（毫秒）。"""
        if self._checking_shown_at <= 0.0:
            return 0
        elapsed_ms = (time.monotonic() - self._checking_shown_at) * 1000.0
        return max(0, int(self.MIN_CHECKING_VISIBLE_MS - elapsed_ms))

    def _apply_check_result(self, info: object, error: object) -> None:
        """应用检查结果，并在有更新时自动开始下载。"""
        if self._disposed or self._state != STATE_CHECKING:
            return
        self._checking_shown_at = 0.0

        if error is None and info is None:
            error = UpdateError("internal")
        if error is not None:
            self._state = STATE_CHECK_FAILED
            self._error = error
            self._info = None
            self.check_failed.emit(error)
            return

        if bool(getattr(info, "update_available", False)):
            self._info = info
            self._error = None
            self._downloaded = 0
            self._total = 0
            self._installer_path = ""
            if _is_prerelease_update(info):
                # 测试版不自动下载：交由设置页展示版本/说明并让用户确认。
                self._state = STATE_UPDATE_AVAILABLE
                self.update_available.emit(info)
            else:
                self._state = STATE_DOWNLOADING
                self._start_download(info)
            return

        self._state = STATE_UP_TO_DATE
        self._info = info
        self._error = None
        self.up_to_date.emit(info)

    # ------------------------------------------------------------------
    # 下载
    # ------------------------------------------------------------------

    @staticmethod
    def _installer_asset_usable(info: object) -> bool:
        """判断更新快照是否带可下载的安装包。"""
        asset = getattr(info, "asset", None)
        if not isinstance(asset, dict):
            return False
        name = asset.get("name")
        sha256 = asset.get("sha256")
        size = asset.get("size")
        return (
            isinstance(name, str)
            and bool(name.strip())
            and isinstance(sha256, str)
            and len(sha256.strip()) == 64
            and _positive_int(size) > 0
        )

    def _start_download(self, info: object) -> None:
        """自动开始下载；缺少安装包时给出明确失败原因。"""
        if not self._installer_asset_usable(info):
            self._fail_download(
                info,
                UpdateError(
                    "no_installer_asset", "该版本没有可用的安装包"
                ),
            )
            return

        asset = getattr(info, "asset", None)
        self._downloaded = 0
        self._total = _positive_int(
            asset.get("size") if isinstance(asset, dict) else 0
        )

        service = self._service
        if service is None:
            self._fail_download(info, UpdateError("unavailable"))
            return
        try:
            request_id = service.start_download(info)
        except Exception:  # noqa: BLE001 - 下载入口失败给出可读错误
            self._fail_download(info, UpdateError("internal"))
            return
        if not isinstance(request_id, str) or not request_id:
            self._fail_download(info, UpdateError("internal"))
            return

        self._download_id = request_id
        self.download_started.emit(info)
        try:
            snapshot = service.get_download_state(request_id)
        except Exception:  # noqa: BLE001 - 初始快照失败不阻断进度信号
            snapshot = None
        if isinstance(snapshot, tuple) and len(snapshot) == 3:
            _state, downloaded, total = snapshot
            downloaded_value = _positive_int(downloaded)
            total_value = _positive_int(total)
            if total_value > 0:
                self._total = total_value
            if downloaded_value > 0:
                self._downloaded = downloaded_value
        self.download_progress.emit(self._downloaded, self._total)

    def _on_download_progress(
        self,
        request_id: str,
        downloaded: object,
        total: object,
        _speed: float,
    ) -> None:
        """刷新当前下载进度。"""
        if self._disposed or request_id != self._download_id:
            return
        self._downloaded = _positive_int(downloaded)
        total_value = _positive_int(total)
        if total_value > 0:
            self._total = total_value
        self.download_progress.emit(self._downloaded, self._total)

    def _on_download_state_changed(
        self, request_id: str, state: str
    ) -> None:
        """校验阶段视为 100%，避免百分比停在 99%。"""
        if self._disposed or request_id != self._download_id:
            return
        if state == "verifying" and self._total > 0:
            self._downloaded = self._total
            self.download_progress.emit(self._downloaded, self._total)

    def _on_download_finished(
        self, request_id: str, installer_path: str
    ) -> None:
        """下载完成：登记待安装更新，不立即安装。"""
        if self._disposed or request_id != self._download_id:
            return
        self._download_id = None
        info = self._info
        path_text = str(installer_path or "").strip()
        if info is None or not path_text:
            self._fail_download(info, UpdateError("internal"))
            return
        try:
            marker_ok = bool(write_pending_update(info, path_text))
        except Exception as exc:  # noqa: BLE001 - 标记失败按下载失败处理
            warning(f"登记待安装更新失败：{exc!r}")
            marker_ok = False
        if not marker_ok:
            self._fail_download(
                info,
                UpdateError(
                    "io", "无法登记下次启动安装，请重试。"
                ),
            )
            return

        self._state = STATE_DOWNLOADED
        self._installer_path = path_text
        self._error = None
        self.downloaded.emit(info, path_text)

    def _on_download_failed(
        self, request_id: str, error: object
    ) -> None:
        """下载失败：保留可读原因并结束当前下载。"""
        if self._disposed or request_id != self._download_id:
            return
        self._download_id = None
        self._fail_download(self._info, error)

    def _fail_download(self, info: object, error: object) -> None:
        """统一切换到下载失败状态。"""
        self._state = STATE_DOWNLOAD_FAILED
        self._error = error if error is not None else UpdateError("internal")
        self._download_id = None
        self.download_failed.emit(info, self._error)


# ----------------------------------------------------------------------
# 单例
# ----------------------------------------------------------------------

_session: Optional[InlineUpdateSession] = None
_session_lock = threading.Lock()


def get_inline_update_session(
    service_factory: Optional[Callable[[], Any]] = None,
) -> InlineUpdateSession:
    """返回进程级内联更新会话；已销毁时重新创建。"""
    global _session
    with _session_lock:
        if _session is None or _session.disposed:
            _session = InlineUpdateSession(service_factory=service_factory)
        return _session


def get_inline_update_session_if_exists() -> Optional[InlineUpdateSession]:
    """返回已存在的内联更新会话；从未创建或已销毁时返回 ``None``。"""
    with _session_lock:
        session = _session
    if session is None or session.disposed:
        return None
    return session


def reset_inline_update_session() -> None:
    """销毁并清空内联更新会话（测试与退出清理使用，幂等）。"""
    global _session
    with _session_lock:
        session = _session
        _session = None
    if session is not None:
        session.dispose()


__all__ = [
    "InlineUpdateSession",
    "MIN_CHECKING_VISIBLE_MS",
    "STATE_CHECKING",
    "STATE_CHECK_FAILED",
    "STATE_DOWNLOADED",
    "STATE_DOWNLOADING",
    "STATE_DOWNLOAD_FAILED",
    "STATE_IDLE",
    "STATE_UPDATE_AVAILABLE",
    "STATE_UPDATE_SKIPPED",
    "STATE_UP_TO_DATE",
    "get_inline_update_session",
    "get_inline_update_session_if_exists",
    "reset_inline_update_session",
]
