"""``sopeek.core.native.platform_gpu``：启动器定位与 PE 导出解析。"""

from __future__ import annotations

from pathlib import Path

import pytest

from sopeek.core.native import platform_gpu


pytestmark = pytest.mark.unit


def test_launcher_path_lives_in_packaging_launcher() -> None:
    """启动器路径随脚本迁移到 ``packaging/launcher/``（不再硬编码盘符）。"""
    path = platform_gpu.launcher_exe_path()
    assert isinstance(path, Path)
    assert path.name == platform_gpu.LAUNCHER_EXE_NAME
    assert path.parent.name == "launcher"
    assert path.parent.parent.name == "packaging"


def test_launcher_exists_matches_filesystem() -> None:
    assert platform_gpu.launcher_exists() is platform_gpu.launcher_exe_path().is_file()


def test_required_exports_are_declared() -> None:
    assert platform_gpu.REQUIRED_GPU_EXPORTS == (
        "NvOptimusEnablement",
        "AmdPowerXpressRequestHighPerformance",
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("RENDER_GPU=NVIDIA GeForce RTX 4060\nADAPTERS=2\n", {"render_gpu": "NVIDIA GeForce RTX 4060", "adapters": 2}),
        ("RENDER_GPU=\nADAPTERS=abc\n", {"render_gpu": "unknown", "adapters": -1}),
        ("", {"render_gpu": "unknown", "adapters": -1}),
        ("  RENDER_GPU=Intel   \n  ADAPTERS=1  \n", {"render_gpu": "Intel", "adapters": 1}),
    ],
)
def test_parse_affinity_output(text: str, expected: dict) -> None:
    assert platform_gpu.parse_affinity_output(text) == expected


def test_read_pe_exports_on_non_pe_file_is_empty(tmp_path: Path) -> None:
    """非 PE 文件返回空列表而不是抛异常（调用方按“无导出”处理）。"""
    bogus = tmp_path / "bogus.exe"
    bogus.write_bytes(b"not a PE file at all")
    assert platform_gpu.read_pe_exports(bogus) == []


def test_launcher_has_gpu_exports_is_false_without_launcher(tmp_path: Path) -> None:
    missing = tmp_path / "SPK-Launcher.exe"
    assert platform_gpu.launcher_has_gpu_exports(missing) is False
