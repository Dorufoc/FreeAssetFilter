#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""进程提权检测与去提权重启（Windows 专用；纯 ctypes + 标准库，无 Qt）。

背景
----
当 Sopeek 以管理员身份运行（High 完整性级别）时，UIPI 会阻止未提权
的 Explorer 向提权窗口投放 OLE 拖放数据，拖拽功能因此失效。唯一的补救方向是
"去提权重启"：把应用以普通用户令牌重新拉起。

本模块只提供**共享原语层**（任务 12），不实现任何 UI、IPC 或 UAC 提权
（``runas``）；用户交互与启动期接线由任务 13/14 负责。

冻结的公开 API（任务 13/14 依赖，不得改名/改签名）
--------------------------------------------------
- :func:`is_process_elevated` -> bool：当前进程是否提权（任何失败一律 False）。
- :func:`get_integrity_level` -> int | None：当前进程令牌完整性级别 RID
  （``INTEGRITY_LEVEL_LOW``=0x1000 / ``MEDIUM``=0x2000 / ``HIGH``=0x3000 /
  ``SYSTEM``=0x4000；失败 None）。
- :func:`deelevation_available` -> bool：仅当进程已提权**且**能找到 shell
  （Explorer）窗口时为 True —— 两条去提权机制都需要借壳 shell 的普通令牌。
- :func:`quote_windows_args` -> str：MSVCRT / ``CommandLineToArgvW`` 兼容引号。
- :func:`restart_de_elevated` -> tuple[bool, str]：以普通用户令牌重启。
  未提权时返回 ``(False, "not elevated")`` 且**绝不启动任何进程**。

去提权机制链（``_MECHANISM_ORDER``）
------------------------------------
1. ``explorer``：复刻安装器既有的转发惯用法（项目内 §15 指定的唯一机制，
   见 ``installer_duilib/src/render/launch_forward.cpp:36-38``）::

       ShellExecuteW(GetShellWindow(), L"open", L"explorer.exe",
                     L"\\"<target>\\"", NULL, SW_SHOWNORMAL)

   返回码 ``<= 32`` 即失败（``SE_ERR_FNF=2`` / ``SE_ERR_ACCESSDENIED=5`` /
   ``SE_ERR_OOM=8``）。**实测约束（Windows 11 Build 26300）**：该转发只能
   携带单个目标路径 —— 多余的 argv 会被 Explorer 静默丢弃、``ShellExecuteW``
   仍返回 >32 的"成功"值；转发出的子进程工作目录是 Explorer 的目录
   （实测 ``C:\\Windows\\System32``），永远不是调用方 cwd。因此
   ``len(argv) != 1`` 时本机制主动报告失败，把机会让给机制 2。
2. ``shell_token``：借壳（Explorer）普通用户令牌的健壮路径 —— 源码运行
   （``python -m sopeek.app.main``）必需，因为 ``-m`` 依赖
   ``sys.path[0] == cwd`` 定位包。链:
   ``GetShellWindow`` -> ``GetWindowThreadProcessId`` ->
   ``OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`` -> ``OpenProcessToken``
   （``TOKEN_DUPLICATE | TOKEN_QUERY``）-> ``DuplicateTokenEx``（主令牌）->
   ``CreateProcessWithTokenW``（``LOGON_WITH_PROFILE`` +
   ``CREATE_UNICODE_ENVIRONMENT`` + ``lpEnvironment=None``）。调用者需持有
   ``SeImpersonatePrivilege``，缺失时失败码为 1314
   （``ERROR_PRIVILEGE_NOT_HELD``）。**所有句柄在任何路径上都会关闭**。
   ``lpEnvironment=None`` 的依据：MSDN 规定 NULL 时新进程使用目标用户
   profile 生成的环境块（``LOGON_WITH_PROFILE`` 已加载），无需
   ``CreateEnvironmentBlock``。新进程默认**不等待**（fire-and-forget）；
   ``_relaunch_via_shell_token(..., wait=True)`` 为将来需要等待的调用方保留。

