"""GitCode 发布资产补全（SHA256SUMS + HEAD 探测）的单元测试。"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from sopeek.services import update_service

INSTALLER = "Sopeek-2.0.0-windows-x64.exe"
GITCODE_URL = (
    "https://gitcode.com/Dorufoc/FreeAssetFilter/releases/download/nightly/"
    f"{INSTALLER}"
)
DIGEST = "a1" * 32


def test_checksums_url_derives_sibling_checksum_file() -> None:
    """GitHub / GitCode 的资产路径都能推导出同目录校验清单。"""
    assert update_service._checksums_url(GITCODE_URL) == (
        "https://gitcode.com/Dorufoc/FreeAssetFilter/releases/download/nightly/"
        "SHA256SUMS.txt"
    )
    assert update_service._checksums_url(
        f"https://github.com/Dorufoc/Sopeek/releases/download/v1.0.0/{INSTALLER}"
    ) == (
        "https://github.com/Dorufoc/Sopeek/releases/download/v1.0.0/SHA256SUMS.txt"
    )


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://gitcode.com/a/b.exe",
        "https://gitcode.com.evil.com/a/b.exe",
        "https://evil.example/a/b.exe",
    ],
)
def test_checksums_url_rejects_untrusted_urls(url: str) -> None:
    """非 https 或不受信任主机的地址不推导。"""
    assert update_service._checksums_url(url) is None


def test_parse_sha256sums_matches_exact_filename() -> None:
    """按文件名精确匹配，兼容 `*` 前缀与大写摘要。"""
    text = (
        f"{DIGEST.upper()}  {INSTALLER}\n"
        f"{'b' * 64}  other.exe\n"
    )
    assert update_service._parse_sha256sums(text, INSTALLER) == DIGEST
    assert update_service._parse_sha256sums(text, "missing.exe") is None
    assert update_service._parse_sha256sums("", INSTALLER) is None


def test_hydrate_asset_fills_missing_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺少 sha256/size 时分别从校验清单与 HEAD 探测补齐。"""
    monkeypatch.setattr(
        update_service,
        "_fetch_text",
        lambda url, timeout=20.0: f"{DIGEST}  {INSTALLER}\n",
    )
    monkeypatch.setattr(
        update_service, "_probe_remote_size", lambda url, timeout=20.0: 156_450_341
    )
    asset: dict[str, Any] = {
        "name": INSTALLER,
        "download_url": GITCODE_URL,
        "size": 0,
        "sha256": None,
    }

    update_service._hydrate_asset(asset)

    assert asset["sha256"] == DIGEST
    assert asset["size"] == 156_450_341


def test_hydrate_asset_is_noop_when_metadata_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GitHub 源已有完整元数据时不再发起任何网络请求。"""

    def _unexpected(*args: Any, **kwargs: Any) -> Optional[str]:
        raise AssertionError("不应发起网络请求")

    monkeypatch.setattr(update_service, "_fetch_text", _unexpected)
    monkeypatch.setattr(update_service, "_probe_remote_size", _unexpected)
    asset: dict[str, Any] = {
        "name": INSTALLER,
        "download_url": GITCODE_URL,
        "size": 1,
        "sha256": DIGEST,
    }

    update_service._hydrate_asset(asset)

    assert asset["sha256"] == DIGEST
    assert asset["size"] == 1


def test_hydrate_asset_keeps_values_when_probes_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """探测失败时保持原值，交给后续下载给出明确错误。"""
    monkeypatch.setattr(update_service, "_fetch_text", lambda url, timeout=20.0: None)
    monkeypatch.setattr(
        update_service, "_probe_remote_size", lambda url, timeout=20.0: 0
    )
    asset: dict[str, Any] = {
        "name": INSTALLER,
        "download_url": GITCODE_URL,
        "size": 0,
        "sha256": None,
    }

    update_service._hydrate_asset(asset)

    assert asset["sha256"] is None
    assert asset["size"] == 0
