# -*- coding: utf-8 -*-
"""P7.4 显存释放：最小化挂起流体纹理 / 释放 Mica 层 / 恢复重建。

无法在 CI 里量真实显存（计划 P0 已定「显存只报告不门控」），因此本模块
直接验证**释放动作与状态机**：

1. ``StyledFluidBackground.suspend()`` 停 tick、销毁 GPU 子控件、清空静态帧；
2. ``suspend_all()/resume_all()`` 覆盖全部存活实例（弱集合），且恢复可重入；
3. ``MicaMaterial.release_cached_layers()`` 清空层缓存与当前层像素、**不触发
   重烘焙**（``_maybe_rebake`` 未被调用）；
4. 主窗口最小化路径 ``_suspend_background_renderers()`` 同时触达两者。

验证命令：
    python -m pytest tests/unit/ui/layout/test_p74_vram_release.py -v
"""

from __future__ import annotations

from typing import Any, List

import pytest
from PySide6.QtGui import QColor, QPixmap

from freeassetfilter.ui.components.styled_fluid_background import (
    StyledFluidBackground,
)

pytestmark = pytest.mark.unit


def _mark_loaded(background: StyledFluidBackground, renderer: str = "cpu") -> None:
    """把实例置为「已加载 + CPU 渲染器 + 已有静态帧」的最小可挂起状态。"""
    background._loaded = True
    background._renderer = renderer
    background._palette = [QColor(10, 20, 30)] * 5
    background._static_pixmap = QPixmap(4, 4)


def test_suspend_clears_textures_and_resume_rebuilds(qapp: Any) -> None:
    """挂起释放静态帧/GPU 控件；恢复后重新进入已加载态。"""
    background = StyledFluidBackground()
    try:
        _mark_loaded(background)
        background.suspend()
        assert background._suspended is True
        assert background._static_pixmap is None
        assert background._gpu_widget is None
        background.resume()
        assert background._suspended is False
        # 恢复后至少有一个渲染器选择（CPU 路径会重烘静态帧）
        assert background._renderer in {"cpu", "gpu", "gpu_pending"}
    finally:
        background.unload()


def test_suspend_all_and_resume_all_cover_live_instances(qapp: Any) -> None:
    """类级弱集合覆盖所有存活实例，重复调用幂等。"""
    first = StyledFluidBackground()
    second = StyledFluidBackground()
    try:
        _mark_loaded(first)
        _mark_loaded(second)
        suspended = StyledFluidBackground.suspend_all()
        assert suspended >= 2
        assert first._suspended is True and second._suspended is True
        # 已挂起的不重复计数
        assert StyledFluidBackground.suspend_all() == 0
        resumed = StyledFluidBackground.resume_all()
        assert resumed >= 2
        assert first._suspended is False and second._suspended is False
    finally:
        for background in (first, second):
            background.unload()
            assert background not in StyledFluidBackground._LIVE_INSTANCES


def test_mica_release_cached_layers_clears_without_rebake(
    qapp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """释放层缓存与当前层像素，且不触发重烘焙。"""
    from freeassetfilter.ui.mica import material as material_mod

    rebaked: List[int] = []
    monkeypatch.setattr(
        material_mod.MicaMaterial,
        "_maybe_rebake",
        lambda self, force=False: rebaked.append(1),
    )
    mica = material_mod.MicaMaterial.__new__(material_mod.MicaMaterial)
    # 只初始化释放路径需要的字段（避开真实烘焙的构造期依赖）。
    # ``_layer`` / ``_pixmap`` 是 ``ViewportCompositor`` 的属性视图，
    # 因此用真实合成器承载层像素。
    compositor = material_mod.ViewportCompositor()
    compositor.set_layer("layer", QPixmap(2, 2))
    mica._borrowed = False
    mica._compositor = compositor
    mica._layer_pixmap = QPixmap(2, 2)
    mica._layer_cache = {"k1": (None, QPixmap(2, 2)), "k2": (None, QPixmap(2, 2))}
    mica._speculative_key = "s"
    mica._speculative_extra = "e"
    mica._last_req = object()

    released = mica.release_cached_layers()
    assert released == 3  # 2 个缓存层 + 当前层像素
    assert mica._layer_cache == {}
    assert mica._layer is None
    assert mica._layer_pixmap is None
    assert mica._speculative_key is None
    assert rebaked == [], "释放不得触发重烘焙"


def test_main_window_suspend_path_touches_fluid_and_mica(
    qapp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """主窗口最小化路径：流体 suspend_all + Mica release_cached_layers。"""
    from freeassetfilter.ui.main_window import MainWindow

    calls: List[str] = []

    class _FakeMaterial:
        def release_cached_layers(self) -> int:
            calls.append("mica")
            return 1

    class _FakeBackgroundWidget:
        mica = _FakeMaterial()

    class _Shim:
        _mica_background = _FakeBackgroundWidget()

        @staticmethod
        def _mica_material() -> Any:
            return MainWindow._mica_material(_Shim())

    monkeypatch.setattr(
        StyledFluidBackground,
        "suspend_all",
        classmethod(lambda cls: calls.append("fluid") or 1),
    )
    MainWindow._suspend_background_renderers(_Shim())
    assert calls == ["fluid", "mica"]


def test_mica_material_lookup_prefers_mica_property(qapp: Any) -> None:
    """``_mica_material`` 能从包装控件上找到材质（GL/内置两条实现）。"""
    from freeassetfilter.ui.main_window import MainWindow

    class _Material:
        def release_cached_layers(self) -> int:
            return 0

    material = _Material()

    class _Widget:
        mica = material

    class _Shim:
        _mica_background = _Widget()

    assert MainWindow._mica_material(_Shim()) is material

    class _EmptyShim:
        _mica_background = None

    assert MainWindow._mica_material(_EmptyShim()) is None
