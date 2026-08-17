"""pytest 日志环境：日志目录准备、双写流与根 logger 接管。

* :func:`prepare_log_dir` —— 清空 ``tests/log/`` 下旧 ``run-*.log`` 后
  创建本次运行的 ``run-<timestamp>.log``，由运行器在启动时调用；
* :func:`pytest_configure` —— 安装 stdlib ``logging`` 根 handler 并把
  ``sys.stdout`` / ``sys.stderr`` 替换为双写流（原始流 + 日志文件），
  产品无感知；对 *console capture* 的 stdout 直写同样被双写（pytest 的
  capture 被配置为 ``no:cacheprovider`` + Tee 后保留原始能力）；
* :func:`get_current_log_path` —— 查询当前日志文件路径。

:class:`_TeeStream` 复用了 ``freeassetfilter.utils.app_logger`` 的
TeeStream 思路，但此处为**独立实现**，不导入任何产品模块，避免测试
基础设施与产品日志互耦。
"""

from __future__ import annotations

import io
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Optional, TextIO

#: 模块所在目录 tests/support/ 的上级两级即仓库根（tests/ → 根）。
_ROOT_DIR: Path = Path(__file__).resolve().parents[2]

#: 默认日志目录。
DEFAULT_LOG_DIR: Path = _ROOT_DIR / "tests" / "log"

#: 当前会话日志文件路径；未 prepare 前为 None。
_log_path: Optional[Path] = None

#: 防止重复安装（同一进程多次 pytest_configure / 重复 prepare）。
_handlers_installed: bool = False

#: 根 logger 格式化模板。
_LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


class _TeeStream(io.TextIOBase):
    """把写入内容同时转发到原始流与日志文件的双写流。

    与产品 ``app_logger.TeeStream`` 同思路但独立实现：测试会话的
    ``print`` / ``sys.stdout.write`` / ``traceback`` 输出在保留控制台
    可见的同时落盘到本次运行日志。

    Attributes:
        original_stream: 被替换前的原始流（控制台或 pytest 捕获器）。
    """

    def __init__(
        self,
        original_stream: Optional[TextIO],
        log_path: Path,
    ) -> None:
        super().__init__()
        self.original_stream: Optional[TextIO] = original_stream
        self._log_file: Optional[IO[str]] = None
        self._encoding: str = "utf-8"
        try:
            self._log_file = open(log_path, "a", encoding=self._encoding, buffering=1)
        except OSError:
            self._log_file = None

    @property
    def encoding(self) -> str:  # type: ignore[override]
        """流编码：优先原始流继承值，否则退化为 utf-8。

        Returns:
            str: 编码名。
        """
        if self.original_stream is not None:
            return str(getattr(self.original_stream, "encoding", None) or self._encoding)
        return self._encoding

    def writable(self) -> bool:
        """恒为可写。

        Returns:
            bool: True。
        """
        return True

    def isatty(self) -> bool:
        """透传原始流的 tty 状态。

        Returns:
            bool: 原始流的 isatty 结果。
        """
        if self.original_stream is not None:
            try:
                return bool(self.original_stream.isatty())
            except (AttributeError, OSError, ValueError):
                return False
        return False

    def write(self, s: object) -> int:  # type: ignore[override]
        """写入原始流并同步到日志文件。

        Args:
            s: 待写入文本；非字符串会被 str() 归一化。

        Returns:
            int: 原始流实际写入的字符数（失败时按输入长度计）。
        """
        if s is None:
            return 0
        text: str = s if isinstance(s, str) else str(s)
        written: int = 0
        if self.original_stream is not None:
            try:
                written = self.original_stream.write(text) or 0
            except (OSError, ValueError, TypeError):
                written = 0
        if self._log_file is not None:
            try:
                self._log_file.write(text)
            except (OSError, ValueError, TypeError):
                pass
        return written if written else len(text)

    def flush(self) -> None:
        """冲刷原始流与日志文件。"""
        if self.original_stream is not None:
            try:
                self.original_stream.flush()
            except (OSError, ValueError, TypeError):
                pass
        if self._log_file is not None:
            try:
                self._log_file.flush()
            except (OSError, ValueError, TypeError):
                pass

    def close(self) -> None:
        """冲刷并关闭日志文件。"""
        self.flush()
        if self._log_file is not None:
            try:
                self._log_file.close()
            except OSError:
                pass
        self._log_file = None
        super().close()


def prepare_log_dir(log_dir: Optional[Path] = None) -> Path:
    """清空日志目录旧文件并创建新会话日志文件。

    幂等：重复调用会清掉上一个会话的 ``run-*.log`` 并重新命名。

    Args:
        log_dir: 覆盖默认日志目录（默认 ``tests/log/``）。

    Returns:
        Path: 新建的 ``run-<timestamp>.log`` 绝对路径。
    """
    global _log_path, _handlers_installed
    target_dir: Path = Path(log_dir).resolve() if log_dir is not None else DEFAULT_LOG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    for old in target_dir.glob("run-*.log"):
        try:
            old.unlink()
        except OSError:
            pass
    stamp: str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path: Path = target_dir / f"run-{stamp}.log"
    log_path.write_text("", encoding="utf-8")
    _log_path = log_path
    _handlers_installed = False  # 新文件需重新装 handler / Tee
    return log_path


def get_current_log_path() -> Optional[Path]:
    """返回当前会话日志文件的路径。

    Returns:
        Optional[Path]: 已 prepare 则返回路径，否则 None。
    """
    return _log_path


def _install_root_handler(log_path: Path) -> None:
    """给 stdlib 根 logger 追加文件 handler（防重复安装）。

    Args:
        log_path: 目标日志文件。
    """
    global _handlers_installed
    if _handlers_installed:
        return
    root_logger: logging.Logger = logging.getLogger()
    handler: logging.Handler = logging.FileHandler(log_path, encoding="utf-8", mode="a")
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root_logger.addHandler(handler)
    _handlers_installed = True


def _install_tee_stdout_stderr(log_path: Path) -> bool:
    """把 sys.stdout/stderr 替换为双写流（若尚未是 _TeeStream）。

    Args:
        log_path: 目标日志文件。

    Returns:
        bool: 至少成功安装一个 Tee 流。
    """
    installed: bool = False
    for name in ("stdout", "stderr"):
        current: TextIO = getattr(sys, name)
        original: Optional[TextIO] = getattr(sys, f"__{name}__", None)
        if isinstance(current, _TeeStream):
            continue
        try:
            setattr(sys, name, _TeeStream(original, log_path))
            installed = True
        except OSError:
            pass
    return installed


def pytest_configure(config: object = None) -> None:
    """pytest 配置钩子：准备日志目录并安装双写环境。

    若运行器已调用 :func:`prepare_log_dir` 则复用其路径；否则在此处
    自动准备（保证纯 pytest 命令行也能落日志）。随后安装根 logger
    handler 与 stdout/stderr Tee。

    Args:
        config: pytest 配置对象（供 hook 兼容，未直接使用）。
    """
    log_path: Path = _log_path if _log_path is not None else prepare_log_dir()
    if not _handlers_installed:
        _install_root_handler(log_path)
    _install_tee_stdout_stderr(log_path)
    print(f"[log_setup] 测试日志: {log_path}", flush=True)