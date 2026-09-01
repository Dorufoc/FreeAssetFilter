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


class _StubMicaBackground(QWidget):
    """make_mica_background 的 QWidget 替身。

    带与真实 Mica 背景层一致的窗口事件入口（no-op）：
    ``MainWindow.resizeEvent/moveEvent`` 会把窗口事件转发到 mica 层，
    个别用例（如 ``grab()`` 触发布局与窗口事件链）会走到这些入口；
    普通 ``QWidget`` 缺少它们会 AttributeError。``_mica`` 属性刻意
    不存在——``_start_mica_refresh`` 内部以 ``getattr`` None 守卫跳过
    后台刷新（见 ``_load_mica_settings`` 同款防御）。
    """

    def handle_window_resize(self) -> None:
        """空实现：替身无需响应窗口缩放。"""

    def handle_window_move(self) -> None:
        """空实现：替身无需响应窗口移动。"""


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

    替身带 no-op 的 ``handle_window_resize``/``handle_window_move``
    （``_StubMicaBackground``）：MainWindow 的事件转发路径依赖这两个入口。

    本文件断言不依赖真实 Mica 视觉效果；``TestMicaBackgroundWidgetCpu/GL``
    直接构造真实 Mica 的测试不受本替换影响（未走 ``make_mica_background``）。

    Args:
        monkeypatch: pytest monkeypatch 夹具。
    """

    monkeypatch.setattr(
        "freeassetfilter.ui.main_window.make_mica_background",
        lambda *a, **k: _StubMicaBackground(),
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


class TestBackgroundMode:
    """自定义窗口背景：启动恢复 / 模式切换 / 图片设置 / showEvent 门控。

    所有用例通过 monkeypatch ``MainWindow._load_background_settings`` 控制
    启动配置，与用户真实 data/settings_v2.json 完全隔离；沿用本文件模式：
    qapp fixture、不调用 show()、每例结束 deleteLater + processEvents。
    """

    @staticmethod
    def _patch_background_settings(
        monkeypatch: pytest.MonkeyPatch, config: dict
    ) -> None:
        """把 MainWindow._load_background_settings 替换为返回固定配置。

        Args:
            monkeypatch: pytest monkeypatch 夹具。
            config: 固定返回的背景配置（含 mode / image 键）。
        """
        monkeypatch.setattr(
            MainWindow, "_load_background_settings", staticmethod(lambda: config)
        )

    def test_default_mica_mode(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """默认 mica 模式：custom 层隐藏、mica 层可见。"""
        self._patch_background_settings(monkeypatch, {"mode": "mica", "image": ""})
        window = MainWindow()
        assert window._background_mode == "mica"
        assert window._background_image_name == ""
        assert window._custom_background.isHidden() is True
        assert window._mica_background.isHidden() is False
        window.deleteLater()
        qapp.processEvents()

    def test_startup_restore_image_mode_missing_file(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """image 模式启动恢复：图片缺失时纯色兜底，不抛异常。"""
        self._patch_background_settings(
            monkeypatch, {"mode": "image", "image": "missing.png"}
        )
        window = MainWindow()
        assert window._background_mode == "image"
        # custom 未被显式隐藏（image 模式可见），mica 被隐藏
        assert window._custom_background.isHidden() is False
        assert window._mica_background.isHidden() is True
        # 图片文件不存在：set_image 失败 → 无图（纯色兜底路径）
        assert window._custom_background.has_image() is False
        window.deleteLater()
        qapp.processEvents()

    def test_set_background_mode_switch(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """运行时模式切换：翻转层可见性，切回 mica 时补调度后台刷新。"""
        self._patch_background_settings(monkeypatch, {"mode": "mica", "image": ""})
        window = MainWindow()
        assert getattr(window, "_mica_refresh_started", False) is False

        window.set_background_mode("image")
        assert window._background_mode == "image"
        assert window._custom_background.isHidden() is False
        assert window._mica_background.isHidden() is True

        window.set_background_mode("mica")
        assert window._background_mode == "mica"
        assert window._custom_background.isHidden() is True
        assert window._mica_background.isHidden() is False
        # image 模式启动跳过了 Mica 后台刷新，切回 mica 时补刷标志已置位
        assert window._mica_refresh_started is True

        # 非法模式被忽略：状态不被破坏
        window.set_background_mode("bogus")
        assert window._background_mode == "mica"
        window.deleteLater()
        qapp.processEvents()

    def test_set_custom_background_image(
        self,
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """set_custom_background_image：成功/失败路径与绘制安全。"""
        self._patch_background_settings(monkeypatch, {"mode": "mica", "image": ""})
        window = MainWindow()

        # 生成临时 png（64x32 填色）
        pm = QPixmap(64, 32)
        pm.fill(QColor(120, 40, 200))
        image_path = str(tmp_path / "bg_test.png")
        assert pm.save(image_path, "PNG")

        assert window.set_custom_background_image(image_path) is True
        assert window._custom_background.has_image() is True
        assert window._custom_background.image_path == image_path

        # 不存在路径：返回 False（组件内部清空并回退纯色兜底）
        assert window.set_custom_background_image(str(tmp_path / "nope.png")) is False
        assert window._custom_background.has_image() is False

        # 绘制不崩溃：grab 强制执行 paintEvent，非 null
        grabbed = window._custom_background.grab()
        assert not grabbed.isNull()
        window.deleteLater()
        qapp.processEvents()

    def test_show_event_gating(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """showEvent 门控：image 模式跳过 Mica 刷新调度，mica 模式才调度。"""
        # 防止 100ms 备份恢复定时器访问未构建的 _file_pool（None）
        monkeypatch.setattr(
            MainWindow, "_check_and_restore_backup", lambda self: None
        )

        # image 模式：showEvent 后不调度 Mica 后台刷新
        self._patch_background_settings(monkeypatch, {"mode": "image", "image": ""})
        window = MainWindow()
        window.showEvent(QShowEvent())
        assert getattr(window, "_mica_refresh_started", False) is False
        window.deleteLater()
        qapp.processEvents()

        # mica 模式：showEvent 后调度（置位标志）
        self._patch_background_settings(monkeypatch, {"mode": "mica", "image": ""})
        window2 = MainWindow()
        window2.showEvent(QShowEvent())
        assert window2._mica_refresh_started is True
        window2.deleteLater()
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
        """主题同步与背景刷新切换纯色背景/luminosity。

        背景为不透明纯色，随主题切换：
        深色 → 纯黑 #000000，浅色 → 纯白 #FFFFFF（不再有灰色调 tint）。
        """
        bg = MicaBackgroundWidgetCpu()
        bg.sync_theme()
        assert bg._surface_color in ("#000000", "#FFFFFF")
        assert len(bg._surface_color) == 7  # 不透明纯色（无 alpha 通道）
        bg.refresh_background()
        bg.deleteLater()

    def test_apply_mica_parameters(self, qapp: QApplication, monkeypatch) -> None:
        """滑动条实时预览入口：参数透传到 mixin 与 MicaMaterial。

        置空壁纸路径禁用后台刷新线程（refresh_async 直接返回），
        聚焦参数传递与壁纸缓存失效逻辑，避免测试中终止在途线程。
        注意：main_window 经 ui 短路径导入了 components.mica_material，
        与包路径 freeassetfilter.ui.components.mica_material 是两份模块
        实例，必须按材质对象实际所属模块打补丁才生效。
        """
        import sys as _sys

        bg = MicaBackgroundWidgetCpu(tint_opacity=50)
        mica_material_mod = _sys.modules[type(bg._mica).__module__]
        monkeypatch.setattr(mica_material_mod, "_get_wallpaper_path", lambda: "")
        assert bg._tint_opacity == 50

        bg.apply_mica_parameters(
            blur_radius=120, saturation=2.0, contrast=1.0, tint_opacity=30,
        )
        assert bg._blur_radius == 120
        assert bg._saturation == 2.0
        assert bg._contrast == 1.0
        assert bg._tint_opacity == 30
        assert bg._mica._blur_radius == 120
        assert bg._mica._saturation == 2.0
        assert bg._mica._contrast == 1.0
        assert bg._mica._overlay_opacity == pytest.approx(0.3)

        # 仅叠加层透明度变化：绘制期生效，不失效壁纸缓存（无需重烘焙/重建）
        bg._mica._wallpaper_path = "cached"
        bg.apply_mica_parameters(tint_opacity=80)
        assert bg._mica._wallpaper_path == "cached"
        assert bg._mica._overlay_opacity == pytest.approx(0.8)

        # 模糊半径变化：壁纸缓存失效（强制后台重算）
        bg.apply_mica_parameters(blur_radius=300)
        assert bg._mica._wallpaper_path == ""
        assert bg._mica._blur_radius == 300

        # 对比度变化：同样失效壁纸缓存（对比度参与增强+模糊管线）
        bg.apply_mica_parameters(contrast=2.0)
        assert bg._mica._wallpaper_path == ""
        assert bg._mica._contrast == 2.0

        bg._mica.dispose()
        bg.deleteLater()
        qapp.processEvents()


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