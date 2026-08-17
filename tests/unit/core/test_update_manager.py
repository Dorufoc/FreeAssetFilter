# -*- coding: utf-8 -*-
"""UpdateManager（core/managers/update_manager.py）单元测试。

todo-8（unit/core 批 2）验收口径：
* 版本比较（``compare_version_tuples`` 的 older / newer / equal / malformed）；
* 更新检查异常路径——**网络调用全部 mock，禁止任何真实请求**；
* 对 mock 网络异常返回可处理错误对象（``UpdateError`` / ``UpdateCancelled``），
  绝不泄漏原始 ``URLError`` / ``OSError`` 或抛出未捕获异常；
* 版本 / 日期解析、资产选择、sha256 校验、缓存元数据的纯函数矩阵。

实现约束：``_http_get_text`` 在函数体内 ``from urllib import request``，
因此 mock ``urllib.request.urlopen`` 即可拦截该函数的全部真实网络 IO；
``_extract_latest_tag_from_redirect`` 同样经 ``urllib.request.urlopen``。
``check_for_updates`` 的端到端用例通过脚本化 ``_http_get_text`` 返回
伪造的 atom / expanded_assets 页面完成，全程零网络。
"""

from __future__ import annotations

import hashlib
import os
import sys
from datetime import date
from unittest.mock import MagicMock, patch
from urllib import error as urllib_error

import pytest

import freeassetfilter.core.managers.update_manager as update_manager
from freeassetfilter.core.managers.update_manager import (
    UpdateCancelled,
    UpdateError,
    build_request_headers,
    calculate_sha256,
    check_for_updates,
    compare_release_with_local,
    compare_version_tuples,
    extract_sha256_from_asset_digest,
    fetch_github_releases,
    fetch_installer_sha256,
    fetch_latest_release_via_web,
    generate_random_browser_user_agent,
    get_app_version,
    get_cache_dir,
    get_cached_installer_if_valid,
    parse_date,
    parse_github_date,
    parse_sha256_from_text,
    _parse_size_to_bytes,
    parse_tag_version,
    prepare_cached_installer,
    save_cache_metadata,
    select_checksum_asset,
    select_installer_asset,
    select_latest_release,
    load_cache_metadata,
    load_local_version_info,
    clear_invalid_cache,
    _http_get_text,
)

#: 64 位十六进制哈希常量（mock 响应复用）
_HASH_64: str = "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0"
_EXE_NAME: str = "FreeAssetFilter-Setup-9.9.9.exe"

#: 伪造 releases.atom（够 ``_fetch_release_metadata_from_atom`` 解析即可）
_ATOM_XML: str = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<feed xmlns="http://www.w3.org/2005/Atom">'
    "<entry><title>v9.9.9</title>"
    "<updated>2099-01-01T00:00:00Z</updated>"
    "<content>Changelog v9.9.9</content>"
    '<link rel="alternate" href="https://github.com/Dorufoc/FreeAssetFilter/releases/tag/v9.9.9"/>'
    "</entry></feed>"
)

#: 伪造 expanded_assets 页面（命中 ASSET_ROW_PATTERN）
_ASSET_HTML: str = (
    '<div class="Box-body">'
    f'<a href="/Dorufoc/FreeAssetFilter/releases/download/v9.9.9/{_EXE_NAME}" '
    'class="Link--primary">'
    f'<span class="Truncate-text text-bold">{_EXE_NAME}</span>'
    f"sha256:{_HASH_64}"
    "<span>25.5 MB</span>"
    "</div>"
)


