"""spk_updater.exe NDJSON sidecar 的 Python 桥。

该模块负责 `spk_updater.exe` 子进程的完整生命周期与请求关联：

* 通过 :func:`sopeek.core._paths.native_bin_dir` 定位
  ``spk_updater.exe``；测试可注入可执行文件或完整命令与环境变量，生产默认
  值不受影响。
* stdin/stdout/stderr 全部使用 UTF-8 管线；stdout 与 stderr 各由一个守护
  线程持续排空，stderr 只保留有界尾部（:data:`STDERR_TAIL_BYTES`），避免
  native 侧写满管道或 1 MiB 单行撑爆内存。
* 每行一个 JSON 对象。请求的 ``id`` 由调用方决定（未提供时自动生成
  ``b1``/``b2``/...），响应按 ``id`` 精确投递到
  :attr:`_waiters`，未知 id 与畸形 JSON 行被静默忽略。
* stdout EOF / 进程退出 / 写管道失败会把 :attr:`_process_exited` 置位并
  唤醒所有等待者，异常携带边界化 stderr 尾部。
* 单个请求超时只清理该请求的等待者，不会终止进程。
* ``stop`` 是**总预算**：shutdown ack → terminate → kill 全部受调用方
  ``timeout`` 约束。

除生命周期与请求关联外，本模块还提供下载事件流的分体接口：

* :meth:`SpkUpdaterBridge.download_begin` 只注册回调/终态队列并写请求，
  立即返回；:meth:`SpkUpdaterBridge.download_wait` 才阻塞等待同 id 终态。
* 事件行按到达顺序在 stdout 读线程回调；单个回调异常只记录日志，不会
  杀死读线程。
* 同一时刻只允许一个活动下载；``pause``/``cancel`` 通过普通 :meth:`request`
  发送，ack 的 id 是控制请求 id，而不是目标下载 id。
* ``stop``/``close``/进程退出会以 ``process_exited`` 唤醒下载等待者。
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Optional

from sopeek.core import _paths
from sopeek.utils.app_logger import debug

UPDATER_EXE_NAME: str = "spk_updater.exe"

#: ``check`` 的默认超时（秒），与计划约定一致。
DEFAULT_CHECK_TIMEOUT: float = 45.0

#: ``stop`` 等待 shutdown ack 的上限（秒）。
SHUTDOWN_ACK_TIMEOUT: float = 1.7

#: ``stop`` 在 terminate 后等待退出的上限（秒）。
TERMINATE_TIMEOUT: float = 1.0

#: stderr 保留的尾部字节/字符上限（远小于 1 MiB 洪泛）。
STDERR_TAIL_BYTES: int = 16 * 1024

#: 等待 stderr 读线程收尾的上限（秒）。
STDERR_JOIN_TIMEOUT: float = 1.0

#: ``cancel_event`` 置位后等待终态的总宽限期（秒，1s 轮询 + 1s 宽限）。
CANCEL_GRACE_TIMEOUT: float = 2.0

#: ``download_wait`` 轮询终态队列的单次切片（秒），用于观察取消/空闲/总超时。
DOWNLOAD_POLL_INTERVAL: float = 0.1


class UpdaterBridgeError(RuntimeError):
    """``SpkUpdaterBridge`` 抛出的结构化错误。

    Attributes:
        code: 稳定的错误码（``timeout``/``idle_timeout``/``process_exited``/
            ``write_failed``/``not_running``/``duplicate_request_id``/
            ``unavailable``/``busy``/``cancelled``/``unknown_request``）。
        stderr_tail: 进程 stderr 的有界尾部（可能为空字符串）。
        exit_code: 可获得的进程退出码；未知时为 ``None``。
        abort: 本次失败是否由桥主动中止下载（取消/空闲）触发。
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        stderr_tail: str = "",
        exit_code: Optional[int] = None,
        abort: bool = False,
    ) -> None:
        self.code = code
        self.stderr_tail = stderr_tail
        self.exit_code = exit_code
        self.abort = abort
        detail = f"{code}: {message}"
        if exit_code is not None:
            detail += f" (exit code {exit_code})"
        if stderr_tail:
            detail += f"\nstderr tail:\n{stderr_tail}"
        super().__init__(detail)


