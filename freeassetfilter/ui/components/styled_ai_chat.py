"""WinUI 3 风格的 AI 对话容器组件。

模块把目标设计稿（WinUI 3「对话 Demo · 多类型消息」）拆成四个可独立复用的
容器，气泡本体由 :mod:`freeassetfilter.ui.components.styled_chat_bubble` 提供：

* :class:`StyledAIMessageList` —— 消息区（可滚动行列表，气泡上限按视口 74%）；
* :class:`StyledAIChatHeader` —— 会话头（渐变 AI 头像 + 名称 + 在线状态）；
* :class:`StyledAIChatTitleBar` —— 标题栏（自绘最小化 / 最大化 / 关闭按钮）；
* :class:`StyledChatComposer` —— 底部输入栏（附件 + 输入框 + 发送）；
* :class:`StyledAIChatWindow` —— 上述四件的整窗容器；
* :class:`StyledAIChatPanel` / :class:`StyledAIToolApproval` —— 既有面板与工具
  审批卡片（行为保持不变，气泡换用新的 :class:`ChatMessageRow`）。

设计令牌口径（HTML → 项目 ``tm`` 令牌，深浅主题自动适配）:

===============================  ==========================================
HTML 原型                         本项目表达
===============================  ==========================================
``accent #0078D4``                 ``tm.accent``（不硬编码色值）
卡片 / 控件底 ``#FFFFFF``          ``tm.card_fill``、获焦时 ``tm.surface``
控件描边 ``rgba(0,0,0,0.0578)``    ``tm.alpha_of(tm.text, 6)``
分隔线 ``rgba(0,0,0,0.0803)``      ``tm.alpha_of(tm.text, 8)``
加重的底边 ``rgba(0,0,0,0.10)``    ``tm.alpha_of(tm.text, 10)``
正文 ``#1A1A1A`` / 次要 ``#5D5D5D``  ``tm.text`` / ``tm.text_secondary``
在线圆点 ``#0F7B0F``               ``styled_chat_bubble.ONLINE_COLOR``
控件圆角 4px / 浮层圆角 8px         ``CONTROL_RADIUS`` / 气泡组件内实现
===============================  ==========================================

所有样式一律经 :func:`register_widget_qss` 注册（项目有 fail-closed 单测扫描
全包的逐控件直写样式表调用点），主题切换时重新注册同一控件即可覆盖；
标题栏按钮、AI 头像属于"运行时逐实例绘制"，直接在 ``paintEvent`` / 位图里读取
``tm`` 令牌，因此同样不需要直写样式表。
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from freeassetfilter.ui.components.styled_button import StyledButton
from freeassetfilter.ui.components.styled_chat_bubble import (
    ONLINE_COLOR,
    ChatMessageRow,
    RowSpec,
    StyledChatBubble,
    StyledReasoningDrawer,
    make_ai_avatar_pixmap,
    window_fill_color,
)
from freeassetfilter.ui.components.styled_scroll_area import (
    StyledScrollArea,
    StyledScrollBar,
)
from freeassetfilter.ui.components.styled_textarea import StyledTextarea
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss
from theme import tm

# ---------------------------------------------------------------------------
# 设计常量（对齐 HTML 原型）
# ---------------------------------------------------------------------------

#: 标题栏高度（HTML ``.titlebar`` height 40px）。
TITLE_BAR_HEIGHT = 40
#: 标题栏窗口按钮宽度（HTML 三个按钮各 46px）。
CAPTION_BUTTON_WIDTH = 46
#: 会话头头像直径（HTML ``.chat-header__avatar`` 40px）。
HEADER_AVATAR_SIZE = 40
#: 在线状态圆点直径（HTML ``.status-dot`` 7px）。
STATUS_DOT_SIZE = 7
#: 输入类控件高度（HTML ``height: 34px``）。
CONTROL_HEIGHT = 34
#: 输入类控件圆角（HTML ``--radius-ctrl`` 4px）。
CONTROL_RADIUS = 4
#: 时间胶囊高度（圆角取高度一半即"全圆"）。
TIME_LABEL_HEIGHT = 20
#: 气泡最大宽度占消息区视口的比例（与气泡组件的换算口径一致）。
MESSAGE_WIDTH_RATIO = 0.74
#: 整窗默认标题。
DEFAULT_WINDOW_TITLE = "对话 Demo — WinUI 3 · 多类型消息"


def _hairline(pct: float) -> str:
    """返回"发丝线"颜色的 QSS 文本。

    浅色主题取正文色的低透明度（等价 HTML 的 ``rgba(0,0,0,0.06)`` 一类），
    深色主题下 ``tm.text`` 自动反转为浅色，因此同一条规则在两种主题下都
    是"与底对比的细线"。

    Args:
        pct: 不透明度百分比（0-100）。

    Returns:
        ``rgba(r,g,b,a)`` 形式的 QSS 颜色文本。
    """
    return tm.qss_color(tm.alpha_of(tm.text, pct))


def _control_fill() -> str:
    """返回控件底色的 QSS 文本。

    对应 HTML ``--card-trans: rgba(255,255,255,0.70)``（浅色模式的白底控件）；
    目标截图里输入框实测为纯白 ``#FFFFFF``，因此浅色模式直接给不透明白，
    避免 QSS 半透明底与窗口底叠加后偏灰；深色模式用 ``tm.card_fill`` 表面色，
    不出现发白的控件。

    Returns:
        ``rgba(r,g,b,a)`` 形式的 QSS 颜色文本。
    """
    if tm.is_dark_theme():
        return tm.qss_color(tm.card_fill)
    return tm.qss_color(tm.white)


def _opaque_surface() -> str:
    """返回输入框获焦时的不透明底色 QSS 文本。

    浅色取纯白（HTML 获焦态背景），深色取表面色。

    Returns:
        ``rgba(r,g,b,a)`` 形式的 QSS 颜色文本。
    """
    color = tm.surface if tm.is_dark_theme() else tm.white
    return tm.qss_color(color)


class _ChatCaptionButton(QAbstractButton):
    """标题栏窗口按钮（最小化 / 最大化 / 关闭）。

    自绘原因有两条：``StyledButton`` 的观感是内容按钮而非系统标题栏按钮；
    关闭按钮在两种主题下都使用 Windows 11 的固定红（悬停 ``#C42B1C`` /
    按下 ``#B02318``），无法用主题令牌表达。按下态直接取
    ``QAbstractButton.isDown()``，悬停态用 ``WA_Hover`` 跟踪。

    Args:
        glyph: ``minimize`` / ``maximize`` / ``close``，非法值退化为最小化。
        parent: 父控件。
    """

    #: 关闭按钮悬停底色（Windows 11 标题栏关闭态，两种主题一致）。
    CLOSE_HOVER = QColor("#C42B1C")
    #: 关闭按钮按下底色。
    CLOSE_PRESSED = QColor("#B02318")
    #: 悬停覆盖层不透明度（HTML ``rgba(0,0,0,0.06)``）。
    HOVER_ALPHA = 6
    #: 按下覆盖层不透明度（HTML ``rgba(0,0,0,0.10)``）。
    PRESSED_ALPHA = 10
    #: 线条图标边长（HTML 图标约 10px）。
    GLYPH_SIZE = 10

    def __init__(self, glyph: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._glyph = (
            glyph if glyph in ("minimize", "maximize", "close") else "minimize"
        )
        self._hovered = False
        self.setFixedSize(CAPTION_BUTTON_WIDTH, TITLE_BAR_HEIGHT)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover, True)
        tm.theme_changed.connect(self._on_theme_changed)

    def _background(self) -> Optional[QColor]:
        """返回当前状态下的底色。

        Returns:
            关闭按钮为固定红覆盖层，其余按钮为正文色的低透明度覆盖层；
            既未悬停也未按下时返回 None（完全透明）。
        """
        pressed = self.isDown()
        if not pressed and not self._hovered:
            return None
        if self._glyph == "close":
            return self.CLOSE_PRESSED if pressed else self.CLOSE_HOVER
        pct = self.PRESSED_ALPHA if pressed else self.HOVER_ALPHA
        return tm.alpha_of(tm.text, pct)

    def _ink(self) -> QColor:
        """返回当前状态下的线条颜色。

        Returns:
            关闭按钮在悬停 / 按下时为白色，其余为主题正文色。
        """
        if self._glyph == "close" and (self._hovered or self.isDown()):
            return tm.white
        return tm.text

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制底色与线条图标。

        Args:
            event: Qt 绘制事件。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        background = self._background()
        if background is not None:
            painter.fillRect(self.rect(), background)

        pen = QPen(self._ink())
        pen.setWidthF(1.0)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        center_x = self.width() / 2.0
        center_y = self.height() / 2.0
        half = self.GLYPH_SIZE / 2.0
        if self._glyph == "minimize":
            # 横线取 0.5 像素偏移：1px 线落在像素中心，不被抗锯齿糊成两像素
            painter.drawLine(
                QPointF(center_x - half, center_y + 0.5),
                QPointF(center_x + half, center_y + 0.5),
            )
        elif self._glyph == "maximize":
            painter.drawRect(
                QRectF(
                    center_x - half + 0.5,
                    center_y - half + 0.5,
                    float(self.GLYPH_SIZE),
                    float(self.GLYPH_SIZE),
                )
            )
        else:
            painter.drawLine(
                QPointF(center_x - half, center_y - half),
                QPointF(center_x + half, center_y + half),
            )
            painter.drawLine(
                QPointF(center_x - half, center_y + half),
                QPointF(center_x + half, center_y - half),
            )
        painter.end()

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后重绘（颜色在绘制时取 ``tm`` 令牌）。

        Args:
            _theme: 新主题名（未使用）。
        """
        self.update()

    def enterEvent(self, event: object) -> None:
        """悬停进入：记录状态并重绘。

        Args:
            event: Qt 进入事件。
        """
        self._hovered = True
        self.update()
        super().enterEvent(event)  # type: ignore[arg-type]

    def leaveEvent(self, event: object) -> None:
        """悬停离开：记录状态并重绘。

        Args:
            event: Qt 离开事件。
        """
        self._hovered = False
        self.update()
        super().leaveEvent(event)  # type: ignore[arg-type]


