#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行期存储布局：创建、迁移与清理。

本模块与 :mod:`sopeek._paths` 分工：

* ``_paths`` 只回答“路径在哪”；
* 本模块负责“从旧布局搬到新布局”和“哪些文件可以安全删除”。

布局版本写入 ``<data>/.layout_version.json``。迁移是幂等的：标记为
``version=2`` 且 ``complete=true`` 时直接跳过；失败项保留源文件，下次启动
重试，绝不删除唯一副本。
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sopeek import _paths
from sopeek.utils.atomic_json import read_json, write_json_atomic

#: 当前存储布局版本。
LAYOUT_VERSION = 2

#: 布局标记文件名（位于数据根）。
LAYOUT_MARKER_NAME = ".layout_version.json"

#: 迁移日志上限（避免报告自身无限增长）。
_MAX_MIGRATION_ERRORS = 20

_LOCK = threading.RLock()
_READY = False


# ── 通用工具 ─────────────────────────────────────────────────────────


def _log_warning(message: str) -> None:
    """延迟导入日志组件，避免初始化期循环。"""
    try:
        from sopeek.utils import app_logger

        app_logger.warning(message)
    except Exception:
        pass


def _log_debug(message: str) -> None:
    try:
        from sopeek.utils import app_logger

        app_logger.debug(message)
    except Exception:
        pass


def _norm(path: Path | str) -> str:
    """返回用于比较的规范化绝对路径（Windows 大小写不敏感）。"""
    return os.path.normcase(os.path.abspath(str(path)))


def _is_within(path: Path | str, base: Path | str) -> bool:
    """判断 *path* 是否位于 *base* 目录内（含自身）。"""
    normalized = _norm(path)
    base_normalized = _norm(base)
    return normalized == base_normalized or normalized.startswith(base_normalized + os.sep)


def _rewrite_under(path: str, old_dir: Path, new_dir: Path) -> str:
    """把 *path* 从 *old_dir* 前缀改写到 *new_dir*；不在其下时原样返回。"""
    if not isinstance(path, str) or not path:
        return path
    if not _is_within(path, old_dir):
        return path
    try:
        relative = os.path.relpath(os.path.abspath(path), os.path.abspath(str(old_dir)))
    except ValueError:
        return path
    return str(Path(new_dir) / relative)


def _safe_unlink(path: Path) -> bool:
    try:
        if path.is_file() or path.is_symlink():
            path.unlink()
        else:
            shutil.rmtree(path)
        return True
    except OSError:
        return False


def _dir_latest_mtime(path: Path) -> float:
    """返回目录树内最新 mtime；路径不存在返回 0。"""
    latest = 0.0
    try:
        if path.is_file():
            return path.stat().st_mtime
        for root, _dirs, files in os.walk(path):
            try:
                latest = max(latest, Path(root).stat().st_mtime)
            except OSError:
                continue
            for name in files:
                try:
                    latest = max(latest, (Path(root) / name).stat().st_mtime)
                except OSError:
                    continue
    except OSError:
        return 0.0
    return latest


def _ensure_layout_dirs() -> None:
    """创建 v2 布局的全部一级/二级目录（空目录成本极低）。"""
    for getter in (
        _paths.config_dir,
        _paths.state_dir,
        _paths.assets_dir,
        _paths.cache_dir,
        _paths.logs_dir,
        _paths.updates_dir,
        _paths.diagnostics_dir,
        _paths.temp_dir,
        _paths.backgrounds_dir,
        _paths.luts_dir,
        _paths.icon_cache_dir,
        _paths.thumbnails_dir,
        _paths.office_cache_dir,
        _paths.lut_previews_dir,
        _paths.updates_download_dir,
        _paths.performance_dir,
        _paths.probes_dir,
        _paths.office_temp_dir,
    ):
        getter()


# ── 布局标记 ─────────────────────────────────────────────────────────


def _read_layout_marker() -> Optional[Dict[str, Any]]:
    marker = read_json(
        _paths.layout_version_file(),
        default=None,
        use_backup=False,
        quarantine=False,
    )
    return marker if isinstance(marker, dict) else None


def _write_layout_marker(complete: bool, errors: Sequence[str]) -> None:
    payload = {
        "version": LAYOUT_VERSION,
        "complete": bool(complete),
        "migrated_at": time.time(),
        "errors": list(errors)[:_MAX_MIGRATION_ERRORS],
    }
    try:
        write_json_atomic(
            _paths.layout_version_file(),
            payload,
            indent=2,
            backup=False,
        )
    except OSError as exc:
        _log_warning(f"[storage] 写入布局标记失败: {exc}")


