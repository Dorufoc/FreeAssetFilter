# -*- coding: utf-8 -*-
"""``FileService``（freeassetfilter/services/file_service.py）单元测试。

覆盖（happy + boundary/error 各至少一条）：

* ``normalize_path`` —— 空串/None/尾随分隔符/混合分隔符/点段规范化
* ``scan_directory`` —— 正常目录（跳过隐藏文件）、空目录、目录路径、
  不存在路径、不可读目录、文件路径传参，以及 symlink 条目跳过
* ``filter_files`` —— ``*``/``?``/混合通配符/空模式/大小写不敏感/无匹配/缺 name 键
* ``sort_files`` —— 目录优先 + 按 name/size/modified 排序、未知键回退、
  reverse 语义、不改动原列表

FileService 为单例且不在 conftest 的 ``reset_singletons`` 清单内，故本文件
自带 autouse fixture 在测试前后归零 ``_instance``/``_initialized``。
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

from freeassetfilter.services.file_service import FileService

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_file_service_singleton() -> None:
    """在测试前后归零 FileService 单例，保证每测试全新实例。

    Returns:
        None。
    """
    FileService._instance = None
    FileService._initialized = False
    yield
    FileService._instance = None
    FileService._initialized = False


def _file_entry(
    name: str,
    is_dir: bool = False,
    size: int = 0,
    modified: str = "",
    created: str = "",
) -> Dict[str, Any]:
    """构造 file_selector 兼容的文件信息字典（排序测试辅助）。

    Args:
        name: 文件名。
        is_dir: 是否目录。
        size: 文件大小（字节）。
        modified: ISO 修改时间字符串。
        created: ISO 创建时间字符串。

    Returns:
        Dict[str, Any]: 标准 file_info 字典。
    """
    return {
        "name": name,
        "path": name,
        "is_dir": is_dir,
        "size": size,
        "modified": modified,
        "created": created,
        "suffix": "",
    }


class _FakeEntry:
    """最小 os.DirEntry 替身，用于 symlink 跳过逻辑测试。"""

    def __init__(self, name: str, is_symlink: bool = False, is_dir: bool = False) -> None:
        """初始化替身。

        Args:
            name: 条目名。
            is_symlink: is_symlink() 返回值。
            is_dir: is_dir() 返回值。
        """
        self.name: str = name
        self._is_symlink: bool = is_symlink
        self._is_dir: bool = is_dir

    @property
    def path(self) -> str:
        """条目完整路径（此处即名称）。"""
        return self.name

    def is_symlink(self, follow_symlinks: bool = True) -> bool:
        """是否符号链接。"""
        return self._is_symlink

    def is_dir(self, follow_symlinks: bool = True) -> bool:
        """是否目录。"""
        return self._is_dir

    def stat(self, follow_symlinks: bool = True) -> os.stat_result:
        """伪造固定 stat 结果。"""
        fixed: int = 1_000_000_000
        return os.stat_result(
            (0o100644, 0, 0, 0, 0, 0, 100, fixed, fixed, fixed)
        )


class _FakeScandir:
    """os.scandir 上下文管理器替身。"""

    def __init__(self, entries: List[_FakeEntry]) -> None:
        """初始化替身。

        Args:
            entries: 迭代产出的条目序列。
        """
        self._entries: List[_FakeEntry] = entries

    def __enter__(self) -> "_FakeScandir":
        """上下文进入。"""
        return self

    def __exit__(self, *args: object) -> bool:
        """上下文退出（不吞异常）。"""
        return False

    def __iter__(self) -> Iterator[_FakeEntry]:
        """返回条目迭代器。"""
        return iter(self._entries)


# =============================================================================
# normalize_path
# =============================================================================
class TestNormalizePath:
    """路径标准化"""

    def test_normalize_plain_relative(self) -> None:
        """普通相对路径返回 normpath 结果。"""
        assert FileService.normalize_path("folder/file.txt") == os.path.normpath(
            "folder/file.txt"
        )

    def test_normalize_mixed_separators_and_dotdot(self) -> None:
        """混合分隔符 + 点段被规范化。"""
        assert FileService.normalize_path("C:\\foo\\..\\bar") == os.path.normpath(
            "C:\\foo\\..\\bar"
        )

    def test_normalize_trailing_separator(self) -> None:
        """尾随分隔符被去除。"""
        assert FileService.normalize_path("C:\\temp\\") == os.path.normpath(
            "C:/temp/"
        )

    def test_normalize_empty_returns_empty(self) -> None:
        """空字符串原样返回空字符串。"""
        assert FileService.normalize_path("") == ""

    def test_normalize_none_returns_empty(self) -> None:
        """边界：None 按空串处理返回空字符串。"""
        assert FileService.normalize_path(None) == ""  # type: ignore[arg-type]

    def test_normalize_unicode_path_kept(self) -> None:
        """中文路径规范化后保留。"""
        assert FileService.normalize_path("D:\\素材\\图片.png") == os.path.normpath(
            "D:/素材/图片.png"
        )


# =============================================================================
# scan_directory
# =============================================================================
class TestScanDirectory:
    """目录扫描"""

    def test_scan_happy_path(self, tmp_path: Path) -> None:
        """正常目录：隐藏文件被跳过，字段完整，目录条目 is_dir=True。"""
        (tmp_path / "a.txt").write_text("aaa", encoding="utf-8")
        (tmp_path / "b.jpg").write_bytes(b"img")
        (tmp_path / ".hidden.txt").write_text("h", encoding="utf-8")
        (tmp_path / "sub").mkdir(parents=True)

        files: List[Dict] = FileService().scan_directory(str(tmp_path))
        names: set[str] = {f["name"] for f in files}
        assert {"a.txt", "b.jpg", "sub"} <= names
        assert ".hidden.txt" not in names

        txt: Dict = next(f for f in files if f["name"] == "a.txt")
        assert txt["path"] == str(tmp_path / "a.txt")
        assert txt["is_dir"] is False
        assert txt["size"] == 3
        assert txt["suffix"] == "txt"
        assert txt["modified"].startswith(datetime.now().strftime("%Y"))
        assert "created" in txt

        sub: Dict = next(f for f in files if f["name"] == "sub")
        assert sub["is_dir"] is True
        assert sub["size"] == 0
        assert sub["suffix"] == ""

    def test_scan_suffix_uppercase_lowercased(self, tmp_path: Path) -> None:
        """大写扩展名被转小写并不带点。"""
        (tmp_path / "LOGO.PNG").write_bytes(b"img")
        files: List[Dict] = FileService().scan_directory(str(tmp_path))
        assert files[0]["suffix"] == "png"

    def test_scan_empty_directory(self, tmp_path: Path) -> None:
        """空目录返回空列表。"""
        assert FileService().scan_directory(str(tmp_path)) == []

    def test_scan_nonexistent_path_returns_empty(self, tmp_path: Path) -> None:
        """不存在的路径返回空列表。"""
        assert FileService().scan_directory(str(tmp_path / "nope")) == []

    def test_scan_file_path_returns_empty(self, tmp_path: Path) -> None:
        """传文件路径（非目录）返回空列表。"""
        f: Path = tmp_path / "single.txt"
        f.write_text("x", encoding="utf-8")
        assert FileService().scan_directory(str(f)) == []

    def test_scan_permission_error_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """目录不可读（PermissionError）返回空列表。"""
        def _raise_scandir(path: str) -> object:
            raise PermissionError("denied")

        monkeypatch.setattr(os, "scandir", _raise_scandir)
        assert FileService().scan_directory(str(tmp_path)) == []

    def test_scan_type_error_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """边界：TypeError 同样被吞并返回空列表。"""
        def _raise_scandir(path: str) -> object:
            raise TypeError("bad type")

        monkeypatch.setattr(os, "scandir", _raise_scandir)
        assert FileService().scan_directory(str(tmp_path)) == []

    def test_scan_skips_symlink_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """符号链接条目被跳过（以 DirectoryIterator 替身实测）。"""
        entries: List[_FakeEntry] = [
            _FakeEntry("real.txt", is_symlink=False),
            _FakeEntry("link.txt", is_symlink=True),
            _FakeEntry("folder", is_symlink=False, is_dir=True),
        ]

        def _fake_scandir(path: str) -> _FakeScandir:
            return _FakeScandir(entries)

        monkeypatch.setattr(os, "scandir", _fake_scandir)
        files: List[Dict] = FileService().scan_directory(str(tmp_path))
        names: set[str] = {f["name"] for f in files}
        assert names == {"real.txt", "folder"}
        assert all(f["is_dir"] == (f["name"] == "folder") for f in files)


# =============================================================================
# filter_files
# =============================================================================
class TestFilterFiles:
    """通配符筛选"""

    def test_filter_default_and_star_return_all(self) -> None:
        """默认模式与 ``*`` 均返回全部（含缺省 name 键条目）。"""
        files: List[Dict] = [
            _file_entry("a.txt"),
            _file_entry("b.png"),
            {"path": "no-name", "is_dir": False},
        ]
        assert FileService().filter_files(files) == files
        assert FileService().filter_files(files, "*") == files

    def test_filter_empty_pattern_is_star(self) -> None:
        """空字符串模式等价于 ``*``。"""
        files: List[Dict] = [_file_entry("x.txt")]
        assert FileService().filter_files(files, "") == files

    def test_filter_extension_wildcard_case_insensitive(self) -> None:
        """扩展名过滤：``*.txt`` 大小写不敏感匹配。"""
        files: List[Dict] = [
            _file_entry("a.txt"),
            _file_entry("b.log"),
            _file_entry("ACME.TXT"),
        ]
        result: List[Dict] = FileService().filter_files(files, "*.txt")
        assert {f["name"] for f in result} == {"a.txt", "ACME.TXT"}

    def test_filter_question_mark_matches_single_char(self) -> None:
        """``?`` 匹配单个任意字符。"""
        files: List[Dict] = [
            _file_entry("a1.txt"),
            _file_entry("aa.txt"),
            _file_entry("a.txt"),
        ]
        result: List[Dict] = FileService().filter_files(files, "a?.txt")
        assert {f["name"] for f in result} == {"a1.txt", "aa.txt"}

    def test_filter_mixed_pattern(self) -> None:
        """混合 ``*`` 与 ``?`` 的通配符模式。"""
        files: List[Dict] = [
            _file_entry("photo.001.jpg"),
            _file_entry("photo.002.jpg"),
            _file_entry("photo..jpg"),
            _file_entry("doc.txt"),
        ]
        result: List[Dict] = FileService().filter_files(files, "photo.???.jpg")
        assert {f["name"] for f in result} == {"photo.001.jpg", "photo.002.jpg"}

    def test_filter_no_match_returns_empty(self) -> None:
        """无匹配时返回空列表。"""
        files: List[Dict] = [_file_entry("a.png")]
        assert FileService().filter_files(files, "*.jpg") == []

    def test_filter_missing_name_key_never_matches_non_star(self) -> None:
        """缺 name 键的条目在非 ``*`` 模式下不匹配。"""
        files: List[Dict] = [{"path": "no-name", "is_dir": False}]
        assert FileService().filter_files(files, "*.txt") == []

    def test_filter_returns_new_list(self) -> None:
        """命中模式返回新列表（不原地修改入参）。"""
        files: List[Dict] = [_file_entry("a.txt"), _file_entry("b.txt")]
        original: List[Dict] = list(files)
        FileService().filter_files(files, "*.txt")
        assert files == original


# =============================================================================
# sort_files
# =============================================================================
class TestSortFiles:
    """排序"""

    def test_sort_name_dirs_first_case_insensitive(self) -> None:
        """默认按 name：目录优先且大小写不敏感。"""
        files: List[Dict] = [
            _file_entry("b.txt"),
            _file_entry("dir_z", is_dir=True),
            _file_entry("A.TXT"),
            _file_entry("dir_a", is_dir=True),
        ]
        result: List[Dict] = FileService().sort_files(files)
        assert [f["name"] for f in result] == ["dir_a", "dir_z", "A.TXT", "b.txt"]

    def test_sort_by_size(self) -> None:
        """按 size：目录仍优先，其后按大小升序。"""
        files: List[Dict] = [
            _file_entry("a.txt", size=300),
            _file_entry("dir", is_dir=True, size=0),
            _file_entry("c.txt", size=50),
            _file_entry("b.txt", size=100),
        ]
        result: List[Dict] = FileService().sort_files(files, key="size")
        assert result[0]["name"] == "dir"
        assert [f["name"] for f in result[1:]] == ["c.txt", "b.txt", "a.txt"]

    def test_sort_by_modified(self) -> None:
        """按修改时间升序，目录仍优先。"""
        files: List[Dict] = [
            _file_entry("old", modified="2020-01-01"),
            _file_entry("new", modified="2023-05-05"),
            _file_entry("dir", is_dir=True),
        ]
        result: List[Dict] = FileService().sort_files(files, key="modified")
        assert result[0]["name"] == "dir"
        assert [f["name"] for f in result[1:]] == ["old", "new"]

    def test_sort_unknown_key_falls_back_to_name(self) -> None:
        """未知排序键回退为按 name。"""
        files: List[Dict] = [_file_entry("z.txt"), _file_entry("a.txt")]
        result: List[Dict] = FileService().sort_files(files, key="bogus")
        assert [f["name"] for f in result] == ["a.txt", "z.txt"]

    def test_sort_reverse_reverses_full_order(self) -> None:
        """reverse=True 反转整体：文件在前且降序，目录排最后（现状固化）。"""
        files: List[Dict] = [
            _file_entry("a.txt"),
            _file_entry("z.txt"),
            _file_entry("dir", is_dir=True),
        ]
        result: List[Dict] = FileService().sort_files(files, reverse=True)
        assert [f["name"] for f in result] == ["z.txt", "a.txt", "dir"]

    def test_sort_does_not_mutate_original(self) -> None:
        """排序返回新列表，不影响原始列表。"""
        files: List[Dict] = [_file_entry("b.txt"), _file_entry("a.txt")]
        original: List[Dict] = list(files)
        FileService().sort_files(files)
        assert files == original

    def test_sort_empty_list(self) -> None:
        """空列表排序返回空列表。"""
        assert FileService().sort_files([]) == []

    def test_sort_directory_without_size_stays_first(self) -> None:
        """目录缺省 size 时按 size 排序仍位于文件之前（目录优先谓词主导）。"""
        files: List[Dict] = [
            _file_entry("zz.txt", size=999),
            _file_entry("dir", is_dir=True),
        ]
        result: List[Dict] = FileService().sort_files(files, key="size")
        assert result[0]["name"] == "dir"
        assert result[1]["name"] == "zz.txt"