# =============================================================================
# 纯函数：版本与日期
# =============================================================================
class TestVersionParsing:
    """``parse_tag_version`` 的合法 / 边界 / 非法输入。"""

    @pytest.mark.parametrize(
        "tag, expected",
        [
            ("v1.2.3", (1, 2, 3, 3, 0)),
            ("v1.0.0-alpha.1", (1, 0, 0, 0, 1)),
            ("v1.0.0-beta.2", (1, 0, 0, 1, 2)),
            ("v1.0.0-rc.2", (1, 0, 0, 2, 2)),
            ("v0.0.1", (0, 0, 1, 3, 0)),
            ("  v1.0.0  ", (1, 0, 0, 3, 0)),  # 内部会 strip 后解析
            ("v1.0.0-foo.7", (1, 0, 0, -1, 7)),  # 未知阶段按 alpha 之前处理
        ],
    )
    def test_valid_tags(self, tag: str, expected: tuple) -> None:
        """合法 tag 解析出 (major, minor, patch, stage_rank, stage_number)。"""
        assert parse_tag_version(tag) == expected

    @pytest.mark.parametrize(
        "tag",
        ["", None, "1.0.0", "v1.0", "v1.0.0.1", "version-two", "v1.0.0-"],
    )
    def test_invalid_tags_raise_update_error(self, tag: str) -> None:
        """非法 / 空 tag 抛出可处理的 ``UpdateError``。"""
        with pytest.raises(UpdateError):
            parse_tag_version(tag)

    def test_compare_version_tuples(self) -> None:
        """``compare_version_tuples`` 的 older / newer / equal / malformed 四象限。"""
        # older
        assert compare_version_tuples((1, 9, 0), (2, 0, 0)) == -1
        assert compare_version_tuples((1, 0, 0, 0, 5), (1, 0, 0, 3, 0)) == -1
        # newer
        assert compare_version_tuples((2, 0, 0), (1, 9, 9)) == 1
        assert compare_version_tuples((1, 0, 0, 3, 0), (1, 0, 0, 0, 5)) == 1
        # equal
        assert compare_version_tuples((1, 2, 3), (1, 2, 3)) == 0
        assert compare_version_tuples((1, 2, 3, 2, 4), (1, 2, 3, 2, 4)) == 0
        # malformed（缺段元组被 Python 按字典序比较）
        assert compare_version_tuples((1, 2), (1, 2, 3)) == -1
        assert compare_version_tuples((1, 2, 3, 999), (1, 2, 3)) == 1
        assert compare_version_tuples((0,), ()) == 1

    def test_compare_release_with_local(self) -> None:
        """``compare_release_with_local`` 按发布日期三态比较。"""
        local: dict = {"build_date_obj": date(2026, 5, 22)}

        newer: dict = {"published_date_obj": date(2026, 6, 1)}
        same: dict = {"published_date_obj": date(2026, 5, 22)}
        older: dict = {"published_date_obj": date(2026, 4, 30)}

        assert compare_release_with_local(local, newer) == 1
        assert compare_release_with_local(local, same) == 0
        assert compare_release_with_local(local, older) == -1

    def test_parse_date_valid_and_invalid(self) -> None:
        """``parse_date``：合法日期返回 date，非法抛 UpdateError。"""
        assert parse_date("2026-05-22") == date(2026, 5, 22)
        with pytest.raises(UpdateError):
            parse_date("2026/05/22")
        with pytest.raises(UpdateError):
            parse_date("")
        with pytest.raises(UpdateError):
            parse_date(None)

    def test_parse_github_date(self) -> None:
        """``parse_github_date``：ISO 时间 → (date, YYYY-MM-DD)。"""
        parsed, text = parse_github_date("2026-05-22T12:30:00Z")
        assert parsed == date(2026, 5, 22)
        assert text == "2026-05-22"
        with pytest.raises(UpdateError):
            parse_github_date("22-05-2026")


