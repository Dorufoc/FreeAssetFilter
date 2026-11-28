"""SVG 缩略图渲染的设备生命周期回归测试。

背景：`_load_svg_image` 曾在「画笔仍未结束」时就 `qimage = qimage.convertToFormat(...)`，
旧 QImage 立刻被销毁、画笔悬空 —— Qt 打印
"Cannot destroy paint device that is being painted"，随后 `painter.end()`
作用在已释放的设备上直接 abort（真实运行时批量生成 SVG 缩略图会崩溃）。
本测试固定该路径的行为：必须能安全渲染多次。
"""

from __future__ import annotations

import pytest


_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">
  <rect x="4" y="4" width="56" height="56" rx="10" fill="#4a90d9"/>
  <circle cx="32" cy="32" r="12" fill="#ffffff" fill-opacity="0.85"/>
</svg>
"""


def test_load_svg_image_ends_painter_before_conversion(qapp, tmp_path) -> None:
    """反复渲染同一 SVG：设备生命周期正确时不会崩溃且有有效像素。"""
    from sopeek.core.managers.thumbnail_manager import ThumbnailManager

    svg_path = tmp_path / "sample.svg"
    svg_path.write_text(_SVG, encoding="utf-8")

    manager = ThumbnailManager()
    for _ in range(6):
        image, ok = manager._load_svg_image(str(svg_path))
        assert ok is True
        assert image is not None
        assert image.size[0] > 0 and image.size[1] > 0


@pytest.mark.parametrize("rounds", [3])
def test_load_svg_image_concurrently(qapp, tmp_path, rounds: int) -> None:
    """在多个线程并发渲染：不得触发 QPaintDevice 警告或 abort。"""
    from concurrent.futures import ThreadPoolExecutor

    from sopeek.core.managers.thumbnail_manager import ThumbnailManager

    svg_path = tmp_path / "threaded.svg"
    svg_path.write_text(_SVG, encoding="utf-8")

    manager = ThumbnailManager()

    def render(_index: int) -> bool:
        _image, ok = manager._load_svg_image(str(svg_path))
        return ok

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(render, range(rounds * 3)))
    assert all(results)
