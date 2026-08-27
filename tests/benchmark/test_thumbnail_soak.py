# -*- coding: utf-8 -*-
# targets: core.native.bridges.rust_thumbnail_bridge
"""缩略图混合负载 soak 压测（thumbnail-rust-refactor todo 31）。

契约口径（计划原文）：默认 skip、需 ``-m soak`` 显式运行；混合负载
（50 正常 + 5 损坏 + 2 伪扩展名循环）持续 30 分钟，每轮校验——

* RSS 增长 < 50MB（psutil 采样进程 RSS，基线取预热后首采）；
* 无悬挂子进程：ffmpeg 子进程存活 > 20s 记悬挂。观测口径说明：桥的
  视频抽帧是同步调用，Rust 侧 ``run_command_with_timeout`` 保证子进程
  被回收后才返回——因此主证据是单次视频调用耗时 ≤ 20s；每轮另以
  psutil 扫描**本进程树**内存活 > 20s 的 ffmpeg 子进程作补充兜底
  （只扫自身进程树，避免误伤系统里无关的 ffmpeg 进程）；
* errorlog ≤ 512 条（环形覆盖语义：长时间运行稳定在 512 封顶，
  经桥 ``get_error_log()`` 读取计数）;
* 无 panic/崩溃：桥调用抛 Python 异常、正常样本生成失败或损坏样本
  意外成功均记失败（Rust 侧 panic 已被 catch_unwind 降级为状态码，
  硬崩溃会直接杀死测试进程，天然 FAIL）；
* 吞吐不回退：末轮较首轮每张耗时上涨 > 50% 记 FAIL。

时长经环境变量 ``FAF_SOAK_MINUTES`` 可调（默认 30 分钟；至少跑 1 轮；
``FAF_BENCH_SMOKE=1`` 且未显式设置时长时降级为约 3 秒冒烟）。
报告落盘 ``.omo/evidence/thumbnail-rust-refactor/task-31-soak-report.json``
（失败同样落盘、verdict=FAIL），供 orchestrator 收集。

语料口径（继承 todo 30 结论）：正常图像夹具全部 ≥16x16——
``min(w,h) < 8`` 的源经原生 JPG 编码路径恒返回 -5，会污染成功统计。
损坏样本为截断 PNG 与确定性垃圾字节；伪扩展名为 .txt 承载合法 PNG
字节（registry 魔数嗅探优先于扩展名，解码成败皆属优雅返回，不判失败）。
正常负载中混入体积最小的 2 个视频样本，保证 T2 ffmpeg 子进程路径被
持续演练（媒体目录缺失时自动退化为纯图像负载并在报告中记录）。

选中断言口径：以 ``config.option.markexpr`` 是否包含 "soak" 判定
（``-m soak`` 显式选中；``-m "not soak"`` 视为未选中）。已知局限：
形如 ``-m "soak and not x"`` 的复合表达式按选中处理。
"""

from __future__ import annotations

import itertools
import json
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import psutil
import pytest

from freeassetfilter.core.native.bridges.rust_thumbnail_bridge import (
    RustThumbnailBridge,
)
from tests.support.data_factories import make_image

# --- 时长与环境变量 ---
#: 冒烟模式开关（FAF_BENCH_SMOKE=1 时启用，与 todo 30 同款解析）。
_SMOKE_ENV: str = os.environ.get("FAF_BENCH_SMOKE", "").strip().lower()
SMOKE_MODE: bool = _SMOKE_ENV not in ("", "0", "false", "no")


def _parse_soak_minutes() -> float:
    """解析 soak 时长（分钟）：FAF_SOAK_MINUTES > 冒烟降级 > 默认 30。

    Returns:
        float: soak 目标时长（分钟），恒为正。
    """
    raw: str = os.environ.get("FAF_SOAK_MINUTES", "").strip()
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    if SMOKE_MODE:
        return SOAK_MINUTES_SMOKE
    return SOAK_MINUTES_DEFAULT


