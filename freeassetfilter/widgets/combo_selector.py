from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton,
    QApplication, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QFont, QPainter, QPen, QColor, QBrush, QPolygonF

from freeassetfilter.widgets.dropdown_menu import CustomDropdownMenu
from freeassetfilter.utils.app_logger import debug


class _ArrowButton(QPushButton):
    """带双向箭头（↑↓）的方形按钮，用于 ComboSelector 的触发端。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: rgba(128, 128, 128, 0.15);
            }
            QPushButton:pressed {
                background-color: rgba(128, 128, 128, 0.25);
            }
        """)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        cx = w // 2
        cy = h // 2

        app = QApplication.instance()
        accent_color = "#007AFF"
        if app and hasattr(app, "settings_manager"):
            accent_color = app.settings_manager.get_setting(
                "appearance.colors.accent_color", "#007AFF"
            )
        pen = QPen(QColor(accent_color))
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.setBrush(QColor(accent_color))

        tri_size = 4
        # 上三角
        up_tri = QPolygonF([
            QPointF(cx, cy - tri_size - 3),
            QPointF(cx - tri_size, cy - 1),
            QPointF(cx + tri_size, cy - 1),
        ])
        painter.drawPolygon(up_tri)

        # 下三角
        down_tri = QPolygonF([
            QPointF(cx, cy + tri_size + 3),
            QPointF(cx - tri_size, cy + 1),
            QPointF(cx + tri_size, cy + 1),
        ])
        painter.drawPolygon(down_tri)

        painter.end()


class ComboSelector(QWidget):
    """组合式下拉选择控件。

    布局：
    ┌──────────────────────────┬──────┐
    │  当前选项文本标签          │ [↕]  │
    └──────────────────────────┴──────┘

    左侧 QLabel 显示当前选中的选项名称，
    右侧 _ArrowButton 点击弹出 CustomDropdownMenu。
    """

    currentIndexChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        app = QApplication.instance()
        self.dpi_scale = getattr(app, "dpi_scale_factor", 1.0)
        self.global_font = getattr(app, "global_font", QFont())

        self._items: List[str] = []
        self._current_text: str = ""

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setMinimumHeight(int(28 * self.dpi_scale))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.text_label = QLabel("")
        self.text_label.setFont(self.global_font)
        self.text_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.text_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.text_label, 1)

        layout.addSpacing(4)

        self.arrow_btn = _ArrowButton(self)
        self.arrow_btn.clicked.connect(self._show_dropdown)
        layout.addWidget(self.arrow_btn)

    def set_items(self, items: Sequence[Any], default_item: Any = None):
        """设置下拉选项。items 为可迭代的选项序列（字符串）。"""
        self._items = [str(item) for item in items]
        if default_item is not None:
            self.setCurrentText(str(default_item))
        elif self._items:
            self.setCurrentText(self._items[0])

    def currentText(self) -> str:
        return self._current_text

    def setCurrentText(self, text: str):
        if text != self._current_text:
            self._current_text = text
            self.text_label.setText(text)
            self.currentIndexChanged.emit(text)

    def _show_dropdown(self):
        if not self._items:
            return

        debug(f"[ComboSelector._show_dropdown] items={self._items}")

        menu = CustomDropdownMenu(self, position="bottom", use_internal_button=False)
        menu.set_items(self._items, default_item=self._current_text)
        menu.set_target_button(self.arrow_btn)

        def on_item_clicked(selected_item):
            debug(f"[ComboSelector] 选中: {selected_item}")
            if isinstance(selected_item, dict):
                selected_text = str(selected_item.get("text", ""))
            else:
                selected_text = str(selected_item)
            self.setCurrentText(selected_text)

        menu.itemClicked.connect(on_item_clicked)
        menu.show_menu()

    def setTextColor(self, color: str):
        self.text_label.setStyleSheet(f"color: {color};")

    def set_value(self, text: str):
        """兼容设置项接口。"""
        self.setCurrentText(text)

    def get_value(self) -> str:
        """兼容设置项接口。"""
        return self.currentText()
