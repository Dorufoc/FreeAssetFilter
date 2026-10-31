# -*- coding: utf-8 -*-
"""启动关键路径守护：预算/线程池初始化不得落在「进程 → 首帧」上。

背景（实测回归）：把 ``MemoryBudget.apply()`` 放在 ``_create_application`` 时，
它会为打补丁而强导入 ``file_icon_manager``（冷导入 174–290ms），并且
``QThreadPool.globalInstance()`` 首次调用本身要约 100–140ms——两者都发生在
轻量窗口 ``show()`` 之前，用户能直接感知为「启动变慢」。

本模块锁定三条不变量：

1. ``_create_application`` 不再触碰 pools / memory_budget（结构断言 + 行为断言）；
2. ``_init_runtime_budgets`` 负责两者，且可重复调用（幂等）；
3. ``MemoryBudget.apply()`` 不给未导入的重模块「顺手导入」，而是标记 pending，
   由模块自身构造期读档位补齐。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from sopeek.core import memory_budget as mb_mod

pytestmark = pytest.mark.unit

_MAIN_PY = (
    Path(__file__).resolve().parents[3]
    / "sopeek"
    / "app"
    / "main.py"
)


def _create_application_node() -> ast.FunctionDef:
    """取 ``main.py::_create_application`` 的 AST 节点。"""
    tree = ast.parse(_MAIN_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_create_application":
            return node
    raise AssertionError("main.py 缺少 _create_application")


def _lint_module_imports(func: ast.FunctionDef) -> set[str]:
    """收集函数体内所有 ``import`` 的模块名（含 from-import 的模块部分）。"""
    modules: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_create_application_does_not_touch_pools_or_budget() -> None:
    """启动早期不得导入 pools / memory_budget，也不得调 globalInstance。"""
    node = _create_application_node()
    modules = _lint_module_imports(node)
    assert "sopeek.core.pools" not in modules
    assert "sopeek.core.memory_budget" not in modules
    # 用 AST 而非源码文本：注释里提到 QThreadPool 不算违规。
    referenced = {
        n.id for n in ast.walk(node) if isinstance(n, ast.Name)
    }
    attributes = {
        n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)
    }
    assert "QThreadPool" not in referenced
    assert "globalInstance" not in attributes


def test_runtime_budgets_is_scheduled_after_show() -> None:
    """``_init_runtime_budgets`` 必须在 ``_finish_deferred_ui`` 内（即 show 之后）。"""
    source = _MAIN_PY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    finish = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_finish_deferred_ui":
            finish = node
    assert finish is not None, "main.py 缺少 _finish_deferred_ui"
    called = [
        n.func.id
        for n in ast.walk(finish)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert "_init_runtime_budgets" in called
    # 且必须早于 initialize_deferred_content（预算先于缓存增长生效）
    body_dump = ast.dump(finish)
    assert body_dump.index("_init_runtime_budgets") < body_dump.index(
        "initialize_deferred_content"
    )


def test_apply_marks_heavy_module_pending_instead_of_importing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """apply() 不给未导入的 file_icon_manager 打工：标记 pending 即可。"""
    module_name = "sopeek.services.file_icon_manager"
    if module_name not in sys.modules:
        pytest.skip("本进程未导入 file_icon_manager，无法构造 pending 场景")
    saved = sys.modules[module_name]
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    mb_mod.reset_for_tests()
    budget = mb_mod.get_memory_budget()
    try:
        result = budget.apply(None)
        assert "file_icon_manager" in result["pending"]
        assert module_name not in sys.modules, "apply() 不得重新导入重模块"
    finally:
        monkeypatch.setitem(sys.modules, module_name, saved)
        mb_mod.reset_for_tests()


def test_apply_patches_icon_manager_when_already_imported() -> None:
    """模块已导入时照常打补丁（首帧后的延迟 re-apply 走的就是这条）。"""
    from sopeek.services.file_icon_manager import FileIconManager

    mb_mod.reset_for_tests()
    budget = mb_mod.get_memory_budget()
    budget.set_tier("low")
    try:
        result = budget.apply(None)
        assert "file_icon_manager" in result["applied"]
        assert FileIconManager._ICON_CACHE_MAX_ENTRIES == mb_mod.TIERS["low"].icon_cache_entries
    finally:
        mb_mod.reset_for_tests()


def test_icon_manager_self_applies_budget_at_construction() -> None:
    """FileIconManager 构造期自读档位：即使 apply() 早于导入，上限也正确。"""
    from sopeek.services.file_icon_manager import FileIconManager

    mb_mod.reset_for_tests()
    budget = mb_mod.get_memory_budget()
    budget.set_tier("low")
    try:
        FileIconManager._apply_budget_limits()
        expected = mb_mod.TIERS["low"].icon_cache_entries
        assert FileIconManager._ICON_CACHE_MAX_ENTRIES == expected
        assert FileIconManager._ICON_CACHE_FAMILY_BUDGET == expected
        assert FileIconManager._SYSTEM_ICON_PLACEHOLDER_CACHE_MAX_ENTRIES == expected
    finally:
        mb_mod.reset_for_tests()


def test_runtime_budgets_is_idempotent_and_registers_providers(
    qapp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """预算初始化可重复调用（首帧后一次 + 任务补一次）。"""
    from sopeek.app import main as app_main
    from sopeek.utils import perf_metrics

    calls: Dict[str, int] = {"apply": 0}
    real_apply = mb_mod.MemoryBudget.apply

    def _counting_apply(self, app=None):  # noqa: ANN001 - 测试替身
        calls["apply"] += 1
        return real_apply(self, app)

    monkeypatch.setattr(mb_mod.MemoryBudget, "apply", _counting_apply)
    mb_mod.reset_for_tests()
    try:
        app_main._init_runtime_budgets(qapp)
        app_main._init_runtime_budgets(qapp)
        assert calls["apply"] == 2
        snapshot = perf_metrics.get_perf_snapshot()
        assert "pools" in snapshot["providers"]
        assert "memory" in snapshot["providers"]
    finally:
        mb_mod.reset_for_tests()