#: 默认 soak 时长（分钟，契约原文）。
SOAK_MINUTES_DEFAULT: float = 30.0
#: 冒烟模式时长（分钟，约 3 秒）。
SOAK_MINUTES_SMOKE: float = 0.05
#: 实际生效的 soak 时长（分钟）。
_SOAK_MINUTES: float = _parse_soak_minutes()
#: pytest-timeout 上限（秒）：4 倍时长 + 300s 余量，下限 900s，
#: 防止全局 timeout=30 / benchmark 目录默认 300s 杀死长跑。
_TIMEOUT_S: int = max(900, int(_SOAK_MINUTES * 60.0 * 4.0) + 300)

pytestmark = [
    pytest.mark.benchmark,
    pytest.mark.rust,
    pytest.mark.soak,
    pytest.mark.timeout(_TIMEOUT_S),
]

# --- 契约阈值（todo 31 原文，不许改） ---
#: 每轮正常负载数。
NORMAL_PER_ROUND: int = 50
#: 每轮损坏样本数。
CORRUPT_PER_ROUND: int = 5
#: 每轮伪扩展名样本数。
FAKE_EXT_PER_ROUND: int = 2
#: 进程 RSS 增长上限（MB）。
RSS_GROWTH_LIMIT_MB: float = 50.0
#: errorlog 环形缓冲上限（条）。
ERRORLOG_CAP: int = 512
#: 单次视频抽帧调用上限（毫秒）——超过即疑似悬挂。
VIDEO_CALL_LIMIT_MS: float = 20000.0
#: ffmpeg 子进程存活年龄阈值（秒）——超过即记悬挂。
HUNG_CHILD_AGE_S: float = 20.0
#: 吞吐回退判定阈值（%，末轮较首轮每张耗时上涨超过该值记 FAIL）。
THROUGHPUT_REGRESSION_PCT: float = 50.0

# --- 样本规模 ---
#: 缩略图目标边长（与 todo 30 同量级）。
THUMB_SIZE: int = 128
#: 正常负载池中的视频样本数（取体积最小的前 N 个控制单轮时长）。
VIDEO_COUNT: int = 2
#: 每轮异常明细最多记录条数（防报告膨胀）。
_MAX_ANOMALIES_PER_ROUND: int = 20

#: 程序化正常图像样本（文件名, PIL 格式, 尺寸）——全部 ≥16x16。
GENERATED_SPECS = [
    ("soak_240x180.jpg", "JPEG", (240, 180)),
    ("soak_320x240.png", "PNG", (320, 240)),
    ("soak_640x480.jpg", "JPEG", (640, 480)),
    ("soak_800x600.png", "PNG", (800, 600)),
    ("soak_1024x768.jpg", "JPEG", (1024, 768)),
    ("soak_512x384.png", "PNG", (512, 384)),
    ("soak_256x256.jpg", "JPEG", (256, 256)),
    ("soak_192x192.png", "PNG", (192, 192)),
]

#: 视频样本目录（与 todo 30 共用）。
MEDIA_DIR: Path = Path(__file__).resolve().parents[1] / "support" / "media"
#: 报告 JSON 落盘路径（orchestrator 收集点）。
REPORT_PATH: Path = (
    Path(__file__).resolve().parents[2]
    / ".omo" / "evidence" / "thumbnail-rust-refactor" / "task-31-soak-report.json"
)


def _soak_explicitly_selected(config: Any) -> bool:
    """判定本用例是否被 ``-m`` 表达式显式选中。

    Args:
        config: pytest 配置对象（``request.config``）。

    Returns:
        bool: markexpr 含 "soak"（且非 "not soak" 语义）返回 True。
    """
    markexpr: str = (getattr(config.option, "markexpr", "") or "").replace(" ", "")
    if not markexpr:
        return False
    if "notsoak" in markexpr:
        return False
    return "soak" in markexpr


def _machine_summary() -> Dict[str, Any]:
    """机器摘要字段（平台 / Python / CPU）。"""
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
    }


