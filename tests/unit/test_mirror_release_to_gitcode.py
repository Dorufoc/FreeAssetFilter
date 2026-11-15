"""``tools/mirror_release_to_gitcode.py`` 的关键路径单元测试。"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "tools" / "mirror_release_to_gitcode.py"
)


def _load_module() -> ModuleType:
    """以文件路径加载镜像脚本模块（tools 不是可导入包）。

    Returns:
        ModuleType: 已加载的模块对象。
    """
    spec = importlib.util.spec_from_file_location(
        "mirror_release_to_gitcode", MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mirror = _load_module()


def _release(*names: str) -> dict:
    """构造仅含资产名的最小 GitHub Release 对象。"""
    return {
        "tag_name": "nightly",
        "name": "Nightly 2026-11-15",
        "body": "notes",
        "prerelease": True,
        "target_commitish": "a" * 40,
        "assets": [
            {
                "name": name,
                "browser_download_url": f"https://example.invalid/{name}",
            }
            for name in names
        ],
    }


def test_select_assets_keeps_installer_and_checksums() -> None:
    """只挑安装包与 SHA256SUMS.txt。"""
    assets = mirror._select_assets(
        _release("Sopeek-2.0.0-windows-x64.exe", "SHA256SUMS.txt", "debug.txt")
    )
    assert [asset["name"] for asset in assets] == [
        "Sopeek-2.0.0-windows-x64.exe",
        "SHA256SUMS.txt",
    ]


def test_select_assets_rejects_incomplete_release() -> None:
    """缺少安装包或校验清单时明确失败。"""
    with pytest.raises(mirror.MirrorError):
        mirror._select_assets(_release("SHA256SUMS.txt"))
    with pytest.raises(mirror.MirrorError):
        mirror._select_assets(_release("Sopeek-2.0.0-windows-x64.exe"))


def test_verify_checksums_accepts_and_rejects(tmp_path: Path) -> None:
    """校验清单匹配时通过，篡改内容时失败。"""
    installer = tmp_path / "Sopeek-2.0.0-windows-x64.exe"
    installer.write_bytes(b"sopeek")
    digest = hashlib.sha256(b"sopeek").hexdigest()
    (tmp_path / "SHA256SUMS.txt").write_text(
        f"{digest}  {installer.name}\n", encoding="ascii"
    )
    mirror._verify_checksums(tmp_path)

    installer.write_bytes(b"tampered")
    with pytest.raises(mirror.MirrorError):
        mirror._verify_checksums(tmp_path)


def test_resolve_targets_by_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    """auto/nightly/stable/all 的 tag 解析规则。"""

    def _fake_get(path: str, token: str) -> object:
        if path.endswith("/releases/latest"):
            return {"tag_name": "v2.0.0"}
        return [
            {"tag_name": "nightly"},
            {"tag_name": "v2.0.0"},
            {"tag_name": "v1.0.0"},
            {"tag_name": "draft", "draft": True},
        ]

    monkeypatch.setattr(mirror, "_github_get", _fake_get)
    assert mirror._resolve_targets("auto", "", "o/r", "") == ["nightly", "v2.0.0"]
    assert mirror._resolve_targets("all", "", "o/r", "") == [
        "nightly",
        "v2.0.0",
        "v1.0.0",
    ]
    assert mirror._resolve_targets("stable", " v9.9.9 ", "o/r", "") == ["v9.9.9"]


def test_mirror_release_dry_run_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """dry-run 只解析计划，不下载、不创建、不上传。"""
    monkeypatch.setattr(mirror, "_github_get", lambda path, token: _release(
        "Sopeek-2.0.0-windows-x64.exe", "SHA256SUMS.txt"
    ))
    called: list[str] = []
    monkeypatch.setattr(
        mirror, "_download_assets", lambda assets, work: called.append("download")
    )
    monkeypatch.setattr(
        mirror, "_create_release", lambda *args, **kwargs: called.append("create")
    )
    result = mirror.mirror_release(
        "Dorufoc/FreeAssetFilter",
        "Dorufoc/FreeAssetFilter",
        "nightly",
        token="",
        gh_token="",
        work_dir=tmp_path,
        dry_run=True,
    )
    assert "计划镜像 2 个资产" in result
    assert called == []


def test_mirror_release_uploads_same_asset_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """正式流程：创建 Release 后逐个上传，并以远端资产名回验。"""
    uploads: list[str] = []
    monkeypatch.setattr(mirror, "_github_get", lambda path, token: _release(
        "Sopeek-2.0.0-windows-x64.exe", "SHA256SUMS.txt"
    ))
    monkeypatch.setattr(mirror, "_release_exists", lambda repo, tag, token: False)

    def _fake_download(assets: list[dict], work: Path) -> list[Path]:
        files = []
        for asset in assets:
            path = work / str(asset["name"])
            path.write_bytes(b"x")
            files.append(path)
        return files

    monkeypatch.setattr(mirror, "_download_assets", _fake_download)
    monkeypatch.setattr(mirror, "_verify_checksums", lambda work: None)
    monkeypatch.setattr(mirror, "_create_release", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        mirror,
        "_upload_asset",
        lambda repo, tag, token, path: uploads.append(path.name),
    )
    monkeypatch.setattr(
        mirror,
        "_remote_asset_names",
        lambda repo, tag, token: {"SHA256SUMS.txt", "Sopeek-2.0.0-windows-x64.exe"},
    )
    result = mirror.mirror_release(
        "Dorufoc/FreeAssetFilter",
        "Dorufoc/FreeAssetFilter",
        "nightly",
        token="t",
        gh_token="",
        work_dir=tmp_path,
        dry_run=False,
    )
    assert "已镜像 2 个资产" in result
    assert uploads == ["Sopeek-2.0.0-windows-x64.exe", "SHA256SUMS.txt"]
