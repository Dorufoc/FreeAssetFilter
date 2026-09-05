# -*- coding: utf-8 -*-
"""判定「拖动期增量重绘」可行的载体：哪种控件形态下 scroll() 真的搬移像素？

上一轮已证明：**被兄弟控件覆盖的 alien 子控件**上 ``QWidget::scroll()``
会退化成整窗失效（不搬移像素）。本脚本系统扫描候选形态：

* A alien 子控件，**无**覆盖兄弟      —— 能否 scroll？
* B alien 子控件，**有**覆盖兄弟      —— 已知：退化（对照）
* C ``WA_NativeWindow`` 子控件 + 覆盖兄弟 —— 能否 scroll？（自带 HWND 背存）
* D 顶层窗口                         —— 已知：可用（对照）

只有在该载体上 scroll 可用，"拖动期只重绘新暴露条带" 才成立。
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

W, H = 400, 300


class Bg(QWidget):
    """会画一条可辨识横带（红，y=100..110）的背景控件。"""

    def __init__(self, parent=None, native: bool = False) -> None:
        super().__init__(parent)
        if native:
            self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.regions: list = []

    def paintEvent(self, e):  # noqa: N802
        self.regions.append([QRect(r) for r in e.region()])
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(10, 10, 10))
        p.fillRect(QRect(0, 100, W, 10), QColor(255, 0, 0))
        p.end()


class Overlay(QWidget):
    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 255))
        p.end()


def _row_of(img: QImage, w: int, h: int) -> int:
    best, bv = -1, -10 ** 9
    for y in range(h):
        v = sum(QColor(img.pixel(x, y)).red() - QColor(img.pixel(x, y)).green()
                for x in range(0, w, 4))
        if v > bv:
            bv, best = v, y
    return best


def _blue_top(img: QImage, w: int, h: int) -> int:
    for y in range(h):
        c = QColor(img.pixel(w // 2, y))
        if c.blue() > 150 and c.red() < 100 and c.green() < 100:
            return y
    return -1


def probe(app: QApplication, label: str, native: bool, with_overlay: bool) -> bool:
    host = QWidget()
    host.resize(W, H)
    bg = Bg(host, native=native)
    bg.setGeometry(0, 0, W, H)
    bg.lower()
    ov = None
    if with_overlay:
        ov = Overlay(host)
        ov.setGeometry(0, 250, W, 30)
    host.show()
    app.processEvents()
    app.processEvents()
    if native:
        bg.winId()  # 强制创建 HWND
        app.processEvents()
        app.processEvents()

    screen = app.primaryScreen()

    def shot():
        return screen.grabWindow(host.winId()).toImage().convertToFormat(
            QImage.Format_RGB32)

    img0 = shot()
    y0, ov0 = _row_of(img0, W, H), (_blue_top(img0, W, H) if with_overlay else -1)

    bg.regions.clear()
    bg.scroll(0, -40)
    app.processEvents()
    app.processEvents()

    img1 = shot()
    y1 = _row_of(img1, W, H)
    ov1 = _blue_top(img1, W, H) if with_overlay else -1

    moved = (y1 - y0) == -40
    intact = (ov1 == ov0) if with_overlay else True
    regions = bg.regions[-1] if bg.regions else []
    area = sum(r.width() * r.height() for r in regions)
    verdict = "可用" if (moved and intact) else "不可用"
    print(f"  {label:<42} 搬移 {'是' if moved else '否'} | 兄弟未损 {'是' if intact else '否'} "
          f"| 失效区 {area:7,d} px ({area/(W*H)*100:5.1f}%) | {verdict}")
    host.deleteLater()
    app.processEvents()
    return bool(moved and intact)


def main() -> int:
    app = QApplication([])
    print("=" * 92)
    print("scroll() 载体可行性扫描（scroll(0,-40)，期望横带 y 100→60）")
    print("=" * 92)
    r = []
    r.append(probe(app, "A alien 子控件 · 无覆盖兄弟", False, False))
    r.append(probe(app, "B alien 子控件 · 有覆盖兄弟（对照）", False, True))
    r.append(probe(app, "C WA_NativeWindow 子控件 · 有覆盖兄弟", True, True))
    r.append(probe(app, "D WA_NativeWindow 子控件 · 无覆盖兄弟", True, False))
    print("=" * 92)
    print(f"可用载体：{[c for c, ok in zip('ABCD', r) if ok] or '无'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
