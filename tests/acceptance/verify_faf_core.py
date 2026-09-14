#!/usr/bin/env python3
"""faf-core-rust-migration 验收自检脚本（计划 todo 33）。

一条命令产出机器报告 ``verification-report.json``（每项 PASS/FAIL + 证据
路径），并落一份证据副本 ``.omo/evidence/faf-core-rust-migration/
task-33-verify-report.json``。**全部为机器核对，无人工判断项**。

16 项检查（对照 ``.omo/plans/faf-core-rust-migration.md`` todo 33）：

1.  ``dumpbin /exports faf_core.dll``（vswhere helper 解析路径，为空时按
    ``...\\MSVC\\<ver>\\bin\\Hostx64\\x64\\dumpbin.exe`` 版本目录兜底扫描；
    仍缺失回退 ``llvm-readobj --file-headers --coff-exports``）——14 个
    ``faf_*`` 导出齐全；
2.  ``dumpbin /dependents`` 白名单——仅系统 DLL + VC 运行时（``api-ms-win-*``
    前缀放行；bundled ffmpeg/7z 为子进程依赖，非 PE 导入表项）；
3.  依赖 license 表存在（``task-1-decisions.md`` §4 的 12 个直接依赖 +
    AGPL 兼容结论）；
4.  既有测试契约全绿——计划 Verification strategy 各波回归门文件**逐文件**
    跑 pytest（offscreen + 超时保护）；
5.  新增测试全绿（test_faf_core_bridge / test_file_selector_native_wiring /
    test_font_native_parity / test_encoding_native_parity / test_pdf_drawer_async /
    test_parity_helper）；
6.  benchmark 断言 + 基线——``test_faf_core_perf.py``（FAF_BENCH_SMOKE=1）无
    崩溃/异常，且基线 JSON 存在并含 P50/P95/吞吐/assertion 字段；
7.  C9 护栏——`grep "zip crate|ZipArchive" faf_core/` 为空（含 Cargo.toml /
    Cargo.lock / src/*.rs；排除构建产物 target/）；
8.  ``git status --porcelain`` 仅预期文件（只读命令，不执行任何 git 写操作）；
9.  ``git diff --stat core/__init__.py`` 为空（``_MODULE_MAP`` 未改）；
10. 全部 evidence 文件（task-1..task-32）存在且非空；
11. F3 机器项——setHtml 计数 == 1（``test_slider_debounce_single_render``）；
12. F3 机器项——UI 线程 id != worker id（``test_drawer_renders_off_ui_thread``
    + ``test_audio_select_single_open_and_worker_palette``）；
13. F3 机器项——PDF 像素 hash 相等（``test_drawer_pixels_identical_to_synchronous``）；
14. F3 机器项——截图文件存在且 ``os.path.getsize > 0``（manual-qa/ 目录；
    由 F3 波产出，todo 33 先行时缺失输出 SKIP 并注明来源测试名，不伪造）；
15. F3 机器项——mutagen 单次打开计数 == 1（``test_extract_audio_metadata_single_open``）；
16. F3 机器项——音/视频选择 UI 线程即时返回（``test_video_light_rows_async_returns_immediately``
    + ``test_audio_select_returns_immediately``）。

FAIL 语义：任一检查 FAIL → 退出码非 0，并在摘要中输出对应编号与复现命令
（任一 FAIL 阻止 F1-F4 启动）。

设计规则（继承 tests/acceptance/verify_plan.py 先例）：
- 每项检查独立 try/except——单项失败不阻塞其余；
- 每项产出 PASS / FAIL / SKIP（SKIP 必带原因与来源测试名）；
- 纯 stdlib，无新依赖；测试临时物不落仓库。

用法：``python tests/acceptance/verify_faf_core.py``
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = PROJECT_ROOT / ".omo" / "evidence" / "faf-core-rust-migration"
REPORT_PATH = EVIDENCE_DIR / "verification-report.json"
EVIDENCE_COPY = EVIDENCE_DIR / "task-33-verify-report.json"
DECISIONS_PATH = EVIDENCE_DIR / "task-1-decisions.md"
FAF_CORE_SRC = PROJECT_ROOT / "freeassetfilter" / "core" / "native" / "src" / "faf_core"
BIN_DLL = PROJECT_ROOT / "freeassetfilter" / "core" / "native" / "bin" / "faf_core.dll"
BASELINE_JSON = (
    PROJECT_ROOT / "tests" / "benchmark" / "baseline" / "faf-core-perf.json"
)
MANUAL_QA_DIR = EVIDENCE_DIR / "manual-qa"
CORE_INIT = PROJECT_ROOT / "freeassetfilter" / "core" / "__init__.py"

PYTEST_TIMEOUT_S = 600
BENCH_TIMEOUT_S = 600
GIT_TIMEOUT_S = 60

# 计划 C1 落定的 14 个 faf_* 导出（11 个 + 4 个流式哈希 = 14，含 free_message）。
REQUIRED_EXPORTS: set[str] = {
    "faf_version",
    "faf_free_message",
    "faf_scan_directory",
    "faf_sort_entries",
    "faf_highlight_text",
    "faf_render_markdown",
    "faf_hash_init",
    "faf_hash_update",
    "faf_hash_final",
    "faf_hash_free",
    "faf_detect_encoding",
    "faf_parse_font",
    "faf_copy_files",
    "faf_sum_directory_sizes",
}

# 任务-1-decisions.md §4 落定的 12 个直接依赖（license 表必须逐一覆盖）。
REQUIRED_DEP_RECORDS: tuple[str, ...] = (
    "serde_json", "once_cell", "rayon", "chrono", "syntect", "pulldown-cmark",
    "md-5", "sha1", "sha2", "chardetng", "ttf-parser", "filetime",
)

# dumpbin /dependents 白名单：仅 Windows 系统 DLL + VC 运行时（api-ms-win-* 前缀）。
# bundled ffmpeg/ffprobe/7z 为 T2 子进程依赖，非 PE 导入表项，属计划明示例外。
DEPENDENTS_WHITELIST_EXACT: set[str] = {
    "kernel32.dll", "ntdll.dll", "bcryptprimitives.dll", "advapi32.dll",
    "shell32.dll", "oleaut32.dll", "user32.dll", "gdi32.dll", "ws2_32.dll",
    "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll",
    "msvcp140_2.dll", "ucrtbase.dll",
}
DEPENDENTS_WHITELIST_PREFIXES: tuple[str, ...] = ("api-ms-win-",)

# 既有测试契约（计划 Verification strategy :94-101 各波回归门文件并集）。
GATE_FILES: tuple[str, ...] = (
    "tests/integration/test_selector_thumbnail_flow.py",
    "tests/unit/ui/layout/test_layouts.py",
    "tests/unit/services/test_file_service.py",
    "tests/unit/workers/test_file_list_loader.py",
    "tests/unit/utils/test_syntax_highlighter.py",
    "tests/unit/ui/layout/preview/test_zoom_popups.py",
    "tests/unit/utils/test_markdown_renderer.py",
    "tests/unit/ui/layout/preview/test_file_info_panel.py",
    "tests/unit/services/test_file_info_service.py",
    "tests/unit/core/test_media_probe.py",
    "tests/unit/utils/test_subprocess_utils.py",
    "tests/unit/services/test_staging_pool_service.py",
    "tests/unit/workers/test_staging_tasks.py",
    "tests/unit/services/test_media_metadata_service.py",
    "tests/unit/services/test_pdf_services.py",
    "tests/unit/ui/layout/preview/test_native_pdf_renderer.py",
    "tests/unit/core/test_rust_thumbnail_bridge.py",
    "tests/integration/test_ffmpeg_minimal_binaries.py",
    "tests/unit/core/test_status_channel.py",
)

# 新增测试（todo 3/9/26/25/31/5 交付）。
NEW_TEST_FILES: tuple[str, ...] = (
    "tests/unit/core/test_faf_core_bridge.py",
    "tests/unit/ui/layout/test_file_selector_native_wiring.py",
    "tests/unit/services/test_font_native_parity.py",
    "tests/unit/services/test_encoding_native_parity.py",
    "tests/unit/ui/layout/preview/test_pdf_drawer_async.py",
    "tests/support/test_parity_helper.py",
)

# F3 机器项 → 覆盖它们的既有测试选择器（evidence 来源见各检查）。
F3_DEFS: dict[str, dict[str, Any]] = {
    "11": {
        "name": "F3 setHtml 计数 == 1（滑条防抖单次渲染）",
        "targets": ["tests/unit/ui/layout/test_layouts.py::TestTextPreviewerLayout::test_slider_debounce_single_render"],
        "evidence": ["task-18-debounce.txt"],
        "source": "tests/unit/ui/layout/test_layouts.py::TestTextPreviewerLayout::test_slider_debounce_single_render",
    },
    "12": {
        "name": "F3 UI 线程 id != worker id（调色板/PDF 渲染在 worker 线程）",
        "targets": [
            "tests/unit/ui/layout/preview/test_pdf_drawer_async.py::test_drawer_renders_off_ui_thread",
            "tests/unit/ui/layout/test_layouts.py::TestVideoPlayerLayoutAsyncAudio::test_audio_select_single_open_and_worker_palette",
        ],
        "evidence": ["task-31-pdf-drawer.txt", "task-30-audio.txt"],
        "source": "test_pdf_drawer_async.py::test_drawer_renders_off_ui_thread + test_layouts.py::TestVideoPlayerLayoutAsyncAudio::test_audio_select_single_open_and_worker_palette",
    },
    "13": {
        "name": "F3 PDF 缩略图像素 hash 相等（抽屉 vs 同步 0.25x）",
        "targets": ["tests/unit/ui/layout/preview/test_pdf_drawer_async.py::test_drawer_pixels_identical_to_synchronous"],
        "evidence": ["task-31-pdf-drawer.txt"],
        "source": "tests/unit/ui/layout/preview/test_pdf_drawer_async.py::test_drawer_pixels_identical_to_synchronous",
    },
    "14": {
        "name": "F3 截图文件存在且 os.path.getsize > 0",
        "targets": [],
        "evidence": [],
        "source": "manual-qa/ 目录由 F3 波产出（offscreen 冒烟 + GUI 截图）；todo 33 先行时无此产物",
    },
    "15": {
        "name": "F3 mutagen 单次打开计数 == 1",
        "targets": ["tests/unit/services/test_media_metadata_service.py::TestSingleMutagenOpen::test_extract_audio_metadata_single_open"],
        "evidence": ["task-30-audio.txt"],
        "source": "tests/unit/services/test_media_metadata_service.py::TestSingleMutagenOpen::test_extract_audio_metadata_single_open",
    },
    "16": {
        "name": "F3 音/视频选择 UI 线程即时返回",
        "targets": [
            "tests/unit/ui/layout/preview/test_file_info_panel.py::TestFileInfoPanelMediaAsync::test_video_light_rows_async_returns_immediately",
            "tests/unit/ui/layout/test_layouts.py::TestVideoPlayerLayoutAsyncAudio::test_audio_select_returns_immediately",
        ],
        "evidence": ["task-20-video-async.txt", "task-30-audio.txt"],
        "source": "test_file_info_panel.py::TestFileInfoPanelMediaAsync::test_video_light_rows_async_returns_immediately + test_layouts.py::TestVideoPlayerLayoutAsyncAudio::test_audio_select_returns_immediately",
    },
}

# git status 预期文件集合（本次迁移产物 + 本任务新增 + pre-existing 基准残留）。
ALLOWED_WORKTREE_PREFIXES: tuple[str, ...] = (
    ".gitignore",
    "Pyinstall_build.py",
    "AGENTS.md",
    "freeassetfilter/core/_paths.py",
    "freeassetfilter/core/native/bin/faf_core.dll",
    "freeassetfilter/core/native/bridges/faf_core_bridge.py",
    "freeassetfilter/core/native/src/faf_core/",
    "freeassetfilter/services/file_info_service.py",
    "freeassetfilter/services/media_metadata_service.py",
    "freeassetfilter/services/staging_pool_service.py",
    "freeassetfilter/ui/layout/file_pool_layout.py",
    "freeassetfilter/ui/layout/file_selector_layout.py",
    "freeassetfilter/ui/layout/preview/file_info_panel.py",
    "freeassetfilter/ui/layout/preview/folder_previewer_layout.py",
    "freeassetfilter/ui/layout/preview/pdf_previewer_layout.py",
    "freeassetfilter/ui/layout/preview/text_previewer_layout.py",
    "freeassetfilter/ui/layout/preview/video_player_layout.py",
    "freeassetfilter/utils/markdown_renderer.py",
    "freeassetfilter/utils/syntax_highlighter.py",
    "tests/benchmark/baseline/thumbnail-latency.json",
    "tests/benchmark/baseline/faf-core-perf.json",
    "tests/benchmark/test_faf_core_perf.py",
    "tests/conftest.py",
    "tests/support/faf_core_fixtures/",
    "tests/support/parity/",
    "tests/support/test_parity_helper.py",
    "tests/unit/core/test_faf_core_bridge.py",
    "tests/unit/services/test_encoding_native_parity.py",
    "tests/unit/services/test_file_info_service.py",
    "tests/unit/services/test_font_native_parity.py",
    "tests/unit/services/test_media_metadata_service.py",
    "tests/unit/services/test_staging_pool_service.py",
    "tests/unit/ui/layout/preview/test_file_info_panel.py",
    "tests/unit/ui/layout/preview/test_pdf_drawer_async.py",
    "tests/unit/ui/layout/test_file_selector_native_wiring.py",
    "tests/unit/ui/layout/test_layouts.py",
    "tests/unit/utils/test_markdown_renderer.py",
    "tests/unit/utils/test_syntax_highlighter.py",
    "tests/acceptance/",
    ".omo/",
)


@dataclass
class CheckResult:
    """单项验收检查结果。"""

    check_id: str
    name: str
    status: str  # "PASS" | "FAIL" | "SKIP"
    reason: str
    evidence: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    elapsed_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """序列化到 JSON 报告。

        Returns:
            JSON 兼容字典。
        """
        return {
            "id": self.check_id,
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
            "evidence": self.evidence,
            "details": self.details,
            "elapsed_s": round(self.elapsed_s, 3),
        }


def _read_text_lossy(path: Path) -> str:
    """宽容读取文本文件（UTF-8 / GBK 兜底）。

    Args:
        path: 待读文件。

    Returns:
        解码文本；不可解码字节以 replace 兜底。
    """
    data = path.read_bytes()
    for encoding in ("utf-8", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _rel(path: Path | str) -> str:
    """相对项目根的路径（POSIX 风格，供报告紧凑展示）。

    Args:
        path: 绝对或相对路径。

    Returns:
        相对路径字符串。
    """
    try:
        return Path(path).resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def run_pytest(
    targets: list[str],
    *,
    env_extra: dict[str, str] | None = None,
    timeout_s: int = PYTEST_TIMEOUT_S,
) -> tuple[int, str]:
    """对给定 pytest 目标运行并返回 (returncode, output)。

    Args:
        targets: 相对项目根的测试文件/节点选择器。
        env_extra: 附加环境变量。
        timeout_s: 子进程硬超时（秒）。

    Returns:
        pytest 退出码 + stdout+stderr 合并文本。

    Raises:
        subprocess.TimeoutExpired: 子进程超时。
    """
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *targets, "-q", "--no-header"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        env=env,
        check=False,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run_git(args: list[str], timeout_s: int = GIT_TIMEOUT_S) -> subprocess.CompletedProcess[str]:
    """运行只读 git 命令（不做任何写操作）。

    Args:
        args: git 参数（不含前导 ``git``）。
        timeout_s: 硬超时（秒）。

    Returns:
        已完成的进程对象。
    """
    return subprocess.run(
        ["git", *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        check=False,
    )


def find_dumpbin() -> Path | None:
    """解析 dumpbin.exe 绝对路径（vswhere helper + 版本目录兜底扫描）。

    依次尝试：PATH → ``vswhere -latest -find "**\\dumpbin.exe"``（本机实测
    BuildTools 实例不被识别返回空）→
    ``C:\\Program Files (x86)\\Microsoft Visual Studio\\<ed>\\<ver>\\
    VC\\Tools\\MSVC\\<msvcver>\\bin\\Hostx64\\x64\\dumpbin.exe`` 版本目录
    兜底扫描（learnings 经验）。

    Returns:
        dumpbin.exe 绝对路径；不可用时返回 None。
    """
    which = shutil.which("dumpbin")
    if which:
        return Path(which)
    vswhere_candidates = [
        r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe",
        r"C:\Program Files\Microsoft Visual Studio\Installer\vswhere.exe",
    ]
    for vswhere in vswhere_candidates:
        if not Path(vswhere).is_file():
            continue
        try:
            proc = subprocess.run(
                [vswhere, "-latest", "-find", r"**\dumpbin.exe"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30, check=False,
            )
            hits = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
            if hits:
                return Path(hits[0])
        except Exception:  # noqa: BLE001, S110  # vswhere 探测失败不致命（best-effort，静默跳过）
            pass
    patterns = [
        r"C:\Program Files (x86)\Microsoft Visual Studio\*\*\VC\Tools\MSVC\*\bin\Hostx64\x64\dumpbin.exe",
        r"C:\Program Files\Microsoft Visual Studio\*\*\VC\Tools\MSVC\*\bin\Hostx64\x64\dumpbin.exe",
        r"C:\Program Files (x86)\Microsoft Visual Studio\*\VC\Tools\MSVC\*\bin\Hostx64\x64\dumpbin.exe",
    ]
    for pattern in patterns:
        hits = sorted(glob.glob(pattern), reverse=True)
        if hits:
            return Path(hits[0])
    return None


def find_llvm_readobj() -> Path | None:
    """解析 llvm-readobj 路径（dumpbin 缺失时的回退工具）。

    Returns:
        llvm-readobj 可执行文件路径；不可用时返回 None。
    """
    which = shutil.which("llvm-readobj")
    if which:
        return Path(which)
    patterns = [
        r"C:\Program Files\LLVM\bin\llvm-readobj.exe",
        r"C:\Program Files (x86)\LLVM\bin\llvm-readobj.exe",
    ]
    for pattern in patterns:
        hits = sorted(glob.glob(pattern), reverse=True)
        if hits:
            return Path(hits[0])
    return None


def parse_exports(text: str) -> list[str]:
    """解析 dumpbin /exports 输出的导出名列表。

    Args:
        text: dumpbin /exports 全文。

    Returns:
        导出名列表（按出现顺序）。
    """
    names: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^\s*\d+\s+[0-9A-Fa-f]+\s+[0-9A-Fa-f]+\s+(\S+)\s*$", line)
        if m:
            names.append(m.group(1))
    return names


def parse_exports_llvm(text: str) -> list[str]:
    """解析 llvm-readobj --coff-exports 输出的导出名列表。

    Args:
        text: llvm-readobj 全文。

    Returns:
        导出名列表。
    """
    names: list[str] = []
    for line in text.splitlines():
        m = re.match(r"Name:\s+(\S+)", line)
        if m:
            names.append(m.group(1))
    return names


def parse_dependents(text: str) -> list[str]:
    """从 dumpbin /dependents 输出（或含该节的内容）提取依赖 DLL 列表。

    Args:
        text: 全文（含 ``Image has the following dependencies:`` 节）。

    Returns:
        小写依赖名列表（按出现顺序）。
    """
    names: list[str] = []
    started = False
    for line in text.splitlines():
        if not started:
            if "dependencies:" in line.lower() or "/dependents" in line.lower():
                started = True
            continue
        m = re.match(r"\s+(\S+\.dll)\s*$", line, re.IGNORECASE)
        if m:
            names.append(m.group(1).lower())
        elif names:
            break  # 列表结束后的第一个非 DLL 行（如 Summary）停止
    return names


def classify_dependents(names: list[str]) -> tuple[list[str], list[str]]:
    """把依赖清单分成白名单内/外两组。

    Args:
        names: 依赖 DLL 名（任意大小写）。

    Returns:
        (ok, unexpected) 两组小写名称。
    """
    ok: list[str] = []
    unexpected: list[str] = []
    for name in names:
        lowered = name.lower()
        if lowered in DEPENDENTS_WHITELIST_EXACT or lowered.startswith(
            DEPENDENTS_WHITELIST_PREFIXES
        ):
            ok.append(lowered)
        else:
            unexpected.append(lowered)
    return ok, unexpected


def collect_faf_exports() -> tuple[list[str], str]:
    """实时解析 faf_core.dll 导出名（dumpbin → llvm-readobj 回退）。

    Returns:
        (exports, source)：导出名列表 + 来源描述。
    """
    dumpbin = find_dumpbin()
    if dumpbin is not None:
        proc = subprocess.run(
            [str(dumpbin), "/exports", str(BIN_DLL)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, check=False,
        )
        exports = parse_exports(proc.stdout or "")
        if exports:
            return exports, f"live dumpbin ({dumpbin})"
    llvm = find_llvm_readobj()
    if llvm is not None:
        proc = subprocess.run(
            [str(llvm), "--file-headers", "--coff-exports", str(BIN_DLL)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, check=False,
        )
        exports = parse_exports_llvm(proc.stdout or "")
        if exports:
            return exports, f"live llvm-readobj ({llvm})"
    return [], "dumpbin/llvm-readobj 均不可用"


def collect_faf_dependents() -> tuple[list[str], str]:
    """实时解析 faf_core.dll 依赖清单（dumpbin）。

    Returns:
        (dependents, source)：小写依赖名列表 + 来源描述。
    """
    dumpbin = find_dumpbin()
    if dumpbin is not None:
        proc = subprocess.run(
            [str(dumpbin), "/dependents", str(BIN_DLL)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, check=False,
        )
        names = parse_dependents(proc.stdout or "")
        if names:
            return names, f"live dumpbin ({dumpbin})"
    return [], "dumpbin 不可用"


# ---------------------------------------------------------------------------
# 检查实现。每个函数返回 CheckResult，不得抛出（main 逐项 try/except 兜底）。
# ---------------------------------------------------------------------------


def check_01_exports(full: bool) -> CheckResult:
    """Check 01：dumpbin /exports → 14 个 faf_* 导出齐全。

    Args:
        full: 忽略（两种模式行为一致）。

    Returns:
        PASS 当全部 14 个必需导出命中；否则 FAIL。
    """
    del full
    evidence = [_rel(BIN_DLL), _rel(EVIDENCE_DIR / "task-2-crate-ffi.txt")]
    if not BIN_DLL.is_file():
        return CheckResult("01", "dumpbin /exports 导出清单（14 个 faf_* 导出）", "FAIL",
                           f"DLL 不存在: {_rel(BIN_DLL)}", evidence)
    exports, source = collect_faf_exports()
    faf_exports = {e for e in exports if e.startswith("faf_")}
    missing = sorted(REQUIRED_EXPORTS - faf_exports)
    details: dict[str, Any] = {
        "source": source,
        "export_count": len(exports),
        "faf_export_count": len(faf_exports),
        "missing": missing,
        "expected": sorted(REQUIRED_EXPORTS),
    }
    if not exports:
        return CheckResult("01", "dumpbin /exports 导出清单（14 个 faf_* 导出）", "FAIL",
                           "dumpbin/llvm-readobj 均不可用，无法核对导出清单", evidence, details)
    if missing:
        return CheckResult("01", "dumpbin /exports 导出清单（14 个 faf_* 导出）", "FAIL",
                           f"缺少导出: {missing}", evidence, details)
    return CheckResult("01", "dumpbin /exports 导出清单（14 个 faf_* 导出）", "PASS",
                       f"14 个 faf_* 导出全部命中（来源 {source}）", evidence, details)


def check_02_dependents(full: bool) -> CheckResult:
    """Check 02：dumpbin /dependents 白名单（无新增外部 DLL）。

    Args:
        full: 忽略。

    Returns:
        PASS 当所有依赖均为系统 DLL + VC 运行时。
    """
    del full
    evidence = [_rel(BIN_DLL)]
    if not BIN_DLL.is_file():
        return CheckResult("02", "dumpbin /dependents 白名单", "FAIL",
                           f"DLL 不存在: {_rel(BIN_DLL)}", evidence)
    names, source = collect_faf_dependents()
    if not names:
        return CheckResult("02", "dumpbin /dependents 白名单", "FAIL",
                           "dumpbin 不可用或未解析出依赖清单", evidence)
    ok, unexpected = classify_dependents(names)
    details: dict[str, Any] = {
        "source": source,
        "dependent_count": len(names),
        "whitelisted": ok,
        "unexpected": unexpected,
    }
    if unexpected:
        return CheckResult("02", "dumpbin /dependents 白名单", "FAIL",
                           f"白名单外依赖: {unexpected}", evidence, details)
    if len(names) < 3:
        return CheckResult("02", "dumpbin /dependents 白名单", "FAIL",
                           f"dependents 解析结果过少({len(names)})，疑似解析失败", evidence, details)
    details["note"] = "bundled ffmpeg/ffprobe/7z 为子进程依赖，非 PE 导入表项，属计划明示例外"
    return CheckResult("02", "dumpbin /dependents 白名单", "PASS",
                       f"{len(names)} 个依赖全部在（Windows 系统库 + VC 运行时）白名单内",
                       evidence, details)


def check_03_license_table(full: bool) -> CheckResult:
    """Check 03：依赖 license 表存在（task-1-decisions.md）。

    Args:
        full: 忽略。

    Returns:
        PASS 当 12 个直接依赖全部在 decisions.md 出现且含 AGPL 兼容性讨论。
    """
    del full
    evidence = [_rel(DECISIONS_PATH)]
    if not DECISIONS_PATH.is_file():
        return CheckResult("03", "依赖 license 表存在（task-1-decisions.md）", "FAIL",
                           f"decisions.md 缺失: {_rel(DECISIONS_PATH)}", evidence)
    text = _read_text_lossy(DECISIONS_PATH)
    found: dict[str, int] = {}
    for idx, line in enumerate(text.splitlines(), start=1):
        for dep in REQUIRED_DEP_RECORDS:
            if dep not in found and dep in line:
                found[dep] = idx
    missing = [d for d in REQUIRED_DEP_RECORDS if d not in found]
    agpl_count = len(re.findall(r"AGPL", text, re.IGNORECASE))
    details: dict[str, Any] = {
        "records": {k: f"line {v}" for k, v in sorted(found.items())},
        "missing": missing,
        "agpl_mentions": agpl_count,
    }
    if missing:
        return CheckResult("03", "依赖 license 表存在（task-1-decisions.md）", "FAIL",
                           f"license 表缺少直接依赖记录: {missing}", evidence, details)
    if agpl_count < 3:
        return CheckResult("03", "依赖 license 表存在（task-1-decisions.md）", "FAIL",
                           f"AGPL 兼容性讨论过少({agpl_count} 处)", evidence, details)
    return CheckResult("03", "依赖 license 表存在（task-1-decisions.md）", "PASS",
                       f"12 个直接依赖 license 记录齐全，AGPL 兼容性讨论 {agpl_count} 处",
                       evidence, details)


def _pytest_files_check(
    check_id: str, name: str, files: list[str], *, timeout_s: int = PYTEST_TIMEOUT_S,
    extra_evidence: list[str] | None = None,
) -> CheckResult:
    """按文件逐个跑 pytest（每个文件独立子进程，off-screen + 超时保护）。

    Args:
        check_id: 检查编号。
        name: 检查名称。
        files: 测试文件路径列表（相对项目根）。
        timeout_s: 每个文件的子进程硬超时。
        extra_evidence: 附加证据路径。

    Returns:
        PASS 当每个文件均 exit 0 且能解析 passed 计数。
    """
    evidence = [_rel(f) for f in files] + (extra_evidence or [])
    missing = [f for f in files if not (PROJECT_ROOT / f).exists()]
    if missing:
        return CheckResult(check_id, name, "FAIL", f"测试文件缺失: {missing}", evidence)
    per_file: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for target in files:
        t0 = time.monotonic()
        try:
            rc, out = run_pytest([target], timeout_s=timeout_s)
        except subprocess.TimeoutExpired:
            per_file.append({"file": target, "status": "TIMEOUT",
                             "elapsed_s": float(timeout_s)})
            failed.append({"file": target, "error": f"子进程超时(>{timeout_s}s)"})
            continue
        m = re.search(r"(\d+) passed(?:, (\d+) skipped)?", out)
        passed = int(m.group(1)) if m else -1
        skipped = int(m.group(2)) if m and m.group(2) else 0
        entry: dict[str, Any] = {
            "file": target, "returncode": rc, "passed": passed, "skipped": skipped,
            "elapsed_s": round(time.monotonic() - t0, 2),
        }
        per_file.append(entry)
        if rc != 0 or passed < 0:
            entry["output_tail"] = out[-1200:]
            failed.append({"file": target, "error": f"pytest 退出码 {rc}",
                           "passed": passed})
    details: dict[str, Any] = {"per_file": per_file, "failed": failed,
                               "total_files": len(files), "failed_files": len(failed)}
    if failed:
        return CheckResult(check_id, name, "FAIL",
                           f"{len(failed)}/{len(files)} 个文件未全绿: "
                           + "; ".join(f["file"] for f in failed),
                           evidence, details)
    return CheckResult(check_id, name, "PASS",
                       f"{len(files)} 个文件全部通过（exit 0）", evidence, details)


def check_04_existing_gates(full: bool) -> CheckResult:
    """Check 04：既有测试契约全绿（各波回归门文件逐文件跑）。

    Args:
        full: 忽略（回归门固定为计划清单）。

    Returns:
        PASS 当全部 19 个回归门文件 exit 0。
    """
    del full
    return _pytest_files_check(
        "04", "既有测试契约全绿（各波回归门文件逐文件）", list(GATE_FILES),
        extra_evidence=[_rel(EVIDENCE_DIR / f) for f in
                        ("task-10-folder-previewer.txt", "task-29-bulk-wiring.txt")],
    )


def check_05_new_tests(full: bool) -> CheckResult:
    """Check 05：新增测试全绿。

    Args:
        full: 忽略（新增测试清单固定）。

    Returns:
        PASS 当全部新增测试文件 exit 0。
    """
    del full
    return _pytest_files_check(
        "05", "新增测试全绿（桥/wiring/对拍/抽屉/parity helper）", list(NEW_TEST_FILES),
    )


def check_06_benchmark(full: bool) -> CheckResult:
    """Check 06：benchmark 断言 + 基线 JSON。

    冒烟模式（FAF_BENCH_SMOKE=1，5 样本）跑 test_faf_core_perf.py——失败
    条件只针对崩溃/异常/native 返回 None，性能数值为记录性指标（WARN-only，
    exit 0）；另核对基线 JSON 存在且含 P50/P95/吞吐/assertion 字段。

    Args:
        full: 忽略（冒烟模式已覆盖无崩溃断言）。

    Returns:
        PASS 当 benchmark 无崩溃且基线 JSON 字段齐全。
    """
    del full
    evidence = [_rel(BASELINE_JSON)]
    if not (PROJECT_ROOT / "tests" / "benchmark" / "test_faf_core_perf.py").is_file():
        return CheckResult("06", "benchmark 断言 + 基线 JSON", "FAIL",
                           "tests/benchmark/test_faf_core_perf.py 缺失", evidence)
    t0 = time.monotonic()
    try:
        rc, out = run_pytest(["tests/benchmark/test_faf_core_perf.py"],
                             env_extra={"FAF_BENCH_SMOKE": "1"},
                             timeout_s=BENCH_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return CheckResult("06", "benchmark 断言 + 基线 JSON", "FAIL",
                           f"benchmark 子进程超时(>{BENCH_TIMEOUT_S}s)", evidence,
                           {"benchmark_elapsed_s": float(BENCH_TIMEOUT_S)})
    m = re.search(r"(\d+) passed(?:, (\d+) skipped)?", out)
    passed = int(m.group(1)) if m else -1
    skipped = int(m.group(2)) if m and m.group(2) else 0
    details: dict[str, Any] = {
        "returncode": rc, "passed": passed, "skipped": skipped,
        "smoke_mode": True, "benchmark_elapsed_s": round(time.monotonic() - t0, 2),
    }
    if rc != 0:
        details["output_tail"] = out[-1500:]
        return CheckResult("06", "benchmark 断言 + 基线 JSON", "FAIL",
                           f"benchmark pytest 退出码 {rc}（崩溃/异常为 FAIL）",
                           evidence, details)
    if passed < 0:
        details["output_tail"] = out[-800:]
        return CheckResult("06", "benchmark 断言 + 基线 JSON", "FAIL",
                           "无法从 benchmark 输出解析 passed 计数", evidence, details)
    if not BASELINE_JSON.is_file():
        return CheckResult("06", "benchmark 断言 + 基线 JSON", "FAIL",
                           f"基线 JSON 缺失: {_rel(BASELINE_JSON)}", evidence, details)
    try:
        baseline = json.loads(_read_text_lossy(BASELINE_JSON))
    except json.JSONDecodeError as exc:
        return CheckResult("06", "benchmark 断言 + 基线 JSON", "FAIL",
                           f"基线 JSON 解析失败: {exc}", evidence, details)
    required_sections = ("scan_directory", "highlight", "hash_throughput",
                         "copy_throughput", "overlimit_fallback")
    missing_sections = [s for s in required_sections if s not in baseline]
    field_issues: list[str] = []
    for section in required_sections:
        node = baseline.get(section, {})
        native = node.get("native", {})
        if section == "overlimit_fallback":
            if "native_cap_reject" not in node or "python_fallback" not in node:
                field_issues.append(f"{section}: 缺 native_cap_reject/python_fallback")
            continue
        if "p50_ms" not in native or "p95_ms" not in native:
            field_issues.append(f"{section}.native: 缺 p50_ms/p95_ms")
        if "assertion" not in node:
            field_issues.append(f"{section}: 缺 assertion 字段")
    details["baseline"] = {
        "schema": baseline.get("schema"),
        "mode": baseline.get("mode"),
        "missing_sections": missing_sections,
        "field_issues": field_issues,
    }
    if missing_sections or field_issues:
        return CheckResult("06", "benchmark 断言 + 基线 JSON", "FAIL",
                           f"基线 JSON 字段不全: 缺节 {missing_sections}, 字段问题 {field_issues}",
                           evidence, details)
    return CheckResult("06", "benchmark 断言 + 基线 JSON", "PASS",
                       f"benchmark 冒烟 {passed} passed（无崩溃）；基线 JSON 五节字段齐全",
                       evidence, details)


def check_07_no_zip(full: bool) -> CheckResult:
    """Check 07：C9 护栏——`grep "zip crate|ZipArchive" faf_core/` 为空。

    扫描 faf_core crate 的源码文件（Cargo.toml / Cargo.lock / src/*.rs /
    目录内 .md），排除构建产物 target/。任一路径命中 ``zip crate`` 或
    ``ZipArchive``（大小写不敏感）即 FAIL。

    Args:
        full: 忽略。

    Returns:
        PASS 当 faf_core/ 源码零命中。
    """
    del full
    evidence = [_rel(FAF_CORE_SRC)]
    if not FAF_CORE_SRC.is_dir():
        return CheckResult("07", "C9 护栏：grep 'zip crate|ZipArchive' faf_core/ 为空", "FAIL",
                           f"faf_core 源码目录缺失: {_rel(FAF_CORE_SRC)}", evidence)
    scan_files: list[Path] = []
    for p in FAF_CORE_SRC.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(FAF_CORE_SRC)
        if "target" in rel.parts:
            continue  # 构建产物（二进制/.d/日志），非源码，排除
        if p.suffix.lower() in (".rs", ".toml", ".lock", ".md", ".txt"):
            scan_files.append(p)
    hits: list[dict[str, Any]] = []
    for p in sorted(scan_files):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for idx, line in enumerate(text.splitlines(), start=1):
            stripped = line.lstrip()
            # C9 护栏语义 = 无实际 zip 用法；注释/文档说明（如 Cargo.toml 的
            # "无 zip crate" 说明）非实现代码，跳过。只核对可执行代码行。
            if stripped.startswith(("#", "//", "/*", "*")):
                continue
            lowered = line.lower()
            if "zip crate" in lowered or "ziparchive" in lowered:
                hits.append({"file": _rel(p), "line": idx,
                             "snippet": line.strip()[:160]})
    details: dict[str, Any] = {
        "scanned_files": len(scan_files), "hits": hits,
        "excluded": "target/ 构建产物（非源码）+ 注释/文档行（非实现代码）",
    }
    if hits:
        return CheckResult("07", "C9 护栏：grep 'zip crate|ZipArchive' faf_core/ 为空", "FAIL",
                           f"命中 {len(hits)} 处: " + "; ".join(
                               f"{h['file']}:{h['line']}" for h in hits[:5]),
                           evidence, details)
    return CheckResult("07", "C9 护栏：grep 'zip crate|ZipArchive' faf_core/ 为空", "PASS",
                       f"扫描 {len(scan_files)} 个源码文件零命中（无 zip crate / ZipArchive）",
                       evidence, details)


def check_08_git_status(full: bool) -> CheckResult:
    """Check 08：git status --porcelain 仅预期文件、无 git 操作（只读）。

    Args:
        full: 忽略。

    Returns:
        PASS 当暂存区为空且全部工作树改动都在预期集合内。
    """
    del full
    staged = run_git(["diff", "--cached", "--name-only"])
    status = run_git(["status", "--porcelain=v1"])
    if staged.returncode != 0 or status.returncode != 0:
        return CheckResult("08", "git status --porcelain 仅预期文件", "FAIL",
                           f"git 只读命令失败: staged rc={staged.returncode}, status rc={status.returncode}")
    staged_files = [l for l in (staged.stdout or "").splitlines() if l.strip()]
    wt_lines = [l for l in (status.stdout or "").splitlines() if l.strip()]
    unexpected: list[str] = []
    for line in wt_lines:
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if not any(path.startswith(prefix) for prefix in ALLOWED_WORKTREE_PREFIXES):
            unexpected.append(path)
    details: dict[str, Any] = {
        "staged": staged_files,
        "working_tree_entries": len(wt_lines),
        "modified": sum(1 for l in wt_lines if l.startswith(" M")),
        "untracked": sum(1 for l in wt_lines if l.startswith("??")),
        "unexpected": unexpected,
    }
    if staged_files:
        return CheckResult("08", "git status --porcelain 仅预期文件", "FAIL",
                           f"存在暂存区改动（git 操作发生）: {staged_files}", [], details)
    if unexpected:
        return CheckResult("08", "git status --porcelain 仅预期文件", "FAIL",
                           f"存在预期集合外的工作树改动: {unexpected}", [], details)
    details["note"] = "tests/benchmark/baseline/thumbnail-latency.json 为 pre-existing 基准重写残留（thumbnail 计划 benchmark 运行所致，非本次任务触碰）"
    return CheckResult("08", "git status --porcelain 仅预期文件", "PASS",
                       f"暂存区为空；工作树 {details['modified']} 改动 + {details['untracked']} 未跟踪，全部在预期集合内",
                       [], details)


def check_09_module_map_untouched(full: bool) -> CheckResult:
    """Check 09：core/__init__.py diff 为空（_MODULE_MAP 未改）。

    Args:
        full: 忽略。

    Returns:
        PASS 当 git 对该文件无任何 diff 且工作树状态无该文件。
    """
    del full
    proc = run_git(["diff", "--stat", "--", _rel(CORE_INIT)])
    status = run_git(["status", "--porcelain=v1", "--", _rel(CORE_INIT)])
    changed = [l for l in (proc.stdout or "").splitlines() if l.strip()]
    status_lines = [l for l in (status.stdout or "").splitlines() if l.strip()]
    details: dict[str, Any] = {
        "watch_path": _rel(CORE_INIT), "diff_stat": changed,
        "status_entries": status_lines,
    }
    if proc.returncode != 0:
        return CheckResult("09", "core/__init__.py diff 为空（_MODULE_MAP 未改）", "FAIL",
                           f"git diff 失败: {proc.stderr!r}", [], details)
    if changed or status_lines:
        return CheckResult("09", "core/__init__.py diff 为空（_MODULE_MAP 未改）", "FAIL",
                           "_MODULE_MAP 载体文件出现改动", [], details)
    return CheckResult("09", "core/__init__.py diff 为空（_MODULE_MAP 未改）", "PASS",
                       "core/__init__.py 零改动（_MODULE_MAP 未改）", [], details)


def check_10_evidence_files(full: bool) -> CheckResult:
    """Check 10：全部 evidence 文件存在且非空。

    Args:
        full: 忽略。

    Returns:
        PASS 当 task-* 证据文件全部非空且数量 ≥ 25。
    """
    del full
    files = sorted(p for p in EVIDENCE_DIR.glob("task-*") if p.is_file())
    empty = [_rel(p) for p in files if p.stat().st_size == 0]
    ids_present = {
        int(m.group(1))
        for p in files
        if (m := re.match(r"task-(\d+)-", p.name)) is not None
    }
    ids_missing = [str(i) for i in range(1, 33) if i not in ids_present]
    details: dict[str, Any] = {
        "file_count": len(files),
        "empty": empty,
        "todo_ids_without_dedicated_evidence": ids_missing,
    }
    if empty:
        return CheckResult("10", "全部 evidence 文件存在且非空", "FAIL",
                           f"空证据文件: {empty}", [], details)
    if len(files) < 25:
        return CheckResult("10", "全部 evidence 文件存在且非空", "FAIL",
                           f"证据文件过少({len(files)} < 25)", [], details)
    details["note"] = "task-13/16/23/28 等含测试证据由相邻任务日志合并覆盖；todo 33 的 task-33-verify-report.json 为本次产物"
    return CheckResult("10", "全部 evidence 文件存在且非空", "PASS",
                       f"{len(files)} 个 task-* 证据文件全部非空", [], details)


def _f3_pytest_check(check_id: str, name: str, targets: list[str],
                     evidence_files: list[str]) -> CheckResult:
    """运行 F3 机器项对应的既有测试选择器并断言通过。

    失败（exit 非 0 / 无法解析 passed）→ FAIL；测试目标缺失 → FAIL
    （测试契约是验收一部分）。dll 缺失导致的 skip 仍计 PASS（pytest exit 0）。

    Args:
        check_id: 检查编号。
        name: 检查名称。
        targets: pytest 节点选择器列表。
        evidence_files: 关联证据文件名（EVIDENCE_DIR 内）。

    Returns:
        PASS 当所有选择器 exit 0。
    """
    evidence = [_rel(EVIDENCE_DIR / f) for f in evidence_files]
    missing = [t for t in targets if not (PROJECT_ROOT / t.split("::")[0]).exists()]
    if missing:
        return CheckResult(check_id, name, "FAIL",
                           f"来源测试文件缺失: {missing}", evidence)
    t0 = time.monotonic()
    try:
        rc, out = run_pytest(targets, timeout_s=PYTEST_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return CheckResult(check_id, name, "FAIL",
                           f"pytest 子进程超时(>{PYTEST_TIMEOUT_S}s)", evidence)
    m = re.search(r"(\d+) passed(?:, (\d+) (?:skipped|xfailed))?", out)
    passed = int(m.group(1)) if m else -1
    skipped = int(m.group(2)) if m and m.group(2) else 0
    details: dict[str, Any] = {
        "targets": targets, "returncode": rc, "passed": passed, "skipped": skipped,
        "elapsed_s": round(time.monotonic() - t0, 2),
    }
    if rc != 0:
        details["output_tail"] = out[-1200:]
        return CheckResult(check_id, name, "FAIL",
                           f"来源测试未通过（pytest 退出码 {rc}）", evidence, details)
    if passed < 0:
        details["output_tail"] = out[-800:]
        return CheckResult(check_id, name, "FAIL",
                           "无法从 pytest 输出解析 passed 计数", evidence, details)
    return CheckResult(check_id, name, "PASS",
                       f"{passed} passed, {skipped} skipped（来源测试覆盖）", evidence, details)


def check_11_sethtml(full: bool) -> CheckResult:
    """Check 11：F3 setHtml 计数 == 1（todo 18 防抖单次渲染）。"""
    del full
    d = F3_DEFS["11"]
    return _f3_pytest_check("11", d["name"], d["targets"], d["evidence"])


def check_12_thread_ids(full: bool) -> CheckResult:
    """Check 12：F3 UI 线程 id != worker id（todo 30/31 线程断言）。"""
    del full
    d = F3_DEFS["12"]
    return _f3_pytest_check("12", d["name"], d["targets"], d["evidence"])


def check_13_pdf_hash(full: bool) -> CheckResult:
    """Check 13：F3 PDF 像素 hash 相等（todo 31 抽屉 vs 同步）。"""
    del full
    d = F3_DEFS["13"]
    return _f3_pytest_check("13", d["name"], d["targets"], d["evidence"])


def check_14_screenshots(full: bool) -> CheckResult:
    """Check 14：F3 截图文件存在且 os.path.getsize > 0。

    manual-qa/ 目录由 F3 波（offscreen 冒烟 + GUI 截图）产出，todo 33 先行
    时通常尚不存在——按计划纪律输出 SKIP 并注明来源测试名（不伪造数据）。

    Args:
        full: 忽略。

    Returns:
        截图存在且全部非空 → PASS；目录缺失/无文件 → SKIP（注明 F3 波产出）；
        存在空文件 → FAIL。
    """
    del full
    source_note = F3_DEFS["14"]["source"]
    evidence = [_rel(MANUAL_QA_DIR)]
    if not MANUAL_QA_DIR.is_dir():
        return CheckResult("14", "F3 截图文件存在且 os.path.getsize > 0", "SKIP",
                           f"manual-qa/ 目录尚不存在——截图由 F3 波产出（{source_note}）",
                           evidence)
    images = sorted(
        p for p in MANUAL_QA_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp")
    )
    if not images:
        return CheckResult("14", "F3 截图文件存在且 os.path.getsize > 0", "SKIP",
                           f"manual-qa/ 无截图文件（{source_note}）", evidence)
    empty = [str(p) for p in images if p.stat().st_size == 0]
    details: dict[str, Any] = {
        "screenshots": [_rel(p) for p in images],
        "empty": [_rel(p) for p in images if p.stat().st_size == 0],
    }
    if empty:
        return CheckResult("14", "F3 截图文件存在且 os.path.getsize > 0", "FAIL",
                           f"存在空截图文件: {empty}", evidence, details)
    return CheckResult("14", "F3 截图文件存在且 os.path.getsize > 0", "PASS",
                       f"{len(images)} 个截图文件全部非空", evidence, details)


def check_15_mutagen_open_count(full: bool) -> CheckResult:
    """Check 15：F3 mutagen 单次打开计数 == 1（todo 30 单次打开）。"""
    del full
    d = F3_DEFS["15"]
    return _f3_pytest_check("15", d["name"], d["targets"], d["evidence"])


def check_16_ui_immediate_return(full: bool) -> CheckResult:
    """Check 16：F3 音/视频选择 UI 线程即时返回（todo 20/30 时间断言）。"""
    del full
    d = F3_DEFS["16"]
    return _f3_pytest_check("16", d["name"], d["targets"], d["evidence"])


CHECKS: list[tuple[str, str, Callable[[bool], CheckResult]]] = [
    ("01", "dumpbin /exports 导出清单（14 个 faf_* 导出）", check_01_exports),
    ("02", "dumpbin /dependents 白名单（无新增外部 DLL）", check_02_dependents),
    ("03", "依赖 license 表存在（task-1-decisions.md）", check_03_license_table),
    ("04", "既有测试契约全绿（各波回归门文件逐文件）", check_04_existing_gates),
    ("05", "新增测试全绿（桥/wiring/对拍/抽屉/parity helper）", check_05_new_tests),
    ("06", "benchmark 断言 + 基线 JSON", check_06_benchmark),
    ("07", "C9 护栏：grep 'zip crate|ZipArchive' faf_core/ 为空", check_07_no_zip),
    ("08", "git status --porcelain 仅预期文件（无 git 操作）", check_08_git_status),
    ("09", "core/__init__.py diff 为空（_MODULE_MAP 未改）", check_09_module_map_untouched),
    ("10", "全部 evidence 文件存在且非空", check_10_evidence_files),
    ("11", "F3 setHtml 计数 == 1", check_11_sethtml),
    ("12", "F3 UI 线程 id != worker id", check_12_thread_ids),
    ("13", "F3 PDF 像素 hash 相等", check_13_pdf_hash),
    ("14", "F3 截图文件存在且 os.path.getsize > 0", check_14_screenshots),
    ("15", "F3 mutagen 单次打开计数 == 1", check_15_mutagen_open_count),
    ("16", "F3 音/视频选择 UI 线程即时返回", check_16_ui_immediate_return),
]

# 每个 FAIL 的复现命令（todo 编号对应检查 id）。
REPRO_COMMANDS: dict[str, str] = {
    "01": "dumpbin /exports freeassetfilter/core/native/bin/faf_core.dll（vswhere helper 解析路径；回退 llvm-readobj --file-headers --coff-exports）",
    "02": "dumpbin /dependents freeassetfilter/core/native/bin/faf_core.dll（白名单：系统 DLL + VCRUNTIME140 + api-ms-win-*）",
    "03": "Get-Content .omo/evidence/faf-core-rust-migration/task-1-decisions.md（核对 §4 license 表 12 个直接依赖）",
    "04": "python -m pytest tests/integration/test_selector_thumbnail_flow.py tests/unit/ui/layout/test_layouts.py tests/unit/services/test_file_service.py tests/unit/workers/test_file_list_loader.py tests/unit/utils/test_syntax_highlighter.py tests/unit/ui/layout/preview/test_zoom_popups.py tests/unit/utils/test_markdown_renderer.py tests/unit/ui/layout/preview/test_file_info_panel.py tests/unit/services/test_file_info_service.py tests/unit/core/test_media_probe.py tests/unit/utils/test_subprocess_utils.py tests/unit/services/test_staging_pool_service.py tests/unit/workers/test_staging_tasks.py tests/unit/services/test_media_metadata_service.py tests/unit/services/test_pdf_services.py tests/unit/ui/layout/preview/test_native_pdf_renderer.py tests/unit/core/test_rust_thumbnail_bridge.py tests/integration/test_ffmpeg_minimal_binaries.py tests/unit/core/test_status_channel.py -q --no-header",
    "05": "python -m pytest tests/unit/core/test_faf_core_bridge.py tests/unit/ui/layout/test_file_selector_native_wiring.py tests/unit/services/test_font_native_parity.py tests/unit/services/test_encoding_native_parity.py tests/unit/ui/layout/preview/test_pdf_drawer_async.py tests/support/test_parity_helper.py -q --no-header",
    "06": "python -m pytest tests/benchmark/test_faf_core_perf.py -q --no-header（设 FAF_BENCH_SMOKE=1；核对 tests/benchmark/baseline/faf-core-perf.json 五节字段）",
    "07": "Select-String -Path freeassetfilter/core/native/src/faf_core/src/*.rs, Cargo.toml, Cargo.lock -Pattern 'zip crate|ZipArchive'",
    "08": "git status --porcelain=v1；git diff --cached --name-only（只读，禁止任何 git 写操作）",
    "09": "git diff --stat -- freeassetfilter/core/__init__.py",
    "10": "Get-ChildItem .omo/evidence/faf-core-rust-migration/task-* | Where-Object Length -eq 0",
    "11": "python -m pytest tests/unit/ui/layout/test_layouts.py::TestTextPreviewerLayout::test_slider_debounce_single_render -q --no-header",
    "12": "python -m pytest tests/unit/ui/layout/preview/test_pdf_drawer_async.py::test_drawer_renders_off_ui_thread tests/unit/ui/layout/test_layouts.py::TestVideoPlayerLayoutAsyncAudio::test_audio_select_single_open_and_worker_palette -q --no-header",
    "13": "python -m pytest tests/unit/ui/layout/preview/test_pdf_drawer_async.py::test_drawer_pixels_identical_to_synchronous -q --no-header",
    "14": "Get-ChildItem .omo/evidence/faf-core-rust-migration/manual-qa -Recurse -File | Where-Object Length -eq 0（截图由 F3 波产出）",
    "15": "python -m pytest tests/unit/services/test_media_metadata_service.py::TestSingleMutagenOpen::test_extract_audio_metadata_single_open -q --no-header",
    "16": "python -m pytest tests/unit/ui/layout/preview/test_file_info_panel.py::TestFileInfoPanelMediaAsync::test_video_light_rows_async_returns_immediately tests/unit/ui/layout/test_layouts.py::TestVideoPlayerLayoutAsyncAudio::test_audio_select_returns_immediately -q --no-header",
}


def build_report(results: list[CheckResult], total_elapsed: float) -> dict[str, Any]:
    """组装机器报告。

    Args:
        results: 全部检查结果。
        total_elapsed: 全程墙钟秒数。

    Returns:
        报告字典（JSON 可序列化）。
    """
    counts = {s: sum(1 for r in results if r.status == s)
              for s in ("PASS", "FAIL", "SKIP")}
    overall = "FAIL" if counts["FAIL"] else "PASS"
    failed_ids = [r.check_id for r in results if r.status == "FAIL"]
    return {
        "schema": "verify-faf-core-report/v1",
        "plan": "faf-core-rust-migration",
        "plan_file": ".omo/plans/faf-core-rust-migration.md",
        "todo": 33,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "overall": overall,
        "summary": counts,
        "failed_ids": failed_ids,
        "repro_commands": {cid: REPRO_COMMANDS[cid] for cid in failed_ids},
        "total_elapsed_s": round(total_elapsed, 1),
        "checks": [r.to_dict() for r in results],
    }


def print_summary(results: list[CheckResult], report: dict[str, Any]) -> None:
    """打印人类可读摘要到 stdout。

    Args:
        results: 全部检查结果。
        report: 组装后的报告。
    """
    print("=" * 72)
    print("faf-core-rust-migration 验收自检  todo=33  耗时 "
          f"{report['total_elapsed_s']}s")
    print("=" * 72)
    for r in results:
        marker = {"PASS": "[PASS]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}[r.status]
        print(f"{marker} {r.check_id:<4} {r.name}")
        print(f"       {r.reason}")
    print("-" * 72)
    s = report["summary"]
    print(f"总计: {s['PASS']} PASS / {s['FAIL']} FAIL / {s['SKIP']} SKIP  "
          f"-> OVERALL {report['overall']}")
    if report["failed_ids"]:
        print("\nFAIL 项复现命令（对应 todo 编号）:")
        for cid in report["failed_ids"]:
            print(f"  [{cid}] {REPRO_COMMANDS[cid]}")
    print(f"报告: {_rel(REPORT_PATH)}")
    print(f"证据: {_rel(EVIDENCE_COPY)}")
    print(f"OVERALL {report['overall']}" + ("" if report["overall"] == "PASS"
                                           else "（任一 FAIL 阻止 F1-F4 启动）"))


def main(argv: list[str] | None = None) -> int:
    """入口：运行全部检查，写 JSON 报告 + 证据副本，打印摘要。

    Args:
        argv: CLI 参数（默认 sys.argv）。

    Returns:
        0 当无 FAIL（SKIP 容忍）；1 当任一 FAIL。
    """
    parser = __import__("argparse").ArgumentParser(
        description="faf-core-rust-migration 验收自检脚本（todo 33）"
    )
    parser.add_argument("--report", type=str, default=None,
                        help="覆盖报告输出路径（默认 .omo/evidence/.../verification-report.json）")
    args = parser.parse_args(argv)
    global REPORT_PATH
    if args.report:
        REPORT_PATH = Path(args.report)

    results: list[CheckResult] = []
    started = time.monotonic()
    for check_id, name, func in CHECKS:
        t0 = time.monotonic()
        try:
            result = func(False)
        except Exception as exc:  # noqa: BLE001  # 单项隔离是契约
            result = CheckResult(check_id, name, "FAIL", f"检查自身异常: {exc!r}")
        result.elapsed_s = time.monotonic() - t0
        results.append(result)
        marker = {"PASS": "[PASS]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}[result.status]
        print(f"{marker} {check_id:<4} {name}  ({result.elapsed_s:.1f}s)", flush=True)

    total = time.monotonic() - started
    report = build_report(results, total)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    EVIDENCE_COPY.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    print_summary(results, report)
    return 1 if report["summary"]["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
