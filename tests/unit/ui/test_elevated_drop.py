# -*- coding: utf-8 -*-
"""提权拖入兜底（``ElevatedDropFallbackMixin``）单元测试（todo-14 / 办法二）。

覆盖清单（对齐任务要求 a-e）：

- (a) 未提权：``showEvent`` / ``WinIdChange`` 均零原生调用，且 ``super()``
  链路照旧执行；
- (b) 提权：安装序列恰为 RevokeDragDrop → DragAcceptFiles →
  ChangeWindowMessageFilterEx（WM_DROPFILES / WM_COPYDATA / WM_COPYGLOBALDATA），
  重复 show 幂等；
- (c) 合成 ``WM_DROPFILES``：伪 HDROP 走**真实 shell32** 解析（DragQueryFileW /
  DragQueryPoint 只读内存，无句柄登记校验，见任务证据中的真实 ctypes 冒烟），
  路径完整路由、DragFinish 必达、路由异常不外泄；
- (d) 命中测试拒绝：不查询 / 不路由，但仍 DragFinish（不泄漏 HDROP）；
- (e) ``WinIdChange``（GPU 表面致 HWND 重建）：强制重装；
- 附加：未安装 / 非 ``windows_*_MSG`` / 非 WM_DROPFILES 消息一律透传
  （无边框依赖的 WM_NCCALCSIZE=0x0083、WM_NCHITTEST=0x0084 不被打扰）；
  高 DPI 物理→逻辑坐标换算；两宿主类 MRO + 实际接线（浮窗信号、主窗口
  仅文件池命中）。

运行（offscreen）：
    python -m pytest tests/unit/ui/test_elevated_drop.py -v
"""

# targets: ui.elevated_drop / ui.floating_pool_window / ui.main_window /
#          ui.layout.file_pool_layout

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QApplication, QWidget

# main_window / floating_pool_window 依赖 ui 短路径导入，与 test_main_window.py 同款
_UI_ROOT: str = str(Path(__file__).resolve().parents[3] / "sopeek" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from sopeek.ui import elevated_drop  # noqa: E402
from sopeek.ui.elevated_drop import (  # noqa: E402
    MSGFLT_ALLOW,
    WM_COPYDATA,
    WM_COPYGLOBALDATA,
    WM_DROPFILES,
    ElevatedDropFallbackMixin,
)
from sopeek.ui.floating_pool_window import FloatingPoolWindow  # noqa: E402
from sopeek.ui.frameless_window import FramelessMainWindow  # noqa: E402
from sopeek.ui.main_window import MainWindow  # noqa: E402
from sopeek.utils import elevation  # noqa: E402

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(
        sys.platform != "win32",
        reason="WM_DROPFILES 兜底为 Windows 专用（非 Windows 下整体退化为空操作）",
    ),
]

# ── 伪 HDROP 构造（真实 shell32 可解析的内存块） ─────────────────────────

_GMEM_MOVEABLE = 0x0002

if sys.platform == "win32":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    _kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalUnlock.restype = wintypes.BOOL
    _kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalFree.restype = wintypes.HGLOBAL
else:  # pragma: no cover - 非 Windows 平台测试整体被 skip
    _kernel32 = None


