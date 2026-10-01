"""LUT C++ 扩展的发布运行时加载器。

发布包只从 ``core/native/bin/lut_preview`` 加载已编译扩展；源码目录仅供开发环境回退。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Optional

from freeassetfilter.utils.app_logger import info, warning

_module: Optional[ModuleType] = None
_attempted = False


def _candidates() -> list[Path]:
    native_dir = Path(__file__).resolve().parent.parent
    bundled = native_dir / "bin" / "lut_preview"
    source = native_dir / "src" / "cpp_lut_preview"
    paths = sorted(bundled.glob("lut_preview_cpp*.pyd")) if bundled.is_dir() else []
    if not getattr(sys, "frozen", False):
        paths.extend(sorted(source.glob("lut_preview_cpp*.pyd")))
    return paths


def _load() -> Optional[ModuleType]:
    global _module, _attempted
    if _attempted:
        return _module
    _attempted = True
    for path in _candidates():
        try:
            spec = importlib.util.spec_from_file_location("lut_preview_cpp", path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules["lut_preview_cpp"] = module
            spec.loader.exec_module(module)
            _module = module
            info(f"[LUTPreviewCPP] 加载扩展: {path}")
            return module
        except (ImportError, OSError) as exc:
            warning(f"[LUTPreviewCPP] 加载失败 {path}: {exc}")
    return None


def is_cpp_available() -> bool:
    return _load() is not None


def generate_preview(lut_content: str, image_array, output_width: int, output_height: int) -> bytes:
    module = _load()
    if module is None:
        raise RuntimeError("LUT C++ 扩展不可用")
    return module.generate_preview_from_data(lut_content, image_array, output_width, output_height)


__all__ = ["generate_preview", "is_cpp_available"]
