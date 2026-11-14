# -*- coding: utf-8 -*-
"""窗口级模态守卫（自定义模态）。

背景
----
:class:`~components.styled_dialog.StyledDialog` 是独立顶层窗口，默认既没有
``Qt.WindowModal`` 也没有瞬态父窗口。于是弹窗显示期间主界面照常接收鼠标/
键盘事件：用户可以再次点击「筛选」「收藏夹」等入口，重复弹出多个弹窗。

Qt 原生 ``setWindowModality(Qt.WindowModal)`` 能在事件分发前吞掉宿主窗口的
全部输入，但**连标题栏 ✕ 一起吞掉**——用户被弹窗卡住，无法关闭主界面。
产品要求「弹窗期间主界面不可点，但 ✕ 仍可关主窗」，因此这里用应用级事件
过滤器实现一份可控的模态：

* 只拦截「目标是被遮挡窗口子树」的鼠标按键 / 滚轮 / 键盘 / 上下文菜单；
* 目标控件（或其祖先）带 :data:`MODAL_PASSTHROUGH_PROPERTY` 属性时放行
  （标题栏 ✕ 用它标记，见 ``MainWindow._create_title_bar``）；
* 弹窗自身的控件完全不受影响；
* 支持嵌套：内层弹窗把「宿主窗口 + 外层弹窗」一并记为遮挡目标，因此内层
  关闭后外层仍能正确遮挡主界面；
* 点击被遮挡区域时把弹窗提到前台（避免弹窗被其它窗口盖住却仍在拦截）。

``MouseMove`` / ``Enter`` / ``Leave`` 一律放行：悬停与光标反馈保留，也避免
被遮挡控件卡在「hover 中」状态。

使用
----
通常不直接调用：:func:`components.styled_dialog._show_dialog` 会在弹窗
``modal=True`` 时自动 :meth:`ModalGuard.push`。测试与退出路径可用
:func:`get_modal_guard` 取实例。
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget

#: 控件动态属性名：带该属性（或祖先带该属性）的控件在模态期间仍可交互。
#: 目前只有标题栏的 ✕ 使用——保证弹窗打开时仍能关闭主窗口。
MODAL_PASSTHROUGH_PROPERTY = "sp_modal_passthrough"

#: 需要拦截的事件类型。刻意不含 MouseMove/Enter/Leave（见模块 docstring）。
_BLOCKED_EVENT_TYPES = frozenset({
    QEvent.Type.MouseButtonPress,
    QEvent.Type.MouseButtonRelease,
    QEvent.Type.MouseButtonDblClick,
    QEvent.Type.Wheel,
    QEvent.Type.KeyPress,
    QEvent.Type.KeyRelease,
    QEvent.Type.ContextMenu,
})

#: 模块级单例与其所属 QApplication（测试中 QApplication 可能被重建）。
_guard: Optional["ModalGuard"] = None
_guard_app = None


class _ModalScope:
    """一次模态作用域：一个弹窗 + 它遮挡的窗口集合。"""

    __slots__ = ("dialog", "owner", "blocked")

    def __init__(
        self,
        dialog: QWidget,
        owner: Optional[QWidget],
        blocked: set,
    ) -> None:
        self.dialog = dialog
        self.owner = owner
        self.blocked = blocked


def _dialog_alive(dialog: QWidget) -> bool:
    """判断弹窗是否仍在"有效显示"状态（关闭中即视为失效）。

    ``StyledDialog`` 的退场动画会让窗口在 ``close()`` 之后继续可见约
    180ms；这段窗口期必须立即解除模态，否则用户关掉弹窗后立刻点击会被
    幽灵模态吞掉。``_is_closing`` 是 ``StyledDialog`` 的关闭中标记，
    非 StyledDialog 的弹窗退化为仅看 ``isVisible()``。

    Args:
        dialog: 待判断的弹窗控件。

    Returns:
        bool: True 表示弹窗仍应保持遮挡。
    """
    try:
        if getattr(dialog, "_is_closing", False):
            return False
        return bool(dialog.isVisible())
    except RuntimeError:
        return False


class ModalGuard(QObject):
    """应用级事件过滤器，实现「宿主窗口不可点、弹窗可点」的模态语义。"""

    def __init__(self) -> None:
        super().__init__()
        self._scopes: List[_ModalScope] = []

    # ── 栈操作 ─────────────────────────────────────────────────────────

    def push(self, dialog: QWidget, owner: Optional[QWidget] = None) -> None:
        """登记一个模态弹窗。

        遮挡集合 = 宿主窗口 ∪ 所有已登记作用域的遮挡集合（嵌套弹窗因此
        能同时挡住主界面与外层弹窗）。重复 push 同一弹窗会先移除旧作用域，
        避免重复登记导致引用泄漏。

        Args:
            dialog: 模态弹窗（通常是 ``StyledDialog``）。
            owner: 被遮挡的宿主窗口；``None`` 表示只遮挡已登记的下层目标。
        """
        if not isinstance(dialog, QWidget):
            return
        self.pop_for(dialog)
        blocked: set = set()
        if isinstance(owner, QWidget):
            blocked.add(owner)
        for scope in self._scopes:
            blocked |= scope.blocked
        self._scopes.append(_ModalScope(dialog, owner, blocked))

        finished = getattr(dialog, "finished", None)
        if finished is not None:
            try:
                finished.connect(lambda *_: self.pop_for(dialog))
            except (RuntimeError, TypeError):
                pass
        closing = getattr(dialog, "closing", None)
        if closing is not None:
            try:
                closing.connect(lambda *_: self.pop_for(dialog))
            except (RuntimeError, TypeError):
                pass
        try:
            dialog.destroyed.connect(lambda *_: self.pop_for(dialog))
        except (RuntimeError, TypeError):
            pass

    def pop_for(self, dialog: object) -> None:
        """移除指定弹窗的作用域（幂等；弹窗销毁后仍可安全调用）。"""
        if not self._scopes:
            return
        self._scopes = [s for s in self._scopes if s.dialog is not dialog]

    def pop_owner(self, owner: object) -> None:
        """移除所有以 ``owner`` 为宿主的作用域（宿主关闭时兜底）。"""
        if not self._scopes:
            return
        self._scopes = [s for s in self._scopes if s.owner is not owner]

    def clear(self) -> None:
        """清空全部作用域（测试/退出兜底）。"""
        self._scopes.clear()

    # ── 查询 ───────────────────────────────────────────────────────────

    @property
    def active_dialog(self) -> Optional[QWidget]:
        """当前栈顶的模态弹窗；无作用域时返回 ``None``。"""
        self._prune()
        return self._scopes[-1].dialog if self._scopes else None

    def is_blocked(self, window: Optional[QWidget]) -> bool:
        """判断某个顶层窗口当前是否被模态遮挡。

        Args:
            window: 待查询的顶层窗口（通常为 ``widget.window()``）。

        Returns:
            bool: True 表示该窗口的输入应被拦截。
        """
        if window is None or not self._scopes:
            return False
        self._prune()
        return self._scope_for(window) is not None

    # ── 事件过滤 ───────────────────────────────────────────────────────

    def eventFilter(self, obj: object, event: QEvent) -> bool:
        """拦截被遮挡窗口的输入事件。

        Args:
            obj: 事件接收对象（应用级过滤下可能是非 QWidget）。
            event: 待过滤事件。

        Returns:
            bool: True 表示事件已被消费（不再分发到目标控件）。
        """
        if not self._scopes:
            return False
        if event.type() not in _BLOCKED_EVENT_TYPES:
            return False
        if not isinstance(obj, QWidget):
            return False

        self._prune()
        if not self._scopes:
            return False

        try:
            window = obj.window()
        except RuntimeError:
            return False
        scope = self._scope_for(window)
        if scope is None:
            return False
        if self._allows_passthrough(obj):
            return False
        if event.type() == QEvent.Type.MouseButtonPress:
            self._raise_dialog(scope.dialog)
        return True

    # ── 内部 ───────────────────────────────────────────────────────────

    def _scope_for(self, window: QWidget) -> Optional[_ModalScope]:
        """返回遮挡 ``window`` 的最内层作用域（``window`` 是弹窗自身时为 None）。"""
        for scope in reversed(self._scopes):
            if scope.dialog is window:
                return None
            try:
                if window in scope.blocked:
                    return scope
            except (RuntimeError, TypeError):
                continue
        return None

    def _prune(self) -> None:
        """剔除已关闭/已销毁弹窗的作用域，避免界面被永久锁死。

        退场动画期间弹窗仍 ``isVisible()``，但已进入关闭流程；此时必须
        立即解除遮挡——否则用户关掉弹窗后立刻再点，界面会被"幽灵模态"
        挡住约 180ms。
        """
        if not self._scopes:
            return
        alive: List[_ModalScope] = []
        for scope in self._scopes:
            if _dialog_alive(scope.dialog):
                alive.append(scope)
        if len(alive) != len(self._scopes):
            self._scopes = alive

    @staticmethod
    def _allows_passthrough(obj: QWidget) -> bool:
        """目标控件或其任一祖先带放行属性时返回 True（标题栏 ✕）。"""
        widget: Optional[QWidget] = obj
        while widget is not None:
            try:
                if widget.property(MODAL_PASSTHROUGH_PROPERTY):
                    return True
            except RuntimeError:
                return False
            widget = widget.parentWidget()
        return False

    @staticmethod
    def _raise_dialog(dialog: QWidget) -> None:
        """把弹窗提到前台（点击被遮挡区域时给出反馈）。"""
        try:
            dialog.raise_()
            dialog.activateWindow()
        except (RuntimeError, AttributeError):
            pass


def get_modal_guard() -> ModalGuard:
    """返回当前 QApplication 上的模态守卫（按需创建并安装事件过滤器）。

    Returns:
        ModalGuard: 进程内唯一实例。

    Raises:
        RuntimeError: 尚无 QApplication 实例时。
    """
    global _guard, _guard_app
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("ModalGuard 需要先创建 QApplication 实例")
    if _guard is None or _guard_app is not app:
        if _guard is not None and _guard_app is not None:
            try:
                _guard_app.removeEventFilter(_guard)
            except (RuntimeError, AttributeError):
                pass
        guard = ModalGuard()
        app.installEventFilter(guard)
        _guard = guard
        _guard_app = app
    return _guard
