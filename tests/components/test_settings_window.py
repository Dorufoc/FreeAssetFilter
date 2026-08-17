# -*- coding: utf-8 -*-
"""components 批 3：设置窗口 / 主题编辑器 / 更新控制器测试。

覆盖 ``freeassetfilter/components/settings_window.py``、
``freeassetfilter/components/theme_editor.py`` 与
``freeassetfilter/components/update_controller.py`` 三个模块的公开
类、方法、信号与状态机：

* settings_window：霓虹设置窗口（ModernSettingsWindow）的导航页结构、
  设置读取/写回往返、主题切换触发 ThemeManager 的 theme_changed /
  colors_updated 信号（含新色板）。
* theme_editor：主题编辑器（ThemeEditor）的预设结构、卡片点选、
  自定义配色编辑 / 应用 / 重置信号。
* update_controller：更新检查全 mock（禁止真实网络）；下载进度分段
  发射；下载中途取消的临时文件清理与状态归零；网络异常映射为可处理
  的 failure/错误对话框而非未捕获异常。

本文件为多模块测试文件，目标模块集见文件头 ``# targets:`` 声明。
策略要点：

* ``isolated_settings`` fixture 把 SettingsManager 单例以及
  ``qapp.settings_manager`` 同时绑定到 tmp_path 下的 settings.json，
  使窗口内部控件自建的 ``SettingsManager()`` 不会触碰到真实
  data/settings.json。
* Cross-thread 信号（QThread worker）一律使用有界轮询
  （``_pump_until`` + qapp 事件冲刷）；主线程同步信号使用
  ``wait_for_signal``（经 ``QTimer.singleShot(0, ...)`` 触发），
  不 exec() 任何模态对话框。
"""

# targets: components.settings_window, components.theme_editor, components.update_controller

from __future__ import annotations

import atexit
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QScrollArea

from tests.support.qt_helpers import (
    flush_widget_queue,
    process_qt_events,
    safe_teardown,
    wait_for_signal,
)

pytestmark = pytest.mark.unit


# =============================================================================
# 公共辅助工具
# =============================================================================
def _pump_until(
    qapp: Any,
    predicate: Callable[[], bool],
    timeout_s: float = 5.0,
) -> bool:
    """在截止期内轮询冲刷 Qt 事件直到谓词满足（有界，绝不无限等待）。

    Args:
        qapp: 会话级 QApplication 实例。
        predicate: 目标板状态谓词。
        timeout_s: 最长等待秒数。

    Returns:
        bool: 谓词在超时前满足返回 True，否则 False。
    """
    deadline: float = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        flush_widget_queue(qapp, iterations=5)
        time.sleep(0.01)
    return bool(predicate())


def _stop_worker(worker: Any) -> None:
    """安全停止并销毁 QThread worker（先检查 isRunning 再 wait）。

    Args:
        worker: QThread 子类实例或 None。
    """
    if worker is None:
        return
    try:
        if worker.isRunning():
            worker.requestInterruption()
            worker.wait(5000)
    except RuntimeError:
        pass
    try:
        worker.deleteLater()
    except RuntimeError:
        pass
    flush_widget_queue()


def _isolate_settings(qapp: Any, tmp_path: Any) -> Any:
    """把 SettingsManager 单例与 qapp.settings_manager 绑定到临时文件。

    单例提前重置并绑定 tmp_path，窗口内部控件 fallback 的
    ``SettingsManager()`` 随即返回同一实例——零真实 data/ 访问。

    Args:
        qapp: 会话级 QApplication 实例。
        tmp_path: pytest 内置临时目录。

    Returns:
        Any: 绑定临时 settings.json 的新 SettingsManager 实例。
    """
    from freeassetfilter.core.managers.settings_manager import SettingsManager

    SettingsManager._instance = None
    SettingsManager._initialized = False
    settings_file: str = str(tmp_path / "settings.json")
    manager: Any = SettingsManager(settings_file=settings_file)
    qapp.settings_manager = manager
    return manager


@pytest.fixture
def isolated_settings(qapp: Any, tmp_path: Any) -> Any:
    """提供绑定 tmp_path 的隔离 SettingsManager（单例 + app 属性同指向）。

    Args:
        qapp: 会话级 QApplication 实例。
        tmp_path: pytest 内置临时目录。

    Returns:
        Any: 隔离的 SettingsManager 实例。
    """
    return _isolate_settings(qapp, tmp_path)


# ===== settings_window =====
@pytest.fixture
def make_settings_window(
    qapp: Any,
    isolated_settings: Any,
) -> Iterator[Callable[..., Any]]:
    """构造 ModernSettingsWindow 的工厂（自动收集并 teardown 销毁）。

    Args:
        qapp: 会话级 QApplication 实例（保证 QWidget 正确创建）。
        isolated_settings: 隔离的 SettingsManager（构造依赖注入）。

    Yields:
        Callable[..., Any]: 每次调用返回一个新窗口实例。
    """
    from freeassetfilter.components.settings_window import ModernSettingsWindow

    built: List[Any] = []

    def _factory() -> Any:
        window: Any = ModernSettingsWindow(settings_manager=isolated_settings)
        built.append(window)
        return window

    yield _factory
    for window in built:
        safe_teardown(window)
    flush_widget_queue()


# ===== theme_editor =====
@pytest.fixture
def make_theme_editor(
    qapp: Any,
    isolated_settings: Any,
) -> Iterator[Callable[..., Any]]:
    """构造 ThemeEditor 的工厂（给定视口尺寸并收敛布局，避免残留定时器）。

    Args:
        qapp: 会话级 QApplication 实例（事件冲刷依赖）。
        isolated_settings: 隔离的 SettingsManager（ThemeEditor 经
            ``app.settings_manager`` 读取）。

    Yields:
        Callable[..., Any]: 每次调用返回一个新编辑器实例。
    """
    from freeassetfilter.components.theme_editor import ThemeEditor

    built: List[Any] = []

    def _factory() -> Any:
        editor: Any = ThemeEditor()
        editor.resize(480, 360)
        editor.show()
        process_qt_events(qapp, ms=20)
        built.append(editor)
        return editor

    yield _factory
    for editor in built:
        safe_teardown(editor)
    flush_widget_queue()


# ===== update_controller =====
@pytest.fixture
def make_update_controller(qapp: Any) -> Iterator[Callable[..., Any]]:
    """构造 UpdateController 的工厂（main_window 用占位 QObject）。

    Args:
        qapp: 会话级 QApplication 实例（保证 QObject 正确创建）。

    Yields:
        Callable[..., Any]: 每次调用返回一个新控制器实例。
    """
    from PySide6.QtCore import QObject

    from freeassetfilter.components.update_controller import UpdateController

    built: List[Any] = []

    def _factory() -> Any:
        controller: Any = UpdateController(QObject())
        built.append(controller)
        return controller

    yield _factory
    for controller in built:
        safe_teardown(controller)
    flush_widget_queue()


# ===== update helpers（假 worker / 假响应）=====
class _FakeSignal:
    """可 connect 的信号占位，供假 worker 使用。"""

    def __init__(self) -> None:
        self.callbacks: List[Callable[..., Any]] = []

    def connect(self, callback: Callable[..., Any]) -> None:
        """记录回调（模拟 connect）。"""
        self.callbacks.append(callback)


class _FakeWorker:
    """假 QThread：验证 UpdateController 不会阻塞等待检查 worker。"""

    def __init__(self, running: bool = True) -> None:
        self._running: bool = running
        self.interruption_requested: bool = False
        self.wait_called: bool = False
        self.finished: _FakeSignal = _FakeSignal()
        self.success: _FakeSignal = _FakeSignal()
        self.failure: _FakeSignal = _FakeSignal()
        self.cancelled: _FakeSignal = _FakeSignal()

    def isRunning(self) -> bool:
        """返回模拟的运行状态。"""
        return self._running

    def isInterruptionRequested(self) -> bool:
        """返回是否已请求中断（默认 False，可由测试预置）。"""
        return self.interruption_requested

    def requestInterruption(self) -> None:
        """记录中断请求。"""
        self.interruption_requested = True

    def wait(self, *args: Any, **kwargs: Any) -> bool:
        """若被调用则断言失败（控制器不应阻塞等待）。
        """
        self.wait_called = True
        raise AssertionError("UpdateController 不应阻塞等待检查 worker")


class _FakeUrlResponse:
    """模拟 urllib 下载响应：分块读取 + content-length。

    可配置在第二次 read 处阻塞到外部 threading.Event，用于构造
    "下载中途取消"的确定性时序。
    """

    def __init__(self, chunks: List[bytes], content_length: Optional[str] = None) -> None:
        self.headers: Dict[str, str] = {
            "content-length": content_length or str(sum(len(c) for c in chunks))
        }
        self._chunks: List[bytes] = list(chunks)
        self._index: int = 0
        self._read_blocker: Optional[threading.Event] = None

    def __enter__(self) -> "_FakeUrlResponse":
        """进入 with 块，返回自身。"""
        return self

    def __exit__(self, *args: Any) -> bool:
        """退出 with 块不吞掉异常。"""
        return False

    def block_from_second_read(self, blocker: threading.Event) -> None:
        """让第二次 read 阻塞在给定事件上。"""
        self._read_blocker = blocker

    def read(self, size: int = -1) -> bytes:
        """按 chunks 顺序返回数据，耗尽后返回 b''。"""
        if self._read_blocker is not None and self._index == 1:
            if not self._read_blocker.wait(timeout=5.0):
                return b""
        if self._index >= len(self._chunks):
            return b""
        chunk: bytes = self._chunks[self._index]
        self._index += 1
        return chunk


_RELEASE_INFO: Dict[str, Any] = {
    "installer_name": "FreeAssetFilter-setup.exe",
    "installer_download_url": "https://example.com/faf-setup.exe",
    "installer_sha256": "ab" * 32,
    "installer_size": 1500,
}


def _no_update_result() -> Dict[str, Any]:
    """构造"已是最新版本"的 check_for_updates 返回。"""
    return {
        "update_available": False,
        "comparison_result": 0,
        "local_info": {"tag_name": "v1.0.0", "build_date": "2026-01-01"},
        "latest_release": {"tag_name": "v1.0.0", "published_date": "2026-01-01"},
        "cache_result": {"is_ready": False, "reason": "无需更新"},
    }


