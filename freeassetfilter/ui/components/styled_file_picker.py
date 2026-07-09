"""Styled File Picker components — file/folder selection and drag-drop zone.

Provides:
  - StyledFilePicker: input field + browse button in HBoxLayout
  - StyledFileDropZone: dashed-border area with drag-drop visual feedback
"""

from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QFileDialog,
)
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import (
    QPainter,
    QColor,
    QPaintEvent,
    QFont,
    QPen,
    QBrush,
    QDragEnterEvent,
    QDropEvent,
    QDragLeaveEvent,
)

from .icon_utils import icon_path, render_icon
from theme import tm


# ---------------------------------------------------------------------------
# Internal shared size table
# ---------------------------------------------------------------------------
_SIZE_CONFIG = {
    "sm": {"padding_h": 10, "padding_v": 6, "font_size": 12, "radius": 6, "height": 30},
    "default": {"padding_h": 12, "padding_v": 8, "font_size": 13, "radius": 6, "height": 36},
    "lg": {"padding_h": 16, "padding_v": 12, "font_size": 15, "radius": 6, "height": 44},
}

_BUTTON_SIZE_CONFIG = {
    "sm": {"padding_h": 10, "font_size": 12, "icon_size": 14},
    "default": {"padding_h": 14, "font_size": 13, "icon_size": 14},
    "lg": {"padding_h": 18, "font_size": 14, "icon_size": 16},
}

# ───────────────────────────────────────────────────────────────────
# Internal browse button (styling matches StyledButton secondary)
# ───────────────────────────────────────────────────────────────────


