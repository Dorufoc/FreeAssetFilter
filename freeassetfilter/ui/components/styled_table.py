# allow: SIZE_OK — ~65 lines of data tables (STATUS_COLORS, SIZE_CONFIG, _TABLE_QSS) plus
# extensive docstrings / class docs inflate the count past 250.  The two classes
# (StatusBadgeDelegate, StyledTable) each fit well under 250 LOC and are tightly coupled.

"""Styled Table component — QTableWidget with status badges, checkbox, empty state, size variants.

Matches the web table design exactly:
  https://github.com/D-fronted/components/table/table.css

Public API
----------
StyledTable(columns, data, size, parent)
    .set_columns(columns)   — set column definitions
    .set_data(data)         — populate rows from list[dict]
    .size_variant           — property: sm | default | lg
    .row_selected           — Signal(int): row changed
    .cell_clicked           — Signal(int, int): cell activated

Column config::
    {"label": str, "key": str, "width": int | None, "type": str | None}

    ``type`` = "status"   → StatusBadgeDelegate (colored dot + pill)
              "checkbox"  → checkable items with Qt.ItemIsUserCheckable

Status values (case-insensitive): active, inactive, error, warning.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QTableWidget,
    QTableWidgetItem,
    QStyledItemDelegate,
    QStyle,
    QLabel,
    QAbstractItemView,
    QHeaderView,
    QStyleOptionViewItem,
)
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import (
    QPainter,
    QColor,
    QFont,
    QFontMetrics,
)

from theme import tm

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# padding_v, padding_h, header_font_size, cell_font_size
SIZE_CONFIG: dict[str, dict] = {
    "sm": {
        "cell_pad_v": 8,
        "cell_pad_h": 12,
        "header_font": 11,
        "cell_font": 11,
        "badge_font": 10,
        "badge_pad_h": 6,
        "badge_pad_v": 2,
        "row_height": 32,
    },
    "default": {
        "cell_pad_v": 10,
        "cell_pad_h": 16,
        "header_font": 12,
        "cell_font": 12,
        "badge_font": 11,
        "badge_pad_h": 8,
        "badge_pad_v": 3,
        "row_height": 36,
    },
    "lg": {
        "cell_pad_v": 14,
        "cell_pad_h": 20,
        "header_font": 13,
        "cell_font": 13,
        "badge_font": 12,
        "badge_pad_h": 10,
        "badge_pad_v": 4,
        "row_height": 48,
    },
}

# Base QSS template — extended per size variant
_TABLE_QSS = """
StyledTable {{
    background-color: {bg};
    border: 1px solid {border};
    border-radius: 6px;
    gridline-color: {gridline};
    outline: none;
}}
StyledTable::item {{
    padding: {pad_v}px {pad_h}px;
    color: {text_primary};
}}
StyledTable::item:hover {{
    background: {hover_bg};
}}
StyledTable::item:selected {{
    background: {selected_bg};
    color: {selected_text};
}}
StyledTable QHeaderView::section {{
    background-color: {header_bg};
    color: {header_text};
    padding: {pad_v}px {pad_h}px;
    border: none;
    border-bottom: 1px solid {border};
    border-right: 1px solid {gridline};
    font-weight: 600;
    text-transform: uppercase;
}}
StyledTable QHeaderView::section:hover {{
    background-color: {header_hover_bg};
    color: {header_hover_text};
}}
"""


# ---------------------------------------------------------------------------
# StatusBadgeDelegate
# ---------------------------------------------------------------------------

class StatusBadgeDelegate(QStyledItemDelegate):
    """Renders a colored dot + pill badge for known status values.

    Cell text is matched (case-insensitive) against the keys of
    ``STATUS_COLORS``.  When matched, the delegate draws:

    * Selection- or hover-background matching the table QSS.
    * A soft pill background at 10 % opacity of the status colour.
    * A 6 px filled dot in the status colour.
    * The status text in the status colour.

    Non-status cells fall through to the default delegate.
    """

    @staticmethod
    def _get_get_status_colors() -> dict[str, QColor]:
        return {
            "active": tm.accent,
            "inactive": tm.mid,
            "error": tm.danger,
            "warning": tm.warning,
        }

    def __init__(self, size: str = "default", parent=None):
        super().__init__(parent)
        self._size = size if size in SIZE_CONFIG else "default"

    def set_size(self, size: str) -> None:
        self._size = size if size in SIZE_CONFIG else "default"

    # -- paint -----------------------------------------------------------

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index,
    ) -> None:
        text = (index.data(Qt.DisplayRole) or "")
        status_key = text.lower()

        if status_key in self._get_status_colors():
            self._paint_badge(painter, option, text, status_key)
        else:
            super().paint(painter, option, index)

    def _paint_badge(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        text: str,
        status_key: str,
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect = option.rect
        color = self._get_status_colors()[status_key]
        cfg = SIZE_CONFIG[self._size]

        # ── Selection / hover background ────────────────────────────
        is_selected = bool(option.state & QStyle.State_Selected)
        is_hovered = bool(option.state & QStyle.State_MouseOver)

        if is_selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(tm.alpha_of(tm.accent, 8))
            painter.drawRect(rect)
        elif is_hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(tm.alpha_of(tm.surface, 90))
            painter.drawRect(rect)

        # ── Badge metrics ───────────────────────────────────────────
        cfg_badge_font = QFont("Microsoft YaHei UI", cfg["badge_font"])
        fm = QFontMetrics(cfg_badge_font)

        text_w = fm.horizontalAdvance(text)
        dot_size = 6
        gap = 6
        bp_h = cfg["badge_pad_h"]
        bp_v = cfg["badge_pad_v"]

        # Pill width & height
        badge_w = text_w + bp_h * 2 + dot_size + gap
        badge_h = fm.height() + bp_v * 2

        # Center the badge vertically within the cell
        badge_y = rect.y() + (rect.height() - badge_h) // 2
        badge_x = rect.x() + bp_h

        # Dot centre
        dot_cx = badge_x + bp_h + dot_size / 2
        dot_cy = badge_y + badge_h / 2

        # Text rect
        text_x = dot_cx + dot_size / 2 + gap

        # ── Pill background (10 % opacity) ──────────────────────────
        bg_color = QColor(color)
        bg_color.setAlpha(25)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(
            QRectF(badge_x, badge_y, badge_w, badge_h),
            badge_h / 2,
            badge_h / 2,
        )

        # ── Dot ─────────────────────────────────────────────────────
        painter.setBrush(color)
        painter.drawEllipse(
            QPointF(dot_cx, dot_cy),
            dot_size / 2,
            dot_size / 2,
        )

        # ── Text ────────────────────────────────────────────────────
        text_color = QColor(color)
        if is_selected:
            text_color = tm.text
        painter.setPen(text_color)
        painter.setFont(cfg_badge_font)
        painter.drawText(
            QRectF(text_x, rect.y(), rect.right() - text_x, rect.height()),
            Qt.AlignLeft | Qt.AlignVCenter,
            text,
        )

        painter.restore()


# ---------------------------------------------------------------------------
# StyledTable
# ---------------------------------------------------------------------------

class StyledTable(QTableWidget):
    """A styled table component matching the web table design.

    Parameters
    ----------
    columns : list[dict] | None
        Each entry: ``{"label": ..., "key": ..., "width": ...,
        "type": "status"|"checkbox"}``.
    data : list[dict] | None
        Rows keyed by column key.
    size : str
        One of ``"sm"``, ``"default"``, ``"lg"``.
    parent : Optional[QWidget]
    """

    #: Emitted when the selected row changes.  Carries the row index.
    row_selected = Signal(int)

    #: Emitted on any cell click.  Carries (row, column).
    cell_clicked = Signal(int, int)

    def __init__(
        self,
        columns: Optional[list[dict]] = None,
        data: Optional[list[dict]] = None,
        size: str = "default",
        parent=None,
    ):
        super().__init__(parent)

        self._columns: list[dict] = columns or []
        self._data: list[dict] = data or []
        self._size: str = size if size in SIZE_CONFIG else "default"
        self._delegate = StatusBadgeDelegate(self._size, self)

        self._setup_table()
        self._build_empty_state()
        self._apply_size()

        if self._columns:
            self.set_columns(self._columns)
        if self._data:
            self.set_data(self._data)

    # ── Setup helpers ──────────────────────────────────────────────────

    def _setup_table(self) -> None:
        """Configure selection, sorting, headers, and signal wiring."""
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(False)
        self.setShowGrid(True)
        self.setCornerButtonEnabled(False)

        hheader = self.horizontalHeader()
        hheader.setStretchLastSection(True)
        hheader.setHighlightSections(False)

        self.verticalHeader().setVisible(False)

        # Wire signals
        self.cellClicked.connect(self._on_cell_clicked)
        self.itemSelectionChanged.connect(self._on_selection_changed)

    def _build_empty_state(self) -> None:
        """Create the overlay label shown when the table has no rows."""
        self._empty_label = QLabel("暂无数据", self)
        self._empty_label.setAlignment(Qt.AlignCenter)
        empty_color = tm.alpha_of(tm.mid, 60).name()
        self._empty_label.setStyleSheet(
            f"QLabel {{"
            f"  color: {empty_color};"
            f"  font-size: 13px;"
            f"  background: transparent;"
            f"  border: none;"
            f"  padding: 40px 16px;"
            f"}}"
        )
        self._empty_label.setVisible(False)

    def _apply_size(self) -> None:
        """Update row heights, fonts, and QSS for the current size variant."""
        cfg = SIZE_CONFIG[self._size]

        # Row height
        self.verticalHeader().setDefaultSectionSize(cfg["row_height"])

        # Cell font
        cell_font = QFont("Microsoft YaHei UI", cfg["cell_font"])
        self.setFont(cell_font)

        # Header font
        header_font = QFont(
            "Microsoft YaHei UI",
            cfg["header_font"],
            QFont.Weight.DemiBold,
        )
        self.horizontalHeader().setFont(header_font)

        # Update delegate
        self._delegate.set_size(self._size)

        # Rebuild QSS with current padding
        self._update_qss()

    def _update_qss(self) -> None:
        cfg = SIZE_CONFIG[self._size]
        accent = tm.accent
        qss = _TABLE_QSS.format(
            pad_v=cfg["cell_pad_v"],
            pad_h=cfg["cell_pad_h"],
            bg=tm.surface.name(),
            border=tm.alpha_of(tm.mid, 40).name(),
            gridline=tm.alpha_of(tm.mid, 30).name(),
            text_primary=tm.text.name(),
            hover_bg=tm.alpha_of(tm.surface, 90).name(),
            selected_bg=f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.08)",
            selected_text=tm.text.name(),
            header_bg=tm.alpha_of(tm.surface, 90).name(),
            header_text=tm.mid.name(),
            header_hover_bg=tm.surface.name(),
            header_hover_text=tm.text.name(),
        )
        self.setStyleSheet(qss)

    # ── Public API ─────────────────────────────────────────────────────

    def set_columns(self, columns: list[dict]) -> None:
        """Set table columns.

        Each column dict::

            {"label": str, "key": str, "width": int | None, "type": str | None}

        * ``type="status"`` applies :class:`StatusBadgeDelegate`.
        * ``type="checkbox"`` makes items checkable.
        """
        self._columns = columns
        self.setColumnCount(len(columns))

        hheader = self.horizontalHeader()
        for i, col in enumerate(columns):
            item = QTableWidgetItem(col["label"])
            w = col.get("width")
            if w is not None:
                self.setColumnWidth(i, w)
            else:
                hheader.setSectionResizeMode(i, QHeaderView.Interactive)
            self.setHorizontalHeaderItem(i, item)

            # Per-column delegate
            if col.get("type") == "status":
                self.setItemDelegateForColumn(i, self._delegate)

    def set_data(self, data: list[dict]) -> None:
        """Populate table rows from a list of dicts keyed by column key."""
        self._data = data
        self.setRowCount(len(data))

        if not data:
            self._show_empty_state()
            return

        self._hide_empty_state()

        for row_idx, row_data in enumerate(data):
            for col_idx, col in enumerate(self._columns):
                key = col["key"]
                raw = row_data.get(key, "")
                value = str(raw) if raw is not None else ""

                item = QTableWidgetItem(value)

                col_type = col.get("type")
                if col_type == "checkbox":
                    # Checkable item that toggles
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    if isinstance(raw, bool):
                        item.setCheckState(
                            Qt.Checked if raw else Qt.Unchecked
                        )
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)

                self.setItem(row_idx, col_idx, item)

    # ── Properties ────────────────────────────────────────────────────

    @property
    def table_data(self) -> list[dict]:
        """Return the original data dicts passed to ``set_data``."""
        return self._data

    @property
    def size_variant(self) -> str:
        return self._size

    @size_variant.setter
    def size_variant(self, value: str) -> None:
        if value in SIZE_CONFIG:
            self._size = value
            self._apply_size()

    # ── Empty state ───────────────────────────────────────────────────

    def _show_empty_state(self) -> None:
        self._empty_label.setVisible(True)
        self._empty_label.resize(self.viewport().size())
        self._empty_label.move(0, 0)

    def _hide_empty_state(self) -> None:
        self._empty_label.setVisible(False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._empty_label.isVisible():
            self._empty_label.resize(self.viewport().size())

    # ── Signal forwarding ─────────────────────────────────────────────

    def _on_cell_clicked(self, row: int, col: int) -> None:
        self.cell_clicked.emit(row, col)

    def _on_selection_changed(self) -> None:
        rows = self.selectionModel().selectedRows()
        if rows:
            self.row_selected.emit(rows[0].row())
