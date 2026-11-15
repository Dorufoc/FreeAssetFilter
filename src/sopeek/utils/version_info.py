"""本地版本号与发布页地址。

版本信息以仓库根目录的 ``SPKVERSION`` 为唯一来源：第一行为版本号，
第二行为构建日期。读取失败时使用安全的 ``0.0.0`` / ``None`` 回退，
避免更新检查因打包缺文件而崩溃。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from sopeek.utils.path_utils import get_resource_path

#: 当前程序（产品）名称，用于优先匹配同名 GitHub 仓库。
PROGRAM_NAME = "Sopeek"

#: GitHub 仓库所有者。
REPO_OWNER = "Dorufoc"

#: 程序同名仓库不存在（HTTP 404）时的回退仓库名。
FALLBACK_REPO_NAME = "FreeAssetFilter"

#: 更新检查仓库候选（``owner/name``）：优先与当前程序同名的仓库，
#: 该仓库返回 404 时回退到 ``FreeAssetFilter``。
REPO_CANDIDATES: tuple[str, ...] = (
    f"{REPO_OWNER}/{PROGRAM_NAME}",
    f"{REPO_OWNER}/{FALLBACK_REPO_NAME}",
)

#: GitHub Releases 页面，供手动下载与更新提示复用。
RELEASES_URL = f"https://github.com/{REPO_CANDIDATES[0]}/releases"

#: 更新对话框中允许打开的发布页前缀（覆盖全部候选仓库）。
RELEASE_URL_PREFIXES: tuple[str, ...] = tuple(
    f"https://github.com/{repo}/releases/" for repo in REPO_CANDIDATES
)


@dataclass(frozen=True)
class UpdateSource:
    """一个可选更新源（API 基地址 + 仓库候选 + 发布页）。

    Attributes:
        key: 设置值（``update.source``）使用的稳定标识。
        label: 设置页下拉展示文案。
        api_base: ``spk_updater`` ``check`` 使用的 API 基地址；原生端只接受
            白名单内的固定地址（GitHub 官方或 GitCode v5）。
        repos: ``owner/name`` 候选仓库；首个返回 404 时按顺序回退。
        releases_url: 发布页首页（结果缺少 ``html_url`` 时的兜底链接）。
    """

    key: str
    label: str
    api_base: str
    repos: tuple[str, ...]
    releases_url: str


#: GitHub 官方源（默认）。
GITHUB_SOURCE: UpdateSource = UpdateSource(
    key="github",
    label="GitHub（官方）",
    api_base="https://api.github.com",
    repos=REPO_CANDIDATES,
    releases_url=RELEASES_URL,
)

#: GitCode 国内镜像源（Gitee 风格的 v5 API，发布列表字段与 GitHub 兼容）。
GITCODE_SOURCE: UpdateSource = UpdateSource(
    key="gitcode",
    label="GitCode（国内）",
    api_base="https://gitcode.com/api/v5",
    repos=(f"{REPO_OWNER}/{FALLBACK_REPO_NAME}",),
    releases_url=f"https://gitcode.com/{REPO_OWNER}/{FALLBACK_REPO_NAME}/releases",
)

#: 全部可选更新源（顺序即设置页下拉顺序）。
UPDATE_SOURCES: dict[str, UpdateSource] = {
    source.key: source for source in (GITHUB_SOURCE, GITCODE_SOURCE)
}

#: 默认更新源。
DEFAULT_UPDATE_SOURCE: str = GITHUB_SOURCE.key


def get_update_source(key: object) -> UpdateSource:
    """按设置值解析更新源。

    Args:
        key: ``update.source`` 的设置值；大小写与空白会被忽略。

    Returns:
        UpdateSource: 匹配的更新源；未知/非法值回退 :data:`DEFAULT_UPDATE_SOURCE`。
    """
    if isinstance(key, str):
        source = UPDATE_SOURCES.get(key.strip().lower())
        if source is not None:
            return source
    return UPDATE_SOURCES[DEFAULT_UPDATE_SOURCE]

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
