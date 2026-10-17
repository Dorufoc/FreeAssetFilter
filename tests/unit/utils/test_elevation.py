#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``freeassetfilter.utils.elevation`` 单元测试（floating-pool-window 任务 12）。

测试纪律：
- **不启动任何真实进程**，也不触发真实 Win32 提权/启动 API —— 所有模块级
  绑定（``_open_process`` / ``_duplicate_token_ex`` ...）一律 monkeypatch 为
  记录性假实现；
- 唯一的真实 API 例外：``CommandLineToArgvW`` 纯字符串解析往返测试（仅证明
  引号算法与系统解析器兼容，不启动进程）；
- ``is_process_elevated`` / ``get_integrity_level`` 另有一组"真实环境自适应
  一致性"测试（只读自身令牌，不做任何修改）。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any, Callable, NoReturn, Sequence

import pytest

from freeassetfilter.utils import elevation

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="freeassetfilter.utils.elevation 为 Windows 专用模块",
)

_EXPECTED_EXPORTS = {
    "INTEGRITY_LEVEL_HIGH",
    "INTEGRITY_LEVEL_LOW",
    "INTEGRITY_LEVEL_MEDIUM",
    "INTEGRITY_LEVEL_SYSTEM",
    "deelevation_available",
    "get_integrity_level",
    "is_process_elevated",
    "quote_windows_args",
    "restart_de_elevated",
}

_ELEVATION_BINDINGS = (
    "_shell_execute_w",
    "_get_shell_window",
    "_get_window_thread_process_id",
    "_get_current_process",
    "_open_process",
    "_close_handle",
    "_wait_for_single_object",
    "_open_process_token",
    "_get_token_information",
    "_get_sid_sub_authority_count",
    "_get_sid_sub_authority",
    "_duplicate_token_ex",
    "_create_process_with_token_w",
)

_QUOTE_CASES: list[tuple[tuple[str, ...], str]] = [
    ((), ""),
    (("plain",), "plain"),
    (("a\\b",), "a\\b"),
    (("a b", "c"), '"a b" c'),
    (("",), '""'),
    (('say"hi',), '"say\\"hi"'),
    (("C:\\Program Files",), '"C:\\Program Files"'),
    (("C:\\Program Files\\",), '"C:\\Program Files\\\\"'),
    (("a\\b", "c d"), 'a\\b "c d"'),
    (("tab\there",), '"tab\there"'),
]


# ────────────────────────────── 假实现工具 ──────────────────────────────


def _fail_if_called(*args: Any, **kwargs: Any) -> NoReturn:
    """替代绝不应被调用的函数（未提权路径 / 已成功路径）。"""
    raise AssertionError("该函数不应被调用")


def _make_close_spy(closed: list[Any]) -> Callable[[Any], bool]:
    """构造记录句柄的 ``CloseHandle`` 假实现（HANDLE 取 .value，其余原样）。"""

    def spy(handle: Any) -> bool:
        if isinstance(handle, ctypes.c_void_p):
            closed.append(handle.value)
        else:
            closed.append(handle)
        return True

    return spy


def _install_token_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    elevated_value: int = 1,
    open_token_ok: bool = True,
    info_ok: bool = True,
) -> tuple[list[Any], list[tuple[str, Any]]]:
    """安装 ``is_process_elevated`` 所需的令牌链假实现。

    Returns:
        ``(closed, calls)``：已关闭句柄列表与调用记录。
    """
    closed: list[Any] = []
    calls: list[tuple[str, Any]] = []
    token_value = 0x42

    def fake_get_current_process() -> int:
        return 0xFFFF

    def fake_open_process_token(process: Any, access: int, out: Any) -> bool:
        calls.append(("open_process_token", (process, access)))
        if not open_token_ok:
            return False
        out._obj.value = token_value
        return True

    def fake_get_token_information(
        token: Any, info_class: int, buffer: Any, size: int, returned: Any
    ) -> bool:
        calls.append(("get_token_information", (info_class, buffer is None, size)))
        if not info_ok:
            return False
        if info_class == elevation._TOKEN_ELEVATION_CLASS:
            buffer._obj.TokenIsElevated = elevated_value
        return True

    monkeypatch.setattr(elevation, "_get_current_process", fake_get_current_process)
    monkeypatch.setattr(elevation, "_open_process_token", fake_open_process_token)
    monkeypatch.setattr(elevation, "_get_token_information", fake_get_token_information)
    monkeypatch.setattr(elevation, "_close_handle", _make_close_spy(closed))
    return closed, calls


