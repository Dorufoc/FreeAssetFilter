#!/usr/bin/env python3
"""把 GitHub Release 的发布资产镜像到 GitCode Release。

背景：GitCode 托管 Runner 只有 Linux（Ubuntu / openEuler），而本项目发布包
必须在 Windows 上构建（PyInstaller + NSIS + MinGW）。因此 GitCode 侧不重建，
而是把 GitHub Actions 已构建好的同款资产（安装包 + ``SHA256SUMS.txt``）原样
发布到 GitCode 的同名 Release，保证两个平台的发行资产完全一致。

用法（在 GitCode 流水线中由 ``.gitcode/workflows/mirror-release.yml`` 调用）::

    GITCODE_TOKEN=xxx python3 tools/mirror_release_to_gitcode.py --channel auto

环境变量：
    GITCODE_TOKEN / ATOMGIT_TOKEN  GitCode 访问令牌（写 Release 必需）。
    GH_TOKEN                       可选，GitHub 令牌（提高 API 限流额度）。

退出码：0 成功（含“已是最新、跳过”）；非 0 表示失败。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Optional

GITHUB_API_BASE = "https://api.github.com"
GITCODE_API_BASE = "https://api.gitcode.com/api/v5"

DEFAULT_GITHUB_REPO = "Dorufoc/FreeAssetFilter"
DEFAULT_GITCODE_REPO = "Dorufoc/FreeAssetFilter"
DEFAULT_NIGHTLY_TAG = "nightly"

#: 从 GitHub Release 中挑选要镜像的资产：最终安装包 + 校验值清单。
INSTALLER_PATTERN = re.compile(r"^Sopeek-.+\.exe$", re.IGNORECASE)
CHECKSUM_ASSET_NAME = "SHA256SUMS.txt"

#: 单次下载/上传的超时（秒）。
HTTP_TIMEOUT = 300


class MirrorError(RuntimeError):
    """镜像流程中的可预期失败（缺少令牌、资产不完整等）。"""


def log(message: str) -> None:
    """输出带统一前缀的进度日志。

    Args:
        message: 日志正文。
    """
    print(f"[mirror] {message}", flush=True)


def _request(
    method: str,
    url: str,
    *,
    data: Any = None,
    headers: Optional[dict[str, str]] = None,
    timeout: int = 60,
) -> tuple[int, bytes]:
    """发送 HTTP 请求并返回状态码与响应体（不因 4xx/5xx 抛异常）。

    Args:
        method: HTTP 方法。
        url: 完整 URL。
        data: 请求体；``None`` 表示无请求体。文件对象会以流式发送。
        headers: 附加请求头。
        timeout: 超时秒数。

    Returns:
        tuple[int, bytes]: ``(状态码, 响应体)``；网络级失败返回 ``(0, 错误描述)``。
    """
    request = urllib.request.Request(
        url, data=data, method=method, headers=headers or {}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except urllib.error.URLError as error:
        return 0, str(error.reason).encode("utf-8", "replace")


def _github_get(path: str, token: str) -> Any:
    """调用 GitHub REST API 并解析 JSON。

    Args:
        path: 以 ``/`` 开头的 API 路径。
        token: 可选 GitHub 令牌；为空时匿名请求。

    Returns:
        Any: 解析后的 JSON。

    Raises:
        MirrorError: 请求失败或响应不是 JSON。
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Sopeek-Mirror",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    status, body = _request("GET", f"{GITHUB_API_BASE}{path}", headers=headers)
    if status != 200:
        raise MirrorError(
            f"GitHub API {path} 返回 HTTP {status}: {body[:300]!r}"
        )
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise MirrorError(f"GitHub API {path} 返回非 JSON: {error}") from error


def _gitcode_url(path: str, token: str) -> str:
    """拼接 GitCode API URL（``access_token`` 以查询参数形式传递，与官方文档一致）。

    Args:
        path: 以 ``/`` 开头的 API 路径。
        token: GitCode 访问令牌。

    Returns:
        str: 完整 URL。
    """
    query = urllib.parse.urlencode({"access_token": token})
    return f"{GITCODE_API_BASE}{path}?{query}"


