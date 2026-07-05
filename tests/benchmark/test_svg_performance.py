# -*- coding: utf-8 -*-
"""
SVG 渲染性能基准测试

覆盖：
- SVG 颜色替换性能
- SVG 渲染到 Pixmap 性能
- 不同复杂度 SVG 的渲染性能
"""

import os
import time
import tempfile
import shutil
from pathlib import Path

import pytest

from tests.benchmark.perf_benchmark_utils import (
    create_benchmark_dataset,
    export_perf_snapshot,
    get_perf_summary,
    print_perf_summary,
    reset_perf_metrics,
)


class TestSvgPerformance:
    """SVG 渲染性能测试类"""

    def setup_method(self):
        """测试前准备"""
        self.dataset = create_benchmark_dataset(
            image_count=0,
            svg_count=20,
            archive_count=0,
            timeline_video_placeholders=0,
        )
        reset_perf_metrics()

    def teardown_method(self):
        """测试后清理"""
        self.dataset.cleanup()

    def test_svg_color_replace_performance(self):
        """SVG 颜色替换性能测试 - 高频调用热点"""
        from freeassetfilter.core.svg_renderer import SvgRenderer
        from freeassetfilter.utils.perf_metrics import track_perf

        # 创建复杂 SVG 内容
        complex_svg = self._create_complex_svg()

        # 预热
        SvgRenderer._replace_svg_colors(complex_svg)

        # 基准测试
        iterations = 100
        start = time.perf_counter()
        for _ in range(iterations):
            with track_perf("svg.replace_colors_bench"):
                SvgRenderer._replace_svg_colors(complex_svg)
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / iterations) * 1000
        print(f"\nSVG 颜色替换性能:")
        print(f"  迭代次数: {iterations}")
        print(f"  总耗时: {elapsed*1000:.2f}ms")
        print(f"  平均耗时: {avg_ms:.3f}ms")

        # 性能目标：单次 < 5ms (P95)
        assert avg_ms < 5.0, f"SVG 颜色替换过慢: {avg_ms:.3f}ms"

    def test_svg_render_pixmap_performance(self):
        """SVG 渲染到 Pixmap 性能测试"""
        from freeassetfilter.core.svg_renderer import SvgRenderer
        from PySide6.QtWidgets import QApplication

        # 确保 QApplication 存在
        app = QApplication.instance() or QApplication([])

        svg_path = self.dataset.svg_paths[0]

        # 预热
        SvgRenderer.render_svg_to_pixmap(svg_path, icon_size=64)

        # 基准测试
        iterations = 50
        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            pixmap = SvgRenderer.render_svg_to_pixmap(svg_path, icon_size=64)
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        times.sort()
        p50 = times[int(len(times) * 0.5)]
        p95 = times[int(len(times) * 0.95)]
        p99 = times[int(len(times) * 0.99)]
        avg = sum(times) / len(times)

        print(f"\nSVG 渲染到 Pixmap 性能:")
        print(f"  迭代次数: {iterations}")
        print(f"  平均耗时: {avg:.2f}ms")
        print(f"  P50: {p50:.2f}ms")
        print(f"  P95: {p95:.2f}ms")
        print(f"  P99: {p99:.2f}ms")

        # 性能目标
        assert avg < 10.0, f"SVG 渲染平均耗时过高: {avg:.2f}ms"
        assert p95 < 20.0, f"SVG 渲染 P95 过高: {p95:.2f}ms"

    @pytest.mark.parametrize("icon_size", [24, 32, 64, 128])
    def test_svg_render_different_sizes(self, icon_size):
        """不同尺寸 SVG 渲染性能测试"""
        from freeassetfilter.core.svg_renderer import SvgRenderer
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        svg_path = self.dataset.svg_paths[0]

        iterations = 20
        start = time.perf_counter()
        for _ in range(iterations):
            SvgRenderer.render_svg_to_exact_pixmap(
                svg_path, icon_width=icon_size, icon_height=icon_size
            )
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / iterations) * 1000
        print(f"\nSVG 渲染尺寸 {icon_size}x{icon_size}: {avg_ms:.2f}ms")

        # 大尺寸渲染应该更慢，但不应超过 3 倍
        assert avg_ms < 30.0, f"大尺寸 SVG 渲染过慢: {avg_ms:.2f}ms"

    def test_svg_render_batch_performance(self):
        """批量 SVG 渲染性能测试 - 模拟文件选择器场景"""
        from freeassetfilter.core.svg_renderer import SvgRenderer
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])

        # 模拟文件选择器滚动场景：同时渲染 20 个 SVG
        batch_size = 20
        svg_paths = self.dataset.svg_paths[:batch_size]

        start = time.perf_counter()
        for svg_path in svg_paths:
            SvgRenderer.render_svg_to_pixmap(svg_path, icon_size=64)
        elapsed = time.perf_counter() - start

        total_ms = elapsed * 1000
        avg_ms = total_ms / batch_size

        print(f"\n批量 SVG 渲染性能:")
        print(f"  批量大小: {batch_size}")
        print(f"  总耗时: {total_ms:.2f}ms")
        print(f"  平均耗时: {avg_ms:.2f}ms")

        # 批量渲染应该保持线性增长
        assert avg_ms < 15.0, f"批量 SVG 渲染平均耗时过高: {avg_ms:.2f}ms"

    def test_svg_color_cache_effectiveness(self):
        """SVG 颜色缓存效果测试"""
        from freeassetfilter.core.svg_renderer import SvgRenderer

        # 获取当前缓存状态
        initial_cache_size = len(SvgRenderer._cached_colors)

        # 多次调用确保缓存建立
        for _ in range(10):
            SvgRenderer._get_accent_color()
            SvgRenderer._get_base_color()

        # 验证缓存有效
        assert SvgRenderer._color_cache_valid, "颜色缓存未生效"

        print(f"\nSVG 颜色缓存测试:")
        print(f"  缓存大小: {len(SvgRenderer._cached_colors)}")
        print(f"  缓存有效: {SvgRenderer._color_cache_valid}")

    def _create_complex_svg(self) -> str:
        """创建复杂 SVG 内容用于测试"""
        return """<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="grad1" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#000000;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#FFFFFF;stop-opacity:1" />
    </linearGradient>
  </defs>
  <rect width="256" height="256" rx="24" fill="url(#grad1)"/>
  <circle cx="128" cy="128" r="72" fill="#0a59f7"/>
  <text x="128" y="146" font-size="42" text-anchor="middle" fill="#FFFFFF">Test</text>
  <path d="M50 50 L100 100 L50 150 Z" fill="#000000" stroke="#FFFFFF"/>
  <path d="M206 50 L156 100 L206 150 Z" fill="#FFFFFF" stroke="#000000"/>
  <rect x="80" y="180" width="96" height="20" fill="#cecece"/>
</svg>"""


