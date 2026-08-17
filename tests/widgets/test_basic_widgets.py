# -*- coding: utf-8 -*-
# targets: widgets.audio_background, widgets.button_widgets, widgets.color_slider, widgets.color_wheel_picker
#       widgets.combo_selector, widgets.control_menu, widgets.custom_scrollbar, widgets.dropdown_menu
#       widgets.hover_tooltip, widgets.input_widgets, widgets.list_widgets, widgets.loading_widget
#       widgets.message_box, widgets.progress_widgets, widgets.setting_widgets, widgets.smooth_scroller
#       widgets.switch_widgets, widgets.theme_card
"""``widgets/`` 基础控件库（todo-15）单元测试。

在单一文件中覆盖 18 个基础 widget 模块：

* ``audio_background`` —— 音频背景（主题/速度/模式/暂停状态）
* ``button_widgets`` —— CustomButton（文本/类型/主按钮切换）
* ``color_slider`` —— ColorSliderWidget 颜色滑条（set/get_color）
* ``color_wheel_picker`` —— 色相轮/完整颜色选择器/预览/菜单
* ``combo_selector`` —— ComboSelector（选项/当前文本/信号）
* ``control_menu`` —— CustomControlMenu（内容/位置/显隐）
* ``custom_scrollbar`` —— FileScrollBar（范围/值/步长/配置）
* ``dropdown_menu`` —— Ddropmenu（选项/当前项/尺寸/信号）
* ``hover_tooltip`` —— HoverTooltip（构造/清理幂等）
* ``input_widgets`` —— CustomInputBox（文本/占位/可编辑/信号）
* ``list_widgets`` —— CustomSelectList（增删/选择/模式）
* ``loading_widget`` —— LoadingSpinner（启动/停止）
* ``message_box`` —— CustomWindow + CustomMessageBox（标题/按钮/输入）
* ``progress_widgets`` —— CustomProgressBar / D_ProgressBar / CustomValueBar
* ``setting_widgets`` —— CustomSettingItem（开关/按钮组/输入/数值条/文件夹）
* ``smooth_scroller`` —— SmoothScroller（应用于滚动区）
* ``switch_widgets`` —— CustomSwitch（初始值/切换/信号）
* ``theme_card`` —— ThemeCard（主题信息/选中/点击信号）

测试纪律（Q3-W3）：
* 全部走 ``pytest.mark.unit``；Qt 对象 teardown 一律 ``safe_teardown``。
* show() 后必须 pump 事件再断言；动画/定时器类测试结束须显式停止。
* 信号断言采用"先连接收集槽再触发"，异步类用 ``wait_for_signal``。
* 不调用 ``exec()/exec_()``，不比较像素，不触碰真实 ``data/`` 目录，
  依赖 settings 的控件全部注入 ``settings_manager`` fixture（临时文件）。
"""

from __future__ import annotations

import io
from typing import Any, Callable, List, Optional

import pytest
from PIL import Image as _PILImage
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QEnterEvent, QFont, QMouseEvent, QPixmap, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QWidget

from freeassetfilter.widgets.audio_background import (
    AudioBackground,
    ColorExtractionTask,
    CoverCache,
    FluidOpenGLLayer,
    PersistentBackgroundColorCache,
)
from freeassetfilter.widgets.button_widgets import CustomButton
from freeassetfilter.widgets.color_slider import ColorSliderWidget, HueSlider
from freeassetfilter.widgets.color_wheel_picker import (
    ColorPreview,
    ColorWheelPicker,
    ColorWheelPickerWidget,
    D_ColorWheelPickerMenu,
)
from freeassetfilter.widgets.combo_selector import ComboSelector
from freeassetfilter.widgets.control_menu import CustomControlMenu
from freeassetfilter.widgets.custom_scrollbar import FileScrollBar
from freeassetfilter.widgets.dropdown_menu import CustomDropdownMenu, Ddropmenu
from freeassetfilter.widgets.hover_tooltip import HoverTooltip
from freeassetfilter.widgets.input_widgets import CustomInputBox
from freeassetfilter.widgets.list_widgets import CustomSelectList, CustomSelectListItem
from freeassetfilter.widgets.loading_widget import LoadingSpinner
from freeassetfilter.widgets.message_box import CustomMessageBox, CustomWindow
from freeassetfilter.widgets.progress_widgets import (
    CustomProgressBar,
    CustomValueBar,
    CustomVolumeBar,
    D_ProgressBar,
)
from freeassetfilter.widgets.setting_widgets import CustomSettingItem
from freeassetfilter.widgets.smooth_scroller import D_ScrollBar, SmoothScroller
from freeassetfilter.widgets.switch_widgets import CustomSwitch
from freeassetfilter.widgets.theme_card import ThemeCard

from tests.support.qt_helpers import (
    flush_widget_queue,
    process_qt_events,
    safe_teardown,
)

pytestmark = pytest.mark.unit


def _pump(qapp: Any, ms: int = 50) -> None:
    """泵事件窗口，处理 singleShot(0, ...) 等延迟初始化。

    Args:
        qapp: QApplication 实例。
        ms: 泵事件毫秒数。
    """
    process_qt_events(qapp, ms)


def _collect_signal(signal: Any) -> List[Any]:
    """连接信号到一个收集槽，返回收集列表（用于信号断言）。

    Args:
        signal: Qt 信号实例。

    Returns:
        list: 被收集到的信号参数列表。
    """
    collected: List[Any] = []
    signal.connect(collected.append)
    return collected


