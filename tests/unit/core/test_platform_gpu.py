#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for ``freeassetfilter.core.native.platform_gpu`` (W1, todo 10)."""

from __future__ import annotations

import subprocess

import pytest

from freeassetfilter.core.native import platform_gpu
from freeassetfilter.core.native.platform_gpu import (
    apply_gpu_profile,
    build_launcher_command,
    current_gpu_affinity,
    launcher_exe_path,
    launcher_has_gpu_exports,
    parse_affinity_output,
    read_pe_exports,
)


def test_launcher_exe_path_points_into_repo_launcher_dir() -> None:
    """launcher_exe_path resolves to <repo>/launcher/FAF-Launcher.exe."""
    exe = launcher_exe_path()
    assert exe.name == "FAF-Launcher.exe"
    assert exe.parent.name == "launcher"
    assert (exe.parent / "launcher.c").is_file()


def test_read_pe_exports_finds_both_w1_symbols() -> None:
    """The built launcher EXE exports both W1 GPU-request symbols."""
    exe = launcher_exe_path()
    if not exe.is_file():
        pytest.skip("launcher not built; run launcher/build_launcher.ps1")
    names = read_pe_exports(exe)
    assert "NvOptimusEnablement" in names
    assert "AmdPowerXpressRequestHighPerformance" in names


def test_launcher_has_gpu_exports_true_for_built_launcher() -> None:
    """Fail-closed check passes for the real built launcher."""
    exe = launcher_exe_path()
    if not exe.is_file():
        pytest.skip("launcher not built; run launcher/build_launcher.ps1")
    assert launcher_has_gpu_exports(exe) is True


def test_read_pe_exports_empty_for_non_pe_file(tmp_path) -> None:
    """Non-PE input yields [] (failed verification), never an exception."""
    junk = tmp_path / "junk.bin"
    junk.write_bytes(b"not a portable executable\x00\x01\x02")
    assert read_pe_exports(junk) == []
    assert launcher_has_gpu_exports(junk) is False


def test_apply_gpu_profile_accepts_all_three_modes() -> None:
    """performance/balanced/powersave accepted when launcher is usable."""
    exe = launcher_exe_path()
    if not exe.is_file():
        pytest.skip("launcher not built; run launcher/build_launcher.ps1")
    if not launcher_has_gpu_exports(exe):
        pytest.skip("launcher exports missing")
    assert apply_gpu_profile("performance") is True
    assert apply_gpu_profile("balanced") is True
    assert apply_gpu_profile("powersave") is True


def test_apply_gpu_profile_rejects_unknown_mode() -> None:
    """Unknown mode raises ValueError (explicit, not silent)."""
    with pytest.raises(ValueError, match="unknown GPU profile"):
        apply_gpu_profile("turbo")


def test_parse_affinity_output_contract() -> None:
    """RENDER_GPU=/ADAPTERS= lines parse; garbage falls back to unknown."""
    parsed = parse_affinity_output("RENDER_GPU=NVIDIA\nADAPTERS=5\n")
    assert parsed == {"render_gpu": "NVIDIA", "adapters": 5}
    parsed = parse_affinity_output("nothing useful here\n")
    assert parsed == {"render_gpu": "unknown", "adapters": -1}


def test_build_launcher_command_forwards_args() -> None:
    """Command starts with the launcher EXE and appends extra args."""
    cmd = build_launcher_command(["--open-path", "C:\\tmp"])
    assert cmd[0] == str(launcher_exe_path())
    assert cmd[1:] == ["--open-path", "C:\\tmp"]
    assert build_launcher_command() == [str(launcher_exe_path())]


@pytest.mark.skipif(
    not platform_gpu._DIAG_SCRIPT.is_file(),
    reason="task-3 diagnostic script missing",
)
def test_current_gpu_affinity_live_single_sample() -> None:
    """Live diagnostic (1 sample) honours the output contract."""
    try:
        result = current_gpu_affinity(samples=1, interval=0, timeout=120)
    except Exception as exc:  # pragma: no cover - env dependent
        pytest.skip(f"diagnostic cannot run here: {exc}")
    assert result["render_gpu"] in ("NVIDIA", "Intel", "AMD", "unknown")
    assert isinstance(result["adapters"], int)
    assert "RENDER_GPU=" in str(result["raw"])
    assert result["returncode"] in (0, 2)


def test_launcher_propagates_child_exit_code() -> None:
    """Launcher waits and returns the child exit code (override path)."""
    exe = launcher_exe_path()
    if not exe.is_file():
        pytest.skip("launcher not built; run launcher/build_launcher.ps1")
    import os

    env = dict(os.environ)
    env["FAF_LAUNCHER_CMD"] = 'cmd.exe /c "exit 42"'
    proc = subprocess.run([str(exe)], env=env, capture_output=True,
                          timeout=60)
    assert proc.returncode == 42
