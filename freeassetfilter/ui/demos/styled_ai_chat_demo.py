# -*- coding: utf-8 -*-
"""WinUI 3 风格对话 Demo —— 多类型消息 + 本地模拟回复。

运行（仓库根目录）：

    python -m freeassetfilter.ui.demos.styled_ai_chat_demo

演示内容（逐条对齐用户给定的 HTML 静态内容）：

1. 居中时间胶囊「今天 14:30」；
2. 对方文本「你好呀，可以给我发送文字、图片或文件试试，我会自动回复你。」；
3. 我方文本「好，那我先发一条文字消息。」；
4. 对方图片气泡（QPainter 现场生成的蓝色渐变占位图，不联网）；
5. 我方文件气泡「设计规范 v2.1.pdf / 1.6 MB / PDF」；
6. 对方文件气泡「接口文档.docx / 892 KB / DOCX」；
7. 我方文本「哈哈哈」。

交互（对齐 HTML 脚本）：回车或「发送」→ 我方文本气泡 → 禁用发送 →
对方 typing 气泡 → 800~1500ms 后移除 typing 并追加随机回复
（约 18% 图片 / 16% 文件 / 其余文本）→ 恢复发送。「+」按钮弹出
Flyout 菜单（发送图片 / 发送文件），点击外部自动关闭。

所有样式一律经 ``register_widget_qss`` 注册，禁止逐控件直写样式表。
"""

from __future__ import annotations

import inspect
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

# 先导入 freeassetfilter.ui.theme：短路径别名 `theme` 由包初始化统一收敛
from freeassetfilter.ui.theme import tm
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss

from freeassetfilter.ui.components.styled_ai_chat import StyledAIChatWindow
from freeassetfilter.ui.components.styled_chat_bubble import ChatMessageRow, RowSpec
from freeassetfilter.ui.components.styled_context_menu import StyledContextMenu

#: 窗口标题（与 task-2 冻结文案一致）。
WINDOW_TITLE = "对话 Demo — WinUI 3 · 多类型消息"

#: 初始尺寸：用户 HTML 为 518×779，这里取等比近似值 520×780。
WINDOW_SIZE = (520, 780)

#: 居中时间胶囊文案。
TIME_LABEL = "今天 14:30"

#: 静态消息清单中的三条文本。
GREETING_TEXT = "你好呀，可以给我发送文字、图片或文件试试，我会自动回复你。"
USER_TEXT = "好，那我先发一条文字消息。"
USER_FINAL_TEXT = "哈哈哈"

#: HTML 原型里位于滚动区下方（目标截图不可见）的两条消息：补齐后滚动区
#: 内容高度与原型一致，滚动条滑块比例因此与目标截图相同。
TRAILING_REPLY_TEXT = "图片和文件都收到了，样式看起来挺清晰的。"
TRAILING_USER_TEXT = "OK，测试完成～"

#: 静态图片气泡的占位图尺寸（对齐 HTML 的 320×200）。
PLACEHOLDER_SIZE = (320, 200)

#: 占位图缓存目录名（系统临时目录下，避免污染仓库）。
PLACEHOLDER_DIR_NAME = "faf_chat_demo"

#: 对方随机回复的文本池。
REPLY_TEXT_POOL: tuple[str, ...] = (
    "收到，我看到了你的消息。",
    "这条回复完全来自本地模拟，没有调用任何网络服务。",
    "文字、图片、文件三种气泡现在都支持了。",
    "你可以继续发送消息，我会随机回复不同类型的内容。",
    "好的，还有什么想测试的？",
)

#: 对方随机回复的文件池：(文件名, 大小文案, 扩展名角标)。
REPLY_FILE_POOL: tuple[tuple[str, str, str], ...] = (
    ("需求说明书 v1.3.docx", "248 KB", "DOCX"),
    ("数据统计表.xlsx", "76 KB", "XLSX"),
    ("项目排期.pptx", "2.4 MB", "PPTX"),
    ("会议纪要.txt", "12 KB", "TXT"),
)

#: 我方通过 Flyout 发送文件时使用的文件池。
USER_FILE_POOL: tuple[tuple[str, str, str], ...] = (
    ("界面切图.zip", "5.2 MB", "ZIP"),
    ("测试用例.xlsx", "184 KB", "XLSX"),
    ("演示文稿.pptx", "3.1 MB", "PPTX"),
)


