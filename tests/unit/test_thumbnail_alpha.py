"""透明通道缩略图回归测试。

覆盖两层：

* 头部嗅探（``thumbnail_alpha.has_alpha_source``）—— 不解码、只看魔数/标志位；
* 落盘策略（``ThumbnailManager._save_alpha_thumbnail``）—— 真的带 alpha 写 PNG，
  名义带 alpha 但全不透明回退 JPEG，并清掉同哈希的另一种格式，避免读到旧图。
"""

from __future__ import annotations

import os

from PIL import Image

from sopeek.core.managers.thumbnail_alpha import has_alpha_source
from sopeek.core.managers.thumbnail_manager import ThumbnailManager


def _write_rgba_png(path: str, size: int = 32, alpha: int = 0) -> None:
    image = Image.new("RGBA", (size, size), (255, 0, 0, alpha))
    image.save(path, format="PNG")


def _write_palette_png_with_trns(path: str, size: int = 32) -> None:
    image = Image.new("P", (size, size), 0)
    image.putpalette([0, 0, 0, 255, 0, 0] + [0, 0, 0] * 254)
    image.save(path, format="PNG", transparency=0)


def test_png_alpha_by_color_type(tmp_path) -> None:
    """RGBA PNG 直接由 IHDR color type 判定。"""
    transparent = tmp_path / "a.png"
    opaque = tmp_path / "b.png"
    _write_rgba_png(str(transparent))
    Image.new("RGB", (32, 32), (1, 2, 3)).save(str(opaque), format="PNG")

    assert has_alpha_source(str(transparent)) is True
    assert has_alpha_source(str(opaque)) is False


def test_png_alpha_by_trns_chunk(tmp_path) -> None:
    """调色板 PNG 靠 tRNS 块声明透明色。"""
    path = tmp_path / "p.png"
    _write_palette_png_with_trns(str(path))

    assert has_alpha_source(str(path)) is True


def test_non_alpha_formats_are_skipped(tmp_path) -> None:
    """JPEG/BMP 等格式不进入透明链路。"""
    jpg = tmp_path / "x.jpg"
    Image.new("RGB", (16, 16), (9, 9, 9)).save(str(jpg), format="JPEG")

    assert has_alpha_source(str(jpg)) is False


def test_webp_lossless_alpha_detected(tmp_path) -> None:
    """VP8L 无损头的 alpha 位。"""
    path = tmp_path / "x.webp"
    Image.new("RGBA", (16, 16), (0, 255, 0, 0)).save(
        str(path), format="WEBP", lossless=True
    )

    assert has_alpha_source(str(path)) is True


def test_gif_transparency_detected(tmp_path) -> None:
    """GIF 图形控制扩展的透明标志。"""
    with_alpha = tmp_path / "a.gif"
    without = tmp_path / "b.gif"

    image = Image.new("P", (16, 16), 0)
    image.putpalette([0, 0, 0, 255, 0, 0] + [0, 0, 0] * 254)
    image.save(str(with_alpha), format="GIF", transparency=0)
    Image.new("P", (16, 16), 0).save(str(without), format="GIF")

    assert has_alpha_source(str(with_alpha)) is True
    assert has_alpha_source(str(without)) is False


def test_svg_is_always_alpha(tmp_path) -> None:
    """矢量渲染天然带 alpha，不必嗅探内容。"""
    path = tmp_path / "logo.svg"
    path.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")

    assert has_alpha_source(str(path)) is True


def test_save_alpha_thumbnail_writes_png_and_drops_stale_jpg(tmp_path) -> None:
    """真带 alpha → 写 .png，并删除同哈希旧 .jpg。"""
    manager = ThumbnailManager()
    source = tmp_path / "src.png"
    _write_rgba_png(str(source))

    stale_jpg = manager.get_thumbnail_path(str(source))
    os.makedirs(os.path.dirname(stale_jpg), exist_ok=True)
    with open(stale_jpg, "wb") as handle:
        handle.write(b"stale")

    saved = manager._save_alpha_thumbnail(
        Image.new("RGBA", (32, 32), (0, 0, 0, 0)), str(source)
    )

    assert saved is not None
    assert saved.endswith(".png")
    assert os.path.exists(saved)
    assert not os.path.exists(stale_jpg)
    with Image.open(saved) as thumb:
        assert thumb.mode == "RGBA"
        assert thumb.getchannel("A").getextrema()[0] < 255


def test_save_alpha_thumbnail_falls_back_to_jpeg_when_opaque(tmp_path) -> None:
    """名义带 alpha 但全不透明 → 回退 JPEG，不白付 PNG 编码成本。"""
    manager = ThumbnailManager()
    source = tmp_path / "opaque.png"
    _write_rgba_png(str(source), alpha=255)

    stale_png = manager.get_legacy_thumbnail_path(str(source))
    os.makedirs(os.path.dirname(stale_png), exist_ok=True)
    with open(stale_png, "wb") as handle:
        handle.write(b"stale")

    saved = manager._save_alpha_thumbnail(
        Image.new("RGBA", (32, 32), (255, 0, 0, 255)), str(source)
    )

    assert saved is not None
    assert saved.endswith(".jpg")
    assert not os.path.exists(stale_png)
    with Image.open(saved) as thumb:
        assert thumb.mode == "RGB"
