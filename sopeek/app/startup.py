#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sopeek 启动阶段任务编排（startup）
--------------------------------------------
自引导层（``sopeek/app/main.py``）拆分出的首帧后任务：

  - ``StartupWarmupThread``：后台预热 FFmpeg 工具链，避免阻塞首屏
  - ``StartupController``：首帧后分阶段调度（心跳、附加字体注册、AVIF
    图标缓存清理、缩略图缓存清理、启动更新检查）

说明：静默更新检查已由 Rust native updater 恢复——首帧 3 秒后按
``update_startup`` 的策略（环境变量门控 / 设置开关 / 24 小时节流）发起
一次非阻塞检查，并在发现新版本时弹出启动提示。下载 / 安装引导仍由后续
更新流程负责；本模块各任务相互独立，失败仅记日志。

线程模型：``StartupWarmupThread`` 已从「run 即弃 QThread」重构为
``QRunnable`` 池任务（投递到 ``thread_pools.pool("background")``），
完成信号经主线程持有的 ``_StartupWarmupSignals`` 中转对象跨线程投递；
退出等待语义经内部 ``threading.Event`` 保持（cleanup 有界等待 2s）。
"""

from __future__ import annotations

import os
import threading
import time
import traceback
from typing import Any, Optional

from PySide6.QtCore import QObject, QRunnable, QTimer, Qt, Signal

# 注：`sopeek.core.pools` 在 `_start_background_warmup` 内延迟导入，
# 避免把 Qt 池/ctypes 初始化拉到「进程→首帧」的关键路径上。
from sopeek.utils.app_logger import debug, error, info, warning
from sopeek.utils.path_utils import get_resource_path


class _StartupWarmupSignals(QObject):
    """预热任务完成信号中转（主线程持有，跨线程队列投递）。"""

    finished = Signal()


class StartupWarmupThread(QRunnable):
    """启动后后台预热任务：FFmpeg 工具链。

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
        # P6.3：协作式取消标记（预热子步骤在下一步开始前检查）。
        self._cancelled = threading.Event()

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

    def cancel(self) -> None:
        """请求取消预热（已开始的子步骤不可中断，仅阻止后续步骤）。"""
        self._cancelled.set()

    def run(self):
        try:
            self._warm_ffmpeg()
        finally:
            self._done.set()
            self._signals.finished.emit()

    def _warm_ffmpeg(self) -> None:
        if self._cancelled.is_set():
            return
        try:
            from sopeek.core.native.bridges.media_probe import (
                warmup_ffmpeg_tools,
            )

            warmup_ffmpeg_tools()
        except Exception as e:
            error(f"FFmpeg 预热失败: {e}")


