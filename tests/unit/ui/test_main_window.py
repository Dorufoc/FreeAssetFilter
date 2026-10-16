# -*- coding: utf-8 -*-
"""主窗口单元测试（todo-23 批 3 / task-23）。

覆盖 ui.main_window：只测构造与结构，不 exec() 主事件循环。

断言范围（QA 要求）：
- 主布局装配：MainLayout 四区域（selector / preview / pool / info）
- 各区域构建入口：_build_panel("selector"/"preview"/"pool"/"info") 后对应布局非 None
- 菜单动作存在：标题栏按钮与主题切换入口
- 关闭清理：closeEvent 安全（不 show，用 QCloseEvent 手动触发）
- 不弹真实窗口（不调用 show）；不出错地跨过 _dispose_mica

验证命令：
    python -m pytest tests/unit/ui/test_main_window.py --timeout 60 -q
"""

# targets: ui.main_window

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QCloseEvent, QColor, QMouseEvent, QPixmap, QShowEvent
from PySide6.QtWidgets import QApplication, QWidget

# main_window.py 自带 _ui_root bootstrap（第 22-30 行），
# 但其依赖的 components/layout 模块同样依赖该 short-path。
_UI_ROOT: str = str(Path(__file__).resolve().parents[3] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.main_window import (  # noqa: E402
    FIXED_MICA_PARAMS,
    MainWindow,
    MicaBackgroundWidgetCpu,
    MicaBackgroundWidgetGL,
    SettingsWindow,
    fixed_mica_params,
    make_mica_background,
)

# 全局主题单例（与 main_window 同款短路径；不在 reset_singletons 清单，
# 测试中切换主题后必须手动恢复）
from theme import tm  # noqa: E402

from tests.support.qt_helpers import process_qt_events  # noqa: E402

pytestmark = pytest.mark.unit


class _StubMicaBackground(QWidget):
    """make_mica_background 的 QWidget 替身。

    带与真实 Mica 背景层一致的窗口事件入口（no-op）：
    ``MainWindow.resizeEvent/moveEvent`` 会把窗口事件转发到 mica 层，
    个别用例（如 ``grab()`` 触发布局与窗口事件链）会走到这些入口；
    普通 ``QWidget`` 缺少它们会 AttributeError。``_ensure_mica_material``
    返回 None——``_start_mica_refresh`` 以 None 守卫跳过后台刷新
    （真实控件在窗口显示后惰性创建材质，本替身无材质可建）。

    ``sync_theme`` 同为类级 no-op：``MainWindow._on_theme_changed``
    （``tm.theme_changed`` 广播路径）无条件调用它；主题切换测试
    （``TestContentThemeTransition``）依赖该方法存在，且类级方法
    不受 monkeypatch undo 影响（实例级补丁在测试结束后被撤销，
    残留广播会撞 AttributeError）。
    """

    def handle_window_resize(self) -> None:
        """空实现：替身无需响应窗口缩放。"""

    def handle_window_move(self) -> None:
        """空实现：替身无需响应窗口移动。"""

    def _ensure_mica_material(self):
        """空实现：替身无材质，返回 None 让调用方走守卫分支。"""

    def sync_theme(self) -> None:
        """空实现：替身无需重烘焙 Mica 主题。"""


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
    """主布局结构：MainLayout 四区域 / 占位 / 标题栏均就绪。"""

    def test_main_layout_zones(self, qapp: QApplication) -> None:
        """MainLayout 已挂载 4 个区域（selector / preview / pool / info）。"""
        window = MainWindow()
        assert window._main_layout is not None
        assert window._main_layout.mode == "workspace"
        assert set(window._main_layout.zones.keys()) == {
            "selector", "preview", "pool", "info",
        }
        assert len(window._zone_placeholders) == 4
        assert all(ph is not None for ph in window._zone_placeholders.values())
        window.deleteLater()
        qapp.processEvents()

    def test_zone_object_names(self, qapp: QApplication) -> None:
        """区域对象名符合约定（MainZoneSelector / Preview / Pool / Info）。"""
        window = MainWindow()
        names = [zone.objectName() for zone in window._main_layout.zones.values()]
        assert names == [
            "MainZoneSelector",
            "MainZonePreview",
            "MainZonePool",
            "MainZoneInfo",
        ]
        window.deleteLater()
        qapp.processEvents()

    def test_title_bar_buttons_exist(self, qapp: QApplication) -> None:
        """标题栏按钮（最小化/最大化/关闭/主题/设置/重置布局/布局切换）均存在。"""
        window = MainWindow()
        for attr in (
            "_minimize_btn",
            "_maximize_btn",
            "_close_btn",
            "_theme_btn",
            "_settings_btn",
            "_reset_layout_btn",
            "_layout_toggle_btn",
        ):
            assert getattr(window, attr) is not None, f"{attr} 缺失"
        window.deleteLater()
        qapp.processEvents()

    def test_lightweight_startup_shell(self, qapp: QApplication) -> None:
        """轻量启动模式先提供标题栏与加载覆盖层，不创建业务面板。"""
        window = MainWindow(defer_heavy_init=True)
        assert window._content is not None
        assert window._main_layout is None
        assert window._startup_overlay is not None
        for attr in (
            "_minimize_btn",
            "_maximize_btn",
            "_close_btn",
            "_theme_btn",
            "_settings_btn",
            "_reset_layout_btn",
            "_layout_toggle_btn",
        ):
            assert getattr(window, attr) is not None
        window.deleteLater()
        qapp.processEvents()

    def test_lightweight_deferred_init_is_idempotent(self, qapp: QApplication) -> None:
        """deferred 内容初始化重复调用不会重复替换窗口内容。"""
        window = MainWindow(defer_heavy_init=True)
        window.initialize_deferred_content()
        root = window._root
        window.initialize_deferred_content()
        assert window._deferred_content_ready is True
        assert window._root is root or window._root is not None
        assert window._main_layout is not None
        window.deleteLater()
        qapp.processEvents()

    def test_placeholder_panels_initially(self, qapp: QApplication) -> None:
        """四区域初始为占位标签，真实布局延迟到 _build_panel 才就绪。"""
        window = MainWindow()
        assert window._file_selector is None
        assert window._file_pool is None
        assert window._previewer is None
        assert window._info_panel is None
        assert window._zone_placeholders["selector"] is not None
        window.deleteLater()
        qapp.processEvents()


class TestMainWindowPanelBuild:
    """四区域真实布局构建：手动触发 _build_panel（不 show 窗口）。"""

    def test_build_all_panels(self, qapp: QApplication) -> None:
        """依次构建四区域：file_selector/file_pool/previewer/info 就绪。"""
        window = MainWindow()
        window._build_panel("selector")
        window._build_panel("preview")
        window._build_panel("pool")
        window._build_panel("info")
        assert window._file_selector is not None
        assert window._file_pool is not None
        assert window._previewer is not None
        assert window._info_panel is not None
        # 占位标签已被移除
        assert all(ph is None for ph in window._zone_placeholders.values())
        window.deleteLater()
        qapp.processEvents()

    def test_build_single_panel_then_placeholders_remain(
        self, qapp: QApplication
    ) -> None:
        """只构建选择器时，其余区域占位仍在。"""
        window = MainWindow()
        window._build_panel("selector")
        assert window._file_selector is not None
        assert window._file_pool is None
        assert window._previewer is None
        assert window._info_panel is None
        assert window._zone_placeholders["selector"] is None
        assert window._zone_placeholders["preview"] is not None
        assert window._zone_placeholders["pool"] is not None
        assert window._zone_placeholders["info"] is not None
        window.deleteLater()
        qapp.processEvents()

    def test_build_panel_failure_is_isolated(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """单区域构建失败不拖垮整体启动（_build_panel 内部捕获异常）。"""
        window = MainWindow()
        # 注入必失败模块：让 file_selector 构造抛异常。
        # 布局模块由 _build_panel 局部导入（首帧提速），故补丁打在
        # 源模块属性上——局部导入在调用时才读取该属性。
        def _boom_selector(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("injected build failure")

        monkeypatch.setattr(
            "layout.file_selector_layout.FileSelectorLayout", _boom_selector
        )
        window._build_panel("selector")
        # 选择器失败：_file_selector 仍为 None，其余区域不受影响
        assert window._file_selector is None
        window._build_panel("pool")
        assert window._file_pool is not None
        monkeypatch.undo()
        window.deleteLater()
        qapp.processEvents()

    def test_set_layout_mode_switches_pool_and_previewer(
        self, qapp: QApplication
    ) -> None:
        """set_layout_mode：池子视图 / 按钮承载方式 / 底栏宿主随布局切换。"""
        window = MainWindow()
        window._build_panel("preview")
        window._build_panel("pool")
        assert window._layout_mode == "workspace"
        assert window._file_pool.get_view_mode() == "grid"
        assert window._previewer._actions_top is True
        # New：底栏留在预览器内部（隐藏），无经典槽位
        assert window._main_layout.classic_action_slot() is None
        assert window._previewer._bottom_bar.parentWidget() is window._previewer

        assert window.set_layout_mode("classic") is True
        assert window._layout_mode == "classic"
        assert window._file_pool.get_view_mode() == "list"
        assert window._previewer._actions_top is False
        # 经典：底栏挂到右列槽位（信息面板下方，整列最底部）
        slot = window._main_layout.classic_action_slot()
        assert slot is not None
        assert window._previewer._bottom_bar.parentWidget() is slot
        assert window._previewer._bottom_bar.isHidden() is False

        assert window.set_layout_mode("workspace") is True
        assert window._file_pool.get_view_mode() == "grid"
        assert window._previewer._actions_top is True
        # 切回 New：底栏归位到预览器内部并隐藏
        assert window._previewer._bottom_bar.parentWidget() is window._previewer
        assert window._previewer._bottom_bar.isHidden() is True

        # 非法值：拒绝且不改变状态
        assert window.set_layout_mode("bogus") is False
        assert window._layout_mode == "workspace"
        window.deleteLater()
        qapp.processEvents()

    def test_layout_toggle_button_switches_mode_and_icon(
        self, qapp: QApplication
    ) -> None:
        """布局切换按钮：点击在 classic / workspace 间切换并同步图标与提示。"""
        window = MainWindow()
        assert window.get_layout_mode() == "workspace"
        assert window._layout_toggle_btn.toolTip() == "切换为经典三栏布局"

        window._layout_toggle_btn.click()
        assert window.get_layout_mode() == "classic"
        assert window._layout_toggle_btn.toolTip() == "切换为预览优先布局"
        assert str(window._layout_toggle_btn._svg_icon_path).endswith(
            "layout_workspace.svg"
        )

        window._layout_toggle_btn.click()
        assert window.get_layout_mode() == "workspace"
        assert window._layout_toggle_btn.toolTip() == "切换为经典三栏布局"
        assert str(window._layout_toggle_btn._svg_icon_path).endswith(
            "layout_classic.svg"
        )
        window.deleteLater()
        qapp.processEvents()


class TestMainWindowMinimumSizes:
    """主窗口最小尺寸：按布局模式聚合叶子实测下限（含标题栏/容器边距）。"""

    @staticmethod
    def _build_all(qapp: QApplication) -> MainWindow:
        """构建四区域（不 show），返回可测量的窗口。"""
        window = MainWindow()
        for side in ("selector", "preview", "pool", "info"):
            window._build_panel(side)
        qapp.processEvents()
        return window

    @staticmethod
    def _chrome(window: MainWindow):
        """窗口装饰尺寸（容器边距 + 自绘标题栏高度）。"""
        margins = window._splitter_container.layout().contentsMargins()
        chrome_w = margins.left() + margins.right()
        chrome_h = (
            margins.top()
            + margins.bottom()
            + int(window._title_bar_header.minimumHeight())
        )
        return chrome_w, chrome_h

    def test_workspace_minimums_from_leaf_widgets(
        self, qapp: QApplication
    ) -> None:
        """workspace：预览器最小 640×(360+48)；窗口最小 = 叶子聚合 + 窗口装饰。"""
        from freeassetfilter.ui.layout.main_layout import (
            HANDLE_WIDTH,
            PREVIEW_CHROME_PX,
            WORKSPACE_PREVIEW_MIN_CONTENT_H,
            WORKSPACE_PREVIEW_MIN_CONTENT_W,
        )

        window = self._build_all(qapp)
        try:
            assert window._layout_mode == "workspace"
            # 预览器最小尺寸随模式下发（内容区 640×360 + 顶栏 48）
            assert window._previewer.minimumWidth() == WORKSPACE_PREVIEW_MIN_CONTENT_W
            assert window._previewer.minimumHeight() == (
                WORKSPACE_PREVIEW_MIN_CONTENT_H + PREVIEW_CHROME_PX
            )

            window._apply_leaf_minimums()
            window._apply_window_minimums()

            pool = window._file_pool
            info = window._info_panel
            pool_h = max(pool.minimumHeight(), pool.minimumSizeHint().height())
            info_h = max(info.minimumHeight(), info.minimumSizeHint().height())
            pool_w = max(pool.minimumWidth(), pool.minimumSizeHint().width())
            info_w = max(info.minimumWidth(), info.minimumSizeHint().width())
            selector_w = max(
                window._file_selector.minimumWidth(),
                window._file_selector.minimumSizeHint().width(),
            )
            chrome_w, chrome_h = self._chrome(window)
            layout_min_w = (
                selector_w
                + HANDLE_WIDTH
                + max(
                    WORKSPACE_PREVIEW_MIN_CONTENT_W,
                    pool_w + HANDLE_WIDTH + info_w,
                )
            )
            layout_min_h = (
                WORKSPACE_PREVIEW_MIN_CONTENT_H
                + PREVIEW_CHROME_PX
                + HANDLE_WIDTH
                + max(pool_h, info_h)
            )
            assert window.minimumWidth() == layout_min_w + chrome_w
            assert window.minimumHeight() == layout_min_h + chrome_h
        finally:
            window.deleteLater()
            qapp.processEvents()

    def test_classic_switch_clears_previewer_min_and_sets_min_height(
        self, qapp: QApplication
    ) -> None:
        """切经典：预览器下限清除；窗口最小高覆盖信息区两倍最小高 + 底栏槽位。"""
        from freeassetfilter.ui.layout.main_layout import (
            CLASSIC_ACTION_SLOT_PX,
            HANDLE_WIDTH,
        )

        window = self._build_all(qapp)
        try:
            assert window.set_layout_mode("classic") is True
            qapp.processEvents()
            # 经典：清除预览器显式下限（自然最小），使信息高度范围可完整覆盖
            assert window._previewer.minimumWidth() == 0
            assert window._previewer.minimumHeight() == 0
            # 仅储存池可折叠
            assert window._main_layout.splitters["main"].isCollapsible(1) is True

            window._apply_window_minimums()
            info_h = max(
                window._info_panel.minimumHeight(),
                window._info_panel.minimumSizeHint().height(),
            )
            _chrome_w, chrome_h = self._chrome(window)
            layout_min_h = (
                max(2 * info_h + HANDLE_WIDTH, 0)
                + HANDLE_WIDTH
                + CLASSIC_ACTION_SLOT_PX
            )
            assert window.minimumHeight() >= layout_min_h + chrome_h
        finally:
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
        """已构建全部区域后 closeEvent 仍安全（flush_backup / info 停止受保护）。"""
        window = MainWindow()
        window._build_panel("selector")
        window._build_panel("preview")
        window._build_panel("pool")
        window._build_panel("info")
        window.closeEvent(QCloseEvent())
        window.deleteLater()
        qapp.processEvents()


class TestMainWindowStartupOverlay:
    """启动加载覆盖层：创建契约、撤销钩子与幂等性（不 show 窗口）。"""

    def test_overlay_created_with_content_shell(self, qapp: QApplication) -> None:
        """构造后覆盖层已就绪：不透明遮罩、铺满整个内容层、定时器已建。"""
        window = MainWindow()
        overlay = window._startup_overlay
        assert overlay is not None
        assert overlay.overlay is True
        assert overlay.backdrop == "opaque"
        # 挂在 _content（整个客户区）而非 _splitter_container：实色底才能
        # 覆盖到自绘标题栏所在区域，避免标题栏透出背景层形成断色。
        assert overlay.parentWidget() is window._content
        assert window._title_bar_header is not None
        assert window._startup_overlay_timer is not None
        # 覆盖层不设鼠标穿透：加载期内容区不可点击（标题栏在其上层不受影响）
        assert not overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        window.deleteLater()
        qapp.processEvents()

    def test_dismiss_past_min_display_fades_out(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """已超过最短展示时长时撤销：直接同步淡出并交出动画引用。"""
        window = MainWindow()
        # 把起始时刻挪到过去 → remain_ms <= 0 → 走同步淡出分支（可确定性断言）
        monkeypatch.setattr(window, "_startup_overlay_started_at", 0.0)

        window._dismiss_startup_overlay()

        assert window._startup_overlay is None
        assert window._startup_overlay_animation is not None
        window.deleteLater()
        qapp.processEvents()

    def test_dismiss_within_min_display_defers(
        self, qapp: QApplication
    ) -> None:
        """未到最短展示时长时撤销：只排定补齐定时器，覆盖层仍在。"""
        window = MainWindow()
        # 刚构造 → elapsed 远小于 STARTUP_OVERLAY_MIN_MS
        window._dismiss_startup_overlay()

        assert window._startup_overlay is not None
        assert window._startup_overlay_animation is None
        assert window._startup_overlay_timer.isActive()
        window._startup_overlay_timer.stop()
        window.deleteLater()
        qapp.processEvents()

    def test_fade_out_is_idempotent(self, qapp: QApplication) -> None:
        """连续两次淡出不抛异常（幂等：三栏就绪与兜底超时可能先后到达）。"""
        window = MainWindow()
        window._fade_out_startup_overlay()
        window._fade_out_startup_overlay()
        assert window._startup_overlay is None
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
        # 测试隔离：暂存池恢复涉及磁盘 I/O，一律短路（恢复时机已改为
        # 由 _finalize_panels 在文件池就绪后触发，见 main_window.py）
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


class TestBackgroundModeTransition:
    """背景模式过渡：切前抓帧、切后 450ms 交叉淡入（BackgroundTransitionOverlay）。

    过渡仅在窗口在屏时启用（``_can_transition_background`` 以
    ``_content.isVisible()`` 判定）；本文件约定不 show()，故用例以实例级
    补丁模拟在屏（与 ``TestContentThemeTransition`` 同款）。遮罩层级细节
    （stack_below 压低）由组件测试覆盖，这里断言主窗口集成契约。
    """

    @staticmethod
    def _patch_background_settings(
        monkeypatch: pytest.MonkeyPatch, config: dict
    ) -> None:
        """把 MainWindow._load_background_settings 替换为返回固定配置。"""
        monkeypatch.setattr(
            MainWindow, "_load_background_settings", staticmethod(lambda: config)
        )

    def _make_visible_window(
        self,
        monkeypatch: pytest.MonkeyPatch,
        config: dict | None = None,
    ) -> MainWindow:
        """构造「在屏」主窗口（isVisible 补丁模拟，不弹真实窗口）。"""
        self._patch_background_settings(
            monkeypatch, {"mode": "mica", "image": ""} if config is None else config
        )
        window = MainWindow()
        if window._content is not None:
            monkeypatch.setattr(window._content, "isVisible", lambda: True)
        return window

    @staticmethod
    def _teardown(window: MainWindow, qapp: QApplication) -> None:
        """收尾遮罩并销毁窗口（避免残留定时器跨用例）。"""
        try:
            window._finish_background_transition()
        except Exception:
            pass
        window.deleteLater()
        qapp.processEvents()

    def test_mode_switch_starts_background_transition(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """在屏切换：旧帧淡出遮罩创建（父级 _root），层可见性仍同步翻转。"""
        window = self._make_visible_window(monkeypatch)
        try:
            window.set_background_mode("image")
            overlay = window._background_transition_overlay
            assert overlay is not None
            assert overlay.parent() is window._root
            assert overlay.isVisibleTo(window._root)
            assert overlay.DEFAULT_DURATION_MS == 450
            # 既有语义不变：状态与层可见性同步翻转
            assert window._background_mode == "image"
            assert window._custom_background.isHidden() is False
            assert window._mica_background.isHidden() is True
        finally:
            self._teardown(window, qapp)

    def test_same_mode_does_not_start_transition(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """同模式重复下发：不建遮罩（无变化无需过渡）。"""
        window = self._make_visible_window(monkeypatch)
        try:
            window.set_background_mode("mica")
            assert window._background_transition_overlay is None
        finally:
            self._teardown(window, qapp)

    def test_invisible_window_switches_without_transition(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """窗口不可见（未 show/最小化）：不建遮罩，切换照常完成。"""
        self._patch_background_settings(
            monkeypatch, {"mode": "mica", "image": ""}
        )
        window = MainWindow()
        try:
            window.set_background_mode("image")
            assert window._background_transition_overlay is None
            assert window._background_mode == "image"
            assert window._custom_background.isHidden() is False
            assert window._mica_background.isHidden() is True
        finally:
            self._teardown(window, qapp)

    def test_rapid_switch_replaces_single_overlay(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """连点连切：上一遮罩立即收尾，单实例去重不叠层。"""
        window = self._make_visible_window(monkeypatch)
        try:
            window.set_background_mode("image")
            first = window._background_transition_overlay
            assert first is not None
            window.set_background_mode("minimalist")
            second = window._background_transition_overlay
            assert second is not None and second is not first
            assert first._finished is True, "上一遮罩应立即收尾（去重）"
            assert window._background_mode == "minimalist"
        finally:
            self._teardown(window, qapp)

    def test_capture_failure_does_not_block_switch(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """抓帧失败：跳过过渡但不阻塞切换本身。"""
        window = self._make_visible_window(monkeypatch)
        try:
            monkeypatch.setattr(
                window, "_capture_background_frame", lambda: None
            )
            window.set_background_mode("image")
            assert window._background_transition_overlay is None
            assert window._background_mode == "image"
            assert window._custom_background.isHidden() is False
        finally:
            self._teardown(window, qapp)

    def test_ambient_toggle_in_minimalist_transitions(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """简约模式下切换弥散氛围：同样走交叉淡入。"""
        window = self._make_visible_window(monkeypatch)
        try:
            window.set_background_mode("minimalist")
            window._finish_background_transition()
            assert window._background_transition_overlay is None
            window.set_ambient_enabled(False)
            assert window.is_ambient_enabled() is False
            assert window._background_transition_overlay is not None
        finally:
            self._teardown(window, qapp)

    def test_image_swap_in_image_mode_transitions(
        self,
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """图像模式下更换图片：同样走交叉淡入（云母→图像由模式切换覆盖）。"""
        window = self._make_visible_window(monkeypatch)
        try:
            pm1 = QPixmap(32, 32)
            pm1.fill(QColor(200, 30, 30))
            path1 = str(tmp_path / "one.png")
            assert pm1.save(path1, "PNG")
            pm2 = QPixmap(32, 32)
            pm2.fill(QColor(30, 200, 30))
            path2 = str(tmp_path / "two.png")
            assert pm2.save(path2, "PNG")

            assert window.set_custom_background_image(path1) is True
            window.set_background_mode("image")
            window._finish_background_transition()
            assert window._background_transition_overlay is None

            assert window.set_custom_background_image(path2) is True
            assert window._background_transition_overlay is not None
            assert window._custom_background.image_path == path2
        finally:
            self._teardown(window, qapp)


class TestFixedMicaParams:
    """米卡参数按主题固定：常量值 / 主题取值 / 启动加载 / 构造消费。

    米卡滑动条与原生 DWM 云母开关已移除，参数为产品定值：
    亮色 1×/1×/200px/65%，深色 2×/1×/200px/80%（浅色降饱和降透明，
    避免壁纸色满强度染到整个界面）。
    """

    def test_fixed_params_constant_values(self) -> None:
        """FIXED_MICA_PARAMS 两组定值与产品规格一致。"""
        assert FIXED_MICA_PARAMS["light"] == {
            "blur_radius": 200, "saturation": 1.0,
            "contrast": 1.0, "tint_opacity": 65,
        }
        assert FIXED_MICA_PARAMS["dark"] == {
            "blur_radius": 200, "saturation": 2.0,
            "contrast": 1.0, "tint_opacity": 80,
        }

    def test_fixed_params_follow_theme(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """fixed_mica_params 按当前主题返回对应定值（返回副本）。"""
        import freeassetfilter.ui.main_window as mw_mod

        monkeypatch.setattr(mw_mod.tm, "is_dark_theme", lambda: False)
        assert mw_mod.fixed_mica_params() == FIXED_MICA_PARAMS["light"]
        monkeypatch.setattr(mw_mod.tm, "is_dark_theme", lambda: True)
        dark = mw_mod.fixed_mica_params()
        assert dark == FIXED_MICA_PARAMS["dark"]
        # 返回副本：修改结果不影响常量
        dark["saturation"] = 0.0
        assert FIXED_MICA_PARAMS["dark"]["saturation"] == 2.0

    def test_load_mica_settings_returns_fixed_values(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_load_mica_settings 返回主题定值，不再读取设置文件。"""
        import freeassetfilter.ui.main_window as mw_mod

        def _boom(*_a: Any, **_k: Any) -> None:
            raise AssertionError("参数固定后不得读取 SettingsManagerV2")

        monkeypatch.setattr(
            "freeassetfilter.core.managers.settings_manager_v2."
            "SettingsManagerV2.load",
            _boom,
        )
        monkeypatch.setattr(mw_mod.tm, "is_dark_theme", lambda: True)
        assert MainWindow._load_mica_settings() == FIXED_MICA_PARAMS["dark"]
        monkeypatch.setattr(mw_mod.tm, "is_dark_theme", lambda: False)
        assert MainWindow._load_mica_settings() == FIXED_MICA_PARAMS["light"]

    def test_main_window_consumes_fixed_params(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """MainWindow 构造消费主题定值（参数字段与固定值一致）。

        本文件的 autouse 夹具把 ``_mica_background`` 替换为
        ``_StubMicaBackground``（无 ``_mica`` 属性），因此只断言
        MainWindow 侧消费结果，不触达真实 MicaMaterial。
        """
        import freeassetfilter.ui.main_window as mw_mod

        monkeypatch.setattr(
            MainWindow, "_load_background_settings",
            staticmethod(lambda: {"mode": "mica", "image": ""}),
        )
        monkeypatch.setattr(mw_mod.tm, "is_dark_theme", lambda: True)
        window = MainWindow()
        expected = FIXED_MICA_PARAMS["dark"]
        assert window._blur_radius == expected["blur_radius"]
        assert window._saturation == expected["saturation"]
        assert window._contrast == expected["contrast"]
        assert window._tint_opacity == expected["tint_opacity"]
        window.deleteLater()
        qapp.processEvents()


class TestMicaChainPreload:
    """Mica 依赖链预导入：主线程延迟执行（修复跨线程导入竞态）。

    历史实现启动 ``faf-mica-preload`` daemon 线程导入 numpy/PySide 链，
    在 PySide6 6.10 下与主线程 Qt 事件处理存在原生竞态（进程 Aborted /
    挂死；``test_main_window`` 全文件运行稳定复现）。修复后改为
    ``QTimer.singleShot(0)`` 主线程执行，本类钉住该行为防回归。
    """

    def test_preload_scheduled_without_background_thread(
        self, qapp: QApplication
    ) -> None:
        """initialize_deferred_content 安排预导入但不创建后台线程。"""
        import threading

        window = MainWindow(defer_heavy_init=True)
        before = {t.name for t in threading.enumerate() if t.is_alive()}
        window.initialize_deferred_content()
        assert window._mica_preload_started is True
        qapp.processEvents()
        after = {t.name for t in threading.enumerate() if t.is_alive()}
        assert "faf-mica-preload" not in (after - before)
        # 主线程导入已完成并置位记账（后续刷新请求不再等待）
        assert window._mica_chain_ready is True
        window.deleteLater()
        qapp.processEvents()

    def test_preload_imports_chain_on_main_thread(self, qapp: QApplication) -> None:
        """直接调用预导入：主线程导入完成并置位 ready 记账。"""
        window = MainWindow(defer_heavy_init=True)
        assert window._mica_chain_ready is False
        window._preload_mica_chain()
        assert window._mica_chain_ready is True
        window.deleteLater()
        qapp.processEvents()


class TestMicaBackgroundWidgetCpu:
    """MicaBackgroundWidgetCpu：构造/绘制/交互/主题同步。"""

    def test_construct_and_render(self, qapp: QApplication) -> None:
        """构造 + 真实 paintEvent（render 到 QPixmap）不抛异常。

        材质惰性化：构造后 ``_mica`` 为 None（窗口显示后首轮事件循环才建），
        此期间绘制以当前主题纯色铺底（与材质未烘焙时同色，材质就位后无缝接替）。
        """
        bg = MicaBackgroundWidgetCpu()
        assert bg._mica is None
        assert bg._blur_radius == 200
        bg.resize(320, 200)
        bg.show()
        qapp.processEvents()
        pixmap = QPixmap(320, 200)
        bg.render(pixmap)
        assert not pixmap.isNull()
        bg.deleteLater()
        qapp.processEvents()

    def test_mica_material_lazy_creation(self, qapp: QApplication) -> None:
        """材质惰性创建：_ensure_mica_material 首次建、后续幂等返回同一实例。"""
        bg = MicaBackgroundWidgetCpu()
        assert bg._mica is None
        material = bg._ensure_mica_material()
        assert material is not None
        assert bg._ensure_mica_material() is material
        material.dispose()
        bg.deleteLater()
        qapp.processEvents()

    def test_handle_window_resize_move(self, qapp: QApplication) -> None:
        """窗口拖拽/缩放回调（begin_interaction）不抛异常。"""
        bg = MicaBackgroundWidgetCpu()
        bg.handle_window_resize()
        bg.handle_window_move()
        # 惰性：交互回调本身不触发材质创建
        assert bg._mica is None
        bg.deleteLater()

    def test_sync_theme_and_refresh(self, qapp: QApplication) -> None:
        """主题同步与背景刷新切换纯色背景/luminosity。

        背景为不透明纯色，随主题切换：
        深色 → 纯黑 #000000，浅色 → 纯白 #FFFFFF（不再有灰色调 tint）。
        ``refresh_background`` 语义上需要材质，会惰性创建。
        """
        bg = MicaBackgroundWidgetCpu()
        bg.sync_theme()
        assert bg._surface_color in ("#000000", "#FFFFFF")
        assert len(bg._surface_color) == 7  # 不透明纯色（无 alpha 通道）
        bg.refresh_background()
        assert bg._mica is not None
        bg._mica.dispose()
        bg.deleteLater()

    def test_apply_mica_parameters(self, qapp: QApplication, monkeypatch) -> None:
        """滑动条实时预览入口：参数透传到 mixin 与 MicaMaterial。

        新架构下色彩参数落在 ``MicaMaterial._params``（``MicaParams`` 不可变
        dataclass），叠加层透明度单独存于 ``_overlay_opacity``。本例以
        ``_request_rebuild`` 打桩记录重建调度，避免真正去采壁纸、起后台线程。

        关键行为：
        - 模糊 / 饱和度 / 对比度变化 → 触发一次后台重建（绘制期无法即时生效）；
        - 仅叠加层透明度变化 → 仅绘制期生效，不调度重建。
        """
        bg = MicaBackgroundWidgetCpu(tint_opacity=50)
        # 材质惰性化：参数透传目标需显式创建（生产路径由 _start_mica_refresh 触发）
        material = bg._ensure_mica_material()
        assert material is not None
        # 桩掉重建调度：只记录调用次数，不真正去采壁纸 / 起线程
        rebuild_calls: list = []
        monkeypatch.setattr(material, "_request_rebuild", lambda: rebuild_calls.append(1))
        assert bg._tint_opacity == 50

        bg.apply_mica_parameters(
            blur_radius=120, saturation=2.0, contrast=1.0, tint_opacity=30,
        )
        assert bg._blur_radius == 120
        assert bg._saturation == 2.0
        assert bg._contrast == 1.0
        assert bg._tint_opacity == 30
        # 新架构：参数落在 MicaParams dataclass，叠加层透明度另存
        assert material._params.blur_radius == pytest.approx(120)
        assert material._params.saturation == pytest.approx(2.0)
        assert material._params.contrast == pytest.approx(1.0)
        assert material._overlay_opacity == pytest.approx(0.3)
        # 本次同时改了模糊 / 饱和度 / 对比度，必然调度一次重建
        assert len(rebuild_calls) == 1

        # 仅叠加层透明度变化：绘制期生效，不调度重建
        rebuild_calls.clear()
        bg.apply_mica_parameters(tint_opacity=80)
        assert material._overlay_opacity == pytest.approx(0.8)
        assert rebuild_calls == []

        # 模糊半径变化：调度重建
        rebuild_calls.clear()
        bg.apply_mica_parameters(blur_radius=300)
        assert material._params.blur_radius == pytest.approx(300)
        assert len(rebuild_calls) == 1

        # 对比度变化：同样调度重建
        rebuild_calls.clear()
        bg.apply_mica_parameters(contrast=2.0)
        assert material._params.contrast == pytest.approx(2.0)
        assert len(rebuild_calls) == 1

        bg._mica.dispose()
        bg.deleteLater()

    def test_sync_theme_single_rebake_with_folded_params(
        self, qapp: QApplication, monkeypatch
    ) -> None:
        """主题切换：固定参数折入 set_theme，单次重烘收敛（无双烘链）。

        旧链路 sync_theme = set_theme（R1 起烘）+ apply_mica_parameters
        （R2 作废重烘）= 两次调度；现改为参数在 key 计算前折入 set_theme，
        仅一次 ``_maybe_rebake``。本例先把材质参数拨到「另一主题」的值，
        模拟真实切换时参数必然变化的场景。
        """
        bg = MicaBackgroundWidgetCpu()
        # 材质惰性化：主题切换测试需材质就位（生产路径由 _start_mica_refresh 触发）
        material = bg._ensure_mica_material()
        assert material is not None
        # 模拟「当前材质还是另一主题的参数」：拨一个必然不同的饱和度。
        material._params = material._params.replace(saturation=99.0)
        rebake_calls: list = []
        monkeypatch.setattr(
            material, "_maybe_rebake",
            lambda force=False: rebake_calls.append(force),
        )

        bg.sync_theme()

        fixed = fixed_mica_params()
        assert material._params.saturation == pytest.approx(fixed["saturation"])
        assert material._params.blur_radius == pytest.approx(fixed["blur_radius"])
        assert material._params.contrast == pytest.approx(fixed["contrast"])
        assert material._overlay_opacity == pytest.approx(
            fixed["tint_opacity"] / 100.0
        )
        # 主题 + 参数单次收敛：仅 set_theme 内的一次调度（force=False）。
        assert rebake_calls == [False]

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
        # 材质惰性化：构造后未创建，显式确保后方可重绘（NULL/GPU 路径）
        assert bg._mica is None
        assert bg._ensure_mica_material() is not None
        bg.handle_window_resize()
        bg.handle_window_move()
        assert bg._blur_radius == 200
        bg._mica.dispose()
        bg.deleteLater()
        qapp.processEvents()


class TestMakeMicaBackground:
    """make_mica_background：工厂返回 Mica 背景控件（默认 CPU 回退）。"""

    def test_factory_returns_mica_widget(self, qapp: QApplication) -> None:
        """默认路径返回 CPU 或 GL 版之一，材质由 _ensure_mica_material 惰性建。"""
        bg = make_mica_background()
        assert isinstance(bg, (MicaBackgroundWidgetCpu, MicaBackgroundWidgetGL))
        assert bg._mica is None
        assert bg._ensure_mica_material() is not None
        bg._mica.dispose()
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

    def test_root_background_follows_theme_switch(
        self, qapp: QApplication
    ) -> None:
        """根容器背景随主题真实切换（回归：调色板被 QSS 全树重刷还原）。

        背景由 ``_apply_theme_palette`` 的 ``setPalette`` + QSS 片段共同承载：
        应用级样式表重刷（``QApplication.setStyleSheet``，主题切换链路同步
        执行一次、片段重注册后的合并 tick 再执行一次）会把控件调色板还原为
        「上次应用样式时」的旧主题值。仅靠调色板时「深色 → 浅色」后根容器
        背景仍停留在深色 G1（设置窗口切浅色不生效的直接原因），因此这里走
        真实 ``theme_changed`` 广播 + 有界事件泵，对根容器取样断言双向切换。
        """
        initial_dark = tm.is_dark_theme()
        win = SettingsWindow()  # 不 show：grab() 离屏渲染即可，遵循本文件约定
        try:
            tm.set_theme_mode("dark")
            process_qt_events(qapp, ms=50)
            self._assert_root_background(win, tm.surface)
            # 深色 → 浅色：旧实现（仅调色板）在此停留深色背景。
            tm.set_theme_mode("light")
            process_qt_events(qapp, ms=50)
            self._assert_root_background(win, tm.surface)
        finally:
            while tm.is_dark_theme() is not initial_dark:
                tm.toggle_theme()
            process_qt_events(qapp, ms=0)
            win.deleteLater()
            qapp.processEvents()

    @staticmethod
    def _assert_root_background(win: SettingsWindow, expected: QColor) -> None:
        """断言根容器背景为期望主题色（标题栏透明区 + 侧边栏区域取样）。

        Args:
            win: 设置窗口实例（根容器背景铺满整窗，子控件多为透明/自绘）。
            expected: 期望的 ``tm.surface`` 主题色。

        Raises:
            AssertionError: 任一样点偏离期望色（容差 ±4，跨平台抗锯齿抖动）。
        """
        image = win._root.grab().toImage()
        width, height = image.width(), image.height()
        for x, y in ((width // 2, 10), (60, height // 2)):
            color = image.pixelColor(x, y)
            for channel, got, want in (
                ("R", color.red(), expected.red()),
                ("G", color.green(), expected.green()),
                ("B", color.blue(), expected.blue()),
            ):
                assert abs(want - got) <= 4, (
                    f"根容器背景未随主题切换：取样点 ({x}, {y}) 的 {channel} "
                    f"通道 {got} 偏离期望 {want}（tm.surface={expected.name()}）"
                )


class TestContentThemeTransition:
    """_on_theme_toggle 的内容层过渡（ContentTransitionOverlay 集成）。

    恢复整窗遮罩移除后丢失的「组件渐变过渡」：切前抓内容子树快照，
    切后旧外观淡出。Mica 背景过渡（材质级交叉淡入）不在本测试范围。
    """

    def _make_window(self, monkeypatch: pytest.MonkeyPatch) -> MainWindow:
        """构建可测试的主题切换窗口（隔离持久化与 Mica 广播路径）。

        Args:
            monkeypatch: pytest monkeypatch 夹具。

        Returns:
            MainWindow: 补丁就绪的主窗口实例（未 show）。
        """
        window = MainWindow()
        # 未显示窗口无过渡（isVisible 守卫）——补丁为 True 模拟在屏
        if window._content is not None:
            monkeypatch.setattr(window._content, "isVisible", lambda: True)
        # _StubMicaBackground.sync_theme 为类级 no-op（见替身 docstring），
        # theme_changed 广播路径无需额外补丁。
        # 拦截持久化：SettingsManagerV2.save 默认写真实 data/settings_v2.json
        monkeypatch.setattr(
            "freeassetfilter.core.managers.settings_manager_v2.SettingsManagerV2.save",
            lambda self: None,
        )
        return window

    def _restore_theme(self, initial_dark: bool) -> None:
        """恢复全局主题状态（ThemeManager 不在 reset_singletons 清单）。"""
        while tm.is_dark_theme() is not initial_dark:
            tm.toggle_theme()

    def test_toggle_starts_content_transition(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """主题切换：内容过渡遮罩创建并显示，主题真实翻转。"""
        initial_dark = tm.is_dark_theme()
        window = self._make_window(monkeypatch)
        try:
            window._on_theme_toggle()
            overlay = window._content_theme_overlay
            assert overlay is not None
            assert overlay.parent() is window._content
            # 父级未 show：isVisible 恒 False，断言相对父级的可见性
            assert overlay.isVisibleTo(window._content)
            assert tm.is_dark_theme() is (not initial_dark)
            overlay.finish_now()
            assert not overlay.isVisibleTo(window._content)
        finally:
            self._restore_theme(initial_dark)
            window.deleteLater()
            qapp.processEvents()

    def test_toggle_dedups_previous_overlay(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """快速连续切换：旧遮罩立即结束并被替换，不叠加多层遮罩。"""
        initial_dark = tm.is_dark_theme()
        window = self._make_window(monkeypatch)
        try:
            window._on_theme_toggle()
            first = window._content_theme_overlay
            assert first is not None
            window._on_theme_toggle()
            second = window._content_theme_overlay
            assert second is not None
            assert second is not first
            assert second.isVisibleTo(window._content)
        finally:
            self._restore_theme(initial_dark)
            window.deleteLater()
            qapp.processEvents()

    def test_persist_deferred_save_not_in_click_sync(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """点击同步段不写盘：save 挂起，事件循环推进后落盘。"""
        calls: list[int] = []
        # 直接对单例实例打桩：类级 setattr 对已实例化的单例无效
        # （助手已先建实例，类级补丁不会替换其方法解析结果）。
        settings_manager = self._settings_manager_for_patch(qapp)
        monkeypatch.setattr(settings_manager, "save", lambda: calls.append(1))
        window = self._make_window(monkeypatch)
        try:
            window._persist_theme_state(defer_save=True)
            # 同步段：save 尚未调用（磁盘 IO 已移出点击回调）
            assert calls == []
            # 有界事件泵（嵌套事件循环）：延迟写盘回调在下一次循环推进中执行。
            # 注意：不能用纯 processEvents 轮询——隐藏窗的启动覆盖层动画持续
            # 产生重绘事件，0ms 定时器需要真实事件循环才会被派发。
            process_qt_events(qapp, ms=30)
            assert calls == [1]
        finally:
            window.deleteLater()
            qapp.processEvents()

    def test_persist_deferred_save_dedups_burst(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """连点去重：多次延迟写盘只落最新一次。"""
        calls: list[int] = []
        settings_manager = self._settings_manager_for_patch(qapp)
        monkeypatch.setattr(settings_manager, "save", lambda: calls.append(1))
        window = self._make_window(monkeypatch)
        try:
            window._persist_theme_state(defer_save=True)
            window._persist_theme_state(defer_save=True)
            window._persist_theme_state(defer_save=True)
            process_qt_events(qapp, ms=30)
            # 旧代际跳过，仅最新一次落盘
            assert calls == [1]
        finally:
            window.deleteLater()
            qapp.processEvents()

    @staticmethod
    def _settings_manager_for_patch(qapp: QApplication):
        """返回 _persist_theme_state 将复用的设置管理器实例（供实例级打桩）。"""
        settings_manager = getattr(qapp, "settings_manager", None)
        if settings_manager is None:
            from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2

            settings_manager = SettingsManagerV2()
            settings_manager.load()
            qapp.settings_manager = settings_manager
        return settings_manager

    def test_toggle_radial_origin_from_theme_button(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """过渡为径向揭示：扩散圆心 = 主题按钮中心（内容层坐标）。"""
        initial_dark = tm.is_dark_theme()
        window = self._make_window(monkeypatch)
        captured: dict[str, Any] = {}
        real_overlay = window._content_theme_overlay

        class _SpyContentOverlay:
            """记录构造参数的 ContentTransitionOverlay 替身。"""

            def __init__(
                self, parent: QWidget, snapshot: QPixmap, duration_ms: int = 450,
                origin: QPoint | None = None,
            ) -> None:
                captured["parent"] = parent
                captured["snapshot"] = snapshot
                captured["origin"] = origin
                self._finished = False

            def start(self) -> None:
                captured["started"] = True

            def finish_now(self) -> None:
                self._finished = True

            def isVisibleTo(self, _widget: QWidget) -> bool:
                return True

        monkeypatch.setattr(
            "freeassetfilter.ui.main_window.ContentTransitionOverlay",
            _SpyContentOverlay,
        )
        try:
            window._on_theme_toggle()
            origin = captured.get("origin")
            assert origin is not None
            expected = window._theme_btn.mapTo(
                window._content, window._theme_btn.rect().center()
            )
            assert origin == expected
            # 快照按物理分辨率生成（与控件 DPR 一致，高分屏不糊）
            snapshot = captured["snapshot"]
            assert isinstance(snapshot, QPixmap)
            assert snapshot.devicePixelRatio() == pytest.approx(
                window._content.devicePixelRatioF()
            )
            assert captured.get("started") is True
        finally:
            self._restore_theme(initial_dark)
            window._content_theme_overlay = real_overlay
            window.deleteLater()
            qapp.processEvents()

    def test_theme_toggle_origin_none_without_button(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """主题按钮缺失：扩散圆心退化为 None（遮罩走透明度淡出）。"""
        window = self._make_window(monkeypatch)
        try:
            assert window._theme_toggle_origin(window._content) is not None
            monkeypatch.setattr(window, "_theme_btn", None)
            assert window._theme_toggle_origin(window._content) is None
        finally:
            window.deleteLater()
            qapp.processEvents()

    def test_layout_transition_uses_dissolve(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """布局切换过渡为快照溶解：250ms、Linear、无扩散圆心、不依赖主题按钮。"""
        window = self._make_window(monkeypatch)
        try:
            # 主题按钮缺失也不影响：溶解模式恒不传圆心
            monkeypatch.setattr(window, "_theme_btn", None)
            window.begin_layout_transition()
            overlay = window._content_theme_overlay
            assert overlay is not None
            assert overlay.parent() is window._content
            assert overlay._reveal_center is None, "布局过渡不得走径向揭示"
            assert overlay._duration_ms == overlay.DISSOLVE_DURATION_MS == 250
            assert overlay._easing.type() == QEasingCurve.Linear
            assert overlay.isVisibleTo(window._content)
            overlay.finish_now()
            assert not overlay.isVisibleTo(window._content)
        finally:
            window.deleteLater()
            qapp.processEvents()

    def test_layout_transition_gate_disabled_skips_overlay(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """layout_switch 动画关闭：跳过过渡（不建遮罩、不抛异常）。"""
        window = self._make_window(monkeypatch)
        calls: list[tuple] = []

        def fake_gate(*args, **kwargs):
            calls.append((args, kwargs))
            return False

        monkeypatch.setattr(
            "freeassetfilter.ui.main_window.is_animation_enabled", fake_gate
        )
        try:
            window.begin_layout_transition()
            assert window._content_theme_overlay is None
            assert calls and calls[0][0][0] == "layout_switch"
        finally:
            window.deleteLater()
            qapp.processEvents()

    def test_content_transition_unknown_mode_falls_back_to_fade(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """未知过渡模式：回退为透明度淡出（无圆心、InOutCubic 缓动）。"""
        window = self._make_window(monkeypatch)
        try:
            window._start_content_theme_transition("bogus")
            overlay = window._content_theme_overlay
            assert overlay is not None
            assert overlay._reveal_center is None
            assert overlay._duration_ms == overlay.DEFAULT_DURATION_MS
            assert overlay._easing.type() == QEasingCurve.InOutCubic
            overlay.finish_now()
        finally:
            window.deleteLater()
            qapp.processEvents()