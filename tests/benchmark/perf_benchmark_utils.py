# -*- coding: utf-8 -*-
"""性能基准测试辅助工具（todo-27 benchmark 重写）。

提供缩小版临时数据集的程序化生成（图像 20 张 ≤256px / SVG 5 个 /
zip 1 个），以及 perf_metrics 的清理、快照导出与摘要读取辅助函数。

资源纪律：

* 数据一律落在调用方传入的临时目录（``tmp_path`` / ``tmp_path_factory``），
  绝不访问真实 ``data/``；
* 图像尺寸默认 240x180（两轴均 ≤256px），避免旧版 100 张 1920px 的
  高耗时；断言口径由各测试文件按旧基准缩小 5 倍后的宽松阈值承接。
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from freeassetfilter.utils.perf_metrics import (
    clear_perf_metrics,
    export_perf_metrics,
    get_perf_snapshot,
)

#: SVG 最小可渲染模板（256px 画布，品牌色圆 + 标签文字）。
SIMPLE_SVG_TEMPLATE: str = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" '
    'viewBox="0 0 256 256">\n'
    '  <rect width="256" height="256" rx="24" fill="#ffffff"/>\n'
    '  <circle cx="128" cy="128" r="72" fill="#0a59f7"/>\n'
    '  <text x="128" y="146" font-size="42" text-anchor="middle" '
    'fill="#333333">{text}</text>\n'
    "</svg>\n"
)

#: 基准图片尺寸（两轴均 ≤256px 的缩小约束）。
IMAGE_SIZE: Tuple[int, int] = (240, 180)


@dataclass
class PerfBenchmarkDataset:
    """基准测试数据集。

    ``root_dir`` 下按 ``images/`` / ``svgs/`` / ``archives/`` 三个子目录
    存放生成产物；路径列表供各性能测试直接消费。
    """

    root_dir: str
    image_paths: List[str]
    svg_paths: List[str]
    archive_paths: List[str]

    def snapshot_path(self, name: str = "perf_snapshot.json") -> str:
        """返回把性能快照写入数据集目录时的目标路径。

        Args:
            name: 快照文件名。

        Returns:
            str: 数据集根目录下的快照绝对路径。
        """
        return str(Path(self.root_dir) / name)


def _ensure_parent(path: str) -> None:
    """确保目标文件父目录存在。

    Args:
        path: 目标文件路径。
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def create_test_image(
    path: str,
    size: Tuple[int, int] = IMAGE_SIZE,
    color: Tuple[int, int, int] = (255, 120, 30),
) -> str:
    """生成一张纯色 JPEG 测试图（两轴 ≤256px）。

    Args:
        path: 输出路径（以 ``.jpg`` 结尾）。
        size: 图像尺寸（默认 240x180，两轴均 ≤256）。
        color: RGB 填充颜色。

    Returns:
        str: 生成后的文件路径。
    """
    from PIL import Image

    _ensure_parent(path)
    image = Image.new("RGB", size, color=color)
    image.save(path, "JPEG", quality=90)
    return path


def create_test_svg(path: str, text: str = "SVG") -> str:
    """生成一个最小可渲染 SVG 文件。

    Args:
        path: 输出路径（以 ``.svg`` 结尾）。
        text: 画布中央的标签文字。

    Returns:
        str: 生成后的文件路径。
    """
    _ensure_parent(path)
    Path(path).write_text(SIMPLE_SVG_TEMPLATE.format(text=text), encoding="utf-8")
    return path


def create_test_archive(path: str, source_files: Sequence[str]) -> str:
    """把若干源文件打包成一个 ZIP 压缩包。

    Args:
        path: 输出路径（以 ``.zip`` 结尾）。
        source_files: 待打包的源文件路径序列。

    Returns:
        str: 生成后的压缩包路径。

    Raises:
        FileNotFoundError: 任一源文件缺失时由 ``zipfile`` 抛出。
    """
    _ensure_parent(path)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for source_file in source_files:
            zf.write(source_file, arcname=Path(source_file).name)
    return path


def create_benchmark_dataset(
    base_dir: str,
    *,
    image_count: int = 20,
    svg_count: int = 5,
    archive_count: int = 1,
) -> PerfBenchmarkDataset:
    """在指定临时目录内生成缩小版基准数据集。

    Args:
        base_dir: 数据集根目录（应传入 ``tmp_path`` / ``tmp_path_factory``
            派生的会话级临时目录，绝不使用真实 data/）。
        image_count: 图像数量（默认 20，全部 ≤256px）。
        svg_count: SVG 数量（默认 5）。
        archive_count: ZIP 数量（默认 1）。

    Returns:
        PerfBenchmarkDataset: 数据集（含三组路径）。
    """
    root: Path = Path(base_dir)
    image_dir: Path = root / "images"
    svg_dir: Path = root / "svgs"
    archive_dir: Path = root / "archives"

    image_paths: List[str] = []
    svg_paths: List[str] = []

    for i in range(image_count):
        r: int = (i * 37) % 255
        g: int = (i * 61) % 255
        b: int = (i * 91) % 255
        image_paths.append(
            create_test_image(
                str(image_dir / f"image_{i:03d}.jpg"),
                color=(r, g, b),
            )
        )

    for i in range(svg_count):
        svg_paths.append(
            create_test_svg(str(svg_dir / f"icon_{i:03d}.svg"), text=f"S{i}")
        )

    archive_paths: List[str] = []
    sources: List[str] = image_paths[: max(1, min(6, len(image_paths)))] + svg_paths[
        : max(1, min(3, len(svg_paths)))
    ]
    for i in range(archive_count):
        archive_paths.append(
            create_test_archive(str(archive_dir / f"sample_{i:02d}.zip"), sources)
        )

    return PerfBenchmarkDataset(
        root_dir=str(root),
        image_paths=image_paths,
        svg_paths=svg_paths,
        archive_paths=archive_paths,
    )


def reset_perf_metrics() -> None:
    """清空 perf_metrics 注册表的全部事件与计数器。"""
    clear_perf_metrics()


def export_perf_snapshot(output_path: Optional[str] = None) -> str:
    """导出当前 perf_metrics 快照 JSON。

    Args:
        output_path: 输出路径；None 时导出到默认快照目录
            （``~/.freeassetfilter/performance/``，供 regression 子命令
            读取最新快照做时序对比）。

    Returns:
        str: 快照文件的绝对路径。
    """
    return export_perf_metrics(output_path)


def get_perf_summary() -> Dict[str, Dict]:
    """读取 perf_metrics 当前 events 映射（event name -> stats dict）。

    Returns:
        dict[str, dict]: 指标名到统计字典的映射（可能为空）。
    """
    snapshot = get_perf_snapshot()
    return snapshot.get("events", {})


def print_perf_summary(title: str = "Perf Summary") -> None:
    """把当前 perf_metrics 快照打印到控制台（供 -s 调试与证据留档）。

    Args:
        title: 摘要标题。
    """
    snapshot = get_perf_snapshot()
    print(f"\n=== {title} ===")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))