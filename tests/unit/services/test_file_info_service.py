# -*- coding: utf-8 -*-
"""file_info_service 单元测试（todo-23 批 4 / task-23）。

覆盖：格式化工具、类型分类、stat 基础信息、各类型轻量行采集、
详细信息采集（图片/文本/压缩包详情使用打桩或真实样本）、
三哈希计算与中断、缓存读写与陈旧失效。全部使用临时目录，不触碰仓库数据。

验证命令：
    python -m pytest tests/unit/services/test_file_info_service.py --timeout 60 -q
"""

# targets: freeassetfilter.services.file_info_service

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

from freeassetfilter.services import file_info_service as fis


pytestmark = pytest.mark.unit


# =============================================================================
# 格式化与分类
# =============================================================================
class TestFormatHelpers:
    """格式化工具：size/duration/bitrate/画面标签。"""

    def test_format_size(self) -> None:
        assert fis.format_size(0) == "0 B"
        assert fis.format_size(1023) == "1023 B"
        assert fis.format_size(1536) == "1.5 KB"
        assert fis.format_size(-1) == fis.UNAVAILABLE

    def test_format_duration(self) -> None:
        assert fis.format_duration(0) == "00:00"
        assert fis.format_duration(59.9) == "00:59"
        assert fis.format_duration(3661) == "01:01:01"
        assert fis.format_duration(-3) == fis.UNAVAILABLE

    def test_format_bitrate(self) -> None:
        assert fis.format_bitrate(999) == "999 bps"
        assert fis.format_bitrate(128000) == "128.0 Kbps"
        assert fis.format_bitrate(8_000_000) == "8.0 Mbps"
        assert fis.format_bitrate(-1) == fis.UNAVAILABLE

    def test_resolution_label_and_join(self) -> None:
        assert fis._p_label(1920, 1080) == "1080p"
        assert fis._p_label(1280, 1024) == "1280×1024"
        assert fis._format_fps(60.0) == "60 fps"
        assert fis._format_fps(29.97) == "29.97 fps"
        assert fis._join("1080p", "60 fps", "8.2 Mbps") == "1080p · 60 fps · 8.2 Mbps"
        assert fis._join(None, fis.UNAVAILABLE, "A") == "A"


class TestClassifySuffix:
    """后缀分类。"""

    @pytest.mark.parametrize(
        "suffix,expected",
        [
            ("png", ("图片", "PNG")),
            ("JPG", ("图片", "JPG")),
            ("cr2", ("图片", "CR2")),
            ("svg", ("图片", "SVG")),
            ("mp4", ("视频", "MP4")),
            ("flac", ("音频", "FLAC")),
            ("pdf", ("PDF 文档", "PDF")),
            ("py", ("文本/代码", "PY")),
            ("zip", ("压缩包", "ZIP")),
            ("ttf", ("字体", "TTF")),
            ("docx", ("Office 文档", "DOCX")),
            ("", ("文件", "")),
            ("noidea", ("文件", "NOIDEA")),
        ],
    )
    def test_common_types(self, suffix: str, expected: tuple[str, str]) -> None:
        assert fis.classify_suffix(suffix) == expected


# =============================================================================
# stat 基础信息
# =============================================================================
class TestStatBasic:
    """stat_basic：存在/缺失/目录安全。"""

    def test_existing_file(self, temp_file: str) -> None:
        info = fis.stat_basic(temp_file)
        assert info["name"] == Path(temp_file).name
        assert info["path"] == temp_file
        assert info["size"] > 0
        assert info["modified"] != fis.UNAVAILABLE
        assert info["created"] != fis.UNAVAILABLE
        assert len(info["modified"]) == 16  # %Y-%m-%d %H:%M

    def test_missing_file_returns_placeholders(self, tmp_path: Path) -> None:
        missing = str(tmp_path / "not_exist.bin")
        info = fis.stat_basic(missing)
        assert info["name"] == "not_exist.bin"
        assert info["size_str"] == fis.UNAVAILABLE
        assert info["modified"] == fis.UNAVAILABLE
        assert info["created"] == fis.UNAVAILABLE


# =============================================================================
# 轻量行采集
# =============================================================================
def _info_dict(path: str, suffix: Optional[str] = None) -> dict:
    suffix = suffix or Path(path).suffix.lstrip(".")
    return {
        "name": Path(path).name,
        "path": path,
        "is_dir": False,
        "size": os.path.getsize(path) if os.path.exists(path) else 0,
        "suffix": suffix,
    }


