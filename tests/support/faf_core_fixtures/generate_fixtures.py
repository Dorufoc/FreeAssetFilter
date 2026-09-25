# -*- coding: utf-8 -*-
"""faf_core_fixtures 生成脚本（rust-hot-path-native-migration todo 5）。

在 ``tests/support/faf_core_fixtures/`` 下新建 6 组对拍夹具，全部确定性
生成（固定 seed / 固定参数），单文件 <512KB，供后续 EXIF/PSD/SVG/fluid/
7z/PDF 的 native-vs-Python 对拍与回退测试使用：

- ``exif_samples/``     JPEG EXIF：含 GPS / 多值标签 / 损坏（截断字节）
- ``psd_samples/``      PSD：图层 + 蒙版 + 混合模式 / 损坏（截断字节）
- ``svg_samples/``      18 条换色正则会中样本 + 无命中样本
- ``fluid_samples/``    固定 seed/time 参考帧（Python 侧渲染存 RGBA md5）
- ``seven_zip_samples/`` 7z ``-slt`` 输出文本样本（UTF-8 与 GBK 两套编码）
- ``pdf_samples/``      多页多词 PDF（fitz 生成）

用法：``python tests/support/faf_core_fixtures/generate_fixtures.py``

依赖仓库既有库：Pillow / psd-tools / PyMuPDF(fitz) / exifread；fluid 参考
帧需要 QApplication（脚本内部以 offscreen 平台创建）。

注意：本脚本位于测试目录内，不属于产品代码，不会触碰 ``freeassetfilter/``。
"""

from __future__ import annotations

import hashlib
import io
import os
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

