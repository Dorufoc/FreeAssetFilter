# -*- coding: utf-8 -*-
"""``UpdateService`` 与 ``version_info`` 的可观察契约测试。

覆盖 Rust native updater Todo 9：检查去重、单飞下载、暂停/恢复、取消、
缓存校验、错误映射、线程池与单例生命周期。测试坚持从公开信号和公开方法
观察行为，不依赖 Rust DLL 或真实 updater 子进程。
"""

from __future__ import annotations

import json
from dataclasses import fields
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from PySide6.QtCore import QCoreApplication, QThreadPool
from PySide6.QtTest import QSignalSpy

from sopeek.core.managers import settings_manager_v2 as settings_manager_module
from sopeek.core.native.bridges.spk_updater_bridge import UpdaterBridgeError
from sopeek.services import update_service as update_service_module
from sopeek.services import update_startup
from sopeek.services.update_service import (
    ERROR_MESSAGES,
    RETRYABLE_CODES,
    UpdateError,
    UpdateInfo,
    UpdateService,
    get_update_service,
    get_update_service_if_exists,
    sanitize_asset_name,
)
from sopeek.utils import version_info
from sopeek.utils.version_info import RELEASES_URL

pytestmark = pytest.mark.unit

MIB = 1024 * 1024
SHA = "a" * 64
_UNSET = object()


def _available_check_response(tag: str | None = "v1.0.1") -> dict[str, Any]:
    """构造一个可用的更新检查响应；``tag=None`` 时省略 tag。"""
    remote: dict[str, Any] = {"version": "v1.0.1", "date": "2026-06-01"}
    if tag is not None:
        remote["tag"] = tag
    return {
        "ok": True,
        "result": {
            "update_available": True,
            "reason": "newer_version",
            "local": {"version": "1.0.0-alpha.5", "date": "2026-05-22"},
            "remote": remote,
            "asset": {
                "name": "Setup.exe",
                "size": 10,
                "sha256": SHA,
                "download_url": "https://example.com/Setup.exe",
            },
            "skipped_newer_tag": None,
        },
    }


def _pump_until(predicate: Callable[[], bool], timeout: float = 6.0) -> bool:
    """轮询 Qt 事件循环直到条件成立或超时。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    QCoreApplication.processEvents()
    return bool(predicate())


def _pump(seconds: float = 0.08) -> None:
    """短暂驱动事件循环。"""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)


def _info(
    *,
    name: str = "Sopeek_Setup.exe",
    sha256: str | None = SHA,
    size: object = 4096,
    url: str = "https://example.com/Sopeek_Setup.exe",
    version: str = "v1.0.1",
) -> UpdateInfo:
    """构造一个下载用 UpdateInfo。"""
    asset = {"name": name, "size": size, "sha256": sha256, "download_url": url}
    return UpdateInfo(
        local_version="1.0.0-alpha.5",
        local_date="2026-05-22",
        update_available=True,
        reason="newer_version",
        skipped_newer_tag=None,
        remote={"version": version, "date": "2026-06-01"},
        asset=asset,  # type: ignore[arg-type]
    )


class FakeBridge:
    """可控的 updater bridge 替身；所有阻塞点都可释放。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.available = True
        self.ensure_started_error: BaseException | None = None
        self.ensure_gate: threading.Event | None = None
        self.ensure_entered = threading.Event()
        self.ensure_calls = 0
        self.ensure_threads: list[threading.Thread] = []

        self.check_response: dict[str, Any] = {
            "ok": True,
            "result": {
                "update_available": False,
                "reason": "none",
                "local": {"version": "1.0.0-alpha.5", "date": "2026-05-22"},
                "remote": {},
                "asset": None,
                "skipped_newer_tag": None,
            },
        }
        self.check_error: BaseException | None = None
        self.check_gate: threading.Event | None = None
        self.check_entered = threading.Event()
        self.check_calls: list[dict[str, Any]] = []
        self.check_threads: list[threading.Thread] = []

        self.begin_error: BaseException | None = None
        self.begin_gate: threading.Event | None = None
        self.begin_entered = threading.Event()
        self.begin_calls: list[dict[str, Any]] = []
        self.callbacks: dict[str, Callable[[dict[str, Any]], None]] = {}
        self.last_begin_params: dict[str, Any] = {}

        self.wait_error: BaseException | None = None
        self.wait_gate: threading.Event | None = None
        self.wait_entered = threading.Event()
        self.wait_calls: list[tuple[str, threading.Event | None]] = []
        self.terminal_state = "done"
        self.wait_threads: list[threading.Thread] = []

        self.pause_response: dict[str, Any] = {"ok": True, "result": {"accepted": True}}
        self.pause_error: BaseException | None = None
        self.pause_gate: threading.Event | None = None
        self.pause_entered = threading.Event()
        self.pause_calls: list[str] = []

        self.cancel_response: dict[str, Any] = {"ok": True, "result": {"accepted": True}}
        self.cancel_error: BaseException | None = None
        self.cancel_gate: threading.Event | None = None
        self.cancel_entered = threading.Event()
        self.cancel_calls: list[str] = []

        self.verify_response: dict[str, Any] = {
            "ok": True,
            "result": {"match": True, "volume_serial": 1, "file_index": 2},
        }
        self.verify_error: BaseException | None = None
        self.verify_gate: threading.Event | None = None
        self.verify_entered = threading.Event()
        self.verify_calls: list[dict[str, Any]] = []
        self.verify_threads: list[threading.Thread] = []

        self.stop_result = True
        self.stop_calls: list[float] = []
        self.close_calls = 0
        self.wait_exited_calls: list[tuple[float, bool]] = []
        self.wait_exited_result = True
        self.wait_exited_gate: threading.Event | None = None

    def release_all(self) -> None:
        """释放所有测试阻塞点，避免 teardown 留活线程。"""
        for gate in (
            self.ensure_gate,
            self.check_gate,
            self.begin_gate,
            self.wait_gate,
            self.pause_gate,
            self.cancel_gate,
            self.verify_gate,
            self.wait_exited_gate,
        ):
            if gate is not None:
                gate.set()

    def is_available(self) -> bool:
        """返回可配置的可用性。"""
        return self.available

    def ensure_started(self) -> bool:
        """记录并可选阻塞 ensure_started。"""
        with self._lock:
            self.ensure_calls += 1
            self.ensure_threads.append(threading.current_thread())
        self.ensure_entered.set()
        if self.ensure_gate is not None:
            self.ensure_gate.wait(6)
        if self.ensure_started_error is not None:
            raise self.ensure_started_error
        return True

    def check(self, params: dict[str, Any], request_id: str | None = None) -> dict[str, Any]:
        """记录 check 参数并返回预设响应。"""
        with self._lock:
            self.check_calls.append(dict(params))
            self.check_threads.append(threading.current_thread())
            if request_id is not None:
                self.callbacks[request_id] = lambda event: None
        self.check_entered.set()
        if self.check_gate is not None:
            self.check_gate.wait(6)
        if self.check_error is not None:
            raise self.check_error
        return self.check_response

    def download_begin(
        self,
        params: dict[str, Any],
        on_event: Callable[[dict[str, Any]], None],
        request_id: str | None = None,
        *,
        ensure: bool = True,
    ) -> dict[str, Any]:
        """记录 begin 参数与事件回调。"""
        rid = request_id or f"fake-{len(self.begin_calls) + 1}"
        with self._lock:
            self.begin_calls.append(
                {
                    "params": dict(params),
                    "request_id": rid,
                    "ensure": ensure,
                    "thread": threading.current_thread(),
                }
            )
            self.callbacks[rid] = on_event
            self.last_begin_params = dict(params)
        self.begin_entered.set()
        if self.begin_gate is not None:
            self.begin_gate.wait(6)
        if self.begin_error is not None:
            raise self.begin_error
        return {"ok": True, "result": {}}

    def download_wait(
        self, request_id: str, cancel_event: threading.Event | None = None
    ) -> dict[str, Any]:
        """记录 wait；可阻塞并返回 done/paused/cancelled。"""
        with self._lock:
            self.wait_calls.append((request_id, cancel_event))
            self.wait_threads.append(threading.current_thread())
            params = dict(self.last_begin_params)
        self.wait_entered.set()
        if self.wait_gate is not None:
            self.wait_gate.wait(6)
        if self.wait_error is not None:
            raise self.wait_error
        dest = Path(str(params.get("dest_path", "")))
        result: dict[str, Any] = {
            "state": self.terminal_state,
            "path": str(dest),
            "downloaded": int(params.get("expected_size") or 0),
            "sha256": params.get("expected_sha256"),
        }
        if self.terminal_state == "done" and str(dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"native-updater-test")
            result["downloaded"] = len(b"native-updater-test")
        return {"ok": True, "result": result}

    def pause(self, target_id: str) -> dict[str, Any]:
        """记录并可选阻塞 pause。"""
        with self._lock:
            self.pause_calls.append(target_id)
        self.pause_entered.set()
        if self.pause_gate is not None:
            self.pause_gate.wait(6)
        if self.pause_error is not None:
            raise self.pause_error
        return self.pause_response

    def cancel(self, target_id: str) -> dict[str, Any]:
        """记录并可选阻塞 cancel。"""
        with self._lock:
            self.cancel_calls.append(target_id)
        self.cancel_entered.set()
        if self.cancel_gate is not None:
            self.cancel_gate.wait(6)
        if self.cancel_error is not None:
            raise self.cancel_error
        return self.cancel_response

    def verify(self, params: dict[str, Any], request_id: str | None = None) -> dict[str, Any]:
        """记录 verify 参数与调用线程。"""
        with self._lock:
            self.verify_calls.append(dict(params))
            self.verify_threads.append(threading.current_thread())
        self.verify_entered.set()
        if self.verify_gate is not None:
            self.verify_gate.wait(6)
        if self.verify_error is not None:
            raise self.verify_error
        return self.verify_response

    def stop(self, timeout: float = 4.0) -> bool:
        """记录 stop 超时。"""
        self.stop_calls.append(float(timeout))
        return self.stop_result

    def close(self) -> None:
        """记录 close。"""
        self.close_calls += 1

    def wait_exited(self, timeout: float = 1.0) -> bool:
        """记录 wait_exited 调用，并保存调用瞬间产物是否存在。"""
        params = dict(self.last_begin_params)
        path = Path(str(params.get("dest_path", "")))
        self.wait_exited_calls.append((float(timeout), bool(str(path) and path.exists())))
        if self.wait_exited_gate is not None:
            self.wait_exited_gate.wait(6)
        return self.wait_exited_result


