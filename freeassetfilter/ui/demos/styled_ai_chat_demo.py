# -*- coding: utf-8 -*-
"""WinUI 3 方向 AI 对话 Demo（单列、无侧边栏）。

运行（仓库根目录）：

    python -m freeassetfilter.ui.demos.styled_ai_chat_demo

本 Demo 只负责把 :class:`StyledAIChatWindow` 装进一个独立窗口，并接入欢迎态、
建议卡片、模型切换、附件 Flyout、本地模拟回复与停止。所有颜色 / 字体 / 控件
样式均来自 ``tm`` 与 ``freeassetfilter/ui/components/`` 下的 styled 组件。

静态消息覆盖文本、图片、文件、typing 四种类型；图片为 QPainter 本地生成的
占位图，不联网。
"""

from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

# 直接以脚本方式执行时把仓库根目录加入 sys.path，保证绝对导入可用
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QVBoxLayout,
    QWidget,
)

from freeassetfilter.ui.components.styled_ai_chat import StyledAIChatWindow
from freeassetfilter.ui.components.styled_chat_bubble import (
    ChatMessageRow,
    RowSpec,
    window_fill_color,
)
from freeassetfilter.ui.components.styled_context_menu import StyledContextMenu
from freeassetfilter.ui.frameless_window import FramelessMainWindow
from freeassetfilter.ui.theme import tm
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss

#: 应用标题。
APP_TITLE = "FreeAsset AI"
#: 当前会话标题。
CONVERSATION_TITLE = "设计素材归档"
#: 窗口尺寸（布局尺寸，不是视觉令牌）。
WINDOW_SIZE = (900, 780)
#: 窗口最小尺寸。
MINIMUM_SIZE = (720, 600)
#: 居中时间胶囊文案。
TIME_LABEL = "今天 14:30"
#: 初始问候语（测试依赖该常量）。
GREETING_TEXT = "你好呀，可以给我发送文字、图片或文件试试，我会自动回复你。"
#: 我方文本。
USER_TEXT = "好，那我先发一条文字消息。"
#: 我方最后一条短文本。
USER_FINAL_TEXT = "哈哈哈"
#: 原型中位于滚动区下方的补充消息。
TRAILING_REPLY_TEXT = "图片和文件都收到了，样式看起来挺清晰的。"
TRAILING_USER_TEXT = "OK，测试完成～"
#: 图片气泡占位图尺寸。
PLACEHOLDER_SIZE = (320, 200)
#: 占位图缓存目录名。
PLACEHOLDER_DIR_NAME = "faf_chat_demo"
#: 可选模型列表。
MODEL_OPTIONS: tuple[str, ...] = ("FreeAsset-Seed", "FreeAsset-Mini", "本地模型")
#: 对方随机回复文本池。
REPLY_TEXT_POOL: tuple[str, ...] = (
    "收到，我看到了你的消息。",
    "这条回复完全来自本地模拟，没有调用任何网络服务。",
    "文字、图片、文件三种气泡现在都支持了。",
    "你可以继续发送消息，我会随机回复不同类型的内容。",
    "好的，还有什么想测试的？",
)
#: 对方随机回复文件池：(文件名, 大小文案, 扩展名角标)。
REPLY_FILE_POOL: tuple[tuple[str, str, str], ...] = (
    ("需求说明书 v1.3.docx", "248 KB", "DOCX"),
    ("数据统计表.xlsx", "76 KB", "XLSX"),
    ("项目排期.pptx", "2.4 MB", "PPTX"),
    ("会议纪要.txt", "12 KB", "TXT"),
)
#: 我方通过附件 Flyout 发送文件时使用的文件池。
USER_FILE_POOL: tuple[tuple[str, str, str], ...] = (
    ("界面切图.zip", "5.2 MB", "ZIP"),
    ("测试用例.xlsx", "184 KB", "XLSX"),
    ("演示文稿.pptx", "3.1 MB", "PPTX"),
)


def _placeholder_palette(variant: int) -> tuple[QColor, QColor]:
    """返回占位图渐变的首尾颜色（来自主题强调色）。

    Args:
        variant: 配色序号（自动对 3 取模）。

    Returns:
        渐变起止色 ``(start, end)``。
    """
    base = QColor(tm.accent)
    variants = (
        (base.lighter(128), base.lighter(172)),
        (base.lighter(112), base.lighter(150)),
        (base.lighter(140), base.lighter(185)),
    )
    return variants[variant % len(variants)]