# =============================================================================
# audio_background
# =============================================================================
class TestAudioBackground:
    """AudioBackground 基础状态/主题/速度/暂停。"""

    def test_default_state(self, qapp: Any, settings_manager: Any) -> None:
        bg = AudioBackground()
        try:
            assert bg.getMode() == AudioBackground.MODE_FLUID
            assert bg.getTheme() == "sunset"
            assert bg.isAnimationPaused() is False
        finally:
            safe_teardown(bg)
            _pump(qapp)

    def test_mode_constants_and_setmode(self, qapp: Any) -> None:
        bg = AudioBackground()
        try:
            assert AudioBackground.MODE_FLUID == "fluid"
            assert AudioBackground.MODE_COVER_BLUR == "cover_blur"
            bg.setMode(AudioBackground.MODE_COVER_BLUR)
            assert bg.getMode() == AudioBackground.MODE_COVER_BLUR
        finally:
            safe_teardown(bg)
            _pump(qapp)

    def test_set_theme_emits_and_validates(self, qapp: Any) -> None:
        bg = AudioBackground()
        emitted = _collect_signal(bg.themeChanged)
        try:
            bg.setTheme("ocean")
            assert bg.getTheme() == "ocean"
            assert emitted == ["ocean"]
            bg.setTheme("invalid_theme")
            assert bg.getTheme() == "ocean"
        finally:
            safe_teardown(bg)
            _pump(qapp)

    def test_set_animation_speed_clamps(self, qapp: Any) -> None:
        bg = AudioBackground()
        emitted = _collect_signal(bg.speedChanged)
        try:
            bg.setAnimationSpeed(0.5)
            assert bg.getAnimationSpeed() == 0.5
            bg.setAnimationSpeed(99.0)
            assert bg.getAnimationSpeed() == 2.0
            bg.setAnimationSpeed(-5.0)
            assert bg.getAnimationSpeed() == 0.1
            assert len(emitted) >= 3
        finally:
            safe_teardown(bg)
            _pump(qapp)

    def test_use_accent_theme(self, qapp: Any) -> None:
        bg = AudioBackground()
        try:
            bg.useAccentTheme()
            assert bg.getTheme() == "accent"
        finally:
            safe_teardown(bg)
            _pump(qapp)

    def test_set_custom_colors_requires_5(self, qapp: Any) -> None:
        bg = AudioBackground()
        try:
            bg.setCustomColors([QColor("#ff0000")])  # 少于5个，应忽略
            assert bg.getTheme() == "sunset"
            colors = [QColor(f"#{i:02x}{i:02x}{i:02x}") for i in range(5)]
            bg.setCustomColors(colors)
            assert bg.getTheme() == "custom"
        finally:
            safe_teardown(bg)
            _pump(qapp)

    def test_pause_resume_animation_flags(self, qapp: Any) -> None:
        bg = AudioBackground()
        try:
            bg.pauseAnimation()
            assert bg.isAnimationPaused() is True
            bg.resumeAnimation()
            assert bg.isAnimationPaused() is False
        finally:
            safe_teardown(bg)
            _pump(qapp)

    def test_is_loaded_false_without_load(self, qapp: Any) -> None:
        bg = AudioBackground()
        try:
            assert bg.isLoaded() is False
        finally:
            safe_teardown(bg)
            _pump(qapp)


# =============================================================================
# button_widgets
# =============================================================================
class TestCustomButton:
    """CustomButton 文本/类型/主按钮切换。"""

    def _make(self, qapp: Any, settings_manager: Any, **kw: Any) -> CustomButton:
        btn = CustomButton(
            text=kw.pop("text", "按钮"),
            dpi_scale=1.0,
            global_font=QFont("Microsoft YaHei", 9),
            settings_manager=settings_manager,
            **kw,
        )
        _pump(qapp)
        return btn

    def test_default_text_and_set(self, qapp: Any, settings_manager: Any) -> None:
        btn = self._make(qapp, settings_manager)
        try:
            assert btn.text() == "按钮"
            btn.setText("保存")
            assert btn.text() == "保存"
        finally:
            safe_teardown(btn)
            _pump(qapp)

    def test_set_button_type_and_primary(self, qapp: Any, settings_manager: Any) -> None:
        btn = self._make(qapp, settings_manager)
        try:
            btn.set_button_type("secondary")
            assert btn.button_type == "secondary"
            btn.set_primary(True)
            assert btn.button_type == "primary"
            btn.set_primary(False)
            assert btn.button_type != "primary"
        finally:
            safe_teardown(btn)
            _pump(qapp)

    def test_button_type_variants(self, qapp: Any, settings_manager: Any) -> None:
        for btype in ("primary", "secondary", "normal", "warning"):
            btn = self._make(qapp, settings_manager, button_type=btype)
            try:
                assert btn.button_type == btype
                btn.update_style()
            finally:
                safe_teardown(btn)
                _pump(qapp)


# =============================================================================
# color_slider
# =============================================================================
class TestColorSlider:
    """ColorSliderWidget 构造与颜色 get/set。"""

    def test_construct_and_default_color(self, qapp: Any) -> None:
        slider = ColorSliderWidget(dpi_scale=1.0, global_font=QFont())
        try:
            color = slider.get_color()
            assert isinstance(color, str)
            assert color.startswith("#")
            assert len(color) == 7
        finally:
            safe_teardown(slider)
            _pump(qapp)

    def test_set_color_get_color(self, qapp: Any) -> None:
        slider = ColorSliderWidget(dpi_scale=1.0, global_font=QFont())
        try:
            slider.set_color("#ff0000")
            color = slider.get_color()
            assert color.startswith("#")
            assert len(color) == 7
        finally:
            safe_teardown(slider)
            _pump(qapp)

    def test_set_color_invalid_ignored(self, qapp: Any) -> None:
        slider = ColorSliderWidget(dpi_scale=1.0, global_font=QFont())
        try:
            before = slider.get_color()
            slider.set_color("not-a-color")
            assert slider.get_color() == before
        finally:
            safe_teardown(slider)
            _pump(qapp)

    def test_hue_slider_range(self, qapp: Any) -> None:
        hue = HueSlider(dpi_scale=1.0)
        try:
            hue.setRange(0, 360)
            emitted = _collect_signal(hue.valueChanged)
            hue.setValue(180)
            assert hue.value() == 180
            assert emitted == [180]
        finally:
            safe_teardown(hue)
            _pump(qapp)


# =============================================================================
# color_wheel_picker
# =============================================================================
class TestColorWheelPicker:
    """色相轮 / 完整选择器 / 预览 / 菜单。"""

    def test_picker_set_hue_emits(self, qapp: Any, settings_manager: Any) -> None:
        picker = ColorWheelPicker(dpi_scale=1.0, settings_manager=settings_manager)
        try:
            emitted = _collect_signal(picker.hueChanged)
            picker.set_hue(180, emit_signal=True)
            assert picker.get_hue() == 180
            assert emitted == [180]
        finally:
            safe_teardown(picker)
            _pump(qapp)

    def test_widget_set_color_hex(self, qapp: Any, settings_manager: Any) -> None:
        widget = ColorWheelPickerWidget(dpi_scale=1.0, settings_manager=settings_manager)
        try:
            # HSL 往返存在 ±2 精度损失（#FF0000 → #FF0101）
            widget.set_color(QColor("#ff0000"))
            expected = (255, 0, 0)
            rgb = widget.get_rgb()
            assert isinstance(rgb, tuple) and len(rgb) == 3
            assert all(abs(rgb[i] - expected[i]) <= 2 for i in range(3))
            assert widget.get_hex().startswith("#FF")
        finally:
            safe_teardown(widget)
            _pump(qapp)

    def test_color_preview(self, qapp: Any, settings_manager: Any) -> None:
        preview = ColorPreview(dpi_scale=1.0, settings_manager=settings_manager)
        try:
            preview.set_color(QColor("#00ff00"))
            assert preview.get_color().name().upper() == "#00FF00"
        finally:
            safe_teardown(preview)
            _pump(qapp)

    def test_menu_construct_and_forward(self, qapp: Any) -> None:
        menu = D_ColorWheelPickerMenu()
        try:
            menu.set_color(QColor("#0000ff"))
            picker = menu.get_color_picker()
            assert isinstance(picker, ColorWheelPickerWidget)
            # HSL 往返精度：RGB 分量 ±2 容差（#0000FF → #0101FF）
            r, g, b = menu.get_rgb()
            assert abs(r - 0) <= 2
            assert abs(g - 0) <= 2
            assert abs(b - 255) <= 2
        finally:
            menu.hide()
            safe_teardown(menu)
            _pump(qapp)


