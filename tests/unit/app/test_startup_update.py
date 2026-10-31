# -*- coding: utf-8 -*-
"""``StartupController`` 启动更新检查钩子的契约测试。

覆盖 Rust native updater Todo 13：3 秒启动钩子、信号只连接一次且使用
``Qt.QueuedConnection``、启动提示转发、退出时只停止已存在的
``UpdateService``。测试不启动真实 updater 子进程、不访问网络。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Signal

from sopeek.app import startup as startup_module
from sopeek.app.startup import StartupController
from sopeek.services import update_service as update_service_module
from sopeek.services import update_startup
from sopeek.services.update_service import UpdateInfo, UpdateService

pytestmark = pytest.mark.unit


def _pump(seconds: float = 0.15) -> None:
    """短暂驱动 Qt 事件循环。"""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)


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


def _info(tag: str = "v9.9.9") -> UpdateInfo:
    """构造一个可展示的更新信息。"""
    return UpdateInfo(
        local_version="1.0.0-alpha.5",
        local_date="2026-05-22",
        update_available=True,
        reason="newer_version",
        skipped_newer_tag=None,
        remote={"version": "v9.9.9", "tag": tag, "date": "2026-06-01"},
        asset=None,
    )


def _check_response(tag: str) -> dict[str, Any]:
    """构造原生 check 成功响应。"""
    return {
        "ok": True,
        "result": {
            "update_available": True,
            "reason": "newer_version",
            "local": {"version": "1.0.0-alpha.5", "date": "2026-05-22"},
            "remote": {"version": "v9.9.9", "tag": tag, "date": "2026-06-01"},
            "asset": None,
            "skipped_newer_tag": None,
        },
    }


class FakeUpdateService(QObject):
    """可控的更新服务替身（真实 Qt 信号，便于验证连接语义）。"""

    startup_update_available = Signal(object)

    def __init__(
        self,
        *,
        emit_info: Optional[UpdateInfo] = None,
        error: Optional[BaseException] = None,
    ) -> None:
        super().__init__()
        self.emit_info = emit_info
        self.error = error
        self.maybe_calls: list[Any] = []
        self.shutdown_calls: list[float] = []

    def maybe_startup_check(self, window: Any = None) -> Optional[str]:
        self.maybe_calls.append(window)
        if self.error is not None:
            raise self.error
        if self.emit_info is not None:
            self.startup_update_available.emit(self.emit_info)
        return "check-1"

    def shutdown(self, timeout: float = 4.0) -> bool:
        self.shutdown_calls.append(timeout)
        return True


class FakeBridge:
    """可控的 updater 原生桥替身（不启动子进程）。"""

    def __init__(
        self,
        *,
        available: bool = True,
        response: Optional[dict[str, Any]] = None,
    ) -> None:
        self.available = available
        self.response = response or _check_response("v9.9.9")
        self.ensure_calls = 0
        self.check_calls: list[tuple[dict[str, Any], Optional[str]]] = []
        self.stop_calls: list[float] = []

    def is_available(self) -> bool:
        return self.available

    def ensure_started(self) -> bool:
        self.ensure_calls += 1
        return True

    def check(
        self, params: dict[str, Any], request_id: Optional[str] = None
    ) -> dict[str, Any]:
        self.check_calls.append((dict(params), request_id))
        return self.response

    def stop(self, timeout: float = 4.0) -> bool:
        self.stop_calls.append(timeout)
        return True


@pytest.fixture
def window() -> Any:
    """主窗口替身。"""
    return SimpleNamespace(name="main-window")


@pytest.fixture
def controller(qapp: Any, window: Any) -> StartupController:
    """构造走真实 Qt 事件循环的 StartupController。"""
    return StartupController(app=SimpleNamespace(settings_manager=None), window=window)


@pytest.fixture
def built_services(qapp: Any):
    """创建并回收使用替身桥的 UpdateService。"""
    created: list[UpdateService] = []

    def make(bridge: Any) -> UpdateService:
        service = UpdateService(bridge_factory=lambda: bridge)
        created.append(service)
        return service

    yield make

    for service in created:
        try:
            service.shutdown(timeout=0.2)
        except Exception:  # 清理阶段：服务可能已自行关闭
            pass
        try:
            service.close()
        except Exception:  # 清理阶段：重复关闭必须无副作用
            pass


@pytest.fixture
def update_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把启动检查状态与设置读取隔离到临时目录。"""
    monkeypatch.setattr(update_startup, "get_app_data_path", lambda: tmp_path)
    monkeypatch.setattr(update_service_module, "get_app_data_path", lambda: tmp_path)
    monkeypatch.delenv(update_startup.DISABLE_ENV_VAR, raising=False)
    monkeypatch.setattr(update_startup, "_startup_setting_enabled", lambda: True)
    return tmp_path


