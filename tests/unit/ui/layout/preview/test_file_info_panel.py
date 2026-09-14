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


class TestFileInfoPanelMediaAsync:
    """视频/音频 light 行异步化：ffprobe 不阻塞 UI；陈旧 token 丢弃。"""

    @staticmethod
    def _slow_probe(probe: dict, delay: float):
        """构造一个带确定性延迟的 _media_probe mock。"""

        def _side_effect(path: str) -> dict:
            time.sleep(delay)
            return probe

        return _side_effect

    def test_video_light_rows_async_returns_immediately(
        self, qapp: QApplication, tmp_path: Path
    ) -> None:
        from unittest.mock import patch

        video = tmp_path / "sample.mp4"
        video.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        probe = {
            "duration_seconds": 10.5,
            "width": 1280,
            "height": 720,
            "fps": 30.0,
            "video_bitrate": 1_500_000,
            "format_name": "mov,mp4",
        }
        panel = _make_panel(qapp, tmp_path)
        with patch.object(fis, "_media_probe", side_effect=self._slow_probe(probe, 0.5)):
            started = time.perf_counter()
            panel.set_file(_file_info(str(video)))
            elapsed_ms = (time.perf_counter() - started) * 1000
            # ffprobe mock 延迟 500ms：基础行必须同步渲染、set_file 不得等待
            assert elapsed_ms < 50, f"set_file 阻塞了 {elapsed_ms:.1f}ms"
            rows = dict(panel._rows)
            assert rows["类别"] == "MP4 视频"
            assert "大小" in rows
            assert "时长" not in rows  # 媒体行尚未到达
            # 泵事件循环直至媒体行异步到达
            assert wait_for_signal(panel.media_loaded, timeout_ms=8000)
            rows = dict(panel._rows)
            assert rows["时长"] == "00:10"
            assert "720p · 30 fps · 1.5 Mbps" in rows["画面信息"]
        panel.stop()
        safe_teardown(panel)

    def test_video_probe_empty_shows_placeholder(
        self, qapp: QApplication, tmp_path: Path
    ) -> None:
        """ffprobe 无结果（等价超时）时媒体行落占位符，不挂死不抛异常。"""
        from unittest.mock import patch

        video = tmp_path / "broken.mp4"
        video.write_bytes(b"not a real mp4")
        panel = _make_panel(qapp, tmp_path)
        with patch.object(fis, "_media_probe", side_effect=self._slow_probe({}, 0.05)):
            panel.set_file(_file_info(str(video)))
            assert wait_for_signal(panel.media_loaded, timeout_ms=8000)
            rows = dict(panel._rows)
            assert rows["画面信息"] == fis.UNAVAILABLE
            assert "时长" not in rows
            assert panel._file_info["path"] == str(video)
        panel.stop()
        safe_teardown(panel)

    def test_switch_video_discards_stale_media_result(
        self, qapp: QApplication, tmp_path: Path
    ) -> None:
        from unittest.mock import patch

        video_a = tmp_path / "a.mp4"
        video_a.write_bytes(b"\x00\x00\x00\x18ftypmp42a")
        video_b = tmp_path / "b.mp4"
        video_b.write_bytes(b"\x00\x00\x00\x18ftypmp42b")
        # A 慢（0.4s）B 快（0.1s）：B 先到达并展示，A 迟到结果必须被 token 丢弃
        probe_a = {"duration_seconds": 5, "width": 640, "height": 360}
        probe_b = {"duration_seconds": 30, "width": 1920, "height": 1080}
        panel = _make_panel(qapp, tmp_path)

        def _probe(path: str) -> dict:
            if str(path) == str(video_a):
                time.sleep(0.4)
                return probe_a
            time.sleep(0.1)
            return probe_b

        with patch.object(fis, "_media_probe", side_effect=_probe):
            panel.set_file(_file_info(str(video_a)))
            panel.set_file(_file_info(str(video_b)))  # 立刻切换
            assert wait_for_signal(panel.media_loaded, timeout_ms=8000)
            rows = dict(panel._rows)
            assert rows["时长"] == "00:30"  # 当前文件 B 的媒体行
            # 再等 A 的陈旧结果（0.4s 后到达）被丢弃：行内容不得被覆盖
            _pump(qapp, 1000)
            rows = dict(panel._rows)
            assert rows["时长"] == "00:30"
            assert panel._file_info["path"] == str(video_b)
        panel.stop()
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


