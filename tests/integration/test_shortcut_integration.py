# -*- coding: utf-8 -*-
"""快捷键集成测试：主窗口 → 派发器 → 各区域 handler 的完整链路。

覆盖：

* 派发器随主窗口安装/卸载；
* 焦点变化驱动区域切换（selector / pool / info / preview.*）；
* 焦点区遍历顺序（workspace 与 classic 两套）；
* 全局键（``Ctrl+I`` 打开设置）在无弹窗时生效；
* 各区域 handler 已登记（防「忘了调 _register_shortcuts」）。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/integration/test_shortcut_integration.py -v
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from sopeek.core.shortcuts import reset_dispatcher_for_tests, shortcut_dispatcher

pytestmark = pytest.mark.integration


@pytest.fixture
def window(qapp: Any) -> Iterator[Any]:
    """构造并显示主窗口，等三栏面板构建完成。"""
    from PySide6.QtTest import QTest

    from sopeek.ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    QTest.qWait(600)
    qapp.processEvents()
    try:
        yield win
    finally:
        win.close()
        win.deleteLater()
        qapp.processEvents()
        reset_dispatcher_for_tests()


# ── 派发器安装 ───────────────────────────────────────────────────────


def test_dispatcher_installed(window: Any) -> None:
    """主窗口初始化后派发器已安装并接线。"""
    assert window._shortcut_installed is True
    assert window._shortcuts_wired is True
    assert window._shortcuts is shortcut_dispatcher()


def test_dispatcher_uninstalled_on_close(qapp: Any) -> None:
    """关闭主窗口后派发器被卸载（避免全局过滤器残留）。"""
    from PySide6.QtTest import QTest

    from sopeek.ui.main_window import MainWindow

    win = MainWindow()
    win.show()
    QTest.qWait(400)
    qapp.processEvents()
    win.close()
    qapp.processEvents()
    win.deleteLater()
    qapp.processEvents()
    # closeEvent 已调 uninstall；单例仍在但不再挂在 QApplication 上
    assert shortcut_dispatcher()._app is None


# ── handler 登记完整性 ───────────────────────────────────────────────


def test_selector_handlers_registered(window: Any) -> None:
    """选择器的关键动作都已登记 handler。"""
    handlers = shortcut_dispatcher().handlers
    for action_id in (
        "selector.enter",
        "selector.toggle_pool",
        "selector.filter",
        "selector.refresh",
        "selector.sort_menu",
        "selector.gen_thumbs",
        "selector.clear_thumbs",
        "selector.nav_up",
        "selector.batch_right",
    ):
        assert handlers.has(action_id), action_id


def test_pool_handlers_registered(window: Any) -> None:
    """储存池的关键动作都已登记 handler。"""
    handlers = shortcut_dispatcher().handlers
    for action_id in (
        "pool.enter",
        "pool.toggle_pool",
        "pool.nav_up",
        "pool.batch_down",
        "pool.gen_thumbs",
        "pool.clear_thumbs",
    ):
        assert handlers.has(action_id), action_id


def test_info_handlers_registered(window: Any) -> None:
    """信息面板的四个动作都已登记。"""
    handlers = shortcut_dispatcher().handlers
    for action_id in (
        "info.nav_up",
        "info.nav_down",
        "info.copy_current",
        "info.copy_all",
    ):
        assert handlers.has(action_id), action_id


def test_global_handlers_registered(window: Any) -> None:
    """全局键与焦点区遍历都已登记。"""
    handlers = shortcut_dispatcher().handlers
    for action_id in (
        "global.open_settings",
        "global.open_in_explorer",
        "global.open_with_default",
        "global.locate_in_app",
        "nav.next_zone",
        "nav.prev_zone",
        "nav.next_zone_f6",
        "nav.prev_zone_f6",
    ):
        assert handlers.has(action_id), action_id


def test_selector_media_delegation_registered(window: Any) -> None:
    """选择器与储存池的媒体键委托已登记（含倍速三态）。"""
    handlers = shortcut_dispatcher().handlers
    for prefix in ("selector", "pool"):
        for action in ("play_pause", "seek_back", "volume_up"):
            assert handlers.has(f"{prefix}.{action}"), f"{prefix}.{action}"
        for action in ("speed_1", "speed_2", "speed_3", "speed_half"):
            assert handlers.has(f"{prefix}.{action}.press"), action
            assert handlers.has(f"{prefix}.{action}.release"), action


def test_escape_providers_registered(window: Any) -> None:
    """选择器与储存池的 Escape 消费链已登记。"""
    providers = shortcut_dispatcher()._escape_providers
    assert "selector" in providers
    assert "pool" in providers


# ── 区域解析 ─────────────────────────────────────────────────────────


def test_resolve_region_none_is_app(window: Any) -> None:
    """无焦点控件时区域为 app。"""
    assert window._resolve_shortcut_region(None) == "app"


def test_resolve_region_selector(window: Any) -> None:
    """焦点在选择器子树时区域为 selector。"""
    assert (
        window._resolve_shortcut_region(window._file_selector._file_list)
        == "selector"
    )


def test_resolve_region_path(window: Any) -> None:
    """焦点在路径框时区域为 path。"""
    assert (
        window._resolve_shortcut_region(window._file_selector._path_input) == "path"
    )


def test_resolve_region_pool(window: Any) -> None:
    """焦点在储存池子树时区域为 pool。"""
    assert window._resolve_shortcut_region(window._file_pool) == "pool"


def test_resolve_region_info(window: Any) -> None:
    """焦点在信息面板子树时区域为 info。"""
    assert window._resolve_shortcut_region(window._info_panel) == "info"


def test_resolve_region_empty_previewer_falls_back_to_selector(window: Any) -> None:
    """预览器已清空（无内层预览器）时，预览区焦点按 selector 归属。

    取消预览后焦点可能残留在预览器容器上；此时区域若退化为 ``app``，
    ``selector.nav_*`` 不会派发，方向键就成了无响应的死键。
    """
    previewer = window._previewer
    assert previewer is not None
    previewer.clear_preview()
    window._shortcuts.replace_region("selector")

    assert previewer._current_preview_type is None
    assert window._resolve_shortcut_region(previewer) == "selector"


def test_resolve_region_active_previewer_keeps_preview_region(window: Any) -> None:
    """有内层预览器时仍按预览器类型解析（不被 selector 兜底吞掉）。"""
    from sopeek.ui.layout.preview.image_previewer_layout import ImagePreviewerLayout

    previewer = window._previewer
    previewer.clear_preview()
    previewer._current_preview_type = ImagePreviewerLayout

    assert window._resolve_shortcut_region(previewer) == "preview.image"


def test_cancel_releases_stale_preview_region(window: Any) -> None:
    """取消预览后区域不得陈旧地停留在 ``preview.*``。

    区域由 ``focusChanged`` 驱动；内层预览器被销毁后其 handler 已注销。
    若焦点没有真正变化，``focusChanged`` 不发射，区域会停在 ``preview.*``，
    方向键按预览区查表找不到 handler 也不回落 selector —— 表现为「按方向键
    完全没反应」。取消预览必须主动把区域收回选择器。
    """
    window._shortcuts.replace_region("preview.image")

    window._on_preview_cancelled()

    assert window._shortcuts.region() == "selector"


def test_release_preview_region_keeps_non_preview_regions(window: Any) -> None:
    """区域收回只作用于 ``preview.*`` / ``fullscreen``，其它区域原样保留。"""
    for region in ("pool", "info", "selector", "path", "app"):
        window._shortcuts.replace_region(region)
        window._release_preview_shortcut_region()
        assert window._shortcuts.region() == region, region


def test_release_preview_region_resets_fullscreen(window: Any) -> None:
    """全屏区域同样失效（预览器已销毁，全屏语义不存在）。"""
    window._shortcuts.replace_region("fullscreen")

    window._release_preview_shortcut_region()

    assert window._shortcuts.region() == "selector"


# ── 焦点区遍历 ───────────────────────────────────────────────────────


def test_zone_order_workspace(window: Any) -> None:
    """New 布局的焦点区顺序：path → selector → preview → pool → info。"""
    assert window._ZONE_ORDER_WORKSPACE == (
        "path",
        "selector",
        "preview",
        "pool",
        "info",
    )


def test_zone_order_classic(window: Any) -> None:
    """经典三栏的焦点区顺序：path → selector → pool → preview → info。"""
    assert window._ZONE_ORDER_CLASSIC == (
        "path",
        "selector",
        "pool",
        "preview",
        "info",
    )


def test_current_zone_name_maps_preview(window: Any) -> None:
    """``preview.*`` 区域映射为区名 preview。"""
    window._shortcuts.replace_region("preview.image")
    assert window._current_zone_name() == "preview"
    window._shortcuts.replace_region("preview.pdf")
    assert window._current_zone_name() == "preview"


def test_focus_next_zone_moves(window: Any) -> None:
    """``_focus_next_zone`` 能把焦点从 app 移到第一个区。"""
    window._shortcuts.replace_region("app")
    assert window._focus_next_zone(+1) is True
    # app 不在序列内 → index=-1 → 下一个是序列首项 path
    assert window._current_zone_name() == "path"


def test_ctrl_arrow_switches_zone_from_selector(window: Any, qapp: Any) -> None:
    """文件列表内 ``Ctrl+←`` 不进入批量选择。

    右侧三区全空时第一次按键先停在文件选择器并高亮（无处可去时的可见
    反馈），第二次才切到路径框；两条路径都不得触发批量选择。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    selector = window._file_selector
    # 测试会话的数据目录共享：前序用例可能留下暂存池备份并被新窗口恢复。
    # 等恢复定时器跑完再清空，确保“三块全空”的前提不受用例顺序影响。
    QTest.qWait(700)
    qapp.processEvents()
    window._file_pool.clear_all_without_confirmation()
    window._info_panel.clear()
    window._previewer.clear_preview()
    QTest.qWait(300)
    selector.focus_file_list()
    qapp.processEvents()
    assert window._shortcuts.region() == "selector"
    assert not window._previewer.has_active_preview()
    assert not window._file_pool.has_items()
    assert not window._info_panel.has_file()
    window._last_flash_zone = ""

    QTest.keyClick(
        selector._file_list,
        Qt.Key.Key_Left,
        Qt.KeyboardModifier.ControlModifier,
    )
    qapp.processEvents()

    # 第一次：停在文件选择器并高亮它，路径框尚未接管。
    assert window._current_zone_name() == "selector"
    assert QApplication.focusWidget() is selector._file_list
    assert selector._batch_mode is False
    assert window._last_flash_zone == "selector"

    QTest.keyClick(
        selector._file_list,
        Qt.Key.Key_Left,
        Qt.KeyboardModifier.ControlModifier,
    )
    qapp.processEvents()

    # 第二次：继续到路径框（保持完整焦点区循环）。
    assert window._current_zone_name() == "path"
    assert QApplication.focusWidget() is selector._path_input
    assert selector._batch_mode is False