约束
----
- 纯 ``ctypes`` + 标准库；**禁止 import Qt、禁止新增 pip 依赖**（启动期需在
  ``QApplication`` 之前廉价导入）。
- 全部 ``ctypes`` 声明显式给出 ``argtypes`` / ``restype``；64 位句柄一律读取
  原始返回值/``.value``（``wintypes.HWND``/``HANDLE`` 是 ``c_void_p``，直接
  ``int()`` 会按字节串解析并抛 ``ValueError``）。
- 所有失败路径 fail-safe：返回 False / None / 失败元组，绝不抛异常。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Any, Sequence

__all__ = [
    "INTEGRITY_LEVEL_HIGH",
    "INTEGRITY_LEVEL_LOW",
    "INTEGRITY_LEVEL_MEDIUM",
    "INTEGRITY_LEVEL_SYSTEM",
    "deelevation_available",
    "get_integrity_level",
    "is_process_elevated",
    "quote_windows_args",
    "restart_de_elevated",
]

# ────────────────────────────── Win32 常量 ──────────────────────────────

_TOKEN_QUERY = 0x0008
_TOKEN_DUPLICATE = 0x0002
_TOKEN_ALL_ACCESS = 0x000F01FF
_TOKEN_ELEVATION_CLASS = 20  # TokenElevation
_TOKEN_INTEGRITY_LEVEL_CLASS = 25  # TokenIntegrityLevel
_SECURITY_IMPERSONATION = 2  # SECURITY_IMPERSONATION_LEVEL
_TOKEN_PRIMARY = 1  # TOKEN_TYPE

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_LOGON_WITH_PROFILE = 0x00000001
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_SW_SHOWNORMAL = 1
_SE_ERR_FNF = 2
_SE_ERR_ACCESSDENIED = 5
_SE_ERR_OOM = 8
_ERROR_PRIVILEGE_NOT_HELD = 1314
_INFINITE = 0xFFFFFFFF

#: 令牌完整性级别 RID（``get_integrity_level`` 的取值语义）。
INTEGRITY_LEVEL_LOW = 0x1000
INTEGRITY_LEVEL_MEDIUM = 0x2000
INTEGRITY_LEVEL_HIGH = 0x3000
INTEGRITY_LEVEL_SYSTEM = 0x4000

#: 去提权机制尝试顺序（冻结；任务 13 依赖 "explorer" 在前）。
_MECHANISM_ORDER: tuple[str, ...] = ("explorer", "shell_token")

_IS_WINDOWS: bool = sys.platform == "win32"

# ────────────────────────────── 结构体定义 ──────────────────────────────


class _TOKEN_ELEVATION(ctypes.Structure):
    """``GetTokenInformation(TokenElevation)`` 的输出结构。"""

    _fields_ = [("TokenIsElevated", wintypes.DWORD)]


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    """``TOKEN_MANDATORY_LABEL.Label`` 字段类型。"""

    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _TOKEN_MANDATORY_LABEL(ctypes.Structure):
    """``GetTokenInformation(TokenIntegrityLevel)`` 的输出结构（缓冲区前缀）。"""

    _fields_ = [("Label", _SID_AND_ATTRIBUTES)]


class _STARTUPINFOW(ctypes.Structure):
    """``CreateProcessWithTokenW`` 需要的 ``STARTUPINFOW``（64 位显式布局）。"""

    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    """``CreateProcessWithTokenW`` 的输出结构。"""

    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


# ────────────────────────────── 函数绑定 ──────────────────────────────
# 全部为模块级可替换引用：单测用 monkeypatch 注入假实现验证失败路径。