# 项目根目录入 sys.path（保证裸执行也能解析 freeassetfilter/）。
_PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# _styled_fluid_cpu.py 内部 `from components._styled_fluid_math import ...`
# 使用裸顶层包名，需把 freeassetfilter/ui 加入 sys.path（与既有 fluid 测试一致）。
_UI_ROOT: str = str(_PROJECT_ROOT / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

# fluid 参考帧渲染需要 offscreen 平台（无真实显示器）。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_FIXTURES_DIR: Path = Path(__file__).resolve().parent

#: 单文件大小上限（验收标准）。
_MAX_BYTES: int = 512 * 1024


def _write_bytes(rel_path: str, data: bytes) -> Path:
    """把字节写入夹具目录下的相对路径并返回绝对路径。

    Args:
        rel_path: 相对 ``faf_core_fixtures/`` 的子路径。
        data: 文件内容字节。

    Returns:
        Path: 写入后的绝对路径。
    """
    target: Path = _FIXTURES_DIR / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _write_text(rel_path: str, text: str, encoding: str = "utf-8") -> Path:
    """把文本写入夹具目录下的相对路径（指定编码）并返回绝对路径。

    Args:
        rel_path: 相对 ``faf_core_fixtures/`` 的子路径。
        text: 文本内容。
        encoding: 写入编码（GBK 样本用 gbk）。

    Returns:
        Path: 写入后的绝对路径。
    """
    return _write_bytes(rel_path, text.encode(encoding))


def _make_exif_samples() -> List[str]:
    """生成 EXIF 夹具组（GPS / 多值 / 损坏）。

    用 PIL 现写 JPEG EXIF：0th IFD 平铺常见标签 + GPS IFD 引用坐标
    （多值 rational 组）+ 一个多值 FNumber。损坏样本取完好样本字节
    并在 EXIF TIFF 中部截断。

    Returns:
        list[str]: 生成的文件名列表。
    """
    from PIL import Image

    def build_jpeg() -> bytes:
        image: Image.Image = Image.new("RGB", (120, 80), (200, 40, 60))
        exif: Image.Exif = Image.Exif()
        exif[0x010F] = "TestMaker"               # Image Make
        exif[0x0110] = "TestModel"               # Image Model
        exif[0x0132] = "2026:09:05 10:11:12"      # Image DateTime
        exif[0x9003] = "2026:09:05 10:11:12"      # Image DateTimeOriginal
        exif[0x8827] = 400                        # Image ISOSpeedRatings
        exif[0x829D] = (28, 10)                   # Image FNumber（多值 rational）
        gps: Dict[int, object] = exif.get_ifd(0x8825)
        gps[1] = "N"                              # GPS GPSLatitudeRef
        gps[2] = (37.0, 0.0, 0.0)                # GPS GPSLatitude（多值）
        gps[3] = "E"                              # GPS GPSLongitudeRef
        gps[4] = (122.0, 0.0, 0.0)               # GPS GPSLongitude（多值）
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", exif=exif)
        return buffer.getvalue()

    good: bytes = build_jpeg()
    _write_bytes("exif_samples/sample_gps_multivalue.jpg", good)

    # 损坏样本：从 EXIF APP1 段（Exif\0\0）起截断，保证破坏 TIFF 结构。
    exif_marker: bytes = b"Exif\x00\x00"
    pos: int = good.find(exif_marker)
    cut_at: int = (pos + 190) if pos >= 0 else int(len(good) * 0.45)
    _write_bytes("exif_samples/sample_corrupt.jpg", good[:cut_at])

    # 标准 EXIF 样本（无 GPS/多值），供 rest 字段平铺对拍。
    image: Image.Image = Image.new("RGB", (96, 64), (60, 120, 200))
    exif_std: Image.Exif = Image.Exif()
    exif_std[0x010F] = "Canon"
    exif_std[0x0110] = "EOS Standard"
    exif_std[0x0131] = "SampleSoftware 1.0"
    exif_std[0x0132] = "2026-09-05 09:00:00"
    exif_std[0x9003] = "2026-09-05 09:00:00"
    exif_std[0x8827] = 200
    exif_std[0x0112] = 6                          # Orientation
    exif_std[0x0100] = 96                          # ImageWidth
    exif_std[0x0101] = 64                          # ImageLength
    buffer_std = io.BytesIO()
    image.save(buffer_std, "JPEG", exif=exif_std)
    _write_bytes("exif_samples/sample_standard.jpg", buffer_std.getvalue())

    return ["sample_gps_multivalue.jpg", "sample_standard.jpg", "sample_corrupt.jpg"]


def _make_psd_samples() -> List[str]:
    """生成 PSD 夹具组（图层 / 蒙版 / 混合模式 / 损坏）。

    用 psd-tools 构造 RGB 64x48 PSD：底层纯色 + multiply 混合模式图层
    （psd-tools 对有透明度的图层自动生成蒙版）+ 普通混合图层。损坏样本
    取完好 PSD 字节在 40% 处截断。

    Returns:
        list[str]: 生成的文件名列表。
    """
    from PIL import Image
    from psd_tools.api.psd_image import PSDImage
    from psd_tools.constants import BlendMode

    base: PSDImage = PSDImage.new(mode="RGB", size=(64, 48), color=(255, 0, 0))

    multiply_img: Image.Image = Image.new("RGBA", (64, 48), (0, 255, 0, 128))
    layer_multiply = base.create_pixel_layer(multiply_img)
    layer_multiply.blend_mode = BlendMode.MULTIPLY
    layer_multiply.name = "multiply_green"
    # psd-tools 对带透明度的图层自动创建蒙版（has_mask() == True）。

    normal_img: Image.Image = Image.new("RGBA", (64, 48), (80, 80, 200, 200))
    layer_normal = base.create_pixel_layer(normal_img)
    layer_normal.name = "normal_blue"

    base.append(layer_multiply)
    base.append(layer_normal)

    buffer = io.BytesIO()
    base.save(buffer)
    good: bytes = buffer.getvalue()
    _write_bytes("psd_samples/sample_layers_blend_mask.psd", good)
    _write_bytes("psd_samples/sample_corrupt.psd", good[: int(len(good) * 0.4)])

    return ["sample_layers_blend_mask.psd", "sample_corrupt.psd"]


#: 18 条换色正则的来源模块路径（校验用）。
_SVG_REGEX_MODULE: str = "freeassetfilter.core.preview.svg_renderer"

_SVG_HIT_ALL: str = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" width="220" height="220">\n'
    '  <rect width="220" height="220" fill="#111111"/>\n'
    '  <path d="M10 10h30v30z" stroke="#cecece"/>\n'
    '  <rect x="60" y="10" width="20" height="20" stroke="#FFFFFF"/>\n'
    '  <rect x="100" y="10" width="20" height="20" stroke="#FFF"/>\n'
    '  <rect x="140" y="10" width="20" height="20" stroke="#000000"/>\n'
    '  <rect x="180" y="10" width="20" height="20" stroke="#000"/>\n'
    '  <rect x="10" y="60" width="20" height="20" fill="#FFFFFF"/>\n'
    '  <rect x="60" y="60" width="20" height="20" fill="#FFF"/>\n'
    '  <rect x="100" y="60" width="20" height="20" fill="#000000"/>\n'
    '  <rect x="140" y="60" width="20" height="20" fill="#000"/>\n'
    '  <path d="M180 60l20 20v-20z" style="fill: #FFFFFF"/>\n'
    '  <path d="M10 110l20 20v-20z" style="fill: #FFF"/>\n'
    '  <path d="M60 110l20 20v-20z" style="fill: #000000"/>\n'
    '  <path d="M100 110l20 20v-20z" style="fill: #000"/>\n'
    '  <circle cx="180" cy="130" r="15" fill="#0a59f7"/>\n'
    '  <rect x="10" y="160" width="20" height="20" stroke="#cecece"/>\n'
    '  <rect x="60" y="160" width="20" height="20" fill="#cecece"/>\n'
    '  <path d="M100 160l20 20v-20z" style="fill: #cecece"/>\n'
    '  <path d="M140 160l20 20v-20z" style="stroke: #cecece"/>\n'
    "</svg>\n"
)