def placeholder_directory() -> Path:
    """返回占位图缓存目录。

    Returns:
        系统临时目录下的固定子目录。
    """
    return Path(tempfile.gettempdir()) / PLACEHOLDER_DIR_NAME


def build_placeholder_image(
    width: int = PLACEHOLDER_SIZE[0],
    height: int = PLACEHOLDER_SIZE[1],
    *,
    variant: int = 0,
    directory: Optional[Path] = None,
) -> str:
    """生成主题色渐变占位图并落盘为 PNG。

    Args:
        width: 图片宽度。
        height: 图片高度。
        variant: 配色序号。
        directory: 输出目录；None 时使用 :func:`placeholder_directory`。

    Returns:
        PNG 绝对路径。
    """
    target_dir = directory if directory is not None else placeholder_directory()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"chat_placeholder_{width}x{height}_{variant}.png"
    if path.exists():
        return str(path)

    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    start, end = _placeholder_palette(variant)
    gradient = QLinearGradient(0.0, 0.0, float(width), float(height))
    gradient.setColorAt(0.0, start)
    gradient.setColorAt(1.0, end)
    painter.fillRect(QRectF(0.0, 0.0, float(width), float(height)), gradient)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 255, 255, 38))
    painter.drawEllipse(
        QRectF(width * 0.58, -height * 0.22, width * 0.58, width * 0.58)
    )
    mountain = QPainterPath()
    mountain.moveTo(0.0, float(height))
    mountain.lineTo(width * 0.30, height * 0.46)
    mountain.lineTo(width * 0.52, height * 0.72)
    mountain.lineTo(width * 0.72, height * 0.38)
    mountain.lineTo(float(width), height * 0.78)
    mountain.lineTo(float(width), float(height))
    mountain.closeSubpath()
    painter.setBrush(QColor(255, 255, 255, 46))
    painter.drawPath(mountain)
    painter.end()

    pixmap.save(str(path), "PNG")
    return str(path)


