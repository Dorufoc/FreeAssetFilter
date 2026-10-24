#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0.0
Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

FreeAssetFilter 应用引导层（精简版）
-------------------------------------
只承担「引导 / 进程级设施」职责，不包含任何业务 UI：

  - 日志与输出捕获（fd 级原生捕获 + stdout/stderr 双写）
  - faulthandler（VEH/UEF 崩溃栈兜底，仅写日志文件）
  - 未捕获异常钩子（sys.excepthook / threading.excepthook）
  - AppUserModelID、DPI 感知、单实例互斥体、运行时实例信息
  - 启动期提权自愈（管理员运行致 Explorer 拖入被 UIPI 拦截时，询问去提权重启）
  - 内部子进程分流：--faf-thumbnail-worker
  - 首帧分阶段启动调度（见 freeassetfilter.app.startup）
  - 退出链（心跳停止 → fd 卸载 → 设置落盘 → 日志 flush → 互斥体释放）

模块级零副作用：全部设施安装发生在 ``main()`` 内，导入本模块不会
接管 fd / 注册钩子（便于测试与复用）。

主窗口为 ``freeassetfilter.ui.main_window.MainWindow``。
单实例守卫见 ``freeassetfilter.app.instance_guard``；
启动任务编排见 ``freeassetfilter.app.startup``。

