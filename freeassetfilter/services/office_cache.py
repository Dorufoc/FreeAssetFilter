#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

Office 转换 PDF 缓存模块（T8）。

将 LO/COM 后端产出的 PDF 按源文件 ``(path, mtime_ns, size)`` 键缓存到
``data/office_cache/``，命中时跳过重复转换；清理按「7 天过期 + 大小上限」
驱逐，最旧优先，幂等且永不抛出。缓存目录不可写时全部函数降级为
“不缓存”（转换流程照常进行）。

设计要点：
- 普通模块（非单例、无 ``_instance``、无需注册到 ``reset_singletons``）；
- 缓存目录在**调用期**解析（非模块导入期快照），便于测试 monkeypatch；
- 必须使用 ``freeassetfilter.utils.path_utils.get_app_data_path()``（开发
  环境返回项目根 ``data/``），**不是** ``freeassetfilter.core._paths`` 的
  包内版本 —— 两者同名不同义，本模块刻意选择 utils 变体（见下方护栏注释）。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time
from pathlib import Path

from freeassetfilter.utils import path_utils
from freeassetfilter.utils.app_logger import debug, warning

# ⚠️ .gitignore 护栏（请勿删除/修改） ────────────────────────────────────
# 仓库 `.gitignore` 第 21 行的 `data/` 规则已覆盖本缓存目录
# （``data/office_cache/``，源自 ``utils.path_utils.get_app_data_path()``）。
# 缓存属运行期再生成数据，不应进入版本控制。
# **不要** 为 office_cache 追加任何 .gitignore 规则 —— 那将破坏此设计意图。

# 缓存子目录名（相对 get_app_data_path() 的 data/）。
OFFICE_CACHE_DIR_NAME: str = "office_cache"

# 缓存条目超过该天数即视为过期（清理时优先删除）。镜像 ThumbnailManager
# 的 MAX_THUMB_CACHE_* 常量风格。
MAX_OFFICE_CACHE_AGE_DAYS: int = 7

# 缓存总容量预算（MB）。清理目标 = 预算的 80%（镜像 THUMB_CACHE_TARGET_SIZE
# 风格），留出余量避免频繁触发清理。
MAX_OFFICE_CACHE_SIZE_MB: int = 512
OFFICE_CACHE_TARGET_SIZE_MB: int = int(MAX_OFFICE_CACHE_SIZE_MB * 0.8)  # 409 MB

# 以字节为单位的清理阈值。``cleanup_cache`` 在**运行期**读取本常量（而非
# 导入时快照），使测试可通过 monkeypatch 缩小阈值。
OFFICE_CACHE_TARGET_BYTES: int = OFFICE_CACHE_TARGET_SIZE_MB * 1024 * 1024

# 缓存文件后缀（产物均为 PDF）。
_CACHE_SUFFIX: str = ".pdf"

# 周期清理间隔（秒）：``OfficeConverter.convert()`` 首次调用时惰性启动
# 一个 daemon 线程，每 30 分钟清理一次过期 / 超限缓存条目。
OFFICE_CACHE_CLEANUP_INTERVAL_SECONDS: float = 1800.0

# ── 周期清理线程状态（普通模块级状态，无单例注册） ───────────────────
# 模块级 ``threading.Lock`` 保护「启动 / 停止」竞态；daemon 线程在任何
# 情况下都不会阻止进程退出。
_PERIODIC_CLEANUP_LOCK: threading.Lock = threading.Lock()
_PERIODIC_CLEANUP_THREAD: threading.Thread | None = None
_PERIODIC_CLEANUP_STOP_REQUESTED: threading.Event | None = None


# ── 目录解析 ───────────────────────────────────────────────────────────


def office_cache_dir() -> Path:
    """
    惰性解析缓存目录 = ``path_utils.get_app_data_path() / "office_cache"``。

    在调用期解析（而非模块导入期快照），使测试可通过 monkeypatch
    ``freeassetfilter.utils.path_utils.get_app_data_path`` 或本函数将缓存
    重定向到 ``tmp_path``。

    Returns
    -------
    Path
        缓存目录绝对路径（``get_app_data_path()`` 内部会确保 data/ 存在；
        本函数不负责创建 office_cache 子目录）。
    """
    return Path(path_utils.get_app_data_path()) / OFFICE_CACHE_DIR_NAME


