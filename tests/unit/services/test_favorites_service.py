# -*- coding: utf-8 -*-
"""``FavoritesService``（freeassetfilter/services/favorites_service.py）单元测试。

覆盖（happy + boundary/error 各至少一条）：

* 生命周期 —— initialize 创建父目录、dispose 幂等并清空内存缓存、
  销毁后可重初始化（磁盘数据保留）
* 增删查 —— add/remove/contains 往返、重复添加返回 False、
  不存在的移除返回 False
* 持久化 —— save 落盘 + 新实例 load 一致、中文原文落盘、
  缓存语义（首次 load 后磁盘改动不再可见）、损坏 JSON / 根类型错误 /
  读取异常均安全回退空列表

FavoritesService 非单例，每个测试通过 tmp_path 构造独立实例，
不触碰真实 ``data/favorites.json``。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from freeassetfilter.services.favorites_service import FavoritesService

pytestmark = pytest.mark.unit


@pytest.fixture
def fav_file(tmp_path: Path) -> str:
    """提供指向 tmp_path 的收藏夹文件路径。

    Args:
        tmp_path: pytest 内置的每测试临时目录。

    Returns:
        str: 收藏夹 JSON 文件路径。
    """
    return str(tmp_path / "favorites.json")


# =============================================================================
# 生命周期
# =============================================================================
class TestLifecycle:
    """生命周期管理"""

    def test_initialize_creates_parent_dir(self, tmp_path: Path) -> None:
        """initialize 确保收藏夹父目录存在。"""
        target: Path = tmp_path / "nested" / "deep" / "favs.json"
        svc: FavoritesService = FavoritesService(str(target))
        assert svc.initialize() is True
        assert (tmp_path / "nested" / "deep").is_dir()

    def test_initialize_is_idempotent(self, fav_file: str) -> None:
        """重复 initialize 均返回 True。"""
        svc: FavoritesService = FavoritesService(fav_file)
        assert svc.initialize() is True
        assert svc.initialize() is True

    def test_dispose_idempotent_and_clears_cache(self, fav_file: str) -> None:
        """dispose 幂等，清空内存缓存且 is_initialized 归位。"""
        svc: FavoritesService = FavoritesService(fav_file)
        svc.initialize()
        svc.add("C:\\a.png")
        svc.dispose()
        svc.dispose()  # 幂等：第二次不抛异常
        assert svc.is_initialized is False
        # 内存缓存已清空；磁盘无文件 → load 返回空列表
        assert svc.load() == []

    def test_reinitialize_keeps_disk_data(self, fav_file: str) -> None:
        """销毁后重新初始化，磁盘数据仍可加载。"""
        svc: FavoritesService = FavoritesService(fav_file)
        svc.save(["C:\\persist.png"])
        svc.dispose()
        svc.initialize()
        assert svc.load() == ["C:\\persist.png"]


# =============================================================================
# 增删查
# =============================================================================
class TestCrud:
    """增删查操作"""

    def test_add_and_contains_happy(self, fav_file: str) -> None:
        """添加后 contains 命中且处于待持久化内存列表。"""
        svc: FavoritesService = FavoritesService(fav_file)
        assert svc.add("C:\\a.png") is True
        assert svc.contains("C:\\a.png") is True
        assert svc._favorites == ["C:\\a.png"]

    def test_add_duplicate_returns_false(self, fav_file: str) -> None:
        """重复添加同一路径返回 False 且不重复。"""
        svc: FavoritesService = FavoritesService(fav_file)
        assert svc.add("C:\\a.png") is True
        assert svc.add("C:\\a.png") is False
        assert len(svc._favorites) == 1

    def test_remove_happy(self, fav_file: str) -> None:
        """移除成功返回 True，contains 变为 False。"""
        svc: FavoritesService = FavoritesService(fav_file)
        svc.add("C:\\a.png")
        assert svc.remove("C:\\a.png") is True
        assert svc.contains("C:\\a.png") is False
        assert svc._favorites == []

    def test_remove_missing_returns_false(self, fav_file: str) -> None:
        """移除不存在的路径返回 False。"""
        assert FavoritesService(fav_file).remove("C:\\nope.png") is False

    def test_contains_missing_returns_false(self, fav_file: str) -> None:
        """不存在的路径 contains 返回 False。"""
        assert FavoritesService(fav_file).contains("C:\\nope.png") is False

    def test_add_multiple_distinct_paths(self, fav_file: str) -> None:
        """多个不同路径可共存且保持添加顺序。"""
        svc: FavoritesService = FavoritesService(fav_file)
        svc.add("D:\\1.png")
        svc.add("D:\\2.png")
        assert svc._favorites == ["D:\\1.png", "D:\\2.png"]


# =============================================================================
# 持久化
# =============================================================================
class TestPersistence:
    """持久化与缓存语义"""

    def test_save_then_new_instance_loads(self, fav_file: str) -> None:
        """save 落盘后新实例 load 得到一致结果。"""
        expected: list[str] = ["C:\\a.png", "D:\\素材\\b.jpg"]
        FavoritesService(fav_file).save(expected)
        assert FavoritesService(fav_file).load() == expected

    def test_save_preserves_unicode_literal(self, fav_file: str) -> None:
        """中文路径以原文写入磁盘（ensure_ascii=False）。"""
        FavoritesService(fav_file).save(["D:\\素材\\图片.png"])
        raw: str = Path(fav_file).read_text(encoding="utf-8")
        assert "素材" in raw

    def test_load_missing_file_returns_empty(self, fav_file: str) -> None:
        """文件不存在返回空列表。"""
        assert FavoritesService(fav_file).load() == []

    def test_load_corrupted_json_returns_empty(self, fav_file: str) -> None:
        """损坏 JSON 静默回退空列表。"""
        Path(fav_file).write_text("{bad", encoding="utf-8")
        assert FavoritesService(fav_file).load() == []

    def test_load_wrong_root_type_returns_empty(self, fav_file: str) -> None:
        """根节点非 list 时静默回退空列表。"""
        Path(fav_file).write_text('{"list": []}', encoding="utf-8")
        assert FavoritesService(fav_file).load() == []

    def test_load_read_error_returns_empty(
        self, fav_file: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """读取 IO 异常静默回退空列表。"""
        Path(fav_file).write_text("[]", encoding="utf-8")

        def _raise_open(*args: object, **kwargs: object) -> object:
            raise OSError("denied")

        monkeypatch.setattr("builtins.open", _raise_open)
        assert FavoritesService(fav_file).load() == []

    def test_load_is_cached_after_first_call(self, fav_file: str) -> None:
        """首次 load 后内存缓存生效：外部磁盘改动不再可见。"""
        svc: FavoritesService = FavoritesService(fav_file)
        svc.save(["C:\\first.png"])
        assert svc.load() == ["C:\\first.png"]
        Path(fav_file).write_text(
            json.dumps(["C:\\changed.png"]), encoding="utf-8"
        )
        assert svc.load() == ["C:\\first.png"]

    def test_save_updates_memory_cache(self, fav_file: str) -> None:
        """save 直接更新内存缓存与加载标志。"""
        svc: FavoritesService = FavoritesService(fav_file)
        svc.save(["C:\\saved.png"])
        assert svc.contains("C:\\saved.png") is True
        # 磁盘内容与内存一致
        assert json.loads(Path(fav_file).read_text(encoding="utf-8")) == [
            "C:\\saved.png"
        ]