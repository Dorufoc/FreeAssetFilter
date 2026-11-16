#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sopeek v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/Sopeek
许可协议：https://github.com/Dorufoc/Sopeek/blob/main/LICENSE

Office 转换分派服务
普通类（非单例），classmethod 风格（镜像 ImageDecoderService）。
能力探测（LibreOffice / MS Office / WPS COM）+ 后端分派：
按「MS Office / WPS COM → LibreOffice → 纯 Python」顺序自动降级，每个后缀
定义允许的后端集合；docx/pptx/xlsx 无外部后端时可纯 Python 降级
（HTML / 文本大纲 / HTML 表格），旧二进制格式（doc/xls/ppt）仅接受
COM/LibreOffice 转 PDF（无外部后端时返回安装提示）。
"""

from __future__ import annotations

import html
import os
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
import uuid
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any
from xml.etree import ElementTree

from sopeek.utils.app_logger import debug, warning


def _hidden_subprocess_kwargs() -> dict:
    """返回 Windows 下隐藏子进程控制台窗口的 ``subprocess`` 参数。

    Sopeek 以 ``--windowed`` 打包，父进程没有控制台；此时启动 ``powershell``
    等控制台程序会弹出一个黑色命令窗口。``CREATE_NO_WINDOW`` 配合
    ``STARTUPINFO`` 的 ``SW_HIDE`` 可确保子进程完全不可见。非 Windows 平台
    返回空字典，调用方可直接 ``**`` 展开。
    """
    if os.name != "nt":
        return {}
    kwargs: dict = {}
    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if flags:
        kwargs["creationflags"] = flags
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startupinfo
    except Exception as exc:  # noqa: BLE001 - 隐藏失败不应阻断转换
        debug(f"[OfficeConverter] 构造隐藏子进程参数失败: {exc}")
    return kwargs

# ── 结果对象 ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ConversionResult:
    """一次 Office 转换 / 降级尝试的不可变结果。

    Attributes
    ----------
    content_type :
        结果内容类型：``"pdf"``（COM/LibreOffice 转 PDF）、``"html"``（docx 降级）、
        ``"outline"``（pptx 降级）、``"error"``。
    content :
        结果内容：转换产物路径（``Path``）或内联内容字符串（``str``）。
    backend_used :
        实际生效的后端标识：``"com"`` / ``"libreoffice"`` / ``"pure-python"``
        / ``"error"``。
    message :
        附加说明或错误提示文案。
    detail :
        面向排障的技术详情（COM HRESULT / 异常描述 / 命令等）。
        UI 的「复制错误信息」会把它连同文件、版本、日志路径一起复制，
        默认不在预览界面直接展示。
    failed_backend :
        实际失败的后端标识（``"com"`` / ``"libreoffice"`` / ``"pure-python"``）。
        仅在 ``content_type="error"`` 时有意义；``backend_used="error"`` 时
        用它保留失败来源，便于报告区分。
    """

    content_type: str
    content: str | Path
    backend_used: str
    message: str = ""
    detail: str = ""
    failed_backend: str = ""


# ── 常量（不可变） ───────────────────────────────────────────────────────
# 唯一例外：T5/T9 LibreOffice 后端持有模块级可变状态（_LO_CONVERSION_LOCK
# 转换串行锁与 _ACTIVE_LO_POPEN Popen 句柄注册表，见本文件下方）。


# 本服务支持的全部 Office 后缀（不含前导点，小写）。
SUPPORTED_SUFFIXES: frozenset[str] = frozenset({
    "docx", "pptx", "xlsx", "doc", "xls", "ppt",
})

# OOXML 现代格式。docx/pptx/xlsx 在无外部后端时均可纯 Python 降级：
# docx→HTML、pptx→文本大纲、xlsx→HTML 表格（只保留值与基础网格）。
MODERN_SUFFIXES: frozenset[str] = frozenset({"docx", "pptx", "xlsx"})

# OOXML 之前的旧二进制格式：无 COM/LibreOffice 时仅提示安装，不提供纯 Python 降级。
LEGACY_SUFFIXES: frozenset[str] = frozenset({"doc", "xls", "ppt"})

# 每个后缀允许的后端集合（元组顺序即分派优先级）。只读常量，运行期不修改。
_ALLOWED_BACKENDS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "docx": ("com", "libreoffice", "pure-python"),
    "pptx": ("com", "libreoffice", "pure-python"),
    "xlsx": ("com", "libreoffice", "pure-python"),
    "doc": ("com", "libreoffice"),
    "xls": ("com", "libreoffice"),
    "ppt": ("com", "libreoffice"),
})

# 纯 Python 降级（T7）各后缀对应的内容类型。只读常量。
_PURE_PYTHON_CONTENT_TYPE: Mapping[str, str] = MappingProxyType({
    "docx": "html",
    "pptx": "outline",
    "xlsx": "html",
})

# xlsx → HTML 表格降级的安全上限：预览只展示有代表性的前若干行/列，
# 避免超大工作簿把 UI 线程 / QTextBrowser 卡死。运行期读取，便于测试
# 通过 monkeypatch 缩小阈值。
XLSX_MAX_PREVIEW_ROWS: int = 200
XLSX_MAX_PREVIEW_COLS: int = 50
XLSX_MAX_PREVIEW_SHEETS: int = 10
XLSX_MAX_PREVIEW_CELLS: int = 20000

# COM 探测的 ProgID 顺序（镜像 ``tests/conftest.py`` 的 ``com_available`` fixture）。
_COM_PROG_IDS: tuple[str, ...] = (
    "Word.Application",
    "Excel.Application",
    "PowerPoint.Application",
    "Kwps.Application",
    "Ket.Application",
    "Kwpp.Application",
)

# 无外部后端（doc/xls/ppt legacy）时的安装提示文案（精确匹配计划措辞）。
ERROR_MESSAGE = (
    "请安装 Microsoft Office/WPS Office 或 LibreOffice 插件以获得完整预览"
    if os.name == "nt" else "请安装 LibreOffice 以预览旧版 Office 格式。"
)

# LibreOffice 后端默认转换超时（秒）。T5/T9：测试通过注入更短的 ``timeout``
# 验证超时路径；soffice 卡死时由 ``_convert_with_libreoffice`` 终止并强杀。
SOFFICE_CONVERSION_TIMEOUT: float = 30.0

# LibreOffice 转换串行化锁：soffice 为单实例程序，同一时刻只允许一个转换
# 运行（跨线程）。模块级锁包裹「启动 + 等待」全程（T5 串行化测试契约）。
_LO_CONVERSION_LOCK: threading.Lock = threading.Lock()

# T9 取消 seam：正在进行的 soffice ``Popen`` 句柄注册表，键为执行线程的
# ``threading.get_ident()``。转换完成 / 失败后必须在 ``finally`` 中清空对应
# 键，避免泄漏句柄（``get_active_lo_popen()`` / ``clear_active_lo_popen()``）。
_ACTIVE_LO_POPEN: dict[int, subprocess.Popen] = {}


def get_active_lo_popen(thread_id: int | None = None) -> subprocess.Popen | None:
    """
    读取当前（或指定）线程正在进行的 soffice 子进程句柄（T9 取消 seam）。

    Parameters
    ----------
    thread_id : int | None
        线程标识（``threading.get_ident()``）；``None`` 时读取当前线程。

    Returns
    -------
    subprocess.Popen | None
        正在进行的 soffice ``Popen`` 句柄；无则返回 ``None``。
    """
    key = threading.get_ident() if thread_id is None else thread_id
    return _ACTIVE_LO_POPEN.get(key)


def clear_active_lo_popen(thread_id: int | None = None) -> None:
    """
    清除当前（或指定）线程的 soffice 子进程句柄（T9 取消 seam）。

    Parameters
    ----------
    thread_id : int | None
        线程标识（``threading.get_ident()``）；``None`` 时清除当前线程。
    """
    key = threading.get_ident() if thread_id is None else thread_id
    _ACTIVE_LO_POPEN.pop(key, None)


def _resolve_soffice_binary() -> Path | None:
    """
    在候选目录中定位 soffice 可执行文件。绝不抛出。

    复用 T2 ``soffice_paths()`` 返回的「目录」候选列表，逐个探测
    本平台的可执行文件；惰性导入为保证测试 monkeypatch
    ``sopeek._paths.soffice_paths`` 生效（探测异常一律视为不可用）。

    Returns
    -------
    Path | None
        找到的 soffice 可执行文件路径；未找到或探测异常时返回 ``None``。
    """
    try:
        from sopeek._paths import soffice_paths
        candidates = soffice_paths()
    except Exception as e:
        warning(f"[OfficeConverter] 解析 soffice 路径失败: {e}")
        return None
    names = ("soffice.exe", "soffice.com") if os.name == "nt" else ("soffice",)
    for base_dir in candidates:
        for name in names:
            candidate = base_dir / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
    return None


def _lo_degraded_result(message: str) -> ConversionResult:
    """
    源文件缺失 / 路径无效时的 LibreOffice 降级结果（T4 分派门禁契约）。

    保持 ``content_type="pdf"`` 与 ``backend_used="libreoffice"``（镜像 T7
    ``_degraded_result`` 约定），实际内容为空，失败原因写入 *message*。

    Parameters
    ----------
    message : str
        降级原因提示文案。

    Returns
    -------
    ConversionResult
        ``content=""`` 且携带提示消息的降级结果。
    """
    return ConversionResult(
        content_type="pdf",
        content="",
        backend_used="libreoffice",
        message=message,
    )


def _lo_error_result(message: str, *, detail: str = "") -> ConversionResult:
    """
    生成 LibreOffice 后端的错误结果（``content_type="error"``）。

    Parameters
    ----------
    message : str
        明确的中文错误提示文案。
    detail : str
        面向排障的技术详情（命令、退出码、输出目录等）。

    Returns
    -------
    ConversionResult
        ``backend_used="error"`` 且携带失败后端标识的错误结果。
    """
    return ConversionResult(
        content_type="error",
        content="",
        backend_used="error",
        message=message,
        detail=detail,
        failed_backend="libreoffice",
    )


def _terminate_lo_process(proc: subprocess.Popen) -> None:
    """
    超时后确保 soffice 子进程死亡（terminate → 宽限 → kill）。

    ``terminate()`` 后等待 1 秒宽限期；仍存活则 ``kill()`` 强杀并等待
    子进程退出，保证退出后 ``proc.poll()`` 非 ``None``。

    Parameters
    ----------
    proc : subprocess.Popen
        超时的 soffice 子进程句柄。
    """
    proc.terminate()
    try:
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _remove_temp_profile(
    profile_dir: Path,
    attempts: int = 3,
    delay: float = 0.5,
) -> None:
    """
    尽力删除临时 LibreOffice profile 目录（容忍 Windows 文件锁）。

    最多重试 *attempts* 次、每次间隔 *delay* 秒；删除彻底失败仅记录告警
    日志，绝不抛出、绝不阻断转换流程（残留目录可容忍）。

    Parameters
    ----------
    profile_dir : Path
        待删除的临时 profile 目录。
    attempts : int
        删除重试次数上限（默认 3）。
    delay : float
        两次重试之间的间隔秒数（默认 0.5）。
    """
    for attempt in range(attempts):
        try:
            shutil.rmtree(profile_dir)
            return
        except Exception as e:
            if attempt + 1 < attempts:
                time.sleep(delay)
            else:
                warning(
                    f"[OfficeConverter] 清理临时 LibreOffice profile 失败: {e}"
                )


def _office_temp_root() -> Path:
    """返回应用自有的 Office 临时根目录（``<data>/temp/office``）。"""
    from sopeek._paths import office_temp_dir

    return Path(office_temp_dir())


def _remove_temp_dir(path: Path, attempts: int = 3, delay: float = 0.3) -> None:
    """尽力删除本次转换的临时目录；失败只告警，残留由启动清理兜底。"""
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            if attempt + 1 < attempts:
                time.sleep(delay)
            else:
                warning(f"[OfficeConverter] 清理临时转换目录失败: {exc}")


def _cleanup_temp_artifact(path: Path | str) -> None:
    """缓存成功后删除临时 PDF 及其专属目录。

    仅删除 ``temp/office`` 内的路径；缓存写入失败时调用方不应调用本函数，
    以保证预览仍能读取原临时文件。
    """
    artifact = Path(path)
    try:
        root = _office_temp_root()
        resolved = Path(os.path.abspath(str(artifact)))
        root_resolved = Path(os.path.abspath(str(root)))
        if not str(resolved).lower().startswith(str(root_resolved).lower()):
            return
        parent = resolved.parent
        if os.path.normcase(str(parent)) == os.path.normcase(str(root_resolved)):
            artifact.unlink(missing_ok=True)
        else:
            _remove_temp_dir(parent)
    except OSError:
        pass


class OfficeConverter:
    """
    职责：
    1. 能力探测 —— 每次 ``convert()`` 调用时运行时重新评估
       MS Office / WPS COM 与 LibreOffice 的可用性，探测函数永不抛出；
    2. 后端分派 —— 按「COM → LibreOffice → 纯 Python」顺序为每个后缀
       选择允许的后端；doc/xls/ppt（legacy）在 COM/LO 均不可用时返回
       安装提示后端（无纯 Python 降级）；xlsx 还可落到 HTML 表格。

    本类无 ``__init__`` 实例状态，全部入口为 classmethod；缓存清理
    （T8）通过 ``_maybe_cleanup_cache()`` 在 ``convert()`` 入口幂等触发。

    使用方式::

        result = OfficeConverter.convert({"path": "a.docx", "suffix": "docx"})
        if result.backend_used == "error":
            print(result.message)
    """

    # ── 公共 API ─────────────────────────────────────────────────────

    @classmethod
    def convert(cls, file_info: dict) -> ConversionResult:
        """
        按「缓存命中 → COM → LibreOffice → 纯 Python」顺序处理 *file_info*。

        先查缓存（T8 缓存 + 本任务接线）：命中直接返回
        ``backend_used="cache"`` 的 PDF 结果，**不调用任何转换后端**；
        未命中则按 COM → LibreOffice → 纯 Python 顺序分派，并在产物为
        PDF 时写入缓存供下次复用。

        与旧实现不同：某一后端**尝试后失败**（返回 ``content_type="error"``）
        会继续尝试下一个允许的后端，而不是立刻把错误交给 UI。例如 pptx 的
        COM 导出失败后仍可落到纯 Python 大纲；docx 可落到 HTML。全部后端
        失败时聚合错误并保留每个后端的技术详情，供「复制错误信息」使用。

        Parameters
        ----------
        file_info : dict
            与 ``PreviewerRegistry.get_previewer_class`` 契约一致：至少含
            ``"suffix"``（文件扩展名，可带前导点或大小写混用）与 ``"path"``
            （T4 分派暂不读取，T5/T6/T7 后端使用）。

        Returns
        -------
        ConversionResult
            永不抛出异常。无任何可用后端时返回错误提示结果
            （``backend_used == "error"``）。

        Notes
        -----
        缓存清理（T8）在方法入口通过 ``_maybe_cleanup_cache()`` 幂等触发，
        同时惰性启动周期清理线程；本服务为 classmethod 风格、无
        ``__init__``，因此清理与缓存读写绝不依赖构造器。
        """
        cls._maybe_cleanup_cache()

        # 缓存命中短路（不调用任何后端）
        cached = cls._get_cache_path_safe(file_info)
        if cached is not None:
            return ConversionResult(
                content_type="pdf",
                content=cached,
                backend_used="cache",
                message="命中 Office 转换缓存",
            )

        suffix = cls._normalize_suffix(file_info)
        if suffix not in _ALLOWED_BACKENDS:
            return cls._unsupported_result(suffix)

        # 零幻灯片 PPTX 预检：PowerPoint 无法把“没有幻灯片”的演示文稿导出为
        # PDF（SaveAs 会抛 0x80004005），且完全没必要为此拉起 Office。
        # 这里在分派前用 OOXML 包结构离线判断，直接返回空状态文案。
        if suffix == "pptx":
            path = cls._extract_path(file_info)
            if path and cls._pptx_slide_count(path) == 0:
                return ConversionResult(
                    content_type="outline",
                    content="该演示文稿没有幻灯片。",
                    backend_used="pure-python",
                    message="演示文稿没有幻灯片，无需转换",
                )

        failures: list[ConversionResult] = []
        for backend in _ALLOWED_BACKENDS[suffix]:
            try:
                result = cls._try_backend(backend, file_info, suffix)
            except Exception as e:  # noqa: BLE001 - 后端异常不得突破 convert()
                warning(f"[OfficeConverter] {backend} 后端异常，视为失败: {e}")
                failures.append(
                    ConversionResult(
                        content_type="error",
                        content="",
                        backend_used="error",
                        message=f"{backend} 转换异常：{e}",
                        detail=traceback.format_exc(),
                        failed_backend=backend,
                    )
                )
                continue

            if result is None:
                # 后端不可用：继续下一级。
                continue
            if result.content_type == "error":
                # 后端尝试过但失败：记录错误后继续尝试下一级（若有）。
                failures.append(result)
                continue
            # 仅 PDF 产物（COM/LO）落缓存，pure-python 文本产物不缓存
            return cls._cache_pdf_result(file_info, result)

        if failures:
            return cls._aggregate_failures(suffix, failures)

        # legacy 格式（doc/xls/ppt）在 COM/LO 均不可用时走到这里。
        return cls._error_backend(suffix)

    @classmethod
    def _aggregate_failures(
        cls,
        suffix: str,
        failures: list[ConversionResult],
    ) -> ConversionResult:
        """聚合所有后端的失败结果，保留完整技术详情。

        展示用 ``message`` 取最后一个后端（通常是最终尝试的纯 Python 或
        COM）的文案；``detail`` 按后端顺序拼接，供 UI 一键复制。

        Parameters
        ----------
        suffix : str
            归一化小写后缀，仅用于日志标识。
        failures : list[ConversionResult]
            按分派顺序收集的非空错误结果。

        Returns
        -------
        ConversionResult
            ``content_type="error"`` 的聚合错误结果。
        """
        primary = failures[-1]
        detail_parts: list[str] = []
        for failure in failures:
            backend = failure.failed_backend or failure.backend_used or "unknown"
            part = f"[{backend}] {failure.message}"
            if failure.detail:
                part += f"\n{failure.detail}"
            detail_parts.append(part)
        debug(
            f"[OfficeConverter] {suffix} 全部后端失败，共 {len(failures)} 条错误"
        )
        return ConversionResult(
            content_type="error",
            content="",
            backend_used="error",
            message=primary.message or ERROR_MESSAGE,
            detail="\n\n".join(detail_parts),
            failed_backend=primary.failed_backend or "error",
        )

    @staticmethod
    def _pptx_slide_count(path: str) -> int | None:
        """离线读取 pptx 幻灯片数量；无法读取时返回 ``None``。

        只使用标准库解析 OOXML 包，不依赖 python-pptx，也绝不启动 Office。
        ``ppt/presentation.xml`` 中缺少 ``<p:sldIdLst>`` 或列表为空即视为
        0 张幻灯片——PowerPoint 无法把这种文件导出为 PDF。
        """
        try:
            with zipfile.ZipFile(path) as archive:
                xml = archive.read("ppt/presentation.xml")
            root = ElementTree.fromstring(xml)
        except Exception as e:  # noqa: BLE001 - 预检失败按未知处理
            debug(f"[OfficeConverter] 读取 pptx 幻灯片数量失败: {e}")
            return None

        namespace = {
            "p": "http://schemas.openxmlformats.org/presentationml/2006/main"
        }
        slide_list = root.find("p:sldIdLst", namespace)
        if slide_list is None:
            return 0
        return len(slide_list.findall("p:sldId", namespace))

    # ── 能力探测（永不抛出；探测放服务内供运行时重新评估） ─────────────

    @classmethod
    def _soffice_available(cls) -> bool:
        """检查可用于转换的本地 LibreOffice 程序，不启动进程。"""
        return _resolve_soffice_binary() is not None

    @classmethod
    def _com_available(cls, suffix: str = "") -> bool:
        """
        探测 MS Office / WPS COM 组件是否可用。永不抛出。

        **只做注册表探测，绝不实际 Dispatch**：旧实现在注册表缺失时会
        ``Dispatch`` 一个隐藏实例来验证，既可能拉起 Office 窗口/进程，也让
        一次预览启动两次 Office。这里改为只读注册表，并同时检查 32/64 位
        视图（HKCR 的合并视图取决于当前 Python 位数，32 位 Office 安装在
        64 位 Python 下可能只在 32 位视图可见）。

        Parameters
        ----------
        suffix : str
            归一化小写后缀；提供时只探测该格式相关的 ProgID
            （pptx 不再因为 Word 已安装而误判 COM 可用）。

        Returns
        -------
        bool
            任一相关 Office/WPS ProgID 已注册则为 ``True``，否则为 ``False``。
        """
        prog_ids = cls._com_prog_ids(suffix) if suffix else _COM_PROG_IDS
        if not prog_ids:
            return False

        try:
            import winreg
        except ImportError:
            return False

        access_modes = [0]
        for name in ("KEY_WOW64_64KEY", "KEY_WOW64_32KEY"):
            flag = getattr(winreg, name, 0)
            if flag and flag not in access_modes:
                access_modes.append(flag)

        for prog_id in prog_ids:
            for access in access_modes:
                try:
                    winreg.OpenKey(
                        winreg.HKEY_CLASSES_ROOT,
                        prog_id,
                        0,
                        winreg.KEY_READ | access,
                    )
                    return True
                except OSError:
                    continue
                except Exception as e:  # noqa: BLE001 - 探测异常视为不可用
                    debug(
                        f"[OfficeConverter] 注册表探测 {prog_id} 异常: {e}"
                    )
                    continue
        return False

    # ── 分派内部实现 ─────────────────────────────────────────────────

    @classmethod
    def _try_backend(
        cls,
        backend: str,
        file_info: dict,
        suffix: str,
    ) -> ConversionResult | None:
        """
        尝试单个 *backend*：先探测可用性，可用则调用对应转换方法。

        探测函数抛出的任何异常都在此捕获并视为不可用（返回 ``None``，
        由调用方降级到下一级），绝不向上传播。纯 Python 后端不参与
        能力探测：docx/pptx 直接尝试，依赖缺失时返回错误结果，由
        ``convert()`` 继续聚合或降级。

        Parameters
        ----------
        backend : str
            ``"com"`` / ``"libreoffice"`` / ``"pure-python"``。
        file_info : dict
            与 ``convert()`` 一致的文件信息。
        suffix : str
            归一化小写后缀（无前导点）。

        Returns
        -------
        ConversionResult | None
            后端不可用或探测失败时返回 ``None``。
        """
        if backend == "libreoffice":
            try:
                available = cls._soffice_available()
            except Exception as e:
                warning(f"[OfficeConverter] LibreOffice 探测异常，视为不可用: {e}")
                available = False
            if not available:
                return None
            return cls._convert_with_libreoffice(file_info, suffix)

        if backend == "com":
            try:
                available = cls._com_available(suffix)
            except Exception as e:
                warning(f"[OfficeConverter] COM 探测异常，视为不可用: {e}")
                available = False
            if not available:
                return None
            return cls._convert_with_com(file_info, suffix)

        # pure-python
        return cls._convert_pure_python(file_info, suffix)

    # ── 各后端转换方法（T4 占位；真实实现由 T5/T6/T7 替换） ────────────

    @classmethod
    def _convert_with_libreoffice(
        cls,
        file_info: dict,
        suffix: str = "",
        *,
        timeout: float = SOFFICE_CONVERSION_TIMEOUT,
    ) -> ConversionResult:
        """
        LibreOffice 后端：通过 soffice 无头子进程把 Office 文档转为 PDF。

        执行流程（Metis B3/D5/D8）：
        1. 输入校验 —— 路径缺失或源文件不存在时返回保留 ``"pdf"/"libreoffice"``
           标识的降级结果（镜像 T7 ``_degraded_result`` 约定，兼容 T4 分派
           路由测试），绝不启动子进程；
        2. 二进制解析 —— ``_resolve_soffice_binary()`` 复用 T2
           ``soffice_paths()`` 候选目录探测本平台可执行文件，
           未找到即错误结果（不抛出）；
        3. 串行化 —— 模块级 ``_LO_CONVERSION_LOCK`` 包裹「启动 + 等待」全程
           （soffice 为单实例程序，同一时刻只允许一个转换运行）；
        4. 临时目录 —— ``tempfile.mkdtemp`` 创建 ``spk_lo_*`` profile 与
           ``spk_lo_out_*`` 输出目录；profile 在 ``finally`` 中尽力删除
           （3 次 × 0.5s 重试，容忍 Windows 文件锁，失败仅告警）；
        5. 取消 seam —— 子进程句柄注册到模块级
           ``_ACTIVE_LO_POPEN[当前线程 ident]``（T9 集成点），无论成败都在
           ``finally`` 中 ``clear_active_lo_popen``；
        6. 超时 —— ``proc.wait(timeout=timeout)`` 超时后 ``terminate()`` →
           短暂宽限 → ``kill()`` → ``wait()``，确保子进程已死。

        Parameters
        ----------
        file_info : dict
            与 ``convert()`` 一致的文件信息（至少含 ``"path"``）。
        suffix : str
            归一化小写后缀（无前导点），仅作兼容参数，不影响输出命名
            （输出名始终为源文件 basename + ``.pdf``）。
        timeout : float
            转换超时秒数，默认 ``SOFFICE_CONVERSION_TIMEOUT``（30 秒）。

        Returns
        -------
        ConversionResult
            成功时 ``content`` 为产物 PDF 的 ``Path``，``content_type="pdf"``，
            ``backend_used="libreoffice"``；源文件缺失返回保留后端标识的降级
            结果；其余失败（二进制缺失 / 超时 / 非零退出 / 未产出 PDF /
            启动失败）返回 ``content_type="error"`` 的错误结果。所有路径
            绝不抛出。
        """
        path = cls._extract_path(file_info)
        if path is None:
            return _lo_degraded_result("LibreOffice 转换失败：无法获取文件路径")
        if not Path(path).is_file():
            return _lo_degraded_result(
                f"LibreOffice 转换失败：源文件不存在：{path}"
            )

        binary = _resolve_soffice_binary()
        if binary is None:
            return _lo_error_result(
                "LibreOffice 转换失败：未检测到 soffice（请安装 LibreOffice）"
            )

        # soffice 为单实例程序：模块级锁包裹「启动 + 等待」全程，保证并发
        # 转换串行执行（T5 测试用阻塞假 soffice 断言启动时间差 >= 阻塞时长）。
        with _LO_CONVERSION_LOCK:
            thread_id = threading.get_ident()
            profile_dir: Path | None = None
            out_dir: Path | None = None
            keep_out_dir = False
            try:
                temp_root = _office_temp_root()
                profile_dir = Path(
                    tempfile.mkdtemp(prefix="lo_profile_", dir=str(temp_root))
                )
                out_dir = Path(
                    tempfile.mkdtemp(prefix="lo_out_", dir=str(temp_root))
                )
                output_pdf = out_dir / f"{Path(path).stem}.pdf"
                profile_flag = "-env:UserInstallation=" + profile_dir.as_uri()
                command = [
                    str(binary),
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(out_dir),
                    profile_flag,
                    str(path),
                ]

                command_text = " ".join(command)
                try:
                    proc = subprocess.Popen(
                        command,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        **_hidden_subprocess_kwargs(),
                    )
                except Exception as e:
                    warning(f"[OfficeConverter] LibreOffice 启动失败: {e}")
                    return _lo_error_result(
                        f"LibreOffice 转换失败：{e}",
                        detail=(
                            f"命令：{command_text}\n"
                            f"二进制：{binary}\n"
                            f"异常：{e!r}"
                        ),
                    )

                # T9 取消 seam：句柄注册到当前线程，成功/失败都必须清理。
                _ACTIVE_LO_POPEN[thread_id] = proc
                try:
                    try:
                        proc.wait(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        _terminate_lo_process(proc)
                        return _lo_error_result(
                            f"LibreOffice 转换超时（超过 {timeout} 秒），"
                            "已终止 soffice 进程",
                            detail=(
                                f"命令：{command_text}\n"
                                f"超时：{timeout} 秒\n"
                                f"输出目录：{out_dir}"
                            ),
                        )
                    if proc.returncode != 0:
                        return _lo_error_result(
                            "LibreOffice 转换失败：soffice 退出码 "
                            f"{proc.returncode}",
                            detail=(
                                f"命令：{command_text}\n"
                                f"退出码：{proc.returncode}\n"
                                f"输出目录：{out_dir}"
                            ),
                        )
                    if not output_pdf.is_file() or output_pdf.stat().st_size == 0:
                        return _lo_error_result(
                            "LibreOffice 转换失败：soffice 退出但未生成 PDF 文件",
                            detail=(
                                f"命令：{command_text}\n"
                                f"期望输出：{output_pdf}\n"
                                f"输出目录：{out_dir}"
                            ),
                        )
                    keep_out_dir = True
                    return ConversionResult(
                        content_type="pdf",
                        content=output_pdf,
                        backend_used="libreoffice",
                    )
                finally:
                    clear_active_lo_popen(thread_id)
            finally:
                if profile_dir is not None:
                    _remove_temp_profile(profile_dir)
                if out_dir is not None and not keep_out_dir:
                    _remove_temp_dir(out_dir)

    @classmethod
    def _convert_with_com(
        cls,
        file_info: dict,
        suffix: str,
    ) -> ConversionResult:
        """
        COM 后端（T6）：通过 MS Office / WPS COM 自动化将文档导出为 PDF。

        Metis A2（非协商项）—— 每次任务新建一个专用线程执行 COM 工作：
        ``pythoncom.CoInitialize()`` 是该任务线程的第一条语句，
        ``pythoncom.CoUninitialize()`` 放入 ``finally``；全部 COM 对象在
        同一任务线程内创建 / 使用 / 释放，绝不跨线程传递。Metis E8 用
        ``threading.get_ident()`` sentinel 断言 CoInitialize 运行在任务线程
        而非调用线程，且失败路径也要执行 CoUninitialize。

        Metis C4（仅顺序，无 WPS 特判）—— ProgID 顺序：doc/docx 依次
        ``Word.Application`` → ``Kwps.Application``；xls/xlsx 依次
        ``Excel.Application`` → ``Ket.Application``；ppt/pptx 依次
        ``PowerPoint.Application`` → ``Kwpp.Application``。任一可实例化即
        使用，不做品牌区分。

        pywin32（pythoncom / win32com.client）惰性导入只在方法内部；
        导入失败返回错误结果。自动化设置：``DispatchEx`` 优先（独立实例，
        不劫持用户已打开的 Office 窗口）、``Visible=False``（仅 Word/Excel
        稳定允许；PowerPoint 禁止隐藏主窗口，改为尽力尝试 + ``WindowState=2``
        最小化）、``ReadOnly=True``、``AutomationSecurity=3``（禁用宏）；
        ``app.Quit()`` 收尾在 ``finally``。

        PowerPoint 导出 PDF 使用 ``SaveAs(路径, 32)``：无窗口打开时先直接
        保存；若特定版本/文件在 ``WithWindow=False`` 下拒绝保存，则关闭后
        以“有窗口 + 最小化”重新打开再试一次。零幻灯片 pptx 会在 ``convert()``
        入口被离线预检拦截，根本不会拉起 PowerPoint（PowerPoint 无法导出
        没有幻灯片的演示文稿）。

        Parameters
        ----------
        file_info : dict
            与 ``convert()`` 一致的文件信息（至少含 ``"path"``）。
        suffix : str
            归一化小写后缀（无前导点），决定 ProgID 顺序。

        Returns
        -------
        ConversionResult
            成功时 ``content`` 为产物 PDF 的 ``Path``，``content_type="pdf"``；
            源文件缺失时返回保留 ``"com"``/``"pdf"`` 标识的降级结果（镜像
            ``_degraded_result`` 约定，兼容 T4 分派路由测试）；
            其余失败返回 ``content_type="error"`` 的错误结果，绝不抛出。
        """
        path = cls._extract_path(file_info)
        if path is None:
            return cls._com_error_result("COM 转换失败：无法获取文件路径")

        # 源文件不存在（如 T4 分派路由测试的占位路径）→ 返回保留后端标识的
        # 降级结果（镜像 ``_degraded_result`` 约定），不启动任务线程。
        if not Path(path).is_file():
            return ConversionResult(
                content_type="pdf",
                content="",
                backend_used="com",
                message="COM 转换失败：源文件不存在",
            )

        try:
            import pythoncom  # noqa: PLC0415
            # 仅探测 pywin32 是否可用；实际分派在 _convert_via_com 内惰性导入。
            import win32com.client  # noqa: PLC0415,F401
        except ImportError:
            return cls._com_error_result(
                "COM 转换失败：pywin32 未安装（pip install pywin32）"
            )

        # Metis A2/E8：结果经线程安全的容器回传；线程目标第一句 CoInitialize。
        results: list[ConversionResult] = []
        task_started_at = datetime.now()

        def _com_task() -> None:
            pythoncom.CoInitialize()
            try:
                results.append(
                    cls._com_convert_in_task(path, suffix, task_started_at)
                )
            except Exception as e:  # noqa: BLE001 - 任务线程兜底
                results.append(
                    cls._com_error_result(
                        f"COM 转换失败：{e}",
                        detail=traceback.format_exc(),
                    )
                )
            finally:
                pythoncom.CoUninitialize()

        thread = threading.Thread(
            target=_com_task,
            name=f"office-com-{suffix}",
            daemon=True,
        )
        thread.start()
        thread.join()

        if not results:
            return cls._com_error_result("COM 转换失败：任务线程未返回结果")
        return results[0]

    @staticmethod
    def _com_error_result(message: str, *, detail: str = "") -> ConversionResult:
        """
        生成 COM 后端的错误结果（``content_type="error"``）。

        Parameters
        ----------
        message : str
            明确的中文错误提示文案。
        detail : str
            面向排障的技术详情（HRESULT / 阶段 / 输出路径等）。

        Returns
        -------
        ConversionResult
            ``backend_used="error"`` 且携带失败后端标识的错误结果。
        """
        return ConversionResult(
            content_type="error",
            content="",
            backend_used="error",
            message=message,
            detail=detail,
            failed_backend="com",
        )

    @classmethod
    def _com_convert_in_task(
        cls,
        path: str,
        suffix: str,
        task_started_at: datetime,
    ) -> ConversionResult:
        """
        在任务线程内完成真实的 COM 自动化转换。仅在任务线程执行。

        该方法的调用方（``_convert_with_com``）已完成 ``CoInitialize`` 并在
        ``finally`` 中调用 ``CoUninitialize``；本方法关注单次文档转换本身。

        Parameters
        ----------
        path : str
            源文档的字符串路径。
        suffix : str
            归一化小写后缀（无前导点）。
        task_started_at : datetime
            本次转换任务开始时间，用于孤儿进程清理时间窗下界（Metis B3）。

        Returns
        -------
        ConversionResult
            成功返回 ``content`` 为产物 PDF 的 ``Path``；失败返回错误结果，
            ``detail`` 含可复制的阶段 / HRESULT / 描述。
        """
        import win32com.client  # noqa: PLC0415

        prog_ids = cls._com_prog_ids(suffix)
        if not prog_ids:
            return cls._com_error_result(
                f"COM 转换失败：不支持的后缀 {suffix}",
                detail=f"不受支持的 Office 后缀：{suffix}",
            )

        out_dir = Path(
            tempfile.mkdtemp(prefix="com_", dir=str(_office_temp_root()))
        )
        output = out_dir / (
            f"{cls._safe_output_stem(path)}_com_{uuid.uuid4().hex}.pdf"
        )

        app = None
        document = None
        stage = "启动 Office"
        extra_details: list[str] = []
        conversion_failed = False
        keep_out_dir = False
        try:
            # Metis C4：按顺序尝试 ProgID，任一成功即使用。
            dispatch_errors: list[str] = []
            for prog_id in prog_ids:
                try:
                    app = cls._dispatch_office_app(win32com.client, prog_id)
                    break
                except Exception as e:
                    warning(f"[OfficeConverter] COM 启动 {prog_id} 失败: {e}")
                    dispatch_errors.append(f"{prog_id}: {e!r}")
            if app is None:
                return cls._com_error_result(
                    "COM 转换失败：未能启动 MS Office/WPS（请确认已安装）",
                    detail="\n".join(dispatch_errors)
                    or "所有候选 ProgID 均无法实例化",
                )

            stage = "配置 Office 实例"
            cls._configure_office_app(app, suffix)

            stage = "打开文档"
            document = cls._open_com_document(app, path, suffix)

            stage = "导出 PDF"
            if suffix in ("doc", "docx"):
                # wdExportFormatPDF = 17
                document.ExportAsFixedFormat(str(output), 17)
            elif suffix in ("xls", "xlsx"):
                # xlTypePDF = 0。Workbook 级导出，避免只导出当前工作表。
                document.ExportAsFixedFormat(0, str(output))
            else:  # ppt / pptx
                # ppSaveAsPDF = 32。真实 QA 验证：win32com 动态分派对
                # PowerPoint 的 SaveAs 没有 PrintRange 参数（传它报
                # "unexpected keyword argument 'PrintRange'"），故不传。
                try:
                    document.SaveAs(str(output), 32)
                except Exception as first_error:
                    warning(
                        "[OfficeConverter] PowerPoint 无窗口 SaveAs 失败，"
                        f"尝试带窗口重试: {first_error}"
                    )
                    extra_details.append(
                        "无窗口 SaveAs 失败：\n"
                        + cls._format_com_error(
                            first_error,
                            stage="导出 PDF（无窗口 SaveAs）",
                            source_path=path,
                            output_path=str(output),
                        )
                    )
                    # 部分 PowerPoint 版本/文件在 WithWindow=False 下拒绝保存。
                    # 关闭后以“有窗口 + 最小化”重新打开再试一次；窗口只在
                    # 首次失败时短暂出现，正常文件不会走到这里。
                    cls._close_com_document(document, suffix)
                    document = None
                    document = app.Presentations.Open(
                        path,
                        ReadOnly=True,
                        Untitled=False,
                        WithWindow=True,
                    )
                    try:
                        app.WindowState = 2
                    except Exception as exc:  # noqa: BLE001
                        debug(
                            "设置 PowerPoint WindowState 失败（忽略）: "
                            f"{exc}"
                        )
                    document.SaveAs(str(output), 32)

            if not output.is_file() or output.stat().st_size == 0:
                return cls._com_error_result(
                    "COM 转换失败：未生成 PDF 产物",
                    detail=cls._com_error_detail(
                        stage=stage,
                        source_path=path,
                        output_path=output,
                        extra="\n".join(extra_details),
                    ),
                )

            keep_out_dir = True
            return ConversionResult(
                content_type="pdf",
                content=output,
                backend_used="com",
            )
        except Exception as e:
            conversion_failed = True
            warning(f"[OfficeConverter] COM 转换异常: {e}")
            return cls._com_error_result(
                cls._com_friendly_message(suffix, stage),
                detail=cls._format_com_error(
                    e,
                    stage=stage,
                    source_path=path,
                    output_path=str(output),
                    extra="\n".join(extra_details),
                ),
            )
        finally:
            cls._close_com_document(document, suffix)
            quit_failed = False
            if app is not None:
                try:
                    app.Quit()
                except Exception as exc:
                    quit_failed = True
                    debug(f"COM 应用退出失败（可能存在残留进程）：{exc}")
            # 成功且 Quit 正常时不启动 PowerShell：既省一次子进程开销，
            # 也降低误伤用户同时打开的 Office 进程的概率。
            if conversion_failed or quit_failed:
                cls._cleanup_orphan_processes(task_started_at)
            if not keep_out_dir:
                _remove_temp_dir(out_dir)

    @staticmethod
    def _dispatch_office_app(client: Any, prog_id: str) -> Any:
        """优先 ``DispatchEx`` 创建独立实例，失败时回退 ``Dispatch``。

        ``DispatchEx`` 不会复用用户已打开的 Office 实例，避免把用户的窗口
        ``Visible=False`` 或 ``Quit()`` 掉；部分 WPS 版本不支持时回退。

        Parameters
        ----------
        client : Any
            ``win32com.client`` 模块。
        prog_id : str
            目标 ProgID。

        Returns
        -------
        Any
            已创建的 COM Application 对象。
        """
        dispatch_ex = getattr(client, "DispatchEx", None)
        if callable(dispatch_ex):
            try:
                return dispatch_ex(prog_id)
            except Exception as exc:  # noqa: BLE001 - 回退 Dispatch
                debug(f"DispatchEx({prog_id}) 失败，回退 Dispatch: {exc}")
        return client.Dispatch(prog_id)

    @staticmethod
    def _configure_office_app(app: Any, suffix: str) -> None:
        """设置隐藏 / 静默 / 禁用宏等 automation 属性。

        PowerPoint 禁止 ``Visible=False``，失败只记调试日志；Word/Excel
        则必须尽快隐藏。所有属性设置均为 best-effort，不因单个属性失败
        中断转换。
        """
        if suffix in ("ppt", "pptx"):
            # PowerPoint 禁止 Visible=False（会抛 "Hiding the application
            # window is not allowed."），只做最小化；演示文稿本身用
            # WithWindow=False 打开，不会出现编辑窗口。
            try:
                app.WindowState = 2  # ppWindowMinimized
            except Exception as exc:  # noqa: BLE001
                debug(f"设置 PowerPoint WindowState 失败（忽略）: {exc}")
            try:
                app.DisplayAlerts = 1  # ppAlertsNone
            except Exception as exc:  # noqa: BLE001
                debug(f"设置 PowerPoint DisplayAlerts 失败（忽略）: {exc}")
        else:
            # Word/Excel 支持隐藏主窗口；尽早设置，避免窗口停留。
            try:
                app.Visible = False
            except Exception as exc:  # noqa: BLE001
                debug(f"设置 Office Visible=False 失败（忽略）: {exc}")
            try:
                app.DisplayAlerts = False
            except Exception as exc:  # noqa: BLE001
                debug(f"设置 Office DisplayAlerts 失败（忽略）: {exc}")

        # msoAutomationSecurityForceDisable = 3：预览不受信任文档时不执行宏。
        try:
            app.AutomationSecurity = 3
        except Exception as exc:  # noqa: BLE001
            debug(f"设置 Office AutomationSecurity 失败（忽略）: {exc}")

    @staticmethod
    def _open_com_document(app: Any, path: str, suffix: str) -> Any:
        """按格式打开文档（只读），返回 Document / Workbook / Presentation。"""
        if suffix in ("doc", "docx"):
            return app.Documents.Open(path, ReadOnly=True)
        if suffix in ("xls", "xlsx"):
            return app.Workbooks.Open(path, ReadOnly=True, UpdateLinks=0)
        return app.Presentations.Open(
            path,
            ReadOnly=True,
            Untitled=False,
            WithWindow=False,
        )

    @staticmethod
    def _close_com_document(document: Any, suffix: str) -> None:
        """按格式关闭文档。

        PowerPoint 的 ``Presentation.Close`` **不接受参数**；旧实现统一传
        ``False`` 会静默失败，导致演示文稿未关闭、``Quit()`` 退出不干净。
        """
        if document is None:
            return
        try:
            if suffix in ("ppt", "pptx"):
                document.Close()
            else:
                document.Close(False)
        except Exception as exc:  # noqa: BLE001 - 关闭失败仅记录
            debug(f"COM 文档关闭失败（可能存在文件占用）：{exc}")

    @staticmethod
    def _safe_output_stem(path: str) -> str:
        """截断并清理源文件名，避免 MAX_PATH / 非法字符导致导出失败。"""
        stem = Path(path).stem or "office"
        cleaned = "".join(
            ch if ch not in '<>:"/\\|?*' else "_" for ch in stem
        )
        return cleaned[:40] or "office"

    @staticmethod
    def _com_error_detail(
        *,
        stage: str,
        source_path: str,
        output_path: Path,
        extra: str = "",
    ) -> str:
        """构造“未生成产物”类错误的技术详情。"""
        lines = [
            f"阶段：{stage}",
            f"源文件：{source_path}",
            f"输出文件：{output_path}",
        ]
        if extra:
            lines.extend(["", extra])
        return "\n".join(lines)

    @staticmethod
    def _format_com_error(
        exc: BaseException,
        *,
        stage: str,
        source_path: str = "",
        output_path: str = "",
        extra: str = "",
    ) -> str:
        """把 ``pywintypes.com_error`` 格式化为可复制的中文诊断块。

        ``com_error.args`` 的典型结构为
        ``(hresult, strerror, excepinfo, argerror)``，其中 ``excepinfo``
        为 ``(wCode, source, description, helpFile, helpContext, scode)``。
        非 COM 异常也能安全处理（只输出 ``repr``）。
        """
        lines: list[str] = []
        if stage:
            lines.append(f"阶段：{stage}")
        if source_path:
            lines.append(f"源文件：{source_path}")
        if output_path:
            lines.append(f"输出文件：{output_path}")

        args = getattr(exc, "args", ())
        hresult = args[0] if len(args) > 0 else None
        text = args[1] if len(args) > 1 else None
        excepinfo = args[2] if len(args) > 2 else None
        argerror = args[3] if len(args) > 3 else None

        if isinstance(hresult, int):
            lines.append(f"HRESULT：0x{hresult & 0xFFFFFFFF:08X}")
        if text:
            lines.append(f"错误说明：{text}")
        if isinstance(excepinfo, (tuple, list)):
            fields = list(excepinfo) + [None] * 6
            code, source, description, help_file, help_context, scode = (
                fields[:6]
            )
            if code:
                lines.append(f"异常代码：{code}")
            if source:
                lines.append(f"来源：{source}")
            if description:
                lines.append(f"描述：{description}")
            if help_file:
                lines.append(f"帮助文件：{help_file}")
            if help_context:
                lines.append(f"帮助上下文：{help_context}")
            if isinstance(scode, int):
                lines.append(f"内部错误码：0x{scode & 0xFFFFFFFF:08X}")
        if argerror:
            lines.append(f"参数错误：{argerror}")
        lines.append(f"原始异常：{exc!r}")
        if extra:
            lines.extend(["", extra])
        return "\n".join(lines)

    @staticmethod
    def _com_friendly_message(suffix: str, stage: str) -> str:
        """把失败阶段翻译成面向用户的中文短消息。"""
        app_name = {
            "doc": "Word",
            "docx": "Word",
            "xls": "Excel",
            "xlsx": "Excel",
            "ppt": "PowerPoint",
            "pptx": "PowerPoint",
        }.get(suffix, "Office")
        if stage == "启动 Office":
            return f"COM 转换失败：无法启动 {app_name}（请确认已安装并激活）"
        if stage == "配置 Office 实例":
            return f"COM 转换失败：{app_name} 初始化失败"
        if stage == "打开文档":
            return (
                f"COM 转换失败：{app_name} 无法打开该文档"
                "（可能已损坏、被占用或受保护）"
            )
        if stage == "导出 PDF":
            return f"COM 转换失败：{app_name} 导出 PDF 失败"
        return f"COM 转换失败：{app_name} 转换失败"

    @staticmethod
    def _com_prog_ids(suffix: str) -> tuple[str, ...]:
        """
        按后缀返回 ProgID 尝试顺序（Metis C4，仅顺序、无品牌特判）。

        Parameters
        ----------
        suffix : str
            归一化小写后缀（无前导点）。

        Returns
        -------
        tuple[str, ...]
            MS Office ProgID 在前的有序元组；未知后缀返回空元组。
        """
        if suffix in ("doc", "docx"):
            return ("Word.Application", "Kwps.Application")
        if suffix in ("xls", "xlsx"):
            return ("Excel.Application", "Ket.Application")
        if suffix in ("ppt", "pptx"):
            return ("PowerPoint.Application", "Kwpp.Application")
        return ()

    @staticmethod
    def _cleanup_orphan_processes(task_started_at: datetime) -> None:
        """
        Metis B3：尽力清理本服务可能残留的 Office/WPS 孤儿进程。

        仅结束 **本次转换启动的隐藏实例** —— 判定条件（须同时满足）：
        - 进程名在 WINWORD / EXCEL / POWERPNT 之列；
        - 进程启动时间晚于本次转换任务开始（``task_started_at``）；
        - 进程没有主窗口标题（COM 隐藏实例 ``Visible=False`` 无窗口；用户
          手动打开的文档必然有标题）。

        找不到 / 无法区分 / powershell 不可用时保持安全（不终止任何进程），
        绝不影响用户的其它 Office 文档。所有操作均为 best-effort，
        任何失败静默忽略、仅记调试日志。

        Parameters
        ----------
        task_started_at : datetime
            本次转换任务开始时间，作为进程启动时间窗下界。
        """
        try:
            cutoff = task_started_at.strftime("%Y-%m-%dT%H:%M:%S")
            stdout = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    (
                        "Get-Process WINWORD,EXCEL,POWERPNT "
                        "-ErrorAction SilentlyContinue | Where-Object {"
                        f"$_.StartTime -ge [datetime]'{cutoff}' -and "
                        "$_.MainWindowTitle -eq ''} | "
                        "Stop-Process -Force -ErrorAction SilentlyContinue"
                    ),
                ],
                capture_output=True,
                timeout=15,
                check=False,
                **_hidden_subprocess_kwargs(),
            )
            if stdout.returncode != 0:
                debug(
                    f"[OfficeConverter] 孤儿进程清理命令退出码 {stdout.returncode}"
                )
        except FileNotFoundError:
            debug("[OfficeConverter] powershell 不可用，跳过孤儿进程清理")
        except Exception as e:
            debug(f"[OfficeConverter] 孤儿进程清理失败（安全跳过）: {e}")

    @classmethod
    def _convert_pure_python(
        cls,
        file_info: dict,
        suffix: str,
    ) -> ConversionResult:
        """
        纯 Python 后端：docx→HTML、pptx→大纲、xlsx→HTML 表格。

        仅在 LibreOffice 与 COM 均不可用或转换失败后被调用（现代格式
        docx/pptx/xlsx）。全部第三方库（mammoth / python-pptx / openpyxl）
        都在各方法内部按需惰性导入（Metis B4-4）—— 模块加载不依赖任何
        Office 库。

        Parameters
        ----------
        file_info : dict
            与 ``convert()`` 一致的文件信息（至少含 ``"path"``）。
        suffix : str
            归一化小写后缀（无前导点）。

        Returns
        -------
        ConversionResult
            - docx：``content_type="html"``，``content`` 为 mammoth 生成的 HTML 字符串；
            - pptx：``content_type="outline"``，``content`` 为逐页纯文本大纲；
            - xlsx：``content_type="html"``，``content`` 为 HTML 表格（含 sheet 名）；
            - 其他后缀（防御性兜底，正常分派不会到达）：错误结果；
            - 依赖缺失 / 解析失败：``backend_used="error"`` 的错误结果，绝不抛出；
            - 文件缺失 / 路径无效：保持 ``content_type`` 与 ``backend_used`` 的
              降级结果（``content=""`` + 提示消息），绝不抛出。
        """
        if suffix == "docx":
            return cls._pure_python_docx(file_info)
        if suffix == "pptx":
            return cls._pure_python_pptx(file_info)
        if suffix == "xlsx":
            return cls._pure_python_xlsx(file_info)
        # 其他后缀（doc/xls/ppt）或未知后缀的防御性兜底 —— 正常分派不会走到这里。
        return ConversionResult(
            content_type="error",
            content="",
            backend_used="pure-python",
            message=ERROR_MESSAGE,
            failed_backend="pure-python",
        )

    # ── 纯 Python 后端各格式实现（T7；所有第三方库导入均为惰性） ───────

    @classmethod
    def _pure_python_docx(cls, file_info: dict) -> ConversionResult:
        """
        docx → HTML（mammoth）。库缺失 / 文件问题一律返回结果而不抛出。

        Parameters
        ----------
        file_info : dict
            含 ``"path"`` 的文件信息。

        Returns
        -------
        ConversionResult
            ``content_type="html"`` 且 ``content`` 为 mammoth 生成的 HTML 字符串；
            失败时为错误 / 降级结果。
        """
        path = cls._extract_path(file_info)
        if path is None:
            return cls._degraded_result("docx", "未提供有效的文件路径")
        if not Path(path).is_file():
            return cls._degraded_result("docx", f"文件不存在或不可读：{path}")

        try:
            import mammoth
        except ImportError:
            warning("[OfficeConverter] mammoth 不可用，docx 纯 Python 降级失败")
            return cls._pure_python_error_result(
                "无法预览 docx 文档：缺少 mammoth 库，请安装依赖后重试",
                detail="ImportError: mammoth",
            )

        try:
            converted = mammoth.convert_to_html(path)
        except Exception as e:
            warning(f"[OfficeConverter] docx 转换失败: {e}")
            return cls._pure_python_error_result(
                f"docx 文档解析失败：{e}",
                detail=traceback.format_exc(),
            )

        return ConversionResult(
            content_type="html",
            content=converted.value,
            backend_used="pure-python",
        )

    @classmethod
    def _pure_python_pptx(cls, file_info: dict) -> ConversionResult:
        """
        pptx → 逐页纯文本大纲（python-pptx）。失败时返回结果而不抛出。

        ``content`` 为逐页大纲：每页以 ``--- 第 N 页 ---`` 标记开头，页内文本行
        按形状 / 段落顺序拼接，页与页之间空行分隔。

        Parameters
        ----------
        file_info : dict
            含 ``"path"`` 的文件信息。

        Returns
        -------
        ConversionResult
            ``content_type="outline"``；失败时为错误 / 降级结果。
        """
        path = cls._extract_path(file_info)
        if path is None:
            return cls._degraded_result("pptx", "未提供有效的文件路径")
        if not Path(path).is_file():
            return cls._degraded_result("pptx", f"文件不存在或不可读：{path}")

        try:
            from pptx import Presentation
        except ImportError:
            warning("[OfficeConverter] python-pptx 不可用，pptx 纯 Python 降级失败")
            return cls._pure_python_error_result(
                "无法预览 pptx 演示文稿：缺少 python-pptx 库，请安装依赖后重试",
                detail="ImportError: python-pptx",
            )

        try:
            presentation = Presentation(path)
        except Exception as e:
            warning(f"[OfficeConverter] pptx 解析失败: {e}")
            return cls._pure_python_error_result(
                f"pptx 文件解析失败：{e}",
                detail=traceback.format_exc(),
            )

        if len(presentation.slides) == 0:
            return ConversionResult(
                content_type="outline",
                content="该演示文稿没有幻灯片。",
                backend_used="pure-python",
            )

        pages: list[str] = []
        has_text = False
        for page_no, slide in enumerate(presentation.slides, start=1):
            lines: list[str] = []
            for shape in slide.shapes:
                if not getattr(shape, "has_text_frame", False):
                    continue
                for paragraph in shape.text_frame.paragraphs:
                    text = "".join(run.text for run in paragraph.runs).strip()
                    if text:
                        lines.append(text)
            if lines:
                has_text = True
            pages.append(f"--- 第 {page_no} 页 ---\n" + "\n".join(lines))

        if not has_text:
            return cls._pure_python_error_result(
                "pptx 中未找到可预览的文本内容（可能是纯图片幻灯片）"
            )

        return ConversionResult(
            content_type="outline",
            content="\n\n".join(pages),
            backend_used="pure-python",
        )

    @classmethod
    def _pure_python_xlsx(cls, file_info: dict) -> ConversionResult:
        """xlsx → HTML 表格（openpyxl）。失败时返回结果而不抛出。

        只读取单元格值（``data_only=True``），不执行公式、不保留图表 /
        图片 / 合并单元格版式。超大工作簿按模块级上限截断，避免阻塞 UI。

        Parameters
        ----------
        file_info : dict
            含 ``"path"`` 的文件信息。

        Returns
        -------
        ConversionResult
            ``content_type="html"`` 且 ``content`` 为 HTML 表格；
            依赖缺失 / 解析失败时为错误结果，绝不抛出。
        """
        path = cls._extract_path(file_info)
        if path is None:
            return cls._degraded_result("xlsx", "未提供有效的文件路径")
        if not Path(path).is_file():
            return cls._degraded_result("xlsx", f"文件不存在或不可读：{path}")

        try:
            import openpyxl
        except ImportError:
            warning("[OfficeConverter] openpyxl 不可用，xlsx 纯 Python 降级失败")
            return cls._pure_python_error_result(
                "无法预览 xlsx 表格：缺少 openpyxl 库，请安装依赖后重试",
                detail="ImportError: openpyxl",
            )

        try:
            workbook = openpyxl.load_workbook(
                path,
                read_only=True,
                data_only=True,
            )
        except Exception as e:
            warning(f"[OfficeConverter] xlsx 解析失败: {e}")
            return cls._pure_python_error_result(
                f"xlsx 文件解析失败：{e}",
                detail=traceback.format_exc(),
            )

        try:
            html_content = cls._render_xlsx_html(workbook)
        except Exception as e:
            warning(f"[OfficeConverter] xlsx 表格渲染失败: {e}")
            return cls._pure_python_error_result(
                f"xlsx 表格渲染失败：{e}",
                detail=traceback.format_exc(),
            )
        finally:
            try:
                workbook.close()
            except Exception as exc:  # noqa: BLE001 - 关闭失败仅记录
                debug(f"[OfficeConverter] 关闭 xlsx 工作簿失败（忽略）: {exc}")

        return ConversionResult(
            content_type="html",
            content=html_content,
            backend_used="pure-python",
        )

    @classmethod
    def _render_xlsx_html(cls, workbook: Any) -> str:
        """把 openpyxl 工作簿渲染为受限的 HTML 表格。

        每个可见工作表渲染为一张表：首行按表头加粗，空单元格用
        ``&nbsp;`` 保持网格。超过 ``XLSX_MAX_PREVIEW_*`` 上限时截断并
        追加提示，避免超大工作簿拖垮 QTextBrowser。
        """
        row_limit = max(1, int(XLSX_MAX_PREVIEW_ROWS))
        col_limit = max(1, int(XLSX_MAX_PREVIEW_COLS))
        sheet_limit = max(1, int(XLSX_MAX_PREVIEW_SHEETS))
        cell_limit = max(1, int(XLSX_MAX_PREVIEW_CELLS))

        parts: list[str] = [
            '<div style="font-family: sans-serif;">',
            '<p style="font-size: 12px;">'
            "纯 Python 表格预览：公式显示缓存值，图表 / 图片 / "
            "合并单元格版式不保留。"
            "</p>",
        ]
        rendered_sheets = 0
        total_cells = 0
        stopped_for_cells = False

        for worksheet in workbook.worksheets:
            if getattr(worksheet, "sheet_state", "visible") != "visible":
                continue
            if rendered_sheets >= sheet_limit:
                parts.append(
                    f'<p style="font-size: 12px;">仅显示前 {sheet_limit} 个工作表，'
                    "完整内容请安装 LibreOffice 或使用 Excel 查看。</p>"
                )
                break

            rendered_sheets += 1
            parts.append(
                f"<h3>工作表：{html.escape(str(worksheet.title))}</h3>"
            )
            rows_html: list[str] = []
            row_truncated = False
            col_truncated = False
            sheet_has_value = False

            # read_only 模式下 max_column / max_row 有时为 None：有值时按实际
            # 范围渲染，避免把 3 列的小表渲染成 50 列空白网格；无值时逐行
            # 去掉尾部空单元格。
            sheet_max_col = getattr(worksheet, "max_column", None) or 0
            sheet_max_row = getattr(worksheet, "max_row", None) or 0
            if sheet_max_col > col_limit:
                col_truncated = True
            if sheet_max_row > row_limit:
                row_truncated = True
            effective_cols = min(sheet_max_col, col_limit) if sheet_max_col else 0

            iter_kwargs: dict = {
                "min_row": 1,
                "min_col": 1,
                "values_only": True,
            }
            if effective_cols > 0:
                iter_kwargs["max_col"] = effective_cols
            if sheet_max_row > 0:
                iter_kwargs["max_row"] = min(sheet_max_row, row_limit)

            for row_index, row in enumerate(
                worksheet.iter_rows(**iter_kwargs),
                start=1,
            ):
                if row_index > row_limit:
                    row_truncated = True
                    break
                if total_cells >= cell_limit:
                    stopped_for_cells = True
                    break

                values = list(row)
                if len(values) > col_limit:
                    values = values[:col_limit]
                    col_truncated = True
                if sheet_max_col == 0:
                    while values and (
                        values[-1] is None or str(values[-1]) == ""
                    ):
                        values.pop()
                remaining = cell_limit - total_cells
                if len(values) > remaining:
                    values = values[:remaining]
                    stopped_for_cells = True
                total_cells += len(values)
                if any(
                    value is not None and str(value) != ""
                    for value in values
                ):
                    sheet_has_value = True

                tag = "th" if row_index == 1 else "td"
                cells_html = "".join(
                    f"<{tag}>{cls._xlsx_cell_html(value)}</{tag}>"
                    for value in values
                )
                if not cells_html:
                    cells_html = "<td>&nbsp;</td>"
                rows_html.append(f"<tr>{cells_html}</tr>")

                if stopped_for_cells:
                    break

            if rows_html and sheet_has_value:
                parts.append(
                    '<table border="1" cellspacing="0" cellpadding="4">'
                    + "".join(rows_html)
                    + "</table>"
                )
            else:
                parts.append("<p>（空工作表）</p>")

            if row_truncated and col_truncated:
                scope = f"{row_limit} 行 × {col_limit} 列"
            elif row_truncated:
                scope = f"{row_limit} 行"
            elif col_truncated:
                scope = f"{col_limit} 列"
            else:
                scope = ""
            if scope:
                parts.append(
                    f'<p style="font-size: 12px;">仅显示前 {scope}，'
                    "完整内容请安装 LibreOffice 或使用 Excel 查看。</p>"
                )
            if stopped_for_cells:
                parts.append(
                    '<p style="font-size: 12px;">内容过多，仅显示前 '
                    f"{cell_limit} 个单元格，完整内容请安装 LibreOffice "
                    "或使用 Excel 查看。</p>"
                )
                break

        if rendered_sheets == 0:
            parts.append("<p>工作簿没有可见工作表。</p>")

        parts.append("</div>")
        return "".join(parts)

    @staticmethod
    def _xlsx_cell_html(value: Any) -> str:
        """把单元格值转成安全的 HTML 片段（空值用 ``&nbsp;`` 保持网格）。"""
        if value is None:
            return "&nbsp;"
        if isinstance(value, datetime):
            text = value.isoformat(sep=" ")
        elif hasattr(value, "isoformat"):
            try:
                text = value.isoformat()
            except Exception:  # noqa: BLE001 - 非标准日期对象退回 str
                text = str(value)
        else:
            text = str(value)
        if not text:
            return "&nbsp;"
        text = html.escape(text)
        return (
            text.replace("\r\n", "\n")
            .replace("\r", "")
            .replace("\n", "<br>")
        )

    @staticmethod
    def _extract_path(file_info: dict) -> str | None:
        """
        从 *file_info* 提取字符串路径；缺失 / 非路径 / 无法转换时返回 ``None``。

        Parameters
        ----------
        file_info : dict
            含 ``"path"`` 键的文件信息。

        Returns
        -------
        str | None
            字符串路径；``file_info`` 非字典、缺少 ``"path"`` 或无法转为字符串
            时返回 ``None``。
        """
        if not isinstance(file_info, dict):
            return None
        path = file_info.get("path")
        if path is None:
            return None
        try:
            return str(path)
        except Exception:
            return None

    @staticmethod
    def _degraded_result(suffix: str, message: str) -> ConversionResult:
        """
        文件缺失 / 路径无效时的降级结果（保持内容类型与后端标识）。

        保持 ``content_type`` 与 ``backend_used="pure-python"`` 是为了兼容 T4
        分派测试（对不存在的占位路径仍断言路由到纯 Python 后端）；实际内容为空，
        失败原因写入 *message*。

        Parameters
        ----------
        suffix : str
            归一化小写后缀，决定保留的 ``content_type``。
        message : str
            降级原因提示文案。

        Returns
        -------
        ConversionResult
            ``content=""`` 且携带提示消息的降级结果。
        """
        return ConversionResult(
            content_type=_PURE_PYTHON_CONTENT_TYPE.get(suffix, "outline"),
            content="",
            backend_used="pure-python",
            message=message,
        )

    @staticmethod
    def _pure_python_error_result(
        message: str,
        *,
        detail: str = "",
    ) -> ConversionResult:
        """
        依赖缺失或解析失败时的错误结果（``backend_used="error"``）。

        Parameters
        ----------
        message : str
            明确的错误提示文案（中文）。
        detail : str
            面向排障的技术详情（异常堆栈 / 缺失依赖名等）。

        Returns
        -------
        ConversionResult
            ``content_type="error"`` 的错误结果。
        """
        return ConversionResult(
            content_type="error",
            content="",
            backend_used="error",
            message=message,
            detail=detail,
            failed_backend="pure-python",
        )

    # ── 错误 / 提示结果 ───────────────────────────────────────────────

    @classmethod
    def _error_backend(cls, suffix: str) -> ConversionResult:
        """
        仅 legacy 格式（doc/xls/ppt）在 COM/LibreOffice 均不可用时走到这里。
        xlsx 已有纯 Python HTML 表格降级，不再返回该安装提示。

        Parameters
        ----------
        suffix : str
            归一化小写后缀，仅作日志 / 调试标识。

        Returns
        -------
        ConversionResult
            ``content_type="error"`` 且 ``message`` 为安装提示文案。
        """
        return ConversionResult(
            content_type="error",
            content="",
            backend_used="error",
            message=ERROR_MESSAGE,
        )

    @classmethod
    def _unsupported_result(cls, suffix: str) -> ConversionResult:
        """
        未知后缀或缺少后缀信息时的错误结果（``convert()`` 不抛出）。

        Parameters
        ----------
        suffix : str
            归一化小写后缀，用于错误消息；为空表示缺失后缀信息。

        Returns
        -------
        ConversionResult
            ``content_type="error"`` 的错误结果。
        """
        message = (
            f"不支持的 Office 文件格式: {suffix}"
            if suffix
            else "缺少文件后缀信息，无法分派 Office 转换"
        )
        return ConversionResult(
            content_type="error",
            content="",
            backend_used="error",
            message=message,
        )

    # ── T8 接入点（缓存清理 seam） ────────────────────────────────────

    @classmethod
    def _maybe_cleanup_cache(cls) -> None:
        """
        缓存清理幂等入口（T8 实现 + 周期清理惰性启动）。

        设计约束：本服务为 classmethod 风格、无 ``__init__``，因此缓存清理
        与周期清理线程的启动都必须在 ``convert()`` 入口调用本方法幂等触发，
        绝不依赖构造器。惰性导入 ``office_cache.cleanup_cache`` 并调用
        （7 天过期 + 大小上限驱逐），同时惰性启动周期清理 daemon 线程
        （默认每 30 分钟自动清理一次）；任何异常都静默降级，绝不阻断
        转换。重复调用无副作用（启动是幂等的）。
        """
        try:
            from sopeek.services.office_cache import (
                _ensure_periodic_cleanup_started,
                cleanup_cache,
            )
        except ImportError:
            # office_cache 缺失时跳过清理，不影响转换主流程。
            return
        try:
            # 首次 convert 时惰性启动周期清理线程（幂等，应用生命周期内只启动一次）。
            _ensure_periodic_cleanup_started()
            cleanup_cache()
        except Exception:
            # 缓存清理失败绝不阻断转换（降级为不清理）。
            pass

    # ── 缓存读写接入（T14 需求接线） ─────────────────────────────────

    @staticmethod
    def _get_cache_path_safe(file_info: dict) -> Path | None:
        """
        查询 *file_info* 的缓存命中路径；任何异常/缺失信息都降级为未命中。

        惰性导入 ``office_cache.get_cache_path``（镜像 ``_maybe_cleanup_cache``
        的容错风格）：导入失败、调用抛异常或目录不可写一律返回 ``None``，
        绝不因缓存问题阻断转换。

        Parameters
        ----------
        file_info : dict
            与 ``convert()`` 一致的文件信息（含 ``"path"``）。

        Returns
        -------
        Path | None
            缓存 PDF 路径（命中），或 ``None``（未命中 / 缓存不可用）。
        """
        try:
            from sopeek.services.office_cache import get_cache_path
        except ImportError:
            return None
        try:
            return get_cache_path(file_info)
        except Exception:
            return None

    @classmethod
    def _cache_pdf_result(cls, file_info: dict, result: ConversionResult) -> ConversionResult:
        """
        把 PDF 产物写入缓存；兼容非缓存路径（原样返回）。

        仅当 *result* 是真实的 PDF 产物（``content_type=="pdf"`` 且
        ``content`` 为 ``Path`` 且 ``backend_used`` 为 ``"libreoffice"`` /
        ``"com"``）时才调用 ``put_cache``；pure-python 后端的
        html/outline **文本**产物没有 PDF 文件，不缓存。``put_cache``
        自带降级：缓存不可写返回原路径，不影响预览。

        Parameters
        ----------
        file_info : dict
            与 ``convert()`` 一致的文件信息。
        result : ConversionResult
            后端已产生的转换结果。

        Returns
        -------
        ConversionResult
            写入缓存后返回缓存内路径结果；非 PDF 产物或缓存失败时返回
            *result* 本身（转换流程照常）。
        """
        is_pdf_artifact = (
            result.content_type == "pdf"
            and isinstance(result.content, Path)
            and result.backend_used in ("com", "libreoffice")
        )
        if not is_pdf_artifact:
            return result
        try:
            from sopeek.services.office_cache import put_cache
        except ImportError:
            return result
        try:
            cached_path = put_cache(file_info, result.content)
        except Exception:
            return result

        # 缓存成功（返回路径与源产物不同）后立即删除本次临时目录；
        # 缓存失败/降级时 put_cache 原样返回源路径，保留给预览读取。
        try:
            if os.path.normcase(os.path.abspath(str(cached_path))) != os.path.normcase(
                os.path.abspath(str(result.content))
            ):
                _cleanup_temp_artifact(result.content)
        except OSError:
            pass

        return ConversionResult(
            content_type=result.content_type,
            content=cached_path,
            backend_used=result.backend_used,
            message=result.message,
            detail=result.detail,
            failed_backend=result.failed_backend,
        )

    # ── 内部工具 ─────────────────────────────────────────────────────

    @staticmethod
    def _normalize_suffix(file_info: dict) -> str:
        """
        从 *file_info* 提取归一化后缀（小写、无前导点）。

        Parameters
        ----------
        file_info : dict
            含 ``"suffix"`` 键的文件信息；非字典或缺少键 / 值为 ``None``
            时返回 ``''``（保证 ``convert()`` 永不抛出）。

        Returns
        -------
        str
            归一化后缀（如 ``"docx"``），无法识别时返回 ``''``。
        """
        if not isinstance(file_info, dict):
            return ''
        suffix = file_info.get("suffix", '')
        if suffix is None:
            return ''
        return str(suffix).lower().lstrip(".")


__all__ = [
    "ConversionResult",
    "ERROR_MESSAGE",
    "LEGACY_SUFFIXES",
    "MODERN_SUFFIXES",
    "OfficeConverter",
    "SOFFICE_CONVERSION_TIMEOUT",
    "SUPPORTED_SUFFIXES",
    "clear_active_lo_popen",
    "get_active_lo_popen",
]
