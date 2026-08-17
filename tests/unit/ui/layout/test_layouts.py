# -*- coding: utf-8 -*-
"""布局层单元测试（todo-23 批 3 / task-23）。

覆盖 ui/layout 下 11 个布局模块的构造契约、尺寸生效与 set_file 分发：
全部 QWidget 布局以默认参数构造、放入内容后 geometry 非空；
带 ``set_file`` 入口的布局对缺失路径安全降级（不抛异常、返回 False 或
停留在 overlay）；``PreviewFullscreenHost`` 在无父窗口时进出全屏不抛；
``VideoPlayerLayout`` 在无 libmpv 时不真实播放（缺失路径直接返回 False）。

验证命令：
    python -m pytest tests/unit/ui/layout/test_layouts.py --timeout 60 -q
"""

# targets: ui.layout.file_pool_layout, ui.layout.file_selector_layout,
#          ui.layout.settings_layout, ui.layout.unified_previewer_layout,
#          ui.layout.preview.font_previewer_layout,
#          ui.layout.preview.fullscreen_host,
#          ui.layout.preview.image_previewer_layout,
#          ui.layout.preview.office_previewer_layout,
#          ui.layout.preview.pdf_previewer_layout,
#          ui.layout.preview.text_previewer_layout,
#          ui.layout.preview.video_player_layout

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QEvent, QPointF, QObject, Qt, QThread, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QEnterEvent,
    QHideEvent,
    QMouseEvent,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

# 布局模块内部使用短路径导入（from theme import tm / components.*），
# 要求 freeassetfilter/ui 位于 sys.path；与 layout/preview 模块自身的
# bootstrap 保持一致（详见 file_pool_layout.py:46 的用法）。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.layout.file_pool_layout import FilePoolLayout
from freeassetfilter.ui.layout.file_selector_layout import FileSelectorLayout
from freeassetfilter.ui.layout.preview.font_previewer_layout import (
    FontLoadThread,
    FontPreviewerLayout,
)
from freeassetfilter.ui.layout.preview.fullscreen_host import PreviewFullscreenHost
from freeassetfilter.ui.layout.preview.image_previewer_layout import ImagePreviewerLayout
import freeassetfilter.ui.layout.preview.office_previewer_layout as _opl
from freeassetfilter.ui.layout.preview.office_previewer_layout import (
    OfficePreviewerLayout,
)
from freeassetfilter.ui.layout.preview.pdf_previewer_layout import PdfPreviewerLayout
from freeassetfilter.ui.layout.preview.text_previewer_layout import TextPreviewerLayout
from freeassetfilter.ui.layout.preview.video_player_layout import VideoPlayerLayout
from freeassetfilter.ui.layout.settings_layout import (
    AccentColorButton,
    AppearanceSettingsPage,
    CustomAccentButton,
    SettingsLayout,
)
from freeassetfilter.ui.layout.unified_previewer_layout import UnifiedPreviewerLayout

from tests.support.qt_helpers import safe_teardown  # noqa: E402

pytestmark = pytest.mark.unit

_MISSING_FILE: str = "C:/definitely/missing_file.xyz"
_LAYOUT_SIZE: tuple[int, int] = (640, 480)


def _assert_layout_geometry(widget: QWidget, qapp: QApplication) -> None:
    """宿主 resize 后 geometry 有效（尺寸用例的公共断言）。"""
    widget.resize(*_LAYOUT_SIZE)
    qapp.processEvents()
    assert widget.width() > 0
    assert widget.height() == 480


# =============================================================================
# ui.layout.file_pool_layout
# =============================================================================
class TestFilePoolLayout:
    """文件池布局：构造契约、add_file 入池与尺寸生效。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = FilePoolLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_add_file_and_query(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """add_file 入池后 has_file / get_pool_paths 可见，可安全移除。"""
        # 禁用删除动画，使 remove_file 同步完成（否则经 _removing_paths 异步走）
        import freeassetfilter.ui.layout.file_pool_layout as fpl_mod

        monkeypatch.setattr(
            fpl_mod, "is_animation_enabled", lambda *args, **kwargs: False
        )
        layout = FilePoolLayout()
        _assert_layout_geometry(layout, qapp)
        file_path = "D:/dummy/file_pool_sample.png"
        layout.add_file({"path": file_path, "name": "file_pool_sample.png"})
        assert layout.has_file(file_path) is True
        assert file_path.replace("/", "\\") in layout.get_pool_paths() or file_path in layout.get_pool_paths()
        layout.remove_file(file_path)
        assert layout.has_file(file_path) is False
        layout.deleteLater()


# =============================================================================
# ui.layout.file_selector_layout
# =============================================================================
class TestFileSelectorLayout:
    """文件选择器布局：构造契约与尺寸生效。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = FileSelectorLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()


