"""
D-Fronted Qt6 Components - Main Entry Point

Demonstrates all components in a complete settings window demo.
"""

import sys

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QScrollArea,
    QPushButton,
)
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QMouseEvent, QPainter, QPaintEvent, QResizeEvent, QMoveEvent

from qframelesswindow import FramelessMainWindow

from components.mica_material import MicaMaterial
from components.styled_button import StyledButton
from components.styled_lineedit import StyledLineEdit
from components.styled_toggle import StyledToggle
from components.styled_checkbox import StyledCheckbox
from components.styled_radio import StyledRadio
from components.styled_slider import StyledSlider
from components.styled_combobox import StyledComboBox
from components.settings_card import SettingsCard, SettingsRow, NotificationRow, PluginItem
from components.styled_sidebar import StyledSidebar, ContentScrollBar
from components.styled_progress import StyledProgress
from components.styled_progress_circle import StyledProgressCircle
from theme import tm

def load_global_stylesheet() -> str:
    """Load the global QSS stylesheet via ThemeManager from the .qss.tpl template."""
    return tm.render_qss()


class AccountSettingsPage(QWidget):
    """The account and storage settings page content."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(8)

        # Account info card
        account_card = SettingsCard()
        account_card.add_header("账号信息")
        body = account_card.add_body()

        row1 = SettingsRow(
            title="用户名",
            description="当前登录的用户账号",
        )
        username_label = QLabel("user@example.com")
        username_label.setStyleSheet(f'font-size: 13px; color: {tm.mid.name()};')
        row1.set_control(username_label)
        body.addWidget(row1)

        row2 = SettingsRow(
            title="存储空间",
            description="已使用 2.5GB / 10GB",
        )
        storage_bar = StyledSlider(value=0.25, size="sm")
        storage_bar.setFixedWidth(200)
        row2.set_control(storage_bar)
        body.addWidget(row2)

        layout.addWidget(account_card)

        # Data management card
        data_card = SettingsCard()
        data_card.add_header("数据管理")
        body2 = data_card.add_body()

        row3 = SettingsRow(
            title="自动备份聊天记录",
            description="定期备份聊天记录到云端",
        )
        backup_toggle = StyledToggle(checked=True)
        row3.set_control(backup_toggle)
        body2.addWidget(row3)

        row4 = SettingsRow(
            title="清理缓存",
            description="释放本地存储空间",
        )
        clear_btn = StyledButton("立即清理", variant="secondary", size="sm")
        row4.set_control(clear_btn)
        body2.addWidget(row4)

        layout.addWidget(data_card)
        layout.addStretch()


class GeneralSettingsPage(QWidget):
    """The general settings page content."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(8)

        # Language Card
        lang_card = SettingsCard()
        lang_combo = StyledComboBox(
            items=["跟随系统", "简体中文", "English"],
            size="sm",
        )
        lang_combo.setCurrentText("跟随系统")
        lang_card.add_header("语言", lang_combo)
        layout.addWidget(lang_card)

        # Translation Card
        trans_card = SettingsCard()
        body1_layout = trans_card.add_body()

        row1 = SettingsRow(
            title="将文字翻译为",
            description="在聊天中使用翻译功能时的目标语言",
        )
        target_combo = StyledComboBox(
            items=["当前使用的语言", "简体中文", "English"],
            size="sm",
        )
        target_combo.setCurrentText("当前使用的语言")
        row1.set_control(target_combo)
        body1_layout.addWidget(row1)

        row2 = SettingsRow(
            title="自动翻译聊天中收到的消息",
            description="开启后所有消息会被自动翻译",
        )
        auto_toggle = StyledToggle(checked=False)
        row2.set_control(auto_toggle)
        body1_layout.addWidget(row2)

        row2b = SettingsRow(
            title="显示原文对照",
            description="翻译后同时显示原文和译文",
        )
        show_original = StyledCheckbox(checked=True)
        row2b.set_control(show_original)
        body1_layout.addWidget(row2b)

        layout.addWidget(trans_card)

        # Appearance Card
        appear_card = SettingsCard()
        appear_card.add_header("外观")

        body2_layout = appear_card.add_body()

        # Theme radio group
        theme_row = SettingsRow(title="主题模式")
        theme_widget = QWidget()
        theme_vlayout = QVBoxLayout(theme_widget)
        theme_vlayout.setContentsMargins(0, 0, 0, 0)
        theme_vlayout.setSpacing(8)
        r1 = StyledRadio(checked=False, text="浅色模式", group_name="theme", size="sm")
        r2 = StyledRadio(checked=True, text="深色模式", group_name="theme", size="sm")
        r3 = StyledRadio(checked=False, text="跟随系统", group_name="theme", size="sm")
        theme_vlayout.addWidget(r1)
        theme_vlayout.addWidget(r2)
        theme_vlayout.addWidget(r3)
        theme_row.set_control(theme_widget)
        body2_layout.addWidget(theme_row)

        font_row = SettingsRow(title="字体大小")
        font_row.control_widget.setFixedWidth(240)
        slider = StyledSlider(
            value=0.5,
            tick_count=4,
            labels=["小", "标准", "大"],
        )
        font_row.set_control(slider)
        body2_layout.addWidget(font_row)

        layout.addWidget(appear_card)

        # File & Search Card
        file_card = SettingsCard()
        body3_layout = file_card.add_body()

        row3 = SettingsRow(
            title="以只读的方式打开聊天中的文件",
            description="开启后可保护聊天中的文件不被修改",
        )
        file_toggle = StyledToggle(checked=True)
        row3.set_control(file_toggle)
        body3_layout.addWidget(row3)

        row4 = SettingsRow(
            title="显示网络搜索历史",
            description="在搜索框中显示之前的搜索记录",
        )
        search_toggle = StyledToggle(checked=True)
        row4.set_control(search_toggle)
        body3_layout.addWidget(row4)

        layout.addWidget(file_card)

        layout.addStretch()


