"""Styled Date Picker component - matches web DatePicker exactly."""

from theme import tm
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QLabel, QFrame, QApplication, QLineEdit
)
from PySide6.QtCore import (
    Qt, Signal, QRectF, QPoint, QDate, QSize, QTimer, QEvent,
    QPropertyAnimation, QEasingCurve, Property,
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QPainterPath, QFont, QMouseEvent, QKeyEvent, QPaintEvent, QCursor
)

from datetime import datetime

# Font config
FONT_FAMILY = "Microsoft YaHei UI"

def _font(size: int, weight: int = QFont.Normal) -> QFont:
    """Create font with proper family and anti-aliasing."""
    f = QFont(FONT_FAMILY, size, weight)
    f.setStyleStrategy(QFont.PreferAntialias)
    return f


class _CalendarPanel(QFrame):
    """The dropdown calendar panel."""

    date_selected = Signal(str)
    range_selected = Signal(str, str)
    closed = Signal()

    @property
    def _bg_card(self) -> QColor:
        return tm.alpha_of(tm.surface, 90)

    @property
    def _border_color(self) -> QColor:
        return tm.alpha_of(tm.mid, 40)

    def __init__(self, parent=None):
        super().__init__(None)  # No parent to allow independent popup
        self.setObjectName("calendarPanel")
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.setFrameShape(QFrame.NoFrame)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedWidth(280)
        self._parent_ref = parent  # Keep reference for positioning
        self._current_year = datetime.now().year
        self._current_month = datetime.now().month
        self._selected_date = None
        self._range_start = None
        self._range_end = None
        self._is_range = False
        self._is_datetime = False
        self._is_month_picker = False
        self._time_hour = 0
        self._time_minute = 0
        self._selecting_range_end = False
        self._hovered_cell = -1  # (row, col) tuple
        self._closing_internally = False

        # Style - removed stylesheet, using paintEvent instead
        # Match ComboBox popup style: no nested containers, direct drawing

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(0)

        # Header
        header_layout = QHBoxLayout()
        header_layout.setSpacing(0)

        self._prev_btn = _NavButton(-1, self)
        self._prev_btn.clicked.connect(self._prev_month)

        self._header_label = QLabel()
        self._header_label.setStyleSheet(f"""
            color: {tm.text.name()}; font-size: 14px; font-weight: 500;
            padding: 4px 8px; border-radius: 4px;
        """)
        self._header_label.setCursor(Qt.PointingHandCursor)
        self._header_label.setAlignment(Qt.AlignCenter)

        self._next_btn = _NavButton(1, self)
        self._next_btn.clicked.connect(self._next_month)

        header_layout.addWidget(self._prev_btn)
        header_layout.addWidget(self._header_label, 1)
        header_layout.addWidget(self._next_btn)
        main_layout.addLayout(header_layout)

        # Weekday labels (hidden for month picker)
        weekdays_layout = QHBoxLayout()
        weekdays_layout.setSpacing(2)
        weekdays_layout.setContentsMargins(0, 8, 0, 4)
        for wd in ["日", "一", "二", "三", "四", "五", "六"]:
            lbl = QLabel(wd)
            lbl.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()}; font-size: 11px;")
            lbl.setAlignment(Qt.AlignCenter)
            weekdays_layout.addWidget(lbl)
        self._weekdays_widget = QWidget()
        self._weekdays_widget.setLayout(weekdays_layout)
        main_layout.addWidget(self._weekdays_widget)

        # Days grid
        self._days_widget = _DaysGrid(self)
        self._days_widget.date_clicked.connect(self._on_date_clicked)
        self._days_widget.hover_changed.connect(self._on_hover_changed)
        main_layout.addWidget(self._days_widget)

        # Month grid (hidden by default)
        self._months_widget = _MonthsGrid(self)
        self._months_widget.month_clicked.connect(self._on_month_clicked)
        self._months_widget.hide()
        main_layout.addWidget(self._months_widget)

        # Time picker (hidden by default, shown for datetime mode)
        self._time_picker = _TimePicker(self)
        self._time_picker.time_changed.connect(self._on_time_changed)
        self._time_picker.hide()
        main_layout.addWidget(self._time_picker)

        # Footer
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 12, 0, 0)

        self._today_btn = QPushButton("今天")
        self._today_btn.setCursor(Qt.PointingHandCursor)
        self._today_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {tm.accent.name()}; font-size: 12px;
                border: none; padding: 4px 8px; border-radius: 4px;
            }}
            QPushButton:hover {{ background: {tm.fill.lighter(115).name()}; }}
        """)
        self._today_btn.clicked.connect(self._select_today)
        footer_layout.addWidget(self._today_btn)
        footer_layout.addStretch()

        self._footer_widget = QWidget()
        self._footer_widget.setLayout(footer_layout)
        main_layout.addWidget(self._footer_widget)

        self._update_header()

    def set_date(self, date_str: str):
        """Set selected date (YYYY-MM-DD)."""
        self._selected_date = date_str
        if date_str:
            parts = date_str.split("-")
            self._current_year = int(parts[0])
            self._current_month = int(parts[1])
            self._update_header()
        self._days_widget.update()

    def set_range(self, start: str, end: str):
        """Set range selection."""
        self._range_start = start
        self._range_end = end
        self._days_widget.update()

    def set_range_mode(self, enabled: bool):
        self._is_range = enabled
        self._selecting_range_end = False

    def set_datetime_mode(self, enabled: bool):
        self._is_datetime = enabled
        self._time_picker.setVisible(enabled)

    def set_month_picker_mode(self, enabled: bool):
        self._is_month_picker = enabled
        self._weekdays_widget.setVisible(not enabled)
        self._days_widget.setVisible(not enabled)
        self._months_widget.setVisible(enabled)
        self._today_btn.setVisible(not enabled)
        if enabled:
            self._prev_btn._direction = -12
            self._next_btn._direction = 12
        self._update_header()

    def _update_header(self):
        if self._is_month_picker:
            self._header_label.setText(f"{self._current_year}年")
        else:
            self._header_label.setText(f"{self._current_year}年{self._current_month}月")
        self._days_widget.update()
        self._months_widget.update()

    def _prev_month(self):
        if self._is_month_picker:
            self._current_year -= 1
        else:
            self._current_month -= 1
            if self._current_month < 1:
                self._current_month = 12
                self._current_year -= 1
        self._update_header()

    def _next_month(self):
        if self._is_month_picker:
            self._current_year += 1
        else:
            self._current_month += 1
            if self._current_month > 12:
                self._current_month = 1
                self._current_year += 1
        self._update_header()

    def _on_date_clicked(self, date_str: str):
        if not date_str:
            return

        if self._is_range:
            if not self._range_start or (self._range_start and self._range_end):
                self._range_start = date_str
                self._range_end = None
                self._selecting_range_end = True
                self._days_widget.update()
            else:
                if date_str < self._range_start:
                    self._range_end = self._range_start
                    self._range_start = date_str
                else:
                    self._range_end = date_str
                self._selecting_range_end = False
                self._days_widget.update()
                self.range_selected.emit(self._range_start, self._range_end)
                self._close()
        else:
            self._selected_date = date_str
            if self._is_datetime:
                # Don't close immediately in datetime mode - let user set time too
                val = f"{date_str} {self._time_hour:02d}:{self._time_minute:02d}"
                self.date_selected.emit(val)
                self._days_widget.update()
            else:
                val = date_str
                self.date_selected.emit(val)
                self._close()

    def _on_month_clicked(self, month: int):
        self._current_month = month
        self._selected_date = f"{self._current_year}-{month:02d}"
        # 月份选择器模式下只显示年份，否则显示年份+月份
        if self._is_month_picker:
            self._header_label.setText(f"{self._current_year}年")
        else:
            self._header_label.setText(f"{self._current_year}年{month}月")
        self.date_selected.emit(f"{self._current_year}-{month:02d}")
        self._close()

    def _on_hover_changed(self, cell: int):
        self._hovered_cell = cell
        self._days_widget.update()

    def _on_time_changed(self, hour: int, minute: int):
        """Handle time change from time picker."""
        self._time_hour = hour
        self._time_minute = minute
        # If a date is already selected, emit the updated datetime
        if self._selected_date and self._is_datetime:
            val = f"{self._selected_date} {self._time_hour:02d}:{self._time_minute:02d}"
            self.date_selected.emit(val)

    def _select_today(self):
        today = datetime.now()
        date_str = today.strftime("%Y-%m-%d")
        self._current_year = today.year
        self._current_month = today.month
        self._selected_date = date_str
        self._update_header()

        if self._is_datetime:
            self._time_hour = today.hour
            self._time_minute = today.minute
            val = f"{date_str} {self._time_hour:02d}:{self._time_minute:02d}"
        else:
            val = date_str

        self.date_selected.emit(val)
        self._close()

    def _close(self):
        self.close_animated()

    def showEvent(self, event):
        super().showEvent(event)
        self._days_widget.update()
        self._closing_internally = False

    def paintEvent(self, event: QPaintEvent):
        """Draw rounded background + border, matching ComboBox popup style."""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        r = 8

        # Background
        p.setPen(Qt.NoPen)
        p.setBrush(self._bg_card)
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        # Border
        p.setPen(QPen(self._border_color, 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)
        p.end()

    def show_animated(self, anchor: QPoint):
        """Fade in + slide down from anchor point, matching ComboBox."""
        start_h = 10
        target_w = self.width()
        target_h = self.sizeHint().height()

        x = anchor.x()
        self.setGeometry(x, anchor.y(), target_w, start_h)
        self.setWindowOpacity(0.0)
        super().show()

        # Opacity animation
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(200)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)

        # Height slide animation
        self._slide = QPropertyAnimation(self, b"geometry")
        self._slide.setDuration(220)
        self._slide.setStartValue(self.geometry())
        self._slide.setEndValue(
            QRectF(x, anchor.y(), target_w, target_h).toRect()
        )
        self._slide.setEasingCurve(QEasingCurve.OutCubic)

        self._fade.start()
        self._slide.start()

    def close_animated(self):
        """Slide up + fade out for smooth dismiss."""
        self._closing_internally = True
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(150)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.InCubic)

        self._slide = QPropertyAnimation(self, b"geometry")
        self._slide.setDuration(150)
        self._slide.setStartValue(self.geometry())
        end = QRectF(self.geometry())
        end.setHeight(10)
        self._slide.setEndValue(end.toRect())
        self._slide.setEasingCurve(QEasingCurve.InCubic)

        self._slide.finished.connect(self._on_close_animation_finished)
        self._fade.start()
        self._slide.start()

    def _on_close_animation_finished(self):
        self.hide()
        self.closed.emit()


class _DaysGrid(QWidget):
    """Widget that renders the days grid."""

    date_clicked = Signal(str)
    hover_changed = Signal(int)

    @property
    def _accent_primary(self) -> QColor:
        return tm.accent

    @property
    def _text_primary(self) -> QColor:
        return tm.text

    def __init__(self, panel: _CalendarPanel, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(210)
        self.setMouseTracking(True)
        self._panel = panel
        self._hover_progress = {}  # cell_idx -> progress (0.0 to 1.0)
        self._hover_targets = {}  # cell_idx -> target value
        self._hover_timers = {}  # cell_idx -> QTimer
        self._current_hover_idx = -1

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        panel = self._panel
        year = panel._current_year
        month = panel._current_month

        first_day = QDate(year, month, 1)
        last_day = first_day.daysInMonth()
        start_weekday = first_day.dayOfWeek() % 7  # 0=Sun

        today = QDate.currentDate()
        today_str = today.toString("yyyy-MM-dd")

        cell_w = self.width() / 7
        cell_h = 32

        day = 1
        prev_month_days = QDate(year, month, 1).addDays(-1).day()

        # Draw grid: 6 rows max
        for row in range(6):
            for col in range(7):
                idx = row * 7 + col
                is_current_month = False
                display_day = 0
                date_str = ""

                if idx < start_weekday:
                    display_day = prev_month_days - (start_weekday - 1 - idx)
                    pm = month - 1 if month > 1 else 12
                    py = year if month > 1 else year - 1
                    date_str = f"{py}-{pm:02d}-{display_day:02d}"
                elif day <= last_day:
                    is_current_month = True
                    display_day = day
                    date_str = f"{year}-{month:02d}-{day:02d}"
                    day += 1
                else:
                    display_day = day - last_day
                    nm = month + 1 if month < 12 else 1
                    ny = year if month < 12 else year + 1
                    date_str = f"{ny}-{nm:02d}-{display_day:02d}"
                    day += 1

                x = col * cell_w
                y = row * cell_h

                # Determine state
                is_selected = (date_str == panel._selected_date)
                is_today = (date_str == today_str)
                is_other = not is_current_month
                is_hovered = (panel._hovered_cell == idx and is_current_month)

                is_range_start = (date_str == panel._range_start)
                is_range_end = (date_str == panel._range_end)
                is_in_range = False
                if panel._range_start and panel._range_end and is_current_month:
                    is_in_range = panel._range_start < date_str < panel._range_end

                # Get hover progress for this cell
                hover_progress = self._hover_progress.get(idx, 0.0)

                # Draw in-range background
                if is_in_range:
                    painter.fillRect(
                        int(x + 2), int(y + 2), int(cell_w - 4), int(cell_h - 4),
                        tm.alpha_of(tm.accent, 10)
                    )

                # Draw day cell
                rect = QRectF(x + 2, y + 2, cell_w - 4, cell_h - 4)

                if is_selected or is_range_start or is_range_end:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(self._accent_primary)
                    painter.drawRoundedRect(rect, 4, 4)
                    painter.setPen(tm.text)
                    painter.setFont(_font(13))
                elif hover_progress > 0:
                    # Animated hover background
                    r = int(50 + (60 - 50) * hover_progress)
                    g = int(50 + (60 - 50) * hover_progress)
                    b = int(50 + (60 - 50) * hover_progress)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(r, g, b))
                    painter.drawRoundedRect(rect, 4, 4)
                    # Animated text color
                    tr = int(160 + (232 - 160) * hover_progress)
                    tg = int(160 + (232 - 160) * hover_progress)
                    tb = int(160 + (232 - 160) * hover_progress)
                    painter.setPen(QColor(tr, tg, tb))
                    painter.setFont(_font(13))
                elif is_other:
                    painter.setPen(tm.alpha_of(tm.mid, 60))
                    painter.setFont(_font(13))
                else:
                    painter.setPen(self._text_primary)
                    painter.setFont(_font(13))

                # Today border
                if is_today and not is_selected:
                    painter.setPen(QPen(self._accent_primary, 1))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawRoundedRect(rect, 4, 4)
                    painter.setPen(tm.text if (is_selected or is_range_start or is_range_end) else self._text_primary)

                # Opacity for other month
                if is_other:
                    painter.setOpacity(0.4)

                painter.drawText(
                    QRectF(x, y, cell_w, cell_h),
                    Qt.AlignCenter,
                    str(display_day)
                )
                painter.setOpacity(1.0)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            return

        panel = self._panel
        year = panel._current_year
        month = panel._current_month

        first_day = QDate(year, month, 1)
        last_day = first_day.daysInMonth()
        start_weekday = first_day.dayOfWeek() % 7

        cell_w = self.width() / 7
        cell_h = 32

        col = int(event.position().x() / cell_w)
        row = int(event.position().y() / cell_h)
        idx = row * 7 + col

        if idx < start_weekday:
            display_day = QDate(year, month, 1).addDays(-1).day() - (start_weekday - 1 - idx)
            pm = month - 1 if month > 1 else 12
            py = year if month > 1 else year - 1
            date_str = f"{py}-{pm:02d}-{display_day:02d}"
        elif idx < start_weekday + last_day:
            day = idx - start_weekday + 1
            date_str = f"{year}-{month:02d}-{day:02d}"
        else:
            display_day = idx - start_weekday - last_day + 1
            nm = month + 1 if month < 12 else 1
            ny = year if month < 12 else year + 1
            date_str = f"{ny}-{nm:02d}-{display_day:02d}"

        # Only current month dates are clickable
        is_current = idx >= start_weekday and idx < start_weekday + last_day
        if not is_current:
            return

        self.date_clicked.emit(date_str)

    def mouseMoveEvent(self, event: QMouseEvent):
        col = int(event.position().x() / (self.width() / 7))
        row = int(event.position().y() / 32)
        idx = row * 7 + col

        if idx != self._current_hover_idx:
            # Animate out old cell
            if self._current_hover_idx >= 0:
                self._animate_cell_hover(self._current_hover_idx, 0.0)
            # Animate in new cell
            if idx >= 0:
                self._animate_cell_hover(idx, 1.0)
            self._current_hover_idx = idx
            self.hover_changed.emit(idx)

    def leaveEvent(self, event):
        # Clear hover when mouse leaves the widget
        if self._current_hover_idx >= 0:
            self._animate_cell_hover(self._current_hover_idx, 0.0)
            self._current_hover_idx = -1
        super().leaveEvent(event)

    def _animate_cell_hover(self, idx: int, target: float):
        """Animate hover progress for a specific cell using QTimer."""
        self._hover_targets[idx] = target
        
        # Stop existing timer for this cell if any
        if idx in self._hover_timers and self._hover_timers[idx] is not None:
            self._hover_timers[idx].stop()
        
        # Create new timer for this cell
        timer = QTimer(self)
        timer.setInterval(16)  # ~60fps
        timer.timeout.connect(lambda: self._update_hover_progress(idx))
        self._hover_timers[idx] = timer
        timer.start()

    def _update_hover_progress(self, idx: int):
        """Update hover progress for a specific cell."""
        target = self._hover_targets.get(idx, 0.0)
        current = self._hover_progress.get(idx, 0.0)
        
        # If already at target, stop
        if abs(target - current) < 0.01:
            self._hover_progress[idx] = target
            if idx in self._hover_timers:
                self._hover_timers[idx].stop()
                del self._hover_timers[idx]
            self.update()
            return
        
        # Calculate step (160ms duration / 16ms interval = 10 steps)
        step = 0.1 if target > current else -0.1
        
        new_value = current + step
        
        # Check if we've reached the target
        if (target > current and new_value >= target) or (target < current and new_value <= target):
            new_value = target
            # Stop the timer
            if idx in self._hover_timers:
                self._hover_timers[idx].stop()
                del self._hover_timers[idx]
        
        self._hover_progress[idx] = new_value
        self.update()


class _MonthsGrid(QWidget):
    """Widget that renders the months grid for month picker mode."""

    month_clicked = Signal(int)

    @property
    def _accent_primary(self) -> QColor:
        return tm.accent

    @property
    def _text_primary(self) -> QColor:
        return tm.text

    def __init__(self, panel: _CalendarPanel, parent=None):
        super().__init__(parent)
        self._panel = panel
        self.setFixedHeight(180)
        self.setMouseTracking(True)
        self._hovered_month = -1
        self._hover_progress = {}  # month -> progress (0.0 to 1.0)
        self._hover_targets = {}  # month -> target value
        self._hover_timers = {}  # month -> QTimer
        self._current_hover_month = -1

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        panel = self._panel
        selected_month = None
        if panel._selected_date:
            parts = panel._selected_date.split("-")
            if len(parts) >= 2:
                selected_month = int(parts[1])

        cell_w = self.width() / 3
        cell_h = 36

        for row in range(4):
            for col in range(3):
                m = row * 3 + col + 1
                x = col * cell_w
                y = row * cell_h

                rect = QRectF(x + 2, y + 2, cell_w - 4, cell_h - 4)
                is_selected = (m == selected_month)

                # Get hover progress for this month
                hover_progress = self._hover_progress.get(m, 0.0)

                if is_selected:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(self._accent_primary)
                    painter.drawRoundedRect(rect, 4, 4)
                    painter.setPen(tm.text)
                    painter.setFont(_font(13, QFont.Bold))
                elif hover_progress > 0:
                    # Animated hover background
                    r = int(50 + (60 - 50) * hover_progress)
                    g = int(50 + (60 - 50) * hover_progress)
                    b = int(50 + (60 - 50) * hover_progress)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(r, g, b))
                    painter.drawRoundedRect(rect, 4, 4)
                    # Animated text color
                    tr = int(160 + (232 - 160) * hover_progress)
                    tg = int(160 + (232 - 160) * hover_progress)
                    tb = int(160 + (232 - 160) * hover_progress)
                    painter.setPen(QColor(tr, tg, tb))
                    painter.setFont(_font(13))
                else:
                    painter.setPen(self._text_primary)
                    painter.setFont(_font(13))

                painter.drawText(
                    QRectF(x, y, cell_w, cell_h),
                    Qt.AlignCenter,
                    f"{m}月"
                )

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            return

        col = int(event.position().x() / (self.width() / 3))
        row = int(event.position().y() / 36)
        m = row * 3 + col + 1

        if 1 <= m <= 12:
            self.month_clicked.emit(m)

    def mouseMoveEvent(self, event: QMouseEvent):
        col = int(event.position().x() / (self.width() / 3))
        row = int(event.position().y() / 36)
        m = row * 3 + col + 1

        if m != self._current_hover_month and 1 <= m <= 12:
            # Animate out old month
            if self._current_hover_month >= 1:
                self._animate_month_hover(self._current_hover_month, 0.0)
            # Animate in new month
            if 1 <= m <= 12:
                self._animate_month_hover(m, 1.0)
            self._current_hover_month = m
            self._hovered_month = m

    def leaveEvent(self, event):
        # Clear hover when mouse leaves the widget
        if self._current_hover_month >= 1:
            self._animate_month_hover(self._current_hover_month, 0.0)
            self._current_hover_month = -1
        super().leaveEvent(event)

    def _animate_month_hover(self, month: int, target: float):
        """Animate hover progress for a specific month using QTimer."""
        self._hover_targets[month] = target
        
        # Stop existing timer for this month if any
        if month in self._hover_timers and self._hover_timers[month] is not None:
            self._hover_timers[month].stop()
        
        # Create new timer for this month
        timer = QTimer(self)
        timer.setInterval(16)  # ~60fps
        timer.timeout.connect(lambda: self._update_month_hover_progress(month))
        self._hover_timers[month] = timer
        timer.start()

    def _update_month_hover_progress(self, month: int):
        """Update hover progress for a specific month."""
        target = self._hover_targets.get(month, 0.0)
        current = self._hover_progress.get(month, 0.0)
        
        # If already at target, stop
        if abs(target - current) < 0.01:
            self._hover_progress[month] = target
            if month in self._hover_timers:
                self._hover_timers[month].stop()
                del self._hover_timers[month]
            self.update()
            return
        
        # Calculate step (160ms duration / 16ms interval = 10 steps)
        step = 0.1 if target > current else -0.1
        
        new_value = current + step
        
        # Check if we've reached the target
        if (target > current and new_value >= target) or (target < current and new_value <= target):
            new_value = target
            # Stop the timer
            if month in self._hover_timers:
                self._hover_timers[month].stop()
                del self._hover_timers[month]
        
        self._hover_progress[month] = new_value
        self.update()


class _NavButton(QPushButton):
    """Navigation arrow button."""

    def __init__(self, direction: int, parent=None):
        super().__init__(parent)
        self._direction = direction  # -1 for prev, 1 for next, -12 for prev year, 12 for next year
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none; color: {tm.mid.name()};
                border-radius: 4px;
            }}
            QPushButton:hover {{ background: {tm.fill.lighter(115).name()}; }}
        """)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        is_year_nav = abs(self._direction) == 12

        if self._direction in (-1, -12):
            # Left arrow(s)
            path = QPainterPath()
            path.moveTo(16, 6)
            path.lineTo(8, 14)
            path.lineTo(16, 22)
            painter.setPen(QPen(tm.mid, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(path)
            if is_year_nav:
                path2 = QPainterPath()
                path2.moveTo(12, 6)
                path2.lineTo(4, 14)
                path2.lineTo(12, 22)
                painter.drawPath(path2)
        else:
            # Right arrow(s)
            path = QPainterPath()
            path.moveTo(8, 6)
            path.lineTo(16, 14)
            path.lineTo(8, 22)
            painter.setPen(QPen(tm.mid, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(path)
            if is_year_nav:
                path2 = QPainterPath()
                path2.moveTo(12, 6)
                path2.lineTo(20, 14)
                path2.lineTo(12, 22)
                painter.drawPath(path2)


class _TimePicker(QWidget):
    """Time picker widget with +/- buttons and editable input for datetime mode."""

    time_changed = Signal(int, int)  # hour, minute

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hour = 0
        self._minute = 0
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(4)

        # Hour spin box
        self._hour_box = _TimeSpinBox(0, 23, self)
        self._hour_box.value_changed.connect(self._on_hour_changed)
        layout.addWidget(self._hour_box)

        # Separator
        sep = QLabel(":")
        sep.setStyleSheet(f"color: {tm.mid.name()}; font-size: 14px; font-weight: 600;")
        sep.setAlignment(Qt.AlignCenter)
        sep.setFixedWidth(12)
        layout.addWidget(sep)

        # Minute spin box
        self._minute_box = _TimeSpinBox(0, 59, self)
        self._minute_box.value_changed.connect(self._on_minute_changed)
        layout.addWidget(self._minute_box)

        # 移除 addStretch，让内容居中
        layout.setAlignment(Qt.AlignCenter)

    def set_time(self, hour: int, minute: int):
        """Set the time."""
        self._hour = hour
        self._minute = minute
        self._hour_box.set_value(hour)
        self._minute_box.set_value(minute)

    def _on_hour_changed(self, hour: int):
        self._hour = hour
        self.time_changed.emit(self._hour, self._minute)

    def _on_minute_changed(self, minute: int):
        self._minute = minute
        self.time_changed.emit(self._hour, self._minute)


class _TimeSpinBox(QWidget):
    """Spin box for time input with +/- buttons and editable number."""

    value_changed = Signal(int)

    def __init__(self, min_val: int, max_val: int, parent=None):
        super().__init__(parent)
        self._min = min_val
        self._max = max_val
        self._value = min_val
        self._editing = False

        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Decrement button
        self._dec_btn = QPushButton("-")
        self._dec_btn.setFixedSize(26, 32)
        self._dec_btn.setCursor(Qt.PointingHandCursor)
        self._dec_btn.setStyleSheet(f"""
            QPushButton {{
                background: {tm.fill.name()}; color: {tm.text.name()}; border: none;
                border-radius: 4px; font-size: 16px; font-weight: 600;
            }}
            QPushButton:hover {{ background: {tm.fill.lighter(115).name()}; color: {tm.text.name()}; }}
            QPushButton:pressed {{ background: {tm.fill.name()}; }}
        """)
        self._dec_btn.clicked.connect(self._decrement)
        layout.addWidget(self._dec_btn)

        # Editable value display
        self._value_edit = _EditableNumber(self._min, self._max, self)
        self._value_edit.value_changed.connect(self._on_value_edited)
        layout.addWidget(self._value_edit)

        # Increment button
        self._inc_btn = QPushButton("+")
        self._inc_btn.setFixedSize(26, 32)
        self._inc_btn.setCursor(Qt.PointingHandCursor)
        self._inc_btn.setStyleSheet(f"""
            QPushButton {{
                background: {tm.fill.name()}; color: {tm.text.name()}; border: none;
                border-radius: 4px; font-size: 16px; font-weight: 600;
            }}
            QPushButton:hover {{ background: {tm.fill.lighter(115).name()}; color: {tm.text.name()}; }}
            QPushButton:pressed {{ background: {tm.fill.name()}; }}
        """)
        self._inc_btn.clicked.connect(self._increment)
        layout.addWidget(self._inc_btn)

    def set_value(self, value: int):
        """Set the value."""
        value = max(self._min, min(self._max, value))
        if value != self._value:
            self._value = value
            self._value_edit.set_value(value)

    def _on_value_edited(self, value: int):
        self._value = value
        self.value_changed.emit(self._value)

    def _increment(self):
        self._value = self._min if self._value >= self._max else self._value + 1
        self._value_edit.set_value(self._value)
        self.value_changed.emit(self._value)

    def _decrement(self):
        self._value = self._max if self._value <= self._min else self._value - 1
        self._value_edit.set_value(self._value)
        self.value_changed.emit(self._value)


class _EditableNumber(QWidget):
    """Editable number display - click to edit, shows formatted number."""

    value_changed = Signal(int)

    def __init__(self, min_val: int, max_val: int, parent=None):
        super().__init__(parent)
        self._min = min_val
        self._max = max_val
        self._value = min_val

        self.setFixedSize(36, 32)

        # Label for display
        self._label = QLabel(self)
        self._label.setGeometry(0, 0, 36, 32)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setCursor(Qt.PointingHandCursor)
        self._label.setStyleSheet(f"""
            QLabel {{
                background: {tm.fill.name()}; color: {tm.text.name()};
                border: 1px solid {tm.alpha_of(tm.mid, 40).name()}; border-radius: 4px;
                font-size: 15px; font-weight: 600;
            }}
            QLabel:hover {{ border: 1px solid {tm.accent.name()}; background: {tm.fill.name()}; }}
        """)
        self._update_label()

        # Line edit for editing (hidden by default)
        self._edit = QLineEdit(self)
        self._edit.setGeometry(0, 0, 36, 32)
        self._edit.setAlignment(Qt.AlignCenter)
        self._edit.setStyleSheet(f"""
            QLineEdit {{
                background: {tm.fill.name()}; color: {tm.text.name()}; border: 1px solid {tm.accent.name()};
                border-radius: 4px; font-size: 15px; font-weight: 600;
                padding: 0;
            }}
        """)
        self._edit.setVisible(False)
        self._edit.editingFinished.connect(self._on_edit_finished)
        self._edit.returnPressed.connect(self._on_edit_finished)

    def _update_label(self):
        self._label.setText(f"{self._value:02d}")

    def set_value(self, value: int):
        self._value = max(self._min, min(self._max, value))
        self._update_label()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self._edit.isVisible():
            self._start_editing()

    def _start_editing(self):
        self._edit.setText(f"{self._value:02d}")
        self._edit.setVisible(True)
        self._label.setVisible(False)
        self._edit.setFocus()
        self._edit.selectAll()

    def _on_edit_finished(self):
        text = self._edit.text()
        try:
            value = int(text)
            value = max(self._min, min(self._max, value))
            if value != self._value:
                self._value = value
                self.value_changed.emit(self._value)
        except ValueError:
            pass
        self._edit.setVisible(False)
        self._label.setVisible(True)
        self._update_label()


class _DateInput(QWidget):
    """Custom input widget for date display."""

    clicked = Signal()

    @property
    def _bg_input(self) -> QColor:
        return tm.alpha_of(tm.mid, 40)

    @property
    def _accent_primary(self) -> QColor:
        return tm.accent

    @property
    def _text_primary(self) -> QColor:
        return tm.text

    @property
    def _text_tertiary(self) -> QColor:
        return tm.alpha_of(tm.mid, 60)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._placeholder = "选择日期..."
        self._hovered = False
        self._has_focus = False
        self._size_variant = "default"
        self._disabled = False
        self._icon_type = "calendar"  # "calendar" or "clock"

        self._setup_sizes()
        self.setCursor(Qt.PointingHandCursor)

    def _setup_sizes(self):
        configs = {
            "sm": {"height": 28, "font": 12, "padding_l": 8, "padding_r": 28, "icon": 14},
            "default": {"height": 36, "font": 13, "padding_l": 12, "padding_r": 32, "icon": 16},
            "lg": {"height": 44, "font": 14, "padding_l": 14, "padding_r": 36, "icon": 18},
        }
        self._config = configs.get(self._size_variant, configs["default"])

    def set_size_variant(self, size: str):
        self._size_variant = size
        self._setup_sizes()
        self.update()
        self.setFixedHeight(self._config["height"])

    def set_icon_type(self, icon_type: str):
        self._icon_type = icon_type
        self.update()

    def set_disabled_state(self, disabled: bool):
        self._disabled = disabled
        self.update()

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value: str):
        self._text = value
        self.update()

    def set_placeholder(self, value: str):
        self._placeholder = value
        self.update()

    def _draw_icon(self, painter: QPainter):
        cfg = self._config
        h = cfg["height"]
        icon_size = cfg["icon"]
        icon_x = self.width() - icon_size - 10
        icon_y = (h - icon_size) / 2

        painter.save()
        painter.translate(icon_x, icon_y)

        pen = QPen(tm.alpha_of(tm.mid, 60), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        if self._icon_type == "calendar":
            # Calendar icon matching web SVG
            r = 2
            painter.drawRoundedRect(2, 4, icon_size - 4, icon_size - 6, r, r)
            painter.drawLine(6, 2, 6, 5)
            painter.drawLine(icon_size - 6, 2, icon_size - 6, 5)
            painter.drawLine(2, 8, icon_size - 2, 8)
        else:
            # Clock icon
            cx, cy = icon_size / 2, icon_size / 2
            r = icon_size / 2 - 2
            painter.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))
            painter.drawLine(int(cx), int(cy - r + 3), int(cx), int(cy + 2))
            painter.drawLine(int(cx), int(cy + 2), int(cx + r - 3), int(cy + 2))

        painter.restore()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        cfg = self._config
        h = cfg["height"]

        # Inset for border to avoid clipping
        inset = 1.0

        # Background
        bg = self._bg_input

        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(inset, inset, self.width() - inset * 2, h - inset * 2, 6, 6)

        # Opacity for disabled
        if self._disabled:
            painter.setOpacity(0.5)

        # Border
        if self._has_focus:
            painter.setPen(QPen(self._accent_primary, 1))
        else:
            painter.setPen(QPen(self._border_color, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(inset, inset, self.width() - inset * 2, h - inset * 2, 6, 6)

        painter.setOpacity(1.0)

        # Text
        painter.setFont(_font(cfg["font"]))
        display_text = self._text if self._text else self._placeholder
        text_color = self._text_primary if self._text else self._text_tertiary
        if self._disabled:
            text_color = tm.mid
        painter.setPen(text_color)
        painter.drawText(
            QRectF(cfg["padding_l"], 0, self.width() - cfg["padding_r"] - cfg["padding_l"] + 4, h),
            Qt.AlignVCenter | Qt.AlignLeft,
            display_text
        )

        # Icon
        self._draw_icon(painter)

    def sizeHint(self):
        cfg = self._config
        return QSize(200, cfg["height"])

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if not self._disabled:
            self.clicked.emit()
        super().mousePressEvent(event)


class StyledDatePicker(QWidget):
    """Date picker matching web component exactly.

    Features:
        - Single date selection
        - Range selection
        - Datetime mode
        - Month picker mode
        - Size variants (sm, default, lg)
        - Disabled state
    """

    date_changed = Signal(str)
    range_changed = Signal(str, str)

    def __init__(
        self,
        date: str = "",
        size: str = "default",
        enabled: bool = True,
        placeholder: str = "",
        is_range: bool = False,
        is_datetime: bool = False,
        is_month_picker: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._date = date
        self._size = size
        self._enabled = enabled
        self._is_range = is_range
        self._is_datetime = is_datetime
        self._is_month_picker = is_month_picker
        self._range_start = None
        self._range_end = None
        self._placeholder = placeholder
        self._app_filter_installed = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(0)

        self._input = _DateInput(self)
        self._input.set_size_variant(size)

        if is_datetime:
            self._input.set_icon_type("clock")
            if date:
                self._input.text = date
            else:
                self._input.set_placeholder("选择日期时间...")
        elif is_month_picker:
            if date:
                parts = date.split("-")
                if len(parts) >= 2:
                    self._input.text = f"{parts[0]}年{int(parts[1])}月"
                else:
                    self._input.text = date
            else:
                self._input.set_placeholder("选择月份...")
        else:
            if date:
                self._input.text = date
            else:
                self._input.set_placeholder(placeholder or ("选择日期范围..." if is_range else "选择日期..."))

        self._input.set_disabled_state(not enabled)
        self._input.clicked.connect(self._toggle_panel)

        # Width config - range mode needs wider input
        if is_range:
            widths = {"sm": 240, "default": 280, "lg": 320}
        else:
            widths = {"sm": 160, "default": 200, "lg": 240}
        self._input.setFixedWidth(widths.get(size, 200))

        layout.addWidget(self._input)

        # Create panel
        self._panel = _CalendarPanel(self)
        if date:
            self._panel.set_date(date)
        self._panel.set_range_mode(is_range)
        self._panel.set_datetime_mode(is_datetime)
        self._panel.set_month_picker_mode(is_month_picker)
        self._panel.date_selected.connect(self._on_date_selected)
        self._panel.range_selected.connect(self._on_range_selected)
        self._panel.closed.connect(self._on_panel_closed)
        self._panel.hide()

    def _toggle_panel(self):
        if not self._enabled:
            return
        if self._panel.isVisible():
            self._panel.close_animated()
        else:
            # Close other panels first
            self._close_other_panels()
            pos = self.mapToGlobal(QPoint(0, self.height() + 8))
            self._panel.show_animated(pos)
            self._panel.raise_()
            self._input._has_focus = True
            self._input.update()
            
            # Install app-level event filter to detect clicks outside
            if not self._app_filter_installed:
                QApplication.instance().installEventFilter(self)
                self._app_filter_installed = True
                # Also monitor parent window for move/deactivate events
                parent_window = self.window()
                if parent_window and parent_window != self:
                    parent_window.installEventFilter(self)

    def _close_other_panels(self):
        """Close all other date picker panels."""
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, _CalendarPanel) and widget != self._panel and widget.isVisible():
                widget.close_animated()

    def _on_date_selected(self, date_str: str):
        self._date = date_str
        if self._is_month_picker:
            parts = date_str.split("-")
            if len(parts) >= 2:
                self._input.text = f"{parts[0]}年{int(parts[1])}月"
            else:
                self._input.text = date_str
        else:
            self._input.text = date_str
        self.date_changed.emit(date_str)

    def _on_range_selected(self, start: str, end: str):
        self._range_start = start
        self._range_end = end
        self._input.text = f"{start} - {end}"
        self.range_changed.emit(start, end)

    def _on_panel_closed(self):
        """Handle panel closed signal."""
        self._input._has_focus = False
        self._input.update()

        # Uninstall event filter when panel is closed
        if self._app_filter_installed:
            QApplication.instance().removeEventFilter(self)
            # Also remove from top-level window
            top_window = self.window()
            if top_window and top_window != self:
                top_window.removeEventFilter(self)
            self._app_filter_installed = False

    def eventFilter(self, obj, event):
        """App-level filter: close popup when clicking outside it or window moves."""
        if self._panel.isVisible():
            # Handle clicks outside
            if event.type() in (QEvent.MouseButtonPress, QEvent.TouchBegin):
                if isinstance(event, QMouseEvent):
                    global_pos = event.globalPosition().toPoint()
                    # 点击在控件区域内：消费事件，避免 _DateInput 收到点击
                    # 触发 toggle 而关闭面板
                    if self.rect().contains(self.mapFromGlobal(global_pos)):
                        return True
                    # Check if click is inside the panel (use global geometry
                    # since panel is a separate top-level window)
                    if self._panel.geometry().contains(global_pos):
                        return False
                    # Click is outside both - close panel, but don't consume event
                    # so the click can reach other widgets (e.g. another date picker)
                    self._panel.close_animated()
                    return False

            # Handle window move - close panel when window is dragged
            if event.type() == QEvent.Move:
                if isinstance(obj, QWidget) and obj is self.window():
                    self._panel.close_animated()
                    return False

            # Handle window deactivation (focus lost to another window)
            if event.type() == QEvent.WindowDeactivate:
                if isinstance(obj, QWidget) and obj is self.window():
                    # 如果 deactivate 是因为点击面板导致的（鼠标在面板上），
                    # 不关闭面板，避免焦点切换时面板被误关
                    if self._panel.geometry().contains(QCursor.pos()):
                        return False
                    self._panel.close_animated()
                    return False

        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        self._panel.hide()
        if self._app_filter_installed:
            QApplication.instance().removeEventFilter(self)
            self._app_filter_installed = False
        super().closeEvent(event)

    def hideEvent(self, event):
        self._panel.hide()
        if self._app_filter_installed:
            QApplication.instance().removeEventFilter(self)
            self._app_filter_installed = False
        super().hideEvent(event)

    # ── Public API ───────────────────────────────────────────────

    @property
    def date(self) -> str:
        return self._date

    @date.setter
    def date(self, value: str):
        self._date = value
        if self._is_month_picker:
            parts = value.split("-")
            if len(parts) >= 2:
                self._input.text = f"{parts[0]}年{int(parts[1])}月"
            else:
                self._input.text = value
        else:
            self._input.text = value
        self._panel.set_date(value)

    @property
    def range_start(self) -> str:
        return self._range_start

    @property
    def range_end(self) -> str:
        return self._range_end

    def set_range(self, start: str, end: str):
        self._range_start = start
        self._range_end = end
        if start and end:
            self._input.text = f"{start} - {end}"
        self._panel.set_range(start, end)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value
        self._input.set_disabled_state(not value)

    def close_panel(self):
        self._panel.hide()
        self._input._has_focus = False
        self._input.update()


# ── Standalone Time Picker ────────────────────────────────────

class _TimePanel(QFrame):
    """Dropdown panel for standalone time picker.
    
    Derived from _CalendarPanel (datetime mode) - only time picker, no calendar.
    Uses identical styling, animations, and layout patterns.
    """

    time_selected = Signal(str)
    closed = Signal()

    @property
    def _bg_card(self) -> QColor:
        return tm.alpha_of(tm.surface, 90)

    @property
    def _border_color(self) -> QColor:
        return tm.alpha_of(tm.mid, 40)

    def __init__(self, parent=None):
        super().__init__(None)  # No parent to allow independent popup
        self.setObjectName("timePanel")
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.setFrameShape(QFrame.NoFrame)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedWidth(280)  # Same width as _CalendarPanel
        self._parent_ref = parent
        self._closing_internally = False

        self._setup_ui()

    def _setup_ui(self):
        """Mirror _CalendarPanel._setup_ui but only with time picker."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(0)

        # Header - same style as _CalendarPanel
        header_layout = QHBoxLayout()
        header_layout.setSpacing(0)

        # Time icon in header
        icon_widget = QLabel()
        icon_widget.setFixedSize(24, 24)
        icon_widget.setStyleSheet("background: transparent;")
        icon_widget.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(icon_widget)

        # Header label - same style as _CalendarPanel
        self._header_label = QLabel("选择时间")
        self._header_label.setStyleSheet(f"""
            color: {tm.text.name()}; font-size: 14px; font-weight: 500;
            padding: 4px 8px; border-radius: 4px;
        """)
        self._header_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(self._header_label, 1)

        # Spacer to balance layout (same width as nav buttons area)
        spacer = QWidget()
        spacer.setFixedSize(24, 24)
        header_layout.addWidget(spacer)

        main_layout.addLayout(header_layout)

        # Time picker - same as _CalendarPanel's datetime mode
        self._time_picker = _TimePicker(self)
        self._time_picker.time_changed.connect(self._on_time_changed)
        main_layout.addWidget(self._time_picker)

        # Footer - same style as _CalendarPanel
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 12, 0, 0)

        self._now_btn = QPushButton("此刻")
        self._now_btn.setCursor(Qt.PointingHandCursor)
        self._now_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {tm.accent.name()}; font-size: 12px;
                border: none; padding: 4px 8px; border-radius: 4px;
            }}
            QPushButton:hover {{ background: {tm.fill.lighter(115).name()}; }}
        """)
        self._now_btn.clicked.connect(self._select_now)
        footer_layout.addWidget(self._now_btn)
        footer_layout.addStretch()

        self._confirm_btn = QPushButton("确认")
        self._confirm_btn.setCursor(Qt.PointingHandCursor)
        self._confirm_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {tm.accent.name()}; font-size: 12px;
                border: none; padding: 4px 8px; border-radius: 4px;
            }}
            QPushButton:hover {{ background: {tm.fill.lighter(115).name()}; }}
        """)
        self._confirm_btn.clicked.connect(self._on_confirm)
        footer_layout.addWidget(self._confirm_btn)

        self._footer_widget = QWidget()
        self._footer_widget.setLayout(footer_layout)
        main_layout.addWidget(self._footer_widget)

    def _on_time_changed(self, hour: int, minute: int):
        pass  # Just track internally

    def _select_now(self):
        """Set time to current time."""
        now = datetime.now()
        self._time_picker.set_time(now.hour, now.minute)

    def _on_confirm(self):
        h = self._time_picker._hour
        m = self._time_picker._minute
        self.time_selected.emit(f"{h:02d}:{m:02d}")
        self.close_animated()

    def set_time(self, hour: int, minute: int):
        self._time_picker.set_time(hour, minute)

    def showEvent(self, event):
        super().showEvent(event)
        self._closing_internally = False

    def paintEvent(self, event: QPaintEvent):
        """Draw rounded background + border, matching CalendarPanel style exactly."""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        r = 8

        # Background
        p.setPen(Qt.NoPen)
        p.setBrush(self._bg_card)
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        # Border
        p.setPen(QPen(self._border_color, 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)
        p.end()

    def show_animated(self, anchor: QPoint):
        """Fade in + slide down from anchor point, matching CalendarPanel."""
        start_h = 10
        target_w = self.width()
        target_h = self.sizeHint().height()

        x = anchor.x()
        self.setGeometry(x, anchor.y(), target_w, start_h)
        self.setWindowOpacity(0.0)
        super().show()

        # Opacity animation
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(200)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)

        # Height slide animation
        self._slide = QPropertyAnimation(self, b"geometry")
        self._slide.setDuration(220)
        self._slide.setStartValue(self.geometry())
        self._slide.setEndValue(
            QRectF(x, anchor.y(), target_w, target_h).toRect()
        )
        self._slide.setEasingCurve(QEasingCurve.OutCubic)

        self._fade.start()
        self._slide.start()

    def close_animated(self):
        """Slide up + fade out for smooth dismiss, matching CalendarPanel."""
        self._closing_internally = True
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(150)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.InCubic)

        self._slide = QPropertyAnimation(self, b"geometry")
        self._slide.setDuration(150)
        self._slide.setStartValue(self.geometry())
        end = QRectF(self.geometry())
        end.setHeight(10)
        self._slide.setEndValue(end.toRect())
        self._slide.setEasingCurve(QEasingCurve.InCubic)

        self._slide.finished.connect(self._on_close_animation_finished)
        self._fade.start()
        self._slide.start()

    def _on_close_animation_finished(self):
        self.hide()
        self.closed.emit()

    def hideEvent(self, event):
        super().hideEvent(event)
        if not self._closing_internally:
            self.closed.emit()


class StyledTimePicker(QWidget):
    """Standalone time picker with dropdown panel.
    
    Derived from the datetime mode of StyledDatePicker, reusing _DateInput
    with clock icon for consistent styling.
    """

    time_changed = Signal(str)

    def __init__(
        self,
        time: str = "",
        size: str = "default",
        enabled: bool = True,
        placeholder: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._time = time
        self._size = size
        self._enabled = enabled
        self._placeholder = placeholder
        self._app_filter_installed = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(0)

        # Reuse _DateInput with clock icon for consistent styling
        self._input = _DateInput(self)
        self._input.set_size_variant(size)
        self._input.set_icon_type("clock")  # Use clock icon like datetime mode

        if time:
            self._input.text = time
        else:
            self._input.set_placeholder(placeholder or "选择时间...")

        self._input.set_disabled_state(not enabled)
        self._input.clicked.connect(self._toggle_panel)

        # Width config - same as date picker
        widths = {"sm": 160, "default": 200, "lg": 240}
        self._input.setFixedWidth(widths.get(size, 200))

        layout.addWidget(self._input)

        # Create panel
        self._panel = _TimePanel(self)
        if time:
            parts = time.split(":")
            if len(parts) >= 2:
                self._panel.set_time(int(parts[0]), int(parts[1]))
        self._panel.time_selected.connect(self._on_time_selected)
        self._panel.closed.connect(self._on_panel_closed)
        self._panel.hide()

    def _toggle_panel(self):
        if not self._enabled:
            return
        if self._panel.isVisible():
            self._panel.close_animated()
        else:
            pos = self.mapToGlobal(QPoint(0, self.height() + 8))
            self._panel.show_animated(pos)
            self._panel.raise_()
            self._input._has_focus = True
            self._input.update()

            if not self._app_filter_installed:
                QApplication.instance().installEventFilter(self)
                self._app_filter_installed = True
                # Also install filter on top-level window for move/deactivate events
                top_window = self.window()
                if top_window and top_window != self:
                    top_window.installEventFilter(self)

    def _on_time_selected(self, time_str: str):
        self._time = time_str
        self._input.text = time_str
        self.time_changed.emit(time_str)

    def _on_panel_closed(self):
        self._input._has_focus = False
        self._input.update()

        if self._app_filter_installed:
            QApplication.instance().removeEventFilter(self)
            self._app_filter_installed = False

    def eventFilter(self, obj, event):
        """App-level filter: close popup when clicking outside it or window moves."""
        if self._panel.isVisible():
            # Handle clicks outside
            if event.type() in (QEvent.MouseButtonPress, QEvent.TouchBegin):
                if isinstance(event, QMouseEvent):
                    global_pos = event.globalPosition().toPoint()
                    # 点击在控件区域内：消费事件，避免 _DateInput 收到点击
                    # 触发 toggle 而关闭面板
                    if self.rect().contains(self.mapFromGlobal(global_pos)):
                        return True
                    # Check if click is inside the panel (use global geometry
                    # since panel is a separate top-level window)
                    if self._panel.geometry().contains(global_pos):
                        return False
                    # Click is outside both - close panel, but don't consume event
                    # so the click can reach other widgets (e.g. another date picker)
                    self._panel.close_animated()
                    return False

            # Handle window move - close panel when window is dragged
            if event.type() == QEvent.Move:
                if isinstance(obj, QWidget) and obj is self.window():
                    self._panel.close_animated()
                    return False

            # Handle window deactivation (focus lost to another window)
            if event.type() == QEvent.WindowDeactivate:
                if isinstance(obj, QWidget) and obj is self.window():
                    # 如果 deactivate 是因为点击面板导致的（鼠标在面板上），
                    # 不关闭面板，避免焦点切换时面板被误关
                    if self._panel.geometry().contains(QCursor.pos()):
                        return False
                    self._panel.close_animated()
                    return False

        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        self._panel.hide()
        if self._app_filter_installed:
            QApplication.instance().removeEventFilter(self)
            self._app_filter_installed = False
        super().closeEvent(event)

    def hideEvent(self, event):
        self._panel.hide()
        if self._app_filter_installed:
            QApplication.instance().removeEventFilter(self)
            self._app_filter_installed = False
        super().hideEvent(event)

    # ── Public API ───────────────────────────────────────────────

    @property
    def time(self) -> str:
        return self._time

    @time.setter
    def time(self, value: str):
        self._time = value
        self._input.text = value
        parts = value.split(":")
        if len(parts) >= 2:
            self._panel.set_time(int(parts[0]), int(parts[1]))

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value
        self._input.set_disabled_state(not value)
