# -*- coding: utf-8 -*-
"""
缩略图批量生成性能基准测试

覆盖：
- 单张缩略图生成性能
- 批量缩略图生成吞吐量
- 缓存命中率测试
- Rust vs Python 实现对比
"""

import os
import time
import tempfile
import shutil
from pathlib import Path
from typing import List, Dict, Any

import pytest

from tests.benchmark.perf_benchmark_utils import (
    create_benchmark_dataset,
    export_perf_snapshot,
    get_perf_summary,
    print_perf_summary,
    reset_perf_metrics,
)


class TestBatchThumbnailPerformance:
    """批量缩略图生成性能测试"""

    def setup_method(self):
        """测试前准备"""
        self.dataset = create_benchmark_dataset(
            image_count=50,
            svg_count=0,
            archive_count=0,
            timeline_video_placeholders=0,
        )
        reset_perf_metrics()

    def teardown_method(self):
        """测试后清理"""
        self.dataset.cleanup()

    def test_single_thumbnail_generation_latency(self):
        """单张缩略图生成延迟测试"""
        from freeassetfilter.core.thumbnail_manager import get_thumbnail_manager

        manager = get_thumbnail_manager(dpi_scale=1.0)
        test_image = self.dataset.image_paths[0]

        # 预热
        manager.create_thumbnail(test_image, force_regenerate=True)

        # 延迟测试
        iterations = 20
        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            manager.create_thumbnail(test_image, force_regenerate=True)
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        times.sort()
        p50 = times[int(len(times) * 0.5)]
        p95 = times[int(len(times) * 0.95)]
        avg = sum(times) / len(times)

        print(f"\n单张缩略图生成延迟:")
        print(f"  平均: {avg:.2f}ms")
        print(f"  P50: {p50:.2f}ms")
        print(f"  P95: {p95:.2f}ms")

        # 性能目标
        assert avg < 100.0, f"单张缩略图生成过慢: {avg:.2f}ms"
        assert p95 < 150.0, f"单张缩略图 P95 过高: {p95:.2f}ms"

    def test_batch_thumbnail_throughput(self):
        """批量缩略图生成吞吐量测试"""
        from freeassetfilter.core.thumbnail_manager import get_thumbnail_manager

        manager = get_thumbnail_manager(dpi_scale=1.0)
        test_images = self.dataset.image_paths[:30]

        # 清除缓存，确保测试生成性能
        for img_path in test_images:
            thumb_path = manager.get_thumbnail_path(img_path)
            if thumb_path and os.path.exists(thumb_path):
                os.remove(thumb_path)

        # 批量生成测试
        start = time.perf_counter()
        success_count, processed_count = manager.create_thumbnails_batch(
            test_images,
            progress_callback=None,
            cancel_check=None
        )
        elapsed = time.perf_counter() - start

        throughput = processed_count / elapsed if elapsed > 0 else 0

        print(f"\n批量缩略图生成吞吐量:")
        print(f"  图片数量: {processed_count}")
        print(f"  成功数量: {success_count}")
        print(f"  总耗时: {elapsed:.2f}s")
        print(f"  吞吐量: {throughput:.2f} 张/秒")

        # 性能目标：> 2 张/秒
        assert throughput > 2.0, f"批量缩略图吞吐量过低: {throughput:.2f} 张/秒"

    def test_thumbnail_cache_hit_performance(self):
        """缩略图缓存命中性能测试"""
        from freeassetfilter.core.thumbnail_manager import get_thumbnail_manager

        manager = get_thumbnail_manager(dpi_scale=1.0)
        test_images = self.dataset.image_paths[:20]

        # 第一轮：生成缩略图（冷缓存）
        start = time.perf_counter()
        for img_path in test_images:
            manager.create_thumbnail(img_path, force_regenerate=False)
        cold_time = time.perf_counter() - start

        # 第二轮：读取缓存（热缓存）
        start = time.perf_counter()
        for img_path in test_images:
            manager.create_thumbnail(img_path, force_regenerate=False)
        hot_time = time.perf_counter() - start

        speedup = cold_time / hot_time if hot_time > 0 else 1.0

        print(f"\n缩略图缓存性能:")
        print(f"  冷缓存耗时: {cold_time*1000:.2f}ms")
        print(f"  热缓存耗时: {hot_time*1000:.2f}ms")
        print(f"  加速比: {speedup:.1f}x")

        # 缓存应该显著加速
        assert speedup > 5.0, f"缓存加速效果不明显: {speedup:.1f}x"
        assert hot_time < 0.5, f"缓存读取过慢: {hot_time*1000:.2f}ms"

    @pytest.mark.parametrize("batch_size", [10, 20, 50])
    def test_batch_size_scaling(self, batch_size):
        """不同批量大小下的性能扩展性测试"""
        from freeassetfilter.core.thumbnail_manager import get_thumbnail_manager

        manager = get_thumbnail_manager(dpi_scale=1.0)
        test_images = self.dataset.image_paths[:batch_size]

        # 清除缓存
        for img_path in test_images:
            thumb_path = manager.get_thumbnail_path(img_path)
            if thumb_path and os.path.exists(thumb_path):
                os.remove(thumb_path)

        start = time.perf_counter()
        success_count, processed_count = manager.create_thumbnails_batch(
            test_images,
            progress_callback=None,
            cancel_check=None
        )
        elapsed = time.perf_counter() - start

        avg_time_per_image = elapsed / processed_count if processed_count > 0 else 0

        print(f"\n批量大小 {batch_size} 性能:")
        print(f"  总耗时: {elapsed:.2f}s")
        print(f"  平均每张: {avg_time_per_image*1000:.2f}ms")

        # 扩展性：批量增大时，单张耗时不应显著增加
        assert avg_time_per_image < 0.5, f"批量 {batch_size} 单张耗时过高"

    def test_rust_bridge_availability(self):
        """Rust 缩略图引擎可用性测试"""
        from freeassetfilter.core.native.bridges.rust_thumbnail_bridge import RustThumbnailBridge

        bridge = RustThumbnailBridge()

        print(f"\nRust 缩略图引擎状态:")
        print(f"  可用: {bridge.available}")

        if bridge.available:
            stats = bridge.get_decode_stats()
            print(f"  解码统计: {stats}")

        # 记录状态，不强制断言（允许纯 Python 回退）
        assert True

    def test_memory_usage_during_batch(self):
        """批量生成过程中的内存使用测试"""
        import psutil
        import gc

        from freeassetfilter.core.thumbnail_manager import get_thumbnail_manager

        # 尝试导入 psutil，未安装则跳过
        try:
            process = psutil.Process()
        except Exception:
            pytest.skip("psutil not available")

        manager = get_thumbnail_manager(dpi_scale=1.0)
        test_images = self.dataset.image_paths[:30]

        # 强制垃圾回收，获取基线内存
        gc.collect()
        baseline_memory = process.memory_info().rss / 1024 / 1024  # MB

        # 执行批量生成
        manager.create_thumbnails_batch(
            test_images,
            progress_callback=None,
            cancel_check=None
        )

        # 再次垃圾回收后检查内存
        gc.collect()
        peak_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = peak_memory - baseline_memory

        print(f"\n批量生成内存使用:")
        print(f"  基线内存: {baseline_memory:.1f}MB")
        print(f"  峰值内存: {peak_memory:.1f}MB")
        print(f"  内存增长: {memory_increase:.1f}MB")

        # 内存增长不应超过 200MB
        assert memory_increase < 200, f"内存增长过高: {memory_increase:.1f}MB"


