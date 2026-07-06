"""Centralized resource path resolver for FreeAssetFilter.

This module is the single source of truth for locating resource directories
(DLLs, native binaries, 7z, icons) after the core reorganization.
All moved core modules should import from here rather than hardcoding paths.

Usage:
    from freeassetfilter.core._paths import core_dir, native_bin_dir
"""

from __future__ import annotations

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


__all__ = [
    "core_dir",
    "native_bin_dir",
    "archive_7z_dir",
    "icons_dir",
]
