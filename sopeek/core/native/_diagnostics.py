"""诊断/证据产物的路径解析（审查 3.1#27：发行环境不再写仓库 .omo）。

约定
----
* ``SPK_EVIDENCE_DIR`` 环境变量优先：显式指定时所有诊断产物写入该目录；
* 未指定且处于开发态（源码运行，``sys.frozen`` 为假）时，沿用仓库内
  ``.omo/evidence/performance-ceiling-optimization`` 证据目录，保留原有
  开发工作流与测试断言；
* 冻结/打包态落盘到 ``<exe目录>/data/diagnostics``，与 ``app_logger``
  冻结态写 ``<exe目录>/data/logs`` 的既有约定一致，避免写只读的程序目录。

诊断脚本查找（如 GPU affinity 探针）
------------------------------------
* ``SPK_GPU_DIAG_SCRIPT`` 环境变量优先；
* 未设置时回退仓库内 task-3 脚本（存在才使用，调用方自行判存）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: 计划证据在仓库内的相对目录（开发态默认根）。
REPO_EVIDENCE_REL = Path(".omo") / "evidence" / "performance-ceiling-optimization"

#: GPU affinity 诊断脚本在仓库内的相对路径（开发态默认）。
REPO_GPU_DIAG_REL = REPO_EVIDENCE_REL / "task-3" / "gpu_affinity_check.py"


def _repo_root() -> Path:
    """仓库根：``sopeek/core/native/_diagnostics.py`` 上溯三级。"""
    return Path(__file__).resolve().parents[3]


def diagnostics_root() -> Path:
    """返回诊断产物根目录（不创建，调用方按需 ``mkdir``）。

    Returns:
        * 设置了 ``SPK_EVIDENCE_DIR`` 时：该目录；
        * 冻结态：``<exe目录>/data/diagnostics``；
        * 开发态：仓库 ``.omo/evidence/performance-ceiling-optimization``。
    """
    override = os.environ.get("SPK_EVIDENCE_DIR", "").strip()
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "data" / "diagnostics"
    return _repo_root() / REPO_EVIDENCE_REL


def gpu_diag_script() -> Path:
    """返回 GPU affinity 诊断脚本路径（可能不存在，调用方自行判存）。

    Returns:
        * 设置了 ``SPK_GPU_DIAG_SCRIPT`` 时：该路径；
        * 否则：仓库内 task-3 脚本的默认路径。
    """
    override = os.environ.get("SPK_GPU_DIAG_SCRIPT", "").strip()
    if override:
        return Path(override)
    return _repo_root() / REPO_GPU_DIAG_REL


__all__ = [
    "REPO_EVIDENCE_REL",
    "REPO_GPU_DIAG_REL",
    "diagnostics_root",
    "gpu_diag_script",
]
