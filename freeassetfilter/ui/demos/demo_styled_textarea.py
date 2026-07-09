"""StyledTextarea Demo - standalone demo for all textarea variants."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from theme import tm

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QPushButton,
)
from PySide6.QtCore import Qt

from components.styled_textarea import StyledTextarea


def make_section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"font-size: 14px; font-weight: 600; color: {tm.text.name()}; margin-top: 4px;"
    )
    return label


def build_default_section() -> QWidget:
    """Basic textarea - no label, no counter, simple placeholder."""
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    ta = StyledTextarea(placeholder="请输入内容...")
    layout.addWidget(ta)

    return container


def build_label_section() -> QWidget:
    """Textarea with label and description."""
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    ta = StyledTextarea(
        label="反馈建议",
        description="您的反馈将帮助我们改进产品体验",
        placeholder="请描述您的想法或遇到的问题...",
    )
    layout.addWidget(ta)

    return container


def build_counter_section() -> QWidget:
    """Textarea with character counter."""
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    ta = StyledTextarea(
        label="自定义提示词",
        description="自定义提示词将作为系统提示词使用",
        placeholder="输入自定义提示词，用于模型生成回答...",
        max_length=500,
        text="你是一个专业的翻译助手，请将以下内容翻译成英文。",
    )
    layout.addWidget(ta)

    return container


def build_sizes_section() -> QWidget:
    """Textarea in sm, default, lg sizes."""
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)

    sm = StyledTextarea(
        label="SM - 小型",
        size="sm",
        placeholder="小型文本输入...",
    )
    layout.addWidget(sm)

    default = StyledTextarea(
        label="Default - 默认",
        size="default",
        placeholder="默认尺寸文本输入...",
    )
    layout.addWidget(default)

    lg = StyledTextarea(
        label="LG - 大型",
        size="lg",
        placeholder="大型文本输入...",
    )
    layout.addWidget(lg)

    return container


def build_error_section() -> QWidget:
    """Textarea in error state."""
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    ta = StyledTextarea(
        label="翻译备注",
        description="输入内容不符合要求",
        placeholder="请输入有效内容...",
        error=True,
        text="无效的内容格式",
    )
    layout.addWidget(ta)

    return container


def build_disabled_section() -> QWidget:
    """Textarea in disabled state."""
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    ta = StyledTextarea(
        label="不可编辑字段",
        description="此字段已被禁用",
        placeholder="此文本不可编辑",
        text="此字段不可编辑",
    )
    ta.setEnabled(False)
    layout.addWidget(ta)

    return container


def build_interactive_section() -> QWidget:
    """Interactive demo with live counter, error toggle, and text output."""
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    # Top row: textarea + toggle button
    row = QHBoxLayout()
    row.setSpacing(12)

    ta = StyledTextarea(
        label="交互演示",
        description="输入文本查看实时变化",
        placeholder="输入文本查看实时变化...",
        max_length=100,
    )
    row.addWidget(ta, stretch=1)

    toggle_btn = QPushButton("Toggle Error")
    toggle_btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {tm.mid.name()};
            color: {tm.text.name()};
            border: 1px solid {tm.alpha_of(tm.mid, 40).name()};
            border-radius: 6px;
            padding: 8px 16px;
            font-size: 13px;
        }}
        QPushButton:hover {{
            background-color: {tm.mid.name()};
        }}
    """)
    toggle_btn.setFixedWidth(120)
    row.addWidget(toggle_btn)

    layout.addLayout(row)

    # Output label
    output_label = QLabel("当前输入:（空）")
    output_label.setStyleSheet(
        f"font-size: 13px; color: {tm.accent.name()}; padding: 6px 0;"
    )
    layout.addWidget(output_label)

    # Connections
    def on_text_changed(text: str):
        display = text if text else "（空）"
        output_label.setText(f"当前输入: {display}")

    def on_toggle():
        ta.error = not ta.error
        toggle_btn.setText("Error OFF" if ta.error else "Error ON")

    ta.text_changed.connect(on_text_changed)
    toggle_btn.clicked.connect(on_toggle)

    return container


def main():
    app = QApplication(sys.argv)

    app.setStyleSheet(f"""
        QWidget {{
            background-color: {tm.surface.name()};
        }}
    """)

    window = QWidget()
    window.setWindowTitle("StyledTextarea Demo")
    window.resize(720, 900)

    main_layout = QVBoxLayout(window)
    main_layout.setContentsMargins(32, 24, 32, 24)
    main_layout.setSpacing(16)

    # Section 1: Default
    main_layout.addWidget(make_section_label("1. Default / 默认"))
    main_layout.addWidget(build_default_section())

    sep1 = QFrame()
    sep1.setFrameShape(QFrame.HLine)
    sep1.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 30).name()};")
    main_layout.addWidget(sep1)

    # Section 2: With Label
    main_layout.addWidget(make_section_label("2. With Label / 带标签"))
    main_layout.addWidget(build_label_section())

    sep2 = QFrame()
    sep2.setFrameShape(QFrame.HLine)
    sep2.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 30).name()};")
    main_layout.addWidget(sep2)

    # Section 3: With Counter
    main_layout.addWidget(make_section_label("3. With Counter / 带字数统计"))
    main_layout.addWidget(build_counter_section())

    sep3 = QFrame()
    sep3.setFrameShape(QFrame.HLine)
    sep3.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 30).name()};")
    main_layout.addWidget(sep3)

    # Section 4: Sizes
    main_layout.addWidget(make_section_label("4. Sizes / 尺寸"))
    main_layout.addWidget(build_sizes_section())

    sep4 = QFrame()
    sep4.setFrameShape(QFrame.HLine)
    sep4.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 30).name()};")
    main_layout.addWidget(sep4)

    # Section 5: Error
    main_layout.addWidget(make_section_label("5. Error / 错误状态"))
    main_layout.addWidget(build_error_section())

    sep5 = QFrame()
    sep5.setFrameShape(QFrame.HLine)
    sep5.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 30).name()};")
    main_layout.addWidget(sep5)

    # Section 6: Disabled
    main_layout.addWidget(make_section_label("6. Disabled / 禁用状态"))
    main_layout.addWidget(build_disabled_section())

    sep6 = QFrame()
    sep6.setFrameShape(QFrame.HLine)
    sep6.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 30).name()};")
    main_layout.addWidget(sep6)

    # Section 7: Interactive
    main_layout.addWidget(make_section_label("7. Interactive / 交互演示"))
    main_layout.addWidget(build_interactive_section())

    main_layout.addStretch()

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
