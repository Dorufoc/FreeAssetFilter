# -*- coding: utf-8 -*-
"""P3.4 流式扫描游标（`faf_scan_begin/next/free`）与 UI 派发测试。

锁定五条契约：

1. 游标分批覆盖全部条目（每批 ≤ max），耗尽后幂等返回空数组；
2. 每行携带 ``attrs``（Windows 属性位），且 7 键字段与 Python 收集器一致；
3. 非法句柄 / 非正上限返回 ``None``，``free`` 幂等；
4. UI 侧 ``_iter_directory_batches`` 在 native 可用时走游标并把属性位写进
   ``attrs_out``（**不**泄漏到 7 键条目）；
5. native 不可用（旧 DLL / 关闭开关）时自动回退 Python 逐批，语义一致。

验证命令：
    python -m pytest tests/unit/ui/layout/test_file_selector_native_stream.py -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest

from freeassetfilter.core.native import api as native_api

#: 布局模块用短路径导入，需 ``freeassetfilter/ui`` 在 sys.path。
_UI_ROOT: str = str(Path(__file__).resolve().parents[3] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.layout import file_selector_layout as fsl_mod  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture()
def sample_dir(tmp_path: Path) -> Path:
    """构造 5 个文件的临时目录（其中 1 个隐藏文件）。"""
    for index in range(4):
        (tmp_path / f"file_{index}.txt").write_text(str(index), encoding="utf-8")
    hidden = tmp_path / "hidden.txt"
    hidden.write_text("h", encoding="utf-8")
    try:
        import ctypes

        FILE_ATTRIBUTE_HIDDEN = 0x2
        ctypes.windll.kernel32.SetFileAttributesW(  # type: ignore[attr-defined]
            str(hidden), FILE_ATTRIBUTE_HIDDEN
        )
    except Exception:  # noqa: BLE001 - 非 Windows / 权限不足时保持普通文件
        pass
    return tmp_path


def _require_stream() -> None:
    """DLL 或导出缺失时跳过。"""
    if not native_api.supports("scanstream"):
        pytest.skip("faf_core 流式扫描导出不可用")


def _drain(path: Path, chunk: int) -> List[Dict[str, Any]]:
    """用游标读完整个目录，返回行列表。"""
    handle = native_api.scan_begin(str(path))
    assert handle > 0
    rows: List[Dict[str, Any]] = []
    try:
        while True:
            batch = native_api.scan_next(handle, chunk)
            assert batch is not None
            if not batch:
                break
            assert len(batch) <= chunk
            rows.extend(batch)
    finally:
        assert native_api.scan_free(handle) is True
    return rows


def test_scan_stream_covers_all_entries(sample_dir: Path) -> None:
    """分块读完，总量与目录项数一致；耗尽后幂等。"""
    _require_stream()
    rows = _drain(sample_dir, 2)
    assert len(rows) == len(list(os.scandir(sample_dir)))


def test_scan_stream_rows_match_python_collector(sample_dir: Path) -> None:
    """7 键字段与 Python 收集器逐字段一致，并额外带 ``attrs``。"""
    _require_stream()
    rows = _drain(sample_dir, 3)
    python_rows = fsl_mod.FileSelectorLayout._collect_directory_entries_python(
        str(sample_dir)
    )
    assert python_rows is not None
    by_name = {row["name"]: row for row in python_rows}
    assert set(by_name) == {row["name"] for row in rows}
    for row in rows:
        assert "attrs" in row
        reference = by_name[row["name"]]
        for field in ("path", "is_dir", "size", "modified", "created", "suffix"):
            assert row[field] == reference[field], field


def test_scan_stream_bad_calls(sample_dir: Path) -> None:
    """非法句柄/上限返回 None；free 幂等。"""
    _require_stream()
    assert native_api.scan_next(0, 4) is None
    assert native_api.scan_free(0) is False
    handle = native_api.scan_begin(str(sample_dir))
    assert handle > 0
    try:
        assert native_api.scan_next(handle, 0) is None
    finally:
        assert native_api.scan_free(handle) is True
    assert native_api.scan_free(handle) is False
    assert native_api.scan_begin(str(sample_dir / "no_such_dir")) == 0


def test_scan_begin_returns_zero_without_support(
    sample_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """能力缺失时门面返回 0（调用方据此回退）。"""
    monkeypatch.setattr(native_api, "supports", lambda capability: False)
    assert native_api.scan_begin(str(sample_dir)) == 0
    assert native_api.scan_next(1, 4) is None
    assert native_api.scan_free(1) is False


def _collect(
    path: str, attrs_out: Optional[Dict[str, int]] = None
) -> Iterator[Tuple[List[Dict[str, Any]], bool]]:
    """调用生产入口（含 native 派发）。"""
    return fsl_mod.FileSelectorLayout._iter_directory_batches(
        path,
        False,
        lambda: False,
        batch_size=2,
        attrs_out=attrs_out,
    )


def test_ui_dispatch_uses_native_stream_and_keeps_seven_keys(
    sample_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """native 可用：批次来自游标，``attrs`` 进旁路表且不留在条目里。"""
    _require_stream()
    monkeypatch.setattr(fsl_mod, "NATIVE_STREAM_ENABLED", True)
    attrs: Dict[str, int] = {}
    batches = list(_collect(str(sample_dir), attrs))
    assert batches, "至少应有一批"
    assert batches[-1][1] is True
    assert all(is_final is False for _batch, is_final in batches[:-1])

    rows = [row for batch, _final in batches for row in batch]
    assert len(rows) == len(list(os.scandir(sample_dir)))
    assert set(attrs) == {row["name"] for row in rows}
    for row in rows:
        assert "attrs" not in row
        assert set(row) == {
            "name",
            "path",
            "is_dir",
            "size",
            "modified",
            "created",
            "suffix",
        }


def test_ui_dispatch_falls_back_to_python(
    sample_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """关闭开关或 native 缺失：走 Python 逐批，条目与属性位仍完整。"""
    monkeypatch.setattr(fsl_mod, "NATIVE_STREAM_ENABLED", False)
    attrs: Dict[str, int] = {}
    batches = list(_collect(str(sample_dir), attrs))
    rows = [row for batch, _final in batches for row in batch]
    assert len(rows) == len(list(os.scandir(sample_dir)))
    assert set(attrs) == {row["name"] for row in rows}
    assert batches[-1][1] is True


def test_ui_dispatch_falls_back_when_begin_fails(
    sample_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """游标打不开（返回 0）时不得丢条目。"""
    monkeypatch.setattr(fsl_mod, "NATIVE_STREAM_ENABLED", True)
    monkeypatch.setattr(native_api, "supports", lambda capability: True)
    monkeypatch.setattr(native_api, "scan_begin", lambda path: 0)
    batches = list(_collect(str(sample_dir), {}))
    rows = [row for batch, _final in batches for row in batch]
    assert len(rows) == len(list(os.scandir(sample_dir)))


def test_ui_dispatch_handles_midway_failure(
    sample_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """中途 scan_next 失败：已交付批次保留，且以 ``([], True)`` 收尾。"""
    monkeypatch.setattr(fsl_mod, "NATIVE_STREAM_ENABLED", True)
    monkeypatch.setattr(native_api, "supports", lambda capability: True)
    monkeypatch.setattr(native_api, "scan_begin", lambda path: 42)
    monkeypatch.setattr(native_api, "scan_free", lambda handle: True)
    calls: List[int] = []

    def _next(handle: int, count: int) -> Optional[List[Dict[str, Any]]]:
        calls.append(count)
        if len(calls) == 1:
            return [
                {
                    "name": "a.txt",
                    "path": str(sample_dir / "a.txt"),
                    "is_dir": False,
                    "size": 1,
                    "modified": "2026-01-01 00:00",
                    "created": "2026-01-01 00:00",
                    "suffix": "txt",
                    "attrs": 0,
                },
                {
                    "name": "b.txt",
                    "path": str(sample_dir / "b.txt"),
                    "is_dir": False,
                    "size": 1,
                    "modified": "2026-01-01 00:00",
                    "created": "2026-01-01 00:00",
                    "suffix": "txt",
                    "attrs": 0,
                },
            ]
        return None

    monkeypatch.setattr(native_api, "scan_next", _next)
    batches = list(_collect(str(sample_dir), {}))
    assert len(batches) == 2
    assert [row["name"] for row in batches[0][0]] == ["a.txt", "b.txt"]
    assert batches[0][1] is False
    assert batches[1] == ([], True)