_SVG_HIT_SHORT_UPPER: str = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120">\n'
    '  <path d="M0 0h20v20z" STROKE="#FFFFFF"/>\n'
    '  <rect FILL="#FFF"/>\n'
    '  <rect stroke="#000"/>\n'
    '  <rect fill="#FFFFFF"/>\n'
    '  <path style="fill: #000"/>\n'
    '  <circle fill="#0A59F7"/>\n'
    '  <rect stroke="#CECECE"/>\n'
    "</svg>\n"
)

_SVG_NO_MATCH: str = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120">\n'
    '  <rect width="120" height="120" fill="#123456"/>\n'
    '  <circle cx="60" cy="60" r="30" stroke="#abcdef" stroke-width="2" fill="none"/>\n'
    '  <path d="M0 0l20 20v20z" fill="#010101"/>\n'
    '  <path d="M30 30l20 20v20z" style="fill: #ffeedd" fill="none"/>\n'
    '  <path d="M60 60l20 20v20z" style="stroke: #fedcba" fill="none"/>\n'
    '  <text x="10" y="110" fill="#808080">no match</text>\n'
    "</svg>\n"
)


def _make_svg_samples() -> List[str]:
    """生成 SVG 夹具组（18 条换色正则命中 + 无命中）。

    Returns:
        list[str]: 生成的文件名列表。
    """
    _write_text("svg_samples/sample_hit_all.svg", _SVG_HIT_ALL)
    _write_text("svg_samples/sample_hit_short_upper.svg", _SVG_HIT_SHORT_UPPER)
    _write_text("svg_samples/sample_no_match.svg", _SVG_NO_MATCH)
    return ["sample_hit_all.svg", "sample_hit_short_upper.svg", "sample_no_match.svg"]


def _md5(data: bytes) -> str:
    """计算字节串的 md5 十六进制摘要。

    Args:
        data: 输入字节。

    Returns:
        str: 32 位小写十六进制摘要。
    """
    return hashlib.md5(data).hexdigest()