# =============================================================================
# 纯函数：资产选择与 sha256
# =============================================================================
class TestAssetAndDigest:
    """installer / checksum 资产选择与 sha256 文本解析。"""

    def test_select_installer_asset_prefers_largest_exe(self) -> None:
        """多个 exe 中按 (size, name) 降序取最大；非 exe 被忽略。"""
        assets: list = [
            {"name": "note.zip", "browser_download_url": "u", "size": 1},
            {"name": "old.exe", "browser_download_url": "u", "size": 10},
            {"name": "new.exe", "browser_download_url": "u", "size": 100},
        ]
        assert select_installer_asset(assets)["name"] == "new.exe"
        assert select_installer_asset(["bad"]) is None  # 无 dict 项
        assert select_installer_asset([]) is None
        assert select_installer_asset(None) is None

    def test_select_checksum_asset(self) -> None:
        """按 CHECKSUM_ASSET_PATTERNS 筛选校验资产。"""
        assets: list = [
            {"name": "setup.exe", "browser_download_url": "u", "size": 1},
            {"name": "setup.exe.sha256", "browser_download_url": "u", "size": 5},
            {"name": "sha256sums", "browser_download_url": "u", "size": 9},
        ]
        assert select_checksum_asset(assets)["name"] == "sha256sums"
        assert select_checksum_asset([]) is None
        assert select_checksum_asset(None) is None

    def test_extract_sha256_from_asset_digest(self) -> None:
        """digest 字段 `sha256:<hex64>` 提取并小写化。"""
        digest: str = f"sha256:{'AB' * 32}"
        assert extract_sha256_from_asset_digest({"digest": digest}) == "ab" * 32
        assert extract_sha256_from_asset_digest({"digest": "md5:xyz"}) is None
        assert extract_sha256_from_asset_digest({}) is None
        assert extract_sha256_from_asset_digest("not-a-dict") is None

    def test_parse_size_to_bytes(self) -> None:
        """大小文本 → 字节；非法文本回退 0，未知单位按原值。"""
        assert _parse_size_to_bytes("2.5", "MB") == 2621440
        assert _parse_size_to_bytes("1", "KB") == 1024
        assert _parse_size_to_bytes("10", "GB") == 10 * 1024 ** 3
        assert _parse_size_to_bytes("abc", "MB") == 0
        assert _parse_size_to_bytes("5", "XX") == 5

    def test_parse_sha256_from_text(self) -> None:
        """三种行格式（hash+filename / filename:hash / 单行 hash）。"""
        target: str = _EXE_NAME.lower()
        line1: str = f"{_HASH_64}  {_EXE_NAME}"
        assert parse_sha256_from_text(line1, target) == _HASH_64.lower()

        line2: str = f"{_EXE_NAME}: {_HASH_64}"
        assert parse_sha256_from_text(line2, target) == _HASH_64.lower()

        assert parse_sha256_from_text(_HASH_64, target) == _HASH_64.lower()

        assert parse_sha256_from_text(f"{_HASH_64}  other-version.exe", target) is None
        assert parse_sha256_from_text("", target) is None
        assert parse_sha256_from_text(123, target) is None
        assert parse_sha256_from_text(line1, "not-the-target") is None

    def test_calculate_and_verify_sha256(self, tmp_path: object) -> None:
        """``calculate_sha256`` + ``verify_installer_file`` 正 / 反校验。"""
        exe: str = str(tmp_path / "installer.exe")
        with open(exe, "wb") as f:
            f.write(b"fake installer bytes")

        digest: str = calculate_sha256(exe)
        assert len(digest) == 64
        assert digest == hashlib.sha256(b"fake installer bytes").hexdigest()

        from freeassetfilter.core.managers.update_manager import verify_installer_file

        assert verify_installer_file(exe, digest.upper()) is True  # 大小写不敏感
        assert verify_installer_file(exe, "0" * 64) is False
        assert verify_installer_file(str(tmp_path / "missing.exe"), digest) is False
        assert verify_installer_file("", "") is False

    def test_browser_headers(self) -> None:
        """随机 UA 与请求头构造。"""
        ua: str = generate_random_browser_user_agent()
        assert ua.startswith("Mozilla/5.0")
        headers: dict = build_request_headers()
        assert headers["Accept"] == "application/vnd.github+json"
        assert "User-Agent" in headers