class _BrowseButton(QPushButton):
    """Browse button with folder icon painted via icon_utils."""

    def __init__(self, size: str = "default", parent=None):
        super().__init__(parent)
        self._size = size if size in _SIZE_CONFIG else "default"
        self._hovered = False
        self._pressed = False

        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setFlat(True)
        self.setFocusPolicy(Qt.NoFocus)

    def set_size(self, size: str):
        if size in _SIZE_CONFIG:
            self._size = size
            self.update()

    # ── Event overrides ────────────────────────────────────────────

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed = False
            self.update()
        super().mouseReleaseEvent(event)

    # ── Paint ──────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing)

            config = _BUTTON_SIZE_CONFIG[self._size]
            w = self.width()
            h = self.height()

            if not self.isEnabled():
                painter.setOpacity(0.4)
                bg = tm.alpha_of(tm.mid, 20)
                text_color = tm.alpha_of(tm.mid, 40)
                border_color = tm.alpha_of(tm.mid, 40)
            elif self._pressed:
                bg = tm.surface
                text_color = tm.text
                border_color = tm.alpha_of(tm.mid, 40)
            elif self._hovered:
                bg = tm.alpha_of(tm.mid, 40)
                text_color = tm.text
                border_color = tm.alpha_of(tm.mid, 60)
            else:
                bg = tm.alpha_of(tm.mid, 40)
                text_color = tm.mid
                border_color = tm.mid

            r = _SIZE_CONFIG[self._size]["radius"]

            # Background
            painter.setPen(QPen(border_color, 1))
            painter.setBrush(bg)
            painter.drawRoundedRect(0, 0, w, h, r, r)

            # Icon + text
            icon_size = config["icon_size"]
            font_size = config["font_size"]
            padding = config["padding_h"]

            font = QFont("Microsoft YaHei UI", font_size)
            painter.setFont(font)
            text = "浏览..."
            text_w = painter.fontMetrics().horizontalAdvance(text)

            total_w = icon_size + 6 + text_w
            start_x = (w - total_w) / 2.0

            # Folder icon via icon_utils
            folder_path = icon_path("folder")
            if not folder_path.isEmpty():
                painter.save()
                scale = icon_size / 24.0
                icon_center_x = start_x + icon_size / 2.0
                icon_center_y = h / 2.0
                painter.translate(icon_center_x, icon_center_y)
                painter.scale(scale, scale)
                painter.translate(-12, -12)
                painter.setPen(QPen(text_color, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(folder_path)
                painter.restore()

            # Text
            text_x = start_x + icon_size + 6
            painter.setPen(text_color)
            painter.drawText(
                QRectF(text_x, 0, text_w, h),
                Qt.AlignVCenter | Qt.AlignLeft,
                text,
            )
        finally:
            painter.end()


# ───────────────────────────────────────────────────────────────────
# StyledFilePicker
# ───────────────────────────────────────────────────────────────────


class StyledFilePicker(QWidget):
    """A file/folder picker: read-only input + browse button.

    Modes:
      "file"   — QFileDialog.getOpenFileName()
      "folder" — QFileDialog.getExistingDirectory()

    Sizes: sm, default, lg
    States: normal, error (red border), disabled
    """

    path_chosen = Signal(str)

    def __init__(
        self,
        path: str = "",
        mode: str = "file",
        size: str = "default",
        error: bool = False,
        placeholder: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._mode = mode if mode in ("file", "folder") else "file"
        self._size = size if size in _SIZE_CONFIG else "default"
        self._error = error
        self._path = path

        self.setAttribute(Qt.WA_StyledBackground, False)

        self._setup_ui()
        self._resize_children()

        if placeholder:
            self._input.setPlaceholderText(placeholder)
        elif mode == "folder":
            self._input.setPlaceholderText("选择文件夹...")
        else:
            self._input.setPlaceholderText("选择文件...")

    # ── UI construction ────────────────────────────────────────────

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._input = QLineEdit(self)
        self._input.setReadOnly(True)
        self._input.setText(self._path)

        self._browse_btn = _BrowseButton(size=self._size, parent=self)
        self._browse_btn.clicked.connect(self._on_browse)

        layout.addWidget(self._input)
        layout.addWidget(self._browse_btn)
        self.setLayout(layout)

    def _resize_children(self):
        config = _SIZE_CONFIG[self._size]
        h = config["height"]
        self._input.setFixedHeight(h)
        self._browse_btn.setFixedHeight(h)
        self._input.setFixedWidth(180)
        self._apply_stylesheet()

    def _apply_stylesheet(self):
        config = _SIZE_CONFIG[self._size]
        border_color = tm.danger.name() if self._error else tm.mid.name()

        self._input.setObjectName(f"fp_input_{id(self)}")
        self._input.setStyleSheet(f"""
            #fp_input_{id(self)} {{
                background-color: {tm.fill.name()};
                color: {tm.text.name()};
                border: 1px solid {border_color};
                border-radius: {config["radius"]}px;
                font-size: {config["font_size"]}px;
                font-family: "Microsoft YaHei UI";
                padding: 0 {config["padding_h"]}px;
                selection-background-color: {tm.accent.name()};
                selection-color: #ffffff;
            }}
            #fp_input_{id(self)}:hover {{
                background-color: {tm.fill.lighter(115).name()};
            }}
            #fp_input_{id(self)}:disabled {{
                background-color: {tm.surface.name()};
                color: {tm.alpha_of(tm.mid, 40).name()};
                border-color: {tm.alpha_of(tm.mid, 40).name()};
            }}
        """)

    # ── Browse action ──────────────────────────────────────────────

    def _on_browse(self):
        if self._mode == "folder":
            path = QFileDialog.getExistingDirectory(self, "选择文件夹", self._path)
        else:
            path, _ = QFileDialog.getOpenFileName(self, "选择文件", self._path)

        if path:
            self._path = path
            self._input.setText(path)
            self.path_chosen.emit(path)

    # ── Properties ─────────────────────────────────────────────────

    @property
    def path(self) -> str:
        return self._path

    @path.setter
    def path(self, value: str):
        self._path = value
        self._input.setText(value)

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str):
        if value in ("file", "folder"):
            self._mode = value

    @property
    def size_variant(self) -> str:
        return self._size

    @size_variant.setter
    def size_variant(self, value: str):
        if value not in _SIZE_CONFIG:
            return
        self._size = value
        self._browse_btn.set_size(value)
        self._resize_children()

    @property
    def error(self) -> bool:
        return self._error

    @error.setter
    def error(self, value: bool):
        self._error = value
        self._apply_stylesheet()

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        self._input.setEnabled(enabled)
        self._browse_btn.setEnabled(enabled)


# ───────────────────────────────────────────────────────────────────
# StyledFileDropZone
# ───────────────────────────────────────────────────────────────────


class StyledFileDropZone(QWidget):
    """Drag-and-drop zone with dashed border and visual feedback.

    Idle:  dashed 2px #3a3a3a border
    Drag:  solid 2px #07c160 border + subtle green tint
    Click: opens QFileDialog.getOpenFileName()
    """

    path_chosen = Signal(str)

    def __init__(
        self,
        text: str = "拖拽文件到此处",
        hint: str = "或点击选择文件",
        parent=None,
    ):
        super().__init__(parent)
        self._text = text
        self._hint = hint
        self._drag_over = False

        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(100)
        self.setAttribute(Qt.WA_StyledBackground, False)

    # ── Properties ─────────────────────────────────────────────────

    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value: str):
        self._text = value
        self.update()

    @property
    def hint(self) -> str:
        return self._hint

    @hint.setter
    def hint(self, value: str):
        self._hint = value
        self.update()

    # ── Drag-drop events ───────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            self._drag_over = True
            self.update()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        self._drag_over = False
        self.update()

    def dropEvent(self, event: QDropEvent):
        self._drag_over = False
        urls = event.mimeData().urls()
        if urls:
            local_path = urls[0].toLocalFile()
            if local_path:
                self.path_chosen.emit(local_path)
        self.update()

    def mouseReleaseEvent(self, event):
        path, _ = QFileDialog.getOpenFileName(self, "选择文件")
        if path:
            self.path_chosen.emit(path)
        super().mouseReleaseEvent(event)

    # ── Paint ──────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.TextAntialiasing)

            w = self.width()
            h = self.height()

            if self._drag_over:
                bg = tm.alpha_of(tm.accent, 5)
                border_color = tm.accent
                border_style = Qt.SolidLine
            else:
                bg = tm.alpha_of(tm.surface, 90)
                border_color = tm.mid
                border_style = Qt.DashLine

            # Background + border
            painter.setPen(QPen(border_color, 2, border_style))
            painter.setBrush(bg)
            painter.drawRoundedRect(1, 1, w - 2, h - 2, 8, 8)

            # Upload icon (centered above text)
            icon_size = 32
            icon_rect = QRectF(
                (w - icon_size) / 2.0,
                h / 2.0 - icon_size - 16,
                icon_size,
                icon_size,
            )
            icon_color = tm.accent if self._drag_over else tm.mid
            render_icon(painter, "upload", icon_rect, icon_color, pen_width=1.8)

            # Main text
            font = QFont("Microsoft YaHei UI", 13)
            painter.setFont(font)
            text_color = tm.accent if self._drag_over else tm.mid
            painter.setPen(text_color)
            painter.drawText(
                QRectF(0, h / 2.0 - 4, w, 20),
                Qt.AlignCenter,
                self._text,
            )

            # Hint text
            hint_font = QFont("Microsoft YaHei UI", 12)
            painter.setFont(hint_font)
            painter.setPen(tm.alpha_of(tm.mid, 60))
            painter.drawText(
                QRectF(0, h / 2.0 + 18, w, 18),
                Qt.AlignCenter,
                self._hint,
            )
        finally:
            painter.end()