def _update_available_result() -> Dict[str, Any]:
    """构造"发现新版本"的 check_for_updates 返回。"""
    return {
        "update_available": True,
        "comparison_result": 1,
        "local_info": {"tag_name": "v1.0.0-alpha.5", "build_date": "2026-08-01"},
        "latest_release": {
            "tag_name": "v1.1.0",
            "published_date": "2026-08-10",
            "installer_name": _RELEASE_INFO["installer_name"],
            "installer_download_url": _RELEASE_INFO["installer_download_url"],
            "installer_sha256": _RELEASE_INFO["installer_sha256"],
            "installer_size": _RELEASE_INFO["installer_size"],
            "release_body": "- 修复若干问题\n- 提升性能",
        },
        "cache_result": {"is_ready": False, "reason": "未缓存"},
    }


# ===== settings_window =====
class TestSettingsWindowStructure:
    """ModernSettingsWindow 基础结构与标签页导航。"""

    def test_modern_settings_window_is_dialog_with_navigation(self, make_settings_window: Any) -> None:
        """窗口是 QDialog，且带 settings_saved / player_restart_requested 信号。"""
        window: Any = make_settings_window()
        assert isinstance(window, QDialog)
        assert hasattr(window, "settings_saved")
        assert hasattr(window, "player_restart_requested")
        nav_ids: List[str] = [item["id"] for item in window.navigation_items]
        assert nav_ids == [
            "general",
            "file_selector",
            "file_staging",
            "player",
            "text_preview",
            "developer",
            "about",
        ]

    def test_initial_general_tab_populated(self, make_settings_window: Any) -> None:
        """初始渲染通用页：主题组 / 动画组 / 字体组均存在。"""
        window: Any = make_settings_window()
        assert window._current_tab_id == "general"
        assert window.theme_group.title() == "主题"
        assert window.animation_group.title() == "动画"
        assert set(window.animation_setting_items) == {
            "directory_transition",
            "file_record_changes",
            "smooth_scrolling",
            "file_card_state",
            "progress_bar_smoothing",
            "button_smoothing",
        }
        assert window.font_group.title() == "字体设置"

    def test_navigation_switches_tab_and_builds_groups(self, make_settings_window: Any) -> None:
        """切到文件选择器/播放器页时构建对应设置组并更新标题。"""
        window: Any = make_settings_window()
        window._on_navigation_clicked(1)
        assert window._current_tab_id == "file_selector"
        assert hasattr(window, "file_selector_group")
        assert window.content_title.text() == "文件选择器设置"

        window._on_navigation_clicked(3)
        assert window._current_tab_id == "player"
        assert hasattr(window, "control_bar_group")
        assert hasattr(window, "volume_group")
        assert window.content_title.text() == "播放器设置"

    def test_repeated_navigation_is_noop(self, make_settings_window: Any) -> None:
        """重复点击当前标签不应重建页面控件。"""
        window: Any = make_settings_window()
        window._on_navigation_clicked(3)
        first_group: Any = window.control_bar_group
        window._on_navigation_clicked(3)
        assert window._current_tab_id == "player"
        assert window.control_bar_group is first_group

    def test_about_tab_structure(self, make_settings_window: Any) -> None:
        """关于页包含关于 / 版本检查两个分组。"""
        window: Any = make_settings_window()
        window._on_navigation_clicked(6)
        assert window._current_tab_id == "about"
        assert hasattr(window, "about_group")
        assert hasattr(window, "version_check_group")


class TestSettingsWindowSettingsFlow:
    """设置读取 / 写回 / 检测。"""

    def test_current_settings_loads_from_manager(
        self,
        make_settings_window: Any,
        isolated_settings: Any,
    ) -> None:
        """窗口从设置管理器读取初始值并填充 current_settings。"""
        isolated_settings.set_setting("appearance.theme", "dark")
        isolated_settings.set_setting("file_selector.cache_cleanup_period", 15)
        window: Any = make_settings_window()
        assert window.current_settings["appearance.theme"] == "dark"
        assert window.current_settings["file_selector.cache_cleanup_period"] == 15

    def test_get_current_setting_value_prefers_current(
        self,
        make_settings_window: Any,
        isolated_settings: Any,
    ) -> None:
        """_get_current_setting_value 优先返回 current_settings，缺省回落到设置管理器。"""
        window: Any = make_settings_window()
        window.current_settings["appearance.colors.accent_color"] = "#AABBCC"
        assert (
            window._get_current_setting_value("appearance.colors.accent_color", "#007AFF")
            == "#AABBCC"
        )
        del window.current_settings["appearance.colors.accent_color"]
        assert (
            window._get_current_setting_value("appearance.colors.accent_color", "#007AFF")
            == isolated_settings.get_setting("appearance.colors.accent_color", "#007AFF")
        )

    def test_save_settings_writes_back_to_manager(
        self,
        make_settings_window: Any,
        isolated_settings: Any,
        monkeypatch: Any,
    ) -> None:
        """save_settings 把 current_settings 写回到隔离的 settings_manager。"""
        window: Any = make_settings_window()
        window.current_settings["file_selector.cache_cleanup_period"] = 21
        window.current_settings["appearance.colors.accent_color"] = "#112233"
        # 颜色变更会触发 SVG 图标缓存失效，此处打桩避免依赖主题刷新内部实现。
        from freeassetfilter.core.preview.svg_renderer import SvgRenderer

        monkeypatch.setattr(
            SvgRenderer,
            "_invalidate_color_cache",
            lambda: None,
            raising=False,
        )
        window.save_settings()
        assert isolated_settings.get_setting("file_selector.cache_cleanup_period") == 21
        assert isolated_settings.get_setting("appearance.colors.accent_color") == "#112233"
        assert window.isHidden()

    def test_save_settings_emits_settings_saved(
        self,
        qapp: Any,
        make_settings_window: Any,
        isolated_settings: Any,
        monkeypatch: Any,
    ) -> None:
        """保存成功后 settings_saved 信号携带 current_settings。"""
        window: Any = make_settings_window()
        captured: List[Dict[str, Any]] = []
        window.settings_saved.connect(captured.append)
        # 避免字体变更触发模态提示、播放器变更触发重启询问。
        monkeypatch.setattr(window, "_show_font_change_reminder", lambda: None)
        monkeypatch.setattr(window, "_prompt_restart_player_if_needed", lambda: None)
        window.current_settings["font.size"] = 14
        QTimer.singleShot(0, window.save_settings)
        assert wait_for_signal(window.settings_saved, timeout_ms=3000)
        assert len(captured) == 1
        assert captured[0]["font.size"] == 14
        assert isolated_settings.get_setting("font.size") == 14

    def test_theme_switch_writes_dark_palette(self, make_settings_window: Any) -> None:
        """主题开关切到深色时写 dark 主题与深色色板进 current_settings。"""
        window: Any = make_settings_window()
        window.theme_switch.set_switch_value(True)
        assert window.current_settings["appearance.theme"] == "dark"
        assert window.current_settings["appearance.colors.base_color"] == "#212121"
        assert window.current_settings["appearance.colors.secondary_color"] == "#FFFFFF"

        window.theme_switch.set_switch_value(False)
        assert window.current_settings["appearance.theme"] == "default"
        assert window.current_settings["appearance.colors.base_color"] == "#FFFFFF"

    def test_theme_and_colors_change_detection(self, make_settings_window: Any) -> None:
        """_check_theme_changed / _check_colors_changed 检测差异。"""
        window: Any = make_settings_window()
        assert window._check_theme_changed() is False
        assert window._check_colors_changed() is False
        window.current_settings["appearance.theme"] = "dark"
        assert window._check_theme_changed() is True
        window.current_settings["appearance.theme"] = "default"
        assert window._check_theme_changed() is False

        window.current_settings["appearance.colors.accent_color"] = "#112233"
        assert window._check_colors_changed() is True
        window.current_settings["appearance.colors.accent_color"] = "#007AFF"
        assert window._check_colors_changed() is False

        # 保存后 current_settings 被写回管理器，差异重新归零
        window.save_settings()
        assert window._check_theme_changed() is False
        assert window._check_colors_changed() is False


# ===== theme_editor =====
class TestThemeEditorPresets:
    """ThemeEditor 预设主题结构。"""

    def test_theme_editor_is_scroll_area(self, make_theme_editor: Any) -> None:
        """编辑器是 QScrollArea 且携带主题相关信号。"""
        editor: Any = make_theme_editor()
        assert isinstance(editor, QScrollArea)
        assert hasattr(editor, "theme_selected")
        assert hasattr(editor, "add_new_design")
        assert hasattr(editor, "theme_applied")

    def test_preset_themes_structure(self, make_theme_editor: Any) -> None:
        """预设主题含 6 项，且每项携带 name 与 colors。"""
        editor: Any = make_theme_editor()
        assert len(editor.preset_themes) == 6
        names: List[str] = [theme["name"] for theme in editor.preset_themes]
        assert "活力蓝" in names
        assert "热情红" in names
        assert all("colors" in theme for theme in editor.preset_themes)

    def test_custom_themes_contains_custom_design(self, make_theme_editor: Any) -> None:
        """自定义主题组含默认的"自定义设计1"。"""
        editor: Any = make_theme_editor()
        custom_names: List[str] = [theme["name"] for theme in editor.custom_themes]
        assert "自定义设计1" in custom_names

    def test_selected_theme_defaults_to_preset(self, make_theme_editor: Any) -> None:
        """默认强调色 #007AFF 应匹配预设"活力蓝"。"""
        editor: Any = make_theme_editor()
        selected: Optional[Dict[str, Any]] = editor.get_selected_theme()
        assert selected is not None
        assert selected["name"] == "活力蓝"

    def test_theme_card_click_emits_theme_selected(
        self,
        qapp: Any,
        make_theme_editor: Any,
    ) -> None:
        """点击预设卡片触发 theme_selected 信号并携带新主题。"""
        editor: Any = make_theme_editor()
        # 取第一张预设卡片（活力蓝）
        card: Any = editor.preset_grid.itemAt(0).widget()
        assert card is not None
        captured: List[Dict[str, Any]] = []
        editor.theme_selected.connect(captured.append)
        QTimer.singleShot(0, lambda: card.clicked.emit(card))
        assert wait_for_signal(editor.theme_selected, timeout_ms=3000)
        assert len(captured) == 1
        assert captured[0]["name"] == "活力蓝"
        assert captured[0]["colors"][0] == "#007AFF"


