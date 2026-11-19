"""弹窗内的空间焦点导航。

为什么不用 ``Tab`` 顺序
=======================
``Tab`` 顺序按「创建顺序」走，与视觉布局无关：筛选弹窗里按 ``↓`` 期望
到「移除筛选」按钮，按 ``←``/``→`` 期望在三个横向按钮间切换，按 ``↑``
期望回到搜索框——这些都是**几何邻近**关系，只能按控件实际位置推算。

算法
====
对每个可聚焦控件取其在弹窗内容区内的中心点，按方向筛选「在目标方向上」
的候选，用加权距离挑最近的：

- 主方向距离权重 1.0（必须为正，否则不是该方向）；
- 次方向偏移权重 2.0（鼓励同列/同行）；
- 距离按控件尺寸归一化，避免大控件因中心远而被跳过。

无候选时不移动（不环绕），符合桌面弹窗的常规手感。
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSpinBox,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QSlider,
    QTextEdit,
    QWidget,
)

#: 次方向偏移的权重（越大越倾向同列/同行）。
_CROSS_WEIGHT = 2.0


def _is_focusable(widget: QWidget) -> bool:
    """控件是否可被键盘聚焦并参与空间导航。

    Args:
        widget: 待判定控件。

    Returns:
        bool: 可聚焦、可见、启用时返回 True。
    """
    try:
        if not widget.isVisible() or not widget.isEnabled():
            return False
        policy = widget.focusPolicy()
    except RuntimeError:
        return False
    return policy not in (Qt.FocusPolicy.NoFocus,)


def collect_focusable(root: QWidget) -> List[QWidget]:
    """收集 ``root`` 子树内全部可聚焦控件（按视觉位置排序）。

    Args:
        root: 弹窗内容根控件。

    Returns:
        List[QWidget]: 可聚焦控件列表（先按 y 再按 x 排序）。
    """
    found: List[QWidget] = []
    for widget in root.findChildren(QWidget):
        if widget is root:
            continue
        if not _is_focusable(widget):
            continue
        # 只收「叶子级」可聚焦控件：容器自身可聚焦时会把子控件遮蔽
        if isinstance(widget, (QLineEdit, QComboBox, QAbstractButton)):
            found.append(widget)
            continue
        has_focusable_child = any(
            _is_focusable(child) for child in widget.findChildren(QWidget)
        )
        if not has_focusable_child:
            found.append(widget)
    found.sort(key=lambda w: (w.mapTo(root, QPoint(0, 0)).y(), w.mapTo(root, QPoint(0, 0)).x()))
    return found


def _center_in(widget: QWidget, root: QWidget) -> Optional[QPoint]:
    """取控件中心点（相对 ``root``）。

    Args:
        widget: 目标控件。
        root: 参照根控件。

    Returns:
        Optional[QPoint]: 中心点；控件已销毁时返回 ``None``。
    """
    try:
        top_left = widget.mapTo(root, QPoint(0, 0))
        return QPoint(top_left.x() + widget.width() // 2, top_left.y() + widget.height() // 2)
    except RuntimeError:
        return None


def _pick(
    current: QPoint,
    candidates: Sequence[Tuple[QWidget, QPoint]],
    direction: str,
) -> Optional[QWidget]:
    """按方向挑最近的可聚焦控件。

    两轮筛选：先按「严格主方向」（primary > 0）挑；若无候选，退化为
    「按次方向距离 + 总距离」挑最近的一个。退化保证在任何布局下方向键
    都有响应（例如 footer 与 body 因布局未结算而落在同一 y 时，按 ↓ 仍能
    到按钮而不是毫无反应）。

    Args:
        current: 当前焦点中心点。
        candidates: 候选 ``(控件, 中心点)`` 列表。
        direction: ``"up"`` / ``"down"`` / ``"left"`` / ``"right"``。

    Returns:
        Optional[QWidget]: 命中的控件；无候选返回 ``None``。
    """
    best: Optional[QWidget] = None
    best_score = float("inf")
    fallback: Optional[QWidget] = None
    fallback_score = float("inf")
    for widget, point in candidates:
        dx = point.x() - current.x()
        dy = point.y() - current.y()
        if direction == "up":
            primary, cross = -dy, abs(dx)
        elif direction == "down":
            primary, cross = dy, abs(dx)
        elif direction == "left":
            primary, cross = -dx, abs(dy)
        else:
            primary, cross = dx, abs(dy)
        total = abs(dx) + abs(dy)
        if total == 0:
            continue
        if primary > 0:
            score = primary + _CROSS_WEIGHT * cross
            if score < best_score:
                best_score = score
                best = widget
        elif total < fallback_score:
            fallback_score = total
            fallback = widget
    return best if best is not None else fallback


def move_focus(root: QWidget, direction: str) -> bool:
    """按方向把焦点移到几何上最近的控件。

    Args:
        root: 弹窗内容根控件。
        direction: ``"up"`` / ``"down"`` / ``"left"`` / ``"right"``。

    Returns:
        bool: 焦点发生移动返回 True。
    """
    from PySide6.QtWidgets import QApplication

    current_widget = QApplication.focusWidget()
    if _consumes_direction_natively(current_widget, direction):
        return False

    widgets = collect_focusable(root)
    if not widgets:
        return False

    if current_widget is None or current_widget not in widgets:
        # 无焦点：落到第一个（或最后一个，取决于方向）
        target = widgets[0] if direction in ("down", "right") else widgets[-1]
        try:
            target.setFocus(Qt.FocusReason.OtherFocusReason)
        except RuntimeError:
            return False
        return True

    current = _center_in(current_widget, root)
    if current is None:
        return False
    candidates = []
    for widget in widgets:
        if widget is current_widget:
            continue
        point = _center_in(widget, root)
        if point is not None:
            candidates.append((widget, point))
    target = _pick(current, candidates, direction)
    if target is None:
        return False
    try:
        target.setFocus(Qt.FocusReason.OtherFocusReason)
    except RuntimeError:
        return False
    return True


def _consumes_direction_natively(widget: Optional[QWidget], direction: str) -> bool:
    """控件是否本来就用该方向键做「自己的事」。

    列表 / 树 / 表格内部用 ``↑↓`` 移动选中行，下拉框用 ``↑↓`` 切值，
    微调框 / 滑块用 ``↑↓←→`` 调值。这些场景若被空间导航抢走，控件就废了。
    列表仅在第一行按 ``↑`` / 最后一行按 ``↓`` 时才让出焦点（回到搜索框）。

    Args:
        widget: 当前焦点控件（可为 ``None``）。
        direction: 方向键方向。

    Returns:
        bool: True 表示应把按键留给控件自己处理。
    """
    if widget is None:
        return False
    if isinstance(widget, QComboBox):
        return True
    if isinstance(widget, (QAbstractSpinBox, QSlider)):
        return True
    if isinstance(widget, (QTextEdit, QPlainTextEdit)):
        return True
    if isinstance(widget, QAbstractItemView):
        if direction not in ("up", "down"):
            return True
        model = widget.model()
        if model is None:
            return True
        row = widget.currentIndex().row()
        last = model.rowCount() - 1
        if direction == "up":
            return row > 0
        return row < last
    return False
