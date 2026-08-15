"""
PreviewFullscreenHost 单元测试

验证 freeassetfilter/ui/layout/preview/fullscreen_host.py 的 detach/reattach
行为：把 previewer widget 分离到独立 frameless 宿主窗口，退出时还原到原父布局。
"""

import sys
from pathlib import Path

# Match the sys.path bootstrap in preview layout modules so sibling imports work.
_UI_ROOT = str(Path(__file__).resolve().parents[5] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import QVBoxLayout, QWidget

from freeassetfilter.ui.layout.preview.fullscreen_host import PreviewFullscreenHost


class TestPreviewFullscreenHostAttachDetach:
    """attach / detach / exit_fullscreen 的核心行为。"""

    def test_attach_moves_widget_into_host(self, qapp) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        child = QWidget(container)
        layout.addWidget(child)

        host = PreviewFullscreenHost()
        assert host.attach(child) is True
        assert host.content is child
        assert child.parentWidget() is host
        assert layout.indexOf(child) == -1

    def test_exit_fullscreen_restores_widget_to_original_layout(self, qapp) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        child = QWidget(container)
        layout.addWidget(child)

        host = PreviewFullscreenHost()
        host.attach(child)
        host.exit_fullscreen()
        assert host.content is None
        assert child.parentWidget() is container
        assert layout.indexOf(child) == 0

    def test_exit_fullscreen_restores_original_index(self, qapp) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        first = QWidget(container)
        child = QWidget(container)
        layout.addWidget(first)
        layout.addWidget(child)

        host = PreviewFullscreenHost()
        host.attach(child)
        host.exit_fullscreen()
        assert layout.indexOf(child) == 1
        assert layout.indexOf(first) == 0

    def test_double_attach_rejected(self, qapp) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        child = QWidget(container)
        layout.addWidget(child)
        other = QWidget()

        host = PreviewFullscreenHost()
        assert host.attach(child) is True
        assert host.attach(other) is False, "host already has content"
        assert other.parentWidget() is None or other.parentWidget() is not host
        host.exit_fullscreen()

    def test_host_is_frameless_top_level_window(self, qapp) -> None:
        host = PreviewFullscreenHost()
        flags = host.windowFlags()
        assert flags & Qt.FramelessWindowHint
        assert flags & Qt.Window

    def test_show_fullscreen_activates_host(self, qapp) -> None:
        """进入全屏后宿主可见、全屏，并把应用活动窗口设为本窗口。

        主窗口持焦点时触发全屏，Windows 不会自动把激活状态交还给
        新窗口；show_fullscreen 必须显式转移焦点（activeWindow 指向宿主），
        保证键盘事件（Esc / 翻页）送达宿主且宿主位于主窗口之上。
        """
        host = PreviewFullscreenHost()
        host.show_fullscreen()
        # 窗口激活是异步请求，模拟事件循环处理
        qapp.processEvents()
        assert host.isVisible()
        assert host.isFullScreen()
        assert qapp.activeWindow() is host
        host.exit_fullscreen()


class TestPreviewFullscreenHostEvents:
    """Esc 键、非 Esc 键转发与关闭事件行为。"""

    def test_escape_emits_signal(self, qapp) -> None:
        host = PreviewFullscreenHost()
        received = []
        host.escapePressed.connect(lambda: received.append(True))
        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        host.keyPressEvent(event)
        assert received == [True]

    def test_non_escape_key_forwarded_to_content(self, qapp) -> None:
        """非 Esc 按键应被转发给承载的内容 widget（如 VideoPlayerLayout）。"""
        container = QWidget()
        layout = QVBoxLayout(container)
        child = QWidget(container)
        layout.addWidget(child)

        received = []

        def _child_key(event: QKeyEvent) -> None:
            received.append(event.key())
            event.accept()

        child.keyPressEvent = _child_key

        host = PreviewFullscreenHost()
        host.attach(child)
        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Space, Qt.NoModifier)
        host.keyPressEvent(event)
        assert received == [Qt.Key_Space]
        host.exit_fullscreen()

    def test_non_escape_key_forwarded_to_layout_presses(self, qapp) -> None:
        """转发后内容 widget 的按键处理应实际生效（模拟真实 VideoPlayerLayout）。"""
        container = QWidget()
        layout = QVBoxLayout(container)
        child = QWidget(container)
        layout.addWidget(child)

        pressed = []

        def _child_key(event: QKeyEvent) -> None:
            pressed.append(event.key())

        child.keyPressEvent = _child_key

        host = PreviewFullscreenHost()
        host.attach(child)
        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Right, Qt.NoModifier)
        host.keyPressEvent(event)
        assert pressed == [Qt.Key_Right]
        host.exit_fullscreen()

    def test_non_escape_key_without_content_does_not_crash(self, qapp) -> None:
        """无内容时非 Esc 按键走默认处理（不崩溃、不抛异常）。"""
        host = PreviewFullscreenHost()
        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Space, Qt.NoModifier)
        host.keyPressEvent(event)

    def test_key_not_forwarded_when_focus_on_content(self, qapp) -> None:
        """焦点已在内容 widget 上时不转发（避免按键二次投递回 content）。"""
        container = QWidget()
        layout = QVBoxLayout(container)
        child = QWidget(container)
        layout.addWidget(child)

        received = []

        def _child_key(event: QKeyEvent) -> None:
            received.append(event.key())

        child.keyPressEvent = _child_key
        child.setFocusPolicy(Qt.StrongFocus)

        host = PreviewFullscreenHost()
        host.attach(child)
        child.setFocus()
        qapp.processEvents()
        assert host.focusWidget() is child

        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Space, Qt.NoModifier)
        host.keyPressEvent(event)
        assert received == [], "焦点在 content 上时不应二次转发"
        host.exit_fullscreen()

    def test_close_event_restores_content_and_emits_closed(self, qapp) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        child = QWidget(container)
        layout.addWidget(child)

        host = PreviewFullscreenHost()
        host.attach(child)
        closed = []
        host.closed.connect(lambda: closed.append(True))
        host.closeEvent(QCloseEvent())
        assert closed == [True]
        assert host.content is None
        assert child.parentWidget() is container