class _ForgedDrop:
    """伪 HDROP：GMEM_MOVEABLE 全局内存 + DROPFILES 头 + UTF-16 路径表。

    ``DragQueryFileW`` / ``DragQueryPoint`` 只解析内存结构，不校验句柄登记，
    故该伪句柄可被真实原生函数完整读取（任务证据中的冒烟已先行验证）。
    """

    def __init__(self, paths: list[str], *, non_client: bool = False) -> None:
        """写入 DROPFILES 头（pt=(123, 456)）与 ``paths`` 列表。

        Args:
            paths: 伪 HDROP 携带的路径列表。
            non_client: 是否标记落点位于非客户区（``fNC``）。
        """
        payload = "".join(p + "\0" for p in paths) + "\0"
        encoded = payload.encode("utf-16-le")
        size = ctypes.sizeof(elevated_drop._DROPFILES) + len(encoded)
        self.handle = int(_kernel32.GlobalAlloc(_GMEM_MOVEABLE, size))
        assert self.handle, "GlobalAlloc 失败"
        pointer = _kernel32.GlobalLock(wintypes.HGLOBAL(self.handle))
        assert pointer, "GlobalLock 失败"
        try:
            header = elevated_drop._DROPFILES.from_address(pointer)
            header.pFiles = ctypes.sizeof(elevated_drop._DROPFILES)
            header.pt.x = 123
            header.pt.y = 456
            header.fNC = 1 if non_client else 0
            header.fWide = 1
            ctypes.memmove(
                pointer + ctypes.sizeof(elevated_drop._DROPFILES),
                encoded,
                len(encoded),
            )
        finally:
            _kernel32.GlobalUnlock(wintypes.HGLOBAL(self.handle))

    def free(self) -> None:
        """释放伪 HDROP（未被真实 DragFinish 接管时由测试清理）。"""
        if self.handle:
            _kernel32.GlobalFree(wintypes.HGLOBAL(self.handle))
            self.handle = 0


class _MsgPtr:
    """堆上的一份 ``wintypes.MSG``（暴露指针地址供 nativeEvent 使用）。"""

    def __init__(
        self,
        *,
        hwnd: int = 0x1234,
        message: int = WM_DROPFILES,
        wparam: int = 0,
        lparam: int = 0,
    ) -> None:
        """构造 MSG 并记录其指针。

        Args:
            hwnd: 消息目标窗口句柄。
            message: 消息常量。
            wparam: 消息 ``wParam``。
            lparam: 消息 ``lParam``。
        """
        self._buf = ctypes.create_string_buffer(ctypes.sizeof(wintypes.MSG))
        msg = wintypes.MSG.from_buffer(self._buf)
        msg.hwnd = hwnd
        msg.message = message
        msg.wParam = wparam
        msg.lParam = lparam
        msg.time = 0
        self.pointer: int = ctypes.cast(self._buf, ctypes.c_void_p).value or 0


# ── 假宿主（记录 super() 链路与路由 hook） ───────────────────────────────


class _FakeHostBase:
    """假宿主基类：在 ``nativeEvent`` / ``showEvent`` / ``event`` 上留哨兵。"""

    def __init__(self) -> None:
        self.hwnd = 0x1234
        self.device_pixel_ratio = 1.0
        self.super_native_events: list[tuple[Any, Any]] = []
        self.super_show_events: list[Any] = []
        self.super_events: list[Any] = []

    def internalWinId(self) -> int:
        """返回可控 HWND（0 模拟建窗前的假句柄）。"""
        return self.hwnd

    def devicePixelRatioF(self) -> float:
        """返回可控 DPR。"""
        return self.device_pixel_ratio

    def showEvent(self, event: Any) -> None:
        """哨兵：记录 super() 收到的显示事件。"""
        self.super_show_events.append(event)

    def event(self, event: Any) -> bool:
        """哨兵：记录 super() 收到的事件类型。"""
        self.super_events.append(event.type())
        return False

    def nativeEvent(self, eventType: Any, message: Any) -> tuple[bool, int]:
        """哨兵：记录透传给 super() 的原生消息。"""
        self.super_native_events.append((eventType, message))
        return False, 0


class _Host(ElevatedDropFallbackMixin, _FakeHostBase):
    """可实例化宿主：hook 覆写放在最外层以记录 / 可控失败。"""

    def __init__(self) -> None:
        super().__init__()
        self.accepted_points: list[tuple[int, int]] = []
        self.routed_paths: list[list[str]] = []
        self.point_accepted = True
        self.raise_on_route = False

    def _elevated_drop_accepts_point(self, x: int, y: int) -> bool:
        """记录命中测试入参并返回可控结果。"""
        self.accepted_points.append((x, y))
        return self.point_accepted

    def _elevated_drop_accept_paths(self, paths: list[str]) -> None:
        """记录路由结果；``raise_on_route`` 时抛异常模拟路由失败。"""
        self.routed_paths.append(list(paths))
        if self.raise_on_route:
            raise RuntimeError("route boom")


