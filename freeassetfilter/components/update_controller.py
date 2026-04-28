#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 更新控制器
负责：
- 检查 GitHub Releases
- 比较本地版本与发布日期
- 复用或下载最新安装包
- 校验 SHA256
- 引导用户安装
"""

import os
import sys
import time
import subprocess
from urllib import request, error as urllib_error

from PySide6.QtCore import QObject, Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QScrollArea, QSizePolicy, QTextBrowser
from PySide6.QtGui import QFont

from freeassetfilter.core.update_manager import (
    UpdateCancelled,
    UpdateError,
    build_request_headers,
    check_for_updates,
    prepare_cached_installer,
    get_cache_dir,
    get_cache_metadata_path,
    verify_installer_file,
)
from freeassetfilter.utils.app_logger import info, warning, error, debug
from freeassetfilter.widgets.message_box import CustomMessageBox
from freeassetfilter.widgets.progress_widgets import D_ProgressBar
from freeassetfilter.widgets.loading_widget import LoadingSpinner
from freeassetfilter.widgets.smooth_scroller import D_ScrollBar, SmoothScroller


class UpdateCheckWorker(QThread):
    """
    后台检查更新线程
    """

    success = Signal(dict)
    failure = Signal(str)
    cancelled = Signal()

    def run(self):
        debug("UpdateCheckWorker: 开始检查更新")
        try:
            if self.isInterruptionRequested():
                debug("UpdateCheckWorker: 在开始前已被中断")
                self.cancelled.emit()
                return

            result = check_for_updates(cancel_check=self.isInterruptionRequested)

            if self.isInterruptionRequested():
                debug("UpdateCheckWorker: 检查完成后已被中断，忽略结果")
                self.cancelled.emit()
                return

            debug("UpdateCheckWorker: 检查更新成功")
            self.success.emit(result)
        except UpdateCancelled:
            debug("UpdateCheckWorker: 检查更新已取消")
            self.cancelled.emit()
        except UpdateError as e:
            warning(f"检查更新失败: {e}")
            self.failure.emit(str(e))
        except Exception as e:
            error(f"检查更新失败: {e}")
            self.failure.emit(f"检查更新失败：{e}")


class SilentUpdateCheckWorker(QThread):
    """
    启动时静默检查更新线程
    - 不影响任何用户操作
    - 如果有更新，通过信号通知主线程显示提示
    - 如果是最新版本，静默结束
    """
    
    update_available = Signal(dict)
    success = Signal(dict)
    failure = Signal(str)
    cancelled = Signal()
    check_finished = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SilentUpdateCheckWorker")
    
    def run(self):
        debug("SilentUpdateCheckWorker: 开始静默检查更新")
        try:
            if self.isInterruptionRequested():
                debug("SilentUpdateCheckWorker: 在开始前已被中断")
                self.check_finished.emit()
                return
            
            result = check_for_updates(cancel_check=self.isInterruptionRequested)
            
            if self.isInterruptionRequested():
                debug("SilentUpdateCheckWorker: 检查完成后已被中断，忽略结果")
                self.cancelled.emit()
                self.check_finished.emit()
                return
            
            debug("SilentUpdateCheckWorker: 静默检查完成")
            self.success.emit(result)
            
            if result.get("update_available", False):
                debug("SilentUpdateCheckWorker: 发现新版本")
                self.update_available.emit(result)
            
            self.check_finished.emit()
        except UpdateError as e:
            if self.isInterruptionRequested():
                debug("SilentUpdateCheckWorker: 静默检查已中断")
                self.cancelled.emit()
            else:
                debug(f"SilentUpdateCheckWorker: 静默检查失败: {e}")
                self.failure.emit(str(e))
            self.check_finished.emit()
        except Exception as e:
            if self.isInterruptionRequested():
                debug("SilentUpdateCheckWorker: 静默检查已中断")
                self.cancelled.emit()
            else:
                debug(f"SilentUpdateCheckWorker: 静默检查异常: {e}")
                self.failure.emit(f"检查更新失败：{e}")
            self.check_finished.emit()


class UpdateDownloadWorker(QThread):
    """
    后台下载更新线程
    """

    progress_changed = Signal(int, int, str)
    success = Signal(dict)
    failure = Signal(str)
    cancelled = Signal()

    def __init__(self, release_info, parent=None):
        super().__init__(parent)
        self.release_info = release_info
        self._cancel_requested = False

    def cancel(self):
        debug("UpdateDownloadWorker: 收到取消请求")
        self._cancel_requested = True

    def run(self):
        temp_path = None
        debug("UpdateDownloadWorker: 开始下载更新")
        try:
            os.makedirs(get_cache_dir(), exist_ok=True)

            installer_name = self.release_info["installer_name"]
            final_path = os.path.join(get_cache_dir(), installer_name)
            temp_path = f"{final_path}.download"
            debug(f"UpdateDownloadWorker: 下载目标路径: {final_path}")

            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

            headers = build_request_headers("application/octet-stream")

            req = request.Request(
                self.release_info["installer_download_url"],
                headers=headers,
                method="GET",
            )

            with request.urlopen(req, timeout=60) as response:
                total_size = int(response.headers.get("content-length", 0))
                if total_size <= 0:
                    total_size = int(self.release_info.get("installer_size", 0) or 0)
                downloaded_size = 0
                debug(f"UpdateDownloadWorker: 文件总大小: {total_size} bytes")

                with open(temp_path, "wb") as f:
                    while True:
                        if self._cancel_requested:
                            debug("UpdateDownloadWorker: 下载已取消，清理临时文件")
                            try:
                                f.close()
                            except Exception:
                                pass
                            try:
                                if temp_path and os.path.exists(temp_path):
                                    os.remove(temp_path)
                            except OSError:
                                pass
                            self.cancelled.emit()
                            return

                        chunk = response.read(1024 * 128)
                        if not chunk:
                            break

                        f.write(chunk)
                        f.flush()
                        downloaded_size += len(chunk)
                        self.progress_changed.emit(
                            downloaded_size,
                            total_size,
                            f"正在下载更新… {self._format_progress_text(downloaded_size, total_size)}",
                        )

            try:
                os.replace(temp_path, final_path)
                debug(f"UpdateDownloadWorker: 临时文件重命名成功: {final_path}")
            except OSError as e:
                raise UpdateError(f"写入安装包失败：{e}") from e

            is_valid = verify_installer_file(final_path, self.release_info["installer_sha256"])
            if not is_valid:
                warning("UpdateDownloadWorker: SHA256 校验失败")
                try:
                    os.remove(final_path)
                except OSError:
                    pass
                raise UpdateError("下载完成，但 SHA256 校验失败")

            debug("UpdateDownloadWorker: SHA256 校验通过")
            cache_result = prepare_cached_installer(self.release_info, final_path)
            info("UpdateDownloadWorker: 更新下载完成")
            self.success.emit(cache_result)
        except UpdateError as e:
            warning(f"UpdateDownloadWorker: 下载失败: {e}")
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            self.failure.emit(str(e))
        except (urllib_error.URLError, OSError) as e:
            error(f"UpdateDownloadWorker: 网络或文件错误: {e}")
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            self.failure.emit(f"下载更新失败：{e}")
        except Exception as e:
            error(f"UpdateDownloadWorker: 下载异常: {e}")
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            self.failure.emit(f"下载更新失败：{e}")

    @staticmethod
    def _format_progress_text(downloaded_size, total_size):
        if total_size > 0:
            progress = int(downloaded_size * 100 / total_size)
            return (
                f"{progress}% "
                f"({UpdateDownloadWorker._format_size(downloaded_size)} / "
                f"{UpdateDownloadWorker._format_size(total_size)})"
            )
        return f"{UpdateDownloadWorker._format_size(downloaded_size)}"

    @staticmethod
    def _format_size(size):
        units = ["B", "KB", "MB", "GB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.2f} {unit}"
            value /= 1024.0
        return f"{size} B"


class UpdateController(QObject):
    """
    更新控制器
    """

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.update_button = None

        self._check_worker = None
        self._download_worker = None
        self._current_dialog = None
        self._current_progress_bar = None
        self._current_progress_info_label = None
        self._current_loading_spinner = None
        self._current_release_info = None
        self._current_ready_package = None
        self._check_cancelled = False
        self._pending_check_restart = False
        self._current_download_total_size = 0
        self._download_progress_timer = QTimer(self)
        self._download_progress_timer.setInterval(1000)
        self._download_progress_timer.timeout.connect(self._poll_download_progress_from_file)
        self._current_download_temp_path = None
        self._current_download_final_path = None
        self._latest_downloaded_size = 0
        self._last_speed_check_time = None
        self._last_speed_check_size = 0
        self._current_download_speed_text = "0 B/s"
        
        # 静默检查更新相关状态
        self._silent_check_worker = None
        self._silent_check_cancelled = False
        self._manual_check_uses_silent = False
        self._silent_check_claimed_by_manual = False
        self._retired_check_workers = []
        self._retired_silent_workers = []

    def start_silent_update_check(self):
        """
        启动静默更新检查（程序启动时调用）
        """
        if self._silent_check_worker and self._silent_check_worker.isRunning():
            debug("UpdateController: 静默检查已在进行中，忽略重复请求")
            return
        
        if self._check_worker and self._check_worker.isRunning():
            debug("UpdateController: 手动检查更新正在进行，跳过静默检查")
            return
            
        self._silent_check_cancelled = False
        self._manual_check_uses_silent = False
        self._silent_check_claimed_by_manual = False
        self._silent_check_worker = SilentUpdateCheckWorker(self)
        self._silent_check_worker.update_available.connect(self._on_silent_check_update_available)
        self._silent_check_worker.success.connect(self._on_silent_check_success)
        self._silent_check_worker.failure.connect(self._on_silent_check_failure)
        self._silent_check_worker.cancelled.connect(self._on_silent_check_cancelled)
        self._silent_check_worker.check_finished.connect(self._on_silent_check_finished)
        self._silent_check_worker.start()
        debug("UpdateController: 静默更新检查已启动")

    def cancel_silent_check(self, retire=False):
        """
        取消静默检查（例如用户手动触发检查更新时）
        retire=True 用于交互取消，不在主线程等待网络请求结束；
        默认路径不等待线程（因 HTTP 请求无法被中断），直接退休避免阻塞关闭流程。
        """
        if self._silent_check_worker and self._silent_check_worker.isRunning():
            debug("UpdateController: 取消静默检查")
            self._silent_check_cancelled = True
            self._manual_check_uses_silent = False
            self._silent_check_claimed_by_manual = False
            if retire:
                self._retire_silent_worker(self._silent_check_worker)
                self._silent_check_worker = None
            else:
                self._silent_check_worker.requestInterruption()
                # 不等待线程结束：HTTP 请求是同步阻塞的，无法被中断
                # 直接退休线程，保留引用直到完成信号触发，避免阻塞关闭流程
                self._retire_silent_worker(self._silent_check_worker)
                # 断开 Qt 父子关系，防止 QThread 对象随父窗口销毁时触发 "Destroyed while thread is still running"
                try:
                    self._silent_check_worker.setParent(None)
                except Exception:
                    pass
                self._silent_check_worker = None
        elif self._silent_check_worker:
            debug("UpdateController: 取消静默检查 - worker 存在但已不在运行")

    def bind_button(self, button):
        """
        绑定更新按钮
        """
        if self.update_button is button:
            return

        if self.update_button is not None:
            try:
                self.update_button.clicked.disconnect(self.on_check_updates_clicked)
            except Exception:
                pass

        self.update_button = button
        if self.update_button is not None:
            self.update_button.clicked.connect(self.on_check_updates_clicked)
            debug("UpdateController: 更新按钮绑定成功")

    def _retire_worker(self, worker, retired_workers):
        """
        请求后台检查线程停止，并保留引用直到线程结束，避免 UI 等待。
        """
        if worker is None:
            return

        try:
            worker.requestInterruption()
        except Exception:
            pass

        if worker not in retired_workers:
            retired_workers.append(worker)

        try:
            worker.finished.connect(lambda w=worker, workers=retired_workers: self._forget_retired_worker(w, workers))
        except Exception:
            pass

    def _retire_check_worker(self, worker):
        self._retire_worker(worker, self._retired_check_workers)

    def _retire_silent_worker(self, worker):
        """
        退休静默检查工作线程，断开 Qt 父子关系防止销毁时触发警告
        """
        try:
            worker.setParent(None)
        except Exception:
            pass
        self._retire_worker(worker, self._retired_silent_workers)

    def _forget_retired_worker(self, worker, retired_workers):
        try:
            retired_workers.remove(worker)
        except ValueError:
            pass

    def on_check_updates_clicked(self):
        """
        点击"检查更新"
        """
        debug("UpdateController: 用户点击检查更新")

        if self._silent_check_worker and self._silent_check_worker.isRunning():
            debug("UpdateController: 手动检查接管正在运行的静默检查")
            self._start_manual_check_from_silent()
            return
        
        if self._check_worker and self._check_worker.isRunning():
            if self._check_cancelled or self._check_worker.isInterruptionRequested():
                debug("UpdateController: 当前检查正在取消中，记录重新检查请求")
                self._pending_check_restart = True
                self._set_dialog_text("正在取消当前检查，随后将重新检查更新…")
                self._set_dialog_buttons([])
                self._check_worker.requestInterruption()
            else:
                debug("UpdateController: 检查更新已在进行中，忽略重复请求")
            return

        if self._download_worker and self._download_worker.isRunning():
            debug("UpdateController: 下载更新已在进行中，忽略检查请求")
            return

        self._start_manual_check()

    def _show_check_progress_dialog(self):
        self._show_progress_dialog(
            title="检查更新",
            text="正在检查更新…",
            progress_min=0,
            progress_max=0,
            progress_value=0,
            buttons=["取消检查"],
            button_types=["normal"],
            callback=self._on_check_dialog_clicked,
            allow_close=False,
        )

    def _start_manual_check_from_silent(self):
        self._current_release_info = None
        self._current_ready_package = None
        self._check_cancelled = False
        self._pending_check_restart = False
        self._silent_check_cancelled = False
        self._manual_check_uses_silent = True
        self._silent_check_claimed_by_manual = False
        self._show_check_progress_dialog()

    def _start_manual_check(self):
        self._current_release_info = None
        self._current_ready_package = None
        self._check_cancelled = False
        self._pending_check_restart = False
        self._manual_check_uses_silent = False
        self._silent_check_claimed_by_manual = False
        self._show_check_progress_dialog()

        self._check_worker = UpdateCheckWorker(self)
        self._check_worker.success.connect(self._on_check_success)
        self._check_worker.failure.connect(self._on_check_failure)
        self._check_worker.cancelled.connect(self._on_check_cancelled)
        self._check_worker.start()
        debug("UpdateController: 检查更新任务已启动")

    def _restart_manual_check_if_needed(self):
        if not self._pending_check_restart:
            return

        debug("UpdateController: 当前检查已结束，重新发起检查更新")
        self._pending_check_restart = False
        QTimer.singleShot(0, self._start_manual_check)

    def _on_check_dialog_clicked(self, index):
        if index != 0:
            return

        if self._manual_check_uses_silent and self._silent_check_worker and self._silent_check_worker.isRunning():
            debug("UpdateController: 用户取消已接管的静默检查")
            self._check_cancelled = True
            self._silent_check_cancelled = True
            self._manual_check_uses_silent = False
            self._silent_check_claimed_by_manual = False
            self._retire_silent_worker(self._silent_check_worker)
            self._silent_check_worker = None
            self._close_current_dialog()
            return

        if self._check_worker and self._check_worker.isRunning():
            debug("UpdateController: 用户取消检查更新")
            self._check_cancelled = True
            self._retire_check_worker(self._check_worker)
            self._check_worker = None
            self._close_current_dialog()

    def _on_check_success(self, result):
        sender = self.sender()
        if sender in self._retired_check_workers:
            debug("UpdateController: 忽略已取消检查的成功结果")
            return

        debug("UpdateController: 检查更新成功，处理结果")
        self._check_worker = None

        if self._check_cancelled:
            debug("UpdateController: 检查已被取消，忽略结果")
            self._check_cancelled = False
            self._close_current_dialog()
            self._restart_manual_check_if_needed()
            return

        self._show_check_result(result)

    def _show_check_result(self, result):
        if not result.get("update_available", False):
            local_info = result.get("local_info", {})
            latest_release = result.get("latest_release", {})

            latest_tag = latest_release.get("tag_name") or "未知版本"
            latest_date = latest_release.get("published_date") or "未知日期"
            local_tag = local_info.get("tag_name") or "未知版本"
            local_date = local_info.get("build_date") or "未知日期"

            info(f"当前已是最新版本: {local_tag} ({local_date})")
            self._show_message_dialog(
                title="检查更新",
                text=(
                    "当前已是最新版本。\n\n"
                    f"当前版本：{local_tag}\n"
                    f"构建日期：{local_date}\n"
                    f"最新发布：{latest_tag}\n"
                    f"发布日期：{latest_date}"
                ),
                buttons=["确定"],
                button_types=["primary"],
            )
            return

        release_info = result["latest_release"]
        self._current_release_info = release_info
        info(f"发现新版本: {release_info.get('tag_name', 'unknown')}")

        local_info = result.get("local_info", {})

        cache_result = result.get("cache_result", {})
        installer_path = cache_result.get("installer_path")
        installer_ready = bool(cache_result.get("is_ready")) and bool(installer_path)

        self._current_ready_package = cache_result if installer_ready else None
        if installer_ready:
            debug("UpdateController: 本地已存在可用安装包")

        self._show_update_available_detail_dialog(
            local_info=local_info,
            release_info=release_info,
            installer_ready=installer_ready,
        )

    def _on_check_failure(self, message):
        sender = self.sender()
        if sender in self._retired_check_workers:
            debug("UpdateController: 忽略已取消检查的失败结果")
            return

        warning(f"检查更新失败: {message}")
        self._check_worker = None

        if self._check_cancelled:
            debug("UpdateController: 检查取消后收到失败结果，忽略")
            self._check_cancelled = False
            self._close_current_dialog()
            self._restart_manual_check_if_needed()
            return

        self._show_message_dialog(
            title="检查更新失败",
            text=message,
            buttons=["确定"],
            button_types=["primary"],
        )

    def _on_check_cancelled(self):
        sender = self.sender()
        if sender in self._retired_check_workers:
            debug("UpdateController: 已取消检查线程结束")
            return

        debug("UpdateController: 检查更新已取消")
        self._check_worker = None
        self._check_cancelled = False
        self._close_current_dialog()
        self._restart_manual_check_if_needed()

    def _on_update_available_dialog_clicked(self, index):
        if index != 0 or not self._current_release_info:
            return

        debug("UpdateController: 用户确认下载更新")
        self._current_download_total_size = int(self._current_release_info.get("installer_size", 0) or 0)
        self._latest_downloaded_size = 0
        self._last_speed_check_time = time.time()
        self._last_speed_check_size = 0
        self._current_download_speed_text = "0 B/s"
        installer_name = self._current_release_info.get("installer_name", "")
        if installer_name:
            self._current_download_final_path = os.path.join(get_cache_dir(), installer_name)
            self._current_download_temp_path = f"{self._current_download_final_path}.download"
        else:
            self._current_download_final_path = None
            self._current_download_temp_path = None

        progress_max = self._current_download_total_size if self._current_download_total_size > 0 else 1000

        self._show_progress_dialog(
            title="下载更新",
            text="正在下载更新… 0.0%",
            progress_min=0,
            progress_max=progress_max,
            progress_value=0,
            buttons=["取消下载"],
            button_types=["normal"],
            callback=self._on_download_dialog_clicked,
            allow_close=False,
        )

        if self._current_download_total_size > 0:
            self._set_progress_info_text(
                f"{self._format_size(0)} / {self._format_size(self._current_download_total_size)} | {self._current_download_speed_text}"
            )
        else:
            self._set_progress_info_text(f"{self._format_size(0)} | {self._current_download_speed_text}")

        self._download_worker = UpdateDownloadWorker(self._current_release_info, self)
        self._download_worker.progress_changed.connect(self._on_download_progress_changed)
        self._download_worker.success.connect(self._on_download_success)
        self._download_worker.failure.connect(self._on_download_failure)
        self._download_worker.cancelled.connect(self._on_download_cancelled)
        self._download_worker.start()
        self._download_progress_timer.start()
        info("UpdateController: 下载任务已启动")

    def _on_download_dialog_clicked(self, index):
        if index != 0:
            return
        if self._download_worker and self._download_worker.isRunning():
            debug("UpdateController: 用户请求取消下载")
            self._set_dialog_text("正在取消下载，请稍候…")
            self._set_dialog_buttons([])
            self._download_worker.cancel()

    def _on_download_progress_changed(self, downloaded_size, total_size, text):
        """
        下载线程进度信号：
        - 记录线程侧已下载大小，作为文件系统大小轮询的兜底值
        - 同步总大小
        """
        self._latest_downloaded_size = max(self._latest_downloaded_size, int(downloaded_size or 0))

        effective_total = int(total_size or 0)
        if effective_total > 0:
            self._current_download_total_size = effective_total

    def _on_download_success(self, cache_result):
        info("UpdateController: 下载完成，SHA256校验通过")
        self._download_progress_timer.stop()
        self._download_worker = None
        self._current_download_total_size = 0
        self._current_download_temp_path = None
        self._current_download_final_path = None
        self._latest_downloaded_size = 0
        self._last_speed_check_time = None
        self._last_speed_check_size = 0
        self._current_download_speed_text = "0 B/s"
        self._current_ready_package = cache_result

        self._show_install_ready_dialog(
            title="下载完成",
            text=(
                "更新安装包已下载完成，并且 SHA256 校验通过。\n\n"
                "如果立即安装，程序将关闭，请先保存好当前工作区。"
            ),
        )

    def _on_download_failure(self, message):
        error(f"UpdateController: 下载失败: {message}")
        self._download_progress_timer.stop()
        self._download_worker = None
        self._current_download_total_size = 0
        self._current_download_temp_path = None
        self._current_download_final_path = None
        self._latest_downloaded_size = 0
        self._last_speed_check_time = None
        self._last_speed_check_size = 0
        self._current_download_speed_text = "0 B/s"
        self._show_message_dialog(
            title="下载更新失败",
            text=message,
            buttons=["确定"],
            button_types=["primary"],
        )

    def _on_download_cancelled(self):
        info("UpdateController: 下载已取消")
        self._download_progress_timer.stop()
        self._download_worker = None
        self._current_download_total_size = 0
        self._current_download_temp_path = None
        self._current_download_final_path = None
        self._latest_downloaded_size = 0
        self._last_speed_check_time = None
        self._last_speed_check_size = 0
        self._current_download_speed_text = "0 B/s"
        self._show_message_dialog(
            title="下载已取消",
            text="更新下载已取消，本次未保留未完成的临时文件。",
            buttons=["确定"],
            button_types=["primary"],
        )

    def _poll_download_progress_from_file(self):
        """
        每秒检查一次本地下载文件大小，并据此刷新下载百分比与进度条
        """
        if self._current_progress_bar is None:
            return

        effective_total = int(self._current_download_total_size or 0)
        if effective_total <= 0:
            effective_total = int((self._current_release_info or {}).get("installer_size", 0) or 0)

        file_size = 0
        for candidate in (self._current_download_temp_path, self._current_download_final_path):
            if candidate and os.path.exists(candidate):
                try:
                    file_size = os.path.getsize(candidate)
                    break
                except OSError:
                    continue

        current_size = max(file_size, int(self._latest_downloaded_size or 0))

        now = time.time()
        if self._last_speed_check_time is None:
            self._last_speed_check_time = now
            self._last_speed_check_size = current_size
            self._current_download_speed_text = "0 B/s"
        else:
            delta_time = max(0.001, now - self._last_speed_check_time)
            delta_size = max(0, current_size - self._last_speed_check_size)
            speed_bytes_per_sec = delta_size / delta_time
            self._current_download_speed_text = self._format_speed(speed_bytes_per_sec)
            self._last_speed_check_time = now
            self._last_speed_check_size = current_size

        if effective_total > 0:
            percent = (current_size * 100.0) / effective_total
            percent = max(0.0, min(100.0, percent))

            self._set_dialog_text(f"正在下载更新… {percent:.1f}%")
            self._set_progress_info_text(
                f"{self._format_size(current_size)} / {self._format_size(effective_total)} | {self._current_download_speed_text}"
            )
            self._current_progress_bar.setRange(0, effective_total)
            self._current_progress_bar.setValue(min(current_size, effective_total), use_animation=False)
        else:
            self._set_dialog_text("正在下载更新…")
            self._set_progress_info_text(f"{self._format_size(current_size)} | {self._current_download_speed_text}")
            self._current_progress_bar.setRange(0, 0)
            self._current_progress_bar.setValue(0, use_animation=False)

        self._current_progress_bar.update()
        if self._current_progress_info_label is not None:
            self._current_progress_info_label.update()
        QApplication.processEvents()

    @staticmethod
    def _format_speed(bytes_per_sec):
        value = float(bytes_per_sec or 0.0)
        if value >= 1024 * 1024:
            return f"{value / (1024 * 1024):.2f} MB/s"
        if value >= 1024:
            return f"{value / 1024:.2f} KB/s"
        return f"{value:.0f} B/s"

    @staticmethod
    def _format_size(size):
        units = ["B", "KB", "MB", "GB"]
        value = float(size or 0)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.2f} {unit}"
            value /= 1024.0
        return f"{size} B"

    def _normalize_release_notes(self, text):
        if not text:
            return "暂无更新日志。"
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        return normalized or "暂无更新日志。"

    def _get_theme_colors(self):
        app = QApplication.instance()
        settings_manager = getattr(app, "settings_manager", None)

        base_color = "#FFFFFF"
        secondary_color = "#333333"
        accent_color = "#007AFF"
        auxiliary_color = "#f1f3f5"

        if settings_manager is not None:
            base_color = settings_manager.get_setting("appearance.colors.base_color", base_color)
            secondary_color = settings_manager.get_setting("appearance.colors.secondary_color", secondary_color)
            accent_color = settings_manager.get_setting("appearance.colors.accent_color", accent_color)
            auxiliary_color = settings_manager.get_setting("appearance.colors.auxiliary_color", auxiliary_color)

        return {
            "base": base_color,
            "secondary": secondary_color,
            "accent": accent_color,
            "auxiliary": auxiliary_color,
        }

    def _create_info_label(self, text, selectable=False):
        theme_colors = self._get_theme_colors()
        label = QLabel(text)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignCenter)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse if selectable else Qt.NoTextInteraction)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: {theme_colors["secondary"]};
                background-color: transparent;
                padding: 0px;
                margin: 0px;
                line-height: 1.5;
            }}
            """
        )
        return label

    def _create_section_title_label(self, text):
        theme_colors = self._get_theme_colors()
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: {theme_colors["secondary"]};
                background-color: transparent;
                font-weight: 600;
                padding: 0px;
                margin-top: 4px;
                margin-bottom: 2px;
            }}
            """
        )
        return label

    def _render_markdown_release_notes(self, html_content):
        """
        将更新日志内容包装为完整 HTML 文档，应用 CSS 样式

        Args:
            html_content (str): 更新日志内容（纯文本或 HTML）

        Returns:
            str: 渲染后的完整 HTML 文档
        """
        if not html_content or not html_content.strip():
            return "<p style='color: #999;'>暂无更新日志。</p>"

        # 检测是否为 HTML 格式（以标签开头）
        is_html = html_content.strip().startswith("<")

        if not is_html:
            # 纯文本/Markdown 格式，转换为 HTML
            html_content = self._convert_markdown_to_html(html_content)

        theme_colors = self._get_theme_colors()
        secondary_color = theme_colors["secondary"]
        border_color = theme_colors["secondary"]
        auxiliary_color = theme_colors["auxiliary"]

        full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{ font-family: Microsoft YaHei, sans-serif; font-size: 10pt; line-height: 1.6; color: {secondary_color}; margin: 0; padding: 8px; }}
div {{ color: {secondary_color}; }}
p {{ color: {secondary_color}; margin: 0.5em 0; }}
li {{ color: {secondary_color}; margin: 0.3em 0; }}
pre {{ background-color: {auxiliary_color}; padding: 10px; border-radius: 4px; overflow-x: auto; margin: 0.5em 0; white-space: pre-wrap; word-wrap: break-word; }}
code {{ background-color: {auxiliary_color}; padding: 2px 5px; border-radius: 3px; font-family: Consolas, monospace; color: {secondary_color}; }}
pre code {{ background-color: transparent; padding: 0; color: {secondary_color} !important; }}
h1, h2, h3, h4, h5, h6 {{ color: {secondary_color}; margin-top: 1em; margin-bottom: 0.5em; }}
h1 {{ font-size: 1.8em; border-bottom: 1px solid {border_color}; padding-bottom: 0.3em; }}
h2 {{ font-size: 1.5em; border-bottom: 1px solid {border_color}; padding-bottom: 0.2em; }}
h3 {{ font-size: 1.25em; }}
h4 {{ font-size: 1.1em; }}
h5 {{ font-size: 1em; }}
h6 {{ font-size: 0.9em; }}
table {{ border-collapse: collapse; width: 100%; margin: 0.5em 0; }}
th {{ background-color: {auxiliary_color}; color: {secondary_color}; }}
td {{ color: {secondary_color}; }}
th, td {{ border: 1px solid {border_color}; padding: 8px; text-align: left; }}
blockquote {{ border-left: 4px solid {border_color}; margin: 0.5em 0; padding-left: 16px; color: {secondary_color}; }}
img {{ max-width: 100%; }}
strong, b {{ color: {secondary_color}; font-weight: 600; }}
em, i {{ color: {secondary_color}; font-style: italic; }}
a {{ color: {secondary_color}; text-decoration: underline; }}
ul, ol {{ margin: 0.5em 0; padding-left: 2em; }}
ul ul, ul ol, ol ul, ol ol {{ margin: 0.2em 0; }}
ul li {{ list-style-type: disc; }}
ul ul li {{ list-style-type: circle; }}
ol li {{ list-style-type: decimal; }}
ol ol li {{ list-style-type: lower-alpha; }}
hr {{ border: none; border-top: 1px solid {border_color}; margin: 1em 0; }}
</style>
</head>
<body>
{html_content}
</body>
</html>"""
        return full_html

    @staticmethod
    def _convert_markdown_to_html(text):
        """将简化的 Markdown 文本转换为 HTML"""
        # 统一换行符
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        
        lines = text.split("\n")
        html_parts = []
        
        for line in lines:
            stripped = line.strip()
            
            if not stripped:
                # 空行
                html_parts.append("<br>")
            elif stripped.startswith("### "):
                html_parts.append(f"<h4>{UpdateController._process_inline_markdown(stripped[4:])}</h4>")
            elif stripped.startswith("## "):
                html_parts.append(f"<h3>{UpdateController._process_inline_markdown(stripped[3:])}</h3>")
            elif stripped.startswith("# "):
                html_parts.append(f"<h2>{UpdateController._process_inline_markdown(stripped[2:])}</h2>")
            elif stripped.startswith("- ") or stripped.startswith("* "):
                html_parts.append(f"<li>{UpdateController._process_inline_markdown(stripped[2:])}</li>")
            else:
                # 普通文本行，处理行内 Markdown 后直接输出
                html_parts.append(f"{UpdateController._process_inline_markdown(stripped)}<br>")
        
        return "".join(html_parts)

    @staticmethod
    def _process_inline_markdown(text):
        """处理行内 Markdown 格式：粗体、斜体、链接、代码"""
        # 先转义 HTML 特殊字符
        text = UpdateController._escape_html(text)
        
        # 处理链接格式：**text**: url 或 **text**:url
        import re
        text = re.sub(
            r'\*\*(.+?)\*\*:\s*(https?://[^\s<]+)',
            r'<strong>\1</strong>: <a href="\2" target="_blank">\2</a>',
            text
        )
        
        # 处理纯链接
        text = re.sub(
            r'(https?://[^\s<]+)',
            r'<a href="\1" target="_blank">\1</a>',
            text
        )
        
        # 处理粗体 **text**
        text = re.sub(
            r'\*\*(.+?)\*\*',
            r'<strong>\1</strong>',
            text
        )
        
        # 处理斜体 *text*（但要排除已经处理的粗体）
        text = re.sub(
            r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)',
            r'<em>\1</em>',
            text
        )
        
        # 处理行内代码 `text`
        text = re.sub(
            r'`(.+?)`',
            r'<code>\1</code>',
            text
        )
        
        return text

    @staticmethod
    def _escape_html(text):
        """转义 HTML 特殊字符"""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    def _create_markdown_text_edit(self, html_content):
        """
        创建用于显示更新日志的 QTextBrowser

        Args:
            html_content (str): HTML 内容（完整 HTML 文档）

        Returns:
            QTextBrowser: 配置好的 QTextBrowser 实例
        """
        text_browser = QTextBrowser()
        text_browser.setReadOnly(True)
        text_browser.setOpenExternalLinks(False)
        text_browser.setHtml(html_content)
        text_browser.setLineWrapMode(QTextBrowser.WidgetWidth)
        text_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        text_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        text_browser.setFrameShape(QTextBrowser.NoFrame)
        text_browser.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextBrowserInteraction)

        theme_colors = self._get_theme_colors()
        text_browser.setStyleSheet(
            f"""
            QTextBrowser {{
                background-color: transparent;
                color: {theme_colors["secondary"]};
                border: none;
                padding: 0px;
                margin: 0px;
            }}
            """
        )

        return text_browser

    def _show_update_available_detail_dialog(self, local_info, release_info, installer_ready):
        self._close_current_dialog()

        dialog = CustomMessageBox(self.main_window)
        dialog.setModal(True)
        
        current_tag = local_info.get("tag_name", "未知版本")
        latest_tag = release_info.get("tag_name", "未知版本")
        latest_date = release_info.get("published_date", "未知日期")
        installer_size = self._format_size(release_info.get("installer_size", 0))
        release_notes = self._normalize_release_notes(release_info.get("release_body", ""))

        dialog.set_title(f"检测到可用更新（{latest_tag}）")

        main_container = QWidget()
        main_layout = QVBoxLayout(main_container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(12)

        info_text = f"发布日期：{latest_date}    |    安装包大小：{installer_size}"
        main_layout.addWidget(self._create_info_label(info_text))

        main_layout.addWidget(self._create_section_title_label("更新日志"))
        
        markdown_html = self._render_markdown_release_notes(release_notes)
        markdown_label = self._create_markdown_text_edit(markdown_html)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scroll_area.setMinimumSize(450, 260)

        scroll_area.setWidget(markdown_label)
        
        theme_colors = self._get_theme_colors()
        normal_color = theme_colors["auxiliary"]
        
        scroll_area.setStyleSheet(
            f"""
            QScrollArea {{
                background-color: {normal_color};
                border: 1px solid {normal_color};
                border-radius: 4px;
                padding: 6px;
            }}
            """
        )
        
        vertical_scrollbar = D_ScrollBar(Qt.Vertical, scroll_area)
        vertical_scrollbar.apply_theme_from_settings()
        scroll_area.setVerticalScrollBar(vertical_scrollbar)
        SmoothScroller.apply_to_scroll_area(scroll_area, enable_mouse_drag=False, enable_smart_width=True)

        main_layout.addWidget(scroll_area)

        dialog.list_layout.addWidget(main_container)
        dialog.list_widget.show()

        buttons = ["立即安装", "取消"] if installer_ready else ["下载更新", "取消"]
        button_types = ["primary", "normal"] if installer_ready else ["primary", "normal"]
        callback = self._on_install_ready_dialog_clicked if installer_ready else self._on_update_available_dialog_clicked
        dialog.set_buttons(buttons, Qt.Horizontal, button_types)
        dialog.buttonClicked.connect(callback)

        self._current_dialog = dialog
        self._current_progress_bar = None
        self._current_progress_info_label = None
        dialog.exec()
        if self._current_dialog is dialog:
            self._current_dialog = None
            self._current_progress_bar = None
            self._current_progress_info_label = None

    def _show_install_ready_dialog(self, title, text):
        self._show_message_dialog(
            title=title,
            text=text,
            buttons=["立即安装", "取消"],
            button_types=["primary", "normal"],
            callback=self._on_install_ready_dialog_clicked,
        )

    def _on_install_ready_dialog_clicked(self, index):
        if index != 0:
            return

        debug("UpdateController: 用户确认安装更新")
        if not self._current_ready_package:
            warning("UpdateController: 安装失败，未找到安装包信息")
            self._show_message_dialog(
                title="安装失败",
                text="未找到可用的安装包信息。",
                buttons=["确定"],
                button_types=["primary"],
            )
            return

        installer_path = self._current_ready_package.get("installer_path")
        expected_sha256 = self._current_ready_package.get("installer_sha256")

        if not installer_path or not expected_sha256:
            warning("UpdateController: 安装失败，安装包信息不完整")
            self._show_message_dialog(
                title="安装失败",
                text="安装包信息不完整，无法继续安装。",
                buttons=["确定"],
                button_types=["primary"],
            )
            return

        if not os.path.exists(installer_path):
            warning(f"UpdateController: 安装失败，安装包不存在: {installer_path}")
            self._show_message_dialog(
                title="安装失败",
                text="本地安装包不存在，请重新检查更新后再试。",
                buttons=["确定"],
                button_types=["primary"],
            )
            return

        if not verify_installer_file(installer_path, expected_sha256):
            warning("UpdateController: 安装失败，本地安装包校验失败")
            try:
                os.remove(installer_path)
            except OSError:
                pass

            metadata_path = get_cache_metadata_path()
            if os.path.exists(metadata_path):
                try:
                    os.remove(metadata_path)
                except OSError:
                    pass

            self._show_message_dialog(
                title="安装失败",
                text="本地安装包校验失败，缓存已清理，请重新下载。",
                buttons=["确定"],
                button_types=["primary"],
            )
            return

        try:
            self._launch_installer_helper(installer_path, expected_sha256)
        except Exception as e:
            error(f"UpdateController: 启动安装程序失败: {e}")
            self._show_message_dialog(
                title="安装失败",
                text=f"启动安装程序失败：{e}",
                buttons=["确定"],
                button_types=["primary"],
            )
            return

        info(f"准备退出程序并启动安装包: {installer_path}")
        self.main_window.close()
        QTimer.singleShot(100, QApplication.instance().quit)

    def _launch_installer_helper(self, installer_path, expected_sha256):
        current_pid = os.getpid()

        if getattr(sys, "frozen", False):
            helper_args = [
                sys.executable,
                "--faf-run-installer",
                installer_path,
                expected_sha256,
                str(current_pid),
            ]
        else:
            helper_entry = os.path.abspath(sys.argv[0])
            helper_args = [
                sys.executable,
                helper_entry,
                "--faf-run-installer",
                installer_path,
                expected_sha256,
                str(current_pid),
            ]

        creation_flags = 0
        creation_flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        creation_flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        creation_flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        info(f"启动安装 helper: {' '.join(helper_args)}")

        subprocess.Popen(
            helper_args,
            close_fds=True,
            creationflags=creation_flags,
        )

    def _show_progress_dialog(
        self,
        title,
        text,
        progress_min=0,
        progress_max=1000,
        progress_value=0,
        buttons=None,
        button_types=None,
        callback=None,
        allow_close=False,
    ):
        self._close_current_dialog()

        dialog = CustomMessageBox(self.main_window)
        dialog.setModal(True)
        dialog.set_title(title)

        progress_container = QWidget()
        progress_container_layout = QVBoxLayout(progress_container)
        progress_container_layout.setContentsMargins(0, 0, 0, 0)
        progress_container_layout.setSpacing(8)

        is_checking = progress_max == 0

        if is_checking:
            dialog.text_label.hide()
            dialog.body_layout.removeWidget(dialog.text_label)
            dialog.image_label.hide()
            dialog.body_layout.removeWidget(dialog.image_label)
            dialog.list_widget.hide()
            dialog.body_layout.removeWidget(dialog.list_widget)
            dialog.input_widget.hide()
            dialog.body_layout.removeWidget(dialog.input_widget)
            dialog.progress_widget.hide()
            dialog.body_layout.removeWidget(dialog.progress_widget)

            self._current_loading_spinner = LoadingSpinner(icon_size=48, dpi_scale=1.0)
            self._current_loading_spinner.set_background_color(self._get_theme_colors()["base"])
            self._current_loading_spinner.start()
            progress_container_layout.addWidget(self._current_loading_spinner, 0, Qt.AlignCenter)
            self._current_progress_bar = None
            self._current_progress_info_label = None
        else:
            dialog.set_text(text)
            progress_bar = D_ProgressBar(is_interactive=False)
            progress_bar.setInteractive(False)
            progress_bar.setRange(progress_min, progress_max)
            progress_bar.setValue(progress_value, use_animation=False)
            progress_container_layout.addWidget(progress_bar)

            progress_info_label = QLabel("")
            progress_info_label.setAlignment(Qt.AlignCenter)
            theme_colors = self._get_theme_colors()
            progress_info_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {theme_colors["secondary"]};
                    background-color: transparent;
                    padding: 0px;
                    margin: 0px;
                }}
                """
            )
            progress_container_layout.addWidget(progress_info_label)
            self._current_progress_info_label = progress_info_label
            self._current_progress_bar = progress_bar
            self._current_loading_spinner = None

        button_index = dialog.body_layout.indexOf(dialog.button_widget)
        dialog.body_layout.insertWidget(button_index, progress_container)

        if buttons:
            dialog.set_buttons(buttons, Qt.Horizontal, button_types or ["primary"] * len(buttons))
            if callback:
                dialog.buttonClicked.connect(callback)

        if not allow_close:
            dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowCloseButtonHint)

        self._current_dialog = dialog
        dialog.show()

    def _show_message_dialog(self, title, text, buttons, button_types, callback=None):
        self._close_current_dialog()

        dialog = CustomMessageBox(self.main_window)
        dialog.setModal(True)
        dialog.set_title(title)
        dialog.set_text(text)
        dialog.set_buttons(buttons, Qt.Horizontal, button_types)
        if callback:
            dialog.buttonClicked.connect(callback)

        self._current_dialog = dialog
        self._current_progress_bar = None
        self._current_progress_info_label = None
        dialog.exec()
        if self._current_dialog is dialog:
            self._current_dialog = None
            self._current_progress_bar = None
            self._current_progress_info_label = None

    def _set_dialog_text(self, text):
        if self._current_dialog is not None:
            self._current_dialog.set_text(text)

    def _set_progress_info_text(self, text):
        if self._current_progress_info_label is not None:
            self._current_progress_info_label.setText(text)

    def _set_dialog_buttons(self, buttons, button_types=None, callback=None):
        if self._current_dialog is None:
            return

        if buttons:
            self._current_dialog.set_buttons(buttons, Qt.Horizontal, button_types or ["primary"] * len(buttons))
            if callback:
                self._current_dialog.buttonClicked.connect(callback)
        else:
            self._current_dialog.set_buttons([], Qt.Horizontal, [])

    def _close_current_dialog(self):
        if self._current_dialog is not None:
            try:
                self._current_dialog.close()
            except Exception:
                pass
        self._download_progress_timer.stop()
        self._last_speed_check_time = None
        self._last_speed_check_size = 0
        self._current_download_speed_text = "0 B/s"
        if self._current_loading_spinner is not None:
            self._current_loading_spinner.stop()
            self._current_loading_spinner = None
        self._current_dialog = None
        self._current_progress_bar = None
        self._current_progress_info_label = None

    def _on_silent_check_update_available(self, result):
        """
        静默检查发现新版本后的回调
        """
        sender = self.sender()
        if sender in self._retired_silent_workers:
            debug("UpdateController: 忽略已取消静默检查的更新提示")
            return

        if self._manual_check_uses_silent or self._silent_check_claimed_by_manual:
            debug("UpdateController: 静默检查结果已由手动检查接管，不显示静默提示")
            return

        if self._silent_check_cancelled:
            debug("UpdateController: 静默检查已被取消，忽略更新提示")
            self._silent_check_cancelled = False
            return
        
        # 如果用户已经手动触发了检查更新，不显示弹窗
        if self._check_worker and self._check_worker.isRunning():
            debug("UpdateController: 手动检查正在运行，静默检查结果不弹窗")
            return
        
        release_info = result["latest_release"]
        self._current_release_info = release_info
        info(f"静默检查发现新版本: {release_info.get('tag_name', 'unknown')}")
        
        local_info = result.get("local_info", {})
        
        cache_result = result.get("cache_result", {})
        installer_path = cache_result.get("installer_path")
        installer_ready = bool(cache_result.get("is_ready")) and bool(installer_path)
        
        self._current_ready_package = cache_result if installer_ready else None
        if installer_ready:
            debug("UpdateController: 静默检查发现本地已存在可用安装包")
        
        # 显示更新提示弹窗
        self._show_update_available_detail_dialog(
            local_info=local_info,
            release_info=release_info,
            installer_ready=installer_ready,
        )

    def _on_silent_check_success(self, result):
        sender = self.sender()
        if sender in self._retired_silent_workers:
            debug("UpdateController: 忽略已取消静默检查的成功结果")
            return

        if not self._manual_check_uses_silent:
            return

        debug("UpdateController: 使用静默检查结果完成手动检查展示")
        self._manual_check_uses_silent = False
        self._silent_check_claimed_by_manual = True
        self._silent_check_cancelled = False

        if self._check_cancelled:
            debug("UpdateController: 手动检查已取消，忽略静默检查结果")
            self._check_cancelled = False
            self._close_current_dialog()
            return

        self._show_check_result(result)

    def _on_silent_check_failure(self, message):
        sender = self.sender()
        if sender in self._retired_silent_workers:
            debug("UpdateController: 忽略已取消静默检查的失败结果")
            return

        if not self._manual_check_uses_silent:
            return

        debug("UpdateController: 已接管的静默检查失败")
        self._manual_check_uses_silent = False
        self._silent_check_claimed_by_manual = True
        self._on_check_failure(message)

    def _on_silent_check_cancelled(self):
        sender = self.sender()
        if sender in self._retired_silent_workers:
            debug("UpdateController: 已取消静默检查线程结束")
            return

        if not self._manual_check_uses_silent:
            return

        debug("UpdateController: 已接管的静默检查被取消")
        self._manual_check_uses_silent = False
        self._silent_check_claimed_by_manual = False
        self._on_check_cancelled()

    def _on_silent_check_finished(self):
        """
        静默检查完成的回调（无论成功失败）
        """
        sender = self.sender()
        if sender in self._retired_silent_workers:
            self._forget_retired_worker(sender, self._retired_silent_workers)
            return

        debug("UpdateController: 静默检查已完成")
        if sender is None or sender is self._silent_check_worker:
            self._silent_check_worker = None
            self._manual_check_uses_silent = False
            self._silent_check_claimed_by_manual = False
