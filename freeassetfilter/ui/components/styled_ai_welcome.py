# -*- coding: utf-8 -*-
"""AI 对话欢迎态（styled 组件）。

空会话时占据消息区：AI 头像 + 标题 + 副标题 + 2×2 建议卡片。所有颜色来自
``tm`` 令牌，字号取自现有 styled 组件档位（16 / 13.5 / 13 / 12），不写死色值。
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from freeassetfilter.ui.components.icon_utils import render_icon
from freeassetfilter.ui.components.styled_chat_bubble import (
    RADIUS_BUBBLE,
    make_ai_avatar_pixmap,
)
from freeassetfilter.ui.components.styled_lineedit import (
    FONT_FAMILY,
    StyledLineEdit,
    styled_font,
)
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss
from theme import tm

#: 头像边长（像素）。
AVATAR_SIZE = 64
#: 建议卡片尺寸。
CARD_WIDTH = 260
CARD_HEIGHT = 92
#: 建议卡片图标块边长。
ICON_TILE = 32
#: 内容列最大宽度。
CONTENT_MAX_WIDTH = 560


class StyledAISuggestionCard(QAbstractButton):
    """欢迎态建议卡片。

    Args:
        title: 卡片标题。
        description: 卡片描述。
        prompt: 点击后填入输入器的文本；为空时使用标题。
        icon: ``icon_utils`` 图标名。
        parent: 父控件。

    Signals:
        activated: 点击后发出，携带 ``prompt``。
    """

    activated = Signal(str)

    #: 标题字号（与 ``StyledLineEdit`` default 档一致）。
    TITLE_SIZE = StyledLineEdit.SIZE_CONFIG["default"]["font_size"]
    #: 描述字号（与 ``StyledLineEdit`` sm 档一致）。
    DESC_SIZE = StyledLineEdit.SIZE_CONFIG["sm"]["font_size"]

    def __init__(
        self,
        title: str,
        description: str = "",
        prompt: str = "",
        icon: str = "sparkles",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._title = str(title or "")
        self._description = str(description or "")
        self._prompt = str(prompt or self._title)
        self._icon = str(icon or "sparkles")
        self._hovered = False

        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(CARD_HEIGHT)
        self.setMaximumHeight(CARD_HEIGHT)
        self.clicked.connect(lambda: self.activated.emit(self._prompt))

        self._title_font = styled_font(self.TITLE_SIZE)
        self._title_font.setWeight(QFont.Weight.DemiBold)
        self._desc_font = styled_font(self.DESC_SIZE)

        tm.theme_changed.connect(self._on_theme_changed)
        tm.colors_updated.connect(self._on_theme_changed)

    def prompt(self) -> str:
        """返回点击后填入输入器的文本。

        Returns:
            建议文本。
        """
        return self._prompt

    def set_prompt(self, prompt: str) -> None:
        """设置点击后填入输入器的文本。

        Args:
            prompt: 建议文本；为空时回退到标题。
        """
        self._prompt = str(prompt or self._title)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        """返回建议尺寸。

        Returns:
            卡片 QSize。
        """
        return QSize(CARD_WIDTH, CARD_HEIGHT)

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制卡片底、图标块与两行文本。

        Args:
            event: Qt 绘制事件。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        fill = QColor(tm.surface) if self._hovered else QColor(tm.card_fill)
        border = QColor(tm.accent) if self._hovered else QColor(tm.card_border)
        painter.setPen(border)
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, RADIUS_BUBBLE, RADIUS_BUBBLE)

        tile = QRectF(
            rect.left() + 14,
            rect.center().y() - ICON_TILE / 2.0,
            float(ICON_TILE),
            float(ICON_TILE),
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(tm.accent_alpha(28))
        painter.drawRoundedRect(tile, 8, 8)

        icon_side = 18.0
        render_icon(
            painter,
            self._icon,
            QRectF(
                tile.center().x() - icon_side / 2.0,
                tile.center().y() - icon_side / 2.0,
                icon_side,
                icon_side,
            ),
            QColor(tm.accent),
            1.8,
        )

        text_left = tile.right() + 12
        text_width = max(1.0, rect.right() - text_left - 12)
        painter.setFont(self._title_font)
        painter.setPen(QColor(tm.text))
        title_rect = QRectF(
            text_left,
            rect.center().y() - 18,
            text_width,
            18,
        )
        painter.drawText(
            title_rect,
            Qt.AlignLeft | Qt.AlignVCenter,
            QFontMetrics(self._title_font).elidedText(
                self._title, Qt.ElideRight, int(text_width)
            ),
        )

        painter.setFont(self._desc_font)
        painter.setPen(QColor(tm.text_secondary))
        desc_rect = QRectF(
            text_left,
            rect.center().y() + 2,
            text_width,
            18,
        )
        painter.drawText(
            desc_rect,
            Qt.AlignLeft | Qt.AlignVCenter,
            QFontMetrics(self._desc_font).elidedText(
                self._description, Qt.ElideRight, int(text_width)
            ),
        )
        painter.end()

    def enterEvent(self, event: object) -> None:
        """悬停进入：重绘。

        Args:
            event: Qt 进入事件。
        """
        self._hovered = True
        self.update()
        super().enterEvent(event)  # type: ignore[arg-type]

    def leaveEvent(self, event: object) -> None:
        """悬停离开：重绘。

        Args:
            event: Qt 离开事件。
        """
        self._hovered = False
        self.update()
        super().leaveEvent(event)  # type: ignore[arg-type]

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后重绘。

        Args:
            _theme: 新主题名（未使用）。
        """
        self.update()