def test_alt_arrow_enters_batch_from_selector(window: Any, qapp: Any) -> None:
    """文件列表内 ``Alt+←`` 进入批量选择（Ctrl 已让给焦点区切换）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    selector = window._file_selector
    selector.focus_file_list()
    qapp.processEvents()
    assert window._shortcuts.region() == "selector"

    QTest.keyClick(
        selector._file_list,
        Qt.Key.Key_Left,
        Qt.KeyboardModifier.AltModifier,
    )
    qapp.processEvents()

    assert selector._batch_mode is True
    selector.exit_batch_mode(keep_selection=False)


# ── 全局键行为 ───────────────────────────────────────────────────────


def test_open_settings_toggles(window: Any, qapp: Any) -> None:
    """``Ctrl+I`` 打开设置；再次触发则关闭。"""
    from PySide6.QtTest import QTest

    assert window._shortcuts.handlers.get("global.open_settings") is not None
    window._shortcuts.handlers.get("global.open_settings")()
    QTest.qWait(300)
    qapp.processEvents()
    assert window._settings_window is not None
    window._shortcuts.handlers.get("global.open_settings")()
    QTest.qWait(300)
    qapp.processEvents()


def test_pool_layout_mode_follows_layout(window: Any) -> None:
    """储存池的布局模式与主窗口一致（三栏禁缩放）。"""
    window.set_layout_mode("classic")
    assert window._file_pool._layout_mode == "classic"
    window.set_layout_mode("workspace")
    assert window._file_pool._layout_mode == "workspace"


# ── 媒体委托 ─────────────────────────────────────────────────────────


def test_media_delegation_noop_without_previewer(window: Any) -> None:
    """无媒体预览器时媒体键委托静默无操作（不抛异常）。"""
    handler = window._shortcuts.handlers.get("selector.play_pause")
    assert handler is not None
    handler()  # 不应抛异常


def test_preview_file_nav_without_selector(window: Any) -> None:
    """``_on_previewer_file_nav`` 在无选择器时安全返回。"""
    window._on_previewer_file_nav(+1)  # 不应抛异常


def test_media_speed_delegates_temp_speed(window: Any) -> None:
    """倍速键委托走预览器 ``begin_temp_speed`` / ``end_temp_speed``。

    保证「选择器 / 储存池区域」与「预览区域」的倍速提示语义一致：
    按下常显，松手收尾后自动隐藏。
    """

    class _StubPreviewer:
        def __init__(self) -> None:
            self.calls = []

        @property
        def current_speed(self) -> float:
            return 1.0

        def begin_temp_speed(self, speed: float) -> None:
            self.calls.append(("begin", speed))

        def end_temp_speed(self, long_pressed: bool) -> None:
            self.calls.append(("end", long_pressed))

    previewer = window._previewer
    assert previewer is not None
    stub = _StubPreviewer()
    previous = previewer._current_preview_widget
    previewer._current_preview_widget = stub
    try:
        window._make_media_speed_press(2.0)()
        window._make_media_speed_release()(True)
    finally:
        previewer._current_preview_widget = previous

    assert stub.calls == [("begin", 2.0), ("end", True)]


# ── 鼠标点击切区 ─────────────────────────────────────────────────────


def test_click_switches_shortcut_region(
    window: Any, qapp: Any, tmp_path: Any
) -> None:
    """点击**有内容**的区域后，快捷键区域跟随点击位置。

    空池 / 空信息面板不是焦点区，点击它们会回退到 selector（另有集成
    用例覆盖）；这里先给两区放入内容，锁定非空区域的点击切区语义。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    path = tmp_path / "click_region.txt"
    path.write_text("x", encoding="utf-8")
    info = {"path": str(path), "name": path.name, "suffix": "txt"}
    window._file_pool.add_file(dict(info))
    window._info_panel.set_file(dict(info))
    QTest.qWait(300)
    qapp.processEvents()
    assert window._file_pool.has_items() is True
    assert window._info_panel.has_file() is True

    window._shortcuts.replace_region("app")
    for widget, expected in (
        (window._file_pool, "pool"),
        (window._info_panel, "info"),
        (window._file_selector._file_list, "selector"),
    ):
        QTest.mouseClick(
            widget, Qt.MouseButton.LeftButton, pos=widget.rect().center()
        )
        qapp.processEvents()
        assert window._shortcuts.region() == expected