def _gitcode_request(
    method: str, path: str, token: str, **kwargs: Any
) -> tuple[int, bytes]:
    """调用 GitCode API。

    Args:
        method: HTTP 方法。
        path: 以 ``/`` 开头的 API 路径。
        token: GitCode 访问令牌。
        **kwargs: 透传给 :func:`_request` 的额外参数。

    Returns:
        tuple[int, bytes]: ``(状态码, 响应体)``。
    """
    headers = kwargs.pop("headers", {}) or {}
    headers.setdefault("Accept", "application/json")
    headers.setdefault("User-Agent", "Sopeek-Mirror")
    return _request(
        method, _gitcode_url(path, token), headers=headers, **kwargs
    )


def _release_exists(repo: str, tag: str, token: str) -> bool:
    """判断 GitCode 上是否已存在指定 tag 的 Release。

    Args:
        repo: ``owner/name``。
        tag: Release tag。
        token: GitCode 访问令牌。

    Returns:
        bool: 存在返回 True；其它状态码（含 404）返回 False。

    Raises:
        MirrorError: 令牌无效等非 404 的鉴权失败。
    """
    status, body = _gitcode_request("GET", f"/repos/{repo}/releases/{tag}", token)
    if status == 200:
        return True
    if status in (401, 403):
        raise MirrorError(
            f"GitCode 鉴权失败（HTTP {status}），请检查 GITCODE_TOKEN: {body[:300]!r}"
        )
    if status == 404:
        return False
    raise MirrorError(f"查询 GitCode Release 失败（HTTP {status}）: {body[:300]!r}")


def _delete_release(repo: str, tag: str, token: str) -> None:
    """删除 GitCode 上指定 tag 的 Release（不存在视为成功）。

    Args:
        repo: ``owner/name``。
        tag: Release tag。
        token: GitCode 访问令牌。

    Raises:
        MirrorError: 删除失败（非 2xx 且非 404）。
    """
    status, body = _gitcode_request(
        "DELETE", f"/repos/{repo}/releases/{tag}", token
    )
    if status in (200, 204, 404):
        log(f"已删除旧的 Release {tag}（HTTP {status}）")
        return
    raise MirrorError(f"删除 Release {tag} 失败（HTTP {status}）: {body[:300]!r}")


def _delete_tag_best_effort(repo: str, tag: str, token: str) -> None:
    """尽力删除同名 tag，让新建的 Release 能指向最新提交。

    GitCode 的 tag 删除接口不在公开文档中，失败不影响主流程；若 tag 仍存在，
    创建 Release 时会回退为不带 ``target_commitish``。

    Args:
        repo: ``owner/name``。
        tag: tag 名称。
        token: GitCode 访问令牌。
    """
    status, _body = _gitcode_request("DELETE", f"/repos/{repo}/tags/{tag}", token)
    log(f"清理 tag {tag} 结果：HTTP {status}")


def _select_assets(release: dict[str, Any]) -> list[dict[str, Any]]:
    """从 GitHub Release JSON 中挑选需要镜像的资产。

    Args:
        release: GitHub Release 对象。

    Returns:
        list[dict[str, Any]]: 安装包与 ``SHA256SUMS.txt`` 资产列表。

    Raises:
        MirrorError: 缺少安装包或校验值清单。
    """
    assets = [asset for asset in release.get("assets") or [] if isinstance(asset, dict)]
    installers = [
        asset
        for asset in assets
        if INSTALLER_PATTERN.match(str(asset.get("name", "")))
    ]
    checksum = [
        asset
        for asset in assets
        if asset.get("name") == CHECKSUM_ASSET_NAME
    ]
    if not installers:
        raise MirrorError("GitHub Release 中没有形如 Sopeek-<版本>-windows-<架构>.exe 的安装包")
    if not checksum:
        raise MirrorError(f"GitHub Release 中缺少 {CHECKSUM_ASSET_NAME}")
    return installers + checksum


