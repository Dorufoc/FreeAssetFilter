#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 更新管理模块

功能：
- 读取本地 FAFVERSION
- 获取 GitHub Releases 发布信息
- 比较构建日期与版本号
- 自动选择 exe 安装包
- 自动发现并解析 SHA256 校验信息
- 管理 data/download 安装包缓存
"""

import os
import re
import json
import html
import random
import hashlib
from datetime import datetime
from xml.etree import ElementTree

from urllib import request, error as urllib_error

from freeassetfilter.utils.app_logger import info, warning, error
from freeassetfilter.utils.path_utils import get_app_data_path, get_resource_path


GITHUB_USER = "Dorufoc"
GITHUB_REPO = "FreeAssetFilter"
GITHUB_RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/releases"
GITHUB_RELEASES_LATEST_URL = f"https://github.com/{GITHUB_USER}/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_ATOM_URL = f"https://github.com/{GITHUB_USER}/{GITHUB_REPO}/releases.atom"
GITHUB_RELEASES_EXPANDED_ASSETS_URL = f"https://github.com/{GITHUB_USER}/{GITHUB_REPO}/releases/expanded_assets"
CHROME_MAJOR_VERSIONS = [132, 133, 134, 135, 136]
EDGE_MAJOR_VERSIONS = [132, 133, 134, 135, 136]
FIREFOX_MAJOR_VERSIONS = [133, 134, 135, 136, 137]

REQUEST_ACCEPT_HEADER = "application/vnd.github+json"

def _find_fafversion_file():
    """
    查找 FAFVERSION 文件，支持多种路径策略
    
    Returns:
        str: FAFVERSION 文件的完整路径，如果找不到则返回 None
    """
    import sys
    
    # 策略 1: 使用 get_resource_path
    path1 = get_resource_path("FAFVERSION")
    if os.path.exists(path1):
        return path1
    
    # 策略 2: 打包环境下，尝试 exe 所在目录
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        path2 = os.path.join(exe_dir, "FAFVERSION")
        if os.path.exists(path2):
            return path2
        
        # 策略 3: 尝试 _internal 目录
        path3 = os.path.join(exe_dir, "_internal", "FAFVERSION")
        if os.path.exists(path3):
            return path3
    
    # 策略 4: 尝试当前工作目录
    path4 = os.path.join(os.getcwd(), "FAFVERSION")
    if os.path.exists(path4):
        return path4

    # 策略 5: 所有路径都找不到时，创建默认版本文件
    create_path = None
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        create_path = os.path.join(exe_dir, "FAFVERSION")
    else:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        create_path = os.path.join(project_root, "FAFVERSION")

    try:
        os.makedirs(os.path.dirname(create_path), exist_ok=True)
        with open(create_path, "w", encoding="utf-8") as f:
            f.write("v1\n")
            f.write("1970-01-01\n")
        info(f"已创建默认版本文件: {create_path}")
        return create_path
    except (OSError, IOError) as e:
        warning(f"创建版本文件失败: {e}")
        return None

FAFVERSION_FILE = _find_fafversion_file() or get_resource_path("FAFVERSION")

CACHE_DIR_NAME = "download"
CACHE_METADATA_FILE = "update_cache.json"

TAG_PATTERN = re.compile(
    r"^(v)(\d+)\.(\d+)\.(\d+)(?:-([A-Za-z]+)(?:\.(\d+))?)?$"
)

CHECKSUM_ASSET_PATTERNS = (
    ".exe.sha256",
    ".sha256",
    ".sha256.txt",
    "sha256sums",
    "checksums",
)

CHECKSUM_LINE_PATTERNS = (
    re.compile(r"^\s*([a-fA-F0-9]{64})\s+[* ]?(.+?)\s*$"),
    re.compile(r"^\s*(.+?)\s*[:=]\s*([a-fA-F0-9]{64})\s*$"),
)

ASSET_DIGEST_PATTERN = re.compile(r"^sha256:([a-fA-F0-9]{64})$")
ASSET_ROW_PATTERN = re.compile(
    r'<a href="(?P<href>/Dorufoc/FreeAssetFilter/releases/download/[^"]+\.exe)"[^>]*>.*?'
    r'<span[^>]*class="Truncate-text text-bold"[^>]*>(?P<name>[^<]+)</span>.*?'
    r'sha256:(?P<sha256>[a-fA-F0-9]{64}).*?'
    r'(?P<size>\d+(?:\.\d+)?)\s*(?P<size_unit>KB|MB|GB|TB)',
    re.IGNORECASE | re.DOTALL,
)

STAGE_ORDER = {
    "alpha": 0,
    "beta": 1,
    "rc": 2,
    "release": 3,
}


class UpdateError(Exception):
    """
    更新流程错误
    """


def get_cache_dir():
    """
    获取安装包缓存目录
    """
    cache_dir = os.path.join(get_app_data_path(), CACHE_DIR_NAME)
    os.makedirs(cache_dir, exist_ok=True)
    info(f"缓存目录: {cache_dir}")
    return cache_dir


def get_cache_metadata_path():
    """
    获取缓存元数据文件路径
    """
    return os.path.join(get_cache_dir(), CACHE_METADATA_FILE)


def load_local_version_info():
    """
    读取本地 FAFVERSION

    Returns:
        dict: {
            tag_name,
            build_date,
            build_date_obj,
        }
    """
    info("读取本地版本信息")

    if not os.path.exists(FAFVERSION_FILE):
        error(f"版本文件不存在: {FAFVERSION_FILE}")
        raise UpdateError(f"未找到版本文件：{FAFVERSION_FILE}")

    try:
        with open(FAFVERSION_FILE, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
    except OSError as e:
        error(f"读取版本文件失败: {e}")
        raise UpdateError(f"读取版本文件失败：{e}") from e

    if len(lines) < 2:
        error("FAFVERSION 格式无效")
        raise UpdateError("FAFVERSION 格式无效，应包含版本号和构建日期两行")

    tag_name = lines[0]
    build_date = lines[1]
    build_date_obj = parse_date(build_date)

    info(f"本地版本: {tag_name}, 构建日期: {build_date}")

    return {
        "tag_name": tag_name,
        "build_date": build_date,
        "build_date_obj": build_date_obj,
    }


def get_app_version(default="未知版本"):
    """
    获取当前应用版本号。

    版本信息统一由更新管理器提供，避免在其他模块重复读取 FAFVERSION。

    Args:
        default: 读取失败时返回的默认值

    Returns:
        str: 当前版本号
    """
    try:
        version = load_local_version_info()["tag_name"]
        return version
    except UpdateError as e:
        warning(f"读取应用版本失败: {e}")
        return default


def parse_date(date_text):
    """
    解析 YYYY-MM-DD 日期
    """
    if not isinstance(date_text, str) or not date_text.strip():
        error("日期内容为空")
        raise UpdateError("日期内容为空")

    try:
        result = datetime.strptime(date_text.strip(), "%Y-%m-%d").date()
        return result
    except ValueError as e:
        error(f"日期格式无效: {date_text}")
        raise UpdateError(f"日期格式无效：{date_text}") from e


def parse_tag_version(tag_name):
    """
    解析版本号，支持：
    - v1.0.0
    - v1.0.0-alpha.4
    - v1.0.0-beta.2

    Returns:
        tuple: (major, minor, patch, stage_rank, stage_number)
    """
    if not isinstance(tag_name, str) or not tag_name.strip():
        error("版本号为空")
        raise UpdateError("版本号为空")

    match = TAG_PATTERN.match(tag_name.strip())
    if not match:
        error(f"无法解析版本号: {tag_name}")
        raise UpdateError(f"无法解析版本号：{tag_name}")

    _, major, minor, patch, stage_name, stage_number = match.groups()

    normalized_stage = "release"
    if stage_name:
        normalized_stage = stage_name.lower()

    stage_rank = STAGE_ORDER.get(normalized_stage)
    if stage_rank is None:
        # 未知预发布标识，按 alpha 之前处理，保证稳定版优先级最高
        stage_rank = -1

    stage_number_value = int(stage_number) if stage_number is not None else 0

    return (
        int(major),
        int(minor),
        int(patch),
        stage_rank,
        stage_number_value,
    )


def compare_version_tuples(version_a, version_b):
    """
    比较两个版本元组

    Returns:
        int: 1(a>b), 0(a=b), -1(a<b)
    """
    if version_a > version_b:
        return 1
    if version_a < version_b:
        return -1
    return 0


def compare_release_with_local(local_info, release_info):
    """
    只比较更新日期

    Returns:
        int: 1(release更新), 0(相同), -1(local更新)
    """
    local_date = local_info["build_date_obj"]
    release_date = release_info["published_date_obj"]

    if release_date > local_date:
        return 1
    if release_date < local_date:
        return -1

    return 0


def generate_random_browser_user_agent():
    """
    生成随机的现代浏览器 UA
    """
    browser_family = random.choice(["chrome", "edge", "firefox"])

    if browser_family == "chrome":
        major = random.choice(CHROME_MAJOR_VERSIONS)
        build = random.randint(1000, 6999)
        patch = random.randint(10, 220)
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{major}.0.{build}.{patch} Safari/537.36"
        )

    if browser_family == "edge":
        chrome_major = random.choice(CHROME_MAJOR_VERSIONS)
        edge_major = random.choice(EDGE_MAJOR_VERSIONS)
        chrome_build = random.randint(1000, 6999)
        chrome_patch = random.randint(10, 220)
        edge_build = random.randint(1000, 6999)
        edge_patch = random.randint(10, 220)
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{chrome_major}.0.{chrome_build}.{chrome_patch} "
            f"Safari/537.36 Edg/{edge_major}.0.{edge_build}.{edge_patch}"
        )

    major = random.choice(FIREFOX_MAJOR_VERSIONS)
    gecko_date = random.choice(["20100101", "20200101"])
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:"
        f"{major}.0) Gecko/{gecko_date} Firefox/{major}.0"
    )


def build_request_headers(accept_header=REQUEST_ACCEPT_HEADER):
    """
    为每次请求构造新的随机浏览器请求头
    """
    return {
        "Accept": accept_header,
        "User-Agent": generate_random_browser_user_agent(),
    }


def _http_get_text(url, timeout=30):
    """
    通过标准库执行 HTTP GET，请求文本内容
    """
    req = request.Request(url, headers=build_request_headers(), method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            result = response.read().decode(charset, errors="replace")
            return result
    except urllib_error.URLError as e:
        error(f"网络请求失败: {e}")
        raise UpdateError(f"网络请求失败：{e}") from e
    except OSError as e:
        error(f"网络请求失败: {e}")
        raise UpdateError(f"网络请求失败：{e}") from e


def fetch_github_releases():
    """
    保留旧接口，兼容历史调用。
    当前优先使用网页源避免 GitHub API rate limit。
    """
    info("获取 GitHub Releases (API)")

    raw_text = _http_get_text(GITHUB_RELEASES_API_URL, timeout=30)

    try:
        releases = json.loads(raw_text)
    except ValueError as e:
        error("GitHub Releases 返回无效 JSON")
        raise UpdateError("GitHub Releases 返回了无效 JSON") from e

    if not isinstance(releases, list):
        error("GitHub Releases 响应格式无效")
        raise UpdateError("GitHub Releases 响应格式无效")

    info(f"获取到 {len(releases)} 个 Release")
    return releases


def select_latest_release(releases):
    """
    保留旧接口，兼容历史调用。
    当前主流程已改为网页源抓取。
    """
    info("筛选最新 Release")

    candidates = []

    for release in releases:
        if not isinstance(release, dict):
            continue

        if release.get("draft"):
            continue

        tag_name = release.get("tag_name")
        published_at = release.get("published_at") or release.get("created_at")
        assets = release.get("assets") or []

        if not tag_name or not published_at:
            continue

        try:
            version_tuple = parse_tag_version(tag_name)
            published_date_obj, published_date = parse_github_date(published_at)
        except UpdateError:
            continue

        installer_asset = select_installer_asset(assets)
        if installer_asset is None:
            continue

        installer_sha256 = extract_sha256_from_asset_digest(installer_asset)

        checksum_asset_name = ""
        checksum_download_url = ""

        if not installer_sha256:
            checksum_asset = select_checksum_asset(assets)
            if checksum_asset is None:
                continue

            installer_sha256 = fetch_installer_sha256(
                checksum_download_url=checksum_asset["browser_download_url"],
                installer_name=installer_asset["name"],
            )
            if not installer_sha256:
                continue

            checksum_asset_name = checksum_asset["name"]
            checksum_download_url = checksum_asset["browser_download_url"]

        candidates.append(
            {
                "release_id": release.get("id"),
                "tag_name": tag_name,
                "version_tuple": version_tuple,
                "published_at": published_at,
                "published_date": published_date,
                "published_date_obj": published_date_obj,
                "html_url": release.get("html_url", ""),
                "release_body": release.get("body", "") or "",
                "installer_name": installer_asset["name"],
                "installer_size": installer_asset.get("size", 0),
                "installer_download_url": installer_asset["browser_download_url"],
                "installer_sha256": installer_sha256.lower(),
                "checksum_asset_name": checksum_asset_name,
                "checksum_download_url": checksum_download_url,
                "is_prerelease": bool(release.get("prerelease", False)),
            }
        )

    if not candidates:
        error("未找到有效发布版本")
        raise UpdateError("未找到包含 exe 安装包且可校验 SHA256 的有效发布版本")

    candidates.sort(
        key=lambda item: item["published_date_obj"],
        reverse=True,
    )

    latest = candidates[0]
    info(f"最新版本: {latest['tag_name']}, 发布日期: {latest['published_date']}")
    return latest


def _extract_latest_tag_from_redirect():
    """
    通过 releases/latest 跳转获取最新 tag
    """
    info("获取最新版本标签")

    req = request.Request(
        GITHUB_RELEASES_LATEST_URL,
        headers=build_request_headers("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        method="GET",
    )

    try:
        with request.urlopen(req, timeout=30) as response:
            final_url = response.geturl()
    except urllib_error.URLError as e:
        error(f"获取最新发布跳转失败: {e}")
        raise UpdateError(f"获取最新发布跳转失败：{e}") from e
    except OSError as e:
        error(f"获取最新发布跳转失败: {e}")
        raise UpdateError(f"获取最新发布跳转失败：{e}") from e

    match = re.search(r"/releases/tag/([^/?#]+)", final_url)
    if not match:
        error("无法从跳转地址解析版本标签")
        raise UpdateError("无法从 latest 跳转地址解析最新版本标签")

    tag = match.group(1)
    info(f"最新版本标签: {tag}")
    return tag


def _parse_size_to_bytes(size_text, size_unit):
    """
    将 GitHub 网页中的大小文本转为字节数
    """
    try:
        value = float(size_text)
    except (TypeError, ValueError):
        return 0

    unit = str(size_unit).upper()
    factors = {
        "KB": 1024,
        "MB": 1024 ** 2,
        "GB": 1024 ** 3,
        "TB": 1024 ** 4,
    }
    factor = factors.get(unit, 1)
    return int(value * factor)


def _fetch_release_metadata_from_atom(tag_name):
    """
    从 releases.atom 中获取指定 tag 的发布时间和更新日志
    """
    info(f"获取版本元数据: {tag_name}")

    atom_text = _http_get_text(GITHUB_RELEASES_ATOM_URL, timeout=30)

    try:
        root = ElementTree.fromstring(atom_text)
    except ElementTree.ParseError as e:
        error("解析 releases.atom 失败")
        raise UpdateError("解析 releases.atom 失败") from e

    namespace = {"atom": "http://www.w3.org/2005/Atom"}

    for entry in root.findall("atom:entry", namespace):
        title_node = entry.find("atom:title", namespace)
        if title_node is None:
            continue

        entry_tag = (title_node.text or "").strip()
        if entry_tag != tag_name:
            continue

        updated_node = entry.find("atom:updated", namespace)
        content_node = entry.find("atom:content", namespace)
        link_node = entry.find("atom:link[@rel='alternate']", namespace)

        published_at = (updated_node.text or "").strip() if updated_node is not None else ""
        if not published_at:
            error(f"未找到 {tag_name} 的发布时间")
            raise UpdateError(f"在 atom 中未找到 {tag_name} 的发布时间")

        published_date_obj, published_date = parse_github_date(published_at)
        release_body_html = (content_node.text or "") if content_node is not None else ""
        release_body = html.unescape(release_body_html)
        release_body = re.sub(r"<br\s*/?>", "\n", release_body, flags=re.IGNORECASE)
        release_body = re.sub(r"</p\s*>", "\n\n", release_body, flags=re.IGNORECASE)
        release_body = re.sub(r"</h[1-6]\s*>", "\n", release_body, flags=re.IGNORECASE)
        release_body = re.sub(r"<[^>]+>", "", release_body)
        release_body = re.sub(r"\n{3,}", "\n\n", release_body).strip()

        html_url = ""
        if link_node is not None:
            html_url = link_node.attrib.get("href", "")

        info(f"获取到元数据: 发布日期={published_date}")
        return {
            "tag_name": tag_name,
            "published_at": published_at,
            "published_date": published_date,
            "published_date_obj": published_date_obj,
            "html_url": html_url,
            "release_body": release_body,
        }

    error(f"在 releases.atom 中未找到版本: {tag_name}")
    raise UpdateError(f"在 releases.atom 中未找到版本 {tag_name}")


def _fetch_installer_info_from_expanded_assets(tag_name):
    """
    从 expanded_assets 页面获取 exe、sha256 和大小
    """
    info(f"获取安装包信息: {tag_name}")

    html_text = _http_get_text(
        f"{GITHUB_RELEASES_EXPANDED_ASSETS_URL}/{tag_name}",
        timeout=30,
    )

    match = ASSET_ROW_PATTERN.search(html_text)
    if not match:
        error("解析 expanded_assets 页面失败")
        raise UpdateError("未能从 expanded_assets 页面解析安装包信息")

    installer_href = html.unescape(match.group("href"))
    installer_name = html.unescape(match.group("name")).strip()
    installer_sha256 = match.group("sha256").lower()
    installer_size = _parse_size_to_bytes(match.group("size"), match.group("size_unit"))

    if installer_href.startswith("/"):
        installer_download_url = f"https://github.com{installer_href}"
    else:
        installer_download_url = installer_href

    info(f"安装包: {installer_name}, 大小: {installer_size} bytes")
    return {
        "installer_name": installer_name,
        "installer_sha256": installer_sha256,
        "installer_size": installer_size,
        "installer_download_url": installer_download_url,
        "checksum_asset_name": "",
        "checksum_download_url": "",
    }


def fetch_latest_release_via_web():
    """
    使用 GitHub 网页源获取最新发布，避免 API rate limit
    """
    info("获取最新 Release (网页源)")

    tag_name = _extract_latest_tag_from_redirect()
    version_tuple = parse_tag_version(tag_name)

    metadata = _fetch_release_metadata_from_atom(tag_name)
    installer_info = _fetch_installer_info_from_expanded_assets(tag_name)

    info(f"获取成功: {tag_name}")
    return {
        "release_id": None,
        "tag_name": tag_name,
        "version_tuple": version_tuple,
        "published_at": metadata["published_at"],
        "published_date": metadata["published_date"],
        "published_date_obj": metadata["published_date_obj"],
        "html_url": metadata["html_url"],
        "release_body": metadata["release_body"],
        "installer_name": installer_info["installer_name"],
        "installer_size": installer_info["installer_size"],
        "installer_download_url": installer_info["installer_download_url"],
        "installer_sha256": installer_info["installer_sha256"],
        "checksum_asset_name": installer_info["checksum_asset_name"],
        "checksum_download_url": installer_info["checksum_download_url"],
        "is_prerelease": "-" in tag_name,
    }


def extract_sha256_from_asset_digest(asset):
    """
    从 GitHub release asset 的 digest 字段提取 sha256
    """
    if not isinstance(asset, dict):
        return None

    digest_value = str(asset.get("digest", "")).strip()
    if not digest_value:
        return None

    match = ASSET_DIGEST_PATTERN.match(digest_value)
    if not match:
        return None

    return match.group(1).lower()


def parse_github_date(date_text):
    """
    解析 GitHub ISO 时间，输出 date 对象和 YYYY-MM-DD
    """
    try:
        dt = datetime.strptime(date_text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as e:
        raise UpdateError(f"发布日期格式无效：{date_text}") from e

    release_date = dt.date()
    return release_date, release_date.strftime("%Y-%m-%d")


def select_installer_asset(assets):
    """
    选择 exe 安装包资产
    """
    if not isinstance(assets, list):
        return None

    exe_assets = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue

        name = asset.get("name", "")
        url = asset.get("browser_download_url", "")
        if not name or not url:
            continue

        if name.lower().endswith(".exe"):
            exe_assets.append(asset)

    if not exe_assets:
        return None

    exe_assets.sort(
        key=lambda item: (
            item.get("size", 0),
            item.get("name", ""),
        ),
        reverse=True,
    )
    return exe_assets[0]


def select_checksum_asset(assets):
    """
    选择校验文件资产
    """
    if not isinstance(assets, list):
        return None

    checksum_candidates = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue

        name = asset.get("name", "")
        url = asset.get("browser_download_url", "")
        if not name or not url:
            continue

        lower_name = name.lower()
        if any(pattern in lower_name for pattern in CHECKSUM_ASSET_PATTERNS):
            checksum_candidates.append(asset)

    if not checksum_candidates:
        return None

    checksum_candidates.sort(
        key=lambda item: (
            item.get("size", 0),
            item.get("name", ""),
        ),
        reverse=True,
    )
    return checksum_candidates[0]


def fetch_installer_sha256(checksum_download_url, installer_name):
    """
    下载并解析 checksum 文件，提取目标 exe 的 sha256
    """
    info(f"获取校验文件: {installer_name}")

    try:
        text = _http_get_text(checksum_download_url, timeout=30)
    except UpdateError as e:
        warning(f"获取校验文件失败: {e}")
        return None

    sha256 = parse_sha256_from_text(text, installer_name)
    if sha256:
        info(f"校验值获取成功")
    else:
        warning("校验值解析失败")
    return sha256


def parse_sha256_from_text(text, installer_name):
    """
    从 checksum 文本中解析指定安装包的 sha256
    """
    if not isinstance(text, str) or not isinstance(installer_name, str):
        return None

    target_name = installer_name.strip().lower()
    if not target_name:
        return None

    fallback_hash = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        for pattern in CHECKSUM_LINE_PATTERNS:
            match = pattern.match(line)
            if not match:
                continue

            if pattern is CHECKSUM_LINE_PATTERNS[0]:
                sha256_value = match.group(1).strip().lower()
                file_name = os.path.basename(match.group(2).strip()).lower()
            else:
                file_name = os.path.basename(match.group(1).strip()).lower()
                sha256_value = match.group(2).strip().lower()

            if file_name == target_name:
                return sha256_value

            if file_name.endswith(".exe") and fallback_hash is None:
                fallback_hash = (file_name, sha256_value)

    if fallback_hash and fallback_hash[0] == target_name:
        return fallback_hash[1]

    # 兼容某些只有单行哈希的情况
    stripped = text.strip().lower()
    if re.fullmatch(r"[a-f0-9]{64}", stripped):
        return stripped

    return None


def calculate_sha256(file_path, chunk_size=1024 * 1024):
    """
    计算文件 sha256
    """
    info(f"计算文件 SHA256: {os.path.basename(file_path)}")

    sha256_hash = hashlib.sha256()

    try:
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                sha256_hash.update(chunk)
    except OSError as e:
        error(f"读取文件计算 SHA256 失败: {e}")
        raise UpdateError(f"读取文件计算 SHA256 失败：{e}") from e

    result = sha256_hash.hexdigest().lower()
    info("SHA256 计算完成")
    return result


def verify_installer_file(file_path, expected_sha256):
    """
    校验安装包 sha256
    """
    if not file_path or not expected_sha256:
        warning("校验参数无效")
        return False

    if not os.path.exists(file_path):
        warning("安装包不存在")
        return False

    info(f"校验安装包: {os.path.basename(file_path)}")

    try:
        actual_sha256 = calculate_sha256(file_path)
    except UpdateError:
        error("SHA256 计算失败")
        return False

    is_valid = actual_sha256 == expected_sha256.lower()
    if is_valid:
        info("安装包校验通过")
    else:
        error("安装包校验失败")
    return is_valid


def load_cache_metadata():
    """
    读取缓存元数据
    """
    metadata_path = get_cache_metadata_path()
    if not os.path.exists(metadata_path):
        return None

    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError) as e:
        warning(f"读取缓存元数据失败: {e}")
        return None

    if not isinstance(data, dict):
        warning("缓存元数据格式无效")
        return None

    info("缓存元数据加载成功")
    return data


def save_cache_metadata(metadata):
    """
    保存缓存元数据
    """
    metadata_path = get_cache_metadata_path()
    info(f"保存缓存元数据: {metadata_path}")

    try:
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        info("缓存元数据保存成功")
    except OSError as e:
        error(f"写入缓存元数据失败: {e}")
        raise UpdateError(f"写入缓存元数据失败：{e}") from e


def clear_invalid_cache(installer_path=None):
    """
    清理无效缓存
    """
    info("清理无效缓存")

    if installer_path and os.path.exists(installer_path):
        try:
            os.remove(installer_path)
            info(f"删除安装包: {os.path.basename(installer_path)}")
        except OSError as e:
            warning(f"删除安装包失败: {e}")

    metadata_path = get_cache_metadata_path()
    if os.path.exists(metadata_path):
        try:
            os.remove(metadata_path)
            info("删除缓存元数据")
        except OSError as e:
            warning(f"删除缓存元数据失败: {e}")


def prepare_cached_installer(release_info, installer_path):
    """
    将本地已准备好的安装包写入缓存元数据
    """
    info(f"准备缓存安装包: {os.path.basename(installer_path)}")

    if not os.path.exists(installer_path):
        error("安装包不存在")
        raise UpdateError("安装包不存在，无法写入缓存")

    if not verify_installer_file(installer_path, release_info["installer_sha256"]):
        error("安装包校验失败")
        raise UpdateError("安装包 SHA256 校验失败，无法写入缓存")

    metadata = {
        "release_id": release_info.get("release_id"),
        "tag_name": release_info.get("tag_name"),
        "published_date": release_info.get("published_date"),
        "installer_name": release_info.get("installer_name"),
        "installer_download_url": release_info.get("installer_download_url"),
        "installer_sha256": release_info.get("installer_sha256"),
        "installer_path": installer_path,
        "saved_at": int(datetime.utcnow().timestamp()),
    }
    save_cache_metadata(metadata)

    result = dict(metadata)
    result["is_ready"] = True
    info("安装包缓存准备完成")
    return result


def get_cached_installer_if_valid(release_info):
    """
    如果本地已有可复用缓存，则返回缓存信息
    """
    info("检查缓存安装包")

    metadata = load_cache_metadata()
    if not metadata:
        info("未找到缓存元数据")
        return {
            "is_ready": False,
            "reason": "未找到缓存元数据",
        }

    installer_path = metadata.get("installer_path")
    expected_sha256 = metadata.get("installer_sha256")
    tag_name = metadata.get("tag_name")
    published_date = metadata.get("published_date")

    if (
        tag_name != release_info.get("tag_name")
        or published_date != release_info.get("published_date")
        or expected_sha256 != release_info.get("installer_sha256")
    ):
        info("缓存版本与最新发布不匹配")
        return {
            "is_ready": False,
            "reason": "缓存版本与最新发布不匹配",
        }

    if not installer_path or not os.path.exists(installer_path):
        warning("缓存安装包不存在")
        clear_invalid_cache()
        return {
            "is_ready": False,
            "reason": "缓存安装包不存在",
        }

    if not verify_installer_file(installer_path, expected_sha256):
        warning("缓存安装包校验失败")
        clear_invalid_cache(installer_path)
        return {
            "is_ready": False,
            "reason": "缓存安装包校验失败",
        }

    info("缓存安装包有效")
    return {
        "is_ready": True,
        "installer_path": installer_path,
        "installer_sha256": expected_sha256,
        "installer_name": metadata.get("installer_name"),
        "tag_name": tag_name,
        "published_date": published_date,
    }


def check_for_updates():
    """
    检查更新

    Returns:
        dict:
        {
            update_available,
            local_info,
            latest_release,
            cache_result,
            comparison_result,
        }
    """
    info("开始检查更新")

    local_info = load_local_version_info()

    latest_release = None
    api_error = None

    try:
        latest_release = fetch_latest_release_via_web()
    except UpdateError as web_error:
        warning(f"网页源检查更新失败，回退 API: {web_error}")
        try:
            releases = fetch_github_releases()
            latest_release = select_latest_release(releases)
        except UpdateError as fallback_error:
            api_error = fallback_error

    if latest_release is None:
        if api_error is not None:
            raise api_error
        raise UpdateError("无法获取最新发布信息")

    comparison_result = compare_release_with_local(local_info, latest_release)
    update_available = comparison_result > 0

    cache_result = {
        "is_ready": False,
        "reason": "当前无需缓存",
    }

    if update_available:
        cache_result = get_cached_installer_if_valid(latest_release)

    result = {
        "update_available": update_available,
        "comparison_result": comparison_result,
        "local_info": local_info,
        "latest_release": latest_release,
        "cache_result": cache_result,
    }

    info(
        f"更新检查完成: 本地={local_info['tag_name']}, "
        f"远程={latest_release['tag_name']}, "
        f"有更新={update_available}"
    )

    return result