# ── 迁移 ─────────────────────────────────────────────────────────────


def _legacy_roots() -> List[Path]:
    """按优先级返回可能包含旧布局的根目录（去重）。"""
    roots: List[Path] = [_paths.app_data_root()]
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        roots.extend([exe_dir / "_internal" / "data", exe_dir / "data"])
    else:
        roots.append(_paths.repo_root() / "data")
    roots.append(_paths.package_dir() / "data")

    result: List[Path] = []
    seen: set = set()
    for root in roots:
        key = _norm(root)
        if key not in seen:
            seen.add(key)
            result.append(root)
    return result


def _find_file(name: str, roots: Sequence[Path]) -> Optional[Path]:
    for root in roots:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _find_dir(name: str, roots: Sequence[Path]) -> Optional[Path]:
    for root in roots:
        candidate = root / name
        if candidate.is_dir():
            return candidate
    return None


def _remove_source(source: Path, data_root: Path) -> None:
    """只删除数据根内的旧文件；安装目录/仓库内的历史文件保持原样。"""
    if not _is_within(source, data_root):
        return
    try:
        if source.is_file():
            source.unlink()
        elif source.is_dir():
            shutil.rmtree(source)
    except OSError:
        pass


def _migrate_file(
    source: Path,
    target: Path,
    *,
    data_root: Path,
    prefer_newer: bool = False,
    moved: List[str],
    errors: List[str],
) -> bool:
    """把单个文件迁移到目标位置；目标已存在时按需保留较新版本。"""
    try:
        if _norm(source) == _norm(target):
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if not prefer_newer:
                return False
            try:
                source_mtime = source.stat().st_mtime
                target_mtime = target.stat().st_mtime
            except OSError:
                return False
            if source_mtime <= target_mtime + 1.0:
                return False
            try:
                shutil.copy2(str(target), str(target) + ".bak")
            except OSError:
                pass
        shutil.copy2(str(source), str(target))
        try:
            if source.stat().st_size != target.stat().st_size:
                errors.append(f"大小校验失败: {source} -> {target}")
                return False
        except OSError as exc:
            errors.append(f"无法校验迁移结果: {source} -> {target}: {exc}")
            return False
        _remove_source(source, data_root)
        moved.append(f"{source} -> {target}")
        return True
    except OSError as exc:
        errors.append(f"迁移文件失败: {source} -> {target}: {exc}")
        return False


def _migrate_dir(
    source: Path,
    target: Path,
    *,
    data_root: Path,
    moved: List[str],
    errors: List[str],
) -> Optional[Tuple[Path, Path]]:
    """迁移目录并返回 ``(旧目录, 新目录)``；失败返回 None。

    目标已存在时做合并复制，确保两边的文件都不丢；合并成功后删除源目录。
    """
    if not source.is_dir():
        return None
    if _norm(source) == _norm(target):
        return None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.copytree(str(source), str(target), dirs_exist_ok=True)
        else:
            try:
                shutil.move(str(source), str(target))
            except OSError:
                shutil.copytree(str(source), str(target), dirs_exist_ok=True)
                _remove_source(source, data_root)
        _remove_source(source, data_root)
        moved.append(f"{source} -> {target}")
        return source, target
    except OSError as exc:
        errors.append(f"迁移目录失败: {source} -> {target}: {exc}")
        return None


def _migrate_cache_dir(
    source: Path,
    target: Path,
    *,
    data_root: Path,
    moved: List[str],
    errors: List[str],
) -> Optional[Tuple[Path, Path]]:
    """缓存目录可以整体移动；目标已存在时逐项合并，交给清理策略兜底。

    Returns:
        Optional[Tuple[Path, Path]]: 成功迁移时的 ``(旧目录, 新目录)``；
        无需迁移时返回 None。
    """
    if not source.is_dir() or _norm(source) == _norm(target):
        return None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            # 目标目录已在布局初始化时创建（通常为空）：逐项移动，不覆盖同名项。
            for entry in list(source.iterdir()):
                destination = target / entry.name
                if destination.exists():
                    continue
                try:
                    shutil.move(str(entry), str(destination))
                except OSError:
                    if entry.is_dir():
                        shutil.copytree(str(entry), str(destination), dirs_exist_ok=True)
                    else:
                        shutil.copy2(str(entry), str(destination))
                    _remove_source(entry, data_root)
        else:
            try:
                shutil.move(str(source), str(target))
            except OSError:
                shutil.copytree(str(source), str(target), dirs_exist_ok=True)
                _remove_source(source, data_root)
        _remove_source(source, data_root)
        moved.append(f"{source} -> {target}")
        return source, target
    except OSError as exc:
        errors.append(f"迁移缓存失败: {source} -> {target}: {exc}")
        return None


