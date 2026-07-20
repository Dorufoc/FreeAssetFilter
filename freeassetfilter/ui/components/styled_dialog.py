"""Styled Dialog component - matches web dialog exactly.

Provides:
  - StyledDialog: standalone frameless top-level dialog window
  - DialogIconCircle: icon circle for success/danger variants
  - Factory functions for all dialog variants
"""

from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QGraphicsDropShadowEffect,
    QSizePolicy, QApplication, QGraphicsEffect,
)
from PySide6.QtCore import (
    Qt, Signal, QPropertyAnimation, QEasingCurve, Property, QRectF, QPoint, QTimer,
)
from PySide6.QtGui import QPainter, QColor, QPaintEvent, QFont, QCursor, QMouseEvent

from theme import tm

from components.styled_button import StyledButton
from components.styled_progress import StyledProgress
from components.styled_progress_circle import StyledProgressCircle


# ── Constants ──────────────────────────────────────────────────────

FOOTER_RIGHT = "right"
FOOTER_CENTER = "center"
FOOTER_LEFT = "left"
FOOTER_STACKED = "stacked"
FOOTER_THREE = "three"
FOOTER_WITH_HELP = "with_help"
FOOTER_NO_BORDER = "no_border"
FOOTER_NONE = "none"  # No footer at all

# Web CSS 尺寸值
SIZE_CONFIG = {
    "sm": {"width": 320},
    "default": {"width": 400},
    "lg": {"width": 560},
}


class DialogAnimationEffect(QGraphicsEffect):
    """Combined opacity + scale effect applied to the whole dialog.

    Renders the source widget (and all child widgets) into a pixmap,
    then draws it with optional opacity and uniform scale around the
    actual dialog center (the source widget's own rect center).
    """

    def __init__(self, dialog: QWidget):
        super().__init__(dialog)
        self._dialog = dialog
        self._opacity = 1.0
        self._scale = 1.0

    @Property(float)
    def opacity(self) -> float:
        return self._opacity

    @opacity.setter
    def opacity(self, value: float) -> None:
        self._opacity = max(0.0, min(1.0, value))
        self.update()

    @Property(float)
    def scale(self) -> float:
        return self._scale

    @scale.setter
    def scale(self, value: float) -> None:
        self._scale = max(0.0, value)
        self.update()

    def draw(self, painter: QPainter) -> None:
        pixmap = self.sourcePixmap(Qt.LogicalCoordinates)
        if pixmap.isNull():
            self.drawSource(painter)
            return

        painter.save()
        painter.setOpacity(self._opacity)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Anchor at the source widget's own center, ignoring shadow expansion.
        center = QRectF(self._dialog.rect()).center()
        painter.translate(center)
        painter.scale(self._scale, self._scale)
        painter.translate(-center)
        painter.drawPixmap(QPoint(0, 0), pixmap)
        painter.restore()


# ── StyledDialog ───────────────────────────────────────────────────

