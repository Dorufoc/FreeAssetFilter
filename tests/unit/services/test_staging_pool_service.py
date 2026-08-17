# -*- coding: utf-8 -*-
"""``StagingPoolService``（freeassetfilter/services/staging_pool_service.py）单元测试。

覆盖（happy + boundary/error 各至少一条）：

* 生命周期 —— 单例同实例、initialize 创建大小计算线程池、dispose 清空并
  释放线程池
* 项目管理 —— 批量添加/移除/清空、路径规范化重复检测、缺失 path 拒绝、
  默认字段补齐、is_dir 标记、快照副本语义、has_path/get_item_by_path
* 磁盘空间 —— 不存在目录返回 (None, None)、真实目录返回 int 元组
* 文件夹大小 —— 递归求和、空目录为 0、非目录/不存在路径为 None、
  预先取消返回 None、异步计算 Happy/非目录/未初始化/重复提交复用 Future/
  取消任务
* 序列化 —— format_file_size 全变体、serialize_backup_item 归一化、
  build_file_info 文件/目录/显式参数/缺失路径

StagingPoolService 为单例且不在 conftest 的 ``reset_singletons`` 清单内，
本文件自带 autouse fixture 归零并在 teardown 释放旧实例线程池。
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from freeassetfilter.services.staging_pool_service import StagingPoolService

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_staging_pool_singleton() -> None:
    """在测试前后归零 StagingPoolService 单例并释放旧实例线程池。

    Returns:
        None。
    """
    previous: Optional[StagingPoolService] = StagingPoolService._instance
    StagingPoolService._instance = None
    yield
    if previous is not None:
        try:
            previous.dispose()
        except Exception:
            pass
    StagingPoolService._instance = None


def _item(path: str, name: Optional[str] = None, is_dir: bool = False, **extra: Any) -> Dict[str, Any]:
    """构造暂存池文件信息字典（测试辅助）。

    Args:
        path: 文件/目录路径。
        name: 显示名称，缺省取路径 basename。
        is_dir: 是否目录。
        extra: 额外字段。

    Returns:
        Dict[str, Any]: 文件信息字典。
    """
    data: Dict[str, Any] = {
        "path": path,
        "name": name or os.path.basename(path),
        "is_dir": is_dir,
    }
    data.update(extra)
    return data


def _build_tree(tmp_path: Path) -> Path:
    """构建嵌套目录树：总大小 200 字节。

    Args:
        tmp_path: pytest 内置的每测试临时目录。

    Returns:
        Path: 树根目录路径。
    """
    from tests.support.data_factories import make_text

    base: Path = tmp_path / "tree"
    sub: Path = base / "sub"
    sub.mkdir(parents=True)
    (sub / "empty").mkdir()
    make_text(base / "a.txt", content="x" * 120)
    make_text(sub / "b.txt", content="y" * 80)
    return base


# =============================================================================
# 生命周期
# =============================================================================
class TestLifecycle:
    """生命周期与单例"""

    def test_singleton_returns_same_instance(self) -> None:
        """重复构造必须返回同一实例。"""
        assert StagingPoolService() is StagingPoolService()

    def test_initialize_creates_size_executor(self) -> None:
        """initialize 后创建线程池且 is_initialized 置位。"""
        svc: StagingPoolService = StagingPoolService()
        assert svc.is_initialized is False
        svc.initialize()
        assert svc.is_initialized is True
        assert svc._size_calculator_executor is not None

    def test_dispose_clears_items_and_executor(self) -> None:
        """dispose 清空项目并释放线程池。"""
        svc: StagingPoolService = StagingPoolService()
        svc.initialize()
        svc.add_item(_item("C:\\a.txt"))
        svc.dispose()
        assert svc.is_initialized is False
        assert svc.get_items() == []
        assert svc._size_calculator_executor is None


# =============================================================================
# 项目管理
# =============================================================================
class TestItemManagement:
    """暂存池项目增删查"""

    def test_add_item_sets_default_display_fields(self) -> None:
        """添加成功后补齐 display_name/original_name 默认值。"""
        svc: StagingPoolService = StagingPoolService()
        assert svc.add_item({"path": "C:\\foo\\bar.jpg"}) is True
        item: Optional[Dict[str, Any]] = svc.get_item_by_path("C:\\foo\\bar.jpg")
        assert item is not None
        assert item["display_name"] == "bar.jpg"
        assert item["original_name"] == "bar.jpg"
        assert svc.get_items() == [item]

    def test_add_item_keeps_explicit_name(self) -> None:
        """显式 name 时不覆盖默认 display_name。"""
        svc: StagingPoolService = StagingPoolService()
        svc.add_item(_item("C:\\f.txt", name="自定义名"))
        item: Optional[Dict[str, Any]] = svc.get_item_by_path("C:\\f.txt")
        assert item is not None
        assert item["display_name"] == "自定义名"

    def test_add_item_missing_path_returns_false(self) -> None:
        """缺 path 键返回 False 且不进入池。"""
        svc: StagingPoolService = StagingPoolService()
        assert svc.add_item({"name": "x"}) is False
        assert svc.add_item({}) is False
        assert svc.get_items() == []

    def test_add_item_duplicate_normalized_path(self) -> None:
        """路径规范化后重复检测：斜杠/反斜杠写法视为同一路径。"""
        svc: StagingPoolService = StagingPoolService()
        assert svc.add_item(_item("C:\\foo\\bar.jpg")) is True
        assert svc.add_item(_item("C:/foo/bar.jpg")) is False
        assert len(svc.get_items()) == 1

    def test_add_item_dir_marks_size_calculating(self) -> None:
        """目录项目缺省标记 size_calculating=True。"""
        svc: StagingPoolService = StagingPoolService()
        svc.add_item(_item("C:\\folder", is_dir=True))
        item: Optional[Dict[str, Any]] = svc.get_item_by_path("C:\\folder")
        assert item is not None
        assert item["size_calculating"] is True

    def test_add_item_stores_copy_of_input(self) -> None:
        """存入的是输入字典的副本，后续外部修改不影响池内项目。"""
        svc: StagingPoolService = StagingPoolService()
        info: Dict[str, Any] = _item("C:\\a.txt", size=10)
        svc.add_item(info)
        info["size"] = 999
        item: Optional[Dict[str, Any]] = svc.get_item_by_path("C:\\a.txt")
        assert item is not None
        assert item["size"] == 10

    def test_remove_item_returns_removed_item(self) -> None:
        """移除返回被移除的项目字典。"""
        svc: StagingPoolService = StagingPoolService()
        svc.add_item(_item("C:\\a.txt"))
        removed: Optional[Dict[str, Any]] = svc.remove_item("C:\\a.txt")
        assert removed is not None
        assert removed["path"] == "C:\\a.txt"
        assert svc.get_items() == []

    def test_remove_item_normalized_match(self) -> None:
        """移除同样做路径规范化匹配。"""
        svc: StagingPoolService = StagingPoolService()
        svc.add_item(_item("C:\\foo\\a.txt"))
        assert svc.remove_item("C:/foo/a.txt") is not None

    def test_remove_missing_returns_none(self) -> None:
        """移除不存在的路径返回 None。"""
        svc: StagingPoolService = StagingPoolService()
        assert svc.remove_item("C:\\nope.txt") is None

    def test_get_items_returns_independent_copies(self) -> None:
        """get_items 快照独立，修改快照不影响内部项目。"""
        svc: StagingPoolService = StagingPoolService()
        svc.add_item(_item("C:\\a.txt"))
        snapshot: list[Dict[str, Any]] = svc.get_items()
        snapshot[0]["name"] = "mutated"
        item: Optional[Dict[str, Any]] = svc.get_item_by_path("C:\\a.txt")
        assert item is not None
        assert item["name"] == "a.txt"

    def test_clear_empties_pool(self) -> None:
        """clear 一次清空全部项目。"""
        svc: StagingPoolService = StagingPoolService()
        svc.add_item(_item("C:\\a.txt"))
        svc.add_item(_item("C:\\b.txt"))
        svc.clear()
        assert svc.get_items() == []

    def test_has_path(self) -> None:
        """has_path 反映路径是否在池中。"""
        svc: StagingPoolService = StagingPoolService()
        assert svc.has_path("C:\\a.txt") is False
        svc.add_item(_item("C:\\a.txt"))
        assert svc.has_path("C:\\a.txt") is True

    def test_get_item_by_path_missing_returns_none(self) -> None:
        """get_item_by_path 未命中返回 None。"""
        assert StagingPoolService().get_item_by_path("C:\\missing.txt") is None


# =============================================================================
# 磁盘空间
# =============================================================================
class TestDiskSpace:
    """目录所在磁盘容量查询"""

    def test_missing_directory_returns_none_none(self, tmp_path: Path) -> None:
        """不存在的目录返回 (None, None)。"""
        svc: StagingPoolService = StagingPoolService()
        assert (
            svc.get_directory_space(str(tmp_path / "ghost_directory")) == (None, None)
        )

    def test_existing_directory_returns_int_tuple(self, tmp_path: Path) -> None:
        """真实目录返回 (总容量, 可用空间) 非负 int 元组。"""
        svc: StagingPoolService = StagingPoolService()
        total: Any
        free: Any
        total, free = svc.get_directory_space(str(tmp_path))
        assert isinstance(total, int)
        assert isinstance(free, int)
        assert total >= 0
        assert free >= 0


# =============================================================================
# 文件夹大小
# =============================================================================
class TestFolderSize:
    """递归大小计算"""

    def test_calculate_folder_size_recursive(self, tmp_path: Path) -> None:
        """嵌套目录递归求和。"""
        base: Path = _build_tree(tmp_path)
        size: Optional[int] = StagingPoolService().calculate_folder_size(str(base))
        assert size == 200

    def test_calculate_folder_size_empty_dir(self, tmp_path: Path) -> None:
        """空目录返回 0。"""
        empty: Path = tmp_path / "empty"
        empty.mkdir()
        assert StagingPoolService().calculate_folder_size(str(empty)) == 0

    def test_calculate_folder_size_not_dir_returns_none(self, tmp_path: Path) -> None:
        """传文件路径返回 None。"""
        f: Path = tmp_path / "file.txt"
        f.write_text("x", encoding="utf-8")
        assert StagingPoolService().calculate_folder_size(str(f)) is None

    def test_calculate_folder_size_missing_path_returns_none(
        self, tmp_path: Path
    ) -> None:
        """不存在的路径返回 None。"""
        assert (
            StagingPoolService().calculate_folder_size(
                str(tmp_path / "missing")
            )
            is None
        )

    def test_calculate_folder_size_precancelled_returns_none(
        self, tmp_path: Path
    ) -> None:
        """预先置位的取消事件使计算返回 None。"""
        base: Path = _build_tree(tmp_path)
        cancel: threading.Event = threading.Event()
        cancel.set()
        assert (
            StagingPoolService().calculate_folder_size(str(base), cancel) is None
        )

    def test_async_happy_path(self, tmp_path: Path) -> None:
        """异步计算返回带结果的 Future。"""
        base: Path = _build_tree(tmp_path)
        svc: StagingPoolService = StagingPoolService()
        svc.initialize()
        future: Optional[Future] = svc.calculate_folder_size_async(str(base))
        assert future is not None
        assert future.result(timeout=10) == 200

    def test_async_not_dir_returns_none(self, tmp_path: Path) -> None:
        """非目录路径异步提交返回 None。"""
        f: Path = tmp_path / "f.txt"
        f.write_text("x", encoding="utf-8")
        svc: StagingPoolService = StagingPoolService()
        svc.initialize()
        assert svc.calculate_folder_size_async(str(f)) is None

    def test_async_without_initialize_returns_none(self, tmp_path: Path) -> None:
        """未 initialize（无线程池）时返回 None。"""
        base: Path = _build_tree(tmp_path)
        svc: StagingPoolService = StagingPoolService()
        assert svc.calculate_folder_size_async(str(base)) is None

    def test_async_duplicate_submit_reuses_running_future(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """相同路径的未完成任务只提交一次，重复提交复用同一 Future。"""
        base: Path = _build_tree(tmp_path)
        svc: StagingPoolService = StagingPoolService()
        svc.initialize()
        started: threading.Event = threading.Event()
        release: threading.Event = threading.Event()

        def _slow_worker(folder: str, cancel_event: threading.Event) -> Optional[int]:
            started.set()
            release.wait(10)
            return 200

        monkeypatch.setattr(svc, "_calculate_folder_size_worker", _slow_worker)
        try:
            first: Optional[Future] = svc.calculate_folder_size_async(str(base))
            assert first is not None
            assert started.wait(5)
            second: Optional[Future] = svc.calculate_folder_size_async(str(base))
            assert second is not None
            assert second is first
        finally:
            release.set()

    def test_cancel_folder_size_calculation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """取消任务后 Future 解析为 None。"""
        base: Path = _build_tree(tmp_path)
        svc: StagingPoolService = StagingPoolService()
        svc.initialize()

        def _blocking_worker(
            folder: str, cancel_event: threading.Event
        ) -> Optional[int]:
            while not cancel_event.is_set():
                time.sleep(0.01)
            return None

        monkeypatch.setattr(svc, "_calculate_folder_size_worker", _blocking_worker)
        future: Optional[Future] = svc.calculate_folder_size_async(str(base))
        assert future is not None
        svc.cancel_folder_size_calculation(str(base))
        assert future.result(timeout=10) is None


# =============================================================================
# 文件大小格式化
# =============================================================================
class TestFormatFileSize:
    """字节数格式化"""

    def test_zero_bytes(self) -> None:
        assert StagingPoolService.format_file_size(0) == "0 B"

    def test_small_bytes(self) -> None:
        assert StagingPoolService.format_file_size(512) == "512 B"

    def test_kilobytes(self) -> None:
        assert StagingPoolService.format_file_size(1536) == "1.50 KB"

    def test_megabytes(self) -> None:
        assert StagingPoolService.format_file_size(2 * 1024 * 1024) == "2.00 MB"

    def test_float_input(self) -> None:
        assert StagingPoolService.format_file_size(1024.0) == "1.00 KB"

    def test_none_returns_empty(self) -> None:
        assert StagingPoolService.format_file_size(None) == ""

    def test_invalid_input_returns_empty(self) -> None:
        assert StagingPoolService.format_file_size("abc") == ""

    def test_negative_clamped_to_zero(self) -> None:
        assert StagingPoolService.format_file_size(-10) == "0 B"


# =============================================================================
# 序列化
# =============================================================================
class TestSerializeBackupItem:
    """备份序列化"""

    def test_happy_path_normalizes(self) -> None:
        """合法输入归一化：path 规范化、未知 string/bool 字段补默认值。"""
        out: Optional[Dict[str, Any]] = StagingPoolService.serialize_backup_item(
            {
                "path": "C:\\foo\\bar.txt",
                "name": "bar.txt",
                "size": 123,
                "is_dir": False,
                "size_calculating": False,
            }
        )
        assert out is not None
        assert out["path"] == os.path.normpath("C:\\foo\\bar.txt")
        assert out["size"] == 123
        assert out["name"] == "bar.txt"
        assert out["is_dir"] is False
        assert out["size_calculating"] is False
        assert out["modified"] == ""

    def test_size_none_preserved(self) -> None:
        """size 为 None 时保留为 None。"""
        out: Optional[Dict[str, Any]] = StagingPoolService.serialize_backup_item(
            {"path": "C:\\d", "size": None}
        )
        assert out is not None
        assert out["size"] is None

    def test_size_bool_coerced_to_none(self) -> None:
        """size 为 bool 时不视为数字，降级为 None。"""
        out: Optional[Dict[str, Any]] = StagingPoolService.serialize_backup_item(
            {"path": "C:\\d", "size": True}
        )
        assert out is not None
        assert out["size"] is None

    def test_string_and_bool_fields_coerced(self) -> None:
        """string 字段转 str、bool 字段走 truthiness。"""
        out: Optional[Dict[str, Any]] = StagingPoolService.serialize_backup_item(
            {
                "path": "C:\\a.txt",
                "info_text": None,
                "suffix": 42,
                "is_selected": "yes",
            }
        )
        assert out is not None
        assert out["info_text"] == ""
        assert out["suffix"] == "42"
        assert out["is_selected"] is True

    def test_non_dict_returns_none(self) -> None:
        assert StagingPoolService.serialize_backup_item("nope") is None

    def test_missing_path_returns_none(self) -> None:
        assert StagingPoolService.serialize_backup_item({"name": "x"}) is None

    def test_blank_path_normalizes_to_dot(self) -> None:
        """记录现状：纯空白路径 normpath(\"\") 后为 \".\"，被接受而非拒绝。

        ``normpath`` 对空串返回 ``\".\"``（Windows 与 POSIX 一致），因此
        代码里的 ``if not path`` 空路径守卫实际上是死代码——空白路径会以
        ``\".\"`` 形式通过序列化。
        """
        out: Optional[Dict[str, Any]] = StagingPoolService.serialize_backup_item(
            {"path": "   "}
        )
        assert out is not None
        assert out["path"] == "."


class TestBuildFileInfo:
    """文件信息构建"""

    def test_happy_file(self, tmp_path: Path) -> None:
        """真实文件构建完整信息字典。"""
        f: Path = tmp_path / "photo.PNG"
        f.write_bytes(b"xx")
        info: Optional[Dict[str, Any]] = StagingPoolService.build_file_info(str(f))
        assert info is not None
        assert info["name"] == "photo.PNG"
        assert info["path"] == str(f)
        assert info["is_dir"] is False
        assert info["suffix"] == "png"
        assert info["size"] == 2
        assert info["size_calculating"] is False
        assert info["display_name"] == "photo.PNG"

    def test_happy_directory(self, tmp_path: Path) -> None:
        """目录信息：size 为 None、size_calculating 为 True、无后缀。"""
        d: Path = tmp_path / "folder"
        d.mkdir()
        info: Optional[Dict[str, Any]] = StagingPoolService.build_file_info(str(d))
        assert info is not None
        assert info["is_dir"] is True
        assert info["size"] is None
        assert info["size_calculating"] is True
        assert info["suffix"] == ""

    def test_missing_path_returns_none(self, tmp_path: Path) -> None:
        """不存在的路径返回 None。"""
        assert (
            StagingPoolService.build_file_info(str(tmp_path / "missing")) is None
        )

    def test_explicit_stat_and_is_dir(self, tmp_path: Path) -> None:
        """显式传入 stat_result 与 is_dir 时避免重复系统调用。"""
        f: Path = tmp_path / "a.txt"
        f.write_text("hello", encoding="utf-8")
        stat: os.stat_result = os.stat(str(f))
        info: Optional[Dict[str, Any]] = StagingPoolService.build_file_info(
            str(f), stat_result=stat, is_dir=False
        )
        assert info is not None
        assert info["size"] == 5
        assert info["is_dir"] is False