# -*- coding: utf-8 -*-
"""``MediaMetadataService`` 单元测试（todo-13 unit/services 批2）。

覆盖：真实最小 WAV/MP3/FLAC 样本的元数据解析（mutagen 可用时）、
缺失/损坏文件的无异常回退、mock mutagen 分支（封面魔术字节扫描、
ID3 frame 折叠、APIC 键提取）以及格式化工具函数边界。

策略：
* 真实样本只构造**最小合法文件头**（WAV RIFF、MP3 两帧、FLAC fLaC+STREAMINFO），
  不依赖仓库内任何音频资源；
* mutagen 缺失时真实样本测试 skip，mock 分支无条件可跑；
* 所有临时文件使用 ``tmp_path``，不触碰生产代码。
"""

from __future__ import annotations

import importlib.util
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pytest

_MMS = "freeassetfilter.services.media_metadata_service"

pytestmark = pytest.mark.unit

#: mutagen 是否安装（真实样本测试的跳转开关）。
_MUTAGEN_INSTALLED: bool = importlib.util.find_spec("mutagen") is not None

#: 一张最小 PNG 的字节内容（用作 APIC 封面）。
_PNG_BYTES: bytes = (
    b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00\x00\x00\x01"
    + b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0c"
    + b"IDAT\x08\xd7c\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01" + b"4\x8f\x88"
    + b"\x7d\x00\x00\x00\x00IEND\xaeB`\x82"
)


# ── 最小合法媒体文件构造 ─────────────────────────────────────────────────


def _make_wav(path: Union[str, Path], seconds: float = 1.0, sample_rate: int = 8000) -> str:
    """构造一个 8-bit PCM 的沉默 WAV 文件（可被 mutagen 解析）。

    Args:
        path: 输出路径（``.wav``）。
        seconds: 时长秒数。
        sample_rate: 采样率 Hz。

    Returns:
        str: 生成后的文件路径。
    """
    out: Path = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    data: bytes = b"\x80" * int(seconds * sample_rate)
    fmt_chunk: bytes = struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate, 1, 8)
    fmt_body: bytes = b"fmt " + fmt_chunk
    data_chunk: bytes = b"data" + struct.pack("<I", len(data)) + data
    riff: bytes = (
        b"RIFF" + struct.pack("<I", 4 + len(fmt_body) + len(data_chunk)) + b"WAVE"
        + fmt_body + data_chunk
    )
    out.write_bytes(riff)
    return str(out)


def _make_mp3(
    path: Union[str, Path],
    add_id3: bool = False,
    cover: Optional[bytes] = None,
) -> str:
    """构造一个含两个 MPEG-1 Layer III 帧的最小 MP3 文件。

    Args:
        path: 输出路径（``.mp3``）。
        add_id3: 是否写入 ID3 标签（TIT2/TPE1/TALB）。
        cover: 非 ``None`` 时同时写入 APIC 封面帧。

    Returns:
        str: 生成后的文件路径。

    Raises:
        ImportError: mutagen 未安装时。
    """
    out: Path = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame_len: int = (144 * 128000) // 44100  # 417 字节（128kbps / 44100Hz）
    frame: bytes = b"\xff\xfb\x90\x00" + b"\x00" * (frame_len - 4)
    out.write_bytes(frame * 2)

    if add_id3 or cover is not None:
        from mutagen import File as mutagen_file
        from mutagen.id3 import APIC, TALB, TIT2, TPE1

        audio = mutagen_file(str(out))
        if audio is None or audio.tags is None:
            audio.add_tags()
        audio.tags.add(TIT2(encoding=3, text="测试歌曲"))
        audio.tags.add(TPE1(encoding=3, text="测试歌手"))
        audio.tags.add(TALB(encoding=3, text="测试专辑"))
        if cover is not None:
            audio.tags.add(
                APIC(encoding=3, mime="image/png", type=3, desc="cover", data=cover)
            )
        audio.save()
    return str(out)