def _download_assets(
    assets: Iterable[dict[str, Any]], work_dir: Path
) -> list[Path]:
    """下载资产到工作目录。

    Args:
        assets: GitHub 资产对象（含 ``name`` / ``browser_download_url``）。
        work_dir: 下载目录。

    Returns:
        list[Path]: 下载后的本地文件列表。

    Raises:
        MirrorError: 下载失败或文件为空。
    """
    downloaded: list[Path] = []
    for asset in assets:
        name = str(asset["name"])
        url = str(asset["browser_download_url"])
        target = work_dir / name
        log(f"下载 {name} ...")
        request = urllib.request.Request(
            url, headers={"User-Agent": "Sopeek-Mirror"}
        )
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
                if response.status != 200:
                    raise MirrorError(f"下载 {name} 失败（HTTP {response.status}）")
                with target.open("wb") as handle:
                    shutil.copyfileobj(response, handle, length=1024 * 1024)
        except urllib.error.HTTPError as error:
            raise MirrorError(f"下载 {name} 失败（HTTP {error.code}）") from error
        except urllib.error.URLError as error:
            raise MirrorError(f"下载 {name} 失败：{error.reason}") from error
        if target.stat().st_size <= 0:
            raise MirrorError(f"下载的 {name} 为空文件")
        downloaded.append(target)
    return downloaded


