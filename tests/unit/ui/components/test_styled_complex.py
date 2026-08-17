# -*- coding: utf-8 -*-
"""styled_* 复杂组件单元测试（todo-22 批 2 / task-22）。

覆盖 ui/components 下 18 个"复杂"styled_* / 复合组件模块的构造契约、
属性/信号断言与纯函数行为。设计约束与 test_styled_basic.py 一致：全部
离屏、QWidget 测试显式依赖 session 级 qapp fixture、只断言源码与离屏
探针确认过的 API surface、不弹真实窗口、不做像素级比对。

验证命令：
    python -m pytest tests/unit/ui/ -k "test_styled_complex" --timeout 30 -q
"""

# targets: ui.components.styled_accordion, ui.components.styled_carousel,
#          ui.components.styled_cascader, ui.components.styled_date_picker,
#          ui.components.styled_file_picker, ui.components.styled_music_info_panel,
#          ui.components.styled_pagination, ui.components.styled_player_bar,
#          ui.components.styled_sidebar, ui.components.styled_table,
#          ui.components.styled_tabs, ui.components.styled_timeline,
#          ui.components.settings_card, ui.components.icon_utils,
#          ui.components.paint_utils, ui.components.mica_material,
#          ui.components.mica_window, ui.components.theme_transition_overlay

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QEnterEvent, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

# 组件模块内部使用短路径导入（from theme import tm / components.*），
# 要求 freeassetfilter/ui 位于 sys.path；与 tests/unit/ui/layout 下
# test_layouts.py 的 bootstrap 方式保持一致。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from tests.support.qt_helpers import safe_teardown  # noqa: E402

from freeassetfilter.ui.components.icon_utils import icon_path, render_icon  # noqa: E402
from freeassetfilter.ui.components.mica_material import MicaMaterial, MicaWidget  # noqa: E402
from freeassetfilter.ui.components.mica_window import MicaWindow  # noqa: E402
from freeassetfilter.ui.components.paint_utils import (  # noqa: E402
    draw_capsule,
    draw_checkmark,
    draw_chevron,
    draw_circle,
    draw_dashed_line,
    draw_rounded_rect,
)
from freeassetfilter.ui.components.settings_card import (  # noqa: E402
    NotificationRow,
    PluginItem,
    SettingsCard,
    SettingsRow,
)
from freeassetfilter.ui.components.styled_accordion import (  # noqa: E402
    StyledAccordion,
    StyledAccordionItem,
)
from freeassetfilter.ui.components.styled_carousel import StyledCarousel  # noqa: E402
from freeassetfilter.ui.components.styled_cascader import StyledCascader  # noqa: E402
from freeassetfilter.ui.components.styled_date_picker import (  # noqa: E402
    StyledDatePicker,
    StyledTimePicker,
)
from freeassetfilter.ui.components.styled_file_picker import (  # noqa: E402
    StyledFileDropZone,
    StyledFilePicker,
)
from freeassetfilter.ui.components.styled_music_info_panel import (  # noqa: E402
    StyledMusicInfoPanel,
)
from freeassetfilter.ui.components.styled_pagination import StyledPagination  # noqa: E402
from freeassetfilter.ui.components.styled_player_bar import StyledPlayerBar  # noqa: E402
from freeassetfilter.ui.components.styled_sidebar import (  # noqa: E402
    AnimatedHighlightBar,
    ContentScrollBar,
    SidebarIconWidget,
    SidebarItem,
    SidebarScrollBar,
    StyledSidebar,
)
from freeassetfilter.ui.components.styled_table import (  # noqa: E402
    StatusBadgeDelegate,
    StyledTable,
)
from freeassetfilter.ui.components.styled_tabs import StyledTabWidget  # noqa: E402
from freeassetfilter.ui.components.styled_timeline import StyledTimeline  # noqa: E402
from freeassetfilter.ui.components.theme_transition_overlay import (  # noqa: E402
    ThemeTransitionOverlay,
)

pytestmark = pytest.mark.unit


def _make_capture(signal: Any) -> list:
    """返回一个可 append 的信号捕获列表，用于同步信号断言。

    Args:
        signal: Qt 信号对象。

    Returns:
        list: 收集信号发射的实参列表（每次发射 append 一个 tuple）。
    """
    received: list = []

    def _on_signal(*args: Any) -> None:
        received.append(args)

    signal.connect(_on_signal)
    return received


