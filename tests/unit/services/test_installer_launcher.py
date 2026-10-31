# -*- coding: utf-8 -*-
"""安装器启动服务测试（rust-native-updater Todo 18）。

覆盖原生校验 -> sidecar 关闭 -> Python 独立复核 -> 提权启动的决策链，
以及失败/UAC 取消/句柄关闭/单次 finished 等边界。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication

import sopeek.services.installer_launcher as il

pytestmark = pytest.mark.unit


class FakeUpdateService:
    """最小 UpdateService 替身。"""

    def __init__(
        self,
        *,
        verified: bool = True,
        identity: tuple[int, int] = (0, 0),
        shutdown_ok: bool = True,
        verify_error: Exception | None = None,
    ) -> None:
        self.verified = verified
        self.identity = identity
        self.shutdown_ok = shutdown_ok
        self.verify_error = verify_error
        self.verify_calls: list[tuple[Path, str]] = []
        self.shutdown_calls: list[float] = []
        self.ensure_calls = 0

    def verify_installer(
        self, path: Path, sha256: str
    ) -> tuple[bool, int, int]:
        """记录并返回预设校验结果。"""
        self.verify_calls.append((path, sha256))
        if self.verify_error is not None:
            raise self.verify_error
        return self.verified, self.identity[0], self.identity[1]

    def shutdown(self, timeout: float = 4.0) -> bool:
        """记录并返回预设关闭结果。"""
        self.shutdown_calls.append(timeout)
        return self.shutdown_ok

    def ensure_bridge(self) -> bool:
        """记录恢复调用。"""
        self.ensure_calls += 1
        return True


class FakePool:
    """同步记录 QRunnable 的线程池替身。"""

    def __init__(self) -> None:
        self.tasks: list[Any] = []

    def start(self, task: Any) -> None:
        """记录任务，不自动执行。"""
        self.tasks.append(task)


def _identity_for(path: Path) -> tuple[int, int]:
    """读取真实文件标识，供 FakeUpdateService 返回一致值。"""
    handle = il._open_installer_handle(path)
    try:
        return il._file_identity(handle)
    finally:
        il._close_handle(handle)


def _make_file(tmp_path: Path, name: str = "setup.exe") -> tuple[Path, str]:
    """创建安装包并返回路径与 SHA-256。"""
    path = tmp_path / "download" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"Sopeek installer payload"
    path.write_bytes(payload)
    return path, hashlib.sha256(payload).hexdigest()


class TestRunVerification:
    """worker 内部三步流水线。"""

    def test_success_keeps_open_handle_and_identity(self, tmp_path: Path) -> None:
        """校验/关闭/复核全部成功时保留句柄供启动阶段使用。"""
        path, sha = _make_file(tmp_path)
        identity = _identity_for(path)
        service = FakeUpdateService(identity=identity)

        result = il._run_verification(service, path, sha)

        assert result[0] == str(path)
        assert result[1] is True
        assert result[2] is True
        assert result[3] is True
        assert result[4] is not None
        assert result[5] == identity
        assert result[6] is None
        assert service.verify_calls == [(path, sha)]
        assert service.shutdown_calls == [4.0]
        il._close_handle(result[4])

    def test_hash_mismatch_keeps_handle_for_gui_cleanup(
        self, tmp_path: Path
    ) -> None:
        """哈希不一致时 recheck_ok=False，但句柄留给 GUI 关闭并删除。"""
        path, _sha = _make_file(tmp_path)
        identity = _identity_for(path)
        service = FakeUpdateService(identity=identity)

        result = il._run_verification(service, path, "0" * 64)

        assert result[1] is True
        assert result[2] is True
        assert result[3] is False
        assert result[4] is not None
        assert "复核" in str(result[6])
        il._close_handle(result[4])

    def test_shutdown_failure_skips_recheck(self, tmp_path: Path) -> None:
        """sidecar 关闭失败时不再复核，也不返回句柄。"""
        path, sha = _make_file(tmp_path)
        service = FakeUpdateService(shutdown_ok=False)

        result = il._run_verification(service, path, sha)

        assert result[1] is True
        assert result[2] is False
        assert result[3] is False
        assert result[4] is None
        assert "关闭" in str(result[6])
        assert len(service.verify_calls) == 1
        assert len(service.shutdown_calls) == 1

    def test_verify_exception_is_readable(self, tmp_path: Path) -> None:
        """Rust 校验异常被转换为可读错误，不抛出 worker。"""
        path, sha = _make_file(tmp_path)
        service = FakeUpdateService(verify_error=RuntimeError("boom"))

        result = il._run_verification(service, path, sha)

        assert result[1] is False
        assert result[4] is None
        assert "校验失败" in str(result[6])
        assert len(service.shutdown_calls) == 1


class TestLaunchPath:
    """启动前的路径边界。"""

    def test_accepts_exe_inside_download_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """download 下的真实 exe 被接受并返回 realpath。"""
        monkeypatch.setattr(il, "get_app_data_path", lambda: str(tmp_path))
        path, _sha = _make_file(tmp_path)

        assert il._launch_path(str(path)) == path.resolve()

    def test_rejects_outside_sibling_txt_relative_and_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """目录外/兄弟目录/非 exe/相对路径/缺失文件全部拒绝。"""
        monkeypatch.setattr(il, "get_app_data_path", lambda: str(tmp_path))
        path, _sha = _make_file(tmp_path)
        outside = tmp_path / "outside.exe"
        outside.write_bytes(b"x")
        backup = tmp_path / "download_backup" / "setup.exe"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(b"x")
        text = path.with_suffix(".txt")
        text.write_bytes(b"x")

        assert il._launch_path(str(outside)) is None
        assert il._launch_path(str(backup)) is None
        assert il._launch_path(str(text)) is None
        assert il._launch_path("download/setup.exe") is None
        assert il._launch_path(str(tmp_path / "download" / "missing.exe")) is None


class TestOpenInstallerHandle:
    """句柄打开时的 reparse point 防护。"""

    def test_rejects_symlink_reparse_point(self, tmp_path: Path) -> None:
        """符号链接必须在读取哈希前被拒绝，且句柄已关闭。"""
        target = tmp_path / "real.exe"
        target.write_bytes(b"payload")
        link = tmp_path / "link.exe"
        try:
            link.symlink_to(target)
        except OSError as exc:
            pytest.skip(f"当前环境无法创建符号链接: {exc}")

        with pytest.raises(OSError, match="符号链接|目录联接"):
            il._open_installer_handle(link)


class TestLaunchInstaller:
    """ShellExecuteW 参数契约。"""

    def test_uses_runas_absolute_path_and_parent_directory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """runas + 绝对路径 + 安装包父目录 + SW_SHOWNORMAL。"""
        calls: list[tuple[Any, ...]] = []

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
                    calls.append((hwnd, verb, file, params, cwd, show))
                    return 42

                self.ShellExecuteW = shell_execute

        monkeypatch.setattr(il.ctypes, "WinDLL", lambda *a, **k: FakeShell32())
        path = Path(r"C:\tmp\download\setup.exe")

        assert il.launch_installer(str(path)) == 42
        assert calls == [
            (None, "runas", str(path), None, str(path.parent), il.SW_SHOWNORMAL)
        ]

    def test_none_return_becomes_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ShellExecuteW 返回 None 时返回 0，不抛 TypeError。"""
        class FakeShell32:
            def __init__(self) -> None:
                def shell_execute(*_args: Any) -> None:
                    return None

                self.ShellExecuteW = shell_execute

        monkeypatch.setattr(il.ctypes, "WinDLL", lambda *a, **k: FakeShell32())

        assert il.launch_installer(Path(r"C:\tmp\download\setup.exe")) == 0


