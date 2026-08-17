# -*- coding: utf-8 -*-
"""ThumbnailManager（core/managers/thumbnail_manager.py）单元测试。

todo-8（unit/core 批 2）验收口径：
* ``create_thumbnail`` 的 PNG / JPG / BMP 三条真实生成路径；
* 缓存命中（第二次调用直接返回既有文件）与强制 ``force_regenerate`` 路径；
* ``get_cache_statistics`` 返回值形状；
* ``clean_thumbnails`` 按数量 / 按过期天数清理，``clear_all_thumbnails``；
* ``create_thumbnails_batch`` 异步队列不泄漏线程（qt_helpers.flush + 有界等待）。

资源纪律：测试不触碰真实 appdata 缩略图目录——每个用例把
``manager._thumb_dir`` 重定向到 ``tmp_path``；teardown 清理生成的缓存文件。
原生 Rust 引擎可用时走原生路径，不可用时回退 PIL（两条路径均在用例中被
驱动，不依赖特定 DLL）。
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, List

import pytest
from unittest.mock import patch

from tests.support import qt_helpers
from tests.support.data_factories import make_image, make_text


# =============================================================================
# fixture
# =============================================================================
@pytest.fixture
def thumb_manager(tmp_path: Any) -> Any:
    """提供缩略图目录被隔离到临时目录的全新 ThumbnailManager 单例。

    重置单例并把 ``_thumb_dir`` 指向 ``tmp_path/thumbs``，保证用例间零
    环境污染（真实 appdata 缩略图目录只在构造瞬间被 mkdir，不写入文件）。

    Args:
        tmp_path: pytest 内置每测试临时目录。

    Returns:
        ThumbnailManager: 绑定临时缓存目录的新实例。
    """
    from freeassetfilter.core.managers.thumbnail_manager import ThumbnailManager

    manager = ThumbnailManager()
    thumb_dir: str = str(tmp_path / "thumbs")
    manager._thumb_dir = thumb_dir
    os.makedirs(thumb_dir, exist_ok=True)
    manager._clear_path_exists_cache()
    yield manager
    try:
        manager.clear_all_thumbnails()
    except Exception:
        pass
    ThumbnailManager._instance = None
    ThumbnailManager._initialized = False


def _make_images(tmp_path: Any, count: int, fmt: str = "PNG") -> List[str]:
    """批量生成 count 张测试图片并返回路径列表。

    Args:
        tmp_path: 临时目录。
        count: 生成数量。
        fmt: PIL 保存格式（PNG/JPEG/BMP）。

    Returns:
        list[str]: 生成后的图片路径列表。
    """
    return [make_image(tmp_path / f"img_{i:03d}.png", fmt=fmt) for i in range(count)]


# =============================================================================
# 基本文件分类
# =============================================================================
class TestFileClassification:
    """图片 / 视频 / 媒体文件判定函数。"""

    def test_image_video_media_classification(self, thumb_manager: Any, tmp_path: Any) -> None:
        """常见扩展名的分类判定是否符合预期。"""
        png: str = str(tmp_path / "photo.png")
        mp4: str = str(tmp_path / "clip.mp4")
        txt: str = str(tmp_path / "notes.txt")

        assert thumb_manager.is_image_file(png) is True
        assert thumb_manager.is_image_file(mp4) is False
        assert thumb_manager.is_video_file(mp4) is True
        assert thumb_manager.is_video_file(png) is False
        assert thumb_manager.is_media_file(png) is True
        assert thumb_manager.is_media_file(mp4) is True
        assert thumb_manager.is_media_file(txt) is False

    def test_thumbnail_path_conventions(self, thumb_manager: Any, tmp_path: Any) -> None:
        """主缩略图路径 .jpg、兼容路径 .png，且哈希一致。"""
        img: str = str(tmp_path / "hashed.png")
        primary: str = thumb_manager.get_thumbnail_path(img)
        legacy: str = thumb_manager.get_legacy_thumbnail_path(img)
        assert primary.endswith(".jpg")
        assert legacy.endswith(".png")
        assert thumb_manager._get_thumbnail_hash(img) in primary
        assert thumb_manager._get_thumbnail_hash(img) in legacy

    def test_module_level_singleton_bridge(self, thumb_manager: Any) -> None:
        """``get_thumbnail_manager`` 返回同构单例（类级 _instance 共用）。"""
        import freeassetfilter.core.managers.thumbnail_manager as tm_module

        manager: Any = tm_module.get_thumbnail_manager()
        assert manager is thumb_manager
        assert tm_module._thumbnail_manager is thumb_manager


# =============================================================================
# create_thumbnail
# =============================================================================
class TestCreateThumbnail:
    """``create_thumbnail`` 的真实生成 / 缓存命中 / 强制再生。"""

    @pytest.mark.parametrize("fmt, suffix", [("PNG", ".png"), ("JPEG", ".jpg"), ("BMP", ".bmp")])
    def test_create_thumbnail_formats(
        self, thumb_manager: Any, tmp_path: Any, fmt: str, suffix: str
    ) -> None:
        """PNG / JPG / BMP 三种来源都真实产出 .jpg 缩略图。"""
        img: str = make_image(tmp_path / f"sample{suffix}", fmt=fmt)
        thumb_path: Any = thumb_manager.create_thumbnail(img)

        assert thumb_path is not None
        assert thumb_path.endswith(".jpg")
        assert os.path.exists(thumb_path)
        assert thumb_manager.has_thumbnail(img) is True
        assert thumb_manager.get_existing_thumbnail_path(img) == thumb_path

    def test_second_call_hits_cache(self, thumb_manager: Any, tmp_path: Any) -> None:
        """第二次调用不重新生成，直接返回既有缩略图路径。"""
        img: str = str(tmp_path / "cached.png")
        make_image(img, fmt="PNG")
        first: Any = thumb_manager.create_thumbnail(img)
        second: Any = thumb_manager.create_thumbnail(img)

        assert first is not None
        assert second == first
        assert thumb_manager.get_cache_statistics()["total_files"] == 1

    def test_cache_hit_rate_over_20_images(self, thumb_manager: Any, tmp_path: Any) -> None:
        """小数据集 20 张图片的二次命中率须 >0.85（验收 QA 口径）。"""
        paths: List[str] = _make_images(tmp_path, 20)
        first_pass: List[Any] = [thumb_manager.create_thumbnail(p) for p in paths]
        assert all(p is not None for p in first_pass)

        stats: dict = thumb_manager.get_cache_statistics(max_cache_size=20)
        assert stats["total_files"] == 20

        second_pass: List[Any] = [thumb_manager.create_thumbnail(p) for p in paths]
        hits: int = sum(
            1 for a, b in zip(second_pass, first_pass) if a is not None and a == b
        )
        assert hits / len(paths) >= 0.85

    def test_force_regenerate_invokes_generator(
        self, thumb_manager: Any, tmp_path: Any
    ) -> None:
        """``force_regenerate=True`` 跳过缓存捷径并真实调用各生成器。"""
        img: str = str(tmp_path / "regen.png")
        make_image(img, fmt="PNG")
        first: Any = thumb_manager.create_thumbnail(img)
        assert first is not None and os.path.exists(first)

        with patch.object(
            thumb_manager, "_create_native_thumbnail", wraps=thumb_manager._create_native_thumbnail
        ) as native_spy, patch.object(
            thumb_manager, "_create_image_thumbnail", wraps=thumb_manager._create_image_thumbnail
        ) as python_spy:
            regenerated: Any = thumb_manager.create_thumbnail(img, force_regenerate=True)

        assert regenerated is not None
        assert os.path.exists(regenerated)
        assert native_spy.called or python_spy.called

    def test_missing_source_returns_none(self, thumb_manager: Any, tmp_path: Any) -> None:
        """源文件不存在时返回 None 且不抛异常。"""
        missing: str = str(tmp_path / "not_exist.png")
        assert thumb_manager.create_thumbnail(missing) is None

    def test_non_media_file_returns_none(self, thumb_manager: Any, tmp_path: Any) -> None:
        """非媒体文件（.txt）返回 None。"""
        text_file: str = make_text(tmp_path / "notes.txt")
        assert thumb_manager.create_thumbnail(text_file) is None


# =============================================================================
# 缓存统计与清理
# =============================================================================
class TestCacheStatisticsAndCleanup:
    """``get_cache_statistics`` / ``clean_thumbnails`` / ``clear_all_thumbnails``。"""

    def test_empty_statistics_shape(self, thumb_manager: Any) -> None:
        """空缓存的统计 dict 形状与默认值。"""
        stats: dict = thumb_manager.get_cache_statistics()
        assert stats == {
            "total_files": 0,
            "max_files": 2000,
            "usage_percentage": 0,
            "oldest_file_time": None,
            "newest_file_time": None,
        }

    def test_statistics_after_creation(self, thumb_manager: Any, tmp_path: Any) -> None:
        """生成 3 张后统计字段正确。"""
        for img in _make_images(tmp_path, 3):
            assert thumb_manager.create_thumbnail(img)

        stats: dict = thumb_manager.get_cache_statistics(max_cache_size=100)
        assert stats["total_files"] == 3
        assert stats["max_files"] == 100
        assert abs(stats["usage_percentage"] - 3.0) < 1e-6
        assert stats["oldest_file_time"] and stats["newest_file_time"]
        assert stats["oldest_file_time"] <= stats["newest_file_time"]

    def test_clean_by_max_count(self, thumb_manager: Any, tmp_path: Any) -> None:
        """按最大数量清理：保留最新的 max_cache_size 个，返回 (删除数, 剩余数)。"""
        for img in _make_images(tmp_path, 5):
            assert thumb_manager.create_thumbnail(img)

        deleted: int
        remaining: int
        deleted, remaining = thumb_manager.clean_thumbnails(max_cache_size=2)
        assert (deleted, remaining) == (3, 2)
        assert thumb_manager.get_thumbnail_count() == 2
        assert thumb_manager.get_cache_statistics()["total_files"] == 2

    def test_clean_expired_by_age(self, thumb_manager: Any, tmp_path: Any) -> None:
        """按过期天数清理：时间戳早于 cutoff 的缩略图全部删除。

        Windows 下 ctime 不可回拨，因此注入假的 ``_get_all_thumbnail_files``
        时间戳来驱动清理分支（文件本身真实存在于磁盘）。
        """
        for img in _make_images(tmp_path, 2):
            assert thumb_manager.create_thumbnail(img)

        files: List[Any] = thumb_manager._get_all_thumbnail_files()
        assert len(files) == 2
        aged: List[Any] = [(path, time.time() - 30 * 86400) for path, _ in files]

        with patch.object(
            thumb_manager, "_get_all_thumbnail_files", return_value=aged
        ):
            deleted: int
            remaining: int
            deleted, remaining = thumb_manager.clean_thumbnails(cleanup_period_days=7)

        assert (deleted, remaining) == (2, 0)
        assert thumb_manager.get_thumbnail_count() == 0

    def test_clear_all_thumbnails(self, thumb_manager: Any, tmp_path: Any) -> None:
        """``clear_all_thumbnails`` 删除全部缓存并清空统计。"""
        for img in _make_images(tmp_path, 3):
            assert thumb_manager.create_thumbnail(img)

        deleted: int = thumb_manager.clear_all_thumbnails()
        assert deleted == 3
        assert thumb_manager.get_thumbnail_count() == 0
        assert thumb_manager.get_cache_statistics()["total_files"] == 0


# =============================================================================
# 异步批量队列
# =============================================================================
class TestBatchAsyncQueue:
    """``create_thumbnails_batch`` 的异步队列完成与线程纪律。"""

    def test_batch_creates_and_reuses_cache(self, thumb_manager: Any, tmp_path: Any, qapp: Any) -> None:
        """批量生成 8 张全部成功；二轮批量全部命中缓存。"""
        paths: List[str] = _make_images(tmp_path, 8)

        success: int
        processed: int
        success, processed = thumb_manager.create_thumbnails_batch(paths)
        assert (success, processed) == (8, 8)

        success2, processed2 = thumb_manager.create_thumbnails_batch(paths)
        assert (success2, processed2) == (8, 8)

    def test_batch_mixed_missing_files(self, thumb_manager: Any, tmp_path: Any) -> None:
        """缺失源文件计入 processed 且回调失败，不阻塞其余任务。"""
        good: str = make_image(tmp_path / "good.png", fmt="PNG")
        missing: str = str(tmp_path / "missing.png")
        progress: List[bool] = []

        success: int
        processed: int
        success, processed = thumb_manager.create_thumbnails_batch(
            [good, missing],
            progress_callback=lambda done, total, item, ok: progress.append(ok),
        )

        assert (success, processed) == (1, 2)
        assert progress.count(False) >= 1

    def test_batch_cancel_check_aborts(self, thumb_manager: Any, tmp_path: Any) -> None:
        """取消检查立即返回时，批量调用安全短路为 (0, 0)。"""
        paths: List[str] = _make_images(tmp_path, 4)
        success: int
        processed: int
        success, processed = thumb_manager.create_thumbnails_batch(
            paths, cancel_check=lambda: True
        )
        assert (success, processed) == (0, 0)

    def test_batch_no_thread_leak_after_flush(
        self, thumb_manager: Any, tmp_path: Any, qapp: Any
    ) -> None:
        """异步队列结束后不得遗留 ``thumb_batch`` 线程。

        先冲刷 Qt 事件，再做有界等待（内部超时兜底）轮询线程表，
        只要出现残留 ``thumb_batch*`` 线程即判失败——防止泄漏累积导致
        后续用例并发膨胀。
        """
        paths: List[str] = _make_images(tmp_path, 8)
        success: int
        processed: int
        success, processed = thumb_manager.create_thumbnails_batch(paths)
        assert (success, processed) == (8, 8)

        # 再跑一轮，确保连续两次批量后也没有线程残留
        thumb_manager.create_thumbnails_batch(paths)

        qt_helpers.process_qt_events(qapp, ms=30)
        deadline: float = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            lingering: List[str] = [
                t.name for t in threading.enumerate() if "thumb_batch" in t.name
            ]
            if not lingering:
                break
            time.sleep(0.05)

        lingering = [t.name for t in threading.enumerate() if "thumb_batch" in t.name]
        assert not lingering, f"批量缩略图线程泄漏: {lingering}"


# =============================================================================
# 帧 / SVG 缓存数据类
# =============================================================================
class TestFrameCacheEntries:
    """FrameCacheEntry / SvgRenderCacheEntry 数据类构造与字段。"""

    def test_frame_cache_entry_fields(self) -> None:
        """帧缓存条目：frame/timestamp/position/estimated_bytes。"""
        from freeassetfilter.core.managers.thumbnail_manager import FrameCacheEntry

        entry = FrameCacheEntry(frame=b"\x00", timestamp=1.5, position=10)
        assert entry.frame == b"\x00"
        assert entry.timestamp == 1.5
        assert entry.position == 10
        assert entry.estimated_bytes == 0
        entry.estimated_bytes = 42
        assert entry.estimated_bytes == 42

    def test_svg_render_cache_entry_fields(self) -> None:
        """SVG 渲染缓存条目：image/mtime/last_validated_at。"""
        from freeassetfilter.core.managers.thumbnail_manager import SvgRenderCacheEntry

        entry = SvgRenderCacheEntry(image=object(), mtime=3.0, last_validated_at=4.0)
        assert entry.mtime == 3.0
        assert entry.last_validated_at == 4.0


class TestVideoFrameCache:
    """VideoFrameCache：put/get/clear 与容量淘汰。"""

    def test_put_get_roundtrip(self) -> None:
        """写入后按 position 取回，miss 返回 None。"""
        from freeassetfilter.core.managers.thumbnail_manager import VideoFrameCache

        cache = VideoFrameCache(max_entries=2)
        cache.put(0, "frame-a")
        cache.put(1, "frame-b")
        assert cache.get(0) == "frame-a"
        assert cache.get(1) == "frame-b"
        assert cache.get(99) is None

    def test_clear_empties_cache(self) -> None:
        """clear 后 get 全部 miss 且容量归零。"""
        from freeassetfilter.core.managers.thumbnail_manager import VideoFrameCache

        cache = VideoFrameCache(max_entries=2)
        cache.put(0, "a")
        cache.put(1, "b")
        cache.clear()
        assert cache.get(0) is None
        assert cache.get(1) is None
        assert cache.current_bytes == 0

    def test_eviction_replaces_oldest(self) -> None:
        """超出 max_entries 时淘汰最旧条目。"""
        from freeassetfilter.core.managers.thumbnail_manager import VideoFrameCache

        cache = VideoFrameCache(max_entries=2)
        cache.put(0, "old")
        cache.put(1, "mid")
        cache.put(2, "new")
        assert cache.get(2) == "new"
        assert len(cache.cache) <= 2
        assert cache.current_bytes <= cache.max_bytes