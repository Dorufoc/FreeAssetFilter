"""应用更新检查与下载服务。

本模块封装 ``faf_updater`` 原生桥，负责：

* 更新检查（手动/启动共用一次在途请求）；
* 单飞下载、暂停/恢复/取消与缓存校验；
* Rust 错误码到用户可读文案的稳定映射；
* 在独立的有界 :class:`QThreadPool` 中执行阻塞操作。

所有跨线程状态只由 ``_dispatch_lock`` 保护；GUI 线程只做参数校验和信号
发射，``ensure_started`` / ``download_begin`` / ``download_wait`` 等阻塞调用
一律不持有该锁。
"""

from __future__ import annotations

import itertools
import shutil
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    QRunnable,
    QThread,
    QThreadPool,
    QTimer,
    Signal,
)

from freeassetfilter.core.native.bridges.faf_updater_bridge import (
    FafUpdaterBridge,
    UpdaterBridgeError,
)
from freeassetfilter.services import update_startup
from freeassetfilter.utils.app_logger import debug, warning
from freeassetfilter.utils.path_utils import get_app_data_path
from freeassetfilter.utils.version_info import (
    get_local_build_date,
    get_local_version,
)

_REPO = "Dorufoc/FreeAssetFilter"
_DISK_RESERVE = 64 * 1024 * 1024
_ARTIFACT_RETRIES = 5
_ARTIFACT_RETRY_DELAY = 0.05

ERROR_MESSAGES: dict[str, str] = {
    "bad_command": "更新器收到无法识别的命令。",
    "bad_params": "更新参数无效，请稍后重试。",
    "bad_range": "下载范围无效。",
    "busy": "已有下载任务正在进行，请稍后再试。",
    "checksum_mismatch": "安装包校验失败，请重新下载。",
    "checksum_missing": "发布信息缺少安装包校验值，无法安全下载。",
    "cancelled": "下载已取消。",
    "http_status": "更新服务器返回异常状态，请稍后重试。",
    "io": "写入安装包失败，请检查磁盘空间或权限。",
    "invalid_json": "更新器返回了无法解析的数据。",
    "invalid_version": "版本号格式无效。",
    "network": "网络连接失败，请检查网络后重试。",
    "no_installer_asset": "该版本没有可用的安装包。",
    "no_release": "没有找到可用的发布版本。",
    "rate_limited": "请求过于频繁，请稍后重试。",
    "size_mismatch": "安装包大小与发布信息不一致，已删除。",
    "timeout": "更新操作超时，请稍后重试。",
    "unsafe_url": "下载地址不安全，已拒绝。",
    "internal": "更新器内部错误，请稍后重试。",
    "process_exited": "更新进程意外退出，请重试。",
    "unavailable": "更新组件不可用，请重新安装应用。",
}

RETRYABLE_CODES = frozenset({"network", "http_status", "rate_limited", "timeout", "busy"})

#: 兼容内部测试/调用方的旧命名。
_ERROR_MESSAGES = ERROR_MESSAGES


@dataclass(frozen=True)
class UpdateInfo:
    """一次更新检查的稳定结果快照。"""

    local_version: str
    local_date: Optional[str]
    update_available: bool
    reason: str
    skipped_newer_tag: Optional[str]
    remote: dict[str, Any]
    asset: Optional[dict[str, Any]]


@dataclass(frozen=True)
class UpdateError:
    """可跨信号传递的更新错误。"""

    code: str
    message: str = ""
    retryable: Optional[bool] = None
    abort: bool = False

    def __post_init__(self) -> None:
        """补齐默认文案与可重试语义。"""
        if not self.message:
            object.__setattr__(
                self,
                "message",
                ERROR_MESSAGES.get(self.code, ERROR_MESSAGES["internal"]),
            )
        if self.retryable is None:
            object.__setattr__(self, "retryable", self.code in RETRYABLE_CODES)


def _coerce_int(value: Any) -> int:
    """将任意值安全转为非负整数。"""
    if isinstance(value, bool):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, number)


