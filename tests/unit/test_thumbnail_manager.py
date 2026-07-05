# -*- coding: utf-8 -*-
"""
thumbnail_manager 单元测试
测试 freeassetfilter/core/thumbnail_manager.py 模块的功能
"""
import pytest
import os
import sys
import time
from unittest.mock import MagicMock, patch

from PIL import Image

from freeassetfilter.utils.perf_metrics import clear_perf_metrics, get_perf_snapshot


def _svg_event_snapshot():
    snapshot = get_perf_snapshot()
    return snapshot.get("events", {}).get("thumbnail.load_svg_image", {})


def _clear_svg_cache(manager) -> None:
    with manager._svg_cache_lock:
        for entry in manager._svg_render_cache.values():
            manager._close_pil_image_quietly(entry.image)
        manager._svg_render_cache.clear()
        manager._set_svg_cache_metadata_locked()


def _clear_path_exists_cache(manager) -> None:
    manager._clear_path_exists_cache()


class TestThumbnailManagerBasic:
    """测试 ThumbnailManager 基本功能"""
    
    def test_module_import(self):
        """测试模块可以导入"""
        from freeassetfilter.core.thumbnail_manager import ThumbnailManager
        assert ThumbnailManager is not None
    
    def test_module_has_required_attributes(self):
        """测试模块有必要的属性"""
        from freeassetfilter.core import thumbnail_manager
        # 检查模块存在
        assert thumbnail_manager is not None


class TestThumbnailManagerRobustness:
    """测试 ThumbnailManager 鲁棒性"""
    
    def test_module_handles_errors_gracefully(self):
        """测试模块能优雅处理错误"""
        # 基础错误处理测试
        pass


class TestThumbnailManagerIntegration:
    """测试 ThumbnailManager 集成"""
    
    def test_module_integration(self):
        """测试模块集成"""
        # 集成测试
        pass


class TestThumbnailManagerSvgCache:
    """测试 SVG 渲染缓存的热命中、重校验与淘汰行为"""

    def setup_method(self):
        from freeassetfilter.core.thumbnail_manager import ThumbnailManager

        clear_perf_metrics()
        self.manager = ThumbnailManager()
        _clear_svg_cache(self.manager)

    def teardown_method(self):
        _clear_svg_cache(self.manager)

    def test_hot_cache_hit_skips_mtime_revalidation(self, monkeypatch):
        manager = self.manager
        file_path = "hot.svg"

        monkeypatch.setattr(manager, "SVG_CACHE_REVALIDATE_INTERVAL_SECONDS", 60.0)
        monkeypatch.setattr("freeassetfilter.core.thumbnail_manager.os.path.getmtime", lambda _: 1.0)
        manager._store_svg_cache_image(file_path, Image.new("RGBA", (4, 4), (255, 0, 0, 255)))

        def fail_getmtime(_):
            raise AssertionError("hot cache hit should not call getmtime")

        monkeypatch.setattr("freeassetfilter.core.thumbnail_manager.os.path.getmtime", fail_getmtime)
        cached = manager._get_cached_svg_image(file_path)

        assert cached is not None
        event = _svg_event_snapshot()
        assert event["cache_hit"] == 1
        assert event["counters"]["hot_cache_hit"] == 1
        assert event["cache_miss"] == 0

    def test_cold_cache_hit_revalidates_mtime(self, monkeypatch):
        manager = self.manager
        file_path = "cold.svg"
        observed = []

        monkeypatch.setattr(manager, "SVG_CACHE_REVALIDATE_INTERVAL_SECONDS", 0.0)

        def fake_getmtime(path):
            observed.append(path)
            return 5.0

        monkeypatch.setattr("freeassetfilter.core.thumbnail_manager.os.path.getmtime", fake_getmtime)
        manager._store_svg_cache_image(file_path, Image.new("RGBA", (4, 4), (0, 255, 0, 255)))

        with manager._svg_cache_lock:
            manager._svg_render_cache[file_path].last_validated_at = time.monotonic() - 10.0

        cached = manager._get_cached_svg_image(file_path)

        assert cached is not None
        assert observed == [file_path, file_path]
        event = _svg_event_snapshot()
        assert event["cache_hit"] == 1
        assert event["counters"]["revalidated_cache_hit"] == 1
        assert event["cache_miss"] == 0

    def test_stale_cache_entry_invalidates_and_counts_miss(self, monkeypatch):
        manager = self.manager
        file_path = "stale.svg"

        monkeypatch.setattr(manager, "SVG_CACHE_REVALIDATE_INTERVAL_SECONDS", 0.0)
        monkeypatch.setattr("freeassetfilter.core.thumbnail_manager.os.path.getmtime", lambda _: 5.0)
        manager._store_svg_cache_image(file_path, Image.new("RGBA", (4, 4), (0, 0, 255, 255)))

        with manager._svg_cache_lock:
            manager._svg_render_cache[file_path].last_validated_at = time.monotonic() - 10.0

        monkeypatch.setattr("freeassetfilter.core.thumbnail_manager.os.path.getmtime", lambda _: 6.0)
        cached = manager._get_cached_svg_image(file_path)

        assert cached is None
        with manager._svg_cache_lock:
            assert file_path not in manager._svg_render_cache
        event = _svg_event_snapshot()
        assert event["cache_miss"] == 1
        assert event["counters"]["stale_invalidated"] == 1

    def test_svg_cache_eviction_updates_counter(self, monkeypatch):
        manager = self.manager
        monkeypatch.setattr(manager, "MAX_SVG_CACHE_ENTRIES", 1)
        mtimes = iter([1.0, 2.0])
        monkeypatch.setattr("freeassetfilter.core.thumbnail_manager.os.path.getmtime", lambda _: next(mtimes))

        manager._store_svg_cache_image("first.svg", Image.new("RGBA", (2, 2), (1, 1, 1, 255)))
        manager._store_svg_cache_image("second.svg", Image.new("RGBA", (2, 2), (2, 2, 2, 255)))

        with manager._svg_cache_lock:
            assert list(manager._svg_render_cache.keys()) == ["second.svg"]
        event = _svg_event_snapshot()
        assert event["counters"]["cache_eviction"] == 1