def _install_integrity_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    needed_size: int = 28,
    second_call_ok: bool = True,
    sid_value: int | None = 0x1000,
    count_value: int = 1,
    count_ok: bool = True,
    sub_ok: bool = True,
) -> dict[str, Any]:
    """安装 ``get_integrity_level`` 所需的完整性级别假链。"""
    closed: list[Any] = []
    sizes: list[int] = []
    sid_args: list[Any] = []

    def fake_get_current_process() -> int:
        return 0xFFFF

    def fake_open_process_token(process: Any, access: int, out: Any) -> bool:
        out._obj.value = 0x42
        return True

    def fake_get_token_information(
        token: Any, info_class: int, buffer: Any, size: int, returned: Any
    ) -> bool:
        sizes.append(size)
        if buffer is None:
            returned._obj.value = needed_size
            return False
        if not second_call_ok:
            return False
        if sid_value is not None:
            label = ctypes.cast(
                buffer._obj, ctypes.POINTER(elevation._TOKEN_MANDATORY_LABEL)
            )
            label.contents.Label.Sid = sid_value
        return True

    def fake_count(sid: Any) -> Any:
        sid_args.append(sid)
        if not count_ok:
            return None
        return ctypes.pointer(ctypes.c_ubyte(count_value))

    def fake_sub_authority(sid: Any, index: int) -> Any:
        sid_args.append((sid, index))
        if not sub_ok:
            return None
        return ctypes.pointer(wintypes.DWORD(0x2000))

    monkeypatch.setattr(elevation, "_get_current_process", fake_get_current_process)
    monkeypatch.setattr(elevation, "_open_process_token", fake_open_process_token)
    monkeypatch.setattr(elevation, "_get_token_information", fake_get_token_information)
    monkeypatch.setattr(elevation, "_get_sid_sub_authority_count", fake_count)
    monkeypatch.setattr(elevation, "_get_sid_sub_authority", fake_sub_authority)
    monkeypatch.setattr(elevation, "_close_handle", _make_close_spy(closed))
    return {"closed": closed, "sizes": sizes, "sid_args": sid_args}