class Recorder:
    """收集 UpdateService 公开信号。"""

    def __init__(self, service: UpdateService) -> None:
        self.check_started: list[tuple[Any, ...]] = []
        self.check_finished: list[tuple[Any, ...]] = []
        self.download_started: list[tuple[Any, ...]] = []
        self.download_progress: list[tuple[Any, ...]] = []
        self.download_state_changed: list[tuple[Any, ...]] = []
        self.download_pause_acked: list[tuple[Any, ...]] = []
        self.download_finished: list[tuple[Any, ...]] = []
        self.download_failed: list[tuple[Any, ...]] = []
        self.startup_update_available: list[tuple[Any, ...]] = []

        service.check_started.connect(lambda *a: self.check_started.append(a))
        service.check_finished.connect(lambda *a: self.check_finished.append(a))
        service.download_started.connect(lambda *a: self.download_started.append(a))
        service.download_progress.connect(lambda *a: self.download_progress.append(a))
        service.download_state_changed.connect(lambda *a: self.download_state_changed.append(a))
        service.download_pause_acked.connect(lambda *a: self.download_pause_acked.append(a))
        service.download_finished.connect(lambda *a: self.download_finished.append(a))
        service.download_failed.connect(lambda *a: self.download_failed.append(a))
        service.startup_update_available.connect(lambda *a: self.startup_update_available.append(a))


@pytest.fixture(autouse=True)
def reset_update_service_singleton():
    """每个测试前后清空 UpdateService 单例。"""
    UpdateService._instance = None
    UpdateService._initialized = False
    yield
    instance = UpdateService._instance
    if instance is not None:
        try:
            instance.shutdown(timeout=0.2)
        except Exception:  # 清理阶段：服务可能已自行关闭
            pass
        try:
            instance.close()
        except Exception:  # 清理阶段：重复关闭必须无副作用
            pass
    UpdateService._instance = None
    UpdateService._initialized = False