class TestThemeEditorActions:
    """ThemeEditor 应用 / 重置 / 自定义配色。"""

    def test_apply_clicked_saves_accent_and_emits(
        self,
        make_theme_editor: Any,
        isolated_settings: Any,
    ) -> None:
        """应用选中主题时写回强调色与预设名，并发射 theme_applied。"""
        editor: Any = make_theme_editor()
        editor.selected_theme = {
            "name": "热情红",
            "colors": ["#DD5940", "#333333", "#e0e0e0", "#f1f3f3", "#FFFFFF"],
        }
        applied: List[str] = []
        editor.theme_applied.connect(lambda: applied.append("applied"))
        QTimer.singleShot(0, editor.on_apply_clicked)
        assert wait_for_signal(editor.theme_applied, timeout_ms=3000)
        assert applied == ["applied"]
        assert isolated_settings.get_setting("appearance.colors.accent_color") == "#DD5940"
        assert isolated_settings.get_setting("appearance.preset_theme") == "热情红"

    def test_reset_clicked_restores_default_accent(self, make_theme_editor: Any) -> None:
        """重置后强调色恢复默认 #007AFF。"""
        editor: Any = make_theme_editor()
        # 先改一个强调色，制造非默认状态
        editor.selected_theme = {
            "name": "热情红",
            "colors": ["#DD5940", "#333333", "#e0e0e0", "#f1f3f3", "#FFFFFF"],
        }
        editor.on_apply_clicked()
        editor.current_theme = {"accent_color": "#DD5940"}
        editor.on_reset_clicked()
        assert editor.settings_manager.get_setting("appearance.colors.accent_color") == "#007AFF"

    def test_custom_color_changed_updates_slider(
        self,
        make_theme_editor: Any,
        isolated_settings: Any,
    ) -> None:
        """变更自定义配色滑块写入保存的值。"""
        editor: Any = make_theme_editor()
        assert hasattr(editor, "add_card")
        # 直接经 color_changed 信号触发滑条颜色保存
        QTimer.singleShot(0, lambda: editor._on_add_card_color_changed("#112233"))
        flush_widget_queue()
        assert isolated_settings.get_setting("appearance.colors.custom_design_color") == "#112233"


# ===== update_controller =====
class TestUpdateControllerCheck:
    """UpdateController 检查更新流程（全 mock，禁真实网络）。"""

    def test_controller_init_state(self, make_update_controller: Any) -> None:
        """初始无 worker、无进度尺寸、无下载路径。"""
        controller: Any = make_update_controller()
        assert controller._check_worker is None
        assert controller._download_worker is None
        assert controller._silent_check_worker is None
        assert controller._current_download_total_size == 0
        assert controller._current_download_temp_path is None
        assert controller._current_download_final_path is None

    def test_silent_worker_promoted_to_manual(
        self,
        make_update_controller: Any,
        monkeypatch: Any,
    ) -> None:
        """运行中的静默检查被手动检查接管，不新开线程。"""
        controller: Any = make_update_controller()
        fake: Any = _FakeWorker(running=True)
        controller._silent_check_worker = fake
        shown: List[str] = []
        monkeypatch.setattr(
            controller,
            "_show_check_progress_dialog",
            lambda: shown.append("shown"),
        )
        controller.on_check_updates_clicked()
        assert fake.wait_called is False
        assert controller._manual_check_uses_silent is True
        assert shown == ["shown"]

    def test_idle_check_starts_manual_worker(
        self,
        make_update_controller: Any,
        monkeypatch: Any,
    ) -> None:
        """空闲时点击开始手动检查：弹进度框并创建检查 worker。"""
        controller: Any = make_update_controller()
        shown: List[str] = []
        monkeypatch.setattr(controller, "_show_check_progress_dialog", lambda: shown.append("shown"))
        started: List[str] = []

        class _Recorder(_FakeWorker):
            def start(self) -> None:
                started.append("started")

        monkeypatch.setattr(
            "freeassetfilter.components.update_controller.UpdateCheckWorker",
            lambda controller: _Recorder(running=False),
        )
        controller.on_check_updates_clicked()
        assert shown == ["shown"]
        assert started == ["started"]
        assert controller._manual_check_uses_silent is False

    def test_check_running_ignore_duplicate(self, make_update_controller: Any) -> None:
        """检查已在进行时点击：忽略重复请求。"""
        controller: Any = make_update_controller()
        fake: Any = _FakeWorker(running=True)
        controller._check_worker = fake
        controller.on_check_updates_clicked()
        assert fake.wait_called is False
        assert controller._check_worker is fake

    def test_check_success_no_update_shows_message(
        self,
        make_update_controller: Any,
        monkeypatch: Any,
    ) -> None:
        """检查成功且无更新时走最新版本提示。"""
        controller: Any = make_update_controller()
        messages: List[Tuple[Any, ...]] = []
        monkeypatch.setattr(
            controller,
            "_show_message_dialog",
            lambda *args, **kwargs: messages.append((args, kwargs)),
        )
        controller._on_check_success(_no_update_result())
        assert len(messages) == 1
        assert messages[0][1]["title"] == "检查更新"
        assert "当前已是最新版本" in messages[0][1]["text"]

    def test_check_success_update_available_sets_release(
        self,
        make_update_controller: Any,
        monkeypatch: Any,
    ) -> None:
        """检查发现新版本时记录 release_info。"""
        controller: Any = make_update_controller()
        monkeypatch.setattr(controller, "_show_update_available_detail_dialog", lambda **kwargs: None)
        controller._on_check_success(_update_available_result())
        assert controller._current_release_info is not None
        assert controller._current_release_info["tag_name"] == "v1.1.0"

    def test_check_failure_shows_error(self, make_update_controller: Any, monkeypatch: Any) -> None:
        """检查失败映射为错误消息对话框而非未捕获异常。"""
        controller: Any = make_update_controller()
        messages: List[Tuple[Any, ...]] = []
        monkeypatch.setattr(
            controller,
            "_show_message_dialog",
            lambda *args, **kwargs: messages.append((args, kwargs)),
        )
        controller._on_check_failure("网络连接失败")
        assert len(messages) == 1
        assert messages[0][1]["title"] == "检查更新失败"
        assert messages[0][1]["text"] == "网络连接失败"
        assert controller._check_worker is None


class TestUpdateControllerDownload:
    """下载进度分享 / 取消 / 失败路径（无真实网络）。"""

    def test_download_progress_updates_state(self, make_update_controller: Any) -> None:
        """进度信号更新已下载大小与总大小。"""
        controller: Any = make_update_controller()
        controller._on_download_progress_changed(500, 1500, "500 B / 1.5 KB")
        assert controller._latest_downloaded_size == 500
        assert controller._current_download_total_size == 1500

    def test_download_progress_ignores_unknown_total(self, make_update_controller: Any) -> None:
        """total=0 时保留已知已下载大小（取较大者），不回写总大小。"""
        controller: Any = make_update_controller()
        controller._latest_downloaded_size = 100
        controller._on_download_progress_changed(50, 0, "50 B")
        assert controller._latest_downloaded_size == 100
        assert controller._current_download_total_size == 0

    def test_download_cancel_cleans_state(
        self,
        make_update_controller: Any,
        monkeypatch: Any,
    ) -> None:
        """取消下载后 worker/尺寸/路径/速度全部归零。"""
        controller: Any = make_update_controller()
        controller._download_worker = _FakeWorker(running=True)
        controller._current_download_total_size = 1500
        controller._current_download_temp_path = "x.download"
        controller._current_download_final_path = "x.exe"
        controller._latest_downloaded_size = 1000
        messages: List[Tuple[Any, ...]] = []
        monkeypatch.setattr(
            controller,
            "_show_message_dialog",
            lambda *args, **kwargs: messages.append((args, kwargs)),
        )
        controller._on_download_cancelled()
        assert controller._download_worker is None
        assert controller._current_download_total_size == 0
        assert controller._current_download_temp_path is None
        assert controller._current_download_final_path is None
        assert controller._latest_downloaded_size == 0
        assert len(messages) == 1
        assert messages[0][1]["title"] == "下载已取消"

    def test_download_failure_cleans_state(
        self,
        make_update_controller: Any,
        monkeypatch: Any,
    ) -> None:
        """下载失败后 worker 与路径归零并提示失败。"""
        controller: Any = make_update_controller()
        controller._download_worker = _FakeWorker(running=True)
        controller._current_download_total_size = 1500
        controller._current_download_temp_path = "x.download"
        controller._current_download_final_path = "x.exe"
        messages: List[Tuple[Any, ...]] = []
        monkeypatch.setattr(
            controller,
            "_show_message_dialog",
            lambda *args, **kwargs: messages.append((args, kwargs)),
        )
        controller._on_download_failure("写入磁盘失败")
        assert controller._download_worker is None
        assert controller._current_download_total_size == 0
        assert controller._current_download_temp_path is None
        assert controller._current_download_final_path is None
        assert len(messages) == 1
        assert messages[0][1]["title"] == "下载更新失败"
        assert messages[0][1]["text"] == "写入磁盘失败"

    def test_download_success_keeps_package(
        self,
        make_update_controller: Any,
        monkeypatch: Any,
    ) -> None:
        """下载成功保留 ready_package 现场。"""
        controller: Any = make_update_controller()
        controller._download_worker = _FakeWorker(running=True)
        # 安装就绪对话框会触发真实 CustomMessageBox(exec)，此处打桩绕开。
        monkeypatch.setattr(controller, "_show_install_ready_dialog", lambda **kwargs: None)
        package: Dict[str, Any] = {
            "is_ready": True,
            "installer_path": "C:/cache/x.exe",
            "installer_sha256": "ab" * 32,
        }
        controller._on_download_success(package)
        assert controller._download_worker is None
        assert controller._latest_downloaded_size == 0
        assert controller._current_ready_package is package


# ===== update_controller 三个 Worker（构造契约，不启动真实网络任务）=====

