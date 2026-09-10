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
  - 内部子进程分流：--faf-thumbnail-worker
  - 首帧分阶段启动调度（见 freeassetfilter.app.startup）
  - 退出链（心跳停止 → fd 卸载 → 设置落盘 → 日志 flush → 互斥体释放）

模块级零副作用：全部设施安装发生在 ``main()`` 内，导入本模块不会
接管 fd / 注册钩子（便于测试与复用）。

主窗口为 ``freeassetfilter.ui.main_window.MainWindow``。
单实例守卫见 ``freeassetfilter.app.instance_guard``；
启动任务编排见 ``freeassetfilter.app.startup``。

注意：``ui/main_window.py`` 底部保留了独立的调试入口 ``main()``
（方便单独跑窗口调试；两入口在启动行为上应保持一致，后续若合并
入口请同步删除该调试函数及相关注释）。
"""

from __future__ import annotations

import atexit
import ctypes
import faulthandler
import logging
import os
import sys
import threading
import time
import warnings

# 确保包能被正确导入（PyInstaller 直接执行本脚本时也需要）
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from freeassetfilter.utils.app_logger import (
    get_logger,
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

    # DPI 感知声明（历史遗留保险）：
    #   Qt6 默认已启用高 DPI 缩放（等效于声明 PerMonitorV2），本块在
    #   常规环境下冗余；保留用于 PyInstaller 冻结 exe / Qt 行为变化的
    #   保险（缺失时高 DPI 屏可能退化为 Windows 位图拉伸而模糊）。
    #   TODO(优化整理)：后续评估是否随 Qt6 默认行为稳定后移除。
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
    QPixmapCache.setCacheLimit(50 * 1024 * 1024)

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

    # 创建主窗口
    try:
        from freeassetfilter.ui.main_window import MainWindow

        window = MainWindow()
    except Exception as e:
        error_msg = f"应用程序初始化失败：{e}\n\n请尝试重启程序。如果问题持续，请检查日志文件。"
        error(error_msg)
        try:
            if sys.platform == "win32":
                ctypes.windll.user32.MessageBoxW(0, error_msg, "启动错误 - FreeAssetFilter", 0x10)
        except Exception:
            pass
        sys.exit(1)
    info(f"[启动] 主窗口创建: {(time.perf_counter()-_start_ts)*1000:.0f}ms")

    controller = StartupController(app, window)

    window.show()
    info(f"[启动] 窗口显示: {(time.perf_counter()-_start_ts)*1000:.0f}ms")

    # 无边框能力运行时检查（Qt<6.10 退化时显著告警，不阻塞启动）
    _warn_if_frameless_unsupported()

    controller.schedule_startup_tasks()
    info(f"[启动] 启动任务已调度: {(time.perf_counter()-_start_ts)*1000:.0f}ms")

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
        except Exception:
            pass

        # 5) 清理实例信息与互斥体
        try:
            instance_guard._remove_runtime_instance_info(expected_pid=os.getpid())
        except Exception:
            pass
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
