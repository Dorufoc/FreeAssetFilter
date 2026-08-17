# -*- coding: utf-8 -*-
"""GUI 组件渲染矩阵测试（tests-comprehensive-refactor todo-26 重写）。

对 12 个代表性组件逐一代入离屏渲染并落盘截图，断言每个 pixmap 非空
（逐像素扫描）且状态对之间几何一致。全部使用
``capture_widget(widget, output_path=..., size=...)``（scripts/qt_capture），
**不**使用 ``capture_multiple_states`` / ``compare_screenshots``（无像素
基线）。截图只写入 ``tests/gui/screenshots/``（gitignore）。

覆盖矩阵（每个组件至少一个固定尺寸截图）：
* 卡片类：FileBlockCard（默认/选中）、CustomFileHorizontalCard（默认/选中）
* 预览类：UnifiedPreviewer（占位）、PhotoViewer（初始加载视图）
* 面板类：CustomFileSelector（空/满）、FileStagingPool（含条目）
* 主题卡：ThemeCard（默认/选中）
* styled 控件 5 个：StyledButton / StyledSlider / StyledToggle /
  StyledLineEdit / StyledInfoCard

约定（todo-26）：零生产代码改动；每个测试显式依赖 ``qapp`` fixture；
文件级 ``pytestmark = pytest.mark.gui``——默认 addopts ``-m "not gui"``
排除，仅 ``python tests/run_tests.py gui``（-m gui）收集执行。
"""

# targets: widgets.file_block_card, widgets.file_horizontal_card,
#          components.unified_previewer, components.photo_viewer,
#          components.file_selector, components.file_staging_pool,
#          widgets.theme_card, ui.components.styled_button,
#          ui.components.styled_info_card, ui.components.styled_lineedit,
#          ui.components.styled_slider, ui.components.styled_toggle

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