# =============================================================================
# HTTP 层（mock urlopen）
# =============================================================================
class _FakeHttpResponse:
    """模拟 ``http.client.HTTPResponse`` 的上层接口。"""

    class _Headers:
        def get_content_charset(self) -> str:
            return "utf-8"

    headers = _Headers()

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self, size: int) -> bytes:
        chunk: bytes = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class TestHttpLayer:
    """``_http_get_text`` 的成功 / 异常包装 / 取消路径（全部 mock）。"""

    def test_http_get_text_success(self) -> None:
        """正常响应：分块读取后 UTF-8 解码返回，且检查取消点被调用。"""
        payload: bytes = "网络响应内容".encode("utf-8")
        cancelled: list = []

        with patch("urllib.request.urlopen", return_value=_FakeHttpResponse(payload)) as urlopen:
            text: str = _http_get_text(
                "https://example.invalid/data", timeout=5, cancel_check=lambda: cancelled.append(1) or False
            )

        assert text == "网络响应内容"
        assert urlopen.call_count >= 1
        assert len(cancelled) >= 1

    def test_http_get_text_urlerror_wrapped(self) -> None:
        """``URLError`` 被包装为 ``UpdateError``（可处理错误对象）。"""
        with patch("urllib.request.urlopen", side_effect=urllib_error.URLError("net down")):
            with pytest.raises(UpdateError) as exc:
                _http_get_text("https://example.invalid/data")
        assert "网络请求失败" in str(exc.value)
        # 绝不泄漏原始异常类型
        assert not isinstance(exc.value, urllib_error.URLError)

    def test_http_get_text_oserror_wrapped(self) -> None:
        """``OSError`` 同样被包装为 ``UpdateError``。"""
        with patch("urllib.request.urlopen", side_effect=OSError("socket closed")):
            with pytest.raises(UpdateError):
                _http_get_text("https://example.invalid/data")

    def test_http_get_text_cancelled_before_request(self) -> None:
        """取消检查通过时请求根本不发出。"""
        with patch("urllib.request.urlopen") as urlopen:
            with pytest.raises(UpdateCancelled):
                _http_get_text(
                    "https://example.invalid/data", cancel_check=lambda: True
                )
        urlopen.assert_not_called()

    def test_fetch_github_releases_invalid_json(self) -> None:
        """API 返回非法 JSON 时抛出 ``UpdateError``。"""
        with patch.object(update_manager, "_http_get_text", return_value="not json"):
            with pytest.raises(UpdateError):
                fetch_github_releases()

    def test_fetch_github_releases_valid(self) -> None:
        """API 返回合法 JSON 列表时原样返回。"""
        with patch.object(update_manager, "_http_get_text", return_value='[{"tag_name": "v1.0.0"}]'):
            releases = fetch_github_releases()
        assert isinstance(releases, list) and len(releases) == 1


# =============================================================================
# 缓存元数据
# =============================================================================
class TestCacheMetadata:
    """缓存元数据读写 / 安装包预备 / 缓存复用判定（本地文件，无网络）。"""

    def _patch_cache_path(self, tmp_path: object):
        """把缓存元数据路径重定向到临时目录并确保父目录存在。"""
        cache_dir = str(tmp_path / "download")
        os.makedirs(cache_dir, exist_ok=True)
        return patch.object(
            update_manager,
            "get_cache_metadata_path",
            return_value=os.path.join(cache_dir, "update_cache.json"),
        )

    def test_save_load_clear_roundtrip(self, tmp_path: object) -> None:
        """写入 → 读回一致 → 清除后不存在。"""
        metadata: dict = {"tag_name": "v1.0.0", "installer_path": "C:/x.exe"}
        with self._patch_cache_path(tmp_path):
            save_cache_metadata(metadata)
            assert load_cache_metadata() == metadata
            clear_invalid_cache(installer_path="C:/x.exe")
            assert load_cache_metadata() is None

    def test_load_missing_or_corrupt(self, tmp_path: object) -> None:
        """元数据不存在或损坏时返回 None 而非抛异常。"""
        with self._patch_cache_path(tmp_path):
            assert load_cache_metadata() is None
            from freeassetfilter.core.managers.update_manager import CACHE_METADATA_FILE, get_cache_metadata_path

            path: str = os.path.join(os.path.dirname(get_cache_metadata_path()), CACHE_METADATA_FILE)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("{corrupt json")
            assert load_cache_metadata() is None

    def test_prepare_cached_installer(self, tmp_path: object) -> None:
        """准备缓存安装包：sha 匹配写元数据并返回 is_ready；不匹配抛 UpdateError。"""
        exe: str = str(tmp_path / "installer.exe")
        with open(exe, "wb") as f:
            f.write(b"installer payload")
        sha: str = calculate_sha256(exe)

        release_ok: dict = {
            "release_id": None,
            "tag_name": "v9.9.9",
            "published_date": "2099-01-01",
            "installer_name": "installer.exe",
            "installer_download_url": "https://x",
            "installer_sha256": sha,
        }
        with self._patch_cache_path(tmp_path):
            result: dict = prepare_cached_installer(release_ok, exe)
            assert result["is_ready"] is True
            assert load_cache_metadata()["tag_name"] == "v9.9.9"

            release_bad: dict = dict(release_ok)
            release_bad["installer_sha256"] = "0" * 64
            with pytest.raises(UpdateError):
                prepare_cached_installer(release_bad, exe)

    def test_get_cached_installer_if_valid(self, tmp_path: object) -> None:
        """缓存匹配返回 is_ready True；版本不匹配返回可处理假值。"""
        exe: str = str(tmp_path / "installer.exe")
        with open(exe, "wb") as f:
            f.write(b"installer payload")
        sha: str = calculate_sha256(exe)
        release: dict = {
            "release_id": None,
            "tag_name": "v9.9.9",
            "published_date": "2099-01-01",
            "installer_name": "installer.exe",
            "installer_download_url": "https://x",
            "installer_sha256": sha,
        }

        with self._patch_cache_path(tmp_path):
            # 无缓存
            assert get_cached_installer_if_valid(release)["is_ready"] is False

            # 写入有效缓存
            prepare_cached_installer(release, exe)
            valid: dict = get_cached_installer_if_valid(release)
            assert valid["is_ready"] is True

            # 版本不匹配
            stale: dict = dict(release)
            stale["tag_name"] = "v0.0.0"
            mismatch: dict = get_cached_installer_if_valid(stale)
            assert mismatch["is_ready"] is False
            assert "不匹配" in mismatch["reason"]


