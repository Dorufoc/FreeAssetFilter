"""
性能基准测试辅助工具

提供：
- 临时测试数据集创建
- perf metrics 初始化与快照导出
- 简单的基准结果打印
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image

from freeassetfilter.utils.perf_metrics import clear_perf_metrics, export_perf_metrics, get_perf_snapshot


SIMPLE_SVG_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <rect width="256" height="256" rx="24" fill="#000000"/>
  <circle cx="128" cy="128" r="72" fill="#0a59f7"/>
  <text x="128" y="146" font-size="42" text-anchor="middle" fill="#FFFFFF">{text}</text>
</svg>
"""


@dataclass
class PerfBenchmarkDataset:
    root_dir: str
    image_paths: List[str]
    svg_paths: List[str]
    archive_paths: List[str]
    timeline_dir: Optional[str] = None

    def cleanup(self) -> None:
        shutil.rmtree(self.root_dir, ignore_errors=True)


def _ensure_parent(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def create_test_image(path: str, size=(1920, 1080), color=(255, 0, 0)) -> str:
    _ensure_parent(path)
    img = Image.new("RGB", size, color=color)
    img.save(path, "JPEG", quality=95)
    return path


def create_test_svg(path: str, text: str = "SVG") -> str:
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(SIMPLE_SVG_TEMPLATE.format(text=text))
    return path


def create_test_archive(path: str, source_files: List[str]) -> str:
    _ensure_parent(path)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for source_file in source_files:
            zf.write(source_file, arcname=os.path.basename(source_file))
    return path


def create_benchmark_dataset(
    *,
    image_count: int = 20,
    svg_count: int = 10,
    archive_count: int = 2,
    timeline_video_placeholders: int = 5,
) -> PerfBenchmarkDataset:
    root_dir = tempfile.mkdtemp(prefix="faf_perf_benchmark_")
    image_dir = os.path.join(root_dir, "images")
    svg_dir = os.path.join(root_dir, "svgs")
    archive_dir = os.path.join(root_dir, "archives")
    timeline_dir = os.path.join(root_dir, "timeline_inputs")

    image_paths: List[str] = []
    svg_paths: List[str] = []
    archive_paths: List[str] = []

    for i in range(image_count):
        image_paths.append(
            create_test_image(
                os.path.join(image_dir, f"image_{i:03d}.jpg"),
                size=(1920 + (i % 5) * 100, 1080 + (i % 3) * 50),
                color=((i * 17) % 255, (i * 29) % 255, (i * 43) % 255),
            )
        )

    for i in range(svg_count):
        svg_paths.append(
            create_test_svg(
                os.path.join(svg_dir, f"icon_{i:03d}.svg"),
                text=f"S{i}",
            )
        )

    archive_sources = image_paths[: max(1, min(10, len(image_paths)))] + svg_paths[: max(1, min(5, len(svg_paths)))]
    for i in range(archive_count):
        archive_paths.append(
            create_test_archive(
                os.path.join(archive_dir, f"sample_{i:02d}.zip"),
                archive_sources,
            )
        )

    # timeline 测试数据入口：先创建占位文件，真实视频可由外部覆盖
    os.makedirs(timeline_dir, exist_ok=True)
    for i in range(timeline_video_placeholders):
        placeholder = os.path.join(timeline_dir, f"video_{i:03d}.mp4")
        with open(placeholder, "wb") as f:
            f.write(b"")

    return PerfBenchmarkDataset(
        root_dir=root_dir,
        image_paths=image_paths,
        svg_paths=svg_paths,
        archive_paths=archive_paths,
        timeline_dir=timeline_dir,
    )


def reset_perf_metrics() -> None:
    clear_perf_metrics()


def export_perf_snapshot(output_path: Optional[str] = None) -> str:
    return export_perf_metrics(output_path)


def get_perf_summary() -> Dict[str, Dict]:
    snapshot = get_perf_snapshot()
    return snapshot.get("events", {})


def print_perf_summary(title: str = "Perf Summary") -> None:
    snapshot = get_perf_snapshot()
    print(f"\n=== {title} ===")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
