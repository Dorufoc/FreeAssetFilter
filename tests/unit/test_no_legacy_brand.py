# -*- coding: utf-8 -*-
"""Permanent RED regression gate: legacy brand must disappear from the tree.

This module mirrors the T2 PowerShell gate (``scripts/verify_no_legacy_brand.ps1``)
in pure Python so it can run inside pytest on any machine. Three surfaces are
covered:

* text content of every non-excluded file (BOM-aware decoding);
* file and directory names below the repository root (``Path.name`` only, so
  a checkout directory whose own name carries the brand never counts);
* the old top-level package must no longer be importable.

The forbidden patterns and the synthetic probe are assembled from string
fragments at runtime, which keeps this module free of any complete forbidden
literal and prevents self-matching.

All four tests are permanent gates and must pass: the three tree scanners plus
the synthetic-detection test that proves the scanner actually catches a hit.
"""

from __future__ import annotations

import codecs
import importlib.util
import re
import stat
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest

_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

# Assembled from fragments: no complete forbidden literal appears in source.
_BRAND: str = "free" + "asset" + "filter"
_BRAND_SPACED: str = "free" + r"[\s_-]*" + "asset" + r"[\s_-]*" + "filter"
_SHORT: str = "f" + "af"
_TRI_CLASS: str = "[" + "Ff" + "]" + "[" + "Aa" + "]" + "[" + "Ff" + "]"
_VERSION_TOKEN: str = _SHORT + "version"

# Exact T2 text pattern, rebuilt from the fragments above.
_TEXT_PATTERN: str = (
    "(?:(?i:"
    + _BRAND
    + "|"
    + _BRAND_SPACED
    + ")|(?<![A-Za-z0-9])"
    + _TRI_CLASS
    + r"(?=[A-Z_]|[_\-.\\/]|\b)"
    + r"|\b"
    + _VERSION_TOKEN
    + r"\b)"
)
_TEXT_RE: re.Pattern[str] = re.compile(_TEXT_PATTERN, re.MULTILINE)

# Exact T2 exclusion manifest (case-insensitive directory and file patterns).
_EXCLUSION_MANIFEST: Tuple[str, ...] = (
    ".git/",
    ".venv/",
    ".probe_venv/",
    ".probe_head_tree/",
    ".kilo/",
    ".trae/",
    ".zcode/",
    ".workbuddy/",
    ".qoder/",
    ".continue/",
    ".agents/",
    ".codegraph/",
    ".acl-recovery/",
    ".dsh-acl-recovery/",
    ".demo_out/",
    ".pytest_tmp/",
    ".VSCodeCounter/",
    "outputs/",
    "tests/log/",
    "build/",
    "dist/",
    "data/",
    ".omo/",
    "node_modules/",
    "__pycache__/",
    "*/target/",
    "*/build/",
    ".ruff_cache/",
    ".pytest_cache/",
    ".coverage",
    ".opencode/",
    ".reasonix/",
)

_REPARSE_FLAG: int = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _is_excluded(rel_path: str, is_directory: bool) -> bool:
    """Return True when a root-relative path matches the frozen manifest.

    Directory patterns follow the T2 semantics: a pattern with a leading
    ``*/`` matches that directory name at any depth; a pattern containing an
    inner ``/`` matches from the root; a bare directory name matches any path
    segment; a file pattern (no trailing slash) matches the basename only.

    Args:
        rel_path: Root-relative path using forward slashes.
        is_directory: Whether the path refers to a directory.

    Returns:
        bool: True when the path must be skipped by the scanners.
    """
    rel = rel_path.replace("\\", "/").lower()
    if not rel:
        return False
    for raw in _EXCLUSION_MANIFEST:
        pattern = raw.lower()
        if pattern.endswith("/"):
            if not is_directory:
                continue
            needle = pattern.rstrip("/")
            if needle.startswith("*/"):
                suffix = needle[2:]
                if rel == suffix or rel.endswith("/" + suffix):
                    return True
            elif "/" in needle:
                if rel == needle or rel.startswith(needle + "/"):
                    return True
            elif rel == needle or rel.endswith("/" + needle) or "/" + needle + "/" in rel:
                return True
        elif not is_directory:
            name = rel.rsplit("/", 1)[-1]
            if name == pattern:
                return True
    return False


def _is_reparse_point(path: Path) -> bool:
    """Return True for symlinks and Windows reparse points.

    Args:
        path: Candidate directory or file.

    Returns:
        bool: True when the entry must not be descended into.
    """
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & _REPARSE_FLAG) or path.is_symlink()


def _iter_entries(root: Path) -> Iterator[Tuple[Path, str, bool]]:
    """Yield ``(path, rel_path, is_dir)`` for entries beneath ``root``.

    The root itself is never yielded. Excluded directories are pruned before
    being pushed onto the stack, so their contents are never enumerated.

    Args:
        root: Directory that anchors the scan.

    Yields:
        Tuple[Path, str, bool]: Absolute path, forward-slash relative path,
        and whether the entry is a directory.
    """
    stack: List[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name)
        except OSError:
            continue
        for child in children:
            if _is_reparse_point(child):
                continue
            rel = child.relative_to(root).as_posix()
            try:
                is_directory = child.is_dir()
            except OSError:
                continue
            if is_directory:
                if _is_excluded(rel, True):
                    continue
                yield child, rel, True
                stack.append(child)
            else:
                if _is_excluded(rel, False):
                    continue
                yield child, rel, False