_shell_execute_w: Any = None  # shell32.ShellExecuteW
_get_shell_window: Any = None  # user32.GetShellWindow
_get_window_thread_process_id: Any = None  # user32.GetWindowThreadProcessId
_get_current_process: Any = None  # kernel32.GetCurrentProcess
_open_process: Any = None  # kernel32.OpenProcess
_close_handle: Any = None  # kernel32.CloseHandle
_wait_for_single_object: Any = None  # kernel32.WaitForSingleObject
_open_process_token: Any = None  # advapi32.OpenProcessToken
_get_token_information: Any = None  # advapi32.GetTokenInformation
_get_sid_sub_authority_count: Any = None  # advapi32.GetSidSubAuthorityCount
_get_sid_sub_authority: Any = None  # advapi32.GetSidSubAuthority
_duplicate_token_ex: Any = None  # advapi32.DuplicateTokenEx
_create_process_with_token_w: Any = None  # advapi32.CreateProcessWithTokenW


def _load_win32_bindings() -> None:
    """加载并绑定本模块使用的全部 Win32 函数（显式 argtypes/restype）。

    仅在 Windows 上执行；任何 DLL 加载失败都静默降级为"未绑定"，公开 API
    按 fail-safe 契约返回失败值。导入本模块永不抛异常。
    """
    global _shell_execute_w, _get_shell_window, _get_window_thread_process_id
    global _get_current_process, _open_process, _close_handle, _wait_for_single_object
    global _open_process_token, _get_token_information
    global _get_sid_sub_authority_count, _get_sid_sub_authority
    global _duplicate_token_ex, _create_process_with_token_w

    if not _IS_WINDOWS:
        return
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except OSError:
        return

    _get_shell_window = user32.GetShellWindow
    _get_shell_window.argtypes = []
    _get_shell_window.restype = wintypes.HWND

    _get_window_thread_process_id = user32.GetWindowThreadProcessId
    _get_window_thread_process_id.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _get_window_thread_process_id.restype = wintypes.DWORD

    _shell_execute_w = shell32.ShellExecuteW
    _shell_execute_w.argtypes = [
        wintypes.HWND,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_int,
    ]
    _shell_execute_w.restype = ctypes.c_void_p

    _get_current_process = kernel32.GetCurrentProcess
    _get_current_process.argtypes = []
    _get_current_process.restype = wintypes.HANDLE

    _open_process = kernel32.OpenProcess
    _open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _open_process.restype = wintypes.HANDLE

    _close_handle = kernel32.CloseHandle
    _close_handle.argtypes = [wintypes.HANDLE]
    _close_handle.restype = wintypes.BOOL

    _wait_for_single_object = kernel32.WaitForSingleObject
    _wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _wait_for_single_object.restype = wintypes.DWORD

    _open_process_token = advapi32.OpenProcessToken
    _open_process_token.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    _open_process_token.restype = wintypes.BOOL

    _get_token_information = advapi32.GetTokenInformation
    _get_token_information.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _get_token_information.restype = wintypes.BOOL

    _get_sid_sub_authority_count = advapi32.GetSidSubAuthorityCount
    _get_sid_sub_authority_count.argtypes = [ctypes.c_void_p]
    _get_sid_sub_authority_count.restype = ctypes.POINTER(ctypes.c_ubyte)

    _get_sid_sub_authority = advapi32.GetSidSubAuthority
    _get_sid_sub_authority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    _get_sid_sub_authority.restype = ctypes.POINTER(wintypes.DWORD)

    _duplicate_token_ex = advapi32.DuplicateTokenEx
    _duplicate_token_ex.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    _duplicate_token_ex.restype = wintypes.BOOL

    _create_process_with_token_w = advapi32.CreateProcessWithTokenW
    _create_process_with_token_w.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(_STARTUPINFOW),
        ctypes.POINTER(_PROCESS_INFORMATION),
    ]
    _create_process_with_token_w.restype = wintypes.BOOL


_load_win32_bindings()


# ────────────────────────────── 内部工具 ──────────────────────────────