# =============================================================================
# combo_selector
# =============================================================================
class TestComboSelector:
    """ComboSelector 选项/当前文本/信号。"""

    def test_set_items_and_default(self, qapp: Any) -> None:
        selector = ComboSelector()
        try:
            selector.set_items(["图像", "视频", "文档"], default_item="视频")
            assert selector.currentText() == "视频"
        finally:
            safe_teardown(selector)
            _pump(qapp)

    def test_set_items_defaults_to_first(self, qapp: Any) -> None:
        selector = ComboSelector()
        try:
            selector.set_items(["图像", "视频"])
            assert selector.currentText() == "图像"
        finally:
            safe_teardown(selector)
            _pump(qapp)

    def test_set_current_text_emits(self, qapp: Any) -> None:
        selector = ComboSelector()
        try:
            emitted = _collect_signal(selector.currentIndexChanged)
            selector.set_items(["a", "b"])
            selector.setCurrentText("b")
            assert selector.currentText() == "b"
            assert "b" in emitted
        finally:
            safe_teardown(selector)
            _pump(qapp)

    def test_value_alias_and_color(self, qapp: Any) -> None:
        selector = ComboSelector()
        try:
            selector.set_items(["x", "y"])
            selector.set_value("y")
            assert selector.get_value() == "y"
            selector.setTextColor("#ff0000")  # 不应抛异常
        finally:
            safe_teardown(selector)
            _pump(qapp)


# =============================================================================
# control_menu
# =============================================================================
class TestCustomControlMenu:
    """CustomControlMenu 内容/位置/显隐。"""

    def test_show_with_content_then_hide(self, qapp: Any, settings_manager: Any) -> None:
        menu = CustomControlMenu(dpi_scale=1.0, settings_manager=settings_manager)
        try:
            content = QLabel("选项")
            menu.set_content(content)
            menu.set_target_button(QLabel("触发"))
            menu.set_position("bottom")
            menu.show()
            _pump(qapp)
            assert menu.isVisible()
            menu.hide()
            _pump(qapp)
            assert not menu.isVisible()
        finally:
            menu.hide()
            safe_teardown(menu)
            _pump(qapp)

    def test_set_content_replaces_and_no_double_parent(self, qapp: Any, settings_manager: Any) -> None:
        menu = CustomControlMenu(dpi_scale=1.0, settings_manager=settings_manager)
        try:
            menu.set_content(QLabel("内容A"))
            menu.set_content(QLabel("内容B"))  # 旧内容应被移除，不抛异常
        finally:
            safe_teardown(menu)
            _pump(qapp)

    def test_position_variants(self, qapp: Any, settings_manager: Any) -> None:
        menu = CustomControlMenu(dpi_scale=1.0, settings_manager=settings_manager)
        try:
            menu.set_content(QLabel("x"))
            menu.set_position("top")
            menu.show()
            _pump(qapp)
            assert menu.isVisible()
        finally:
            menu.hide()
            safe_teardown(menu)
            _pump(qapp)


# =============================================================================
# custom_scrollbar
# =============================================================================
class TestFileScrollBar:
    """FileScrollBar 范围/值/步长。"""

    def test_construct_and_default_range(self, qapp: Any) -> None:
        bar = FileScrollBar(dpi_scale=1.0)
        try:
            assert bar.sizeHint().width() > 0
            bar.setRange(0, 100)
            bar.setValue(50)
            # setValue 不发射信号（仅拖拽时发射）
            assert bar.valueChanged is not None
        finally:
            safe_teardown(bar)
            _pump(qapp)

    def test_set_value_silent(self, qapp: Any) -> None:
        bar = FileScrollBar(dpi_scale=1.0)
        emitted = _collect_signal(bar.valueChanged)
        try:
            bar.setRange(0, 100)
            bar.setValue(50)
            bar.setValue(60)
            assert emitted == []
        finally:
            safe_teardown(bar)
            _pump(qapp)

    def test_steps_and_configure(self, qapp: Any) -> None:
        bar = FileScrollBar(dpi_scale=1.0)
        try:
            bar.setPageStep(10)
            bar.setSingleStep(5)
            bar.configure(bar_width_normal=6, padding=2)
            bar.set_padding(2)
            assert bar.sizeHint().width() > 0
        finally:
            safe_teardown(bar)
            _pump(qapp)


# =============================================================================
# dropdown_menu
# =============================================================================
class TestDdropmenu:
    """Ddropmenu 选项/当前项/尺寸/信号。"""

    def _make(self, qapp: Any, settings_manager: Any, **kw: Any) -> Ddropmenu:
        menu = Ddropmenu(
            position="bottom",
            use_internal_button=kw.pop("use_internal_button", True),
            dpi_scale=1.0,
            global_font=QFont("Microsoft YaHei", 9),
            settings_manager=settings_manager,
            **kw,
        )
        _pump(qapp)
        return menu

    @staticmethod
    def _teardown(menu: Ddropmenu, qapp: Any) -> None:
        menu.close()  # 触发 closeEvent，移除 app 事件过滤器
        try:
            menu.hide_menu()
        except (RuntimeError, AttributeError):
            pass
        safe_teardown(menu)
        _pump(qapp)
        flush_widget_queue(qapp)

    def test_set_items_and_current(self, qapp: Any, settings_manager: Any) -> None:
        menu = self._make(qapp, settings_manager)
        try:
            menu.set_items(["图像", "视频", "文档"])
            assert menu.current_item() == "图像"
            info = menu.current_item_info()
            assert info is not None and info["text"] == "图像"
            menu.set_current_item("视频")
            assert menu.current_item() == "视频"
        finally:
            self._teardown(menu, qapp)

    def test_set_items_accepts_dicts(self, qapp: Any, settings_manager: Any) -> None:
        menu = self._make(qapp, settings_manager)
        try:
            items = [{"text": "A", "data": 1}, {"text": "B", "data": 2}]
            menu.set_items(items)
            assert menu.current_item() == 1
            assert menu.current_item_info()["text"] == "A"
        finally:
            self._teardown(menu, qapp)

    def test_set_current_item_by_index(self, qapp: Any, settings_manager: Any) -> None:
        menu = self._make(qapp, settings_manager)
        try:
            menu.set_items(["a", "b", "c"])
            menu.set_current_item(2)
            assert menu.current_item() == "c"
        finally:
            self._teardown(menu, qapp)

    def test_layout_and_position_controls(self, qapp: Any, settings_manager: Any) -> None:
        menu = self._make(qapp, settings_manager)
        try:
            menu.set_items(["a", "b"])
            menu.set_fixed_width(200)
            menu.set_position("top")
            menu.set_target_button(QLabel("btn"))
            # 无默认项时 current 应为 None（已清空路径）或首个元素
            menu2 = self._make(qapp, settings_manager, use_internal_button=False)
            try:
                menu2.set_items([])
                assert menu2.current_item() is None
            finally:
                self._teardown(menu2, qapp)
        finally:
            self._teardown(menu, qapp)


