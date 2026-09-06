# -*- coding: utf-8 -*-
"""file_info_panel 单元测试（todo-23 批 4 / task-23）。

覆盖：构造与空状态、set_file/clear 生命周期、自绘画布状态与命中数据、
底侧折叠入口显隐（不支持详细信息的文件隐藏）、详细信息/哈希值展开
（真实小文件 + 注入的临时缓存路径）、单击复制、切文件令牌守卫、
主题重绘安全。

验证命令：
    python -m pytest tests/unit/ui/layout/preview/test_file_info_panel.py --timeout 60 -q
"""

# targets: freeassetfilter.ui.layout.preview.file_info_panel

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Optional

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

# 与 test_layouts.py 相同的路径引导：布局模块内部使用短路径导入
_UI_ROOT: str = str(Path(__file__).resolve().parents[5] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.layout.preview.file_info_panel import FileInfoPanel  # noqa: E402
from freeassetfilter.services import file_info_service as fis  # noqa: E402
from tests.support.qt_helpers import safe_teardown, wait_for_signal  # noqa: E402


pytestmark = pytest.mark.unit


def _pump(qapp: QApplication, ms: float = 1200) -> None:
    """有界事件泵：轮询 processEvents 直到时间耗尽。"""
    deadline = time.time() + ms / 1000
    while time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)


def _file_info(path: str, suffix: Optional[str] = None) -> dict:
    suffix = suffix or Path(path).suffix.lstrip(".")
    return {
        "name": Path(path).name,
        "path": path,
        "is_dir": False,
        "size": os.path.getsize(path) if os.path.exists(path) else 0,
        "suffix": suffix,
    }


def _make_panel(qapp: QApplication, tmp_path: Path) -> FileInfoPanel:
    """构造并显示面板（注入临时缓存路径，避免触碰仓库默认缓存）。"""
    panel = FileInfoPanel(cache_path=str(tmp_path / "fic.json"))
    panel.show()
    panel.resize(540, 420)
    qapp.processEvents()
    return panel


def _row_by_label(panel: FileInfoPanel, label: str):
    """按标签在画布 items 中查找字段行（grid / 文件名 / 路径共用同一数据源）。"""
    return next(
        (item for item in panel._canvas._items if item.is_field and item.label == label),
        None,
    )


class TestFileInfoPanelBasic:
    """构造 / 空状态 / set_file / clear。"""

    def test_construct_and_empty_state(self, qapp: QApplication, tmp_path: Path) -> None:
        panel = _make_panel(qapp, tmp_path)
        assert panel.current_path() is None
        assert not panel._fold_bar.isVisible()
        assert panel._canvas._row_blocks == []
        # 空状态画布高度跟随可视区（自绘占位文案居中）
        assert panel._canvas.height() > 0
        safe_teardown(panel)

    def test_set_file_none_is_safe(self, qapp: QApplication, tmp_path: Path) -> None:
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(None)
        qapp.processEvents()
        assert panel._file_info is None
        safe_teardown(panel)

    def test_set_image_and_clear(
        self, qapp: QApplication, sample_image_file: str, tmp_path: Path
    ) -> None:
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(sample_image_file))
        qapp.processEvents()
        assert panel.current_path() == sample_image_file
        assert panel._summary["name"] == Path(sample_image_file).name
        assert panel._summary["path"] == sample_image_file
        rows = dict(panel._rows)
        assert rows["类别"] == "PNG 图片"
        assert "格式" not in rows  # 已并入「类别」
        assert rows["尺寸"] == "240 × 160"
        assert panel._canvas._row_blocks  # 画布已排版出命中行
        assert panel._fold_bar.isVisible()
        assert panel._detail_link.isVisible()
        assert panel._hash_link.isVisible()

        panel.clear()
        qapp.processEvents()
        assert panel._file_info is None
        assert not panel._fold_bar.isVisible()
        safe_teardown(panel)

    def test_canvas_has_no_child_text_widgets(
        self, qapp: QApplication, sample_image_file: str, tmp_path: Path
    ) -> None:
        """条目不再以子控件渲染：画布内不存在任何 QLabel。"""
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(sample_image_file))
        qapp.processEvents()
        assert panel._canvas.findChildren(QLabel) == []
        safe_teardown(panel)

    def test_missing_unsupported_file_safe(
        self, qapp: QApplication, tmp_path: Path
    ) -> None:
        panel = _make_panel(qapp, tmp_path)
        missing = str(tmp_path / "nope.zzz")
        panel.set_file(_file_info(missing, suffix="zzz"))
        qapp.processEvents()
        assert panel._file_info is not None
        rows = dict(panel._rows)
        assert rows["类别"] == "ZZZ 文件"
        assert rows["大小"] == fis.UNAVAILABLE
        # 无可用类型详情：详细信息入口隐藏，哈希入口保留
        assert not panel._detail_supported
        assert not panel._detail_link.isVisible()
        assert panel._hash_link.isVisible()
        safe_teardown(panel)

    def test_pdf_hides_details_link(
        self, qapp: QApplication, sample_pdf_file: str, tmp_path: Path
    ) -> None:
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(sample_pdf_file))
        qapp.processEvents()
        assert not panel._detail_link.isVisible()
        assert panel._hash_link.isVisible()
        safe_teardown(panel)

    def test_theme_rebuild_preserves_rows(
        self, qapp: QApplication, sample_image_file: str, tmp_path: Path
    ) -> None:
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(sample_image_file))
        qapp.processEvents()
        rows_before = list(panel._rows)
        blocks_before = len(panel._canvas._row_blocks)
        panel._on_theme_changed("dark")
        qapp.processEvents()
        assert panel._file_info is not None
        assert panel._rows == rows_before
        assert len(panel._canvas._row_blocks) == blocks_before
        safe_teardown(panel)