def _rss_mb() -> float:
    """当前进程 RSS（MB）。"""
    return psutil.Process().memory_info().rss / (1024.0 * 1024.0)


def _hung_ffmpeg_children() -> List[str]:
    """扫描本进程树内存活超过阈值的 ffmpeg 子进程。

    只扫自身进程树（同步桥调用下子进程应已被 Rust 侧 wait 回收），
    避免误伤系统中与本项目无关的 ffmpeg 进程。

    Returns:
        list[str]: 悬挂进程描述列表（空列表即无悬挂）。
    """
    hung: List[str] = []
    now: float = time.time()
    try:
        children = psutil.Process().children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return hung
    for child in children:
        try:
            name: str = (child.name() or "").lower()
            if "ffmpeg" not in name:
                continue
            age_s: float = now - child.create_time()
            if age_s > HUNG_CHILD_AGE_S:
                hung.append(f"{name}(pid={child.pid}, age={age_s:.0f}s)")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return hung


def _errorlog_len(bridge: RustThumbnailBridge) -> int:
    """经桥读取错误日志环形缓冲的当前条数。

    Args:
        bridge: 已确认可用的原生桥实例。

    Returns:
        int: 条数；JSON 解析失败返回 -1（由调用方记为异常观测）。
    """
    try:
        parsed = json.loads(bridge.get_error_log())
        return len(parsed) if isinstance(parsed, list) else -1
    except Exception:  # noqa: BLE001 - 降级不抛，交由轮次校验记录
        return -1


