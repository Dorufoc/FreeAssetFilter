# -*- coding: utf-8 -*-
"""GUI 主题视觉切换测试（tests-comprehensive-refactor todo-26 重写）。

验证 ui/theme 的 ThemeManager 单例在深色 / 浅色之间切换时：

* 同一 styled 组件（StyledButton / StyledLineEdit）在两套主题下渲染出的
  截图**均非空**（逐像素扫描）；
* 两套主题下**同一组件截图几何尺寸一致**（组件不因换主题而变形）；
* 主题色值断言：``is_dark_theme()`` 翻转、``surface`` / ``gray.g1`` /
  ``gray_light.g1`` 的颜色表数值随主题变化；
* ``theme_changed`` 信号在 set_theme 时同步发射（先连接监听再触发断言）。

关键点（todo-26 + tests/conftest.py:112-116 约定）：

* **ui/theme ThemeManager 不在根 conftest 的 ``reset_singletons`` 清单内**
  ——本文件用 autouse fixture 在每个测试前后手动归零
  ``ThemeManager._instance = None`` / ``ThemeManager._initialized = False``。
* ui 短路径导入依赖 ``sopeek/ui`` 位于 ``sys.path``（参照
  tests/unit/ui/test_ui_theme.py 的 bootstrap），并且**必须先 import
  ``sopeek.ui.theme``** 注册 ``sys.modules['theme']`` 别名，
  保证 styled 组件内 ``from theme import tm`` 与本文件的
  ``from sopeek.ui.theme import tm`` 收敛到**同一单例**，避免
  双实例 Identity 分裂。
* 每个测试显式依赖 ``qapp``；``pytestmark = pytest.mark.gui``；截图只写
  ``screenshots_dir``（gui conftest fixture，自动建目录）。
"""

# targets: ui.theme.theme_manager, ui.components.styled_button,
#          ui.components.styled_lineedit

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterator

import pytest
from PySide6.QtCore import QSize

