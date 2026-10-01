"""Preload legacy top-level UI packages in a frozen PyInstaller process."""
from __future__ import annotations

import importlib

# The spec collects these packages under their legacy top-level names. Importing
# them here makes their package __path__ available before delayed UI imports.
for _name in ("components", "theme"):
    try:
        importlib.import_module(_name)
    except Exception:
        pass
