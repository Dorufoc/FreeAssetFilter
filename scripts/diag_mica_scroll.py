# -*- coding: utf-8 -*-
"""验证 QWidget.scroll() 是否真的搬移了背存像素（而非仅仅缩小失效区）。

QWidget::render() 会**整窗重绘**，因此不能用它来验证 scroll 的效果。本脚本：
把探针作为顶层窗口（自带背存），用 QScreen::grabWindow 抓取该窗口的真实
合成内容，比对 scroll 前后的色带位置。

这是「拖动期只重绘新暴露条带」这一优化能否成立的前提。
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

W, H = 400, 300


class Probe(QWidget):
    """顶层探针窗口：横带（红，y=100..110）+ 竖带（绿，x=200..210）。"""

    def __init__(self) -> None:
        super().__init__()
        self.resize(W, H)
        self.regions: list = []
        self.counter = 0

    def paintEvent(self, e):  # noqa: N802
        self.regions.append([QRect(r) for r in e.region()])
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(10, 10, 10))
        p.fillRect(QRect(0, 100, W, 10), QColor(255, 0, 0))
        p.fillRect(QRect(200, 0, 10, H), QColor(0, 255, 0))
        p.end()


def bands(img: QImage) -> tuple:
    """返回 (横带 y, 竖带 x)。"""
    w, h = img.width(), img.height()
    best_y, bv = -1, -1
    for y in range(h):
        v = sum(QColor(img.pixel(x, y)).red() - QColor(img.pixel(x, y)).green()
                for x in range(0, w, 4))
        if v > bv:
            bv, best_y = v, y
    best_x, bv = -1, -1
    for x in range(w):
        v = sum(QColor(img.pixel(x, y)).green() - QColor(img.pixel(x, y)).red()
                for y in range(0, h, 4))
        if v > bv:
            bv, best_x = v, x
    return best_y, best_x


def main() -> int:
    app = QApplication([])
    p = Probe()
    p.show()
    app.processEvents()
    app.processEvents()

    screen = app.primaryScreen()
    img0 = screen.grabWindow(p.winId()).toImage().convertToFormat(QImage.Format_RGB32)
    print(f"抓取尺寸 {img0.width()}x{img0.height()}（窗口 {W}x{H}）")
    y0, x0 = bands(img0)
    print(f"scroll 前：横带 y≈{y0}  竖带 x≈{x0}")

    p.regions.clear()
    p.scroll(0, -40)
    app.processEvents()
    app.processEvents()
    print(f"scroll(0,-40) 失效区：{p.regions[-1]}")

    img1 = screen.grabWindow(p.winId()).toImage().convertToFormat(QImage.Format_RGB32)
    y1, x1 = bands(img1)
    print(f"scroll 后：横带 y≈{y1}  竖带 x≈{x1}   Δy={y1-y0} Δx={x1-x0}（期望 Δy=-40, Δx=0）")

    ok = (y1 - y0) == -40 and (x1 - x0) == 0
    verdict = "真的搬移了背存像素 ✔ 可用于增量重绘" if ok else "未搬移像素 ✘ 不可用于增量重绘"
    print(f"\n[顶层窗口] 结论：QWidget.scroll() {verdict}")

    child_ok = verify_alien_child(app)
    return 0 if (ok and child_ok) else 1


def verify_alien_child(app) -> bool:
    """验证 Mica 的真实形态：主窗口内的 alien 子控件。

    额外验证：子控件 scroll 时，叠在其上的**兄弟控件**是否会被错误地一起搬移
    （若会，该优化会破坏 UI 内容，必须放弃）。
    """
    W2, H2 = 400, 300

    class Bg(QWidget):
        def __init__(self, parent: QWidget) -> None:
            super().__init__(parent)
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.regions: list = []

        def paintEvent(self, e):  # noqa: N802
            self.regions.append([QRect(r) for r in e.region()])
            p = QPainter(self)
            p.fillRect(self.rect(), QColor(10, 10, 10))
            p.fillRect(QRect(0, 100, W2, 10), QColor(255, 0, 0))
            p.end()

    class Overlay(QWidget):
        def paintEvent(self, e):  # noqa: N802
            p = QPainter(self)
            p.fillRect(self.rect(), QColor(0, 0, 255))
            p.end()

    host = QWidget()
    host.resize(W2, H2)
    bg = Bg(host)
    bg.setGeometry(0, 0, W2, H2)
    bg.lower()
    ov = Overlay(host)
    ov.setGeometry(0, 250, W2, 30)
    host.show()
    app.processEvents()
    app.processEvents()
    screen = app.primaryScreen()

    def _shot():
        return screen.grabWindow(host.winId()).toImage().convertToFormat(
            QImage.Format_RGB32)

    img0 = _shot()
    y0 = _row_of(img0, W2, H2)
    ov0 = _blue_top(img0, W2, H2)
    print(f"\n[alien 子控件] scroll 前：背景横带 y≈{y0}  叠加蓝条顶 y≈{ov0}")

    bg.regions.clear()
    bg.scroll(0, -40)
    app.processEvents()
    app.processEvents()
    print(f"[alien 子控件] scroll(0,-40) 失效区：{bg.regions[-1]}")

    img1 = _shot()
    y1 = _row_of(img1, W2, H2)
    ov1 = _blue_top(img1, W2, H2)
    print(f"[alien 子控件] scroll 后：背景横带 y≈{y1}（Δ={y1 - y0}, 期望 -40）"
          f"  叠加蓝条顶 y≈{ov1}（Δ={ov1 - ov0}, 期望 0）")

    moved = (y1 - y0) == -40
    intact = (ov1 - ov0) == 0
    print(f"[alien 子控件] 背景已搬移：{'是' if moved else '否'} | "
          f"叠加兄弟控件未被破坏：{'是' if intact else '否'}")
    if moved and not intact:
        print("[alien 子控件] 警告：背景搬移时误搬了上层兄弟控件 —— 该优化不可用于重叠场景")
    host.deleteLater()
    return bool(moved and intact)


def _row_of(img: QImage, w: int, h: int) -> int:
    """找红色横带的 y。"""
    best, bv = -1, -10 ** 9
    for y in range(h):
        v = sum(QColor(img.pixel(x, y)).red() - QColor(img.pixel(x, y)).green()
                for x in range(0, w, 4))
        if v > bv:
            bv, best = v, y
    return best


def _blue_top(img: QImage, w: int, h: int) -> int:
    """找蓝色叠加控件的最上一行 y。"""
    for y in range(h):
        c = QColor(img.pixel(w // 2, y))
        if c.blue() > 150 and c.red() < 100 and c.green() < 100:
            return y
    return -1


if __name__ == "__main__":
    raise SystemExit(main())
