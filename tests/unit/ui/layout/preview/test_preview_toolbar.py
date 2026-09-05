# -*- coding: utf-8 -*-
"""PreviewToolbarFrame 共享顶栏框架测试。

覆盖：
- 左「目录类」/ 右「全屏类」按钮的归位；
- 中部按钮组在宽度不足时按优先级折叠进「更多」菜单，恢复后自动展开；
- 折叠项可通过「更多」菜单触发原按钮行为；
- 居中的信息标签永不折叠，并持续获得可用宽度（info_available_width）；
- 文本预览器的字数/行数标签在极窄时缩字号 / 折成两行显示（不遮挡内容）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

_PROJECT_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "freeassetfilter").is_dir()
)
_UI_ROOT = _PROJECT_ROOT / "freeassetfilter" / "ui"
if str(_UI_ROOT) not in sys.path:
    sys.path.insert(0, str(_UI_ROOT))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from freeassetfilter.ui.components.styled_button import StyledButton  # noqa: E402
from freeassetfilter.ui.layout.preview.preview_toolbar import (  # noqa: E402
    PreviewToolbarFrame,
)
from freeassetfilter.ui.layout.preview.text_previewer_layout import (  # noqa: E402
    TextPreviewerLayout,
)
from tests.support.qt_helpers import process_qt_events  # noqa: E402


@pytest.fixture()
def host(qapp: QApplication) -> tuple[QWidget, PreviewToolbarFrame]:
    """创建一个手动控制宽度的宿主窗口（顶栏不参与父级布局）。"""
    win = QWidget()
    win.resize(1000, 60)
    bar = PreviewToolbarFrame(win)
    bar.setFixedHeight(48)
    bar.setGeometry(0, 0, 1000, 48)
    win.show()
    process_qt_events(qapp, ms=30)
    yield win, bar
    win.close()


def _icon_btn(tip: str) -> StyledButton:
    btn = StyledButton("", variant="ghost", size="sm")
    btn.setFixedSize(32, 32)
    btn.setToolTip(tip)
    return btn


def _resize_bar(
    qapp: QApplication, bar: PreviewToolbarFrame, width: int
) -> None:
    bar.setGeometry(0, 0, width, 48)
    process_qt_events(qapp, ms=30)


class TestToolbarGrouping:
    def test_left_directory_right_fullscreen(self, qapp, host):
        win, bar = host
        left = _icon_btn("目录")
        right = _icon_btn("全屏")
        zoom = _icon_btn("缩放")
        bar.add_left(left)
        bar.add_right(right)
        bar.add_trailing(zoom)
        bar.set_overflow_priority([zoom])
        process_qt_events(qapp, ms=30)
        assert bar._left_widgets == [left]
        assert bar._right_widgets == [right]
        assert bar._trail_widgets == [zoom]
        # 透明无背景：不设置任何背景 QSS 即可（QFrame 默认透明）
        assert bar.autoFillBackground() is False

    def test_center_group_holds_info_label(self, qapp, host):
        _, bar = host
        info = QLabel("测试信息")
        lead = _icon_btn("搜索")
        trail = _icon_btn("缩放")
        bar.add_leading(lead)
        bar.add_trailing(trail)
        bar.set_info_widget(info)
        process_qt_events(qapp, ms=30)
        assert bar._info_widget is info
        assert info.parent() is not None


class TestOverflowFold:
    def test_fold_and_restore(self, qapp, host):
        _, bar = host
        wide = _icon_btn("编码")   # 模拟较宽控件（如编码下拉 110px）
        wide.setFixedWidth(110)
        b1 = _icon_btn("搜索")
        b2 = _icon_btn("换行")
        b3 = _icon_btn("AI")
        b4 = _icon_btn("缩放")
        bar.add_left(_icon_btn("目录"))
        bar.add_right(_icon_btn("全屏"))
        bar.add_leading(wide)
        for w in (b1,):
            bar.add_leading(w)
        for w in (b2, b3, b4):
            bar.add_trailing(w)
        bar.set_overflow_priority([b1, b2, b3, b4, wide])
        process_qt_events(qapp, ms=30)

        avail_wide = bar.info_available_width()
        assert not any(w.isHidden() for w in (b1, b2, b3, b4, wide))
        assert bar._more_btn.isHidden()

        # 缩窄 → 按优先级折叠（b1/b2/b3 收起，b4 与较宽的 wide 保留）
        _resize_bar(qapp, bar, 300)
        assert b1.isHidden() and b2.isHidden() and b3.isHidden()
        assert not b4.isHidden()
        assert not wide.isHidden()
        assert not bar._more_btn.isHidden()
        assert bar.info_available_width() < avail_wide

        # 恢复 → 全部展开
        _resize_bar(qapp, bar, 1000)
        assert not any(w.isHidden() for w in (b1, b2, b3, b4, wide))
        assert bar._more_btn.isHidden()

    def test_more_menu_invokes_original_action(self, qapp, host):
        _, bar = host
        clicked: list[str] = []

        def make(tip: str, key: str) -> StyledButton:
            btn = _icon_btn(tip)
            btn.clicked.connect(lambda k=key: clicked.append(k))
            return btn

        b1 = make("搜索", "search")
        b2 = make("换行", "wrap")
        b3 = make("AI", "ai")
        for w in (b1, b2, b3):
            bar.add_trailing(w)
        bar.set_overflow_priority([b1, b2, b3])
        process_qt_events(qapp, ms=30)

        _resize_bar(qapp, bar, 64)
        folded = list(bar._folded)
        assert len(folded) == 3, "极窄时应全部折叠进「更多」菜单"
        # 「更多」菜单中每个折叠项都有可读文案与回调触发
        for widget in folded:
            assert bar._menu_label(widget)
            bar._invoke(widget)
        process_qt_events(qapp, ms=30)
        assert len(clicked) == 3, "菜单项应触发原按钮行为"


class TestTextStatsRemoved:
    """顶栏不再显示字数/行数（统计仅保留在信息面板的详细信息中）。"""

    def test_stats_label_absent(self, qapp):
        layout = TextPreviewerLayout(dpi_scale=1.0, standalone=False)
        assert not hasattr(layout, "_title_label")
        assert not hasattr(layout, "_update_stats")
        assert layout._top_bar._info_widget is None
        layout.deleteLater()


class TestGroupCentered:
    """功能区作为一个整体水平居中（不再用平衡占位把标签单独居中）。"""

    def test_group_center_on_wide_bar(self, qapp, host):
        _, bar = host
        b1 = _icon_btn("编码")
        b1.setFixedWidth(110)
        b2 = _icon_btn("搜索")
        b3 = _icon_btn("AI")
        b4 = _icon_btn("缩放")
        info = QLabel("123字 · 4行")
        bar.add_left(_icon_btn("目录"))
        bar.add_right(_icon_btn("全屏"))
        for w in (b1, b2):
            bar.add_leading(w)
        for w in (b3, b4):
            bar.add_trailing(w)
        bar.set_info_widget(info)
        bar.set_overflow_priority([b1, b2, b3, b4])
        process_qt_events(qapp, ms=30)

        _resize_bar(qapp, bar, 1000)
        # 整组内容（lead…trail 可见跨度）的几何中心应贴近顶栏中心
        assert not any(w.isHidden() for w in (b1, b2, b3, b4))
        left_x = bar._lead_box.x()
        right_x = bar._trail_box.geometry().right()
        group_mid = (left_x + right_x) / 2.0
        assert abs(group_mid - bar.width() / 2.0) <= 3, (
            f"group_mid={group_mid}, bar_center={bar.width() / 2.0}"
        )


class TestEncodingComboFormatLabel:
    """编码下拉：默认“格式▾”（无框、贴字箭头、居中），手动选择后双行居中对齐"""

    def test_title_only_initial_and_manual_state(self, qapp):
        layout = TextPreviewerLayout(dpi_scale=1.0, standalone=False)
        combo = layout._encoding_combo
        assert combo._title == "格式"
        assert combo.flat is True
        assert combo.height() == 36  # 双行标题模式高度适配 48px 顶栏
        assert combo._current_index == 0
        # 初始默认预览态：仅显示“格式”，窄宽度
        assert combo.showing_title_only() is True
        assert combo._chevron_gap() <= 8  # 箭头与文字为正常间距
        default_w = combo.content_width()
        assert 40 <= default_w <= 130

        # 用户手动再选“自动识别”→ 不退回单行，改双行“格式 / 自动识别”
        combo._on_item_selected(0)
        layout._update_encoding_combo_width()
        assert combo.showing_title_only() is False
        assert combo.width() == combo.content_width()

        # 切换到其它编码仍是双行
        combo._on_item_selected(1)
        layout._update_encoding_combo_width()
        assert combo.showing_title_only() is False
        assert combo.currentText() != "自动识别"
        assert combo.width() == combo.content_width()

        # 切换新文件 → 恢复初始默认的单行“格式”态
        combo.setCurrentIndex(0)
        combo.reset_title_only()
        layout._update_encoding_combo_width()
        assert combo.showing_title_only() is True
        assert combo.width() == default_w

        layout.deleteLater()

    def test_combo_without_title_keeps_single_row(self, qapp):
        from freeassetfilter.ui.components.styled_combobox import StyledComboBox

        combo = StyledComboBox(items=["Regular", "Bold"], size="sm")
        assert combo._title == ""
        assert combo.height() == 30
        combo.deleteLater()


class TestTextNoWrapButton:
    """换行切换按钮已移除，源码视图默认（固定）自动换行。"""

    def test_no_wrap_button_and_default_wrap(self, qapp):
        layout = TextPreviewerLayout(dpi_scale=1.0, standalone=False)
        assert not hasattr(layout, "_wrap_btn")
        assert not hasattr(layout, "_on_word_wrap_toggle")
        source = layout._source_view._text_edit
        from PySide6.QtWidgets import QTextEdit

        assert source.lineWrapMode() == QTextEdit.WidgetWidth
        layout.deleteLater()
