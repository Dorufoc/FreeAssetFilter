#!/usr/bin/env python3
"""rust-hot-path-native-migration 验收自检脚本（计划 todo 24）。

一条命令产出机器报告 ``verification-report.json``（每项 PASS/FAIL + 对应
todo 编号 + 复现命令），并落一份证据副本 ``.omo/evidence/
rust-hot-path-native-migration/task-24-verify-report.json``。**全部为机器
核对，无人工判断项**。

9 项检查（对照 ``.omo/plans/rust-hot-path-native-migration.md`` todo 24）：

1.  ``dumpbin /exports faf_core.dll``——**20 个** ``faf_*`` 导出齐全（14 既有
    + 6 新：``faf_parse_exif``/``faf_composite_psd``/``faf_replace_svg_colors``/
    ``faf_render_fluid_frame``/``faf_parse_7z_list``/``faf_pdf_select_words``；
    todo 1(iv)=DROP 故计数保持 20，无第 7 导出）；
2.  ``dumpbin /dependents`` 白名单——无新增运行时外部 DLL（仅系统 DLL + VC
    运行时 + ``api-ms-win-*`` 前缀；bundled ffmpeg/7z 为子进程依赖非 PE 导入表项）；
3.  依赖 license 表存在——``Cargo.toml`` 注释含 ``kamadak-exif``（BSD-2-Clause）
    与 ``regex``（MIT OR Apache-2.0），且 ``task-1-decisions.md`` 存在非空；
4.  既有测试契约全绿——Wave 回归门中非新增路径的既有文件逐文件 pytest
    （paths / file_info_panel / archive_previewer_layout / syntax_highlighter /
    rust_thumbnail_bridge / module_imports）；
5.  新增对拍/回退测试全绿——EXIF/PSD/SVG/fluid/7z/PDF 相关对拍与回退测试
    逐文件 pytest（bridge / file_info_service / image_services / svg_renderer /
    styled_fluid / py7z_core / pdf_services / file_icon_manager）；
6.  benchmark 断言与基线——``faf-core-perf.json`` 含 6 个新段
    （exif/psd/svg_replace_colors/fluid_frame/sevenz_parse/pdf_select_words，
    KEEP 段需 P50/P95、DROP 段需 ``native_none_expected``）且高亮段
    ``highlight.assertion.passed == true``（todo 21/22/23）；
7.  6 个新桥方法的 DLL 缺失降级——mock ``_candidate_paths`` 指向不存在目录 →
    ``available is False``、6 个 ``_supports_*`` 全 False、6 方法各返回 ``None``
    不抛异常；真实可用时 6 方法可调用且 ``_supports_*`` 全 True；
8.  ``git status --porcelain`` 无 git 操作（暂存区为空）+ ``core/__init__.py``
    diff 为空（``_MODULE_MAP`` 未改；只读查询，无任何 git 写操作）；
9.  evidence 文件齐全且非空——``task-1..task-25`` 证据全在（task-24 即本报告
    自身，首次运行由脚本落盘后补齐）。

FAIL 语义：任一检查 FAIL → 退出码非 0，并在摘要中输出对应编号 + 复现命令
（任一 FAIL 阻止 F1-F4 启动）。

设计规则（继承 tests/acceptance/verify_plan.py 与旧 verify_faf_core.py 先例）：
- 每项检查独立 try/except——单项失败不阻塞其余；
- 每项产出 PASS / FAIL / SKIP（SKIP 必带原因）；
- 纯 stdlib + 项目桥模块（仅检查 7 惰性导入），无新依赖；测试临时物不落仓库；
- 不执行任何 git 写操作。

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
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = PROJECT_ROOT / ".omo" / "evidence" / "rust-hot-path-native-migration"
REPORT_PATH = EVIDENCE_DIR / "verification-report.json"
EVIDENCE_COPY = EVIDENCE_DIR / "task-24-verify-report.json"
DECISIONS_PATH = EVIDENCE_DIR / "task-1-decisions.md"
FAF_CORE_SRC = PROJECT_ROOT / "freeassetfilter" / "core" / "native" / "src" / "faf_core"
CARGO_TOML = FAF_CORE_SRC / "Cargo.toml"
BIN_DLL = PROJECT_ROOT / "freeassetfilter" / "core" / "native" / "bin" / "faf_core.dll"
BASELINE_JSON = (
    PROJECT_ROOT / "tests" / "benchmark" / "baseline" / "faf-core-perf.json"
)
CORE_INIT = PROJECT_ROOT / "freeassetfilter" / "core" / "__init__.py"

PYTEST_TIMEOUT_S = 600
GIT_TIMEOUT_S = 60

# todo 1/2/10 落定的 20 个 faf_* 导出（14 既有 + 6 新；todo 1(iv) `_pil_to_qimage`
# DROP → 无第 7 导出，计数 20）。
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
    "faf_parse_exif",
    "faf_composite_psd",
    "faf_replace_svg_colors",
    "faf_render_fluid_frame",
    "faf_parse_7z_list",
    "faf_pdf_select_words",
}

# 6 个新桥方法名 → 降级检查的哑元入参（available=False 时全部在探测门早退
# 返回 None，不入参校验；真实可用时入参仅用于证明方法可调用）。
NEW_BRIDGE_METHODS: dict[str, tuple[Any, ...]] = {
    "parse_exif": ("",),
    "composite_psd": ("",),
    "replace_svg_colors": ("", False, False),
    "render_fluid_frame": (320, 200, "[]", 20260925, 0.0, "{}"),
    "parse_7z_list": ("", "", ""),
    "pdf_select_words": ("[]", "{}"),
}
NEW_SUPPORT_FLAGS: tuple[str, ...] = (
    "_supports_parse_exif",
    "_supports_composite_psd",
    "_supports_replace_svg_colors",
    "_supports_render_fluid_frame",
    "_supports_parse_7z_list",
    "_supports_pdf_select_words",
)

# dumpbin /dependents 白名单：仅 Windows 系统 DLL + VC 运行时（api-ms-win-* 前缀）。
# bundled ffmpeg/ffprobe/7z 为子进程依赖，非 PE 导入表项，属计划明示例外。
DEPENDENTS_WHITELIST_EXACT: set[str] = {
    "kernel32.dll", "ntdll.dll", "bcryptprimitives.dll", "advapi32.dll",
    "shell32.dll", "oleaut32.dll", "user32.dll", "gdi32.dll", "ws2_32.dll",
    "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll",
    "msvcp140_2.dll", "ucrtbase.dll",
}
DEPENDENTS_WHITELIST_PREFIXES: tuple[str, ...] = ("api-ms-win-",)

# Check 04 既有测试契约：本计划各 Wave 回归门中**非新增路径**的既有文件
# （新增路径文件归入 check 05）。全局契约（全程）一并纳入。
GATE_FILES: tuple[str, ...] = (
    "tests/unit/core/test_paths.py",
    "tests/unit/ui/layout/preview/test_file_info_panel.py",
    "tests/unit/ui/layout/preview/test_archive_previewer_layout.py",
    "tests/unit/utils/test_syntax_highlighter.py",
    "tests/unit/core/test_rust_thumbnail_bridge.py",
    "tests/integration/test_module_imports.py",
)

# Check 05 新增对拍/回退测试：EXIF/PSD/SVG 换色/fluid/7z 解析/PDF 选区六个
# 新路径的对拍与回退测试所在文件（todo 3/5/6/7/8/9/11/12/13/14/16/17/18/19 交付）。
NEW_TEST_FILES: tuple[str, ...] = (
    "tests/unit/core/test_faf_core_bridge.py",
    "tests/unit/services/test_file_info_service.py",
    "tests/unit/services/test_image_services.py",
    "tests/unit/core/test_svg_renderer.py",
    "tests/unit/ui/components/test_styled_fluid.py",
    "tests/unit/core/test_py7z_core.py",
    "tests/unit/services/test_pdf_services.py",
    "tests/unit/services/test_file_icon_manager.py",
)

# Check 06：baseline JSON 的 6 个新段 → 期望 status（todo 23 落定）。
BENCH_NEW_SECTIONS: dict[str, str] = {
    "exif": "KEEP",
    "svg_replace_colors": "KEEP",
    "sevenz_parse": "KEEP",
    "pdf_select_words": "KEEP",
    "psd": "DROP",
    "fluid_frame": "DROP",
}

# Check 09：evidence 必须覆盖的 todo 编号（task-24 为本脚本产物，首次运行
# 报告落盘前尚不存在——脚本在检查时若已存在则一并要求）。
EVIDENCE_BASE_IDS: frozenset[int] = frozenset(range(1, 26)) - frozenset({24})


@dataclass
class CheckResult:
    """单项验收检查结果。"""

    check_id: str
    name: str
    status: str  # "PASS" | "FAIL" | "SKIP"
    reason: str
    todos: list[str] = field(default_factory=list)
    repro: str = ""
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
            "todos": self.todos,
            "repro": self.repro,
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


def check_01_exports(_full: bool) -> CheckResult:
    """Check 01：dumpbin /exports → 20 个 faf_* 导出齐全（todo 2/10）。

    Args:
        _full: 忽略（两种模式行为一致）。

    Returns:
        PASS 当全部 20 个必需导出命中；否则 FAIL。
    """
    todos = ["2", "10"]
    repro = "dumpbin /exports freeassetfilter/core/native/bin/faf_core.dll（vswhere 解析路径；回退 llvm-readobj --file-headers --coff-exports）；期望 20 个 faf_* 导出"
    evidence = [_rel(BIN_DLL), _rel(EVIDENCE_DIR / "task-2-exports.txt")]
    if not BIN_DLL.is_file():
        return CheckResult("01", "dumpbin /exports 导出清单（20 个 faf_* 导出）", "FAIL",
                           f"DLL 不存在: {_rel(BIN_DLL)}", todos, repro, evidence)
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
        return CheckResult("01", "dumpbin /exports 导出清单（20 个 faf_* 导出）", "FAIL",
                           "dumpbin/llvm-readobj 均不可用，无法核对导出清单", todos, repro,
                           evidence, details)
    if missing:
        return CheckResult("01", "dumpbin /exports 导出清单（20 个 faf_* 导出）", "FAIL",
                           f"缺少导出: {missing}", todos, repro, evidence, details)
    if len(faf_exports) != len(REQUIRED_EXPORTS):
        return CheckResult("01", "dumpbin /exports 导出清单（20 个 faf_* 导出）", "FAIL",
                           f"faf_* 导出数不符（{len(faf_exports)} != {len(REQUIRED_EXPORTS)}）",
                           todos, repro, evidence, details)
    return CheckResult("01", "dumpbin /exports 导出清单（20 个 faf_* 导出）", "PASS",
                       f"20 个 faf_* 导出全部命中（来源 {source}；todo 1(iv)=DROP 计数保持 20）",
                       todos, repro, evidence, details)


def check_02_dependents(_full: bool) -> CheckResult:
    """Check 02：dumpbin /dependents 白名单（无新增运行时外部 DLL）（todo 1）。

    Args:
        _full: 忽略。

    Returns:
        PASS 当所有依赖均为系统 DLL + VC 运行时。
    """
    todos = ["1"]
    repro = "dumpbin /dependents freeassetfilter/core/native/bin/faf_core.dll（白名单 = Windows 系统 DLL + VC 运行时 + api-ms-win-*）"
    evidence = [_rel(BIN_DLL)]
    if not BIN_DLL.is_file():
        return CheckResult("02", "dumpbin /dependents 白名单", "FAIL",
                           f"DLL 不存在: {_rel(BIN_DLL)}", todos, repro, evidence)
    names, source = collect_faf_dependents()
    if not names:
        return CheckResult("02", "dumpbin /dependents 白名单", "FAIL",
                           "dumpbin 不可用或未解析出依赖清单", todos, repro, evidence)
    ok, unexpected = classify_dependents(names)
    details: dict[str, Any] = {
        "source": source,
        "dependent_count": len(names),
        "whitelisted": ok,
        "unexpected": unexpected,
    }
    if unexpected:
        return CheckResult("02", "dumpbin /dependents 白名单", "FAIL",
                           f"白名单外依赖: {unexpected}", todos, repro, evidence, details)
    if len(names) < 3:
        return CheckResult("02", "dumpbin /dependents 白名单", "FAIL",
                           f"dependents 解析结果过少({len(names)})，疑似解析失败",
                           todos, repro, evidence, details)
    details["note"] = "bundled ffmpeg/ffprobe/7z 为子进程依赖，非 PE 导入表项，属计划明示例外"
    return CheckResult("02", "dumpbin /dependents 白名单", "PASS",
                       f"{len(names)} 个依赖全部在（Windows 系统库 + VC 运行时）白名单内",
                       todos, repro, evidence, details)


def check_03_license_table(_full: bool) -> CheckResult:
    """Check 03：依赖 license 表存在（Cargo.toml 注释 + decisions 证据）（todo 1）。

    新增 crate（kamadak-exif BSD-2-Clause / regex MIT OR Apache-2.0）必须在
    Cargo.toml 注释中有 license 说明，且 task-1-decisions.md 存在非空。

    Args:
        _full: 忽略。

    Returns:
        PASS 当两个 crate license 注释命中 + decisions 文件存在非空。
    """
    todos = ["1"]
    repro = ("Get-Content freeassetfilter/core/native/src/faf_core/Cargo.toml"
             "（kamadak-exif BSD-2-Clause / regex MIT OR Apache-2.0）+ "
             "Get-Content .omo/evidence/rust-hot-path-native-migration/task-1-decisions.md")
    evidence = [_rel(CARGO_TOML), _rel(DECISIONS_PATH)]
    if not CARGO_TOML.is_file():
        return CheckResult("03", "依赖 license 表存在（Cargo.toml 注释 + decisions）", "FAIL",
                           f"Cargo.toml 缺失: {_rel(CARGO_TOML)}", todos, repro, evidence)
    text = _read_text_lossy(CARGO_TOML)
    checks: dict[str, str] = {
        "kamadak-exif": "kamadak-exif 条目缺失",
        "BSD-2-Clause": "kamadak-exif license（BSD-2-Clause）注释缺失",
        "regex": "regex 条目缺失",
        "MIT OR Apache-2.0": "regex license（MIT OR Apache-2.0）注释缺失",
    }
    found_issues: list[str] = []
    for needle, msg in checks.items():
        if needle not in text:
            found_issues.append(msg)
    if not DECISIONS_PATH.is_file():
        found_issues.append(f"decisions 缺失: {_rel(DECISIONS_PATH)}")
    if DECISIONS_PATH.is_file() and DECISIONS_PATH.stat().st_size == 0:
        found_issues.append(f"decisions 为空文件: {_rel(DECISIONS_PATH)}")
    details: dict[str, Any] = {
        "cargo_toml_checks": {k: (v in text) for k, v in checks.items()},
        "decisions_exists": DECISIONS_PATH.is_file(),
        "issues": found_issues,
    }
    if found_issues:
        return CheckResult("03", "依赖 license 表存在（Cargo.toml 注释 + decisions）", "FAIL",
                           "; ".join(found_issues), todos, repro, evidence, details)
    return CheckResult("03", "依赖 license 表存在（Cargo.toml 注释 + decisions）", "PASS",
                       "kamadak-exif（BSD-2-Clause）与 regex（MIT OR Apache-2.0）license 注释齐全，decisions 存在非空",
                       todos, repro, evidence, details)


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
        return CheckResult(check_id, name, "FAIL", f"测试文件缺失: {missing}", evidence=evidence)
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
                           evidence=evidence, details=details)
    return CheckResult(check_id, name, "PASS",
                       f"{len(files)} 个文件全部通过（exit 0）", evidence=evidence, details=details)


def check_04_existing_gates(_full: bool) -> CheckResult:
    """Check 04：既有测试契约全绿（非新增路径回归门逐文件，todo 7/9/12/14/17/19/21）。

    Args:
        _full: 忽略（回归门固定为计划清单）。

    Returns:
        PASS 当全部 6 个既有回归门文件 exit 0。
    """
    todos = ["7", "9", "12", "14", "17", "19", "21"]
    repro = ("python -m pytest tests/unit/core/test_paths.py "
             "tests/unit/ui/layout/preview/test_file_info_panel.py "
             "tests/unit/ui/layout/preview/test_archive_previewer_layout.py "
             "tests/unit/utils/test_syntax_highlighter.py "
             "tests/unit/core/test_rust_thumbnail_bridge.py "
             "tests/integration/test_module_imports.py -q --no-header")
    result = _pytest_files_check(
        "04", "既有测试契约全绿（非新增路径回归门逐文件）", list(GATE_FILES),
        extra_evidence=[_rel(EVIDENCE_DIR / f) for f in
                        ("task-25-docs.txt", "task-19-pdf-wiring.txt")],
    )
    result.todos = todos
    result.repro = repro
    return result


def check_05_new_tests(_full: bool) -> CheckResult:
    """Check 05：新增对拍/回退测试全绿（EXIF/PSD/SVG/fluid/7z/PDF，todo 3/5-20）。

    Args:
        _full: 忽略（新增测试清单固定）。

    Returns:
        PASS 当全部新增测试文件 exit 0。
    """
    todos = ["3", "5", "6", "7", "8", "9", "11", "12", "13", "14", "16", "17", "18", "19"]
    repro = ("python -m pytest tests/unit/core/test_faf_core_bridge.py "
             "tests/unit/services/test_file_info_service.py "
             "tests/unit/services/test_image_services.py "
             "tests/unit/core/test_svg_renderer.py tests/unit/ui/components/test_styled_fluid.py "
             "tests/unit/core/test_py7z_core.py tests/unit/services/test_pdf_services.py "
             "tests/unit/services/test_file_icon_manager.py -q --no-header")
    result = _pytest_files_check(
        "05", "新增对拍/回退测试全绿（EXIF/PSD/SVG/fluid/7z/PDF）", list(NEW_TEST_FILES),
    )
    result.todos = todos
    result.repro = repro
    return result


def check_06_benchmark(_full: bool) -> CheckResult:
    """Check 06：benchmark 断言与基线（6 新段 + 高亮 passed:true，todo 22/23）。

    基线 JSON 已由 todo 22/23 落盘；本检查为纯产物核对（不重跑 benchmark，
    避免单文件运行覆写基线丢其余段——todo 22 learnings 已记录的坑）。

    Args:
        _full: 忽略。

    Returns:
        PASS 当 6 个新段结构齐全且 highlight.assertion.passed == true。
    """
    todos = ["22", "23"]
    repro = ("Get-Content tests/benchmark/baseline/faf-core-perf.json（6 新段 + "
             "highlight.assertion.passed==true）；重跑请显式执行 python -m pytest "
             "tests/benchmark/test_faf_core_perf.py --no-header（设置 FAF_BENCH_SMOKE=1）")
    evidence = [_rel(BASELINE_JSON)]
    if not BASELINE_JSON.is_file():
        return CheckResult("06", "benchmark 断言与基线（6 新段 + 高亮 passed:true）", "FAIL",
                           f"基线 JSON 缺失: {_rel(BASELINE_JSON)}", todos, repro, evidence)
    try:
        baseline = json.loads(_read_text_lossy(BASELINE_JSON))
    except json.JSONDecodeError as exc:
        return CheckResult("06", "benchmark 断言与基线（6 新段 + 高亮 passed:true）", "FAIL",
                           f"基线 JSON 解析失败: {exc}", todos, repro, evidence)
    missing_sections = [s for s in BENCH_NEW_SECTIONS if s not in baseline]
    issues: list[str] = []
    for section, expected_status in BENCH_NEW_SECTIONS.items():
        node = baseline.get(section)
        if not isinstance(node, dict):
            if section not in missing_sections:
                issues.append(f"{section}: 非对象")
            continue
        actual_status = node.get("status")
        if actual_status != expected_status:
            issues.append(f"{section}: status={actual_status!r}，期望 {expected_status!r}")
        if expected_status == "DROP":
            if node.get("native_none_expected") is not True:
                issues.append(f"{section}: native_none_expected 非 true")
            if node.get("native_returned_none") is not True:
                issues.append(f"{section}: native_returned_none 非 true")
            if node.get("assertion", {}).get("passed") is not True:
                issues.append(f"{section}: assertion.passed 非 true")
        else:
            native = node.get("native", {})
            python = node.get("python", {})
            if "p50_ms" not in native or "p95_ms" not in native:
                issues.append(f"{section}.native: 缺 p50_ms/p95_ms")
            if "p50_ms" not in python:
                issues.append(f"{section}.python: 缺 p50_ms")
            if not isinstance(node.get("assertion", {}).get("passed"), bool):
                issues.append(f"{section}: assertion.passed 缺失")
    highlight = baseline.get("highlight", {})
    highlight_assertion = highlight.get("assertion", {})
    highlight_passed = highlight_assertion.get("passed")
    if highlight_passed is not True:
        issues.append(f"highlight.assertion.passed: {highlight_passed!r}，期望 true")
    details: dict[str, Any] = {
        "schema": baseline.get("schema"),
        "timestamp": baseline.get("timestamp"),
        "mode": baseline.get("mode"),
        "new_sections": list(BENCH_NEW_SECTIONS),
        "missing_sections": missing_sections,
        "highlight": {
            "lines": highlight.get("lines"),
            "native_p50_ms": highlight.get("native", {}).get("p50_ms"),
            "assertion_passed": highlight_passed,
        },
        "issues": issues,
    }
    if missing_sections or issues:
        return CheckResult("06", "benchmark 断言与基线（6 新段 + 高亮 passed:true）", "FAIL",
                           f"基线核对失败: 缺节 {missing_sections}, 字段问题 {issues}",
                           todos, repro, evidence, details)
    return CheckResult("06", "benchmark 断言与基线（6 新段 + 高亮 passed:true）", "PASS",
                       "基线含 6 个新段（结构齐全）且 highlight.assertion.passed == true",
                       todos, repro, evidence, details)


def check_07_bridge_fallback(_full: bool) -> CheckResult:
    """Check 07：6 个新桥方法的 DLL 缺失降级（mock 探测 False → 返回 None）（todo 3）。

    惰性导入桥模块；把 ``_candidate_paths`` mock 指向不存在目录后重置单例 →
    新实例 ``available is False``、6 个 ``_supports_*`` 全 False、6 方法各返回
    ``None`` 不抛异常。随后恢复桥单例与原方法。真实可用时另断言 6 方法可调用
    且 ``_supports_*`` 全 True。

    Args:
        _full: 忽略。

    Returns:
        PASS 当降级路径 6 方法全返回 None；可用实例 6 方法全绑定。
    """
    todos = ["3"]
    repro = ("python -m pytest tests/unit/core/test_faf_core_bridge.py -q --no-header"
             "（DLL 缺失降级用例覆盖 6 新方法）；或临时把桥 _candidate_paths 指向不存在目录后"
             "调 get_faf_core_bridge() 验证 available=False")
    evidence = [
        _rel(EVIDENCE_DIR / "task-3-bridge.txt"),
        _rel(PROJECT_ROOT / "freeassetfilter" / "core" / "native" / "bridges" / "faf_core_bridge.py"),
    ]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    try:
        import freeassetfilter.core.native.bridges.faf_core_bridge as fafb
    except Exception as exc:  # noqa: BLE001  # 桥导入失败即 FAIL（依赖不足）
        return CheckResult("07", "6 个新桥方法 DLL 缺失降级", "FAIL",
                           f"桥模块导入失败: {exc!r}", todos, repro, evidence)
    real_instance = fafb._instance
    orig_method = fafb.FafCoreBridge._candidate_paths
    degraded: Optional[Any] = None
    try:
        missing_dir = PROJECT_ROOT / ".omo" / "_verify_faf_core_missing_dll"
        fafb.FafCoreBridge._candidate_paths = lambda _self: [missing_dir / fafb.LIBRARY_NAME]  # type: ignore[method-assign]
        fafb._instance = None
        degraded = fafb.get_faf_core_bridge()
        available = bool(degraded.available)
        flags = {flag: bool(getattr(degraded, flag)) for flag in NEW_SUPPORT_FLAGS}
        results: dict[str, Any] = {}
        for name, args in NEW_BRIDGE_METHODS.items():
            try:
                results[name] = getattr(degraded, name)(*args)
            except Exception as exc:  # noqa: BLE001  # 任一方法抛异常即 FAIL
                results[name] = f"RAISED {exc!r}"
        details: dict[str, Any] = {
            "degraded_available": available,
            "degraded_support_flags": flags,
            "degraded_method_results": results,
            "mock_candidate_paths": _rel(missing_dir),
        }
        problems: list[str] = []
        if available:
            problems.append("mock 后 available 仍为 True（DLL 缺失降级未生效）")
        for flag, val in flags.items():
            if val:
                problems.append(f"{flag} 应为 False，实为 True")
        for name, val in results.items():
            if val is not None:
                problems.append(f"{name} 应返回 None，实为 {val!r}")
        if real_instance is not None and getattr(real_instance, "available", False):
            real_flags = {flag: bool(getattr(real_instance, flag)) for flag in NEW_SUPPORT_FLAGS}
            real_missing = [name for name in NEW_BRIDGE_METHODS
                            if not callable(getattr(real_instance, name, None))]
            details["live_available"] = True
            details["live_support_flags"] = real_flags
            details["live_missing_methods"] = real_missing
            if any(not real_flags[f] for f in NEW_SUPPORT_FLAGS):
                problems.append(f"可用实例存在 _supports_* 为 False: "
                                f"{[f for f in NEW_SUPPORT_FLAGS if not real_flags[f]]}")
            if real_missing:
                problems.append(f"可用实例缺方法: {real_missing}")
        if problems:
            return CheckResult("07", "6 个新桥方法 DLL 缺失降级", "FAIL",
                               "; ".join(problems), todos, repro, evidence, details)
        return CheckResult("07", "6 个新桥方法 DLL 缺失降级", "PASS",
                           "mock DLL 缺失 → available=False、6 个 _supports_* 全 False、6 方法各返回 None；可用实例 6 方法绑定齐全",
                           todos, repro, evidence, details)
    finally:
        if degraded is not None and getattr(degraded, "_dll_directory_handle", None) is not None:
            try:
                os.remove_dll_directory(degraded._dll_directory_handle)
            except Exception:  # noqa: BLE001, S110  # 清理失败不影响检查结论
                pass
        fafb._instance = real_instance
        fafb.FafCoreBridge._candidate_paths = orig_method  # type: ignore[method-assign]


def check_08_git_status(_full: bool) -> CheckResult:
    """Check 08：git 无写操作 + core/__init__.py 零改动（只读查询，todo 4/Must NOT）。

    Args:
        _full: 忽略。

    Returns:
        PASS 当暂存区为空（无 git add/commit）且 core/__init__.py 无 diff。
    """
    todos = ["4"]
    repro = ("git status --porcelain=v1；git diff --cached --name-only（须为空，AGENTS.md 铁律，"
             "本检查只读）；git diff --stat -- freeassetfilter/core/__init__.py（须为空，Must NOT _MODULE_MAP）")
    staged = run_git(["diff", "--cached", "--name-only"])
    status = run_git(["status", "--porcelain=v1"])
    if staged.returncode != 0 or status.returncode != 0:
        return CheckResult("08", "git 无写操作 + core/__init__.py 零改动", "FAIL",
                           f"git 只读命令失败: staged rc={staged.returncode}, status rc={status.returncode}",
                           todos, repro)
    staged_files = [l for l in (staged.stdout or "").splitlines() if l.strip()]
    wt_lines = [l for l in (status.stdout or "").splitlines() if l.strip()]
    diff_core = run_git(["diff", "--stat", "--", _rel(CORE_INIT)])
    status_core = run_git(["status", "--porcelain=v1", "--", _rel(CORE_INIT)])
    core_diff_lines = [l for l in (diff_core.stdout or "").splitlines() if l.strip()]
    core_status_lines = [l for l in (status_core.stdout or "").splitlines() if l.strip()]
    details: dict[str, Any] = {
        "staged": staged_files,
        "working_tree_entries": len(wt_lines),
        "core_init_diff_stat": core_diff_lines,
        "core_init_status": core_status_lines,
        "watch_path": _rel(CORE_INIT),
    }
    problems: list[str] = []
    if staged_files:
        problems.append(f"存在暂存区改动（git 写操作发生）: {staged_files}")
    if core_diff_lines or core_status_lines:
        problems.append("core/__init__.py（_MODULE_MAP 载体）出现改动")
    if problems:
        return CheckResult("08", "git 无写操作 + core/__init__.py 零改动", "FAIL",
                           "; ".join(problems), todos, repro, evidence=[], details=details)
    return CheckResult("08", "git 无写操作 + core/__init__.py 零改动", "PASS",
                       "暂存区为空（无 git 操作）；core/__init__.py 零改动（_MODULE_MAP 未改）",
                       todos, repro, evidence=[], details=details)


def check_09_evidence_files(_full: bool) -> CheckResult:
    """Check 09：evidence 文件齐全且非空（task-1..task-25，todo 1-25）。

    task-24 即本脚本的 ``task-24-verify-report.json`` 产物——首次运行报告落盘
    前尚不存在，故仅当文件已存在时纳入必需清单；其余 task-1..23、task-25
    必须存在且非空。

    Args:
        _full: 忽略。

    Returns:
        PASS 当全部必需 task-* 证据存在且非空。
    """
    todos = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
             "11", "12", "13", "14", "15", "16", "17", "18", "19", "20",
             "21", "22", "23", "25"]
    repro = ("Get-ChildItem .omo/evidence/rust-hot-path-native-migration/task-* | "
             "Where-Object Length -eq 0；缺 task-N 即核对对应 todo 的产出；"
             "task-24-verify-report.json 为本次脚本产物")
    evidence = [_rel(EVIDENCE_DIR)]
    if not EVIDENCE_DIR.is_dir():
        return CheckResult("09", "evidence 文件齐全且非空（task-1..task-25）", "FAIL",
                           f"evidence 目录缺失: {_rel(EVIDENCE_DIR)}", todos, repro, evidence)
    files = sorted(p for p in EVIDENCE_DIR.glob("task-*") if p.is_file())
    empty = [_rel(p) for p in files if p.stat().st_size == 0]
    ids_present: dict[int, list[str]] = {}
    for p in files:
        m = re.match(r"task-(\d+)-", p.name)
        if m:
            ids_present.setdefault(int(m.group(1)), []).append(_rel(p))
    required = set(EVIDENCE_BASE_IDS)
    if int(24) in ids_present:
        required.add(24)
    missing = sorted(str(i) for i in sorted(required) if i not in ids_present)
    details: dict[str, Any] = {
        "file_count": len(files),
        "empty": empty,
        "required_todo_ids": sorted(required),
        "missing_todo_ids": missing,
        "present_todo_ids": sorted(ids_present),
    }
    problems: list[str] = []
    if empty:
        problems.append(f"空证据文件: {empty}")
    if missing:
        problems.append(f"缺失证据 todo: {missing}")
    if problems:
        return CheckResult("09", "evidence 文件齐全且非空（task-1..task-25）", "FAIL",
                           "; ".join(problems), todos, repro, evidence, details)
    return CheckResult("09", "evidence 文件齐全且非空（task-1..task-25）", "PASS",
                       f"{len(files)} 个 task-* 证据文件全部非空，todo 1-25 证据齐全"
                       + ("（含本次产物 task-24-verify-report.json）" if 24 in required else ""),
                       todos, repro, evidence, details)


CHECKS: list[tuple[str, str, Callable[[bool], CheckResult]]] = [
    ("01", "dumpbin /exports 导出清单（20 个 faf_* 导出）", check_01_exports),
    ("02", "dumpbin /dependents 白名单（无新增运行时外部 DLL）", check_02_dependents),
    ("03", "依赖 license 表存在（Cargo.toml 注释 + decisions）", check_03_license_table),
    ("04", "既有测试契约全绿（非新增路径回归门逐文件）", check_04_existing_gates),
    ("05", "新增对拍/回退测试全绿（EXIF/PSD/SVG/fluid/7z/PDF）", check_05_new_tests),
    ("06", "benchmark 断言与基线（6 新段 + 高亮 passed:true）", check_06_benchmark),
    ("07", "6 个新桥方法 DLL 缺失降级（mock 探测 False → None）", check_07_bridge_fallback),
    ("08", "git 无写操作 + core/__init__.py 零改动", check_08_git_status),
    ("09", "evidence 文件齐全且非空（task-1..task-25）", check_09_evidence_files),
]


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
        "schema": "verify-faf-core-rust-hot-path/v1",
        "plan": "rust-hot-path-native-migration",
        "plan_file": ".omo/plans/rust-hot-path-native-migration.md",
        "todo": 24,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "overall": overall,
        "summary": counts,
        "failed_ids": failed_ids,
        "repro_commands": {cid: next((c.repro for c in results if c.check_id == cid), "")
                           for cid in failed_ids},
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
    print("rust-hot-path-native-migration 验收自检  todo=24  耗时 "
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
            print(f"  [{cid}] {report['repro_commands'][cid]}")
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
        description="rust-hot-path-native-migration 验收自检脚本（todo 24）"
    )
    parser.add_argument("--report", type=str, default=None,
                        help="覆盖报告输出路径（默认 .omo/evidence/rust-hot-path-native-migration/verification-report.json）")
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