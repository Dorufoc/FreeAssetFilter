"""像素 parity 断言：多源图像归一化 RGBA + 确定性 hash + 逐像素差异诊断。

与 :mod:`tests.support.parity.comparator` 的字段级断言互补——SVG 换色、
fluid 参考帧、PSD 合成等「渲染结果」类对拍需要把不同来源（PIL / QImage /
QPixmap / 原始 RGBA 字节 / 图片路径）归一化成统一的 RGBA8888 字节后再比较。

比较语义：
- :func:`pixel_hash` 对归一化 RGBA 字节计算 md5（确定性、非加密用途）。
- :func:`assert_pixel_parity` 默认要求两实现像素逐字节一致；可通过
  ``max_diff_count`` / ``max_diff_ratio`` 注入可容忍的像素差异（等价于
  comparator 的 accepted-diffs 豁免，只是按像素计数而非路径豁免）。

QPixmap 注意点：多数平台上 QPixmap 内部以 ``Format_ARGB32_Premultiplied``
存储，``toImage()`` 反向非预乘会引入舍入，故其归一化字节与同内容的
QImage / PIL / 原始 RGBA 不一定逐字节相等。对拍时应让两侧走同一管线
（同 QImage 或同 PIL 锚），避免一侧 QPixmap 一侧 QImage 直接比较。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, List, Optional, Tuple, Union

#: 支持归一化的源类型别名（QImage/QPixmap 以协议方式鸭子类型判断）。
_ImageSource = Union[bytes, bytearray, memoryview, Tuple[int, int, bytes]]


class PixelParityMismatchError(AssertionError):
    """像素 parity 断言失败：两实现渲染结果不一致。

    Attributes:
        python_hash: python-impl 侧 RGBA md5。
        native_hash: native-impl 侧 RGBA md5。
        geometry: (宽, 高)；源无法确定尺寸时为 None。
        diff_count: 不一致像素数。
        samples: 差异像素样例描述行（坐标 + 双值）。
    """

    def __init__(
        self,
        python_hash: str,
        native_hash: str,
        geometry: Optional[Tuple[int, int]],
        diff_count: int,
        samples: List[str],
    ) -> None:
        self.python_hash: str = python_hash
        self.native_hash: str = native_hash
        self.geometry: Optional[Tuple[int, int]] = geometry
        self.diff_count: int = diff_count
        self.samples: List[str] = samples
        geo_text: str = f"{geometry[0]}x{geometry[1]}" if geometry else "unknown"
        detail: str = "\n".join(f"  - {line}" for line in samples[:8])
        super().__init__(
            f"pixel parity mismatch ({diff_count} pixels differ, size={geo_text}):\n"
            f"  python={python_hash}\n  native={native_hash}\n{detail}"
        )


def _is_qimage(obj: Any) -> bool:
    """判断对象是否 QImage（避免强导入 Qt 依赖）。

    Args:
        obj: 任意对象。

    Returns:
        bool: 对象具备 ``convertToFormat`` 与 ``constBits`` 即视为 QImage。
    """
    return hasattr(obj, "convertToFormat") and hasattr(obj, "constBits")


def _is_qpixmap(obj: Any) -> bool:
    """判断对象是否 QPixmap（具备 ``toImage``）。

    Args:
        obj: 任意对象。

    Returns:
        bool: 对象具备 ``toImage`` 即视为 QPixmap。
    """
    return hasattr(obj, "toImage")


def rgba_bytes(source: Any) -> bytes:
    """把任意图像源归一化为 RGBA8888 原始字节（行优先、(R,G,B,A)）。

    支持：bytes/bytearray/memoryview（视为已归一化 RGBA）、PIL.Image、
    QImage、QPixmap、(宽, 高, 字节) 元组、图片文件路径。

    Args:
        source: 图像源。

    Returns:
        bytes: RGBA 原始字节。

    Raises:
        TypeError: 无法识别的源类型。
    """
    if isinstance(source, (bytes, bytearray, memoryview)):
        return bytes(source)
    if isinstance(source, tuple) and len(source) == 3:
        _width, _height, data = source
        return bytes(data)
    if isinstance(source, (str, Path)):
        from PIL import Image

        with Image.open(str(source)) as image:
            return _pil_to_rgba_bytes(image)
    # PIL.Image：具备 convert() 与 tobytes()。
    if hasattr(source, "convert") and hasattr(source, "tobytes"):
        return _pil_to_rgba_bytes(source)
    if _is_qpixmap(source):
        return rgba_bytes(source.toImage())
    if _is_qimage(source):
        return _qimage_to_rgba_bytes(source)
    raise TypeError(f"无法把源归一化为 RGBA 字节: {type(source).__name__}")


def _pil_to_rgba_bytes(image: Any) -> bytes:
    """PIL.Image → RGBA 字节。

    Args:
        image: PIL Image 实例。

    Returns:
        bytes: RGBA8888 原始字节。
    """
    return image.convert("RGBA").tobytes()


def _qimage_to_rgba_bytes(image: Any) -> bytes:
    """QImage → RGBA8888 字节。

    Args:
        image: QImage 实例。

    Returns:
        bytes: RGBA8888 原始字节。
    """
    from PySide6.QtGui import QImage

    rgba: QImage = image.convertToFormat(QImage.Format_RGBA8888)
    return bytes(rgba.constBits().tobytes())


def image_geometry(source: Any) -> Optional[Tuple[int, int]]:
    """尽力返回图像源的 (宽, 高)；无法确定时返回 None。

    Args:
        source: 图像源。

    Returns:
        Optional[tuple[int, int]]: (宽, 高) 或 None。
    """
    if isinstance(source, tuple) and len(source) == 3:
        return (int(source[0]), int(source[1]))
    if isinstance(source, (str, Path)):
        from PIL import Image

        with Image.open(str(source)) as image:
            return image.size
    if hasattr(source, "convert") and hasattr(source, "tobytes") and hasattr(source, "size"):
        return tuple(int(v) for v in source.size)  # type: ignore[return-value]
    if _is_qpixmap(source):
        return image_geometry(source.toImage())
    if _is_qimage(source) and hasattr(source, "width") and hasattr(source, "height"):
        return (int(source.width()), int(source.height()))
    return None


def pixel_hash(source: Any) -> str:
    """计算图像源的确定性 RGBA md5。

    Args:
        source: 图像源（见 :func:`rgba_bytes`）。

    Returns:
        str: 32 位小写十六进制 md5 摘要。
    """
    return hashlib.md5(rgba_bytes(source)).hexdigest()


def pixel_diff_count(python_source: Any, native_source: Any) -> int:
    """比较两图像源，返回不一致的像素数。

    两源 RGBA 字节长度不一致时返回 1（视为整体不一致），并尽力报告。

    Args:
        python_source: python-impl 侧图像源。
        native_source: native-impl 侧图像源。

    Returns:
        int: 不一致像素数。
    """
    py_bytes: bytes = rgba_bytes(python_source)
    native_bytes: bytes = rgba_bytes(native_source)
    if len(py_bytes) != len(native_bytes):
        return 1
    if len(py_bytes) % 4 != 0:
        # 非 4 对齐视为无法按像素解释，按字节不一致处理。
        return len(py_bytes) if py_bytes != native_bytes else 0
    return sum(
        1 for i in range(0, len(py_bytes), 4)
        if py_bytes[i:i + 4] != native_bytes[i:i + 4]
    )


def pixel_diff_samples(
    python_source: Any,
    native_source: Any,
    limit: int = 8,
) -> List[str]:
    """返回差异像素的描述行（坐标 + 双方 RGBA 值）。

    Args:
        python_source: python-impl 侧图像源。
        native_source: native-impl 侧图像源。
        limit: 最多返回的样例行数。

    Returns:
        list[str]: 差异描述行；无差异返回空列表。
    """
    py_bytes: bytes = rgba_bytes(python_source)
    native_bytes: bytes = rgba_bytes(native_source)
    geometry: Optional[Tuple[int, int]] = (
        image_geometry(python_source) or image_geometry(native_source)
    )
    if len(py_bytes) != len(native_bytes):
        return [
            "byte length differs "
            f"(python={len(py_bytes)} native={len(native_bytes)})"
        ]
    if len(py_bytes) % 4 != 0:
        return [f"non-RGBA-aligned buffer length {len(py_bytes)}"]
    samples: List[str] = []
    stride: int = geometry[0] * 4 if geometry else 0
    for offset in range(0, len(py_bytes), 4):
        if py_bytes[offset:offset + 4] == native_bytes[offset:offset + 4]:
            continue
        if len(samples) >= limit:
            break
        if geometry and stride:
            x: int = (offset % stride) // 4
            y: int = offset // stride
            where: str = f"({x},{y})"
        else:
            where = f"offset {offset}"
        samples.append(
            f"{where}: python=({py_bytes[offset]:#04x},{py_bytes[offset + 1]:#04x},"
            f"{py_bytes[offset + 2]:#04x},{py_bytes[offset + 3]:#04x}) "
            f"native=({native_bytes[offset]:#04x},{native_bytes[offset + 1]:#04x},"
            f"{native_bytes[offset + 2]:#04x},{native_bytes[offset + 3]:#04x})"
        )
    return samples


def assert_pixel_parity(
    python_source: Any,
    native_source: Any,
    *,
    max_diff_count: int = 0,
    max_diff_ratio: float = 0.0,
) -> str:
    """断言两实现渲染像素 parity 一致（默认逐字节相等）。

    Args:
        python_source: python-impl 侧图像源。
        native_source: native-impl 侧图像源。
        max_diff_count: 允许的最大不一致像素数（0 表示必须完全一致）。
        max_diff_ratio: 允许的最大不一致像素比例（0.0-1.0，与
            ``max_diff_count`` 取更宽松者）。

    Returns:
        str: 双方一致的 RGBA md5（便于记录）。

    Raises:
        PixelParityMismatchError: 不一致像素数超限，消息含双端 hash /
            尺寸 / 差异样例明细。
    """
    py_bytes: bytes = rgba_bytes(python_source)
    native_bytes: bytes = rgba_bytes(native_source)
    py_hash: str = hashlib.md5(py_bytes).hexdigest()
    native_hash: str = hashlib.md5(native_bytes).hexdigest()

    if py_hash == native_hash:
        return py_hash

    diff_count: int = pixel_diff_count(python_source, native_source)
    geometry: Optional[Tuple[int, int]] = (
        image_geometry(python_source) or image_geometry(native_source)
    )
    if geometry:
        total: int = max(1, geometry[0] * geometry[1])
        ratio_limit: float = max(0.0, min(1.0, max_diff_ratio))
        allowed: int = max(max_diff_count, int(total * ratio_limit))
    else:
        allowed = max_diff_count
    if diff_count <= allowed:
        return py_hash
    samples: List[str] = pixel_diff_samples(python_source, native_source)
    raise PixelParityMismatchError(py_hash, native_hash, geometry, diff_count, samples)
