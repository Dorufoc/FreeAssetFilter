"""本地版本号与发布页地址。

版本信息以仓库根目录的 ``SPKVERSION`` 为唯一来源：第一行为版本号，
第二行为构建日期。读取失败时使用安全的 ``0.0.0`` / ``None`` 回退，
避免更新检查因打包缺文件而崩溃。
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Optional

from sopeek.utils.path_utils import get_resource_path

#: GitHub Releases 页面，供手动下载与更新提示复用。
RELEASES_URL = "https://github.com/Dorufoc/Sopeek/releases"

_VERSION_FILE = "SPKVERSION"
_FALLBACK_VERSION = "0.0.0"
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _read_version_lines() -> list[str]:
    """读取 ``SPKVERSION`` 的原始行（保留空行位置）。

    Returns:
        list[str]: 去除首尾空白后的行；文件缺失或读取失败时为空列表。
    """
    path = Path(get_resource_path(_VERSION_FILE))
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return []
    return [line.strip() for line in text.splitlines()]


def _normalize_version(raw: str) -> str:
    """去掉一个前导 ``v``/``V``，空值回退到 ``0.0.0``。"""
    value = raw.strip()
    if value[:1] in {"v", "V"}:
        value = value[1:]
    return value or _FALLBACK_VERSION


def get_local_version() -> str:
    """读取本地版本号。

    Returns:
        str: ``SPKVERSION`` 第一行（去掉一个前导 ``v``/``V``）；
        缺失时返回 ``0.0.0``。
    """
    lines = _read_version_lines()
    return _normalize_version(lines[0]) if lines else _FALLBACK_VERSION


def get_local_build_date() -> Optional[str]:
    """读取并校验本地构建日期。

    Returns:
        Optional[str]: 严格合法的 ``YYYY-MM-DD`` 第二行；缺失或非法时返回 ``None``。
    """
    lines = _read_version_lines()
    if len(lines) < 2:
        return None
    value = lines[1]
    if not _DATE_PATTERN.fullmatch(value):
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return value
