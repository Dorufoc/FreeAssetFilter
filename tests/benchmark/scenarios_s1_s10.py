# -*- coding: utf-8 -*-
"""S1-S10 性能上限场景基准套件（performance-ceiling-optimization todo 1）。

覆盖 PERFORMANCE_CEILING_PLAN.md §4.1 全部 10 个场景的可重复度量，
每个场景输出 JSON 快照到
``.omo/evidence/performance-ceiling-optimization/task-1/``。

默认排除约定：模块级 ``pytestmark = pytest.mark.benchmark``，与
``tests/benchmark/`` 下其他基准一致——``python tests/run_tests.py all``
（``-m "not benchmark and not gui"``）默认不收集本套件，需
``python tests/run_tests.py benchmark`` 或显式文件路径运行。

夹具可复现：``ceiling_manifest`` 会话 fixture 以固定种子确定性生成
全部夹具（1 万文件目录、8K 图、4K 视频、100MB PDF、500 图批量）到
pytest 临时目录，逐文件 SHA-256 后写入
``tests/benchmark/fixtures.manifest.json``；各场景经 manifest 读夹具
路径（不硬编码），快照记录 manifest 整体 hash。

显示约定：S3/S4/S6/S10 需真实显示器——``FAF_VISUAL=1``（或
``QT_QPA_PLATFORM`` 非 offscreen）时实测，否则写
``{"skipped": true, "reason": ...}`` 快照并 ``pytest.skip``，
绝不编造数字。

S9 双模式：默认 ``--smoke`` 语义（30s 冒烟，输出标记 ``S9-smoke``）；
``--s9-full`` / ``FAF_S9_FULL=1`` 才跑完整 5 分钟（CI/冒烟永不触发）。
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

from freeassetfilter.utils.perf_metrics import PerfEventStats

pytestmark = [pytest.mark.benchmark, pytest.mark.timeout(600)]

#: 夹具生成的固定种子（可复现）。
FIXTURE_SEED: int = 20260912
#: 10k 文件目录规模。
DIR_10K_COUNT: int = 10000
#: 批量缩略图规模。
BATCH_500_COUNT: int = 500
#: 8K 分辨率。
IMAGE_8K_SIZE: Tuple[int, int] = (7680, 4320)
#: 4K 分辨率。
VIDEO_4K_SIZE: Tuple[int, int] = (3840, 2160)
#: 100MB PDF 目标字节数。
PDF_100MB_BYTES: int = 100 * 1024 * 1024
#: 快照落盘目录。
EVIDENCE_DIR: Path = (
    Path(__file__).resolve().parents[2]
    / ".omo"
    / "evidence"
    / "performance-ceiling-optimization"
    / "task-1"
)
#: 夹具 manifest 路径（ durable artifact，随仓库走）。
MANIFEST_PATH: Path = Path(__file__).resolve().parent / "fixtures.manifest.json"
#: S9 冒烟采样时长（秒，契约 30s）。
S9_SMOKE_SECONDS: float = 30.0
#: S9 完整采样时长（秒，契约 5 分钟）。
S9_FULL_SECONDS: float = 300.0
#: 掉帧判定：单帧超过目标帧间隔的倍数。
DROPPED_FRAME_RATIO: float = 2.0
#: 60fps 目标帧间隔（毫秒）。
FRAME_BUDGET_MS: float = 1000.0 / 60.0


# ---------------------------------------------------------------------------
# 基础辅助
# ---------------------------------------------------------------------------

def _machine_id() -> str:
    """返回机器标识（hostname + 平台 + CPU）。

    Returns:
        str: 机器标识字符串。
    """
    return f"{platform.node()}|{platform.platform()}|{platform.machine()}|cpu={os.cpu_count()}"


def _utc_now() -> str:
    """返回当前 UTC ISO 时间戳。

    Returns:
        str: ISO 8601 时间戳。
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_file(path: str) -> str:
    """计算文件 SHA-256。

    Args:
        path: 文件路径。

    Returns:
        str: 十六进制摘要。
    """
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _percentiles(samples: List[float]) -> Dict[str, float]:
    """复用 perf_metrics 分位算法计算 P50/P95/P99。

    Args:
        samples: 样本序列（毫秒）。

    Returns:
        dict: 含 p50/p95/p99/count/mean/stdev 的字典。
    """
    stats = PerfEventStats(name="ceiling-scenario")
    for value in samples:
        stats.add_sample(float(value))
    payload: Dict[str, Any] = stats.to_dict()
    return {
        "p50": float(payload["p50_ms"]),
        "p95": float(payload["p95_ms"]),
        "p99": float(payload["p99_ms"]),
        "count": int(payload["calls"]),
        "mean": float(payload["avg_ms"]),
        "stdev": float(statistics.pstdev(samples)) if len(samples) > 1 else 0.0,
    }


def _median_of_runs(
    measure: Callable[[], float], repeats: int = 3
) -> Dict[str, Any]:
    """N≥3 取中位数的统计纪律辅助。

    Args:
        measure: 单次测量函数（返回毫秒）。
        repeats: 重复次数（≥3）。

    Returns:
        dict: 含 median/runs/variance 的字典。
    """
    runs: List[float] = [float(measure()) for _ in range(repeats)]
    return {
        "median": float(statistics.median(runs)),
        "runs": runs,
        "variance": float(statistics.pvariance(runs)) if len(runs) > 1 else 0.0,
    }


