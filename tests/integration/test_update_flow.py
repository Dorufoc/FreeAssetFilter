# -*- coding: utf-8 -*-
"""End-to-end update flow: fake sidecar -> UpdateService -> dialogs/About page.

The sidecar is ``tests/support/fake_updater.py`` launched through the real
``FafUpdaterBridge`` command-injection seam. No network, installer or UAC
prompt is used; ``ShellExecuteW`` is mocked. Paused artifacts are always
removed by the fixture teardown.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest
from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtWidgets import QApplication

import freeassetfilter.core.managers.settings_manager_v2 as settings_v2
import freeassetfilter.services.installer_launcher as launcher_mod
import freeassetfilter.services.update_service as update_service_module
import freeassetfilter.ui.layout.settings_layout as settings_mod
import freeassetfilter.ui.layout.update_dialogs as dialogs_mod
from freeassetfilter.core.native.bridges.faf_updater_bridge import FafUpdaterBridge
from freeassetfilter.services.update_service import (
    UpdateService,
    get_update_service_if_exists,
)
from freeassetfilter.ui.theme import tm
from tests.support.qt_helpers import drain_deferred_deletes, safe_teardown

pytestmark = pytest.mark.integration

_FAKE_UPDATER = Path(__file__).resolve().parents[1] / "support" / "fake_updater.py"
_PAYLOAD = bytes((index % 251) for index in range(1024 * 1024))
_ASSET_NAME = "FreeAssetFilter_Setup.exe"
_SHA256 = hashlib.sha256(_PAYLOAD).hexdigest()


def _pump_until(predicate: Callable[[], bool], timeout: float = 8.0) -> bool:
    """Process Qt events until ``predicate`` returns True or time expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    QCoreApplication.processEvents()
    return bool(predicate())


def _pump(seconds: float = 0.1) -> None:
    """Drive the event loop for a bounded period."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)


@dataclass
class Flow:
    """One isolated fake-sidecar update service."""

    service: UpdateService
    bridge: FafUpdaterBridge
    appdata: Path
    check_file: Path

    @property
    def dest(self) -> Path:
        return self.appdata / "download" / _ASSET_NAME

    @property
    def part(self) -> Path:
        return Path(str(self.dest) + ".part")

    @property
    def meta(self) -> Path:
        return Path(str(self.dest) + ".part.json")


def _check_result() -> dict[str, Any]:
    """Return a check result pointing at the fake's HTTP-free payload."""
    return {
        "update_available": True,
        "reason": "newer_version",
        "local": {"version": "1.0.0-alpha.5", "date": "2026-05-22"},
        "remote": {
            "version": "1.0.0-alpha.6",
            "tag": "v1.0.0-alpha.6",
            "date": "2026-06-01",
            "html_url": "https://github.com/Dorufoc/FreeAssetFilter/releases/tag/v1.0.0-alpha.6",
        },
        "asset": {
            "name": _ASSET_NAME,
            "size": len(_PAYLOAD),
            "sha256": _SHA256,
            "download_url": f"https://example.invalid/{_ASSET_NAME}",
        },
        "skipped_newer_tag": None,
    }


def _info() -> Any:
    """Build the UpdateInfo the service will return for the fake check."""
    return update_service_module.UpdateInfo(
        local_version="1.0.0-alpha.5",
        local_date="2026-05-22",
        update_available=True,
        reason="newer_version",
        skipped_newer_tag=None,
        remote=dict(_check_result()["remote"]),
        asset=dict(_check_result()["asset"]),
    )


@pytest.fixture
def flow_factory(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., Flow]:
    """Create one service whose sidecar is the Python fake updater."""
    appdata = tmp_path / "appdata"
    appdata.mkdir()
    check_file = tmp_path / "check-result.json"
    monkeypatch.setattr(
        update_service_module, "get_app_data_path", lambda: appdata
    )
    created: list[Flow] = []

    def make(env: dict[str, str] | None = None) -> Flow:
        check_file.write_text(json.dumps(_check_result()), encoding="utf-8")
        merged = {
            "FAF_FAKE_CHECK_RESULT": str(check_file),
            "FAF_FAKE_CHUNK_SIZE": "32768",
            "FAF_FAKE_CHUNK_DELAY": "0.01",
        }
        if env:
            merged.update(env)
        bridge = FafUpdaterBridge(
            command=[sys.executable, str(_FAKE_UPDATER)],
            env=merged,
        )
        service = UpdateService(bridge_factory=lambda: bridge)
        flow = Flow(service, bridge, appdata, check_file)
        created.append(flow)
        return flow

    yield make

    for dialog in list(dialogs_mod._active_dialogs):
        try:
            dialog.close_dialog()
        except Exception:  # 清理阶段：对话框可能已被 Qt 自动销毁
            pass
    dialogs_mod._active_dialogs.clear()
    dialogs_mod._active_progress_dialogs.clear()
    drain_deferred_deletes()
    for flow in created:
        try:
            flow.service.shutdown(timeout=2.0)
        except Exception:  # 清理阶段：服务可能已自行关闭
            pass
        try:
            flow.service.close()
        except Exception:  # 清理阶段：重复关闭必须无副作用
            pass
        try:
            flow.bridge.close()
        except Exception:  # 清理阶段：边车可能已退出
            pass
        for artifact in (flow.part, flow.meta):
            try:
                artifact.unlink(missing_ok=True)
            except OSError:
                # 清理阶段：已关闭的边车可能仍短暂占用文件的句柄。
                pass


