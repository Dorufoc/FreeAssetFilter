"""Sopeek 资源与仓库路径解析——全项目唯一事实来源。

所有需要“找某个目录/文件在哪”的代码都从这里取，禁止再写
``Path(__file__).parents[N]`` 或 ``"../icons"`` 之类的相对推导：
目录层级一变（例如从 ``sopeek/`` 迁到 ``src/sopeek/``）这类代码就会静默指向
不存在的路径。

冻结态（PyInstaller onedir）下 ``__file__`` 落在 ``_internal/``，随包数据与
包代码保持同样的相对位置，因此同一套推导在源码态与冻结态都成立。

Usage:
    from sopeek._paths import icons_dir, native_bin_dir, repo_root
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import List


def package_dir() -> Path:
    """返回 ``sopeek`` 包目录（本文件所在目录）。

    Returns:
        Path: ``<repo>/src/sopeek``（源码态）或 ``<_internal>/sopeek``（冻结态）。
    """
    return Path(__file__).resolve().parent


def repo_root() -> Path:
    """返回仓库根目录；冻结态返回可执行文件所在目录。

    Returns:
        Path: 源码态为 ``<repo>``（``package_dir`` 上溯两级），
        冻结态为 exe 所在目录。
    """
    if getattr(os.sys, "frozen", False):
        return Path(os.sys.executable).resolve().parent
    return package_dir().parent.parent


def src_dir() -> Path:
    """返回源码根 ``src/``（冻结态即 ``_internal``）。

    Returns:
        Path: ``package_dir`` 的父目录。
    """
    return package_dir().parent


def resources_dir() -> Path:
    """返回随包资源根目录。

    Returns:
        Path: ``sopeek/resources/``。
    """
    return package_dir() / "resources"


def icons_dir() -> Path:
    """返回界面与文件类型图标目录。

    Returns:
        Path: ``sopeek/resources/icons/``。
    """
    return resources_dir() / "icons"


def syntax_dir() -> Path:
    """返回 TextMate 语法定义目录（``*.tmLanguage.json``）。

    Returns:
        Path: ``sopeek/resources/syntax/``。
    """
    return resources_dir() / "syntax"


def shaders_dir() -> Path:
    """返回 Qt Shader Baker 编译产物目录（``*.qsb``）。

    Returns:
        Path: ``sopeek/resources/shaders/``。
    """
    return resources_dir() / "shaders"


def docs_dir() -> Path:
    """返回随包文档目录（第三方许可清单）。

    Returns:
        Path: ``sopeek/resources/docs/``。
    """
    return resources_dir() / "docs"


def native_dir() -> Path:
    """返回原生运行时目录（``bin/`` 的父目录）。

    Returns:
        Path: ``sopeek/core/native/``。
    """
    return package_dir() / "core" / "native"


def native_bin_dir() -> Path:
    """返回原生二进制目录。

    Houses mpv runtime DLLs (``libmpv-2.dll``, ffmpeg, libplacebo, etc.),
    compiled Rust/C++ binaries (``thumbnail_generator.dll``,
    ``spk_core.dll``, ``mica_render.dll``), and ffmpeg/ffprobe executables.

    Returns:
        Path: ``sopeek/core/native/bin/``。
    """
    return native_dir() / "bin"


def archive_7z_dir() -> Path:
    """返回 7-Zip 归档工具目录（``7z.exe`` / ``7z.dll``）。

    Returns:
        Path: ``sopeek/core/native/bin/7z/``。
    """
    return native_bin_dir() / "7z"


def native_source_root() -> Path:
    """返回原生源码根目录（Rust/C++ 工程，构建输入而非随包数据）。

    Returns:
        Path: ``<repo>/native/``；冻结态该目录不存在，调用方应只在开发态使用。
    """
    return repo_root() / "native"


def launcher_dir() -> Path:
    """返回独显启动器目录（``SPK-Launcher.exe`` 的构建与安装位置）。

    Returns:
        Path: ``<repo>/packaging/launcher/``。
    """
    return repo_root() / "packaging" / "launcher"


def version_file() -> Path:
    """返回版本号文件 ``SPKVERSION`` 的路径。

    Returns:
        Path: 仓库根（源码态）或 exe 所在目录（冻结态）下的 ``SPKVERSION``。
    """
    return repo_root() / "SPKVERSION"


def get_app_data_path() -> Path:
    """返回应用数据目录（可写）。

    委托 :func:`sopeek.utils.path_utils.get_app_data_path`，保证原生侧与 UI 侧
    共用同一个运行时根：``SPK_DATA_DIR`` 优先，否则
    ``%LOCALAPPDATA%\\Sopeek\\data``。目录不存在时创建。

    Returns:
        Path: 应用数据目录绝对路径。
    """
    from sopeek.utils.path_utils import get_app_data_path as _get_app_data_path

    return Path(_get_app_data_path())


def soffice_paths() -> List[Path]:
    """返回可能包含 soffice 的目录列表（去重、按探测顺序）。

    依次探测：

    1. ``%ProgramFiles%\\LibreOffice\\program``
    2. ``%ProgramFiles(x86)%\\LibreOffice\\program``
    3. ``shutil.which`` 找到的 ``soffice``/``soffice.com`` 所在目录
    4. :func:`native_bin_dir`（便携版预留位置）

    永不抛异常、永不启动 soffice——只做路径探测。

    Returns:
        List[Path]: 去重且存在性过滤后的候选目录；未检测到 LibreOffice 时为空列表。
    """
    candidates: List[Path] = []

    # 1/2: 标准 Windows 安装位置（环境变量优先，硬编码兜底）。
    for program_files in (
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ):
        program_dir = Path(program_files) / "LibreOffice" / "program"
        if program_dir.is_dir() and any(
            (program_dir / name).is_file() for name in ("soffice.exe", "soffice.com")
        ):
            candidates.append(program_dir)

    # 3: PATH 查找——取已解析二进制所在目录。
    for name in ("soffice", "soffice.com"):
        try:
            found = shutil.which(name)
        except Exception:
            continue
        if found:
            candidates.append(Path(found).resolve().parent)

    # 4: 便携版/应用目录预留位置。
    native_bin = native_bin_dir()
    if native_bin.is_dir():
        candidates.append(native_bin)

    seen: set = set()
    result: List[Path] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
    return result


__all__ = [
    "package_dir",
    "repo_root",
    "src_dir",
    "resources_dir",
    "icons_dir",
    "syntax_dir",
    "shaders_dir",
    "docs_dir",
    "native_dir",
    "native_bin_dir",
    "archive_7z_dir",
    "native_source_root",
    "launcher_dir",
    "version_file",
    "get_app_data_path",
    "soffice_paths",
]
