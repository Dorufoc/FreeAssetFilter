# -*- coding: utf-8 -*-
# targets: core.managers.thumbnail_manager
"""缩略图批量生成性能基准（todo-27 benchmark 重写）。

覆盖批量生成链路的三个口径（数据缩小为 20 张 240x180，全 tmp 生成）：

* ``create_thumbnails_batch`` 全量成功 + 吞吐量（>2 张/秒，宽松）；
* 缓存在两轮批量间的加速效果（speedup > 1.5x + 热路径单张 < 0.2s）；
* 批量规模 [5, 10, 20] 下的单张均耗扩展性（< 0.5s）。

资源纪律：``_thumb_dir`` 隔离到 tmp；等待全部有界（``qt_helpers`` +
deadline 轮询），绝不让后台 ``thumb_batch*`` 线程泄漏。
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, List

import pytest

from tests.benchmark.perf_benchmark_utils import create_benchmark_dataset
from tests.support import qt_helpers


pytestmark = pytest.mark.benchmark

#: 批量吞吐量下限（张/秒，宽松）。
THROUGHPUT_FLOOR: float = 2.0
#: 缓存加速比下限（非退化口径：128x128 原生生成本就毫秒级，
#: 冷/热差异主要由机器调度开销主导，放宽到 > 1.5x 防退化即可）。
SPEEDUP_FLOOR: float = 1.5
#: 热路径单张耗时上限（秒）。
HOT_PER_IMAGE_UPPER_S: float = 0.2
#: 批量扩展性单张耗时上限（秒）。
SCALE_PER_IMAGE_UPPER_S: float = 0.5


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: Any) -> Any:
    """模块级缩小基准数据集（20 图 / 5 SVG / 1 zip，全 tmp）。

    Args:
        tmp_path_factory: pytest 内置会话级临时目录工厂。

    Returns:
        PerfBenchmarkDataset: 数据集对象。
    """
    base_dir: Any = tmp_path_factory.mktemp("faf_bench_batch")
    return create_benchmark_dataset(
        str(base_dir), image_count=20, svg_count=5, archive_count=1
    )


@pytest.fixture
def thumb_manager(tmp_path: Any, qapp: Any) -> Any:
    """提供缩略图目录被隔离到临时目录的全新 ThumbnailManager 单例。

    Args:
        tmp_path: pytest 内置每测试临时目录。
        qapp: 会话级 QApplication。

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
    except Exception:  # noqa: BLE001 - teardown 幂等兜底
        pass
    ThumbnailManager._instance = None  # noqa: SLF001
    ThumbnailManager._initialized = False  # noqa: SLF001


def _wait_no_batch_threads(timeout: float = 5.0) -> None:
    """有界轮询确认无 ``thumb_batch*`` 后台线程残留。

    Args:
        timeout: 最大等待秒数（绝不无限等待）。
    """
    deadline: float = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any("thumb_batch" in t.name for t in threading.enumerate()):
            return
        time.sleep(0.05)
    lingering: List[str] = [
        t.name for t in threading.enumerate() if "thumb_batch" in t.name
    ]
    raise AssertionError(f"批量缩略图线程泄漏: {lingering}")


class TestBatchThumbnailPerf:
    """批量缩略图生成吞吐与缓存基准。"""

    def test_batch_throughput_above_2_per_second(
        self, thumb_manager: Any, dataset: Any, qapp: Any
    ) -> None:
        """20 张批量生成：全部成功且吞吐量 > 2 张/秒。"""
        images: List[str] = dataset.image_paths

        start: float = time.perf_counter()
        success: int
        processed: int
        success, processed = thumb_manager.create_thumbnails_batch(images)
        elapsed: float = time.perf_counter() - start
        qt_helpers.process_qt_events(qapp, ms=50)

        assert (success, processed) == (20, 20)
        throughput: float = processed / elapsed if elapsed > 0 else 0.0
        avg_ms: float = elapsed / max(1, processed) * 1000.0
        print(
            f"\n批量生成: {processed} 张 | 总耗时 {elapsed:.2f}s | "
            f"吞吐 {throughput:.2f} 张/秒 | 平均 {avg_ms:.2f}ms"
        )
        assert throughput > THROUGHPUT_FLOOR, (
            f"批量缩略图吞吐量过低: {throughput:.2f} 张/秒"
        )
        assert thumb_manager.get_thumbnail_count() == 20
        _wait_no_batch_threads()

    def test_cache_hit_speedup_and_hot_latency(
        self, thumb_manager: Any, dataset: Any, qapp: Any
    ) -> None:
        """两轮批量：热路径加速比 > 1.5x 且单张热耗时 < 0.2s。"""
        images: List[str] = dataset.image_paths

        # 第一轮：冷缓存生成
        start_cold: float = time.perf_counter()
        thumb_manager.create_thumbnails_batch(images)
        cold_s: float = time.perf_counter() - start_cold
        qt_helpers.process_qt_events(qapp, ms=30)

        # 第二轮：热缓存复用
        start_hot: float = time.perf_counter()
        thumb_manager.create_thumbnails_batch(images)
        hot_s: float = time.perf_counter() - start_hot
        qt_helpers.process_qt_events(qapp, ms=30)

        hot_per_image_s: float = hot_s / len(images) if hot_s > 0 else 0.0
        speedup: float = cold_s / hot_s if hot_s > 0 else 1.0
        print(
            f"\n冷缓存 {cold_s * 1000:.2f}ms -> 热缓存 {hot_s * 1000:.2f}ms | "
            f"加速比 {speedup:.1f}x | 热单张 {hot_per_image_s * 1000:.3f}ms"
        )
        assert speedup > SPEEDUP_FLOOR, f"缓存加速效果不明显: {speedup:.1f}x"
        assert hot_per_image_s < HOT_PER_IMAGE_UPPER_S, (
            f"缓存读取过慢: {hot_per_image_s * 1000:.2f}ms/张"
        )
        _wait_no_batch_threads()

    @pytest.mark.parametrize("batch_size", [5, 10, 20])
    def test_batch_size_scaling_avg_below_500ms(
        self, thumb_manager: Any, dataset: Any, batch_size: int, qapp: Any
    ) -> None:
        """带缓存清理的批量规模扩展：单张均耗 < 0.5s。"""
        images: List[str] = dataset.image_paths[:batch_size]

        # 清除本批缓存，确保测量真实生成性能
        for img_path in images:
            thumb_path: Any = thumb_manager.get_thumbnail_path(img_path)
            if thumb_path and os.path.exists(thumb_path):
                os.remove(thumb_path)

        start: float = time.perf_counter()
        success: int
        processed: int
        success, processed = thumb_manager.create_thumbnails_batch(images)
        elapsed: float = time.perf_counter() - start
        qt_helpers.process_qt_events(qapp, ms=30)

        assert success == batch_size
        assert processed == batch_size
        avg_time_per_image: float = (
            elapsed / processed if processed > 0 else 0.0
        )
        print(
            f"\n批量 {batch_size}: 总耗时 {elapsed:.2f}s | "
            f"平均每张 {avg_time_per_image * 1000:.2f}ms"
        )
        assert avg_time_per_image < SCALE_PER_IMAGE_UPPER_S, (
            f"批量 {batch_size} 单张耗时过高: {avg_time_per_image * 1000:.2f}ms"
        )
        _wait_no_batch_threads()