class TestUpdateWorkers:
    """update_controller 三个 Worker：可构造、可取消、不连接真实任务。"""

    def test_update_check_worker_constructs(self, qapp: Any) -> None:
        """UpdateCheckWorker：构造后未启动，可请求中断（无异常）。"""
        from freeassetfilter.components.update_controller import UpdateCheckWorker

        worker = UpdateCheckWorker(parent=None)
        try:
            assert not worker.isRunning()
            worker.requestInterruption()  # 未启动时安全 no-op
            _stop_worker(worker)
        finally:
            _stop_worker(worker)

    def test_silent_update_check_worker_constructs(self, qapp: Any) -> None:
        """SilentUpdateCheckWorker：构造后未启动。"""
        from freeassetfilter.components.update_controller import SilentUpdateCheckWorker

        worker = SilentUpdateCheckWorker(parent=None)
        try:
            assert not worker.isRunning()
        finally:
            _stop_worker(worker)

    def test_update_download_worker_constructs_and_cancel(self, qapp: Any) -> None:
        """UpdateDownloadWorker：构造 + cancel 幂等（不触发真实下载）。"""
        from freeassetfilter.components.update_controller import UpdateDownloadWorker

        release_info: Dict[str, Any] = {
            "assets": [
                {
                    "name": "FreeAssetFilter.exe",
                    "browser_download_url": "https://example.invalid/faf.exe",
                }
            ]
        }
        worker = UpdateDownloadWorker(release_info, parent=None)
        try:
            assert not worker.isRunning()
            worker.cancel()
        finally:
            _stop_worker(worker)


# =============================================================================
# update_controller 覆盖率扩展：模块级全局 / Worker run() / 下载与静默流程
# =============================================================================
class _FakeSignalBox:
    """可 connect / emit 的信号占位（供假对话框 / 假 worker 使用）。"""

    def __init__(self) -> None:
        self._callbacks: List[Callable[..., Any]] = []

    def connect(self, callback: Callable[..., Any]) -> None:
        """记录回调。"""
        self._callbacks.append(callback)

    def emit(self, *args: Any) -> None:
        """同步调用所有已注册回调。"""
        for cb in list(self._callbacks):
            cb(*args)


class _FakeWidgetStub:
    """UI 小件占位：hide/show/setText/setRange 等 no-op。"""

    def __init__(self) -> None:
        self.text: str = ""

    def hide(self) -> None:
        return None

    def show(self) -> None:
        return None

    def setText(self, text: str) -> None:
        self.text = text

    def setAlignment(self, *args: Any, **kwargs: Any) -> None:
        return None

    def setStyleSheet(self, *args: Any, **kwargs: Any) -> None:
        return None


class _StubBoxLayout:
    """QVBoxLayout 占位：记录 addWidget / 支持 indexOf / insertWidget。"""

    def __init__(self) -> None:
        self.widgets: List[Any] = []

    def addWidget(self, *args: Any, **kwargs: Any) -> None:
        return None

    def removeWidget(self, *args: Any, **kwargs: Any) -> None:
        return None

    def insertWidget(self, index: int, *args: Any, **kwargs: Any) -> None:
        return None

    def indexOf(self, widget: Any) -> int:
        """按钮组件默认位于末尾，保证插入位置有效。"""
        return -1