def _is_nul_heavy(data: bytes) -> bool:
    """Detect BOM-less UTF-16LE payloads using the T2 heuristic.

    Args:
        data: Raw file bytes.

    Returns:
        bool: True when the first 4096 bytes are at least 10% zero bytes and
        at least 90% of the high bytes are zero.
    """
    sample = data[:4096]
    if len(sample) < 8:
        return False
    pairs = len(sample) // 2
    zero_count = 0
    high_zero_count = 0
    for index in range(0, pairs * 2, 2):
        if sample[index] == 0:
            zero_count += 1
        if sample[index + 1] == 0:
            zero_count += 1
            high_zero_count += 1
    zero_ratio = zero_count / (pairs * 2)
    high_zero_ratio = high_zero_count / pairs
    return zero_ratio >= 0.10 and high_zero_ratio >= 0.90


def _decode_bytes(data: bytes) -> Optional[str]:
    """Decode file bytes in the T2 order, returning None when undecodable.

    Supported inputs: UTF-8 BOM, UTF-16LE/BE BOM, strict UTF-8, NUL-heavy
    UTF-16LE (even when strict UTF-8 also succeeds), plus strict UTF-16LE as a
    last attempt for NUL-heavy payloads.

    Args:
        data: Raw file bytes.

    Returns:
        Optional[str]: Decoded text, or None when the file must be skipped.
    """
    if not data:
        return ""
    if data.startswith(codecs.BOM_UTF8):
        try:
            return data[len(codecs.BOM_UTF8) :].decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None
    if data.startswith(codecs.BOM_UTF16_LE):
        try:
            return data[len(codecs.BOM_UTF16_LE) :].decode("utf-16-le", errors="strict")
        except UnicodeDecodeError:
            return None
    if data.startswith(codecs.BOM_UTF16_BE):
        try:
            return data[len(codecs.BOM_UTF16_BE) :].decode("utf-16-be", errors="strict")
        except UnicodeDecodeError:
            return None

    nul_heavy = _is_nul_heavy(data)
    try:
        text: Optional[str] = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        text = None
    if nul_heavy:
        try:
            return data.decode("utf-16-le", errors="strict")
        except UnicodeDecodeError:
            pass
    return text


def _scan_text(root: Path) -> List[Dict[str, Any]]:
    """Scan every decodable, non-excluded file beneath ``root`` for hits.

    Args:
        root: Directory that anchors the scan.

    Returns:
        List[Dict[str, Any]]: Hit records with ``path``, ``line``, and
        ``match`` keys.
    """
    hits: List[Dict[str, Any]] = []
    for path, rel_path, is_directory in _iter_entries(root):
        if is_directory:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        text = _decode_bytes(data)
        if text is None:
            continue
        for match in _TEXT_RE.finditer(text):
            hits.append(
                {
                    "path": rel_path,
                    "line": text.count("\n", 0, match.start()) + 1,
                    "match": match.group(0),
                }
            )
    return hits


def _scan_names(root: Path) -> List[Dict[str, Any]]:
    """Scan ``Path.name`` of every entry beneath ``root`` for hits.

    Args:
        root: Directory that anchors the scan.

    Returns:
        List[Dict[str, Any]]: Hit records with ``path``, ``name``, and
        ``is_dir`` keys.
    """
    hits: List[Dict[str, Any]] = []
    for path, rel_path, is_directory in _iter_entries(root):
        if _TEXT_RE.search(path.name):
            hits.append({"path": rel_path, "name": path.name, "is_dir": is_directory})
    return hits


def _format_sample(surface: str, hits: List[Dict[str, Any]], limit: int = 5) -> str:
    """Render a compact diagnostic message for failed assertions.

    Args:
        surface: Human-readable surface label.
        hits: Hit records produced by a scanner.
        limit: Maximum number of records to include.

    Returns:
        str: Total hit count plus the first ``limit`` records.
    """
    sample = hits[:limit]
    lines = [f"{surface}: {item}" for item in sample]
    return f"{len(hits)} hit(s); first {len(sample)}:\n" + "\n".join(lines)


def test_text_has_no_legacy_brand() -> None:
    """Full tree must contain no legacy-brand text."""
    hits = _scan_text(_PROJECT_ROOT)
    assert not hits, _format_sample("text", hits)


def test_path_names_have_no_legacy_brand() -> None:
    """No file or directory name beneath the root may carry the brand."""
    hits = _scan_names(_PROJECT_ROOT)
    assert not hits, _format_sample("name", hits)


def test_old_package_is_not_importable() -> None:
    """The old top-level package must be gone once the rename lands."""
    assert importlib.util.find_spec(_BRAND) is None


def test_scanner_detects_synthetic_hit(tmp_path: Path) -> None:
    """The shared scanner must catch a fragment-built synthetic hit."""
    probe_dir = tmp_path / "probe_tree"
    probe_dir.mkdir()
    probe_file = probe_dir / ("probe" + ".txt")
    probe_file.write_text("head " + _BRAND + " tail\n", encoding="utf-8")
    try:
        text_hits = _scan_text(probe_dir)
        name_hits = _scan_names(probe_dir)
        assert len(text_hits) == 1
        assert text_hits[0]["path"] == "probe.txt"
        assert text_hits[0]["match"].lower() == _BRAND.lower()
        assert text_hits[0]["line"] == 1
        assert name_hits == []
    finally:
        probe_file.unlink(missing_ok=True)
        probe_dir.rmdir()
