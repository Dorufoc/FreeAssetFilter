# -*- coding: utf-8 -*-
"""设置页外观实时预览的下发契约（性能回归门禁）。

覆盖 ``ui/layout/settings_layout`` 的预览链路（阶段 B 契约）：

1. 主题切换只做逐控件下发，**不再**触发应用级
   ``QApplication.setStyleSheet`` 全树重刷（性能根因，见
   ``ui/theme/app_stylesheet`` 模块 docstring 的实测数据）；
2. 纯背景模式切换整段跳过主题链路（不重设 ``tm``、不抓整窗快照、
   不建设置窗遮罩）——历史实现会跑完整套主题链路（两轮全表重刷）；
3. 同值/重复改动零下发（去重）；
4. 连点在去抖窗口内合并为有限次切换（不再逐次叠加），最终状态与
   最后选择一致。

验证命令：
    python -m pytest tests/unit/ui/layout/test_settings_theme_preview.py --timeout 60 -q
"""

# targets: ui.layout.settings_layout, ui.theme.app_stylesheet

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterator, List

import pytest
from PySide6.QtWidgets import QApplication

# 短路径导入 bootstrap（与 tests/unit/ui/test_main_window.py 同款）。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

import freeassetfilter.ui.theme  # noqa: E402  (注册 theme 短路径别名)

from theme import tm  # noqa: E402
from freeassetfilter.ui.layout.settings_layout import (  # noqa: E402
    APPEARANCE_PREVIEW_DEBOUNCE_MS,
    SettingsLayout,
)
from freeassetfilter.ui.theme import app_stylesheet as app_qss  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _restore_theme() -> Iterator[None]:
    """用例前后恢复主题偏好（``tm`` 单例不由根 conftest 重置）。"""
    try:
        original = tm.get_theme_mode()
    except Exception:
        original = "dark"
    yield
    try:
        tm.set_theme_mode(original)
    except Exception:
        pass  # 用例清理失败不影响断言结果


@pytest.fixture
def layout(qapp: QApplication) -> Iterator[SettingsLayout]:
    """构建独立设置页（无主窗口：主题链路仍完整，背景下发自然跳过）。"""
    widget = SettingsLayout()
    widget.resize(720, 520)
    qapp.processEvents()
    try:
        yield widget
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


class _DeliveryCounter:
    """统计逐控件下发次数（包装注册表 ``_apply_entry``）。"""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """安装计数包装。

        Args:
            monkeypatch: pytest 补丁器（用例结束自动还原）。
        """
        self.count = 0
        original = app_qss._AppStylesheetRegistry._apply_entry

        def counting(registry_self: Any, widget: Any) -> bool:
            applied = original(registry_self, widget)
            if applied:
                self.count += 1
            return applied

        monkeypatch.setattr(
            app_qss._AppStylesheetRegistry, "_apply_entry", counting
        )

    def reset(self) -> None:
        """清零计数。"""
        self.count = 0


class _AppSheetCounter:
    """统计应用级 ``QApplication.setStyleSheet`` 调用次数。"""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """安装计数包装。

        Args:
            monkeypatch: pytest 补丁器（用例结束自动还原）。
        """
        self.count = 0
        original = QApplication.setStyleSheet

        def counting(app_self: QApplication, sheet: str) -> None:
            self.count += 1
            original(app_self, sheet)

        monkeypatch.setattr(QApplication, "setStyleSheet", counting)

    def reset(self) -> None:
        """清零计数。"""
        self.count = 0


def _settle(qapp: QApplication, ms: int = 60) -> None:
    """递进泵浦事件到去抖窗口之后。

    Args:
        qapp: 应用实例。
        ms: 等待步长（毫秒）。
    """
    for _ in range(30):
        qapp.processEvents()
    # 推进去抖窗口（含余量）
    import time

    deadline = time.monotonic() + (APPEARANCE_PREVIEW_DEBOUNCE_MS + 40) / 1000.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    for _ in range(5):
        qapp.processEvents()


