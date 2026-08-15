"""
FontPreviewerLayout 冒烟测试

在隔离环境中测试 freeassetfilter/ui/layout/preview/font_previewer_layout.py
的 FontPreviewerLayout，不依赖 PreviewerRegistry 或 UnifiedPreviewer。

覆盖：
1. standalone 模式可实例化并暴露 set_file。
2. 顶栏固定高度 48px。
3. 初始化时显示未加载覆盖层。
4. set_file() 异步加载字体后切换到预览视图并设置 current_font_family。
5. 打包字体缺失时优雅跳过。
"""

import sys
import time
from pathlib import Path

# Match the sys.path bootstrap in font_previewer_layout.py so we can import
# sibling preview modules without triggering the full freeassetfilter.ui chain.
_UI_ROOT = str(Path(__file__).resolve().parents[5] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

import pytest
from PySide6.QtWidgets import QApplication

from freeassetfilter.ui.layout.preview import font_previewer_layout as fpl

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def bundled_font_path() -> str:
    """解析仓库内置 FiraCode-VF.ttf 路径；不存在时跳过测试。"""
    project_root = Path(__file__).resolve().parents[5]
    font_path = project_root / "freeassetfilter" / "icons" / "FiraCode-VF.ttf"
    if not font_path.is_file():
        pytest.skip(f"Bundled font not found: {font_path}")
    return str(font_path)


@pytest.fixture
def font_previewer(qapp) -> fpl.FontPreviewerLayout:
    """创建 FontPreviewerLayout 实例并在测试结束后清理。"""
    layout = fpl.FontPreviewerLayout(standalone=True)
    try:
        yield layout
    finally:
        layout.close()
        layout.deleteLater()


# =============================================================================
# 1. API 表面
# =============================================================================


class TestFontPreviewerLayoutAPISurface:
    """测试公共 API 是否存在且可调用。"""

    def test_api_surface(self, qapp) -> None:
        """验证 standalone 实例可创建，并暴露 set_file 与 close_requested。"""
        layout = fpl.FontPreviewerLayout(standalone=True)
        try:
            assert callable(layout.set_file)
            assert hasattr(layout, "close_requested")
            assert layout._standalone is True
        finally:
            layout.close()
            layout.deleteLater()


# =============================================================================
# 2. 顶栏高度
# =============================================================================


class TestFontPreviewerLayoutTopBar:
    """测试顶栏几何属性。"""

    def test_top_bar_height(self, qapp) -> None:
        """layout.show() 后顶栏高度应为 48px。"""
        layout = fpl.FontPreviewerLayout(standalone=True)
        try:
            layout.show()
            qapp.processEvents()

            assert layout._top_bar.height() == 48
            assert layout._top_bar.fixedHeight() == 48
        finally:
            layout.close()
            layout.deleteLater()


# =============================================================================
# 3. 初始化状态
# =============================================================================


class TestFontPreviewerLayoutInitialState:
    """测试初始状态。"""

    def test_initial_overlay_visible(self, font_previewer: fpl.FontPreviewerLayout) -> None:
        """初始化时内容栈应显示覆盖层（index 1）。"""
        assert font_previewer._content_stack.currentIndex() == 1


# =============================================================================
# 4. 字体加载
# =============================================================================


class TestFontPreviewerLayoutSetFile:
    """测试 set_file() 异步加载字体。"""

    def _wait_for_font_loaded(
        self,
        layout: fpl.FontPreviewerLayout,
        qapp: QApplication,
        timeout: float = 5.0,
    ) -> bool:
        """轮询等待字体加载完成。

        Args:
            layout: FontPreviewerLayout 实例。
            qapp: QApplication fixture。
            timeout: 最大等待时间（秒），默认 5 秒。

        Returns:
            是否在超时前加载成功。
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            qapp.processEvents()
            if layout._content_stack.currentIndex() == 0:
                return True
            time.sleep(0.05)
        return layout._content_stack.currentIndex() == 0

    def test_set_file_loads_bundled_font(
        self,
        qapp,
        bundled_font_path: str,
    ) -> None:
        """set_file() 加载打包字体后应切换到预览视图并设置字体族名称。"""
        layout = fpl.FontPreviewerLayout(standalone=True)
        try:
            layout.set_file(bundled_font_path)

            loaded = self._wait_for_font_loaded(layout, qapp)

            assert loaded, "字体加载未在 5 秒内完成"
            assert layout._content_stack.currentIndex() == 0
            assert layout.current_font_family != ""
        finally:
            layout.close()
            layout.deleteLater()

    def test_set_file_keeps_overlay_when_font_missing(
        self,
        qapp,
        tmp_path: Path,
    ) -> None:
        """当字体文件不存在时，加载失败应仍停留在覆盖层。"""
        missing_font = tmp_path / "missing.ttf"
        layout = fpl.FontPreviewerLayout(standalone=True)
        try:
            layout.set_file(str(missing_font))

            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                qapp.processEvents()
                time.sleep(0.05)

            assert layout._content_stack.currentIndex() == 1
            assert layout.current_font_family == ""
        finally:
            layout.close()
            layout.deleteLater()


# =============================================================================
# 5. 预览文本与主题
# =============================================================================


class TestFontPreviewerLayoutPreviewText:
    """测试预览文本同步。"""

    def test_default_preview_text_populates_text_edit(
        self, font_previewer: fpl.FontPreviewerLayout
    ) -> None:
        """初始预览区应包含默认示例文本。"""
        plain_text = font_previewer._preview_view._text_edit.toPlainText()
        assert "FreeAssetFilter" in plain_text

    def test_set_file_applies_preview_text(
        self,
        qapp,
        bundled_font_path: str,
    ) -> None:
        """加载字体后预览区仍应保留默认示例文本。"""
        layout = fpl.FontPreviewerLayout(standalone=True)
        try:
            layout.set_file(bundled_font_path)

            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                qapp.processEvents()
                if layout._content_stack.currentIndex() == 0:
                    break
                time.sleep(0.05)

            assert layout._content_stack.currentIndex() == 0
            plain_text = layout._preview_view._text_edit.toPlainText()
            assert "FreeAssetFilter" in plain_text
        finally:
            layout.close()
            layout.deleteLater()


# =============================================================================
# 6. 字重/样式选择器
# =============================================================================


class TestFontPreviewerWeightSelector:
    """测试字重/样式下拉框与高级可变字重弹窗。"""

    def _wait_for_font_loaded(self, layout: fpl.FontPreviewerLayout, qapp: QApplication, timeout: float = 5.0) -> bool:
        """轮询等待字体加载完成。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            qapp.processEvents()
            if layout._content_stack.currentIndex() == 0:
                return True
            time.sleep(0.05)
        return layout._content_stack.currentIndex() == 0

    def test_styles_populated_after_load(
        self,
        qapp,
        bundled_font_path: str,
    ) -> None:
        """加载多字重字体后，样式下拉框应包含多个命名实例。"""
        layout = fpl.FontPreviewerLayout(standalone=True)
        try:
            layout.set_file(bundled_font_path)
            assert self._wait_for_font_loaded(layout, qapp), "字体加载超时"
            combo = layout._weight_combo
            assert combo is not None
            # FiraCode-VF 至少包含 Light, Regular, Medium, SemiBold, Bold
            assert combo.count() >= 5
            # 包含 Regular
            items = [combo._items[i] for i in range(combo.count())]
            assert "Regular" in items
        finally:
            layout.close()
            layout.deleteLater()

    def test_style_selection_changes_preview_font(
        self,
        qapp,
        bundled_font_path: str,
    ) -> None:
        """选择不同命名实例应改变预览文本字体的 styleName。"""
        layout = fpl.FontPreviewerLayout(standalone=True)
        try:
            layout.set_file(bundled_font_path)
            assert self._wait_for_font_loaded(layout, qapp)
            combo = layout._weight_combo
            assert combo.count() >= 2
            initial_style = layout._preview_view._text_edit.font().styleName()
            # 选择第三个样式 (Medium)
            combo.setCurrentIndex(2)
            combo.selection_made.emit(combo.currentText())
            qapp.processEvents()
            new_style = layout._preview_view._text_edit.font().styleName()
            assert new_style != initial_style
        finally:
            layout.close()
            layout.deleteLater()

    def test_single_style_font_disables_combo(
        self,
        qapp,
        tmp_path: Path,
    ) -> None:
        """单一字重字体应显示不可用的下拉框（仅包含 Regular 并被禁用）。"""
        # 创建一个极简单实例 TTF（使用空字节模拟，实际需真实字体，这里跳过）
        # 由于无法生成真实单实例字体，本测试仅验证逻辑：若 _available_styles 为空则下拉框不可用
        layout = fpl.FontPreviewerLayout(standalone=True)
        try:
            # 手动模拟单实例状态
            layout._available_styles = []
            layout._populate_weight_combo()
            qapp.processEvents()
            combo = layout._weight_combo
            assert not combo.isEnabled()
            assert combo.count() == 1
            assert combo.currentText() == "Regular"
        finally:
            layout.close()
            layout.deleteLater()

    def test_variable_weight_slider_changes_preview_weight(
        self,
        qapp,
        bundled_font_path: str,
    ) -> None:
        """高级可变字重弹窗滑块应改变预览字重。"""
        layout = fpl.FontPreviewerLayout(standalone=True)
        try:
            layout.set_file(bundled_font_path)
            assert self._wait_for_font_loaded(layout, qapp)
            # 直接调用内部方法验证逻辑
            layout._apply_variable_weight(700)
            qapp.processEvents()
            weight = layout._preview_view._text_edit.font().weight()
            assert weight >= 600
            # 验证按钮标签同步
            assert layout._weight_btn.text() == "700"
        finally:
            layout.close()
            layout.deleteLater()

    def test_variable_weight_popup_opens_and_syncs(
        self,
        qapp,
        bundled_font_path: str,
    ) -> None:
        """点击高级按钮应打开弹窗，且弹窗能从父布局同步当前字重。"""
        layout = fpl.FontPreviewerLayout(standalone=True)
        try:
            layout.set_file(bundled_font_path)
            assert self._wait_for_font_loaded(layout, qapp)
            # 点击按钮
            layout._on_weight_clicked()
            qapp.processEvents()
            popup = layout._weight_popup
            assert popup is not None and popup.isVisible()
            # 修改滑块值
            popup._slider.value = 0.666  # ~700
            qapp.processEvents()
            weight = layout._preview_view._text_edit.font().weight()
            assert weight >= 600
            # 关闭弹窗
            popup.close_animated()
            qapp.processEvents()
        finally:
            layout.close()
            layout.deleteLater()

    def test_theme_toggle_does_not_crash_popup_and_refreshes_label(self, qapp) -> None:
        """主题切换不应导致高级字重弹窗崩溃或文字颜色刷新异常。"""
        layout = fpl.FontPreviewerLayout(standalone=True)
        try:
            # Load a bundled font first
            bundled_font_path = 'freeassetfilter/icons/FiraCode-VF.ttf'
            layout.set_file(bundled_font_path)
            # Wait for loading
            assert self._wait_for_font_loaded(layout, qapp)
            # Open the advanced weight popup
            layout._on_weight_clicked()
            qapp.processEvents()
            popup = layout._weight_popup
            assert popup is not None and popup.isVisible()
            # Switch theme
            from freeassetfilter.ui.theme import tm
            tm.set_theme("dark")
            qapp.processEvents()
            # Verify popup still usable after theme change
            assert popup.isVisible()
            assert popup._value_label.text() == "400"
            # Close popup cleanly
            popup.close_animated()
            qapp.processEvents()
        finally:
            layout.close()
            layout.deleteLater()