def _describe_win_error(error_code: int) -> str:
    """把 Win32 错误码格式化为失败细节片段（已知码附可读名）。"""
    if error_code == _ERROR_PRIVILEGE_NOT_HELD:
        return f"{error_code} ERROR_PRIVILEGE_NOT_HELD"
    return str(error_code)


def _close_handle_quietly(handle: Any) -> None:
    """尽力关闭 Win32 句柄；空句柄 / 关闭失败一律忽略（清理路径不抛异常）。"""
    if not handle or _close_handle is None:
        return
    try:
        _close_handle(handle)
    except Exception:  # noqa: BLE001 - 清理路径 fail-safe：关闭失败无需上报
        pass


def _get_shell_window_handle() -> int | None:
    """``GetShellWindow()`` 返回的 shell 窗口 HWND（失败/无 shell 返回 None）。"""
    if _get_shell_window is None:
        return None
    try:
        hwnd = _get_shell_window()
    except Exception:  # noqa: BLE001 - fail-safe 契约：查询失败返回 None
        return None
    return int(hwnd) if hwnd else None


def _get_shell_pid() -> int | None:
    """shell 窗口所属进程 PID（无 shell / 任一步失败返回 None）。"""
    shell_hwnd = _get_shell_window_handle()
    if shell_hwnd is None or _get_window_thread_process_id is None:
        return None
    pid = wintypes.DWORD(0)
    try:
        if not _get_window_thread_process_id(shell_hwnd, ctypes.byref(pid)):
            return None
    except Exception:  # noqa: BLE001 - fail-safe 契约：查询失败返回 None
        return None
    return int(pid.value) or None


# ────────────────────────────── 公开 API ──────────────────────────────


def is_process_elevated() -> bool:
    """判断当前进程是否以管理员（提权）令牌运行。

    实现：``OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY)`` +
    ``GetTokenInformation(TokenElevation=20)`` 读取
    ``TOKEN_ELEVATION.TokenIsElevated``。

    Returns:
        提权为 True；**任何失败（非 Windows / 绑定缺失 / API 失败 / 异常）
        一律返回 False**（fail-safe，绝不抛异常）。令牌句柄总会关闭。
    """
    if _open_process_token is None or _get_token_information is None or _get_current_process is None:
        return False
    token = wintypes.HANDLE()
    try:
        if not _open_process_token(_get_current_process(), _TOKEN_QUERY, ctypes.byref(token)):
            return False
        elevation = _TOKEN_ELEVATION()
        returned = wintypes.DWORD(0)
        if not _get_token_information(
            token,
            _TOKEN_ELEVATION_CLASS,
            ctypes.byref(elevation),
            ctypes.sizeof(elevation),
            ctypes.byref(returned),
        ):
            return False
        return bool(elevation.TokenIsElevated)
    except Exception:  # noqa: BLE001 - fail-safe 契约：任何异常都视为"未提权"
        return False
    finally:
        _close_handle_quietly(token)


