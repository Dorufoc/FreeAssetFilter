# -*- coding: utf-8 -*-
"""StyledChatBubble / ChatMessageRow 原子组件独立演示。

运行（仓库根目录）：

    python -m freeassetfilter.ui.demos.styled_chat_bubble_demo

演示内容（SettingsCard 分节）：

1. 角色变体：assistant / user / reasoning / system / tool；
2. 消息类型：文本 / 图片 / 文件 / 输入中；
3. WinUI 3 气泡规格：助手白气泡与强调蓝气泡，左下 / 右下 4px 收窄对比；
4. 流式追加：逐段输出 + 流式光标；
5. 主题切换：全部配色跟随 ThemeManager。

所有样式一律经 ``register_widget_qss`` 注册，禁止逐控件直写样式表。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Optional

# 直接以脚本方式执行时把仓库根目录加入 sys.path，保证绝对导入可用
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

# 先导入 freeassetfilter.ui.theme：短路径别名 `theme` 由包初始化统一收敛
from freeassetfilter.ui.theme import tm
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss

from freeassetfilter.ui.components.settings_card import SettingsCard
from freeassetfilter.ui.components.styled_button import StyledButton
from freeassetfilter.ui.components.styled_chat_bubble import (
    ChatMessageRow,
    RowSpec,
    StyledChatBubble,
)


def _build_demo_image(width: int = 224, height: int = 120) -> str:
    """生成演示用蓝色渐变占位图（本地绘制，不联网）。

    Args:
        width: 图片宽度（像素）。
        height: 图片高度（像素）。

    Returns:
        生成的 PNG 路径；绘制失败时返回空串。
    """
    target_dir = Path(tempfile.gettempdir()) / "faf_chat_bubble_demo"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"bubble_demo_{width}x{height}.png"
    if path.exists():
        return str(path)

    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    gradient = QLinearGradient(0.0, 0.0, float(width), float(height))
    gradient.setColorAt(0.0, QColor("#2F6FED"))
    gradient.setColorAt(1.0, QColor("#7FD3FF"))
    painter.fillRect(QRectF(0.0, 0.0, float(width), float(height)), gradient)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 255, 255, 40))
    painter.drawEllipse(
        QRectF(width * 0.58, -height * 0.30, width * 0.55, width * 0.55)
    )
    painter.end()
    return str(path) if pixmap.save(str(path), "PNG") else ""


class DemoWindow(QWidget):
    """展示 StyledChatBubble 角色、消息类型、WinUI 规格与流式能力。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """搭建演示界面并订阅主题切换。

        Args:
            parent: 父控件。
        """
        super().__init__(parent)
        self._stream_preview: Optional[StyledChatBubble] = None
        self._stream_timer: Optional[QTimer] = None
        self._stream_index = 0
        self._labels: list[tuple[QLabel, str]] = []
        self._theme_button: Optional[StyledButton] = None
        #: 「向对侧延伸」演示用的消息行，窗口缩放时按视口重算气泡上限。
        self._rows: list[ChatMessageRow] = []
        self._image_path = _build_demo_image()

        self.setWindowTitle("StyledChatBubble 气泡组件 Demo")
        self.resize(820, 780)
        self._setup_ui()
        tm.theme_changed.connect(self._on_theme_changed)

    # ------------------------------------------------------------------
    # 窗口背景与文本配色
    # ------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        """用主题填充色绘制窗口背景。

        Args:
            event: Qt 绘制事件。
        """
        painter = QPainter(self)
        painter.fillRect(self.rect(), tm.fill)
        painter.end()

    def _label(self, text: str, kind: str = "normal") -> QLabel:
        """创建随主题刷新配色的标签。

        Args:
            text: 标签文本。
            kind: ``"title"`` / ``"hint"`` / ``"normal"``。

        Returns:
            已登记主题刷新队列的 QLabel。
        """
        label = QLabel(text)
        self._labels.append((label, kind))
        self._style_label(label, kind)
        return label

    def _style_label(self, label: QLabel, kind: str) -> None:
        """按标签用途写入当前主题下的字号与颜色。

        Args:
            label: 目标标签。
            kind: 标签用途。
        """
        if kind == "title":
            qss = f"font-size: 13px; font-weight: 600; color: {tm.text.name()};"
        elif kind == "hint":
            qss = f"font-size: 12px; color: {tm.alpha_of(tm.mid, 70).name()};"
        else:
            qss = f"font-size: 12px; color: {tm.mid.name()};"
        register_widget_qss(label, qss)

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后刷新窗口背景、文本配色与主题按钮文案。

        Args:
            _theme: 主题名，此处不使用。
        """
        self.update()
        for label, kind in self._labels:
            self._style_label(label, kind)
        if self._theme_button is not None:
            target = "浅色" if tm.is_dark_theme() else "深色"
            self._theme_button.setText(f"切换到{target}模式")

    # ------------------------------------------------------------------
    # 界面搭建
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """按卡片分组搭建全部演示区块。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)
        root.addWidget(self._build_intro())
        root.addWidget(self._build_roles())
        root.addWidget(self._build_content_types())
        root.addWidget(self._build_winui_spec())
        root.addWidget(self._build_cross_side())
        root.addWidget(self._build_streaming())
        root.addWidget(self._build_theme_actions())
        root.addStretch(1)

    def resizeEvent(self, event: object) -> None:
        """窗口缩放时按宽度重算「向对侧延伸」演示气泡的上限。

        Args:
            event: Qt 尺寸变化事件。
        """
        viewport = max(200, self.width() - 120)
        for row in self._rows:
            row.set_max_width(viewport)
        super().resizeEvent(event)  # type: ignore[arg-type]

    def _row_host(self, widget: QWidget, align_left: bool = True) -> QWidget:
        """把行控件放进一行布局，便于对比左右对齐。

        Args:
            widget: 待放置的行控件。
            align_left: True 靠左，False 靠右。

        Returns:
            承载该行的容器控件。
        """
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        if align_left:
            layout.addWidget(widget)
            layout.addStretch(1)
        else:
            layout.addStretch(1)
            layout.addWidget(widget)
        return host

    def _build_intro(self) -> SettingsCard:
        """构建组件简介卡片。

        Returns:
            简介卡片。
        """
        card = SettingsCard()
        card.add_header("StyledChatBubble / ChatMessageRow")
        body = card.add_body()
        body.addWidget(self._label("原子化聊天气泡与消息行组件", "title"))
        body.addWidget(
            self._label(
                "ChatMessageRow 负责角色、头像与左右对齐，RowSpec 负责消息类型；"
                "颜色跟随 ThemeManager。",
                "hint",
            )
        )
        return card

    def _build_roles(self) -> SettingsCard:
        """构建「角色变体」演示卡片。

        Returns:
            角色变体卡片。
        """
        card = SettingsCard()
        card.add_header("角色变体")
        body = card.add_body()
        body.addWidget(self._label("同一消息行可表达不同对话角色。", "hint"))
        role_texts = (
            ("user", "这是用户发送的消息"),
            ("assistant", "这是 AI 助手的回复"),
            ("reasoning", "正在分析问题与上下文"),
            ("system", "系统状态消息"),
            ("tool", "等待工具审批"),
        )
        for role, text in role_texts:
            row = ChatMessageRow(role=role, text=text)
            if role == "user":
                body.addWidget(self._row_host(row, align_left=False))
            else:
                body.addWidget(self._row_host(row, align_left=True))
        return card

    def _build_content_types(self) -> SettingsCard:
        """构建「消息类型」演示卡片。

        Returns:
            消息类型卡片。
        """
        card = SettingsCard()
        card.add_header("消息类型")
        body = card.add_body()
        body.addWidget(
            self._label("文本、图片、文件和输入中状态使用同一个 RowSpec 接口。", "hint")
        )

        text_row = ChatMessageRow(role="assistant", spec=RowSpec.text_of("普通文本消息"))
        body.addWidget(self._row_host(text_row, align_left=True))

        file_row = ChatMessageRow(
            role="user",
            spec=RowSpec.file("设计规范 v2.1.pdf", "1.6 MB", "PDF"),
        )
        body.addWidget(self._row_host(file_row, align_left=False))

        image_host = QWidget()
        image_layout = QHBoxLayout(image_host)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(10)
        if self._image_path:
            image_layout.addWidget(
                ChatMessageRow(role="assistant", spec=RowSpec.image(self._image_path))
            )
        image_layout.addWidget(
            ChatMessageRow(role="assistant", spec=RowSpec.typing())
        )
        image_layout.addStretch(1)
        body.addWidget(image_host)
        return card

    def _build_winui_spec(self) -> SettingsCard:
        """构建「WinUI 3 气泡规格」对比卡片。

        左列是助手白气泡（左下角 4px 收窄），右列是我方强调蓝气泡
        （右下角 4px 收窄），用于肉眼比对气泡圆角与左右对齐差异。

        Returns:
            气泡规格卡片。
        """
        card = SettingsCard()
        card.add_header("WinUI 3 气泡规格")
        body = card.add_body()
        body.addWidget(
            self._label(
                "助手气泡为白底深色文字、左下角 4px 收窄；我方气泡为强调蓝实底、"
                "右下角 4px 收窄，其余三角为常规圆角。",
                "hint",
            )
        )
        body.addWidget(
            self._row_host(ChatMessageRow(role="assistant", text="助手白气泡"), True)
        )
        body.addWidget(
            self._row_host(ChatMessageRow(role="user", text="强调蓝气泡"), False)
        )
        return card

    def _build_cross_side(self) -> SettingsCard:
        """构建「气泡向对侧延伸」演示卡片。

        早期实现两侧都用 stretch，剩余空间被对等分割，气泡最多只能长到自己
        那一半；正确做法是"对侧自适应空白 + 头像侧固定占位"，因此我方靠右的
        气泡可以一直往左延伸，反之亦然——只要能容下对面头像的空档即可。

        Returns:
            交叉延伸演示卡片。
        """
        card = SettingsCard()
        card.add_header("气泡向对侧延伸")
        body = card.add_body()
        body.addWidget(
            self._label(
                "长消息不会被限制在自己那一半：我方气泡靠右但一直延伸到左侧，"
                "只保留对面头像所需的空档；短消息仍保持紧凑，不会被拉满。",
                "hint",
            )
        )
        long_text = (
            "这是一条比较长的消息，用来演示气泡在需要的时候可以一直向对面那一侧"
            "延伸过去，而不是被限制在自己这一半的区域里。"
        )
        for role, text in (("user", long_text), ("assistant", long_text)):
            host = QWidget()
            host_layout = QHBoxLayout(host)
            host_layout.setContentsMargins(0, 4, 0, 0)
            host_layout.setSpacing(0)
            row = ChatMessageRow(role=role, text=text)
            self._rows.append(row)
            host_layout.addWidget(row)
            body.addWidget(host)
        body.addWidget(
            self._label("短消息对照（紧凑，不拉满）：", "hint")
        )
        for role, text in (("user", "哈哈哈"), ("assistant", "OK")):
            host = QWidget()
            host_layout = QHBoxLayout(host)
            host_layout.setContentsMargins(0, 4, 0, 0)
            host_layout.setSpacing(0)
            row = ChatMessageRow(role=role, text=text)
            self._rows.append(row)
            host_layout.addWidget(row)
            body.addWidget(host)
        return card

    def _build_streaming(self) -> SettingsCard:
        """构建「流式追加」演示卡片。

        Returns:
            流式追加卡片。
        """
        card = SettingsCard()
        card.add_header("流式追加")
        body = card.add_body()
        body.addWidget(
            self._label("点击按钮模拟 AI 逐段输出；组件会显示流式光标。", "hint")
        )
        self._stream_preview = StyledChatBubble(
            "assistant", "text", "", parent=self
        )
        self._stream_preview.set_streaming(True)
        row = QHBoxLayout()
        row.setContentsMargins(0, 8, 0, 0)
        row.addWidget(self._stream_preview)
        row.addStretch(1)
        body.addLayout(row)
        self._stream_button = StyledButton("开始流式演示", variant="primary", size="sm")
        self._stream_button.clicked.connect(self._start_stream)
        body.addWidget(self._stream_button, 0, Qt.AlignLeft)
        return card

    def _build_theme_actions(self) -> QWidget:
        """构建主题切换与清空操作区。

        Returns:
            操作区容器。
        """
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self._theme_button = StyledButton("切换主题", variant="secondary", size="sm")
        self._theme_button.clicked.connect(tm.toggle_theme)
        clear = StyledButton("清空流式内容", variant="ghost", size="sm")
        clear.clicked.connect(self._clear_stream)
        row.addWidget(self._theme_button)
        row.addWidget(clear)
        row.addStretch(1)
        return host

    # ------------------------------------------------------------------
    # 交互回调
    # ------------------------------------------------------------------

    def _start_stream(self) -> None:
        """开始逐段输出演示文本。"""
        if self._stream_timer is not None and self._stream_timer.isActive():
            return
        self._stream_preview.set_text("")
        self._stream_preview.set_streaming(True)
        self._stream_index = 0
        self._stream_button.setEnabled(False)
        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(90)
        self._stream_timer.timeout.connect(self._append_stream_chunk)
        self._stream_timer.start()

    def _append_stream_chunk(self) -> None:
        """追加一段流式文本；输出完毕恢复按钮。"""
        chunks = [
            "这是一段 ",
            "逐步输出的 ",
            "AI 回复内容，",
            "用于验证流式布局、",
            "光标状态与主题适配。",
        ]
        timer = self._stream_timer
        if self._stream_index >= len(chunks):
            if timer is not None:
                timer.stop()
            self._stream_preview.set_streaming(False)
            self._stream_button.setEnabled(True)
            return
        self._stream_preview.append_text(chunks[self._stream_index])
        self._stream_index += 1

    def _clear_stream(self) -> None:
        """清空流式演示文本。"""
        self._stream_preview.set_text("")


def main() -> int:
    """演示入口。

    Returns:
        应用退出码。
    """
    app = QApplication(sys.argv)
    app.setApplicationName("StyledChatBubble Demo")
    window = DemoWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
