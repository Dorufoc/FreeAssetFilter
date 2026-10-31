# -*- coding: utf-8 -*-
"""``SpkUpdaterBridge`` 的单元测试（Todo 7）。

覆盖生命周期、请求/响应关联、超时隔离、崩溃唤醒、stderr 有界排空、
UTF-8、停止预算与关闭幂等，以及假边车的未来下载契约。

所有测试只启动 ``tests/support/fake_updater.py``，不访问网络。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from sopeek.core import _paths
from sopeek.core.native.bridges import spk_updater_bridge as bridge_module
from sopeek.core.native.bridges.spk_updater_bridge import (
    DEFAULT_CHECK_TIMEOUT,
    STDERR_TAIL_BYTES,
    SpkUpdaterBridge,
    UpdaterBridgeError,
)

pytestmark = pytest.mark.unit

FAKE_UPDATER: Path = (
    Path(__file__).resolve().parents[2] / "support" / "fake_updater.py"
)


def _fake_command() -> list[str]:
    """返回启动假边车的完整命令。"""
    return [sys.executable, str(FAKE_UPDATER)]


def _wait_for(predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    """轮询等待条件成立。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.fixture
def bridge_factory() -> Iterator[Callable[..., SpkUpdaterBridge]]:
    """创建使用假边车的桥，并在测试结束时统一关闭。"""
    bridges: list[SpkUpdaterBridge] = []

    def factory(env: Mapping[str, str] | None = None) -> SpkUpdaterBridge:
        bridge = SpkUpdaterBridge(command=_fake_command(), env=env)
        bridges.append(bridge)
        return bridge

    yield factory
    for bridge in bridges:
        bridge.close()


# =============================================================================
# 定位与生产默认值
# =============================================================================
def test_default_command_lives_under_native_bin_dir() -> None:
    """未注入命令时定位 ``native_bin_dir()/spk_updater.exe``。"""
    bridge = SpkUpdaterBridge()
    expected = _paths.native_bin_dir() / "spk_updater.exe"
    assert Path(bridge.command[0]) == expected
    assert bridge.command[0] == str(expected)
    bridge.close()


def test_test_injection_does_not_weaken_production_defaults() -> None:
    """注入命令/环境只影响该实例。"""
    bridge = SpkUpdaterBridge(
        command=_fake_command(),
        env={"SPK_FAKE_MARKER": "1"},
    )
    assert bridge.command == _fake_command()
    assert bridge.env["SPK_FAKE_MARKER"] == "1"
    assert "PATH" in bridge.env, "应继承既有环境变量"
    bridge.close()


# =============================================================================
# 请求 / 响应关联
# =============================================================================
def test_hello_happy_path_returns_protocol_and_version(
    bridge_factory: Callable[..., SpkUpdaterBridge],
) -> None:
    """真实线路形状：hello 返回 protocol=1。"""
    bridge = bridge_factory()
    assert bridge.ensure_started() is True

    response = bridge.request("hello")

    assert response["id"] == "b1"
    assert response["ok"] is True
    assert response["result"]["protocol"] == 1
    assert isinstance(response["result"]["version"], str)


def test_caller_supplied_request_id_is_echoed_verbatim(
    bridge_factory: Callable[..., SpkUpdaterBridge],
) -> None:
    """调用方 id 原样写入并原样回显。"""
    bridge = bridge_factory()
    bridge.ensure_started()
    request_id = "req-中文 with spaces-?"

    response = bridge.request("hello", request_id=request_id)

    assert response["id"] == request_id


def test_auto_ids_increment_only_when_none(
    bridge_factory: Callable[..., SpkUpdaterBridge],
) -> None:
    """未提供 id 时生成 b1/b2...；显式 id 不消耗自动序号。"""
    bridge = bridge_factory()
    bridge.ensure_started()

    first = bridge.request("hello")
    explicit = bridge.request("hello", request_id="custom")
    second = bridge.request("hello")

    assert [first["id"], explicit["id"], second["id"]] == ["b1", "custom", "b2"]


def test_response_for_one_id_never_wakes_another_waiter(
    bridge_factory: Callable[..., SpkUpdaterBridge],
) -> None:
    """慢请求的响应不会唤醒另一个 id 的等待者。"""
    bridge = bridge_factory()
    bridge.ensure_started()
    slow_result: dict[str, Any] = {}

    def slow() -> None:
        slow_result["response"] = bridge.request(
            "check",
            {"delay": 0.45, "echo": "slow"},
            timeout=5.0,
            request_id="slow",
        )

    worker = threading.Thread(target=slow)
    worker.start()
    time.sleep(0.05)

    started = time.monotonic()
    fast = bridge.request(
        "check",
        {"echo": "fast"},
        timeout=2.0,
        request_id="fast",
    )
    fast_elapsed = time.monotonic() - started

    worker.join(timeout=5.0)
    assert not worker.is_alive()
    assert fast["id"] == "fast"
    assert fast["result"]["echo"] == "fast"
    assert fast_elapsed < 0.35, "fast id 不应等待 slow id 的延迟"
    assert slow_result["response"]["id"] == "slow"
    assert slow_result["response"]["result"]["echo"] == "slow"


