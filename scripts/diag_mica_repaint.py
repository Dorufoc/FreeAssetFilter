# -*- coding: utf-8 -*-
"""定位「快速拖动」的真正瓶颈：背景失效 → 上层 UI 是否被拖入整窗重绘？

Qt 的背存（backing store）是**顶层窗口共用**的：某块区域变脏后，
``QWidgetBackingStore::sync()`` 会让**所有与该区域相交的控件**自底向上重绘。
Mica 背景是最底层、覆盖全窗的控件 —— 一旦对它做整窗 ``update()``，
整个 UI（侧边栏、文件列表、工具条…）都会跟着重绘。

本脚本构造一个与真实主窗口同构的场景（底层 Mica 背景 + 上层 N 个内容控件），
实测三种失效策略下：

* 各控件收到的 paintEvent 次数 / 覆盖面积；
* 总耗时。

从而判定「缩小重绘范围」到底能省多少。
"""

from __future__ import annotations

import os
import sys
import time
from typing import Callable, List, Tuple

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, os.path.join(_ROOT, "freeassetfilter")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

WIN_W, WIN_H = 1600, 1000
VIRTUAL = (0, 0, 2560, 1440)


def _pixmap_from_rgb(image: np.ndarray) -> QPixmap:
    h, w = int(image.shape[0]), int(image.shape[1])
    data = np.ascontiguousarray(image, dtype=np.uint8).tobytes()
    qimg = QImage(data, w, h, w * 3, QImage.Format_RGB888)
    pm = QPixmap.fromImage(qimg)
    del qimg, data
    return pm


def _layer(w: int, h: int) -> np.ndarray:
    yy = np.linspace(0.0, 1.0, h, dtype=np.float32).reshape(h, 1)
    xx = np.linspace(0.0, 1.0, w, dtype=np.float32).reshape(1, w)
    img = np.stack([30.0 + 40.0 * xx + 18.0 * yy,
                    32.0 + 36.0 * xx + 20.0 * yy,
                    38.0 + 30.0 * xx + 26.0 * yy], axis=2)
    return np.clip(img, 0, 255).astype(np.uint8)


