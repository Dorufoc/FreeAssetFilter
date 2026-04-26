#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 悬浮详细信息组件
当鼠标放到控件上时，显示当前鼠标指针所指向的文本内容
鼠标静止1秒才会显示，鼠标移动或点击则立即隐藏

使用 GlobalMouseMonitor 全局鼠标钩子来检测鼠标移动和点击状态，
确保 tooltip 在鼠标移动或点击时能够及时隐藏，即使鼠标仍在控件范围内。
"""

import weakref

from PySide6.QtCore import (
    Property,
    QEvent,
    QPoint,
    QRect,
    QTimer,
    Qt,
    QEasingCurve,
    QPropertyAnimation,
)
from PySide6.QtGui import QColor, QBrush, QCursor, QFont, QPainter, QPen, QTransform
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from freeassetfilter.utils.app_logger import debug
from freeassetfilter.utils.global_mouse_monitor import GlobalMouseMonitor


class HoverTooltip(QWidget):
    """
    悬浮详细信息组件
    特点：
    - 鼠标静止1秒后显示
    - 鼠标移动或点击则立即隐藏（使用全局鼠标钩子检测）
    - 即使鼠标仍在控件范围内，移动或点击也会隐藏
    - 白色圆角卡片样式
    - 灰色400字重文字
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # 设置窗口标志
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 生命周期与安全控制
        self._safe_mode = False
        self._disposed = False
        self._cleaning_up = False

        # 创建标签显示文本内容
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        app = QApplication.instance()
        self.dpi_scale = getattr(app, "dpi_scale_factor", 1.0) if app else 1.0

        # 设置字体样式：创建一个新的字体实例，确保不受调用组件字体影响
        font = QFont()
        if app and hasattr(app, "global_font"):
            global_font = app.global_font
            font.setFamily(global_font.family())
            font.setStyle(global_font.style())
            font.setWeight(global_font.weight())
            global_size = global_font.pointSizeF()
        else:
            global_size = 10.0

        new_size = max(1, int(global_size * 0.8))
        font.setPointSize(new_size)
        self.label.setFont(font)

        # 应用初始样式
        self.update_style()

        # 显示定时器（鼠标静止后显示tooltip）
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(1000)  # 1秒延迟
        self.timer.timeout.connect(self.show_tooltip)

        # 鼠标位置跟踪
        self.last_mouse_pos = QPoint()
        self.target_widgets = []  # 存储目标控件的弱引用列表

        # 鼠标活动监控器（全局鼠标钩子）
        self._mouse_monitor = GlobalMouseMonitor(self)
        self._mouse_monitor.mouse_moved.connect(self._on_global_mouse_moved)
        self._mouse_monitor.mouse_clicked.connect(self._on_global_mouse_clicked)
        self._mouse_monitor.mouse_scrolled.connect(self._on_global_mouse_scrolled)
        self._mouse_monitor_active = False

        # 动画相关属性
        self._is_animating = False
        self._fade_duration = 200
        self._opacity_value = 1.0
        self._scale_value = 1.0

        self._fade_animation = QPropertyAnimation(self, b"_tooltip_opacity")
        self._fade_animation.setDuration(self._fade_duration)
        self._fade_animation.setEasingCurve(QEasingCurve.InOutQuad)
        self._fade_animation.finished.connect(self._on_animation_finished)

        self._scale_animation = QPropertyAnimation(self, b"_tooltip_scale")
        self._scale_animation.setDuration(self._fade_duration)
        self._scale_animation.setEasingCurve(QEasingCurve.InOutQuad)

        self.hide()

        destroyed_signal = getattr(self, "destroyed", None)
        if destroyed_signal is not None:
            try:
                destroyed_signal.connect(self._on_self_destroyed)
            except (RuntimeError, TypeError):
                pass

    # --------------------------
    # 生命周期与安全控制
    # --------------------------
    def _is_usable(self):
        """检查当前对象是否仍可安全使用"""
        return not self._disposed and not self._cleaning_up

    def cleanup(self):
        """
        显式释放 tooltip 占用的资源。
        该方法是幂等的，可重复调用。
        """
        if self._disposed or self._cleaning_up:
            return

        self._cleaning_up = True

        try:
            if hasattr(self, "timer") and self.timer:
                self.timer.stop()
        except RuntimeError as e:
            debug(f"HoverTooltip timer stop error during cleanup: {e}")

        try:
            self._stop_mouse_monitor()
        except RuntimeError as e:
            debug(f"HoverTooltip mouse monitor stop error during cleanup: {e}")

        try:
            if hasattr(self, "_fade_animation") and self._fade_animation:
                self._fade_animation.stop()
        except RuntimeError as e:
            debug(f"HoverTooltip fade animation stop error during cleanup: {e}")

        try:
            if hasattr(self, "_scale_animation") and self._scale_animation:
                self._scale_animation.stop()
        except RuntimeError as e:
            debug(f"HoverTooltip scale animation stop error during cleanup: {e}")

        self._detach_all_target_widgets()

        try:
            self._is_animating = False
            self._opacity_value = 1.0
            self._scale_value = 1.0
            self.setWindowOpacity(1.0)
        except RuntimeError:
            pass

        try:
            super().hide()
        except RuntimeError as e:
            debug(f"HoverTooltip hide error during cleanup: {e}")

        self._disposed = True
        self._cleaning_up = False

    def _on_self_destroyed(self, obj=None):
        """对象销毁前的兜底清理"""
        try:
            self.cleanup()
        except Exception as e:
            debug(f"HoverTooltip cleanup on destroyed failed: {e}")

    def _detach_all_target_widgets(self):
        """移除所有目标控件上的事件过滤器并清理失效引用"""
        valid_refs = []

        for ref in getattr(self, "target_widgets", []):
            try:
                target = ref()
            except RuntimeError:
                continue

            if target is None:
                continue

            try:
                _ = target.objectName()
            except RuntimeError:
                continue

            try:
                target.removeEventFilter(self)
            except (RuntimeError, TypeError):
                pass

            if not self._disposed:
                valid_refs.append(ref)

        self.target_widgets = [] if self._disposed else valid_refs

    def _prune_invalid_targets(self):
        """清理已失效的弱引用，同时移除不可用控件上的事件过滤器残留"""
        valid_refs = []

        for ref in self.target_widgets:
            try:
                target = ref()
            except RuntimeError:
                continue

            if target is None:
                continue

            try:
                _ = target.objectName()
            except RuntimeError:
                continue

            valid_refs.append(ref)

        self.target_widgets = valid_refs

    # --------------------------
    # 样式与动画
    # --------------------------
    def update_style(self):
        """
        更新组件样式
        """
        if self._disposed:
            return

        app = QApplication.instance()
        if app and hasattr(app, "settings_manager"):
            settings_manager = app.settings_manager
        else:
            from freeassetfilter.core.settings_manager import SettingsManager

            settings_manager = SettingsManager()

        secondary_color = settings_manager.get_setting(
            "appearance.colors.secondary_color", "#333333"
        )

        self.setStyleSheet(
            f"""
            QWidget {{
                background: transparent;
                border: none;
            }}
            QLabel {{
                color: {secondary_color};
                background: transparent;
                padding: 4px;
                font-weight: 400;
            }}
        """
        )

        self.update()

    def _get_opacity(self):
        """获取透明度"""
        return self._opacity_value

    def _set_opacity(self, opacity):
        """设置透明度"""
        if self._disposed:
            return
        self._opacity_value = max(0.0, min(1.0, opacity))
        self.setWindowOpacity(self._opacity_value)

    _tooltip_opacity = Property(float, _get_opacity, _set_opacity)

    def _get_scale(self):
        """获取缩放比例"""
        return self._scale_value

    def _set_scale(self, scale):
        """设置缩放比例"""
        if self._disposed:
            return
        self._scale_value = max(0.01, min(2.0, scale))
        self.update()

    _tooltip_scale = Property(float, _get_scale, _set_scale)

    def _on_animation_finished(self):
        """动画结束处理"""
        if self._disposed:
            return

        try:
            if self._opacity_value <= 0.01:
                super().hide()
                self._opacity_value = 1.0
            self._is_animating = False
        except RuntimeError:
            pass

    def _fade_in(self):
        """淡入显示（透明度0→1，缩放0.5→1）"""
        if not self._is_usable() or self._is_animating:
            return

        self._is_animating = True

        try:
            self._fade_animation.stop()
            self._scale_animation.stop()

            self._opacity_value = 0.0
            self._scale_value = 0.5
            self.setWindowOpacity(0.0)

            super().show()

            self._fade_animation.setStartValue(0.0)
            self._fade_animation.setEndValue(1.0)
            self._fade_animation.start()

            self._scale_animation.setStartValue(0.5)
            self._scale_animation.setEndValue(1.0)
            self._scale_animation.start()
        except RuntimeError as e:
            debug(f"HoverTooltip fade in animation error: {e}")
            self._is_animating = False
            self._opacity_value = 1.0
            self._scale_value = 1.0
            try:
                self.setWindowOpacity(1.0)
                super().show()
            except RuntimeError:
                pass

    def _fade_out(self):
        """淡出隐藏（透明度1→0，缩放1→0.5）"""
        if not self._is_usable():
            return

        if not self.isVisible():
            self._is_animating = False
            return

        if self._is_animating:
            return

        self._is_animating = True

        try:
            self._fade_animation.stop()
            self._scale_animation.stop()

            self._fade_animation.setStartValue(self._get_opacity())
            self._fade_animation.setEndValue(0.0)
            self._fade_animation.start()

            self._scale_animation.setStartValue(self._get_scale())
            self._scale_animation.setEndValue(0.5)
            self._scale_animation.start()
        except RuntimeError as e:
            debug(f"HoverTooltip fade out animation error: {e}")
            self._is_animating = False
            try:
                super().hide()
            except RuntimeError:
                pass

    # --------------------------
    # 目标控件管理
    # --------------------------
    def set_target_widget(self, widget):
        """设置要监听的目标控件"""
        if not self._is_usable() or widget is None:
            return

        self._prune_invalid_targets()

        for ref in self.target_widgets:
            try:
                existing_widget = ref()
            except RuntimeError:
                continue

            if existing_widget is None:
                continue

            try:
                _ = existing_widget.objectName()
            except RuntimeError:
                continue

            if existing_widget is widget:
                return

        ref = weakref.ref(widget)
        self.target_widgets.append(ref)

        try:
            widget.installEventFilter(self)
        except RuntimeError as e:
            debug(f"HoverTooltip installEventFilter error: {e}")
            self._prune_invalid_targets()
            return

        destroyed_signal = getattr(widget, "destroyed", None)
        if destroyed_signal is not None:
            try:
                destroyed_signal.connect(self._on_target_widget_destroyed)
            except (RuntimeError, TypeError):
                pass

    def _on_target_widget_destroyed(self, obj=None):
        """
        目标控件被销毁时的处理函数
        """
        if self._disposed:
            return

        try:
            self.timer.stop()
        except RuntimeError as e:
            debug(f"HoverTooltip timer stop error: {e}")

        self._stop_mouse_monitor()

        try:
            self._fade_animation.stop()
            self._scale_animation.stop()
        except RuntimeError:
            pass

        try:
            self._is_animating = False
            super().hide()
        except RuntimeError as e:
            debug(f"HoverTooltip hide error: {e}")

        self._prune_invalid_targets()

    # --------------------------
    # 鼠标监控
    # --------------------------
    def _start_mouse_monitor(self):
        """启动全局鼠标活动监控"""
        if not self._is_usable():
            return

        if not self._mouse_monitor_active:
            started = self._mouse_monitor.start()
            self._mouse_monitor_active = bool(started)

    def _stop_mouse_monitor(self):
        """停止全局鼠标活动监控"""
        if self._mouse_monitor_active:
            try:
                self._mouse_monitor.stop()
            finally:
                self._mouse_monitor_active = False

    def _on_global_mouse_moved(self):
        """
        全局鼠标移动回调函数
        """
        if not self._is_usable():
            return

        if self.isVisible():
            self._fade_out()

        current_widget = QApplication.widgetAt(QCursor.pos())
        is_over_target = False

        for ref in self.target_widgets:
            try:
                target = ref()
            except RuntimeError:
                continue

            if target is None:
                continue

            try:
                _ = target.objectName()
            except RuntimeError:
                continue

            if current_widget:
                try:
                    _ = current_widget.objectName()
                except RuntimeError:
                    current_widget = None

            if current_widget == target or (current_widget and target.isAncestorOf(current_widget)):
                is_over_target = True
                break

        if is_over_target:
            self.last_mouse_pos = QCursor.pos()
            self.timer.start()
        else:
            self.timer.stop()
            self._stop_mouse_monitor()

    def _on_global_mouse_clicked(self):
        """
        全局鼠标点击回调函数
        """
        if not self._is_usable():
            return

        if self.isVisible():
            self._fade_out()

        self.timer.stop()

    def _on_global_mouse_scrolled(self):
        """
        全局鼠标滚轮滚动回调函数
        """
        if not self._is_usable():
            return

        if self.isVisible():
            self._fade_out()

        self.timer.stop()

    # --------------------------
    # 事件处理
    # --------------------------
    def eventFilter(self, obj, event):
        """事件过滤器，监听鼠标事件"""
        if not self._is_usable():
            return False

        is_target = False
        for ref in self.target_widgets:
            try:
                target = ref()
            except RuntimeError:
                continue

            if target is None:
                continue

            try:
                _ = target.objectName()
            except RuntimeError:
                continue

            if target is obj:
                is_target = True
                break

        if is_target:
            event_type = event.type()

            if event_type == QEvent.MouseMove:
                self.last_mouse_pos = event.globalPos()
                self.timer.start()
                self._fade_out()
            elif event_type == QEvent.Enter:
                self.last_mouse_pos = event.globalPos()
                self.timer.start()
                self._start_mouse_monitor()
            elif event_type == QEvent.Leave:
                self._fade_out()
                self.timer.stop()
            elif event_type == QEvent.MouseButtonPress or event_type == QEvent.MouseButtonRelease:
                self._fade_out()
                self.timer.stop()
                self._stop_mouse_monitor()
            elif event_type == QEvent.MouseButtonDblClick:
                self._fade_out()
                self.timer.stop()
                self._stop_mouse_monitor()

        return False

    def hideEvent(self, event):
        """隐藏时确保停止计时器与鼠标监控"""
        if not self._disposed:
            try:
                self.timer.stop()
            except RuntimeError:
                pass

            try:
                self._stop_mouse_monitor()
            except RuntimeError:
                pass

        super().hideEvent(event)

    def closeEvent(self, event):
        """关闭时显式清理资源"""
        self.cleanup()
        super().closeEvent(event)

    def set_safe_mode(self, enabled):
        """
        设置安全模式，防止在重建过程中意外显示

        Args:
            enabled (bool): 是否启用安全模式
        """
        if self._disposed:
            return

        self._safe_mode = enabled
        if enabled:
            try:
                self.timer.stop()
                self._stop_mouse_monitor()
                self._fade_out()
            except (RuntimeError, AttributeError):
                pass

    # --------------------------
    # Tooltip 显示与文本获取
    # --------------------------
    def _show_text_at_global_pos(self, text, global_pos, animated=True):
        """在指定全局坐标显示指定文本"""
        if not self._is_usable() or not text:
            return

        self.label.setText(text)

        self.label.adjustSize()
        margin = int(4 * self.dpi_scale)
        self.resize(self.label.width() + margin, self.label.height() + margin)

        label_x = (self.width() - self.label.width()) // 2
        label_y = (self.height() - self.label.height()) // 2
        self.label.move(label_x, label_y)

        pos = QPoint(global_pos)
        pos.setY(pos.y() + int(5 * self.dpi_scale))

        screen = QApplication.primaryScreen()
        current_screen = self.screen()
        screen_rect = screen.geometry() if screen else (current_screen.geometry() if current_screen else QRect())
        margin = int(2.5 * self.dpi_scale)

        if screen_rect.isValid():
            if pos.x() + self.width() > screen_rect.width():
                pos.setX(screen_rect.width() - self.width() - margin)
            if pos.y() + self.height() > screen_rect.height():
                pos.setY(screen_rect.height() - self.height() - margin)

        self.move(pos)

        if animated and not self.isVisible():
            self._fade_in()
        else:
            try:
                self._fade_animation.stop()
                self._scale_animation.stop()
            except RuntimeError:
                pass

            try:
                self._is_animating = False
                self._opacity_value = 1.0
                self._scale_value = 1.0
                self.setWindowOpacity(1.0)
                super().show()
                self.update()
            except RuntimeError:
                pass

    def show_text_at(self, text, global_pos):
        """立即在指定位置显示文本，用于替代 Qt 原生 QToolTip.showText"""
        if not self._is_usable() or self._safe_mode or not text:
            return

        try:
            self.timer.stop()
        except RuntimeError:
            pass

        self._show_text_at_global_pos(text, global_pos, animated=False)

    def hide_tooltip(self):
        """隐藏 tooltip，用于替代 Qt 原生 QToolTip.hideText"""
        if not self._is_usable():
            return

        try:
            self.timer.stop()
        except RuntimeError:
            pass

        self._fade_out()

    def show_tooltip(self):
        """显示悬浮提示框"""
        if not self._is_usable() or self._safe_mode:
            return

        self._prune_invalid_targets()

        visible_widgets = []
        for ref in self.target_widgets:
            try:
                target = ref()
            except RuntimeError:
                continue

            if target is None:
                continue

            try:
                _ = target.objectName()
            except RuntimeError:
                continue

            if target.isVisible():
                visible_widgets.append(target)

        if not visible_widgets:
            return

        widget = QApplication.widgetAt(self.last_mouse_pos)
        if not widget:
            return

        current_widget = None
        for ref in self.target_widgets:
            try:
                target = ref()
            except RuntimeError:
                continue

            if target is None:
                continue

            try:
                _ = target.objectName()
            except RuntimeError:
                continue

            if widget:
                try:
                    _ = widget.objectName()
                except RuntimeError:
                    widget = None

            if widget == target or (widget and target.isAncestorOf(widget)):
                current_widget = target
                break

        if not current_widget:
            return

        text = self.get_text_at_position()
        if not text:
            return

        self._show_text_at_global_pos(text, self.last_mouse_pos, animated=True)

    def get_text_at_position(self, widget=None):
        """获取鼠标位置的文本内容"""
        if self._disposed:
            return ""

        try:
            return self._get_text_at_position_internal(widget)
        except RuntimeError:
            return ""

    def _build_file_card_tooltip(self, file_path, display_name="", file_info=None):
        """构建文件卡片统一 tooltip 文本。"""
        import os
        from PySide6.QtCore import QFileInfo

        file_info = file_info or {}
        file_path = str(file_path or file_info.get("path", "") or "")
        qfile_info = QFileInfo(file_path)
        file_name = (
            str(display_name or "")
            or str(file_info.get("display_name", "") or "")
            or str(file_info.get("name", "") or "")
            or os.path.basename(file_path)
            or file_path
        )

        exists = qfile_info.exists()
        is_dir = bool(file_info.get("is_dir", False)) if "is_dir" in file_info else qfile_info.isDir()
        suffix = str(file_info.get("suffix", "") or qfile_info.suffix() or "").lstrip(".")
        file_type = "文件夹" if is_dir else (f".{suffix}" if suffix else "文件")
        abs_path = os.path.normpath(qfile_info.absoluteFilePath()) if file_path else ""

        if exists:
            created_time = (
                qfile_info.birthTime().toString("yyyy-MM-dd HH:mm:ss")
                if qfile_info.birthTime().isValid()
                else "未知"
            )
            modified_time = (
                qfile_info.lastModified().toString("yyyy-MM-dd HH:mm:ss")
                if qfile_info.lastModified().isValid()
                else "未知"
            )
        else:
            created_time = "文件不存在"
            modified_time = "文件不存在"

        tooltip_text = f"名称: {file_name}\n"
        tooltip_text += f"类型: {file_type}\n"
        tooltip_text += f"创建时间: {created_time}\n"
        tooltip_text += f"修改时间: {modified_time}\n"
        tooltip_text += f"路径: {abs_path}"

        return tooltip_text

    def _build_horizontal_card_tooltip(self, card):
        """构建横向卡片的统一 tooltip 文本"""
        return self._build_file_card_tooltip(
            getattr(card, "file_path", ""),
            display_name=getattr(card, "_display_name", "") or "",
        )

    def _build_view_index_tooltip(self, widget):
        """从虚拟化 QListView 命中的 index 构建文件 tooltip。"""
        from PySide6.QtWidgets import QListView

        view = widget if isinstance(widget, QListView) else None
        if view is None and widget is not None:
            parent = widget.parent()
            if isinstance(parent, QListView):
                view = parent
        if view is None or view.model() is None:
            return ""

        viewport = view.viewport()
        if viewport is None:
            return ""

        pos = viewport.mapFromGlobal(self.last_mouse_pos)
        if not viewport.rect().contains(pos):
            return ""

        index = view.indexAt(pos)
        if not index.isValid():
            return ""

        model = view.model()
        if hasattr(model, "get_file_info"):
            file_info = model.get_file_info(index)
        else:
            file_info = {}

        file_path = file_info.get("path", "")
        if not file_path and hasattr(model, "FilePathRole"):
            file_path = index.data(model.FilePathRole) or ""

        display_name = (
            file_info.get("display_name", "")
            or file_info.get("name", "")
            or index.data()
            or ""
        )
        if not file_path:
            return ""

        return self._build_file_card_tooltip(file_path, display_name=display_name, file_info=file_info)

    def _get_text_at_position_internal(self, widget=None):
        """获取鼠标位置的文本内容（内部实现）"""
        direct_widget = QApplication.widgetAt(self.last_mouse_pos)
        if direct_widget:
            try:
                _ = direct_widget.objectName()
            except RuntimeError:
                return ""

            index_tooltip = self._build_view_index_tooltip(direct_widget)
            if index_tooltip:
                return index_tooltip

            from .file_horizontal_card import CustomFileHorizontalCard

            current_widget = direct_widget
            while current_widget:
                if isinstance(current_widget, CustomFileHorizontalCard):
                    return self._build_horizontal_card_tooltip(current_widget)
                current_widget = current_widget.parent()

            from .button_widgets import CustomButton

            if isinstance(direct_widget, CustomButton):
                if direct_widget._tooltip_text:
                    return direct_widget._tooltip_text
                elif direct_widget._display_mode == "text":
                    text_attr = direct_widget.text
                    if callable(text_attr):
                        text_value = text_attr()
                        if text_value:
                            return text_value
                    elif text_attr:
                        return text_attr
                elif direct_widget._display_mode == "icon" and direct_widget._icon_path:
                    svg_tooltip_map = {
                        "favorites.svg": "收藏夹",
                        "back.svg": "返回上一次退出程序时的目录",
                        "forward.svg": "前进到下一次目录",
                        "refresh.svg": "刷新",
                        "search.svg": "搜索",
                        "close.svg": "关闭",
                        "folder.svg": "文件夹",
                        "file.svg": "文件",
                        "add.svg": "添加",
                        "remove.svg": "移除",
                        "edit.svg": "编辑",
                        "settings.svg": "设置",
                        "help.svg": "帮助",
                        "info.svg": "信息",
                        "trash.svg": "清空所有项目",
                    }

                    import os

                    svg_filename = os.path.basename(direct_widget._icon_path)
                    return svg_tooltip_map.get(svg_filename, svg_filename)

            from .setting_widgets import CustomSettingItem

            if isinstance(direct_widget, CustomSettingItem) or isinstance(direct_widget.parent(), CustomSettingItem):
                setting_item = direct_widget if isinstance(direct_widget, CustomSettingItem) else direct_widget.parent()
                if setting_item._tooltip_text:
                    return setting_item._tooltip_text

                tooltip_parts = []
                if setting_item.text:
                    tooltip_parts.append(f"{setting_item.text}")
                if setting_item.secondary_text:
                    tooltip_parts.append(f"{setting_item.secondary_text}")
                if tooltip_parts:
                    return "\n".join(tooltip_parts)
                return ""

            if direct_widget.objectName() == "FileBlockCard" or (
                hasattr(direct_widget.parent(), "objectName")
                and direct_widget.parent().objectName() == "FileBlockCard"
            ):
                card = direct_widget if direct_widget.objectName() == "FileBlockCard" else direct_widget.parent()
                if hasattr(card, "file_info"):
                    file_info = card.file_info
                    return self._build_file_card_tooltip(
                        file_info.get("path", ""),
                        display_name=file_info.get("name", ""),
                        file_info=file_info,
                    )

            if hasattr(direct_widget, "text"):
                text_attr = direct_widget.text
                if callable(text_attr):
                    text_value = text_attr()
                    if text_value:
                        return text_value
                elif text_attr:
                    return text_attr

        if not widget:
            widget = direct_widget
            if not widget:
                return ""

        def find_text_in_children(w):
            if hasattr(w, "text"):
                text_attr = w.text
                if callable(text_attr):
                    text_value = text_attr()
                    if text_value:
                        return text_value
                elif text_attr:
                    return text_attr

            if hasattr(w, "objectName") and w.objectName() == "FileCard":
                if hasattr(w, "file_info"):
                    file_info = w.file_info
                    file_name = file_info["name"]
                    file_path = file_info["path"]
                    return f"{file_name}\n{file_path}"

            if hasattr(w, "itemAt"):
                pos = w.mapFromGlobal(self.last_mouse_pos)
                item = w.itemAt(pos)
                if item and hasattr(item, "text"):
                    text_attr = item.text
                    if callable(text_attr):
                        return text_attr()
                    return text_attr

            from PySide6.QtWidgets import QLayout, QWidget

            for child in w.children():
                if isinstance(child, QWidget):
                    if child.isVisible():
                        child_rect = child.rect()
                        child_global_pos = child.mapToGlobal(QPoint(0, 0))
                        mouse_in_child = QRect(child_global_pos, child_rect.size()).contains(self.last_mouse_pos)

                        if mouse_in_child:
                            text = find_text_in_children(child)
                            if text:
                                return text
                elif isinstance(child, QLayout):
                    for i in range(child.count()):
                        layout_item = child.itemAt(i)
                        if layout_item:
                            if layout_item.widget():
                                layout_widget = layout_item.widget()
                                if layout_widget.isVisible():
                                    layout_widget_rect = layout_widget.rect()
                                    layout_widget_global_pos = layout_widget.mapToGlobal(QPoint(0, 0))
                                    mouse_in_layout_widget = QRect(
                                        layout_widget_global_pos, layout_widget_rect.size()
                                    ).contains(self.last_mouse_pos)

                                    if mouse_in_layout_widget:
                                        text = find_text_in_children(layout_widget)
                                        if text:
                                            return text
                            elif layout_item.layout():
                                text = find_text_in_children(layout_item.layout())
                                if text:
                                    return text

            return ""

        if hasattr(widget, "text"):
            text_attr = widget.text
            if callable(text_attr):
                text_value = text_attr()
                if text_value:
                    return text_value
            elif text_attr:
                return text_attr

        text = find_text_in_children(widget)
        if text:
            return text

        if direct_widget:
            parent = direct_widget.parent()
            while parent:
                if hasattr(parent, "text"):
                    text_attr = parent.text
                    if callable(text_attr):
                        text_value = text_attr()
                        if text_value:
                            return text_value
                    elif text_attr:
                        return text_attr
                parent = parent.parent()

        return ""

    def paintEvent(self, event):
        """绘制圆角卡片，并在绘制时应用缩放效果"""
        if self._disposed:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        if abs(self._scale_value - 1.0) > 0.01:
            transform = QTransform()
            center_x = self.width() / 2
            center_y = self.height() / 2
            transform.translate(center_x, center_y)
            transform.scale(self._scale_value, self._scale_value)
            transform.translate(-center_x, -center_y)
            painter.setTransform(transform)

        app = QApplication.instance()
        if app and hasattr(app, "settings_manager"):
            settings_manager = app.settings_manager
        else:
            from freeassetfilter.core.settings_manager import SettingsManager

            settings_manager = SettingsManager()

        current_colors = settings_manager.get_setting("appearance.colors", {})
        base_color = current_colors.get("base_color", "#ffffff")
        normal_color = current_colors.get("normal_color", "#333333")

        border_pen = QPen(QColor(normal_color))
        border_pen.setWidth(1)
        painter.setPen(border_pen)

        brush = QBrush(QColor(base_color))
        painter.setBrush(brush)

        rect = QRect(0, 0, self.width() - 1, self.height() - 1)
        radius = 4
        painter.drawRoundedRect(rect, radius, radius)