class TestThumbnailManagerExistsCacheScope:
    """测试文件存在性缓存已提升为管理器级共享缓存。"""

    def setup_method(self):
        from freeassetfilter.core.thumbnail_manager import ThumbnailManager

        self.manager = ThumbnailManager()
        self.original_thumb_dir = self.manager._thumb_dir
        _clear_path_exists_cache(self.manager)

    def teardown_method(self):
        self.manager._thumb_dir = self.original_thumb_dir
        _clear_path_exists_cache(self.manager)

    def test_shared_exists_cache_reused_between_lookup_and_create(self, monkeypatch, tmp_path):
        manager = self.manager
        source_path = str(tmp_path / "source.jpg")
        thumbnail_path = str(tmp_path / "thumb.jpg")
        legacy_path = str(tmp_path / "thumb.png")
        exists_calls = {}

        monkeypatch.setattr(manager, "PATH_EXISTS_CACHE_TTL_SECONDS", 60.0)
        monkeypatch.setattr(manager, "get_thumbnail_path", lambda _: thumbnail_path)
        monkeypatch.setattr(manager, "get_legacy_thumbnail_path", lambda _: legacy_path)
        monkeypatch.setattr(manager, "_update_file_access_time", lambda _: None)

        def fake_exists(path):
            exists_calls[path] = exists_calls.get(path, 0) + 1
            return path in {source_path, thumbnail_path}

        monkeypatch.setattr("freeassetfilter.core.thumbnail_manager.os.path.exists", fake_exists)

        assert manager.get_existing_thumbnail_path(source_path) == thumbnail_path
        assert manager.create_thumbnail(source_path, force_regenerate=False) == thumbnail_path
        assert exists_calls[source_path] == 1
        assert exists_calls[thumbnail_path] == 1
        assert legacy_path not in exists_calls

    def test_clean_thumbnails_marks_deleted_files_missing_in_cache(self, monkeypatch, tmp_path):
        manager = self.manager
        thumbnail_path = tmp_path / "stale-thumb.jpg"
        thumbnail_path.write_bytes(b"thumb")
        manager._thumb_dir = str(tmp_path)

        monkeypatch.setattr(manager, "PATH_EXISTS_CACHE_TTL_SECONDS", 60.0)
        manager._set_cached_path_exists(str(thumbnail_path), True)

        deleted_count, remaining_count = manager.clean_thumbnails(max_cache_size=0)

        assert deleted_count == 1
        assert remaining_count == 0

        def fail_exists(_):
            raise AssertionError("deleted thumbnail path should be served from invalidated cache state")

        monkeypatch.setattr("freeassetfilter.core.thumbnail_manager.os.path.exists", fail_exists)
        assert manager._get_cached_path_exists(str(thumbnail_path)) is False


