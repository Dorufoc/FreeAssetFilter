#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FavoritesRepository 单元测试

测试纯数据访问层 —— 文件 I/O 与类型安全边界。
不测试业务逻辑（去重、验证等）。
"""

import json
import os
from pathlib import Path

import pytest

from freeassetfilter.services.favorites_repository import FavoritesRepository


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path) -> FavoritesRepository:
    """创建一个指向临时目录的 FavoritesRepository 实例。"""
    return FavoritesRepository(filepath=str(tmp_path / "favorites.json"))


def _write_json(tmp_path: Path, data, filename: str = "favorites.json") -> str:
    """向临时文件写入原始 JSON 数据，返回文件路径。"""
    path = tmp_path / filename
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# 测试：构造 / 路径默认值
# ---------------------------------------------------------------------------

class TestInit:
    """构造与路径相关测试。"""

    def test_default_filepath_contains_data_favorites(self) -> None:
        """默认 filepath 应包含 data/favorites.json。"""
        repo = FavoritesRepository()
        assert "data" in repo.filepath
        assert repo.filepath.endswith("favorites.json")

    def test_custom_filepath(self, tmp_path: Path) -> None:
        """可传入自定义 filepath。"""
        custom_path = str(tmp_path / "my_favs.json")
        repo = FavoritesRepository(filepath=custom_path)
        assert repo.filepath == custom_path


# ---------------------------------------------------------------------------
# 测试：load()
# ---------------------------------------------------------------------------

class TestLoad:
    """从磁盘加载 JSON 文件。"""

    def test_load_returns_empty_when_no_file(self, tmp_path: Path) -> None:
        """文件不存在时返回空列表。"""
        repo = _make_repo(tmp_path)
        assert repo.load() == []

    def test_load_returns_list_from_file(self, tmp_path: Path) -> None:
        """正常 JSON 列表文件应正确加载。"""
        paths = ["/a/b.txt", "/c/d.png"]
        _write_json(tmp_path, paths)
        repo = _make_repo(tmp_path)
        assert repo.load() == paths

    def test_load_returns_empty_on_corrupted_json(self, tmp_path: Path) -> None:
        """损坏的 JSON 应返回空列表。"""
        (tmp_path / "favorites.json").write_text("{bad json", encoding="utf-8")
        repo = _make_repo(tmp_path)
        assert repo.load() == []

    def test_load_returns_empty_on_wrong_type_dict(self, tmp_path: Path) -> None:
        """JSON 是 dict 而非 list 时返回空列表。"""
        _write_json(tmp_path, {"key": "value"})
        repo = _make_repo(tmp_path)
        assert repo.load() == []

    def test_load_returns_empty_on_wrong_type_string(self, tmp_path: Path) -> None:
        """JSON 是 string 而非 list 时返回空列表。"""
        _write_json(tmp_path, "not_a_list")
        repo = _make_repo(tmp_path)
        assert repo.load() == []

    def test_load_returns_empty_on_wrong_type_number(self, tmp_path: Path) -> None:
        """JSON 是 number 而非 list 时返回空列表。"""
        _write_json(tmp_path, 42)
        repo = _make_repo(tmp_path)
        assert repo.load() == []

    def test_load_returns_empty_on_wrong_type_null(self, tmp_path: Path) -> None:
        """JSON 是 null 而非 list 时返回空列表。"""
        _write_json(tmp_path, None)
        repo = _make_repo(tmp_path)
        assert repo.load() == []

    def test_load_empty_json_array(self, tmp_path: Path) -> None:
        """空 JSON 数组 [] 应正常加载为空列表。"""
        _write_json(tmp_path, [])
        repo = _make_repo(tmp_path)
        assert repo.load() == []

    def test_load_with_non_ascii_paths(self, tmp_path: Path) -> None:
        """包含非 ASCII 字符的路径应正确加载。"""
        paths = ["/中文/文件.txt", "/日本語/ファイル.png"]
        _write_json(tmp_path, paths)
        repo = _make_repo(tmp_path)
        assert repo.load() == paths

    def test_load_error_on_directory(self, tmp_path: Path) -> None:
        """当文件路径是一个目录时，应返回空列表。"""
        repo = _make_repo(tmp_path)
        # 创建一个同名目录代替文件
        os.makedirs(repo.filepath, exist_ok=True)
        assert repo.load() == []

    def test_load_does_not_cache(self, tmp_path: Path) -> None:
        """每次调用 load() 都应重新读取文件内容（无缓存）。"""
        paths_a = ["/a.txt"]
        _write_json(tmp_path, paths_a)
        repo = _make_repo(tmp_path)
        assert repo.load() == paths_a

        # 修改文件内容
        paths_b = ["/b.txt"]
        _write_json(tmp_path, paths_b)
        # 应读取新内容
        assert repo.load() == paths_b


# ---------------------------------------------------------------------------
# 测试：save()
# ---------------------------------------------------------------------------

class TestSave:
    """持久化数据到 JSON 文件。"""

    def test_save_writes_file(self, tmp_path: Path) -> None:
        """save() 应将数据写入 JSON 文件。"""
        paths = ["/x/y.txt", "/z/w.png"]
        repo = _make_repo(tmp_path)
        repo.save(paths)
        saved = json.loads(
            (tmp_path / "favorites.json").read_text(encoding="utf-8")
        )
        assert saved == paths

    def test_save_overwrites_existing(self, tmp_path: Path) -> None:
        """save() 应覆盖已有文件内容。"""
        _write_json(tmp_path, ["/old.txt"])
        repo = _make_repo(tmp_path)
        repo.save(["/new.txt"])
        saved = json.loads(
            (tmp_path / "favorites.json").read_text(encoding="utf-8")
        )
        assert saved == ["/new.txt"]

    def test_save_empty_list(self, tmp_path: Path) -> None:
        """保存空列表应写入 []。"""
        repo = _make_repo(tmp_path)
        repo.save([])
        saved = json.loads(
            (tmp_path / "favorites.json").read_text(encoding="utf-8")
        )
        assert saved == []

    def test_save_creates_parent_directory(self, tmp_path: Path) -> None:
        """父目录不存在时自动创建。"""
        nested = tmp_path / "sub" / "deep" / "fav.json"
        repo = FavoritesRepository(filepath=str(nested))
        repo.save(["/path.txt"])
        assert nested.exists()

    def test_save_writes_valid_json(self, tmp_path: Path) -> None:
        """写入内容应为合法 JSON。"""
        paths = ["/a.txt", "/b.txt"]
        repo = _make_repo(tmp_path)
        repo.save(paths)
        # 再次读取应成功
        loaded = json.loads(
            (tmp_path / "favorites.json").read_text(encoding="utf-8")
        )
        assert loaded == paths

    def test_save_with_non_ascii_paths(self, tmp_path: Path) -> None:
        """非 ASCII 路径应正确写入。"""
        paths = ["/中文/文件.txt", "/日本語/ファイル.png"]
        repo = _make_repo(tmp_path)
        repo.save(paths)
        saved = json.loads(
            (tmp_path / "favorites.json").read_text(encoding="utf-8")
        )
        assert saved == paths

    def test_save_pretty_print(self, tmp_path: Path) -> None:
        """写入的 JSON 应为 pretty-print 格式（含缩进）。"""
        repo = _make_repo(tmp_path)
        repo.save(["/a.txt"])
        content = (tmp_path / "favorites.json").read_text(encoding="utf-8")
        # pretty-print 的 JSON 会包含换行和缩进
        assert "\n" in content
        assert "  " in content

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        """save() 后再 load() 应返回相同数据。"""
        paths = ["/1.txt", "/2.txt", "/3.txt"]
        repo = _make_repo(tmp_path)
        repo.save(paths)
        assert repo.load() == paths


# ---------------------------------------------------------------------------
# 测试：独立多实例隔离
# ---------------------------------------------------------------------------

class TestMultiInstance:
    """多个 Repository 实例之间的隔离性。"""

    def test_different_files_dont_interfere(self, tmp_path: Path) -> None:
        """不同的文件路径互不影响。"""
        repo_a = FavoritesRepository(filepath=str(tmp_path / "a.json"))
        repo_b = FavoritesRepository(filepath=str(tmp_path / "b.json"))

        repo_a.save(["/from_a.txt"])
        repo_b.save(["/from_b.txt"])

        assert repo_a.load() == ["/from_a.txt"]
        assert repo_b.load() == ["/from_b.txt"]
