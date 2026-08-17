# -*- coding: utf-8 -*-
# targets: freeassetfilter.app.main, freeassetfilter.components.unified_previewer, freeassetfilter.components.file_selector, freeassetfilter.components.file_staging_pool, freeassetfilter.core.managers.settings_manager, freeassetfilter.core.managers.theme_manager
"""integration 批 1（W6/todo-24）：模块导入集成测试。

基于 ``tests.support.coverage_manifest`` 动态导出 freeassetfilter 全部
现存模块清单（物理模块 ∪ 旧式扁平懒别名），逐个 ``importlib.import_module``
冒烟验证：

* **物理模块**：AST 扫描 ``freeassetfilter/**/*.py``（排除 ui/demos、
  core/native/src、setup.py、__init__.py、*.pyi）得到的全部可导入模块；
* **懒别名**：``freeassetfilter.core.settings_manager`` 等旧扁平路径经
  ``core/__init__.py`` 的 ``_LazyModuleAlias`` 注册为 ``sys.modules``
  占位符，首次属性访问（或包级 ``__getattr__``）时解析到真实子包模块并
  替换占位条目；本文件断言替换后 ``sys.modules`` 条目指向真实模块；
* **脆弱名单**（复刻旧 test_module_imports.py:120-128 的
  ``_FRAGILE_MODULES`` 机制）：仅在原生 DLL 缺失时 import 即抛
  ``ImportError`` 的模块（当前只有
  ``core.native.bridges.rust_color_extractor``），按名单 try/except +
  ``pytest.skip`` 而非硬失败。

环境对齐：``ui/main_window.py:22-30`` 在应用启动时把 ``freeassetfilter/ui``
插入 ``sys.path``（``ui.components._styled_fluid_cpu`` 等用裸短路径
``from theme import tm`` 导入）；本文件在模块顶部做同样的事，保证这些
ui 模块照常导入而非误报失败。

约束（计划 todo-24）：零生产代码改动；不启动应用（不调用 main()）；
所有导入在测试进程内完成，不写任何用户数据文件。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import List, Set

import pytest

from tests.support.coverage_manifest import (
    ModuleInventory,
    extract_alias_modules,
    scan_source_modules,
)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# 环境对齐：与 ui/main_window.py:22-30 一致，把 freeassetfilter/ui 加入 sys.path
# ---------------------------------------------------------------------------
_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
_UI_ROOT: Path = _PROJECT_ROOT / "freeassetfilter" / "ui"
_UI_PATH: str = str(_UI_ROOT)
if _UI_PATH not in sys.path:
    sys.path.insert(0, _UI_PATH)

# ---------------------------------------------------------------------------
# 模块清单构建（与 coverage_manifest.run 同源）
# ---------------------------------------------------------------------------
_inventory: ModuleInventory = ModuleInventory()
scan_source_modules(_inventory)
_inventory.alias_to_real = extract_alias_modules()
#: 物理模块名（如 freeassetfilter.components.unified_previewer）。
PHYSICAL_MODULES: List[str] = sorted(_inventory.modules)
#: 旧式扁平别名模块名（如 freeassetfilter.core.settings_manager）。
ALIAS_MODULES: List[str] = sorted(_inventory.alias_to_real)

#: 已知「import 时因原生依赖缺失而抛 ImportError」的模块（跳过而非失败）。
#: 复刻 old-tests-snapshot/tests/integration/test_module_imports.py:120-128
#: 的脆弱名单机制。旧名单中的 core.native.rust_color_extractor 与
#: core.native.src.*.setup 已因扫描排除 core/native/src 或路径变更而消失；
#: 现存的唯一实例是 bridges/rust_color_extractor.py:177 的显式 raise。
_FRAGILE_MODULES: Set[str] = {
    "freeassetfilter.core.native.bridges.rust_color_extractor",
}


# ---------------------------------------------------------------------------
# 物理模块导入冒烟
# ---------------------------------------------------------------------------
class TestPhysicalModulesImport:
    """全部现存物理模块逐个导入冒烟（~160 个）。"""

    @pytest.mark.parametrize("module_name", PHYSICAL_MODULES)
    def test_physical_module_imports(self, module_name: str) -> None:
        """物理模块应可被 importlib 导入；脆弱名单内失败则跳过。

        Args:
            module_name: 待导入的物理模块名（来自 coverage_manifest 扫描）。
        """
        if module_name in _FRAGILE_MODULES:
            try:
                assert importlib.import_module(module_name) is not None
            except ImportError:
                pytest.skip(f"已知脆弱模块 {module_name} 缺少原生 DLL")
            return

        assert importlib.import_module(module_name) is not None

    def test_all_physical_import_batch(self) -> None:
        """批量导入全部物理模块（脆弱名单除外），汇总失败而非逐个中断。

        一次 gather 全部 ImportError，失败信息含模块名与原因。
        """
        failures: List[str] = []
        for module_name in PHYSICAL_MODULES:
            if module_name in _FRAGILE_MODULES:
                continue
            try:
                importlib.import_module(module_name)
            except ImportError as exc:
                failures.append(f"{module_name}: {exc}")
        assert not failures, (
            "以下模块导入失败：\n" + "\n".join(failures)
        )


# ---------------------------------------------------------------------------
# 懒别名 sys.modules 兼容性
# ---------------------------------------------------------------------------
class TestLazyAliasCompatibility:
    """旧式扁平导入路径（如 core.settings_manager）的懒解析兼容性。"""

    def test_aliases_registered_in_sys_modules(self) -> None:
        """全部扁平别名应被 core/__init__.py 注册进 sys.modules。

        导入 ``freeassetfilter.core`` 触发安装后，对清单中的 14 条别名
        逐一断言条目存在（值可能为 _LazyModuleAlias 占位符或已解析真实模块）。
        """
        importlib.import_module("freeassetfilter.core")
        for alias in ALIAS_MODULES:
            assert alias in sys.modules, f"别名 {alias} 未注册到 sys.modules"

    def test_alias_resolves_to_real_module(self) -> None:
        """触发包级 __getattr__ 后，sys.modules 条目应指向真实物理模块。

        对应 ``from freeassetfilter.core import settings_manager`` 的
        行为（core/__init__.py L156 会把 sys.modules[alias] 替换为真实模块）。
        """
        importlib.import_module("freeassetfilter.core")
        for alias, real in _inventory.alias_to_real.items():
            flat_name: str = alias.rsplit(".", 1)[-1]  # 如 settings_manager
            getattr(importlib.import_module("freeassetfilter.core"), flat_name)
            assert (
                sys.modules[alias] is importlib.import_module(real)
            ), f"别名 {alias} 未能替换为真实模块 {real}"

    def test_flat_import_style_symbols(self) -> None:
        """旧式 ``from freeassetfilter.core import <symbol>`` 兼容性。

        校验 __getattr__ 符号路径（SettingsManager/ThemeManager）可解析，
        与 core/__init__.py 的 _SYMBOL_MAP 行为一致。
        """
        importlib.import_module("freeassetfilter.core")
        from freeassetfilter.core import SettingsManager, ThemeManager  # type: ignore[attr-defined]

        assert SettingsManager is not None
        assert ThemeManager is not None