class TestHandleResult:
    """GUI 线程上的启动决策。"""

    def _launcher(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[il.InstallerLauncher, FakeUpdateService, dict[str, Any]]:
        """构造带记录器的 launcher。"""
        service = FakeUpdateService()
        launcher = il.InstallerLauncher(service)
        records: dict[str, Any] = {
            "closed": [],
            "deleted": [],
            "failures": [],
            "uac": [],
            "quit": 0,
            "shell": [],
            "finished": [],
        }
        original_close = il._close_handle

        def close(handle: int | None) -> None:
            records["closed"].append(handle)
            original_close(handle)

        monkeypatch.setattr(il, "_close_handle", close)
        monkeypatch.setattr(
            il, "_safe_delete", lambda path: records["deleted"].append(path)
        )
        monkeypatch.setattr(
            il.InstallerLauncher,
            "_notify_failure",
            lambda self, message: records["failures"].append(message),
        )
        monkeypatch.setattr(
            il.InstallerLauncher,
            "_notify_uac_cancelled",
            lambda self, path: records["uac"].append(path),
        )
        monkeypatch.setattr(
            il, "_quit_app", lambda: records.__setitem__("quit", records["quit"] + 1)
        )
        monkeypatch.setattr(
            il,
            "_shell_execute",
            lambda path: records["shell"].append(path) or 42,
        )
        launcher.finished.connect(records["finished"].append)
        return launcher, service, records

    def test_success_quits_closes_handle_and_emits_once(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ret > 32 即成功，即使 last_error 仍是 1223。"""
        launcher, service, records = self._launcher(qapp, monkeypatch)
        monkeypatch.setattr(il, "_launch_path", lambda path: Path("C:/x/setup.exe"))
        monkeypatch.setattr(il, "_get_last_error", lambda: 1223)
        result = ("C:/x/setup.exe", True, True, True, 123, (1, 2), None)

        launcher.handle_result(result)

        assert records["quit"] == 1
        assert records["closed"] == [123]
        assert records["finished"] == [result]
        assert service.ensure_calls == 0
        assert records["failures"] == []

    def test_uac_cancel_restores_bridge_without_quit(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """错误码 1223 显示 UAC 取消，不退出应用，只恢复一次桥。"""
        launcher, service, records = self._launcher(qapp, monkeypatch)
        monkeypatch.setattr(il, "_launch_path", lambda path: Path("C:/x/setup.exe"))
        monkeypatch.setattr(il, "_shell_execute", lambda path: 5)
        monkeypatch.setattr(il, "_get_last_error", lambda: 1223)
        result = ("C:/x/setup.exe", True, True, True, 123, (1, 2), None)

        launcher.handle_result(result)
        launcher.handle_result(result)

        assert records["uac"] == ["C:\\x\\setup.exe"]
        assert records["quit"] == 0
        assert records["closed"] == [123]
        assert service.ensure_calls == 1
        assert records["finished"] == [result]

    def test_uac_cancel_survives_mutating_close(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CloseHandle 改写 last_error 时仍按 1223 走 UAC 取消。"""
        launcher, service, records = self._launcher(qapp, monkeypatch)
        monkeypatch.setattr(il, "_launch_path", lambda path: Path("C:/x/setup.exe"))

        def shell_execute(path: Path) -> int:
            il.ctypes.set_last_error(1223)
            return 5

        monkeypatch.setattr(il, "_shell_execute", shell_execute)
        base_close = il._close_handle

        def mutating_close(handle: int | None) -> None:
            base_close(handle)
            il.ctypes.set_last_error(0)

        monkeypatch.setattr(il, "_close_handle", mutating_close)
        result = ("C:/x/setup.exe", True, True, True, 123, (1, 2), None)

        launcher.handle_result(result)

        assert records["uac"] == ["C:\\x\\setup.exe"]
        assert records["quit"] == 0
        assert service.ensure_calls == 1
        assert records["closed"] == [123]
        assert records["finished"] == [result]

    @pytest.mark.parametrize(
        ("verified", "shutdown_ok", "recheck_ok", "delete_expected"),
        [
            (False, True, False, True),
            (True, False, False, False),
            (True, True, False, True),
        ],
    )
    def test_failure_paths_close_and_notify(
        self,
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
        verified: bool,
        shutdown_ok: bool,
        recheck_ok: bool,
        delete_expected: bool,
    ) -> None:
        """校验/关闭/复核失败均关闭句柄、恢复桥并显示可读提示。"""
        launcher, service, records = self._launcher(qapp, monkeypatch)
        result = (
            "C:/x/setup.exe",
            verified,
            shutdown_ok,
            recheck_ok,
            123,
            (1, 2),
            "失败原因",
        )

        launcher.handle_result(result)

        assert records["closed"] == [123]
        assert bool(records["deleted"]) is delete_expected
        assert records["failures"] == ["失败原因"]
        assert records["shell"] == []
        assert service.ensure_calls == 1
        assert records["quit"] == 0

    def test_non_cancel_failure_mentions_permission(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """非 1223 的启动失败不退出，提示包含“权限”。"""
        launcher, service, records = self._launcher(qapp, monkeypatch)
        monkeypatch.setattr(il, "_launch_path", lambda path: Path("C:/x/setup.exe"))
        monkeypatch.setattr(il, "_shell_execute", lambda path: 5)
        monkeypatch.setattr(il, "_get_last_error", lambda: 5)
        result = ("C:/x/setup.exe", True, True, True, 123, (1, 2), None)

        launcher.handle_result(result)

        assert records["quit"] == 0
        assert service.ensure_calls == 1
        assert "权限" in records["failures"][0]
        assert records["closed"] == [123]
        assert records["finished"] == [result]

    def test_invalid_launch_path_never_calls_shell(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """路径校验失败时不调用 ShellExecute，恢复桥并提示。"""
        launcher, service, records = self._launcher(qapp, monkeypatch)
        monkeypatch.setattr(il, "_launch_path", lambda path: None)
        result = ("C:/x/setup.exe", True, True, True, 123, (1, 2), None)

        launcher.handle_result(result)

        assert records["shell"] == []
        assert records["failures"] == ["安装包路径无效，已取消安装。"]
        assert records["closed"] == [123]
        assert service.ensure_calls == 1
        assert records["quit"] == 0

    def test_malformed_payload_fails_closed(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """非七元组 payload 不抛异常，按失败关闭。"""
        launcher, service, records = self._launcher(qapp, monkeypatch)

        launcher.handle_result(("bad",))

        assert records["failures"]
        assert service.ensure_calls == 1
        assert len(records["finished"]) == 1
        assert records["finished"][0][1] is False


class TestLauncherStart:
    """任务提交与端到端线程边界。"""

    def test_empty_metadata_emits_failure_without_pool(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """空路径/空摘要立即失败关闭，不提交 worker。"""
        service = FakeUpdateService()
        pool = FakePool()
        launcher = il.InstallerLauncher(service, pool=pool)
        finished: list[Any] = []
        failures: list[str] = []
        launcher.finished.connect(finished.append)
        monkeypatch.setattr(
            il.InstallerLauncher,
            "_notify_failure",
            lambda self, message: failures.append(message),
        )

        assert launcher.start("", "") is False
        qapp.processEvents()

        assert pool.tasks == []
        assert failures
        assert len(finished) == 1
        assert finished[0][1] is False

    def test_worker_result_reaches_gui_launch(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """worker 完成 -> 排队回 GUI -> 成功提权并关闭句柄。"""
        monkeypatch.setattr(il, "get_app_data_path", lambda: str(tmp_path))
        path, sha = _make_file(tmp_path)
        service = FakeUpdateService(identity=_identity_for(path))
        pool = FakePool()
        launcher = il.InstallerLauncher(service, pool=pool)
        records: dict[str, Any] = {"closed": [], "quit": 0, "finished": []}
        original_close = il._close_handle

        def close(handle: int | None) -> None:
            records["closed"].append(handle)
            original_close(handle)

        monkeypatch.setattr(il, "_close_handle", close)
        monkeypatch.setattr(il, "_shell_execute", lambda resolved: 42)
        monkeypatch.setattr(
            il, "_quit_app", lambda: records.__setitem__("quit", records["quit"] + 1)
        )
        launcher.finished.connect(records["finished"].append)

        assert launcher.start(str(path), sha) is True
        assert len(pool.tasks) == 1
        pool.tasks[0].run()
        qapp.processEvents()

        assert records["quit"] == 1
        assert len(records["closed"]) == 1
        assert records["closed"][0] is not None
        assert len(records["finished"]) == 1
        assert records["finished"][0][1:4] == (True, True, True)
        assert service.shutdown_calls == [4.0]
