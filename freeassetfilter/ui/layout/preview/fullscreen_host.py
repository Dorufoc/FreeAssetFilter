"""
全屏宿主窗口 — 将内嵌的 previewer layout 分离到独立 frameless 全屏窗口

背景：新版 preview layout（font / image / pdf / text / video）内嵌在主窗口
（UnifiedPreviewerLayout → MainWindow._panel_right）时，旧实现直接调用
``self.window().showFullScreen()``，而 ``window()`` 返回的是主窗口
（FramelessMainWindow），导致整个主窗口被无边框全屏化。

本模块提供 ``PreviewFullscreenHost``：一个 frameless 顶层 QWidget，把
previewer 从原父布局中摘除后 attach 进来，再以无边框方式 showFullScreen()；
退出时 detach 还原到原父布局的原位置。全屏因此只作用于预览器自身。
"""

from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent, QWindow
from PySide6.QtWidgets import QApplication, QLayout, QVBoxLayout, QWidget


class PreviewFullscreenHost(QWidget):
    """承载 previewer layout 的独立 frameless 全屏窗口。

    用法：
        1. ``host.attach(widget)`` 把 widget 从当前父布局摘除并移入宿主；
        2. ``host.showFullScreen()`` 以无边框方式全屏；
        3. ``host.exit_fullscreen()`` 把 widget 还原到原父布局并隐藏宿主。
        4. 用户按 Esc 会发出 ``escapePressed``；宿主被系统关闭（Alt+F4 等）
           会先自动还原内容，再发出 ``closed``。

    Signals:
        escapePressed: 用户在宿主窗口内按下 Esc。
        closed: 宿主窗口被关闭（内容已自动还原）。
        activated_changed: 窗口激活状态变化（True=获得激活，False=失去激活）。
            用于全屏宿主失焦时通知外部立即隐藏浮动控制栏。
    """

    escapePressed = Signal()
    closed = Signal()
    activated_changed = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setFocusPolicy(Qt.StrongFocus)

        self._content: Optional[QWidget] = None
        self._orig_parent: Optional[QWidget] = None
        self._orig_layout: Optional[QLayout] = None
        self._orig_index: int = -1
        self._active_watched = False
        # 持续焦点守卫状态：原顶层窗口（main window）引用 + 是否已连接信号
        self._main_window: Optional[QWidget] = None
        self._focus_guard_active = False

        self._host_layout = QVBoxLayout(self)
        self._host_layout.setContentsMargins(0, 0, 0, 0)
        self._host_layout.setSpacing(0)

    # ── 公共 API ──

    @property
    def content(self) -> Optional[QWidget]:
        """当前承载的 widget，未承载时为 None。"""
        return self._content

    def attach(self, widget: Optional[QWidget]) -> bool:
        """把 widget 从当前父布局摘除并移入宿主。

        记录原父控件 / 原布局 / 原索引，退出全屏时还原。
        宿主已有内容时返回 False（不覆盖）。

        Args:
            widget: 要承载的 previewer widget。

        Returns:
            bool: 是否成功挂载。
        """
        if self._content is not None or widget is None:
            return False
        self._orig_parent = widget.parentWidget()
        if self._orig_parent is not None:
            parent_layout = self._orig_parent.layout()
            if parent_layout is not None:
                self._orig_layout = parent_layout
                self._orig_index = parent_layout.indexOf(widget)
        # 记录原顶层窗口（内嵌时即 main window），供全屏期间持续焦点守卫使用。
        # 必须在摘除 widget 之前取 window()，否则 window() 会返回宿主自身。
        if self._orig_parent is not None:
            self._main_window = self._orig_parent.window()
        widget.setParent(self)
        self._host_layout.addWidget(widget)
        self._content = widget
        return True

    def detach(self) -> None:
        """把内容还原到原父布局的原位置，并清空宿主。"""
        if self._content is None:
            return
        widget = self._content
        self._host_layout.removeWidget(widget)
        if self._orig_layout is not None and self._orig_parent is not None:
            if self._orig_index >= 0:
                self._orig_layout.insertWidget(self._orig_index, widget)
            else:
                self._orig_layout.addWidget(widget)
        else:
            widget.setParent(self._orig_parent)
        self._content = None
        self._orig_parent = None
        self._orig_layout = None
        self._orig_index = -1

    def show_fullscreen(self) -> None:
        """以无边框方式全屏显示，并把焦点转移到本窗口。

        全屏窗口由主窗口（持有焦点）触发创建时，Windows 可能不会自动
        把激活状态交还给新窗口；这里显式 ``raise_`` + ``activateWindow``
        并把应用活动窗口设为本窗口，保证：
            1. 分离全屏窗口获得键盘焦点（Esc / 翻页等事件送达宿主）；
            2. 分离全屏窗口位于主窗口之上。
        """
        self.showFullScreen()
        self._activate_window()
        # Windows 上窗口激活是异步请求，首次调用可能被窗口系统忽略
        # （应用刚从主窗口切换前台）；事件循环后再激活一次，
        # 确保焦点最终落在宿主上、宿主位于主窗口之上。
        QTimer.singleShot(0, self._activate_window)
        # 监听窗口激活状态变化（QWindow 句柄需在窗口显示后才可用）
        QTimer.singleShot(0, self._watch_active_state)
        # 全屏期间持续焦点守卫：main window 抢回焦点时自动交还给宿主
        self._start_focus_guard()

    def _start_focus_guard(self) -> None:
        """连接应用级焦点信号，全屏期间守卫 main window 抢焦点。

        事件驱动（QGuiApplication.focusWindowChanged），无轮询开销：
        main window 获得焦点时把焦点交还给宿主，保证分离窗口持续
        位于 main window 之上；焦点落在其他窗口时不打断用户操作。
        """
        if self._focus_guard_active:
            return
        app = QApplication.instance()
        if app is None:
            return
        app.focusWindowChanged.connect(self._on_focus_window_changed)
        self._focus_guard_active = True

    def _stop_focus_guard(self) -> None:
        """断开焦点守卫连接并清空 main window 引用。"""
        if self._focus_guard_active:
            app = QApplication.instance()
            if app is not None:
                try:
                    app.focusWindowChanged.disconnect(
                        self._on_focus_window_changed
                    )
                except (RuntimeError, TypeError):
                    # 信号可能已被整体断开（如应用关闭），忽略即可
                    pass
            self._focus_guard_active = False
        self._main_window = None

    def _on_focus_window_changed(self, focus_window: Optional[QWindow]) -> None:
        """焦点窗口变化：main window 获得焦点时把焦点交还给宿主。

        Args:
            focus_window: 当前获得焦点的顶层窗口；无焦点窗口时为 None。
        """
        try:
            if not self.isVisible() or not self.isFullScreen():
                return
            main = self._main_window
            if main is None or main.windowHandle() is None:
                return
            if focus_window is None or focus_window != main.windowHandle():
                return
        except RuntimeError:
            # main window 已被销毁（应用退出流程等），忽略该次焦点事件
            return
        # 焦点确实回到了 main window：延迟一拍再激活宿主。
        # 避免在信号处理栈内直接切换前台引起的时序问题，也让 Windows
        # 前台切换稳定后再次 raise_ + activateWindow 保证置顶。
        QTimer.singleShot(0, self._activate_window)

    def _watch_active_state(self) -> None:
        """连接 QWindow.activeChanged，转发为 activated_changed 信号。"""
        if self._active_watched:
            return
        handle = self.windowHandle()
        if handle is not None:
            self._active_watched = True
            # QWindow.activeChanged 是 C++ 无参信号，这里查询当前激活状态再转发
            handle.activeChanged.connect(
                lambda: self._on_active_changed(self.isActiveWindow())
            )

    def _on_active_changed(self, active: bool) -> None:
        """QWindow 激活状态变化 → 转发信号。"""
        self.activated_changed.emit(active)

    def _activate_window(self) -> None:
        """把焦点与顶层 Z 序交给本窗口。"""
        self.raise_()
        self.activateWindow()
        window = self.windowHandle()
        if window is not None:
            window.requestActivate()
        self.setFocus(Qt.ActiveWindowFocusReason)

    def exit_fullscreen(self) -> None:
        """退出全屏：还原内容到原父布局并隐藏宿主。"""
        self._stop_focus_guard()
        self.detach()
        self.hide()

    # ── 事件处理 ──

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape:
            self.escapePressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        # 宿主被系统关闭时先把内容还原，避免 widget 随宿主一起销毁
        self.exit_fullscreen()
        self.closed.emit()
        event.accept()
