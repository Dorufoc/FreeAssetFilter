# -*- coding: utf-8 -*-
# targets: freeassetfilter.app.main, freeassetfilter.app.instance_guard,
#          freeassetfilter.app.startup
"""新版应用引导层（app/ 包）集成测试。

引导层已拆分为三个模块（main / instance_guard / startup），模块级零副作用
（导入不再安装 fd 捕获 / faulthandler / 异常钩子），本文件直接导入并覆盖：

* 内部子进程参数分流（--faf-thumbnail-worker）
* 右键 ``--open-path`` 解析与初始导航路径推导
* 运行时实例信息（runtime_instance.json）写/读/删往返
* Windows 进程守卫纯函数边界
* 设置管理器提前初始化（挂 app.settings_manager）
* StartupController 清理链路与 StartupWarmupThread 预热顺序
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def app_main() -> Any:
    """导入引导层 main 模块（模块级无副作用）。"""
    import freeassetfilter.app.main as main_module

    return main_module


@pytest.fixture
def instance_guard() -> Any:
    """导入单实例守卫模块。"""
    import freeassetfilter.app.instance_guard as guard_module

    return guard_module


@pytest.fixture
def startup() -> Any:
    """导入启动任务编排模块。"""
    import freeassetfilter.app.startup as startup_module

    return startup_module


class TestInternalWorkerArgs:
    """--faf-thumbnail-worker 内部分流。"""

    def test_thumbnail_worker_args(self, app_main: Any) -> None:
        argv = ["prog", "--faf-thumbnail-worker", "C:/v.mp4", "1.4", "1"]
        kind, payload = app_main._parse_internal_worker_args(argv)
        assert kind == "thumbnail"
        assert payload["file_path"] == "C:/v.mp4"
        assert payload["dpi_scale"] == "1.4"
        assert payload["prefer_native"] == "1"

    def test_normal_args_returns_none(self, app_main: Any) -> None:
        assert app_main._parse_internal_worker_args(["prog"]) == (None, {})

    def test_insufficient_worker_args_returns_none(self, app_main: Any) -> None:
        assert app_main._parse_internal_worker_args(
            ["prog", "--faf-thumbnail-worker"]
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
            "freeassetfilter.core.managers.settings_manager_v2.SettingsManagerV2",
            lambda: fake,
        )
        app_main._init_settings_manager(qapp)
        assert qapp.settings_manager is fake
        assert fake.loaded is True


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


class TestStartupWarmupThread:
    """预热线程 run()（stub 全部底层预热入口，同步直调不启线程）。"""

    def test_run_warmups_are_invoked(self, startup: Any, monkeypatch: Any) -> None:
        calls: list = []

        def _ffmpeg():
            calls.append("ffmpeg")

        def _lut_cpp():
            calls.append("lut_cpp")

        def _lut_gen():
            calls.append("lut_gen")

        monkeypatch.setattr(
            "freeassetfilter.core.native.bridges.media_probe.warmup_ffmpeg_tools", _ffmpeg
        )
        monkeypatch.setattr(
            "freeassetfilter.core.native.src.cpp_lut_preview.warmup", _lut_cpp
        )
        monkeypatch.setattr(
            "freeassetfilter.core.native.bridges.lut_preview_generator.get_preview_generator",
            _lut_gen,
        )
        startup.StartupWarmupThread().run()
        assert calls == ["ffmpeg", "lut_cpp", "lut_gen"]

    def test_run_isolates_failures(self, startup: Any, monkeypatch: Any) -> None:
        """FFmpeg 预热失败不影响 LUT 预热（逐项隔离）。"""
        calls: list = []

        def _ffmpeg():
            raise RuntimeError("boom")

        def _lut_cpp():
            calls.append("lut_cpp")

        def _lut_gen():
            calls.append("lut_gen")

        monkeypatch.setattr(
            "freeassetfilter.core.native.bridges.media_probe.warmup_ffmpeg_tools", _ffmpeg
        )
        monkeypatch.setattr(
            "freeassetfilter.core.native.src.cpp_lut_preview.warmup", _lut_cpp
        )
        monkeypatch.setattr(
            "freeassetfilter.core.native.bridges.lut_preview_generator.get_preview_generator",
            _lut_gen,
        )
        startup.StartupWarmupThread().run()
        assert calls == ["lut_cpp", "lut_gen"]
