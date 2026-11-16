"""收藏夹服务：默认路径必须落在用户数据目录，不写安装目录。

历史缺陷：默认路径按 ``__file__`` 上溯到 ``sopeek/data/favorites.json``，
冻结后位于 ``_internal`` 下，普通用户不可写且卸载器不会清理。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sopeek import storage_layout
from sopeek.services.favorites_service import FavoritesService


pytestmark = pytest.mark.unit


@pytest.fixture()
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("SPK_DATA_DIR", str(data_dir))
    storage_layout.reset_layout_state()
    yield data_dir
    storage_layout.reset_layout_state()


def test_default_path_is_under_user_data(isolated: Path) -> None:
    """默认收藏夹位于 ``<data>/config/favorites.json``。"""
    service = FavoritesService()
    assert Path(service.favorites_file) == isolated / "config" / "favorites.json"


def test_save_and_load_roundtrip(isolated: Path) -> None:
    service = FavoritesService()
    assert service.save([{"name": "a", "path": "D:/a"}]) is True

    reloaded = FavoritesService()
    assert reloaded.load() == [{"name": "a", "path": "D:/a"}]


def test_save_is_atomic_and_keeps_backup(isolated: Path) -> None:
    service = FavoritesService()
    service.save([{"name": "first", "path": "D:/first"}])
    service.save([{"name": "second", "path": "D:/second"}])

    target = isolated / "config" / "favorites.json"
    backup = Path(str(target) + ".bak")
    assert backup.is_file()
    assert "first" in backup.read_text(encoding="utf-8")
    assert "second" in target.read_text(encoding="utf-8")


def test_corrupt_file_falls_back_to_empty(isolated: Path) -> None:
    target = isolated / "config" / "favorites.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{broken", encoding="utf-8")

    assert FavoritesService().load() == []


def test_explicit_path_is_honoured(tmp_path: Path) -> None:
    custom = tmp_path / "custom.json"
    service = FavoritesService(str(custom))
    assert service.favorites_file == str(custom)
    assert service.save(["D:/x"]) is True
    assert custom.is_file()
