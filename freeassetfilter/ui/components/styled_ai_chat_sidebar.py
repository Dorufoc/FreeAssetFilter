# -*- coding: utf-8 -*-
"""独立的 AI 会话导航侧边栏（styled 组件）。

该组件只负责会话导航布局，不持有聊天区，也不依赖 ``StyledAIChatWindow``，
便于后续嵌入任意窗口或控件。视觉常量复用 :class:`StyledSidebar` 的展开 /
折叠宽度，颜色全部来自 ``tm`` 令牌。

Example:
    >>> sidebar = StyledAIChatSidebar()
    >>> sidebar.set_conversations([ConversationEntry("1", "设计素材归档")])
    >>> sidebar.conversation_selected.connect(on_selected)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QFontMetrics,
    QPainter,
    QPaintEvent,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from freeassetfilter.ui.components.icon_utils import render_icon
from freeassetfilter.ui.components.styled_avatar import StyledAvatar
from freeassetfilter.ui.components.styled_button import StyledButton
from freeassetfilter.ui.components.styled_chat_bubble import make_ai_avatar_pixmap
from freeassetfilter.ui.components.styled_context_menu import StyledContextMenu
from freeassetfilter.ui.components.styled_icon_button import StyledIconButton
from freeassetfilter.ui.components.styled_lineedit import (
    FONT_FAMILY,
    StyledLineEdit,
    styled_font,
)
from freeassetfilter.ui.components.styled_scroll_area import StyledScrollArea
from freeassetfilter.ui.components.styled_sidebar import StyledSidebar
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss
from freeassetfilter.utils.animation_settings import is_animation_enabled
from theme import tm

#: 展开 / 折叠宽度：直接复用 StyledSidebar 的常量。
EXPANDED_WIDTH = StyledSidebar.DEFAULT_WIDTH
COMPACT_WIDTH = StyledSidebar.COMPACT_WIDTH
#: 会话项高度。
ITEM_HEIGHT = 44
#: 分组顺序。
GROUP_ORDER = ("置顶", "今天", "昨天", "更早")


@dataclass
class ConversationEntry:
    """一条会话导航数据。

    Attributes:
        id: 唯一标识。
        title: 会话标题。
        preview: 最后一条消息预览。
        time_text: 时间文案（如 ``14:30``）。
        group: 分组名（``置顶`` / ``今天`` / ``昨天`` / ``更早``）。
        pinned: 是否置顶；True 时归入「置顶」分组。
    """

    id: str
    title: str
    preview: str = ""
    time_text: str = ""
    group: str = "今天"
    pinned: bool = False


class _SidebarSearchEdit(StyledLineEdit):
    """带前置搜索图标的侧边栏搜索框。

    Args:
        parent: 父控件。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(size="sm", parent=parent)
        self.setPlaceholderText("搜索对话")
        config = self.SIZE_CONFIG["sm"]
        self.setTextMargins(
            config["padding_h"] + 18,
            config["padding_v"],
            config["padding_h"],
            config["padding_v"],
        )

    def paintEvent(self, event: object) -> None:
        """先绘制输入框本体，再叠加搜索图标。

        Args:
            event: Qt 绘制事件。
        """
        super().paintEvent(event)  # type: ignore[arg-type]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        side = 14.0
        render_icon(
            painter,
            "search",
            QRectF(9.0, (self.height() - side) / 2.0, side, side),
            QColor(tm.text_hint),
            1.6,
        )
        painter.end()