class StyledDialog(QWidget):
    """Standalone frameless top-level dialog window.

    Sizes: sm (320px), default (400px), lg (560px)
    Types: default, success, danger, info
    Footer layouts: right, center, left, stacked, three, with_help, no_border
    """

    # Shadow margin to prevent clipping
    SHADOW_MARGIN = 20

    finished = Signal(int)

    @staticmethod
    def _get_type_colors() -> dict[str, dict[str, str]]:
        return {
            "default": {
                "title": tm.text.name(),
                "icon_bg": tm.surface.name(),
                "icon_color": tm.mid.name(),
            },
            "success": {
                "title": tm.accent.name(),
                "icon_bg": "rgba(7,193,96,0.15)",
                "icon_color": tm.accent.name(),
            },
            "danger": {
                "title": tm.danger.name(),
                "icon_bg": "rgba(239,68,68,0.15)",
                "icon_color": tm.danger.name(),
            },
            "info": {
                "title": tm.info.name(),
                "icon_bg": "rgba(59,130,246,0.15)",
                "icon_color": tm.info.name(),
            },
        }

    def __init__(
        self,
        size: str = "default",
        dialog_type: str = "default",
        title: str = "",
        body_widget: QWidget = None,
        footer_type: str = FOOTER_RIGHT,
        show_close: bool = True,
        animate: bool = True,
        parent=None,
    ):
        # No parent -> top-level window
        super().__init__(None)
        self._size = size if size in SIZE_CONFIG else "default"
        self._dialog_type = dialog_type if dialog_type in self._get_type_colors() else "default"
        self._footer_type = footer_type
        self._result = 0
        self._animate = animate
        self._is_closing = False
        self._shown_once = False

        # Drag support
        self._drag_pos: QPoint = None

        # Frameless top-level window
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # Animation
        self._anim_effect: DialogAnimationEffect = None
        self._enter_opacity_anim: QPropertyAnimation = None
        self._enter_scale_anim: QPropertyAnimation = None
        self._exit_opacity_anim: QPropertyAnimation = None
        self._exit_scale_anim: QPropertyAnimation = None
        if self._animate:
            self._setup_animations()

        self.setObjectName("StyledDialog")
        # Window is larger than content to accommodate shadow
        content_width = SIZE_CONFIG[self._size]["width"]
        self.setFixedWidth(content_width + self.SHADOW_MARGIN * 2)

        # Create content container with shadow
        self._content_widget = QWidget(self)
        self._content_widget.setObjectName("DialogContent")
        self._content_widget.setStyleSheet(f"""
            #DialogContent {{
                background-color: {tm.surface.name()};
                border: 1px solid {tm.alpha_of(tm.surface, 90).name()};
                border-radius: 12px;
            }}
        """)

        # Web CSS: box-shadow: var(--shadow-lg)
        shadow = QGraphicsDropShadowEffect(self._content_widget)
        shadow.setBlurRadius(60)
        shadow.setColor(tm.alpha_of(tm.black, 50))
        shadow.setOffset(0, 10)
        self._content_widget.setGraphicsEffect(shadow)

        # Layout for content container
        content_layout = QVBoxLayout(self._content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        if title or show_close:
            self._build_header(title, show_close, content_layout)

        if body_widget:
            self._build_body(body_widget, content_layout)

        if footer_type != FOOTER_NONE:
            self._build_footer(footer_type, content_layout)

        # Position content widget with shadow margin
        self._content_widget.setGeometry(
            self.SHADOW_MARGIN, self.SHADOW_MARGIN,
            content_width, 100  # height will be adjusted
        )

    # ── Header ─────────────────────────────────────────────────────

    def _build_header(self, title: str, show_close: bool, parent_layout):
        # Web CSS: padding: 20px 24px 0
        header_frame = QWidget()
        header_frame.setObjectName("DialogHeader")
        header_frame.setStyleSheet("background: transparent; border: none;")
        header_frame.setContentsMargins(24, 20, 12, 0)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)

        colors = self._get_type_colors()[self._dialog_type]

        # Web CSS: .dialog-header-with-icon { display: flex; flex-direction: column; }
        if self._dialog_type in ("success", "danger", "info"):
            # 带图标的 header: icon 在上，title 在下
            icon_title_widget = QWidget()
            icon_title_widget.setStyleSheet("background: transparent;")
            icon_title_layout = QVBoxLayout(icon_title_widget)
            icon_title_layout.setContentsMargins(0, 0, 0, 0)
            icon_title_layout.setSpacing(0)

            # Web CSS: .dialog-icon { width: 40px; height: 40px; border-radius: var(--radius-md); margin-bottom: 12px; }
            icon_circle = DialogIconCircle(
                icon_type=self._dialog_type,
                bg_color=colors["icon_bg"],
                icon_color=colors["icon_color"],
            )
            icon_title_layout.addWidget(icon_circle)

            # Web CSS: .dialog-title { font-size: 16px; font-weight: 600; }
            title_label = self._make_label(title, 16, QFont.Weight.DemiBold, colors["title"])
            title_label.setContentsMargins(0, 12, 0, 0)
            icon_title_layout.addWidget(title_label)

            header_layout.addWidget(icon_title_widget)
        else:
            # 普通 header: title 在左，close 在右
            title_label = self._make_label(title, 16, QFont.Weight.DemiBold, colors["title"])
            header_layout.addWidget(title_label, stretch=1)

        if show_close:
            header_layout.addSpacing(12)
            close_btn = self._make_close_button()
            header_layout.addWidget(close_btn, alignment=Qt.AlignTop)

        parent_layout.addWidget(header_frame)

    # ── Body ───────────────────────────────────────────────────────

    def _build_body(self, content: QWidget, parent_layout):
        # Web CSS: padding: 16px 24px
        body_frame = QWidget()
        body_frame.setStyleSheet("background: transparent; border: none;")
        body_frame.setContentsMargins(24, 16, 24, 16)
        body_layout = QVBoxLayout(body_frame)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(content)
        parent_layout.addWidget(body_frame)

    # ── Footer ─────────────────────────────────────────────────────

    def _build_footer(self, footer_type: str, parent_layout):
        # Web CSS: padding: 16px 24px, gap: 10px, border-top: 1px solid var(--divider-color)
        footer_frame = QWidget()
        footer_frame.setObjectName("footer_frame")
        has_border = footer_type != FOOTER_NO_BORDER
        border_css = f"border-top: 1px solid {tm.alpha_of(tm.surface, 90).name()};" if has_border else ""
        # Use object name selector to prevent style inheritance to child widgets
        footer_frame.setStyleSheet(f"#footer_frame {{ background: transparent; {border_css} }}")

        if footer_type == FOOTER_RIGHT:
            # Web CSS: justify-content: flex-end
            footer_frame.setContentsMargins(24, 16, 24, 16)
            layout = QHBoxLayout(footer_frame)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)
            layout.addStretch()
            self._footer_layout = layout

        elif footer_type == FOOTER_CENTER:
            # Web CSS: justify-content: center
            footer_frame.setContentsMargins(24, 16, 24, 16)
            layout = QHBoxLayout(footer_frame)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)
            self._footer_layout = layout

        elif footer_type == FOOTER_LEFT:
            # Web CSS: justify-content: flex-start
            footer_frame.setContentsMargins(24, 16, 24, 16)
            layout = QHBoxLayout(footer_frame)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)
            self._footer_layout = layout

        elif footer_type == FOOTER_STACKED:
            # Web CSS: flex-direction: column, gap: 8px
            # Web CSS: .dialog-footer-stacked .btn { width: 100%; justify-content: center; }
            footer_frame.setContentsMargins(24, 16, 24, 16)
            layout = QVBoxLayout(footer_frame)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)
            self._footer_layout = layout

        elif footer_type == FOOTER_THREE:
            # Web CSS: justify-content: space-between
            footer_frame.setContentsMargins(24, 16, 24, 16)
            layout = QHBoxLayout(footer_frame)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)
            self._left_footer_widget = QWidget()
            self._left_footer_widget.setStyleSheet("background: transparent;")
            self._left_footer_layout = QHBoxLayout(self._left_footer_widget)
            self._left_footer_layout.setContentsMargins(0, 0, 0, 0)
            self._left_footer_layout.setSpacing(10)
            layout.addWidget(self._left_footer_widget)
            layout.addStretch()
            self._right_footer_widget = QWidget()
            self._right_footer_widget.setStyleSheet("background: transparent;")
            self._right_footer_layout = QHBoxLayout(self._right_footer_widget)
            self._right_footer_layout.setContentsMargins(0, 0, 0, 0)
            self._right_footer_layout.setSpacing(10)
            layout.addWidget(self._right_footer_widget)
            self._footer_layout = layout

        elif footer_type == FOOTER_WITH_HELP:
            # Web CSS: justify-content: space-between
            footer_frame.setContentsMargins(24, 16, 24, 16)
            layout = QHBoxLayout(footer_frame)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)
            # Web CSS: .help-link { font-size: 12px; color: var(--accent-primary); }
            self._help_link = QPushButton("查看完整协议 →")
            self._help_link.setCursor(QCursor(Qt.PointingHandCursor))
            self._help_link.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; border: none; color: {tm.accent.name()};
                    font-size: 12px; text-align: left; padding: 0;
                }}
                QPushButton:hover {{ text-decoration: underline; }}
            """)
            layout.addWidget(self._help_link)
            layout.addStretch()
            self._right_footer_widget = QWidget()
            self._right_footer_widget.setStyleSheet("background: transparent;")
            self._right_footer_layout = QHBoxLayout(self._right_footer_widget)
            self._right_footer_layout.setContentsMargins(0, 0, 0, 0)
            self._right_footer_layout.setSpacing(10)
            layout.addWidget(self._right_footer_widget)
            self._footer_layout = layout

        elif footer_type == FOOTER_NO_BORDER:
            # Web CSS: border-top: none
            footer_frame.setContentsMargins(24, 16, 24, 16)
            layout = QHBoxLayout(footer_frame)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)
            layout.addStretch()
            self._footer_layout = layout

        parent_layout.addWidget(footer_frame)

    # ── Helpers ───────────────────────────────────────────────────

    def _make_close_button(self) -> QPushButton:
        # Web CSS: width: 32px; height: 32px; border-radius: var(--radius-sm)
        btn = QPushButton()
        btn.setFixedSize(32, 32)
        btn.setCursor(QCursor(Qt.PointingHandCursor))
        btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 6px;"
            f" color: {tm.mid.name()}; font-size: 18px; font-weight: 300; }}"
            f"QPushButton:hover {{ background-color: {tm.surface.name()}; color: {tm.text.name()}; }}"
        )
        btn.setText("✕")
        btn.clicked.connect(lambda: self.close_dialog(0))
        return btn

    @staticmethod
    def _make_label(text: str, font_size: int, weight, color: str) -> QLabel:
        label = QLabel(text)
        font = QFont("Microsoft YaHei UI", font_size)
        font.setWeight(weight)
        label.setFont(font)
        label.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        return label

    # ── Public API ─────────────────────────────────────────────────

    def close_dialog(self, result: int = 0):
        """Close the dialog with a result code."""
        self._result = result
        self.close()

    def _on_finished(self, result: int):
        self.finished.emit(result)

    # ── Animation ──────────────────────────────────────────────────

    def _setup_animations(self) -> None:
        self._anim_effect = DialogAnimationEffect(self)
        self._anim_effect.opacity = 1.0
        self._anim_effect.scale = 1.0
        self.setGraphicsEffect(self._anim_effect)

        self._enter_opacity_anim = QPropertyAnimation(self._anim_effect, b"opacity", self)
        self._enter_opacity_anim.setDuration(280)
        self._enter_opacity_anim.setStartValue(0.0)
        self._enter_opacity_anim.setEndValue(1.0)
        self._enter_opacity_anim.setEasingCurve(QEasingCurve.InOutCubic)

        self._enter_scale_anim = QPropertyAnimation(self._anim_effect, b"scale", self)
        self._enter_scale_anim.setDuration(280)
        self._enter_scale_anim.setStartValue(0.85)
        self._enter_scale_anim.setEndValue(1.0)
        self._enter_scale_anim.setEasingCurve(QEasingCurve.InOutCubic)

        self._exit_opacity_anim = QPropertyAnimation(self._anim_effect, b"opacity", self)
        self._exit_opacity_anim.setDuration(200)
        self._exit_opacity_anim.setStartValue(1.0)
        self._exit_opacity_anim.setEndValue(0.0)
        self._exit_opacity_anim.setEasingCurve(QEasingCurve.InOutCubic)

        self._exit_scale_anim = QPropertyAnimation(self._anim_effect, b"scale", self)
        self._exit_scale_anim.setDuration(200)
        self._exit_scale_anim.setStartValue(1.0)
        self._exit_scale_anim.setEndValue(0.95)
        self._exit_scale_anim.setEasingCurve(QEasingCurve.InOutCubic)

        self._exit_opacity_anim.finished.connect(self._finish_close)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._animate and self._anim_effect is not None and not self._shown_once:
            self._shown_once = True
            self._anim_effect.opacity = 0.0
            self._anim_effect.scale = 0.85
            self._enter_opacity_anim.start()
            self._enter_scale_anim.start()

    def closeEvent(self, event) -> None:
        if self._animate and not self._is_closing and self._anim_effect is not None:
            self._is_closing = True
            event.ignore()
            self._exit_opacity_anim.start()
            self._exit_scale_anim.start()
            return
        self._is_closing = False
        self._on_finished(self._result)
        super().closeEvent(event)

    def _finish_close(self) -> None:
        self.close()

    # ── Drag support ───────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        """Start dragging when clicking on the header area."""
        if event.button() == Qt.LeftButton:
            # Only drag from header area (top ~60px)
            if event.position().y() < 60:
                self._drag_pos = event.position().toPoint()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        """Drag the window."""
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            new_pos = self.pos() + event.position().toPoint() - self._drag_pos
            self.move(new_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        """Resize content widget to fit within shadow margins."""
        super().resizeEvent(event)
        if self._content_widget:
            content_width = self.width() - self.SHADOW_MARGIN * 2
            content_height = self.height() - self.SHADOW_MARGIN * 2
            self._content_widget.setGeometry(
                self.SHADOW_MARGIN, self.SHADOW_MARGIN,
                content_width, content_height
            )


# ── DialogIconCircle ───────────────────────────────────────────────

class DialogIconCircle(QWidget):
    """Circular icon badge for success / danger / info dialog headers."""

    def __init__(self, icon_type: str = "success",
                 bg_color: str = None, icon_color: str = None, parent=None):
        if bg_color is None:
            bg_color = tm.surface.name()
        if icon_color is None:
            icon_color = tm.mid.name()
        super().__init__(parent)
        self._icon_type = icon_type
        self._bg_color = QColor(bg_color) if not bg_color.startswith("rgba") else self._parse_rgba(bg_color)
        self._icon_color = QColor(icon_color)
        self.setFixedSize(40, 40)

    @staticmethod
    def _parse_rgba(rgba: str) -> QColor:
        parts = rgba.replace("rgba(", "").replace(")", "").split(",")
        return QColor(int(parts[0]), int(parts[1]), int(parts[2]), int(float(parts[3]) * 255))

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._bg_color)
            # Web CSS: border-radius: var(--radius-md) = 8px
            painter.drawRoundedRect(QRectF(0, 0, 40, 40), 8, 8)

            painter.setPen(self._icon_color)
            font = QFont("Segoe UI Symbol", 14)
            font.setWeight(QFont.Weight.Bold)
            painter.setFont(font)
            rect = QRectF(0, 0, 40, 40)
            if self._icon_type == "success":
                painter.drawText(rect, Qt.AlignCenter, "✓")
            elif self._icon_type == "danger":
                painter.drawText(rect, Qt.AlignCenter, "⚠")
            elif self._icon_type == "info":
                painter.drawText(rect, Qt.AlignCenter, "↓")
        finally:
            painter.end()


# ══════════════════════════════════════════════════════════════════
#  Factory Functions
# ══════════════════════════════════════════════════════════════════

def _make_body_label(text: str) -> QWidget:
    # Web CSS: font-size: 13.5px; color: var(--text-secondary); line-height: 1.6
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(
        f"font-size: 13.5px; color: {tm.mid.name()}; background: transparent;"
    )
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(lbl)
    return w


def _show_dialog(dialog: StyledDialog):
    """Position dialog at screen center (where mouse is) and show it."""
    content_width = SIZE_CONFIG[dialog._size]["width"]
    
    # Set content widget fixed width so layout can compute height properly
    dialog._content_widget.setFixedWidth(content_width)
    
    # Force layout calculation before showing
    dialog._content_widget.ensurePolished()
    dialog._content_widget.layout().activate()
    
    # Calculate content height by summing all layout items
    layout = dialog._content_widget.layout()
    content_height = 0
    margins = layout.contentsMargins()
    content_height += margins.top() + margins.bottom()
    
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.widget():
            content_height += item.widget().sizeHint().height()
        elif item.layout():
            content_height += item.layout().totalSizeHint().height()
        content_height += layout.spacing()
    
    # Remove last spacing
    if layout.count() > 0:
        content_height -= layout.spacing()
    
    if content_height < 80:
        content_height = 80
    
    # Set final size BEFORE showing to avoid flicker
    window_width = content_width + dialog.SHADOW_MARGIN * 2
    window_height = content_height + dialog.SHADOW_MARGIN * 2
    dialog.setFixedSize(window_width, window_height)
    
    # Move to screen center
    cursor_pos = QCursor.pos()
    screen = QApplication.screenAt(cursor_pos)
    if not screen:
        screen = QApplication.primaryScreen()
    screen_geom = screen.geometry()
    cx = screen_geom.x() + (screen_geom.width() - window_width) // 2
    cy = screen_geom.y() + (screen_geom.height() - window_height) // 2
    dialog.move(max(screen_geom.x(), cx), max(screen_geom.y(), cy))
    
    # Show at correct size and position
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()


def create_basic_dialog(
    title: str = "确认删除",
    message: str = "确定要删除这个项目吗？此操作无法撤销。",
    cancel_text: str = "取消",
    confirm_text: str = "确认",
    animate: bool = True,
) -> StyledDialog:
    """Basic confirmation dialog."""
    body = _make_body_label(message)
    dialog = StyledDialog(animate=animate, title=title, body_widget=body)
    if cancel_text:
        cancel_btn = StyledButton(cancel_text, variant="ghost")
        cancel_btn.clicked.connect(lambda: dialog.close_dialog(0))
        dialog._footer_layout.addWidget(cancel_btn)
    confirm_btn = StyledButton(confirm_text, variant="primary")
    confirm_btn.clicked.connect(lambda: dialog.close_dialog(1))
    dialog._footer_layout.addWidget(confirm_btn)
    _show_dialog(dialog)
    return dialog


def create_success_dialog(
    title: str = "保存成功",
    message: str = "您的设置已成功保存。所有更改已生效。",
    confirm_text: str = "好的",
    animate: bool = True,
) -> StyledDialog:
    """Success dialog with green checkmark icon."""
    body = _make_body_label(message)
    dialog = StyledDialog(animate=animate, dialog_type="success", title=title, body_widget=body)
    confirm_btn = StyledButton(confirm_text, variant="primary")
    confirm_btn.clicked.connect(lambda: dialog.close_dialog(1))
    dialog._footer_layout.addWidget(confirm_btn)
    _show_dialog(dialog)
    return dialog


def create_danger_dialog(
    title: str = "确认永久删除",
    message: str = "此操作将永久删除该项目及其所有关联数据，无法恢复。请确认是否继续？",
    cancel_text: str = "取消",
    confirm_text: str = "确认删除",
    animate: bool = True,
) -> StyledDialog:
    """Danger dialog with warning icon and red confirm button."""
    body = _make_body_label(message)
    dialog = StyledDialog(animate=animate, dialog_type="danger", title=title, body_widget=body)
    if cancel_text:
        cancel_btn = StyledButton(cancel_text, variant="ghost")
        cancel_btn.clicked.connect(lambda: dialog.close_dialog(0))
        dialog._footer_layout.addWidget(cancel_btn)
    # Web CSS: .dialog-danger .dialog-footer .btn-primary { background: #ef4444; }
    confirm_btn = StyledButton(confirm_text, variant="danger")
    confirm_btn.clicked.connect(lambda: dialog.close_dialog(1))
    dialog._footer_layout.addWidget(confirm_btn)
    _show_dialog(dialog)
    return dialog


def create_info_dialog(
    title: str = "提示信息",
    message: str = "这是一条重要的提示信息，请仔细阅读。",
    confirm_text: str = "知道了",
    animate: bool = True,
) -> StyledDialog:
    """Info dialog with blue info icon."""
    body = _make_body_label(message)
    dialog = StyledDialog(animate=animate, dialog_type="info", title=title, body_widget=body)
    confirm_btn = StyledButton(confirm_text, variant="info")
    confirm_btn.clicked.connect(lambda: dialog.close_dialog(1))
    dialog._footer_layout.addWidget(confirm_btn)
    _show_dialog(dialog)
    return dialog


def create_input_dialog(
    title: str = "重命名",
    message: str = "请输入新的名称：",
    placeholder: str = "输入新名称...",
    cancel_text: str = "取消",
    confirm_text: str = "确认",
    animate: bool = True,
) -> StyledDialog:
    """Input dialog with a text field."""
    body = QWidget()
    body.setStyleSheet("background: transparent;")
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(0, 0, 0, 0)
    body_layout.setSpacing(0)

    msg_label = QLabel(message)
    msg_label.setStyleSheet(
        f"font-size: 13.5px; color: {tm.mid.name()}; background: transparent;"
    )
    body_layout.addWidget(msg_label)

    # Web CSS: .dialog-input { margin-top: 12px; width: 100%; }
    input_field = QLineEdit()
    input_field.setPlaceholderText(placeholder)
    input_field.setStyleSheet(f"""
        QLineEdit {{
            background-color: {tm.surface.name()}; border: 1px solid {tm.mid.name()}; border-radius: 6px;
            padding: 8px 12px; font-size: 13px; color: {tm.text.name()}; margin-top: 12px;
        }}
        QLineEdit:focus {{ border-color: {tm.accent.name()}; }}
    """)
    body_layout.addWidget(input_field)

    dialog = StyledDialog(animate=animate, title=title, body_widget=body)
    dialog._input_field = input_field

    if cancel_text:
        cancel_btn = StyledButton(cancel_text, variant="ghost")
        cancel_btn.clicked.connect(lambda: dialog.close_dialog(0))
        dialog._footer_layout.addWidget(cancel_btn)
    confirm_btn = StyledButton(confirm_text, variant="primary")
    confirm_btn.clicked.connect(lambda: dialog.close_dialog(1))
    dialog._footer_layout.addWidget(confirm_btn)
    _show_dialog(dialog)
    return dialog


def create_small_dialog(
    title: str = "提示",
    message: str = "这是一个小尺寸的对话框。",
    cancel_text: str = "取消",
    confirm_text: str = "确认",
    animate: bool = True,
) -> StyledDialog:
    """Small (320 px) dialog."""
    body = _make_body_label(message)
    dialog = StyledDialog(animate=animate, size="sm", title=title, body_widget=body)
    if cancel_text:
        cancel_btn = StyledButton(cancel_text, variant="ghost")
        cancel_btn.clicked.connect(lambda: dialog.close_dialog(0))
        dialog._footer_layout.addWidget(cancel_btn)
    confirm_btn = StyledButton(confirm_text, variant="primary")
    confirm_btn.clicked.connect(lambda: dialog.close_dialog(1))
    dialog._footer_layout.addWidget(confirm_btn)
    _show_dialog(dialog)
    return dialog


def create_large_dialog(
    title: str = "关于此功能",
    message: str = (
        "这是一个大尺寸的对话框，适用于需要展示较多内容的场景。例如详细说明、条款确认、或者复杂的表单输入。\n\n"
        "大对话框提供了更宽敞的阅读空间，确保用户能够完整理解需要确认的内容。"
    ),
    cancel_text: str = "关闭",
    confirm_text: str = "我知道了",
    animate: bool = True,
) -> StyledDialog:
    """Large (560 px) dialog."""
    body = _make_body_label(message)
    dialog = StyledDialog(animate=animate, size="lg", title=title, body_widget=body)
    if cancel_text:
        cancel_btn = StyledButton(cancel_text, variant="ghost")
        cancel_btn.clicked.connect(lambda: dialog.close_dialog(0))
        dialog._footer_layout.addWidget(cancel_btn)
    confirm_btn = StyledButton(confirm_text, variant="primary")
    confirm_btn.clicked.connect(lambda: dialog.close_dialog(1))
    dialog._footer_layout.addWidget(confirm_btn)
    _show_dialog(dialog)
    return dialog


# ── Progress dialogs ───────────────────────────────────────────────

def create_progress_linear_dialog(
    title: str = "正在处理中...",
    message: str = "正在分析文件，请稍候...",
    progress_value: float = 0.65,
    progress_label: str = "65% 已完成",
    progress_detail: str = "13/20 项",
    animate: bool = True,
) -> StyledDialog:
    """Dialog with a linear progress bar."""
    body = QWidget()
    body.setStyleSheet("background: transparent;")
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(0, 0, 0, 0)
    body_layout.setSpacing(8)

    msg = QLabel(message)
    msg.setStyleSheet(f"font-size: 13.5px; color: {tm.mid.name()}; background: transparent;")
    body_layout.addWidget(msg)

    # Web CSS: .dialog-progress .progress { margin-top: 12px; }
    progress = StyledProgress(value=progress_value)
    body_layout.addWidget(progress)

    # Web CSS: .dialog-progress .progress-label { font-size: 12px; margin-top: 8px; }
    label_row = QWidget()
    label_row.setStyleSheet("background: transparent;")
    lr = QHBoxLayout(label_row)
    lr.setContentsMargins(0, 0, 0, 0)
    lr.setSpacing(0)
    left = QLabel(progress_label)
    left.setStyleSheet(f"font-size: 12px; color: {tm.mid.name()}; background: transparent;")
    lr.addWidget(left)
    lr.addStretch()
    right = QLabel(progress_detail)
    right.setStyleSheet(f"font-size: 12px; color: {tm.mid.name()}; background: transparent;")
    lr.addWidget(right)
    body_layout.addWidget(label_row)

    dialog = StyledDialog(animate=animate, title=title, body_widget=body)
    dialog._progress = progress

    cancel_btn = StyledButton("取消", variant="ghost")
    cancel_btn.clicked.connect(lambda: dialog.close_dialog(0))
    dialog._footer_layout.addWidget(cancel_btn)
    _show_dialog(dialog)
    return dialog


def create_progress_circular_dialog(
    title: str = "同步数据",
    message: str = "正在同步云端数据...",
    progress_value: float = 0.70,
    confirm_text: str = "查看详情",
    animate: bool = True,
) -> StyledDialog:
    """Dialog with a circular progress ring."""
    body = QWidget()
    body.setStyleSheet("background: transparent;")
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(0, 8, 0, 0)
    body_layout.setSpacing(8)

    # Web CSS: .progress-circle-wrapper { width: 120px; height: 120px; margin: 16px auto; }
    circle = StyledProgressCircle(value=progress_value, size="lg")
    body_layout.addWidget(circle, alignment=Qt.AlignCenter)

    # Web CSS: .progress-circle-label { font-size: 13px; margin-top: 8px; }
    label = QLabel(message)
    label.setAlignment(Qt.AlignCenter)
    label.setStyleSheet(
        f"font-size: 13px; color: {tm.mid.name()}; background: transparent;"
    )
    body_layout.addWidget(label)

    dialog = StyledDialog(animate=animate, 
        title=title, body_widget=body, footer_type=FOOTER_CENTER,
    )
    dialog._progress_circle = circle

    confirm_btn = StyledButton(confirm_text, variant="primary")
    confirm_btn.clicked.connect(lambda: dialog.close_dialog(1))
    dialog._footer_layout.addWidget(confirm_btn)
    _show_dialog(dialog)
    return dialog


def create_progress_download_dialog(
    progress_value: float = 0.35,
    animate: bool = True,
) -> StyledDialog:
    """Download-progress dialog with three-button footer."""
    body = QWidget()
    body.setStyleSheet("background: transparent;")
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(0, 0, 0, 0)
    body_layout.setSpacing(8)

    # File info row
    info_row = QWidget()
    info_row.setStyleSheet("background: transparent;")
    info_lr = QHBoxLayout(info_row)
    info_lr.setContentsMargins(0, 0, 0, 0)
    file_name = QLabel("v2.4.1 版本更新包")
    file_name.setStyleSheet(f"font-size: 13px; color: {tm.text.name()}; background: transparent;")
    info_lr.addWidget(file_name)
    info_lr.addStretch()
    file_size = QLabel("45.2 MB / 128 MB")
    file_size.setStyleSheet(f"font-size: 12px; color: {tm.mid.name()}; background: transparent;")
    info_lr.addWidget(file_size)
    body_layout.addWidget(info_row)

    # Progress bar (info-blue)
    progress = StyledProgress(value=progress_value)
    progress._track_widget.variant = "default"
    body_layout.addWidget(progress)

    # Progress labels
    label_row = QWidget()
    label_row.setStyleSheet("background: transparent;")
    lr = QHBoxLayout(label_row)
    lr.setContentsMargins(0, 0, 0, 0)
    lr.setSpacing(0)
    left = QLabel("35% — 2.3 MB/s")
    left.setStyleSheet(f"font-size: 12px; color: {tm.mid.name()}; background: transparent;")
    lr.addWidget(left)
    lr.addStretch()
    right = QLabel("预计剩余时间: 36 秒")
    right.setStyleSheet(f"font-size: 12px; color: {tm.mid.name()}; background: transparent;")
    lr.addWidget(right)
    body_layout.addWidget(label_row)

    dialog = StyledDialog(animate=animate, 
        size="lg",
        dialog_type="info",
        title="下载更新",
        body_widget=body,
        footer_type=FOOTER_THREE,
    )
    dialog._progress = progress

    # Left button
    bg_btn = StyledButton("后台下载", variant="ghost")
    bg_btn.clicked.connect(lambda: dialog.close_dialog(0))
    dialog._left_footer_layout.addWidget(bg_btn)

    # Right group
    pause_btn = StyledButton("暂停", variant="ghost")
    pause_btn.clicked.connect(lambda: dialog.close_dialog(0))
    dialog._right_footer_layout.addWidget(pause_btn)

    # Web CSS: style="background: var(--accent-info);"
    download_btn = StyledButton("立即下载", variant="info")
    download_btn.clicked.connect(lambda: dialog.close_dialog(1))
    dialog._right_footer_layout.addWidget(download_btn)

    _show_dialog(dialog)
    return dialog


# ── Button-layout variants ─────────────────────────────────────────

def create_center_button_dialog(
    title: str = "提示",
    message: str = "操作已成功完成。",
    confirm_text: str = "确 定",
    animate: bool = True,
) -> StyledDialog:
    """Small dialog with a single centered button."""
    body = _make_body_label(message)
    dialog = StyledDialog(animate=animate, size="sm", title=title, body_widget=body,
                          footer_type=FOOTER_CENTER)
    confirm_btn = StyledButton(confirm_text, variant="primary")
    confirm_btn.clicked.connect(lambda: dialog.close_dialog(1))
    dialog._footer_layout.addWidget(confirm_btn)
    _show_dialog(dialog)
    return dialog


def create_left_button_dialog(
    title: str = "导出设置",
    message: str = "请选择导出格式：",
    animate: bool = True,
) -> StyledDialog:
    """Dialog with left-aligned footer buttons."""
    body = QWidget()
    body.setStyleSheet("background: transparent;")
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(0, 0, 0, 0)
    body_layout.setSpacing(12)

    msg = QLabel(message)
    msg.setStyleSheet(f"font-size: 13.5px; color: {tm.mid.name()}; background: transparent;")
    body_layout.addWidget(msg)

    from components.styled_radio import StyledRadio
    radio_row = QWidget()
    radio_row.setStyleSheet("background: transparent;")
    rr = QHBoxLayout(radio_row)
    rr.setContentsMargins(0, 0, 0, 0)
    rr.setSpacing(12)
    rr.addWidget(StyledRadio(checked=True, text="JSON", group_name="export-fmt"))
    rr.addWidget(StyledRadio(checked=False, text="YAML", group_name="export-fmt"))
    rr.addWidget(StyledRadio(checked=False, text="TOML", group_name="export-fmt"))
    rr.addStretch()
    body_layout.addWidget(radio_row)

    dialog = StyledDialog(animate=animate, title=title, body_widget=body, footer_type=FOOTER_LEFT)

    export_btn = StyledButton("导出", variant="primary")
    export_btn.clicked.connect(lambda: dialog.close_dialog(1))
    dialog._footer_layout.addWidget(export_btn)

    cancel_btn = StyledButton("取消", variant="ghost")
    cancel_btn.clicked.connect(lambda: dialog.close_dialog(0))
    dialog._footer_layout.addWidget(cancel_btn)

    _show_dialog(dialog)
    return dialog


def create_stacked_button_dialog(
    title: str = "选择操作",
    message: str = "请选择您要进行的操作：",
    animate: bool = True,
) -> StyledDialog:
    """Small dialog with full-width stacked buttons."""
    body = _make_body_label(message)
    dialog = StyledDialog(animate=animate, size="sm", title=title, body_widget=body,
                          footer_type=FOOTER_STACKED)

    # Web CSS: .dialog-footer-stacked .btn { width: 100%; }
    btn1 = StyledButton("创建新项目", variant="primary", block=True)
    btn1.clicked.connect(lambda: dialog.close_dialog(1))
    dialog._footer_layout.addWidget(btn1)

    btn2 = StyledButton("从模板导入", variant="secondary", block=True)
    btn2.clicked.connect(lambda: dialog.close_dialog(2))
    dialog._footer_layout.addWidget(btn2)

    btn3 = StyledButton("暂不操作", variant="ghost", block=True)
    btn3.clicked.connect(lambda: dialog.close_dialog(0))
    dialog._footer_layout.addWidget(btn3)

    _show_dialog(dialog)
    return dialog


def create_three_button_dialog(
    title: str = "保存更改",
    message: str = "您有未保存的更改，是否保存？",
    animate: bool = True,
) -> StyledDialog:
    """Dialog with left + right button groups."""
    body = _make_body_label(message)
    dialog = StyledDialog(animate=animate, title=title, body_widget=body, footer_type=FOOTER_THREE)

    cancel_btn = StyledButton("取消", variant="ghost")
    cancel_btn.clicked.connect(lambda: dialog.close_dialog(0))
    dialog._left_footer_layout.addWidget(cancel_btn)

    no_save_btn = StyledButton("不保存", variant="ghost")
    no_save_btn.clicked.connect(lambda: dialog.close_dialog(2))
    dialog._right_footer_layout.addWidget(no_save_btn)

    save_btn = StyledButton("保存", variant="primary")
    save_btn.clicked.connect(lambda: dialog.close_dialog(1))
    dialog._right_footer_layout.addWidget(save_btn)

    _show_dialog(dialog)
    return dialog


def create_help_link_dialog(
    title: str = "许可协议",
    message: str = "请阅读并同意我们的服务条款和隐私政策，以继续使用本软件。",
    animate: bool = True,
) -> StyledDialog:
    """Dialog with a help link in the footer."""
    body = _make_body_label(message)
    dialog = StyledDialog(animate=animate, title=title, body_widget=body, footer_type=FOOTER_WITH_HELP)

    reject_btn = StyledButton("拒绝", variant="ghost")
    reject_btn.clicked.connect(lambda: dialog.close_dialog(0))
    dialog._right_footer_layout.addWidget(reject_btn)

    accept_btn = StyledButton("同意并继续", variant="primary")
    accept_btn.clicked.connect(lambda: dialog.close_dialog(1))
    dialog._right_footer_layout.addWidget(accept_btn)

    _show_dialog(dialog)
    return dialog


def create_no_border_dialog(
    title: str = "快捷操作",
    animate: bool = True,
) -> StyledDialog:
    """Dialog with no footer border and action buttons in the body."""
    body = QWidget()
    body.setStyleSheet("background: transparent;")
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(0, 0, 0, 0)
    body_layout.setSpacing(8)

    msg = QLabel("请选择一个快捷操作：")
    msg.setStyleSheet(f"font-size: 13.5px; color: {tm.mid.name()}; background: transparent;")
    body_layout.addWidget(msg)

    for text in ["📋 复制选中文本", "🔗 生成分享链接", " 导出为文件"]:
        btn = StyledButton(text, variant="ghost")
        btn.setContentsMargins(12, 0, 0, 0)
        body_layout.addWidget(btn, alignment=Qt.AlignLeft)

    dialog = StyledDialog(animate=animate, title=title, body_widget=body, footer_type=FOOTER_NO_BORDER)

    close_btn = StyledButton("关闭", variant="primary")
    close_btn.clicked.connect(lambda: dialog.close_dialog(0))
    dialog._footer_layout.addWidget(close_btn)

    _show_dialog(dialog)
    return dialog


def create_no_footer_dialog(
    title: str = "关于",
    animate: bool = True,
) -> StyledDialog:
    """Dialog with no footer at all (about-style)."""
    body = QWidget()
    body.setStyleSheet("background: transparent;")
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(0, 8, 0, 8)
    body_layout.setSpacing(4)

    emoji = QLabel("🎉")
    emoji.setAlignment(Qt.AlignCenter)
    emoji.setStyleSheet("font-size: 48px; background: transparent;")
    body_layout.addWidget(emoji)

    name = QLabel("D-Fronted")
    name.setAlignment(Qt.AlignCenter)
    name.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {tm.text.name()}; background: transparent;")
    body_layout.addWidget(name)

    version = QLabel("版本 2.4.1")
    version.setAlignment(Qt.AlignCenter)
    version.setStyleSheet(f"font-size: 13px; color: {tm.mid.name()}; background: transparent;")
    body_layout.addWidget(version)

    copyright_ = QLabel("© 2026 All rights reserved.")
    copyright_.setAlignment(Qt.AlignCenter)
    copyright_.setStyleSheet(f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; background: transparent; margin-top: 8px;")
    body_layout.addWidget(copyright_)

    dialog = StyledDialog(animate=animate, size="sm", title=title, body_widget=body,
                          footer_type=FOOTER_NONE, show_close=True)
    _show_dialog(dialog)
    return dialog