def _make_flac(path: Union[str, Path], sample_rate: int = 44100) -> str:
    """构造一个 fLaC + STREAMINFO + 空 VorbisComment 的最小 FLAC 文件。

    Args:
        path: 输出路径（``.flac``）。
        sample_rate: STREAMINFO 中写入的采样率。

    Returns:
        str: 生成后的文件路径。
    """
    out: Path = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    streaminfo: bytes = struct.pack(">HH", 4096, 4096) + b"\x00\x00\x00" + b"\x00\x00\x00"
    field: int = (sample_rate << 44) | (1 << 41) | (16 << 36) | sample_rate
    streaminfo += struct.pack(">Q", field) + b"\x00" * 16  # MD5 全零
    body: bytes = b"fLaC" + bytes([0x80]) + struct.pack(">I", 34)[1:] + streaminfo
    vorbis: bytes = b"\x03vorbis" + struct.pack("<I", 0) * 3
    body += bytes([0x00]) + struct.pack(">I", len(vorbis))[1:] + vorbis
    out.write_bytes(body)
    return str(out)


# ── 假对象（mock mutagen 分支用） ─────────────────────────────────────────


class _FakeFrame:
    """模拟 ID3 / Vorbis frame 对象：既带 ``data`` 又带 ``text``。"""

    def __init__(self, data: Optional[bytes] = None, text: Optional[List[str]] = None) -> None:
        """初始化假 frame。

        Args:
            data: 二进制负载（封面用）。
            text: 文本列表（ID3 ``.text`` 风格）。
        """
        self.data: Optional[bytes] = data
        self.text: Optional[List[str]] = text


class _FakeAudio:
    """模拟 ``mutagen.File`` 的返回值。"""

    def __init__(self, tags: Optional[Dict[str, Any]] = None) -> None:
        """初始化假音频对象。

        Args:
            tags: 标签容器（dict 风格）。
        """
        self.tags: Optional[Dict[str, Any]] = tags


def _fake_mutagen_file(audio: _FakeAudio):
    """返回一个忽略路径参数、恒返回 *audio* 的假 ``mutagen.File``。"""

    def _loader(_file_path: str) -> _FakeAudio:
        return audio

    return _loader


# ── 真实样本测试（mutagen 可用） ──────────────────────────────────────────


@pytest.mark.skipif(not _MUTAGEN_INSTALLED, reason="mutagen 未安装，跳过真实音频样本测试")
class TestRealMediaFiles:
    """基于最小合法 WAV/MP3/FLAC 文件的真实解析测试。"""

    def test_extract_basic_info_wav_reads_audio_metadata(self, tmp_path: Path) -> None:
        """happy：真实 WAV 应解析出时长/声道/采样率/大小。

        Args:
            tmp_path: pytest 临时目录。
        """
        path: str = _make_wav(tmp_path / "song.wav", seconds=2.0)
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        svc = MediaMetadataService()
        info: Dict[str, Any] = svc.extract_basic_info(path)
        assert info["extension"] == "wav"
        assert info["file_size"] > 0
        assert abs(float(info["duration"]) - 2.0) < 0.1
        assert info["channels"] == 1
        assert info["sample_rate"] == 8000

    def test_extract_basic_info_mp3_reads_bitrate(self, tmp_path: Path) -> None:
        """happy：真实 MP3 应解析出比特率 128kbps 与 44.1kHz。

        Args:
            tmp_path: pytest 临时目录。
        """
        path: str = _make_mp3(tmp_path / "song.mp3")
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        svc = MediaMetadataService()
        info: Dict[str, Any] = svc.extract_basic_info(path)
        assert info["bitrate"] == 128000
        assert info["sample_rate"] == 44100
        assert info["channels"] == 2
        assert float(info["duration"]) > 0

    def test_extract_basic_info_flac_reads_streaminfo(self, tmp_path: Path) -> None:
        """happy：真实 FLAC 应解析出 STREAMINFO 中的时长/声道/采样率。

        Args:
            tmp_path: pytest 临时目录。
        """
        path: str = _make_flac(tmp_path / "song.flac")
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        svc = MediaMetadataService()
        info: Dict[str, Any] = svc.extract_basic_info(path)
        assert info["extension"] == "flac"
        assert abs(float(info["duration"]) - 1.0) < 0.1
        assert info["channels"] == 2
        assert info["sample_rate"] == 44100

    def test_extract_audio_tags_maps_id3_fields(self, tmp_path: Path) -> None:
        """happy：真实 MP3 ID3 标签应映射到 title/artist/album。

        Args:
            tmp_path: pytest 临时目录。
        """
        path: str = _make_mp3(tmp_path / "tagged.mp3", add_id3=True)
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        svc = MediaMetadataService()
        tags: Dict[str, Any] = svc.extract_audio_tags(path)
        assert tags is not None
        assert tags["title"] == "测试歌曲"
        assert tags["artist"] == "测试歌手"
        assert tags["album"] == "测试专辑"

    def test_extract_audio_cover_returns_apic_image(self, tmp_path: Path) -> None:
        """happy：真实 MP3 的 APIC 封面应返回 PNG 字节。

        Args:
            tmp_path: pytest 临时目录。
        """
        path: str = _make_mp3(tmp_path / "cover.mp3", cover=_PNG_BYTES)
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        svc = MediaMetadataService()
        cover: Optional[bytes] = svc.extract_audio_cover(path)
        assert cover is not None
        assert cover[:4] == b"\x89PNG"

    def test_extract_audio_cover_wav_without_tags_returns_none(self, tmp_path: Path) -> None:
        """boundary：无标签的 WAV 应返回 None 而非抛出。

        Args:
            tmp_path: pytest 临时目录。
        """
        path: str = _make_wav(tmp_path / "plain.wav")
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        svc = MediaMetadataService()
        assert svc.extract_audio_cover(path) is None