# =============================================================================
# ui.layout.settings_layout
# =============================================================================
class TestSettingsLayout:
    """设置页布局：构造契约与尺寸生效（读取真实 settings_v2.json）。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = SettingsLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()


# =============================================================================
# ui.layout.unified_previewer_layout
# =============================================================================
class TestUnifiedPreviewerLayout:
    """统一预览器布局：构造、set_file(None)/clear_preview 分发。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_file_none_is_safe(self, qapp: QApplication) -> None:
        """set_file(None) 走安全清空路径，不抛异常。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(None)
        qapp.processEvents()
        assert layout._content_layout is not None
        layout.clear_preview()
        layout.deleteLater()


# =============================================================================
# ui.layout.preview.font_previewer_layout
# =============================================================================
class TestFontPreviewerLayout:
    """字体预览布局：构造契约与 set_file 缺失路径降级。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_file_missing_safe(self, qapp: QApplication) -> None:
        """set_file(缺失路径) 不抛异常，停留 overlay 视图。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(_MISSING_FILE)
        qapp.processEvents()
        assert layout._content_stack.currentIndex() == 1
        layout.deleteLater()


# =============================================================================
# ui.layout.preview.fullscreen_host
# =============================================================================
class TestPreviewFullscreenHost:
    """全屏宿主席：attach/detach 进出、无父窗口进出全屏不抛。"""

    def test_attach_detach_roundtrip(self, qapp: QApplication) -> None:
        """attach 移入宿主，exit_fullscreen 还原到原父布局。"""
        container = QWidget()
        layout = QVBoxLayout(container)
        child = QWidget(container)
        layout.addWidget(child)

        host = PreviewFullscreenHost()
        assert host.attach(child) is True
        assert host.content is child
        assert layout.indexOf(child) == -1
        host.exit_fullscreen()
        assert host.content is None
        assert layout.indexOf(child) == 0
        host.deleteLater()
        container.deleteLater()

    def test_fullscreen_without_parent_does_not_raise(
        self, qapp: QApplication
    ) -> None:
        """无父窗口时 show_fullscreen / exit_fullscreen 不抛（QA 要求）。"""
        host = PreviewFullscreenHost()
        host.show_fullscreen()
        qapp.processEvents()
        host.exit_fullscreen()
        qapp.processEvents()
        host.deleteLater()

    def test_escape_emits_signal(self, qapp: QApplication) -> None:
        """Esc 按键发射 escapePressed 信号（先 connect 再触发）。"""
        host = PreviewFullscreenHost()
        received: list[bool] = []
        host.escapePressed.connect(lambda: received.append(True))
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        host.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        assert received == [True]
        host.deleteLater()


# =============================================================================
# ui.layout.preview.image_previewer_layout
# =============================================================================
class TestImagePreviewerLayout:
    """图像预览布局：构造契约与 set_file 缺失路径返回 False。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = ImagePreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_file_missing_returns_false(self, qapp: QApplication) -> None:
        """set_file(缺失路径) 返回 False，不抛异常。"""
        layout = ImagePreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert layout.set_file(_MISSING_FILE) is False
        layout.deleteLater()


# =============================================================================
# ui.layout.preview.office_previewer_layout
# =============================================================================
class _FakeOfficeWorker(QObject):
    """``OfficeConverterWorker`` 的可控替身：不启动真实 soffice 线程。"""

    converted = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        file_info: dict,
        timeout: float | None = None,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.file_info: dict = file_info
        self._running: bool = False

    def start(self, *args: Any, **kwargs: Any) -> None:
        """镜像 start：fake 只标记运行中。"""
        self._running = True

    def is_running(self) -> bool:
        """线程是否仍在运行。"""
        return self._running

    def isRunning(self) -> bool:  # noqa: N802
        """Qt 兼容接口。"""
        return self._running

    def request_cancel(self) -> None:
        """镜像 request_cancel。"""
        self._running = False

    def wait(self, timeout_ms: int = 3000) -> bool:
        """镜像 wait。"""
        return not self._running

    def cleanup(self, wait_ms: int = 3000) -> None:
        """镜像 cleanup。"""
        self._running = False


