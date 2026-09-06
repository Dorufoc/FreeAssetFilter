"""设置暂存缓存 — 新版设置窗口的临时缓存隔离层。

本模块是设置窗口与应用主状态之间的唯一隔离边界：

- 所有用户修改（文本输入、选项切换、滑块调整等）首先写入暂存缓存，
  未点击「应用」/「确定」前不得触碰 :class:`SettingsManagerV2`、
  :class:`ThemeManager`（``tm``）或主窗口任何运行时状态；
- 点击「应用」/「确定」时由 :class:`SettingsLayout` 统一提交事务，
  点击「取消」/关闭窗口未提交时自动丢弃；
- 纯数据模块，不依赖 Qt、不导入 ``tm`` 与主窗口，命名空间独立，
  可在无 ``QApplication`` 环境下单测。

命名空间：``settings_staging``，见 :data:`STAGING_NAMESPACE`。
"""

from __future__ import annotations

import copy
import threading
import time
from typing import Any, Dict, List, Optional


STAGING_NAMESPACE: str = "settings_staging"

_ALLOWED_BG_MODES: tuple[str, ...] = ("mica", "image", "minimalist")

_DEBUG_ENABLED: bool = False


def set_debug_enabled(enabled: bool) -> None:
    """开启/关闭暂存缓存的调试日志输出。

    Args:
        enabled: True 开启后 ``set``/``commit``/``discard`` 将打印耗时摘要。
    """
    global _DEBUG_ENABLED
    _DEBUG_ENABLED = bool(enabled)


def is_debug_enabled() -> bool:
    """返回当前调试开关状态。

    Returns:
        bool: 调试开关是否开启。
    """
    return _DEBUG_ENABLED


def _split_key(key_path: str) -> List[str]:
    """切分点号键路径并校验非空。

    Args:
        key_path: 点号路径，如 ``"appearance.theme"``。

    Returns:
        List[str]: 切分后的键列表。

    Raises:
        ValueError: 路径为空或含空片段时抛出。
    """
    if not isinstance(key_path, str) or not key_path.strip():
        raise ValueError("key_path 必须是非空字符串")
    parts = key_path.split(".")
    if any(not p for p in parts):
        raise ValueError(f"非法键路径: {key_path!r}")
    return parts


def _get_by_path(data: Dict[str, Any], key_path: str, default: Any = None) -> Any:
    """按点号路径读取嵌套字典值。

    Args:
        data: 源字典。
        key_path: 点号路径。
        default: 路径缺失时的返回值。

    Returns:
        Any: 路径对应的值，缺失时返回 *default*。
    """
    try:
        node: Any = data
        for part in _split_key(key_path):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node
    except ValueError:
        return default


def _set_by_path(data: Dict[str, Any], key_path: str, value: Any) -> bool:
    """按点号路径写入嵌套字典值。

    Args:
        data: 目标字典（原地修改）。
        key_path: 点号路径。
        value: 待写入的值。

    Returns:
        bool: 值有变化返回 True，无变化返回 False。
    """
    parts = _split_key(key_path)
    node = data
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    leaf = parts[-1]
    if leaf in node and node[leaf] == value:
        return False
    node[leaf] = copy.deepcopy(value)
    return True


