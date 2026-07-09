"""Settings Card component - matches web settings card exactly."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from theme import tm


class SettingsCard(QWidget):
    """A settings card matching the web component exactly."""

    _instance_count = 0

    def __init__(
        self,
        variant: str = "default",  # default, danger, info
        compact: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        SettingsCard._instance_count += 1
        self._instance_id = SettingsCard._instance_count
        self._variant = variant
        self._compact = compact

        # Enable QSS background rendering (CRITICAL: without this, setStyleSheet is ignored)
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(18, 0, 18, 18)
        self._main_layout.setSpacing(0)
        self._apply_style()

    def _apply_style(self):
        if self._variant == "danger":
            c = tm.danger
            border_color = f"rgba({c.red()}, {c.green()}, {c.blue()}, 0.3)"
        elif self._variant == "info":
            c = tm.info
            border_color = f"rgba({c.red()}, {c.green()}, {c.blue()}, 0.3)"
        else:
            border_color = tm.alpha_of(tm.mid, 40).name()

        # Set style on self only via unique objectName to prevent inheritance
        self.setObjectName(f"SettingsCard_{self._instance_id}")
        bg_color = tm.surface.name()
        self.setStyleSheet(f"""
            #SettingsCard_{self._instance_id} {{
                background-color: {bg_color};
                border-radius: 10px;
            }}
        """)

    def add_header(self, title: str, action_widget: QWidget = None):
        """Add a card header with title and optional action widget."""
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 16, 20, 8)
        layout.setSpacing(16)

        title_label = QLabel(title)
        if self._variant == "danger":
            title_label.setStyleSheet(f'font-size: 14px; font-weight: 600; color: {tm.danger.name()}; letter-spacing: 0.3px;')
        elif self._variant == "info":
            title_label.setStyleSheet(f'font-size: 14px; font-weight: 600; color: {tm.info.name()}; letter-spacing: 0.3px;')
        else:
            title_label.setStyleSheet(f'font-size: 14px; font-weight: 600; color: {tm.text.name()}; letter-spacing: 0.3px;')
        layout.addWidget(title_label, stretch=1)

        if action_widget:
            layout.addWidget(action_widget)

        self._main_layout.addWidget(header)
        return header

    def add_body(self) -> QVBoxLayout:
        """Add a card body container and return its layout."""
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 4, 0, 4)  # Web CSS: .card-body { padding: 4px 0; }
        body_layout.setSpacing(0)
        self._main_layout.addWidget(body)
        return body_layout

    def add_footer(self) -> QHBoxLayout:
        """Add a card footer container and return its layout."""
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 12, 20, 12)
        footer_layout.setSpacing(16)

        # Add top border via a separator widget
        sep = QFrame()
        sep.setObjectName(f"SettingsCardSep_{self._instance_id}")
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"""
            #SettingsCardSep_{self._instance_id} {{
                background-color: {tm.alpha_of(tm.mid, 30).name()};
            }}
        """)
        footer_layout_parent = QVBoxLayout()
        footer_layout_parent.setContentsMargins(0, 0, 0, 0)
        footer_layout_parent.setSpacing(0)
        footer_layout_parent.addWidget(sep)
        footer_layout_parent.addWidget(footer)

        self._main_layout.addLayout(footer_layout_parent)
        return footer_layout


class SettingsRow(QWidget):
    """A settings row matching the web component exactly."""

    _instance_count = 0

    def __init__(
        self,
        title: str = "",
        description: str = "",
        compact: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        SettingsRow._instance_count += 1
        self._instance_id = SettingsRow._instance_count
        self._compact = compact
        title_size = "13px" if compact else "13.5px"

        self.setObjectName(f"SettingsRow_{self._instance_id}")
        # Use unique objectName to scope styles to this widget only (prevent inheritance)
        self.setStyleSheet(f"#SettingsRow_{self._instance_id} {{ background: transparent; }}")
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8 if not compact else 6, 0, 8 if not compact else 6)
        layout.setSpacing(16)

        # Left: title + description
        content = QVBoxLayout()
        content.setSpacing(2)

        if title:
            self.title_label = QLabel(title)
            self.title_label.setStyleSheet(f'font-size: {title_size}; font-weight: 500; color: {tm.text.name()};')
            content.addWidget(self.title_label)

        if description:
            self.desc_label = QLabel(description)
            self.desc_label.setStyleSheet(f'font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; line-height: 1.5;')
            self.desc_label.setWordWrap(True)
            content.addWidget(self.desc_label)

        content.addStretch()
        content_widget = QWidget()
        content_widget.setLayout(content)
        layout.addWidget(content_widget, stretch=1)

        # Right: control area
        self.control_widget = QWidget()
        self.control_layout = QHBoxLayout(self.control_widget)
        self.control_layout.setContentsMargins(0, 0, 0, 0)
        self.control_layout.setSpacing(0)
        layout.addWidget(self.control_widget)

    def set_control(self, widget: QWidget):
        """Set the right-side control widget."""
        while self.control_layout.count():
            item = self.control_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.control_layout.addWidget(widget)


class NotificationRow(QWidget):
    """A notification row with a dot indicator."""

    _instance_count = 0

    def __init__(
        self,
        title: str = "",
        description: str = "",
        active: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        NotificationRow._instance_count += 1
        self._instance_id = NotificationRow._instance_count

        self.setObjectName(f"NotificationRow_{self._instance_id}")
        # Use unique objectName to scope styles to this widget only (prevent inheritance)
        self.setStyleSheet(f"#NotificationRow_{self._instance_id} {{ background: transparent; }}")
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)  # Web CSS: padding: 8px 20px
        layout.setSpacing(12)  # Web CSS: gap: 12px

        # Dot indicator
        dot = QFrame()
        dot.setObjectName(f"NotificationDot_{self._instance_id}")
        dot.setFixedSize(8, 8)
        dot_color = tm.accent.name() if active else tm.alpha_of(tm.mid, 60).name()
        dot.setStyleSheet(f"""
            #NotificationDot_{self._instance_id} {{
                background-color: {dot_color};
                border-radius: 4px;
            }}
        """)
        layout.addWidget(dot)

        # Content
        content = QVBoxLayout()
        content.setSpacing(2)

        if title:
            title_label = QLabel(title)
            title_label.setStyleSheet(f'font-size: 13.5px; font-weight: 500; color: {tm.text.name()};')
            content.addWidget(title_label)

        if description:
            desc_label = QLabel(description)
            desc_label.setStyleSheet(f'font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()};')
            content.addWidget(desc_label)

        content_widget = QWidget()
        content_widget.setLayout(content)
        layout.addWidget(content_widget, stretch=1)

        # Control
        self.control_widget = QWidget()
        self.control_layout = QHBoxLayout(self.control_widget)
        self.control_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.control_widget)

    def set_control(self, widget: QWidget):
        while self.control_layout.count():
            item = self.control_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.control_layout.addWidget(widget)


class PluginItem(QWidget):
    """A plugin item with icon, info, and toggle."""

    _instance_count = 0

    def __init__(
        self,
        name: str = "",
        description: str = "",
        icon_gradient: tuple = ("#07c160", "#059a4c"),
        parent=None,
    ):
        super().__init__(parent)
        PluginItem._instance_count += 1
        self._instance_id = PluginItem._instance_count

        self.setObjectName(f"PluginItem_{self._instance_id}")
        # Use unique objectName to scope styles to this widget only (prevent inheritance)
        self.setStyleSheet(f"#PluginItem_{self._instance_id} {{ background: transparent; }}")
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)  # Web CSS: padding: 8px 20px
        layout.setSpacing(14)  # Web CSS: gap: 14px

        # Icon
        icon = QFrame()
        icon.setObjectName(f"PluginIcon_{self._instance_id}")
        icon.setFixedSize(40, 40)
        icon.setStyleSheet(f"""
            #PluginIcon_{self._instance_id} {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {icon_gradient[0]}, stop:1 {icon_gradient[1]});
                border-radius: 6px;
            }}
        """)
        layout.addWidget(icon)

        # Info
        info = QVBoxLayout()
        info.setSpacing(2)

        if name:
            name_label = QLabel(name)
            name_label.setStyleSheet(f'font-size: 13px; font-weight: 500; color: {tm.text.name()};')
            info.addWidget(name_label)

        if description:
            desc_label = QLabel(description)
            desc_label.setStyleSheet(f'font-size: 11.5px; color: {tm.alpha_of(tm.mid, 60).name()};')
            info.addWidget(desc_label)

        info_widget = QWidget()
        info_widget.setLayout(info)
        layout.addWidget(info_widget, stretch=1)

        # Control
        self.control_widget = QWidget()
        self.control_layout = QHBoxLayout(self.control_widget)
        self.control_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.control_widget)

    def set_control(self, widget: QWidget):
        while self.control_layout.count():
            item = self.control_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.control_layout.addWidget(widget)
