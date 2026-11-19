"""快捷键处理器注册表 —— ``action_id`` → 可调用对象，支持按 owner 批量注销。

生命周期
========
预览器 / 布局在 ``__init__`` 末尾调 :meth:`HandlerRegistry.register` 登记，
在 ``cleanup()`` 里调 :meth:`HandlerRegistry.unregister_owner` 一次性摘除，
避免控件销毁后派发器仍持有其方法引用（PySide6 下会抛 ``RuntimeError``）。

多 owner 覆盖
=============
同一 ``action_id`` 允许被多个 owner 注册（例如「播放 / 暂停」在选择器与
媒体预览器各有一份）。派发时**后注册者覆盖先注册者**，且调用方应在注册前
先注销旧 owner，保证语义明确。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

#: 处理器签名：无参，可返回 ``bool``。
#:
#: 返回 ``False`` 表示「未消费」，派发器会继续向下层区域查找；
#: 返回 ``None`` 或 ``True`` 表示已消费。
Handler = Callable[[], Optional[bool]]


class HandlerRegistry:
    """``action_id`` → 处理器 + owner 的注册表。"""

    def __init__(self) -> None:
        #: action_id → (handler, owner)
        self._entries: Dict[str, Tuple[Handler, Any]] = {}

    # ── 注册 / 注销 ──────────────────────────────────────────────

    def register(self, action_id: str, handler: Handler, owner: Any) -> None:
        """登记一个处理器。

        Args:
            action_id: 动作 id（须与 ``registry.ACTION_SPECS`` 一致）。
            handler: 无参可调用对象；可返回 ``bool`` 表示是否消费。
            owner: 所属对象（用于 :meth:`unregister_owner`）。
        """
        if not callable(handler):
            raise TypeError(f"{action_id}: handler 必须可调用")
        self._entries[action_id] = (handler, owner)

    def register_many(
        self, mapping: Dict[str, Handler], owner: Any
    ) -> None:
        """批量登记同一 owner 的多个处理器。

        Args:
            mapping: ``action_id`` → handler 映射。
            owner: 所属对象。
        """
        for action_id, handler in mapping.items():
            self.register(action_id, handler, owner)

    def unregister(self, action_id: str) -> None:
        """移除单个处理器（幂等）。

        Args:
            action_id: 动作 id。
        """
        self._entries.pop(action_id, None)

    def unregister_owner(self, owner: Any) -> int:
        """移除某 owner 登记的全部处理器（按对象身份比对，幂等）。

        使用 ``is`` 比对而不是 ``id()``，避免 owner 被回收后 id 复用导致
        误删其它对象的登记。

        Args:
            owner: 目标 owner。

        Returns:
            int: 实际移除的条目数。
        """
        stale: List[str] = [
            action_id
            for action_id, (_, reg_owner) in self._entries.items()
            if reg_owner is owner
        ]
        for action_id in stale:
            self._entries.pop(action_id, None)
        return len(stale)

    def clear(self) -> None:
        """清空全部登记（测试 / 退出时使用）。"""
        self._entries.clear()

    # ── 查询 ────────────────────────────────────────────────────

    def get(self, action_id: str) -> Optional[Handler]:
        """取处理器；未登记返回 ``None``。

        Args:
            action_id: 动作 id。

        Returns:
            Optional[Handler]: 已登记的处理器。
        """
        entry = self._entries.get(action_id)
        return entry[0] if entry is not None else None

    def has(self, action_id: str) -> bool:
        """是否已登记该动作。

        Args:
            action_id: 动作 id。

        Returns:
            bool: 已登记返回 True。
        """
        return action_id in self._entries

    def action_ids(self) -> List[str]:
        """返回已登记的动作 id 列表（调试用）。"""
        return sorted(self._entries)

    def owner_of(self, action_id: str) -> Any:
        """返回某动作的登记 owner（调试用）；未登记返回 ``None``。"""
        entry = self._entries.get(action_id)
        return entry[1] if entry is not None else None