def _coerce_size(value: Any) -> int:
    """将发布信息中的大小限制到 Rust 接受的范围。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value if value >= 0 else 0


def _coerce_bool(value: Any, default: bool = False) -> bool:
    """将任意值转为布尔值。"""
    if value is None:
        return default
    return bool(value)


def sanitize_asset_name(raw: Any) -> Optional[str]:
    """按 Rust ``sanitize_asset_name`` 规则清洗发布资产名。

    仅保留 basename，移除 Windows 非法字符与控制字符，补齐 ``.exe``，
    拒绝保留设备名与空文件名，并把 stem 截断到 116 个字符。

    Args:
        raw: 发布资产中的原始文件名。

    Returns:
        Optional[str]: 安全文件名；无效时返回 ``None``。
    """
    if not isinstance(raw, str):
        return None
    basename = raw.replace("\\", "/").rsplit("/", 1)[-1]
    illegal = set('<>:"/\\|?*')
    cleaned = "".join(
        character
        for character in basename
        if character not in illegal and unicodedata.category(character) != "Cc"
    )
    cleaned = cleaned.rstrip(" .")
    if not cleaned:
        return None

    lower = cleaned.lower()
    if lower.endswith(".exe"):
        stem_raw, suffix = cleaned[:-4], cleaned[-4:]
    else:
        stem_raw, suffix = cleaned, ".exe"
    stem = stem_raw.rstrip(" .")
    if not stem:
        return None
    if _is_reserved_windows_name(stem):
        return None
    return stem[:116] + suffix


def _is_reserved_windows_name(stem: str) -> bool:
    """判断 stem 是否命中 Windows 保留设备名。"""
    first = stem.split(".", 1)[0].rstrip(" .")
    upper = first.upper()
    if upper in {"CON", "PRN", "AUX", "NUL"}:
        return True
    return (
        len(upper) == 4
        and (upper.startswith("COM") or upper.startswith("LPT"))
        and upper[3] in "123456789"
    )


class _PoolTask(QRunnable):
    """在私有线程池中执行一个可调用对象。"""

    def __init__(self, action: Callable[[], None], on_error: Callable[[BaseException], None]) -> None:
        super().__init__()
        self._action = action
        self._on_error = on_error
        self.setAutoDelete(True)

    def run(self) -> None:
        """执行任务并在未捕获异常时记录日志。"""
        try:
            self._action()
        except Exception as exc:  # noqa: BLE001 - 线程池边界必须兜底
            try:
                self._on_error(exc)
            except Exception:  # noqa: BLE001
                warning(f"UpdateService 线程池任务异常: {exc!r}")


class UpdateService(QObject):
    """应用更新检查/下载服务（主线程单例）。"""

    check_started = Signal(str, bool)
    check_finished = Signal(str, bool, object, object)
    download_started = Signal(str)
    download_progress = Signal(str, object, object, float)
    download_state_changed = Signal(str, str)
    download_pause_acked = Signal(str, bool)
    download_finished = Signal(str, str)
    download_failed = Signal(str, object)
    startup_update_available = Signal(object)

    _instance: Optional["UpdateService"] = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls, *args: Any, **kwargs: Any) -> "UpdateService":
        """返回唯一实例。"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(
        self,
        bridge_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        """初始化单例；必须在 GUI 主线程调用。"""
        app = QCoreApplication.instance()
        if app is None or QThread.currentThread() is not app.thread():
            with type(self)._lock:
                if type(self)._instance is self:
                    type(self)._instance = None
            raise RuntimeError("UpdateService 必须在 GUI 主线程创建")

        with type(self)._lock:
            if type(self)._initialized:
                return
            QObject.__init__(self)
            self._bridge: Any = bridge_factory() if bridge_factory is not None else FafUpdaterBridge()
            self._dispatch_lock = threading.Lock()
            self._download_pool = QThreadPool(self)
            self._task_pool = QThreadPool(self)
            self._control_pool = QThreadPool(self)
            self._download_pool.setMaxThreadCount(1)
            self._task_pool.setMaxThreadCount(2)
            self._control_pool.setMaxThreadCount(2)
            for pool in (self._download_pool, self._task_pool, self._control_pool):
                pool.setObjectName("faf-update-pool")

            self._check_counter = itertools.count(1)
            self._download_counter = itertools.count(1)
            self._check_request_id: Optional[str] = None
            self._check_manual: set[bool] = set()
            self.check_finished.connect(self._on_check_finished)

            self._download_request_id: Optional[str] = None
            self._download_state: dict[str, str] = {}
            self._download_infos: dict[str, UpdateInfo] = {}
            self._download_progress: dict[str, tuple[int, int]] = {}
            self._dispatched: dict[str, threading.Event] = {}
            self._dispatching: dict[str, bool] = {}
            self._before_dispatch: dict[str, bool] = {}
            self._cancel_events: dict[str, threading.Event] = {}
            self._dispatch_epoch: dict[str, int] = {}
            self._pause_pending: set[tuple[str, int]] = set()
            self._pause_ack_sent: dict[tuple[str, int], bool] = {}

            type(self)._initialized = True
            debug("UpdateService 已初始化")

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------
    def check(self, manual: bool = False) -> str:
        """发起或加入一次更新检查。

        Args:
            manual: ``True`` 表示用户手动检查，失败会通过 ``check_finished``
                报告；``False`` 表示启动检查，失败只写日志。

        Returns:
            str: 请求 id；同一在途检查返回同一 id。
        """
        with self._dispatch_lock:
            active = self._check_request_id
            if active is not None:
                if manual:
                    self._check_manual.add(True)
                else:
                    self._check_manual.add(False)
                return active
            request_id = f"check-{next(self._check_counter)}"
            self._check_request_id = request_id
            self._check_manual = {bool(manual)}

        self.check_started.emit(request_id, bool(manual))
        self._task_pool.start(
            _PoolTask(
                lambda: self._execute_check(request_id),
                lambda exc: self._check_crashed(request_id, exc),
            )
        )
        return request_id

    def start_download(self, info: UpdateInfo) -> str:
        """启动下载；同一资产在途时复用，不同资产则返回 busy 错误 id。"""
        expected_size = _coerce_size((info.asset or {}).get("size"))
        with self._dispatch_lock:
            active = self._download_request_id
            if active is not None:
                state = self._download_state.get(active, "")
                same = self._same_asset(active, info)
                if state in {"running", "verifying"}:
                    if same:
                        return active
                    reject_id = f"download-{next(self._download_counter)}"
                    self._schedule_busy(reject_id)
                    return reject_id
                if state == "paused":
                    if same:
                        self._download_infos[active] = info
                        return active
                    evicted = active
                    old_info = self._download_infos.get(active)
                    self._clear_request_locked(active)
                else:
                    evicted = None
                    old_info = None
            else:
                evicted = None
                old_info = None

            request_id = f"download-{next(self._download_counter)}"
            self._download_request_id = request_id
            self._download_state[request_id] = "running"
            self._download_infos[request_id] = info
            self._download_progress[request_id] = (0, expected_size)
            self._cancel_events[request_id] = threading.Event()
            self._dispatched[request_id] = threading.Event()
            self._dispatching[request_id] = False
            self._dispatch_epoch[request_id] = 0

        if evicted is not None:
            self._evict_paused(evicted, old_info)

        failure_code = self._validate_download(info, expected_size)
        if failure_code is not None:
            with self._dispatch_lock:
                self._clear_request_locked(request_id)
            self._emit_async(
                self.download_failed,
                request_id,
                UpdateError(failure_code),
            )
            return request_id

        try:
            download_dir = Path(get_app_data_path()) / "download"
            dest = download_dir / str(sanitize_asset_name((info.asset or {}).get("name")))
        except (OSError, TypeError):
            with self._dispatch_lock:
                self._clear_request_locked(request_id)
            self._emit_async(self.download_failed, request_id, UpdateError("io"))
            return request_id

        self._emit_async(self.download_started, request_id)
        if dest.exists():
            with self._dispatch_lock:
                if self._download_request_id != request_id:
                    return request_id
                self._download_state[request_id] = "verifying"
            self._emit_async(self.download_state_changed, request_id, "verifying")
            self._task_pool.start(
                _PoolTask(
                    lambda: self._verify_cached(request_id, dest),
                    lambda exc: self._fail_request(request_id, self._error_from_exception(exc)),
                )
            )
        else:
            self._download_pool.start(
                _PoolTask(
                    lambda: self._run_download(request_id, self._epoch(request_id)),
                    lambda exc: self._fail_request(request_id, self._error_from_exception(exc)),
                )
            )
        return request_id

    def resume_download(self, request_id: str) -> bool:
        """恢复已暂停或尚未 dispatch 的下载。"""
        with self._dispatch_lock:
            if self._download_request_id != request_id:
                return False
            state = self._download_state.get(request_id)
            if state != "paused" and not self._before_dispatch.get(request_id):
                return False
            if self._dispatching.get(request_id, False):
                self._before_dispatch.pop(request_id, None)
                self._download_state[request_id] = "running"
                self._pop_pause_keys_locked(request_id)
                return True

            self._before_dispatch.pop(request_id, None)
            self._download_state[request_id] = "running"
            epoch = self._dispatch_epoch.get(request_id, 0) + 1
            self._dispatch_epoch[request_id] = epoch
            cancel_event = self._cancel_events.get(request_id)
            if cancel_event is None:
                self._cancel_events[request_id] = threading.Event()
            else:
                cancel_event.clear()
            self._dispatched[request_id] = threading.Event()
            self._dispatching[request_id] = False
            self._pop_pause_keys_locked(request_id)

        self._download_pool.start(
            _PoolTask(
                lambda: self._run_download(request_id, epoch),
                lambda exc: self._fail_request(request_id, self._error_from_exception(exc)),
            )
        )
        return True

    def pause_download(self, request_id: str) -> bool:
        """请求暂停；仅立即校验 id，实际 ack 走控制池。"""
        with self._dispatch_lock:
            if self._download_request_id != request_id:
                return False
            state = self._download_state.get(request_id, "")
            epoch = self._dispatch_epoch.get(request_id, 0)
            self._pause_ack_sent.pop((request_id, epoch), None)
            self._pause_pending.add((request_id, epoch))
            worker_owns_pause = False
            if state == "paused":
                self._mark_pause_ack_locked(request_id, True)
                accepted = True
            elif state != "verifying" and not self._dispatched.get(
                request_id, threading.Event()
            ).is_set():
                # begin 尚未返回：worker 在 ensure/begin 之后消费该意图。
                self._before_dispatch[request_id] = True
                worker_owns_pause = self._dispatching.get(request_id, False)

        if state == "paused":
            if accepted:
                self.download_pause_acked.emit(request_id, True)
            return True
        if worker_owns_pause:
            return True

        self._control_pool.start(
            _PoolTask(
                lambda: self._pause_control(request_id, epoch),
                lambda exc: warning(f"UpdateService pause 任务异常: {exc!r}"),
            )
        )
        return True

    def cancel_download(self, request_id: str) -> None:
        """请求取消下载；先同步置位 Event，再由控制池通知原生端。"""
        with self._dispatch_lock:
            if self._download_request_id != request_id:
                warning(f"UpdateService 忽略未知下载取消: {request_id}")
                return
            event = self._cancel_events.get(request_id)
            if event is None:
                warning(f"UpdateService 取消时缺少 Event: {request_id}")
                return
            event.set()
            state = self._download_state.get(request_id, "")

        self._control_pool.start(
            _PoolTask(
                lambda: self._cancel_control(request_id, state),
                lambda exc: warning(f"UpdateService cancel 任务异常: {exc!r}"),
            )
        )

    def get_download_state(self, request_id: str) -> Optional[tuple[str, int, int]]:
        """返回下载状态 ``(state, downloaded, total)``，未知 id 返回 ``None``。"""
        with self._dispatch_lock:
            if self._download_request_id != request_id:
                return None
            state = self._download_state.get(request_id)
            if state is None:
                return None
            downloaded, total = self._download_progress.get(request_id, (0, 0))
            if self._before_dispatch.get(request_id, False):
                return ("paused", downloaded, total)
            return (state, downloaded, total)

    def verify_installer(self, path: Path, sha256: str) -> tuple[bool, int, int]:
        """调用原生 verify 校验安装包签名/卷序列号。"""
        self._bridge.ensure_started()
        response = self._bridge.verify({"path": str(path), "sha256": sha256})
        if not isinstance(response, dict) or not response.get("ok", False):
            raise self._error_from_response(response)
        result = response.get("result") or {}
        if not isinstance(result, dict):
            result = {}
        return (
            bool(result.get("match", False)),
            _coerce_int(result.get("volume_serial")),
            _coerce_int(result.get("file_index")),
        )

    def ensure_bridge(self) -> bool:
        """确保原生 updater 已启动（供 UAC 取消后的重试）。"""
        return bool(self._bridge.ensure_started())

    def is_available(self) -> bool:
        """每次重新探测 updater 可执行文件；不启动子进程。"""
        probe = getattr(self._bridge, "is_available", None)
        if callable(probe):
            return bool(probe())
        command = getattr(self._bridge, "command", None)
        if isinstance(command, (list, tuple)) and command:
            return len(command) > 1 or Path(str(command[0])).is_file()
        return False

    def maybe_startup_check(self, window: Any = None) -> Optional[str]:
        """按启动策略发起一次非阻塞更新检查。

        顺序固定为：可用性探测 -> 策略判断 -> 写入尝试时间 -> 派发检查。
        服务不可用或未到期时直接返回，且不触碰 ``check_state.json``。

        Args:
            window: 预留的主窗口引用，服务本身不使用。

        Returns:
            Optional[str]: 已派发的请求 id；跳过时返回 ``None``。
        """
        if not self.is_available():
            debug("更新器不可用，跳过启动检查")
            return None
        if not update_startup.should_check_on_startup():
            return None
        update_startup.record_check_attempt()
        return self.check(False)

    def shutdown(self, timeout: float = 4.0) -> bool:
        """停止原生 updater 子进程。"""
        return bool(self._bridge.stop(timeout))

    def close(self) -> None:
        """关闭原生桥并等待私有线程池中的任务结束。"""
        try:
            self._bridge.close()
        finally:
            for pool in (self._download_pool, self._task_pool, self._control_pool):
                pool.waitForDone(2000)

    @classmethod
    def get_update_service(
        cls,
        bridge_factory: Optional[Callable[[], Any]] = None,
    ) -> "UpdateService":
        """获取单例；不存在时创建。"""
        with cls._lock:
            existing = cls._instance
        if existing is not None:
            return existing
        return cls(bridge_factory=bridge_factory)

    @classmethod
    def get_update_service_if_exists(cls) -> Optional["UpdateService"]:
        """返回已存在的单例，不会构造新实例。"""
        with cls._lock:
            return cls._instance

    # ------------------------------------------------------------------
    # 检查
    # ------------------------------------------------------------------
    def _execute_check(self, request_id: str) -> None:
        """在任务池执行原生检查并分发结果。"""
        try:
            self._bridge.ensure_started()
            params = {
                "repo": _REPO,
                "current_version": get_local_version(),
                "current_date": get_local_build_date(),
                "include_prerelease": True,
            }
            response = self._bridge.check(params, request_id=request_id)
        except UpdaterBridgeError as exc:
            self._finish_check(request_id, None, self._error_from_exception(exc))
            return
        except Exception as exc:  # noqa: BLE001 - 线程边界
            warning(f"UpdateService check 异常: {exc!r}")
            self._finish_check(request_id, None, UpdateError("internal"))
            return

        if not isinstance(response, dict) or not response.get("ok", False):
            self._finish_check(request_id, None, self._error_from_response(response))
            return
        result = response.get("result") or {}
        if not isinstance(result, dict):
            result = {}
        self._finish_check(request_id, self._info_from_result(result), None)

    def _finish_check(
        self,
        request_id: str,
        info: Optional[UpdateInfo],
        error: Optional[UpdateError],
    ) -> None:
        """结束检查并按手动/启动订阅者分发信号。"""
        with self._dispatch_lock:
            if self._check_request_id != request_id:
                return
            manuals = set(self._check_manual)
            self._check_request_id = None
            self._check_manual = set()

        if error is not None:
            if True in manuals:
                self.check_finished.emit(request_id, True, None, error)
            else:
                warning(f"启动更新检查失败: {error.code}: {error.message}")
            return

        if info is not None and False in manuals:
            self.check_finished.emit(request_id, False, info, None)
        if info is not None and True in manuals:
            self.check_finished.emit(request_id, True, info, None)

    def _on_check_finished(
        self,
        request_id: str,
        manual: bool,
        info: Optional[UpdateInfo],
        error: Optional[UpdateError],
    ) -> None:
        """启动检查成功时按标签去重后发出 ``startup_update_available``。

        该槽由 ``check_finished`` 派发，因此在 GUI 线程排队执行；只在启动检查
        成功且确实有更新、且标签与上次已提醒标签不同时提醒一次。

        Args:
            request_id: 检查请求 id（仅用于日志）。
            manual: 是否为手动检查。
            info: 检查结果；失败时为 ``None``。
            error: 检查错误；成功时为 ``None``。
        """
        if manual or error is not None or info is None or not info.update_available:
            return

        tag = self._notification_tag(info)
        if not tag:
            debug(f"启动检查 {request_id} 缺少发布标签，跳过通知")
            return

        last_tag = update_startup.read_check_state().get("last_notified_tag")
        if tag == last_tag:
            debug(f"启动检查 {request_id} 的标签 {tag} 已提醒过，跳过通知")
            return

        update_startup.record_notified_tag(tag)
        self.startup_update_available.emit(info)

    @staticmethod
    def _notification_tag(info: UpdateInfo) -> str:
        """提取通知去重标签；优先 ``tag``，缺失时回退版本号。"""
        remote = info.remote if isinstance(info.remote, dict) else {}
        tag = remote.get("tag")
        if not isinstance(tag, str) or not tag:
            tag = remote.get("version")
        if tag is None or tag == "":
            return ""
        return str(tag)

    def _check_crashed(self, request_id: str, exc: BaseException) -> None:
        """检查任务未捕获异常时转为内部错误。"""
        warning(f"UpdateService check 任务异常: {exc!r}")
        self._finish_check(request_id, None, UpdateError("internal"))

    def _info_from_result(self, result: dict[str, Any]) -> UpdateInfo:
        """把 Rust check result 转为 UpdateInfo。"""
        local = result.get("local")
        if not isinstance(local, dict):
            local = {}
        remote = result.get("remote")
        if not isinstance(remote, dict):
            remote = {}
        asset = result.get("asset")
        if not isinstance(asset, dict):
            asset = None
        available = _coerce_bool(result.get("update_available"))
        local_version = str(local.get("version") or get_local_version())
        local_date = local.get("date", get_local_build_date())
        reason = str(result.get("reason") or "none")
        skipped = result.get("skipped_newer_tag")
        return UpdateInfo(
            local_version=local_version,
            local_date=str(local_date) if local_date is not None else None,
            update_available=available,
            reason=reason,
            skipped_newer_tag=str(skipped) if skipped is not None else None,
            remote=remote,
            asset=asset,
        )

    # ------------------------------------------------------------------
    # 下载
    # ------------------------------------------------------------------
    def _validate_download(self, info: UpdateInfo, expected_size: int) -> Optional[str]:
        """校验下载参数；返回错误码或 ``None``。"""
        asset = info.asset
        if not isinstance(asset, dict) or asset.get("sha256") is None:
            return "checksum_missing"
        name = asset.get("name")
        if not isinstance(name, str) or not sanitize_asset_name(name):
            return "bad_params"
        if asset.get("size") is None:
            return "bad_params"
        try:
            download_dir = Path(get_app_data_path()) / "download"
            download_dir.mkdir(parents=True, exist_ok=True)
            free = shutil.disk_usage(download_dir).free
        except OSError:
            return "io"
        if free < expected_size + _DISK_RESERVE:
            return "io"
        return None

    def _run_download(self, request_id: str, epoch: int) -> None:
        """下载池 worker：ensure -> begin -> wait -> 终态处理。"""
        with self._dispatch_lock:
            if not self._owns(request_id, epoch):
                return
            event = self._cancel_events.get(request_id)
            if event is not None and event.is_set():
                cancelled = True
            else:
                cancelled = False
            if not cancelled and self._before_dispatch.pop(request_id, False):
                previous = self._download_state.get(request_id)
                self._download_state[request_id] = "paused"
                ack = self._mark_pause_ack_locked(request_id, True)
                paused_intent = True
                paused_changed = previous != "paused"
                info = self._download_infos.get(request_id)
            else:
                self._dispatching[request_id] = True
                info = self._download_infos.get(request_id)
                ack = False
                paused_intent = False
                paused_changed = False

        if cancelled:
            self._finish_cancelled(request_id, epoch)
            return
        if paused_intent:
            if ack:
                self.download_pause_acked.emit(request_id, True)
            if paused_changed:
                self.download_state_changed.emit(request_id, "paused")
            return
        if info is None:
            self._fail_request(request_id, UpdateError("internal"))
            return

        asset = info.asset or {}
        sanitized = sanitize_asset_name(asset.get("name"))
        if not sanitized:
            self._fail_request(request_id, UpdateError("bad_params"))
            return
        try:
            dest = Path(get_app_data_path()) / "download" / sanitized
            params = {
                "source_url": asset.get("download_url"),
                "dest_path": str(dest),
                "expected_sha256": asset.get("sha256"),
                "expected_size": _coerce_size(asset.get("size")),
            }
            self._bridge.ensure_started()
        except Exception as exc:  # noqa: BLE001 - 原生边界
            self._fail_request(request_id, self._error_from_exception(exc))
            return

        with self._dispatch_lock:
            if not self._owns(request_id, epoch):
                return
            event = self._cancel_events.get(request_id)
            if event is not None and event.is_set():
                late_cancelled = True
                late_paused = False
                late_ack = False
            elif self._before_dispatch.pop(request_id, False):
                late_cancelled = False
                late_paused = True
                late_previous = self._download_state.get(request_id)
                self._download_state[request_id] = "paused"
                self._dispatching[request_id] = False
                late_ack = self._mark_pause_ack_locked(request_id, True)
            else:
                late_cancelled = False
                late_paused = False
                late_previous = None
                late_ack = False

        if late_cancelled:
            self._finish_cancelled(request_id, epoch)
            return
        if late_paused:
            if late_ack:
                self.download_pause_acked.emit(request_id, True)
            if late_previous != "paused":
                self.download_state_changed.emit(request_id, "paused")
            return

        def on_event(event_payload: dict[str, Any]) -> None:
            self._handle_download_event(request_id, epoch, event_payload)

        try:
            self._bridge.download_begin(
                params,
                on_event,
                request_id,
                ensure=False,
            )
        except Exception as exc:  # noqa: BLE001
            self._fail_request(request_id, self._error_from_exception(exc))
            return

        with self._dispatch_lock:
            if not self._owns(request_id, epoch):
                return
            self._dispatched[request_id].set()
            self._dispatching[request_id] = False
            event = self._cancel_events.get(request_id)
            cancel_after_begin = event is not None and event.is_set()
            pause_after_begin = self._before_dispatch.pop(request_id, False)

        if cancel_after_begin:
            try:
                self._bridge.cancel(request_id)
            except Exception as exc:  # noqa: BLE001
                warning(f"UpdateService cancel after begin failed: {exc!r}")
            self._finish_cancelled(request_id, epoch)
            return

        if pause_after_begin:
            try:
                self._bridge.pause(request_id)
            except Exception as exc:  # noqa: BLE001
                warning(f"UpdateService pause after begin failed: {exc!r}")
        try:
            response = self._bridge.download_wait(
                request_id,
                cancel_event=self._cancel_events.get(request_id),
            )
        except UpdaterBridgeError as exc:
            if getattr(exc, "abort", False):
                self._bridge.wait_exited(1.0)
            self._finish_terminal_error(
                request_id, epoch, self._error_from_exception(exc)
            )
            return
        except Exception as exc:  # noqa: BLE001
            self._finish_terminal_error(
                request_id, epoch, self._error_from_exception(exc)
            )
            return

        self._finish_terminal_response(request_id, epoch, response, dest)

    def _verify_cached(self, request_id: str, dest: Path) -> None:
        """任务池 worker：校验缓存文件，命中则完成，否则重新下载。"""
        with self._dispatch_lock:
            info = self._download_infos.get(request_id)
        if info is None or not isinstance(info.asset, dict):
            self._fail_request(request_id, UpdateError("internal"))
            return
        try:
            self._bridge.ensure_started()
            response = self._bridge.verify(
                {"path": str(dest), "sha256": info.asset.get("sha256")}
            )
        except Exception as exc:  # noqa: BLE001
            self._fail_request(request_id, self._error_from_exception(exc))
            return
        if not isinstance(response, dict) or not response.get("ok", False):
            self._fail_request(request_id, self._error_from_response(response))
            return
        result = response.get("result") or {}
        match = bool(result.get("match", False)) if isinstance(result, dict) else False
        if match:
            with self._dispatch_lock:
                if self._download_request_id != request_id:
                    return
                event = self._cancel_events.get(request_id)
                cancelled = event is not None and event.is_set()
                self._clear_request_locked(request_id)
            if cancelled:
                self._remove_artifacts(dest)
                self.download_failed.emit(request_id, UpdateError("cancelled"))
            else:
                self.download_finished.emit(request_id, str(dest))
            return

        self._remove_artifacts(dest)
        with self._dispatch_lock:
            if self._download_request_id != request_id:
                return
            event = self._cancel_events.get(request_id)
            if event is not None and event.is_set():
                cancelled = True
                self._clear_request_locked(request_id)
            else:
                cancelled = False
                self._download_state[request_id] = "running"
        if cancelled:
            self._remove_artifacts(dest)
            self.download_failed.emit(request_id, UpdateError("cancelled"))
            return
        self._download_pool.start(
            _PoolTask(
                lambda: self._run_download(request_id, self._epoch(request_id)),
                lambda exc: self._fail_request(request_id, self._error_from_exception(exc)),
            )
        )

    def _finish_terminal_response(
        self, request_id: str, epoch: int, response: Any, dest: Path
    ) -> None:
        """处理 download_wait 返回的终态响应。"""
        if not isinstance(response, dict) or not response.get("ok", False):
            self._finish_terminal_error(
                request_id, epoch, self._error_from_response(response)
            )
            return
        result = response.get("result") or {}
        if not isinstance(result, dict):
            result = {}
        state = str(result.get("state") or "")
        downloaded = _coerce_int(result.get("downloaded"))
        total = _coerce_int(result.get("total")) or self._download_progress.get(
            request_id, (0, 0)
        )[1]

        with self._dispatch_lock:
            if not self._owns(request_id, epoch):
                return
            event = self._cancel_events.get(request_id)
            cancelled = event is not None and event.is_set()
            pause_ack = False
            paused_changed = False
            if cancelled or state == "cancelled":
                seed = self._mark_pause_ack_locked(request_id, False)
                self._clear_request_locked(request_id)
            elif state == "paused":
                paused_changed = self._download_state.get(request_id) != "paused"
                self._download_state[request_id] = "paused"
                self._download_progress[request_id] = (downloaded, total)
                pause_ack = self._mark_pause_ack_locked(request_id, True)
                seed = False
            elif state == "done":
                self._download_progress[request_id] = (downloaded, total)
                seed = self._mark_pause_ack_locked(request_id, False)
                self._clear_request_locked(request_id)
            else:
                seed = self._mark_pause_ack_locked(request_id, False)
                self._clear_request_locked(request_id)
                state = "error"

        if cancelled or state == "cancelled":
            self._remove_artifacts(dest)
            if seed:
                self.download_pause_acked.emit(request_id, False)
            self.download_failed.emit(request_id, UpdateError("cancelled"))
            return
        if state == "paused":
            if pause_ack:
                self.download_pause_acked.emit(request_id, True)
            if paused_changed:
                self.download_state_changed.emit(request_id, "paused")
            return
        if state == "done":
            if seed:
                self.download_pause_acked.emit(request_id, False)
            self.download_finished.emit(request_id, str(dest))
            return
        self._remove_artifacts(dest)
        if seed:
            self.download_pause_acked.emit(request_id, False)
        self.download_failed.emit(request_id, UpdateError("internal"))

    def _finish_terminal_error(
        self, request_id: str, epoch: int, error: UpdateError
    ) -> None:
        """将 download_wait 的错误响应收尾为终态错误。"""
        with self._dispatch_lock:
            if not self._owns(request_id, epoch):
                return
            ack = self._mark_pause_ack_locked(request_id, False)
            info = self._download_infos.get(request_id)
            dest = self._dest_for(info) if info is not None else None
            self._clear_request_locked(request_id)
        if dest is not None:
            self._remove_artifacts(dest)
        if ack:
            self.download_pause_acked.emit(request_id, False)
        self.download_failed.emit(request_id, error)

    def _handle_download_event(
        self, request_id: str, epoch: int, payload: Any
    ) -> None:
        """转发 Rust 下载事件并维护进度/状态。"""
        if not isinstance(payload, dict):
            return
        name = str(payload.get("event") or "")
        if name == "progress":
            downloaded = _coerce_int(payload.get("downloaded"))
            total = _coerce_int(payload.get("total"))
            speed = 0.0
            try:
                speed = float(payload.get("speed_bps") or 0.0)
            except (TypeError, ValueError):
                speed = 0.0
            with self._dispatch_lock:
                if not self._owns(request_id, epoch):
                    return
                self._download_progress[request_id] = (downloaded, total)
                if self._download_state.get(request_id) != "paused":
                    self._download_state[request_id] = "running"
            self.download_progress.emit(request_id, downloaded, total, speed)
            return
        if name in {"verifying", "paused", "resumed"}:
            new_state = {"verifying": "verifying", "paused": "paused", "resumed": "running"}[name]
            with self._dispatch_lock:
                if not self._owns(request_id, epoch):
                    return
                self._download_state[request_id] = new_state
            self.download_state_changed.emit(request_id, new_state)

    # ------------------------------------------------------------------
    # 控制池
    # ------------------------------------------------------------------
    def _pause_control(self, request_id: str, epoch: int) -> None:
        """Pause from the control pool without racing terminal state."""
        with self._dispatch_lock:
            if not self._owns(request_id, epoch):
                return
            state = self._download_state.get(request_id)
            dispatched = self._dispatched.get(
                request_id, threading.Event()
            ).is_set()
            if state == "verifying":
                accepted = False
                call_bridge = False
            elif state == "paused":
                accepted = True
                call_bridge = False
            elif self._dispatching.get(request_id, False) and not dispatched:
                return
            elif not dispatched:
                accepted = True
                call_bridge = False
            else:
                call_bridge = True
                accepted = False

        if call_bridge:
            try:
                response = self._bridge.pause(request_id)
            except Exception as exc:  # noqa: BLE001
                warning(f"UpdateService pause failed: {exc!r}")
                return
            if not isinstance(response, dict) or not response.get("ok", False):
                warning("UpdateService pause returned an error; waiting for terminal result")
            return

        with self._dispatch_lock:
            if not self._owns(request_id, epoch):
                return
            previous = self._download_state.get(request_id)
            if accepted:
                self._download_state[request_id] = "paused"
            emitted = self._mark_pause_ack_locked(request_id, accepted)
        if emitted:
            self.download_pause_acked.emit(request_id, accepted)
        if accepted and previous != "paused":
            self.download_state_changed.emit(request_id, "paused")

    def _cancel_control(self, request_id: str, state: str) -> None:
        """控制池 worker：按状态通知原生端或直接删除暂停产物。"""
        if state == "paused":
            self._cancel_paused(request_id)
            return
        with self._dispatch_lock:
            if self._download_request_id != request_id:
                return
            dispatched = self._dispatched.get(request_id, threading.Event()).is_set()
            current = self._download_state.get(request_id)
        if current == "verifying" or not dispatched:
            return
        try:
            self._bridge.cancel(request_id)
        except Exception as exc:  # noqa: BLE001
            warning(f"UpdateService cancel 调用失败: {exc!r}")

    def _cancel_paused(self, request_id: str) -> None:
        """删除暂停中的 part/meta/final 并发一次 cancelled。"""
        with self._dispatch_lock:
            if self._download_request_id != request_id:
                return
            info = self._download_infos.get(request_id)
            self._clear_request_locked(request_id)
        if info is not None:
            dest = self._dest_for(info)
            if dest is not None:
                self._remove_artifacts(dest)
        self.download_failed.emit(request_id, UpdateError("cancelled"))

    # ------------------------------------------------------------------
    # 清理与辅助
    # ------------------------------------------------------------------
    def _finish_cancelled(self, request_id: str, epoch: Optional[int] = None) -> None:
        """下载 worker 在 begin 前发现取消时结束请求。"""
        with self._dispatch_lock:
            if self._download_request_id != request_id:
                return
            if epoch is not None and not self._owns(request_id, epoch):
                return
            info = self._download_infos.get(request_id)
            ack = self._mark_pause_ack_locked(request_id, False)
            self._clear_request_locked(request_id)
        if info is not None:
            dest = self._dest_for(info)
            if dest is not None:
                self._remove_artifacts(dest)
        if ack:
            self.download_pause_acked.emit(request_id, False)
        self.download_failed.emit(request_id, UpdateError("cancelled"))

    def _fail_request(self, request_id: str, error: UpdateError) -> None:
        """失败路径统一清理。"""
        with self._dispatch_lock:
            if self._download_request_id != request_id:
                return
            info = self._download_infos.get(request_id)
            ack = self._mark_pause_ack_locked(request_id, False)
            self._clear_request_locked(request_id)
        if info is not None:
            dest = self._dest_for(info)
            if dest is not None:
                self._remove_artifacts(dest)
        if ack:
            self.download_pause_acked.emit(request_id, False)
        self.download_failed.emit(request_id, error)

    def _evict_paused(self, request_id: str, info: Optional[UpdateInfo]) -> None:
        """暂停中的旧资产被新资产替换时删除其产物。"""
        if info is not None:
            dest = self._dest_for(info)
            if dest is not None:
                self._remove_artifacts(dest)
        self._emit_async(self.download_failed, request_id, UpdateError("cancelled"))

    def _dest_for(self, info: Optional[UpdateInfo]) -> Optional[Path]:
        """根据 info 计算最终文件路径。"""
        if info is None or not isinstance(info.asset, dict):
            return None
        name = sanitize_asset_name(info.asset.get("name"))
        if not name:
            return None
        try:
            return Path(get_app_data_path()) / "download" / name
        except OSError:
            return None

    def _remove_artifacts(self, dest: Path) -> None:
        """有界重试删除 final/part/meta，不向调用方抛异常。"""
        for path in (
            dest,
            dest.with_name(dest.name + ".part"),
            dest.with_name(dest.name + ".meta"),
        ):
            for attempt in range(_ARTIFACT_RETRIES):
                try:
                    path.unlink()
                    break
                except FileNotFoundError:
                    break
                except PermissionError:
                    if attempt == _ARTIFACT_RETRIES - 1:
                        warning(f"UpdateService 删除文件失败: {path}")
                        break
                    time.sleep(_ARTIFACT_RETRY_DELAY)
                except OSError as exc:
                    warning(f"UpdateService 删除文件失败: {path}: {exc}")
                    break

    def _same_asset(self, request_id: str, info: UpdateInfo) -> bool:
        """判断新请求与活动请求是否指向同一资产。"""
        current = self._download_infos.get(request_id)
        if current is None:
            return False
        left = current.asset or {}
        right = info.asset or {}
        return (
            left.get("sha256"),
            left.get("name"),
            left.get("size"),
            left.get("download_url"),
        ) == (
            right.get("sha256"),
            right.get("name"),
            right.get("size"),
            right.get("download_url"),
        )

    def _owns(self, request_id: str, epoch: int) -> bool:
        """调用方是否仍持有当前请求的 epoch。"""
        return (
            self._download_request_id == request_id
            and self._dispatch_epoch.get(request_id) == epoch
        )

    def _epoch(self, request_id: str) -> int:
        """读取请求当前 epoch。"""
        with self._dispatch_lock:
            return self._dispatch_epoch.get(request_id, 0)

    def _mark_pause_ack_locked(self, request_id: str, accepted: bool) -> bool:
        """在持锁状态下标记一次 pause ack，返回是否应发信号。"""
        epoch = self._dispatch_epoch.get(request_id)
        if epoch is None:
            return False
        key = (request_id, epoch)
        if key not in self._pause_pending or key in self._pause_ack_sent:
            return False
        self._pause_pending.discard(key)
        self._pause_ack_sent[key] = accepted
        return True

    def _pop_pause_keys_locked(self, request_id: str) -> None:
        """清除某个请求的 pause 尝试记录。"""
        self._pause_pending = {key for key in self._pause_pending if key[0] != request_id}
        self._pause_ack_sent = {
            key: value for key, value in self._pause_ack_sent.items() if key[0] != request_id
        }

    def _clear_request_locked(self, request_id: str) -> None:
        """在持锁状态下彻底清除请求状态。"""
        if self._download_request_id == request_id:
            self._download_request_id = None
        self._download_state.pop(request_id, None)
        self._download_infos.pop(request_id, None)
        self._download_progress.pop(request_id, None)
        self._dispatched.pop(request_id, None)
        self._dispatching.pop(request_id, None)
        self._before_dispatch.pop(request_id, None)
        self._cancel_events.pop(request_id, None)
        self._dispatch_epoch.pop(request_id, None)
        self._pop_pause_keys_locked(request_id)

    def _error_from_response(self, response: Any) -> UpdateError:
        """把 Rust 错误信封转为 UpdateError。"""
        if not isinstance(response, dict):
            return UpdateError("internal")
        raw = response.get("error")
        if not isinstance(raw, dict):
            return UpdateError("internal")
        code = str(raw.get("code") or "internal")
        message = raw.get("message")
        retryable = raw.get("retryable")
        return UpdateError(
            code=code,
            message=str(message) if message else "",
            retryable=bool(retryable) if retryable is not None else None,
        )

    def _error_from_exception(self, exc: BaseException) -> UpdateError:
        """把桥异常转为 UpdateError。"""
        if isinstance(exc, UpdaterBridgeError):
            retryable = getattr(exc, "retryable", None)
            return UpdateError(
                code=str(getattr(exc, "code", "internal") or "internal"),
                message=str(exc),
                retryable=bool(retryable) if retryable is not None else None,
                abort=bool(getattr(exc, "abort", False)),
            )
        return UpdateError("internal", str(exc))

    def _schedule_busy(self, request_id: str) -> None:
        """异步报告 busy，且不为拒绝 id 建立任何状态。"""
        self._emit_async(self.download_failed, request_id, UpdateError("busy"))

    def _emit_async(self, signal: Any, *args: Any) -> None:
        """从 GUI 线程通过事件循环异步发送信号。"""
        QTimer.singleShot(0, lambda: signal.emit(*args))


def get_update_service(
    bridge_factory: Optional[Callable[[], Any]] = None,
) -> UpdateService:
    """Return the UpdateService singleton, creating it on first use."""
    return UpdateService.get_update_service(bridge_factory=bridge_factory)


def get_update_service_if_exists() -> Optional[UpdateService]:
    """Return the existing UpdateService without constructing a new one."""
    return UpdateService.get_update_service_if_exists()
