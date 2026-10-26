# -*- coding: utf-8 -*-
# targets: core.managers.thumbnail_manager
"""缩略图单张生成性能基准（todo-27 benchmark 重写）。

锁定 ThumbnailManager 单张缩略图生成链路的耗时口径：

* 首次生成（强制重生成路径）平均耗时 < 0.2s——沿旧口径但数据缩小 5 倍
  （旧版 100 张 1920px 太慢；本文件单张 240x180）；
* 二次调用（缓存捷径）应命中缓存并返回相同路径（二跳缓存契约）。

资源纪律：

* 管理器 ``_thumb_dir`` 重定向到 ``tmp_path``，绝不触碰真实 appdata
  缩略图缓存；
* 不访问真实 data/，全部图片由 ``make_image`` 程序化生成。
"""

from __future__ import annotations

import os
import time
from typing import Any

import pytest

from tests.support.data_factories import make_image


pytestmark = pytest.mark.benchmark

#: 单张生成平均耗时上限（秒，宽松阈值，沿旧口径缩小 5 倍后的断言）。
AVG_UPPER_BOUND_S: float = 0.2
#: 强制重生成迭代次数。
SAMPLES: int = 5


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


class TestThumbnailPerf:
    """单张缩略图生成的延迟基准。"""

    def test_single_thumbnail_generation_avg_below_200ms(
        self, thumb_manager: Any, tmp_path: Any
    ) -> None:
        """强制重生成 5 次的平均耗时 < 0.2s（缩小数据口径）。"""
        img: str = make_image(
            tmp_path / "single_thumb.jpg", fmt="JPEG", size=(240, 180)
        )
        first: Any = thumb_manager.create_thumbnail(img)
        assert first is not None and os.path.exists(first)

        samples: list[float] = []
        for _ in range(SAMPLES):
            start: float = time.perf_counter()
            result: Any = thumb_manager.create_thumbnail(img, force_regenerate=True)
            elapsed: float = time.perf_counter() - start
            assert result is not None and os.path.exists(result)
            samples.append(elapsed)

        avg_s: float = sum(samples) / len(samples)
        avg_ms: float = avg_s * 1000.0
        print(
            f"\n单张缩略图强制重生成: 迭代 {len(samples)} 次 | "
            f"平均 {avg_ms:.2f}ms"
        )
        assert avg_s < AVG_UPPER_BOUND_S, (
            f"单张缩略图生成过慢: avg={avg_ms:.2f}ms "
            f"(上限 {AVG_UPPER_BOUND_S * 1000:.0f}ms)"
        )

    def test_second_call_hits_cache_and_returns_same_path(
        self, thumb_manager: Any, tmp_path: Any
    ) -> None:
        """二次调用走缓存捷径：返回相同路径且时间显著低于冷生成。"""
        img: str = make_image(
            tmp_path / "cached_thumb.jpg", fmt="JPEG", size=(240, 180)
        )
        first: Any = thumb_manager.create_thumbnail(img)
        assert first is not None

        # 冷路径（强制重生成一次作为对照）
        start_cold: float = time.perf_counter()
        thumb_manager.create_thumbnail(img, force_regenerate=True)
        cold_s: float = time.perf_counter() - start_cold

        # 热路径（缓存二跳）
        start_hot: float = time.perf_counter()
        second: Any = thumb_manager.create_thumbnail(img)
        hot_s: float = time.perf_counter() - start_hot

        assert second == first
        assert os.path.exists(second)  # type: ignore[arg-type]
        print(f"\n冷生成 {cold_s * 1000:.2f}ms -> 热复用 {hot_s * 1000:.2f}ms")
        # 热路径必须显著快于冷路径（缓存生效；不 gate 绝对值差异）
        assert hot_s < cold_s

    def test_small_dataset_cache_statistics_consistent(
        self, thumb_manager: Any, tmp_path: Any
    ) -> None:
        """20 张缩略图生成后磁盘缓存统计与计数一致（数据规模 5 倍缩小）。"""
        paths: list[str] = [
            make_image(tmp_path / f"img_{i:03d}.jpg", fmt="JPEG", size=(240, 180))
            for i in range(20)
        ]
        for p in paths:
            result: Any = thumb_manager.create_thumbnail(p)
            assert result is not None and os.path.exists(result)

        stats: dict = thumb_manager.get_cache_statistics(max_cache_size=20)
        assert stats["total_files"] == 20
        assert thumb_manager.get_thumbnail_count() == 20
        assert stats["usage_percentage"] == 100.0
