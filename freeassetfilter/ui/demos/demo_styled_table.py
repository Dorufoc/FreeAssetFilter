"""StyledTable Demo — status badges, checkbox, size variants, empty state, selection."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QScrollArea,
    QPushButton,
    QSizePolicy,
    QGridLayout,
)
from PySide6.QtCore import Qt

from theme import tm
from components.styled_table import StyledTable


# ── Demo data ──────────────────────────────────────────────────────────────

COLUMNS = [
    {"label": "姓名", "key": "name", "width": 140},
    {"label": "状态", "key": "status", "width": 120, "type": "status"},
    {"label": "角色", "key": "role", "width": 140},
    {"label": "操作", "key": "actions", "width": 180},
]

ROWS = [
    {"name": "张三", "status": "active", "role": "管理员", "actions": "编辑 删除"},
    {"name": "李四", "status": "inactive", "role": "编辑者", "actions": "编辑 删除"},
    {"name": "王五", "status": "error", "role": "访客", "actions": "编辑 删除"},
    {"name": "赵六", "status": "warning", "role": "审核员", "actions": "编辑 删除"},
    {"name": "钱七", "status": "active", "role": "管理员", "actions": "编辑 删除"},
]

CHECKBOX_COLUMNS = [
    {"label": "", "key": "checked", "width": 40, "type": "checkbox"},
    {"label": "文件名", "key": "file", "width": 180},
    {"label": "大小", "key": "size", "width": 100},
    {"label": "状态", "key": "status", "width": 120, "type": "status"},
]

CHECKBOX_ROWS = [
    {"checked": True, "file": "report.pdf", "size": "2.4 MB", "status": "active"},
    {"checked": False, "file": "photo.png", "size": "5.1 MB", "status": "inactive"},
    {"checked": True, "file": "notes.txt", "size": "12 KB", "status": "active"},
    {"checked": False, "file": "data.json", "size": "340 KB", "status": "warning"},
    {"checked": True, "file": "backup.zip", "size": "45 MB", "status": "error"},
]


# ── Demo window ────────────────────────────────────────────────────────────

class StyledTableDemo(QWidget):
    """Demonstrates all StyledTable features."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledTable Demo")
        self.resize(880, 780)

        self._setup_ui()
        self._apply_theme()

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {tm.surface.name()};
                color: {tm.text.name()};
                font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
            }}
        """)

    # ── UI helpers ───────────────────────────────────────────────────

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"font-size: 15px; font-weight: 600;"
            f" color: {tm.text.name()}; margin-top: 8px; margin-bottom: 4px;"
        )
        return label

    def _section_desc(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; margin-bottom: 8px;"
        )
        return label

    def _separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(
            f"background-color: {tm.alpha_of(tm.mid, 30).name()}; max-height: 1px; border: none;"
        )
        return line

    def _status_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"font-size: 12px; color: {tm.mid.name()}; margin: 4px 0 2px;"
        )
        return label

    # ── Setup UI ─────────────────────────────────────────────────────

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("border: none; background: transparent;")

        content = QWidget()
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        # ── Section 1: Default table ─────────────────────────────────
        layout.addWidget(self._section_label("1. Default Table"))
        layout.addWidget(
            self._section_desc(
                "4 columns (name / status / role / actions), 5 rows,"
                " status badges, row selection."
            )
        )

        self._table_default = StyledTable(COLUMNS, ROWS, size="default")
        layout.addWidget(self._table_default)

        # Selection feedback
        self._sel_label = QLabel("Selected row: none")
        self._sel_label.setStyleSheet(
            f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; margin-bottom: 4px;"
        )
        layout.addWidget(self._sel_label)

        self._table_default.row_selected.connect(self._on_row_selected)
        self._table_default.cell_clicked.connect(self._on_cell_clicked)

        layout.addWidget(self._separator())

        # ── Section 2: Size variants ─────────────────────────────────
        layout.addWidget(self._section_label("2. Size Variants"))
        layout.addWidget(
            self._section_desc("Small / default / large — same data, different padding & font.")
        )

        sizes_grid = QGridLayout()
        sizes_grid.setSpacing(12)

        size_buttons = []
        for col, (sz, label) in enumerate([("sm", "Small"), ("default", "Default"), ("lg", "Large")]):
            tbl = StyledTable(COLUMNS, ROWS, size=sz)
            sizes_grid.addWidget(tbl, 0, col)
            status_lbl = self._status_label(label)
            sizes_grid.addWidget(status_lbl, 1, col, alignment=Qt.AlignCenter)

        layout.addLayout(sizes_grid)
        layout.addWidget(self._separator())

        # ── Section 3: Checkbox column ───────────────────────────────
        layout.addWidget(self._section_label("3. Checkbox Column"))
        layout.addWidget(
            self._section_desc(
                "First column rendered as native checkboxes"
                " (Qt.ItemIsUserCheckable)."
            )
        )

        self._table_check = StyledTable(CHECKBOX_COLUMNS, CHECKBOX_ROWS, size="default")
        layout.addWidget(self._table_check)

        # Checkstate feedback button
        btn_check = QPushButton("Log checked rows")
        btn_check.setStyleSheet(self._btn_style())
        btn_check.clicked.connect(self._on_log_checked)
        layout.addWidget(btn_check)

        layout.addWidget(self._separator())

        # ── Section 4: Empty state ───────────────────────────────────
        layout.addWidget(self._section_label("4. Empty State"))
        layout.addWidget(
            self._section_desc("Table with no data — shows '暂无数据' centred overlay.")
        )

        self._table_empty = StyledTable(COLUMNS, [], size="default")
        self._table_empty.setMaximumHeight(120)
        layout.addWidget(self._table_empty)

        # Toggle empty / populated
        btn_toggle = QPushButton("Toggle data")
        btn_toggle.setStyleSheet(self._btn_style())
        btn_toggle.clicked.connect(self._on_toggle_empty)
        layout.addWidget(btn_toggle)

        layout.addWidget(self._separator())

        # ── Section 5: Dynamic size change ───────────────────────────
        layout.addWidget(self._section_label("5. Dynamic Size Change"))
        layout.addWidget(
            self._section_desc("Use buttons to switch size variant at runtime.")
        )

        self._table_dynamic = StyledTable(COLUMNS, ROWS, size="default")
        layout.addWidget(self._table_dynamic)

        size_row = QHBoxLayout()
        size_row.setSpacing(8)
        for sz in ("sm", "default", "lg"):
            btn = QPushButton(sz)
            btn.setStyleSheet(self._btn_style())
            btn.clicked.connect(lambda checked, s=sz: self._table_dynamic.size_variant(s))
            size_row.addWidget(btn)
        size_row.addStretch()
        layout.addLayout(size_row)

        layout.addStretch()

        # ── Outer scroll ─────────────────────────────────────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ── Event handlers ───────────────────────────────────────────────

    def _on_row_selected(self, row: int) -> None:
        data = ROWS[row]
        self._sel_label.setText(
            f"Selected: row {row} — {data['name']} ({data['role']})"
        )

    def _on_cell_clicked(self, row: int, col: int) -> None:
        print(f"[StyledTable Demo] cell_clicked(row={row}, col={col})")

    def _on_log_checked(self) -> None:
        checked = []
        for r in range(self._table_check.rowCount()):
            item = self._table_check.item(r, 0)
            if item and item.checkState() == Qt.Checked:
                file_item = self._table_check.item(r, 1)
                name = file_item.text() if file_item else f"row {r}"
                checked.append(name)
        print(f"Checked rows: {checked}")

    def _on_toggle_empty(self) -> None:
        if self._table_empty.rowCount() == 0:
            self._table_empty.set_data(ROWS)
            self._table_empty.setMaximumHeight(200)
        else:
            self._table_empty.set_data([])
            self._table_empty.setMaximumHeight(120)

    def _btn_style(self) -> str:
        return f"""QPushButton {{
  background-color: {tm.surface.name()};
  color: {tm.text.name()};
  border: 1px solid {tm.mid.name()};
  border-radius: 6px;
  padding: 8px 18px;
  font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
}}
QPushButton:hover {{
  background-color: {tm.alpha_of(tm.mid, 40).name()};
  border-color: {tm.alpha_of(tm.mid, 40).name()};
}}
QPushButton:pressed {{
  background-color: {tm.surface.name()};
}}
"""


# ── Entry point ────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    demo = StyledTableDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
