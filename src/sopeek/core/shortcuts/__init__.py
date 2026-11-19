"""快捷键系统 —— 注册表 + 绑定表 + 处理器 + 派发器。

对外只暴露四类入口：

- :data:`ACTION_SPECS` / :class:`ActionSpec`：键位的唯一事实来源；
- :class:`BindingKey`：归一化键（物理键码 + 修饰键）；
- :class:`BindingTable`：``(region, key) → action_id`` 的只读索引；
- :func:`shortcut_dispatcher`：进程内唯一的派发器。

典型用法::

    from sopeek.core.shortcuts import shortcut_dispatcher

    d = shortcut_dispatcher()
    d.handlers.register("selector.refresh", self._reload_directory, owner=self)
    d.register_escape_provider("selector", self)

    # 主窗口初始化时安装一次
    d.install()
"""

from __future__ import annotations

from .bindings import BindingKey, parse_all
from .dispatcher import (
    BindingTable,
    ShortcutDispatcher,
    defer_call,
    enter_fullscreen_region,
    exit_fullscreen_region,
    reset_dispatcher_for_tests,
    shortcut_dispatcher,
)
from .handlers import HandlerRegistry
from .registry import (
    ACTION_SPECS,
    CATEGORY_ORDER,
    ActionSpec,
    Region,
    RepeatPolicy,
    spec_by_id,
)

__all__ = [
    "ACTION_SPECS",
    "CATEGORY_ORDER",
    "ActionSpec",
    "BindingKey",
    "BindingTable",
    "HandlerRegistry",
    "Region",
    "RepeatPolicy",
    "ShortcutDispatcher",
    "defer_call",
    "enter_fullscreen_region",
    "exit_fullscreen_region",
    "parse_all",
    "reset_dispatcher_for_tests",
    "shortcut_dispatcher",
    "spec_by_id",
]
