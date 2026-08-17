# -*- coding: utf-8 -*-
"""``FileListLoaderThread``（core/workers/file_list_loader.py）单元测试。

覆盖（happy + boundary/error 各至少一条）：

* 正常目录扫描 —— loaded 信号携带 path + 文件字典列表；隐藏文件跳过、
  目录 is_dir=True、suffix 提取、大小/时间字段齐全
* "All" 模式 —— win32 平台 mock ``GetLogicalDrives`` 位掩码下的盘符条目
  （禁止真实枚举整机磁盘）；非 win32 回退为根目录 ``/``
* error —— 不存在的路径 → ``failed`` 信号携带路径与错误串；
  符号链接路径 → OSError → ``failed``（mock ``os.path.islink``）
* scandir 内部分支 —— 点文件跳过、符号链接条目跳过、stat 抛
  ``PermissionError`` 的条目被静默忽略，其余条目完整入列

线程纪律（AGENTS.md / learnings W7）：``run()`` 本体在 Qt 原生线程执行时
**不被 coverage.py 追踪**（``sys.settrace`` 不进入 Qt 线程），因此本文件统一
**同步调用 ``thread.run()``** 驱动扫描逻辑（信号按直连在调用线程内同步派发），
以覆盖 run() 全部分支——这是既有 learnings 固化且验证的模式。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from freeassetfilter.core.workers.file_list_loader import FileListLoaderThread
from tests.support.data_factories import make_image, make_text

pytestmark = pytest.mark.unit


class _FakeEntry:
    """模拟 ``os.DirEntry``：可控 name/path/is_dir/is_symlink/stat。"""

    def __init__(
        self,
        name: str,
        path: str,
        is_dir: bool = False,
        is_symlink: bool = False,
        stat_error: bool = False,
    ) -> None:
        self.name = name
        self.path = path
        self._is_dir = is_dir
        self._is_symlink = is_symlink
        self._stat_error = stat_error

    def is_dir(self, follow_symlinks: bool = False) -> bool:
        """模拟 ``DirEntry.is_dir``。

        Args:
            follow_symlinks: 是否跟随符号链接（本替身忽略）。

        Returns:
            bool: 是否目录。
        """
        return self._is_dir

    def is_symlink(self) -> bool:
        """模拟 ``DirEntry.is_symlink``。

        Returns:
            bool: 是否符号链接条目。
        """
        return self._is_symlink

    def stat(self, follow_symlinks: bool = False) -> SimpleNamespace:
        """模拟 ``DirEntry.stat``；``stat_error`` 时抛 PermissionError。

        Args:
            follow_symlinks: 是否跟随符号链接（本替身忽略）。

        Returns:
            SimpleNamespace: 带 st_size/st_mtime/st_ctime 的假 stat 结果。

        Raises:
            PermissionError: 当 ``stat_error`` 为 True 时。
        """
        if self._stat_error:
            raise PermissionError("权限不足（模拟）")
        return SimpleNamespace(
            st_size=42,
            st_mtime=1234567890,
            st_ctime=1234567890,
        )


class _FakeScandir:
    """可复用的 ``os.scandir`` 上下文管理器替身。"""

    def __init__(self, entries: List[_FakeEntry]) -> None:
        self._entries = entries

    def __enter__(self) -> "_FakeScandir":
        """进入上下文（被 ``with`` 使用）。"""
        return self

    def __exit__(self, *_args: Any) -> bool:
        """退出上下文，不吞异常。"""
        return False

    def __iter__(self) -> Any:
        """迭代返回注入的条目列表迭代器。"""
        return iter(self._entries)


def test_loaded_scans_normal_directory(qapp: Any, tmp_path: Path) -> None:
    """happy：正常目录扫描后 loaded 携带路径与文件字典列表。

    Args:
        qapp: session QApplication。
        tmp_path: 临时目录。
    """
    make_image(str(tmp_path / "pic.png"))
    make_text(str(tmp_path / "note.txt"))
    (tmp_path / ".hidden").write_text("hidden", encoding="utf-8")
    sub: Path = tmp_path / "subdir"
    sub.mkdir()

    received: List[Tuple[str, List[Dict[str, Any]]]] = []
    thread: FileListLoaderThread = FileListLoaderThread(str(tmp_path))
    thread.loaded.connect(lambda p, files: received.append((p, files)))
    # 同步 run()：QThread.start() 的 run 本体在 Qt 原生线程执行，coverage 无法追踪。
    thread.run()

    assert received, "loaded 未发出"
    path, files = received[0]
    assert path == str(tmp_path)
    names: List[str] = [f["name"] for f in files]
    assert "note.txt" in names
    assert "pic.png" in names
    assert "subdir" in names
    assert ".hidden" not in names  # 隐藏文件跳过

    pic: Dict[str, Any] = next(f for f in files if f["name"] == "pic.png")
    assert pic["is_dir"] is False
    assert pic["size"] > 0
    assert pic["suffix"] == "png"
    assert pic["path"].endswith("pic.png")
    assert pic["modified"]  # ISO 时间非空

    subdir: Dict[str, Any] = next(f for f in files if f["name"] == "subdir")
    assert subdir["is_dir"] is True


def test_loaded_empty_directory(qapp: Any, tmp_path: Path) -> None:
    """boundary：空目录 loaded 携带空文件列表。

    Args:
        qapp: session QApplication。
        tmp_path: 临时目录。
    """
    received: List[Tuple[str, List[Dict[str, Any]]]] = []
    empty: Path = tmp_path / "empty"
    empty.mkdir()
    thread: FileListLoaderThread = FileListLoaderThread(str(empty))
    thread.loaded.connect(lambda p, files: received.append((p, files)))
    thread.run()

    assert received[0][0] == str(empty)
    assert received[0][1] == []


def test_all_mode_mocked_windows_drives(qapp: Any, tmp_path: Path, monkeypatch: Any) -> None:
    """happy（win32）：All 模式 mock GetLogicalDrives 后 loaded 盘符条目。

    os.stat 被 monkeypatch 成稳定假值，确保盘符 stat 成功分支（
    modified/created 有值）确定性覆盖，不依赖测试机真实驱动器存在。

    Args:
        qapp: session QApplication。
        tmp_path: 临时目录。
        monkeypatch: pytest monkeypatch fixture。
    """
    if sys.platform != "win32":
        pytest.skip("win32 All 模式需要模拟盘符位掩码")

    received: List[Tuple[str, List[Dict[str, Any]]]] = []
    fake_stat = SimpleNamespace(st_mtime=1000, st_ctime=2000)
    monkeypatch.setattr(os, "stat", lambda _p: fake_stat)
    with patch("ctypes.windll.kernel32.GetLogicalDrives", return_value=0b101):
        thread = FileListLoaderThread("All")
        thread.loaded.connect(lambda p, files: received.append((p, files)))
        thread.run()

    path, files = received[0]
    assert path == "All"
    names: List[str] = [f["name"] for f in files]
    assert "A:" in names
    assert "C:" in names
    drive_a: Dict[str, Any] = next(f for f in files if f["name"] == "A:")
    assert drive_a["is_dir"] is True
    assert drive_a["path"] in ("A:\\", "A:/")
    assert drive_a["size"] == 0
    assert drive_a["modified"]  # stat 成功 → 有 ISO 时间


def test_all_mode_windows_drive_stat_error(qapp: Any, monkeypatch: Any) -> None:
    """boundary（win32）：盘符 stat 抛 OSError → modified/created 兜底为空串。

    test_manual: monkeypatch os.stat 抛 OSError，断言条目仍生成且时间为空。

    Args:
        qapp: session QApplication。
        monkeypatch: pytest monkeypatch fixture。
    """
    if sys.platform != "win32":
        pytest.skip("win32 All 模式需要模拟盘符位掩码")

    received: List[Tuple[str, List[Dict[str, Any]]]] = []

    def _raise_oserror(_p: str) -> Any:
        raise OSError("模拟盘符不可访问")

    monkeypatch.setattr(os, "stat", _raise_oserror)
    with patch("ctypes.windll.kernel32.GetLogicalDrives", return_value=0b101):
        thread = FileListLoaderThread("All")
        thread.loaded.connect(lambda p, files: received.append((p, files)))
        thread.run()

    path, files = received[0]
    assert path == "All"
    assert len(files) == 2  # A: 与 C: 均生成（即使 stat 失败）
    for f in files:
        assert f["modified"] == ""
        assert f["created"] == ""


def test_all_mode_root_on_non_win32(qapp: Any, monkeypatch: Any) -> None:
    """boundary（非 win32）：All 模式回退为根目录 ``/`` 一个条目。

    test_manual: monkeypatch sys.platform='linux' + os.stat 假值，断言根条目。

    Args:
        qapp: session QApplication。
        monkeypatch: pytest monkeypatch fixture。
    """
    received: List[Tuple[str, List[Dict[str, Any]]]] = []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        os, "stat", lambda _p: SimpleNamespace(st_mtime=1000, st_ctime=2000)
    )
    thread = FileListLoaderThread("All")
    thread.loaded.connect(lambda p, files: received.append((p, files)))
    thread.run()

    path, files = received[0]
    assert path == "All"
    assert len(files) == 1
    assert files[0]["name"] == "/"
    assert files[0]["is_dir"] is True
    assert files[0]["modified"]


def test_all_mode_root_stat_error_on_non_win32(qapp: Any, monkeypatch: Any) -> None:
    """boundary（非 win32）：根目录 stat 抛 OSError → 时间兜底为空串。

    Args:
        qapp: session QApplication。
        monkeypatch: pytest monkeypatch fixture。
    """

    def _raise_oserror(_p: str) -> Any:
        raise OSError("模拟根目录不可访问")

    received: List[Tuple[str, List[Dict[str, Any]]]] = []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "stat", _raise_oserror)
    thread = FileListLoaderThread("All")
    thread.loaded.connect(lambda p, files: received.append((p, files)))
    thread.run()

    path, files = received[0]
    assert path == "All"
    assert len(files) == 1
    assert files[0]["modified"] == ""
    assert files[0]["created"] == ""


def test_failed_on_nonexistent_path(qapp: Any, tmp_path: Path) -> None:
    """error：不存在的目录触发 failed 信号（路径 + 错误串）。

    Args:
        qapp: session QApplication。
        tmp_path: 临时目录。
    """
    missing: str = str(tmp_path / "nope")
    received: List[Tuple[str, str]] = []
    thread: FileListLoaderThread = FileListLoaderThread(missing)
    thread.failed.connect(lambda p, err: received.append((p, err)))
    thread.run()

    assert received, "failed 未发出"
    assert received[0][0] == missing
    assert received[0][1]  # 错误信息非空


def test_failed_on_symlink_path(qapp: Any, tmp_path: Path, monkeypatch: Any) -> None:
    """error：符号链接路径触发 failed（mock os.path.islink 返回 True）。

    test_manual: ``monkeypatch.setattr(os.path, "islink", ...)`` 返回
    True 模拟符号链接，断言 failed 信号中含 OSError 消息。

    Args:
        qapp: session QApplication。
        tmp_path: 临时目录。
        monkeypatch: pytest monkeypatch fixture。
    """
    received: List[Tuple[str, str]] = []
    monkeypatch.setattr(os.path, "islink", lambda _p: True)
    thread: FileListLoaderThread = FileListLoaderThread(str(tmp_path))
    thread.failed.connect(lambda p, err: received.append((p, err)))
    thread.run()

    assert received[0][0] == str(tmp_path)
    assert "符号链接" in received[0][1] or "拒绝扫描" in received[0][1]


def test_scandir_skips_hidden_symlink_and_stat_errors(
    qapp: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """boundary：scandir 内部分支——点文件、符号链接、stat 错误全被跳过。

    使用 ``_FakeScandir`` / ``_FakeEntry`` 注入可控条目，确定性覆盖
    隐藏文件跳过、``is_symlink()`` 跳过、``stat()`` 抛 PermissionError
    时的 ``except (OSError, PermissionError): continue`` 分支。

    Args:
        qapp: session QApplication。
        tmp_path: 临时目录。
        monkeypatch: pytest monkeypatch fixture。
    """
    entries: List[_FakeEntry] = [
        _FakeEntry(".dot", str(tmp_path / ".dot")),
        _FakeEntry("target.txt", str(tmp_path / "target.txt"), is_symlink=True),
        _FakeEntry("locked.txt", str(tmp_path / "locked.txt"), stat_error=True),
        _FakeEntry("a.txt", str(tmp_path / "a.txt")),
        _FakeEntry("sub", str(tmp_path / "sub"), is_dir=True),
    ]
    monkeypatch.setattr(os, "scandir", lambda _p: _FakeScandir(entries))

    received: List[Tuple[str, List[Dict[str, Any]]]] = []
    thread: FileListLoaderThread = FileListLoaderThread(str(tmp_path))
    thread.loaded.connect(lambda p, files: received.append((p, files)))
    thread.run()

    path, files = received[0]
    assert path == str(tmp_path)
    names: List[str] = [f["name"] for f in files]
    assert names == ["a.txt", "sub"]  # 三种"异常"条目均被跳过

    a: Dict[str, Any] = files[0]
    assert a["path"] == str(tmp_path / "a.txt")
    assert a["is_dir"] is False
    assert a["size"] == 42
    assert a["suffix"] == "txt"
    assert a["modified"]

    sub: Dict[str, Any] = files[1]
    assert sub["is_dir"] is True