class ShortcutsSettingsPage(QWidget):
    """The shortcuts settings page content."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(8)

        card = SettingsCard()
        body_layout = card.add_body()

        shortcuts = [
            ("打开聊天", "快速打开新的聊天窗口", ["Ctrl", "Alt", "N"]),
            ("搜索", "全局搜索功能", ["Ctrl", "F"]),
            ("截图", "截取当前屏幕", ["Ctrl", "Shift", "S"]),
            ("设置", "打开设置窗口", ["Ctrl", ","]),
        ]

        for title, desc, keys in shortcuts:
            row = SettingsRow(title=title, description=desc)
            keys_layout = QHBoxLayout()
            keys_layout.setSpacing(4)
            for i, key in enumerate(keys):
                badge = QLabel(key)
                badge.setFixedWidth(max(28, len(key) * 8 + 12))
                badge.setAlignment(Qt.AlignCenter)
                badge.setStyleSheet(f"""
                    background-color: {tm.mid.name()};
                    border: 1px solid {tm.mid.name()};
                    border-radius: 6px;
                    font-size: 11px;
                    font-weight: 600;
                    color: {tm.mid.name()};
                    min-height: 26px;
                """)
                keys_layout.addWidget(badge)
                if i < len(keys) - 1:
                    sep = QLabel("+")
                    sep.setStyleSheet(f'color: {tm.alpha_of(tm.mid, 60).name()}; font-size: 12px;')
                    keys_layout.addWidget(sep)
            keys_layout.addStretch()

            keys_widget = QWidget()
            keys_widget.setLayout(keys_layout)
            row.set_control(keys_widget)
            body_layout.addWidget(row)

        layout.addWidget(card)
        layout.addStretch()


class NotificationsSettingsPage(QWidget):
    """The notifications settings page content."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(8)

        card = SettingsCard()
        body_layout = card.add_body()

        notif1 = NotificationRow(
            title="新消息通知",
            description="收到新消息时弹出通知",
            active=True,
        )
        toggle1 = StyledToggle(checked=True)
        notif1.set_control(toggle1)
        body_layout.addWidget(notif1)

        notif2 = NotificationRow(
            title="桌面弹窗",
            description="在桌面显示通知弹窗",
            active=False,
        )
        toggle2 = StyledToggle(checked=False)
        notif2.set_control(toggle2)
        body_layout.addWidget(notif2)

        notif3 = NotificationRow(
            title="声音提醒",
            description="收到消息时播放提示音",
            active=True,
        )
        toggle3 = StyledToggle(checked=True)
        notif3.set_control(toggle3)
        body_layout.addWidget(notif3)

        layout.addWidget(card)
        layout.addStretch()


