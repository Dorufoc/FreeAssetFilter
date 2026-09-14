"""逐字段 parity 断言：python-impl 输出 vs native-impl 输出。

差异路径记法（JSONPath 风格子集）：
- 字典键：``$.entries``、``$.entries.size``
- 列表下标：``$.entries[0]``、``$.entries[0].name``

accepted-diffs 条目命中规则：某条差异路径与清单条目相等，或以
``条目 + "."`` / ``条目 + "["`` 开头，即视为命中（允许用父路径豁免整棵子树）。
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence


class ParityMismatchError(AssertionError):
    """parity 断言失败：仍有未被 accepted-diffs 豁免的字段差异。

    Attributes:
        diffs: 未豁免的差异明细行。
        accepted: 被清单豁免的差异明细行（仅供排查）。
    """

    def __init__(self, diffs: List[str], accepted: List[str]) -> None:
        self.diffs: List[str] = list(diffs)
        self.accepted: List[str] = list(accepted)
        detail: str = "\n".join(f"  - {line}" for line in diffs)
        super().__init__(f"parity mismatch ({len(diffs)} diffs):\n{detail}")


def is_accepted(diff_path: str, accepted_diffs: Sequence[str]) -> bool:
    """判断某条差异路径是否命中 accepted-diffs 清单。

    Args:
        diff_path: 差异路径（如 ``$.entries[0].name``）。
        accepted_diffs: 允许分歧清单（路径或父路径前缀）。

    Returns:
        bool: 命中清单为 True，否则 False。
    """
    for entry in accepted_diffs:
        if diff_path == entry:
            return True
        if diff_path.startswith(entry + ".") or diff_path.startswith(entry + "["):
            return True
    return False


def _format_value(value: Any) -> str:
    """把差异中的值格式化为短字符串（防超长刷屏）。

    Args:
        value: 任意值。

    Returns:
        str: 截断到 120 字符的 repr。
    """
    text: str = repr(value)
    if len(text) > 120:
        text = text[:117] + "..."
    return text


def diff_values(python_value: Any, native_value: Any, path: str = "$") -> List[str]:
    """递归比较两个值并返回字段级差异明细。

    dict 按键逐字段比较（缺键/多键分别报告）；list 先比长度再逐下标；
    float 与 int 混合时按数值比较（``1 == 1.0`` 视为相等）；其余类型
    ``!=`` 即报告差异。

    Args:
        python_value: python-impl 侧输出。
        native_value: native-impl 侧输出。
        path: 当前路径（递归用，调用方保持默认）。

    Returns:
        list[str]: 差异明细行（每行以路径开头）；无差异返回空列表。
    """
    if isinstance(python_value, dict) and isinstance(native_value, dict):
        diffs: List[str] = []
        for key in python_value:
            child: str = f"{path}.{key}"
            if key not in native_value:
                diffs.append(f"{child}: missing in native (python={_format_value(python_value[key])})")
            else:
                diffs.extend(diff_values(python_value[key], native_value[key], child))
        for key in native_value:
            if key not in python_value:
                diffs.append(
                    f"{path}.{key}: extra in native (native={_format_value(native_value[key])})"
                )
        return diffs
    if isinstance(python_value, list) and isinstance(native_value, list):
        diffs = []
        if len(python_value) != len(native_value):
            diffs.append(
                f"{path}: list length differs "
                f"(python={len(python_value)} native={len(native_value)})"
            )
        for index, (item_py, item_rs) in enumerate(zip(python_value, native_value)):
            diffs.extend(diff_values(item_py, item_rs, f"{path}[{index}]"))
        return diffs
    if isinstance(python_value, bool) or isinstance(native_value, bool):
        # bool 必须严格同类型比较（Python 里 True == 1，parity 下视为分歧）。
        if type(python_value) is not type(native_value) or python_value != native_value:
            return [
                f"{path}: value differs "
                f"(python={_format_value(python_value)} native={_format_value(native_value)})"
            ]
        return []
    if isinstance(python_value, (int, float)) and isinstance(native_value, (int, float)):
        if python_value != native_value:
            return [
                f"{path}: value differs "
                f"(python={_format_value(python_value)} native={_format_value(native_value)})"
            ]
        return []
    if python_value != native_value:
        return [
            f"{path}: value differs "
            f"(python={_format_value(python_value)} native={_format_value(native_value)})"
        ]
    return []


def assert_parity(
    python_value: Any,
    native_value: Any,
    accepted_diffs: Optional[Sequence[str]] = None,
) -> List[str]:
    """断言两实现输出 parity 一致（未豁免差异 → 抛错）。

    Args:
        python_value: python-impl 侧输出（dict/list 嵌套结构）。
        native_value: native-impl 侧输出（同形结构）。
        accepted_diffs: 允许分歧清单（路径前缀）；命中则豁免。

    Returns:
        list[str]: 全部差异明细（含被豁免的）；一致时为空列表。

    Raises:
        ParityMismatchError: 存在未被清单豁免的差异，错误消息内含差异明细。
    """
    accepted: Sequence[str] = accepted_diffs or []
    all_diffs: List[str] = diff_values(python_value, native_value)
    remaining: List[str] = []
    waived: List[str] = []
    for line in all_diffs:
        diff_path: str = line.split(":", 1)[0]
        if is_accepted(diff_path, accepted):
            waived.append(line)
        else:
            remaining.append(line)
    if remaining:
        raise ParityMismatchError(remaining, waived)
    return all_diffs
