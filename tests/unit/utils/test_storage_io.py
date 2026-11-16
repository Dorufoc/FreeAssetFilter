"""原子 JSON 读写与日志保留策略。

覆盖：原子写、备份回退、损坏隔离；日志 7 天压缩 / 20 天删除 / 200MB 淘汰
以及活动日志保护。
"""

from __future__ import annotations

import gzip
import json
import os
import time
from pathlib import Path

import pytest

from sopeek.utils import atomic_json, log_retention


pytestmark = pytest.mark.unit


# ── atomic_json ──────────────────────────────────────────────────────


def test_write_json_atomic_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "settings.json"
    atomic_json.write_json_atomic(target, {"a": 1})

    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    assert not list(target.parent.glob("*.tmp"))


def test_write_json_atomic_backup_keeps_previous(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    atomic_json.write_json_atomic(target, {"v": 1})
    atomic_json.write_json_atomic(target, {"v": 2}, backup=True)

    assert json.loads(target.read_text(encoding="utf-8")) == {"v": 2}
    backup = Path(str(target) + ".bak")
    assert json.loads(backup.read_text(encoding="utf-8")) == {"v": 1}


def test_read_json_falls_back_to_backup(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    Path(str(target) + ".bak").write_text('{"ok": true}', encoding="utf-8")
    target.write_text("{broken", encoding="utf-8")

    assert atomic_json.read_json(target) == {"ok": True}


def test_read_json_quarantines_unrecoverable_file(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    target.write_text("{broken", encoding="utf-8")

    assert atomic_json.read_json(target, default={"fallback": True}) == {
        "fallback": True
    }
    assert not target.exists()
    assert list(tmp_path.glob("settings.json.corrupt-*"))


def test_read_json_missing_returns_default(tmp_path: Path) -> None:
    assert atomic_json.read_json(tmp_path / "nope.json", default=[]) == []


# ── log_retention ────────────────────────────────────────────────────


def _make_log(directory: Path, name: str, age_days: float, payload: bytes = b"x") -> Path:
    path = directory / name
    path.write_bytes(payload)
    stamp = time.time() - age_days * 86400
    os.utime(path, (stamp, stamp))
    return path


def test_compresses_logs_older_than_seven_days(tmp_path: Path) -> None:
    old = _make_log(tmp_path, "app_20260101_000000.log", 10)
    new = _make_log(tmp_path, "app_20261116_000000.log", 1)

    report = log_retention.maintain_logs(tmp_path)

    assert report["compressed"] == 1
    assert not old.exists()
    archive = tmp_path / "app_20260101_000000.log.gz"
    assert archive.exists()
    with gzip.open(archive, "rb") as handle:
        assert handle.read() == b"x"
    assert new.exists()


def test_never_touches_active_log(tmp_path: Path) -> None:
    active = _make_log(tmp_path, "app_20260101_000000.log", 30)

    report = log_retention.maintain_logs(tmp_path, active_log_path=active)

    assert report["compressed"] == 0
    assert active.exists()
    assert not (tmp_path / "app_20260101_000000.log.gz").exists()


def test_deletes_archives_older_than_twenty_days(tmp_path: Path) -> None:
    old_archive = _make_log(tmp_path, "app_20250101_000000.log.gz", 25)
    fresh_archive = _make_log(tmp_path, "app_20261101_000000.log.gz", 5)

    report = log_retention.maintain_logs(tmp_path)

    assert report["deleted"] == 1
    assert not old_archive.exists()
    assert fresh_archive.exists()


def test_enforces_total_size_limit_oldest_first(tmp_path: Path) -> None:
    oldest = _make_log(tmp_path, "app_20260101_000000.log", 3, b"a" * 1024)
    newer = _make_log(tmp_path, "app_20260102_000000.log", 2, b"b" * 1024)

    report = log_retention.maintain_logs(tmp_path, max_total_bytes=1500)

    assert report["deleted"] == 1
    assert not oldest.exists()
    assert newer.exists()


def test_active_log_survives_size_limit(tmp_path: Path) -> None:
    active = _make_log(tmp_path, "app_20260103_000000.log", 0, b"a" * 2048)
    other = _make_log(tmp_path, "app_20260101_000000.log", 2, b"b" * 1024)

    log_retention.maintain_logs(
        tmp_path, active_log_path=active, max_total_bytes=1500
    )

    assert active.exists()
    assert not other.exists()


def test_keeps_recent_logs_untouched(tmp_path: Path) -> None:
    recent = _make_log(tmp_path, "app_20261115_000000.log", 1)

    report = log_retention.maintain_logs(tmp_path)

    assert report["compressed"] == 0
    assert report["deleted"] == 0
    assert recent.exists()


def test_no_file_count_limit_by_default(tmp_path: Path) -> None:
    """默认不限制文件数量：20 个新日志全部保留。"""
    for index in range(20):
        _make_log(
            tmp_path,
            f"app_202611{index + 1:02d}_1200{index:02d}.log",
            0.5,
        )

    log_retention.maintain_logs(tmp_path)

    assert len(list(tmp_path.glob("app_*.log"))) == 20
