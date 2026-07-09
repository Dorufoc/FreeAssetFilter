"""StyledTag Demo - standalone demo showcasing all tag features."""

import sys
import os

# Path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from theme import tm

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QScrollArea,
    QSizePolicy,
)
from PySide6.QtCore import Qt

from components.styled_tag import StyledTag


class StyledTagDemo(QWidget):
    """Main demo window for StyledTag."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledTag Demo")
        self.resize(700, 580)

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

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"""
            font-size: 15px;
            font-weight: 600;
            color: {tm.text.name()};
            margin-top: 8px;
            margin-bottom: 4px;
        """)
        return label

    def _section_desc(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; margin-bottom: 8px;")
        return label

    def _separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background-color: {tm.alpha_of(tm.mid, 30).name()}; max-height: 1px; border: none;")
        return line

    def _row_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; min-width: 60px;")
        label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        return label

    def _tag_row(self, tags: list) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for tag in tags:
            layout.addWidget(tag)
        layout.addStretch()
        return row

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("border: none; background: transparent;")

        content = QWidget()
        scroll.setWidget(content)

        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(32, 24, 32, 24)
        main_layout.setSpacing(16)

        # Section 1: Default
        main_layout.addWidget(self._section_label("1. Default Tags"))
        main_layout.addWidget(self._section_desc("Basic tag in default color"))

        main_layout.addWidget(self._tag_row([
            StyledTag(text="\u9ed8\u8ba4\u6807\u7b7e"),
        ]))
        main_layout.addWidget(self._separator())

        # Section 2: Color Variants
        main_layout.addWidget(self._section_label("2. Color Variants"))
        main_layout.addWidget(self._section_desc("6 color themes for different semantic meanings"))

        main_layout.addWidget(self._tag_row([
            StyledTag(text="Default", variant="default"),
            StyledTag(text="Primary", variant="primary"),
            StyledTag(text="Success", variant="success"),
            StyledTag(text="Warning", variant="warning"),
            StyledTag(text="Danger", variant="danger"),
            StyledTag(text="Info", variant="info"),
        ]))
        main_layout.addWidget(self._separator())

        # Section 3: Closable Tags
        main_layout.addWidget(self._section_label("3. Closable Tags"))
        main_layout.addWidget(self._section_desc("Tags with close button, hover to see effect"))

        main_layout.addWidget(self._tag_row([
            StyledTag(text="\u53ef\u5173\u95ed\u6807\u7b7e", closable=True),
            StyledTag(text="Primary Closable", variant="primary", closable=True),
            StyledTag(text="Warning Closable", variant="warning", closable=True),
        ]))
        main_layout.addWidget(self._separator())

        # Section 4: Size Variants
        main_layout.addWidget(self._section_label("4. Size Variants"))
        main_layout.addWidget(self._section_desc("Small, default, and large tag sizes"))

        main_layout.addWidget(self._tag_row([
            StyledTag(text="Small", size="sm"),
            StyledTag(text="Default", size="default"),
            StyledTag(text="Large", size="lg"),
        ]))

        main_layout.addWidget(self._tag_row([
            StyledTag(text="Small Primary", variant="primary", size="sm"),
            StyledTag(text="Default Primary", variant="primary", size="default"),
            StyledTag(text="Large Primary", variant="primary", size="lg"),
        ]))
        main_layout.addWidget(self._separator())

        # Section 5: Pill Style
        main_layout.addWidget(self._section_label("5. Pill Style"))
        main_layout.addWidget(self._section_desc("Fully rounded corner tags"))

        main_layout.addWidget(self._tag_row([
            StyledTag(text="Pill Tag", pill=True),
            StyledTag(text="Pill Primary", variant="primary", pill=True),
            StyledTag(text="Pill Closable", variant="warning", pill=True, closable=True),
        ]))
        main_layout.addWidget(self._separator())

        # Section 6: Tag Group Example
        main_layout.addWidget(self._section_label("6. Tag Group"))
        main_layout.addWidget(self._section_desc("Tags used as category labels"))

        group_card = QWidget()
        group_card.setStyleSheet(f"background-color: {tm.surface.name()}; border-radius: 8px;")
        group_layout = QVBoxLayout(group_card)
        group_layout.setContentsMargins(16, 12, 16, 12)
        group_layout.setSpacing(8)

        group_row = QWidget()
        gr_layout = QHBoxLayout(group_row)
        gr_layout.setContentsMargins(0, 0, 0, 0)
        gr_layout.setSpacing(8)
        gr_layout.addWidget(StyledTag(text="\u8bbe\u8ba1", variant="primary"))
        gr_layout.addWidget(StyledTag(text="\u524d\u7aef", variant="info"))
        gr_layout.addWidget(StyledTag(text="Beta", variant="warning"))
        gr_layout.addWidget(StyledTag(text="\u5df2\u5e9f\u5f03", variant="danger"))
        gr_layout.addWidget(StyledTag(text="\u901a\u7528"))
        gr_layout.addStretch()
        group_layout.addWidget(group_row)

        main_layout.addWidget(group_card)
        main_layout.addWidget(self._separator())

        # Section 7: Plugin Status Example
        main_layout.addWidget(self._section_label("7. Plugin Status Example"))
        main_layout.addWidget(self._section_desc("Tags used to display plugin states"))

        plugin_card = QWidget()
        plugin_card.setStyleSheet(f"background-color: {tm.surface.name()}; border-radius: 8px;")
        plugin_layout = QVBoxLayout(plugin_card)
        plugin_layout.setContentsMargins(16, 12, 16, 12)
        plugin_layout.setSpacing(12)

        # Plugin 1
        p1 = QWidget()
        p1_layout = QHBoxLayout(p1)
        p1_layout.setContentsMargins(0, 0, 0, 0)
        p1_layout.setSpacing(8)
        p1_info = QVBoxLayout()
        p1_info.setContentsMargins(0, 0, 0, 0)
        p1_info.setSpacing(2)
        p1_title = QLabel("\u4ee3\u7801\u9ad8\u4eae\u63d2\u4ef6")
        p1_title.setStyleSheet(f"font-size: 13px; color: {tm.text.name()}; font-weight: 500;")
        p1_info.addWidget(p1_title)
        p1_desc = QLabel("\u4e3a\u4ee3\u7801\u5757\u63d0\u4f9b\u8bed\u6cd5\u9ad8\u4eae\u652f\u6301")
        p1_desc.setStyleSheet(f"font-size: 11px; color: {tm.alpha_of(tm.mid, 60).name()};")
        p1_info.addWidget(p1_desc)
        p1_layout.addLayout(p1_info)
        p1_layout.addStretch()
        p1_tags = QHBoxLayout()
        p1_tags.setSpacing(6)
        p1_tags.addWidget(StyledTag(text="\u5df2\u542f\u7528", variant="primary", size="sm"))
        p1_tags.addWidget(StyledTag(text="v2.1.0", size="sm"))
        p1_layout.addLayout(p1_tags)
        plugin_layout.addWidget(p1)

        # Plugin 2
        p2 = QWidget()
        p2_layout = QHBoxLayout(p2)
        p2_layout.setContentsMargins(0, 0, 0, 0)
        p2_layout.setSpacing(8)
        p2_info = QVBoxLayout()
        p2_info.setContentsMargins(0, 0, 0, 0)
        p2_info.setSpacing(2)
        p2_title = QLabel("AI \u52a9\u624b\u63d2\u4ef6")
        p2_title.setStyleSheet(f"font-size: 13px; color: {tm.text.name()}; font-weight: 500;")
        p2_info.addWidget(p2_title)
        p2_desc = QLabel("\u96c6\u6210 AI \u5bf9\u8bdd\u529f\u80fd")
        p2_desc.setStyleSheet(f"font-size: 11px; color: {tm.alpha_of(tm.mid, 60).name()};")
        p2_info.addWidget(p2_desc)
        p2_layout.addLayout(p2_info)
        p2_layout.addStretch()
        p2_tags = QHBoxLayout()
        p2_tags.setSpacing(6)
        p2_tags.addWidget(StyledTag(text="\u5df2\u542f\u7528", variant="primary", size="sm"))
        p2_tags.addWidget(StyledTag(text="Beta", variant="warning", size="sm"))
        p2_tags.addWidget(StyledTag(text="v0.9.3", size="sm"))
        p2_layout.addLayout(p2_tags)
        plugin_layout.addWidget(p2)

        # Plugin 3
        p3 = QWidget()
        p3_layout = QHBoxLayout(p3)
        p3_layout.setContentsMargins(0, 0, 0, 0)
        p3_layout.setSpacing(8)
        p3_info = QVBoxLayout()
        p3_info.setContentsMargins(0, 0, 0, 0)
        p3_info.setSpacing(2)
        p3_title = QLabel("\u4e3b\u9898\u5207\u6362\u5668")
        p3_title.setStyleSheet(f"font-size: 13px; color: {tm.text.name()}; font-weight: 500;")
        p3_info.addWidget(p3_title)
        p3_desc = QLabel("\u652f\u6301\u6d45\u8272\u548c\u6df1\u8272\u4e3b\u9898\u5207\u6362")
        p3_desc.setStyleSheet(f"font-size: 11px; color: {tm.alpha_of(tm.mid, 60).name()};")
        p3_info.addWidget(p3_desc)
        p3_layout.addLayout(p3_info)
        p3_layout.addStretch()
        p3_tags = QHBoxLayout()
        p3_tags.setSpacing(6)
        p3_tags.addWidget(StyledTag(text="\u514d\u8d39", variant="success", size="sm"))
        p3_tags.addWidget(StyledTag(text="v1.5.2", size="sm"))
        p3_layout.addLayout(p3_tags)
        plugin_layout.addWidget(p3)

        # Plugin 4
        p4 = QWidget()
        p4_layout = QHBoxLayout(p4)
        p4_layout.setContentsMargins(0, 0, 0, 0)
        p4_layout.setSpacing(8)
        p4_info = QVBoxLayout()
        p4_info.setContentsMargins(0, 0, 0, 0)
        p4_info.setSpacing(2)
        p4_title = QLabel("\u65e7\u7248\u5bfc\u51fa\u63d2\u4ef6")
        p4_title.setStyleSheet(f"font-size: 13px; color: {tm.text.name()}; font-weight: 500;")
        p4_info.addWidget(p4_title)
        p4_desc = QLabel("\u4f7f\u7528\u65b0\u7248\u5bfc\u51fa\u529f\u80fd\u66ff\u4ee3")
        p4_desc.setStyleSheet(f"font-size: 11px; color: {tm.alpha_of(tm.mid, 60).name()};")
        p4_info.addWidget(p4_desc)
        p4_layout.addLayout(p4_info)
        p4_layout.addStretch()
        p4_tags = QHBoxLayout()
        p4_tags.setSpacing(6)
        p4_tags.addWidget(StyledTag(text="\u5df2\u5e9f\u5f03", variant="danger", size="sm"))
        p4_tags.addWidget(StyledTag(text="v0.4.1", size="sm"))
        p4_layout.addLayout(p4_tags)
        plugin_layout.addWidget(p4)

        main_layout.addWidget(plugin_card)
        main_layout.addWidget(self._separator())

        # Section 8: Events
        main_layout.addWidget(self._section_label("8. Close Event"))
        main_layout.addWidget(self._section_desc("Click close button to trigger closed signal"))

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        self._event_tag = StyledTag(text="\u70b9\u51fb\u5173\u95ed\u6211", closable=True)
        self._event_tag.closed.connect(self._on_tag_closed)
        row_layout.addWidget(self._event_tag)
        self._event_label = QLabel("Tag exists")
        self._event_label.setStyleSheet(f"font-size: 13px; color: {tm.mid.name()};")
        row_layout.addWidget(self._event_label)
        row_layout.addStretch()
        main_layout.addWidget(row)

        # Scrollable outer layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _on_tag_closed(self):
        self._event_label.setText("Tag closed!")
        self._event_label.setStyleSheet(f"font-size: 13px; color: {tm.danger.name()}; font-weight: 500;")


def main():
    app = QApplication(sys.argv)
    demo = StyledTagDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
