"""程序化测试数据生成：图片 / PDF / 文本 / 压缩包 / 字体 / 文件信息。

全部工厂函数只接受目标路径并返回生成后的路径字符串；目录不存在时自动
创建父目录。提供多色几何图案 PIL 图片、纯字节构造的 PDF 1.4、简单文本、
ZIP 压缩包、Windows Fonts 字体拷贝与前缀元信息字典，供 W1-W8 各测试
套件直接引用（conftest（todo 4）将以这些函数为底，包装出 fixture）。
"""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

#: SVG 的最小可渲染内容（红色圆 + 正文字）。
_DEFAULT_SVG: str = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">\n'
    '  <rect width="120" height="80" fill="#ffffff"/>\n'
    '  <circle cx="60" cy="40" r="25" fill="#d04040"/>\n'
    '  <text x="60" y="72" font-size="12" text-anchor="middle" fill="#333333">'
    "FAF test</text>\n"
    "</svg>\n"
)


def _as_path(path: Union[str, Path]) -> Path:
    """把输入归一化为 Path 并确保父目录存在。

    Args:
        path: 目标路径。

    Returns:
        Path: 归一化后的绝对路径。
    """
    p: Path = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def make_image(
    path: Union[str, Path],
    fmt: str = "PNG",
    size: tuple[int, int] = (240, 160),
) -> str:
    """生成一张含多色几何图案的 PIL 图片。

    图案：红蓝对角渐变底 + 黄绿色圆环 + 品红矩形 + 青色三角形，保证在
    缩略图、颜色提取等测试中"肉眼可见地非空"。

    Args:
        path: 输出路径（含扩展名，如 ``x.png``）。
        fmt: PIL 保存格式名（默认 PNG；JPEG/BMP 亦可）。
        size: 图片尺寸 (宽, 高)。

    Returns:
        str: 生成后的文件路径。

    Raises:
        ImportError: PIL（Pillow）不可用。
    """
    from PIL import Image, ImageDraw

    width, height = size
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        for x in range(width):
            r = int(255 * x / max(1, width - 1))
            b = int(255 * y / max(1, height - 1))
            image.putpixel((x, y), (r, 40, b))
    # 圆形描边（黄）与实心圆（橙）
    draw.ellipse((width // 5, height // 5, width * 4 // 5, height * 4 // 5),
                 outline=(255, 200, 0), width=max(2, width // 30))
    draw.ellipse((width // 3, height // 3, width * 2 // 3, height * 2 // 3),
                 fill=(255, 120, 0))
    # 品红矩形与青色三角形
    draw.rectangle((0, height - height // 4, width // 4, height - 1), fill=(230, 40, 200))
    draw.polygon([(width - 1, height - 1), (width - 1, height // 2),
                  (width // 2, height - 1)], fill=(0, 210, 210))
    out: Path = _as_path(path)
    image.save(str(out), fmt)
    return str(out)


def make_pdf(path: Union[str, Path]) -> str:
    """用纯字节构造一个最小可用 PDF 1.4 文件。

    逻辑搬运自归档 ``old-tests-snapshot/tests/conftest.py:298-343`` 的
    ``temp_pdf_file``（不含 fixture 包装），不依赖任何第三方 PDF 库。

    Args:
        path: 输出路径（通常以 ``.pdf`` 结尾）。

    Returns:
        str: 生成后的文件路径。
    """
    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    obj3 = (b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n")
    obj4 = (b"4 0 obj\n<< /Length 44 >>\nstream\n"
            b"BT /F1 24 Tf 100 700 Td (Hello World) Tj ET\nendstream\nendobj\n")
    obj5 = b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    objects: List[bytes] = [obj1, obj2, obj3, obj4, obj5]
    header = b"%PDF-1.4\n"
    body = b"".join(objects)
    offsets: List[int] = []
    pos: int = len(header)
    for obj in objects:
        offsets.append(pos)
        pos += len(obj)
    xref_offset: int = pos
    num_entries: int = len(objects) + 1
    xref_parts: List[bytes] = [f"xref\n0 {num_entries}\n".encode()]
    xref_parts.append(b"0000000000 65535 f \n")
    for offset in offsets:
        xref_parts.append(f"{offset:010d} 00000 n \n".encode())
    xref: bytes = b"".join(xref_parts)
    trailer: bytes = f"trailer\n<< /Size {num_entries} /Root 1 0 R >>\n".encode()
    startxref: bytes = f"startxref\n{xref_offset}\n%%EOF".encode()
    out: Path = _as_path(path)
    out.write_bytes(header + body + xref + trailer + startxref)
    return str(out)


def make_text(
    path: Union[str, Path],
    content: Optional[str] = None,
    encoding: str = "utf-8",
) -> str:
    """生成一个纯文本文件。

    Args:
        path: 输出路径（通常以 ``.txt`` / ``.md`` 结尾）。
        content: 文件内容；缺省为三行示例文本。
        encoding: 写入编码。

    Returns:
        str: 生成后的文件路径。
    """
    body: str = content if content is not None else (
        "# 示例文档\n\nHello, World!\n第二行内容\n"
    )
    out: Path = _as_path(path)
    out.write_text(body, encoding=encoding)
    return str(out)


def make_zip(
    path: Union[str, Path],
    entries: Union[Mapping[str, str], Sequence[str]],
) -> str:
    """生成一个 ZIP 压缩包。

    ``entries`` 为 ``{相对路径: 内容}`` 映射时写入相应字节内容；为
    字符串序列时按名创建空文件。

    Args:
        path: 输出路径（通常以 ``.zip`` 结尾）。
        entries: 条目映射（名字→内容）或仅文件名序列。

    Returns:
        str: 生成后的文件路径。
    """
    out: Path = _as_path(path)
    with zipfile.ZipFile(str(out), "w", zipfile.ZIP_DEFLATED) as zf:
        if isinstance(entries, Mapping):
            for name, content in entries.items():
                zf.writestr(name, content)
        else:
            for name in entries:
                zf.writestr(str(name), b"")
    return str(out)


def make_svg(path: Union[str, Path]) -> str:
    """生成一个最小可渲染的 SVG 文件。

    Args:
        path: 输出路径（以 ``.svg`` 结尾）。

    Returns:
        str: 生成后的文件路径。
    """
    out: Path = _as_path(path)
    out.write_text(_DEFAULT_SVG, encoding="utf-8")
    return str(out)


def _font_candidates() -> List[Path]:
    """返回 Windows Fonts 目录下优先尝试的字体候选。

    Returns:
        list[Path]: 绝对路径候选，按常用度排序。
    """
    fonts_dir: Path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    return [fonts_dir / name for name in ("arial.ttf", "segoeui.ttf", "times.ttf", "calibri.ttf")]


def make_font_path() -> Optional[str]:
    """从 Windows Fonts 复制一个字体候选到临时目录。

    失败（无 Windows 字体目录、复制被拒等）时返回 ``None``，调用方应
    据此跳过依赖字体的测试。

    Returns:
        Optional[str]: 复制后的字体文件路径；失败为 None。
    """
    cache_dir: Path = Path(tempfile.gettempdir()) / "faf_test_fonts"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    for src in _font_candidates():
        if not src.is_file():
            continue
        dest: Path = cache_dir / src.name
        try:
            shutil.copy2(str(src), str(dest))
            return str(dest)
        except OSError:
            continue
    return None


_MEDIA_DIR: Path = Path(__file__).resolve().parent / "media"


def make_video_sample(name: str, target: Path) -> str:
    """从 ``tests/support/media/`` 复制一个视频测试样本到目标路径。

    样本（sample_h264.mp4 / sample_vp9.webm 等）由 Todo 5 生成并随仓库
    跟踪，本函数仅做复制，与 :func:`make_font_path` 同款复制模式。

    Args:
        name: 样本文件名（须存在于 ``tests/support/media/``）。
        target: 输出路径（复制到的目标文件）。

    Returns:
        str: 复制后的文件路径。

    Raises:
        FileNotFoundError: 源样本文件不存在。
    """
    src: Path = _MEDIA_DIR / name
    if not src.is_file():
        raise FileNotFoundError(f"视频测试样本不存在: {src}")
    out: Path = _as_path(target)
    shutil.copy2(str(src), str(out))
    return str(out)


def file_info_dict(path: Union[str, Path], ext: str = "png") -> Dict[str, Any]:
    """构造与产品 ``FileInfo`` 兼容的元信息字典。

    形状参考归档 ``mock_file_info``（old-tests-snapshot/tests/utils.py），
    字段：path / name / type / extension / size / modified。

    Args:
        path: 文件路径（不必真实存在，size/modified 缺省占位）。
        ext: 扩展名（不带点），写入 ``extension`` 字段。

    Returns:
        dict[str, Any]: 文件信息字典。
    """
    full: str = str(path)
    name: str = Path(full).name
    stat_result: Optional[os.stat_result] = None
    try:
        stat_result = os.stat(full)
    except OSError:
        pass
    size: int = int(stat_result.st_size) if stat_result is not None else 0
    modified: int = int(stat_result.st_mtime) if stat_result is not None else 0
    info: Dict[str, Any] = {
        "path": full,
        "name": name,
        "type": "file",
        "extension": ext,
        "size": size,
        "modified": modified,
    }
    return info