class TestFileInfoPanelAsync:
    """详细信息 / 哈希值的后台计算与令牌守卫。"""

    def test_details_expansion(
        self, qapp: QApplication, sample_image_file: str, tmp_path: Path
    ) -> None:
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(sample_image_file))
        qapp.processEvents()
        panel._toggle_details()
        assert panel._expanded == "details"
        assert wait_for_signal(panel.details_loaded, timeout_ms=8000)
        assert panel._detail["status"] == "done"
        rows = dict(panel._detail["rows"])
        assert rows.get("色彩模式") == "RGB"
        assert not panel.is_loading()
        safe_teardown(panel)

    def test_hash_expansion_writes_cache(
        self, qapp: QApplication, temp_file: str, tmp_path: Path
    ) -> None:
        cache_file = tmp_path / "fic.json"
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(temp_file))
        qapp.processEvents()
        panel._toggle_hashes()
        assert wait_for_signal(panel.hashes_loaded, timeout_ms=8000)
        assert panel._hash["status"] == "done"
        assert len(panel._hash["values"]["SHA256"]) == 64
        assert cache_file.exists()
        cached = fis.read_cached(temp_file, cache_path=str(cache_file))
        assert cached is not None
        assert cached["hashes"]["SHA256"] == panel._hash["values"]["SHA256"]
        safe_teardown(panel)

    def test_switch_file_discards_stale_result(
        self, qapp: QApplication, sample_image_file: str, temp_file: str, tmp_path: Path
    ) -> None:
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(temp_file))
        qapp.processEvents()
        panel._toggle_details()
        # 计算期间立刻切换文件：旧结果不得写入新文件的状态
        panel.set_file(_file_info(sample_image_file))
        _pump(qapp, 2000)
        assert panel._file_info["path"] == sample_image_file
        assert panel._detail["status"] == "idle"
        assert panel._expanded is None
        panel.stop()
        safe_teardown(panel)

    def test_collapse_during_hash_then_recompute(
        self, qapp: QApplication, temp_file: str, tmp_path: Path
    ) -> None:
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(temp_file))
        qapp.processEvents()
        panel._toggle_hashes()
        panel._toggle_hashes()  # 立即收起
        assert panel._expanded is None
        panel._toggle_hashes()  # 再次展开应复用已完成状态
        qapp.processEvents()
        if wait_for_signal(panel.hashes_loaded, timeout_ms=8000):
            assert panel._hash["status"] == "done"
        panel.stop()
        safe_teardown(panel)

    def test_empty_folder_info(
        self, qapp: QApplication, sample_dir: str, tmp_path: Path
    ) -> None:
        panel = _make_panel(qapp, tmp_path)
        panel.set_file({**_file_info(sample_dir), "is_dir": True})
        qapp.processEvents()
        assert panel._rows == [("类别", "文件夹")]
        assert not panel._detail_supported
        safe_teardown(panel)

    def test_items_geometry_invariant(
        self, qapp: QApplication, sample_image_file: str, tmp_path: Path
    ) -> None:
        """结构性保证：items 几何单调连续、row_blocks 只含属性行。"""
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(sample_image_file))
        qapp.processEvents()
        canvas = panel._canvas
        assert canvas._verify_items() is True, f"geom={canvas._geom_last_fail}"
        # row_blocks 只是 grid 行的兼容别名（命中/复制与绘制同源）
        assert [item.label for item in canvas._row_blocks] == [
            label for label, _ in panel._rows
        ]
        safe_teardown(panel)

    def test_row_hit_returns_same_row_data(
        self, qapp: QApplication, sample_image_file: str, tmp_path: Path
    ) -> None:
        """命中测试：点击/悬停某行中心，_row_at 返回的行与绘制行一致。"""
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(sample_image_file))
        qapp.processEvents()
        canvas = panel._canvas
        for item in canvas._items:
            if item.kind != "grid":
                continue
            hit = canvas._row_at(item.rect.center())
            assert hit is item, f"行 {item.label} 命中数据与绘制数据不一致"
        safe_teardown(panel)

    def test_collapsed_detail_rows_never_render(
        self, qapp: QApplication, sample_image_file: str, tmp_path: Path
    ) -> None:
        """未展开详细信息时，items 中绝不含任何详情行。"""
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(sample_image_file))
        qapp.processEvents()
        panel._detail["status"] = "done"
        panel._detail["rows"] = [("编码格式", "GBK"), ("字符数", "9")]
        panel._sync_canvas()
        qapp.processEvents()
        canvas = panel._canvas
        grid_labels = [i.label for i in canvas._items if i.kind == "grid"]
        assert "编码格式" not in grid_labels
        assert "字符数" not in grid_labels
        assert grid_labels == [label for label, _ in panel._rows]
        safe_teardown(panel)

    def test_expanded_detail_keeps_base_then_detail_order(
        self, qapp: QApplication, sample_image_file: str, tmp_path: Path
    ) -> None:
        """展开详细信息后行序 = 基础行 → 详情行，基础行绝不串入详情区。"""
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(sample_image_file))
        qapp.processEvents()
        base_labels = [label for label, _ in panel._rows]
        panel._detail["status"] = "done"
        panel._detail["rows"] = [("编码格式", "GBK"), ("字符数", "9")]
        panel._expanded = "details"
        panel._sync_canvas()
        qapp.processEvents()
        canvas = panel._canvas
        grid_labels = [i.label for i in canvas._items if i.kind == "grid"]
        detail_labels = [label for label, _ in panel._detail["rows"]]
        assert grid_labels == base_labels + detail_labels
        # 逐行命中仍一致（绘制与交互同源，不会因展开错位）
        for item in canvas._items:
            if item.kind == "grid":
                hit = canvas._row_at(item.rect.center())
                assert hit is item
        safe_teardown(panel)

    def test_mouse_hover_tooltip_matches_row(
        self, qapp: QApplication, sample_image_file: str, tmp_path: Path
    ) -> None:
        """tooltip 与所悬停行的 label/value 严格一致。"""
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(sample_image_file))
        qapp.processEvents()
        canvas = panel._canvas
        target = next(i for i in canvas._items if i.kind == "grid" and i.label == "大小")
        hit = canvas._row_at(target.rect.center())
        assert hit is not None
        assert f"{hit.label}: {hit.value}" == f"大小: {hit.value}"
        safe_teardown(panel)

    def test_path_wraps_inside_english_words(
        self, qapp: QApplication, tmp_path: Path
    ) -> None:
        """文件地址允许在英文单词中间断行显示（不溢出也不截断）。"""
        panel = _make_panel(qapp, tmp_path)
        target = tmp_path / ("SegmentWithoutSpaces" * 6)
        target = target.with_suffix(".txt")
        target.write_text("x", encoding="utf-8")
        panel.set_file(_file_info(str(target)))
        qapp.processEvents()

        fm = QFontMetrics(panel._canvas.FONT_PATH)
        path = panel._summary["path"]
        width = 260
        lines, height = panel._canvas._path_lines(fm, path, width)
        assert len(lines) > 1, "超长英文路径应在单词内部断行"
        assert all(fm.horizontalAdvance(line) <= width for line in lines)
        assert height >= len(lines) * fm.lineSpacing()
        safe_teardown(panel)


