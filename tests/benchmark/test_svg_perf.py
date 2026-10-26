# -*- coding: utf-8 -*-
# targets: core.preview.svg_renderer
"""SVG 渲染性能基准（todo-27 benchmark 重写）。

覆盖 SVG 的两个高频热点：

* ``_replace_svg_colors`` 颜色替换（文件选择器滚动时逐图标调用）；
* ``render_svg_to_pixmap`` 渲染到 Pixmap（含精确尺寸渲染）。

断言口径：平均耗时 < 0.2s（宽松阈值，数据缩小为 5 个小 SVG）。不引入
任何绝对秒数上限 gate——测试失败仅代表实现明显劣化，作基准快照参考。
"""

from __future__ import annotations

import time
from typing import Any, List

import pytest

from tests.support.data_factories import make_svg


pytestmark = pytest.mark.benchmark

#: 平均耗时上限（秒）。
AVG_UPPER_BOUND_S: float = 0.2
#: 复杂 SVG 内容（触发黑/白/品牌色/常规色四组替换）。
_COMPLEX_SVG: str = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" '
    'viewBox="0 0 256 256">\n'
    '  <defs>\n'
    '    <linearGradient id="grad1" x1="0%" y1="0%" x2="100%" y2="100%">\n'
    '      <stop offset="0%" stop-color="#000000"/>\n'
    '      <stop offset="100%" stop-color="#FFFFFF"/>\n'
    '    </linearGradient>\n'
    '  </defs>\n'
    '  <rect width="256" height="256" rx="24" fill="#000000"/>\n'
    '  <circle cx="128" cy="128" r="72" fill="#0a59f7"/>\n'
    '  <text x="128" y="146" font-size="42" text-anchor="middle" '
    'fill="#FFFFFF">Test</text>\n'
    '  <path d="M50 50 L100 100 L50 150 Z" fill="#cecece" stroke="#000000"/>\n'
    '  <path d="M206 50 L156 100 L206 150 Z" fill="#FFFFFF" stroke="#0a59f7"/>\n'
    '  <rect x="80" y="180" width="96" height="20" fill="#cecece"/>\n'
    "</svg>\n"
)


@pytest.fixture(scope="module")
def svg_dataset(tmp_path_factory: Any) -> Any:
    """模块级临时 SVG 数据集（5 个，缩小规模）。

    Args:
        tmp_path_factory: pytest 内置会话级临时目录工厂。

    Returns:
        list[str]: 5 个 SVG 文件路径。
    """
    base_dir: Any = tmp_path_factory.mktemp("faf_bench_svg")
    return [make_svg(base_dir / f"icon_{i:02d}.svg") for i in range(5)]


class TestSvgPerf:
    """SVG 颜色替换与渲染基准。"""

    def test_color_replace_avg_below_200ms(self) -> None:
        """``_replace_svg_colors`` 30 次平均 < 0.2s（颜色替换热点）。"""
        from freeassetfilter.core.preview.svg_renderer import SvgRenderer

        # 预热（SettingsManager 首个实例懒加载）
        SvgRenderer._replace_svg_colors(_COMPLEX_SVG)

        samples: List[float] = []
        for _ in range(30):
            start: float = time.perf_counter()
            result: str = SvgRenderer._replace_svg_colors(_COMPLEX_SVG)
            samples.append(time.perf_counter() - start)
            assert isinstance(result, str) and len(result) > 0

        avg_ms: float = sum(samples) / len(samples) * 1000.0
        print(f"\nSVG 颜色替换: 30 次平均 {avg_ms:.3f}ms")
        assert avg_ms / 1000.0 < AVG_UPPER_BOUND_S, (
            f"SVG 颜色替换过慢: avg={avg_ms:.3f}ms"
        )

    def test_render_pixmap_avg_below_200ms(
        self, svg_dataset: List[str], qapp: Any
    ) -> None:
        """``render_svg_to_pixmap`` 15 次平均 < 0.2s。"""
        from freeassetfilter.core.preview.svg_renderer import SvgRenderer

        svg_path: str = svg_dataset[0]
        assert SvgRenderer.render_svg_to_pixmap(svg_path, icon_size=64) is not None

        samples: List[float] = []
        for _ in range(15):
            start: float = time.perf_counter()
            pixmap: Any = SvgRenderer.render_svg_to_pixmap(svg_path, icon_size=64)
            samples.append(time.perf_counter() - start)
            assert pixmap is not None and not pixmap.isNull()

        avg_ms: float = sum(samples) / len(samples) * 1000.0
        print(f"\nSVG 渲染 64px: 15 次平均 {avg_ms:.2f}ms")
        assert avg_ms / 1000.0 < AVG_UPPER_BOUND_S, (
            f"SVG 渲染平均耗时过高: avg={avg_ms:.2f}ms"
        )

    @pytest.mark.parametrize("icon_size", [24, 32, 64])
    def test_render_different_sizes_avg_below_200ms(
        self, svg_dataset: List[str], icon_size: int, qapp: Any
    ) -> None:
        """不同尺寸精确渲染平均 < 0.2s（24/32/64px）。"""
        from freeassetfilter.core.preview.svg_renderer import SvgRenderer

        svg_path: str = svg_dataset[1 % len(svg_dataset)]

        iterations: int = 10
        samples: List[float] = []
        for _ in range(iterations):
            start: float = time.perf_counter()
            pixmap: Any = SvgRenderer.render_svg_to_exact_pixmap(
                svg_path, icon_width=icon_size, icon_height=icon_size
            )
            samples.append(time.perf_counter() - start)
            assert pixmap is not None and not pixmap.isNull()

        avg_ms: float = sum(samples) / len(samples) * 1000.0
        print(f"\nSVG 精确渲染 {icon_size}x{icon_size}: 平均 {avg_ms:.2f}ms")
        assert avg_ms / 1000.0 < AVG_UPPER_BOUND_S, (
            f"SVG 渲染尺寸 {icon_size} 过慢: avg={avg_ms:.2f}ms"
        )

    def test_render_batch_avg_below_200ms(
        self, svg_dataset: List[str], qapp: Any
    ) -> None:
        """批量渲染 5 个 SVG（模拟选择器滚动）平均 < 0.2s。"""
        from freeassetfilter.core.preview.svg_renderer import SvgRenderer

        # 预热
        for path in svg_dataset:
            SvgRenderer.render_svg_to_pixmap(path, icon_size=64)

        samples: List[float] = []
        for _ in range(5):
            start: float = time.perf_counter()
            for path in svg_dataset:
                pixmap: Any = SvgRenderer.render_svg_to_pixmap(path, icon_size=64)
                assert pixmap is not None and not pixmap.isNull()
            samples.append(time.perf_counter() - start)

        total_s: float = sum(samples)
        avg_ms: float = total_s / (5 * len(svg_dataset)) * 1000.0
        print(
            f"\n批量 SVG 渲染: 5 轮 x {len(svg_dataset)} 个 | "
            f"平均 {avg_ms:.2f}ms/个"
        )
        assert avg_ms / 1000.0 < AVG_UPPER_BOUND_S, (
            f"批量 SVG 渲染平均耗时过高: avg={avg_ms:.2f}ms"
        )
