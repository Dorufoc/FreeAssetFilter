"""``sopeek.utils.path_utils`` 的校验与资源定位行为。"""

from __future__ import annotations

from pathlib import Path

import pytest

from sopeek.utils import path_utils


pytestmark = pytest.mark.unit


# ── 文件名 / 扩展名 / 数值校验 ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    ["正常文件.txt", "a.b.c.mkv", " 前后空格.mp4".strip(), "中文 名字 带空格.png"],
)
def test_validate_filename_accepts_ordinary_names(name: str) -> None:
    assert path_utils.validate_filename(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "",                     # 空
        "   ",                  # 全空白
        "bad<name>.txt",        # 非法字符
        "bad|name",             # 非法字符
        "CON",                  # Windows 保留名
        "nul.txt",              # 保留名 + 扩展名
        "trailing.",            # 以点结尾
        "x" * 300,              # 超长
    ],
)
def test_validate_filename_rejects_invalid_names(name: str) -> None:
    assert path_utils.validate_filename(name) is False


def test_validate_filename_trims_surrounding_whitespace() -> None:
    """首尾空白会先被 strip，因此不会触发“以空格开头/结尾”的拒绝分支。"""
    assert path_utils.validate_filename(" leading.txt") is True
    assert path_utils.validate_filename("trailing.txt ") is True


def test_validate_filename_can_skip_reserved_names() -> None:
    """``check_reserved=False`` 时保留名放行（调用方自行决定语义）。"""
    assert path_utils.validate_filename("CON", check_reserved=False) is True


def test_validate_file_extension_uses_whitelist() -> None:
    assert path_utils.validate_file_extension("clip.MP4") is True
    assert path_utils.validate_file_extension("notes.md") is False
    assert path_utils.validate_file_extension("no_extension") is False
    assert path_utils.validate_file_extension("a.MKV", {".mkv"}, case_sensitive=True) is False
    assert path_utils.validate_file_extension("a.mkv", {".mkv"}, case_sensitive=True) is True


def test_validate_numeric_range_boundaries() -> None:
    assert path_utils.validate_numeric_range(5, 1, 10) is True
    assert path_utils.validate_numeric_range(1, 1, 10) is True
    assert path_utils.validate_numeric_range(10, 1, 10) is True
    assert path_utils.validate_numeric_range(0, 1, 10) is False
    assert path_utils.validate_numeric_range(11, 1, 10) is False
    assert path_utils.validate_numeric_range(None, 1, 10) is False
    assert path_utils.validate_numeric_range(None, 1, 10, allow_none=True) is True


# ── 注入字符 / 路径穿越 ────────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["a\nb", "a\rb", "a\x00b", "$(rm -rf /)", "${HOME}", "`whoami`"])
def test_contains_injection_chars_flags_dangerous_input(path: str) -> None:
    assert path_utils.contains_injection_chars(path) is True


@pytest.mark.parametrize("path", ["", "C:/正常/路径.txt", "名字 & 符号.txt"])
def test_contains_injection_chars_allows_shell_safe_text(path: str) -> None:
    assert path_utils.contains_injection_chars(path) is False


def test_validate_safe_path_resolves_and_guards_base(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    inside = base / "ok.txt"
    inside.write_text("x", encoding="utf-8")

    resolved = path_utils.validate_safe_path(str(inside), str(base))
    assert Path(resolved) == inside.resolve()

    with pytest.raises(ValueError):
        path_utils.validate_safe_path(str(tmp_path / "outside.txt"), str(base))

    with pytest.raises(ValueError):
        path_utils.validate_safe_path("")


def test_is_path_within_base_handles_siblings(tmp_path: Path) -> None:
    base = tmp_path / "base"
    sibling = tmp_path / "base-sibling"
    base.mkdir()
    sibling.mkdir()

    assert path_utils.is_path_within_base(str(base / "a.txt"), str(base)) is True
    assert path_utils.is_path_within_base(str(base), str(base)) is True
    # 前缀相同的兄弟目录不算“在 base 下”（分隔符检查）。
    assert path_utils.is_path_within_base(str(sibling / "a.txt"), str(base)) is False


def test_is_sensitive_path_blocks_system_dirs() -> None:
    assert path_utils.is_sensitive_path(r"C:\Windows\System32\drivers") is True
    assert path_utils.is_sensitive_path(r"C:\Program Files\Sopeek") is True
    assert path_utils.is_sensitive_path(r"C:\Users\someone\Pictures\a.png") is False


# ── 资源定位 ──────────────────────────────────────────────────────────────


def test_get_resource_path_finds_version_file() -> None:
    """``SPKVERSION`` 在仓库根；资源解析必须能找到它（更新检查依赖）。"""
    resolved = Path(path_utils.get_resource_path("SPKVERSION"))
    assert resolved.is_file()
    assert resolved.read_text(encoding="utf-8-sig").strip()


def test_get_resource_path_missing_file_returns_path_under_a_known_root() -> None:
    """缺失文件不抛异常，返回一个“像样”的绝对路径供调用方统一处理。"""
    resolved = path_utils.get_resource_path("definitely-not-here.bin")
    assert Path(resolved).is_absolute()
    assert not Path(resolved).exists()


def test_get_app_data_path_creates_thumbnails_subdir(_isolated_data_dir: Path) -> None:
    data_dir = Path(path_utils.get_app_data_path())
    assert data_dir == _isolated_data_dir
    assert (data_dir / "thumbnails").is_dir()


def test_get_safe_dll_paths_returns_existing_dll_files() -> None:
    """返回的是**已存在的 DLL 文件**绝对路径（不是目录），供加载器按序尝试。"""
    paths = path_utils.get_safe_dll_paths("libmpv-2.dll")
    assert paths, "随包 libmpv-2.dll 应被解析到"
    for path in paths:
        assert Path(path).is_absolute()
        assert Path(path).is_file()


def test_get_safe_dll_paths_unknown_dll_is_empty() -> None:
    assert path_utils.get_safe_dll_paths("definitely-not-a-real-dll.dll") == []
