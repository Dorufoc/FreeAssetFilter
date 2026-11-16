"""存储布局：目录结构、迁移、路径重写与清理策略。

这些测试是“数据不丢”的防回退锁：迁移必须把旧平铺布局搬到分类布局，
并保留内容、修正设置里的绝对路径；任何失败项都不能删除唯一副本。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from sopeek import _paths
from sopeek import storage_layout


pytestmark = pytest.mark.unit


@pytest.fixture()
def fresh_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把数据根指向全新目录，并重置进程内布局缓存。"""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("SPK_DATA_DIR", str(data_dir))
    storage_layout.reset_layout_state()
    yield data_dir
    storage_layout.reset_layout_state()


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_ensure_layout_creates_v2_directories(fresh_data_dir: Path) -> None:
    """首次启动创建完整分类布局，并写入版本标记。"""
    report = storage_layout.ensure_layout()
    assert report["version"] == storage_layout.LAYOUT_VERSION

    for relative in (
        "config",
        "state",
        "assets/backgrounds",
        "assets/luts",
        "cache/icons",
        "cache/thumbnails",
        "cache/office",
        "cache/lut_previews",
        "logs",
        "updates/download",
        "diagnostics/performance",
        "diagnostics/probes",
        "temp/office",
    ):
        assert (fresh_data_dir / relative).is_dir(), relative

    marker = _read(fresh_data_dir / ".layout_version.json")
    assert marker["version"] == storage_layout.LAYOUT_VERSION
    assert marker["complete"] is True


def test_ensure_layout_is_idempotent(fresh_data_dir: Path) -> None:
    """第二次调用不重复迁移（标记已 complete）。"""
    storage_layout.ensure_layout()
    marker_before = _read(fresh_data_dir / ".layout_version.json")

    report = storage_layout.ensure_layout(force=True)
    assert report.get("migrated") is False
    marker_after = _read(fresh_data_dir / ".layout_version.json")
    assert marker_after["migrated_at"] == marker_before["migrated_at"]


def test_migrates_flat_layout_files(fresh_data_dir: Path) -> None:
    """旧平铺文件迁移到对应分类目录，内容保持一致。"""
    fresh_data_dir.mkdir(parents=True, exist_ok=True)
    _write(fresh_data_dir / "settings_v2.json", {"appearance": {"theme": "dark"}})
    _write(fresh_data_dir / "ai_accounts.json", {"version": 1, "accounts": []})
    _write(fresh_data_dir / "last_path.json", {"last_path": "D:/assets"})
    _write(fresh_data_dir / "staging_pool_backup.json", {"items": [1]})
    _write(fresh_data_dir / "check_state.json", {"last_check": 123})
    _write(fresh_data_dir / "file_info_cache.json", {"version": 2, "files": {}})

    storage_layout.ensure_layout()

    assert _read(fresh_data_dir / "config" / "settings.json") == {
        "appearance": {"theme": "dark"}
    }
    assert _read(fresh_data_dir / "config" / "ai_accounts.json")["version"] == 1
    assert _read(fresh_data_dir / "state" / "last_path.json")["last_path"] == "D:/assets"
    assert _read(fresh_data_dir / "state" / "staging_pool.json") == {"items": [1]}
    assert _read(fresh_data_dir / "state" / "update_check.json")["last_check"] == 123
    assert _read(fresh_data_dir / "cache" / "file_info.json")["version"] == 2

    # 旧平铺文件被清理（数据根内的源文件）。
    assert not (fresh_data_dir / "settings_v2.json").exists()
    assert not (fresh_data_dir / "last_path.json").exists()


def test_migrates_user_assets_and_rewrites_settings_paths(
    fresh_data_dir: Path,
) -> None:
    """LUT 目录迁移后，设置里的绝对路径同步改写到新位置。"""
    old_lut_dir = fresh_data_dir / "luts"
    old_lut_dir.mkdir(parents=True)
    old_lut = old_lut_dir / "abc_profile.cube"
    old_lut.write_text("LUT_3D_SIZE 2\n", encoding="utf-8")

    old_preview_dir = fresh_data_dir / "lut_previews"
    old_preview_dir.mkdir(parents=True)
    old_preview = old_preview_dir / "abc_preview.png"
    old_preview.write_bytes(b"png")

    _write(
        fresh_data_dir / "settings_v2.json",
        {
            "video": {
                "lut_files": [
                    {
                        "id": "abc",
                        "path": str(old_lut),
                        "preview_path": str(old_preview),
                    }
                ]
            }
        },
    )

    storage_layout.ensure_layout()

    assert (fresh_data_dir / "assets" / "luts" / "abc_profile.cube").is_file()
    assert (
        fresh_data_dir / "cache" / "lut_previews" / "abc_preview.png"
    ).is_file()

    settings = _read(fresh_data_dir / "config" / "settings.json")
    entry = settings["video"]["lut_files"][0]
    assert entry["path"] == str(
        fresh_data_dir / "assets" / "luts" / "abc_profile.cube"
    )
    assert entry["preview_path"] == str(
        fresh_data_dir / "cache" / "lut_previews" / "abc_preview.png"
    )


