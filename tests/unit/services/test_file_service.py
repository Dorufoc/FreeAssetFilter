#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FileService 单元测试

测试 freeassetfilter.services.file_service.FileService 的全部 5 个公共方法：
normalize_path, scan_directory, filter_files, sort_files 及单例模式。
纯文件系统操作，无需 QApplication。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock, patch

import pytest

from freeassetfilter.services.file_service import FileService


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _make_file_dict(
    name: str,
    is_dir: bool = False,
    size: int = 0,
    modified: str = "",
    created: str = "",
) -> Dict:
    """创建符合 FileService file_dict 格式的字典。

    Args:
        name: 文件名。
        is_dir: 是否为目录。
        size: 文件大小（字节）。
        modified: ISO 格式修改时间。
        created: ISO 格式创建时间。

    Returns:
        标准 file_dict。
    """
    suffix = ""
    if not is_dir:
        suffix = os.path.splitext(name)[1].lower().lstrip(".")
    return {
        "name": name,
        "path": f"/fake/{name}",
        "is_dir": is_dir,
        "size": size,
        "modified": modified,
        "created": created,
        "suffix": suffix,
    }


def _sorted_file_dicts() -> List[Dict]:
    """创建用于排序测试的混杂顺序文件字典列表。"""
    return [
        _make_file_dict("zeta.txt", size=300, modified="2024-03-01", created="2024-01-01"),
        _make_file_dict("Alpha.txt", size=100, modified="2024-01-01", created="2024-03-01"),
        _make_file_dict("beta.txt", size=200, modified="2024-02-01", created="2024-02-01"),
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_file_service_singleton() -> None:
    """每个测试前重置 FileService 单例状态，保证测试隔离。"""
    FileService._instance = None
    FileService._initialized = False
    yield
    FileService._instance = None
    FileService._initialized = False


@pytest.fixture
def service() -> FileService:
    """提供已初始化的 FileService 单例。"""
    svc = FileService()
    svc.initialize()
    return svc


# ===========================================================================
# Test: normalize_path
# ===========================================================================

class TestNormalizePath:
    """normalize_path() 静态方法测试。"""

    def test_normal_path(self) -> None:
        """正常路径应被 os.path.normpath 标准化。"""
        raw = "C:\\Users\\Test\\..\\Test\\file.txt"
        expected = os.path.normpath(raw)
        result = FileService.normalize_path(raw)
        assert result == expected

    def test_empty_string(self) -> None:
        """空字符串应返回空字符串。"""
        assert FileService.normalize_path("") == ""

    def test_none_like_empty(self) -> None:
        """None 等效于空字符串，应返回空字符串。"""
        # 实现中 file_path 为 falsy 时返回 ""
        # 类型注解为 str，此处使用 type: ignore 通过类型检查
        assert FileService.normalize_path(None) == ""  # type: ignore[arg-type]

    def test_relative_path(self) -> None:
        """相对路径也应标准化。"""
        result = FileService.normalize_path("foo/bar/../baz")
        assert ".." not in result


# ===========================================================================
# Test: scan_directory
# ===========================================================================

class TestScanDirectory:
    """scan_directory() 测试。"""

    def test_scan_normal_directory(self, tmp_path: Path, service: FileService) -> None:
        """扫描包含文件和子目录的正常目录，应返回完整的文件信息列表。"""
        # 准备：创建混合的文件/目录结构
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "script.py").write_text("print('test')")
        (tmp_path / "docs").mkdir()

        result = service.scan_directory(str(tmp_path))

        assert len(result) == 3
        names = {item["name"] for item in result}
        assert names == {"readme.txt", "script.py", "docs"}

        # 验证每个字典的键完整性
        for item in result:
            assert "name" in item
            assert "path" in item
            assert "is_dir" in item
            assert "size" in item
            assert "modified" in item
            assert "created" in item
            assert "suffix" in item

        # 验证目录项的属性
        dir_item = next(item for item in result if item["name"] == "docs")
        assert dir_item["is_dir"] is True
        assert dir_item["size"] == 0
        assert dir_item["suffix"] == ""

        # 验证文件项的属性
        file_item = next(item for item in result if item["name"] == "readme.txt")
        assert file_item["is_dir"] is False
        assert file_item["size"] == 5  # "hello" 为 5 字节
        assert file_item["suffix"] == "txt"

        # 验证时间戳格式为 ISO
        for item in result:
            if item["modified"]:
                assert "T" in item["modified"] or len(item["modified"]) >= 10
            if item["created"]:
                assert "T" in item["created"] or len(item["created"]) >= 10

    def test_empty_directory(self, tmp_path: Path, service: FileService) -> None:
        """空目录应返回空列表。"""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        assert service.scan_directory(str(empty_dir)) == []

    def test_hidden_files_skipped(self, tmp_path: Path, service: FileService) -> None:
        """以 ``.`` 开头的隐藏文件和目录应被跳过。"""
        (tmp_path / ".hidden_config").write_text("secret")
        (tmp_path / ".hidden_dir").mkdir()
        (tmp_path / "visible.txt").write_text("hello")

        result = service.scan_directory(str(tmp_path))

        names = {item["name"] for item in result}
        assert names == {"visible.txt"}
        assert ".hidden_config" not in names
        assert ".hidden_dir" not in names

    def test_nonexistent_path(self, service: FileService) -> None:
        """不存在的路径应返回空列表。"""
        nonexistent = "/nonexistent_path_that_does_not_exist_12345"
        result = service.scan_directory(nonexistent)
        assert result == []

    def test_path_is_file(self, tmp_path: Path, service: FileService) -> None:
        """传入文件路径（非目录）应返回空列表（NotADirectoryError 被捕获）。"""
        test_file = tmp_path / "not_a_dir.txt"
        test_file.write_text("content")
        result = service.scan_directory(str(test_file))
        assert result == []

    def test_path_is_symlink_to_dir(
        self, tmp_path: Path, service: FileService
    ) -> None:
        """符号链接应被跳过（即使指向目录）。"""
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        (real_dir / "inside.txt").write_text("data")

        symlink_path = tmp_path / "link_to_dir"
        try:
            symlink_path.symlink_to(real_dir, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            pytest.skip("当前环境不支持创建符号链接")

        result = service.scan_directory(str(tmp_path))
        assert "link_to_dir" not in {item["name"] for item in result}

    def test_scan_preserves_full_path(self, tmp_path: Path, service: FileService) -> None:
        """返回的 path 应为完整绝对路径。"""
        (tmp_path / "some_file.txt").write_text("data")
        result = service.scan_directory(str(tmp_path))
        for item in result:
            # path 应以 tmp_path 开头
            assert item["path"].startswith(str(tmp_path))
            assert os.path.isabs(item["path"])

    def test_scan_all_drives_returns_list(self, service: FileService) -> None:
        """_scan_all_drives 应返回盘符/根目录列表。"""
        result = service._scan_all_drives()
        assert isinstance(result, list)
        if os.name == "nt":
            assert len(result) >= 1  # 至少 C: 盘
            for item in result:
                assert item["is_dir"] is True
                assert item["size"] == 0
                assert item["suffix"] == ""
        else:
            assert len(result) == 1
            assert result[0]["name"] == "/"

    def test_scan_all_drives_has_valid_entries(
        self, service: FileService
    ) -> None:
        """_scan_all_drives 返回的每项均有有效字段。"""
        result = service._scan_all_drives()
        for item in result:
            assert "name" in item
            assert "path" in item
            assert "is_dir" in item
            assert "size" in item
            assert "modified" in item
            assert "created" in item
            assert "suffix" in item

    def test_scan_all_drives_stat_error(
        self, service: FileService
    ) -> None:
        """os.stat 失败时 modified/created 应为空字符串。"""
        with patch("os.stat", side_effect=OSError("模拟驱动不可访问")):
            result = service._scan_all_drives()
        if os.name == "nt":
            assert len(result) >= 1
            for item in result:
                assert item["modified"] == ""
                assert item["created"] == ""

    def test_scan_all_drives_unix_branch(
        self, service: FileService
    ) -> None:
        """在 Unix 分支下应返回根目录 ``/``。"""
        with patch("os.name", "posix"):
            with patch("os.stat") as mock_stat:
                mock_root = MagicMock()
                mock_root.st_mtime = 1_700_000_000
                mock_root.st_ctime = 1_700_000_000
                mock_stat.return_value = mock_root

                result = service._scan_all_drives()

        assert len(result) == 1
        assert result[0]["name"] == "/"
        assert result[0]["path"] == "/"
        assert result[0]["is_dir"] is True

    def test_scan_all_drives_unix_stat_error(
        self, service: FileService
    ) -> None:
        """Unix 分支下 os.stat 失败时 modified/created 应为空字符串。"""
        with patch("os.name", "posix"):
            with patch("os.stat", side_effect=OSError("模拟错误")):
                result = service._scan_all_drives()

        assert len(result) == 1
        assert result[0]["name"] == "/"
        assert result[0]["modified"] == ""
        assert result[0]["created"] == ""

    def test_scan_skips_symlink(
        self, tmp_path: Path, service: FileService
    ) -> None:
        """真实的符号链接文件应被跳过。"""
        (tmp_path / "real_file.txt").write_text("real")
        try:
            symlink = tmp_path / "link.txt"
            symlink.symlink_to(tmp_path / "real_file.txt")
        except (OSError, NotImplementedError, AttributeError):
            pytest.skip("当前环境不支持创建符号链接")

        result = service.scan_directory(str(tmp_path))
        names = {item["name"] for item in result}
        assert "real_file.txt" in names
        assert "link.txt" not in names

    def test_scan_skips_symlink_mocked(
        self, service: FileService
    ) -> None:
        """符号链接通过 is_symlink() 检测后被跳过（覆盖 line 281）。"""
        symlink_entry = MagicMock(spec=os.DirEntry)
        symlink_entry.name = "link_file.txt"
        symlink_entry.path = "/fake/link_file.txt"
        symlink_entry.is_symlink.return_value = True  # 触发 skip

        normal_entry = MagicMock(spec=os.DirEntry)
        normal_entry.name = "real_file.txt"
        normal_entry.path = "/fake/real_file.txt"
        normal_entry.is_symlink.return_value = False
        normal_entry.is_dir.return_value = False
        normal_stat = MagicMock()
        normal_stat.st_size = 200
        normal_stat.st_mtime = 1_700_000_000.0
        normal_stat.st_ctime = 1_700_000_000.0
        normal_entry.stat.return_value = normal_stat

        with patch("os.scandir") as mock_scandir:
            mock_scandir.return_value.__enter__.return_value = [
                symlink_entry, normal_entry,
            ]
            result = service._scan_normal_directory("/fake")

        assert len(result) == 1
        assert result[0]["name"] == "real_file.txt"

    def test_scan_skips_entry_on_stat_error(
        self, service: FileService
    ) -> None:
        """stat 失败的文件项应被跳过（OSError/PermissionError 被捕获）。"""
        good_entry = MagicMock(spec=os.DirEntry)
        good_entry.name = "good.txt"
        good_entry.path = "/fake/good.txt"
        good_entry.is_symlink.return_value = False
        good_entry.is_dir.return_value = False
        good_stat = MagicMock()
        good_stat.st_size = 100
        good_stat.st_mtime = 1_700_000_000.0
        good_stat.st_ctime = 1_700_000_000.0
        good_entry.stat.return_value = good_stat

        bad_entry = MagicMock(spec=os.DirEntry)
        bad_entry.name = "bad.txt"
        bad_entry.path = "/fake/bad.txt"
        bad_entry.is_symlink.return_value = False
        # stat 调用抛出异常
        bad_entry.stat.side_effect = OSError("模拟权限错误")

        with patch("os.scandir") as mock_scandir:
            mock_scandir.return_value.__enter__.return_value = [
                good_entry, bad_entry,
            ]
            result = service._scan_normal_directory("/fake")

        assert len(result) == 1
        assert result[0]["name"] == "good.txt"


# ===========================================================================
# Test: filter_files
# ===========================================================================

class TestFilterFiles:
    """filter_files() 测试。"""

    @staticmethod
    def _sample() -> List[Dict]:
        return [
            _make_file_dict("readme.txt"),
            _make_file_dict("script.py"),
            _make_file_dict("data.json"),
            _make_file_dict("notes.txt"),
        ]

    def test_default_pattern_matches_all(self, service: FileService) -> None:
        """默认 ``*`` 模式应匹配全部文件。"""
        files = self._sample()
        result = service.filter_files(files)
        assert len(result) == 4

    def test_specific_pattern_txt(self, service: FileService) -> None:
        """模式 ``*.txt`` 应只匹配 .txt 文件。"""
        files = self._sample()
        result = service.filter_files(files, "*.txt")
        assert len(result) == 2
        assert all(f["name"].endswith(".txt") for f in result)

    def test_empty_string_as_wildcard(self, service: FileService) -> None:
        """空字符串模式应视为 ``*``，匹配全部文件。"""
        files = self._sample()
        result = service.filter_files(files, "")
        assert len(result) == 4

    def test_question_mark_pattern(self, service: FileService) -> None:
        """``?`` 应匹配单个字符。"""
        files = [
            _make_file_dict("a.txt"),
            _make_file_dict("ab.txt"),
            _make_file_dict("abc.txt"),
        ]
        # ?? — 恰好匹配 2 个任意字符
        result = service.filter_files(files, "??.txt")
        assert len(result) == 1
        assert result[0]["name"] == "ab.txt"
        # ? — 恰好匹配 1 个任意字符
        result2 = service.filter_files(files, "?.txt")
        assert len(result2) == 1
        assert result2[0]["name"] == "a.txt"

    def test_case_insensitive(self, service: FileService) -> None:
        """筛选应不区分大小写。"""
        files = [
            _make_file_dict("README.TXT"),
            _make_file_dict("readme.txt"),
            _make_file_dict("readme.md"),
        ]
        result = service.filter_files(files, "*.txt")
        assert len(result) == 2

    def test_invalid_pattern_returns_empty(self, service: FileService) -> None:
        """无效的通配符模式应返回空列表（防御性异常捕获）。"""
        files = self._sample()
        with patch.object(re, "compile", side_effect=re.error("mock")):
            result = service.filter_files(files, "*.txt")
            assert result == []

    def test_no_matches_returns_empty(self, service: FileService) -> None:
        """无匹配文件时应返回空列表。"""
        files = self._sample()
        result = service.filter_files(files, "*.xyz")
        assert result == []

    def test_filter_does_not_mutate_input(self, service: FileService) -> None:
        """filter_files 不应修改传入的原始列表。"""
        files = self._sample()
        original_len = len(files)
        service.filter_files(files, "*.txt")
        assert len(files) == original_len

    def test_pattern_matches_directory(self, service: FileService) -> None:
        """模式应同时匹配文件和目录名。"""
        files = [
            _make_file_dict("assets", is_dir=True),
            _make_file_dict("assets.txt", is_dir=False),
            _make_file_dict("other.txt", is_dir=False),
        ]
        result = service.filter_files(files, "assets*")
        assert len(result) == 2
        assert {f["name"] for f in result} == {"assets", "assets.txt"}


# ===========================================================================
# Test: sort_files
# ===========================================================================

class TestSortFiles:
    """sort_files() 测试。"""

    def test_sort_by_name(self, service: FileService) -> None:
        """按名称不区分大小写升序排序。"""
        result = service.sort_files(_sorted_file_dicts(), key="name")
        names = [f["name"] for f in result]
        # 不区分大小写: Alpha → beta → zeta
        assert names == ["Alpha.txt", "beta.txt", "zeta.txt"]

    def test_sort_by_size(self, service: FileService) -> None:
        """按文件大小升序排序。"""
        result = service.sort_files(_sorted_file_dicts(), key="size")
        sizes = [f["size"] for f in result]
        assert sizes == [100, 200, 300]

    def test_sort_by_modified(self, service: FileService) -> None:
        """按修改时间升序排序。"""
        result = service.sort_files(_sorted_file_dicts(), key="modified")
        items = [(f["name"], f["modified"]) for f in result]
        assert items[0][1] <= items[1][1] <= items[2][1]

    def test_sort_by_created(self, service: FileService) -> None:
        """按创建时间升序排序。"""
        result = service.sort_files(_sorted_file_dicts(), key="created")
        items = [(f["name"], f["created"]) for f in result]
        assert items[0][1] <= items[1][1] <= items[2][1]

    def test_directories_before_files(self, service: FileService) -> None:
        """目录始终排在文件之前。"""
        files = [
            _make_file_dict("z_file.txt", is_dir=False),
            _make_file_dict("a_dir", is_dir=True),
            _make_file_dict("m_file.py", is_dir=False),
        ]
        result = service.sort_files(files, key="name")
        # 目录 a_dir 应在两个文件之前
        assert result[0]["name"] == "a_dir"
        assert result[0]["is_dir"] is True
        # 所有 is_dir=True 的项在 is_dir=False 之前
        dir_indices = [i for i, f in enumerate(result) if f["is_dir"]]
        file_indices = [i for i, f in enumerate(result) if not f["is_dir"]]
        if dir_indices and file_indices:
            assert max(dir_indices) < min(file_indices)

    def test_reverse_sort(self, service: FileService) -> None:
        """逆序排序应反转结果。"""
        forward = service.sort_files(_sorted_file_dicts(), key="name", reverse=False)
        backward = service.sort_files(_sorted_file_dicts(), key="name", reverse=True)
        assert list(reversed(forward)) == backward

    def test_unknown_key_falls_back_to_name(self, service: FileService) -> None:
        """未知排序键应回退为按 name 排序。"""
        result = service.sort_files(_sorted_file_dicts(), key="nonexistent_key")
        names = [f["name"] for f in result]
        assert names == ["Alpha.txt", "beta.txt", "zeta.txt"]

    def test_sort_does_not_mutate_input(self, service: FileService) -> None:
        """sort_files 不应修改传入的原始列表。"""
        files = _sorted_file_dicts()
        original_ids = [id(f) for f in files]
        service.sort_files(files, key="name")
        assert [id(f) for f in files] == original_ids

    def test_empty_list(self, service: FileService) -> None:
        """空列表应返回空列表。"""
        assert service.sort_files([], key="name") == []

    def test_single_item(self, service: FileService) -> None:
        """单元素列表应原样返回。"""
        files = [_make_file_dict("only.txt")]
        result = service.sort_files(files, key="name")
        assert len(result) == 1
        assert result[0]["name"] == "only.txt"

    def test_stable_sort_maintains_order_for_equal_keys(
        self, service: FileService
    ) -> None:
        """相同排序键的项应保留原始相对顺序（稳定排序，Python's sort 保证）。"""
        files = [
            _make_file_dict("b.txt", size=100),
            _make_file_dict("a.txt", size=200),
            _make_file_dict("c.txt", size=100),
        ]
        # 按 size 排序，b.txt(size=100) 和 c.txt(size=100) 应保持原始顺序
        result = service.sort_files(files, key="size")
        size_100 = [f["name"] for f in result if f["size"] == 100]
        assert size_100 == ["b.txt", "c.txt"]


# ===========================================================================
# Test: 单例模式
# ===========================================================================

class TestSingleton:
    """FileService 单例模式验证。"""

    def test_same_instance(self) -> None:
        """多次构造应返回同一实例。"""
        service1 = FileService()
        service2 = FileService()
        assert service1 is service2

    def test_initialize_once(self, service: FileService) -> None:
        """initialize() 仅首次执行实际逻辑，后续返回 True 但不重复执行。"""
        assert service.initialize() is True
        assert service.initialize() is True
        assert service.is_initialized is True

    def test_dispose_resets_state(self, service: FileService) -> None:
        """dispose() 后 is_initialized 为 False。"""
        service.dispose()
        assert service.is_initialized is False

    def test_reinitialize_after_dispose(self, service: FileService) -> None:
        """dispose → initialize 后可重新进入已初始化状态。"""
        service.dispose()
        service.initialize()
        assert service.is_initialized is True


# ===========================================================================
# Test: BaseService 生命周期集成
# ===========================================================================

class TestLifecycle:
    """通过 FileService 验证 BaseService 生命周期管理。"""

    def test_init_marks_as_initialized(self) -> None:
        """构造后 is_initialized 为 True（__init__ 自动标记初始化完成）。"""
        svc = FileService()
        assert svc.is_initialized is True

    def test_initialize_idempotent(self, service: FileService) -> None:
        """多次调用 initialize() 均返回 True。"""
        assert service.initialize() is True
        assert service.initialize() is True

    def test_scan_directory_works_after_initialize(
        self, tmp_path: Path, service: FileService
    ) -> None:
        """初始化后可正常执行扫描操作。"""
        (tmp_path / "hello.txt").write_text("data")
        result = service.scan_directory(str(tmp_path))
        assert len(result) == 1
