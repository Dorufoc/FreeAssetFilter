# -*- coding: utf-8 -*-
"""极简 MJPEG-AVI 写入器（无 ffmpeg 编码器时的兜底）。"""

from __future__ import annotations

import io
import struct
from pathlib import Path


def _chunk(fourcc: bytes, payload: bytes) -> bytes:
    data = payload + (b"\x00" if len(payload) % 2 else b"")
    return fourcc + struct.pack("<I", len(payload)) + data


def write_mjpeg_avi(path: Path, frames: list[bytes], width: int, height: int, fps: int = 12) -> None:
    """把一组 JPEG 帧写成无索引的 MJPEG AVI。"""
    n = len(frames)
    avih = struct.pack(
        "<IIIIIIIIII4I",
        int(1_000_000 / fps),  # dwMicroSecPerFrame
        width * height * 3 * fps,  # dwMaxBytesPerSec
        0,
        0x10,  # AVIF_HASINDEX
        n,
        0,
        1,
        max(len(f) for f in frames),
        width,
        height,
        0, 0, 0, 0,
    )
    strh = (
        b"vids"
        + b"MJPG"
        + struct.pack("<IHHIIIIIIII4h", 0, 0, 0, 0, 1, fps, 0, n, max(len(f) for f in frames), 10000, 0, 0, 0, width, height)
    )
    strf = struct.pack(
        "<IiiHH4sIiiII",
        40, width, height, 1, 24, b"MJPG", width * height * 3, 0, 0, 0, 0,
    )
    strl = b"LIST" + struct.pack("<I", 4 + 8 + len(strh) + 8 + len(strf)) + b"strl" + _chunk(b"strh", strh) + _chunk(b"strf", strf)
    hdrl = b"LIST" + struct.pack("<I", 4 + 8 + len(avih) + len(strl)) + b"hdrl" + _chunk(b"avih", avih) + strl

    movi_payload = b""
    index = b""
    for frame in frames:
        index += struct.pack("<4sIII", b"00dc", 0x10, len(movi_payload) + 4, len(frame))
        movi_payload += _chunk(b"00dc", frame)
    movi = b"LIST" + struct.pack("<I", 4 + len(movi_payload)) + b"movi" + movi_payload
    idx1 = _chunk(b"idx1", index)

    body = b"AVI " + hdrl + movi + idx1
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)


def make_frames(width: int = 1280, height: int = 720, count: int = 72, fps: int = 12) -> list[bytes]:
    from PIL import Image, ImageDraw
    import math

    frames: list[bytes] = []
    for i in range(count):
        t = i / (count - 1)
        img = Image.new("RGB", (width, height), (8, 12, 20))
        d = ImageDraw.Draw(img)
        for band in range(7):
            base = 110 + band * 62
            pts = []
            for x in range(0, width + 1, 32):
                y = base + 58 * (0.5 + 0.5 * math.sin(x / 240 + t * 6.2 + band * 0.8))
                pts.append((x, y))
            color = (36 + band * 22, 132 + band * 14, 148 + band * 15)
            d.line(pts, fill=color, width=24)
        cx, cy = int(width * (0.18 + 0.64 * t)), int(height * 0.26)
        d.ellipse([cx - 70, cy - 70, cx + 70, cy + 70], fill=(238, 245, 255))
        d.text((56, height - 90), "Sopeek 极光演示", fill=(226, 236, 250))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82)
        frames.append(buf.getvalue())
    return frames
