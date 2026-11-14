"""短路径导入重定向：统一 ``theme`` / ``components`` 与 ``sopeek.ui.*``。

背景
----
``sopeek/ui`` 会被加入 ``sys.path``（见 ``app/main.py``、
``ui/main_window.py`` 与 PyInstaller ``--paths`` / ``pyinstaller_runtime_compat``），
以便源码使用 ``from theme import tm`` / ``from components.x import y`` 这类
短路径导入；同时另一部分代码使用 ``sopeek.ui.theme`` /
``sopeek.ui.components`` 规范路径导入。若两条路径各自加载一次，
同一份包代码会被执行两遍——``theme`` 的 ``tm`` 单例、QSS 注册表等模块级
状态会分裂成两份（实测 import 顺序不同即出现）。

实现
----
安装一个 ``sys.meta_path`` finder：导入名称命中短名或规范名之一时，若对侧
名称的等价模块（含子模块）已加载，则复用同一模块对象；否则先经规范路径
正常加载再绑定。任意加载顺序（短名先 / 规范名先 / 冻结 runtime hook 先
预加载短名）最终都收敛到同一对象。finder 由 ``sopeek/__init__.py``
在包初始化时安装，幂等；模块自身不依赖 sopeek 任何子模块。
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys
from typing import Dict, Optional, Tuple

#: 短路径顶层名 ↔ 规范包路径（一一对应，互为别名）。
_SHORT_TO_LONG: Dict[str, str] = {
    "theme": "sopeek.ui.theme",
    "components": "sopeek.ui.components",
}
_LONG_TO_SHORT: Dict[str, str] = {long: short for short, long in _SHORT_TO_LONG.items()}


def _classify(fullname: str) -> Optional[Tuple[str, str, bool, Tuple[str, ...]]]:
    """解析导入名，返回 ``(短名, 规范名, 是否短名导入, 子模块后缀)``。

    不属于两对别名的名称返回 ``None``；对侧名称不存在时也返回 ``None``。

    Args:
        fullname: 本次导入的完整模块名。

    Returns:
        tuple[str, str, bool, tuple[str, ...]] | None: 分类结果或 ``None``。
    """
    parts = fullname.split(".")
    top = parts[0]
    long_top = _SHORT_TO_LONG.get(top)
    if long_top is not None:
        return top, long_top, True, tuple(parts[1:])
    if top == "sopeek" and len(parts) >= 3:
        long_top = ".".join(parts[:3])
        short_top = _LONG_TO_SHORT.get(long_top)
        if short_top is not None:
            return short_top, long_top, False, tuple(parts[3:])
    return None


class _AliasLoader(importlib.abc.Loader):
    """复用对侧已加载模块；对侧未加载时经规范路径正常导入。"""

    def __init__(self, canonical: str) -> None:
        self._canonical = canonical

    def create_module(self, spec):  # type: ignore[no-untyped-def]
        existing = sys.modules.get(self._canonical)
        if existing is not None:
            return existing
        # 短名先到、规范路径未加载：正常导入规范模块（其名称不匹配短名
        # 前缀，不会递归回本 finder），完成后两侧共享同一对象。
        try:
            return importlib.import_module(self._canonical)
        except ModuleNotFoundError as exc:
            if exc.name == self._canonical:
                # 目标模块不存在：以「请求的名称」抛出，保持 __getattr__
                # 子模块探测（如 hasattr 检查）的异常语义一致。
                raise ModuleNotFoundError(
                    f"No module named {spec.name!r}", name=spec.name
                ) from exc
            raise

    def exec_module(self, module):  # type: ignore[no-untyped-def]
        # 模块已由对侧名称执行完毕，无需重复执行。
        ...


class _ShortPathAliasFinder(importlib.abc.MetaPathFinder):
    """让短路径名与规范路径名解析到同一模块对象的 meta path finder。"""

    def find_spec(self, fullname, path=None, target=None):  # type: ignore[no-untyped-def]
        info = _classify(fullname)
        if info is None:
            return None
        short_top, long_top, is_short, suffix = info
        other_top = long_top if is_short else short_top
        other = other_top + ("." + ".".join(suffix) if suffix else "")
        if not is_short and other not in sys.modules:
            # 规范名导入且短名尚未加载：走正常导入路径，无需重定向。
            return None
        return importlib.util.spec_from_loader(fullname, _AliasLoader(other))


#: 安装幂等标志（finder 实例只安装一次）。
_INSTALLED: bool = False


def install() -> None:
    """安装重定向 finder（幂等；由 ``sopeek/__init__.py`` 调用）。"""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    sys.meta_path.insert(0, _ShortPathAliasFinder())


__all__ = ["install"]
