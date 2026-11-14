"""Preload legacy top-level UI packages in a frozen PyInstaller process.

The short names (``components`` / ``theme``) are unified with the canonical
``sopeek.ui.*`` modules by :mod:`sopeek._import_compat`
(installed as soon as the ``sopeek`` package is imported), so either
import order — this hook first, or the application later — resolves to a
single module object per package.
"""
from __future__ import annotations

import importlib

# The spec collects these packages under their legacy top-level names. Importing
# them here makes their package __path__ available before delayed UI imports.
for _name in ("components", "theme"):
    try:
        importlib.import_module(_name)
    except Exception:
        pass  # 冻结启动垫片：预导入失败按未安装处理（此阶段不引日志）