class PluginsSettingsPage(QWidget):
    """The plugins settings page content."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(8)

        card = SettingsCard()
        body_layout = card.add_body()

        plugin1 = PluginItem(
            name="翻译助手",
            description="自动翻译聊天消息",
            icon_gradient=("#07c160", "#059a4c"),
        )
        toggle1 = StyledToggle(checked=True)
        plugin1.set_control(toggle1)
        body_layout.addWidget(plugin1)

        plugin2 = PluginItem(
            name="文件助手",
            description="文件传输与管理",
            icon_gradient=("#3b82f6", "#1d4ed8"),
        )
        toggle2 = StyledToggle(checked=False)
        plugin2.set_control(toggle2)
        body_layout.addWidget(plugin2)

        # Footer
        footer_layout = card.add_footer()
        footer_layout.addStretch()
        manage_btn = StyledButton("管理插件", variant="ghost", size="sm")
        footer_layout.addWidget(manage_btn)
        browse_btn = StyledButton("浏览更多", variant="primary", size="sm")
        footer_layout.addWidget(browse_btn)

        layout.addWidget(card)
        layout.addStretch()


class ComponentsDemoPage(QWidget):
    """Demo page showcasing checkbox and radio components in detail."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _section_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f'font-size: 14px; font-weight: 600; color: {tm.text.name()}; margin-bottom: 4px;')
        return label

    def _section_desc(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f'font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; margin-bottom: 8px;')
        return label

    def _row_with_label(self, label_text: str, widgets: list) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        lbl = QLabel(label_text)
        lbl.setStyleSheet(f'font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; min-width: 64px;')
        layout.addWidget(lbl)
        for w in widgets:
            layout.addWidget(w)
        layout.addStretch()
        return row

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(16)

        # ===== Checkbox Card =====
        cb_card = SettingsCard()
        cb_card.add_header("Checkbox 复选框")
        cb_body = cb_card.add_body()

        # Default
        cb_body.addWidget(self._section_title("默认"))
        cb_body.addWidget(self._section_desc("基础复选框状态"))
        cb_body.addWidget(self._row_with_label("默认", [
            StyledCheckbox(checked=False),
            StyledCheckbox(checked=True),
        ]))

        # With labels
        cb_body.addWidget(self._section_title("带标签"))
        cb_body.addWidget(self._row_with_label("标签", [
            StyledCheckbox(checked=False, text="记住选择"),
            StyledCheckbox(checked=True, text="自动保存"),
        ]))

        # Indeterminate
        cb_body.addWidget(self._section_title("不定状态"))
        cb_body.addWidget(self._row_with_label("不定", [
            StyledCheckbox(checked=False, text="部分选中", indeterminate=True),
        ]))

        # Sizes
        cb_body.addWidget(self._section_title("尺寸"))
        cb_body.addWidget(self._row_with_label("小", [
            StyledCheckbox(checked=False, size="sm", text="小选项"),
            StyledCheckbox(checked=True, size="sm", text="小已选"),
        ]))
        cb_body.addWidget(self._row_with_label("大", [
            StyledCheckbox(checked=False, size="lg", text="大选项"),
            StyledCheckbox(checked=True, size="lg", text="大已选"),
        ]))

        # Disabled
        cb_body.addWidget(self._section_title("禁用"))
        cb_body.addWidget(self._row_with_label("禁用", [
            StyledCheckbox(checked=False, enabled=False, text="禁用未选"),
            StyledCheckbox(checked=True, enabled=False, text="禁用已选"),
        ]))

        # Group example
        cb_body.addWidget(self._section_title("组合示例"))
        group_widget = QWidget()
        group_layout = QVBoxLayout(group_widget)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.setSpacing(8)
        group_layout.addWidget(StyledCheckbox(checked=True, text="接收邮件通知"))
        group_layout.addWidget(StyledCheckbox(checked=True, text="接收短信通知"))
        group_layout.addWidget(StyledCheckbox(checked=False, text="接收推送通知"))
        group_layout.addWidget(StyledCheckbox(checked=False, enabled=False, text="电话通知（不可用）"))
        cb_body.addWidget(group_widget)

        layout.addWidget(cb_card)

        # ===== Radio Card =====
        rb_card = SettingsCard()
        rb_card.add_header("Radio 单选按钮")
        rb_body = rb_card.add_body()

        # Language
        rb_body.addWidget(self._section_title("语言"))
        rb_body.addWidget(self._row_with_label("语言", [
            StyledRadio(checked=True, text="跟随系统", group_name="lang"),
            StyledRadio(checked=False, text="简体中文", group_name="lang"),
            StyledRadio(checked=False, text="English", group_name="lang"),
        ]))

        # Small
        rb_body.addWidget(self._section_title("小尺寸"))
        rb_body.addWidget(self._row_with_label("小", [
            StyledRadio(checked=False, size="sm", text="选项 A", group_name="sz-sm"),
            StyledRadio(checked=True, size="sm", text="选项 B", group_name="sz-sm"),
        ]))

        # Large
        rb_body.addWidget(self._section_title("大尺寸"))
        rb_body.addWidget(self._row_with_label("大", [
            StyledRadio(checked=False, size="lg", text="选项 A", group_name="sz-lg"),
            StyledRadio(checked=True, size="lg", text="选项 B", group_name="sz-lg"),
        ]))

        # Theme
        rb_body.addWidget(self._section_title("主题"))
        rb_body.addWidget(self._row_with_label("主题", [
            StyledRadio(checked=False, size="lg", text="浅色模式", group_name="demo-theme"),
            StyledRadio(checked=True, size="lg", text="深色模式", group_name="demo-theme"),
            StyledRadio(checked=False, size="lg", text="跟随系统", group_name="demo-theme"),
        ]))

        # No label
        rb_body.addWidget(self._section_title("无标签"))
        rb_body.addWidget(self._row_with_label("无标签", [
            StyledRadio(checked=False, group_name="nolabel-demo"),
            StyledRadio(checked=True, group_name="nolabel-demo"),
            StyledRadio(checked=False, group_name="nolabel-demo"),
        ]))

        # Disabled
        rb_body.addWidget(self._section_title("禁用"))
        rb_body.addWidget(self._row_with_label("禁用", [
            StyledRadio(checked=False, text="可用选项", group_name="demo-dis"),
            StyledRadio(checked=False, enabled=False, text="禁用选项", group_name="demo-dis"),
            StyledRadio(checked=True, enabled=False, text="已选中（禁用）", group_name="demo-dis"),
        ]))

        layout.addWidget(rb_card)
        layout.addStretch()

        # ===== Button Card =====
        btn_card = SettingsCard()
        btn_card.add_header("Button 按钮")
        btn_body = btn_card.add_body()

        # Variants
        btn_body.addWidget(self._section_title("变体"))
        btn_body.addWidget(self._section_desc("按钮的 5 种颜色变体"))
        btn_body.addWidget(self._row_with_label("变体", [
            StyledButton("Primary", variant="primary"),
            StyledButton("Secondary", variant="secondary"),
            StyledButton("Ghost", variant="ghost"),
            StyledButton("Danger", variant="danger"),
            StyledButton("Info", variant="info"),
        ]))

        # Sizes
        btn_body.addWidget(self._section_title("尺寸"))
        btn_body.addWidget(self._section_desc("3 种按钮尺寸"))
        btn_body.addWidget(self._row_with_label("小", [
            StyledButton("小按钮", variant="primary", size="sm"),
            StyledButton("小按钮", variant="secondary", size="sm"),
            StyledButton("小按钮", variant="ghost", size="sm"),
        ]))
        btn_body.addWidget(self._row_with_label("默认", [
            StyledButton("默认按钮", variant="primary", size="default"),
            StyledButton("默认按钮", variant="secondary", size="default"),
            StyledButton("默认按钮", variant="ghost", size="default"),
        ]))
        btn_body.addWidget(self._row_with_label("大", [
            StyledButton("大按钮", variant="primary", size="lg"),
            StyledButton("大按钮", variant="secondary", size="lg"),
            StyledButton("大按钮", variant="ghost", size="lg"),
        ]))

        # Icon + Text
        btn_body.addWidget(self._section_title("图标 + 文字"))
        btn_body.addWidget(self._section_desc("图标在文字左侧或右侧"))
        btn_body.addWidget(self._row_with_label("图标左", [
            StyledButton("添加", variant="primary", icon="+", icon_position="left"),
            StyledButton("保存", variant="secondary", icon="💾", icon_position="left"),
            StyledButton("查看详情", variant="info", icon="ℹ", icon_position="left"),
        ]))
        btn_body.addWidget(self._row_with_label("图标右", [
            StyledButton("删除", variant="danger", icon="✕", icon_position="right"),
            StyledButton("下载", variant="primary", icon="↓", icon_position="right"),
            StyledButton("设置", variant="ghost", icon="⚙", icon_position="right"),
        ]))

        # Icon only
        btn_body.addWidget(self._section_title("纯图标按钮"))
        btn_body.addWidget(self._section_desc("仅显示图标的按钮"))
        btn_body.addWidget(self._row_with_label("小", [
            StyledButton(icon="+", variant="primary", size="sm"),
            StyledButton(icon="✕", variant="ghost", size="sm"),
            StyledButton(icon="↓", variant="ghost", size="sm"),
        ]))
        btn_body.addWidget(self._row_with_label("默认", [
            StyledButton(icon="+", variant="primary", size="default"),
            StyledButton(icon="✕", variant="ghost", size="default"),
            StyledButton(icon="↓", variant="ghost", size="default"),
        ]))
        btn_body.addWidget(self._row_with_label("大", [
            StyledButton(icon="+", variant="primary", size="lg"),
            StyledButton(icon="✕", variant="ghost", size="lg"),
            StyledButton(icon="↓", variant="ghost", size="lg"),
        ]))

        # States
        btn_body.addWidget(self._section_title("状态"))
        btn_body.addWidget(self._section_desc("正常、禁用、加载中状态"))
        disabled_btn = StyledButton("Disabled", variant="primary")
        disabled_btn.setEnabled(False)
        btn_body.addWidget(self._row_with_label("状态", [
            StyledButton("Normal", variant="primary"),
            disabled_btn,
            StyledButton("Loading", variant="primary", loading=True),
        ]))

        # Loading with different variants
        btn_body.addWidget(self._section_title("加载状态"))
        btn_body.addWidget(self._section_desc("不同变体的加载动画"))
        btn_body.addWidget(self._row_with_label("加载", [
            StyledButton("加载中", variant="primary", loading=True),
            StyledButton("加载中", variant="secondary", loading=True),
            StyledButton("加载中", variant="ghost", loading=True),
        ]))

        # Block button
        btn_body.addWidget(self._section_title("全宽按钮"))
        block_widget = QWidget()
        block_layout = QVBoxLayout(block_widget)
        block_layout.setContentsMargins(0, 0, 0, 0)
        block_layout.setSpacing(8)
        block_layout.addWidget(StyledButton("全宽保存按钮", variant="primary", block=True))
        block_layout.addWidget(StyledButton("全宽删除按钮", variant="danger", block=True))
        btn_body.addWidget(block_widget)

        # Group example
        btn_body.addWidget(self._section_title("组合示例"))
        btn_body.addWidget(self._section_desc("按钮组排列"))
        group_btn_widget = QWidget()
        group_btn_layout = QHBoxLayout(group_btn_widget)
        group_btn_layout.setContentsMargins(0, 0, 0, 0)
        group_btn_layout.setSpacing(8)
        group_btn_layout.addWidget(StyledButton("取消", variant="secondary"))
        group_btn_layout.addWidget(StyledButton("确认", variant="primary"))
        group_btn_layout.addStretch()
        btn_body.addWidget(group_btn_widget)

        layout.addWidget(btn_card)
        layout.addStretch()

        # ===== Progress Card =====
        prog_card = SettingsCard()
        prog_card.add_header("Progress 进度条")
        prog_body = prog_card.add_body()

        # Linear basic
        prog_body.addWidget(self._section_title("条形进度 - 基础值"))
        prog_body.addWidget(self._section_desc("展示不同进度的状态"))
        for pct in [30, 50, 75]:
            p = StyledProgress(value=pct / 100.0)
            prog_body.addWidget(p)

        # Color variants
        prog_body.addWidget(self._section_title("条形进度 - 颜色变体"))
        for variant in [("success", "成功"), ("warning", "警告"), ("danger", "危险")]:
            row_w = QWidget()
            r_layout = QHBoxLayout(row_w)
            r_layout.setContentsMargins(0, 0, 0, 0)
            r_layout.setSpacing(12)
            vl = QLabel(variant[1])
            vl.setStyleSheet(f'color: {tm.alpha_of(tm.mid, 60).name()}; font-size: 12px; min-width: 40px;')
            r_layout.addWidget(vl)
            r_layout.addWidget(StyledProgress(value=0.65, variant=variant[0]))
            r_layout.addStretch()
            prog_body.addWidget(row_w)

        # Striped
        prog_body.addWidget(self._section_title("条纹动画"))
        prog_body.addWidget(self._row_with_label("条纹", [
            StyledProgress(value=0.75, striped=True),
        ]))

        # Sizes
        prog_body.addWidget(self._section_title("尺寸"))
        prog_body.addWidget(self._row_with_label("小", [
            StyledProgress(value=0.5, size="sm"),
        ]))
        prog_body.addWidget(self._row_with_label("大", [
            StyledProgress(value=0.5, size="lg"),
        ]))

        # Circular
        prog_body.addWidget(self._section_title("圆形进度"))
        prog_body.addWidget(self._section_desc("不同颜色和尺寸的圆形进度环"))
        circ_row = QWidget()
        cr_layout = QHBoxLayout(circ_row)
        cr_layout.setContentsMargins(0, 0, 0, 0)
        cr_layout.setSpacing(24)
        cr_layout.addWidget(StyledProgressCircle(value=0.25, size="md"))
        cr_layout.addWidget(StyledProgressCircle(value=0.5, variant="success", size="md"))
        cr_layout.addWidget(StyledProgressCircle(value=0.75, variant="warning", size="md"))
        cr_layout.addWidget(StyledProgressCircle(value=1.0, variant="danger", size="md"))
        cr_layout.addStretch()
        prog_body.addWidget(circ_row)

        layout.addWidget(prog_card)
        layout.addStretch()