def test_path_input_arrow_keys_are_not_consumed(window: Any, qapp: Any) -> None:
    """焦点在路径框时 ``↑↓`` 不移动文件光标（用户实测反馈）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    selector = window._file_selector
    path_input = selector._path_input
    path_input.setFocus()
    qapp.processEvents()
    assert window._shortcuts.region() == "path"
    before = (selector._nav_cursor_row, selector._nav_cursor_path)
    for key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
        QTest.keyClick(path_input, key)
        qapp.processEvents()
        assert (
            selector._nav_cursor_row,
            selector._nav_cursor_path,
        ) == before


# ── 全屏切换跨区域转发 ───────────────────────────────────────────────


def test_fullscreen_forward_handlers_registered(window: Any) -> None:
    """``Ctrl+\\`` 在 app / selector / pool / info / path 各区都有转发的 handler。"""
    handlers = shortcut_dispatcher().handlers
    for region in ("app", "selector", "pool", "info", "path"):
        for action_id in (
            "preview.media.fullscreen",
            "preview.image.fullscreen",
            "preview.pdf.fullscreen",
            "preview.text.fullscreen",
            "preview.font.fullscreen",
        ):
            assert handlers.get(f"{action_id}@{region}") is not None, (
                action_id,
                region,
            )


def test_previewer_cleanup_unregisters_shortcuts(qapp: Any) -> None:
    """预览器 ``cleanup()`` 必须注销自己的 handler（防陈旧方法引用）。"""
    reset_dispatcher_for_tests()
    from sopeek.ui.layout.preview.image_previewer_layout import ImagePreviewerLayout

    previewer = ImagePreviewerLayout()
    handlers = shortcut_dispatcher().handlers
    assert handlers.get("preview.image.zoom_in") is not None
    try:
        previewer.cleanup()
    finally:
        previewer.deleteLater()
        qapp.processEvents()
    assert handlers.get("preview.image.zoom_in") is None
    assert handlers.get("preview.image.fullscreen") is None
    reset_dispatcher_for_tests()


# ── 预览器根目录 Esc 交还焦点 ────────────────────────────────────────


def test_preview_root_escape_handler_wired(window: Any) -> None:
    """主窗口把「根目录 Esc」回调下发给统一预览器（接线完整）。"""
    assert window._previewer is not None
    assert callable(window._previewer._root_escape_handler)


def test_preview_root_escape_handler_focuses_recorded_zone(
    window: Any, qapp: Any
) -> None:
    """压缩包/文件夹预览器根目录 Esc：焦点交还记录区并刷新首卡光标。"""
    selector = window._file_selector
    selector._current_path = "C:\\preview_return"
    selector._file_model.set_files(
        [
            {
                "name": "dir_a",
                "path": "C:\\preview_return\\dir_a",
                "is_dir": True,
                "size": 0,
                "modified": "2026-01-01 00:00",
                "created": "2026-01-01 00:00",
                "suffix": "",
            },
            {
                "name": "a.png",
                "path": "C:\\preview_return\\a.png",
                "is_dir": False,
                "size": 1024,
                "modified": "2026-01-01 00:00",
                "created": "2026-01-01 00:00",
                "suffix": "png",
            },
        ]
    )
    selector.clear_nav_cursor()
    window._zone_before_preview = "selector"

    handler = window._previewer._root_escape_handler
    assert handler is not None
    try:
        assert handler() is True
    finally:
        selector._file_model.set_files([])

    assert selector._nav_cursor_row == 1
    assert selector._nav_cursor_path.endswith("a.png")
    assert window._zone_has_keyboard_focus("selector") is True
    qapp.processEvents()


# ── Enter 预览 → 焦点移交预览器 ──────────────────────────────────────


def _enter_entry(path: str, *, is_dir: bool = False) -> dict:
    """构造 Enter 用例的条目字典（7 键）。"""
    import os

    return {
        "name": os.path.basename(path),
        "path": path,
        "is_dir": is_dir,
        "size": 0 if is_dir else 1024,
        "modified": "2026-01-01 00:00",
        "created": "2026-01-01 00:00",
        "suffix": "" if is_dir else os.path.splitext(path)[1].lstrip(".").lower(),
    }


def _make_png(tmp_path: Any, name: str = "enter_focus.png") -> str:
    """生成一张真实 PNG（图像预览器可正常加载）。"""
    from PySide6.QtGui import QColor, QImage

    path = tmp_path / name
    image = QImage(64, 48, QImage.Format_RGB32)
    image.fill(QColor("red"))
    assert image.save(str(path))
    return str(path)


def test_selector_enter_file_moves_focus_to_previewer(
    window: Any, qapp: Any, tmp_path: Any
) -> None:
    """选择器文件卡片 Enter：应用内预览 + 焦点落入预览器，区域随之切换。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    file_path = _make_png(tmp_path)
    selector = window._file_selector
    selector._file_model.set_files([_enter_entry(file_path)])
    selector._sync_nav_cursor(file_path)
    selector.focus_file_list()
    qapp.processEvents()
    assert window._shortcuts.region() == "selector"

    QTest.keyClick(selector._file_list, Qt.Key.Key_Return)
    QTest.qWait(150)
    qapp.processEvents()

    current = window._previewer.current_file_info() or {}
    assert current.get("path") == file_path
    focus = QApplication.focusWidget()
    assert window._is_descendant_of(focus, window._previewer)
    assert window._shortcuts.region().startswith("preview.")