def _make_fluid_samples() -> List[str]:
    """生成 fluid 夹具组（固定 seed/time 参考帧）。

    Python 侧 ``render_static_frame`` 以固定参数渲染，保存最终 pixmap 的
    RGBA8888 md5 与 PNG 预览。todo 13 为 DROP 裁决，参考帧供记录与回退
    测试使用。offscreen 平台下渲染。

    Returns:
        list[str]: 生成的文件名列表。
    """
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    from freeassetfilter.ui.components._styled_fluid_cpu import render_static_frame

    _app: QApplication = QApplication.instance() or QApplication([])

    palette: List[QColor] = [
        QColor(30, 60, 120),
        QColor(200, 120, 40),
        QColor(40, 160, 90),
        QColor(120, 40, 180),
        QColor(220, 220, 220),
    ]
    overlay: QColor = QColor(20, 30, 40, 60)

    # 两帧：render-size == target（无缩放）与需要上采样（缩放路径）。
    frames: Sequence[Tuple[str, int, int, int, float, QColor]] = (
        ("fluid_frame_64x48", 64, 48, 12345, 2.5, overlay),
        ("fluid_frame_160x100", 160, 100, 987, 0.0, QColor(0, 0, 0, 0)),
    )
    names: List[str] = []
    for stem, width, height, seed, time, ov in frames:
        pixmap = render_static_frame(width, height, palette, noise_seed=seed,
                                     time=time, overlay_color=ov)
        rgba: bytes = _qimage_rgba_bytes(pixmap)
        meta: Dict[str, object] = {
            "format": "faf-fluid-reference-frame-v1",
            "width": width,
            "height": height,
            "render_width": max(64, int(width * 0.25)),
            "render_height": max(48, int(height * 0.25)),
            "palette": [[c.red(), c.green(), c.blue(), c.alpha()] for c in palette],
            "noise_seed": seed,
            "time": time,
            "overlay": [ov.red(), ov.green(), ov.blue(), ov.alpha()],
            "rgba_md5": _md5(rgba),
            "rgba_bytes": len(rgba),
            "rendered_by": "freeassetfilter.ui.components._styled_fluid_cpu.render_static_frame",
            "note": "todo 13 DROP 裁决下的 Python 参考帧；供记录与回退测试。",
        }
        import json

        _write_text(f"fluid_samples/{stem}.json", json.dumps(meta, ensure_ascii=False, indent=2))
        _write_bytes(f"fluid_samples/{stem}.png", _pixmap_to_png_bytes(pixmap))
        names.append(f"{stem}.json")
        names.append(f"{stem}.png")
    return names


def _qimage_rgba_bytes(pixmap: object) -> bytes:
    """把 QPixmap 归一化为 RGBA8888 原始字节。

    Args:
        pixmap: QPixmap 实例。

    Returns:
        bytes: (R,G,B,A) 逐像素原始字节，行优先。
    """
    from PySide6.QtGui import QImage

    image: QImage = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
    return bytes(image.constBits().tobytes())


def _pixmap_to_png_bytes(pixmap: object) -> bytes:
    """把 QPixmap 编码为 PNG 字节（内存缓冲）。

    Args:
        pixmap: QPixmap 实例。

    Returns:
        bytes: PNG 文件字节。
    """
    from PySide6.QtCore import QBuffer
    from PySide6.QtCore import QByteArray
    from PySide6.QtCore import QIODevice

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    data: QByteArray = buffer.data()
    buffer.close()
    return bytes(data)