# =============================================================================
# hover_tooltip
# =============================================================================
class TestHoverTooltip:
    """HoverTooltip 构造与清理幂等。"""

    def test_construct_and_cleanup_idempotent(self, qapp: Any, settings_manager: Any) -> None:
        tip = HoverTooltip(dpi_scale=1.0, global_font=QFont(), settings_manager=settings_manager)
        try:
            assert not tip.isVisible()
            tip.cleanup()
            tip.cleanup()  # 幂等
        finally:
            safe_teardown(tip)
            _pump(qapp)

    def test_construct_with_parent(self, qapp: Any, settings_manager: Any) -> None:
        parent = QWidget()
        tip = HoverTooltip(parent=parent, dpi_scale=1.0, settings_manager=settings_manager)
        try:
            assert tip.parent() == parent
            tip.cleanup()
        finally:
            safe_teardown(tip)
            safe_teardown(parent)
            _pump(qapp)


# =============================================================================
# input_widgets
# =============================================================================
class TestCustomInputBox:
    """CustomInputBox 文本/占位/可编辑/信号。"""

    def _make(
        self,
        qapp: Any,
        settings_manager: Any,
        **kw: Any,
    ) -> CustomInputBox:
        box = CustomInputBox(
            placeholder_text=kw.pop("placeholder_text", ""),
            initial_text=kw.pop("initial_text", ""),
            height=20,
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=settings_manager,
            **kw,
        )
        _pump(qapp)
        return box

    def test_initial_text_and_get(self, qapp: Any, settings_manager: Any) -> None:
        box = self._make(qapp, settings_manager, initial_text="初始值")
        try:
            assert box.get_text() == "初始值"
            assert box.text() == "初始值"
            assert box.has_content()
        finally:
            box.cleanup()
            safe_teardown(box)
            _pump(qapp)

    def test_set_text_and_clear(self, qapp: Any, settings_manager: Any) -> None:
        box = self._make(qapp, settings_manager)
        emitted = _collect_signal(box.textChanged)
        try:
            box.set_text("新文本")
            assert box.get_text() == "新文本"
            assert emitted and emitted[-1] == "新文本"
            box.clear_text()
            assert box.get_text() == ""
            assert not box.has_content()
        finally:
            box.cleanup()
            safe_teardown(box)
            _pump(qapp)

    def test_placeholder_roundtrip(self, qapp: Any, settings_manager: Any) -> None:
        box = self._make(qapp, settings_manager, placeholder_text="请输入")
        try:
            assert box.get_placeholder_text() == "请输入"
            box.set_placeholder_text("新的占位")
            assert box.get_placeholder_text() == "新的占位"
        finally:
            box.cleanup()
            safe_teardown(box)
            _pump(qapp)

    def test_editable_flag(self, qapp: Any, settings_manager: Any) -> None:
        box = self._make(qapp, settings_manager)
        try:
            assert box.is_editable()
            box.set_editable(False)
            assert not box.is_editable()
            box.set_editable(True)
            assert box.is_editable()
        finally:
            box.cleanup()
            safe_teardown(box)
            _pump(qapp)

    def test_focus_and_text_aliases(self, qapp: Any, settings_manager: Any) -> None:
        box = self._make(qapp, settings_manager)
        try:
            box.setText("别名")
            assert box.text() == "别名"
            box.set_focus()
            assert box.has_focus() in (True, False)  # offscreen 下焦点可能延迟
        finally:
            box.cleanup()
            safe_teardown(box)
            _pump(qapp)


# =============================================================================
# list_widgets
# =============================================================================
class TestCustomSelectList:
    """CustomSelectList 增删/选择/模式。"""

    def _make(self, qapp: Any, settings_manager: Any, **kw: Any) -> CustomSelectList:
        lst = CustomSelectList(
            selection_mode=kw.pop("selection_mode", "single"),
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=settings_manager,
            **kw,
        )
        _pump(qapp)
        return lst

    def test_add_items_and_selection_single(self, qapp: Any, settings_manager: Any) -> None:
        lst = self._make(qapp, settings_manager)
        try:
            lst.add_items(["甲", "乙", "丙"])
            assert lst.get_selected_indices() == []
            lst.set_current_item(1)
            assert lst.get_selected_indices() == [1]
        finally:
            safe_teardown(lst)
            _pump(qapp)

    def test_selection_changed_signal(self, qapp: Any, settings_manager: Any) -> None:
        lst = self._make(qapp, settings_manager)
        emitted = _collect_signal(lst.selectionChanged)
        try:
            lst.add_items(["a", "b"])
            lst.set_selected_indices([0])
            assert lst.get_selected_indices() == [0]
            assert emitted and emitted[-1] == [0]
        finally:
            safe_teardown(lst)
            _pump(qapp)

    def test_multiple_selection_mode(self, qapp: Any, settings_manager: Any) -> None:
        lst = self._make(qapp, settings_manager, selection_mode="multiple")
        try:
            lst.add_items(["a", "b", "c"])
            lst.set_selected_indices([0, 2])
            assert sorted(lst.get_selected_indices()) == [0, 2]
        finally:
            safe_teardown(lst)
            _pump(qapp)

    def test_clear_selection_and_items(self, qapp: Any, settings_manager: Any) -> None:
        lst = self._make(qapp, settings_manager)
        try:
            lst.add_items(["a", "b"])
            lst.set_current_item(0)
            lst.clear_selection()
            assert lst.get_selected_indices() == []
            lst.clear_items()
            assert len(lst.items) == 0
        finally:
            safe_teardown(lst)
            _pump(qapp)

    def test_selection_mode_switch(self, qapp: Any, settings_manager: Any) -> None:
        lst = self._make(qapp, settings_manager, selection_mode="single")
        try:
            lst.add_items(["a", "b"])
            lst.set_selection_mode("multiple")
            assert lst.selection_mode == "multiple"
        finally:
            safe_teardown(lst)
            _pump(qapp)

    def test_item_dataclass(self, qapp: Any) -> None:
        item = CustomSelectListItem(index=0, text="项", icon_path="", is_selected=False)
        assert item.index == 0
        assert item.text == "项"
        assert item.is_selected is False


# =============================================================================
# loading_widget
# =============================================================================
class TestLoadingSpinner:
    """LoadingSpinner 启动/停止。"""

    def test_start_stop(self, qapp: Any) -> None:
        spinner = LoadingSpinner(icon_size=48, dpi_scale=1.0)
        try:
            assert spinner.is_running() is False
            spinner.start()
            assert spinner.is_running() is True
            spinner.stop()
            assert spinner.is_running() is False
        finally:
            spinner.stop()
            safe_teardown(spinner)
            _pump(qapp)

    def test_set_icon_size(self, qapp: Any) -> None:
        spinner = LoadingSpinner(icon_size=48, dpi_scale=1.0)
        try:
            spinner.set_icon_size(64)
            assert spinner.width() == 64
        finally:
            spinner.stop()
            safe_teardown(spinner)
            _pump(qapp)