# =============================================================================
# ui.components.styled_accordion
# =============================================================================
class TestStyledAccordion:
    """StyledAccordion：多开/单开模式、分区信号与禁用项。"""

    def test_construct_and_add_item(self, qapp: QApplication) -> None:
        """默认构造 + add_item 返回 StyledAccordionItem。"""
        acc = StyledAccordion()
        item = acc.add_item("Section 1")
        assert isinstance(item, StyledAccordionItem)
        assert item.is_open is False
        assert acc.accordion_mode is True
        assert acc.bordered is False
        safe_teardown(acc)

    def test_accordion_mode_single_open(self, qapp: QApplication) -> None:
        """单开模式下打开新项会关闭其他项。"""
        acc = StyledAccordion()
        a = acc.add_item("A")
        b = acc.add_item("B")
        a.is_open = True
        b.is_open = True
        assert b.is_open is True
        assert a.is_open is False  # single-open: A 被 B 关闭
        safe_teardown(acc)

    def test_accordion_mode_false_allows_multi_open(self, qapp: QApplication) -> None:
        """accordion_mode=False 时允许同时打开多项。"""
        acc = StyledAccordion()
        acc.accordion_mode = False
        a = acc.add_item("A")
        b = acc.add_item("B")
        a.is_open = True
        b.is_open = True
        assert a.is_open is True
        assert b.is_open is True
        safe_teardown(acc)

    def test_section_toggled_signal(self, qapp: QApplication) -> None:
        """打开分区时发射 section_toggled(index, True)。"""
        acc = StyledAccordion()
        acc.add_item("A")
        received = _make_capture(acc.section_toggled)
        acc.add_item("B").set_open_no_anim(True)
        # add_item 之后再 set_open_no_anim 不触发 toggled（无动画直设）
        assert [r for r in received if r[0] == 1 and r[1] is True] == []
        # 通过 is_open 属性设置会 emit
        acc._items[0].is_open = True
        assert any(r[0] == 0 and r[1] is True for r in received)
        safe_teardown(acc)

    def test_disabled_item_ignores_click(self, qapp: QApplication) -> None:
        """disabled 项 enabled=False 且 is_open 仍可程序化设置。"""
        acc = StyledAccordion()
        item = acc.add_item("D", disabled=True)
        assert item.enabled is False
        item.is_open = True
        assert item.is_open is True
        safe_teardown(acc)

    def test_item_toggle_and_set_content_widget(self, qapp: QApplication) -> None:
        """StyledAccordionItem：set_content_widget / toggled 信号往返。"""
        acc = StyledAccordion()
        item = acc.add_item("E")
        item.set_content_widget(QLabel("body"))
        received = _make_capture(item.toggled)
        item.toggle()
        assert received[-1] == (True,)
        item.toggle()
        assert received[-1] == (False,)
        safe_teardown(acc)


# =============================================================================
# ui.components.styled_carousel
# =============================================================================
class TestStyledCarousel:
    """StyledCarousel：幻灯片增删、切换与自动播放开关。"""

    def test_construct_and_add_slide(self, qapp: QApplication) -> None:
        """默认构造 + add_slide 返回递增索引。"""
        car = StyledCarousel()
        assert car.add_slide(QLabel("s1")) == 0
        assert car.add_slide(QLabel("s2")) == 1
        assert car.current_index == 0
        safe_teardown(car)

    def _narrow_carousel(self, car: StyledCarousel) -> None:
        """把 carousel 连同其 viewport 压到 0 宽，迫使走同步 _done 路径。

        离屏测试无事件循环，500ms 动画永不 _finish 会把 _anim 卡在 True；
        set_current_index 中 `w = _vp.width()`，0 宽时同步 emit slide_changed。
        注意仅 resize carousel 不会联动 _vp（无 resizeEvent 布局），需直接压 _vp。
        """
        car.resize(0, 200)
        car._vp.resize(0, 200)

    def test_current_index_and_switch(self, qapp: QApplication) -> None:
        """set_current_index 同步更新 current_index 并发射 slide_changed。"""
        car = StyledCarousel()
        car.add_slide(QLabel("s1"))
        car.add_slide(QLabel("s2"))
        self._narrow_carousel(car)
        received = _make_capture(car.slide_changed)
        car.set_current_index(1)
        assert car.current_index == 1
        assert received[-1] == (1,)
        safe_teardown(car)

    def test_next_prev_wrap(self, qapp: QApplication) -> None:
        """next/prev 在边界处回绕（2 张：0→1→0→1→0）。"""
        car = StyledCarousel()
        car.add_slide(QLabel("s1"))
        car.add_slide(QLabel("s2"))
        self._narrow_carousel(car)
        car.next()
        assert car.current_index == 1
        car.next()  # 回绕到第一张
        assert car.current_index == 0
        car.prev()  # 回绕到最后一张
        assert car.current_index == 1
        car.prev()
        assert car.current_index == 0
        safe_teardown(car)

    def test_set_current_index_clamped(self, qapp: QApplication) -> None:
        """越界 set_current_index 被夹紧到 [0, len-1]。"""
        car = StyledCarousel()
        car.add_slide(QLabel("s1"))
        car.add_slide(QLabel("s2"))
        self._narrow_carousel(car)
        car.set_current_index(99)
        assert car.current_index == 1
        safe_teardown(car)

    def test_autoplay_toggle(self, qapp: QApplication) -> None:
        """start_autoplay/stop_autoplay 切换 autoplay_enabled。"""
        car = StyledCarousel(autoplay_interval=1000)
        car.add_slide(QLabel("s1"))
        car.add_slide(QLabel("s2"))
        assert car.autoplay_enabled is False
        car.start_autoplay()
        assert car.autoplay_enabled is True
        car.stop_autoplay()
        assert car.autoplay_enabled is False
        safe_teardown(car)


