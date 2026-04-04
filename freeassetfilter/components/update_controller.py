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
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QScrollArea, QSizePolicy

from freeassetfilter.core.update_manager import (
    UpdateError,
    build_request_headers,
    check_for_updates,
    prepare_cached_installer,
    get_cache_dir,
    get_cache_metadata_path,
    verify_installer_file,
)
from freeassetfilter.utils.app_logger import info, warning, error
from freeassetfilter.widgets.message_box import CustomMessageBox
from freeassetfilter.widgets.progress_widgets import D_ProgressBar
from freeassetfilter.widgets.smooth_scroller import D_ScrollBar, SmoothScroller


class UpdateCheckWorker(QThread):
    """
    后台检查更新线程
    """

    success = Signal(dict)
    failure = Signal(str)

    def run(self):
        try:
            result = check_for_updates()
            self.success.emit(result)
        except UpdateError as e:
            self.failure.emit(str(e))
        except Exception as e:
            error(f"检查更新失败: {e}")
            self.failure.emit(f"检查更新失败：{e}")


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
        self._cancel_requested = True

    def run(self):
        temp_path = None
        try:
            os.makedirs(get_cache_dir(), exist_ok=True)

            installer_name = self.release_info["installer_name"]
            final_path = os.path.join(get_cache_dir(), installer_name)
            temp_path = f"{final_path}.download"

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

                with open(temp_path, "wb") as f:
                    while True:
                        if self._cancel_requested:
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
                        downloaded_size += len(chunk)
                        self.progress_changed.emit(
                            downloaded_size,
                            total_size,
                            f"正在下载更新… {self._format_progress_text(downloaded_size, total_size)}",
                        )

            try:
                os.replace(temp_path, final_path)
            except OSError as e:
                raise UpdateError(f"写入安装包失败：{e}") from e

            is_valid = verify_installer_file(final_path, self.release_info["installer_sha256"])
            if not is_valid:
                try:
                    os.remove(final_path)
                except OSError:
                    pass
                raise UpdateError("下载完成，但 SHA256 校验失败")

            cache_result = prepare_cached_installer(self.release_info, final_path)
            self.success.emit(cache_result)
        except UpdateError as e:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            self.failure.emit(str(e))
        except (urllib_error.URLError, OSError) as e:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            self.failure.emit(f"下载更新失败：{e}")
        except Exception as e:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            error(f"下载更新失败: {e}")
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
        self._current_release_info = None
        self._current_ready_package = None
        self._check_cancelled = False

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

    def on_check_updates_clicked(self):
        """
        点击“检查更新”
        """
        if self._check_worker and self._check_worker.isRunning():
            return

        if self._download_worker and self._download_worker.isRunning():
            return

        self._current_release_info = None
        self._current_ready_package = None
        self._check_cancelled = False

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

        self._check_worker = UpdateCheckWorker(self)
        self._check_worker.success.connect(self._on_check_success)
        self._check_worker.failure.connect(self._on_check_failure)
        self._check_worker.start()

    def _on_check_dialog_clicked(self, index):
        if index != 0:
            return

        if self._check_worker and self._check_worker.isRunning():
            self._check_cancelled = True
            self._close_current_dialog()

    def _on_check_success(self, result):
        self._check_worker = None

        if self._check_cancelled:
            self._check_cancelled = False
            return

        if not result.get("update_available", False):
            local_info = result.get("local_info", {})
            latest_release = result.get("latest_release", {})

            latest_tag = latest_release.get("tag_name") or "未知版本"
            latest_date = latest_release.get("published_date") or "未知日期"
            local_tag = local_info.get("tag_name") or "未知版本"
            local_date = local_info.get("build_date") or "未知日期"

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

        local_info = result.get("local_info", {})

        cache_result = result.get("cache_result", {})
        installer_path = cache_result.get("installer_path")
        installer_ready = bool(cache_result.get("is_ready")) and bool(installer_path)

        self._current_ready_package = cache_result if installer_ready else None

        self._show_update_available_detail_dialog(
            local_info=local_info,
            release_info=release_info,
            installer_ready=installer_ready,
        )

    def _on_check_failure(self, message):
        self._check_worker = None

        if self._check_cancelled:
            self._check_cancelled = False
            return

        self._show_message_dialog(
            title="检查更新失败",
            text=message,
            buttons=["确定"],
            button_types=["warning"],
        )

    def _on_update_available_dialog_clicked(self, index):
        if index != 0 or not self._current_release_info:
            return

        progress_max = int(self._current_release_info.get("installer_size", 0) or 0)
        if progress_max <= 0:
            progress_max = 1000

        self._show_progress_dialog(
            title="下载更新",
            text="正在下载更新…",
            progress_min=0,
            progress_max=progress_max,
            progress_value=0,
            buttons=["取消下载"],
            button_types=["normal"],
            callback=self._on_download_dialog_clicked,
            allow_close=False,
        )

        self._download_worker = UpdateDownloadWorker(self._current_release_info, self)
        self._download_worker.progress_changed.connect(self._on_download_progress_changed)
        self._download_worker.success.connect(self._on_download_success)
        self._download_worker.failure.connect(self._on_download_failure)
        self._download_worker.cancelled.connect(self._on_download_cancelled)
        self._download_worker.start()

    def _on_download_dialog_clicked(self, index):
        if index != 0:
            return
        if self._download_worker and self._download_worker.isRunning():
            self._set_dialog_text("正在取消下载，请稍候…")
            self._set_dialog_buttons([])
            self._download_worker.cancel()

    def _on_download_progress_changed(self, downloaded_size, total_size, text):
        self._set_dialog_text(text)

        if self._current_progress_bar is None:
            return

        if total_size > 0:
            self._current_progress_bar.setRange(0, total_size)
            self._current_progress_bar.setValue(downloaded_size, use_animation=False)
        else:
            fallback_total = int((self._current_release_info or {}).get("installer_size", 0) or 0)
            if fallback_total > 0:
                self._current_progress_bar.setRange(0, fallback_total)
                self._current_progress_bar.setValue(min(downloaded_size, fallback_total), use_animation=False)
            else:
                self._current_progress_bar.setRange(0, 0)
                self._current_progress_bar.setValue(0, use_animation=False)

    def _on_download_success(self, cache_result):
        self._download_worker = None
        self._current_ready_package = cache_result

        self._show_install_ready_dialog(
            title="下载完成",
            text=(
                "更新安装包已下载完成，并且 SHA256 校验通过。\n\n"
                "如果立即安装，程序将关闭，请先保存好当前工作区。"
            ),
        )

    def _on_download_failure(self, message):
        self._download_worker = None
        self._show_message_dialog(
            title="下载更新失败",
            text=message,
            buttons=["确定"],
            button_types=["warning"],
        )

    def _on_download_cancelled(self):
        self._download_worker = None
        self._show_message_dialog(
            title="下载已取消",
            text="更新下载已取消，本次未保留未完成的临时文件。",
            buttons=["确定"],
            button_types=["primary"],
        )

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

        secondary_color = "#333333"
        accent_color = "#007AFF"
        auxiliary_color = "#f1f3f5"

        if settings_manager is not None:
            secondary_color = settings_manager.get_setting("appearance.colors.secondary_color", secondary_color)
            accent_color = settings_manager.get_setting("appearance.colors.accent_color", accent_color)
            auxiliary_color = settings_manager.get_setting("appearance.colors.auxiliary_color", auxiliary_color)

        return {
            "secondary": secondary_color,
            "accent": accent_color,
            "auxiliary": auxiliary_color,
        }

    def _create_info_label(self, text, selectable=False):
        theme_colors = self._get_theme_colors()
        label = QLabel(text)
        label.setWordWrap(True)
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

    def _show_update_available_detail_dialog(self, local_info, release_info, installer_ready):
        self._close_current_dialog()

        dialog = CustomMessageBox(self.main_window)
        dialog.setModal(True)
        dialog.set_title("发现新版本")
        dialog.set_text("检测到可用更新，请查看本次发行详情。")

        detail_container = QWidget()
        detail_layout = QVBoxLayout(detail_container)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(8)

        current_tag = local_info.get("tag_name", "未知版本")
        latest_tag = release_info.get("tag_name", "未知版本")
        latest_date = release_info.get("published_date", "未知日期")
        installer_size = self._format_size(release_info.get("installer_size", 0))
        release_notes = self._normalize_release_notes(release_info.get("release_body", ""))

        detail_layout.addWidget(self._create_info_label(f"当前版本号：{current_tag}"))
        detail_layout.addWidget(self._create_info_label(f"最新版本号：{latest_tag}"))
        detail_layout.addWidget(self._create_info_label(f"最新更新日期：{latest_date}"))
        detail_layout.addWidget(self._create_info_label(f"安装包大小：{installer_size}"))

        detail_layout.addWidget(self._create_section_title_label("详细日志"))
        detail_layout.addWidget(self._create_info_label(release_notes, selectable=True))

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scroll_area.setMinimumSize(420, 280)

        theme_colors = self._get_theme_colors()

        vertical_scrollbar = D_ScrollBar(Qt.Vertical, scroll_area)
        vertical_scrollbar.set_colors(
            theme_colors["secondary"],
            theme_colors["secondary"],
            theme_colors["accent"],
            theme_colors["auxiliary"],
        )

        horizontal_scrollbar = D_ScrollBar(Qt.Horizontal, scroll_area)
        horizontal_scrollbar.set_colors(
            theme_colors["secondary"],
            theme_colors["secondary"],
            theme_colors["accent"],
            theme_colors["auxiliary"],
        )

        scroll_area.setVerticalScrollBar(vertical_scrollbar)
        scroll_area.setHorizontalScrollBar(horizontal_scrollbar)
        scroll_area.setWidget(detail_container)
        SmoothScroller.apply_to_scroll_area(scroll_area, enable_mouse_drag=False, enable_smart_width=True)

        dialog.list_layout.addWidget(scroll_area)
        dialog.list_widget.show()

        buttons = ["立即安装", "取消"] if installer_ready else ["下载更新", "取消"]
        button_types = ["warning", "normal"] if installer_ready else ["primary", "normal"]
        callback = self._on_install_ready_dialog_clicked if installer_ready else self._on_update_available_dialog_clicked
        dialog.set_buttons(buttons, Qt.Horizontal, button_types)
        dialog.buttonClicked.connect(callback)

        self._current_dialog = dialog
        self._current_progress_bar = None
        dialog.exec()
        self._current_dialog = None
        self._current_progress_bar = None

    def _show_install_ready_dialog(self, title, text):
        self._show_message_dialog(
            title=title,
            text=text,
            buttons=["立即安装", "取消"],
            button_types=["warning", "normal"],
            callback=self._on_install_ready_dialog_clicked,
        )

    def _on_install_ready_dialog_clicked(self, index):
        if index != 0:
            return

        if not self._current_ready_package:
            self._show_message_dialog(
                title="安装失败",
                text="未找到可用的安装包信息。",
                buttons=["确定"],
                button_types=["warning"],
            )
            return

        installer_path = self._current_ready_package.get("installer_path")
        expected_sha256 = self._current_ready_package.get("installer_sha256")

        if not installer_path or not expected_sha256:
            self._show_message_dialog(
                title="安装失败",
                text="安装包信息不完整，无法继续安装。",
                buttons=["确定"],
                button_types=["warning"],
            )
            return

        if not os.path.exists(installer_path):
            self._show_message_dialog(
                title="安装失败",
                text="本地安装包不存在，请重新检查更新后再试。",
                buttons=["确定"],
                button_types=["warning"],
            )
            return

        if not verify_installer_file(installer_path, expected_sha256):
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
                button_types=["warning"],
            )
            return

        try:
            self._launch_installer_helper(installer_path, expected_sha256)
        except Exception as e:
            self._show_message_dialog(
                title="安装失败",
                text=f"启动安装程序失败：{e}",
                buttons=["确定"],
                button_types=["warning"],
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
        dialog.set_text(text)

        progress_bar = D_ProgressBar(is_interactive=False)
        progress_bar.setInteractive(False)
        progress_bar.setRange(progress_min, progress_max)
        progress_bar.setValue(progress_value, use_animation=False)
        dialog.set_progress(progress_bar)

        if buttons:
            dialog.set_buttons(buttons, Qt.Horizontal, button_types or ["primary"] * len(buttons))
            if callback:
                dialog.buttonClicked.connect(callback)

        if not allow_close:
            dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowCloseButtonHint)

        self._current_dialog = dialog
        self._current_progress_bar = progress_bar
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
        dialog.exec()
        self._current_dialog = None
        self._current_progress_bar = None

    def _set_dialog_text(self, text):
        if self._current_dialog is not None:
            self._current_dialog.set_text(text)

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
        self._current_dialog = None
        self._current_progress_bar = None