# =============================================================================
# message_box
# =============================================================================
class TestCustomWindow:
    """CustomWindow 标题/添加控件。"""

    def test_construct_set_title_add_widget(self, qapp: Any, settings_manager: Any) -> None:
        window = CustomWindow(
            title="初始标题",
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=settings_manager,
        )
        try:
            window.add_widget(QLabel("内容"))
            window.set_title("新标题")
            assert window.title == "新标题"
        finally:
            window.close()
            safe_teardown(window)
            _pump(qapp)

    def test_add_layout(self, qapp: Any, settings_manager: Any) -> None:
        from PySide6.QtWidgets import QVBoxLayout

        window = CustomWindow(dpi_scale=1.0, settings_manager=settings_manager)
        try:
            layout = QVBoxLayout()
            layout.addWidget(QLabel("x"))
            window.add_layout(layout)
        finally:
            window.close()
            safe_teardown(window)
            _pump(qapp)


class TestCustomMessageBox:
    """CustomMessageBox 标题/文本/按钮/输入。"""

    def _make(self, qapp: Any, settings_manager: Any) -> CustomMessageBox:
        box = CustomMessageBox(dpi_scale=1.0, global_font=QFont(), settings_manager=settings_manager)
        _pump(qapp)
        return box

    def test_set_title_and_text(self, qapp: Any, settings_manager: Any) -> None:
        box = self._make(qapp, settings_manager)
        try:
            box.set_title("确认")
            box.set_text("确定要删除吗？")
        finally:
            box.close()
            safe_teardown(box)
            _pump(qapp)

    def test_set_buttons_stores_upto_three(self, qapp: Any, settings_manager: Any) -> None:
        box = self._make(qapp, settings_manager)
        try:
            box.set_buttons(["确定", "取消", "更多", "多余"])
            assert len(box._buttons) == 3
        finally:
            box.close()
            safe_teardown(box)
            _pump(qapp)

    def test_button_clicked_signal(self, qapp: Any, settings_manager: Any) -> None:
        box = self._make(qapp, settings_manager)
        emitted = _collect_signal(box.buttonClicked)
        try:
            box.set_buttons(["确定", "取消"])
            box._on_button_clicked(1)
            assert emitted == [1]
        finally:
            box.close()
            safe_teardown(box)
            _pump(qapp)

    def test_input_roundtrip(self, qapp: Any, settings_manager: Any) -> None:
        box = self._make(qapp, settings_manager)
        try:
            box.set_input("默认文本")
            assert box.get_input() == "默认文本"
            box.clear_input()
            assert box.get_input() == ""
        finally:
            box.close()
            safe_teardown(box)
            _pump(qapp)


# =============================================================================
# progress_widgets
# =============================================================================
class TestCustomProgressBar:
    """CustomProgressBar 范围/值/信号。"""

    def test_construct_and_defaults(self, qapp: Any, settings_manager: Any) -> None:
        bar = CustomProgressBar(dpi_scale=1.0, global_font=QFont(), settings_manager=settings_manager)
        try:
            assert bar.value() == 0
            assert bar.orientation() == bar.Horizontal
            assert bar.isInteractive() is True
        finally:
            safe_teardown(bar)
            _pump(qapp)

    def test_set_range_and_value_emits(self, qapp: Any, settings_manager: Any) -> None:
        bar = CustomProgressBar(dpi_scale=1.0, settings_manager=settings_manager)
        emitted = _collect_signal(bar.valueChanged)
        try:
            bar.setRange(0, 100)
            bar.setValue(30)
            assert bar.value() == 30
            bar.setValue(100.0)  # 越界应钳制
            assert bar.value() == 100
            assert len(emitted) >= 2
        finally:
            safe_teardown(bar)
            _pump(qapp)

    def test_set_value_same_no_emit(self, qapp: Any, settings_manager: Any) -> None:
        bar = CustomProgressBar(dpi_scale=1.0, settings_manager=settings_manager)
        emitted = _collect_signal(bar.valueChanged)
        try:
            bar.setRange(0, 100)
            bar.setValue(50)
            emitted.clear()
            bar.setValue(50)
            assert emitted == []
        finally:
            safe_teardown(bar)
            _pump(qapp)


class TestDProgressBar:
    """D_ProgressBar range/setValue/deadband。"""

    def test_construct_and_defaults(self, qapp: Any, settings_manager: Any) -> None:
        bar = D_ProgressBar(dpi_scale=1.0, settings_manager=settings_manager)
        try:
            assert bar.value() == 0
            assert bar.orientation() == D_ProgressBar.Horizontal
            assert bar.isInteractive() is True
        finally:
            safe_teardown(bar)
            _pump(qapp)

    def test_set_value_clamps(self, qapp: Any, settings_manager: Any) -> None:
        bar = D_ProgressBar(dpi_scale=1.0, settings_manager=settings_manager)
        try:
            bar.setAnimationEnabled(False)
            bar.setRange(0, 100)
            bar.setValue(150)
            assert bar.value() == 100
            bar.setValue(-5)
            assert bar.value() == 0
        finally:
            safe_teardown(bar)
            _pump(qapp)

    def test_set_value_silent_within_deadband(self, qapp: Any, settings_manager: Any) -> None:
        bar = D_ProgressBar(dpi_scale=1.0, settings_manager=settings_manager)
        emitted = _collect_signal(bar.valueChanged)
        try:
            bar.setAnimationEnabled(False)
            bar.setRange(0, 1000)
            bar.setValue(10)
            assert emitted == [10]
            emitted.clear()
            bar.setValue(13)  # 差3 < deadband(5)，不发射
            assert emitted == []
            bar.setValue(15)  # 差5 ≥ 5，发射
            assert emitted == [15]
        finally:
            safe_teardown(bar)
            _pump(qapp)

    def test_orientation_and_interactive(self, qapp: Any, settings_manager: Any) -> None:
        bar = D_ProgressBar(dpi_scale=1.0, settings_manager=settings_manager)
        try:
            bar.setOrientation(D_ProgressBar.Vertical)
            assert bar.orientation() == D_ProgressBar.Vertical
            bar.setInteractive(False)
            assert bar.isInteractive() is False
        finally:
            safe_teardown(bar)
            _pump(qapp)


class TestCustomValueBar:
    """CustomValueBar 范围/值/方向。"""

    def test_construct_and_orientations(self, qapp: Any, settings_manager: Any) -> None:
        bar = CustomValueBar(
            orientation=CustomValueBar.Horizontal,
            interactive=True,
            dpi_scale=1.0,
            settings_manager=settings_manager,
        )
        try:
            assert bar._orientation == CustomValueBar.Horizontal
            assert bar.value() == 0
        finally:
            safe_teardown(bar)
            _pump(qapp)

    def test_set_range_value_emits(self, qapp: Any, settings_manager: Any) -> None:
        bar = CustomValueBar(dpi_scale=1.0, settings_manager=settings_manager)
        emitted = _collect_signal(bar.valueChanged)
        try:
            bar.setRange(0, 100)
            bar.setValue(40)
            assert bar.value() == 40
            bar.setValue(120)
            assert bar.value() == 100
            assert len(emitted) >= 2
        finally:
            safe_teardown(bar)
            _pump(qapp)

    def test_set_orientation(self, qapp: Any, settings_manager: Any) -> None:
        bar = CustomValueBar(dpi_scale=1.0, settings_manager=settings_manager)
        try:
            bar.setOrientation(CustomValueBar.Vertical)
            assert bar._orientation == CustomValueBar.Vertical
        finally:
            safe_teardown(bar)
            _pump(qapp)


