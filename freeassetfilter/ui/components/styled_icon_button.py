# -*- coding: utf-8 -*-
"""统一的小尺寸图标按钮（styled 组件）。

用于标题栏、会话头、输入器与侧边栏等紧凑区域的纯图标操作。所有颜色在
``paintEvent`` 中通过 :mod:`theme` 的 ``tm`` 令牌现取，深浅主题与用户自定义
强调色都会即时生效；图标统一由 :func:`icon_utils.render_icon` 绘制，保持
项目 24×24 归一化线性图标的观感。

Example:
    >>> button = StyledIconButton("paperclip", size="default", variant="ghost")
    >>> button.clicked.connect(handler)
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QAbstractButton, QWidget

from freeassetfilter.ui.components.icon_utils import render_icon
from theme import tm

#: 方形按钮圆角（与 ``styled_ai_chat.CONTROL_RADIUS`` 保持一致）。
SQUARE_RADIUS = 4


class StyledIconButton(QAbstractButton):
    """圆角 / 圆形图标按钮。

    Args:
        icon: ``icon_utils.ICON_PATHS`` 中的图标名（如 ``"paperclip"``）。
        size: 尺寸档位，``"sm"`` / ``"default"`` / ``"lg"``。
        shape: 形状，``"square"``（4px 圆角）或 ``"circle"``。
        variant: 颜色变体，``"ghost"`` / ``"subtle"`` / ``"accent"`` / ``"danger"``。
        checkable: 是否可切换选中态。
        checked: 初始选中态（仅 ``checkable=True`` 时生效）。
        tooltip: 悬停提示文案；为空时不创建提示。
        parent: 父控件。

    Signals:
        clicked: 继承自 ``QAbstractButton``。
    """

    #: 尺寸档位 → 按钮边长（像素），与现有控件高度体系一致。
    SIZE_CONFIG = {"sm": 24, "default": 28, "lg": 32}
    #: 尺寸档位 → 图标边长（像素）。
    ICON_SIZE = {"sm": 14, "default": 16, "lg": 18}
    #: 支持的形状。
    SHAPES = ("square", "circle")
    #: 支持的变体。
    VARIANTS = ("ghost", "subtle", "accent", "danger")

    def __init__(
        self,
        icon: str = "",
        size: str = "default",
        shape: str = "square",
        variant: str = "ghost",
        checkable: bool = False,
        checked: bool = False,
        tooltip: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._icon = str(icon or "")
        self._size = size if size in self.SIZE_CONFIG else "default"
        self._shape = shape if shape in self.SHAPES else "square"
        self._variant = variant if variant in self.VARIANTS else "ghost"
        self._hovered = False

        side = self.SIZE_CONFIG[self._size]
        self.setFixedSize(side, side)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover, True)
        if checkable:
            self.setCheckable(True)
            self.setChecked(bool(checked))
        if tooltip:
            self.set_tooltip(tooltip)

        tm.theme_changed.connect(self._on_theme_changed)
        tm.colors_updated.connect(self._on_theme_changed)

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def set_icon(self, icon: str) -> None:
        """替换图标。

        Args:
            icon: 新的图标名；未知名称会绘制为空。
        """
        self._icon = str(icon or "")
        self.update()

    def icon_name(self) -> str:
        """返回当前图标名。

        Returns:
            图标名。
        """
        return self._icon

    def set_variant(self, variant: str) -> None:
        """切换颜色变体。

        Args:
            variant: ``ghost`` / ``subtle`` / ``accent`` / ``danger``。
        """
        self._variant = variant if variant in self.VARIANTS else "ghost"
        self.update()

    def set_shape(self, shape: str) -> None:
        """切换形状。

        Args:
            shape: ``square`` / ``circle``。
        """
        self._shape = shape if shape in self.SHAPES else "square"
        self.update()

    def set_size(self, size: str) -> None:
        """切换尺寸档位。

        Args:
            size: ``sm`` / ``default`` / ``lg``。
        """
        self._size = size if size in self.SIZE_CONFIG else "default"
        side = self.SIZE_CONFIG[self._size]
        self.setFixedSize(side, side)
        self.updateGeometry()
        self.update()

    def set_tooltip(self, text: str) -> None:
        """设置悬停提示。

        Args:
            text: 提示文案；为空时移除提示。
        """
        self.setToolTip(text)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        """返回固定尺寸。

        Returns:
            按钮边长对应的 QSize。
        """
        side = self.SIZE_CONFIG[self._size]
        return QSize(side, side)

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def _radius(self) -> float:
        """返回当前形状对应的圆角半径。

        Returns:
            圆形取边长一半，方形取 :data:`SQUARE_RADIUS`。
        """
        if self._shape == "circle":
            return self.width() / 2.0
        return float(SQUARE_RADIUS)

    def _background(self) -> Optional[QColor]:
        """返回当前状态下的底色。

        Returns:
            需要绘制底色时返回 QColor；ghost 未悬停/未选中时返回 None。
        """
        if not self.isEnabled():
            if self._variant == "accent":
                return tm.alpha_of(tm.text, 6)
            return None
        pressed = self.isDown()
        checked = self.isChecked()

        if self._variant == "accent":
            if pressed:
                return QColor(tm.accent_active)
            if self._hovered:
                return QColor(tm.accent_hover)
            return QColor(tm.accent)

        if self._variant == "danger":
            if pressed:
                return tm.alpha_of(tm.danger, 22)
            if self._hovered or checked:
                return tm.alpha_of(tm.danger, 15)
            return None

        if self._variant == "subtle":
            if pressed:
                return tm.alpha_of(tm.text, 10)
            if self._hovered:
                return QColor(tm.hover_veil)
            return tm.alpha_of(tm.text, 5)

        # ghost
        if checked:
            return tm.accent_alpha(30)
        if pressed:
            return tm.alpha_of(tm.text, 10)
        if self._hovered:
            return QColor(tm.hover_veil)
        return None

    def _icon_color(self) -> QColor:
        """返回当前状态下的图标颜色。

        Returns:
            图标 QColor；禁用态使用 ``tm.text_disabled``。
        """
        if not self.isEnabled():
            return QColor(tm.text_disabled)
        if self._variant == "accent":
            return QColor(tm.readable_on(tm.accent))
        if self._variant == "danger":
            return QColor(tm.danger)
        if self.isChecked():
            return QColor(tm.accent_text)
        return QColor(tm.text)

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制圆角底与线性图标。

        Args:
            event: Qt 绘制事件。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        background = self._background()
        if background is not None:
            painter.setPen(Qt.NoPen)
            painter.setBrush(background)
            painter.drawRoundedRect(
                QRectF(self.rect()), self._radius(), self._radius()
            )

        icon_side = self.ICON_SIZE[self._size]
        icon_rect = QRectF(
            (self.width() - icon_side) / 2.0,
            (self.height() - icon_side) / 2.0,
            float(icon_side),
            float(icon_side),
        )
        render_icon(painter, self._icon, icon_rect, self._icon_color(), 1.8)
        painter.end()

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------

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

    def _on_theme_changed(self, _theme: str = "") -> None:
        """主题切换后重绘（颜色在绘制时取 ``tm`` 令牌）。

        Args:
            _theme: 新主题名（未使用）。
        """
        self.update()


__all__ = ["StyledIconButton", "SQUARE_RADIUS"]
