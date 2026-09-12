"""Styled Dialog component - matches web dialog exactly.

Provides:
  - StyledDialog: standalone frameless top-level dialog window
  - DialogIconCircle: icon circle for success/danger variants
  - Factory functions for all dialog variants
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit,
    QApplication,
)
from PySide6.QtCore import (
    Qt, Signal, QObject, QEventLoop, QPropertyAnimation, QEasingCurve, Property, QRectF, QPoint,
)
from PySide6.QtGui import QPainter, QColor, QPaintEvent, QFont, QCursor, QMouseEvent
from typing import Dict, List, Optional

from theme import tm

from components.styled_button import StyledButton
from components.paint_utils import render_soft_shadow
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss


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


class DialogAnimationEffect(QObject):
    """Opacity/scale state for the dialog enter/exit animation.

    Previously a graphics-effect subclass that composited the whole
    dialog through an offscreen pixmap; now a plain :class:`QObject`
    holding the same ``opacity``/``scale`` properties (clamped, kept for
    backward compatibility). Opacity reaches the screen via the
    dialog's ``windowOpacity``; ``draw()`` only applies painter opacity
    so existing callers keep working. The paint path uses no effect.
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

    @Property(float)
    def scale(self) -> float:
        return self._scale

    @scale.setter
    def scale(self, value: float) -> None:
        self._scale = max(0.0, value)

    def draw(self, painter: QPainter) -> None:
        """Apply the stored opacity to *painter* (compat shim)."""
        painter.save()
        try:
            painter.setOpacity(self._opacity)
        finally:
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

        # Register the OS-level window title with the dialog's own title so
        # taskbars / Win32 tools (Alt+Tab, Spy++, accessibility) don't show
        # the generic "python" placeholder. The visual header is built later
        # via _build_header(), so we capture the title here and sync it then.
        self._registered_title: str = ""

        # Animation (opacity via windowOpacity; scale micro-zoom retired
        # with the offscreen path — steady states render identically)
        self._anim_effect: Optional[DialogAnimationEffect] = None
        self._enter_opacity_anim: Optional[QPropertyAnimation] = None
        self._exit_opacity_anim: Optional[QPropertyAnimation] = None
        if self._animate:
            self._setup_animations()

        self.setObjectName("StyledDialog")
        # Window is larger than content to accommodate shadow
        content_width = SIZE_CONFIG[self._size]["width"]
        self.setFixedWidth(content_width + self.SHADOW_MARGIN * 2)

        # Create content container with shadow
        self._content_widget = QWidget(self)
        self._content_widget.setObjectName("DialogContent")
        register_widget_qss(self._content_widget,(f"""
            #DialogContent {{
                background-color: {tm.surface.name()};
                border: 1px solid {tm.alpha_of(tm.surface, 90).name()};
                border-radius: 12px;
            }}
        """))

        # Web CSS: box-shadow: var(--shadow-lg) — pre-baked soft shadow,
        # painted in paintEvent via render_soft_shadow (single drawPixmap,
        # no graphics effect on the paint path).
        self._shadow_color = tm.alpha_of(tm.black, 50)

        # Layout for content container
        content_layout = QVBoxLayout(self._content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        if title or show_close:
            self._registered_title = title or "Dialog"
            self.setWindowTitle(self._registered_title)
            self._build_header(title, show_close, content_layout)
        else:
            # 没有 header（FOOTER_NONE 等场景）也要设置窗口标题，否则
            # Alt+Tab/Spy++ 会显示默认的 "python"。
            self._registered_title = "Dialog"
            self.setWindowTitle(self._registered_title)

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
        register_widget_qss(header_frame,("background: transparent; border: none;"))
        header_frame.setContentsMargins(24, 20, 12, 0)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)

        colors = self._get_type_colors()[self._dialog_type]

        # Web CSS: .dialog-header-with-icon { display: flex; flex-direction: column; }
        if self._dialog_type in ("success", "danger", "info"):
            # 带图标的 header: icon 在上，title 在下
            icon_title_widget = QWidget()
            register_widget_qss(icon_title_widget,("background: transparent;"))
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
        register_widget_qss(body_frame,("background: transparent; border: none;"))
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
        register_widget_qss(footer_frame,(f"#footer_frame {{ background: transparent; {border_css} }}"))

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
            register_widget_qss(self._left_footer_widget,("background: transparent;"))
            self._left_footer_layout = QHBoxLayout(self._left_footer_widget)
            self._left_footer_layout.setContentsMargins(0, 0, 0, 0)
            self._left_footer_layout.setSpacing(10)
            layout.addWidget(self._left_footer_widget)
            layout.addStretch()
            self._right_footer_widget = QWidget()
            register_widget_qss(self._right_footer_widget,("background: transparent;"))
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
            register_widget_qss(self._help_link,(f"""
                QPushButton {{
                    background: transparent; border: none; color: {tm.accent.name()};
                    font-size: 12px; text-align: left; padding: 0;
                }}
                QPushButton:hover {{ text-decoration: underline; }}
            """))
            layout.addWidget(self._help_link)
            layout.addStretch()
            self._right_footer_widget = QWidget()
            register_widget_qss(self._right_footer_widget,("background: transparent;"))
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
        register_widget_qss(btn,(
            f"QPushButton {{ background: transparent; border: none; border-radius: 6px;"
            f" color: {tm.mid.name()}; font-size: 18px; font-weight: 300; }}"
            f"QPushButton:hover {{ background-color: {tm.surface.name()}; color: {tm.text.name()}; }}"
        ))
        btn.setText("✕")
        btn.clicked.connect(lambda: self.close_dialog(0))
        return btn

    @staticmethod
    def _make_label(text: str, font_size: int, weight, color: str) -> QLabel:
        label = QLabel(text)
        font = QFont("Microsoft YaHei UI", font_size)
        font.setWeight(weight)
        label.setFont(font)
        register_widget_qss(label,(f"color: {color}; background: transparent; border: none;"))
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
        """Wire enter/exit fades to ``windowOpacity`` (WM-composited)."""
        self._anim_effect = DialogAnimationEffect(self)
        self._anim_effect.opacity = 1.0
        self._anim_effect.scale = 1.0

        self._enter_opacity_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._enter_opacity_anim.setDuration(180)
        self._enter_opacity_anim.setStartValue(0.0)
        self._enter_opacity_anim.setEndValue(1.0)
        self._enter_opacity_anim.setEasingCurve(QEasingCurve.InOutCubic)

        self._exit_opacity_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._exit_opacity_anim.setDuration(180)
        self._exit_opacity_anim.setStartValue(1.0)
        self._exit_opacity_anim.setEndValue(0.0)
        self._exit_opacity_anim.setEasingCurve(QEasingCurve.InOutCubic)

        self._exit_opacity_anim.finished.connect(self._finish_close)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if (
            self._animate
            and self._enter_opacity_anim is not None
            and not self._shown_once
        ):
            self._shown_once = True
            self.setWindowOpacity(0.0)
            self._enter_opacity_anim.start()

    def closeEvent(self, event) -> None:
        if self._animate and not self._is_closing and self._exit_opacity_anim is not None:
            self._is_closing = True
            event.ignore()
            self._exit_opacity_anim.start()
            return
        self._is_closing = False
        self.setWindowOpacity(1.0)
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

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint the pre-baked content shadow under the content widget.

        The root stays transparent (``WA_TranslucentBackground``); the
        shadow bitmap is composited with one ``drawPixmap`` before the
        children paint themselves on top.
        """
        painter = QPainter(self)
        try:
            geom = self._content_widget.geometry()
            shadow = render_soft_shadow(
                geom.width(), geom.height(), 12, 60,
                self._shadow_color, self.SHADOW_MARGIN,
            )
            if not shadow.isNull():
                painter.drawPixmap(
                    geom.x() - self.SHADOW_MARGIN,
                    geom.y() - self.SHADOW_MARGIN + 10,
                    shadow,
                )
        finally:
            painter.end()

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
    register_widget_qss(w,("background: transparent;"))
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    register_widget_qss(lbl,(
        f"font-size: 13.5px; color: {tm.mid.name()}; background: transparent;"
    ))
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
    
    # Move to screen center (cursor's screen so multi-monitor setups are honored)
    cursor_pos = QCursor.pos()
    screen = QApplication.screenAt(cursor_pos)
    if not screen:
        screen = QApplication.primaryScreen()
    screen_geom = screen.availableGeometry()
    # Center the visible content area (excluding the shadow margin) on the
    # screen. Computing the offset from the content's own center prevents the
    # visual drift caused by the shadow margin being double-counted.
    cx = screen_geom.x() + (screen_geom.width() - content_width) // 2 - dialog.SHADOW_MARGIN
    cy = screen_geom.y() + (screen_geom.height() - content_height) // 2 - dialog.SHADOW_MARGIN
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


# Maps CustomMessageBox style names to StyledButton variants.
_VARIANT_MAP: Dict[str, str] = {
    "primary": "primary",
    "secondary": "secondary",
    "ghost": "ghost",
    "danger": "danger",
    "info": "info",
    "normal": "ghost",
}


def create_custom_dialog(
    title: str,
    message: str,
    buttons: List[str],
    variants: Optional[List[str]] = None,
    vertical: bool = False,
    dialog_type: str = "default",
    show_close: bool = False,
    animate: bool = True,
) -> StyledDialog:
    """兼容 CustomMessageBox 接口的多按钮弹窗。

    Args:
        title: 弹窗标题。
        message: 主体文本。
        buttons: 按钮文案列表（从左到右/从上到下）。
        variants: 与 buttons 一一对应的变体名（primary/secondary/ghost/danger/info/normal）。
        vertical: True 则按钮纵向排列，否则横向。
        dialog_type: 弹窗类型（default/success/danger/info），影响图标。
        show_close: 是否显示右上角关闭按钮。
        animate: 是否启用入场/出场动画。
    """
    body = _make_body_label(message)
    footer_type = FOOTER_STACKED if vertical else FOOTER_RIGHT
    dialog = StyledDialog(
        animate=animate,
        dialog_type=dialog_type if dialog_type in ("success", "danger", "info", "default") else "default",
        title=title,
        body_widget=body,
        footer_type=footer_type,
        show_close=show_close,
    )
    for idx, text in enumerate(buttons):
        variant_name = variants[idx] if variants and idx < len(variants) else "primary"
        variant = _VARIANT_MAP.get(variant_name, "primary")
        btn = StyledButton(text, variant=variant)
        btn.clicked.connect(lambda *args, i=idx, d=dialog: d.close_dialog(i))
        dialog._footer_layout.addWidget(btn)
    _show_dialog(dialog)
    return dialog




def ask_custom_dialog(
    title: str,
    message: str,
    buttons: List[str],
    variants: Optional[List[str]] = None,
    vertical: bool = False,
    dialog_type: str = "default",
    show_close: bool = False,
    animate: bool = True,
) -> int:
    """同步阻塞的多按钮弹窗：返回被点击按钮的索引（0-based）。

    ``StyledDialog`` 继承自 QWidget（无 ``exec()``），本助手以
    ``QEventLoop`` 阻塞当前调用直至用户点击按钮 / 关闭对话框；
    ``finished`` 未发射（ESC/关闭按钮）时兜底返回 0。

    Args:
        title: 弹窗标题。
        message: 主体文本。
        buttons: 按钮文案列表。
        variants: 与 buttons 一一对应的变体名（primary/secondary/ghost/danger/info/normal）。
        vertical: True 则按钮纵向排列，否则横向。
        dialog_type: 弹窗类型（default/success/danger/info），影响图标。
        show_close: 是否显示右上角关闭按钮。
        animate: 是否启用入场/出场动画。

    Returns:
        int: 被点击按钮的索引；关闭路径兜底返回 0。
    """
    dialog = create_custom_dialog(
        title=title,
        message=message,
        buttons=buttons,
        variants=variants,
        vertical=vertical,
        dialog_type=dialog_type,
        show_close=show_close,
        animate=animate,
    )
    result: List[int] = [0]
    loop = QEventLoop()

    def _on_finished(idx: int) -> None:
        result[0] = idx
        loop.quit()

    dialog.finished.connect(_on_finished)
    # 兜底：用户用 ESC / 关闭按钮时 finished 可能不发射
    dialog.destroyed.connect(loop.quit)
    loop.exec()
    return result[0]


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


def create_input_dialog(
    title: str = "重命名",
    message: str = "请输入新的名称：",
    placeholder: str = "输入新名称...",
    cancel_text: str = "取消",
    confirm_text: str = "确认",
    show_close: bool = False,
    animate: bool = True,
) -> StyledDialog:
    """Input dialog with a text field."""
    body = QWidget()
    register_widget_qss(body,("background: transparent;"))
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(0, 0, 0, 0)
    body_layout.setSpacing(0)

    msg_label = QLabel(message)
    register_widget_qss(msg_label,(
        f"font-size: 13.5px; color: {tm.mid.name()}; background: transparent;"
    ))
    body_layout.addWidget(msg_label)

    # Web CSS: .dialog-input { margin-top: 12px; width: 100%; }
    input_field = QLineEdit()
    input_field.setPlaceholderText(placeholder)
    register_widget_qss(input_field,(f"""
        QLineEdit {{
            background-color: {tm.surface.name()}; border: 1px solid {tm.mid.name()}; border-radius: 6px;
            padding: 8px 12px; font-size: 13px; color: {tm.text.name()}; margin-top: 12px;
        }}
        QLineEdit:focus {{ border-color: {tm.accent.name()}; }}
    """))
    body_layout.addWidget(input_field)

    dialog = StyledDialog(
        animate=animate, title=title, body_widget=body, show_close=show_close,
    )
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


# ── Progress dialogs ───────────────────────────────────────────────

# ── Button-layout variants ─────────────────────────────────────────