def _make_7z_samples() -> List[str]:
    """生成 7z ``-slt`` 文本夹具组（UTF-8 / GBK 两套编码）。

    文本非压缩包，是 7z.exe ``l -slt`` 输出样例：含中文文件名、目录块、
    隐藏项（点前缀）、压缩包自身、根级文件。GBK 版本以 gbk 编码写入，
    供编码检测/重试路径测试。

    Returns:
        list[str]: 生成的文件名列表。
    """
    slt_utf8: str = (
        "Path = sample_archive.7z\n"
        "Size = 0\n"
        "Type = 7z\n"
        "Physical Size = 4096\n"
        "Headers Size = 172\n"
        "Method = LZMA2:24\n"
        "Solid = +\n"
        "Blocks = 1\n"
        "\n"
        "----------\n"
        "Path = docs\\\n"
        "Folder = +\n"
        "Size = 0\n"
        "Packs = 0\n"
        "Attributes = D_....A\n"
        "Encrypted = -\n"
        "Method = \n"
        "Block = 0\n"
        "\n"
        "----------\n"
        "Path = docs\\readme_中文.txt\n"
        "Size = 256\n"
        "Packs = 256\n"
        "Attributes = ...._A\n"
        "Encrypted = -\n"
        "Method = LZMA2:24\n"
        "Block = 0\n"
        "CRC = 12345678\n"
        "Modified = 2026-09-05 10:30:00\n"
        "\n"
        "----------\n"
        "Path = docs\\说明文档.txt\n"
        "Size = 512\n"
        "Packs = 512\n"
        "Attributes = ...._A\n"
        "Encrypted = -\n"
        "Method = LZMA2:24\n"
        "Block = 0\n"
        "CRC = 9ABCDEF0\n"
        "Modified = 2026-09-05 10:35:00\n"
        "\n"
        "----------\n"
        "Path = docs\\.hidden_config\n"
        "Size = 64\n"
        "Packs = 64\n"
        "Attributes = ...._A\n"
        "Encrypted = -\n"
        "Method = LZMA2:24\n"
        "Block = 0\n"
        "CRC = 11111111\n"
        "Modified = 2026-09-05 10:40:00\n"
        "\n"
        "----------\n"
        "Path = docs\\sub\\\n"
        "Folder = +\n"
        "Size = 0\n"
        "Packs = 0\n"
        "Attributes = D_....A\n"
        "Encrypted = -\n"
        "Method = \n"
        "Block = 0\n"
        "\n"
        "----------\n"
        "Path = docs\\sub\\data.csv\n"
        "Size = 128\n"
        "Packs = 128\n"
        "Attributes = ...._A\n"
        "Encrypted = -\n"
        "Method = LZMA2:24\n"
        "Block = 0\n"
        "CRC = 22222222\n"
        "Modified = 2026-09-05 10:45:00\n"
        "\n"
        "----------\n"
        "Path = src\\\n"
        "Folder = +\n"
        "Size = 0\n"
        "Packs = 0\n"
        "Attributes = D_....A\n"
        "Encrypted = -\n"
        "Method = \n"
        "Block = 0\n"
        "\n"
        "----------\n"
        "Path = src\\main.py\n"
        "Size = 1024\n"
        "Packs = 1024\n"
        "Attributes = ...._A\n"
        "Encrypted = -\n"
        "Method = LZMA2:24\n"
        "Block = 0\n"
        "CRC = 33333333\n"
        "Modified = 2026-09-05 10:50:00\n"
        "\n"
        "----------\n"
        "Path = license.txt\n"
        "Size = 2048\n"
        "Packs = 2048\n"
        "Attributes = ...._A\n"
        "Encrypted = -\n"
        "Method = LZMA2:24\n"
        "Block = 0\n"
        "CRC = AABBCCDD\n"
        "Modified = 2026-09-05 11:00:00\n"
        "\n"
        "----------\n"
        "Path = sample_archive.7z\n"
        "Size = 4096\n"
        "Packs = 4096\n"
        "Attributes = ...._A\n"
        "Encrypted = -\n"
        "Method = LZMA2:24\n"
        "Block = 0\n"
        "CRC = 44444444\n"
        "Modified = 2026-09-05 09:00:00\n"
    )
    _write_text("seven_zip_samples/slt_output_utf8.txt", slt_utf8)
    _write_text("seven_zip_samples/slt_output_gbk.txt", slt_utf8, encoding="gbk")
    return ["slt_output_utf8.txt", "slt_output_gbk.txt"]


def _make_pdf_samples() -> List[str]:
    """生成 PDF 夹具组（多页多词，fitz 生成）。

    Returns:
        list[str]: 生成的文件名列表。
    """
    import fitz

    doc: fitz.Document = fitz.open()
    pages_text: Sequence[Sequence[str]] = (
        ("alpha beta gamma delta", "epsilon zeta eta theta", "iota kappa lambda mu"),
        ("nu xi omicron pi rho", "sigma tau upsilon phi chi", "psi omega first second third"),
        ("fourth fifth sixth seventh eighth", "ninth tenth eleventh twelfth",
         "thirteenth fourteenth fifteenth sixteenth"),
    )
    for lines in pages_text:
        page: fitz.Page = doc.new_page(width=612, height=792)
        y: float = 100.0
        for line in lines:
            page.insert_text((72, y), line, fontname="helv", fontsize=14)
            y += 40.0
    buffer = io.BytesIO()
    doc.save(buffer)
    _write_bytes("pdf_samples/sample_multi_page.pdf", buffer.getvalue())
    return ["sample_multi_page.pdf"]


