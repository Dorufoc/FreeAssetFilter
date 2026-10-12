# -*- coding: utf-8 -*-
"""短路径导入别名收敛测试（freeassetfilter/_import_compat）。

覆盖审查 P2 项：``theme`` / ``components`` 短路径与
``freeassetfilter.ui.*`` 规范路径必须指向同一模块对象（含子模块与
``theme.tm`` 单例），与导入顺序无关。

进程内用例依赖测试会话已导入 ``freeassetfilter``（finder 已安装）；
两个子进程用例分别复刻：
1. 冻结启动顺序 —— 先 import ``pyinstaller_runtime_compat``（runtime
   hook 预加载短名），再走应用导入链；
2. 规范路径先导入、短名后导入。

验证命令：
    python -m pytest tests/unit/ui/test_import_compat.py --timeout 60 -q
"""

# targets: _import_compat

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.unit


def _run_probe(script: str, timeout_s: int = 120) -> subprocess.CompletedProcess:
    """在子进程中执行探针脚本（cwd=仓库根，无头 Qt，UTF-8 输出）。

    Args:
        script: ``python -c`` 执行的探针源码。
        timeout_s: 子进程超时秒数。

    Returns:
        subprocess.CompletedProcess: 含 returncode / stdout / stderr。
    """
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
    )


def test_in_process_aliases_converge() -> None:
    """会话进程内：短名与规范名已是同一模块、同一 ``tm`` 单例。"""
    import freeassetfilter  # noqa: F401 - 安装重定向 finder
    from freeassetfilter._import_compat import install

    install()  # 幂等：重复安装不改变既有收敛结果
    import theme
    import freeassetfilter.ui.theme as canonical_theme

    assert theme is canonical_theme
    assert theme.tm is canonical_theme.tm


#: 冻结 Python 启动顺序探针：runtime hook 先以短名预加载，
#: 应用再经规范路径导入；断言包 / 子模块 / 单例三层收敛。
_FROZEN_ORDER_PROBE = r"""
import os
import sys

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "freeassetfilter", "ui"))

# 复刻 PyInstaller runtime hook：先以短名预加载（finder 尚未安装）。
import pyinstaller_runtime_compat  # noqa: F401

# 应用导入链（规范路径）。
import freeassetfilter  # noqa: F401
import freeassetfilter.ui.theme as ft
import freeassetfilter.ui.components as fc

import theme as t
import components as c

assert t is ft, (t, ft)
assert c is fc, (c, fc)
assert t.tm is ft.tm

# 子模块级收敛
import theme.theme_manager as t_mgr
import freeassetfilter.ui.theme.theme_manager as ft_mgr
assert t_mgr is ft_mgr

import components.file_list_model as c_short
import freeassetfilter.ui.components.file_list_model as c_long
assert c_short is c_long

print("OK")
"""


#: 反向顺序探针：规范路径先导入，短名后导入（含子模块）。
_CANONICAL_FIRST_PROBE = r"""
import os
import sys

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "freeassetfilter", "ui"))

import freeassetfilter.ui.theme as ft
import theme as t
assert t is ft
assert t.tm is ft.tm

import freeassetfilter.ui.theme.app_stylesheet as fas
import theme.app_stylesheet as tas
assert tas is fas

print("OK")
"""


def test_frozen_runtime_import_order_converges() -> None:
    """冻结 runtime hook 顺序（短名先预加载）下两个名称收敛。"""
    completed = _run_probe(_FROZEN_ORDER_PROBE)
    assert completed.returncode == 0, completed.stderr
    assert "OK" in completed.stdout


def test_canonical_first_import_order_converges() -> None:
    """规范路径先导入、短名后导入时两个名称收敛。"""
    completed = _run_probe(_CANONICAL_FIRST_PROBE)
    assert completed.returncode == 0, completed.stderr
    assert "OK" in completed.stdout