# =============================================================================
# ui.components.styled_cascader
# =============================================================================
class TestStyledCascader:
    """StyledCascader：数据设置、路径选择与文本/路径访问。"""

    _DATA = [
        {"label": "A", "value": "a", "children": [{"label": "A1", "value": "a1"}]},
        {"label": "B", "value": "b"},
    ]

    def test_construct_and_set_data(self, qapp: QApplication) -> None:
        """默认构造 + setData 不抛异常，当前路径为空。"""
        cas = StyledCascader()
        cas.setData(self._DATA)
        assert cas.currentPath() == []
        assert cas.currentText() == ""
        safe_teardown(cas)

    def test_set_selected_path(self, qapp: QApplication) -> None:
        """setSelectedPath 更新 currentPath/currentText 并发射 path_changed。"""
        cas = StyledCascader(data=self._DATA)
        received = _make_capture(cas.path_changed)
        path = [{"label": "A", "value": "a"}, {"label": "A1", "value": "a1"}]
        cas.setSelectedPath(path)
        assert cas.currentPath() == path
        assert cas.currentText() == "A / A1"
        assert received[-1][0] == path
        safe_teardown(cas)

    def test_ctor_with_data(self, qapp: QApplication) -> None:
        """构造即传入 data 可用。"""
        cas = StyledCascader(data=self._DATA)
        assert cas.currentPath() == []
        safe_teardown(cas)


# =============================================================================
# ui.components.styled_date_picker
# =============================================================================
class TestStyledDatePicker:
    """StyledDatePicker：日期/范围访问与面板开关。"""

    def test_construct_default(self, qapp: QApplication) -> None:
        """默认构造不抛，初始 date 为空串。"""
        dp = StyledDatePicker()
        assert dp.date == ""
        assert dp.enabled is True
        safe_teardown(dp)

    def test_construct_with_date(self, qapp: QApplication) -> None:
        """传入 date 后 date 属性可读回。"""
        dp = StyledDatePicker(date="2024-01-15")
        assert dp.date == "2024-01-15"
        safe_teardown(dp)

    def test_set_range(self, qapp: QApplication) -> None:
        """set_range 更新 range_start/range_end（不发射信号——信号仅面板交互触发）。"""
        dp = StyledDatePicker(is_range=True)
        dp.set_range("2024-01-01", "2024-01-31")
        assert dp.range_start == "2024-01-01"
        assert dp.range_end == "2024-01-31"
        safe_teardown(dp)

    def test_close_panel_safe(self, qapp: QApplication) -> None:
        """未打开面板时 close_panel 不抛异常。"""
        dp = StyledDatePicker()
        dp.close_panel()
        safe_teardown(dp)

    def test_enabled_setter(self, qapp: QApplication) -> None:
        """enabled 属性可写。"""
        dp = StyledDatePicker(enabled=True)
        dp.enabled = False
        assert dp.enabled is False
        safe_teardown(dp)


# =============================================================================
# ui.components.styled_file_picker
# =============================================================================
class TestStyledFilePicker:
    """StyledFilePicker / StyledFileDropZone：路径/模式/尺寸与拖拽区文案。"""

    def test_construct(self, qapp: QApplication) -> None:
        """默认构造，path/mode/size_variant 读回。"""
        picker = StyledFilePicker()
        assert picker.path == ""
        assert picker.mode == "file"
        assert picker.size_variant == "default"
        assert picker.error is False
        safe_teardown(picker)

    def test_path_setter(self, qapp: QApplication) -> None:
        """path 属性可写。"""
        picker = StyledFilePicker()
        picker.path = r"C:\demo\file.png"
        assert picker.path == r"C:\demo\file.png"
        safe_teardown(picker)

    def test_mode_and_error(self, qapp: QApplication) -> None:
        """mode/error setter 生效。"""
        picker = StyledFilePicker(mode="file")
        picker.mode = "folder"
        assert picker.mode == "folder"
        picker.error = True
        assert picker.error is True
        safe_teardown(picker)

    def test_drop_zone_text_and_hint(self, qapp: QApplication) -> None:
        """StyledFileDropZone 默认文案与 setter。"""
        zone = StyledFileDropZone()
        assert zone.text == "拖拽文件到此处"
        assert zone.hint == "或点击选择文件"
        zone.text = "放到这里"
        zone.hint = "提示"
        assert zone.text == "放到这里"
        assert zone.hint == "提示"
        safe_teardown(zone)


# =============================================================================
# ui.components.styled_music_info_panel
# =============================================================================
class TestStyledMusicInfoPanel:
    """StyledMusicInfoPanel：标题/歌手/封面的设置与清除。"""

    def test_construct_and_clear(self, qapp: QApplication) -> None:
        """默认构造 + clear 不抛异常。"""
        panel = StyledMusicInfoPanel()
        panel.clear()
        safe_teardown(panel)

    def test_set_title_artist(self, qapp: QApplication) -> None:
        """set_title / set_artist 不抛异常。"""
        panel = StyledMusicInfoPanel()
        panel.set_title("My Song")
        panel.set_artist("An Artist")
        safe_teardown(panel)

    def test_set_cover_pixmap(self, qapp: QApplication) -> None:
        """set_cover_pixmap 接受 QPixmap / None，placeholder 可重载。"""
        panel = StyledMusicInfoPanel()
        pm = QPixmap(32, 32)
        pm.fill(QColor("#336699"))
        panel.set_cover_pixmap(pm)
        panel.set_cover_pixmap(None)
        panel.set_placeholder()
        safe_teardown(panel)


