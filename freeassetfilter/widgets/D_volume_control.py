#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 自定义音量控制组件
集成 CustomButton（图标模式）和 D_Volume 控件
用于在 video player 中提供自定义的音量控制功能
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QApplication
from PySide6.QtCore import Qt, Signal, QPoint, QEvent, QTimer
from PySide6.QtGui import QFont, QCursor

from .button_widgets import CustomButton
from .D_volume import D_Volume
from freeassetfilter.core.svg_renderer import SvgRenderer
import os


class DVolumeControl(QWidget):
    """
    自定义音量控制组件
    集成 CustomButton（图标模式）和 D_Volume 控件
    特点：
    - 使用 SVG 图标的 CustomButton 作为触发按钮
    - 点击按钮后在按钮上方显示 D_Volume 控件
    - 音量百分比文本与信号同步
    - 滑块位置控制音量大小
    - 与当前音量大小保持同步
    """

    valueChanged = Signal(int)
    mutedChanged = Signal(bool)
    menuShown = Signal()
    menuHidden = Signal()

    def __init__(self, parent=None):
        """
        初始化自定义音量控制组件

        Args:
            parent: 父窗口部件
        """
        super().__init__(parent)

        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())

        self._volume = 100
        self._muted = False
        self._menu_visible = False

        self._icon_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons')
        self._volume_icon_path = os.path.join(self._icon_dir, 'speaker.svg')
        self._mute_icon_path = os.path.join(self._icon_dir, 'speaker_slash.svg')

        self._init_ui()

    def _init_ui(self):
        """初始化UI组件"""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._volume_button = CustomButton(
            self._volume_icon_path,
            button_type="normal",
            display_mode="icon",
            tooltip_text="音量控制"
        )

        self._update_volume_icon()

        self._d_volume = D_Volume(self)
        self._d_volume.set_target_widget(self._volume_button)
        self._d_volume.set_volume(self._volume)

        main_layout.addWidget(self._volume_button)

        self._volume_button.clicked.connect(self._toggle_volume_menu)
        self._d_volume.progressValueChanged.connect(self._on_volume_slider_changed)
        self._d_volume.progressInteractionEnded.connect(self._on_slider_interaction_ended)

        self._top_window = None
        self._focus_restore_timer = QTimer(self)
        self._focus_restore_timer.setSingleShot(True)
        self._focus_restore_timer.setInterval(50)
        self._focus_restore_timer.timeout.connect(self._restore_parent_focus)

        self._debounce_hide_on_move = False
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._clear_move_debounce)

    def _update_volume_icon(self):
        """更新音量图标"""
        icon_path = self._mute_icon_path if (self._muted or self._volume == 0) else self._volume_icon_path

        self._volume_button._icon_path = icon_path
        self._volume_button._display_mode = "icon"
        self._volume_button._render_icon()
        self._volume_button.update()

    def _toggle_volume_menu(self):
        """切换音量菜单显示/隐藏"""
        if self._menu_visible:
            self._hide_volume_menu()
        else:
            self._show_volume_menu()

    def _show_volume_menu(self):
        """显示音量菜单"""
        if not self._menu_visible:
            self._volume_button.installEventFilter(self)
            self._top_window = self.window()
            if self._top_window:
                self._top_window.installEventFilter(self)
            # 安装全局事件过滤器，检测点击外部区域关闭菜单
            app = QApplication.instance()
            if app:
                app.installEventFilter(self)
            self._d_volume.show()
            self._menu_visible = True
            self.menuShown.emit()
            self._debounce_hide_on_move = True
            self._debounce_timer.start()
            QTimer.singleShot(0, self._restore_parent_focus)

    def _hide_volume_menu(self):
        """隐藏音量菜单"""
        if self._menu_visible:
            self._debounce_hide_on_move = False
            self._debounce_timer.stop()
            app = QApplication.instance()
            if app:
                app.removeEventFilter(self)
            self._volume_button.removeEventFilter(self)
            if self._top_window:
                self._top_window.removeEventFilter(self)
                self._top_window = None
            self._d_volume.hide()
            self._menu_visible = False
            self.menuHidden.emit()
            self._restore_parent_focus()

    def _on_volume_slider_changed(self, value):
        """
        音量滑块值变化处理

        Args:
            value: 新的音量值
        """
        self.set_volume(value)
        if self._menu_visible:
            self._focus_restore_timer.start()

    def _on_slider_interaction_ended(self):
        """滑动条交互结束后恢复全屏窗口焦点"""
        self._focus_restore_timer.stop()
        self._restore_parent_focus()

    def _restore_parent_focus(self):
        """恢复顶层窗口焦点，防止音量弹窗导致全屏窗口失焦"""
        top_window = self.window()
        if top_window and hasattr(top_window, 'activateWindow'):
            top_window.activateWindow()
            if hasattr(top_window, 'setFocus'):
                top_window.setFocus()

    def _clear_move_debounce(self):
        """清除 Move 事件防抖标志"""
        self._debounce_hide_on_move = False

    def set_volume(self, volume):
        """
        设置音量值

        Args:
            volume: 音量值，范围0-100
        """
        if volume < 0:
            volume = 0
        elif volume > 100:
            volume = 100

        if self._volume != volume:
            self._volume = volume
            self._d_volume.set_volume(volume)
            self.valueChanged.emit(volume)

            if volume > 0 and self._muted:
                self._muted = False

            self._update_volume_icon()

    def volume(self):
        """
        获取当前音量值

        Returns:
            int: 当前音量值，范围0-100
        """
        return self._volume

    def set_muted(self, muted):
        """
        设置静音状态

        Args:
            muted: 是否静音
        """
        if self._muted != muted:
            self._muted = muted
            self._update_volume_icon()
            self.mutedChanged.emit(self._muted)

    def muted(self):
        return self._muted

    @property
    def volume_button(self):
        return self._volume_button

    @property
    def volume_widget(self):
        return self._d_volume

    def toggle_mute(self):
        """切换静音状态"""
        self.set_muted(not self._muted)

    def sync_volume_from_player(self, volume):
        """
        从播放器核心同步音量值

        Args:
            volume: 播放器当前的音量值，范围0-100
        """
        self.set_volume(volume)

    def update_style(self):
        """更新样式，用于主题变化时"""
        self._d_volume.update_style()
        self._volume_button.update_style()

    def resizeEvent(self, event):
        """窗口大小变化事件"""
        super().resizeEvent(event)

    def mousePressEvent(self, event):
        """鼠标按下事件"""
        super().mousePressEvent(event)

    def enterEvent(self, event):
        """鼠标进入事件"""
        super().enterEvent(event)

    def leaveEvent(self, event):
        """鼠标离开事件 - 禁用hover检测退出"""
        pass

    def _is_click_on_menu_or_button(self, obj):
        """检查点击目标是否在音量按钮或音量弹出菜单上"""
        # WindowDoesNotAcceptFocus 会导致点击事件被路由到父窗口，obj 参数不可靠，
        # 改用 QApplication.widgetAt() 获取光标下实际控件
        clicked = QApplication.widgetAt(QCursor.pos())
        if clicked:
            obj = clicked
        if not isinstance(obj, QWidget):
            return False
        if obj is self._volume_button or (self._volume_button and self._volume_button.isAncestorOf(obj)):
            return True
        menu_widget = self._d_volume.hover_menu
        if menu_widget:
            if obj is menu_widget or menu_widget.isAncestorOf(obj):
                return True
        return False

    def eventFilter(self, obj, event):
        """事件过滤器 - 监听全局点击外部关闭，以及按钮/窗口移动关闭"""
        # 点击音量菜单外部区域时关闭菜单
        if event.type() == QEvent.MouseButtonPress and self._menu_visible:
            if not self._is_click_on_menu_or_button(obj):
                self._hide_volume_menu()
        # 按钮或窗口移动时关闭菜单（300ms 防抖，与 D_HoverMenu 同步）
        if event.type() == QEvent.Move and self._menu_visible and not self._debounce_hide_on_move:
            if obj == self._volume_button or (self._top_window and obj == self._top_window):
                # 过滤 _restore_parent_focus() → activateWindow() 触发的虚假 Move 事件
                if hasattr(event, 'oldPos') and event.pos() == event.oldPos():
                    return super().eventFilter(obj, event)
                self._hide_volume_menu()
        return super().eventFilter(obj, event)