class StyledAIChatTitleBar(QWidget):
    """对话窗口标题栏。

    高 40px：左侧 16px AI 图标 + 12px 标题（次要文字色），右侧三个 46px 宽的
    自绘按钮（最小化 —、最大化 □、关闭 ✕）。标题栏自身不操作宿主窗口，只发出
    请求信号，由宿主决定如何响应（便于嵌进无边框主窗口或普通窗口）。

    Args:
        title: 标题文案。
        parent: 父控件。

    Signals:
        minimize_requested: 请求最小化宿主窗口。
        maximize_requested: 请求最大化 / 还原宿主窗口。
        close_requested: 请求关闭宿主窗口。
    """

    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()

    def __init__(self, title: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("StyledAIChatTitleBar")
        self.setFixedHeight(TITLE_BAR_HEIGHT)

        self._icon = QLabel(self)
        self._icon.setFixedSize(16, 16)
        self._icon.setPixmap(make_ai_avatar_pixmap(16))
        self._icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._title = QLabel(title, self)
        self._title.setObjectName("StyledAIChatTitleBarTitle")

        self._minimize = _ChatCaptionButton("minimize", self)
        self._maximize = _ChatCaptionButton("maximize", self)
        self._close = _ChatCaptionButton("close", self)
        self._minimize.setToolTip("最小化")
        self._maximize.setToolTip("最大化")
        self._close.setToolTip("关闭")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._icon, 0, Qt.AlignVCenter)
        layout.addWidget(self._title, 0, Qt.AlignVCenter)
        layout.addStretch(1)
        layout.addWidget(self._minimize)
        layout.addWidget(self._maximize)
        layout.addWidget(self._close)

        self._minimize.clicked.connect(lambda: self.minimize_requested.emit())
        self._maximize.clicked.connect(lambda: self.maximize_requested.emit())
        self._close.clicked.connect(lambda: self.close_requested.emit())

        tm.theme_changed.connect(self._on_theme_changed)
        self._apply_qss()

    def title(self) -> str:
        """返回当前标题文案。

        Returns:
            标题栏文本。
        """
        return self._title.text()

    def set_title(self, title: str) -> None:
        """设置标题文案。

        Args:
            title: 新标题。
        """
        self._title.setText(title)

    def _apply_qss(self) -> None:
        """注册标题栏样式片段（透明底 + 次要色小标题）。"""
        register_widget_qss(
            self,
            f"""
            StyledAIChatTitleBar {{ background: transparent; }}
            #StyledAIChatTitleBarTitle {{
                color: {tm.qss_color(tm.text_secondary)};
                font-size: 12px;
            }}
            """,
        )

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后重建图标位图并重新注册样式。

        Args:
            _theme: 新主题名（未使用）。
        """
        self._icon.setPixmap(make_ai_avatar_pixmap(16))
        self._apply_qss()


class StyledAIChatHeader(QWidget):
    """会话头：40px 渐变 AI 头像 + 名称 + 在线状态。

    行内间距 12px、内边距 ``8px 18px 14px``（对齐 HTML ``.chat-header``）。

    Args:
        name: 会话名（默认"智能助手"）。
        status: 初始状态文案（默认"在线"）。
        parent: 父控件。
    """

    def __init__(
        self,
        name: str = "智能助手",
        status: str = "在线",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("StyledAIChatHeader")
        self._online = True

        self._avatar = QLabel(self)
        self._avatar.setFixedSize(HEADER_AVATAR_SIZE, HEADER_AVATAR_SIZE)
        self._avatar.setPixmap(make_ai_avatar_pixmap(HEADER_AVATAR_SIZE))
        self._avatar.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._name = QLabel(name, self)
        self._name.setObjectName("StyledAIChatHeaderName")
        self._dot = QLabel(self)
        self._dot.setObjectName("StyledAIChatHeaderDot")
        self._dot.setFixedSize(STATUS_DOT_SIZE, STATUS_DOT_SIZE)
        self._status = QLabel(status, self)
        self._status.setObjectName("StyledAIChatHeaderStatus")

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(6)
        status_row.addWidget(self._dot)
        status_row.addWidget(self._status)
        status_row.addStretch(1)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(3)
        text_column.addWidget(self._name)
        text_column.addLayout(status_row)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 8, 18, 14)
        layout.setSpacing(12)
        layout.addWidget(self._avatar, 0, Qt.AlignVCenter)
        layout.addLayout(text_column, 1)

        tm.theme_changed.connect(self._on_theme_changed)
        self._apply_qss()

    def set_status(self, text: str, online: bool = True) -> None:
        """设置状态文案与在线状态（决定圆点颜色）。

        Args:
            text: 状态文案，例如"在线"、"正在输入…"。
            online: True 为在线绿点，False 为中性灰点。
        """
        self._status.setText(text)
        self._online = bool(online)
        self._apply_qss()

    def status(self) -> str:
        """返回当前状态文案。

        Returns:
            状态行文本。
        """
        return self._status.text()

    def _apply_qss(self) -> None:
        """注册会话头样式片段（透明底 + 名称 / 状态 / 圆点）。"""
        dot = ONLINE_COLOR if self._online else tm.mid
        register_widget_qss(
            self,
            f"""
            StyledAIChatHeader {{ background: transparent; }}
            #StyledAIChatHeaderName {{
                color: {tm.qss_color(tm.text)};
                font-size: 14px;
                font-weight: 600;
            }}
            #StyledAIChatHeaderStatus {{
                color: {tm.qss_color(tm.text_secondary)};
                font-size: 12px;
            }}
            #StyledAIChatHeaderDot {{
                background-color: {tm.qss_color(dot)};
                border-radius: {STATUS_DOT_SIZE // 2}px;
            }}
            """,
        )

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后重建头像位图并重新注册样式。

        Args:
            _theme: 新主题名（未使用）。
        """
        self._avatar.setPixmap(make_ai_avatar_pixmap(HEADER_AVATAR_SIZE))
        self._apply_qss()