# =============================================================================
# ui.components.styled_pagination
# =============================================================================
class TestStyledPagination:
    """StyledPagination：页码/总页数/每页条数与信号。"""

    def test_construct_default(self, qapp: QApplication) -> None:
        """默认构造：1 页、当前页 1、每页 10 条。"""
        pg = StyledPagination()
        assert pg.current_page == 1
        assert pg.total_pages == 1
        assert pg.page_size == 10
        safe_teardown(pg)

    def test_current_page_setter_emits(self, qapp: QApplication) -> None:
        """current_page 属性 setter 越界夹紧并发射 page_changed。"""
        pg = StyledPagination(total_pages=5, current_page=2)
        received = _make_capture(pg.page_changed)
        pg.current_page = 9
        assert pg.current_page == 5  # clamped
        assert received[-1] == (5,)
        safe_teardown(pg)

    def test_total_pages_setter(self, qapp: QApplication) -> None:
        """total_pages setter 更新数量。"""
        pg = StyledPagination(total_pages=3)
        pg.total_pages = 8
        assert pg.total_pages == 8
        safe_teardown(pg)

    def test_page_size_setter(self, qapp: QApplication) -> None:
        """page_size setter 仅接受 PAGE_SIZE_OPTIONS 内的值。"""
        pg = StyledPagination()
        pg.page_size = 50
        assert pg.page_size == 50
        pg.page_size = 7  # 非法值被忽略
        assert pg.page_size == 50
        safe_teardown(pg)

    def test_show_info_and_size_selector(self, qapp: QApplication) -> None:
        """show_info / show_size_selector 属性可写。"""
        pg = StyledPagination(show_info=True, show_size_selector=True)
        pg.show_info = False
        pg.show_size_selector = False
        assert pg.show_info is False
        assert pg.show_size_selector is False
        safe_teardown(pg)

    def test_page_size_changed_via_combo(self, qapp: QApplication) -> None:
        """size selector 变更触发 page_size_changed。"""
        pg = StyledPagination()
        received = _make_capture(pg.page_size_changed)
        pg._size_combo.setCurrentText("20")
        assert received[-1] == (20,)
        assert pg.page_size == 20
        safe_teardown(pg)


# =============================================================================
# ui.components.styled_player_bar
# =============================================================================
class TestStyledPlayerBar:
    """StyledPlayerBar：构造契约与公开 setter 冒烟测试。"""

    def test_construct_default(self, qapp: QApplication) -> None:
        """默认构造不抛异常。"""
        bar = StyledPlayerBar()
        safe_teardown(bar)

    def test_construct_with_params(self, qapp: QApplication) -> None:
        """带初始参数构造不抛异常。"""
        bar = StyledPlayerBar(
            current_time="01:23",
            total_time="05:00",
            progress=0.5,
            volume=0.5,
            muted=True,
            current_speed="1.5x",
            playing=True,
        )
        safe_teardown(bar)

    def test_setters_smoke(self, qapp: QApplication) -> None:
        """公开 setter 全部调用不抛异常。"""
        bar = StyledPlayerBar()
        bar.set_current_time("01:00")
        bar.set_total_time("04:00")
        bar.set_progress(0.25)
        bar.set_volume(0.8)
        bar.set_muted(True)
        bar.set_audio_tracks([{"id": "a1", "label": "中文"}])
        bar.set_subtitle_tracks([{"id": "s1", "label": "English"}])
        bar.set_speed("2.0x")
        bar.set_playing(True)
        bar.set_fullscreen(True)
        bar.show_osd("test message")
        bar.show_seek_osd(10.0, 100.0, "forward")
        safe_teardown(bar)

    def test_signals_exist(self, qapp: QApplication) -> None:
        """关键信号可按名访问（连接不抛异常）。"""
        bar = StyledPlayerBar()
        for sig in (
            bar.play_paused,
            bar.progress_changed,
            bar.volume_changed,
            bar.mute_changed,
            bar.speed_changed,
            bar.fullscreen_toggled,
            bar.setting_changed,
            bar.add_subtitle_requested,
        ):
            _make_capture(sig)
        safe_teardown(bar)


# =============================================================================
# ui.components.styled_sidebar
# =============================================================================
class TestStyledSidebar:
    """StyledSidebar：条目添加、激活切换与 compact 模式。"""

    def test_construct(self, qapp: QApplication) -> None:
        """默认构造 + add_item 返回条目并默认激活首个。"""
        sb = StyledSidebar(title="Nav")
        received = _make_capture(sb.item_selected)
        item = sb.add_item("Home", icon_svg="chevron_right")
        assert item is not None
        # 首个条目自动激活，但不发射 item_selected（构造期不 emit）
        assert received == []
        safe_teardown(sb)

    def test_compact_width(self, qapp: QApplication) -> None:
        """compact=True 时初始宽度为 COMPACT_WIDTH。"""
        sb = StyledSidebar(title="Nav", width=220, compact=True)
        assert sb.width() == StyledSidebar.COMPACT_WIDTH
        safe_teardown(sb)

    def test_set_compact(self, qapp: QApplication) -> None:
        """set_compact 不抛异常（动画异步生效）。"""
        sb = StyledSidebar(title="Nav", width=220)
        sb.add_item("Home", icon_svg="chevron_right")
        sb.set_compact(True)
        sb.set_compact(False)
        safe_teardown(sb)