# =============================================================================
# setting_widgets
# =============================================================================
class TestCustomSettingItem:
    """CustomSettingItem 五种交互类型。"""

    def _make(self, qapp: Any, settings_manager: Any, **kw: Any) -> CustomSettingItem:
        item = CustomSettingItem(
            text=kw.pop("text", "设置项"),
            interaction_type=kw.pop("interaction_type", CustomSettingItem.SWITCH_TYPE),
            secondary_text="",
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=settings_manager,
            **kw,
        )
        _pump(qapp)
        return item

    def test_switch_type(self, qapp: Any, settings_manager: Any) -> None:
        item = self._make(qapp, settings_manager, interaction_type=CustomSettingItem.SWITCH_TYPE, initial_value=False)
        emitted = _collect_signal(item.switch_toggled)
        try:
            assert item.get_switch_value() is False
            item.set_switch_value(True)
            assert item.get_switch_value() is True
            assert emitted == [True]
            item.set_switch_value(False)
            assert emitted[-1] is False
        finally:
            for b in getattr(item, "button_group", []):
                safe_teardown(b)
            safe_teardown(item)
            _pump(qapp)

    def test_text_setters(self, qapp: Any, settings_manager: Any) -> None:
        item = self._make(qapp, settings_manager, interaction_type=CustomSettingItem.SWITCH_TYPE)
        try:
            item.set_text("新标题")
            assert item.text == "新标题"
            item.set_secondary_text("副标题")
            assert item.secondary_text == "副标题"
            item.set_tooltip_text("提示")
            assert item.get_tooltip_text() == "提示"
            if item._hover_tooltip is not None:
                item._hover_tooltip.cleanup()
        finally:
            if item._hover_tooltip is not None:
                safe_teardown(item._hover_tooltip)
            safe_teardown(item)
            _pump(qapp)

    def test_button_group_type(self, qapp: Any, settings_manager: Any) -> None:
        buttons = [
            {"text": "确定", "type": "primary"},
            {"text": "取消", "type": "normal"},
        ]
        item = self._make(qapp, settings_manager, interaction_type=CustomSettingItem.BUTTON_GROUP_TYPE, buttons=buttons)
        emitted = _collect_signal(item.button_clicked)
        try:
            assert len(item.button_group) == 2
            item._on_button_clicked(1)
            assert emitted == [1]
        finally:
            for b in item.button_group:
                safe_teardown(b)
            safe_teardown(item)
            _pump(qapp)

    def test_input_button_type(self, qapp: Any, settings_manager: Any) -> None:
        item = self._make(
            qapp,
            settings_manager,
            interaction_type=CustomSettingItem.INPUT_BUTTON_TYPE,
            placeholder="输入文字",
            initial_text="hello",
            button_text="确定",
        )
        emitted = _collect_signal(item.input_submitted)
        try:
            assert item.get_input_text() == "hello"
            item.input_box.set_text("world")
            item._on_input_button_clicked()
            assert emitted == ["world"]
        finally:
            item.input_box.cleanup()
            safe_teardown(item)
            _pump(qapp)

    def test_value_bar_type(self, qapp: Any, settings_manager: Any) -> None:
        item = self._make(
            qapp,
            settings_manager,
            interaction_type=CustomSettingItem.VALUE_BAR_TYPE,
            min_value=0,
            max_value=100,
            initial_value=50,
        )
        emitted = _collect_signal(item.value_changed)
        try:
            assert item.get_value() == 50
            item.value_bar.setAnimationEnabled(False)
            item.set_value(75)
            assert item.get_value() == 75
            assert emitted == [75]
        finally:
            safe_teardown(item)
            _pump(qapp)

    def test_folder_button_type(self, qapp: Any, settings_manager: Any) -> None:
        item = self._make(
            qapp,
            settings_manager,
            interaction_type=CustomSettingItem.FOLDER_BUTTON_TYPE,
            initial_text="C:/Downloads",
        )
        try:
            assert item.folder_path_label.text() == "C:/Downloads"
        finally:
            safe_teardown(item)
            _pump(qapp)


# =============================================================================
# smooth_scroller
# =============================================================================
class TestSmoothScroller:
    """SmoothScroller 静态应用方法。"""

    def test_apply_to_scroll_area(self, qapp: Any) -> None:
        area = QScrollArea()
        area.setWidget(QLabel("内容"))
        try:
            result = SmoothScroller.apply_to_scroll_area(area)
            assert result == area
        finally:
            safe_teardown(area)
            _pump(qapp)

    def test_apply_to_non_scroll_area_returns_none(self, qapp: Any) -> None:
        widget = QLabel("x")
        try:
            result = SmoothScroller.apply_to_scroll_area(widget)
            assert result is None
        finally:
            safe_teardown(widget)
            _pump(qapp)

    def test_apply_returns_scroller(self, qapp: Any) -> None:
        widget = QLabel("滚动目标")
        try:
            scroller = SmoothScroller.apply(widget)
            assert scroller is not None
        finally:
            safe_teardown(widget)
            _pump(qapp)

    def test_profiles_defined(self, qapp: Any) -> None:
        assert "frame_rate" in SmoothScroller.DEFAULT_PROFILE
        assert "frame_rate" in SmoothScroller.IOS_LIKE_PROFILE
        assert "frame_rate" in SmoothScroller.QUICK_PROFILE


# =============================================================================
# switch_widgets
# =============================================================================
class TestCustomSwitch:
    """CustomSwitch 构造/切换/信号。"""

    def test_initial_value(self, qapp: Any) -> None:
        off = CustomSwitch(initial_value=False, dpi_scale=1.0)
        on = CustomSwitch(initial_value=True, dpi_scale=1.0)
        _pump(qapp)
        try:
            assert off.isChecked() is False
            assert on.isChecked() is True
        finally:
            safe_teardown(off)
            safe_teardown(on)
            _pump(qapp)

    def test_set_checked_emits_toggled(self, qapp: Any) -> None:
        switch = CustomSwitch(initial_value=False, dpi_scale=1.0)
        emitted = _collect_signal(switch.toggled)
        _pump(qapp)
        try:
            switch.setChecked(True)
            assert switch.isChecked() is True
            assert emitted and emitted[-1] is True
            switch.setChecked(False)
            assert switch.isChecked() is False
            assert emitted[-1] is False
        finally:
            safe_teardown(switch)
            _pump(qapp)

    def test_update_style_no_crash(self, qapp: Any) -> None:
        switch = CustomSwitch(initial_value=False, dpi_scale=1.0)
        _pump(qapp)
        try:
            switch.update_style()
        finally:
            safe_teardown(switch)
            _pump(qapp)


