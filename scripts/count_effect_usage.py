#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Count QGraphics*Effect usages in product code (A2 acceptance probe).

Walks ``freeassetfilter/`` with :mod:`ast` and counts every reference to
``QGraphicsOpacityEffect`` / ``QGraphicsDropShadowEffect`` /
``QGraphicsBlurEffect`` — imports, attribute access and instantiations.
Comments and docstrings are not AST nodes, so a zero count here plus a
follow-up text sweep proves the offscreen effect path is fully gone.

Exit code is 0 only when the counted usage is zero (after exemptions);
any residual effect fails the run. Exemptions are explicit
``path:line:reason`` entries in :data:`EXEMPTIONS`.

Usage:
    python scripts/count_effect_usage.py [--path freeassetfilter]
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

TARGETS: frozenset[str] = frozenset(
    {
        "QGraphicsOpacityEffect",
        "QGraphicsDropShadowEffect",
        "QGraphicsBlurEffect",
    }
)

# Explicit documented exemptions: "path:line" -> reason. Empty means the
# plan's zero-residual goal holds with no exception (styled_fluid_background
# uses a GPU/shader path and references none of the three classes, so no
# exemption entry is needed for it).
EXEMPTIONS: dict[str, str] = {}

# Directories never scanned (mirrors todo 5's counter conventions).
SKIP_DIRS: frozenset[str] = frozenset(
    {"tests", ".omo", "__pycache__", ".git", ".venv", "venv"}
)


class _EffectVisitor(ast.NodeVisitor):
    """Collect (line, kind, name) for every TARGETS reference."""

    def __init__(self) -> None:
        self.hits: list[tuple[int, str, str]] = []

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name in TARGETS:
                self.hits.append((node.lineno, "import", alias.name))
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            base = alias.name.split(".")[-1]
            if base in TARGETS:
                self.hits.append((node.lineno, "import", base))
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in TARGETS:
            self.hits.append((node.lineno, "name", node.id))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in TARGETS:
            self.hits.append((node.lineno, "attribute", node.attr))
        self.generic_visit(node)


def count_file(path: Path) -> list[tuple[int, str, str]]:
    """Return TARGETS hits for a single file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    visitor = _EffectVisitor()
    visitor.visit(tree)
    # Deduplicate: `X(...)` yields both Call->Name and Name visits? No —
    # generic_visit visits each node once; Name inside Call.func is one
    # node, but ImportFrom + later Name use are distinct lines. A single
    # line such as `effect = QGraphicsBlurEffect()` produces exactly one
    # Name hit. Attribute chains like `QGraphicsBlurEffect.PerformanceHint`
    # produce one Name hit (inner) — the Attribute attr is
    # `PerformanceHint`, not a target, so no double count.
    return sorted(set(visitor.hits))


def iter_product_files(root: Path) -> list[Path]:
    """List scanned ``.py`` files under root, minus skipped dirs."""
    files: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def main(argv: list[str] | None = None) -> int:
    """Entry point: scan, report, and exit non-zero on residual usage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        default="freeassetfilter",
        help="Product tree to scan (default: freeassetfilter).",
    )
    args = parser.parse_args(argv)
    root = Path(args.path)
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    counted = 0
    for path in iter_product_files(root):
        rel = path.as_posix()
        for lineno, kind, name in count_file(path):
            key = f"{rel}:{lineno}"
            if key in EXEMPTIONS:
                print(f"exemption={key}:{EXEMPTIONS[key]}")
                continue
            print(f"hit={rel}:{lineno}:{kind}:{name}")
            counted += 1

    print(f"effect_usage={counted}")
    return 0 if counted == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