# =============================================================================
# ui.components.styled_table
# =============================================================================
class TestStyledTable:
    """StyledTable：列/数据设置、行数据读取与选择行为。"""

    _COLUMNS = [
        {"label": "名称", "key": "name", "width": 200},
        {"label": "状态", "key": "status", "width": 120, "type": "status"},
    ]

    _DATA = [
        {"name": "a.png", "status": "ok"},
        {"name": "b.png", "status": "warn"},
    ]

    def test_construct_and_set_columns_data(self, qapp: QApplication) -> None:
        """构造即传 columns/data 并读取 table_data。"""
        table = StyledTable(columns=self._COLUMNS, data=self._DATA)
        assert table.table_data == self._DATA
        safe_teardown(table)

    def test_set_columns_data_after_ctor(self, qapp: QApplication) -> None:
        """迟到 set_columns/set_data 生效。"""
        table = StyledTable()
        table.set_columns(self._COLUMNS)
        table.set_data(self._DATA)
        assert table.table_data == self._DATA
        safe_teardown(table)

    def test_selection_behavior(self, qapp: QApplication) -> None:
        """行选择行为为 SelectRows。"""
        table = StyledTable(columns=self._COLUMNS, data=self._DATA)
        assert table.selectionBehavior() == table.SelectionBehavior.SelectRows
        safe_teardown(table)

    def test_signals_dispatched(self, qapp: QApplication) -> None:
        """row_selected / cell_clicked 信号存在并可连接。"""
        table = StyledTable(columns=self._COLUMNS, data=self._DATA)
        _make_capture(table.row_selected)
        _make_capture(table.cell_clicked)
        safe_teardown(table)


# =============================================================================
# ui.components.styled_tabs
# =============================================================================
class TestStyledTabWidget:
    """StyledTabWidget：标签增删、切换、禁用与计数。"""

    def test_add_tab_and_count(self, qapp: QApplication) -> None:
        """add_tab 返回索引，tab_count 对应。"""
        tabs = StyledTabWidget()
        assert tabs.add_tab("A", QLabel("pageA")) == 0
        assert tabs.add_tab("B", QLabel("pageB")) == 1
        assert tabs.tab_count() == 2
        safe_teardown(tabs)

    def test_set_current_index(self, qapp: QApplication) -> None:
        """set_current_index 更新 current_index 并发射 current_changed。"""
        tabs = StyledTabWidget()
        tabs.add_tab("A", QLabel("pageA"))
        tabs.add_tab("B", QLabel("pageB"))
        received = _make_capture(tabs.current_changed)
        tabs.set_current_index(1)
        assert tabs.current_index == 1
        assert received[-1] == (1,)
        safe_teardown(tabs)

    def test_disabled_tab_blocked(self, qapp: QApplication) -> None:
        """禁用 tab 无法被 set_current_index 选中。"""
        tabs = StyledTabWidget()
        tabs.add_tab("A", QLabel("pageA"))
        tabs.add_tab("B", QLabel("pageB"), disabled=True)
        tabs.set_current_index(1)
        assert tabs.current_index == 0  # disabled → 忽略
        safe_teardown(tabs)

    def test_set_tab_disabled(self, qapp: QApplication) -> None:
        """set_tab_disabled 动态禁用/启用。"""
        tabs = StyledTabWidget()
        tabs.add_tab("A", QLabel("pageA"))
        tabs.add_tab("B", QLabel("pageB"))
        tabs.set_tab_disabled(1, True)
        tabs.set_current_index(1)
        assert tabs.current_index == 0
        tabs.set_tab_disabled(1, False)
        tabs.set_current_index(1)
        assert tabs.current_index == 1
        safe_teardown(tabs)


# =============================================================================
# ui.components.styled_timeline
# =============================================================================
class TestStyledTimeline:
    """StyledTimeline：条目添加属性、读取与清空。"""

    def test_add_item_and_items(self, qapp: QApplication) -> None:
        """add_item 返回条目并进入 items 列表。"""
        tl = StyledTimeline()
        item = tl.add_item("Title", "Desc", time_str="2024-01-01", color="primary")
        assert item is not None
        assert len(tl.items) == 1
        safe_teardown(tl)

    def test_add_many_and_clear(self, qapp: QApplication) -> None:
        """多次 add_item 后 clear 清空。"""
        tl = StyledTimeline()
        for i in range(3):
            tl.add_item(f"Item {i}", size_variant="lg")
        assert len(tl.items) == 3
        tl.clear()
        assert tl.items == []
        safe_teardown(tl)

    def test_add_item_with_icon(self, qapp: QApplication) -> None:
        """带 icon 的条目不抛异常。"""
        tl = StyledTimeline()
        tl.add_item("Iconed", icon="bell", color="warning")
        safe_teardown(tl)


