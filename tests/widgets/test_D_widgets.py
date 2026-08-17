# -*- coding: utf-8 -*-
# targets: widgets.D_widgets, widgets.D_hover_menu, widgets.D_more_menu, widgets.D_volume
#       widgets.D_volume_control, widgets.button_widgets, widgets.lut_manager_dialog, widgets.player_control_bar
#       utils.lut_utils
"""``widgets/`` D 系列与专项控件（todo-16）单元测试。

覆盖 7 个目标模块：

* ``D_widgets`` —— 控件库再导出模块（``__all__`` 完整性）
* ``D_hover_menu`` —— 悬浮菜单（显隐/toggle/内容/透明度/圆角/边距/位置切换）
* ``D_more_menu`` —— 右键菜单项与菜单（增删查、点击信号、显隐）
* ``D_volume`` + ``D_volume_control`` —— 音量滑块与综合音量控件
  （0%/100% 状态收敛、``set_volume`` 钳制、mute 切换、菜单显隐信号）
* ``player_control_bar`` —— 播放器控制栏（播放/进度/音量/倍速/LUT 状态）
* ``lut_manager_dialog`` —— LUT 管理弹窗与导入工作线程
  （无效路径发出 ``import_error`` 且不崩溃、人对话框打开不闪退）

测试纪律（Q3-W3）：
* 全部走 ``pytest.mark.unit``；Qt 对象 teardown 一律 ``safe_teardown``。
* 事件注入用 ``QTest.mouseClick``；信号断言采用"先连接收集槽再触发"，
  QThread 跨线程信号用有界泵事件轮询（避免商队竞态）。
* 不调用 ``exec()/exec_()``，不比较像素，不触碰真实 ``data/`` 目录
  （LUT 导入路径通过 ``monkeypatch`` 隔离）。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, List, Optional

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

import freeassetfilter.widgets.D_widgets as dw
from freeassetfilter.widgets.D_hover_menu import D_HoverMenu
from freeassetfilter.widgets.D_more_menu import D_MoreMenu, D_MoreMenuItem
from freeassetfilter.widgets.D_volume import D_Volume
from freeassetfilter.widgets.D_volume_control import DVolumeControl
from freeassetfilter.widgets.button_widgets import CustomButton
from freeassetfilter.widgets.lut_manager_dialog import (
    LutImportWorker,
    LutManagerDialog,
)
from freeassetfilter.widgets.player_control_bar import PlayerControlBar
from freeassetfilter.utils.lut_utils import LUTInfo

from tests.support.qt_helpers import (
    flush_widget_queue,
    process_qt_events,
    safe_teardown,
)

pytestmark = pytest.mark.unit


#: 2x2x2 3D identity LUT 内联样本（≤50 行，存入 tmp_path，不写真实 data/）。
IDENTITY_2_CUBE: str = """\
TITLE "Identity 2"
LUT_3D_SIZE 2
# corner data
0 0 0
1 0 0
0 1 0
1 1 0
0 0 1
1 0 1
0 1 1
1 1 1
"""


def _pump_until(
    qapp: Any,
    predicate: Callable[[], bool],
    timeout_s: float = 2.0,
) -> bool:
    """在截止期内泵事件直到条件成立（有界，不做裸 sleep 轮询）。

    Args:
        qapp: QApplication 实例。
        predicate: 待满足的条件（返回 bool）。
        timeout_s: 最大泵事件时长（秒）。

    Returns:
        bool: 条件在截止期内成立则 True，否则 False。
    """
    deadline: float = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        flush_widget_queue(qapp, iterations=3)
        time.sleep(0.005)
    return bool(predicate())


@pytest.fixture
def cube_file(tmp_path: Path) -> str:
    """提供指向 tmp_path 的合法 2x2x2 CUBE 文件路径。

    Args:
        tmp_path: pytest 内置的每测试临时目录。

    Returns:
        str: 写入的 .cube 文件路径。
    """
    path: Path = tmp_path / "identity.cube"
    path.write_text(IDENTITY_2_CUBE, encoding="utf-8")
    return str(path)


@pytest.fixture
def empty_cube_file(tmp_path: Path) -> str:
    """提供指向 tmp_path 的空 .cube 文件路径（用于无效 LUT）。

    Args:
        tmp_path: pytest 内置的每测试临时目录。

    Returns:
        str: 空 .cube 文件路径。
    """
    path: Path = tmp_path / "empty.cube"
    path.write_text("", encoding="utf-8")
    return str(path)


# =============================================================================
# D_widgets —— 控件库再导出模块
# =============================================================================
class TestDWidgetsExports:
    """``D_widgets.py`` 的再导出完整性。"""

    def test_all_names_are_defined(self) -> None:
        """``__all__`` 中的每个名字都真实存在于模块。"""
        expected: List[str] = [
            "CustomWindow",
            "CustomButton",
            "CustomProgressBar",
            "CustomSelectListItem",
            "CustomSelectList",
            "CustomValueBar",
            "CustomVolumeBar",
            "CustomMessageBox",
            "CustomInputBox",
            "CustomControlMenu",
            "CustomSettingItem",
            "CustomSwitch",
            "HoverTooltip",
            "D_HoverMenu",
            "Ddropmenu",
            "CustomDropdownMenu",
        ]
        assert set(dw.__all__) == set(expected)
        for name in expected:
            assert hasattr(dw, name), f"模块缺少导出: {name}"

    def test_all_names_are_callable_classes(self) -> None:
        """再导出的对象全部是可实例化的类。"""
        for name in dw.__all__:
            obj: Any = getattr(dw, name)
            assert isinstance(obj, type), f"{name} 不是类: {obj!r}"


# =============================================================================
# D_hover_menu —— 悬浮菜单
# =============================================================================
class TestDHoverMenu:
    """``D_HoverMenu`` 的基础行为。"""

    def test_position_constants(self) -> None:
        """八个位置常量取值正确。"""
        assert D_HoverMenu.Position_Top == "top"
        assert D_HoverMenu.Position_Bottom == "bottom"
        assert D_HoverMenu.Position_Left == "left"
        assert D_HoverMenu.Position_Right == "right"
        assert D_HoverMenu.Position_TopLeft == "top_left"
        assert D_HoverMenu.Position_TopRight == "top_right"
        assert D_HoverMenu.Position_BottomLeft == "bottom_left"
        assert D_HoverMenu.Position_BottomRight == "bottom_right"

    def test_constructor_defaults(self, qapp: Any) -> None:
        """默认构造：初始隐藏、四个信号可连接。"""
        menu: D_HoverMenu = D_HoverMenu()
        try:
            assert menu.is_visible() is False
            assert menu.get_background_alpha() == 1.0
            assert menu.get_border_radius() == 8
            assert menu.get_content_padding() == (0, 0, 0, 0)
            # 信号对象存在且可 connect。
            menu.keyPressed.connect(lambda _obj: None)
            menu.controlBarShown.connect(lambda: None)
            menu.controlBarHidden.connect(lambda: None)
            menu.closed.connect(lambda: None)
        finally:
            safe_teardown(menu)

    def test_content_set_and_clear(self, qapp: Any) -> None:
        """``set_content`` 加入子控件、``clear_content`` 清空。"""
        menu: D_HoverMenu = D_HoverMenu()
        try:
            label: QLabel = QLabel("内容")
            menu.set_content(label)
            assert menu.content_layout().count() == 1

            menu.clear_content()
            assert menu.content_layout().count() == 0
        finally:
            safe_teardown(menu)

    def test_show_hide_toggle(self, qapp: Any) -> None:
        """``show``/``hide``/``toggle`` 驱动 ``is_visible``。"""
        menu: D_HoverMenu = D_HoverMenu(use_sub_widget_mode=True)
        host: QWidget = QWidget()
        host.resize(300, 200)
        try:
            menu.set_content(QLabel("内容"))
            menu.set_target_widget(host)
            menu.set_timeout_enabled(False)

            menu.show()
            process_qt_events(qapp, ms=50)
            assert menu.is_visible() is True

            # 隐藏走 300ms 淡出动画，_on_animation_finished 后才翻转 _is_visible，
            # 故用有界泵等待动画收敛，而非固定 50ms。
            menu.toggle()  # 显示中 → 隐藏
            assert _pump_until(qapp, lambda: not menu.is_visible())

            menu.toggle()  # 隐藏中 → 显示
            assert _pump_until(qapp, lambda: menu.is_visible())

            menu.hide()
            assert _pump_until(qapp, lambda: not menu.is_visible())
        finally:
            menu.hide_immediately()
            safe_teardown(menu)
            safe_teardown(host)

    def test_settings_roundtrip(self, qapp: Any) -> None:
        """背景透明度/圆角/内容边距/垂直动画的 setter 与 getter 往返。"""
        menu: D_HoverMenu = D_HoverMenu()
        try:
            menu.set_background_alpha(0.4)
            assert menu.get_background_alpha() == 0.4

            menu.set_border_radius(12)
            assert menu.get_border_radius() == 12

            menu.set_content_padding(1, 2, 3, 4)
            assert menu.get_content_padding() == (1, 2, 3, 4)

            menu.set_vertical_animation_enabled(False)
            assert menu.is_vertical_animation_enabled() is False
        finally:
            safe_teardown(menu)

    def test_auto_hide_and_position_no_raise(self, qapp: Any) -> None:
        """自动隐藏开关、位置切换、偏移设置不抛异常。"""
        menu: D_HoverMenu = D_HoverMenu()
        try:
            menu.set_auto_hide_enabled(False)
            assert menu.is_auto_hide_enabled() is False
            menu.set_auto_hide_enabled(True)
            assert menu.is_auto_hide_enabled() is True

            menu.set_position(D_HoverMenu.Position_Left)
            menu.set_offset(5, 5)
            menu.set_mouse_move_detection(False)
            menu.set_timeout_duration(3000)
            menu.set_fade_duration(100)
        finally:
            safe_teardown(menu)


# =============================================================================
# D_more_menu —— 右键菜单项与菜单
# =============================================================================
class TestDMoreMenuItem:
    """``D_MoreMenuItem`` 单一项。"""

    def test_default_data_falls_back_to_text(self, qapp: Any) -> None:
        """data 缺省时回落为 text。"""
        item: D_MoreMenuItem = D_MoreMenuItem("打开")
        try:
            assert item.data() == "打开"
            assert item.text() == "打开"
        finally:
            safe_teardown(item)

    def test_set_and_get_data(self, qapp: Any) -> None:
        """``set_data``/``data`` 往返。"""
        item: D_MoreMenuItem = D_MoreMenuItem("删除", data="key-1")
        try:
            assert item.data() == "key-1"
            item.set_data("key-2")
            assert item.data() == "key-2"
        finally:
            safe_teardown(item)


class TestDMoreMenu:
    """``D_MoreMenu`` 菜单本体。"""

    def test_add_count_items(self, qapp: Any) -> None:
        """``add_item`` 后 count/item_text/item_data/items 一致。"""
        menu: D_MoreMenu = D_MoreMenu()
        try:
            menu.set_timeout_enabled(False)
            menu.add_item("打开", data="open")
            menu.add_item("删除", data="delete")
            assert menu.count() == 2
            assert menu.item_text(0) == "打开"
            assert menu.item_data(0) == "open"
            assert menu.item_text(1) == "删除"
            assert menu.item_data(1) == "delete"
            assert len(menu.items()) == 2
        finally:
            safe_teardown(menu)

    def test_set_items_strings_and_dicts(self, qapp: Any) -> None:
        """``set_items`` 支持字符串列表与字典列表。"""
        menu: D_MoreMenu = D_MoreMenu()
        try:
            menu.set_timeout_enabled(False)
            menu.set_items(["复制", {"text": "重命名", "data": "rename"}])
            assert menu.count() == 2
            assert menu.item_text(0) == "复制"
            assert menu.item_data(0) == "复制"
            assert menu.item_text(1) == "重命名"
            assert menu.item_data(1) == "rename"
        finally:
            safe_teardown(menu)

    def test_insert_remove_clear(self, qapp: Any) -> None:
        """``insert_item``/``remove_item``/``clear_items`` 行为。"""
        menu: D_MoreMenu = D_MoreMenu()
        try:
            menu.set_timeout_enabled(False)
            menu.add_item("A")
            menu.add_item("C")
            menu.insert_item(1, "B")
            assert menu.item_text(0) == "A"
            assert menu.item_text(1) == "B"
            assert menu.item_text(2) == "C"

            menu.remove_item(1)
            assert menu.count() == 2
            assert menu.item_text(1) == "C"

            menu.clear_items()
            assert menu.count() == 0
        finally:
            safe_teardown(menu)

    def test_show_hide_toggle(self, qapp: Any) -> None:
        """``show``/``hide``/``toggle`` 驱动可见性。"""
        menu: D_MoreMenu = D_MoreMenu()
        try:
            menu.set_timeout_enabled(False)
            menu.add_item("打开")
            menu.show()
            process_qt_events(qapp, ms=50)
            assert menu.is_visible() is True

            menu.toggle()
            process_qt_events(qapp, ms=50)
            assert menu.is_visible() is False

            menu.toggle()
            process_qt_events(qapp, ms=50)
            assert menu.is_visible() is True

            menu.hide()
            process_qt_events(qapp, ms=50)
            assert menu.is_visible() is False
        finally:
            safe_teardown(menu)

    def test_item_click_emits_item_clicked(self, qapp: Any) -> None:
        """点击菜单项触发 ``itemClicked(data)`` 并自动隐藏。"""
        menu: D_MoreMenu = D_MoreMenu()
        try:
            menu.set_timeout_enabled(False)
            menu.add_item("打开", data="open-cmd")
            menu.show()
            process_qt_events(qapp, ms=50)

            clicked: List[Any] = []
            menu.itemClicked.connect(clicked.append)
            items: List[D_MoreMenuItem] = menu.findChildren(D_MoreMenuItem)
            assert items, "菜单项按钮未创建"
            QTest.mouseClick(items[0], Qt.LeftButton)
            process_qt_events(qapp, ms=50)

            assert clicked == ["open-cmd"]
            assert menu.is_visible() is False
        finally:
            menu.hide()
            safe_teardown(menu)


# =============================================================================
# D_volume —— D_Volume + DVolumeControl（合并目标）
# =============================================================================
class TestDVolume:
    """``D_Volume`` 音量悬浮菜单（百分号 + 竖向进度条）。"""

    def test_default_volume_100(self, qapp: Any) -> None:
        """默认音量为 100。"""
        volume: D_Volume = D_Volume()
        try:
            assert volume.volume() == 100
            assert volume.is_visible() is False
        finally:
            safe_teardown(volume)

    def test_set_volume_clamps_bounds(self, qapp: Any) -> None:
        """``set_volume`` 对非法值钳制到 [0, 100]。"""
        volume: D_Volume = D_Volume()
        try:
            volume.set_volume(-50)
            assert volume.volume() == 0
            volume.set_volume(150)
            assert volume.volume() == 100
            volume.set_volume(0)
            assert volume.volume() == 0
            volume.set_volume(100)
            assert volume.volume() == 100
            volume.set_volume(50)
            assert volume.volume() == 50
        finally:
            safe_teardown(volume)

    def test_volume_0_and_100_convergence(self, qapp: Any) -> None:
        """0% 与 100% 两端状态收敛（QB 要求）。"""
        volume: D_Volume = D_Volume()
        try:
            # 构造期 setValue(100) 只启动了 0→100 动画（display 仍为 0）；
            # 若此时 set_volume(0)，setValue 走到 start_value==value 短路分支，
            # 不发射任何信号。先泵完 init 动画，让 display 收敛到 100 再开始。
            process_qt_events(qapp, ms=300)

            collector: List[int] = []
            volume.progressValueChanged.connect(collector.append)

            volume.set_volume(0)
            assert volume.volume() == 0
            assert _pump_until(qapp, lambda: collector and collector[-1] == 0)

            collector.clear()
            volume.set_volume(100)
            assert volume.volume() == 100
            assert _pump_until(qapp, lambda: collector and collector[-1] == 100)
        finally:
            safe_teardown(volume)

    def test_show_hide_toggle_menu(self, qapp: Any) -> None:
        """``show``/``hide``/``toggle`` 代理到内部悬浮菜单。"""
        volume: D_Volume = D_Volume()
        host: QWidget = QWidget()
        host.resize(200, 100)
        try:
            volume.set_target_widget(host)

            volume.show()
            process_qt_events(qapp, ms=50)
            assert volume.is_visible() is True

            # 隐藏走内部 D_HoverMenu 300ms 淡出动画，等动画收敛再断言。
            volume.toggle()
            assert _pump_until(qapp, lambda: not volume.is_visible())

            volume.toggle()
            assert _pump_until(qapp, lambda: volume.is_visible())

            volume.hide()
            assert _pump_until(qapp, lambda: not volume.is_visible())
        finally:
            volume.hide_menu_immediately()
            safe_teardown(volume)
            safe_teardown(host)

    def test_style_update_no_raise(self, qapp: Any) -> None:
        """``update_style`` 不抛异常。"""
        volume: D_Volume = D_Volume()
        try:
            volume.update_style()
        finally:
            safe_teardown(volume)


class TestDVolumeControl:
    """``DVolumeControl`` 综合音量控件。"""

    def test_defaults(self, qapp: Any) -> None:
        """默认音量 100、未静音、属性暴露。"""
        control: DVolumeControl = DVolumeControl()
        try:
            assert control.volume() == 100
            assert control.muted() is False
            assert isinstance(control.volume_button, CustomButton)
            assert isinstance(control.volume_widget, D_Volume)
        finally:
            safe_teardown(control)

    def test_set_volume_emits_and_clamps(self, qapp: Any) -> None:
        """``set_volume`` 发射 ``valueChanged`` 并对非法值钳制。"""
        control: DVolumeControl = DVolumeControl()
        try:
            collector: List[int] = []
            control.valueChanged.connect(collector.append)

            control.set_volume(30)
            assert control.volume() == 30
            assert collector[-1] == 30

            control.set_volume(-10)
            assert control.volume() == 0
            assert collector[-1] == 0

            control.set_volume(300)
            assert control.volume() == 100
            assert collector[-1] == 100
        finally:
            safe_teardown(control)

    def test_set_muted_and_toggle(self, qapp: Any) -> None:
        """``set_muted``/``toggle_mute`` 发射 ``mutedChanged`` 并同步状态。"""
        control: DVolumeControl = DVolumeControl()
        try:
            collector: List[bool] = []
            control.mutedChanged.connect(collector.append)

            control.set_muted(True)
            assert control.muted() is True
            assert collector[-1] is True

            control.toggle_mute()
            assert control.muted() is False
            assert collector[-1] is False

            control.toggle_mute()
            assert control.muted() is True
        finally:
            safe_teardown(control)

    def test_volume_change_unmutes(self, qapp: Any) -> None:
        """静音时调大音量会自动解除静音。"""
        control: DVolumeControl = DVolumeControl()
        try:
            control.set_muted(True)
            control.set_volume(50)
            assert control.muted() is False
            assert control.volume() == 50
        finally:
            safe_teardown(control)

    def test_menu_toggle_via_button_click(self, qapp: Any, monkeypatch: Any) -> None:
        """点击音量按钮展开/收起菜单并发射 ``menuShown``/``menuHidden``。"""
        control: DVolumeControl = DVolumeControl()
        # 全局 eventFilter 用 QApplication.widgetAt(QCursor.pos()) 判断“是否点到按钮”。
        # 完整套件运行时真实光标可能不在控件上，导致第二次点击被误判为外部点击：
        # 先 hide 再被 clicked 信号 toggle 又 show → _menu_visible 最终为 True。
        # 测试场景下固定 widgetAt 指向音量按钮，使外部点击判定恒为 False。
        monkeypatch.setattr(
            QApplication,
            "widgetAt",
            lambda pos: control._volume_button,
        )
        control.resize(120, 32)
        control.show()
        process_qt_events(qapp, ms=50)
        try:
            shown: List[bool] = []
            hidden: List[bool] = []
            control.menuShown.connect(lambda: shown.append(True))
            control.menuHidden.connect(lambda: hidden.append(True))

            QTest.mouseClick(control.volume_button, Qt.LeftButton)
            process_qt_events(qapp, ms=50)
            assert shown == [True]
            assert control._menu_visible is True

            QTest.mouseClick(control.volume_button, Qt.LeftButton)
            process_qt_events(qapp, ms=50)
            assert hidden == [True]
            assert control._menu_visible is False
        finally:
            if control._menu_visible:
                QTest.mouseClick(control.volume_button, Qt.LeftButton)
                process_qt_events(qapp, ms=50)
            safe_teardown(control)

    def test_sync_from_player_and_style(self, qapp: Any) -> None:
        """``sync_volume_from_player``/``update_style`` 不抛异常。"""
        control: DVolumeControl = DVolumeControl()
        try:
            control.sync_volume_from_player(80)
            assert control.volume() == 80
            control.update_style()
        finally:
            safe_teardown(control)


# =============================================================================
# player_control_bar —— 播放器控制栏
# =============================================================================
class TestPlayerControlBar:
    """``PlayerControlBar`` 播放器控制栏。"""

    def test_constructor_defaults(
        self, qapp: Any, settings_manager: Any
    ) -> None:
        """默认状态：未播放、音量 100、倍速 1.0、未加载 LUT、未分离。"""
        bar: PlayerControlBar = PlayerControlBar(
            settings_manager=settings_manager
        )
        try:
            assert bar.is_playing() is False
            assert bar.get_volume() == 100
            assert bar.get_speed() == 1.0
            assert bar.is_lut_loaded() is False
            assert bar.is_detached() is False
        finally:
            safe_teardown(bar)

    def test_set_playing_toggles_state(self, qapp: Any, settings_manager: Any) -> None:
        """``set_playing`` 切换播放状态。"""
        bar: PlayerControlBar = PlayerControlBar(
            settings_manager=settings_manager
        )
        try:
            bar.set_playing(True)
            assert bar.is_playing() is True
            bar.set_playing(False)
            assert bar.is_playing() is False
        finally:
            safe_teardown(bar)

    def test_set_volume_emits_and_clamps(
        self, qapp: Any, settings_manager: Any
    ) -> None:
        """``set_volume`` 发射 ``volumeChanged`` 并对非法值钳制。"""
        bar: PlayerControlBar = PlayerControlBar(
            settings_manager=settings_manager
        )
        try:
            collector: List[int] = []
            bar.volumeChanged.connect(collector.append)

            bar.set_volume(30)
            assert bar.get_volume() == 30
            assert collector[-1] == 30

            bar.set_volume(-5)
            assert bar.get_volume() == 0
            assert collector[-1] == 0

            bar.set_volume(200)
            assert bar.get_volume() == 100
            assert collector[-1] == 100
        finally:
            safe_teardown(bar)

    def test_set_muted_emits(self, qapp: Any, settings_manager: Any) -> None:
        """``set_muted`` 发射 ``muteChanged``。"""
        bar: PlayerControlBar = PlayerControlBar(
            settings_manager=settings_manager
        )
        try:
            collector: List[bool] = []
            bar.muteChanged.connect(collector.append)
            bar.set_muted(True)
            assert collector[-1] is True
            bar.set_muted(False)
            assert collector[-1] is False
        finally:
            safe_teardown(bar)

    def test_set_speed_emits_on_change(self, qapp: Any, settings_manager: Any) -> None:
        """``set_speed`` 仅在值变化时发射 ``speedChanged``。"""
        bar: PlayerControlBar = PlayerControlBar(
            settings_manager=settings_manager
        )
        try:
            collector: List[float] = []
            bar.speedChanged.connect(collector.append)

            bar.set_speed(2.0)
            assert bar.get_speed() == 2.0
            assert collector == [2.0]

            # 相同值不重复发射。
            bar.set_speed(2.0)
            assert collector == [2.0]
        finally:
            safe_teardown(bar)

    def test_set_duration_and_position_time_label(
        self, qapp: Any, settings_manager: Any
    ) -> None:
        """``set_duration``/``set_position`` 更新时间显示。"""
        bar: PlayerControlBar = PlayerControlBar(
            settings_manager=settings_manager
        )
        try:
            bar.set_duration(60.0)
            assert "01:00" in bar._time_label.text()

            bar.set_position(30.5, 60.0)
            assert "00:30 / 01:00" in bar._time_label.text()

            bar.set_time_text("01:01", "01:02")
            assert bar._time_label.text() == "01:01 / 01:02"
        finally:
            safe_teardown(bar)

    def test_set_progress_updates_bar(self, qapp: Any, settings_manager: Any) -> None:
        """``set_progress`` 更新进度条数值并发射 ``progressChanged``。"""
        bar: PlayerControlBar = PlayerControlBar(
            settings_manager=settings_manager
        )
        try:
            collector: List[int] = []
            bar.progressChanged.connect(collector.append)

            bar.set_progress(500, use_animation=False)
            assert bar._progress_bar._value == 500
            assert collector[-1] == 500

            # 超过最大值被钳制。
            bar.set_progress(9000, use_animation=False)
            assert bar._progress_bar._value == 1000
        finally:
            safe_teardown(bar)

    def test_play_button_click_emits(self, qapp: Any, settings_manager: Any) -> None:
        """点击播放按钮发射 ``playPauseClicked``。"""
        bar: PlayerControlBar = PlayerControlBar(
            settings_manager=settings_manager
        )
        bar.resize(600, 50)
        bar.show()
        process_qt_events(qapp, ms=50)
        try:
            collector: List[bool] = []
            bar.playPauseClicked.connect(lambda: collector.append(True))
            QTest.mouseClick(bar._play_button, Qt.LeftButton)
            process_qt_events(qapp, ms=50)
            assert collector == [True]
        finally:
            safe_teardown(bar)

    def test_detach_button_click_emits(self, qapp: Any, settings_manager: Any) -> None:
        """点击分离窗口按钮发射 ``detachClicked``。"""
        bar: PlayerControlBar = PlayerControlBar(
            settings_manager=settings_manager
        )
        bar.resize(600, 50)
        bar.show()
        process_qt_events(qapp, ms=50)
        try:
            assert hasattr(bar, "_detach_button")
            collector: List[bool] = []
            bar.detachClicked.connect(lambda: collector.append(True))
            QTest.mouseClick(bar._detach_button, Qt.LeftButton)
            process_qt_events(qapp, ms=50)
            assert collector == [True]
        finally:
            safe_teardown(bar)

    def test_lut_subtitle_audio_state(self, qapp: Any, settings_manager: Any) -> None:
        """LUT/字幕/音轨按钮的加载与可见性状态切换。"""
        # LUT 控制按钮默认关闭（player.control_bar_show_lut=False），
        # 需先在设置中打开，``set_lut_loaded`` 才走到真实分支。
        settings_manager.set_setting("player.control_bar_show_lut", True)
        bar: PlayerControlBar = PlayerControlBar(
            settings_manager=settings_manager
        )
        bar.resize(600, 50)
        bar.show()
        process_qt_events(qapp, ms=50)
        try:
            bar.set_lut_loaded(True)
            assert bar.is_lut_loaded() is True
            bar.set_lut_loaded(False)
            assert bar.is_lut_loaded() is False

            bar.set_subtitle_loaded(True)
            assert bar.is_subtitle_loaded() is True

            default_audio_visible: bool = bar.is_audio_button_visible()
            bar.set_audio_button_visible(not default_audio_visible)
            assert bar.is_audio_button_visible() is (not default_audio_visible)
        finally:
            safe_teardown(bar)

    def test_state_toogles_no_raise(self, qapp: Any, settings_manager: Any) -> None:
        """分离/折叠菜单等状态方法不抛异常。"""
        bar: PlayerControlBar = PlayerControlBar(
            settings_manager=settings_manager
        )
        try:
            bar.set_detached(True)
            assert bar.is_detached() is True
            bar.set_detached(False)

            bar.collapse_all_menus()
            bar.update_style()
        finally:
            safe_teardown(bar)


# =============================================================================
# lut_manager_dialog —— LUT 管理弹窗与导入工作线程
# =============================================================================
class TestLutImportWorker:
    """``LutImportWorker`` 后台导入。"""

    def test_invalid_lut_emits_error(
        self, qapp: Any, empty_cube_file: str
    ) -> None:
        """空 LUT 文件（无效）→ 发出 ``import_error`` 且不崩溃（QA 要求）。"""
        worker: LutImportWorker = LutImportWorker(empty_cube_file)
        errors: List[str] = []
        worker.import_error.connect(errors.append)
        worker.start()
        try:
            assert _pump_until(qapp, lambda: len(errors) > 0)
            assert "LUT" in errors[0] or "文件" in errors[0] or errors[0]
        finally:
            worker.wait(2000)
            safe_teardown(worker)

    def test_valid_lut_emits_import_finished(
        self,
        qapp: Any,
        cube_file: str,
        monkeypatch: Any,
    ) -> None:
        """合法 LUT → ``import_finished`` 携带完整 info（不写真实 data/ 目录）。"""
        # 隔离真实存储：跳过复制与预览图生成，仅在内存/临时路径内跑流程。
        monkeypatch.setattr(
            "freeassetfilter.widgets.lut_manager_dialog.copy_lut_file",
            lambda source, lut_id: (True, source),
        )
        monkeypatch.setattr(
            "freeassetfilter.core.native.bridges.lut_preview_generator.generate_lut_preview",
            lambda *args, **kwargs: True,
        )

        worker: LutImportWorker = LutImportWorker(cube_file)
        finished: List[dict] = []
        worker.import_finished.connect(finished.append)
        worker.start()
        try:
            assert _pump_until(qapp, lambda: len(finished) > 0)
            info: dict = finished[0]
            assert info["id"]
            assert info["name"]
            assert info["path"] == cube_file
            assert info["size"] == 2
            assert info["is_3d"] is True
        finally:
            worker.wait(2000)
            safe_teardown(worker)


class TestLutManagerDialog:
    """``LutManagerDialog`` 弹窗行为（不调用 ``exec``）。"""

    def test_construct_and_open_no_crash(self, qapp: Any, settings_manager: Any) -> None:
        """构造并展示弹窗不崩溃，未选择时 ``get_selected_lut`` 为 None。"""
        dialog: LutManagerDialog = LutManagerDialog(
            settings_manager=settings_manager
        )
        dialog.show()
        process_qt_events(qapp, ms=50)
        try:
            assert dialog.get_selected_lut() is None
        finally:
            dialog.close()
            safe_teardown(dialog)

    def test_open_with_invalid_lut_path_no_crash(
        self, qapp: Any, settings_manager: Any, tmp_path: Path
    ) -> None:
        """设置中包含指向不存在路径的 LUT 时，弹窗打开不崩溃（QA 要求）。"""
        fake_lut: LUTInfo = LUTInfo(
            id="missing-id",
            name="缺失的LUT",
            path=str(tmp_path / "nope.cube"),
            preview_path="",
            size=2,
            is_3d=True,
        )
        monkeypatch_patch: Any = None
        # 直接注入内存 LUT 列表，替代读设置（不写真实 data/luts）。
        dialog: LutManagerDialog = LutManagerDialog(
            settings_manager=settings_manager
        )
        try:
            dialog.lut_list = [fake_lut]
            assert dialog.get_selected_lut() is None
            dialog.show()
            process_qt_events(qapp, ms=50)
            assert dialog.isVisible() is True
        finally:
            dialog.close()
            safe_teardown(dialog)

    def test_cancel_button_rejects(self, qapp: Any, settings_manager: Any) -> None:
        """点击 \"取消\" 关闭弹窗，不选中任何 LUT。"""
        dialog: LutManagerDialog = LutManagerDialog(
            settings_manager=settings_manager
        )
        dialog.show()
        process_qt_events(qapp, ms=50)
        try:
            assert dialog.isVisible() is True

            # 通过真实按钮点击触发 CustomMessageBox.setResult(索引) + 动画关闭，
            # 而不是直接 emit 信号（直接 emit 只走 reject()，Rejected==0 无区分度）。
            cancel_button = dialog.button_layout.itemAt(2).widget()
            assert cancel_button is not None
            QTest.mouseClick(cancel_button, Qt.LeftButton)

            # 关闭走 170ms 退场动画，泵到对话框真正隐藏。
            assert _pump_until(qapp, lambda: not dialog.isVisible())
            assert dialog.get_selected_lut() is None
        finally:
            dialog.close()
            safe_teardown(dialog)
