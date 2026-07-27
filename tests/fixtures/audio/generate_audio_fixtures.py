# -*- coding: utf-8 -*-
"""Audio fixture generator for the music previewer layout.

Creates three minimal MP3 files inside ``tests/fixtures/audio``:

- ``with_cover.mp3``: ID3 tags and an embedded PNG cover image.
- ``no_cover.mp3``: ID3 tags but no cover image.
- ``no_tags.mp3``: raw MPEG-1 Layer III frames without any metadata.

The MP3 streams are generated programmatically as silence, so no copyrighted
audio is used. If ``mutagen`` is not installed, only the raw frames are written
and the README explains how to install ``mutagen`` for full metadata fixtures.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Any, Dict, Optional

MUTAGEN_AVAILABLE = False
try:
    from mutagen.mp3 import MP3
    from mutagen.id3 import APIC, TALB, TIT2, TPE1

    MUTAGEN_AVAILABLE = True
except Exception:  # pragma: no cover - mutagen is an optional dependency.
    pass

_THIS_DIR = Path(__file__).resolve().parent

# Valid MPEG-1 Layer III frame header:
# - sync word 0x7FF, version 1, layer 3
# - 128 kbps, 44.1 kHz, stereo, no padding/protection bits.
_FRAME_HEADER = bytes.fromhex("FFFB9000")
_FRAME_LENGTH = 417
_NUM_FRAMES = 60


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """Build a PNG chunk with length, type, data, and CRC."""
    chunk = chunk_type + data
    crc = zlib.crc32(chunk) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk + struct.pack(">I", crc)


def _png_bytes(
    width: int = 4,
    height: int = 4,
    rgb: tuple[int, int, int] = (220, 60, 60),
) -> bytes:
    """Return a minimal valid RGB PNG without external dependencies."""
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")

    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes(rgb) * width
    idat_data = zlib.compress(row * height)

    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr_data)
        + _png_chunk(b"IDAT", idat_data)
        + _png_chunk(b"IEND", b"")
    )


def _silent_mp3_bytes(num_frames: int = _NUM_FRAMES) -> bytes:
    """Create valid silent-ish MPEG-1 Layer III frame data.

    A single 128 kbps / 44.1 kHz stereo frame is 417 bytes. Repeating the
    header followed by zeroed payload produces a stream that MPV, mutagen and
    most decoders accept as a playable MP3.
    """
    payload_length = _FRAME_LENGTH - len(_FRAME_HEADER)
    frame = _FRAME_HEADER + b"\x00" * payload_length
    return frame * num_frames


def _write_id3_tags(
    path: Path,
    tags: Optional[Dict[str, Any]] = None,
    cover: Optional[bytes] = None,
) -> None:
    """Embed ID3 tags and optional cover art when mutagen is available."""
    if not MUTAGEN_AVAILABLE or tags is None:
        return

    audio = MP3(str(path))
    if audio.tags is None:
        audio.add_tags()

    if tags.get("title"):
        audio.tags["TIT2"] = TIT2(encoding=3, text=tags["title"])
    if tags.get("artist"):
        audio.tags["TPE1"] = TPE1(encoding=3, text=tags["artist"])
    if tags.get("album"):
        audio.tags["TALB"] = TALB(encoding=3, text=tags["album"])
    if cover:
        audio.tags["APIC"] = APIC(
            encoding=3,
            mime="image/png",
            type=3,
            desc="cover",
            data=cover,
        )

    audio.save()


def generate_fixture(
    name: str,
    tags: Optional[Dict[str, Any]] = None,
    cover: Optional[bytes] = None,
) -> Path:
    """Write a fixture file and optionally tag it."""
    _THIS_DIR.mkdir(parents=True, exist_ok=True)
    path = _THIS_DIR / name
    path.write_bytes(_silent_mp3_bytes())
    _write_id3_tags(path, tags=tags, cover=cover)
    return path


def _write_readme() -> None:
    """Explain the fixtures and how to enable full metadata generation."""
    lines = [
        "# 音频测试样本",
        "",
        "该目录包含通过 ``generate_audio_fixtures.py`` 生成的无版权静音 MP3 文件：",
        "",
        "- ``with_cover.mp3``：包含 ID3 标题/艺术家/专辑以及一张内嵌 PNG 封面。",
        "- ``no_cover.mp3``：包含 ID3 标题/艺术家/专辑，但没有封面。",
        "- ``no_tags.mp3``：没有任何 ID3 标签的原始 MPEG 帧。",
        "",
        f"mutagen 可用：{MUTAGEN_AVAILABLE}",
        "",
        "如果 ``mutagen`` 未安装，fixtures 仅包含原始 MP3 帧；UI 的元数据读取测试会优雅降级。",
        "要启用完整标签生成，请安装：",
        "",
        "```bash",
        "pip install mutagen",
        "python tests/fixtures/audio/generate_audio_fixtures.py",
        "```",
        "",
    ]
    (_THIS_DIR / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    """Generate the three audio fixture files."""
    cover = _png_bytes(8, 8, (220, 60, 60))

    paths = [
        generate_fixture(
            "with_cover.mp3",
            tags={
                "title": "测试曲目",
                "artist": "测试艺术家",
                "album": "测试专辑",
            },
            cover=cover,
        ),
        generate_fixture(
            "no_cover.mp3",
            tags={
                "title": "无封面测试",
                "artist": "未知艺术家",
                "album": "Demo",
            },
        ),
        generate_fixture("no_tags.mp3"),
    ]

    _write_readme()

    print(f"mutagen available: {MUTAGEN_AVAILABLE}")
    for path in paths:
        print(f"generated: {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