class StyledAIMessageList(QScrollArea):
    """消息区：可滚动的消息行列表。

    滚动区自身透明无边框、水平滚动条常关；内容列内边距 ``18px / 14px /
    18px / 18px``、行间距 12px（对齐 HTML ``.chat-body`` 的
    ``padding: 4px 18px 18px`` 与 ``gap: 12px``）。气泡宽度上限按视口宽度的
    74% 逐行下发，窗口缩放时重新换算。

    Args:
        parent: 父控件。
    """

    #: 内容列内边距（左、上、右、下），对齐 HTML ``.chat-body``。
    CONTENTS_MARGINS = (18, 14, 18, 18)
    #: 行间距（HTML ``gap: 12px``）。
    ROW_SPACING = 12

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setObjectName("StyledAIMessageList")
        self.setVerticalScrollBar(StyledScrollBar(self))
        self.setHorizontalScrollBar(
            StyledScrollBar(self, orientation=Qt.Horizontal)
        )

        self._host = QWidget(self)
        self._host.setObjectName("StyledAIMessageContentView")
        self._column = QVBoxLayout(self._host)
        self._column.setContentsMargins(*self.CONTENTS_MARGINS)
        self._column.setSpacing(self.ROW_SPACING)
        self._column.addStretch(1)
        self.setWidget(self._host)

        StyledScrollArea.apply_to(self)
        tm.theme_changed.connect(self._on_theme_changed)
        self._apply_qss()

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def add_row(self, spec: RowSpec, role: str = "assistant") -> ChatMessageRow:
        """追加一条消息行（图片 / 文件 / typing / 文本）。

        Args:
            spec: 内容描述，见
                :class:`~freeassetfilter.ui.components.styled_chat_bubble.RowSpec`。
            role: 消息角色，决定气泡左右镜像与头像。

        Returns:
            新追加的行控件。
        """
        row = ChatMessageRow(role, spec, parent=self._host)
        # 页脚时间戳：与参考设计一致，时间显示在气泡下方（悬停时与复制按钮一同
        # 淡入），因此这里按发送时刻写入。需要固定文案时用 set_row_time_text。
        row.bubble.set_time_text(datetime.now().strftime("%H:%M"))
        self._column.insertWidget(self._column.count() - 1, row)
        self._apply_row_widths()
        self.scroll_to_bottom()
        return row

    def set_row_time_text(self, row: ChatMessageRow, text: str) -> None:
        """覆盖某行的页脚时间戳（留空则不显示时间）。

        Args:
            row: 目标消息行。
            text: 时间文案，例如 ``23:32``。
        """
        row.bubble.set_time_text(text)

    def add_message(self, role: str, text: str) -> ChatMessageRow:
        """追加一条文本消息行。

        Args:
            role: ``user`` / ``assistant`` / ``reasoning`` / ``system`` /
                ``tool``。
            text: 消息正文。

        Returns:
            新追加的行控件。
        """
        return self.add_row(RowSpec.text_of(text), role)

    def add_time_label(self, text: str) -> QLabel:
        """追加居中的胶囊时间条。

        Args:
            text: 时间文案，例如"今天 14:30"。

        Returns:
            时间标签控件（11px、低透明度底、全圆角）。
        """
        label = QLabel(text, self._host)
        label.setObjectName("StyledAIMessageTime")
        label.setAlignment(Qt.AlignCenter)
        label.setFixedHeight(TIME_LABEL_HEIGHT)
        label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._column.insertWidget(
            self._column.count() - 1, label, 0, Qt.AlignHCenter
        )
        self.scroll_to_bottom()
        return label

    def add_widget(self, widget: QWidget) -> None:
        """追加一个非气泡控件（例如工具审批卡片），左对齐。

        Args:
            widget: 待追加的控件。
        """
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(widget)
        row.addStretch(1)
        self._column.insertLayout(self._column.count() - 1, row)
        self.scroll_to_bottom()

    def remove_row(self, row: QWidget) -> None:
        """移除一条已追加的消息行并销毁它。

        用于撤销临时行（例如"对方正在输入"气泡被真实回复替换）。

        Args:
            row: 待移除的行控件。
        """
        if row is None:
            return
        self._column.removeWidget(row)
        # setParent(None) 会先把控件隐藏，再交给事件循环销毁，避免残影。
        row.setParent(None)
        row.deleteLater()
        self.scroll_to_bottom()

    def last_row(self) -> Optional[ChatMessageRow]:
        """返回最后一条消息行。

        Returns:
            最后一行 :class:`ChatMessageRow`；消息区为空时返回 None。
        """
        rows = self._host.findChildren(ChatMessageRow)
        return rows[-1] if rows else None

    def last_bubble(self) -> Optional[StyledChatBubble]:
        """返回最后一条消息的气泡（流式追加用）。

        Returns:
            最后一个气泡控件；消息区为空时返回 None。
        """
        row = self.last_row()
        if row is not None:
            return row.bubble
        bubbles = self._host.findChildren(StyledChatBubble)
        return bubbles[-1] if bubbles else None

    def last_drawer(self) -> Optional[StyledReasoningDrawer]:
        """返回最后一条消息的思考抽屉（若该行还没抽屉则返回 None）。

        Returns:
            抽屉控件或 None。
        """
        row = self.last_row()
        if row is None:
            return None
        return row.drawer

    def ensure_reasoning_drawer(self) -> StyledReasoningDrawer:
        """在最后一行上按需创建思考抽屉；消息区为空时先建一个助手的空行。

        思考内容不占独立气泡，因此这里把它挂到"即将承载回复"的那一行上，
        抽屉位于气泡上方。

        Returns:
            思考抽屉控件。
        """
        if self.last_row() is None:
            self.add_message("assistant", "")
        row = self.last_row()
        assert row is not None  # add_message 之后必定存在
        return row.ensure_drawer()

    def append_to_last(self, text: str) -> None:
        """向最后一条消息的气泡追加文本（流式输出）。

        Args:
            text: 追加的文本片段。
        """
        bubble = self.last_bubble()
        if bubble is not None:
            bubble.append_text(text)
            self.scroll_to_bottom()

    def scroll_to_bottom(self) -> None:
        """把滚动条拉到底部（显示最新消息）。"""
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _apply_row_widths(self) -> None:
        """按当前视口宽度重算每条消息行的气泡宽度上限。

        行控件内部按"视口宽 × 74%"换算气泡可用宽度；直接 ``add_widget`` 进来
        的裸气泡没有这层换算，这里按同一口径兜底下发。
        """
        viewport = max(1, self.viewport().width())
        rows = self._host.findChildren(ChatMessageRow)
        for row in rows:
            row.set_max_width(viewport)
        fallback_width = int(viewport * MESSAGE_WIDTH_RATIO)
        for bubble in self._host.findChildren(StyledChatBubble):
            # 行内的气泡可能嵌在行的内部容器里（如"头像 + 气泡"那一层），因此要
            # 沿父链判断是否属于某个 ChatMessageRow，不能只看直接父控件——否则会
            # 用未换算的 fallback 宽度覆盖掉行已经算好的 74% 上限。
            if self._belongs_to_row(bubble):
                continue
            bubble.set_max_width(fallback_width)

    @staticmethod
    def _belongs_to_row(widget: QWidget) -> bool:
        """判断控件是否位于某个消息行内部。

        Args:
            widget: 待检查的控件。

        Returns:
            True 表示其祖先链上存在 :class:`ChatMessageRow`。
        """
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, ChatMessageRow):
                return True
            parent = parent.parentWidget()
        return False

    def _apply_qss(self) -> None:
        """注册消息区样式片段（透出窗口底色 + 时间胶囊）。

        消息区实测与窗口同为 ``#F3F3F3``（目标截图逐像素采样），因此保持透明，
        由 :class:`StyledAIChatWindow` 的底色透出，避免多一层色差。
        """
        register_widget_qss(
            self,
            f"""
            StyledAIMessageList {{ background: transparent; border: none; }}
            #qt_scrollarea_viewport {{ background: transparent; }}
            #StyledAIMessageContentView {{ background: transparent; }}
            #StyledAIMessageTime {{
                background-color: {_hairline(4)};
                color: {tm.qss_color(tm.text_secondary)};
                font-size: 11px;
                padding: 0px 10px;
                border-radius: {TIME_LABEL_HEIGHT // 2}px;
            }}
            """,
        )

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后重新注册样式片段。

        Args:
            _theme: 新主题名（未使用）。
        """
        self._apply_qss()

    def resizeEvent(self, event: object) -> None:
        """窗口缩放时重算气泡宽度上限。

        Args:
            event: Qt 尺寸变化事件。
        """
        self._apply_row_widths()
        super().resizeEvent(event)  # type: ignore[arg-type]


class StyledChatComposer(QWidget):
    """底部输入栏：「+」附件按钮 + 输入框 + 「发送」按钮。

    控件高 34px、内边距 ``14px 18px 18px``、顶部 1px 分隔线；输入框圆角
    ``4 4 0 0``，获焦时底变不透明并显示 2px 强调色底边（对齐 HTML
    ``.composer``）。

    Args:
        placeholder: 输入框占位文案。
        parent: 父控件。

    Signals:
        send_requested: 提交非空文本（回车或点击「发送」）；提交后输入框自动清空。
        attach_requested: 点击「+」附件按钮。
        image_requested: :meth:`request_image` 被调用（宿主选择图片）。
        file_requested: :meth:`request_file` 被调用（宿主选择文件）。
    """

    send_requested = Signal(str)
    attach_requested = Signal()
    image_requested = Signal()
    file_requested = Signal()

    def __init__(
        self, placeholder: str = "输入消息…", parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("StyledChatComposer")
        self._enabled = True

        self._attach = QPushButton("+", self)
        self._attach.setObjectName("StyledChatComposerAttach")
        self._attach.setFixedSize(CONTROL_HEIGHT, CONTROL_HEIGHT)
        self._attach.setCursor(Qt.PointingHandCursor)
        self._attach.setFocusPolicy(Qt.NoFocus)
        self._attach.setToolTip("添加图片或文件")
        self._attach.clicked.connect(lambda: self.attach_requested.emit())

        self._input = QLineEdit(self)
        self._input.setObjectName("StyledChatComposerInput")
        self._input.setFixedHeight(CONTROL_HEIGHT)
        self._input.setPlaceholderText(placeholder)
        # QLineEdit.setTextMargins 比 QSS padding 更可靠地定位文本
        self._input.setTextMargins(10, 0, 8, 0)
        # returnPressed 在中文输入法组字期间不会触发（回车先用于提交候选词），
        # 因此无需额外守卫。
        self._input.returnPressed.connect(self._submit)
        self._input.textChanged.connect(self._on_text_changed)

        self.send_button = StyledButton("发送", variant="primary", parent=self)
        self.send_button.setFont(QFont("Microsoft YaHei UI", 10))
        self.send_button.setFixedHeight(CONTROL_HEIGHT)
        metrics = QFontMetrics(QFont("Microsoft YaHei UI", 10))
        # 设计稿要求左右各 20px 内边距
        self.send_button.setMinimumWidth(metrics.horizontalAdvance("发送") + 40)
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self._submit)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(self._attach)
        layout.addWidget(self._input, 1)
        layout.addWidget(self.send_button)

        tm.theme_changed.connect(self._on_theme_changed)
        self._apply_qss()

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        """启用 / 禁用整个输入栏。

        禁用时输入框、「+」与「发送」都不可交互（宿主在等待回复 / 工具调用
        期间调用）；恢复后「发送」按钮仍按输入框是否为空决定可用状态。

        Args:
            enabled: True 启用。
        """
        self._enabled = bool(enabled)
        self._attach.setEnabled(self._enabled)
        self._input.setEnabled(self._enabled)
        self.send_button.setEnabled(
            self._enabled and bool(self._input.text().strip())
        )

    def set_placeholder(self, text: str) -> None:
        """设置输入框占位文案。

        Args:
            text: 占位文案。
        """
        self._input.setPlaceholderText(text)

    def text(self) -> str:
        """返回输入框当前文本。

        Returns:
            输入框文本（未去空白）。
        """
        return self._input.text()

    def clear(self) -> None:
        """清空输入框。"""
        self._input.clear()

    def focus(self) -> None:
        """把键盘焦点交给输入框。"""
        self._input.setFocus(Qt.OtherFocusReason)

    def request_image(self) -> None:
        """请求发送图片（宿主在附件浮出层选择「图片」后调用）。"""
        self.image_requested.emit()

    def request_file(self) -> None:
        """请求发送文件（宿主在附件浮出层选择「文件」后调用）。"""
        self.file_requested.emit()

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _submit(self) -> None:
        """提交输入框文本：非空时清空输入框并发出 :attr:`send_requested`。"""
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.send_requested.emit(text)

    def _on_text_changed(self, text: str) -> None:
        """输入变化时同步「发送」按钮可用状态。

        Args:
            text: 输入框新文本。
        """
        self.send_button.setEnabled(self._enabled and bool(text.strip()))

    def _apply_qss(self) -> None:
        """注册输入栏样式片段（透出窗口底色 + 分隔线 + 附件按钮 + 输入框）。"""
        register_widget_qss(
            self,
            f"""
            StyledChatComposer {{
                background: transparent;
                border-top: 1px solid {_hairline(8)};
            }}
            #StyledChatComposerAttach {{
                background-color: {_control_fill()};
                color: {tm.qss_color(tm.text)};
                border: 1px solid {_hairline(6)};
                border-bottom: 1px solid {_hairline(10)};
                border-radius: {CONTROL_RADIUS}px;
                font-size: 17px;
                padding: 0px;
            }}
            #StyledChatComposerAttach:hover {{
                background-color: {tm.qss_color(tm.alpha_of(tm.text, 8))};
            }}
            #StyledChatComposerAttach:pressed {{
                background-color: {tm.qss_color(tm.alpha_of(tm.text, 12))};
            }}
            #StyledChatComposerInput {{
                background-color: {_control_fill()};
                color: {tm.qss_color(tm.text)};
                border: 1px solid {_hairline(6)};
                border-bottom: 1px solid {_hairline(10)};
                border-top-left-radius: {CONTROL_RADIUS}px;
                border-top-right-radius: {CONTROL_RADIUS}px;
                border-bottom-left-radius: 0px;
                border-bottom-right-radius: 0px;
                font-size: 13px;
                selection-background-color: {tm.qss_color(tm.accent)};
                selection-color: {tm.qss_color(tm.white)};
            }}
            #StyledChatComposerInput:hover {{
                border-color: {_hairline(10)};
            }}
            #StyledChatComposerInput:focus {{
                background-color: {_opaque_surface()};
                border-bottom: 2px solid {tm.qss_color(tm.accent)};
            }}
            #StyledChatComposerInput:disabled {{
                color: {tm.qss_color(tm.text_disabled)};
            }}
            """,
        )

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后重新注册样式片段。

        Args:
            _theme: 新主题名（未使用）。
        """
        self._apply_qss()