# =============================================================================
# 更新检查流程（端到端 mock）
# =============================================================================
class TestUpdateCheckFlows:
    """``check_for_updates`` 的三条流程：成功 / 全失败 / 取消（零网络）。"""

    @staticmethod
    def _scripted_http_get_text(url: str, timeout: int = 5, cancel_check: object = None) -> str:
        """按 URL 分发伪造响应；意外的 URL 视为测试失败。"""
        if "releases.atom" in url:
            return _ATOM_XML
        if "expanded_assets" in url:
            return _ASSET_HTML
        raise AssertionError(f"mock 收到未预期的 URL: {url}")

    def test_check_for_updates_success_mocked(
        self, tmp_path: object, qapp: object
    ) -> None:
        """网页源全程 mock 下成功返回结果 dict：有更新、缓存未就绪。"""
        class _RedirectResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc: object) -> bool:
                return False

            def geturl(self) -> str:
                return "https://github.com/Dorufoc/FreeAssetFilter/releases/tag/v9.9.9"

        with (
            patch.object(
                update_manager,
                "_http_get_text",
                side_effect=self._scripted_http_get_text,
            ) as http_mock,
            patch("urllib.request.urlopen", return_value=_RedirectResponse()) as urlopen_mock,
            patch.object(
                update_manager,
                "get_cache_metadata_path",
                return_value=str(tmp_path / "update_cache.json"),
            ),
        ):
            result: dict = check_for_updates()

        assert http_mock.call_count >= 2  # atom + expanded_assets
        assert urlopen_mock.call_count >= 1  # latest 重定向
        assert result["update_available"] is True
        assert result["latest_release"]["tag_name"] == "v9.9.9"
        assert result["latest_release"]["installer_name"] == _EXE_NAME
        assert result["latest_release"]["installer_sha256"] == _HASH_64
        assert result["comparison_result"] > 0
        assert result["cache_result"]["is_ready"] is False

    def test_check_for_updates_all_network_failures_handleable(self, qapp: object) -> None:
        """网页源 + API 回退全部失败时，返回可处理的 ``UpdateError``。

        验证 plan QA："对 mock 网络异常返回可处理错误对象而非抛未捕获异常"。
        注意：``_http_get_text`` 的 ``UpdateError``（由 mock 直接抛出）经
        ``check_for_updates`` 透传，断言类型即可——绝不泄漏原始
        ``URLError`` / ``OSError``。
        """
        with (
            patch.object(
                update_manager,
                "_http_get_text",
                side_effect=UpdateError("mock net down"),
            ) as http_mock,
            patch(
                "urllib.request.urlopen",
                side_effect=urllib_error.URLError("mock redirect down"),
            ) as urlopen_mock,
        ):
            with pytest.raises(UpdateError) as exc:
                check_for_updates()

        # https 重定向阶段先失败 → urlopen 被调用，而后 API 回退失败抛出 UpdateError
        assert urlopen_mock.call_count >= 1
        assert isinstance(exc.value, UpdateError)
        assert not isinstance(exc.value, urllib_error.URLError)

    def test_check_for_updates_cancellation_propagates(self, qapp: object) -> None:
        """协作取消：``UpdateCancelled`` 透传而非别吞并。"""
        with pytest.raises(UpdateCancelled):
            check_for_updates(cancel_check=lambda: True)

    def test_get_app_version_default_on_missing_file(self, tmp_path: object) -> None:
        """FAFVERSION 缺失时 ``get_app_version`` 回退默认值。"""
        missing: str = str(tmp_path / "nope" / "FAFVERSION")
        with patch.object(update_manager, "FAFVERSION_FILE", missing):
            assert get_app_version() == "未知版本"
            assert get_app_version(default="0.0.0-front") == "0.0.0-front"


