"""Centralized resource path resolver for FreeAssetFilter.

This module is the single source of truth for locating resource directories
(DLLs, native binaries, 7z, icons) after the core reorganization.
All moved core modules should import from here rather than hardcoding paths.

Usage:
    from freeassetfilter.core._paths import core_dir, native_bin_dir
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def core_dir() -> Path:
    """Returns the absolute path to the ``core/`` directory.

    This is the parent directory of this module file, resolved at import time.

    Returns:
        Path: Absolute path to ``freeassetfilter/core/``.
    """
    return Path(__file__).resolve().parent


def native_bin_dir() -> Path:
    """Returns the absolute path to the native binary directory.

    Houses mpv runtime DLLs (``libmpv-2.dll``, ffmpeg, libplacebo, etc.),
    compiled Rust/C++ binaries (``thumbnail_generator.dll``,
    ``rust_color_extractor_native.dll``), and ffmpeg/ffprobe executables.

    Returns:
        Path: ``core/native/bin/``.
    """
    return core_dir() / "native" / "bin"


def archive_7z_dir() -> Path:
    """Returns the absolute path to the 7-Zip archive utility directory.

    Contains ``7z.exe`` and ``7z.dll`` for archive preview/extraction.

    Returns:
        Path: ``core/native/bin/7z/``.
    """
    return core_dir() / "native" / "bin" / "7z"


def icons_dir() -> Path:
    """Returns the absolute path to the application icons directory.

    Houses SVG/PNG/ICO icon assets used throughout the UI.

    Returns:
        Path: ``icons/`` (sibling of ``core/``).
    """
    return core_dir().parent / "icons"


def get_app_data_path() -> Path:
    """Returns the absolute path to the application data directory.

    This is the canonical location for runtime data files such as
    ``last_path.json``.  Creates the directory if it does not exist.

    Returns:
        Path: ``freeassetfilter/data/``.
    """
    data_dir = core_dir().parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def soffice_paths() -> list[Path]:
    """Returns a de-duplicated list of directories that may contain soffice.

    Probes, in order:
    1. ``%ProgramFiles%\\LibreOffice\\program``
    2. ``%ProgramFiles(x86)%\\LibreOffice\\program``
    3. The parent directory of a ``soffice``/``soffice.com`` binary found
       via ``shutil.which`` on ``PATH``
    4. ``native_bin_dir()`` — portable/app-dir forward-compat candidate

    Every returned ``Path`` is a directory.  For the two fixed Program Files
    locations the directory must actually contain ``soffice.exe`` or
    ``soffice.com``; for which()/native_bin_dir candidates the existence of
    the resolved binary / directory is required.  This function never
    raises and never launches soffice — it is a path probe only; callers
    (e.g. the ``soffice_available`` test fixture) inspect the returned
    directories for a soffice binary themselves.

    Returns:
        list[Path]: De-duplicated, existence-filtered candidate
            directories; ``[]`` when no LibreOffice is detected.
    """
    candidates: list[Path] = []

    # 1/2: Standard Windows install locations (env-aware, hardcoded fallback).
    for program_files in (
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ):
        program_dir = Path(program_files) / "LibreOffice" / "program"
        if program_dir.is_dir() and any(
            (program_dir / name).is_file() for name in ("soffice.exe", "soffice.com")
        ):
            candidates.append(program_dir)

    # 3: PATH lookup — add the parent directory of any resolved binary.
    for name in ("soffice", "soffice.com"):
        try:
            found = shutil.which(name)
        except Exception:
            continue
        if found:
            candidates.append(Path(found).resolve().parent)

    # 4: Portable/app-dir forward-compat candidate.
    native_bin = native_bin_dir()
    if native_bin.is_dir():
        candidates.append(native_bin)

    # De-duplicate while preserving probe order.
    seen: set[Path] = set()
    result: list[Path] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
    return result


__all__ = [
    "core_dir",
    "native_bin_dir",
    "archive_7z_dir",
    "icons_dir",
    "get_app_data_path",
    "soffice_paths",
]