#: 各组生成函数的调度表（name -> 生成函数）。
_MAKERS: Dict[str, object] = {
    "exif_samples": _make_exif_samples,
    "psd_samples": _make_psd_samples,
    "svg_samples": _make_svg_samples,
    "fluid_samples": _make_fluid_samples,
    "seven_zip_samples": _make_7z_samples,
    "pdf_samples": _make_pdf_samples,
}


def _validate_svg_regex_coverage() -> None:
    """校验 18 条换色正则命中/不命中覆盖。

    Raises:
        AssertionError: 存在未命中的正则，或 no-match 样本被命中。
    """
    import freeassetfilter.core.preview.svg_renderer as svg_mod

    patterns: Sequence[object] = (
        svg_mod._RE_PATH_NO_FILL, svg_mod._RE_STROKE_WHITE, svg_mod._RE_STROKE_WHITE_SHORT,
        svg_mod._RE_STROKE_BLACK, svg_mod._RE_STROKE_BLACK_SHORT, svg_mod._RE_FILL_WHITE,
        svg_mod._RE_FILL_WHITE_SHORT, svg_mod._RE_FILL_BLACK, svg_mod._RE_FILL_BLACK_SHORT,
        svg_mod._RE_CSS_FILL_WHITE, svg_mod._RE_CSS_FILL_WHITE_SHORT, svg_mod._RE_CSS_FILL_BLACK,
        svg_mod._RE_CSS_FILL_BLACK_SHORT, svg_mod._RE_ACCENT, svg_mod._RE_STROKE_NORMAL,
        svg_mod._RE_FILL_NORMAL, svg_mod._RE_CSS_FILL_NORMAL, svg_mod._RE_CSS_STROKE_NORMAL,
    )
    assert len(patterns) == 18, "SVG 换色正则应恰好 18 条"

    hit_text: str = _SVG_HIT_ALL + _SVG_HIT_SHORT_UPPER
    names: Sequence[str] = (
        "_RE_PATH_NO_FILL", "_RE_STROKE_WHITE", "_RE_STROKE_WHITE_SHORT",
        "_RE_STROKE_BLACK", "_RE_STROKE_BLACK_SHORT", "_RE_FILL_WHITE",
        "_RE_FILL_WHITE_SHORT", "_RE_FILL_BLACK", "_RE_FILL_BLACK_SHORT",
        "_RE_CSS_FILL_WHITE", "_RE_CSS_FILL_WHITE_SHORT", "_RE_CSS_FILL_BLACK",
        "_RE_CSS_FILL_BLACK_SHORT", "_RE_ACCENT", "_RE_STROKE_NORMAL",
        "_RE_FILL_NORMAL", "_RE_CSS_FILL_NORMAL", "_RE_CSS_STROKE_NORMAL",
    )
    for pattern, name in zip(patterns, names):
        assert pattern.search(hit_text) is not None, f"{name} 未命中任何样本"
    for pattern, name in zip(patterns, names):
        assert pattern.search(_SVG_NO_MATCH) is None, f"{name} 错误命中了 no-match 样本"


def _validate_7z_parse() -> None:
    """用产品解析器校验 7z 夹具文本可被正确解析。

    校验 root 浏览（docs/src 目录 + license.txt 文件）与 docs 子目录浏览
    （中文文件名 + sub 目录），隐藏项与压缩包自身被排除。

    Raises:
        AssertionError: 解析结果与预期不符。
    """
    from freeassetfilter.core.native.bridges.py7z_core import Py7zCore

    core: Py7zCore = Py7zCore()
    utf8_path: Path = _FIXTURES_DIR / "seven_zip_samples" / "slt_output_utf8.txt"
    utf8_text: str = utf8_path.read_text(encoding="utf-8")

    root_result = core._parse_list_output(utf8_text, "", "sample_archive.7z")
    root_names: Sequence[str] = [item["name"] for item in root_result]
    assert root_names == ["docs", "src", "license.txt"], f"root 解析不符: {root_names}"

    docs_result = core._parse_list_output(utf8_text, "docs", "sample_archive.7z")
    docs_names: Sequence[str] = sorted(item["name"] for item in docs_result)
    assert docs_names == ["readme_中文.txt", "sub", "说明文档.txt"], f"docs 解析不符: {docs_names}"
    assert all(item["path"] != "docs/.hidden_config" for item in docs_result), "隐藏项未排除"


