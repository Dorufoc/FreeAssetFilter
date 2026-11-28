"""SVG 缩略图渲染比例回归测试。

历史缺陷：``_load_svg_image`` 先用 ``painter.scale()`` 按 viewBox 手工放大，再调
``QSvgRenderer.render(painter)`` —— 而后者本身就会把 viewBox 映射到画笔 viewport，
于是双重放大：200×200 的 SVG 实测圆直径 232px（应为 112px）并越过右／下边界被裁掉，
缩略图里的 SVG 图标永远是「放大后被切掉一块」。

本测试用「四周都有留白」的圆形 SVG 断言：渲染结果不贴边、直径符合比例。
"""

from __future__ import annotations

import os

import pytest

from sopeek.core.managers.thumbnail_manager import ThumbnailManager

_SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}">'
    '<circle cx="{half}" cy="{half}" r="{radius}" fill="#5ad07a"/></svg>'
)


def _circumscribed_svg(path: str, size: int = 200, radius_ratio: float = 0.4) -> int:
    """写入一个居中的圆形 SVG，返回圆半径（像素）。"""
    half = size / 2.0
    radius = size * radius_ratio
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            _SVG_TEMPLATE.format(size=size, half=half, radius=radius)
        )
    return int(round(radius))


def test_svg_render_is_not_double_scaled(tmp_path, qapp) -> None:
    """渲染出的圆不应贴边，且直径与 viewBox 比例一致。"""
    svg_path = str(tmp_path / "circle.svg")
    radius = _circumscribed_svg(svg_path, size=200, radius_ratio=0.4)

    manager = ThumbnailManager(dpi_scale=1.0)
    image, ok = manager._load_svg_image(svg_path)

    assert ok is True
    assert image is not None

    alpha = image.getchannel("A")
    width, height = image.size
    middle_row = height // 2
    columns = [x for x in range(width) if alpha.getpixel((x, middle_row)) > 10]

    assert columns, "圆形区域没有渲染出任何不透明像素"
    left, right = columns[0], columns[-1]
    diameter = right - left + 1
    scale = width / 200.0
    expected = radius * 2 * scale

    # 直径误差 5% 以内（含抗锯齿边缘判定误差）
    assert abs(diameter - expected) <= expected * 0.05, (
        f"直径 {diameter}px 与期望 {expected:.1f}px 不符（双重缩放回归）"
    )
    # 四周都要有留白：贴边即说明被裁切
    assert left > 2, f"左边界贴边（{left}），SVG 被放大裁切"
    assert right < width - 3, f"右边界贴边（{right}/{width}），SVG 被放大裁切"

    middle_column = width // 2
    rows = [y for y in range(height) if alpha.getpixel((middle_column, y)) > 10]
    assert rows, "竖直方向没有渲染出任何不透明像素"
    assert rows[0] > 2 and rows[-1] < height - 3, "上下边界贴边，SVG 被放大裁切"

    os.remove(svg_path)


def test_svg_thumbnail_keeps_transparency(tmp_path, qapp) -> None:
    """SVG 缩略图是 PNG 且圆形之外保持透明。"""
    svg_path = str(tmp_path / "circle.svg")
    _circumscribed_svg(svg_path, size=200, radius_ratio=0.4)

    manager = ThumbnailManager(dpi_scale=1.0)
    saved = manager.create_thumbnail(svg_path, force_regenerate=True)

    assert saved is not None
    assert saved.lower().endswith(".png")

    from PIL import Image

    with Image.open(saved) as thumbnail:
        assert thumbnail.mode == "RGBA"
        assert thumbnail.getpixel((0, 0))[3] == 0
