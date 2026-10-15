# -*- coding: utf-8 -*-
"""布局层单元测试（todo-23 批 3 / task-23）。

覆盖 ui/layout 下 11 个布局模块的构造契约、尺寸生效与 set_file 分发：
全部 QWidget 布局以默认参数构造、放入内容后 geometry 非空；
带 ``set_file`` 入口的布局对缺失路径安全降级（不抛异常、返回 False 或
停留在 overlay）；``PreviewFullscreenHost`` 在无父窗口时进出全屏不抛；
``VideoPlayerLayout`` 在无 libmpv 时不真实播放（缺失路径直接返回 False）。

验证命令：
    python -m pytest tests/unit/ui/layout/test_layouts.py --timeout 60 -q
"""

# targets: ui.layout.file_pool_layout, ui.layout.file_selector_layout,
#          ui.layout.settings_layout, ui.layout.unified_previewer_layout,
#          ui.layout.preview.font_previewer_layout,
#          ui.layout.preview.fullscreen_host,
#          ui.layout.preview.image_previewer_layout,
#          ui.layout.preview.office_previewer_layout,
#          ui.layout.preview.pdf_previewer_layout,
#          ui.layout.preview.text_previewer_layout,
#          ui.layout.preview.video_player_layout

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QEvent, QModelIndex, QPoint, QPointF, QObject, QRect, QSequentialAnimationGroup, Qt, QThread, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QEnterEvent,
    QHideEvent,
    QMouseEvent,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

# 布局模块内部使用短路径导入（from theme import tm / components.*），
# 要求 freeassetfilter/ui 位于 sys.path；与 layout/preview 模块自身的
# bootstrap 保持一致（详见 file_pool_layout.py:46 的用法）。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.layout.file_pool_layout import FilePoolLayout
from freeassetfilter.ui.layout.file_selector_layout import FileSelectorLayout
from freeassetfilter.ui.layout.preview.font_previewer_layout import (
    DEFAULT_PREVIEW_TEXT,
    FontLoadThread,
    FontPreviewerLayout,
)
from freeassetfilter.ui.layout.preview.fullscreen_host import PreviewFullscreenHost
from freeassetfilter.ui.layout.preview.image_previewer_layout import ImagePreviewerLayout
import freeassetfilter.ui.layout.preview.office_previewer_layout as _opl
from freeassetfilter.ui.layout.preview.office_previewer_layout import (
    OfficePreviewerLayout,
)
from freeassetfilter.ui.layout.preview.pdf_previewer_layout import PdfPreviewerLayout
from freeassetfilter.ui.layout.preview.text_previewer_layout import TextPreviewerLayout
import freeassetfilter.ui.layout.preview.text_previewer_layout as _tpl
from freeassetfilter.ui.layout.preview.video_player_layout import VideoPlayerLayout
from freeassetfilter.ui.layout.preview.unsupported_previewer_layout import (
    UnsupportedPreviewerLayout,
)
from freeassetfilter.ui.layout.settings_layout import (
    AccentColorButton,
    AppearanceSettingsPage,
    CustomAccentButton,
    GeneralSettingsPage,
    SettingsLayout,
)
from freeassetfilter.ui.layout.unified_previewer_layout import UnifiedPreviewerLayout

from tests.support.qt_helpers import safe_teardown, wait_until  # noqa: E402

pytestmark = pytest.mark.unit

_MISSING_FILE: str = "C:/definitely/missing_file.xyz"
_LAYOUT_SIZE: tuple[int, int] = (640, 480)

#: 一张最小 1x1 PNG 的字节内容（用作 todo-30 音频封面 / 调色板输入）。
_MINI_PNG_BYTES: bytes = (
    b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00\x00\x00\x01"
    + b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0c"
    + b"IDAT\x08\xd7c\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01" + b"4\x8f\x88"
    + b"\x7d\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _FakeAudioInfo:
    """模拟 ``mutagen`` 音频对象的 ``.info``（编码参数）。"""

    def __init__(self) -> None:
        """初始化最小参数（时长/比特率/声道/采样率）。"""
        self.length = 3.5
        self.bitrate = 128000
        self.channels = 2
        self.sample_rate = 44100


class _FakeFrame:
    """模拟 ID3 / APIC frame 对象：带二进制 ``.data``。"""

    def __init__(self, data: Optional[bytes] = None) -> None:
        """初始化假 frame。

        Args:
            data: 二进制负载（封面用）。
        """
        self.data: Optional[bytes] = data


class _FakeAudio:
    """模拟 ``mutagen.File`` 的返回值（dict 风格 tags + info）。"""

    def __init__(self, tags: Optional[Dict[str, Any]] = None,
                 info: Optional[Any] = None) -> None:
        """初始化假音频对象。

        Args:
            tags: 标签容器（dict 风格）。
            info: 信息对象。
        """
        self.tags: Optional[Dict[str, Any]] = tags
        self.info: Optional[Any] = info or _FakeAudioInfo()


class _CountingMarkdownRenderer:
    """Markdown 渲染测试替身：记录 render() 调用次数与最后一次字号。

    与真实 ``MarkdownRenderer`` 保持同一构造/调用契约（``font_size`` 关键字、
    ``is_available()``、``set_font_size()``、``render(text, file_path)``），
    供字号防抖与异步渲染计数断言使用。渲染返回内嵌字号与输入长度的
    可断言内容。
    """

    call_count = 0
    last_font_size: Optional[int] = None

    def __init__(self, font_size: int = 14) -> None:
        """与真实渲染器一致的构造契约。"""
        self._font_size = font_size

    @classmethod
    def is_available(cls) -> bool:
        """模拟 markdown + pygments 可用。"""
        return True

    def set_font_size(self, size: int) -> None:
        """与真实渲染器一致的字号设置。"""
        self._font_size = size

    def render(self, text: str, file_path: Optional[str] = None) -> str:
        """返回内嵌字号与输入长度的可断言 HTML。"""
        _CountingMarkdownRenderer.call_count += 1
        _CountingMarkdownRenderer.last_font_size = self._font_size
        return f"<p>rendered-{self._font_size}:{len(text)}</p>"


class _SlowMarkdownRenderer:
    """Markdown 渲染测试替身：``SLOW`` 输入时阻塞 400ms 模拟慢渲染。

    用于「快速切换文件 → 陈旧 token 丢弃旧渲染结果」的时序验证。
    """

    def __init__(self, font_size: int = 14) -> None:
        """与真实渲染器一致的构造契约。"""
        self._font_size = font_size

    @classmethod
    def is_available(cls) -> bool:
        """模拟 markdown + pygments 可用。"""
        return True

    def set_font_size(self, size: int) -> None:
        """与真实渲染器一致的字号设置。"""
        self._font_size = size

    def render(self, text: str, file_path: Optional[str] = None) -> str:
        """慢路径 sleep 后返回文本透传内容。"""
        if "SLOW" in text:
            time.sleep(0.4)
        return f"<p>out-{text}</p>"


def _assert_layout_geometry(widget: QWidget, qapp: QApplication) -> None:
    """宿主 resize 后 geometry 有效（尺寸用例的公共断言）。"""
    widget.resize(*_LAYOUT_SIZE)
    qapp.processEvents()
    assert widget.width() > 0
    assert widget.height() == 480


def _pump_events(qapp: QApplication, ms: float = 300) -> None:
    """有界事件泵：让布局/尺寸事件与重绘完成。"""
    deadline = time.time() + ms / 1000
    while time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)


def _pump_until(
    qapp: QApplication,
    predicate: Any,
    timeout_ms: int = 3000,
) -> bool:
    """有界事件泵直到谓词成立（供异步 Markdown 渲染结果回写等待）。"""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _normalize_eol(text: str) -> str:
    """将期望文本的 CRLF 归一为 LF（与 QTextDocument/toPlainText 行为一致）。

    夹具若在检出时被行尾转换（如 Windows autocrlf）带 CRLF，QTextEdit
    读入后会归一为 LF，直接逐字比较将永远不相等。期望侧先做同样归一，
    保证断言只校验内容本身、不依赖检出环境。
    """
    return text.replace("\r\n", "\n")