class TestHashTaskNativeWiring:
    """``_HashTask`` native 流式接线（todo 24）。

    直接同步执行 ``_HashTask.run()``（与 QThreadPool 跨线程投递同一实现）：
    native 可用时走 ``faf_core.hash_file_streaming``；DLL 缺失/失败回退
    ``fis.compute_hashes``；缓存写回（``write_cached`` / ``_CACHE_LOCK`` /
    800 上限 / 原子替换）契约不变；取消不写缓存；缺失文件落 ``-`` 占位。
    """

    @staticmethod
    def _run_task(task) -> dict:
        """同步执行任务并捕获 done 结果（同线程直接连接，emit 同步触发）。"""
        import freeassetfilter.ui.layout.preview.file_info_panel as fip_module

        out: dict = {}
        task.done.connect(lambda values: out.update(values or {}))
        task.run()
        return out

    @staticmethod
    def _native_available() -> bool:
        from freeassetfilter.core.native.bridges.faf_core_bridge import (
            get_faf_core_bridge,
        )

        bridge = get_faf_core_bridge()
        return bool(bridge.available and bridge._supports_hash)  # noqa: SLF001

    def test_native_streaming_result_and_cache(
        self, qapp: QApplication, temp_file: str, tmp_path: Path
    ) -> None:
        import hashlib

        from freeassetfilter.ui.layout.preview.file_info_panel import _HashTask

        if not self._native_available():
            pytest.skip("faf_core.dll 不含流式哈希导出，跳过 native 路径")
        cache = str(tmp_path / "fic.json")
        raw = Path(temp_file).read_bytes()
        values = self._run_task(_HashTask(temp_file, cache))
        assert values["SHA256"] == hashlib.sha256(raw).hexdigest()
        # 缓存写回契约不变（native 结果同样落缓存）
        cached = fis.read_cached(temp_file, cache_path=cache)
        assert cached is not None
        assert cached["hashes"]["SHA256"] == values["SHA256"]

    def test_fallback_when_dll_missing(
        self, qapp: QApplication, temp_file: str, tmp_path: Path
    ) -> None:
        """DLL 缺失（桥降级）→ 回退 compute_hashes，结果/缓存契约不变。"""
        import hashlib
        from unittest.mock import Mock, patch

        import freeassetfilter.ui.layout.preview.file_info_panel as fip_module
        from freeassetfilter.ui.layout.preview.file_info_panel import _HashTask

        degraded = Mock(available=False, _supports_hash=False)
        cache = str(tmp_path / "fic.json")
        raw = Path(temp_file).read_bytes()
        with patch.object(
            fip_module._faf_bridge, "get_faf_core_bridge", return_value=degraded
        ):
            values = self._run_task(_HashTask(temp_file, cache))
        assert values["SHA256"] == hashlib.sha256(raw).hexdigest()
        cached = fis.read_cached(temp_file, cache_path=cache)
        assert cached is not None
        assert cached["hashes"]["SHA256"] == values["SHA256"]

    def test_missing_file_placeholder(self, qapp: QApplication, tmp_path: Path) -> None:
        """缺失文件 → native OSError None → 回退 compute_hashes 落 `-` 占位。"""
        from freeassetfilter.ui.layout.preview.file_info_panel import _HashTask

        values = self._run_task(_HashTask(str(tmp_path / "nope.bin"), None))
        assert values == {
            "MD5": fis.UNAVAILABLE,
            "SHA1": fis.UNAVAILABLE,
            "SHA256": fis.UNAVAILABLE,
        }

    def test_cancel_writes_no_cache(self, qapp: QApplication, tmp_path: Path) -> None:
        """取消（协作式标记）→ 返回部分结果、绝不写缓存。"""
        from freeassetfilter.ui.layout.preview.file_info_panel import _HashTask

        path = tmp_path / "big.bin"
        path.write_bytes(bytes(3 * 1024 * 1024))  # 3MiB（多块）
        cache = str(tmp_path / "fic.json")
        task = _HashTask(str(path), cache)
        task.request_cancel()
        values = self._run_task(task)
        assert len(values.get("SHA256", "")) == 64
        assert not Path(cache).exists(), "取消不得写缓存"
