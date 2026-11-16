#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日志保留策略：按时间压缩、按总大小淘汰。

规则（与产品约定一致）：

* 不限制日志文件数量；
* ``logs`` 目录总大小上限 200MB（含 ``.log`` 与 ``.log.gz``）；
* 非活动 ``.log`` 超过 7 天压缩为 ``.log.gz``；
* ``.log.gz`` 从压缩完成时间起超过 20 天删除；
* 当前活动日志永不压缩、永不删除；若它单独超过上限，只记录告警。

本模块只依赖标准库，可被 ``app_logger`` 在初始化期安全导入。
"""

from __future__ import annotations

import gzip
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional

#: ``logs`` 目录总大小上限。
LOG_MAX_TOTAL_BYTES: int = 200 * 1024 * 1024

#: 非活动日志压缩阈值（天）。
LOG_COMPRESS_AFTER_DAYS: float = 7.0

#: 压缩包保留时长（自压缩完成时间起，天）。
LOG_ARCHIVE_RETENTION_DAYS: float = 20.0

#: 压缩临时文件最长保留时间（天）。
_LOG_TMP_RETENTION_DAYS: float = 1.0

_LOG_NAME_RE = re.compile(r"^app_(\d{8})_(\d{6})")
_LOGGER = logging.getLogger("Sopeek.log_retention")


def _is_active(path: Path, active: Optional[Path]) -> bool:
    if active is None:
        return False
    return os.path.normcase(os.path.abspath(str(path))) == os.path.normcase(
        os.path.abspath(str(active))
    )


def _age_days(path: Path) -> float:
    try:
        return (time.time() - path.stat().st_mtime) / 86400.0
    except OSError:
        return 0.0


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _sort_key(path: Path) -> tuple:
    """按文件名时间戳排序；解析失败回退 mtime。"""
    match = _LOG_NAME_RE.match(path.name)
    if match:
        return (0, match.group(1) + match.group(2), path.name)
    try:
        return (1, f"{path.stat().st_mtime:.6f}", path.name)
    except OSError:
        return (2, "", path.name)


def _iter_files(log_dir: Path) -> List[Path]:
    try:
        return [item for item in log_dir.iterdir() if item.is_file()]
    except OSError:
        return []


def _compress_log(path: Path) -> bool:
    """把单个 ``.log`` 压缩为 ``.log.gz``，成功后删除原文件。"""
    if path.suffix.lower() != ".log":
        return False
    archive = path.with_name(path.name + ".gz")
    if archive.exists() and _size(archive) > 0:
        try:
            path.unlink()
            return True
        except OSError:
            return False

    tmp = path.with_name(path.name + ".gz.tmp")
    try:
        tmp.unlink(missing_ok=True)
        with open(path, "rb") as source, gzip.open(tmp, "wb", compresslevel=6) as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        if _size(tmp) <= 0:
            raise OSError("压缩产物为空")
        os.replace(str(tmp), str(archive))
        # 压缩时间 = 20 天保留期的起点。
        os.utime(str(archive), None)
        path.unlink()
        return True
    except OSError as exc:
        _LOGGER.debug("压缩日志失败 %s: %s", path, exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _delete_expired_archives(
    log_dir: Path,
    active: Optional[Path],
    retention_days: float,
) -> int:
    removed = 0
    for item in _iter_files(log_dir):
        if not item.name.lower().endswith(".log.gz"):
            continue
        if _is_active(item, active):
            continue
        if _age_days(item) > retention_days:
            try:
                item.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def _compress_old_logs(
    log_dir: Path,
    active: Optional[Path],
    compress_after_days: float,
) -> int:
    compressed = 0
    for item in _iter_files(log_dir):
        if not item.name.lower().endswith(".log"):
            continue
        if _is_active(item, active):
            continue
        if _age_days(item) <= compress_after_days:
            continue
        if _compress_log(item):
            compressed += 1
    return compressed


def _enforce_size_limit(
    log_dir: Path,
    active: Optional[Path],
    max_total_bytes: int,
) -> int:
    files = _iter_files(log_dir)
    total = sum(_size(item) for item in files)
    if total <= max_total_bytes:
        return 0

    candidates = [item for item in files if not _is_active(item, active)]
    candidates.sort(key=_sort_key)
    removed = 0
    for item in candidates:
        if total <= max_total_bytes:
            break
        size = _size(item)
        try:
            item.unlink()
            total -= size
            removed += 1
        except OSError:
            continue

    if total > max_total_bytes and active is not None and active.exists():
        _LOGGER.warning(
            "活动日志单独超过 logs 总大小上限（%s > %s 字节），保留不删：%s",
            _size(active),
            max_total_bytes,
            active,
        )
    return removed


def _cleanup_stale_tmp(log_dir: Path) -> int:
    removed = 0
    for item in _iter_files(log_dir):
        if not item.name.endswith(".tmp"):
            continue
        if _age_days(item) > _LOG_TMP_RETENTION_DAYS:
            try:
                item.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def _delete_excess_count(
    log_dir: Path,
    active: Optional[Path],
    max_files: Optional[int],
) -> int:
    """可选的按数量淘汰（默认关闭；保留给测试/特殊部署）。"""
    if not max_files or max_files <= 0:
        return 0
    files = [item for item in _iter_files(log_dir) if not _is_active(item, active)]
    files.sort(key=_sort_key, reverse=True)
    removed = 0
    for item in files[int(max_files):]:
        try:
            item.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def maintain_logs(
    log_dir: Optional[Path | str] = None,
    *,
    active_log_path: Optional[Path | str] = None,
    max_total_bytes: Optional[int] = None,
    compress_after_days: Optional[float] = None,
    archive_retention_days: Optional[float] = None,
    max_files: Optional[int] = None,
) -> Dict[str, int]:
    """执行一次完整的日志保留维护。

    Args:
        log_dir: 日志目录；``None`` 时使用 ``_paths.logs_dir()``。
        active_log_path: 当前活动日志；永不压缩/删除。
        max_total_bytes: 总大小上限；默认 200MB。
        compress_after_days: 压缩阈值；默认 7 天。
        archive_retention_days: 压缩包保留期；默认 20 天。
        max_files: 可选的日志文件数量上限；默认 ``None``（不限制）。

    Returns:
        Dict[str, int]: ``compressed`` / ``deleted`` / ``tmp_deleted`` / ``size``。
    """
    if log_dir is None:
        from sopeek._paths import logs_dir as _logs_dir

        root = _logs_dir()
    else:
        root = Path(log_dir)
        root.mkdir(parents=True, exist_ok=True)
    active = Path(active_log_path) if active_log_path else None
    total_limit = (
        int(max_total_bytes) if max_total_bytes is not None else LOG_MAX_TOTAL_BYTES
    )
    compress_days = (
        float(compress_after_days)
        if compress_after_days is not None
        else LOG_COMPRESS_AFTER_DAYS
    )
    archive_days = (
        float(archive_retention_days)
        if archive_retention_days is not None
        else LOG_ARCHIVE_RETENTION_DAYS
    )

    deleted = _delete_expired_archives(root, active, archive_days)
    compressed = _compress_old_logs(root, active, compress_days)
    deleted += _enforce_size_limit(root, active, total_limit)
    deleted += _delete_excess_count(root, active, max_files)
    tmp_deleted = _cleanup_stale_tmp(root)

    total_size = sum(_size(item) for item in _iter_files(root))
    return {
        "compressed": compressed,
        "deleted": deleted,
        "tmp_deleted": tmp_deleted,
        "size": total_size,
    }


__all__ = [
    "LOG_MAX_TOTAL_BYTES",
    "LOG_COMPRESS_AFTER_DAYS",
    "LOG_ARCHIVE_RETENTION_DAYS",
    "maintain_logs",
]