def get_integrity_level() -> int | None:
    """读取当前进程令牌的完整性级别 RID。

    ``GetTokenInformation(TokenIntegrityLevel=25)`` 取
    ``TOKEN_MANDATORY_LABEL``，再经 ``GetSidSubAuthorityCount`` /
    ``GetSidSubAuthority`` 取 SID 末位子授权值。

    Returns:
        ``INTEGRITY_LEVEL_LOW``/``MEDIUM``/``HIGH``/``SYSTEM`` 等 RID；
        **任何失败返回 None**（fail-safe，绝不抛异常）。令牌句柄总会关闭。
    """
    if _open_process_token is None or _get_token_information is None or _get_current_process is None:
        return None
    token = wintypes.HANDLE()
    try:
        if not _open_process_token(_get_current_process(), _TOKEN_QUERY, ctypes.byref(token)):
            return None
        needed = wintypes.DWORD(0)
        # 首次调用故意传入 0 长度缓冲：预期失败并回填所需字节数。
        _get_token_information(
            token,
            _TOKEN_INTEGRITY_LEVEL_CLASS,
            None,
            0,
            ctypes.byref(needed),
        )
        if needed.value == 0:
            return None
        buffer = ctypes.create_string_buffer(needed.value)
        if not _get_token_information(
            token,
            _TOKEN_INTEGRITY_LEVEL_CLASS,
            ctypes.byref(buffer),
            needed.value,
            ctypes.byref(needed),
        ):
            return None
        label = ctypes.cast(buffer, ctypes.POINTER(_TOKEN_MANDATORY_LABEL)).contents
        sid = label.Label.Sid
        if not sid or _get_sid_sub_authority_count is None or _get_sid_sub_authority is None:
            return None
        count_ptr = _get_sid_sub_authority_count(sid)
        if not count_ptr:
            return None
        count = int(count_ptr.contents.value)
        if count <= 0:
            return None
        sub_authority = _get_sid_sub_authority(sid, count - 1)
        if not sub_authority:
            return None
        return int(sub_authority.contents.value)
    except Exception:  # noqa: BLE001 - fail-safe 契约：任何异常都视为查询失败
        return None
    finally:
        _close_handle_quietly(token)


def deelevation_available() -> bool:
    """判断当前环境是否具备"去提权重启"的条件。

    两条机制都依赖正在运行的 Explorer（借其普通用户令牌），因此仅当进程已
    提权**且**能找到 shell 窗口（``GetShellWindow()`` 非 NULL）时为 True。

    Returns:
        可执行去提权重启为 True，否则 False（fail-safe）。
    """
    return is_process_elevated() and _get_shell_window_handle() is not None


def quote_windows_args(argv: Sequence[str]) -> str:
    """按 MSVCRT / ``CommandLineToArgvW`` 规则把 argv 拼成命令行字符串。

    规则（Microsoft 官方行为）：参数为空串或含空格/Tab/双引号时用双引号包裹；
    引号前的反斜杠数需翻倍并加一个转义反斜杠；结尾反斜杠数翻倍。单个目标
    参数（``quote_windows_args([target])``）即 ``"\\"<target>\\""``，与
    ``launch_forward.cpp`` 的参数形态完全一致。

    Args:
        argv: 参数序列（不含 argv[0] 特殊语义处理；两者按普通参数处理）。

    Returns:
        可直接作为 ``lpCommandLine`` 的命令行字符串；空序列返回空串。

    Examples:
        >>> quote_windows_args(["a b", "c"])
        '"a b" c'
        >>> quote_windows_args([])
        ''
        >>> quote_windows_args([""])
        '""'
    """
    return " ".join(_quote_windows_arg(arg) for arg in argv)


def _quote_windows_arg(arg: str) -> str:
    """为单个参数添加 ``CommandLineToArgvW`` 兼容引号（内部实现）。"""
    if arg == "":
        return '""'
    if not any(char in arg for char in (' ', '\t', '"')):
        return arg
    result: list[str] = ['"']
    backslashes = 0
    for char in arg:
        if char == "\\":
            backslashes += 1
            continue
        if char == '"':
            result.append("\\" * (backslashes * 2 + 1))
            result.append('"')
        else:
            if backslashes:
                result.append("\\" * backslashes)
            result.append(char)
        backslashes = 0
    if backslashes:
        result.append("\\" * (backslashes * 2))
    result.append('"')
    return "".join(result)