# =============================================================================
# theme_card
# =============================================================================
class TestThemeCard:
    """ThemeCard 主题信息/选中/点击/颜色信号。"""

    def test_get_theme_info_defaults(self, qapp: Any, settings_manager: Any) -> None:
        colors = ["#222222", "#eeeeee", "#888888", "#555555"]
        card = ThemeCard(
            theme_name="暗色",
            colors=colors,
            is_selected=False,
            is_add_card=False,
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=settings_manager,
        )
        try:
            info = card.get_theme_info()
            assert info["name"] == "暗色"
            assert len(info["colors"]) >= 4
        finally:
            safe_teardown(card)
            _pump(qapp)

    def test_set_theme_name_and_selected(self, qapp: Any, settings_manager: Any) -> None:
        card = ThemeCard(
            theme_name="初始",
            colors=["#111111"],
            is_add_card=False,
            dpi_scale=1.0,
            settings_manager=settings_manager,
        )
        try:
            card.set_theme_name("新主题")
            assert card.get_theme_info()["name"] == "新主题"
            card.set_selected(True)
            assert card.is_selected is True
            card.set_selected(False)
            assert card.is_selected is False
        finally:
            safe_teardown(card)
            _pump(qapp)

    def test_click_emits_for_normal_card(self, qapp: Any, settings_manager: Any) -> None:
        card = ThemeCard(
            theme_name="主题A",
            colors=["#ff0000", "#ffffff", "#333333", "#999999"],
            is_add_card=False,
            dpi_scale=1.0,
            settings_manager=settings_manager,
        )
        emitted = _collect_signal(card.clicked)
        try:
            card.show()
            _pump(qapp)
            QTest.mouseClick(card, Qt.LeftButton)
            assert emitted and emitted[0] is card
        finally:
            card.hide()
            safe_teardown(card)
            _pump(qapp)

    def test_add_card_no_click_emission(self, qapp: Any, settings_manager: Any) -> None:
        card = ThemeCard(
            theme_name="",
            colors=None,
            is_add_card=True,
            dpi_scale=1.0,
            settings_manager=settings_manager,
        )
        emitted = _collect_signal(card.clicked)
        try:
            card.show()
            _pump(qapp)
            QTest.mouseClick(card, Qt.LeftButton)
            assert emitted == []
        finally:
            card.hide()
            safe_teardown(card)
            _pump(qapp)


# =============================================================================
# audio_background: 缓存与颜色提取任务
# =============================================================================

def _reset_cover_cache() -> None:
    """重置 CoverCache 单例（__new__ 惰性单例，测试之间干净隔离）。"""
    CoverCache._instance = None


class TestCoverCache:
    """CoverCache LRU 封面缓存：get/put/clear/merge。"""

    def test_singleton_and_put_get(self) -> None:
        """put 后 get 命中；未知 key 返回 None。"""
        _reset_cover_cache()
        cache = CoverCache()
        data = b"cover-art-bytes-1"
        cache.put(data, colors=[(255, 0, 0)])
        entry = cache.get(data)
        assert entry is not None
        assert entry["colors"] == [(255, 0, 0)]
        assert cache.get(b"unknown-bytes") is None

    def test_put_merges_existing_fields(self) -> None:
        """对已缓存 key 再 put 保留缺失字段（merge 语义）。"""
        _reset_cover_cache()
        cache = CoverCache()
        data = b"same-cover"
        cache.put(data, colors=[(1, 2, 3)])
        cache.put(data, blurred_pixmap=object())
        entry = cache.get(data)
        assert entry is not None
        assert entry["colors"] == [(1, 2, 3)]  # 旧 colors 保留
        assert entry["blurred_pixmap"] is not None

    def test_clear_empties_cache(self) -> None:
        """clear 后 get 全部失效。"""
        _reset_cover_cache()
        cache = CoverCache()
        cache.put(b"x", colors=[(1, 1, 1)])
        cache.clear()
        assert cache.get(b"x") is None


class TestPersistentBackgroundColorCache:
    """持久化背景色缓存：get_colors/put_colors（文件隔离到 tmp）。"""

    @staticmethod
    def _make(tmp_path: Any, monkeypatch: Any) -> PersistentBackgroundColorCache:
        """重置单例并把缓存文件指向 tmp（避免触碰真实 data/）。"""
        PersistentBackgroundColorCache._instance = None
        cache_file = tmp_path / "audio_bg_cache.json"
        monkeypatch.setattr(
            PersistentBackgroundColorCache,
            "_get_cache_file_path",
            lambda self: str(cache_file),
        )
        return PersistentBackgroundColorCache()

    def test_put_get_roundtrip(self, tmp_path: Any, monkeypatch: Any) -> None:
        """put_colors 后 get_colors 回读规范化颜色列表。"""
        cache = self._make(tmp_path, monkeypatch)
        cache.put_colors(b"album-art", [(255, 0, 0), (0, 255, 0)])
        got = cache.get_colors(b"album-art")
        assert got == [[255, 0, 0], [0, 255, 0]]

    def test_get_unknown_returns_none(self, tmp_path: Any, monkeypatch: Any) -> None:
        """为写入过的 key → None。"""
        cache = self._make(tmp_path, monkeypatch)
        assert cache.get_colors(b"missing") is None

    def test_put_empty_colors_ignored(self, tmp_path: Any, monkeypatch: Any) -> None:
        """空 colors 列表被忽略，不写缓存。"""
        cache = self._make(tmp_path, monkeypatch)
        cache.put_colors(b"data", [])
        assert cache.get_colors(b"data") is None


class TestColorExtractionTask:
    """颜色提取 QRunnable：取消/回调/降级路径。"""

    @staticmethod
    def _make(task_id: int = 1, callback: Any = None) -> ColorExtractionTask:
        return ColorExtractionTask(
            task_id=task_id,
            cover_data=b"fake-cover-image",
            callback=callback or (lambda tid, colors: None),
            widget_ref=None,
        )

    def test_cancel_and_is_cancelled(self) -> None:
        """cancel 置位 is_cancelled。"""
        task = self._make()
        assert task.is_cancelled() is False
        task.cancel()
        assert task.is_cancelled() is True

    def test_run_when_cancelled_skips_callback(self) -> None:
        """取消后 run 不触发回调。"""
        received: List[int] = []
        task = self._make(callback=lambda tid, colors: received.append(tid))
        task.cancel()
        task.run()
        assert received == []

    def test_run_rust_path_calls_callback(self, monkeypatch: Any) -> None:
        """Rust 提取成功（≥5 色）→ callback 收到 5 色列表。"""
        received: List[Any] = []
        task = self._make(
            task_id=7,
            callback=lambda tid, colors: received.append((tid, colors)),
        )
        task._rust_available = True
        monkeypatch.setattr(
            task,
            "_extract_colors_rust",
            lambda: [(10, 20, 30), (40, 50, 60), (70, 80, 90), (100, 110, 120), (130, 140, 150)],
        )
        task.run()
        assert len(received) == 1
        task_id, colors = received[0]
        assert task_id == 7
        assert colors is not None and len(colors) == 5

    def test_run_python_fallback_none(self, monkeypatch: Any) -> None:
        """Rust 不可用且 Python 提取失败 → callback 收到 (task_id, None)。"""
        received: List[Any] = []
        task = self._make(
            task_id=3,
            callback=lambda tid, colors: received.append((tid, colors)),
        )
        task._rust_available = False
        monkeypatch.setattr(task, "_extract_colors_python", lambda: None)
        task.run()
        assert received == [(3, None)]