@pytest.fixture(autouse=True)
def check_state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 24h 节流状态文件隔离到每个测试自己的临时路径。"""
    path = tmp_path / "startup-state" / "check_state.json"
    monkeypatch.setattr(update_startup, "check_state_path", lambda: path)
    return path


@pytest.fixture
def startup_setting(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """用可控假设置管理器替换 ``SettingsManagerV2``。"""
    holder: dict[str, Any] = {"value": True, "calls": 0}

    class FakeSettingsManager:
        """只实现 ``get`` 的假管理器。"""

        def get(self, key_path: str, default: Any = None) -> Any:
            holder["calls"] += 1
            value = holder["value"]
            return default if value is _UNSET else value

    monkeypatch.setattr(settings_manager_module, "SettingsManagerV2", FakeSettingsManager)
    return holder


@pytest.fixture
def appdata(tmp_path: Path) -> Path:
    """提供隔离的 app data 目录。"""
    path = tmp_path / "appdata"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def service_factory(qapp, tmp_path: Path, appdata: Path, monkeypatch: pytest.MonkeyPatch):
    """构造使用 FakeBridge 与临时 app data 的 UpdateService。"""
    monkeypatch.setattr(update_service_module, "get_app_data_path", lambda: appdata)
    created: list[tuple[UpdateService, FakeBridge]] = []

    def make(**overrides: Any) -> tuple[UpdateService, FakeBridge]:
        bridge = FakeBridge()
        for key, value in overrides.items():
            setattr(bridge, key, value)
        service = UpdateService(bridge_factory=lambda: bridge)
        created.append((service, bridge))
        return service, bridge

    yield make

    for service, bridge in created:
        bridge.release_all()
        try:
            service.shutdown(timeout=0.2)
        except Exception:  # 清理阶段：服务可能已自行关闭
            pass
        try:
            service.close()
        except Exception:  # 清理阶段：重复关闭必须无副作用
            pass


def _download_dir(appdata: Path) -> Path:
    """返回 UpdateService 约定的下载目录。"""
    return appdata / "download"


def _dest(appdata: Path, name: str) -> Path:
    """返回某个资产名的最终路径。"""
    return _download_dir(appdata) / name


def _start_blocked_download(
    service: UpdateService,
    bridge: FakeBridge,
    info: UpdateInfo,
) -> str:
    """启动一个阻塞在 download_wait 的下载并返回请求 id。"""
    bridge.wait_gate = threading.Event()
    request_id = service.start_download(info)
    assert bridge.wait_entered.wait(5), "download_wait 未进入"
    return request_id


def _suffixes(dest: Path) -> tuple[Path, Path]:
    """返回测试约定的 part/meta 路径。"""
    return dest.with_name(dest.name + ".part"), dest.with_name(dest.name + ".meta")


# =============================================================================
# version_info
# =============================================================================
class TestVersionInfo:
    """Local version and build-date parsing."""

    def test_reads_real_version_and_build_date(self) -> None:
        version = version_info.get_local_version()
        date = version_info.get_local_build_date()
        assert version == "1.0.0-alpha.5"
        assert date == "2026-05-22"
        assert version_info.RELEASES_URL == "https://github.com/Dorufoc/Sopeek/releases"
        assert RELEASES_URL == version_info.RELEASES_URL

    def test_missing_or_blank_file_has_safe_fallback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        missing = tmp_path / "missing-version"
        monkeypatch.setattr(version_info, "get_resource_path", lambda *a, **k: str(missing))
        assert version_info.get_local_version() == "0.0.0"
        assert version_info.get_local_build_date() is None

        blank = tmp_path / "SPKVERSION"
        blank.write_text("\n\n", encoding="utf-8")
        monkeypatch.setattr(version_info, "get_resource_path", lambda *a, **k: str(blank))
        assert version_info.get_local_version() == "0.0.0"
        assert version_info.get_local_build_date() is None

    def test_strips_exactly_one_leading_v(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = tmp_path / "SPKVERSION"
        monkeypatch.setattr(version_info, "get_resource_path", lambda *a, **k: str(path))
        for raw, expected in (("v1.2.3", "1.2.3"), ("V1.2.3", "1.2.3"), ("vv1.2.3", "v1.2.3")):
            path.write_text(raw + "\n2026-05-22\n", encoding="utf-8")
            assert version_info.get_local_version() == expected

    def test_build_date_requires_valid_iso_date(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = tmp_path / "SPKVERSION"
        monkeypatch.setattr(version_info, "get_resource_path", lambda *a, **k: str(path))
        for raw in ("2026-02-30", "2026/05/22", "not-a-date", "2026-5-2"):
            path.write_text("v1.0.0\n" + raw + "\n", encoding="utf-8")
            assert version_info.get_local_build_date() is None
        path.write_text("v1.0.0\n2026-05-22\n", encoding="utf-8")
        assert version_info.get_local_build_date() == "2026-05-22"

    def test_blank_second_line_is_not_skipped(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = tmp_path / "SPKVERSION"
        monkeypatch.setattr(version_info, "get_resource_path", lambda *a, **k: str(path))
        path.write_text("v1.0.0\n\n2026-05-22\n", encoding="utf-8")
        assert version_info.get_local_version() == "1.0.0"
        assert version_info.get_local_build_date() is None


# =============================================================================
# 资产名清洗与错误码
# =============================================================================
class TestAssetNameAndErrors:
    """跨语言资产名清洗 fixture 与错误码表。"""

    def test_sanitize_matches_shared_fixture(self) -> None:
        fixture_path = Path(__file__).resolve().parents[2] / "fixtures" / "asset_names.json"
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert data["schema"] == 1
        assert data["cases"], "fixture 不应为空"
        for case in data["cases"]:
            actual = sanitize_asset_name(case["input"])
            assert actual == case["expected"], f"case={case['label']!r} input={case['input']!r}"
            if actual is not None:
                assert len(actual) <= 120
                assert sanitize_asset_name(actual) == actual

    def test_sanitize_rejects_reserved_and_illegal(self) -> None:
        assert sanitize_asset_name("CON") is None
        assert sanitize_asset_name("") is None

    def test_error_table_has_exactly_21_codes(self) -> None:
        expected = {
            "bad_command",
            "bad_params",
            "bad_range",
            "busy",
            "checksum_mismatch",
            "checksum_missing",
            "cancelled",
            "http_status",
            "io",
            "invalid_json",
            "invalid_version",
            "network",
            "no_installer_asset",
            "no_release",
            "rate_limited",
            "size_mismatch",
            "timeout",
            "unsafe_url",
            "internal",
            "process_exited",
            "unavailable",
        }
        assert set(ERROR_MESSAGES) == expected
        assert len(ERROR_MESSAGES) == 21
        assert RETRYABLE_CODES == frozenset(
            {"network", "http_status", "rate_limited", "timeout", "busy"}
        )
        assert "更新服务器返回异常状态" in ERROR_MESSAGES["http_status"]
        assert "安装包大小与发布信息不一致" in ERROR_MESSAGES["size_mismatch"]

    def test_update_error_unknown_code_uses_internal_message(self) -> None:
        unknown = UpdateError("some_future_code")
        assert unknown.code == "some_future_code"
        assert unknown.message == ERROR_MESSAGES["internal"]
        assert unknown.retryable is False

        network = UpdateError("network")
        assert network.message == ERROR_MESSAGES["network"]
        assert network.retryable is True


# =============================================================================
# check
# =============================================================================
class TestCheck:
    """更新检查信号、去重与手动请求语义。"""

    def test_manual_update_available(self, service_factory: Callable[..., Any]) -> None:
        service, bridge = service_factory()
        bridge.check_response = {
            "ok": True,
            "result": {
                "update_available": True,
                "reason": "newer_version",
                "local": {"version": "1.0.0-alpha.5", "date": "2026-05-22"},
                "remote": {"version": "v1.0.1", "date": "2026-06-01"},
                "asset": {
                    "name": "Setup.exe",
                    "size": 10,
                    "sha256": SHA,
                    "download_url": "https://example.com/Setup.exe",
                },
                "skipped_newer_tag": None,
            },
        }
        recorder = Recorder(service)
        request_id = service.check(True)
        assert recorder.check_started == [(request_id, True)]
        assert _pump_until(lambda: len(recorder.check_finished) == 1)
        rid, manual, info, error = recorder.check_finished[0]
        assert (rid, manual, error) == (request_id, True, None)
        assert isinstance(info, UpdateInfo)
        assert tuple(field.name for field in fields(UpdateInfo)) == (
            "local_version",
            "local_date",
            "update_available",
            "reason",
            "skipped_newer_tag",
            "remote",
            "asset",
        )
        assert info.local_version == "1.0.0-alpha.5"
        assert info.local_date == "2026-05-22"
        assert info.update_available is True
        assert info.reason == "newer_version"
        assert info.skipped_newer_tag is None
        assert info.remote == {"version": "v1.0.1", "date": "2026-06-01"}
        assert info.asset is not None and info.asset["name"] == "Setup.exe"
        assert not hasattr(info, "current_version")
        assert not hasattr(info, "latest_version")
        assert not hasattr(info, "release_url")
        assert bridge.ensure_calls == 1
        assert bridge.check_calls[0]["repo"] == "Dorufoc/Sopeek"
        assert bridge.check_calls[0]["current_version"] == "1.0.0-alpha.5"
        assert bridge.check_calls[0]["include_prerelease"] is True

    def test_startup_no_update_emits_only_finished(
        self, service_factory: Callable[..., Any]
    ) -> None:
        service, bridge = service_factory()
        recorder = Recorder(service)
        request_id = service.check(False)
        assert _pump_until(lambda: len(recorder.check_finished) == 1)
        assert recorder.check_started == [(request_id, False)]
        assert recorder.startup_update_available == []
        rid, manual, info, error = recorder.check_finished[0]
        assert (rid, manual, error) == (request_id, False, None)
        assert info.update_available is False
        assert info.reason == "none"
        assert info.local_version == "1.0.0-alpha.5"
        assert info.local_date == "2026-05-22"
        assert info.remote == {}

    def test_startup_update_available(self, service_factory: Callable[..., Any]) -> None:
        service, bridge = service_factory()
        bridge.check_response["result"].update(
            {
                "update_available": True,
                "reason": "newer_version",
                "remote": {"version": "v1.0.1", "date": "2026-06-01"},
                "asset": {
                    "name": "Setup.exe",
                    "size": 10,
                    "sha256": SHA,
                    "download_url": "https://example.com/Setup.exe",
                },
            }
        )
        recorder = Recorder(service)
        service.check(False)
        assert _pump_until(lambda: len(recorder.startup_update_available) == 1)
        assert isinstance(recorder.startup_update_available[0][0], UpdateInfo)

    def test_manual_and_startup_share_single_request(
        self, service_factory: Callable[..., Any]
    ) -> None:
        service, bridge = service_factory(check_gate=threading.Event())
        recorder = Recorder(service)
        first = service.check(False)
        assert bridge.check_entered.wait(5)
        second = service.check(True)
        assert first == second
        assert recorder.check_started == [(first, False)]
        assert len(bridge.check_calls) == 1
        bridge.check_gate.set()
        assert _pump_until(lambda: len(recorder.check_finished) == 2)
        assert {item[1] for item in recorder.check_finished} == {False, True}

    def test_manual_failure_finishes_manual_and_suppresses_startup(
        self, service_factory: Callable[..., Any]
    ) -> None:
        service, bridge = service_factory(
            check_response={
                "ok": False,
                "error": {"code": "rate_limited", "message": "limited", "retryable": True},
            }
        )
        recorder = Recorder(service)
        request_id = service.check(True)
        service.check(False)
        assert _pump_until(lambda: len(recorder.check_finished) == 1)
        rid, manual, info, error = recorder.check_finished[0]
        assert (rid, manual, info) == (request_id, True, None)
        assert isinstance(error, UpdateError)
        assert error.code == "rate_limited"
        assert error.retryable is True
        assert recorder.startup_update_available == []
        assert len(bridge.check_calls) == 1

    def test_startup_only_failure_is_silent(self, service_factory: Callable[..., Any]) -> None:
        service, bridge = service_factory(
            check_response={"ok": False, "error": {"code": "network", "retryable": True}}
        )
        recorder = Recorder(service)
        service.check(False)
        assert _pump_until(lambda: len(bridge.check_calls) == 1)
        _pump(0.15)
        assert recorder.check_finished == []
        assert recorder.startup_update_available == []

    def test_bridge_exception_maps_known_code(self, service_factory: Callable[..., Any]) -> None:
        service, bridge = service_factory(
            check_error=UpdaterBridgeError("network", "offline")
        )
        recorder = Recorder(service)
        service.check(True)
        assert _pump_until(lambda: len(recorder.check_finished) == 1)
        error = recorder.check_finished[0][3]
        assert isinstance(error, UpdateError)
        assert error.code == "network"
        assert error.retryable is True


# =============================================================================
# 启动策略：24h 节流、每版本一次提醒、环境变量门控
# =============================================================================
class TestStartupPolicy:
    """启动检查策略的状态文件、设置读取与通知去重。"""

    NOW = 1_800_000_000.0

    def _write_state(self, path: Path, **state: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")

    def test_startup_default_due_with_empty_state(
        self,
        startup_setting: dict[str, Any],
        service_factory: Callable[..., Any],
        check_state_file: Path,
    ) -> None:
        service, bridge = service_factory()
        recorder = Recorder(service)
        assert update_startup.read_check_state() == {}

        request_id = service.maybe_startup_check()

        assert request_id is not None
        assert _pump_until(lambda: len(recorder.check_finished) == 1)
        state = update_startup.read_check_state()
        assert isinstance(state.get("last_attempt_ts"), float)
        assert len(bridge.check_calls) == 1

    def test_startup_throttle_window_and_clock_rollback(
        self,
        startup_setting: dict[str, Any],
        check_state_file: Path,
    ) -> None:
        self._write_state(check_state_file, last_attempt_ts=self.NOW - 86_399)
        assert update_startup.should_check_on_startup(now=self.NOW) is False

        self._write_state(check_state_file, last_attempt_ts=self.NOW - 86_400)
        assert update_startup.should_check_on_startup(now=self.NOW) is True

        self._write_state(check_state_file, last_attempt_ts=self.NOW + 60)
        assert update_startup.should_check_on_startup(now=self.NOW) is True

    @pytest.mark.parametrize("raw", [None, "nope", {}, [], True])
    def test_startup_invalid_attempt_ts_is_due(
        self,
        startup_setting: dict[str, Any],
        check_state_file: Path,
        raw: object,
    ) -> None:
        self._write_state(check_state_file, last_attempt_ts=raw)
        assert update_startup.should_check_on_startup(now=self.NOW) is True

    def test_startup_setting_false_skips(
        self,
        startup_setting: dict[str, Any],
        check_state_file: Path,
    ) -> None:
        startup_setting["value"] = False
        assert update_startup.should_check_on_startup(now=self.NOW) is False

    @pytest.mark.parametrize("raw", [_UNSET, None, "false", 0])
    def test_startup_non_bool_setting_defaults_true(
        self,
        startup_setting: dict[str, Any],
        check_state_file: Path,
        raw: object,
    ) -> None:
        startup_setting["value"] = raw
        assert update_startup.should_check_on_startup(now=self.NOW) is True

    def test_startup_setting_toggle_is_observed_without_process_flag(
        self,
        startup_setting: dict[str, Any],
        check_state_file: Path,
    ) -> None:
        startup_setting["value"] = True
        assert update_startup.should_check_on_startup(now=self.NOW) is True
        startup_setting["value"] = False
        assert update_startup.should_check_on_startup(now=self.NOW) is False
        startup_setting["value"] = True
        assert update_startup.should_check_on_startup(now=self.NOW) is True
        assert startup_setting["calls"] == 3

    @pytest.mark.parametrize("value", ["1", "true", "YES", "On"])
    def test_startup_env_disable_skips(
        self,
        startup_setting: dict[str, Any],
        check_state_file: Path,
        monkeypatch: pytest.MonkeyPatch,
        value: str,
    ) -> None:
        monkeypatch.setenv("SPK_DISABLE_UPDATE_CHECK", value)
        assert update_startup.should_check_on_startup(now=self.NOW) is False
        assert startup_setting["calls"] == 0

    def test_startup_corrupt_state_is_empty_and_due(
        self,
        startup_setting: dict[str, Any],
        check_state_file: Path,
    ) -> None:
        check_state_file.parent.mkdir(parents=True, exist_ok=True)
        check_state_file.write_text("{bad", encoding="utf-8")

        assert update_startup.read_check_state() == {}
        assert update_startup.should_check_on_startup(now=self.NOW) is True

    def test_startup_unavailable_writes_nothing(
        self,
        startup_setting: dict[str, Any],
        service_factory: Callable[..., Any],
        check_state_file: Path,
    ) -> None:
        service, bridge = service_factory(available=False)

        assert service.maybe_startup_check() is None

        assert bridge.check_calls == []
        assert bridge.ensure_calls == 0
        assert not check_state_file.exists()

    def test_startup_records_attempt_before_dispatch(
        self,
        startup_setting: dict[str, Any],
        service_factory: Callable[..., Any],
        check_state_file: Path,
    ) -> None:
        gate = threading.Event()
        service, bridge = service_factory(check_gate=gate)
        recorder = Recorder(service)

        request_id = service.maybe_startup_check()

        assert request_id is not None
        assert bridge.check_entered.wait(5)
        assert isinstance(update_startup.read_check_state().get("last_attempt_ts"), float)
        assert recorder.check_finished == []
        gate.set()
        assert _pump_until(lambda: len(recorder.check_finished) == 1)

    def test_startup_failure_keeps_attempt_and_throttles(
        self,
        startup_setting: dict[str, Any],
        service_factory: Callable[..., Any],
        check_state_file: Path,
    ) -> None:
        service, bridge = service_factory(
            check_response={"ok": False, "error": {"code": "network", "retryable": True}}
        )
        recorder = Recorder(service)

        assert service.maybe_startup_check() is not None
        assert _pump_until(lambda: len(bridge.check_calls) == 1)
        _pump(0.1)

        assert isinstance(update_startup.read_check_state().get("last_attempt_ts"), float)
        assert service.maybe_startup_check() is None
        assert len(bridge.check_calls) == 1
        assert recorder.check_finished == []
        assert recorder.startup_update_available == []

    def test_startup_inflight_manual_join_failure_keeps_attempt(
        self,
        startup_setting: dict[str, Any],
        service_factory: Callable[..., Any],
        check_state_file: Path,
    ) -> None:
        gate = threading.Event()
        service, bridge = service_factory(
            check_gate=gate,
            check_response={"ok": False, "error": {"code": "network", "retryable": True}},
        )
        recorder = Recorder(service)

        request_id = service.maybe_startup_check()
        assert request_id is not None
        assert bridge.check_entered.wait(5)
        assert service.check(True) == request_id
        gate.set()

        assert _pump_until(lambda: len(recorder.check_finished) == 1)
        rid, manual, info, error = recorder.check_finished[0]
        assert (rid, manual, info) == (request_id, True, None)
        assert isinstance(error, UpdateError) and error.code == "network"
        assert isinstance(update_startup.read_check_state().get("last_attempt_ts"), float)
        assert service.maybe_startup_check() is None
        assert len(bridge.check_calls) == 1

    def test_startup_returns_before_check_and_notifies_later(
        self,
        startup_setting: dict[str, Any],
        service_factory: Callable[..., Any],
        check_state_file: Path,
    ) -> None:
        gate = threading.Event()
        service, bridge = service_factory(check_gate=gate)
        bridge.check_response = _available_check_response(tag="v9.9.9")
        recorder = Recorder(service)

        started = time.monotonic()
        request_id = service.maybe_startup_check()
        elapsed = time.monotonic() - started

        assert request_id is not None
        assert elapsed < 2.0
        assert bridge.check_entered.wait(5)
        assert recorder.startup_update_available == []
        gate.set()
        assert _pump_until(lambda: len(recorder.startup_update_available) == 1)
        info = recorder.startup_update_available[0][0]
        assert isinstance(info, UpdateInfo)
        assert info.remote["tag"] == "v9.9.9"
        assert update_startup.read_check_state().get("last_notified_tag") == "v9.9.9"

    def test_startup_same_tag_notifies_once(
        self,
        startup_setting: dict[str, Any],
        service_factory: Callable[..., Any],
        check_state_file: Path,
    ) -> None:
        service, bridge = service_factory(check_response=_available_check_response(tag="v1.0.2"))
        recorder = Recorder(service)

        service.check(False)
        assert _pump_until(lambda: len(recorder.startup_update_available) == 1)
        first_state = update_startup.read_check_state()
        assert first_state.get("last_notified_tag") == "v1.0.2"

        service.check(False)
        assert _pump_until(lambda: len(recorder.check_finished) == 2)
        _pump(0.15)

        assert len(recorder.startup_update_available) == 1
        assert update_startup.read_check_state() == first_state

    def test_startup_notification_tag_falls_back_to_version(
        self,
        startup_setting: dict[str, Any],
        service_factory: Callable[..., Any],
        check_state_file: Path,
    ) -> None:
        service, bridge = service_factory(check_response=_available_check_response(tag=None))
        recorder = Recorder(service)

        service.check(False)

        assert _pump_until(lambda: len(recorder.startup_update_available) == 1)
        assert update_startup.read_check_state().get("last_notified_tag") == "v1.0.1"

    def test_startup_module_entrypoint_uses_existing_service(
        self,
        startup_setting: dict[str, Any],
        service_factory: Callable[..., Any],
    ) -> None:
        service, bridge = service_factory()
        recorder = Recorder(service)

        request_id = update_startup.maybe_startup_check(object())

        assert request_id is not None
        assert _pump_until(lambda: len(recorder.check_finished) == 1)
        assert len(bridge.check_calls) == 1


# =============================================================================
# download 验证与状态机
# =============================================================================
class TestDownloadValidation:
    """下载参数、磁盘与资产名校验。"""

    def test_missing_asset_checksum_is_async_failure(
        self, service_factory: Callable[..., Any]
    ) -> None:
        service, bridge = service_factory()
        recorder = Recorder(service)
        request_id = service.start_download(_info(sha256=None))
        assert recorder.download_failed == []
        assert service.get_download_state(request_id) is None
        assert _pump_until(lambda: len(recorder.download_failed) == 1)
        rid, error = recorder.download_failed[0]
        assert rid == request_id
        assert isinstance(error, UpdateError) and error.code == "checksum_missing"
        assert bridge.begin_calls == []

    def test_missing_name_is_bad_params(self, service_factory: Callable[..., Any]) -> None:
        service, bridge = service_factory()
        recorder = Recorder(service)
        request_id = service.start_download(_info(name=""))
        assert _pump_until(lambda: len(recorder.download_failed) == 1)
        assert recorder.download_failed[0][0] == request_id
        assert recorder.download_failed[0][1].code == "bad_params"
        assert bridge.begin_calls == []

    def test_sanitize_rejection_is_bad_params(self, service_factory: Callable[..., Any]) -> None:
        service, bridge = service_factory()
        recorder = Recorder(service)
        service.start_download(_info(name="CON"))
        assert _pump_until(lambda: len(recorder.download_failed) == 1)
        assert recorder.download_failed[0][1].code == "bad_params"
        assert bridge.begin_calls == []

    def test_missing_size_is_bad_params(self, service_factory: Callable[..., Any]) -> None:
        service, bridge = service_factory()
        recorder = Recorder(service)
        service.start_download(_info(size=None))
        assert _pump_until(lambda: len(recorder.download_failed) == 1)
        assert recorder.download_failed[0][1].code == "bad_params"

    def test_bad_size_coerces_to_zero(
        self, service_factory: Callable[..., Any], appdata: Path
    ) -> None:
        service, bridge = service_factory()
        recorder = Recorder(service)
        request_id = service.start_download(_info(size="not-a-number"))
        assert _pump_until(lambda: len(recorder.download_finished) == 1)
        dest = _dest(appdata, "Sopeek_Setup.exe")
        assert recorder.download_finished[0] == (request_id, str(dest))
        assert bridge.begin_calls[0]["params"]["expected_size"] == 0

    def test_size_coercion_is_strict(self) -> None:
        assert update_service_module._coerce_size(3 * 1024**3) == 3 * 1024**3
        assert update_service_module._coerce_size("4096") == 0
        assert update_service_module._coerce_size(True) == 0
        assert update_service_module._coerce_size(-1) == 0
        assert update_service_module._coerce_size(None) == 0

    def test_download_started_is_async(
        self, service_factory: Callable[..., Any]
    ) -> None:
        service, bridge = service_factory()
        bridge.ensure_gate = threading.Event()
        bridge.wait_gate = threading.Event()
        recorder = Recorder(service)
        request_id = service.start_download(_info())
        assert recorder.download_started == []
        assert bridge.ensure_entered.wait(5)
        assert recorder.download_started == []
        bridge.ensure_gate.set()
        assert _pump_until(lambda: recorder.download_started == [(request_id,)])
        assert bridge.wait_entered.wait(5)
        bridge.wait_gate.set()
        assert _pump_until(lambda: len(recorder.download_finished) == 1)

    def test_disk_space_failure_maps_io(
        self, service_factory: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service, bridge = service_factory()
        monkeypatch.setattr(
            update_service_module.shutil,
            "disk_usage",
            lambda path: SimpleNamespace(total=0, used=0, free=0),
        )
        recorder = Recorder(service)
        service.start_download(_info())
        assert _pump_until(lambda: len(recorder.download_failed) == 1)
        assert recorder.download_failed[0][1].code == "io"
        assert bridge.begin_calls == []

    def test_appdata_oserror_maps_io(
        self, service_factory: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service, bridge = service_factory()

        def raise_oserror() -> Path:
            raise OSError("denied")

        monkeypatch.setattr(update_service_module, "get_app_data_path", raise_oserror)
        recorder = Recorder(service)
        service.start_download(_info())
        assert _pump_until(lambda: len(recorder.download_failed) == 1)
        assert recorder.download_failed[0][1].code == "io"

    def test_success_creates_dir_and_uses_sanitized_name(
        self, service_factory: Callable[..., Any], appdata: Path
    ) -> None:
        service, bridge = service_factory()
        recorder = Recorder(service)
        request_id = service.start_download(_info(name='Setup<>:"|?*.exe  '))
        assert _pump_until(lambda: len(recorder.download_finished) == 1)
        params = bridge.begin_calls[0]["params"]
        dest = Path(params["dest_path"])
        assert dest.parent == _download_dir(appdata) and dest.parent.is_dir()
        assert dest.name == "Setup.exe"
        assert params["source_url"] == "https://example.com/Sopeek_Setup.exe"
        assert params["expected_sha256"] == SHA
        assert params["expected_size"] == 4096
        assert recorder.download_finished[0] == (request_id, str(dest))
        assert service.get_download_state(request_id) is None

    def test_progress_keeps_64bit_values(
        self, service_factory: Callable[..., Any]
    ) -> None:
        service, bridge = service_factory()
        recorder = Recorder(service)
        spy = QSignalSpy(service.download_progress)
        request_id = _start_blocked_download(service, bridge, _info(size=2**32))
        callback = bridge.callbacks[request_id]
        callback(
            {"event": "progress", "downloaded": 2**31 + 7, "total": 2**32, "speed_bps": 12.5}
        )
        assert _pump_until(lambda: spy.count() == 1)
        args = spy.at(0)
        assert args[0] == request_id
        assert args[1] == 2**31 + 7
        assert args[2] == 2**32
        assert args[3] == pytest.approx(12.5)
        assert service.get_download_state(request_id) == ("running", 2**31 + 7, 2**32)
        bridge.terminal_state = "done"
        bridge.wait_gate.set()
        assert _pump_until(lambda: len(recorder.download_finished) == 1)


class TestSingleFlight:
    """同一时刻只允许一个活动下载。"""

    def test_same_asset_reuses_request_without_duplicate_signals(
        self, service_factory: Callable[..., Any]
    ) -> None:
        service, bridge = service_factory()
        recorder = Recorder(service)
        request_id = _start_blocked_download(service, bridge, _info())
        again = service.start_download(_info())
        assert again == request_id
        assert len(bridge.begin_calls) == 1
        assert _pump_until(lambda: recorder.download_started == [(request_id,)])
        assert service.get_download_state(request_id) is not None
        bridge.wait_gate.set()
        assert _pump_until(lambda: len(recorder.download_finished) == 1)

    def test_different_asset_is_rejected_with_busy(
        self, service_factory: Callable[..., Any]
    ) -> None:
        service, bridge = service_factory()
        recorder = Recorder(service)
        active = _start_blocked_download(service, bridge, _info(name="First.exe"))
        rejected = service.start_download(_info(name="Second.exe"))
        assert rejected != active
        assert service.get_download_state(rejected) is None
        assert _pump_until(lambda: len(recorder.download_failed) == 1)
        rid, error = recorder.download_failed[0]
        assert rid == rejected and isinstance(error, UpdateError) and error.code == "busy"
        assert service.get_download_state(active) is not None
        service.cancel_download(rejected)
        assert bridge.cancel_calls == []
        bridge.wait_gate.set()
        assert _pump_until(lambda: len(recorder.download_finished) == 1)


class TestPauseResume:
    """暂停/恢复语义与状态转换。"""

    def test_pause_then_resume_same_asset(
        self, service_factory: Callable[..., Any]
    ) -> None:
        service, bridge = service_factory()
        recorder = Recorder(service)
        request_id = _start_blocked_download(service, bridge, _info())
        bridge.terminal_state = "paused"
        assert service.pause_download(request_id) is True
        assert _pump_until(lambda: bridge.pause_calls == [request_id])
        bridge.wait_gate.set()
        assert _pump_until(lambda: recorder.download_pause_acked == [(request_id, True)])
        assert _pump_until(lambda: service.get_download_state(request_id)[0] == "paused")
        assert "paused" in [item[1] for item in recorder.download_state_changed]
        assert recorder.download_failed == []

        assert service.start_download(_info()) == request_id
        assert len(bridge.begin_calls) == 1
        bridge.terminal_state = "done"
        assert service.resume_download(request_id) is True
        assert _pump_until(lambda: len(recorder.download_finished) == 1)
        assert recorder.download_finished[0][0] == request_id
        assert len(bridge.begin_calls) == 2

    def test_paused_same_asset_reuses_without_dispatch(
        self, service_factory: Callable[..., Any]
    ) -> None:
        service, bridge = service_factory()
        recorder = Recorder(service)
        request_id = _start_blocked_download(service, bridge, _info())
        bridge.terminal_state = "paused"
        service.pause_download(request_id)
        bridge.wait_gate.set()
        assert _pump_until(lambda: service.get_download_state(request_id)[0] == "paused")

        assert service.start_download(_info()) == request_id
        _pump(0.08)
        assert len(bridge.begin_calls) == 1
        assert recorder.download_started == [(request_id,)]
        assert service.resume_download(request_id) is True
        bridge.terminal_state = "done"
        assert _pump_until(lambda: len(recorder.download_finished) == 1)

    def test_paused_different_asset_cancels_old_and_replaces(
        self, service_factory: Callable[..., Any], appdata: Path
    ) -> None:
        service, bridge = service_factory()
        recorder = Recorder(service)
        old = _start_blocked_download(service, bridge, _info(name="Old.exe"))
        old_dest = _dest(appdata, "Old.exe")
        old_part, old_meta = _suffixes(old_dest)
        old_part.write_bytes(b"partial")
        old_meta.write_text("{}", encoding="utf-8")
        bridge.terminal_state = "paused"
        service.pause_download(old)
        bridge.wait_gate.set()
        assert _pump_until(lambda: service.get_download_state(old)[0] == "paused")

        bridge.terminal_state = "done"
        new = service.start_download(_info(name="New.exe"))
        assert new != old
        assert _pump_until(lambda: len(recorder.download_finished) == 1)
        rid, error = recorder.download_failed[0]
        assert rid == old and error.code == "cancelled"
        assert not old_part.exists() and not old_meta.exists()
        assert recorder.download_finished[0][0] == new

    def test_predispatch_pause_and_resume(
        self, service_factory: Callable[..., Any]
    ) -> None:
        service, bridge = service_factory()
        bridge.ensure_gate = threading.Event()
        recorder = Recorder(service)
        request_id = service.start_download(_info())
        assert bridge.ensure_entered.wait(5)
        service.pause_download(request_id)
        assert service.get_download_state(request_id)[0] == "paused"
        bridge.ensure_gate.set()
        assert _pump_until(lambda: recorder.download_pause_acked == [(request_id, True)])
        assert service.get_download_state(request_id)[0] == "paused"
        assert bridge.begin_calls == []

        assert service.resume_download(request_id) is True
        assert _pump_until(lambda: len(recorder.download_finished) == 1)
        assert len(bridge.begin_calls) == 1

    def test_pause_then_resume_while_dispatching(
        self, service_factory: Callable[..., Any]
    ) -> None:
        service, bridge = service_factory()
        bridge.begin_gate = threading.Event()
        recorder = Recorder(service)
        request_id = service.start_download(_info())
        assert bridge.begin_entered.wait(5)
        service.pause_download(request_id)
        assert service.resume_download(request_id) is True
        bridge.begin_gate.set()
        assert _pump_until(lambda: len(recorder.download_finished) == 1)
        assert recorder.download_pause_acked == []
        assert len(bridge.begin_calls) == 1

    def test_pause_during_begin_failure_then_done_acks_false(
        self, service_factory: Callable[..., Any]
    ) -> None:
        service, bridge = service_factory()
        bridge.begin_gate = threading.Event()
        bridge.pause_error = UpdaterBridgeError("process_exited", "gone")
        recorder = Recorder(service)
        request_id = service.start_download(_info())
        assert bridge.begin_entered.wait(5)
        service.pause_download(request_id)
        bridge.begin_gate.set()
        assert _pump_until(lambda: len(recorder.download_finished) == 1)
        assert bridge.pause_calls == [request_id]
        assert recorder.download_pause_acked == [(request_id, False)]
        assert recorder.download_failed == []
        assert service.get_download_state(request_id) is None

    def test_pause_during_begin_paused_acks_true_once(
        self, service_factory: Callable[..., Any]
    ) -> None:
        service, bridge = service_factory()
        bridge.begin_gate = threading.Event()
        bridge.terminal_state = "paused"
        recorder = Recorder(service)
        request_id = service.start_download(_info())
        assert bridge.begin_entered.wait(5)
        service.pause_download(request_id)
        bridge.begin_gate.set()
        assert _pump_until(lambda: recorder.download_pause_acked == [(request_id, True)])
        assert bridge.pause_calls == [request_id]
        assert service.get_download_state(request_id)[0] == "paused"
        _pump(0.1)
        assert recorder.download_pause_acked == [(request_id, True)]
        assert recorder.download_finished == []

    def test_pause_while_verifying_acks_false_without_bridge(
        self, service_factory: Callable[..., Any], appdata: Path
    ) -> None:
        service, bridge = service_factory()
        bridge.verify_gate = threading.Event()
        dest = _dest(appdata, "Setup.exe")
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"cached")
        recorder = Recorder(service)
        request_id = service.start_download(_info(name="Setup.exe"))
        assert bridge.verify_entered.wait(5)
        assert service.get_download_state(request_id)[0] == "verifying"
        service.pause_download(request_id)
        assert _pump_until(lambda: recorder.download_pause_acked == [(request_id, False)])
        assert bridge.pause_calls == []
        bridge.verify_gate.set()
        assert _pump_until(lambda: len(recorder.download_finished) == 1)

    def test_old_pause_control_does_not_touch_new_request(
        self, service_factory: Callable[..., Any]
    ) -> None:
        service, bridge = service_factory()
        recorder = Recorder(service)
        old = _start_blocked_download(service, bridge, _info(name="Old.exe"))
        bridge.pause_gate = threading.Event()
        service.pause_download(old)
        assert bridge.pause_entered.wait(5)

        bridge.terminal_state = "done"
        bridge.wait_gate.set()
        assert _pump_until(lambda: len(recorder.download_finished) == 1)
        assert recorder.download_finished[0][0] == old

        new = service.start_download(_info(name="New.exe"))
        assert _pump_until(lambda: len(recorder.download_finished) == 2)
        assert recorder.download_finished[1][0] == new
        bridge.pause_gate.set()
        _pump(0.15)
        assert bridge.pause_calls == [old]
        assert all(rid != new for rid, _ in recorder.download_failed)
        assert recorder.download_finished[1][0] == new


class TestCancel:
    """取消、abort 顺序与产物清理。"""

    def test_predispatch_cancel_sets_event_and_skips_begin(
        self, service_factory: Callable[..., Any]
    ) -> None:
        service, bridge = service_factory()
        bridge.ensure_gate = threading.Event()
        recorder = Recorder(service)
        request_id = service.start_download(_info())
        assert bridge.ensure_entered.wait(5)
        service.cancel_download(request_id)
        bridge.ensure_gate.set()
        assert _pump_until(lambda: len(recorder.download_failed) == 1)
        assert recorder.download_failed[0][0] == request_id
        assert recorder.download_failed[0][1].code == "cancelled"
        assert bridge.begin_calls == []
        assert bridge.cancel_calls == []

    def test_cancel_during_begin_calls_bridge_and_emits_once(
        self, service_factory: Callable[..., Any]
    ) -> None:
        service, bridge = service_factory()
        bridge.begin_gate = threading.Event()
        recorder = Recorder(service)
        request_id = service.start_download(_info())
        assert bridge.begin_entered.wait(5)
        service.cancel_download(request_id)
        bridge.begin_gate.set()
        assert _pump_until(lambda: len(recorder.download_failed) == 1)
        _pump(0.1)
        assert bridge.cancel_calls == [request_id]
        assert recorder.download_failed[0][0] == request_id
        assert recorder.download_failed[0][1].code == "cancelled"
        assert recorder.download_finished == []
        assert len(recorder.download_failed) == 1
        assert bridge.wait_calls == []

    def test_cancel_after_begin_cleans_and_emits_once(
        self, service_factory: Callable[..., Any], appdata: Path
    ) -> None:
        service, bridge = service_factory()
        recorder = Recorder(service)
        request_id = _start_blocked_download(service, bridge, _info(name="Setup.exe"))
        dest = _dest(appdata, "Setup.exe")
        part, meta = _suffixes(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(b"partial")
        meta.write_text("{}", encoding="utf-8")
        service.cancel_download(request_id)
        assert _pump_until(lambda: bridge.cancel_calls == [request_id])
        bridge.terminal_state = "cancelled"
        bridge.wait_gate.set()
        assert _pump_until(lambda: len(recorder.download_failed) == 1)
        _pump(0.12)
        assert len(recorder.download_failed) == 1
        assert recorder.download_failed[0][1].code == "cancelled"
        assert recorder.download_finished == []
        assert not dest.exists() and not part.exists() and not meta.exists()
        assert bridge.wait_exited_calls == []

    def test_cancel_paused_download_deletes_without_bridge(
        self, service_factory: Callable[..., Any], appdata: Path
    ) -> None:
        service, bridge = service_factory()
        recorder = Recorder(service)
        request_id = _start_blocked_download(service, bridge, _info(name="Setup.exe"))
        bridge.terminal_state = "paused"
        service.pause_download(request_id)
        bridge.wait_gate.set()
        assert _pump_until(lambda: service.get_download_state(request_id)[0] == "paused")
        dest = _dest(appdata, "Setup.exe")
        part, meta = _suffixes(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(b"partial")
        meta.write_text("{}", encoding="utf-8")
        service.cancel_download(request_id)
        assert _pump_until(lambda: len(recorder.download_failed) == 1)
        _pump(0.1)
        assert len(recorder.download_failed) == 1
        assert bridge.cancel_calls == []
        assert not part.exists() and not meta.exists()

    def test_cancel_while_verifying_cache(
        self, service_factory: Callable[..., Any], appdata: Path
    ) -> None:
        service, bridge = service_factory()
        bridge.verify_gate = threading.Event()
        dest = _dest(appdata, "Setup.exe")
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"cached")
        recorder = Recorder(service)
        request_id = service.start_download(_info(name="Setup.exe"))
        assert bridge.verify_entered.wait(5)
        service.cancel_download(request_id)
        assert service.get_download_state(request_id)[0] == "verifying"
        bridge.verify_gate.set()
        assert _pump_until(lambda: len(recorder.download_failed) == 1)
        _pump(0.1)
        assert len(recorder.download_failed) == 1
        assert recorder.download_failed[0][1].code == "cancelled"
        assert recorder.download_finished == []
        assert not dest.exists()
        assert bridge.begin_calls == []

    def test_abort_error_waits_for_process_before_cleanup(
        self, service_factory: Callable[..., Any], appdata: Path
    ) -> None:
        service, bridge = service_factory()
        bridge.wait_gate = threading.Event()
        recorder = Recorder(service)
        bridge.wait_error = UpdaterBridgeError("cancelled", "aborted", abort=True)
        request_id = service.start_download(_info(name="Setup.exe"))
        assert bridge.wait_entered.wait(5)
        dest = _dest(appdata, "Setup.exe")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"partial")
        bridge.wait_gate.set()
        assert _pump_until(lambda: len(recorder.download_failed) == 1)
        assert recorder.download_failed[0][0] == request_id
        assert recorder.download_failed[0][1].code == "cancelled"
        assert bridge.wait_exited_calls and bridge.wait_exited_calls[0][0] == 1.0
        assert bridge.wait_exited_calls[0][1] is True  # 等待进程退出时文件仍在
        assert not dest.exists()

    def test_normal_cancel_result_does_not_wait_for_process(
        self, service_factory: Callable[..., Any]
    ) -> None:
        service, bridge = service_factory()
        recorder = Recorder(service)
        bridge.terminal_state = "cancelled"
        service.start_download(_info())
        assert _pump_until(lambda: len(recorder.download_failed) == 1)
        assert bridge.wait_exited_calls == []

    def test_cancel_unknown_id_is_noop(self, service_factory: Callable[..., Any]) -> None:
        service, bridge = service_factory()
        service.cancel_download("missing")
        _pump(0.05)
        assert bridge.cancel_calls == []
        assert service.get_download_state("missing") is None


class TestCache:
    """缓存命中、校验与安装包验证。"""

    def test_cache_hit_verifies_on_task_pool_and_finishes(
        self, service_factory: Callable[..., Any], appdata: Path
    ) -> None:
        service, bridge = service_factory()
        dest = _dest(appdata, "Setup.exe")
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"cached")
        recorder = Recorder(service)
        main_thread = threading.current_thread()
        request_id = service.start_download(_info(name="Setup.exe"))
        assert service.get_download_state(request_id)[0] == "verifying"
        assert _pump_until(lambda: len(recorder.download_finished) == 1)
        assert recorder.download_finished[0] == (request_id, str(dest))
        assert bridge.begin_calls == []
        assert bridge.verify_calls[0]["path"] == str(dest)
        assert bridge.verify_calls[0]["sha256"] == SHA
        assert bridge.verify_threads[0] is not main_thread
        assert len([x for x in recorder.download_state_changed if x[1] == "verifying"]) == 1

    def test_cache_mismatch_deletes_then_downloads(
        self, service_factory: Callable[..., Any], appdata: Path
    ) -> None:
        service, bridge = service_factory()
        dest = _dest(appdata, "Setup.exe")
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"stale")
        bridge.verify_response = {
            "ok": True,
            "result": {"match": False, "volume_serial": 0, "file_index": 0},
        }
        recorder = Recorder(service)
        request_id = service.start_download(_info(name="Setup.exe"))
        assert _pump_until(lambda: len(recorder.download_finished) == 1)
        assert recorder.download_finished[0][0] == request_id
        assert len(bridge.begin_calls) == 1
        assert dest.exists()

    def test_verify_installer_forwards_result(self, service_factory: Callable[..., Any]) -> None:
        service, bridge = service_factory()
        result = service.verify_installer(Path("C:/Setup.exe"), SHA)
        assert result == (True, 1, 2)
        assert bridge.verify_calls[0] == {"path": str(Path("C:/Setup.exe")), "sha256": SHA}

    def test_is_available_reprobes_and_shutdown_forwards(
        self, service_factory: Callable[..., Any]
    ) -> None:
        service, bridge = service_factory()
        assert service.is_available() is True
        bridge.available = False
        assert service.is_available() is False
        bridge.available = True
        bridge.stop_result = True
        assert service.ensure_bridge() is True
        assert service.shutdown(timeout=2.5) is True
        assert bridge.stop_calls == [2.5]
        assert service.is_available() is True


class TestLifecycle:
    """单例、线程池与关闭。"""

    def test_singleton_getter_and_if_exists(
        self, qapp, service_factory: Callable[..., Any]
    ) -> None:
        assert get_update_service_if_exists() is None
        service, _ = service_factory()
        assert get_update_service_if_exists() is service
        assert get_update_service(bridge_factory=lambda: FakeBridge()) is service

    def test_constructor_requires_main_thread(self, qapp) -> None:
        errors: list[BaseException] = []

        def build() -> None:
            try:
                UpdateService(bridge_factory=lambda: FakeBridge())
            except BaseException as exc:  # noqa: BLE001 - 记录到主线程断言
                errors.append(exc)

        worker = threading.Thread(target=build)
        worker.start()
        worker.join(5)
        assert errors and isinstance(errors[0], RuntimeError)
        assert UpdateService._instance is None

    def test_private_bounded_pools(self, service_factory: Callable[..., Any]) -> None:
        service, _ = service_factory()
        global_pool = QThreadPool.globalInstance()
        assert service._download_pool is not global_pool
        assert service._task_pool is not global_pool
        assert service._control_pool is not global_pool
        assert service._download_pool.maxThreadCount() == 1
        assert service._task_pool.maxThreadCount() == 2
        assert service._control_pool.maxThreadCount() == 2
        assert isinstance(service._dispatch_lock, type(threading.Lock()))

    def test_close_is_idempotent(self, service_factory: Callable[..., Any]) -> None:
        service, bridge = service_factory()
        service.close()
        service.close()
        assert bridge.close_calls == 2