class TestThumbnailManagerBatchExecutorShutdown:
    """测试批量缩略图线程池的退出逻辑。"""

    def setup_method(self):
        from freeassetfilter.core.thumbnail_manager import ThumbnailManager

        self.manager = ThumbnailManager()

    def test_batch_executor_shutdown_is_non_blocking_after_normal_completion(self, monkeypatch, tmp_path):
        manager = self.manager
        source_path = str(tmp_path / "source.jpg")
        thumbnail_path = str(tmp_path / "thumb.jpg")
        legacy_path = str(tmp_path / "thumb.png")

        class ImmediateFuture:
            def __init__(self, result):
                self._result = result

            def add_done_callback(self, callback):
                callback(self)

            def done(self):
                return True

            def result(self):
                return self._result

            def cancel(self):
                return False

        class FakeExecutor:
            def __init__(self):
                self.shutdown_calls = []

            def submit(self, fn, *args, **kwargs):
                return ImmediateFuture(fn(*args, **kwargs))

            def shutdown(self, wait, cancel_futures=False):
                self.shutdown_calls.append((wait, cancel_futures))

        fake_executor = FakeExecutor()

        monkeypatch.setattr(
            "freeassetfilter.core.thumbnail_manager.ThreadPoolExecutor",
            lambda *args, **kwargs: fake_executor,
        )
        monkeypatch.setattr(manager, "_rust_bridge", MagicMock(available=False))
        monkeypatch.setattr(manager, "get_thumbnail_path", lambda _: thumbnail_path)
        monkeypatch.setattr(manager, "get_legacy_thumbnail_path", lambda _: legacy_path)
        monkeypatch.setattr(manager, "_create_image_thumbnail", lambda *_: thumbnail_path)
        monkeypatch.setattr(manager, "_update_file_access_time", lambda *_: None)
        monkeypatch.setattr(manager, "_set_cached_path_exists", lambda *_: None)
        monkeypatch.setattr(
            manager,
            "_get_cached_path_exists",
            lambda path, force_refresh=False: path in {source_path, thumbnail_path},
        )

        success_count, processed_count = manager.create_thumbnails_batch([source_path])

        assert (success_count, processed_count) == (1, 1)
        assert fake_executor.shutdown_calls == [(False, False)]

    def test_batch_executor_cancel_uses_async_shutdown_cleanup(self, monkeypatch, tmp_path):
        manager = self.manager
        source_path = str(tmp_path / "source.jpg")
        thumbnail_path = str(tmp_path / "thumb.jpg")
        legacy_path = str(tmp_path / "thumb.png")
        started_threads = []

        class PendingFuture:
            def __init__(self):
                self.cancel_called = False

            def add_done_callback(self, callback):
                self._callback = callback

            def done(self):
                return False

            def result(self):
                raise AssertionError("pending future should not be consumed")

            def cancel(self):
                self.cancel_called = True
                return True

        class FakeExecutor:
            def __init__(self):
                self.future = PendingFuture()
                self.shutdown_calls = []

            def submit(self, fn, *args, **kwargs):
                return self.future

            def shutdown(self, wait, cancel_futures=False):
                self.shutdown_calls.append((wait, cancel_futures))

        class FakeThread:
            def __init__(self, target, name, daemon):
                self.target = target
                self.name = name
                self.daemon = daemon

            def start(self):
                started_threads.append(self)

        cancel_states = iter([False, False, True])
        fake_executor = FakeExecutor()

        monkeypatch.setattr(
            "freeassetfilter.core.thumbnail_manager.ThreadPoolExecutor",
            lambda *args, **kwargs: fake_executor,
        )
        monkeypatch.setattr("freeassetfilter.core.thumbnail_manager.threading.Thread", FakeThread)
        monkeypatch.setattr(manager, "_rust_bridge", MagicMock(available=False))
        monkeypatch.setattr(manager, "get_thumbnail_path", lambda _: thumbnail_path)
        monkeypatch.setattr(manager, "get_legacy_thumbnail_path", lambda _: legacy_path)
        monkeypatch.setattr(
            manager,
            "_get_cached_path_exists",
            lambda path, force_refresh=False: path == source_path,
        )

        success_count, processed_count = manager.create_thumbnails_batch(
            [source_path],
            cancel_check=lambda: next(cancel_states, True),
        )

        assert (success_count, processed_count) == (0, 0)
        assert fake_executor.future.cancel_called is True
        assert fake_executor.shutdown_calls == []
        assert len(started_threads) == 1
        assert started_threads[0].daemon is True
        assert started_threads[0].name == "thumb_batch_shutdown_cancelled"