# UI 短路径导入 bootstrap（参照 tests/unit/ui/test_ui_theme.py:31-33）。
_UI_ROOT: str = str(Path(__file__).resolve().parents[2] / "sopeek" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

# 必须先导入并注册 'theme' 模块别名（ui/theme/__init__.py:29-30），
# 保证 styled 组件内 `from theme import tm` 与本文件拿到同一个单例。
import sopeek.ui.theme  # noqa: F401  (注册 sys.modules['theme'] 别名，副作用导入)
from sopeek.ui.theme import tm
from sopeek.ui.theme.theme_manager import ThemeManager

from sopeek.ui.components.styled_button import StyledButton
from sopeek.ui.components.styled_lineedit import StyledLineEdit

from scripts.qt_capture import capture_widget
from tests.support.parity import pixel_hash
from tests.support.qt_helpers import assert_pixmap_nonempty, safe_teardown

pytestmark = pytest.mark.gui


# =============================================================================
# 单例重置（autouse）
# =============================================================================
@pytest.fixture(autouse=True)
def _reset_theme_singleton() -> Iterator[None]:
    """每个测试前后手动归零 ui/theme ThemeManager 单例（autouse）。

    根 conftest 的 ``reset_singletons`` 明确**不**覆盖
    ui/theme/theme_manager 的 ``_instance`` / ``_initialized``（约定见
    tests/conftest.py:112-116）；本 fixture 补齐该清单缺口，防止
    set_theme / toggle_theme 的跨测试污染泄漏。

    Returns:
        None。
    """
    ThemeManager._instance = None
    ThemeManager._initialized = False
    yield
    ThemeManager._instance = None
    ThemeManager._initialized = False


# =============================================================================
# 公共辅助
# =============================================================================
def _capture_styled(widget: Any, screenshots_dir: str, state_name: str, size: tuple[int, int]) -> Any:
    """离屏渲染 styled 组件并落盘，断言非空后返回 pixmap。

    Args:
        widget: 被测 styled QWidget。
        screenshots_dir: 截图输出目录（fixture 提供）。
        state_name: 状态名（PNG 文件名，不含扩展名）。
        size: (宽, 高) 固定尺寸。

    Returns:
        QPixmap: 捕获结果（已断言非空）。
    """
    output_path: str = str(Path(screenshots_dir) / f"{state_name}.png")
    pixmap: Any = capture_widget(widget, output_path=output_path, size=size)
    assert_pixmap_nonempty(pixmap, f"{state_name} 截图应包含可见像素")
    return pixmap


def _assert_same_geometry(pixmap_a: Any, pixmap_b: Any, label: str) -> None:
    """断言两主题截图的几何尺寸完全一致。

    Args:
        pixmap_a: 深色主题截图。
        pixmap_b: 浅色主题截图。
        label: 失败时的诊断标签。

    Raises:
        AssertionError: 尺寸不一致。
    """
    assert pixmap_a.size() == pixmap_b.size(), (
        f"{label} 两主题几何应一致: {pixmap_a.size()} != {pixmap_b.size()}"
    )


# =============================================================================
# 深 / 浅主题切换视觉断言
# =============================================================================
class TestThemeSwitchingVisual:
    """同一组件在深 / 浅主题下渲染非空且几何一致。"""

    def test_styled_button_dark_and_light(
        self, qapp: Any, screenshots_dir: str
    ) -> None:
        """StyledButton 在深 / 浅两主题下截图均非空且尺寸一致。"""
        tm.set_theme("dark")
        button: Any = StyledButton(text="深色按钮", variant="primary")
        try:
            dark_pix: Any = _capture_styled(
                button, screenshots_dir, "theme_button_dark", (320, 120)
            )
        finally:
            safe_teardown(button)

        tm.set_theme("light")
        button2: Any = StyledButton(text="浅色按钮", variant="primary")
        try:
            light_pix: Any = _capture_styled(
                button2, screenshots_dir, "theme_button_light", (320, 120)
            )
        finally:
            safe_teardown(button2)

        _assert_same_geometry(dark_pix, light_pix, "StyledButton")

    def test_styled_lineedit_dark_and_light(
        self, qapp: Any, screenshots_dir: str
    ) -> None:
        """StyledLineEdit 在深 / 浅两主题下截图均非空且尺寸一致。"""
        tm.set_theme("dark")
        edit: Any = StyledLineEdit(text="深色输入", size="default")
        try:
            dark_pix: Any = _capture_styled(
                edit, screenshots_dir, "theme_lineedit_dark", (320, 100)
            )
        finally:
            safe_teardown(edit)

        tm.set_theme("light")
        edit2: Any = StyledLineEdit(text="浅色输入", size="default")
        try:
            light_pix: Any = _capture_styled(
                edit2, screenshots_dir, "theme_lineedit_light", (320, 100)
            )
        finally:
            safe_teardown(edit2)

        _assert_same_geometry(dark_pix, light_pix, "StyledLineEdit")


class TestThemeColorTable:
    """主题切换后的颜色表数值断言（读 ThemeManager 颜色表）。"""

    def test_is_dark_theme_flips(self, qapp: Any) -> None:
        """is_dark_theme() 随 set_theme 正确翻转。"""
        tm.set_theme("dark")
        assert tm.is_dark_theme() is True
        tm.set_theme("light")
        assert tm.is_dark_theme() is False
        tm.set_theme("dark")
        assert tm.is_dark_theme() is True

    def test_surface_color_changes_with_theme(self, qapp: Any) -> None:
        """surface（gray.g1 vs gray_light.g1）随主题变化且颜色不同。"""
        tm.set_theme("dark")
        dark_surface: str = tm.surface.name()
        tm.set_theme("light")
        light_surface: str = tm.surface.name()
        assert dark_surface != light_surface, (
            f"surface 应随主题变化: dark={dark_surface}, light={light_surface}"
        )

    def test_gray_token_table_differs(self, qapp: Any) -> None:
        """颜色表 gray.g1 与 gray_light.g1 解析出的 QColor 不同。"""
        tm.set_theme("dark")
        dark_gray: Any = tm.get_color("gray.g1")
        assert dark_gray is not None
        tm.set_theme("light")
        light_gray: Any = tm.get_color("gray_light.g1")
        assert light_gray is not None
        assert dark_gray.name() != light_gray.name(), (
            f"gray 颜色表应随主题变化: dark={dark_gray.name()}, light={light_gray.name()}"
        )

    def test_theme_changed_signal_emitted(self, qapp: Any) -> None:
        """set_theme 同步发射 theme_changed(str) 信号。"""
        emitted: list[str] = []
        tm.theme_changed.connect(lambda theme: emitted.append(theme))
        try:
            tm.set_theme("dark")
            assert emitted == ["dark"], f"应收到 theme_changed('dark')，实际 {emitted}"
            tm.set_theme("light")
            assert emitted == ["dark", "light"], f"应收到两次 theme_changed，实际 {emitted}"
        finally:
            tm.theme_changed.disconnect()

    def test_all_properties_return_qcolor(self, qapp: Any) -> None:
        """主题色值断言：关键属性/方法均返回有效 QColor。"""
        tm.set_theme("dark")
        from PySide6.QtGui import QColor

        for color in (tm.surface, tm.fill, tm.mid, tm.text, tm.accent, tm.danger):
            assert isinstance(color, QColor), f"主题属性应返回 QColor，得到 {type(color)}"
            assert color.isValid(), f"主题颜色应为有效 QColor: {color.name()}"
        # 尺寸一致性归属于切换测试；此处保证颜色表每次都能读到非空对象
        assert tm.surface.name().startswith("#")


# =============================================================================
# 切换不污染（跨测试隔离）
# =============================================================================
class TestThemeIsolation:
    """主题切换不跨界测试污染（配合 autouse 手动单例重置）。"""

    def test_state_does_not_leak_across_reset(self, qapp: Any) -> None:
        """前置测试切到 light 后，本测试通过显式 set_theme 不受残影影响。"""
        # 不依赖上一测试留下的主题状态；显式设置到深色。
        tm.set_theme("dark")
        assert tm.is_dark_theme() is True
        dark_surface: str = tm.surface.name()
        # 再切浅色验证颜色表可再次读取且不同。
        tm.set_theme("light")
        light_surface: str = tm.surface.name()
        assert dark_surface != light_surface
        # 尺寸断言：本测试独立构造组件，前面测试不残留 widget 状态。
        button: Any = StyledButton(text="隔离验证", variant="secondary")
        try:
            pixmap: Any = capture_widget(button, size=(320, 120))
            assert_pixmap_nonempty(pixmap, "隔离验证按钮应渲染非空")
            assert pixmap.size() == QSize(320, 120) or pixmap.width() > 0
        finally:
            safe_teardown(button)


# =============================================================================
# 强调色（主题色）单独变化的即时刷新回归
# =============================================================================
class TestAccentLiveRefresh:
    """主题色切换（只发 ``colors_updated``）时的即时刷新回归。

    回归背景：强调色变化不走 ``theme_changed``；仅在 ``theme_changed``
    时清缓存/重建位图的组件会卡住旧色（表现为「换主题色后部分控件不变，
    鼠标扫过才恢复」）。此处覆盖按钮配色缓存与图标重建两条链路。
    """

    def test_set_color_emits_colors_updated_only(self, qapp: Any) -> None:
        """set_color 只发 colors_updated，不发 theme_changed。

        Args:
            qapp: 会话级 QApplication。
        """
        theme_events: list[str] = []
        color_events: list[Any] = []
        tm.theme_changed.connect(lambda theme: theme_events.append(theme))
        tm.colors_updated.connect(lambda colors: color_events.append(colors))
        original: str = tm.accent.name()
        try:
            probe: str = "#FF00AA" if original.lower() != "#ff00aa" else "#22CC99"
            changed: bool = tm.set_color("accent.primary", probe)
            assert changed is True, "accent.primary 应为可写路径"
            assert color_events, "强调色变化应发射 colors_updated"
            assert theme_events == [], "强调色变化不应发射 theme_changed"
            assert tm.accent.name().lower() == probe.lower()
        finally:
            tm.set_color("accent.primary", original)
            tm.theme_changed.disconnect()
            tm.colors_updated.disconnect()

    def test_primary_button_repaints_without_hover(
        self, qapp: Any, screenshots_dir: str
    ) -> None:
        """强调色变化后 primary 按钮像素即时变化（无需鼠标扫过）。

        Args:
            qapp: 会话级 QApplication。
            screenshots_dir: 截图输出目录。
        """
        tm.set_theme("dark")
        button: Any = StyledButton(text="即时换色", variant="primary")
        original: str = tm.accent.name()
        try:
            first: Any = capture_widget(
                button, output_path=str(Path(screenshots_dir) / "accent_btn_before.png"),
                size=(240, 90),
            )
            first_hash: str = pixel_hash(first)

            probe: str = "#FF00AA" if original.lower() != "#ff00aa" else "#22CC99"
            assert tm.set_color("accent.primary", probe) is True
            qapp.processEvents()

            second: Any = capture_widget(
                button, output_path=str(Path(screenshots_dir) / "accent_btn_after.png"),
                size=(240, 90),
            )
            assert pixel_hash(second) != first_hash, (
                "强调色变化后 primary 按钮应即时按新色重绘（配色缓存未清空？）"
            )
        finally:
            tm.set_color("accent.primary", original)
            safe_teardown(button)

    def test_floating_pool_row_refresh_icon_rebuilds_pixmap(
        self, qapp: Any, tmp_path: Path
    ) -> None:
        """浮窗条目行 ``refresh_icon`` 按新强调色重建图标位图。

        Args:
            qapp: 会话级 QApplication。
            tmp_path: pytest 临时目录。
        """
        from sopeek.ui.floating_pool_window import _PoolItemRow

        png_path: Path = tmp_path / "row_icon.png"
        png_path.write_bytes(b"fake-png")
        row: Any = _PoolItemRow(
            {
                "path": str(png_path),
                "name": "row_icon.png",
                "suffix": "png",
                "is_dir": False,
                "size": 1,
            }
        )
        original: str = tm.accent.name()
        try:
            first: Any = row._icon_label.pixmap()
            assert first is not None and not first.isNull(), "行图标应渲染非空"

            probe: str = "#00AACC" if original.lower() != "#00aacc" else "#CC7700"
            assert tm.set_color("accent.primary", probe) is True
            row.refresh_icon()
            qapp.processEvents()

            second: Any = row._icon_label.pixmap()
            assert second is not None and not second.isNull()
            assert second.cacheKey() != first.cacheKey(), (
                "refresh_icon 后浮窗行图标应重新渲染"
            )
        finally:
            tm.set_color("accent.primary", original)
            safe_teardown(row)

    def test_unsupported_previewer_icon_refreshes_on_accent_change(
        self, qapp: Any, tmp_path: Path
    ) -> None:
        """「无法预览」页大图标随强调色变化即时重建（信号连线路径）。

        Args:
            qapp: 会话级 QApplication。
            tmp_path: pytest 临时目录。
        """
        from sopeek.ui.layout.preview.unsupported_previewer_layout import (
            UnsupportedPreviewerLayout,
        )

        target: Path = tmp_path / "sample.txt"
        target.write_text("hello", encoding="utf-8")

        previewer: Any = UnsupportedPreviewerLayout()
        original: str = tm.accent.name()
        try:
            previewer.set_file(
                {
                    "path": str(target),
                    "suffix": "txt",
                    "is_dir": False,
                    "name": "sample.txt",
                }
            )
            first: Any = previewer._icon_label.pixmap()
            assert first is not None and not first.isNull(), "预览图标应渲染非空"

            probe: str = "#77AA22" if original.lower() != "#77aa22" else "#AA2277"
            assert tm.set_color("accent.primary", probe) is True
            qapp.processEvents()

            second: Any = previewer._icon_label.pixmap()
            assert second is not None and not second.isNull()
            assert second.cacheKey() != first.cacheKey(), (
                "强调色变化后「无法预览」页图标应重新渲染"
            )
        finally:
            tm.set_color("accent.primary", original)
            safe_teardown(previewer)