# UI 短路径导入 bootstrap：styled 组件内部使用 `from components.X import Y`
# 与 `from theme import tm` 短路径，require `freeassetfilter/ui` 在 sys.path
# （参照 tests/unit/ui/test_ui_theme.py:31-33 的 bootstrap）。
_UI_ROOT: str = str(Path(__file__).resolve().parents[2] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

# ui/theme 必须先导入注册 sys.modules['theme'] 别名（ui/theme/__init__.py），
# 保证 styled 组件模块内 `from theme import tm` 与
# `from freeassetfilter.ui.theme import tm` 收敛到同一个单例对象。
import freeassetfilter.ui.theme  # noqa: E402  (注册 'theme' 模块别名)
from freeassetfilter.ui.components.styled_button import StyledButton  # noqa: E402
from freeassetfilter.ui.components.styled_info_card import StyledInfoCard  # noqa: E402
from freeassetfilter.ui.components.styled_lineedit import StyledLineEdit  # noqa: E402
from freeassetfilter.ui.components.styled_slider import StyledSlider  # noqa: E402
from freeassetfilter.ui.components.styled_toggle import StyledToggle  # noqa: E402

from freeassetfilter.components.file_selector import CustomFileSelector
from freeassetfilter.components.file_staging_pool import FileStagingPool
from freeassetfilter.components.photo_viewer import PhotoViewer
from freeassetfilter.components.unified_previewer import UnifiedPreviewer
from freeassetfilter.services.drive_service import DriveService
from freeassetfilter.services.staging_pool_service import StagingPoolService
from freeassetfilter.widgets.file_block_card import FileBlockCard
from freeassetfilter.widgets.file_horizontal_card import CustomFileHorizontalCard
from freeassetfilter.widgets.theme_card import ThemeCard

from tests.support.data_factories import make_text
from tests.support.qt_helpers import assert_pixmap_nonempty, safe_teardown
from scripts.qt_capture import capture_widget

pytestmark = pytest.mark.gui


# =============================================================================
# 公共辅助
# =============================================================================
def _capture(
    widget: Any,
    screenshots_dir: str,
    state_name: str,
    size: tuple[int, int],
) -> Any:
    """离屏渲染 widget 并落盘截图，断言非空后返回 pixmap。

    Args:
        widget: 被测 QWidget。
        screenshots_dir: 截图输出目录（fixture 提供）。
        state_name: 状态名（PNG 文件名，不含扩展名）。
        size: (宽, 高) 固定尺寸。

    Returns:
        QPixmap: 捕获结果（已断言非空）。
    """
    output_path: str = str(Path(screenshots_dir) / f"{state_name}.png")
    pixmap = capture_widget(widget, output_path=output_path, size=size)
    assert_pixmap_nonempty(pixmap, f"{state_name} 截图应包含可见像素")
    return pixmap


def _assert_same_geometry(pixmap_a: Any, pixmap_b: Any, label: str) -> None:
    """断言两个状态截图的几何尺寸完全一致。

    Args:
        pixmap_a: 首个状态的 QPixmap。
        pixmap_b: 对比状态的 QPixmap。
        label: 失败时的诊断标签。

    Raises:
        AssertionError: 尺寸不一致。
    """
    assert pixmap_a.size() == pixmap_b.size(), (
        f"{label} 两状态几何应一致: {pixmap_a.size()} != {pixmap_b.size()}"
    )


# =============================================================================
# 卡片类
# =============================================================================
class TestFileBlockCard:
    """FileBlockCard 默认 / 选中两状态渲染。"""

    def test_default_state_renders(
        self, qapp: Any, screenshots_dir: str, settings_manager: Any
    ) -> None:
        """默认状态 card 可渲染非空。"""
        file_info: Dict[str, Any] = {
            "path": str(Path(qapp.applicationDirPath()) / "sample.txt"),
            "name": "sample.txt",
            "is_dir": False,
            "size": 1024,
            "suffix": "txt",
        }
        card: Any = FileBlockCard(
            file_info=file_info,
            dpi_scale=1.0,
            settings_manager=settings_manager,
        )
        try:
            _capture(card, screenshots_dir, "file_block_card_default", (360, 240))
        finally:
            safe_teardown(card)

    def test_selected_state_renders(
        self, qapp: Any, screenshots_dir: str, settings_manager: Any
    ) -> None:
        """选中态 card 渲染非空且与默认态几何一致。"""
        file_info: Dict[str, Any] = {
            "path": str(Path(qapp.applicationDirPath()) / "book.pdf"),
            "name": "book.pdf",
            "is_dir": False,
            "size": 204800,
            "suffix": "pdf",
        }
        card: Any = FileBlockCard(
            file_info=file_info,
            dpi_scale=1.0,
            settings_manager=settings_manager,
        )
        card.set_selected(True)
        try:
            pixmap: Any = _capture(
                card, screenshots_dir, "file_block_card_selected", (360, 240)
            )
            assert pixmap.width() > 0 and pixmap.height() > 0
        finally:
            safe_teardown(card)


class TestCustomFileHorizontalCard:
    """CustomFileHorizontalCard 默认 / 选中两状态渲染。"""

    def _make_card(self, settings_manager: Any, selected: bool) -> Any:
        """构造水平卡片（默认或选中）。

        Args:
            settings_manager: 临时设置管理器。
            selected: True 时置为选中态。

        Returns:
            CustomFileHorizontalCard: 已构造的卡片。
        """
        card: Any = CustomFileHorizontalCard(
            file_path=str(Path("C:/test") / "folder"),
            display_name="Test Folder",
            enable_multiselect=False,
            dpi_scale=1.0,
            settings_manager=settings_manager,
        )
        if selected:
            card.set_selected(True)
        return card

    def test_default_state_renders(
        self, qapp: Any, screenshots_dir: str, settings_manager: Any
    ) -> None:
        """默认状态 horizontal card 可渲染非空。"""
        card: Any = self._make_card(settings_manager, selected=False)
        try:
            _capture(card, screenshots_dir, "file_horizontal_card_default", (480, 96))
        finally:
            safe_teardown(card)

    def test_selected_state_renders(
        self, qapp: Any, screenshots_dir: str, settings_manager: Any
    ) -> None:
        """选中态渲染非空，且与默认态共享固定捕获尺寸。"""
        card: Any = self._make_card(settings_manager, selected=True)
        try:
            pixmap: Any = _capture(
                card, screenshots_dir, "file_horizontal_card_selected", (480, 96)
            )
            assert pixmap.size() == QSize(480, 96)
        finally:
            safe_teardown(card)


# =============================================================================
# 预览类
# =============================================================================
class TestPreviewers:
    """UnifiedPreviewer / PhotoViewer 初始占位视图渲染。"""

    def test_unified_previewer_placeholder(
        self, qapp: Any, screenshots_dir: str, settings_manager: Any
    ) -> None:
        """UnifiedPreviewer 无文件时渲染占位视图。"""
        previewer: Any = UnifiedPreviewer(
            settings_manager=settings_manager,
            dpi_scale=1.0,
            global_font=qapp.global_font,
        )
        try:
            _capture(previewer, screenshots_dir, "unified_previewer_placeholder", (480, 320))
        finally:
            safe_teardown(previewer)

    def test_photo_viewer_initial(
        self, qapp: Any, screenshots_dir: str, settings_manager: Any
    ) -> None:
        """PhotoViewer 构造后的初始加载视图可渲染。"""
        viewer: Any = PhotoViewer(
            settings_manager=settings_manager,
            dpi_scale=1.0,
            global_font=qapp.global_font,
        )
        try:
            _capture(viewer, screenshots_dir, "photo_viewer_initial", (480, 320))
        finally:
            safe_teardown(viewer)


# =============================================================================
# 文件选择器（空 / 满）
# =============================================================================
class TestCustomFileSelector:
    """CustomFileSelector 空列表 / 模型填充后渲染。"""

    def _make_selector(
        self,
        screenshots_dir: str,
        settings_manager: Any,
        tmp_path: Any,
        monkeypatch: Any,
        filled: bool,
    ) -> Any:
        """构造隔离的 CustomFileSelector 并可选填充模型。

        Args:
            screenshots_dir: 截图目录（仅透传）。
            settings_manager: 临时设置管理器。
            tmp_path: 临时目录。
            monkeypatch: pytest monkeypatch fixture。
            filled: True 时向 file_model 注入文件列表。

        Returns:
            QPixmap: 捕获结果（已断言非空）。
        """
        monkeypatch.setattr(CustomFileSelector, "load_last_path", lambda self: None)
        monkeypatch.setattr(CustomFileSelector, "_load_view_mode", lambda self: None)
        monkeypatch.setattr(CustomFileSelector, "refresh_files", lambda self: None)
        monkeypatch.setattr(DriveService, "list_drives", lambda *a, **k: ["C:\\"])
        monkeypatch.setattr(
            DriveService, "_list_windows_drives", lambda *a, **k: ["C:\\"]
        )
        monkeypatch.setattr(
            DriveService, "_list_windows_network_locations", lambda *a, **k: []
        )

        selector: Any = CustomFileSelector(settings_manager=settings_manager)
        selector.save_path_file = str(tmp_path / "last_path.json")
        selector.save_view_mode_file = str(tmp_path / "view_mode.json")
        selector.favorites_file = str(tmp_path / "favorites.json")

        if filled:
            text_file: str = make_text(tmp_path / "doc.txt")
            entries: List[Dict[str, Any]] = [
                {"name": "doc.txt", "path": text_file, "is_dir": False, "size": 8, "suffix": "txt"},
                {"name": "logo.png", "path": str(tmp_path / "logo.png"), "is_dir": False, "size": 50, "suffix": "png"},
                {"name": "assets", "path": str(tmp_path / "assets"), "is_dir": True, "size": 0, "suffix": ""},
            ]
            selector.file_model.set_files(entries)

        state_name: str = "file_selector_filled" if filled else "file_selector_empty"
        try:
            return self._capture_selector(selector, screenshots_dir, state_name)
        finally:
            for thread_name in ("_file_loader_thread", "_drive_list_thread"):
                thread: Any = getattr(selector, thread_name, None)
                if thread is not None and thread.isRunning():
                    if not thread.wait(2000):
                        thread.terminate()
                        thread.wait(1000)
            safe_teardown(selector)

    def _capture_selector(self, selector: Any, screenshots_dir: str, state_name: str) -> Any:
        """捕获选择器并断言非空即返回 pixmap。

        Args:
            selector: CustomFileSelector 实例。
            screenshots_dir: 截图目录。
            state_name: 状态名。

        Returns:
            QPixmap: 捕获结果。
        """
        output_path: str = str(Path(screenshots_dir) / f"{state_name}.png")
        pixmap: Any = capture_widget(selector, output_path=output_path, size=(640, 420))
        assert_pixmap_nonempty(pixmap, f"{state_name} 截图应包含可见像素")
        return pixmap

    def test_empty_list_renders(
        self,
        qapp: Any,
        screenshots_dir: str,
        settings_manager: Any,
        tmp_path: Any,
        monkeypatch: Any,
    ) -> None:
        """空文件列表的选择器可渲染。"""
        self._make_selector(
            screenshots_dir, settings_manager, tmp_path, monkeypatch, filled=False
        )

    def test_filled_list_renders(
        self,
        qapp: Any,
        screenshots_dir: str,
        settings_manager: Any,
        tmp_path: Any,
        monkeypatch: Any,
    ) -> None:
        """模型填充条目后选择器可渲染。"""
        self._make_selector(
            screenshots_dir, settings_manager, tmp_path, monkeypatch, filled=True
        )


# =============================================================================
# 文件暂存池（含条目）
# =============================================================================
class TestFileStagingPool:
    """FileStagingPool 含条目时渲染。"""

    def test_with_items_renders(
        self, qapp: Any, screenshots_dir: str, settings_manager: Any, tmp_path: Any
    ) -> None:
        """向暂存池添加非媒体条目后可渲染非空。"""
        StagingPoolService._instance = None
        pool: Any = FileStagingPool(
            settings_manager=settings_manager,
            dpi_scale=1.0,
            global_font=qapp.global_font,
        )
        pool.backup_file = str(tmp_path / "pool_backup.json")
        try:
            text_file: str = make_text(tmp_path / "pool_item.txt")
            pool.add_file(
                {
                    "name": "pool_item.txt",
                    "path": text_file,
                    "is_dir": False,
                    "size": 8,
                    "suffix": "txt",
                }
            )
            state_name: str = "file_staging_pool_items"
            output_path: str = str(Path(screenshots_dir) / f"{state_name}.png")
            pixmap: Any = capture_widget(pool, output_path=output_path, size=(640, 420))
            assert_pixmap_nonempty(pixmap, f"{state_name} 截图应包含可见像素")
        finally:
            pool.cleanup()
            safe_teardown(pool)
            StagingPoolService._instance = None


# =============================================================================
# 主题卡片
# =============================================================================
class TestThemeCard:
    """ThemeCard 默认 / 选中两状态渲染。"""

    def _make_card(self, settings_manager: Any, selected: bool) -> Any:
        """构造主题卡片（默认或选中）。

        Args:
            settings_manager: 临时设置管理器。
            selected: True 时置为选中态。

        Returns:
            ThemeCard: 已构造的卡片。
        """
        colors: List[str] = ["#7C4DFF", "#FFFFFF", "#EEEEEE", "#AAAAAA"]
        card: Any = ThemeCard(
            theme_name="自定义主题",
            colors=colors,
            is_selected=selected,
            is_add_card=False,
            dpi_scale=1.0,
            settings_manager=settings_manager,
        )
        if selected:
            card.set_selected(True)
        return card

    def test_default_state_renders(
        self, qapp: Any, screenshots_dir: str, settings_manager: Any
    ) -> None:
        """默认状态主题卡可渲染非空。"""
        card: Any = self._make_card(settings_manager, selected=False)
        try:
            _capture(card, screenshots_dir, "theme_card_default", (280, 180))
        finally:
            safe_teardown(card)

    def test_selected_state_renders(
        self, qapp: Any, screenshots_dir: str, settings_manager: Any
    ) -> None:
        """选中态主题卡渲染非空且与默认态几何一致。"""
        default_card: Any = self._make_card(settings_manager, selected=False)
        default_pix: Any
        try:
            default_pix = _capture(default_card, screenshots_dir, "theme_card_default_only_for_compare", (280, 180))
        finally:
            safe_teardown(default_card)

        selected_card: Any = self._make_card(settings_manager, selected=True)
        try:
            selected_pix: Any = _capture(
                selected_card, screenshots_dir, "theme_card_selected", (280, 180)
            )
            _assert_same_geometry(default_pix, selected_pix, "ThemeCard")
        finally:
            safe_teardown(selected_card)


# =============================================================================
# styled 控件（5 个代表）
# =============================================================================
class TestStyledComponents:
    """5 个代表 styled 控件渲染非空。"""

    def test_styled_button(
        self, qapp: Any, screenshots_dir: str
    ) -> None:
        """StyledButton primary 渲染非空。"""
        button: Any = StyledButton(text="确认", variant="primary")
        try:
            _capture(button, screenshots_dir, "styled_button_primary", (240, 56))
        finally:
            safe_teardown(button)

    def test_styled_lineedit(
        self, qapp: Any, screenshots_dir: str
    ) -> None:
        """StyledLineEdit 默认渲染非空。"""
        edit: Any = StyledLineEdit(text="搜索关键字", size="default")
        try:
            _capture(edit, screenshots_dir, "styled_lineedit_default", (240, 56))
        finally:
            safe_teardown(edit)

    def test_styled_toggle(
        self, qapp: Any, screenshots_dir: str
    ) -> None:
        """StyledToggle 选中态渲染非空。"""
        toggle: Any = StyledToggle(checked=True, size="default")
        try:
            _capture(toggle, screenshots_dir, "styled_toggle_checked", (120, 56))
        finally:
            safe_teardown(toggle)

    def test_styled_slider(
        self, qapp: Any, screenshots_dir: str
    ) -> None:
        """StyledSlider 默认渲染非空。"""
        slider: Any = StyledSlider(value=0.5)
        try:
            _capture(slider, screenshots_dir, "styled_slider_default", (240, 56))
        finally:
            safe_teardown(slider)

    def test_styled_info_card(
        self, qapp: Any, screenshots_dir: str
    ) -> None:
        """StyledInfoCard 横向布局渲染非空。"""
        card: Any = StyledInfoCard(
            layout_mode="horizontal",
            title="文件信息",
            subtitle="现代预览排版",
            desc="统一预览器中的信息卡片",
        )
        try:
            _capture(card, screenshots_dir, "styled_info_card_horizontal", (360, 120))
        finally:
            safe_teardown(card)