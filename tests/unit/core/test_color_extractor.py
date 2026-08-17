# -*- coding: utf-8 -*-
"""核心颜色提取工具单测（tests-comprehensive-refactor todo-9）。

覆盖 ``freeassetfilter.core.native.bridges.color_extractor`` 的纯 Python
降级路径与通用工具函数：

* ``_extract_cover_colors_python`` 的像素统计/去重/补灰逻辑；
* ``extract_cover_colors`` 的 Rust 优先 + 空数据/坏图降级；
* ``extract_cover_colors_from_path`` 的缺失文件/正常文件路径；
* ``color_distance`` / ``_is_color_different`` / ``_is_valid_color``；
* ``rgb_to_hex`` / ``hex_to_qcolor`` 互转；
* ``sort_colors_by_brightness`` / ``adjust_colors_for_gradient``；
* ``generate_colors_from_accent`` / ``get_theme_colors_for_audio``；
* ``is_rust_available`` / ``get_extractor_version`` 状态查询。

为保证确定性，所有走 ``extract_cover_colors`` 的测试显式将
``_ensure_rust_module`` 打桩为 False，强制走纯 Python 路径，避免依赖
本机 Rust DLL。坏图数据统一用 ``b"not-an-image"`` 触发解码失败。
"""

from __future__ import annotations

import io
from typing import Any, Callable, List

import pytest
from PIL import Image
from PySide6.QtGui import QColor

from freeassetfilter.core.native.bridges import color_extractor as ce


# ---------------------------------------------------------------------------
# 测试上下文辅助
# ---------------------------------------------------------------------------
def _force_python_fallback(monkeypatch: Any) -> None:
    """强制 ``extract_cover_colors`` 走纯 Python 降级路径。"""
    monkeypatch.setattr(ce, "_ensure_rust_module", lambda: False)