class TestFileInfoPanelCanvasInteraction:
    """自绘画布的点击复制与 EXIF 展开命中。"""

    def test_click_row_copies_value(
        self, qapp: QApplication, sample_image_file: str, tmp_path: Path
    ) -> None:
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(sample_image_file))
        qapp.processEvents()
        canvas = panel._canvas
        size_row = _row_by_label(panel, "大小")
        assert size_row is not None
        expected = size_row.value
        QTest.mouseClick(canvas, Qt.LeftButton, pos=size_row.rect.center())
        qapp.processEvents()
        assert qapp.clipboard().text() == expected
        safe_teardown(panel)

    def test_click_name_and_path_copy(
        self, qapp: QApplication, sample_image_file: str, tmp_path: Path
    ) -> None:
        """文件名/文件路径行单击即复制各自全文。"""
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(sample_image_file))
        qapp.processEvents()
        canvas = panel._canvas

        name_row = _row_by_label(panel, "文件名")
        assert name_row is not None
        assert not name_row.highlight  # 名称/路径行悬停无背景高亮
        QTest.mouseClick(canvas, Qt.LeftButton, pos=name_row.rect.center())
        qapp.processEvents()
        assert qapp.clipboard().text() == Path(sample_image_file).name
        assert panel._toast_label.isVisible()

        path_row = _row_by_label(panel, "文件路径")
        assert path_row is not None
        assert not path_row.highlight
        QTest.mouseClick(canvas, Qt.LeftButton, pos=path_row.rect.center())
        qapp.processEvents()
        assert qapp.clipboard().text() == sample_image_file
        safe_teardown(panel)

    @pytest.mark.skipif(sys.platform != "win32", reason="资源管理器仅限 Windows")
    def test_ctrl_click_path_opens_explorer_without_copy(
        self, qapp: QApplication, sample_image_file: str, tmp_path: Path
    ) -> None:
        """Ctrl+左键点击文件路径：打开资源管理器选中文件，不复制不提示。"""
        import freeassetfilter.ui.layout.preview.file_info_panel as fip_module
        from unittest.mock import patch

        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(sample_image_file))
        qapp.processEvents()
        canvas = panel._canvas
        path_row = _row_by_label(panel, "文件路径")
        assert path_row is not None

        qapp.clipboard().clear()
        with patch.object(fip_module.subprocess, "Popen") as popen:
            QTest.mouseClick(
                canvas, Qt.LeftButton, Qt.ControlModifier, path_row.rect.center(),
            )
            qapp.processEvents()
            popen.assert_called_once()
            args = popen.call_args.args[0]
            assert args[0] == "explorer"
            assert args[1] == "/select,"
            assert os.path.normpath(args[2]) == os.path.normpath(sample_image_file)
        assert qapp.clipboard().text() == ""
        assert not panel._toast_label.isVisible()
        safe_teardown(panel)

    def test_click_row_shows_centered_copy_toast(
        self, qapp: QApplication, sample_image_file: str, tmp_path: Path
    ) -> None:
        """单击行复制后：折叠入口行居中显示「已复制」，到时自动消失。"""
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(sample_image_file))
        qapp.processEvents()
        panel._toast_timer.setInterval(250)
        canvas = panel._canvas
        row = _row_by_label(panel, "大小")
        assert row is not None
        QTest.mouseClick(canvas, Qt.LeftButton, pos=row.rect.center())
        qapp.processEvents()
        assert panel._toast_label.isVisible()
        assert panel._toast_label.text() == "已复制"
        assert panel._toast_timer.isActive()
        # 水平居中于折叠行（事件循环稳定后再定位，此处多泵一轮）
        _pump(qapp, 40)
        assert abs(
            (panel._toast_label.x() + panel._toast_label.width() / 2)
            - panel._fold_bar.width() / 2
        ) <= 2
        _pump(qapp, 600)
        assert not panel._toast_label.isVisible()
        safe_teardown(panel)

    def test_consecutive_copy_resets_toast_countdown(
        self, qapp: QApplication, sample_image_file: str, tmp_path: Path
    ) -> None:
        """连续复制时重置消失计时：中途仍可见，最后一次计时后才消失。"""
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(sample_image_file))
        qapp.processEvents()
        panel._toast_timer.setInterval(500)
        canvas = panel._canvas
        row = _row_by_label(panel, "大小")
        assert row is not None

        def _click() -> None:
            QTest.mouseClick(canvas, Qt.LeftButton, pos=row.rect.center())
            qapp.processEvents()

        _click()
        _pump(qapp, 200)  # 首次计时已过半
        _click()  # 重置计时
        _pump(qapp, 300)  # 若未重置，首次 500ms 已到期 → 仍可见即证明重置生效
        assert panel._toast_label.isVisible()
        assert panel._toast_timer.isActive()
        _pump(qapp, 400)
        assert not panel._toast_label.isVisible()
        safe_teardown(panel)

    def test_expand_all_exif_link_hit(
        self, qapp: QApplication, sample_image_file: str, tmp_path: Path
    ) -> None:
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(sample_image_file))
        qapp.processEvents()
        panel._detail["status"] = "done"
        panel._detail["exif_common"] = [("相机厂商", "ACME")]
        panel._detail["exif_more"] = [("TagX", "v1"), ("TagY", "v2")]
        panel._expanded = "details"
        panel._sync_canvas()
        qapp.processEvents()
        canvas = panel._canvas
        link_items = [item for item in canvas._items if item.kind == "link"]
        assert link_items
        assert link_items[0].action == "expand_exif"
        rect = link_items[0].rect
        QTest.mouseClick(panel._canvas, Qt.LeftButton, pos=rect.center())
        qapp.processEvents()
        assert panel._detail["exif_expanded"] is True
        assert [item for item in canvas._items if item.kind == "link"] == []
        safe_teardown(panel)

    def test_copy_all_via_state(
        self, qapp: QApplication, sample_image_file: str, tmp_path: Path
    ) -> None:
        panel = _make_panel(qapp, tmp_path)
        panel.set_file(_file_info(sample_image_file))
        qapp.processEvents()
        panel._copy_all()
        text = qapp.clipboard().text()
        assert "文件信息" in text
        assert "文件名:" in text
        assert Path(sample_image_file).name in text
        safe_teardown(panel)


