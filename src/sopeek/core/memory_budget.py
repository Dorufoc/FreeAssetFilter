#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内存/显存预算器（P7.2）。

按「可用物理内存」自动选档，把原先散落在各模块的硬编码缓存上限收敛到
一处；档位可通过 ``SPK_MEMORY_TIER=low|balanced|high`` 强制覆盖。

设计原则
--------
* **默认 balanced**：本机 31.47GB 落在 12–32GB 区间，保持既有上限不变
  （改造前后行为一致，避免"优化即回归"）；
* **只降不升**：``low`` 档同步下调 QPixmapCache / Rust 缩略图 / 帧缓存 /
  Mica 层数；``high`` 档上调但不超过既有硬编码的 2 倍；
* **显存靠纹理上限**：``fluid_texture_max_px`` 是唯一能真正约束显存的
  旋钮（Qt 的 QPixmap 是 CPU raster，删 QPixmapCache 不会降显存）；
* **失败静默**：任何子模块导入/赋值失败只记 debug，不影响启动。

与设置页的关系
--------------
本模块**不是设置项**（不触碰 ``SettingsStagingCache`` 铁律）：档位由硬件
探测或环境变量决定；若将来暴露 UI，必须走设置暂存的四处覆盖。
"""

from __future__ import annotations

import os
import sys
import threading
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional

from sopeek.core.native import memory_probe
from sopeek.utils.app_logger import debug, warning

#: 1 GiB。
_GIB: int = 1024 * 1024 * 1024
#: 1 MiB。
_MIB: int = 1024 * 1024


@dataclass(frozen=True)
class BudgetTier:
    """一档缓存预算（字节 / 条目 / 像素）。"""

    name: str
    pixmap_cache_kb: int
    rust_thumb_cache_bytes: int
    frame_cache_bytes: int
    frame_cache_groups: int
    frame_cache_bytes_per_group: int
    icon_cache_entries: int
    icon_scale_cache_entries: int
    file_info_entries: int
    path_exists_entries: int
    svg_cache_entries: int
    mica_layers: int
    mica_layer_long_edge: int
    fluid_texture_max_px: int
    rss_soft_bytes: int
    rss_hard_bytes: int


#: 三档预算。``balanced`` 全部等于改造前的硬编码值。
TIERS: Dict[str, BudgetTier] = {
    "low": BudgetTier(
        name="low",
        pixmap_cache_kb=24 * 1024,
        rust_thumb_cache_bytes=96 * _MIB,
        frame_cache_bytes=128 * _MIB,
        frame_cache_groups=64,
        frame_cache_bytes_per_group=24 * _MIB,
        icon_cache_entries=128,
        icon_scale_cache_entries=128,
        file_info_entries=400,
        path_exists_entries=4096,
        svg_cache_entries=128,
        mica_layers=1,
        mica_layer_long_edge=4096,
        fluid_texture_max_px=1920,
        rss_soft_bytes=int(1.2 * _GIB),
        rss_hard_bytes=int(1.8 * _GIB),
    ),
    "balanced": BudgetTier(
        name="balanced",
        pixmap_cache_kb=50 * 1024,
        rust_thumb_cache_bytes=200 * _MIB,
        frame_cache_bytes=256 * _MIB,
        frame_cache_groups=128,
        frame_cache_bytes_per_group=32 * _MIB,
        icon_cache_entries=256,
        icon_scale_cache_entries=256,
        file_info_entries=800,
        path_exists_entries=8192,
        svg_cache_entries=256,
        mica_layers=2,
        mica_layer_long_edge=8192,
        fluid_texture_max_px=2560,
        rss_soft_bytes=int(1.8 * _GIB),
        rss_hard_bytes=int(2.6 * _GIB),
    ),
    "high": BudgetTier(
        name="high",
        pixmap_cache_kb=96 * 1024,
        rust_thumb_cache_bytes=320 * _MIB,
        frame_cache_bytes=384 * _MIB,
        frame_cache_groups=192,
        frame_cache_bytes_per_group=40 * _MIB,
        icon_cache_entries=384,
        icon_scale_cache_entries=384,
        file_info_entries=1200,
        path_exists_entries=16384,
        svg_cache_entries=384,
        mica_layers=2,
        mica_layer_long_edge=8192,
        fluid_texture_max_px=3840,
        rss_soft_bytes=int(2.6 * _GIB),
        rss_hard_bytes=int(3.6 * _GIB),
    ),
}


#: 被覆写过的模块/类常量原值（``reset_for_tests`` 回滚，避免跨用例污染）。
#: key = (id(target), attr) → (target, attr, original_value)。
_PATCHED_ORIGINALS: "dict[tuple[int, str], tuple[Any, str, Any]]" = {}


def _patch_constant(target: Any, attr: str, value: Any) -> None:
    """设置模块/类常量，并记住原值（仅首次）。

    Args:
        target: 模块或类对象。
        attr: 常量名。
        value: 当前档位下的目标值。
    """
    key = (id(target), attr)
    if key not in _PATCHED_ORIGINALS:
        _PATCHED_ORIGINALS[key] = (target, attr, getattr(target, attr, None))
    setattr(target, attr, value)


class MemoryBudget:
    """内存/显存预算单例（线程安全）。"""

    _instance: Optional["MemoryBudget"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "MemoryBudget":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    obj = super().__new__(cls)
                    obj._tier = TIERS["balanced"]
                    obj._applied = False
                    obj._ledger: Dict[str, Dict[str, Any]] = {}
                    obj._pressure_callbacks: List[Callable[[str, dict], None]] = []
                    obj._last_sample: Dict[str, Any] = {}
                    cls._instance = obj
        return cls._instance

    # ── 档位 ──────────────────────────────────────────────────────────────
    @property
    def tier(self) -> BudgetTier:
        """当前档位。"""
        return self._tier

    def detect_tier_name(self) -> str:
        """按物理内存与是否独显探测档位名。

        Returns:
            str: ``low`` / ``balanced`` / ``high``。
        """
        override = os.environ.get("SPK_MEMORY_TIER", "").strip().lower()
        if override in TIERS:
            return override
        system = memory_probe.read_system_memory()
        total = system.get("total_phys_bytes")
        if total is None:
            return "balanced"
        if total < 12 * _GIB:
            return "low"
        if total > 32 * _GIB:
            return "high"
        return "balanced"

    def set_tier(self, name: str) -> None:
        """强制切档（QA/压测）。

        Args:
            name: ``low`` / ``balanced`` / ``high``。

        Raises:
            ValueError: 未知档位名。
        """
        if name not in TIERS:
            raise ValueError(f"unknown memory tier: {name!r}")
        self._tier = TIERS[name]

    # ── 应用 ──────────────────────────────────────────────────────────────
    def apply(self, app: Any = None) -> Dict[str, Any]:
        """把当前档位推到各缓存（幂等）。

        只对**已导入**的重模块赋值；未导入的模块在自身构造时读取
        :meth:`tier`（避免启动期强拉 PIL/psd-tools 等）。

        Args:
            app: 可选 QApplication（当前未使用，保留签名）。

        Returns:
            dict: 应用结果（``applied`` 为成功项列表）。
        """
        del app
        tier = self._tier
        applied: List[str] = []
        #: 本次未应用、等模块导入后由延迟 re-apply 补齐的项。
        pending: List[str] = []

        # 1) QPixmapCache（Qt 已在用，必定可设）
        try:
            from PySide6.QtGui import QPixmapCache

            QPixmapCache.setCacheLimit(tier.pixmap_cache_kb)
            applied.append("qpixmap_cache")
        except Exception as exc:  # noqa: BLE001
            debug(f"[memory_budget] QPixmapCache 应用失败: {exc}")

        # 2) ThumbnailManager（类级常量 + 已存在实例）
        if "sopeek.core.managers.thumbnail_manager" in sys.modules:
            try:
                from sopeek.core.managers.thumbnail_manager import (
                    ThumbnailManager,
                )

                # 原值记录在 _PATCHED_ORIGINALS，reset_for_tests 回滚（避免跨用例污染）。
                _patch_constant(
                    ThumbnailManager, "MAX_FRAME_CACHE_BYTES", tier.frame_cache_bytes
                )
                _patch_constant(
                    ThumbnailManager, "MAX_FRAME_CACHE_GROUPS", tier.frame_cache_groups
                )
                _patch_constant(
                    ThumbnailManager,
                    "MAX_FRAME_CACHE_BYTES_PER_GROUP",
                    tier.frame_cache_bytes_per_group,
                )
                _patch_constant(
                    ThumbnailManager, "MAX_SVG_CACHE_ENTRIES", tier.svg_cache_entries
                )
                _patch_constant(
                    ThumbnailManager,
                    "PATH_EXISTS_CACHE_MAX_ENTRIES",
                    tier.path_exists_entries,
                )
                instance = getattr(ThumbnailManager, "_instance", None)
                if instance is not None:
                    instance._native_cache_limit = tier.rust_thumb_cache_bytes
                    if getattr(instance, "_rust_bridge", None) is not None:
                        try:
                            instance._rust_bridge.set_cache_limit(
                                tier.rust_thumb_cache_bytes
                            )
                        except Exception:  # noqa: BLE001
                            pass
                applied.append("thumbnail_manager")
            except Exception as exc:  # noqa: BLE001
                debug(f"[memory_budget] ThumbnailManager 应用失败: {exc}")

        # 3) 图标缓存（类级常量）
        # 启动期**不得**为了打补丁而强导入 file_icon_manager：该模块冷导入实测
        # 174–290ms（SVG 渲染 / 并行子模块），会把首次绘制拖慢。未导入时记为
        # pending —— FileIconManager 构造时会自行读档位，首次绘制后的延迟
        # re-apply 再兜一次。
        icon_module = sys.modules.get("sopeek.services.file_icon_manager")
        file_icon_manager = (
            getattr(icon_module, "FileIconManager", None)
            if icon_module is not None
            else None
        )
        if file_icon_manager is None:
            pending.append("file_icon_manager")
        else:
            try:
                _patch_constant(
                    file_icon_manager,
                    "_ICON_CACHE_MAX_ENTRIES",
                    tier.icon_cache_entries,
                )
                _patch_constant(
                    file_icon_manager,
                    "_SYSTEM_ICON_CACHE_MAX_ENTRIES",
                    tier.icon_cache_entries,
                )
                _patch_constant(
                    file_icon_manager,
                    "_SYSTEM_ICON_PLACEHOLDER_CACHE_MAX_ENTRIES",
                    tier.icon_cache_entries,
                )
                # P7.3：三套缓存共享家族预算（同 key 去重后总量不再 ×3）。
                _patch_constant(
                    file_icon_manager,
                    "_ICON_CACHE_FAMILY_BUDGET",
                    tier.icon_cache_entries,
                )
                applied.append("file_icon_manager")
            except Exception as exc:  # noqa: BLE001
                debug(f"[memory_budget] FileIconManager 应用失败: {exc}")

        # 4) 模块级常量（只在已导入时改）
        if "sopeek.ui.components.file_card_delegate" in sys.modules:
            try:
                import sopeek.ui.components.file_card_delegate as fcd

                _patch_constant(
                    fcd, "_ICON_SCALE_CACHE_CAP", tier.icon_scale_cache_entries
                )
                applied.append("file_card_delegate")
            except Exception as exc:  # noqa: BLE001
                debug(f"[memory_budget] file_card_delegate 应用失败: {exc}")

        if "sopeek.services.file_info_service" in sys.modules:
            try:
                import sopeek.services.file_info_service as fis

                _patch_constant(
                    fis, "_MAX_CACHE_ENTRIES", tier.file_info_entries
                )
                applied.append("file_info_service")
            except Exception as exc:  # noqa: BLE001
                debug(f"[memory_budget] file_info_service 应用失败: {exc}")

        if "sopeek.ui.mica.material" in sys.modules:
            try:
                import sopeek.ui.mica.material as material

                _patch_constant(material, "_LAYER_CACHE_MAX", tier.mica_layers)
                # P7.3：层长边上限也由档位驱动（low 4096 / balanced、high 8192）。
                # ``_layer_display_long`` 读的是 material 模块命名空间里的常量，
                # 因此需同时改两处（drag 与原模块）。
                _patch_constant(
                    material, "LAYER_DISPLAY_LONG_MAX", tier.mica_layer_long_edge
                )
                try:
                    import sopeek.ui.mica.drag as mica_drag

                    _patch_constant(
                        mica_drag, "LAYER_DISPLAY_LONG_MAX", tier.mica_layer_long_edge
                    )
                except Exception:  # noqa: BLE001 - drag 模块缺失时只改 material
                    pass
                applied.append("mica")
            except Exception as exc:  # noqa: BLE001
                debug(f"[memory_budget] Mica 应用失败: {exc}")

        self._applied = True
        debug(f"[memory_budget] tier={tier.name} applied={applied} pending={pending}")
        return {"tier": tier.name, "applied": applied, "pending": pending}

    # ── 采样 ──────────────────────────────────────────────────────────────
    def sample(self) -> Dict[str, Any]:
        """采样当前内存占用并与档位阈值比较。

        Returns:
            dict: ``{"process","system","gpu","tier","pressure"}``；
                ``pressure`` 为 ``None`` / ``"rss_soft"`` / ``"rss_hard"``。
        """
        snapshot = memory_probe.snapshot()
        rss = snapshot["process"].get("rss_bytes") or 0
        if rss >= self._tier.rss_hard_bytes:
            pressure = "rss_hard"
        elif rss >= self._tier.rss_soft_bytes:
            pressure = "rss_soft"
        else:
            pressure = None
        result = {
            "tier": self._tier.name,
            "pressure": pressure,
            "process": snapshot["process"],
            "system": snapshot["system"],
            "gpu": snapshot["gpu"],
            "thresholds": {
                "rss_soft_bytes": self._tier.rss_soft_bytes,
                "rss_hard_bytes": self._tier.rss_hard_bytes,
            },
        }
        self._last_sample = result
        if pressure is not None:
            self._emit_pressure(pressure, result)
        return result

    def on_pressure(self, callback: Callable[[str, dict], None]) -> None:
        """注册内存压力回调（同优先级顺序调用）。

        Args:
            callback: ``(level, sample)`` 回调。
        """
        self._pressure_callbacks.append(callback)

    def _emit_pressure(self, level: str, sample: Dict[str, Any]) -> None:
        """派发内存压力事件（回调异常隔离）。"""
        warning(f"[memory_budget] 内存压力: {level}")
        for callback in list(self._pressure_callbacks):
            try:
                callback(level, sample)
            except Exception:  # noqa: BLE001 - 回调失败不得影响主流程
                pass

    def release_caches(self) -> None:
        """释放可立即回收的缓存（压力兜底）。"""
        try:
            from PySide6.QtGui import QPixmapCache

            QPixmapCache.clear()
        except Exception:  # noqa: BLE001
            pass
        try:
            from sopeek.core.managers.thumbnail_manager import (
                get_thumbnail_manager,
            )

            manager = get_thumbnail_manager()
            manager.release_caches()
        except Exception:  # noqa: BLE001
            pass

    # ── 账本 ──────────────────────────────────────────────────────────────
    def register_cache(
        self, name: str, cap_bytes: Optional[int] = None, cap_entries: Optional[int] = None
    ) -> None:
        """登记一个可统计的缓存池（供 ``ledger`` 展示）。

        Args:
            name: 池名。
            cap_bytes: 字节上限。
            cap_entries: 条目上限。
        """
        self._ledger[name] = {
            "cap_bytes": cap_bytes,
            "cap_entries": cap_entries,
            "bytes": 0,
            "entries": 0,
        }

    def note(
        self,
        name: str,
        *,
        put_bytes: int = 0,
        evict_bytes: int = 0,
        entries_delta: int = 0,
    ) -> None:
        """更新账本（调用方在插入/淘汰时上报）。

        Args:
            name: 池名。
            put_bytes: 新增字节。
            evict_bytes: 淘汰字节。
            entries_delta: 条目变化。
        """
        entry = self._ledger.get(name)
        if entry is None:
            return
        entry["bytes"] = max(0, int(entry["bytes"]) + put_bytes - evict_bytes)
        entry["entries"] = max(0, int(entry["entries"]) + entries_delta)

    def ledger(self) -> Dict[str, Dict[str, Any]]:
        """返回账本副本。"""
        return {name: dict(values) for name, values in self._ledger.items()}

    def snapshot(self) -> Dict[str, Any]:
        """构造 ``perf_metrics`` 的 ``memory`` provider 段。

        Returns:
            dict: 档位、阈值、内存采样与账本摘要。
        """
        sample = self._last_sample or self.sample()
        return {
            "tier": self._tier.name,
            "tier_values": asdict(self._tier),
            "pressure": sample.get("pressure"),
            "process": sample.get("process"),
            "system": sample.get("system"),
            "gpu": sample.get("gpu"),
            "ledger": self.ledger(),
            "applied": self._applied,
        }


def get_memory_budget() -> MemoryBudget:
    """获取预算器单例。"""
    return MemoryBudget()


def reset_for_tests() -> None:
    """重置单例并回滚所有被覆写的常量（测试用）。

    P7.2/P7.3：``apply()`` 会改写多个模块/类常量（如 Mica 层长边）。若不
    回滚，前一个用例选的低档位会污染后续用例（例如拖垮
    ``test_layer_display_long_is_screen_1to1`` 的 1:1 不变量）。
    """
    with MemoryBudget._lock:
        MemoryBudget._instance = None
    for target, attr, original in list(_PATCHED_ORIGINALS.values()):
        try:
            if original is not None:
                setattr(target, attr, original)
        except Exception as exc:  # noqa: BLE001 - 回滚失败不得阻塞用例
            debug(f"[memory_budget] 回滚 {attr} 失败: {exc}")
    _PATCHED_ORIGINALS.clear()