# ── 内部工具 ───────────────────────────────────────────────────────────


def _cache_key(file_info: dict) -> str | None:
    """
    按 ``(path, mtime_ns, size)`` 计算稳定缓存键（sha1 十六进制串）。

    Parameters
    ----------
    file_info : dict
        与 ``PreviewerRegistry`` 契约一致的文件信息，需含 ``"path"`` 键。

    Returns
    -------
    str | None
        sha1 键；``file_info`` 非法、缺少 ``"path"`` 或源文件不可 stat
        时返回 ``None``（视为“不可缓存”）。
    """
    if not isinstance(file_info, dict):
        return None
    path = file_info.get("path")
    if path is None:
        return None
    try:
        st = os.stat(str(path))
    except OSError:
        return None
    raw = f"{path}|{st.st_mtime_ns}|{st.st_size}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _cache_path(file_info: dict, cache_dir: Path) -> Path | None:
    """
    计算 *file_info* 对应的缓存文件路径（不校验文件是否存在）。

    Parameters
    ----------
    file_info : dict
        文件信息（含 ``"path"``）。
    cache_dir : Path
        缓存目录。

    Returns
    -------
    Path | None
        形如 ``<cache_dir>/<sha1>.pdf`` 的路径；键不可计算时为 ``None``。
    """
    key = _cache_key(file_info)
    if key is None:
        return None
    return cache_dir / f"{key}{_CACHE_SUFFIX}"


def _is_writable_dir(cache_dir: Path) -> bool:
    """
    尽力检查 *cache_dir* 是否可写；任何异常视为不可写。

    说明：``os.access`` 在 Windows 上对 ACL 的判断可能不完全可靠，本检查
    仅是第一道防线，真正的写操作仍由各函数的 try/except OSError 兜底。
    """
    try:
        return os.access(cache_dir, os.W_OK)
    except OSError:
        return False


def _writable_cache_dir() -> Path | None:
    """
    解析缓存目录并确保可写；不可写时返回 ``None``。

    Returns
    -------
    Path | None
        可写缓存目录；目录解析失败 / mkdir 失败 / 无写权限时返回 ``None``
        （调用方据此降级为“不缓存”）。
    """
    try:
        cache_dir = office_cache_dir()
    except Exception as e:
        debug(f"[OfficeCache] 缓存目录解析失败: {e}")
        return None
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        warning(f"[OfficeCache] 缓存目录不可写，本次降级为不缓存: {e}")
        return None
    if not _is_writable_dir(cache_dir):
        return None
    return cache_dir


def _file_mtime(path: Path) -> float:
    """读取文件 mtime；stat 失败返回 ``inf``（视为最新，避免被误删）。"""
    try:
        return path.stat().st_mtime
    except OSError:
        return float("inf")


def _file_size(path: Path) -> int:
    """读取文件大小；stat 失败返回 0。"""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _unlink_safe(path: Path) -> bool:
    """尽力删除文件；删除失败（如只读 / 权限）返回 ``False``，不抛出。"""
    try:
        path.unlink()
        return True
    except OSError:
        return False


def _touch_safe(path: Path) -> None:
    """尽力把 *path* 的 mtime 刷新到当前时间（LRU 语义）；失败静默。

    命中缓存时刷新 mtime，使 ``cleanup_cache`` 的「最旧优先」成为真正的
    LRU——近期使用过的缓存条目不会被提前滚掉。``os.utime`` 任何失败
    （如文件已被并发删除）都静默忽略，不影响命中返回。

    Parameters
    ----------
    path : Path
        缓存 PDF 文件路径。
    """
    try:
        os.utime(path)
    except OSError:
        pass


# ── 公共 API ───────────────────────────────────────────────────────────


