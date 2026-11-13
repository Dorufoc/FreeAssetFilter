# -*- coding: utf-8 -*-
"""待安装更新标记与启动安装结果测试。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sopeek.services import update_pending

pytestmark = pytest.mark.unit


@pytest.fixture
def appdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把应用数据目录与本地版本隔离到临时目录。"""
    monkeypatch.setattr(update_pending, "get_app_data_path", lambda: tmp_path)
    monkeypatch.setattr(
        update_pending, "get_local_version", lambda: "1.0.0-alpha.5"
    )
    return tmp_path


def _installer(appdata: Path, name: str = "Setup.exe") -> tuple[Path, bytes]:
    """创建下载目录下的安装包并返回路径与内容。"""
    path = appdata / "download" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"Sopeek installer payload"
    path.write_bytes(payload)
    return path, payload


def _info(
    payload: bytes,
    *,
    version: str = "v1.0.0-alpha.6",
    sha256: str | None = None,
    size: int | None = None,
    asset: Any = ...,
) -> SimpleNamespace:
    """构造用于登记的最小 UpdateInfo 替身。"""
    digest = sha256 if sha256 is not None else hashlib.sha256(payload).hexdigest()
    asset_value = (
        {
            "name": "Setup.exe",
            "sha256": digest,
            "size": size if size is not None else len(payload),
        }
        if asset is ...
        else asset
    )
    return SimpleNamespace(
        local_version="1.0.0-alpha.5",
        remote={"version": version, "tag": version},
        asset=asset_value,
    )


class TestPendingUpdateFile:
    """原子读写、静态校验与清理。"""

    def test_roundtrip_and_clear(self, appdata: Path) -> None:
        path, payload = _installer(appdata)
        info = _info(payload)

        assert update_pending.write_pending_update(info, str(path)) is True
        marker = update_pending.pending_update_path()
        assert marker.is_file()
        assert not list(marker.parent.glob(f".{marker.name}.*.tmp"))

        pending = update_pending.read_pending_update()
        assert pending is not None
        assert pending.installer_path == str(path.resolve())
        assert pending.sha256 == hashlib.sha256(payload).hexdigest()
        assert pending.size == len(payload)
        assert pending.version == "1.0.0-alpha.6"
        assert pending.from_version == "1.0.0-alpha.5"

        assert update_pending.clear_pending_update() is True
        assert not marker.exists()
        assert update_pending.clear_pending_update() is True
        assert update_pending.read_pending_update() is None

    def test_invalid_json_is_cleared(self, appdata: Path) -> None:
        marker = update_pending.pending_update_path()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("{not json", encoding="utf-8")

        assert update_pending.read_pending_update() is None
        assert not marker.exists()

    def test_version_mismatch_is_cleared(
        self, appdata: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path, payload = _installer(appdata)
        assert update_pending.write_pending_update(
            _info(payload), str(path)
        )
        monkeypatch.setattr(
            update_pending, "get_local_version", lambda: "1.0.0-alpha.7"
        )

        assert update_pending.read_pending_update() is None
        assert not update_pending.pending_update_path().exists()

    def test_path_outside_download_rejected(self, appdata: Path) -> None:
        outside = appdata / "outside.exe"
        outside.write_bytes(b"outside")
        info = _info(b"outside")

        assert update_pending.write_pending_update(info, str(outside)) is False
        assert not update_pending.pending_update_path().exists()

    def test_size_mismatch_is_cleared(self, appdata: Path) -> None:
        path, payload = _installer(appdata)
        assert update_pending.write_pending_update(
            _info(payload), str(path)
        )
        path.write_bytes(b"changed size")

        assert update_pending.read_pending_update() is None
        assert not update_pending.pending_update_path().exists()

    def test_invalid_sha_rejected(self, appdata: Path) -> None:
        path, payload = _installer(appdata)
        info = _info(payload, sha256="not-a-sha")

        assert update_pending.write_pending_update(info, str(path)) is False

    def test_same_target_version_rejected(self, appdata: Path) -> None:
        path, payload = _installer(appdata)
        info = _info(payload, version="v1.0.0-alpha.5")

        assert update_pending.write_pending_update(info, str(path)) is False

    def test_missing_asset_rejected(self, appdata: Path) -> None:
        path, payload = _installer(appdata)
        info = _info(payload, asset=None)

        assert update_pending.write_pending_update(info, str(path)) is False


class TestApplyPendingUpdate:
    """启动时读取标记并调用同步安装器启动函数。"""

    def test_no_marker_does_not_create_service(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created: list[bool] = []
        monkeypatch.setattr(update_pending, "read_pending_update", lambda: None)

        result = update_pending.apply_pending_update(
            service_factory=lambda: created.append(True)
        )

        assert result.launched is False
        assert result.detail == ""
        assert created == []

    def test_success_clears_marker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pending = SimpleNamespace(
            installer_path="C:/download/Setup.exe", sha256="a" * 64
        )
        cleared: list[bool] = []
        monkeypatch.setattr(
            update_pending, "read_pending_update", lambda: pending
        )
        monkeypatch.setattr(
            update_pending,
            "clear_pending_update",
            lambda: cleared.append(True) or True,
        )
        calls: list[tuple[Any, str, str]] = []

        def launcher(service: Any, path: str, sha: str) -> Any:
            calls.append((service, path, sha))
            return SimpleNamespace(launched=True, detail="")

        result = update_pending.apply_pending_update(
            service_factory=lambda: "service", launcher=launcher
        )

        assert result.launched is True
        assert calls == [("service", pending.installer_path, pending.sha256)]
        assert cleared == [True]

    def test_failure_reports_detail_and_clears_marker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pending = SimpleNamespace(
            installer_path="C:/download/Setup.exe", sha256="a" * 64
        )
        monkeypatch.setattr(
            update_pending, "read_pending_update", lambda: pending
        )
        monkeypatch.setattr(
            update_pending, "clear_pending_update", lambda: True
        )

        result = update_pending.apply_pending_update(
            service_factory=lambda: "service",
            launcher=lambda *a: SimpleNamespace(
                launched=False, detail="UAC 已取消"
            ),
        )

        assert result.launched is False
        assert result.detail == "UAC 已取消"

    def test_launcher_exception_is_readable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pending = SimpleNamespace(
            installer_path="C:/download/Setup.exe", sha256="a" * 64
        )
        cleared: list[bool] = []
        monkeypatch.setattr(
            update_pending, "read_pending_update", lambda: pending
        )
        monkeypatch.setattr(
            update_pending,
            "clear_pending_update",
            lambda: cleared.append(True) or True,
        )

        def boom(*_args: Any) -> Any:
            raise RuntimeError("boom")

        result = update_pending.apply_pending_update(
            service_factory=lambda: "service", launcher=boom
        )

        assert result.launched is False
        assert "boom" in result.detail
        assert cleared == [True]