class TestPreviewFullscreenHostFocusGuard:
    """持续焦点守卫：main window 抢回焦点时自动把焦点交还给宿主。

    offscreen 平台无法真实激活窗口，测试通过直接调用
    ``_on_focus_window_changed`` 并替换 ``_activate_window`` 断言触发行为。
    """

    def _setup(self) -> tuple:
        """构造 模拟 main window（container）+ 已 attach 的宿主。"""
        container = QWidget()
        layout = QVBoxLayout(container)
        child = QWidget(container)
        layout.addWidget(child)
        host = PreviewFullscreenHost()
        host.attach(child)
        return container, host

    def test_attach_records_original_top_level_window(self, qapp) -> None:
        """attach 后 _main_window 记录为原 parent 的顶层窗口。"""
        container, host = self._setup()
        assert host._main_window is container
        host.exit_fullscreen()

    def test_attach_records_nested_top_level_window(self, qapp) -> None:
        """内嵌多层时 _main_window 仍是最外层顶层窗口。"""
        container = QWidget()
        sub = QWidget(container)
        layout = QVBoxLayout(sub)
        child = QWidget(sub)
        layout.addWidget(child)
        host = PreviewFullscreenHost()
        host.attach(child)
        assert host._main_window is container
        host.exit_fullscreen()

    def test_focus_guard_returns_focus_when_main_window_focused(
        self, qapp, monkeypatch
    ) -> None:
        """焦点回到 main window → 守卫激活宿主。"""
        container, host = self._setup()
        container.show()
        qapp.processEvents()
        host.show_fullscreen()
        qapp.processEvents()
        assert host.isVisible() and host.isFullScreen()
        main_handle = container.windowHandle()
        assert main_handle is not None

        calls = []
        monkeypatch.setattr(host, "_activate_window", lambda: calls.append(True))
        host._on_focus_window_changed(main_handle)
        qapp.processEvents()
        assert calls == [True]
        host.exit_fullscreen()
        container.hide()

    def test_focus_guard_ignores_non_main_windows(self, qapp, monkeypatch) -> None:
        """焦点在宿主自身 / 其他窗口 / 无焦点窗口时不抢回。"""
        container, host = self._setup()
        container.show()
        qapp.processEvents()
        host.show_fullscreen()
        qapp.processEvents()

        other = QWidget()
        other.show()
        qapp.processEvents()

        calls = []
        monkeypatch.setattr(host, "_activate_window", lambda: calls.append(True))
        # 其他窗口获得焦点
        host._on_focus_window_changed(other.windowHandle())
        qapp.processEvents()
        # 宿主自身获得焦点（守卫激活宿主后回调再次触发时不递归）
        host._on_focus_window_changed(host.windowHandle())
        qapp.processEvents()
        # 无焦点窗口
        host._on_focus_window_changed(None)
        qapp.processEvents()
        assert calls == []
        host.exit_fullscreen()
        container.hide()
        other.hide()

    def test_focus_guard_inactive_after_exit_fullscreen(
        self, qapp, monkeypatch
    ) -> None:
        """exit_fullscreen 后守卫断开且不再抢焦点。"""
        container, host = self._setup()
        container.show()
        qapp.processEvents()
        host.show_fullscreen()
        qapp.processEvents()
        assert host._focus_guard_active is True
        main_handle = container.windowHandle()
        assert main_handle is not None

        host.exit_fullscreen()
        assert host._focus_guard_active is False
        assert host._main_window is None

        calls = []
        monkeypatch.setattr(host, "_activate_window", lambda: calls.append(True))
        host._on_focus_window_changed(main_handle)
        qapp.processEvents()
        assert calls == []
        container.hide()

    def test_focus_guard_without_main_window(self, qapp, monkeypatch) -> None:
        """未 attach（无 main window 记录）时守卫安全返回。"""
        host = PreviewFullscreenHost()
        host.show_fullscreen()
        qapp.processEvents()
        assert host._main_window is None
        assert host._focus_guard_active is True

        calls = []
        monkeypatch.setattr(host, "_activate_window", lambda: calls.append(True))
        host._on_focus_window_changed(None)
        qapp.processEvents()
        assert calls == []
        host.exit_fullscreen()
        assert host._focus_guard_active is False