def restart_de_elevated(argv: Sequence[str], cwd: str | None = None) -> tuple[bool, str]:
    """以普通用户令牌（非提权）重新启动本应用。

    未提权时立即返回 ``(False, "not elevated")`` 且**绝不启动任何进程**
    （测试与非提权启动路径依赖此契约）。已提权时按 ``_MECHANISM_ORDER``
    依次尝试 ``explorer`` / ``shell_token`` 两条机制，第一条成功即返回
    ``(True, "<机制名>")``；全部失败返回 ``(False, "<两机制合并的失败细节>")``，
    细节原样交给调用方展示（勿吞掉）。

    Args:
        argv: 目标命令行参数序列；调用方负责不含本进程 argv[0] 语义差异
            （直接传完整 argv 即可）。
        cwd: 新进程工作目录；``None`` 表示继承当前进程工作目录。源码运行
            （``python -m sopeek.app.main``）必须传仓库根目录，
            因为 ``-m`` 依赖 cwd 定位包。

    Returns:
        ``(True, 机制名)`` 或 ``(False, 失败细节)``；本函数永不抛异常，
        不等待新进程（fire-and-forget），可在 GUI 线程安全调用。
    """
    if not is_process_elevated():
        return False, "not elevated"
    failures: list[str] = []
    mechanisms = {
        "explorer": lambda args: _relaunch_via_explorer(args),
        "shell_token": lambda args: _relaunch_via_shell_token(args, cwd),
    }
    for name in _MECHANISM_ORDER:
        launched, detail = mechanisms[name](argv)
        if launched:
            return True, name
        failures.append(f"{name}: {detail}")
    return False, "; ".join(failures)


# ────────────────────────────── 去提权机制 ──────────────────────────────


def _relaunch_via_explorer(argv: Sequence[str]) -> tuple[bool, str]:
    """机制 1：经 Explorer 转发目标（§15 惯用法，仅支持单个目标）。

    实测（Windows 11 Build 26300）：Explorer 只打开命令行中的单个目标路径，
    多余的 argv 会被静默丢弃且 ``ShellExecuteW`` 仍返回成功值；转发出的子
    进程 cwd 为 Explorer 自身的目录。因此 ``len(argv) != 1`` 时本函数如实
    报告失败（让 ``shell_token`` 机制接管），绝不返回虚假成功。

    Args:
        argv: 目标参数序列（本机制要求恰好一个元素，即目标程序路径）。

    Returns:
        ``(True, "")`` 或 ``(False, 失败细节；含 ``ShellExecuteW`` 返回码)``。
    """
    if not _IS_WINDOWS or _shell_execute_w is None or _get_shell_window is None:
        return False, "shell32/user32 bindings unavailable"
    if len(argv) != 1:
        return False, (
            "explorer forwarding can carry a single target only "
            f"(got {len(argv)} argv items); it cannot forward extra arguments "
            "or a working directory"
        )
    shell_hwnd = _get_shell_window_handle()
    if shell_hwnd is None:
        return False, "shell window not found (GetShellWindow returned NULL)"
    parameters = quote_windows_args(argv)
    try:
        raw_result = _shell_execute_w(
            shell_hwnd,
            "open",
            "explorer.exe",
            parameters,
            None,
            _SW_SHOWNORMAL,
        )
    except Exception as exc:  # noqa: BLE001 - fail-safe 契约：失败返回细节元组
        return False, f"ShellExecuteW raised {type(exc).__name__}: {exc}"
    # HINSTANCE 以 c_void_p 返回：NULL -> None；数值 <= 32 是 ShellExecuteW 的失败约定。
    result_code = 0 if raw_result is None else int(raw_result)
    if result_code <= 32:
        return False, (
            f"ShellExecuteW(explorer) returned {result_code} (<=32 is failure: "
            f"SE_ERR_FNF={_SE_ERR_FNF}, SE_ERR_ACCESSDENIED={_SE_ERR_ACCESSDENIED}, "
            f"SE_ERR_OOM={_SE_ERR_OOM})"
        )
    return True, ""