def _rewrite_tree(value: Any, mappings: Sequence[Tuple[Path, Path]]) -> Any:
    """递归改写结构内所有落在旧目录下的字符串路径。"""
    if isinstance(value, dict):
        return {key: _rewrite_tree(item, mappings) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_tree(item, mappings) for item in value]
    if isinstance(value, str):
        result = value
        for old_dir, new_dir in mappings:
            result = _rewrite_under(result, old_dir, new_dir)
        return result
    return value


def _rewrite_settings_paths(mappings: Sequence[Tuple[Path, Path]], errors: List[str]) -> None:
    """迁移后修正 settings.json 内保存的绝对路径（LUT/背景等）。"""
    settings_path = _paths.settings_file()
    data = read_json(settings_path, default=None, use_backup=True, quarantine=False)
    if not isinstance(data, dict):
        return
    rewritten = _rewrite_tree(data, mappings)
    if rewritten == data:
        return
    try:
        write_json_atomic(settings_path, rewritten, indent=4, backup=True)
    except OSError as exc:
        errors.append(f"改写设置内路径失败: {exc}")


def _rewrite_pending_update(
    download_moves: Sequence[Tuple[Path, Path]],
    errors: List[str],
) -> None:
    """迁移下载目录后修正待安装更新标记；安装包失效则清理标记。"""
    path = _paths.pending_update_file()
    data = read_json(path, default=None, use_backup=False, quarantine=False)
    if not isinstance(data, dict):
        return
    installer = data.get("installer_path")
    if isinstance(installer, str) and installer:
        for old_dir, new_dir in download_moves:
            installer = _rewrite_under(installer, old_dir, new_dir)
        data["installer_path"] = installer
        if not Path(installer).is_file():
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return
    try:
        write_json_atomic(path, data, indent=2, backup=False)
    except OSError as exc:
        errors.append(f"改写待安装更新标记失败: {exc}")


def _write_migration_report(report: Dict[str, Any]) -> None:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    target = _paths.diagnostics_dir() / f"migration-{timestamp}.json"
    try:
        write_json_atomic(target, report, indent=2, backup=False)
    except OSError:
        pass


