#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量取组件令牌真值（字体度量 / 卡片尺寸 / 控件高度），供 promo 网页对齐。

不显示任何窗口，只创建 QApplication 并计算；输出 JSON。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"


def _ensure_importable() -> None:
    src = str(SRC_DIR)
    if src not in sys.path:
        sys.path.insert(0, src)


def main() -> int:
    _ensure_importable()

    from PySide6.QtGui import QFont, QFontMetrics
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])

    from sopeek.ui.components.file_card_delegate import CARD_CONFIG, LIST_CONFIG, FileCardDelegate
    from sopeek.ui.components.styled_button import StyledButton
    from sopeek.ui.components.styled_checkbox import StyledCheckbox
    from sopeek.ui.components.styled_combobox import StyledComboBox
    from sopeek.ui.components.styled_icon_button import StyledIconButton
    from sopeek.ui.components.styled_lineedit import StyledLineEdit
    from sopeek.ui.components.styled_textarea import StyledTextarea

    out: dict = {}

    fams = ["Microsoft YaHei UI", "Segoe UI", "Bahnschrift"]
    out["fonts"] = {}
    for fam in fams:
        row = {}
        for pt in (9, 10, 11, 12, 13, 14):
            fm = QFontMetrics(QFont(fam, pt))
            row[str(pt)] = {
                "px_height": fm.height(),
                "ascent": fm.ascent(),
                "descent": fm.descent(),
                "lineSpacing": fm.lineSpacing(),
                "digit_w": fm.horizontalAdvance("0"),
                "date_w": fm.horizontalAdvance("2024-12-31"),
            }
        out["fonts"][fam] = row

    out["card"] = {
        "config": CARD_CONFIG,
        "size": FileCardDelegate._calc_card_size(CARD_CONFIG, 1.0),
        "list_config": LIST_CONFIG,
        "list_size": FileCardDelegate._calc_list_size(LIST_CONFIG, 1.0),
    }

    def measure(widget) -> dict:
        return {
            "sizeHint": [widget.sizeHint().width(), widget.sizeHint().height()],
            "minimumSizeHint": [widget.minimumSizeHint().width(), widget.minimumSizeHint().height()],
            "minSize": [widget.minimumWidth(), widget.minimumHeight()],
            "font_pt": widget.font().pointSizeF(),
            "font_px": widget.font().pixelSize(),
        }

    buttons = {}
    for size in ("sm", "default", "lg"):
        b = StyledButton("生成缩略图", variant="primary", size=size)
        buttons[size] = measure(b)
    out["styled_button"] = buttons

    out["styled_icon_button"] = {
        s: measure(StyledIconButton(shape="square", size=s)) for s in ("sm", "default", "lg")
    }
    out["styled_lineedit"] = {s: measure(StyledLineEdit()) for s in ("sm", "default", "lg")}
    out["styled_textarea"] = {s: measure(StyledTextarea()) for s in ("sm", "default", "lg")}
    out["styled_combobox"] = {s: measure(StyledComboBox()) for s in ("sm", "default", "lg")}
    out["styled_checkbox"] = {s: measure(StyledCheckbox("标签")) for s in ("sm", "default", "lg")}

    text = json.dumps(out, ensure_ascii=False, indent=1)
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if target is not None:
        target.write_text(text, encoding="utf-8")
        print(f"[tokens] 已写入 {target}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

