"""检查更新入口控制器。

主窗口标题栏与设置页「关于」页共用本控制器：同一个在途检查、同一个单弹窗
（:class:`~freeassetfilter.ui.layout.update_dialogs.UpdateCenterDialog`）、
同一份结果。

职责边界：

* 只编排 UI 状态与 ``UpdateService`` 请求关联，不解析 NDJSON、不碰窗口；
* 只处理 ``manual=True`` 的检查结果，启动自动检查仍走 ``StartupController``；
* 检查阶段在单弹窗内切换（检查中 → 已是最新 / 发现新版本 / 检查失败），
  下载阶段交给既有的 ``show_download_progress`` 独立弹窗。

``update_dialogs`` / ``get_update_service`` / ``get_local_version`` 均在方法内
导入，避免首屏加载更新栈。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QTimer

from freeassetfilter.services.update_service import UpdateError

#: 检查中弹窗的最小展示时长（毫秒），避免检查瞬间完成时弹窗只闪一下。
MIN_CHECKING_VISIBLE_MS = 250


class UpdateEntryController(QObject):
    """两个入口共享的检查更新编排器。

    Attributes:
        MIN_CHECKING_VISIBLE_MS: 检查中状态的最短展示时长（毫秒）。
    """

    MIN_CHECKING_VISIBLE_MS = MIN_CHECKING_VISIBLE_MS

    def __init__(
        self,
        service_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        """初始化控制器并订阅更新服务的检查信号。

        必须在 GUI 主线程构造（``UpdateService`` 自身有同样的约束）。

        Args:
            service_factory: 可注入的服务工厂（测试用）；省略时使用
                :func:`freeassetfilter.services.update_service.get_update_service`。
        """
        super().__init__()
        self._service_factory = service_factory
        self._service: Any = None
        self._request_id: Optional[str] = None
        self._busy = False
        self._pending_claim = False
        self._dialog: Any = None
        self._checking_shown_at = 0.0
        self._disposed = False
        self._subscribe()

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------

    def request_check(self) -> None:
        """发起或加入一次手动检查，并在弹窗内展示检查状态。

        两个入口（标题栏 / 关于页）唯一调用点。重复调用只把已有弹窗前置，
        不会重复派发检查。
        """
        if self._disposed:
            return
        if self._busy:
            if self._dialog is None:
                self._show_checking()
            else:
                self._present_dialog()
            return

        service = self._ensure_service()
        if service is None:
            self._show_error(UpdateError("unavailable"))
            return

        try:
            available = bool(service.is_available())
        except Exception:  # noqa: BLE001 - 探测失败按不可用处理
            available = False
        if not available:
            self._show_error(UpdateError("unavailable"))
            return

        self._busy = True
        self._pending_claim = True
        self._show_checking()
        try:
            request_id = service.check(manual=True)
        except Exception:  # noqa: BLE001 - 派发失败给出可重试错误
            self._finish()
            self._show_error(UpdateError("internal"))
            return
        # 启动检查在途时服务不会补发 check_started，用返回值补齐请求 id。
        if self._request_id is None:
            self._request_id = request_id

    def dispose(self) -> None:
        """关闭弹窗、断开订阅并标记控制器不可用（幂等）。"""
        if self._disposed:
            return
        self._disposed = True
        self._close_dialog()
        service = self._service
        if service is None:
            return
        for signal_name, slot in (
            ("check_started", self._on_check_started),
            ("check_finished", self._on_check_finished),
        ):
            signal = getattr(service, signal_name, None)
            if signal is None:
                continue
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                continue

    # ------------------------------------------------------------------
    # 服务关联
    # ------------------------------------------------------------------

    def _subscribe(self) -> None:
        """连接更新服务的检查信号（服务不可用时静默跳过）。"""
        service = self._ensure_service()
        if service is None:
            return
        try:
            service.check_started.connect(self._on_check_started)
            service.check_finished.connect(self._on_check_finished)
        except (AttributeError, RuntimeError, TypeError):
            return

    def _ensure_service(self) -> Any:
        """惰性取得更新服务；失败时返回 ``None``。"""
        if self._service is not None:
            return self._service
        try:
            if self._service_factory is not None:
                self._service = self._service_factory()
            else:
                from freeassetfilter.services.update_service import get_update_service

                self._service = get_update_service()
        except Exception:  # noqa: BLE001 - 服务不可用降级为错误弹窗
            self._service = None
        return self._service

    def _on_check_started(self, request_id: str, manual: bool) -> None:
        """认领本入口发起的手动检查请求 id。

        ``manual=False`` 的启动检查与「非本入口发起」的手动检查都不认领。

        Args:
            request_id: 服务分配的检查请求 id。
            manual: 是否手动检查。
        """
        if self._disposed or not manual or not self._pending_claim:
            return
        self._request_id = request_id

    def _on_check_finished(
        self,
        request_id: str,
        manual: bool,
        info: object,
        error: object,
    ) -> None:
        """按请求 id 过滤并应用检查结果。

        Args:
            request_id: 服务回传的请求 id。
            manual: 是否手动检查。
            info: ``UpdateInfo`` 或 ``None``。
            error: ``UpdateError`` 或 ``None``。
        """
        if self._disposed or not manual:
            return
        if self._request_id is None or request_id != self._request_id:
            return
        self._request_id = None

        delay_ms = self._remaining_checking_ms()
        if delay_ms > 0:
            QTimer.singleShot(delay_ms, lambda: self._apply_result(info, error))
        else:
            self._apply_result(info, error)

    def _remaining_checking_ms(self) -> int:
        """返回检查中状态还需保持的最小展示时长（毫秒）。"""
        if self._checking_shown_at <= 0.0:
            return 0
        elapsed_ms = (time.monotonic() - self._checking_shown_at) * 1000.0
        return max(0, int(self.MIN_CHECKING_VISIBLE_MS - elapsed_ms))

    def _apply_result(self, info: object, error: object) -> None:
        """把检查结果写入弹窗并复位忙闲状态。

        Args:
            info: ``UpdateInfo`` 或 ``None``。
            error: ``UpdateError`` 或 ``None``。
        """
        if self._disposed:
            return
        self._finish()
        dialog = self._ensure_dialog()
        if dialog is None:
            return
        if error is not None:
            dialog.set_error(error)
        elif info is not None:
            dialog.set_result(info)
        else:
            dialog.set_error(UpdateError("internal"))
        self._present_dialog()

    def _finish(self) -> None:
        """复位忙闲与请求关联状态。"""
        self._busy = False
        self._pending_claim = False
        self._request_id = None
        self._checking_shown_at = 0.0

    # ------------------------------------------------------------------
    # 弹窗管理
    # ------------------------------------------------------------------

    def _show_checking(self) -> None:
        """渲染检查中状态并显示弹窗。"""
        dialog = self._ensure_dialog()
        if dialog is None:
            return
        from freeassetfilter.utils.version_info import get_local_version

        dialog.set_checking(get_local_version())
        self._checking_shown_at = time.monotonic()
        self._present_dialog()

    def _show_error(self, error: object) -> None:
        """渲染错误状态并显示弹窗。

        Args:
            error: ``UpdateError`` 实例。
        """
        dialog = self._ensure_dialog()
        if dialog is None:
            return
        dialog.set_error(error)
        self._present_dialog()

    def _ensure_dialog(self) -> Any:
        """返回单弹窗实例；不存在且未销毁时新建（不显示）。"""
        if self._dialog is not None:
            return self._dialog
        if self._disposed:
            return None
        try:
            from freeassetfilter.ui.layout.update_dialogs import UpdateCenterDialog

            dialog = UpdateCenterDialog(
                on_download=self._on_download,
                on_retry=self.request_check,
            )
            dialog.finished.connect(self._on_dialog_finished)
        except Exception:  # noqa: BLE001 - 弹窗构建失败不应拖垮入口
            return None
        self._dialog = dialog
        return dialog

    def _present_dialog(self) -> None:
        """显示弹窗；已可见时前置并激活。"""
        dialog = self._dialog
        if dialog is None:
            return
        try:
            if not dialog.isVisible():
                dialog.show_dialog()
            else:
                dialog.raise_()
                dialog.activateWindow()
        except RuntimeError:
            self._dialog = None

    def _close_dialog(self) -> None:
        """关闭并销毁当前弹窗（幂等）。"""
        dialog = self._dialog
        self._dialog = None
        if dialog is None:
            return
        try:
            dialog.close_dialog()
        except RuntimeError:
            return
        try:
            dialog.deleteLater()
        except RuntimeError:
            pass

    def _on_dialog_finished(self, _result: int = 0) -> None:
        """弹窗关闭后清空引用（不取消正在进行的检查）。

        Args:
            _result: ``finished`` 信号的结果码（未使用）。
        """
        dialog = self._dialog
        if dialog is None:
            return
        self._dialog = None
        try:
            dialog.deleteLater()
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # 下载 / 重试
    # ------------------------------------------------------------------

    def _on_download(self, info: object) -> None:
        """关闭检查弹窗并把下载交给既有进度弹窗。

        Args:
            info: ``UpdateInfo`` 快照。
        """
        if self._disposed:
            return
        service = self._service
        if service is None:
            self._show_error(UpdateError("unavailable"))
            return
        self._close_dialog()
        try:
            from freeassetfilter.ui.layout import update_dialogs

            update_dialogs.show_download_progress(info, service)
        except Exception:  # noqa: BLE001 - 下载入口失败给出可读错误
            self._show_error(UpdateError("internal"))


# ----------------------------------------------------------------------
# 单例
# ----------------------------------------------------------------------

_controller: Optional[UpdateEntryController] = None
_controller_lock = threading.Lock()


def get_update_entry_controller(
    service_factory: Optional[Callable[[], Any]] = None,
) -> UpdateEntryController:
    """返回共享控制器；已销毁时重新创建。

    Args:
        service_factory: 仅在新创建时使用的服务工厂（测试用）。

    Returns:
        UpdateEntryController: 进程内唯一实例。
    """
    global _controller
    with _controller_lock:
        if _controller is None or _controller._disposed:
            _controller = UpdateEntryController(service_factory=service_factory)
        return _controller


def reset_update_entry_controller() -> None:
    """销毁并清空共享控制器（测试与退出清理使用，幂等）。"""
    global _controller
    with _controller_lock:
        controller = _controller
        _controller = None
    if controller is not None:
        controller.dispose()