def get_cache_path(file_info: dict) -> Path | None:
    """
    返回 *file_info* 对应的有效缓存 PDF 路径；未命中返回 ``None``。

    命中条件：键（path+mtime_ns+size）一致，且缓存文件存在、非空。
    缓存目录不可写（含只读）时一律视为未命中（“降级为不缓存”）。

    Parameters
    ----------
    file_info : dict
        文件信息（含 ``"path"``）。

    Returns
    -------
    Path | None
        缓存 PDF 路径；未命中或缓存不可用时为 ``None``。永不抛出。
    """
    cache_dir = _writable_cache_dir()
    if cache_dir is None:
        return None
    cached = _cache_path(file_info, cache_dir)
    if cached is None:
        return None
    try:
        is_hit = cached.is_file() and cached.stat().st_size > 0
    except OSError:
        return None
    if not is_hit:
        return None
    # LRU：命中即刷新 mtime，使 cleanup 的「最旧优先」成为真正的
    # 最近使用优先——近期打开的文件不会被提前滚掉。touch 为 best-effort，
    # 任何失败都静默忽略，绝不把命中变成 miss（``_touch_safe`` 内部已吞掉
    # ``os.utime`` 的 ``OSError``，这里再包一层是防御 monkeypatch / 未来
    # 实现变化）。
    try:
        _touch_safe(cached)
    except OSError:
        pass
    return cached


# ── 周期清理 ───────────────────────────────────────────────────────────


def _periodic_cleanup_loop(interval_seconds: float, stop_event: threading.Event) -> None:
    """daemon 线程体：周期调用 ``cleanup_cache()``，异常吞掉保活。

    ``cleanup_cache()`` 本身幂等且永不抛出，这里再包一层 try/except
    是为了防御未来实现出现意外异常也不让线程退出。

    Parameters
    ----------
    interval_seconds : float
        两次清理之间的间隔（秒）。
    stop_event : threading.Event
        停止信号；``stop_periodic_cleanup()`` 设置后本循环退出。
    """
    while not stop_event.wait(interval_seconds):
        try:
            cleanup_cache()
        except Exception:  # noqa: BLE001 - 周期清理异常绝不退出线程
            pass


def start_periodic_cleanup(interval_seconds: float = OFFICE_CACHE_CLEANUP_INTERVAL_SECONDS) -> threading.Thread:
    """幂等启动周期清理 daemon 线程。

    已启动（线程仍存活）时复用现有线程，不做二次启动；返回线程对象。
    线程为 daemon——进程退出时不阻塞。

    Parameters
    ----------
    interval_seconds : float
        清理间隔秒数，默认 ``OFFICE_CACHE_CLEANUP_INTERVAL_SECONDS``
        （30 分钟）；测试可传极小值 + monkeypatch ``cleanup_cache`` spy。

    Returns
    -------
    threading.Thread
        正在运行的清理线程（本次启动或既有复用）。
    """
    global _PERIODIC_CLEANUP_THREAD, _PERIODIC_CLEANUP_STOP_REQUESTED

    with _PERIODIC_CLEANUP_LOCK:
        existing = _PERIODIC_CLEANUP_THREAD
        if existing is not None and existing.is_alive():
            return existing

        stop_event = threading.Event()
        thread = threading.Thread(
            target=_periodic_cleanup_loop,
            args=(interval_seconds, stop_event),
            name="office-cache-periodic-cleanup",
            daemon=True,
        )
        _PERIODIC_CLEANUP_THREAD = thread
        _PERIODIC_CLEANUP_STOP_REQUESTED = stop_event
        thread.start()
        return thread


def stop_periodic_cleanup() -> bool:
    """请求停止周期清理线程并 ``join``（防测试悬挂）。

    未启动（或线程已自行退出）返回 ``False``；成功请求停止返回 ``True``。
    已停止的线程对象会被清除，下次 ``start_periodic_cleanup`` 会重新创建。

    Returns
    -------
    bool
        ``True`` 表示本次成功触发了停止，``False`` 表示本来就未运行。
    """
    global _PERIODIC_CLEANUP_THREAD, _PERIODIC_CLEANUP_STOP_REQUESTED

    with _PERIODIC_CLEANUP_LOCK:
        thread = _PERIODIC_CLEANUP_THREAD
        stop_event = _PERIODIC_CLEANUP_STOP_REQUESTED
        if thread is None or not thread.is_alive():
            _PERIODIC_CLEANUP_THREAD = None
            _PERIODIC_CLEANUP_STOP_REQUESTED = None
            return False
        if stop_event is not None:
            stop_event.set()
    # 锁外 join：设置 stop_event 后 `stop_event.wait` 立即返回，循环随即
    # 退出；5 秒只是安全上界（处理未来实现异常），daemon 属性保证即使
    # join 被跳过也不会阻塞进程退出。
    thread.join(timeout=5.0)
    _PERIODIC_CLEANUP_THREAD = None
    _PERIODIC_CLEANUP_STOP_REQUESTED = None
    return True


