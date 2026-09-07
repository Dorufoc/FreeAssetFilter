#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 单实例守卫（instance_guard）
--------------------------------------------
自引导层（``freeassetfilter/app/main.py``）拆分出的进程级设施，职责：

  - 运行时实例信息（``data/runtime_instance.json``）写 / 读 / 删
  - Windows 进程守卫：PID 存活判定、进程映像路径、保守身份校验、强制终止
  - 互斥体（``FreeAssetFilter_SingleInstance_Mutex``）获取与"已在运行"处理
    （含强制终止后重启）

本模块为纯逻辑 + Windows API 封装，不含 Qt 对象（弹窗在需要时惰性创建）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Optional

from freeassetfilter.utils.app_logger import error, info, warning
from freeassetfilter.utils.path_utils import get_app_data_path

_MUTEX_NAME: str = "FreeAssetFilter_SingleInstance_Mutex"
_ERROR_ALREADY_EXISTS: int = 183  # ERROR_ALREADY_EXISTS


# ──────────────────────────────────────────────────────────────
# 运行时实例信息（供单实例冲突时定位残留进程）
# ──────────────────────────────────────────────────────────────

def _get_runtime_info_file_path() -> str:
    """获取运行实例信息文件路径。"""
    return os.path.join(get_app_data_path(), "runtime_instance.json")


def _write_runtime_instance_info() -> dict:
    """写入当前运行实例信息。"""
    runtime_info = {
        "pid": os.getpid(),
        "started_at": time.time(),
        "exe_path": os.path.abspath(sys.executable),
        "argv": list(sys.argv),
    }
    runtime_file = _get_runtime_info_file_path()
    os.makedirs(os.path.dirname(runtime_file), exist_ok=True)
    with open(runtime_file, "w", encoding="utf-8") as f:
        json.dump(runtime_info, f, indent=2, ensure_ascii=False)
    return runtime_info


def _read_runtime_instance_info() -> Optional[dict]:
    """读取运行实例信息；不存在 / 损坏 / 非 dict 时返回 None。"""
    runtime_file = _get_runtime_info_file_path()
    if not os.path.exists(runtime_file):
        return None
    try:
        with open(runtime_file, "r", encoding="utf-8") as f:
            runtime_info = json.load(f)
    except (OSError, IOError, ValueError, TypeError):
        return None
    return runtime_info if isinstance(runtime_info, dict) else None


def _remove_runtime_instance_info(expected_pid: Optional[int] = None) -> None:
    """删除运行实例信息文件。

    Args:
        expected_pid: 仅当文件中的 pid 与该值一致时才删除，避免误删其他实例信息。
    """
    runtime_file = _get_runtime_info_file_path()
    if not os.path.exists(runtime_file):
        return
    try:
        if expected_pid is not None:
            with open(runtime_file, "r", encoding="utf-8") as f:
                runtime_info = json.load(f)
            if runtime_info.get("pid") != expected_pid:
                return
    except (OSError, IOError, ValueError, TypeError):
        if expected_pid is not None:
            return
    try:
        os.remove(runtime_file)
    except (OSError, IOError, PermissionError, FileNotFoundError):
        pass


# ──────────────────────────────────────────────────────────────
# Windows 进程守卫
# ──────────────────────────────────────────────────────────────

