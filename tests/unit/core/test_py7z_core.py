# -*- coding: utf-8 -*-
"""7z 压缩包处理核心单测（tests-comprehensive-refactor todo-9 补全）。

覆盖 ``freeassetfilter.core.native.bridges.py7z_core``：

* **7z.exe 可用（真实执行路径）**：``list_archive`` 列出 ZIP 内容、
  ``_run_7z_command`` 解压单个条目到临时目录、``get_archive_type`` /
  ``is_encrypted`` / ``test_archive`` 真实调用、模块便捷函数与单例；
* **7z.exe 缺失（mock 路径）**：绕过构造函数（``__new__``）直接设置
  ``_7z_exe_path``，将模块级 ``run_with_limited_output`` patch 为假实现，
  覆盖命令注入拦截 / 超时 / 输出截断 / utf-16 解码 / 解析器 / 编码探测 /
  安全路径与嵌套深度边界；
* 双模式守卫：直接探测 ``core/native/bin/7z/7z.exe`` 存在性，不存在时
  真实执行类整体 ``pytest.skip``（-rs 可见原因）。

任何子进程调用都带 ``command_timeout``（测试统一 30s 或 mock 完全替换）。
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, List

import pytest

from freeassetfilter.core._paths import archive_7z_dir
from freeassetfilter.core.native.bridges import py7z_core as py7z_mod
from freeassetfilter.core.native.bridges.py7z_core import (
    Py7zCore,
    get_7z_core,
    get_archive_type,
    is_encrypted,
    list_archive,
)
from tests.support.data_factories import make_zip


pytestmark = pytest.mark.unit


#: 模拟 7z ``l -slt`` 输出的典型样本（含压缩包自身块 + 两个条目）。
_SLT_SAMPLE: str = """7-Zip 26.00 (x64)
Listing archive: C:\\tmp\\sample.zip

Path = sample.zip
Type = zip
Physical Size = 251

Path = hello.txt
Size = 15
Modified = 2026-01-01 10:00:00
Attributes =  01800000