class StartupController(QObject):
    """引导层启动任务编排器（全部经 QTimer 调度到主线程）。"""

    def __init__(self, app, window) -> None:
        super().__init__()
        self.app = app
        self.window = window
        self._heartbeat = None
        self._warmup_thread = None
        self._update_signal_connected = False

    # ── 调度入口 ────────────────────────────────────────────────

    def schedule_startup_tasks(self) -> None:
        """在首屏显示后分阶段执行启动任务，避免阻塞窗口显示。"""
        try:
            from sopeek.core.managers.heartbeat_manager import HeartbeatManager

            self._heartbeat = HeartbeatManager()
        except Exception as e:
            error(f"[启动] 心跳管理器创建失败: {e}")

        QTimer.singleShot(0, self._safe("_register_extra_fonts"))
        # P6.2/P7.2：这两项都会导入重模块或跑 FFI（pools 导入 ~20ms、预算补应用
        # 含 set_cache_limit），放在面板构建（0/30/60/90ms 网格）期间会推迟
        # 四区齐备与覆盖层淡出。延到面板构建完后再跑，与首次交互并行。
        QTimer.singleShot(200, self._safe("_start_background_warmup"))
        QTimer.singleShot(0, self._safe("_cleanup_icon_cache"))
        QTimer.singleShot(400, self._safe("_reapply_memory_budget"))
        QTimer.singleShot(100, self._safe("_schedule_thumbnail_cleanup"))
        QTimer.singleShot(3000, self._safe("_maybe_check_updates"))

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

    def _reapply_memory_budget(self) -> None:
        """首帧后补齐内存预算（P7.2）。

        启动早期只能给**已导入**模块打补丁；主窗口构造后图标/缩略图模块已就位，
        此时再跑一次 `apply()` 只做常量赋值（实测 <10ms），不会拖慢首屏。
        """
        try:
            from sopeek.core.memory_budget import get_memory_budget

            result = get_memory_budget().apply(None)
            debug(f"[启动] 预算补应用: applied={result.get('applied')}")
        except Exception as exc:  # noqa: BLE001 - 预算补应用失败不阻塞启动
            warning(f"[启动] 预算补应用失败: {exc}")

    # ── 附加字体与可选插件 ──────────────────────────────────────

    def _register_extra_fonts(self) -> None:
        """注册 FiraCode（代码高亮字体；注册后可按 family 名使用）。

        不再改写全局应用字体：全局字体保持 Qt 默认。
        """
        from PySide6.QtGui import QFontDatabase

        firacode_font_path = get_resource_path("sopeek/icons/FiraCode-VF.ttf")
        if not os.path.exists(firacode_font_path):
            return
        try:
            QFontDatabase.addApplicationFont(firacode_font_path)
        except Exception as e:
            warning(f"[启动] FiraCode 注册失败: {e}")

    # ── 缓存清理 ────────────────────────────────────────────────

    def _cleanup_icon_cache(self) -> None:
        """启动阶段磁盘图标缓存清理（最旧优先双阈值）。"""
        try:
            from sopeek.utils.icon_utils import cleanup_icon_cache

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
                QTimer.singleShot(0, lambda: self._run_thumbnail_cleanup(now, cleanup_period))
        except Exception as e:
            warning(f"[启动] 缩略图清理调度失败: {e}")

    def _run_thumbnail_cleanup(self, current_time: float, cleanup_period_days: int = 7) -> None:
        """执行缩略图缓存清理并记录本次清理时间。

        Args:
            current_time: 本次清理时间戳（写回 ``last_cleanup_time``）。
            cleanup_period_days: 清理周期（天），由
                :meth:`_schedule_thumbnail_cleanup` 从
                ``file_selector.cache_cleanup_period`` 读取后传入——
                修复此前硬编码 7 天导致配置项实际不生效的问题。
        """
        try:
            from sopeek.core.managers.thumbnail_manager import clean_thumbnails

            deleted_count, remaining_count = clean_thumbnails(
                cleanup_period_days=cleanup_period_days
            )
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
        # P6.2：池模块略带 Qt/ctypes 初始化开销（~20ms），放到真正需要它的
        # 预热回调里导入，不占用“进程→首帧”的关键路径。
        from sopeek.core import pools as thread_pools

        thread_pools.pool("background").start(self._warmup_thread)

    def _on_warmup_finished(self) -> None:
        info("[预热] 启动阶段后台预热任务结束")

    # ── 启动更新检查 ────────────────────────────────────────────

    def _maybe_check_updates(self) -> None:
        """按启动策略发起一次非阻塞更新检查，并接好启动提示。

        更新服务与对话框模块均惰性导入，避免拖慢首屏。信号必须在检查
        之前连接（且只连一次），这样即使服务在 ``maybe_startup_check``
        内同步发出信号也不会漏掉通知。
        """
        from sopeek.services.update_service import get_update_service

        service = get_update_service()
        if service is None:
            return

        if not self._update_signal_connected:
            service.startup_update_available.connect(
                self._on_startup_update_available, Qt.QueuedConnection
            )
            self._update_signal_connected = True

        service.maybe_startup_check(self.window)

    def _on_startup_update_available(self, info: Any) -> None:
        """把启动检查发现的新版本交给启动提示对话框。"""
        from sopeek.ui.layout import update_dialogs

        update_dialogs.show_startup_update(self.window, info)

    # ── 退出清理 ────────────────────────────────────────────────

    def cleanup(self) -> None:
        """退出前停止心跳、等待预热任务并停止已存在的更新服务（有界 2 秒）。"""
        if self._heartbeat is not None:
            try:
                self._heartbeat.stop_all()
            except Exception as e:
                warning(f"[退出] 心跳停止失败: {e}")

        if self._warmup_thread is not None and not self._warmup_thread.is_done:
            try:
                # P6.3：退出路径只给 300ms；预热子步骤不可中断，超时即放弃
                # （线程池为守护语义，不阻塞进程退出）。
                self._warmup_thread.cancel()
                if not self._warmup_thread.wait(300):
                    warning("[退出] 预热任务未在 300ms 内完成，已放弃等待")
                    try:
                        from sopeek.utils import perf_metrics as pm

                        pm.increment_global("startup.warmup_abandoned")
                    except Exception:  # noqa: BLE001 - 埋点不得影响退出
                        pass
            except Exception as e:
                warning(f"[退出] 预热任务清理失败: {e}")

        # 退出路径只触碰已存在的服务：get_update_service() 会构造新实例，
        # 既可能拉起原生 updater，也可能让退出多等数秒。
        try:
            from sopeek.services.update_service import (
                get_update_service_if_exists,
            )

            service = get_update_service_if_exists()
            if service is not None:
                service.shutdown(timeout=2.0)
        except Exception as e:
            warning(f"[退出] 更新服务停止失败: {e}")


__all__ = [
    "StartupWarmupThread",
    "StartupController",
]
