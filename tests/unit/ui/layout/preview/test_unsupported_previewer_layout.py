"""不支持格式预览视图测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from sopeek.ui.layout.preview.unsupported_previewer_layout import (
    UnsupportedPreviewerLayout,
)


def test_displays_file_metadata(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "unknown.zzz"
    path.write_bytes(b"1234")
    widget = UnsupportedPreviewerLayout()
    widget.set_file({"path": str(path), "suffix": "zzz", "is_dir": False})

    assert widget._name_label.text() == "unknown.zzz"
    assert widget._description_label.text() == "当前文件无法在本软件中直接预览"
    assert widget._size_label.text() == "大小：4 B"
    assert widget._open_default_btn.sizePolicy().horizontalPolicy().name == "Fixed"
    assert widget._open_explorer_btn.sizePolicy().horizontalPolicy().name == "Fixed"
    assert widget._open_default_btn.width() >= widget._open_default_btn.sizeHint().width()
    assert widget._open_explorer_btn.width() >= widget._open_explorer_btn.sizeHint().width()
    assert "ZZZ" in widget._format_label.text()
    assert widget._open_default_btn.isEnabled()
    assert widget._open_explorer_btn.isEnabled()
    widget.deleteLater()


def test_explorer_uses_select_argument_on_windows(
    qapp: QApplication, tmp_path: Path,
) -> None:
    path = tmp_path / "unknown.zzz"
    path.write_bytes(b"x")
    widget = UnsupportedPreviewerLayout()
    widget.set_file({"path": str(path), "suffix": "zzz", "is_dir": False})

    with patch(
        "sopeek.ui.layout.preview.unsupported_previewer_layout.sys.platform",
        "win32",
    ), patch(
        "sopeek.ui.layout.preview.unsupported_previewer_layout.subprocess.Popen"
    ) as popen:
        widget.open_in_explorer()

    args, kwargs = popen.call_args
    assert args[0][0:2] == ["explorer", "/select,"]
    assert args[0][2] == str(path).replace("/", "\\")
    assert "creationflags" in kwargs
    widget.deleteLater()


def test_missing_file_disables_actions(qapp: QApplication) -> None:
    widget = UnsupportedPreviewerLayout()
    widget.set_file({"path": "C:/missing/unknown.zzz", "suffix": "zzz", "is_dir": False})
    assert widget._open_default_btn.isEnabled() is False
    assert widget._open_explorer_btn.isEnabled() is False
    widget.deleteLater()