@pytest.fixture
def shown(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, UpdateInfo]]:
    """替换启动提示 UI 并记录调用参数。"""
    from sopeek.ui.layout import update_dialogs

    calls: list[tuple[Any, UpdateInfo]] = []
    monkeypatch.setattr(
        update_dialogs,
        "show_startup_update",
        lambda parent, info: calls.append((parent, info)),
    )
    return calls


class TestStartupSchedule:
    """3 秒启动钩子调度。"""

    def test_schedule_startup_tasks_adds_three_second_update_check(
        self, controller: StartupController, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[int, Callable[[], None]]] = []

        class RecordingTimer:
            @staticmethod
            def singleShot(msec: int, callback: Callable[[], None]) -> None:
                calls.append((msec, callback))

        from sopeek.core.managers import heartbeat_manager as hb_module

        class DummyHeartbeat:
            def start(self) -> None:
                pass

        monkeypatch.setattr(startup_module, "QTimer", RecordingTimer)
        monkeypatch.setattr(hb_module, "HeartbeatManager", DummyHeartbeat)

        fired: list[bool] = []
        monkeypatch.setattr(
            controller, "_maybe_check_updates", lambda: fired.append(True)
        )

        controller.schedule_startup_tasks()

        delays = [msec for msec, _ in calls]
        # 首帧后：字体 / 图标缓存清理（0ms）→ 缩略图缓存清理（100ms）→
        # FFmpeg 预热（200ms）→ 预算补应用（400ms）→ 更新检查（3000ms）。
        # 后两项都会导入重模块或跑 FFI，刻意错开面板构建网格（0–24ms）。
        assert delays[:5] == [0, 200, 0, 400, 100]
        update_callbacks = [callback for msec, callback in calls if msec == 3000]
        assert len(update_callbacks) == 1
        update_callbacks[0]()
        assert fired == [True]

    def test_controller_is_qobject(self, controller: StartupController) -> None:
        assert isinstance(controller, QObject)


