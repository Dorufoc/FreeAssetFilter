"""源图像透明通道嗅探。

缩略图主线一直把结果编码成 JPEG（``THUMB_EXT_PRIMARY = '.jpg'``），而 JPEG 没有
alpha 通道，于是 SVG / PNG / WebP / GIF / ICO 这类带透明背景的素材在卡片上会被
压成一块黑底或白底。要保住透明通道就得改输出格式，但「改格式」只应发生在**真的
有 alpha** 的文件上：PNG 编码比 JPEG 慢一个量级，无差别切换会拖慢批量生成。

本模块只做**头部嗅探**（读几十字节到几 KB），不做解码，因此可以在生成前对每个
文件都跑一遍：

* PNG —— IHDR 的 color type 为 4/6 直接判定；0/2/3 需要继续找 ``tRNS`` 块；
* WebP —— ``VP8X`` 的 alpha 标志位，或 ``VP8L`` 无损头里的 alpha 位；
* GIF —— 扫描首个图形控制扩展（``0x21 0xF9``）的透明标志；
* ICO/CUR/ICNS —— 图标本身按带 alpha 处理（体积小、PNG 编码开销可忽略）；
* SVG —— 矢量渲染天然带 alpha；
* TGA —— 仅 32 位像素深度才有 alpha。

判定为「可能带 alpha」不等于「这一张真的用了透明」：PNG color type 6 也可能全
不透明。为避免给全不透明的图白付 PNG 编码成本，调用方在写完像素后还会做一次
``alpha_is_opaque`` 快速检查，必要时回退 JPEG。
"""

from __future__ import annotations

import os

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_TRNS_SCAN_BYTES = 512 * 1024
_GIF_TRNS_SCAN_BYTES = 256 * 1024

#: 扩展名 → 是否需要检查透明通道。
ALPHA_SOURCE_SUFFIXES: frozenset[str] = frozenset(
    {".svg", ".png", ".webp", ".gif", ".ico", ".cur", ".icns", ".tga"}
)


def _read_head(path: str, size: int) -> bytes:
    """读取文件头部 ``size`` 字节；失败返回空字节串。"""
    try:
        with open(path, "rb") as handle:
            return handle.read(size)
    except OSError:
        return b""


def _png_has_trns(path: str) -> bool:
    """扫描 PNG 块链，判断 IDAT 之前是否存在 ``tRNS`` 块。

    ``tRNS`` 为调色板或灰度/真彩图像声明透明色，出现即代表有透明像素。
    """
    try:
        with open(path, "rb") as handle:
            handle.seek(8)
            scanned = 8
            while scanned < _PNG_TRNS_SCAN_BYTES:
                header = handle.read(8)
                if len(header) < 8:
                    return False
                length = int.from_bytes(header[:4], "big")
                chunk_type = header[4:8]
                if chunk_type in (b"IDAT", b"IEND"):
                    return False
                if chunk_type == b"tRNS":
                    return True
                if length < 0 or length > _PNG_TRNS_SCAN_BYTES:
                    return False
                handle.seek(length + 4, os.SEEK_CUR)
                scanned += 8 + length + 4
    except OSError:
        return False
    return False


def _png_has_alpha(path: str) -> bool:
    head = _read_head(path, 26)
    if len(head) < 26 or not head.startswith(_PNG_SIGNATURE):
        return False
    if head[12:16] != b"IHDR":
        return False
    color_type = head[25]
    if color_type in (4, 6):
        return True
    if color_type in (0, 2, 3):
        return _png_has_trns(path)
    return False


def _webp_has_alpha(path: str) -> bool:
    head = _read_head(path, 32)
    if len(head) < 30 or head[0:4] != b"RIFF" or head[8:12] != b"WEBP":
        return False
    chunk = head[12:16]
    if chunk == b"VP8X":
        # VP8X 标志字节位于扩展块头第 1 字节：bit4 = alpha。
        return bool(head[20] & 0x10)
    if chunk == b"VP8L":
        # 无损头位流（从载荷第 2 字节起按 LSB 打包）：
        #   14 bit 宽-1、14 bit 高-1、1 bit alpha_is_used、3 bit 版本。
        # alpha 位 = 第 8+14+14 = 28 位 → 从偏移 21 起的 32 位小端字的
        # 第 28 位 → 文件偏移 24 的 bit4。
        if head[20] != 0x2F:
            return False
        return bool(head[24] & 0x10)
    if chunk == b"VP8 ":
        return False
    # 其它（如 ANIM/ANMF 包装）无法从头部判定，保守按无 alpha 处理。
    return False


def _gif_has_alpha(path: str) -> bool:
    """扫描 GIF 图形控制扩展的透明标志。"""
    try:
        with open(path, "rb") as handle:
            data = handle.read(_GIF_TRNS_SCAN_BYTES)
    except OSError:
        return False
    if len(data) < 13 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return False
    index = data.find(b"\x21\xf9\x04", 13)
    while index >= 0 and index + 4 < len(data):
        packed = data[index + 3]
        if packed & 0x01:
            return True
        index = data.find(b"\x21\xf9\x04", index + 4)
    return False


def _ico_has_alpha(path: str) -> bool:
    """ICO/CUR 一律视为带 alpha：位图条目可能用 32 位 alpha 或 AND 掩码。"""
    head = _read_head(path, 6)
    return len(head) >= 6 and head[:4] in (b"\x00\x00\x01\x00", b"\x00\x00\x02\x00")


def _icns_has_alpha(path: str) -> bool:
    head = _read_head(path, 4)
    return head == b"icns"


def _tga_has_alpha(path: str) -> bool:
    """TGA 只有 32 位像素深度才带 alpha。"""
    head = _read_head(path, 18)
    if len(head) < 18:
        return False
    return head[16] == 32


def has_alpha_source(file_path: str, suffix: str | None = None) -> bool:
    """判断源文件是否可能带透明通道。

    Args:
        file_path: 源文件绝对路径。
        suffix: 预取的小写扩展名（含点）；省略时从 ``file_path`` 解析。

    Returns:
        bool: True 表示需要按 alpha 输出（PNG）；False 表示走既有 JPEG 主线。
    """
    ext = suffix if suffix is not None else os.path.splitext(file_path)[1].lower()
    if ext not in ALPHA_SOURCE_SUFFIXES:
        return False
    if ext == ".svg":
        return True
    if ext == ".png":
        return _png_has_alpha(file_path)
    if ext == ".webp":
        return _webp_has_alpha(file_path)
    if ext == ".gif":
        return _gif_has_alpha(file_path)
    if ext in (".ico", ".cur"):
        return _ico_has_alpha(file_path)
    if ext == ".icns":
        return _icns_has_alpha(file_path)
    if ext == ".tga":
        return _tga_has_alpha(file_path)
    return False