# =============================================================================
# 缓存目录 / 本地版本信息
# =============================================================================
class TestCacheDirAndLocalVersion:
    """``get_cache_dir`` 与 ``load_local_version_info`` 的纯路径逻辑。"""

    def test_get_cache_dir_creates_download_subdir(self, tmp_path: object) -> None:
        """以应用数据目录为根创建 ``download`` 缓存目录。"""
        with patch.object(update_manager, "get_app_data_path", return_value=str(tmp_path)):
            cache_dir: str = get_cache_dir()
        assert cache_dir == os.path.join(str(tmp_path), update_manager.CACHE_DIR_NAME)
        assert os.path.isdir(cache_dir)

    def test_load_local_version_info_reads_tag_and_date(
        self, tmp_path: object
    ) -> None:
        """两行 FAFVERSION（版本 / ISO 日期）→ 结构化 dict。"""
        version_file: str = str(tmp_path / "FAFVERSION")
        with open(version_file, "w", encoding="utf-8") as f:
            f.write("v9.9.9\n2026-05-22\n")
        with patch.object(update_manager, "FAFVERSION_FILE", version_file):
            info: dict = load_local_version_info()
        assert info["tag_name"] == "v9.9.9"
        assert info["build_date"] == "2026-05-22"
        assert info["build_date_obj"] == date(2026, 5, 22)

    def test_load_local_version_info_missing_file_raises(self, tmp_path: object) -> None:
        """FAFVERSION 缺失 → ``UpdateError``。"""
        missing: str = str(tmp_path / "nope" / "FAFVERSION")
        with patch.object(update_manager, "FAFVERSION_FILE", missing):
            with pytest.raises(UpdateError):
                load_local_version_info()

    def test_load_local_version_info_single_line_raises(self, tmp_path: object) -> None:
        """仅一行（缺构建日期）→ ``UpdateError``。"""
        version_file: str = str(tmp_path / "FAFVERSION")
        with open(version_file, "w", encoding="utf-8") as f:
            f.write("v9.9.9\n")
        with patch.object(update_manager, "FAFVERSION_FILE", version_file):
            with pytest.raises(UpdateError):
                load_local_version_info()


# =============================================================================
# select_latest_release（旧 API 兼容层）
# =============================================================================
class TestSelectLatestRelease:
    """``select_latest_release``：筛选 draft / 无资产 / 校验失败项。"""

    def _make_release(self, tag: str, published: str) -> dict:
        """构造一个带 sha256 digest 的合法 release dict。"""
        return {
            "id": 1,
            "tag_name": tag,
            "published_at": published,
            "assets": [
                {
                    "name": _EXE_NAME.replace("9.9.9", "x"),
                    "browser_download_url": "https://example.com/setup.exe",
                    "size": 12345,
                    "digest": f"sha256:{_HASH_64}",
                }
            ],
        }

    def test_select_latest_release_returns_newest(self) -> None:
        """多版本中返回 published_date 最新的合法版本。"""
        older: dict = self._make_release("v1.0.0", "2026-01-01T00:00:00Z")
        newer: dict = self._make_release("v9.9.9", "2026-05-22T00:00:00Z")
        latest: dict = select_latest_release([older, newer])
        assert latest["tag_name"] == "v9.9.9"

    def test_select_latest_release_skips_draft_and_junk(self) -> None:
        """draft 标记、非 dict、缺字段项全部被跳过。"""
        draft: dict = self._make_release("v2.0.0", "2026-05-22T00:00:00Z")
        draft["draft"] = True
        payload: list = [draft, "junk", {}, self._make_release("v1.0.0", "2026-01-01T00:00:00Z")]
        latest: dict = select_latest_release(payload)
        assert latest["tag_name"] == "v1.0.0"

    def test_select_latest_release_no_valid_raises(self) -> None:
        """全部无效 → ``UpdateError``。"""
        with pytest.raises(UpdateError):
            select_latest_release([])
        with pytest.raises(UpdateError):
            select_latest_release([{"tag_name": "v1", "published_at": "bad"}])

    def test_select_latest_release_cancel_check_propagates(self) -> None:
        """取消回调返回 True → ``UpdateCancelled``。"""
        with pytest.raises(UpdateCancelled):
            select_latest_release([self._make_release("v1.0.0", "2026-01-01T00:00:00Z")], cancel_check=lambda: True)


