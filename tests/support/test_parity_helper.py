"""parity helper 单测（todo 5 验收）：相等 PASS / 不等 FAIL / 清单豁免 / 像素 hash。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict

import pytest

from tests.support.parity import (
    ParityMismatchError,
    PixelParityMismatchError,
    assert_parity,
    assert_pixel_parity,
    pixel_hash,
)


def _python_impl() -> Dict[str, Any]:
    """模拟 python-impl 输出（dict/list 嵌套）。"""
    return {
        "name": "alpha",
        "size": 12,
        "tags": ["x", "y"],
        "meta": {"created": "2026-01-01", "count": 3},
    }


def _native_impl_same() -> Dict[str, Any]:
    """模拟与 python-impl 一致的 native-impl 输出。"""
    return {
        "name": "alpha",
        "size": 12,
        "tags": ["x", "y"],
        "meta": {"created": "2026-01-01", "count": 3},
    }


def _native_impl_different() -> Dict[str, Any]:
    """模拟与 python-impl 不一致的 native-impl 输出（两处分歧）。"""
    return {
        "name": "alpha",
        "size": 13,
        "tags": ["x", "z"],
        "meta": {"created": "2026-01-01", "count": 3},
    }


def test_equal_pass_and_unequal_fail() -> None:
    """相等实现断言通过；不等实现断言失败且输出差异明细。"""
    assert assert_parity(_python_impl(), _native_impl_same()) == []

    with pytest.raises(ParityMismatchError) as excinfo:
        assert_parity(_python_impl(), _native_impl_different())
    message: str = str(excinfo.value)
    assert "$.size" in message
    assert "$.tags[1]" in message
    assert len(excinfo.value.diffs) == 2


def test_accepted_diffs_injection_hit_passes() -> None:
    """accepted-diffs 命中全部差异路径时豁免通过。"""
    diffs = assert_parity(
        _python_impl(),
        _native_impl_different(),
        accepted_diffs=["$.size", "$.tags[1]"],
    )
    assert len(diffs) == 2


def test_accepted_diffs_miss_still_fails() -> None:
    """清单未覆盖的差异仍 FAIL（只豁免命中的那条）。"""
    with pytest.raises(ParityMismatchError) as excinfo:
        assert_parity(
            _python_impl(),
            _native_impl_different(),
            accepted_diffs=["$.size"],
        )
    assert len(excinfo.value.diffs) == 1
    assert excinfo.value.diffs[0].startswith("$.tags[1]")
    assert len(excinfo.value.accepted) == 1


def _solid_rgba(pixel: bytes, width: int, height: int) -> bytes:
    """构造纯色 RGBA 字节（行优先）。

    Args:
        pixel: 4 字节 (R,G,B,A)。
        width: 宽。
        height: 高。

    Returns:
        bytes: ``width * height`` 像素的 RGBA 字节。
    """
    return pixel * (width * height)


def test_pixel_hash_equal_pass() -> None:
    """相等 RGBA 字节 → 像素 parity 断言 PASS 并返回共同 md5。"""
    rgba: bytes = _solid_rgba(b"\x11\x22\x33\x44", 4, 4)
    result: str = assert_pixel_parity(rgba, rgba)
    assert result == hashlib.md5(rgba).hexdigest()


def test_pixel_hash_unequal_fail() -> None:
    """不等 RGBA 字节 → FAIL 且输出差异明细（hash / 像素计数 / 样例）。"""
    same: bytes = _solid_rgba(b"\x10\x20\x30\xff", 4, 4)
    different: bytes = bytearray(same)
    different[-1] = 0xFE  # 只改最后一个像素的 alpha
    with pytest.raises(PixelParityMismatchError) as excinfo:
        assert_pixel_parity(same, bytes(different))
    message: str = str(excinfo.value)
    assert excinfo.value.diff_count == 1
    assert excinfo.value.python_hash in message
    assert excinfo.value.native_hash in message
    assert excinfo.value.geometry is None  # 裸字节无法推断尺寸
    assert any("offset" in line for line in excinfo.value.samples)


def test_pixel_parity_source_normalization(qapp: Any) -> None:
    """QImage / QPixmap / PIL / (w,h,bytes) 归一化到同一 RGBA md5。

    注意：QPixmap 在多数平台内部以 ``Format_ARGB32_Premultiplied`` 存储，
    ``toImage()`` 反向非预乘会带舍入，故其 hash 与原始 RGBA 不一定相等；
    但对同一输入 + 同一平台是确定性的——因此对 QPixmap 只断言「往返自洽」
    与「同一输入两次构造 hash 一致」，跨实现的严格像素一致性应以 QImage
    / PIL / 原始字节为锚。
    """
    from PIL import Image
    from PySide6.QtGui import QImage, QPixmap

    width, height = 8, 6
    rgba: bytes = bytes(
        ((x * 3 + y * 5 + c * 7) & 0xFF)
        for y in range(height)
        for x in range(width)
        for c in range(4)
    )
    expected: str = pixel_hash(rgba)

    pil_image: Image.Image = Image.frombytes("RGBA", (width, height), rgba)
    qimage: QImage = QImage(rgba, width, height, width * 4, QImage.Format_RGBA8888)
    qpixmap: QPixmap = QPixmap.fromImage(qimage)

    assert pixel_hash(pil_image) == expected
    assert pixel_hash(qimage) == expected
    assert pixel_hash((width, height, rgba)) == expected
    # QPixmap：两次独立构造 + toImage 往返自洽。
    qpixmap_again: QPixmap = QPixmap.fromImage(qimage)
    assert pixel_hash(qpixmap) == pixel_hash(qpixmap_again)
    assert pixel_hash(qpixmap) == pixel_hash(qpixmap.toImage())


def test_pixel_parity_tolerance_allows_small_diff() -> None:
    """默认逐字节一致；``max_diff_count`` 豁免少量像素差异后 PASS。"""
    width = height = 4
    base: bytes = _solid_rgba(b"\xc8\x64\x32\xff", width, height)
    tweaked: bytearray = bytearray(base)
    tweaked[-1] = 0xFE  # 1 像素 alpha 差异

    with pytest.raises(PixelParityMismatchError):
        assert_pixel_parity((width, height, base), (width, height, bytes(tweaked)))

    result: str = assert_pixel_parity(
        (width, height, base),
        (width, height, bytes(tweaked)),
        max_diff_count=1,
    )
    assert result == hashlib.md5(base).hexdigest()


def test_fluid_reference_frame_png_hash_matches_record() -> None:
    """fluid 参考帧 PNG 经 helper 归一化后与 JSON 记录 rgba_md5 一致。

    该用例把夹具（``fluid_samples/*.json`` / ``*.png``）与 parity helper
    的像素 hash 通路端到端串起来：PNG → RGBA md5 == 生成时记录值。
    """
    fixture_dir: Path = Path(__file__).resolve().parent / "faf_core_fixtures" / "fluid_samples"
    for stem in ("fluid_frame_64x48", "fluid_frame_160x100"):
        meta: Dict[str, Any] = json.loads(
            (fixture_dir / f"{stem}.json").read_text(encoding="utf-8")
        )
        png_hash: str = pixel_hash(str(fixture_dir / f"{stem}.png"))
        assert png_hash == meta["rgba_md5"]
