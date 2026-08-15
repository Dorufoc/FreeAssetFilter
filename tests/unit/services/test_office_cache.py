#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
office_cache 缓存模块单元测试（T8，TDD）。

通过 monkeypatch 把缓存目录重定向到 tmp_path，验证：
- 首次转换 miss → put_cache 后缓存文件存在且位于键控路径
- 同 path+mtime+size 二次调用命中，后端不再被调用（Metis E4）
- mtime / size 变化 → miss（不同键）
- 过期条目（超过 7 天）被驱逐
- cleanup_cache 幂等（重复调用安全）
- 大小上限裁剪（最旧优先）
- 缓存目录不可写 / 无法创建 → 全部函数降级为“不缓存”且不抛出
- office_cache_dir 使用 utils.path_utils 变体解析
"""

import os
import time
from pathlib import Path

import pytest

from freeassetfilter.services import office_cache


def _write_source(
    tmp_path: Path, name: str = "sample.docx", body: bytes = b"docx-content" * 64
) -> Path:
    """构造一个真实的 Office 源文件。"""
    src = tmp_path / name
    src.write_bytes(body)
    return src


def _make_file_info(src: Path) -> dict:
    """构造与 PreviewerRegistry 契约一致的 file_info。"""
    return {"path": str(src), "suffix": "docx"}


def _fake_pdf(tmp_path: Path, name: str = "converted.pdf") -> Path:
    """构造一个产物 PDF。"""
    pdf = tmp_path / name
    pdf.write_bytes(b"%PDF-1.4 fake")
    return pdf


@pytest.fixture()
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """将 office_cache 缓存目录重定向到 tmp_path 下（调用期 monkeypatch）。"""
    _cache_dir = tmp_path / "office_cache"
    monkeypatch.setattr(office_cache, "office_cache_dir", lambda: _cache_dir)
    return _cache_dir


# ===========================================================================
# 目录解析
# ===========================================================================


class TestOfficeCacheDir:
    """缓存目录必须来自 ``utils.path_utils.get_app_data_path()`` 变体。"""

    def test_resolves_under_app_data_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """office_cache_dir() == get_app_data_path() / "office_cache"。"""
        monkeypatch.setattr(
            "freeassetfilter.utils.path_utils.get_app_data_path",
            lambda: str(tmp_path / "data"),
        )
        assert office_cache.office_cache_dir() == tmp_path / "data" / "office_cache"

    def test_constant_mirrors_thumbnail_style(self) -> None:
        """常量镜像 ThumbnailManager 风格（7 天 + 512MB 预算 + 80% 目标）。"""
        assert office_cache.MAX_OFFICE_CACHE_AGE_DAYS == 7
        assert office_cache.MAX_OFFICE_CACHE_SIZE_MB == 512
        assert office_cache.OFFICE_CACHE_TARGET_SIZE_MB == int(
            office_cache.MAX_OFFICE_CACHE_SIZE_MB * 0.8
        )
        assert (
            office_cache.OFFICE_CACHE_TARGET_BYTES
            == office_cache.OFFICE_CACHE_TARGET_SIZE_MB * 1024 * 1024
        )


# ===========================================================================
# miss → put → hit
# ===========================================================================


class TestMissPutHit:
    """首次 miss，put_cache 后命中文件存在；二次调用命中且后端不再调用。"""

    def test_first_call_is_miss(self, tmp_path: Path, cache_dir: Path) -> None:
        """缓存为空时 get_cache_path 返回 None。"""
        src = _write_source(tmp_path)
        assert office_cache.get_cache_path(_make_file_info(src)) is None

    def test_put_cache_creates_keyed_file(self, tmp_path: Path, cache_dir: Path) -> None:
        """put_cache 后缓存文件存在于键控路径（<cache_dir>/<sha1>.pdf）。"""
        src = _write_source(tmp_path)
        pdf = _fake_pdf(tmp_path)
        cached = office_cache.put_cache(_make_file_info(src), pdf)

        assert isinstance(cached, Path)
        assert cached.parent == cache_dir
        assert cached.suffix == ".pdf"
        assert cached.is_file()
        assert cached.read_bytes() == pdf.read_bytes()

    def test_second_call_hits_and_backend_not_reinvoked(
        self, tmp_path: Path, cache_dir: Path
    ) -> None:
        """Metis E4：同 path+mtime+size 二次调用命中，后端不再被调用。"""
        src = _write_source(tmp_path)
        info = _make_file_info(src)
        backend_calls: list[int] = []

        def backend(_info: dict) -> Path:
            """模拟转换后端：每调用一次产出一个新 PDF。"""
            backend_calls.append(1)
            pdf = tmp_path / f"conv-{len(backend_calls)}.pdf"
            pdf.write_bytes(b"%PDF")
            return pdf

        # 模拟调用方逻辑：miss 才走后端并落缓存
        hit = office_cache.get_cache_path(info)
        if hit is None:
            office_cache.put_cache(info, backend(info))

        # 第二次“转换”：命中缓存则后端不得再被调用
        hit2 = office_cache.get_cache_path(info)
        assert hit2 is not None
        if hit2 is None:  # pragma: no cover - 不应走到
            backend(info)

        assert len(backend_calls) == 1

    def test_get_cache_path_ignores_empty_or_missing_cached_file(
        self, tmp_path: Path, cache_dir: Path
    ) -> None:
        """缓存文件为空（损坏）或已被删除时视为未命中。"""
        src = _write_source(tmp_path)
        info = _make_file_info(src)
        cached = office_cache.put_cache(info, _fake_pdf(tmp_path))

        cached.write_bytes(b"")  # 清空模拟损坏
        assert office_cache.get_cache_path(info) is None

        cached.unlink()  # 删除
        assert office_cache.get_cache_path(info) is None

    def test_hit_refreshes_mtime_for_lru(self, tmp_path: Path, cache_dir: Path) -> None:
        """LRU 需求：命中时把缓存 mtime 刷到当前，避免近期使用被提前滚掉。"""
        src = _write_source(tmp_path)
        info = _make_file_info(src)
        cached = office_cache.put_cache(info, _fake_pdf(tmp_path))

        past = time.time() - 3600  # 一小时前（模拟旧创建时间）
        os.utime(cached, (past, past))
        before = cached.stat().st_mtime

        hit = office_cache.get_cache_path(info)

        assert hit == cached
        refreshed = cached.stat().st_mtime
        assert refreshed > before
        # 刷新到接近当前时间（误差 < 2 秒）
        assert time.time() - refreshed < 2.0

    def test_hit_refresh_failure_is_silent(
        self, tmp_path: Path, cache_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """mtime 刷新失败（os.utime 抛异常）不影响命中返回。"""
        src = _write_source(tmp_path)
        info = _make_file_info(src)
        office_cache.put_cache(info, _fake_pdf(tmp_path))

        def _boom(*_a, **_k):
            raise OSError("touch failed")

        monkeypatch.setattr(office_cache, "_touch_safe", _boom)

        # best-effort：即便触摸失败，命中语义不变
        assert office_cache.get_cache_path(info) is not None


# ===========================================================================
# 键稳定性：mtime / size 变化 → miss
# ===========================================================================


class TestKeyStaleness:
    """键 = (path, mtime_ns, size)：任一变化都应导致 miss。"""

    def test_mtime_change_causes_miss(self, tmp_path: Path, cache_dir: Path) -> None:
        """mtime 变化 → miss；恢复原 mtime → 再次命中。"""
        src = _write_source(tmp_path)
        info = _make_file_info(src)
        orig_ns = src.stat().st_mtime_ns
        office_cache.put_cache(info, _fake_pdf(tmp_path))
        assert office_cache.get_cache_path(info) is not None

        os.utime(src, ns=(orig_ns + 10**9, orig_ns + 10**9))
        assert office_cache.get_cache_path(info) is None

        os.utime(src, ns=(orig_ns, orig_ns))
        assert office_cache.get_cache_path(info) is not None

    def test_size_change_causes_miss(self, tmp_path: Path, cache_dir: Path) -> None:
        """size 变化 → miss；恢复大小与原 mtime → 再次命中。"""
        src = _write_source(tmp_path)
        info = _make_file_info(src)
        orig_ns = src.stat().st_mtime_ns
        office_cache.put_cache(info, _fake_pdf(tmp_path))
        assert office_cache.get_cache_path(info) is not None

        src.write_bytes(b"docx-content" * 128)  # 变大
        assert office_cache.get_cache_path(info) is None

        src.write_bytes(b"docx-content" * 64)  # 恢复大小
        os.utime(src, ns=(orig_ns, orig_ns))  # 恢复 mtime
        assert office_cache.get_cache_path(info) is not None


# ===========================================================================
# cleanup_cache：过期驱逐 + 大小裁剪 + 幂等
# ===========================================================================


class TestCleanupEviction:
    """清理按 7 天过期驱逐并按大小上限（最旧优先）裁剪，幂等。"""

    def test_expired_entries_evicted(self, tmp_path: Path) -> None:
        """超过 7 天的缓存条目被驱逐，新鲜条目保留。"""
        cache_dir = tmp_path / "office_cache"
        cache_dir.mkdir()
        fresh = cache_dir / "fresh.pdf"
        fresh.write_bytes(b"f")
        stale = cache_dir / "stale.pdf"
        stale.write_bytes(b"s")
        old = time.time() - 8 * 86400
        os.utime(stale, (old, old))

        removed = office_cache.cleanup_cache(cache_dir)

        assert removed == 1
        assert not stale.exists()
        assert fresh.exists()

    def test_cleanup_is_idempotent(self, tmp_path: Path) -> None:
        """重复调用 cleanup_cache 安全且无副作用。"""
        cache_dir = tmp_path / "office_cache"
        cache_dir.mkdir()
        (cache_dir / "a.pdf").write_bytes(b"x")

        assert office_cache.cleanup_cache(cache_dir) == 0
        assert office_cache.cleanup_cache(cache_dir) == 0
        assert len(list(cache_dir.iterdir())) == 1

    def test_size_cap_trims_oldest_first(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """总量超上限时按 mtime 最旧优先删除至目标阈值以下。"""
        cache_dir = tmp_path / "office_cache"
        cache_dir.mkdir()
        monkeypatch.setattr(office_cache, "OFFICE_CACHE_TARGET_BYTES", 100)
        base = time.time() - 86400  # 1 天前，未过期
        for i in range(5):
            p = cache_dir / f"{i}.pdf"
            p.write_bytes(b"z" * 50)
            os.utime(p, (base + i, base + i))  # i=0 最旧

        removed = office_cache.cleanup_cache(cache_dir)

        # 5×50=250 字节 > 100 → 删最旧的 0/1/2，剩 3/4（100 字节）
        assert removed == 3
        assert sorted(p.name for p in cache_dir.iterdir()) == ["3.pdf", "4.pdf"]


# ===========================================================================
# 不可写缓存目录 → 全部降级为“不缓存”
# ===========================================================================


class TestUnwritableDegradation:
    """缓存目录不可写时所有函数降级为“不缓存”且不抛出（QA 场景）。"""

    def test_readonly_dir_via_os_access_degrades(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cache_dir: Path
    ) -> None:
        """os.access 判定不可写（模拟只读目录）→ get/put/cleanup 全部降级。"""
        src = _write_source(tmp_path)
        info = _make_file_info(src)
        monkeypatch.setattr(office_cache.os, "access", lambda *a, **k: False)

        assert office_cache.get_cache_path(info) is None

        pdf = _fake_pdf(tmp_path)
        assert office_cache.put_cache(info, pdf) is pdf  # 不复制，原样返回

        assert office_cache.cleanup_cache() == 0
        # 确无缓存落盘
        assert len(list(cache_dir.iterdir())) == 0

    def test_cache_dir_under_regular_file_degrades(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """真实代码路径：父路径是文件 → mkdir 抛 OSError → 全部降级不抛出。"""
        blocker = tmp_path / "blocker"
        blocker.write_bytes(b"not a dir")
        monkeypatch.setattr(
            office_cache, "office_cache_dir", lambda: blocker / "office_cache"
        )
        src = _write_source(tmp_path)
        info = _make_file_info(src)

        assert office_cache.get_cache_path(info) is None

        pdf = _fake_pdf(tmp_path)
        assert office_cache.put_cache(info, pdf) is pdf

        assert office_cache.cleanup_cache() == 0

    def test_cleanup_with_missing_dir_is_noop(self, tmp_path: Path) -> None:
        """缓存目录不存在时 cleanup_cache 返回 0 且不创建目录。"""
        cache_dir = tmp_path / "office_cache"
        assert office_cache.cleanup_cache(cache_dir) == 0
        assert not cache_dir.exists()


# ===========================================================================
# 周期自动清理（B 需求）：daemon 线程 + 幂等启动/停止 + 异常保活
# ===========================================================================


class TestPeriodicCleanup:
    """``start/stop_periodic_cleanup`` 幂等、可停止、线程异常保活。"""

    def _wait_until(
        self, predicate, timeout: float = 2.0, interval: float = 0.01
    ) -> bool:
        """轮询等待谓词成立（避免真实 sleep 超时）。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(interval)
        return predicate()

    def test_constant_exists(self) -> None:
        """OFFICE_CACHE_CLEANUP_INTERVAL_SECONDS 默认 1800 秒。"""
        assert office_cache.OFFICE_CACHE_CLEANUP_INTERVAL_SECONDS == 1800.0

    def test_start_is_idempotent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """两次启动返回同一线程；只启动一个 daemon 线程。"""
        office_cache.stop_periodic_cleanup()
        monkeypatch.setattr(office_cache, "cleanup_cache", lambda: None)

        t1 = office_cache.start_periodic_cleanup(0.01)
        t2 = office_cache.start_periodic_cleanup(0.01)

        try:
            assert t1 is t2
            assert t1.is_alive()
            assert t1.daemon
        finally:
            office_cache.stop_periodic_cleanup()

    def test_stop_when_not_started_returns_false(self) -> None:
        """未启动时 stop 返回 False。"""
        office_cache.stop_periodic_cleanup()  # 确保已停止
        assert office_cache.stop_periodic_cleanup() is False

    def test_periodic_cleanup_runs_and_stop_halts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """短间隔下 cleanup 被周期性调用；stop 后不再调用。"""
        office_cache.stop_periodic_cleanup()
        calls: list[int] = []

        def _spy() -> None:
            calls.append(1)

        monkeypatch.setattr(office_cache, "cleanup_cache", _spy)

        office_cache.start_periodic_cleanup(0.01)
        assert self._wait_until(lambda: len(calls) >= 2)

        assert office_cache.stop_periodic_cleanup() is True
        after_stop = len(calls)
        time.sleep(0.05)  # 给一个周期，确认不再调用
        assert len(calls) == after_stop

    def test_thread_survives_cleanup_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cleanup 抛异常时线程仍然存活且继续下一轮。"""
        office_cache.stop_periodic_cleanup()
        attempts: list[int] = []

        def _boom() -> None:
            attempts.append(1)
            raise RuntimeError("cleanup boom")

        monkeypatch.setattr(office_cache, "cleanup_cache", _boom)

        thread = office_cache.start_periodic_cleanup(0.01)
        try:
            assert self._wait_until(lambda: len(attempts) >= 2)
            # 异常被吞掉，线程保活
            assert thread.is_alive()
        finally:
            office_cache.stop_periodic_cleanup()

    def test_start_after_stop_creates_new_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """stop 后再 start 生成全新线程。"""
        office_cache.stop_periodic_cleanup()
        monkeypatch.setattr(office_cache, "cleanup_cache", lambda: None)

        t1 = office_cache.start_periodic_cleanup(0.01)
        office_cache.stop_periodic_cleanup()
        t2 = office_cache.start_periodic_cleanup(0.01)
        try:
            assert t1 is not t2
            assert t2.is_alive()
        finally:
            office_cache.stop_periodic_cleanup()