def _install_shell_chain(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pid: int = 4242,
    process_handle: Any = 0x111,
    open_token_ok: bool = True,
    duplicate_ok: bool = True,
    duplicate_error: int = 0,
    create_ok: bool = True,
    create_error: int = 0,
) -> dict[str, Any]:
    """安装 ``_relaunch_via_shell_token`` 的完整假链；返回记录字典。"""
    closed: list[Any] = []
    wait_calls: list[tuple[Any, int]] = []
    records: dict[str, Any] = {"closed": closed, "wait_calls": wait_calls}

    def fake_get_shell_window() -> int:
        return 0x1234

    def fake_get_window_thread_process_id(hwnd: Any, pid_out: Any) -> int:
        pid_out._obj.value = pid
        return 1

    def fake_open_process(access: int, inherit: bool, target_pid: int) -> Any:
        records["open_process"] = (access, inherit, target_pid)
        ctypes.set_last_error(87)
        return process_handle

    def fake_open_process_token(process: Any, access: int, out: Any) -> bool:
        records["open_token"] = (process, access)
        if not open_token_ok:
            ctypes.set_last_error(5)
            return False
        out._obj.value = 0x222
        return True

    def fake_duplicate_token_ex(
        token: Any, access: int, attrs: Any, impersonation: int, token_type: int, out: Any
    ) -> bool:
        records["duplicate"] = (token, access, attrs, impersonation, token_type)
        if not duplicate_ok:
            ctypes.set_last_error(duplicate_error)
            return False
        out._obj.value = 0x444
        return True

    def fake_create_process_with_token_w(
        token: Any,
        logon_flags: int,
        app_name: Any,
        cmdline: Any,
        flags: int,
        env: Any,
        cwd: Any,
        startup_ptr: Any,
        process_info_ptr: Any,
    ) -> bool:
        records["create"] = {
            "token": token.value if isinstance(token, ctypes.c_void_p) else token,
            "logon_flags": logon_flags,
            "app_name": app_name,
            "cmdline": cmdline.value,
            "flags": flags,
            "env": env,
            "cwd": cwd,
            "startup_cb": startup_ptr._obj.cb,
        }
        if not create_ok:
            ctypes.set_last_error(create_error)
            return False
        process_info_ptr._obj.hProcess = 0x555
        process_info_ptr._obj.hThread = 0x333
        return True

    def fake_wait(handle: Any, timeout: int) -> int:
        wait_calls.append((handle, timeout))
        return 0

    monkeypatch.setattr(elevation, "_get_shell_window", fake_get_shell_window)
    monkeypatch.setattr(
        elevation, "_get_window_thread_process_id", fake_get_window_thread_process_id
    )
    monkeypatch.setattr(elevation, "_open_process", fake_open_process)
    monkeypatch.setattr(elevation, "_open_process_token", fake_open_process_token)
    monkeypatch.setattr(elevation, "_duplicate_token_ex", fake_duplicate_token_ex)
    monkeypatch.setattr(
        elevation, "_create_process_with_token_w", fake_create_process_with_token_w
    )
    monkeypatch.setattr(elevation, "_wait_for_single_object", fake_wait)
    monkeypatch.setattr(elevation, "_close_handle", _make_close_spy(closed))
    return records


# ────────────────────────────── 模块接口冻结 ──────────────────────────────


class TestModuleSurface:
    """公开 API / 常量 / 机制顺序冻结（任务 13/14 依赖）。"""

    def test_frozen_exports(self) -> None:
        assert set(elevation.__all__) == _EXPECTED_EXPORTS

    def test_public_api_is_callable(self) -> None:
        for name in (
            "deelevation_available",
            "get_integrity_level",
            "is_process_elevated",
            "quote_windows_args",
            "restart_de_elevated",
        ):
            assert callable(getattr(elevation, name))

    def test_integrity_level_constants(self) -> None:
        assert elevation.INTEGRITY_LEVEL_LOW == 0x1000
        assert elevation.INTEGRITY_LEVEL_MEDIUM == 0x2000
        assert elevation.INTEGRITY_LEVEL_HIGH == 0x3000
        assert elevation.INTEGRITY_LEVEL_SYSTEM == 0x4000

    def test_mechanism_order_frozen(self) -> None:
        assert elevation._MECHANISM_ORDER == ("explorer", "shell_token")

    def test_bindings_are_module_level_seams(self) -> None:
        for name in _ELEVATION_BINDINGS:
            assert hasattr(elevation, name)

    def test_no_qt_dependency(self) -> None:
        module_path = elevation.__file__
        assert module_path is not None
        source = Path(module_path).read_text(encoding="utf-8")
        assert "PySide6" not in source
        assert "PyQt" not in source


# ────────────────────────────── 真实环境自适应 ──────────────────────────────


class TestRealEnvironment:
    """真实环境一致性（只读自身令牌；本机已提权时同样成立）。"""

    def test_elevation_matches_integrity_level(self) -> None:
        integrity = elevation.get_integrity_level()
        if integrity is None:
            pytest.skip("无法读取当前进程完整性级别（环境不支持）")
        assert elevation.is_process_elevated() is (
            integrity >= elevation.INTEGRITY_LEVEL_HIGH
        )

    def test_deelevation_available_is_bool_and_implies_elevation(self) -> None:
        available = elevation.deelevation_available()
        assert isinstance(available, bool)
        if not elevation.is_process_elevated():
            assert available is False


# ────────────────────────────── is_process_elevated ──────────────────────────────