class TestLightRows:
    """各类型的「选中即展示」行。"""

    def test_image_png(self, sample_image_file: str) -> None:
        rows = dict(fis.collect_light_rows(_info_dict(sample_image_file)))
        assert rows["类别"] == "PNG 图片"
        assert "格式" not in rows  # 已并入「类别」
        assert rows["尺寸"] == "240 × 160"
        assert rows["大小"] != fis.UNAVAILABLE
        assert set(rows).issuperset({"修改时间", "创建时间"})

    def test_svg(self, sample_svg_file: str) -> None:
        rows = dict(fis.collect_light_rows(_info_dict(sample_svg_file)))
        assert rows["类别"] == "SVG 图片"
        assert "格式" not in rows
        assert rows["尺寸"] == "120 × 80"

    def test_text_encoding(self, sample_text_file: str) -> None:
        rows = dict(fis.collect_light_rows(_info_dict(sample_text_file)))
        ext = Path(sample_text_file).suffix.lstrip(".").upper()
        assert rows["类别"] == f"{ext} 文本/代码"
        assert rows["编码格式"].lower() in ("utf-8", "ascii", "utf-8-sig")

    def test_archive_detected_by_signature(self, sample_zip_file: str) -> None:
        rows = dict(fis.collect_light_rows(_info_dict(sample_zip_file)))
        ext = Path(sample_zip_file).suffix.lstrip(".").upper()
        assert rows["类别"] == f"{ext} 压缩包"
        assert rows["压缩格式"] == "ZIP"

    def test_archive_falls_back_to_extension(self, tmp_path: Path) -> None:
        fake = tmp_path / "fake.7z"
        fake.write_bytes(b"not really a 7z archive")
        rows = dict(fis.collect_light_rows(_info_dict(str(fake))))
        assert rows["压缩格式"] == "7Z"

    def test_font_names(self, sample_font_file: Optional[str]) -> None:
        if sample_font_file is None:
            pytest.skip("系统字体不可用")
        if importlib.util.find_spec("fontTools") is None:
            pytest.skip("fontTools 未安装")
        rows = dict(fis.collect_light_rows(_info_dict(sample_font_file)))
        assert rows["类别"].endswith("字体")
        assert any(key in rows for key in ("字体名称", "全名", "PostScript 名称"))

    def test_missing_file_is_safe(self) -> None:
        rows = fis.collect_light_rows(_info_dict("C:/no/such/file.mp3"))
        labels = [label for label, _ in rows]
        assert labels[0] == "类别"
        assert labels[1] == "大小"

    def test_directory(self, sample_dir: str) -> None:
        rows = dict(fis.collect_light_rows({**_info_dict(sample_dir), "is_dir": True}))
        assert rows == {"类别": "文件夹"}


# =============================================================================
# 详细信息采集
# =============================================================================
class TestDetailData:
    """详细信息：图片 / 文本 / 压缩包（打桩 7z） / 字体。"""

    def test_image_rows_and_no_exif(self, sample_image_file: str) -> None:
        data = fis.collect_detail_data(sample_image_file)
        assert dict(data["rows"]) == {"色彩模式": "RGB", "位深": "24 bit"}
        assert data["exif_common"] == []
        assert data["exif_more"] == []

    def test_pdf_returns_empty(self, sample_pdf_file: str) -> None:
        assert fis.collect_detail_data(sample_pdf_file) == {
            "rows": [], "exif_common": [], "exif_more": []
        }

    def test_text_counts(self, sample_text_file: str) -> None:
        data = fis.collect_detail_data(sample_text_file)
        values = dict(data["rows"])
        assert "字符数" in values
        assert "行数" in values
        assert "单词数" in values

    def test_text_huge_skips_counts(self, tmp_path: Path) -> None:
        big = tmp_path / "big.txt"
        big.write_text("x" * (fis._TEXT_EXT_COUNTS_THRESHOLD + 1024), encoding="utf-8")
        values = dict(fis.collect_detail_data(str(big))["rows"])
        assert "字符数" not in values

    def test_archive_detail_with_stubbed_7z(self, sample_zip_file: str) -> None:
        def _fake_list_archive(path, current_path="", encoding="utf-8"):
            assert path == sample_zip_file
            return [
                {"name": "hello.txt", "is_dir": False, "size": 21},
                {"name": "subdir/data.json", "is_dir": False, "size": 9},
            ]

        with patch(
            "freeassetfilter.core.native.bridges.py7z_core.list_archive",
            side_effect=_fake_list_archive,
        ):
            values = dict(fis.collect_detail_data(sample_zip_file)["rows"])
        assert values["内部文件数"] == "2"
        assert values["解压总大小"] == "30 B"
        assert "压缩率" in values

    def test_font_detail(self, sample_font_file: Optional[str]) -> None:
        if sample_font_file is None:
            pytest.skip("系统字体不可用")
        if importlib.util.find_spec("fontTools") is None:
            pytest.skip("fontTools 未安装")
        values = dict(fis.collect_detail_data(sample_font_file)["rows"])
        assert "字体格式" in values
        assert "字形数" in values

    def test_missing_path(self) -> None:
        assert fis.collect_detail_data("C:/no/file.png") == {
            "rows": [], "exif_common": [], "exif_more": []
        }


