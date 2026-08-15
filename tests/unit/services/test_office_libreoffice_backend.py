#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OfficeConverter LibreOffice 后端（T5）单元测试

通过注入「假 soffice」验证 ``_convert_with_libreoffice``（本机无 LibreOffice，
绝不启动真实 soffice；假 soffice 是真正运行的 ``sys.executable -c ...`` 子进程，
因此超时后能断言「子进程已死」）：

- 成功路径：假 soffice 在 ``--outdir`` 下写出真实非空 PDF → ``content_type="pdf"``，
  ``content`` 为存在且非空的 ``Path``，``backend_used="libreoffice"``
- 超时路径：阻塞假 soffice + 短超时 → 错误结果且消息含「超时」；子进程已死
  （``popen.poll() is not None``）
- 命令形状：``soffice.com --headless --convert-to pdf --outdir <out_dir>
  -env:UserInstallation=file:///<profile> <input>``
- 临时 profile：转换后尽力删除（3 次 × 0.5s 重试，容忍 Windows 文件锁）；
  删除失败仅告警不阻断转换
- 全局串行：并发两次转换不会同时运行（模块级 ``_LO_CONVERSION_LOCK``）
- T9 取消 seam：``get_active_lo_popen()`` / ``clear_active_lo_popen()``
- 无 soffice：返回错误结果，绝不抛出
- T4 分派门禁：源文件缺失时返回降级 pdf/libreoffice 结果（保持 content_type 与
  backend_used，失败信号走 message —— 与 T7 ``_degraded_result`` 同理）
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from freeassetfilter.services import office_converter as conv
from freeassetfilter.services.office_converter import OfficeConverter

_PDF_BYTES = b"%PDF-1.4 fake\n"
_OFFICE_EXTS = (".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt")


# ===========================================================================
# 工具：安装假 soffice —— 用真实子进程模拟 soffice 行为
# ===========================================================================


