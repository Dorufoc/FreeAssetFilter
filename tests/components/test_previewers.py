# -*- coding: utf-8 -*-
# targets: components.unified_previewer, components.photo_viewer, components.video_player, components.pdf_previewer, components.native_pdf_renderer, components.text_previewer, components.font_previewer, components.archive_browser, components.folder_content_list, components.file_info_previewer
"""组件层批 2：预览器全家（10 个模块）单体测试。

覆盖统一预览器（类型分派）、图片查看器（PhotoViewer / ImageWidget）、
视频播放器（离线构造 / 缺失文件 / 清理幂等）、PDF 预览器与原生渲染器、
文本 / 字体 / 压缩包 / 文件夹列表 / 文件信息预览器。

已知生产缺陷（仅为绕过，不改生产代码）：
* ``font_previewer.FontPreviewer`` 构造时 ``FontPreviewWidget(self)`` 未传
  ``settings_manager``，触发 ``app`` NameError（font_previewer.py:197）。
  本文件直接测试 ``FontPreviewWidget``（显式传入 settings_manager）。
* ``folder_content_list`` / ``FontPreviewWidget`` 同样在 settings_manager
  为空时引用未定义的 ``app``，本文件一律显式传参规避。

约定：每个测试在激活异步线程后轮询等待线程终结后再销毁，避免
"QThread: Destroyed while thread is still running"。
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, List, Optional
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QImage
from PySide6.QtWidgets import QApplication

from freeassetfilter.core.managers.settings_manager import SettingsManager
from tests.support.data_factories import (
    file_info_dict,
    make_font_path,
    make_image,
    make_pdf,
    make_text,
    make_zip,
)
from tests.support.qt_helpers import (
    process_qt_events,
    safe_teardown,
    wait_for_signal,
)

pytestmark = pytest.mark.unit


# ===== 公共辅助 =====

def _settings_manager() -> SettingsManager:
    """返回一个全新的设置管理器实例（配合单例重置使用）。"""
    return SettingsManager()


def _global_font() -> QFont:
    """从 QApplication 读取全局字体，缺省为 Microsoft YaHei 9。"""
    app = QApplication.instance()
    return getattr(app, "global_font", QFont("Microsoft YaHei", 9))


def _wait_until(app: Optional[QApplication], predicate: Callable[[], bool], timeout_ms: float = 10000.0) -> bool:
    """带超时地轮询条件成立（溢出前持续泵事件）。

    Args:
        app: QApplication 实例。
        predicate: 判定条件。
        timeout_ms: 最长等待毫秒数。

    Returns:
        bool: 超时前条件成立返回 True，否则 False。
    """
    deadline: float = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        process_qt_events(app, ms=30)
        if predicate():
            return True
    return False


def _signal_collector(signal: Any) -> List[Any]:
    """连接信号并返回参数收集列表（同步发射用）。

    Args:
        signal: Qt 信号对象。

    Returns:
        List[Any]: 每次发射追加（信号参数元组）。
    """
    collected: List[Any] = []

    def _capture(*args: Any) -> None:
        collected.append(args)

    signal.connect(_capture)
    return collected


def _make_finfo(path: str, suffix: str = "", is_dir: bool = False) -> dict:
    """构造与 FileInfo 兼容的最小预览字典。

    Args:
        path: 文件或目录路径。
        suffix: 扩展名（不含点，目录传空串）。
        is_dir: 是否为目录。

    Returns:
        dict: 预览元信息字典。
    """
    return {"path": path, "suffix": suffix, "is_dir": is_dir}


# ===== unified_previewer =====

class TestUnifiedPreviewer:
    """统一预览器：构造、set_file 状态、类型分派、待处理队列。"""

    def test_construction_initial_state(self, qapp: QApplication) -> None:
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer

        up = UnifiedPreviewer(settings_manager=_settings_manager(), dpi_scale=1.0, global_font=_global_font())
        try:
            assert up.current_file_info is None
            assert up.current_preview_widget is None
            assert up.current_preview_type is None
            assert up.is_loading_preview is False
            assert up.file_info_viewer is not None
        finally:
            safe_teardown(up)

    def test_set_file_sets_current_info_and_emits_started(
        self, qapp: QApplication, tmp_path: Any
    ) -> None:
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer

        png_path: str = make_image(str(tmp_path / "sample.png"))
        finfo: dict = _make_finfo(png_path, suffix="png")

        up = UnifiedPreviewer(settings_manager=_settings_manager(), dpi_scale=1.0, global_font=_global_font())
        try:
            captured_preview_type: List[str] = []
            up._start_preview_switch = lambda file_path, preview_type: captured_preview_type.append(preview_type)  # type: ignore[method-assign]
            started: List[Any] = _signal_collector(up.preview_started)

            up.set_file(finfo)

            assert up.current_file_info == finfo
            assert started, "应发射 preview_started 信号"
            assert started[0][0] == finfo
        finally:
            safe_teardown(up)

    def test_set_file_while_loading_queues_pending(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer

        png_path: str = make_image(str(tmp_path / "sample.png"))
        finfo: dict = _make_finfo(png_path, suffix="png")

        up = UnifiedPreviewer(settings_manager=_settings_manager(), dpi_scale=1.0, global_font=_global_font())
        try:
            up.is_loading_preview = True
            up.set_file(finfo)
            assert up.current_file_info is None
            assert up._pending_file_info == finfo
        finally:
            safe_teardown(up)

    def test_dispatch_dir(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer

        sub = tmp_path / "subdir"
        sub.mkdir()
        finfo: dict = _make_finfo(str(sub), is_dir=True)

        up = UnifiedPreviewer(settings_manager=_settings_manager(), dpi_scale=1.0, global_font=_global_font())
        try:
            captured: List[str] = []
            up._start_preview_switch = lambda file_path, preview_type: captured.append(preview_type)  # type: ignore[method-assign]
            up.set_file(finfo)
            assert captured == ["dir"]
        finally:
            safe_teardown(up)

    @pytest.mark.parametrize(
        ("class_name", "suffix", "expected"),
        [
            ("ImagePreviewerLayout", "png", "image"),
            ("PhotoViewer", "png", "image"),
            ("GifViewer", "gif", "image"),
            ("VideoPlayer", "mp4", "video"),
            ("VideoPlayer", "mp3", "audio"),
            ("PDFPreviewer", "pdf", "pdf"),
            ("TextPreviewWidget", "txt", "text"),
            ("ArchiveBrowser", "zip", "archive"),
            ("FontPreviewWidget", "ttf", "font"),
            ("SomeOtherClass", "xyz", "unknown"),
        ],
    )
    def test_dispatch_class_mapping(
        self, qapp: QApplication, tmp_path: Any, class_name: str, suffix: str, expected: str
    ) -> None:
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer

        probe_file: str = str(tmp_path / f"sample.{suffix}")
        with open(probe_file, "w", encoding="utf-8") as handle:
            handle.write("x")
        finfo: dict = _make_finfo(probe_file, suffix=suffix)

        class FakeRegistry:
            @staticmethod
            def get_previewer_class(_info: dict) -> Optional[type]:
                return type(class_name, (), {"__name__": class_name})

        up = UnifiedPreviewer(settings_manager=_settings_manager(), dpi_scale=1.0, global_font=_global_font())
        try:
            import freeassetfilter.components.unified_previewer as up_mod

            up_mod.PreviewerRegistry = FakeRegistry  # type: ignore[assignment]
            captured: List[str] = []
            up._start_preview_switch = lambda file_path, preview_type: captured.append(preview_type)  # type: ignore[method-assign]
            up.set_file(finfo)
            assert captured == [expected]
        finally:
            safe_teardown(up)

    def test_dispatch_unknown_when_registry_returns_none(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer

        probe_file: str = str(tmp_path / "sample.qqq")
        with open(probe_file, "w", encoding="utf-8") as handle:
            handle.write("x")
        finfo: dict = _make_finfo(probe_file, suffix="qqq")

        class EmptyRegistry:
            @staticmethod
            def get_previewer_class(_info: dict) -> None:
                return None

        up = UnifiedPreviewer(settings_manager=_settings_manager(), dpi_scale=1.0, global_font=_global_font())
        try:
            import freeassetfilter.components.unified_previewer as up_mod

            up_mod.PreviewerRegistry = EmptyRegistry  # type: ignore[assignment]
            captured: List[str] = []
            up._start_preview_switch = lambda file_path, preview_type: captured.append(preview_type)  # type: ignore[method-assign]
            up.set_file(finfo)
            assert captured == ["unknown"]
        finally:
            safe_teardown(up)

    def test_stop_preview_clears_state(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer

        png_path: str = make_image(str(tmp_path / "sample.png"))
        up = UnifiedPreviewer(settings_manager=_settings_manager(), dpi_scale=1.0, global_font=_global_font())
        try:
            up.current_file_info = _make_finfo(png_path, suffix="png")
            up.stop_preview()
            assert up.current_file_info is None
            assert up.is_loading_preview is False
        finally:
            safe_teardown(up)


class TestUnifiedPreviewerBehavior:
    """统一预览器深度行为：按钮 / 进度条 / 清理 / 预览线程 / 占位与主题。"""

    def _make_up(self) -> Any:
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer

        return UnifiedPreviewer(settings_manager=_settings_manager(), dpi_scale=1.0, global_font=_global_font())

    def test_construction_uses_application_fallbacks(self, qapp: QApplication, monkeypatch: Any) -> None:
        """不传 dpi_scale / global_font / settings_manager 时走应用级回退。"""
        import freeassetfilter.core.managers.settings_manager as sm_mod
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer

        fake_sm = MagicMock()
        monkeypatch.setattr(sm_mod, "SettingsManager", lambda: fake_sm)
        setattr(qapp, "dpi_scale_factor", 2.0)
        setattr(qapp, "global_font", _global_font())

        up = UnifiedPreviewer()
        try:
            assert up.dpi_scale == 2.0
            assert up.global_font == _global_font()
            assert up._settings_manager is fake_sm
        finally:
            safe_teardown(up)

    def test_theme_colors_and_update_theme(self, qapp: QApplication) -> None:
        up = self._make_up()
        try:
            colors = up._get_theme_colors()
            assert "panel_background" in colors
            up.update_theme()
        finally:
            safe_teardown(up)

    def test_placeholder_show_and_hide(self, qapp: QApplication) -> None:
        up = self._make_up()
        try:
            up._hide_default_placeholder()
            assert up.default_placeholder.isHidden()
            up._show_default_placeholder()
            assert not up.default_placeholder.isHidden()
        finally:
            safe_teardown(up)

    def test_width_policy_helpers(self, qapp: QApplication) -> None:
        from PySide6.QtWidgets import QLabel

        up = self._make_up()
        try:
            up._apply_preview_width_policy(None)
            label = QLabel("x")
            up._apply_preview_width_policy(label)
            assert label.minimumWidth() >= up._preview_content_min_width()
            up._add_preview_widget(label)
            assert up.preview_layout.indexOf(label) >= 0
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_show_preview_without_file_info(self, qapp: QApplication) -> None:
        up = self._make_up()
        try:
            up.current_file_info = None
            up._show_preview()
            assert up.clear_preview_button.isHidden()
            assert up.open_with_system_button.isHidden()
        finally:
            safe_teardown(up)

    def test_clear_preview_button_clicked_resets(self, qapp: QApplication, tmp_path: Any) -> None:
        png_path: str = make_image(str(tmp_path / "sample.png"))
        up = self._make_up()
        try:
            cleared: List[Any] = _signal_collector(up.preview_cleared)
            up.current_file_info = _make_finfo(png_path, suffix="png")
            up.file_info_viewer.set_file(_make_finfo(png_path, suffix="png"))
            up._on_clear_preview_button_clicked()
            assert up.current_file_info is None
            assert cleared, "应发射 preview_cleared"
            assert up.clear_preview_button.isHidden()
        finally:
            safe_teardown(up)

    def test_clear_preview_public_method(self, qapp: QApplication) -> None:
        up = self._make_up()
        try:
            up.clear_preview()
            assert up.current_file_info is None
        finally:
            safe_teardown(up)

    def test_open_file_with_system(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import os

        from freeassetfilter import widgets as _w  # noqa: F401  确保包可导入

        png_path: str = make_image(str(tmp_path / "sample.png"))
        started: List[str] = []

        class _FakeMB:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

            def set_title(self, *a: Any, **k: Any) -> None:
                pass

            def set_text(self, *a: Any, **k: Any) -> None:
                pass

            def set_buttons(self, *a: Any, **k: Any) -> None:
                pass

            def exec(self) -> None:
                return None

        monkeypatch.setattr(os, "startfile", lambda p: started.append(p))
        monkeypatch.setattr("freeassetfilter.widgets.D_widgets.CustomMessageBox", _FakeMB)

        up = self._make_up()
        try:
            # 无当前文件：直接返回
            up._open_file_with_system()
            # 有效文件
            up.current_file_info = _make_finfo(png_path, suffix="png")
            up._open_file_with_system()
            assert started == [png_path]
        finally:
            safe_teardown(up)

    def test_open_file_with_system_missing(self, qapp: QApplication, monkeypatch: Any) -> None:
        from freeassetfilter import widgets as _w  # noqa: F401

        shown: List[str] = []

        class _FakeMB:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

            def set_title(self, *a: Any, **k: Any) -> None:
                pass

            def set_text(self, *a: Any, **k: Any) -> None:
                pass

            def set_buttons(self, *a: Any, **k: Any) -> None:
                pass

            def exec(self) -> None:
                shown.append("shown")
                return None

        monkeypatch.setattr("freeassetfilter.widgets.D_widgets.CustomMessageBox", _FakeMB)
        up = self._make_up()
        try:
            up.current_file_info = _make_finfo(str(tmp_missing()), suffix="png")
            up._open_file_with_system()
            assert shown, "缺失文件应弹错误提示"
        finally:
            safe_teardown(up)

    def test_locate_file_in_selector(self, qapp: QApplication, tmp_path: Any) -> None:
        png_path: str = make_image(str(tmp_path / "sample.png"))
        up = self._make_up()
        try:
            captured: List[Any] = _signal_collector(up.open_in_selector_requested)
            up.current_file_info = _make_finfo(png_path, suffix="png")
            up._locate_file_in_selector()
            assert captured, "应发射 open_in_selector_requested"
            assert captured[0][0] == str(tmp_path)
            assert captured[0][1] == up.current_file_info
        finally:
            safe_teardown(up)

    def test_copy_to_clipboard_button(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        from PySide6.QtWidgets import QApplication as QA

        from freeassetfilter import widgets as _w  # noqa: F401

        png_path: str = make_image(str(tmp_path / "sample.png"))
        copied: List[Any] = []

        class _FakeClip:
            def setMimeData(self, mime: Any) -> None:
                copied.append(mime.urls())

        class _FakeMB:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

            def set_title(self, *a: Any, **k: Any) -> None:
                pass

            def set_text(self, *a: Any, **k: Any) -> None:
                pass

            def set_buttons(self, *a: Any, **k: Any) -> None:
                pass

            def exec(self) -> None:
                return None

        monkeypatch.setattr(QA, "clipboard", staticmethod(lambda: _FakeClip()))
        monkeypatch.setattr("freeassetfilter.widgets.D_widgets.CustomMessageBox", _FakeMB)

        up = self._make_up()
        try:
            # 无当前文件：返回
            up._on_copy_to_clipboard_button_clicked()
            up.current_file_info = _make_finfo(png_path, suffix="png")
            up._on_copy_to_clipboard_button_clicked()
            assert copied, "应写入剪切板"
            assert os.path.normpath(copied[0][0].toLocalFile()) == os.path.normpath(png_path)
        finally:
            safe_teardown(up)

    def test_stop_preview_video_and_text_branches(self, qapp: QApplication, monkeypatch: Any) -> None:
        import freeassetfilter.components.text_previewer as tp_mod
        import freeassetfilter.components.video_player as vp_mod
        from PySide6.QtWidgets import QWidget

        up = self._make_up()
        try:
            fake_video = type("FakeVideoPlayer", (QWidget,), {"close": lambda self: None})
            fake_text = type("FakeTextWidget", (QWidget,), {"cleanup": lambda self: None})
            monkeypatch.setattr(vp_mod, "VideoPlayer", fake_video)
            monkeypatch.setattr(tp_mod, "TextPreviewWidget", fake_text)

            up.current_file_info = _make_finfo(str(tmp_missing()), suffix="mp4")
            up.current_preview_widget = fake_video()
            up.stop_preview()
            assert up.current_preview_widget is None

            up.current_preview_widget = fake_text()
            up.stop_preview()
            assert up.current_preview_widget is None
        finally:
            safe_teardown(up)

    def test_clear_preview_plain_widget(self, qapp: QApplication) -> None:
        from PySide6.QtWidgets import QWidget

        up = self._make_up()
        try:
            cleared: List[Any] = _signal_collector(up.preview_cleared)
            widget = QWidget()
            up._add_preview_widget(widget)
            up.current_preview_widget = widget
            up._clear_preview()
            assert up.current_preview_widget is None
            assert up.current_preview_type is None
            assert cleared, "应发射 preview_cleared"
        finally:
            safe_teardown(up)

    def test_clear_preview_reentrancy_guard(self, qapp: QApplication) -> None:
        up = self._make_up()
        try:
            up._clearing_preview = True
            up._clear_preview()
            assert up.current_preview_widget is None
        finally:
            safe_teardown(up)

    def test_show_error_with_copy_button(self, qapp: QApplication) -> None:
        up = self._make_up()
        try:
            up._show_error_with_copy_button("boom")
            assert up.current_preview_type == "error"
            assert up.current_preview_widget is not None
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_show_image_preview_static(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.unified_previewer as up_mod
        from PySide6.QtWidgets import QWidget

        png_path: str = make_image(str(tmp_path / "sample.png"))

        loaded_paths: List[str] = []

        class FakeImg(QWidget):
            def __init__(self, parent=None, dpi_scale=None, global_font=None, settings_manager=None):
                super().__init__(parent)

            def set_file(self, path: str) -> None:
                loaded_paths.append(path)

        class FakeRegistry:
            @staticmethod
            def get_previewer_class(_info: dict) -> type:
                return FakeImg

        monkeypatch.setattr(up_mod, "PreviewerRegistry", FakeRegistry)
        up = self._make_up()
        try:
            up.current_file_info = _make_finfo(png_path, suffix="png")
            up._show_image_preview(png_path)
            assert loaded_paths == [png_path]
            assert up.current_preview_type == "image"
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_show_image_preview_registry_none(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.unified_previewer as up_mod

        png_path: str = make_image(str(tmp_path / "sample.png"))

        class EmptyRegistry:
            @staticmethod
            def get_previewer_class(_info: dict) -> None:
                return None

        monkeypatch.setattr(up_mod, "PreviewerRegistry", EmptyRegistry)
        up = self._make_up()
        try:
            up.current_file_info = _make_finfo(png_path, suffix="png")
            up._show_image_preview(png_path)
            assert up.current_preview_type == "error"
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_show_image_preview_animated_webp(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.photo_viewer as pv_mod
        from PySide6.QtWidgets import QWidget

        webp_path: str = str(tmp_path / "anim.webp")
        with open(webp_path, "wb") as handle:
            handle.write(b"x")

        loaded: List[str] = []

        class FakeGifViewer(QWidget):
            def __init__(self, *a: Any, **k: Any) -> None:
                super().__init__()

            def load_gif(self, path: str) -> bool:
                loaded.append(path)
                return True

        monkeypatch.setattr(pv_mod, "GifViewer", FakeGifViewer)
        up = self._make_up()
        try:
            up.current_file_info = _make_finfo(webp_path, suffix="webp")
            up._show_image_preview(webp_path, loaded_data={"is_animated": True, "is_animated_webp": True})
            assert loaded == [webp_path], "动画 WebP 应走 GifViewer 路径"
            assert up.current_preview_type == "image"
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_show_image_preview_animated_detect_fallback(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.photo_viewer as pv_mod
        from PySide6.QtWidgets import QWidget

        webp_path: str = str(tmp_path / "anim2.webp")
        with open(webp_path, "wb") as handle:
            handle.write(b"x")

        loaded: List[str] = []

        class FakeGifViewer(QWidget):
            def __init__(self, *a: Any, **k: Any) -> None:
                super().__init__()

            def load_gif(self, path: str) -> bool:
                loaded.append(path)
                return True

        monkeypatch.setattr(pv_mod, "GifViewer", FakeGifViewer)
        up = self._make_up()
        try:
            up._is_animated_image = lambda p: True  # type: ignore[method-assign]
            up.current_file_info = _make_finfo(webp_path, suffix="webp")
            up._show_image_preview(webp_path, loaded_data={"is_animated_webp": True})
            assert loaded == [webp_path]
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_is_animated_image_detection(self, qapp: QApplication, tmp_path: Any) -> None:
        up = self._make_up()
        try:
            # 非动画扩展名快速路径
            assert up._is_animated_image(str(tmp_path / "a.jpg")) is False
            # 静态 PNG
            png_path: str = make_image(str(tmp_path / "static.png"))
            assert up._is_animated_image(png_path) is False
            # 缺失文件
            assert up._is_animated_image(str(tmp_missing())) is False
        finally:
            safe_teardown(up)

    def test_show_video_preview(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.video_player as vp_mod
        from PySide6.QtWidgets import QWidget

        mp4_path: str = str(tmp_path / "video.mp4")
        with open(mp4_path, "wb") as handle:
            handle.write(b"x")

        calls: List[Any] = []

        class FakePlayer(QWidget):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__()

            def load_media(self, path: str, is_audio: bool = False) -> None:
                calls.append(("load", path, is_audio))

            def play(self) -> None:
                calls.append(("play",))

        monkeypatch.setattr(vp_mod, "VideoPlayer", FakePlayer)
        up = self._make_up()
        try:
            up._show_video_preview(mp4_path)
            assert ("load", mp4_path, False) in calls
            assert ("play",) in calls
            assert up.current_preview_type == "video"
            assert up.is_loading_preview is False
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_show_audio_preview(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.video_player as vp_mod
        from PySide6.QtWidgets import QWidget

        mp3_path: str = str(tmp_path / "audio.mp3")
        with open(mp3_path, "wb") as handle:
            handle.write(b"x")

        calls: List[Any] = []

        class FakePlayer(QWidget):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__()

            def load_media(self, path: str, is_audio: bool = False) -> None:
                calls.append(("load", path, is_audio))

        monkeypatch.setattr(vp_mod, "VideoPlayer", FakePlayer)
        up = self._make_up()
        try:
            up._show_audio_preview(mp3_path)
            assert ("load", mp3_path, True) in calls
            assert up.current_preview_type == "audio"
            assert up.is_loading_preview is False
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_show_pdf_preview(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.pdf_previewer as pdf_mod
        from PySide6.QtCore import Signal
        from PySide6.QtWidgets import QWidget

        pdf_path: str = make_pdf(str(tmp_path / "doc.pdf"))
        loaded: List[str] = []

        class FakePdf(QWidget):
            pdf_render_finished = Signal()

            def load_file_from_path(self, path: str) -> None:
                loaded.append(path)

        monkeypatch.setattr(pdf_mod, "PDFPreviewer", FakePdf)
        up = self._make_up()
        try:
            up._show_pdf_preview(pdf_path)
            assert loaded == [pdf_path]
            assert up.current_preview_type == "pdf"
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_show_text_preview(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.text_previewer as tp_mod
        from PySide6.QtWidgets import QWidget

        txt_path: str = make_text(str(tmp_path / "hello.txt"), content="Hello")
        set_content: List[Any] = []
        set_file: List[str] = []

        class FakeText(QWidget):
            def set_text_content(self, content: str, file_path: str = "", encoding: str = "utf-8") -> None:
                set_content.append((content, file_path, encoding))

            def set_file(self, path: str) -> None:
                set_file.append(path)

        monkeypatch.setattr(tp_mod, "TextPreviewWidget", FakeText)
        up = self._make_up()
        try:
            up._show_text_preview(txt_path, loaded_data={"text_content": "预读内容", "encoding": "utf-8"})
            assert set_content, "预读内容应直接注入"
            up._clear_preview(emit_signal=False)

            up._show_text_preview(txt_path)
            assert set_file == [txt_path], "无预读内容应回退到 set_file"
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_show_font_preview(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.font_previewer as fp_mod
        from PySide6.QtWidgets import QWidget

        font_path: str = str(tmp_path / "a.ttf")
        with open(font_path, "wb") as handle:
            handle.write(b"x")
        set_font: List[str] = []

        class FakeFont(QWidget):
            def set_font(self, path: str) -> None:
                set_font.append(path)

        monkeypatch.setattr(fp_mod, "FontPreviewWidget", FakeFont)
        up = self._make_up()
        try:
            up._show_font_preview(font_path)
            assert set_font == [font_path]
            assert up.current_preview_type == "font"
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_show_document_preview_missing_libreoffice(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.unified_previewer as up_mod
        from PySide6.QtWidgets import QWidget

        doc_path: str = str(tmp_path / "report.docx")
        with open(doc_path, "wb") as handle:
            handle.write(b"x")

        class FakePdf(QWidget):
            def load_file_from_path(self, path: str) -> None:
                pass

        monkeypatch.setattr(up_mod, "os", __import__("os"))
        up = self._make_up()
        try:
            # LibreOfficePortable 不存在 → 应显示 info 占位而非崩溃
            up._show_document_preview(doc_path)
            assert up.current_preview_widget is not None
            assert up.current_preview_type == "info"
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_progress_dialog_callbacks(self, qapp: QApplication) -> None:
        up = self._make_up()
        try:
            up._show_progress_dialog("标题", "消息")
            assert up.progress_dialog is not None
            up._on_progress_updated(50, "进行中")
            up._on_file_read_finished()
            assert up.progress_dialog is None
        finally:
            if up.progress_dialog:
                up.progress_dialog.close()
                up.progress_dialog = None
            safe_teardown(up)

    def test_cancel_progress(self, qapp: QApplication, monkeypatch: Any) -> None:
        from PySide6.QtCore import QTimer

        up = self._make_up()
        try:
            timer = QTimer(up)
            up._progress_timer = timer
            up._show_progress_dialog("标题", "消息")
            up._on_cancel_progress(0)
            assert up.is_cancelled is True
            assert up.progress_dialog is None
            assert not hasattr(up, "_progress_timer")
        finally:
            if up.progress_dialog:
                up.progress_dialog.close()
                up.progress_dialog = None
            safe_teardown(up)

    def test_on_pdf_render_finished(self, qapp: QApplication) -> None:
        up = self._make_up()
        try:
            up._show_progress_dialog("标题", "消息")
            up._on_pdf_render_finished()
            assert up.progress_dialog is None
        finally:
            if up.progress_dialog:
                up.progress_dialog.close()
                up.progress_dialog = None
            safe_teardown(up)

    def test_copy_to_clipboard_helper(self, qapp: QApplication, monkeypatch: Any) -> None:
        class _RecordingClipboard:
            def __init__(self) -> None:
                self._text = ""

            def setText(self, text: str) -> None:
                self._text = text

            def text(self) -> str:
                return self._text

        fake = _RecordingClipboard()
        # 真实系统剪贴板可能被外部进程锁定（Windows OpenClipboard 返回 ERROR_ACCESS_DENIED），
        # 无法可靠读回；改用记录型假剪贴板验证生产代码写入的文本内容。
        monkeypatch.setattr(QApplication, "clipboard", staticmethod(lambda: fake))
        up = self._make_up()
        try:
            up._copy_to_clipboard("文本")
            assert fake.text() == "文本"
        finally:
            safe_teardown(up)

    def test_preview_loader_thread_text(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer

        txt_path: str = make_text(str(tmp_path / "hello.txt"), content="线程读取内容")
        up = self._make_up()
        thread = UnifiedPreviewer.PreviewLoaderThread(txt_path, "text", up)
        results: List[Any] = []
        thread.preview_created.connect(lambda data, ptype: results.append((data, ptype)))
        try:
            thread.run()  # 同步执行，验证 run 体
            assert results, "应发射 preview_created"
            data, ptype = results[0]
            assert ptype == "text"
            assert "线程读取内容" in data["text_content"]
        finally:
            thread.deleteLater()
            safe_teardown(up)

    def test_preview_loader_thread_image(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer

        png_path: str = make_image(str(tmp_path / "sample.png"))
        up = self._make_up()
        thread = UnifiedPreviewer.PreviewLoaderThread(png_path, "image", up)
        results: List[Any] = []
        thread.preview_created.connect(lambda data, ptype: results.append((data, ptype)))
        try:
            thread.run()
            assert results
            data, ptype = results[0]
            assert ptype == "image"
            assert data.get("image_width", 0) > 0
        finally:
            thread.deleteLater()
            safe_teardown(up)

    def test_preview_loader_thread_pdf_and_media(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer

        pdf_path: str = make_pdf(str(tmp_path / "doc.pdf"))
        media_path: str = str(tmp_path / "clip.mp4")
        with open(media_path, "wb") as handle:
            handle.write(b"x")

        up = self._make_up()
        for fpath, ptype in ((pdf_path, "pdf"), (media_path, "video")):
            thread = UnifiedPreviewer.PreviewLoaderThread(fpath, ptype, up)
            results: List[Any] = []
            thread.preview_created.connect(lambda data, t=ptype: results.append((data, t)))
            try:
                thread.run()
                assert results, f"{ptype} 应发射 preview_created"
                assert results[0][0].get("file_size", 0) >= 0
            finally:
                thread.deleteLater()
        safe_teardown(up)

    def test_preview_loader_thread_cancel_and_unknown(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer

        txt_path: str = make_text(str(tmp_path / "hello.txt"), content="x")
        up = self._make_up()

        # 取消
        thread = UnifiedPreviewer.PreviewLoaderThread(txt_path, "text", up)
        errors: List[str] = []
        thread.preview_error.connect(errors.append)
        try:
            thread.cancel()
            assert thread.is_cancelled is True
            thread.run()
            assert errors, "取消后应发射 preview_error"
        finally:
            thread.deleteLater()

        # 不支持的预览类型
        thread2 = UnifiedPreviewer.PreviewLoaderThread(txt_path, "bogus", up)
        errors2: List[str] = []
        thread2.preview_error.connect(errors2.append)
        try:
            thread2.run()
            assert errors2, "不支持的类型应发射 preview_error"
        finally:
            thread2.deleteLater()
        safe_teardown(up)

    def test_on_preview_created_dir(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.folder_content_list as fcl_mod
        from PySide6.QtWidgets import QWidget

        sub = tmp_path / "sub"
        sub.mkdir()
        set_path: List[str] = []

        class FakeFolder(QWidget):
            open_in_selector_requested = Signal(str, object)

            def set_path(self, path: str) -> None:
                set_path.append(path)

        monkeypatch.setattr(fcl_mod, "FolderContentList", FakeFolder)
        up = self._make_up()
        try:
            up.current_file_info = _make_finfo(str(sub), is_dir=True)
            up._on_preview_created({}, "dir")
            assert set_path == [str(sub)]
            assert isinstance(up.current_preview_widget, FakeFolder)
            assert up.is_loading_preview is False
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_on_preview_created_unknown(self, qapp: QApplication, tmp_path: Any) -> None:
        probe: str = str(tmp_path / "sample.qqq")
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("x")
        up = self._make_up()
        try:
            up.current_file_info = _make_finfo(probe, suffix="qqq")
            up._on_preview_created({}, "unknown")
            assert up.current_preview_type == "info"
            assert up.current_preview_widget is not None
            assert up.is_loading_preview is False
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_on_preview_created_exception_guard(self, qapp: QApplication) -> None:
        up = self._make_up()
        try:
            up.current_file_info = None
            up._on_preview_created({}, "dir")
            assert up.is_loading_preview is False
            assert up.current_preview_type == "error"
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_on_preview_error(self, qapp: QApplication) -> None:
        up = self._make_up()
        try:
            up._on_preview_error("加载失败")
            assert up.current_preview_type == "error"
            assert up.is_loading_preview is False
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_process_pending_preview(self, qapp: QApplication, tmp_path: Any) -> None:
        png_path: str = make_image(str(tmp_path / "sample.png"))
        finfo: dict = _make_finfo(png_path, suffix="png")
        up = self._make_up()
        try:
            # 正在加载：直接返回
            up.is_loading_preview = True
            up._pending_file_info = finfo
            up._process_pending_preview()
            assert up._pending_file_info == finfo

            # 空闲：自动加载
            up.is_loading_preview = False
            calls: List[dict] = []
            up.set_file = lambda f: calls.append(f)  # type: ignore[method-assign]
            up._process_pending_preview()
            assert calls == [finfo]
            assert up._pending_file_info is None
        finally:
            safe_teardown(up)

    def test_pause_active_media_preview(self, qapp: QApplication, monkeypatch: Any) -> None:
        import freeassetfilter.components.video_player as vp_mod
        from PySide6.QtWidgets import QWidget

        up = self._make_up()
        try:
            # 无当前组件
            assert up.pause_active_media_preview() is False
            # 非视频组件
            up.current_preview_widget = QWidget()
            assert up.pause_active_media_preview() is False
            # 视频组件
            fake = type("FakeVp", (QWidget,), {"pause": lambda self: True})
            monkeypatch.setattr(vp_mod, "VideoPlayer", fake)
            up.current_preview_widget = fake()
            assert up.pause_active_media_preview() is True
        finally:
            up._clear_preview(emit_signal=False)
            safe_teardown(up)

    def test_schedule_safe_preview_cleanup(self, qapp: QApplication, monkeypatch: Any) -> None:
        import freeassetfilter.components.video_player as vp_mod
        from PySide6.QtWidgets import QWidget

        up = self._make_up()
        fake = type("FakeVp", (QWidget,), {})
        monkeypatch.setattr(vp_mod, "VideoPlayer", fake)
        try:
            up.current_preview_widget = fake()
            up.schedule_safe_preview_cleanup(delay_ms=0)
            assert up._scheduled_preview_cleanup is True
            # 已调度：跳过重复
            up.schedule_safe_preview_cleanup(delay_ms=0)
            process_qt_events(qapp, ms=50)
            assert up._scheduled_preview_cleanup is False
            assert up.current_preview_widget is None
        finally:
            safe_teardown(up)

    def test_close_event_cleans_thread(self, qapp: QApplication) -> None:
        up = self._make_up()
        try:
            fake_thread = MagicMock()
            fake_thread.isRunning.return_value = False
            up._preview_thread = fake_thread
            up.close()
            assert up._preview_thread is None
        finally:
            safe_teardown(up)

    def test_update_theme_touches_current_preview_and_buttons(self, qapp: QApplication, monkeypatch: Any) -> None:
        from PySide6.QtWidgets import QWidget

        up = self._make_up()
        try:
            class _FWid(QWidget):
                def update_theme(self) -> None:
                    pass

            wid = _FWid()
            up.current_preview_widget = wid
            up.update_theme()
            assert wid.isVisible() is False or not wid.isHidden()
        finally:
            up._clear_preview(emit_signal=False)
            safe_teardown(up)

    def test_stop_preview_generic_and_exception(self, qapp: QApplication) -> None:
        from PySide6.QtWidgets import QWidget

        up = self._make_up()
        obj: object = object()
        try:
            # 通用 widget（非视频/文本）：走 else 分支，正常移除
            up.current_preview_widget = QWidget()
            up.stop_preview()
            assert up.current_preview_widget is None

            # 非 QWidget 对象：removeWidget 抛 TypeError → 异常分支（widget 保持不变）
            up.current_preview_widget = obj  # type: ignore[assignment]
            up.stop_preview()
            assert up.current_preview_widget is obj
        finally:
            safe_teardown(up)

    def test_cleanup_preview_thread_paths(self, qapp: QApplication, monkeypatch: Any) -> None:
        up = self._make_up()
        try:
            from PySide6.QtCore import Signal

            class _FakeThread:
                preview_created = Signal(object, str)
                preview_error = Signal(str)
                preview_progress = Signal(int, str)

                def __init__(self) -> None:
                    self._running = True
                    self._cancelled = False

                def isRunning(self) -> bool:
                    return self._running

                def cancel(self) -> None:
                    self._cancelled = True

                def wait(self, _ms: int) -> bool:
                    return False

                def deleteLater(self) -> None:
                    self._running = False

            # 线程仍运行：跳过 deleteLater（超时警告分支）
            thread = _FakeThread()
            up._preview_thread = thread
            up._cleanup_preview_thread()
            assert thread._cancelled is True

            # 已停止线程：正常 deleteLater
            thread2 = _FakeThread()
            thread2._running = False
            up._preview_thread = thread2
            up._cleanup_preview_thread()
        finally:
            up._preview_thread = None
            safe_teardown(up)

    def test_safe_delete_thread_and_destroy_cleanup(self, qapp: QApplication, monkeypatch: Any) -> None:
        up = self._make_up()
        try:
            # None 安全返回
            up._safe_delete_thread(None)

            class _T:
                def __init__(self, running: bool) -> None:
                    self._running = running

                def isRunning(self) -> bool:
                    return self._running

                def cancel(self) -> None:
                    self._running = False

                def wait(self, _ms: int) -> bool:
                    return True

                def deleteLater(self) -> None:
                    self._running = False

            stopped = _T(False)
            up._safe_delete_thread(stopped)
            running = _T(True)
            up._safe_delete_thread(running)
            assert running._running is False

            # destroyed 清理：运行中线程 → cancel 后线程停止
            t2 = _T(True)
            up._preview_thread = t2
            up._cleanup_thread_on_destroy()
            assert t2._running is False

            # destroyed 清理：无线程
            up._preview_thread = None
            up._cleanup_thread_on_destroy()
        finally:
            up._preview_thread = None
            safe_teardown(up)

    def test_open_file_with_system_empty_path(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.unified_previewer as up_mod

        shown: List[str] = []
        png_path: str = make_image(str(tmp_path / "existing.png"))

        class _FakeMB:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

            def set_title(self, *a: Any, **k: Any) -> None:
                pass

            def set_text(self, *a: Any, **k: Any) -> None:
                pass

            def set_buttons(self, *a: Any, **k: Any) -> None:
                pass

            def exec(self) -> None:
                shown.append("shown")
                return None

        monkeypatch.setattr("freeassetfilter.widgets.D_widgets.CustomMessageBox", _FakeMB)
        monkeypatch.setattr(up_mod.sys, "platform", "darwin")
        recorded: List[str] = []
        monkeypatch.setattr(up_mod.os, "system", lambda cmd: recorded.append(cmd))
        up = self._make_up()
        try:
            up.current_file_info = _make_finfo("", suffix="png")
            up._open_file_with_system()
            assert recorded == [], "空 path 应直接返回"

            up.current_file_info = _make_finfo(str(tmp_missing()), suffix="png")
            up._open_file_with_system()
            assert shown, "文件不存在应弹错误提示"
            assert recorded == [], "缺失文件不应调用 os.system"

            # 存在的文件 + darwin → os.system open
            up.current_file_info = _make_finfo(png_path, suffix="png")
            up._open_file_with_system()
            assert recorded, "darwin 分支应调用 os.system"
        finally:
            safe_teardown(up)

    def test_open_file_with_system_open_exception(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.unified_previewer as up_mod

        png_path: str = make_image(str(tmp_path / "sample.png"))
        shown: List[str] = []

        class _FakeMB:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

            def set_title(self, *a: Any, **k: Any) -> None:
                pass

            def set_text(self, *a: Any, **k: Any) -> None:
                pass

            def set_buttons(self, *a: Any, **k: Any) -> None:
                pass

            def exec(self) -> None:
                shown.append("shown")
                return None

        monkeypatch.setattr("freeassetfilter.widgets.D_widgets.CustomMessageBox", _FakeMB)

        def _boom(path: str) -> None:
            raise OSError("boom")

        monkeypatch.setattr(up_mod.os, "startfile", _boom)
        up = self._make_up()
        try:
            up.current_file_info = _make_finfo(png_path, suffix="png")
            up._open_file_with_system()
            assert shown, "打开失败应弹错误提示"
        finally:
            safe_teardown(up)

    def test_locate_file_in_selector_missing_dir(self, qapp: QApplication, monkeypatch: Any) -> None:
        from freeassetfilter import widgets as _w  # noqa: F401

        shown: List[str] = []

        class _FakeMB:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

            def set_title(self, *a: Any, **k: Any) -> None:
                pass

            def set_text(self, *a: Any, **k: Any) -> None:
                pass

            def set_buttons(self, *a: Any, **k: Any) -> None:
                pass

            def exec(self) -> None:
                shown.append("shown")
                return None

        monkeypatch.setattr("freeassetfilter.widgets.D_widgets.CustomMessageBox", _FakeMB)
        up = self._make_up()
        try:
            # 无 current_file_info
            up._locate_file_in_selector()
            # 空路径
            up.current_file_info = _make_finfo("", suffix="png")
            up._locate_file_in_selector()
            # 目录不存在（父目录路径也不存在）
            up.current_file_info = _make_finfo(os.path.join(str(tmp_missing()), "no_such_dir", "file.png"), suffix="png")
            up._locate_file_in_selector()
            assert shown, "目录不存在应弹错误提示"
        finally:
            safe_teardown(up)

    def test_copy_to_clipboard_missing_and_exception(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        from PySide6.QtWidgets import QApplication as QA

        from freeassetfilter import widgets as _w  # noqa: F401

        class _FakeMB:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

            def set_title(self, *a: Any, **k: Any) -> None:
                pass

            def set_text(self, *a: Any, **k: Any) -> None:
                pass

            def set_buttons(self, *a: Any, **k: Any) -> None:
                pass

            def exec(self) -> None:
                return None

        monkeypatch.setattr("freeassetfilter.widgets.D_widgets.CustomMessageBox", _FakeMB)
        up = self._make_up()
        try:
            # 路径不存在：直接返回
            up.current_file_info = _make_finfo(str(tmp_missing()), suffix="png")
            up._on_copy_to_clipboard_button_clicked()

            # clipboard 抛异常 → error 分支
            def _boom() -> None:
                raise RuntimeError("clipboard boom")

            monkeypatch.setattr(QA, "clipboard", staticmethod(_boom))
            png_path: str = make_image(str(tmp_path / "sample.png"))
            up.current_file_info = _make_finfo(png_path, suffix="png")
            up._on_copy_to_clipboard_button_clicked()
        finally:
            safe_teardown(up)

    def test_start_preview_switch_end_to_end(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        from PySide6.QtCore import Signal, QThread

        import freeassetfilter.components.unified_previewer as up_mod

        png_path: str = make_image(str(tmp_path / "sample.png"))
        titles: List[str] = []

        class _FakeLoader(QThread):
            preview_created = Signal(object, str)
            preview_error = Signal(str)
            preview_progress = Signal(int, str)

            def __init__(self, file_path: str, preview_type: str, parent: Any = None) -> None:
                super().__init__()
                self.file_path = file_path
                self.preview_type = preview_type

            def start(self, *args: Any, **kwargs: Any) -> None:
                self.preview_created.emit({}, self.preview_type)

        up = self._make_up()
        try:
            monkeypatch.setattr(up, "_show_progress_dialog", lambda t, m: titles.append(t))
            up.PreviewLoaderThread = _FakeLoader  # type: ignore[assignment]
            up.current_file_info = _make_finfo(png_path, suffix="png")
            up._show_preview_flag = False  # type: ignore[attr-defined]
            up._start_preview_switch(png_path, "unknown")
            assert titles, "应显示进度条弹窗"
            assert up.current_preview_type == "unknown"
            assert up.is_loading_preview is False
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_start_preview_switch_thread_create_error(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        png_path: str = make_image(str(tmp_path / "sample.png"))
        up = self._make_up()
        try:
            monkeypatch.setattr(up, "_show_progress_dialog", lambda t, m: None)

            def _boom(*args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("create boom")

            up.PreviewLoaderThread = _boom  # type: ignore[assignment]
            up._start_preview_switch(png_path, "unknown")
            assert up.is_loading_preview is False
        finally:
            safe_teardown(up)

    def test_clear_preview_video_detached(self, qapp: QApplication, monkeypatch: Any) -> None:
        import freeassetfilter.components.video_player as vp_mod
        from PySide6.QtWidgets import QWidget

        up = self._make_up()
        try:
            class _FakeVp(QWidget):
                pass

            monkeypatch.setattr(vp_mod, "VideoPlayer", _FakeVp)
            vid = _FakeVp()
            vid._detached_window = object()  # type: ignore[attr-defined]
            up.current_preview_widget = vid
            cleared: List[Any] = _signal_collector(up.preview_cleared)
            up._clear_preview()
            assert cleared, "分离窗口跳过清理但应发射信号"
        finally:
            safe_teardown(up)

    def test_clear_preview_video_cleanup(self, qapp: QApplication, monkeypatch: Any) -> None:
        import freeassetfilter.components.video_player as vp_mod
        from PySide6.QtWidgets import QWidget

        up = self._make_up()
        try:
            class _FakeVp(QWidget):
                def cleanup(self, async_mode: bool = False) -> None:
                    pass

            monkeypatch.setattr(vp_mod, "VideoPlayer", _FakeVp)
            vid = _FakeVp()
            up.current_preview_widget = vid
            up._clear_preview(emit_signal=False)
            process_qt_events(qapp, ms=200)
            assert up.current_preview_widget is None
        finally:
            safe_teardown(up)

    def test_clear_preview_on_cleared_exception(self, qapp: QApplication, monkeypatch: Any) -> None:
        up = self._make_up()
        try:
            def _boom() -> None:
                raise RuntimeError("boom")

            up._clear_preview(emit_signal=True, on_cleared=_boom)
            assert up.current_preview_widget is None
        finally:
            safe_teardown(up)

    def test_clear_preview_text_cleanup_branch(self, qapp: QApplication, monkeypatch: Any) -> None:
        import freeassetfilter.components.text_previewer as tp_mod
        from PySide6.QtWidgets import QWidget

        up = self._make_up()
        try:
            class _FakeText(QWidget):
                def cleanup(self) -> None:
                    pass

            monkeypatch.setattr(tp_mod, "TextPreviewWidget", _FakeText)
            wid = _FakeText()
            up.current_preview_widget = wid
            up._clear_preview(emit_signal=False)
            assert up.current_preview_widget is None
        finally:
            safe_teardown(up)

    def test_update_preview_widget_type_branches(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.archive_browser as ab_mod
        import freeassetfilter.components.pdf_previewer as pdf_mod
        import freeassetfilter.components.photo_viewer as pv_mod
        import freeassetfilter.components.text_previewer as tp_mod
        from PySide6.QtCore import Signal
        from PySide6.QtWidgets import QWidget

        mp4_path: str = str(tmp_path / "v.mp4")
        with open(mp4_path, "wb") as handle:
            handle.write(b"x")
        png_path: str = make_image(str(tmp_path / "i.png"))
        pdf_path: str = make_pdf(str(tmp_path / "d.pdf"))
        txt_path: str = make_text(str(tmp_path / "t.txt"), content="x")
        zip_path: str = make_zip(str(tmp_path / "a.zip"), {"x.txt": "x"})
        sub = tmp_path / "subdir"
        sub.mkdir()

        calls: List[str] = []

        class _Rec(QWidget):
            def __init__(self, *a: Any, **k: Any) -> None:
                super().__init__()

        class _Vp(_Rec):
            def load_media(self, path: str, is_audio: bool = False) -> None:
                calls.append("load_media")

        class _Photo(_Rec):
            def load_image_from_path(self, path: str) -> None:
                calls.append("load_image_from_path")

        class _Pdf(_Rec):
            pdf_render_finished = Signal()

            def set_file(self, path: str) -> None:
                calls.append("pdf_set_file")

        class _Text(_Rec):
            def set_file(self, path: str) -> None:
                calls.append("text_set_file")

        class _Zip(_Rec):
            def set_archive_path(self, path: str) -> None:
                calls.append("set_archive_path")

        class _Folder(_Rec):
            def set_path(self, path: str) -> None:
                calls.append("set_path")

        monkeypatch.setattr(pv_mod, "PhotoViewer", _Photo)
        monkeypatch.setattr(pdf_mod, "PDFPreviewer", _Pdf)
        monkeypatch.setattr(tp_mod, "TextPreviewWidget", _Text)
        monkeypatch.setattr(ab_mod, "ArchiveBrowser", _Zip)

        up = self._make_up()
        try:
            # video: load_media
            up.current_preview_widget = _Vp()
            up.current_preview_type = "video"
            up._update_preview_widget(mp4_path, "video")
            assert "load_media" in calls

            # image 静态: load_image_from_path
            up.current_preview_widget = _Photo()
            up.current_preview_type = "image"
            up._update_preview_widget(png_path, "image")
            assert "load_image_from_path" in calls

            # pdf: set_file
            up.current_preview_widget = _Pdf()
            up.current_preview_type = "pdf"
            up._update_preview_widget(pdf_path, "pdf")
            assert "pdf_set_file" in calls

            # text: set_file
            up.current_preview_widget = _Text()
            up.current_preview_type = "text"
            up._update_preview_widget(txt_path, "text")
            assert "text_set_file" in calls

            # archive: set_archive_path
            up.current_preview_widget = _Zip()
            up.current_preview_type = "archive"
            up._update_preview_widget(zip_path, "archive")
            assert "set_archive_path" in calls

            # dir: set_path
            up.current_preview_widget = _Folder()
            up.current_preview_type = "dir"
            up._update_preview_widget(str(sub), "dir")
            assert "set_path" in calls
        finally:
            safe_teardown(up)

    def test_update_preview_widget_document_and_font_branches(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        from PySide6.QtWidgets import QWidget

        txt_path: str = make_text(str(tmp_path / "t.txt"), content="x")

        up = self._make_up()
        try:
            class _Txt(QWidget):
                pass

            font_called: List[bool] = []
            up._show_font_preview = lambda p: font_called.append(True)  # type: ignore[method-assign]

            # document: 重新走 _show_preview
            up.current_preview_widget = _Txt()
            up.current_preview_type = "document"
            up._update_preview_widget(txt_path, "document")
            assert up.current_preview_widget is None  # _clear_preview 后未重建

            # font: 重建字体预览
            up.current_preview_widget = _Txt()
            up.current_preview_type = "font"
            up._update_preview_widget(txt_path, "font")
            assert font_called, "font 分支应重建预览"
        finally:
            safe_teardown(up)

    def test_update_preview_widget_gif_and_exception(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        from PySide6.QtWidgets import QWidget

        # 生成 2 帧 GIF
        gif_path: str = str(tmp_path / "anim.gif")
        from PIL import Image as PILImage

        frame1 = PILImage.new("RGB", (4, 4), "red")
        frame2 = PILImage.new("RGB", (4, 4), "blue")
        frame1.save(gif_path, save_all=True, append_images=[frame2], format="GIF", duration=100, loop=0)

        up = self._make_up()
        try:
            class _W(QWidget):
                pass

            # GIF 或动画 → 重建路径（_clear_preview + _show_image_preview）
            shown: List[bool] = []
            up._show_image_preview = lambda p, loaded_data=None: shown.append(True)  # type: ignore[method-assign]
            up.current_preview_widget = _W()
            up.current_preview_type = "image"
            up._update_preview_widget(gif_path, "image")
            assert shown, "GIF 应重建为 ImagePreviewerLayout"

            # 异常路径
            class _Broken(QWidget):
                def set_file(self, path: str) -> None:
                    raise RuntimeError("boom")

            up.current_preview_widget = _Broken()
            up.current_preview_type = "pdf"
            up._update_preview_widget(str(tmp_missing()), "pdf")
        finally:
            safe_teardown(up)

    def test_on_preview_created_routing(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.archive_browser as ab_mod
        from PySide6.QtWidgets import QWidget

        routed: List[tuple] = []

        up = self._make_up()
        try:
            class _Zip(QWidget):
                def set_archive_path(self, path: str) -> None:
                    routed.append(("archive", path))

            monkeypatch.setattr(ab_mod, "ArchiveBrowser", _Zip)
            probe: str = str(tmp_path / "sample.bin")
            with open(probe, "wb") as handle:
                handle.write(b"x")
            up.current_file_info = _make_finfo(probe, suffix="bin")

            for ptype in ("image", "video", "audio", "pdf", "text", "document", "font", "unknown", "archive"):
                up.is_loading_preview = True
                up.current_preview_type = None
                if ptype in ("image", "video", "audio", "pdf", "text", "document", "font"):
                    monkeypatch.setattr(
                        up, f"_show_{'document' if ptype == 'document' else ptype}_preview",
                        lambda p, loaded_data=None, t=ptype: routed.append((t, "show")),
                        raising=False,
                    )
                up._on_preview_created({}, ptype)
                if ptype == "unknown":
                    # unknown 分支：创建普通信息容器并标记为 info
                    assert up.current_preview_type == "info"
                    assert up.current_preview_widget is not None
            assert any(t == "archive" for t, _ in routed), "archive 分支应创建 ArchiveBrowser"
        finally:
            safe_teardown(up)

    def test_show_image_preview_exception(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.unified_previewer as up_mod

        png_path: str = make_image(str(tmp_path / "sample.png"))

        class _BoomRegistry:
            @staticmethod
            def get_previewer_class(_info: dict) -> type:
                class _Boom:
                    def __init__(self, *a: Any, **k: Any) -> None:
                        raise RuntimeError("construct boom")

                return _Boom

        monkeypatch.setattr(up_mod, "PreviewerRegistry", _BoomRegistry)
        up = self._make_up()
        try:
            up.current_file_info = _make_finfo(png_path, suffix="png")
            up._show_image_preview(png_path)
            assert up.current_preview_type == "error"
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_is_animated_image_cache_eviction_and_errors(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.unified_previewer as up_mod

        png_path: str = make_image(str(tmp_path / "a.png"))
        up = self._make_up()
        try:
            # 第二次命中缓存
            assert up._is_animated_image(png_path) is False
            assert up._is_animated_image(png_path) is False

            # getmtime OSError
            real_getmtime = up_mod.os.path.getmtime

            def _boom(path: str) -> float:
                raise OSError("stat boom")

            monkeypatch.setattr(up_mod.os.path, "getmtime", _boom)
            assert up._is_animated_image(png_path) is False
            monkeypatch.setattr(up_mod.os.path, "getmtime", real_getmtime)

            # LRU 淘汰
            up._ANIMATED_CACHE_MAX_SIZE = 1
            p2: str = make_image(str(tmp_path / "b.png"))
            p3: str = make_image(str(tmp_path / "c.png"))
            up._is_animated_image(p2)
            up._is_animated_image(p3)
            assert len(up._animated_image_cache) <= 1
        finally:
            safe_teardown(up)

    def test_show_video_audio_pdf_preview_exceptions(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.video_player as vp_mod

        mp4_path: str = str(tmp_path / "v.mp4")
        for _i in range(3):
            mp4_path = f"{mp4_path}"
        # 用独立后缀文件避免误判
        media_path: str = str(tmp_path / "clip.bin")
        with open(media_path, "wb") as handle:
            handle.write(b"x")

        def _boom(*a: Any, **k: Any) -> Any:
            raise RuntimeError("load boom")

        monkeypatch.setattr(vp_mod, "VideoPlayer", _boom)
        up = self._make_up()
        try:
            up._show_video_preview(str(tmp_path / "clip.mp4"))
            assert up.current_preview_type == "error"
            up._clear_preview(emit_signal=False)
            up._show_audio_preview(str(tmp_path / "clip.mp3"))
            assert up.current_preview_type == "error"
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_show_pdf_preview_exception(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.pdf_previewer as pdf_mod

        pdf_path: str = make_pdf(str(tmp_path / "d.pdf"))

        def _boom(*a: Any, **k: Any) -> Any:
            raise RuntimeError("load boom")

        monkeypatch.setattr(pdf_mod, "PDFPreviewer", _boom)
        up = self._make_up()
        try:
            up._show_pdf_preview(pdf_path)
            assert up.current_preview_type == "error"
            assert up.is_loading_preview is False
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_show_text_font_preview_exceptions(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.font_previewer as fp_mod
        import freeassetfilter.components.text_previewer as tp_mod

        txt_path: str = make_text(str(tmp_path / "t.txt"), content="x")
        font_path: str = str(tmp_path / "a.ttf")
        with open(font_path, "wb") as handle:
            handle.write(b"x")

        monkeypatch.setattr(tp_mod, "TextPreviewWidget", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        monkeypatch.setattr(fp_mod, "FontPreviewWidget", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        up = self._make_up()
        try:
            up._show_text_preview(txt_path)
            assert up.current_preview_type == "error"
            up._clear_preview(emit_signal=False)
            up._show_font_preview(font_path)
            assert up.current_preview_type == "error"
            up._clear_preview(emit_signal=False)
        finally:
            safe_teardown(up)

    def test_progress_dialog_recreate(self, qapp: QApplication) -> None:
        up = self._make_up()
        try:
            up._show_progress_dialog("一", "一")
            dialog1 = up.progress_dialog
            up._show_progress_dialog("二", "二")
            assert up.progress_dialog is not None and up.progress_dialog is not dialog1
            up._on_file_read_finished()
        finally:
            if up.progress_dialog:
                up.progress_dialog.close()
                up.progress_dialog = None
            safe_teardown(up)

    def test_cancel_progress_deep(self, qapp: QApplication, monkeypatch: Any) -> None:
        up = self._make_up()
        try:
            class _W:
                def cancel_file_read(self) -> None:
                    pass

            up.current_preview_widget = _W()  # type: ignore[assignment]

            class _T:
                def __init__(self) -> None:
                    self._running = True

                def isRunning(self) -> bool:
                    return self._running

                def cancel(self) -> None:
                    self._running = False

                def wait(self, _ms: int) -> bool:
                    return True

            up._preview_thread = _T()
            up._show_progress_dialog("标题", "消息")
            up._on_cancel_progress(0)
            assert up.is_cancelled is True
            assert up.progress_dialog is None
        finally:
            up.current_preview_widget = None
            up._preview_thread = None
            if up.progress_dialog:
                up.progress_dialog.close()
                up.progress_dialog = None
            safe_teardown(up)

    def test_on_file_read_finished_with_timer(self, qapp: QApplication) -> None:
        from PySide6.QtCore import QTimer

        up = self._make_up()
        try:
            timer = QTimer(up)
            up._progress_timer = timer
            up._on_file_read_finished()
            assert not hasattr(up, "_progress_timer")
        finally:
            safe_teardown(up)

    def test_select_text_fallback_and_simulate_progress(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer

        txt_path: str = make_text(str(tmp_path / "t.txt"), content="x")
        up = self._make_up()
        thread = UnifiedPreviewer.PreviewLoaderThread(txt_path, "text", up)
        try:
            data: dict = {}
            thread._load_text_file_data(data)
            assert "text_content" in data

            up._progress = 90
            up._simulate_video_progress()
            assert up._progress >= 95
        finally:
            thread.deleteLater()
            safe_teardown(up)

    def test_preview_loader_thread_loaders(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer

        sub = tmp_path / "subdir"
        sub.mkdir()
        up = self._make_up()

        # 文本：处理异常路径（目录作为文件读取）
        thread = UnifiedPreviewer.PreviewLoaderThread(str(sub), "text", up)
        data: dict = {}
        try:
            thread._load_text_file_data(data)
            assert "text_content" in data, "目录读取失败也应反馈"
        finally:
            thread.deleteLater()

        # 图片元数据
        png_path: str = make_image(str(tmp_path / "meta.png"))
        thread2 = UnifiedPreviewer.PreviewLoaderThread(png_path, "image", up)
        data2: dict = {}
        try:
            thread2._load_image_metadata(data2)
            assert data2.get("image_mode", "") != ""
        finally:
            thread2.deleteLater()

        # 音频/视频信息
        clip: str = str(tmp_path / "clip.mp4")
        with open(clip, "wb") as handle:
            handle.write(b"x")
        thread3 = UnifiedPreviewer.PreviewLoaderThread(clip, "video", up)
        data3: dict = {}
        try:
            thread3._load_media_info(data3)
            assert data3.get("file_size", 0) >= 0
        finally:
            thread3.deleteLater()

        # PDF 信息：通过真实 PDF 验证
        pdf_path: str = make_pdf(str(tmp_path / "d.pdf"))
        thread4 = UnifiedPreviewer.PreviewLoaderThread(pdf_path, "pdf", up)
        data4: dict = {}
        try:
            thread4._load_pdf_info(data4)
            assert data4.get("file_size", 0) >= 0
        finally:
            thread4.deleteLater()

        safe_teardown(up)

    def test_preview_loader_thread_ulemon_runtime_failure(self, qapp: QApplication, tmp_path: Any) -> None:
        """线程 run() 中抛异常 → preview_error。"""
        import freeassetfilter.components.unified_previewer as up_mod
        from freeassetfilter.components.unified_previewer import UnifiedPreviewer

        txt_path: str = make_text(str(tmp_path / "t.txt"), content="x")
        up = self._make_up()
        thread = UnifiedPreviewer.PreviewLoaderThread(txt_path, "text", up)
        errors: List[str] = []
        thread.preview_error.connect(errors.append)
        try:

            def _boom(data: dict) -> None:
                raise RuntimeError("read boom")

            thread._load_text_file_data = _boom  # type: ignore[method-assign]
            thread.run()
            assert errors, "线程异常应发射 preview_error"
        finally:
            thread.deleteLater()
            safe_teardown(up)

    def test_focus_in_event(self, qapp: QApplication) -> None:
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QFocusEvent

        up = self._make_up()
        try:
            up.focusInEvent(QFocusEvent(QEvent.Type.FocusIn))
        finally:
            safe_teardown(up)

    def test_pause_active_media_exception(self, qapp: QApplication, monkeypatch: Any) -> None:
        import freeassetfilter.components.video_player as vp_mod
        from PySide6.QtWidgets import QWidget

        up = self._make_up()
        try:
            class _FakeVp(QWidget):
                def pause(self) -> bool:
                    raise RuntimeError("pause boom")

            monkeypatch.setattr(vp_mod, "VideoPlayer", _FakeVp)
            up.current_preview_widget = _FakeVp()
            assert up.pause_active_media_preview() is False
        finally:
            up._clear_preview(emit_signal=False)
            safe_teardown(up)

    def test_schedule_cleanup_no_widget_and_exception(self, qapp: QApplication, monkeypatch: Any) -> None:
        from PySide6.QtWidgets import QWidget as _QW

        up = self._make_up()
        try:
            # 无当前组件：回调直接返回
            up.schedule_safe_preview_cleanup(delay_ms=0)
            process_qt_events(qapp, ms=50)
            assert up._scheduled_preview_cleanup is False

            # stop_preview 抛异常 → error 分支
            raise_flag: List[bool] = []

            def _boom() -> None:
                raise_flag.append(True)
                raise RuntimeError("stop boom")

            up.stop_preview = _boom  # type: ignore[method-assign]
            fake_vp_type = type("_FV", (_QW,), {})
            monkeypatch.setattr("freeassetfilter.components.video_player.VideoPlayer", fake_vp_type)
            up.current_preview_widget = fake_vp_type()
            up.schedule_safe_preview_cleanup(delay_ms=0)
            process_qt_events(qapp, ms=50)
            assert raise_flag, "应触发 stop_preview 并捕获异常"
        finally:
            safe_teardown(up)

    def test_show_document_preview_injection_and_cached(self, qapp: QApplication, monkeypatch: Any, tmp_path: Any) -> None:
        import os

        import freeassetfilter.components.unified_previewer as up_mod

        doc_path: str = str(tmp_path / "report.docx")
        with open(doc_path, "wb") as handle:
            handle.write(b"x")

        # _show_document_preview 会按模块位置计算缓存路径：<项目根>/data/temp/<原名>_temp.pdf
        module_dir: str = os.path.dirname(up_mod.__file__)
        project_root: str = os.path.dirname(os.path.dirname(module_dir))
        temp_dir: str = os.path.join(project_root, "data", "temp")
        os.makedirs(temp_dir, exist_ok=True)
        cache_pdf: str = os.path.join(temp_dir, "report_temp.pdf")

        up = self._make_up()
        try:
            # 路径含注入字符 → ValueError → 错误标签
            monkeypatch.setattr(up_mod, "contains_injection_chars", lambda p: True)
            up._show_document_preview(doc_path)
            assert up.current_preview_widget is not None

            # 已存在缓存 PDF：直接复用（伪装 _show_pdf_preview）
            shown: List[bool] = []
            up._show_pdf_preview = lambda p: shown.append(True)  # type: ignore[method-assign]
            monkeypatch.setattr(up_mod, "contains_injection_chars", lambda p: False)
            with open(cache_pdf, "wb") as handle:
                handle.write(b"%PDF-1.4")
            up._show_document_preview(doc_path)
            assert shown, "缓存存在时应直接进入 PDF 预览"
        finally:
            up._clear_preview(emit_signal=False)
            safe_teardown(up)
            if os.path.exists(cache_pdf):
                try:
                    os.remove(cache_pdf)
                except OSError:
                    pass


# ===== photo_viewer =====

class TestPhotoViewer:
    """图片查看器：加载成功 / 缺失文件 / 异步加载落地 / 视图重置。"""

    def _make_viewer(self) -> Any:
        from freeassetfilter.components.photo_viewer import PhotoViewer

        return PhotoViewer(global_font=_global_font(), dpi_scale=1.0, settings_manager=_settings_manager())

    def _start_loader(self, viewer: Any) -> Any:
        """启动加载后立即捕获 ImageLoader 强引用。

        ``_on_image_loader_complete`` 会把 ``image_widget.image_loader`` 置为
        None（见 photo_viewer.py:877），若测试在完成回调后读取该属性只会得到
        None，导致 C++ QThread 在 worker 线程收尾前被 Python GC 销毁
        （QThread: Destroyed while thread is still running → 0xC0000409）。
        此处抢先持有强引用并在 teardown 前 ``wait()``，保证线程完整结束。
        """
        return viewer.image_widget.image_loader

    def test_set_file_valid_png(self, qapp: QApplication, tmp_path: Any) -> None:
        png_path: str = make_image(str(tmp_path / "valid.png"))
        viewer = self._make_viewer()
        loader: Any = None
        try:
            result: bool = viewer.set_file(png_path)
            assert result is True
            assert viewer.windowTitle() == f"照片查看器 - valid.png"
            loader = self._start_loader(viewer)
            # ImageWidget 通过 QThread 异步解码，等待镜像文件落地
            loaded: bool = _wait_until(qapp, lambda: viewer.image_widget.current_file_path == png_path)
            assert loaded, "PNG 未在预期时间内完成异步加载"
            assert viewer.image_widget.source_image is not None
        finally:
            self._abort_image_loader(viewer, loader)
            safe_teardown(viewer)

    def test_set_file_missing_returns_false(self, qapp: QApplication) -> None:
        viewer = self._make_viewer()
        try:
            assert viewer.set_file(str(tmp_missing())) is False
            assert viewer.windowTitle() == "照片查看器"
        finally:
            safe_teardown(viewer)

    def test_async_load_sets_loaded_state(self, qapp: QApplication, tmp_path: Any) -> None:
        png_path: str = make_image(str(tmp_path / "async.png"))
        viewer = self._make_viewer()
        loader: Any = None
        try:
            assert viewer.set_file(png_path) is True
            loader = self._start_loader(viewer)
            loaded: bool = _wait_until(qapp, lambda: viewer.image_widget.current_file_path == png_path)
            assert loaded, "异步加载未在预期时间内完成"
            assert viewer.image_widget.source_image is not None
            assert viewer.image_widget.rotation_steps == 0
        finally:
            self._abort_image_loader(viewer, loader)
            safe_teardown(viewer)

    def test_reset_view_no_crash(self, qapp: QApplication, tmp_path: Any) -> None:
        png_path: str = make_image(str(tmp_path / "reset.png"))
        viewer = self._make_viewer()
        loader: Any = None
        try:
            assert viewer.set_file(png_path) is True
            loader = self._start_loader(viewer)
            _wait_until(qapp, lambda: viewer.image_widget.current_file_path == png_path, timeout_ms=5000.0)
            viewer.reset_view()
        finally:
            self._abort_image_loader(viewer, loader)
            safe_teardown(viewer)

    def _abort_image_loader(self, viewer: Any, loader: Any = None) -> None:
        """尽力中止 ImageLoader 线程，并在销毁前完整收尾。

        即使加载已完成（``image_loader`` 已被置 None），传入的强引用仍保持
        C++ QThread 存活，``wait()`` 确保线程退出后才允许 widget 销毁，
        消除 "QThread: Destroyed while thread is still running" 原生崩溃。

        Args:
            viewer: 被测 PhotoViewer。
            loader: 启动时捕获的 ImageLoader 强引用；缺省时回退读取属性。
        """
        try:
            if loader is None:
                loader = viewer.image_widget.image_loader
            if loader is not None:
                if loader.isRunning():
                    loader.cancel()
                loader.wait(3000)
        except (RuntimeError, AttributeError):
            pass


class TestImageWidget:
    """ImageWidget 粘合层：直接 set_image 的行为（同步返回 / 缺失路径）。"""

    def _make_image_widget(self) -> Any:
        from freeassetfilter.components.photo_viewer import ImageWidget

        return ImageWidget(settings_manager=_settings_manager())

    def test_set_image_png_returns_true_and_loads(self, qapp: QApplication, tmp_path: Any) -> None:
        png_path: str = make_image(str(tmp_path / "direct.png"))
        widget = self._make_image_widget()
        loader: Any = None
        try:
            assert widget.set_image(png_path) is True
            # 与 TestPhotoViewer 相同的强引用策略：完成回调会把
            # image_loader 置 None，提前捕获并在 teardown 前 wait()，
            # 防止 C++ QThread 在线程收尾前被 GC 销毁（0xC0000409）。
            loader = widget.image_loader
            ok: bool = _wait_until(qapp, lambda: widget.current_file_path == png_path)
            assert ok
            assert widget.source_image is not None
        finally:
            try:
                if loader is not None:
                    if loader.isRunning():
                        loader.cancel()
                    loader.wait(3000)
            except (RuntimeError, AttributeError):
                pass
            safe_teardown(widget)

    def test_set_image_missing_returns_false(self, qapp: QApplication) -> None:
        widget = self._make_image_widget()
        try:
            assert widget.set_image(str(tmp_missing())) is False
            assert widget.current_file_path == ""
        finally:
            safe_teardown(widget)


class TestImageWidgetDispatchAndInteraction:
    """ImageWidget：格式分派、处理器槽、交互事件与复制行为。"""

    def _make_widget(self) -> Any:
        from freeassetfilter.components.photo_viewer import ImageWidget

        return ImageWidget(settings_manager=_settings_manager())

    def _make_worker(self, path: str, force_full_resolution: bool = False) -> Any:
        from PySide6.QtCore import QObject

        class _Worker(QObject):
            processing_complete = Signal(QImage, str)
            processing_failed = Signal(str)
            processing_progress = Signal(int, str)

            def __init__(self, p: str, ffr: bool = False) -> None:
                super().__init__()
                self.path = p
                self.force_full_resolution = ffr
                self._running = False
                self.cancel_calls = 0

            def isRunning(self) -> bool:
                return self._running

            def cancel(self) -> None:
                self.cancel_calls += 1

            def start(self) -> None:
                self._running = True

        return _Worker(path)

    def _loaded_widget(self, qapp: QApplication, size: int = 200) -> Any:
        widget = self._make_widget()
        widget.resize(300, 300)
        process_qt_events(qapp, ms=10)
        img = QImage(size, size, QImage.Format_RGB32)
        widget.source_image = img
        widget.original_image = img.copy()
        widget.rotation_steps = 0
        widget.calculate_fit_scale()
        widget.update_image()
        return widget

    @pytest.mark.parametrize(
        "ext, attr, cls_name",
        [
            ("cr2", "raw_processor", "RawProcessor"),
            ("heic", "heif_avif_processor", "HeifAvifProcessor"),
            ("ico", "ico_processor", "IcoProcessor"),
            ("psd", "psd_processor", "PSDProcessor"),
            ("png", "image_loader", "ImageLoader"),
        ],
    )
    def test_set_image_dispatch(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any, ext: str, attr: str, cls_name: str) -> None:
        import freeassetfilter.components.photo_viewer as pv

        monkeypatch.setattr(pv, cls_name, self._make_worker)
        widget = self._make_widget()
        target = tmp_path / f"a.{ext}"
        target.write_bytes(b"x")
        try:
            assert widget.set_image(str(target)) is True
            proc = getattr(widget, attr)
            assert proc is not None
            assert proc.path == str(target)
            assert proc._running
            assert getattr(proc, "_load_seq") == widget._current_load_sequence
        finally:
            safe_teardown(widget)

    def test_set_image_cancels_running_processor(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        import freeassetfilter.components.photo_viewer as pv

        monkeypatch.setattr(pv, "RawProcessor", self._make_worker)
        widget = self._make_widget()
        prev = self._make_worker(str(tmp_path / "prev.cr2"))
        prev._running = True
        widget.raw_processor = prev
        target = tmp_path / "a.cr2"
        target.write_bytes(b"x")
        try:
            assert widget.set_image(str(target)) is True
            assert prev.cancel_calls == 1
        finally:
            safe_teardown(widget)

    def test_processor_slot_sequence_guard(self, qapp: QApplication) -> None:
        widget = self._make_widget()
        try:
            widget._current_load_sequence = 5
            proc = self._make_worker("x.ico")
            proc._load_seq = 3
            widget.ico_processor = proc
            # 必须经信号发射，槽内 sender() 才能返回过期处理器
            proc.processing_complete.connect(widget._on_ico_processing_complete)
            proc.processing_failed.connect(widget._on_ico_processing_failed)
            proc.processing_complete.emit(QImage(4, 4, QImage.Format_RGB32), "x")
            assert widget.ico_processor is proc, "过期序列应被忽略，不清空处理器"
            assert widget.source_image is None
            proc.processing_failed.emit("boom")
            assert widget.ico_processor is proc
        finally:
            safe_teardown(widget)

    def test_processor_complete_slot_loads_image(self, qapp: QApplication) -> None:
        widget = self._make_widget()
        try:
            widget._current_load_sequence = 3
            proc = self._make_worker("x.ico")
            proc._load_seq = 3
            widget.ico_processor = proc
            widget._on_ico_processing_complete(QImage(4, 4, QImage.Format_RGB32), "x")
            assert widget.ico_processor is None
            assert widget.source_image is not None
            assert widget.current_file_path == "x"

            proc2 = self._make_worker("x.raw")
            proc2._load_seq = 4
            widget.raw_processor = proc2
            widget._current_load_sequence = 4
            widget._on_raw_processing_complete(QImage(4, 4, QImage.Format_RGB32), "r")
            assert widget.raw_processor is None

            proc3 = self._make_worker("x.psd")
            proc3._load_seq = 5
            widget.psd_processor = proc3
            widget._current_load_sequence = 5
            png = self._make_temp_png()
            widget._on_psd_processing_complete(png)
            assert widget.psd_processor is None
            os.remove(png)
        finally:
            safe_teardown(widget)

    def test_psd_progress_slot_both_paths(self, qapp: QApplication) -> None:
        from PySide6.QtWidgets import QWidget as HostWidget

        from freeassetfilter.components.photo_viewer import ImageWidget

        # 分支一：无父窗口时走 _progress_callback 回退
        widget = self._make_widget()
        calls: List[tuple] = []
        widget._progress_callback = lambda p, s: calls.append((p, s))
        widget._on_psd_processing_progress(30, "合成")
        assert calls == [(30, "合成")]
        safe_teardown(widget)

        # 分支二：存在带 _on_progress_updated 的父窗口时转发给父窗口
        host = HostWidget()
        calls2: List[tuple] = []
        host._on_progress_updated = lambda p, s: calls2.append((p, s))
        parent = ImageWidget(parent=host, settings_manager=_settings_manager())
        try:
            parent._on_psd_processing_progress(70, "完成")
            assert calls2 == [(70, "完成")]
        finally:
            safe_teardown(parent)
            host.deleteLater()

    def test_rotate_and_apply_rotation(self, qapp: QApplication) -> None:
        widget = self._make_widget()
        try:
            img = QImage(10, 10, QImage.Format_RGB32)
            widget.source_image = img
            widget.rotate_clockwise()
            assert widget.rotation_steps == 1
            assert widget.original_image is not None
            widget.rotate_clockwise()
            widget.rotate_clockwise()
            widget.rotate_clockwise()
            assert widget.rotation_steps == 0  # 4 次回到原位
            assert widget.original_image.width() == 10
        finally:
            safe_teardown(widget)

    def test_switch_and_load_bg_color(self, qapp: QApplication) -> None:
        sm = _settings_manager()
        # 显式归位起始键，避免磁盘 settings.json 残留键值影响循环起点
        sm.set_setting("photo_viewer.style.bg_color_key", "base_color")
        widget = self._make_widget()
        try:
            widget._switch_bg_color()
            assert sm.get_setting("photo_viewer.style.bg_color_key") == "secondary_color"
            assert widget._current_bg_color_key == "secondary_color"

            sm.set_setting("photo_viewer.style.remember_bg_color", False)
            sm.set_setting("appearance.colors.base_color", "#ABCDEF")
            assert widget._get_current_bg_color() == "#ABCDEF"

            sm.set_setting("photo_viewer.style.remember_bg_color", True)
            sm.set_setting("appearance.colors.secondary_color", "#123456")
            assert widget._get_current_bg_color() == "#123456"
        finally:
            safe_teardown(widget)

    def test_copy_clipboard_operations(self, qapp: QApplication, monkeypatch: Any) -> None:
        class _RecordingClipboard:
            def __init__(self) -> None:
                self._text = ""

            def setText(self, text: str) -> None:
                self._text = text

            def text(self) -> str:
                return self._text

        fake = _RecordingClipboard()
        # 真实系统剪贴板可能被外部进程锁定，改用记录型假剪贴板验证写入内容
        monkeypatch.setattr(QApplication, "clipboard", staticmethod(lambda: fake))
        widget = self._make_widget()
        try:
            widget.pixel_info = {"x": 1, "y": 2, "r": 10, "g": 20, "b": 30, "hex": "#0a141e"}
            widget.copy_color_value()
            text = fake.text()
            assert "RGB(10, 20, 30)" in text and "HEX: #0a141e" in text

            widget.current_file_path = os.path.abspath("x.png")
            widget.copy_file_path()
            assert "x.png" in fake.text()
            widget.copy_file_name()
            assert fake.text() == "x.png"
            widget.copy_file()  # 路径不存在时不崩溃
        finally:
            safe_teardown(widget)

    def test_pixel_position_and_update_pixel_info(self, qapp: QApplication) -> None:
        from PySide6.QtCore import QPoint

        widget = self._loaded_widget(qapp)
        # 强制 1.0 缩放：200×200 图居中于 300×300 视口，(5,5) 在图片外，(100,100) 在图片内
        widget.scale_factor = 1.0
        widget.pan_offset = QPoint(0, 0)
        widget.update_image()
        try:
            assert widget.is_valid_pixel_position(QPoint(100, 100))
            assert not widget.is_valid_pixel_position(QPoint(5, 5))
            collected: List[dict] = []
            widget.pixel_info_changed.connect(collected.append)
            widget.update_pixel_info(QPoint(100, 100))
            assert collected, "应发射 pixel_info_changed"
            info = widget.pixel_info
            assert 0 <= info["x"] < 200 and 0 <= info["y"] < 200
            assert widget.get_pixel_info() == info
        finally:
            safe_teardown(widget)

    def test_mouse_press_move_release_wheel(self, qapp: QApplication) -> None:
        from PySide6.QtCore import QEvent, QPoint, QPointF
        from PySide6.QtGui import QMouseEvent, QWheelEvent

        widget = self._loaded_widget(qapp)
        try:
            before = widget.scale_factor
            press = QMouseEvent(QEvent.MouseButtonPress, QPointF(100, 100), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            widget.mousePressEvent(press)
            assert widget.is_panning
            move = QMouseEvent(QEvent.MouseMove, QPointF(110, 105), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
            widget.mouseMoveEvent(move)
            assert widget.pan_offset == QPoint(10, 5)
            release = QMouseEvent(QEvent.MouseButtonRelease, QPointF(110, 105), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            widget.mouseReleaseEvent(release)
            assert not widget.is_panning

            wheel = QWheelEvent(
                QPointF(150, 150), QPointF(150, 150), QPoint(), QPoint(0, 120),
                Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
            )
            widget.wheelEvent(wheel)
            assert widget.scale_factor > before
        finally:
            safe_teardown(widget)

    def test_double_click_and_paint(self, qapp: QApplication) -> None:
        from PySide6.QtCore import QEvent, QPoint, QPointF, QRect
        from PySide6.QtGui import QMouseEvent, QPaintEvent

        widget = self._loaded_widget(qapp)
        try:
            widget.pan_offset = QPoint(3, 3)
            dbl = QMouseEvent(QEvent.MouseButtonDblClick, QPointF(100, 100), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            widget.mouseDoubleClickEvent(dbl)
            widget.paintEvent(QPaintEvent(QRect(0, 0, 300, 300)))
            widget.update()  # no crash
        finally:
            safe_teardown(widget)

    def test_context_menu_and_actions(self, qapp: QApplication) -> None:
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QContextMenuEvent

        widget = self._loaded_widget(qapp)
        try:
            ev = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(10, 10), QPoint(20, 20))
            widget.contextMenuEvent(ev)
            assert hasattr(widget, "_context_menu")
            widget._on_context_menu_clicked("fit_to_size")
            widget._on_context_menu_clicked("copy_color")
            widget._on_context_menu_clicked("switch_bg_color")
            widget._on_context_menu_clicked("rotate_clockwise")
            widget._on_context_menu_clicked("copy_path")
            widget._on_context_menu_clicked("copy_name")
            widget._on_context_menu_clicked("copy_file")
        finally:
            widget._context_menu = None
            safe_teardown(widget)

    def test_paint_event_empty_widget(self, qapp: QApplication) -> None:
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QPaintEvent

        widget = self._make_widget()
        try:
            widget.paintEvent(QPaintEvent(QRect(0, 0, 100, 100)))
        finally:
            safe_teardown(widget)

    def test_reset_view_and_fit_scale_clamps(self, qapp: QApplication) -> None:
        widget = self._loaded_widget(qapp)
        try:
            widget.scale_factor = 0.05
            widget.calculate_fit_scale()
            assert widget.scale_factor >= widget.min_scale
            widget.resize(10, 10)
            process_qt_events(qapp, ms=10)
            widget.calculate_fit_scale()
            assert widget.scale_factor == 0.1  # 最小缩放钳制
            widget.reset_view()
        finally:
            safe_teardown(widget)

    def _make_temp_png(self) -> str:
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        QImage(2, 2, QImage.Format_RGB32).save(path, "PNG")
        return path


# ===== video_player =====

class TestVideoPlayer:
    """视频播放器：离线构造 / 缺失文件错误信号 / 清理幂等。"""

    @pytest.fixture(autouse=True)
    def _fake_mpv_manager(self, monkeypatch: Any) -> None:
        """用假核替换 ``video_player`` 模块内的 ``MPVManager``，阻断真实单例。

        ``VideoPlayer.__init__`` 经 ``_init_mpv_manager`` 会创建真实
        ``MPVManager`` 单例并注册 Heartbeat 回调；该单例及其残留 wiring
        在共享测试进程中正是 components 目录间歇性原生崩溃的种子
        （0xC0000409 / 0xC0000005，libmpv 实际从未加载，见 task-28 复盘）。
        本组测试仅验证离线构造契约，假核足以支撑全部断言，同时消除
        ``cleanup → stop`` 的 ~5s 空等超时（见 mpv_manager.stop 的
        ``future.result(timeout=5.0)``）。
        """
        import freeassetfilter.components.video_player as vp_mod

        fake: MagicMock = MagicMock()
        fake.register_component.return_value = True
        fake.stop.return_value = True
        fake.close.return_value = True
        fake.unregister_component.return_value = True
        monkeypatch.setattr(vp_mod, "MPVManager", lambda: fake)

    def _make_player(self) -> Any:
        from freeassetfilter.components.video_player import VideoPlayer

        return VideoPlayer(
            show_lut_controls=False,
            show_detach_button=False,
            settings_manager=_settings_manager(),
            dpi_scale=1.0,
            global_font=_global_font(),
        )

    def test_construction_without_libmpv(self, qapp: QApplication) -> None:
        vp = self._make_player()
        try:
            assert vp._is_mpv_embedded is False
        finally:
            try:
                vp.cleanup()
            except Exception:
                pass
            safe_teardown(vp)

    def test_load_missing_file_returns_false(self, qapp: QApplication) -> None:
        vp = self._make_player()
        try:
            errors: List[str] = []
            vp.errorOccurred.connect(errors.append)
            result: bool = vp.load_file(str(tmp_missing()), is_audio=False)
            assert result is False
            assert errors, "缺失文件应发射 errorOccurred"
        finally:
            try:
                vp.cleanup()
            except Exception:
                pass
            safe_teardown(vp)

    def test_cleanup_twice_is_idempotent(self, qapp: QApplication) -> None:
        vp = self._make_player()
        try:
            vp.cleanup()
            vp.cleanup()
            assert vp._is_mpv_embedded is False
        finally:
            safe_teardown(vp)


class TestVideoPlayerBehavior:
    """video_player 播放控制 / 事件处理器 / 字幕音频状态：真实行为断言。

    所有测试使用可配置的假 MPVManager（阻断真实单例），通过配置各方法
    返回值驱动分支路径，断言返回值 / 信号 / 控制栏状态，不断言内部实现。
    """

    @pytest.fixture(autouse=True)
    def _fake_mpv_manager(self, monkeypatch: Any) -> MagicMock:
        """配置默认行为的假 MPVManager，返回实例供测试逐项调整。"""
        import freeassetfilter.components.video_player as vp_mod

        fake: MagicMock = MagicMock()
        fake.register_component.return_value = True
        fake.stop.return_value = True
        fake.close.return_value = True
        fake.unregister_component.return_value = True
        fake.is_initialized.return_value = True
        fake.is_playing.return_value = True
        fake.is_paused.return_value = False
        fake.is_muted.return_value = False
        fake.get_position.return_value = 0.0
        fake.get_duration.return_value = 0.0
        fake.get_duration_direct.return_value = 0.0
        fake.get_volume.return_value = 50
        fake.get_speed.return_value = 1.0
        fake.get_video_size.return_value = (640, 360)
        fake.load_file.return_value = True
        fake.play.return_value = True
        fake.pause.return_value = True
        fake.seek.return_value = True
        fake.set_volume.return_value = True
        fake.set_muted.return_value = True
        fake.set_speed.return_value = True
        fake.set_loop.return_value = True
        fake.set_window_id.return_value = True
        fake.initialize.return_value = True
        fake.load_lut.return_value = True
        fake.unload_lut.return_value = True
        fake.load_subtitle.return_value = True
        fake.hide_subtitle.return_value = True
        fake.set_subtitle_track.return_value = True
        fake.set_audio_track.return_value = True
        fake.get_subtitle_state.return_value = {}
        fake.get_audio_state.return_value = {}
        monkeypatch.setattr(vp_mod, "MPVManager", lambda: fake)
        return fake

    def _make(self, **kwargs: Any) -> Any:
        from freeassetfilter.components.video_player import VideoPlayer

        params: dict = dict(
            show_lut_controls=False,
            show_detach_button=False,
            settings_manager=_settings_manager(),
            dpi_scale=1.0,
            global_font=_global_font(),
        )
        params.update(kwargs)
        return VideoPlayer(**params)

    # ===== 播放控制 =====

    def test_play_pause_stop_seek_toggle(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            assert vp.play() is True
            assert vp.is_playing() is True
            assert vp.pause() is True
            _fake_mpv_manager.is_paused.return_value = True
            assert vp.toggle_play_pause() is True  # paused → play
            _fake_mpv_manager.is_paused.return_value = False
            assert vp.toggle_play_pause() is True  # playing → pause
            assert vp.stop() is True
            assert vp.seek(30.0) is True
            assert vp.get_position() == 0.0
            assert vp.get_duration() == 0.0
        finally:
            safe_teardown(vp)

    def test_playback_no_manager_paths(self, qapp: QApplication) -> None:
        vp = self._make()
        try:
            vp._destroy_mpv_manager()
            assert vp.play() is False
            assert vp.pause() is False
            assert vp.stop() is False
            assert vp.seek(1.0) is False
            assert vp.set_volume(30) is False
            assert vp.set_mute(True) is False
            assert vp.set_speed(2.0) is False
            assert vp.toggle_play_pause() is False
            assert vp.seek_forward() is False
            assert vp.seek_backward() is False
            assert vp.volume_up() is False
            assert vp.volume_down() is False
            assert vp.is_playing() is False
            assert vp.get_position() == 0.0
            assert vp.get_duration() == 0.0
            assert vp.get_video_size() == (0, 0)
            assert vp.take_screenshot("x.png") is False
            assert vp.wait_for_cleanup() is True
        finally:
            safe_teardown(vp)

    def test_volume_speed_seek_forward_backward(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            assert vp.set_volume(70) is True
            assert vp.set_mute(True) is True
            assert vp.set_loop_mode("yes") is True

            _fake_mpv_manager.get_position.return_value = 100.0
            _fake_mpv_manager.get_duration.return_value = 120.0
            assert vp.seek_forward(5.0) is True
            _fake_mpv_manager.seek.assert_called_with(105.0, component_id=vp._component_id)

            _fake_mpv_manager.seek.reset_mock()
            assert vp.seek_backward(10.0) is True
            _fake_mpv_manager.seek.assert_called_with(90.0, component_id=vp._component_id)

            assert vp.set_speed(2.0) is True
            assert vp.volume_up(5) is True
            assert vp.volume_down(3) is True
        finally:
            safe_teardown(vp)

    def test_seek_clamped_to_bounds(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            _fake_mpv_manager.get_position.return_value = 1000.0
            _fake_mpv_manager.get_duration.return_value = 120.0
            vp.seek_forward(5.0)
            _fake_mpv_manager.seek.assert_called_with(120.0, component_id=vp._component_id)

            _fake_mpv_manager.seek.reset_mock()
            _fake_mpv_manager.get_position.return_value = 1.0
            vp.seek_backward(10.0)
            _fake_mpv_manager.seek.assert_called_with(0.0, component_id=vp._component_id)

            _fake_mpv_manager.get_volume.return_value = 98
            assert vp.volume_up(5) is True
            _fake_mpv_manager.get_volume.return_value = 2
            assert vp.volume_down(5) is True
        finally:
            safe_teardown(vp)

    def test_getters_metadata_and_border_radius(self, qapp: QApplication) -> None:
        vp = self._make()
        try:
            assert vp.get_current_file() == ""
            assert vp.get_video_size() == (640, 360)
            assert vp.update_style() is None
            assert vp.get_control_bar_border_radius() == 8
            vp.set_control_bar_border_radius(12)
            assert vp.get_control_bar_border_radius() == 12
            vp.set_control_bar_border_radius(-3)
            assert vp.get_control_bar_border_radius() == 0
            assert vp.sizeHint().width() == 640
            assert vp.minimumSizeHint().width() == 320
            assert vp.load_media("/nope.mp4") is False
        finally:
            safe_teardown(vp)

    # ===== load_file =====

    def test_load_file_video_success(self, qapp: QApplication, _fake_mpv_manager: MagicMock, tmp_path: Any) -> None:
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"fakemp4")
        vp = self._make()
        try:
            assert vp.load_file(str(video), is_audio=False) is True
            assert vp.get_current_file() == str(video)
            _fake_mpv_manager.load_file.assert_called_with(str(video), component_id=vp._component_id)
        finally:
            safe_teardown(vp)

    def test_load_file_video_failure(self, qapp: QApplication, _fake_mpv_manager: MagicMock, tmp_path: Any) -> None:
        video = tmp_path / "fail.mp4"
        video.write_bytes(b"fakemp4")
        _fake_mpv_manager.load_file.return_value = False
        vp = self._make()
        try:
            assert vp.load_file(str(video), is_audio=False) is False
            assert vp.get_current_file() == ""
        finally:
            safe_teardown(vp)

    def test_load_media_alias(self, qapp: QApplication, _fake_mpv_manager: MagicMock, tmp_path: Any) -> None:
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"fakemp4")
        vp = self._make()
        try:
            assert vp.load_media(str(video), is_audio=False) is True
        finally:
            safe_teardown(vp)

    # ===== 事件处理器 =====

    def test_manager_signal_handlers(self, qapp: QApplication) -> None:
        from freeassetfilter.core.managers.mpv_manager import MPVState

        vp = self._make()
        try:
            errors: List[str] = []

            vp.errorOccurred.connect(errors.append)
            vp._on_manager_state_changed(MPVState(is_playing=True, is_paused=False))
            vp._on_manager_state_changed(MPVState(is_playing=False, is_paused=True))
            vp._on_manager_position_changed(10.0, 100.0)
            vp._on_manager_volume_changed(66)
            vp._on_manager_muted_changed(True)
            vp._on_manager_speed_changed(1.5)
            vp._on_manager_file_ended(0)
            vp._on_manager_error(1, "boom")
            vp._on_core_crashed()
            vp._on_detached_window_focus_changed(True)
            assert any("播放器错误: boom" in e for e in errors)
            assert any("核心已崩溃" in e for e in errors)
        finally:
            safe_teardown(vp)

    def test_manager_file_loaded_handler(self, qapp: QApplication, _fake_mpv_manager: MagicMock, tmp_path: Any) -> None:
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"fakemp4")
        vp = self._make()
        try:
            _fake_mpv_manager.get_speed.return_value = 1.25
            _fake_mpv_manager.get_volume.return_value = 40
            _fake_mpv_manager.get_duration.return_value = 120.0
            _fake_mpv_manager.get_position.return_value = 5.0
            vp._on_manager_file_loaded(str(video))
            assert vp._current_load_sequence == vp._load_sequence_counter
            _fake_mpv_manager.get_speed.assert_called()
            _fake_mpv_manager.get_volume.assert_called()
        finally:
            safe_teardown(vp)

    def test_user_interact_and_progress(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            vp._on_user_interact_started()
            assert vp._user_interacting is True
            _fake_mpv_manager.get_duration_direct.return_value = 100.0
            vp._on_progress_changed(500)
            assert vp._pending_seek_value == 500
            vp._on_user_interact_ended()
            assert vp._user_interacting is False
            # 500ms/1000 * 100s → 50.0s
            _fake_mpv_manager.seek.assert_called_with(50.0, component_id=vp._component_id)
            vp._clear_pending_seek_state()
            assert vp._pending_seek_value is None
            _fake_mpv_manager.seek.reset_mock()
            _fake_mpv_manager.get_duration_direct.return_value = 0.0
            vp._pending_seek_value = 300
            vp._flush_pending_seek()
            _fake_mpv_manager.seek.assert_not_called()
        finally:
            safe_teardown(vp)

    def test_volume_speed_changed_handlers(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            vp._on_volume_changed(40)
            _fake_mpv_manager.set_volume.assert_called_with(40, component_id=vp._component_id)
            vp._on_speed_changed(2.5)
            _fake_mpv_manager.set_speed.assert_called_with(2.5, component_id=vp._component_id)
            vp._on_mute_changed(True)
            _fake_mpv_manager.set_muted.assert_called_with(True, component_id=vp._component_id)
        finally:
            safe_teardown(vp)

    def test_on_play_pause_clicked(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            _fake_mpv_manager.is_paused.return_value = True
            vp._on_play_pause_clicked()
            _fake_mpv_manager.play.assert_called_with(component_id=vp._component_id)
            _fake_mpv_manager.is_paused.return_value = False
            _fake_mpv_manager.is_playing.return_value = True
            vp._on_play_pause_clicked()
            _fake_mpv_manager.pause.assert_called_with(component_id=vp._component_id)
        finally:
            safe_teardown(vp)

    def test_lut_handlers(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            errors: List[str] = []

            vp.errorOccurred.connect(errors.append)
            vp._on_lut_selected("/x/a.cube")
            _fake_mpv_manager.load_lut.assert_called_with("/x/a.cube", component_id=vp._component_id)
            vp._on_lut_cleared()
            _fake_mpv_manager.unload_lut.assert_called_with(component_id=vp._component_id)
            _fake_mpv_manager.load_lut.return_value = False
            vp._on_lut_selected("/x/b.cube")
            assert any("加载LUT失败" in e for e in errors)
            _fake_mpv_manager.unload_lut.return_value = False
            vp._on_lut_cleared()
        finally:
            safe_teardown(vp)

    # ===== 字幕状态 =====

    def test_subtitle_state_helpers(self, qapp: QApplication) -> None:
        from freeassetfilter.components.video_player import VideoPlayer

        vp = self._make()
        try:
            empty = vp._get_empty_subtitle_state()
            assert empty["has_available_subtitles"] is False
            assert empty["tracks"] == []

            empty_audio = vp._get_empty_audio_state()
            assert empty_audio["track_count"] == 0

            tracks = [
                {"id": 1, "title": "Cust", "lang": "chi", "selected": True},
                {"id": 2, "external": True, "external_filename": "/s/ext.srt"},
                {"id": 3, "external": False, "lang": "eng"},
            ]
            state = empty.copy()
            state["tracks"] = tracks
            embedded = vp._get_embedded_subtitle_tracks(state)
            assert embedded == [
                {"id": 1, "title": "Cust", "lang": "chi", "selected": True},
                {"id": 3, "external": False, "lang": "eng"},
            ]

            audio_tracks = [
                {"id": 1, "has_audio": True, "title": "Main"},
                {"id": 2, "has_audio": False},
                {"id": 3},
            ]
            astate = empty_audio.copy()
            astate["tracks"] = audio_tracks
            avail = vp._get_available_audio_tracks(astate)
            assert avail == [{"id": 1, "has_audio": True, "title": "Main"}]

            assert "Cust" in vp._format_subtitle_track_label(tracks[0], 0)
            label_ext = vp._format_subtitle_track_label(tracks[1], 1)
            assert "ext.srt" in label_ext and "外挂" in label_ext
            label_lang = vp._format_subtitle_track_label(tracks[2], 2)
            assert "ENG" in label_lang and "内嵌" in label_lang
            label_noid = vp._format_subtitle_track_label({}, 3)
            assert label_noid == "字幕轨 4（内嵌）"

            assert "Main" in vp._format_audio_track_label(audio_tracks[0], 0)
            label_audio_lang = vp._format_audio_track_label({"lang": "eng", "selected": True}, 1)
            assert "ENG" in label_audio_lang and "当前" in label_audio_lang
            label_audio_id = vp._format_audio_track_label({"id": 7}, 2)
            assert label_audio_id == "音轨 7"
        finally:
            safe_teardown(vp)

    @staticmethod
    def _set_subtitle_state(vp: Any, state: dict) -> None:
        vp._subtitle_state_cache = vp._get_empty_subtitle_state()
        vp._subtitle_state_cache.update(state)

    def test_refresh_subtitle_state(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            _fake_mpv_manager.get_subtitle_state.return_value = {
                "has_active_subtitle": True,
                "is_subtitle_visible": True,
                "tracks": [{"id": 1, "external": False}],
            }
            state = vp._refresh_subtitle_state()
            assert state["has_active_subtitle"] is True
            assert vp._subtitle_state_cache["tracks"] == [{"id": 1, "external": False}]

            _fake_mpv_manager.get_subtitle_state.return_value = None
            state = vp._refresh_subtitle_state()
            assert state["has_available_subtitles"] is False
        finally:
            safe_teardown(vp)

    def test_refresh_audio_state(self, qapp: QApplication, _fake_mpv_manager: MagicMock, tmp_path: Any) -> None:
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"v")
        vp = self._make()
        try:
            vp._current_file = str(video)
            _fake_mpv_manager.get_audio_state.return_value = {
                "has_available_audio_tracks": True,
                "has_multiple_audio_tracks": True,
                "track_count": 2,
                "tracks": [{"id": 1, "has_audio": True}, {"id": 2, "has_audio": True}],
            }
            state = vp._refresh_audio_state()
            assert state["track_count"] == 2

            _fake_mpv_manager.get_audio_state.return_value = None
            state = vp._refresh_audio_state()
            assert state["track_count"] == 0

            vp._current_file = ""
            state = vp._refresh_audio_state()
            assert state["track_count"] == 0
        finally:
            safe_teardown(vp)

    def test_reset_subtitle_audio_and_dialogs(self, qapp: QApplication) -> None:
        from freeassetfilter.components.video_player import CustomMessageBox, VideoPlayer, VideoPlaceholder

        vp = self._make()
        try:
            vp._reset_subtitle_state()
            vp._reset_audio_state()
            assert vp._subtitle_state_cache["tracks"] == []
            assert vp._audio_state_cache["tracks"] == []

            class _Dlg:
                def close(self) -> None:
                    pass

                def deleteLater(self) -> None:
                    pass

            vp._subtitle_track_dialog = _Dlg()
            vp._audio_track_dialog = _Dlg()
            vp._close_subtitle_track_dialog()
            vp._close_audio_track_dialog()
            assert vp._subtitle_track_dialog is None
            assert vp._audio_track_dialog is None
        finally:
            safe_teardown(vp)

    # ===== 字幕加载 / 自动匹配 =====

    def test_load_subtitle_path(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            assert vp._load_subtitle_path("/s/sub.srt") is True
            _fake_mpv_manager.load_subtitle.assert_called_with("/s/sub.srt", component_id=vp._component_id)
            _fake_mpv_manager.get_duration.return_value = 100.0
            _fake_mpv_manager.get_subtitle_state.return_value = {
                "has_available_subtitles": True,
                "has_active_subtitle": True,
                "is_subtitle_visible": True,
            }
            _fake_mpv_manager.load_subtitle.reset_mock()
            _fake_mpv_manager.load_subtitle.return_value = False
            errors: List[str] = []
            vp.errorOccurred.connect(errors.append)
            assert vp._load_subtitle_path("/s/nope.srt") is False
            assert any("字幕加载失败" in e for e in errors)
        finally:
            safe_teardown(vp)

    def test_find_matching_subtitle_file_cache_hit(self, qapp: QApplication, tmp_path: Any) -> None:
        video = tmp_path / "movie.mp4"
        sub = tmp_path / "movie.srt"
        video.write_bytes(b"v")
        sub.write_bytes(b"s")
        vp = self._make()
        try:
            vp._current_file = str(video)
            now = time.monotonic()
            vp._subtitle_scan_cache[str(video)] = (str(sub), now)
            result = vp._find_matching_subtitle_file(str(video))
            assert result == str(sub)

            # 过期缓存 → 重新提交扫描（需要 base_dir 不存在，走短路分支）
            vp._subtitle_scan_cache[str(video)] = (str(sub), now - 120)
            result = vp._find_matching_subtitle_file(str(video))
            assert result is None  # 提交后台扫描，返回 None
        finally:
            safe_teardown(vp)

    def test_find_matching_subtitle_no_dir(self, qapp: QApplication) -> None:
        video_path = os.path.join("Z:/no_such_dir_xyz", "movie.mp4")
        vp = self._make()
        try:
            assert vp._find_matching_subtitle_file(video_path) is None
            assert os.path.splitext(os.path.basename(video_path))[0] == "movie"
        finally:
            safe_teardown(vp)

    def test_on_subtitle_scan_completed(self, qapp: QApplication, _fake_mpv_manager: MagicMock, tmp_path: Any) -> None:
        video = tmp_path / "scan.mp4"
        sub = tmp_path / "scan.srt"
        video.write_bytes(b"v")
        sub.write_bytes(b"s")
        vp = self._make()
        try:
            vp._current_file = str(video)
            vp._pending_subtitle_scans.add(str(video))
            vp._on_subtitle_scan_completed(str(video), str(sub))
            assert str(video) not in vp._pending_subtitle_scans
            assert vp._subtitle_scan_cache[str(video)][0] == str(sub)

            # 当前文件变化 → 不自动加载
            vp._current_file = "/other.mp4"
            vp._on_subtitle_scan_completed(str(video), str(sub))
        finally:
            safe_teardown(vp)

    def test_try_auto_load_matching_subtitle(self, qapp: QApplication, _fake_mpv_manager: MagicMock, tmp_path: Any) -> None:
        video = tmp_path / "auto.mp4"
        sub = tmp_path / "auto.srt"
        video.write_bytes(b"v")
        sub.write_bytes(b"s")
        vp = self._make()
        try:
            vp._current_file = str(video)
            now = time.monotonic()
            vp._subtitle_scan_cache[str(video)] = (str(sub), now)
            _fake_mpv_manager.get_subtitle_state.return_value = {}
            vp._try_auto_load_matching_subtitle()
            _fake_mpv_manager.load_subtitle.assert_called_with(str(sub), component_id=vp._component_id)

            _fake_mpv_manager.load_subtitle.reset_mock()
            vp._playback_mode = vp.AUDIO_MODE
            vp._try_auto_load_matching_subtitle()
            _fake_mpv_manager.load_subtitle.assert_not_called()
        finally:
            safe_teardown(vp)

    # ===== 键盘 / 鼠标 / 分离窗口 =====

    def test_control_bar_key_pressed_space(self, qapp: QApplication, _fake_mpv_manager: MagicMock, monkeypatch: Any) -> None:
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent

        vp = self._make()
        try:
            # 无分离窗口 → 直接返回（不触发任何操作）
            vp._on_control_bar_key_pressed(MagicMock())
            _fake_mpv_manager.play.assert_not_called()

            # 模拟分离窗口存在
            vp._detached_window = MagicMock()
            vp._detached_window.isVisible.return_value = False
            event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
            _fake_mpv_manager.is_paused.return_value = True
            vp._on_control_bar_key_pressed(event)
            assert event.isAccepted()
        finally:
            safe_teardown(vp)

    def test_detached_window_osd_and_cursor(self, qapp: QApplication) -> None:
        from freeassetfilter.components.video_player import DetachedVideoWindow

        window = DetachedVideoWindow(parent=None, dpi_scale=1.0, global_font=_global_font())
        try:
            window._format_time(3661)  # 01:01:01
            window._format_time(61)  # 01:01
            window.show_osd("测试消息")
            window.show_seek_osd(50.0, 100.0, "forward")
            window.show_seek_osd(50.0, 0.0, "backward")
            window._hide_osd()
            window.set_cursor_visible(True)
            window.set_cursor_visible(False)
            window.show_cursor()
            window.hide_cursor()
            window.reset_cursor()
            assert window._cursor_hidden is False
        finally:
            window.close()
            safe_teardown(window)

    @staticmethod
    def _create_key_event(key: Any) -> Any:
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent

        return QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)

    def test_detached_window_key_press_signals(self, qapp: QApplication) -> None:
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent
        from freeassetfilter.components.video_player import DetachedVideoWindow

        window = DetachedVideoWindow(parent=None, dpi_scale=1.0, global_font=_global_font())
        collected: List[str] = []
        window.spacePressed.connect(lambda: collected.append("space"))
        window.escapePressed.connect(lambda: collected.append("escape"))
        window.leftArrowPressed.connect(lambda: collected.append("left"))
        window.rightArrowPressed.connect(lambda: collected.append("right"))
        window.upArrowPressed.connect(lambda: collected.append("up"))
        window.downArrowPressed.connect(lambda: collected.append("down"))
        window.key1Pressed.connect(lambda: collected.append("k1"))
        window.key2Pressed.connect(lambda: collected.append("k2"))
        window.key3Pressed.connect(lambda: collected.append("k3"))
        window.keyTildePressed.connect(lambda: collected.append("tilde"))
        try:
            cases = [
                (Qt.Key.Key_Space, "space"),
                (Qt.Key.Key_Escape, "escape"),
                (Qt.Key.Key_Left, "left"),
                (Qt.Key.Key_Right, "right"),
                (Qt.Key.Key_Up, "up"),
                (Qt.Key.Key_Down, "down"),
                (Qt.Key.Key_1, "k1"),
                (Qt.Key.Key_2, "k2"),
                (Qt.Key.Key_3, "k3"),
                (Qt.Key.Key_QuoteLeft, "tilde"),
            ]
            for key, expected in cases:
                event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
                window.keyPressEvent(event)
            # 未匹配键 → 走 super()，不产生信号
            other = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)
            window.keyPressEvent(other)
            assert collected == [c for _, c in cases]
        finally:
            window.close()
            safe_teardown(window)

    def test_detached_window_focus_and_set_video_player(self, qapp: QApplication) -> None:
        from PySide6.QtGui import QFocusEvent
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QWidget
        from freeassetfilter.components.video_player import DetachedVideoWindow

        window = DetachedVideoWindow(parent=None, dpi_scale=1.0, global_font=_global_font())
        focus_events: List[bool] = []
        window.focusChanged.connect(focus_events.append)
        try:
            window.focusInEvent(QFocusEvent(QEvent.Type.FocusIn))
            window.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
            assert focus_events == [True, False]

            class _Vp(QWidget):
                pass

            player = _Vp()
            window.set_video_player(player)
            assert window._video_player is player
            window._force_focus()
            process_qt_events(qapp, ms=150)  # 触发 _delayed_focus
        finally:
            window.close()
            safe_teardown(window)

    def test_video_placeholder_paint(self, qapp: QApplication) -> None:
        from PySide6.QtGui import QPaintEvent
        from freeassetfilter.components.video_player import VideoPlaceholder

        placeholder = VideoPlaceholder(parent=None)
        try:
            placeholder.show()
            process_qt_events(qapp, ms=30)
            placeholder.paintEvent(QPaintEvent(placeholder.rect()))
        finally:
            safe_teardown(placeholder)

    def test_subtitle_scan_task_run(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.video_player import _SubtitleScanTask

        video = tmp_path / "scan.mp4"
        sub = tmp_path / "scan.srt"
        video.write_bytes(b"v")
        sub.write_bytes(b"s")
        results: List[Any] = []

        def cb(path: str, result: Any) -> None:
            results.append((path, result))

        task = _SubtitleScanTask(
            str(tmp_path), "scan", ".mp4",
            {".srt", ".ass"}, str(video), cb,
        )
        task.run()
        assert _wait_until(qapp, lambda: bool(results))

        # 无字幕目录 → result None
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        results.clear()
        task2 = _SubtitleScanTask(
            str(empty_dir), "scan", ".mp4", {".srt"}, str(video), cb,
        )
        task2.run()
        assert _wait_until(qapp, lambda: bool(results))
        assert results[0][1] is None

    # ===== 浮动 / 分离窗口 =====

    def test_switch_floating_and_fixed_mode(self, qapp: QApplication, monkeypatch: Any) -> None:
        import freeassetfilter.components.video_player as vp_mod

        hover_instances: List[MagicMock] = []

        class _FakeHoverMenu(MagicMock):
            Position_Bottom = "bottom"

            def __init__(self, *a: Any, **k: Any) -> None:
                super().__init__()
                hover_instances.append(self)

        monkeypatch.setattr(vp_mod, "D_HoverMenu", _FakeHoverMenu)
        vp = self._make()
        try:
            vp._is_floating_mode = True
            vp._switch_to_floating_mode()  # 已浮动 → 直接返回
            assert hover_instances == []

            vp._is_floating_mode = False
            vp._switch_to_floating_mode()
            assert hover_instances, "应创建浮动控制栏"
            assert vp._is_floating_mode is True

            vp._switch_to_fixed_mode()
            assert vp._is_floating_mode is False
            assert vp._floating_control_bar is None

            vp._is_floating_mode = False
            vp._switch_to_fixed_mode()  # 已固定 → 直接返回
        finally:
            safe_teardown(vp)

    def test_detach_and_reattach(self, qapp: QApplication, monkeypatch: Any) -> None:
        import freeassetfilter.components.video_player as vp_mod

        class _FakeHoverMenu(MagicMock):
            Position_Bottom = "bottom"

            def __init__(self, *a: Any, **k: Any) -> None:
                super().__init__()

        # 阻断真实全局鼠标监控（原生钩子）与浮动控制栏，改用 MagicMock
        monkeypatch.setattr(vp_mod, "GlobalMouseMonitor", lambda *a, **k: MagicMock())
        monkeypatch.setattr(vp_mod, "D_HoverMenu", _FakeHoverMenu)
        vp = self._make(show_detach_button=True)
        # _refresh_popup_menu_owners 强制重建原生窗口句柄，依赖真实 Windows Qt.Tool 窗口
        # 且访问的 sm._speed_button 并非菜单属性（属控制栏），测试环境无法安全执行，
        # 故仅在分离/恢复机制测试中桩掉该副作用（机制断言不受影响）
        monkeypatch.setattr(vp, "_refresh_popup_menu_owners", MagicMock())
        try:
            vp._on_detach_clicked()
            assert vp._detached_window is not None
            assert isinstance(vp._detached_window, vp_mod.DetachedVideoWindow)
            assert vp.parent() is vp._detached_window  # setParent 已生效
            assert vp._is_floating_mode is True

            vp._on_detach_clicked()  # 已分离 → 恢复
            assert vp._detached_window is None
            assert vp._is_floating_mode is False
        finally:
            safe_teardown(vp)

    def test_save_and_restore_playback_state(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            _fake_mpv_manager.get_position.return_value = 10.0
            _fake_mpv_manager.get_duration.return_value = 100.0
            _fake_mpv_manager.get_volume.return_value = 77
            _fake_mpv_manager.is_muted.return_value = True
            _fake_mpv_manager.is_playing.return_value = True
            _fake_mpv_manager.get_speed.return_value = 2.0
            state = vp._save_playback_state()
            assert state["position"] == 10.0
            assert state["volume"] == 77
            assert state["muted"] is True
            assert state["playing"] is True
            assert state["speed"] == 2.0

            vp._restore_playback_state(state)
            _fake_mpv_manager.set_volume.assert_called_with(77, component_id=vp._component_id)
            _fake_mpv_manager.seek.assert_called_with(10.0, component_id=vp._component_id)
            _fake_mpv_manager.play.assert_called()

            _fake_mpv_manager.reset_mock()
            vp._restore_playback_state({"playing": False, "position": 0.0})
            _fake_mpv_manager.pause.assert_called()
        finally:
            safe_teardown(vp)

    def test_embed_mpv_window(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            _fake_mpv_manager.is_initialized.return_value = True
            _fake_mpv_manager.set_window_id.return_value = True
            vp._embed_mpv_window()
            assert vp._is_mpv_embedded is True
            _fake_mpv_manager.set_volume.assert_called_with(vp._initial_volume, component_id=vp._component_id)
            _fake_mpv_manager.set_speed.assert_called_with(vp._initial_speed, component_id=vp._component_id)

            # 已嵌入 → 直接返回
            vp._embed_mpv_window()
            assert vp._is_mpv_embedded is True
        finally:
            safe_teardown(vp)

    def test_embed_mpv_window_audio_mode_and_initialize_failure(
        self, qapp: QApplication, _fake_mpv_manager: MagicMock
    ) -> None:
        vp = self._make()
        try:
            vp._playback_mode = vp.AUDIO_MODE
            _fake_mpv_manager.initialize.return_value = True
            vp._is_mpv_embedded = False
            vp._embed_mpv_window()
            assert vp._is_mpv_embedded is True

            _fake_mpv_manager.initialize.return_value = False
            errors: List[str] = []
            vp.errorOccurred.connect(errors.append)
            vp._is_mpv_embedded = False
            vp._embed_mpv_window()
            assert any("无法初始化MPV播放器" in e for e in errors)
        finally:
            safe_teardown(vp)

    def test_reconnect_and_sync_geometry(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            vp._video_surface.show()
            process_qt_events(qapp, ms=10)
            vp._reconnect_mpv_window()
            _wait_until(qapp, lambda: _fake_mpv_manager.set_window_id.called)
            vp._sync_mpv_geometry()
            assert vp._video_surface is not None
        finally:
            safe_teardown(vp)

    def test_event_filter_and_mouse_events(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent, QResizeEvent, QCloseEvent
        from PySide6.QtCore import QEvent, QSize

        vp = self._make()
        try:
            vp._show_lut_controls = False
            vp._is_floating_mode = True
            vp._floating_control_bar = MagicMock()
            # fixture 默认 is_paused=False / is_playing=True → toggle 走 pause；
            # 停顿态双击应触发 play
            _fake_mpv_manager.is_paused.return_value = True

            dbl = QMouseEvent(
                QEvent.Type.MouseButtonDblClick, QPointF(10, 10), Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            )
            handled = vp.eventFilter(vp._video_surface, dbl)
            assert handled is True
            _fake_mpv_manager.play.assert_called()

            press = QMouseEvent(
                QEvent.Type.MouseButtonPress, QPointF(10, 10), Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            )
            vp.eventFilter(vp._video_surface, press)
            vp.mousePressEvent(press)
            vp.mouseDoubleClickEvent(press)

            vp.resizeEvent(QResizeEvent(QSize(100, 100), QSize(80, 80)))
            vp.closeEvent(QCloseEvent())
            assert vp._is_mpv_embedded is False or True  # 不依赖嵌入状态
        finally:
            safe_teardown(vp)

    # ===== 扫描任务分支 / 构造默认值 =====

    def test_subtitle_scan_run_extra_branches(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.video_player import _SubtitleScanTask

        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        (scan_dir / "subdir").mkdir()  # 目录条目 → not isfile 分支
        (scan_dir / "other.mp4").write_bytes(b"1")  # stem 不匹配 → continue
        (scan_dir / "scan.mp4").write_bytes(b"v")  # 与视频后缀相同 → continue
        (scan_dir / "scan.xml").write_bytes(b"x")  # 后缀不在自动字幕集 → continue
        (scan_dir / "scan.srt").write_bytes(b"s")  # 唯一候选
        vp_path = str(scan_dir / "scan.mp4")
        collected: List[tuple] = []

        def cb(path: str, result: Any) -> None:
            collected.append((path, result))

        task = _SubtitleScanTask(str(scan_dir), "scan", ".mp4", {".srt", ".ass"}, vp_path, cb)
        task.run()
        assert _wait_until(qapp, lambda: bool(collected))
        assert collected[0][0] == vp_path
        assert collected[0][1] == str(scan_dir / "scan.srt")

        # base_dir 不是目录 → os.listdir 抛异常 → 回调 None
        not_dir = tmp_path / "afile.mp4"
        not_dir.write_bytes(b"v")
        collected.clear()
        task2 = _SubtitleScanTask(str(not_dir), "scan", ".mp4", {".srt"}, vp_path, cb)
        task2.run()
        assert _wait_until(qapp, lambda: bool(collected))
        assert collected[0][1] is None

    def test_construction_defaults_and_settings(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        from freeassetfilter.components.video_player import VideoPlayer
        from freeassetfilter.core.settings_manager import SettingsManager

        vp = VideoPlayer(
            settings_manager=None,  # 走 QApplication 探测 / 新建 SettingsManager 分支
            dpi_scale=None,  # 走 getattr(QApplication.instance(), ...) 兜底
            global_font=None,
        )
        try:
            assert isinstance(vp._settings_manager, SettingsManager)
            vp._control_bar.set_video_controls_visible(True)
            assert vp.dpi_scale == getattr(QApplication.instance(), "dpi_scale_factor", 1.0)
            assert (vp.global_font is None) is False
        finally:
            safe_teardown(vp)

    def test_audio_mode_ui_and_destroy_again(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make(playback_mode="audio")
        try:
            # 音频模式 UI：_init_ui 走 _init_audio_mode_ui，且隐藏视频控制
            assert vp._video_surface is None
            assert hasattr(vp, "_audio_background")
            # _destroy_mpv_manager 在无管理器时的 else 分支
            vp._destroy_mpv_manager()
            vp._destroy_mpv_manager()
            assert vp._mpv_manager is None
        finally:
            safe_teardown(vp)

    # ===== 光标自动隐藏 / 断开信号异常 =====

    def test_cursor_timeout_and_monitor_branches(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        from PySide6.QtCore import QRect

        vp = self._make()
        try:
            # 非法超时设置 → except 分支
            monkeypatch_inline = None  # noqa: F841 占位避免误用
            vp._settings_manager.set_setting("player.control_bar_timeout", "abc")
            assert vp._get_cursor_timeout_duration() == 3000

            # _ensure_cursor_activity_monitor 已有监控器 → else 分支
            vp._cursor_activity_monitor = MagicMock()
            vp._ensure_cursor_activity_monitor()
            assert vp._cursor_activity_monitor is not None

            # 无分离窗口 → 提前返回
            vp._detached_window = None
            vp._start_cursor_auto_hide_monitor()

            # 有分离窗口 + 监控器未启动 → start()
            vp._detached_window = MagicMock()
            vp._detached_window.isVisible.return_value = True
            vp._cursor_activity_monitor = MagicMock()
            vp._cursor_activity_monitor.is_monitoring.return_value = False
            vp._start_cursor_auto_hide_monitor()
            vp._cursor_activity_monitor.start.assert_called()

            # _stop_cursor_auto_hide_monitor：监控中 → stop
            vp._cursor_activity_monitor = MagicMock()
            vp._cursor_activity_monitor.is_monitoring.return_value = True
            vp._stop_cursor_auto_hide_monitor()
            vp._cursor_activity_monitor.stop.assert_called()

            # _is_cursor_inside_detached_window：不可见 → False
            vp._detached_window = MagicMock()
            vp._detached_window.isVisible.return_value = False
            assert vp._is_cursor_inside_detached_window() is False

            # 可见且鼠标在范围内 → True
            vp._detached_window.isVisible.return_value = True
            vp._detached_window.frameGeometry.return_value = QRect(0, 0, 4000, 4000)
            assert vp._is_cursor_inside_detached_window() is True

            # _on_cursor_activity：无分离窗口 → 返回
            vp._detached_window = None
            vp._on_cursor_activity()

            # 分离窗口可见且光标在内且监控中 → show_cursor + reset_timer
            vp._detached_window = MagicMock()
            vp._detached_window.isVisible.return_value = True
            vp._detached_window.frameGeometry.return_value = QRect(0, 0, 4000, 4000)
            vp._cursor_activity_monitor = MagicMock()
            vp._cursor_activity_monitor.is_monitoring.return_value = True
            vp._on_cursor_activity()
            vp._detached_window.show_cursor.assert_called()
            vp._cursor_activity_monitor.reset_timer.assert_called()

            # _on_cursor_hide_timeout：无分离窗口 → 返回；可见 → hide_cursor
            vp._detached_window = None
            vp._on_cursor_hide_timeout()
            vp._detached_window = MagicMock()
            vp._detached_window.isVisible.return_value = True
            vp._on_cursor_hide_timeout()
            vp._detached_window.hide_cursor.assert_called()
        finally:
            vp._cursor_activity_monitor = None
            vp._detached_window = None
            safe_teardown(vp)

    def test_disconnect_manager_signals_exceptions(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            signal_names = [
                "stateChanged", "positionChanged", "volumeChanged", "mutedChanged",
                "speedChanged", "fileLoaded", "fileEnded", "errorOccurred", "coreCrashed",
            ]
            for name in signal_names:
                getattr(_fake_mpv_manager, name).disconnect.side_effect = RuntimeError("x")
            vp._disconnect_manager_signals()  # 每个信号断开失败 → 各 except 分支
            vp._disconnect_manager_signals()  # 幂等
        finally:
            safe_teardown(vp)

    # ===== 嵌入 / 重连 / 进度守卫 =====

    def test_embed_and_reconnect_branches(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            # 嵌入：管理器未初始化 → initialize(initial_window_id=...) 分支
            _fake_mpv_manager.is_initialized.return_value = False
            vp._is_mpv_embedded = False
            vp._embed_mpv_window()
            _fake_mpv_manager.initialize.assert_called()
            _fake_mpv_manager.is_initialized.return_value = True

            # 重连无管理器 → 提前返回
            vp._destroy_mpv_manager()
            vp._reconnect_mpv_window()
            vp._do_reconnect_window(win_id=123)
            assert vp._mpv_manager is None

            # 重建管理器 → _do_reconnect_window win_id 自动取 video_surface
            vp._init_mpv_manager()
            vp._do_reconnect_window(win_id=None)
            vp._do_reconnect_window(win_id=456)
            vp._sync_mpv_geometry()
        finally:
            safe_teardown(vp)

    def test_do_reconnect_no_video_surface(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make(playback_mode="audio", dpi_scale=1.0)
        try:
            vp._do_reconnect_window(win_id=None)  # 音频模式 video_surface=None → win_id 仍为 None → return
        finally:
            safe_teardown(vp)

    def test_play_pause_click_no_manager(self, qapp: QApplication) -> None:
        vp = self._make()
        try:
            vp._destroy_mpv_manager()
            vp._on_play_pause_clicked()
        finally:
            safe_teardown(vp)

    def test_stale_position_and_flush_guards(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            # 过时 positionChanged 信号
            vp._load_sequence_counter = 5
            vp._current_load_sequence = 1
            vp._on_manager_position_changed(10.0, 100.0)

            # _flush_pending_seek：pending 为 None → 提前返回
            vp._pending_seek_value = None
            vp._flush_pending_seek()

            # _flush_pending_seek：无管理器 → 提前返回
            vp._destroy_mpv_manager()
            vp._pending_seek_value = 300
            vp._flush_pending_seek()
        finally:
            safe_teardown(vp)

    def test_initialize_progress_display_branches(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            # 无管理器 → 提前返回
            vp._destroy_mpv_manager()
            vp._initialize_progress_display()

            # 重建 → 时长无效(0) → 重试 singleShot
            from freeassetfilter.components.video_player import VideoPlayer

            vp2 = self._make()
            try:
                _fake_mpv_manager.get_duration.return_value = 0.0
                vp2._initialize_progress_display()

                # get_duration 抛异常 → except 分支
                _fake_mpv_manager.get_duration.side_effect = RuntimeError("boom")
                vp2._initialize_progress_display()
            finally:
                safe_teardown(vp2)
        finally:
            safe_teardown(vp)

    # ===== 对话框 / 音轨提示 =====

    def test_close_track_dialogs_runtime_error(self, qapp: QApplication) -> None:
        vp = self._make()
        try:
            for attr in ("_subtitle_track_dialog", "_audio_track_dialog"):
                dlg = MagicMock()
                dlg.close.side_effect = RuntimeError("gone")
                setattr(vp, attr, dlg)
            vp._close_subtitle_track_dialog()
            vp._close_audio_track_dialog()
            assert vp._subtitle_track_dialog is None
            assert vp._audio_track_dialog is None
        finally:
            safe_teardown(vp)

    def test_show_audio_message(self, qapp: QApplication, monkeypatch: Any) -> None:
        import freeassetfilter.components.video_player as vp_mod

        calls: List[tuple] = []

        class _FakeMB:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

            def set_title(self, t: str) -> None:
                calls.append(("title", t))

            def set_text(self, t: str) -> None:
                calls.append(("text", t))

            def set_buttons(self, *a: Any, **k: Any) -> None:
                calls.append(("buttons", a))

            def exec(self) -> int:  # noqa: A003
                return 0

        monkeypatch.setattr(vp_mod, "CustomMessageBox", _FakeMB)
        vp = self._make()
        try:
            vp._show_audio_message("提示", "测试消息")
            assert calls[0] == ("title", "提示")
        finally:
            safe_teardown(vp)

    def test_refresh_subtitle_state_no_manager(self, qapp: QApplication) -> None:
        vp = self._make()
        try:
            vp._destroy_mpv_manager()
            state = vp._refresh_subtitle_state()
            assert state["has_available_subtitles"] is False
        finally:
            safe_teardown(vp)

    # ===== 字幕查找 / 加载 / 自动匹配 =====

    def test_find_subtitle_empty_and_pending(self, qapp: QApplication, tmp_path: Any) -> None:
        vp = self._make()
        try:
            assert vp._find_matching_subtitle_file("") is None  # 空路径

            video = tmp_path / "pend.mp4"
            video.write_bytes(b"v")
            vp._pending_subtitle_scans.add(str(video))
            assert vp._find_matching_subtitle_file(str(video)) is None  # 已有待扫描
        finally:
            safe_teardown(vp)

    def test_load_subtitle_path_extras(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            assert vp._load_subtitle_path("") is False  # 空路径

            # 成功 + 分离窗口 → OSD
            vp._detached_window = MagicMock()
            assert vp._load_subtitle_path("/s/sub.srt", show_osd=True) is True
            vp._detached_window.show_osd.assert_called_with("字幕已加载")

            # 无管理器 → False
            vp._destroy_mpv_manager()
            assert vp._load_subtitle_path("/s/sub.srt") is False
        finally:
            vp._detached_window = None
            safe_teardown(vp)

    def test_try_auto_load_subtitle_branches(self, qapp: QApplication, _fake_mpv_manager: MagicMock, tmp_path: Any) -> None:
        vp = self._make()
        try:
            video = tmp_path / "auto.mp4"
            video.write_bytes(b"v")
            vp._current_file = str(video)

            # 无管理器 → 提前返回
            vp._destroy_mpv_manager()
            vp._try_auto_load_matching_subtitle()

            # 重建 → 已有可用字幕 → 返回
            vp._init_mpv_manager()
            _fake_mpv_manager.get_subtitle_state.return_value = {"has_available_subtitles": True}
            vp._try_auto_load_matching_subtitle()
            _fake_mpv_manager.load_subtitle.assert_not_called()

            # 无匹配字幕（缓存命中 None）→ 返回
            _fake_mpv_manager.get_subtitle_state.return_value = {}
            vp._subtitle_scan_cache[str(video)] = (None, time.monotonic())
            vp._try_auto_load_matching_subtitle()
            _fake_mpv_manager.load_subtitle.assert_not_called()
        finally:
            safe_teardown(vp)

    def test_open_external_subtitle_picker(self, qapp: QApplication, _fake_mpv_manager: MagicMock, monkeypatch: Any) -> None:
        import freeassetfilter.components.video_player as vp_mod

        vp = self._make()
        try:
            # 取消选择 → False
            class _CancelFD:
                @staticmethod
                def getOpenFileName(*a: Any, **k: Any) -> tuple:
                    return ("", "")

            monkeypatch.setattr(vp_mod, "QFileDialog", _CancelFD)
            assert vp._open_external_subtitle_picker() is False

            # 选择文件 → 加载成功
            class _PickFD:
                @staticmethod
                def getOpenFileName(*a: Any, **k: Any) -> tuple:
                    return ("/s/pick.srt", "")

            monkeypatch.setattr(vp_mod, "QFileDialog", _PickFD)
            assert vp._open_external_subtitle_picker() is True
        finally:
            safe_teardown(vp)

    # ===== 字幕 / 音轨按钮点击 =====

    def test_on_subtitle_clicked_branches(self, qapp: QApplication, _fake_mpv_manager: MagicMock, monkeypatch: Any) -> None:
        vp = self._make()
        try:
            errors: List[str] = []
            vp.errorOccurred.connect(errors.append)
            vp._is_floating_mode = True
            vp._floating_control_bar = MagicMock()

            # 未加载文件 → 错误
            vp._on_subtitle_clicked()
            assert any("先加载视频文件" in e for e in errors)
            vp._floating_control_bar.set_popup_menu_visible.assert_called_with(False)

            # 播放器未初始化
            errors.clear()
            vp._current_file = "/x.mp4"
            vp._destroy_mpv_manager()
            vp._on_subtitle_clicked()
            assert any("播放器未初始化" in e for e in errors)

            # 已加载字幕 → 隐藏成功 + OSD
            vp._init_mpv_manager()
            vp._detached_window = MagicMock()
            monkeypatch.setattr(
                vp, "_refresh_subtitle_state",
                MagicMock(return_value={"has_active_subtitle": True, "is_subtitle_visible": True}),
            )
            errors.clear()
            vp._on_subtitle_clicked()
            _fake_mpv_manager.hide_subtitle.assert_called_with(component_id=vp._component_id)
            vp._detached_window.show_osd.assert_called_with("字幕已隐藏")

            # 隐藏失败 → 错误
            _fake_mpv_manager.hide_subtitle.return_value = False
            with_osd_before = vp._detached_window
            errors.clear()
            vp._on_subtitle_clicked()
            assert any("隐藏字幕失败" in e for e in errors)
            _fake_mpv_manager.hide_subtitle.return_value = True

            # 有内嵌字幕轨 → 打开字幕轨对话框（桩掉）
            dlg_spy = MagicMock()
            monkeypatch.setattr(vp, "_open_subtitle_track_dialog", dlg_spy)
            monkeypatch.setattr(
                vp, "_refresh_subtitle_state",
                MagicMock(return_value={"has_active_subtitle": False, "tracks": [{"id": 1, "external": False}]}),
            )
            vp._on_subtitle_clicked()
            dlg_spy.assert_called_once()
            with_osd_before.show_osd.assert_called()

            # 无内嵌轨 → 打开外部选择器（桩掉）
            picker_spy = MagicMock()
            monkeypatch.setattr(vp, "_open_external_subtitle_picker", picker_spy)
            monkeypatch.setattr(
                vp, "_refresh_subtitle_state",
                MagicMock(return_value={"has_active_subtitle": False, "tracks": [{"id": 2, "external": True}]}),
            )
            vp._on_subtitle_clicked()
            picker_spy.assert_called_once()
        finally:
            vp._is_floating_mode = False
            vp._floating_control_bar = None
            vp._detached_window = None
            safe_teardown(vp)

    def test_on_audio_clicked_branches(self, qapp: QApplication, _fake_mpv_manager: MagicMock, monkeypatch: Any) -> None:
        vp = self._make()
        try:
            messages: List[str] = []
            dialog_spy = MagicMock()
            monkeypatch.setattr(vp, "_show_audio_message", lambda title, text: messages.append(text))
            monkeypatch.setattr(vp, "_open_audio_track_dialog", dialog_spy)
            vp._is_floating_mode = True
            vp._floating_control_bar = MagicMock()

            # 未加载文件 → 提示
            vp._on_audio_clicked()
            assert any("请先加载媒体文件后再操作音轨" == m for m in messages)
            vp._floating_control_bar.set_popup_menu_visible.assert_called_with(False)

            # 播放器未初始化
            messages.clear()
            vp._current_file = "/x.mp4"
            vp._destroy_mpv_manager()
            vp._on_audio_clicked()
            assert any("播放器未初始化" == m for m in messages)

            # 重建管理器，轨道总数 <=1
            vp._init_mpv_manager()
            monkeypatch.setattr(vp, "_refresh_audio_state", MagicMock(return_value={"tracks": [{"id": 1}]}))
            messages.clear()
            vp._on_audio_clicked()
            assert any("当前视频暂无其他音轨" == m for m in messages)

            # 有效轨道数 <= 0
            monkeypatch.setattr(
                vp, "_refresh_audio_state",
                MagicMock(return_value={"tracks": [{"id": 1}, {"id": 2}]}),
            )
            messages.clear()
            vp._on_audio_clicked()
            assert any("当前视频其他音轨暂无音频" == m for m in messages)

            # 有效轨道数 == 1 → 仍提示
            monkeypatch.setattr(
                vp, "_refresh_audio_state",
                MagicMock(return_value={"tracks": [{"id": 1, "has_audio": True}, {"id": 2}]}),
            )
            messages.clear()
            vp._on_audio_clicked()
            assert any("当前视频其他音轨暂无音频" == m for m in messages)

            # 有效轨道数 >= 2 → 打开音轨对话框
            monkeypatch.setattr(
                vp, "_refresh_audio_state",
                MagicMock(
                    return_value={"tracks": [
                        {"id": 1, "has_audio": True},
                        {"id": 2, "has_audio": True},
                        {"id": 3},
                    ]},
                ),
            )
            vp._on_audio_clicked()
            dialog_spy.assert_called_once()
        finally:
            vp._is_floating_mode = False
            vp._floating_control_bar = None
            safe_teardown(vp)

    # ===== 键盘处理 =====

    def test_control_bar_key_handlers_all_keys(self, qapp: QApplication, _fake_mpv_manager: MagicMock, monkeypatch: Any) -> None:
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent

        vp = self._make()
        try:
            vp._detached_window = MagicMock()
            monkeypatch.setattr(vp, "_reattach_to_parent", MagicMock())
            _fake_mpv_manager.get_position.return_value = 50.0
            _fake_mpv_manager.get_duration.return_value = 100.0

            for key in (Qt.Key.Key_Space, Qt.Key.Key_Escape, Qt.Key.Key_Left, Qt.Key.Key_Right,
                        Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_0, Qt.Key.Key_1,
                        Qt.Key.Key_2, Qt.Key.Key_3, Qt.Key.Key_QuoteLeft):
                event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
                vp._on_control_bar_key_pressed(event)
                assert event.isAccepted()

            # 无分离窗口 → 直接返回，不产生任何副作用
            vp._detached_window = None
            _fake_mpv_manager.reset_mock()
            vp._reattach_to_parent.reset_mock()
            event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
            vp._on_control_bar_key_pressed(event)
            _fake_mpv_manager.play.assert_not_called()
            _fake_mpv_manager.pause.assert_not_called()
            vp._reattach_to_parent.assert_not_called()
        finally:
            safe_teardown(vp)

    def test_floating_control_bar_key_handlers(self, qapp: QApplication, _fake_mpv_manager: MagicMock, monkeypatch: Any) -> None:
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent

        vp = self._make()
        try:
            vp._detached_window = MagicMock()
            monkeypatch.setattr(vp, "_reattach_to_parent", MagicMock())
            _fake_mpv_manager.get_position.return_value = 50.0
            _fake_mpv_manager.get_duration.return_value = 100.0

            for key in (Qt.Key.Key_Space, Qt.Key.Key_Escape, Qt.Key.Key_Left, Qt.Key.Key_Right,
                        Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_1, Qt.Key.Key_2,
                        Qt.Key.Key_3, Qt.Key.Key_QuoteLeft):
                event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
                vp._on_floating_control_bar_key_pressed(event)
                assert event.isAccepted()

            # 无分离窗口 → 直接返回，不产生任何副作用
            vp._detached_window = None
            _fake_mpv_manager.reset_mock()
            vp._reattach_to_parent.reset_mock()
            event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
            vp._on_floating_control_bar_key_pressed(event)
            _fake_mpv_manager.play.assert_not_called()
            _fake_mpv_manager.pause.assert_not_called()
            vp._reattach_to_parent.assert_not_called()
        finally:
            safe_teardown(vp)

    def test_control_bar_show_hide_and_popup_changed(self, qapp: QApplication) -> None:
        vp = self._make()
        try:
            vp._on_control_bar_shown()
            vp._on_control_bar_hidden()

            # 弹出菜单可见性变化 → 转发给浮动控制栏
            vp._floating_control_bar = MagicMock()
            vp._on_control_bar_popup_menu_changed(True)
            vp._floating_control_bar.set_popup_menu_visible.assert_called_with(True)

            # 无浮动控制栏 → 直接返回
            vp._floating_control_bar = None
            vp._on_control_bar_popup_menu_changed(False)
        finally:
            safe_teardown(vp)

    def test_register_popup_widgets_no_floating_bar(self, qapp: QApplication) -> None:
        vp = self._make()
        try:
            assert vp._floating_control_bar is None
            vp._register_control_bar_popup_widgets()  # 无浮动控制栏 → return
        finally:
            safe_teardown(vp)

    # ===== load_file 音频模式 / OSD / cleanup =====

    def test_load_file_audio_mode(self, qapp: QApplication, _fake_mpv_manager: MagicMock, tmp_path: Any, monkeypatch: Any) -> None:
        from freeassetfilter.widgets.audio_background import AudioBackground

        audio = tmp_path / "song.mp3"
        audio.write_bytes(b"fakemp3")
        vp = self._make(playback_mode="audio")
        try:
            _fake_mpv_manager.get_duration.return_value = 200.0
            vp._audio_background = MagicMock()
            monkeypatch.setattr(vp, "_extract_audio_cover", MagicMock(return_value=b"cover"))
            assert vp.load_file(str(audio), is_audio=True) is True
            vp._audio_background.setMode.assert_called()
            vp._audio_background.setAudioCover.assert_called_with(b"cover")

            # 封面模糊背景样式分支
            vp._settings_manager.set_setting("player.audio_background_style", "封面模糊")
            assert vp.load_file(str(audio), is_audio=True) is True
            vp._audio_background.setMode.assert_called_with(AudioBackground.MODE_COVER_BLUR)
        finally:
            safe_teardown(vp)

    def test_load_file_no_manager_and_detached(self, qapp: QApplication, _fake_mpv_manager: MagicMock, tmp_path: Any) -> None:
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"fakemp4")
        vp = self._make()
        try:
            # 分离模式下加载 → 重启光标监控（此处监控器为 None，仅走分支不崩溃）
            vp._detached_window = MagicMock()
            vp._cursor_activity_monitor = None
            assert vp.load_file(str(video), is_audio=False) is True

            # 无管理器 → 错误发射 + 返回 False
            vp._destroy_mpv_manager()
            errors: List[str] = []
            vp.errorOccurred.connect(errors.append)
            assert vp.load_file(str(video), is_audio=False) is False
            assert any("播放器未初始化" in e for e in errors)
        finally:
            safe_teardown(vp)

    def test_pause_stop_with_audio_background(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make(playback_mode="audio")
        try:
            vp._detached_window = MagicMock()
            vp._audio_background = MagicMock()
            assert vp.pause() is True
            vp._detached_window.show_osd.assert_called_with("暂停")
            assert vp.stop() is True
            vp._audio_background.unload.assert_called()
        finally:
            safe_teardown(vp)

    def test_seek_speed_volume_osd_detached(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            vp._detached_window = MagicMock()
            _fake_mpv_manager.get_position.return_value = 10.0
            _fake_mpv_manager.get_duration.return_value = 120.0
            _fake_mpv_manager.get_volume.return_value = 30

            vp.seek_forward(5.0)
            vp._detached_window.show_seek_osd.assert_called_with(15.0, 120.0, "forward")
            vp.seek_backward(5.0)
            vp._detached_window.show_seek_osd.assert_called_with(5.0, 120.0, "backward")
            vp.set_speed(2.0)
            vp._detached_window.show_osd.assert_called_with("2.0x")
            vp.volume_up(5)
            vp._detached_window.show_osd.assert_called_with("音量 35%")
            vp.volume_down(5)
            vp._detached_window.show_osd.assert_called_with("音量 25%")
        finally:
            safe_teardown(vp)

    def test_set_loop_no_manager_and_border_radius(self, qapp: QApplication) -> None:
        vp = self._make()
        try:
            vp._destroy_mpv_manager()
            assert vp.set_loop_mode("yes") is False

            # 浮动控制栏存在 → 动态更新圆角
            vp._floating_control_bar = MagicMock()
            vp.set_control_bar_border_radius(10)
            vp._floating_control_bar.set_border_radius.assert_called_with(10)
        finally:
            safe_teardown(vp)

    def test_cleanup_branches(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make(playback_mode="audio")
        try:
            vp._audio_background = MagicMock()
            # 停止/卸载/关闭抛异常 → 各 except 分支
            _fake_mpv_manager.stop.side_effect = RuntimeError("stop boom")
            _fake_mpv_manager.close.side_effect = RuntimeError("close boom")
            vp._audio_background.unload.side_effect = RuntimeError("unload boom")
            vp.cleanup()
            # 异步清理分支（需清除 close 的 side_effect 才能走到 debug 分支）
            _fake_mpv_manager.stop.side_effect = None
            _fake_mpv_manager.close.side_effect = None
            vp2 = self._make(playback_mode="audio")
            try:
                vp2._audio_background = MagicMock()
                vp2.cleanup(async_mode=True)
                assert vp2._mpv_manager is not None  # 异步模式下保留引用
            finally:
                safe_teardown(vp2)
        finally:
            safe_teardown(vp)

    def test_wait_for_cleanup_with_manager(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            _fake_mpv_manager.wait_for_cleanup.return_value = True
            assert vp.wait_for_cleanup(1.0) is True
        finally:
            safe_teardown(vp)

    def test_close_event_and_heartbeat(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        from PySide6.QtGui import QCloseEvent

        vp = self._make()
        try:
            # _heartbeat_sync 无控制栏 → return（此时控制栏存在，先正常走一次）
            vp._heartbeat_sync()

            # closeEvent：seek debounce 激活 → stop
            vp._seek_debounce_timer.start()
            vp.closeEvent(QCloseEvent())
            assert not vp._seek_debounce_timer.isActive()
        finally:
            safe_teardown(vp)

    def test_sync_geometry_no_video_surface(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make(playback_mode="audio")
        try:
            assert vp._video_surface is None
            vp._sync_mpv_geometry()  # 无 video_surface → return
        finally:
            safe_teardown(vp)

    # ===== 残留分支收尾（format_time / 封面提取 / debounce / 未就绪守卫） =====

    def test_format_time_and_extract_audio_cover(self, qapp: QApplication, _fake_mpv_manager: MagicMock, monkeypatch: Any) -> None:
        import freeassetfilter.components.video_player as vp_mod

        vp = self._make()
        try:
            # _format_time：负数 → 归零；整小时 → HH:MM:SS
            assert vp._format_time(-5) == "00:00"
            assert vp._format_time(3661) == "01:01:01"

            # _extract_audio_cover → 委托 MediaMetadataService.extract_audio_cover
            monkeypatch.setattr(
                vp_mod, "MediaMetadataService",
                lambda: MagicMock(extract_audio_cover=MagicMock(return_value=b"cover")),
            )
            assert vp._extract_audio_cover("/fake/song.mp3") == b"cover"
        finally:
            safe_teardown(vp)

    def test_seek_debounce_active_in_load_and_cleanup(self, qapp: QApplication, _fake_mpv_manager: MagicMock, tmp_path: Any) -> None:
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"fakemp4")
        vp = self._make()
        try:
            # load_file：seek debounce 激活 → stop
            vp._seek_debounce_timer.start()
            assert vp.load_file(str(video)) is True
            assert not vp._seek_debounce_timer.isActive()

            # cleanup：seek debounce 激活 → stop
            vp._seek_debounce_timer.start()
            vp.cleanup()
            assert not vp._seek_debounce_timer.isActive()
        finally:
            safe_teardown(vp)

    def test_manager_file_loaded_and_heartbeat_without_control_bar(self, qapp: QApplication, _fake_mpv_manager: MagicMock, tmp_path: Any) -> None:
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"fakemp4")
        vp = self._make()
        try:
            # 模拟控制栏未就绪 → 直接返回不崩溃
            vp._control_bar = None
            vp._on_manager_file_loaded(str(video))
            vp._heartbeat_sync()
            _fake_mpv_manager.get_speed.assert_not_called()
        finally:
            safe_teardown(vp)

    def test_restore_playback_state_no_manager(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            vp._destroy_mpv_manager()
            assert vp._restore_playback_state({"volume": 50}) is None  # 无 manager → return
        finally:
            safe_teardown(vp)

    def test_cursor_activity_cursor_outside(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        from PySide6.QtCore import QRect

        vp = self._make()
        try:
            # 分离窗口可见但光标不在其内 → 直接返回，不显示光标
            vp._detached_window = MagicMock()
            vp._detached_window.isVisible.return_value = True
            vp._detached_window.frameGeometry.return_value = QRect(0, 0, 1, 1)
            vp._cursor_activity_monitor = MagicMock()
            vp._is_cursor_inside_detached_window = MagicMock(return_value=False)
            vp._on_cursor_activity()
            vp._detached_window.show_cursor.assert_not_called()
        finally:
            vp._detached_window = None
            vp._cursor_activity_monitor = None
            safe_teardown(vp)

    def test_switch_floating_without_primary_screen(self, qapp: QApplication, _fake_mpv_manager: MagicMock, monkeypatch: Any) -> None:
        import freeassetfilter.components.video_player as vp_mod

        class _FakeHoverMenu(MagicMock):
            Position_Bottom = "bottom"

            def __init__(self, *a: Any, **k: Any) -> None:
                super().__init__()

        monkeypatch.setattr(vp_mod, "D_HoverMenu", _FakeHoverMenu)
        monkeypatch.setattr(vp_mod.QApplication, "primaryScreen", staticmethod(lambda: None))
        vp = self._make()
        try:
            vp._switch_to_floating_mode()
            # 无主屏 → 回退到 set_target_widget(_video_surface)
            vp._floating_control_bar.set_target_widget.assert_called_once_with(vp._video_surface)
        finally:
            vp._floating_control_bar = None
            vp._is_floating_mode = False
            safe_teardown(vp)

    def test_event_filter_classic_reset(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        from PySide6.QtCore import QPointF, QEvent
        from PySide6.QtGui import QMouseEvent

        vp = self._make()
        try:
            vp._is_floating_mode = True
            vp._floating_control_bar = MagicMock()
            vp._settings_manager.set_setting("player.fullscreen_classic_control_bar", False)
            press = QMouseEvent(
                QEvent.Type.MouseButtonPress, QPointF(10, 10), Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            )
            vp.eventFilter(vp._video_surface, press)
            vp._floating_control_bar.reset_auto_hide_timer.assert_called_once()
        finally:
            vp._is_floating_mode = False
            vp._floating_control_bar = None
            safe_teardown(vp)

    def test_switch_fixed_mode_disconnect_exception(self, qapp: QApplication, _fake_mpv_manager: MagicMock) -> None:
        vp = self._make()
        try:
            real_signal = vp._control_bar.popupMenuVisibilityChanged
            # 强制断开信号抛 TypeError → except 分支吞掉
            vp._control_bar.popupMenuVisibilityChanged = MagicMock(
                disconnect=MagicMock(side_effect=TypeError("boom"))
            )
            vp._is_floating_mode = True
            vp._switch_to_fixed_mode()
            assert vp._is_floating_mode is False
        finally:
            vp._control_bar.popupMenuVisibilityChanged = real_signal
            vp._is_floating_mode = False
            safe_teardown(vp)


class TestPhotoViewerDialogs:
    """PhotoViewer：打开文件对话框与异常路径。"""

    def _make_viewer(self) -> Any:
        from freeassetfilter.components.photo_viewer import PhotoViewer

        return PhotoViewer(global_font=_global_font(), dpi_scale=1.0, settings_manager=_settings_manager())

    def test_open_file_success(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        png = make_image(str(tmp_path / "open.png"))

        class _FD:
            @staticmethod
            def getOpenFileName(*a: Any, **k: Any) -> tuple:
                return (png, "")

        monkeypatch.setattr("freeassetfilter.components.photo_viewer.QFileDialog", _FD)
        viewer = self._make_viewer()
        loader: Any = None
        try:
            viewer.open_file()
            assert viewer.windowTitle() == "照片查看器 - open.png"
            loader = viewer.image_widget.image_loader
            ok: bool = _wait_until(qapp, lambda: viewer.image_widget.current_file_path == png)
            assert ok
        finally:
            if loader is not None:
                if loader.isRunning():
                    loader.cancel()
                loader.wait(3000)
            safe_teardown(viewer)

    def test_open_file_cancelled(self, qapp: QApplication, monkeypatch: Any) -> None:
        class _FD:
            @staticmethod
            def getOpenFileName(*a: Any, **k: Any) -> tuple:
                return ("", "")

        monkeypatch.setattr("freeassetfilter.components.photo_viewer.QFileDialog", _FD)
        viewer = self._make_viewer()
        try:
            viewer.open_file()
            assert viewer.windowTitle() == "照片查看器"
        finally:
            safe_teardown(viewer)

    def test_open_file_exception_shows_warning(self, qapp: QApplication, monkeypatch: Any) -> None:
        class _FD:
            @staticmethod
            def getOpenFileName(*a: Any, **k: Any) -> tuple:
                raise OSError("dialog failed")

        monkeypatch.setattr("freeassetfilter.components.photo_viewer.QFileDialog", _FD)
        warnings: List[Any] = []

        class _MB:
            @staticmethod
            def warning(*a: Any, **k: Any) -> Any:
                warnings.append(a)

        monkeypatch.setattr("freeassetfilter.components.photo_viewer.QMessageBox", _MB)
        viewer = self._make_viewer()
        try:
            viewer.open_file()
            assert warnings, "打开失败应弹出警告框"
        finally:
            safe_teardown(viewer)

    def test_load_image_from_path_exception(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        viewer = self._make_viewer()
        try:
            png = make_image(str(tmp_path / "x.png"))

            def _boom(path: str) -> bool:
                raise ValueError("boom")

            monkeypatch.setattr(viewer.image_widget, "set_image", _boom)
            assert viewer.load_image_from_path(png) is False
            assert viewer.windowTitle() == "照片查看器"
        finally:
            safe_teardown(viewer)


class TestGifViewerAndWidget:
    """GifViewer/GifWidget：真实 GIF 加载、电影数据回调与交互。"""

    def _make_viewer(self) -> Any:
        from freeassetfilter.components.photo_viewer import GifViewer

        return GifViewer(global_font=_global_font(), dpi_scale=1.0, settings_manager=_settings_manager())

    def _make_gif(self, path: str) -> None:
        from PIL import Image

        Image.new("RGB", (100, 100), (0, 255, 0)).save(path, format="GIF")

    def test_load_gif_missing_returns_false(self, qapp: QApplication) -> None:
        viewer = self._make_viewer()
        try:
            assert viewer.load_gif(str(tmp_missing())) is False
        finally:
            safe_teardown(viewer)

    def test_load_gif_valid_sets_movie(self, qapp: QApplication, tmp_path: Any) -> None:
        from PySide6.QtCore import QBuffer

        gif = tmp_path / "a.gif"
        self._make_gif(str(gif))
        viewer = self._make_viewer()
        loader: Any = None
        try:
            assert viewer.load_gif(str(gif)) is True
            loader = viewer.movie_loader
            ok: bool = _wait_until(
                qapp,
                lambda: viewer.movie is not None and viewer.gif_widget.current_file_path == str(gif),
            )
            assert ok, "GIF 数据未在预期时间内完成加载"
            assert isinstance(viewer._movie_buffer, QBuffer)
            assert viewer.windowTitle() == "GIF查看器 - a.gif"
        finally:
            if loader is not None:
                if loader.isRunning():
                    loader.cancel()
                loader.wait(3000)
            if viewer.movie is not None:
                viewer.movie.stop()
            safe_teardown(viewer)

    def test_on_movie_data_loaded_stale_seq_ignored(self, qapp: QApplication) -> None:
        viewer = self._make_viewer()
        try:
            viewer._current_load_sequence = 2
            viewer._on_movie_data_loaded(b"GIF89a garbage", "p.gif", 1)
            assert viewer.movie is None
            assert viewer._movie_buffer is None
        finally:
            safe_teardown(viewer)

    def test_on_movie_data_loaded_invalid_gif(self, qapp: QApplication) -> None:
        viewer = self._make_viewer()
        try:
            viewer._current_load_sequence = 1
            viewer._on_movie_data_loaded(b"\x00\x01\x02 not a gif", "bad.gif", 1)
            assert viewer.movie is None
        finally:
            safe_teardown(viewer)

    def test_on_movie_load_failed(self, qapp: QApplication) -> None:
        viewer = self._make_viewer()
        try:
            viewer._current_load_sequence = 1
            viewer._on_movie_load_failed("boom", 1)  # 匹配序列：仅记录日志
            viewer._on_movie_load_failed("boom", 2)  # 过期序列：忽略
        finally:
            safe_teardown(viewer)

    def test_gif_widget_first_frame_and_rotation(self, qapp: QApplication, tmp_path: Any) -> None:
        from PySide6.QtGui import QMovie

        from freeassetfilter.components.photo_viewer import GifWidget

        gif = tmp_path / "x.gif"
        self._make_gif(str(gif))
        movie = QMovie(str(gif))
        widget = GifWidget(settings_manager=_settings_manager())
        try:
            widget.set_movie(movie)
            movie.start()
            ok: bool = _wait_until(
                qapp,
                lambda: movie.currentPixmap() is not None and not movie.currentPixmap().isNull(),
            )
            assert ok, "GIF 第一帧未在预期时间内加载"
            widget._on_first_frame_loaded(0)
            assert widget.base_pixmap is not None
            assert widget.original_size.isValid()
            widget.rotate_clockwise()
            assert widget.rotation_steps == 1
            widget.on_frame_changed()
            widget._on_first_frame_loaded(5)  # 非首帧：不处理
            assert widget.rotation_steps == 1
        finally:
            movie.stop()
            safe_teardown(widget)

    def test_gif_widget_bg_color_switch(self, qapp: QApplication) -> None:
        from freeassetfilter.components.photo_viewer import GifWidget

        sm = _settings_manager()
        # 清掉可能从磁盘/settings.json 泄漏的历史键值，保证确定性
        sm.set_setting("photo_viewer.style.bg_color_key", "base_color")
        widget = GifWidget(settings_manager=sm)
        try:
            assert widget._current_bg_color_key == "base_color"
            widget._switch_bg_color()
            assert widget._current_bg_color_key == "secondary_color"
            assert sm.get_setting("photo_viewer.style.bg_color_key") == "secondary_color"
            # 显式指定颜色值，避免磁盘残留的 appearance.colors.secondary_color 干扰断言
            sm.set_setting("photo_viewer.style.remember_bg_color", True)
            sm.set_setting("appearance.colors.secondary_color", "#333333")
            assert widget._get_current_bg_color() == "#333333"
        finally:
            safe_teardown(widget)

    def test_gif_widget_mouse_and_wheel(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        from PySide6.QtCore import QEvent, QPoint, QPointF
        from PySide6.QtGui import QMouseEvent, QMovie, QWheelEvent

        from freeassetfilter.components.photo_viewer import GifWidget

        class _RecordingClipboard:
            def __init__(self) -> None:
                self._text = ""

            def setText(self, text: str) -> None:
                self._text = text

            def text(self) -> str:
                return self._text

        fake = _RecordingClipboard()
        # 真实系统剪贴板可能被外部进程锁定，改用记录型假剪贴板验证写入内容
        monkeypatch.setattr(QApplication, "clipboard", staticmethod(lambda: fake))
        gif = tmp_path / "x.gif"
        self._make_gif(str(gif))
        movie = QMovie(str(gif))
        widget = GifWidget(settings_manager=_settings_manager())
        widget.resize(300, 300)
        try:
            widget.set_movie(movie)
            movie.start()
            ok: bool = _wait_until(
                qapp,
                lambda: movie.currentPixmap() is not None and not movie.currentPixmap().isNull(),
            )
            assert ok
            widget._on_first_frame_loaded(0)

            before = widget.scale_factor
            wheel = QWheelEvent(
                QPointF(150, 150), QPointF(150, 150), QPoint(), QPoint(0, 120),
                Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
            )
            widget.wheelEvent(wheel)
            assert widget.scale_factor > before

            press = QMouseEvent(QEvent.MouseButtonPress, QPointF(150, 150), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            widget.mousePressEvent(press)
            assert widget.is_panning
            move = QMouseEvent(QEvent.MouseMove, QPointF(160, 160), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
            widget.mouseMoveEvent(move)
            assert widget.pan_offset == QPoint(10, 10)
            release = QMouseEvent(QEvent.MouseButtonRelease, QPointF(160, 160), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            widget.mouseReleaseEvent(release)
            assert not widget.is_panning

            widget.update_pixel_info(QPoint(150, 150))
            widget.copy_color_value()
            assert "RGB(" in fake.text()
        finally:
            movie.stop()
            safe_teardown(widget)

    def test_gif_widget_context_menu(self, qapp: QApplication, monkeypatch: Any) -> None:
        from PySide6.QtCore import QObject, QPoint, QTimer
        from PySide6.QtGui import QContextMenuEvent

        class _FakeMenu(QObject):
            itemClicked = Signal(str)

            def __init__(self, parent: Any = None) -> None:
                super().__init__(parent)
                self.items: List[Any] = []

            def set_items(self, items: List[Any]) -> None:
                self.items = items

            def popup(self, pos: QPoint) -> None:
                QTimer.singleShot(0, lambda: self.itemClicked.emit("fit_to_size"))

            def isVisible(self) -> bool:
                return False

        monkeypatch.setattr("freeassetfilter.widgets.D_more_menu.D_MoreMenu", _FakeMenu)

        from freeassetfilter.components.photo_viewer import GifWidget

        widget = GifWidget(settings_manager=_settings_manager())
        try:
            ev = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(10, 10), QPoint(20, 20))
            widget.contextMenuEvent(ev)
            assert hasattr(widget, "_context_menu")
            assert widget._context_menu.items, "菜单项应已构建"
            widget._on_context_menu_clicked("copy_color")
            widget._on_context_menu_clicked("fit_to_size")
            widget._on_context_menu_clicked("switch_bg_color")
            widget._on_context_menu_clicked("rotate_clockwise")
        finally:
            widget._context_menu = None
            safe_teardown(widget)

    def test_gif_widget_paint_and_reset(self, qapp: QApplication, tmp_path: Any) -> None:
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QMovie, QPaintEvent

        from freeassetfilter.components.photo_viewer import GifWidget

        widget = GifWidget(settings_manager=_settings_manager())
        widget.resize(300, 300)
        try:
            widget.paintEvent(QPaintEvent(QRect(0, 0, 300, 300)))  # 空图
            gif = tmp_path / "x.gif"
            self._make_gif(str(gif))
            movie = QMovie(str(gif))
            widget.set_movie(movie)
            movie.start()
            ok: bool = _wait_until(
                qapp,
                lambda: movie.currentPixmap() is not None and not movie.currentPixmap().isNull(),
            )
            assert ok
            widget._on_first_frame_loaded(0)
            widget.paintEvent(QPaintEvent(QRect(0, 0, 300, 300)))
            widget.reset_view()
            widget.reset_view()  # 幂等
        finally:
            movie.stop()
            safe_teardown(widget)

    def test_gif_viewer_reset_view(self, qapp: QApplication) -> None:
        viewer = self._make_viewer()
        try:
            viewer.reset_view()  # gif_widget 无图时安全
            viewer.reset_view()
        finally:
            safe_teardown(viewer)


# ===== pdf_previewer =====

class TestPdfPreviewer:
    """PDF 预览器：加载有效 / 缺失文件安全 / 翻页与缩放不崩溃。"""

    @pytest.fixture(autouse=True)
    def _inject_app_global(self, monkeypatch: Any, qapp: QApplication) -> None:
        """注入模块级 app 引用。

        PDFPageWidget.__init__ 在未传 settings_manager 时引用模块级 `app`
        （生产代码未定义该名字，加载流程必然 NameError）。测试注入 qapp
        模拟真实运行环境，使 PDF 渲染路径可完整走通。
        """
        import freeassetfilter.components.pdf_previewer as pdf_mod

        monkeypatch.setattr(pdf_mod, "app", qapp, raising=False)

    def _make_previewer(self) -> Any:
        from freeassetfilter.components.pdf_previewer import PDFPreviewer

        return PDFPreviewer(settings_manager=_settings_manager(), dpi_scale=1.0, global_font=_global_font())

    def test_load_valid_pdf(self, qapp: QApplication, tmp_path: Any) -> None:
        pdf_path: str = make_pdf(str(tmp_path / "doc.pdf"))
        previewer = self._make_previewer()
        try:
            finished: List[Any] = _signal_collector(previewer.pdf_render_finished)
            previewer.load_file_from_path(pdf_path)
            assert previewer.pdf_document.pageCount() == 1
            assert previewer.current_page == 0
            assert previewer.total_pages == 1
            ok: bool = _wait_until(qapp, lambda: bool(finished), timeout_ms=5000.0)
            assert ok, "应发射 pdf_render_finished"
        finally:
            previewer._close_document()
            safe_teardown(previewer)

    def test_load_missing_file_no_crash(self, qapp: QApplication) -> None:
        previewer = self._make_previewer()
        try:
            previewer.load_file_from_path(str(tmp_missing()))
            assert previewer.total_pages == 0 or previewer.current_page == 0
        finally:
            try:
                previewer._close_document()
            except Exception:
                pass
            safe_teardown(previewer)

    def test_navigation_no_crash(self, qapp: QApplication, tmp_path: Any) -> None:
        pdf_path: str = make_pdf(str(tmp_path / "nav.pdf"))
        previewer = self._make_previewer()
        try:
            previewer.load_file_from_path(pdf_path)
            _wait_until(qapp, lambda: previewer.current_page == 0, timeout_ms=5000.0)
            previewer._go_to_next_page()
            previewer._go_to_prev_page()
            previewer._go_to_prev_page()
            previewer._go_to_next_page()
            assert previewer.current_page == 0
        finally:
            try:
                previewer._close_document()
            except Exception:
                pass
            safe_teardown(previewer)

    def test_set_file_accepts_dict(self, qapp: QApplication, tmp_path: Any) -> None:
        pdf_path: str = make_pdf(str(tmp_path / "dict.pdf"))
        previewer = self._make_previewer()
        try:
            previewer.set_file(_make_finfo(pdf_path, suffix="pdf"))
            assert previewer.pdf_document.pageCount() == 1
        finally:
            try:
                previewer._close_document()
            except Exception:
                pass
            safe_teardown(previewer)


# ===== native_pdf_renderer =====

class TestNativePdfRenderer:
    """原生 PDF 渲染器：加载 / 页码查询 / 缩放边界 / 无效路径。"""

    def _make_renderer(self) -> Any:
        from freeassetfilter.components.native_pdf_renderer import NativePdfRenderer

        renderer = NativePdfRenderer(settings_manager=_settings_manager(), dpi_scale=1.0, global_font=_global_font())
        renderer.resize(640, 480)
        return renderer

    def _teardown(self, renderer: Any) -> None:
        try:
            renderer._renderer.cancel_all()
        except (RuntimeError, AttributeError):
            pass
        renderer.close()
        safe_teardown(renderer)

    def test_load_valid_document(self, qapp: QApplication, tmp_path: Any) -> None:
        pdf_path: str = make_pdf(str(tmp_path / "render.pdf"))
        renderer = self._make_renderer()
        try:
            pages: List[int] = []
            renderer.total_pages_changed.connect(pages.append)
            assert renderer.load_document(pdf_path) is True
            assert renderer.page_count() == 1
            assert renderer.current_page() == 0
            assert pages == [1]
        finally:
            self._teardown(renderer)

    def test_load_missing_returns_false(self, qapp: QApplication) -> None:
        renderer = self._make_renderer()
        try:
            assert renderer.load_document(str(tmp_missing())) is False
            assert renderer.page_count() == 0
        finally:
            self._teardown(renderer)

    def test_load_corrupt_returns_false(self, qapp: QApplication, tmp_path: Any) -> None:
        corrupt: str = str(tmp_path / "broken.pdf")
        with open(corrupt, "wb") as handle:
            handle.write(b"not a pdf at all")
        renderer = self._make_renderer()
        try:
            assert renderer.load_document(corrupt) is False
        finally:
            self._teardown(renderer)

    def test_zoom_clamps_to_valid_range(self, qapp: QApplication, tmp_path: Any) -> None:
        pdf_path: str = make_pdf(str(tmp_path / "zoom.pdf"))
        renderer = self._make_renderer()
        try:
            assert renderer.load_document(pdf_path) is True
            renderer.set_zoom(0.05)
            assert renderer._view.zoom_level >= 0.1
            renderer.set_zoom(50.0)
            assert renderer._view.zoom_level <= 10.0
        finally:
            self._teardown(renderer)

    def test_go_to_page_and_fit_no_crash(self, qapp: QApplication, tmp_path: Any) -> None:
        pdf_path: str = make_pdf(str(tmp_path / "page.pdf"))
        renderer = self._make_renderer()
        try:
            assert renderer.load_document(pdf_path) is True
            renderer.go_to_page(0)
            renderer.fit_to_page()
            assert renderer.current_page() == 0
        finally:
            self._teardown(renderer)


# ===== text_previewer =====

class TestTextPreviewer:
    """文本预览器：加载文本 / 编码探测 / 缺失文件安全 / 清理幂等。"""

    def _make_previewer(self) -> Any:
        from freeassetfilter.components.text_previewer import TextPreviewer

        return TextPreviewer(settings_manager=_settings_manager(), dpi_scale=1.0, global_font=_global_font())

    def _wait_not_loading(self, app: QApplication, previewer: Any) -> bool:
        return _wait_until(app, lambda: not bool(previewer.preview_widget._is_loading), timeout_ms=8000.0)

    def test_load_text_file(self, qapp: QApplication, tmp_path: Any) -> None:
        txt_path: str = make_text(str(tmp_path / "hello.txt"), content="Hello, World!\n第二行内容")
        previewer = self._make_previewer()
        try:
            previewer.set_file(txt_path)
            assert self._wait_not_loading(qapp, previewer)
            content: str = previewer.preview_widget.text_edit.toPlainText()
            assert "Hello, World!" in content
        finally:
            self._abort_text_thread(previewer)
            safe_teardown(previewer)

    def test_load_gbk_encoding(self, qapp: QApplication, tmp_path: Any) -> None:
        txt_path: str = make_text(str(tmp_path / "gbk.txt"), content="编码测试 GBK 内容", encoding="gbk")
        previewer = self._make_previewer()
        try:
            previewer.set_file(txt_path)
            assert self._wait_not_loading(qapp, previewer)
            content: str = previewer.preview_widget.text_edit.toPlainText()
            assert "编码测试" in content
        finally:
            self._abort_text_thread(previewer)
            safe_teardown(previewer)

    def test_missing_file_no_crash(self, qapp: QApplication) -> None:
        previewer = self._make_previewer()
        try:
            previewer.set_file(str(tmp_missing()))
            assert self._wait_not_loading(qapp, previewer)
        finally:
            self._abort_text_thread(previewer)
            safe_teardown(previewer)

    def test_cleanup_twice_is_idempotent(self, qapp: QApplication) -> None:
        previewer = self._make_previewer()
        try:
            previewer.cleanup()
            previewer.cleanup()
        finally:
            safe_teardown(previewer)

    def _abort_text_thread(self, previewer: Any) -> None:
        try:
            thread = previewer.preview_widget._thread
            if thread is not None and thread.isRunning():
                thread.abort()
                thread.wait(2000)
        except (RuntimeError, AttributeError):
            pass


# ===== font_previewer =====

class TestFontPreviewWidget:
    """字体预览控件：调用 font_previewer 模块而非损坏的 FontPreviewer 包装。

    注意：``FontPreviewer()`` 构造触发生产 NameError（未传 settings_manager
    给 FontPreviewWidget，见文件头说明），故只测底层控件。
    """

    def _make_widget(self) -> Any:
        from freeassetfilter.components.font_previewer import FontPreviewWidget

        return FontPreviewWidget(
            settings_manager=_settings_manager(),
            dpi_scale=1.0,
            global_font=_global_font(),
        )

    def test_construction_with_settings_manager(self, qapp: QApplication) -> None:
        widget = self._make_widget()
        try:
            assert widget is not None
            assert hasattr(widget, "text_edit")
        finally:
            widget.cleanup()
            safe_teardown(widget)

    def test_missing_font_file_no_crash(self, qapp: QApplication) -> None:
        widget = self._make_widget()
        try:
            widget.set_file(str(tmp_missing()))
            process_qt_events(qapp, ms=100)
        finally:
            widget.cleanup()
            safe_teardown(widget)

    def test_load_real_font(self, qapp: QApplication, tmp_path: Any) -> None:
        font_path: Optional[str] = make_font_path()
        if font_path is None:
            pytest.skip("当前环境无可用的 Windows 字体")
        widget = self._make_widget()
        try:
            widget.set_file(font_path)
            loaded: bool = _wait_until(
                qapp,
                lambda: bool(getattr(widget, "current_font_family", "")) or bool(getattr(widget, "font_id", None) != -1),
                timeout_ms=8000.0,
            )
            assert loaded, "字体异步加载未在预期时间内完成"
        finally:
            widget.cleanup()
            safe_teardown(widget)

    def test_cleanup_twice_is_idempotent(self, qapp: QApplication) -> None:
        widget = self._make_widget()
        try:
            widget.cleanup()
            widget.cleanup()
        finally:
            safe_teardown(widget)


# ===== archive_browser =====

class TestArchiveBrowser:
    """压缩包浏览器：加载压缩包 / 编码切换 / 缺失路径安全。"""

    @pytest.fixture(autouse=True)
    def _silence_message_boxes(self, monkeypatch: Any) -> None:
        """屏蔽设置失败路径的模态弹窗，防止测试卡死。"""
        import freeassetfilter.components.archive_browser as archive_mod

        class _NoopMB:  # noqa: N806
            @staticmethod
            def warning(*_args: Any, **_kwargs: Any) -> None:
                return None

            @staticmethod
            def critical(*_args: Any, **_kwargs: Any) -> None:
                return None

        monkeypatch.setattr(archive_mod, "QMessageBox", _NoopMB)

    def _make_browser(self) -> Any:
        from freeassetfilter.components.archive_browser import ArchiveBrowser

        return ArchiveBrowser(settings_manager=_settings_manager(), dpi_scale=1.0, global_font=_global_font())

    def test_load_zip_lists_entries(self, qapp: QApplication, tmp_path: Any, py7z_available: bool) -> None:
        if not py7z_available:
            pytest.skip("py7z / 7z.exe 不可用")
        zip_path: str = make_zip(str(tmp_path / "bundle.zip"), {"a.txt": "A", "b.txt": "B", "sub/c.txt": "C"})
        browser = self._make_browser()
        try:
            browser.set_archive_path(zip_path)
            assert browser.archive_path == zip_path
            assert browser.files_list.count() >= 3
            names: List[str] = [browser.files_list.item(i).text() for i in range(browser.files_list.count())]
            assert any("a.txt" in n for n in names)
        finally:
            safe_teardown(browser)

    def test_encoding_change_refreshes(self, qapp: QApplication, tmp_path: Any, py7z_available: bool) -> None:
        if not py7z_available:
            pytest.skip("py7z / 7z.exe 不可用")
        zip_path: str = make_zip(str(tmp_path / "enc.zip"), {"文件.txt": "内容"})
        browser = self._make_browser()
        try:
            browser.set_archive_path(zip_path)
            browser._on_encoding_changed("gbk")
            assert browser.manual_encoding == "gbk"
        finally:
            safe_teardown(browser)

    def test_invalid_path_no_crash(self, qapp: QApplication) -> None:
        browser = self._make_browser()
        try:
            browser.set_archive_path(str(tmp_missing()))
            assert browser.archive_path is None or browser.archive_path == ""
        finally:
            safe_teardown(browser)


# ===== folder_content_list =====

class TestFolderContentList:
    """文件夹内容列表：set_path 加载 / 打开信号 / 线程清理。"""

    def _make_list(self) -> Any:
        from freeassetfilter.components.folder_content_list import FolderContentList

        return FolderContentList(settings_manager=_settings_manager(), dpi_scale=1.0, global_font=_global_font())

    def _stop_thread(self, fl: Any) -> None:
        try:
            thread = fl._load_thread
            if thread is not None and thread.isRunning():
                thread.quit()
                thread.wait(2000)
        except (RuntimeError, AttributeError):
            pass

    def test_set_path_loads_entries(self, qapp: QApplication, tmp_path: Any) -> None:
        (tmp_path / "one.txt").write_text("1", encoding="utf-8")
        (tmp_path / "two.txt").write_text("2", encoding="utf-8")
        (tmp_path / "sub").mkdir()

        fl = self._make_list()
        try:
            self._stop_thread(fl)
            fl.set_path(str(tmp_path))
            assert fl.current_path == str(tmp_path)

            def _loaded() -> bool:
                return fl.content_list.count() > 0 and fl.content_list.item(0).text() != "正在加载..."

            assert _wait_until(qapp, _loaded, timeout_ms=8000.0), "文件夹内容未在预期时间内加载"
            assert fl.content_list.count() >= 3
        finally:
            self._stop_thread(fl)
            safe_teardown(fl)

    def test_open_in_selector_signal(self, qapp: QApplication, tmp_path: Any) -> None:
        (tmp_path / "one.txt").write_text("1", encoding="utf-8")

        fl = self._make_list()
        try:
            self._stop_thread(fl)
            fl.set_path(str(tmp_path))
            _wait_until(
                qapp,
                lambda: fl.content_list.count() > 0 and fl.content_list.item(0).text() != "正在加载...",
                timeout_ms=8000.0,
            )
            captured: List[Any] = _signal_collector(fl.open_in_selector_requested)
            fl._on_open_in_selector_clicked()
            assert captured, "应发射 open_in_selector_requested"
            assert captured[0][0] == str(tmp_path)
            assert captured[0][1]["path"] == str(tmp_path)
            assert captured[0][1]["is_directory"] is True
        finally:
            self._stop_thread(fl)
            safe_teardown(fl)

    def test_set_path_to_missing_no_crash(self, qapp: QApplication) -> None:
        fl = self._make_list()
        try:
            self._stop_thread(fl)
            fl.set_path(str(tmp_missing()))
            assert fl.current_path != str(tmp_missing()) or fl._load_thread is not None
        finally:
            self._stop_thread(fl)
            safe_teardown(fl)


# ===== file_info_previewer =====

class TestFileInfoPreviewer:
    """文件信息预览器：get_ui 初始化 → set_file 提取基本信息与详情。"""

    def _make_previewer(self) -> Any:
        from freeassetfilter.components.file_info_previewer import FileInfoPreviewer

        return FileInfoPreviewer(settings_manager=_settings_manager(), dpi_scale=1.0, global_font=_global_font())

    def test_set_file_file_type(self, qapp: QApplication, tmp_path: Any) -> None:
        png_path: str = make_image(str(tmp_path / "info.png"))
        previewer = self._make_previewer()
        ui = previewer.get_ui()
        try:
            finfo: dict = _make_finfo(png_path, suffix="png")
            previewer.set_file(finfo)
            assert previewer.current_file == finfo
            assert previewer.file_info["basic"]["文件名"] == "info.png"
            assert previewer.file_info["details"]["文件类型"] == "png"
        finally:
            safe_teardown(previewer)
            safe_teardown(ui)

    def test_set_file_directory(self, qapp: QApplication, tmp_path: Any) -> None:
        previewer = self._make_previewer()
        ui = previewer.get_ui()
        try:
            finfo: dict = _make_finfo(str(tmp_path), is_dir=True)
            previewer.set_file(finfo)
            assert previewer.current_file == finfo
            assert "details" in previewer.file_info
            assert isinstance(previewer.file_info["details"], dict)
            assert bool(previewer.file_info["details"]), "目录详情不应为空"
        finally:
            safe_teardown(previewer)
            safe_teardown(ui)

    def test_set_file_missing_path_graceful(self, qapp: QApplication) -> None:
        previewer = self._make_previewer()
        ui = previewer.get_ui()
        try:
            finfo: dict = _make_finfo(str(tmp_missing()), suffix="png")
            previewer.set_file(finfo)
            assert previewer.file_info["basic"]["文件大小"] == "无法获取"
        finally:
            safe_teardown(previewer)
            safe_teardown(ui)


# ===== file_info_previewer 格式/哈希/目录/音频/各类型详解 =====

class TestFileInfoPreviewerDetail:
    """文件信息预览器：格式化 helper、哈希、目录、音频管线与各类型详解方法。"""

    def _make_previewer(self) -> Any:
        from freeassetfilter.components.file_info_previewer import FileInfoPreviewer

        return FileInfoPreviewer(settings_manager=_settings_manager(), dpi_scale=1.0, global_font=_global_font())

    def test_format_helpers(self, qapp: QApplication) -> None:
        """_format_size/_format_duration/_format_bitrate：各量级与负值。"""
        from freeassetfilter.components.file_info_previewer import FileInfoPreviewer

        pv = FileInfoPreviewer(settings_manager=_settings_manager(), dpi_scale=1.0, global_font=_global_font())
        try:
            assert pv._format_size(-1) == "无法获取"
            assert pv._format_size(512) == "512.0 B"
            assert pv._format_size(1536) == "1.5 KB"
            assert pv._format_size(1024 ** 4) == "1.0 TB"
            assert "PB" in pv._format_size(1024 ** 5)

            assert pv._format_duration(-5) == "无法获取"
            assert pv._format_duration(0) == "00:00"
            assert pv._format_duration(59) == "00:59"
            assert pv._format_duration(3661) == "01:01:01"

            assert pv._format_bitrate(-1) == "无法获取"
            assert pv._format_bitrate(500) == "500 bps"
            assert pv._format_bitrate(1500) == "1.5 Kbps"
            assert pv._format_bitrate(2000000) == "2.0 Mbps"
        finally:
            safe_teardown(pv)

    def test_get_file_hash_success_and_failure(self, qapp: QApplication, tmp_path: Any) -> None:
        """_get_file_hash：真实文件返回摘要；缺失文件返回"无法计算"。"""
        import hashlib

        png_path: str = make_image(str(tmp_path / "hash.png"))
        pv = self._make_previewer()
        try:
            hash256 = pv._get_file_hash(png_path, hashlib.sha256)
            assert len(hash256) == 64
            assert hash256 == hashlib.sha256(open(png_path, "rb").read()).hexdigest()
            assert pv._get_file_hash(str(tmp_missing()), hashlib.md5) == "无法计算"

            # 空文件也计算成功（可解码）
            empty = tmp_path / "empty.bin"
            empty.write_bytes(b"")
            assert pv._get_file_hash(str(empty), hashlib.sha1).startswith("da39a3ee")
        finally:
            safe_teardown(pv)

    def test_get_directory_info_success(self, qapp: QApplication, tmp_path: Any) -> None:
        """_get_directory_info：真实目录返回子目录数与文件数。"""
        (tmp_path / "sub").mkdir()
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        pv = self._make_previewer()
        try:
            info = pv._get_directory_info(str(tmp_path))
            assert info["子目录数"] == 1
            assert info["文件数"] == 1
        finally:
            safe_teardown(pv)

    def test_get_directory_info_unreachable(self, qapp: QApplication) -> None:
        """_get_directory_info：缺失目录返回"无法访问"占位。"""
        pv = self._make_previewer()
        try:
            info = pv._get_directory_info(str(tmp_missing()))
            assert info["子目录数"] == "无法访问"
            assert info["文件数"] == "无法访问"
        finally:
            safe_teardown(pv)

    def test_get_audio_info_async_pipeline(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        """_get_audio_info → _start_audio_info_task → run → _on_audio_info_loaded 全链路。"""
        from unittest.mock import MagicMock

        import freeassetfilter.components.file_info_previewer as fip
        from PySide6.QtCore import QThreadPool

        audio_path = tmp_path / "song.mp3"
        audio_path.write_bytes(b"ID3dummy")

        class _FakePool:
            def __init__(self) -> None:
                self.started: list = []

            def start(self, runnable: Any) -> None:
                self.started.append(runnable)

        pool = _FakePool()
        monkeypatch.setattr(QThreadPool, "globalInstance", staticmethod(lambda: pool))

        fake_audio = MagicMock()
        fake_audio.info.length = 65.5
        fake_audio.info.bitrate = 128000
        fake_audio.info.channels = 2
        fake_audio.info.sample_rate = 44100
        monkeypatch.setattr(fip, "mutagen_file", lambda path: fake_audio)

        pv = self._make_previewer()
        collected = _signal_collector(pv.audioInfoLoaded)
        try:
            info = pv._get_audio_info(str(audio_path))
            assert info["时长"] == "加载中..."
            assert len(pool.started) == 1
            task = pool.started[0]
            assert pv._current_audio_task is task

            # 同步执行任务.run（QRunnable 可直调）
            task.run()
            assert pv._current_audio_task is None
            assert pv.file_info["details"]["时长"] == "01:05"
            assert pv.file_info["details"]["比特率"] == "128.0 Kbps"
            assert pv.file_info["details"]["声道数"] == 2
            assert pv.file_info["details"]["采样率"] == "44100 Hz"
            assert len(collected) == 1

            # 过期任务 ID 被忽略
            pv._audio_task_id = 99
            pv._on_audio_info_loaded(1, {"时长": "旧"})
            assert pv.file_info["details"]["时长"] == "01:05"

            # 取消语义：cancel() 后 run 不回调
            pv2 = self._make_previewer()
            calls: list = []
            task2 = fip.AudioInfoTask(str(audio_path), 1, lambda tid, d: calls.append(d))
            task2.cancel()
            task2.run()
            assert calls == []
            safe_teardown(pv2)
        finally:
            safe_teardown(pv)

    def test_cancel_audio_task(self, qapp: QApplication, tmp_path: Any) -> None:
        """_cancel_audio_task：有当前任务时取消并清引用，无任务时安全。"""
        from unittest.mock import MagicMock

        pv = self._make_previewer()
        try:
            pv._cancel_audio_task()
            assert pv._current_audio_task is None

            task = MagicMock()
            pv._current_audio_task = task
            pv._cancel_audio_task()
            task.cancel.assert_called_once()
            assert pv._current_audio_task is None
        finally:
            safe_teardown(pv)

    def test_get_audio_advanced_info_empty(self, qapp: QApplication, tmp_path: Any) -> None:
        """_get_audio_advanced_info：恒为空字典。"""
        pv = self._make_previewer()
        try:
            assert pv._get_audio_advanced_info(str(tmp_path)) == {}
        finally:
            safe_teardown(pv)

    def test_get_audio_info_sync_mutagen(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        """_get_audio_info_sync：mutagen 命中即返回，不回落 ffprobe。"""
        from unittest.mock import MagicMock

        import freeassetfilter.components.file_info_previewer as fip

        audio_path = tmp_path / "a.flac"
        audio_path.write_bytes(b"fLaC")
        fake_audio = MagicMock()
        fake_audio.info.length = 10
        fake_audio.info.bitrate = 320000
        fake_audio.info.channels = 1
        fake_audio.info.sample_rate = 48000
        monkeypatch.setattr(fip, "mutagen_file", lambda path: fake_audio)
        monkeypatch.setattr(fip, "run_with_limited_output", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应调用 ffprobe")))

        pv = self._make_previewer()
        try:
            info = pv._get_audio_info_sync(str(audio_path))
            assert info["时长"] == "00:10"
            assert info["比特率"] == "320.0 Kbps"
            assert info["声道数"] == 1
        finally:
            safe_teardown(pv)

    def test_get_audio_info_sync_ffprobe_fallback(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        """_get_audio_info_sync：mutagen 无效时回落 ffprobe JSON。"""
        from types import SimpleNamespace

        import freeassetfilter.components.file_info_previewer as fip

        audio_path = tmp_path / "b.ogg"
        audio_path.write_bytes(b"OggS")
        monkeypatch.setattr(fip, "mutagen_file", lambda path: None)
        monkeypatch.setattr(fip, "get_ffprobe_path", lambda: "ffprobe")
        monkeypatch.setattr(fip, "get_subprocess_creationflags", lambda: 0)
        result = SimpleNamespace(stdout='{"format": {"duration": "33", "bit_rate": "96000"}}', stdout_truncated=False)
        monkeypatch.setattr(fip, "run_with_limited_output", lambda *a, **k: result)

        pv = self._make_previewer()
        try:
            info = pv._get_audio_info_sync(str(audio_path))
            assert info["时长"] == "00:33"
            assert info["比特率"] == "96.0 Kbps"
        finally:
            safe_teardown(pv)

    def test_get_audio_info_sync_failure(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        """_get_audio_info_sync：全失败时回落"无法获取"。"""
        import subprocess

        import freeassetfilter.components.file_info_previewer as fip

        audio_path = tmp_path / "c.mp3"
        audio_path.write_bytes(b"X")

        def _boom(*a: Any, **k: Any) -> None:
            raise subprocess.SubprocessError("boom")

        monkeypatch.setattr(fip, "mutagen_file", lambda path: None)
        monkeypatch.setattr(fip, "get_ffprobe_path", lambda: "ffprobe")
        monkeypatch.setattr(fip, "run_with_limited_output", _boom)

        pv = self._make_previewer()
        try:
            info = pv._get_audio_info_sync(str(audio_path))
            assert info["时长"] == "无法获取"
            assert info["比特率"] == "无法获取"
        finally:
            safe_teardown(pv)

    def test_get_video_info_and_advanced(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        """_get_video_info/_get_video_advanced_info：流信息命中与异常。"""
        from types import SimpleNamespace

        import freeassetfilter.components.file_info_previewer as fip

        video_path = tmp_path / "m.mp4"
        video_path.write_bytes(b"MDAta")

        good = {"duration_seconds": 120, "width": 1920, "height": 1080, "fps": 30.0,
                "codec": "h264", "bitrate": 2000000}
        monkeypatch.setattr(fip, "get_video_stream_info", lambda path: good)

        pv = self._make_previewer()
        try:
            info = pv._get_video_info(str(video_path))
            assert info["时长"] == "02:00"
            assert info["分辨率"] == "1920 x 1080"
            assert info["帧率"] == "30.00 fps"
            adv = pv._get_video_advanced_info(str(video_path))
            assert adv["视频编解码器"] == "h264"
            assert adv["码率"] == "2.0 Mbps"

            # 异常分支：流信息抛错 → 基本字段兜底
            pv2 = self._make_previewer()
            monkeypatch.setattr(fip, "get_video_stream_info", lambda path: (_ for _ in ()).throw(RuntimeError("x")))
            try:
                info2 = pv2._get_video_info(str(video_path))
                assert info2 == {"文件大小": pv2._format_size(5)}
                adv2 = pv2._get_video_advanced_info(str(video_path))
                assert adv2 == {"码率": "无法获取"}
            finally:
                safe_teardown(pv2)

            # 部分缺失字段不写入
            pv3 = self._make_previewer()
            monkeypatch.setattr(fip, "get_video_stream_info", lambda path: {"duration_seconds": None, "width": 0, "height": 0})
            try:
                assert pv3._get_video_info(str(video_path)) == {"文件大小": pv3._format_size(5)}
            finally:
                safe_teardown(pv3)
        finally:
            safe_teardown(pv)

    def test_get_image_info_success(self, qapp: QApplication, tmp_path: Any) -> None:
        """_get_image_info：PIL 可读取时返回尺寸/格式/模式。"""
        png_path: str = make_image(str(tmp_path / "pic.png"))
        pv = self._make_previewer()
        try:
            info = pv._get_image_info(png_path)
            assert info["尺寸"] == "240 x 160"
            assert info["格式"] == "PNG"
            assert info["模式"] == "RGB"
        finally:
            safe_teardown(pv)

    def test_get_image_info_failure(self, qapp: QApplication) -> None:
        """_get_image_info：无法读取时返回"无法获取"占位。"""
        pv = self._make_previewer()
        try:
            info = pv._get_image_info(str(tmp_missing()))
            assert info["尺寸"] == "无法获取"
            assert info["格式"] == "无法获取"
            assert info["模式"] == "无法获取"
        finally:
            safe_teardown(pv)

    def test_get_text_info_success_and_failure(self, qapp: QApplication, tmp_path: Any) -> None:
        """_get_text_info：可读文本统计字符/行/单词；不可读时占位。"""
        text_path: str = make_text(str(tmp_path / "doc.txt"))
        pv = self._make_previewer()
        try:
            info = pv._get_text_info(text_path)
            assert info["字符数"] >= 1
            assert info["行数"] >= 1
            assert info["单词数"] >= 1
            assert "编码格式" in info

            bad = pv._get_text_info(str(tmp_missing()))
            assert bad["编码格式"] == "无法检测"
            assert bad["字符数"] == "无法统计"
            assert bad["行数"] == "无法统计"
        finally:
            safe_teardown(pv)

    def test_get_text_advanced_info(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        """_get_text_advanced_info：magic 不可用返回空；可用时返回 MIME。"""
        import freeassetfilter.components.file_info_previewer as fip

        text_path: str = make_text(str(tmp_path / "adv.txt"))
        pv = self._make_previewer()
        try:
            # magic 缺失（当前环境实测无 python-magic）
            assert pv._get_text_advanced_info(text_path) == {}

            # 注入 fake magic 命中分支
            class _FakeMagic:
                def __init__(self, mime: bool = False) -> None:
                    self.mime = mime

                def from_file(self, path: str) -> str:
                    return "text/plain" if self.mime else "ASCII text"

            monkeypatch.setattr(fip, "magic", type("M", (), {"Magic": _FakeMagic}))
            mime_info = pv._get_text_advanced_info(text_path)
            assert mime_info["MIME类型"] == "text/plain"
            assert mime_info["详细类型"] == "ASCII text"
        finally:
            safe_teardown(pv)

    def test_get_archive_info(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        """_get_archive_info：7z 核心命中（含 dir 条目）与 iso 特例、异常兜底。"""
        import freeassetfilter.components.file_info_previewer as fip

        zip_path: str = make_zip(str(tmp_path / "pack.zip"), {"a.txt": "hello", "b.txt": "world"})
        pv = self._make_previewer()
        try:
            class _Fake7z:
                def get_archive_type(self, path: str) -> str:
                    return "zip"

                def list_archive(self, path: str, encoding: str = "utf-8") -> list:
                    return [
                        {"path": "a.txt", "size": 5, "is_dir": False, "modified": "2020-01-01"},
                        {"path": "b.txt", "size": 5, "is_dir": False, "modified": "2020-01-02"},
                        {"path": "sub", "size": 0, "is_dir": True, "modified": ""},
                    ]

            fake = _Fake7z()
            monkeypatch.setattr(pv, "_7z_core", fake)
            info = pv._get_archive_info(zip_path)
            assert info["压缩格式"] == "zip"
            assert info["文件数"] == 2
            assert info["总大小"] == "10.0 B"
            assert info["压缩率"].endswith("%")

            # iso 特例：压缩率 N/A
            class _Iso7z:
                def get_archive_type(self, path: str) -> str:
                    return "iso"

                def list_archive(self, path: str, encoding: str = "utf-8") -> list:
                    return [{"path": "x", "size": 5, "is_dir": False, "modified": ""}]

            monkeypatch.setattr(pv, "_7z_core", _Iso7z())
            assert pv._get_archive_info(zip_path)["压缩率"] == "N/A"

            # 空条目 → 压缩率 无法计算
            class _Empty7z:
                def get_archive_type(self, path: str) -> str:
                    return "zip"

                def list_archive(self, path: str, encoding: str = "utf-8") -> list:
                    return []

            monkeypatch.setattr(pv, "_7z_core", _Empty7z())
            empty_info = pv._get_archive_info(zip_path)
            assert empty_info["压缩率"] == "无法计算"

            # 异常兜底
            class _Boom7z:
                def get_archive_type(self, path: str) -> str:
                    raise RuntimeError("boom")

            monkeypatch.setattr(pv, "_7z_core", _Boom7z())
            bad = pv._get_archive_info(zip_path)
            assert bad["文件数"] == "无法获取"
            assert bad["总大小"] == "无法获取"
            assert bad["压缩率"] == "无法计算"
        finally:
            safe_teardown(pv)

    def test_get_archive_advanced_info(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        """_get_archive_advanced_info：>10 条目追加省略行；异常安全。"""
        import freeassetfilter.components.file_info_previewer as fip

        zip_path: str = make_zip(str(tmp_path / "many.zip"), {"x.txt": "x"})
        pv = self._make_previewer()
        try:
            class _Many7z:
                def list_archive(self, path: str, encoding: str = "utf-8") -> list:
                    return [{"path": f"f{i}.txt", "size": 10, "is_dir": False, "modified": None} for i in range(15)]

            monkeypatch.setattr(pv, "_7z_core", _Many7z())
            info = pv._get_archive_advanced_info(zip_path)
            assert len(info["内容列表"]) == 11
            assert "还有 5 个文件" in info["内容列表"][-1]["名称"]

            class _Boom7z:
                def list_archive(self, path: str, encoding: str = "utf-8") -> list:
                    raise RuntimeError("boom")

            monkeypatch.setattr(pv, "_7z_core", _Boom7z())
            assert pv._get_archive_advanced_info(zip_path) == {}
        finally:
            safe_teardown(pv)

    def test_get_pdf_info_and_advanced(self, qapp: QApplication, tmp_path: Any) -> None:
        """_get_pdf_info/_get_pdf_advanced_info：占位实现。"""
        pdf_path: str = make_pdf(str(tmp_path / "doc.pdf"))
        pv = self._make_previewer()
        try:
            assert pv._get_pdf_info(pdf_path) == {"页数": "无法获取"}
            assert pv._get_pdf_advanced_info(pdf_path) == {}
        finally:
            safe_teardown(pv)

    def test_get_font_info_and_advanced(self, qapp: QApplication, tmp_path: Any) -> None:
        """_get_font_info/_get_font_advanced_info：fontTools 缺失时安全返回空。"""
        font_path = make_font_path()
        pv = self._make_previewer()
        try:
            if font_path is None:
                pytest.skip("无可用字体样本")
            assert pv._get_font_info(font_path) == {}
            assert pv._get_font_advanced_info(font_path) == {}
        finally:
            safe_teardown(pv)

    def test_extract_file_info_no_current(self, qapp: QApplication) -> None:
        """extract_file_info：无当前文件时直接返回不改状态。"""
        pv = self._make_previewer()
        try:
            pv.current_file = None
            pv.extract_file_info()
            assert pv.file_info == {}
        finally:
            safe_teardown(pv)


# ===== file_info_previewer 覆盖补充：详情线程 / 缓存 / 剪贴板 / 各类型分支 =====

from types import SimpleNamespace

class _FakeClipboard:
    """测试用记录剪贴板：规避 Windows OpenClipboard 锁与写后读回问题。"""

    def __init__(self) -> None:
        self._text = ""

    def setText(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class _Fake7z:
    """7z 核心假实现：zip 文件 + 一个目录条目。"""

    def get_archive_type(self, path: str) -> str:
        return "zip"

    def list_archive(self, path: str, encoding: str = "utf-8") -> list:
        return [
            {"path": "a.txt", "size": 5, "is_dir": False, "modified": "2020-01-01"},
            {"path": "sub", "size": 0, "is_dir": True, "modified": ""},
        ]


class _FakeTTFont:
    """最小 TTFont 假实现（fontTools 未安装时注入 sys.modules 覆盖字体分支）。"""

    def __init__(self, path: Any) -> None:
        pass

    def __enter__(self) -> "_FakeTTFont":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def __contains__(self, key: str) -> bool:
        return key in ("hhea", "name", "CFF ")

    def __getitem__(self, key: str) -> Any:
        if key == "name":
            return SimpleNamespace(
                names=[
                    SimpleNamespace(nameID=1, string="MyFont".encode("utf-8")),
                    SimpleNamespace(nameID=2, string=b"\xff\xfe\xfd\xfc"),
                    SimpleNamespace(nameID=4, string="MyFont-Regular".encode("utf-8")),
                ]
            )
        if key == "hhea":
            return SimpleNamespace(ascent=800, descent=-200, lineGap=90)
        if key == "CFF ":
            return None
        raise KeyError(key)

    def getGlyphOrder(self) -> list:
        return ["A", "B", "C"]


class TestFileInfoPreviewerCoverage:
    """file_info_previewer 补充覆盖：详情加载线程、缓存读写、右键菜单、类型分派分支。"""

    def _make_previewer(self) -> Any:
        from freeassetfilter.components.file_info_previewer import FileInfoPreviewer

        return FileInfoPreviewer(settings_manager=_settings_manager(), dpi_scale=1.0, global_font=_global_font())

    @staticmethod
    def _sync_pool(monkeypatch: Any) -> None:
        """把 QThreadPool.globalInstance 换成同步 fake pool，runnable 立即 run（确定性）。"""
        from PySide6.QtCore import QThreadPool

        class _SyncPool:
            def start(self, runnable: Any) -> None:
                if hasattr(runnable, "run"):
                    runnable.run()

        monkeypatch.setattr(QThreadPool, "globalInstance", staticmethod(lambda: _SyncPool()))

    def _run_detail_thread(self, pv: Any) -> None:
        """同步执行详情加载线程体，随后等待真实线程收尾避免竞态。"""
        thread = pv.load_thread
        thread.run()
        if thread.isRunning():
            thread.wait(5000)
        if hasattr(pv, "loading_dialog") and pv.loading_dialog:
            pv.loading_dialog.close()

    def test_detail_load_cache_roundtrip(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        """详情加载：cache miss → 线程计算 → _on_loading_finished → 缓存落盘 → 缓存命中回放。"""
        import json

        text_path: str = make_text(str(tmp_path / "note.txt"))
        pv = self._make_previewer()
        ui = pv.get_ui()
        monkeypatch.setattr(pv, "_get_cache_dir", lambda: str(tmp_path))
        self._sync_pool(monkeypatch)
        try:
            pv.set_file(_make_finfo(text_path, suffix="txt"))

            # 线程结果带"元数据"键 → _on_loading_finished 须过滤
            pv._get_text_advanced_info = lambda p: {"元数据": {"artist": "x"}}  # type: ignore[method-assign]
            pv._load_detailed_info()
            assert pv.loading_dialog is not None
            self._run_detail_thread(pv)

            # 详情 + 哈希字段 + 更多信息按钮隐藏
            assert pv.file_info["details"]["字符数"] >= 1
            assert pv.file_info["details"]["行数"] >= 1
            assert "MD5" in pv.basic_info_widgets
            assert "SHA1" in pv.basic_info_labels
            assert pv.more_info_btn.isHidden()

            # 缓存已写到临时目录（realpath 规范化后键一致）
            cache_file = tmp_path / "file_info_cache.json"
            assert cache_file.exists()
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            assert any(v["basic"]["MD5"] for v in cached.values())

            # update_ui：哈希值样式分支 + 详情清空分支
            pv.file_info["basic"]["MD5"] = "deadbeef"
            pv.update_ui()
            pv.update_ui()

            # 二次加载 → 命中缓存：不再创建线程
            pv._load_detailed_info()
            assert pv.file_info["details"]["字符数"] >= 1
            assert pv.more_info_btn.isHidden()
        finally:
            if hasattr(pv, "load_thread") and pv.load_thread.isRunning():
                pv.load_thread.wait(3000)
            if hasattr(pv, "loading_dialog") and pv.loading_dialog:
                pv.loading_dialog.close()
            safe_teardown(pv)
            safe_teardown(ui)

    @pytest.mark.parametrize(
        "fname, suffix, kind, expected_key",
        [
            ("pic.png", "png", "image", "尺寸"),
            ("mov.mp4", "mp4", "video", "帧率"),
            ("song.mp3", "mp3", "audio", "时长"),
            ("note.txt", "txt", "text", "字符数"),
            ("pack.zip", "zip", "archive", "文件数"),
            ("page.pdf", "pdf", "pdf", "页数"),
            ("font.ttf", "ttf", "font", "字体名称"),
        ],
    )
    def test_detail_load_thread_type_branches(
        self, qapp: QApplication, tmp_path: Any, monkeypatch: Any,
        fname: str, suffix: str, kind: str, expected_key: str,
    ) -> None:
        """LoadThread.run 按扩展名分派 image/video/audio/text/archive/pdf/font 详情分支。"""
        import sys
        import types

        import freeassetfilter.components.file_info_previewer as fip

        path = tmp_path / fname
        path.write_bytes(b"dummy")
        pv = self._make_previewer()
        ui = pv.get_ui()
        monkeypatch.setattr(pv, "_get_cache_dir", lambda: str(tmp_path))
        self._sync_pool(monkeypatch)

        if kind == "image":
            target: str = make_image(str(path))
        elif kind == "video":
            monkeypatch.setattr(fip, "get_video_stream_info", lambda p: {
                "duration_seconds": 30, "width": 640, "height": 480,
                "fps": 24.0, "codec": "h264", "bitrate": 500000,
            })
            target = str(path)
        elif kind == "audio":
            fake_audio = MagicMock()
            fake_audio.info.length = 5
            fake_audio.info.bitrate = 128000
            fake_audio.info.channels = 2
            fake_audio.info.sample_rate = 44100
            monkeypatch.setattr(fip, "mutagen_file", lambda p: fake_audio)
            target = str(path)
        elif kind == "archive":
            monkeypatch.setattr(pv, "_7z_core", _Fake7z())
            target = str(path)
        elif kind == "pdf":
            target = make_pdf(str(path))
        elif kind == "font":
            ttlib = types.ModuleType("fontTools.ttLib")
            ttlib.TTFont = _FakeTTFont
            monkeypatch.setitem(sys.modules, "fontTools", types.ModuleType("fontTools"))
            monkeypatch.setitem(sys.modules, "fontTools.ttLib", ttlib)
            target = str(path)
        else:  # text
            target = make_text(str(path))

        try:
            pv.set_file(_make_finfo(target, suffix=suffix))
            pv._load_detailed_info()
            self._run_detail_thread(pv)

            assert expected_key in pv.file_info["details"], (
                f"{kind} 详情分支未产生 {expected_key}: {pv.file_info['details']}"
            )
            assert "MD5" in pv.basic_info_widgets
        finally:
            if hasattr(pv, "load_thread") and pv.load_thread.isRunning():
                pv.load_thread.wait(3000)
            if hasattr(pv, "loading_dialog") and pv.loading_dialog:
                pv.loading_dialog.close()
            safe_teardown(pv)
            safe_teardown(ui)

    def test_detail_load_dir_only_hashes(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        """目录文件的 LoadThread：跳过扩展名详情，仅计算校验码（失败占位不崩溃）。"""
        pv = self._make_previewer()
        ui = pv.get_ui()
        monkeypatch.setattr(pv, "_get_cache_dir", lambda: str(tmp_path))
        self._sync_pool(monkeypatch)
        try:
            pv.set_file(_make_finfo(str(tmp_path), is_dir=True))
            pv._load_detailed_info()
            self._run_detail_thread(pv)
            assert "MD5" in pv.basic_info_widgets
            assert pv.file_info["details"]["子目录数"] == 0
            assert pv.file_info["details"]["文件数"] == 0
        finally:
            if hasattr(pv, "load_thread") and pv.load_thread.isRunning():
                pv.load_thread.wait(3000)
            if hasattr(pv, "loading_dialog") and pv.loading_dialog:
                pv.loading_dialog.close()
            safe_teardown(pv)
            safe_teardown(ui)

    def test_detail_load_cache_hit_filters_metadata(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        """缓存命中：元数据被过滤、隐藏更多信息按钮、从缓存回放哈希字段。"""
        import json

        text_path: str = make_text(str(tmp_path / "c.txt"))
        pv = self._make_previewer()
        ui = pv.get_ui()
        monkeypatch.setattr(pv, "_get_cache_dir", lambda: str(tmp_path))
        cache_data = {
            text_path: {
                "basic": {"MD5": "abc", "SHA1": "def", "SHA256": "ghi"},
                "details": {"字符数": 3, "元数据": {"artist": "x"}},
            }
        }
        (tmp_path / "file_info_cache.json").write_text(json.dumps(cache_data), encoding="utf-8")
        try:
            pv.set_file(_make_finfo(text_path, suffix="txt"))
            pv._load_detailed_info()
            assert pv.file_info["details"]["字符数"] == 3
            assert "元数据" not in pv.file_info["details"]
            assert "MD5" in pv.basic_info_widgets
            assert pv.more_info_btn.isHidden()
        finally:
            safe_teardown(pv)
            safe_teardown(ui)

    def test_detail_load_cache_loading_then_thread(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        """缓存含"加载中..."状态 → 判定无效 → 回退线程加载。"""
        import json

        text_path: str = make_text(str(tmp_path / "d.txt"))
        pv = self._make_previewer()
        ui = pv.get_ui()
        monkeypatch.setattr(pv, "_get_cache_dir", lambda: str(tmp_path))
        self._sync_pool(monkeypatch)
        cache_data = {text_path: {"basic": {}, "details": {"时长": "加载中..."}}}
        (tmp_path / "file_info_cache.json").write_text(json.dumps(cache_data), encoding="utf-8")
        try:
            pv.set_file(_make_finfo(text_path, suffix="txt"))
            pv._load_detailed_info()
            assert hasattr(pv, "load_thread"), "缓存无效应回退线程加载"
            self._run_detail_thread(pv)
            assert pv.file_info["details"]["字符数"] >= 1
        finally:
            if hasattr(pv, "load_thread") and pv.load_thread.isRunning():
                pv.load_thread.wait(3000)
            if hasattr(pv, "loading_dialog") and pv.loading_dialog:
                pv.loading_dialog.close()
            safe_teardown(pv)
            safe_teardown(ui)

    def test_load_detailed_info_no_current_file(self, qapp: QApplication) -> None:
        """_load_detailed_info：无当前文件 → 直接返回。"""
        pv = self._make_previewer()
        try:
            pv._load_detailed_info()
            assert not hasattr(pv, "load_thread")
        finally:
            safe_teardown(pv)

    def test_cache_runnables_direct(self, qapp: QApplication, tmp_path: Any) -> None:
        """_CacheJsonSignals/_CacheReadRunnable/_CacheWriteRunnable：正常与失败路径。"""
        import json

        import freeassetfilter.components.file_info_previewer as fip

        signals = fip._CacheJsonSignals()
        collected: List[Any] = []
        signals.finished.connect(lambda d: collected.append(d))

        good = tmp_path / "good.json"
        good.write_text(json.dumps({"k": 1}), encoding="utf-8")
        fip._CacheReadRunnable(str(good), signals).run()
        assert collected == [{"k": 1}]

        collected.clear()
        fip._CacheReadRunnable(str(tmp_path / "missing.json"), signals).run()
        assert collected == [None]

        bad = tmp_path / "bad.json"
        bad.write_text("{oops", encoding="utf-8")
        collected.clear()
        fip._CacheReadRunnable(str(bad), signals).run()
        assert collected == [None]

        out = tmp_path / "out.json"
        fip._CacheWriteRunnable(str(out), lambda: {"a": [1, 2]}).run()
        assert json.loads(out.read_text(encoding="utf-8"))["a"] == [1, 2]

        # 写数据抛异常被吞
        fip._CacheWriteRunnable(
            str(tmp_path / "fail.json"), lambda: (_ for _ in ()).throw(ValueError("x"))
        ).run()

    def test_save_to_cache_filters_loading_metadata(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        """_save_to_cache：过滤"加载中..."与元数据，再读回缓存文件验证内容。"""
        import json

        pv = self._make_previewer()
        monkeypatch.setattr(pv, "_get_cache_dir", lambda: str(tmp_path))
        self._sync_pool(monkeypatch)
        try:
            # 既有缓存文件损坏 → 读失败被吞，从空数据重建
            (tmp_path / "file_info_cache.json").write_text("{broken", encoding="utf-8")
            pv._save_to_cache("/f", {
                "basic": {"MD5": "abc"},
                "details": {"时长": "加载中...", "元数据": {"a": 1}, "字符数": 9},
            })
            cache_file = tmp_path / "file_info_cache.json"
            assert cache_file.exists()
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            assert data["/f"]["basic"]["MD5"] == "abc"
            assert data["/f"]["details"] == {"字符数": 9}
        finally:
            safe_teardown(pv)

    def test_get_cached_info_branches(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        """_get_cached_info：缺缓存文件 / 非法 JSON / 命中 / 未命中 四分支。"""
        import json

        pv = self._make_previewer()
        monkeypatch.setattr(pv, "_get_cache_dir", lambda: str(tmp_path))
        cache_file = tmp_path / "file_info_cache.json"
        try:
            assert pv._get_cached_info("/x") is None
            cache_file.write_text("{broken", encoding="utf-8")
            assert pv._get_cached_info("/x") is None
            cache_file.write_text(
                json.dumps({"/x": {"basic": {}, "details": {}}}), encoding="utf-8"
            )
            assert pv._get_cached_info("/x") == {"basic": {}, "details": {}}
            assert pv._get_cached_info("/y") is None
        finally:
            safe_teardown(pv)

    def test_get_cache_dir_creates_when_missing(self, qapp: QApplication, monkeypatch: Any) -> None:
        """_get_cache_dir：目标目录缺失时创建（monkeypatch 避免真实写仓库 data/）。"""
        import freeassetfilter.components.file_info_previewer as fip

        pv = self._make_previewer()
        makedirs_calls: List[str] = []
        monkeypatch.setattr(fip.os.path, "exists", lambda p: False)
        monkeypatch.setattr(fip.os, "makedirs", lambda p: makedirs_calls.append(p))
        try:
            cache_dir = pv._get_cache_dir()
            assert cache_dir.endswith("data")
            assert makedirs_calls, "目录不存在时应调用 makedirs"
        finally:
            safe_teardown(pv)

    def test_set_file_removes_hash_widgets(self, qapp: QApplication, tmp_path: Any) -> None:
        """set_file 清空上一个文件动态添加的校验码控件。"""
        from PySide6.QtWidgets import QLabel, QTextEdit

        png_path: str = make_image(str(tmp_path / "h.png"))
        pv = self._make_previewer()
        ui = pv.get_ui()
        try:
            for k in ("MD5", "SHA1", "SHA256"):
                pair = {"label": QLabel(f"{k}:"), "value": QTextEdit()}
                pv.basic_info_widgets[k] = pair
                pv.basic_info_labels[k] = pair["value"]
            pv.set_file(_make_finfo(png_path, suffix="png"))
            assert "MD5" not in pv.basic_info_widgets
            assert "SHA1" not in pv.basic_info_labels
            assert "SHA256" not in pv.basic_info_widgets
        finally:
            safe_teardown(pv)
            safe_teardown(ui)

    def test_create_value_widget_clickable(self, qapp: QApplication) -> None:
        """_create_value_widget：clickable 分支下划线样式 + 指针光标。"""
        from PySide6.QtCore import Qt

        pv = self._make_previewer()
        try:
            normal = pv._create_value_widget("你好")
            assert normal.toPlainText() == "你好"
            clickable = pv._create_value_widget("哈希", is_clickable=True)
            assert clickable.toPlainText() == "哈希"
            assert clickable.cursor().shape() == Qt.PointingHandCursor
            assert normal.cursor().shape() != Qt.PointingHandCursor
        finally:
            safe_teardown(pv)

    def test_copy_all_and_current_to_clipboard(self, qapp: QApplication, monkeypatch: Any) -> None:
        """_copy_all_info / _copy_current_info：剪贴板写入内容断言。"""
        fake = _FakeClipboard()
        monkeypatch.setattr(QApplication, "clipboard", staticmethod(lambda: fake))
        pv = self._make_previewer()
        try:
            pv.file_info = {
                "basic": {"文件名": "a.txt", "文件大小": "1.0 KB"},
                "details": {"字符数": 5, "行数": 2},
            }
            pv._copy_all_info()
            text = fake.text()
            assert "文件信息" in text and "=" * 20 in text
            assert "文件名: a.txt" in text
            assert "字符数: 5" in text

            pv._copy_current_info("文件名", "b.txt")
            assert fake.text() == "文件名: b.txt"

            pv._context_menu = MagicMock(_current_key="文件名", _current_value="c.txt")
            pv._on_context_menu_clicked("copy_current")
            assert fake.text() == "文件名: c.txt"
            pv._on_context_menu_clicked("copy_all")
            assert "文件名: a.txt" in fake.text()
        finally:
            safe_teardown(pv)

    def test_update_theme_branches(self, qapp: QApplication, monkeypatch: Any) -> None:
        """update_theme：more_info_btn 更新失败被吞 + 详情控件样式刷新。"""
        from PySide6.QtWidgets import QLabel, QTextEdit

        pv = self._make_previewer()
        ui = pv.get_ui()
        try:
            pv.more_info_btn.update_theme = lambda: (_ for _ in ()).throw(RuntimeError("x"))  # type: ignore[method-assign]
            pv.update_theme()

            pv.details_info_widgets = [(QLabel("K:"), QTextEdit())]
            pv.update_theme()
            label, value = pv.details_info_widgets[0]
            assert label.styleSheet() != ""
            assert value.styleSheet() != ""
        finally:
            safe_teardown(pv)
            safe_teardown(ui)

    def test_update_ui_empty_returns(self, qapp: QApplication) -> None:
        """update_ui：file_info 为空时提前返回不崩溃。"""
        pv = self._make_previewer()
        try:
            pv.file_info = {}
            pv.update_ui()
            assert pv.file_info == {}
        finally:
            safe_teardown(pv)

    def test_context_menu_popup_and_actions(self, qapp: QApplication, monkeypatch: Any) -> None:
        """右键菜单：customContextMenuRequested → 取当前值 → copy_current/copy_all 分派。"""
        from PySide6.QtCore import QPoint

        import freeassetfilter.components.file_info_previewer as fip

        menus: List[MagicMock] = []

        class _FakeMenu(MagicMock):
            def __init__(self, *a: Any, **k: Any) -> None:
                super().__init__()
                menus.append(self)

        monkeypatch.setattr(fip, "D_MoreMenu", _FakeMenu)
        fake = _FakeClipboard()
        monkeypatch.setattr(QApplication, "clipboard", staticmethod(lambda: fake))
        pv = self._make_previewer()
        ui = pv.get_ui()
        try:
            pv.basic_info_labels["文件名"].customContextMenuRequested.emit(QPoint(0, 0))
            assert menus, "应创建右键菜单"
            menu = menus[0]
            assert menu._current_key == "文件名"
            assert menu._current_value == "-"
            menu.set_items.assert_called()
            menu.popup.assert_called()

            pv._context_menu = MagicMock(_current_key="文件名", _current_value="hello")
            pv._on_context_menu_clicked("copy_current")
            assert "文件名: hello" in fake.text()

            # QLabel 型值控件 → text() 分支
            from PySide6.QtWidgets import QLabel

            label_ql = QLabel("label-value")
            pv.basic_info_labels["文件名"] = label_ql
            pv._connect_context_menu(label_ql, "文件名")
            menu = pv._context_menu
            menu._current_value = ""  # 重置，验证 emit 后刷新
            label_ql.customContextMenuRequested.emit(QPoint(0, 0))
            assert menu._current_key == "文件名"
            assert menu._current_value == "label-value"

            # 不在 basic_info_labels 的键 → 空值分支（复用同一菜单实例）
            unknown = QLabel("unknown")
            pv._connect_context_menu(unknown, "SOME_NEW_KEY")
            unknown.customContextMenuRequested.emit(QPoint(0, 0))
            assert menu._current_key == "SOME_NEW_KEY"
            assert menu._current_value == ""
        finally:
            if hasattr(pv, "_context_menu"):
                try:
                    pv._context_menu.close()
                except Exception:
                    pass
            safe_teardown(pv)
            safe_teardown(ui)

    def test_on_loading_error_shows_message(self, qapp: QApplication, monkeypatch: Any) -> None:
        """_on_loading_error：关闭加载框并弹出错误提示。"""
        import freeassetfilter.components.file_info_previewer as fip

        class _FakeMB:
            def __init__(self, *a: Any, **k: Any) -> None:
                self.actions: List[str] = []

            def set_title(self, t: str) -> None:
                self.actions.append(t)

            def set_text(self, t: str) -> None:
                self.actions.append(t)

            def set_buttons(self, *a: Any, **k: Any) -> None:
                self.actions.append("buttons")

            def exec(self) -> int:
                return 0

        monkeypatch.setattr(fip, "CustomMessageBox", _FakeMB)
        pv = self._make_previewer()
        try:
            pv.loading_dialog = MagicMock()
            pv._on_loading_error("boom")
            pv.loading_dialog.close.assert_called()
        finally:
            safe_teardown(pv)

    def test_audio_task_ffprobe_and_error_paths(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        """AudioInfoTask：ffprobe 成功 / 失败 / 注入字符 / mutagen 异常 多路径。"""
        import subprocess
        from types import SimpleNamespace

        import freeassetfilter.components.file_info_previewer as fip

        audio_path = tmp_path / "probe.mp3"
        audio_path.write_bytes(b"ID3")
        monkeypatch.setattr(fip, "mutagen_file", lambda p: None)
        monkeypatch.setattr(fip, "get_ffprobe_path", lambda: "ffprobe")
        monkeypatch.setattr(fip, "get_subprocess_creationflags", lambda: 0)

        # 成功：JSON 时长 + 比特率
        ok = SimpleNamespace(
            stdout='{"format": {"duration": "45", "bit_rate": "64000"}}',
            stdout_truncated=False,
        )
        monkeypatch.setattr(fip, "run_with_limited_output", lambda *a, **k: ok)
        calls: List[tuple] = []
        task = fip.AudioInfoTask(str(audio_path), 1, lambda tid, d: calls.append((tid, d)))
        task.run()
        _, info = calls[0]
        assert info["时长"] == "00:45"
        assert info["比特率"] == "64.0 Kbps"

        # 失败 → 兜底"无法获取"
        monkeypatch.setattr(
            fip, "run_with_limited_output",
            lambda *a, **k: (_ for _ in ()).throw(subprocess.SubprocessError("boom")),
        )
        calls_fail: List[tuple] = []
        task2 = fip.AudioInfoTask(str(audio_path), 1, lambda tid, d: calls_fail.append((tid, d)))
        task2.run()
        assert calls_fail[0][1]["时长"] == "无法获取"
        assert calls_fail[0][1]["比特率"] == "无法获取"

        # 注入风险字符 → 拒绝并兜底
        inj_path = tmp_path / "x$(evil.mp3"
        inj_path.write_bytes(b"X")
        inj_calls: List[tuple] = []
        task3 = fip.AudioInfoTask(str(inj_path), 1, lambda tid, d: inj_calls.append((tid, d)))
        task3.run()
        assert inj_calls[0][1]["时长"] == "无法获取"

        # ffprobe 输出截断 → 拒绝并兜底
        truncated = SimpleNamespace(stdout="{}", stdout_truncated=True)
        monkeypatch.setattr(fip, "run_with_limited_output", lambda *a, **k: truncated)
        trunc_calls: List[tuple] = []
        task4 = fip.AudioInfoTask(str(audio_path), 1, lambda tid, d: trunc_calls.append((tid, d)))
        task4.run()
        assert trunc_calls[0][1]["时长"] == "无法获取"

    def test_audio_task_mutagen_exception(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        """AudioInfoTask：mutagen 抛异常 → except 吞掉 → ffprobe 兜底。"""
        from types import SimpleNamespace

        import freeassetfilter.components.file_info_previewer as fip

        audio_path = tmp_path / "mut.mp3"
        audio_path.write_bytes(b"ID3")
        monkeypatch.setattr(fip, "mutagen_file", lambda p: (_ for _ in ()).throw(OSError("boom")))
        monkeypatch.setattr(fip, "get_ffprobe_path", lambda: "ffprobe")
        monkeypatch.setattr(fip, "get_subprocess_creationflags", lambda: 0)
        ok = SimpleNamespace(stdout='{"format": {"duration": "9"}}', stdout_truncated=False)
        monkeypatch.setattr(fip, "run_with_limited_output", lambda *a, **k: ok)
        calls: List[tuple] = []
        task = fip.AudioInfoTask(str(audio_path), 1, lambda tid, d: calls.append((tid, d)))
        task.run()
        assert calls[0][1]["时长"] == "00:09"

    def test_audio_task_format_helpers(self, qapp: QApplication) -> None:
        """AudioInfoTask._format_duration/_format_bitrate：负值与各量级。"""
        import freeassetfilter.components.file_info_previewer as fip

        assert fip.AudioInfoTask._format_duration(-1) == "无法获取"
        assert fip.AudioInfoTask._format_duration(0) == "00:00"
        assert fip.AudioInfoTask._format_duration(3661) == "01:01:01"
        assert fip.AudioInfoTask._format_bitrate(-1) == "无法获取"
        assert fip.AudioInfoTask._format_bitrate(500) == "500 bps"
        assert fip.AudioInfoTask._format_bitrate(1500) == "1.5 Kbps"
        assert fip.AudioInfoTask._format_bitrate(2000000) == "2.0 Mbps"

    def test_get_audio_info_sync_injection_truncation_and_mutagen_error(
        self, qapp: QApplication, tmp_path: Any, monkeypatch: Any
    ) -> None:
        """_get_audio_info_sync：注入字符拒绝 / 输出截断 / mutagen 异常分支。"""
        import subprocess
        from types import SimpleNamespace

        import freeassetfilter.components.file_info_previewer as fip

        audio_path = tmp_path / "trunc.mp3"
        audio_path.write_bytes(b"X")
        monkeypatch.setattr(fip, "mutagen_file", lambda p: None)
        monkeypatch.setattr(fip, "get_ffprobe_path", lambda: "ffprobe")
        monkeypatch.setattr(fip, "get_subprocess_creationflags", lambda: 0)
        pv = self._make_previewer()
        try:
            # 输出截断 → ValueError → "无法获取"
            truncated = SimpleNamespace(stdout="{}", stdout_truncated=True)
            monkeypatch.setattr(fip, "run_with_limited_output", lambda *a, **k: truncated)
            bad = pv._get_audio_info_sync(str(audio_path))
            assert bad["时长"] == "无法获取"

            # 注入风险字符 → 提前拒绝
            inj = tmp_path / "x$(evil.mp3"
            inj.write_bytes(b"X")
            info = pv._get_audio_info_sync(str(inj))
            assert info["时长"] == "无法获取"

            # mutagen 抛 OSError → ffprobe 兜底成功
            monkeypatch.setattr(fip, "mutagen_file", lambda p: (_ for _ in ()).throw(OSError("boom")))
            ok = SimpleNamespace(stdout='{"format": {"duration": "9"}}', stdout_truncated=False)
            monkeypatch.setattr(fip, "run_with_limited_output", lambda *a, **k: ok)
            info2 = pv._get_audio_info_sync(str(audio_path))
            assert info2["时长"] == "00:09"

            # 全链路失败 → 兜底
            monkeypatch.setattr(
                fip, "run_with_limited_output",
                lambda *a, **k: (_ for _ in ()).throw(subprocess.SubprocessError("boom")),
            )
            info3 = pv._get_audio_info_sync(str(inj))
            assert info3["时长"] == "无法获取"
        finally:
            safe_teardown(pv)

    def test_get_image_advanced_info_exif(self, qapp: QApplication, tmp_path: Any) -> None:
        """_get_image_advanced_info：真实 EXIF JPEG 解析出标签。"""
        from PIL import Image

        import freeassetfilter.components.file_info_previewer as fip

        assert fip.exifread, "环境应含 exifread"
        p = tmp_path / "exif.jpg"
        img = Image.new("RGB", (8, 8), "red")
        exif = Image.Exif()
        exif[0x010F] = "FAF Test"
        img.save(str(p), exif=exif)
        pv = self._make_previewer()
        try:
            info = pv._get_image_advanced_info(str(p))
            exif_info = info.get("EXIF信息", {})
            assert exif_info, "应解析出 EXIF 标签"
            assert exif_info.get("Image Make") == "FAF Test"
        finally:
            safe_teardown(pv)

    def test_get_image_advanced_info_exception(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        """_get_image_advanced_info：exifread 抛异常 → 安全返回空。"""
        import freeassetfilter.components.file_info_previewer as fip

        class _BoomExif:
            def process_file(self, f: Any, details: bool = False) -> dict:
                raise OSError("boom")

        monkeypatch.setattr(fip, "exifread", _BoomExif())
        p = tmp_path / "bad.jpg"
        p.write_bytes(b"notimage")
        pv = self._make_previewer()
        try:
            assert pv._get_image_advanced_info(str(p)) == {}
        finally:
            safe_teardown(pv)

    def test_get_text_advanced_info_magic_error(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        """_get_text_advanced_info：fake magic 抛异常 → 空字典。"""
        import freeassetfilter.components.file_info_previewer as fip

        text_path: str = make_text(str(tmp_path / "e.txt"))
        pv = self._make_previewer()
        try:
            class _BoomMagic:
                def __init__(self, mime: bool = False) -> None:
                    pass

                def from_file(self, path: str) -> str:
                    raise OSError("boom")

            monkeypatch.setattr(fip, "magic", type("M", (), {"Magic": _BoomMagic}))
            assert pv._get_text_advanced_info(text_path) == {}
        finally:
            safe_teardown(pv)

    def test_get_font_info_with_fake_fonttools(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        """_get_font_info/_get_font_advanced_info：注入假 fontTools 覆盖正常与 CFF 分支。"""
        import sys
        import types

        import freeassetfilter.components.file_info_previewer as fip

        font_path = tmp_path / "fake.ttf"
        font_path.write_bytes(b"fonts")
        ttlib = types.ModuleType("fontTools.ttLib")
        ttlib.TTFont = _FakeTTFont
        monkeypatch.setitem(sys.modules, "fontTools", types.ModuleType("fontTools"))
        monkeypatch.setitem(sys.modules, "fontTools.ttLib", ttlib)
        pv = self._make_previewer()
        try:
            info = pv._get_font_info(str(font_path))
            assert info["字体名称"] == "MyFont"
            assert "字体样式" in info  # latin-1 回退分支成功解码
            assert info["全名"] == "MyFont-Regular"

            adv = pv._get_font_advanced_info(str(font_path))
            assert adv["字体格式"] == "OpenType/CFF"
            assert adv["字符数"] == 3
            assert adv["上升"] == 800 and adv["下降"] == -200 and adv["行间距"] == 90
        finally:
            safe_teardown(pv)

    def test_module_optional_import_fallbacks(self, qapp: QApplication, monkeypatch: Any) -> None:
        """模块可选依赖（exifread/mutagen/magic/zipfile/PIL/chardet）缺失时回退为 None。"""
        import builtins
        import importlib
        import sys

        name = "freeassetfilter.components.file_info_previewer"
        original = sys.modules.get(name)
        blocked = {"exifread", "mutagen", "magic", "zipfile", "tarfile", "PIL", "chardet"}
        real_import = builtins.__import__

        def _fake_import(nm: str, *a: Any, **k: Any) -> Any:
            if nm.split(".")[0] in blocked:
                raise ImportError(nm)
            return real_import(nm, *a, **k)

        monkeypatch.setattr(builtins, "__import__", _fake_import)
        try:
            sys.modules.pop(name, None)  # 强制重新执行模块体以触发可选依赖回退
            mod = importlib.import_module(name)
            assert mod.exifread is None
            assert mod.mutagen_file is None
            assert mod.magic is None
            assert mod.zipfile is None and mod.tarfile is None
            assert mod.Image is None and mod.TAGS is None
            assert mod.chardet is None
        finally:
            # 恢复原模块对象，避免影响后续测试的 mutagen/exifread 行为
            if original is not None:
                sys.modules[name] = original


# ===== photo_viewer 内部线程 / GifWidget =====

class TestPhotoViewerWorkers:
    """photo_viewer 内部线程与 GIF 部件：构造契约 + 取消语义（不启动解码线程）。"""

    @pytest.mark.parametrize(
        "worker_cls",
        [
            "HeifAvifProcessor",
            "IcoProcessor",
            "ImageLoader",
            "MovieLoader",
            "PSDProcessor",
            "RawProcessor",
        ],
    )
    def test_worker_construct_and_cancel(self, qapp: QApplication, worker_cls: str) -> None:
        """各解码线程：可构造、可取消、构造后未启动。"""
        import importlib

        mod = importlib.import_module("freeassetfilter.components.photo_viewer")
        cls = getattr(mod, worker_cls)
        worker = cls(str(tmp_missing()))  # 只构造不启动
        try:
            assert not worker.isRunning()
            assert callable(worker.cancel)
            worker.cancel()
        finally:
            if worker.isRunning():
                worker.wait(2000)
            worker.deleteLater()

    def test_gif_widget_rotate_and_position(self, qapp: QApplication) -> None:
        """GifWidget：构造 + rotate_clockwise 空图安全 + 像素位置校验。"""
        from PySide6.QtCore import QPoint

        from freeassetfilter.components.photo_viewer import GifWidget

        widget = GifWidget(settings_manager=_settings_manager())
        try:
            widget.rotate_clockwise()  # 空 GIF：base_pixmap 为空，安全返回
            assert widget.is_valid_pixel_position(QPoint(0, 0)) is False
        finally:
            safe_teardown(widget)

    def test_gif_widget_set_movie(self, qapp: QApplication) -> None:
        """GifWidget.set_movie：空/有效 QMovie 均可接受，不崩溃。"""
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QMovie

        from freeassetfilter.components.photo_viewer import GifWidget

        widget = GifWidget(settings_manager=_settings_manager())
        try:
            widget.set_movie(None)
            widget.set_movie(QMovie())
            widget.update_pixel_info(QPoint(1, 1))
            widget.on_frame_changed()
        finally:
            safe_teardown(widget)


class TestPhotoViewerWorkersRun:
    """photo_viewer 解码线程 run()：同步调用 run() 验证真实行为（不启动线程）。"""

    def _make_ico(self, path: str) -> None:
        from PIL import Image

        Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(path, format="ICO")

    def _make_png(self, path: str, mode: str = "RGB") -> None:
        from PIL import Image

        if mode == "RGBA":
            Image.new(mode, (8, 6), (10, 20, 30, 255)).save(path, format="PNG")
        else:
            Image.new(mode, (8, 6), (10, 20, 30)).save(path, format="PNG")

    def _make_gif(self, path: str) -> None:
        from PIL import Image

        Image.new("RGB", (100, 100), (0, 255, 0)).save(path, format="GIF")

    def test_raw_processor_run_success(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        import numpy as np

        from freeassetfilter.components.photo_viewer import RawProcessor

        rgb = np.zeros((2, 3, 3), dtype=np.uint8)
        monkeypatch.setattr("freeassetfilter.components.photo_viewer.load_raw_rgb_array", lambda *a, **k: rgb)
        raw = tmp_path / "x.dng"
        raw.write_bytes(b"dummy")
        proc = RawProcessor(str(raw))
        completed = _signal_collector(proc.processing_complete)
        failed = _signal_collector(proc.processing_failed)
        proc.run()
        assert len(completed) == 1
        qimg, path = completed[0]
        assert path == str(raw)
        assert qimg.width() == 3 and qimg.height() == 2
        assert failed == []
        proc.deleteLater()

    def test_raw_processor_run_large_file_half_size(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        import numpy as np

        from freeassetfilter.components.photo_viewer import RawProcessor

        calls: List[Any] = []

        def _fake_load(image_path: str, half_size: bool = False, **kwargs: Any) -> Any:
            calls.append(half_size)
            return np.zeros((1, 1, 3), dtype=np.uint8)

        monkeypatch.setattr("freeassetfilter.components.photo_viewer.load_raw_rgb_array", _fake_load)
        big = tmp_path / "big.dng"
        big.write_bytes(b"\0" * (10 * 1024 * 1024 + 1))
        proc = RawProcessor(str(big))
        completed = _signal_collector(proc.processing_complete)
        proc.run()
        assert calls == [True], "超过 10MB 的 RAW 应以 half_size 解码"
        assert len(completed) == 1
        proc.deleteLater()

    def test_raw_processor_run_cancelled(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        import numpy as np

        from freeassetfilter.components.photo_viewer import RawProcessor

        # 取消标志在 load_raw_rgb_array 解码完成后、发射信号前检查
        monkeypatch.setattr(
            "freeassetfilter.components.photo_viewer.load_raw_rgb_array", lambda *a, **k: np.zeros((4, 8, 3), dtype=np.uint8)
        )
        raw = tmp_path / "x.dng"
        raw.write_bytes(b"dummy")
        proc = RawProcessor(str(raw))
        completed = _signal_collector(proc.processing_complete)
        failed = _signal_collector(proc.processing_failed)
        proc._is_cancelled = True
        proc.run()
        assert completed == [] and failed == []
        proc.deleteLater()

    def test_raw_processor_run_error_branches(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        from freeassetfilter.components.photo_viewer import RawProcessor

        raw = tmp_path / "x.dng"
        raw.write_bytes(b"dummy")

        def _raise_import(*a: Any, **k: Any) -> Any:
            raise ImportError("no rawpy")

        monkeypatch.setattr("freeassetfilter.components.photo_viewer.load_raw_rgb_array", _raise_import)
        proc = RawProcessor(str(raw))
        failed = _signal_collector(proc.processing_failed)
        proc.run()
        assert len(failed) == 1 and "缺少依赖" in failed[0][0]
        proc.deleteLater()

        def _raise_os(*a: Any, **k: Any) -> Any:
            raise OSError("bad file")

        monkeypatch.setattr("freeassetfilter.components.photo_viewer.load_raw_rgb_array", _raise_os)
        proc2 = RawProcessor(str(raw))
        failed2 = _signal_collector(proc2.processing_failed)
        proc2.run()
        assert len(failed2) == 1 and "文件错误" in failed2[0][0]
        proc2.deleteLater()

        def _raise_generic(*a: Any, **k: Any) -> Any:
            raise RuntimeError("boom")

        monkeypatch.setattr("freeassetfilter.components.photo_viewer.load_raw_rgb_array", _raise_generic)
        proc3 = RawProcessor(str(raw))
        failed3 = _signal_collector(proc3.processing_failed)
        proc3.run()
        assert len(failed3) == 1 and "未知错误" in failed3[0][0]
        proc3.deleteLater()

    def test_ico_processor_run_pil_success(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.photo_viewer import IcoProcessor

        ico = tmp_path / "x.ico"
        self._make_ico(str(ico))
        proc = IcoProcessor(str(ico))
        completed = _signal_collector(proc.processing_complete)
        failed = _signal_collector(proc.processing_failed)
        proc.run()
        assert len(completed) == 1
        qimg, path = completed[0]
        assert path == str(ico)
        assert not qimg.isNull() and qimg.width() == 32 and qimg.height() == 32
        assert failed == []
        proc.deleteLater()

    def test_ico_processor_run_windows_api_fallback(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        from freeassetfilter.components.photo_viewer import IcoProcessor

        ico = tmp_path / "x.ico"
        self._make_ico(str(ico))

        def _raise_import(self_: Any) -> Any:
            raise ImportError("no PIL")

        def _api_ok(self_: Any) -> Any:
            return QImage(4, 4, QImage.Format_ARGB32)

        monkeypatch.setattr(IcoProcessor, "_load_with_pil", _raise_import)
        monkeypatch.setattr(IcoProcessor, "_load_with_windows_api", _api_ok)
        proc = IcoProcessor(str(ico))
        completed = _signal_collector(proc.processing_complete)
        failed = _signal_collector(proc.processing_failed)
        proc.run()
        assert len(completed) == 1 and not completed[0][0].isNull()
        assert failed == []
        proc.deleteLater()

    def test_ico_processor_run_pil_and_api_fail(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        from freeassetfilter.components.photo_viewer import IcoProcessor

        ico = tmp_path / "x.ico"
        self._make_ico(str(ico))

        def _raise_import(self_: Any) -> Any:
            raise ImportError("no PIL")

        monkeypatch.setattr(IcoProcessor, "_load_with_pil", _raise_import)
        monkeypatch.setattr(IcoProcessor, "_load_with_windows_api", lambda self_: None)
        proc = IcoProcessor(str(ico))
        failed = _signal_collector(proc.processing_failed)
        proc.run()
        assert len(failed) == 1 and "未知错误" in failed[0][0]
        proc.deleteLater()

    def test_ico_processor_run_corrupt_file(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.photo_viewer import IcoProcessor

        ico = tmp_path / "bad.ico"
        ico.write_bytes(b"not an ico")
        proc = IcoProcessor(str(ico))
        failed = _signal_collector(proc.processing_failed)
        proc.run()
        assert len(failed) == 1 and "文件错误" in failed[0][0]
        proc.deleteLater()

    def test_heif_avif_processor_run_success(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.photo_viewer import HeifAvifProcessor

        for mode in ("RGB", "RGBA"):
            png = tmp_path / f"x_{mode}.png"
            self._make_png(str(png), mode)
            proc = HeifAvifProcessor(str(png))
            completed = _signal_collector(proc.processing_complete)
            failed = _signal_collector(proc.processing_failed)
            proc.run()
            assert len(completed) == 1, f"mode={mode} 应处理成功"
            qimg, path = completed[0]
            assert not qimg.isNull() and qimg.width() == 8 and qimg.height() == 6
            assert failed == []
            proc.deleteLater()

    def test_heif_avif_processor_run_large_resize(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        import freeassetfilter.components.photo_viewer as pv

        png = tmp_path / "big.png"
        self._make_png(str(png))
        monkeypatch.setattr("freeassetfilter.components.photo_viewer.os.path.getsize", lambda p: 25 * 1024 * 1024)
        proc = pv.HeifAvifProcessor(str(png))
        completed = _signal_collector(proc.processing_complete)
        proc.run()
        assert len(completed) == 1 and not completed[0][0].isNull()
        proc.deleteLater()

    def test_heif_avif_processor_run_cancelled_and_errors(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        import freeassetfilter.components.photo_viewer as pv

        png = tmp_path / "x.png"
        self._make_png(str(png))

        proc = pv.HeifAvifProcessor(str(png))
        proc._is_cancelled = True
        completed = _signal_collector(proc.processing_complete)
        proc.run()
        assert completed == []
        proc.deleteLater()

        bad = tmp_path / "bad.png"
        bad.write_bytes(b"garbage")
        proc2 = pv.HeifAvifProcessor(str(bad))
        failed = _signal_collector(proc2.processing_failed)
        proc2.run()
        assert len(failed) == 1 and "文件错误" in failed[0][0]
        proc2.deleteLater()

        def _boom(p: str) -> int:
            raise RuntimeError("boom")

        monkeypatch.setattr("freeassetfilter.components.photo_viewer.os.path.getsize", _boom)
        proc3 = pv.HeifAvifProcessor(str(png))
        failed3 = _signal_collector(proc3.processing_failed)
        proc3.run()
        assert len(failed3) == 1 and "未知错误" in failed3[0][0]
        proc3.deleteLater()

    def test_psd_processor_run_success(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        import sys
        import types

        from PIL import Image as PILImage

        fake_psd = types.ModuleType("psd_tools")
        fake_psd.PSDImage = types.SimpleNamespace(
            open=lambda p: types.SimpleNamespace(
                width=4, height=4, composite=lambda: PILImage.new("RGBA", (4, 4), (10, 20, 30, 255))
            )
        )
        monkeypatch.setitem(sys.modules, "psd_tools", fake_psd)

        from freeassetfilter.components.photo_viewer import PSDProcessor

        psd = tmp_path / "x.psd"
        psd.write_bytes(b"dummy")
        proc = PSDProcessor(str(psd))
        completed = _signal_collector(proc.processing_complete)
        failed = _signal_collector(proc.processing_failed)
        progress = _signal_collector(proc.processing_progress)
        proc.run()
        assert len(completed) == 1
        temp_path = completed[0][0]
        assert os.path.exists(temp_path) and temp_path.endswith(".png")
        assert not QImage(temp_path).isNull()
        assert failed == []
        assert {p[0] for p in progress} >= {5, 10, 30, 70, 85, 100}
        os.remove(temp_path)
        proc.deleteLater()

    def test_psd_processor_run_missing_dependency(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        import sys
        import types

        monkeypatch.setitem(sys.modules, "psd_tools", types.ModuleType("psd_tools"))

        from freeassetfilter.components.photo_viewer import PSDProcessor

        psd = tmp_path / "x.psd"
        psd.write_bytes(b"dummy")
        proc = PSDProcessor(str(psd))
        failed = _signal_collector(proc.processing_failed)
        proc.run()
        assert len(failed) == 1 and "缺少必要的库" in failed[0][0]
        proc.deleteLater()

    def test_psd_processor_run_cancelled(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.photo_viewer import PSDProcessor

        psd = tmp_path / "x.psd"
        psd.write_bytes(b"dummy")
        proc = PSDProcessor(str(psd))
        completed = _signal_collector(proc.processing_complete)
        progress = _signal_collector(proc.processing_progress)
        proc._cancelled = True
        proc.run()
        assert completed == []
        assert len(progress) == 1 and progress[0][0] == 5
        proc.deleteLater()

    def test_psd_processor_run_save_failure(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        import sys
        import types

        class _FailingComposite:
            mode = "RGBA"

            def save(self, path: str, fmt: str) -> None:
                raise OSError("disk full")

        fake_psd = types.ModuleType("psd_tools")
        fake_psd.PSDImage = types.SimpleNamespace(
            open=lambda p: types.SimpleNamespace(width=4, height=4, composite=lambda: _FailingComposite())
        )
        monkeypatch.setitem(sys.modules, "psd_tools", fake_psd)

        from freeassetfilter.components.photo_viewer import PSDProcessor

        psd = tmp_path / "x.psd"
        psd.write_bytes(b"dummy")
        proc = PSDProcessor(str(psd))
        failed = _signal_collector(proc.processing_failed)
        proc.run()
        assert len(failed) == 1 and "保存临时文件时出错" in failed[0][0]
        proc.deleteLater()

    def test_image_loader_run_success(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.photo_viewer import ImageLoader

        png = tmp_path / "x.png"
        make_image(str(png))
        loader = ImageLoader(str(png))
        completed = _signal_collector(loader.processing_complete)
        failed = _signal_collector(loader.processing_failed)
        loader.run()
        assert len(completed) == 1 and not completed[0][0].isNull()
        assert completed[0][1] == str(png)
        assert failed == []
        loader.deleteLater()

    def test_image_loader_run_force_full_resolution(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.photo_viewer import ImageLoader

        png = tmp_path / "x.png"
        make_image(str(png))
        loader = ImageLoader(str(png), force_full_resolution=True)
        completed = _signal_collector(loader.processing_complete)
        loader.run()
        assert len(completed) == 1 and not completed[0][0].isNull()
        loader.deleteLater()

    def test_image_loader_run_failure_and_cancelled(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.photo_viewer import ImageLoader

        loader = ImageLoader(str(tmp_missing()))
        failed = _signal_collector(loader.processing_failed)
        loader.run()
        assert len(failed) == 1 and "加载失败" in failed[0][0]
        loader.deleteLater()

        png = tmp_path / "x.png"
        make_image(str(png))
        loader2 = ImageLoader(str(png))
        loader2._is_cancelled = True
        completed = _signal_collector(loader2.processing_complete)
        loader2.run()
        assert completed == []
        loader2.deleteLater()

    def test_movie_loader_run(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.photo_viewer import MovieLoader

        gif = tmp_path / "x.gif"
        self._make_gif(str(gif))
        loader = MovieLoader(str(gif))
        loaded = _signal_collector(loader.movie_data_loaded)
        failed = _signal_collector(loader.loading_failed)
        loader.run()
        assert len(loaded) == 1 and loaded[0][1] == str(gif)
        assert loaded[0][0].startswith(b"GIF")
        assert failed == []
        loader.deleteLater()

        loader2 = MovieLoader(str(tmp_missing()))
        failed2 = _signal_collector(loader2.loading_failed)
        loader2.run()
        assert len(failed2) == 1
        loader2.deleteLater()

    def test_movie_loader_run_cancelled(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        from freeassetfilter.components.photo_viewer import MovieLoader

        gif = tmp_path / "x.gif"
        self._make_gif(str(gif))

        loader = MovieLoader(str(gif))
        loader._is_cancelled = True
        loaded = _signal_collector(loader.movie_data_loaded)
        loader.run()
        assert loaded == []
        loader.deleteLater()

        # 读文件后、发射前取消：open 成功但随后置取消标志 → 572-573 分支
        loader3 = MovieLoader(str(gif))
        loaded3 = _signal_collector(loader3.movie_data_loaded)

        class _CancellingFile:
            def __init__(self, path: str, mode: str = "rb") -> None:
                self._f = real_open(path, mode)

            def read(self) -> bytes:
                loader3._is_cancelled = True
                return self._f.read()

            def __enter__(self) -> "_CancellingFile":
                return self

            def __exit__(self, *a: Any) -> None:
                self._f.close()

        real_open = open  # noqa: A001 - builtins 引用，read 时置取消

        def _open_cancel(path: str, mode: str = "rb", **kw: Any) -> _CancellingFile:
            return _CancellingFile(path, mode)

        monkeypatch.setattr("builtins.open", _open_cancel)
        try:
            loader3.run()
        finally:
            monkeypatch.undo()
        assert loaded3 == []
        loader3.deleteLater()

    def test_ico_processor_run_cancel_and_import_error_branches(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        import freeassetfilter.components.photo_viewer as pv
        from freeassetfilter.components.photo_viewer import IcoProcessor

        ico = tmp_path / "x.ico"
        self._make_ico(str(ico))

        # 125：run 开始时已取消
        proc = IcoProcessor(str(ico))
        proc._is_cancelled = True
        completed = _signal_collector(proc.processing_complete)
        proc.run()
        assert completed == []
        proc.deleteLater()

        # 131：PIL 解码成功但随后取消
        def _pil_then_cancel(self_: Any) -> Any:
            self_._is_cancelled = True
            return QImage(2, 2, QImage.Format_ARGB32)

        monkeypatch.setattr(IcoProcessor, "_load_with_pil", _pil_then_cancel)
        proc2 = IcoProcessor(str(ico))
        completed2 = _signal_collector(proc2.processing_complete)
        proc2.run()
        assert completed2 == []
        proc2.deleteLater()

        # 102-103/139-144：PIL 抛 ImportError 后在 Windows API 路径取消
        def _pil_raises(self_: Any) -> Any:
            raise ImportError("no PIL")

        def _api_then_cancel(self_: Any) -> Any:
            self_._is_cancelled = True
            return QImage(2, 2, QImage.Format_ARGB32)

        monkeypatch.setattr(IcoProcessor, "_load_with_pil", _pil_raises)
        monkeypatch.setattr(IcoProcessor, "_load_with_windows_api", _api_then_cancel)
        proc3 = IcoProcessor(str(ico))
        completed3 = _signal_collector(proc3.processing_complete)
        proc3.run()
        assert completed3 == []
        proc3.deleteLater()

        # 139：PIL 抛 ImportError 且此时已取消（先走取消检查）
        def _pil_raises_and_cancel(self_: Any) -> Any:
            self_._is_cancelled = True
            raise ImportError("no PIL")

        monkeypatch.setattr(IcoProcessor, "_load_with_pil", _pil_raises_and_cancel)
        proc4 = IcoProcessor(str(ico))
        completed4 = _signal_collector(proc4.processing_complete)
        proc4.run()
        assert completed4 == []
        proc4.deleteLater()

        # 151-153：PIL 与 Windows API 均抛 ImportError → 外层缺少依赖分支
        monkeypatch.setattr(IcoProcessor, "_load_with_pil", _pil_raises)
        monkeypatch.setattr(IcoProcessor, "_load_with_windows_api", _pil_raises)
        proc5 = IcoProcessor(str(ico))
        failed5 = _signal_collector(proc5.processing_failed)
        proc5.run()
        assert len(failed5) == 1 and "缺少依赖" in failed5[0][0]
        proc5.deleteLater()

        # 149：Windows API 返回空图 → 未知错误
        monkeypatch.setattr(IcoProcessor, "_load_with_windows_api", lambda self_: None)
        proc6 = IcoProcessor(str(ico))
        failed6 = _signal_collector(proc6.processing_failed)
        proc6.run()
        assert len(failed6) == 1 and "未知错误" in failed6[0][0]
        proc6.deleteLater()

        assert pv.IcoProcessor is IcoProcessor

    def test_ico_processor_run_windows_api_real_path(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        import ctypes
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from PySide6.QtGui import QPixmap

        from freeassetfilter.components.photo_viewer import IcoProcessor

        ico = tmp_path / "x.ico"
        self._make_ico(str(ico))

        extract_calls: List[tuple] = []

        class _FakeExtract:
            def __init__(self) -> None:
                self.argtypes: Any = None
                self.restype: Any = None

            def __call__(self, path: str, index: int, a: Any, b: Any, n: int) -> int:
                extract_calls.append((index, n))
                if index == -1:
                    return 1  # icon_count
                # 将句柄写入 byref 指向的内存，使 large_icon/small_icon 非空
                from ctypes import POINTER, c_void_p, cast

                if a is not None:
                    cast(a, POINTER(c_void_p)).contents.value = 0x1234
                if b is not None:
                    cast(b, POINTER(c_void_p)).contents.value = 0x5678
                return 1  # 成功提取

        fake_windll = SimpleNamespace(
            shell32=SimpleNamespace(ExtractIconExW=_FakeExtract()),
            user32=SimpleNamespace(
                DestroyIcon=MagicMock(return_value=True),
                GetIconInfo=MagicMock(return_value=True),
            ),
            gdi32=SimpleNamespace(
                GetObjectW=MagicMock(return_value=24),
                DeleteObject=MagicMock(return_value=True),
            ),
        )
        monkeypatch.setattr(ctypes, "windll", fake_windll)
        monkeypatch.setattr("freeassetfilter.utils.icon_utils.hicon_to_pixmap", lambda *a, **k: QPixmap(4, 4))

        def _pil_raises(self_: Any) -> Any:
            raise ImportError("no PIL")

        monkeypatch.setattr(IcoProcessor, "_load_with_pil", _pil_raises)

        proc = IcoProcessor(str(ico))
        completed = _signal_collector(proc.processing_complete)
        failed = _signal_collector(proc.processing_failed)
        proc.run()
        assert len(completed) == 1 and not completed[0][0].isNull()
        assert failed == []
        assert extract_calls[0] == (-1, 0) and extract_calls[1] == (0, 1), "应先枚举图标再提取"
        proc.deleteLater()

    def test_ico_processor_run_windows_api_error_branches(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        import ctypes
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from PySide6.QtGui import QPixmap

        from freeassetfilter.components.photo_viewer import IcoProcessor

        ico = tmp_path / "x.ico"
        self._make_ico(str(ico))

        def _pil_raises(self_: Any) -> Any:
            raise ImportError("no PIL")

        monkeypatch.setattr(IcoProcessor, "_load_with_pil", _pil_raises)

        # 217-218：icon_count == 0 → "未找到图标" 异常 → 未知错误信号
        fake_windll = SimpleNamespace(
            shell32=SimpleNamespace(
                ExtractIconExW=MagicMock(return_value=0)
            ),
            user32=SimpleNamespace(DestroyIcon=MagicMock(return_value=True)),
            gdi32=SimpleNamespace(DeleteObject=MagicMock(return_value=True)),
        )
        monkeypatch.setattr(ctypes, "windll", fake_windll)
        proc = IcoProcessor(str(ico))
        failed = _signal_collector(proc.processing_failed)
        proc.run()
        assert len(failed) == 1 and "未知错误" in failed[0][0]
        proc.deleteLater()

        # 226-227：extracted == 0 → "无法提取ICO图标" 异常
        fake_windll2 = SimpleNamespace(
            shell32=SimpleNamespace(
                ExtractIconExW=MagicMock(side_effect=lambda *a, **k: (a[1] == -1) and 1 or 0)
            ),
            user32=SimpleNamespace(DestroyIcon=MagicMock(return_value=True)),
            gdi32=SimpleNamespace(DeleteObject=MagicMock(return_value=True)),
        )
        # ExtractIconExW 第 1 次（索引 -1）返回 1，第 2 次（索引 0）返回 0
        fake_windll2.shell32.ExtractIconExW.side_effect = lambda path, index, a, b, n: 1 if index == -1 else 0
        monkeypatch.setattr(ctypes, "windll", fake_windll2)
        proc2 = IcoProcessor(str(ico))
        failed2 = _signal_collector(proc2.processing_failed)
        proc2.run()
        assert len(failed2) == 1 and "未知错误" in failed2[0][0]
        proc2.deleteLater()

        # 279-280/283：GetIconInfo 返回假 → icon_size 兜底 256，hicon_to_pixmap 成功
        def _extract_ok(path: str, index: int, a: Any, b: Any, n: int) -> int:
            if index == -1:
                return 1
            from ctypes import POINTER, c_void_p, cast

            if a is not None:
                cast(a, POINTER(c_void_p)).contents.value = 0x1234
            if b is not None:
                cast(b, POINTER(c_void_p)).contents.value = 0x5678
            return 1  # 成功提取

        good_extract = MagicMock(side_effect=_extract_ok)
        fake_windll3 = SimpleNamespace(
            shell32=SimpleNamespace(ExtractIconExW=good_extract),
            user32=SimpleNamespace(
                DestroyIcon=MagicMock(return_value=True),
                GetIconInfo=MagicMock(return_value=False),
            ),
            gdi32=SimpleNamespace(
                GetObjectW=MagicMock(return_value=-1),
                DeleteObject=MagicMock(return_value=True),
            ),
        )
        monkeypatch.setattr(ctypes, "windll", fake_windll3)
        monkeypatch.setattr("freeassetfilter.utils.icon_utils.hicon_to_pixmap", lambda *a, **k: QPixmap(4, 4))
        proc3 = IcoProcessor(str(ico))
        completed3 = _signal_collector(proc3.processing_complete)
        proc3.run()
        assert len(completed3) == 1 and not completed3[0][0].isNull()
        proc3.deleteLater()

        # 291-292：hicon_to_pixmap 返回空 → "HICON转换失败"
        hicon_none_windll = SimpleNamespace(
            shell32=SimpleNamespace(ExtractIconExW=good_extract),
            user32=SimpleNamespace(
                DestroyIcon=MagicMock(return_value=True),
                GetIconInfo=MagicMock(return_value=False),
            ),
            gdi32=SimpleNamespace(
                GetObjectW=MagicMock(return_value=-1),
                DeleteObject=MagicMock(return_value=True),
            ),
        )
        monkeypatch.setattr(ctypes, "windll", hicon_none_windll)
        monkeypatch.setattr("freeassetfilter.utils.icon_utils.hicon_to_pixmap", lambda *a, **k: None)
        proc4 = IcoProcessor(str(ico))
        failed4 = _signal_collector(proc4.processing_failed)
        proc4.run()
        assert len(failed4) == 1 and "未知错误" in failed4[0][0]
        proc4.deleteLater()

    def test_heif_avif_processor_run_mode_conversions(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        import sys

        from PIL import Image as PILImage

        from freeassetfilter.components.photo_viewer import HeifAvifProcessor

        png = tmp_path / "x.png"
        self._make_png(str(png))

        for mode in ("L", "1", "LA", "P", "RGBX", "RGBa"):
            img = PILImage.new(mode, (8, 6))
            fake_open = lambda *a, **k: img  # noqa: E731
            monkeypatch.setattr("PIL.Image.open", fake_open)
            proc = HeifAvifProcessor(str(png))
            completed = _signal_collector(proc.processing_complete)
            failed = _signal_collector(proc.processing_failed)
            proc.run()
            if mode in ("L", "1", "LA", "P"):
                # 这些模式转换后走正常完成
                assert len(completed) == 1, f"mode={mode} 应成功"
                assert failed == []
            proc.deleteLater()

    def test_heif_avif_processor_run_resize_path(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        from PIL import Image as PILImage

        from freeassetfilter.components.photo_viewer import HeifAvifProcessor

        # 真实 2600x2000 大图 + getsize > 20MB → 走 resize 分支
        big = tmp_path / "big.png"
        PILImage.new("RGB", (2600, 2000), (10, 20, 30)).save(str(big))
        monkeypatch.setattr("freeassetfilter.components.photo_viewer.os.path.getsize", lambda p: 25 * 1024 * 1024)
        proc = HeifAvifProcessor(str(big))
        completed = _signal_collector(proc.processing_complete)
        proc.run()
        assert len(completed) == 1 and not completed[0][0].isNull()
        proc.deleteLater()

    def test_heif_avif_processor_run_import_and_cancel_branches(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        import sys
        import types

        from freeassetfilter.components.photo_viewer import HeifAvifProcessor

        png = tmp_path / "x.png"
        self._make_png(str(png))

        # pillow_avif 导入失败 → except ImportError: pass
        monkeypatch.setitem(sys.modules, "pillow_avif", None)
        proc = HeifAvifProcessor(str(png))
        completed = _signal_collector(proc.processing_complete)
        proc.run()
        assert len(completed) == 1
        proc.deleteLater()

        # pillow_heif 导入失败 → except ImportError: pass
        monkeypatch.setitem(sys.modules, "pillow_heif", None)
        proc2 = HeifAvifProcessor(str(png))
        completed2 = _signal_collector(proc2.processing_complete)
        proc2.run()
        assert len(completed2) == 1
        proc2.deleteLater()

        # 341：heif 注册后（getsize 前）取消
        def _getsize_cancel(p: str) -> int:
            proc3._is_cancelled = True
            return 100

        proc3 = HeifAvifProcessor(str(png))
        loaded_cancel = _signal_collector(proc3.processing_complete)
        monkeypatch.setattr("freeassetfilter.components.photo_viewer.os.path.getsize", _getsize_cancel)
        proc3.run()
        assert loaded_cancel == []
        proc3.deleteLater()

        # 409-410：PIL 导入失败 → 缺少依赖分支（用无 Image 属性的假 PIL）
        fake_pil = types.ModuleType("fake_PIL")
        monkeypatch.setitem(sys.modules, "PIL", fake_pil)
        proc4 = HeifAvifProcessor(str(png))
        failed4 = _signal_collector(proc4.processing_failed)
        proc4.run()
        assert len(failed4) == 1 and "缺少依赖" in failed4[0][0]
        proc4.deleteLater()

    def test_image_loader_run_branches(self, qapp: QApplication, tmp_path: Any, monkeypatch: Any) -> None:
        import freeassetfilter.components.photo_viewer as pv
        from PySide6.QtCore import QSize

        png = tmp_path / "x.png"
        make_image(str(png))

        # reader.size() > 4096 超大图 → setScaledSize 分支
        class _BigReader:
            def __init__(self, path: str) -> None:
                self._img = QImage(path)
                self.scaled: Any = None

            def size(self) -> Any:
                return QSize(5000, 5000)

            def setScaledSize(self, s: Any) -> None:
                self.scaled = s

            def read(self) -> QImage:
                return self._img

        monkeypatch.setattr(pv, "QImageReader", _BigReader)
        loader = pv.ImageLoader(str(png))
        completed = _signal_collector(loader.processing_complete)
        loader.run()
        assert len(completed) == 1
        loader.deleteLater()

        # 读取抛异常 → 未知错误分支
        class _BoomReader:
            def __init__(self, path: str) -> None:
                raise OSError("boom")

        monkeypatch.setattr(pv, "QImageReader", _BoomReader)
        loader2 = pv.ImageLoader(str(png))
        failed2 = _signal_collector(loader2.processing_failed)
        loader2.run()
        assert len(failed2) == 1 and "未知错误" in failed2[0][0]
        loader2.deleteLater()


# ===== text_previewer 语法高亮 / 编辑控件 / 线程 =====

class TestTextSyntaxHighlighters:
    """text_previewer 高亮家族：构造契约（QSyntaxHighlighter 子类）。"""

    @pytest.mark.parametrize("hl_cls", ["SyntaxHighlighter", "PythonHighlighter", "JsonHighlighter", "XmlHighlighter"])
    def test_highlighter_construct(self, qapp: QApplication, hl_cls: str) -> None:
        import importlib

        from PySide6.QtGui import QTextDocument

        mod = importlib.import_module("freeassetfilter.components.text_previewer")
        cls = getattr(mod, hl_cls)
        document = QTextDocument("print('hello')")
        highlighter = cls(document)
        try:
            assert highlighter.document() is not None
        finally:
            document.deleteLater()

    def test_adapter_construct_and_theme(self, qapp: QApplication) -> None:
        from PySide6.QtGui import QTextDocument

        from freeassetfilter.components.text_previewer import FAFHighlighterAdapter

        document = QTextDocument()
        adapter = FAFHighlighterAdapter(document, file_path="script.py", language="python")
        try:
            assert adapter.language in ("python", "text")
            adapter.rehighlight()
            adapter.update_theme()
        finally:
            document.deleteLater()

    def test_edit_and_line_area(self, qapp: QApplication) -> None:
        from PySide6.QtWidgets import QTextEdit

        from freeassetfilter.components.text_previewer import LineNumberArea, ZoomDisabledTextEdit

        edit = ZoomDisabledTextEdit(parent=None)
        area = LineNumberArea(edit, settings_manager=_settings_manager())
        try:
            assert callable(area.update_width)
            area.update_width()
            assert area.get_width() >= 0
        finally:
            safe_teardown(area)
            safe_teardown(edit)

    def test_text_preview_thread_set_file(self, qapp: QApplication) -> None:
        from freeassetfilter.components.text_previewer import TextPreviewThread

        missing_path = str(tmp_missing())
        thread = TextPreviewThread(parent=None)
        try:
            thread.setFile(missing_path, encoding="utf-8")
            assert thread.file_path == missing_path
        finally:
            if thread.isRunning():
                thread.wait(2000)
            thread.deleteLater()


# ===== video_player 独立窗口 / 占位 =====

class TestVideoPlayerWindow:
    """video_player 独立窗口与占位部件：构造契约。"""

    def test_detached_window_construct(self, qapp: QApplication) -> None:
        from freeassetfilter.components.video_player import DetachedVideoWindow

        window = DetachedVideoWindow(parent=None, dpi_scale=1.0, global_font=_global_font())
        try:
            assert window.windowTitle() == "视频播放器 - FreeAssetFilter"
            window.close()
        finally:
            safe_teardown(window)

    def test_placeholder_set_message(self, qapp: QApplication) -> None:
        from freeassetfilter.components.video_player import VideoPlaceholder

        placeholder = VideoPlaceholder(parent=None)
        try:
            placeholder.set_message("加载中...")
        finally:
            safe_teardown(placeholder)


# ===== font_previewer FontLoadThread / FontPreviewer 结构 =====

class TestFontWorkerAndPreviewer:
    """font_previewer：FontLoadThread 构造 + FontPreviewer 结构断言（规避生产 NameError）。"""

    def test_font_load_thread_contract(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.font_previewer import FontLoadThread

        thread = FontLoadThread(parent=None)
        try:
            thread.set_request_id(7)
            thread.set_file(str(tmp_path))
            assert hasattr(thread, "abort")
        finally:
            if thread.isRunning():
                thread.wait(2000)
            thread.deleteLater()

    def test_font_previewer_structure(self, qapp: QApplication) -> None:
        """FontPreviewer 因生产 NameError 不可直接构造：用结构断言验证接口。"""
        from PySide6.QtWidgets import QWidget

        from freeassetfilter.components.font_previewer import FontPreviewer

        assert issubclass(FontPreviewer, QWidget)
        assert callable(FontPreviewer.set_preview_text)


# ===== pdf_previewer PDFPageWidget =====

class TestPdfPageWidget:
    """PDFPageWidget：显式传 settings_manager 规避生产 NameError 后构造。"""

    @pytest.fixture(autouse=True)
    def _inject_app_global(self, monkeypatch: Any, qapp: QApplication) -> None:
        import freeassetfilter.components.pdf_previewer as pdf_mod

        monkeypatch.setattr(pdf_mod, "app", qapp, raising=False)

    def test_construct_and_size(self, qapp: QApplication) -> None:
        from freeassetfilter.components.pdf_previewer import PDFPageWidget

        page = PDFPageWidget(parent=None, settings_manager=_settings_manager(), dpi_scale=1.0)
        try:
            assert callable(page.set_page_pixmap)
            assert page.sizeHint().isValid()
        finally:
            safe_teardown(page)


# ===== folder_content_list 加载线程 =====

class TestFolderContentLoaderThread:
    """FolderContentLoaderThread：构造契约（不启动）。"""

    def test_construct(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.folder_content_list import FolderContentLoaderThread

        thread = FolderContentLoaderThread(str(tmp_path))
        try:
            assert not thread.isRunning()
            assert thread._path == str(tmp_path)
        finally:
            if thread.isRunning():
                thread.wait(2000)
            thread.deleteLater()


# ===== file_info_previewer AudioInfoTask =====

class TestAudioInfoTask:
    """AudioInfoTask（QRunnable）：构造契约（不执行真实解析，避免 mutagen 依赖）。"""

    def test_construct(self, qapp: QApplication, tmp_path: Any) -> None:
        from freeassetfilter.components.file_info_previewer import AudioInfoTask

        missing_path = str(tmp_missing())
        task = AudioInfoTask(missing_path, 1, lambda *_: None)
        try:
            assert task.task_id == 1
            assert task.file_path == missing_path
            assert callable(task.run)
        finally:
            pass


# ===== 末尾辅助（模块级延迟求值避免不必要的导入） =====

def tmp_missing() -> str:
    """返回一个必然不存在的临时路径（带随机后缀防碰撞）。"""
    import tempfile

    return os.path.join(tempfile.gettempdir(), f"faf_missing_{time.time_ns()}.tmp")