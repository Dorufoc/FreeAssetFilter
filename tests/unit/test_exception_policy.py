# -*- coding: utf-8 -*-
"""全局代码卫生门禁：禁止"裸静默"宽泛异常捕获（review 3.5-1 防回归）。

规则
----
扫描 ``freeassetfilter/``、``tests/``、``tools/``、``scripts/`` 与根目录
两个构建/兼容脚本；对每个 ``except Exception`` / ``except BaseException``
（含裸 ``except:``）且处理体**仅有** ``pass`` 的处理器：

* 处理体（或 ``except`` 行）内必须带注释说明——例如
  ``pass  # 预期防御：宿主已销毁`` 或 ``# noqa: BLE001 - 理由``；
* 带日志调用的处理体不属于"裸静默"（已留痕），不在本门禁约束内；
* 窄类型捕获（如 ``except queue.Empty:``、``except (TypeError, ValueError):``）
  同样不在本门禁约束内。

背景
----
2026-10 review 3.5 全量治理：包内 110+ 处宽泛 ``except ...: pass`` 逐处
要么补 debug/warning 留痕、要么就地写明理由；本测试把这个约定固化为
fail-closed 门禁，防止重新长出"裸静默"。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator, List, Tuple

_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

_SCAN_DIRS: Tuple[str, ...] = ("freeassetfilter", "tests", "tools", "scripts")
_SCAN_ROOT_FILES: Tuple[str, ...] = (
    "Pyinstall_build.py",
    "pyinstaller_runtime_compat.py",
)
_SKIP_PARTS = {".venv", "__pycache__", "target", "build"}
_SKIP_SUBSTRINGS = ("tests/support/faf_core_fixtures",)


def _iter_sources() -> Iterator[Tuple[Path, str]]:
    """Yield ``(path, rel_path)`` for every in-scope Python source file."""
    for directory in _SCAN_DIRS:
        base = _PROJECT_ROOT / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(_PROJECT_ROOT).as_posix()
            if any(part in _SKIP_PARTS for part in path.parts):
                continue
            if any(s in rel for s in _SKIP_SUBSTRINGS):
                continue
            yield path, rel
    for name in _SCAN_ROOT_FILES:
        path = _PROJECT_ROOT / name
        if path.is_file():
            yield path, name


def _handler_name(node_type: ast.expr | None) -> str | None:
    if isinstance(node_type, ast.Name):
        return node_type.id
    if isinstance(node_type, ast.Attribute):
        return node_type.attr
    return None


def _is_broad(node_type: ast.expr | None) -> bool:
    """True for bare ``except:`` / ``Exception`` / ``BaseException`` catches."""
    if node_type is None:
        return True
    if isinstance(node_type, ast.Tuple):
        return any(
            _handler_name(elt) in ("Exception", "BaseException")
            for elt in node_type.elts
        )
    return _handler_name(node_type) in ("Exception", "BaseException")


def _collect_violations() -> List[str]:
    violations: List[str] = []
    for path, rel in _iter_sources():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if not _is_broad(node.type):
                continue
            # 处理体除 pass 外还有语句（含日志调用）→ 已留痕，不在门禁范围。
            if any(not isinstance(stmt, ast.Pass) for stmt in node.body):
                continue
            span = lines[node.lineno - 1 : node.end_lineno]
            if any("#" in line for line in span):
                continue
            violations.append(f"{rel}:{node.lineno}")
    return violations


def test_no_bare_silent_except_handlers() -> None:
    """全仓宽泛 ``except ...: pass`` 必须带就地注释/理由（fail-closed）。"""
    violations = _collect_violations()
    assert not violations, (
        "发现裸静默异常捕获（宽泛 except 且仅 pass、无任何注释）：\n"
        + "\n".join(f"  - {item}" for item in violations)
        + "\n请补日志留痕（debug/warning）或就地写明理由注释。"
    )
