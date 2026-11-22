# -*- coding: utf-8 -*-
"""系统托盘控制器。

职责：封装 :class:`QSystemTrayIcon` 的创建、右键菜单与生命周期管理，向宿主
窗口只暴露两个信号——「打开主界面」（``open_requested``）与「彻底退出」
（``quit_requested``）。本模块不持有、也不查询主窗口引用，宿主自行连接信号。

托盘不可用时（例如无桌面会话、远程终端、系统未提供托盘区）安全降级：
内部托盘对象置 ``None``，仅记录 warning 日志，构造不抛异常，``show`` /
``hide`` / ``dispose`` 全部变成无操作，宿主无需额外判空。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QSystemTrayIcon

from sopeek._paths import icons_dir
from sopeek.ui.components.styled_context_menu import StyledContextMenu
from sopeek.utils.app_logger import warning


class TrayController(QObject):
    """可复用的系统托盘控制器。

    宿主只需连接两个信号即可，不依赖主窗口类型：

    Attributes:
        open_requested: 用户双击托盘图标或点击「打开主界面」时发出。
        quit_requested: 用户点击「彻底退出」时发出。

    Usage::

        tray = TrayController(parent=window)
        tray.open_requested.connect(window.show_and_activate)
        tray.quit_requested.connect(window.really_quit)
        tray.show()
        ...
        tray.dispose()
    """

    open_requested = Signal()
    quit_requested = Signal()

    def __init__(
        self,
        parent: Optional[QObject] = None,
        icon_path: Optional[str] = None,
    ) -> None:
        """创建托盘图标、右键菜单并连接激活信号。

        Args:
            parent: Qt 父对象；传入主窗口可让托盘随窗口生命周期回收。
            icon_path: 托盘图标路径；为空时使用
                :func:`sopeek._paths.icons_dir` 下的 ``SPK-main.ico``。
        """
        super().__init__(parent)
        self._tray: Optional[QSystemTrayIcon] = None
        self._menu: Optional[StyledContextMenu] = None

        if not QSystemTrayIcon.isSystemTrayAvailable():
            warning("系统托盘不可用，TrayController 已降级为无操作模式")
            return

        tray = QSystemTrayIcon(self._load_icon(icon_path), self)
        tray.setToolTip("Sopeek")

        # QMenu 的 parent 只能是 QWidget（托盘与控制器都是纯 QObject），
        # 且 QSystemTrayIcon 不接管菜单所有权，故不设 parent，改为保存为
        # 实例属性防 GC——否则右键会落到已销毁的 C++ 对象上。
        menu = StyledContextMenu()
        menu.add_item("打开主界面", callback=self.open_requested.emit)
        menu.add_separator()
        menu.add_item("彻底退出", callback=self.quit_requested.emit)
        tray.setContextMenu(menu)

        tray.activated.connect(self._on_activated)

        self._menu = menu
        self._tray = tray

    # ── 内部辅助 ─────────────────────────────────────────────────────

    def _load_icon(self, icon_path: Optional[str]) -> QIcon:
        """加载托盘图标；文件缺失或图标为空时只告警，不中断创建。

        Args:
            icon_path: 外部指定的图标路径，可为 ``None``。

        Returns:
            QIcon: 可能为空图标（``QIcon.isNull()`` 为 True）。
        """
        path = Path(icon_path) if icon_path else icons_dir() / "SPK-main.ico"
        if not path.is_file():
            warning(f"托盘图标文件不存在：{path}")

        icon = QIcon(str(path))
        if icon.isNull():
            warning(f"托盘图标加载失败（QIcon 为空）：{path}")
        return icon

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """仅在双击时请求打开主界面（单击 Trigger 易误触，不响应）。"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_requested.emit()

    # ── 公开接口 ─────────────────────────────────────────────────────

    @property
    def is_available(self) -> bool:
        """托盘是否处于可用状态（不可用或已释放时为 False）。"""
        return self._tray is not None

    @property
    def menu(self) -> Optional[StyledContextMenu]:
        """右键菜单实例（托盘不可用时为 None，测试用）。"""
        return self._menu

    def show(self) -> None:
        """显示托盘图标；托盘不可用时无操作。"""
        if self._tray is None:
            return
        try:
            self._tray.show()
        except RuntimeError:
            # C++ 对象已被销毁（例如宿主提前回收父对象）。
            self._tray = None

    def hide(self) -> None:
        """隐藏托盘图标；托盘不可用时无操作。"""
        if self._tray is None:
            return
        try:
            self._tray.hide()
        except RuntimeError:
            self._tray = None

    def dispose(self) -> None:
        """释放托盘与菜单资源，可重复调用（幂等）。

        先置空内部引用再操作 C++ 对象，确保中途异常也不会留下半初始化状态；
        已销毁对象抛出的 ``RuntimeError`` 一律吞掉。
        """
        tray = self._tray
        menu = self._menu
        self._tray = None
        self._menu = None

        if tray is not None:
            try:
                tray.hide()
            except RuntimeError:
                pass
            try:
                tray.activated.disconnect(self._on_activated)
            except (RuntimeError, TypeError):
                pass
            try:
                tray.setContextMenu(None)
            except (RuntimeError, TypeError):
                pass

        if menu is not None:
            try:
                menu.close()
            except RuntimeError:
                pass
            menu.deleteLater()

        if tray is not None:
            tray.deleteLater()
