# -*- coding: utf-8 -*-
# targets: sopeek.app.main, sopeek.app.instance_guard,
#          sopeek.app.startup
"""新版应用引导层（app/ 包）集成测试。

引导层已拆分为三个模块（main / instance_guard / startup），模块级零副作用
（导入不再安装 fd 捕获 / faulthandler / 异常钩子），本文件直接导入并覆盖：

* 内部子进程参数分流（--spk-thumbnail-worker）
* 右键 ``--open-path`` 解析与初始导航路径推导
* 运行时实例信息（runtime_instance.json）写/读/删往返
* Windows 进程守卫纯函数边界
* 设置管理器提前初始化（挂 app.settings_manager）
* StartupController 清理链路与 StartupWarmupThread 预热顺序
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def app_main() -> Any:
    """导入引导层 main 模块（模块级无副作用）。"""
    import sopeek.app.main as main_module

    return main_module


@pytest.fixture
def instance_guard() -> Any:
    """导入单实例守卫模块。"""
    import sopeek.app.instance_guard as guard_module

    return guard_module


@pytest.fixture
def startup() -> Any:
    """导入启动任务编排模块。"""
    import sopeek.app.startup as startup_module

    return startup_module


class TestInternalWorkerArgs:
    """--spk-thumbnail-worker 内部分流。"""

    def test_thumbnail_worker_args(self, app_main: Any) -> None:
        argv = ["prog", "--spk-thumbnail-worker", "C:/v.mp4", "1.4", "1"]
        kind, payload = app_main._parse_internal_worker_args(argv)
        assert kind == "thumbnail"
        assert payload["file_path"] == "C:/v.mp4"
        assert payload["dpi_scale"] == "1.4"
        assert payload["prefer_native"] == "1"

    def test_normal_args_returns_none(self, app_main: Any) -> None:
        assert app_main._parse_internal_worker_args(["prog"]) == (None, {})

    def test_insufficient_worker_args_returns_none(self, app_main: Any) -> None:
        assert app_main._parse_internal_worker_args(
            ["prog", "--spk-thumbnail-worker"]
        ) == (None, {})


class TestOpenPathArg:
    """--open-path 解析与初始导航路径推导。"""

    def test_open_path_arg(self, app_main: Any) -> None:
        assert app_main._extract_open_path_arg(["prog", "--open-path", "D:/dir"]) == "D:/dir"
        assert app_main._extract_open_path_arg(["prog"]) is None

    def test_resolve_file_points_to_dirname(self, app_main: Any, tmp_path: Path) -> None:
        """文件路径 → 其所在目录（双击文件启动的导航语义）。"""
        file_path = tmp_path / "a.txt"
        file_path.write_text("x", encoding="utf-8")
        result = app_main._resolve_initial_navigate_path(["prog", "--open-path", str(file_path)])
        assert result == str(tmp_path)

    def test_resolve_dir_keeps_dir(self, app_main: Any, tmp_path: Path) -> None:
        result = app_main._resolve_initial_navigate_path(["prog", "--open-path", str(tmp_path)])
        assert result == str(tmp_path)

    def test_resolve_missing_returns_none(self, app_main: Any, tmp_path: Path) -> None:
        result = app_main._resolve_initial_navigate_path(
            ["prog", "--open-path", str(tmp_path / "nope.txt")]
        )
        assert result is None

    def test_resolve_without_arg_returns_none(self, app_main: Any) -> None:
        assert app_main._resolve_initial_navigate_path(["prog"]) is None


class TestRuntimeInstanceInfo:
    """runtime_instance.json 写/读/删往返（重定向到 tmp_path）。"""

    def test_roundtrip(self, instance_guard: Any, tmp_path: Path, monkeypatch: Any) -> None:
        monkeypatch.setattr(instance_guard, "get_app_data_path", lambda: str(tmp_path))

        instance_guard._write_runtime_instance_info()

        info = instance_guard._read_runtime_instance_info()
        assert info is not None
        assert info["pid"] > 0
        assert isinstance(info["argv"], list)
        assert "exe_path" in info

        # 不匹配的 expected_pid 不得删除
        instance_guard._remove_runtime_instance_info(expected_pid=-1)
        assert (tmp_path / "runtime_instance.json").exists()

        # 匹配的 expected_pid 删除
        instance_guard._remove_runtime_instance_info(expected_pid=info["pid"])
        assert not (tmp_path / "runtime_instance.json").exists()
        assert instance_guard._read_runtime_instance_info() is None

    def test_read_missing_returns_none(
        self, instance_guard: Any, tmp_path: Path, monkeypatch: Any
    ) -> None:
        monkeypatch.setattr(instance_guard, "get_app_data_path", lambda: str(tmp_path))
        assert instance_guard._read_runtime_instance_info() is None

    def test_read_corrupted_returns_none(
        self, instance_guard: Any, tmp_path: Path, monkeypatch: Any
    ) -> None:
        monkeypatch.setattr(instance_guard, "get_app_data_path", lambda: str(tmp_path))
        (tmp_path / "runtime_instance.json").write_text("{broken", encoding="utf-8")
        assert instance_guard._read_runtime_instance_info() is None


class _FakeWin32Function:
    """记录 argtypes/restype 赋值的可调用桩。"""

    def __init__(self, result: Any = None) -> None:
        self.result = result
        self.argtypes = None
        self.restype = None

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.result


class _FakeKernel32:
    """CreateMutexW 桩：固定句柄与固定 GetLastError 返回值。"""

    def __init__(self, mutex_handle: int, last_error: int) -> None:
        self._last_error = last_error
        self.CreateMutexW = _FakeWin32Function(mutex_handle)
        self.closed_handles: list[int] = []

    def GetLastError(self) -> int:
        return self._last_error

    def CloseHandle(self, handle: int) -> bool:
        self.closed_handles.append(handle)
        return True


class TestSingleInstanceAcquisition:
    """单实例互斥体：第二个实例必须静默快速退出，不得弹模态框。"""

    def test_second_instance_exits_zero_without_dialog(
        self, instance_guard: Any, monkeypatch: Any
    ) -> None:
        """ERROR_ALREADY_EXISTS → SystemExit(0)，关闭句柄，不调用任何弹窗。"""
        import ctypes
        from types import SimpleNamespace

        fake = _FakeKernel32(mutex_handle=4242, last_error=183)
        monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=fake))
        dialog_calls: list[Any] = []
        error_calls: list[Any] = []
        monkeypatch.setattr(
            instance_guard,
            "_show_already_running_dialog_and_handle_restart",
            lambda handle: dialog_calls.append(handle),
        )
        monkeypatch.setattr(
            instance_guard,
            "_show_error_box",
            lambda *args: error_calls.append(args),
        )

        with pytest.raises(SystemExit) as exc_info:
            instance_guard._acquire_single_instance()

        assert exc_info.value.code == 0
        assert dialog_calls == []
        assert error_calls == []
        assert fake.closed_handles == [4242]

    def test_first_instance_returns_mutex_handle(
        self, instance_guard: Any, monkeypatch: Any
    ) -> None:
        """首个实例取得句柄后直接返回，且不关闭句柄。"""
        import ctypes
        from types import SimpleNamespace

        fake = _FakeKernel32(mutex_handle=4242, last_error=0)
        monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=fake))

        assert instance_guard._acquire_single_instance() == 4242
        assert fake.closed_handles == []

    def test_mutex_name_is_stable(self, instance_guard: Any) -> None:
        """命名互斥体名称是跨进程契约，不得改动。"""
        assert instance_guard._MUTEX_NAME == "Sopeek_SingleInstance_Mutex"


class TestProcessGuards:
    """进程守卫纯函数边界（未运行 Windows 时保守为 False/None）。"""

    def test_is_process_running_invalid_pid(self, instance_guard: Any) -> None:
        if sys.platform != "win32":
            pytest.skip("仅 Windows 上验证")
        assert instance_guard._is_process_running(0) is False
        assert instance_guard._is_process_running(-5) is False

    def test_get_process_image_path_invalid_pid(self, instance_guard: Any) -> None:
        if sys.platform != "win32":
            pytest.skip("仅 Windows 上验证")
        assert instance_guard._get_process_image_path(0) is None

    def test_terminate_process_invalid_pid(self, instance_guard: Any) -> None:
        if sys.platform != "win32":
            pytest.skip("仅 Windows 上验证")
        ok, msg = instance_guard._terminate_process(0)
        assert ok is False
        assert "无效" in msg


class FakeV2Settings:
    """桩 V2 设置管理器（记录 load 调用，防真实数据文件被触碰）。"""

    def __init__(self) -> None:
        self.loaded = False

    def load(self):
        self.loaded = True
        return {"version": 2}


class TestSettingsInit:
    """设置管理器提前初始化（挂到 app.settings_manager）。"""

    def test_init_settings_manager_uses_v2(self, qapp: Any, app_main: Any, monkeypatch: Any) -> None:
        fake = FakeV2Settings()
        monkeypatch.setattr(
            "sopeek.core.managers.settings_manager_v2.SettingsManagerV2",
            lambda: fake,
        )
        app_main._init_settings_manager(qapp)
        assert qapp.settings_manager is fake
        assert fake.loaded is True


class TestHardwareAccelerationRelaunch:
    """使用硬件加速：经独显启动器重启的决策（不实际启动进程）。"""

    def test_marker_prevents_recursive_relaunch(
        self, app_main: Any, monkeypatch: Any
    ) -> None:
        """子进程已带 SPK_GPU_LAUNCHED 标记时直接继续，不再读设置。"""
        monkeypatch.setenv(app_main._GPU_LAUNCHED_ENV, "1")
        called = {"settings": False}

        def _fake_enabled() -> bool:
            called["settings"] = True
            return True

        monkeypatch.setattr(
            app_main, "_hardware_acceleration_enabled", _fake_enabled
        )
        assert app_main._maybe_relaunch_with_gpu_launcher(["prog"]) is False
        assert called["settings"] is False

    def test_enabled_launches_launcher_with_marker(
        self, app_main: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """开启且启动器就绪：拉起启动器并注入防递归标记与父 PID。"""
        exe = tmp_path / "SPK-Launcher.exe"
        exe.write_bytes(b"MZ")
        monkeypatch.delenv(app_main._GPU_LAUNCHED_ENV, raising=False)
        monkeypatch.setattr(
            app_main, "_hardware_acceleration_enabled", lambda: True
        )
        monkeypatch.setattr(app_main, "_gpu_launcher_ready", lambda: True)

        import sopeek.core.native.platform_gpu as gpu_mod

        monkeypatch.setattr(gpu_mod, "launcher_exe_path", lambda: exe)
        calls: dict[str, Any] = {}

        def _fake_popen(cmd: Any, **kwargs: Any) -> object:
            calls["cmd"] = cmd
            calls["kwargs"] = kwargs
            return object()

        monkeypatch.setattr(app_main.subprocess, "Popen", _fake_popen)
        argv = ["prog", "--open-path", "C:\\tmp"]
        assert app_main._maybe_relaunch_with_gpu_launcher(argv) is True
        assert calls["cmd"] == [str(exe), "--open-path", "C:\\tmp"]
        env = calls["kwargs"]["env"]
        assert env[app_main._GPU_LAUNCHED_ENV] == "1"
        assert env[app_main._GPU_PARENT_PID_ENV] == str(os.getpid())

    def test_unavailable_launcher_falls_back(
        self, app_main: Any, monkeypatch: Any
    ) -> None:
        """启动器缺失/导出校验失败：不拉起进程，继续直启。"""
        monkeypatch.delenv(app_main._GPU_LAUNCHED_ENV, raising=False)
        monkeypatch.setattr(
            app_main, "_hardware_acceleration_enabled", lambda: True
        )
        monkeypatch.setattr(app_main, "_gpu_launcher_ready", lambda: False)
        called = {"popen": False}

        def _fake_popen(*args: Any, **kwargs: Any) -> object:
            called["popen"] = True
            return object()

        monkeypatch.setattr(app_main.subprocess, "Popen", _fake_popen)
        assert app_main._maybe_relaunch_with_gpu_launcher(["prog"]) is False
        assert called["popen"] is False


class TestStartupController:
    """StartupController 的清理链路。"""

    @pytest.fixture
    def controller(self, qapp: Any, startup: Any) -> Any:
        from PySide6.QtWidgets import QWidget

        return startup.StartupController(qapp, QWidget())

    def test_cleanup_stops_heartbeat(self, controller: Any) -> None:
        """cleanup 停止心跳，异常不抛出；无预热线程时安全。"""
        stopped: list = []

        class _FakeHeartbeat:
            def stop_all(self):
                stopped.append(True)

        controller._heartbeat = _FakeHeartbeat()
        controller.cleanup()
        assert stopped == [True]
        assert controller._warmup_thread is None

    def test_run_thumbnail_cleanup_passes_configured_period(
        self, controller: Any, monkeypatch: Any
    ) -> None:
        """清理周期参数透传到 clean_thumbnails（修复硬编码 7 天）。"""
        from sopeek.core.managers import thumbnail_manager as tm_mod

        received: list = []

        def _fake_clean(cleanup_period_days=None, max_cache_size=2000):
            received.append(cleanup_period_days)
            return (0, 0)

        monkeypatch.setattr(tm_mod, "clean_thumbnails", _fake_clean)
        controller._run_thumbnail_cleanup(123.0, 30)
        assert received == [30]

    def test_schedule_thumbnail_cleanup_reads_config_period(
        self, controller: Any, monkeypatch: Any
    ) -> None:
        """调度读取 cache_cleanup_period 并在执行时按配置值调用。"""
        import sopeek.app.startup as startup_mod
        from sopeek.core.managers import thumbnail_manager as tm_mod

        calls: list = []
        scheduled: list = []

        class _Settings:
            def get(self, key, default=None):
                values = {
                    "file_selector.auto_clear_thumbnail_cache": True,
                    "file_selector.cache_cleanup_period": 30,
                    "file_selector.last_cleanup_time": None,
                }
                return values.get(key, default)

            def set(self, key, value):
                pass

            def save(self):
                pass

        class _App:
            settings_manager = _Settings()

        controller.app = _App()
        monkeypatch.setattr(
            tm_mod,
            "clean_thumbnails",
            lambda cleanup_period_days=None, max_cache_size=2000: (
                calls.append(cleanup_period_days),
                (0, 0),
            )[1],
        )
        monkeypatch.setattr(
            startup_mod.QTimer,
            "singleShot",
            lambda ms, cb: scheduled.append((ms, cb)),
        )
        controller._schedule_thumbnail_cleanup()
        assert len(scheduled) == 1
        scheduled[0][1]()  # 执行被调度的清理回调
        assert calls == [30]


class TestStartupWarmupThread:
    """预热线程 run()（stub FFmpeg 底层预热入口，同步直调不启线程）。"""

    def test_run_warmups_are_invoked(self, startup: Any, monkeypatch: Any) -> None:
        calls: list = []

        def _ffmpeg():
            calls.append("ffmpeg")

        monkeypatch.setattr(
            "sopeek.core.native.bridges.media_probe.warmup_ffmpeg_tools", _ffmpeg
        )
        thread = startup.StartupWarmupThread()
        thread.run()
        assert calls == ["ffmpeg"]
        assert thread.is_done

    def test_run_isolates_failures(self, startup: Any, monkeypatch: Any) -> None:
        """FFmpeg 预热失败不影响启动任务完成。"""
        calls: list = []

        def _ffmpeg():
            calls.append("attempted")
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "sopeek.core.native.bridges.media_probe.warmup_ffmpeg_tools", _ffmpeg
        )
        thread = startup.StartupWarmupThread()
        thread.run()
        assert calls == ["attempted"]
        assert thread.is_done