class SpkUpdaterBridge:
    """`spk_updater.exe` 的 NDJSON 子进程桥。"""

    def __init__(
        self,
        executable: Optional[Path | str] = None,
        *,
        command: Optional[Sequence[Path | str]] = None,
        env: Optional[Mapping[str, str]] = None,
        cwd: Optional[Path | str] = None,
        startup_timeout: float = 5.0,
    ) -> None:
        """构造桥（不会立即启动进程）。

        Args:
            executable: 可执行文件路径；``None`` 时使用
                ``native_bin_dir()/spk_updater.exe``。
            command: 完整命令序列（含解释器），用于测试注入
                ``[sys.executable, fake_updater.py]``；优先级高于
                ``executable``。
            env: 追加/覆盖到当前进程环境变量的键值；生产默认环境保持不变。
            cwd: 子进程工作目录；``None`` 表示继承当前目录。
            startup_timeout: 预留的启动等待上限（秒）。
        """
        if command is not None:
            self._command: list[str] = [str(part) for part in command]
        elif executable is not None:
            self._command = [str(executable)]
        else:
            self._command = [str(_paths.native_bin_dir() / UPDATER_EXE_NAME)]
        self._merged_env: dict[str, str] = dict(os.environ)
        if env is not None:
            self._merged_env.update({str(key): str(value) for key, value in env.items()})
        self._cwd = str(cwd) if cwd is not None else None
        self._startup_timeout = float(startup_timeout)

        self._lifecycle_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._exit_lock = threading.Lock()
        self._close_lock = threading.Lock()

        self._waiters: dict[str, queue.Queue[Any]] = {}
        #: 每个活动下载的终态队列；只能由 ``download_wait`` 在消费后移除。
        self._download_terminals: dict[str, queue.Queue[Any]] = {}
        #: 每个活动下载的事件回调（在 stdout 读线程按到达顺序调用）。
        self._download_callbacks: dict[str, Optional[Callable[[dict[str, Any]], None]]] = {}
        #: 每个活动下载最近一次事件/终态的时间戳（monotonic），用于空闲超时。
        self._download_activity: dict[str, float] = {}
        #: 单活动下载预留；由 ``_state_lock`` 保护。
        self._active_download_id: Optional[str] = None
        self._process_exited = threading.Event()
        self._process: Optional[subprocess.Popen[str]] = None
        self._generation = 0
        self._next_id = 0
        self._stderr_tail = ""
        self._exit_code: Optional[int] = None
        self._stdout_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._closed = False

    # ------------------------------------------------------------------
    # 只读属性
    # ------------------------------------------------------------------
    @property
    def command(self) -> list[str]:
        """返回启动命令的副本（测试与诊断用）。"""
        return list(self._command)

    @property
    def env(self) -> dict[str, str]:
        """返回合并后环境变量的副本（测试与诊断用）。"""
        return dict(self._merged_env)

    @property
    def stderr_tail(self) -> str:
        """返回当前 stderr 有界尾部快照。"""
        with self._state_lock:
            return self._stderr_tail

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def is_running(self) -> bool:
        """进程是否存在且尚未退出。

        Returns:
            bool: 有活着的子进程时为 ``True``。
        """
        process = self._process
        return (
            process is not None
            and process.poll() is None
            and not self._process_exited.is_set()
        )

    def is_available(self) -> bool:
        """重新探测 updater 可执行文件是否存在（不启动子进程）。

        Returns:
            bool: 单文件命令指向真实文件，或多段命令未显式缺失时返回 ``True``。
        """
        command = list(self._command)
        if not command:
            return False
        if len(command) == 1:
            return Path(command[0]).is_file()
        return True

    def start(self) -> bool:
        """启动子进程（已运行时幂等）。

        Returns:
            bool: 成功启动或已经在运行时为 ``True``。

        Raises:
            UpdaterBridgeError: 可执行文件缺失或 ``Popen`` 失败。
        """
        with self._lifecycle_lock:
            return self._start_locked()

    def ensure_started(self) -> bool:
        """确保有活着的子进程，并发调用只会 spawn 一次。

        Returns:
            bool: 有活着的子进程时为 ``True``。

        Raises:
            UpdaterBridgeError: 进程无法启动。
        """
        with self._lifecycle_lock:
            if self.is_running():
                return True
            return self._start_locked()

    def _start_locked(self) -> bool:
        """在持有 ``_lifecycle_lock`` 时启动进程。"""
        previous = self._process
        if previous is not None and previous.poll() is None:
            return True
        if previous is not None:
            self._signal_exit(
                "previous process exited",
                previous.returncode,
                generation=self._generation,
            )
        # 先递增代际，使旧 reader 线程的迟到 EOF 不再影响新进程。
        self._generation += 1
        generation = self._generation
        self._join_readers(STDERR_JOIN_TIMEOUT)

        with self._state_lock:
            self._stderr_tail = ""
            self._exit_code = None
        self._process_exited.clear()

        command = self._resolve_command()
        creationflags = 0
        if os.name == "nt":
            creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=self._merged_env,
                cwd=self._cwd,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise UpdaterBridgeError(
                "unavailable",
                f"无法启动 spk_updater: {command!r}: {exc}",
            ) from exc

        self._process = process
        self._stdout_thread = threading.Thread(
            target=self._stdout_loop,
            args=(process, generation),
            name=f"spk-updater-stdout-{generation}",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._stderr_loop,
            args=(process, generation),
            name=f"spk-updater-stderr-{generation}",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()
        debug(f"spk_updater 已启动: {command!r} (generation={generation})")
        return True

    def _resolve_command(self) -> list[str]:
        """校验并返回实际启动命令。"""
        command = list(self._command)
        if not command:
            raise UpdaterBridgeError("unavailable", "spk_updater 启动命令为空")
        # 显式 command（含解释器）由调用方负责；单元素命令视为可执行文件。
        if len(command) == 1:
            path = Path(command[0])
            if not path.is_file():
                raise UpdaterBridgeError(
                    "unavailable",
                    f"spk_updater 可执行文件不存在: {path}",
                )
        return command

    # ------------------------------------------------------------------
    # 请求 / 响应
    # ------------------------------------------------------------------
    def request(
        self,
        cmd: str,
        params: Optional[Any] = None,
        timeout: Optional[float] = None,
        request_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """发送一条 NDJSON 请求并等待同 id 响应。

        Args:
            cmd: 命令名（如 ``hello``/``check``/``verify``）。
            params: 命令参数，序列化为 JSON ``params`` 字段。
            timeout: 等待响应的秒数；``None`` 表示无限等待。超时只会移除
                本请求的等待者，不影响进程。
            request_id: 调用方指定的请求 id；``None`` 时自动生成
                ``b1``/``b2``/...。指定值原样写入 JSON、原样匹配响应。

        Returns:
            dict[str, Any]: 完整响应信封（``{"id","ok","result"/"error"}``）。

        Raises:
            UpdaterBridgeError: 进程未运行、写管道失败、等待超时或进程退出。
        """
        if not isinstance(cmd, str) or not cmd:
            raise ValueError("cmd 必须是非空字符串")
        if request_id is not None and not isinstance(request_id, str):
            raise TypeError("request_id 必须是字符串或 None")
        payload = {} if params is None else params
        waiter: queue.Queue[Any] = queue.Queue(maxsize=1)
        generation = self._generation

        with self._write_lock:
            process = self._process
            if process is None or not self.is_running() or process.stdin is None:
                tail, exit_code = self._error_snapshot()
                raise UpdaterBridgeError(
                    "not_running",
                    "spk_updater 进程未运行",
                    stderr_tail=tail,
                    exit_code=exit_code,
                )
            with self._state_lock:
                resolved_id = (
                    request_id
                    if request_id is not None
                    else self._next_auto_id_locked()
                )
                if (
                    resolved_id in self._waiters
                    or resolved_id in self._download_terminals
                    or resolved_id == self._active_download_id
                ):
                    raise UpdaterBridgeError(
                        "duplicate_request_id",
                        f"请求 id 已存在: {resolved_id}",
                    )
                self._waiters[resolved_id] = waiter
            encoded = (
                json.dumps(
                    {"id": resolved_id, "cmd": cmd, "params": payload},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
            try:
                process.stdin.write(encoded)
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                with self._state_lock:
                    if self._waiters.get(resolved_id) is waiter:
                        del self._waiters[resolved_id]
                tail, exit_code = self._error_snapshot()
                self._signal_exit(
                    "stdin write failed",
                    _safe_returncode(process),
                    generation=generation,
                )
                raise UpdaterBridgeError(
                    "write_failed",
                    f"写入 {cmd} 请求失败: {exc}",
                    stderr_tail=tail,
                    exit_code=exit_code,
                ) from exc

        try:
            outcome = waiter.get() if timeout is None else waiter.get(timeout=timeout)
        except queue.Empty:
            with self._state_lock:
                if self._waiters.get(resolved_id) is waiter:
                    del self._waiters[resolved_id]
            raise UpdaterBridgeError(
                "timeout",
                f"{cmd} (id={resolved_id}) 在 {timeout:.3f}s 内没有响应",
            ) from None

        if isinstance(outcome, BaseException):
            raise outcome
        if not isinstance(outcome, dict):  # pragma: no cover - internal invariant
            raise UpdaterBridgeError("protocol", "响应不是 JSON 对象")
        return outcome

    def check(
        self,
        params: Optional[Any] = None,
        request_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """发送 ``check`` 请求，默认等待 45 秒。"""
        return self.request(
            "check",
            params,
            timeout=DEFAULT_CHECK_TIMEOUT,
            request_id=request_id,
        )

    def verify(
        self,
        params: Optional[Any] = None,
        request_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """发送 ``verify`` 请求（``check`` 风格的便利包装）。"""
        return self.request(
            "verify",
            params,
            timeout=DEFAULT_CHECK_TIMEOUT,
            request_id=request_id,
        )

    # ------------------------------------------------------------------
    # 下载：begin / wait / 兼容包装 / 控制
    # ------------------------------------------------------------------
    def download_begin(
        self,
        params: Optional[Any],
        on_event: Optional[Callable[[dict[str, Any]], None]],
        request_id: str,
        *,
        ensure: bool = True,
    ) -> None:
        """发送 ``download`` 请求并立即返回（不等待终态）。

        终态等待队列与事件回调在写 stdin **之前**注册，因此子进程再快也
        不会丢事件。``ensure=True`` 时在 ``_write_lock`` 之外调用
        :meth:`ensure_started`；``ensure=False`` 供已经预启动边车的服务
        worker 使用，此时绝不获取 ``_lifecycle_lock``。

        Args:
            params: ``download`` 命令参数。
            on_event: 接收 ``{"event":..., "id":...}`` 原始字典的回调；在
                stdout 读线程按到达顺序调用，异常被捕获并记录日志。
            request_id: 服务层生成的请求 id，原样写入 JSON 并由终态响应
                原样回显；桥不改写。
            ensure: 是否在写入前确保边车已启动。

        Raises:
            UpdaterBridgeError: 已有活动下载（``busy``）、id 冲突
                （``duplicate_request_id``）、进程未运行或写管道失败。
        """
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request_id 必须是非空字符串")
        if on_event is not None and not callable(on_event):
            raise TypeError("on_event 必须是可调用对象或 None")

        # ensure 必须在注册之前完成：_start_locked 对已退出的旧进程会调用
        # _signal_exit，若先注册会被当作旧下载唤醒。
        if ensure:
            self.ensure_started()

        terminal: queue.Queue[Any] = queue.Queue()
        with self._state_lock:
            active = self._active_download_id
            if active is not None:
                raise UpdaterBridgeError(
                    "busy",
                    f"已有活动下载: {active}",
                )
            if request_id in self._waiters or request_id in self._download_terminals:
                raise UpdaterBridgeError(
                    "duplicate_request_id",
                    f"请求 id 已存在: {request_id}",
                )
            self._active_download_id = request_id
            self._download_terminals[request_id] = terminal
            self._download_callbacks[request_id] = on_event
            self._download_activity[request_id] = time.monotonic()

        payload = {} if params is None else params
        encoded = (
            json.dumps(
                {"id": request_id, "cmd": "download", "params": payload},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )
        generation = self._generation
        with self._write_lock:
            process = self._process
            if process is None or not self.is_running() or process.stdin is None:
                self._release_download(request_id)
                tail, exit_code = self._error_snapshot()
                raise UpdaterBridgeError(
                    "not_running",
                    "spk_updater 进程未运行",
                    stderr_tail=tail,
                    exit_code=exit_code,
                )
            try:
                process.stdin.write(encoded)
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._release_download(request_id)
                tail, exit_code = self._error_snapshot()
                self._signal_exit(
                    "stdin write failed",
                    _safe_returncode(process),
                    generation=generation,
                )
                raise UpdaterBridgeError(
                    "write_failed",
                    f"写入 download 请求失败: {exc}",
                    stderr_tail=tail,
                    exit_code=exit_code,
                ) from exc

    def download_wait(
        self,
        request_id: str,
        timeout: Optional[float] = None,
        *,
        idle_timeout: Optional[float] = 300.0,
        cancel_event: Optional[threading.Event] = None,
    ) -> dict[str, Any]:
        """阻塞等待某次下载的终态响应。

        Args:
            request_id: :meth:`download_begin` 使用的请求 id。
            timeout: 总等待上限（秒）；``None`` 表示不设总上限。
            idle_timeout: 连续无事件/终态的空闲上限（秒）；``None`` 关闭。
            cancel_event: 取消信号；置位后最多等待
                :data:`CANCEL_GRACE_TIMEOUT` 秒终态，超时则
                ``stop(timeout=1.0)`` 并抛出 ``cancelled``（``abort=True``）。

        Returns:
            dict[str, Any]: 终态响应信封（``id`` 与 ``request_id`` 相同）。

        Raises:
            UpdaterBridgeError: 未知下载、进程退出、取消、空闲、总超时或
                协议错误。
        """
        if not isinstance(request_id, str):
            raise TypeError("request_id 必须是字符串")
        with self._state_lock:
            terminal = self._download_terminals.get(request_id)
            tail = self._stderr_tail
            exit_code = self._exit_code
        if terminal is None:
            raise UpdaterBridgeError(
                "unknown_request",
                f"没有活动下载: {request_id}",
                stderr_tail=tail,
                exit_code=exit_code,
            )

        started = time.monotonic()
        deadline = (
            None
            if timeout is None
            else started + max(0.0, float(timeout))
        )
        idle_limit = (
            None
            if idle_timeout is None
            else max(0.0, float(idle_timeout))
        )
        last_activity = started
        cancel_deadline: Optional[float] = None

        while True:
            now = time.monotonic()
            if cancel_event is not None and cancel_event.is_set():
                if cancel_deadline is None:
                    cancel_deadline = now + CANCEL_GRACE_TIMEOUT
                if now >= cancel_deadline:
                    self.stop(timeout=1.0)
                    self._release_download(request_id)
                    raise UpdaterBridgeError(
                        "cancelled",
                        f"下载 {request_id} 在取消信号后 "
                        f"{CANCEL_GRACE_TIMEOUT:.1f}s 内没有终态",
                        abort=True,
                    )
            if deadline is not None and now >= deadline:
                # 调用方级总超时只是放弃本次等待：下载仍在运行，必须保留
                # 终态队列/回调/活动时间与单活动预留，允许再次 wait 或
                # pause/cancel；释放只属于终态、进程退出、取消/空闲中止与
                # ensure/write 失败等真正的结束路径。
                raise UpdaterBridgeError(
                    "timeout",
                    f"下载 {request_id} 在 {float(timeout):.3f}s 内没有终态",
                )

            with self._state_lock:
                activity = self._download_activity.get(request_id)
            if activity is not None:
                last_activity = max(last_activity, activity)
            if idle_limit is not None and now - last_activity > idle_limit:
                self.stop(timeout=1.0)
                self._release_download(request_id)
                raise UpdaterBridgeError(
                    "idle_timeout",
                    f"下载 {request_id} 空闲超过 {idle_limit:.1f}s",
                    abort=True,
                )

            wait_slice = DOWNLOAD_POLL_INTERVAL
            if cancel_deadline is not None:
                wait_slice = min(wait_slice, max(0.01, cancel_deadline - now))
            if deadline is not None:
                wait_slice = min(wait_slice, max(0.01, deadline - now))
            if idle_limit is not None:
                wait_slice = min(wait_slice, max(0.01, idle_limit - (now - last_activity)))
            try:
                outcome = terminal.get(timeout=wait_slice)
            except queue.Empty:
                continue

            if isinstance(outcome, BaseException):
                self._release_download(request_id)
                raise outcome
            if not isinstance(outcome, dict):  # pragma: no cover - internal invariant
                self._release_download(request_id)
                raise UpdaterBridgeError("protocol", "下载终态响应不是 JSON 对象")
            self._release_download(request_id)
            return outcome

    def download(
        self,
        params: Optional[Any],
        on_event: Optional[Callable[[dict[str, Any]], None]],
        request_id: str,
        *,
        ensure: bool = True,
        timeout: Optional[float] = None,
        idle_timeout: Optional[float] = 300.0,
        cancel_event: Optional[threading.Event] = None,
    ) -> dict[str, Any]:
        """``download_begin`` + ``download_wait`` 的同步兼容包装。"""
        self.download_begin(params, on_event, request_id, ensure=ensure)
        return self.download_wait(
            request_id,
            timeout=timeout,
            idle_timeout=idle_timeout,
            cancel_event=cancel_event,
        )

    def pause(self, target_id: str) -> dict[str, Any]:
        """暂停 ``target_id`` 对应的活动下载，返回控制请求的 ack。"""
        return self.request(
            "pause",
            {"target": target_id},
            timeout=DEFAULT_CHECK_TIMEOUT,
        )

    def cancel(self, target_id: str) -> dict[str, Any]:
        """取消 ``target_id`` 对应的活动下载，返回控制请求的 ack。"""
        return self.request(
            "cancel",
            {"target": target_id},
            timeout=DEFAULT_CHECK_TIMEOUT,
        )

    def _release_download(self, request_id: str) -> None:
        """移除一次下载的终态队列/回调/活动时间并释放预留。"""
        with self._state_lock:
            if self._active_download_id == request_id:
                self._active_download_id = None
            self._download_terminals.pop(request_id, None)
            self._download_callbacks.pop(request_id, None)
            self._download_activity.pop(request_id, None)

    def _next_auto_id_locked(self) -> str:
        """在持有 ``_state_lock`` 时生成未占用的 ``bN`` id。"""
        while True:
            self._next_id += 1
            candidate = f"b{self._next_id}"
            if (
                candidate not in self._waiters
                and candidate not in self._download_terminals
                and candidate != self._active_download_id
            ):
                return candidate

    # ------------------------------------------------------------------
    # 读取 / 排空线程
    # ------------------------------------------------------------------
    def _stdout_loop(
        self,
        process: subprocess.Popen[str],
        generation: int,
    ) -> None:
        """逐行读取 stdout；EOF 视为进程退出。"""
        stdout = process.stdout
        if stdout is not None:
            try:
                for raw_line in stdout:
                    if generation != self._generation:
                        return
                    line = raw_line.strip()
                    if not line:
                        continue
                    self._dispatch_line(line)
            except (OSError, ValueError):
                pass
        if generation == self._generation:
            self._finalize_exit(process, generation)

    def _stderr_loop(
        self,
        process: subprocess.Popen[str],
        generation: int,
    ) -> None:
        """持续排空 stderr，仅保留有界尾部。"""
        stream = process.stderr
        if stream is None:
            return
        while True:
            try:
                chunk = stream.read(4096)
            except (OSError, ValueError):
                break
            if not chunk:
                break
            if generation != self._generation:
                break
            with self._state_lock:
                self._stderr_tail = (self._stderr_tail + chunk)[-STDERR_TAIL_BYTES:]

    def _dispatch_line(self, line: str) -> None:
        """把一条 stdout 行投递给精确匹配 id 的等待者。"""
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            # 畸形行直接跳过；后续合法响应仍能正常匹配。
            return
        if not isinstance(value, dict):
            return
        request_id = value.get("id")
        if not isinstance(request_id, str):
            return
        if "event" in value:
            now = time.monotonic()
            with self._state_lock:
                callback = self._download_callbacks.get(request_id)
                if request_id in self._download_activity:
                    self._download_activity[request_id] = now
            if callback is not None:
                try:
                    callback(value)
                except Exception as exc:  # noqa: BLE001 - 回调异常不得杀死读线程
                    debug(f"下载事件回调失败 (id={request_id}): {exc!r}")
            return
        now = time.monotonic()
        with self._state_lock:
            terminal = self._download_terminals.get(request_id)
            if terminal is not None:
                self._download_activity[request_id] = now
                # 终态已到达：释放预留，但保留队列直到 download_wait 消费。
                if self._active_download_id == request_id:
                    self._active_download_id = None
                self._download_callbacks.pop(request_id, None)
            else:
                waiter = self._waiters.pop(request_id, None)
        if terminal is not None:
            try:
                terminal.put_nowait(value)
            except queue.Full:  # pragma: no cover - 终态队列无界
                pass
            return
        if waiter is None:
            # 超时后的迟到响应或未知 id：不得唤醒任何其他等待者。
            return
        try:
            waiter.put_nowait(value)
        except queue.Full:  # pragma: no cover - 一个 waiter 只应收到一次
            pass

    def _finalize_exit(
        self,
        process: subprocess.Popen[str],
        generation: int,
    ) -> None:
        """stdout EOF 后短暂等待 stderr 排空并唤醒所有等待者。"""
        if generation != self._generation:
            return
        stderr_thread = self._stderr_thread
        if stderr_thread is not None and stderr_thread is not threading.current_thread():
            stderr_thread.join(timeout=STDERR_JOIN_TIMEOUT)
        exit_code: Optional[int] = None
        try:
            exit_code = process.wait(timeout=STDERR_JOIN_TIMEOUT)
        except subprocess.TimeoutExpired:
            exit_code = _safe_returncode(process)
        if generation != self._generation:
            return
        self._signal_exit(
            "stdout EOF",
            exit_code,
            generation=generation,
        )

    def _signal_exit(
        self,
        reason: str,
        exit_code: Optional[int],
        *,
        generation: Optional[int] = None,
    ) -> None:
        """置位退出事件并把错误投递给所有等待者（幂等）。"""
        with self._exit_lock:
            if generation is not None and generation != self._generation:
                return
            if self._process_exited.is_set():
                return
            with self._state_lock:
                tail = self._stderr_tail
                waiters = list(self._waiters.values())
                self._waiters.clear()
                terminals = list(self._download_terminals.values())
                self._download_callbacks.clear()
                self._download_activity.clear()
                self._active_download_id = None
                self._exit_code = exit_code
                self._process_exited.set()
        if not waiters and not terminals:
            return
        detail = f"spk_updater 已退出（{reason}）"
        for waiter in waiters:
            waiter.put_nowait(
                UpdaterBridgeError(
                    "process_exited",
                    detail,
                    stderr_tail=tail,
                    exit_code=exit_code,
                )
            )
        # 终态队列由 download_wait 消费后再移除；这里只投递唤醒错误。
        for terminal in terminals:
            terminal.put_nowait(
                UpdaterBridgeError(
                    "process_exited",
                    detail,
                    stderr_tail=tail,
                    exit_code=exit_code,
                )
            )

    # ------------------------------------------------------------------
    # ֹͣ / �ر�
    # ------------------------------------------------------------------
    def wait_exited(self, timeout: float = 1.0) -> bool:
        """等待子进程退出但**不**主动终止它。

        取消路径在确认 ``abort=True`` 后先调用本方法，确保原生进程已不再
        持有安装包句柄，再删除半成品文件。

        Args:
            timeout: 最长等待秒数。

        Returns:
            bool: 进程已退出或本来就不存在时为 ``True``；超时返回 ``False``。
        """
        process = self._process
        if process is None:
            return True
        try:
            process.wait(timeout=max(0.0, float(timeout)))
        except subprocess.TimeoutExpired:
            return False
        return True

    def stop(self, timeout: float = 4.0) -> bool:
        """在**总预算**内停止子进程。

        顺序为：shutdown 请求（等待 ack ≤1.7 s）→ ``terminate()``
        （≤1.0 s）→ ``kill()`` 并使用剩余预算轮询。未启动或已停止时立即
        返回 ``True`` 且不写任何管道。

        Args:
            timeout: 整个停止过程的总预算（秒）。

        Returns:
            bool: 始终为 ``True``（进程已停止或本就不在运行）。
        """
        budget = max(0.0, float(timeout))
        with self._lifecycle_lock:
            return self._stop_locked(budget)

    def _stop_locked(self, timeout: float) -> bool:
        """在持有 ``_lifecycle_lock`` 时执行带预算的停止。"""
        deadline = time.monotonic() + max(0.0, timeout)
        process = self._process
        if process is None:
            return True
        if process.poll() is not None:
            self._signal_exit(
                "already exited",
                process.returncode,
                generation=self._generation,
            )
            self._process = None
            return True

        generation = self._generation
        # 停止是桥层主动中止：先唤醒全部等待者（含下载终态队列），
        # 避免 download_wait 依赖子进程是否还来得及写终态行。
        self._signal_exit("stop requested", None, generation=generation)
        ack_waiter: queue.Queue[Any] = queue.Queue(maxsize=1)
        shutdown_id = f"shutdown-{generation}"
        with self._state_lock:
            self._waiters[shutdown_id] = ack_waiter
        encoded = (
            json.dumps(
                {"id": shutdown_id, "cmd": "shutdown", "params": {}},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )
        try:
            with self._write_lock:
                if process.stdin is not None and process.poll() is None:
                    process.stdin.write(encoded)
                    process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        ack_budget = min(
            SHUTDOWN_ACK_TIMEOUT,
            max(0.0, deadline - time.monotonic()),
        )
        try:
            ack_waiter.get(timeout=ack_budget)
        except queue.Empty:
            pass
        finally:
            with self._state_lock:
                if self._waiters.get(shutdown_id) is ack_waiter:
                    del self._waiters[shutdown_id]

        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
            terminate_budget = min(
                TERMINATE_TIMEOUT,
                max(0.0, deadline - time.monotonic()),
            )
            try:
                process.wait(timeout=terminate_budget)
            except subprocess.TimeoutExpired:
                pass

        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
            remaining = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                # 预算耗尽后仍给一个极短的回收窗口，避免留下僵尸句柄。
                try:
                    process.wait(timeout=0.05)
                except subprocess.TimeoutExpired:
                    pass

        self._signal_exit(
            "stop requested",
            _safe_returncode(process),
            generation=generation,
        )
        self._process = None
        debug(f"spk_updater 已停止 (generation={generation})")
        return True

    def close(self) -> None:
        """幂等关闭桥：停止进程、回收输出线程并关闭管道。"""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        with self._lifecycle_lock:
            process = self._process
            if process is not None and process.poll() is None:
                self._stop_locked(4.0)
            else:
                self._signal_exit(
                    "close",
                    _safe_returncode(process) if process is not None else None,
                    generation=self._generation,
                )
                self._process = None
            self._join_readers(STDERR_JOIN_TIMEOUT)
            if process is not None:
                for stream in (process.stdin, process.stdout, process.stderr):
                    try:
                        if stream is not None:
                            stream.close()
                    except (OSError, ValueError):
                        pass
                try:
                    process.wait(timeout=0.5)
                except (subprocess.TimeoutExpired, OSError):
                    pass

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _join_readers(self, timeout: float) -> None:
        """等待输出线程结束（跳过当前线程）。"""
        current = threading.current_thread()
        for thread in (self._stdout_thread, self._stderr_thread):
            if thread is not None and thread is not current and thread.is_alive():
                thread.join(timeout=timeout)

    def _error_snapshot(self) -> tuple[str, Optional[int]]:
        """返回 (stderr 尾部, 退出码) 快照。"""
        with self._state_lock:
            return self._stderr_tail, self._exit_code


_instance_lock: threading.Lock = threading.Lock()
_instance: Optional["SpkUpdaterBridge"] = None


def get_spk_updater_bridge() -> "SpkUpdaterBridge":
    """获取 spk_updater 桥的模块级惰性单例（线程安全）。

    惰性构造避免启动期在 sidecar 缺失环境产生不必要的 I/O；构造本身不会
    启动子进程，调用方仍需经 ``ensure_started``/``is_available`` 管理生命周期。

    Returns:
        SpkUpdaterBridge: 桥实例（模块首次调用时构造）。
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = SpkUpdaterBridge()
    return _instance


def _safe_returncode(process: subprocess.Popen[str]) -> Optional[int]:
    """读取进程退出码，进程仍存活时返回 ``None``。"""
    try:
        return process.poll()
    except OSError:  # pragma: no cover - poll 极少失败
        return None
