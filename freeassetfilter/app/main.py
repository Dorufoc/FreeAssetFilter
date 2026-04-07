#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0.0
master
Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

FreeAssetFilter 主程序
核心功能应用程序，不包含视频播放器功能
"""

# 导入必要的模块用于异常处理
import sys
import os
import json
import warnings
import time
import traceback
import threading
import subprocess
import faulthandler

# 添加父目录到Python路径，确保包能被正确导入
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 导入日志模块（必须在其他导入之前，确保日志功能可用）
from freeassetfilter.utils.app_logger import (
    get_logger, info, debug, warning, error, critical,
    log_exception, install_console_capture
)

# 初始化日志系统
logger = get_logger()

# 尽早安装 stdout/stderr 双写捕获：
# - 保留原控制台输出（如果存在）
# - 将 print/sys.stdout.write/sys.stderr.write/traceback.print_exc 等同步写入日志文件
try:
    if install_console_capture(logger.get_log_file_path()):
        info(f"已启用控制台输出捕获，标准输出/错误将同步写入日志: {logger.get_log_file_path()}")
    else:
        warning("控制台输出捕获未能启用，部分直接控制台输出可能不会写入日志")
except (OSError, IOError, PermissionError, FileNotFoundError) as e:
    warning(f"启用控制台输出捕获失败 - 文件操作错误: {e}")
except (ValueError, TypeError) as e:
    warning(f"启用控制台输出捕获失败 - 数据转换错误: {e}")


def _get_available_stderr_stream():
    """
    获取可用于 faulthandler 的 stderr 流
    优先使用 sys.__stderr__，确保尽量绕过可能被包装/替换的 sys.stderr
    """
    for stream_name in ("__stderr__", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue

        try:
            if stream.closed:
                continue
        except (AttributeError, ValueError):
            pass

        try:
            stream.fileno()
        except (AttributeError, OSError, ValueError, TypeError):
            continue

        return stream

    return None


def _create_fault_output_tee(stderr_stream, log_file_path):
    """
    创建 faulthandler 的双写输出通道：
    - 一个写端提供给 faulthandler
    - 后台线程将内容同时转发到 stderr 和日志文件

    Returns:
        tuple[file | None, file | None, threading.Thread | None]:
            (提供给 faulthandler 的写端, 日志文件句柄, 转发线程)
    """
    import os

    stderr_fd = stderr_stream.fileno()
    log_file = open(log_file_path, "ab", buffering=0)

    read_fd, write_fd = os.pipe()
    write_stream = os.fdopen(write_fd, "wb", buffering=0)

    def _tee_worker():
        try:
            while True:
                chunk = os.read(read_fd, 4096)
                if not chunk:
                    break

                try:
                    os.write(stderr_fd, chunk)
                except OSError:
                    pass

                try:
                    log_file.write(chunk)
                except (OSError, ValueError):
                    pass
        finally:
            try:
                os.close(read_fd)
            except OSError:
                pass

            try:
                log_file.flush()
            except (OSError, ValueError):
                pass

    tee_thread = threading.Thread(
        target=_tee_worker,
        name="FaultHandlerTee",
        daemon=True
    )
    tee_thread.start()

    return write_stream, log_file, tee_thread


# 启用 faulthandler：
# - 有 stderr 且日志文件可用时，尽量同时输出到终端和日志
# - 只有 stderr 时输出到 stderr
# - 没有控制台终端时仅写入日志
_fault_handler_file = None
_fault_handler_output = None
_fault_handler_tee_thread = None
_fault_handler_enabled = False

fault_stream = _get_available_stderr_stream()
log_file_path = None
try:
    log_file_path = logger.get_log_file_path()
except (AttributeError, OSError, IOError, PermissionError, FileNotFoundError, ValueError, TypeError):
    log_file_path = None

if fault_stream is not None and log_file_path:
    try:
        _fault_handler_output, _fault_handler_file, _fault_handler_tee_thread = _create_fault_output_tee(
            fault_stream, log_file_path
        )
        faulthandler.enable(file=_fault_handler_output, all_threads=True)
        info(f"faulthandler已启用，崩溃信息将同时输出到stderr和日志: {log_file_path}")
        _fault_handler_enabled = True
    except (OSError, IOError, PermissionError, FileNotFoundError) as e:
        warning(f"启用faulthandler双写输出失败 - 文件操作错误: {e}")
    except (ValueError, TypeError) as e:
        warning(f"启用faulthandler双写输出失败 - 数据转换错误: {e}")

if not _fault_handler_enabled and fault_stream is not None:
    try:
        faulthandler.enable(file=fault_stream, all_threads=True)
        info("faulthandler已启用，崩溃信息将输出到stderr")
        _fault_handler_enabled = True
    except (OSError, IOError, PermissionError, FileNotFoundError) as e:
        warning(f"启用faulthandler到stderr失败 - 文件操作错误: {e}")
    except (ValueError, TypeError) as e:
        warning(f"启用faulthandler到stderr失败 - 数据转换错误: {e}")

if not _fault_handler_enabled and log_file_path:
    try:
        _fault_handler_file = open(log_file_path, "a", encoding="utf-8")
        faulthandler.enable(file=_fault_handler_file, all_threads=True)
        info(f"faulthandler已启用，C++层崩溃信息将写入日志: {log_file_path}")
        _fault_handler_enabled = True
    except (OSError, IOError, PermissionError, FileNotFoundError) as e:
        warning(f"启用faulthandler到日志文件失败 - 文件操作错误: {e}")
    except (ValueError, TypeError) as e:
        warning(f"启用faulthandler到日志文件失败 - 数据转换错误: {e}")

if not _fault_handler_enabled:
    warning("faulthandler未能启用，C++层崩溃信息可能无法被捕获")


def debug_exit_threads():
    """
    在程序退出前打印当前仍然活跃的线程，便于排查退出卡住问题
    - 输出线程基础信息
    - 尝试输出线程类型
    - 尝试输出当前 Python 栈，尤其用于定位 DummyThread 来源
    """
    try:
        current_frames = sys._current_frames()
    except Exception as e:
        current_frames = {}
        warning(f"获取当前线程栈帧失败: {e}")

    try:
        for thread in threading.enumerate():
            try:
                thread_type = f"{thread.__class__.__module__}.{thread.__class__.__name__}"
                is_dummy_thread = isinstance(thread, threading._DummyThread)
                extra_hint = " [外部/native线程代理]" if is_dummy_thread else ""
                info(
                    f"活跃线程: {thread.name}, "
                    f"线程类型: {thread_type}, "
                    f"是否守护线程: {thread.daemon}, "
                    f"线程标识: {thread.ident}, "
                    f"是否存活: {thread.is_alive()}"
                    f"{extra_hint}"
                )

                frame = current_frames.get(thread.ident)
                if frame is None:
                    info(f"线程 {thread.name} 无可用 Python 栈信息")
                    continue

                stack_text = "".join(traceback.format_stack(frame)).rstrip()
                if stack_text:
                    info(f"线程 {thread.name} 当前调用栈:\n{stack_text}")
            except Exception as e:
                warning(f"打印线程信息失败: {e}")
    except Exception as e:
        warning(f"枚举活跃线程失败: {e}")


def cleanup_fault_handler_tee():
    """
    退出前主动关闭 faulthandler 双写通道，促使 FaultHandlerTee 线程自然退出
    """
    global _fault_handler_output, _fault_handler_file, _fault_handler_tee_thread

    try:
        if _fault_handler_output is not None:
            try:
                _fault_handler_output.close()
            except (OSError, ValueError):
                pass
            _fault_handler_output = None

        if _fault_handler_tee_thread is not None and _fault_handler_tee_thread.is_alive():
            _fault_handler_tee_thread.join(timeout=1.0)

        if _fault_handler_file is not None:
            try:
                _fault_handler_file.flush()
            except (OSError, ValueError):
                pass
            try:
                _fault_handler_file.close()
            except (OSError, ValueError):
                pass
            _fault_handler_file = None
    except Exception as e:
        warning(f"清理 faulthandler 双写线程失败: {e}")


# 定义异常处理函数
def handle_exception(exc_type, exc_value, exc_traceback):
    """
    处理未捕获的Python异常

    Args:
        exc_type: 异常类型
        exc_value: 异常值
        exc_traceback: 异常回溯信息
    """
    if issubclass(exc_type, KeyboardInterrupt):
        # 如果是用户中断，使用系统默认的异常处理
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    # 使用日志模块记录异常
    log_exception(exc_type, exc_value, exc_traceback)

def handle_thread_exception(args):
    """
    处理 Python 子线程中的未捕获异常

    Args:
        args: threading.ExceptHookArgs
    """
    try:
        if issubclass(args.exc_type, KeyboardInterrupt):
            return
    except TypeError:
        pass

    log_exception(args.exc_type, args.exc_value, args.exc_traceback)


# 将系统异常钩子绑定到自定义处理函数
sys.excepthook = handle_exception
threading.excepthook = handle_thread_exception

# 忽略sipPyTypeDict相关的弃用警告
warnings.filterwarnings("ignore", category=DeprecationWarning, module="PySide6")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*sipPyTypeDict.*")

try:
    import pillow_avif
except ImportError as e:
    logger.debug(f"pillow_avif 模块未安装: {e}")

from freeassetfilter.utils.path_utils import get_resource_path, get_app_data_path, get_config_path, get_app_version

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGroupBox, QGridLayout, QSizePolicy, QSplitter, QMessageBox
)
from PySide6.QtCore import Qt, QUrl, QEvent, QTimer, QThread
from freeassetfilter.components.update_controller import UpdateController
from PySide6.QtGui import QFont, QIcon


class StartupWarmupThread(QThread):
    """
    启动后后台预热线程
    避免 LUT/C++ 相关初始化阻塞主线程首屏展示
    """

    def run(self):
        try:
            from freeassetfilter.core.cpp_lut_preview import warmup as lut_cpp_warmup
            info("[预热] 开始后台预热 LUT 预览 C++ 模块...")
            lut_cpp_warmup()

            from freeassetfilter.core.lut_preview_generator import get_preview_generator
            info("[预热] 开始后台预加载 LUT 生成器...")
            get_preview_generator()
            info("[预热] LUT 预览后台预热完成")
        except (OSError, IOError, PermissionError, FileNotFoundError) as e:
            error(f"[预热] LUT 预览后台预热失败 - 文件操作错误: {e}")
        except (ValueError, TypeError) as e:
            error(f"[预热] LUT 预览后台预热失败 - 数据转换错误: {e}")
        except (ImportError, ModuleNotFoundError) as e:
            error(f"[预热] LUT 预览后台预热失败 - 模块导入错误: {e}")
        except Exception as e:
            error(f"[预热] LUT 预览后台预热失败 - 未知错误: {e}")


class FreeAssetFilterApp(QMainWindow):
    """
    FreeAssetFilter 主应用程序类
    提供核心功能的主界面
    """

    def __init__(self):
        super().__init__()

        # 获取应用实例
        app = QApplication.instance()

        # 使用逻辑像素设置窗口大小，Qt会自动处理DPI
        base_window_width = 650  # 基础逻辑像素（100%缩放时的大小）

        # 获取当前光标所在的屏幕（多显示器环境下更准确）
        from PySide6.QtGui import QCursor
        cursor_pos = QCursor.pos()
        screen = QApplication.screenAt(cursor_pos)
        if screen is None:
            screen = QApplication.primaryScreen()

        # 获取系统缩放因子并设置为1.5倍
        logical_dpi = screen.logicalDotsPerInch()
        physical_dpi = screen.physicalDotsPerInch()
        system_scale = physical_dpi / logical_dpi if logical_dpi > 0 else 1.0

        # 设置默认大小为系统缩放的1.5倍
        window_width = int(base_window_width * system_scale * 1.5)
        window_height = int(window_width * (10 / 16))

        # 获取当前屏幕的可用尺寸（逻辑像素）
        # 使用 geometry() 而不是 availableGeometry() 避免多显示器虚拟桌面问题
        screen_geometry = screen.geometry()
        available_geometry = screen.availableGeometry()
        available_width_logical = available_geometry.width()
        available_height_logical = available_geometry.height()

        # 确保窗口大小不超过当前屏幕可用尺寸（使用逻辑像素）
        self.window_width = min(window_width, available_width_logical - 20)  # 留20px边距
        self.window_height = min(window_height, available_height_logical - 20)  # 留20px边距

        self.setWindowTitle("FreeAssetFilter")

        # 设置窗口大小
        self.resize(int(self.window_width), int(self.window_height))

        # 使用PySide6内置方法将窗口居中到当前屏幕的可用区域
        # 获取窗口的几何尺寸
        window_geometry = self.frameGeometry()
        # 获取当前屏幕可用区域的中心点
        center_point = available_geometry.center()
        # 将窗口的中心移动到屏幕可用区域的中心
        window_geometry.moveCenter(center_point)
        # 设置窗口位置（自动处理物理像素和逻辑像素的转换）
        self.move(window_geometry.topLeft())

        # 设置程序图标
        icon_path = get_resource_path('freeassetfilter/icons/FAF-main.ico')
        self.setWindowIcon(QIcon(icon_path))

        # 用于生成唯一的文件选择器实例ID
        self.file_selector_counter = 0

        # 主题更新状态标志，防止重复调用
        self._update_theme_in_progress = False
        self._theme_update_queued = False
        self._ui_state_backup = None
        self._splitter = None

        # 启动阶段异步任务状态
        self._pending_restore_items = []
        self._pending_restore_unlinked_files = []
        self._restore_total_count = 0
        self._restore_success_count = 0
        self._restore_batch_size = 20
        self._startup_warmup_thread = None

        # 更新控制器
        self.update_controller = UpdateController(self)

        # 获取全局字体
        global_font = getattr(app, 'global_font', QFont())
        # 创建全局字体的副本，避免修改全局字体对象
        self.global_font = QFont(global_font)

        # 设置窗口字体
        self.setFont(self.global_font)

        # 创建UI
        self.init_ui()

        # 启用窗口激活事件监听，用于焦点管理
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, False)

        # 应用窗口标题栏深色模式（根据当前主题设置）
        self._apply_title_bar_theme()

    def _cleanup_preview_before_close(self):
        """
        在主窗口关闭前优先清理预览区域，避免预览组件在主程序销毁过程中残留资源。
        """
        if not hasattr(self, 'unified_previewer') or not self.unified_previewer:
            return

        try:
            # 先停止任何正在运行的预览线程
            if hasattr(self.unified_previewer, '_preview_thread') and self.unified_previewer._preview_thread:
                if self.unified_previewer._preview_thread.isRunning():
                    self.unified_previewer._preview_thread.cancel()
                    self.unified_previewer._preview_thread.wait(500)
                    if self.unified_previewer._preview_thread.isRunning():
                        self.unified_previewer._preview_thread.terminate()
                        self.unified_previewer._preview_thread.wait(100)

            # 清理预览区域内容
            self.unified_previewer._clear_preview(app_closing=True)

            # 清理文件信息面板内容
            if hasattr(self.unified_previewer, 'file_info_viewer') and self.unified_previewer.file_info_viewer:
                self.unified_previewer.file_info_viewer.current_file = None
                self.unified_previewer.file_info_viewer.file_info = {}

                if hasattr(self.unified_previewer.file_info_viewer, 'basic_info_labels'):
                    for key, widget in self.unified_previewer.file_info_viewer.basic_info_labels.items():
                        widget.setPlainText("-")

                if hasattr(self.unified_previewer.file_info_viewer, 'details_info_widgets'):
                    for label_widget, value_widget in self.unified_previewer.file_info_viewer.details_info_widgets:
                        label_widget.setText("")
                        value_widget.setPlainText("-")

            # 重置当前预览状态，确保主程序继续退出前界面已被清空
            self.unified_previewer.current_file_info = None
            if hasattr(self.unified_previewer, 'default_label') and self.unified_previewer.default_label:
                self.unified_previewer.default_label.show()
            if hasattr(self.unified_previewer, 'clear_preview_button'):
                self.unified_previewer.clear_preview_button.hide()
            if hasattr(self.unified_previewer, 'open_with_system_button'):
                self.unified_previewer.open_with_system_button.hide()
            if hasattr(self.unified_previewer, 'copy_to_clipboard_button'):
                self.unified_previewer.copy_to_clipboard_button.hide()
            if hasattr(self.unified_previewer, 'locate_in_selector_button'):
                self.unified_previewer.locate_in_selector_button.hide()
        except Exception as e:
            logger.warning(f"关闭主窗口前清理预览区域失败: {e}")

    def closeEvent(self, event):
        """
        主窗口关闭事件，确保先清理预览区域，再保存状态并关闭主程序
        """
        

        # 用户尝试关闭程序时，优先清理预览区域
        self._cleanup_preview_before_close()

        # 关闭所有子窗口，确保全局设置窗口等随主窗口关闭而销毁
        from PySide6.QtWidgets import QDialog
        for widget in self.findChildren(QDialog):
            widget.close()

        # 保存文件选择器A的当前路径
        last_path = 'All'
        if hasattr(self, 'file_selector_a'):
            self.file_selector_a.save_current_path()
            last_path = self.file_selector_a.current_path
        # 保存文件存储池状态，传递文件选择器的当前路径
        if hasattr(self, 'file_staging_pool'):
            self.file_staging_pool.save_backup(last_path)

        # 统一清理：删除整个temp文件夹
        import shutil
        import os
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        temp_dir = os.path.join(project_root, "data", "temp")
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                logger.debug(f"已删除临时文件夹: {temp_dir}")
            except (OSError, PermissionError) as e:
                logger.warning(f"删除临时文件夹失败: {e}")

        # 停止后台预热线程
        if self._startup_warmup_thread and self._startup_warmup_thread.isRunning():
            self._startup_warmup_thread.quit()
            self._startup_warmup_thread.wait(500)

        cleanup_fault_handler_tee()
        debug_exit_threads()

        # 调用父类的closeEvent
        super().closeEvent(event)

    def _apply_title_bar_theme(self):
        """
        应用窗口标题栏主题（深色/浅色模式）
        使用 Windows DWM API 设置标题栏颜色跟随系统/应用主题
        """
        try:
            import ctypes
            from ctypes import wintypes

            # 获取窗口句柄
            hwnd = int(self.winId())

            # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Windows 10 1903+)
            # DWMWA_USE_IMMERSIVE_DARK_MODE = 19 (Windows 10 1809)
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20

            # 获取当前主题模式
            app = QApplication.instance()
            is_dark_mode = False
            if hasattr(app, 'settings_manager'):
                is_dark_mode = app.settings_manager.get_setting("appearance.theme", "default") == "dark"

            # 设置深色模式属性 (1 = 启用深色, 0 = 禁用深色/使用浅色)
            dark_mode_value = wintypes.BOOL(1 if is_dark_mode else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(dark_mode_value),
                ctypes.sizeof(dark_mode_value)
            )

        except (AttributeError, OSError, ctypes.WinError) as e:
            # 如果设置失败（非Windows系统或DWM API不可用），静默忽略
            logger.debug(f"设置标题栏主题失败（非Windows系统或DWM API不可用）: {e}")

    def focusInEvent(self, event):
        """
        处理焦点进入事件
        - 确保组件获得焦点时能够接收键盘事件
        """
        super().focusInEvent(event)

    def resizeEvent(self, event):
        """
        处理窗口大小变化事件
        - Qt会自动处理DPI变化
        - 监听窗口尺寸变化，稳定后重新计算卡片尺寸
        """
        super().resizeEvent(event)
        QTimer.singleShot(50, self._on_resize_stabilized)

    def _on_resize_stabilized(self):
        """
        窗口尺寸稳定后的回调
        - 使用连续检测机制确保窗口尺寸已完全稳定
        """
        self._check_and_update_cards(retry_count=0)

    def _check_and_update_cards(self, retry_count=0):
        """
        检测并更新卡片尺寸
        - 连续检测窗口尺寸是否稳定
        """
        if not hasattr(self, 'file_selector_a') or not self.file_selector_a:
            return

        if not hasattr(self.file_selector_a, '_update_all_cards_width'):
            return

        container = self.file_selector_a.files_container
        current_width = container.width()

        if current_width <= 0:
            max_retries = 15
            if retry_count < max_retries:
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()
                QTimer.singleShot(30, lambda: self._check_and_update_cards(retry_count + 1))
            return

        self.file_selector_a._update_all_cards_width()

    def changeEvent(self, event):
        """
        处理窗口状态变化事件
        - 监听窗口最大化/窗口化状态变化
        - 状态变化时重新计算文件选择器卡片尺寸
        """
        if event.type() == QEvent.WindowStateChange:
            QTimer.singleShot(200, self._on_window_state_changed)
        super().changeEvent(event)

    def _on_window_state_changed(self):
        """
        窗口状态变化后的回调
        - 延迟执行确保布局完成
        - 连续检测直到窗口尺寸稳定
        """
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        self._check_and_update_cards(retry_count=0)

    def _create_file_selector_widget(self):
        """
        创建内嵌式文件选择器组件

        Returns:
            QWidget: 内嵌式文件选择器组件
        """
        from freeassetfilter.components.file_selector import CustomFileSelector
        return CustomFileSelector()

    def _get_theme_colors(self):
        """
        获取当前主题相关颜色，优先使用设置管理器缓存接口
        """
        app = QApplication.instance()
        auxiliary_color = "#f1f3f5"
        normal_color = "#e0e0e0"
        base_color = "#212121"

        if hasattr(app, "settings_manager"):
            auxiliary_color = app.settings_manager.get_setting(
                "appearance.colors.auxiliary_color", "#f1f3f5"
            )
            normal_color = app.settings_manager.get_setting(
                "appearance.colors.normal_color", "#e0e0e0"
            )
            base_color = app.settings_manager.get_setting(
                "appearance.colors.base_color", "#212121"
            )

        return auxiliary_color, normal_color, base_color

    def _refresh_widget_self_only(self, widget):
        """
        仅刷新单个控件自身样式，不递归处理子控件
        """
        if not widget:
            return

        try:
            if hasattr(widget, "apply_theme_from_settings"):
                widget.apply_theme_from_settings()
        except (RuntimeError, AttributeError, TypeError) as e:
            logger.debug(f"应用控件主题设置失败: {e}")

        try:
            style = widget.style()
            if style is not None:
                style.unpolish(widget)
                style.polish(widget)
        except (RuntimeError, AttributeError, TypeError) as e:
            logger.debug(f"重新 polish 控件样式失败: {e}")

        try:
            widget.update()
        except (RuntimeError, AttributeError):
            pass

    def _refresh_widget_theme_recursively(self, root_widget, visited=None):
        """
        递归刷新控件树主题，优先调用组件自己的 update_theme，避免重复遍历整棵子树
        """
        if not root_widget:
            return

        if visited is None:
            visited = set()

        widget_id = id(root_widget)
        if widget_id in visited:
            return
        visited.add(widget_id)

        has_explicit_theme_handler = False

        try:
            if hasattr(root_widget, "update_theme"):
                root_widget.update_theme()
                has_explicit_theme_handler = True
            elif hasattr(root_widget, "set_theme"):
                root_widget.set_theme()
                has_explicit_theme_handler = True
            elif hasattr(root_widget, "_init_animations"):
                root_widget._init_animations()
        except (RuntimeError, AttributeError, TypeError) as e:
            logger.debug(f"递归刷新控件主题入口失败: {e}")

        self._refresh_widget_self_only(root_widget)

        # 组件自己已经处理其内部主题时，不再对子树做重复遍历
        if has_explicit_theme_handler:
            return

        try:
            for child in root_widget.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
                if child is root_widget:
                    continue
                self._refresh_widget_theme_recursively(child, visited)
        except (RuntimeError, AttributeError, TypeError) as e:
            logger.debug(f"递归遍历子控件失败: {e}")

    def _apply_theme_to_existing_widgets(self):
        """
        对当前已存在的控件树执行增量主题刷新，避免整棵布局重建
        """
        auxiliary_color, normal_color, base_color = self._get_theme_colors()
        border_radius = 8
        visited = set()

        if hasattr(self, "central_widget") and self.central_widget:
            self.central_widget.setStyleSheet(f"background-color: {auxiliary_color};")

        column_style = (
            f"background-color: {base_color}; "
            f"border: 1px solid {normal_color}; "
            f"border-radius: {border_radius}px;"
        )

        for widget_name in ("left_column", "middle_column", "right_column"):
            widget = getattr(self, widget_name, None)
            if widget:
                widget.setStyleSheet(column_style)

        if hasattr(self, "status_label") and self.status_label:
            self.status_label.setStyleSheet("color: #888888; margin-top: 0px;")

        themed_widgets = [
            getattr(self, "file_selector_a", None),
            getattr(self, "file_staging_pool", None),
            getattr(self, "unified_previewer", None),
            getattr(self, "github_button", None),
            getattr(self, "global_settings_button", None),
            getattr(self, "hover_tooltip", None),
        ]

        for widget in themed_widgets:
            if not widget:
                continue

            try:
                self._refresh_widget_theme_recursively(widget, visited)
            except (RuntimeError, AttributeError, TypeError) as e:
                logger.debug(f"递归刷新组件主题失败: {e}")

        # 顶层容器只刷新自身，避免把同一子树重复递归一遍
        for container_name in ("left_column", "middle_column", "right_column", "central_widget"):
            container = getattr(self, container_name, None)
            if container:
                try:
                    self._refresh_widget_self_only(container)
                except (RuntimeError, AttributeError, TypeError) as e:
                    logger.debug(f"刷新容器主题失败: {e}")

        if self._splitter:
            try:
                self._refresh_widget_self_only(self._splitter)
            except (RuntimeError, AttributeError, TypeError) as e:
                logger.debug(f"刷新分割器样式失败: {e}")

        if hasattr(self, "central_widget") and self.central_widget:
            self.central_widget.update()
        self.update()

    def init_ui(self):
        """
        初始化用户界面
        """
        # 创建中央部件
        self.central_widget = QWidget()
        # 获取主题颜色
        auxiliary_color, normal_color, base_color = self._get_theme_colors()
        self.central_widget.setStyleSheet(f"background-color: {auxiliary_color};")
        self.setCentralWidget(self.central_widget)

        # 创建主布局：标题 + 三列
        main_layout = QVBoxLayout(self.central_widget)
        # 设置间距和边距
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # 创建三列布局，使用QSplitter实现可拖动分割
        splitter = QSplitter(Qt.Horizontal)
        splitter.setContentsMargins(0, 0, 0, 0)
        self._splitter = splitter

        # 左侧列：文件选择器A
        self.left_column = QWidget()
        self.left_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 设置边框圆角
        border_radius = 8
        self.left_column.setStyleSheet(f"background-color: {base_color}; border: 1px solid {normal_color}; border-radius: {border_radius}px;")
        left_layout = QVBoxLayout(self.left_column)

        # 内嵌文件选择器A
        self.file_selector_a = self._create_file_selector_widget()
        left_layout.addWidget(self.file_selector_a)

        # 中间列：文件临时存储池
        self.middle_column = QWidget()
        self.middle_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.middle_column.setStyleSheet(f"background-color: {base_color}; border: 1px solid {normal_color}; border-radius: {border_radius}px;")
        middle_layout = QVBoxLayout(self.middle_column)

        # 添加文件临时存储池组件
        from freeassetfilter.components.file_staging_pool import FileStagingPool
        self.file_staging_pool = FileStagingPool()
        middle_layout.addWidget(self.file_staging_pool)

        # 右侧列：统一文件预览器
        self.right_column = QWidget()
        self.right_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.right_column.setStyleSheet(f"background-color: {base_color}; border: 1px solid {normal_color}; border-radius: {border_radius}px;")
        right_layout = QVBoxLayout(self.right_column)

        # 统一文件预览器
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer
        self.unified_previewer = UnifiedPreviewer(self)
        right_layout.addWidget(self.unified_previewer, 1)

        # 将三列添加到分割器，调整初始比例
        splitter.addWidget(self.left_column)
        splitter.addWidget(self.middle_column)
        splitter.addWidget(self.right_column)

        # 设置分割器初始大小，将三个板块宽度默认值设定为比值334（3:3:4）
        # 计算总宽度（使用逻辑像素）
        total_width = self.window_width - 40  # 减去边距和边框宽度
        # 根据3:3:4的比例分配宽度
        left_width = int(total_width * (3 / 10))
        middle_width = int(total_width * (3 / 10))
        right_width = int(total_width * (4 / 10))
        sizes = [left_width, middle_width, right_width]
        splitter.setSizes(sizes)

        # 连接文件选择器的左键点击信号到预览器
        self.file_selector_a.file_selected.connect(self.unified_previewer.set_file)

        # 连接文件选择器的选中状态变化信号到存储池（自动添加/移除）
        self.file_selector_a.file_selection_changed.connect(self.handle_file_selection_changed)

        # 连接预览器的信号：请求在文件选择器中打开路径，同时传递文件信息以便滚动定位
        self.unified_previewer.open_in_selector_requested.connect(lambda path, file_info: self.handle_navigate_to_path(path, file_info))

        # 连接文件临时存储池的信号到预览器
        self.file_staging_pool.item_right_clicked.connect(self.unified_previewer.set_file)
        # 添加左键点击信号连接，用于预览
        self.file_staging_pool.item_left_clicked.connect(self.unified_previewer.set_file)

        # 连接文件临时存储池的信号到处理方法，用于从文件选择器中删除文件
        self.file_staging_pool.remove_from_selector.connect(self.handle_remove_from_selector)

        # 连接文件临时存储池的信号到处理方法，用于通知文件选择器文件已被添加到储存池
        self.file_staging_pool.file_added_to_pool.connect(self.handle_file_added_to_pool)

        # 连接文件临时存储池的导航信号到处理方法，用于更新文件选择器的路径
        self.file_staging_pool.navigate_to_path.connect(self.handle_navigate_to_path)

        # 连接统一预览器的预览状态信号
        self.unified_previewer.preview_started.connect(self.handle_preview_started)
        self.unified_previewer.preview_cleared.connect(self.handle_preview_cleared)

        # 添加分割器到主布局
        main_layout.addWidget(splitter, 1)

        # 创建状态标签和全局设置按钮的布局
        status_container = QWidget()
        status_container_layout = QVBoxLayout(status_container)
        status_container_layout.setContentsMargins(0, 0, 0, 0)
        status_container_layout.setAlignment(Qt.AlignCenter)

        # 创建状态标签和全局设置按钮的水平布局
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)

        # 创建GitHub按钮，使用svg图标
        from freeassetfilter.widgets.button_widgets import CustomButton
        github_icon_path = get_resource_path('freeassetfilter/icons/github.svg')
        self.github_button = CustomButton(github_icon_path, button_type="normal", display_mode="icon", height=20, tooltip_text="跳转项目主页")
        self.github_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        # 连接到GitHub跳转函数
        self.github_button.clicked.connect(self._open_github)
        status_layout.addWidget(self.github_button)

        # 添加左侧占位符，将状态标签推到居中位置
        status_layout.addStretch()

        # 状态标签
        self.status_label = QLabel(
            f"FreeAssetFilter {get_app_version()} | By Dorufoc & renmoren | 遵循AGPL-3.0协议开源"
        )
        self.status_label.setAlignment(Qt.AlignCenter)
        # 使用小一号的字体
        status_font = QFont(self.global_font)
        status_font.setPointSize(int(self.global_font.pointSize() * 0.85))
        self.status_label.setFont(status_font)
        margin = 0
        self.status_label.setStyleSheet(f"color: #888888; margin-top: {margin}px;")
        status_layout.addWidget(self.status_label)

        # 添加右侧占位符，将全局设置按钮推到右侧
        status_layout.addStretch()

        # 创建更新按钮，显示在设置按钮左侧
        update_icon_path = get_resource_path('freeassetfilter/icons/update.svg')
        self.update_button = CustomButton(update_icon_path, button_type="normal", display_mode="icon", height=20, tooltip_text="检查更新")
        self.update_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        status_layout.addWidget(self.update_button)

        # 创建全局设置按钮，使用svg图标
        setting_icon_path = get_resource_path('freeassetfilter/icons/setting.svg')
        self.global_settings_button = CustomButton(setting_icon_path, button_type="normal", display_mode="icon", height=20, tooltip_text="全局设置")
        self.global_settings_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        # 连接到全局设置函数
        self.global_settings_button.clicked.connect(self._open_global_settings)
        status_layout.addWidget(self.global_settings_button)

        if hasattr(self, "update_controller") and self.update_controller:
            self.update_controller.bind_button(self.update_button)

        # 将水平布局添加到容器的垂直布局中
        status_container_layout.addLayout(status_layout)

        # 添加状态容器到主布局
        main_layout.addWidget(status_container)

        # 初始化自定义悬浮提示
        from freeassetfilter.widgets.hover_tooltip import HoverTooltip
        self.hover_tooltip = HoverTooltip(self)
        # 将底部按钮添加为目标控件
        self.hover_tooltip.set_target_widget(self.github_button)
        self.hover_tooltip.set_target_widget(self.update_button)
        self.hover_tooltip.set_target_widget(self.global_settings_button)

        # 应用主题设置
        self.update_theme()

    def _open_github(self):
        """打开GitHub项目主页"""
        import webbrowser
        webbrowser.open("https://github.com/Dorufoc/FreeAssetFilter")

    def _open_global_settings(self):
        """打开全局设置窗口"""
        if hasattr(self, 'unified_previewer') and hasattr(self.unified_previewer, '_open_global_settings'):
            self.unified_previewer._open_global_settings()

    def show_info(self, title, message):
        """
        显示信息提示

        Args:
            title (str): 提示标题
            message (str): 提示消息
        """
        # 简单的信息显示，使用状态标签
        self.status_label.setText(f"{title}: {message}")

    def _backup_ui_state(self):
        """
        备份当前UI状态到内存，避免主题切换过程中产生额外磁盘 I/O

        Returns:
            bool: 是否成功备份
        """
        try:
            backup_data = {
                "file_selector": {
                    "current_path": None,
                    "selected_files": {},
                    "_selected_file_paths": [],
                    "previewing_file_path": None,
                    "filter_pattern": "*",
                    "sort_by": "name",
                    "sort_order": "asc",
                    "view_mode": "card",
                },
                "file_staging_pool": {
                    "items": [],
                    "previewing_file_path": None,
                },
                "splitter_sizes": [100, 100, 100],
            }

            old_file_selector = getattr(self, "file_selector_a", None)
            old_staging_pool = getattr(self, "file_staging_pool", None)

            if old_file_selector:
                try:
                    if hasattr(old_file_selector, "current_path"):
                        backup_data["file_selector"]["current_path"] = old_file_selector.current_path
                    if hasattr(old_file_selector, "selected_files"):
                        selected = old_file_selector.selected_files
                        if isinstance(selected, dict):
                            backup_data["file_selector"]["selected_files"] = {
                                k: list(v) for k, v in selected.items()
                            }
                    if hasattr(old_file_selector, "_selected_file_paths"):
                        backup_data["file_selector"]["_selected_file_paths"] = list(
                            old_file_selector._selected_file_paths
                        )
                    if hasattr(old_file_selector, "previewing_file_path"):
                        backup_data["file_selector"]["previewing_file_path"] = old_file_selector.previewing_file_path
                    if hasattr(old_file_selector, "filter_pattern"):
                        backup_data["file_selector"]["filter_pattern"] = old_file_selector.filter_pattern
                    if hasattr(old_file_selector, "sort_by"):
                        backup_data["file_selector"]["sort_by"] = old_file_selector.sort_by
                    if hasattr(old_file_selector, "sort_order"):
                        backup_data["file_selector"]["sort_order"] = old_file_selector.sort_order
                    if hasattr(old_file_selector, "view_mode"):
                        backup_data["file_selector"]["view_mode"] = old_file_selector.view_mode
                except (RuntimeError, AttributeError) as e:
                    logger.debug(f"备份文件选择器状态时出错: {e}")

            if old_staging_pool:
                try:
                    if hasattr(old_staging_pool, "items"):
                        backup_data["file_staging_pool"]["items"] = list(old_staging_pool.items)
                    if hasattr(old_staging_pool, "previewing_file_path"):
                        backup_data["file_staging_pool"]["previewing_file_path"] = old_staging_pool.previewing_file_path
                except (RuntimeError, AttributeError) as e:
                    logger.debug(f"备份文件存储池状态时出错: {e}")

            if self._splitter:
                try:
                    backup_data["splitter_sizes"] = list(self._splitter.sizes())
                except (RuntimeError, AttributeError) as e:
                    logger.debug(f"备份分割器大小时出错: {e}")

            self._ui_state_backup = backup_data
            return True
        except (TypeError, AttributeError) as e:
            logger.warning(f"备份UI状态失败: {e}")
            return False

    def _restore_ui_state(self):
        """
        从内存恢复 UI 状态

        Returns:
            bool: 是否成功恢复
        """
        backup_data = self._ui_state_backup
        if not backup_data:
            return False

        try:
            new_file_selector = getattr(self, "file_selector_a", None)
            new_staging_pool = getattr(self, "file_staging_pool", None)

            if new_file_selector:
                try:
                    file_selector_state = backup_data.get("file_selector", {})

                    if "current_path" in file_selector_state:
                        new_file_selector.current_path = file_selector_state["current_path"]
                    if "selected_files" in file_selector_state:
                        raw_selected = file_selector_state["selected_files"]
                        if isinstance(raw_selected, dict):
                            new_file_selector.selected_files = {
                                k: set(v) if isinstance(v, list) else v
                                for k, v in raw_selected.items()
                            }
                    if "_selected_file_paths" in file_selector_state:
                        new_file_selector._selected_file_paths = set(file_selector_state["_selected_file_paths"])
                    if "previewing_file_path" in file_selector_state:
                        new_file_selector.previewing_file_path = file_selector_state["previewing_file_path"]
                    if "filter_pattern" in file_selector_state:
                        new_file_selector.filter_pattern = file_selector_state["filter_pattern"]
                    if "sort_by" in file_selector_state:
                        new_file_selector.sort_by = file_selector_state["sort_by"]
                    if "sort_order" in file_selector_state:
                        new_file_selector.sort_order = file_selector_state["sort_order"]
                    if "view_mode" in file_selector_state:
                        new_file_selector.view_mode = file_selector_state["view_mode"]

                    if hasattr(new_file_selector, "_update_filter_button_style"):
                        new_file_selector._update_filter_button_style()
                    if hasattr(new_file_selector, "_update_timeline_button_visibility"):
                        new_file_selector._update_timeline_button_visibility()
                    if hasattr(new_file_selector, "_update_file_selection_state"):
                        new_file_selector._update_file_selection_state()
                    if (
                        getattr(new_file_selector, "previewing_file_path", None)
                        and hasattr(new_file_selector, "set_previewing_file")
                    ):
                        new_file_selector.set_previewing_file(new_file_selector.previewing_file_path)
                except (RuntimeError, AttributeError) as e:
                    logger.debug(f"恢复文件选择器状态时出错: {e}")

            if new_staging_pool:
                try:
                    staging_pool_state = backup_data.get("file_staging_pool", {})
                    if "items" in staging_pool_state:
                        items_data = staging_pool_state["items"]
                        existing_paths = set()
                        if hasattr(new_staging_pool, "items"):
                            existing_paths = {
                                os.path.normpath(item.get("path", ""))
                                for item in new_staging_pool.items
                                if isinstance(item, dict) and item.get("path")
                            }

                        if hasattr(new_staging_pool, "add_file"):
                            for item_data in items_data:
                                try:
                                    if isinstance(item_data, dict) and "path" in item_data:
                                        item_path = os.path.normpath(item_data["path"])
                                        if item_path not in existing_paths:
                                            new_staging_pool.add_file(item_data)
                                            existing_paths.add(item_path)
                                except (TypeError, AttributeError) as e:
                                    logger.debug(f"添加文件到存储池时出错: {e}")
                                    continue

                    previewing_file_path = staging_pool_state.get("previewing_file_path")
                    if previewing_file_path:
                        if hasattr(new_staging_pool, "set_previewing_file"):
                            new_staging_pool.set_previewing_file(previewing_file_path)
                    elif hasattr(new_staging_pool, "clear_previewing_state"):
                        new_staging_pool.clear_previewing_state()
                except (RuntimeError, AttributeError) as e:
                    logger.debug(f"恢复文件存储池状态时出错: {e}")

            if "splitter_sizes" in backup_data and self._splitter:
                try:
                    old_sizes = backup_data["splitter_sizes"]
                    if sum(old_sizes) > 0:
                        self._splitter.setSizes(old_sizes)
                except (RuntimeError, AttributeError) as e:
                    logger.debug(f"恢复分割器大小时出错: {e}")

            return True
        except (TypeError, KeyError) as e:
            logger.warning(f"恢复UI状态失败: {e}")
            return False

    def _rebuild_main_layout(self):
        """
        重建主布局，用于主题切换时确保所有组件使用正确样式
        """
        app = QApplication.instance()
        if app is None:
            return False

        if not self.isVisible():
            return False

        if hasattr(app, 'global_font'):
            self.global_font = QFont(app.global_font)
            self.setFont(self.global_font)

        # 在整个重建过程中禁用更新，防止闪烁
        previous_updates_enabled = self.updatesEnabled()
        self.setUpdatesEnabled(False)
        
        # 保存应用实例的更新状态
        app_previous_updates_enabled = app.updatesEnabled()
        app.setUpdatesEnabled(False)
        
        # 启用 HoverTooltip 安全模式，防止在重建过程中意外显示
        if hasattr(self, 'hover_tooltip') and self.hover_tooltip:
            try:
                if hasattr(self.hover_tooltip, 'set_safe_mode'):
                    self.hover_tooltip.set_safe_mode(True)
            except (RuntimeError, AttributeError) as e:
                logger.debug(f"设置 HoverTooltip 安全模式失败: {e}")

        self._backup_ui_state()

        old_hover_tooltip = getattr(self, 'hover_tooltip', None)

        # 颜色直接从JSON文件读取，绕过内存缓存
        auxiliary_color = app.settings_manager.get_setting("appearance.colors.auxiliary_color", "#f1f3f5", use_file_for_colors=True)
        normal_color = app.settings_manager.get_setting("appearance.colors.normal_color", "#e0e0e0", use_file_for_colors=True)
        base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#212121", use_file_for_colors=True)
        border_radius = 8

        old_central_widget = getattr(self, 'central_widget', None)

        try:
            if old_central_widget:
                # 彻底隐藏所有窗口类型的控件，包括直接子窗口和递归查找的所有子窗口
                # 使用 findChildren 查找所有 QWidget 类型，检查它们是否是窗口
                all_widgets = old_central_widget.findChildren(QWidget)
                
                for child in all_widgets:
                    try:
                        # 检查控件是否有效
                        if not child or not hasattr(child, 'isWindow'):
                            continue
                        
                        # 隐藏所有窗口类型的控件
                        if child.isWindow():
                            # 停止可能正在运行的动画
                            if hasattr(child, 'stop'):
                                try:
                                    child.stop()
                                except (RuntimeError, AttributeError):
                                    pass
                            # 彻底隐藏
                            child.hide()
                            # 确保不处理事件
                            child.blockSignals(True)
                    except (RuntimeError, AttributeError):
                        continue
                
                # 额外检查主窗口的所有子窗口
                for child in self.findChildren(QWidget):
                    try:
                        if child and child.isWindow() and child != self:
                            child.hide()
                            child.blockSignals(True)
                    except (RuntimeError, AttributeError):
                        continue

                # 最后隐藏旧中央部件
                old_central_widget.hide()
                old_central_widget.blockSignals(True)
        except (RuntimeError, AttributeError) as e:
            logger.debug(f"隐藏旧中央部件时出错: {e}")

        self.central_widget = QWidget()
        self.central_widget.setStyleSheet(f"background-color: {auxiliary_color};")
        self.setCentralWidget(self.central_widget)

        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setContentsMargins(0, 0, 0, 0)
        self._splitter = splitter

        self.left_column = QWidget()
        self.left_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.left_column.setStyleSheet(f"background-color: {base_color}; border: 1px solid {normal_color}; border-radius: {border_radius}px;")
        left_layout = QVBoxLayout(self.left_column)

        self.file_selector_a = self._create_file_selector_widget()
        left_layout.addWidget(self.file_selector_a)

        self.middle_column = QWidget()
        self.middle_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.middle_column.setStyleSheet(f"background-color: {base_color}; border: 1px solid {normal_color}; border-radius: {border_radius}px;")
        middle_layout = QVBoxLayout(self.middle_column)

        from freeassetfilter.components.file_staging_pool import FileStagingPool
        self.file_staging_pool = FileStagingPool()
        middle_layout.addWidget(self.file_staging_pool)

        self.right_column = QWidget()
        self.right_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.right_column.setStyleSheet(f"background-color: {base_color}; border: 1px solid {normal_color}; border-radius: {border_radius}px;")
        right_layout = QVBoxLayout(self.right_column)

        from freeassetfilter.components.unified_previewer import UnifiedPreviewer
        self.unified_previewer = UnifiedPreviewer(self)
        right_layout.addWidget(self.unified_previewer, 1)

        splitter.addWidget(self.left_column)
        splitter.addWidget(self.middle_column)
        splitter.addWidget(self.right_column)

        total_width = self.window_width - 40
        left_width = int(total_width * (3 / 10))
        middle_width = int(total_width * (3 / 10))
        right_width = int(total_width * (4 / 10))
        splitter.setSizes([left_width, middle_width, right_width])

        self.file_selector_a.file_selected.connect(self.unified_previewer.set_file)
        self.file_selector_a.file_selection_changed.connect(self.handle_file_selection_changed)
        self.unified_previewer.open_in_selector_requested.connect(lambda path, file_info: self.handle_navigate_to_path(path, file_info))
        self.file_staging_pool.item_right_clicked.connect(self.unified_previewer.set_file)
        self.file_staging_pool.item_left_clicked.connect(self.unified_previewer.set_file)
        self.file_staging_pool.remove_from_selector.connect(self.handle_remove_from_selector)
        self.file_staging_pool.file_added_to_pool.connect(self.handle_file_added_to_pool)
        self.file_staging_pool.navigate_to_path.connect(self.handle_navigate_to_path)
        self.unified_previewer.preview_started.connect(self.handle_preview_started)
        self.unified_previewer.preview_cleared.connect(self.handle_preview_cleared)

        main_layout.addWidget(splitter, 1)

        status_container = QWidget()
        status_container_layout = QVBoxLayout(status_container)
        status_container_layout.setContentsMargins(0, 0, 0, 0)
        status_container_layout.setAlignment(Qt.AlignCenter)

        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)

        from freeassetfilter.widgets.button_widgets import CustomButton
        github_icon_path = get_resource_path('freeassetfilter/icons/github.svg')
        self.github_button = CustomButton(github_icon_path, button_type="normal", display_mode="icon", height=20, tooltip_text="跳转项目主页")
        self.github_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.github_button.clicked.connect(self._open_github)
        status_layout.addWidget(self.github_button)

        status_layout.addStretch()

        self.status_label = QLabel(
            f"FreeAssetFilter {get_app_version()} | By Dorufoc & renmoren | 遵循AGPL-3.0协议开源"
        )
        self.status_label.setAlignment(Qt.AlignCenter)
        status_font = QFont(self.global_font)
        status_font.setPointSize(int(self.global_font.pointSize() * 0.85))
        self.status_label.setFont(status_font)
        self.status_label.setStyleSheet("color: #888888; margin-top: 0px;")
        status_layout.addWidget(self.status_label)

        status_layout.addStretch()

        update_icon_path = get_resource_path('freeassetfilter/icons/update.svg')
        self.update_button = CustomButton(update_icon_path, button_type="normal", display_mode="icon", height=20, tooltip_text="检查更新")
        self.update_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        status_layout.addWidget(self.update_button)

        setting_icon_path = get_resource_path('freeassetfilter/icons/setting.svg')
        self.global_settings_button = CustomButton(setting_icon_path, button_type="normal", display_mode="icon", height=20, tooltip_text="全局设置")
        self.global_settings_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.global_settings_button.clicked.connect(self._open_global_settings)
        status_layout.addWidget(self.global_settings_button)

        if hasattr(self, "update_controller") and self.update_controller:
            self.update_controller.bind_button(self.update_button)

        status_container_layout.addLayout(status_layout)
        main_layout.addWidget(status_container)

        if old_hover_tooltip:
            try:
                if hasattr(old_hover_tooltip, 'cleanup'):
                    old_hover_tooltip.cleanup()
            except (RuntimeError, AttributeError) as e:
                logger.debug(f"清理旧 HoverTooltip 失败: {e}")

            try:
                old_hover_tooltip.hide()
            except (RuntimeError, AttributeError):
                pass

            try:
                old_hover_tooltip.setParent(None)
            except (RuntimeError, AttributeError):
                pass

            try:
                old_hover_tooltip.deleteLater()
            except (RuntimeError, AttributeError):
                pass

        from freeassetfilter.widgets.hover_tooltip import HoverTooltip
        self.hover_tooltip = HoverTooltip(self)
        self.hover_tooltip.set_target_widget(self.github_button)
        self.hover_tooltip.set_target_widget(self.update_button)
        self.hover_tooltip.set_target_widget(self.global_settings_button)

        self._restore_ui_state()
        
        # 恢复应用实例和主窗口的更新状态
        try:
            app.setUpdatesEnabled(app_previous_updates_enabled)
        except (RuntimeError, AttributeError):
            pass
        
        try:
            self.setUpdatesEnabled(previous_updates_enabled)
        except (RuntimeError, AttributeError):
            pass
        
        # 强制更新主窗口
        self.update()
        
        # 禁用 HoverTooltip 安全模式
        if hasattr(self, 'hover_tooltip') and self.hover_tooltip:
            try:
                if hasattr(self.hover_tooltip, 'set_safe_mode'):
                    self.hover_tooltip.set_safe_mode(False)
            except (RuntimeError, AttributeError) as e:
                logger.debug(f"禁用 HoverTooltip 安全模式失败: {e}")

        return True

    def update_theme(self, delayed=False):
        """
        更新应用主题：
        - 启动阶段窗口尚未显示时，使用轻量样式刷新
        - 窗口显示后，优先直接重建主布局，避免对整棵旧控件树做高成本增量刷新

        Args:
            delayed: 是否延迟执行，用于防止在窗口关闭时调用
        """
        if not delayed and self._update_theme_in_progress:
            if not self._theme_update_queued:
                self._theme_update_queued = True
                QTimer.singleShot(50, lambda: self.update_theme(delayed=True))
            return

        self._update_theme_in_progress = True
        self._theme_update_queued = False

        previous_updates_enabled = self.updatesEnabled()
        self.setUpdatesEnabled(False)

        # 清除SVG颜色缓存，确保新组件使用最新的主题颜色
        from freeassetfilter.core.svg_renderer import SvgRenderer
        SvgRenderer._invalidate_color_cache()

        try:
            # 启动阶段窗口未显示时，不做重建，避免无意义构造/销毁
            if not self.isVisible():
                if hasattr(self, "central_widget") and self.central_widget:
                    self._apply_theme_to_existing_widgets()
            else:
                success = self._rebuild_main_layout()
                if not success and hasattr(self, "central_widget") and self.central_widget:
                    self._apply_theme_to_existing_widgets()
        except (RuntimeError, AttributeError) as e:
            logger.warning(f"更新主题时出错，回退到轻量刷新: {e}")
            try:
                if hasattr(self, "central_widget") and self.central_widget:
                    self._apply_theme_to_existing_widgets()
            except (RuntimeError, AttributeError) as fallback_error:
                logger.warning(f"轻量刷新主题时出错: {fallback_error}")
        finally:
            self.setUpdatesEnabled(previous_updates_enabled)
            self._update_theme_in_progress = False

        self.update()

        # 更新窗口标题栏主题
        self._apply_title_bar_theme()

    def schedule_startup_tasks(self):
        """
        在首屏显示后分阶段执行启动任务，避免阻塞窗口显示
        """
        QTimer.singleShot(100, self.check_and_restore_backup)
        QTimer.singleShot(400, self._start_background_warmup)
        QTimer.singleShot(800, self._schedule_thumbnail_cleanup)

    def _start_background_warmup(self):
        """
        启动后台预热线程
        """
        if self._startup_warmup_thread and self._startup_warmup_thread.isRunning():
            return

        self._startup_warmup_thread = StartupWarmupThread(self)
        self._startup_warmup_thread.finished.connect(self._on_startup_warmup_finished)
        self._startup_warmup_thread.start()

    def _on_startup_warmup_finished(self):
        """
        后台预热完成回调
        """
        info("[预热] 启动阶段后台预热任务结束")

    def _schedule_thumbnail_cleanup(self):
        """
        将缩略图缓存清理延后到窗口显示后执行
        """
        app = QApplication.instance()
        settings_manager = getattr(app, 'settings_manager', None)
        if settings_manager is None:
            return

        if not settings_manager.get_setting("file_selector.auto_clear_thumbnail_cache", True):
            return

        cache_cleanup_period = settings_manager.get_setting("file_selector.cache_cleanup_period", 7)
        last_cleanup_time = settings_manager.get_setting("file_selector.last_cleanup_time", None)
        current_time = time.time()

        if last_cleanup_time is None or (current_time - last_cleanup_time) > (cache_cleanup_period * 86400):
            QTimer.singleShot(0, lambda: self._run_thumbnail_cleanup(cache_cleanup_period, current_time))

    def _run_thumbnail_cleanup(self, cache_cleanup_period, current_time):
        """
        执行缩略图缓存清理
        """
        try:
            from freeassetfilter.core.thumbnail_manager import clean_thumbnails
            deleted_count, remaining_count = clean_thumbnails(cleanup_period_days=cache_cleanup_period)
            info(f"[启动] 缩略图缓存清理完成: 删除 {deleted_count} 个文件，剩余 {remaining_count} 个文件")

            app = QApplication.instance()
            if hasattr(app, 'settings_manager'):
                app.settings_manager.set_setting("file_selector.last_cleanup_time", current_time)
                app.settings_manager.save_settings()
        except Exception as e:
            warning(f"[启动] 缩略图缓存清理失败: {e}")

    def show_custom_window_demo(self):
        """
        演示自定义窗口的使用
        """
        # 设置窗口大小
        window_width = 400
        window_height = 300

        # 创建自定义窗口实例，并将其赋值给self，防止被垃圾回收
        from freeassetfilter.widgets.D_widgets import CustomWindow
        from freeassetfilter.widgets.D_widgets import CustomButton
        self.custom_window = CustomWindow("自定义窗口演示", self)
        self.custom_window.setGeometry(200, 200, window_width, window_height)

        # 添加示例控件
        title_label = QLabel("这是一个自定义窗口")
        title_font = QFont(self.global_font)
        title_font.setPointSize(int(self.global_font.pointSize() * 1.5))
        title_font.setWeight(QFont.Weight.Bold)
        title_label.setFont(title_font)
        title_margin = 16
        title_label.setStyleSheet(f"""
            QLabel {{
                color: #333333;
                margin-bottom: {title_margin}px;
                text-align: center;
            }}
        """)
        self.custom_window.add_widget(title_label)

        info_label = QLabel("这个窗口具有以下特点：\n\n"
                            "• 纯白圆角矩形外观\n"
                            "• 右上角圆形关闭按钮\n"
                            "• 可拖拽移动（通过标题栏）\n"
                            "• 支持内嵌其他控件\n"
                            "• 带阴影效果")
        info_margin = 24
        info_label.setFont(self.global_font)
        info_label.setStyleSheet(f"""
            QLabel {{
                color: #666666;
                line-height: 1.6;
                margin-bottom: {info_margin}px;
            }}
        """)
        info_label.setWordWrap(True)
        self.custom_window.add_widget(info_label)

        demo_button = CustomButton("示例按钮")
        demo_button.clicked.connect(lambda: QMessageBox.information(self.custom_window, "提示", "自定义按钮被点击了！"))
        self.custom_window.add_widget(demo_button)

        self.custom_window.show()

    def handle_file_selection_changed(self, file_info, is_selected):
        """
        处理文件选择状态变化事件

        Args:
            file_info (dict): 文件信息
            is_selected (bool): 是否被选中
        """
        import datetime
        from freeassetfilter.utils.app_logger import debug as logger_debug

        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            logger_debug(f"[{timestamp}] [handle_file_selection_changed] {msg}")

        file_path = os.path.normpath(file_info['path'])
        debug(f"文件选择状态变化: 路径={file_path}, 选中={is_selected}")

        if is_selected:
            existing_paths = [os.path.normpath(item['path']) for item in self.file_staging_pool.items]
            debug(f"储存池现有路径: {existing_paths}")
            if file_path not in existing_paths:
                debug(f"文件不在储存池中，准备添加")
                self.file_staging_pool.add_file(file_info)
            else:
                debug(f"文件已在储存池中，跳过添加")
        else:
            debug(f"取消选中，准备从储存池移除")
            self.file_staging_pool.remove_file(file_path)

    def handle_remove_from_selector(self, file_info):
        """
        从文件选择器中删除文件（取消选中状态）

        Args:
            file_info (dict): 文件信息
        """
        import datetime
        from freeassetfilter.utils.app_logger import debug as logger_debug

        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            logger_debug(f"[{timestamp}] [handle_remove_from_selector] {msg}")

        file_path = os.path.normpath(file_info['path'])
        file_dir = os.path.normpath(os.path.dirname(file_path))
        debug(f"从选择器移除文件: 路径={file_path}, 目录={file_dir}")
        debug(f"移除前的selected_files: {self.file_selector_a.selected_files}")

        if file_dir in self.file_selector_a.selected_files:
            self.file_selector_a.selected_files[file_dir].discard(file_path)
            debug(f"从集合中移除文件，剩余文件: {self.file_selector_a.selected_files[file_dir]}")

            if not self.file_selector_a.selected_files[file_dir]:
                del self.file_selector_a.selected_files[file_dir]
                debug(f"目录集合为空，删除目录条目")

        if hasattr(self.file_selector_a, '_selected_file_paths'):
            self.file_selector_a._selected_file_paths.discard(file_path)
            debug(f"移除后的扁平选中集合: {self.file_selector_a._selected_file_paths}")

        debug(f"移除后的selected_files: {self.file_selector_a.selected_files}")
        debug(f"调用_update_file_selection_state")
        self.file_selector_a._update_file_selection_state()

    def handle_navigate_to_path(self, path, file_info=None):
        """
        处理导航到指定路径的请求，更新文件选择器的当前路径

        Args:
            path (str): 要导航到的路径
            file_info (dict, optional): 文件信息，如果提供则导航后滚动到该文件位置
        """
        if hasattr(self, 'file_selector_a') and self.file_selector_a:
            path = os.path.normpath(path)
            self.file_selector_a.current_path = path

            def on_files_refreshed():
                if file_info:
                    self.file_staging_pool.add_file(file_info)
                self.file_selector_a._update_file_selection_state()
                # 滚动到目标文件位置
                if file_info:
                    self.file_selector_a.scroll_to_file(file_info)

            self.file_selector_a.refresh_files(callback=on_files_refreshed, scroll_to_top=not file_info)

    def handle_file_added_to_pool(self, file_info):
        """
        处理文件被添加到储存池的事件，将文件添加到文件选择器的选中文件列表中

        Args:
            file_info (dict): 文件信息
        """
        file_path = os.path.normpath(file_info['path'])
        file_dir = os.path.normpath(os.path.dirname(file_path))

        if file_dir not in self.file_selector_a.selected_files:
            self.file_selector_a.selected_files[file_dir] = set()

        if file_path not in self.file_selector_a.selected_files[file_dir]:
            self.file_selector_a.selected_files[file_dir].add(file_path)

        if hasattr(self.file_selector_a, '_selected_file_paths'):
            self.file_selector_a._selected_file_paths.add(file_path)

        def on_files_refreshed():
            self.file_selector_a._update_file_selection_state()

        if self.file_selector_a.current_path == file_dir:
            if self.file_selector_a._is_loading:
                self.file_selector_a._refresh_callback = on_files_refreshed
            else:
                self.file_selector_a._update_file_selection_state()
        else:
            self.file_selector_a._update_file_selection_state()

    def handle_preview_started(self, file_info):
        """
        处理预览开始事件，更新文件选择器和存储池中对应文件的预览态

        Args:
            file_info (dict): 文件信息
        """
        file_path = file_info.get('path', '')
        debug(f"[Main] handle_preview_started called with path: {file_path}")
        if not file_path:
            return

        # 更新文件选择器中的卡片预览态
        if hasattr(self, 'file_selector_a') and self.file_selector_a:
            self.file_selector_a.set_previewing_file(file_path)

        # 更新文件存储池中的卡片预览态
        if hasattr(self, 'file_staging_pool') and self.file_staging_pool:
            debug(f"[Main] Calling file_staging_pool.set_previewing_file: {file_path}")
            self.file_staging_pool.set_previewing_file(file_path)

    def handle_preview_cleared(self):
        """
        处理预览清除事件，清除所有卡片的预览态
        """
        # 清除文件选择器中的卡片预览态
        if hasattr(self, 'file_selector_a') and self.file_selector_a:
            self.file_selector_a.clear_previewing_state()
            self.file_selector_a.previewing_file_path = None

        # 清除文件存储池中的卡片预览态
        if hasattr(self, 'file_staging_pool') and self.file_staging_pool:
            self.file_staging_pool.clear_previewing_state()
            self.file_staging_pool.previewing_file_path = None

    def check_and_restore_backup(self):
        """
        检查是否存在备份文件，并根据设置决定是否自动恢复或询问用户
        注意：只恢复文件存储池，文件选择器的状态由其他模块处理
        """
        from freeassetfilter.widgets.D_widgets import CustomMessageBox
        import json

        backup_file = os.path.join(get_app_data_path(), 'staging_pool_backup.json')

        if not os.path.exists(backup_file):
            return

        try:
            with open(backup_file, 'r', encoding='utf-8') as f:
                backup_data = json.load(f)
        except (OSError, IOError, ValueError, TypeError) as e:
            warning(f"读取备份文件失败: {e}")
            return

        items = backup_data.get('items', []) if isinstance(backup_data, dict) else backup_data

        if not items:
            return

        auto_restore = True
        app = QApplication.instance()
        if hasattr(app, 'settings_manager'):
            auto_restore = app.settings_manager.get_setting("file_staging.auto_restore_records", True)

        if auto_restore:
            self.start_restore_backup(backup_data)
        else:
            confirm_msg = CustomMessageBox(self)
            confirm_msg.set_title("恢复上次选中内容")
            confirm_msg.set_text(f"检测到上次有 {len(items)} 个文件在文件存储池中，是否恢复？")
            confirm_msg.set_buttons(["是", "否"], Qt.Horizontal, ["primary", "normal"])

            is_confirmed = False

            def on_confirm_clicked(button_index):
                nonlocal is_confirmed
                is_confirmed = (button_index == 0)
                confirm_msg.close()

            confirm_msg.buttonClicked.connect(on_confirm_clicked)
            confirm_msg.exec()

            if is_confirmed:
                self.start_restore_backup(backup_data)

    def start_restore_backup(self, backup_data):
        """
        启动分批异步恢复，避免主线程长时间阻塞

        Args:
            backup_data (dict or list): 备份数据
        """
        items = backup_data.get('items', []) if isinstance(backup_data, dict) else backup_data
        if not items:
            return

        self._pending_restore_items = list(items)
        self._pending_restore_unlinked_files = []
        self._restore_total_count = len(items)
        self._restore_success_count = 0

        if hasattr(self, 'file_staging_pool'):
            setattr(self.file_staging_pool, "_suspend_backup_save", True)

        QTimer.singleShot(0, self._process_restore_batch)

    def _process_restore_batch(self):
        """
        分批恢复备份项，每批处理少量数据，将控制权交还事件循环
        """
        if not hasattr(self, 'file_staging_pool'):
            return

        batch = self._pending_restore_items[:self._restore_batch_size]
        self._pending_restore_items = self._pending_restore_items[self._restore_batch_size:]

        for file_info in batch:
            try:
                file_path = file_info.get("path", "")
                if file_path and os.path.exists(file_path):
                    self.file_staging_pool.add_file(file_info)
                    self._restore_success_count += 1
                else:
                    self._pending_restore_unlinked_files.append({
                        "original_file_info": file_info,
                        "status": "unlinked",
                        "new_path": None,
                        "md5": None
                    })
            except Exception as e:
                warning(f"恢复备份项失败: {e}")

        processed_count = self._restore_total_count - len(self._pending_restore_items)

        if self._pending_restore_items:
            QTimer.singleShot(0, self._process_restore_batch)
        else:
            self._finish_restore_backup()

    def _finish_restore_backup(self):
        """
        完成恢复流程，统一保存备份并处理未链接文件
        """
        if hasattr(self, 'file_staging_pool'):
            setattr(self.file_staging_pool, "_suspend_backup_save", False)
            try:
                last_path = getattr(getattr(self, 'file_selector_a', None), 'current_path', 'All')
                self.file_staging_pool.save_backup(last_path)
            except Exception as e:
                warning(f"恢复完成后统一保存备份失败: {e}")



        if self._pending_restore_unlinked_files:
            QTimer.singleShot(
                0,
                lambda: self.file_staging_pool.show_unlinked_files_dialog(self._pending_restore_unlinked_files)
            )

    def restore_backup(self, backup_data):
        """
        兼容旧调用入口：改为使用新的分批恢复流程

        Args:
            backup_data (dict or list): 备份数据
        """
        self.start_restore_backup(backup_data)


def _parse_internal_worker_args(argv):
    """
    解析内部子进程参数

    Returns:
        tuple[str | None, dict]:
            (worker_type, worker_payload)
    """
    if len(argv) >= 5 and argv[1] == "--faf-thumbnail-worker":
        return "thumbnail", {
            "file_path": argv[2],
            "dpi_scale": argv[3],
            "prefer_native": argv[4],
        }

    if len(argv) >= 5 and argv[1] == "--faf-run-installer":
        return "run-installer", {
            "installer_path": argv[2],
            "expected_sha256": argv[3],
            "parent_pid": argv[4],
        }

    return None, {}


def _wait_for_process_exit(pid, timeout_seconds=30):
    """
    等待指定进程退出
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return

    deadline = time.time() + max(1, timeout_seconds)
    while time.time() < deadline:
        if not _is_process_running(pid):
            return
        time.sleep(0.3)

    time.sleep(1.0)