def _build_menu_icon(kind: str, size: int = 16) -> QIcon:
    """绘制 Flyout 菜单项左侧图标。

    Args:
        kind: ``"image"`` 或 ``"file"``。
        size: 图标边长。

    Returns:
        QIcon。
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    color = QColor(tm.accent)
    pen = QPen(color)
    pen.setWidthF(1.35)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    if kind == "file":
        page = QPainterPath()
        page.moveTo(2.5, 1.5)
        page.lineTo(9.5, 1.5)
        page.lineTo(13.5, 5.5)
        page.lineTo(13.5, 14.5)
        page.lineTo(2.5, 14.5)
        page.closeSubpath()
        painter.drawPath(page)
        painter.drawLine(QPointF(9.5, 1.5), QPointF(9.5, 5.5))
        painter.drawLine(QPointF(9.5, 5.5), QPointF(13.5, 5.5))
        painter.drawLine(QPointF(5.0, 9.0), QPointF(11.0, 9.0))
        painter.drawLine(QPointF(5.0, 11.5), QPointF(9.5, 11.5))
    else:
        painter.drawRoundedRect(QRectF(1.5, 2.5, 13.0, 11.0), 2.0, 2.0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(5.2, 6.2), 1.3, 1.3)
        painter.setPen(pen)
        mountain = QPainterPath()
        mountain.moveTo(2.6, 12.2)
        mountain.lineTo(6.4, 8.2)
        mountain.lineTo(9.2, 11.0)
        mountain.lineTo(11.4, 9.0)
        mountain.lineTo(13.8, 12.2)
        painter.drawPath(mountain)

    painter.end()
    return QIcon(pixmap)


def _flyout_qss() -> str:
    """返回 Flyout 菜单样式片段（颜色来自 tm）。

    Returns:
        QSS 文本。
    """
    background = tm.qss_color(tm.card_fill)
    text_color = tm.qss_color(tm.text)
    border = tm.qss_color(tm.card_border)
    hover = tm.qss_color(tm.hover_veil)
    disabled = tm.qss_color(tm.text_disabled)
    return (
        "StyledContextMenu {"
        f" background-color: {background};"
        f" color: {text_color};"
        f" border: 1px solid {border};"
        " border-radius: 8px;"
        " padding: 4px;"
        "}"
        "StyledContextMenu::item {"
        " height: 34px;"
        " padding-left: 10px;"
        " padding-right: 20px;"
        " border-radius: 4px;"
        "}"
        "StyledContextMenu::item:selected {"
        f" background-color: {hover};"
        "}"
        "StyledContextMenu::item:disabled {"
        f" color: {disabled};"
        "}"
    )


class DemoWindow(FramelessMainWindow):
    """WinUI 3 方向对话 Demo 窗口。

    Args:
        parent: 父控件。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rng = random.Random(20261014)
        self._typing_row: Optional[QWidget] = None
        self._flyout: Optional[StyledContextMenu] = None
        self._image_cache: dict[int, str] = {}

        self._reply_timer = QTimer(self)
        self._reply_timer.setSingleShot(True)
        self._reply_timer.timeout.connect(self._deliver_reply)

        self.setWindowTitle(f"{APP_TITLE} — 对话 Demo")
        self.resize(*WINDOW_SIZE)
        self.setMinimumSize(*MINIMUM_SIZE)
        self._setup_ui()
        self._populate_static_messages()
        tm.theme_changed.connect(self._on_theme_changed)

    # ------------------------------------------------------------------
    # 对外只读属性
    # ------------------------------------------------------------------

    @property
    def chat(self) -> StyledAIChatWindow:
        """返回内嵌的对话容器。

        Returns:
            当前窗口内的 :class:`StyledAIChatWindow` 实例。
        """
        return self._chat

    # ------------------------------------------------------------------
    # 界面搭建
    # ------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        """填充窗口底色。

        Args:
            event: Qt 绘制事件。
        """
        painter = QPainter(self)
        painter.fillRect(self.rect(), window_fill_color())
        painter.end()

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后重绘窗口底。

        Args:
            _theme: 主题名（未使用）。
        """
        self.update()

    def _setup_ui(self) -> None:
        """创建对话容器并接线信号。"""
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._chat = StyledAIChatWindow(
            central,
            title=CONVERSATION_TITLE,
            models=list(MODEL_OPTIONS),
            model=MODEL_OPTIONS[0],
        )
        layout.addWidget(self._chat)
        self.setCentralWidget(central)

        self._chat.send_requested.connect(self._on_send_requested)
        self._chat.stop_requested.connect(self._on_stop_requested)
        self._chat.attach_requested.connect(self._open_flyout)
        self._chat.more_requested.connect(self._open_more_menu)
        self._chat.minimize_requested.connect(self.showMinimized)
        self._chat.maximize_requested.connect(self._toggle_maximized)
        self._chat.close_requested.connect(self.close)
        self._chat.header.set_status("在线", True)

    def _toggle_maximized(self) -> None:
        """最大化 / 还原窗口。"""
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    # ------------------------------------------------------------------
    # 静态消息清单
    # ------------------------------------------------------------------

    def _populate_static_messages(self) -> None:
        """按原型静态内容填充消息区。"""
        messages = self._chat.messages
        messages.add_time_label(TIME_LABEL)
        messages.add_message("assistant", GREETING_TEXT)
        messages.add_message("user", USER_TEXT)
        self._add_row(RowSpec.image(self._placeholder_path(0)), "assistant")
        self._add_row(RowSpec.file("设计规范 v2.1.pdf", "1.6 MB", "PDF"), "user")
        self._add_row(RowSpec.file("接口文档.docx", "892 KB", "DOCX"), "assistant")
        messages.add_message("user", USER_FINAL_TEXT)
        messages.add_message("assistant", TRAILING_REPLY_TEXT)
        messages.add_message("user", TRAILING_USER_TEXT)
        self._chat.show_welcome(False)
        self.scroll_to_top()

    def scroll_to_top(self) -> None:
        """把消息区滚回顶部。"""
        scrollbar = self._chat.messages.verticalScrollBar()
        scrollbar.setValue(scrollbar.minimum())

    def _placeholder_path(self, variant: int) -> str:
        """按需生成并缓存占位图路径。

        Args:
            variant: 配色序号。

        Returns:
            PNG 路径。
        """
        if variant not in self._image_cache:
            self._image_cache[variant] = build_placeholder_image(variant=variant)
        return self._image_cache[variant]

    def _add_row(self, spec: RowSpec, role: str = "assistant") -> ChatMessageRow:
        """向消息区追加一条非文本消息行。

        Args:
            spec: 行规格。
            role: 消息角色。

        Returns:
            新追加的行控件。
        """
        self._chat.show_welcome(False)
        return self._chat.messages.add_row(spec, role=role)

    def _remove_row(self, row: Optional[QWidget]) -> None:
        """从消息区移除一条消息行。

        Args:
            row: 待移除的行；None 时直接返回。
        """
        if row is None:
            return
        self._chat.messages.remove_row(row)

    # ------------------------------------------------------------------
    # 本地模拟对话
    # ------------------------------------------------------------------

    def _on_send_requested(self, text: str) -> None:
        """发送文本并启动模拟回复。

        Args:
            text: 输入文本。
        """
        content = (text or "").strip()
        if not content:
            return
        self._chat.messages.add_message("user", content)
        self._start_reply_flow()

    def _start_reply_flow(self) -> None:
        """显示 typing 并禁用发送，延迟追加回复。"""
        self._chat.set_busy(True)
        self._chat.header.set_status("正在输入…", True)
        self._remove_row(self._typing_row)
        self._typing_row = self._add_row(RowSpec.typing(), "assistant")
        self._chat.messages.scroll_to_bottom()
        self._reply_timer.start(self._rng.randint(800, 1500))

    def _deliver_reply(self) -> None:
        """移除 typing 并追加随机回复。"""
        self._remove_row(self._typing_row)
        self._typing_row = None

        roll = self._rng.random()
        if roll < 0.18:
            spec = RowSpec.image(self._placeholder_path(self._rng.randrange(3)))
            self._add_row(spec, "assistant")
        elif roll < 0.18 + 0.16:
            name, size, extension = self._rng.choice(REPLY_FILE_POOL)
            self._add_row(RowSpec.file(name, size, extension), "assistant")
        else:
            self._chat.messages.add_message(
                "assistant", self._rng.choice(REPLY_TEXT_POOL)
            )
        self._chat.messages.scroll_to_bottom()
        self._chat.set_busy(False)
        self._chat.header.set_status("在线", True)

    def _on_stop_requested(self) -> None:
        """停止本轮模拟回复。"""
        self._reply_timer.stop()
        self._remove_row(self._typing_row)
        self._typing_row = None
        self._chat.set_busy(False)
        self._chat.header.set_status("已停止", False)

    # ------------------------------------------------------------------
    # Flyout / 更多菜单
    # ------------------------------------------------------------------

    def _on_user_image(self) -> None:
        """附件菜单「发送图片」。"""
        spec = RowSpec.image(self._placeholder_path(self._rng.randrange(3)))
        self._add_row(spec, "user")
        self._start_reply_flow()

    def _on_user_file(self) -> None:
        """附件菜单「发送文件」。"""
        name, size, extension = self._rng.choice(USER_FILE_POOL)
        self._add_row(RowSpec.file(name, size, extension), "user")
        self._start_reply_flow()

    def _flyout_position(self, menu: StyledContextMenu) -> QPoint:
        """计算附件菜单弹出位置。

        Args:
            menu: 菜单实例。

        Returns:
            全局坐标。
        """
        origin = self._chat.composer.mapToGlobal(QPoint(0, 0))
        height = menu.sizeHint().height()
        return QPoint(origin.x() + 18, max(0, origin.y() - height - 6))

    def build_flyout_menu(self) -> StyledContextMenu:
        """构建附件菜单（不弹出）。

        Returns:
            已配置样式的菜单实例。
        """
        menu = StyledContextMenu(parent=self)
        menu.add_item("发送图片", callback=self._on_user_image).setIcon(
            _build_menu_icon("image")
        )
        menu.add_item("发送文件", callback=self._on_user_file).setIcon(
            _build_menu_icon("file")
        )
        register_widget_qss(menu, _flyout_qss())

        shadow = QGraphicsDropShadowEffect(menu)
        shadow.setBlurRadius(24.0)
        shadow.setOffset(0.0, 8.0)
        shadow.setColor(QColor(0, 0, 0, 36))
        menu.setGraphicsEffect(shadow)
        return menu

    def _open_flyout(self) -> None:
        """弹出附件菜单。"""
        menu = self.build_flyout_menu()
        self._flyout = menu
        menu.exec(self._flyout_position(menu))

    def _open_more_menu(self) -> None:
        """弹出会话头更多菜单。"""
        menu = StyledContextMenu(parent=self)
        menu.add_item("清空会话", callback=self._clear_conversation)
        menu.add_item("切换主题", callback=self._toggle_theme)
        register_widget_qss(menu, _flyout_qss())
        menu.exec(self.mapToGlobal(self.rect().center()))

    def _clear_conversation(self) -> None:
        """清空消息并回到欢迎态。"""
        self._reply_timer.stop()
        self._typing_row = None
        self._chat.clear_conversation()

    def _toggle_theme(self) -> None:
        """在浅色 / 深色之间切换。"""
        tm.set_theme("light" if tm.is_dark_theme() else "dark")


def main() -> int:
    """Demo 独立入口。

    Returns:
        应用退出码。
    """
    app = QApplication(sys.argv)
    app.setApplicationName("FreeAsset AI Chat Demo")
    window = DemoWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