def _red_png_bytes(size: tuple[int, int] = (100, 100)) -> bytes:
    """生成纯红色 PNG 字节。"""
    buf = io.BytesIO()
    Image.new("RGB", size, (255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# extract_cover_colors
# ---------------------------------------------------------------------------
class TestExtractCoverColors:
    """``extract_cover_colors`` 主入口。"""

    def test_empty_data_returns_empty(self, monkeypatch: Any) -> None:
        """空封面数据返回空列表。"""
        assert ce.extract_cover_colors(b"") == []

    def test_invalid_image_returns_empty(self, monkeypatch: Any) -> None:
        """坏图数据返回空列表而不抛异常。"""
        _force_python_fallback(monkeypatch)
        assert ce.extract_cover_colors(b"not-an-image") == []

    def test_python_fallback_extracts_red(self, monkeypatch: Any) -> None:
        """纯红色图提取到红色为主的颜色列表。"""
        _force_python_fallback(monkeypatch)
        colors = ce.extract_cover_colors(_red_png_bytes(), num_colors=5)
        assert len(colors) == 5
        red = colors[0]
        assert red.red() == 255 and red.green() == 0 and red.blue() == 0

    def test_num_colors_respected(self, monkeypatch: Any) -> None:
        """请求数量受限（单色图补灰到 5 个）。"""
        _force_python_fallback(monkeypatch)
        colors = ce.extract_cover_colors(_red_png_bytes(), num_colors=5)
        assert len(colors) == 5

    def test_falls_back_when_rust_throws(self, monkeypatch: Any) -> None:
        """Rust 提取抛异常时降级到 Python 仍返回结果。"""
        monkeypatch.setattr(ce, "_ensure_rust_module", lambda: True)
        monkeypatch.setattr(ce, "_RUST_MODULE", None)

        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise ValueError("rust failed")

        monkeypatch.setattr(ce, "_prepare_image_data_for_rust", _boom)
        colors = ce.extract_cover_colors(_red_png_bytes(), num_colors=5)
        assert len(colors) == 5


# ---------------------------------------------------------------------------
# extract_cover_colors_from_path
# ---------------------------------------------------------------------------
class TestExtractFromPath:
    """``extract_cover_colors_from_path`` 文件路径入口。"""

    def test_missing_file_returns_empty(self, monkeypatch: Any, tmp_path: Any) -> None:
        """不存在的文件返回空列表。"""
        _force_python_fallback(monkeypatch)
        assert ce.extract_cover_colors_from_path(str(tmp_path / "nope.png")) == []

    def test_valid_file_extracts(self, monkeypatch: Any, tmp_path: Any) -> None:
        """正常文件提取出颜色。"""
        _force_python_fallback(monkeypatch)
        path = tmp_path / "cover.png"
        path.write_bytes(_red_png_bytes((64, 64)))
        colors = ce.extract_cover_colors_from_path(str(path), num_colors=5)
        assert len(colors) == 5


# ---------------------------------------------------------------------------
# 内部判定函数
# ---------------------------------------------------------------------------
class TestColorJudgment:
    """颜色有效性/差异判定。"""

    def test_is_valid_color_midtones(self) -> None:
        """中等亮度颜色有效。"""
        assert ce._is_valid_color(QColor(128, 128, 128)) is True

    def test_is_valid_color_rejects_black(self) -> None:
        """全黑颜色无效（过暗）。"""
        assert ce._is_valid_color(QColor(0, 0, 0)) is False

    def test_is_valid_color_rejects_white(self) -> None:
        """全白颜色无效（过亮）。"""
        assert ce._is_valid_color(QColor(255, 255, 255)) is False

    def test_color_distance_same_color_zero(self) -> None:
        """同色距离为 0。"""
        assert ce.color_distance(QColor(10, 20, 30), QColor(10, 20, 30)) == 0.0

    def test_color_distance_square(self) -> None:
        """欧氏平方距离正确。"""
        assert ce.color_distance(QColor(0, 0, 0), QColor(3, 4, 0)) == 25.0

    def test_is_color_different_threshold(self) -> None:
        """距离低于阈值判定为相似（False）。"""
        existing = [QColor(0, 0, 0)]
        assert ce._is_color_different(QColor(1, 1, 0), existing, min_distance=2.0) is False
        assert ce._is_color_different(QColor(5, 0, 0), existing, min_distance=2.0) is True


# ---------------------------------------------------------------------------
# 颜色转换
# ---------------------------------------------------------------------------
class TestColorConversion:
    """``rgb_to_hex`` / ``hex_to_qcolor`` 互转。"""

    def test_rgb_to_hex(self) -> None:
        """QColor 转小写十六进制字符串。"""
        assert ce.rgb_to_hex(QColor(255, 0, 128)) == "#ff0080"

    def test_hex_to_qcolor_valid(self) -> None:
        """合法 7 位 hex 字符串转 QColor。"""
        color = ce.hex_to_qcolor("#12ab44")
        assert color is not None
        assert (color.red(), color.green(), color.blue()) == (0x12, 0xAB, 0x44)

    def test_hex_to_qcolor_invalid_short(self) -> None:
        """非 7 位长度返回 None。"""
        assert ce.hex_to_qcolor("#ff0") is None

    def test_hex_to_qcolor_invalid_prefix(self) -> None:
        """缺少 # 前缀返回 None。"""
        assert ce.hex_to_qcolor("ff0000") is None

    def test_hex_to_qcolor_invalid_hex(self) -> None:
        """非法十六进制字符返回 None。"""
        assert ce.hex_to_qcolor("#zzzzzz") is None


# ---------------------------------------------------------------------------
# 排序与会话
# ---------------------------------------------------------------------------
class TestSortAndGradient:
    """明度排序与渐变调整。"""

    def test_sort_colors_by_brightness_ascending(self) -> None:
        """按亮度升序排序。"""
        dark, mid, bright = QColor(30, 30, 30), QColor(128, 128, 128), QColor(200, 200, 200)
        result = ce.sort_colors_by_brightness([bright, dark, mid], ascending=True)
        assert result == [dark, mid, bright]

    def test_sort_colors_by_brightness_descending_default(self) -> None:
        """默认降序。"""
        dark, bright = QColor(30, 30, 30), QColor(200, 200, 200)
        result = ce.sort_colors_by_brightness([dark, bright])
        assert result == [bright, dark]

    def test_adjust_colors_for_gradient_fewer_than_five(self) -> None:
        """不足 5 色时原样返回。"""
        colors = [QColor(1, 2, 3)]
        result = ce.adjust_colors_for_gradient(colors)
        assert result is colors

    def test_adjust_colors_for_gradient_returns_five(self) -> None:
        """5 色以上采样回落到 5 色。"""
        colors = [QColor(i * 10, 0, 0) for i in range(1, 9)]
        result = ce.adjust_colors_for_gradient(colors)
        assert len(result) == 5


# ---------------------------------------------------------------------------
# 主题色生成
# ---------------------------------------------------------------------------
class TestAccentColors:
    """``generate_colors_from_accent`` 基于强调色生成。"""

    def test_returns_five_colors(self) -> None:
        """始终返回 5 个协调色。"""
        colors = ce.generate_colors_from_accent("#B036EE")
        assert len(colors) == 5

    def test_all_qcolor(self) -> None:
        """全部是 QColor 实例。"""
        assert all(isinstance(c, QColor) for c in ce.generate_colors_from_accent())

    def test_invalid_accent_falls_back_to_default(self) -> None:
        """非法 hex 回退到默认紫色并生成 5 色。"""
        colors = ce.generate_colors_from_accent("nonsense")
        assert len(colors) == 5


class TestThemeColorsForAudio:
    """``get_theme_colors_for_audio``。"""

    def test_missing_file_uses_accent(self, monkeypatch: Any) -> None:
        """文件不存在时基于强调色生成。"""
        colors = ce.get_theme_colors_for_audio("C:/no/such/file.mp3")
        assert len(colors) == 5

    def test_large_file_skips_extraction(self, monkeypatch: Any, tmp_path: Any) -> None:
        """超过 100MB 跳过封面提取。"""
        big_file = tmp_path / "huge.mp3"
        big_file.write_bytes(b"\x00" * (101 * 1024 * 1024))
        colors = ce.get_theme_colors_for_audio(str(big_file))
        assert len(colors) == 5

    def test_no_cover_uses_accent(self, monkeypatch: Any, tmp_path: Any) -> None:
        """无封面音频回退到强调色生成。"""
        empty_file = tmp_path / "no_cover.mp3"
        empty_file.write_bytes(b"\x00")
        monkeypatch.setattr(ce, "extract_cover_from_audio", lambda _path: None)
        colors = ce.get_theme_colors_for_audio(str(empty_file))
        assert len(colors) == 5


# ---------------------------------------------------------------------------
# 状态查询
# ---------------------------------------------------------------------------
class TestAvailabilityQueries:
    """Rust 可用性查询（不断言具体值，只校验类型/契约）。"""

    def test_is_rust_available_returns_bool(self) -> None:
        """返回值是布尔。"""
        assert isinstance(ce.is_rust_available(), bool)

    def test_get_extractor_version_returns_string(self) -> None:
        """版本串以实现前缀开头。"""
        version = ce.get_extractor_version()
        assert version.startswith(("Rust", "Python"))


# ---------------------------------------------------------------------------
# 模块 API 表面
# ---------------------------------------------------------------------------
class TestModuleApi:
    """导出符号完整性。"""

    def test_public_functions_exist(self) -> None:
        """关键公开函数均可调用。"""
        for name in (
            "extract_cover_colors",
            "extract_cover_colors_from_path",
            "extract_cover_from_audio",
            "generate_colors_from_accent",
            "get_theme_colors_for_audio",
            "color_distance",
            "rgb_to_hex",
            "hex_to_qcolor",
            "sort_colors_by_brightness",
            "adjust_colors_for_gradient",
            "is_rust_available",
            "get_extractor_version",
        ):
            assert callable(getattr(ce, name)), f"{name} missing"