"""Styled Context Menu component — matches web context-menu exactly.

Provides a QMenu subclass with custom QSS styling, submenu support,
checkable items, and a smooth fade-in animation on show.
"""

from PySide6.QtWidgets import QMenu, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, QPropertyAnimation, QAbstractAnimation, QEasingCurve
from PySide6.QtGui import QColor, QAction

from theme import tm


class StyledContextMenu(QMenu):
    """A styled context menu matching the web component.

    Inherits ALL native QMenu behaviour: submenu positioning, edge-flip,
    keyboard navigation, click-outside-to-close.

    Usage::

        menu = StyledContextMenu()
        menu.add_item("Copy", shortcut="Ctrl+C",
                      callback=lambda: print("Copy"))
        menu.add_separator()
        menu.add_item("Delete", danger=True,
                      callback=lambda: print("Delete"))
        menu.exec(widget.mapToGlobal(QPoint(0, 0)))
    """

    def __init__(self, title: str = "", parent=None):
        super().__init__(title, parent)
        self._last_anim = None       # keep ref to prevent GC
        self.setStyleSheet(self._qss())

    # ── QSS ─────────────────────────────────────────────────────

    @staticmethod
    def _qss() -> str:
        """Return QSS for the menu and its items.

        Values align with global.qss QMenu section plus extended
        states for danger, disabled, and checkable items.
        """

        def _rgba(c: QColor) -> str:
            return f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha() / 255:.2f})"

        bg = tm.surface.name()
        text = tm.text.name()
        hover_bg = _rgba(tm.alpha_of(tm.fill, 60))
        border = _rgba(tm.alpha_of(tm.mid, 40))
        disabled = _rgba(tm.alpha_of(tm.mid, 40))
        danger = tm.danger.name()
        separator = _rgba(tm.alpha_of(tm.mid, 30))
        return (
            f"StyledContextMenu {{"
            f"  background-color: {bg};"
            f"  color: {text};"
            f"  border: 1px solid {border};"
            f"  border-radius: 8px;"
            f"  padding: 4px;"
            f"}}"
            f"StyledContextMenu::item {{"
            f"  padding: 8px 24px 8px 12px;"
            f"  border-radius: 4px;"
            f"}}"
            f"StyledContextMenu::item:selected {{"
            f"  background-color: {hover_bg};"
            f"}}"
            f"StyledContextMenu::item:disabled {{"
            f"  color: {disabled};"
            f"}}"
            f"StyledContextMenu::item[danger=\"true\"] {{"
            f"  color: {danger};"
            f"}}"
            f"StyledContextMenu::item[danger=\"true\"]:selected {{"
            f"  background-color: rgba(239, 68, 68, 0.15);"
            f"}}"
            f"StyledContextMenu::separator {{"
            f"  height: 1px;"
            f"  background-color: {separator};"
            f"  margin: 4px 8px;"
            f"}}"
            f"StyledContextMenu::indicator {{"
            f"  width: 16px;"
            f"  height: 16px;"
            f"  margin-left: 4px;"
            f"}}"
        )

    # ── Public API ─────────────────────────────────────────────

    def add_item(self, label: str,
                 shortcut: str = "",
                 callback=None,
                 disabled: bool = False,
                 danger: bool = False,
                 checkable: bool = False,
                 checked: bool = False) -> QAction:
        """Add a menu item.

        Args:
            label:        Display text.
            shortcut:     Keyboard shortcut (e.g. ``"Ctrl+C"``).
            callback:     Callable invoked when the item is triggered.
            disabled:     Gray out and block interaction.
            danger:       Render text in red (#ef4444).
            checkable:    Show a checkable toggle.
            checked:      Initial checked state (requires ``checkable=True``).

        Returns:
            The QAction for this item.
        """
        action = QAction(label, self)

        if shortcut:
            action.setShortcut(shortcut)

        if disabled:
            action.setEnabled(False)

        if danger:
            action.setProperty("danger", True)

        if checkable:
            action.setCheckable(True)
            if checked:
                action.setChecked(True)

        if callback:
            action.triggered.connect(callback)

        self.addAction(action)
        return action

    def add_separator(self):
        """Insert a visual separator line."""
        self.addSeparator()

    def add_submenu(self, label: str,
                    menu: "StyledContextMenu") -> QAction:
        """Attach a nested submenu.

        Args:
            label:  Display text for the submenu action.
            menu:   StyledContextMenu instance to nest.

        Returns:
            The QAction that opens the submenu.
        """
        action = self.addMenu(menu)
        action.setText(label)
        return action

    # ── Animation ──────────────────────────────────────────────

    def showEvent(self, event):
        """Fade-in animation on menu appearance."""
        super().showEvent(event)
        # Animate every time the menu is shown (not only the first).
        # 120 ms is fast enough not to feel sluggish on re-open.
        self._animate_in()

    def _animate_in(self):
        """Animate menu opacity from 0 → 1 over 120 ms (OutCubic)."""
        # Discard any previous animation/effect
        self.setGraphicsEffect(None)

        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)

        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(120)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        anim.start(QAbstractAnimation.DeleteWhenStopped)

        # Keep a reference so the animation lives long enough to start;
        # DeleteWhenStopped handles cleanup after that.
        self._last_anim = anim