class TestIsProcessElevated:
    """``is_process_elevated``：提权检测 + fail-safe + 句柄关闭。"""

    @pytest.mark.parametrize(
        "binding",
        ["_open_process_token", "_get_token_information", "_get_current_process"],
    )
    def test_returns_false_when_binding_missing(
        self, monkeypatch: pytest.MonkeyPatch, binding: str
    ) -> None:
        monkeypatch.setattr(elevation, binding, None)
        assert elevation.is_process_elevated() is False

    def test_open_token_failure_returns_false_without_close(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        closed, _ = _install_token_fakes(monkeypatch, open_token_ok=False)
        assert elevation.is_process_elevated() is False
        assert closed == []

    def test_token_information_failure_returns_false_and_closes_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        closed, _ = _install_token_fakes(monkeypatch, info_ok=False)
        assert elevation.is_process_elevated() is False
        assert closed == [0x42]

    def test_elevated_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        closed, calls = _install_token_fakes(monkeypatch, elevated_value=1)
        assert elevation.is_process_elevated() is True
        assert calls == [
            ("open_process_token", (0xFFFF, 0x0008)),
            (
                "get_token_information",
                (20, False, ctypes.sizeof(elevation._TOKEN_ELEVATION)),
            ),
        ]
        assert closed == [0x42]

    def test_elevated_false_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        closed, _ = _install_token_fakes(monkeypatch, elevated_value=0)
        assert elevation.is_process_elevated() is False
        assert closed == [0x42]

    def test_exception_returns_false_and_closes_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        closed, _ = _install_token_fakes(monkeypatch)

        def boom(*args: Any, **kwargs: Any) -> NoReturn:
            raise RuntimeError("boom")

        monkeypatch.setattr(elevation, "_get_token_information", boom)
        assert elevation.is_process_elevated() is False
        assert closed == [0x42]


# ────────────────────────────── get_integrity_level ──────────────────────────────


class TestGetIntegrityLevel:
    """``get_integrity_level``：完整性级别读取 + fail-safe + 句柄关闭。"""

    @pytest.mark.parametrize(
        "binding",
        ["_open_process_token", "_get_token_information", "_get_current_process"],
    )
    def test_returns_none_when_binding_missing(
        self, monkeypatch: pytest.MonkeyPatch, binding: str
    ) -> None:
        monkeypatch.setattr(elevation, binding, None)
        assert elevation.get_integrity_level() is None

    def test_open_token_failure_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        closed, _ = _install_token_fakes(monkeypatch, open_token_ok=False)
        assert elevation.get_integrity_level() is None
        assert closed == []

    def test_needed_size_zero_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        records = _install_integrity_fakes(monkeypatch, needed_size=0)
        assert elevation.get_integrity_level() is None
        assert records["sizes"] == [0]
        assert records["closed"] == [0x42]

    def test_second_query_failure_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        records = _install_integrity_fakes(monkeypatch, second_call_ok=False)
        assert elevation.get_integrity_level() is None
        assert records["sizes"] == [0, 28]
        assert records["closed"] == [0x42]

    def test_success_returns_sub_authority_rid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        records = _install_integrity_fakes(
            monkeypatch, sid_value=0x1000, count_value=1
        )
        assert elevation.get_integrity_level() == 0x2000
        assert records["sizes"] == [0, 28]
        assert records["sid_args"] == [0x1000, (0x1000, 0)]
        assert records["closed"] == [0x42]

    def test_null_sid_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        records = _install_integrity_fakes(monkeypatch, sid_value=None)
        assert elevation.get_integrity_level() is None
        assert records["sid_args"] == []

    def test_sid_count_null_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        records = _install_integrity_fakes(monkeypatch, count_ok=False)
        assert elevation.get_integrity_level() is None
        assert records["sid_args"] == [0x1000]

    def test_sid_count_zero_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        records = _install_integrity_fakes(monkeypatch, count_value=0)
        assert elevation.get_integrity_level() is None
        assert records["sid_args"] == [0x1000]

    def test_sub_authority_null_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        records = _install_integrity_fakes(monkeypatch, sub_ok=False)
        assert elevation.get_integrity_level() is None
        assert records["sid_args"] == [0x1000, (0x1000, 0)]

    def test_exception_returns_none_and_closes_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        records = _install_integrity_fakes(monkeypatch)

        def boom(*args: Any, **kwargs: Any) -> NoReturn:
            raise RuntimeError("boom")

        monkeypatch.setattr(elevation, "_get_sid_sub_authority_count", boom)
        assert elevation.get_integrity_level() is None
        assert records["closed"] == [0x42]


# ────────────────────────────── deelevation_available ──────────────────────────────


class TestDeelevationAvailable:
    """``deelevation_available``：提权 + shell 窗口双重条件。"""

    def test_true_when_elevated_and_shell_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_token_fakes(monkeypatch, elevated_value=1)
        monkeypatch.setattr(elevation, "_get_shell_window", lambda: 0x1234)
        assert elevation.deelevation_available() is True

    def test_false_without_shell_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_token_fakes(monkeypatch, elevated_value=1)
        monkeypatch.setattr(elevation, "_get_shell_window", lambda: 0)
        assert elevation.deelevation_available() is False

    def test_false_when_not_elevated_without_touching_shell(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_token_fakes(monkeypatch, elevated_value=0)
        monkeypatch.setattr(elevation, "_get_shell_window", _fail_if_called)
        assert elevation.deelevation_available() is False


# ────────────────────────────── shell 窗口 / PID 查询 ──────────────────────────────


class TestGetShellWindowHandle:
    """``_get_shell_window_handle``：HWND 获取与 fail-safe。"""

    def test_none_binding_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(elevation, "_get_shell_window", None)
        assert elevation._get_shell_window_handle() is None

    def test_null_window_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(elevation, "_get_shell_window", lambda: 0)
        assert elevation._get_shell_window_handle() is None

    def test_returns_integer_handle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(elevation, "_get_shell_window", lambda: 0x1234)
        assert elevation._get_shell_window_handle() == 0x1234

    def test_exception_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom() -> NoReturn:
            raise OSError("boom")

        monkeypatch.setattr(elevation, "_get_shell_window", boom)
        assert elevation._get_shell_window_handle() is None


class TestGetShellPid:
    """``_get_shell_pid``：shell 进程 PID 查询与 fail-safe。"""

    def test_returns_none_without_shell_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(elevation, "_get_shell_window", lambda: 0)
        assert elevation._get_shell_pid() is None

    def test_returns_none_when_thread_lookup_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(elevation, "_get_shell_window", lambda: 0x1234)
        monkeypatch.setattr(elevation, "_get_window_thread_process_id", lambda hwnd, out: 0)
        assert elevation._get_shell_pid() is None

    def test_returns_none_when_pid_is_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(elevation, "_get_shell_window", lambda: 0x1234)
        monkeypatch.setattr(
            elevation, "_get_window_thread_process_id", lambda hwnd, out: 1
        )
        assert elevation._get_shell_pid() is None

    def test_returns_shell_pid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(elevation, "_get_shell_window", lambda: 0x1234)
        calls: list[Any] = []

        def fake_thread_pid(hwnd: Any, out: Any) -> int:
            calls.append(hwnd)
            out._obj.value = 4242
            return 1

        monkeypatch.setattr(elevation, "_get_window_thread_process_id", fake_thread_pid)
        assert elevation._get_shell_pid() == 4242
        assert calls == [0x1234]

    def test_returns_none_when_binding_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(elevation, "_get_shell_window", lambda: 0x1234)
        monkeypatch.setattr(elevation, "_get_window_thread_process_id", None)
        assert elevation._get_shell_pid() is None


# ────────────────────────────── 句柄清理 ──────────────────────────────


class TestCloseHandleQuietly:
    """``_close_handle_quietly``：清理路径绝不抛异常。"""

    def test_closes_truthy_handle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        closed: list[Any] = []
        monkeypatch.setattr(elevation, "_close_handle", _make_close_spy(closed))
        elevation._close_handle_quietly(0x42)
        assert closed == [0x42]

    @pytest.mark.parametrize("handle", [None, 0])
    def test_skips_falsy_handle(
        self, monkeypatch: pytest.MonkeyPatch, handle: Any
    ) -> None:
        monkeypatch.setattr(elevation, "_close_handle", _fail_if_called)
        elevation._close_handle_quietly(handle)

    def test_swallows_close_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(handle: Any) -> NoReturn:
            raise OSError("boom")

        monkeypatch.setattr(elevation, "_close_handle", boom)
        elevation._close_handle_quietly(0x42)

    def test_skips_when_binding_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(elevation, "_close_handle", None)
        elevation._close_handle_quietly(0x42)


# ────────────────────────────── quote_windows_args ──────────────────────────────


class TestQuoteWindowsArgs:
    """``quote_windows_args``：MSVCRT / CommandLineToArgvW 兼容引号。"""

    @pytest.mark.parametrize("argv, expected", _QUOTE_CASES)
    def test_fixed_forms(self, argv: Sequence[str], expected: str) -> None:
        assert elevation.quote_windows_args(argv) == expected

    def test_roundtrip_matches_command_line_to_argv_w(self) -> None:
        samples = [
            "plain",
            "a b",
            'say"hi',
            "C:\\Program Files",
            "",
            "back\\slash",
            "tab\there",
            "trail\\",
        ]
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        parse = shell32.CommandLineToArgvW
        parse.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
        parse.restype = ctypes.POINTER(wintypes.LPWSTR)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        local_free = kernel32.LocalFree
        local_free.argtypes = [wintypes.HLOCAL]
        local_free.restype = wintypes.HLOCAL

        command_line = "prog.exe " + elevation.quote_windows_args(samples)
        argc = ctypes.c_int(0)
        argv_ptr = parse(command_line, ctypes.byref(argc))
        assert argv_ptr, "CommandLineToArgvW 解析失败"
        try:
            parsed = [argv_ptr[index] for index in range(1, argc.value)]
        finally:
            local_free(argv_ptr)
        assert parsed == samples


# ────────────────────────────── 错误细节格式化 ──────────────────────────────


class TestDescribeWinError:
    """``_describe_win_error``：错误码格式化（1314 附可读名）。"""

    @pytest.mark.parametrize(
        "code, expected",
        [
            (1314, "1314 ERROR_PRIVILEGE_NOT_HELD"),
            (5, "5"),
            (87, "87"),
            (0, "0"),
        ],
    )
    def test_format(self, code: int, expected: str) -> None:
        assert elevation._describe_win_error(code) == expected


# ────────────────────────────── restart_de_elevated ──────────────────────────────


class TestRestartDeElevated:
    """``restart_de_elevated``：未提权契约 + 机制顺序 + 失败合并。"""

    def test_not_elevated_returns_contract_without_launch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(elevation, "is_process_elevated", lambda: False)
        monkeypatch.setattr(elevation, "_relaunch_via_explorer", _fail_if_called)
        monkeypatch.setattr(elevation, "_relaunch_via_shell_token", _fail_if_called)
        assert elevation.restart_de_elevated(["app.exe"]) == (False, "not elevated")

    def test_mechanism_order_and_failure_join(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(elevation, "is_process_elevated", lambda: True)
        calls: list[Any] = []

        def fake_explorer(argv: Sequence[str]) -> tuple[bool, str]:
            calls.append(("explorer", tuple(argv)))
            return False, "boom1"

        def fake_shell(
            argv: Sequence[str], cwd: str | None = None, *, wait: bool = False
        ) -> tuple[bool, str]:
            calls.append(("shell_token", tuple(argv), cwd))
            return False, "boom2"

        monkeypatch.setattr(elevation, "_relaunch_via_explorer", fake_explorer)
        monkeypatch.setattr(elevation, "_relaunch_via_shell_token", fake_shell)
        result = elevation.restart_de_elevated(["app.exe", "--flag"], cwd="C:\\repo")
        assert result == (False, "explorer: boom1; shell_token: boom2")
        assert calls == [
            ("explorer", ("app.exe", "--flag")),
            ("shell_token", ("app.exe", "--flag"), "C:\\repo"),
        ]

    def test_explorer_success_skips_shell_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(elevation, "is_process_elevated", lambda: True)
        monkeypatch.setattr(elevation, "_relaunch_via_explorer", lambda argv: (True, ""))
        monkeypatch.setattr(elevation, "_relaunch_via_shell_token", _fail_if_called)
        assert elevation.restart_de_elevated(["app.exe"]) == (True, "explorer")

    def test_shell_token_success_after_explorer_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(elevation, "is_process_elevated", lambda: True)
        monkeypatch.setattr(
            elevation, "_relaunch_via_explorer", lambda argv: (False, "no")
        )
        monkeypatch.setattr(
            elevation, "_relaunch_via_shell_token", lambda argv, cwd=None: (True, "")
        )
        assert elevation.restart_de_elevated(["app.exe"]) == (True, "shell_token")


# ────────────────────────────── _relaunch_via_explorer ──────────────────────────────


class TestRelaunchViaExplorer:
    """机制 1：Explorer 转发（单目标约束，真实实测语义）。"""

    def test_bindings_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(elevation, "_shell_execute_w", None)
        assert elevation._relaunch_via_explorer(["x"]) == (
            False,
            "shell32/user32 bindings unavailable",
        )

    @pytest.mark.parametrize("argv", [(), ("a", "b")])
    def test_multi_or_zero_targets_refused_without_shell_execute(
        self, monkeypatch: pytest.MonkeyPatch, argv: tuple[str, ...]
    ) -> None:
        monkeypatch.setattr(elevation, "_shell_execute_w", _fail_if_called)
        monkeypatch.setattr(elevation, "_get_shell_window", lambda: 0x1234)
        ok, detail = elevation._relaunch_via_explorer(argv)
        assert ok is False
        assert detail == (
            "explorer forwarding can carry a single target only "
            f"(got {len(argv)} argv items); it cannot forward extra arguments "
            "or a working directory"
        )

    def test_shell_window_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(elevation, "_shell_execute_w", _fail_if_called)
        monkeypatch.setattr(elevation, "_get_shell_window", lambda: 0)
        ok, detail = elevation._relaunch_via_explorer(["x"])
        assert ok is False
        assert detail == "shell window not found (GetShellWindow returned NULL)"

    def test_success_invokes_shell_execute_with_quoted_target(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: list[tuple[Any, ...]] = []

        def fake_shell_execute(
            hwnd: Any, op: str, file: str, params: str, directory: Any, show: int
        ) -> int:
            recorded.append((hwnd, op, file, params, directory, show))
            return 42

        monkeypatch.setattr(elevation, "_shell_execute_w", fake_shell_execute)
        monkeypatch.setattr(elevation, "_get_shell_window", lambda: 0x1234)
        ok, detail = elevation._relaunch_via_explorer(["C:\\Program Files\\app.exe"])
        assert (ok, detail) == (True, "")
        assert recorded == [
            (
                0x1234,
                "open",
                "explorer.exe",
                '"C:\\Program Files\\app.exe"',
                None,
                1,
            )
        ]

    @pytest.mark.parametrize(
        "raw_result, expected_code",
        [(None, 0), (0, 0), (2, 2), (5, 5), (8, 8), (32, 32)],
    )
    def test_failure_codes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        raw_result: Any,
        expected_code: int,
    ) -> None:
        monkeypatch.setattr(elevation, "_shell_execute_w", lambda *args: raw_result)
        monkeypatch.setattr(elevation, "_get_shell_window", lambda: 0x1234)
        ok, detail = elevation._relaunch_via_explorer(["x"])
        assert ok is False
        assert f"ShellExecuteW(explorer) returned {expected_code}" in detail
        assert "SE_ERR_FNF=2" in detail
        assert "SE_ERR_ACCESSDENIED=5" in detail

    def test_exception_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*args: Any) -> NoReturn:
            raise RuntimeError("boom")

        monkeypatch.setattr(elevation, "_shell_execute_w", boom)
        monkeypatch.setattr(elevation, "_get_shell_window", lambda: 0x1234)
        ok, detail = elevation._relaunch_via_explorer(["x"])
        assert (ok, detail) == (False, "ShellExecuteW raised RuntimeError: boom")


# ────────────────────────────── _relaunch_via_shell_token ──────────────────────────────


class TestRelaunchViaShellToken:
    """机制 2：借壳 shell 令牌创建进程（句柄链 + 参数协议）。"""

    _ARGV = ["C:\\Program Files\\x.exe", "a b"]
    _CMDLINE = '"C:\\Program Files\\x.exe" "a b"'

    def test_bindings_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(elevation, "_open_process", None)
        assert elevation._relaunch_via_shell_token(["x"]) == (
            False,
            "advapi32/kernel32 bindings unavailable",
        )

    def test_shell_process_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(elevation, "_get_shell_window", lambda: 0)
        ok, detail = elevation._relaunch_via_shell_token(["x"])
        assert ok is False
        assert detail == (
            "shell process not found (GetShellWindow/GetWindowThreadProcessId failed)"
        )

    def test_open_process_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        records = _install_shell_chain(monkeypatch, process_handle=None)
        ok, detail = elevation._relaunch_via_shell_token(["x"])
        assert ok is False
        assert detail == "OpenProcess(shell pid=4242) failed (error 87)"
        assert records["closed"] == []

    def test_open_process_token_failure_closes_process(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        records = _install_shell_chain(monkeypatch, open_token_ok=False)
        ok, detail = elevation._relaunch_via_shell_token(["x"])
        assert ok is False
        assert detail == "OpenProcessToken failed (error 5)"
        assert records["closed"] == [0x111]

    def test_duplicate_token_failure_reports_privilege_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        records = _install_shell_chain(
            monkeypatch,
            duplicate_ok=False,
            duplicate_error=elevation._ERROR_PRIVILEGE_NOT_HELD,
        )
        ok, detail = elevation._relaunch_via_shell_token(["x"])
        assert ok is False
        assert detail == "DuplicateTokenEx failed (error 1314 ERROR_PRIVILEGE_NOT_HELD)"
        assert records["closed"] == [0x222, 0x111]

    def test_create_process_failure_closes_primary_and_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        records = _install_shell_chain(monkeypatch, create_ok=False, create_error=5)
        ok, detail = elevation._relaunch_via_shell_token(["x"])
        assert ok is False
        assert detail == "CreateProcessWithTokenW failed (error 5)"
        assert records["closed"] == [0x444, 0x222, 0x111]

    def test_success_full_chain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        records = _install_shell_chain(monkeypatch)
        ok, detail = elevation._relaunch_via_shell_token(self._ARGV, cwd="C:\\repo")
        assert (ok, detail) == (True, "")
        assert records["open_process"] == (0x1000, False, 4242)
        open_token_process, open_token_access = records["open_token"]
        assert open_token_process == 0x111
        assert open_token_access == 0x000A
        token_obj, access, attrs, impersonation, token_type = records["duplicate"]
        assert token_obj.value == 0x222
        assert (access, attrs, impersonation, token_type) == (0x000F01FF, None, 2, 1)
        create = records["create"]
        assert create["token"] == 0x444
        assert create["logon_flags"] == 0x00000001
        assert create["app_name"] is None
        assert create["cmdline"] == self._CMDLINE
        assert create["flags"] == 0x00000400
        assert create["env"] is None
        assert create["cwd"] == "C:\\repo"
        assert create["startup_cb"] == ctypes.sizeof(elevation._STARTUPINFOW)
        assert records["closed"] == [0x333, 0x555, 0x444, 0x222, 0x111]
        assert records["wait_calls"] == []

    def test_wait_true_waits_for_process(self, monkeypatch: pytest.MonkeyPatch) -> None:
        records = _install_shell_chain(monkeypatch)
        ok, _ = elevation._relaunch_via_shell_token(self._ARGV, wait=True)
        assert ok is True
        assert records["wait_calls"] == [(0x555, 0xFFFFFFFF)]