def _validate_fluid_hash() -> None:
    """重渲染 fluid 参考帧，校验 rgba_md5 可复现。

    Raises:
        AssertionError: 重渲染 md5 与 JSON 记录不一致。
    """
    import json

    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    from freeassetfilter.ui.components._styled_fluid_cpu import render_static_frame

    _app: QApplication = QApplication.instance() or QApplication([])
    for json_name in ("fluid_frame_64x48.json", "fluid_frame_160x100.json"):
        meta_path: Path = _FIXTURES_DIR / "fluid_samples" / json_name
        meta: Dict[str, object] = json.loads(meta_path.read_text(encoding="utf-8"))
        palette: List[QColor] = [
            QColor(r, g, b, a) for r, g, b, a in meta["palette"]  # type: ignore[index]
        ]
        overlay: QColor = QColor(*meta["overlay"])  # type: ignore[arg-type]
        pixmap = render_static_frame(
            int(meta["width"]),  # type: ignore[arg-type]
            int(meta["height"]),  # type: ignore[arg-type]
            palette,
            noise_seed=int(meta["noise_seed"]),  # type: ignore[arg-type]
            time=float(meta["time"]),  # type: ignore[arg-type]
            overlay_color=overlay,
        )
        actual: str = _md5(_qimage_rgba_bytes(pixmap))
        assert actual == meta["rgba_md5"], f"{json_name} 重渲染 hash 不一致"


def _validate_corrupt_psd() -> None:
    """校验损坏 PSD 至少可被打开（不 panic），记录其图层数。

    Raises:
        AssertionError: 损坏 PSD 打开即抛异常（不符合夹具预期）。
    """
    from psd_tools.api.psd_image import PSDImage

    corrupt_path: Path = _FIXTURES_DIR / "psd_samples" / "sample_corrupt.psd"
    try:
        back = PSDImage.open(corrupt_path)
        print(f"  [info] 损坏 PSD 可打开，图层数={len(list(back.descendants()))}")
    except Exception as exc:  # noqa: BLE001 - 仅记录损坏行为
        print(f"  [info] 损坏 PSD 打开即抛异常: {type(exc).__name__}: {exc}")


def _validate_sizes() -> List[str]:
    """校验全部夹具单文件 <512KB 并返回超限清单。

    Returns:
        list[str]: 超出 512KB 的文件相对路径（应为空）。
    """
    oversized: List[str] = []
    for root, _, files in os.walk(_FIXTURES_DIR):
        for name in files:
            path: Path = Path(root) / name
            if path.name == "generate_fixtures.py":
                continue
            if path.stat().st_size > _MAX_BYTES:
                oversized.append(str(path.relative_to(_FIXTURES_DIR)))
    return oversized


def main() -> int:
    """执行全部夹具生成与自校验并打印清单。

    Returns:
        int: 0 表示成功，1 表示失败。
    """
    print(f"夹具根目录: {_FIXTURES_DIR}")
    for group, maker in _MAKERS.items():
        print(f"\n[{group}]")
        for name in maker():  # type: ignore[misc]
            path: Path = _FIXTURES_DIR / group / name
            print(f"  {path.relative_to(_FIXTURES_DIR)}  ({path.stat().st_size} bytes)")

    print("\n[自校验]")
    _validate_svg_regex_coverage()
    print("  SVG 18 条正则命中/不命中覆盖 OK")
    _validate_7z_parse()
    print("  7z -slt 夹具可被 _parse_list_output 正确解析 OK")
    _validate_fluid_hash()
    print("  fluid 参考帧 md5 可复现 OK")
    _validate_corrupt_psd()
    oversized: List[str] = _validate_sizes()
    assert not oversized, f"存在超 512KB 的夹具: {oversized}"
    print("  全部夹具单文件 <512KB OK")
    print("\n生成完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