class AboutSettingsPage(QWidget):
    """The about settings page content."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(8)

        # App info card
        info_card = SettingsCard()
        body_layout = info_card.add_body()

        app_name = QLabel("D-Fronted Qt6 Components")
        app_name.setStyleSheet(f'font-size: 16px; font-weight: 600; color: {tm.text.name()};')
        app_name.setContentsMargins(20, 16, 20, 4)
        body_layout.addWidget(app_name)

        version = QLabel("版本 0.1.0")
        version.setStyleSheet(f'font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()};')
        version.setContentsMargins(20, 0, 20, 16)
        body_layout.addWidget(version)

        desc = QLabel("基于 PySide6 + qasync 构建的桌面组件库，完整复现 Web 组件库的视觉设计和交互功能。")
        desc.setStyleSheet(f'font-size: 13px; color: {tm.mid.name()}; line-height: 1.5;')
        desc.setWordWrap(True)
        desc.setContentsMargins(20, 0, 20, 16)
        body_layout.addWidget(desc)

        layout.addWidget(info_card)

        # Components list
        comp_card = SettingsCard()
        comp_card.add_header("包含组件")
        comp_layout = comp_card.add_body()

        components = [
            "StyledButton - 按钮组件 (5种变体, 3种尺寸)",
            "StyledLineEdit - 输入框组件 (3种尺寸, 错误状态)",
            "StyledToggle - 开关组件 (3种尺寸, 动画效果)",
            "StyledSlider - 滑动条组件 (3种尺寸, 刻度标签)",
            "StyledComboBox - 下拉选择组件 (自定义渲染)",
            "SettingsCard - 设置卡片组件 (header/body/footer)",
            "StyledSidebar - 侧边栏组件 (导航, 徽章, 分隔线)",
        ]

        for comp in components:
            row = SettingsRow(title=comp)
            comp_layout.addWidget(row)

        layout.addWidget(comp_card)
        layout.addStretch()


class SettingsWindow(FramelessMainWindow):
    """Main settings window combining sidebar and content panels with custom Mica effect."""

    # Mica配置参数
    MICA_CONFIG = {
        "blur_radius": 200,
        "tint_color": "#202020E8",
        "luminosity": 0.65,
        "contrast": 1.5,
        "saturation": 4.0,
    }

    def __init__(self, parent=None):
        # 先定义属性，防止父类初始化期间触发的事件访问未定义属性
        self._pages = {}
        self._mica = None
        super().__init__(parent)
        
        self._setup_ui()
        
        # UI设置完成后初始化自定义Mica效果
        self._mica = MicaMaterial(
            self,
            blur_radius=self.MICA_CONFIG["blur_radius"],
            tint_color=self.MICA_CONFIG["tint_color"],
            luminosity=self.MICA_CONFIG["luminosity"],
            contrast=self.MICA_CONFIG["contrast"],
            saturation=self.MICA_CONFIG["saturation"],
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制Mica背景效果。"""
        if self._mica is None:
            return
        painter = QPainter(self)
        self._mica.paint(painter, event)
        painter.end()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """窗口大小变化时刷新Mica缓存并触发重绘。"""
        super().resizeEvent(event)
        if self._mica is not None:
            self._mica.invalidate_cache()
            self.update()  # 触发paintEvent重新绘制

    def moveEvent(self, event: QMoveEvent) -> None:
        """窗口移动时刷新Mica缓存并触发重绘。"""
        super().moveEvent(event)
        if self._mica is not None:
            self._mica.invalidate_cache()
            self.update()  # 触发paintEvent重新绘制

    def _setup_ui(self):
        self.setWindowTitle("设置 - D-Fronted Qt6 Components")
        self.resize(860, 560)
        self.setMinimumSize(700, 450)
        
        # 设置窗口透明背景，让Mica效果可见
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("SettingsWindow { background: transparent; }")

        # --- 中央控件透明，让窗口级别的Mica背景可见 ---
        central = QWidget()
        central.setObjectName("MainWindow")
        central.setAttribute(Qt.WA_TranslucentBackground, True)
        central.setStyleSheet("""
            #MainWindow {
                background-color: transparent;
            }
        """)
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar (transparent to show Mica through)
        self._sidebar = StyledSidebar(title=" ", width=240, transparent=True)
        self._sidebar.add_item("组件展示", icon_svg="grid")
        self._sidebar.add_item("账号与存储", icon_svg="user")
        self._sidebar.add_item("通用", icon_svg="gear")
        self._sidebar.add_item("快捷键", icon_svg="keyboard")
        self._sidebar.add_item("通知", icon_svg="bell")
        self._sidebar.add_item("插件", icon_svg="plugins")
        self._sidebar.add_item("关于", icon_svg="info")
        self._sidebar.item_selected.connect(self._on_sidebar_selected)
        self._sidebar.installEventFilter(self)  # drag on empty area
        main_layout.addWidget(self._sidebar)

        # Content panel (semi-transparent to show Mica through)
        panel = QWidget()
        panel.setObjectName("ContentPanel")
        panel.setStyleSheet("""
            #ContentPanel {
                background-color: transparent;
                border-top-right-radius: 12px;
                border-bottom-right-radius: 12px;
            }
        """)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        # --- Custom header (as library title bar for native drag) ---
        header = QFrame()
        header.setFixedHeight(60)
        header.setFrameShape(QFrame.NoFrame)
        header.setObjectName("PanelHeader")
        header.setStyleSheet("""
            #PanelHeader {
                background-color: transparent;
                border-top-right-radius: 12px;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 12, 16, 12)
        header_layout.setSpacing(0)

        # Title wrapper — independently bottom-aligned via internal stretch
        title_wrapper = QWidget()
        title_layout = QVBoxLayout(title_wrapper)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        title_layout.addStretch()
        self._panel_title = QLabel("账号与存储")
        self._panel_title.setStyleSheet(f'font-size: 22px; font-weight: 600; color: {tm.text.name()};')
        title_layout.addWidget(self._panel_title)
        header_layout.addWidget(title_wrapper, stretch=1)

        # Minimize button
        minimize_btn = StyledButton("", variant="ghost", size="sm")
        minimize_btn.setFixedSize(32, 32)
        minimize_btn.setText("−")
        minimize_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none; color: {tm.mid.name()}; font-size: 18px; font-weight: 300; }}
            QPushButton:hover {{ color: {tm.text.name()}; }}
        """)
        minimize_btn.clicked.connect(self._on_minimize_clicked)
        header_layout.addWidget(minimize_btn)

        # Close button
        close_btn = StyledButton("", variant="ghost", size="sm")
        close_btn.setFixedSize(32, 32)
        close_btn.setText("✕")
        close_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none; color: {tm.mid.name()}; font-size: 18px; font-weight: 300; }}
            QPushButton:hover {{ color: {tm.text.name()}; }}
        """)
        close_btn.clicked.connect(self._on_close_clicked)
        header_layout.addWidget(close_btn)

        # Custom header – drag via eventFilter
        header.installEventFilter(self)
        panel_layout.addWidget(header)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setObjectName("ContentScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBar(ContentScrollBar(scroll))
        scroll.setStyleSheet("""
            #ContentScroll {
                border: none;
                background: transparent;
            }
        """)
        scroll.viewport().setStyleSheet("background: transparent;")

        self._content_widget = QWidget()
        self._content_widget.setStyleSheet("background: transparent;")
        scroll.setWidget(self._content_widget)
        panel_layout.addWidget(scroll, stretch=1)

        # Footer
        footer = QFrame()
        footer.setFrameShape(QFrame.NoFrame)
        footer.setObjectName("SettingsFooter")
        footer.setStyleSheet("""
            #SettingsFooter {
                background-color: transparent;
            }
        """)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 14, 24, 14)
        footer_layout.setSpacing(10)

        reset_btn = StyledButton("重置设置", variant="secondary", size="sm")
        save_btn = StyledButton("保存更改", variant="primary", size="sm")
        footer_layout.addStretch()
        footer_layout.addWidget(reset_btn)
        footer_layout.addWidget(save_btn)

        panel_layout.addWidget(footer)

        main_layout.addWidget(panel, stretch=1)

        # 只显示第一个页面，其他页面延迟加载
        self._show_page(0)

    def _get_page(self, index: int):
        """获取页面，支持延迟加载。只在首次访问时才创建页面实例。"""
        if index not in self._pages:
            # 延迟创建页面
            page_creators = {
                0: ComponentsDemoPage,
                1: AccountSettingsPage,
                2: GeneralSettingsPage,
                3: ShortcutsSettingsPage,
                4: NotificationsSettingsPage,
                5: PluginsSettingsPage,
                6: AboutSettingsPage,
            }
            if index in page_creators:
                self._pages[index] = page_creators[index]()
        return self._pages.get(index)

    def _show_page(self, index: int):
        """Show the page at the given index."""
        # Clear current content
        layout = self._content_widget.layout()
        if layout:
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().setParent(None)
        else:
            layout = QVBoxLayout(self._content_widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

        page = self._get_page(index)
        if page:
            page.setParent(self._content_widget)
            layout.addWidget(page)

    def _on_sidebar_selected(self, index: int, label: str):
        """Handle sidebar item selection."""
        self._panel_title.setText(label)
        self._show_page(index)

    def _on_minimize_clicked(self):
        self.showMinimized()

    def _on_close_clicked(self):
        QApplication.instance().quit()

    def eventFilter(self, obj, event):
        """Trigger native window move on header/sidebar drag (empty areas only)."""
        if not isinstance(event, QMouseEvent) or event.button() != Qt.LeftButton:
            return False
        if event.type() != QEvent.Type.MouseButtonPress:
            return False

        child = obj.childAt(event.position().toPoint())
        if child is not None and isinstance(child, QPushButton):
            return False  # only skip actual buttons, not labels/frames

        if self.windowHandle():
            self.windowHandle().startSystemMove()
            return True
        return False


def main() -> None:
    """Application entry point."""
    app = QApplication(sys.argv)
    app.setApplicationName("D-Fronted Qt6 Components")
    app.setApplicationVersion("0.1.0")
    app.setOrganizationName("D-Fronted")

    # Apply global stylesheet
    qss = load_global_stylesheet()
    if qss:
        app.setStyleSheet(qss)

    # Create and show main window
    window = SettingsWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
