"""
统一性能埋点链路基准测试

覆盖：
- thumbnail
- svg
- py7z
- timeline（有真实视频时执行，否则跳过耗时链路）
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.benchmark.perf_benchmark_utils import (
    create_benchmark_dataset,
    export_perf_snapshot,
    get_perf_summary,
    print_perf_summary,
    reset_perf_metrics,
)


class TestPerfMetricsPipeline:
    def setup_method(self):
        self.dataset = create_benchmark_dataset(
            image_count=12,
            svg_count=6,
            archive_count=2,
            timeline_video_placeholders=3,
        )
        reset_perf_metrics()

    def teardown_method(self):
        self.dataset.cleanup()

    def test_thumbnail_svg_py7z_pipeline(self):
        from freeassetfilter.core.thumbnail_manager import get_thumbnail_manager
        from freeassetfilter.core.svg_renderer import SvgRenderer
        from freeassetfilter.core.py7z_core import get_7z_core

        manager = get_thumbnail_manager(1.0)

        # thumbnail
        for image_path in self.dataset.image_paths[:6]:
            manager.create_thumbnail(image_path, force_regenerate=True)
            manager.create_thumbnail(image_path, force_regenerate=False)

        # svg
        for svg_path in self.dataset.svg_paths:
            SvgRenderer.render_svg_to_pixmap(svg_path, icon_size=24)
            SvgRenderer.render_svg_to_exact_pixmap(svg_path, icon_width=32, icon_height=32)
            SvgRenderer.render_unknown_file_icon(svg_path, text="T", icon_size=64)

        # archive
        core = get_7z_core()
        for archive_path in self.dataset.archive_paths:
            files = core.list_archive(archive_path)
            assert isinstance(files, list)

        summary = get_perf_summary()
        print_perf_summary("thumbnail+svg+py7z")

        assert "thumbnail.create_thumbnail" in summary
        assert "svg.render_pixmap" in summary
        assert "py7z.list_archive" in summary

        snapshot_path = export_perf_snapshot(
            os.path.join(self.dataset.root_dir, "perf_thumbnail_svg_py7z.json")
        )
        assert os.path.exists(snapshot_path)

    def test_timeline_pipeline_with_optional_real_videos(self):
        from freeassetfilter.core.timeline_generator import FolderScanner

        video_dir = Path(self.dataset.timeline_dir)
        real_video_candidates = [
            str(path)
            for path in video_dir.iterdir()
            if path.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv", ".mxf"} and path.stat().st_size > 0
        ]

        if not real_video_candidates:
            pytest.skip("timeline 基准未提供真实视频样本，已保留测试数据入口目录")

        scanner = FolderScanner(str(video_dir))
        scanner.run()

        summary = get_perf_summary()
        print_perf_summary("timeline")

        assert "timeline.folder_scanner.run" in summary
        assert "timeline.get_video_duration" in summary
        assert "media_probe.run_ffprobe_json" in summary

        snapshot_path = export_perf_snapshot(
            os.path.join(self.dataset.root_dir, "perf_timeline.json")
        )
        assert os.path.exists(snapshot_path)
