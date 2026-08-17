# -*- coding: utf-8 -*-
"""lut_utils.py（freeassetfilter/utils/lut_utils.py）单元测试。

覆盖 CubeLUTParser 的 CUBE 解析（3D/1D、TITLE、注释与空行、数据不完整、
文件缺失、非法尺寸）、apply_to_pixel 的 3D/1D 插值与越界钳制、validate_lut_file
的扩展名/大小/损坏检查、copy/remove 生命周期（存储目录 monkeypatch 隔离，
不触碰真实 data/luts）以及 load/save/remove 设置接口（桩设置管理器）。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import pytest

from freeassetfilter.utils import lut_utils as lu
from freeassetfilter.utils.lut_utils import CubeLUTParser, LUTInfo

pytestmark = pytest.mark.unit

#: 2x2x2 3D identity LUT 文本（索引 = (z*size+y)*size+x）。
_IDENTITY_2_CUBE = """\
TITLE "Identity 2"
LUT_3D_SIZE 2
# corner data
0 0 0
1 0 0
0 1 0
1 1 0
0 0 1
1 0 1
0 1 1
1 1 1
"""

#: 3x3 1D identity LUT：R/G/B 各 3 行（每通道一份映射）。
_IDENTITY_1D_CUBE = """\
LUT_1D_SIZE 3
0 0 0
0.5 0.5 0.5
1 1 1
0 0 0
0.5 0.5 0.5
1 1 1
0 0 0
0.5 0.5 0.5
1 1 1
"""


def _write_cube(tmp_path: Any, name: str, text: str) -> str:
    """写入一个 CUBE 文件并返回路径。

    Args:
        tmp_path: pytest 临时目录。
        name: 文件名。
        text: 文件内容。

    Returns:
        str: 写入后的路径。
    """
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


class TestParse:
    """CUBE 解析。"""

    def test_parse_3d_identity(self, tmp_path: Any) -> None:
        """3D LUT 解析成功，size/is_3d/data_count 正确。"""
        parser = CubeLUTParser(_write_cube(tmp_path, "id3.cube", _IDENTITY_2_CUBE))
        assert parser.parse() is True
        info = parser.get_info()
        assert info["title"] == "Identity 2"
        assert info["size"] == 2
        assert info["is_3d"] is True
        assert info["data_count"] == 8

    def test_parse_1d_identity(self, tmp_path: Any) -> None:
        """1D LUT 解析成功，is_3d=False。"""
        parser = CubeLUTParser(_write_cube(tmp_path, "id1.cube", _IDENTITY_1D_CUBE))
        assert parser.parse() is True
        info = parser.get_info()
        assert info["size"] == 3
        assert info["is_3d"] is False
        assert info["data_count"] == 9

    def test_parse_incomplete_data_returns_false(self, tmp_path: Any) -> None:
        """数据行数不足预期 → 解析失败。"""
        path = _write_cube(
            tmp_path,
            "incomplete.cube",
            "LUT_3D_SIZE 2\n0 0 0\n1 0 0\n",
        )
        parser = CubeLUTParser(path)
        assert parser.parse() is False

    def test_parse_missing_file_returns_false(self, tmp_path: Any) -> None:
        """文件不存在 → OSError 兜底返回 False。"""
        parser = CubeLUTParser(str(tmp_path / "nope.cube"))
        assert parser.parse() is False

    def test_parse_invalid_size_returns_false(self, tmp_path: Any) -> None:
        """LUT_3D_SIZE 后跟非整数 → ValueError 兜底返回 False。"""
        path = _write_cube(tmp_path, "bad.cube", "LUT_3D_SIZE abc\n0 0 0\n")
        parser = CubeLUTParser(path)
        assert parser.parse() is False

    def test_parse_skips_comments_and_blanks(self, tmp_path: Any) -> None:
        """注释/空行被跳过，不影响头与数据解析。"""
        text = (
            "# leading comment\n\n"
            "LUT_1D_SIZE 2\n"
            "# mid comment\n"
            "0 0 0\n"
            "\n"
            "1 1 1\n"
        )
        parser = CubeLUTParser(_write_cube(tmp_path, "cmt.cube", text))
        assert parser.parse() is True
        assert parser.lut_size == 2
        assert parser.is_3d is False
        assert len(parser.data) == 2

    def test_no_data_returns_false(self, tmp_path: Any) -> None:
        """只有头没有数据 → data 不足预期返回 False。"""
        path = _write_cube(tmp_path, "nodata.cube", "LUT_3D_SIZE 2\n")
        parser = CubeLUTParser(path)
        assert parser.parse() is False


class TestApplyPixel:
    """apply_to_pixel 插值与边界。"""

    def test_apply_to_empty_data_passthrough(self) -> None:
        """无数据（未解析）→ 原样返回输入。"""
        parser = CubeLUTParser("unused.cube")
        assert parser.apply_to_pixel(0.2, 0.4, 0.6) == (0.2, 0.4, 0.6)

    def test_apply_3d_corners_exact(self, tmp_path: Any) -> None:
        """3D 角落点等值（identity）精准命中。"""
        parser = CubeLUTParser(_write_cube(tmp_path, "c.cube", _IDENTITY_2_CUBE))
        assert parser.parse() is True
        assert parser.apply_to_pixel(0.0, 0.0, 0.0) == (0.0, 0.0, 0.0)
        assert parser.apply_to_pixel(1.0, 1.0, 1.0) == (1.0, 1.0, 1.0)

    def test_apply_3d_midpoint_trilinear(self, tmp_path: Any) -> None:
        """中心点 (0.5,0.5,0.5) 三线性插值为各轴中点。"""
        parser = CubeLUTParser(_write_cube(tmp_path, "c.cube", _IDENTITY_2_CUBE))
        assert parser.parse() is True
        out = parser.apply_to_pixel(0.5, 0.5, 0.5)
        assert all(abs(v - 0.5) < 1e-9 for v in out)

    def test_apply_3d_clamps_out_of_range(self, tmp_path: Any) -> None:
        """越界输入被钳制到 [0,1]，再映射到 LUT 角落。"""
        parser = CubeLUTParser(_write_cube(tmp_path, "c.cube", _IDENTITY_2_CUBE))
        assert parser.parse() is True
        # (2.0,-1.0,0.5) → clamp → (1,0,0.5)
        out = parser.apply_to_pixel(2.0, -1.0, 0.5)
        assert abs(out[0] - 1.0) < 1e-9
        assert abs(out[1] - 0.0) < 1e-9
        assert abs(out[2] - 0.5) < 1e-9

    def test_apply_1d_interpolation(self, tmp_path: Any) -> None:
        """1D 通道分离插值。"""
        parser = CubeLUTParser(_write_cube(tmp_path, "1d.cube", _IDENTITY_1D_CUBE))
        assert parser.parse() is True
        out = parser.apply_to_pixel(0.5, 0.5, 0.5)
        assert all(abs(v - 0.5) < 1e-9 for v in out)
        out2 = parser.apply_to_pixel(0.25, 0.25, 0.25)
        assert all(abs(v - 0.25) < 1e-9 for v in out2)


class TestValidate:
    """validate_lut_file 检查。"""

    def test_missing_file(self, tmp_path: Any) -> None:
        ok, msg = lu.validate_lut_file(str(tmp_path / "gone.cube"))
        assert ok is False
        assert "文件不存在" in msg

    def test_wrong_extension(self, tmp_path: Any) -> None:
        path = _write_cube(tmp_path, "bad.txt", _IDENTITY_2_CUBE)
        ok, msg = lu.validate_lut_file(path)
        assert ok is False
        assert "仅支持.cube格式" in msg

    def test_empty_file(self, tmp_path: Any) -> None:
        path = _write_cube(tmp_path, "empty.cube", "")
        ok, msg = lu.validate_lut_file(path)
        assert ok is False
        assert "文件为空" in msg

    def test_file_too_large(self, tmp_path: Any, monkeypatch: Any) -> None:
        path = _write_cube(tmp_path, "big.cube", _IDENTITY_2_CUBE)
        monkeypatch.setattr(os.path, "getsize", lambda _p: 101 * 1024 * 1024)
        ok, msg = lu.validate_lut_file(path)
        assert ok is False
        assert "文件过大" in msg

    def test_corrupted_content(self, tmp_path: Any) -> None:
        path = _write_cube(tmp_path, "corrupt.cube", "LUT_3D_SIZE 2\n0 0 0\n")
        ok, msg = lu.validate_lut_file(path)
        assert ok is False
        assert "解析失败" in msg

    def test_valid_cube(self, tmp_path: Any) -> None:
        path = _write_cube(tmp_path, "valid.cube", _IDENTITY_2_CUBE)
        ok, msg = lu.validate_lut_file(path)
        assert ok is True
        assert msg == ""


class TestFileLifecycle:
    """copy/remove 与显示名（存储目录 monkeypatch 隔离）。"""

    def test_copy_lut_file(self, tmp_path: Any, monkeypatch: Any) -> None:
        src = _write_cube(tmp_path, "src.cube", _IDENTITY_2_CUBE)
        luts_dir = tmp_path / "luts"
        luts_dir.mkdir()
        monkeypatch.setattr(lu, "get_lut_storage_dir", lambda: str(luts_dir))
        ok, target = lu.copy_lut_file(src, lut_id="lut-123")
        assert ok is True
        assert target == os.path.join(str(luts_dir), "lut-123_src.cube")
        assert os.path.exists(target)

    def test_copy_lut_file_invalid(self, tmp_path: Any, monkeypatch: Any) -> None:
        src = _write_cube(tmp_path, "bad.cube", "LUT_3D_SIZE 2\n0 0 0\n")
        luts_dir = tmp_path / "luts"
        luts_dir.mkdir()
        monkeypatch.setattr(lu, "get_lut_storage_dir", lambda: str(luts_dir))
        ok, msg = lu.copy_lut_file(src)
        assert ok is False
        assert "验证失败" in msg or "解析失败" in msg

    def test_remove_lut_file(self, tmp_path: Any) -> None:
        path = _write_cube(tmp_path, "del.cube", _IDENTITY_2_CUBE)
        assert lu.remove_lut_file(path) is True
        assert not os.path.exists(path)
        # 删除不存在的文件不报错
        assert lu.remove_lut_file(str(tmp_path / "gone.cube")) is True

    def test_get_lut_display_name(self) -> None:
        uuid_name = "550e8400-e29b-41d4-a716-446655440000_MyLUT"
        assert lu.get_lut_display_name(uuid_name) == "MyLUT"
        assert lu.get_lut_display_name("MyLUT.cube") == "MyLUT"
        assert lu.get_lut_display_name("abc_123") == "abc_123"
        assert lu.get_lut_display_name("") == ""


class TestSettingsInterface:
    """load/save/remove 设置接口（桩设置管理器）。"""

    class _FakeSettings:
        def __init__(self) -> None:
            self.data: Dict[str, Any] = {}

        def get_setting(self, key: str, default: Any = None) -> Any:
            return self.data.get(key, default)

        def set_setting(self, key: str, value: Any) -> None:
            self.data[key] = value

        def save_settings(self) -> None:
            pass

    def _make_info(self, lut_id: str, name: str) -> LUTInfo:
        return LUTInfo(
            id=lut_id,
            name=name,
            path=f"path/{lut_id}.cube",
            preview_path="",
            size=2,
            is_3d=True,
        )

    def test_load_empty_settings(self) -> None:
        sm = self._FakeSettings()
        assert lu.load_lut_from_settings(sm) == []

    def test_save_then_load(self) -> None:
        sm = self._FakeSettings()
        info = self._make_info("a", "LUT A")
        lu.save_lut_to_settings(sm, info)
        loaded = lu.load_lut_from_settings(sm)
        assert len(loaded) == 1
        assert loaded[0].id == "a"
        assert loaded[0].name == "LUT A"

    def test_save_same_id_updates_not_duplicates(self) -> None:
        sm = self._FakeSettings()
        lu.save_lut_to_settings(sm, self._make_info("a", "LUT A"))
        lu.save_lut_to_settings(sm, self._make_info("a", "LUT A2"))
        loaded = lu.load_lut_from_settings(sm)
        assert len(loaded) == 1
        assert loaded[0].name == "LUT A2"

    def test_remove_lut(self) -> None:
        sm = self._FakeSettings()
        lu.save_lut_to_settings(sm, self._make_info("a", "LUT A"))
        lu.remove_lut_from_settings(sm, "a")
        assert lu.load_lut_from_settings(sm) == []

    def test_remove_active_lut_clears_active_id(self) -> None:
        sm = self._FakeSettings()
        lu.save_lut_to_settings(sm, self._make_info("a", "LUT A"))
        sm.set_setting("video.active_lut_id", "a")
        lu.remove_lut_from_settings(sm, "a")
        assert sm.get_setting("video.active_lut_id") is None

    def test_remove_missing_lut_is_noop(self) -> None:
        sm = self._FakeSettings()
        lu.save_lut_to_settings(sm, self._make_info("a", "LUT A"))
        lu.remove_lut_from_settings(sm, "not-exist")
        assert len(lu.load_lut_from_settings(sm)) == 1


class TestPreviewDir:
    """get_lut_preview_dir：返回 data/lut_previews 目录（mkidr 隔离）。"""

    def test_returns_lut_previews_str(self, monkeypatch: Any, tmp_path: Any) -> None:
        """返回 data/lut_previews 目录路径；mkdir 打桩避免触碰真实 data/。"""
        from pathlib import Path as _Path

        # 打桩 Path.mkdir：验证逻辑不落盘，不污染仓库 data/
        real_path_cls = type(_Path())
        calls: list[Any] = []

        class _NoMkdirPath(real_path_cls):  # type: ignore[misc]
            def mkdir(self, *args: Any, **kwargs: Any) -> None:
                calls.append((args, kwargs))

        monkeypatch.setattr(lu, "Path", _NoMkdirPath)
        result = lu.get_lut_preview_dir()
        assert isinstance(result, str)
        assert "lut_previews" in result
        assert calls  # mkdir 确实被调用（打桩捕获）