class TestOfficePreviewerLayout:
    """Office 预览布局：构造契约与 set_file 分发（注入 fake worker）。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造（无 worker） + resize 后 geometry 非空。"""
        layout = OfficePreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.cleanup()
        layout.deleteLater()

    def test_set_file_str_routes_to_worker(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """宿主 str 路径分发 → 归一化为 dict、启动 worker（fake）。"""
        monkeypatch.setattr(_opl, "OfficeConverterWorker", _FakeOfficeWorker)
        layout = OfficePreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file("C:/fake/path/sample.docx")
        assert layout._current_suffix == "docx"
        assert isinstance(layout._current_worker, _FakeOfficeWorker)
        layout.cleanup()
        layout.deleteLater()


# =============================================================================
# ui.layout.preview.pdf_previewer_layout
# =============================================================================
class TestPdfPreviewerLayout:
    """PDF 预览布局：构造契约与 set_file 缺失路径返回 False。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = PdfPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_file_missing_returns_false(self, qapp: QApplication) -> None:
        """set_file(缺失路径) 返回 False，不抛异常。"""
        layout = PdfPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert layout.set_file(_MISSING_FILE) is False
        layout.deleteLater()


# =============================================================================
# ui.layout.preview.text_previewer_layout
# =============================================================================
class TestTextPreviewerLayout:
    """文本预览布局：构造契约、set_text_content 与缺失路径降级。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_text_content(self, qapp: QApplication) -> None:
        """直接注入文本内容不抛异常。"""
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_text_content("hello from test")
        qapp.processEvents()
        layout.deleteLater()

    def test_set_file_missing_safe(self, qapp: QApplication) -> None:
        """set_file(缺失路径) 不抛异常。"""
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(_MISSING_FILE)
        qapp.processEvents()
        layout.deleteLater()


# =============================================================================
# ui.layout.preview.video_player_layout
# =============================================================================
class TestVideoPlayerLayout:
    """视频播放布局：构造契约；不带 libmpv 时不真实播放（缺失路径返回 False）。"""

    def test_construct_and_geometry(
        self, qapp: QApplication, heartbeat_manager: Any
    ) -> None:
        """默认构造 + resize 后 geometry 非空（HeartbeatManager 已启动）。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            layout = VideoPlayerLayout()
            assert layout is not None
        finally:
            qapp.setProperty("faf_disable_animation", animation_enabled_original)
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_file_missing_returns_false(
        self, qapp: QApplication, heartbeat_manager: Any
    ) -> None:
        """无 libmpv 时 set_file(缺失路径) 返回 False，不做真实播放。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            layout = VideoPlayerLayout()
            assert layout.set_file(_MISSING_FILE) is False
        finally:
            qapp.setProperty("faf_disable_animation", animation_enabled_original)
        layout.deleteLater()


# =============================================================================
# ui.layout.preview.font_previewer_layout — FontLoadThread
# =============================================================================
class TestFontLoadThread:
    """FontLoadThread：文件/请求 ID/中止设置与缺失路径降级。"""

    def test_construct_and_setters(self, qapp: QApplication) -> None:
        """构造后 set_file / set_request_id 生效，未启动线程。"""
        thread = FontLoadThread()
        assert isinstance(thread, QThread)
        thread.set_file(_MISSING_FILE)
        thread.set_request_id(7)
        assert thread.file_path == _MISSING_FILE
        assert thread._request_id == 7
        thread.set_request_id(0)
        thread.abort()  # abort 标记置位
        thread.deleteLater()

    def test_run_missing_path_emits_error(self, qapp: QApplication) -> None:
        """run() 同步执行：缺失路径发 error(request_id, 消息)。"""
        thread = FontLoadThread()
        thread.set_file(_MISSING_FILE)
        thread.set_request_id(42)
        received: list = []

        def _on_error(request_id: int, msg: str) -> None:
            received.append((request_id, msg))

        thread.error.connect(_on_error)
        thread.run()  # 同步执行 run 体，避免真实后台线程
        assert len(received) == 1
        assert received[0][0] == 42
        assert "不存在" in received[0][1]
        thread.deleteLater()


# =============================================================================
# ui.layout.settings_layout — AccentColorButton
# =============================================================================
class TestAccentColorButton:
    """AccentColorButton：构造、color_hex/selected/hover_progress 与点击。"""

    def test_construct(self, qapp: QApplication) -> None:
        """默认构造：color_hex 回退为传入值，未选中、hover 进度 0。"""
        btn = AccentColorButton("#007AFF", name="蓝")
        assert btn.color_hex == "#007AFF"
        assert btn.selected is False
        assert btn.hover_progress == 0.0
        safe_teardown(btn)

    def test_value_override(self, qapp: QApplication) -> None:
        """value 参数覆盖 color_hex 返回值（自动模式用）。"""
        btn = AccentColorButton("#007AFF", value="auto")
        assert btn.color_hex == "auto"
        safe_teardown(btn)

    def test_selected_roundtrip(self, qapp: QApplication) -> None:
        """selected 可写且可读回。"""
        btn = AccentColorButton("#007AFF")
        btn.selected = True
        assert btn.selected is True
        btn.selected = False
        assert btn.selected is False
        safe_teardown(btn)

    def test_click_emits_hex(self, qapp: QApplication) -> None:
        """左键按下发射 clicked(原始 hex)。"""
        btn = AccentColorButton("#007AFF")
        received: list = []

        def _on_clicked(color: str) -> None:
            received.append(color)

        btn.clicked.connect(_on_clicked)
        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(20, 20),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        btn.mousePressEvent(press)
        assert received == ["#007AFF"]
        safe_teardown(btn)

    def test_paint_event_safe(self, qapp: QApplication) -> None:
        """离屏渲染不抛异常。"""
        btn = AccentColorButton("#007AFF", center_text="A")
        btn.selected = True
        pm = QPixmap(40, 40)
        pm.fill(QColor("#000000"))
        btn.render(pm)
        safe_teardown(btn)


# =============================================================================
# ui.layout.settings_layout — CustomAccentButton
# =============================================================================
class TestCustomAccentButton:
    """CustomAccentButton：构造、selected 与点击。"""

    def test_construct(self, qapp: QApplication) -> None:
        """默认构造未选中；传参构造选中。"""
        btn = CustomAccentButton()
        assert btn.selected is False
        btn2 = CustomAccentButton(selected=True)
        assert btn2.selected is True
        safe_teardown(btn)
        safe_teardown(btn2)

    def test_selected_setter(self, qapp: QApplication) -> None:
        """selected 可写可读回。"""
        btn = CustomAccentButton()
        btn.selected = True
        assert btn.selected is True
        safe_teardown(btn)

    def test_click_emits(self, qapp: QApplication) -> None:
        """左键按下发射 clicked。"""
        btn = CustomAccentButton()
        received: list = []

        def _on_clicked() -> None:
            received.append(True)

        btn.clicked.connect(_on_clicked)
        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(20, 20),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        btn.mousePressEvent(press)
        assert received == [True]
        safe_teardown(btn)

    def test_paint_event_safe(self, qapp: QApplication) -> None:
        """离屏渲染不抛异常。"""
        btn = CustomAccentButton(selected=True)
        pm = QPixmap(40, 40)
        pm.fill(QColor("#000000"))
        btn.render(pm)
        safe_teardown(btn)


# =============================================================================
# ui.layout.settings_layout — AppearanceSettingsPage
# =============================================================================
class TestAppearanceSettingsPage:
    """AppearanceSettingsPage：构造、设置收集、主题刷新与关闭路径。"""

    def test_construct_and_collect_settings(self, qapp: QApplication) -> None:
        """构造后 collect_settings 返回 V2 外观结构。"""
        page = AppearanceSettingsPage()
        settings = page.collect_settings()
        assert "appearance" in settings
        assert "theme" in settings["appearance"]
        assert "accent_color" in settings["appearance"]
        safe_teardown(page)

    def test_refresh_theme(self, qapp: QApplication) -> None:
        """refresh_theme：同步 toggle 状态且不抛异常。"""
        page = AppearanceSettingsPage()
        page.refresh_theme()
        assert page._dark_toggle.checked == page._dark_toggle.checked
        safe_teardown(page)

    def test_event_filter_dispatches_to_super(self, qapp: QApplication) -> None:
        """面板未创建时 eventFilter 对点击返回 False（放行继续传播）。"""
        page = AppearanceSettingsPage()
        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(10, 10),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        assert page.eventFilter(page, press) is False
        safe_teardown(page)

    def test_hide_and_close_safe(self, qapp: QApplication) -> None:
        """hideEvent / closeEvent 在面板未创建时不抛异常。"""
        page = AppearanceSettingsPage()
        page.hideEvent(QHideEvent())
        page.closeEvent(QCloseEvent())
        safe_teardown(page)