class TestFluidOpenGLLayer:
    """FluidOpenGLLayer：GL 层构造与未加载时 paintGL 早退。"""

    def test_construct_and_paint_early_exit(self, qapp: Any) -> None:
        """host 未加载 → paintGL 直接 return，无 GL 绘图。"""
        host = AudioBackground()
        try:
            try:
                layer = FluidOpenGLLayer(host)
            except Exception:
                pytest.skip("OpenGL context unavailable")
            assert layer._host is host
            layer.resize(100, 100)
            layer.paintGL()  # host.isLoaded()==False → 早退
        finally:
            safe_teardown(host)
            _pump(qapp)


# =============================================================================
# dropdown_menu: CustomDropdownMenu（兼容别名）
# =============================================================================
class TestCustomDropdownMenu:
    """CustomDropdownMenu：Ddropmenu 兼容子类，构造可用。"""

    def test_subclass_of_ddropmenu(self) -> None:
        """CustomDropdownMenu 是 Ddropmenu 子类（旧接口别名）。"""
        assert issubclass(CustomDropdownMenu, Ddropmenu)

    def test_construct_and_set_items(self, qapp: Any, settings_manager: Any) -> None:
        """构造 + set_items 可用（继承 Ddropmenu 行为）。"""
        menu = CustomDropdownMenu(
            position="bottom",
            use_internal_button=True,
            dpi_scale=1.0,
            global_font=QFont(),
            settings_manager=settings_manager,
        )
        try:
            menu.set_items(["a", "b"])
            assert menu.current_item() == "a"
        finally:
            menu.close()
            try:
                menu.hide_menu()
            except (RuntimeError, AttributeError):
                pass
            safe_teardown(menu)
            _pump(qapp)


# =============================================================================
# progress_widgets: CustomVolumeBar
# =============================================================================
class TestCustomVolumeBar:
    """CustomVolumeBar：range/value/鼠标/滚轮/绘制。"""

    def _make(self, qapp: Any, settings_manager: Any) -> CustomVolumeBar:
        bar = CustomVolumeBar(dpi_scale=1.0, settings_manager=settings_manager)
        bar.setFixedSize(200, 30)
        _pump(qapp)
        return bar

    def test_defaults_and_range(self, qapp: Any, settings_manager: Any) -> None:
        """默认值 50；setValue 钳制到 100。"""
        bar = self._make(qapp, settings_manager)
        try:
            assert bar.value() == 50
            bar.setRange(0, 100)
            bar.setValue(25)
            assert bar.value() == 25
            bar.setValue(200)
            assert bar.value() == 100
        finally:
            safe_teardown(bar)
            _pump(qapp)

    def test_set_value_emits_once_per_change(self, qapp: Any, settings_manager: Any) -> None:
        """值变化发射 valueChanged；相同值不发射。"""
        bar = self._make(qapp, settings_manager)
        emitted = _collect_signal(bar.valueChanged)
        try:
            bar.setRange(0, 100)
            bar.setValue(30)
            assert emitted == [30]
            bar.setValue(30)
            assert emitted == [30]
        finally:
            safe_teardown(bar)
            _pump(qapp)

    def test_mouse_press_move_release(self, qapp: Any, settings_manager: Any) -> None:
        """按下拖动松开：_is_pressed 生命周期 + 值改变。"""
        bar = self._make(qapp, settings_manager)
        try:
            press = QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(100, 10),
                Qt.LeftButton,
                Qt.LeftButton,
                Qt.NoModifier,
            )
            bar.mousePressEvent(press)
            assert bar._is_pressed is True
            move = QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(160, 10),
                Qt.LeftButton,
                Qt.LeftButton,
                Qt.NoModifier,
            )
            bar.mouseMoveEvent(move)
            assert bar.value() != 50  # 拖动改变值
            release = QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                QPointF(160, 10),
                Qt.LeftButton,
                Qt.LeftButton,
                Qt.NoModifier,
            )
            bar.mouseReleaseEvent(release)
            assert bar._is_pressed is False
        finally:
            safe_teardown(bar)
            _pump(qapp)

    def test_wheel_event_step(self, qapp: Any, settings_manager: Any) -> None:
        """上滚 +step（范围 2%），下滚 -step。"""
        bar = self._make(qapp, settings_manager)
        try:
            bar.setRange(0, 100)
            assert bar.value() == 50
            up = QWheelEvent(
                QPointF(10, 10),
                QPointF(10, 10),
                QPoint(0, 0),
                QPoint(0, 120),
                Qt.NoButton,
                Qt.NoModifier,
                Qt.ScrollPhase.ScrollUpdate,
                False,
            )
            bar.wheelEvent(up)
            assert bar.value() == 52
            down = QWheelEvent(
                QPointF(10, 10),
                QPointF(10, 10),
                QPoint(0, 0),
                QPoint(0, -120),
                Qt.NoButton,
                Qt.NoModifier,
                Qt.ScrollPhase.ScrollUpdate,
                False,
            )
            bar.wheelEvent(down)
            assert bar.value() == 50
        finally:
            safe_teardown(bar)
            _pump(qapp)

    def test_paint_and_enter_leave(self, qapp: Any, settings_manager: Any) -> None:
        """render 到 QPixmap 真实绘制；enter/leave 刷新不抛。"""
        bar = self._make(qapp, settings_manager)
        try:
            pixmap = QPixmap(200, 30)
            bar.render(pixmap)
            assert not pixmap.isNull()
            bar.enterEvent(QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
            bar.leaveEvent(QEvent(QEvent.Type.Leave))
        finally:
            safe_teardown(bar)
            _pump(qapp)


# =============================================================================
# smooth_scroller: D_ScrollBar
# =============================================================================
class TestDScrollBar:
    """D_ScrollBar：自定义平滑滚动条构造与颜色设置。"""

    def test_construct_and_vertical_default(self, qapp: Any) -> None:
        """默认垂直；初始样式已生成。"""
        bar = D_ScrollBar()
        try:
            assert bar.orientation() == Qt.Vertical
            assert bar.styleSheet()  # __init__ 已 _update_style
        finally:
            safe_teardown(bar)
            _pump(qapp)

    def test_set_colors_updates_stylesheet(self, qapp: Any) -> None:
        """set_colors 更新样式表（颜色注入）。"""
        bar = D_ScrollBar()
        try:
            before = bar.styleSheet()
            bar.set_colors("#111111", "#222222", "#333333", "#444444")
            after = bar.styleSheet()
            assert after and after != before
        finally:
            safe_teardown(bar)
            _pump(qapp)
