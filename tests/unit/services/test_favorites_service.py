#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FavoritesService 单元测试
"""

import json
import os
from pathlib import Path

import pytest

from freeassetfilter.services.favorites_service import FavoritesService


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _make_service(tmp_path: Path) -> FavoritesService:
    """创建一个指向临时目录的 FavoritesService 实例。"""
    fav_file = str(tmp_path / "favorites.json")
    service = FavoritesService(favorites_file=fav_file)
    service.initialize()
    return service


def _write_favorites(tmp_path: Path, data) -> str:
    """向临时文件写入原始 JSON 数据，返回文件路径。"""
    path = tmp_path / "favorites.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# 测试：初始化 / 路径默认值
# ---------------------------------------------------------------------------

class TestInit:
    """构造与初始化相关测试。"""

    def test_default_favorites_file(self) -> None:
        """默认 favorites_file 指向项目 data/ 目录下的 favorites.json。"""
        service = FavoritesService()
        service.initialize()
        assert "data" in service.favorites_file
        assert service.favorites_file.endswith("favorites.json")
        service.dispose()

    def test_custom_favorites_file(self, tmp_path: Path) -> None:
        """可传入自定义 favorites_file 路径。"""
        custom_path = str(tmp_path / "custom_fav.json")
        service = FavoritesService(favorites_file=custom_path)
        service.initialize()
        assert service.favorites_file == custom_path
        service.dispose()

    def test_initialize_creates_parent_dir(self, tmp_path: Path) -> None:
        """initialize() 应自动创建父目录。"""
        nested = tmp_path / "sub" / "deep" / "fav.json"
        assert not nested.parent.exists()
        service = FavoritesService(favorites_file=str(nested))
        service.initialize()
        assert nested.parent.exists()
        service.dispose()


# ---------------------------------------------------------------------------
# 测试：load()
# ---------------------------------------------------------------------------

class TestLoad:
    """从磁盘加载收藏夹数据。"""

    def test_load_returns_empty_when_no_file(self, tmp_path: Path) -> None:
        """文件不存在时返回空列表。"""
        service = _make_service(tmp_path)
        assert service.load() == []

    def test_load_returns_list_from_file(self, tmp_path: Path) -> None:
        """正常 JSON 列表文件应正确加载。"""
        paths = ["/a/b.txt", "/c/d.png"]
        _write_favorites(tmp_path, paths)
        service = _make_service(tmp_path)
        assert service.load() == paths

    def test_load_returns_empty_on_corrupted_json(self, tmp_path: Path) -> None:
        """损坏的 JSON 应返回空列表。"""
        (tmp_path / "favorites.json").write_text("{bad json", encoding="utf-8")
        service = _make_service(tmp_path)
        assert service.load() == []

    def test_load_returns_empty_on_wrong_type(self, tmp_path: Path) -> None:
        """JSON 不是列表时（如 dict）应返回空列表。"""
        _write_favorites(tmp_path, {"key": "value"})
        service = _make_service(tmp_path)
        assert service.load() == []

    def test_load_caches_result(self, tmp_path: Path) -> None:
        """多次调用 load() 应返回同一缓存结果。"""
        paths = ["/a.txt"]
        _write_favorites(tmp_path, paths)
        service = _make_service(tmp_path)
        assert service.load() == paths
        # 修改文件内容（模拟外部修改）
        _write_favorites(tmp_path, ["/b.txt"])
        # 应返回旧缓存，而非新内容
        assert service.load() == paths

    def test_load_empty_json_array(self, tmp_path: Path) -> None:
        """空 JSON 数组 [] 应正常加载为空列表。"""
        _write_favorites(tmp_path, [])
        service = _make_service(tmp_path)
        assert service.load() == []


# ---------------------------------------------------------------------------
# 测试：save()
# ---------------------------------------------------------------------------

class TestSave:
    """持久化收藏夹数据到磁盘。"""

    def test_save_writes_file(self, tmp_path: Path) -> None:
        """save() 应将数据写入 JSON 文件。"""
        paths = ["/x/y.txt", "/z/w.png"]
        service = _make_service(tmp_path)
        service.save(paths)
        saved = json.loads((tmp_path / "favorites.json").read_text(encoding="utf-8"))
        assert saved == paths

    def test_save_overwrites_existing(self, tmp_path: Path) -> None:
        """save() 应覆盖已有文件内容。"""
        _write_favorites(tmp_path, ["/old.txt"])
        service = _make_service(tmp_path)
        service.save(["/new.txt"])
        saved = json.loads((tmp_path / "favorites.json").read_text(encoding="utf-8"))
        assert saved == ["/new.txt"]

    def test_save_updates_cache(self, tmp_path: Path) -> None:
        """save() 后 load() 应返回新数据。"""
        service = _make_service(tmp_path)
        service.save(["/a.txt"])
        assert service.load() == ["/a.txt"]


# ---------------------------------------------------------------------------
# 测试：add()
# ---------------------------------------------------------------------------

class TestAdd:
    """添加路径到收藏夹（仅内存操作）。"""

    def test_add_returns_true_for_new(self, tmp_path: Path) -> None:
        """新路径应返回 True。"""
        service = _make_service(tmp_path)
        assert service.add("/new.txt") is True

    def test_add_returns_false_for_duplicate(self, tmp_path: Path) -> None:
        """重复路径应返回 False。"""
        service = _make_service(tmp_path)
        service.add("/dup.txt")
        assert service.add("/dup.txt") is False

    def test_add_increases_list(self, tmp_path: Path) -> None:
        """添加后列表长度应 +1。"""
        service = _make_service(tmp_path)
        service.add("/a.txt")
        service.add("/b.txt")
        assert len(service.load()) == 2


# ---------------------------------------------------------------------------
# 测试：remove()
# ---------------------------------------------------------------------------

class TestRemove:
    """从收藏夹移除路径。"""

    def test_remove_returns_true_for_existing(self, tmp_path: Path) -> None:
        """已收藏的路径移除应返回 True。"""
        service = _make_service(tmp_path)
        service.add("/rm.txt")
        assert service.remove("/rm.txt") is True

    def test_remove_returns_false_for_missing(self, tmp_path: Path) -> None:
        """不存在的路径移除应返回 False。"""
        service = _make_service(tmp_path)
        assert service.remove("/nonexistent.txt") is False

    def test_remove_decreases_list(self, tmp_path: Path) -> None:
        """移除后列表长度应 -1。"""
        service = _make_service(tmp_path)
        service.add("/a.txt")
        service.add("/b.txt")
        service.remove("/a.txt")
        assert len(service.load()) == 1


# ---------------------------------------------------------------------------
# 测试：contains()
# ---------------------------------------------------------------------------

class TestContains:
    """检查路径是否已收藏。"""

    def test_contains_returns_true_for_added(self, tmp_path: Path) -> None:
        """已添加的路径应返回 True。"""
        service = _make_service(tmp_path)
        service.add("/present.txt")
        assert service.contains("/present.txt") is True

    def test_contains_returns_false_for_absent(self, tmp_path: Path) -> None:
        """未添加的路径应返回 False。"""
        service = _make_service(tmp_path)
        assert service.contains("/absent.txt") is False

    def test_contains_returns_false_after_remove(self, tmp_path: Path) -> None:
        """移除后应返回 False。"""
        service = _make_service(tmp_path)
        service.add("/gone.txt")
        service.remove("/gone.txt")
        assert service.contains("/gone.txt") is False


# ---------------------------------------------------------------------------
# 测试：BaseService 生命周期
# ---------------------------------------------------------------------------

class TestLifecycle:
    """BaseService 的 initialize/dispose 生命周期。"""

    def test_initialize_called_once(self, tmp_path: Path) -> None:
        """多次 initialize() 仅首次执行。"""
        service = _make_service(tmp_path)
        assert service.initialize() is True
        assert service.initialize() is True  # 第二次应直接返回 True
        assert service.is_initialized is True

    def test_dispose_resets_state(self, tmp_path: Path) -> None:
        """dispose() 后 is_initialized 为 False。"""
        service = _make_service(tmp_path)
        service.initialize()
        service.dispose()
        assert service.is_initialized is False

    def test_load_after_reinitialize(self, tmp_path: Path) -> None:
        """dispose + initialize 后可重新加载。"""
        service = _make_service(tmp_path)
        service.save(["/persist.txt"])
        service.dispose()
        service.initialize()
        assert service.load() == ["/persist.txt"]