def test_interleaved_concurrent_writes_keep_responses_correlated(
    bridge_factory: Callable[..., SpkUpdaterBridge],
) -> None:
    """多线程交错写 stdin 时，每个等待者只收到自己的响应。"""
    bridge = bridge_factory()
    bridge.ensure_started()
    count = 16
    barrier = threading.Barrier(count)
    results: dict[str, dict[str, Any]] = {}
    failures: list[BaseException] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        request_id = f"m{index}"
        try:
            barrier.wait(timeout=5.0)
            response = bridge.request(
                "check",
                {"delay": 0.01 * (index % 3), "echo": f"value-{index}"},
                timeout=10.0,
                request_id=request_id,
            )
            with lock:
                results[request_id] = response
        except BaseException as exc:  # noqa: BLE001 - 测试收集所有异常
            with lock:
                failures.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10.0)

    assert not failures, f"并发请求失败: {failures!r}"
    assert len(results) == count
    for index in range(count):
        request_id = f"m{index}"
        assert results[request_id]["id"] == request_id
        assert results[request_id]["result"]["echo"] == f"value-{index}"


def test_verify_is_a_convenience_wrapper(
    bridge_factory: Callable[..., SpkUpdaterBridge],
) -> None:
    """verify 走同一条请求/响应关联路径。"""
    bridge = bridge_factory()
    bridge.ensure_started()
    digest = "a" * 64

    response = bridge.verify({"path": "C:\\tmp\\installer.exe", "sha256": digest})

    assert response["ok"] is True
    assert response["result"]["match"] is True
    assert response["result"]["actual"] == digest


def test_concurrent_check_and_verify_keep_their_own_responses(
    bridge_factory: Callable[..., SpkUpdaterBridge],
) -> None:
    """check 与 verify 并发（不同 id）时响应不串台。"""
    bridge = bridge_factory()
    bridge.ensure_started()
    barrier = threading.Barrier(2)
    results: dict[str, dict[str, Any]] = {}
    failures: list[BaseException] = []
    lock = threading.Lock()
    digest = "b" * 64

    def run_check() -> None:
        try:
            barrier.wait(timeout=5.0)
            response = bridge.request(
                "check",
                {"delay": 0.2, "echo": "check-echo"},
                timeout=5.0,
                request_id="check-concurrent",
            )
            with lock:
                results["check"] = response
        except BaseException as exc:  # noqa: BLE001 - 测试收集所有异常
            with lock:
                failures.append(exc)

    def run_verify() -> None:
        try:
            barrier.wait(timeout=5.0)
            response = bridge.verify(
                {
                    "path": "C:\\tmp\\installer.exe",
                    "sha256": digest,
                    "delay": 0.2,
                },
                request_id="verify-concurrent",
            )
            with lock:
                results["verify"] = response
        except BaseException as exc:  # noqa: BLE001 - 测试收集所有异常
            with lock:
                failures.append(exc)

    threads = [
        threading.Thread(target=run_check, name="concurrent-check"),
        threading.Thread(target=run_verify, name="concurrent-verify"),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10.0)

    assert not failures, f"并发 check/verify 失败: {failures!r}"
    assert all(not thread.is_alive() for thread in threads)
    assert results["check"]["id"] == "check-concurrent"
    assert results["check"]["result"]["echo"] == "check-echo"
    assert "match" not in results["check"]["result"]
    assert results["verify"]["id"] == "verify-concurrent"
    assert results["verify"]["result"]["match"] is True
    assert results["verify"]["result"]["actual"] == digest
    assert "echo" not in results["verify"]["result"]