def _run_installer_after_parent_exit(installer_path, expected_sha256, parent_pid):
    """
    内部 helper：
    - 等待主程序退出
    - 再次校验安装包
    - 拉起安装程序
    """
    from freeassetfilter.core.update_manager import verify_installer_file

    if not installer_path or not expected_sha256:
        error("[安装 helper] 缺少安装包路径或 SHA256")
        return 1

    installer_path = os.path.abspath(installer_path)
    if not os.path.exists(installer_path):
        error(f"[安装 helper] 安装包不存在: {installer_path}")
        return 1

    _wait_for_process_exit(parent_pid, timeout_seconds=30)

    if not verify_installer_file(installer_path, expected_sha256):
        error(f"[安装 helper] 安装包校验失败: {installer_path}")
        return 1

    try:
        if sys.platform == "win32" and hasattr(os, "startfile"):
            os.startfile(installer_path)
        else:
            subprocess.Popen(
                [installer_path],
                close_fds=True,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
        info(f"[安装 helper] 已启动安装包: {installer_path}")
        return 0
    except Exception as first_error:
        try:
            subprocess.Popen(
                [installer_path],
                close_fds=True,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
            info(f"[安装 helper] 已通过回退方式启动安装包: {installer_path}")
            return 0
        except Exception as second_error:
            error(f"[安装 helper] 启动安装包失败: {first_error}; 回退失败: {second_error}")
            return 1


def _extract_associated_file_path(argv):
    """
    提取文件关联传入的文件路径，忽略内部工作进程参数
    """
    if len(argv) <= 1:
        return None

    candidate = argv[1]
    if isinstance(candidate, str) and candidate.startswith("--faf-"):
        return None

    return candidate


def _get_runtime_info_file_path():
    """
    获取运行实例信息文件路径
    """
    return os.path.join(get_app_data_path(), "runtime_instance.json")


def _write_runtime_instance_info():
    """
    写入当前运行实例信息，供单实例冲突时定位残留进程
    """
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


def _remove_runtime_instance_info(expected_pid=None):
    """
    删除运行实例信息文件

    Args:
        expected_pid (int | None): 仅当文件中的 pid 与该值一致时才删除，避免误删其他实例信息
    """
    runtime_file = _get_runtime_info_file_path()
    if not os.path.exists(runtime_file):
        return

    try:
        if expected_pid is not None:
            with open(runtime_file, "r", encoding="utf-8") as f:
                runtime_info = json.load(f)
            file_pid = runtime_info.get("pid")
            if file_pid != expected_pid:
                return
    except (OSError, IOError, ValueError, TypeError):
        if expected_pid is not None:
            return

    try:
        os.remove(runtime_file)
    except (OSError, IOError, PermissionError, FileNotFoundError):
        pass


def _read_runtime_instance_info():
    """
    读取运行实例信息
    """
    runtime_file = _get_runtime_info_file_path()
    if not os.path.exists(runtime_file):
        return None

    with open(runtime_file, "r", encoding="utf-8") as f:
        runtime_info = json.load(f)

    if not isinstance(runtime_info, dict):
        return None

    return runtime_info


def _is_process_running(pid):
    """
    判断指定 PID 是否仍在运行
    """
    if not isinstance(pid, int) or pid <= 0:
        return False

    if sys.platform != "win32":
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


def _get_process_image_path(pid):
    """
    获取进程可执行文件路径
    """
    if not isinstance(pid, int) or pid <= 0:
        return None

    if sys.platform != "win32":
        return None

    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
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
        success = kernel32.QueryFullProcessImageNameW(
            process_handle,
            0,
            buffer,
            ctypes.byref(buffer_length)
        )
        if not success:
            return None
        return os.path.normcase(os.path.normpath(buffer.value))
    finally:
        kernel32.CloseHandle(process_handle)


def _is_expected_app_process(pid, runtime_info):
    """
    保守校验 PID 是否指向 FreeAssetFilter 主程序自身
    """
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


def _terminate_process(pid):
    """
    强制终止指定进程
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


def _restart_current_application():
    """
    使用当前启动参数重新启动应用程序
    """
    relaunch_args = [sys.executable] + list(sys.argv[1:])
    subprocess.Popen(
        relaunch_args,
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )


def _show_already_running_dialog_and_handle_restart(mutex_handle):
    """
    显示“程序已在运行”弹窗，并在需要时执行强制终止后重启
    """
    from PySide6.QtWidgets import QApplication as _QApplication, QMessageBox

    _temp_app = _QApplication(sys.argv)
    msg_box = QMessageBox()
    msg_box.setWindowTitle("FreeAssetFilter")
    msg_box.setIcon(QMessageBox.Warning)
    msg_box.setText("程序已经在运行中")
    msg_box.setInformativeText(
        "FreeAssetFilter 已经在运行，不能启动多个实例。\n\n"
        "仅当你已经确认程序窗口已关闭，但这里仍然反复提示程序正在运行时，"
        "才点击“强制终止后重新启动”。\n"
        "该操作会强制结束残留后台进程，未保存内容可能丢失。"
    )
    ok_button = msg_box.addButton("确定", QMessageBox.AcceptRole)
    force_restart_button = msg_box.addButton("强制终止后重新启动", QMessageBox.DestructiveRole)
    msg_box.setDefaultButton(ok_button)
    msg_box.exec()

    clicked_button = msg_box.clickedButton()
    if clicked_button is not force_restart_button:
        return

    try:
        runtime_info = _read_runtime_instance_info()
    except (OSError, IOError, ValueError, TypeError) as e:
        error_box = QMessageBox()
        error_box.setWindowTitle("强制终止失败")
        error_box.setIcon(QMessageBox.Critical)
        error_box.setText("无法读取正在运行实例的信息")
        error_box.setInformativeText(
            f"读取运行实例信息失败：{e}\n\n"
            "仅当你已经确认程序窗口已关闭，但仍然反复弹出本提示时，才应尝试此操作。"
        )
        error_box.exec()
        return

    if not runtime_info:
        error_box = QMessageBox()
        error_box.setWindowTitle("强制终止失败")
        error_box.setIcon(QMessageBox.Critical)
        error_box.setText("未找到可供终止的运行实例信息")
        error_box.setInformativeText(
            "没有找到残留实例记录，无法安全执行强制终止。\n\n"
            "仅当你已经确认程序窗口已关闭，但仍然反复弹出本提示时，才应尝试此操作。"
        )
        error_box.exec()
        return

    target_pid = runtime_info.get("pid")
    if not isinstance(target_pid, int) or target_pid <= 0:
        error_box = QMessageBox()
        error_box.setWindowTitle("强制终止失败")
        error_box.setIcon(QMessageBox.Critical)
        error_box.setText("运行实例信息中的 PID 无效")
        error_box.setInformativeText("为避免误杀其他进程，已取消本次强制终止。")
        error_box.exec()
        return

    if not _is_process_running(target_pid):
        _remove_runtime_instance_info(expected_pid=target_pid)

        error_box = QMessageBox()
        error_box.setWindowTitle("未发现残留进程")
        error_box.setIcon(QMessageBox.Information)
        error_box.setText("记录中的运行实例已经不存在")
        error_box.setInformativeText(
            "程序残留记录已清理，请重新启动程序。\n\n"
            "仅当你已经确认程序窗口已关闭，但仍然反复弹出本提示时，才应点击该按钮。"
        )
        error_box.exec()
        return

    if not _is_expected_app_process(target_pid, runtime_info):
        error_box = QMessageBox()
        error_box.setWindowTitle("强制终止失败")
        error_box.setIcon(QMessageBox.Critical)
        error_box.setText("检测到的目标进程与当前程序不匹配")
        error_box.setInformativeText("为避免误杀其他进程，已取消本次强制终止。")
        error_box.exec()
        return

    terminated, terminate_message = _terminate_process(target_pid)
    if not terminated:
        error_box = QMessageBox()
        error_box.setWindowTitle("强制终止失败")
        error_box.setIcon(QMessageBox.Critical)
        error_box.setText("无法强制结束残留进程")
        error_box.setInformativeText(terminate_message)
        error_box.exec()
        return

    _remove_runtime_instance_info(expected_pid=target_pid)

    if sys.platform == "win32" and mutex_handle:
        try:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(mutex_handle)
        except Exception:
            pass

    try:
        _restart_current_application()
    except Exception as e:
        error_box = QMessageBox()
        error_box.setWindowTitle("重新启动失败")
        error_box.setIcon(QMessageBox.Critical)
        error_box.setText("残留进程已被强制结束，但重新启动失败")
        error_box.setInformativeText(str(e))
        error_box.exec()
        return

    _temp_app.quit()
    sys.exit(0)


def main():
    """
    主程序入口函数
    """
    info("=== FreeAssetFilter 主程序 ===")

    # 内部缩略图子进程模式：
    # - 必须在单实例检测之前分流
    # - 避免打包态通过 sys.executable 再次拉起主程序时触发“多实例运行”弹窗
    worker_type, worker_payload = _parse_internal_worker_args(sys.argv)
    if worker_type == "thumbnail":
        try:
            from freeassetfilter.core.thumbnail_manager import _run_batch_video_thumbnail_subprocess

            file_path = worker_payload.get("file_path", "")
            dpi_scale = float(worker_payload.get("dpi_scale", 1.0))
            prefer_native_raw = str(worker_payload.get("prefer_native", "1")).lower()
            prefer_native = prefer_native_raw in ("1", "true", "yes", "on")

            exit_code = _run_batch_video_thumbnail_subprocess(
                file_path,
                dpi_scale,
                prefer_native,
            )
            sys.exit(exit_code)
        except Exception as e:
            error(f"[内部缩略图子进程] 执行失败: {e}")
            sys.exit(1)

    if worker_type == "run-installer":
        try:
            exit_code = _run_installer_after_parent_exit(
                worker_payload.get("installer_path", ""),
                worker_payload.get("expected_sha256", ""),
                worker_payload.get("parent_pid", "0"),
            )
            sys.exit(exit_code)
        except Exception as e:
            error(f"[内部安装 helper] 执行失败: {e}")
            sys.exit(1)

    # 单实例检测 - 使用Windows互斥锁确保只有一个程序实例运行
    # 防止多个实例同时运行导致JSON文件存取异常
    _mutex_handle = None
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes

        # 创建命名互斥锁
        mutex_name = "FreeAssetFilter_SingleInstance_Mutex"
        kernel32 = ctypes.windll.kernel32

        # CreateMutexW 参数类型设置
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE

        # 尝试创建互斥锁
        _mutex_handle = kernel32.CreateMutexW(None, False, mutex_name)

        if _mutex_handle:
            # 检查错误码，ERROR_ALREADY_EXISTS = 183
            error_code = kernel32.GetLastError()
            if error_code == 183:  # ERROR_ALREADY_EXISTS
                warning("程序已经在运行中，禁止启动多个实例")
                try:
                    _show_already_running_dialog_and_handle_restart(_mutex_handle)
                except Exception as e:
                    warning(f"显示多实例提示弹窗失败: {e}")
                finally:
                    if _mutex_handle:
                        try:
                            kernel32.CloseHandle(_mutex_handle)
                        except Exception:
                            pass
                sys.exit(0)
            else:
                info("单实例检测通过，程序启动")

    try:
        _write_runtime_instance_info()
    except (OSError, IOError, PermissionError, FileNotFoundError, ValueError, TypeError) as e:
        warning(f"写入运行实例信息失败: {e}")

    # 获取通过文件关联传递进来的文件路径（Inno Setup通过命令行参数传递）
    # 忽略内部工作进程参数，避免将内部参数误识别为文件路径
    associated_file_path = _extract_associated_file_path(sys.argv)
    if associated_file_path:
        info(f"[文件关联] 接收到关联文件: {associated_file_path}")

    # 修改sys.argv[0]以确保Windows任务栏显示正确图标
    sys.argv[0] = os.path.abspath(__file__)

    # 在Windows系统上设置应用程序身份，确保任务栏显示正确图标
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FreeAssetFilter.App")

        # 设置DPI感知级别
        try:
            user32 = ctypes.windll.user32
            SetProcessDpiAwarenessContext = user32.SetProcessDpiAwarenessContext
            SetProcessDpiAwarenessContext.restype = ctypes.c_void_p
            SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = 0x3
            result = SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
            if result == 0:
                shcore = ctypes.windll.shcore
                SetProcessDpiAwareness = shcore.SetProcessDpiAwareness
                SetProcessDpiAwareness.restype = ctypes.c_long
                SetProcessDpiAwareness.argtypes = [ctypes.c_int]
                PROCESS_PER_MONITOR_DPI_AWARE = 2
                SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
                logger.debug("设置为每显示器DPI感知模式")
            else:
                logger.debug("设置为每显示器DPI感知v2模式")
        except (AttributeError, OSError) as e:
            try:
                user32 = ctypes.windll.user32
                SetProcessDPIAware = user32.SetProcessDPIAware
                SetProcessDPIAware.restype = ctypes.c_bool
                SetProcessDPIAware()
                logger.debug("设置为系统DPI感知模式")
            except (AttributeError, OSError) as e2:
                logger.debug(f"设置DPI感知失败: {e2}")

    app = QApplication(sys.argv)

    # 将关联文件路径存储到app对象，供其他组件访问
    app.associated_file_path = associated_file_path

    # 设置全局DPI缩放因子为系统缩放的1.4倍
    from PySide6.QtGui import QCursor, QFontDatabase, QFont
    cursor_pos = QCursor.pos()
    screen = QApplication.screenAt(cursor_pos)
    if screen is None:
        screen = QApplication.primaryScreen()
    logical_dpi = screen.logicalDotsPerInch()
    physical_dpi = screen.physicalDotsPerInch()
    system_scale = physical_dpi / logical_dpi if logical_dpi > 0 else 1.0
    app.dpi_scale_factor = system_scale * 1.4

    # 设置应用程序图标，用于任务栏显示
    icon_path = get_resource_path('freeassetfilter/icons/FAF-main.ico')
    app.setWindowIcon(QIcon(icon_path))

    # 导入设置管理器
    from freeassetfilter.core.settings_manager import SettingsManager

    # 检测并设置全局字体
    font_families = QFontDatabase.families()

    # 加载 FiraCode-VF 字体（用于代码高亮显示）
    firacode_font_path = get_resource_path('freeassetfilter/icons/FiraCode-VF.ttf')
    firacode_font_family = None
    if os.path.exists(firacode_font_path):
        font_id = QFontDatabase.addApplicationFont(firacode_font_path)
        if font_id != -1:
            firacode_font_family = QFontDatabase.applicationFontFamilies(font_id)[0]

    # 初始化设置管理器
    settings_manager = SettingsManager()

    # 从设置管理器中获取字体设置
    DEFAULT_FONT_SIZE = settings_manager.get_setting("font.size", 10)
    saved_font_style = settings_manager.get_setting("font.style", "Microsoft YaHei")

    # 检查保存的字体是否可用，如果不可用则回退到微软雅黑
    selected_font = saved_font_style
    if selected_font not in font_families:
        yahei_fonts = ["Microsoft YaHei", "Microsoft YaHei UI"]
        for font_name in yahei_fonts:
            if font_name in font_families:
                selected_font = font_name
                break

        if selected_font not in font_families:
            selected_font = None

    if selected_font:
        app.setFont(QFont(selected_font, DEFAULT_FONT_SIZE, QFont.Normal))
        global_font = QFont(selected_font, DEFAULT_FONT_SIZE, QFont.Normal)
    else:
        global_font = QFont()
        global_font.setPointSize(DEFAULT_FONT_SIZE)
        global_font.setWeight(QFont.Normal)

    # 将默认字体大小存储到app对象中，方便其他组件访问
    app.default_font_size = DEFAULT_FONT_SIZE

    # 将设置管理器存储到app对象中，方便其他组件访问
    app.settings_manager = settings_manager

    # 将全局字体存储到app对象中，方便其他组件访问
    app.global_font = global_font

    # 将 FiraCode 字体族名存储到app对象中，供代码高亮模式使用
    app.firacode_font_family = firacode_font_family

    # 根据当前主题动态设置全局滚动条样式
    theme = settings_manager.get_setting("appearance.theme", "default")
    if theme == "dark":
        scroll_area_bg = "#2D2D2D"
        scrollbar_bg = "#3C3C3C"
        scrollbar_handle = "#555555"
        scrollbar_handle_hover = "#666666"
    else:
        scroll_area_bg = "#ffffff"
        scrollbar_bg = "#f0f0f0"
        scrollbar_handle = "#c0c0c0"
        scrollbar_handle_hover = "#a0a0a0"

    scrollbar_style = """
        /* 滚动区域样式 */
        QScrollArea {
            background-color: %s;
            border: none;
        }

        /* 垂直滚动条样式 */
        QScrollBar:vertical {
            width: 8px;
            background: %s;
            border-radius: 3px;
        }

        QScrollBar::handle:vertical {
            background: %s;
            border-radius: 3px;
        }

        QScrollBar::handle:vertical:hover {
            background: %s;
        }

        QScrollBar::sub-line:vertical,
        QScrollBar::add-line:vertical {
            height: 0px;
        }

        /* 水平滚动条样式 */
        QScrollBar:horizontal {
            height: 8px;
            background: %s;
            border-radius: 3px;
        }

        QScrollBar::handle:horizontal {
            background: %s;
            border-radius: 3px;
        }

        QScrollBar::handle:horizontal:hover {
            background: %s;
        }

        QScrollBar::sub-line:horizontal,
        QScrollBar::add-line:horizontal {
            width: 0px;
        }
    """ % (scroll_area_bg, scrollbar_bg, scrollbar_handle, scrollbar_handle_hover,
           scrollbar_bg, scrollbar_handle, scrollbar_handle_hover)

    app.setStyleSheet(scrollbar_style)

    window = FreeAssetFilterApp()
    # 应用主题设置
    window.update_theme()
    # 窗口启动时窗口化显示
    window.show()
    # 首屏显示后再分阶段执行恢复/预热/清理，避免阻塞启动
    window.schedule_startup_tasks()

    # 应用程序退出前记录当前时间
    def on_app_exit():
        exit_time = time.time()
        settings_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'settings.json')

        try:
            if os.path.exists(settings_file):
                with open(settings_file, 'r', encoding='utf-8') as f:
                    settings_data = json.load(f)

                if 'app' not in settings_data:
                    settings_data['app'] = {}

                settings_data['app']['last_exit_time'] = exit_time

                with open(settings_file, 'w', encoding='utf-8') as f:
                    json.dump(settings_data, f, indent=4, ensure_ascii=False)
            else:
                settings_manager.set_setting("app.last_exit_time", exit_time)

        except (OSError, PermissionError, json.JSONDecodeError, TypeError) as e:
            settings_manager.set_setting("app.last_exit_time", exit_time)
            logger.warning(f"保存退出时间失败: {e}")

        try:
            _remove_runtime_instance_info(expected_pid=os.getpid())
        except Exception as e:
            logger.warning(f"清理运行实例信息失败: {e}")

        if sys.platform == 'win32' and _mutex_handle:
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(_mutex_handle)
            except Exception as e:
                logger.debug(f"关闭单实例互斥锁句柄失败: {e}")

    # 连接应用程序退出信号
    app.aboutToQuit.connect(on_app_exit)

    sys.exit(app.exec())


# 主程序入口
if __name__ == "__main__":
    main()
