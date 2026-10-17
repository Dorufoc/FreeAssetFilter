# -*- coding: utf-8 -*-
"""GUI 视觉测试：全局浮窗真实显示器用例。

覆盖两点（计划 Todo 7 (c) / Metis 发现 #22/#23）：

* 真实拖入临时文件到浮窗 → ``add_file_requested`` 发射（文件信息可由
  ``StagingPoolService`` 构建）；
* 浮窗为 ``Qt.Tool`` 顶层窗口，Windows 下其扩展样式位含
  ``WS_EX_TOOLWINDOW``（不出现在任务栏）。

约定（tests/gui/conftest.py）：每个测试函数显式依赖 session 级 ``qapp``；
文件级 ``pytestmark = pytest.mark.gui``。无真实显示器（``offscreen`` 平台）
或非 Windows 时优雅跳过——``WS_EX_TOOLWINDOW`` 是 Windows 专有语义。
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from typing import Any, List

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

# 浮窗模块内部使用短路径导入（from theme import tm / components.*）：
# 需把 freeassetfilter/ui 置于 sys.path（与其他 UI 测试模块同约定）。
_UI_ROOT: str = str(Path(__file__).resolve().parents[2] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

pytestmark = pytest.mark.gui

#: ``GetWindowLongPtrW`` 的扩展样式索引与 ``WS_EX_TOOLWINDOW`` 位。
_GWL_EXSTYLE: int = -20
_WS_EX_TOOLWINDOW: int = 0x00000080


def _display_available() -> bool:
    """判定是否具备真实显示器（非 offscreen 平台）。

    Returns:
        bool: 平台非 ``offscreen`` 时返回 True。
    """
    return QApplication.platformName() != "offscreen"


def _extended_window_style(hwnd: int) -> int:
    """读取指定窗口的扩展样式位（``GWL_EXSTYLE``）。

    Args:
        hwnd: 窗口句柄（``int(floating.winId())``）。

    Returns:
        int: 扩展样式位掩码。
    """
    user32 = ctypes.windll.user32
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    return int(user32.GetWindowLongPtrW(ctypes.c_void_p(hwnd), _GWL_EXSTYLE))


def test_floating_pool_drag_in_and_not_in_taskbar(
    qapp: Any, tmp_path: Path,
) -> None:
    """真实拖入临时文件 + 断言浮窗带 ``WS_EX_TOOLWINDOW``（不在任务栏）。"""
    if sys.platform != "win32":
        pytest.skip("WS_EX_TOOLWINDOW 为 Windows 专有语义，跳过非 Windows")
    if not _display_available():
        pytest.skip("需要真实显示器（offscreen 无法建立真实顶层窗口）")

    from freeassetfilter.ui.floating_pool_window import FloatingPoolWindow

    path = tmp_path / "gui_floating_drop.txt"
    path.write_text("gui", encoding="utf-8")

    floating = FloatingPoolWindow()
    received: List[dict] = []
    floating.add_file_requested.connect(received.append)
    try:
        floating.show()
        qapp.processEvents()

        # 不在任务栏：扩展样式含 WS_EX_TOOLWINDOW
        hwnd = int(floating.winId())
        assert hwnd != 0
        assert _extended_window_style(hwnd) & _WS_EX_TOOLWINDOW, (
            "浮窗缺少 WS_EX_TOOLWINDOW（会出现在任务栏）"
        )

        # 真实拖入：真实 dropEvent 路径（mime 引用存活至调用结束）
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        event = QDropEvent(
            QPointF(2, 2), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
        )
        floating.dropEvent(event)

        assert received, "拖入临时文件未发射 add_file_requested"
        assert any(
            Path(str(info.get("path"))).name == path.name for info in received
        )
    finally:
        floating.close()
        floating.deleteLater()
        qapp.processEvents()