def _placeholder_palette(variant: int) -> tuple[QColor, QColor]:
    """返回占位图渐变的首尾颜色。

    固定 3 套蓝色配色，保证多次截图结果稳定（不使用随机色）。

    Args:
        variant: 配色序号（自动对 3 取模）。

    Returns:
        渐变起止色 ``(start, end)``。
    """
    palettes: tuple[tuple[str, str], ...] = (
        ("#2F6FED", "#6FB6FF"),
        ("#1E5FD8", "#4FC3F7"),
        ("#3A7BD5", "#7FD3FF"),
    )
    start_hex, end_hex = palettes[variant % len(palettes)]
    return QColor(start_hex), QColor(end_hex)


def placeholder_directory() -> Path:
    """返回占位图缓存目录（系统临时目录下的固定子目录）。

    Returns:
        占位图目录路径（不保证已存在）。
    """
    return Path(tempfile.gettempdir()) / PLACEHOLDER_DIR_NAME


def build_placeholder_image(
    width: int = PLACEHOLDER_SIZE[0],
    height: int = PLACEHOLDER_SIZE[1],
    *,
    variant: int = 0,
    directory: Optional[Path] = None,
) -> str:
    """用 QPainter 生成蓝色渐变占位图并落盘为 PNG。

    占位图内容为「蓝色线性渐变 + 白色半透明圆形 + 白色半透明山形」，
    与用户 HTML 里的示例图一致；全程本地绘制，不访问网络。

    Args:
        width: 图片宽度（像素）。
        height: 图片高度（像素）。
        variant: 配色序号，用于让多次回复的图片略有差异。
        directory: 输出目录；``None`` 时使用 :func:`placeholder_directory`。

    Returns:
        生成的 PNG 绝对路径，可直接传给 ``RowSpec.image(path)``。
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

    # 右上角白色半透明圆形（超出画布的部分由裁剪自动截断）
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 255, 255, 38))
    painter.drawEllipse(
        QRectF(width * 0.58, -height * 0.22, width * 0.58, width * 0.58)
    )
    # 底部白色半透明山形
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
    """绘制 Flyout 菜单项左侧的强调色图标。

    Args:
        kind: ``"image"``（图片图标）或 ``"file"``（文档图标）。
        size: 图标边长（像素），默认 16。

    Returns:
        可直接交给 ``QAction.setIcon`` 的图标。
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
        # 带折角的文档轮廓 + 两条内容线
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
        # 圆角相框 + 太阳圆点 + 山形
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
    """返回 Flyout 菜单的样式片段（按当前主题取色）。

    Returns:
        WinUI 3 Flyout 规格的 QSS：白底、圆角 8、描边 rgba(0,0,0,0.0578)、
        菜单项高 36、悬停 rgba(0,0,0,0.05)。
    """
    if tm.is_dark_theme():
        background = tm.qss_color(tm.alpha_of(tm.surface, 96))
        text_color = tm.text.name()
        border = "rgba(255,255,255,0.09)"
        hover = "rgba(255,255,255,0.06)"
        disabled = "rgba(255,255,255,0.36)"
    else:
        background = "#ffffff"
        text_color = tm.text.name()
        border = "rgba(0,0,0,0.0578)"
        hover = "rgba(0,0,0,0.05)"
        disabled = "rgba(0,0,0,0.36)"
    return (
        "StyledContextMenu {"
        f" background-color: {background};"
        f" color: {text_color};"
        f" border: 1px solid {border};"
        " border-radius: 8px;"
        " padding: 4px;"
        "}"
        "StyledContextMenu::item {"
        " height: 36px;"
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


def _accepts_role(callable_obj: Callable[..., object]) -> bool:
    """判断可调用对象是否接受 ``role`` 关键字参数。

    ``StyledAIMessageList.add_row`` 的冻结签名是 ``add_row(spec)``，
    对话 Demo 需要按角色区分左右对齐，故运行时探测容器是否提供了
    向后兼容的 ``role`` 关键字；缺失时退化为自建 ``ChatMessageRow``。

    Args:
        callable_obj: 待探测的可调用对象。

    Returns:
        True 表示可以安全地以 ``role=`` 关键字调用。
    """
    try:
        parameters = inspect.signature(callable_obj).parameters
    except (TypeError, ValueError):
        return False
    if "role" in parameters:
        return True
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )


class DemoWindow(QWidget):
    """WinUI 3 对话 Demo 窗口。

    窗口内只有一个 :class:`StyledAIChatWindow`（零边距铺满），静态消息
    按 HTML 清单逐条填充；输入栏发送后走本地模拟回复流程，不访问网络。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """搭建窗口并填充静态消息。

        Args:
            parent: 父控件（顶层窗口时为 ``None``）。
        """
        super().__init__(parent)
        self._rng = random.Random(20261014)
        self._typing_row: Optional[QWidget] = None
        self._flyout: Optional[StyledContextMenu] = None
        self._image_cache: dict[int, str] = {}

        self._reply_timer = QTimer(self)
        self._reply_timer.setSingleShot(True)
        self._reply_timer.timeout.connect(self._deliver_reply)

        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*WINDOW_SIZE)
        self._setup_ui()
        self._populate_static_messages()
        tm.theme_changed.connect(self._on_theme_changed)

    # ------------------------------------------------------------------
    # 对外只读属性
    # ------------------------------------------------------------------

    @property
    def chat(self) -> StyledAIChatWindow:
        """返回内嵌的 WinUI 3 对话容器。

        Returns:
            当前窗口内的 :class:`StyledAIChatWindow` 实例。
        """
        return self._chat

    # ------------------------------------------------------------------
    # 界面搭建
    # ------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        """用主题填充色绘制窗口底色（防止内容区出现缝隙）。

        Args:
            event: Qt 绘制事件。
        """
        painter = QPainter(self)
        painter.fillRect(self.rect(), tm.fill)
        painter.end()

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后重绘窗口底色。

        Args:
            _theme: 主题名（``"light"`` / ``"dark"``），此处不使用。
        """
        self.update()

    def _setup_ui(self) -> None:
        """创建对话容器并接线信号。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._chat = StyledAIChatWindow(self)
        self._chat.set_title(WINDOW_TITLE)
        self._chat.send_requested.connect(self._on_send_requested)
        root.addWidget(self._chat)

        self._connect_attach_button()
        self._row_role_supported = _accepts_role(
            getattr(self._chat.messages, "add_row", None)
        )

    def _connect_attach_button(self) -> None:
        """把输入栏「+」按钮接到 Flyout 菜单。

        优先使用输入栏自身的 ``attach_requested``（task-1 冻结契约）；
        容器未提供时退化为直接响应窗口级图片/文件请求信号。
        """
        composer = getattr(self._chat, "composer", None)
        signal = getattr(composer, "attach_requested", None)
        if signal is None or not hasattr(signal, "connect"):
            signal = getattr(self._chat, "attach_requested", None)
        if signal is not None and hasattr(signal, "connect"):
            signal.connect(self._open_flyout)
            return
        # 无「+」信号时的兜底：窗口级图片/文件请求直接模拟发送
        for name, handler in (
            ("image_requested", self._on_user_image),
            ("file_requested", self._on_user_file),
        ):
            fallback = getattr(self._chat, name, None)
            if fallback is not None and hasattr(fallback, "connect"):
                fallback.connect(handler)

    # ------------------------------------------------------------------
    # 静态消息清单
    # ------------------------------------------------------------------

    def _populate_static_messages(self) -> None:
        """按用户 HTML 的静态内容依次填充消息区。

        末尾两条为 HTML 原型里"被折叠在滚动区下方"的消息（``.chat-body``
        在 747px 视口下需要滚动，目标截图右侧可见 8px 滚动条与位于顶部的
        滑块），补齐后滚动区内容高度与原型一致；填充完停在顶部，与目标
        截图的滚动位置一致。
        """
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
        self.scroll_to_top()

    def scroll_to_top(self) -> None:
        """把消息区滚回顶部（对齐目标截图里位于顶部的滚动条滑块）。"""
        scrollbar = self._chat.messages.verticalScrollBar()
        scrollbar.setValue(scrollbar.minimum())

    def _placeholder_path(self, variant: int) -> str:
        """按需生成并缓存占位图路径。

        Args:
            variant: 配色序号。

        Returns:
            占位图 PNG 路径。
        """
        if variant not in self._image_cache:
            self._image_cache[variant] = build_placeholder_image(variant=variant)
        return self._image_cache[variant]

    def _add_row(self, spec: RowSpec, role: str = "assistant") -> QWidget:
        """向消息区追加一条非文本消息行。

        Args:
            spec: 行规格（图片 / 文件 / typing）。
            role: 消息角色，决定左右对齐与头像。

        Returns:
            追加后的行控件。
        """
        messages = self._chat.messages
        add_row = getattr(messages, "add_row", None)
        if callable(add_row) and getattr(self, "_row_role_supported", False):
            return add_row(spec, role=role)  # type: ignore[no-any-return]
        if callable(add_row):
            return add_row(spec)  # type: ignore[no-any-return]
        row = ChatMessageRow(role=role, spec=spec)
        messages.add_widget(row)
        return row

    def _remove_row(self, row: Optional[QWidget]) -> None:
        """从消息区移除一条已追加的消息行。

        Args:
            row: 待移除的行控件；``None`` 时直接返回。
        """
        if row is None:
            return
        messages = self._chat.messages
        remove_row = getattr(messages, "remove_row", None)
        if callable(remove_row):
            remove_row(row)
            return
        row.setParent(None)
        row.deleteLater()

    # ------------------------------------------------------------------
    # 本地模拟对话
    # ------------------------------------------------------------------

    def _on_send_requested(self, text: str) -> None:
        """回车或点击「发送」：追加我方文本气泡并启动模拟回复。

        Args:
            text: 输入栏提交的文本。
        """
        content = (text or "").strip()
        if not content:
            return
        self._chat.messages.add_message("user", content)
        self._start_reply_flow()

    def _start_reply_flow(self) -> None:
        """统一的「对方正在输入」流程：禁用发送 → typing → 延迟回复 → 恢复。"""
        self._set_composer_enabled(False)
        self._remove_row(self._typing_row)
        self._typing_row = self._add_row(RowSpec.typing(), "assistant")
        self._chat.messages.scroll_to_bottom()
        self._reply_timer.start(self._rng.randint(800, 1500))

    def _deliver_reply(self) -> None:
        """移除 typing 气泡并追加一条随机类型的对方回复。"""
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
        self._set_composer_enabled(True)

    def _set_composer_enabled(self, enabled: bool) -> None:
        """禁用 / 恢复输入栏的发送能力。

        Args:
            enabled: True 恢复发送，False 禁用发送按钮。
        """
        composer = getattr(self._chat, "composer", None)
        setter = getattr(composer, "set_enabled", None)
        if callable(setter):
            setter(enabled)

    # ------------------------------------------------------------------
    # Flyout 菜单
    # ------------------------------------------------------------------

    def _on_user_image(self) -> None:
        """Flyout「发送图片」：以占位图模拟我方发送一张图片。"""
        spec = RowSpec.image(self._placeholder_path(self._rng.randrange(3)))
        self._add_row(spec, "user")
        self._start_reply_flow()

    def _on_user_file(self) -> None:
        """Flyout「发送文件」：以文件气泡模拟我方发送一个文件。"""
        name, size, extension = self._rng.choice(USER_FILE_POOL)
        self._add_row(RowSpec.file(name, size, extension), "user")
        self._start_reply_flow()

    def _flyout_position(self, menu: StyledContextMenu) -> QPoint:
        """计算 Flyout 的弹出位置（输入栏上方左对齐）。

        Args:
            menu: 待弹出的菜单（用于取 sizeHint 高度）。

        Returns:
            全局坐标下的弹出点。
        """
        anchor = getattr(self._chat, "composer", None) or self._chat
        origin = anchor.mapToGlobal(QPoint(0, 0))
        height = menu.sizeHint().height()
        return QPoint(origin.x() + 18, max(0, origin.y() - height - 6))

    def build_flyout_menu(self) -> StyledContextMenu:
        """构建「+」按钮的 Flyout 菜单（不弹出，便于单测与复用）。

        Returns:
            已完成样式注册与投影配置的菜单实例。
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
        """弹出「+」按钮的 Flyout 菜单（点击外部由 QMenu 自动关闭）。"""
        menu = self.build_flyout_menu()
        self._flyout = menu
        menu.exec(self._flyout_position(menu))


def main() -> int:
    """Demo 独立入口：以真实窗口运行本地模拟对话。

    Returns:
        应用退出码。
    """
    app = QApplication(sys.argv)
    app.setApplicationName("StyledAIChat Demo")
    window = DemoWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