# ── 缺失 / 损坏文件回退（不依赖 mutagen 分支真假） ────────────────────────


class TestMissingAndCorruptFallback:
    """文件缺失 / 损坏时的无异常回退测试。"""

    def test_extract_basic_info_missing_file_returns_path_info(self, tmp_path: Path) -> None:
        """boundary：文件不存在时只返回基础路径信息。

        Args:
            tmp_path: pytest 临时目录。
        """
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        svc = MediaMetadataService()
        missing: str = str(tmp_path / "ghost.mp3")
        info: Dict[str, Any] = svc.extract_basic_info(missing)
        assert info["file_name"] == "ghost.mp3"
        assert info["file_path"] == missing
        assert "file_size" not in info
        assert "is_dir" not in info

    def test_extract_audio_tags_missing_file_returns_none(self, tmp_path: Path) -> None:
        """error：不存在文件的标签解析返回 None，绝不抛出。

        Args:
            tmp_path: pytest 临时目录。
        """
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        svc = MediaMetadataService()
        assert svc.extract_audio_tags(str(tmp_path / "ghost.mp3")) is None
        assert svc.extract_audio_cover(str(tmp_path / "ghost.mp3")) is None

    def test_extract_basic_info_directory_skips_media_parse(self, tmp_path: Path) -> None:
        """boundary：目录输入只返回目录元数据，不触发 mutagen 解析。

        Args:
            tmp_path: pytest 临时目录。
        """
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        svc = MediaMetadataService()
        info: Dict[str, Any] = svc.extract_basic_info(str(tmp_path))
        assert info["is_dir"] is True
        assert "duration" not in info

    def test_extract_audio_tags_corrupt_file_returns_empty_schema(self, tmp_path: Path) -> None:
        """error：损坏的音频文件返回空 schema 而非异常。

        Args:
            tmp_path: pytest 临时目录。
        """
        bad: Path = tmp_path / "broken.wav"
        bad.write_bytes(b"\x00NOT-A-REAL-WAV\xff\xff")
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        svc = MediaMetadataService()
        tags: Optional[Dict[str, Any]] = svc.extract_audio_tags(str(bad))
        assert tags is not None
        assert tags["title"] == ""
        assert tags["cover_data"] is None
        assert svc.extract_audio_cover(str(bad)) is None


# ── mock mutagen 分支（覆盖键映射 / 封面扫描 / 降级） ─────────────────────


