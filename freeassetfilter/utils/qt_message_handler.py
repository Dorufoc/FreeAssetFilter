# -*- coding: utf-8 -*-
"""qt_message_handler: Qt 层消息捕获模块（fix-log-truncation Todo 3）。

将 ``qInstallMessageHandler`` 安装为进程级全局 handler，按 ``QtMsgType``
映射到统一日志组件（``get_logger()``），使 Qt 层警告/错误首次进入日志
文件与控制台。

约束：
- handler 内绝不调用任何 Qt GUI API；
- handler 内任何异常仅经 ``_write_bootstrap_fallback`` 兜底，绝不向上抛；
- 用 ``threading.local()`` 标志防回环（handler 内日志若再触发 Qt 消息
  直接返回）。
"""

from __future__ import annotations

import threading
from typing import Any

from freeassetfilter.utils.app_logger import _write_bootstrap_fallback, get_logger

_tls = threading.local()

# 已知无害的 Qt 平台层消息前缀：应用关闭时销毁原生子窗口（MPV / GPU 表面 /
# QRhiWidget 等）产生的 WM_DESTROY 级联警告，属 Qt Windows 平台的正常关闭
# 噪音（窗口树在 nativeEvent 级被 Windows 回收），静默避免刷屏。
_SILENT_PREFIXES: tuple[str, ...] = (
    "External WM_DESTROY received for",
)


def _format_qt_message(message: Any, context: Any) -> str:
    """格式化 Qt 消息文本（对 context 字段逐个防御 None/空）。

    Args:
        message: Qt 传递的原始消息（可能非 str）。
        context: QMessageLogContext 或 None，其 file/line/function
            字段可能为 None 或空。

    Returns:
        str: ``[Qt] <原文> (<file>:<line> <function>)``；上下文
        全缺失时退化为 ``[Qt] <原文>``。
    """
    text = message if isinstance(message, str) else str(message)

    file_part: str = ""
    line_part: str = ""
    func_part: str = ""
    if context is not None:
        try:
            raw_file = getattr(context, "file", None)
            if raw_file:
                file_part = str(raw_file)
        except Exception:
            file_part = ""
        try:
            raw_line = getattr(context, "line", None)
            if raw_line:
                line_part = str(raw_line)
        except Exception:
            line_part = ""
        try:
            raw_func = getattr(context, "function", None)
            if raw_func:
                func_part = str(raw_func)
        except Exception:
            func_part = ""

    if not file_part and not line_part and not func_part:
        return f"[Qt] {text}"
    location = f"{file_part or '?'}:{line_part or '?'}"
    if func_part:
        location = f"{location} {func_part}"
    return f"[Qt] {text} ({location})"


def _qt_message_handler(msg_type: Any, context: Any, message: Any) -> None:
    """Qt 全局消息 handler（PySide6 qInstallMessageHandler 约定签名）。

    按 QtMsgType 映射到统一 logger；任何异常仅经 bootstrap fallback
    兜底，绝不向上抛；handler 内不调用任何 Qt GUI API。

    Args:
        msg_type: Qt 消息类型（QtMsgType 枚举）。
        context: QMessageLogContext 或 None。
        message: 原始消息文本。
    """
    if getattr(_tls, "in_handler", False):
        return
    _tls.in_handler = True
    try:
        from PySide6.QtCore import QtMsgType

        formatted = _format_qt_message(message, context)
        # 静默已知无害的平台噪音（如关闭时原生子窗口 WM_DESTROY 级联警告）。
        # 匹配时需剥掉 _format_qt_message 附加的 "[Qt] " 前缀。
        match_text = formatted[5:] if formatted.startswith("[Qt] ") else formatted
        if any(match_text.startswith(prefix) for prefix in _SILENT_PREFIXES):
            return
        logger = get_logger()
        if msg_type == QtMsgType.QtDebugMsg:
            logger.debug(formatted)
        elif msg_type == QtMsgType.QtInfoMsg:
            logger.info(formatted)
        elif msg_type == QtMsgType.QtWarningMsg:
            logger.warning(formatted)
        elif msg_type == QtMsgType.QtCriticalMsg:
            logger.error(formatted)
        elif msg_type == QtMsgType.QtFatalMsg:
            logger.critical(formatted)
        else:
            logger.warning(formatted)
    except Exception as exc:
        try:
            _write_bootstrap_fallback(f"[Qt] handler failed: {exc}")
        except Exception:
            pass
    finally:
        _tls.in_handler = False


def install_qt_message_handler() -> bool:
    """安装 Qt 全局消息 handler。

    Returns:
        bool: 安装成功返回 True，失败返回 False（失败原因经
        bootstrap fallback 记录）。
    """
    try:
        from PySide6.QtCore import qInstallMessageHandler

        qInstallMessageHandler(_qt_message_handler)
        return True
    except Exception as exc:
        try:
            _write_bootstrap_fallback(f"[Qt] install handler failed: {exc}")
        except Exception:
            pass
        return False