def test_check_and_verify_use_45_second_default_timeout(
    bridge_factory: Callable[..., SpkUpdaterBridge],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """check/verify 的默认 timeout 是 45 秒。"""
    bridge = bridge_factory()
    captured: list[tuple[str, float | None, str | None]] = []

    def fake_request(
        cmd: str,
        params: Any = None,
        timeout: float | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        captured.append((cmd, timeout, request_id))
        return {"ok": True}

    monkeypatch.setattr(bridge, "request", fake_request)

    bridge.check({"a": 1}, request_id="c1")
    bridge.verify({"b": 2})

    assert captured == [
        ("check", DEFAULT_CHECK_TIMEOUT, "c1"),
        ("verify", DEFAULT_CHECK_TIMEOUT, None),
    ]
    assert DEFAULT_CHECK_TIMEOUT == 45.0


# =============================================================================
# 并发启动 / 关闭
# =============================================================================
def test_concurrent_ensure_started_spawns_exactly_one_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """多个线程同时 ensure_started 只 spawn 一次。"""
    bridge = SpkUpdaterBridge(command=_fake_command())
    real_popen = subprocess.Popen
    spawn_count: list[int] = []
    count_lock = threading.Lock()

    def counting_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[str]:
        with count_lock:
            spawn_count.append(1)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(bridge_module.subprocess, "Popen", counting_popen)
    count = 8
    barrier = threading.Barrier(count)
    outcomes: list[bool] = []
    failures: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            barrier.wait(timeout=5.0)
            outcome = bridge.ensure_started()
            with lock:
                outcomes.append(outcome)
        except BaseException as exc:  # noqa: BLE001 - 测试收集所有异常
            with lock:
                failures.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10.0)

    try:
        assert not failures, f"并发启动失败: {failures!r}"
        assert len(spawn_count) == 1, f"期望只 spawn 一次，实际 {len(spawn_count)}"
        assert outcomes == [True] * count
        assert bridge.is_running() is True
    finally:
        bridge.close()


def test_close_is_idempotent_and_reaps_the_process(
    bridge_factory: Callable[..., SpkUpdaterBridge],
) -> None:
    """close 可重复调用，且结束后 poll() 非 None。"""
    bridge = bridge_factory()
    bridge.ensure_started()
    process = bridge._process  # noqa: SLF001 - 断言子进程回收
    assert process is not None

    bridge.close()
    bridge.close()

    assert process.poll() is not None
    assert bridge.is_running() is False


# =============================================================================
# 超时 / 崩溃 / 畸形行 / stderr
# =============================================================================
def test_request_timeout_cleans_only_that_waiter(
    bridge_factory: Callable[..., SpkUpdaterBridge],
) -> None:
    """请求超时只清理自身等待者，进程继续服务。"""
    bridge = bridge_factory()
    bridge.ensure_started()

    with pytest.raises(UpdaterBridgeError) as excinfo:
        bridge.request(
            "check",
            {"delay": 0.6},
            timeout=0.15,
            request_id="slow-timeout",
        )
    assert excinfo.value.code == "timeout"
    assert bridge.is_running() is True

    response = bridge.request("hello", timeout=2.0, request_id="after-timeout")
    assert response["ok"] is True
    assert response["id"] == "after-timeout"

    # 让慢响应真正到达；它属于已超时的 id，只能被静默丢弃。
    time.sleep(0.65)
    again = bridge.request("hello", timeout=2.0, request_id="still-alive")
    assert again["ok"] is True


def test_crash_wakes_all_waiters_with_bounded_stderr_tail(
    bridge_factory: Callable[..., SpkUpdaterBridge],
) -> None:
    """崩溃时所有等待者都被唤醒，异常带退出码与 stderr 尾部。"""
    bridge = bridge_factory()
    bridge.ensure_started()
    errors: list[UpdaterBridgeError] = []
    lock = threading.Lock()

    def slow(request_id: str) -> None:
        try:
            bridge.request(
                "check",
                {"delay": 5.0},
                timeout=10.0,
                request_id=request_id,
            )
        except UpdaterBridgeError as exc:
            with lock:
                errors.append(exc)

    threads = [
        threading.Thread(target=slow, args=(request_id,))
        for request_id in ("slow-1", "slow-2")
    ]
    for thread in threads:
        thread.start()
    time.sleep(0.15)

    with pytest.raises(UpdaterBridgeError) as excinfo:
        bridge.request(
            "check",
            {"crash": True},
            timeout=5.0,
            request_id="crash",
        )
    errors.append(excinfo.value)

    for thread in threads:
        thread.join(timeout=5.0)
        assert not thread.is_alive()

    assert len(errors) == 3
    for error in errors:
        assert error.code == "process_exited"
        assert error.exit_code == 3
        assert "stderr tail marker" in (error.stderr_tail or "")
        assert "process_exited" in str(error)

    assert bridge.is_running() is False
    assert bridge.stop() is True


def test_malformed_json_line_is_skipped_and_later_response_resolves(
    bridge_factory: Callable[..., SpkUpdaterBridge],
) -> None:
    """畸形行被跳过，其后的合法响应仍能解析。"""
    bridge = bridge_factory()
    bridge.ensure_started()

    response = bridge.request(
        "check",
        {"bad_json": True, "echo": "after-bad-line"},
        timeout=5.0,
        request_id="bad-json",
    )

    assert response["ok"] is True
    assert response["id"] == "bad-json"
    assert response["result"]["echo"] == "after-bad-line"

    hello = bridge.request("hello", timeout=2.0)
    assert hello["ok"] is True


def test_one_mib_stderr_flood_does_not_deadlock_and_keeps_bounded_tail(
    bridge_factory: Callable[..., SpkUpdaterBridge],
) -> None:
    """1 MiB stderr 洪泛时 stdout 仍可继续，尾部保持有界。"""
    bridge = bridge_factory()
    bridge.ensure_started()

    response = bridge.request(
        "check",
        {"stderr_flood": 1024 * 1024},
        timeout=15.0,
        request_id="flood",
    )

    assert response["ok"] is True
    assert bridge.is_running() is True
    assert len(bridge.stderr_tail) <= STDERR_TAIL_BYTES
    follow_up = bridge.request("hello", timeout=2.0)
    assert follow_up["ok"] is True


def test_utf8_chinese_round_trip(
    bridge_factory: Callable[..., SpkUpdaterBridge],
) -> None:
    """UTF-8 中文参数与结果往返不损坏。"""
    bridge = bridge_factory()
    bridge.ensure_started()
    text = "中文预览 · 文件校验 ✓"

    response = bridge.request(
        "check",
        {"echo": text},
        timeout=5.0,
        request_id="utf8",
    )

    assert response["result"]["echo"] == text


def test_request_after_abrupt_exit_raises_bridge_error(
    bridge_factory: Callable[..., SpkUpdaterBridge],
) -> None:
    """进程被直接杀死后，后续请求抛出结构化错误而非挂起。"""
    bridge = bridge_factory()
    bridge.ensure_started()
    process = bridge._process  # noqa: SLF001 - 模拟外部崩溃
    assert process is not None

    process.kill()
    process.wait(timeout=5.0)
    assert _wait_for(lambda: not bridge.is_running(), timeout=3.0)

    with pytest.raises(UpdaterBridgeError) as excinfo:
        bridge.request("hello", timeout=2.0)

    assert excinfo.value.code in {"not_running", "process_exited", "write_failed"}


# =============================================================================
# stop / close 预算
# =============================================================================
def test_stop_unstarted_returns_true_immediately(
    bridge_factory: Callable[..., SpkUpdaterBridge],
) -> None:
    """未启动的桥 stop() 立即返回 True 且不创建进程。"""
    bridge = bridge_factory()

    started = time.monotonic()
    assert bridge.stop() is True
    elapsed = time.monotonic() - started

    assert elapsed < 0.2
    assert bridge._process is None  # noqa: SLF001
    assert bridge.is_running() is False


def test_stop_is_a_total_budget_even_when_shutdown_never_acks(
    bridge_factory: Callable[..., SpkUpdaterBridge],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """忽略 shutdown 的假边车必须被 terminate/kill 回收。"""
    bridge = bridge_factory(env={"SPK_FAKE_IGNORE_SHUTDOWN": "1"})
    bridge.ensure_started()
    process = bridge._process  # noqa: SLF001 - 断言 terminate 分支
    assert process is not None

    terminate_calls: list[bool] = []
    real_terminate = subprocess.Popen.terminate

    def recording_terminate(self: subprocess.Popen[str]) -> None:
        terminate_calls.append(self.poll() is None)
        real_terminate(self)

    monkeypatch.setattr(subprocess.Popen, "terminate", recording_terminate)

    # 直接发一条 shutdown：假边车必须不 ack、不退出，进程仍存活。
    with pytest.raises(UpdaterBridgeError) as excinfo:
        bridge.request(
            "shutdown",
            timeout=0.25,
            request_id="ignored-shutdown",
        )
    assert excinfo.value.code == "timeout"
    time.sleep(0.05)
    assert process.poll() is None, "忽略 shutdown 时假边车不应退出"
    assert bridge.is_running() is True

    started = time.monotonic()
    assert bridge.stop(1.2) is True
    elapsed = time.monotonic() - started

    assert terminate_calls == [True], "stop 必须在进程仍存活时调用 terminate"
    assert elapsed < 1.9, f"stop 超出总预算: {elapsed:.3f}s"
    assert process.poll() is not None, "stop 必须回收进程"
    assert bridge.is_running() is False
    assert bridge._process is None  # noqa: SLF001


def test_stop_responsive_child_is_fast(
    bridge_factory: Callable[..., SpkUpdaterBridge],
) -> None:
    """正常边车会先 ack shutdown，stop 很快完成。"""
    bridge = bridge_factory()
    bridge.ensure_started()

    started = time.monotonic()
    assert bridge.stop(4.0) is True
    elapsed = time.monotonic() - started

    assert elapsed < 3.0
    assert bridge.is_running() is False


# =============================================================================
# 假边车的未来下载契约（Todo 9/21 依赖）
# =============================================================================
def test_fake_download_done_renames_part_and_deletes_meta(
    bridge_factory: Callable[..., SpkUpdaterBridge],
    tmp_path: Path,
) -> None:
    """done：原子改名到 dest 并删除 .part / .part.json。"""
    bridge = bridge_factory()
    bridge.ensure_started()
    dest = tmp_path / "Sopeek_Setup.exe"
    body = b"installer-body-" * 1000
    digest = hashlib.sha256(body).hexdigest()

    response = bridge.request(
        "download",
        {
            "dest_path": str(dest),
            "body": body.decode("ascii"),
            "expected_sha256": digest,
            "expected_size": len(body),
        },
        timeout=10.0,
        request_id="d-done",
    )

    assert response["ok"] is True
    assert response["result"]["state"] == "done"
    assert response["result"]["sha256"] == digest
    assert dest.read_bytes() == body
    assert not Path(str(dest) + ".part").exists()
    assert not Path(str(dest) + ".part.json").exists()


def test_fake_download_pause_retains_part_and_meta(
    bridge_factory: Callable[..., SpkUpdaterBridge],
    tmp_path: Path,
) -> None:
    """paused：保留 .part 与 .part.json，并拒绝不匹配 target 的控制。"""
    bridge = bridge_factory()
    bridge.ensure_started()
    dest = tmp_path / "Sopeek_Setup.exe"
    part = Path(str(dest) + ".part")
    meta = Path(str(dest) + ".part.json")
    body_size = 1024 * 1024
    outcome: dict[str, Any] = {}

    def download() -> None:
        try:
            outcome["response"] = bridge.request(
                "download",
                {
                    "dest_path": str(dest),
                    "body_size": body_size,
                    "expected_size": body_size,
                    "chunk_size": 4 * 1024,
                    "chunk_delay": 0.01,
                },
                timeout=15.0,
                request_id="d-pause",
            )
        except BaseException as exc:  # noqa: BLE001 - 测试收集所有异常
            outcome["error"] = exc

    worker = threading.Thread(target=download)
    worker.start()
    assert _wait_for(part.exists, timeout=3.0), "下载未创建 .part"

    stale = bridge.request(
        "pause",
        {"target": "not-the-download"},
        timeout=5.0,
        request_id="p-stale",
    )
    assert stale["result"]["accepted"] is False

    ack = bridge.request(
        "pause",
        {"target": "d-pause"},
        timeout=5.0,
        request_id="p-real",
    )
    assert ack["result"]["accepted"] is True

    worker.join(timeout=10.0)
    assert not worker.is_alive()
    assert "error" not in outcome, outcome.get("error")
    assert outcome["response"]["result"]["state"] == "paused"
    assert part.exists(), "paused 必须保留 .part"
    assert meta.exists(), "paused 必须保留 .part.json"


# =============================================================================
# Todo 8 — 下载事件流 / 暂停 / 取消 / 关闭 / 重启
# =============================================================================
class _RecordingLock:
    """记录被获取次数的锁包装，用于断言 ensure=False 不取生命周期锁。"""

    def __init__(self, real: Any) -> None:
        self._real = real
        self.used = 0

    def acquire(self, *args: Any, **kwargs: Any) -> bool:
        self.used += 1
        return bool(self._real.acquire(*args, **kwargs))

    def release(self) -> None:
        self._real.release()

    def __enter__(self) -> Any:
        self.used += 1
        return self._real.__enter__()

    def __exit__(self, *exc: Any) -> Any:
        return self._real.__exit__(*exc)


def _download_params(
    dest: Path,
    *,
    body_size: int = 1024 * 1024,
    chunk_size: int = 4096,
    chunk_delay: float = 0.01,
) -> dict[str, Any]:
    """构造假边车下载参数（默认足够慢，便于中途暂停/取消）。"""
    return {
        "dest_path": str(dest),
        "body_size": body_size,
        "expected_size": body_size,
        "chunk_size": chunk_size,
        "chunk_delay": chunk_delay,
    }


def _fast_download_params(dest: Path) -> dict[str, Any]:
    """构造立即完成的下载参数。"""
    return {
        "dest_path": str(dest),
        "body_size": 64 * 1024,
        "expected_size": 64 * 1024,
        "chunk_size": 64 * 1024,
    }


def test_download_begin_returns_immediately_with_verbatim_id(
    bridge_factory: Callable[..., SpkUpdaterBridge],
    tmp_path: Path,
) -> None:
    """begin 写行后立即返回；request_id 原样出现在事件与终态中。"""
    bridge = bridge_factory()
    bridge.ensure_started()
    dest = tmp_path / "setup.exe"
    events: list[dict[str, Any]] = []
    request_id = "svc-download-中文-42"

    started = time.monotonic()
    bridge.download_begin(
        _download_params(dest),
        events.append,
        request_id,
    )
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, f"download_begin 不应等待终态: {elapsed:.3f}s"
    response = bridge.download_wait(request_id, timeout=20.0)

    assert response["id"] == request_id
    assert response["result"]["state"] == "done"
    assert dest.exists()
    assert events, "应至少收到一条事件"
    assert all(event["id"] == request_id for event in events)


def test_download_events_are_ordered_and_progress_is_monotonic(
    bridge_factory: Callable[..., SpkUpdaterBridge],
    tmp_path: Path,
) -> None:
    """download() 兼容包装按到达顺序回调事件，进度单调不减。"""
    bridge = bridge_factory()
    dest = tmp_path / "events.exe"
    events: list[dict[str, Any]] = []

    response = bridge.download(
        {
            "dest_path": str(dest),
            "body_size": 512 * 1024,
            "expected_size": 512 * 1024,
            "chunk_size": 64 * 1024,
            "chunk_delay": 0.002,
        },
        events.append,
        "evt-download",
        timeout=15.0,
    )

    assert response["id"] == "evt-download"
    assert response["result"]["state"] == "done"
    states = [
        event.get("state")
        for event in events
        if event.get("event") == "state"
    ]
    assert "resolving" in states
    assert "downloading" in states
    assert states.index("resolving") < states.index("downloading")
    progress = [
        int(event["downloaded"])
        for event in events
        if event.get("event") == "progress"
    ]
    assert len(progress) >= 3, f"进度事件不足: {progress!r}"
    assert progress == sorted(progress), f"进度必须单调: {progress!r}"
    assert progress[-1] == 512 * 1024


def test_download_event_callback_exception_does_not_kill_reader(
    bridge_factory: Callable[..., SpkUpdaterBridge],
    tmp_path: Path,
) -> None:
    """回调抛异常被捕获，读线程继续派发并收到终态。"""
    bridge = bridge_factory()
    dest = tmp_path / "callback.exe"
    seen: list[dict[str, Any]] = []

    def exploding(event: dict[str, Any]) -> None:
        seen.append(event)
        raise RuntimeError("callback boom")

    response = bridge.download(
        _fast_download_params(dest),
        exploding,
        "evt-boom",
        timeout=10.0,
    )

    assert response["result"]["state"] == "done"
    assert seen, "回调应至少被调用一次"
    assert bridge.is_running() is True
    assert bridge.request("hello", timeout=2.0)["ok"] is True


def test_pause_ack_id_is_request_id_and_terminal_state_is_paused(
    bridge_factory: Callable[..., SpkUpdaterBridge],
    tmp_path: Path,
) -> None:
    """pause 的 ack id 是控制请求 id；随后终态为 paused 且保留工件。"""
    bridge = bridge_factory()
    dest = tmp_path / "paused.exe"
    part = Path(str(dest) + ".part")
    meta = Path(str(dest) + ".part.json")
    progress_seen = threading.Event()

    def on_event(event: dict[str, Any]) -> None:
        if event.get("event") == "progress":
            progress_seen.set()

    bridge.download_begin(
        _download_params(dest),
        on_event,
        "d-pause-ack",
    )
    assert progress_seen.wait(timeout=5.0), "下载未产生进度事件"

    stale = bridge.pause("not-the-download")
    assert stale["result"]["accepted"] is False
    assert stale["id"] != "d-pause-ack"

    ack = bridge.pause("d-pause-ack")
    assert ack["id"] != "d-pause-ack", "ack id 不得等于 target"
    assert ack["id"] == "b2", f"ack 应使用控制请求自动 id: {ack['id']}"
    assert ack["result"]["accepted"] is True

    response = bridge.download_wait("d-pause-ack", timeout=10.0)
    assert response["id"] == "d-pause-ack"
    assert response["result"]["state"] == "paused"
    assert part.exists(), "paused 必须保留 .part"
    assert meta.exists(), "paused 必须保留 .part.json"


def test_cancel_ack_id_is_request_id_and_terminal_state_is_cancelled(
    bridge_factory: Callable[..., SpkUpdaterBridge],
    tmp_path: Path,
) -> None:
    """cancel 的 ack id 是控制请求 id；随后终态为 cancelled 并删除工件。"""
    bridge = bridge_factory()
    dest = tmp_path / "cancelled.exe"
    part = Path(str(dest) + ".part")
    meta = Path(str(dest) + ".part.json")
    progress_seen = threading.Event()

    def on_event(event: dict[str, Any]) -> None:
        if event.get("event") == "progress":
            progress_seen.set()

    bridge.download_begin(
        _download_params(dest),
        on_event,
        "d-cancel-ack",
    )
    assert progress_seen.wait(timeout=5.0), "下载未产生进度事件"

    ack = bridge.cancel("d-cancel-ack")
    assert ack["id"] != "d-cancel-ack", "ack id 不得等于 target"
    assert ack["result"]["accepted"] is True

    response = bridge.download_wait("d-cancel-ack", timeout=10.0)
    assert response["id"] == "d-cancel-ack"
    assert response["result"]["state"] == "cancelled"
    assert not part.exists(), "cancel 必须删除 .part"
    assert not meta.exists(), "cancel 必须删除 .part.json"


def test_second_download_begin_raises_busy_without_overwriting_first(
    bridge_factory: Callable[..., SpkUpdaterBridge],
    tmp_path: Path,
) -> None:
    """同一时刻只允许一个活动下载；终态后预留被释放。"""
    bridge = bridge_factory()
    first_dest = tmp_path / "first.exe"
    second_dest = tmp_path / "second.exe"

    bridge.download_begin(
        _download_params(first_dest),
        None,
        "d-first",
    )
    with pytest.raises(UpdaterBridgeError) as excinfo:
        bridge.download_begin(
            _fast_download_params(second_dest),
            None,
            "d-second",
        )

    assert excinfo.value.code == "busy"
    assert not second_dest.exists()

    ack = bridge.cancel("d-first")
    assert ack["result"]["accepted"] is True
    first = bridge.download_wait("d-first", timeout=10.0)
    assert first["result"]["state"] == "cancelled"

    bridge.download_begin(
        _fast_download_params(second_dest),
        None,
        "d-second",
    )
    second = bridge.download_wait("d-second", timeout=10.0)
    assert second["result"]["state"] == "done"


def test_download_begin_ensure_false_skips_ensure_and_lifecycle_lock(
    bridge_factory: Callable[..., SpkUpdaterBridge],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ensure=False 已预启动场景：不调用 ensure_started、不取生命周期锁。"""
    bridge = bridge_factory()
    bridge.ensure_started()
    dest = tmp_path / "ensure-false.exe"
    real_lock = bridge._lifecycle_lock  # noqa: SLF001 - 断言锁未使用
    tracker = _RecordingLock(real_lock)

    def forbidden_ensure() -> bool:
        raise AssertionError("ensure=False 不得调用 ensure_started")

    monkeypatch.setattr(bridge, "ensure_started", forbidden_ensure)
    bridge._lifecycle_lock = tracker  # noqa: SLF001
    try:
        bridge.download_begin(
            _fast_download_params(dest),
            None,
            "d-ensure-false",
            ensure=False,
        )
        response = bridge.download_wait("d-ensure-false", timeout=10.0)
    finally:
        bridge._lifecycle_lock = real_lock  # noqa: SLF001

    assert response["result"]["state"] == "done"
    assert tracker.used == 0, "ensure=False 不得获取 _lifecycle_lock"


def test_download_begin_ensure_failure_leaves_no_reservation(
    bridge_factory: Callable[..., SpkUpdaterBridge],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ensure 失败时不留下终态队列/回调/活动下载预留。"""
    bridge = bridge_factory()

    def failing_ensure() -> bool:
        raise UpdaterBridgeError("unavailable", "fake missing")

    monkeypatch.setattr(bridge, "ensure_started", failing_ensure)

    with pytest.raises(UpdaterBridgeError) as excinfo:
        bridge.download_begin(
            _fast_download_params(tmp_path / "ensure-fail.exe"),
            None,
            "d-ensure-fail",
        )

    assert excinfo.value.code == "unavailable"
    assert bridge._download_terminals == {}  # noqa: SLF001
    assert bridge._download_callbacks == {}  # noqa: SLF001
    assert bridge._active_download_id is None  # noqa: SLF001


def test_cancel_event_without_terminal_stops_and_raises_abort(
    bridge_factory: Callable[..., SpkUpdaterBridge],
    tmp_path: Path,
) -> None:
    """cancel_event 置位后 2s 无终态：stop(1.0) 并抛 cancelled(abort=True)。"""
    bridge = bridge_factory()
    dest = tmp_path / "abort.exe"
    part = Path(str(dest) + ".part")
    cancel = threading.Event()
    outcome: dict[str, Any] = {}

    bridge.download_begin(
        _download_params(dest, chunk_delay=0.02),
        None,
        "d-abort",
    )
    assert _wait_for(part.exists, timeout=3.0), "下载未创建 .part"

    def wait() -> None:
        try:
            outcome["response"] = bridge.download_wait(
                "d-abort",
                timeout=None,
                cancel_event=cancel,
            )
        except BaseException as exc:  # noqa: BLE001 - 测试收集所有异常
            outcome["error"] = exc

    worker = threading.Thread(target=wait)
    worker.start()
    time.sleep(0.1)
    started = time.monotonic()
    cancel.set()
    worker.join(timeout=8.0)
    elapsed = time.monotonic() - started

    assert not worker.is_alive()
    assert "response" not in outcome
    error = outcome["error"]
    assert isinstance(error, UpdaterBridgeError)
    assert error.code == "cancelled"
    assert error.abort is True
    assert elapsed < 3.5, f"取消中止超出宽限: {elapsed:.3f}s"
    assert bridge.is_running() is False


def test_download_wait_timeout_keeps_active_reservation(
    bridge_factory: Callable[..., SpkUpdaterBridge],
    tmp_path: Path,
) -> None:
    """调用方总超时只抛错，不释放仍在运行的下载预留。"""
    bridge = bridge_factory()
    dest = tmp_path / "timeout-keep.exe"
    request_id = "d-timeout-keep"

    bridge.download_begin(
        _download_params(dest, chunk_delay=0.02),
        None,
        request_id,
    )
    with pytest.raises(UpdaterBridgeError) as excinfo:
        bridge.download_wait(request_id, timeout=0.05)

    assert excinfo.value.code == "timeout"
    assert bridge._active_download_id == request_id  # noqa: SLF001
    assert request_id in bridge._download_terminals  # noqa: SLF001
    assert request_id in bridge._download_callbacks  # noqa: SLF001
    assert request_id in bridge._download_activity  # noqa: SLF001

    with pytest.raises(UpdaterBridgeError) as busy:
        bridge.download_begin(
            _fast_download_params(tmp_path / "timeout-second.exe"),
            None,
            "d-timeout-second",
        )
    assert busy.value.code == "busy"

    ack = bridge.cancel(request_id)
    assert ack["result"]["accepted"] is True
    response = bridge.download_wait(request_id, timeout=10.0)
    assert response["id"] == request_id
    assert response["result"]["state"] == "cancelled"


def test_request_id_colliding_with_active_download_is_rejected(
    bridge_factory: Callable[..., SpkUpdaterBridge],
    tmp_path: Path,
) -> None:
    """普通请求不得占用活动下载 id，否则响应会被下载终态队列吞掉。"""
    bridge = bridge_factory()
    dest = tmp_path / "id-collision.exe"
    request_id = "d-id-collision"

    bridge.download_begin(
        _download_params(dest, chunk_delay=0.02),
        None,
        request_id,
    )
    with pytest.raises(UpdaterBridgeError) as excinfo:
        bridge.request("hello", timeout=2.0, request_id=request_id)

    assert excinfo.value.code == "duplicate_request_id"
    assert bridge._active_download_id == request_id  # noqa: SLF001

    ack = bridge.cancel(request_id)
    assert ack["result"]["accepted"] is True
    response = bridge.download_wait(request_id, timeout=10.0)
    assert response["result"]["state"] == "cancelled"


def test_active_close_wakes_download_waiter_and_reaps_process(
    bridge_factory: Callable[..., SpkUpdaterBridge],
    tmp_path: Path,
) -> None:
    """活动下载中 close() 不抛异常，唤醒等待者且不残留进程。"""
    bridge = bridge_factory()
    bridge.ensure_started()
    process = bridge._process  # noqa: SLF001 - 断言进程回收
    assert process is not None
    dest = tmp_path / "close-active.exe"
    part = Path(str(dest) + ".part")
    outcome: dict[str, Any] = {}

    bridge.download_begin(
        _download_params(dest),
        None,
        "d-close",
    )
    assert _wait_for(part.exists, timeout=3.0), "下载未创建 .part"

    def wait() -> None:
        try:
            outcome["response"] = bridge.download_wait(
                "d-close",
                timeout=None,
                idle_timeout=30.0,
            )
        except BaseException as exc:  # noqa: BLE001 - 测试收集所有异常
            outcome["error"] = exc

    worker = threading.Thread(target=wait)
    worker.start()
    bridge.close()
    worker.join(timeout=5.0)

    assert not worker.is_alive()
    assert "response" not in outcome
    error = outcome["error"]
    assert isinstance(error, UpdaterBridgeError)
    assert error.code == "process_exited"
    assert process.poll() is not None, "close 必须回收子进程"
    assert bridge.is_running() is False


def test_stop_then_ensure_started_hello_succeeds(
    bridge_factory: Callable[..., SpkUpdaterBridge],
) -> None:
    """stop 后 ensure_started 能重新拉起边车并继续 hello。"""
    bridge = bridge_factory()
    assert bridge.ensure_started() is True
    assert bridge.request("hello", timeout=5.0)["result"]["protocol"] == 1

    assert bridge.stop(4.0) is True
    assert bridge.is_running() is False

    assert bridge.ensure_started() is True
    hello = bridge.request("hello", timeout=5.0)
    assert hello["ok"] is True
    assert hello["result"]["protocol"] == 1
