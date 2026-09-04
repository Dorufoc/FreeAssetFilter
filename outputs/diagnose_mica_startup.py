from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget

from freeassetfilter.ui.main_window import MainWindow
from freeassetfilter.ui.mica import winapi


OUTPUT_DIR = Path(__file__).resolve().parent


def geometry(widget: QWidget | None) -> dict[str, object] | None:
    if widget is None:
        return None
    geo = widget.geometry()
    frame = widget.frameGeometry()
    top_left = widget.mapToGlobal(widget.rect().topLeft())
    return {
        "type": type(widget).__name__,
        "object_name": widget.objectName(),
        "geometry": [geo.x(), geo.y(), geo.width(), geo.height()],
        "frame_geometry": [frame.x(), frame.y(), frame.width(), frame.height()],
        "rect": [widget.rect().x(), widget.rect().y(), widget.rect().width(), widget.rect().height()],
        "global_top_left": [top_left.x(), top_left.y()],
        "visible": widget.isVisible(),
        "native": widget.testAttribute(Qt.WidgetAttribute.WA_NativeWindow),
        "win_id": int(widget.winId()),
        "win32_rect": list(winapi.window_rect(int(widget.winId()))),
        "size_hint": [widget.sizeHint().width(), widget.sizeHint().height()],
        "minimum_size_hint": [widget.minimumSizeHint().width(), widget.minimumSizeHint().height()],
    }


def snapshot(window: MainWindow, label: str) -> None:
    try:
        QApplication.processEvents()
        title_bar = window.findChild(QWidget, "TitleBar")
        payload = {
            "label": label,
            "window": geometry(window),
            "root": geometry(window._root),
            "mica_background": geometry(window._mica_background),
            "content": geometry(window._content),
            "title_bar": geometry(title_bar),
            "splitter": geometry(window._splitter),
            "panel_left": geometry(window._panel_left),
            "panel_center": geometry(window._panel_center),
            "panel_right": geometry(window._panel_right),
            "file_selector": geometry(window._file_selector),
            "file_pool": geometry(window._file_pool),
            "previewer": geometry(window._previewer),
            "splitter_sizes": list(window._splitter.sizes()),
            "mica_window_rect": list(window._mica_background._mica._window_rect_tuple()),
            "mica_layer": None,
        }
        layer = window._mica_background._mica._layer
        if layer is not None:
            payload["mica_layer"] = {
                "region": list(layer.region),
                "width": layer.width,
                "height": layer.height,
                "win_size": list(layer.win_size),
            }
        (OUTPUT_DIR / f"mica_{label}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        screen = window.screen()
        if screen is not None:
            screen.grabWindow(int(window.winId())).save(str(OUTPUT_DIR / f"mica_{label}.png"), "PNG")
    except Exception:
        (OUTPUT_DIR / f"mica_{label}_error.txt").write_text(
            traceback.format_exc(), encoding="utf-8"
        )


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    app.aboutToQuit.connect(window._dispose_mica)
    window.show()

    QTimer.singleShot(2500, lambda: snapshot(window, "initial"))

    def resize_once() -> None:
        size = window.size()
        window.resize(size.width() + 1, size.height() + 1)
        QApplication.processEvents()
        window.resize(size)

    QTimer.singleShot(2700, resize_once)
    QTimer.singleShot(3500, lambda: snapshot(window, "after_resize"))
    QTimer.singleShot(3800, window.close)
    QTimer.singleShot(4000, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