# =============================================================================
# 哈希
# =============================================================================
class TestHashes:
    """三哈希正确性与中断。"""

    def test_matches_reference(self, temp_file: str) -> None:
        raw = Path(temp_file).read_bytes()
        expected = {
            "MD5": hashlib.md5(raw).hexdigest(),  # noqa: S324
            "SHA1": hashlib.sha1(raw).hexdigest(),  # noqa: S324
            "SHA256": hashlib.sha256(raw).hexdigest(),
        }
        assert fis.compute_hashes(temp_file) == expected

    def test_missing_file_placeholders(self) -> None:
        assert fis.compute_hashes("C:/no/file.bin") == {
            "MD5": fis.UNAVAILABLE, "SHA1": fis.UNAVAILABLE, "SHA256": fis.UNAVAILABLE,
        }

    def test_interruption_returns_partial(self, temp_file: str) -> None:
        cancelled = False

        def _stop() -> bool:
            return cancelled

        cancelled = True
        values = fis.compute_hashes(temp_file, should_stop=_stop)
        assert len(values["SHA256"]) == 64


# =============================================================================
# 缓存
# =============================================================================
class TestCache:
    """缓存读写 / 指纹失效 / 版本守卫。"""

    def test_roundtrip_and_stale_invalidation(self, temp_file: str, tmp_path: Path) -> None:
        cache_file = str(tmp_path / "fic.json")
        path = temp_file
        assert fis.read_cached(path, cache_path=cache_file) is None

        fis.write_cached(path, details=[("a", "1")], hashes={"MD5": "x"}, cache_path=cache_file)
        entry = fis.read_cached(path, cache_path=cache_file)
        assert entry is not None
        assert entry["details"] == [["a", "1"]]
        assert entry["hashes"] == {"MD5": "x"}

        # mtime 变化 → 失效
        time.sleep(0.01)
        st = os.stat(path)
        os.utime(path, (st.st_atime, st.st_mtime + 2))
        assert fis.read_cached(path, cache_path=cache_file) is None

    def test_size_change_invalidates(self, tmp_path: Path) -> None:
        cache_file = str(tmp_path / "fic.json")
        path = str(tmp_path / "size.bin")
        path_obj = Path(path)
        path_obj.write_bytes(b"12345")
        fis.write_cached(path, details=[], hashes={}, cache_path=cache_file)
        path_obj.write_bytes(b"1234567890")
        assert fis.read_cached(path, cache_path=cache_file) is None

    def test_old_version_store_ignored(self, temp_file: str, tmp_path: Path) -> None:
        cache_file = Path(tmp_path / "fic.json")
        cache_file.write_text(
            json.dumps({"version": 1, "files": {}}, ensure_ascii=False), encoding="utf-8"
        )
        assert fis.read_cached(temp_file, cache_path=str(cache_file)) is None

    def test_write_is_atomic_and_readable(self, temp_file: str, tmp_path: Path) -> None:
        cache_file = str(tmp_path / "fic.json")
        fis.write_cached(temp_file, details=[("行数", "3")], cache_path=cache_file)
        with open(cache_file, encoding="utf-8") as f:
            store = json.load(f)
        assert store["version"] == 2
        assert ".tmp" not in os.listdir(tmp_path)
