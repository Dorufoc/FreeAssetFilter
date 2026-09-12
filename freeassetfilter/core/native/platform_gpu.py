#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W1 discrete-GPU launcher integration (performance-ceiling-optimization).

This module is the Python-side companion of ``launcher/FAF-Launcher.exe``,
a tiny C launcher whose PE export table carries::

    NvOptimusEnablement = 1
    AmdPowerXpressRequestHighPerformance = 1

The NVIDIA Optimus / AMD PowerXpress driver scans the *executable image's*
PE exports to decide on the high-performance adapter; a ctypes global
inside ``python.exe`` can never be an export, so the request must live in
the launcher EXE (two independent plan reviews confirmed this). The
launcher itself creates no GPU surfaces -- all Qt/D3D initialisation
happens in the spawned child (``python -m freeassetfilter.app.main``),
which inherits the adapter selection.

Three-mode profile switch (todo 10 scope):

- ``performance``: launch via ``FAF-Launcher.exe`` (exports always on).
- ``balanced`` (default): same as performance -- the export itself is
  free and correct; power-throttling / core-pinning policy is W2's job
  (``platform_threads.py``, todo 11) and is NOT touched here.
- ``powersave``: accepted for API completeness; currently identical to
  balanced (no throttling changes owned by this module).

Only ``pathlib``/``struct``/``subprocess`` from the stdlib are used; no
third-party dependencies. Observation helpers never change driver state.
"""

from __future__ import annotations

import logging
import struct
import subprocess
import sys

from pathlib import Path

logger = logging.getLogger(__name__)

GPU_PROFILE_MODES: tuple[str, str, str] = (
    "performance",
    "balanced",
    "powersave",
)
"""Valid GPU profile modes."""

DEFAULT_GPU_PROFILE: str = "balanced"
"""Default profile: use the launcher, change no power policy."""

LAUNCHER_EXE_NAME: str = "FAF-Launcher.exe"
"""Launcher executable file name (built by ``launcher/build_launcher.ps1``)."""

REQUIRED_GPU_EXPORTS: tuple[str, str] = (
    "NvOptimusEnablement",
    "AmdPowerXpressRequestHighPerformance",
)
"""PE export names the launcher EXE must carry for W1 to work."""

_DIAG_SCRIPT: Path = (
    Path(__file__).resolve().parents[3]
    / ".omo"
    / "evidence"
    / "performance-ceiling-optimization"
    / "task-3"
    / "gpu_affinity_check.py"
)
"""Proven task-3 diagnostic (stdlib + ctypes, observation only)."""


def launcher_exe_path() -> Path:
    """Return the expected path of the built launcher EXE.

    Returns:
        Absolute path to ``launcher/FAF-Launcher.exe`` under the repo root
        (derived from this file's location, never hardcoded to a drive).
    """
    return (
        Path(__file__).resolve().parents[3] / "launcher" / LAUNCHER_EXE_NAME
    )


def launcher_exists() -> bool:
    """Check whether the launcher EXE has been built.

    Returns:
        True when ``launcher/FAF-Launcher.exe`` exists on disk.
    """
    return launcher_exe_path().is_file()


def read_pe_exports(exe_path: str | Path) -> list[str]:
    """List the PE export-table names of a Windows EXE/DLL (pure stdlib).

    Parses DOS header -> NT headers -> optional-header data directory[0]
    (export table) -> name pointer table. Returns an empty list for
    non-PE files instead of raising, so callers can treat "no exports"
    as a failed verification.

    Args:
        exe_path: Path to the image to inspect.

    Returns:
        Export names in table order (may be empty).
    """
    path = Path(exe_path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        logger.warning("read_pe_exports: cannot read %s: %s", path, exc)
        return []
    try:
        if len(data) < 0x40 or data[0:2] != b"MZ":
            return []
        (e_lfanew,) = struct.unpack_from("<I", data, 0x3C)
        if data[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
            return []
        coff = e_lfanew + 4
        (num_sections,) = struct.unpack_from("<H", data, coff + 2)
        (opt_size,) = struct.unpack_from("<H", data, coff + 16)
        _ = num_sections  # section scan is zero-entry terminated instead
        opt = coff + 20
        magic = struct.unpack_from("<H", data, opt)[0]
        if magic == 0x10B:  # PE32
            export_rva, _ = struct.unpack_from("<II", data, opt + 96)
        elif magic == 0x20B:  # PE32+
            export_rva, _ = struct.unpack_from("<II", data, opt + 112)
        else:
            return []
        if export_rva == 0:
            return []

        sections_off = opt + opt_size
        rva_to_file = _build_rva_map(data, sections_off)
        exp_off = _rva_to_offset(export_rva, rva_to_file)
        if exp_off is None:
            return []
        (_chars, _ts, _maj, _min, _name_rva, _base,
         _num_funcs, num_names, _addr_funcs, addr_names) = (
            struct.unpack_from("<IIHHIIIIIII", data, exp_off)[:10]
        )
        names_off = _rva_to_offset(addr_names, rva_to_file)
        if names_off is None:
            return []
        names: list[str] = []
        for i in range(num_names):
            (name_rva,) = struct.unpack_from("<I", data, names_off + 4 * i)
            str_off = _rva_to_offset(name_rva, rva_to_file)
            if str_off is None:
                continue
            end = data.index(b"\x00", str_off)
            names.append(data[str_off:end].decode("ascii", "replace"))
        return names
    except (struct.error, ValueError, IndexError, OverflowError) as exc:
        logger.warning("read_pe_exports: parse failed for %s: %s", path, exc)
        return []


def _build_rva_map(
    data: bytes, sections_off: int
) -> list[tuple[int, int, int]]:
    """Build (VirtualAddress, SizeOfRawData, PointerToRawData) section list.

    Args:
        data: Whole image bytes.
        sections_off: File offset of the first section header.

    Returns:
        List of section mapping triples.
    """
    return _section_table(data, sections_off)


def _section_table(
    data: bytes, sections_off: int
) -> list[tuple[int, int, int]]:
    """Read section headers starting at ``sections_off`` (best effort).

    The section count is recovered from the COFF header preceding the
    optional header; this helper scans at most 96 headers and stops at
    the first all-zero entry.

    Args:
        data: Whole image bytes.
        sections_off: File offset of the first section header.

    Returns:
        List of (VirtualAddress, SizeOfRawData, PointerToRawData) triples.
    """
    # COFF header sits 20 bytes before the optional header end anchor is
    # unknown here, so bound the scan instead: stop at zero entries.
    table: list[tuple[int, int, int]] = []
    for i in range(96):
        off = sections_off + 40 * i
        if off + 40 > len(data):
            break
        entry = data[off:off + 40]
        if entry == b"\x00" * 40:
            break
        vaddr, raw_size, raw_ptr = struct.unpack_from("<III", entry, 12)
        if raw_size == 0 or raw_ptr == 0:
            continue
        table.append((vaddr, raw_size, raw_ptr))
    return table


def _rva_to_offset(
    rva: int, sections: list[tuple[int, int, int]]
) -> int | None:
    """Map a Relative Virtual Address to a file offset via section table.

    Args:
        rva: Address to translate.
        sections: Section mapping triples from ``_section_table``.

    Returns:
        File offset, or None when no section contains the RVA.
    """
    for vaddr, raw_size, raw_ptr in sections:
        if vaddr <= rva < vaddr + raw_size:
            return raw_ptr + (rva - vaddr)
    return None


def launcher_has_gpu_exports(exe_path: str | Path | None = None) -> bool:
    """Verify the launcher EXE exports BOTH W1 GPU-request symbols.

    This is the fail-closed acceptance check: ``dumpbin /exports``
    output (or this pure-Python equivalent) must contain both names --
    "the build succeeded" alone proves nothing.

    Args:
        exe_path: Image to inspect (defaults to :func:`launcher_exe_path`).

    Returns:
        True only when both ``REQUIRED_GPU_EXPORTS`` names are present.
    """
    target = Path(exe_path) if exe_path is not None else launcher_exe_path()
    names = read_pe_exports(target)
    missing = [n for n in REQUIRED_GPU_EXPORTS if n not in names]
    if missing:
        logger.warning("launcher %s missing PE exports: %s", target, missing)
        return False
    return True


def parse_affinity_output(text: str) -> dict[str, object]:
    """Parse ``RENDER_GPU=``/``ADAPTERS=`` lines from diagnostic output.

    Args:
        text: Combined stdout of ``gpu_affinity_check.py``.

    Returns:
        Dict with ``render_gpu`` (str, ``"unknown"`` fallback) and
        ``adapters`` (int, ``-1`` when unparsable).
    """
    render_gpu = "unknown"
    adapters = -1
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("RENDER_GPU="):
            render_gpu = line.split("=", 1)[1].strip() or "unknown"
        elif line.startswith("ADAPTERS="):
            try:
                adapters = int(line.split("=", 1)[1].strip())
            except ValueError:
                adapters = -1
    return {"render_gpu": render_gpu, "adapters": adapters}


def current_gpu_affinity(
    samples: int = 3, interval: int = 1, timeout: int = 120
) -> dict[str, object]:
    """Run the task-3 diagnostic fresh and return the attribution.

    Always re-runs the script (no caching): pre/post comparisons must be
    same-session-comparable (stale-state probe).

    Args:
        samples: Number of GPU-engine counter samples.
        interval: Seconds between samples.
        timeout: Subprocess timeout in seconds.

    Returns:
        Dict with ``render_gpu``, ``adapters``, ``returncode`` and
        ``raw`` (full stdout). ``render_gpu`` is ``"unknown"`` when the
        script is missing or fails.
    """
    result: dict[str, object] = {
        "render_gpu": "unknown",
        "adapters": -1,
        "returncode": -1,
        "raw": "",
    }
    if not _DIAG_SCRIPT.is_file():
        logger.warning("GPU diagnostic script not found: %s", _DIAG_SCRIPT)
        return result
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(_DIAG_SCRIPT),
                "--samples",
                str(samples),
                "--interval",
                str(interval),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("GPU diagnostic failed to run: %s", exc)
        return result
    result["returncode"] = proc.returncode
    result["raw"] = proc.stdout
    result.update(parse_affinity_output(proc.stdout))
    return result


def apply_gpu_profile(mode: str = DEFAULT_GPU_PROFILE) -> bool:
    """Apply a GPU profile (performance|balanced|powersave).

    W1 scope is deliberately thin: the discrete-GPU export itself is
    always on (it is free and correct), and power-throttling / affinity
    policy belongs to W2 (``platform_threads.py``, todo 11) -- so this
    function validates the mode, verifies the launcher EXE is present
    with both PE exports, and logs the effective routing. No window
    creation logic, no settings-schema writes, no driver calls.

    Args:
        mode: One of ``"performance"``, ``"balanced"`` (default),
            ``"powersave"``.

    Returns:
        True when the mode is accepted and the launcher is usable;
        False when the launcher EXE is missing or fails export
        verification (caller should fall back to a direct launch).

    Raises:
        ValueError: When ``mode`` is not a known profile name.
    """
    if mode not in GPU_PROFILE_MODES:
        raise ValueError(
            f"unknown GPU profile {mode!r}; "
            f"expected one of {list(GPU_PROFILE_MODES)}"
        )
    exe = launcher_exe_path()
    if not exe.is_file():
        logger.warning(
            "GPU profile %s: launcher not built at %s; "
            "run launcher/build_launcher.ps1",
            mode,
            exe,
        )
        return False
    if not launcher_has_gpu_exports(exe):
        logger.warning(
            "GPU profile %s: launcher %s lacks W1 PE exports", mode, exe
        )
        return False
    logger.info(
        "GPU profile %s: routing via %s (W1 exports verified)",
        mode,
        exe,
    )
    return True


def build_launcher_command(extra_args: list[str] | None = None) -> list[str]:
    """Build the launcher command line for spawning the app.

    Args:
        extra_args: Additional argv forwarded to the child app
            (appended after the launcher EXE path).

    Returns:
        Command list ``[launcher_exe, *extra_args]``.
    """
    cmd: list[str] = [str(launcher_exe_path())]
    if extra_args:
        cmd.extend(extra_args)
    return cmd
