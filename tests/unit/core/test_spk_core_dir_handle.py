# -*- coding: utf-8 -*-
"""spk_core ABI 闸门与目录句柄测试（P3.1 / P3.2）。

锁定五条契约：

1. ``spk_abi_version`` 返回 ``abi == 1`` 且声明支持句柄；
2. 目录句柄可打开、计数、按窗口取行（窗口化，不受 8MB 上限影响）；
3. 句柄上可原地排序（排序后窗口顺序变化）；
4. 非法句柄返回 ``-1`` / ``None`` / ``False``，不抛异常；
5. ``dir_close`` 幂等。

验证命令：
    python -m pytest tests/unit/core/test_spk_core_dir_handle.py -v
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pytest

from sopeek.core.native import api as native_api
from sopeek.core.native.bridges.spk_core_bridge import get_spk_core_bridge

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def bridge() -> Any:
    """原生桥；DLL 不可用或缺句柄导出时跳过。"""
    inst = get_spk_core_bridge()
    if inst is None or not inst.available:
        pytest.skip("spk_core.dll 不可用")
    if not getattr(inst, "_supports_dir_handle", False):
        pytest.skip("spk_core 缺目录句柄导出")
    return inst


@pytest.fixture()
def sample_dir(tmp_path: Path) -> Path:
    """构造 12 个文件的临时目录。"""
    for i in range(12):
        (tmp_path / f"file_{i:02d}.txt").write_text(str(i), encoding="utf-8")
    return tmp_path


def test_abi_version(bridge: Any) -> None:
    """ABI 闸门声明 abi=1 且支持句柄。"""
    info = bridge.abi_version()
    assert info is not None
    assert info.get("abi") == 1
    assert info.get("handles") is True
    assert info.get("handle_cap") == 32
    assert native_api.supports("abi") is True


def test_dir_handle_roundtrip(bridge: Any, sample_dir: Path) -> None:
    """打开 → 计数 → 取窗口 → 排序 → 关闭。"""
    handle = bridge.dir_open(str(sample_dir))
    assert handle > 0
    expected = len(list(sample_dir.iterdir()))
    try:
        assert bridge.dir_count(handle) == expected

        rows: Optional[list] = bridge.dir_rows(handle, 0, 5)
        assert rows is not None and len(rows) == 5
        assert all(isinstance(row, dict) for row in rows)
        assert set(rows[0]) == {
            "name",
            "path",
            "is_dir",
            "size",
            "modified",
            "created",
            "suffix",
            "attrs",
        }

        # 窗口化：越界起点返回空数组而非全量
        assert bridge.dir_rows(handle, 100, 5) == []
        # 非法参数
        assert bridge.dir_rows(handle, -1, 5) is None
        assert bridge.dir_rows(handle, 0, 0) is None

        # 排序：mode 1（名称降序）
        assert bridge.dir_sort(handle, 1) == 0
        sorted_rows = bridge.dir_rows(handle, 0, expected)
        assert sorted_rows is not None
        names = [row["name"] for row in sorted_rows]
        # mode 1 与 ``_python_oracle`` 同口径：名称降序、目录排在文件之后
        # （同目录内 autouse fixture 可能创建 ``spk_test_appdata`` 子目录）。
        expected_names = sorted(
            names,
            key=lambda name: (not (sample_dir / name).is_dir(), name.lower()),
            reverse=True,
        )
        assert names == expected_names
    finally:
        assert bridge.dir_close(handle) is True


def test_invalid_handle_is_safe(bridge: Any) -> None:
    """非法句柄返回值契约，不抛异常。"""
    assert bridge.dir_count(0) == -1
    assert bridge.dir_rows(0, 0, 10) is None
    assert bridge.dir_sort(0, 0) == -1
    assert bridge.dir_close(0) is False


def test_dir_close_is_idempotent(bridge: Any, sample_dir: Path) -> None:
    """关闭两次：第二次返回 False。"""
    handle = bridge.dir_open(str(sample_dir))
    assert handle > 0
    assert bridge.dir_close(handle) is True
    assert bridge.dir_close(handle) is False


def test_dir_open_missing_path(bridge: Any, tmp_path: Path) -> None:
    """不存在的目录返回 0。"""
    assert bridge.dir_open(str(tmp_path / "no_such_dir")) == 0


def test_dir_next_streaming_cursor(bridge: Any, sample_dir: Path) -> None:
    """流式游标：分块取完，每块 ≤ max_count，总量等于条目数。"""
    expected = len(list(sample_dir.iterdir()))
    handle = bridge.dir_open(str(sample_dir))
    assert handle > 0
    try:
        sizes = []
        while True:
            chunk = bridge.dir_next(handle, 5)
            assert chunk is not None
            if not chunk:
                break
            assert len(chunk) <= 5
            sizes.append(len(chunk))
        assert sum(sizes) == expected
        # 耗尽后仍返回空数组（幂等）
        assert bridge.dir_next(handle, 5) == []
    finally:
        bridge.dir_close(handle)


def test_dir_cancel_stops_stream_and_sort(bridge: Any, sample_dir: Path) -> None:
    """取消后 next 返回空数组、sort 拒绝执行（P3.7）。"""
    handle = bridge.dir_open(str(sample_dir))
    assert handle > 0
    try:
        assert bridge.dir_cancel(handle) is True
        assert bridge.dir_next(handle, 5) == []
        assert bridge.dir_sort(handle, 0) == -1
    finally:
        bridge.dir_close(handle)
    assert bridge.dir_cancel(0) is False


def test_dir_rows_pod_matches_json_rows(bridge: Any, sample_dir: Path) -> None:
    """POD 通道与 JSON 通道逐字段一致（P3.3）。"""
    handle = bridge.dir_open(str(sample_dir))
    assert handle > 0
    try:
        assert bridge.dir_sort(handle, 1) == 0
        json_rows = bridge.dir_rows(handle, 0, 10)
        pod_rows = bridge.dir_rows_pod(handle, 0, 10)
        assert pod_rows is not None
        assert pod_rows == json_rows
        # 非法参数/句柄
        assert bridge.dir_rows_pod(handle, 0, 0) is None
        assert bridge.dir_rows_pod(handle, -1, 5) is None
        assert bridge.dir_rows_pod(0, 0, 5) is None
    finally:
        bridge.dir_close(handle)


def test_api_facade_dir_handle(sample_dir: Path) -> None:
    """门面暴露的 dir_* 与 supports 一致。"""
    if not native_api.supports("dirhandle"):
        pytest.skip("dirhandle 不可用")
    handle = native_api.dir_open(str(sample_dir))
    assert handle > 0
    try:
        assert native_api.dir_count(handle) == len(list(sample_dir.iterdir()))
        assert native_api.dir_rows(handle, 0, 3) is not None
        assert native_api.dir_sort(handle, 0) == 0
    finally:
        assert native_api.dir_close(handle) is True


# ── P3.6：句柄内排序 + 窗口取行（排序结果不回传） ────────────────────────────


def _python_oracle(rows: list, mode: int) -> list:
    """与 ``FileSelectorLayout._sort_entries`` 同口径的纯 Python 排序。"""
    rows = [dict(row) for row in rows]
    if mode >= 2:
        rows.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    if mode == 0:
        rows.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    elif mode == 1:
        rows.sort(
            key=lambda x: (not x["is_dir"], x["name"].lower()), reverse=True
        )
    elif mode == 2:
        rows.sort(key=lambda x: (not x["is_dir"], x.get("modified", "")), reverse=True)
    elif mode == 3:
        rows.sort(key=lambda x: (not x["is_dir"], x.get("modified", "")))
    elif mode == 4:
        rows.sort(key=lambda x: (not x["is_dir"], x.get("size", 0)), reverse=True)
    elif mode == 5:
        rows.sort(key=lambda x: (not x["is_dir"], x.get("size", 0)))
    elif mode == 6:
        rows.sort(key=lambda x: (not x["is_dir"], x.get("created", "")), reverse=True)
    elif mode == 7:
        rows.sort(key=lambda x: (not x["is_dir"], x.get("created", "")))
    return rows


@pytest.mark.parametrize("mode", list(range(8)))
def test_dir_sort_window_matches_python_oracle(
    bridge: Any, sample_dir: Path, mode: int
) -> None:
    """P3.6：句柄排序 + 窗口取行与 Python oracle 逐条相等（8 模式）。"""
    handle = bridge.dir_open(str(sample_dir))
    assert handle > 0
    try:
        total = bridge.dir_count(handle)
        window = bridge.dir_sort_window(handle, mode, 0, total)
        assert window is not None
        assert len(window) == total
        baseline = bridge.dir_open(str(sample_dir))
        assert baseline > 0
        try:
            raw = bridge.dir_rows(baseline, 0, total)
        finally:
            bridge.dir_close(baseline)
        assert window == _python_oracle(raw, mode)
    finally:
        bridge.dir_close(handle)


def test_dir_sort_window_is_windowed(bridge: Any, sample_dir: Path) -> None:
    """P3.6：排序后可只取任意窗口，拼接等于全量（不回传全量）。"""
    handle = bridge.dir_open(str(sample_dir))
    assert handle > 0
    try:
        total = bridge.dir_count(handle)
        first = bridge.dir_sort_window(handle, 0, 0, 4)
        assert first is not None and len(first) == 4
        # 后续窗口不重排序（句柄已就位），直接取行
        rest = bridge.dir_rows(handle, 4, total)
        assert rest is not None
        full = bridge.dir_sort_window(handle, 0, 0, total)
        assert full is not None
        assert first + rest == full
    finally:
        bridge.dir_close(handle)


def test_dir_rows_prefers_pod_without_behaviour_change(
    bridge: Any, sample_dir: Path
) -> None:
    """P3.5：POD 通道可用时 ``dir_rows`` 仍返回与 JSON 通道一致的 7 键行。"""
    if not getattr(bridge, "_supports_dir_rows_pod", False):
        pytest.skip("DLL 缺 spk_dir_rows_pod 导出")
    handle = bridge.dir_open(str(sample_dir))
    assert handle > 0
    try:
        pod_rows = bridge.dir_rows(handle, 0, 5)
        json_rows = bridge._call_json_list_export(
            lambda: bridge._native_dir_rows(handle, 0, 5)
        )
        assert pod_rows == json_rows
        assert set(pod_rows[0]) == {
            "name",
            "path",
            "is_dir",
            "size",
            "modified",
            "created",
            "suffix",
            # P3.4：内置通道额外携带 Windows 属性位（与 st_file_attributes 同源）
            "attrs",
        }
    finally:
        bridge.dir_close(handle)