class AIConversationItem(QAbstractButton):
    """单条会话项。

    Args:
        entry: 会话数据。
        compact: 是否折叠态（仅显示图标）。
        parent: 父控件。

    Signals:
        delete_requested: 点击删除，携带会话 id。
        rename_requested: 右键菜单选择重命名，携带会话 id。
    """

    delete_requested = Signal(str)
    rename_requested = Signal(str)

    TITLE_SIZE = StyledLineEdit.SIZE_CONFIG["default"]["font_size"]
    META_SIZE = StyledLineEdit.SIZE_CONFIG["sm"]["font_size"]

    def __init__(
        self,
        entry: ConversationEntry,
        compact: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.entry = entry
        self._compact = bool(compact)
        self._active = False
        self._hovered = False
        self._title_font = styled_font(self.TITLE_SIZE)
        self._meta_font = styled_font(self.META_SIZE)

        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(ITEM_HEIGHT)

        self._delete_button = StyledIconButton(
            "trash",
            size="sm",
            shape="square",
            variant="danger",
            tooltip="删除对话",
            parent=self,
        )
        self._delete_button.clicked.connect(
            lambda: self.delete_requested.emit(self.entry.id)
        )
        self._delete_button.hide()
        if self._compact:
            self.setToolTip(self.entry.title)

        tm.theme_changed.connect(self._on_theme_changed)
        tm.colors_updated.connect(self._on_theme_changed)

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def set_active(self, active: bool) -> None:
        """设置选中态。

        Args:
            active: 是否选中。
        """
        self._active = bool(active)
        self.update()

    def is_active(self) -> bool:
        """返回是否选中。

        Returns:
            选中状态。
        """
        return self._active

    def set_compact(self, compact: bool) -> None:
        """切换折叠态。

        Args:
            compact: True 时仅显示会话图标。
        """
        self._compact = bool(compact)
        if self._compact:
            self._delete_button.hide()
            self.setToolTip(self.entry.title)
        else:
            self.setToolTip("")
        self.update()

    def set_entry(self, entry: ConversationEntry) -> None:
        """更新会话数据。

        Args:
            entry: 新的会话数据。
        """
        self.entry = entry
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        """返回会话项尺寸。

        Returns:
            QSize。
        """
        return QSize(0, ITEM_HEIGHT)

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def _shape_rect(self) -> QRectF:
        """返回内容绘制区域。

        Returns:
            去掉 1px 内边距的矩形。
        """
        return QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制选中/悬停底与标题、预览、时间。

        Args:
            event: Qt 绘制事件。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self._shape_rect()

        if self._active:
            painter.setPen(Qt.NoPen)
            painter.setBrush(tm.hover_veil)
            painter.drawRoundedRect(rect, 4, 4)
            painter.setBrush(QColor(tm.accent))
            painter.drawRoundedRect(
                QRectF(0.0, rect.center().y() - 9.0, 3.0, 18.0), 1.5, 1.5
            )
        elif self._hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(tm.alpha_of(tm.text, 4))
            painter.drawRoundedRect(rect, 4, 4)

        if self._compact:
            side = 18.0
            render_icon(
                painter,
                "chat",
                QRectF(
                    rect.center().x() - side / 2.0,
                    rect.center().y() - side / 2.0,
                    side,
                    side,
                ),
                QColor(tm.accent_text if self._active else tm.text_secondary),
                1.8,
            )
            painter.end()
            return

        title_left = 14.0
        title_width = max(1.0, rect.width() - title_left - 14.0)
        if self._hovered:
            title_width -= 26.0
        painter.setFont(self._title_font)
        painter.setPen(QColor(tm.text))
        painter.drawText(
            QRectF(title_left, 7.0, title_width, 18.0),
            Qt.AlignLeft | Qt.AlignVCenter,
            QFontMetrics(self._title_font).elidedText(
                self.entry.title, Qt.ElideRight, int(title_width)
            ),
        )

        meta = self.entry.preview or self.entry.time_text
        if meta:
            painter.setFont(self._meta_font)
            painter.setPen(QColor(tm.text_secondary))
            painter.drawText(
                QRectF(title_left, 24.0, title_width, 15.0),
                Qt.AlignLeft | Qt.AlignVCenter,
                QFontMetrics(self._meta_font).elidedText(
                    meta, Qt.ElideRight, int(title_width)
                ),
            )
        painter.end()

    def resizeEvent(self, event: object) -> None:
        """把删除按钮放在右侧居中位置。

        Args:
            event: Qt 尺寸事件。
        """
        super().resizeEvent(event)  # type: ignore[arg-type]
        side = self._delete_button.width()
        self._delete_button.move(
            self.width() - side - 8,
            (self.height() - side) // 2,
        )

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------

    def enterEvent(self, event: object) -> None:
        """悬停进入：显示删除按钮并重绘。

        Args:
            event: Qt 进入事件。
        """
        self._hovered = True
        if not self._compact:
            self._delete_button.show()
        self.update()
        super().enterEvent(event)  # type: ignore[arg-type]

    def leaveEvent(self, event: object) -> None:
        """悬停离开：隐藏删除按钮并重绘。

        Args:
            event: Qt 离开事件。
        """
        self._hovered = False
        self._delete_button.hide()
        self.update()
        super().leaveEvent(event)  # type: ignore[arg-type]

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """右键菜单：重命名 / 删除。

        Args:
            event: 右键菜单事件。
        """
        menu = StyledContextMenu(parent=self.window())
        menu.add_item("重命名", callback=lambda: self.rename_requested.emit(self.entry.id))
        menu.add_separator()
        menu.add_item(
            "删除",
            danger=True,
            callback=lambda: self.delete_requested.emit(self.entry.id),
        )
        menu.exec(event.globalPos())
        event.accept()

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后重绘。

        Args:
            _theme: 新主题名（未使用）。
        """
        self.update()


class StyledAIChatSidebar(QWidget):
    """独立会话导航侧边栏。

    Args:
        parent: 父控件。

    Signals:
        new_chat_requested: 点击新建对话。
        conversation_selected: 选中会话，携带会话 id。
        rename_requested: 请求重命名，携带会话 id。
        delete_requested: 请求删除，携带会话 id。
        search_changed: 搜索文本变化。
        settings_requested: 点击设置。
        collapsed_changed: 折叠状态变化。
    """

    new_chat_requested = Signal()
    conversation_selected = Signal(str)
    rename_requested = Signal(str)
    delete_requested = Signal(str)
    search_changed = Signal(str)
    settings_requested = Signal()
    collapsed_changed = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._entries: List[ConversationEntry] = []
        self._items: Dict[str, AIConversationItem] = {}
        self._section_labels: List[QLabel] = []
        self._current_id: Optional[str] = None
        self._filter_text = ""
        self._collapsed = False
        self._width_animation: Optional[QParallelAnimationGroup] = None

        self.setFixedWidth(EXPANDED_WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setAttribute(Qt.WA_StyledBackground, False)

        self._build_ui()
        tm.theme_changed.connect(self._on_theme_changed)
        tm.colors_updated.connect(self._on_theme_changed)
        self._apply_qss()

    # ------------------------------------------------------------------
    # UI 搭建
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """搭建品牌区、新建、搜索、列表与用户卡片。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 品牌区
        brand = QWidget(self)
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(12, 10, 8, 10)
        brand_layout.setSpacing(8)
        self._brand_icon = QLabel(brand)
        self._brand_icon.setFixedSize(28, 28)
        self._brand_icon.setPixmap(make_ai_avatar_pixmap(28))
        self._brand_title = QLabel("FreeAsset AI", brand)
        self._brand_title.setObjectName("StyledAIChatSidebarBrand")
        self._collapse_button = StyledIconButton(
            "panel_left",
            size="default",
            shape="square",
            variant="ghost",
            tooltip="折叠侧边栏",
            parent=brand,
        )
        self._collapse_button.clicked.connect(self._toggle_collapsed)
        brand_layout.addWidget(self._brand_icon, 0, Qt.AlignVCenter)
        brand_layout.addWidget(self._brand_title, 1, Qt.AlignVCenter)
        brand_layout.addWidget(self._collapse_button, 0, Qt.AlignVCenter)
        root.addWidget(brand)

        # 新建对话
        self._new_button = StyledButton(
            "新建对话",
            variant="primary",
            icon="+",
            block=True,
            parent=self,
        )
        self._new_button.setFixedHeight(36)
        self._new_button.clicked.connect(lambda: self.new_chat_requested.emit())
        self._compact_new_button = StyledIconButton(
            "plus",
            size="lg",
            shape="circle",
            variant="accent",
            tooltip="新建对话",
            parent=self,
        )
        self._compact_new_button.clicked.connect(
            lambda: self.new_chat_requested.emit()
        )
        self._compact_new_button.hide()

        new_host = QWidget(self)
        new_layout = QVBoxLayout(new_host)
        new_layout.setContentsMargins(12, 0, 12, 8)
        new_layout.setSpacing(0)
        new_layout.addWidget(self._new_button)
        root.addWidget(new_host)
        self._new_host = new_host

        # 搜索
        self._search = _SidebarSearchEdit(self)
        self._search.textChanged.connect(self._on_search_changed)
        search_host = QWidget(self)
        search_layout = QVBoxLayout(search_host)
        search_layout.setContentsMargins(12, 0, 12, 8)
        search_layout.setSpacing(0)
        search_layout.addWidget(self._search)
        root.addWidget(search_host)
        self._search_host = search_host

        # 会话列表
        self._scroll = StyledScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(StyledScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_host = QWidget(self._scroll)
        self._list_layout = QVBoxLayout(self._scroll_host)
        self._list_layout.setContentsMargins(8, 4, 8, 8)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch(1)
        self._scroll.setWidget(self._scroll_host)
        root.addWidget(self._scroll, 1)

        # 空结果提示
        self._empty_label = QLabel("没有找到对话", self)
        self._empty_label.setObjectName("StyledAIChatSidebarEmpty")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.hide()
        root.addWidget(self._empty_label)

        # 用户卡片
        self._footer = QWidget(self)
        footer_layout = QHBoxLayout(self._footer)
        footer_layout.setContentsMargins(12, 8, 8, 8)
        footer_layout.setSpacing(8)
        self._avatar = StyledAvatar("本", size="sm", parent=self._footer)
        self._user_name = QLabel("本地用户", self._footer)
        self._user_name.setObjectName("StyledAIChatSidebarUser")
        self._user_sub = QLabel("演示模式", self._footer)
        self._user_sub.setObjectName("StyledAIChatSidebarUserSub")
        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(0)
        text_column.addWidget(self._user_name)
        text_column.addWidget(self._user_sub)
        self._settings_button = StyledIconButton(
            "gear",
            size="default",
            shape="square",
            variant="ghost",
            tooltip="设置",
            parent=self._footer,
        )
        self._settings_button.clicked.connect(lambda: self.settings_requested.emit())
        footer_layout.addWidget(self._avatar, 0, Qt.AlignVCenter)
        footer_layout.addLayout(text_column, 1)
        footer_layout.addWidget(self._settings_button, 0, Qt.AlignVCenter)
        root.addWidget(self._footer)

    def _apply_qss(self) -> None:
        """注册品牌 / 用户 / 空状态文字样式。"""
        register_widget_qss(
            self._brand_title,
            f"color: {tm.qss_color(tm.text)};"
            f' font-family: "{FONT_FAMILY}";'
            f" font-size: {StyledLineEdit.SIZE_CONFIG['default']['font_size']}px;"
            " font-weight: 600;",
        )
        register_widget_qss(
            self._user_name,
            f"color: {tm.qss_color(tm.text)};"
            f' font-family: "{FONT_FAMILY}";'
            f" font-size: {StyledLineEdit.SIZE_CONFIG['default']['font_size']}px;",
        )
        register_widget_qss(
            self._user_sub,
            f"color: {tm.qss_color(tm.text_secondary)};"
            f' font-family: "{FONT_FAMILY}";'
            f" font-size: {StyledLineEdit.SIZE_CONFIG['sm']['font_size']}px;",
        )
        register_widget_qss(
            self._empty_label,
            f"color: {tm.qss_color(tm.text_hint)};"
            f' font-family: "{FONT_FAMILY}";'
            f" font-size: {StyledLineEdit.SIZE_CONFIG['sm']['font_size']}px;"
            " padding: 12px;",
        )

    # ------------------------------------------------------------------
    # 数据 API
    # ------------------------------------------------------------------

    def set_conversations(self, entries: List[ConversationEntry]) -> None:
        """替换全部会话并重建列表。

        Args:
            entries: 会话数据列表。
        """
        self._entries = list(entries)
        if self._current_id is None and self._entries:
            self._current_id = self._entries[0].id
        self._rebuild()

    def add_conversation(self, entry: ConversationEntry) -> None:
        """新增会话并选中。

        Args:
            entry: 会话数据。
        """
        self._entries.insert(0, entry)
        self._current_id = entry.id
        self._rebuild()

    def update_conversation(self, entry: ConversationEntry) -> None:
        """按 id 更新会话。

        Args:
            entry: 新的会话数据。
        """
        for index, current in enumerate(self._entries):
            if current.id == entry.id:
                self._entries[index] = entry
                break
        else:
            self._entries.insert(0, entry)
        self._rebuild()

    def remove_conversation(self, conversation_id: str) -> None:
        """删除会话并自动选中相邻项。

        Args:
            conversation_id: 会话 id。
        """
        index = next(
            (i for i, item in enumerate(self._entries) if item.id == conversation_id),
            -1,
        )
        if index < 0:
            return
        self._entries.pop(index)
        if self._current_id == conversation_id:
            if self._entries:
                self._current_id = self._entries[min(index, len(self._entries) - 1)].id
            else:
                self._current_id = None
        self._rebuild()

    def select_conversation(self, conversation_id: str, emit: bool = True) -> None:
        """选中会话。

        Args:
            conversation_id: 会话 id。
            emit: 是否发出 :attr:`conversation_selected`。
        """
        if conversation_id == self._current_id and emit:
            self.conversation_selected.emit(conversation_id)
            return
        self._current_id = conversation_id
        self._sync_active()
        if emit:
            self.conversation_selected.emit(conversation_id)

    def current_id(self) -> Optional[str]:
        """返回当前选中的会话 id。

        Returns:
            会话 id；无选中时返回 None。
        """
        return self._current_id

    def conversations(self) -> List[ConversationEntry]:
        """返回当前会话数据副本。

        Returns:
            会话列表。
        """
        return list(self._entries)

    def filter(self, text: str) -> None:
        """按标题过滤会话。

        Args:
            text: 关键词。
        """
        self._filter_text = (text or "").strip().lower()
        self._rebuild()

    def set_collapsed(self, collapsed: bool) -> None:
        """展开 / 折叠侧边栏。

        Args:
            collapsed: True 折叠。
        """
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed

        self._brand_title.setVisible(not collapsed)
        self._new_button.setVisible(not collapsed)
        self._compact_new_button.setVisible(collapsed)
        self._search_host.setVisible(not collapsed)
        self._user_name.setVisible(not collapsed)
        self._user_sub.setVisible(not collapsed)
        self._settings_button.setVisible(not collapsed)
        self._footer.layout().setContentsMargins(
            12 if not collapsed else 0, 8, 8 if not collapsed else 0, 8
        )
        self._new_host.layout().setContentsMargins(
            12 if not collapsed else 8, 0, 12 if not collapsed else 8, 8
        )
        self._new_host.layout().removeWidget(self._compact_new_button)
        self._new_host.layout().addWidget(
            self._compact_new_button if collapsed else self._new_button
        )
        for item in self._items.values():
            item.set_compact(collapsed)
        for label in self._section_labels:
            label.setVisible(not collapsed)

        target = COMPACT_WIDTH if collapsed else EXPANDED_WIDTH
        self._animate_width(target)
        self.collapsed_changed.emit(collapsed)

    def is_collapsed(self) -> bool:
        """返回是否折叠。

        Returns:
            折叠状态。
        """
        return self._collapsed

    # ------------------------------------------------------------------
    # 内部：列表重建
    # ------------------------------------------------------------------

    def _visible_entries(self) -> List[ConversationEntry]:
        """返回过滤后的会话。

        Returns:
            匹配关键词的会话列表。
        """
        if not self._filter_text:
            return list(self._entries)
        return [
            entry
            for entry in self._entries
            if self._filter_text in entry.title.lower()
        ]

    def _entry_group(self, entry: ConversationEntry) -> str:
        """返回会话所属分组。

        Args:
            entry: 会话数据。

        Returns:
            分组名。
        """
        return "置顶" if entry.pinned else (entry.group or "今天")

    def _clear_list(self) -> None:
        """移除列表中的全部控件。"""
        self._items.clear()
        self._section_labels.clear()
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _rebuild(self) -> None:
        """按过滤条件与分组重建会话列表。"""
        self._clear_list()
        visible = self._visible_entries()
        self._empty_label.setVisible(bool(self._filter_text) and not visible)

        grouped: Dict[str, List[ConversationEntry]] = {}
        for entry in visible:
            grouped.setdefault(self._entry_group(entry), []).append(entry)

        ordered_groups = [name for name in GROUP_ORDER if name in grouped]
        ordered_groups.extend(name for name in grouped if name not in ordered_groups)

        for group in ordered_groups:
            label = QLabel(group, self._scroll_host)
            label.setObjectName("StyledAIChatSidebarSection")
            label.setContentsMargins(14, 8, 14, 4)
            self._apply_section_style(label)
            label.setVisible(not self._collapsed)
            self._section_labels.append(label)
            self._list_layout.insertWidget(self._list_layout.count() - 1, label)

            for entry in grouped[group]:
                item = AIConversationItem(entry, compact=self._collapsed, parent=self._scroll_host)
                item.set_active(entry.id == self._current_id)
                item.clicked.connect(lambda it=item: self.select_conversation(it.entry.id))
                item.delete_requested.connect(self.delete_requested.emit)
                item.rename_requested.connect(self.rename_requested.emit)
                self._items[entry.id] = item
                self._list_layout.insertWidget(self._list_layout.count() - 1, item)

    def _apply_section_style(self, label: QLabel) -> None:
        """注册分组标题样式。

        Args:
            label: 分组标题控件。
        """
        register_widget_qss(
            label,
            f"color: {tm.qss_color(tm.text_secondary)};"
            f' font-family: "{FONT_FAMILY}";'
            f" font-size: {StyledLineEdit.SIZE_CONFIG['sm']['font_size']}px;"
            " font-weight: 600;",
        )

    def _sync_active(self) -> None:
        """同步所有会话项的选中态。"""
        for conversation_id, item in self._items.items():
            item.set_active(conversation_id == self._current_id)

    def _on_search_changed(self, text: str) -> None:
        """搜索文本变化：过滤并转发信号。

        Args:
            text: 搜索文本。
        """
        self.filter(text)
        self.search_changed.emit(text)

    def _toggle_collapsed(self) -> None:
        """折叠按钮入口。"""
        self.set_collapsed(not self._collapsed)

    # ------------------------------------------------------------------
    # 内部：宽度动画
    # ------------------------------------------------------------------

    def _animate_width(self, target: int) -> None:
        """动画调整侧边栏宽度。

        Args:
            target: 目标宽度。
        """
        if self._width_animation is not None:
            self._width_animation.stop()
            self._width_animation = None

        duration = 220 if is_animation_enabled("ai_chat") else 0
        if duration == 0:
            self.setFixedWidth(target)
            return

        start = self.width()
        group = QParallelAnimationGroup(self)
        for prop in (b"minimumWidth", b"maximumWidth"):
            anim = QPropertyAnimation(self, prop, group)
            anim.setDuration(duration)
            anim.setStartValue(start)
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.InOutCubic)
            group.addAnimation(anim)
        group.finished.connect(lambda: self.setFixedWidth(target))
        self._width_animation = group
        group.start()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制侧边栏底、右分隔线与用户卡片上边线。

        Args:
            event: Qt 绘制事件。
        """
        painter = QPainter(self)
        painter.fillRect(self.rect(), tm.surface)
        painter.setPen(tm.alpha_of(tm.text, 8))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        footer_top = self._footer.y()
        painter.drawLine(0, footer_top, self.width() - 1, footer_top)
        painter.end()

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后刷新头像、样式与列表。

        Args:
            _theme: 新主题名（未使用）。
        """
        self._brand_icon.setPixmap(make_ai_avatar_pixmap(28))
        self._apply_qss()
        for label in self._section_labels:
            self._apply_section_style(label)
        self.update()


__all__ = [
    "StyledAIChatSidebar",
    "AIConversationItem",
    "ConversationEntry",
    "EXPANDED_WIDTH",
    "COMPACT_WIDTH",
]
