#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

自动时间线组件
用于多媒体资产管理与行为分析的核心可视化工具
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QFont, QLinearGradient, QPainter, QPen, QTextOption
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from freeassetfilter.core.settings_manager import SettingsManager
from freeassetfilter.core.timeline_generator import (
    CSVParser,
    FolderScanner,
    TimelineParams,
    build_timeline_dataset_from_events,
)
from freeassetfilter.core.timeline_layout import TimelineLayoutEngine, TimelineLayoutMetrics
from freeassetfilter.core.timeline_models import TimelineDataset, TimelineSegment, TimelineTrack, build_legacy_merged_events
from freeassetfilter.utils.app_logger import debug, info, warning
from freeassetfilter.widgets.button_widgets import CustomButton
from freeassetfilter.widgets.hover_tooltip import HoverTooltip
from freeassetfilter.widgets.smooth_scroller import SmoothScroller
from freeassetfilter.widgets.table_widgets import CustomMatrixTable


class TimelineWidget(QWidget):
    """
    基于布局引擎的数据驱动画布
    将渲染层与布局/命中测试分离，保留原有交互习惯。
    """

    timeline_clicked = Signal(int, int, dict)
    scale_changed = Signal(float)

    def __init__(self, params):
        super().__init__()
        debug("初始化 TimelineWidget")

        self.params = params
        self.layout_engine = TimelineLayoutEngine(
            TimelineLayoutMetrics(
                top_axis_height=30,
                row_height=int(self.params.row_height),
                row_padding=5,
                min_segment_width=2.0,
                right_padding=100,
                px_per_second=float(self.params.px_per_second),
            )
        )

        self.dataset = TimelineDataset()
        self.tracks = []
        self.legacy_events = []

        self.setMinimumHeight(600)
        self.setMinimumWidth(1200)
        self.setMouseTracking(True)

        self.hover_tooltip = HoverTooltip(self)
        self.hover_tooltip.set_target_widget(self)

        self.mouse_pos = QPoint()
        self.current_mouse_pos = QPoint()

        self.selected_segment_keys = set()
        self.primary_selected_key = None

        self.is_dragging = False
        self.drag_start_point = QPoint()
        self.drag_current_point = QPoint()

        app = QApplication.instance()
        global_font = getattr(app, "global_font", QFont())
        self.global_font = QFont(global_font)
        self.dpi_scale = getattr(app, "dpi_scale_factor", 1.0)

    def set_dataset(self, dataset: TimelineDataset, legacy_events=None):
        """
        设置新版数据集，同时可选保留旧版适配视图
        """
        self.dataset = dataset or TimelineDataset()
        self.tracks = list(self.dataset.tracks or [])
        self.legacy_events = list(legacy_events or [])
        self.layout_engine.set_row_height(int(self.params.row_height))
        self.layout_engine.update_scale(float(self.params.px_per_second))
        self.layout_engine.configure_from_dataset(self.dataset)

        self.params.global_start_time = self.dataset.global_start_time
        self.params.global_end_time = self.dataset.global_end_time

        total_width = self.layout_engine.total_content_width(self.width())
        total_height = self.layout_engine.total_content_height(len(self.tracks), self.height())
        self.setMinimumWidth(int(total_width))
        self.setMinimumHeight(int(total_height))
        self.update()

    def clear_selection(self):
        self.selected_segment_keys.clear()
        self.primary_selected_key = None
        self.update()

    def _segment_key(self, row_index: int, segment_index: int) -> tuple:
        return (row_index, segment_index)

    def _is_selected(self, row_index: int, segment_index: int) -> bool:
        return self._segment_key(row_index, segment_index) in self.selected_segment_keys

    def _build_segment_payload(self, row_index: int, segment_index: int, track: TimelineTrack, segment: TimelineSegment):
        duration = segment.start_time.secsTo(segment.end_time)
        return {
            "row_index": row_index,
            "segment_index": segment_index,
            "name": track.label,
            "device": track.key,
            "start_time": segment.start_time.toString("yyyy-MM-dd HH:mm:ss"),
            "end_time": segment.end_time.toString("yyyy-MM-dd HH:mm:ss"),
            "duration": duration,
            "video_count": len(segment.paths),
            "video_paths": list(segment.paths),
            "asset_types": list(segment.asset_types),
            "record_ids": list(segment.record_ids),
        }

    def _build_selection_event_info(self):
        selected_events = []

        for row_index, track in enumerate(self.tracks):
            for segment_index, segment in enumerate(track.segments):
                if self._is_selected(row_index, segment_index):
                    selected_events.append(
                        self._build_segment_payload(row_index, segment_index, track, segment)
                    )

        summary = {
            "selected_count": len(selected_events),
            "selected_tracks": len({item["device"] for item in selected_events}),
            "selected_files": sum(item["video_count"] for item in selected_events),
            "total_duration": sum(item["duration"] for item in selected_events),
        }

        return {
            "selected_events": selected_events,
            "summary": summary,
        }

    def _compute_tick_interval(self, total_duration: int) -> int:
        if total_duration <= 0:
            return 1

        target_ticks = 10
        raw_interval = total_duration / target_ticks
        intervals = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400]
        return min(intervals, key=lambda value: abs(value - raw_interval))

    def _draw_background(self, painter: QPainter):
        painter.fillRect(self.rect(), QColor(30, 30, 30))

        if not self.params.global_start_time or not self.params.global_end_time:
            return

        total_duration = self.params.global_start_time.secsTo(self.params.global_end_time)
        if total_duration <= 0:
            return

        interval = self._compute_tick_interval(total_duration)
        painter.setPen(QPen(QColor(50, 50, 50), 1))

        for offset in range(0, int(total_duration) + interval, interval):
            x = int(self.layout_engine.viewport.time_to_x(self.params.global_start_time.addSecs(offset)))
            painter.drawLine(x, 0, x, self.height())

    def _draw_time_scale(self, painter: QPainter):
        if not self.params.global_start_time or not self.params.global_end_time:
            return

        painter.setPen(QPen(Qt.white, 1))
        time_font = QFont(self.global_font)
        time_font.setPointSize(max(8, int(self.global_font.pointSize() * 1.05)))
        painter.setFont(time_font)

        total_duration = self.params.global_start_time.secsTo(self.params.global_end_time)
        interval = self._compute_tick_interval(total_duration)

        if interval < 60:
            format_str = "HH:mm:ss"
        elif interval < 3600:
            format_str = "HH:mm"
        else:
            format_str = "yyyy-MM-dd HH:mm"

        first_tick = self.params.global_start_time
        secs_since_epoch = first_tick.toSecsSinceEpoch()
        remainder = secs_since_epoch % interval
        if remainder != 0:
            first_tick = first_tick.addSecs(interval - remainder)

        current_time = first_tick
        while current_time <= self.params.global_end_time:
            x = int(self.layout_engine.viewport.time_to_x(current_time))
            painter.drawLine(x, 0, x, 20)
            painter.drawText(x - 40, 20, 80, 20, Qt.AlignCenter, current_time.toString(format_str))
            current_time = current_time.addSecs(interval)

    def _draw_tracks(self, painter: QPainter):
        for row_index, track in enumerate(self.tracks):
            row_top = self.layout_engine.row_top(row_index)

            painter.setPen(QPen(QColor(60, 60, 60), 1))
            painter.drawLine(0, row_top, self.width(), row_top)

            for segment_index, segment in enumerate(track.segments):
                rect = self.layout_engine.segment_rect(row_index, segment)
                is_selected = self._is_selected(row_index, segment_index)

                gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                color_hash = hash(track.label) % 256

                if is_selected:
                    gradient.setColorAt(0, QColor(60 + color_hash % 100, 125, 183))
                    gradient.setColorAt(1, QColor(16 + color_hash % 80, 87, 152))
                    painter.setPen(QPen(QColor(255, 255, 255), 2))
                else:
                    gradient.setColorAt(0, QColor(90 + color_hash % 100, 155, 213))
                    gradient.setColorAt(1, QColor(46 + color_hash % 80, 117, 182))
                    painter.setPen(QPen(QColor(30, 30, 30), 1))

                painter.setBrush(QBrush(gradient))
                painter.drawRoundedRect(rect, 4, 4)

                if segment.paths:
                    painter.setPen(QPen(Qt.white, 1))
                    count_font = QFont(self.global_font)
                    count_font.setPointSize(max(7, int(self.global_font.pointSize() * 0.9)))
                    painter.setFont(count_font)
                    painter.drawText(rect.adjusted(5, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, f"{len(segment.paths)}")

    def _draw_overlay(self, painter: QPainter):
        if not self.current_mouse_pos.isNull() and self.params.global_start_time and self.params.global_end_time:
            mouse_x = self.current_mouse_pos.x()
            if 0 <= mouse_x <= self.width():
                painter.setPen(QPen(QColor(255, 0, 0), 1, Qt.DashLine))
                painter.drawLine(mouse_x, 0, mouse_x, self.height())

                current_time = self.layout_engine.viewport.x_to_time(mouse_x)
                painter.setPen(QPen(QColor(255, 255, 255), 1))
                time_font = QFont(self.global_font)
                time_font.setPointSize(max(8, int(self.global_font.pointSize() * 1.05)))
                painter.setFont(time_font)
                painter.drawText(mouse_x + 5, 20, current_time.toString("yyyy-MM-dd HH:mm:ss"))

        if self.is_dragging:
            selection_rect = QRectF(self.drag_start_point, self.drag_current_point).normalized()
            selection_rect.setTop(self.layout_engine.metrics.top_axis_height)
            painter.setBrush(QBrush(QColor(0, 100, 255, 50)))
            painter.setPen(QPen(QColor(0, 150, 255), 1))
            painter.drawRect(selection_rect)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        self._draw_background(painter)
        self._draw_time_scale(painter)
        self._draw_tracks(painter)
        self._draw_overlay(painter)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            current_scale = self.params.px_per_second

            if delta > 0:
                new_scale = min(current_scale * 1.1, current_scale + 0.1)
            else:
                new_scale = max(current_scale * 0.9, current_scale - 0.1)

            new_scale = max(0.1, min(new_scale, 200))
            self.params.px_per_second = new_scale
            self.layout_engine.update_scale(new_scale)
            self.scale_changed.emit(new_scale)
            self.update()
            event.accept()
        else:
            super().wheelEvent(event)

    def enterEvent(self, event):
        self.current_mouse_pos = self.mapFromGlobal(QCursor.pos())
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.current_mouse_pos = QPoint()
        self.hover_tooltip.hide_tooltip()
        self.update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        self.mouse_pos = event.pos()
        self.current_mouse_pos = event.pos()

        if self.is_dragging:
            self.drag_current_point = event.pos()
            selection_rect = QRectF(self.drag_start_point, self.drag_current_point).normalized()
            selection_rect.setTop(self.layout_engine.metrics.top_axis_height)

            hits = self.layout_engine.collect_segments_in_rect(self.tracks, selection_rect)

            if not event.modifiers() & Qt.ControlModifier:
                selected_keys = set()
            else:
                selected_keys = set(self.selected_segment_keys)

            for hit in hits:
                selected_keys.add(self._segment_key(hit["row_index"], hit["segment_index"]))

            self.selected_segment_keys = selected_keys
            self.update()
            return

        hit = self.layout_engine.hit_test_segment(self.tracks, event.x(), event.y())
        if hit:
            payload = self._build_segment_payload(
                hit["row_index"],
                hit["segment_index"],
                hit["track"],
                hit["segment"],
            )

            tooltip_text = (
                f"{payload['name']}\n"
                f"分组: {payload['device']}\n"
                f"开始时间: {payload['start_time']}\n"
                f"结束时间: {payload['end_time']}\n"
                f"文件数量: {payload['video_count']}"
            )
            self.hover_tooltip.show_text_at(tooltip_text, event.globalPos())
        else:
            current_time = self.layout_engine.viewport.x_to_time(event.x())
            self.hover_tooltip.show_text_at(current_time.toString("yyyy-MM-dd HH:mm:ss"), event.globalPos())

        self.update()

    def mousePressEvent(self, event):
        self.drag_start_point = event.pos()
        self.drag_current_point = event.pos()
        self.is_dragging = True

        if not event.modifiers() & Qt.ControlModifier:
            self.selected_segment_keys.clear()
            self.primary_selected_key = None

        self.update()

    def mouseReleaseEvent(self, event):
        if not self.is_dragging:
            return

        self.is_dragging = False
        self.drag_current_point = event.pos()

        drag_distance = abs(self.drag_current_point.x() - self.drag_start_point.x()) + abs(
            self.drag_current_point.y() - self.drag_start_point.y()
        )

        if drag_distance < 8:
            hit = self.layout_engine.hit_test_segment(self.tracks, event.x(), event.y())
            if hit:
                key = self._segment_key(hit["row_index"], hit["segment_index"])

                if event.modifiers() & Qt.ControlModifier:
                    if key in self.selected_segment_keys:
                        self.selected_segment_keys.remove(key)
                    else:
                        self.selected_segment_keys.add(key)
                else:
                    self.selected_segment_keys = {key}

                self.primary_selected_key = key
                event_info = self._build_selection_event_info()
                self.timeline_clicked.emit(event.x(), event.y(), event_info)
            else:
                if not event.modifiers() & Qt.ControlModifier:
                    self.selected_segment_keys.clear()
                    self.primary_selected_key = None
                self.timeline_clicked.emit(event.x(), event.y(), self._build_selection_event_info())
        else:
            selection_rect = QRectF(self.drag_start_point, self.drag_current_point).normalized()
            selection_rect.setTop(self.layout_engine.metrics.top_axis_height)

            hits = self.layout_engine.collect_segments_in_rect(self.tracks, selection_rect)
            if not event.modifiers() & Qt.ControlModifier:
                self.selected_segment_keys.clear()

            for hit in hits:
                self.selected_segment_keys.add(self._segment_key(hit["row_index"], hit["segment_index"]))

            event_info = self._build_selection_event_info()
            self.timeline_clicked.emit(event.x(), event.y(), event_info)

        self.update()


class AutoTimeline(QWidget):
    """
    自动时间线主组件
    整合数据加载、处理和可视化功能
    """

    json_result_ready = Signal(str)

    def __init__(self, initial_path=None):
        super().__init__()
        debug("初始化 AutoTimeline")

        app = QApplication.instance()
        self.dpi_scale = getattr(app, "dpi_scale_factor", 1.0)

        global_font = getattr(app, "global_font", QFont())
        self.global_font = QFont(global_font)
        self.setFont(self.global_font)

        self.params = TimelineParams()
        self.params.dpi_scale = self.dpi_scale
        self.params.row_height = int(40 * self.dpi_scale)

        self.raw_events = []
        self.dataset = TimelineDataset()
        self.merged_events = []

        self.scanner = None
        self.csv_parser = None
        self.json_display_widget = None
        self.generated_csv_path = None
        self.generated_json_path = None

        self.delay_detection_timer = QTimer(self)
        self.delay_detection_timer.setInterval(500)
        self.delay_detection_timer.timeout.connect(self.check_and_adjust_timeline)

        self.initialized = False

        self.init_ui()

        if initial_path and initial_path != "All" and os.path.exists(initial_path):
            self.load_path(initial_path)

    def init_ui(self):
        debug("初始化 AutoTimeline UI")
        main_layout = QVBoxLayout(self)

        control_panel = self.create_control_panel()
        main_layout.addWidget(control_panel)

        self.progress_layout = QHBoxLayout()
        self.progress_label = QLabel("进度:")
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)

        self.progress_layout.addWidget(self.progress_label)
        self.progress_layout.addWidget(self.progress_bar)
        main_layout.addLayout(self.progress_layout)

        self.splitter = QSplitter(Qt.Horizontal)

        self.left_table = self.create_left_table()
        self.left_table.set_row_height(self.params.row_height)
        self.splitter.addWidget(self.left_table)

        self.timeline_draw_area = TimelineWidget(self.params)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.timeline_draw_area)
        self.scroll_area.setWidgetResizable(True)
        self.splitter.addWidget(self.scroll_area)

        SmoothScroller.apply_to_scroll_area(self.scroll_area)

        self.splitter.setSizes([330, 600])
        self.splitter.splitterMoved.connect(self.on_splitter_moved)

        main_layout.addWidget(self.splitter, 1)

        self.create_json_display()
        main_layout.addWidget(self.json_display_widget)

        self.left_table.verticalScrollBar().valueChanged.connect(
            self.scroll_area.verticalScrollBar().setValue
        )
        self.scroll_area.verticalScrollBar().valueChanged.connect(
            self.left_table.verticalScrollBar().setValue
        )

        self.timeline_draw_area.timeline_clicked.connect(self.on_timeline_clicked)
        self.timeline_draw_area.scale_changed.connect(self.on_timeline_scale_changed)

        if self.window() is not None and not hasattr(self.window(), "_old_resizeEvent"):
            self.window()._old_resizeEvent = self.window().resizeEvent
            self.window().resizeEvent = self.on_window_resize

    def showEvent(self, event):
        super().showEvent(event)
        self.delay_detection_timer.start()

        if self.merged_events:
            QTimer.singleShot(100, self.adjust_timeline_width)
            QTimer.singleShot(100, self.adjust_left_table_width)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.delay_detection_timer.stop()

    def adjust_left_table_width(self):
        if hasattr(self, "splitter") and self.splitter.count() > 0:
            left_width = self.splitter.sizes()[0]
            total_ratio = 15 + 10 + 8

            name_width = int(left_width * 15 / total_ratio)
            device_width = int(left_width * 10 / total_ratio)
            video_width = int(left_width * 8 / total_ratio)

            new_widths = [name_width, device_width, video_width]
            self.left_table.set_column_widths(new_widths)

            if self.merged_events:
                self.left_table.update_data(self.merged_events)

    def on_window_resize(self, event):
        if hasattr(self.window(), "_old_resizeEvent"):
            self.window()._old_resizeEvent(event)

        if self.merged_events:
            QTimer.singleShot(100, self.adjust_timeline_width)
            QTimer.singleShot(100, self.adjust_left_table_width)

    def check_and_adjust_timeline(self):
        if not self.initialized and self.merged_events:
            self.adjust_timeline_width()
            self.adjust_left_table_width()
            self.initialized = True

        if self.merged_events and self.params.global_start_time and self.params.global_end_time:
            total_duration = self.params.global_start_time.secsTo(self.params.global_end_time)
            expected_width = total_duration * self.params.px_per_second + 100

            if abs(self.timeline_draw_area.width() - expected_width) > 100:
                self.adjust_timeline_width()

            self.adjust_left_table_width()

    def create_control_panel(self):
        panel = QGroupBox("控制面板")
        layout = QHBoxLayout(panel)

        import_folder_btn = CustomButton("导入文件夹")
        import_folder_btn.clicked.connect(self.import_folder)
        layout.addWidget(import_folder_btn)

        import_csv_btn = CustomButton("导入CSV")
        import_csv_btn.clicked.connect(self.import_csv)
        layout.addWidget(import_csv_btn)

        layout.addWidget(QLabel("容差:"))
        self.gap_threshold_spinbox = QSpinBox()
        self.gap_threshold_spinbox.setRange(1, 3600)
        self.gap_threshold_spinbox.setValue(30)
        self.gap_threshold_spinbox.valueChanged.connect(self.on_gap_threshold_changed)
        layout.addWidget(self.gap_threshold_spinbox)

        self.gap_threshold_unit_combo = QComboBox()
        self.gap_threshold_unit_combo.addItems(["秒", "分", "时"])
        self.gap_threshold_unit_combo.setCurrentIndex(0)
        self.gap_threshold_unit_combo.currentIndexChanged.connect(self.on_gap_threshold_unit_changed)
        layout.addWidget(self.gap_threshold_unit_combo)

        layout.addWidget(QLabel("分组:"))
        self.group_by_combo = QComboBox()
        self.group_by_combo.addItem("按文件夹", "group")
        self.group_by_combo.addItem("按类型", "asset_type")
        self.group_by_combo.addItem("按日期", "date")
        self.group_by_combo.currentIndexChanged.connect(self.on_group_by_changed)
        layout.addWidget(self.group_by_combo)

        layout.addWidget(QLabel("时间来源:"))
        self.time_source_combo = QComboBox()
        self.time_source_combo.addItem("修改时间", "modified")
        self.time_source_combo.addItem("创建时间", "created")
        self.time_source_combo.currentIndexChanged.connect(self.on_time_source_changed)
        layout.addWidget(self.time_source_combo)

        layout.addWidget(QLabel("缩放:"))
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(1, 1000)
        self.scale_slider.setValue(10)
        self.scale_slider.setSingleStep(1)
        self.scale_slider.setPageStep(10)
        self.scale_slider.valueChanged.connect(self.on_scale_changed)
        layout.addWidget(self.scale_slider)

        self.scale_label = QLabel("1秒/像素")
        self.scale_label.setFixedWidth(70)
        layout.addWidget(self.scale_label)

        refresh_btn = CustomButton("刷新")
        refresh_btn.clicked.connect(self.refresh_timeline)
        layout.addWidget(refresh_btn)

        return panel

    def create_left_table(self):
        table = CustomMatrixTable()
        table.row_clicked.connect(self.on_table_row_clicked)
        return table

    def import_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if not folder_path:
            return
        self.load_path(folder_path)

    def load_path(self, folder_path):
        if not folder_path or not os.path.exists(folder_path):
            warning(f"文件夹路径无效: {folder_path}")
            return

        info(f"加载文件夹: {folder_path}")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.scanner = FolderScanner(folder_path, time_source=self.params.time_source)
        self.scanner.scan_finished.connect(self.on_scan_finished)
        self.scanner.progress.connect(self.on_progress_update)
        self.scanner.start()
        info("扫描线程已启动")

    def import_csv(self, file_path=None):
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "选择CSV文件", "", "CSV Files (*.csv);;All Files (*)"
            )

        if not file_path:
            return

        info(f"导入CSV: {file_path}")

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.csv_parser = CSVParser(file_path, time_source=self.params.time_source)
        self.csv_parser.finished.connect(self.on_csv_parse_finished)
        self.csv_parser.progress.connect(self.on_progress_update)
        self.csv_parser.start()

    def on_progress_update(self, current, total):
        if total > 0:
            progress = int((current / total) * 100)
            self.progress_bar.setValue(progress)

    def on_scan_finished(self, events, csv_path, json_path):
        if not events:
            self.progress_bar.setVisible(False)
            warning("扫描完成但没有找到事件")
            return

        self.progress_bar.setVisible(False)

        info(f"扫描完成，CSV: {csv_path}, JSON: {json_path}")
        self.generated_csv_path = csv_path
        self.generated_json_path = json_path

        self.csv_parser = CSVParser(csv_path, time_source=self.params.time_source)
        self.csv_parser.finished.connect(self.on_csv_parse_finished)
        self.csv_parser.progress.connect(self.on_progress_update)
        self.csv_parser.start()

    def on_csv_parse_finished_with_cleanup(self, events):
        self.on_csv_parse_finished(events)

        if hasattr(self, "temp_csv_path") and os.path.exists(self.temp_csv_path):
            os.unlink(self.temp_csv_path)
            delattr(self, "temp_csv_path")

    def on_csv_parse_finished(self, events):
        self.progress_bar.setVisible(False)

        debug(f"CSV解析完成: {len(events) if events else 0} 条事件")
        self.raw_events = events
        self.process_events()
        self.initialized = False

    def process_events(self):
        if not self.raw_events:
            warning("没有原始事件数据可处理")
            self.dataset = TimelineDataset()
            self.merged_events = []
            self.left_table.update_data([])
            self.timeline_draw_area.set_dataset(self.dataset, [])
            self.update_selection_panels({})
            return

        debug(f"处理事件: {len(self.raw_events)} 条原始事件")
        self.dataset = build_timeline_dataset_from_events(self.raw_events, self.params)
        self.merged_events = build_legacy_merged_events(self.dataset.tracks)

        debug(f"合并完成: {len(self.merged_events)} 条合并事件, 轨道数: {len(self.dataset.tracks)}")

        self.update_left_table()
        self.timeline_draw_area.set_dataset(self.dataset, self.merged_events)
        self.update_selection_panels({})

        QTimer.singleShot(200, self.adjust_timeline_width)
        QTimer.singleShot(200, self.adjust_left_table_width)

    def update_left_table(self):
        self.left_table.update_data(self.merged_events)
        self.left_table.set_row_height(self.params.row_height)

    def on_table_row_clicked(self, row_idx):
        if row_idx < 0 or row_idx >= len(self.dataset.tracks):
            return

        self.timeline_draw_area.clear_selection()

        track = self.dataset.tracks[row_idx]
        selected_info = {
            "selected_events": [],
            "summary": {
                "selected_count": len(track.segments),
                "selected_tracks": 1,
                "selected_files": sum(len(segment.paths) for segment in track.segments),
                "total_duration": sum(segment.start_time.secsTo(segment.end_time) for segment in track.segments),
            },
        }

        for segment_index, segment in enumerate(track.segments):
            self.timeline_draw_area.selected_segment_keys.add((row_idx, segment_index))
            selected_info["selected_events"].append(
                {
                    "name": track.label,
                    "device": track.key,
                    "start_time": segment.start_time.toString("yyyy-MM-dd HH:mm:ss"),
                    "end_time": segment.end_time.toString("yyyy-MM-dd HH:mm:ss"),
                    "duration": segment.start_time.secsTo(segment.end_time),
                    "video_count": len(segment.paths),
                    "video_paths": list(segment.paths),
                    "asset_types": list(segment.asset_types),
                    "record_ids": list(segment.record_ids),
                }
            )

        self.timeline_draw_area.update()
        self.update_selection_panels(selected_info)

    def on_timeline_clicked(self, x, y, event_info):
        self.update_selection_panels(event_info)

        if event_info:
            json_data = {
                "click_position": {"x": x, "y": y},
                "event_info": event_info,
            }
            json_str = json.dumps(json_data, ensure_ascii=False, indent=2)
            self.json_text_edit.setText(json_str)
            self.json_result_ready.emit(json_str)
        else:
            self.json_text_edit.setText("")

    def update_selection_panels(self, event_info):
        self.summary_text_edit.clear()
        self.file_list_table.setRowCount(0)

        if not event_info or not event_info.get("selected_events"):
            self.summary_text_edit.setText("未选择任何时间片段")
            return

        selected_events = event_info.get("selected_events", [])
        summary = event_info.get("summary", {})

        file_paths = []
        asset_type_counter = {}

        earliest_start = None
        latest_end = None

        for selected_event in selected_events:
            file_paths.extend(selected_event.get("video_paths", []))

            start_time = selected_event.get("start_time")
            end_time = selected_event.get("end_time")

            if earliest_start is None or (start_time and start_time < earliest_start):
                earliest_start = start_time
            if latest_end is None or (end_time and end_time > latest_end):
                latest_end = end_time

            for asset_type in selected_event.get("asset_types", []):
                asset_type_counter[asset_type] = asset_type_counter.get(asset_type, 0) + 1

        unique_file_paths = []
        seen = set()
        for path in file_paths:
            if path in seen:
                continue
            seen.add(path)
            unique_file_paths.append(path)

        summary_lines = [
            f"选中片段数：{summary.get('selected_count', len(selected_events))}",
            f"涉及轨道数：{summary.get('selected_tracks', 0)}",
            f"文件总数：{summary.get('selected_files', len(unique_file_paths))}",
            f"总持续时间：{summary.get('total_duration', 0)} 秒",
            f"最早开始：{earliest_start or '-'}",
            f"最晚结束：{latest_end or '-'}",
            f"分组方式：{self.group_by_combo.currentText()}",
            f"时间来源：{self.time_source_combo.currentText()}",
        ]

        if asset_type_counter:
            asset_parts = [f"{key}: {value}" for key, value in sorted(asset_type_counter.items())]
            summary_lines.append("资产类型分布：" + " / ".join(asset_parts))

        self.summary_text_edit.setText("\n".join(summary_lines))

        self.file_list_table.setRowCount(len(unique_file_paths))
        for row, path in enumerate(unique_file_paths):
            file_name = os.path.basename(path)
            name_item = QTableWidgetItem(file_name)
            path_item = QTableWidgetItem(path)
            self.file_list_table.setItem(row, 0, name_item)
            self.file_list_table.setItem(row, 1, path_item)

    def adjust_timeline_width(self):
        if not self.dataset.tracks or not self.params.global_start_time or not self.params.global_end_time:
            return

        total_duration = self.params.global_start_time.secsTo(self.params.global_end_time)
        total_width = total_duration * self.params.px_per_second + 100
        self.timeline_draw_area.setMinimumWidth(int(total_width))

    def on_gap_threshold_changed(self, value):
        self.params.gap_threshold = value
        if self.raw_events:
            self.process_events()

    def on_gap_threshold_unit_changed(self, index):
        units = ["sec", "min", "hour"]
        self.params.gap_threshold_unit = units[index]
        if self.raw_events:
            self.process_events()

    def on_group_by_changed(self, index):
        self.params.group_by = self.group_by_combo.currentData()
        if self.raw_events:
            self.process_events()

    def on_time_source_changed(self, index):
        self.params.time_source = self.time_source_combo.currentData()

    def on_splitter_moved(self, pos, index):
        left_width = pos
        total_ratio = 15 + 10 + 8

        name_width = int(left_width * 15 / total_ratio)
        device_width = int(left_width * 10 / total_ratio)
        video_width = int(left_width * 8 / total_ratio)

        new_widths = [name_width, device_width, video_width]
        self.left_table.set_column_widths(new_widths)

        if self.merged_events:
            self.left_table.update_data(self.merged_events)

    def create_json_display(self):
        self.json_display_widget = QTabWidget()
        self.json_display_widget.setFixedHeight(int(300 * self.dpi_scale))

        self.summary_text_edit = QTextEdit()
        self.summary_text_edit.setReadOnly(True)
        self.summary_text_edit.setWordWrapMode(QTextOption.WrapAnywhere)
        self.summary_text_edit.setStyleSheet(
            "background-color: #2b2b2b; color: #f0f0f0; font-family: Consolas, monospace;"
        )
        self.json_display_widget.addTab(self.summary_text_edit, "选中摘要")

        self.json_text_edit = QTextEdit()
        self.json_text_edit.setReadOnly(True)
        self.json_text_edit.setStyleSheet(
            "background-color: #2b2b2b; color: #f0f0f0; font-family: Consolas, monospace;"
        )
        self.json_display_widget.addTab(self.json_text_edit, "JSON数据")

        self.file_list_table = QTableWidget()
        self.file_list_table.setColumnCount(2)
        self.file_list_table.setHorizontalHeaderLabels(["文件名", "文件路径"])
        self.file_list_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.json_display_widget.addTab(self.file_list_table, "文件列表")

    def on_scale_changed(self, value):
        secs_per_pixel = value / 10.0
        self.params.px_per_second = 1.0 / secs_per_pixel
        self.scale_label.setText(f"{secs_per_pixel:.1f}秒/像素")
        self.timeline_draw_area.layout_engine.update_scale(self.params.px_per_second)
        self.timeline_draw_area.update()
        QTimer.singleShot(100, self.adjust_timeline_width)

    def on_timeline_scale_changed(self, scale):
        secs_per_pixel = 1.0 / scale
        slider_value = secs_per_pixel * 10.0

        self.scale_slider.blockSignals(True)
        self.scale_slider.setValue(int(round(slider_value)))
        self.scale_slider.blockSignals(False)

        self.scale_label.setText(f"{secs_per_pixel:.1f}秒/像素")
        QTimer.singleShot(100, self.adjust_timeline_width)

    def refresh_timeline(self):
        if self.raw_events:
            self.process_events()


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    settings_manager = SettingsManager()
    font_size = settings_manager.get_setting("font.size", 10)
    font_style = settings_manager.get_setting("font.style", "Microsoft YaHei")
    font = QFont(font_style, font_size)
    app.setFont(font)

    timeline = AutoTimeline()
    timeline.setWindowTitle("自动时间线测试")
    timeline.resize(1000, 700)
    timeline.show()

    sys.exit(app.exec())