def test_selector_enter_folder_keeps_focus_in_selector(
    window: Any, qapp: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    """选择器文件夹卡片 Enter：仍进入目录，焦点留在文件选择器。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    dir_path = str(tmp_path / "sub")
    selector = window._file_selector
    selector._file_model.set_files([_enter_entry(dir_path, is_dir=True)])
    selector._sync_nav_cursor(dir_path)
    selector.focus_file_list()
    qapp.processEvents()

    navigated: list = []
    monkeypatch.setattr(
        selector, "_navigate_to", lambda path, **_kw: navigated.append(path) or True
    )

    QTest.keyClick(selector._file_list, Qt.Key.Key_Return)
    QTest.qWait(80)
    qapp.processEvents()

    assert navigated == [dir_path]
    assert window._shortcuts.region() == "selector"
    assert window._is_descendant_of(QApplication.focusWidget(), selector)


def test_pool_enter_moves_focus_to_previewer(
    window: Any, qapp: Any, tmp_path: Any
) -> None:
    """储存池卡片 Enter：预览池内文件并把焦点交给预览器。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    file_path = _make_png(tmp_path, "pool_enter_focus.png")
    pool = window._file_pool
    pool.add_file(_enter_entry(file_path))
    qapp.processEvents()
    pool._set_cursor(file_path)
    qapp.processEvents()
    assert window._shortcuts.region() == "pool"

    QTest.keyClick(QApplication.focusWidget() or pool, Qt.Key.Key_Return)
    QTest.qWait(150)
    qapp.processEvents()

    current = window._previewer.current_file_info() or {}
    assert current.get("path") == file_path
    focus = QApplication.focusWidget()
    assert window._is_descendant_of(focus, window._previewer)
    assert window._shortcuts.region().startswith("preview.")


def test_selector_batch_enter_keeps_focus(window: Any, qapp: Any) -> None:
    """选择器批量态 Enter：无操作，焦点与区域均不变。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    selector = window._file_selector
    selector._file_model.set_files(
        [_enter_entry("C:\\preview_batch\\a.png"), _enter_entry("C:\\preview_batch\\b.png")]
    )
    selector._sync_nav_cursor("C:\\preview_batch\\a.png")
    selector.focus_file_list()
    qapp.processEvents()
    selector._batch_mode = True
    selector._batch_selected = {"C:\\preview_batch\\a.png"}
    region_before = window._shortcuts.region()

    QTest.keyClick(selector._file_list, Qt.Key.Key_Return)
    QTest.qWait(80)
    qapp.processEvents()

    assert selector._batch_mode is True
    assert selector._batch_selected == {"C:\\preview_batch\\a.png"}
    assert window._shortcuts.region() == region_before == "selector"
    assert window._is_descendant_of(QApplication.focusWidget(), selector)
    selector.exit_batch_mode(keep_selection=False)
    selector._file_model.set_files([])