# =============================================================================
# 网页源抓取 / sha256 校验（私有网络 helper 全部 mock）
# =============================================================================
class TestWebFetchHelpers:
    """``fetch_latest_release_via_web`` 与 ``fetch_installer_sha256``。"""

    def test_fetch_installer_sha256_parses_text(self) -> None:
        """checksum 文本中提取目标哈希。"""
        checksum_text: str = f"{_HASH_64}  {_EXE_NAME}"
        with patch.object(update_manager, "_http_get_text", return_value=checksum_text):
            digest: str = fetch_installer_sha256("https://example.com/checksum", _EXE_NAME)
        assert digest == _HASH_64.lower()

    def test_fetch_installer_sha256_missing_target_returns_none(self) -> None:
        """文本不含目标文件 → None。"""
        with patch.object(update_manager, "_http_get_text", return_value=f"{_HASH_64}  other.exe"):
            assert fetch_installer_sha256("https://example.com/checksum", _EXE_NAME) is None

    def test_fetch_installer_sha256_network_error_returns_none(self) -> None:
        """``_http_get_text`` 抛 ``UpdateError`` → None（吞掉网络失败）。"""
        with patch.object(update_manager, "_http_get_text", side_effect=UpdateError("net down")):
            assert fetch_installer_sha256("https://example.com/checksum", _EXE_NAME) is None

    def test_fetch_installer_sha256_cancel_propagates(self) -> None:
        """取消信号不被吞并。"""
        with patch.object(update_manager, "_http_get_text", side_effect=UpdateCancelled("cancelled")):
            with pytest.raises(UpdateCancelled):
                fetch_installer_sha256("https://example.com/checksum", _EXE_NAME)

    def test_fetch_latest_release_via_web_aggregates(self) -> None:
        """网页源成功时聚合 tag / metadata / installer 信息。"""
        with (
            patch.object(
                update_manager, "_extract_latest_tag_from_redirect", return_value="v9.9.9"
            ),
            patch.object(
                update_manager,
                "_fetch_release_metadata_from_atom",
                return_value={
                    "published_at": "2026-05-22T00:00:00Z",
                    "published_date": "2026-05-22",
                    "published_date_obj": date(2026, 5, 22),
                    "html_url": "https://github.com/rel/v9.9.9",
                    "release_body": "Changelog",
                },
            ),
            patch.object(
                update_manager,
                "_fetch_installer_info_from_expanded_assets",
                return_value={
                    "installer_name": _EXE_NAME,
                    "installer_size": 12345,
                    "installer_download_url": "https://example.com/setup.exe",
                    "installer_sha256": _HASH_64.lower(),
                    "checksum_asset_name": "setup.exe.sha256",
                    "checksum_download_url": "https://example.com/checksum",
                },
            ),
        ):
            result: dict = fetch_latest_release_via_web()
        assert result["tag_name"] == "v9.9.9"
        assert result["version_tuple"][:3] == (9, 9, 9)
        assert result["installer_name"] == _EXE_NAME
        assert result["installer_sha256"] == _HASH_64.lower()
        assert result["checksum_download_url"] == "https://example.com/checksum"
        assert result["is_prerelease"] is False

    def test_fetch_latest_release_via_web_cancel_propagates(self) -> None:
        """首步取消回调即抛出 ``UpdateCancelled``，不触网络。"""
        with patch.object(update_manager, "_extract_latest_tag_from_redirect") as extract_mock:
            with pytest.raises(UpdateCancelled):
                fetch_latest_release_via_web(cancel_check=lambda: True)
        extract_mock.assert_not_called()