class TestSvgPerformanceRegression:
    """SVG 性能回归测试 - 用于检测性能退化"""

    def setup_method(self):
        self.dataset = create_benchmark_dataset(
            image_count=0,
            svg_count=5,
            archive_count=0,
            timeline_video_placeholders=0,
        )
        reset_perf_metrics()

    def teardown_method(self):
        self.dataset.cleanup()

    def test_svg_color_replace_regression(self):
        """SVG 颜色替换回归测试 - 建立性能基线"""
        from freeassetfilter.core.svg_renderer import SvgRenderer

        svg_content = """<svg xmlns="http://www.w3.org/2000/svg">
  <path fill="#000000" stroke="#FFFFFF" d="M0 0 L100 100"/>
  <rect fill="#0a59f7" width="50" height="50"/>
  <circle fill="#cecece" cx="25" cy="25" r="20"/>
</svg>"""

        # 多次采样获取稳定结果
        samples = []
        for _ in range(50):
            start = time.perf_counter()
            SvgRenderer._replace_svg_colors(svg_content)
            elapsed = (time.perf_counter() - start) * 1000
            samples.append(elapsed)

        samples.sort()
        median = samples[len(samples) // 2]

        print(f"\nSVG 颜色替换回归基线:")
        print(f"  中位数: {median:.3f}ms")
        print(f"  P95: {samples[int(len(samples)*0.95)]:.3f}ms")

        # 导出性能快照
        summary = get_perf_summary()
        print_perf_summary("svg_color_replace_regression")

        # 建立基线：中位数 < 3ms
        assert median < 3.0, f"SVG 颜色替换性能退化: {median:.3f}ms"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