class StyledAIChatWindow(QWidget):
    """WinUI 3 风格对话容器：标题栏 + 会话头 + 消息区 + 输入栏。

    Args:
        parent: 父控件。
        title: 标题栏文案。

    Signals:
        send_requested: 输入栏提交文本。
        attach_requested: 点击输入栏「+」附件按钮。
        image_requested: 宿主请求选择图片（``composer.request_image()``）。
        file_requested: 宿主请求选择文件（``composer.request_file()``）。
        minimize_requested: 请求最小化宿主窗口。
        maximize_requested: 请求最大化 / 还原宿主窗口。
        close_requested: 请求关闭宿主窗口。
    """

    send_requested = Signal(str)
    attach_requested = Signal()
    image_requested = Signal()
    file_requested = Signal()
    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        title: str = DEFAULT_WINDOW_TITLE,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("StyledAIChatWindow")

        self.title_bar = StyledAIChatTitleBar(title, self)
        self.header = StyledAIChatHeader(parent=self)
        self.messages = StyledAIMessageList(self)
        self.composer = StyledChatComposer(parent=self)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.title_bar)
        root.addWidget(self.header)
        root.addWidget(self.messages, 1)
        root.addWidget(self.composer)

        self.composer.send_requested.connect(
            lambda text: self.send_requested.emit(text)
        )
        self.composer.attach_requested.connect(
            lambda: self.attach_requested.emit()
        )
        self.composer.image_requested.connect(
            lambda: self.image_requested.emit()
        )
        self.composer.file_requested.connect(lambda: self.file_requested.emit())
        self.title_bar.minimize_requested.connect(
            lambda: self.minimize_requested.emit()
        )
        self.title_bar.maximize_requested.connect(
            lambda: self.maximize_requested.emit()
        )
        self.title_bar.close_requested.connect(
            lambda: self.close_requested.emit()
        )

        tm.theme_changed.connect(self._on_theme_changed)
        self._apply_qss()

    def set_title(self, title: str) -> None:
        """设置标题栏文案。

        Args:
            title: 新标题。
        """
        self.title_bar.set_title(title)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        """返回默认建议尺寸。

        Returns:
            建议尺寸：参考设计稿（WinUI 3 HTML）窗口内容区 511×747。宽度按
            目标截图反推——目标窗口外框 502px、消息区左右各 18px 内边距，
            文字气泡在其 74% 上限下需要 511px 内容宽才能复现 338px 的两行气泡
            （实测：内容宽 511 时气泡 337px、首行墨迹 294px，与目标 338/292
            相差 0.3%）。
        """
        return QSize(511, 747)

    def _apply_qss(self) -> None:
        """注册整窗样式片段（填充底色）。

        底色走 :func:`window_fill_color`：浅色为参考设计的 Mica 灰 ``#F3F3F3``
        （目标截图实测值），深色回落 ``tm.fill``；消息区与输入栏保持透明，
        由本底色统一透出（实测与目标截图同色，避免多一层色差）。
        """
        register_widget_qss(
            self,
            "StyledAIChatWindow { background-color: "
            f"{tm.qss_color(window_fill_color())}; }}",
        )

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后重新注册样式片段。

        Args:
            _theme: 新主题名（未使用）。
        """
        self._apply_qss()


class StyledAIToolApproval(QWidget):
    """工具调用审批卡片（批准 / 拒绝）。

    Args:
        call_id: 工具调用 id，随信号回传给宿主。
        name: 工具名。
        arguments: 调用参数文本。
        parent: 父控件。

    Signals:
        approved: 点击「批准」，携带 ``call_id``。
        rejected: 点击「拒绝」，携带 ``call_id``。
    """

    approved = Signal(str)
    rejected = Signal(str)

    def __init__(
        self,
        call_id: str,
        name: str,
        arguments: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("StyledAIToolApproval")
        self.call_id = call_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        title = QLabel(f"工具请求 · {name}", self)
        title.setObjectName("StyledAIToolApprovalTitle")
        details = QLabel(arguments, self)
        details.setObjectName("StyledAIToolApprovalDetails")
        details.setWordWrap(True)
        details.setTextInteractionFlags(Qt.TextSelectableByMouse)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        approve = StyledButton("批准", variant="primary", size="sm", parent=self)
        reject = StyledButton("拒绝", variant="danger", size="sm", parent=self)
        approve.clicked.connect(lambda: self.approved.emit(self.call_id))
        reject.clicked.connect(lambda: self.rejected.emit(self.call_id))
        actions.addStretch(1)
        actions.addWidget(reject)
        actions.addWidget(approve)

        layout.addWidget(title)
        layout.addWidget(details)
        layout.addLayout(actions)

        tm.theme_changed.connect(self._on_theme_changed)
        self._apply_qss()

    def _apply_qss(self) -> None:
        """注册审批卡片样式片段（信息色低透明度底 + 描边）。"""
        register_widget_qss(
            self,
            f"""
            StyledAIToolApproval {{
                background-color: {tm.qss_color(tm.alpha_of(tm.info, 10))};
                border: 1px solid {tm.qss_color(tm.alpha_of(tm.info, 45))};
                border-radius: 8px;
            }}
            #StyledAIToolApprovalTitle {{
                color: {tm.qss_color(tm.info)};
                font-size: 13px;
                font-weight: 600;
            }}
            #StyledAIToolApprovalDetails {{
                color: {tm.qss_color(tm.text)};
                font-size: 12px;
            }}
            """,
        )

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后重新注册样式片段。

        Args:
            _theme: 新主题名（未使用）。
        """
        self._apply_qss()