def _relaunch_via_shell_token(
    argv: Sequence[str],
    cwd: str | None = None,
    *,
    wait: bool = False,
) -> tuple[bool, str]:
    """机制 2：复制 shell 进程令牌并以其主令牌创建新进程（可设 cwd）。

    句柄链（任何路径都会关闭）：
    ``GetShellWindow`` -> ``GetWindowThreadProcessId`` ->
    ``OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`` -> ``OpenProcessToken``
    -> ``DuplicateTokenEx`` -> ``CreateProcessWithTokenW``。失败时读取
    ``ctypes.get_last_error()``；1314（``ERROR_PRIVILEGE_NOT_HELD``，缺少
    ``SeImpersonatePrivilege``）会标注在细节中。

    Args:
        argv: 完整命令行参数序列。
        cwd: 新进程工作目录；``None`` 表示继承当前进程工作目录。
        wait: 默认 False（fire-and-forget，不得阻塞 GUI）；将来若有调用方
            需要等待新进程退出，传 True。

    Returns:
        ``(True, "")`` 或 ``(False, 失败细节；含 Win32 错误码)``。
    """
    if (
        not _IS_WINDOWS
        or _open_process is None
        or _open_process_token is None
        or _duplicate_token_ex is None
        or _create_process_with_token_w is None
    ):
        return False, "advapi32/kernel32 bindings unavailable"
    shell_pid = _get_shell_pid()
    if shell_pid is None:
        return False, "shell process not found (GetShellWindow/GetWindowThreadProcessId failed)"
    process = _open_process(_PROCESS_QUERY_LIMITED_INFORMATION, False, shell_pid)
    if not process:
        return False, (
            f"OpenProcess(shell pid={shell_pid}) failed "
            f"(error {_describe_win_error(ctypes.get_last_error())})"
        )
    try:
        token = wintypes.HANDLE()
        if not _open_process_token(
            process, _TOKEN_DUPLICATE | _TOKEN_QUERY, ctypes.byref(token)
        ):
            return False, (
                f"OpenProcessToken failed (error {_describe_win_error(ctypes.get_last_error())})"
            )
        try:
            primary = wintypes.HANDLE()
            if not _duplicate_token_ex(
                token,
                _TOKEN_ALL_ACCESS,
                None,
                _SECURITY_IMPERSONATION,
                _TOKEN_PRIMARY,
                ctypes.byref(primary),
            ):
                return False, (
                    f"DuplicateTokenEx failed (error {_describe_win_error(ctypes.get_last_error())})"
                )
            try:
                return _spawn_with_token(primary, argv, cwd, wait=wait)
            finally:
                _close_handle_quietly(primary)
        finally:
            _close_handle_quietly(token)
    finally:
        _close_handle_quietly(process)


def _spawn_with_token(
    token: Any,
    argv: Sequence[str],
    cwd: str | None,
    *,
    wait: bool,
) -> tuple[bool, str]:
    """``CreateProcessWithTokenW`` 实际创建进程（Token 句柄由调用方负责）。

    环境块选择：``lpEnvironment=None`` —— MSDN 规定此时新进程使用目标用户
    profile 生成的环境块（``LOGON_WITH_PROFILE`` 已加载），无需
    ``CreateEnvironmentBlock``。命令行为可变缓冲（API 会原地修改）。
    """
    command_line = ctypes.create_unicode_buffer(quote_windows_args(argv))
    startup = _STARTUPINFOW()
    startup.cb = ctypes.sizeof(_STARTUPINFOW)
    process_info = _PROCESS_INFORMATION()
    created = _create_process_with_token_w(
        token,
        _LOGON_WITH_PROFILE,
        None,  # lpApplicationName：模块名取命令行首个（带引号的）token
        command_line,
        _CREATE_UNICODE_ENVIRONMENT,
        None,  # lpEnvironment：None -> 使用目标用户 profile 环境块
        cwd,
        ctypes.byref(startup),
        ctypes.byref(process_info),
    )
    error_code = ctypes.get_last_error()  # 必须紧邻调用读取
    if not created:
        return False, f"CreateProcessWithTokenW failed (error {_describe_win_error(error_code)})"
    try:
        if wait:
            _wait_for_single_object(process_info.hProcess, _INFINITE)
    finally:
        _close_handle_quietly(process_info.hThread)
        _close_handle_quietly(process_info.hProcess)
    return True, ""