# =============================================================================
# ui.components.settings_card
# =============================================================================
class TestSettingsCard:
    """SettingsCard / 内部行组件：头部/主体/页脚与行控件。"""

    def test_construct_and_layout(self, qapp: QApplication) -> None:
        """add_header/add_body/add_footer 返回对应布局对象。"""
        card = SettingsCard()
        card.add_header("Title")
        body = card.add_body()
        footer = card.add_footer()
        assert isinstance(body, QVBoxLayout)
        assert body is not None
        assert footer is not None
        safe_teardown(card)

    def test_instance_count_increments(self, qapp: QApplication) -> None:
        """类级 _instance_count 递增，objectName 唯一。"""
        before = SettingsCard._instance_count
        c1 = SettingsCard()
        c2 = SettingsCard()
        assert SettingsCard._instance_count == before + 2
        assert c1.objectName() != c2.objectName()
        safe_teardown(c1)
        safe_teardown(c2)

    def test_variant_danger(self, qapp: QApplication) -> None:
        """danger 变体构造不抛。"""
        card = SettingsCard(variant="danger")
        safe_teardown(card)

    def test_settings_row_control(self, qapp: QApplication) -> None:
        """SettingsRow：构造 + set_control 放置控件。"""
        row = SettingsRow(title="标题", description="描述")
        btn = QPushButton("btn")
        row.set_control(btn)
        assert row.title_label is not None
        assert row.desc_label is not None
        assert row.control_layout.itemAt(0).widget() is btn
        safe_teardown(row)

    def test_notification_row_control(self, qapp: QApplication) -> None:
        """NotificationRow：构造 + set_control。"""
        row = NotificationRow(title="通知", description="desc", active=True)
        row.set_control(QLabel("x"))
        safe_teardown(row)

    def test_plugin_item_control(self, qapp: QApplication) -> None:
        """PluginItem：构造 + set_control。"""
        item = PluginItem(name="插件", description="描述")
        item.set_control(QLabel("x"))
        safe_teardown(item)


# =============================================================================
# ui.components.icon_utils
# =============================================================================
class TestIconUtils:
    """icon_utils：已知/未知图标路径与离屏渲染。"""

    def test_icon_path_known(self, qapp: QApplication) -> None:
        """已知图标名返回非空 QPainterPath。"""
        for name in ("chevron_right", "checkmark", "folder", "search", "close"):
            assert icon_path(name).isEmpty() is False

    def test_icon_path_unknown(self, qapp: QApplication) -> None:
        """未知图标名返回空 QPainterPath。"""
        assert icon_path("no_such_icon").isEmpty() is True

    def test_render_icon_smoke(self, qapp: QApplication) -> None:
        """render_icon 在离屏 QPainter 上执行不抛异常。"""
        pm = QPixmap(48, 48)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        try:
            render_icon(painter, "chevron_right", QRectF(0, 0, 48, 48), QColor("#ffffff"))
        finally:
            painter.end()


# =============================================================================
# ui.components.paint_utils
# =============================================================================
class TestPaintUtils:
    """paint_utils：全部绘图像元在离屏 QPainter 上执行不抛异常。"""

    def _new_painter(self) -> tuple[QPixmap, QPainter]:
        """创建 64x64 透明离屏画布。

        Returns:
            tuple[QPixmap, QPainter]: 画布与画笔。
        """
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        return pm, QPainter(pm)

    def test_draw_capsule(self, qapp: QApplication) -> None:
        pm, p = self._new_painter()
        try:
            draw_capsule(p, QRectF(4, 4, 56, 24), QColor("#336699"))
        finally:
            p.end()

    def test_draw_circle(self, qapp: QApplication) -> None:
        pm, p = self._new_painter()
        try:
            draw_circle(p, 32, 32, 16, border_color=QColor("#ffffff"), fill_color=QColor("#336699"))
        finally:
            p.end()

    def test_draw_checkmark(self, qapp: QApplication) -> None:
        pm, p = self._new_painter()
        try:
            draw_checkmark(p, QRectF(8, 8, 48, 48), QColor("#ffffff"))
        finally:
            p.end()

    def test_draw_rounded_rect(self, qapp: QApplication) -> None:
        pm, p = self._new_painter()
        try:
            draw_rounded_rect(
                p, QRectF(4, 4, 56, 56), 8,
                border=QColor("#ffffff"), fill=QColor("#336699"),
            )
        finally:
            p.end()

    def test_draw_chevron_directions(self, qapp: QApplication) -> None:
        pm, p = self._new_painter()
        try:
            for direction in ("right", "left", "up", "down", "bogus"):
                draw_chevron(p, QRectF(8, 8, 48, 48), QColor("#ffffff"), direction=direction)
        finally:
            p.end()

    def test_draw_dashed_line(self, qapp: QApplication) -> None:
        pm, p = self._new_painter()
        try:
            draw_dashed_line(p, 4, 32, 60, 32, QColor("#ffffff"))
        finally:
            p.end()


# =============================================================================
# ui.components.mica_material
# =============================================================================
class TestMicaMaterial:
    """MicaMaterial：延迟构造、焦点白名单与清理。"""

    def test_construct_lazy_and_dispose(self, qapp: QApplication) -> None:
        """lazy=True 构造 + dispose 安全清理。"""
        host = QWidget()
        mica = MicaMaterial(host, lazy=True)
        assert mica is not None
        mica.dispose()
        safe_teardown(host)

    def test_set_active(self, qapp: QApplication) -> None:
        """set_active 切换不抛异常。"""
        host = QWidget()
        mica = MicaMaterial(host, lazy=True)
        mica.set_active(False)
        mica.set_active(True)
        mica.dispose()
        safe_teardown(host)

    def test_focus_whitelist(self, qapp: QApplication) -> None:
        """add/remove_focus_whitelist 往返不抛异常。"""
        host = QWidget()
        mica = MicaMaterial(host, lazy=True)
        other = QWidget()
        mica.add_focus_whitelist(other)
        mica.remove_focus_whitelist(other)
        mica.dispose()
        safe_teardown(host)
        safe_teardown(other)

    def test_refresh_on_lazy_safe(self, qapp: QApplication) -> None:
        """lazy 实例显式 refresh 不抛异常（壁纸缺失时优雅返回）。"""
        host = QWidget()
        mica = MicaMaterial(host, lazy=True)
        mica.refresh()
        mica.dispose()
        safe_teardown(host)