def _make_about_page(monkeypatch: pytest.MonkeyPatch, service: UpdateService) -> Any:
    """Create AboutSettingsPage bound to the isolated service."""
    monkeypatch.setattr(
        settings_mod, "get_update_service", lambda: service, raising=False
    )
    return settings_mod.AboutSettingsPage()


def _find_available_dialog() -> Any:
    """Return the live update-available dialog."""
    for dialog in list(dialogs_mod._active_dialogs):
        if hasattr(dialog, "_download_button"):
            return dialog
    return None


class TestAboutPageFlow:
    """About page + real dialogs through the fake sidecar."""

    def test_close_pauses_and_late_finish_never_installs(
        self,
        flow_factory: Callable[..., Flow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Close pauses, keeps part/meta, and a late finish does not install."""
        settings_writes: list[tuple[str, Any]] = []
        theme_calls: list[str] = []
        monkeypatch.setattr(
            settings_v2.SettingsManagerV2,
            "set",
            lambda self, key, value, *a, **k: settings_writes.append((key, value)),
        )
        monkeypatch.setattr(
            settings_v2.SettingsManagerV2,
            "save",
            lambda self, *a, **k: settings_writes.append(("save", None)),
        )
        for name in ("set_theme", "set_theme_mode", "toggle_theme"):
            monkeypatch.setattr(
                tm,
                name,
                lambda *a, _n=name, **k: theme_calls.append(_n),
            )
        theme_before = tm.get_theme_mode()
        install_calls: list[tuple[Any, ...]] = []
        monkeypatch.setattr(
            dialogs_mod,
            "show_install_confirm",
            lambda *args: install_calls.append(args),
        )

        flow = flow_factory()
        page = _make_about_page(monkeypatch, flow.service)
        try:
            # Startup check is already in flight; a manual check joins it.
            startup_id = flow.service.check(manual=False)
            page._check_update()
            manual_id = page._request_id
            assert manual_id == startup_id
            assert page._check_active is True

            assert _pump_until(lambda: _find_available_dialog() is not None, 10)
            available = _find_available_dialog()
            assert available is not None
            available._download_button.click()

            assert _pump_until(
                lambda: bool(dialogs_mod._active_progress_dialogs), 8
            )
            request_id = next(iter(dialogs_mod._active_progress_dialogs))
            progress = dialogs_mod._active_progress_dialogs[request_id]
            assert _pump_until(lambda: progress._download_index > 0, 8)

            # A foreign request id must not change this dialog's state.
            flow.service.download_state_changed.emit("download-999", "paused")
            _pump(0.05)
            assert progress._state != "paused"

            progress.close()
            assert _pump_until(
                lambda: (flow.service.get_download_state(request_id) or ("",))[0]
                in {"paused", "done"},
                10,
            )
            state = flow.service.get_download_state(request_id)
            assert state is not None
            state_name, downloaded, _total = state
            assert state_name in {"paused", "done"}
            assert flow.part.exists()
            assert flow.meta.exists()
            held = downloaded
            _pump(0.25)
            after = flow.service.get_download_state(request_id)
            assert after is not None and after[1] == held

            # Late terminal after close: the detached dialog must not install.
            flow.service.download_finished.emit(request_id, str(flow.dest))
            _pump(0.15)
            assert install_calls == []

            assert settings_writes == []
            assert theme_calls == []
            assert tm.get_theme_mode() == theme_before
            assert get_update_service_if_exists() is flow.service
        finally:
            safe_teardown(page)
            page.deleteLater()
            drain_deferred_deletes()

    def test_cancel_wins_over_late_completion(
        self,
        flow_factory: Callable[..., Flow],
    ) -> None:
        """A cancel racing a completion emits one cancelled terminal."""
        flow = flow_factory(
            {
                "FAF_FAKE_IGNORE_CANCEL": "1",
                "FAF_FAKE_CHUNK_DELAY": "0.02",
                "FAF_FAKE_CHUNK_SIZE": "16384",
            }
        )
        finished: list[tuple[str, str]] = []
        failed: list[tuple[str, str]] = []
        flow.service.download_finished.connect(
            lambda rid, path: finished.append((rid, path))
        )
        flow.service.download_failed.connect(
            lambda rid, error: failed.append((rid, str(getattr(error, "code", error))))
        )

        request_id = flow.service.start_download(_info())
        assert _pump_until(
            lambda: (flow.service.get_download_state(request_id) or ("", 0, 0))[1]
            > len(_PAYLOAD) // 4,
            10,
        )
        flow.service.cancel_download(request_id)

        assert _pump_until(
            lambda: bool(finished or failed), 12
        )
        _pump(0.2)
        assert failed == [(request_id, "cancelled")]
        assert finished == []
        assert not flow.part.exists()
        assert flow.service.get_download_state(request_id) is None

    def test_crash_at_half_shows_retry_and_fails_cleanly(
        self,
        flow_factory: Callable[..., Flow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A sidecar crash at 50% surfaces a retryable failure."""
        flow = flow_factory(
            {
                "FAF_FAKE_CRASH_AT": str(len(_PAYLOAD) // 2),
                "FAF_FAKE_CHUNK_DELAY": "0.01",
                "FAF_FAKE_CHUNK_SIZE": "16384",
            }
        )
        failed: list[tuple[str, str]] = []
        flow.service.download_failed.connect(
            lambda rid, error: failed.append((rid, str(getattr(error, "code", error))))
        )
        dialog = dialogs_mod.show_download_progress(_info(), flow.service)
        request_id = dialog._request_id
        assert _pump_until(
            lambda: dialog._state == "error" and dialog._retry_button.isVisible(),
            15,
        )
        assert failed == [(request_id, "process_exited")]
        assert dialog._error_label.isVisible()
        assert dialog._retry_button.isEnabled()
        assert not flow.part.exists()
        assert not flow.dest.exists()
        dialog.close_dialog()

    @pytest.mark.parametrize(
        ("shell_result", "last_error", "expect_uac"),
        [
            (42, 0, False),
            (5, 1223, True),
        ],
    )
    def test_install_launch_and_uac_cancel_recovery(
        self,
        flow_factory: Callable[..., Flow],
        monkeypatch: pytest.MonkeyPatch,
        shell_result: int,
        last_error: int,
        expect_uac: bool,
    ) -> None:
        """ShellExecuteW success installs; UAC cancel restores the bridge."""
        flow = flow_factory({"FAF_FAKE_REAL_VERIFY": "1"})
        monkeypatch.setattr(
            launcher_mod, "get_app_data_path", lambda: flow.appdata
        )
        monkeypatch.setattr(
            dialogs_mod, "get_update_service", lambda: flow.service
        )
        shell_calls: list[tuple[Any, ...]] = []
        quit_calls: list[int] = []
        real_win_dll = ctypes.WinDLL

        class FakeShell32:
            def __init__(self) -> None:
                def shell_execute(
                    hwnd: Any,
                    verb: str,
                    file: str,
                    params: Any,
                    cwd: str,
                    show: int,
                ) -> int:
                    shell_calls.append((hwnd, verb, file, params, cwd, show))
                    ctypes.set_last_error(last_error)
                    return shell_result

                self.ShellExecuteW = shell_execute

        def fake_win_dll(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "shell32":
                return FakeShell32()
            return real_win_dll(name, *args, **kwargs)

        monkeypatch.setattr(launcher_mod.ctypes, "WinDLL", fake_win_dll)
        monkeypatch.setattr(
            launcher_mod, "_quit_app", lambda: quit_calls.append(1)
        )
        uac_dialogs: list[Any] = []
        original_uac = dialogs_mod.show_uac_cancelled
        monkeypatch.setattr(
            dialogs_mod,
            "show_uac_cancelled",
            lambda path: uac_dialogs.append(original_uac(path)),
        )

        dialog = dialogs_mod.show_download_progress(_info(), flow.service)
        request_id = dialog._request_id

        def _confirm_install() -> None:
            for candidate in list(dialogs_mod._active_dialogs):
                button = getattr(candidate, "_confirm_button", None)
                if button is not None and button.isVisible() and button.isEnabled():
                    button.click()
                    return
            QTimer.singleShot(20, _confirm_install)

        # The download finishes into show_install_confirm's nested event loop.
        QTimer.singleShot(20, _confirm_install)
        assert _pump_until(
            lambda: uac_dialogs or quit_calls or shell_calls, 20
        )
        assert _pump_until(
            lambda: dialogs_mod._active_progress_dialogs.get(request_id) is None,
            10,
        )
        assert shell_calls and shell_calls[0][1] == "runas"
        assert Path(shell_calls[0][2]).name == _ASSET_NAME
        assert not flow.part.exists()
        assert not flow.meta.exists()
        assert flow.dest.exists()

        if expect_uac:
            assert quit_calls == []
            assert len(uac_dialogs) == 1
            assert flow.service.ensure_bridge() is True
            checked: list[tuple[str, bool, Any, Any]] = []
            flow.service.check_finished.connect(
                lambda rid, manual, info, error: checked.append(
                    (rid, manual, info, error)
                )
            )
            flow.service.check(manual=True)
            assert _pump_until(lambda: bool(checked), 10)
            assert checked[0][1] is True
            assert checked[0][2] is not None
            assert checked[0][3] is None
            uac_dialogs[0].close_dialog()
        else:
            assert quit_calls == [1]
            assert uac_dialogs == []
