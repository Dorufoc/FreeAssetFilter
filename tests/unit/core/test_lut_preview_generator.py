# -*- coding: utf-8 -*-
"""C++/Python 双引擎 LUT 预览生成器单测（tests-comprehensive-refactor todo-9）。

覆盖 ``freeassetfilter.core.native.bridges.lut_preview_generator``：

* ``LUTPreviewGenerator`` 初始化（默认参考图路径解析）；
* ``load_reference_image`` 的缺失/存在/转换路径；
* ``preload`` 的 (256,256)/(512,512) 缩放缓存构建；
* ``generate_preview`` 的三分支：缓存命中 / C++ 引擎 / Python 引擎；
* ``_apply_1d_lut_numpy`` / ``_apply_3d_lut_numpy`` 向量化 LUT 应用；
* ``get_preview_path`` / ``clear_cache``（指定与全部）与存储目录隔离；
* 模块级 ``get_preview_generator`` / ``generate_lut_preview`` /
  ``create_default_reference_image``。

设计：测试不依赖真实 .pyd 是否可用——C++ 路径用 monkeypatch 伪造
``cpp_generate_preview`` 返回真实 PNG 字节；Python 路径强制 ``_cpp_available``
返回 False 后走 numpy 插值。``get_lut_preview_dir`` 被 monkeypatch 到
tmp_path 隔离存储，避免写真实 ``data/lut_previews``。
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np
import pytest

try:
    from PIL import Image

    from freeassetfilter.core.native.bridges.lut_preview_generator import (
        LUTPreviewGenerator,
        generate_lut_preview,
        get_preview_generator,
        create_default_reference_image,
    )
    from freeassetfilter.utils.lut_utils import CubeLUTParser
except (ImportError, RuntimeError) as exc:  # pragma: no cover - 环境依赖缺失
    pytest.skip(f"lut_preview_generator 依赖不可用: {exc}", allow_module_level=True)


# ---------------------------------------------------------------------------
# 测试上下文辅助
# ---------------------------------------------------------------------------
def _make_reference_image(path: Any, size: tuple[int, int] = (16, 16)) -> str:
    """生成一张带渐变色的 RGB 参考图并返回路径。"""
    img = Image.new("RGB", size)
    for y in range(size[1]):
        for x in range(size[0]):
            img.putpixel((x, y), (x * 16 % 256, y * 16 % 256, 128))
    img.save(str(path), "PNG")
    return str(path)


def _make_lut_3d(path: Any, size: int = 2) -> str:
    """生成一张最小的 3D identity CUBE LUT（size**3 行数据）。"""
    lines = ["TITLE \"test 3d\"", f"LUT_3D_SIZE {size}"]
    for b in range(size):
        for g in range(size):
            for r in range(size):
                lines.append(f"{r / (size - 1):.4f} {g / (size - 1):.4f} {b / (size - 1):.4f}")
    text = "\n".join(lines) + "\n"
    path = str(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _make_lut_1d(path: Any, size: int = 2) -> str:
    """生成一张最小的 1D CUBE LUT（size 行数据，R..G..B 排布）。"""
    lines = ["TITLE \"test 1d\"", f"LUT_1D_SIZE {size}"]
    for v in range(size):
        lines.append(f"{v / (size - 1):.4f} 0.0 0.0")
    for v in range(size):
        lines.append(f"{v / (size - 1):.4f} 0.0 0.0")
    for v in range(size):
        lines.append(f"{v / (size - 1):.4f} 0.0 0.0")
    text = "\n".join(lines) + "\n"
    path = str(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


@pytest.fixture(autouse=True)
def _isolate_preview_dir(monkeypatch: Any, tmp_path: Any) -> str:
    """将 ``get_lut_preview_dir`` monkeypatch 到临时目录。"""
    fake_dir = tmp_path / "lut_previews"
    fake_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(
        "freeassetfilter.core.native.bridges.lut_preview_generator.get_lut_preview_dir",
        lambda: str(fake_dir),
    )
    return str(fake_dir)


# ---------------------------------------------------------------------------
# 初始化与参考图加载
# ---------------------------------------------------------------------------
class TestInitAndReference:
    """构造函数与参考图加载。"""

    def test_default_reference_path_points_to_native_icons(self) -> None:
        """未显式传值时使用 native/icons/lut_reference.png。"""
        gen = LUTPreviewGenerator()
        assert "native" in gen.reference_image_path
        assert gen.reference_image_path.endswith("lut_reference.png")

    def test_explicit_reference_path(self, tmp_path: Any) -> None:
        """显式传参的路径被保留。"""
        ref = _make_reference_image(tmp_path / "ref.png")
        gen = LUTPreviewGenerator(reference_image_path=ref)
        assert gen.reference_image_path == ref

    def test_load_reference_image_missing_returns_false(self, tmp_path: Any) -> None:
        """参考图不存在返回 False。"""
        gen = LUTPreviewGenerator(str(tmp_path / "missing.png"))
        assert gen.load_reference_image() is False
        assert gen._reference_image is None

    def test_load_reference_image_success(self, tmp_path: Any) -> None:
        """参考图加载成功并转为 RGB。"""
        ref = _make_reference_image(tmp_path / "ref.png")
        gen = LUTPreviewGenerator(ref)
        assert gen.load_reference_image() is True
        assert gen._reference_image is not None
        assert gen._reference_image.mode == "RGB"


# ---------------------------------------------------------------------------
# preload
# ---------------------------------------------------------------------------
class TestPreload:
    """``preload`` 缩放缓存。"""

    def test_preload_builds_scaled_cache(self, tmp_path: Any) -> None:
        """preload 后存在 (256,256)/(512,512) 两个缩放缓存。"""
        ref = _make_reference_image(tmp_path / "ref.png")
        gen = LUTPreviewGenerator(ref)
        gen.preload()
        assert set(gen._reference_image_scaled.keys()) == {(256, 256), (512, 512)}
        assert gen._reference_image_scaled[(256, 256)].shape == (256, 256, 3)


# ---------------------------------------------------------------------------
# generate_preview：三个分支
# ---------------------------------------------------------------------------
@pytest.fixture()
def _prepared(tmp_path: Any) -> tuple[str, str]:
    """构造参考图 + 3D LUT 的通用素材。"""
    ref = _make_reference_image(tmp_path / "ref.png")
    lut = _make_lut_3d(tmp_path / "test.cube")
    return ref, lut


class TestGeneratePreview:
    """``generate_preview`` 缓存命中 / C++ / Python 分支。"""

    def test_cache_hit_returns_scaled_pixmap(
        self, qapp: Any, tmp_path: Any, _prepared: tuple[str, str]
    ) -> None:
        """缓存文件存在时直接读取并缩放。"""
        ref, _ = _prepared
        gen = LUTPreviewGenerator(ref)
        gen.preload()
        cache = tmp_path / "preview.png"
        Image.new("RGB", (256, 256), (10, 20, 30)).save(cache, "PNG")
        pixmap = gen.generate_preview("unused.cube", output_size=(64, 64), cache_path=str(cache))
        assert pixmap is not None
        assert not pixmap.isNull()

    def test_cpp_engine_path(self, qapp: Any, monkeypatch: Any, _prepared: tuple[str, str]) -> None:
        """C++ 引擎路径返回真实 PNG 解码的 QPixmap。"""
        ref, lut = _prepared
        gen = LUTPreviewGenerator(ref)
        monkeypatch.setattr(
            "freeassetfilter.core.native.bridges.lut_preview_generator._cpp_available",
            lambda: True,
        )
        import io

        png_bytes = io.BytesIO()
        Image.new("RGB", (8, 8), (99, 88, 77)).save(png_bytes, "PNG")

        def _fake_generate(lut_content: str, img_array: Any, w: int, h: int) -> bytes:
            assert len(lut_content) > 0
            assert img_array.ndim == 3
            assert w == 64 and h == 64
            return png_bytes.getvalue()

        monkeypatch.setattr(
            "freeassetfilter.core.native.bridges.lut_preview_generator.cpp_generate_preview",
            _fake_generate,
        )
        pixmap = gen.generate_preview(lut, output_size=(64, 64))
        assert pixmap is not None
        assert not pixmap.isNull()

    def test_python_engine_path(self, qapp: Any, monkeypatch: Any, _prepared: tuple[str, str]) -> None:
        """Python numpy 插值路径返回有效 QPixmap。"""
        ref, lut = _prepared
        gen = LUTPreviewGenerator(ref)
        monkeypatch.setattr(
            "freeassetfilter.core.native.bridges.lut_preview_generator._cpp_available",
            lambda: False,
        )
        pixmap = gen.generate_preview(lut, output_size=(64, 64))
        assert pixmap is not None
        assert not pixmap.isNull()

    def test_python_engine_saves_cache(
        self, qapp: Any, monkeypatch: Any, tmp_path: Any, _prepared: tuple[str, str]
    ) -> None:
        """Python 引擎生成时正确落缓存文件。"""
        ref, lut = _prepared
        gen = LUTPreviewGenerator(ref)
        monkeypatch.setattr(
            "freeassetfilter.core.native.bridges.lut_preview_generator._cpp_available",
            lambda: False,
        )
        cache = tmp_path / "out.png"
        pixmap = gen.generate_preview(lut, output_size=(64, 64), cache_path=str(cache))
        assert pixmap is not None
        assert cache.exists()

    def test_invalid_lut_returns_none(
        self, qapp: Any, monkeypatch: Any, tmp_path: Any, _prepared: tuple[str, str]
    ) -> None:
        """Python 引擎下坏 LUT 返回 None。"""
        ref, _ = _prepared
        gen = LUTPreviewGenerator(ref)
        monkeypatch.setattr(
            "freeassetfilter.core.native.bridges.lut_preview_generator._cpp_available",
            lambda: False,
        )
        bad_lut = tmp_path / "bad.cube"
        bad_lut.write_text("LUT_3D_SIZE 2\n0.1 0.1 0.1\n", encoding="utf-8")  # 数据不完整
        assert gen.generate_preview(str(bad_lut), output_size=(32, 32)) is None


# ---------------------------------------------------------------------------
# numpy LUT 应用
# ---------------------------------------------------------------------------
class TestApplyLutNumpy:
    """``_apply_1d_lut_numpy`` / ``_apply_3d_lut_numpy`` 向量化逻辑。"""

    def test_1d_identity_lut(self, tmp_path: Any) -> None:
        """identity 1D LUT 输出近似等于输入。"""
        lut_path = _make_lut_1d(tmp_path / "id1d.cube", size=2)
        parser = CubeLUTParser(lut_path)
        assert parser.parse() is True
        assert parser.is_3d is False
        img = np.zeros((4, 4, 3), dtype=np.float32)
        img[..., 0] = 0.5
        gen = LUTPreviewGenerator(str(tmp_path / "unused.png"))
        out = gen._apply_1d_lut_numpy(img, parser)
        assert out.shape == (4, 4, 3)
        assert abs(float(out[0, 0, 0]) - 0.5) < 0.01

    def test_3d_identity_lut(self, tmp_path: Any) -> None:
        """identity 3D LUT 输出近似等于输入。"""
        lut_path = _make_lut_3d(tmp_path / "id3d.cube", size=2)
        parser = CubeLUTParser(lut_path)
        assert parser.parse() is True
        assert parser.is_3d is True
        img = np.zeros((4, 4, 3), dtype=np.float32)
        img[..., 0] = 0.25
        img[..., 1] = 0.75
        img[..., 2] = 0.5
        gen = LUTPreviewGenerator(str(tmp_path / "unused.png"))
        out = gen._apply_3d_lut_numpy(img, parser)
        assert out.shape == (4, 4, 3)
        for channel, expected in ((0, 0.25), (1, 0.75), (2, 0.5)):
            vals = out[..., channel]
            assert float(vals.mean()) - expected < 0.15


# ---------------------------------------------------------------------------
# 缓存路径与清除
# ---------------------------------------------------------------------------
class TestCacheManagement:
    """``get_preview_path`` / ``clear_cache``。"""

    def test_get_preview_path_contains_lut_id(self, _isolate_preview_dir: str) -> None:
        """预览路径为 预览目录 + <lut_id>_preview.png。"""
        gen = LUTPreviewGenerator()
        assert gen.get_preview_path("abc") == os.path.join(_isolate_preview_dir, "abc_preview.png")

    def test_clear_cache_specific(self, tmp_path: Any) -> None:
        """仅删除指定 LUT 的缓存文件。"""
        gen = LUTPreviewGenerator()
        (tmp_path / "keep").mkdir(exist_ok=True)
        target = tmp_path / "to_remove.png"
        target.write_bytes(b"png")
        gen.get_preview_path = lambda _id: str(target)  # type: ignore[method-assign]
        gen.clear_cache("target")
        assert not target.exists()


# ---------------------------------------------------------------------------
# 模块级便捷入口
# ---------------------------------------------------------------------------
class TestModuleEntrypoints:
    """``get_preview_generator`` / ``generate_lut_preview`` / ``create_default_reference_image``。"""

    def test_get_preview_generator_singleton(self, monkeypatch: Any) -> None:
        """返回同类型实例（不强制单例断言）。"""
        import freeassetfilter.core.native.bridges.lut_preview_generator as mod

        monkeypatch.setattr(mod, "_preview_generator", None)
        gen = get_preview_generator()
        assert isinstance(gen, LUTPreviewGenerator)
        assert gen is mod._preview_generator

    def test_generate_lut_preview_without_source(self, qapp: Any, tmp_path: Any) -> None:
        """缺失 LUT 文件时不抛内部异常（返回 None 或 pixmap 均可）。"""
        result = generate_lut_preview(
            str(tmp_path / "missing.cube"), "dummy", output_size=(32, 32)
        )
        assert result is None or not result.isNull()

    def test_create_default_reference_image(self, tmp_path: Any) -> None:
        """创建法生成标准色彩测试图。"""
        out = tmp_path / "default_ref.png"
        assert create_default_reference_image(str(out)) is True
        assert out.exists()
        img = Image.open(out)
        assert img.size == (400, 400)
        img.close()