class SettingsStagingCache:
    """设置暂存缓存：与应用主状态严格隔离的临时数据结构。

    生命周期：``begin()`` 快照 V2 → 多次 ``set()`` 暂存 → ``commit_snapshot()``
    产出待提交快照（由调用方事务性落盘）→ ``mark_committed()`` 更新基线，或
    ``discard()`` 丢弃回基线。关闭未提交时调用方必须调用 ``discard()``。
    """

    def __init__(self) -> None:
        """初始化空缓存（未快照，需先调用 :meth:`begin`）。"""
        self._lock = threading.Lock()
        self._baseline: Dict[str, Any] = {}
        self._staged: Dict[str, Any] = {}
        self._dirty_keys: set[str] = set()
        self._begun: bool = False
        self._last_set_ms: float = 0.0
        self._last_commit_ms: float = 0.0
        self._commit_count: int = 0

    # ── 生命周期 ──────────────────────────────────────────────

    def begin(self, snapshot: Dict[str, Any]) -> None:
        """以 V2 当前全量快照开启一轮暂存。

        Args:
            snapshot: 调用方从 ``SettingsManagerV2().load()`` 深拷贝的快照。
        """
        staged = copy.deepcopy(snapshot)
        with self._lock:
            self._baseline = copy.deepcopy(snapshot)
            self._staged = staged
            self._dirty_keys = set()
            self._begun = True
        if _DEBUG_ENABLED:
            print(f"[{STAGING_NAMESPACE}] begin keys={len(self._baseline)}")

    def is_active(self) -> bool:
        """返回缓存是否已 ``begin``（可接受读写）。

        Returns:
            bool: 已开启返回 True。
        """
        with self._lock:
            return self._begun

    # ── 读写 ──────────────────────────────────────────────────

    def get(self, key_path: str, default: Any = None) -> Any:
        """读取暂存区的值（控件展示的唯一数据源）。

        Args:
            key_path: 点号路径。
            default: 缺失时的默认值。

        Returns:
            Any: 暂存值或 *default*。
        """
        with self._lock:
            return copy.deepcopy(_get_by_path(self._staged, key_path, default))

    def set(self, key_path: str, value: Any) -> bool:
        """写入暂存区（所有控件修改的唯一入口，实时更新，<200ms）。

        Args:
            key_path: 点号路径。
            value: 待暂存的值。

        Returns:
            bool: 值有变化返回 True。
        """
        t0 = time.perf_counter()
        with self._lock:
            changed = _set_by_path(self._staged, key_path, value)
            if changed:
                self._dirty_keys.add(key_path)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self._last_set_ms = elapsed_ms
        if _DEBUG_ENABLED:
            print(f"[{STAGING_NAMESPACE}] set {key_path} changed={changed} {elapsed_ms:.2f}ms")
        return changed

    def snapshot_staged(self) -> Dict[str, Any]:
        """返回暂存区的深拷贝快照（供提交事务使用）。

        Returns:
            Dict[str, Any]: 暂存区全量深拷贝。
        """
        with self._lock:
            return copy.deepcopy(self._staged)

    def is_dirty(self) -> bool:
        """返回是否有未提交的暂存修改。

        Returns:
            bool: 脏返回 True。
        """
        with self._lock:
            return bool(self._dirty_keys)

    def dirty_keys(self) -> List[str]:
        """返回脏键路径列表（调试用）。

        Returns:
            List[str]: 脏键排序列表。
        """
        with self._lock:
            return sorted(self._dirty_keys)

    # ── 提交 / 丢弃 / 重置 ─────────────────────────────────────

    def commit_snapshot(self) -> Dict[str, Any]:
        """产出待提交的暂存快照并记录耗时（不直接写盘，保持事务边界清晰）。

        Returns:
            Dict[str, Any]: 暂存区深拷贝，供调用方事务性写入 V2。
        """
        t0 = time.perf_counter()
        with self._lock:
            snapshot = copy.deepcopy(self._staged)
        self._last_commit_ms = (time.perf_counter() - t0) * 1000.0
        self._commit_count += 1
        return snapshot

    def mark_committed(self, snapshot: Optional[Dict[str, Any]] = None) -> None:
        """提交成功后将基线前移到已提交快照并清空脏标记。

        Args:
            snapshot: 已落盘的快照，为空时取当前暂存区。
        """
        with self._lock:
            base = copy.deepcopy(snapshot) if snapshot is not None else copy.deepcopy(self._staged)
            self._baseline = base
            self._staged = copy.deepcopy(base)
            self._dirty_keys = set()

    def discard(self) -> None:
        """丢弃未提交的暂存，回滚到基线（取消/关闭未提交时调用）。"""
        with self._lock:
            self._staged = copy.deepcopy(self._baseline)
            self._dirty_keys = set()
        if _DEBUG_ENABLED:
            print(f"[{STAGING_NAMESPACE}] discard -> baseline restored")

    def reset_to_defaults(self, defaults: Dict[str, Any]) -> None:
        """将暂存区重置为默认值（重置按钮用，不直接落盘，需提交才生效）。

        Args:
            defaults: 默认设置全量字典（如 ``DEFAULT_SETTINGS_V2`` 深拷贝）。
        """
        staged = copy.deepcopy(defaults)
        with self._lock:
            self._staged = staged
            # 与基线逐叶比对，记录脏键，便于提交时仅写差异
            self._dirty_keys = set()
            self._collect_dirty(self._baseline, self._staged, "")
        if _DEBUG_ENABLED:
            print(f"[{STAGING_NAMESPACE}] reset_to_defaults dirty={len(self._dirty_keys)}")

    def _collect_dirty(self, base: Any, staged: Any, prefix: str) -> None:
        """递归比对基线与暂存，收集差异叶键。"""
        if isinstance(base, dict) and isinstance(staged, dict):
            for key in set(base) | set(staged):
                child_prefix = f"{prefix}.{key}" if prefix else key
                if key not in base or key not in staged:
                    self._dirty_keys.add(child_prefix)
                else:
                    self._collect_dirty(base[key], staged[key], child_prefix)
        elif base != staged:
            self._dirty_keys.add(prefix)

    # ── 调试工具 ──────────────────────────────────────────────

    def dump(self) -> Dict[str, Any]:
        """导出缓存状态快照（调试工具，不暴露内部引用）。

        Returns:
            Dict[str, Any]: 含命名空间、基线/暂存深拷贝、脏键、耗时统计。
        """
        with self._lock:
            return {
                "namespace": STAGING_NAMESPACE,
                "active": self._begun,
                "baseline": copy.deepcopy(self._baseline),
                "staged": copy.deepcopy(self._staged),
                "dirty_keys": sorted(self._dirty_keys),
                "last_set_ms": self._last_set_ms,
                "last_commit_ms": self._last_commit_ms,
                "commit_count": self._commit_count,
            }

    def debug_info(self) -> Dict[str, Any]:
        """返回轻量调试摘要（键数量、脏键、耗时，不含全量数据）。

        Returns:
            Dict[str, Any]: 调试摘要字典。
        """
        with self._lock:
            return {
                "namespace": STAGING_NAMESPACE,
                "active": self._begun,
                "dirty": sorted(self._dirty_keys),
                "dirty_count": len(self._dirty_keys),
                "last_set_ms": round(self._last_set_ms, 3),
                "last_commit_ms": round(self._last_commit_ms, 3),
                "commit_count": self._commit_count,
            }
