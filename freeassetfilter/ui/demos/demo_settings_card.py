"""SettingsCard Demo - standalone demo showcasing SettingsCard, SettingsRow,
NotificationRow, and PluginItem."""

import sys
import os

# Path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
)
from PySide6.QtCore import Qt
from theme import tm

from components.settings_card import SettingsCard, SettingsRow, NotificationRow, PluginItem
from components.styled_toggle import StyledToggle
from components.styled_button import StyledButton
from components.styled_lineedit import StyledLineEdit
from components.styled_combobox import StyledComboBox


class SettingsCardDemo(QWidget):
    """Main demo window for settings card components."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Settings Card Demo")
        self.resize(800, 800)

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
            font-size: 16px;
            font-weight: 700;
            color: {tm.text.name()};
            margin-top: 12px;
            margin-bottom: 2px;
        """)
        return label

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("border: none; background: transparent;")

        content = QWidget()
        scroll.setWidget(content)

        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(32, 24, 32, 32)
        main_layout.setSpacing(20)

        # ── Section 1: Default Card ──
        main_layout.addWidget(self._section_label("Default Card"))

        default_card = SettingsCard(variant="default")
        default_card.add_header("账号设置")

        body1 = default_card.add_body()

        row_user = SettingsRow(title="用户名", description="当前登录的用户名称")
        username_edit = StyledLineEdit()
        username_edit.setPlaceholderText("请输入用户名")
        username_edit.setText("admin")
        row_user.set_control(username_edit)
        body1.addWidget(row_user)

        row_email = SettingsRow(title="邮箱", description="用于接收通知的邮箱地址")
        email_edit = StyledLineEdit()
        email_edit.setPlaceholderText("请输入邮箱")
        email_edit.setText("admin@example.com")
        row_email.set_control(email_edit)
        body1.addWidget(row_email)

        row_notify = SettingsRow(title="启用通知", description="开启后将接收系统通知")
        notify_toggle = StyledToggle(checked=True)
        row_notify.set_control(notify_toggle)
        body1.addWidget(row_notify)

        footer1 = default_card.add_footer()
        footer1.addStretch()
        cancel_btn = StyledButton("取消", variant="secondary", size="sm")
        save_btn = StyledButton("保存", variant="primary", size="sm")
        footer1.addWidget(cancel_btn)
        footer1.addWidget(save_btn)

        main_layout.addWidget(default_card)

        # ── Section 2: Danger Card ──
        main_layout.addWidget(self._section_label("Danger Card"))

        danger_card = SettingsCard(variant="danger")
        danger_card.add_header("危险操作")

        body2 = danger_card.add_body()

        row_del = SettingsRow(
            title="删除账号",
            description="此操作不可撤销，所有数据将被永久删除",
        )
        warning_label = QLabel("请谨慎操作")
        warning_label.setStyleSheet(f"font-size: 13px; color: {tm.danger.name()};")
        row_del.set_control(warning_label)
        body2.addWidget(row_del)

        row_confirm = SettingsRow(
            title="确认删除",
            description="我已阅读上述警告，确认执行此操作",
        )
        confirm_toggle = StyledToggle(checked=False)
        row_confirm.set_control(confirm_toggle)
        body2.addWidget(row_confirm)

        footer2 = danger_card.add_footer()
        footer2.addStretch()
        del_btn = StyledButton("删除账号", variant="danger", size="sm")
        footer2.addWidget(del_btn)

        main_layout.addWidget(danger_card)

        # ── Section 3: Info Card ──
        main_layout.addWidget(self._section_label("Info Card"))

        info_card = SettingsCard(variant="info")
        info_card.add_header("关于")

        body3 = info_card.add_body()

        row_version = SettingsRow(title="版本", description="当前应用程序版本号")
        version_label = QLabel("v1.2.3")
        version_label.setStyleSheet(f"font-size: 13px; color: {tm.info.name()};")
        row_version.set_control(version_label)
        body3.addWidget(row_version)

        row_theme = SettingsRow(title="主题偏好", description="选择界面颜色主题")
        theme_combo = StyledComboBox(
            items=["深色模式", "浅色模式", "跟随系统"],
            size="sm",
        )
        theme_combo.setCurrentText("深色模式")
        row_theme.set_control(theme_combo)
        body3.addWidget(row_theme)

        main_layout.addWidget(info_card)

        # ── Section 4: Notification Rows ──
        main_layout.addWidget(self._section_label("Notification Rows"))

        notif_card = SettingsCard()
        body4 = notif_card.add_body()

        n1 = NotificationRow(
            title="新消息通知",
            description="收到新消息时弹出通知提醒",
            active=True,
        )
        n1.set_control(StyledToggle(checked=True))
        body4.addWidget(n1)

        n2 = NotificationRow(
            title="系统更新",
            description="操作系统或组件有新版本时通知",
            active=True,
        )
        n2.set_control(StyledToggle(checked=True))
        body4.addWidget(n2)

        n3 = NotificationRow(
            title="邮件提醒",
            description="收取到新邮件时进行提醒",
            active=False,
        )
        n3.set_control(StyledToggle(checked=False))
        body4.addWidget(n3)

        main_layout.addWidget(notif_card)

        # ── Section 5: Plugin Items ──
        main_layout.addWidget(self._section_label("Plugin Items"))

        plugin_card = SettingsCard()
        body5 = plugin_card.add_body()

        p1 = PluginItem(
            name="翻译助手",
            description="自动翻译聊天消息，支持多语种",
            icon_gradient=("#07c160", "#059a4c"),
        )
        p1_btn = StyledButton("启用", variant="primary", size="sm")
        p1.set_control(p1_btn)
        body5.addWidget(p1)

        p2 = PluginItem(
            name="云同步",
            description="自动同步数据到云端存储",
            icon_gradient=("#3b82f6", "#1d4ed8"),
        )
        p2_btn = StyledButton("安装", variant="ghost", size="sm")
        p2.set_control(p2_btn)
        body5.addWidget(p2)

        footer5 = plugin_card.add_footer()
        footer5.addStretch()
        manage_btn = StyledButton("管理插件", variant="ghost", size="sm")
        browse_btn = StyledButton("浏览更多", variant="primary", size="sm")
        footer5.addWidget(manage_btn)
        footer5.addWidget(browse_btn)

        main_layout.addWidget(plugin_card)

        main_layout.addStretch()

        # Outer layout with scroll area
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Settings Card Demo")

    window = SettingsCardDemo()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
