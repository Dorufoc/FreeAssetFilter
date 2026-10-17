# -*- coding: utf-8 -*-
"""启动期提权自愈（floating-pool-window 任务 13，办法一）单元测试。

覆盖 ``freeassetfilter.app.main`` 的 ``_offer_deelevation_restart_if_elevated``
与 ``_deelevation_restart_command``：

* 未提权 / 无 shell 可借壳 → 零副作用 ``"continue"``（不弹窗、不重启）；
* 提权 + 「立即重启」→ 先释放互斥体并清理实例信息，再恰一次调用 relaunch 并
  返回 ``"restart"``（由 ``main`` 负责 ``sys.exit(0)``）；
* 提权 + 「保持管理员权限」→ 绝不调用 relaunch，且本次运行内不再询问；
* relaunch 失败 → 弹告警（失败细节原样透传）、返回 ``"restart_failed"``、
  不退出（继续以提权态运行，交 task 14 原生兜底）。

测试纪律：**不启动任何真实进程、不弹出任何真实对话框** —— 所有副作用
（提权检测 / 去提权重启 / 互斥体 / 弹窗）一律 monkeypatch 为记录性假实现。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

import freeassetfilter.app.main as main_module
from freeassetfilter.app import instance_guard
from freeassetfilter.utils import elevation

#: 独立于生产代码推导仓库根：tests/unit/<本文件> → parents[2]。
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _Env:
    """提权自愈测试环境：记录全部假实现调用（含调用时序）。"""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.elevated = False
        self.deelevation_available = True
        self.dialog_choice = 1  # 0=「立即重启」 / 1=「保持管理员权限」
        self.relaunch_result: tuple[bool, str] = (True, "shell_token")
        self.mutex_handles: list[Any] = []
        self.relaunch_calls: list[tuple[list[str], Any]] = []
        self.alert_details: list[str] = []


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> _Env:
    """把提权自愈的全部副作用替换为记录性假实现。"""
    env = _Env()
    monkeypatch.setattr(main_module, "_deelevation_prompt_suppressed", False)

    def fake_is_process_elevated() -> bool:
        env.events.append("is_process_elevated")
        return env.elevated

    def fake_deelevation_available() -> bool:
        env.events.append("deelevation_available")
        return env.deelevation_available

    def fake_ask_dialog() -> int:
        env.events.append("ask_dialog")
        return env.dialog_choice

    def fake_alert(detail: str) -> None:
        env.events.append("alert")
        env.alert_details.append(detail)

    def fake_release_mutex(mutex_handle: Any) -> None:
        env.events.append("release_mutex")
        env.mutex_handles.append(mutex_handle)

    def fake_remove_runtime_instance_info(expected_pid: Any = None) -> None:
        env.events.append("remove_runtime_instance_info")

    def fake_relaunch(argv: Any, cwd: Any = None) -> tuple[bool, str]:
        env.events.append("relaunch")
        env.relaunch_calls.append((list(argv), cwd))
        return env.relaunch_result

    monkeypatch.setattr(elevation, "is_process_elevated", fake_is_process_elevated)
    monkeypatch.setattr(elevation, "deelevation_available", fake_deelevation_available)
    monkeypatch.setattr(elevation, "restart_de_elevated", fake_relaunch)
    monkeypatch.setattr(main_module, "_ask_deelevation_restart_choice", fake_ask_dialog)
    monkeypatch.setattr(main_module, "_show_deelevation_restart_failure", fake_alert)
    monkeypatch.setattr(instance_guard, "_release_mutex", fake_release_mutex)
    monkeypatch.setattr(
        instance_guard, "_remove_runtime_instance_info", fake_remove_runtime_instance_info
    )
    return env


class TestOfferDeElevationRestart:
    """``_offer_deelevation_restart_if_elevated`` 决策矩阵。"""

    def test_unelevated_skips_everything(self, env: _Env) -> None:
        """未提权：不弹窗、不重启、不碰互斥体，按现状继续。"""
        env.elevated = False
        action = main_module._offer_deelevation_restart_if_elevated(object())
        assert action == "continue"
        assert env.events == ["is_process_elevated"]
        assert env.relaunch_calls == []
        assert env.mutex_handles == []
        assert env.alert_details == []

    def test_elevated_without_deelevation_available_skips_dialog(self, env: _Env) -> None:
        """已提权但找不到 shell（无法去提权）：直接继续，不弹窗。"""
        env.elevated = True
        env.deelevation_available = False
        action = main_module._offer_deelevation_restart_if_elevated(object())
        assert action == "continue"
        assert env.events == ["is_process_elevated", "deelevation_available"]
        assert env.relaunch_calls == []
        assert env.alert_details == []

    def test_keep_never_relaunches_and_suppresses_reprompt(self, env: _Env) -> None:
        """「保持管理员权限」：不重启，且本次运行内不再询问。"""
        env.elevated = True
        env.dialog_choice = 1
        handle = object()
        assert main_module._offer_deelevation_restart_if_elevated(handle) == "keep"
        assert env.events == ["is_process_elevated", "deelevation_available", "ask_dialog"]
        assert env.relaunch_calls == []
        assert env.mutex_handles == []
        assert env.alert_details == []
        # 第二次调用在弹窗前短路（内存抑制，无新事件、无新副作用）
        assert main_module._offer_deelevation_restart_if_elevated(handle) == "continue"
        assert env.events == ["is_process_elevated", "deelevation_available", "ask_dialog"]

    def test_restart_releases_mutex_then_relaunches_once(self, env: _Env) -> None:
        """「立即重启」：先释放互斥体 → 清理实例信息 → 恰一次 relaunch。"""
        env.elevated = True
        env.dialog_choice = 0
        env.relaunch_result = (True, "shell_token")
        handle = object()
        action = main_module._offer_deelevation_restart_if_elevated(handle)
        assert action == "restart"
        # 时序钉死：新实例启动前互斥体必须已释放，否则会误判「已在运行」
        assert env.events == [
            "is_process_elevated",
            "deelevation_available",
            "ask_dialog",
            "release_mutex",
            "remove_runtime_instance_info",
            "relaunch",
        ]
        assert env.mutex_handles == [handle]
        assert len(env.relaunch_calls) == 1
        argv, cwd = env.relaunch_calls[0]
        assert argv == [sys.executable, "-m", "freeassetfilter.app.main"]
        assert isinstance(cwd, str)
        assert os.path.normcase(cwd) == os.path.normcase(str(_PROJECT_ROOT))
        assert env.alert_details == []

    def test_restart_failure_alerts_with_detail_and_returns_failed(self, env: _Env) -> None:
        """relaunch 失败：弹告警（细节原样）、返回 restart_failed、不退出。"""
        env.elevated = True
        env.dialog_choice = 0
        detail = (
            "explorer: explorer forwarding can carry a single target only "
            "(got 3 argv items); shell_token: CreateProcessWithTokenW failed "
            "(error 1314 ERROR_PRIVILEGE_NOT_HELD)"
        )
        env.relaunch_result = (False, detail)
        action = main_module._offer_deelevation_restart_if_elevated(object())
        assert action == "restart_failed"
        assert env.alert_details == [detail]
        assert len(env.relaunch_calls) == 1
        # 失败后继续以提权态运行；用户决定已做出，不再重复询问
        assert main_module._offer_deelevation_restart_if_elevated(object()) == "continue"
        assert env.alert_details == [detail]


class TestDeElevationRestartCommand:
    """重启目标命令行（源码 / 冻结两态约定）。"""

    def test_source_run_uses_module_entry_and_repo_root(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """源码运行：``python -m freeassetfilter.app.main`` + 仓库根 cwd。"""
        monkeypatch.delattr(sys, "frozen", raising=False)
        argv, cwd = main_module._deelevation_restart_command()
        assert argv == [sys.executable, "-m", "freeassetfilter.app.main"]
        assert os.path.normcase(cwd) == os.path.normcase(str(_PROJECT_ROOT))

    def test_frozen_run_uses_executable_and_its_directory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """冻结运行：直接重启自身 exe，cwd 取可执行文件所在目录。"""
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        argv, cwd = main_module._deelevation_restart_command()
        assert argv == [sys.executable]
        assert os.path.normcase(cwd) == os.path.normcase(os.path.dirname(sys.executable))


class TestDialogWrappers:
    """真实弹窗包装函数的参数契约（styled 组件参数，不弹真实窗口）。"""

    def test_choice_dialog_kwargs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """询问框：按钮顺序/类型正确，且显式 show_close=False（无 X 关闭歧义）。"""
        import freeassetfilter.ui.components.styled_dialog as styled_dialog

        calls: list[dict[str, Any]] = []

        def fake_ask(**kwargs: Any) -> int:
            calls.append(kwargs)
            return 1

        monkeypatch.setattr(styled_dialog, "ask_custom_dialog", fake_ask)
        assert main_module._ask_deelevation_restart_choice() == 1
        assert len(calls) == 1
        kwargs = calls[0]
        assert kwargs["buttons"] == ["立即重启", "保持管理员权限"]
        assert kwargs["dialog_type"] == "question"
        assert kwargs["show_close"] is False
        assert kwargs["title"]
        assert kwargs["message"]

    def test_failure_alert_kwargs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """失败告警：单一确认按钮、danger 类型、失败细节原样进入正文。"""
        import freeassetfilter.ui.components.styled_dialog as styled_dialog

        calls: list[dict[str, Any]] = []

        def fake_ask(**kwargs: Any) -> int:
            calls.append(kwargs)
            return 0

        monkeypatch.setattr(styled_dialog, "ask_custom_dialog", fake_ask)
        main_module._show_deelevation_restart_failure("some-detail-xyz")
        assert len(calls) == 1
        kwargs = calls[0]
        assert kwargs["buttons"] == ["我知道了"]
        assert kwargs["dialog_type"] == "danger"
        assert kwargs["show_close"] is False
        assert "some-detail-xyz" in kwargs["message"]