def migrate_layout() -> Dict[str, Any]:
    """执行一次 v1 平铺布局 → v2 分类布局迁移。

    Returns:
        Dict[str, Any]: 迁移摘要（``moved`` / ``errors`` / ``complete``）。
    """
    data_root = _paths.app_data_root()
    roots = _legacy_roots()
    moved: List[str] = []
    errors: List[str] = []
    mappings: List[Tuple[Path, Path]] = []
    download_moves: List[Tuple[Path, Path]] = []

    # 1) 配置文件（优先保留较新版本）。
    config_files = (
        ("settings_v2.json", _paths.settings_file()),
        ("ai_accounts.json", _paths.ai_accounts_file()),
        ("favorites.json", _paths.favorites_file()),
    )
    for name, target in config_files:
        source = _find_file(name, roots)
        if source is not None:
            _migrate_file(
                source,
                target,
                data_root=data_root,
                prefer_newer=True,
                moved=moved,
                errors=errors,
            )

    # 2) 状态文件（目标已存在时保留目标）。
    state_files = (
        ("last_path.json", _paths.last_path_file()),
        ("staging_pool_backup.json", _paths.staging_pool_file()),
        ("check_state.json", _paths.update_check_file()),
        ("pending_update.json", _paths.pending_update_file()),
        ("runtime_instance.json", _paths.runtime_instance_file()),
        ("staging_pool.json", _paths.staging_pool_file()),
        ("update_check.json", _paths.update_check_file()),
    )
    for name, target in state_files:
        source = _find_file(name, roots)
        if source is not None:
            _migrate_file(
                source,
                target,
                data_root=data_root,
                prefer_newer=False,
                moved=moved,
                errors=errors,
            )

    # 3) 用户资源。
    for name, target in (
        ("backgrounds", _paths.backgrounds_dir()),
        ("luts", _paths.luts_dir()),
    ):
        for root in roots:
            source = root / name
            pair = _migrate_dir(
                source,
                target,
                data_root=data_root,
                moved=moved,
                errors=errors,
            )
            if pair is not None:
                mappings.append(pair)

    # 4) 缓存（整体移动，失败时保留旧目录）。
    for name, target in (
        ("lut_previews", _paths.lut_previews_dir()),
        ("thumbnails", _paths.thumbnails_dir()),
        ("office_cache", _paths.office_cache_dir()),
        ("performance", _paths.performance_dir()),
    ):
        for root in roots:
            pair = _migrate_cache_dir(
                root / name,
                target,
                data_root=data_root,
                moved=moved,
                errors=errors,
            )
            if pair is not None:
                mappings.append(pair)

    # 5) 缓存文件。
    file_info_source = _find_file("file_info_cache.json", roots)
    if file_info_source is not None:
        _migrate_file(
            file_info_source,
            _paths.file_info_cache_file(),
            data_root=data_root,
            prefer_newer=False,
            moved=moved,
            errors=errors,
        )

    # 6) 下载目录：先迁移，再修正 pending_update。
    for root in roots:
        source = root / "download"
        pair = _migrate_dir(
            source,
            _paths.updates_download_dir(),
            data_root=data_root,
            moved=moved,
            errors=errors,
        )
        if pair is not None:
            download_moves.append(pair)

    # 7) 修正设置和待安装更新中的绝对路径。
    _rewrite_settings_paths(mappings, errors)
    _rewrite_pending_update(download_moves, errors)

    report = {
        "version": LAYOUT_VERSION,
        "started_at": time.time(),
        "moved": moved,
        "errors": errors[:_MAX_MIGRATION_ERRORS],
        "complete": not errors,
    }
    _write_migration_report(report)
    _write_layout_marker(complete=not errors, errors=errors)
    if errors:
        _log_warning(
            f"[storage] 布局迁移完成但存在 {len(errors)} 个问题；旧文件已保留，下次启动重试"
        )
    return report


def ensure_layout(force: bool = False) -> Dict[str, Any]:
    """确保 v2 布局存在；首次调用时执行迁移。

    Args:
        force: 忽略进程内缓存，重新检查布局（测试/诊断用）。

    Returns:
        Dict[str, Any]: 迁移摘要或就绪状态。
    """
    global _READY
    with _LOCK:
        if _READY and not force:
            return {"version": LAYOUT_VERSION, "ready": True, "migrated": False}

        _ensure_layout_dirs()
        marker = _read_layout_marker()
        marker_version = 0
        if isinstance(marker, dict):
            try:
                marker_version = int(marker.get("version", 0) or 0)
            except (TypeError, ValueError):
                marker_version = 0
        if (
            marker is not None
            and marker_version >= LAYOUT_VERSION
            and bool(marker.get("complete", False))
        ):
            _READY = True
            return {"version": LAYOUT_VERSION, "ready": True, "migrated": False}

        report = migrate_layout()
        _READY = True
        return report


def reset_layout_state() -> None:
    """重置进程内布局缓存（测试用）。"""
    global _READY
    with _LOCK:
        _READY = False


# ── 清理 ─────────────────────────────────────────────────────────────


