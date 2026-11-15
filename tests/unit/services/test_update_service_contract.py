# -*- coding: utf-8 -*-
"""``UpdateService.check`` 的定向契约测试（src 布局版）。

只覆盖远端 ``main-v2`` 在这一轮里新增的两条行为，取代原先被整体删除的
1654 行 ``tests/unit/services/test_update_service.py``：

* ``include_prerelease`` 原样透传给原生桥（检查更新页「获取测试版」开关状态）；
* 仓库 404 时按 ``REPO_CANDIDATES`` 回退，非 404 错误不回退。

测试坚持从公开信号 ``check_finished`` 观察结果，并用 ``FakeBridge`` 替代
真实 updater 子进程，因此不依赖 Rust DLL 或网络。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/services/test_update_service.py -v
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Iterator, Optional

import pytest
from PySide6.QtCore import QCoreApplication

from sopeek.services import update_service as update_service_module
from sopeek.services.update_service import (
    UpdateError,
    UpdateInfo,
    UpdateService,
)
from sopeek.utils.version_info import REPO_CANDIDATES

pytestmark = pytest.mark.unit

SHA = "a" * 64


def _available_response() -> dict[str, Any]:
    """构造一个「有新版本」的原生 check 响应。"""
    return {
        "ok": True,
        "result": {
            "update_available": True,
            "reason": "newer_version",
            "local": {"version": "1.0.0", "date": "2026-01-01"},
            "remote": {"version": "v9.9.9", "date": "2026-06-01", "tag": "v9.9.9"},
            "asset": {
                "name": "Setup.exe",
                "size": 10,
                "sha256": SHA,
                "download_url": "https://example.com/Setup.exe",
            },
            "skipped_newer_tag": None,
        },
    }


def _error_response(code: str, message: str) -> dict[str, Any]:
    """构造一个原生错误信封。"""
    return {
        "ok": False,
        "error": {"code": code, "message": message, "retryable": True},
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


class FakeBridge:
    """可控的 updater bridge 替身：记录每次 check 的入参并返回脚本化响应。"""

    def __init__(self, responses: Optional[list[dict[str, Any]]] = None) -> None:
        self.available = True
        self.responses: list[dict[str, Any]] = list(responses or [])
        self.check_calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        """返回可配置的可用性。"""
        return self.available

    def ensure_started(self) -> bool:
        """原生子进程启动总是成功（测试不 spawn 真实进程）。"""
        return True

    def check(
        self, params: Optional[Any] = None, request_id: Optional[str] = None
    ) -> dict[str, Any]:
        """记录入参并按顺序返回脚本化响应（超出则重复最后一个）。"""
        with self._lock:
            self.check_calls.append(dict(params or {}))
            index = len(self.check_calls) - 1
            if not self.responses:
                return _available_response()
            return self.responses[min(index, len(self.responses) - 1)]


class Recorder:
    """收集 ``check_finished`` 公开信号。"""

    def __init__(self, service: UpdateService) -> None:
        self.check_finished: list[tuple[Any, ...]] = []
        service.check_finished.connect(
            lambda *args: self.check_finished.append(args)
        )


@pytest.fixture(autouse=True)
def reset_update_service_singleton() -> Iterator[None]:
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


@pytest.fixture
def service_factory(
    qapp: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., tuple[UpdateService, FakeBridge]]]:
    """构造使用 FakeBridge 与隔离 app data 的 ``UpdateService``。"""
    appdata = tmp_path / "appdata"
    appdata.mkdir(parents=True)
    monkeypatch.setattr(
        update_service_module, "get_app_data_path", lambda: appdata
    )

    created: list[tuple[UpdateService, FakeBridge]] = []

    def make(**bridge_kwargs: Any) -> tuple[UpdateService, FakeBridge]:
        bridge = FakeBridge(**bridge_kwargs)
        service = UpdateService(bridge_factory=lambda: bridge)
        created.append((service, bridge))
        return service, bridge

    yield make

    for service, _bridge in created:
        try:
            service.shutdown(timeout=0.2)
        except Exception:  # 清理阶段：服务可能已自行关闭
            pass
        try:
            service.close()
        except Exception:  # 清理阶段：重复关闭必须无副作用
            pass


class TestIncludePrerelease:
    """「获取测试版」勾选状态必须原样透传给原生桥。"""

    def test_false_is_forwarded(
        self, service_factory: Callable[..., tuple[UpdateService, FakeBridge]]
    ) -> None:
        """``include_prerelease=False`` → 桥收到 False（仅查正式版）。"""
        service, bridge = service_factory()
        recorder = Recorder(service)
        service.check(True, include_prerelease=False)
        assert _pump_until(lambda: len(recorder.check_finished) == 1)
        assert bridge.check_calls[0]["include_prerelease"] is False

    def test_true_is_forwarded(
        self, service_factory: Callable[..., tuple[UpdateService, FakeBridge]]
    ) -> None:
        """``include_prerelease=True`` → 桥收到 True（含预发布版）。"""
        service, bridge = service_factory()
        recorder = Recorder(service)
        service.check(True, include_prerelease=True)
        assert _pump_until(lambda: len(recorder.check_finished) == 1)
        assert bridge.check_calls[0]["include_prerelease"] is True

    def test_default_keeps_startup_behaviour(
        self, service_factory: Callable[..., tuple[UpdateService, FakeBridge]]
    ) -> None:
        """不传该参数时默认 True，保持启动检查的既有行为。"""
        service, bridge = service_factory()
        recorder = Recorder(service)
        service.check(False)
        assert _pump_until(lambda: len(recorder.check_finished) == 1)
        assert bridge.check_calls[0]["include_prerelease"] is True


class TestStartupChannel:
    """启动检查的通道必须跟随「已安装构建」，而不是无条件包含测试版。"""

    @pytest.mark.parametrize(
        ("version", "expected"),
        [
            ("2.0.0", False),
            ("v2.0.0", False),
            ("2.0.0.nightly-20261114", True),
            ("v2.0.0.nightly-20261114", True),
            ("1.0.0-alpha.5", True),
            ("", False),
        ],
    )
    def test_prerelease_detection(self, version: str, expected: bool) -> None:
        """夜间版与语义化预发布版都算预发布构建。"""
        assert update_service_module._is_prerelease_build(version) is expected

    @pytest.mark.parametrize(
        ("local_version", "expected"),
        [("2.0.0", False), ("2.0.0.nightly-20261114", True)],
    )
    def test_startup_check_follows_installed_build(
        self,
        service_factory: Callable[..., tuple[UpdateService, FakeBridge]],
        monkeypatch: pytest.MonkeyPatch,
        local_version: str,
        expected: bool,
    ) -> None:
        """启动检查按本地构建的通道派发 ``include_prerelease``。"""
        service, bridge = service_factory()
        recorder = Recorder(service)
        monkeypatch.setattr(
            update_service_module, "get_local_version", lambda: local_version
        )
        monkeypatch.setattr(
            update_service_module.update_startup,
            "should_check_on_startup",
            lambda now=None: True,
        )
        monkeypatch.setattr(
            update_service_module.update_startup,
            "record_check_attempt",
            lambda now=None: True,
        )

        request_id = service.maybe_startup_check()

        assert isinstance(request_id, str) and request_id
        assert _pump_until(lambda: len(recorder.check_finished) == 1)
        assert bridge.check_calls[0]["include_prerelease"] is expected

    def test_notification_dedupe_prefers_version(self) -> None:
        """夜间版固定标签 ``nightly`` 无法去重，去重键必须用版本号。"""
        info = UpdateInfo(
            local_version="2.0.0",
            local_date="2026-11-01",
            update_available=True,
            reason="newer_version",
            skipped_newer_tag=None,
            remote={"version": "2.0.0.nightly-20261114", "tag": "nightly"},
            asset=None,
        )
        assert UpdateService._notification_tag(info) == "2.0.0.nightly-20261114"

    def test_notification_tag_falls_back_to_release_tag(self) -> None:
        """缺少版本号时回退发布标签。"""
        info = UpdateInfo(
            local_version="1.0.0",
            local_date=None,
            update_available=True,
            reason="newer_version",
            skipped_newer_tag=None,
            remote={"tag": "v9.9.9"},
            asset=None,
        )
        assert UpdateService._notification_tag(info) == "v9.9.9"


class TestRepoFallback:
    """同名仓库 404 时回退到官方仓库；其他错误不回退。"""

    def test_falls_back_on_404(
        self, service_factory: Callable[..., tuple[UpdateService, FakeBridge]]
    ) -> None:
        """首个候选返回 404 → 改用第二个候选并正常返回结果。"""
        service, bridge = service_factory(
            responses=[
                _error_response("http_status", "GitHub API 返回 HTTP 404"),
                _available_response(),
            ]
        )
        recorder = Recorder(service)
        service.check(True)
        assert _pump_until(lambda: len(recorder.check_finished) == 1)
        _, manual, info, error = recorder.check_finished[0]
        assert (manual, error) == (True, None)
        assert isinstance(info, UpdateInfo)
        assert info.update_available is True
        assert [call["repo"] for call in bridge.check_calls] == list(
            REPO_CANDIDATES
        )

    def test_does_not_fall_back_on_other_errors(
        self, service_factory: Callable[..., tuple[UpdateService, FakeBridge]]
    ) -> None:
        """网络错误不回退，直接作为检查失败上报。"""
        service, bridge = service_factory(
            responses=[_error_response("network", "检查更新失败")]
        )
        recorder = Recorder(service)
        service.check(True)
        assert _pump_until(lambda: len(recorder.check_finished) == 1)
        _, _, info, error = recorder.check_finished[0]
        assert info is None
        assert isinstance(error, UpdateError)
        assert error.code == "network"
        assert [call["repo"] for call in bridge.check_calls] == [
            REPO_CANDIDATES[0]
        ]

    def test_reports_last_error_when_all_candidates_404(
        self, service_factory: Callable[..., tuple[UpdateService, FakeBridge]]
    ) -> None:
        """全部候选都 404 → 用尽候选后上报错误，不无限重试。"""
        not_found = _error_response("http_status", "GitHub API 返回 HTTP 404")
        service, bridge = service_factory(responses=[not_found, not_found])
        recorder = Recorder(service)
        service.check(True)
        assert _pump_until(lambda: len(recorder.check_finished) == 1)
        _, _, info, error = recorder.check_finished[0]
        assert info is None
        assert isinstance(error, UpdateError)
        assert error.code == "http_status"
        assert len(bridge.check_calls) == len(REPO_CANDIDATES)


class TestUpdateSource:
    """检查请求按持久化的 ``update.source`` 选择 API 基地址与仓库候选。"""

    def test_default_source_uses_github_api_base(
        self, service_factory: Callable[..., tuple[UpdateService, FakeBridge]]
    ) -> None:
        """默认（github）→ 请求 GitHub API，仓库仍按候选顺序回退。"""
        service, bridge = service_factory()
        recorder = Recorder(service)
        service.check(True)
        assert _pump_until(lambda: len(recorder.check_finished) == 1)
        assert bridge.check_calls[0]["api_base"] == "https://api.github.com"
        assert bridge.check_calls[0]["repo"] == REPO_CANDIDATES[0]

    def test_gitcode_source_uses_domestic_api_base(
        self,
        service_factory: Callable[..., tuple[UpdateService, FakeBridge]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """选择 gitcode → 请求 GitCode v5 API 与镜像仓库。"""
        monkeypatch.setattr(
            update_service_module, "read_update_source_key", lambda: "gitcode"
        )
        service, bridge = service_factory()
        recorder = Recorder(service)
        service.check(True)
        assert _pump_until(lambda: len(recorder.check_finished) == 1)
        assert bridge.check_calls[0]["api_base"] == "https://gitcode.com/api/v5"
        assert bridge.check_calls[0]["repo"] == "Dorufoc/FreeAssetFilter"

    def test_unknown_source_falls_back_to_github(
        self,
        service_factory: Callable[..., tuple[UpdateService, FakeBridge]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """未知/非法设置值 → 回退默认 GitHub 源。"""
        monkeypatch.setattr(
            update_service_module, "read_update_source_key", lambda: "unknown"
        )
        service, bridge = service_factory()
        recorder = Recorder(service)
        service.check(True)
        assert _pump_until(lambda: len(recorder.check_finished) == 1)
        assert bridge.check_calls[0]["api_base"] == "https://api.github.com"