class TestMockedMutagen:
    """通过 monkeypatch ``mutagen_file`` 覆盖无需真实文件的分支。"""

    def test_vorbis_comment_keys_mapped(self, monkeypatch: Any, tmp_path: Path) -> None:
        """happy：Vorbis Comment 键（TITLE/ARTIST/ALBUM）应正确映射。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        dummy: Path = tmp_path / "dummy.wav"
        dummy.write_bytes(b"x")
        fake_audio: _FakeAudio = _FakeAudio(
            tags={"TITLE": "标题", "ARTIST": "艺术家", "ALBUM": "专辑名"}
        )
        monkeypatch.setattr(_MMS + ".mutagen_file", _fake_mutagen_file(fake_audio))
        svc = MediaMetadataService()
        tags: Dict[str, Any] = svc.extract_audio_tags(str(dummy))
        assert tags["title"] == "标题"
        assert tags["artist"] == "艺术家"
        assert tags["album"] == "专辑名"

    def test_mp4_unicode_keys_mapped(self, monkeypatch: Any, tmp_path: Path) -> None:
        """happy：MP4 的 ``\\u00a9nam`` 等 Unicode 键应映射到字段。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        dummy: Path = tmp_path / "dummy.m4a"
        dummy.write_bytes(b"x")
        fake_audio: _FakeAudio = _FakeAudio(
            tags={"\u00a9nam": "曲名", "\u00a9ART": "演唱者", "\u00a9alb": "唱片"}
        )
        monkeypatch.setattr(_MMS + ".mutagen_file", _fake_mutagen_file(fake_audio))
        svc = MediaMetadataService()
        tags: Dict[str, Any] = svc.extract_audio_tags(str(dummy))
        assert tags["title"] == "曲名"
        assert tags["artist"] == "演唱者"
        assert tags["album"] == "唱片"

    def test_id3_frame_text_list_collapsed(self, monkeypatch: Any, tmp_path: Path) -> None:
        """happy：ID3 frame 的 ``text`` 列表应被折叠为逗号分隔字符串。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        dummy: Path = tmp_path / "dummy.mp3"
        dummy.write_bytes(b"x")
        frame: _FakeFrame = _FakeFrame(text=["甲", "乙"])
        fake_audio: _FakeAudio = _FakeAudio(tags={"TPE1": frame})
        monkeypatch.setattr(_MMS + ".mutagen_file", _fake_mutagen_file(fake_audio))
        svc = MediaMetadataService()
        tags: Dict[str, Any] = svc.extract_audio_tags(str(dummy))
        assert tags["artist"] == "甲, 乙"

    def test_cover_extracted_from_apic_key(self, monkeypatch: Any, tmp_path: Path) -> None:
        """happy：``APIC:`` 键的 frame ``.data`` 应作为封面返回。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        dummy: Path = tmp_path / "dummy.mp3"
        dummy.write_bytes(b"x")
        fake_audio: _FakeAudio = _FakeAudio(
            tags={"APIC:": _FakeFrame(data=_PNG_BYTES)}
        )
        monkeypatch.setattr(_MMS + ".mutagen_file", _fake_mutagen_file(fake_audio))
        svc = MediaMetadataService()
        cover: Optional[bytes] = svc.extract_audio_cover(str(dummy))
        assert cover is not None
        assert cover == _PNG_BYTES

    def test_cover_extracted_via_magic_bytes_scan(self, monkeypatch: Any, tmp_path: Path) -> None:
        """happy：任意键的 ``.data`` 命中 JPEG 魔术字节时应作为封面返回。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        dummy: Path = tmp_path / "dummy.mp3"
        dummy.write_bytes(b"x")
        jpeg: bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 32
        fake_audio: _FakeAudio = _FakeAudio(
            tags={"MISC": _FakeFrame(data=jpeg)}
        )
        monkeypatch.setattr(_MMS + ".mutagen_file", _fake_mutagen_file(fake_audio))
        svc = MediaMetadataService()
        cover: Optional[bytes] = svc.extract_audio_cover(str(dummy))
        assert cover == jpeg

    def test_cover_none_when_tags_have_no_image(self, monkeypatch: Any, tmp_path: Path) -> None:
        """error：无图像数据的标签应返回 None，不抛出。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        dummy: Path = tmp_path / "dummy.mp3"
        dummy.write_bytes(b"x")
        fake_audio: _FakeAudio = _FakeAudio(
            tags={"COMM": _FakeFrame(data=b"plain text, not an image")}
        )
        monkeypatch.setattr(_MMS + ".mutagen_file", _fake_mutagen_file(fake_audio))
        svc = MediaMetadataService()
        assert svc.extract_audio_cover(str(dummy)) is None

    def test_mutagen_disabled_degrades_gracefully(self, monkeypatch: Any, tmp_path: Path) -> None:
        """boundary：mutagen 缺失（``None``）时全部 API 应安全降级。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        dummy: Path = tmp_path / "dummy.mp3"
        dummy.write_bytes(b"x")
        monkeypatch.setattr(_MMS + ".mutagen_file", None)
        svc = MediaMetadataService()
        assert svc.extract_audio_cover(str(dummy)) is None
        tags: Optional[Dict[str, Any]] = svc.extract_audio_tags(str(dummy))
        assert tags is not None
        assert tags == {"title": "", "artist": "", "album": "", "cover_data": None}
        info: Dict[str, Any] = svc.extract_basic_info(str(dummy))
        assert info["file_size"] == 1
        assert "duration" not in info


# ── 格式化 / 工具函数边界 ─────────────────────────────────────────────────


class TestFormatHelpers:
    """静态格式化工具函数的单位 / 负值边界测试。"""

    def test_format_size_units(self) -> None:
        """happy：``_format_size`` 按 1024 进制选择单位。"""
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        assert MediaMetadataService._format_size(0) == "0.0 B"
        assert MediaMetadataService._format_size(2048) == "2.0 KB"
        assert MediaMetadataService._format_size(3 * 1024 * 1024) == "3.0 MB"

    def test_format_size_negative(self) -> None:
        """error：负值返回占位文案而非异常。"""
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        assert MediaMetadataService._format_size(-1) == "无法获取"

    def test_format_duration_formats(self) -> None:
        """happy：``_format_duration`` 输出 MM:SS / HH:MM:SS。"""
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        assert MediaMetadataService._format_duration(65.0) == "01:05"
        assert MediaMetadataService._format_duration(3661.0) == "01:01:01"

    def test_format_duration_negative(self) -> None:
        """error：负时长返回占位文案。"""
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        assert MediaMetadataService._format_duration(-0.5) == "无法获取"

    def test_format_bitrate_units(self) -> None:
        """happy：``_format_bitrate`` 输出 bps / Kbps / Mbps。"""
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        assert MediaMetadataService._format_bitrate(500) == "500 bps"
        assert MediaMetadataService._format_bitrate(128000) == "128.0 Kbps"
        assert MediaMetadataService._format_bitrate(5_000_000) == "5.0 Mbps"

    def test_looks_like_image_magic_bytes(self) -> None:
        """happy：JPEG / PNG / BMP 魔术字节被识别，纯文本被拒绝。"""
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        assert MediaMetadataService._looks_like_image(b"\xff\xd8\xff\xe0rest")
        assert MediaMetadataService._looks_like_image(b"\x89PNG rest")
        assert MediaMetadataService._looks_like_image(b"BM rest")
        assert not MediaMetadataService._looks_like_image(b"text, not image")


# ── 生命周期冒烟 ─────────────────────────────────────────────────────────


class TestLifecycle:
    """``BaseService`` 生命周期与实例化冒烟。"""

    def test_initialize_and_dispose_idempotent(self) -> None:
        """happy：initialize/dispose 可重复调用且互不干扰。"""
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        svc = MediaMetadataService()
        assert svc.initialize() is True
        assert svc.initialize() is True
        assert svc.is_initialized is True
        svc.dispose()
        assert svc.is_initialized is False
        assert svc.initialize() is True  # 可再次初始化

    def test_extract_returns_before_initialize(self, tmp_path: Path) -> None:
        """boundary：未 initialize 也可提取基础信息（无资源依赖）。"""
        from freeassetfilter.services.media_metadata_service import MediaMetadataService

        svc = MediaMetadataService()
        path: str = _make_wav(tmp_path / "w.wav")
        assert svc.extract_basic_info(path)["file_size"] > 0


__all__: Tuple[str, ...] = ()