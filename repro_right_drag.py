# -*- coding: utf-8 -*-
"""临时诊断脚本 v3：SendInput 真实输入复现左/右键框选（用后即删）。

v3 增强抗干扰：按键按下前校验光标实际位置（GetCursorPos），不一致则重移重试；
池路径基于实际显示文件（FilePathRole）；MOVE 跟踪附带 QApplication.mouseButtons()。
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
_UI_ROOT = str(ROOT / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication

from freeassetfilter.ui.components.file_list_model import FilePathRole
from freeassetfilter.ui.layout.file_selector_layout import FileSelectorLayout

user32 = ctypes.windll.user32

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

TRACE = {
    int(QEvent.MouseButtonPress): "PRESS",
    int(QEvent.MouseButtonRelease): "RELEASE",
    int(QEvent.MouseMove): "MOVE",
    int(QEvent.ContextMenu): "CTXMENU",
    int(QEvent.MouseButtonDblClick): "DBLCLK",
    int(QEvent.NonClientAreaMouseButtonPress): "NC-PRESS",
    int(QEvent.NonClientAreaMouseButtonRelease): "NC-RELEASE",
    int(QEvent.NonClientAreaMouseMove): "NC-MOVE",
}


class DbgSelector(FileSelectorLayout):
    """带真实鼠标事件跟踪的选择器（仅诊断用）。"""

    def eventFilter(self, obj: Any, ev: Any) -> bool:  # noqa: N802
        name = TRACE.get(int(ev.type()))
        if name and (obj is self._file_list.viewport() or obj is self._file_list):
            try:
                print(
                    f"[EVT:{name}] obj={type(obj).__name__} btn={ev.button()} "
                    f"btns={ev.buttons()} qapp_btns={QApplication.mouseButtons()} "
                    f"pos={ev.position().toPoint()} "
                    f"active={self._rubber_active} start={self._rubber_start_pos}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[EVT] log error: {exc}", flush=True)
        return super().eventFilter(obj, ev)


REMOVED: List[str] = []
ADDED: List[str] = []
TOGGLES: List[str] = []
_w: Any = None


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _U)]


def send_mouse(flags: int, dx: int = 0, dy: int = 0) -> None:
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(dx, dy, 0, flags, 0, None)
    if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
        print(f"[SEND] failed flags={flags:#x}", flush=True)


def move_to_phys(x: int, y: int) -> bool:
    """移动光标并校验到位；最多重试 3 次，成功返回 True。"""
    for _ in range(3):
        vx = user32.GetSystemMetrics(76)
        vy = user32.GetSystemMetrics(77)
        vw = user32.GetSystemMetrics(78)
        vh = user32.GetSystemMetrics(79)
        nx = (x - vx) * 65535 // max(vw - 1, 1)
        ny = (y - vy) * 65535 // max(vh - 1, 1)
        send_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny)
        time.sleep(0.05)
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        if abs(pt.x - x) <= 3 and abs(pt.y - y) <= 3:
            return True
    print(f"[SEND] cursor not at {x},{y} (got {pt.x},{pt.y}) — 干扰或 DPI 失配", flush=True)
    return False


def snapshot(tag: str) -> None:
    s = _w
    print(
        f"[STATE:{tag}] active={s._rubber_active} start={s._rubber_start_pos} "
        f"btn={s._rubber_button} rect={s._rubber_rect} suppressed={s._context_menu_suppressed} "
        f"removed={len(REMOVED)} added={len(ADDED)}",
        flush=True,
    )


def phys_of_viewport_point(vp_point: QPoint) -> tuple:
    vp = _w._file_list.viewport()
    g = vp.mapToGlobal(vp_point)
    hwnd = int(_w.winId())
    try:
        dpi = user32.GetDpiForWindow(hwnd)
    except Exception:  # noqa: BLE001
        dpi = user32.GetDpiForSystem()
    scale = (dpi or 96) / 96.0
    return int(g.x() * scale), int(g.y() * scale)


def drag(btn_down_flag: int, btn_up_flag: int, tag: str) -> None:
    x, y = phys_of_viewport_point(QPoint(60, 60))
    if not move_to_phys(x, y):
        return
    send_mouse(btn_down_flag)
    print(f"[DRAG:{tag}] down at {x},{y}", flush=True)
    steps = 8
    for k in range(steps):
        QTimer.singleShot(120 + k * 40, lambda k=k: move_to_phys(x + (k + 1) * 40, y + (k + 1) * 40))
        if k == 4:
            QTimer.singleShot(120 + k * 40 + 20, lambda: snapshot(f"{tag}-mid"))
    QTimer.singleShot(120 + steps * 40, lambda: send_mouse(btn_up_flag))
    QTimer.singleShot(120 + steps * 40 + 20, lambda: print(f"[DRAG:{tag}] up", flush=True))
    QTimer.singleShot(120 + steps * 40 + 400, lambda: snapshot(f"{tag}-end"))


def main() -> None:
    global _w
    app = QApplication.instance() or QApplication(sys.argv)
    _w = DbgSelector()
    _w.resize(900, 900)
    _w.move(120, 120)
    _w.setWindowTitle("RUBBER-DBG3")
    _w.remove_from_pool_requested.connect(lambda info: REMOVED.append(info["path"]))
    _w.add_to_pool_requested.connect(lambda info: ADDED.append(info["path"]))
    _w.show()

    def sync_pool_to_displayed() -> None:
        model = _w._file_model
        rows = model.rowCount()
        paths = [model.data(model.index(r, 0), FilePathRole) for r in range(min(rows, 4))]
        pool = {os.path.normcase(os.path.normpath(p)) for p in paths if p}
        _w.sync_pool_status(pool)
        print(f"[SYNC] rows={rows} first={paths[:2]} pool_size={len(pool)}", flush=True)

    QTimer.singleShot(900, sync_pool_to_displayed)
    QTimer.singleShot(1200, lambda: drag(MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, "left"))
    QTimer.singleShot(3000, lambda: drag(MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, "right"))

    def right_click_no_drag() -> None:
        """右键单击（无拖拽）：验证 ContextMenu→toggle 语义未被 press 消费破坏。"""
        x, y = phys_of_viewport_point(QPoint(60, 400))
        if not move_to_phys(x, y):
            return
        send_mouse(MOUSEEVENTF_RIGHTDOWN)
        QTimer.singleShot(120, lambda: send_mouse(MOUSEEVENTF_RIGHTUP))
        QTimer.singleShot(600, lambda: snapshot("right-click-end"))
        QTimer.singleShot(650, lambda: print(f"[FINAL2] toggles={len(TOGGLES)} {TOGGLES[:2]}", flush=True))
        QTimer.singleShot(700, app.quit)

    QTimer.singleShot(4800, lambda: print(f"[FINAL] removed={REMOVED}", flush=True))
    QTimer.singleShot(4850, right_click_no_drag)
    QTimer.singleShot(5800, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