class StyledAIChatPanel(QWidget):
    """AI 对话面板（标题 + 消息区 + 多行输入 + 发送 / 取消 + 工具审批）。

    面向 ``ai_chat_demo`` 这类"面板嵌进设置页"的场景；气泡外观与新容器
    保持一致。

    Args:
        title: 面板标题。
        parent: 父控件。

    Signals:
        send_requested: 用户提交问题文本。
        cancel_requested: 用户点击「取消」。
        tool_approval: 工具审批结果 ``(call_id, approved)``。
    """

    send_requested = Signal(str)
    cancel_requested = Signal()
    tool_approval = Signal(str, bool)

    def __init__(
        self, title: str = "AI 对话", parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self._assistant_row: Optional[ChatMessageRow] = None
        #: 思考开始的单调时钟（第一次收到思考片段时打点），用于「用时 N 秒」。
        self._reasoning_started_at: Optional[float] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        heading = QLabel(title, self)
        heading.setObjectName("StyledAIChatPanelHeading")
        self.status = QLabel("就绪", self)
        self.status.setObjectName("StyledAIChatPanelStatus")
        header.addWidget(heading)
        header.addStretch(1)
        header.addWidget(self.status)
        root.addLayout(header)

        self.messages = StyledAIMessageList(self)
        root.addWidget(self.messages, 1)

        self.composer = StyledTextarea(
            placeholder="输入问题或补充信息…", size="default", parent=self
        )
        root.addWidget(self.composer)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self.send_button = StyledButton("发送", variant="primary", parent=self)
        self.cancel_button = StyledButton("取消", variant="secondary", parent=self)
        self.cancel_button.setEnabled(False)
        self.send_button.clicked.connect(self._send)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        actions.addStretch(1)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.send_button)
        root.addLayout(actions)

        tm.theme_changed.connect(self._on_theme_changed)
        self._apply_qss()

    def _send(self) -> None:
        """提交输入框文本：追加用户气泡、清空输入并进入忙碌态。"""
        text = self.composer.text.strip()
        if not text:
            return
        self.messages.add_message("user", text)
        self.composer.text = ""
        self._assistant_row = None
        self.set_busy(True)
        self.send_requested.emit(text)

    def append_reasoning(self, text: str) -> None:
        """追加思考内容到可折叠抽屉（不再使用独立气泡）。

        抽屉挂在"承载回复的那一行"的气泡上方：首次收到思考片段时创建并开始计时，
        后续片段持续追加；耗时用于标题栏「已思考（用时 N 秒）」。抽屉在流式思考
        期间自动展开，思考结束（开始输出正式回复）时自动收起。

        Args:
            text: 思考文本片段。
        """
        if self._reasoning_started_at is None:
            self._reasoning_started_at = time.monotonic()
        self._ensure_reasoning_target()
        drawer = self._assistant_row.ensure_drawer()  # type: ignore[union-attr]
        drawer.append_text(text)
        drawer.set_elapsed_ms(
            int((time.monotonic() - self._reasoning_started_at) * 1000)
        )
        drawer.set_streaming(True)
        if not drawer.expanded:
            drawer.set_expanded(True)
        self.messages.scroll_to_bottom()

    def _ensure_reasoning_target(self) -> None:
        """确保存在承载思考抽屉的助手消息行。"""
        if self._assistant_row is None:
            self._assistant_row = self.messages.add_message("assistant", "")
            self._assistant_row.bubble.set_streaming(True)

    def finish_reasoning(self) -> None:
        """结束思考：冻结耗时并自动收起抽屉。"""
        row = self._assistant_row
        if row is None or row.drawer is None:
            return
        drawer = row.drawer
        if self._reasoning_started_at is not None:
            drawer.set_elapsed_ms(
                int((time.monotonic() - self._reasoning_started_at) * 1000)
            )
        drawer.set_streaming(False)
        drawer.set_expanded(False)
        self._reasoning_started_at = None

    def append_text(self, text: str) -> None:
        """追加助手回复文本（首片自动创建流式气泡）。

        正式回复开始时若思考抽屉正在展开，先收起抽屉——思考结束后让位给答复，
        与参考设计的行为一致。

        Args:
            text: 回复文本片段。
        """
        if self._assistant_row is None:
            self._assistant_row = self.messages.add_message("assistant", "")
            self._assistant_row.bubble.set_streaming(True)
        if self._reasoning_started_at is not None:
            self.finish_reasoning()
        self._assistant_row.bubble.append_text(text)
        self.messages.scroll_to_bottom()

    def add_tool_approval(
        self, call_id: str, name: str, arguments: str
    ) -> StyledAIToolApproval:
        """追加一张工具审批卡片。

        Args:
            call_id: 工具调用 id。
            name: 工具名。
            arguments: 调用参数文本。

        Returns:
            新追加的审批卡片控件。
        """
        widget = StyledAIToolApproval(call_id, name, arguments, self)
        widget.approved.connect(
            lambda value: self.tool_approval.emit(value, True)
        )
        widget.rejected.connect(
            lambda value: self.tool_approval.emit(value, False)
        )
        self.messages.add_widget(widget)
        return widget

    def set_busy(self, busy: bool, status: str = "处理中…") -> None:
        """切换忙碌态（按钮可用性 + 状态文案 + 结束流式气泡）。

        Args:
            busy: True 表示请求进行中。
            status: 忙碌时显示的状态文案。
        """
        self.send_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.status.setText(status if busy else "就绪")
        if not busy and self._assistant_row is not None:
            self._assistant_row.bubble.set_streaming(False)

    def show_error(self, message: str) -> None:
        """显示错误状态。

        Args:
            message: 错误文案。
        """
        self.status.setText(message)
        self.set_busy(False, "请求失败")

    def _apply_qss(self) -> None:
        """注册面板样式片段（标题与状态文案）。"""
        register_widget_qss(
            self,
            f"""
            #StyledAIChatPanelHeading {{
                color: {tm.qss_color(tm.text)};
                font-size: 15px;
                font-weight: 600;
            }}
            #StyledAIChatPanelStatus {{
                color: {tm.qss_color(tm.mid)};
                font-size: 11px;
            }}
            """,
        )

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后重新注册样式片段。

        Args:
            _theme: 新主题名（未使用）。
        """
        self._apply_qss()


#: 兼容旧名：气泡统一由 :mod:`styled_chat_bubble` 提供。
StyledAIChatBubble = StyledChatBubble

__all__ = [
    "StyledAIChatPanel",
    "StyledAIMessageList",
    "StyledAIChatBubble",
    "StyledChatBubble",
    "StyledAIToolApproval",
    "StyledAIChatHeader",
    "StyledAIChatTitleBar",
    "StyledChatComposer",
    "StyledAIChatWindow",
    "ChatMessageRow",
    "RowSpec",
]
