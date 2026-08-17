# -*- coding: utf-8 -*-
# targets: core.managers.thumbnail_manager
"""缩略图缓存性能基准（todo-27 benchmark 重写）。

旧快照的 ``test_cache_performance.py`` 针对不存在的
``freeassetfilter.core.lru_k_cache.LRUKCache`` 做 put/get 延迟测量——
该模块在当前源码树中已不存在（V3 审计确认）。本文件改测 ThumbnailManager
的真实缓存路径：

* ``get_existing_thumbnail_path`` 热查找延迟（命中内存路径存在缓存）平均
  < 0.2s；
* 二轮 ``create_thumbnail`` 的缓存命中率 ≥ 0.85（沿用旧口径）。

资源纪律：``_thumb_dir`` 隔离到 tmp，数据全部程序化生成。
"""

from __future__ import annotations

import os
import time
from typing import Any, List

import pytest

from tests.support.data_factories import make_image


pytestmark = pytest.mark.benchmark

#: 单次缓存查找平均耗时上限（秒，宽松阈值）。
AVG_UPPER_BOUND_S: float = 0.2
#: 缓存命中率下限（沿用旧口径）。
HIT_RATE_FLOOR: float = 0.85
#: 数据集图片数量（缩小 5 倍后的规模）。
DATASET_SIZE: int = 20


@pytest.fixture
def thumb_manager(tmp_path: Any, qapp: Any) -> Any:
    """提供缩略图目录被隔离到临时目录的全新 ThumbnailManager 单例。

    Args:
        tmp_path: pytest 内置每测试临时目录。
        qapp: 会话级 QApplication（离屏渲染所需）。

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


def _make_images(tmp_path: Any, count: int) -> List[str]:
    """生成 count 张 240x180 JPEG 并返回路径列表。

    Args:
        tmp_path: 临时目录。
        count: 生成数量。

    Returns:
        list[str]: 生成后的图片路径列表。
    """
    return [
        make_image(tmp_path / f"img_{i:03d}.jpg", fmt="JPEG", size=(240, 180))
        for i in range(count)
    ]


class TestCachePerf:
    """缩略图缓存热查找与命中率基准。"""

    def test_cached_lookup_avg_below_200ms(
        self, thumb_manager: Any, tmp_path: Any
    ) -> None:
        """20 张缩略图预热后，热缓存查找平均 < 0.2s。"""
        paths: List[str] = _make_images(tmp_path, DATASET_SIZE)
        for p in paths:
            assert thumb_manager.create_thumbnail(p) is not None

        samples: List[float] = []
        for _ in range(20):  # 20 轮 × 20 路径 = 400 次热查找
            for p in paths:
                start: float = time.perf_counter()
                existing: Any = thumb_manager.get_existing_thumbnail_path(p)
                samples.append(time.perf_counter() - start)
                assert existing is not None

        avg_s: float = sum(samples) / len(samples)
        avg_ms: float = avg_s * 1000.0
        print(
            f"\n缓存热查找: {len(samples)} 次 | "
            f"平均 {avg_ms * 1000:.2f}us"
        )
        assert avg_s < AVG_UPPER_BOUND_S, (
            f"缓存热查找过慢: avg={avg_ms:.2f}ms "
            f"(上限 {AVG_UPPER_BOUND_S * 1000:.0f}ms)"
        )

    def test_cache_hit_rate_above_85_percent(
        self, thumb_manager: Any, tmp_path: Any
    ) -> None:
        """一轮生成 + 二轮命中：命中率 ≥ 0.85（沿用旧口径）。"""
        paths: List[str] = _make_images(tmp_path, DATASET_SIZE)

        # 第一轮：生成（冷缓存）
        for p in paths:
            assert thumb_manager.create_thumbnail(p, force_regenerate=False) is not None

        # 第二轮：读取（热缓存）
        hits: int = 0
        for p in paths:
            existing: Any = thumb_manager.create_thumbnail(p, force_regenerate=False)
            if existing is not None and os.path.exists(existing):
                hits += 1

        hit_rate: float = hits / len(paths)
        print(f"\n缓存命中率: {hit_rate:.2%}（{hits}/{len(paths)}）")
        assert hit_rate >= HIT_RATE_FLOOR, f"缓存命中率过低: {hit_rate:.2%}"

    def test_cache_miss_sorted_by_cache_hit_rate_stats(
        self, thumb_manager: Any, tmp_path: Any
    ) -> None:
        """批量后再查统计：total_files 等于生成数（缓存一致性）。"""
        paths: List[str] = _make_images(tmp_path, DATASET_SIZE)
        for p in paths:
            assert thumb_manager.create_thumbnail(p) is not None

        stats: dict = thumb_manager.get_cache_statistics(max_cache_size=DATASET_SIZE)
        assert stats["total_files"] == DATASET_SIZE
        assert stats["usage_percentage"] == 100.0
        assert thumb_manager.get_thumbnail_count() == DATASET_SIZE