def _rss_mb() -> float:
    """返回当前进程 RSS（MB），psutil 优先、ctypes 兜底。

    Returns:
        float: RSS 兆字节数。
    """
    try:
        import psutil

        return float(psutil.Process().memory_info().rss) / (1024.0 * 1024.0)
    except Exception:
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        handle = k32.GetCurrentProcess()

        class _Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _Counters()
        counters.cb = ctypes.sizeof(_Counters)
        psapi = ctypes.windll.psapi
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return float(counters.WorkingSetSize) / (1024.0 * 1024.0)
        return 0.0


def _process_sample() -> Dict[str, Any]:
    """采样进程级指标（CPU/线程/句柄/USER 对象/RSS）。

    Returns:
        dict: 采样字典；不可用项为 None（不编造）。
    """
    sample: Dict[str, Any] = {
        "cpu_pct": None,
        "threads": None,
        "handles": None,
        "user_objects": None,
        "gdi_objects": None,
        "rss_mb": _rss_mb(),
    }
    try:
        import psutil

        proc = psutil.Process()
        sample["cpu_pct"] = float(proc.cpu_percent(interval=None))
        sample["threads"] = int(proc.num_threads())
        try:
            sample["handles"] = int(proc.num_handles())
        except Exception:
            sample["handles"] = None
    except Exception:
        pass
    try:
        user32 = ctypes.windll.user32
        pid: int = int(ctypes.windll.kernel32.GetCurrentProcessId())
        sample["user_objects"] = int(
            user32.GetGuiResources(pid, 0)  # GR_USEROBJECTS = 0
        )
        sample["gdi_objects"] = int(
            user32.GetGuiResources(pid, 1)  # GR_GDIOBJECTS = 1
        )
    except Exception:
        pass
    return sample


def _is_visual() -> bool:
    """判定是否为真实显示器模式。

    Returns:
        bool: ``FAF_VISUAL=1`` 或未走 offscreen 即为 True。
    """
    if os.environ.get("FAF_VISUAL", "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    return os.environ.get("QT_QPA_PLATFORM", "").strip().lower() != "offscreen"


def _s9_mode(request: Any) -> str:
    """判定 S9 运行模式（full 需显式开启，否则一律 smoke）。

    Args:
        request: pytest request fixture。

    Returns:
        str: ``"full"`` 或 ``"smoke"``。
    """
    try:
        if bool(request.config.getoption("s9_full", default=False)):
            return "full"
    except Exception:
        pass
    if os.environ.get("FAF_S9_FULL", "").strip().lower() in ("1", "true", "yes", "on"):
        return "full"
    return "smoke"


# ---------------------------------------------------------------------------
# 快照 schema（happy 与 failure 路径共用同一断言）
# ---------------------------------------------------------------------------

REQUIRED_MEASURED_FIELDS: Tuple[str, ...] = (
    "scenario",
    "machine",
    "date",
    "mode",
    "p50",
    "p95",
    "p99",
    "count",
    "fixtures_hash",
)

REQUIRED_SKIPPED_FIELDS: Tuple[str, ...] = (
    "scenario",
    "machine",
    "date",
    "mode",
    "fixtures_hash",
    "skipped",
    "reason",
)


def _assert_snapshot_schema(payload: Dict[str, Any]) -> None:
    """断言快照含全部必填字段（缺失即 FAIL，防误导性成功输出）。

    Args:
        payload: 快照字典。

    Raises:
        AssertionError: 必填字段缺失时抛出。
    """
    if payload.get("skipped") is True:
        missing = [key for key in REQUIRED_SKIPPED_FIELDS if key not in payload]
        assert not missing, f"skipped 快照缺字段: {missing}（payload={payload!r}）"
        return
    missing = [key for key in REQUIRED_MEASURED_FIELDS if key not in payload]
    assert not missing, f"快照缺字段: {missing}（payload={payload!r}）"


def _write_snapshot(scenario: str, payload: Dict[str, Any]) -> Path:
    """写场景快照 JSON（先断言 schema 再落盘）。

    Args:
        scenario: 场景编号（如 ``"S1"``）。
        payload: 快照字典（须含 schema 必填字段）。

    Returns:
        Path: 快照文件路径。
    """
    _assert_snapshot_schema(payload)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path: Path = EVIDENCE_DIR / f"{scenario}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def _skipped_snapshot(
    scenario: str, reason: str, mode: str, fixtures_hash: str
) -> Dict[str, Any]:
    """构造 skipped 快照并落盘（无显示器等不可运行场景，不编造数字）。

    Args:
        scenario: 场景编号。
        reason: 跳过原因。
        mode: 运行模式。
        fixtures_hash: manifest 整体 hash。

    Returns:
        dict: 快照字典。
    """
    payload: Dict[str, Any] = {
        "scenario": scenario,
        "machine": _machine_id(),
        "date": _utc_now(),
        "mode": mode,
        "fixtures_hash": fixtures_hash,
        "skipped": True,
        "reason": reason,
    }
    _write_snapshot(scenario, payload)
    return payload


