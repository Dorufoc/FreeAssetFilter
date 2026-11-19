"""快捷键绑定键的归一化、比较与 Qt 键码互转。

设计要点
========
所有绑定都用**物理键码**（``event.key()``）而不是字符（``event.text()``），
原因：

- ``Ctrl+\\`` 在中文输入法下 ``text()`` 是空串或全角字符，但 ``key()``
  恒为 ``Key_Backslash``；
- ``Ctrl+,`` 的 ``text()`` 可能是 ``,`` 或 ``，``，``key()`` 恒为 ``Key_Comma``；
- 大小写锁定、键盘布局差异都只影响 ``text()``。

因此本模块完全不做字符归一化，只处理「键码 + 修饰键掩码」。

``KeypadModifier`` 必须屏蔽
---------------------------
小键盘的 ``+`` / ``-`` 会带 ``KeypadModifier`` 位。若不屏蔽，小键盘按键
永远匹配不上不含该位的绑定表项。

``+`` 的两种来源
----------------
主键盘打 ``+`` 需要 ``Shift``：``key()`` 是 ``Key_Equal`` + ``ShiftModifier``；
小键盘打 ``+``：``key()`` 是 ``Key_Plus`` + （屏蔽后的）无修饰键。
两者不是同一个键码，因此注册表里需要同时登记（见 ``registry.py``）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QKeySequence

# ── 修饰键掩码（QKeySequence 的 int 构造需要这些位） ──────────────────
_CTRL = int(Qt.KeyboardModifier.ControlModifier.value)
_ALT = int(Qt.KeyboardModifier.AltModifier.value)
_SHIFT = int(Qt.KeyboardModifier.ShiftModifier.value)
_META = int(Qt.KeyboardModifier.MetaModifier.value)

#: 归一化时必须清除的「非用户修饰键」。
#:
#: - ``KeypadModifier``：只表示按键来自小键盘，不改变语义。
#: - ``GroupSwitchModifier``：输入法组字切换键，与绑定无关。
_IGNORED_MODIFIERS = (
    int(Qt.KeyboardModifier.KeypadModifier.value)
    | int(Qt.KeyboardModifier.GroupSwitchModifier.value)
)

#: 纯修饰键：不能单独成为一个绑定。
_MODIFIER_KEYS = frozenset({
    int(Qt.Key.Key_Control.value),
    int(Qt.Key.Key_Shift.value),
    int(Qt.Key.Key_Alt.value),
    int(Qt.Key.Key_Meta.value),
    int(Qt.Key.Key_AltGr.value),
    int(Qt.Key.Key_CapsLock.value),
    int(Qt.Key.Key_NumLock.value),
    int(Qt.Key.Key_ScrollLock.value),
})


#: ``QKeySequence`` 解析失败时返回的哨兵键码（0x01FFFFFF）。
_INVALID_KEY = 0x01FFFFFF


@dataclass(frozen=True, order=True)
class BindingKey:
    """归一化后的「键码 + 修饰键」组合（可直接用作 dict 键）。

    Attributes:
        key: Qt 物理键码（``Qt.Key_*`` 的整数值）。
        ctrl: 是否按住 Ctrl。
        alt: 是否按住 Alt。
        shift: 是否按住 Shift。
        meta: 是否按住 Win/Meta。
    """

    key: int
    ctrl: bool = False
    alt: bool = False
    shift: bool = False
    meta: bool = False

    # ── 构造 ─────────────────────────────────────────────────────

    @classmethod
    def from_event(cls, event: QKeyEvent) -> Optional["BindingKey"]:
        """从 Qt 按键事件构造归一化键。

        纯修饰键（Ctrl / Shift / Alt / Meta 等）返回 ``None``，因为它们
        不能单独触发动作，且需要放行给控件自身（如 PDF 的 Ctrl 状态机）。

        Args:
            event: ``QKeyEvent`` 按键事件。

        Returns:
            Optional[BindingKey]: 归一化键；纯修饰键或非法键返回 ``None``。
        """
        key = int(event.key())
        if key == 0 or key in _MODIFIER_KEYS:
            return None
        mods = int(event.modifiers().value) & ~_IGNORED_MODIFIERS
        return cls(
            key=key,
            ctrl=bool(mods & _CTRL),
            alt=bool(mods & _ALT),
            shift=bool(mods & _SHIFT),
            meta=bool(mods & _META),
        )

    @classmethod
    def parse(cls, text: str) -> Optional["BindingKey"]:
        """把 ``QKeySequence`` 可移植文本解析为归一化键。

        Args:
            text: 形如 ``"Ctrl+Shift+F"`` 的文本；``"Ctrl+\\\\"`` 表示
                ``Ctrl+\\``。

        Returns:
            Optional[BindingKey]: 解析结果；空串或无法解析返回 ``None``。
        """
        if not text or not isinstance(text, str) or not text.strip():
            return None
        seq = QKeySequence.fromString(
            text, QKeySequence.SequenceFormat.PortableText
        )
        if seq.count() == 0:
            return None
        combo = seq[0]
        key = int(combo.key())
        if key == 0 or key == _INVALID_KEY or key in _MODIFIER_KEYS:
            return None
        mods = int(combo.keyboardModifiers().value) & ~_IGNORED_MODIFIERS
        return cls(
            key=key,
            ctrl=bool(mods & _CTRL),
            alt=bool(mods & _ALT),
            shift=bool(mods & _SHIFT),
            meta=bool(mods & _META),
        )

    # ── 输出 ─────────────────────────────────────────────────────

    def to_sequence(self) -> QKeySequence:
        """转换为 ``QKeySequence``（用于展示与 ``QAction``）。"""
        bits = int(self.key)
        if self.ctrl:
            bits |= _CTRL
        if self.alt:
            bits |= _ALT
        if self.shift:
            bits |= _SHIFT
        if self.meta:
            bits |= _META
        return QKeySequence(bits)

    def text(self) -> str:
        """返回可移植文本形式（如 ``"Ctrl+Shift+F"``）。"""
        return self.to_sequence().toString(
            QKeySequence.SequenceFormat.PortableText
        )

    # ── 查询 ─────────────────────────────────────────────────────

    def has_modifier(self) -> bool:
        """是否带任意修饰键（用于输入框守卫判定）。"""
        return self.ctrl or self.alt or self.shift or self.meta

    def has_command_modifier(self) -> bool:
        """是否带 Ctrl / Alt / Meta（不含 Shift）。

        Shift 单独存在时仍然会输入字符（如 ``Shift+Q`` 打 ``Q``），
        因此「能在文本输入框里安全触发」必须要求 Ctrl/Alt/Meta。
        """
        return self.ctrl or self.alt or self.meta

    def __str__(self) -> str:
        return self.text() or f"0x{self.key:x}"


def parse_all(texts) -> list[BindingKey]:
    """批量解析键位文本，丢弃无法解析的项（保序去重）。

    Args:
        texts: 键位文本可迭代对象。

    Returns:
        list[BindingKey]: 解析成功的键位列表。
    """
    out: list[BindingKey] = []
    seen: set[BindingKey] = set()
    for text in texts or ():
        key = BindingKey.parse(text)
        if key is None or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out