# -*- coding: utf-8 -*-
# targets: services.settings_repository, services.favorites_repository, services.office_cache
"""``settings_repository`` / ``favorites_repository`` / ``office_cache`` 单元测试。

三个纯数据层模块（freeassetfilter/services/ 下）均只做文件 I/O，返回类型安全
的静默降级。覆盖（每个模块 happy + boundary/error 各至少一条）：

* ``SettingsRepository`` —— load/save/atomic_save 往返、缺失/损坏/超大/非法
  UTF-8 文件回退空字典、父目录自动创建、权限异常吞掉、临时文件清理。
* ``FavoritesRepository`` —— 列表往返、缺失/损坏/根类型错误回退空列表、
  中文原始落盘。
* ``office_cache`` —— 缓存目录调用期解析、稳定缓存键、put/get 往返、空文件
  视为未命中、不可写降级、LRU touch、过期与大小驱逐、周期清理线程幂等启停。

所有测试仅使用 ``tmp_path``：缓存目录通过 monkeypatch
``path_utils.get_app_data_path`` 重定向，绝不触碰真实 ``data/``。
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Dict, List

import pytest

from freeassetfilter.services import office_cache as office_cache_module
from freeassetfilter.services.favorites_repository import FavoritesRepository
from freeassetfilter.services.office_cache import (
    MAX_OFFICE_CACHE_AGE_DAYS,
    OFFICE_CACHE_DIR_NAME,
)
from freeassetfilter.services.settings_repository import SettingsRepository

pytestmark = pytest.mark.unit


# =============================================================================
# 共享 fixture
# =============================================================================
@pytest.fixture
def office_cache_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """把 office_cache 的缓存目录重定向到 tmp_path，测试结束自动还原。

    Args:
        monkeypatch: pytest monkeypatch fixture。
        tmp_path: pytest 内置的每测试临时目录。

    Returns:
        Path: 充当 ``get_app_data_path()`` 的临时目录。
    """
    import freeassetfilter.utils.path_utils as path_utils_module

    monkeypatch.setattr(
        path_utils_module,
        "get_app_data_path",
        lambda: str(tmp_path),
    )
    return tmp_path


# =============================================================================
# SettingsRepository
# =============================================================================
class TestSettingsRepository:
    """JSON 设置数据访问层"""

    def test_load_missing_file_returns_empty_dict(self, tmp_path: Path) -> None:
        """文件不存在返回空字典。"""
        repo: SettingsRepository = SettingsRepository(str(tmp_path / "missing.json"))
        assert repo.load() == {}

    def test_save_then_load_roundtrip(self, tmp_path: Path) -> None:
        """保存后读取往返一致（含嵌套结构）。"""
        repo: SettingsRepository = SettingsRepository(str(tmp_path / "cfg.json"))
        data: Dict[str, object] = {
            "appearance": {"theme": "dark"},
            "custom": {"nested": {"a": 1}},
        }
        repo.save(data)
        assert repo.load() == data

    def test_save_preserves_unicode_literal(self, tmp_path: Path) -> None:
        """ensure_ascii=False：中文以原文写入磁盘。"""
        repo: SettingsRepository = SettingsRepository(str(tmp_path / "cfg.json"))
        repo.save({"note": "你好，世界"})
        raw: str = Path(repo.file_path).read_text(encoding="utf-8")
        assert "你好，世界" in raw

    def test_save_creates_parent_directories(self, tmp_path: Path) -> None:
        """父目录不存在时自动创建。"""
        target: Path = tmp_path / "nested" / "deep" / "cfg.json"
        repo: SettingsRepository = SettingsRepository(str(target))
        repo.save({"x": 1})
        assert target.exists()

    def test_load_corrupted_json_returns_empty(self, tmp_path: Path) -> None:
        """损坏 JSON 静默回退空字典。"""
        bad: Path = tmp_path / "bad.json"
        bad.write_text("{not valid json!!", encoding="utf-8")
        assert SettingsRepository(str(bad)).load() == {}

    def test_load_invalid_utf8_returns_empty(self, tmp_path: Path) -> None:
        """非法 UTF-8 字节静默回退空字典。"""
        bad: Path = tmp_path / "bad_utf8.json"
        bad.write_bytes(b"\xff\xfe\x00{broken}")
        assert SettingsRepository(str(bad)).load() == {}

    def test_load_oversized_file_returns_empty(self, tmp_path: Path) -> None:
        """超过 MAX_JSON_SIZE 的文件回退空字典（缩小阈值实测）。"""
        big: Path = tmp_path / "big.json"
        big.write_text('{"padding": "' + "x" * 200 + '"}', encoding="utf-8")
        repo: SettingsRepository = SettingsRepository(str(big))
        repo.MAX_JSON_SIZE = 100
        assert repo.load() == {}

    def test_load_root_not_dict_passthrough(self, tmp_path: Path) -> None:
        """记录现状：仓库层不校验根类型，合法 JSON list 原样返回。

        根类型逃逸导致的 AttributeError 是 SettingsManager 层的既有缺陷
        （见 learnings todo-7）；数据访问层本身忠实返回解析结果。
        """
        f: Path = tmp_path / "list.json"
        f.write_text("[1, 2, 3]", encoding="utf-8")
        assert SettingsRepository(str(f)).load() == [1, 2, 3]

    def test_load_permission_error_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """读取权限不足时静默回退空字典。"""
        f: Path = tmp_path / "cfg.json"
        f.write_text("{}", encoding="utf-8")
        repo: SettingsRepository = SettingsRepository(str(f))

        def _raise_open(*args: object, **kwargs: object) -> object:
            raise PermissionError("denied")

        monkeypatch.setattr("builtins.open", _raise_open)
        assert repo.load() == {}

    def test_atomic_save_roundtrip_and_no_tmp_left(self, tmp_path: Path) -> None:
        """atomic_save 往返一致且不留 .tmp 残留。"""
        target: Path = tmp_path / "cfg.json"
        repo: SettingsRepository = SettingsRepository(str(target))
        repo.atomic_save({"a": 1, "nested": {"b": "好"}})
        assert repo.load() == {"a": 1, "nested": {"b": "好"}}
        assert list(tmp_path.glob("*.tmp")) == []

    def test_atomic_save_creates_parent_dir(self, tmp_path: Path) -> None:
        """atomic_save 同样确保父目录存在。"""
        target: Path = tmp_path / "x" / "y" / "cfg.json"
        repo: SettingsRepository = SettingsRepository(str(target))
        repo.atomic_save({"k": "v"})
        assert target.exists()

    def test_file_path_property(self, tmp_path: Path) -> None:
        """file_path 属性返回构造时传入的路径。"""
        p: str = str(tmp_path / "cfg.json")
        assert SettingsRepository(p).file_path == p

    def test_default_path_points_to_data_settings(self) -> None:
        """默认路径指向项目 data/settings.json（绝对路径）。"""
        repo: SettingsRepository = SettingsRepository()
        assert repo.file_path.endswith(os.path.join("data", "settings.json"))


# =============================================================================
# FavoritesRepository
# =============================================================================
class TestFavoritesRepository:
    """收藏夹 JSON 数据访问层"""

    def test_load_missing_file_returns_empty_list(self, tmp_path: Path) -> None:
        """文件不存在返回空列表。"""
        repo: FavoritesRepository = FavoritesRepository(str(tmp_path / "favs.json"))
        assert repo.load() == []

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        """路径列表往返一致。"""
        fav_file: Path = tmp_path / "favs.json"
        repo: FavoritesRepository = FavoritesRepository(str(fav_file))
        paths: List[str] = [
            r"C:\assets\a.png",
            r"C:\assets\b.jpg",
            "相对路径/文件.txt",
        ]
        repo.save(paths)
        assert repo.load() == paths

    def test_save_creates_parent_dir(self, tmp_path: Path) -> None:
        """父目录不存在时自动创建。"""
        fav_file: Path = tmp_path / "deep" / "favs.json"
        repo: FavoritesRepository = FavoritesRepository(str(fav_file))
        repo.save(["x"])
        assert fav_file.exists()

    def test_load_corrupted_json_returns_empty(self, tmp_path: Path) -> None:
        """损坏 JSON 静默回退空列表。"""
        fav_file: Path = tmp_path / "favs.json"
        fav_file.write_text("{oops", encoding="utf-8")
        assert FavoritesRepository(str(fav_file)).load() == []

    def test_load_wrong_root_type_returns_empty(self, tmp_path: Path) -> None:
        """根节点非 list 时静默回退空列表。"""
        fav_file: Path = tmp_path / "favs.json"
        fav_file.write_text('{"paths": ["x"]}', encoding="utf-8")
        assert FavoritesRepository(str(fav_file)).load() == []

    def test_load_empty_list(self, tmp_path: Path) -> None:
        """合法的空数组正常返回 []。"""
        fav_file: Path = tmp_path / "favs.json"
        fav_file.write_text("[]", encoding="utf-8")
        assert FavoritesRepository(str(fav_file)).load() == []

    def test_save_unicode_preserved(self, tmp_path: Path) -> None:
        """中文路径以原文落盘（ensure_ascii=False）。"""
        fav_file: Path = tmp_path / "favs.json"
        FavoritesRepository(str(fav_file)).save(["D:\\素材\\图片.png"])
        text: str = fav_file.read_text(encoding="utf-8")
        assert "素材" in text

    def test_new_repository_instance_roundtrip(self, tmp_path: Path) -> None:
        """新实例从磁盘重新加载已保存内容。"""
        fav_file: Path = tmp_path / "favs.json"
        FavoritesRepository(str(fav_file)).save(["a", "b"])
        assert FavoritesRepository(str(fav_file)).load() == ["a", "b"]


# =============================================================================
# office_cache
# =============================================================================
class TestOfficeCacheDir:
    """缓存目录解析"""

    def test_office_cache_dir_resolves_under_app_data(
        self, office_cache_tmp: Path
    ) -> None:
        """调用期解析为 get_app_data_path()/office_cache。"""
        assert (
            office_cache_module.office_cache_dir()
            == Path(office_cache_tmp) / OFFICE_CACHE_DIR_NAME
        )

    def test_writable_cache_dir_creates_on_demand(self, office_cache_tmp: Path) -> None:
        """幂等创建缓存目录并返回可写目录。"""
        cache_dir: object | None = office_cache_module._writable_cache_dir()
        assert cache_dir is not None
        assert Path(cache_dir).is_dir()
        assert Path(cache_dir).name == OFFICE_CACHE_DIR_NAME


class TestCacheKey:
    """稳定缓存键计算"""

    def test_cache_key_stable_sha1(self, tmp_path: Path) -> None:
        """同文件重复计算得到一致的 40 位 sha1。"""
        from tests.support.data_factories import make_text

        src: str = make_text(tmp_path / "src.txt", content="hello")
        file_info: Dict[str, object] = {"path": src}
        key1: object | None = office_cache_module._cache_key(file_info)
        key2: object | None = office_cache_module._cache_key(file_info)
        assert key1 == key2
        assert key1 is not None
        assert len(key1) == 40

    def test_cache_key_changes_on_content_change(self, tmp_path: Path) -> None:
        """文件内容变化（mtime/size 变化）产生不同键。"""
        from tests.support.data_factories import make_text

        src: str = make_text(tmp_path / "src.txt", content="v1")
        first: object | None = office_cache_module._cache_key({"path": src})
        make_text(tmp_path / "src.txt", content="longer content v2")
        second: object | None = office_cache_module._cache_key({"path": src})
        assert first != second

    def test_cache_key_non_dict_returns_none(self) -> None:
        """非字典输入返回 None。"""
        assert office_cache_module._cache_key("not a dict") is None

    def test_cache_key_missing_path_returns_none(self) -> None:
        """缺少 path 键返回 None。"""
        assert office_cache_module._cache_key({}) is None

    def test_cache_key_unstatable_file_returns_none(self) -> None:
        """源文件不存在（stat 失败）返回 None。"""
        assert office_cache_module._cache_key({"path": "C:\\no\\such\\file.pdf"}) is None

    def test_cache_path_appends_pdf_suffix(self, tmp_path: Path) -> None:
        """缓存路径形如 <cache_dir>/<sha1>.pdf。"""
        from tests.support.data_factories import make_text

        src: str = make_text(tmp_path / "src.txt", content="x")
        cached: object | None = office_cache_module._cache_path(
            {"path": src}, Path(tmp_path) / "office_cache"
        )
        assert cached is not None
        assert cached.parent == Path(tmp_path) / "office_cache"
        assert cached.suffix == ".pdf"

    def test_cache_path_none_when_key_invalid(self) -> None:
        """键不可计算时缓存路径返回 None。"""
        assert office_cache_module._cache_path({}, Path("irrelevant")) is None


class TestGetPutCache:
    """写入与命中"""

    def test_roundtrip_put_then_get(self, office_cache_tmp: Path) -> None:
        """put_cache 后 get_cache_path 命中并返回缓存路径。"""
        from tests.support.data_factories import make_pdf, make_text

        src: str = make_text(office_cache_tmp / "src.txt", content="x")
        pdf: str = make_pdf(office_cache_tmp / "out.pdf")
        file_info: Dict[str, str] = {"path": src}

        assert office_cache_module.get_cache_path(file_info) is None  # 未命中
        cached: Path = office_cache_module.put_cache(file_info, Path(pdf))
        assert cached.suffix == ".pdf"
        assert cached.exists()
        assert office_cache_module.get_cache_path(file_info) == cached

    def test_get_ignores_empty_cache_file(
        self, office_cache_tmp: Path
    ) -> None:
        """缓存文件存在但为空时视为未命中。"""
        from tests.support.data_factories import make_pdf, make_text

        src: str = make_text(office_cache_tmp / "src.txt", content="x")
        pdf: str = make_pdf(office_cache_tmp / "out.pdf")
        file_info: Dict[str, str] = {"path": src}
        cached: Path = office_cache_module.put_cache(file_info, Path(pdf))
        cached.write_bytes(b"")
        assert office_cache_module.get_cache_path(file_info) is None

    def test_get_cache_touches_lru_mtime(self, office_cache_tmp: Path) -> None:
        """命中即刷新 mtime，使最旧优先驱逐成为真正的 LRU。"""
        from tests.support.data_factories import make_pdf, make_text

        src: str = make_text(office_cache_tmp / "src.txt", content="x")
        pdf: str = make_pdf(office_cache_tmp / "out.pdf")
        file_info: Dict[str, str] = {"path": src}
        cached: Path = office_cache_module.put_cache(file_info, Path(pdf))
        old_mtime: int = cached.stat().st_mtime_ns
        time.sleep(0.01)
        office_cache_module.get_cache_path(file_info)
        assert cached.stat().st_mtime_ns > old_mtime

    def test_put_cache_degrades_when_key_invalid(
        self, office_cache_tmp: Path, tmp_path: Path
    ) -> None:
        """键不可计算时原样返回产物 PDF（降级为不缓存）。"""
        from tests.support.data_factories import make_pdf

        pdf: Path = Path(make_pdf(tmp_path / "out.pdf"))
        assert office_cache_module.put_cache({}, pdf) == pdf

    def test_put_cache_degrades_when_cache_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, sample_pdf_file: str
    ) -> None:
        """缓存目录不可用时原样返回产物 PDF。"""
        monkeypatch.setattr(
            office_cache_module, "_writable_cache_dir", lambda: None
        )
        pdf: Path = Path(sample_pdf_file)
        assert office_cache_module.put_cache({"path": "whatever.txt"}, pdf) == pdf

    def test_get_cache_unavailable_returns_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """缓存目录不可用时一律视为未命中。"""
        from tests.support.data_factories import make_text

        monkeypatch.setattr(
            office_cache_module, "_writable_cache_dir", lambda: None
        )
        src: str = make_text(tmp_path / "src.txt", content="x")
        assert office_cache_module.get_cache_path({"path": src}) is None


class TestCleanupCache:
    """过期驱逐与大小裁剪"""

    @staticmethod
    def _make_entry(cache_dir: Path, name: str, age_days: float) -> Path:
        """在缓存目录创建条目并回拨 mtime。"""
        p: Path = cache_dir / name
        p.write_bytes(b"cache-data")
        ts: float = time.time() - age_days * 86400
        os.utime(p, (ts, ts))
        return p

    def test_cleanup_removes_expired_entries(self, office_cache_tmp: Path) -> None:
        """超过 MAX_OFFICE_CACHE_AGE_DAYS 天的条目被删除，新条目保留。"""
        cache_dir: Path = office_cache_module.office_cache_dir()
        cache_dir.mkdir(parents=True)
        old_entry: Path = self._make_entry(
            cache_dir, "old.pdf", MAX_OFFICE_CACHE_AGE_DAYS + 1
        )
        fresh_entry: Path = cache_dir / "fresh.pdf"
        fresh_entry.write_bytes(b"cache-data")

        removed: int = office_cache_module.cleanup_cache(cache_dir)
        assert removed == 1
        assert not old_entry.exists()
        assert fresh_entry.exists()

    def test_cleanup_trims_to_target_size(
        self, office_cache_tmp: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """超过目标容量时按最旧优先裁剪。"""
        monkeypatch.setattr(office_cache_module, "OFFICE_CACHE_TARGET_BYTES", 10)
        cache_dir: Path = office_cache_module.office_cache_dir()
        cache_dir.mkdir(parents=True)
        entries: List[Path] = []
        base: float = time.time()
        for i in range(4):
            p: Path = cache_dir / f"f{i}.pdf"
            p.write_bytes(b"x" * 50)
            os.utime(p, (base - i, base - i))  # f0 最旧
            entries.append(p)

        removed: int = office_cache_module.cleanup_cache(cache_dir)
        assert removed == 4
        assert all(not p.exists() for p in entries)

    def test_cleanup_nonexistent_dir_returns_zero(
        self, office_cache_tmp: Path, tmp_path: Path
    ) -> None:
        """缓存目录不存在返回 0，不抛异常。"""
        assert office_cache_module.cleanup_cache(tmp_path / "nope") == 0

    def test_cleanup_unwritable_dir_returns_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """不可写目录返回 0。"""
        monkeypatch.setattr(
            office_cache_module, "_is_writable_dir", lambda p: False
        )
        assert office_cache_module.cleanup_cache(Path("irrelevant")) == 0

    def test_cleanup_without_cache_dir_returns_zero(
        self, office_cache_tmp: Path
    ) -> None:
        """无缓存目录时默认路径分支返回 0。"""
        assert office_cache_module.cleanup_cache() == 0


class TestPeriodicCleanup:
    """周期清理线程"""

    def test_start_is_idempotent_and_stops(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """重复 start 复用同一线程；stop 成功后再次 stop 返回 False。"""
        monkeypatch.setattr(office_cache_module, "cleanup_cache", lambda: 0)
        office_cache_module.stop_periodic_cleanup()  # 确保无残留线程
        try:
            first = office_cache_module.start_periodic_cleanup(
                interval_seconds=60.0
            )
            second = office_cache_module.start_periodic_cleanup(
                interval_seconds=60.0
            )
            assert first is second
            assert first.is_alive()
            assert first.daemon
            assert office_cache_module.stop_periodic_cleanup() is True
        finally:
            office_cache_module.stop_periodic_cleanup()

    def test_stop_when_not_running_returns_false(self) -> None:
        """未启动（或已停止）时 stop 返回 False。"""
        office_cache_module.stop_periodic_cleanup()
        assert office_cache_module.stop_periodic_cleanup() is False

    def test_periodic_loop_invokes_cleanup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """周期线程按间隔实际调用 cleanup_cache。"""
        calls: List[int] = []
        monkeypatch.setattr(
            office_cache_module,
            "cleanup_cache",
            lambda: calls.append(1) or 0,
        )
        try:
            office_cache_module.start_periodic_cleanup(interval_seconds=0.02)
            deadline: float = time.monotonic() + 3.0
            while not calls and time.monotonic() < deadline:
                time.sleep(0.01)
            assert calls, "周期清理线程应在超时内调用 cleanup_cache"
        finally:
            office_cache_module.stop_periodic_cleanup()