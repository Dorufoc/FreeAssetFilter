"""向后兼容 shim —— 旧 ``components.mica_material.MicaMaterial`` 的导入入口。

实际的 Mica 实现已迁移到 :mod:`freeassetfilter.ui.mica.material`（无 DWM 依赖、
纯自主渲染）。本文件仅做再导出，保证 ``main_window`` / ``demos`` 等既有调用方无需改动。
"""

from __future__ import annotations

# 绝对导入：本模块既可能被 ``main_window`` 以顶层 ``components.*`` 形式加载
# （main_window 会把 freeassetfilter/ui 加入 sys.path），也可能被测试以
# ``freeassetfilter.ui.components.*`` 形式加载。相对导入在两种情况下不能兼得，
# 故使用绝对包路径，确保无论哪种加载方式都可用。
from freeassetfilter.ui.mica.material import MicaMaterial, MicaWidget

__all__ = ["MicaMaterial", "MicaWidget"]
