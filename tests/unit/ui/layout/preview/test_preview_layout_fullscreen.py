"""
PreviewerLayout 全屏 detach/restore 共享测试

覆盖 font / image / pdf / text 四个非视频 previewer layout 的全屏按钮行为：
点击全屏时 layout 分离到独立 frameless 宿主窗口（PreviewFullscreenHost），
而不是全屏主窗口；退出时还原回原父布局的原位置；cleanup 时先退出全屏。
"""

import sys
from pathlib import Path

# Match the sys.path bootstrap in preview layout modules so sibling imports work.
_UI_ROOT = str(Path(__file__).resolve().parents[5] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from freeassetfilter.ui.layout.preview import (
    font_previewer_layout as fpl,
    image_previewer_layout as ipl,
    pdf_previewer_layout as ppl,
    text_previewer_layout as tpl,
)

PREVIEWER_CASES = [
    ("font", fpl.FontPreviewerLayout),
    ("image", ipl.ImagePreviewerLayout),
    ("pdf", ppl.PdfPreviewerLayout),
    ("text", tpl.TextPreviewerLayout),
]


def _make_previewer(cls):
    """构造 previewer 实例；缺少 native 依赖导致构造失败时跳过。"""
    try:
        return cls(standalone=True)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"{cls.__name__} 构造失败: {exc}")


@pytest.fixture
def container(qapp) -> tuple[QWidget, QVBoxLayout]:
    """创建容器窗口 + 布局，测试后清理。"""
    win = QWidget()
    layout = QVBoxLayout(win)
    yield win, layout
    win.close()
    win.deleteLater()
    QApplication.processEvents()


@pytest.mark.parametrize(
    "name,cls", PREVIEWER_CASES, ids=[case[0] for case in PREVIEWER_CASES]
)
class TestPreviewerLayoutFullscreen:
    """全屏进入/退出必须 detach 到独立 frameless 宿主并还原。"""

    def test_toggle_detaches_to_frameless_host(
        self, qapp, container, name: str, cls
    ) -> None:
        win, win_layout = container
        layout = _make_previewer(cls)
        win_layout.addWidget(layout)

        # 进入全屏：layout 移入独立 frameless 宿主，而不是全屏主窗口
        layout._on_maxsize_toggle()
        assert layout._fullscreen is True
        assert layout._fullscreen_host is not None
        assert layout.parentWidget() is layout._fullscreen_host
        assert layout.window() is layout._fullscreen_host
        assert layout._fullscreen_host.windowFlags() & Qt.FramelessWindowHint
        assert layout._fullscreen_host.isFullScreen()
        assert layout._maxsize_btn.toolTip() == "还原"
        # 容器窗口自身不被全屏化
        assert win.isFullScreen() is False

        # 退出全屏：还原回原父布局原位置
        layout._on_maxsize_toggle()
        assert layout._fullscreen is False
        assert layout._fullscreen_host is None
        assert layout.parentWidget() is win
        assert win_layout.indexOf(layout) == 0
        assert layout._maxsize_btn.toolTip() == "最大化"

        layout.close()
        layout.deleteLater()

    def test_cleanup_exits_fullscreen_first(
        self, qapp, container, name: str, cls
    ) -> None:
        win, win_layout = container
        layout = _make_previewer(cls)
        win_layout.addWidget(layout)

        layout._on_maxsize_toggle()
        assert layout._fullscreen is True
        # cleanup 时应先退出全屏再清理，避免 widget 随宿主一起销毁
        layout.cleanup()
        assert layout._fullscreen is False
        assert layout._fullscreen_host is None
        assert layout.parentWidget() is win
        assert win_layout.indexOf(layout) == 0

        layout.close()
        layout.deleteLater()
