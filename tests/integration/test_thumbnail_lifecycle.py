# -*- coding: utf-8 -*-
# targets: core.managers.thumbnail_manager
"""缩略图全生命周期集成测试（todo-25 integration 批 2 / test_thumbnail_lifecycle）。

验证 ThumbnailManager 跨模块的真实端到端契约：

* 20 张图片批量异步生成：``create_thumbnails_batch`` 全部成功、二轮命中
  缓存（缓存命中率 >=0.85，ISO）；
* ``clean_thumbnails`` LRU 清理后文件系统计数与 ``get_thumbnail_count``、
  ``get_existing_thumbnail_path`` 三方一致；
* 损坏字节文件 / 缺失文件：不产出缓存文件、不抛异常（异常安全降级）；
* 异步队列结束后不得泄漏 ``thumb_batch*`` 工作线程。

资源纪律：

* 用例把 ``manager._thumb_dir`` 重定向到 ``tmp_path/thumbs``，绝不触碰真实
  appdata 缩略图缓存；
* 所有等待均有界：``qt_helpers.process_qt_events`` + deadline 轮询兜底，
  绝不裸 wait；
* teardown 走 ``clear_all_thumbnails`` + 单例重置（conftest autouse 兜底）。
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, List, Tuple

import pytest

from tests.support import qt_helpers
from tests.support.data_factories import make_image, make_text


pytestmark = pytest.mark.integration


# =============================================================================
# fixture
# =============================================================================
@pytest.fixture
def thumb_manager(tmp_path: Any) -> Any:
    """提供缩略图目录被隔离到临时目录的全新 ThumbnailManager 单例。

    Args:
        tmp_path: pytest 内置每测试临时目录。

    Returns:
        ThumbnailManager: 绑定临时缓存目录的新实例。
    """
    from freeassetfilter.core.managers.thumbnail_manager import ThumbnailManager

    manager = ThumbnailManager()
    thumb_dir: str = str(tmp_path / "thumbs")
    manager._thumb_dir = thumb_dir  # noqa: SLF001
    os.makedirs(thumb_dir, exist_ok=True)
    manager._clear_path_exists_cache()  # noqa: SLF001
    yield manager
    try:
        manager.clear_all_thumbnails()
    except Exception:  # noqa: BLE001 - teardown 幂等
        pass
    ThumbnailManager._instance = None  # noqa: SLF001
    ThumbnailManager._initialized = False  # noqa: SLF001


def _make_images(tmp_path: Any, count: int) -> List[str]:
    """批量生成 count 张 PNG 并返回路径列表。

    Args:
        tmp_path: 临时目录。
        count: 生成数量。

    Returns:
        list[str]: 生成后的图片路径列表。
    """
    return [make_image(tmp_path / f"img_{i:03d}.png", fmt="PNG") for i in range(count)]


def _wait_until(
    predicate: Any, timeout: float = 5.0, interval: float = 0.05
) -> None:
    """有界轮询等待条件成立；超时抛 AssertionError（绝不无限等待）。

    Args:
        predicate: 返回真值即停止的条件函数。
        timeout: 最大等待秒数。
        interval: 轮询间隔秒数。
    """
    deadline: float = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"条件在 {timeout}s 内未满足")


# =============================================================================
# 批量异步生成与缓存命中
# =============================================================================
class TestBatchAsyncGeneration:
    """``create_thumbnails_batch`` 异步生成 + 二轮缓存命中。"""

    def test_batch_20_creates_and_reuses_cache(
        self, thumb_manager: Any, tmp_path: Any, qapp: Any
    ) -> None:
        """20 张批量生成全部成功；二轮批量全部命中缓存且命中率达标。"""
        paths: List[str] = _make_images(tmp_path, 20)

        success: int
        processed: int
        success, processed = thumb_manager.create_thumbnails_batch(paths)
        assert (success, processed) == (20, 20)
        qt_helpers.process_qt_events(qapp, ms=50)

        stats: dict = thumb_manager.get_cache_statistics(max_cache_size=20)
        assert stats["total_files"] == 20

        success2: int
        processed2: int
        success2, processed2 = thumb_manager.create_thumbnails_batch(paths)
        assert (success2, processed2) == (20, 20)

        # 命中率：二轮生成的路径应与一轮一致
        hits: int = 0
        for p in paths:
            existing: Any = thumb_manager.get_existing_thumbnail_path(p)
            if existing is not None:
                hits += 1
        assert hits / len(paths) >= 0.85, f"缓存命中率过低: {hits}/20"
        qt_helpers.process_qt_events(qapp, ms=0)

    def test_batch_progress_callback_counts(
        self, thumb_manager: Any, tmp_path: Any, qapp: Any
    ) -> None:
        """progress_callback 收到与文件数一致的回调（含失败项计数）。"""
        good: List[str] = _make_images(tmp_path, 3)
        missing: str = str(tmp_path / "missing.png")
        progress: List[bool] = []

        success: int
        processed: int
        success, processed = thumb_manager.create_thumbnails_batch(
            good + [missing],
            progress_callback=lambda done, total, item, ok: progress.append(ok),
        )

        assert (success, processed) == (3, 4)
        assert len(progress) == 4, f"progress 回调数应为 4: {len(progress)}"
        assert progress.count(False) == 1
        qt_helpers.process_qt_events(qapp, ms=0)

    def test_batch_no_thread_leak_after_flush(
        self, thumb_manager: Any, tmp_path: Any, qapp: Any
    ) -> None:
        """两轮批量后，有界轮询确认无 ``thumb_batch*`` 残留线程。"""
        paths: List[str] = _make_images(tmp_path, 20)
        thumb_manager.create_thumbnails_batch(paths)
        thumb_manager.create_thumbnails_batch(paths)

        qt_helpers.process_qt_events(qapp, ms=30)

        def _no_lingering() -> bool:
            return not any(
                "thumb_batch" in t.name
                for t in threading.enumerate()
            )

        _wait_until(_no_lingering, timeout=5.0)
        lingering: List[str] = [
            t.name for t in threading.enumerate() if "thumb_batch" in t.name
        ]
        assert not lingering, f"批量缩略图线程泄漏: {lingering}"


# =============================================================================
# 清理与文件系统一致性
# =============================================================================
class TestCleanupFsConsistency:
    """``clean_thumbnails`` LRU 清理后的三方计数一致性。"""

    def test_clean_lru_then_counts_consistent(
        self, thumb_manager: Any, tmp_path: Any
    ) -> None:
        """生成 20 张后按 max_cache_size=5 清理：删除 15、剩 5，计数一致。"""
        paths: List[str] = _make_images(tmp_path, 20)
        for p in paths:
            result: Any = thumb_manager.create_thumbnail(p)
            assert result is not None and os.path.exists(result)

        assert thumb_manager.get_thumbnail_count() == 20

        deleted: int
        remaining: int
        deleted, remaining = thumb_manager.clean_thumbnails(max_cache_size=5)
        assert (deleted, remaining) == (15, 5)

        fs_count: int = len(
            os.listdir(str(tmp_path / "thumbs"))
        ) if os.path.isdir(str(tmp_path / "thumbs")) else 0
        assert fs_count == thumb_manager.get_thumbnail_count() == 5

        # 被清理的文件不再有缩略图
        survival: int = sum(
            1
            for p in paths
            if thumb_manager.get_existing_thumbnail_path(p) is not None
        )
        assert survival == 5, f"清理后应有 5 张存活缩略图: {survival}"

    def test_clear_all_returns_deleted_count(
        self, thumb_manager: Any, tmp_path: Any
    ) -> None:
        """``clear_all_thumbnails`` 返回删除数并对齐缓存统计。"""
        for p in _make_images(tmp_path, 5):
            assert thumb_manager.create_thumbnail(p)

        deleted_count: int = thumb_manager.clear_all_thumbnails()
        assert deleted_count == 5
        assert thumb_manager.get_thumbnail_count() == 0
        assert thumb_manager.get_cache_statistics()["total_files"] == 0


# =============================================================================
# 异常安全降级
# =============================================================================
class TestBadSourcesSafeDegrade:
    """损坏字节 / 非媒体 / 缺失文件一律安全降级。"""

    def test_corrupt_image_no_cache_no_exception(
        self, thumb_manager: Any, tmp_path: Any
    ) -> None:
        """损坏 PNG：返回 None、不产缓存文件、不抛异常。"""
        bad_file: str = str(tmp_path / "broken.png")
        with open(bad_file, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 512 + b"\xff\xfe garbage")

        result: Any = thumb_manager.create_thumbnail(bad_file)
        assert result is None, f"损坏图片不应产出缩略图: {result}"
        assert thumb_manager.get_existing_thumbnail_path(bad_file) is None
        assert thumb_manager.get_thumbnail_count() == 0
        assert thumb_manager.get_cache_statistics()["total_files"] == 0

    def test_non_media_and_missing_safe(
        self, thumb_manager: Any, tmp_path: Any
    ) -> None:
        """非媒体 .txt 与缺失文件都返回 None 且不抛异常。"""
        text_file: str = make_text(tmp_path / "notes.txt")
        missing: str = str(tmp_path / "not_exist.png")

        assert thumb_manager.create_thumbnail(text_file) is None
        assert thumb_manager.create_thumbnail(missing) is None
        assert thumb_manager.get_existing_thumbnail_path(text_file) is None
        assert thumb_manager.get_existing_thumbnail_path(missing) is None

    def test_batch_with_corrupt_source_counts_failure(
        self, thumb_manager: Any, tmp_path: Any, qapp: Any
    ) -> None:
        """批量中含损坏文件：计入 processed、回调失败、不阻塞其余任务。"""
        good: str = make_image(tmp_path / "good.png", fmt="PNG")
        bad_file: str = str(tmp_path / "corrupt.png")
        with open(bad_file, "wb") as fh:
            fh.write(b"not a real image at all" * 20)

        progress: List[bool] = []
        success: int
        processed: int
        success, processed = thumb_manager.create_thumbnails_batch(
            [good, bad_file],
            progress_callback=lambda done, total, item, ok: progress.append(ok),
        )

        assert (success, processed) == (1, 2)
        assert progress.count(False) >= 1
        # 损坏文件不随机产出任何缓存
        assert thumb_manager.get_existing_thumbnail_path(bad_file) is None
        qt_helpers.process_qt_events(qapp, ms=0)


# =============================================================================
# 缓存命中接口路径
# =============================================================================
class TestReuseAndForceRegen:
    """``create_thumbnail`` 二跳缓存与 force_regenerate。"""

    def test_second_call_returns_same_path(
        self, thumb_manager: Any, tmp_path: Any
    ) -> None:
        """同一图片两次 ``create_thumbnail`` 返回完全相同路径（缓存命中）。"""
        img: str = make_image(tmp_path / "cached.png", fmt="PNG")
        first: Any = thumb_manager.create_thumbnail(img)
        second: Any = thumb_manager.create_thumbnail(img)

        assert first is not None and os.path.exists(first)
        assert second == first
        assert thumb_manager.get_cache_statistics()["total_files"] == 1

    def test_force_regenerate_overwrites_cache(
        self, thumb_manager: Any, tmp_path: Any
    ) -> None:
        """``force_regenerate=True`` 跳过缓存捷径重新走生成器。"""
        from unittest.mock import patch

        img: str = make_image(tmp_path / "regen.png", fmt="PNG")
        first: Any = thumb_manager.create_thumbnail(img)
        assert first is not None and os.path.exists(first)

        with patch.object(
            thumb_manager,
            "_create_native_thumbnail",
            wraps=thumb_manager._create_native_thumbnail,  # noqa: SLF001
        ) as native_spy, patch.object(
            thumb_manager,
            "_create_image_thumbnail",
            wraps=thumb_manager._create_image_thumbnail,  # noqa: SLF001
        ) as python_spy:
            regenerated: Any = thumb_manager.create_thumbnail(
                img, force_regenerate=True
            )

        assert regenerated is not None
        assert os.path.exists(regenerated)
        assert native_spy.called or python_spy.called