def _sha256_file(path: Path) -> str:
    """以流式方式计算文件的 SHA256。

    Args:
        path: 文件路径。

    Returns:
        str: 小写十六进制摘要。
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_checksums(work_dir: Path) -> None:
    """按 ``SHA256SUMS.txt`` 校验下载到的安装包。

    Args:
        work_dir: 资产所在目录。

    Raises:
        MirrorError: 清单缺失、为空或校验不一致。
    """
    sums_path = work_dir / CHECKSUM_ASSET_NAME
    if not sums_path.is_file():
        raise MirrorError(f"缺少 {CHECKSUM_ASSET_NAME}")
    lines = [
        line.strip()
        for line in sums_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    ]
    if not lines:
        raise MirrorError(f"{CHECKSUM_ASSET_NAME} 为空")
    for line in lines:
        match = re.match(r"^([0-9A-Fa-f]{64})\s+\*?(.+)$", line)
        if not match:
            raise MirrorError(f"无法解析校验行：{line!r}")
        expected, name = match.group(1).lower(), match.group(2).strip()
        target = work_dir / name
        if not target.is_file():
            raise MirrorError(f"校验清单指向不存在的文件：{name}")
        digest = _sha256_file(target)
        if digest != expected:
            raise MirrorError(f"{name} 校验失败：期望 {expected}，实际 {digest}")
    log("SHA256 校验通过")


def _create_release(
    repo: str,
    tag: str,
    name: str,
    body: str,
    prerelease: bool,
    target_commitish: str,
    token: str,
) -> None:
    """在 GitCode 创建 Release；tag 已存在时回退为不带目标提交的创建方式。

    Args:
        repo: ``owner/name``。
        tag: Release tag。
        name: Release 标题。
        body: Release 说明（与 GitHub 完全一致）。
        prerelease: 是否预发布（nightly 为 True）。
        target_commitish: 目标提交；为空则不带该字段。
        token: GitCode 访问令牌。

    Raises:
        MirrorError: 两种创建方式都失败。
    """
    base_payload: dict[str, Any] = {
        "tag_name": tag,
        "name": name,
        "body": body,
        "prerelease": prerelease,
    }
    attempts: list[dict[str, Any]] = []
    if target_commitish:
        attempts.append({**base_payload, "target_commitish": target_commitish})
    attempts.append(base_payload)

    last_error = ""
    for index, payload in enumerate(attempts):
        status, body_bytes = _gitcode_request(
            "POST",
            f"/repos/{repo}/releases",
            token,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        if status in (200, 201):
            log(f"已创建 GitCode Release {tag}")
            return
        last_error = f"HTTP {status}: {body_bytes[:300]!r}"
        if index < len(attempts) - 1:
            log(f"创建 Release {tag} 失败（{last_error}），回退为默认目标后重试")
    raise MirrorError(f"创建 Release {tag} 失败：{last_error}")


def _upload_asset(
    repo: str, tag: str, token: str, file_path: Path
) -> None:
    """上传单个资产：先取 OBS 上传地址，再用 PUT 直传。

    Args:
        repo: ``owner/name``。
        tag: Release tag。
        token: GitCode 访问令牌。
        file_path: 待上传文件。

    Raises:
        MirrorError: 取上传地址或上传失败。
    """
    query = urllib.parse.urlencode(
        {"access_token": token, "file_name": file_path.name}
    )
    status, body = _request(
        "GET",
        f"{GITCODE_API_BASE}/repos/{repo}/releases/{tag}/upload_url?{query}",
        headers={"Accept": "application/json", "User-Agent": "Sopeek-Mirror"},
    )
    if status != 200:
        raise MirrorError(
            f"获取 {file_path.name} 上传地址失败（HTTP {status}）: {body[:300]!r}"
        )
    try:
        upload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise MirrorError(f"上传地址响应不是 JSON: {error}") from error

    upload_url = str(upload.get("url") or "")
    upload_headers = {
        str(key): str(value)
        for key, value in (upload.get("headers") or {}).items()
    }
    if not upload_url:
        raise MirrorError(f"{file_path.name} 上传地址为空")

    size = file_path.stat().st_size
    upload_headers["Content-Length"] = str(size)
    log(f"上传 {file_path.name}（{size} 字节）...")
    with file_path.open("rb") as handle:
        status, response = _request(
            "PUT",
            upload_url,
            data=handle,
            headers=upload_headers,
            timeout=HTTP_TIMEOUT,
        )
    if status not in (200, 201, 204):
        raise MirrorError(
            f"上传 {file_path.name} 失败（HTTP {status}）: {response[:300]!r}"
        )


def _remote_asset_names(repo: str, tag: str, token: str) -> set[str]:
    """读取 GitCode Release 当前的资产名集合。

    Args:
        repo: ``owner/name``。
        tag: Release tag。
        token: GitCode 访问令牌。

    Returns:
        set[str]: 资产文件名集合；查询失败时为空集。
    """
    status, body = _gitcode_request("GET", f"/repos/{repo}/releases/{tag}", token)
    if status != 200:
        return set()
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return set()
    return {
        str(asset.get("name"))
        for asset in payload.get("assets") or []
        if isinstance(asset, dict)
    }


def _resolve_targets(
    channel: str, tag_input: str, github_repo: str, gh_token: str
) -> list[str]:
    """解析本次需要镜像的 GitHub Release tag 列表。

    Args:
        channel: ``auto`` / ``nightly`` / ``stable`` / ``all``。
        tag_input: 手动指定的 tag；非空时只镜像该 tag。
        github_repo: GitHub ``owner/name``。
        gh_token: GitHub 令牌（可空）。

    Returns:
        list[str]: 去重后的 tag 列表。

    Raises:
        MirrorError: 无法解析出任何 tag。
    """
    if tag_input.strip():
        return [tag_input.strip()]

    targets: list[str] = []
    if channel in ("auto", "nightly"):
        targets.append(DEFAULT_NIGHTLY_TAG)
    if channel == "all":
        releases = _github_get(
            f"/repos/{github_repo}/releases?per_page=100", gh_token
        )
        for release in releases if isinstance(releases, list) else []:
            if not isinstance(release, dict) or release.get("draft"):
                continue
            tag = str(release.get("tag_name") or "").strip()
            if tag and tag not in targets:
                targets.append(tag)
    if channel in ("auto", "stable"):
        try:
            latest = _github_get(
                f"/repos/{github_repo}/releases/latest", gh_token
            )
        except MirrorError as error:
            # auto 通道下夜间版仍应镜像；只有显式 stable 才视为失败。
            if channel == "stable":
                raise
            log(f"跳过正式版（未取到 GitHub 最新正式发布）：{error}")
        else:
            latest_tag = str(latest.get("tag_name") or "").strip()
            if latest_tag and latest_tag not in targets:
                targets.append(latest_tag)
    if not targets:
        raise MirrorError("未能解析出需要镜像的 Release tag")
    return targets


def mirror_release(
    github_repo: str,
    gitcode_repo: str,
    tag: str,
    token: str,
    gh_token: str,
    work_dir: Path,
    *,
    dry_run: bool,
) -> str:
    """把一个 GitHub Release 镜像到 GitCode。

    Args:
        github_repo: GitHub ``owner/name``。
        gitcode_repo: GitCode ``owner/name``。
        tag: Release tag。
        token: GitCode 访问令牌。
        gh_token: GitHub 令牌（可空）。
        work_dir: 下载与校验的工作目录。
        dry_run: 为 True 时只解析并打印计划，不写 GitCode。

    Returns:
        str: 结果描述（用于汇总）。

    Raises:
        MirrorError: 任何一步失败。
    """
    release = _github_get(f"/repos/{github_repo}/releases/tags/{tag}", gh_token)
    name = str(release.get("name") or tag)
    body = str(release.get("body") or "")
    prerelease = bool(release.get("prerelease"))
    target_commitish = str(release.get("target_commitish") or "")
    assets = _select_assets(release)
    asset_names = sorted(str(asset["name"]) for asset in assets)

    log(f"源 Release：{tag}（{name}，prerelease={prerelease}）")
    log(f"资产：{', '.join(asset_names)}")

    if token and _release_exists(gitcode_repo, tag, token):
        if not prerelease:
            log(f"GitCode 已存在正式版 {tag}，跳过（正式版不做静默覆盖）")
            return f"{tag}: 已存在，跳过"
        log(f"GitCode 已存在 {tag}，按 nightly 语义覆盖")
        if not dry_run:
            _delete_release(gitcode_repo, tag, token)
            _delete_tag_best_effort(gitcode_repo, tag, token)

    if dry_run:
        log("dry-run：跳过下载与写操作")
        return f"{tag}: 计划镜像 {len(asset_names)} 个资产"

    files = _download_assets(assets, work_dir)
    _verify_checksums(work_dir)

    _create_release(
        gitcode_repo, tag, name, body, prerelease, target_commitish, token
    )
    for file_path in files:
        _upload_asset(gitcode_repo, tag, token, file_path)

    expected = {file_path.name for file_path in files}
    actual = _remote_asset_names(gitcode_repo, tag, token)
    missing = sorted(expected - actual)
    if missing:
        raise MirrorError(f"上传后校验失败，GitCode 缺少资产：{', '.join(missing)}")
    log(f"镜像完成：{tag}（{len(files)} 个资产与 GitHub 一致）")
    return f"{tag}: 已镜像 {len(files)} 个资产"


def _summary_line(text: str) -> None:
    """把一行汇总写入流水线步骤摘要（若平台提供）。

    Args:
        text: Markdown 文本。
    """
    summary = os.environ.get("ATOMGIT_STEP_SUMMARY")
    if not summary:
        return
    try:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError:
        pass


def main(argv: Optional[list[str]] = None) -> int:
    """脚本入口。

    Args:
        argv: 命令行参数；默认取 ``sys.argv[1:]``。

    Returns:
        int: 进程退出码。
    """
    parser = argparse.ArgumentParser(description="镜像 GitHub Release 到 GitCode")
    parser.add_argument(
        "--channel",
        choices=("auto", "nightly", "stable", "all"),
        default=os.environ.get("CHANNEL") or "auto",
        help="auto=nightly + 最新正式版；nightly=仅夜间版；stable=仅最新正式版；"
        "all=遍历全部 GitHub Release（用于一次性补齐历史版本）",
    )
    parser.add_argument(
        "--tag",
        default=os.environ.get("TAG_INPUT") or "",
        help="指定 GitHub Release tag（留空按通道自动解析）",
    )
    parser.add_argument(
        "--github-repo", default=os.environ.get("GH_REPO") or DEFAULT_GITHUB_REPO
    )
    parser.add_argument(
        "--gitcode-repo",
        default=os.environ.get("GITCODE_REPO")
        or os.environ.get("ATOMGIT_REPOSITORY")
        or DEFAULT_GITCODE_REPO,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=os.environ.get("DRY_RUN") == "1",
        help="只解析并打印计划，不下载、不写 GitCode",
    )
    args = parser.parse_args(argv)

    token = (os.environ.get("GITCODE_TOKEN") or os.environ.get("ATOMGIT_TOKEN") or "").strip()
    gh_token = (os.environ.get("GH_TOKEN") or "").strip()
    if not token and not args.dry_run:
        log(
            "缺少 GitCode 令牌：请在 GitCode 仓库设置里添加 Secret "
            "GITCODE_TOKEN（需要仓库写权限），或依赖流水线自带的 ATOMGIT_TOKEN。"
        )
        return 2

    work_dir = Path(tempfile.mkdtemp(prefix="sopeek-mirror-"))
    results: list[str] = []
    try:
        targets = _resolve_targets(
            args.channel, args.tag, args.github_repo, gh_token
        )

        for tag in targets:
            results.append(
                mirror_release(
                    args.github_repo,
                    args.gitcode_repo,
                    tag,
                    token,
                    gh_token,
                    work_dir,
                    dry_run=args.dry_run,
                )
            )
    except MirrorError as error:
        log(f"失败：{error}")
        _summary_line(f"- ❌ 镜像失败：{error}")
        return 1
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    for line in results:
        log(line)
        _summary_line(f"- ✅ {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