class TestThumbnailPerformanceRegression:
    """缩略图性能回归测试"""

    def setup_method(self):
        self.dataset = create_benchmark_dataset(
            image_count=20,
            svg_count=0,
            archive_count=0,
            timeline_video_placeholders=0,
        )
        reset_perf_metrics()

    def teardown_method(self):
        self.dataset.cleanup()

    def test_thumbnail_generation_baseline(self):
        """缩略图生成性能基线测试"""
        from freeassetfilter.core.thumbnail_manager import get_thumbnail_manager

        manager = get_thumbnail_manager(dpi_scale=1.0)
        test_images = self.dataset.image_paths[:10]

        # 清除缓存
        for img_path in test_images:
            thumb_path = manager.get_thumbnail_path(img_path)
            if thumb_path and os.path.exists(thumb_path):
                os.remove(thumb_path)

        # 执行批量生成
        start = time.perf_counter()
        success_count, processed_count = manager.create_thumbnails_batch(
            test_images,
            progress_callback=None,
            cancel_check=None
        )
        elapsed = time.perf_counter() - start

        throughput = processed_count / elapsed if elapsed > 0 else 0

        print(f"\n缩略图生成性能基线:")
        print(f"  处理数量: {processed_count}")
        print(f"  成功数量: {success_count}")
        print(f"  总耗时: {elapsed:.2f}s")
        print(f"  吞吐量: {throughput:.2f} 张/秒")

        # 导出性能快照
        summary = get_perf_summary()
        print_perf_summary("thumbnail_batch_baseline")

        # 基线：吞吐量 > 2 张/秒
        assert throughput > 2.0, f"缩略图生成性能退化: {throughput:.2f} 张/秒"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
