# -*- coding: utf-8 -*-
"""AI 对话多行输入器（styled 组件）。

由三部分组成：

* :class:`StyledAIModelChip` —— 模型胶囊，点击弹出 :class:`StyledContextMenu`；
* :class:`_ComposerTextEdit` —— 透明底多行编辑器，1–6 行自动增高；
* :class:`StyledAIComposer` —— 圆角卡片 + 附件 / 模型 / 快捷键提示 / 发送。

所有颜色来自 :mod:`theme` 的 ``tm`` 令牌，字号来自 ``StyledLineEdit`` 的
``SIZE_CONFIG``，字体族使用该组件导出的 ``FONT_FAMILY``；不写死色值与字号。
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QKeyEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from freeassetfilter.ui.components.icon_utils import render_icon
from freeassetfilter.ui.components.styled_context_menu import StyledContextMenu
from freeassetfilter.ui.components.styled_icon_button import StyledIconButton
from freeassetfilter.ui.components.styled_lineedit import (
    StyledLineEdit,
    styled_font,
)
from freeassetfilter.ui.components.styled_scroll_area import StyledScrollBar
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss
from theme import tm

#: 输入器卡片圆角（与气泡 / 浮层圆角一致）。
CARD_RADIUS = 8
#: 卡片外留白（用于投影）。
SHADOW_MARGIN = 6
#: 编辑器最少 / 最多显示行数。
MIN_LINES = 1
MAX_LINES = 6


class StyledAIModelChip(QAbstractButton):
    """模型选择胶囊。

    Args:
        model: 初始模型名。
        parent: 父控件。

    Signals:
        model_selected: 用户从菜单选择模型后发出，携带模型名。
    """

    model_selected = Signal(str)

    #: 胶囊高度（与 ``StyledLineEdit`` sm 档高度一致）。
    HEIGHT = StyledLineEdit.SIZE_CONFIG["sm"]["height"]
    #: 胶囊字号（与 ``StyledLineEdit`` sm 档一致）。
    FONT_SIZE = StyledLineEdit.SIZE_CONFIG["sm"]["font_size"]

    def __init__(self, model: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._model = model or "默认模型"
        self._models: List[str] = []
        self._hovered = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._font = styled_font(self.FONT_SIZE)
        self.setFont(self._font)
        self.clicked.connect(self._open_menu)
        tm.theme_changed.connect(self._on_theme_changed)
        tm.colors_updated.connect(self._on_theme_changed)

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def set_models(self, models: List[str]) -> None:
        """设置可选模型列表。

        Args:
            models: 模型名列表。
        """
        self._models = [str(item) for item in models if str(item).strip()]

    def set_model(self, model: str) -> None:
        """设置当前模型名并刷新宽度。

        Args:
            model: 模型名。
        """
        self._model = model or "默认模型"
        self.updateGeometry()
        self.update()

    def model(self) -> str:
        """返回当前模型名。

        Returns:
            模型名。
        """
        return self._model

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        """返回按文字宽度计算的胶囊尺寸。

        Returns:
            胶囊 QSize。
        """
        metrics = QFontMetrics(self._font)
        width = metrics.horizontalAdvance(self._model) + 34
        return QSize(width, self.HEIGHT)

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制胶囊底、模型名与下拉箭头。

        Args:
            event: Qt 绘制事件。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        fill = (
            tm.alpha_of(tm.text, 8)
            if self._hovered and self.isEnabled()
            else tm.alpha_of(tm.text, 5)
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, self.HEIGHT / 2.0, self.HEIGHT / 2.0)

        painter.setPen(tm.text_secondary)
        painter.setFont(self._font)
        text_rect = rect.adjusted(10, 0, -22, 0)
        painter.drawText(
            text_rect,
            Qt.AlignVCenter | Qt.AlignLeft,
            QFontMetrics(self._font).elidedText(
                self._model, Qt.ElideRight, int(text_rect.width())
            ),
        )

        icon_side = 14.0
        icon_rect = QRectF(
            rect.right() - 18.0,
            (rect.height() - icon_side) / 2.0,
            icon_side,
            icon_side,
        )
        render_icon(
            painter,
            "chevron_down",
            icon_rect,
            QColor(tm.text_secondary),
            1.8,
        )
        painter.end()

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------

    def _open_menu(self) -> None:
        """在胶囊下方弹出模型菜单。"""
        if not self._models:
            return
        menu = StyledContextMenu(parent=self.window())
        for name in self._models:
            menu.add_item(
                name,
                callback=lambda value=name: self._choose(value),
                checkable=True,
                checked=(name == self._model),
            )
        menu.exec(self.mapToGlobal(QPoint(0, self.height() + 4)))

    def _choose(self, model: str) -> None:
        """应用选中的模型并发出信号。

        Args:
            model: 模型名。
        """
        self.set_model(model)
        self.model_selected.emit(model)

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


class _ComposerTextEdit(QPlainTextEdit):
    """输入器内部的多行编辑器。

    Args:
        parent: 父控件。

    Signals:
        submit_requested: 用户按下 Enter（未按 Shift、非输入法组字）。
        focus_changed: 焦点进入 / 离开。
    """

    submit_requested = Signal()
    focus_changed = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._composing = False
        self.setObjectName("StyledAIComposerEdit")
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBar(StyledScrollBar(self))
        self.setTabChangesFocus(True)
        self.setFont(
            styled_font(StyledLineEdit.SIZE_CONFIG["default"]["font_size"])
        )
        self.document().setDocumentMargin(0)
        self.setContentsMargins(0, 0, 0, 0)
        self.viewport().setAutoFillBackground(False)

        tm.theme_changed.connect(self._on_theme_changed)
        tm.colors_updated.connect(self._on_theme_changed)
        self._apply_qss()

    def _apply_qss(self) -> None:
        """注册编辑器样式（透明底 + 主题文字色）。"""
        selection_text = tm.readable_on(tm.accent)
        register_widget_qss(
            self,
            f"""
            #StyledAIComposerEdit {{
                background: transparent;
                border: none;
                color: {tm.qss_color(tm.text)};
                font-size: {StyledLineEdit.SIZE_CONFIG["default"]["font_size"]}px;
                selection-background-color: {tm.qss_color(tm.accent)};
                selection-color: {tm.qss_color(selection_text)};
            }}
            """,
        )
        palette = self.palette()
        palette.setColor(QPalette.PlaceholderText, tm.text_hint)
        self.setPalette(palette)

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后重新注册样式。

        Args:
            _theme: 新主题名（未使用）。
        """
        self._apply_qss()

    def inputMethodEvent(self, event: object) -> None:
        """跟踪输入法组字状态。

        Args:
            event: Qt 输入法事件。
        """
        preedit = getattr(event, "preeditString", lambda: "")()
        self._composing = bool(preedit)
        super().inputMethodEvent(event)  # type: ignore[arg-type]

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Enter 发送、Shift+Enter 换行。

        Args:
            event: 键盘事件。
        """
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)
                return
            if not self._composing:
                self.submit_requested.emit()
                event.accept()
                return
        super().keyPressEvent(event)

    def focusInEvent(self, event: object) -> None:
        """焦点进入。

        Args:
            event: Qt 焦点事件。
        """
        super().focusInEvent(event)  # type: ignore[arg-type]
        self.focus_changed.emit(True)

    def focusOutEvent(self, event: object) -> None:
        """焦点离开。

        Args:
            event: Qt 焦点事件。
        """
        super().focusOutEvent(event)  # type: ignore[arg-type]
        self.focus_changed.emit(False)


class StyledAIComposer(QWidget):
    """AI 对话多行输入器。

    Args:
        placeholder: 占位文案。
        models: 可选模型列表（传给模型胶囊）。
        model: 初始模型名。
        parent: 父控件。

    Signals:
        send_requested: 提交非空文本，携带文本内容。
        stop_requested: 忙碌态下点击停止。
        attach_requested: 点击附件按钮。
        model_changed: 模型切换，携带模型名。
    """

    send_requested = Signal(str)
    stop_requested = Signal()
    attach_requested = Signal()
    model_changed = Signal(str)

    def __init__(
        self,
        placeholder: str = "给 AI 发送消息…",
        models: Optional[List[str]] = None,
        model: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._enabled = True
        self._busy = False
        self._focused = False

        self._editor = _ComposerTextEdit(self)
        self._editor.setPlaceholderText(placeholder)
        self._editor.submit_requested.connect(self._submit)
        self._editor.textChanged.connect(self._sync_state)
        self._editor.focus_changed.connect(self._on_focus_changed)

        self.attach_button = StyledIconButton(
            "paperclip",
            size="default",
            shape="square",
            variant="ghost",
            tooltip="添加图片或文件",
            parent=self,
        )
        self.attach_button.clicked.connect(lambda: self.attach_requested.emit())

        self.model_chip = StyledAIModelChip(model, self)
        if models:
            self.model_chip.set_models(models)
        self.model_chip.model_selected.connect(self._on_model_selected)

        self._hint = QLabel("Enter 发送 · Shift+Enter 换行", self)
        self._hint.setObjectName("StyledAIComposerHint")
        self._hint.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        self.send_button = StyledIconButton(
            "send",
            size="lg",
            shape="circle",
            variant="accent",
            tooltip="发送",
            parent=self,
        )
        self.send_button.clicked.connect(self._submit)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        toolbar.addWidget(self.attach_button, 0, Qt.AlignVCenter)
        toolbar.addWidget(self.model_chip, 0, Qt.AlignVCenter)
        toolbar.addStretch(1)
        toolbar.addWidget(self._hint, 0, Qt.AlignVCenter)
        toolbar.addWidget(self.send_button, 0, Qt.AlignVCenter)

        root = QVBoxLayout(self)
        root.setContentsMargins(
            SHADOW_MARGIN + 14,
            SHADOW_MARGIN + 10,
            SHADOW_MARGIN + 14,
            SHADOW_MARGIN + 10,
        )
        root.setSpacing(6)
        root.addWidget(self._editor)
        root.addLayout(toolbar)

        tm.theme_changed.connect(self._on_theme_changed)
        tm.colors_updated.connect(self._on_theme_changed)
        self._apply_qss()
        self._update_editor_height()
        self._sync_state()

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def text(self) -> str:
        """返回编辑器当前文本。

        Returns:
            文本（未去空白）。
        """
        return self._editor.toPlainText()

    def set_text(self, text: str) -> None:
        """设置编辑器文本并把光标移到末尾。

        Args:
            text: 新文本。
        """
        self._editor.setPlainText(text)
        cursor = self._editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._editor.setTextCursor(cursor)
        self._update_editor_height()
        self._sync_state()

    def clear(self) -> None:
        """清空编辑器。"""
        self._editor.clear()

    def focus(self) -> None:
        """把键盘焦点交给编辑器。"""
        self._editor.setFocus(Qt.OtherFocusReason)

    def set_busy(self, busy: bool) -> None:
        """切换发送 / 停止状态。

        Args:
            busy: True 时发送按钮变为停止按钮。
        """
        self._busy = bool(busy)
        self.send_button.set_icon("stop" if self._busy else "send")
        self.send_button.set_tooltip("停止生成" if self._busy else "发送")
        self._sync_state()

    def set_model(self, model: str) -> None:
        """设置模型胶囊文案。

        Args:
            model: 模型名。
        """
        self.model_chip.set_model(model)

    def set_models(self, models: List[str]) -> None:
        """设置模型菜单列表。

        Args:
            models: 模型名列表。
        """
        self.model_chip.set_models(models)

    def set_enabled(self, enabled: bool) -> None:
        """启用 / 禁用输入器。

        Args:
            enabled: True 启用。
        """
        self._enabled = bool(enabled)
        self._editor.setEnabled(self._enabled)
        self.attach_button.setEnabled(self._enabled)
        self.model_chip.setEnabled(self._enabled)
        self._sync_state()

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _submit(self) -> None:
        """提交文本或停止生成。"""
        if self._busy:
            self.stop_requested.emit()
            return
        text = self._editor.toPlainText().strip()
        if not text or not self._enabled:
            return
        self._editor.clear()
        self.send_requested.emit(text)

    def _sync_state(self) -> None:
        """同步发送按钮可用状态与编辑器高度。"""
        has_text = bool(self._editor.toPlainText().strip())
        self.send_button.setEnabled(
            self._enabled and (self._busy or has_text)
        )
        self._update_editor_height()

    def _update_editor_height(self) -> None:
        """按文档高度在 1–6 行之间调整编辑器高度。"""
        metrics = QFontMetrics(self._editor.font())
        line_height = max(1, metrics.lineSpacing())
        vertical_padding = 8
        min_height = line_height * MIN_LINES + vertical_padding * 2
        max_height = line_height * MAX_LINES + vertical_padding * 2

        document_height = int(self._editor.document().size().height()) + vertical_padding * 2
        height = max(min_height, min(max_height, document_height))
        if self._editor.height() != height:
            self._editor.setFixedHeight(height)

    def _on_focus_changed(self, focused: bool) -> None:
        """编辑器焦点变化：刷新卡片描边。

        Args:
            focused: 是否获得焦点。
        """
        self._focused = bool(focused)
        self.update()

    def _on_model_selected(self, model: str) -> None:
        """转发模型切换信号。

        Args:
            model: 模型名。
        """
        self.model_changed.emit(model)

    def _apply_qss(self) -> None:
        """注册提示文案样式。"""
        register_widget_qss(
            self._hint,
            f"color: {tm.qss_color(tm.text_hint)};"
            f" font-size: {StyledLineEdit.SIZE_CONFIG['sm']['font_size']}px;",
        )

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后重新注册样式并重绘。

        Args:
            _theme: 新主题名（未使用）。
        """
        self._apply_qss()
        self.update()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制卡片底、投影与焦点描边。

        Args:
            event: Qt 绘制事件。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        card = QRectF(self.rect()).adjusted(
            SHADOW_MARGIN, SHADOW_MARGIN, -SHADOW_MARGIN, -SHADOW_MARGIN
        )
        if card.width() <= 0 or card.height() <= 0:
            painter.end()
            return

        painter.setPen(Qt.NoPen)
        for spread, alpha, dy in ((2.0, 18.0, 2.0), (0.0, 10.0, 1.0)):
            shadow = QColor(tm.black)
            shadow.setAlpha(int(alpha))
            painter.setBrush(shadow)
            painter.drawRoundedRect(
                card.adjusted(-spread, -spread + dy, spread, spread + dy),
                CARD_RADIUS,
                CARD_RADIUS,
            )

        painter.setBrush(QColor(tm.card_fill))
        painter.drawRoundedRect(card, CARD_RADIUS, CARD_RADIUS)

        border = tm.accent if self._focused else tm.card_border
        painter.setBrush(Qt.NoBrush)
        painter.setPen(border)
        painter.drawRoundedRect(
            card.adjusted(0.5, 0.5, -0.5, -0.5), CARD_RADIUS, CARD_RADIUS
        )
        painter.end()


__all__ = ["StyledAIComposer", "StyledAIModelChip", "CARD_RADIUS"]