class StyledAIWelcome(QWidget):
    """AI 对话欢迎态。

    Args:
        suggestions: 建议卡片数据列表，每项支持 ``title`` / ``description`` /
            ``prompt`` / ``icon``。
        parent: 父控件。

    Signals:
        suggestion_selected: 点击建议卡片后发出，携带建议文本。
    """

    suggestion_selected = Signal(str)

    #: 默认建议卡片。
    DEFAULT_SUGGESTIONS: List[dict] = [
        {
            "icon": "folder",
            "title": "整理素材",
            "description": "按类型归类今天的文件",
            "prompt": "帮我按类型整理今天的素材文件。",
        },
        {
            "icon": "search",
            "title": "查找文件",
            "description": "描述你要找的文件特征",
            "prompt": "帮我找一下最近修改过的设计文件。",
        },
        {
            "icon": "edit",
            "title": "起草文档",
            "description": "写一份结构清晰的文档",
            "prompt": "帮我起草一份项目周报。",
        },
        {
            "icon": "sparkles",
            "title": "解释内容",
            "description": "解释选中的文件或代码",
            "prompt": "解释一下这个文件的主要内容。",
        },
    ]

    def __init__(
        self,
        suggestions: Optional[List[dict]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._cards: List[StyledAISuggestionCard] = []
        self._avatar = QLabel(self)
        self._avatar.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
        self._avatar.setPixmap(make_ai_avatar_pixmap(AVATAR_SIZE))
        self._avatar.setAlignment(Qt.AlignCenter)

        self._title = QLabel("有什么可以帮你？", self)
        self._title.setObjectName("StyledAIWelcomeTitle")
        self._title.setAlignment(Qt.AlignCenter)
        self._subtitle = QLabel(
            "我可以帮你整理素材、解释文件、起草文档，或者只是聊聊。", self
        )
        self._subtitle.setObjectName("StyledAIWelcomeSubtitle")
        self._subtitle.setAlignment(Qt.AlignCenter)
        self._subtitle.setWordWrap(True)

        self._grid_host = QWidget(self)
        self._grid_host.setMaximumWidth(CONTENT_MAX_WIDTH)
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(12)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        column.addWidget(self._avatar, 0, Qt.AlignHCenter)
        column.addWidget(self._title)
        column.addWidget(self._subtitle)
        column.addSpacing(16)
        column.addWidget(self._grid_host, 0, Qt.AlignHCenter)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(1)
        outer.addLayout(column)
        outer.addStretch(1)

        self.set_suggestions(
            suggestions if suggestions is not None else self.DEFAULT_SUGGESTIONS
        )

        tm.theme_changed.connect(self._on_theme_changed)
        tm.colors_updated.connect(self._on_theme_changed)
        self._apply_qss()

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def set_suggestions(self, suggestions: List[dict]) -> None:
        """重建建议卡片网格。

        Args:
            suggestions: 卡片数据列表；最多显示 4 项。
        """
        for card in self._cards:
            self._grid.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()

        for index, item in enumerate(list(suggestions)[:4]):
            card = StyledAISuggestionCard(
                title=str(item.get("title", "")),
                description=str(item.get("description", "")),
                prompt=str(item.get("prompt", "")),
                icon=str(item.get("icon", "sparkles")),
                parent=self._grid_host,
            )
            card.activated.connect(self.suggestion_selected.emit)
            self._cards.append(card)
            self._grid.addWidget(card, index // 2, index % 2)

    def suggestions(self) -> List[StyledAISuggestionCard]:
        """返回当前建议卡片。

        Returns:
            卡片列表。
        """
        return list(self._cards)

    def _apply_qss(self) -> None:
        """注册标题 / 副标题样式（字号取自现有档位）。"""
        register_widget_qss(
            self._title,
            f"color: {tm.qss_color(tm.text)};"
            f' font-family: "{FONT_FAMILY}";'
            " font-size: 16px;"
            " font-weight: 600;",
        )
        register_widget_qss(
            self._subtitle,
            f"color: {tm.qss_color(tm.text_secondary)};"
            f' font-family: "{FONT_FAMILY}";'
            " font-size: 13.5px;",
        )

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后刷新头像与样式。

        Args:
            _theme: 新主题名（未使用）。
        """
        self._avatar.setPixmap(make_ai_avatar_pixmap(AVATAR_SIZE))
        self._apply_qss()
        self.update()


__all__ = [
    "StyledAIWelcome",
    "StyledAISuggestionCard",
    "AVATAR_SIZE",
    "CARD_WIDTH",
    "CARD_HEIGHT",
]
