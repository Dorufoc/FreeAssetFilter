"""``SettingsManagerV2``：点号路径读写、默认树回退、按改动键合并写盘。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sopeek.core.managers.settings_manager_v2 import (
    DEFAULT_SETTINGS_V2,
    SettingsManagerV2,
)


pytestmark = pytest.mark.unit


@pytest.fixture()
def manager(tmp_path: Path) -> SettingsManagerV2:
    return SettingsManagerV2(str(tmp_path / "settings_v2.json"))


def test_first_load_creates_file_with_defaults(manager: SettingsManagerV2) -> None:
    data = manager.load()
    assert data["version"] == 2
    assert Path(manager.file_path).is_file()
    on_disk = json.loads(Path(manager.file_path).read_text(encoding="utf-8"))
    assert on_disk["version"] == 2


def test_get_reads_nested_default_values(manager: SettingsManagerV2) -> None:
    assert manager.get("appearance.theme_mode") == DEFAULT_SETTINGS_V2["appearance"]["theme_mode"]
    assert manager.get("performance.profile") == DEFAULT_SETTINGS_V2["performance"]["profile"]
    assert manager.get("no.such.path", "fallback") == "fallback"


def test_set_returns_false_for_unchanged_value(manager: SettingsManagerV2) -> None:
    current = manager.get("appearance.theme_mode")
    assert manager.set("appearance.theme_mode", current) is False
    assert manager.set("appearance.theme_mode", "light") is True


def test_set_creates_intermediate_dicts(manager: SettingsManagerV2) -> None:
    assert manager.set("brand.new.key", 7) is True
    assert manager.get("brand.new.key") == 7
    assert isinstance(manager.get("brand"), dict)


def test_save_without_changes_does_not_touch_disk(manager: SettingsManagerV2) -> None:
    """无改动时不写盘——避免退出时用旧快照覆盖用户刚落盘的修改。"""
    manager.load()
    path = Path(manager.file_path)
    before = path.read_bytes()
    manager.save()
    assert path.read_bytes() == before


def test_save_merges_only_dirty_keys(manager: SettingsManagerV2) -> None:
    """另一个实例改了别的键，本实例只回写自己改过的键。"""
    manager.load()
    manager.set("appearance.accent_color", "#123456")
    manager.save()

    other = SettingsManagerV2(manager.file_path)
    other.load()
    other.set("performance.profile", "powersave")
    other.save()

    reloaded = SettingsManagerV2(manager.file_path)
    assert reloaded.get("appearance.accent_color") == "#123456"
    assert reloaded.get("performance.profile") == "powersave"


def test_corrupt_file_falls_back_to_defaults(manager: SettingsManagerV2) -> None:
    Path(manager.file_path).write_text("{ not json", encoding="utf-8")
    data = manager.load()
    assert data["version"] == 2
    # 损坏文件被默认树重写
    assert json.loads(Path(manager.file_path).read_text(encoding="utf-8"))["version"] == 2


def test_non_dict_root_is_rejected(manager: SettingsManagerV2) -> None:
    Path(manager.file_path).write_text("[1, 2, 3]", encoding="utf-8")
    assert manager.load()["version"] == 2


def test_oversized_file_is_rejected(manager: SettingsManagerV2, monkeypatch) -> None:
    manager.load()
    monkeypatch.setattr(SettingsManagerV2, "MAX_SETTINGS_FILE_BYTES", 4)
    reloaded = SettingsManagerV2(manager.file_path)
    assert reloaded.load()["version"] == 2


def test_reset_to_defaults_persists(manager: SettingsManagerV2) -> None:
    manager.load()
    manager.set("appearance.theme_mode", "light")
    manager.save()
    manager.reset_to_defaults()
    assert manager.get("appearance.theme_mode") == DEFAULT_SETTINGS_V2["appearance"]["theme_mode"]
    assert SettingsManagerV2(manager.file_path).get("appearance.theme_mode") == (
        DEFAULT_SETTINGS_V2["appearance"]["theme_mode"]
    )


def test_get_all_returns_a_copy(manager: SettingsManagerV2) -> None:
    snapshot = manager.get_all()
    snapshot["version"] = 999
    assert manager.get("version") == 2


def test_update_source_defaults_to_github(manager: SettingsManagerV2) -> None:
    """更新源默认 github；旧文件缺键时由默认树补齐。"""
    assert manager.get("update.source") == "github"
    assert DEFAULT_SETTINGS_V2["update"]["source"] == "github"


def test_general_hidden_system_flags_round_trip(manager: SettingsManagerV2) -> None:
    """隐藏/系统文件两个布尔键可持久化，且非布尔值加载时回退 False。"""
    manager.load()
    assert manager.set("general.show_hidden_files", True) is True
    assert manager.set("general.show_system_files", True) is True
    manager.save()

    reloaded = SettingsManagerV2(manager.file_path)
    assert reloaded.get("general.show_hidden_files") is True
    assert reloaded.get("general.show_system_files") is True

    data = json.loads(Path(manager.file_path).read_text(encoding="utf-8"))
    data["general"]["show_hidden_files"] = "true"
    data["general"]["show_system_files"] = 1
    Path(manager.file_path).write_text(json.dumps(data), encoding="utf-8")
    invalid = SettingsManagerV2(manager.file_path)
    assert invalid.get("general.show_hidden_files") is False
    assert invalid.get("general.show_system_files") is False


def test_general_close_action_default_and_whitelist(manager: SettingsManagerV2) -> None:
    """general.close_action 默认 "ask"；非法值回退，合法 tray/quit 被保留。"""
    assert DEFAULT_SETTINGS_V2["general"]["close_action"] == "ask"
    assert manager.get("general.close_action") == "ask"

    manager.load()
    manager.set("general.close_action", "tray")
    manager.save()
    assert SettingsManagerV2(manager.file_path).get("general.close_action") == "tray"

    path = Path(manager.file_path)
    for invalid in ("minimize", 123, None):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["general"]["close_action"] = invalid
        path.write_text(json.dumps(data), encoding="utf-8")
        assert (
            SettingsManagerV2(manager.file_path).get("general.close_action")
            == "ask"
        )

    data = json.loads(path.read_text(encoding="utf-8"))
    data["general"]["close_action"] = "quit"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert SettingsManagerV2(manager.file_path).get("general.close_action") == "quit"


def test_update_source_whitelist_round_trip(manager: SettingsManagerV2) -> None:
    """gitcode 可持久化；非法值在加载合并时回退默认 github。"""
    manager.load()
    manager.set("update.source", "gitcode")
    manager.save()
    assert SettingsManagerV2(manager.file_path).get("update.source") == "gitcode"

    path = Path(manager.file_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["update"]["source"] = "not-a-source"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert SettingsManagerV2(manager.file_path).get("update.source") == "github"


def test_write_is_atomic_via_temp_replace(manager: SettingsManagerV2) -> None:
    """写盘经 ``<file>.tmp`` + ``os.replace``：结束后不应残留临时文件。"""
    manager.load()
    manager.set("appearance.theme_mode", "light")
    manager.save()
    leftovers = list(Path(manager.file_path).parent.glob("*.tmp"))
    assert leftovers == []
