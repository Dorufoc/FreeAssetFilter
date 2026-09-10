#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 启动阶段任务编排（startup）
--------------------------------------------
自引导层（``freeassetfilter/app/main.py``）拆分出的首帧后任务：

  - ``StartupWarmupThread``：后台预热（FFmpeg / LUT），避免阻塞首屏
  - ``StartupController``：首帧后分阶段调度（心跳、附加字体注册、AVIF
    插件导入、预热、图标缓存清理、缩略图缓存清理）

说明：旧版的静默更新检查 / 下载 / 安装引导已整体移除（2026-09 重构，
功能不再提供）；启动 flags 门控与看门狗随更新流程一并移除，本模块的
各任务相互独立、失败仅记日志。

线程模型：``StartupWarmupThread`` 已从「run 即弃 QThread」重构为
``QRunnable`` 池任务（投递到 ``QThreadPool.globalInstance()``），
完成信号经主线程持有的 ``_StartupWarmupSignals`` 中转对象跨线程投递；
退出等待语义经内部 ``threading.Event`` 保持（cleanup 有界等待 2s）。
"""

from __future__ import annotations

import os
import threading
import time
import traceback
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from freeassetfilter.utils.app_logger import error, info, warning
from freeassetfilter.utils.path_utils import get_resource_path


class _StartupWarmupSignals(QObject):
    """预热任务完成信号中转（主线程持有，跨线程队列投递）。"""

    finished = Signal()


class StartupWarmupThread(QRunnable):
    """启动后后台预热任务：FFmpeg 工具链 + LUT（C++/生成器）。

    所有预热均惰性导入、逐项隔离：单项失败不影响其余预热与主流程。

    ``run()`` 在全局线程池线程中执行；完成后置位 ``is_done`` 并经
    ``finished`` 信号通知（信号经主线程持有的中转对象队列投递）。
    类名与构造签名保持向后兼容（旧版为 QThread，同名 API 不变）。
    """

    def __init__(self, parent: Optional[QObject] = None):
        # parent 参数仅为兼容旧构造签名保留；QRunnable 非 QObject，不参与父子。
        super().__init__()
        self.setAutoDelete(True)
        self._signals = _StartupWarmupSignals()
        self._done = threading.Event()

    @property
    def finished(self):
        """完成信号（经主线程中转对象；连接方式与旧 QThread.finished 一致）。"""
        return self._signals.finished

    @property
    def is_done(self) -> bool:
        """任务是否已结束（run() 返回后为 True）。"""
        return self._done.is_set()

    def wait(self, timeout_ms: int) -> bool:
        """有界等待任务完成（等价旧 QThread.wait 语义）。

        Args:
            timeout_ms: 最大等待毫秒数。

        Returns:
            bool: 超时前完成返回 True，否则 False。
        """
        return self._done.wait(timeout_ms / 1000.0)

    def run(self):
        try:
            self._warm_ffmpeg()
            self._warm_lut()
        finally:
            self._done.set()
            self._signals.finished.emit()

    def _warm_ffmpeg(self) -> None:
        try:
            from freeassetfilter.core.native.bridges.media_probe import (
                warmup_ffmpeg_tools,
            )

            warmup_ffmpeg_tools()
        except Exception as e:
            error(f"FFmpeg 预热失败: {e}")

    def _warm_lut(self) -> None:
        try:
            from freeassetfilter.core.native.bridges.lut_preview_generator import (
                get_preview_generator,
            )
            from freeassetfilter.core.native.src.cpp_lut_preview import (
                warmup as lut_cpp_warmup,
            )

            lut_cpp_warmup()
            get_preview_generator()
        except Exception as e:
            error(f"LUT 预热失败: {e}")


class StartupController:
    """引导层启动任务编排器（非 Qt 对象，全部经 QTimer 调度到主线程）。"""

    def __init__(self, app, window) -> None:
        self.app = app
        self.window = window
        self._heartbeat = None
        self._warmup_thread = None

    # ── 调度入口 ────────────────────────────────────────────────

    def schedule_startup_tasks(self) -> None:
        """在首屏显示后分阶段执行启动任务，避免阻塞窗口显示。"""
        try:
            from freeassetfilter.core.managers.heartbeat_manager import HeartbeatManager

            self._heartbeat = HeartbeatManager()
        except Exception as e:
            error(f"[启动] 心跳管理器创建失败: {e}")

        QTimer.singleShot(0, self._safe("_register_extra_fonts"))
        QTimer.singleShot(0, self._safe("_lazy_import_pillow_avif"))
        QTimer.singleShot(0, self._safe("_start_background_warmup"))
        QTimer.singleShot(0, self._safe("_cleanup_icon_cache"))
        QTimer.singleShot(100, self._safe("_schedule_thumbnail_cleanup"))

        # 首帧后启动心跳（主线程周期性调度；GPU 流体背景 ~30FPS 动画依赖它）
        if self._heartbeat is not None:
            QTimer.singleShot(0, self._heartbeat.start)

    def _safe(self, name):
        def _runner():
            try:
                getattr(self, name)()
            except Exception as e:
                error(f"启动回调 [{name}] 失败: {e}")
                error(traceback.format_exc())
        return _runner

    # ── 附加字体与可选插件 ──────────────────────────────────────

    def _register_extra_fonts(self) -> None:
        """注册 FiraCode（代码高亮字体；注册后可按 family 名使用）。

        不再改写全局应用字体：全局字体保持 Qt 默认，与
        ui/main_window.py 独立启动观感一致。
        """
        from PySide6.QtGui import QFontDatabase

        firacode_font_path = get_resource_path("freeassetfilter/icons/FiraCode-VF.ttf")
        if not os.path.exists(firacode_font_path):
            return
        try:
            QFontDatabase.addApplicationFont(firacode_font_path)
        except Exception as e:
            warning(f"[启动] FiraCode 注册失败: {e}")

    def _lazy_import_pillow_avif(self) -> None:
        """延迟导入 pillow_avif（AVIF 图像打开前注册即可）。"""
        try:
            import pillow_avif  # noqa: F401
        except ImportError:
            pass

    # ── 缓存清理 ────────────────────────────────────────────────

    def _cleanup_icon_cache(self) -> None:
        """启动阶段磁盘图标缓存清理（最旧优先双阈值）。"""
        try:
            from freeassetfilter.utils.icon_utils import cleanup_icon_cache

            removed = cleanup_icon_cache()
            if removed:
                info(f"[启动] 图标缓存清理: 删除 {removed} 个文件")
        except Exception as e:
            warning(f"[启动] 图标缓存清理失败: {e}")

    def _schedule_thumbnail_cleanup(self) -> None:
        """按设置门控调度缩略图缓存清理（自动清理开且超过清理周期才执行）。"""
        sm = getattr(self.app, "settings_manager", None)
        try:
            auto_clear = bool(sm.get("file_selector.auto_clear_thumbnail_cache", True)) if sm else True
            if not auto_clear:
                return
            cleanup_period = int(sm.get("file_selector.cache_cleanup_period", 7) or 7) if sm else 7
            last_cleanup = sm.get("file_selector.last_cleanup_time", None) if sm else None
            now = time.time()
            if last_cleanup is None or (now - float(last_cleanup)) > (cleanup_period * 86400):
                QTimer.singleShot(0, lambda: self._run_thumbnail_cleanup(now))
        except Exception as e:
            warning(f"[启动] 缩略图清理调度失败: {e}")

    def _run_thumbnail_cleanup(self, current_time: float) -> None:
        """执行缩略图缓存清理并记录本次清理时间。"""
        try:
            from freeassetfilter.core.managers.thumbnail_manager import clean_thumbnails

            deleted_count, remaining_count = clean_thumbnails(cleanup_period_days=7)
            info(f"[启动] 缩略图缓存清理完成: 删除 {deleted_count} 个文件，剩余 {remaining_count} 个文件")
        except Exception as e:
            warning(f"缩略图缓存清理失败: {e}")
        finally:
            try:
                sm = getattr(self.app, "settings_manager", None)
                if sm is not None:
                    sm.set("file_selector.last_cleanup_time", current_time)
                    sm.save()
            except Exception as e:
                warning(f"更新清理时间失败: {e}")

    # ── 后台预热 ────────────────────────────────────────────────

    def _start_background_warmup(self) -> None:
        """启动后台预热任务（投递到全局线程池）。"""
        if self._warmup_thread is not None and not self._warmup_thread.is_done:
            return
        self._warmup_thread = StartupWarmupThread()
        self._warmup_thread.finished.connect(self._on_warmup_finished)
        QThreadPool.globalInstance().start(self._warmup_thread)

    def _on_warmup_finished(self) -> None:
        info("[预热] 启动阶段后台预热任务结束")

    # ── 退出清理 ────────────────────────────────────────────────

    def cleanup(self) -> None:
        """退出前停止心跳并等待预热任务完成（有界 2 秒）。"""
        if self._heartbeat is not None:
            try:
                self._heartbeat.stop_all()
            except Exception as e:
                warning(f"[退出] 心跳停止失败: {e}")

        if self._warmup_thread is not None and not self._warmup_thread.is_done:
            try:
                if not self._warmup_thread.wait(2000):
                    warning("[退出] 预热任务未在 2 秒内完成")
            except Exception as e:
                warning(f"[退出] 预热任务清理失败: {e}")


__all__ = [
    "StartupWarmupThread",
    "StartupController",
]
