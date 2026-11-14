"""文件卡片的后缀 → 类型标签映射。"""

from __future__ import annotations

import pytest

from sopeek.ui.components.file_card_delegate import _get_file_type_display


pytestmark = pytest.mark.unit


def test_directory_label() -> None:
    assert _get_file_type_display("", is_dir=True) == "文件夹"


def test_missing_suffix_label() -> None:
    assert _get_file_type_display("") == "文件"


@pytest.mark.parametrize(
    ("suffix", "expected"),
    [
        ("jpg", "JPEG 图像"),
        ("JPG", "JPEG 图像"),
        ("py", "Python 源文件"),
        ("pdf", "PDF 文档"),
        ("mp4", "MP4 视频"),
        ("7z", "7z 压缩文件"),
        ("ttf", "TTF 字体"),
    ],
)
def test_known_suffixes_are_mapped(suffix: str, expected: str) -> None:
    assert _get_file_type_display(suffix) == expected


def test_ts_is_described_as_video() -> None:
    """.ts 同时是 TypeScript 与 MPEG-TS；映射表里只登记视频（历史行为）。"""
    assert _get_file_type_display("ts") == "TS 视频"


def test_unknown_suffix_falls_back_to_upper() -> None:
    assert _get_file_type_display("qqq") == "QQQ 文件"
