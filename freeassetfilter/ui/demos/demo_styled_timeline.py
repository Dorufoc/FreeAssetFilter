"""StyledTimeline Demo - standalone demo showcasing all timeline variants."""

import sys
import os

# Path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from theme import tm

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
)
from PySide6.QtCore import Qt

from components.styled_timeline import StyledTimeline


class StyledTimelineDemo(QWidget):
    """Main demo window for StyledTimeline."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledTimeline Demo")
        self.resize(620, 640)

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

        # Section 1: Color Variants
        main_layout.addWidget(self._section_label("1. Color Variants"))
        main_layout.addWidget(
            self._section_desc(
                "5 colour variants: primary (green), warning (amber), "
                "danger (red), info (blue), default (grey)"
            )
        )

        timeline1 = StyledTimeline()
        timeline1.add_item(
            "订单已提交",
            "您的订单已成功提交，等待系统处理",
            "2024-01-15 14:30",
            color="primary",
        )
        timeline1.add_item(
            "订单处理中",
            "系统正在处理您的订单，请耐心等待",
            "2024-01-15 14:35",
            color="warning",
        )
        timeline1.add_item(
            "支付失败",
            "余额不足，支付未完成",
            "2024-01-15 14:32",
            color="danger",
        )
        timeline1.add_item(
            "退款已发起",
            "已通知支付渠道处理退款",
            "2024-01-15 14:40",
            color="info",
        )
        timeline1.add_item(
            "等待用户确认",
            "请确认收货后完成订单",
            "2024-01-15 15:00",
            color="default",
        )
        main_layout.addWidget(timeline1)

        # Section 2: Icon Variant
        main_layout.addWidget(self._section_label("2. Icon Variant"))
        main_layout.addWidget(
            self._section_desc(
                "Dots replaced with outlined SVG icons (bell, checkmark, "
                "warning, error, clock)"
            )
        )

        timeline2 = StyledTimeline()
        timeline2.add_item(
            "新消息通知",
            "您收到了一条新的系统消息",
            "10:32",
            color="primary",
            icon="bell",
        )
        timeline2.add_item(
            "任务已完成",
            "代码审查任务已完成",
            "10:15",
            color="primary",
            icon="checkmark",
        )
        timeline2.add_item(
            "系统警告",
            "磁盘使用率已超过 85%",
            "09:50",
            color="warning",
            icon="warning",
        )
        timeline2.add_item(
            "同步失败",
            "文件同步服务暂时不可用",
            "09:20",
            color="danger",
            icon="error",
        )
        timeline2.add_item(
            "定时任务",
            "每日数据备份将在 5 分钟后执行",
            "09:00",
            color="info",
            icon="clock",
        )
        main_layout.addWidget(timeline2)

        # Section 3: Size Variants
        main_layout.addWidget(self._section_label("3. Size Variants"))
        main_layout.addWidget(
            self._section_desc("Small (8 px), default (12 px), large (16 px) dots")
        )

        timeline3 = StyledTimeline()
        timeline3.add_item("Small dot", "8 px diameter circle", "size_variant='sm'", color="primary", size_variant="sm")
        timeline3.add_item("Default dot", "12 px diameter circle", "size_variant='default'", color="info", size_variant="default")
        timeline3.add_item("Large dot", "16 px diameter circle", "size_variant='lg'", color="warning", size_variant="lg")
        main_layout.addWidget(timeline3)

        # Section 4: Empty State
        main_layout.addWidget(self._section_label("4. Empty State"))
        main_layout.addWidget(
            self._section_desc("When no items are present a centred icon + '暂无数据' is shown")
        )

        empty_timeline = StyledTimeline()
        main_layout.addWidget(empty_timeline)

        # Toggle button to show / hide items
        btn_row = QHBoxLayout()
        add_btn = QPushButton("添加示例项")
        add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {tm.accent.name()};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {tm.accent_hover.name()}; }}
            QPushButton:pressed {{ background-color: {tm.accent_active.name()}; }}
        """)
        clear_btn = QPushButton("清空")
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {tm.danger.name()};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {tm.danger.name()}; }}
            QPushButton:pressed {{ background-color: {tm.danger.name()}; }}
        """)

        def _add_demo_item():
            empty_timeline.add_item(
                "示例事件",
                "通过按钮动态添加的时间线项目",
                "2024-06-07 16:00",
                color="primary",
            )

        def _clear_items():
            empty_timeline.clear()

        add_btn.clicked.connect(_add_demo_item)
        clear_btn.clicked.connect(_clear_items)

        btn_row.addWidget(add_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        main_layout.addLayout(btn_row)

        # Section 5: Single item
        main_layout.addWidget(self._section_label("5. Single Item"))
        main_layout.addWidget(self._section_desc("Timeline with only one item"))

        timeline5 = StyledTimeline()
        timeline5.add_item(
            "当前状态",
            "这是唯一的时间线节点",
            "刚刚",
            color="primary",
        )
        main_layout.addWidget(timeline5)

        # Scrollable outer layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)


def main():
    app = QApplication(sys.argv)
    demo = StyledTimelineDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
