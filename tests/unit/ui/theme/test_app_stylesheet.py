# -*- coding: utf-8 -*-
"""应用级样式表单元测试（QSS 单例化 / ``scope_qss`` 解析契约）。

覆盖 ``ui/theme/app_stylesheet``：

1. 纯裸声明片段 → 两条规则（自身 + 子树），与 ``setStyleSheet`` 语义一致；
2. 纯选择器规则片段 → 后代形态 + 类型锚定自身形态；
3. 同片段内「裸声明 + 选择器规则」粘连形态的拆分（储存池丢样式回归）：
   含逗号的声明值（``rgba(255,255,255,0.05)``）不得把选择器切碎，后续
   规则不得被吞；
4. 无法可靠拆分的选择器（属性值含分号）宁可整条跳过也不下发畸形文本——
   Qt 解析器遇到畸形规则会丢弃整张样式表的后续内容；
5. category (c) 直写点白名单门禁：全包 AST 扫描的 ``setStyleSheet``
   调用点必须与 ``DIRECT_SETSTYLESHEET_SITES`` 精确一致。

验证命令：
    python -m pytest tests/unit/ui/theme/test_app_stylesheet.py --timeout 60 -q
"""

# targets: ui.theme.app_stylesheet

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import List, Tuple

import pytest

# 模块内部使用短路径导入（from theme.system_accent import ...），
# 需要 freeassetfilter/ui 位于 sys.path。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.theme.app_stylesheet import (  # noqa: E402
    DIRECT_SETSTYLESHEET_SITES,
    scope_qss,
)

pytestmark = pytest.mark.unit

#: 粗粒度规则解析：匹配不含嵌套的正规 ``selector { declarations }``。
_RULE_RE = re.compile(r"([^{}]*)\{([^{}]*)\}", re.DOTALL)


def _parse_rules(scoped: str) -> List[Tuple[str, str]]:
    """把作用域文本解析为 ``(selector, declarations)`` 列表（结构断言用）。

    同时校验输出形态：花括号配平、规则块之外无残留文本、选择器非空且
    不含 ``;``（合法 QSS 选择器不含分号；残留在选择器中的分号意味着
    畸形规则，会让 Qt 丢弃整张样式表其后内容）。

    Args:
        scoped: ``scope_qss`` 渲染出的作用域文本。

    Returns:
        每个规则块的 ``(选择器, 声明)`` 元组列表。
    """
    assert scoped.count("{") == scoped.count("}"), (
        f"花括号不配平: {scoped[:120]!r}"
    )
    rules: List[Tuple[str, str]] = []
    for match in _RULE_RE.finditer(scoped):
        selector = match.group(1).strip()
        assert selector, f"空选择器规则: {match.group(0)[:120]!r}"
        assert ";" not in selector, f"选择器含分号（畸形）: {selector[:120]!r}"
        assert ": " not in selector, (
            f"选择器疑似吞入声明文本: {selector[:120]!r}"
        )
        rules.append((selector, match.group(2)))
    leftover = _RULE_RE.sub("", scoped).strip()
    assert leftover == "", f"规则块外残留无法解析文本: {leftover[:120]!r}"
    return rules


