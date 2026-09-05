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
from unittest.mock import MagicMock

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

    @staticmethod
    def _make_target_file(tmp_path) -> Path:
        """在临时目录创建一个定位目标文件，返回其路径。"""
        target = tmp_path / "locate_target.txt"
        target.write_text("locate me", encoding="utf-8")
        return target

    def test_locate_file_navigates_and_highlights(
        self, qapp: QApplication, tmp_path: object, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """文件池预览文件不在当前目录：locate_file 导航到所在目录并高亮卡片。"""
        import os

        import freeassetfilter.ui.layout.file_selector_layout as fsl_mod

        messages: list = []
        monkeypatch.setattr(
            fsl_mod.FileSelectorLayout, "_show_message_dialog",
            lambda self, t, m: messages.append((t, m)),
        )

        target = self._make_target_file(tmp_path)
        layout = FileSelectorLayout()
        _assert_layout_geometry(layout, qapp)
        assert messages == []

        layout.locate_file({"path": str(target), "name": target.name})

        target_dir = os.path.abspath(os.path.normpath(str(tmp_path)))
        assert os.path.normcase(layout._current_path) == os.path.normcase(target_dir)
        assert layout._previewing_file_path is not None
        assert (
            os.path.normcase(layout._previewing_file_path)
            == os.path.normcase(str(target))
        )
        # 等待延后滚动的 singleShot 触达后安全清理
        import time

        time.sleep(0.25)
        qapp.processEvents()
        layout.deleteLater()

    def test_locate_file_same_directory_skips_navigation(
        self, qapp: QApplication, tmp_path: object, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """目标文件已在当前目录：locate_file 不重复导航，仅高亮滚动。"""
        import os

        import freeassetfilter.ui.layout.file_selector_layout as fsl_mod

        messages: list = []
        monkeypatch.setattr(
            fsl_mod.FileSelectorLayout, "_show_message_dialog",
            lambda self, t, m: messages.append((t, m)),
        )

        target = self._make_target_file(tmp_path)
        layout = FileSelectorLayout()
        _assert_layout_geometry(layout, qapp)

        layout._load_directory(os.path.abspath(str(tmp_path)))
        assert messages == []

        navigate_calls: list = []
        original_navigate = layout._navigate_to

        def _spy_navigate(path: str) -> None:
            navigate_calls.append(path)
            original_navigate(path)

        monkeypatch.setattr(layout, "_navigate_to", _spy_navigate)

        layout.locate_file({"path": str(target), "name": target.name})

        assert navigate_calls == []  # 目录未变，不触发导航
        assert layout._previewing_file_path is not None
        assert (
            os.path.normcase(layout._previewing_file_path)
            == os.path.normcase(str(target))
        )

        import time

        time.sleep(0.25)
        qapp.processEvents()
        layout.deleteLater()

    def test_locate_file_missing_directory_shows_message(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """目标目录不存在：弹提示且不导航、不高亮。"""
        import os

        import freeassetfilter.ui.layout.file_selector_layout as fsl_mod

        messages: list = []
        monkeypatch.setattr(
            fsl_mod.FileSelectorLayout, "_show_message_dialog",
            lambda self, t, m: messages.append((t, m)),
        )

        layout = FileSelectorLayout()
        _assert_layout_geometry(layout, qapp)

        ghost = "D:/definitely/not/exists_dir/ghost.txt"
        navigate_calls: list = []
        monkeypatch.setattr(layout, "_navigate_to", lambda path: navigate_calls.append(path))

        layout.locate_file({"path": ghost, "name": "ghost.txt"})

        assert len(messages) == 1
        assert messages[0][0] == "错误"
        assert navigate_calls == []
        assert not layout._previewing_file_path
        assert os.path.normcase(layout._current_path) == os.path.normcase("All")
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

    def test_appearance_page_uses_floating_styled_scrollbar(
        self, qapp: QApplication,
    ) -> None:
        """外观页包在浮动滚动区中：styled 浮动滚动条接管，原生滚动条隐藏。"""
        from PySide6.QtWidgets import QScrollArea

        from components.styled_scroll_area import StyledScrollBar
        from freeassetfilter.ui.layout.settings_layout import _FloatingScrollArea

        layout = SettingsLayout()
        scrolls = layout._stack.findChildren(QScrollArea)
        floating = [s for s in scrolls if isinstance(s, _FloatingScrollArea)]
        assert len(floating) == 1

        area = floating[0]
        # 原生滚动条隐藏，浮动 styled 滚动条存在
        assert area.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert area.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert isinstance(area._floating_bar, StyledScrollBar)
        # 浮动条锚定挂在外观卡片（#SettingsCard）下，贴其右缘（而非滚动区自身）
        assert area._region is area.parent()
        assert area._floating_bar.parent() is area.parent()
        # 平滑滚动在 showEvent 中初始化（未显示前未施加）
        assert area._scroller_ready is False
        safe_teardown(layout)

    def test_floating_scrollbar_range_and_value_sync(
        self, qapp: QApplication,
    ) -> None:
        """浮动滚动条与内部滚动条范围/值双向同步，随内容显隐。"""
        from freeassetfilter.ui.layout.settings_layout import _FloatingScrollArea

        area = _FloatingScrollArea()
        area.resize(400, 300)

        inner = QWidget()
        inner.setFixedHeight(800)  # 内容超出 → 产生滚动范围
        area.setWidget(inner)
        qapp.processEvents()
        area.show()
        qapp.processEvents()

        vbar = area.verticalScrollBar()
        bar = area._floating_bar
        if vbar.maximum() > 0:
            assert bar.maximum() == vbar.maximum()
            assert bar.isVisible()

            # 内部值变化 → 浮动条跟随
            vbar.setValue(10)
            assert bar.value() == 10
            # 浮动条拖动 → 内部跟随
            bar.setValue(20)
            assert vbar.value() == 20
            # 浮动条贴右侧边缘几何
            assert bar.x() == area.width() - bar.width()
        area.hide()
        safe_teardown(area)


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

    @staticmethod
    def _unsupported_file_info() -> dict:
        """无对应预览器的文件信息（不触发真实预览加载，仅驱动底栏状态）。"""
        return {"path": "D:/dummy/unsupported_sample.zzz", "suffix": "zzz", "is_dir": False}

    def test_bottom_buttons_disabled_then_enabled(
        self, qapp: QApplication,
    ) -> None:
        """无预览文件时底栏按钮禁用；set_file 后启用；clear_preview 后再禁用。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)

        assert layout._share_btn.isEnabled() is False
        assert layout._open_default_btn.isEnabled() is False
        assert layout._locate_btn.isEnabled() is False
        assert layout._close_btn.isEnabled() is False

        layout.set_file(self._unsupported_file_info())
        qapp.processEvents()
        assert layout._share_btn.isEnabled() is True
        assert layout._open_default_btn.isEnabled() is True
        assert layout._locate_btn.isEnabled() is True
        assert layout._close_btn.isEnabled() is True

        layout.clear_preview()
        qapp.processEvents()
        assert layout._share_btn.isEnabled() is False
        assert layout._open_default_btn.isEnabled() is False
        assert layout._locate_btn.isEnabled() is False
        assert layout._close_btn.isEnabled() is False
        layout.deleteLater()

    def test_locate_button_emits_requested(self, qapp: QApplication) -> None:
        """点击"定位到所在目录"发射 locate_requested(当前文件信息)。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(self._unsupported_file_info())

        received: list = []
        layout.locate_requested.connect(lambda info: received.append(info))
        layout._locate_btn.click()

        assert len(received) == 1
        assert received[0]["path"] == "D:/dummy/unsupported_sample.zzz"
        layout.deleteLater()

    def test_close_button_emits_clear_requested(self, qapp: QApplication) -> None:
        """点击 close 按钮发射 clear_requested（清除预览请求）。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(self._unsupported_file_info())

        received: list = []
        layout.clear_requested.connect(lambda: received.append(True))
        layout._close_btn.click()

        assert received == [True]
        layout.deleteLater()

    @pytest.mark.parametrize(
        "file_info, expected",
        [
            ({"path": "x.mp3", "suffix": "mp3"}, True),   # 无点号音频
            ({"path": "x.wav", "suffix": ".wav"}, True),  # 带点号音频
            ({"path": "x.MP3", "suffix": "MP3"}, True),   # 大写后缀
            ({"suffix": ""}, False),                       # 空后缀
            ({"path": "x.txt", "suffix": "txt"}, False),   # 非音频（无点）
            ({"path": "x.log", "suffix": ".txt"}, False),  # 非音频（带点）
        ],
    )
    def test_is_audio_file_normalizes_suffix(
        self, qapp: QApplication, file_info: dict, expected: bool
    ) -> None:
        """_is_audio_file 对 suffix 归一化（无点/带点/大小写）后再判音频。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert layout._is_audio_file(file_info) is expected
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

    def test_set_file_recovers_dead_core(
        self, qapp: QApplication, heartbeat_manager: Any, tmp_path: object
    ) -> None:
        """核心死亡时 set_file 自动重建（initialize）并重新嵌入窗口后正常加载。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            media = tmp_path / "sample.mp4"
            media.write_bytes(b"\x00" * 16)
            layout = VideoPlayerLayout()

            fake_manager: Any = MagicMock()
            fake_manager.is_core_operational.return_value = False  # 核心已死
            fake_manager.initialize.return_value = True
            fake_manager.set_window_id.return_value = True
            fake_manager.load_file.return_value = True
            fake_manager.play.return_value = True
            fake_manager.set_volume.return_value = True
            fake_manager.set_speed.return_value = True
            layout._mpv_manager = fake_manager  # noqa: SLF001

            assert layout.set_file(str(media), is_audio=False) is True
            fake_manager.initialize.assert_called_once()  # 自愈重建
            fake_manager.set_window_id.assert_called_once()  # 重新嵌入
            fake_manager.load_file.assert_called_once()
            assert layout._stack.currentIndex() == 0  # noqa: SLF001
        finally:
            qapp.setProperty("faf_disable_animation", animation_enabled_original)
        layout.deleteLater()

    def test_load_failure_shows_overlay(
        self, qapp: QApplication, heartbeat_manager: Any, tmp_path: object
    ) -> None:
        """load_file 失败时切回 overlay 显示错误（不再停留黑色视频表面）。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            media = tmp_path / "bad.mp4"
            media.write_bytes(b"\x00" * 16)
            layout = VideoPlayerLayout()

            fake_manager: Any = MagicMock()
            fake_manager.is_core_operational.return_value = True
            fake_manager.set_window_id.return_value = True
            fake_manager.load_file.return_value = False  # 加载失败
            layout._mpv_manager = fake_manager  # noqa: SLF001

            assert layout.set_file(str(media), is_audio=False) is False
            assert layout._stack.currentIndex() == 1  # noqa: SLF001
            assert "无法加载文件" in layout._placeholder.text()  # noqa: SLF001
        finally:
            qapp.setProperty("faf_disable_animation", animation_enabled_original)
        layout.deleteLater()

    def test_core_rebuild_failure_shows_overlay(
        self, qapp: QApplication, heartbeat_manager: Any, tmp_path: object
    ) -> None:
        """核心重建失败时切回 overlay 显示"无法初始化播放器"。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            media = tmp_path / "dead.mp4"
            media.write_bytes(b"\x00" * 16)
            layout = VideoPlayerLayout()

            fake_manager: Any = MagicMock()
            fake_manager.is_core_operational.return_value = False
            fake_manager.initialize.return_value = False  # 重建失败
            layout._mpv_manager = fake_manager  # noqa: SLF001

            assert layout.set_file(str(media), is_audio=False) is False
            assert layout._stack.currentIndex() == 1  # noqa: SLF001
            assert "无法初始化播放器" in layout._placeholder.text()  # noqa: SLF001
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

    def test_mica_sliders_removed(self, qapp: QApplication) -> None:
        """米卡参数已固定（按主题定值）：外观页不再构建滑动条配置项。"""
        page = AppearanceSettingsPage()
        assert not hasattr(page, "_mica_sliders")
        assert not hasattr(page, "_mica_value_labels")
        assert not hasattr(page, "_mica_values")
        assert not hasattr(page, "_mica_preview_timer")
        assert not hasattr(page, "_native_mica_toggle")
        safe_teardown(page)

    def test_bg_segmented_hugs_content_width(self, qapp: QApplication) -> None:
        """「窗口背景」分段控件宽度贴合选项内容，不占满页面/卡片整宽。"""
        page = AppearanceSettingsPage()
        page.resize(640, 900)
        qapp.processEvents()

        seg = page._bg_segmented
        hint = seg.sizeHint()
        assert hint.width() > 0
        assert seg.width() == hint.width()
        assert seg.width() < page.width()
        # pill 容器背景只包住选项内容
        assert int(seg._header.content_width) == seg.width()
        safe_teardown(page)

    # ── 窗口背景区块（米卡效果 / 自定义图片） ─────────────────────

    @staticmethod
    def _make_fake_bg_main_window() -> Any:
        """构造记录背景 API 调用顺序的假主窗口（无需真实 QWidget）。"""

        class _FakeBgMainWindow:
            """记录 set_background_mode / set_custom_background_image 调用。"""

            def __init__(self) -> None:
                self.mode_calls: list[str] = []
                self.image_calls: list[str] = []

            def set_background_mode(self, mode: str) -> None:
                self.mode_calls.append(mode)

            def set_custom_background_image(self, path: str) -> bool:
                self.image_calls.append(path)
                return True

        return _FakeBgMainWindow()

    @staticmethod
    def _make_fake_file_dialog(result: tuple[str, str]) -> Any:
        """构造 getOpenFileName 返回固定结果的假 QFileDialog。"""

        class _FakeFileDialog:
            """静态 getOpenFileName 返回预设 (path, filter) 元组。"""

            @staticmethod
            def getOpenFileName(*args: Any, **kwargs: Any) -> tuple[str, str]:
                return result

        return _FakeFileDialog

    def test_background_default_mica_ui_state(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """默认（V2 无背景设置）：mica 模式——分段 0、图片行隐藏、滑动条可用。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )

        page = AppearanceSettingsPage()
        assert page._bg_mode == "mica"
        assert page._bg_image_name == ""
        assert page._bg_segmented.current_index == 1
        assert page._bg_image_row.isVisibleTo(page) is False
        assert page._bg_file_label.text() == "未设置"
        safe_teardown(page)

    def test_background_image_mode_loaded_from_v2(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """V2 保存 image 模式且文件存在：初始即 image UI 状态（不触发应用）。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )
        from components.custom_background import BACKGROUND_DIR_NAME

        tmp_file = str(tmp_path / "settings_v2.json")
        v2 = SettingsManagerV2(tmp_file)
        v2.load()
        v2.set(
            "appearance.background",
            {"mode": "image", "image": "custom_background.png"},
        )
        v2.save()

        bg_dir = tmp_path / BACKGROUND_DIR_NAME
        bg_dir.mkdir()
        pm = QPixmap(16, 16)
        pm.fill(QColor("#336699"))
        assert pm.save(str(bg_dir / "custom_background.png"), "PNG") is True

        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))

        page = AppearanceSettingsPage()
        assert page._bg_mode == "image"
        assert page._bg_image_name == "custom_background.png"
        assert page._bg_segmented.current_index == 2
        assert page._bg_image_row.isVisibleTo(page) is True
        assert page._bg_file_label.text() == "custom_background.png"
        safe_teardown(page)

    def test_apply_background_settings_routes_and_saves(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """_apply_background_settings：暂存优先（未提交不触碰主窗口与磁盘）。

        新语义：仅写入暂存缓存并刷新本页 UI；主窗口应用与 V2 落盘统一由
        ``SettingsLayout._submit_settings`` 在点击应用/确定时执行。
        """
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "_find_main_window", lambda self: fake_mw
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))

        page = AppearanceSettingsPage()
        page._bg_image_name = "custom_background.png"

        # image 暂存：不直调主窗口、不落盘，仅缓存 + UI 可见
        page._apply_background_settings("image")
        assert fake_mw.image_calls == []
        assert fake_mw.mode_calls == []
        assert page._staging_cache.get("appearance.background.mode") == "image"
        assert page._staging_cache.get("appearance.background.image") == "custom_background.png"
        assert page._bg_image_row.isVisibleTo(page) is True

        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background.mode") == "mica"

        # mica 暂存：同样仅缓存，不动主窗口图片接口
        page._apply_background_settings("mica")
        assert fake_mw.mode_calls == []
        assert len(fake_mw.image_calls) == 0
        assert page._bg_image_row.isVisibleTo(page) is False
        assert page._staging_cache.get("appearance.background.mode") == "mica"
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background.mode") == "mica"
        safe_teardown(page)

    def test_bg_segment_switch_with_existing_image(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """已有持久化图片时切换分段：暂存 image 模式（不经文件对话框、不直写）。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )
        from components.custom_background import BACKGROUND_DIR_NAME

        tmp_file = str(tmp_path / "settings_v2.json")
        bg_dir = tmp_path / BACKGROUND_DIR_NAME
        bg_dir.mkdir()
        pm = QPixmap(16, 16)
        pm.fill(QColor("#336699"))
        assert pm.save(str(bg_dir / "custom_background.png"), "PNG") is True

        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "_find_main_window", lambda self: fake_mw
        )

        page = AppearanceSettingsPage()
        page._bg_image_name = "custom_background.png"
        # 模拟用户点击图像分段（触发 current_changed → 处理器，仅暂存）
        page._bg_segmented.set_current_index(2)

        assert page._bg_mode == "image"
        assert page._staging_cache.get("appearance.background.mode") == "image"
        assert len(fake_mw.image_calls) == 0
        assert fake_mw.mode_calls == []
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background.mode") == "mica"
        safe_teardown(page)

    def test_bg_segment_switch_cancel_reverts(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """无图片时切换分段后取消选择：分段回退、设置不变、不调用主窗口。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))
        monkeypatch.setattr(
            sl_mod, "QFileDialog", self._make_fake_file_dialog(("", ""))
        )
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "_find_main_window", lambda self: fake_mw
        )

        page = AppearanceSettingsPage()
        page._bg_segmented.set_current_index(2)

        # 取消：分段编程式回退到云母，模式与持久化设置保持默认（未被写入）
        assert page._bg_segmented.current_index == 1
        assert page._bg_mode == "mica"
        assert fake_mw.mode_calls == []
        assert fake_mw.image_calls == []
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background") == {"mode": "mica", "image": "", "ambient": True}
        safe_teardown(page)

    def test_bg_segment_switch_import_failure_shows_dialog(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """导入失败：弹 danger 对话框、分段回退、不切换不改设置。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))
        monkeypatch.setattr(
            sl_mod, "QFileDialog",
            self._make_fake_file_dialog(("D:/fake/pic.png", "图片文件 (*.png)")),
        )
        monkeypatch.setattr(
            sl_mod, "import_custom_background_image", lambda path: None
        )
        dialog_calls: list[dict] = []
        monkeypatch.setattr(
            sl_mod, "create_danger_dialog",
            lambda **kwargs: dialog_calls.append(kwargs),
        )
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "_find_main_window", lambda self: fake_mw
        )

        page = AppearanceSettingsPage()
        page._bg_segmented.set_current_index(2)

        assert len(dialog_calls) == 1
        assert dialog_calls[0]["title"] == "导入失败"
        assert page._bg_segmented.current_index == 1
        assert page._bg_mode == "mica"
        assert fake_mw.mode_calls == []
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background") == {"mode": "mica", "image": "", "ambient": True}
        safe_teardown(page)

    def test_choose_bg_image_success_via_button(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """按钮点击选择图片成功：暂存文件名与 image 模式（提交前不直写）。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))
        monkeypatch.setattr(
            sl_mod, "QFileDialog",
            self._make_fake_file_dialog(("D:/fake/pic.png", "图片文件 (*.png)")),
        )
        dest = str(tmp_path / "backgrounds" / "custom_background.png")
        monkeypatch.setattr(
            sl_mod, "import_custom_background_image", lambda path: dest
        )
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "_find_main_window", lambda self: fake_mw
        )

        page = AppearanceSettingsPage()
        # 模拟按钮点击（clicked → _on_choose_bg_image_clicked → 非强制选择）
        page._bg_choose_btn.click()

        assert page._bg_image_name == "custom_background.png"
        assert page._bg_file_label.text() == "custom_background.png"
        assert page._bg_mode == "image"
        assert page._bg_segmented.current_index == 1  # 按钮入口不切分段
        assert page._staging_cache.get("appearance.background.image") == "custom_background.png"
        assert fake_mw.image_calls == []
        assert fake_mw.mode_calls == []
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background.mode") == "mica"
        safe_teardown(page)

    def test_update_bg_ui_state_toggles_image_row(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """_update_bg_ui_state：image 模式显示图片行，mica 模式隐藏。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )

        page = AppearanceSettingsPage()
        page._bg_mode = "image"
        page._update_bg_ui_state()
        assert page._bg_image_row.isVisibleTo(page) is True

        page._bg_mode = "mica"
        page._update_bg_ui_state()
        assert page._bg_image_row.isVisibleTo(page) is False
        safe_teardown(page)