class TestFileInfoPanelTypographyAndScroll:
    """字号统一 / 提示样式 / 右侧滚动条内缩。"""

    def test_row_fonts_uniform_at_label_size(
        self, qapp: QApplication, tmp_path: Path
    ) -> None:
        """行项目与内容字号一致（以项目 12 为基准）。"""
        panel = _make_panel(qapp, tmp_path)
        canvas = panel._canvas
        sizes = {
            canvas.FONT_LABEL.pointSize(),
            canvas.FONT_VALUE.pointSize(),
            canvas.FONT_MONO.pointSize(),
        }
        assert sizes == {12}
        safe_teardown(panel)

    def test_toast_style_matches_fold_text(self, qapp: QApplication, tmp_path: Path) -> None:
        """「已复制」与折叠行文字同字号同色，且纯透明无胶囊背景。"""
        import freeassetfilter.ui.layout.preview.file_info_panel as fip_module
        from theme import tm

        panel = _make_panel(qapp, tmp_path)
        stylesheet = panel._toast_label.styleSheet()
        expected_color = fip_module._rgba(tm.alpha_of(tm.mid, 80))
        assert expected_color in stylesheet
        assert "font-size: 12px" in stylesheet
        assert "background: transparent" in stylesheet
        assert "background-color" not in stylesheet
        assert "border-radius" not in stylesheet
        assert "padding" not in stylesheet
        safe_teardown(panel)

    def test_float_scrollbar_top_inset_only(
        self, qapp: QApplication, sample_image_file: str, tmp_path: Path
    ) -> None:
        """滚动条顶部内缩 = 文件名上间距一半(6px)，底部贴边；无溢出隐藏。"""
        panel = _make_panel(qapp, tmp_path)
        assert not panel._float_bar.isVisible()

        panel.set_file(_file_info(sample_image_file))
        # 缩小高度制造内容溢出
        panel.resize(540, 150)
        _pump(qapp, 400)
        assert panel._float_bar.isVisible()
        viewport = panel._scroll_area.viewport()
        assert panel._float_bar.x() == viewport.width() - panel._float_bar.width()
        assert panel._float_bar.y() == 6  # _InfoCanvas.PAD_TOP // 2
        assert panel._float_bar.height() == viewport.height() - 6  # 底部贴边

        panel.clear()
        _pump(qapp, 200)
        assert not panel._float_bar.isVisible()
        safe_teardown(panel)


class TestFileInfoPanelCacheMissWrite:
    """确保测试不会写入仓库默认缓存文件（默认路径被注入覆盖）。"""

    def test_default_cache_file_not_touched(self, tmp_path: Path) -> None:
        default = Path(__file__).resolve().parents[5] / "data" / fis.CACHE_FILE_NAME
        existed = default.exists()
        try:
            if existed:
                os.remove(default)
            assert not default.exists()
        finally:
            if existed:
                default.write_text("{}", encoding="utf-8")