class Counted(QWidget):
    """记录自身 paintEvent 次数与覆盖面积的内容控件（模拟昂贵的 UI）。"""

    #: 全局统计
    stats: dict = {}
    #: 模拟内容绘制成本：每次绘制的“工作量”（像素 × 系数）
    WORK_PER_PX: int = 40

    def __init__(self, name: str, cost: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        self._cost = cost
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        Counted.stats[name] = [0, 0]

    def paintEvent(self, e):  # noqa: N802
        st = Counted.stats[self._name]
        st[0] += 1
        st[1] += e.region().boundingRect().width() * e.region().boundingRect().height()
        # 模拟真实 UI 的绘制成本（自绘卡片/图标/文字）
        r = e.region().boundingRect()
        n = max(1, r.width() * r.height())
        sink = 0
        for i in range(0, min(n, 400000), max(1, n // self._cost)):
            sink += i
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(60, 60, 70, 255))
        p.end()
        Counted.stats.setdefault("_sink", [0, 0])[0] = sink & 1


class MicaBg(QWidget):
    """模拟 Mica 背景控件（最底层、覆盖全窗）。"""

    calls = 0
    area = 0

    def __init__(self, pm: QPixmap, parent: QWidget) -> None:
        super().__init__(parent)
        self._pm = pm
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def paintEvent(self, e):  # noqa: N802
        MicaBg.calls += 1
        MicaBg.area += e.region().boundingRect().width() * e.region().boundingRect().height()
        p = QPainter(self)
        p.drawPixmap(QRect(self.rect()), self._pm,
                     QRect(self._src_x, self._src_y, WIN_W, WIN_H))
        p.end()

    _src_x = 0
    _src_y = 0


def build(app: QApplication):
    host = QWidget()
    host.resize(WIN_W, WIN_H)
    pm = _pixmap_from_rgb(_layer(VIRTUAL[2], VIRTUAL[3]))
    bg = MicaBg(pm, host)
    bg.setGeometry(0, 0, WIN_W, WIN_H)

    # 上层内容：侧边栏 + 工具条 + 主内容区 + 状态栏（模拟真实布局）
    content = QWidget(host)
    content.setGeometry(0, 0, WIN_W, WIN_H)
    lay = QVBoxLayout(content)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    for name, h, cost in [
        ("titlebar", 48, 300),
        ("toolbar", 56, 300),
        ("sidebar_row", 120, 400),
        ("filelist", WIN_H - 48 - 56 - 120 - 40, 1200),
        ("statusbar", 40, 200),
    ]:
        w = Counted(name, cost, content)
        w.setFixedHeight(h)
        lay.addWidget(w)

    bg.lower()
    host.show()
    app.processEvents()
    app.processEvents()
    return host, bg


def run_case(app: QApplication, host: QWidget, bg: MicaBg, label: str,
             invalidate: Callable[[], None], frames: int = 120) -> Tuple[float, int]:
    MicaBg.calls = 0
    MicaBg.area = 0
    for k in Counted.stats:
        Counted.stats[k] = [0, 0]
    started = time.perf_counter()
    for i in range(frames):
        bg._src_x = (400 + i * 3) % 900
        bg._src_y = (200 + (i % 40))
        invalidate()
        app.processEvents()
    el = (time.perf_counter() - started) * 1000.0
    total_calls = sum(v[0] for k, v in Counted.stats.items() if k != "_sink")
    total_area = sum(v[1] for k, v in Counted.stats.items() if k != "_sink")
    print(f"\n  {label}")
    print(f"    总耗时 {el:8.1f} ms | 单帧 {el/frames:7.3f} ms | "
          f"折算 {1000.0/(el/frames):7.0f} fps")
    print(f"    背景 paint {MicaBg.calls:4d} 次 / 面积 {MicaBg.area:12,d} px")
    print(f"    上层 UI paint {total_calls:4d} 次 / 面积 {total_area:12,d} px "
          f"(= {total_area/(WIN_W*WIN_H*frames)*100:5.1f}% 全窗×帧)")
    detail = " | ".join(
        f"{k}:{v[0]}" for k, v in Counted.stats.items() if k != "_sink"
    )
    print(f"    分布 → {detail}")
    return el / frames, total_area


def main() -> int:
    app = QApplication([])
    host, bg = build(app)

    print("=" * 80)
    print("拖动期失效策略对「整窗重绘」的影响（窗口 1600x1000，上层 5 个内容控件）")
    print("=" * 80)

    results = {}
    results["full"] = run_case(
        app, host, bg, "① 整窗 update()  ← 当前实现",
        lambda: bg.update())
    results["strip32"] = run_case(
        app, host, bg, "② 仅顶部 32px 条带 update(QRect)",
        lambda: bg.update(QRect(0, 0, WIN_W, 32)))
    results["strip3"] = run_case(
        app, host, bg, "③ 仅左侧 3px 条带 update(QRect)",
        lambda: bg.update(QRect(0, 0, 3, WIN_H)))
    results["none"] = run_case(
        app, host, bg, "④ 完全不失效（基线：DWM 平移，背景贴窗）",
        lambda: None)

    print("\n" + "=" * 80)
    print("结论")
    print("=" * 80)
    base = results["none"][0]
    for k, label in [("full", "整窗 update"), ("strip32", "32px 条带"),
                     ("strip3", "3px 条带"), ("none", "不失效")]:
        t = results[k][0]
        print(f"  {label:<14} 单帧 {t:7.3f} ms  相对基线 {t/max(base,1e-9):7.1f}×  "
              f"UI 重绘面积 {results[k][1]:12,d} px")
    host.deleteLater()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