# =============================================================================
# ui.components.mica_window
# =============================================================================
class TestMicaWindow:
    """MicaWindow：构造、mica 属性与刷新入口。"""

    def test_construct_and_content_layout(self, qapp: QApplication) -> None:
        """默认构造，content_layout 初始为 None（未设置布局）。"""
        win = MicaWindow()
        assert win.mica is not None
        assert win.mica.__class__.__name__ == "MicaMaterial"
        assert win.content_layout is None
        safe_teardown(win)

    def test_construct_with_title(self, qapp: QApplication) -> None:
        """带窗口标题构造。"""
        win = MicaWindow(window_title="Test")
        assert win.windowTitle() == "Test"
        safe_teardown(win)

    def test_refresh_background(self, qapp: QApplication) -> None:
        """refresh_background 调用不抛异常。"""
        win = MicaWindow()
        win.refresh_background()
        safe_teardown(win)


# =============================================================================
# ui.components.theme_transition_overlay
# =============================================================================
class TestThemeTransitionOverlay:
    """ThemeTransitionOverlay：构造、classmethod 与 start。"""

    def test_construct_and_start(self, qapp: QApplication) -> None:
        """构造 + start 不抛异常，默认时长 300ms。"""
        parent = QWidget()
        snapshot = QPixmap(100, 100)
        overlay = ThemeTransitionOverlay(parent, snapshot)
        assert overlay.DEFAULT_DURATION_MS == 300
        overlay.start()
        safe_teardown(overlay)
        safe_teardown(parent)

    def test_duration_min_clamped(self, qapp: QApplication) -> None:
        """duration_ms 下限被钳到 50ms。"""
        parent = QWidget()
        overlay = ThemeTransitionOverlay(parent, QPixmap(10, 10), duration_ms=5)
        assert overlay._duration_ms >= 50
        safe_teardown(overlay)
        safe_teardown(parent)

    def test_from_widget(self, qapp: QApplication) -> None:
        """from_widget 从顶层窗口抓快照并构造 overlay。"""
        window = QWidget()
        window.resize(120, 80)
        overlay = ThemeTransitionOverlay.from_widget(window)
        assert isinstance(overlay, ThemeTransitionOverlay)
        safe_teardown(overlay)
        safe_teardown(window)


# =============================================================================
# ui.components.mica_material — MicaWidget
# =============================================================================
class TestMicaWidget:
    """MicaWidget：构造、mica 属性与交互入口。"""

    def test_construct_and_mica_property(self, qapp: QApplication) -> None:
        """默认构造后 mica 属性为非 None 的 MicaMaterial。"""
        widget = MicaWidget()
        assert widget.mica is not None
        assert widget.mica.__class__.__name__ == "MicaMaterial"
        safe_teardown(widget)

    def test_resize_and_move_safe(self, qapp: QApplication) -> None:
        """resizeEvent / moveEvent 触发 begin_interaction 不抛异常。"""
        widget = MicaWidget()
        widget.resize(200, 120)
        widget.move(50, 30)
        safe_teardown(widget)

    def test_paint_event_safe(self, qapp: QApplication) -> None:
        """paint 路径：render 到 pixmap 不抛异常（壁纸缺失优雅返回）。"""
        widget = MicaWidget()
        widget.resize(160, 90)
        pm = QPixmap(160, 90)
        pm.fill(QColor("#000000"))
        widget.render(pm)
        safe_teardown(widget)


# =============================================================================
# ui.components.styled_date_picker — StyledTimePicker
# =============================================================================
class TestStyledTimePicker:
    """StyledTimePicker：time/enabled 属性与面板生命周期入口。"""

    def test_construct_default(self, qapp: QApplication) -> None:
        """默认构造读回空 time、enabled=True。"""
        picker = StyledTimePicker()
        assert picker.time == ""
        assert picker.enabled is True
        safe_teardown(picker)

    def test_construct_with_time(self, qapp: QApplication) -> None:
        """传 time 后 time 属性读回。"""
        picker = StyledTimePicker(time="14:30", enabled=False)
        assert picker.time == "14:30"
        assert picker.enabled is False
        safe_teardown(picker)

    def test_time_setter_roundtrip(self, qapp: QApplication) -> None:
        """time setter 更新内部值并同步面板。"""
        picker = StyledTimePicker()
        picker.time = "09:05"
        assert picker.time == "09:05"
        assert picker._input.text == "09:05"
        safe_teardown(picker)

    def test_enabled_setter(self, qapp: QApplication) -> None:
        """enabled setter 同步输入禁用态。"""
        picker = StyledTimePicker(enabled=True)
        picker.enabled = False
        assert picker.enabled is False
        assert picker._input._disabled is True
        safe_teardown(picker)

    def test_close_and_hide_safe(self, qapp: QApplication) -> None:
        """closeEvent / hideEvent 路径安全（未打开面板时）。"""
        picker = StyledTimePicker()
        picker.hide()
        picker.close()
        safe_teardown(picker)


