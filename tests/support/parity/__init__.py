"""Parity-test helper:逐字段断言 python-impl 与 native-impl 输出一致。

比较 dict/list 嵌套结构并输出字段级差异；调用方可通过 accepted-diffs
清单注入已知允许的分歧（命中清单的差异不再 FAIL）。

本包由 faf-core-rust-migration todo 5 创建；``normalize_html`` 模块为
todo 15/17 预留位置（实现留到对应 todo，本包只占位对齐目录结构）。
"""

from __future__ import annotations

from tests.support.parity.comparator import (
    ParityMismatchError,
    assert_parity,
    diff_values,
    is_accepted,
)

__all__ = [
    "ParityMismatchError",
    "assert_parity",
    "diff_values",
    "is_accepted",
]
