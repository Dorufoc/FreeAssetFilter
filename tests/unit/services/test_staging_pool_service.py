#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StagingPoolService 单元测试
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
from typing import Any, Dict, List

import pytest

from freeassetfilter.services.staging_pool_service import StagingPoolService

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def service() -> StagingPoolService:
    """提供已初始化的 StagingPoolService 实例。"""
    svc = StagingPoolService()
    svc.initialize()
    yield svc
    svc.dispose()


@pytest.fixture
def sample_file(tmp_path) -> str:
    """创建一个示例文件并返回路径。"""
    file_path = os.path.join(str(tmp_path), "test.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("hello world")
    return file_path


@pytest.fixture
def sample_dir(tmp_path) -> str:
    """创建一个包含文件的示例目录并返回路径。"""
    sub_dir = os.path.join(str(tmp_path), "subdir")
    os.makedirs(sub_dir, exist_ok=True)
    for i in range(3):
        fp = os.path.join(sub_dir, f"file_{i}.txt")
        with open(fp, "w", encoding="utf-8") as f:
            f.write("x" * (i + 1) * 100)
    return sub_dir


def _make_item(path: str, **overrides: Any) -> Dict[str, Any]:
    """构造一个标准文件信息字典。"""
    item = {
        "path": path,
        "name": os.path.basename(path),
        "is_dir": os.path.isdir(path),
        "size": None if os.path.isdir(path) else os.path.getsize(path),
        "size_calculating": False,
        "modified": "2025-01-01 00:00:00",
        "created": "2025-01-01 00:00:00",
        "suffix": os.path.splitext(path)[1].lstrip(".") if not os.path.isdir(path) else "",
        "display_name": os.path.basename(path),
        "original_name": os.path.basename(path),
    }
    item.update(overrides)
    return item


# ── Lifecycle ────────────────────────────────────────────────────────────


class TestLifecycle:
    """BaseService 生命周期测试。"""

    def test_initialize_and_dispose(self) -> None:
        """Given 新服务实例, When 初始化, Then 状态正确."""
        svc = StagingPoolService()
        assert svc.initialize() is True
        assert svc.is_initialized is True

        svc.dispose()
        assert svc.is_initialized is False

    def test_initialize_idempotent(self) -> None:
        """Given 已初始化的服务, When 再次初始化, Then 返回 True."""
        svc = StagingPoolService()
        svc.initialize()
        assert svc.initialize() is True

    def test_dispose_idempotent(self) -> None:
        """Given 已销毁的服务, When 再次销毁, Then 不报错."""
        svc = StagingPoolService()
        svc.initialize()
        svc.dispose()
        svc.dispose()  # should not raise


# ── Item management ─────────────────────────────────────────────────────


class TestAddItem:
    """add_item 方法测试。"""

    def test_add_single_file(self, service: StagingPoolService, sample_file: str) -> None:
        """Given 有效文件路径, When 添加到暂存池, Then 返回 True 且项目存在."""
        item = _make_item(sample_file)
        assert service.add_item(item) is True
        items = service.get_items()
        assert len(items) == 1
        assert items[0]["name"] == "test.txt"

    def test_add_duplicate_path(self, service: StagingPoolService, sample_file: str) -> None:
        """Given 重复路径, When 再次添加, Then 返回 False 且项目不重复."""
        item = _make_item(sample_file)
        assert service.add_item(item) is True
        assert service.add_item(item) is False
        assert len(service.get_items()) == 1

    def test_add_without_path(self, service: StagingPoolService) -> None:
        """Given 无 path 的字典, When 添加, Then 返回 False."""
        assert service.add_item({"name": "no_path.txt"}) is False
        assert len(service.get_items()) == 0

    def test_add_directory(self, service: StagingPoolService, sample_dir: str) -> None:
        """Given 目录路径, When 添加, Then 标记 size_calculating=True."""
        item = _make_item(sample_dir)
        assert service.add_item(item) is True
        items = service.get_items()
        assert len(items) == 1
        assert items[0]["is_dir"] is True

    def test_add_sets_defaults(self, service: StagingPoolService, sample_file: str) -> None:
        """Given 缺少 display_name 的 item, When 添加, Then 自动填充默认值."""
        item = {"path": sample_file}
        assert service.add_item(item) is True
        items = service.get_items()
        assert items[0]["display_name"] == "test.txt"
        assert items[0]["original_name"] == "test.txt"


class TestRemoveItem:
    """remove_item 方法测试。"""

    def test_remove_existing(self, service: StagingPoolService, sample_file: str) -> None:
        """Given 暂存池中有项目, When 按路径移除, Then 返回被移除的项目."""
        item = _make_item(sample_file)
        service.add_item(item)

        removed = service.remove_item(sample_file)
        assert removed is not None
        assert removed["path"] == sample_file
        assert service.get_items() == []

    def test_remove_nonexistent(self, service: StagingPoolService) -> None:
        """Given 不存在的路径, When 移除, Then 返回 None."""
        assert service.remove_item("/nonexistent/path.txt") is None
        assert service.get_items() == []

    def test_remove_normalizes_path(self, service: StagingPoolService, sample_file: str) -> None:
        """Given 路径大小写/分隔符不同, When 移除, Then 仍能匹配."""
        item = _make_item(sample_file)
        service.add_item(item)

        # 使用不同风格路径
        alt_path = sample_file.replace("\\", "/")
        removed = service.remove_item(alt_path)
        assert removed is not None


class TestGetItems:
    """get_items 方法测试。"""

    def test_get_items_returns_copy(self, service: StagingPoolService, sample_file: str) -> None:
        """Given 暂存池有项目, When 获取列表, Then 返回的是独立副本."""
        item = _make_item(sample_file)
        service.add_item(item)

        items = service.get_items()
        items.clear()
        assert len(service.get_items()) == 1  # 原列表不受影响

    def test_get_items_empty_when_no_items(self, service: StagingPoolService) -> None:
        """Given 空暂存池, When 获取列表, Then 返回空列表."""
        assert service.get_items() == []


class TestClear:
    """clear 方法测试。"""

    def test_clear_removes_all(self, service: StagingPoolService, tmp_path) -> None:
        """Given 暂存池有多个项目, When 清空, Then 列表为空."""
        for i in range(5):
            fp = os.path.join(str(tmp_path), f"file_{i}.txt")
            # 先创建真实文件，否则 _make_item 中 os.path.getsize 会报错
            with open(fp, "w") as f:
                f.write("test")
            service.add_item(_make_item(fp))
        assert len(service.get_items()) == 5

        service.clear()
        assert service.get_items() == []

    def test_clear_empty_pool(self, service: StagingPoolService) -> None:
        """Given 空暂存池, When 清空, Then 不报错."""
        service.clear()  # should not raise


class TestGetItemByPath:
    """get_item_by_path 方法测试。"""

    def test_find_existing(self, service: StagingPoolService, sample_file: str) -> None:
        """Given 已添加的文件, When 按路径查找, Then 返回正确项目."""
        item = _make_item(sample_file)
        service.add_item(item)
        found = service.get_item_by_path(sample_file)
        assert found is not None
        assert found["name"] == "test.txt"

    def test_find_nonexistent(self, service: StagingPoolService) -> None:
        """Given 未添加的路径, When 查找, Then 返回 None."""
        assert service.get_item_by_path("/nonexistent.txt") is None


class TestHasPath:
    """has_path 方法测试。"""

    def test_has_existing_path(self, service: StagingPoolService, sample_file: str) -> None:
        """Given 已添加的文件, When 检查路径, Then 返回 True."""
        item = _make_item(sample_file)
        service.add_item(item)
        assert service.has_path(sample_file) is True

    def test_has_nonexistent_path(self, service: StagingPoolService) -> None:
        """Given 未添加的路径, When 检查, Then 返回 False."""
        assert service.has_path("/nonexistent.txt") is False

    def test_has_after_removal(self, service: StagingPoolService, sample_file: str) -> None:
        """Given 已移除的项目, When 检查路径, Then 返回 False."""
        item = _make_item(sample_file)
        service.add_item(item)
        service.remove_item(sample_file)
        assert service.has_path(sample_file) is False


# ── Disk space ──────────────────────────────────────────────────────────


class TestGetDirectorySpace:
    """get_directory_space 方法测试。"""

    def test_returns_non_none_for_existing_dir(self, service: StagingPoolService) -> None:
        """Given 存在的目录, When 查询磁盘空间, Then 返回 (total, free) 整数对."""
        total, free = service.get_directory_space(os.getcwd())
        assert total is not None
        assert free is not None
        assert isinstance(total, int)
        assert isinstance(free, int)
        assert total > 0
        assert free > 0

    def test_returns_none_for_nonexistent_dir(self, service: StagingPoolService) -> None:
        """Given 不存在的目录, When 查询磁盘空间, Then 返回 (None, None)."""
        total, free = service.get_directory_space("Z:\\nonexistent_path_xyz")
        assert total is None
        assert free is None


# ── Folder size ─────────────────────────────────────────────────────────


class TestCalculateFolderSize:
    """calculate_folder_size 方法测试。"""

    def test_empty_dir(self, service: StagingPoolService, tmp_path) -> None:
        """Given 空目录, When 计算大小, Then 返回 0."""
        empty_dir = os.path.join(str(tmp_path), "empty")
        os.makedirs(empty_dir, exist_ok=True)
        size = service.calculate_folder_size(empty_dir)
        assert size == 0

    def test_dir_with_files(self, service: StagingPoolService, sample_dir: str) -> None:
        """Given 包含文件的目录, When 计算大小, Then 返回累加大小."""
        size = service.calculate_folder_size(sample_dir)
        # files: file_0.txt (100B), file_1.txt (200B), file_2.txt (300B)
        assert size == 600  # (1 + 2 + 3) * 100

    def test_cancelled_returns_none(self, service: StagingPoolService, tmp_path) -> None:
        """Given 取消事件已设置, When 计算大小, Then 返回 None."""
        cancel = threading.Event()
        cancel.set()
        result = service.calculate_folder_size(str(tmp_path), cancel_event=cancel)
        assert result is None

    def test_nonexistent_dir(self, service: StagingPoolService) -> None:
        """Given 不存在的目录, When 计算大小, Then 返回 None."""
        size = service.calculate_folder_size("Z:\\nonexistent_path_xyz")
        assert size is None


class TestCalculateFolderSizeAsync:
    """calculate_folder_size_async 方法测试。"""

    def test_async_returns_future(self, service: StagingPoolService, sample_dir: str) -> None:
        """Given 存在的目录, When 异步计算, Then 返回 Future 并得到正确结果."""
        future = service.calculate_folder_size_async(sample_dir)
        assert future is not None
        result = future.result(timeout=10)
        assert result == 600

    def test_async_returns_none_for_file(self, service: StagingPoolService, sample_file: str) -> None:
        """Given 文件而非目录, When 异步计算, Then 返回 None."""
        result = service.calculate_folder_size_async(sample_file)
        assert result is None

    def test_async_callback_called(self, service: StagingPoolService, sample_dir: str) -> None:
        """Given 注册了 callback, When 异步计算完成, Then callback 被调用. """
        received: List[Any] = []

        def cb(result):
            received.append(result)

        future = service.calculate_folder_size_async(sample_dir, callback=cb)
        assert future is not None
        future.result(timeout=10)

        # Callback is invoked from done callback; wait a tick
        import time
        time.sleep(0.1)
        assert len(received) == 1
        assert received[0] == 600

    def test_cancel_async(self, service: StagingPoolService, tmp_path) -> None:
        """Given 提交后立即取消, When 取消任务, Then 不报错."""
        sub_dir = os.path.join(str(tmp_path), "cancel_test")
        os.makedirs(sub_dir, exist_ok=True)

        future = service.calculate_folder_size_async(sub_dir)
        assert future is not None
        service.cancel_folder_size_calculation(sub_dir)
        # 取消后不报错即可


class TestCancelFolderSize:
    """cancel_folder_size_calculation 方法测试。"""

    def test_cancel_nonexistent(self, service: StagingPoolService) -> None:
        """Given 不存在的任务, When 取消, Then 不报错."""
        service.cancel_folder_size_calculation("/nonexistent")  # should not raise


# ── Serialization ───────────────────────────────────────────────────────


class TestSerializeBackupItem:
    """serialize_backup_item 方法测试。"""

    def test_serialize_valid_item(self) -> None:
        """Given 有效文件信息, When 序列化, Then 返回可 JSON 序列化的字典."""
        item = {
            "path": "C:\\test\\file.txt",
            "name": "file.txt",
            "size": 1024,
            "is_dir": False,
            "is_selected": True,
            "is_missing": False,
            "size_calculating": False,
            "modified": "2025-01-01",
            "created": "2025-01-01",
            "suffix": "txt",
            "display_name": "file.txt",
            "original_name": "file.txt",
        }
        result = StagingPoolService.serialize_backup_item(item)
        assert result is not None
        assert result["path"] == "C:\\test\\file.txt"
        assert result["size"] == 1024
        assert result["is_dir"] is False
        assert result["is_selected"] is True

    def test_serialize_invalid_type(self) -> None:
        """Given 非字典输入, When 序列化, Then 返回 None."""
        assert StagingPoolService.serialize_backup_item(None) is None
        assert StagingPoolService.serialize_backup_item("not_a_dict") is None

    def test_serialize_missing_path(self) -> None:
        """Given 不含 path 的字典, When 序列化, Then 返回 None."""
        assert StagingPoolService.serialize_backup_item({"foo": "bar"}) is None


# ── build_file_info ─────────────────────────────────────────────────────


class TestBuildFileInfo:
    """build_file_info 方法测试。"""

    def test_build_file_info(self, sample_file: str) -> None:
        """Given 文件路径, When 构建信息, Then 返回完整信息字典."""
        info = StagingPoolService.build_file_info(sample_file)
        assert info is not None
        assert info["name"] == "test.txt"
        assert info["path"] == sample_file
        assert info["is_dir"] is False
        assert info["size"] is not None

    def test_build_file_info_nonexistent(self) -> None:
        """Given 不存在的路径, When 构建信息, Then 返回 None."""
        info = StagingPoolService.build_file_info("Z:\\nonexistent.txt")
        assert info is None


# ── Thread safety ───────────────────────────────────────────────────────


class TestThreadSafety:
    """多线程并发操作测试。"""

    def test_concurrent_add(self, service: StagingPoolService, tmp_path) -> None:
        """Given 多线程, When 并发添加, Then 数据一致."""
        paths = []
        for i in range(20):
            fp = os.path.join(str(tmp_path), f"concurrent_{i}.txt")
            with open(fp, "w") as f:
                f.write(str(i))
            paths.append(fp)

        errors: List[Exception] = []

        def add_path(p: str) -> None:
            try:
                service.add_item(_make_item(p))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_path, args=(p,)) for p in paths]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发添加时发生异常: {errors}"
        assert len(service.get_items()) == 20

    def test_concurrent_remove(self, service: StagingPoolService, tmp_path) -> None:
        """Given 多线程, When 并发移除, Then 数据一致."""
        paths = []
        for i in range(10):
            fp = os.path.join(str(tmp_path), f"rem_{i}.txt")
            with open(fp, "w") as f:
                f.write(str(i))
            paths.append(fp)
            service.add_item(_make_item(fp))

        errors: List[Exception] = []

        def remove_path(p: str) -> None:
            try:
                service.remove_item(p)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=remove_path, args=(p,)) for p in paths]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发移除时发生异常: {errors}"
        assert len(service.get_items()) == 0