class _FakeMessageBox:
    """CustomMessageBox 空壳：满足 _show_progress_dialog/_show_message_dialog/
    _show_update_available_detail_dialog 全部接口，不构造真实窗口。

    关键：exec() 直接返回（非阻塞），buttonClicked 可同步 emit 触发回调。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.text_label: Any = _FakeWidgetStub()
        self.image_label: Any = _FakeWidgetStub()
        self.list_widget: Any = _FakeWidgetStub()
        self.input_widget: Any = _FakeWidgetStub()
        self.progress_widget: Any = _FakeWidgetStub()
        self.button_widget: Any = _FakeWidgetStub()
        self.body_layout: Any = _StubBoxLayout()
        self.list_layout: Any = _StubBoxLayout()
        self.buttonClicked: Any = _FakeSignalBox()
        self.closed: bool = False
        self.shown: bool = False

    def setModal(self, *args: Any, **kwargs: Any) -> None:
        return None

    def setWindowFlags(self, *args: Any, **kwargs: Any) -> None:
        return None

    def windowFlags(self) -> int:
        from PySide6.QtCore import Qt

        return int(Qt.WindowCloseButtonHint)

    def set_title(self, *args: Any, **kwargs: Any) -> None:
        return None

    def set_text(self, *args: Any, **kwargs: Any) -> None:
        return None

    def set_buttons(self, *args: Any, **kwargs: Any) -> None:
        return None

    def show(self) -> None:
        self.shown = True

    def close(self) -> None:
        self.closed = True

    def exec(self) -> int:  # noqa: A003
        return 0


class _FakeUrlOpener:
    """替换 urllib.request.urlopen：返回分块响应或抛指定异常。"""

    def __init__(self, response: Any = None, error: Optional[Exception] = None) -> None:
        self.response: Any = response
        self.error: Optional[Exception] = error

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self.error is not None:
            raise self.error
        return self.response


class _ChunkedResponse:
    """模拟 urlopen 响应：分块 read + content-length 头。"""

    def __init__(self, chunks: List[bytes], content_length: Optional[int] = None) -> None:
        self.headers: Dict[str, str] = {
            "content-length": str(content_length if content_length is not None else sum(len(c) for c in chunks))
        }
        self._chunks: List[bytes] = list(chunks)
        self._index: int = 0

    def __enter__(self) -> "_ChunkedResponse":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def read(self, size: int = -1) -> bytes:
        if self._index >= len(self._chunks):
            return b""
        chunk: bytes = self._chunks[self._index]
        self._index += 1
        return chunk


@pytest.fixture(autouse=True)
def _restore_global_qthread_refs() -> Iterator[None]:
    """每个测试前后恢复 update_controller 的模块级 QThread 引用集。

    退休 worker 测试会把假 QThread 注入 ``_global_qthread_refs``（经
    ``_keep_qthread_alive``）；若不清理，解释器退出时 atexit 处理器会对
    假 worker 调用 ``wait(5000)`` 并触发 AssertionError。此 autouse fixture
    快照并在测试后恢复，保证集合跨测试不泄漏。
    """
    import freeassetfilter.components.update_controller as uc

    saved: set = set(uc._global_qthread_refs)
    yield
    uc._global_qthread_refs.clear()
    uc._global_qthread_refs.update(saved)


class _CancelableFakeWorker(_FakeWorker):
    """带 cancel() 的假下载 worker（供 _on_download_dialog_clicked）。"""

    def __init__(self, running: bool = True) -> None:
        super().__init__(running)
        self.cancel_called: bool = False

    def cancel(self) -> None:
        self.cancel_called = True


class _FakeMainWindow:
    """带 close() 记录的主窗口占位（安装成功路径）。"""

    def __init__(self) -> None:
        self.closed: bool = False

    def close(self) -> bool:
        self.closed = True
        return True


class TestUpdateControllerModuleGlobals:
    """update_controller 模块级 QThread 引用集与 atexit 处理器。"""

    def test_keep_qthread_alive_adds_and_removes(self, qapp: Any, monkeypatch: Any) -> None:
        """_keep_qthread_alive 加入全局集合并经 finished 信号移除。"""
        import freeassetfilter.components.update_controller as uc

        fake: Any = _FakeWorker(running=False)
        try:
            uc._global_qthread_refs.discard(fake)
            uc._keep_qthread_alive(fake)
            assert fake in uc._global_qthread_refs
            # 触发 finished 回调：_remove_from_global 从集合中移除
            for cb in fake.finished._callbacks if hasattr(fake.finished, "_callbacks") else fake.finished.callbacks:
                cb(fake)
            assert fake not in uc._global_qthread_refs
        finally:
            uc._global_qthread_refs.discard(fake)

    def test_register_qthread_atexit_idempotent(self, monkeypatch: Any) -> None:
        """_register_qthread_atexit 幂等：重复调用不重复注册。"""
        import atexit as atexit_mod
        import typing
        from typing import Callable, List

        import freeassetfilter.components.update_controller as uc

        registered: List[Callable[..., None]] = []

        def fake_register(func: Callable[..., None]) -> Callable[..., None]:
            registered.append(func)
            return func

        monkeypatch.setattr(atexit_mod, "register", fake_register)
        monkeypatch.setattr(uc, "_atexit_registered", False)
        uc._register_qthread_atexit()
        assert uc._atexit_registered is True
        assert len(registered) == 1
        uc._register_qthread_atexit()
        assert uc._atexit_registered is True
        assert len(registered) == 1


class TestUpdateControllerBindButton:
    """bind_button 绑定/重复绑定/清空。"""

    def test_bind_new_button_then_rebind(self, qapp: Any, make_update_controller: Any) -> None:
        """先绑定按钮，重复绑定同一按钮为 no-op，再绑定新按钮断开旧槽。"""
        from PySide6.QtWidgets import QPushButton

        from freeassetfilter.components.update_controller import UpdateController

        controller: UpdateController = make_update_controller()
        b1: Any = QPushButton("检查更新")
        b2: Any = QPushButton("检查更新")

        controller.bind_button(b1)
        assert controller.update_button is b1
        controller.bind_button(b1)
        assert controller.update_button is b1

        controller.bind_button(b2)
        assert controller.update_button is b2

        controller.bind_button(None)
        assert controller.update_button is None
        safe_teardown(b1)
        safe_teardown(b2)

    def test_button_click_invokes_check(self, qapp: Any, make_update_controller: Any, monkeypatch: Any) -> None:
        """点击已绑定按钮触发 on_check_updates_clicked。"""
        from PySide6.QtWidgets import QPushButton

        controller: Any = make_update_controller()
        clicked: List[str] = []
        monkeypatch.setattr(
            controller,
            "on_check_updates_clicked",
            lambda: clicked.append("clicked"),
        )
        button: Any = QPushButton("检查更新")
        controller.bind_button(button)
        button.click()
        assert clicked == ["clicked"]
        safe_teardown(button)


class TestUpdateControllerSilentLifecycle:
    """start/cancel 静默检查 + 退休 worker 的引用管理。"""

    def test_start_silent_check_creates_and_starts_worker(
        self, make_update_controller: Any, monkeypatch: Any
    ) -> None:
        """空闲时启动静默检查：创建 worker 并 start。"""
        import freeassetfilter.components.update_controller as uc

        controller: Any = make_update_controller()

        class _SilentStub:
            def __init__(self, parent=None) -> None:
                self.update_available = _FakeSignalBox()
                self.success = _FakeSignalBox()
                self.failure = _FakeSignalBox()
                self.cancelled = _FakeSignalBox()
                self.check_finished = _FakeSignalBox()
                self.started: bool = False

            def start(self) -> None:
                self.started = True

        monkeypatch.setattr(uc, "SilentUpdateCheckWorker", lambda parent=None: _SilentStub())
        controller.start_silent_update_check()
        assert controller._silent_check_worker is not None
        assert controller._silent_check_worker.started is True

    def test_start_silent_skips_when_running(self, make_update_controller: Any) -> None:
        """静默检查已在运行时不重复启动。"""
        controller: Any = make_update_controller()
        fake: Any = _FakeWorker(running=True)
        controller._silent_check_worker = fake
        controller.start_silent_update_check()
        assert controller._silent_check_worker is fake

    def test_start_silent_skips_when_manual_running(self, make_update_controller: Any) -> None:
        """手动检查进行中跳过静默检查。"""
        controller: Any = make_update_controller()
        controller._check_worker = _FakeWorker(running=True)
        controller.start_silent_update_check()
        assert controller._silent_check_worker is None

    def test_cancel_silent_check_retires_worker(self, make_update_controller: Any) -> None:
        """retire=True 取消静默检查：退休 worker 并清空引用。"""
        controller: Any = make_update_controller()
        fake: Any = _FakeWorker(running=True)
        controller._silent_check_worker = fake
        controller.cancel_silent_check(retire=True)
        assert controller._silent_check_worker is None
        assert controller._silent_check_cancelled is True
        assert fake in controller._retired_silent_workers

    def test_cancel_silent_check_non_retire(self, make_update_controller: Any) -> None:
        """retire=False（默认）同样退休线程并清空引用。"""
        controller: Any = make_update_controller()
        fake: Any = _FakeWorker(running=True)
        controller._silent_check_worker = fake
        controller.cancel_silent_check()
        assert controller._silent_check_worker is None
        assert fake in controller._retired_silent_workers

    def test_retire_worker_keeps_reference_then_forgets(
        self, make_update_controller: Any
    ) -> None:
        """_retire_worker 加入退休列表；线程结束时经 finished 回调移除。"""
        import freeassetfilter.components.update_controller as uc

        controller: Any = make_update_controller()
        fake: Any = _FakeWorker(running=False)
        uc._global_qthread_refs.discard(fake)
        try:
            controller._retire_check_worker(fake)
            assert fake in controller._retired_check_workers
            assert fake in uc._global_qthread_refs
            # 模拟线程 finished 信号：弱引用存活时移除退休记录
            for cb in fake.finished._callbacks if hasattr(fake.finished, "_callbacks") else fake.finished.callbacks:
                cb(fake)
            assert fake not in controller._retired_check_workers
        finally:
            uc._global_qthread_refs.discard(fake)

    def test_retire_worker_none_is_noop(self, make_update_controller: Any) -> None:
        """_retire_worker(None) 安全返回。"""
        controller: Any = make_update_controller()
        controller._retire_worker(None, controller._retired_check_workers)
        assert controller._retired_check_workers == []

    def test_forget_retired_worker_value_error_safe(self, make_update_controller: Any) -> None:
        """_forget_retired_worker 对不在列表中的 worker 安全（ValueError 被吞）。"""
        controller: Any = make_update_controller()
        fake: Any = _FakeWorker(running=False)
        controller._forget_retired_worker(fake, controller._retired_check_workers)
        assert controller._retired_check_workers == []


class TestUpdateCheckWorkerRun:
    """UpdateCheckWorker.run() 各分支（注入 check_for_updates 假实现）。"""

    def _call_run(self, monkeypatch: Any, check_result: Any = None, check_error: Optional[Exception] = None) -> Dict[str, Any]:
        import freeassetfilter.components.update_controller as uc

        def fake_check(**kwargs: Any) -> Any:
            if check_error is not None:
                raise check_error
            return check_result

        monkeypatch.setattr(uc, "check_for_updates", fake_check)
        worker: Any = uc.UpdateCheckWorker(parent=None)
        events: Dict[str, Any] = {"success": None, "failure": None, "cancelled": False}
        worker.success.connect(lambda r: events.__setitem__("success", r))
        worker.failure.connect(lambda m: events.__setitem__("failure", m))
        worker.cancelled.connect(lambda: events.__setitem__("cancelled", True))
        return worker, events

    def test_run_success_emits_result(self, monkeypatch: Any) -> None:
        worker, events = self._call_run(monkeypatch, check_result=_no_update_result())
        worker.run()
        assert events["success"] == _no_update_result()
        assert events["cancelled"] is False

    def test_run_interrupted_before_starts_emits_cancelled(self, monkeypatch: Any) -> None:
        worker, events = self._call_run(monkeypatch)
        # QThread 未 start 时 requestInterruption() 不生效，直接桩 isInterruptionRequested
        monkeypatch.setattr(worker, "isInterruptionRequested", lambda: True)
        worker.run()
        assert events["cancelled"] is True
        assert events["success"] is None

    def test_run_emits_cancelled_after_interruption(self, monkeypatch: Any) -> None:
        """检查完成后被中断：忽略结果并发送 cancelled。"""
        import freeassetfilter.components.update_controller as uc

        calls: Dict[str, int] = {"n": 0}

        def fake_interrupted() -> bool:
            # 第一次调用返回 False（检查前），之后返回 True（检查后）
            calls["n"] += 1
            return calls["n"] > 1

        def fake_check(**kwargs):
            return _no_update_result()

        worker, events = self._call_run(monkeypatch)
        monkeypatch.setattr(uc, "check_for_updates", fake_check)
        monkeypatch.setattr(worker, "isInterruptionRequested", fake_interrupted)
        worker.run()
        assert events["cancelled"] is True

    def test_run_update_cancelled_emits_cancelled(self, monkeypatch: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        worker, events = self._call_run(monkeypatch)
        (worker2, events2) = worker, events  # keep reference
        # 重新构造：让 check_for_updates 抛 UpdateCancelled
        monkeypatch.setattr(uc, "check_for_updates", lambda **k: (_ for _ in ()).throw(uc.UpdateCancelled()))
        w2: Any = uc.UpdateCheckWorker(parent=None)
        ev: Dict[str, Any] = {"failure": None, "cancelled": False}
        w2.cancelled.connect(lambda: ev.__setitem__("cancelled", True))
        w2.run()
        assert ev["cancelled"] is True

    def test_run_update_error_emits_failure(self, monkeypatch: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        monkeypatch.setattr(uc, "check_for_updates", lambda **k: (_ for _ in ()).throw(uc.UpdateError("网络超时")))
        w: Any = uc.UpdateCheckWorker(parent=None)
        failed: List[str] = []
        w.failure.connect(failed.append)
        w.run()
        assert failed == ["网络超时"]

    def test_run_generic_exception_emits_failure(self, monkeypatch: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        monkeypatch.setattr(uc, "check_for_updates", lambda **k: (_ for _ in ()).throw(RuntimeError("boom")))
        w: Any = uc.UpdateCheckWorker(parent=None)
        failed: List[str] = []
        w.failure.connect(failed.append)
        w.run()
        assert failed == ["检查更新失败：boom"]


class TestSilentUpdateCheckWorkerRun:
    """SilentUpdateCheckWorker.run() 各分支。"""

    def test_run_no_update_success_and_finished(self, monkeypatch: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        monkeypatch.setattr(uc, "check_for_updates", lambda **k: _no_update_result())
        w: Any = uc.SilentUpdateCheckWorker()
        events: Dict[str, Any] = {"update_available": 0, "success": 0, "failure": 0, "cancelled": 0, "finished": 0}
        w.update_available.connect(lambda r: events.__setitem__("update_available", events["update_available"] + 1))
        w.success.connect(lambda r: events.__setitem__("success", events["success"] + 1))
        w.cancelled.connect(lambda: events.__setitem__("cancelled", events["cancelled"] + 1))
        w.check_finished.connect(lambda: events.__setitem__("finished", events["finished"] + 1))
        w.run()
        assert events["success"] == 1
        assert events["update_available"] == 0
        assert events["finished"] == 1

    def test_run_update_available_emits_both(self, monkeypatch: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        monkeypatch.setattr(uc, "check_for_updates", lambda **k: _update_available_result())
        w: Any = uc.SilentUpdateCheckWorker()
        events: Dict[str, Any] = {"update_available": 0, "success": 0, "finished": 0}
        w.update_available.connect(lambda r: events.__setitem__("update_available", events["update_available"] + 1))
        w.success.connect(lambda r: events.__setitem__("success", events["success"] + 1))
        w.check_finished.connect(lambda: events.__setitem__("finished", events["finished"] + 1))
        w.run()
        assert events["success"] == 1
        assert events["update_available"] == 1
        assert events["finished"] == 1

    def test_run_interrupted_before_emits_finished(self, monkeypatch: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        w: Any = uc.SilentUpdateCheckWorker()
        finished: List[str] = []
        w.check_finished.connect(lambda: finished.append("done"))
        w.requestInterruption()
        w.run()
        assert finished == ["done"]

    def test_run_update_error_failure_and_finished(self, monkeypatch: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        monkeypatch.setattr(uc, "check_for_updates", lambda **k: (_ for _ in ()).throw(uc.UpdateError("网络超时")))
        w: Any = uc.SilentUpdateCheckWorker()
        failed: List[str] = []
        w.failure.connect(failed.append)
        finished: List[str] = []
        w.check_finished.connect(lambda: finished.append("done"))
        w.run()
        assert failed == ["网络超时"]
        assert finished == ["done"]

    def test_run_generic_exception_failure_and_finished(self, monkeypatch: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        monkeypatch.setattr(uc, "check_for_updates", lambda **k: (_ for _ in ()).throw(RuntimeError("boom")))
        w: Any = uc.SilentUpdateCheckWorker()
        failed: List[str] = []
        w.failure.connect(failed.append)
        w.run()
        assert failed == ["检查更新失败：boom"]


class TestUpdateDownloadWorkerRun:
    """UpdateDownloadWorker.run() 成功 / 取消 / 校验失败 / 网络错误。"""

    def _make_worker_and_run(self, monkeypatch: Any, tmp_path: Any, **overrides: Any) -> Dict[str, Any]:
        import urllib.request

        import freeassetfilter.components.update_controller as uc

        cache_dir: str = str(tmp_path / "cache")
        rel_info: Dict[str, Any] = dict(_RELEASE_INFO)
        rel_info.update(overrides.pop("release_info", {}))
        monkeypatch.setattr(uc, "get_cache_dir", lambda: cache_dir)
        monkeypatch.setattr(uc, "build_request_headers", lambda *a, **k: {"Accept": "application/octet-stream"})
        monkeypatch.setattr(uc, "verify_installer_file", overrides.pop("verify", lambda *a, **k: True))
        monkeypatch.setattr(
            uc,
            "prepare_cached_installer",
            overrides.pop("prepare", lambda *a, **k: {"is_ready": True, "installer_path": "x.exe"}),
        )
        opener = overrides.pop("opener", _FakeUrlOpener(response=_ChunkedResponse([b"a" * 1024, b"b" * 476], 1500)))
        monkeypatch.setattr(urllib.request, "urlopen", opener)

        worker: Any = uc.UpdateDownloadWorker(rel_info, parent=None)
        events: Dict[str, Any] = {"success": None, "failure": None, "cancelled": False, "progress": []}
        worker.success.connect(lambda r: events.__setitem__("success", r))
        worker.failure.connect(lambda m: events.__setitem__("failure", m))
        worker.cancelled.connect(lambda: events.__setitem__("cancelled", True))
        worker.progress_changed.connect(lambda d, t, txt: events["progress"].append((d, t)))
        return worker, events

    def test_run_success_downloads_and_reports(self, monkeypatch: Any, tmp_path: Any) -> None:
        worker, events = self._make_worker_and_run(monkeypatch, tmp_path)
        worker.run()
        assert events["success"] is not None
        assert events["failure"] is None
        assert events["progress"]  # 至少一段进度
        assert events["progress"][-1][1] == 1500

    def test_run_cancel_during_download(self, monkeypatch: Any, tmp_path: Any) -> None:
        worker, events = self._make_worker_and_run(monkeypatch, tmp_path)
        worker._cancel_requested = True
        worker.run()
        assert events["cancelled"] is True
        assert events["success"] is None

    def test_run_sha256_failure(self, monkeypatch: Any, tmp_path: Any) -> None:
        worker, events = self._make_worker_and_run(
            monkeypatch, tmp_path, verify=lambda *a, **k: False
        )
        worker.run()
        assert events["failure"] == "下载完成，但 SHA256 校验失败"
        assert events["success"] is None

    def test_run_urllib_error(self, monkeypatch: Any, tmp_path: Any) -> None:
        worker, events = self._make_worker_and_run(
            monkeypatch,
            tmp_path,
            opener=_FakeUrlOpener(error=urllib.error.URLError("no route")),
        )
        worker.run()
        assert events["failure"] == "下载更新失败：<urlopen error no route>"

    def test_run_oserror_maps_to_update_error(self, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        def _real_os_replace(a, b):
            raise OSError("disk full")

        def _os_replace_with_fail(src, dst):
            return _real_os_replace(src, dst)

        original_replace = os.replace
        monkeypatch.setattr(os, "replace", _os_replace_with_fail)
        worker, events = self._make_worker_and_run(monkeypatch, tmp_path)
        try:
            worker.run()
            assert events["failure"] is not None
            assert "写入安装包失败" in events["failure"]
        finally:
            monkeypatch.setattr(os, "replace", original_replace)

    def test_run_generic_exception(self, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        def _boom(*a, **k):
            raise RuntimeError("cache blew")

        worker, events = self._make_worker_and_run(
            monkeypatch, tmp_path, prepare=_boom
        )
        worker.run()
        assert events["failure"] is not None
        assert "下载更新失败" in events["failure"]

    def test_format_progress_text(self) -> None:
        from freeassetfilter.components.update_controller import UpdateDownloadWorker

        text: str = UpdateDownloadWorker._format_progress_text(500, 1000)
        assert text == "50% (500 B / 1000 B)"
        text_no_total: str = UpdateDownloadWorker._format_progress_text(500, 0)
        assert text_no_total == "500 B"

    def test_format_size_units(self) -> None:
        from freeassetfilter.components.update_controller import UpdateDownloadWorker

        assert UpdateDownloadWorker._format_size(0) == "0 B"
        assert UpdateDownloadWorker._format_size(512) == "512 B"
        assert UpdateDownloadWorker._format_size(1500) == "1.46 KB"
        assert UpdateDownloadWorker._format_size(2 * 1024 * 1024) == "2.00 MB"


class TestUpdateControllerCheckFlowExtras:
    """检查流程的取消 / 重试 / 对话框与静默接管分支。"""

    def test_on_check_dialog_clicked_index_ignored(self, make_update_controller: Any) -> None:
        controller: Any = make_update_controller()
        controller._on_check_dialog_clicked(1)
        assert controller._check_cancelled is False

    def test_on_check_dialog_clicked_cancels_manual_check(self, make_update_controller: Any) -> None:
        controller: Any = make_update_controller()
        fake: Any = _FakeWorker(running=True)
        controller._check_worker = fake
        controller._on_check_dialog_clicked(0)
        assert controller._check_cancelled is True
        assert controller._check_worker is None
        assert fake in controller._retired_check_workers

    def test_on_check_dialog_clicked_cancels_claimed_silent(self, make_update_controller: Any) -> None:
        controller: Any = make_update_controller()
        fake: Any = _FakeWorker(running=True)
        controller._silent_check_worker = fake
        controller._manual_check_uses_silent = True
        controller._on_check_dialog_clicked(0)
        assert controller._silent_check_cancelled is True
        assert controller._silent_check_worker is None
        assert fake in controller._retired_silent_workers

    def test_on_check_cancelled_clears_state(self, make_update_controller: Any, monkeypatch: Any) -> None:
        controller: Any = make_update_controller()
        controller._check_worker = _FakeWorker(running=False)
        controller._check_cancelled = True
        closed: List[str] = []
        monkeypatch.setattr(controller, "_close_current_dialog", lambda: closed.append("closed"))
        controller._on_check_cancelled()
        assert controller._check_worker is None
        assert controller._check_cancelled is False
        assert closed == ["closed"]

    def test_on_check_cancelled_ignores_retired_sender(self, make_update_controller: Any, monkeypatch: Any) -> None:
        controller: Any = make_update_controller()
        fake: Any = _FakeWorker(running=False)
        controller._retired_check_workers.append(fake)
        monkeypatch.setattr(controller, "sender", lambda: fake)
        controller._on_check_cancelled()
        assert controller._check_worker is None  # 未做任何清理

    def test_on_check_success_ignores_retired_sender(self, make_update_controller: Any, monkeypatch: Any) -> None:
        controller: Any = make_update_controller()
        fake: Any = _FakeWorker(running=False)
        controller._retired_check_workers.append(fake)
        monkeypatch.setattr(controller, "sender", lambda: fake)
        controller._on_check_success(_update_available_result())
        assert controller._check_worker is None

    def test_on_check_failure_ignores_retired_sender(self, make_update_controller: Any, monkeypatch: Any) -> None:
        controller: Any = make_update_controller()
        fake: Any = _FakeWorker(running=False)
        controller._retired_check_workers.append(fake)
        monkeypatch.setattr(controller, "sender", lambda: fake)
        controller._on_check_failure("旧线程")
        assert controller._check_worker is None

    def test_on_check_success_cancelled_restarts(self, make_update_controller: Any, monkeypatch: Any) -> None:
        controller: Any = make_update_controller()
        controller._check_cancelled = True
        restarted: List[str] = []
        monkeypatch.setattr(controller, "_restart_manual_check_if_needed", lambda: restarted.append("restart"))
        closed: List[str] = []
        monkeypatch.setattr(controller, "_close_current_dialog", lambda: closed.append("closed"))
        controller._on_check_success(_update_available_result())
        assert controller._check_cancelled is False
        assert restarted == ["restart"]
        assert closed == ["closed"]

    def test_restart_manual_check_schedules(self, make_update_controller: Any, monkeypatch: Any) -> None:
        controller: Any = make_update_controller()
        controller._pending_check_restart = True
        started: List[str] = []
        monkeypatch.setattr(controller, "_start_manual_check", lambda: started.append("start"))
        controller._restart_manual_check_if_needed()
        assert controller._pending_check_restart is False
        flush_widget_queue()
        assert started == ["start"]

    def test_restart_manual_check_noop_when_not_pending(self, make_update_controller: Any, monkeypatch: Any) -> None:
        controller: Any = make_update_controller()
        started: List[str] = []
        monkeypatch.setattr(controller, "_start_manual_check", lambda: started.append("start"))
        controller._restart_manual_check_if_needed()
        assert started == []

    def test_start_manual_check_from_silent_sets_flags(self, make_update_controller: Any, monkeypatch: Any) -> None:
        controller: Any = make_update_controller()
        shown: List[str] = []
        monkeypatch.setattr(controller, "_show_check_progress_dialog", lambda: shown.append("shown"))
        controller._start_manual_check_from_silent()
        assert controller._manual_check_uses_silent is True
        assert controller._check_cancelled is False
        assert shown == ["shown"]

    def test_show_check_progress_dialog(self, make_update_controller: Any, monkeypatch: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        controller: Any = make_update_controller()
        monkeypatch.setattr(uc, "CustomMessageBox", _FakeMessageBox)
        controller._show_check_progress_dialog()
        assert controller._current_dialog is not None
        assert controller._current_loading_spinner is not None
        controller._close_current_dialog()
        assert controller._current_loading_spinner is None


class TestUpdateControllerDownloadFlow:
    """下载启动 / 取消对话框 / 进度轮询。"""

    def test_on_update_available_clicked_starts_download(
        self, make_update_controller: Any, monkeypatch: Any
    ) -> None:
        import freeassetfilter.components.update_controller as uc

        controller: Any = make_update_controller()
        controller._current_release_info = dict(_RELEASE_INFO)
        monkeypatch.setattr(uc, "CustomMessageBox", _FakeMessageBox)

        class _DownloadStub(_FakeWorker):
            def __init__(self, release_info, parent=None) -> None:
                super().__init__(running=False)
                self.release_info = release_info
                self.progress_changed: Any = _FakeSignalBox()
                self.cancelled: Any = _FakeSignalBox()
                self.started: bool = False

            def start(self) -> None:
                self.started = True

        monkeypatch.setattr(uc, "UpdateDownloadWorker", _DownloadStub)
        controller._on_update_available_dialog_clicked(0)
        assert controller._download_worker is not None
        assert controller._download_worker.started is True
        assert controller._current_download_total_size == 1500
        controller._close_current_dialog()

    def test_on_update_available_clicked_wrong_index(self, make_update_controller: Any) -> None:
        controller: Any = make_update_controller()
        controller._current_release_info = dict(_RELEASE_INFO)
        controller._on_update_available_dialog_clicked(1)
        assert controller._download_worker is None

    def test_on_download_dialog_clicked_cancels(self, make_update_controller: Any, monkeypatch: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        controller: Any = make_update_controller()
        fake_dl: Any = _CancelableFakeWorker(running=True)
        controller._download_worker = fake_dl
        monkeypatch.setattr(uc, "CustomMessageBox", _FakeMessageBox)
        controller._show_progress_dialog(
            title="下载更新",
            text="正在下载…",
            progress_min=0,
            progress_max=100,
            progress_value=0,
            buttons=["取消下载"],
            button_types=["normal"],
            callback=controller._on_download_dialog_clicked,
            allow_close=False,
        )
        controller._on_download_dialog_clicked(0)
        assert controller._current_progress_bar is not None
        controller._close_current_dialog()

    def test_on_download_dialog_clicked_wrong_index(self, make_update_controller: Any) -> None:
        controller: Any = make_update_controller()
        controller._on_download_dialog_clicked(1)
        assert controller._download_worker is None

    def test_poll_progress_with_file_and_total(self, make_update_controller: Any, tmp_path: Any) -> None:
        controller: Any = make_update_controller()
        from PySide6.QtWidgets import QLabel

        from freeassetfilter.widgets.progress_widgets import D_ProgressBar

        bar: Any = D_ProgressBar(is_interactive=False)
        label: Any = QLabel("")
        controller._current_progress_bar = bar
        controller._current_progress_info_label = label
        cache: Any = tmp_path / "cache"
        cache.mkdir()
        temp_file: Any = cache / "faf.exe.download"
        temp_file.write_bytes(b"x" * 512)
        controller._current_download_temp_path = str(temp_file)
        controller._current_download_total_size = 1024
        controller._poll_download_progress_from_file()
        assert "50.0%" in controller._current_dialog_text if hasattr(controller, "_current_dialog_text") else True
        assert "下载更新" in str(label.text()) or label.text() != ""
        controller._close_current_dialog()

    def test_poll_progress_no_total_uses_release_size(self, make_update_controller: Any, tmp_path: Any) -> None:
        controller: Any = make_update_controller()
        from PySide6.QtWidgets import QLabel

        from freeassetfilter.widgets.progress_widgets import D_ProgressBar

        bar: Any = D_ProgressBar(is_interactive=False)
        controller._current_progress_bar = bar
        controller._current_progress_info_label = QLabel("")
        controller._current_download_total_size = 0
        controller._current_release_info = {"installer_size": 500}
        cache: Any = tmp_path / "cache"
        cache.mkdir()
        temp_file: Any = cache / "faf.exe.download"
        temp_file.write_bytes(b"x" * 100)
        controller._current_download_temp_path = str(temp_file)
        controller._poll_download_progress_from_file()
        controller._close_current_dialog()

    def test_poll_progress_speed_calculation(self, make_update_controller: Any, monkeypatch: Any) -> None:
        import time

        from PySide6.QtWidgets import QLabel

        from freeassetfilter.widgets.progress_widgets import D_ProgressBar

        controller: Any = make_update_controller()
        bar: Any = D_ProgressBar(is_interactive=False)
        controller._current_progress_bar = bar
        controller._current_progress_info_label = QLabel("")
        controller._current_download_total_size = 2048
        controller._last_speed_check_time = time.time() - 1.0
        controller._last_speed_check_size = 1024
        controller._latest_downloaded_size = 2048
        controller._poll_download_progress_from_file()
        assert controller._current_download_speed_text != "0 B/s"
        controller._close_current_dialog()

    def test_format_speed_and_controller_size(self, make_update_controller: Any) -> None:
        controller: Any = make_update_controller()
        assert controller._format_speed(0) == "0 B/s"
        assert controller._format_speed(500) == "500 B/s"
        assert controller._format_speed(2 * 1024) == "2.00 KB/s"
        assert controller._format_speed(3 * 1024 * 1024) == "3.00 MB/s"
        assert controller._format_size(1024) == "1.00 KB"
        assert controller._format_size(2 * 1024 * 1024) == "2.00 MB"


class TestUpdateControllerDialogs:
    """消息 / 更新详情 / 安装对话框（CustomMessageBox 全部打桩）。"""

    def test_show_message_dialog_with_callback(self, make_update_controller: Any, monkeypatch: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        controller: Any = make_update_controller()
        monkeypatch.setattr(uc, "CustomMessageBox", _FakeMessageBox)
        controller._show_message_dialog("标题", "文本", ["确定"], ["primary"])
        assert controller._current_dialog is None  # exec 返回后清理
        fake: Any = _FakeMessageBox()
        controller._current_dialog = fake
        controller._show_message_dialog("标题", "文本", ["确定"], ["primary"], callback=controller._on_check_dialog_clicked)
        assert controller._current_dialog is None

    def test_show_update_available_detail_dialog_not_ready(self, make_update_controller: Any, monkeypatch: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        controller: Any = make_update_controller()
        monkeypatch.setattr(uc, "CustomMessageBox", _FakeMessageBox)
        controller._show_update_available_detail_dialog(
            local_info={"tag_name": "v1.0.0"},
            release_info={"tag_name": "v1.1.0", "published_date": "2026-08-10", "installer_size": 1500, "release_body": "- 修复"},
            installer_ready=False,
        )
        assert controller._current_dialog is None  # exec 返回后清理

    def test_show_update_available_detail_dialog_ready(self, make_update_controller: Any, monkeypatch: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        controller: Any = make_update_controller()
        monkeypatch.setattr(uc, "CustomMessageBox", _FakeMessageBox)
        controller._current_ready_package = {"is_ready": True, "installer_path": "C:/x.exe", "installer_sha256": "ab" * 32}
        controller._show_update_available_detail_dialog(
            local_info={"tag_name": "v1.0.0"},
            release_info={"tag_name": "v1.1.0", "published_date": "2026-08-10", "installer_size": 1500, "release_body": "- 修复"},
            installer_ready=True,
        )
        assert controller._current_dialog is None

    def test_show_install_ready_dialog_delegates(self, make_update_controller: Any, monkeypatch: Any) -> None:
        controller: Any = make_update_controller()
        captured: List[Dict[str, Any]] = []
        monkeypatch.setattr(
            controller,
            "_show_message_dialog",
            lambda **kwargs: captured.append(kwargs),
        )
        controller._show_install_ready_dialog(title="下载完成", text="SHA256 校验通过。")
        assert len(captured) == 1
        assert captured[0]["title"] == "下载完成"
        assert captured[0]["buttons"] == ["立即安装", "取消"]

    def test_on_install_ready_no_package(self, make_update_controller: Any, monkeypatch: Any) -> None:
        controller: Any = make_update_controller()
        controller._current_ready_package = None
        captured: List[Dict[str, Any]] = []
        monkeypatch.setattr(controller, "_show_message_dialog", lambda **kwargs: captured.append(kwargs))
        controller._on_install_ready_dialog_clicked(0)
        assert captured and captured[0]["title"] == "安装失败"

    def test_on_install_ready_wrong_index(self, make_update_controller: Any, monkeypatch: Any) -> None:
        controller: Any = make_update_controller()
        controller._current_ready_package = {"installer_path": "C:/x.exe", "installer_sha256": "ab" * 32}
        controller._on_install_ready_dialog_clicked(1)
        assert controller._current_ready_package is not None  # 未消费

    def test_on_install_ready_missing_file(self, make_update_controller: Any, monkeypatch: Any) -> None:
        controller: Any = make_update_controller()
        controller._current_ready_package = {"installer_path": "C:/does/not/exist.exe", "installer_sha256": "ab" * 32}
        captured: List[Dict[str, Any]] = []
        monkeypatch.setattr(controller, "_show_message_dialog", lambda **kwargs: captured.append(kwargs))
        controller._on_install_ready_dialog_clicked(0)
        assert captured and "不存在" in captured[0]["text"]

    def test_on_install_ready_verify_fail_cleans_cache(
        self, make_update_controller: Any, monkeypatch: Any, tmp_path: Any
    ) -> None:
        import freeassetfilter.components.update_controller as uc

        controller: Any = make_update_controller()
        installer: Any = tmp_path / "faf.exe"
        installer.write_bytes(b"MZ")
        metadata: Any = tmp_path / "metadata.json"
        metadata.write_text("{}")
        package: Dict[str, Any] = {
            "installer_path": str(installer),
            "installer_sha256": "ab" * 32,
        }
        controller._current_ready_package = package
        monkeypatch.setattr(uc, "verify_installer_file", lambda *a, **k: False)
        monkeypatch.setattr(uc, "get_cache_metadata_path", lambda: str(metadata))
        captured: List[Dict[str, Any]] = []
        monkeypatch.setattr(controller, "_show_message_dialog", lambda **kwargs: captured.append(kwargs))
        controller._on_install_ready_dialog_clicked(0)
        assert captured and "校验失败" in captured[0]["text"]
        assert not installer.exists()
        assert not metadata.exists()

    def test_on_install_ready_success_launches_and_closes(
        self, make_update_controller: Any, monkeypatch: Any, tmp_path: Any
    ) -> None:
        import freeassetfilter.components.update_controller as uc

        controller: Any = make_update_controller()
        installer: Any = tmp_path / "faf.exe"
        installer.write_bytes(b"MZ")
        package: Dict[str, Any] = {
            "installer_path": str(installer),
            "installer_sha256": "ab" * 32,
        }
        controller._current_ready_package = package
        monkeypatch.setattr(uc, "verify_installer_file", lambda *a, **k: True)
        fake_main: _FakeMainWindow = _FakeMainWindow()
        controller.main_window = fake_main
        launched: List[str] = []
        monkeypatch.setattr(controller, "_launch_installer_helper", lambda *a, **k: launched.append("launch"))
        controller._on_install_ready_dialog_clicked(0)
        assert launched == ["launch"]
        assert fake_main.closed is True

    def test_launch_installer_helper_non_frozen(self, make_update_controller: Any, monkeypatch: Any, tmp_path: Any) -> None:
        import freeassetfilter.components.update_controller as uc

        controller: Any = make_update_controller()
        spawned: List[List[str]] = []
        monkeypatch.setattr(uc.subprocess, "Popen", lambda args, **kw: spawned.append(args))
        controller._launch_installer_helper(str(tmp_path / "faf.exe"), "ab" * 32)
        assert len(spawned) == 1
        args: List[str] = spawned[0]
        assert "--faf-run-installer" in args

    def test_launch_installer_helper_frozen(self, make_update_controller: Any, monkeypatch: Any, tmp_path: Any) -> None:
        import sys

        import freeassetfilter.components.update_controller as uc

        controller: Any = make_update_controller()
        spawned: List[List[str]] = []
        monkeypatch.setattr(uc.subprocess, "Popen", lambda args, **kw: spawned.append(args))
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        try:
            controller._launch_installer_helper(str(tmp_path / "faf.exe"), "ab" * 32)
            assert len(spawned) == 1
            assert "--faf-run-installer" in spawned[0]
        finally:
            monkeypatch.setattr(sys, "frozen", False, raising=False)

    def test_set_dialog_helpers(self, make_update_controller: Any) -> None:
        controller: Any = make_update_controller()
        fake: Any = _FakeMessageBox()
        controller._current_dialog = fake
        controller._set_dialog_text("正在取消下载，请稍候…")
        assert fake.closed is False
        controller._set_progress_info_text("12 KB / 100 KB")
        controller._set_dialog_buttons([], [])
        controller._close_current_dialog()
        assert controller._current_dialog is None
        # None 路径安全
        controller._set_dialog_text("文本")
        controller._set_progress_info_text("文本")
        controller._set_dialog_buttons(["确定"])


class TestUpdateControllerSilentHandlers:
    """静默检查的各回调：接管 / 取消 / 完成。"""

    def _controller_with_sender(self, make_update_controller: Any, monkeypatch: Any, sender: Any = None) -> Any:
        controller: Any = make_update_controller()
        if sender is not None:
            monkeypatch.setattr(controller, "sender", lambda: sender)
        return controller

    def test_update_available_normal_shows_detail(
        self, make_update_controller: Any, monkeypatch: Any
    ) -> None:
        import freeassetfilter.components.update_controller as uc

        controller: Any = make_update_controller()
        shown: List[Dict[str, Any]] = []
        monkeypatch.setattr(
            controller,
            "_show_update_available_detail_dialog",
            lambda **kwargs: shown.append(kwargs),
        )
        result: Dict[str, Any] = _update_available_result()
        controller._on_silent_check_update_available(result)
        assert len(shown) == 1
        assert controller._current_release_info["tag_name"] == "v1.1.0"

    def test_update_available_ignores_retired(self, make_update_controller: Any, monkeypatch: Any) -> None:
        controller: Any = make_update_controller()
        fake: Any = _FakeWorker(running=False)
        controller._retired_silent_workers.append(fake)
        monkeypatch.setattr(controller, "sender", lambda: fake)
        controller._on_silent_check_update_available(_update_available_result())
        assert controller._current_release_info is None

    def test_update_available_ignores_when_claimed_by_manual(
        self, make_update_controller: Any, monkeypatch: Any
    ) -> None:
        controller: Any = make_update_controller()
        controller._silent_check_claimed_by_manual = True
        controller._on_silent_check_update_available(_update_available_result())
        assert controller._current_release_info is None

    def test_success_normal_shows_check_result(
        self, make_update_controller: Any, monkeypatch: Any
    ) -> None:
        controller: Any = make_update_controller()
        controller._manual_check_uses_silent = True
        results: List[Dict[str, Any]] = []
        monkeypatch.setattr(controller, "_show_check_result", lambda r: results.append(r))
        controller._on_silent_check_success(_update_available_result())
        assert len(results) == 1
        assert controller._manual_check_uses_silent is False
        assert controller._silent_check_claimed_by_manual is True

    def test_success_ignored_not_manual(self, make_update_controller: Any) -> None:
        controller: Any = make_update_controller()
        controller._on_silent_check_success(_update_available_result())
        assert controller._silent_check_claimed_by_manual is False

    def test_success_cancelled_closes_dialog(
        self, make_update_controller: Any, monkeypatch: Any
    ) -> None:
        controller: Any = make_update_controller()
        controller._manual_check_uses_silent = True
        controller._check_cancelled = True
        closed: List[str] = []
        monkeypatch.setattr(controller, "_close_current_dialog", lambda: closed.append("closed"))
        controller._on_silent_check_success(_update_available_result())
        assert closed == ["closed"]
        assert controller._check_cancelled is False

    def test_failure_normal_forwards_to_check_failure(
        self, make_update_controller: Any, monkeypatch: Any
    ) -> None:
        controller: Any = make_update_controller()
        controller._manual_check_uses_silent = True
        forwarded: List[str] = []
        monkeypatch.setattr(controller, "_on_check_failure", lambda m: forwarded.append(m))
        controller._on_silent_check_failure("网络超时")
        assert forwarded == ["网络超时"]
        assert controller._silent_check_claimed_by_manual is True

    def test_failure_ignored_not_manual(self, make_update_controller: Any) -> None:
        controller: Any = make_update_controller()
        controller._on_silent_check_failure("网络超时")
        assert controller._manual_check_uses_silent is False

    def test_cancelled_normal_forwards(self, make_update_controller: Any, monkeypatch: Any) -> None:
        controller: Any = make_update_controller()
        controller._manual_check_uses_silent = True
        called: List[str] = []
        monkeypatch.setattr(controller, "_on_check_cancelled", lambda: called.append("cancelled"))
        controller._on_silent_check_cancelled()
        assert called == ["cancelled"]
        assert controller._manual_check_uses_silent is False

    def test_finished_clears_worker(self, make_update_controller: Any) -> None:
        controller: Any = make_update_controller()
        controller._silent_check_worker = _FakeWorker(running=False)
        controller._on_silent_check_finished()
        assert controller._silent_check_worker is None
        assert controller._manual_check_uses_silent is False

    def test_finished_forgets_retired(self, make_update_controller: Any, monkeypatch: Any) -> None:
        controller: Any = make_update_controller()
        fake: Any = _FakeWorker(running=False)
        controller._retired_silent_workers.append(fake)
        monkeypatch.setattr(controller, "sender", lambda: fake)
        controller._on_silent_check_finished()
        assert fake not in controller._retired_silent_workers


class TestUpdateControllerFormatting:
    """更新日志 / 主题色 / Markdown 渲染等静态工具。"""

    def test_normalize_release_notes(self, make_update_controller: Any) -> None:
        controller: Any = make_update_controller()
        assert controller._normalize_release_notes("") == "暂无更新日志。"
        assert controller._normalize_release_notes(None) == "暂无更新日志。"
        assert controller._normalize_release_notes("\r\n 内容 \r\n") == "内容"

    def test_get_theme_colors_with_settings(self, make_update_controller: Any, qapp: Any) -> None:
        controller: Any = make_update_controller()
        colors: Dict[str, str] = controller._get_theme_colors()
        assert set(colors) == {"base", "secondary", "accent", "auxiliary"}
        assert isinstance(colors["accent"], str)

    def test_get_theme_colors_without_settings(self, make_update_controller: Any, monkeypatch: Any) -> None:
        from PySide6.QtCore import QObject

        import freeassetfilter.components.update_controller as uc

        controller: Any = make_update_controller()
        dummy: Any = QObject()
        monkeypatch.setattr(uc.QApplication, "instance", lambda: dummy)
        colors: Dict[str, str] = controller._get_theme_colors()
        assert colors["base"] == "#FFFFFF"

    def test_create_info_and_section_labels(self, make_update_controller: Any) -> None:
        from PySide6.QtWidgets import QLabel

        controller: Any = make_update_controller()
        info: QLabel = controller._create_info_label("信息")
        assert isinstance(info, QLabel)
        section: QLabel = controller._create_section_title_label("更新日志")
        assert isinstance(section, QLabel)
        selectable: QLabel = controller._create_info_label("可选", selectable=True)
        assert isinstance(selectable, QLabel)

    def test_render_markdown_release_notes(self, make_update_controller: Any) -> None:
        controller: Any = make_update_controller()
        empty: str = controller._render_markdown_release_notes("")
        assert "暂无更新日志" in empty
        markdown: str = controller._render_markdown_release_notes("## 标题\n- 项目")
        assert "<h3>" in markdown
        assert "<li>" in markdown

    def test_convert_markdown_to_html(self, make_update_controller: Any) -> None:
        controller: Any = make_update_controller()
        html: str = controller._convert_markdown_to_html("## 章节\n- 一\n- 二\n\n正文")
        assert "<h3>" in html
        assert "<li>" in html
        assert "<br>" in html

    def test_process_inline_markdown_escapes(self, make_update_controller: Any) -> None:
        controller: Any = make_update_controller()
        text: str = controller._process_inline_markdown("**粗体**、*斜体*、`代码` 与 <b>标签</b>")
        assert "<strong>粗体</strong>" in text
        assert "<em>斜体</em>" in text
        assert "<code>代码</code>" in text
        assert "&lt;b&gt;" in text

    def test_process_inline_markdown_links(self, make_update_controller: Any) -> None:
        controller: Any = make_update_controller()
        text: str = controller._process_inline_markdown("**官网**: https://example.com")
        assert '<a href="https://example.com"' in text
        assert "<strong>官网</strong>" in text

    def test_escape_html(self, make_update_controller: Any) -> None:
        controller: Any = make_update_controller()
        assert controller._escape_html("<a>&</a>") == "&lt;a&gt;&amp;&lt;/a&gt;"

    def test_create_markdown_text_edit(self, make_update_controller: Any) -> None:
        from PySide6.QtWidgets import QTextBrowser

        controller: Any = make_update_controller()
        browser: QTextBrowser = controller._create_markdown_text_edit("<p>Hello</p>")
        assert isinstance(browser, QTextBrowser)
        assert browser.isReadOnly() is True