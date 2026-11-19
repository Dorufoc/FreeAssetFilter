# -*- coding: utf-8 -*-
"""主窗口「预览器根目录 Esc 交还焦点」回归。

背景（用户需求）：焦点在压缩包/文件夹预览器内、已退到根目录时再按 ``Esc``，
焦点应回到进入预览器之前的焦点区，且该区光标刷新到第一个卡片。

本文件锁定以下契约（与真实控件解耦，只用宿主替身验证判定逻辑）：

* ``_remember_zone_before_preview``：只记录 path/selector/pool/info，
  ``preview.*`` / ``app`` / ``settings`` / ``fullscreen`` 不覆盖记录；
* ``_on_preview_root_escape``：优先回记录区，其次 selector → pool → info；
  无法聚焦时返回 False；所有尝试都以 ``first=True`` 刷新首卡光标；
* 记录值非法（如误写成 ``preview``）时回落到 selector，避免回跳进预览器。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/test_main_window_preview_return.py -v
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import pytest

from sopeek.ui.main_window import MainWindow

pytestmark = pytest.mark.unit


class _ZoneReturnHost:
    """``_on_preview_root_escape`` 的最小宿主替身。"""

    _ZONE_REGIONS = MainWindow._ZONE_REGIONS

    def __init__(
        self,
        *,
        zone: str = "",
        focusable: Optional[Dict[str, bool]] = None,
    ) -> None:
        self._zone_before_preview = zone
        self._focusable = dict(focusable or {})
        self.calls: list[Tuple[str, bool]] = []

    def _focus_zone(self, name: str, *, first: bool = False) -> bool:
        self.calls.append((name, first))
        return bool(self._focusable.get(name, False))


class _RememberHost:
    """``_remember_zone_before_preview`` 的最小宿主替身。"""

    _ZONE_REGIONS = MainWindow._ZONE_REGIONS

    def __init__(self, zone: str = "") -> None:
        self._zone_before_preview = zone


# ── 记录进入预览器前的焦点区 ─────────────────────────────────────────


@pytest.mark.parametrize("region", ["path", "selector", "pool", "info"])
def test_remember_accepts_card_zones(region: str) -> None:
    """四个卡片区都作为回跳候选记录。"""
    host = _RememberHost()
    MainWindow._remember_zone_before_preview(host, region)
    assert host._zone_before_preview == region


@pytest.mark.parametrize(
    "region",
    ["preview.archive", "preview.folder", "preview.image", "app", "settings", "fullscreen"],
)
def test_remember_ignores_non_card_zones(region: str) -> None:
    """预览器自身 / 非卡片区不覆盖记录（保证记录的是「进入前」）。"""
    host = _RememberHost("selector")
    MainWindow._remember_zone_before_preview(host, region)
    assert host._zone_before_preview == "selector"


def test_remember_keeps_last_card_zone() -> None:
    """连续记录取最后一次卡片区（信息面板 → 储存池 → 预览器）。"""
    host = _RememberHost()
    MainWindow._remember_zone_before_preview(host, "info")
    MainWindow._remember_zone_before_preview(host, "pool")
    MainWindow._remember_zone_before_preview(host, "preview.folder")
    assert host._zone_before_preview == "pool"


# ── Esc 回跳 ─────────────────────────────────────────────────────────


def test_root_escape_returns_to_recorded_zone() -> None:
    """优先回记录区，并以 first=True 刷新该区首卡光标。"""
    host = _ZoneReturnHost(zone="pool", focusable={"pool": True})
    assert MainWindow._on_preview_root_escape(host) is True
    assert host.calls == [("pool", True)]


def test_root_escape_without_record_falls_back_to_selector() -> None:
    """无记录（程序启动后直接进预览器）时回落文件选择器。"""
    host = _ZoneReturnHost(zone="", focusable={"selector": True})
    assert MainWindow._on_preview_root_escape(host) is True
    assert host.calls == [("selector", True)]


def test_root_escape_falls_back_when_recorded_zone_empty() -> None:
    """记录区不可聚焦（空池）时按 selector → pool → info 继续尝试。"""
    host = _ZoneReturnHost(
        zone="pool", focusable={"selector": True}
    )
    assert MainWindow._on_preview_root_escape(host) is True
    assert host.calls == [("pool", True), ("selector", True)]


def test_root_escape_all_zones_unavailable_returns_false() -> None:
    """所有候选区都不可聚焦：返回 False，让 Esc 继续向下传播。"""
    host = _ZoneReturnHost(zone="pool")
    assert MainWindow._on_preview_root_escape(host) is False
    assert [name for name, _ in host.calls] == ["pool", "selector", "info"]


def test_root_escape_invalid_record_falls_back_to_selector() -> None:
    """异常记录（误存成 preview）不得把焦点送回预览器。"""
    host = _ZoneReturnHost(zone="preview", focusable={"selector": True})
    assert MainWindow._on_preview_root_escape(host) is True
    assert host.calls == [("selector", True)]
