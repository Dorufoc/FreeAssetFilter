#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原子 JSON 读写与损坏文件隔离。

运行期配置/状态文件统一走本模块：

* 写入：同目录临时文件 → ``flush`` → ``fsync`` → ``os.replace``，避免
  断电/崩溃时截断目标文件；
* 读取：主文件损坏时回退 ``<name>.bak``，仍失败则把损坏文件改名为
  ``<name>.corrupt-<时间戳>``，不静默覆盖原始字节；
* 备份：可选的 ``<name>.bak`` 保留上一份成功写入的内容。

本模块只依赖标准库，不导入日志/路径模块，避免初始化期循环。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Optional


def quarantine_corrupt(path: Path | str, suffix: str = ".corrupt") -> Optional[Path]:
    """把损坏文件改名隔离，返回新路径；文件不存在或改名失败返回 None。

    Args:
        path: 损坏文件路径。
        suffix: 隔离文件名前缀后缀，最终形如 ``<name>.corrupt-20261116_120000``。

    Returns:
        Optional[Path]: 隔离后的路径；失败时返回 None。
    """
    source = Path(path)
    if not source.exists():
        return None
    stamp = time.strftime("%Y%m%d_%H%M%S")
    target = source.with_name(f"{source.name}{suffix}-{stamp}")
    counter = 1
    while target.exists():
        target = source.with_name(f"{source.name}{suffix}-{stamp}-{counter}")
        counter += 1
    try:
        os.replace(str(source), str(target))
        return target
    except OSError:
        return None


def write_json_atomic(
    path: Path | str,
    data: Any,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
    backup: bool = False,
    fsync: bool = True,
) -> None:
    """原子写入 JSON 文件。

    Args:
        path: 目标文件路径。
        data: 可 JSON 序列化的对象。
        indent: 缩进宽度。
        ensure_ascii: 是否转义非 ASCII 字符（项目统一为 False）。
        backup: 写入前是否把旧文件复制为 ``<name>.bak``。
        fsync: 是否在替换前刷盘（关键配置建议 True）。

    Raises:
        OSError: 目录创建、临时文件写入或替换失败。
        TypeError: *data* 不可 JSON 序列化。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if backup and target.exists():
        try:
            shutil.copy2(str(target), str(target) + ".bak")
        except OSError:
            # 备份失败不阻断主写入；主文件仍是当前有效版本。
            pass

    temp_name = ""
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(target.parent),
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=ensure_ascii, indent=indent)
            handle.flush()
            if fsync:
                os.fsync(handle.fileno())
        os.replace(temp_name, str(target))
        temp_name = ""
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


def read_json(
    path: Path | str,
    *,
    default: Any = None,
    use_backup: bool = True,
    quarantine: bool = True,
) -> Any:
    """读取 JSON；主文件损坏时尝试 ``.bak``，最后隔离损坏文件并返回默认值。

    Args:
        path: 目标文件路径。
        default: 文件不存在/不可恢复时返回的值。
        use_backup: 是否尝试 ``<name>.bak``。
        quarantine: 是否把不可恢复的损坏文件改名隔离。

    Returns:
        Any: 解析后的 JSON 对象或 *default*。
    """
    target = Path(path)
    try:
        with open(target, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except (OSError, ValueError, TypeError):
        pass

    if use_backup:
        try:
            with open(str(target) + ".bak", "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError, TypeError):
            pass

    if quarantine:
        quarantine_corrupt(target)
    return default


__all__ = [
    "quarantine_corrupt",
    "write_json_atomic",
    "read_json",
]