# =============================================================================
# ui.components.styled_table — StatusBadgeDelegate
# =============================================================================
class TestStatusBadgeDelegate:
    """StatusBadgeDelegate：构造、尺寸切换与状态色清单。"""

    def test_construct(self, qapp: QApplication) -> None:
        """默认构造后内部尺寸回退为 default。"""
        dlg = StatusBadgeDelegate()
        assert dlg._size == "default"
        safe_teardown(dlg)

    def test_set_size(self, qapp: QApplication) -> None:
        """set_size 接受合法值，非法值回退 default。"""
        dlg = StatusBadgeDelegate("sm")
        dlg.set_size("lg")
        assert dlg._size == "lg"
        dlg.set_size("bogus")
        assert dlg._size == "default"
        safe_teardown(dlg)

    def test_status_colors(self, qapp: QApplication) -> None:
        """状态色清单包含四类键。"""
        dlg = StatusBadgeDelegate()
        colors = dlg._get_get_status_colors()
        assert set(colors) >= {"active", "inactive", "error", "warning"}
        assert all(isinstance(c, QColor) for c in colors.values())
        safe_teardown(dlg)


# =============================================================================
# ui.components.styled_sidebar — 内部组件
# =============================================================================
class TestSidebarInternal:
    """styled_sidebar 内部组件：滚动条、图标、条目与高亮条。"""

    def test_sidebar_scrollbar(self, qapp: QApplication) -> None:
        """SidebarScrollBar：构造、sizeHint 与 hover 往返。"""
        bar = SidebarScrollBar()
        assert bar.sizeHint() == QSize(4, 100)
        bar.setRange(0, 100)
        bar.setPageStep(20)
        bar.enterEvent(QEnterEvent(QPointF(2, 2), QPointF(2, 2), QPointF(2, 2)))
        assert bar._hovered is True
        bar.leaveEvent(QEvent(QEvent.Leave))
        assert bar._hovered is False
        safe_teardown(bar)

    def test_content_scrollbar(self, qapp: QApplication) -> None:
        """ContentScrollBar：尺寸/hover/滑块定位。"""
        bar = ContentScrollBar()
        assert bar.sizeHint() == QSize(8, 100)
        assert bar.DEFAULT_WIDTH == 2.0
        assert bar.HOVER_WIDTH == 8.0
        bar.resize(8, 200)
        bar.setRange(0, 100)
        bar.setPageStep(20)
        assert bar._value_from_pos(20) >= 0
        bar.enterEvent(QEnterEvent(QPointF(4, 4), QPointF(4, 4), QPointF(4, 4)))
        assert bar._hovered is True
        bar.leaveEvent(QEvent(QEvent.Leave))
        assert bar._hovered is False
        safe_teardown(bar)

    def test_sidebar_icon_widget(self, qapp: QApplication) -> None:
        """SidebarIconWidget：构造、set_color 与离屏渲染。"""
        for icon in ("user", "gear", "keyboard", "bell", "plugins", "info", "collapse", "expand", "sun"):
            w = SidebarIconWidget(icon_name=icon)
            assert w._icon_name == icon
            w.set_color(QColor("#ff0000"))
            w.resize(20, 20)
            pm = QPixmap(20, 20)
            pm.fill(QColor("#000000"))
            w.render(pm)
            safe_teardown(w)

    def test_sidebar_item(self, qapp: QApplication) -> None:
        """SidebarItem：active/文本/图标/点击信号。"""
        item = SidebarItem(label="Home", icon_svg="user", active=False, badge="3")
        assert item.active is False
        item.active = True
        assert item.active is True
        item.set_label_text("Changed")
        item.set_icon("gear")
        item.set_label_opacity(0.5)
        item.ensure_opacity_effect()
        assert item._label_widget.text() == "Changed"
        safe_teardown(item)

    def test_sidebar_item_click_emits(self, qapp: QApplication) -> None:
        """SidebarItem 左键按下发射 clicked。"""
        item = SidebarItem(label="Home")
        received = _make_capture(item.clicked)
        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(10, 10),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        item.mousePressEvent(press)
        assert received == [()]
        safe_teardown(item)

    def test_animated_highlight_bar(self, qapp: QApplication) -> None:
        """AnimatedHighlightBar：坐标属性、geometry 与显隐。"""
        bar = AnimatedHighlightBar()
        assert bar.get_top_y() == 0.0
        bar.set_top_y(10.0)
        assert bar.get_top_y() == 10.0
        bar.set_bottom_y(80.0)
        assert bar.get_bottom_y() == 80.0
        assert bar.top_y == 10.0
        assert bar.bottom_y == 80.0
        bar.set_bar_geometry(5.0, 70.0)
        assert bar.get_top_y() == 5.0
        assert bar.get_bottom_y() == 70.0
        bar.show_bar()
        bar.hide_bar()
        pm = QPixmap(8, 100)
        pm.fill(QColor("#000000"))
        bar.resize(8, 100)
        bar.render(pm)
        safe_teardown(bar)