class TestScopeQss:
    """``scope_qss`` 把每控件片段重写为应用级作用域文本。"""

    def test_bare_declarations_scope_to_widget_and_subtree(self) -> None:
        """裸声明 → 自身 + 子树两条规则（与 Qt 子树级联语义一致）。"""
        scoped = scope_qss("t1", "background: transparent; border: none;")
        rules = _parse_rules(scoped)
        selectors = [sel for sel, _ in rules]
        assert '*[fafQssId="t1"]' in selectors
        assert '[fafQssId="t1"] *' in selectors
        assert all(
            "background: transparent;" in decls for _, decls in rules
        )

    def test_plain_selector_rule_scopes_to_type(self) -> None:
        """选择器规则 → 后代形态 + ``Type[scope]`` 自身形态。"""
        scoped = scope_qss("t2", "QLabel { color: #888888; }")
        rules = _parse_rules(scoped)
        assert len(rules) == 1
        selector, decls = rules[0]
        assert '[fafQssId="t2"] QLabel' in selector
        assert 'QLabel[fafQssId="t2"]' in selector
        assert "color: #888888;" in decls

    def test_declarations_then_rule_split(self) -> None:
        """回归：裸声明 + 后续选择器规则不再被切碎（储存池丢样式根因）。

        历史缺陷：``[^{}]+`` 会把声明的 ``rgba(...)`` 逗号当选择器分隔符，
        生成 ``[fafQssId=...] background-color: rgba(255, ...`` 之类的畸形
        规则；Qt 解析器遇到畸形规则后会丢弃整张样式表后续内容，
        导致储存池内容区/底栏/空池提示整体丢样式。
        """
        fragment = (
            "background-color: rgba(255,255,255,0.05);\n"
            "border: 1px solid rgba(136,136,136,0.5);\n"
            "border-radius: 8px;\n"
            'QFrame[dragActive="true"] { border: 2px dashed #4a90d9; }'
        )
        scoped = scope_qss("t3", fragment)
        rules = _parse_rules(scoped)
        # 声明完整保留（含逗号的 rgba 值未被切断）
        joined = " ".join(decls for _, decls in rules)
        assert "background-color: rgba(255,255,255,0.05);" in joined
        assert "border: 1px solid rgba(136,136,136,0.5);" in joined
        assert "border-radius: 8px;" in joined
        # 动态属性选择器规则完整保留（后代 + 自身两种作用域形态）
        selectors = " ".join(sel for sel, _ in rules)
        assert '[fafQssId="t3"] QFrame[dragActive="true"]' in selectors
        assert 'QFrame[fafQssId="t3"][dragActive="true"]' in selectors
        assert "border: 2px dashed #4a90d9;" in joined

    def test_explicit_universal_block_with_rule(self) -> None:
        """储存池现行写法：显式 ``* { ... }`` + 后续规则，两条都保留。"""
        fragment = (
            "* { background-color: rgba(255,255,255,0.05);"
            " border: 1px solid rgba(136,136,136,0.5);"
            " border-radius: 8px; }\n"
            'QFrame[dragActive="true"] { border: 2px dashed #4a90d9; }'
        )
        scoped = scope_qss("t4", fragment)
        rules = _parse_rules(scoped)
        selectors = [sel for sel, _ in rules]
        # ``*`` 选择器与裸声明同语义：自身 + 子树两条规则，外加拖放反馈规则
        assert '*[fafQssId="t4"]' in selectors
        assert '[fafQssId="t4"] *' in selectors
        assert any('dragActive="true"' in sel for sel in selectors)
        joined_decls = " ".join(decls for _, decls in rules)
        assert "background-color: rgba(255,255,255,0.05);" in joined_decls
        assert "border: 2px dashed #4a90d9;" in joined_decls

    def test_unparsable_selector_is_skipped_without_garbage(self) -> None:
        """属性值含分号的片段无法可靠拆分：跳过规则，绝不下发畸形文本。"""
        scoped = scope_qss("t5", 'color: red; QFrame[a="x;y"] { color: blue; }')
        rules = _parse_rules(scoped)
        assert all(";" not in sel for sel, _ in rules)
        assert "color: blue" not in scoped

    def test_empty_fragment_returns_empty(self) -> None:
        """空/空白片段返回空串（等价 unregister 语义，不产生规则）。"""
        assert scope_qss("t6", "") == ""
        assert scope_qss("t6", "   \n  ") == ""


#: 包根：freeassetfilter/（本文件位于 tests/unit/ui/theme/ 下，向上四级）。
_PACKAGE_ROOT: Path = Path(__file__).resolve().parents[4] / "freeassetfilter"


class _DirectStylesheetCollector(ast.NodeVisitor):
    """收集 ``setStyleSheet`` 调用点及其所在的最近函数名。"""

    def __init__(self) -> None:
        self._function_stack: List[str] = []
        self.sites: set = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._function_stack.append(node.name)
        self.generic_visit(node)
        self._function_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "setStyleSheet":
            self.sites.add(
                self._function_stack[-1] if self._function_stack else "<module>"
            )
        self.generic_visit(node)


def _scan_direct_stylesheet_sites() -> set:
    """AST 扫描全包，返回 ``{(相对路径, 函数名), ...}`` 直写点集合。"""
    found: set = set()
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        rel = path.relative_to(_PACKAGE_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        collector = _DirectStylesheetCollector()
        collector.visit(tree)
        for func_name in collector.sites:
            found.add((rel, func_name))
    return found


class TestDirectStylesheetRegistry:
    """category (c) 直写点登记门禁（fail-closed）。"""

    def test_direct_sites_match_registry(self) -> None:
        """全包直写点必须与 ``DIRECT_SETSTYLESHEET_SITES`` 精确一致。

        新增直写点 → 报"新增"并提示补内联理由与登记；删除调用点后未同步
        白名单 → 报"扫描不到"并提示清理。
        """
        found = _scan_direct_stylesheet_sites()
        expected = set(DIRECT_SETSTYLESHEET_SITES)
        assert found == expected, (
            "直接 setStyleSheet 调用点与白名单不一致：\n"
            f"  新增（须补内联理由并登记）: {sorted(found - expected)}\n"
            f"  白名单但扫描不到（应清理）: {sorted(expected - found)}"
        )