def _build_corpus(workdir: Path) -> Dict[str, List[Tuple[str, str]]]:
    """构建混合负载语料：(路径, 类别) 列表三组。

    类别语义：image/video 属正常负载（须成功）；corrupt 属损坏样本
    （须优雅失败）；fakeext 属伪扩展名（任意优雅返回皆可）。

    Args:
        workdir: 语料落盘目录（pytest tmp_path_factory 提供）。

    Returns:
        dict: ``{"normal": [...], "corrupt": [...], "fakeext": [...]}``。
    """
    normal: List[Tuple[str, str]] = []
    for name, fmt, size in GENERATED_SPECS:
        normal.append((make_image(workdir / name, fmt=fmt, size=size), "image"))

    videos: List[Path] = sorted(
        (p for p in MEDIA_DIR.iterdir() if p.is_file()),
        key=lambda p: (p.stat().st_size, p.name),
    )[:VIDEO_COUNT]
    for p in videos:
        normal.append((str(p), "video"))

    # 损坏样本基线：一张真实 PNG 的字节（截断用）+ 确定性垃圾字节
    png_bytes: bytes = Path(
        make_image(workdir / "soak_base.png", fmt="PNG", size=(320, 240))
    ).read_bytes()

    corrupt: List[Tuple[str, str]] = [
        (str(workdir / "corrupt_trunc_0.png"), "corrupt"),
        (str(workdir / "corrupt_trunc_1.png"), "corrupt"),
        (str(workdir / "corrupt_trunc_2.png"), "corrupt"),
        (str(workdir / "corrupt_garbage_0.png"), "corrupt"),
        (str(workdir / "corrupt_garbage_1.png"), "corrupt"),
    ]
    (workdir / "corrupt_trunc_0.png").write_bytes(png_bytes[: len(png_bytes) // 2])
    (workdir / "corrupt_trunc_1.png").write_bytes(png_bytes[:64])
    (workdir / "corrupt_trunc_2.png").write_bytes(png_bytes[: len(png_bytes) // 8])
    garbage: bytes = bytes((i * 37 + 11) % 256 for i in range(512))
    (workdir / "corrupt_garbage_0.png").write_bytes(garbage)
    (workdir / "corrupt_garbage_1.png").write_bytes(garbage[:256])

    fakeext: List[Tuple[str, str]] = [
        (str(workdir / "fakeext_0.txt"), "fakeext"),
        (str(workdir / "fakeext_1.txt"), "fakeext"),
    ]
    (workdir / "fakeext_0.txt").write_bytes(png_bytes)
    (workdir / "fakeext_1.txt").write_bytes(png_bytes[: len(png_bytes) // 3])

    return {"normal": normal, "corrupt": corrupt, "fakeext": fakeext}


def _run_round(
    bridge: RustThumbnailBridge, workload: List[Tuple[str, str]]
) -> Dict[str, Any]:
    """执行一轮混合负载并返回轮指标。

    Args:
        bridge: 已确认可用的原生桥实例。
        workload: 本轮 (路径, 类别) 序列。

    Returns:
        dict: 成功/失败计数、正常负载平均耗时、视频最大耗时、异常明细。
    """
    success: int = 0
    failure: int = 0
    normal_ms: List[float] = []
    max_video_ms: float = 0.0
    anomalies: List[str] = []

    for path, kind in workload:
        name: str = Path(path).name
        start: float = time.perf_counter()
        try:
            blob, status = bridge.generate_jpg_with_status(path, THUMB_SIZE, THUMB_SIZE)
        except Exception as exc:  # noqa: BLE001 - 异常即崩溃信号，记失败不中断
            failure += 1
            if len(anomalies) < _MAX_ANOMALIES_PER_ROUND:
                anomalies.append(f"{name}: 桥调用异常 {exc!r}")
            continue
        elapsed_ms: float = (time.perf_counter() - start) * 1000.0

        if kind in ("image", "video"):
            ok = status == 0 and blob is not None and blob[:2] == b"\xff\xd8"
            if not ok:
                failure += 1
                if len(anomalies) < _MAX_ANOMALIES_PER_ROUND:
                    anomalies.append(f"{name}: status={status}（正常负载须成功）")
                continue
            success += 1
            normal_ms.append(elapsed_ms)
            if kind == "video":
                max_video_ms = max(max_video_ms, elapsed_ms)
                if elapsed_ms > VIDEO_CALL_LIMIT_MS:
                    if len(anomalies) < _MAX_ANOMALIES_PER_ROUND:
                        anomalies.append(
                            f"{name}: 抽帧 {elapsed_ms:.0f}ms > "
                            f"{VIDEO_CALL_LIMIT_MS:.0f}ms（疑似悬挂）"
                        )
        elif kind == "corrupt":
            if status == 0 and blob is not None:
                failure += 1
                if len(anomalies) < _MAX_ANOMALIES_PER_ROUND:
                    anomalies.append(f"{name}: 损坏样本意外成功")
            else:
                success += 1
        else:  # fakeext：魔数嗅探优先于扩展名，任意优雅返回皆属预期
            success += 1

    avg_normal_ms: float = sum(normal_ms) / len(normal_ms) if normal_ms else 0.0
    return {
        "success": success,
        "failure": failure,
        "avg_normal_ms": avg_normal_ms,
        "max_video_ms": max_video_ms,
        "anomalies": anomalies,
    }


@pytest.fixture(scope="module")
def soak_selected(request: Any) -> None:
    """soak 显式选中门控：未被 ``-m soak`` 选中时跳过整个模块。

    Args:
        request: pytest 内建 request fixture。
    """
    if not _soak_explicitly_selected(request.config):
        pytest.skip(
            "soak 用例默认跳过：需 -m soak 显式运行"
            "（时长经 FAF_SOAK_MINUTES 可调，默认 30 分钟）"
        )


@pytest.fixture(scope="module")
def bridge(soak_selected: None) -> RustThumbnailBridge:
    """模块级共享原生桥实例；DLL 不可用时跳过整个 soak。

    Args:
        soak_selected: 显式选中门控（依赖以固定跳过顺序）。

    Returns:
        RustThumbnailBridge: 已确认 ``available`` 的桥实例。
    """
    inst = RustThumbnailBridge()
    if not inst.available:
        pytest.skip("thumbnail_generator.dll 不可用，跳过原生缩略图 soak")
    return inst


@pytest.fixture(scope="module")
def soak_corpus(
    bridge: RustThumbnailBridge, tmp_path_factory: Any
) -> Dict[str, List[Tuple[str, str]]]:
    """构建 soak 语料（正常/损坏/伪扩展名三组）。

    Args:
        bridge: 已确认可用的原生桥实例。
        tmp_path_factory: pytest 会话级临时目录工厂。

    Returns:
        dict: 语料分组字典。
    """
    return _build_corpus(tmp_path_factory.mktemp("faf_soak_corpus"))


class TestThumbnailSoak:
    """缩略图混合负载 soak（todo 31 契约主体）。"""

    def test_mixed_load_soak(
        self,
        bridge: RustThumbnailBridge,
        soak_corpus: Dict[str, List[Tuple[str, str]]],
    ) -> None:
        """循环混合负载至目标时长，逐轮校验并落盘报告 JSON。"""
        target_s: float = _SOAK_MINUTES * 60.0
        report: Dict[str, Any] = {
            "schema": "thumbnail-soak-report/v1",
            "mode": "smoke" if SMOKE_MODE or _SOAK_MINUTES != SOAK_MINUTES_DEFAULT else "full",
            "minutes_requested": _SOAK_MINUTES,
            "timeout_bound_s": _TIMEOUT_S,
            "machine": _machine_summary(),
            "thresholds": {
                "rss_growth_limit_mb": RSS_GROWTH_LIMIT_MB,
                "errorlog_cap": ERRORLOG_CAP,
                "video_call_limit_ms": VIDEO_CALL_LIMIT_MS,
                "hung_child_age_s": HUNG_CHILD_AGE_S,
                "throughput_regression_pct": THROUGHPUT_REGRESSION_PCT,
            },
            "corpus": {
                "normal_pool": len(soak_corpus["normal"]),
                "normal_per_round": NORMAL_PER_ROUND,
                "corrupt_per_round": CORRUPT_PER_ROUND,
                "fakeext_per_round": FAKE_EXT_PER_ROUND,
                "videos_in_pool": sum(
                    1 for _, kind in soak_corpus["normal"] if kind == "video"
                ),
            },
            "start": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

        # 预热轮：DLL 惰性初始化 / rayon 注册表 / ffmpeg OnceLock /
        # 首次解码冷缓存，不计入统计；同时快速验证正常语料可用性。
        for path, kind in soak_corpus["normal"]:
            blob, status = bridge.generate_jpg_with_status(path, THUMB_SIZE, THUMB_SIZE)
            assert status == 0 and blob is not None, (
                f"预热失败：{Path(path).name} status={status}（正常语料不可用）"
            )
        bridge.clear_error_log()

        rss_start_mb: float = _rss_mb()
        start_mono: float = time.perf_counter()
        rounds: List[Dict[str, Any]] = []
        fail_rounds: Dict[str, int] = {}
        total_success: int = 0
        total_failure: int = 0
        errorlog_peak: int = 0
        hung_seen: List[str] = []

        def note(category: str, round_idx: int) -> None:
            """记录某类违例的首次出现轮次（同类只记一次防膨胀）。"""
            fail_rounds.setdefault(category, round_idx)

        try:
            normal_cycle = itertools.cycle(soak_corpus["normal"])
            corrupt_cycle = itertools.cycle(soak_corpus["corrupt"])
            fake_cycle = itertools.cycle(soak_corpus["fakeext"])

            round_idx: int = 0
            while True:
                round_idx += 1
                workload: List[Tuple[str, str]] = (
                    list(itertools.islice(normal_cycle, NORMAL_PER_ROUND))
                    + list(itertools.islice(corrupt_cycle, CORRUPT_PER_ROUND))
                    + list(itertools.islice(fake_cycle, FAKE_EXT_PER_ROUND))
                )
                metrics: Dict[str, Any] = _run_round(bridge, workload)

                rss_now_mb: float = _rss_mb()
                log_len: int = _errorlog_len(bridge)
                hung: List[str] = _hung_ffmpeg_children()
                elapsed_s: float = time.perf_counter() - start_mono

                total_success += metrics["success"]
                total_failure += metrics["failure"]
                errorlog_peak = max(errorlog_peak, log_len)
                if hung:
                    hung_seen.extend(hung)

                if metrics["failure"] > 0:
                    note("call_failures", round_idx)
                if rss_now_mb - rss_start_mb >= RSS_GROWTH_LIMIT_MB:
                    note("rss_growth", round_idx)
                if log_len > ERRORLOG_CAP or log_len < 0:
                    note("errorlog_overflow", round_idx)
                if hung:
                    note("hung_ffmpeg", round_idx)
                if (
                    metrics["max_video_ms"] > VIDEO_CALL_LIMIT_MS
                ):
                    note("video_call_timeout", round_idx)

                rounds.append(
                    {
                        "round": round_idx,
                        "elapsed_s": round(elapsed_s, 2),
                        "avg_normal_ms": round(metrics["avg_normal_ms"], 3),
                        "max_video_ms": round(metrics["max_video_ms"], 1),
                        "rss_mb": round(rss_now_mb, 2),
                        "errorlog_len": log_len,
                        "success": metrics["success"],
                        "failure": metrics["failure"],
                    }
                )
                if metrics["anomalies"]:
                    rounds[-1]["anomalies"] = metrics["anomalies"]

                verbose: bool = _SOAK_MINUTES <= 1.0 or round_idx % 25 == 0
                if verbose:
                    print(
                        f"\n[soak] round {round_idx} | {elapsed_s:.0f}s/"
                        f"{target_s:.0f}s | RSS {rss_now_mb:.1f}MB | "
                        f"errorlog {log_len} | 平均 {metrics['avg_normal_ms']:.1f}ms",
                        flush=True,
                    )

                if elapsed_s >= target_s:
                    break
        finally:
            end_mono: float = time.perf_counter()
            rss_end_mb: float = _rss_mb()
            rss_growth_mb: float = rss_end_mb - rss_start_mb
            first_avg: float = rounds[0]["avg_normal_ms"] if rounds else 0.0
            last_avg: float = rounds[-1]["avg_normal_ms"] if rounds else 0.0
            regression_pct: float = (
                (last_avg - first_avg) / first_avg * 100.0 if first_avg > 0 else 0.0
            )
            if regression_pct > THROUGHPUT_REGRESSION_PCT:
                fail_rounds.setdefault("throughput_regression", len(rounds))

            violations: List[str] = [
                f"{cat}(首次出现于第 {rnd} 轮)" for cat, rnd in sorted(fail_rounds.items())
            ]
            if hung_seen:
                violations.append(f"悬挂进程: {', '.join(hung_seen[:5])}")

            report.update(
                {
                    "end": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "duration_actual_s": round(end_mono - start_mono, 2),
                    "total_rounds": len(rounds),
                    "rss_start_mb": round(rss_start_mb, 2),
                    "rss_end_mb": round(rss_end_mb, 2),
                    "rss_growth_mb": round(rss_growth_mb, 2),
                    "errorlog_peak": errorlog_peak,
                    "success_count": total_success,
                    "failure_count": total_failure,
                    "throughput": {
                        "first_round_avg_ms": round(first_avg, 3),
                        "last_round_avg_ms": round(last_avg, 3),
                        "regression_pct": round(regression_pct, 2),
                    },
                    "hung_ffmpeg_found": bool(hung_seen),
                    "violations": violations,
                    "verdict": "FAIL" if violations else "PASS",
                    "rounds": rounds,
                }
            )
            REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            REPORT_PATH.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                f"\n[soak] 完成 {len(rounds)} 轮 / "
                f"{report['duration_actual_s']:.0f}s | verdict={report['verdict']} | "
                f"报告: {REPORT_PATH}",
                flush=True,
            )

        assert not fail_rounds and not hung_seen, (
            f"soak 校验失败: {'; '.join(report['violations'])}"
        )