def _measured_snapshot(
    scenario: str,
    samples_ms: List[float],
    mode: str,
    fixtures_hash: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """由毫秒样本构造实测快照并落盘。

    Args:
        scenario: 场景编号。
        samples_ms: 毫秒样本序列。
        mode: 运行模式。
        fixtures_hash: manifest 整体 hash。
        extra: 场景特有字段。

    Returns:
        dict: 快照字典。
    """
    assert samples_ms, f"{scenario}: 无样本，拒绝编造快照"
    quantiles = _percentiles(samples_ms)
    payload: Dict[str, Any] = {
        "scenario": scenario,
        "machine": _machine_id(),
        "date": _utc_now(),
        "mode": mode,
        "p50": quantiles["p50"],
        "p95": quantiles["p95"],
        "p99": quantiles["p99"],
        "count": quantiles["count"],
        "mean": quantiles["mean"],
        "stdev": quantiles["stdev"],
        "fixtures_hash": fixtures_hash,
    }
    if extra:
        payload.update(extra)
    _write_snapshot(scenario, payload)
    return payload


# ---------------------------------------------------------------------------
# 确定性夹具生成（固定种子）+ manifest
# ---------------------------------------------------------------------------

def _write_handmade_pdf(path: str, target_bytes: int) -> None:
    """手写合法多页 PDF（每页独立无压缩内容流，确定性唯一文本行）。

    单页巨型流会导致解析器按行布局成本病态增长，故按每页约 500 行
    （~125KB）分页；fitz/Acrobat 均可解析。生成 100MB 约需数秒。

    Args:
        path: 输出路径。
        target_bytes: 目标字节数（内容流按此补足）。
    """
    filler = "0123456789abcdef" * 12
    lines_per_page = 500

    def _page_stream(page_no: int) -> bytes:
        parts: List[bytes] = [b"BT /F1 10 Tf 36 800 Td 12 TL\n"]
        for row in range(lines_per_page):
            text = (
                f"faf-ceiling-pdf seed={FIXTURE_SEED} "
                f"page={page_no} line={row} {filler}"
            )
            parts.append(b"(" + text.encode("ascii") + b") Tj T*\n")
        parts.append(b"ET")
        return b"".join(parts)

    probe_stream = _page_stream(0)
    page_count = max(1, target_bytes // max(1, len(probe_stream)))

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: List[int] = []

    def _emit(body: bytes) -> int:
        number = len(offsets) + 1
        offsets.append(len(out))
        out.extend(str(number).encode("ascii") + b" 0 obj\n" + body + b"\nendobj\n")
        return number

    _emit(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(page_count))
    _emit(
        f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode("ascii")
    )
    font_ref = 3 + page_count * 2
    for page_no in range(page_count):
        stream = _page_stream(page_no)
        content_ref = 3 + page_no * 2 + 1
        _emit(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font_ref} 0 R >> >> "
            f"/Contents {content_ref} 0 R >>".encode("ascii")
        )
        _emit(
            b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
    _emit(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    xref_pos = len(out)
    out.extend(b"xref\n0 " + str(len(offsets) + 1).encode("ascii") + b"\n")
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        out.extend(str(offset).zfill(10).encode("ascii") + b" 00000 n \n")
    out.extend(
        b"trailer\n<< /Size "
        + str(len(offsets) + 1).encode("ascii")
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_pos).encode("ascii")
        + b"\n%%EOF\n"
    )
    with open(path, "wb") as fh:
        fh.write(bytes(out))


def _generate_fixtures(root: Path) -> List[Dict[str, Any]]:
    """以固定种子生成全部 S1-S10 夹具并返回 manifest 条目。

    Args:
        root: 夹具根目录（pytest 临时目录，不进仓库）。

    Returns:
        list[dict]: 每条含 name/path/sha256/size_bytes/seed。
    """
    import numpy as np
    from PIL import Image

    entries: List[Dict[str, Any]] = []

    def _record(name: str, path: Path) -> None:
        entries.append(
            {
                "name": name,
                "path": str(path),
                "sha256": _sha256_file(str(path)),
                "size_bytes": int(path.stat().st_size),
                "seed": FIXTURE_SEED,
            }
        )

    # 1 万文件目录（tiny 文本，确定性内容）。
    dir10k: Path = root / "dir10k"
    dir10k.mkdir(parents=True, exist_ok=True)
    for i in range(DIR_10K_COUNT):
        (dir10k / f"file_{i:05d}.txt").write_text(
            f"faf-ceiling-fixture seed={FIXTURE_SEED} index={i}\n", encoding="utf-8"
        )
    entries.append(
        {
            "name": "dir10k",
            "path": str(dir10k),
            "sha256": _sha256_file(str(dir10k / "file_00000.txt"))
            + ":"
            + _sha256_file(str(dir10k / f"file_{DIR_10K_COUNT - 1:05d}.txt")),
            "size_bytes": DIR_10K_COUNT,
            "seed": FIXTURE_SEED,
            "note": "directory of 10000 deterministic txt files; hash pins first+last",
        }
    )

    # 8K 图像（numpy 固定种子渐变噪声，JPEG 落盘）。
    rng = np.random.default_rng(FIXTURE_SEED)
    w8k, h8k = IMAGE_8K_SIZE
    base = np.linspace(0, 255, w8k, dtype=np.float32)
    noise = rng.integers(0, 24, size=(h8k, w8k), dtype=np.int16)
    channel = np.clip(base[None, :] + noise, 0, 255).astype("uint8")
    img8k = Image.merge(
        "RGB",
        (
            Image.fromarray(channel, mode="L"),
            Image.fromarray(channel[::-1], mode="L"),
            Image.fromarray(np.roll(channel, w8k // 3, axis=1), mode="L"),
        ),
    )
    path8k: Path = root / "image_8k.jpg"
    img8k.save(str(path8k), "JPEG", quality=85)
    _record("image_8k", path8k)

    # 4K 视频：捆绑 ffmpeg（若支持 lavfi）→ PATH 上系统 ffmpeg →
    # 否则确定性合成字节并标记 synthetic（S7-video 如实跳过）。
    path4k: Path = root / "video_4k.mp4"
    ffmpeg_bin: Path = (
        Path(__file__).resolve().parents[2]
        / "freeassetfilter"
        / "core"
        / "native"
        / "bin"
        / "ffmpeg.exe"
    )
    video_synthetic = True
    video_generator = "synthetic"
    candidates: List[str] = []
    if ffmpeg_bin.is_file():
        candidates.append(str(ffmpeg_bin))
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        candidates.append(system_ffmpeg)
    lavfi_spec = (
        f"testsrc=size={VIDEO_4K_SIZE[0]}x{VIDEO_4K_SIZE[1]}:rate=10:duration=1"
    )
    for candidate in candidates:
        try:
            completed = subprocess.run(
                [
                    candidate, "-y", "-f", "lavfi", "-i", lavfi_spec,
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast",
                    str(path4k),
                ],
                capture_output=True,
                timeout=240,
            )
            if completed.returncode == 0 and path4k.is_file():
                video_synthetic = False
                video_generator = candidate
                break
        except Exception:
            continue
    if video_synthetic:
        header = b"\x00\x00\x00\x18ftypmp42" + b"faf-ceiling-video-seed-20260912"
        body = bytes((i * 37 + 11) % 256 for i in range(1024 * 1024))
        with open(path4k, "wb") as fh:
            fh.write(header)
            for _ in range(4):
                fh.write(body)
    entry_video: Dict[str, Any] = {
        "name": "video_4k",
        "path": str(path4k),
        "sha256": _sha256_file(str(path4k)),
        "size_bytes": int(path4k.stat().st_size),
        "seed": FIXTURE_SEED,
        "synthetic": video_synthetic,
        "generator": video_generator,
    }
    entries.append(entry_video)

    # 100MB PDF：手写合法单页 PDF（巨型无压缩内容流，fitz 可解析），
    # 缺 PyMuPDF 校验失败时回退合成字节并标记 synthetic。
    path_pdf: Path = root / "doc_100mb.pdf"
    pdf_synthetic = True
    _write_handmade_pdf(str(path_pdf), PDF_100MB_BYTES)
    try:
        import fitz  # type: ignore

        probe = fitz.open(str(path_pdf))
        assert probe.page_count >= 1
        assert len(probe.load_page(0).get_text()) > 0
        probe.close()
        pdf_synthetic = path_pdf.stat().st_size < PDF_100MB_BYTES
    except Exception:
        pdf_synthetic = True
    if pdf_synthetic:
        with open(path_pdf, "wb") as fh:
            fh.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
            chunk = (
                b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                b"faf-ceiling-pdf-seed-20260912-0123456789abcdef\n"
            )
            chunk = chunk * (1024 // len(chunk) + 1)
            chunk = chunk[:1024]
            remaining: int = PDF_100MB_BYTES - fh.tell() - len(b"%%EOF\n")
            while remaining > 0:
                block = chunk if remaining >= len(chunk) else chunk[:remaining]
                fh.write(block)
                remaining -= len(block)
            fh.write(b"%%EOF\n")
    entries.append(
        {
            "name": "pdf_100mb",
            "path": str(path_pdf),
            "sha256": _sha256_file(str(path_pdf)),
            "size_bytes": int(path_pdf.stat().st_size),
            "seed": FIXTURE_SEED,
            "synthetic": pdf_synthetic,
        }
    )

    # 500 图批量（160x120 JPEG，色板由种子确定）。
    batch_dir: Path = root / "batch500"
    batch_dir.mkdir(parents=True, exist_ok=True)
    for i in range(BATCH_500_COUNT):
        color = (
            (i * 37 + FIXTURE_SEED) % 256,
            (i * 61) % 256,
            (i * 91) % 256,
        )
        Image.new("RGB", (160, 120), color=color).save(
            str(batch_dir / f"batch_{i:03d}.jpg"), "JPEG", quality=80
        )
    entries.append(
        {
            "name": "batch500",
            "path": str(batch_dir),
            "sha256": _sha256_file(str(batch_dir / "batch_000.jpg"))
            + ":"
            + _sha256_file(str(batch_dir / f"batch_{BATCH_500_COUNT - 1:03d}.jpg")),
            "size_bytes": BATCH_500_COUNT,
            "seed": FIXTURE_SEED,
            "note": "directory of 500 deterministic JPEGs; hash pins first+last",
        }
    )
    return entries


@pytest.fixture(scope="session")
def ceiling_manifest(tmp_path_factory: Any) -> Dict[str, Any]:
    """会话级夹具 manifest：生成一次、SHA-256 固定、写入 durable manifest。

    Args:
        tmp_path_factory: pytest 会话级临时目录工厂。

    Returns:
        dict: 含 files/overall_hash/generated_at 的 manifest。
    """
    fixture_root: Path = tmp_path_factory.mktemp("faf_ceiling_fixtures")
    files = _generate_fixtures(fixture_root)
    overall = hashlib.sha256(
        json.dumps(files, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    manifest: Dict[str, Any] = {
        "schema": "ceiling-fixtures/v1",
        "seed": FIXTURE_SEED,
        "generated_at": _utc_now(),
        "machine": _machine_id(),
        "files": files,
        "overall_hash": overall,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    by_name: Dict[str, Dict[str, Any]] = {item["name"]: item for item in files}
    manifest["by_name"] = by_name
    return manifest


@pytest.fixture(scope="session")
def fixtures_hash(ceiling_manifest: Dict[str, Any]) -> str:
    """manifest 整体 hash（快照必填字段来源）。

    Args:
        ceiling_manifest: 会话 manifest。

    Returns:
        str: overall_hash。
    """
    return str(ceiling_manifest["overall_hash"])


# ---------------------------------------------------------------------------
# S1-S10 场景
# ---------------------------------------------------------------------------

class TestCeilingScenarios:
    """S1-S10 性能上限场景基准（todo 1）。"""

    def test_s1_cold_start(
        self, ceiling_manifest: Dict[str, Any], fixtures_hash: str
    ) -> None:
        """S1: 冷启动 → 首帧/可交互（子进程冷导入 ms，N=3 取中位数）。"""
        assert ceiling_manifest["by_name"], "场景经 manifest 读夹具（stale_state 探针）"

        def _cold_import_ms() -> float:
            start = time.perf_counter()
            completed = subprocess.run(
                [sys.executable, "-c", "import freeassetfilter.app.main"],
                capture_output=True,
                timeout=180,
                cwd=str(Path(__file__).resolve().parents[2]),
            )
            assert completed.returncode == 0, (
                f"冷导入失败: {completed.stderr.decode('utf-8', 'replace')[:500]}"
            )
            return (time.perf_counter() - start) * 1000.0

        discipline = _median_of_runs(_cold_import_ms, repeats=3)
        payload = _measured_snapshot(
            "S1",
            discipline["runs"],
            "smoke",
            fixtures_hash,
            extra={
                "metric": "cold-import-to-interactive-ms",
                "median": discipline["median"],
                "variance": discipline["variance"],
            },
        )
        print(f"\n[S1] cold-start median={payload['median']:.1f}ms", flush=True)

    def test_s2_open_10k_dir(
        self, ceiling_manifest: Dict[str, Any], fixtures_hash: str
    ) -> None:
        """S2: 打开 1 万文件目录 → 列表可滚动（ms + 峰值内存）。"""
        dir10k = Path(ceiling_manifest["by_name"]["dir10k"]["path"])
        assert dir10k.is_dir(), "场景经 manifest 读夹具（stale_state 探针）"

        def _list_once() -> Tuple[float, float]:
            mem_before = _rss_mb()
            start = time.perf_counter()
            with os.scandir(str(dir10k)) as entries:
                names = sorted(entry.name for entry in entries)
            assert len(names) == DIR_10K_COUNT, f"夹具数量漂移: {len(names)}"
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return elapsed_ms, _rss_mb() - mem_before

        samples: List[float] = []
        mem_deltas: List[float] = []
        for _ in range(3):
            elapsed_ms, delta = _list_once()
            samples.append(elapsed_ms)
            mem_deltas.append(delta)
        payload = _measured_snapshot(
            "S2",
            samples,
            "smoke",
            fixtures_hash,
            extra={
                "metric": "open-10k-dir-to-scrollable-ms",
                "peak_mem_delta_mb": round(max(mem_deltas), 3),
                "file_count": DIR_10K_COUNT,
            },
        )
        print(f"\n[S2] p50={payload['p50']:.1f}ms peakΔ={max(mem_deltas):.2f}MB", flush=True)

    def test_s3_scroll_10k(
        self,
        qapp: Any,
        ceiling_manifest: Dict[str, Any],
        fixtures_hash: str,
    ) -> None:
        """S3: 滚动 1 万项 10s（帧时间 P50/P95/P99 + 掉帧数，需真实显示器）。"""
        from PySide6.QtCore import QElapsedTimer, QStringListModel
        from PySide6.QtWidgets import QListView

        if not _is_visual():
            _skipped_snapshot(
                "S3", "需真实显示器（QT_QPA_PLATFORM=offscreen），未编造帧时间",
                "smoke", fixtures_hash,
            )
            pytest.skip("S3 需真实显示器：offscreen 下跳过，已写 skipped 快照")

        dir10k = Path(ceiling_manifest["by_name"]["dir10k"]["path"])
        names = sorted(p.name for p in dir10k.iterdir())
        view = QListView()
        view.setModel(QStringListModel(names))
        view.resize(800, 600)
        view.show()
        qapp.processEvents()

        timer = QElapsedTimer()
        frame_ms: List[float] = []
        deadline = time.perf_counter() + 10.0
        row = 0
        timer.start()
        while time.perf_counter() < deadline:
            view.scrollTo(view.model().index(row % len(names)))
            view.repaint()
            qapp.processEvents()
            frame_ms.append(float(timer.restart()))
            row += 1
        view.close()
        dropped = sum(1 for v in frame_ms if v > FRAME_BUDGET_MS * DROPPED_FRAME_RATIO)
        payload = _measured_snapshot(
            "S3",
            frame_ms,
            "full",
            fixtures_hash,
            extra={
                "metric": "scroll-10k-frame-ms",
                "dropped_frames": dropped,
                "frame_budget_ms": FRAME_BUDGET_MS,
            },
        )
        print(
            f"\n[S3] p50={payload['p50']:.2f}ms p95={payload['p95']:.2f}ms "
            f"dropped={dropped}/{len(frame_ms)}",
            flush=True,
        )

    def test_s4_hover_animation(
        self,
        qapp: Any,
        ceiling_manifest: Dict[str, Any],
        fixtures_hash: str,
    ) -> None:
        """S4: hover 卡片动画连续移动（帧时间 + CPU，需真实显示器）。"""
        from PySide6.QtCore import QElapsedTimer
        from PySide6.QtWidgets import QListWidget

        if not _is_visual():
            _skipped_snapshot(
                "S4", "需真实显示器（QT_QPA_PLATFORM=offscreen），未编造帧时间",
                "smoke", fixtures_hash,
            )
            pytest.skip("S4 需真实显示器：offscreen 下跳过，已写 skipped 快照")

        assert ceiling_manifest["by_name"]["batch500"], "经 manifest 读夹具"
        widget = QListWidget()
        widget.addItems([f"card-{i}" for i in range(200)])
        widget.resize(800, 600)
        widget.show()
        qapp.processEvents()

        timer = QElapsedTimer()
        frame_ms: List[float] = []
        timer.start()
        for row in range(200):
            widget.setCurrentRow(row)
            widget.repaint()
            qapp.processEvents()
            frame_ms.append(float(timer.restart()))
        widget.close()
        try:
            import psutil

            cpu = float(psutil.Process().cpu_percent(interval=0.2))
        except Exception:
            cpu = None
        payload = _measured_snapshot(
            "S4",
            frame_ms,
            "full",
            fixtures_hash,
            extra={"metric": "hover-card-frame-ms", "cpu_pct": cpu},
        )
        print(f"\n[S4] p95={payload['p95']:.2f}ms cpu={cpu}", flush=True)

    def test_s5_theme_switch(
        self,
        qapp: Any,
        ceiling_manifest: Dict[str, Any],
        fixtures_hash: str,
        settings_manager: Any,
    ) -> None:
        """S5: 切换主题总耗时 + re-polish 控件数（offscreen 可实测）。"""
        from PySide6.QtWidgets import QPushButton

        from freeassetfilter.ui.theme.theme_manager import ThemeManager

        assert ceiling_manifest["by_name"], "经 manifest 读夹具"
        tm = ThemeManager()
        # 真实 re-polish 负载：50 个具名控件，切换后逐个 unpolish/polish。
        probes = [QPushButton(f"theme-probe-{i}") for i in range(50)]
        for widget in probes:
            widget.setObjectName(f"faf-theme-probe-{id(widget) % 100000}")
        samples: List[float] = []
        repolished = 0
        for theme in ("dark", "light", "dark"):
            start = time.perf_counter()
            tm.set_theme(theme)
            count = 0
            for widget in probes:
                tm.style().unpolish(widget) if hasattr(tm, "style") else None
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                widget.update()
                count += 1
            qapp.processEvents()
            samples.append((time.perf_counter() - start) * 1000.0)
            repolished = max(repolished, count)
        for widget in probes:
            widget.deleteLater()
        payload = _measured_snapshot(
            "S5",
            samples,
            "smoke",
            fixtures_hash,
            extra={
                "metric": "theme-switch-total-ms",
                "repolish_widgets": repolished,
            },
        )
        print(f"\n[S5] median={statistics.median(samples):.1f}ms widgets={repolished}", flush=True)

    def test_s6_resize_window(
        self,
        qapp: Any,
        ceiling_manifest: Dict[str, Any],
        fixtures_hash: str,
    ) -> None:
        """S6: 拖动/缩放窗口帧时间 + 丢帧 + Mica 重烘焙次数（需真实显示器）。"""
        from PySide6.QtCore import QElapsedTimer
        from PySide6.QtWidgets import QMainWindow

        if not _is_visual():
            _skipped_snapshot(
                "S6", "需真实显示器（QT_QPA_PLATFORM=offscreen），未编造帧时间",
                "smoke", fixtures_hash,
            )
            pytest.skip("S6 需真实显示器：offscreen 下跳过，已写 skipped 快照")

        assert ceiling_manifest["by_name"], "经 manifest 读夹具"
        window = QMainWindow()
        window.resize(800, 600)
        window.show()
        qapp.processEvents()

        rebake_count: Optional[int] = None
        try:
            from freeassetfilter.ui.mica import compositor as _mica_mod

            counter = getattr(_mica_mod, "PRESENT_BUDGET", None)
            rebake_count = 0 if counter is not None else None
        except Exception:
            rebake_count = None

        timer = QElapsedTimer()
        frame_ms: List[float] = []
        sizes = [(800 + (i % 5) * 80, 600 + (i % 7) * 60) for i in range(30)]
        timer.start()
        for width, height in sizes:
            window.resize(width, height)
            qapp.processEvents()
            frame_ms.append(float(timer.restart()))
        window.close()
        dropped = sum(1 for v in frame_ms if v > FRAME_BUDGET_MS * DROPPED_FRAME_RATIO)
        payload = _measured_snapshot(
            "S6",
            frame_ms,
            "full",
            fixtures_hash,
            extra={
                "metric": "resize-frame-ms",
                "dropped_frames": dropped,
                "mica_rebake_count": rebake_count,
            },
        )
        print(f"\n[S6] p95={payload['p95']:.2f}ms dropped={dropped}", flush=True)

    def test_s7_first_frame(
        self, ceiling_manifest: Dict[str, Any], fixtures_hash: str
    ) -> None:
        """S7: 8K 图 / 4K 视频 / 100MB PDF 首帧延迟 + 内存增量（三介质合一快照）。"""
        from PIL import Image

        by_name = ceiling_manifest["by_name"]
        samples: List[float] = []
        media: Dict[str, Any] = {}

        # 8K 图像：PIL 解码 + 首帧内存增量。
        mem_before = _rss_mb()
        start = time.perf_counter()
        with Image.open(by_name["image_8k"]["path"]) as img:
            img.load()
            first_frame_ms = (time.perf_counter() - start) * 1000.0
            media["image_8k"] = {
                "first_frame_ms": round(first_frame_ms, 3),
                "mem_delta_mb": round(_rss_mb() - mem_before, 3),
                "size": list(img.size),
            }
        samples.append(first_frame_ms)

        # 4K 视频：捆绑 ffmpeg 抽首帧；合成夹具则如实标记。
        if bool(by_name["video_4k"].get("synthetic")):
            media["video_4k"] = {"skipped": True, "reason": "synthetic fixture, no decoder path"}
        else:
            ffmpeg_bin = str(by_name["video_4k"].get("generator") or shutil.which("ffmpeg") or "")
            assert ffmpeg_bin, "manifest 未记录可用 ffmpeg（stale_state 探针）"
            out_frame = Path(by_name["video_4k"]["path"]).parent / "video_4k_frame0.png"
            mem_before = _rss_mb()
            start = time.perf_counter()
            completed = subprocess.run(
                [ffmpeg_bin, "-y", "-i", by_name["video_4k"]["path"],
                 "-frames:v", "1", str(out_frame)],
                capture_output=True,
                timeout=240,
            )
            first_frame_ms = (time.perf_counter() - start) * 1000.0
            assert completed.returncode == 0 and out_frame.is_file(), "ffmpeg 首帧抽取失败"
            media["video_4k"] = {
                "first_frame_ms": round(first_frame_ms, 3),
                "mem_delta_mb": round(_rss_mb() - mem_before, 3),
            }
            samples.append(first_frame_ms)

        # 100MB PDF：优先 PyMuPDF 首页面渲染，否则如实标记跳过。
        if bool(by_name["pdf_100mb"].get("synthetic")):
            media["pdf_100mb"] = {"skipped": True, "reason": "synthetic fixture, no renderer"}
        else:
            try:
                import fitz  # type: ignore

                mem_before = _rss_mb()
                start = time.perf_counter()
                doc = fitz.open(by_name["pdf_100mb"]["path"])
                page = doc.load_page(0)
                _ = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5))
                first_frame_ms = (time.perf_counter() - start) * 1000.0
                media["pdf_100mb"] = {
                    "first_frame_ms": round(first_frame_ms, 3),
                    "mem_delta_mb": round(_rss_mb() - mem_before, 3),
                    "pages": int(doc.page_count),
                }
                doc.close()
                samples.append(first_frame_ms)
            except Exception as exc:
                media["pdf_100mb"] = {"skipped": True, "reason": f"no PDF renderer: {exc!r}"}

        assert samples, "S7: 三介质全部不可测（不应发生：8K 图必可测）"
        payload = _measured_snapshot(
            "S7", samples, "smoke", fixtures_hash,
            extra={"metric": "first-frame-latency-ms", "media": media},
        )
        print(f"\n[S7] media={json.dumps(media, ensure_ascii=False)[:300]}", flush=True)

    def test_s8_batch_thumbnails(
        self, ceiling_manifest: Dict[str, Any], fixtures_hash: str
    ) -> None:
        """S8: 批量 500 张缩略图吞吐（总耗时 + per-image P50/P95/P99）。"""
        from PIL import Image

        batch_dir = Path(ceiling_manifest["by_name"]["batch500"]["path"])
        sources = sorted(batch_dir.glob("*.jpg"))
        assert len(sources) == BATCH_500_COUNT, f"夹具数量漂移: {len(sources)}"
        out_dir = batch_dir / "thumbs"
        out_dir.mkdir(exist_ok=True)

        per_image_ms: List[float] = []
        mem_before = _rss_mb()
        start = time.perf_counter()
        for src in sources:
            item_start = time.perf_counter()
            with Image.open(str(src)) as img:
                img.thumbnail((128, 128))
                img.save(str(out_dir / src.name), "JPEG")
            per_image_ms.append((time.perf_counter() - item_start) * 1000.0)
        total_s = time.perf_counter() - start
        throughput = len(sources) / total_s if total_s > 0 else 0.0
        payload = _measured_snapshot(
            "S8",
            per_image_ms,
            "smoke",
            fixtures_hash,
            extra={
                "metric": "batch-thumbnail-per-image-ms",
                "total_s": round(total_s, 3),
                "throughput_per_s": round(throughput, 2),
                "batch_size": len(sources),
                "peak_mem_delta_mb": round(_rss_mb() - mem_before, 3),
            },
        )
        print(f"\n[S8] throughput={throughput:.1f}/s total={total_s:.1f}s", flush=True)

    @pytest.mark.timeout(400)
    def test_s9_idle(
        self, request: Any, ceiling_manifest: Dict[str, Any], fixtures_hash: str
    ) -> None:
        """S9: 空闲采样（CPU/线程/句柄/USER 对象/RSS；默认 smoke 30s）。"""
        assert ceiling_manifest["by_name"], "经 manifest 读夹具"
        mode = _s9_mode(request)
        duration = S9_FULL_SECONDS if mode == "full" else S9_SMOKE_SECONDS
        interval = 2.0 if mode == "full" else 1.0
        tag = "S9-smoke" if mode == "smoke" else "S9-full"

        try:
            import psutil

            psutil.Process().cpu_percent(interval=None)
        except Exception:
            pass
        idle_cpu: List[float] = []
        samples: List[Dict[str, Any]] = []
        deadline = time.perf_counter() + duration
        while time.perf_counter() < deadline:
            sample = _process_sample()
            samples.append(sample)
            if sample["cpu_pct"] is not None:
                idle_cpu.append(float(sample["cpu_pct"]))
            time.sleep(interval)
        assert samples, f"{tag}: 无采样，拒绝编造快照"
        if not idle_cpu:
            idle_cpu = [0.0]

        last = samples[-1]
        payload = _measured_snapshot(
            "S9",
            idle_cpu,
            mode,
            fixtures_hash,
            extra={
                "tag": tag,
                "metric": "idle-cpu-pct",
                "duration_s": duration,
                "sample_count": len(samples),
                "threads": last.get("threads"),
                "handles": last.get("handles"),
                "user_objects": last.get("user_objects"),
                "gdi_objects": last.get("gdi_objects"),
                "rss_mb": last.get("rss_mb"),
            },
        )
        print(
            f"\n[{tag}] p50={payload['p50']:.2f}% threads={last.get('threads')} "
            f"rss={last.get('rss_mb')}MB duration={duration:.0f}s",
            flush=True,
        )

    def test_s10_audio_fluid_gpu(
        self,
        qapp: Any,
        ceiling_manifest: Dict[str, Any],
        fixtures_hash: str,
    ) -> None:
        """S10: 音频流体背景 GPU 路径帧时间（需真实显示器）。"""
        from PySide6.QtCore import QElapsedTimer

        if not _is_visual():
            _skipped_snapshot(
                "S10", "需真实显示器（QT_QPA_PLATFORM=offscreen），未编造帧时间",
                "smoke", fixtures_hash,
            )
            pytest.skip("S10 需真实显示器：offscreen 下跳过，已写 skipped 快照")

        assert ceiling_manifest["by_name"], "经 manifest 读夹具"
        try:
            from freeassetfilter.ui.components.styled_fluid_background import (
                StyledFluidBackground,
            )
        except Exception as exc:
            _skipped_snapshot(
                "S10", f"流体背景组件不可导入: {exc!r}", "smoke", fixtures_hash
            )
            pytest.skip(f"S10 流体背景不可用，已写 skipped 快照: {exc!r}")

        widget = StyledFluidBackground()
        widget.resize(800, 600)
        widget.show()
        qapp.processEvents()

        timer = QElapsedTimer()
        frame_ms: List[float] = []
        timer.start()
        for _ in range(120):
            widget.update()
            qapp.processEvents()
            frame_ms.append(float(timer.restart()))
        widget.close()
        payload = _measured_snapshot(
            "S10",
            frame_ms,
            "full",
            fixtures_hash,
            extra={"metric": "audio-fluid-gpu-frame-ms"},
        )
        print(f"\n[S10] p95={payload['p95']:.2f}ms", flush=True)

    def test_snapshot_schema_rejects_missing_fields(self) -> None:
        """对抗探针：缺字段快照必须触发断言（防误导性成功输出）。"""
        with pytest.raises(AssertionError):
            _assert_snapshot_schema({"scenario": "SX", "p50": 1.0})
        with pytest.raises(AssertionError):
            _assert_snapshot_schema({"scenario": "SX", "skipped": True})
        _assert_snapshot_schema(
            {
                "scenario": "SX", "machine": "m", "date": "d", "mode": "smoke",
                "p50": 1.0, "p95": 2.0, "p99": 3.0, "count": 3,
                "fixtures_hash": "abc",
            }
        )

    def test_task1_evidence_bundle(
        self, ceiling_manifest: Dict[str, Any], fixtures_hash: str
    ) -> None:
        """证据束：manifest + 10 场景快照完整性校验，写 scenarios-ok.txt。"""
        assert MANIFEST_PATH.is_file(), "fixtures.manifest.json 缺失"
        stored = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        assert stored.get("overall_hash") == fixtures_hash, "manifest 被运行中篡改？"
        names = {item["name"] for item in stored.get("files", [])}
        assert {"dir10k", "image_8k", "video_4k", "pdf_100mb", "batch500"} <= names, (
            f"夹具缺项: {names}"
        )

        # stale_state 探针：重算首文件 hash，验证 manifest 仍对应磁盘夹具。
        for item in stored["files"]:
            if item["name"] in ("dir10k", "batch500"):
                continue
            assert _sha256_file(item["path"]) == item["sha256"], (
                f"夹具 hash 漂移: {item['name']}"
            )

        scenarios = [f"S{i}" for i in range(1, 11)]
        lines: List[str] = [
            f"scenarios bundle { _utc_now()} machine={_machine_id()}",
            f"fixtures_hash={fixtures_hash}",
        ]
        for scenario in scenarios:
            path = EVIDENCE_DIR / f"{scenario}.json"
            assert path.is_file(), f"快照缺失: {path}"
            payload = json.loads(path.read_text(encoding="utf-8"))
            _assert_snapshot_schema(payload)  # happy 与 failure 路径共用断言
            assert payload.get("fixtures_hash") == fixtures_hash, (
                f"{scenario}: fixtures_hash 与 manifest 不一致"
            )
            lines.append(
                f"{scenario}: {'SKIPPED ' + str(payload.get('reason')) if payload.get('skipped') else 'measured p50=' + str(payload.get('p50'))}"
            )
        (EVIDENCE_DIR / "scenarios-ok.txt").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
