"""不支持格式文件的预览占位视图。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from components.styled_button import StyledButton
from freeassetfilter.services.file_icon_manager import FileIconManager
from freeassetfilter.services.file_info_service import classify_suffix, stat_basic
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss
from freeassetfilter.utils.app_logger import error
from theme import tm


class UnsupportedPreviewerLayout(QWidget):
    """显示不支持预览文件的图标、基本信息和快捷打开操作。"""

    accepts_file_info = True

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._file_info: Optional[dict] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(10)
        root.addStretch(1)

        self._icon_label = QLabel(self)
        self._icon_label.setObjectName("UnsupportedPreviewIcon")
        self._icon_label.setAlignment(Qt.AlignCenter)
        self._icon_label.setFixedSize(128, 128)
        self._icon_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        root.addWidget(self._icon_label, 0, Qt.AlignHCenter)

        self._name_label = QLabel(self)
        self._name_label.setObjectName("UnsupportedPreviewName")
        self._name_label.setAlignment(Qt.AlignCenter)
        self._name_label.setWordWrap(False)
        self._name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root.addWidget(self._name_label)

        self._description_label = QLabel("当前文件无法在本软件中直接预览", self)
        self._description_label.setObjectName("UnsupportedPreviewDescription")
        self._description_label.setAlignment(Qt.AlignCenter)
        self._description_label.setWordWrap(True)
        root.addWidget(self._description_label)

        self._size_label = QLabel(self)
        self._size_label.setObjectName("UnsupportedPreviewSize")
        self._size_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self._size_label)

        self._format_label = QLabel(self)
        self._format_label.setObjectName("UnsupportedPreviewFormat")
        self._format_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self._format_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 10, 0, 0)
        actions.setSpacing(8)
        self._open_default_btn = StyledButton(
            "使用系统默认方式打开", variant="secondary", size="sm"
        )
        self._open_default_btn.setObjectName("UnsupportedPreviewOpenDefault")
        self._open_default_btn.clicked.connect(self.open_with_system)
        actions.addWidget(self._open_default_btn)
        self._open_explorer_btn = StyledButton(
            "在资源管理器中打开", variant="primary", size="sm"
        )
        self._open_explorer_btn.setObjectName("UnsupportedPreviewOpenExplorer")
        self._open_explorer_btn.clicked.connect(self.open_in_explorer)
        actions.addWidget(self._open_explorer_btn)
        # 按钮按自身最小宽度组成紧凑操作组，整体居中，不在横向空间中均匀分散。
        root.addLayout(actions, 0)
        root.setAlignment(actions, Qt.AlignHCenter)
        root.addStretch(1)

        for button in (self._open_default_btn, self._open_explorer_btn):
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            button.setFixedWidth(button.sizeHint().width())
        self._apply_styles()
        tm.theme_changed.connect(self._on_theme_changed)

    def _apply_styles(self) -> None:
        """应用主题相关文字样式。"""
        register_widget_qss(
            self._name_label,
            f"color: {tm.text.name()}; font-size: 16px; font-weight: 600;",
        )
        secondary = (
            tm.alpha_of(tm.mid, 75) if tm.is_dark_theme() else tm.text_secondary
        ).name(QColor.NameFormat.HexArgb)
        register_widget_qss(
            self._description_label,
            f"color: {secondary}; font-size: 13px;",
        )
        register_widget_qss(
            self._size_label,
            f"color: {secondary}; font-size: 12px;",
        )
        register_widget_qss(
            self._format_label,
            f"color: {secondary}; font-size: 12px;",
        )

    def _on_theme_changed(self, _theme: str) -> None:
        """主题切换时刷新文字颜色。"""
        self._apply_styles()

    def set_file(self, file_info: str | dict) -> None:
        """设置待展示文件。"""
        if isinstance(file_info, str):
            path = file_info
            file_info = {
                "path": path,
                "suffix": Path(path).suffix.lstrip("."),
                "is_dir": False,
            }
        self._file_info = dict(file_info)
        path = str(self._file_info.get("path", ""))
        suffix = str(self._file_info.get("suffix", "")).lstrip(".")
        basic = stat_basic(path)
        name = str(self._file_info.get("name") or basic.get("name") or Path(path).name or path)
        size = self._file_info.get("size_str") or basic.get("size_str") or "-"
        category, extension = classify_suffix(suffix)
        format_text = f"格式：{category}（{extension}）" if extension else "格式：无扩展名"

        self._name_label.setText(name)
        self._name_label.setToolTip(name)
        self._size_label.setText(f"大小：{size}")
        self._format_label.setText(format_text)
        self._render_icon()
        exists = bool(path) and os.path.exists(path)
        self._open_default_btn.setEnabled(exists)
        self._open_explorer_btn.setEnabled(exists)

    def _render_icon(self) -> None:
        """获取并显示大尺寸文件图标。"""
        self._icon_label.clear()
        if not self._file_info:
            return
        try:
            pixmap = FileIconManager().get_icon_pixmap(
                self._file_info,
                112,
                self.devicePixelRatioF(),
            )
            if pixmap is not None and not pixmap.isNull():
                self._icon_label.setPixmap(pixmap)
        except Exception as exc:  # noqa: BLE001
            error(f"[UnsupportedPreviewerLayout] 文件图标生成失败: {exc}")

    def open_with_system(self) -> None:
        """使用操作系统默认关联打开文件。"""
        path = self._path()
        if not path:
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:  # noqa: BLE001
            error(f"[UnsupportedPreviewerLayout] 使用系统打开失败: {exc}")

    def open_in_explorer(self) -> None:
        """在资源管理器中打开并选中文件。"""
        path = self._path()
        if not path:
            return
        try:
            if sys.platform == "win32":
                subprocess.Popen(
                    ["explorer", "/select,", os.path.normpath(path)],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            elif sys.platform == "darwin":
                subprocess.Popen(["open", os.path.dirname(path)])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except Exception as exc:  # noqa: BLE001
            error(f"[UnsupportedPreviewerLayout] 在资源管理器中打开失败: {exc}")

    def _path(self) -> str:
        """返回存在的绝对文件路径。"""
        if not self._file_info:
            return ""
        path = os.path.abspath(str(self._file_info.get("path", "")))
        return path if os.path.exists(path) else ""

    def cleanup(self) -> None:
        """释放当前文件引用。"""
        self._file_info = None


__all__ = ["UnsupportedPreviewerLayout"]