def _cleanup_office_temp(max_age_hours: float = 24.0) -> int:
    """删除 ``temp/office`` 下最后修改超过 *max_age_hours* 的条目。"""
    root = _paths.office_temp_dir()
    cutoff = time.time() - max_age_hours * 3600.0
    removed = 0
    try:
        entries = list(root.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if _dir_latest_mtime(entry) < cutoff:
            if _safe_unlink(entry):
                removed += 1
    return removed


def _cleanup_updates(max_age_days: float = 14.0) -> int:
    """删除过期的安装包下载，保留 pending_update 引用的文件。"""
    root = _paths.updates_download_dir()
    cutoff = time.time() - max_age_days * 86400.0
    pending = read_json(
        _paths.pending_update_file(),
        default=None,
        use_backup=False,
        quarantine=False,
    )
    keep_path = ""
    if isinstance(pending, dict):
        raw = pending.get("installer_path")
        if isinstance(raw, str):
            keep_path = _norm(raw)
    removed = 0
    try:
        entries = list(root.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if not entry.is_file():
            continue
        if keep_path and _norm(entry) == keep_path:
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    return removed


def _cleanup_diagnostics(max_age_days: float = 30.0, max_files: int = 20) -> int:
    """清理过期性能快照和探针产物。"""
    removed = 0
    perf_dir = _paths.performance_dir()
    cutoff = time.time() - max_age_days * 86400.0

    def _mtime(item: Path) -> float:
        try:
            return item.stat().st_mtime
        except OSError:
            return 0.0

    try:
        files = sorted(
            (item for item in perf_dir.iterdir() if item.is_file()),
            key=_mtime,
            reverse=True,
        )
    except OSError:
        files = []
    for index, item in enumerate(files):
        try:
            if index >= max_files or _mtime(item) < cutoff:
                item.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue

    probes = _paths.probes_dir()
    for root, _dirs, names in os.walk(probes):
        for name in names:
            item = Path(root) / name
            try:
                if _mtime(item) < cutoff:
                    item.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
    return removed


def _cleanup_lut_previews(max_age_days: float = 90.0) -> int:
    """删除超龄或对应 LUT 已不存在的预览图。"""
    preview_dir = _paths.lut_previews_dir()
    lut_dir = _paths.luts_dir()
    cutoff = time.time() - max_age_days * 86400.0
    try:
        lut_ids = {
            name.split("_", 1)[0]
            for name in (item.name for item in lut_dir.iterdir())
            if name.lower().endswith(".cube")
        }
    except OSError:
        lut_ids = set()
    removed = 0
    try:
        entries = list(preview_dir.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if not entry.is_file() or not entry.name.lower().endswith("_preview.png"):
            continue
        lut_id = entry.name[: -len("_preview.png")]
        try:
            too_old = entry.stat().st_mtime < cutoff
        except OSError:
            continue
        if lut_id not in lut_ids or too_old:
            entry.unlink(missing_ok=True)
            removed += 1
    return removed


def _cleanup_file_info_cache(max_bytes: int = 8 * 1024 * 1024) -> int:
    """文件信息缓存超过大小上限时裁剪到最近 400 条。"""
    path = _paths.file_info_cache_file()
    try:
        if not path.is_file() or path.stat().st_size <= max_bytes:
            return 0
    except OSError:
        return 0
    data = read_json(path, default=None, use_backup=False, quarantine=False)
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return 0
    files = data["files"]
    if len(files) <= 400:
        return 0
    for key in list(files)[: len(files) - 400]:
        files.pop(key, None)
    try:
        write_json_atomic(path, data, indent=2, backup=False)
        return 1
    except OSError:
        return 0


def cleanup_storage(
    categories: Optional[Iterable[str]] = None,
    *,
    active_log_path: Optional[str] = None,
) -> Dict[str, int]:
    """按类别清理可再生文件，返回各类别删除数量。

    Args:
        categories: 要清理的类别；``None`` 表示全部。支持
            ``logs`` / ``temp_office`` / ``updates`` / ``diagnostics`` /
            ``lut_previews`` / ``file_info``。
        active_log_path: 当前活动日志路径，日志清理时永不删除/压缩它。

    Returns:
        Dict[str, int]: 类别 → 删除/处理数量。
    """
    selected = set(categories) if categories is not None else {
        "logs",
        "temp_office",
        "updates",
        "diagnostics",
        "lut_previews",
        "file_info",
    }
    result: Dict[str, int] = {}
    if "logs" in selected:
        try:
            from sopeek.utils.log_retention import maintain_logs

            report = maintain_logs(active_log_path=active_log_path)
            result["logs"] = int(report.get("deleted", 0))
        except Exception as exc:
            _log_debug(f"[storage] 日志清理失败: {exc}")
            result["logs"] = 0
    if "temp_office" in selected:
        result["temp_office"] = _cleanup_office_temp()
    if "updates" in selected:
        result["updates"] = _cleanup_updates()
    if "diagnostics" in selected:
        result["diagnostics"] = _cleanup_diagnostics()
    if "lut_previews" in selected:
        result["lut_previews"] = _cleanup_lut_previews()
    if "file_info" in selected:
        result["file_info"] = _cleanup_file_info_cache()
    return result


__all__ = [
    "LAYOUT_VERSION",
    "LAYOUT_MARKER_NAME",
    "ensure_layout",
    "migrate_layout",
    "reset_layout_state",
    "cleanup_storage",
]
