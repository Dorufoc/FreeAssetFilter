# -*- coding: utf-8 -*-
"""主窗口单元测试（todo-23 批 3 / task-23）。

覆盖 ui.main_window：只测构造与结构，不 exec() 主事件循环。

断言范围（QA 要求）：
- 三栏布局拼装：splitter 上三栏（_panel_left / _panel_center / _panel_right）
- 各栏构建入口：_build_panel("left"/"center"/"right") 后对应布局非 None
- 菜单动作存在：标题栏按钮与主题切换入口
- 关闭清理：closeEvent 安全（不 show，用 QCloseEvent 手动触发）
- 不弹真实窗口（不调用 show）；不出错地跨过 _dispose_mica

验证命令：
    python -m pytest tests/unit/ui/test_main_window.py --timeout 60 -q
"""

# targets: ui.main_window

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QCloseEvent, QColor, QMouseEvent, QPixmap, QShowEvent
from PySide6.QtWidgets import QApplication, QWidget

# main_window.py 自带 _ui_root bootstrap（第 22-30 行），
# 但其依赖的 components/layout 模块同样依赖该 short-path。
_UI_ROOT: str = str(Path(__file__).resolve().parents[3] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.main_window import (  # noqa: E402
    MainWindow,
    MicaBackgroundWidgetCpu,
    MicaBackgroundWidgetGL,
    SettingsWindow,
    make_mica_background,
    main,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _block_deferred_panel_build(monkeypatch: pytest.MonkeyPatch) -> None:
    """用普通 QWidget 替代真实 Mica 背景，隔离 MicaMaterial 残留源。

    根因（task-29 回归，本机复现）：``MainWindow`` 构造时经
    ``make_mica_background`` 创建 ``MicaBackgroundWidgetCpu/GL``，其内部
    ``MicaMaterial`` 构造会在顶层窗口安装 ``installEventFilter`` 事件过滤器，
    并创建多个 QTimer（``_update_timer``/``_settle_timer``/``_fade_timer``/
    ``_deactivate_timer``/``_watchdog``）。测试销毁窗口（``deleteLater()``）
    后这些残留仍附着在 QApplication/顶层窗口事件链上；后续任意测试进入
    ``QEventLoop``（如 ``wait_for_signal`` 等待 worker 线程信号）处理事件/
    原生消息时，回调访问已删除的 C++ 对象 → 原生访问冲突 ``0xC0000005``。

    崩溃签名唯一且崩点固定为「首个进入事件循环的 worker 测试」。二分实验：
    - 阻断 ``_build_panels_deferred``/``_install_edge_hit_test_passthrough``/
      ``installNativeEventFilter`` 均不能止崩（3 阻断 × 2 连崩）；
    - 仅替换 ``make_mica_background`` → 普通 ``QWidget`` 即零 failure 通过
      本文件 + workers 组合（25 passed × 5，含 drive_list/timeout 线程测试）。

    本文件断言不依赖真实 Mica 视觉效果；``TestMicaBackgroundWidgetCpu/GL``
    直接构造真实 Mica 的测试不受本替换影响（未走 ``make_mica_background``）。

    Args:
        monkeypatch: pytest monkeypatch 夹具。
    """

    monkeypatch.setattr(
        "freeassetfilter.ui.main_window.make_mica_background",
        lambda *a, **k: QWidget(),
    )


class TestMainWindowStructure:
    """三栏结构：splitter / 面板 / 标题栏均就绪。"""

    def test_three_panel_splitter(self, qapp: QApplication) -> None:
        """splitter 已挂载三栏面板（左/中/右）。"""
        window = MainWindow()
        assert window._splitter is not None
        assert window._splitter.count() == 3
        assert len(window._panels) == 3
        window.deleteLater()
        qapp.processEvents()

    def test_panel_object_names(self, qapp: QApplication) -> None:
        """三栏对象名符合约定（PanelLeft / PanelCenter / PanelRight）。"""
        window = MainWindow()
        names = [panel.objectName() for panel in window._panels]
        assert names == ["PanelLeft", "PanelCenter", "PanelRight"]
        window.deleteLater()
        qapp.processEvents()

    def test_title_bar_buttons_exist(self, qapp: QApplication) -> None:
        """标题栏按钮（最小化/最大化/关闭/主题/设置/GitHub）均存在。"""
        window = MainWindow()
        for attr in (
            "_minimize_btn",
            "_maximize_btn",
            "_close_btn",
            "_theme_btn",
            "_settings_btn",
            "_github_btn",
        ):
            assert getattr(window, attr) is not None, f"{attr} 缺失"
        window.deleteLater()
        qapp.processEvents()

    def test_placeholder_panels_initially(self, qapp: QApplication) -> None:
        """三栏初始为占位标签，真实布局延迟到 _build_panel 才就绪。"""
        window = MainWindow()
        assert window._file_selector is None
        assert window._file_pool is None
        assert window._previewer is None
        assert window._panel_left_placeholder is not None
        window.deleteLater()
        qapp.processEvents()


class TestMainWindowPanelBuild:
    """三栏真实布局构建：手动触发 _build_panel（不 show 窗口）。"""

    def test_build_all_panels(self, qapp: QApplication) -> None:
        """依次构建左/中/右三栏：file_selector/file_pool/previewer 就绪。"""
        window = MainWindow()
        window._build_panel("left")
        window._build_panel("center")
        window._build_panel("right")
        assert window._file_selector is not None
        assert window._file_pool is not None
        assert window._previewer is not None
        # 占位标签已被移除
        assert window._panel_left_placeholder is None
        assert window._panel_center_placeholder is None
        assert window._panel_right_placeholder is None
        window.deleteLater()
        qapp.processEvents()

    def test_build_single_panel_then_placeholders_remain(
        self, qapp: QApplication
    ) -> None:
        """只构建左栏时，中/右栏占位仍在。"""
        window = MainWindow()
        window._build_panel("left")
        assert window._file_selector is not None
        assert window._file_pool is None
        assert window._previewer is None
        assert window._panel_left_placeholder is None
        assert window._panel_center_placeholder is not None
        assert window._panel_right_placeholder is not None
        window.deleteLater()
        qapp.processEvents()

    def test_build_panel_failure_is_isolated(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """单栏构建失败不拖垮整体启动（_build_panel 内部捕获异常）。"""
        window = MainWindow()
        # 注入必失败模块：让 file_selector 构造抛异常
        import freeassetfilter.ui.main_window as mw

        def _boom_selector(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("injected build failure")

        monkeypatch.setattr(mw, "FileSelectorLayout", _boom_selector)  # type: ignore[assignment]
        window._build_panel("left")
        # 左栏失败：_file_selector 仍为 None，中/右栏不受影响
        assert window._file_selector is None
        window._build_panel("center")
        assert window._file_pool is not None
        monkeypatch.undo()
        window.deleteLater()
        qapp.processEvents()


class TestMainWindowClose:
    """关闭清理：closeEvent 安全（不 show，手动触发）。"""

    def test_close_event_no_raise(self, qapp: QApplication) -> None:
        """未 show 的窗口手动 closeEvent 不抛异常。"""
        window = MainWindow()
        event = QCloseEvent()
        window.closeEvent(event)
        assert event.isAccepted()
        window.deleteLater()
        qapp.processEvents()

    def test_close_event_with_panels(self, qapp: QApplication) -> None:
        """已构建三栏后 closeEvent 仍安全（flush_backup 受保护）。"""
        window = MainWindow()
        window._build_panel("left")
        window._build_panel("center")
        window._build_panel("right")
        window.closeEvent(QCloseEvent())
        window.deleteLater()
        qapp.processEvents()


class TestMicaBackgroundWidgetCpu:
    """MicaBackgroundWidgetCpu：构造/绘制/交互/主题同步。"""

    def test_construct_and_render(self, qapp: QApplication) -> None:
        """构造 + 真实 paintEvent（render 到 QPixmap）不抛异常。"""
        bg = MicaBackgroundWidgetCpu()
        assert bg._mica is not None
        assert bg._blur_radius == 200
        bg.resize(320, 200)
        bg.show()
        qapp.processEvents()
        pixmap = QPixmap(320, 200)
        bg.render(pixmap)
        assert not pixmap.isNull()
        bg.deleteLater()
        qapp.processEvents()

    def test_handle_window_resize_move(self, qapp: QApplication) -> None:
        """窗口拖拽/缩放回调（begin_interaction）不抛异常。"""
        bg = MicaBackgroundWidgetCpu()
        bg.handle_window_resize()
        bg.handle_window_move()
        assert bg._mica is not None
        bg.deleteLater()

    def test_sync_theme_and_refresh(self, qapp: QApplication) -> None:
        """主题同步与背景刷新切换 tint/luminosity。"""
        bg = MicaBackgroundWidgetCpu()
        bg.sync_theme()
        assert bg._tint_color in ("#202020B4", "#FFFFFFB4")
        bg.refresh_background()
        bg.deleteLater()

    def test_parse_tint(self) -> None:
        """#RRGGBBAA 解析为 QColor；非法值回落默认色。"""
        color = MicaBackgroundWidgetCpu._parse_tint("#102030AA")
        assert color.alpha() == 0xAA
        fallback = MicaBackgroundWidgetCpu._parse_tint("garbage")
        assert fallback == QColor(32, 32, 32, 160)


class TestMicaBackgroundWidgetGL:
    """MicaBackgroundWidgetGL：构造与重绘回调（GPU 版）。"""

    def test_construct_and_handlers(self, qapp: QApplication) -> None:
        """无 OpenGL 环境下跳过，否则构造 + 重绘回调安全。"""
        try:
            bg = MicaBackgroundWidgetGL()
        except Exception:
            pytest.skip("OpenGL context unavailable")
        assert bg._mica is not None
        bg.handle_window_resize()
        bg.handle_window_move()
        assert bg._blur_radius == 200
        bg.deleteLater()
        qapp.processEvents()


class TestMakeMicaBackground:
    """make_mica_background：工厂返回 Mica 背景控件（默认 CPU 回退）。"""

    def test_factory_returns_mica_widget(self, qapp: QApplication) -> None:
        """默认路径返回 CPU 或 GL 版之一，且已构建 MicaMaterial。"""
        bg = make_mica_background()
        assert isinstance(bg, (MicaBackgroundWidgetCpu, MicaBackgroundWidgetGL))
        assert bg._mica is not None
        bg.deleteLater()
        qapp.processEvents()


class TestSettingsWindow:
    """SettingsWindow：独立设置窗口构造/主题刷新/事件过滤。"""

    def test_construct(self, qapp: QApplication) -> None:
        """构造：标题、根容器、关闭按钮、无 Mica（防御属性保留）。"""
        win = SettingsWindow()
        assert win.windowTitle() == "设置"
        assert win._root is not None
        assert win._close_btn is not None
        assert win._mica_background is None  # 设置窗口不使用 Mica
        win.deleteLater()
        qapp.processEvents()

    def test_show_event_no_raise(self, qapp: QApplication) -> None:
        """手动 showEvent 触发 _sync_theme 不抛异常。"""
        win = SettingsWindow()
        win.showEvent(QShowEvent())
        assert win._title_label is not None
        win.deleteLater()
        qapp.processEvents()

    def test_event_filter_ignores_non_title_bar(self, qapp: QApplication) -> None:
        """未 show 时（无 windowHandle）标题栏左键拖拽返回 False，事件不吞。"""
        win = SettingsWindow()
        header = win.findChild(QWidget, "SettingsTitleBar")
        assert header is not None
        ev = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(10, 10),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        assert win.eventFilter(header, ev) is False
        win.deleteLater()
        qapp.processEvents()


class TestModuleEntryPoint:
    """main：模块级入口函数（不执行，避免阻塞事件循环）。"""

    def test_main_is_callable(self) -> None:
        """入口函数签名引用即可覆盖符号，callable 校验。"""
        assert callable(main)
        assert inspect.isfunction(main)