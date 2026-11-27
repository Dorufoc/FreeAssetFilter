#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离屏量取叶子布局真值并抓图（供 promo 对齐）。

只创建叶子布局（文件选择器 / 储存池 / 信息面板 / 统一预览器），
用 WA_DontShowOnScreen + widget.render 抓图，同时输出关键几何与字号。

用法::

    python tools/measure_leaves.py --out .screenshots/leaves
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"


def _ensure_importable() -> None:
    src = str(SRC_DIR)
    if src not in sys.path:
        sys.path.insert(0, src)


def _render(widget, path: Path, size: tuple[int, int]) -> dict:
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtWidgets import QApplication

    widget.resize(*size)
    widget.setAttribute(Qt.WA_DontShowOnScreen, True)
    widget.show()
    for _ in range(8):
        QApplication.processEvents()
        QApplication.sendPostedEvents(None, QEvent.LayoutRequest)

    pm = QPixmap(widget.size())
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    widget.render(p, QPoint(0, 0))
    p.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    pm.save(str(path))
    widget.hide()
    return {"w": widget.width(), "h": widget.height()}


def main() -> int:
    _ensure_importable()
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=".screenshots/leaves")
    args = parser.parse_args()

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])

    from sopeek.ui.layout.file_selector_layout import FileSelectorLayout
    from sopeek.ui.layout.file_pool_layout import FilePoolLayout
    from sopeek.ui.layout.unified_previewer_layout import UnifiedPreviewerLayout
    from sopeek.ui.layout.preview.file_info_panel import FileInfoPanel

    out = Path(args.out)
    report: dict = {}

    sel = FileSelectorLayout()
    report["selector"] = _render(sel, out / "file_selector.png", (404, 700))
    grid = getattr(sel, "_file_list", None)
    report["selector"]["grid"] = {
        "cols": getattr(sel, "_grid_cols", None),
        "card": [getattr(sel, "_grid_card_size", None).width(), getattr(sel, "_grid_card_size", None).height()],
        "gridSize": [grid.gridSize().width(), grid.gridSize().height()] if grid else None,
        "viewportMargins": [
            grid.viewportMargins().left(),
            grid.viewportMargins().top(),
            grid.viewportMargins().right(),
            grid.viewportMargins().bottom(),
        ]
        if grid
        else None,
    }
    top_bar = getattr(sel, "_top_bar", None)
    bottom_bar = getattr(sel, "_bottom_bar", None)
    report["selector"]["top_bar_h"] = top_bar.height() if top_bar else None
    report["selector"]["bottom_bar_h"] = bottom_bar.height() if bottom_bar else None
    report["selector"]["children"] = []
    from PySide6.QtWidgets import QWidget

    for w in sel.findChildren(QWidget):
        if not w.isVisible():
            continue
        g = w.geometry()
        if g.width() <= 0 or g.height() <= 0:
            continue
        report["selector"]["children"].append(
            {
                "cls": type(w).__name__,
                "name": w.objectName(),
                "x": g.x(),
                "y": g.y(),
                "w": g.width(),
                "h": g.height(),
                "font_pt": w.font().pointSizeF(),
                "text": str(getattr(w, "text", lambda: "")())[:20] if hasattr(w, "text") else "",
            }
        )

    pool = FilePoolLayout()
    report["pool"] = _render(pool, out / "file_pool.png", (404, 700))

    prev = UnifiedPreviewerLayout()
    report["previewer"] = _render(prev, out / "unified_previewer.png", (500, 600))

    info = FileInfoPanel()
    report["info"] = _render(info, out / "file_info.png", (400, 520))

    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "children"} for k, v in report.items()}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