class TestThemePreviewDelivery:
    """主题切换：逐控件下发、零应用级重刷。"""

    def test_widget_delivery_mode_is_default(self, qapp: QApplication) -> None:
        """默认下发模式为 widget（性能优先）。"""
        assert app_qss.stylesheet_mode() == "widget"

    def test_theme_switch_never_uses_app_stylesheet(
        self, qapp: QApplication, layout: SettingsLayout,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """切换深色模式：零次应用级重刷，逐控件下发 > 0，``tm`` 已生效。"""
        app_counter = _AppSheetCounter(monkeypatch)
        delivery_counter = _DeliveryCounter(monkeypatch)
        page = layout._appearance_page
        try:
            tm.set_theme_mode("dark")
            _settle(qapp)
            app_counter.reset()
            delivery_counter.reset()

            page.apply_theme_mode("light")
            _settle(qapp)

            assert app_counter.count == 0, "主题切换不得触发应用级全表重刷"
            assert delivery_counter.count > 0, "片段应逐控件下发"
            assert tm.effective_theme() == "light"
        finally:
            tm.set_theme_mode("dark")

    def test_identical_change_is_noop(
        self, qapp: QApplication, layout: SettingsLayout,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """同值重复预览零下发（目标与现状一致整段短路）。"""
        counter = _DeliveryCounter(monkeypatch)
        page = layout._appearance_page
        tm.set_theme_mode("dark")
        _settle(qapp)

        page.apply_theme_mode("dark")
        _settle(qapp)
        counter.reset()

        page.apply_theme_mode("dark")
        _settle(qapp)
        assert counter.count == 0
        assert tm.effective_theme() == "dark"


class TestBackgroundPreviewShortCircuit:
    """背景模式切换：不触碰主题链路、不抓拍、不建遮罩。"""

    def test_background_switch_skips_theme_pipeline(
        self, qapp: QApplication, layout: SettingsLayout,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """背景三态切换：``tm`` 完全不被触碰，且无过渡遮罩。"""
        overlay_calls: List[int] = []
        theme_mode_calls: List[str] = []

        # 基线主题先设定，再装计数（避免把基线设置本身算进去）。
        tm.set_theme_mode("dark")
        _settle(qapp)

        original_overlay = SettingsLayout._start_settings_overlay

        def counting_overlay(layout_self: SettingsLayout) -> None:
            overlay_calls.append(1)
            original_overlay(layout_self)

        monkeypatch.setattr(
            SettingsLayout, "_start_settings_overlay", counting_overlay
        )
        original_set_mode = tm.set_theme_mode

        def counting_set_mode(mode: str) -> None:
            theme_mode_calls.append(mode)
            original_set_mode(mode)

        monkeypatch.setattr(tm, "set_theme_mode", counting_set_mode)

        page = layout._appearance_page

        # 图像分段在无持久化图片时会弹文件对话框：桩掉选择流程，
        # 直接走「已暂存图像模式」的预览路径。
        def fake_choose_image(page_self: Any, force: bool = False) -> None:
            page_self._stage_background_settings("image")
            page_self._update_bg_ui_state()
            page_self.appearance_changed.emit()

        monkeypatch.setattr(
            type(page), "_choose_bg_image", fake_choose_image, raising=False
        )

        before = tm.effective_theme()

        for index in (0, 1, 2):  # 简约 → 云母 → 图像
            page._on_bg_segment_changed(index)
            _settle(qapp)

        assert theme_mode_calls == [], "背景切换不得重设主题偏好"
        assert overlay_calls == [], "背景切换不得建设置窗过渡遮罩"
        assert tm.effective_theme() == before


class TestRapidToggleCoalescing:
    """连点合并：首击立即 + 窗口末尾最多一次补发。"""

    def test_burst_does_not_stack_switches(
        self, qapp: QApplication, layout: SettingsLayout,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """6 次连点：全表重刷恒为 0，最终状态与最后一次选择一致。"""
        app_counter = _AppSheetCounter(monkeypatch)
        delivery_counter = _DeliveryCounter(monkeypatch)
        page = layout._appearance_page

        tm.set_theme_mode("dark")
        _settle(qapp)
        app_counter.reset()
        delivery_counter.reset()

        for mode in ("light", "dark", "light", "dark", "light", "dark"):
            page.apply_theme_mode(mode)
        _settle(qapp)

        assert app_counter.count == 0
        assert tm.effective_theme() == "dark"
        # 一次首击 + 最多一次末尾补发：逐控件下发量不超过两轮
        assert delivery_counter.count <= 2 * app_qss.registered_widget_count()
