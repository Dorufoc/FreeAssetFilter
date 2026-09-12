"""
文件信息预览面板 — 新界面统一预览器下方信息区（ui/layout/preview/file_info_panel.py）

排版（单控件自绘文本流，从零实现）：
- 内容区不再创建任何条目卡片 / 行容器 / 图标徽章等子控件，全部信息由
  一个自绘控件以 QPainter 文本流逐行绘制（无可视定位框、无分隔线）。
- 顶部：文件名（大字号，超长省略，悬停提示全名）与其下方路径（按宽度换行）；
  字段区：标签列定宽左对齐 + 值列自动换行。
- 底侧常驻两行小字入口（滚动区外固定）：「详细信息」「哈希值」——
  独立展开/收起、独立计算、互不触发；展开内容（含 EXIF 常用子集与
  「展开全部 N 条标签」命中链接）作为画布区块追加并自动滚到底部。
- 单击某字段值 = 复制该值（右上角短暂提示）；右键 = 复制该字段/复制全部。
- 哈希展开时画布内自绘细进度条与百分比。
- 全部耗时采集在工作线程执行；切换文件/清空后旧结果作废（令牌守卫）；
  哈希与详细信息（不含 EXIF）写入共享缓存 data/file_info_cache.json。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_THIS_FILE = Path(__file__).resolve()
_UI_ROOT = str(_THIS_FILE.parent.parent.parent)  # freeassetfilter/ui/
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)
_PROJECT_ROOT = str(_THIS_FILE.parent.parent.parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from components.styled_context_menu import StyledContextMenu
from components.styled_scroll_area import StyledScrollArea, StyledScrollBar
from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRect,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QMouseEvent, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from theme import tm

from freeassetfilter.services import file_info_service as fis
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss

# 注：耗时采集走 QThreadPool 全局池（QRunnable 用完即弃）；面板持有在途
# 任务引用（``self._tasks``）防 GC，切文件时协作式取消 + 令牌守卫，无
# 模块级保活集合、无 quit()/wait()/deleteLater()。


def _rgba(color: QColor) -> str:
    return f"rgba({color.red()},{color.green()},{color.blue()},{color.alpha() / 255:.2f})"


class _WorkSignals(QObject):
    """后台采集完成信号中转（任务持有，跨线程队列投递到 UI 线程）。"""

    done = Signal(object)
    progress = Signal(int)


class _WorkTask(QRunnable):
    """通用后台采集池任务基类（子类实现 run；取消经协作式标记）。"""

    def __init__(self) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._signals = _WorkSignals()
        self._cancelled = False

    @property
    def done(self):
        """采集完成信号（经中转对象）。"""
        return self._signals.done

    @property
    def progress(self):
        """哈希进度信号 ``(percent)``（经中转对象）。"""
        return self._signals.progress

    def request_cancel(self) -> None:
        """请求取消（协作式标记；run 内检查）。"""
        self._cancelled = True

    def start(self) -> None:
        """投递到全局线程池执行（替代旧 QThread.start()）。"""
        QThreadPool.globalInstance().start(self)


class _DetailTask(_WorkTask):
    """详细信息采集任务：run 内计算并写缓存，结果经 done 回传。"""

    def __init__(
        self,
        path: str,
        cache_path: Optional[str],
        parent: Optional[QWidget] = None,
    ):
        # parent 参数仅为兼容旧构造签名保留；QRunnable 非 QObject，不参与父子。
        super().__init__()
        self._path = path
        self._cache_path = cache_path

    def run(self) -> None:
        data = fis.collect_detail_data(self._path)
        if not self._cancelled:
            try:
                fis.write_cached(self._path, details=data["rows"], cache_path=self._cache_path)
            except Exception:  # noqa: BLE001
                pass
        self.done.emit(data)


class _HashTask(_WorkTask):
    """哈希计算任务：单次读盘三哈希，progress 汇报进度。"""

    def __init__(
        self,
        path: str,
        cache_path: Optional[str],
        parent: Optional[QWidget] = None,
    ):
        # parent 参数仅为兼容旧构造签名保留；QRunnable 非 QObject，不参与父子。
        super().__init__()
        self._path = path
        self._cache_path = cache_path

    def run(self) -> None:
        def _report(percent: int) -> None:
            self.progress.emit(percent)

        values = fis.compute_hashes(
            self._path,
            progress=_report,
            should_stop=lambda: self._cancelled,
        )
        if not self._cancelled:
            try:
                fis.write_cached(self._path, hashes=values, cache_path=self._cache_path)
            except Exception:  # noqa: BLE001
                pass
        self.done.emit(values)


class _FoldLink(QLabel):
    """底部小字折叠入口（▸/▾ + 文案，hover 变色）。

    Args:
        text: 初始文案。
        color: 常规文字颜色（QColor）；缺省为主题 mid 80%。
        hover_color: 悬停颜色；缺省为主题 accent。
    """

    clicked = Signal()

    def __init__(
        self,
        text: str = "",
        parent: Optional[QWidget] = None,
        color: Optional[QColor] = None,
        hover_color: Optional[QColor] = None,
    ):
        super().__init__(parent)
        self._base_text = text
        self._color = color or tm.alpha_of(tm.mid, 80)
        self._hover_color = hover_color or tm.accent
        self.setText(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self._hovered = False
        self.setAttribute(Qt.WA_Hover, True)
        self._apply_style()

    def _apply_style(self) -> None:
        if not self.isEnabled():
            text_color = _rgba(tm.alpha_of(tm.mid, 35))
        elif self._hovered:
            text_color = _rgba(self._hover_color)
        else:
            text_color = _rgba(self._color)
        register_widget_qss(self,(f"color: {text_color}; font-size: 12px;"))

    def set_text(self, text: str) -> None:
        self._base_text = text
        self.setText(text)
        self._apply_style()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self._apply_style()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self._apply_style()
        super().leaveEvent(event)


class _CanvasItem:
    """一条排版产物：内容 + 几何。

    由排版（_relayout）一次性生成并存入 self._items；
    绘制、命中、tooltip、点击复制、右键菜单、Ctrl+定位只消费
    self._items —— 不存在第二套行索引/坐标，结构上杜绝
    「绘制内容与命中行错位 / 基础信息串进详细信息」。
    """

    __slots__ = (
        "kind", "rect", "height", "text_h", "text", "full_text", "label",
        "value", "mono", "label_col", "value_x", "value_width",
        "row_height", "action", "progress", "track_top", "highlight", "lines",
    )

    def __init__(
        self,
        kind: str,
        rect: QRect,
        height: int,
        text_h: int = 0,
        *,
        text: str = "",
        full_text: str = "",
        label: str = "",
        value: str = "",
        mono: bool = False,
        label_col: int = 0,
        value_x: int = 0,
        value_width: int = 0,
        row_height: int = 0,
        action: str = "",
        progress: Optional[int] = None,
        track_top: int = 0,
        highlight: bool = False,
        lines: Optional[List[str]] = None,
    ):
        self.kind = kind
        self.rect = rect
        self.height = height
        self.text_h = text_h
        self.text = text
        self.full_text = full_text
        self.label = label
        self.value = value
        self.mono = mono
        self.label_col = label_col
        self.value_x = value_x
        self.value_width = value_width
        self.row_height = row_height
        self.action = action
        self.progress = progress
        self.track_top = track_top
        self.highlight = highlight
        self.lines = lines or []

    @property
    def is_field(self) -> bool:
        """可点击复制/定位/提示的条目（属性行、文件名行、路径行）。"""
        return self.kind in ("grid", "title", "path")


# ---------------------------------------------------------------------------
# 自绘画布：文件信息区的唯一内容控件
# ---------------------------------------------------------------------------

class _InfoCanvas(QWidget):
    """信息内容画布。

    排版只发生一次：_relayout() 把 _blocks() 的块解析为 _items
    （含内容与最终几何）。paintEvent 逐条消费 _items，不再自行重算
    块或坐标；所有交互也以 _items 的 rect 为唯一命中依据。
    """

    # 字号规格（行项目与内容字号统一为 12，以项目字号为基准）
    FONT_TITLE = QFont("Microsoft YaHei UI", 17, QFont.DemiBold)
    FONT_PATH = QFont("Microsoft YaHei UI", 12)
    FONT_LABEL = QFont("Microsoft YaHei UI", 12)
    FONT_VALUE = QFont("Microsoft YaHei UI", 12)
    FONT_HEADING = QFont("Microsoft YaHei UI", 13, QFont.DemiBold)
    FONT_MONO = QFont("Consolas", 12)
    FONT_LINK = QFont("Microsoft YaHei UI", 12)

    PAD_X = 16
    PAD_TOP = 12
    PAD_BOTTOM = 14
    LABEL_GAP = 14  # 标签列与值列间距
    LINE_SPACING = 4  # 行组内行距
    GROUP_SPACING = 12  # 区块间距

    def __init__(self, panel: "FileInfoPanel"):
        super().__init__(panel._scroll_area)
        self._panel = panel
        # 唯一排版产物：内容 + 几何（绘制/命中共用）
        self._items: List[_CanvasItem] = []
        self._hover_row: Optional[_CanvasItem] = None
        self._hover_link_action: Optional[str] = None
        self._dot_frame = 0
        self._dot_timer = QTimer(self)
        self._dot_timer.setInterval(260)
        self._dot_timer.timeout.connect(self._advance_dots)
        self._relayouting = False
        # P0 节流：resize 合并（32ms 可取消），拖拽期跳过全量排版。
        self._relayout_debounce = QTimer(self)
        self._relayout_debounce.setSingleShot(True)
        self._relayout_debounce.setInterval(32)
        self._relayout_debounce.timeout.connect(self._on_relayout_timeout)
        self._pending_width = 0
        self._last_width = 0
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    # ------------------------------------------------------------------
    # 公共（由面板驱动）
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """内容/主题/折叠状态变化后重排并重绘。"""
        self._relayout(self.width())
        self._last_width = self.width()
        self._pending_width = self.width()
        self._sync_dot_timer()
        self.update()

    def set_hash_progress(self, percent: int) -> None:
        self._panel._hash["percent"] = max(0, min(100, int(percent)))
        self._relayout(self.width())
        self.update()

    @property
    def _row_blocks(self) -> List[_CanvasItem]:
        """兼容别名：仅属性行（grid）的排版记录（命中/复制用）。"""
        return [item for item in self._items if item.kind == "grid"]

    # ------------------------------------------------------------------
    # 区块内容（纯描述；几何由 _build_items 一次性展开）
    # ------------------------------------------------------------------

    def _blocks(self, content_width: int) -> List[dict]:
        """按当前状态生成绘制区块（仅内容与排版描述，不含几何）。"""
        panel = self._panel
        if panel._file_info is None:
            return []
        blocks: List[dict] = []

        # ── 顶部：文件名 + 路径 ────────────────────────────────────
        name = str(panel._summary.get("name") or "")
        path = str(panel._summary.get("path") or "")
        fm_title = QFontMetrics(self.FONT_TITLE)
        elided_name = fm_title.elidedText(name, Qt.ElideRight, content_width)
        blocks.append({"kind": "title", "text": elided_name, "full_text": name})
        blocks.append({"kind": "gap", "height": int(3 * 1.0)})
        blocks.append({"kind": "path", "text": path, "full_text": path})
        blocks.append({"kind": "gap", "height": int(12 * 1.0)})

        # ── 属性行（基础字段 + 类型字段）────────────────────────────
        self._append_grid_blocks(blocks, panel._rows, content_width, mono=False)
        blocks.append({"kind": "gap", "height": int(4 * 1.0)})

        # ── 详细信息折叠区块 ───────────────────────────────────────
        if panel._expanded == "details":
            self._append_section_blocks(blocks, "详细信息")
            status = panel._detail.get("status", "idle")
            if status == "loading":
                blocks.append({"kind": "busy", "text": "正在分析文件详细信息"})
            else:
                detail_rows: List[Tuple[str, str]] = []
                if status == "done":
                    detail_rows = [tuple(r) for r in panel._detail.get("rows") or []]
                self._append_grid_blocks(blocks, detail_rows, content_width, mono=False)
                exif_common = [tuple(r) for r in panel._detail.get("exif_common") or []]
                exif_more = [tuple(r) for r in panel._detail.get("exif_more") or []]
                if exif_common or exif_more:
                    if not exif_common:
                        self._append_grid_blocks(blocks, exif_more, content_width, mono=False)
                    elif panel._detail.get("exif_expanded"):
                        self._append_grid_blocks(
                            blocks, exif_common + exif_more, content_width, mono=False
                        )
                    else:
                        self._append_grid_blocks(blocks, exif_common, content_width, mono=False)
                        if exif_more:
                            blocks.append({
                                "kind": "link",
                                "text": f"展开全部 {len(exif_more)} 条标签",
                                "action": "expand_exif",
                            })
                elif status == "done" and not detail_rows:
                    blocks.append({
                        "kind": "note", "text": "该文件没有可提取的详细信息",
                    })

        # ── 哈希折叠区块 ───────────────────────────────────────────
        if panel._expanded == "hashes":
            self._append_section_blocks(blocks, "哈希值")
            status = panel._hash.get("status", "idle")
            if status == "loading":
                blocks.append({
                    "kind": "busy",
                    "text": f"正在计算哈希值 {panel._hash.get('percent', 0)}%",
                    "progress": panel._hash.get("percent", 0),
                })
            else:
                values = panel._hash.get("values") or {}
                hash_rows = [
                    (label, values.get(label, fis.UNAVAILABLE))
                    for label in FileInfoPanel._HASH_LABELS
                ]
                self._append_grid_blocks(blocks, hash_rows, content_width, mono=True)
        return blocks

    def _append_section_blocks(self, blocks: List[dict], title: str) -> None:
        blocks.append({"kind": "gap", "height": int(10 * 1.0)})
        blocks.append({"kind": "heading", "text": title})
        blocks.append({"kind": "gap", "height": int(2 * 1.0)})

    def _append_grid_blocks(
        self,
        blocks: List[dict],
        rows: List[Tuple[str, str]],
        content_width: int,
        mono: bool,
    ) -> None:
        if not rows:
            return
        fm_label = QFontMetrics(self.FONT_LABEL)
        fm_value = QFontMetrics(self.FONT_MONO if mono else self.FONT_VALUE)
        label_col = max(
            (fm_label.horizontalAdvance(str(label)) for label, _ in rows), default=0
        )
        label_col = min(label_col, max(0, content_width - 60))
        value_width = max(60, content_width - label_col - self.LABEL_GAP)

        for label, value in rows:
            value_height = self._measure_block(
                fm_value, str(value), value_width
            )
            blocks.append({
                "kind": "grid",
                "label": str(label),
                "value": str(value),
                "mono": mono,
                "label_col": label_col,
                "value_width": value_width,
                "row_height": max(fm_label.height(), value_height),
            })

    @staticmethod
    def _measure_block(fm: QFontMetrics, text: str, width: int) -> int:
        if not text:
            return fm.height()
        rect = fm.boundingRect(
            0, 0, max(1, width), 0x7FFFFFFF,
            Qt.TextWordWrap | Qt.AlignLeft, text,
        )
        return max(fm.height(), rect.height())

    @staticmethod
    def _wrap_break_anywhere(fm: QFontMetrics, text: str, width: int) -> List[str]:
        """逐字形断行（允许在英文单词中间断行），供文件地址等多行显示。"""
        width = max(int(width), 8)
        lines: List[str] = []
        current = ""
        for ch in text:
            if current and fm.horizontalAdvance(current + ch) > width:
                lines.append(current)
                current = ch
            else:
                current += ch
        if current or not lines:
            lines.append(current)
        return lines

    @classmethod
    def _path_lines(cls, fm: QFontMetrics, text: str, width: int) -> Tuple[List[str], int]:
        """文件地址行：逐字形断行，返回 (各行, 所需高度)。"""
        lines = cls._wrap_break_anywhere(fm, text, width)
        height = max(fm.height(), len(lines) * fm.lineSpacing())
        return lines, height

    # ------------------------------------------------------------------
    # 排版：唯一生成 items（内容 + 几何）
    # ------------------------------------------------------------------

    def _make_item(
        self, kind: str, block: dict, content_width: int, width: int, y: int
    ) -> _CanvasItem:
        """把单个块解析为含最终几何的条目（高度含块后的间距）。

        高度规则与既有视觉完全一致：字段行/标题/路径按文本高度，
        heading/note/busy 追加 4px、busy 进度再占 9px、link 追加行距。
        """
        pad4 = int(4 * 1.0)
        if kind == "grid":
            row_height = int(block["row_height"])
            return _CanvasItem(
                kind="grid",
                rect=QRect(0, y, width, row_height),
                height=row_height + self.LINE_SPACING,
                text_h=row_height,
                label=block["label"],
                value=block["value"],
                mono=bool(block["mono"]),
                label_col=int(block["label_col"]),
                value_x=self.PAD_X + int(block["label_col"]) + self.LABEL_GAP,
                value_width=int(block["value_width"]),
                row_height=row_height,
                highlight=True,
            )
        if kind == "title":
            fm = QFontMetrics(self.FONT_TITLE)
            h = self._measure_block(fm, block["text"], content_width)
            return _CanvasItem(
                kind="title",
                rect=QRect(0, y, width, h),
                height=h,
                text_h=h,
                text=block["text"],
                full_text=str(block.get("full_text") or block["text"]),
                label="文件名",
                value=str(block.get("full_text") or block["text"]),
            )
        if kind == "path":
            fm = QFontMetrics(self.FONT_PATH)
            lines, h = self._path_lines(fm, block["text"], content_width)
            return _CanvasItem(
                kind="path",
                rect=QRect(0, y, width, h),
                height=h,
                text_h=h,
                text=block["text"],
                full_text=str(block.get("full_text") or block["text"]),
                label="文件路径",
                value=str(block.get("full_text") or block["text"]),
                lines=lines,
            )
        if kind == "heading":
            fm = QFontMetrics(self.FONT_HEADING)
            h = self._measure_block(fm, block["text"], content_width)
            return _CanvasItem(
                kind="heading",
                rect=QRect(0, y, width, h + pad4),
                height=h + pad4,
                text_h=h,
                text=block["text"],
            )
        if kind == "note":
            fm = QFontMetrics(self.FONT_VALUE)
            h = self._measure_block(fm, block["text"], content_width)
            return _CanvasItem(
                kind="note",
                rect=QRect(0, y, width, h + pad4),
                height=h + pad4,
                text_h=h,
                text=block["text"],
            )
        if kind == "busy":
            fm = QFontMetrics(self.FONT_VALUE)
            text = block.get("text", "")
            h = self._measure_block(fm, text, content_width)
            extra = pad4
            track_top = 0
            if "progress" in block:
                track_top = y + h + pad4
                extra += 3 + 6
            return _CanvasItem(
                kind="busy",
                rect=QRect(0, y, width, h + extra),
                height=h + extra,
                text_h=h,
                text=text,
                progress=block.get("progress"),
                track_top=track_top,
            )
        if kind == "link":
            fm = QFontMetrics(self.FONT_LINK)
            h = self._measure_block(fm, block["text"], content_width)
            return _CanvasItem(
                kind="link",
                rect=QRect(0, y, width, h + self.LINE_SPACING),
                height=h + self.LINE_SPACING,
                text_h=h,
                text=block["text"],
                action=str(block.get("action") or ""),
            )
        raise AssertionError(f"未知块类型: {kind}")

    def _build_items(self, content_width: int, width: int) -> Tuple[List[_CanvasItem], int]:
        """按 _blocks() 顺序一次性生成全部条目，返回 (items, 总高)。"""
        items: List[_CanvasItem] = []
        y = self.PAD_TOP
        pending_gap = 0
        for block in self._blocks(content_width):
            kind = block["kind"]
            if kind == "gap":
                pending_gap += int(block.get("height", 0))
                continue
            if pending_gap:
                y += pending_gap
                pending_gap = 0
            item = self._make_item(kind, block, content_width, width, y)
            items.append(item)
            y += item.height
        return items, y

    def _relayout(self, width: int) -> None:
        if self._relayouting:
            return
        self._relayouting = True
        try:
            panel = self._panel
            if width <= 0:
                width = 640
            content_width = max(60, width - 2 * self.PAD_X)

            self._items = []
            self._hover_row = None
            self._hover_link_action = None
            if panel._file_info is None:
                # 空状态：画布高度跟随可视区，文案在 paintEvent 中垂直居中
                viewport = panel._scroll_area.viewport()
                viewport_h = viewport.height() if viewport is not None else 240
                target = max(80, viewport_h)
                if self.height() != target:
                    self.setFixedHeight(target)
                return

            items, end_y = self._build_items(content_width, width)
            self._items = items
            total = max(0, int(end_y)) + self.PAD_BOTTOM
            if self.height() != total:
                self.setFixedHeight(total)
        finally:
            self._relayouting = False

    # ------------------------------------------------------------------
    # 一致性自检（结构性保证：供测试/调试调用）
    # ------------------------------------------------------------------

    def _verify_items(self) -> bool:
        """校验 items 几何不重叠且单调递增（排版只经 _build_items 一条路径）。

        相邻文本区不得重叠：下一项 top 必须 >= 上一项 top + 上一项 text_h；
        全部条目 top 单调递增、rect 尺寸有效。失败时在 _geom_last_fail 记录
        (index, 上一项top+text_h, 实际top) 供诊断。
        """
        self._geom_last_fail: Optional[tuple] = None
        prev_top = self.PAD_TOP
        prev_bottom = 0
        for index, item in enumerate(self._items):
            if item.rect.top() < prev_top or item.rect.top() < prev_bottom:
                self._geom_last_fail = (index, prev_bottom, item.rect.top())
                return False
            if item.rect.width() <= 0 or item.height <= 0 or item.text_h <= 0:
                self._geom_last_fail = (index, "rect", (item.rect.width(), item.height, item.text_h))
                return False
            if item.kind == "grid" and not (item.label and item.value is not None):
                self._geom_last_fail = (index, "content", item.label)
                return False
            prev_top = item.rect.top()
            prev_bottom = item.rect.top() + item.text_h
        return True


    # ------------------------------------------------------------------
    # 绘制（只消费 _items，不再自行计算块/坐标）
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setRenderHint(QPainter.Antialiasing)

        panel = self._panel
        if panel._file_info is None:
            hint_font = QFont("Microsoft YaHei UI")
            hint_font.setPixelSize(14)
            painter.setFont(hint_font)
            painter.setPen(tm.mid)
            painter.drawText(self.rect(), Qt.AlignCenter, "选择文件以预览详细信息")
            painter.end()
            return

        for item in self._items:
            kind = item.kind
            top = item.rect.top()
            if kind == "title":
                painter.setFont(self.FONT_TITLE)
                painter.setPen(tm.text)
                painter.drawText(
                    QRect(self.PAD_X, top, item.rect.width() - 2 * self.PAD_X, item.text_h),
                    Qt.AlignLeft | Qt.AlignTop, item.text,
                )
                continue

            if kind == "path":
                painter.setFont(self.FONT_PATH)
                painter.setPen(tm.alpha_of(tm.mid, 60))
                line_y = top
                for line in item.lines:
                    painter.drawText(
                        QRect(self.PAD_X, line_y, item.rect.width() - 2 * self.PAD_X, QFontMetrics(self.FONT_PATH).height()),
                        Qt.AlignLeft | Qt.AlignTop, line,
                    )
                    line_y += QFontMetrics(self.FONT_PATH).lineSpacing()
                continue

            if kind == "heading":
                painter.setFont(self.FONT_HEADING)
                painter.setPen(tm.accent)
                painter.drawText(
                    QRect(self.PAD_X, top, item.rect.width() - 2 * self.PAD_X, item.text_h),
                    Qt.AlignLeft | Qt.AlignTop, item.text,
                )
                continue

            if kind == "note":
                painter.setFont(self.FONT_VALUE)
                painter.setPen(tm.alpha_of(tm.mid, 55))
                painter.drawText(
                    QRect(self.PAD_X, top, item.rect.width() - 2 * self.PAD_X, item.text_h),
                    Qt.AlignLeft | Qt.AlignTop, item.text,
                )
                continue

            if kind == "busy":
                painter.setFont(self.FONT_VALUE)
                painter.setPen(tm.alpha_of(tm.mid, 70))
                text = item.text
                if item.progress is None:
                    text = f"{text}{'.' * self._dot_frame}"
                fm = QFontMetrics(self.FONT_VALUE)
                painter.drawText(
                    QRect(self.PAD_X, top, item.rect.width() - 2 * self.PAD_X, item.text_h),
                    Qt.AlignLeft | Qt.AlignTop, text,
                )
                if item.progress is not None and item.track_top > 0:
                    percent = max(0, min(100, int(item.progress)))
                    track = QRect(self.PAD_X, item.track_top,
                                  item.rect.width() - 2 * self.PAD_X, 3)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(tm.alpha_of(tm.mid, 20))
                    painter.drawRoundedRect(track, 1, 1)
                    fill_w = int(track.width() * percent / 100)
                    if fill_w > 0:
                        painter.setBrush(tm.accent)
                        painter.drawRoundedRect(
                            QRect(track.x(), track.y(), fill_w, track.height()), 1, 1,
                        )
                continue

            if kind == "link":
                hovered = self._hover_link_action == item.action
                painter.setFont(self.FONT_LINK)
                painter.setPen(
                    tm.alpha_of(tm.mid, 100) if hovered else tm.alpha_of(tm.mid, 70)
                )
                fm = QFontMetrics(self.FONT_LINK)
                text_width = fm.horizontalAdvance(item.text)
                if hovered and text_width > 0:
                    painter.drawLine(
                        self.PAD_X, top + item.text_h - 1,
                        self.PAD_X + text_width, top + item.text_h - 1,
                    )
                painter.drawText(
                    QRect(self.PAD_X, top, item.rect.width() - 2 * self.PAD_X, item.text_h),
                    Qt.AlignLeft | Qt.AlignTop, item.text,
                )
                continue

            if kind == "grid":
                if item is self._hover_row and item.highlight:
                    painter.fillRect(item.rect, tm.alpha_of(tm.mid, 9))
                painter.setFont(self.FONT_LABEL)
                painter.setPen(tm.alpha_of(tm.mid, 65))
                painter.drawText(
                    QRect(self.PAD_X, top, item.label_col, item.row_height),
                    Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, item.label,
                )
                painter.setFont(self.FONT_MONO if item.mono else self.FONT_VALUE)
                painter.setPen(tm.text)
                painter.drawText(
                    QRect(item.value_x, top, item.value_width, item.row_height),
                    Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, item.value,
                )
                continue

        painter.end()

    def _advance_dots(self) -> None:
        self._dot_frame = (self._dot_frame + 1) % 4
        self.update()

    def _sync_dot_timer(self) -> None:
        panel = self._panel
        need_dots = (
            panel._file_info is not None
            and (
                (panel._expanded == "details" and panel._detail.get("status") == "loading")
                or (panel._expanded == "hashes" and panel._hash.get("status") == "loading")
            )
        )
        if need_dots:
            if not self._dot_timer.isActive():
                self._dot_timer.start()
        else:
            self._dot_timer.stop()

    # ------------------------------------------------------------------
    # 交互（全部以 _items 的 rect 为唯一命中依据）
    # ------------------------------------------------------------------

    def _row_at(self, pos: QPoint) -> Optional[_CanvasItem]:
        for item in reversed(self._items):
            if item.is_field and item.rect.contains(pos):
                return item
        return None

    def _link_action_at(self, pos: QPoint) -> Optional[str]:
        for item in reversed(self._items):
            if item.kind == "link" and item.rect.contains(pos):
                return item.action
        return None

    def _invalidate_items(self, items) -> None:
        """按画布条目矩形局部失效（A4 局部重绘纪律）。

        脏区取各条目 ``rect`` 的并集（已是画布坐标系）；条目为空/矩形无效时
        回退整画布 ``update()``，绝不漏重绘。

        Args:
            items: ``_CanvasItem`` 可迭代对象（允许 None 元素）。
        """
        dirty = QRect()
        try:
            for item in items:
                if item is None:
                    continue
                rect = item.rect
                if rect is not None and rect.isValid() and not rect.isEmpty():
                    dirty = rect if dirty.isNull() else dirty.united(rect)
        except Exception:
            dirty = QRect()
        try:
            if dirty.isNull():
                self.update()
            else:
                self.update(dirty.adjusted(0, -1, 0, 1).intersected(self.rect()))
        except Exception:
            pass

    def _link_items(self, action: Optional[str]) -> list:
        """取指定 link action 对应的画布条目（A4 脏区用）。

        Args:
            action: link 动作名；None 返回空列表。

        Returns:
            匹配条目列表。
        """
        if action is None:
            return []
        return [item for item in self._items if item.kind == "link" and item.action == action]

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint()
        row = self._row_at(pos)
        link_action = self._link_action_at(pos)
        if row is not self._hover_row:
            # A4：hover 高亮只影响新旧两行，按行矩形失效。
            old_row = self._hover_row
            self._hover_row = row
            self._invalidate_items((old_row, row))
        if link_action != self._hover_link_action:
            # A4：link 悬停变色只影响新旧两个链接条目。
            old_action = self._hover_link_action
            self._hover_link_action = link_action
            self._invalidate_items(
                self._link_items(old_action) + self._link_items(link_action)
            )
        self.setCursor(
            Qt.PointingHandCursor
            if (row is not None or link_action is not None)
            else Qt.ArrowCursor
        )
        if row is not None:
            self.setToolTip(f"{row.label}: {row.value}"[:800])
        else:
            self.setToolTip("")
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        # A4：离开时只失效残留 hover 行/链接条目。
        old_row = self._hover_row
        old_action = self._hover_link_action
        self._hover_row = None
        self._hover_link_action = None
        self.setToolTip("")
        self.setCursor(Qt.ArrowCursor)
        self._invalidate_items((old_row,) + tuple(self._link_items(old_action)))
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            action = self._link_action_at(event.position().toPoint())
            if action == "expand_exif":
                self._panel._expand_all_exif()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            row = self._row_at(pos)
            if row is not None and row.rect.contains(pos):
                if event.modifiers() & Qt.ControlModifier and row.label == "文件路径":
                    # Ctrl+左键点击文件路径：在资源管理器中打开并选中该文件（不复制）
                    self._panel._open_in_explorer(row.value)
                    event.accept()
                    return
                QApplication.clipboard().setText(row.value)
                self._panel._show_copy_toast()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        row = self._row_at(pos)
        menu = StyledContextMenu(parent=self)
        if row is not None:
            value = row.value

            def _copy_field() -> None:
                QApplication.clipboard().setText(value)
                self._panel._show_copy_toast()

            def _copy_path() -> None:
                QApplication.clipboard().setText(str(self._panel._summary.get("path", "")))
                self._panel._show_copy_toast()

            menu.add_item("复制该字段", callback=_copy_field)
            if row.label != "文件路径":
                menu.add_separator()
                menu.add_item("复制文件路径", callback=_copy_path)
        menu.add_separator()
        menu.add_item("复制全部信息", callback=self._panel._copy_all)
        menu.exec(event.globalPosition().toPoint())
        event.accept()

    def resizeEvent(self, event) -> None:  # noqa: N802
        """尺寸变化合并节流：拖拽期只存宽重启 32ms 定时，静止后重排。

        P0：每帧 ``_relayout`` 会全量 ``_build_items`` + ``setFixedHeight``
        触发父布局二次测量，拖拽中必须合并；小抖动（<4px）且定时器
        运行中直接合并，不重排。
        """
        super().resizeEvent(event)
        width = self.width()
        # 首帧立即排版，避免初始空闪；后续拖拽合并到 32ms 后一次。
        if self._last_width == 0 and not self._items and width > 0:
            self._pending_width = width
            self._last_width = width
            if not self._relayouting:
                self._relayout(width)
            self.update()
            return
        # 拖拽高频期：仅记录目标宽度并重启合并定时，不做全量排版。
        self._pending_width = width
        self._relayout_debounce.start()

    def _on_relayout_timeout(self) -> None:
        """合并窗口到期：执行一次全量重排并重绘。"""
        width = self._pending_width or self.width()
        self._last_width = width
        if not self._relayouting:
            self._relayout(width)
        self.update()



# ---------------------------------------------------------------------------
# 文件信息面板（固定外壳：滚动区 + 画布 + 底部折叠入口）
# ---------------------------------------------------------------------------

class FileInfoPanel(QWidget):
    """文件信息预览面板（新界面底部信息区，自绘文本流）。"""

    details_loaded = Signal()
    hashes_loaded = Signal()

    _HASH_LABELS = ("MD5", "SHA1", "SHA256")
    _TOAST_INTERVAL_MS = 3000  # 「已复制」提示停留时长（连续复制时重置计时）

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        cache_path: Optional[str] = None,
    ):
        super().__init__(parent)
        self._cache_path = cache_path
        self._file_token = 0
        self._tasks: List[_WorkTask] = []

        self._file_info: Optional[dict] = None
        self._summary: Dict[str, Any] = {"name": "", "path": ""}
        self._rows: List[Tuple[str, str]] = []
        self._detail_supported = False

        self._detail: Dict[str, Any] = {
            "status": "idle",  # idle / loading / done
            "rows": [], "exif_common": [], "exif_more": [],
            "exif_expanded": False,
        }
        self._hash: Dict[str, Any] = {"status": "idle", "values": {}, "percent": 0}
        self._expanded: Optional[str] = None  # 'details' / 'hashes' / None

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._build_skeleton()
        tm.theme_changed.connect(self._on_theme_changed)
        self._sync_canvas()

    # ------------------------------------------------------------------
    # UI 骨架（固定外壳；内容全部由画布自绘）
    # ------------------------------------------------------------------

    def _build_skeleton(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self._scroll_area = StyledScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.NoFrame)
        register_widget_qss(self._scroll_area,(
            "QScrollArea { background: transparent; border: none; }"
        ))
        self._scroll_area.viewport().setAutoFillBackground(False)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 原生垂直条仅作为滚动模型/平滑滚动通道；视觉交给悬浮条
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._native_vbar = self._scroll_area.verticalScrollBar()
        root.addWidget(self._scroll_area, stretch=1)

        self._canvas = _InfoCanvas(self)
        self._scroll_area.setWidget(self._canvas)

        # 悬浮滚动条（视觉条，内缩顶部留白的一半，不占布局）
        self._float_bar = StyledScrollBar(self._scroll_area)
        self._float_bar.setFixedWidth(6)
        self._float_bar.setRange(0, 0)
        self._float_bar.hide()
        self._float_bar.raise_()

        self._native_vbar.rangeChanged.connect(self._on_native_range_changed)
        self._native_vbar.valueChanged.connect(self._on_native_value_changed)
        self._float_bar.valueChanged.connect(self._on_float_value_changed)
        self._scroll_area.installEventFilter(self)

        # 底部折叠入口行
        self._fold_bar = QWidget()
        self._fold_bar.setAttribute(Qt.WA_StyledBackground, False)
        fold_layout = QHBoxLayout(self._fold_bar)
        fold_layout.setContentsMargins(16, 0, 16, 0)
        fold_layout.setSpacing(18)

        self._detail_link = _FoldLink("详细信息", self._fold_bar)
        self._hash_link = _FoldLink("哈希值", self._fold_bar)
        self._detail_link.clicked.connect(self._toggle_details)
        self._hash_link.clicked.connect(self._toggle_hashes)
        # 「详细信息」在左、「哈希值」固定在最右
        fold_layout.addWidget(self._detail_link)
        fold_layout.addStretch(1)
        fold_layout.addWidget(self._hash_link)
        root.addWidget(self._fold_bar)

        # 「已复制」提示：居中叠在折叠入口行上方
        self._toast_label = QLabel("", self._fold_bar)
        self._toast_label.hide()
        self._toast_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.setInterval(self._TOAST_INTERVAL_MS)
        self._toast_timer.timeout.connect(self._hide_copy_toast)
        self._apply_toast_style()

        self._fold_bar.hide()

    # ------------------------------------------------------------------
    # 公共生命周期
    # ------------------------------------------------------------------

    def current_path(self) -> Optional[str]:
        """当前文件路径；无预览时返回 None。"""
        if self._file_info is None:
            return None
        return str(self._summary.get("path") or "") or None

    def is_loading(self) -> bool:
        """是否有正在进行的后台采集（详细信息 / 哈希值）。"""
        return bool(
            (self._expanded == "details" and self._detail.get("status") == "loading")
            or (self._expanded == "hashes" and self._hash.get("status") == "loading")
        )

    def set_file(self, file_info: Optional[dict]) -> None:
        """切换预览文件；None 表示清空。"""
        self.stop()
        self._file_token += 1
        self._file_info = dict(file_info) if file_info else None
        self._summary = {"name": "", "path": ""}
        self._rows = []
        self._detail_supported = False
        self._detail = {
            "status": "idle", "rows": [], "exif_common": [], "exif_more": [],
            "exif_expanded": False,
        }
        self._hash = {"status": "idle", "values": {}, "percent": 0}
        self._expanded = None

        if file_info:
            path = str(file_info.get("path") or "")
            self._summary = {
                "name": str(file_info.get("name") or ""),
                "path": path,
            }
            self._rows = fis.collect_light_rows(file_info)
            self._detail_supported = self._rule_detail_supported(file_info)
        self._sync_canvas()

    def clear(self) -> None:
        """清空预览（与 set_file(None) 等价）。"""
        self.set_file(None)

    def stop(self) -> None:
        """取消全部后台任务（面板销毁/切换文件时调用；过期结果由令牌守卫丢弃）。"""
        for task in list(self._tasks):
            try:
                task.request_cancel()
            except RuntimeError:
                pass
        self._tasks.clear()

    @staticmethod
    def _rule_detail_supported(file_info: dict) -> bool:
        """按类型判定是否提供「详细信息」折叠（PDF/文件夹/未知等无详情）。"""
        if file_info.get("is_dir"):
            return False
        path = str(file_info.get("path") or "")
        if not os.path.isfile(path):
            return False
        suffix = str(file_info.get("suffix", "")).lstrip(".").lower()
        if suffix in fis._SVG_EXTS or suffix in fis._PDF_EXTS:
            return False
        if fis.is_image_suffix(suffix) or fis.is_audio_suffix(suffix) \
                or fis.is_video_suffix(suffix) or fis.is_text_suffix(suffix) \
                or fis.is_archive_suffix(suffix) or fis.is_font_suffix(suffix):
            return True
        return False

    # ------------------------------------------------------------------
    # 折叠控制
    # ------------------------------------------------------------------

    def _toggle_details(self) -> None:
        if not self._detail_supported or self._file_info is None:
            return
        if self._expanded == "details":
            self._expanded = None
        else:
            self._expanded = "details"
            if self._detail["status"] == "idle":
                self._detail["status"] = "loading"
                self._start_details_thread()
        self._sync_canvas()
        if self._expanded == "details":
            self._scroll_to_bottom()

    def _toggle_hashes(self) -> None:
        if self._file_info is None:
            return
        if self._expanded == "hashes":
            self._expanded = None
        else:
            self._expanded = "hashes"
            if self._hash["status"] == "idle":
                self._hash["status"] = "loading"
                self._start_hash_thread()
        self._sync_canvas()
        if self._expanded == "hashes":
            self._scroll_to_bottom()

    def _expand_all_exif(self) -> None:
        self._detail["exif_expanded"] = True
        self._sync_canvas()
        self._scroll_to_bottom()

    def _start_details_thread(self) -> None:
        token = self._file_token
        task = _DetailTask(self.current_path() or "", self._cache_path)
        task.done.connect(lambda data, t=token: self._on_details_done(t, data))
        self._track_task(task)

    def _start_hash_thread(self) -> None:
        token = self._file_token
        task = _HashTask(self.current_path() or "", self._cache_path)
        task.progress.connect(lambda percent, t=token: self._on_hash_progress(t, percent))
        task.done.connect(lambda values, t=token: self._on_hash_done(t, values))
        self._track_task(task)

    def _track_task(self, task: _WorkTask) -> None:
        task.done.connect(lambda _data, tk=task: self._untrack_task(tk))
        self._tasks.append(task)
        task.start()

    def _untrack_task(self, task: _WorkTask) -> None:
        try:
            if task in self._tasks:
                self._tasks.remove(task)
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # 后台结果回调（令牌守卫，防止旧结果覆盖新文件）
    # ------------------------------------------------------------------

    def _on_details_done(self, token: int, data: Any) -> None:
        if token != self._file_token:
            return
        self._detail.update({
            "status": "done",
            "rows": list(data.get("rows") or []),
            "exif_common": list(data.get("exif_common") or []),
            "exif_more": list(data.get("exif_more") or []),
            "exif_expanded": False,
        })
        self.details_loaded.emit()
        self._sync_canvas()
        if self._expanded == "details":
            self._scroll_to_bottom()

    def _on_hash_progress(self, token: int, percent: int) -> None:
        if token != self._file_token:
            return
        self._canvas.set_hash_progress(percent)

    def _on_hash_done(self, token: int, values: Any) -> None:
        if token != self._file_token:
            return
        self._hash["status"] = "done"
        self._hash["values"] = dict(values or {})
        self.hashes_loaded.emit()
        self._sync_canvas()
        if self._expanded == "hashes":
            self._scroll_to_bottom()

    # ------------------------------------------------------------------
    # 画布同步 / 底栏 / 复制提示 / 滚动 / 主题
    # ------------------------------------------------------------------

    def _sync_canvas(self) -> None:
        if self._file_info is None:
            self._fold_bar.hide()
        else:
            self._fold_bar.show()
            self._update_fold_bar()
        self._canvas.refresh()

    def _update_fold_bar(self) -> None:
        self._detail_link.setVisible(self._detail_supported)
        if self._detail_supported:
            arrow = "\u25be" if self._expanded == "details" else "\u25b8"
            text = "详细信息"
            if self._detail["status"] == "done":
                count = (len(self._detail["rows"]) + len(self._detail["exif_common"])
                         + len(self._detail["exif_more"]))
                if count:
                    text = f"详细信息 \u00b7 {count}"
            self._detail_link.set_text(f"{arrow} {text}")

        arrow = "\u25be" if self._expanded == "hashes" else "\u25b8"
        hash_text = "哈希值"
        if self._hash["status"] == "done":
            hash_text = "哈希值 \u00b7 \u5df2\u8ba1\u7b97"
        self._hash_link.set_text(f"{arrow} {hash_text}")

    def _apply_toast_style(self) -> None:
        color = _rgba(tm.alpha_of(tm.mid, 80))
        self._toast_label.setStyleSheet(
            f"color: {color}; font-size: 12px; background: transparent;"
        )

    def _show_copy_toast(self) -> None:
        if not hasattr(self, "_toast_label"):
            return
        self._toast_label.setText("\u5df2\u590d\u5236")
        self._toast_timer.stop()
        self._toast_timer.start()
        self._toast_label.show()
        self._toast_label.raise_()
        self._position_toast()
        QTimer.singleShot(0, self._position_toast)

    def _hide_copy_toast(self) -> None:
        self._toast_label.hide()

    def _position_toast(self) -> None:
        if not self._toast_label.isVisible():
            return
        self._toast_label.adjustSize()
        bar_width = self._fold_bar.width()
        x = max(0, (bar_width - self._toast_label.width()) // 2)
        y = max(0, (self._fold_bar.height() - self._toast_label.height()) // 2)
        self._toast_label.move(x, y)

    # ------------------------------------------------------------------
    # 悬浮滚动条
    # ------------------------------------------------------------------

    def _on_native_range_changed(self, minimum: int, maximum: int) -> None:
        self._float_bar.setRange(minimum, maximum)
        self._float_bar.setPageStep(self._native_vbar.pageStep())
        self._float_bar.setSingleStep(1)
        self._float_bar.setValue(self._native_vbar.value())
        self._float_bar.setVisible(maximum > minimum)
        self._position_float_bar()

    def _on_native_value_changed(self, value: int) -> None:
        self._float_bar.setValue(value)

    def _on_float_value_changed(self, value: int) -> None:
        self._native_vbar.setValue(value)

    def _position_float_bar(self) -> None:
        viewport = self._scroll_area.viewport()
        if viewport is None:
            return
        inset = max(int(self._canvas.PAD_TOP * 1.0 / 2), 2)
        x = viewport.width() - self._float_bar.width()
        self._float_bar.setGeometry(
            x, inset, self._float_bar.width(), max(0, viewport.height() - inset)
        )
        self._float_bar.raise_()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._scroll_area and event.type() == QEvent.Resize:
            self._position_float_bar()
        return super().eventFilter(obj, event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._position_float_bar)

    # ------------------------------------------------------------------
    # Ctrl+左键点击文件路径 → 在资源管理器中打开并选中
    # ------------------------------------------------------------------

    @staticmethod
    def _open_in_explorer(path: str) -> None:
        target = os.path.abspath(path)
        if not os.path.exists(target):
            return
        try:
            if sys.platform == "win32":
                import subprocess
                subprocess.Popen(
                    ["explorer", "/select,", os.path.normpath(target)],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                directory = os.path.dirname(target)
                if sys.platform == "darwin":
                    os.system(f'open "{directory}"')  # noqa: S605
                else:
                    os.system(f'xdg-open "{directory}"')  # noqa: S605
        except Exception as exc:  # noqa: BLE001
            from freeassetfilter.utils.app_logger import error
            error(f"[FileInfoPanel] 在资源管理器中打开失败: {exc}")

    # ------------------------------------------------------------------
    # 复制全部 / 主题
    # ------------------------------------------------------------------

    def _copy_all(self) -> None:
        lines = ["文件信息", "=" * 20]
        lines.append(f"文件名: {self._summary['name']}")
        lines.append(f"文件路径: {self._summary['path']}")
        for label, value in self._rows:
            lines.append(f"{label}: {value}")
        if self._detail["status"] == "done":
            for label, value in self._detail["rows"]:
                lines.append(f"{label}: {value}")
            for label, value in (self._detail["exif_common"] + self._detail["exif_more"]):
                lines.append(f"{label}: {value}")
        if self._hash["status"] == "done":
            for label in self._HASH_LABELS:
                lines.append(f"{label}: {self._hash['values'].get(label, fis.UNAVAILABLE)}")
        QApplication.clipboard().setText("\n".join(lines))

    def _scroll_to_bottom(self) -> None:
        def _do_scroll() -> None:
            try:
                bar = self._scroll_area.verticalScrollBar()
                bar.setValue(bar.maximum())
            except RuntimeError:
                pass

        QTimer.singleShot(0, _do_scroll)

    def _on_theme_changed(self, _theme: str) -> None:
        if hasattr(self, "_toast_label"):
            self._apply_toast_style()
            self._position_toast()
        self._sync_canvas()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        QTimer.singleShot(0, self._position_float_bar)