def put_cache(file_info: dict, pdf_path: Path) -> Path:
    """
    将产物 PDF 复制进缓存，返回缓存内路径。

    缓存不可用（不可写 / 键不可计算）或复制失败时降级：原样返回
    *pdf_path*，调用方仍可继续预览，转换流程不受阻断。

    Parameters
    ----------
    file_info : dict
        文件信息（含 ``"path"``）。
    pdf_path : Path
        后端产出的 PDF 文件路径。

    Returns
    -------
    Path
        缓存内的 PDF 路径；降级时为 *pdf_path* 本身。永不抛出。
    """
    cache_dir = _writable_cache_dir()
    if cache_dir is None:
        return pdf_path
    cached = _cache_path(file_info, cache_dir)
    if cached is None:
        return pdf_path
    try:
        shutil.copy2(pdf_path, cached)
    except OSError as e:
        warning(f"[OfficeCache] 写入缓存失败，本次跳过缓存: {e}")
        return pdf_path
    return cached


def cleanup_cache(cache_dir: Path | None = None) -> int:
    """
    驱逐过期条目并按大小上限裁剪（最旧优先），返回删除的条目数。

    幂等：重复调用安全，无副作用（仅删除应删的条目）。永不抛出 ——
    目录不可访问 / 不可写 / 单文件删除失败均静默跳过。

    Parameters
    ----------
    cache_dir : Path | None
        显式指定缓存目录（测试用）；为 ``None`` 时使用
        ``office_cache_dir()`` 解析。

    Returns
    -------
    int
        本次删除的缓存条目数量。
    """
    if cache_dir is None:
        cache_dir = _writable_cache_dir()
        if cache_dir is None:
            return 0
    else:
        cache_dir = Path(cache_dir)
        if not _is_writable_dir(cache_dir):
            return 0

    try:
        if not cache_dir.is_dir():
            return 0
    except OSError:
        return 0

    try:
        entries = [p for p in cache_dir.iterdir() if p.is_file()]
    except OSError:
        return 0

    removed = 0

    # 1) 过期驱逐（mtime 超过 MAX_OFFICE_CACHE_AGE_DAYS 天）
    cutoff = time.time() - MAX_OFFICE_CACHE_AGE_DAYS * 86400
    remaining: list[Path] = []
    for p in entries:
        if _file_mtime(p) < cutoff:
            if _unlink_safe(p):
                removed += 1
        else:
            remaining.append(p)

    # 2) 大小裁剪（最旧优先，删到目标阈值以下）
    remaining.sort(key=_file_mtime)
    total = sum(_file_size(p) for p in remaining)
    for p in remaining:
        if total <= OFFICE_CACHE_TARGET_BYTES:
            break
        size = _file_size(p)
        if _unlink_safe(p):
            removed += 1
            total -= size

    return removed


def _ensure_periodic_cleanup_started() -> None:
    """惰性启动一次周期清理（供 ``OfficeConverter.convert()`` 首次调用）。

    幂等：后到的调用复用已在运行的线程，应用生命周期内只启动一次。
    """
    start_periodic_cleanup(OFFICE_CACHE_CLEANUP_INTERVAL_SECONDS)


__all__ = [
    "MAX_OFFICE_CACHE_AGE_DAYS",
    "MAX_OFFICE_CACHE_SIZE_MB",
    "OFFICE_CACHE_CLEANUP_INTERVAL_SECONDS",
    "OFFICE_CACHE_DIR_NAME",
    "OFFICE_CACHE_TARGET_BYTES",
    "OFFICE_CACHE_TARGET_SIZE_MB",
    "cleanup_cache",
    "get_cache_path",
    "office_cache_dir",
    "put_cache",
    "start_periodic_cleanup",
    "stop_periodic_cleanup",
]