# =============================================================================
# ui.layout.file_pool_layout
# =============================================================================
class TestFilePoolLayout:
    """文件池布局：构造契约、add_file 入池与尺寸生效。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = FilePoolLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_add_file_and_query(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """add_file 入池后 has_file / get_pool_paths 可见，可安全移除。"""
        # 禁用删除动画，使 remove_file 同步完成（否则经 _removing_paths 异步走）
        import freeassetfilter.ui.layout.file_pool_layout as fpl_mod

        monkeypatch.setattr(
            fpl_mod, "is_animation_enabled", lambda *args, **kwargs: False
        )
        layout = FilePoolLayout()
        _assert_layout_geometry(layout, qapp)
        file_path = "D:/dummy/file_pool_sample.png"
        layout.add_file({"path": file_path, "name": "file_pool_sample.png"})
        assert layout.has_file(file_path) is True
        assert file_path.replace("/", "\\") in layout.get_pool_paths() or file_path in layout.get_pool_paths()
        layout.remove_file(file_path)
        assert layout.has_file(file_path) is False
        layout.deleteLater()

    def test_grid_removal_shrink_and_smooth_fill(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """New 布局网格移除：原地缩小渐隐（card_shrink + 淡出）+ 其余卡片同期平滑补位。"""
        import freeassetfilter.ui.layout.file_pool_layout as fpl_mod

        monkeypatch.setattr(fpl_mod, "is_animation_enabled", lambda *a, **k: True)
        layout = FilePoolLayout()
        layout.resize(600, 420)
        layout.show()
        _pump_events(qapp, 100)

        paths = [os.path.normpath(f"D:/dummy/grid_anim_{i}.png") for i in range(7)]
        for path in paths:
            layout.add_file({"path": path, "name": os.path.basename(path)})
        _pump_events(qapp)
        layout.set_view_mode("grid")
        _pump_events(qapp)

        cards = layout._card_widgets
        before = {p: QRect(cards[p].geometry()) for p in paths}
        target = paths[2]

        layout.remove_file(target)
        assert _pump_until(
            qapp, lambda: target in layout._active_card_animations, timeout_ms=1000
        )

        # 退出动画：绘制级 card_shrink + card_opacity，几何固定在原位（不左滑）
        assert target in layout._removing_paths
        info = layout._active_card_animations.get(target)
        assert info is not None and info["kind"] == "exit"
        exit_group = info["group"]
        exit_props = {
            bytes(exit_group.animationAt(i).propertyName())
            for i in range(exit_group.animationCount())
        }
        assert exit_props == {b"card_shrink", b"card_opacity"}
        assert cards[target].geometry() == before[target]

        # 补位动画：级联结构 = [QPauseAnimation(起步延迟 + 错峰)] + geometry 移动
        fill_group = layout._grid_fill_group
        assert fill_group is not None
        fill_delays: list[int] = []
        for index in range(fill_group.animationCount()):
            seq = fill_group.animationAt(index)
            assert isinstance(seq, QSequentialAnimationGroup)
            move_anim = seq.animationAt(seq.animationCount() - 1)
            assert bytes(move_anim.propertyName()) == b"geometry"
            fill_delays.append(
                sum(
                    seq.animationAt(j).duration()
                    for j in range(seq.animationCount() - 1)
                )
            )
        # 起步延迟 50ms、逐格 +12ms、封顶 98ms；紧邻空位者最先启动
        assert fill_delays
        assert min(fill_delays) == 50
        assert max(fill_delays) <= 98

        assert _pump_until(qapp, lambda: target not in layout._removing_paths)
        _pump_events(qapp, 250)

        # 结束态：卡片已移除、补位完成、后续卡片左移填满且布局稳定无残余空位
        assert layout.has_file(target) is False
        assert layout._grid_fill_group is None
        assert cards[paths[3]].x() == before[paths[2]].x()
        assert cards[paths[4]].x() == before[paths[3]].x()
        positions = {p: (c.x(), c.y()) for p, c in cards.items()}
        layout._card_layout.activate()
        assert {p: (c.x(), c.y()) for p, c in cards.items()} == positions
        layout.deleteLater()

    def test_grid_batch_removal_stays_contiguous(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """网格批量移出：多轮补位互不叠加，剩余卡片最终连续排布无空位。"""
        import freeassetfilter.ui.layout.file_pool_layout as fpl_mod

        monkeypatch.setattr(fpl_mod, "is_animation_enabled", lambda *a, **k: True)
        layout = FilePoolLayout()
        layout.resize(600, 420)
        layout.show()
        _pump_events(qapp, 100)

        paths = [os.path.normpath(f"D:/dummy/grid_batch_{i}.png") for i in range(9)]
        for path in paths:
            layout.add_file({"path": path, "name": os.path.basename(path)})
        _pump_events(qapp)
        layout.set_view_mode("grid")
        _pump_events(qapp)

        cards = layout._card_widgets
        row_y = cards[paths[0]].y()
        removed = (paths[1], paths[3], paths[5])
        for path in removed:
            layout.remove_file(path)

        assert _pump_until(
            qapp,
            lambda: all(p not in layout._removing_paths for p in removed),
        )
        _pump_events(qapp, 250)

        assert layout._grid_fill_group is None
        remaining = [p for p in paths if p not in removed]
        assert set(cards) == set(remaining)
        # 第一行剩余卡片从左起连续排布：相邻卡片间距 = 列宽 + 网格间距
        first_row_xs = sorted(c.x() for c in cards.values() if c.y() == row_y)
        col_w = cards[paths[0]].width()
        spacing = layout._card_layout.spacing()
        assert len(first_row_xs) > 1
        for left, right in zip(first_row_xs, first_row_xs[1:]):
            assert right - left == col_w + spacing
        # 布局稳定：强制重排不再移动任何卡片
        positions = {p: (c.x(), c.y()) for p, c in cards.items()}
        layout._card_layout.activate()
        assert {p: (c.x(), c.y()) for p, c in cards.items()} == positions
        layout.deleteLater()

    def test_list_removal_keeps_slide_animation(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """经典列表移除保持左滑 + 占位折叠：退出动画不引入 card_shrink。"""
        import freeassetfilter.ui.layout.file_pool_layout as fpl_mod

        monkeypatch.setattr(fpl_mod, "is_animation_enabled", lambda *a, **k: True)
        layout = FilePoolLayout()
        layout.resize(*_LAYOUT_SIZE)
        layout.show()
        _pump_events(qapp, 100)

        paths = [os.path.normpath(f"D:/dummy/list_anim_{i}.png") for i in range(3)]
        for path in paths:
            layout.add_file({"path": path, "name": os.path.basename(path)})
        _pump_events(qapp)

        assert layout.get_view_mode() == "list"
        cards = layout._card_widgets
        target = paths[1]
        y_before = cards[paths[2]].y()

        layout.remove_file(target)
        assert _pump_until(
            qapp, lambda: target in layout._active_card_animations, timeout_ms=1000
        )
        info = layout._active_card_animations.get(target)
        assert info is not None and info["kind"] == "exit"
        group = info["group"]
        props = {
            bytes(group.animationAt(i).propertyName())
            for i in range(group.animationCount())
        }
        assert b"geometry" in props
        assert b"card_opacity" in props
        assert b"card_shrink" not in props

        assert _pump_until(qapp, lambda: target not in layout._removing_paths)
        _pump_events(qapp, 300)
        assert layout.has_file(target) is False
        assert cards[paths[2]].y() < y_before  # 下方卡片整体上移
        layout.deleteLater()

    def test_grid_view_mode_layout_and_scale(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """New 布局网格：瓦片卡、与选择器同款列宽算法、默认最小缩放。"""
        import freeassetfilter.ui.layout.file_pool_layout as fpl_mod

        monkeypatch.setattr(
            fpl_mod, "is_animation_enabled", lambda *args, **kwargs: False
        )
        layout = FilePoolLayout()
        layout.resize(515, 250)
        layout.show()
        _pump_events(qapp)

        assert layout.get_view_mode() == "list"
        assert layout._card_scale == 1.0

        for i in range(5):
            layout.add_file({"path": f"D:/dummy/pool_{i}.png", "name": f"pool_{i}.png"})
        _pump_events(qapp)

        layout.set_view_mode("grid")
        _pump_events(qapp)

        assert layout.get_view_mode() == "grid"
        # 网格默认最小缩放
        assert layout._card_scale == layout._card_scale_min
        cards = list(layout._card_widgets.values())
        assert cards
        # 平铺瓦片：竖向形态、无悬浮操作、tooltip 提供完整路径
        assert all(card._layout_mode == "vertical" for card in cards)
        assert all(card._tile_style is True for card in cards)
        assert all(len(card._actions) == 0 for card in cards)
        assert all(card.toolTip() for card in cards)
        # 列宽/列数与选择器同款算法（calc_grid_cell）一致，且卡片定宽
        from components.file_card_delegate import (
            CARD_CONFIG,
            FileCardDelegate,
            calc_grid_base_width,
            calc_grid_cell,
        )

        margins = layout._card_layout.contentsMargins()
        available = max(
            0,
            layout._scroll_area.viewport().width()
            - margins.left()
            - margins.right(),
        )
        base = int(calc_grid_base_width(layout.font()) * layout._card_scale)
        cols, expect_w = calc_grid_cell(available, base, 4)
        assert len({card.width() for card in cards}) == 1
        assert cards[0].width() == expect_w
        assert len({card.x() for card in cards}) == min(cols, len(cards))
        # 卡高与选择器网格卡一致（CARD_CONFIG 规格）
        _, expect_h = FileCardDelegate._calc_card_size(
            CARD_CONFIG, layout._card_scale
        )
        assert cards[0].height() == expect_h
        assert layout._card_container.minimumHeight() > 0

        # 切回列表：恢复信息卡（路径副标题 + 悬浮重命名/删除），网格缩放被记忆
        layout.set_view_mode("list")
        _pump_events(qapp)
        assert layout.get_view_mode() == "list"
        assert layout._card_scale == 1.0
        assert all(card._layout_mode == "horizontal" for card in cards)
        assert all(card._tile_style is False for card in cards)
        assert all(len(card._actions) == 2 for card in cards)
        assert all(not card.toolTip() for card in cards)

        layout.set_view_mode("grid")
        _pump_events(qapp)
        assert layout._card_scale == layout._card_scale_min
        layout.deleteLater()

    def test_grid_mode_new_cards_use_fixed_width(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """先切网格再加入的卡片：平铺瓦片 + 固定列宽 + 无悬浮操作。"""
        import freeassetfilter.ui.layout.file_pool_layout as fpl_mod

        monkeypatch.setattr(
            fpl_mod, "is_animation_enabled", lambda *args, **kwargs: False
        )
        layout = FilePoolLayout()
        layout.resize(443, 250)
        layout.show()
        _pump_events(qapp)

        layout.set_view_mode("grid")
        layout.add_file({"path": "D:/dummy/grid_new.png", "name": "grid_new.png"})
        _pump_events(qapp)

        card = next(iter(layout._card_widgets.values()))
        assert card._layout_mode == "vertical"
        assert card._tile_style is True
        assert card.minimumWidth() == card.maximumWidth()
        assert len(card._actions) == 0
        assert card.toolTip() == "D:/dummy/grid_new.png"
        layout.deleteLater()

    def test_empty_pool_hint_visibility(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """空池提示：无卡片时铺满视口居中可见，入池后隐藏、移除后恢复。

        两种布局模式（经典列表 / New 网格）共用同一 FilePoolLayout 实例，
        提示随之同时覆盖两种布局；切换视图模式不重建提示控件。
        """
        import freeassetfilter.ui.layout.file_pool_layout as fpl_mod

        monkeypatch.setattr(
            fpl_mod, "is_animation_enabled", lambda *args, **kwargs: False
        )
        layout = FilePoolLayout()
        layout.resize(*_LAYOUT_SIZE)
        layout.show()
        _pump_events(qapp)

        hint = layout._empty_hint
        assert hint.text() == "右键选择区卡片以添加文件"
        assert hint.isVisible() is True
        # 鼠标事件透传：不拦截框选/右键/滚轮语义
        assert hint.testAttribute(Qt.WA_TransparentForMouseEvents) is True
        # 铺满滚动视口并由 AlignCenter 居中
        viewport = layout._scroll_area.viewport()
        assert hint.geometry() == viewport.rect()
        assert hint.alignment() == Qt.AlignCenter

        # 切换网格视图（New 布局）后仍是同一提示实例
        layout.set_view_mode("grid")
        _pump_events(qapp)
        assert layout._empty_hint is hint

        file_path = "D:/dummy/empty_hint_sample.png"
        layout.add_file({"path": file_path, "name": "empty_hint_sample.png"})
        _pump_events(qapp)
        assert hint.isVisible() is False

        layout.remove_file(file_path)
        _pump_events(qapp)
        assert hint.isVisible() is True

        layout.deleteLater()

    def test_section_styles_fragment_keeps_sheet_parseable(
        self, qapp: QApplication
    ) -> None:
        """回归：内容区「面板样式 + 拖放反馈」同片段注册后无畸形规则。

        历史缺陷：``content_style`` 直接拼接「裸声明 + QFrame[dragActive]
        规则」，``scope_qss`` 会把声明里 rgba(...) 的逗号当选择器分隔符切碎，
        生成畸形规则；Qt 解析器遇到畸形规则会丢弃整张样式表其后内容
        （症状：储存池内容区/底栏/空池提示整体失去边框与填充）。

        下发模式无关断言：``build_combined``（作用域合并渲染，app 模式实际
        下发内容 / widget 模式的诊断视图）无畸形文本；widget 模式下片段
        已直接落在控件自身。
        """
        from freeassetfilter.ui.theme.app_stylesheet import (
            _REGISTRY,
            stylesheet_mode,
        )

        layout = FilePoolLayout()
        layout.set_section_styles(
            "rgba(255,255,255,0.05)", "rgba(136,136,136,0.5)"
        )
        # 让合并重排的 singleShot 落地（app 模式的统一下发入口）
        _pump_events(qapp)
        sheet = _REGISTRY.build_combined()

        content_sid = layout._content_area.property("fafQssId")
        bar_sid = layout._bottom_bar.property("fafQssId")
        assert content_sid and bar_sid

        if stylesheet_mode() == "widget":
            # 逐控件下发：片段原文落在控件自身，且内容/底栏互不串扰。
            own = layout._content_area.styleSheet()
            assert "background-color: rgba(255,255,255,0.05);" in own
            assert 'dragActive="true"' in own
            assert 'fafQssId' not in own
            layout.deleteLater()
            return

        def _fragment(sid: str) -> str:
            """截取组合样式表中某控件片段（按 faf 注释标记分段）。"""
            marker = f"/* faf:{sid} */"
            start = sheet.find(marker)
            assert start != -1, f"片段 {sid} 未进入组合样式表"
            nxt = sheet.find("/* faf:", start + len(marker))
            return sheet[start + len(marker) : nxt if nxt != -1 else len(sheet)]

        content_fragment = _fragment(content_sid)
        # 畸形规则签名：作用域链后直接跟声明文本（rgba 逗号被当选择器分隔）
        assert '"] background-color' not in content_fragment
        assert '"] border' not in content_fragment
        # 面板声明与拖放反馈规则都在，且声明值未被切断
        assert "background-color: rgba(255,255,255,0.05);" in content_fragment
        assert "border: 1px solid rgba(136,136,136,0.5);" in content_fragment
        assert 'dragActive="true"' in content_fragment
        # 拖放虚线边框跟随强调色（不再写死 #4a90d9）
        from theme import tm as _tm

        assert f"border: 2px dashed {_tm.qss_color(_tm.accent)};" in content_fragment
        # 底栏（同深度、后注册）片段完整保留，不被内容区片段连累
        assert "background-color: rgba(255,255,255,0.05);" in _fragment(bar_sid)
        layout.deleteLater()

    def test_drag_feedback_toggles_dynamic_property(self, qapp: QApplication) -> None:
        """拖放反馈：``dragActive`` 动态属性切换（虚线边框规则的命中条件）。

        样式规则 ``QFrame[dragActive="true"]`` 已随面板片段注册；
        此处只验证属性切换契约（进入拖拽 True / 离开与落下 False，幂等）。
        """
        layout = FilePoolLayout()
        area = layout._content_area
        assert bool(area.property("dragActive")) is False

        layout._set_drag_feedback(True)
        assert bool(area.property("dragActive")) is True
        # 幂等：重复置位不改变状态
        layout._set_drag_feedback(True)
        assert bool(area.property("dragActive")) is True

        layout._set_drag_feedback(False)
        assert bool(area.property("dragActive")) is False
        layout.deleteLater()


def _legacy_unique_target(directory: str, filename: str) -> str:
    """改造前冲突改名算法（oracle，等价 ``_get_unique_target_path``）。"""
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base}_{counter}{ext}")
        counter += 1
    return candidate


def _legacy_export_flat(files: list, target_dir: str) -> tuple:
    """改造前 ``copy_files`` 逐文件顺序复制（语义 oracle）。"""
    success = 0
    failed = 0
    errors = []
    for i, fi in enumerate(files):
        src = fi.get("path", "")
        display_name = fi.get("display_name", os.path.basename(src))
        dst = _legacy_unique_target(target_dir, display_name)
        try:
            if fi.get("is_dir"):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
            success += 1
        except (IOError, OSError, PermissionError, shutil.Error) as e:
            failed += 1
            errors.append(f"{fi.get('display_name', '?')}: {e}")
    return success, failed, errors


def _legacy_export_categorized(files: list, target_dir: str) -> tuple:
    """改造前 ``copy_files_categorized``（语义 oracle）。"""
    success = 0
    failed = 0
    errors = []
    for i, fi in enumerate(files):
        src = fi.get("path", "")
        source_dir = os.path.dirname(src)
        category = os.path.basename(source_dir) or "未分类"
        cat_dir = os.path.join(target_dir, category)
        try:
            os.makedirs(cat_dir, exist_ok=True)
        except (IOError, OSError) as e:
            failed += 1
            errors.append(f"{fi.get('display_name', '?')}: 创建分类目录失败 - {e}")
            continue
        dst = os.path.join(cat_dir, fi.get("display_name", os.path.basename(src)))
        dst = _legacy_unique_target(cat_dir, os.path.basename(dst))
        try:
            if fi.get("is_dir"):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
            success += 1
        except (IOError, OSError, PermissionError, shutil.Error) as e:
            failed += 1
            errors.append(f"{fi.get('display_name', '?')}: {e}")
    return success, failed, errors


def _snapshot_tree(root: str) -> Dict[str, bytes]:
    """递归快照目录树：相对路径 → 文件字节（不含目录条目）。"""
    snap: Dict[str, bytes] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            with open(full, "rb") as f:
                snap[rel] = f.read()
    return snap


class _FakeBridge:
    """faf_core 桥确定性替身（语义等价 native 批量复制 / 大小聚合）。

    - ``copy_files`` 记录每次调用（批次）并做真实 ``copy2/copytree``
      （目标名 = 源文件名），返回 ``{"copied","failed"}``；
    - ``available=False`` 时模拟 DLL 缺失（调用方回退 Python）；
    - ``gate`` 钩子在每次批量调用开始时触发（批次间取消测试用）。
    """

    def __init__(self, available: bool = True) -> None:
        self.available = available
        self._supports_copy = available
        self._supports_sizesum = available
        self.calls: List[List[str]] = []
        self.fail_all = False
        self.gate = None

    def copy_files(self, sources: list, dest_dir: str):
        batch = list(sources)
        self.calls.append(batch)
        if self.fail_all:
            return None
        if self.gate is not None:
            self.gate(len(self.calls))
        copied = []
        failed = []
        for src in sources:
            try:
                name = os.path.basename(src)
                dst = os.path.join(dest_dir, name)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
                copied.append(
                    {"src": src, "dst": dst, "size": os.path.getsize(src)}
                )
            except Exception as e:  # noqa: BLE001  # per-file 失败不中断整批
                failed.append({"src": src, "error": str(e)})
        return {"copied": copied, "failed": failed}

    def sum_directory_sizes(self, paths: list):
        results = []
        for p in paths:
            try:
                total = 0
                for dirpath, _dirs, files in os.walk(p):
                    for name in files:
                        try:
                            total += os.path.getsize(os.path.join(dirpath, name))
                        except OSError:
                            continue
                results.append({"path": p, "size": total, "error": None})
            except OSError as e:
                results.append({"path": p, "size": 0, "error": str(e)})
        return {"results": results}


def _patch_fpl_bridge(monkeypatch: pytest.MonkeyPatch, bridge) -> Any:
    """替换 ``file_pool_layout`` 模块内的 ``get_faf_core_bridge``。"""
    import freeassetfilter.ui.layout.file_pool_layout as fpl_mod

    monkeypatch.setattr(fpl_mod, "get_faf_core_bridge", lambda: bridge)
    return fpl_mod


def _export_items(tmp_path: Path) -> List[Dict[str, str]]:
    """构造一组含同名冲突/自定义 display_name 的导出项。"""
    dir1 = tmp_path / "dir1"
    dir1.mkdir()
    (dir1 / "a.txt").write_bytes(b"content-A")
    (dir1 / "b.txt").write_bytes(b"content-B")
    dir2 = tmp_path / "dir2"
    dir2.mkdir()
    (dir2 / "a.txt").write_bytes(b"content-A2")
    tree = dir1 / "tree"
    (tree / "sub").mkdir(parents=True)
    (tree / "sub" / "leaf.txt").write_bytes(b"leaf")
    return [
        {"path": str(dir1 / "a.txt"), "display_name": "a.txt"},
        {"path": str(dir2 / "a.txt"), "display_name": "a.txt"},  # 同名冲突
        {"path": str(dir1 / "b.txt"), "display_name": "b.txt"},
        {"path": str(dir1 / "b.txt"), "display_name": "rename.txt"},  # 自定义名
        {"path": str(tree), "display_name": "tree", "is_dir": True},  # 目录项
    ]


class TestFilePoolLayoutExport:
    """导出复制接线：native 分批 / 冲突改名 / 错误元组顺序 / 进度单调 / 取消。"""

    def test_export_batches_capped_at_32(self, qapp: QApplication,
                                         monkeypatch: pytest.MonkeyPatch,
                                         tmp_path: Path) -> None:
        """native 批 ≤32/批：70 文件 → 3 批（32/32/6），全部落地且批尺寸合规。"""
        src = tmp_path / "src"
        src.mkdir()
        files = []
        for i in range(70):
            f = src / f"f{i:02}.txt"
            f.write_bytes(bytes(100 + i))
            files.append({"path": str(f), "display_name": f.name})
        bridge = _FakeBridge(available=True)
        _patch_fpl_bridge(monkeypatch, bridge)
        out = tmp_path / "out"
        out.mkdir()
        layout = FilePoolLayout()
        s, f, e = layout.copy_files(files, str(out))
        assert s == 70 and f == 0 and e == []
        assert bridge.calls, "native 路径应被调用"
        for batch in bridge.calls:
            assert len(batch) <= 32, "单批不得超过 _EXPORT_BATCH_SIZE"
        assert len(bridge.calls) == 3, "70 文件应分 3 批（32/32/6）"
        assert len(os.listdir(out)) == 70

    def test_export_conflict_rename_matches_legacy(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """冲突改名结果与改造前字节一致（native 可用 / 假桥 / DLL 缺失三态）。"""
        from freeassetfilter.core.native.bridges.faf_core_bridge import (
            FafCoreBridge,
        )

        cases = [
            ("fallback", _FakeBridge(available=False)),
            ("native-fake", _FakeBridge(available=True)),
        ]
        if FafCoreBridge().available and FafCoreBridge()._supports_copy:  # noqa: SLF001
            cases.append(("native-real", None))

        # 目标目录里预置同名文件，进一步触发改名链。
        items = _export_items(tmp_path)
        for label, bridge in cases:
            out_new = tmp_path / f"out_new_{label}"
            out_new.mkdir()
            (out_new / "a.txt").write_bytes(b"preexisting")
            out_legacy = tmp_path / f"out_legacy_{label}"
            out_legacy.mkdir()
            (out_legacy / "a.txt").write_bytes(b"preexisting")

            if bridge is None:
                # 真实 DLL 路径：恢复真正的单例取回器。
                import freeassetfilter.ui.layout.file_pool_layout as fpl_mod
                from freeassetfilter.core.native.bridges.faf_core_bridge import (
                    get_faf_core_bridge as _real_getter,
                )

                monkeypatch.setattr(
                    fpl_mod, "get_faf_core_bridge", lambda: _real_getter()
                )
            else:
                _patch_fpl_bridge(monkeypatch, bridge)
            layout = FilePoolLayout()
            s_new, f_new, e_new = layout.copy_files(items, str(out_new))
            s_leg, f_leg, e_leg = _legacy_export_flat(items, str(out_legacy))

            assert s_new == s_leg, f"[{label}] 成功数与 oracle 不一致: {s_new} vs {s_leg}"
            assert f_new == f_leg, f"[{label}] 失败数与 oracle 不一致: {f_new} vs {f_leg}"
            assert _snapshot_tree(str(out_new)) == _snapshot_tree(
                str(out_legacy)
            ), f"[{label}] 导出结果与 oracle 字节不一致"
            # 错误元组顺序：仅比较失败的 display 名序列（native 错误串不参与）。
            failed_names_new = [err.split(":")[0] for err in e_new]
            failed_names_leg = [err.split(":")[0] for err in e_leg]
            assert failed_names_new == failed_names_leg, (
                f"[{label}] 错误元组顺序不一致: {failed_names_new} vs {failed_names_leg}"
            )

    def test_export_categorized_matches_legacy(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """分类导出的结果与改造前字节一致（含类目内同名冲突）。"""
        bridge = _FakeBridge(available=True)
        _patch_fpl_bridge(monkeypatch, bridge)
        items = _export_items(tmp_path)
        out_new = tmp_path / "out_new"
        out_new.mkdir()
        out_legacy = tmp_path / "out_legacy"
        out_legacy.mkdir()
        layout = FilePoolLayout()
        s_new, f_new, _ = layout.copy_files_categorized(items, str(out_new))
        s_leg, f_leg, _ = _legacy_export_categorized(items, str(out_legacy))
        assert s_new == s_leg and f_new == f_leg
        assert _snapshot_tree(str(out_new)) == _snapshot_tree(str(out_legacy))

    def test_export_error_tuple_order_consistent(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """错误元组 (success, failed, errors) 顺序与输入序一致（native 与回退）。"""
        src = tmp_path / "src"
        src.mkdir()
        ok1 = src / "ok1.txt"
        ok1.write_bytes(b"1")
        ok2 = src / "ok2.txt"
        ok2.write_bytes(b"2")
        missing1 = tmp_path / "ghost1.txt"
        missing2 = tmp_path / "ghost2.txt"
        files = [
            {"path": str(ok1), "display_name": "ok1.txt"},
            {"path": str(missing1), "display_name": "ghost1.txt"},
            {"path": str(ok2), "display_name": "ok2.txt"},
            {"path": str(missing2), "display_name": "ghost2.txt"},
        ]
        bridge = _FakeBridge(available=True)
        _patch_fpl_bridge(monkeypatch, bridge)
        out = tmp_path / "out"
        out.mkdir()
        layout = FilePoolLayout()
        s, f, e = layout.copy_files(files, str(out))
        assert s == 2 and f == 2
        assert [err.split(":")[0] for err in e] == ["ghost1.txt", "ghost2.txt"]

        # 回退路径同构。
        out2 = tmp_path / "out2"
        out2.mkdir()
        bridge2 = _FakeBridge(available=False)
        _patch_fpl_bridge(monkeypatch, bridge2)
        layout2 = FilePoolLayout()
        s2, f2, e2 = layout2.copy_files(files, str(out2))
        assert s2 == 2 and f2 == 2
        assert [err.split(":")[0] for err in e2] == ["ghost1.txt", "ghost2.txt"]

    def test_export_progress_monotonic(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """进度信号计数单调递增且终结于 len(files)（native 分批补发）。"""
        src = tmp_path / "src"
        src.mkdir()
        files = []
        for i in range(40):
            f = src / f"f{i:02}.txt"
            f.write_bytes(bytes(10))
            files.append({"path": str(f), "display_name": f.name})
        bridge = _FakeBridge(available=True)
        _patch_fpl_bridge(monkeypatch, bridge)
        out = tmp_path / "out"
        out.mkdir()
        layout = FilePoolLayout()
        got: List[int] = []
        layout.update_progress.connect(lambda v: got.append(int(v)))
        layout.copy_files(files, str(out))
        assert len(got) == len(files)
        assert all((got[i + 1] - got[i]) >= 1 for i in range(len(got) - 1)), (
            "进度必须单调递增"
        )
        assert got == list(range(1, len(files) + 1))

    def test_export_batch_cancel_under_500ms(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """批次间取消响应 <500ms：正在执行的批完成后立即终止，不再开新批。"""
        src = tmp_path / "src"
        src.mkdir()
        files = []
        for i in range(40):
            f = src / f"f{i:02}.txt"
            f.write_bytes(bytes(10))
            files.append({"path": str(f), "display_name": f.name})
        out = tmp_path / "out"
        out.mkdir()

        first_started = threading.Event()
        release = threading.Event()
        stop = threading.Event()

        class GatedBridge:
            available = True
            _supports_copy = True
            _supports_sizesum = True

            def __init__(self) -> None:
                self.calls: List[List[str]] = []

            def copy_files(self, sources: list, dest_dir: str):
                self.calls.append(list(sources))
                if len(self.calls) == 1:
                    first_started.set()
                    release.wait(10)
                return {
                    "copied": [
                        {"src": s, "dst": os.path.join(dest_dir, os.path.basename(s)),
                         "size": 1}
                        for s in sources
                    ],
                    "failed": [],
                }

        gated = GatedBridge()
        _patch_fpl_bridge(monkeypatch, gated)
        layout = FilePoolLayout()
        result_box: Dict[str, Any] = {}

        def _run() -> None:
            try:
                result_box["result"] = layout.copy_files(
                    files, str(out), should_stop=lambda: stop.is_set()
                )
            except Exception as ex:  # noqa: BLE001  # 记录线程异常
                result_box["error"] = repr(ex)

        t = threading.Thread(target=_run)
        start = time.perf_counter()
        t.start()
        assert first_started.wait(10), "第一批 native 调用必须启动"
        # 批次间取消：第一批仍在执行时置位 → 批完成后下个边界立即返回。
        stop.set()
        release.set()
        t.join(10)
        elapsed = time.perf_counter() - start
        assert not t.is_alive(), "取消后复制线程应在批次边界立即返回"
        assert elapsed < 0.5, f"批次间取消响应应 <500ms，实际 {elapsed * 1000:.0f}ms"
        assert len(gated.calls) == 1, "取消后不得开启第二批"
        s, f, e = result_box["result"]
        assert s == 32, "第一批 32 个文件应已复制成功"
        assert f == 0
        assert e == []

    def test_export_single_large_file_is_atomic(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """说明性记录：单文件/单目录复制为原子操作，批量取消不适用于其中。"""
        # 单文件复制不进批次（批内 ≤32 也不覆盖本文件——无后续批边界可停）。
        # 该语义由 design 承诺，不做时序断言：仅验证单文件经 native 正常落地。
        bridge = _FakeBridge(available=True)
        _patch_fpl_bridge(monkeypatch, bridge)
        src = tmp_path / "big.bin"
        src.write_bytes(bytes(64 * 1024))
        out = tmp_path / "out"
        out.mkdir()
        layout = FilePoolLayout()
        s, f, e = layout.copy_files(
            [{"path": str(src), "display_name": "big.bin"}], str(out)
        )
        assert s == 1 and f == 0 and e == []
        assert (out / "big.bin").read_bytes() == bytes(64 * 1024)

    def test_export_dll_missing_falls_back_to_python(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """DLL 缺失（mock 探测 False）→ 回退 Python 复制路径，不调 native。"""
        bridge = _FakeBridge(available=False)
        _patch_fpl_bridge(monkeypatch, bridge)
        items = _export_items(tmp_path)
        out_new = tmp_path / "out_new"
        out_new.mkdir()
        out_legacy = tmp_path / "out_legacy"
        out_legacy.mkdir()
        layout = FilePoolLayout()
        s_new, f_new, _ = layout.copy_files(items, str(out_new))
        s_leg, f_leg, _ = _legacy_export_flat(items, str(out_legacy))
        assert s_new == s_leg and f_new == f_leg
        assert _snapshot_tree(str(out_new)) == _snapshot_tree(str(out_legacy))
        assert bridge.calls == [], "DLL 缺失时不得调用 native"

    def test_export_runnable_cancel_event(self, qapp: QApplication,
                                          tmp_path: Path) -> None:
        """``_ExportCopyRunnable`` 取消标记经 ``cancel_event`` 接线。"""
        import freeassetfilter.ui.layout.file_pool_layout as fpl_mod

        layout = FilePoolLayout()
        ev = threading.Event()
        runnable = fpl_mod._ExportCopyRunnable(
            layout, [], str(tmp_path), 0, cancel_event=ev
        )
        assert runnable._should_stop() is False
        ev.set()
        assert runnable._should_stop() is True
        layout.deleteLater()


# =============================================================================
# ui.layout.file_selector_layout
# =============================================================================
class TestFileSelectorLayout:
    """文件选择器布局：构造契约与尺寸生效。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = FileSelectorLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    @staticmethod
    def _make_target_file(tmp_path) -> Path:
        """在临时目录创建一个定位目标文件，返回其路径。"""
        target = tmp_path / "locate_target.txt"
        target.write_text("locate me", encoding="utf-8")
        return target

    def test_locate_file_navigates_and_highlights(
        self, qapp: QApplication, tmp_path: object, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """文件池预览文件不在当前目录：locate_file 异步导航并延迟高亮卡片。"""
        import os

        import freeassetfilter.ui.layout.file_selector_layout as fsl_mod

        messages: list = []
        monkeypatch.setattr(
            fsl_mod.FileSelectorLayout, "_show_message_dialog",
            lambda self, t, m: messages.append((t, m)),
        )

        target = self._make_target_file(tmp_path)
        layout = FileSelectorLayout()
        _assert_layout_geometry(layout, qapp)
        assert messages == []

        layout.locate_file({"path": str(target), "name": target.name})

        target_dir = os.path.abspath(os.path.normpath(str(tmp_path)))
        # 异步导航：等待后台收集完成后由主线程槽应用（旧实现为同步落地）
        assert wait_until(
            qapp,
            lambda: os.path.normcase(layout._current_path)
            == os.path.normcase(target_dir),
        ), "locate_file 应异步导航到目标目录"
        # 挂起定位：条目落地后高亮目标文件卡片
        assert wait_until(
            qapp,
            lambda: os.path.normcase(layout._previewing_file_path or "")
            == os.path.normcase(str(target)),
        ), "locate_file 应在条目落地后高亮目标文件"
        # 等待延后滚动的 singleShot 触达后安全清理
        time.sleep(0.25)
        qapp.processEvents()
        layout.deleteLater()

    def test_locate_file_same_directory_skips_navigation(
        self, qapp: QApplication, tmp_path: object, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """目标文件已在当前目录：locate_file 不重复导航，仅高亮滚动。"""
        import os

        import freeassetfilter.ui.layout.file_selector_layout as fsl_mod

        messages: list = []
        monkeypatch.setattr(
            fsl_mod.FileSelectorLayout, "_show_message_dialog",
            lambda self, t, m: messages.append((t, m)),
        )

        target = self._make_target_file(tmp_path)
        layout = FileSelectorLayout()
        _assert_layout_geometry(layout, qapp)

        layout._load_directory(os.path.abspath(str(tmp_path)))
        assert messages == []

        navigate_calls: list = []
        original_navigate = layout._navigate_to

        def _spy_navigate(path: str) -> None:
            navigate_calls.append(path)
            original_navigate(path)

        monkeypatch.setattr(layout, "_navigate_to", _spy_navigate)

        layout.locate_file({"path": str(target), "name": target.name})

        assert navigate_calls == []  # 目录未变，不触发导航
        assert layout._previewing_file_path is not None
        assert (
            os.path.normcase(layout._previewing_file_path)
            == os.path.normcase(str(target))
        )

        import time

        time.sleep(0.25)
        qapp.processEvents()
        layout.deleteLater()

    def test_locate_file_missing_directory_shows_message(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """目标目录不存在：弹提示且不导航、不高亮。"""
        import os

        import freeassetfilter.ui.layout.file_selector_layout as fsl_mod

        messages: list = []
        monkeypatch.setattr(
            fsl_mod.FileSelectorLayout, "_show_message_dialog",
            lambda self, t, m: messages.append((t, m)),
        )

        layout = FileSelectorLayout()
        _assert_layout_geometry(layout, qapp)

        ghost = "D:/definitely/not/exists_dir/ghost.txt"
        navigate_calls: list = []
        monkeypatch.setattr(layout, "_navigate_to", lambda path: navigate_calls.append(path))

        layout.locate_file({"path": ghost, "name": "ghost.txt"})

        assert len(messages) == 1
        assert messages[0][0] == "错误"
        assert navigate_calls == []
        assert not layout._previewing_file_path
        assert os.path.normcase(layout._current_path) == os.path.normcase("All")
        layout.deleteLater()


# =============================================================================
# ui.layout.file_selector_layout — 异步加载测试替身
# =============================================================================
class _FakeThreadPool:
    """替身线程池：记录投递的 runnable，不真实执行（避免测试真实 IO/线程）。"""

    def __init__(self) -> None:
        """初始化投递记录列表。"""
        self.started: list = []

    def start(self, runnable: object) -> None:
        """记录被投递的 runnable。

        Args:
            runnable: 生产代码构造的 ``_DirectoryCollectRunnable``。
        """
        self.started.append(runnable)


def _patch_async_pool(monkeypatch: pytest.MonkeyPatch) -> _FakeThreadPool:
    """把 file_selector_layout 模块命名空间的 QThreadPool 替换为记录替身。

    Args:
        monkeypatch: pytest monkeypatch fixture。

    Returns:
        _FakeThreadPool: 记录投递任务的替身（测试内手动触发完成信号）。
    """
    import freeassetfilter.ui.layout.file_selector_layout as fsl_mod

    fake = _FakeThreadPool()
    monkeypatch.setattr(
        fsl_mod, "QThreadPool", SimpleNamespace(globalInstance=lambda: fake)
    )
    return fake


def _complete_pending_load(
    layout: FileSelectorLayout,
    path: str,
    entries: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """模拟后台收集完成：以当前世代 token 触发主线程应用槽。

    Args:
        layout: FileSelectorLayout 实例。
        path: 完成加载的路径。
        entries: 条目列表；None 表示加载失败（失败分支），空目录请传 ``[]``。
    """
    layout._on_dir_entries_ready(path, entries, layout._async_load_token)


# =============================================================================
# ui.layout.file_selector_layout — _go_back 返回过渡动画
# =============================================================================
class TestGoBackTransition:
    """_go_back 返回过渡：历史/上级/盘符根分支均一致触发 direction=-1 动画。

    全部用例均用 MagicMock 计数 begin/finish、替身线程池记录异步投递，不跑
    真实动画与后台 IO（offscreen 下 ``FileSelectorLayout`` 真实构造，过渡与
    加载入口被替身替换）；条目落地经 ``_complete_pending_load`` 手动触发。
    """

    def test_history_branch_triggers_back_animation(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """历史分支：有可回退历史时 _go_back 以 -1 触发过渡并加载上一条。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            tmp_path: pytest 临时目录（真实创建 tmpA/tmpB）。
            monkeypatch: 用例级猴子补丁。
        """
        import os

        tmp_a = tmp_path / "tmpA"
        tmp_b = tmp_path / "tmpB"
        tmp_a.mkdir()
        tmp_b.mkdir()
        str_a = os.path.abspath(str(tmp_a))
        str_b = os.path.abspath(str(tmp_b))

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            # 预置历史栈顶为 tmpB，回退应落到 tmpA。
            layout._nav_history = [str_a, str_b]
            layout._history_index = 1
            layout._current_path = str_b
            fake_pool = _patch_async_pool(monkeypatch)
            begin_mock: MagicMock = MagicMock(return_value=True)
            finish_mock: MagicMock = MagicMock(return_value=True)
            monkeypatch.setattr(layout._file_list, "begin_path_transition", begin_mock)
            monkeypatch.setattr(layout._file_list, "finish_path_transition", finish_mock)
            monkeypatch.setattr(layout, "_navigate_to_all", MagicMock())
            monkeypatch.setattr(layout, "_save_last_path", MagicMock())
            monkeypatch.setattr(os.path, "isdir", lambda path: True)

            layout._go_back()

            begin_mock.assert_called_once_with(-1)
            assert len(fake_pool.started) == 1
            assert fake_pool.started[0]._path == str_a
            # 异步：加载完成前不应提前播放过渡
            finish_mock.assert_not_called()

            _complete_pending_load(layout, str_a, [])

            finish_mock.assert_called_once_with(-1)
            assert os.path.normcase(layout._current_path) == os.path.normcase(str_a)
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_parent_fallback_triggers_back_animation(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """上级回退（单条历史/首次访问）：parent 回退分支以 -1 触发过渡。

        覆盖启动恢复、All 重置后等单历史场景：_history_index==0 时
        _go_back 走 parent 回退分支（经 _load_directory_with_transition），
        与历史分支一致触发 -1 动画并加载 dirname 上级。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            tmp_path: pytest 临时目录（真实创建 sub/inner）。
            monkeypatch: 用例级猴子补丁。
        """
        import os

        sub_dir = tmp_path / "sub"
        deep_dir = sub_dir / "inner"
        deep_dir.mkdir(parents=True)
        str_parent = os.path.abspath(str(sub_dir))
        str_deep = os.path.abspath(str(deep_dir))

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            # 单条历史（首次访问/启动恢复场景）：栈顶即 deep，无可回退历史，
            # 回退走 parent 分支，dirname 上级即 parent。
            layout._nav_history = [str_deep]
            layout._history_index = 0
            layout._current_path = str_deep
            fake_pool = _patch_async_pool(monkeypatch)
            begin_mock: MagicMock = MagicMock(return_value=True)
            finish_mock: MagicMock = MagicMock(return_value=True)
            monkeypatch.setattr(layout._file_list, "begin_path_transition", begin_mock)
            monkeypatch.setattr(layout._file_list, "finish_path_transition", finish_mock)
            monkeypatch.setattr(layout, "_navigate_to_all", MagicMock())
            monkeypatch.setattr(layout, "_save_last_path", MagicMock())
            monkeypatch.setattr(os.path, "isdir", lambda path: True)

            layout._go_back()

            begin_mock.assert_called_once_with(-1)
            assert len(fake_pool.started) == 1
            assert fake_pool.started[0]._path == str_parent
            finish_mock.assert_not_called()

            _complete_pending_load(layout, str_parent, [])

            finish_mock.assert_called_once_with(-1)
            assert os.path.normcase(layout._current_path) == os.path.normcase(str_parent)
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_drive_root_delegates_to_all_with_animation(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """盘符根回退：parent == current 时委托 _navigate_to_all 且带 -1 动画。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            monkeypatch: 用例级猴子补丁。
        """
        import os

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            # 无可回退历史、当前为盘符根：dirname 恒返自身以强制走 All 分支。
            layout._nav_history = []
            layout._history_index = -1
            layout._current_path = "D:\\"
            fake_pool = _patch_async_pool(monkeypatch)
            begin_mock: MagicMock = MagicMock(return_value=True)
            finish_mock: MagicMock = MagicMock(return_value=True)
            monkeypatch.setattr(layout._file_list, "begin_path_transition", begin_mock)
            monkeypatch.setattr(layout._file_list, "finish_path_transition", finish_mock)
            monkeypatch.setattr(layout, "_save_last_path", MagicMock())
            monkeypatch.setattr(layout, "_clear_last_path", MagicMock())
            monkeypatch.setattr(os.path, "isdir", lambda path: True)
            monkeypatch.setattr(os.path, "dirname", lambda path: path)
            navigate_all_calls: list = []
            original_navigate_to_all = layout._navigate_to_all

            def _spy_navigate_to_all() -> None:
                """记录委托并执行真实 All 导航（保留其内部 -1 动画）。"""
                navigate_all_calls.append(True)
                original_navigate_to_all()

            monkeypatch.setattr(layout, "_navigate_to_all", _spy_navigate_to_all)

            layout._go_back()

            assert navigate_all_calls == [True]
            begin_mock.assert_called_once_with(-1)
            assert len(fake_pool.started) == 1
            assert fake_pool.started[0]._path == "All"
            finish_mock.assert_not_called()
            assert layout._current_path == "All"

            _complete_pending_load(layout, "All", [])

            finish_mock.assert_called_once_with(-1)
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_deep_nesting_sequential_go_back(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """深层嵌套：逐级 _go_back 每次均触发 -1 动画。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            tmp_path: pytest 临时目录（真实创建 a/b/c）。
            monkeypatch: 用例级猴子补丁。
        """
        import os

        dir_a = tmp_path / "a"
        dir_b = dir_a / "b"
        dir_c = dir_b / "c"
        dir_c.mkdir(parents=True)
        str_a = os.path.abspath(str(dir_a))
        str_b = os.path.abspath(str(dir_b))
        str_c = os.path.abspath(str(dir_c))

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            layout._nav_history = [str_a, str_b, str_c]
            layout._history_index = 2
            layout._current_path = str_c
            fake_pool = _patch_async_pool(monkeypatch)
            begin_mock: MagicMock = MagicMock(return_value=True)
            finish_mock: MagicMock = MagicMock(return_value=True)
            monkeypatch.setattr(layout._file_list, "begin_path_transition", begin_mock)
            monkeypatch.setattr(layout._file_list, "finish_path_transition", finish_mock)
            monkeypatch.setattr(layout, "_navigate_to_all", MagicMock())
            monkeypatch.setattr(layout, "_save_last_path", MagicMock())
            monkeypatch.setattr(os.path, "isdir", lambda path: True)

            layout._go_back()
            layout._go_back()

            assert begin_mock.call_count == 2
            assert [c.args[0] for c in begin_mock.call_args_list] == [-1, -1]
            # 两次回退各投递一次异步加载（b 后被 a 取代）
            assert [r._path for r in fake_pool.started] == [str_b, str_a]
            stale_token = fake_pool.started[0]._token
            latest_token = fake_pool.started[1]._token

            # 过期结果（第一次加载）到达：token 不匹配 → 丢弃且不播过渡
            layout._on_dir_entries_ready(str_b, [], stale_token)
            finish_mock.assert_not_called()
            assert os.path.normcase(layout._current_path) == os.path.normcase(str_c)

            # 最新结果到达：应用并播放一次过渡
            layout._on_dir_entries_ready(str_a, [], latest_token)
            assert finish_mock.call_count == 1
            assert finish_mock.call_args.args[0] == -1
            assert os.path.normcase(layout._current_path) == os.path.normcase(str_a)
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    @pytest.mark.parametrize("scenario", ["history", "parent"])
    def test_direction_always_minus_one(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        scenario: str,
    ) -> None:
        """direction 一致性：历史/上级两种前置下 begin 首参恒为 -1。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            tmp_path: pytest 临时目录。
            monkeypatch: 用例级猴子补丁。
            scenario: 前置场景（history=普通历史回退，parent=回到上级）。
        """
        import os

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            if scenario == "history":
                # 普通历史回退：tmpB -> tmpA。
                tmp_a = tmp_path / "hA"
                tmp_b = tmp_path / "hB"
                tmp_a.mkdir(exist_ok=True)
                tmp_b.mkdir(exist_ok=True)
                layout._nav_history = [os.path.abspath(str(tmp_a)), os.path.abspath(str(tmp_b))]
                layout._history_index = 1
                layout._current_path = os.path.abspath(str(tmp_b))
            else:
                # 上级回退（单条历史/首次访问）：inner 经 parent 分支回到 sub。
                sub_dir = tmp_path / "psub"
                deep_dir = sub_dir / "pinner"
                deep_dir.mkdir(parents=True, exist_ok=True)
                layout._nav_history = [os.path.abspath(str(deep_dir))]
                layout._history_index = 0
                layout._current_path = os.path.abspath(str(deep_dir))
            fake_pool = _patch_async_pool(monkeypatch)
            begin_mock: MagicMock = MagicMock(return_value=True)
            finish_mock: MagicMock = MagicMock(return_value=True)
            monkeypatch.setattr(layout._file_list, "begin_path_transition", begin_mock)
            monkeypatch.setattr(layout._file_list, "finish_path_transition", finish_mock)
            monkeypatch.setattr(layout, "_navigate_to_all", MagicMock())
            monkeypatch.setattr(layout, "_save_last_path", MagicMock())
            monkeypatch.setattr(os.path, "isdir", lambda path: True)

            layout._go_back()

            assert begin_mock.call_count == 1
            assert begin_mock.call_args.args[0] == -1
            assert len(fake_pool.started) == 1

            _complete_pending_load(layout, fake_pool.started[0]._path, [])

            assert finish_mock.call_count == 1
            assert finish_mock.call_args.args[0] == -1
        finally:
            safe_teardown(layout)
            qapp.processEvents()


# =============================================================================
# ui.layout.file_selector_layout — 异步加载：遮罩生命周期 / 失败回滚 / 取消
# =============================================================================
class TestAsyncLoadLifecycle:
    """目录加载遮罩：延迟显示、完成隐藏（替身线程池，不跑真实后台 IO）。"""

    def test_overlay_delayed_show_then_hidden_on_complete(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """请求后遮罩未显示；计时器到点显示「加载中…」；完成后隐藏并恢复计数。"""
        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            _patch_async_pool(monkeypatch)

            layout._load_directory_async("All")

            assert layout._loading_show_timer.isActive(), "应启动延迟显示计时器"
            assert not layout._loading_overlay.isVisibleTo(layout), "延迟期内不应显示遮罩"
            assert layout._path_input.text() == "All", "路径框应即时更新"

            layout._on_loading_indicator_timeout()

            assert layout._loading_overlay.isVisibleTo(layout), "计时器到点应显示遮罩"
            assert layout._file_count_label.text() == "加载中…"

            _complete_pending_load(layout, "All", [])

            assert not layout._loading_show_timer.isActive()
            assert not layout._loading_overlay.isVisibleTo(layout), "完成后遮罩应隐藏"
            assert layout._file_count_label.text() == "0 个条目"
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_overlay_stays_hidden_when_completed_before_delay(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """快目录：延迟期内完成 → 遮罩从未显示、计时器取消。"""
        src_dir = tmp_path / "fast"
        src_dir.mkdir()
        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            _patch_async_pool(monkeypatch)

            layout._load_directory_async(os.path.abspath(str(src_dir)))
            assert layout._loading_show_timer.isActive()

            _complete_pending_load(layout, os.path.abspath(str(src_dir)), [])

            assert not layout._loading_show_timer.isActive(), "完成时应取消延迟计时器"
            assert not layout._loading_overlay.isVisibleTo(layout)
        finally:
            safe_teardown(layout)
            qapp.processEvents()


class TestAsyncLoadFailure:
    """异步加载失败：交互导航保留当前视图并回滚；启动加载回退 All。"""

    def test_interactive_failure_keeps_view_and_rolls_back(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """交互导航失败：保留当前目录与模型，历史/路径框回滚到原目录。"""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        str_a = os.path.abspath(str(dir_a))
        str_b = os.path.abspath(str(dir_b))

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            _patch_async_pool(monkeypatch)
            monkeypatch.setattr(layout, "_save_last_path", MagicMock())
            monkeypatch.setattr(layout, "_clear_last_path", MagicMock())

            # 模拟 _navigate_to 已压栈后的状态：当前 a，栈顶 b（加载中）
            layout._nav_history = [str_a, str_b]
            layout._history_index = 1
            layout._current_path = str_a
            layout._load_directory_async(str_b, 0, rollback_history=True)

            _complete_pending_load(layout, str_b, entries=None)

            assert os.path.normcase(layout._current_path) == os.path.normcase(str_a)
            assert layout._nav_history == [str_a], "失败导航应从历史栈回滚"
            assert layout._history_index == 0
            assert os.path.normcase(layout._path_input.text()) == os.path.normcase(str_a)
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_initial_failure_falls_back_to_all_view(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """启动首次加载失败：回退到 All 视图（重新投递 All 加载请求）。"""
        dir_a = tmp_path / "a"
        dir_a.mkdir()
        str_a = os.path.abspath(str(dir_a))

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            fake_pool = _patch_async_pool(monkeypatch)
            monkeypatch.setattr(layout, "_save_last_path", MagicMock())
            monkeypatch.setattr(layout, "_clear_last_path", MagicMock())

            layout._load_directory_async(str_a, 0, initial=True, rollback_history=True)
            assert [r._path for r in fake_pool.started] == [str_a]

            _complete_pending_load(layout, str_a, entries=None)

            assert layout._current_path == "All"
            assert [r._path for r in fake_pool.started] == [str_a, "All"]
        finally:
            safe_teardown(layout)
            qapp.processEvents()


class TestCollectCancelCheck:
    """``_collect_directory_entries_python`` 的取消检查（过期任务尽早退出）。"""

    def test_cancel_check_stops_scan_and_returns_none(
        self, qapp: QApplication, tmp_path: Path,
    ) -> None:
        """取消检查返回 True 时立即放弃并返回 None（过期结果由 token 丢弃）。"""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "one.txt").write_text("1", encoding="utf-8")
        (src_dir / "two.txt").write_text("2", encoding="utf-8")
        (src_dir / "three.txt").write_text("3", encoding="utf-8")

        checks: list = []

        def _cancel_check() -> bool:
            """首次调用即取消（模拟请求已被更新世代取代）。"""
            checks.append(True)
            return True

        result = FileSelectorLayout._collect_directory_entries_python(
            os.path.abspath(str(src_dir)), _cancel_check
        )

        assert result is None
        assert len(checks) == 1, "取消后不应继续扫描剩余条目"

        entries = FileSelectorLayout._collect_directory_entries_python(
            os.path.abspath(str(src_dir)), lambda: False
        )
        assert entries is not None
        assert sorted(e["name"] for e in entries) == [
            "one.txt", "three.txt", "two.txt",
        ]


# =============================================================================
# ui.layout.file_selector_layout — 空白区右键返回上一级
# =============================================================================
class TestRightClickEmptyAreaGoBack:
    """空白区右键路由：开关 + 无需滚动 + 空卡片位 → _go_back；其余不触发。

    取点基于真实网格几何（离屏布局的 gridSize/卡片尺寸动态计算），
    不 mock ``indexAt``；卡片上入池分支保持原样。
    """

    @staticmethod
    def _load_dir(tmp_path: Path, count: int) -> str:
        """创建含 ``count`` 个文件的目标目录并返回绝对路径。"""
        target_dir = tmp_path / "src"
        target_dir.mkdir(exist_ok=True)
        for i in range(count):
            (target_dir / f"f{i:02d}.txt").write_text("x", encoding="utf-8")
        return os.path.abspath(str(target_dir))

    @classmethod
    def _prepare(
        cls,
        qapp: QApplication,
        tmp_path: Path,
        count: int = 3,
        enabled: bool = True,
    ) -> FileSelectorLayout:
        """构造并加载含 ``count`` 个文件的选择器（可选开启空白右键开关）。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            tmp_path: pytest 临时目录（真实创建 src/）。
            count: 目标目录内文件数。
            enabled: 是否开启「空白区右键返回上一级」开关。

        Returns:
            FileSelectorLayout: 已加载目标目录、完成网格布局的实例。
        """
        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        layout._load_directory(cls._load_dir(tmp_path, count))
        layout.set_blank_right_click_go_back(enabled)
        qapp.processEvents()
        qapp.processEvents()
        return layout

    @staticmethod
    def _empty_slot_points(layout: FileSelectorLayout) -> Dict[str, QPoint]:
        """按真实网格几何计算空位/间距带取点（卡片模式）。

        Returns:
            dict: ``empty``=首个空行空位的卡片脚印内点；``left_pad``=脚印
            左侧间距带；``hgap``=脚印右侧间距带；``vgap``=有卡片行与空行
            之间的行间间距带。
        """
        grid = layout._file_list.gridSize()
        card = layout._grid_card_size
        cols = layout._grid_cols
        rows = (layout._file_model.rowCount() + cols - 1) // cols
        offset_x = max(0, (grid.width() - min(grid.width(), card.width()) + 1) // 2)
        top = rows * grid.height()
        return {
            "empty": QPoint(offset_x + 2, top + 2),
            "left_pad": QPoint(offset_x - 1, top + 2),
            "hgap": QPoint(offset_x + min(grid.width(), card.width()), top + 2),
            "vgap": QPoint(offset_x + 2, top - 1),
        }

    def test_blank_slot_zone_requires_switch(
        self, qapp: QApplication, tmp_path: Path,
    ) -> None:
        """开关关闭（默认）：空位脚印内也不触发返回。"""
        layout = self._prepare(qapp, tmp_path, enabled=False)
        try:
            points = self._empty_slot_points(layout)
            assert layout._blank_right_click_go_back is False
            assert layout._is_blank_slot_go_back_zone(points["empty"]) is False
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_blank_slot_zone_accepts_empty_slot_only(
        self, qapp: QApplication, tmp_path: Path,
    ) -> None:
        """开启后：空位脚印触发；左右间距带、行间间距带、占用格不触发。"""
        layout = self._prepare(qapp, tmp_path, enabled=True)
        try:
            points = self._empty_slot_points(layout)
            zone = layout._is_blank_slot_go_back_zone
            assert zone(points["empty"]) is True
            assert zone(points["left_pad"]) is False
            assert zone(points["hgap"]) is False
            assert zone(points["vgap"]) is False
            # 占用格（第一行第一张卡片中心）不触发
            grid = layout._file_list.gridSize()
            card = layout._grid_card_size
            assert zone(QPoint(grid.width() // 2, card.height() // 2)) is False
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_blank_slot_zone_rejects_when_scrolling_needed(
        self, qapp: QApplication, tmp_path: Path,
    ) -> None:
        """需要滚动时：即使落在空位脚印也不触发（最后一排尾部空位同样）。"""
        layout = self._prepare(qapp, tmp_path, count=59, enabled=True)
        try:
            lst = layout._file_list
            # Qt 不会为「从未显示」的 QListView 主动重算 contentsSize；
            # 旧实现的应用级统一下发恰好提供了那次样式重刷。此处显式触发
            # 一次样式重刷，保证前置条件（需要滚动）与下发模式无关。
            lst.setStyleSheet(lst.styleSheet())
            qapp.processEvents()
            vbar = lst.verticalScrollBar()
            assert vbar.maximum() > 0, "59 个条目应超出视口（需要滚动）"
            # Batched 惰性布局：滚动到底后多轮稳定可视矩形
            for _ in range(3):
                vbar.setValue(vbar.maximum())
                qapp.processEvents()

            grid = layout._file_list.gridSize()
            last_index = layout._file_model.index(
                layout._file_model.rowCount() - 1, 0
            )
            last_rect = layout._file_list.visualRect(last_index)
            assert last_rect.width() > 0, "滚动到底后最后一项应完成布局"

            # 最后一项所在行右侧的尾部空位（同一可视行内）
            point = QPoint(last_rect.x() + grid.width() + 2, last_rect.y() + 2)
            vp = layout._file_list.viewport()
            assert 0 <= point.x() < vp.width()
            assert 0 <= point.y() < vp.height()
            assert not layout._file_list.indexAt(point).isValid()
            assert layout._is_blank_slot_go_back_zone(point) is False
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_blank_slot_zone_list_mode(
        self, qapp: QApplication, tmp_path: Path,
    ) -> None:
        """列表模式：空行脚印触发；行间缝隙与卡片行不触发。"""
        layout = self._prepare(qapp, tmp_path, enabled=True)
        try:
            layout._toggle_view_mode()
            qapp.processEvents()
            grid = layout._file_list.gridSize()
            rows = layout._file_model.rowCount()  # 列表模式恒为单列
            empty_top = rows * grid.height()
            zone = layout._is_blank_slot_go_back_zone
            assert zone(QPoint(2, empty_top + 2)) is True
            assert zone(QPoint(2, empty_top - 1)) is False
            assert zone(QPoint(2, 10)) is False
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_empty_area_right_click_goes_back_when_enabled(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """开关开启 + 空卡片位右键：调用 _go_back，不发入池信号。"""
        layout = self._prepare(qapp, tmp_path, enabled=True)
        try:
            point = self._empty_slot_points(layout)["empty"]
            assert not layout._file_list.indexAt(point).isValid()

            go_back_mock: MagicMock = MagicMock()
            toggle_calls: list = []
            monkeypatch.setattr(layout, "_go_back", go_back_mock)
            layout.toggle_pool_requested.connect(lambda info: toggle_calls.append(info))

            layout._on_right_click_toggle_pool(point)

            go_back_mock.assert_called_once_with()
            assert toggle_calls == []
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_right_click_gap_does_not_go_back(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """卡片间/行间缝隙（含与空位相邻的间距带）：右键不返回，仅清除框选。"""
        layout = self._prepare(qapp, tmp_path, enabled=True)
        try:
            points = self._empty_slot_points(layout)
            go_back_mock: MagicMock = MagicMock()
            monkeypatch.setattr(layout, "_go_back", go_back_mock)

            for key in ("left_pad", "hgap", "vgap"):
                point = points[key]
                assert not layout._file_list.indexAt(point).isValid()
                layout._file_model.set_rows_selected({0}, True)
                layout._on_right_click_toggle_pool(point)
                assert layout._file_model.get_selected_rows() == set()

            go_back_mock.assert_not_called()
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_right_click_blank_disabled_does_not_go_back(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """开关默认关闭：空白位右键不返回，仅清除框选。"""
        layout = self._prepare(qapp, tmp_path, enabled=False)
        try:
            point = self._empty_slot_points(layout)["empty"]
            go_back_mock: MagicMock = MagicMock()
            monkeypatch.setattr(layout, "_go_back", go_back_mock)

            layout._file_model.set_rows_selected({0}, True)
            layout._on_right_click_toggle_pool(point)

            go_back_mock.assert_not_called()
            assert layout._file_model.get_selected_rows() == set()
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_card_right_click_keeps_toggle_pool(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """卡片上右键：发射 toggle_pool_requested，且不触发 _go_back。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            tmp_path: pytest 临时目录（真实创建 src/card.txt）。
            monkeypatch: 用例级猴子补丁。
        """
        target_dir = tmp_path / "src"
        target_dir.mkdir()
        target = target_dir / "card.txt"
        target.write_text("card", encoding="utf-8")

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            layout._load_directory(os.path.abspath(str(target_dir)))
            index = layout._file_model.index(0, 0)
            assert index.isValid()

            go_back_mock: MagicMock = MagicMock()
            toggle_calls: list = []
            monkeypatch.setattr(layout, "_go_back", go_back_mock)
            monkeypatch.setattr(
                layout._file_list, "indexAt", MagicMock(return_value=index)
            )
            layout.toggle_pool_requested.connect(lambda info: toggle_calls.append(info))

            layout._on_right_click_toggle_pool(QPoint(20, 20))

            assert len(toggle_calls) == 1
            assert toggle_calls[0]["name"] == "card.txt"
            assert (
                os.path.normcase(toggle_calls[0]["path"])
                == os.path.normcase(str(target))
            )
            assert toggle_calls[0]["is_dir"] is False
            go_back_mock.assert_not_called()
        finally:
            safe_teardown(layout)
            qapp.processEvents()


# =============================================================================
# ui.layout.settings_layout
# =============================================================================
class TestSettingsLayout:
    """设置页布局：构造契约与尺寸生效（读取真实 settings_v2.json）。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = SettingsLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_appearance_page_uses_floating_styled_scrollbar(
        self, qapp: QApplication,
    ) -> None:
        """外观页包在浮动滚动区中：styled 浮动滚动条接管，原生滚动条隐藏。"""
        from PySide6.QtWidgets import QScrollArea

        from components.styled_scroll_area import StyledScrollBar
        from freeassetfilter.ui.layout.settings_layout import _FloatingScrollArea

        layout = SettingsLayout()
        scrolls = layout._stack.findChildren(QScrollArea)
        floating = [s for s in scrolls if isinstance(s, _FloatingScrollArea)]
        # 通用页 + 外观页 + 关于页各有一处浮动滚动区（三页统一）
        assert len(floating) == 3

        # 列表顺序：0 = 通用，1 = 外观，2 = 关于 → 外观卡在索引 1
        area = layout._stack.widget(1).findChild(_FloatingScrollArea)
        assert area is not None
        # 原生滚动条隐藏，浮动 styled 滚动条存在
        assert area.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert area.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert isinstance(area._floating_bar, StyledScrollBar)
        # 浮动条锚定挂在外观卡片（#SettingsCard）下，贴其右缘（而非滚动区自身）
        assert area._region is area.parent()
        assert area._floating_bar.parent() is area.parent()
        # 平滑滚动在 showEvent 中初始化（未显示前未施加）
        assert area._scroller_ready is False
        safe_teardown(layout)

    def test_floating_scrollbar_range_and_value_sync(
        self, qapp: QApplication,
    ) -> None:
        """浮动滚动条与内部滚动条范围/值双向同步，随内容显隐。"""
        from freeassetfilter.ui.layout.settings_layout import _FloatingScrollArea

        area = _FloatingScrollArea()
        area.resize(400, 300)

        inner = QWidget()
        inner.setFixedHeight(800)  # 内容超出 → 产生滚动范围
        area.setWidget(inner)
        qapp.processEvents()
        area.show()
        qapp.processEvents()

        vbar = area.verticalScrollBar()
        bar = area._floating_bar
        if vbar.maximum() > 0:
            assert bar.maximum() == vbar.maximum()
            assert bar.isVisible()

            # 内部值变化 → 浮动条跟随
            vbar.setValue(10)
            assert bar.value() == 10
            # 浮动条拖动 → 内部跟随
            bar.setValue(20)
            assert vbar.value() == 20
            # 浮动条贴右侧边缘几何
            assert bar.x() == area.width() - bar.width()
        area.hide()
        safe_teardown(area)

    def test_page_scroll_fills_card_and_survives_content_growth(
        self, qapp: QApplication,
    ) -> None:
        """回归：页面滚动区铺满卡片；内容增长后新增行可达（不被裁断）。

        历史缺陷：``_create_page_card`` 曾以 ``addWidget + addStretch`` 排布，
        ``QScrollArea`` 高度被其缓存的 ``sizeHint`` 钉在页面初始内容高度
        （约卡片一半）；切换「窗口背景」使内容变高后，新增行被从中间裁断，
        且缩放窗口也不恢复。修复后滚动区始终铺满卡片内容区（上下各 20px
        布局边距除外），溢出内容全部经滚动范围可达。
        """
        from freeassetfilter.ui.layout.settings_layout import _FloatingScrollArea

        def _expected_fill_height(card: QWidget) -> int:
            """卡片内滚动区的满高：卡片内容高 - 上下各 20px 布局边距。"""
            return card.contentsRect().height() - 40

        layout = SettingsLayout()
        layout.resize(640, 400)
        layout.show()
        _pump_events(qapp)
        try:
            # 通用页（列表索引 0，默认当前页）：滚动区铺满卡片内容区
            general_card = layout._stack.widget(0)
            general_area = general_card.findChild(_FloatingScrollArea)
            assert general_area is not None
            assert general_area.height() == _expected_fill_height(general_card)

            # 外观页（列表索引 1）：切页后同样铺满
            layout._stack.setCurrentIndex(1)
            _pump_events(qapp)
            appearance_card = layout._stack.widget(1)
            appearance_area = appearance_card.findChild(_FloatingScrollArea)
            assert appearance_area is not None
            assert appearance_area.height() == _expected_fill_height(appearance_card)

            # 在外观页增长内容（图像模式：文件行 + 模糊度/透明度滑动条）
            layout._appearance_page._stage_background_settings("image")
            _pump_events(qapp)

            # 滚动区仍铺满（不因陈旧 sizeHint 缩回，高度不随内容变化）
            assert appearance_area.height() == _expected_fill_height(appearance_card)

            # 溢出内容全部经滚动范围可达（而不是被裁断后不可见）
            page = appearance_area.widget()
            viewport = appearance_area.viewport()
            assert page.minimumSizeHint().height() > viewport.height()
            assert appearance_area.verticalScrollBar().maximum() == (
                page.height() - viewport.height()
            )
        finally:
            safe_teardown(layout)


# =============================================================================
# ui.layout.unified_previewer_layout
# =============================================================================
class TestUnifiedPreviewerLayout:
    """统一预览器布局：构造、set_file(None)/clear_preview 分发。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_info_panel_externalized(self, qapp: QApplication) -> None:
        """文件信息面板已外置：本组件不再持有信息面板与内部分割条。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert not hasattr(layout, "_info_panel")
        assert not hasattr(layout, "_splitter")
        assert layout._content_top is not None
        assert layout._bottom_bar is not None
        layout.deleteLater()

    def test_set_file_none_is_safe(self, qapp: QApplication) -> None:
        """set_file(None) 走安全清空路径，不抛异常。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(None)
        qapp.processEvents()
        assert layout._content_layout is not None
        layout.clear_preview()
        layout.deleteLater()

    @staticmethod
    def _unsupported_file_info() -> dict:
        """无对应预览器的文件信息（不触发真实预览加载，仅驱动底栏状态）。"""
        return {"path": "D:/dummy/unsupported_sample.zzz", "suffix": "zzz", "is_dir": False}

    def test_unknown_file_uses_unsupported_previewer(
        self, qapp: QApplication, tmp_path: Path,
    ) -> None:
        """未知扩展名显示专用视图及文件基本信息。"""
        sample = tmp_path / "sample.zzz"
        sample.write_bytes(b"hello")
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file({"path": str(sample), "suffix": "zzz", "is_dir": False})
        qapp.processEvents()
        assert isinstance(layout._current_preview_widget, UnsupportedPreviewerLayout)
        widget = layout._current_preview_widget
        assert widget._name_label.text() == "sample.zzz"
        assert "5 B" in widget._size_label.text()
        assert "ZZZ" in widget._format_label.text()
        assert widget._open_default_btn.isEnabled()
        assert widget._open_explorer_btn.isEnabled()
        layout.deleteLater()

    def test_bottom_buttons_disabled_then_enabled(
        self, qapp: QApplication,
    ) -> None:
        """无预览文件时底栏按钮禁用；set_file 后启用；clear_preview 后再禁用。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)

        assert layout._share_btn.isEnabled() is False
        assert layout._open_default_btn.isEnabled() is False
        assert layout._locate_btn.isEnabled() is False
        assert layout._close_btn.isEnabled() is False

        layout.set_file(self._unsupported_file_info())
        qapp.processEvents()
        assert layout._share_btn.isEnabled() is True
        assert layout._open_default_btn.isEnabled() is True
        assert layout._locate_btn.isEnabled() is True
        assert layout._close_btn.isEnabled() is True

        layout.clear_preview()
        qapp.processEvents()
        assert layout._share_btn.isEnabled() is False
        assert layout._open_default_btn.isEnabled() is False
        assert layout._locate_btn.isEnabled() is False
        assert layout._close_btn.isEnabled() is False
        layout.deleteLater()

    def test_locate_button_emits_requested(self, qapp: QApplication) -> None:
        """点击"定位到所在目录"发射 locate_requested(当前文件信息)。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(self._unsupported_file_info())

        received: list = []
        layout.locate_requested.connect(lambda info: received.append(info))
        layout._locate_btn.click()

        assert len(received) == 1
        assert received[0]["path"] == "D:/dummy/unsupported_sample.zzz"
        layout.deleteLater()

    def test_close_button_emits_clear_requested(self, qapp: QApplication) -> None:
        """点击 close 按钮发射 clear_requested（清除预览请求）。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(self._unsupported_file_info())

        received: list = []
        layout.clear_requested.connect(lambda: received.append(True))
        layout._close_btn.click()

        assert received == [True]
        layout.deleteLater()

    @pytest.mark.parametrize(
        "file_info, expected",
        [
            ({"path": "x.mp3", "suffix": "mp3"}, True),   # 无点号音频
            ({"path": "x.wav", "suffix": ".wav"}, True),  # 带点号音频
            ({"path": "x.MP3", "suffix": "MP3"}, True),   # 大写后缀
            ({"suffix": ""}, False),                       # 空后缀
            ({"path": "x.txt", "suffix": "txt"}, False),   # 非音频（无点）
            ({"path": "x.log", "suffix": ".txt"}, False),  # 非音频（带点）
        ],
    )
    def test_is_audio_file_normalizes_suffix(
        self, qapp: QApplication, file_info: dict, expected: bool
    ) -> None:
        """_is_audio_file 对 suffix 归一化（无点/带点/大小写）后再判音频。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert layout._is_audio_file(file_info) is expected
        layout.deleteLater()

    # ── 底栏按钮：顺序与两文字按钮等宽 ────────────────────────────────

    def _show_layout(self, qapp: QApplication) -> UnifiedPreviewerLayout:
        """显示一个预览器布局（底栏几何类用例的公共前置）。"""
        layout = UnifiedPreviewerLayout()
        layout.show()
        layout.resize(720, 920)
        _pump_events(qapp)
        return layout

    def test_bottom_bar_button_order(
        self, qapp: QApplication,
    ) -> None:
        """底栏顺序：share → 打开方式 → 定位目录 → close。"""
        layout = self._show_layout(qapp)
        share_x = layout._share_btn.x()
        open_x = layout._open_default_btn.x()
        locate_x = layout._locate_btn.x()
        close_x = layout._close_btn.x()
        assert share_x < open_x < locate_x < close_x
        assert not hasattr(layout, "_explorer_btn")
        safe_teardown(layout)

    def test_action_buttons_equal_width_and_track_width(
        self, qapp: QApplication,
    ) -> None:
        """两个文字按钮等宽，随功能区宽度同步同增同减。"""
        layout = self._show_layout(qapp)

        def _widths() -> list[int]:
            return [layout._open_default_btn.width(), layout._locate_btn.width()]

        def _assert_equal(ws: list[int]) -> None:
            assert max(ws) - min(ws) <= 1  # 等分取整误差不超过 1px

        wide = _widths()
        _assert_equal(wide)
        assert wide[0] > 0

        layout.resize(980, 920)  # 变宽 → 同步变大
        _pump_events(qapp)
        wider = _widths()
        _assert_equal(wider)
        assert wider[0] > wide[0]

        layout.resize(600, 920)  # 变窄 → 同步变小
        _pump_events(qapp)
        narrow = _widths()
        _assert_equal(narrow)
        assert narrow[0] < wider[0]
        safe_teardown(layout)

    # ── 统一操作按钮：顶栏模式（New 布局） ────────────────────────────

    def test_actions_mode_top_uses_previewer_toolbar(
        self, qapp: QApplication,
    ) -> None:
        """New 布局：底栏隐藏，图标按钮注入预览器顶栏（unified_action_host）。"""
        from layout.preview.preview_toolbar import PreviewToolbarFrame

        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_actions_mode(True)
        assert layout._bottom_bar.isHidden() is True

        class _FakePreviewer(QWidget):
            """带统一工具栏宿主的替身预览器。"""

            def __init__(self, parent=None) -> None:
                super().__init__(parent)
                self._top_bar = PreviewToolbarFrame(self)

            def unified_action_host(self):
                return self._top_bar

            def cleanup(self) -> None:
                """替身无资源可清。"""

        layout._current_file_info = {
            "path": "D:/dummy/unsupported_sample.zzz",
            "suffix": "zzz",
            "is_dir": False,
        }
        layout._update_bottom_buttons()

        previewer = _FakePreviewer(layout._content_top)
        layout._ensure_content_layout()
        layout._content_layout.addWidget(previewer)
        layout._current_preview_widget = previewer
        layout._current_preview_type = _FakePreviewer
        layout._sync_action_host()

        assert layout._top_host is previewer._top_bar
        for btn in layout._top_buttons:
            assert previewer._top_bar.isAncestorOf(btn)
            assert btn.isEnabled() is True

        # 销毁预览器不应带走按钮（先摘除、后销毁）
        layout._cleanup_current_preview()
        for btn in layout._top_buttons:
            assert btn.parent() is None
        assert layout._top_host is None
        safe_teardown(layout)

    def test_actions_mode_top_fallback_own_toolbar(
        self, qapp: QApplication,
    ) -> None:
        """无顶栏预览器（视频/音频/Office 形态）：由容器提供统一工具栏。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_actions_mode(True)

        class _NoBarPreviewer(QWidget):
            """无顶栏宿主的替身预览器。"""

            def cleanup(self) -> None:
                """替身无资源可清。"""

        previewer = _NoBarPreviewer(layout._content_top)
        layout._ensure_content_layout()
        layout._content_layout.addWidget(previewer)
        layout._current_preview_widget = previewer
        layout._current_preview_type = _NoBarPreviewer
        layout._sync_action_host()

        own = layout._own_toolbar
        assert own is not None
        assert own.isVisibleTo(layout) is True
        assert layout._top_host is own
        for btn in layout._top_buttons:
            assert own.isAncestorOf(btn)
        safe_teardown(layout)

    def test_actions_mode_back_to_classic_restores_bottom_bar(
        self, qapp: QApplication,
    ) -> None:
        """切回经典：底栏恢复显示，顶栏按钮摘离宿主。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_actions_mode(True)
        layout.set_actions_mode(False)

        assert layout._bottom_bar.isHidden() is False
        assert layout._top_host is None
        for btn in layout._top_buttons:
            assert btn.parent() is None
        safe_teardown(layout)


# =============================================================================
# ui.layout.preview.font_previewer_layout
# =============================================================================
class TestFontPreviewerLayout:
    """字体预览布局：构造契约与 set_file 缺失路径降级。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_file_missing_safe(self, qapp: QApplication) -> None:
        """set_file(缺失路径) 不抛异常，停留 overlay 视图。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(_MISSING_FILE)
        qapp.processEvents()
        assert layout._content_stack.currentIndex() == 1
        layout.deleteLater()


class TestFontPreviewTextDrawer:
    """预览文本编辑抽屉：标题结构 / 展开收起 / 实时同步 / 重置 / 清理收起。"""

    def _shown_layout(self, qapp: QApplication) -> FontPreviewerLayout:
        layout = FontPreviewerLayout()
        layout.show()
        layout.resize(1200, 700)
        _pump_events(qapp)
        return layout

    @staticmethod
    def _settle_drawers(
        qapp: QApplication,
        layout: FontPreviewerLayout,
        ms: float = 1500,
    ) -> None:
        """有界等待：直到左右抽屉的展开/收起动画全部结束。"""
        deadline = time.time() + ms / 1000
        while time.time() < deadline:
            animating = [
                getattr(layout, attr)._animating
                for attr in ("_text_drawer", "_ai_drawer")
                if getattr(layout, attr) is not None
            ]
            if not any(animating):
                return
            qapp.processEvents()
            time.sleep(0.01)

    def test_drawer_default_hidden_with_title(self, qapp: QApplication) -> None:
        """初始隐藏；抽屉含标题「编辑预览文本」，编辑框不再自带重复 label。"""
        from PySide6.QtWidgets import QLabel

        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert not layout._text_drawer.is_open
        assert layout._edit_preview_btn.toolTip() == "编辑预览文本"
        titles = [
            c
            for c in layout._text_drawer.panel.findChildren(QLabel)
            if c.text() == "编辑预览文本"
        ]
        assert titles
        assert layout._preview_text_edit.label == ""
        layout.deleteLater()

    def test_toggle_drawer(self, qapp: QApplication) -> None:
        """编辑按钮第一次点击展开、第二次点击收起抽屉。"""
        layout = self._shown_layout(qapp)
        layout._on_edit_preview_text()
        self._settle_drawers(qapp, layout)
        assert layout._text_drawer.is_open
        assert layout._text_drawer.isVisible()
        layout._on_edit_preview_text()
        assert not layout._text_drawer.is_open
        layout.deleteLater()

    def test_edit_text_syncs_to_preview(self, qapp: QApplication) -> None:
        """预览视图激活时：编辑框输入实时同步 _preview_text 与预览区。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout._content_stack.setCurrentIndex(0)
        layout._preview_text_edit.text = "自定义预览内容 ABC"
        qapp.processEvents()
        assert layout._preview_text == "自定义预览内容 ABC"
        assert layout._preview_view._text_edit.toPlainText() == "自定义预览内容 ABC"
        layout.deleteLater()

    def test_reset_preview_text(self, qapp: QApplication) -> None:
        """重置按钮恢复默认预览文本并同步到预览区。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout._preview_text_edit.text = "临时内容"
        layout._on_reset_preview_text()
        assert layout._preview_text == DEFAULT_PREVIEW_TEXT
        assert layout._preview_text_edit.text == DEFAULT_PREVIEW_TEXT
        layout.deleteLater()

    def test_cleanup_closes_drawers(self, qapp: QApplication) -> None:
        """cleanup() 收起已展开的编辑与 AI 抽屉，不抛异常。

        AI 入口默认关闭：先经 set_ai_entry_enabled(True) 显式启用（与设置
        开关生效后的路径一致），再验证 cleanup 收起。
        """
        layout = self._shown_layout(qapp)
        layout.set_ai_entry_enabled(True)
        layout._on_edit_preview_text()
        layout._toggle_ai_drawer()
        self._settle_drawers(qapp, layout)
        assert layout._text_drawer.is_open
        assert layout._ai_drawer.is_open
        layout.cleanup()
        assert not layout._text_drawer.is_open
        assert not layout._ai_drawer.is_open
        layout.deleteLater()


class TestFontWeightLabel:
    """字重标签：数值→标准名映射与静态/可变/未加载三种状态显示。"""

    @pytest.mark.parametrize(
        "weight,expected",
        [
            (100, "Thin"),
            (200, "ExtraLight"),
            (300, "Light"),
            (400, "Regular"),
            (500, "Medium"),
            (600, "SemiBold"),
            (700, "Bold"),
            (800, "ExtraBold"),
            (900, "Black"),
            (1000, "Black"),
            (95, "Thin"),      # 最近档偏差 ≤100
            (105, "Thin"),
            (550, "Medium"),
            (0, "Thin"),       # 越界钳制到下限 100
            (2500, "Black"),   # 越界钳制到上限 1000
        ],
    )
    def test_weight_name_mapping(
        self, weight: int, expected: str,
    ) -> None:
        assert FontPreviewerLayout.weight_name(weight) == expected

    def test_placeholder_when_not_loaded(self, qapp: QApplication) -> None:
        """未加载字体：标签 Weight + 按钮 wght（占位禁用）。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert layout._weight_label.text() == "Weight"
        assert layout._weight_value_btn.text() == "wght"
        assert not layout._weight_value_btn.isEnabled()
        layout.deleteLater()

    def test_static_font_shows_weight_name(self, qapp: QApplication) -> None:
        """静态字体加载后：标签显示真实字重名，按钮显示数值。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.current_font_family = "SomeStatic"
        layout._is_variable_font = False
        layout._current_weight = 700
        layout._sync_weight_controls()
        assert layout._weight_label.text() == "Bold"
        assert layout._weight_value_btn.text() == "700"
        assert layout._weight_value_btn.isEnabled()
        layout.current_font_family = ""
        layout._is_variable_font = False
        layout._sync_weight_controls()
        assert layout._weight_label.text() == "Weight"
        layout.deleteLater()

    def test_variable_font_keeps_weight_label(self, qapp: QApplication) -> None:
        """可变字体：标签保持 Weight，按钮显示数值。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.current_font_family = "SomeVariable"
        layout._is_variable_font = True
        layout._current_weight = 400
        layout._sync_weight_controls()
        assert layout._weight_label.text() == "Weight"
        assert layout._weight_value_btn.text() == "400"
        assert layout._weight_value_btn.isEnabled()
        layout.deleteLater()


class TestFontWeightControlsLayout:
    """字重控件布局：统一间距 / tooltip 拆分 / 折叠菜单映射 / 弹窗居中。"""

    def _shown_layout(self, qapp: QApplication) -> FontPreviewerLayout:
        layout = FontPreviewerLayout()
        layout.show()
        layout.resize(1200, 700)
        _pump_events(qapp)
        return layout

    def test_uniform_gap_after_weight_button(
        self, qapp: QApplication,
    ) -> None:
        """字重数值按钮与 AI/缩放按钮间距为统一 6px（AI 入口显式开启）。"""
        from freeassetfilter.ui.layout.preview.preview_toolbar import (
            PreviewToolbarFrame,
        )

        layout = self._shown_layout(qapp)
        layout.set_ai_entry_enabled(True)
        _pump_events(qapp)
        gap = PreviewToolbarFrame._GAP
        weight_right = layout._weight_value_btn.x() + layout._weight_value_btn.width()
        assert layout._ai_btn.x() - weight_right == gap
        ai_right = layout._ai_btn.x() + layout._ai_btn.width()
        assert layout._zoom_btn.x() - ai_right == gap
        layout.deleteLater()

    def test_tooltips_split_and_group_clean(
        self, qapp: QApplication,
    ) -> None:
        """标签 tooltip Weight、按钮 wght；分组自身不再带 tooltip。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert layout._weight_label.toolTip() == "Weight"
        assert layout._weight_value_btn.toolTip() == "wght"
        assert layout._weight_group.toolTip() == ""
        layout.deleteLater()

    def test_overflow_menu_label_mapping(
        self, qapp: QApplication,
    ) -> None:
        """折叠「更多」菜单：字重组显示注册名「字重」，其余控件仍取 tooltip。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        top_bar = layout._top_bar
        assert top_bar._menu_label(layout._weight_group) == "字重"
        assert top_bar._menu_label(layout._ai_btn) == "AI 功能"
        layout.deleteLater()

    def test_weight_popup_centered_with_button(
        self, qapp: QApplication,
    ) -> None:
        """字重弹窗水平中心与数值按钮中心对齐。"""
        import freeassetfilter.ui.layout.preview.font_previewer_layout as fpl_module

        layout = self._shown_layout(qapp)
        anchor = layout._weight_anchor_global()
        button_center = (
            layout._weight_value_btn.mapToGlobal(
                layout._weight_value_btn.rect().center()
            ).x()
        )
        assert abs(anchor.x() - button_center) <= 1  # 锚点即按钮下缘中心
        popup = fpl_module._WeightPopup(parent=layout)
        rect = popup._target_rect(anchor)
        assert abs(rect.center().x() - anchor.x()) <= 1
        popup.close()
        popup.deleteLater()
        layout.deleteLater()


# =============================================================================
# ui.layout.preview.preview_toolbar（弹窗/溢出菜单锚点）
# =============================================================================
class TestPreviewToolbarPopupAnchoring:
    """顶栏弹窗锚点：功能按钮下缘中心对齐 + 折叠回退 + 溢出菜单居中。"""

    def _shown_toolbar(self, qapp: QApplication) -> Any:
        from freeassetfilter.ui.layout.preview.preview_toolbar import (
            PreviewToolbarFrame,
        )

        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        toolbar = PreviewToolbarFrame()
        toolbar.setFixedHeight(48)
        lay.addWidget(toolbar)
        host.resize(640, 120)
        host.show()
        _pump_events(qapp)
        return host, toolbar

    def test_anchor_is_widget_bottom_center(self, qapp: QApplication) -> None:
        """可见功能按钮的弹窗锚点 = 按钮下缘水平中心。"""
        from PySide6.QtWidgets import QPushButton

        host, toolbar = self._shown_toolbar(qapp)
        try:
            button = QPushButton("X", toolbar)
            button.setFixedSize(32, 32)
            button.show()
            _pump_events(qapp)
            anchor = toolbar.popup_anchor_global(button)
            center = button.mapToGlobal(
                QPoint(button.width() // 2, button.height())
            )
            assert abs(anchor.x() - center.x()) <= 1
            assert abs(anchor.y() - center.y()) <= 1
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)

    def test_anchor_falls_back_to_more_button_when_widget_hidden(
        self, qapp: QApplication,
    ) -> None:
        """功能按钮被折叠隐藏时，锚点回退到「更多」按钮下缘中心。"""
        from PySide6.QtWidgets import QPushButton

        host, toolbar = self._shown_toolbar(qapp)
        try:
            hidden = QPushButton("Z", toolbar)
            hidden.hide()
            toolbar._more_btn.show()
            _pump_events(qapp)
            assert toolbar._more_btn.isVisible()

            anchor = toolbar.popup_anchor_global(hidden)
            center = toolbar._more_btn.mapToGlobal(
                QPoint(toolbar._more_btn.width() // 2, toolbar._more_btn.height())
            )
            assert abs(anchor.x() - center.x()) <= 1
            assert abs(anchor.y() - center.y()) <= 1
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)

    def test_anchor_falls_back_to_toolbar_when_all_hidden(
        self, qapp: QApplication,
    ) -> None:
        """功能按钮与「更多」按钮都不可见时，锚点退回顶栏自身下缘中心。"""
        from PySide6.QtWidgets import QPushButton

        host, toolbar = self._shown_toolbar(qapp)
        try:
            hidden = QPushButton("Z", toolbar)
            hidden.hide()
            toolbar._more_btn.hide()
            _pump_events(qapp)

            anchor = toolbar.popup_anchor_global(hidden)
            self_center = toolbar.mapToGlobal(
                QPoint(toolbar.width() // 2, toolbar.height())
            )
            assert abs(anchor.x() - self_center.x()) <= 1
            assert abs(anchor.y() - self_center.y()) <= 1
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)

    def test_overflow_menu_pos_centered_below_more_button(
        self, qapp: QApplication,
    ) -> None:
        """溢出菜单以「⋯」按钮下缘中心水平展开（居中对齐功能按钮）。"""
        host, toolbar = self._shown_toolbar(qapp)
        try:
            toolbar._more_btn.show()
            _pump_events(qapp)
            menu_w = 220
            pos = toolbar._overflow_menu_pos(menu_w)
            center = toolbar._more_btn.mapToGlobal(
                QPoint(toolbar._more_btn.width() // 2, toolbar._more_btn.height())
            )
            assert abs(pos.x() - (center.x() - menu_w // 2)) <= 1
            assert pos.y() == center.y() + 4  # 按钮下缘 4px 间距
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)


# =============================================================================
# ui.layout.preview.fullscreen_host
# =============================================================================
class TestPreviewFullscreenHost:
    """全屏宿主席：attach/detach 进出、无父窗口进出全屏不抛。"""

    def test_attach_detach_roundtrip(self, qapp: QApplication) -> None:
        """attach 移入宿主，exit_fullscreen 还原到原父布局。"""
        container = QWidget()
        layout = QVBoxLayout(container)
        child = QWidget(container)
        layout.addWidget(child)

        host = PreviewFullscreenHost()
        assert host.attach(child) is True
        assert host.content is child
        assert layout.indexOf(child) == -1
        host.exit_fullscreen()
        assert host.content is None
        assert layout.indexOf(child) == 0
        host.deleteLater()
        container.deleteLater()

    def test_fullscreen_without_parent_does_not_raise(
        self, qapp: QApplication
    ) -> None:
        """无父窗口时 show_fullscreen / exit_fullscreen 不抛（QA 要求）。"""
        host = PreviewFullscreenHost()
        host.show_fullscreen()
        qapp.processEvents()
        host.exit_fullscreen()
        qapp.processEvents()
        host.deleteLater()

    def test_escape_emits_signal(self, qapp: QApplication) -> None:
        """Esc 按键发射 escapePressed 信号（先 connect 再触发）。"""
        host = PreviewFullscreenHost()
        received: list[bool] = []
        host.escapePressed.connect(lambda: received.append(True))
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        host.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        assert received == [True]
        host.deleteLater()


# =============================================================================
# ui.layout.preview.image_previewer_layout
# =============================================================================
class TestImagePreviewerLayout:
    """图像预览布局：构造契约与 set_file 缺失路径返回 False。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = ImagePreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_file_missing_returns_false(self, qapp: QApplication) -> None:
        """set_file(缺失路径) 返回 False，不抛异常。"""
        layout = ImagePreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert layout.set_file(_MISSING_FILE) is False
        layout.deleteLater()

    # ── 打开即适配（真实 viewport 尺寸）与透明背景回归 ─────────────────────

    @staticmethod
    def _make_jpg(tmp_path: Any, name: str, width: int, height: int) -> str:
        """生成指定尺寸的纯色 JPG 到 tmp_path，返回路径。"""
        from PySide6.QtGui import QImage

        img = QImage(width, height, QImage.Format.Format_RGB32)
        img.fill(QColor(120, 160, 200))
        path = str(tmp_path / name)
        assert img.save(path, "JPG", 90)
        return path

    @staticmethod
    def _expected_fit_scale(pv: Any) -> float:
        """按 QGraphicsView 当前真实 viewport 计算期望 fit 比例。

        fitInView 内置约 2px/边的防锯齿留白，此处用无留白上界做近似，
        断言时允许 1% 相对误差即可排除“按默认 640×480 占位尺寸适配”
        的旧缺陷（该场景比例相差远大于 1%）。
        """
        vp = pv._image_view.viewport()
        item = pv._gif_proxy_item if pv._is_gif_mode else pv._pixmap_item
        if pv._is_gif_mode:
            rect = item.boundingRect()
            iw, ih = rect.width(), rect.height()
        else:
            pix = item.pixmap()
            iw, ih = pix.width(), pix.height()
        if not iw or not ih:
            return 0.0
        return min(vp.width() / iw, vp.height() / ih)

    def _shown_previewer(
        self, qapp: QApplication, host_w: int = 1200, host_h: int = 900,
        backdrop: str | None = None,
    ) -> tuple[Any, QWidget]:
        """按真实运行时时序构造：创建 → 加入宿主布局 → set_file 前宿主已可见。"""
        host = QWidget()
        host.resize(host_w, host_h)
        root_lay = QVBoxLayout(host)
        root_lay.setContentsMargins(0, 0, 0, 0)
        outer = QWidget(host)
        if backdrop is not None:
            # NOTE (A1 QSS singleton): backdrop must NOT use a direct
            # setStyleSheet — a widget's own sheet outranks the app-level
            # sheet by Qt level precedence and would paint over the
            # previewer's subtree transparency. Palette fill is visually
            # identical and keeps the QSS cascade untouched.
            palette = outer.palette()
            palette.setColor(outer.backgroundRole(), QColor(backdrop))
            outer.setPalette(palette)
            outer.setAutoFillBackground(True)
        root_lay.addWidget(outer)
        lay = QVBoxLayout(outer)
        lay.setContentsMargins(0, 0, 0, 0)
        pv = ImagePreviewerLayout(parent=outer)
        lay.addWidget(pv)
        host.show()
        qapp.processEvents()
        return pv, host

    def test_open_fits_to_real_viewport_not_placeholder(
        self, qapp: QApplication, tmp_path: Any,
    ) -> None:
        """大图打开后按真实预览区尺寸适配，而非未布局前的默认占位尺寸。

        旧实现：_fit_to_view 在 QGraphicsView 仍处于 Qt 默认几何
        （未加入布局 / 布局未激活）时执行，此后真实尺寸生效也无人再校正，
        观感即“打开不自动缩放”。本用例构造与统一预览器一致的时序
        （先 set_file 后布局激活），断言最终缩放贴近真实 viewport 的 fit 值。
        """
        img = self._make_jpg(tmp_path, "wide.jpg", 3000, 2000)
        pv, host = self._shown_previewer(qapp)
        pv.set_file(img)
        _pump_events(qapp, ms=600)
        try:
            vp = pv._image_view.viewport()
            assert vp.width() > 800 and vp.height() > 500, "宿主布局应已生效"
            expected = self._expected_fit_scale(pv)
            assert expected > 0.1
            actual = pv._image_view.transform().m11()
            assert pv._zoom_pct == 100
            assert abs(actual - expected) / expected <= 0.01, (
                f"打开即适配应使用真实 viewport 尺寸: actual={actual:.4f} "
                f"expected={expected:.4f} vp={vp.width()}x{vp.height()}"
            )
        finally:
            pv.cleanup()
            host.close()
            host.deleteLater()
        _pump_events(qapp, ms=100)

    def test_switching_image_refits_at_unchanged_viewport(
        self, qapp: QApplication, tmp_path: Any,
    ) -> None:
        """viewport 未变化时切换不同尺寸图片也必须重新适配（去重不误伤）。"""
        img_a = self._make_jpg(tmp_path, "a_wide.jpg", 3000, 2000)
        img_b = self._make_jpg(tmp_path, "b_square.jpg", 900, 900)
        pv, host = self._shown_previewer(qapp)
        try:
            pv.set_file(img_a)
            _pump_events(qapp, ms=500)
            scale_a = pv._image_view.transform().m11()
            vp_a = (pv._image_view.viewport().width(), pv._image_view.viewport().height())

            pv.set_file(img_b)
            _pump_events(qapp, ms=500)
            assert pv._zoom_pct == 100
            vp_b = (pv._image_view.viewport().width(), pv._image_view.viewport().height())
            assert vp_a == vp_b, "本例应在 viewport 不变的条件下切换"
            expected_b = self._expected_fit_scale(pv)
            actual_b = pv._image_view.transform().m11()
            assert abs(actual_b - expected_b) / expected_b <= 0.01, (
                f"切换文件后需重新 fit: actual={actual_b:.4f} expected={expected_b:.4f}"
            )
            # 两张图片比例差异明显时，新比例不得残留旧图比例
            expected_a = min(vp_a[0] / 3000.0, vp_a[1] / 2000.0)
            assert abs(scale_a - expected_a) / expected_a <= 0.01
            assert abs(actual_b - scale_a) / scale_a > 0.3, "正方形图不应沿用横图比例"
        finally:
            pv.cleanup()
            host.close()
            host.deleteLater()
        _pump_events(qapp, ms=100)

    def test_preview_area_background_is_transparent(
        self, qapp: QApplication, tmp_path: Any,
    ) -> None:
        """预览区不再涂 tm.surface 深色底，透出下层面板背景（同文本预览器）。

        静态断言：view 样式不含不透明 surface 填色、场景无背景画刷、
        viewport 关闭 palette 自绘；
        行为断言：方形图在宽视口内留出左右 letterbox，其区域像素应透明
        （下层面板为纯红，若有深色底则采样为不透明非透明色）。
        """
        img = self._make_jpg(tmp_path, "square.jpg", 2000, 2000)
        pv, host = self._shown_previewer(qapp, backdrop="#ff0000")
        pv.set_file(img)
        _pump_events(qapp, ms=600)
        try:
            view_ss = pv._image_view.styleSheet().lower()
            assert "surface" not in view_ss and "background-color" not in view_ss
            assert pv._image_scene.backgroundBrush().style() == Qt.NoBrush
            assert pv._image_view.viewport().autoFillBackground() is False
            vp = pv._image_view.viewport()
            assert vp.width() > 800
            image_pix = pv._pixmap_item.pixmap()
            assert image_pix.width() == 2000
            shot = vp.grab().toImage()
            # 依据图像实际渲染矩形选取“必定落在留白区”的采样点：
            # 选左右/上下四条留白中最宽的一条在其中间采样；采样坐标按比例
            # 换算到 grab 位图，兼容高 DPI 屏幕（位图为物理像素）。
            tl = pv._image_view.mapFromScene(
                pv._pixmap_item.sceneBoundingRect().topLeft()
            )
            br = pv._image_view.mapFromScene(
                pv._pixmap_item.sceneBoundingRect().bottomRight()
            )
            gaps = {
                "left": tl.x(),
                "right": vp.width() - 1 - br.x(),
                "top": tl.y(),
                "bottom": vp.height() - 1 - br.y(),
            }
            side, gap = max(gaps.items(), key=lambda kv: kv[1])
            mid_x = vp.width() // 2
            mid_y = vp.height() // 2
            if side == "left":
                log_x, log_y = gap // 2, mid_y
            elif side == "right":
                log_x, log_y = vp.width() - 1 - gap // 2, mid_y
            elif side == "top":
                log_x, log_y = mid_x, gap // 2
            else:
                log_x, log_y = mid_x, vp.height() - 1 - gap // 2
            px = int(round(log_x * shot.width() / vp.width()))
            py = int(round(log_y * shot.height() / vp.height()))
            sample = shot.pixelColor(px, py)
            assert gap >= 4, f"图片应被自适应缩放并留出留白: {gaps}"
            assert sample.alpha() == 0, (
                f"预览区留白应透明（side={side}）: {sample} gaps={gaps}"
            )
        finally:
            pv.cleanup()
            host.close()
            host.deleteLater()
        _pump_events(qapp, ms=100)


# =============================================================================
# ui.layout.preview.office_previewer_layout
# =============================================================================
class _FakeOfficeWorker(QObject):
    """``OfficeConverterWorker`` 的可控替身：不启动真实 soffice 线程。"""

    converted = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        file_info: dict,
        timeout: float | None = None,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.file_info: dict = file_info
        self._running: bool = False

    def start(self, *args: Any, **kwargs: Any) -> None:
        """镜像 start：fake 只标记运行中。"""
        self._running = True

    def is_running(self) -> bool:
        """线程是否仍在运行。"""
        return self._running

    def isRunning(self) -> bool:  # noqa: N802
        """Qt 兼容接口。"""
        return self._running

    def request_cancel(self) -> None:
        """镜像 request_cancel。"""
        self._running = False

    def wait(self, timeout_ms: int = 3000) -> bool:
        """镜像 wait。"""
        return not self._running

    def cleanup(self, wait_ms: int = 3000) -> None:
        """镜像 cleanup。"""
        self._running = False


class TestOfficePreviewerLayout:
    """Office 预览布局：构造契约与 set_file 分发（注入 fake worker）。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造（无 worker） + resize 后 geometry 非空。"""
        layout = OfficePreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.cleanup()
        layout.deleteLater()

    def test_set_file_str_routes_to_worker(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """宿主 str 路径分发 → 归一化为 dict、启动 worker（fake）。"""
        monkeypatch.setattr(_opl, "OfficeConverterWorker", _FakeOfficeWorker)
        layout = OfficePreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file("C:/fake/path/sample.docx")
        assert layout._current_suffix == "docx"
        assert isinstance(layout._current_worker, _FakeOfficeWorker)
        layout.cleanup()
        layout.deleteLater()


# =============================================================================
# ui.layout.preview.pdf_previewer_layout
# =============================================================================
class TestPdfPreviewerLayout:
    """PDF 预览布局：构造契约、set_file 缺失路径与滚动/居中几何。"""

    @staticmethod
    def _write_pdf(tmp_path: Path, pages: int = 2) -> str:
        """用 PyMuPDF 在内存构造多页 PDF（612×792pt）。"""
        fitz = pytest.importorskip("fitz")
        doc = fitz.open()
        for i in range(pages):
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, 72), f"Page {i + 1}")
        target = tmp_path / "previewer_scroll.pdf"
        doc.save(str(target))
        doc.close()
        return str(target)

    @staticmethod
    def _shown_loaded_layout(
        qapp: QApplication, tmp_path: Path,
    ) -> tuple[QWidget, PdfPreviewerLayout]:
        """展示宿主并加载双页 PDF（完成 fit 与滚动条范围定时任务）。"""
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        layout = PdfPreviewerLayout()
        host_layout.addWidget(layout)
        host.resize(520, 420)
        host.show()
        _pump_events(qapp)
        assert layout.set_file(TestPdfPreviewerLayout._write_pdf(tmp_path)) is True
        _pump_events(qapp, 400)
        return host, layout

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = PdfPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_file_missing_returns_false(self, qapp: QApplication) -> None:
        """set_file(缺失路径) 返回 False，不抛异常。"""
        layout = PdfPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert layout.set_file(_MISSING_FILE) is False
        layout.deleteLater()

    def test_content_centered_including_reserved_scrollbar_column(
        self, qapp: QApplication, tmp_path: Path,
    ) -> None:
        """页面白色卡片相对预览器左右边缘等距（右侧预留滚动条列计入画布）。"""
        host, layout = self._shown_loaded_layout(qapp, tmp_path)
        try:
            renderer = layout._renderer
            view = renderer._view
            assert view is not None
            assert view.right_reserved_px == 12
            # 画布中心 = (渲染器宽 + 预留列宽) / 2
            assert abs(view.frame_center_x() - (renderer.width() + 12) / 2.0) <= 0.5

            zoom = view.zoom_level
            pwz = renderer._page_widths[0] * zoom
            box_left = (0.0 - view.offset_x) * zoom + view.frame_center_x()
            white_left = box_left + 6.0
            white_right = box_left + pwz - 6.0
            ml = white_left
            mr = (renderer.width() + 12) - white_right
            assert abs(ml - mr) <= 1.0
            assert ml > 0 and mr > 0
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)

    def test_vertical_scroll_range_reserves_bottom_gap(
        self, qapp: QApplication, tmp_path: Path,
    ) -> None:
        """有纵向溢出时滚动条最大值 = 内容高 - 视口高 + 底部预留空隙。"""
        host, layout = self._shown_loaded_layout(qapp, tmp_path)
        try:
            renderer = layout._renderer
            view = renderer._view
            total_h = view._accum_page_heights[-1] * view.zoom_level
            view_h = max(view.view_height, 1)
            overflow = int(total_h - view_h)
            if overflow > 0:
                assert layout._vbar.maximum() == (
                    overflow + layout._CONTENT_BOTTOM_GAP
                )
            else:
                assert layout._vbar.maximum() == 0
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)

    def test_horizontal_scrollbar_shows_only_on_overflow(
        self, qapp: QApplication, tmp_path: Path,
    ) -> None:
        """fit 态无横向溢出 → 底行滚动条隐藏；放大后出现，回到 fit 再隐藏。"""
        host, layout = self._shown_loaded_layout(qapp, tmp_path)
        try:
            renderer = layout._renderer
            view = renderer._view
            assert not layout._hbar.isVisible()
            assert layout._hbar.maximum() == 0
            assert not layout._corner.isVisible()

            base = view.get_zoom_for_scale(100)
            renderer.set_zoom(base * 1.6)
            _pump_events(qapp, 60)
            assert layout._hbar.isVisible()
            assert layout._hbar.maximum() > 0
            assert layout._corner.isVisible()

            renderer.fit_to_page()
            _pump_events(qapp, 60)
            assert not layout._hbar.isVisible()
            assert layout._hbar.maximum() == 0
            assert not layout._corner.isVisible()
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)


# =============================================================================
# ui.layout.preview.text_previewer_layout
# =============================================================================
class TestTextPreviewerLayout:
    """文本预览布局：构造契约、set_text_content 与缺失路径降级。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_text_content(self, qapp: QApplication) -> None:
        """直接注入文本内容不抛异常。"""
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_text_content("hello from test")
        qapp.processEvents()
        layout.deleteLater()

    def test_set_file_missing_safe(self, qapp: QApplication) -> None:
        """set_file(缺失路径) 不抛异常。"""
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(_MISSING_FILE)
        qapp.processEvents()
        layout.deleteLater()

    def test_slider_debounce_single_render(
        self, qapp: QApplication, monkeypatch: Any
    ) -> None:
        """连续拖动字号滑条 10 次 → 防抖只触发一次渲染且字号为最终值。"""
        monkeypatch.setattr(_tpl, "_MarkdownRenderer", _CountingMarkdownRenderer)
        _CountingMarkdownRenderer.call_count = 0
        _CountingMarkdownRenderer.last_font_size = None
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        try:
            layout.set_text_content("# hello\nworld", "note.md")
            # 等初始异步渲染完成（事件泵直到内容回写）
            assert _pump_until(
                qapp,
                lambda: _CountingMarkdownRenderer.call_count >= 1
                and layout._markdown_view._text_browser.toPlainText().strip()
                == "rendered-14:13",
            )
            _CountingMarkdownRenderer.call_count = 0

            # 连续拖动 10 次（期间不泵事件，防抖窗口内不触发渲染）
            for size in range(20, 30):
                layout._apply_font_size_from_zoom(size)
            assert _CountingMarkdownRenderer.call_count == 0
            assert layout._font_size == 29  # 防抖期间保留最新字号

            # 泵超过 120ms 防抖窗口 → 只触发一次渲染，内容为最终字号
            _pump_events(qapp, 500)
            assert _CountingMarkdownRenderer.call_count == 1
            assert _CountingMarkdownRenderer.last_font_size == 29
            assert (
                layout._markdown_view._text_browser.toPlainText().strip()
                == "rendered-29:13"
            )
        finally:
            safe_teardown(layout)

    def test_rapid_file_switch_drops_stale_render(
        self, qapp: QApplication, monkeypatch: Any
    ) -> None:
        """快速切换文件时 token 防陈旧：旧渲染结果被丢弃，最终显示新文件。"""
        monkeypatch.setattr(_tpl, "_MarkdownRenderer", _SlowMarkdownRenderer)
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        try:
            # 先加载慢渲染文件，随即切到快文件——旧任务结果到达时已过期
            layout.set_text_content("SLOW doc", "slow.md")
            layout.set_text_content("FAST doc", "fast.md")
            assert _pump_until(
                qapp,
                lambda: layout._markdown_view._text_browser.toPlainText().strip()
                == "out-FAST doc",
                timeout_ms=6000,
            )
            assert (
                layout._markdown_view._text_browser.toPlainText().strip()
                == "out-FAST doc"
            )
        finally:
            safe_teardown(layout)

    # ------------------------------------------------------------------
    # 编码探测 worker（todo 25：全文件 chardet 移出 UI 线程 + token 防陈旧）
    # ------------------------------------------------------------------
    _ENC_FIXTURE_DIR = (
        Path(__file__).resolve().parents[3]
        / "support"
        / "faf_core_fixtures"
        / "encoding_samples"
    )

    def test_set_file_gbk_worker_redraws_correctly(
        self, qapp: QApplication, tmp_path: Any
    ) -> None:
        """GBK 文件：快速链先显示防空白，探测 worker 完成后回调解码渲染为 GBK。"""
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        try:
            raw = (self._ENC_FIXTURE_DIR / "gbk_02.txt").read_bytes()
            path = tmp_path / "gbk.txt"
            path.write_bytes(raw)
            layout.set_file(str(path))
            # 立即（未泵事件）已有快速链显示，不空白
            fast_text = layout._source_view._text_edit.toPlainText()
            assert len(fast_text) > 0, "快速链显示不应空白"
            # 探测完成后回调重渲染为 gbk（异步，泵事件直到生效）
            expected = _normalize_eol(raw.decode("gbk", errors="replace"))
            assert _pump_until(
                qapp,
                lambda: layout._current_encoding == "gbk"
                and layout._source_view._text_edit.toPlainText() == expected,
                timeout_ms=6000,
            )
        finally:
            safe_teardown(layout)

    def test_set_file_utf8_no_needless_rerender(
        self, qapp: QApplication, tmp_path: Any
    ) -> None:
        """utf-8 文件：快速链已选 utf-8，探测结果一致 → 不重渲染、文本正确。"""
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        try:
            raw = (self._ENC_FIXTURE_DIR / "utf8_01.txt").read_bytes()
            path = tmp_path / "u.txt"
            path.write_bytes(raw)
            layout.set_file(str(path))
            expected = _normalize_eol(raw.decode("utf-8", errors="replace"))
            assert _pump_until(
                qapp,
                lambda: layout._current_encoding == "utf-8"
                and layout._source_view._text_edit.toPlainText() == expected,
                timeout_ms=6000,
            )
        finally:
            safe_teardown(layout)

    def test_rapid_file_switch_drops_stale_detection(
        self, qapp: QApplication, tmp_path: Any
    ) -> None:
        """快速切文件：旧探测任务结果被 token 丢弃，最终显示新文件正确编码。"""
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        try:
            gbk_raw = (self._ENC_FIXTURE_DIR / "gbk_02.txt").read_bytes()
            utf_raw = (self._ENC_FIXTURE_DIR / "utf8_01.txt").read_bytes()
            gbk_path = tmp_path / "a_gbk.txt"
            utf_path = tmp_path / "b_utf8.txt"
            gbk_path.write_bytes(gbk_raw)
            utf_path.write_bytes(utf_raw)
            layout.set_file(str(gbk_path))
            layout.set_file(str(utf_path))
            expected = _normalize_eol(utf_raw.decode("utf-8", errors="replace"))
            assert _pump_until(
                qapp,
                lambda: layout._current_encoding == "utf-8"
                and layout._source_view._text_edit.toPlainText() == expected,
                timeout_ms=6000,
            )
            # 陈旧探测不得把已渲染的 utf-8 覆盖回 gbk
            qapp.processEvents()
            assert layout._current_encoding == "utf-8"
            assert layout._source_view._text_edit.toPlainText() == expected
        finally:
            safe_teardown(layout)


# =============================================================================
# ui.layout.preview.video_player_layout
# =============================================================================
class TestVideoPlayerLayout:
    """视频播放布局：构造契约；不带 libmpv 时不真实播放（缺失路径返回 False）。"""

    def test_construct_and_geometry(
        self, qapp: QApplication, heartbeat_manager: Any
    ) -> None:
        """默认构造 + resize 后 geometry 非空（HeartbeatManager 已启动）。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            layout = VideoPlayerLayout()
            assert layout is not None
        finally:
            qapp.setProperty("faf_disable_animation", animation_enabled_original)
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_file_missing_returns_false(
        self, qapp: QApplication, heartbeat_manager: Any
    ) -> None:
        """无 libmpv 时 set_file(缺失路径) 返回 False，不做真实播放。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            layout = VideoPlayerLayout()
            assert layout.set_file(_MISSING_FILE) is False
        finally:
            qapp.setProperty("faf_disable_animation", animation_enabled_original)
        layout.deleteLater()

    def test_set_file_recovers_dead_core(
        self, qapp: QApplication, heartbeat_manager: Any, tmp_path: object
    ) -> None:
        """核心死亡时 set_file 自动重建（initialize）并重新嵌入窗口后正常加载。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            media = tmp_path / "sample.mp4"
            media.write_bytes(b"\x00" * 16)
            layout = VideoPlayerLayout()

            fake_manager: Any = MagicMock()
            fake_manager.is_core_operational.return_value = False  # 核心已死
            fake_manager.initialize.return_value = True
            fake_manager.set_window_id.return_value = True
            fake_manager.load_file.return_value = True
            fake_manager.play.return_value = True
            fake_manager.set_volume.return_value = True
            fake_manager.set_speed.return_value = True
            layout._mpv_manager = fake_manager  # noqa: SLF001

            assert layout.set_file(str(media), is_audio=False) is True
            fake_manager.initialize.assert_called_once()  # 自愈重建
            fake_manager.set_window_id.assert_called_once()  # 重新嵌入
            fake_manager.load_file.assert_called_once()
            assert layout._stack.currentIndex() == 0  # noqa: SLF001
        finally:
            qapp.setProperty("faf_disable_animation", animation_enabled_original)
        layout.deleteLater()

    def test_load_failure_shows_overlay(
        self, qapp: QApplication, heartbeat_manager: Any, tmp_path: object
    ) -> None:
        """load_file 失败时切回 overlay 显示错误（不再停留黑色视频表面）。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            media = tmp_path / "bad.mp4"
            media.write_bytes(b"\x00" * 16)
            layout = VideoPlayerLayout()

            fake_manager: Any = MagicMock()
            fake_manager.is_core_operational.return_value = True
            fake_manager.set_window_id.return_value = True
            fake_manager.load_file.return_value = False  # 加载失败
            layout._mpv_manager = fake_manager  # noqa: SLF001

            assert layout.set_file(str(media), is_audio=False) is False
            assert layout._stack.currentIndex() == 1  # noqa: SLF001
            assert "无法加载文件" in layout._placeholder.text()  # noqa: SLF001
        finally:
            qapp.setProperty("faf_disable_animation", animation_enabled_original)
        layout.deleteLater()

    def test_core_rebuild_failure_shows_overlay(
        self, qapp: QApplication, heartbeat_manager: Any, tmp_path: object
    ) -> None:
        """核心重建失败时切回 overlay 显示"无法初始化播放器"。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            media = tmp_path / "dead.mp4"
            media.write_bytes(b"\x00" * 16)
            layout = VideoPlayerLayout()

            fake_manager: Any = MagicMock()
            fake_manager.is_core_operational.return_value = False
            fake_manager.initialize.return_value = False  # 重建失败
            layout._mpv_manager = fake_manager  # noqa: SLF001

            assert layout.set_file(str(media), is_audio=False) is False
            assert layout._stack.currentIndex() == 1  # noqa: SLF001
            assert "无法初始化播放器" in layout._placeholder.text()  # noqa: SLF001
        finally:
            qapp.setProperty("faf_disable_animation", animation_enabled_original)
        layout.deleteLater()


# =============================================================================
# ui.layout.preview.video_player_layout — todo-30 音频元数据异步化 + 单次打开
# =============================================================================
class TestVideoPlayerLayoutAsyncAudio:
    """todo-30：音频选择后 UI 立即返回；mutagen 单次打开；调色板在 worker 线程；
    token 防陈旧（快速切音频时陈旧结果丢弃）。"""

    @staticmethod
    def _make_layout_with_fake_mpv(qapp: QApplication) -> VideoPlayerLayout:
        """构造布局并替换 MPV 管理器为假对象（不真实播放），关闭 OpenGL 初始化。"""
        layout = VideoPlayerLayout()
        fake_manager: Any = MagicMock()
        fake_manager.is_core_operational.return_value = True
        fake_manager.is_initialized.return_value = True
        fake_manager.get_duration.return_value = None
        fake_manager.get_position.return_value = None
        fake_manager.set_window_id.return_value = True
        fake_manager.load_file.return_value = True
        fake_manager.play.return_value = True
        fake_manager.set_volume.return_value = True
        fake_manager.set_speed.return_value = True
        layout._mpv_manager = fake_manager  # noqa: SLF001
        # offscreen 下避免真实 OpenGL / 流体层初始化失败
        layout._fluid_background.load = lambda: None  # type: ignore[method-assign]  # noqa: SLF001
        return layout

    @staticmethod
    def _wait_until(qapp: QApplication, cond: Any, timeout: float = 5.0) -> None:
        """有界事件泵：轮询直到条件满足或超时（让 worker 信号在 UI 线程被投递）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            qapp.processEvents()
            if cond():
                return
            time.sleep(0.02)
        qapp.processEvents()
        assert cond(), "等待异步音频元数据结果超时"

    def test_audio_select_single_open_and_worker_palette(
        self,
        qapp: QApplication,
        heartbeat_manager: Any,
        tmp_path: object,
        monkeypatch: Any,
    ) -> None:
        """happiness：音频选择 → UI 立即返回；``mutagen_file`` 单次打开（=1，而非 2）；
        调色板在 worker 线程执行（线程 id 与 UI 线程不同）。"""
        calls: List[str] = []
        palette_thread_ids: List[int] = []
        ui_thread_id = threading.get_ident()

        def _slow_mutagen(_path: str) -> "_FakeAudio":
            calls.append(str(_path))
            time.sleep(1.5)  # 模拟慢速 mutagen 解析；位于 worker 线程不阻塞 UI
            return _FakeAudio(
                tags={"APIC:": _FakeFrame(data=_MINI_PNG_BYTES)},
                info=_FakeAudioInfo(),
            )

        monkeypatch.setattr(
            "freeassetfilter.services.media_metadata_service.mutagen_file", _slow_mutagen
        )

        orig_palette = VideoPlayerLayout._extract_palette_from_cover

        def _recording_palette(cover_data: bytes) -> list:
            palette_thread_ids.append(threading.get_ident())
            return orig_palette(cover_data)

        monkeypatch.setattr(
            "freeassetfilter.ui.layout.preview.video_player_layout.VideoPlayerLayout"
            "._extract_palette_from_cover",
            staticmethod(_recording_palette),
        )

        media: Path = tmp_path / "single.mp3"
        media.write_bytes(b"x")
        layout: VideoPlayerLayout = self._make_layout_with_fake_mpv(qapp)
        try:
            start = time.time()
            assert layout.set_file(str(media), is_audio=True) is True
            elapsed = time.time() - start
            # 时间断言：mutagen 被 sleep(1.5) 延迟，但 UI 线程立即返回
            assert elapsed < 1.0

            self._wait_until(qapp, lambda: len(palette_thread_ids) > 0, timeout=5.0)

            assert len(calls) == 1  # 单文件选择的 mutagen_file 调用次数 = 1（改造前 2 次）
            assert palette_thread_ids, "调色板应在 worker 线程执行"
            assert palette_thread_ids[0] != ui_thread_id  # worker 线程 id != UI 线程
            # 等 done 回传与任务移除完成后再销毁，避免 orphaned queued 事件
            self._wait_until(
                qapp,
                lambda: len(layout._audio_meta_tasks) == 0,  # noqa: SLF001
                timeout=5.0,
            )
        finally:
            pass
        layout.cleanup()
        layout.deleteLater()

    def test_audio_select_returns_immediately(
        self,
        qapp: QApplication,
        heartbeat_manager: Any,
        tmp_path: object,
        monkeypatch: Any,
    ) -> None:
        """时间断言：mutagen 阻塞解析时 UI 线程立即返回（解析异步执行）。

        共享线程池的调度顺序不确定，"返回时 worker 尚未开始"不是可断言的
        事实（worker 可能在 set_file 返回前已启动）。改用闸门：mutagen 调
        用先登记再阻塞，闸门未放行前必然无法完成——若 set_file 同步等待解
        析，elapsed 会超过闸门超时而断言失败；放行后再等待任务完成收尾。
        """
        import threading

        calls: List[str] = []
        gate = threading.Event()

        def _gated_mutagen(_path: str) -> "_FakeAudio":
            calls.append(str(_path))
            gate.wait(timeout=5.0)
            return _FakeAudio(tags={}, info=_FakeAudioInfo())

        monkeypatch.setattr(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            _gated_mutagen,
        )

        media: Path = tmp_path / "slow.mp3"
        media.write_bytes(b"x")
        layout: VideoPlayerLayout = self._make_layout_with_fake_mpv(qapp)
        try:
            start = time.time()
            assert layout.set_file(str(media), is_audio=True) is True
            elapsed = time.time() - start
            assert elapsed < 1.0  # 不被阻塞中的 mutagen 拖住
            assert len(calls) <= 1  # 已启动最多一次解析（调度顺序不确定）
            gate.set()  # 放行解析
            # 等待 worker 完成再删布局，避免 queued 信号在 deleteLater
            # 之后抵达产生 teardown 噪音
            self._wait_until(qapp, lambda: len(calls) == 1, timeout=5.0)
            self._wait_until(
                qapp,
                lambda: len(layout._audio_meta_tasks) == 0,  # noqa: SLF001
                timeout=5.0,
            )
        finally:
            gate.set()
        layout.cleanup()
        layout.deleteLater()

    def test_rapid_audio_switch_drops_stale_metadata(
        self,
        qapp: QApplication,
        heartbeat_manager: Any,
        tmp_path: object,
        monkeypatch: Any,
    ) -> None:
        """token 防陈旧：首次任务 derlay 更久、后触发任务先完成——陈旧结果被丢弃。"""
        def _path_aware_mutagen(_path: str) -> "_FakeAudio":
            if str(_path).endswith("first.mp3"):
                time.sleep(1.5)  # 第一首解析慢，最后才完成 → token 已过期
                return _FakeAudio(tags={"TITLE": "第一首"}, info=_FakeAudioInfo())
            time.sleep(0.2)  # 第二首先完成 → token 最新，应被采纳
            return _FakeAudio(tags={"TITLE": "第二首"}, info=_FakeAudioInfo())

        monkeypatch.setattr(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            _path_aware_mutagen,
        )

        first: Path = tmp_path / "first.mp3"
        second: Path = tmp_path / "second.mp3"
        first.write_bytes(b"x")
        second.write_bytes(b"x")
        layout: VideoPlayerLayout = self._make_layout_with_fake_mpv(qapp)
        try:
            layout._update_audio_metadata(str(first))  # noqa: SLF001  # token=1
            layout._update_audio_metadata(str(second))  # noqa: SLF001  # token=2

            self._wait_until(
                qapp,
                lambda: layout._music_info_panel._raw_title == "第二首",  # noqa: SLF001
                timeout=5.0,
            )
            time.sleep(1.5)  # 允许陈旧的第一首结果也完成到达
            qapp.processEvents()
            # 陈旧结果被 token 守卫丢弃：最终标题仍是第二首
            assert layout._music_info_panel._raw_title == "第二首"  # noqa: SLF001
            self._wait_until(
                qapp,
                lambda: len(layout._audio_meta_tasks) == 0,  # noqa: SLF001
                timeout=5.0,
            )
        finally:
            pass
        layout.cleanup()
        layout.deleteLater()


# =============================================================================
# ui.layout.preview.font_previewer_layout — FontLoadThread
# =============================================================================
class TestFontLoadThread:
    """FontLoadThread：文件/请求 ID/中止设置与缺失路径降级。"""

    def test_construct_and_setters(self, qapp: QApplication) -> None:
        """构造后 set_file / set_request_id 生效，未启动线程。"""
        thread = FontLoadThread()
        assert isinstance(thread, QThread)
        thread.set_file(_MISSING_FILE)
        thread.set_request_id(7)
        assert thread.file_path == _MISSING_FILE
        assert thread._request_id == 7
        thread.set_request_id(0)
        thread.abort()  # abort 标记置位
        thread.deleteLater()

    def test_run_missing_path_emits_error(self, qapp: QApplication) -> None:
        """run() 同步执行：缺失路径发 error(request_id, 消息)。"""
        thread = FontLoadThread()
        thread.set_file(_MISSING_FILE)
        thread.set_request_id(42)
        received: list = []

        def _on_error(request_id: int, msg: str) -> None:
            received.append((request_id, msg))

        thread.error.connect(_on_error)
        thread.run()  # 同步执行 run 体，避免真实后台线程
        assert len(received) == 1
        assert received[0][0] == 42
        assert "不存在" in received[0][1]
        thread.deleteLater()


# =============================================================================
# ui.layout.settings_layout — AccentColorButton
# =============================================================================
class TestAccentColorButton:
    """AccentColorButton：构造、color_hex/selected/hover_progress 与点击。"""

    def test_construct(self, qapp: QApplication) -> None:
        """默认构造：color_hex 回退为传入值，未选中、hover 进度 0。"""
        btn = AccentColorButton("#007AFF", name="蓝")
        assert btn.color_hex == "#007AFF"
        assert btn.selected is False
        assert btn.hover_progress == 0.0
        safe_teardown(btn)

    def test_value_override(self, qapp: QApplication) -> None:
        """value 参数覆盖 color_hex 返回值（自动模式用）。"""
        btn = AccentColorButton("#007AFF", value="auto")
        assert btn.color_hex == "auto"
        safe_teardown(btn)

    def test_selected_roundtrip(self, qapp: QApplication) -> None:
        """selected 可写且可读回。"""
        btn = AccentColorButton("#007AFF")
        btn.selected = True
        assert btn.selected is True
        btn.selected = False
        assert btn.selected is False
        safe_teardown(btn)

    def test_click_emits_hex(self, qapp: QApplication) -> None:
        """左键按下发射 clicked(原始 hex)。"""
        btn = AccentColorButton("#007AFF")
        received: list = []

        def _on_clicked(color: str) -> None:
            received.append(color)

        btn.clicked.connect(_on_clicked)
        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(20, 20),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        btn.mousePressEvent(press)
        assert received == ["#007AFF"]
        safe_teardown(btn)

    def test_paint_event_safe(self, qapp: QApplication) -> None:
        """离屏渲染不抛异常。"""
        btn = AccentColorButton("#007AFF", center_text="A")
        btn.selected = True
        pm = QPixmap(40, 40)
        pm.fill(QColor("#000000"))
        btn.render(pm)
        safe_teardown(btn)


# =============================================================================
# ui.layout.settings_layout — CustomAccentButton
# =============================================================================
class TestCustomAccentButton:
    """CustomAccentButton：构造、selected 与点击。"""

    def test_construct(self, qapp: QApplication) -> None:
        """默认构造未选中；传参构造选中。"""
        btn = CustomAccentButton()
        assert btn.selected is False
        btn2 = CustomAccentButton(selected=True)
        assert btn2.selected is True
        safe_teardown(btn)
        safe_teardown(btn2)

    def test_selected_setter(self, qapp: QApplication) -> None:
        """selected 可写可读回。"""
        btn = CustomAccentButton()
        btn.selected = True
        assert btn.selected is True
        safe_teardown(btn)

    def test_click_emits(self, qapp: QApplication) -> None:
        """左键按下发射 clicked。"""
        btn = CustomAccentButton()
        received: list = []

        def _on_clicked() -> None:
            received.append(True)

        btn.clicked.connect(_on_clicked)
        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(20, 20),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        btn.mousePressEvent(press)
        assert received == [True]
        safe_teardown(btn)

    def test_paint_event_safe(self, qapp: QApplication) -> None:
        """离屏渲染不抛异常。"""
        btn = CustomAccentButton(selected=True)
        pm = QPixmap(40, 40)
        pm.fill(QColor("#000000"))
        btn.render(pm)
        safe_teardown(btn)


# =============================================================================
# ui.layout.settings_layout — AppearanceSettingsPage
# =============================================================================
class TestAppearanceSettingsPage:
    """AppearanceSettingsPage：构造、设置收集、主题刷新与关闭路径。"""

    def test_construct_and_collect_settings(self, qapp: QApplication) -> None:
        """构造后 collect_settings 返回 V2 外观结构。"""
        page = AppearanceSettingsPage()
        settings = page.collect_settings()
        assert "appearance" in settings
        assert "theme" in settings["appearance"]
        assert "accent_color" in settings["appearance"]
        safe_teardown(page)

    def test_refresh_theme(self, qapp: QApplication) -> None:
        """refresh_theme：同步 toggle 状态且不抛异常。"""
        page = AppearanceSettingsPage()
        page.refresh_theme()
        assert page._dark_toggle.checked == page._dark_toggle.checked
        safe_teardown(page)

    def test_event_filter_dispatches_to_super(self, qapp: QApplication) -> None:
        """面板未创建时 eventFilter 对点击返回 False（放行继续传播）。"""
        page = AppearanceSettingsPage()
        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(10, 10),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        assert page.eventFilter(page, press) is False
        safe_teardown(page)

    def test_hide_and_close_safe(self, qapp: QApplication) -> None:
        """hideEvent / closeEvent 在面板未创建时不抛异常。"""
        page = AppearanceSettingsPage()
        page.hideEvent(QHideEvent())
        page.closeEvent(QCloseEvent())
        safe_teardown(page)

    def test_mica_sliders_removed(self, qapp: QApplication) -> None:
        """米卡参数已固定（按主题定值）：外观页不再构建滑动条配置项。"""
        page = AppearanceSettingsPage()
        assert not hasattr(page, "_mica_sliders")
        assert not hasattr(page, "_mica_value_labels")
        assert not hasattr(page, "_mica_values")
        assert not hasattr(page, "_mica_preview_timer")
        assert not hasattr(page, "_native_mica_toggle")
        safe_teardown(page)

    def test_bg_segmented_hugs_content_width(self, qapp: QApplication) -> None:
        """「窗口背景」分段控件宽度贴合选项内容，不占满页面/卡片整宽。"""
        page = AppearanceSettingsPage()
        page.resize(640, 900)
        qapp.processEvents()

        seg = page._bg_segmented
        hint = seg.sizeHint()
        assert hint.width() > 0
        assert seg.width() == hint.width()
        assert seg.width() < page.width()
        # pill 容器背景只包住选项内容
        assert int(seg._header.content_width) == seg.width()
        safe_teardown(page)

    # ── 窗口背景区块（米卡效果 / 自定义图片） ─────────────────────

    @staticmethod
    def _make_fake_bg_main_window() -> Any:
        """构造记录背景 API 调用顺序的假主窗口（无需真实 QWidget）。"""

        class _FakeBgMainWindow:
            """记录 set_background_mode / set_custom_background_image 调用。"""

            def __init__(self) -> None:
                self.mode_calls: list[str] = []
                self.image_calls: list[str] = []

            def set_background_mode(self, mode: str) -> None:
                self.mode_calls.append(mode)

            def set_custom_background_image(self, path: str) -> bool:
                self.image_calls.append(path)
                return True

        return _FakeBgMainWindow()

    @staticmethod
    def _make_fake_file_dialog(result: tuple[str, str]) -> Any:
        """构造 getOpenFileName 返回固定结果的假 QFileDialog。"""

        class _FakeFileDialog:
            """静态 getOpenFileName 返回预设 (path, filter) 元组。"""

            @staticmethod
            def getOpenFileName(*args: Any, **kwargs: Any) -> tuple[str, str]:
                return result

        return _FakeFileDialog

    def test_background_default_mica_ui_state(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """默认（V2 无背景设置）：mica 模式——分段 0、图片行隐藏、滑动条可用。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )

        page = AppearanceSettingsPage()
        assert page._bg_mode == "mica"
        assert page._bg_image_name == ""
        assert page._bg_segmented.current_index == 1
        assert page._bg_image_row.isVisibleTo(page) is False
        assert page._bg_file_label.text() == "未设置"
        safe_teardown(page)

    def test_background_image_mode_loaded_from_v2(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """V2 保存 image 模式且文件存在：初始即 image UI 状态（不触发应用）。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )
        from components.custom_background import BACKGROUND_DIR_NAME

        tmp_file = str(tmp_path / "settings_v2.json")
        v2 = SettingsManagerV2(tmp_file)
        v2.load()
        v2.set(
            "appearance.background",
            {"mode": "image", "image": "custom_background.png"},
        )
        v2.save()

        bg_dir = tmp_path / BACKGROUND_DIR_NAME
        bg_dir.mkdir()
        pm = QPixmap(16, 16)
        pm.fill(QColor("#336699"))
        assert pm.save(str(bg_dir / "custom_background.png"), "PNG") is True

        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))

        page = AppearanceSettingsPage()
        assert page._bg_mode == "image"
        assert page._bg_image_name == "custom_background.png"
        assert page._bg_segmented.current_index == 2
        assert page._bg_image_row.isVisibleTo(page) is True
        assert page._bg_file_label.text() == "custom_background.png"
        safe_teardown(page)

    def test_apply_background_settings_routes_and_saves(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """_apply_background_settings：暂存优先（未提交不触碰主窗口与磁盘）。

        新语义：仅写入暂存缓存并刷新本页 UI；主窗口应用与 V2 落盘统一由
        ``SettingsLayout._submit_settings`` 在点击应用/确定时执行。
        """
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "find_main_window", lambda self: fake_mw
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))

        page = AppearanceSettingsPage()
        page._bg_image_name = "custom_background.png"

        # image 暂存：不直调主窗口、不落盘，仅缓存 + UI 可见
        page._apply_background_settings("image")
        assert fake_mw.image_calls == []
        assert fake_mw.mode_calls == []
        assert page._staging_cache.get("appearance.background.mode") == "image"
        assert page._staging_cache.get("appearance.background.image") == "custom_background.png"
        assert page._bg_image_row.isVisibleTo(page) is True

        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background.mode") == "mica"

        # mica 暂存：同样仅缓存，不动主窗口图片接口
        page._apply_background_settings("mica")
        assert fake_mw.mode_calls == []
        assert len(fake_mw.image_calls) == 0
        assert page._bg_image_row.isVisibleTo(page) is False
        assert page._staging_cache.get("appearance.background.mode") == "mica"
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background.mode") == "mica"
        safe_teardown(page)

    def test_bg_segment_switch_with_existing_image(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """已有持久化图片时切换分段：暂存 image 模式（不经文件对话框、不直写）。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )
        from components.custom_background import BACKGROUND_DIR_NAME

        tmp_file = str(tmp_path / "settings_v2.json")
        bg_dir = tmp_path / BACKGROUND_DIR_NAME
        bg_dir.mkdir()
        pm = QPixmap(16, 16)
        pm.fill(QColor("#336699"))
        assert pm.save(str(bg_dir / "custom_background.png"), "PNG") is True

        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "find_main_window", lambda self: fake_mw
        )

        page = AppearanceSettingsPage()
        page._bg_image_name = "custom_background.png"
        # 模拟用户点击图像分段（触发 current_changed → 处理器，仅暂存）
        page._bg_segmented.set_current_index(2)

        assert page._bg_mode == "image"
        assert page._staging_cache.get("appearance.background.mode") == "image"
        assert len(fake_mw.image_calls) == 0
        assert fake_mw.mode_calls == []
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background.mode") == "mica"
        safe_teardown(page)

    def test_bg_segment_switch_cancel_reverts(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """无图片时切换分段后取消选择：分段回退、设置不变、不调用主窗口。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))
        monkeypatch.setattr(
            sl_mod, "QFileDialog", self._make_fake_file_dialog(("", ""))
        )
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "find_main_window", lambda self: fake_mw
        )

        page = AppearanceSettingsPage()
        page._bg_segmented.set_current_index(2)

        # 取消：分段编程式回退到云母，模式与持久化设置保持默认（未被写入）
        assert page._bg_segmented.current_index == 1
        assert page._bg_mode == "mica"
        assert fake_mw.mode_calls == []
        assert fake_mw.image_calls == []
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background") == {"mode": "mica", "image": "", "ambient": True, "blur": 0, "transparency": 80}
        safe_teardown(page)

    def test_bg_segment_switch_import_failure_shows_dialog(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """导入失败：弹 danger 对话框、分段回退、不切换不改设置。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))
        monkeypatch.setattr(
            sl_mod, "QFileDialog",
            self._make_fake_file_dialog(("D:/fake/pic.png", "图片文件 (*.png)")),
        )
        monkeypatch.setattr(
            sl_mod, "import_custom_background_image", lambda path: None
        )
        dialog_calls: list[dict] = []
        monkeypatch.setattr(
            sl_mod, "create_danger_dialog",
            lambda **kwargs: dialog_calls.append(kwargs),
        )
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "find_main_window", lambda self: fake_mw
        )

        page = AppearanceSettingsPage()
        page._bg_segmented.set_current_index(2)

        assert len(dialog_calls) == 1
        assert dialog_calls[0]["title"] == "导入失败"
        assert page._bg_segmented.current_index == 1
        assert page._bg_mode == "mica"
        assert fake_mw.mode_calls == []
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background") == {"mode": "mica", "image": "", "ambient": True, "blur": 0, "transparency": 80}
        safe_teardown(page)

    def test_choose_bg_image_success_via_button(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """按钮点击选择图片成功：暂存文件名与 image 模式（提交前不直写）。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))
        monkeypatch.setattr(
            sl_mod, "QFileDialog",
            self._make_fake_file_dialog(("D:/fake/pic.png", "图片文件 (*.png)")),
        )
        dest = str(tmp_path / "backgrounds" / "custom_background.png")
        monkeypatch.setattr(
            sl_mod, "import_custom_background_image", lambda path: dest
        )
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "find_main_window", lambda self: fake_mw
        )

        page = AppearanceSettingsPage()
        # 模拟按钮点击（clicked → _on_choose_bg_image_clicked → 非强制选择）
        page._bg_choose_btn.click()

        assert page._bg_image_name == "custom_background.png"
        assert page._bg_file_label.text() == "custom_background.png"
        assert page._bg_mode == "image"
        assert page._bg_segmented.current_index == 1  # 按钮入口不切分段
        assert page._staging_cache.get("appearance.background.image") == "custom_background.png"
        assert fake_mw.image_calls == []
        assert fake_mw.mode_calls == []
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background.mode") == "mica"
        safe_teardown(page)

    def test_update_bg_ui_state_toggles_image_row(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """_update_bg_ui_state：image 模式显示图片行，mica 模式隐藏。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )

        page = AppearanceSettingsPage()
        page._bg_mode = "image"
        page._update_bg_ui_state()
        assert page._bg_image_row.isVisibleTo(page) is True

        page._bg_mode = "mica"
        page._update_bg_ui_state()
        assert page._bg_image_row.isVisibleTo(page) is False
        safe_teardown(page)


# =============================================================================
# _load_all 保持 Python（faf-core-rust-migration todo 10 回归测试）
# =============================================================================

class TestLoadAllStaysPython:
    """``FileSelectorLayout._load_all`` 保持 Python 实现，不经 faf_core native。

    回归背景（faf-core-rust-migration todo 10）：「All」视图枚举
    逻辑驱动器（GetLogicalDrives 位掩码 ≤26 个盘 + 每盘 os.stat）无性能需求，
    显式排除出 native 范围。本组 mock 位掩码 + 注入确定性元数据，断言驱动
    列表正确且枚举路径仍为 Python（os.stat 逐盘调用、faf_core 桥零触碰）。
    """

    def test_load_all_drives_from_bitmask_stays_python(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """mock GetLogicalDrives 位掩码 → 模型驱动列表正确且确认保持 Python。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            monkeypatch: 用例级猴子补丁。
        """
        import ctypes

        import freeassetfilter.ui.layout.file_selector_layout as fsl_mod
        from components.file_list_model import FileNameRole, FilePathRole, IsDirRole

        # 位掩码 0b0000_0000_0000_0111 = 位 0/1/2 → A:/B:/C:
        drives_bitmask: int = 0b0000_0000_0000_0111
        stat_calls: list[str] = []
        bridge_calls: list[str] = []
        fake_stat = MagicMock(
            st_mtime=1_700_000_000.0,
            st_ctime=1_700_000_000.0,
        )
        orig_stat = os.stat

        def _fake_stat(path: object, **kwargs: object) -> object:
            """仅拦截驱动器根 stat（记录 + 返回确定性元数据），其余委托真实实现。"""
            if isinstance(path, str) and path in ("A:\\", "B:\\", "C:\\"):
                stat_calls.append(path)
                return fake_stat
            return orig_stat(path, **kwargs)

        monkeypatch.setattr(
            fsl_mod,
            "get_faf_core_bridge",
            lambda: bridge_calls.append("bridge"),
        )
        monkeypatch.setattr(
            ctypes.windll.kernel32, "GetLogicalDrives", lambda: drives_bitmask
        )
        # 全部盘符视为物理磁盘（DRIVE_FIXED=3）：默认加载策略下全部进入
        monkeypatch.setattr(
            ctypes.windll.kernel32, "GetDriveTypeW", lambda _path: 3
        )
        monkeypatch.setattr(os, "stat", _fake_stat)

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            layout._load_all()

            model = layout._file_model
            assert model.rowCount() == 3
            names = [
                model.data(model.index(i, 0), FileNameRole) for i in range(model.rowCount())
            ]
            paths = [
                model.data(model.index(i, 0), FilePathRole) for i in range(model.rowCount())
            ]
            assert names == ["A:", "B:", "C:"]
            assert paths == ["A:\\", "B:\\", "C:\\"]
            for i in range(model.rowCount()):
                assert model.data(model.index(i, 0), IsDirRole) is True
            # 确认走 Python：逐盘 os.stat 一次，faf_core 桥完全不触碰
            assert stat_calls == ["A:\\", "B:\\", "C:\\"]
            assert bridge_calls == [], "_load_all 不得触碰 faf_core 桥（保持 Python）"
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_load_all_skips_unset_drive_bits(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """位掩码间隙正确跳过：0b101 → 仅 A:/C: 两盘进入模型。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            monkeypatch: 用例级猴子补丁。
        """
        import ctypes

        import freeassetfilter.ui.layout.file_selector_layout as fsl_mod
        from components.file_list_model import FileNameRole

        fake_stat = MagicMock(
            st_mtime=1_700_000_000.0,
            st_ctime=1_700_000_000.0,
        )
        orig_stat = os.stat

        def _fake_stat(path: object, **kwargs: object) -> object:
            """仅拦截驱动器根 stat，其余委托真实实现（避免污染 pytest 内部）。"""
            if isinstance(path, str) and path in ("A:\\", "C:\\"):
                return fake_stat
            return orig_stat(path, **kwargs)

        monkeypatch.setattr(
            fsl_mod, "get_faf_core_bridge", lambda: None
        )
        monkeypatch.setattr(
            ctypes.windll.kernel32, "GetLogicalDrives", lambda: 0b101
        )
        # 盘符类型视为物理磁盘（DRIVE_FIXED=3）——本用例只验证位掩码间隙跳过
        monkeypatch.setattr(
            ctypes.windll.kernel32, "GetDriveTypeW", lambda _path: 3
        )
        monkeypatch.setattr(os, "stat", _fake_stat)

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            layout._load_all()

            model = layout._file_model
            assert model.rowCount() == 2
            names = [
                model.data(model.index(i, 0), FileNameRole) for i in range(model.rowCount())
            ]
            assert names == ["A:", "C:"]
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_load_all_excludes_remote_drives_stays_python(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """网络/映射盘（DRIVE_REMOTE）默认不加载；All 收集保持纯 Python。

        位掩码 0b111 → A:/B:/C:，GetDriveTypeW 将 A: 标为 DRIVE_REMOTE(4)、
        其余标为 DRIVE_FIXED(3)；断言仅 B:/C: 进入条目、网络盘不做 stat，
        且 ``_collect_directory_entries("All")`` 分支不触碰 faf_core 桥。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            monkeypatch: 用例级猴子补丁。
        """
        import ctypes

        import freeassetfilter.ui.layout.file_selector_layout as fsl_mod

        drives_bitmask: int = 0b111
        stat_calls: list[str] = []
        bridge_calls: list[str] = []
        fake_stat = MagicMock(
            st_mtime=1_700_000_000.0,
            st_ctime=1_700_000_000.0,
        )
        orig_stat = os.stat

        def _fake_stat(path: object, **kwargs: object) -> object:
            """仅拦截驱动器根 stat（记录），其余委托真实实现。"""
            if isinstance(path, str) and path in ("A:\\", "B:\\", "C:\\"):
                stat_calls.append(path)
                return fake_stat
            return orig_stat(path, **kwargs)

        def _fake_drive_type(path: object) -> int:
            """A: 为网络/映射盘（4），其余为固定盘（3）。"""
            value = getattr(path, "value", path)
            return 4 if str(value) == "A:\\" else 3

        monkeypatch.setattr(
            fsl_mod,
            "get_faf_core_bridge",
            lambda: bridge_calls.append("bridge"),
        )
        monkeypatch.setattr(
            ctypes.windll.kernel32, "GetLogicalDrives", lambda: drives_bitmask
        )
        monkeypatch.setattr(
            ctypes.windll.kernel32, "GetDriveTypeW", _fake_drive_type
        )
        monkeypatch.setattr(os, "stat", _fake_stat)

        entries = FileSelectorLayout._collect_directory_entries("All")

        assert [e["name"] for e in entries] == ["B:", "C:"], "仅物理磁盘进入 All 视图"
        assert stat_calls == ["B:\\", "C:\\"], "网络盘不应触发 stat"
        assert bridge_calls == [], "All 收集不得触碰 faf_core 桥（保持 Python）"

    def test_collect_all_includes_remote_and_cdrom_when_enabled(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """开关开启：网络/映射盘（4）与光驱（5）进入 All 视图，物理盘不受影响。

        位掩码 0b1111 → A:/B:/C:/D:；类型分别为 网络盘(4)/固定盘(3)/
        光驱(5)/RAM 盘(6)。默认（False）仅 B:/D:；开启（True）为 A:-D:。
        """
        import ctypes

        import freeassetfilter.ui.layout.file_selector_layout as fsl_mod

        drives_bitmask: int = 0b1111
        drive_types = {"A:\\": 4, "B:\\": 3, "C:\\": 5, "D:\\": 6}
        fake_stat = MagicMock(
            st_mtime=1_700_000_000.0,
            st_ctime=1_700_000_000.0,
        )
        orig_stat = os.stat

        def _fake_stat(path: object, **kwargs: object) -> object:
            if isinstance(path, str) and path in drive_types:
                return fake_stat
            return orig_stat(path, **kwargs)

        def _fake_drive_type(path: object) -> int:
            value = getattr(path, "value", path)
            return drive_types.get(str(value), 3)

        monkeypatch.setattr(
            ctypes.windll.kernel32, "GetLogicalDrives", lambda: drives_bitmask
        )
        monkeypatch.setattr(
            ctypes.windll.kernel32, "GetDriveTypeW", _fake_drive_type
        )
        monkeypatch.setattr(os, "stat", _fake_stat)

        default_entries = FileSelectorLayout._collect_all_drives_python()
        assert [e["name"] for e in default_entries] == ["B:", "D:"], (
            "默认仅物理磁盘（固定盘/RAM 盘）"
        )

        enabled_entries = FileSelectorLayout._collect_all_drives_python(True)
        assert [e["name"] for e in enabled_entries] == ["A:", "B:", "C:", "D:"], (
            "开关开启后网络盘与光驱一并进入 All 视图"
        )


# =============================================================================
# ui.layout.settings_layout — 通用页（界面布局切换）
# =============================================================================
class TestGeneralSettingsPage:
    """GeneralSettingsPage：暂存隔离、分段同步与提交路由。"""

    @staticmethod
    def _make_cache(mode: str = "workspace") -> Any:
        """构造带指定布局模式的暂存缓存。"""
        from freeassetfilter.ui.layout.settings_staging_cache import (
            SettingsStagingCache,
        )

        cache = SettingsStagingCache()
        cache.begin({"general": {"layout_mode": mode}})
        return cache

    def test_construct_and_default_from_cache(self, qapp: QApplication) -> None:
        """构造：从暂存缓存读取布局模式并同步分段选中。"""
        page = GeneralSettingsPage(staging_cache=self._make_cache("classic"))
        assert page._layout_mode == "classic"
        assert page._layout_segmented.current_index == 0
        # 分段名称：经典 / New
        assert page.LAYOUT_LABELS == ("经典", "New")
        # 介绍文字：仅显示当前（经典）布局介绍 + 换行提示行
        desc = page._layout_row.desc_label.text()
        assert "经典布局" in desc
        assert "New 布局" not in desc
        assert desc.endswith(GeneralSettingsPage._LAYOUT_HINT)
        assert "\n" in desc
        safe_teardown(page)

    def test_segment_change_updates_description(self, qapp: QApplication) -> None:
        """切换分段：介绍文字即时切换为对应布局的介绍。"""
        cache = self._make_cache("classic")
        page = GeneralSettingsPage(staging_cache=cache)

        page._layout_segmented.set_current_index(1, animate=False)
        qapp.processEvents()

        desc = page._layout_row.desc_label.text()
        assert "New 布局" in desc
        assert "经典布局" not in desc
        assert GeneralSettingsPage._LAYOUT_HINT in desc
        safe_teardown(page)

    def test_segment_change_writes_staging_only(self, qapp: QApplication) -> None:
        """切换分段只写暂存缓存（不落盘、不触碰主窗口）。"""
        cache = self._make_cache("workspace")
        page = GeneralSettingsPage(staging_cache=cache)
        assert page._layout_segmented.current_index == 1

        page._layout_segmented.set_current_index(0, animate=False)
        qapp.processEvents()

        assert page._layout_mode == "classic"
        assert cache.get("general.layout_mode") == "classic"
        safe_teardown(page)

    def test_refresh_from_staging_restores(self, qapp: QApplication) -> None:
        """refresh_from_staging：以暂存缓存为唯一数据源回写控件展示。"""
        cache = self._make_cache("workspace")
        page = GeneralSettingsPage(staging_cache=cache)
        page._layout_segmented.set_current_index(0, animate=False)
        qapp.processEvents()
        assert page._layout_mode == "classic"

        # 外部（取消/重置链路）使缓存回到 workspace → 刷新后展示随之恢复
        cache.set("general.layout_mode", "workspace")
        page.refresh_from_staging()

        assert page._layout_mode == "workspace"
        assert page._layout_segmented.current_index == 1
        safe_teardown(page)

    def test_submit_routes_layout_mode_to_main_window(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """提交：布局模式下发主窗口（暂存期不下发）并落盘到 V2。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        # 性能档位钩子为真实副作用（电源策略/GPU 启动器），提交链路测试不触碰
        monkeypatch.setattr(
            sl_mod.SettingsLayout,
            "_apply_staged_perf_profile",
            lambda self, profile: None,
        )

        class _FakeMainWindow:
            """记录布局切换调用的假主窗口。"""

            def __init__(self) -> None:
                self.layout_calls: list[str] = []

            def set_layout_mode(self, mode: str) -> bool:
                self.layout_calls.append(mode)
                return True

        fake_mw = _FakeMainWindow()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "find_main_window", lambda self: fake_mw
        )

        from theme import tm

        prev_mode = tm.get_theme_mode()
        layout = SettingsLayout()
        try:
            # 暂存切换到经典三栏 → 提交前不下发主窗口
            layout._general_page._layout_segmented.set_current_index(0, animate=False)
            qapp.processEvents()
            assert fake_mw.layout_calls == []

            assert layout._submit_settings() is True
            assert fake_mw.layout_calls == ["classic"]

            saved = SettingsManagerV2(tmp_file)
            saved.load()
            assert saved.get("general.layout_mode") == "classic"
        finally:
            try:
                tm.set_theme_mode(prev_mode)
            except Exception:
                pass  # teardown 还原主题失败：忽略，避免影响断言
            safe_teardown(layout)

    def test_toggles_default_false_from_cache(self, qapp: QApplication) -> None:
        """构造：AI 入口 / 网络盘 / 空白右键返回开关默认均从缓存读到 False。"""
        page = GeneralSettingsPage(staging_cache=self._make_cache("workspace"))
        assert page._ai_entry is False
        assert page._include_remote_drives is False
        assert page._blank_right_click_go_back is False
        assert page._ai_toggle.checked is False
        assert page._drives_toggle.checked is False
        assert page._blank_back_toggle.checked is False
        safe_teardown(page)

    def test_toggles_write_staging_only(self, qapp: QApplication) -> None:
        """切换三个开关只写暂存缓存（不落盘、不触碰主窗口）。"""
        cache = self._make_cache("workspace")
        page = GeneralSettingsPage(staging_cache=cache)

        page._ai_toggle.checked = True
        page._drives_toggle.checked = True
        page._blank_back_toggle.checked = True
        qapp.processEvents()

        assert page._ai_entry is True
        assert page._include_remote_drives is True
        assert page._blank_right_click_go_back is True
        assert cache.get("general.enable_ai_entry") is True
        assert cache.get("general.include_remote_drives") is True
        assert cache.get("general.blank_right_click_go_back") is True
        safe_teardown(page)

    def test_refresh_from_staging_restores_toggles(self, qapp: QApplication) -> None:
        """refresh_from_staging：外部（取消/重置）修改缓存后开关展示恢复。"""
        cache = self._make_cache("workspace")
        page = GeneralSettingsPage(staging_cache=cache)
        page._ai_toggle.checked = True
        page._drives_toggle.checked = True
        page._blank_back_toggle.checked = True
        qapp.processEvents()

        cache.set("general.enable_ai_entry", False)
        cache.set("general.include_remote_drives", False)
        cache.set("general.blank_right_click_go_back", False)
        page.refresh_from_staging()

        assert page._ai_entry is False
        assert page._include_remote_drives is False
        assert page._blank_right_click_go_back is False
        assert page._ai_toggle.checked is False
        assert page._drives_toggle.checked is False
        assert page._blank_back_toggle.checked is False
        safe_teardown(page)

    def test_submit_routes_general_toggles_to_main_window(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """提交：三个开关下发主窗口（暂存期不下发）并落盘到 V2。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(
            sl_mod.SettingsLayout,
            "_apply_staged_perf_profile",
            lambda self, profile: None,
        )

        class _FakeMainWindow:
            """记录通用开关下发的假主窗口。"""

            def __init__(self) -> None:
                self.ai_calls: list[bool] = []
                self.drives_calls: list[bool] = []
                self.blank_back_calls: list[bool] = []

            def set_ai_entry_enabled(self, enabled: bool) -> None:
                self.ai_calls.append(bool(enabled))

            def set_include_remote_drives(self, enabled: bool) -> None:
                self.drives_calls.append(bool(enabled))

            def set_blank_right_click_go_back(self, enabled: bool) -> None:
                self.blank_back_calls.append(bool(enabled))

        fake_mw = _FakeMainWindow()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "find_main_window", lambda self: fake_mw
        )

        from theme import tm

        prev_mode = tm.get_theme_mode()
        layout = SettingsLayout()
        try:
            layout._general_page._ai_toggle.checked = True
            layout._general_page._drives_toggle.checked = True
            layout._general_page._blank_back_toggle.checked = True
            qapp.processEvents()
            assert fake_mw.ai_calls == []
            assert fake_mw.drives_calls == []
            assert fake_mw.blank_back_calls == []

            assert layout._submit_settings() is True
            assert fake_mw.ai_calls == [True]
            assert fake_mw.drives_calls == [True]
            assert fake_mw.blank_back_calls == [True]

            saved = SettingsManagerV2(tmp_file)
            saved.load()
            assert saved.get("general.enable_ai_entry") is True
            assert saved.get("general.include_remote_drives") is True
            assert saved.get("general.blank_right_click_go_back") is True
        finally:
            try:
                tm.set_theme_mode(prev_mode)
            except Exception:
                pass  # teardown 还原主题失败：忽略，避免影响断言
            safe_teardown(layout)


# =============================================================================
# AI 功能入口开关（PDF / 文本 / 字体预览器）
# =============================================================================
class TestAiEntryToggles:
    """AI 入口开关：默认隐藏 / 开启挂载 / 关闭摘除 / 抽屉惰性创建。"""

    @staticmethod
    def _registered(bar: Any, widget: Any) -> bool:
        """控件是否已注册到顶栏四个功能区之一。"""
        return any(
            widget in collection
            for collection in (
                bar._lead_widgets,
                bar._trail_widgets,
                bar._left_widgets,
                bar._right_widgets,
            )
        )

    @pytest.mark.parametrize("kind", ["pdf", "text", "font"])
    def test_ai_entry_lifecycle(
        self, qapp: QApplication, kind: str,
    ) -> None:
        """默认不在顶栏且抽屉未创建；开启后挂载并可展开；关闭后摘除收起。"""
        from freeassetfilter.ui.layout.preview.font_previewer_layout import (
            FontPreviewerLayout,
        )
        from freeassetfilter.ui.layout.preview.pdf_previewer_layout import (
            PdfPreviewerLayout,
        )
        from freeassetfilter.ui.layout.preview.text_previewer_layout import (
            TextPreviewerLayout,
        )

        mapping = {
            "pdf": PdfPreviewerLayout,
            "text": TextPreviewerLayout,
            "font": FontPreviewerLayout,
        }
        layout = mapping[kind]()
        layout.show()
        layout.resize(1000, 700)
        _pump_events(qapp)
        try:
            bar = layout._top_bar
            # 默认关闭：不在顶栏、抽屉未创建
            assert not self._registered(bar, layout._ai_btn)
            assert layout._ai_drawer is None

            # 开启：按钮挂载、抽屉惰性创建并可展开
            layout.set_ai_entry_enabled(True)
            _pump_events(qapp)
            assert self._registered(bar, layout._ai_btn)
            assert layout._ai_drawer is not None
            layout._toggle_ai_drawer()
            qapp.processEvents()
            assert layout._ai_drawer.is_open

            # 等待展开动画结束：动画期间的 close_drawer 为 no-op（组件语义）
            deadline = time.time() + 2.0
            while layout._ai_drawer._animating and time.time() < deadline:
                qapp.processEvents()
                time.sleep(0.01)

            # 重复开启幂等：按钮只注册一次
            layout.set_ai_entry_enabled(True)
            for collection in (bar._lead_widgets, bar._trail_widgets):
                if layout._ai_btn in collection:
                    assert collection.count(layout._ai_btn) == 1

            # 关闭：收起抽屉并摘除按钮；再次开启可恢复
            layout.set_ai_entry_enabled(False)
            _pump_events(qapp)
            assert not layout._ai_drawer.is_open
            assert not self._registered(bar, layout._ai_btn)

            layout.set_ai_entry_enabled(True)
            _pump_events(qapp)
            assert self._registered(bar, layout._ai_btn)
        finally:
            safe_teardown(layout)


# =============================================================================
# 封面调色板提取（缓冲分桶实现 vs 旧逐像素实现逐项对拍）
# =============================================================================
class TestPaletteExtractionParity:
    """``_extract_palette_from_cover`` 优化实现与旧实现输出完全一致。

    旧实现逐像素构造 ``QColor``（4096 次跨界调用）；优化版单次转换
    RGBA8888 后读像素缓冲。两版必须逐项相等（含 Counter 平局顺序与
    单主导色扩展分支），此对拍防止优化引入行为漂移。
    """

    @staticmethod
    def _reference_palette(cover_data: bytes) -> List[QColor]:
        """旧实现逐字参考版（仅测试对拍使用）。

        Args:
            cover_data: 封面图像二进制数据。

        Returns:
            list[QColor]: 与产品旧实现同序的调色板。
        """
        from collections import Counter

        from PySide6.QtGui import QImage

        image = QImage.fromData(cover_data)
        if image.isNull():
            return []

        image = image.scaled(
            64, 64, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )

        buckets: Counter = Counter()
        for y in range(image.height()):
            for x in range(image.width()):
                color = QColor(image.pixel(x, y))
                if color.alpha() <= 0:
                    continue
                key = (
                    (color.red() // 32) * 32,
                    (color.green() // 32) * 32,
                    (color.blue() // 32) * 32,
                )
                buckets[key] += 1

        if not buckets:
            return []

        palette = [QColor(r, g, b) for (r, g, b), _ in buckets.most_common(5)]
        if len(palette) == 1:
            from components.styled_fluid_background import StyledFluidBackground

            palette = StyledFluidBackground._build_from_seed(palette[0])
        return palette if len(palette) >= 2 else []

    @staticmethod
    def _to_rgb(palette: List[QColor]) -> List[tuple]:
        """调色板转 ``[(r, g, b), ...]`` 以做顺序敏感的逐项比较。"""
        return [(c.red(), c.green(), c.blue()) for c in palette]

    def _assert_parity(self, cover_data: bytes) -> None:
        """断言优化实现与参考实现输出逐项一致。"""
        expected = self._to_rgb(self._reference_palette(cover_data))
        actual = self._to_rgb(
            VideoPlayerLayout._extract_palette_from_cover(cover_data)
        )
        assert actual == expected

    def test_solid_color_single_bucket_parity(self, tmp_path: Path) -> None:
        """单主导色（触发类比色板扩展分支）对拍一致。"""
        from PIL import Image

        path = tmp_path / "solid.png"
        Image.new("RGB", (64, 64), (200, 80, 40)).save(path, format="PNG")
        self._assert_parity(path.read_bytes())

    def test_gradient_with_transparency_parity(self, tmp_path: Path) -> None:
        """渐变 + 透明像素（跳过分支 + Counter 平局顺序）对拍一致。"""
        from PIL import Image

        img = Image.new("RGBA", (96, 96))
        px = img.load()
        for y in range(96):
            for x in range(96):
                px[x, y] = (
                    (x * 3) % 256,
                    (y * 5) % 256,
                    (x + y) % 256,
                    0 if (x + y) % 7 == 0 else 255,
                )
        path = tmp_path / "gradient.png"
        img.save(path, format="PNG")
        self._assert_parity(path.read_bytes())

    def test_jpeg_without_alpha_parity(self, tmp_path: Path) -> None:
        """JPEG（无 alpha 通道，格式转换路径）对拍一致。"""
        from PIL import Image

        path = tmp_path / "photo.jpg"
        Image.new("RGB", (80, 80), (10, 120, 240)).save(path, format="JPEG")
        self._assert_parity(path.read_bytes())

    def test_gif_indexed_format_parity(self, tmp_path: Path) -> None:
        """GIF（索引调色板格式，Qt 解码后可能非 RGBA）对拍一致。"""
        from PIL import Image

        img = Image.new("P", (64, 64))
        img.putpalette([i for i in range(256)] * 3)
        for y in range(64):
            for x in range(64):
                img.putpixel((x, y), (x + y) % 256)
        path = tmp_path / "indexed.gif"
        img.save(path, format="GIF")
        self._assert_parity(path.read_bytes())

    def test_invalid_data_returns_empty(self) -> None:
        """坏数据 → 两实现均返回空列表。"""
        assert VideoPlayerLayout._extract_palette_from_cover(b"not an image") == []
        assert self._reference_palette(b"not an image") == []