def test_rewrites_pending_update_installer_path(fresh_data_dir: Path) -> None:
    """下载目录迁移后，待安装标记指向新路径。"""
    old_download = fresh_data_dir / "download"
    old_download.mkdir(parents=True)
    installer = old_download / "Sopeek-2.0.0-windows-x64.exe"
    installer.write_bytes(b"MZ")
    _write(
        fresh_data_dir / "pending_update.json",
        {
            "schema_version": 1,
            "installer_path": str(installer),
            "sha256": "a" * 64,
            "size": 2,
            "version": "2.0.0",
            "from_version": "1.0.0",
            "created_at": time.time(),
        },
    )

    storage_layout.ensure_layout()

    new_installer = fresh_data_dir / "updates" / "download" / installer.name
    assert new_installer.is_file()
    state = _read(fresh_data_dir / "state" / "pending_update.json")
    assert state["installer_path"] == str(new_installer)


def test_pending_update_cleared_when_installer_missing(
    fresh_data_dir: Path,
) -> None:
    """安装包已不存在时，迁移清理标记而不是留下悬空引用。"""
    _write(
        fresh_data_dir / "pending_update.json",
        {
            "schema_version": 1,
            "installer_path": str(fresh_data_dir / "download" / "gone.exe"),
            "sha256": "a" * 64,
            "size": 2,
            "version": "2.0.0",
            "from_version": "1.0.0",
            "created_at": time.time(),
        },
    )

    storage_layout.ensure_layout()

    assert not (fresh_data_dir / "state" / "pending_update.json").exists()


def test_prefers_newer_settings_when_target_exists(fresh_data_dir: Path) -> None:
    """新旧设置同时存在时保留较新的那份，并把旧份留作 .bak。"""
    target = fresh_data_dir / "config" / "settings.json"
    _write(target, {"marker": "target-old"})
    os.utime(target, (time.time() - 3600, time.time() - 3600))

    source = fresh_data_dir / "settings_v2.json"
    _write(source, {"marker": "source-new"})

    storage_layout.ensure_layout()

    assert _read(target)["marker"] == "source-new"
    assert _read(Path(str(target) + ".bak"))["marker"] == "target-old"


def test_cleanup_office_temp_removes_only_stale_entries(
    fresh_data_dir: Path,
) -> None:
    """只删除 24 小时前的临时转换目录。"""
    storage_layout.ensure_layout()
    root = fresh_data_dir / "temp" / "office"
    stale = root / "stale-task"
    fresh = root / "fresh-task"
    for item in (stale, fresh):
        item.mkdir(parents=True)
        (item / "out.pdf").write_bytes(b"pdf")

    old = time.time() - 48 * 3600
    os.utime(stale, (old, old))
    os.utime(stale / "out.pdf", (old, old))

    removed = storage_layout.cleanup_storage(categories=["temp_office"])

    assert removed["temp_office"] == 1
    assert not stale.exists()
    assert fresh.exists()


def test_cleanup_updates_keeps_pending_installer(fresh_data_dir: Path) -> None:
    """过期下载被删除，但 pending_update 引用的安装包保留。"""
    storage_layout.ensure_layout()
    download = fresh_data_dir / "updates" / "download"
    kept = download / "pending.exe"
    stale = download / "old.exe"
    for item in (kept, stale):
        item.write_bytes(b"MZ")
    old = time.time() - 30 * 86400
    os.utime(kept, (old, old))
    os.utime(stale, (old, old))

    _write(
        fresh_data_dir / "state" / "pending_update.json",
        {"schema_version": 1, "installer_path": str(kept)},
    )

    removed = storage_layout.cleanup_storage(categories=["updates"])

    assert removed["updates"] == 1
    assert kept.exists()
    assert not stale.exists()


def test_cleanup_lut_previews_removes_orphans(fresh_data_dir: Path) -> None:
    """对应 LUT 已删除的预览图被清理。"""
    storage_layout.ensure_layout()
    previews = fresh_data_dir / "cache" / "lut_previews"
    (previews / "alive_preview.png").write_bytes(b"png")
    (previews / "orphan_preview.png").write_bytes(b"png")
    (fresh_data_dir / "assets" / "luts" / "alive_profile.cube").write_text(
        "LUT_3D_SIZE 2\n", encoding="utf-8"
    )

    removed = storage_layout.cleanup_storage(categories=["lut_previews"])

    assert removed["lut_previews"] == 1
    assert (previews / "alive_preview.png").exists()
    assert not (previews / "orphan_preview.png").exists()


def test_layout_paths_are_under_data_root(fresh_data_dir: Path) -> None:
    """所有具名 getter 都必须落在数据根内。"""
    storage_layout.ensure_layout()
    getters = (
        _paths.settings_file,
        _paths.ai_accounts_file,
        _paths.favorites_file,
        _paths.last_path_file,
        _paths.staging_pool_file,
        _paths.update_check_file,
        _paths.pending_update_file,
        _paths.runtime_instance_file,
        _paths.file_info_cache_file,
        _paths.backgrounds_dir,
        _paths.luts_dir,
        _paths.icon_cache_dir,
        _paths.thumbnails_dir,
        _paths.office_cache_dir,
        _paths.lut_previews_dir,
        _paths.logs_dir,
        _paths.updates_download_dir,
        _paths.performance_dir,
        _paths.probes_dir,
        _paths.office_temp_dir,
    )
    root = os.path.normcase(os.path.abspath(str(fresh_data_dir)))
    for getter in getters:
        value = os.path.normcase(os.path.abspath(str(getter())))
        assert value.startswith(root + os.sep), getter.__name__