# ── 打桩账本 fixture ─────────────────────────────────────────────────────


class _InstallSpy:
    """记录模块级原生安装调用的顺序与参数。"""

    def __init__(self) -> None:
        self.order: list[tuple] = []


@pytest.fixture(autouse=True)
def _default_unelevated(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认伪装为非提权进程：隔离测试进程自身提权状态，避免真实原生调用。"""
    monkeypatch.setattr(elevation, "is_process_elevated", lambda: False)


@pytest.fixture()
def install_spy(monkeypatch: pytest.MonkeyPatch) -> _InstallSpy:
    """打桩三个原生安装函数（不触碰真实 ole32/user32/shell32）。"""
    spy = _InstallSpy()

    def _fake_revoke(hwnd: int) -> bool:
        spy.order.append(("revoke", hwnd))
        return True

    def _fake_accept(hwnd: int, accept: bool) -> None:
        spy.order.append(("accept", hwnd, bool(accept)))

    def _fake_allow(hwnd: int, message_id: int) -> bool:
        spy.order.append(("allow", hwnd, message_id))
        return True

    monkeypatch.setattr(elevated_drop, "_revoke_drag_drop", _fake_revoke)
    monkeypatch.setattr(elevated_drop, "_drag_accept_files", _fake_accept)
    monkeypatch.setattr(elevated_drop, "_allow_dropped_message", _fake_allow)
    return spy


@pytest.fixture()
def finish_spy(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """打桩 DragFinish 并记录句柄（真实 DragFinish 会立即释放伪 HDROP 内存）。"""
    calls: list[int] = []
    monkeypatch.setattr(elevated_drop, "_drag_finish", calls.append)
    return calls


# ── 消息常量 ─────────────────────────────────────────────────────────────


def test_message_constants_match_winuser() -> None:
    """消息常量与 winuser.h / shellapi.h 对齐。"""
    assert WM_DROPFILES == 0x0233
    assert WM_COPYDATA == 0x004A
    assert WM_COPYGLOBALDATA == 0x0049
    assert MSGFLT_ALLOW == 1


# ── (a) 未提权：零原生调用 ───────────────────────────────────────────────


def test_unelevated_never_installs(install_spy: _InstallSpy) -> None:
    """(a) 未提权：showEvent / WinIdChange 均零原生调用，super() 链路照旧。"""
    host = _Host()
    host.showEvent(QShowEvent())
    host.event(QEvent(QEvent.Type.WinIdChange))

    assert host.super_show_events, "super().showEvent 未被调用"
    assert QEvent.Type.WinIdChange in host.super_events, "super().event 未被调用"
    assert install_spy.order == []
    assert host._elevated_drop_installed is False


# ── (b) 提权：安装序列与幂等 ─────────────────────────────────────────────


def test_elevated_install_calls_native_apis_once(
    monkeypatch: pytest.MonkeyPatch, install_spy: _InstallSpy
) -> None:
    """(b) 提权：撤销先行，三类调用各一次；重复 show 幂等。"""
    monkeypatch.setattr(elevation, "is_process_elevated", lambda: True)
    host = _Host()
    host.showEvent(QShowEvent())

    assert [entry[0] for entry in install_spy.order] == [
        "revoke",
        "accept",
        "allow",
        "allow",
        "allow",
    ], "安装顺序必须为 RevokeDragDrop → DragAcceptFiles → 消息过滤器"
    assert install_spy.order[1] == ("accept", 0x1234, True)
    assert install_spy.order[2:] == [
        ("allow", 0x1234, WM_DROPFILES),
        ("allow", 0x1234, WM_COPYDATA),
        ("allow", 0x1234, WM_COPYGLOBALDATA),
    ]
    assert host._elevated_drop_installed is True
    assert host._elevated_drop_hwnd == 0x1234

    host.showEvent(QShowEvent())
    assert len(install_spy.order) == 5, "重复 show 不得重复安装"


def test_zero_hwnd_skips_install(
    monkeypatch: pytest.MonkeyPatch, install_spy: _InstallSpy
) -> None:
    """HWND 尚未建立（0）：跳过安装、不触原生、保持未安装。"""
    monkeypatch.setattr(elevation, "is_process_elevated", lambda: True)
    host = _Host()
    host.hwnd = 0
    host.showEvent(QShowEvent())

    assert install_spy.order == []
    assert host._elevated_drop_installed is False


# ── (c) 合成 WM_DROPFILES 全链路（真实 shell32 解析伪 HDROP） ─────────────


def test_wm_dropfiles_routes_paths_e2e(
    monkeypatch: pytest.MonkeyPatch,
    install_spy: _InstallSpy,
    finish_spy: list[int],
) -> None:
    """(c) WM_DROPFILES：真实解析伪 HDROP → 命中 → 路由 → DragFinish 必达。"""
    monkeypatch.setattr(elevation, "is_process_elevated", lambda: True)
    host = _Host()
    host.showEvent(QShowEvent())

    paths = ["C:\\alpha.txt", "C:\\\u8d44\u6599\\beta.txt"]
    forged = _ForgedDrop(paths)
    try:
        msg = _MsgPtr(wparam=forged.handle)
        handled, result = host.nativeEvent(b"windows_generic_MSG", msg.pointer)

        assert handled is True
        assert result == 0
        assert host.accepted_points == [(123, 456)]
        assert host.routed_paths == [paths]
        assert finish_spy == [forged.handle], "DragFinish 必须恰好调用一次"
    finally:
        forged.free()


def test_route_exception_still_finishes(
    monkeypatch: pytest.MonkeyPatch,
    install_spy: _InstallSpy,
    finish_spy: list[int],
) -> None:
    """(c2) 路由异常不外泄：仍返回 (True, 0)，DragFinish 必达。"""
    monkeypatch.setattr(elevation, "is_process_elevated", lambda: True)
    host = _Host()
    host.raise_on_route = True
    host.showEvent(QShowEvent())

    forged = _ForgedDrop(["C:\\boom.txt"])
    try:
        msg = _MsgPtr(wparam=forged.handle)
        handled, _ = host.nativeEvent(b"windows_generic_MSG", msg.pointer)
        assert handled is True
        assert finish_spy == [forged.handle]
    finally:
        forged.free()


# ── (d) 命中测试拒绝：不路由但仍 DragFinish ──────────────────────────────


def test_rejected_point_skips_routing_but_finishes(
    monkeypatch: pytest.MonkeyPatch,
    install_spy: _InstallSpy,
    finish_spy: list[int],
) -> None:
    """(d) 命中测试拒绝：不查询 / 不路由，但仍 DragFinish（不泄漏 HDROP）。"""
    monkeypatch.setattr(elevation, "is_process_elevated", lambda: True)
    host = _Host()
    host.point_accepted = False
    host.showEvent(QShowEvent())

    forged = _ForgedDrop(["C:\\rejected.txt"])
    try:
        msg = _MsgPtr(wparam=forged.handle)
        handled, _ = host.nativeEvent(b"windows_generic_MSG", msg.pointer)
        assert handled is True
        assert host.accepted_points == [(123, 456)]
        assert host.routed_paths == []
        assert finish_spy == [forged.handle]
    finally:
        forged.free()


# ── (e) WinIdChange 强制重装 ─────────────────────────────────────────────


def test_win_id_change_reinstalls(
    monkeypatch: pytest.MonkeyPatch, install_spy: _InstallSpy
) -> None:
    """(e) WinIdChange（HWND 重建）：强制重跑完整安装序列。"""
    monkeypatch.setattr(elevation, "is_process_elevated", lambda: True)
    host = _Host()
    host.showEvent(QShowEvent())
    assert len(install_spy.order) == 5

    host.event(QEvent(QEvent.Type.WinIdChange))
    assert len(install_spy.order) == 10
    assert install_spy.order[5:] == install_spy.order[:5]
    assert host.super_events, "super().event 仍须被调用"


# ── 透传语义（未安装 / 其它消息） ────────────────────────────────────────


def test_native_event_passthrough_when_not_installed(
    install_spy: _InstallSpy, finish_spy: list[int]
) -> None:
    """未安装：WM_DROPFILES 也纯透传，无路由、无 DragFinish。"""
    host = _Host()
    forged = _ForgedDrop(["C:\\x.txt"])
    try:
        msg = _MsgPtr(wparam=forged.handle)
        handled, result = host.nativeEvent(b"windows_generic_MSG", msg.pointer)
        assert (handled, result) == (False, 0)
        assert host.super_native_events[-1] == (
            b"windows_generic_MSG",
            msg.pointer,
        )
        assert host.routed_paths == []
        assert finish_spy == []
    finally:
        forged.free()


@pytest.mark.parametrize("message_id", [0x0083, 0x0084, WM_COPYDATA])
def test_other_messages_passthrough_when_installed(
    monkeypatch: pytest.MonkeyPatch, install_spy: _InstallSpy, message_id: int
) -> None:
    """安装后非 WM_DROPFILES 消息原样交回 super()（无边框消息不被打扰）。

    ``WM_NCCALCSIZE``（0x0083）/ ``WM_NCHITTEST``（0x0084）正是
    ``FramelessMainWindow`` 依赖的消息，必须逐条透传。
    """
    monkeypatch.setattr(elevation, "is_process_elevated", lambda: True)
    host = _Host()
    host.showEvent(QShowEvent())

    msg = _MsgPtr(message=message_id)
    handled, result = host.nativeEvent(b"windows_generic_MSG", msg.pointer)
    assert (handled, result) == (False, 0)
    assert host.super_native_events[-1] == (b"windows_generic_MSG", msg.pointer)


def test_wrong_event_type_passthrough(
    monkeypatch: pytest.MonkeyPatch, install_spy: _InstallSpy
) -> None:
    """非 windows_*_MSG 事件类型：即便消息号是 WM_DROPFILES 也不劫持。"""
    monkeypatch.setattr(elevation, "is_process_elevated", lambda: True)
    host = _Host()
    host.showEvent(QShowEvent())

    msg = _MsgPtr(message=WM_DROPFILES)
    handled, _ = host.nativeEvent(b"some_other_MSG", msg.pointer)
    assert handled is False
    assert host.routed_paths == []


# ── 高 DPI 坐标换算 ──────────────────────────────────────────────────────


def test_point_converted_to_logical_by_dpr(
    monkeypatch: pytest.MonkeyPatch,
    install_spy: _InstallSpy,
    finish_spy: list[int],
) -> None:
    """高 DPI：物理落点 (123, 456) 在 DPR=2 下按逻辑 (62, 228) 命中。"""
    monkeypatch.setattr(elevation, "is_process_elevated", lambda: True)
    host = _Host()
    host.device_pixel_ratio = 2.0
    host.showEvent(QShowEvent())

    forged = _ForgedDrop(["C:\\dpi.txt"])
    try:
        msg = _MsgPtr(wparam=forged.handle)
        host.nativeEvent(b"windows_generic_MSG", msg.pointer)
        assert host.accepted_points == [(62, 228)]
    finally:
        forged.free()


# ── 宿主接线 ─────────────────────────────────────────────────────────────


def test_hosts_mixin_precedes_native_handlers() -> None:
    """两宿主 MRO：Mixin 必须排在原生事件处理者之前，否则 nativeEvent 拦不到。"""
    window_mro = MainWindow.__mro__
    assert ElevatedDropFallbackMixin in window_mro
    assert window_mro.index(ElevatedDropFallbackMixin) < window_mro.index(
        FramelessMainWindow
    )
    assert MainWindow.nativeEvent is ElevatedDropFallbackMixin.nativeEvent

    pool_mro = FloatingPoolWindow.__mro__
    assert ElevatedDropFallbackMixin in pool_mro
    assert pool_mro.index(ElevatedDropFallbackMixin) < pool_mro.index(QWidget)
    assert FloatingPoolWindow.nativeEvent is ElevatedDropFallbackMixin.nativeEvent


def test_floating_pool_window_elevated_paths_route_to_signal(
    qapp: QApplication, tmp_path: Path
) -> None:
    """浮窗接线：兜底路径经真实信号链路 emit（过滤不存在路径、CJK 路径无损）。"""
    window = FloatingPoolWindow()
    try:
        received: list[dict] = []
        window.add_file_requested.connect(received.append)
        real_file = tmp_path / "elevated_drop.txt"
        real_file.write_text("x", encoding="utf-8")

        window._elevated_drop_accept_paths(
            [str(real_file), str(tmp_path / "missing.txt")]
        )

        assert len(received) == 1
        # 同 OLE 链路口径：QUrl.toLocalFile() 返回正斜杠路径，按规范化比较
        assert os.path.normpath(received[0].get("path", "")) == os.path.normpath(
            str(real_file)
        )
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


class _StubMicaBackground(QWidget):
    """``make_mica_background`` 的 QWidget 替身（与 test_main_window.py 同款）。

    MainWindow 的 resize/move/主题回调会调用 Mica 壳的接口，用普通 QWidget
    顶替时缺这些方法会 AttributeError；此处按真实壳的同名 no-op 补齐。
    """

    def handle_window_resize(self) -> None:
        """空实现：无原生 Mica 窗口需同步。"""

    def handle_window_move(self) -> None:
        """空实现：无原生 Mica 窗口需同步。"""

    def _ensure_mica_material(self):
        """空实现：无材质，返回 None 走降级分支。"""
        return None

    def sync_theme(self) -> None:
        """空实现：无 Mica 材质需重载。"""


@pytest.fixture()
def stub_mica(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 Mica 背景工厂替换为普通 QWidget（防止 MicaMaterial 事件过滤器污染）。"""
    monkeypatch.setattr(
        "sopeek.ui.main_window.make_mica_background",
        lambda *a, **k: _StubMicaBackground(),
    )


def test_main_window_hit_test_accepts_only_pool_area(
    qapp: QApplication, stub_mica: None
) -> None:
    """主窗口命中测试：仅文件池控件矩形内落点接受，池外四向拒绝。"""
    window = MainWindow()
    try:
        window._build_panel("pool")
        pool = window._file_pool
        assert pool is not None

        pool.setGeometry(120, 80, 200, 160)
        top_left = pool.mapTo(window, QPoint(0, 0))
        size = pool.size()
        assert (size.width(), size.height()) == (200, 160)

        inside_x = top_left.x() + 5
        inside_y = top_left.y() + 5
        assert window._elevated_drop_accepts_point(inside_x, inside_y) is True
        assert window._elevated_drop_accepts_point(inside_x, top_left.y() - 1) is False
        assert window._elevated_drop_accepts_point(top_left.x() - 1, inside_y) is False
        assert (
            window._elevated_drop_accepts_point(
                top_left.x() + size.width(), inside_y
            )
            is False
        )
        assert (
            window._elevated_drop_accepts_point(
                inside_x, top_left.y() + size.height()
            )
            is False
        )
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_main_window_elevated_paths_route_to_pool(
    qapp: QApplication, stub_mica: None, tmp_path: Path
) -> None:
    """主窗口接线：兜底路径经 add_dropped_paths 注入文件池（跳过不存在路径）。"""
    window = MainWindow()
    try:
        window._build_panel("pool")
        pool = window._file_pool
        assert pool is not None

        before = len(pool.items)
        real_file = tmp_path / "inject.txt"
        real_file.write_text("x", encoding="utf-8")

        window._elevated_drop_accept_paths(
            [str(real_file), str(tmp_path / "missing.txt")]
        )

        assert len(pool.items) == before + 1
        assert pool.items[-1].get("path") == str(real_file)
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()
