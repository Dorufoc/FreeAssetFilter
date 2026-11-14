"""``sopeek.utils.file_icon_helper``：类型图标解析（默认目录来自 ``_paths``）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from sopeek.utils import file_icon_helper


pytestmark = pytest.mark.unit


def test_default_icon_dir_is_package_resources() -> None:
    """默认图标目录必须是随包 ``resources/icons``（迁移前是 ``utils/../icons``）。"""
    from sopeek._paths import icons_dir

    video_icon = file_icon_helper.get_file_icon_path({"suffix": "mp4", "is_dir": False})
    assert Path(video_icon).parent == icons_dir()


def test_known_types_resolve_to_existing_svg() -> None:
    for info in (
        {"suffix": "jpg", "is_dir": False},
        {"suffix": "mp4", "is_dir": False},
        {"suffix": "mp3", "is_dir": False},
        {"is_dir": True},
    ):
        path = Path(file_icon_helper.get_file_icon_path(info))
        assert path.is_file(), path


def test_explicit_icon_dir_is_respected(tmp_path: Path) -> None:
    """传入目录时只在该目录里找（找不到也不回退到随包资源）。"""
    (tmp_path / "视频 – 3.svg").write_text("<svg/>", encoding="utf-8")
    resolved = Path(file_icon_helper.get_file_icon_path({"suffix": "mp4"}, str(tmp_path)))
    assert resolved == tmp_path / "视频 – 3.svg"


def test_missing_v3_icon_falls_back_to_plain_name(tmp_path: Path) -> None:
    (tmp_path / "视频.svg").write_text("<svg/>", encoding="utf-8")
    resolved = Path(file_icon_helper.get_file_icon_path({"suffix": "mp4"}, str(tmp_path)))
    assert resolved == tmp_path / "视频.svg"


def test_unknown_suffix_returns_a_path_not_an_exception(tmp_path: Path) -> None:
    resolved = file_icon_helper.get_file_icon_path({"suffix": "zzz"}, str(tmp_path))
    assert isinstance(resolved, str)
