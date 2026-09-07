# -*- coding: utf-8 -*-
"""file_icon_helper.py（freeassetfilter/utils/file_icon_helper.py）单元测试。

产品仅保留一套多彩 v3 图标（文件名为 ``X – 3.svg``），不再存在图标样式
选择能力。本测试覆盖：

- ``get_file_icon_path`` 的全类型后缀→图标名映射、未知后缀回退、目录分支、
  大写后缀归一化；
- 固定解析规则：类型图标一律返回 ``X – 3.svg``；
- v3 图标缺失时的无后缀兜底（防御性）与路径返回值契约。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

import freeassetfilter.utils.file_icon_helper as fih

pytestmark = pytest.mark.unit


class TestGetFileIconPath:
    """文件信息 → 图标路径映射（固定 v3 后缀）。"""

    def test_directory_uses_folder_icon(self, tmp_path: Path) -> None:
        """is_dir=True → 文件夹 v3 图标。"""
        info = {"is_dir": True, "suffix": ""}
        path = fih.get_file_icon_path(info, str(tmp_path))
        assert path == os.path.join(str(tmp_path), "文件夹 – 3.svg")

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
    def test_suffix_mapping_uses_v3_icon(
        self, tmp_path: Path, suffix: str, expect_icon: str
    ) -> None:
        """各已知后缀映射到对应 v3 图标名；未知后缀回退未知底板 v3。"""
        info = {"is_dir": False, "suffix": suffix}
        path = fih.get_file_icon_path(info, str(tmp_path))
        assert path == os.path.join(str(tmp_path), f"{expect_icon} – 3.svg")

    def test_uppercase_suffix_lowered(self, tmp_path: Path) -> None:
        """大写后缀被统一为小写后参与映射。"""
        path = fih.get_file_icon_path(
            {"is_dir": False, "suffix": "PDF"}, str(tmp_path)
        )
        assert path == os.path.join(str(tmp_path), "PDF – 3.svg")

    def test_empty_dict_falls_back_to_unknown(self, tmp_path: Path) -> None:
        """空字典（无 is_dir/suffix）→ 未知底板 v3，不崩溃。"""
        path = fih.get_file_icon_path({}, str(tmp_path))
        assert path == os.path.join(str(tmp_path), "未知底板 – 3.svg")

    def test_none_input_documents_contract(self, tmp_path: Path) -> None:
        """None 输入违反契约（要求 dict）：记录为 AttributeError 而不静默吞掉。

        目标函数对 ``file_info.get`` 的调用决定了 None 输入必然抛
        AttributeError——测试忠实记录这一契约，避免"假装不崩溃"。
        """
        with pytest.raises(AttributeError):
            fih.get_file_icon_path(None, str(tmp_path))

    def test_real_icons_resolve_to_v3_files(self) -> None:
        """boundary：真实 icons 目录下每个类型都应命中现存 v3 文件。

        防止代码回退到无后缀（已删除的）路径仍能"工作"而无人察觉。
        """
        icon_dir = os.path.normpath(
            os.path.join(os.path.dirname(fih.__file__), "..", "icons")
        )
        assert os.path.isdir(icon_dir)
        probe = {
            "文件夹": {"is_dir": True, "suffix": ""},
            "视频": {"is_dir": False, "suffix": "mp4"},
            "图像": {"is_dir": False, "suffix": "png"},
            "音乐": {"is_dir": False, "suffix": "mp3"},
            "字体": {"is_dir": False, "suffix": "ttf"},
            "压缩文件": {"is_dir": False, "suffix": "zip"},
            "PDF": {"is_dir": False, "suffix": "pdf"},
            "PPT": {"is_dir": False, "suffix": "pptx"},
            "表格": {"is_dir": False, "suffix": "xlsx"},
            "Word文档": {"is_dir": False, "suffix": "docx"},
            "文档": {"is_dir": False, "suffix": "md"},
            "未知底板": {"is_dir": False, "suffix": "zzz"},
        }
        for icon_name, info in probe.items():
            path = fih.get_file_icon_path(info, icon_dir)
            assert os.path.exists(path), f"{icon_name} 图标缺失: {path}"
            assert path.endswith(f"{icon_name} – 3.svg"), path


class TestV3Fallback:
    """v3 图标缺失时的防御性兜底。"""

    def test_missing_v3_falls_back_to_plain(
        self, tmp_path: Path
    ) -> None:
        """boundary：目录中只有无后缀图标时回退到该文件。"""
        (tmp_path / "视频.svg").write_text("<svg/>", encoding="utf-8")
        path = fih.get_file_icon_path({"is_dir": False, "suffix": "mp4"}, str(tmp_path))
        assert path == os.path.join(str(tmp_path), "视频.svg")

    def test_no_icon_at_all_returns_v3_path(self, tmp_path: Path) -> None:
        """boundary：两个文件都不存在时返回 v3 路径（由调用方决定显隐）。"""
        path = fih.get_file_icon_path({"is_dir": False, "suffix": "mp4"}, str(tmp_path))
        assert path == os.path.join(str(tmp_path), "视频 – 3.svg")
