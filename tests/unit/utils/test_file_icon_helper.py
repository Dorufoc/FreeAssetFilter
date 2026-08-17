# -*- coding: utf-8 -*-
"""file_icon_helper.py（freeassetfilter/utils/file_icon_helper.py）单元测试。

覆盖 ``get_file_icon_path`` 的全类型后缀→图标名映射、未知后缀回退、
目录分支、大写后缀归一化；以及 ``get_icon_path`` 的样式后缀解析（
``ICON_STYLE_SUFFIX``）、样式图标缺失回退与无效样式值兜底。
SettingsManager 读取通过 monkeypatch 替换为桩类，绝不触碰真实设置。
"""

from __future__ import annotations

import os
from typing import Any

import pytest

import freeassetfilter.utils.file_icon_helper as fih

pytestmark = pytest.mark.unit


def _patch_settings(monkeypatch: Any, icon_style: int) -> None:
    """把模块内的 SettingsManager 换成只返回固定 icon_style 的桩类。

    Args:
        monkeypatch: pytest 的 monkeypatch 夹具。
        icon_style: 固定的图标样式值。
    """

    class _FakeSettings:
        def get_setting(self, key: str, default: Any = None) -> Any:
            if key == "appearance.icon_style":
                return icon_style
            return default

    monkeypatch.setattr(fih, "SettingsManager", _FakeSettings)


class TestGetFileIconPath:
    """文件信息 → 图标路径映射。"""

    def test_directory_uses_folder_icon(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        """is_dir=True → 文件夹图标。"""
        _patch_settings(monkeypatch, 0)
        info = {"is_dir": True, "suffix": ""}
        path = fih.get_file_icon_path(info, str(tmp_path))
        assert path == os.path.join(str(tmp_path), "文件夹.svg")

    @pytest.mark.parametrize(
        "suffix, expect_icon",
        [
            # 视频
            ("mp4", "视频"),
            ("mov", "视频"),
            ("mkv", "视频"),
            ("mxf", "视频"),
            # 图像
            ("jpg", "图像"),
            ("png", "图像"),
            ("svg", "图像"),
            ("dng", "图像"),
            # 音频
            ("mp3", "音乐"),
            ("wav", "音乐"),
            # 字体
            ("ttf", "字体"),
            ("otf", "字体"),
            # 压缩包
            ("zip", "压缩文件"),
            ("7z", "压缩文件"),
            # 文档
            ("pdf", "PDF"),
            ("ppt", "PPT"),
            ("pptx", "PPT"),
            ("xls", "表格"),
            ("xlsx", "表格"),
            ("doc", "Word文档"),
            ("docx", "Word文档"),
            ("txt", "文档"),
            ("md", "文档"),
            # 未知后缀 → 回退
            ("crazy_unknown_ext", "未知底板"),
            ("", "未知底板"),
        ],
    )
    def test_suffix_mapping(
        self,
        monkeypatch: Any,
        tmp_path: Any,
        suffix: str,
        expect_icon: str,
    ) -> None:
        """各已知后缀映射到正确图标名；未知后缀回退未知底板。"""
        _patch_settings(monkeypatch, 0)
        info = {"is_dir": False, "suffix": suffix}
        path = fih.get_file_icon_path(info, str(tmp_path))
        assert path == os.path.join(str(tmp_path), f"{expect_icon}.svg")

    def test_uppercase_suffix_lowered(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        """大写后缀被统一为小写后参与映射。"""
        _patch_settings(monkeypatch, 0)
        path = fih.get_file_icon_path(
            {"is_dir": False, "suffix": "PDF"}, str(tmp_path)
        )
        assert path == os.path.join(str(tmp_path), "PDF.svg")

    def test_empty_dict_falls_back_to_unknown(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        """空字典（无 is_dir/suffix）→ 未知底板，不崩溃。"""
        _patch_settings(monkeypatch, 0)
        path = fih.get_file_icon_path({}, str(tmp_path))
        assert path == os.path.join(str(tmp_path), "未知底板.svg")

    def test_none_input_documents_contract(self, tmp_path: Any) -> None:
        """None 输入违反契约（要求 dict）：记录为 AttributeError 而不静默吞掉。

        目标函数对 ``file_info.get`` 的调用决定了 None 输入必然抛
        AttributeError——测试忠实记录这一契约，避免"假装不崩溃"。
        """
        with pytest.raises(AttributeError):
            fih.get_file_icon_path(None, str(tmp_path))


class TestGetIconPath:
    """图标名 → 路径解析与样式后缀。"""

    def test_non_styleable_icon_ignores_style(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        """非 STYLEABLE_ICONS 成员不被追加样式后缀。"""
        _patch_settings(monkeypatch, 3)
        path = fih.get_icon_path("自定义图标", str(tmp_path))
        assert path == os.path.join(str(tmp_path), "自定义图标.svg")

    def test_styleable_icon_uses_style_suffix(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        """样式图标文件存在 → 返回带样式后缀的路径。"""
        _patch_settings(monkeypatch, 3)
        icon_dir = tmp_path / "style3"
        icon_dir.mkdir()
        (icon_dir / "视频 – 3.svg").write_text("<svg/>", encoding="utf-8")
        path = fih.get_icon_path("视频", str(icon_dir))
        assert path == str(icon_dir / "视频 – 3.svg")

    def test_style_icon_missing_falls_back_default(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        """样式图标缺失 → 回退无后缀默认图标。"""
        _patch_settings(monkeypatch, 3)
        icon_dir = tmp_path / "fallback"
        icon_dir.mkdir()
        (icon_dir / "视频.svg").write_text("<svg/>", encoding="utf-8")
        path = fih.get_icon_path("视频", str(icon_dir))
        assert path == str(icon_dir / "视频.svg")

    def test_invalid_style_value_falls_back_flat(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        """设置值为非法整数 → 兜底为扁平样式（无后缀）。"""
        _patch_settings(monkeypatch, 42)
        assert fih.get_icon_path("视频", str(tmp_path)).endswith("视频.svg")

    def test_style_value_exception_falls_back_flat(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        """读取设置抛异常（ValueError）→ 兜底为扁平样式。"""
        class _BrokenSettings:
            def get_setting(self, *args: Any, **kwargs: Any) -> Any:
                raise ValueError("boom")

        monkeypatch.setattr(fih, "SettingsManager", _BrokenSettings)
        assert fih.get_icon_path("视频", str(tmp_path)).endswith("视频.svg")

    def test_missing_icon_name_no_crash(self, tmp_path: Any) -> None:
        """图标文件不存在也返回期望路径（由调用方决定显隐）。"""
        path = fih.get_icon_path("不存在的图标", str(tmp_path))
        assert path == os.path.join(str(tmp_path), "不存在的图标.svg")