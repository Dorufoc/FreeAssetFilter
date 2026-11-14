"""启动前待安装更新处理。

关于页自动下载完成并登记 ``pending_update.json`` 后，下次启动在创建主窗口
之前调用 :func:`handle_pending_update`：校验安装包并直接拉起安装器。

本模块刻意保持轻量：没有待安装更新时不会导入 Qt/更新服务，也不会触碰
网络；失败一律降级为原生提示并继续正常启动，绝不让更新阻断应用。
"""

from __future__ import annotations

import ctypes
import sys

from sopeek.services.update_pending import apply_pending_update
from sopeek.utils.app_logger import info, warning


def _show_failure(detail: str) -> None:
    """用原生 MessageBox 提示待安装更新启动失败。"""
    message = (
        f"更新安装未能启动：{detail}\n\n"
        "本次将正常启动当前版本；更新包已保留，可稍后重新检查更新。"
    )
    try:
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(
                None, message, "Sopeek 更新", 0x30
            )
    except Exception as exc:  # noqa: BLE001 - 提示失败不阻断启动
        warning(f"显示待安装更新失败提示失败：{exc!r}")


def handle_pending_update() -> bool:
    """处理启动前待安装更新。

    Returns:
        bool: ``True`` 表示安装器已成功拉起，调用方应立即退出当前进程；
        ``False`` 表示没有待安装更新或启动失败，继续正常启动。
    """
    try:
        result = apply_pending_update()
    except Exception as exc:  # noqa: BLE001 - 启动路径不允许更新组件阻断
        warning(f"处理待安装更新失败：{exc!r}")
        return False

    if result.launched:
        info("[更新] 已拉起待安装更新，当前进程退出以完成安装")
        return True
    if result.detail:
        warning(f"[更新] 待安装更新未能启动：{result.detail}")
        _show_failure(result.detail)
    return False
