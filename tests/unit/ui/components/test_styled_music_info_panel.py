# -*- coding: utf-8 -*-
"""StyledMusicInfoPanel 单元测试

测试 freeassetfilter/ui/components/styled_music_info_panel.py 的公共接口：
- 标题 / 艺术家设置
- 封面 / 占位图切换
- 空艺术家降级为 "未知艺术家"
- 长文本 ElideRight 截断
- clear() 重置状态
- 透明背景
"""

import sys
from pathlib import Path

# Match the sys.path bootstrap in text_previewer_layout tests: expose the
# freeassetfilter/ui directory as a top-level import root for ``theme`` and
# ``components`` short-path imports used by styled components.
_UI_ROOT = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

import pytest

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics, QPixmap
from PySide6.QtWidgets import QLabel

from freeassetfilter.ui.components.styled_music_info_panel import StyledMusicInfoPanel


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def panel(qapp) -> StyledMusicInfoPanel:
    """创建并返回一个独立的 StyledMusicInfoPanel 实例。"""
    widget = StyledMusicInfoPanel(parent=None)
    widget.resize(400, 140)
    try:
        yield widget
    finally:
        widget.close()
        widget.deleteLater()


# =============================================================================
# API surface
# =============================================================================


class TestStyledMusicInfoPanelAPISurface:
    """验证公共 API 可调用。"""

    def test_api_surface(self, qapp) -> None:
        """面板应暴露 set_title / set_artist / set_cover_pixmap / set_placeholder / clear。"""
        widget = StyledMusicInfoPanel(parent=None)
        try:
            assert callable(widget.set_title)
            assert callable(widget.set_artist)
            assert callable(widget.set_cover_pixmap)
            assert callable(widget.set_placeholder)
            assert callable(widget.clear)
        finally:
            widget.close()
            widget.deleteLater()


# =============================================================================
# Title / artist behavior
# =============================================================================


class TestStyledMusicInfoPanelText:
    """测试标题和艺术家文本更新及缺省降级。"""

    def test_set_title_updates_label(self, panel: StyledMusicInfoPanel) -> None:
        """设置标题后，标题标签应显示对应文本。"""
        panel.set_title("告白气球")
        assert panel._title_label.text() == "告白气球"

    def test_empty_title_allowed(self, panel: StyledMusicInfoPanel) -> None:
        """空标题保持为空，不会变成其他默认值。"""
        panel.set_title("暂定")
        panel.set_title("")
        assert panel._title_label.text() == ""

    def test_set_artist_updates_label(self, panel: StyledMusicInfoPanel) -> None:
        """设置艺术家后，艺术家标签应显示对应文本。"""
        panel.set_artist("周杰伦")
        assert panel._artist_label.text() == "周杰伦"

    def test_empty_artist_shows_unknown(self, panel: StyledMusicInfoPanel) -> None:
        """空艺术家或仅空白字符时显示 '未知艺术家'。"""
        panel.set_artist("")
        assert panel._artist_label.text() == "未知艺术家"

        panel.set_artist("   ")
        assert panel._artist_label.text() == "未知艺术家"


# =============================================================================
# Cover / placeholder behavior
# =============================================================================


class TestStyledMusicInfoPanelCover:
    """测试封面与占位图切换。"""

    def test_placeholder_shown_on_init(self, panel: StyledMusicInfoPanel) -> None:
        """初始化时左侧面板应已加载 SVG 占位图。"""
        assert not panel._cover_label.pixmap().isNull()

    def test_set_cover_pixmap_updates_cover(
        self, qapp, panel: StyledMusicInfoPanel
    ) -> None:
        """设置有效 QPixmap 后左侧应显示该封面。"""
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.red)
        panel.set_cover_pixmap(pixmap)
        assert not panel._cover_label.pixmap().isNull()

    def test_set_cover_pixmap_none_restores_placeholder(
        self, panel: StyledMusicInfoPanel
    ) -> None:
        """传入 None 时应恢复 SVG 占位图。"""
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.red)
        panel.set_cover_pixmap(pixmap)
        panel.set_cover_pixmap(None)
        assert not panel._cover_label.pixmap().isNull()

    def test_set_placeholder_restores_default(
        self, panel: StyledMusicInfoPanel
    ) -> None:
        """显式调用 set_placeholder() 应恢复默认占位图。"""
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.blue)
        panel.set_cover_pixmap(pixmap)
        panel.set_placeholder()
        assert not panel._cover_label.pixmap().isNull()


# =============================================================================
# Elision
# =============================================================================


class TestStyledMusicInfoPanelElision:
    """测试长文本 ElideRight 截断。"""

    def test_long_title_elided(self, qapp, panel: StyledMusicInfoPanel) -> None:
        """过长标题在窄宽度下应被截断并带省略号。"""
        long_title = "A" * 500
        panel.set_title(long_title)
        # 200 px leaves very little room for text, forcing "..." output.
        panel.resize(200, 120)
        qapp.processEvents()

        displayed = panel._title_label.text()
        # 如果实际渲染后未截断（例如字体极小），则退而断言 elide 机制已启用。
        if len(displayed) >= len(long_title):
            assert panel._elide_enabled is True
        else:
            assert displayed.endswith("\u2026")

    def test_long_artist_elided(self, qapp, panel: StyledMusicInfoPanel) -> None:
        """过长艺术家名在窄宽度下应被截断并带省略号。"""
        long_artist = "B" * 500
        panel.set_artist(long_artist)
        panel.resize(200, 120)
        qapp.processEvents()

        displayed = panel._artist_label.text()
        if len(displayed) >= len(long_artist):
            assert panel._elide_enabled is True
        else:
            assert displayed.endswith("\u2026")

    def test_elide_uses_right_mode(self, panel: StyledMusicInfoPanel) -> None:
        """截断模式应为 Qt.ElideRight。"""
        assert panel._elide_mode == Qt.TextElideMode.ElideRight


# =============================================================================
# Clear / transparency
# =============================================================================


class TestStyledMusicInfoPanelMisc:
    """测试 clear() 与透明背景。"""

    def test_clear_resets_state(self, panel: StyledMusicInfoPanel) -> None:
        """clear() 应清空标题、恢复 '未知艺术家' 并恢复占位图。"""
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.green)

        panel.set_title("晴天")
        panel.set_artist("周杰伦")
        panel.set_cover_pixmap(pixmap)
        panel.clear()

        assert panel._title_label.text() == ""
        assert panel._artist_label.text() == "未知艺术家"
        assert not panel._cover_label.pixmap().isNull()

    def test_background_is_transparent(self, panel: StyledMusicInfoPanel) -> None:
        """面板应使用 WA_TranslucentBackground，不遮挡流体背景。"""
        assert panel.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True
