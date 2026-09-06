# -*- coding: utf-8 -*-
"""关键实验：背景整窗重绘时，能否冻结上层内容控件使其不被拖入重绘？

``QWidgetBackingStore::sync()`` 递归绘制与脏区相交的控件时，会跳过
``updatesEnabled() == False`` 的控件。若背存中该控件的像素得以保留
（Qt 在 beginPaint 时不清空背存），就能做到：

    拖动期背景整窗重绘（~0.3ms），上层 UI 一个都不重绘，画面完全正确。

这是「背景实时跟手 + 零 UI 重绘」能否兼得的决定性实验。需要验证：
  1. 冻结后，内容控件是否**不再**收到 paintEvent（省下重绘成本）；
  2. 冻结后，内容控件在背存中的像素是否**仍然可见**（不被背景覆盖/清空）。
"""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

W, H = 400, 300


class Bg(QWidget):
    paints = 0

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._src_y = 0

    def paintEvent(self, e):  # noqa: N802
        Bg.paints += 1
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(20, 20, 20))
        # 一条随 _src_y 移动的横带，用来验证背景确实在动
        p.fillRect(QRect(0, 100 - self._src_y, W, 10), QColor(255, 0, 0))
        p.end()


class Content(QWidget):
    paints = 0

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)

    def paintEvent(self, e):  # noqa: N802
        Content.paints += 1
        p = QPainter(self)
        # 半透明蓝：若被背景覆盖就会看到红色/黑色透出
        p.fillRect(self.rect(), QColor(0, 0, 255, 255))
        p.fillRect(QRect(10, 5, 40, 10), QColor(255, 255, 0))
        p.end()


def main() -> int:
    app = QApplication([])
    host = QWidget()
    host.resize(W, H)
    bg = Bg(host)
    bg.setGeometry(0, 0, W, H)
    content = Content(host)
    content.setGeometry(0, 250, W, 50)  # 底部条，叠在背景之上
    bg.lower()
    host.show()
    app.processEvents()
    app.processEvents()
    screen = app.primaryScreen()

    def shot() -> QImage:
        return (screen.grabWindow(host.winId())
                .toImage().convertToFormat(QImage.Format_RGB32))

    # --- 基线：不冻结 ---
    Bg.paints = Content.paints = 0
    t0 = time.perf_counter()
    for i in range(60):
        bg._src_y = i % 40
        bg.update()
        app.processEvents()
    t_free = (time.perf_counter() - t0) * 1000.0
    print(f"[不冻结] 背景 paint {Bg.paints} 次 | 内容 paint {Content.paints} 次 "
          f"| {t_free:.1f} ms")

    img_base = shot()
    px = QColor(img_base.pixel(W // 2, 275))  # 内容控件内部
    print(f"[不冻结] 内容区域像素 = rgb({px.red()},{px.green()},{px.blue()})")

    # --- 实验：冻结内容控件 ---
    content.setUpdatesEnabled(False)
    app.processEvents()
    Bg.paints = Content.paints = 0
    t0 = time.perf_counter()
    for i in range(60):
        bg._src_y = i % 40
        bg.update()
        app.processEvents()
    t_frozen = (time.perf_counter() - t0) * 1000.0
    print(f"\n[冻结]   背景 paint {Bg.paints} 次 | 内容 paint {Content.paints} 次 "
          f"| {t_frozen:.1f} ms  → 加速 {t_free/max(t_frozen,1e-9):.1f}×")

    img_frozen = shot()
    px2 = QColor(img_frozen.pixel(W // 2, 275))
    yellow = QColor(img_frozen.pixel(30, 260))
    print(f"[冻结]   内容区域像素 = rgb({px2.red()},{px2.green()},{px2.blue()}) "
          f"（期望 0,0,255 蓝）")
    print(f"[冻结]   内容内黄色标记 = rgb({yellow.red()},{yellow.green()},{yellow.blue()}) "
          f"（期望 255,255,0）")

    content_visible = px2.blue() > 200 and px2.red() < 60
    marker_visible = yellow.red() > 200 and yellow.green() > 200 and yellow.blue() < 60
    no_repaint = Content.paints == 0

    print("\n" + "=" * 70)
    print(f"  内容不再重绘：{'是 ✔' if no_repaint else '否 ✘'}")
    print(f"  内容仍然可见：{'是 ✔' if content_visible else '否 ✘ 被背景覆盖/清空'}")
    print(f"  细节标记保留：{'是 ✔' if marker_visible else '否 ✘'}")
    usable = no_repaint and content_visible and marker_visible
    verdict = ("可行 —— 冻结上层控件即可让背景实时重绘而零 UI 开销"
               if usable else "不可行 —— 该思路不可用")
    print(f"\n  结论：{verdict}")
    print("=" * 70)
    content.setUpdatesEnabled(True)
    host.deleteLater()
    return 0 if usable else 1


if __name__ == "__main__":
    raise SystemExit(main())