入口唯一：本模块是唯一应用入口（``ui/main_window.py`` 原有的独立调试
入口 ``main()`` 已按审查报告 3.2 合并移除）；需要单独调试窗口时直接
运行 ``python -m freeassetfilter.app.main``。
"""

from __future__ import annotations

import atexit
import ctypes
import faulthandler
import logging
import os
import subprocess
import sys
import threading
import time
import warnings
from typing import Any

# 确保包能被正确导入（PyInstaller 直接执行本脚本时也需要）
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from freeassetfilter.utils import elevation
from freeassetfilter.utils.app_logger import (
    get_logger,
    debug,
    info,
    warning,
    error,
    log_exception,
    install_console_capture,
)
from freeassetfilter.utils.fd_capture import install_fd_capture, uninstall_fd_capture
from freeassetfilter.utils.qt_message_handler import install_qt_message_handler
from freeassetfilter.utils.path_utils import get_resource_path

from freeassetfilter.app import instance_guard
from freeassetfilter.app.startup import StartupController
from freeassetfilter.ui.theme.app_stylesheet import apply_app_stylesheet


# ──────────────────────────────────────────────────────────────
# 进程级设施安装 / 清理
# ──────────────────────────────────────────────────────────────

def _install_process_facilities() -> dict:
    """安装日志捕获、faulthandler、异常钩子等进程级设施。

    顺序固定：fd 捕获 → console 双写 → 控制台 handler 重指 → faulthandler
    → 异常钩子 → 弃用警告过滤。返回供 ``_cleanup_process_facilities``
    使用的状态字典。
    """
    state: dict = {}

    logger = get_logger()

    # 1) fd 级原生输出捕获必须最先安装；备份的控制台流交给 TeeStream
    #    与 AppLogger 控制台 handler，否则 Python 日志会经已接管的 fd 1
    #    双写进日志（FileHandler 一次 + [native-stdout] 一次）。
    state["fd_streams"] = {}
    try:
        state["fd_streams"] = install_fd_capture(logger.get_log_file_path())
    except (OSError, IOError, PermissionError, FileNotFoundError, ValueError, TypeError) as e:
        warning("fd capture init failed")

    # 2) stdout/stderr 双写捕获
    try:
        if not install_console_capture(
            logger.get_log_file_path(),
            saved_stdout=state["fd_streams"].get(1),
            saved_stderr=state["fd_streams"].get(2),
        ):
            info("console capture unavailable (non-fatal)")
    except (OSError, IOError, PermissionError, FileNotFoundError, ValueError, TypeError) as e:
        warning("console capture init failed")

    # 3) 重指 AppLogger 控制台 handler 到备份的控制台流（防双写）。
    #    必须用 type(h) is 精确匹配：FileHandler 是 StreamHandler 子类，
    #    isinstance 会误伤文件 handler。
    try:
        saved_stdout = state["fd_streams"].get(1)
        if saved_stdout is not None:
            for handler in list(getattr(logger, "logger", None).handlers or []):
                if type(handler) is logging.StreamHandler and handler.stream is sys.__stdout__:
                    handler.stream = saved_stdout
    except (OSError, ValueError, AttributeError, TypeError) as e:
        warning("console handler repoint failed")

    # 4) faulthandler：只写日志文件，不输出终端（VEH/UEF 兜底）。
    #    VEH 的存在会使 LuaJIT 的 SEH 异常（0xe24c4a02）也触发 dump；
    #    以 load-scripts=no 启动时该异常成为未处理异常导致崩溃——
    #    故 faulthandler 的 VEH 兼作该场景的兜底。
    state["fault_file"] = None
    state["fault_enabled"] = False
    try:
        log_file_path = logger.get_log_file_path()
        if log_file_path:
            fault_file = open(log_file_path, "ab", buffering=0)
            fault_file.write(
                b"\n=== FAULTHANDLER OUTPUT START ===\n"
                b"\n=== FAULTHANDLER OUTPUT START ===\n"
            )
            fault_file.flush()
            faulthandler.enable(file=fault_file, all_threads=True)
            state["fault_file"] = fault_file
            state["fault_enabled"] = True
    except (OSError, IOError, PermissionError, FileNotFoundError, ValueError, TypeError) as e:
        warning("faulthandler init failed")
    if not state["fault_enabled"]:
        info("faulthandler not enabled (non-fatal)")

    # 5) 未捕获异常钩子
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        log_exception(exc_type, exc_value, exc_traceback)

    def handle_thread_exception(args):
        try:
            if issubclass(args.exc_type, KeyboardInterrupt):
                return
        except TypeError:
            pass
        log_exception(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = handle_exception
    threading.excepthook = handle_thread_exception

    # 6) 弃用警告过滤
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="PySide6")
    warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*sipPyTypeDict.*")

    return state


def _cleanup_process_facilities(state: dict) -> None:
    """卸载 fd 捕获、关闭 faulthandler（幂等，退出链可重复调用）。"""
    try:
        uninstall_fd_capture()
    except (OSError, ValueError) as e:
        warning(f"[退出] fd capture 卸载失败: {e}")

    if state.get("fault_enabled"):
        try:
            faulthandler.disable()
        except (OSError, ValueError):
            pass
        state["fault_enabled"] = False
    fault_file = state.get("fault_file")
    if fault_file is not None:
        try:
            fault_file.write(b"\n=== FAULTHANDLER OUTPUT END ===\n")
            fault_file.flush()
        except (OSError, ValueError):
            pass
        try:
            fault_file.close()
        except (OSError, ValueError):
            pass
        state["fault_file"] = None


# ──────────────────────────────────────────────────────────────
# 参数解析与内部分流
# ──────────────────────────────────────────────────────────────

def _parse_internal_worker_args(argv) -> tuple:
    """解析内部子进程参数（仅缩略图 worker 保留）。

    Returns:
        (worker_type, worker_payload)；非内部调用返回 (None, {})。
    """
    if len(argv) >= 5 and argv[1] == "--faf-thumbnail-worker":
        return "thumbnail", {
            "file_path": argv[2],
            "dpi_scale": argv[3],
            "prefer_native": argv[4],
        }
    return None, {}


def _run_thumbnail_worker(payload: dict) -> int:
    """执行缩略图子进程任务（--faf-thumbnail-worker）。"""
    from freeassetfilter.core.managers.thumbnail_manager import _run_batch_video_thumbnail_subprocess

    file_path = payload.get("file_path", "")
    dpi_scale = float(payload.get("dpi_scale", 1.0))
    prefer_native = str(payload.get("prefer_native", "1")).lower() in ("1", "true", "yes", "on")
    return _run_batch_video_thumbnail_subprocess(file_path, dpi_scale, prefer_native)


def _extract_open_path_arg(argv) -> str | None:
    """解析 --open-path 命令行参数（右键菜单传入的路径）。"""
    try:
        idx = argv.index("--open-path")
        if idx + 1 < len(argv):
            return argv[idx + 1]
    except ValueError:
        pass
    return None


def _resolve_initial_navigate_path(argv) -> str | None:
    """由 --open-path 解析初始导航路径（文件→其所在目录，目录→原样）。"""
    open_path = _extract_open_path_arg(argv)
    if not open_path:
        return None
    open_path = os.path.normpath(open_path)
    if os.path.isfile(open_path):
        return os.path.dirname(open_path)
    if os.path.isdir(open_path):
        return open_path
    return None


# ──────────────────────────────────────────────────────────────
# Windows 进程级设置
# ──────────────────────────────────────────────────────────────

def _setup_windows_process() -> None:
    """设置任务栏 AppUserModelID 与 DPI 感知。"""
    if sys.platform != "win32":
        return

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FreeAssetFilter.App")

    # DPI 感知声明（保留决策；2026-10-12 经审查报告 3.2 评估）：
    #   Qt6 默认已启用高 DPI 缩放（等效于声明 PerMonitorV2），本块在
    #   常规环境下冗余；但它是 PyInstaller 冻结 exe / Qt 行为变化时的
    #   保险（缺失时高 DPI 屏可能退化为 Windows 位图拉伸而模糊）。
    #   权衡后决定长期保留：删除收益仅为数行代码，代价是潜在的整屏
    #   模糊回归，故不再列入移除计划。
    try:
        user32 = ctypes.windll.user32
        SetProcessDpiAwarenessContext = user32.SetProcessDpiAwarenessContext
        SetProcessDpiAwarenessContext.restype = ctypes.c_void_p
        SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        result = SetProcessDpiAwarenessContext(0x3)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if result == 0:
            shcore = ctypes.windll.shcore
            SetProcessDpiAwareness = shcore.SetProcessDpiAwareness
            SetProcessDpiAwareness.restype = ctypes.c_long
            SetProcessDpiAwareness.argtypes = [ctypes.c_int]
            SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except (AttributeError, OSError):
        try:
            SetProcessDPIAware = ctypes.windll.user32.SetProcessDPIAware
            SetProcessDPIAware.restype = ctypes.c_bool
            SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


# ──────────────────────────────────────────────────────────────
# 应用对象装配
# ──────────────────────────────────────────────────────────────

def _init_settings_manager(app) -> None:
    """提前创建并加载 SettingsManagerV2，挂到 app（主窗口复用，避免双加载）。"""
    from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2

    settings_manager = SettingsManagerV2()
    settings_manager.load()
    app.settings_manager = settings_manager
    info("[启动] SettingsManagerV2 初始化完成")


def _create_application(argv, initial_navigate_path):
    """创建 QApplication 并挂载应用级属性。"""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon, QPixmapCache

    app = QApplication(argv)
    try:
        install_qt_message_handler()
    except (OSError, ValueError, TypeError) as e:
        warning("qt message handler init failed")

    # L2 缓存层上限（配合各组件 L1 缓存使用）
    QPixmapCache.setCacheLimit(50 * 1024)

    # 右键菜单初始导航路径（文件选择器启动时消费）
    app.initial_navigate_path = initial_navigate_path
    # 设置管理器：主窗口构造前加载（MainWindow 读取背景/恢复设置时复用）
    _init_settings_manager(app)

    # 任务栏图标
    icon_path = get_resource_path("freeassetfilter/icons/FAF-main.ico")
    app.setWindowIcon(QIcon(icon_path))
    return app


def _warn_if_frameless_unsupported() -> None:
    """Qt < 6.10 时显著警告：原生无边框窗口会退化（避免静默降级）。

    退化表现：窗口带完整原生标题栏、丢失最大化动画，等同于「无边框方案失效」。
    日志用 error 级别，并在主窗口显示后弹出一次提示框（不阻塞启动）。
    """
    try:
        from freeassetfilter.ui.frameless_window import frameless_runtime_status

        supported, detail = frameless_runtime_status()
    except Exception as e:  # noqa: BLE001 - 仅提示用途，失败不影响启动
        warning(f"无边框运行时检测失败: {e}")
        return
    if supported:
        info(f"[无边框] 运行时检查通过：{detail}")
        return

    error(f"[无边框] 原生无边框窗口不可用：{detail}")
    logger = get_logger()
    if logger is not None:
        logger.warning("=" * 68)
        logger.warning("  无边框窗口已退化：%s", detail)
        logger.warning("=" * 68)

    try:
        from PySide6.QtCore import QTimer

        def _show_notice() -> None:
            try:
                from freeassetfilter.ui.components.styled_dialog import create_custom_dialog

                create_custom_dialog(
                    title="无边框窗口不可用",
                    message=(
                        f"{detail}\n\n"
                        "当前窗口会显示系统原生标题栏，最大化动画也可能缺失。"
                    ),
                    buttons=["我知道了"],
                    dialog_type="danger",
                    show_close=True,
                )
            except Exception as e:  # noqa: BLE001 - 提示失败不影响使用
                warning(f"无边框退化提示框显示失败: {e}")

        QTimer.singleShot(600, _show_notice)
    except Exception as e:  # noqa: BLE001
        warning(f"无边框退化提示调度失败: {e}")


# ──────────────────────────────────────────────────────────────
# 启动期提权自愈（UIPI 拖放失效：去提权重启，办法一）
# ──────────────────────────────────────────────────────────────

#: 本次运行内是否已询问过去提权重启（内存标记，不落盘）。
_deelevation_prompt_suppressed: bool = False


def _deelevation_restart_command() -> tuple[list[str], str]:
    """构造去提权重启的目标命令行与工作目录。

    源码运行（``python -m freeassetfilter.app.main``）依赖 cwd 定位包，
    必须携带仓库根目录；冻结运行（PyInstaller exe）直接重启自身，
    cwd 取可执行文件所在目录（沿用 ``getattr(sys, "frozen", False)`` 惯例）。

    Returns:
        ``(argv, cwd)`` 二元组。
    """
    if getattr(sys, "frozen", False):
        return [sys.executable], os.path.dirname(os.path.abspath(sys.executable))
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return [sys.executable, "-m", "freeassetfilter.app.main"], repo_root


def _ask_deelevation_restart_choice() -> int:
    """弹出去提权重启询问框（styled 组件），阻塞至用户点击。

    Returns:
        被点击按钮索引：0 = 「立即重启」；1 = 「保持管理员权限」。
    """
    from freeassetfilter.ui.components.styled_dialog import ask_custom_dialog

    # show_close=False（显式声明）：不提供 X 关闭按钮，避免「关闭 → 兜底 0 →
    # 被误读为立即重启」；StyledDialog 无 ESC 处理，用户必须二选一，语义无歧义。
    return ask_custom_dialog(
        title="以管理员权限运行",
        message=(
            "当前程序以管理员权限运行。Windows 的安全限制（UIPI）会使"
            "「从资源管理器拖入文件/文件夹」失效。\n\n"
            "立即以普通权限重新启动即可恢复正常；"
            "选择「保持管理员权限」则继续使用，本次运行不再询问。"
        ),
        buttons=["立即重启", "保持管理员权限"],
        dialog_type="question",
        show_close=False,
    )


def _show_deelevation_restart_failure(detail: str) -> None:
    """去提权重启失败告警（styled 组件），阻塞至用户确认。

    Args:
        detail: ``restart_de_elevated`` 返回的失败细节（原样展示，不吞掉）。
    """
    from freeassetfilter.ui.components.styled_dialog import ask_custom_dialog

    ask_custom_dialog(
        title="去提权重启失败",
        message=(
            "未能以普通权限重新启动程序，从资源管理器拖入文件仍将不可用。\n\n"
            f"失败原因：{detail}\n\n"
            "程序将继续以管理员权限运行。"
        ),
        buttons=["我知道了"],
        dialog_type="danger",
        show_close=False,
    )


def _offer_deelevation_restart_if_elevated(mutex_handle: Any) -> str:
    """启动期提权自愈：提权且可去提权时，询问并（可选）立即去提权重启。

    背景：提权运行时 UIPI 会拦截未提权 Explorer 的 OLE 投放，导致从资源
    管理器拖入文件失效；以普通权限重启是根治手段（task 13 / 办法一）。

    Args:
        mutex_handle: 单实例互斥体句柄。选择「立即重启」时必须先释放，
            否则重启出的新实例会因互斥体仍存在而拒绝启动。

    Returns:
        ``"continue"`` —— 未提权 / 无 shell 可借壳 / 本次运行已询问过，
        按现状继续（零副作用）；
        ``"keep"`` —— 用户选择保持管理员权限，本次运行不再询问；
        ``"restart"`` —— 已成功发起去提权重启（互斥体与实例信息均已清理，
        调用方应立即结束当前进程）；
        ``"restart_failed"`` —— 已弹告警并附失败细节，继续以提权态运行
        （交原生 WM_DROPFILES 兜底）。
    """
    global _deelevation_prompt_suppressed

    if _deelevation_prompt_suppressed:
        return "continue"
    if not elevation.is_process_elevated():
        return "continue"
    if not elevation.deelevation_available():
        return "continue"

    info("[提权] 检测到以管理员权限运行：询问是否去提权重启（拖放受 UIPI 限制）")
    restart_chosen = _ask_deelevation_restart_choice() == 0
    _deelevation_prompt_suppressed = True
    if not restart_chosen:
        info("[提权] 用户选择保持管理员权限，本次运行不再询问")
        return "keep"

    # 释放互斥体 + 清理运行时实例信息必须先于重启：
    # 否则新实例启动时会命中「已在运行」并直接退出。
    instance_guard._release_mutex(mutex_handle)
    try:
        instance_guard._remove_runtime_instance_info(expected_pid=os.getpid())
    except Exception as exc:  # noqa: BLE001 - 清理失败不阻断重启
        debug(f"[提权] 清理运行时实例信息失败：{exc}")

    argv, cwd = _deelevation_restart_command()
    launched, detail = elevation.restart_de_elevated(argv, cwd)
    if launched:
        info(f"[提权] 已发起去提权重启（机制: {detail}）")
        return "restart"

    warning(f"[提权] 去提权重启失败：{detail}")
    _show_deelevation_restart_failure(detail)
    return "restart_failed"


# ──────────────────────────────────────────────────────────────
# 使用硬件加速：经独显启动器重启自身
# ──────────────────────────────────────────────────────────────

#: 子进程标记：本次启动已经过 FAF-Launcher.exe，禁止再次重启（防递归）。
_GPU_LAUNCHED_ENV: str = "FAF_GPU_LAUNCHED"
#: 父进程 PID：子进程据此等待父进程释放单实例互斥体。
_GPU_PARENT_PID_ENV: str = "FAF_GPU_PARENT_PID"


def _hardware_acceleration_enabled() -> bool:
    """读取 V2 设置中的「使用硬件加速」开关。

    Returns:
        bool: True 表示下次/本次启动请求独占显卡；设置不可读时按关闭处理。
    """
    try:
        from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2

        settings = SettingsManagerV2().load()
        performance = settings.get("performance", {})
        if not isinstance(performance, dict):
            return False
        return performance.get("hardware_acceleration", False) is True
    except Exception as exc:  # noqa: BLE001 - 设置不可读时按关闭处理
        debug(f"[硬件加速] 读取设置失败，按关闭处理：{exc}")
        return False


def _gpu_launcher_ready() -> bool:
    """检查独显启动器是否存在且带两个必需 PE 导出。

    Returns:
        bool: True 表示启动器可用；否则记录告警并返回 False（直启回退）。
    """
    from freeassetfilter.core.native.platform_gpu import (
        launcher_exe_path,
        launcher_has_gpu_exports,
    )

    exe = launcher_exe_path()
    if not exe.is_file():
        warning(f"[硬件加速] 启动器未构建：{exe}（回退直启）")
        return False
    if not launcher_has_gpu_exports(exe):
        warning(f"[硬件加速] 启动器缺少 GPU 导出：{exe}（回退直启）")
        return False
    return True


def _maybe_relaunch_with_gpu_launcher(argv: list[str]) -> bool:
    """启用硬件加速且尚未经启动器启动时，经 FAF-Launcher.exe 重启自身。

    Args:
        argv: 当前进程完整参数列表（``argv[0]`` 不转发）。

    Returns:
        bool: True 表示已发起重启，调用方应立即结束当前进程；
        False 表示继续正常启动。
    """
    if os.environ.get(_GPU_LAUNCHED_ENV) == "1":
        return False
    if not _hardware_acceleration_enabled():
        return False
    if not _gpu_launcher_ready():
        return False

    from freeassetfilter.core.native.platform_gpu import launcher_exe_path

    exe = launcher_exe_path()
    env = os.environ.copy()
    env[_GPU_LAUNCHED_ENV] = "1"
    env[_GPU_PARENT_PID_ENV] = str(os.getpid())
    cwd = (
        os.path.dirname(os.path.abspath(sys.executable))
        if getattr(sys, "frozen", False)
        else os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
    )
    try:
        subprocess.Popen(
            [str(exe), *argv[1:]], cwd=cwd, env=env, close_fds=True
        )
    except OSError as exc:
        warning(f"[硬件加速] 启动器拉起失败，回退直启：{exc}")
        return False
    info(f"[硬件加速] 已通过独显启动器重启：{exe}")
    return True


def _wait_for_gpu_launcher_parent() -> None:
    """等待发起重启的父进程退出，避免子进程撞上单实例互斥体。"""
    raw_pid = os.environ.pop(_GPU_PARENT_PID_ENV, None)
    if not raw_pid or sys.platform != "win32":
        return
    try:
        pid = int(raw_pid)
    except ValueError:
        return
    try:
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return
        try:
            kernel32.WaitForSingleObject(handle, 15000)
        finally:
            kernel32.CloseHandle(handle)
    except (OSError, ValueError) as exc:
        debug(f"[硬件加速] 等待父进程退出失败：{exc}")


# ──────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    """应用引导入口（返回退出码）。"""
    argv = list(sys.argv) if argv is None else list(argv)
    info("程序启动")
    _start_ts = time.perf_counter()

    # 内部子进程分流（在任何 Qt 初始化之前，保证 worker 轻量启动）
    worker_type, worker_payload = _parse_internal_worker_args(argv)
    if worker_type == "thumbnail":
        try:
            sys.exit(_run_thumbnail_worker(worker_payload))
        except Exception as e:
            error(f"缩略图子进程执行失败: {e}")
            sys.exit(1)

    # 独显启动器子进程：先等父进程退出，再走正常单实例流程。
    _wait_for_gpu_launcher_parent()

    # 使用硬件加速：经独显启动器重启自身（必须早于 QApplication 与单实例互斥体）。
    if _maybe_relaunch_with_gpu_launcher(argv):
        return 0

    # 任务栏图标与 DPI 感知
    sys.argv[0] = os.path.abspath(__file__)
    _setup_windows_process()

    # 初始导航路径（--open-path）
    initial_navigate_path = _resolve_initial_navigate_path(argv)

    # 新版 UI 短路径导入约定（components/theme/layout ...）
    _project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _ui_root = os.path.join(_project_root, "freeassetfilter", "ui")
    if _ui_root not in sys.path:
        sys.path.insert(0, _ui_root)

    # 进程级设施（fd/console/faulthandler/异常钩子）
    facilities = _install_process_facilities()

    # QApplication 与应用级属性
    app = _create_application(argv, initial_navigate_path)
    info(f"[启动] QApplication 创建: {(time.perf_counter()-_start_ts)*1000:.0f}ms")

    # 单实例互斥体（冲突时内部处理并退出进程）
    mutex_handle = instance_guard._acquire_single_instance()

    try:
        instance_guard._write_runtime_instance_info()
    except (OSError, IOError, PermissionError, FileNotFoundError, ValueError, TypeError) as e:
        warning(f"写入运行实例信息失败: {e}")

    # 启动期提权自愈（task 13）：管理员运行时 UIPI 会拦截 Explorer 的
    # 拖入投放；询问用户是否以普通权限重启。必须在单实例互斥体已获取、
    # 主窗口构建之前执行（非提权路径零副作用）。
    deelevation_action = _offer_deelevation_restart_if_elevated(mutex_handle)
    if deelevation_action == "restart":
        # 互斥体与实例信息已在自愈流程内释放，重启出的新实例可正常启动。
        sys.exit(0)
    if deelevation_action == "restart_failed":
        # 自愈流程已释放互斥体（失败后继续运行），置空防止退出链二次关闭句柄。
        mutex_handle = None

    # 创建主窗口
    try:
        from freeassetfilter.ui.main_window import MainWindow

        # 轻量首帧：先显示无边框框架、现有自定义标题栏和加载动画，
        # 重型背景/三栏布局在事件循环接管后再初始化。
        window = MainWindow(defer_heavy_init=True)
    except Exception as e:
        error_msg = f"应用程序初始化失败：{e}\n\n请尝试重启程序。如果问题持续，请检查日志文件。"
        error(error_msg)
        try:
            if sys.platform == "win32":
                ctypes.windll.user32.MessageBoxW(0, error_msg, "启动错误 - FreeAssetFilter", 0x10)
        except Exception:
            pass  # 已记录 error 日志；弹窗失败不再追加（避免启动错误路径再抛）
        sys.exit(1)
    info(f"[启动] 主窗口创建: {(time.perf_counter()-_start_ts)*1000:.0f}ms")

    controller = StartupController(app, window)

    # 关键首帧：先把轻量无边框窗口交给 Qt 显示，标题栏和 StyledLoading
    # 能在第一个事件循环周期内响应。完整内容与全局 QSS 均放到 show 之后。
    window.show()
    info(f"[启动] 轻量窗口显示: {(time.perf_counter()-_start_ts)*1000:.0f}ms")

    from PySide6.QtCore import QTimer

    def _finish_deferred_ui() -> None:
        try:
            window.initialize_deferred_content()
            info(f"[启动] 完整内容初始化: {(time.perf_counter()-_start_ts)*1000:.0f}ms")
        except Exception as e:
            error(f"[启动] 完整内容初始化失败: {e}")
        try:
            # A1 QSS 单例化：完整控件已注册片段后统一下发。
            if not apply_app_stylesheet():
                warning("应用级样式表初始下发失败（各组件回退默认样式）")
        except Exception as e:
            warning(f"应用级样式表初始下发失败（各组件回退默认样式）: {e}")
        # 完整 UI 已交给事件循环后，再启动心跳/字体/缓存/FFmpeg 预热，
        # 避免这些任务与首帧和面板构建争抢主线程。
        controller.schedule_startup_tasks()
        info(f"[启动] 启动任务已调度: {(time.perf_counter()-_start_ts)*1000:.0f}ms")

    QTimer.singleShot(0, _finish_deferred_ui)

    # 无边框能力运行时检查（Qt<6.10 退化时显著告警，不阻塞启动）
    _warn_if_frameless_unsupported()

    # ── 退出链（单一处理器 + 幂等标志：aboutToQuit 与 atexit 双挂但只执行一次）──
    exit_done = [False]

    def on_app_exit():
        if exit_done[0]:
            return
        exit_done[0] = True

        # 1) 引导层后台线程与心跳先行停止
        try:
            controller.cleanup()
        except Exception as e:
            warning(f"[退出] 引导层清理失败: {e}")

        # 1.5) 回收 Mica GPU 渲染器常驻线程（若本会话启用过 GPU 烘焙）。
        # 有界 join（DISPOSE_JOIN_MS），卡死时只停用不强杀，守护线程不阻塞退出。
        try:
            from freeassetfilter.ui.mica.gpu import shutdown_gpu_renderer
            shutdown_gpu_renderer()
        except Exception as e:
            warning(f"[退出] Mica GPU 渲染器回收失败: {e}")

        # 1.6) 兜底关闭全局浮窗（MainWindow.closeEvent 未跑到时的保险）。
        # C++ 对象可能已随主窗销毁，故 None 前置检查 + shiboken isValid +
        # RuntimeError 守卫；close() 后不置 None（与 closeEvent 契约一致）。
        try:
            floating_ref = getattr(window, "_floating_pool", None)
            if floating_ref is not None:
                from shiboken6 import isValid
                if isValid(floating_ref):
                    floating_ref.close()
        except Exception as e:
            debug(f"[退出] 兜底关闭全局浮窗失败: {e}")

        # 2) 卸载 fd 捕获（排空管道 + join），再做 handler flush 与 faulthandler 清理
        _cleanup_process_facilities(facilities)
        exit_time = time.time()

        # 3) last_exit_time 写入 SettingsManagerV2
        try:
            settings_manager = getattr(app, "settings_manager", None)
            if settings_manager is None:
                from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2
                settings_manager = SettingsManagerV2()
            settings_manager.set("app.last_exit_time", exit_time)
            settings_manager.save()
        except Exception as e:
            warning(f"[退出] last_exit_time 写入失败: {e}")

        # 4) 显式 flush 全部日志 handler
        try:
            for handler in getattr(get_logger(), "logger", None).handlers or []:
                handler.flush()
        except Exception as exc:
            debug(f"退出时刷新日志句柄失败：{exc}")

        # 5) 清理实例信息与互斥体
        try:
            instance_guard._remove_runtime_instance_info(expected_pid=os.getpid())
        except Exception as exc:
            debug(f"清理运行时实例信息失败：{exc}")
        instance_guard._release_mutex(mutex_handle)

    app.aboutToQuit.connect(on_app_exit)
    atexit.register(on_app_exit)

    info(f"[启动] 总耗时: {(time.perf_counter()-_start_ts)*1000:.0f}ms")
    exit_code = app.exec()

    # 兜底收尾（on_app_exit 中已清理，此处幂等重入）
    _cleanup_process_facilities(facilities)

    non_daemon_alive = [
        t for t in threading.enumerate()
        if t.is_alive() and not t.daemon and t is not threading.main_thread()
    ]
    for thread in non_daemon_alive:
        thread.join(timeout=1.0)
        if thread.is_alive():
            warning(f"线程 {thread.name} 未能正常退出")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
