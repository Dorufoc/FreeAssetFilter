"""Sopeek UI 层。

本包在导入时把 ``sopeek/ui/`` 加入 ``sys.path``，使 ``ui/`` 下的模块可以使用
短路径导入（``from theme import tm``、``from components.styled_button import ...``）。
短名与规范名（``sopeek.ui.theme`` / ``sopeek.ui.components``）由
:mod:`sopeek._import_compat` 的导入重定向 finder 收敛为同一模块对象，
因此两种写法不会产生两份单例。

历史上每个预览器布局文件都各自计算 ``parents[N]`` 再注入 ``sys.path``；
目录层级一变（``sopeek/`` → ``src/sopeek/``）这类代码就会静默失效，现已统一
收敛到本模块。模块内如需仓库根等路径，请用 :mod:`sopeek._paths`。
"""

from __future__ import annotations

import sys
from pathlib import Path

#: 本包目录（``sopeek/ui``）——短路径导入的搜索根。
UI_ROOT: Path = Path(__file__).resolve().parent

if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

__all__ = ["UI_ROOT"]