Path = subdir\\data.json
Size = 8
Modified = 2026-01-02 11:00:00
Attributes =  01800000
"""


@pytest.fixture(scope="module")
def seven_zip_exe() -> str:
    """返回捆绑 7z.exe 的路径（用于可用性探测与真实执行类守卫）。"""
    return str(archive_7z_dir() / "7z.exe")


@pytest.fixture(scope="module")
def seven_zip_available(seven_zip_exe: str) -> bool:
    """探测捆绑 7z.exe 是否存在。"""
    return os.path.isfile(seven_zip_exe)


@pytest.fixture()
def _zip_path(tmp_path: Any) -> str:
    """用 make_zip 生成一个含文件与子目录条目的小 ZIP。"""
    return make_zip(
        tmp_path / "sample.zip",
        {"hello.txt": "Hello from ZIP!", "subdir/data.json": '{"a": 1}'},
    )


def _mocked_core(monkeypatch: Any, run_fn: Any) -> Py7zCore:
    """绕过 ``__init__``（避免无 7z.exe 时构造抛异常）构造 mock 核心。

    Args:
        monkeypatch: pytest MonkeyPatch。
        run_fn: 替换模块级 ``run_with_limited_output`` 的假实现。

    Returns:
        Py7zCore: 设置了假 7z 路径与 30s 超时的实例。
    """
    core = Py7zCore.__new__(Py7zCore)
    core._7z_exe_path = "7z.exe"  # noqa: SLF001
    core._command_timeout = 30  # noqa: SLF001
    monkeypatch.setattr(py7z_mod, "run_with_limited_output", run_fn)
    return core


# =============================================================================
# 真实执行路径（需 7z.exe）
# =============================================================================
class TestReal7zExecution:
    """7z.exe 存在时走真实命令路径。"""

    def test_list_archive_real(self, _zip_path: str, seven_zip_available: bool) -> None:
        """真实列出 ZIP 内容：文件与子目录条目均被解析。"""
        if not seven_zip_available:
            pytest.skip("core/native/bin/7z/7z.exe 缺失")
        core = Py7zCore(command_timeout=30)
        files = core.list_archive(_zip_path)
        names = {f["name"] for f in files}
        assert "hello.txt" in names
        assert "subdir" in names

    def test_extract_single_entry_real(
        self, _zip_path: str, tmp_path: Any, seven_zip_available: bool
    ) -> None:
        """真实解压单个条目到临时目录并验证内容。"""
        if not seven_zip_available:
            pytest.skip("core/native/bin/7z/7z.exe 缺失")
        out_dir = tmp_path / "extracted"
        out_dir.mkdir()
        core = Py7zCore(command_timeout=30)
        returncode, _, stderr = core._run_7z_command(  # noqa: SLF001
            ["e", "-y", f"-o{out_dir}", _zip_path, "hello.txt"]
        )
        assert returncode == 0, stderr
        target = out_dir / "hello.txt"
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "Hello from ZIP!"

    def test_get_archive_type_real(self, _zip_path: str, seven_zip_available: bool) -> None:
        """真实 7z l 输出解析出 Type = zip。"""
        if not seven_zip_available:
            pytest.skip("core/native/bin/7z/7z.exe 缺失")
        core = Py7zCore(command_timeout=30)
        assert core.get_archive_type(_zip_path) == "zip"

    def test_is_encrypted_real_negative(
        self, tmp_path_factory: Any, seven_zip_available: bool
    ) -> None:
        """未加密 zip 返回 False。"""
        if not seven_zip_available:
            pytest.skip("core/native/bin/7z/7z.exe 缺失")
        # pytest 的 tmp_path 目录名含函数名 test_is_encrypted_real_negative，
        # 路径中带 "encrypted" 子串；7z 输出会回显归档路径导致关键字误命中。
        # 因此把 zip 放到 pytest-<num> 基目录下的中性命名子目录。
        neutral_dir = tmp_path_factory.mktemp("faf_neutral")
        zip_path = make_zip(
            neutral_dir / "sample.zip",
            {"hello.txt": "Hello from ZIP!"},
        )
        core = Py7zCore(command_timeout=30)
        assert core.is_encrypted(zip_path) is False

    def test_test_archive_real(self, _zip_path: str, seven_zip_available: bool) -> None:
        """完整 zip 通过 ``t`` 校验。"""
        if not seven_zip_available:
            pytest.skip("core/native/bin/7z/7z.exe 缺失")
        core = Py7zCore(command_timeout=30)
        valid, message = core.test_archive(_zip_path)
        assert valid is True
        assert message == ""

    def test_module_convenience_functions_real(
        self, _zip_path: str, seven_zip_available: bool
    ) -> None:
        """模块级便捷函数走真实 7z 路径。"""
        if not seven_zip_available:
            pytest.skip("core/native/bin/7z/7z.exe 缺失")
        names = {f["name"] for f in list_archive(_zip_path)}
        assert "hello.txt" in names
        assert get_archive_type(_zip_path) == "zip"
        assert is_encrypted(_zip_path) is False

    def test_get_7z_core_singleton(self, seven_zip_available: bool) -> None:
        """``get_7z_core`` 返回同一单例实例。"""
        if not seven_zip_available:
            pytest.skip("core/native/bin/7z/7z.exe 缺失")
        assert get_7z_core() is get_7z_core()


# =============================================================================
# mock 路径（7z.exe 缺失时仍全部可运行）
# =============================================================================
class TestMockedCommandRunner:
    """``_run_7z_command`` 的 mock 分支：注入/超时/截断/解码。"""

    def test_injection_chars_blocked(self, monkeypatch: Any, tmp_path: Any) -> None:
        """含命令注入风险字符的参数直接返回 -1，不触发子进程。"""
        called: List[Any] = []

        def _fake(*a: Any, **k: Any) -> Any:
            called.append(a)
            return subprocess.CompletedProcess(a[0], 0, stdout="", stderr="")

        core = _mocked_core(monkeypatch, _fake)
        code, _out, err = core._run_7z_command(["l", "evil\npath.zip"])  # noqa: SLF001
        assert code == -1
        assert "注入" in err
        assert called == []

    def test_success_text_output(self, monkeypatch: Any) -> None:
        """正常文本输出返回 (0, stdout, stderr)。"""
        fake = lambda *a, **k: subprocess.CompletedProcess(  # noqa: E731
            list(a[0]), 0, stdout="Type = zip\n", stderr=""
        )
        core = _mocked_core(monkeypatch, fake)
        code, out, err = core._run_7z_command(["l", "x.zip"])  # noqa: SLF001
        assert code == 0
        assert out == "Type = zip\n"
        assert err == ""

    def test_timeout_returns_error(self, monkeypatch: Any) -> None:
        """TimeoutExpired 被转换为超时错误元组。"""

        def _raise(*a: Any, **k: Any) -> Any:
            raise subprocess.TimeoutExpired(cmd=a[0], timeout=30)

        core = _mocked_core(monkeypatch, _raise)
        code, _out, err = core._run_7z_command(["t", "x.zip"])  # noqa: SLF001
        assert code == -1
        assert "超时" in err

    def test_output_truncated_returns_error(self, monkeypatch: Any) -> None:
        """stdout 截断时返回 -1 与安全限制提示。"""
        completed = subprocess.CompletedProcess([], 0, stdout="x", stderr="")
        completed.stdout_truncated = True  # type: ignore[attr-defined]
        core = _mocked_core(monkeypatch, lambda *a, **k: completed)
        code, _out, err = core._run_7z_command(["l", "x.zip"])  # noqa: SLF001
        assert code == -1
        assert "安全限制" in err

    def test_utf16_manual_decode(self, monkeypatch: Any) -> None:
        """utf-16le 编码走手动解码分支并还原条目名。"""
        payload = "Path = 你好.txt\n".encode("utf-16le")
        fake = lambda *a, **k: subprocess.CompletedProcess(  # noqa: E731
            list(a[0]), 0, stdout=payload, stderr=b""
        )
        core = _mocked_core(monkeypatch, fake)
        code, out, _err = core._run_7z_command(["l", "x.7z"], encoding="utf-16le")  # noqa: SLF001
        assert code == 0
        assert "你好" in out

    def test_utf16_decode_fallback(self, monkeypatch: Any) -> None:
        """非法 utf-16le 数据回退到 utf-8 errors=replace 解码。"""
        fake = lambda *a, **k: subprocess.CompletedProcess(  # noqa: E731
            list(a[0]), 0, stdout=b"\xff", stderr=b""
        )
        core = _mocked_core(monkeypatch, fake)
        code, out, _err = core._run_7z_command(["l", "x.7z"], encoding="utf-16le")  # noqa: SLF001
        assert code == 0
        assert isinstance(out, str)


class TestMockedListArchive:
    """``list_archive`` 的 mock 分支与边界。"""

    def test_missing_archive_returns_empty(self, monkeypatch: Any, tmp_path: Any) -> None:
        """压缩包不存在时返回 []，不触发子进程。"""
        called: List[Any] = []
        core = _mocked_core(
            monkeypatch, lambda *a, **k: called.append(a) or subprocess.CompletedProcess(a[0], 0)
        )
        assert core.list_archive(str(tmp_path / "missing.zip")) == []
        assert called == []

    def test_nested_depth_limit_returns_empty(self, monkeypatch: Any, tmp_path: Any) -> None:
        """嵌套深度 >= MAX_NESTED_DEPTH 时返回 []。"""
        called: List[Any] = []
        archive = tmp_path / "deep.zip"
        archive.write_bytes(b"PK")
        core = _mocked_core(
            monkeypatch, lambda *a, **k: called.append(a) or subprocess.CompletedProcess(a[0], 0)
        )
        assert core.list_archive(str(archive), nested_depth=core.MAX_NESTED_DEPTH) == []
        assert called == []

    def test_nonzero_exit_returns_empty(self, monkeypatch: Any, tmp_path: Any) -> None:
        """7z 非零退出时返回 []。"""
        archive = tmp_path / "bad.zip"
        archive.write_bytes(b"PK\x03\x04")
        fake = lambda *a, **k: subprocess.CompletedProcess(  # noqa: E731
            list(a[0]), 2, stdout="", stderr="cannot open"
        )
        core = _mocked_core(monkeypatch, fake)
        assert core.list_archive(str(archive)) == []

    def test_success_with_mocked_slt_output(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        """mock 输出经解析后返回文件与子目录条目。"""
        archive = tmp_path / "sample.zip"
        archive.write_bytes(b"PK\x03\x04")
        fake = lambda *a, **k: subprocess.CompletedProcess(  # noqa: E731
            list(a[0]), 0, stdout=_SLT_SAMPLE, stderr=""
        )
        core = _mocked_core(monkeypatch, fake)
        files = core.list_archive(str(archive))
        names = {f["name"] for f in files}
        assert "hello.txt" in names
        assert "subdir" in names
        info = next(f for f in files if f["name"] == "hello.txt")
        assert info["is_dir"] is False
        assert info["size"] == 15

    def test_current_path_filters_entries(self, monkeypatch: Any, tmp_path: Any) -> None:
        """current_path 限定后仅返回该子目录下内容。"""
        archive = tmp_path / "sample.zip"
        archive.write_bytes(b"PK\x03\x04")
        fake = lambda *a, **k: subprocess.CompletedProcess(  # noqa: E731
            list(a[0]), 0, stdout=_SLT_SAMPLE, stderr=""
        )
        core = _mocked_core(monkeypatch, fake)
        files = core.list_archive(str(archive), current_path="subdir")
        assert {f["name"] for f in files} == {"data.json"}


class TestMockedParsers:
    """``_parse_list_output`` / ``_parse_file_block`` / 编码探测。"""

    def test_parse_file_block_full(self) -> None:
        """标准文件块提取 path/size/modified/attributes/crc。"""
        core = Py7zCore.__new__(Py7zCore)
        block = (
            "Path = a.txt\n"
            "Size = 42\n"
            "Modified = 2026-01-01 10:00:00\n"
            "Attributes = A_ -rw-rw-rw-\n"
            "CRC = ABCDEF01\n"
        )
        info = core._parse_file_block(block)  # noqa: SLF001
        assert info is not None
        assert info["path"] == "a.txt"
        assert info["size"] == 42
        assert info["is_dir"] is False
        assert info["modified"] == "2026-01-01T10:00:00"
        assert info["crc"] == "ABCDEF01"

    def test_parse_file_block_directory_attribute(self) -> None:
        """Attributes 含 D 判定为目录。"""
        core = Py7zCore.__new__(Py7zCore)
        block = "Path = sub/\nAttributes = D....\n"
        info = core._parse_file_block(block)  # noqa: SLF001
        assert info is not None
        assert info["path"] == "sub/"
        assert info["is_dir"] is True

    def test_parse_file_block_missing_path_returns_none(self) -> None:
        """无 Path 行的块返回 None。"""
        core = Py7zCore.__new__(Py7zCore)
        assert core._parse_file_block("Size = 5\n") is None  # noqa: SLF001

    def test_parse_list_output_dedupes_self_entry(self) -> None:
        """压缩包自身块被跳过，同名条目按名去重。"""
        core = Py7zCore.__new__(Py7zCore)
        files = core._parse_list_output(_SLT_SAMPLE, current_path="", archive_path="x.zip")  # noqa: SLF001
        names = [f["name"] for f in files]
        assert "x.zip" not in names
        assert len(names) == len(set(names))

    def test_detect_encoding_replacement_means_gbk(self) -> None:
        """输出含替换字符时回退 GBK。"""
        core = Py7zCore.__new__(Py7zCore)
        assert core._detect_encoding_from_output("a\ufffdb", "utf-8") == "gbk"  # noqa: SLF001

    def test_detect_encoding_clean_stays_utf8(self) -> None:
        """干净输出保持 UTF-8。"""
        core = Py7zCore.__new__(Py7zCore)
        assert core._detect_encoding_from_output("clean path", "utf-8") == "utf-8"  # noqa: SLF001

    def test_detect_encoding_respects_explicit_request(self) -> None:
        """非 UTF-8 的显式请求原样保留。"""
        core = Py7zCore.__new__(Py7zCore)
        assert core._detect_encoding_from_output("x\ufffd", "gbk") == "gbk"  # noqa: SLF001


class TestMockedHeuristics:
    """``is_encrypted`` / ``get_archive_type`` 的 mock 路径。"""

    def test_is_encrypted_detects_marker(self, monkeypatch: Any, tmp_path: Any) -> None:
        """二次 -slt 输出含 Encrypted = + 时判定为加密。"""
        archive = tmp_path / "enc.7z"
        archive.write_bytes(b"7z")

        def _fake(*a: Any, **k: Any) -> Any:
            cmd = list(a[0])
            stdout = "Encrypted = +\n" if "-slt" in cmd else "7-Zip 26.00\n"
            return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

        core = _mocked_core(monkeypatch, _fake)
        assert core.is_encrypted(str(archive)) is True

    def test_is_encrypted_negative(self, monkeypatch: Any, tmp_path: Any) -> None:
        """未加密输出判定为 False。"""
        archive = tmp_path / "plain.zip"
        archive.write_bytes(b"PK")
        fake = lambda *a, **k: subprocess.CompletedProcess(  # noqa: E731
            list(a[0]), 0, stdout="Type = zip\n", stderr=""
        )
        core = _mocked_core(monkeypatch, fake)
        assert core.is_encrypted(str(archive)) is False

    def test_get_archive_type_mocked(self, monkeypatch: Any, tmp_path: Any) -> None:
        """Type 行解析出 zip。"""
        archive = tmp_path / "sample.zip"
        archive.write_bytes(b"PK")
        fake = lambda *a, **k: subprocess.CompletedProcess(  # noqa: E731
            list(a[0]), 0, stdout="Type = zip\n", stderr=""
        )
        core = _mocked_core(monkeypatch, fake)
        assert core.get_archive_type(str(archive)) == "zip"

    def test_get_archive_type_falls_back_to_ext(self, monkeypatch: Any, tmp_path: Any) -> None:
        """Type 行缺失时按扩展名推断。"""
        archive = tmp_path / "sample.rar"
        archive.write_bytes(b"Rar!")
        fake = lambda *a, **k: subprocess.CompletedProcess(  # noqa: E731
            list(a[0]), 0, stdout="no type here\n", stderr=""
        )
        core = _mocked_core(monkeypatch, fake)
        assert core.get_archive_type(str(archive)) == "rar"

    def test_missing_file_heuristics(self, monkeypatch: Any, tmp_path: Any) -> None:
        """文件不存在时 is_encrypted 返回 False、类型返回 unknown。"""
        core = _mocked_core(monkeypatch, lambda *a, **k: subprocess.CompletedProcess([]))
        missing = str(tmp_path / "nope.7z")
        assert core.is_encrypted(missing) is False
        assert core.get_archive_type(missing) == "unknown"


class TestConstructorWithout7z:
    """7z.exe 缺失环境下构造函数抛 FileNotFoundError（双模式反向用例）。"""

    def test_constructor_raises_when_7z_missing(self, seven_zip_available: bool) -> None:
        """仅当 7z.exe 不可用时断言构造抛 FileNotFoundError。"""
        if seven_zip_available:
            pytest.skip("7z.exe 存在，构造函数可正常找到")
        with pytest.raises(FileNotFoundError):
            Py7zCore()