class TestUpdateSignalWiring:
    """信号连接与启动提示转发。"""

    def test_connects_once_then_calls_maybe_startup_check(
        self,
        controller: StartupController,
        shown: list[tuple[Any, UpdateInfo]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeUpdateService()
        monkeypatch.setattr(
            update_service_module, "get_update_service", lambda: fake
        )

        controller._maybe_check_updates()
        controller._maybe_check_updates()

        assert fake.maybe_calls == [controller.window, controller.window]
        fake.startup_update_available.emit(_info())
        QCoreApplication.processEvents()
        assert len(shown) == 1
        assert shown[0] == (controller.window, _info())

    def test_connect_before_check_receives_synchronous_emit(
        self,
        controller: StartupController,
        shown: list[tuple[Any, UpdateInfo]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        info = _info()
        fake = FakeUpdateService(emit_info=info)
        monkeypatch.setattr(
            update_service_module, "get_update_service", lambda: fake
        )

        controller._maybe_check_updates()

        assert shown == []
        QCoreApplication.processEvents()
        assert shown == [(controller.window, info)]

    def test_cross_thread_emit_is_queued_to_main_thread(
        self,
        controller: StartupController,
        shown: list[tuple[Any, UpdateInfo]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from sopeek.ui.layout import update_dialogs

        threads: list[threading.Thread] = []
        monkeypatch.setattr(
            update_dialogs,
            "show_startup_update",
            lambda parent, info: threads.append(threading.current_thread()),
        )
        fake = FakeUpdateService()
        monkeypatch.setattr(
            update_service_module, "get_update_service", lambda: fake
        )
        controller._maybe_check_updates()

        info = _info()
        worker = threading.Thread(
            target=lambda: fake.startup_update_available.emit(info)
        )
        worker.start()
        worker.join(5)

        assert threads == []
        QCoreApplication.processEvents()
        assert threads == [threading.main_thread()]

    def test_update_dialogs_slot_calls_show_with_window_and_info(
        self,
        controller: StartupController,
        shown: list[tuple[Any, UpdateInfo]],
    ) -> None:
        info = _info()
        controller._on_startup_update_available(info)
        assert shown == [(controller.window, info)]

    def test_update_dialogs_skeleton_is_importable(self) -> None:
        from sopeek.ui.layout import update_dialogs

        assert callable(update_dialogs.show_startup_update)

    def test_failure_does_not_show_ui_or_escape(
        self,
        controller: StartupController,
        shown: list[tuple[Any, UpdateInfo]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeUpdateService(error=RuntimeError("boom"))
        monkeypatch.setattr(
            update_service_module, "get_update_service", lambda: fake
        )

        controller._safe("_maybe_check_updates")()

        assert fake.maybe_calls == [controller.window]
        assert shown == []


class TestStartupPolicyIntegration:
    """与真实 UpdateService 的策略联动（替身桥，不启动子进程）。"""

    def test_env_gate_skips_check(
        self,
        controller: StartupController,
        built_services: Callable[[Any], UpdateService],
        update_state: Path,
        shown: list[tuple[Any, UpdateInfo]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(update_startup.DISABLE_ENV_VAR, "1")
        bridge = FakeBridge()
        service = built_services(bridge)
        monkeypatch.setattr(
            update_service_module, "get_update_service", lambda: service
        )

        controller._safe("_maybe_check_updates")()
        _pump(0.1)

        assert bridge.check_calls == []
        assert shown == []
        assert not update_startup.check_state_path().exists()

    def test_unavailable_service_does_not_raise_or_show(
        self,
        controller: StartupController,
        built_services: Callable[[Any], UpdateService],
        update_state: Path,
        shown: list[tuple[Any, UpdateInfo]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bridge = FakeBridge(available=False)
        service = built_services(bridge)
        monkeypatch.setattr(
            update_service_module, "get_update_service", lambda: service
        )

        controller._safe("_maybe_check_updates")()
        _pump(0.1)

        assert bridge.check_calls == []
        assert shown == []

    def test_same_tag_notifies_at_most_once(
        self,
        controller: StartupController,
        built_services: Callable[[Any], UpdateService],
        update_state: Path,
        shown: list[tuple[Any, UpdateInfo]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bridge = FakeBridge(response=_check_response("v9.9.9"))
        service = built_services(bridge)
        monkeypatch.setattr(
            update_service_module, "get_update_service", lambda: service
        )
        monkeypatch.setattr(
            update_startup, "should_check_on_startup", lambda: True
        )

        controller._maybe_check_updates()
        assert _pump_until(lambda: len(shown) == 1)
        assert _pump_until(lambda: service._check_request_id is None)

        controller._maybe_check_updates()
        assert _pump_until(lambda: len(bridge.check_calls) == 2)
        assert _pump_until(lambda: service._check_request_id is None)
        _pump(0.2)

        assert len(shown) == 1
        assert shown[0] == (controller.window, _info("v9.9.9"))


class TestCleanup:
    """退出清理只触碰已存在的服务。"""

    def test_cleanup_shuts_down_existing_service_once(
        self,
        controller: StartupController,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeUpdateService()
        monkeypatch.setattr(
            update_service_module, "get_update_service_if_exists", lambda: fake
        )

        def _forbidden(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("cleanup 不得构造 UpdateService")

        monkeypatch.setattr(
            update_service_module, "get_update_service", _forbidden
        )
        monkeypatch.setattr(update_service_module, "UpdateService", _forbidden)

        started = time.monotonic()
        controller.cleanup()
        elapsed = time.monotonic() - started

        assert fake.shutdown_calls == [2.0]
        assert elapsed < 1.0

    def test_cleanup_without_instance_never_constructs(
        self,
        controller: StartupController,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            update_service_module, "get_update_service_if_exists", lambda: None
        )

        def _forbidden(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("cleanup 不得构造 UpdateService")

        monkeypatch.setattr(
            update_service_module, "get_update_service", _forbidden
        )
        monkeypatch.setattr(update_service_module, "UpdateService", _forbidden)

        controller.cleanup()

    def test_unstarted_service_shutdown_returns_true_without_pipe_writes(
        self, qapp: Any
    ) -> None:
        from sopeek.core.native.bridges.spk_updater_bridge import (
            SpkUpdaterBridge,
        )

        bridge = SpkUpdaterBridge()
        service = UpdateService(bridge_factory=lambda: bridge)
        try:
            assert bridge._process is None
            started = time.monotonic()
            assert service.shutdown(timeout=2.0) is True
            elapsed = time.monotonic() - started
            assert elapsed < 1.0
            assert bridge._process is None
        finally:
            service.close()
