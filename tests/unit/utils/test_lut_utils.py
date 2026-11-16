"""``sopeek.utils.lut_utils``：CUBE 解析、校验与存储目录。"""

from __future__ import annotations

from pathlib import Path

import pytest

from sopeek.utils.lut_utils import (
    CubeLUTParser,
    get_lut_preview_dir,
    get_lut_storage_dir,
    validate_lut_file,
)


pytestmark = pytest.mark.unit


def _write_cube(path: Path, size: int = 2, header: str = "LUT_3D_SIZE") -> Path:
    lines = ['TITLE "test lut"', f"{header} {size}"]
    count = size ** (3 if header == "LUT_3D_SIZE" else 1)
    for i in range(count):
        v = i / max(1, count - 1)
        lines.append(f"{v:.6f} {v:.6f} {v:.6f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_parse_3d_cube(tmp_path: Path) -> None:
    cube = _write_cube(tmp_path / "a.cube", size=2)
    parser = CubeLUTParser(str(cube))
    assert parser.parse() is True
    info = parser.get_info()
    assert info["title"] == "test lut"
    assert info["size"] == 2
    assert info["is_3d"] is True
    assert info["data_count"] == 8


def test_parse_1d_cube(tmp_path: Path) -> None:
    cube = _write_cube(tmp_path / "b.cube", size=4, header="LUT_1D_SIZE")
    parser = CubeLUTParser(str(cube))
    assert parser.parse() is True
    info = parser.get_info()
    assert info["is_3d"] is False
    assert info["size"] == 4
    assert info["data_count"] == 4


def test_parse_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    cube = tmp_path / "c.cube"
    cube.write_text(
        "# comment\n\nLUT_3D_SIZE 2\n# mid comment\n"
        "0 0 0\n0 0 1\n0 1 0\n0 1 1\n1 0 0\n1 0 1\n1 1 0\n1 1 1\n",
        encoding="utf-8",
    )
    parser = CubeLUTParser(str(cube))
    assert parser.parse() is True
    assert parser.get_info()["data_count"] == 8


def test_parse_incomplete_data_fails(tmp_path: Path) -> None:
    """数据行不足 ``size**3`` 时视为损坏。"""
    cube = tmp_path / "d.cube"
    cube.write_text("LUT_3D_SIZE 2\n0 0 0\n0 0 1\n", encoding="utf-8")
    parser = CubeLUTParser(str(cube))
    assert parser.parse() is False


def test_validate_rejects_missing_wrong_extension_and_empty(tmp_path: Path) -> None:
    assert validate_lut_file(str(tmp_path / "nope.cube")) == (False, "文件不存在")

    wrong = tmp_path / "x.txt"
    wrong.write_text("hi", encoding="utf-8")
    ok, message = validate_lut_file(str(wrong))
    assert ok is False and ".cube" in message

    empty = tmp_path / "empty.cube"
    empty.write_text("", encoding="utf-8")
    assert validate_lut_file(str(empty)) == (False, "文件为空")


def test_validate_accepts_good_cube(tmp_path: Path) -> None:
    cube = _write_cube(tmp_path / "good.cube", size=2)
    assert validate_lut_file(str(cube)) == (True, "")


def test_storage_and_preview_dirs_under_app_data(_isolated_data_dir: Path) -> None:
    """LUT 存储/预览目录落在应用数据目录的新分类子目录下。"""
    storage = Path(get_lut_storage_dir())
    preview = Path(get_lut_preview_dir())
    assert storage == _isolated_data_dir / "assets" / "luts"
    assert preview == _isolated_data_dir / "cache" / "lut_previews"
    assert storage.is_dir() and preview.is_dir()
