"""AST-based counter for per-widget ``setStyleSheet`` call sites.

Counts ``Call`` nodes whose ``func`` is an attribute named
``setStyleSheet`` (``ast.walk``), excluding ``tests/``, ``.omo/`` and
``__pycache__`` paths.

Usage:
    python scripts/count_stylesheet_calls.py [--root .]

Output:
    stylesheet_calls=<count>

Fail-closed: exits non-zero if any ``.py`` file under the scan roots
cannot be parsed, or if no files were scanned at all.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

EXCLUDED_PARTS = ("tests", ".omo", "__pycache__", ".venv", "venv")


def is_excluded(path: Path, root: Path) -> bool:
    """Return True if *path* lives under an excluded directory.

    Args:
        path: Candidate file path.
        root: Scan root (used for relative-part matching).

    Returns:
        True when any path part matches an excluded directory name.
    """
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        rel_parts = path.parts
    return any(part in EXCLUDED_PARTS for part in rel_parts)


def count_in_tree(tree: ast.AST) -> int:
    """Count ``setStyleSheet`` call nodes in an AST.

    Args:
        tree: Parsed module AST.

    Returns:
        Number of ``Call`` nodes with ``func.attr == 'setStyleSheet'``.
    """
    count = 0
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "setStyleSheet"
        ):
            count += 1
    return count


def count_stylesheet_calls(root: Path) -> tuple[int, dict[str, int]]:
    """Walk *root* and count ``setStyleSheet`` calls per file.

    Args:
        root: Repository root to scan (``freeassetfilter/`` subtree).

    Returns:
        Tuple of (total count, per-file mapping).

    Raises:
        SyntaxError: If any scanned file fails to parse (fail-closed).
        RuntimeError: If no Python files were scanned.
    """
    scan_root = root / "freeassetfilter"
    if not scan_root.is_dir():
        scan_root = root
    total = 0
    per_file: dict[str, int] = {}
    scanned = 0
    failures: list[str] = []
    for path in sorted(scan_root.rglob("*.py")):
        if is_excluded(path, root):
            continue
        scanned += 1
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
            failures.append(f"{path}: {exc}")
            continue
        file_count = count_in_tree(tree)
        if file_count:
            per_file[str(path)] = file_count
            total += file_count
    if failures:
        for failure in failures:
            print(f"PARSE_ERROR {failure}", file=sys.stderr)
        raise SyntaxError(
            f"fail-closed: {len(failures)} file(s) could not be parsed"
        )
    if scanned == 0:
        raise RuntimeError("fail-closed: no Python files scanned")
    return total, per_file


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argument list (defaults to ``sys.argv``).

    Returns:
        Exit code (0 on success, 1 on parse/scan failure).
    """
    parser = argparse.ArgumentParser(
        description="Count setStyleSheet call sites (AST, fail-closed)."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root (default: current directory).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-file breakdown.",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        total, per_file = count_stylesheet_calls(root)
    except (SyntaxError, RuntimeError) as exc:
        print(f"stylesheet_calls=UNKNOWN ({exc})", file=sys.stderr)
        return 1
    print(f"stylesheet_calls={total}")
    if args.verbose:
        for path in sorted(per_file, key=per_file.get, reverse=True):  # type: ignore[arg-type]
            print(f"  {per_file[path]:4d}  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