def _is_process_running(pid) -> bool:
    """判断指定 PID 是否仍在运行（非 Windows 一律 False）。"""
    if not isinstance(pid, int) or pid <= 0 or sys.platform != "win32":
        return False

    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    process_handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process_handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(process_handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(process_handle)


def _get_process_image_path(pid) -> Optional[str]:
    """获取进程可执行文件路径（非 Windows / 无效 PID 返回 None）。"""
    if not isinstance(pid, int) or pid <= 0 or sys.platform != "win32":
        return None

    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    process_handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process_handle:
        return None
    try:
        buffer_length = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(buffer_length.value)
        if not kernel32.QueryFullProcessImageNameW(
            process_handle, 0, buffer, ctypes.byref(buffer_length)
        ):
            return None
        return os.path.normcase(os.path.normpath(buffer.value))
    finally:
        kernel32.CloseHandle(process_handle)


def _is_expected_app_process(pid: int, runtime_info: dict) -> bool:
    """保守校验 PID 是否指向 FreeAssetFilter 主程序自身。"""
    if not _is_process_running(pid):
        return False
    process_image_path = _get_process_image_path(pid)
    if not process_image_path:
        return False

    expected_paths = set()
    runtime_exe_path = runtime_info.get("exe_path")
    if isinstance(runtime_exe_path, str) and runtime_exe_path.strip():
        expected_paths.add(os.path.normcase(os.path.normpath(runtime_exe_path)))
    current_exe_path = os.path.abspath(sys.executable)
    if current_exe_path:
        expected_paths.add(os.path.normcase(os.path.normpath(current_exe_path)))
    if process_image_path in expected_paths:
        return True

    process_name = os.path.basename(process_image_path).lower()
    return "freeassetfilter" in process_name


def _terminate_process(pid) -> tuple:
    """强制终止指定进程（仅 Windows）。

    Returns:
        (ok: bool, message: str)
    """
    if not isinstance(pid, int) or pid <= 0:
        return False, "无效的进程 PID"
    if sys.platform != "win32":
        return False, "仅支持在 Windows 上强制终止实例"

    import ctypes
    from ctypes import wintypes

    PROCESS_TERMINATE = 0x0001
    SYNCHRONIZE = 0x00100000
    WAIT_OBJECT_0 = 0x00000000
    WAIT_TIMEOUT = 0x00000102

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    process_handle = kernel32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
    if not process_handle:
        return False, "无法打开目标进程，可能权限不足或进程已退出"
    try:
        if not kernel32.TerminateProcess(process_handle, 1):
            return False, "调用强制终止失败"
        wait_result = kernel32.WaitForSingleObject(process_handle, 5000)
        if wait_result == WAIT_OBJECT_0:
            return True, ""
        if wait_result == WAIT_TIMEOUT:
            return False, "等待目标进程退出超时"
        return False, f"等待目标进程退出失败，结果码: {wait_result}"
    finally:
        kernel32.CloseHandle(process_handle)


def _restart_current_application() -> None:
    """使用当前启动参数重新启动应用程序。"""
    relaunch_args = [sys.executable] + list(sys.argv[1:])
    subprocess.Popen(
        relaunch_args,
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


# ──────────────────────────────────────────────────────────────
# 单实例入口
# ──────────────────────────────────────────────────────────────

def _acquire_single_instance():
    """获取单实例互斥体；已存在实例时处理冲突并退出进程（不返回）。

    Returns:
        mutex 句柄（int），仅当本进程成为唯一实例时返回。
    """
    if sys.platform != "win32":
        return None

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE

    mutex_handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if not mutex_handle:
        warning("单实例互斥体创建失败（继续运行）")
        return None

    if kernel32.GetLastError() != _ERROR_ALREADY_EXISTS:
        return mutex_handle

    info("another instance already running")
    try:
        _show_already_running_dialog_and_handle_restart(mutex_handle)
    except Exception as e:
        warning(f"多实例提示失败: {e}")
    finally:
        kernel32.CloseHandle(mutex_handle)
    sys.exit(0)


def _release_mutex(mutex_handle) -> None:
    """释放单实例互斥体句柄。"""
    if not mutex_handle or sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.kernel32.CloseHandle(mutex_handle)
    except Exception:
        pass


def _show_already_running_dialog_and_handle_restart(mutex_handle) -> None:
    """显示"程序已在运行"弹窗，并在需要时执行强制终止后重启。"""
    from PySide6.QtWidgets import QMessageBox

    from components.styled_dialog import ask_custom_dialog

    go_restart = ask_custom_dialog(
        title="FreeAssetFilter",
        message=(
            "程序已经在运行中，不能启动多个实例。\n\n"
            "仅当你已经确认程序窗口已关闭，但这里仍然反复提示程序正在运行时，"
            "才点击「强制终止后重新启动」。\n"
            "该操作会强制结束残留后台进程，未保存内容可能丢失。"
        ),
        buttons=["确定", "强制终止后重新启动"],
        variants=["primary", "danger"],
        vertical=True,
        dialog_type="default",
        show_close=False,
    ) == 1
    if not go_restart:
        return

    runtime_info = _read_runtime_instance_info()
    if not runtime_info:
        _show_error_box("强制终止失败", "无法读取正在运行实例的信息")
        return

    target_pid = runtime_info.get("pid")
    if not isinstance(target_pid, int) or target_pid <= 0:
        _show_error_box("强制终止失败", "运行实例信息中的 PID 无效")
        return

    if not _is_process_running(target_pid):
        _remove_runtime_instance_info(expected_pid=target_pid)
        _show_error_box("未发现残留进程", "记录中的运行实例已经不存在，程序残留记录已清理，请重新启动程序。")
        return

    if not _is_expected_app_process(target_pid, runtime_info):
        _show_error_box("强制终止失败", "检测到的目标进程与当前程序不匹配")
        return

    terminated, terminate_message = _terminate_process(target_pid)
    if not terminated:
        _show_error_box("强制终止失败", f"无法强制结束残留进程：{terminate_message}")
        return

    _remove_runtime_instance_info(expected_pid=target_pid)
    try:
        _restart_current_application()
    except Exception as e:
        error(f"残留进程已结束，但重新启动失败: {e}")
        _show_error_box("重新启动失败", f"残留进程已被强制结束，但重新启动失败：{e}")


def _show_error_box(title: str, message: str) -> None:
    """原生错误提示框（强制终止等系统级场景，样式弹窗可能不可用）。"""
    try:
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox()
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Critical)
        box.setText(message)
        box.exec()
    except Exception as e:
        error(f"错误弹窗显示失败（{title}）: {e}")


