# -*- coding: utf-8 -*-
"""设置窗口关闭引用清理与 closeEvent 纵深防御（exit-crash 修复 A+B 锁存测试）。

TDD 红阶段：以下断言在修复前应失败——
- 开→关设置窗口后 ``_settings_window`` 仍非 None（``is obj`` 恒失败）；
- 向 ``closeEvent`` 注入已销毁引用时抛 RuntimeError。

验证命令（offscreen）：
    QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/ui/test_main_window_settings_close.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QWidget

_UI_ROOT: str = str(Path(__file__).resolve().parents[3] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.main_window import MainWindow  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _stub_mica_background(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离 MicaMaterial 原生残留（同 test_main_window.py 做法）。

    Args:
        monkeypatch: pytest monkeypatch 夹具。
    """
    from PySide6.QtWidgets import QWidget as _QWidget

    class _Stub(_QWidget):
        def handle_window_resize(self) -> None:
            """空实现：替身无需响应窗口缩放。"""

        def handle_window_move(self) -> None:
            """空实现：替身无需响应窗口移动。"""

    monkeypatch.setattr(
        "freeassetfilter.ui.main_window.make_mica_background",
        lambda *a, **k: _Stub(),
    )


def _make_window(qapp: QApplication) -> MainWindow:
    """构造主窗口（不 show）。

    Args:
        qapp: 全局 QApplication。

    Returns:
        MainWindow: 新建主窗口实例。
    """
    window = MainWindow()
    return window


def _teardown(window: MainWindow, qapp: QApplication) -> None:
    """安全销毁窗口并排空事件队列。

    Args:
        window: 待销毁主窗口。
        qapp: 全局 QApplication。
    """
    window.deleteLater()
    qapp.processEvents()


class TestSettingsWindowCloseClearsRef:
    """A：开→关设置窗口后引用必清空。"""

    def test_open_then_close_clears_ref(self, qapp: QApplication) -> None:
        """打开设置窗口再关闭，destroyed 后引用必须为 None。"""
        window = _make_window(qapp)
        try:
            window._open_settings_window()
            assert window._settings_window is not None
            ref = window._settings_window
            ref.close()
            qapp.processEvents()
            qapp.processEvents()
            assert window._settings_window is None
        finally:
            _teardown(window, qapp)

    def test_stale_destroyed_event_never_clears_new_window(
        self, qapp: QApplication
    ) -> None:
        """旧窗口 destroyed 晚到时绝不能误清已重建的新窗口引用。"""
        window = _make_window(qapp)
        try:
            window._open_settings_window()
            first = window._settings_window
            assert first is not None
            first_gen = getattr(window, "_settings_window_gen", None)
            # 关闭旧窗口 → 引用应清空
            first.close()
            qapp.processEvents()
            qapp.processEvents()
            assert window._settings_window is None
            # 重建新窗口
            window._open_settings_window()
            second = window._settings_window
            assert second is not None
            assert second is not first
            # 模拟旧窗口 destroyed 信号晚到（传陈旧代际/旧对象）
            stale_gen: Any = first_gen
            if stale_gen is not None:
                window._on_settings_window_closed(stale_gen)
            else:  # 代际方案未实施时的回退：旧对象不应误清新引用
                window._on_settings_window_closed(first)
            assert window._settings_window is second
            # 正常关闭新窗口后仍能清空
            second.close()
            qapp.processEvents()
            qapp.processEvents()
            assert window._settings_window is None
        finally:
            _teardown(window, qapp)


class TestCloseEventDestroyedRefDefense:
    """B：closeEvent 永不对已销毁 C++ 对象崩溃。"""

    def test_close_event_with_destroyed_settings_ref(
        self, qapp: QApplication
    ) -> None:
        """注入已销毁引用后调 closeEvent 不抛，退出流程继续。"""
        window = _make_window(qapp)
        try:
            window._open_settings_window()
            ref = window._settings_window
            assert ref is not None
            ref.close()
            qapp.processEvents()
            qapp.processEvents()
            # 若 A 已生效引用为 None，则重建"过期引用"场景：
            # 重新打开后关闭 C++ 对象但强留 Python 包装，模拟 destroyed 未清空。
            if window._settings_window is None:
                window._open_settings_window()
                stale = window._settings_window
                assert stale is not None
                # 直接销毁 C++ 对象：close + 处理事件使 DeleteOnClose 生效，
                # 若槽已清空则手动挂回过期包装以模拟旧 bug 状态。
                stale.close()
                qapp.processEvents()
                qapp.processEvents()
                if window._settings_window is None:
                    window._settings_window = stale
            assert window._settings_window is not None
            event = QCloseEvent()
            window.closeEvent(event)  # 不得抛出 RuntimeError
            assert event.isAccepted()
            assert window._settings_window is None
        finally:
            _teardown(window, qapp)
