"""``sopeek.utils.version_info``：版本号以 ``SPKVERSION`` 为唯一来源。"""

from __future__ import annotations

import pytest

from sopeek.utils import version_info


pytestmark = pytest.mark.unit


def test_local_version_matches_spkversion_file() -> None:
    """读到的版本号必须与 ``SPKVERSION`` 第一行一致（去掉前导 ``v``）。"""
    from sopeek._paths import version_file

    raw_first_line = version_file().read_text(encoding="utf-8-sig").splitlines()[0].strip()
    expected = raw_first_line[1:] if raw_first_line[:1] in "vV" else raw_first_line
    assert version_info.get_local_version() == expected


def test_package_dunder_version_comes_from_spkversion() -> None:
    """``sopeek.__version__`` 不再硬编码，必须等于 ``get_local_version()``。"""
    import sopeek

    assert sopeek.__version__ == version_info.get_local_version()
    assert sopeek.__version__ != "1.0.0"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("v1.2.3", "1.2.3"),
        ("V1.2.3", "1.2.3"),
        ("1.2.3", "1.2.3"),
        ("  1.2.3  ", "1.2.3"),
        ("", "0.0.0"),
        ("   ", "0.0.0"),
    ],
)
def test_normalize_version(raw: str, expected: str) -> None:
    assert version_info._normalize_version(raw) == expected


def test_build_date_is_iso_or_none() -> None:
    """构建日期要么是严格 ``YYYY-MM-DD``，要么是 ``None``（不抛异常）。"""
    value = version_info.get_local_build_date()
    if value is not None:
        assert len(value) == 10
        assert value[4] == "-" and value[7] == "-"


def test_missing_version_file_falls_back(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """文件缺失时回退 ``0.0.0`` / ``None``，绝不抛异常。"""
    monkeypatch.setattr(
        version_info, "get_resource_path", lambda _name: str(tmp_path / "missing")
    )
    assert version_info.get_local_version() == "0.0.0"
    assert version_info.get_local_build_date() is None
