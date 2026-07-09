"""Styled LineEdit component - matches web input exactly."""

from PySide6.QtWidgets import QLineEdit, QWidget, QHBoxLayout
from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QPainter, QColor, QPaintEvent, QFont
from theme import tm


class StyledLineEdit(QLineEdit):
    """A styled line edit matching the web component exactly.
    
    Sizes: sm, default, lg
    States: default, error, disabled
    """

    SIZE_CONFIG = {
        "sm": {"padding_h": 10, "padding_v": 6, "font_size": 12, "radius": 6, "height": 30},
        "default": {"padding_h": 12, "padding_v": 8, "font_size": 13, "radius": 6, "height": 36},
        "lg": {"padding_h": 16, "padding_v": 12, "font_size": 15, "radius": 6, "height": 44},
    }

    def __init__(
        self,
        text: str = "",
        size: str = "default",
        error: bool = False,
        parent=None,
    ):
        super().__init__(text, parent)
        self._size = size if size in self.SIZE_CONFIG else "default"
        self._error = error
        self._focused = False
        self._hovered = False

        self.setAttribute(Qt.WA_Hover, True)
        self._apply_size()
        self._apply_stylesheet()
        # 主题切换时刷新配色
        tm.theme_changed.connect(self._on_theme_changed)

    def _apply_size(self):
        config = self.SIZE_CONFIG[self._size]
        # Set unique objectName to scope styles to this widget only (prevent inheritance)
        self.setObjectName(f"StyledLineEdit_{id(self)}")
        self.setStyleSheet("")  # Clear any existing
        font = QFont("Microsoft YaHei UI", config["font_size"])
        self.setFont(font)
        # Set fixed height to match Web CSS exactly
        self.setFixedHeight(config["height"])
        # Use setTextMargins for proper text positioning (matches CSS padding)
        self.setTextMargins(
            config["padding_h"],
            config["padding_v"],
            config["padding_h"],
            config["padding_v"],
        )

    def _apply_stylesheet(self):
        config = self.SIZE_CONFIG[self._size]
        obj_name = self.objectName()
        surf = tm.surface
        bg_fill = f"rgba({surf.red()},{surf.green()},{surf.blue()},{30 / 100})"

        if self._error:
            border_color = tm.danger.name()
            focus_border = tm.danger.name()
        else:
            mid = tm.mid
            border_color = f"rgba({mid.red()},{mid.green()},{mid.blue()},{25 / 100})"
            focus_border = tm.accent.name()

        # Disabled state colors (with alpha via rgba)
        mid_d = tm.mid
        disabled_color = f"rgba({mid_d.red()},{mid_d.green()},{mid_d.blue()},{40 / 100})"
        disabled_border = f"rgba({mid_d.red()},{mid_d.green()},{mid_d.blue()},{20 / 100})"

        self.setStyleSheet(f"""
            #{obj_name} {{
                background-color: {bg_fill};
                color: {tm.text.name()};
                border: 1px solid {border_color};
                border-radius: {config["radius"]}px;
                font-size: {config["font_size"]}px;
                selection-background-color: {tm.accent.name()};
                selection-color: {tm.text.name()};
            }}
            #{obj_name}:hover {{
                background-color: {bg_fill};
            }}
            #{obj_name}:focus {{
                border-color: {focus_border};
                background-color: {bg_fill};
            }}
            #{obj_name}:disabled {{
                background-color: {bg_fill};
                color: {disabled_color};
                border-color: {disabled_border};
            }}
        """)

    def _on_theme_changed(self, theme: str) -> None:
        """主题切换时重新应用样式"""
        self._apply_stylesheet()

    @property
    def size_variant(self) -> str:
        return self._size

    @size_variant.setter
    def size_variant(self, value: str):
        if value not in self.SIZE_CONFIG:
            return
        self._size = value
        self._apply_size()
        self._apply_stylesheet()

    @property
    def error(self) -> bool:
        return self._error

    @error.setter
    def error(self, value: bool):
        self._error = value
        self._apply_stylesheet()

    def focusInEvent(self, event):
        self._focused = True
        self._apply_stylesheet()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._focused = False
        self._apply_stylesheet()
        super().focusOutEvent(event)

    def enterEvent(self, event):
        self._hovered = True
        self._apply_stylesheet()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._apply_stylesheet()
        super().leaveEvent(event)


class InputWrapper(QWidget):
    """A wrapper that adds an icon to the left of a StyledLineEdit."""

    def __init__(
        self,
        placeholder: str = "",
        icon_svg_path: str = "",
        size: str = "default",
        parent=None,
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._input = StyledLineEdit(size=size)
        self._input.setPlaceholderText(placeholder)
        layout.addWidget(self._input)

        self.setLayout(layout)

    @property
    def line_edit(self) -> StyledLineEdit:
        return self._input