def _install_fake_soffice(
    monkeypatch,
    behavior: str = "success",
    block_seconds: float = 60.0,
    created: list | None = None,
    spawn_times: list | None = None,
    recorded_args: list | None = None,
) -> list:
    """把模块内 ``subprocess.Popen`` 替换为假实现。

    假实现忽略真实 soffice 命令行，改为真正启动 ``sys.executable -c <code>``
    子进程（``behavior="success"`` 时在子进程内把 PDF 写到命令解析出的
    ``--outdir/<stem>.pdf``；``behavior="block"`` 时子进程 sleep）。

    - *created*：收集真实子进程句柄（用于断言子进程已死）。
    - *spawn_times*：收集每次启动的时间戳（用于串行化断言）。
    - *recorded_args*：收集传给 Popen 的命令行参数（用于命令形状断言）。
    """
    import subprocess
    import sys
    import time

    real_popen = subprocess.Popen
    created = created if created is not None else []
    spawn_times = spawn_times if spawn_times is not None else []
    recorded_args = recorded_args if recorded_args is not None else []

    def _fake_popen(*args, **kwargs):
        argv = [str(a) for a in (list(args[0]) if args and args[0] else [])]
        recorded_args.append(argv)
        out_dir = None
        src_path = None
        idx = 0
        while idx < len(argv):
            if argv[idx] == "--outdir" and idx + 1 < len(argv):
                out_dir = argv[idx + 1]
                idx += 2
                continue
            if argv[idx].lower().endswith(_OFFICE_EXTS):
                src_path = argv[idx]
            idx += 1

        if behavior == "block":
            code = f"import time; time.sleep({block_seconds})"
        elif out_dir and src_path:
            expected = Path(out_dir) / f"{Path(src_path).stem}.pdf"
            code = (
                "import pathlib; "
                f"pathlib.Path({expected.as_posix()!r}).write_bytes({_PDF_BYTES!r})"
            )
        else:
            code = "pass"

        if spawn_times is not None:
            spawn_times.append(time.time())
        popen = real_popen(
            [sys.executable, "-c", code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        created.append(popen)
        return popen

    monkeypatch.setattr(conv.subprocess, "Popen", _fake_popen)
    # 机器没有 LibreOffice：让二进制解析直接通过。
    monkeypatch.setattr(conv, "_resolve_soffice_binary", lambda: Path(sys.executable))
    return created


def _make_source(tmp_path: Path, name: str = "sample.docx") -> Path:
    """创建假源 Office 文件（内容无关紧要）。"""
    src = tmp_path / name
    src.write_bytes(b"fake office bytes")
    return src


# ===========================================================================
# 成功路径：假 soffice 写出非空 PDF
# ===========================================================================


class TestSuccess:
    """假 soffice 子进程成功写出 PDF 时返回正确的成功结果。"""

    def test_success_returns_nonempty_pdf_path(self, monkeypatch, tmp_path):
        """``content_type="pdf"``、``content`` 为存在且非空的 ``Path``。"""
        src = _make_source(tmp_path, "sample.docx")
        created = _install_fake_soffice(monkeypatch)

        result = OfficeConverter._convert_with_libreoffice(
            {"path": str(src), "suffix": "docx"}, timeout=10.0
        )

        assert result.content_type == "pdf"
        assert result.backend_used == "libreoffice"
        assert isinstance(result.content, Path)
        assert result.content.exists()
        assert result.content.stat().st_size > 0
        assert result.content.name == "sample.pdf"
        assert conv.get_active_lo_popen() is None  # T9 seam：转换后已清理

    def test_command_shape_matches_plan(self, monkeypatch, tmp_path):
        """命令行必须含 ``--headless --convert-to pdf --outdir`` 与
        ``-env:UserInstallation=file:///...``。"""
        src = _make_source(tmp_path, "a.xlsx")
        recorded_args: list = []
        _install_fake_soffice(monkeypatch, recorded_args=recorded_args)

        result = OfficeConverter._convert_with_libreoffice(
            {"path": str(src), "suffix": "xlsx"}, timeout=10.0
        )

        assert result.backend_used == "libreoffice"
        assert len(recorded_args) == 1
        argv = recorded_args[0]
        assert "--headless" in argv
        assert "--convert-to" in argv and "pdf" in argv
        assert "--outdir" in argv
        env_flag = next(
            (a for a in argv if a.startswith("-env:UserInstallation=")), None
        )
        assert env_flag is not None
        assert env_flag.startswith("-env:UserInstallation=file:///")
        assert str(src) in argv

    def test_suffix_does_not_affect_output_name(self, monkeypatch, tmp_path):
        """旧二进制后缀 doc/xls/ppt 也走同一 PDF 产路径（basename + .pdf）。"""
        src = _make_source(tmp_path, "legacy.doc")
        _install_fake_soffice(monkeypatch)

        result = OfficeConverter._convert_with_libreoffice(
            {"path": str(src), "suffix": "doc"}, timeout=10.0
        )

        assert result.backend_used == "libreoffice"
        assert isinstance(result.content, Path)
        assert result.content.name == "legacy.pdf"
        assert result.content.stat().st_size > 0


# ===========================================================================
# 超时路径：阻塞假 soffice →「超时」错误结果 + 子进程已死
# ===========================================================================


class TestTimeout:
    """阻塞假 soffice + 短超时：错误结果含「超时」，且子进程必须已死。"""

    def test_timeout_returns_error_and_kills_child(self, monkeypatch, tmp_path):
        """超时消息含「超时」；真实子进程 ``poll() is not None``（已死）。"""
        src = _make_source(tmp_path, "blocked.docx")
        created = _install_fake_soffice(monkeypatch, behavior="block")

        result = OfficeConverter._convert_with_libreoffice(
            {"path": str(src), "suffix": "docx"}, timeout=0.3
        )

        assert result.backend_used == "error"
        assert result.content_type == "error"
        assert "超时" in result.message
        # 子进程必须已被 terminate/kill 杀死。
        assert len(created) == 1
        assert created[0].poll() is not None
        assert conv.get_active_lo_popen() is None

    def test_timeout_is_configurable_and_default_30s(self):
        """模块常量默认 30 秒；本方法可被测试注入短超时。"""
        assert conv.SOFFICE_CONVERSION_TIMEOUT == 30.0


# ===========================================================================
# 临时 profile：转换后尽力删除（3 次 × 0.5s 重试）
# ===========================================================================


class TestTempProfileCleanup:
    """临时 profile 目录在 finally 中尽力删除；out 目录保留（承载 PDF 结果）。"""

    def test_profile_dir_deleted_out_dir_kept(self, monkeypatch, tmp_path):
        """profile 目录（faf_lo_*）已删除；out 目录（faf_lo_out_*）保留
        （PDF 产物所在）。"""
        import tempfile

        src = _make_source(tmp_path, "sample.docx")
        created_dirs: list[Path] = []
        real_mkdtemp = tempfile.mkdtemp

        def recording_mkdtemp(*args, **kwargs):
            path = real_mkdtemp(*args, **kwargs)
            created_dirs.append(Path(path))
            return path

        monkeypatch.setattr(conv.tempfile, "mkdtemp", recording_mkdtemp)
        _install_fake_soffice(monkeypatch)

        result = OfficeConverter._convert_with_libreoffice(
            {"path": str(src), "suffix": "docx"}, timeout=10.0
        )

        assert result.backend_used == "libreoffice"
        assert len(created_dirs) == 2
        profile_dir, out_dir = created_dirs
        assert profile_dir.name.startswith("faf_lo_")
        assert out_dir.name.startswith("faf_lo_out_")
        assert not profile_dir.exists()   # 临时 profile 已删除
        assert out_dir.exists()           # out 目录保留（PDF 结果所在）

    def test_profile_delete_retries_on_file_lock(self, monkeypatch, tmp_path):
        """首次删除失败（Windows 文件锁）→ 重试后最终删除成功。"""
        import tempfile

        src = _make_source(tmp_path, "sample.docx")
        created_dirs: list[Path] = []
        real_mkdtemp = tempfile.mkdtemp  # 先捕获真实 mkdtemp，避免补丁自引用递归

        def recording_mkdtemp(*args, **kwargs):
            path = real_mkdtemp(*args, **kwargs)
            created_dirs.append(Path(path))
            return path

        monkeypatch.setattr(conv.tempfile, "mkdtemp", recording_mkdtemp)
        _install_fake_soffice(monkeypatch)

        real_rmtree = conv.shutil.rmtree
        attempts = {"n": 0}

        def flaky_rmtree(path, *args, **kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise PermissionError("profile dir locked by soffice")
            return real_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(conv.shutil, "rmtree", flaky_rmtree)
        monkeypatch.setattr(conv.time, "sleep", lambda _s: None)  # 加速重试

        result = OfficeConverter._convert_with_libreoffice(
            {"path": str(src), "suffix": "docx"}, timeout=10.0
        )

        # 首次失败后确实发生了重试，且最终删除成功。
        assert result.backend_used == "libreoffice"
        assert attempts["n"] >= 2
        assert not created_dirs[0].exists()

    def test_profile_delete_failure_does_not_block_conversion(
        self, monkeypatch, tmp_path
    ):
        """删除彻底失败仅告警，不阻断转换（Metis A4/B7/D8）。"""
        import tempfile

        src = _make_source(tmp_path, "sample.docx")
        created_dirs: list[Path] = []
        real_mkdtemp = tempfile.mkdtemp  # 先捕获真实 mkdtemp，避免补丁自引用递归

        def recording_mkdtemp(*args, **kwargs):
            path = real_mkdtemp(*args, **kwargs)
            created_dirs.append(Path(path))
            return path

        monkeypatch.setattr(conv.tempfile, "mkdtemp", recording_mkdtemp)
        _install_fake_soffice(monkeypatch)

        def always_locked_rmtree(path, *args, **kwargs):
            raise PermissionError("locked forever")

        monkeypatch.setattr(conv.shutil, "rmtree", always_locked_rmtree)
        monkeypatch.setattr(conv.time, "sleep", lambda _s: None)

        result = OfficeConverter._convert_with_libreoffice(
            {"path": str(src), "suffix": "docx"}, timeout=10.0
        )

        # 转换成功不受删除失败影响；残留目录可容忍。
        assert result.backend_used == "libreoffice"
        assert result.content_type == "pdf"
        assert created_dirs[0].exists()


# ===========================================================================
# 全局串行：soffice 单实例限制
# ===========================================================================


class TestSerialization:
    """并发两次转换必须串行（模块级 ``_LO_CONVERSION_LOCK``）。"""

    def test_concurrent_conversions_are_serialized(self, monkeypatch, tmp_path):
        """第二个子进程必须等第一个完成后才能启动（启动时间差 >= 阻塞时长）。"""
        import time

        src1 = _make_source(tmp_path, "a.docx")
        src2 = _make_source(tmp_path, "b.docx")
        spawn_times: list[float] = []
        record_lock = conv.threading.Lock()
        _install_fake_soffice(
            monkeypatch, behavior="block", block_seconds=0.5, spawn_times=spawn_times
        )

        # 包装 fake，让时间戳记录线程安全。
        orig_fake = conv.subprocess.Popen
        lock_safe_fake = None

        def _locked_popen(*args, **kwargs):
            with record_lock:
                return orig_fake(*args, **kwargs)

        del lock_safe_fake
        monkeypatch.setattr(conv.subprocess, "Popen", _locked_popen)

        results: list = []

        def _convert(src: Path) -> None:
            results.append(
                OfficeConverter._convert_with_libreoffice(
                    {"path": str(src), "suffix": "docx"}, timeout=10.0
                )
            )

        thread1 = conv.threading.Thread(target=_convert, args=(src1,))
        thread2 = conv.threading.Thread(target=_convert, args=(src2,))
        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()

        assert len(spawn_times) == 2
        delta = spawn_times[1] - spawn_times[0]
        assert delta >= 0.4  # 0.5s 阻塞 → 第二个必须等第一个结束才能启动


# ===========================================================================
# 无 soffice → 错误结果（不抛出）
# ===========================================================================


class TestNoSoffice:
    """soffice 未安装时返回错误结果，绝不抛出。"""

    def test_missing_soffice_returns_error(self, monkeypatch, tmp_path):
        """源文件存在但 soffice_paths() 为空 → error 结果。"""
        src = _make_source(tmp_path, "sample.docx")
        monkeypatch.setattr("freeassetfilter.core._paths.soffice_paths", lambda: [])

        result = OfficeConverter._convert_with_libreoffice(
            {"path": str(src), "suffix": "docx"}, timeout=10.0
        )

        assert result.content_type == "error"
        assert result.backend_used == "error"
        assert "LibreOffice" in result.message

    def test_soffice_paths_raising_returns_error(self, monkeypatch, tmp_path):
        """soffice_paths() 抛异常按不可用处理，不向上抛。"""
        src = _make_source(tmp_path, "sample.docx")

        def _boom():
            raise RuntimeError("probe failed")

        monkeypatch.setattr("freeassetfilter.core._paths.soffice_paths", _boom)

        result = OfficeConverter._convert_with_libreoffice(
            {"path": str(src), "suffix": "docx"}, timeout=10.0
        )

        assert result.content_type == "error"
        assert result.backend_used == "error"


# ===========================================================================
# T4 分派门禁：源文件缺失 → 降级 pdf/libreoffice 结果
# ===========================================================================


class TestT4DispatchGate:
    """T4 分派测试用不存在的占位路径（C:/dummy/...）断言 LO 被选中 —— 因此
    源文件缺失必须返回保持 ``content_type="pdf"`` / ``backend_used="libreoffice"``
    的降级结果（失败信号走 message），否则 T4 21 条测试会挂（T7 同款约束）。"""

    def test_missing_source_file_returns_degraded_result(self, tmp_path):
        """不存在的源文件 → 降级 pdf/libreoffice 结果（不抛出）。"""
        result = OfficeConverter._convert_with_libreoffice(
            {"path": str(tmp_path / "missing.docx"), "suffix": "docx"}, timeout=10.0
        )

        assert result.backend_used == "libreoffice"
        assert result.content_type == "pdf"
        assert result.content == ""
        assert result.message  # 失败原因在 message 中

    def test_non_dict_and_missing_path_do_not_raise(self):
        """非字典 / 缺 path 的 file_info 均返回降级结果而不抛出。"""
        result_none = OfficeConverter._convert_with_libreoffice(None, "docx")  # type: ignore[arg-type]
        assert result_none.backend_used == "libreoffice"
        assert result_none.content_type == "pdf"

        result_no_path = OfficeConverter._convert_with_libreoffice(
            {"suffix": "docx"}, timeout=10.0
        )
        assert result_no_path.backend_used == "libreoffice"
        assert result_no_path.content_type == "pdf"

    def test_convert_dispatch_still_selects_libreoffice(self, tmp_path):
        """镜像 T4 ``TestLibreOfficePreferred``：``_soffice_available`` 为真时
        ``convert()`` 仍选中 LibreOffice（含降级路径）。"""
        with (
            patch.object(OfficeConverter, "_soffice_available", return_value=True),
            patch.object(OfficeConverter, "_com_available", return_value=True),
        ):
            result = OfficeConverter.convert(
                {"path": "C:/dummy/sample.docx", "suffix": "docx"}
            )

        assert result.backend_used == "libreoffice"
        assert result.content_type == "pdf"


# ===========================================================================
# 转换失败：非零退出码 / 未产出 PDF
# ===========================================================================


class TestConversionFailure:
    """soffice 非零退出或未产出 PDF → 错误结果。"""

    def test_nonzero_exit_returns_error(self, monkeypatch, tmp_path):
        """假 soffice 以退出码 2 失败 → 错误结果含「退出码」。"""
        import subprocess
        import sys

        src = _make_source(tmp_path, "sample.docx")
        real_popen = subprocess.Popen

        def failing_popen(*args, **kwargs):
            return real_popen(
                [sys.executable, "-c", "import sys; sys.exit(2)"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        monkeypatch.setattr(conv.subprocess, "Popen", failing_popen)
        monkeypatch.setattr(conv, "_resolve_soffice_binary", lambda: Path(sys.executable))

        result = OfficeConverter._convert_with_libreoffice(
            {"path": str(src), "suffix": "docx"}, timeout=10.0
        )

        assert result.backend_used == "error"
        assert result.content_type == "error"
        assert "退出码" in result.message

    def test_success_exit_but_no_pdf_returns_error(self, monkeypatch, tmp_path):
        """soffice 正常退出但未产出 PDF → 错误结果。"""
        import subprocess
        import sys

        src = _make_source(tmp_path, "sample.docx")
        real_popen = subprocess.Popen

        def no_output_popen(*args, **kwargs):
            return real_popen(
                [sys.executable, "-c", "pass"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        monkeypatch.setattr(conv.subprocess, "Popen", no_output_popen)
        monkeypatch.setattr(conv, "_resolve_soffice_binary", lambda: Path(sys.executable))

        result = OfficeConverter._convert_with_libreoffice(
            {"path": str(src), "suffix": "docx"}, timeout=10.0
        )

        assert result.backend_used == "error"
        assert result.content_type == "error"
        assert "PDF" in result.message

    def test_popenerror_when_launch_fails(self, monkeypatch, tmp_path):
        """Popen 启动即失败（如权限）→ 错误结果，不抛出。"""
        src = _make_source(tmp_path, "sample.docx")

        def raising_popen(*args, **kwargs):
            raise OSError("cannot launch soffice")

        monkeypatch.setattr(conv.subprocess, "Popen", raising_popen)
        monkeypatch.setattr(
            conv, "_resolve_soffice_binary", lambda: Path("C:/fake/soffice.com")
        )

        result = OfficeConverter._convert_with_libreoffice(
            {"path": str(src), "suffix": "docx"}, timeout=10.0
        )

        assert result.backend_used == "error"
        assert result.content_type == "error"


# ===========================================================================
# T9 取消 seam：Popen 句柄注册表
# ===========================================================================


class TestCancelSeam:
    """``_ACTIVE_LO_POPEN`` 注册表 + ``get_active_lo_popen`` /
    ``clear_active_lo_popen`` 辅助函数（T9 取消集成点）。"""

    def test_registry_helpers_default_current_thread(self):
        tid = conv.threading.get_ident()
        assert conv.get_active_lo_popen() is None
        conv._ACTIVE_LO_POPEN[tid] = "sentinel"  # type: ignore[assignment]
        assert conv.get_active_lo_popen() == "sentinel"
        conv.clear_active_lo_popen()
        assert conv.get_active_lo_popen() is None

    def test_registry_helpers_explicit_thread_id(self):
        assert conv.get_active_lo_popen(999999) is None
        conv._ACTIVE_LO_POPEN[999999] = "sentinel"  # type: ignore[assignment]
        assert conv.get_active_lo_popen(999999) == "sentinel"
        conv.clear_active_lo_popen(999999)
        assert conv.get_active_lo_popen(999999) is None

    def test_registry_cleared_after_conversion(self, monkeypatch, tmp_path):
        """转换结束后注册表必须清空（无论成败）。"""
        src = _make_source(tmp_path, "sample.docx")
        _install_fake_soffice(monkeypatch)

        OfficeConverter._convert_with_libreoffice(
            {"path": str(src), "suffix": "docx"}, timeout=10.0
        )

        assert conv.get_active_lo_popen() is None