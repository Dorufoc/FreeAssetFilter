"""启动更新检查策略。

本模块只负责"是否值得在启动时检查一次更新"这一策略判断，不涉及 UI：

* 读取 ``general.check_updates_on_startup``（每次调用都读，不缓存进程标志）；
* 响应 ``SPK_DISABLE_UPDATE_CHECK`` 环境变量门控；
* 通过 ``check_state.json`` 持久化 24 小时尝试节流与"每版本一次提醒"去重。

状态文件位于 :func:`get_app_data_path` 目录下，采用同目录临时文件 +
:func:`os.replace` 的原子写法；文件损坏或读写失败一律降级为"空状态 / 检查失败"，
绝不让启动流程因更新检查崩溃。
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from sopeek.utils.app_logger import debug, warning
from sopeek.utils.path_utils import get_app_data_path

#: 两次自动检查之间的最小间隔（24 小时）。
CHECK_INTERVAL_SECONDS = 24 * 3600

#: 启动检查状态文件名。
CHECK_STATE_FILENAME = "check_state.json"

#: 关闭自动检查的环境变量。
DISABLE_ENV_VAR = "SPK_DISABLE_UPDATE_CHECK"

_TRUTHY_ENV_VALUES = frozenset({"1", "true", "yes", "on"})


def check_state_path() -> Path:
    """返回启动检查状态文件路径。

    Returns:
        Path: ``get_app_data_path()/check_state.json``。
    """
    return Path(get_app_data_path()) / CHECK_STATE_FILENAME


def read_check_state() -> dict[str, Any]:
    """读取状态文件；缺失、损坏或非对象内容一律返回空字典。

    Returns:
        dict[str, Any]: 状态副本；任何读取/解析失败都返回 ``{}``。
    """
    try:
        path = check_state_path()
        raw = path.read_text(encoding="utf-8")
    except (OSError, ValueError, TypeError) as exc:
        debug(f"读取更新检查状态失败，按空状态处理: {exc!r}")
        return {}

    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        warning(f"更新检查状态文件损坏，按空状态处理: {exc!r}")
        return {}

    if not isinstance(data, dict):
        warning("更新检查状态文件不是 JSON 对象，按空状态处理")
        return {}
    return dict(data)


def write_check_state(state: dict[str, Any]) -> bool:
    """原子写入状态文件。

    同目录临时文件写满并 ``flush``/``fsync`` 后使用 :func:`os.replace` 覆盖，
    失败时清理临时文件且返回 ``False``，不会向调用方抛异常。

    Args:
        state: 要序列化的状态字典。

    Returns:
        bool: 写入成功返回 ``True``。
    """
    temp_path: Optional[Path] = None
    try:
        path = check_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        temp_path = Path(temp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temp_path), str(path))
        temp_path = None
        return True
    except (OSError, TypeError, ValueError) as exc:
        warning(f"写入更新检查状态失败: {exc!r}")
        return False
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def record_check_attempt(now: Optional[float] = None) -> bool:
    """记录一次启动检查尝试的时间戳。

    Args:
        now: 可注入的时间戳；省略时使用 :func:`time.time`。

    Returns:
        bool: 状态写入是否成功。
    """
    state = read_check_state()
    state["last_attempt_ts"] = time.time() if now is None else float(now)
    return write_check_state(state)


def record_notified_tag(tag: str) -> bool:
    """记录已提醒过的发布标签。

    Args:
        tag: 发布标签（优先 ``remote["tag"]``，缺失时回退版本号）。

    Returns:
        bool: 状态写入是否成功。
    """
    state = read_check_state()
    state["last_notified_tag"] = str(tag)
    return write_check_state(state)


def _env_disabled() -> bool:
    """判断 ``SPK_DISABLE_UPDATE_CHECK`` 是否要求跳过启动检查。"""
    raw = os.environ.get(DISABLE_ENV_VAR, "").strip().lower()
    return raw in _TRUTHY_ENV_VALUES


def _startup_setting_enabled() -> bool:
    """读取 ``general.check_updates_on_startup``；每次调用都重新读取。"""
    try:
        from sopeek.core.managers.settings_manager_v2 import SettingsManagerV2

        value = SettingsManagerV2().get("general.check_updates_on_startup", True)
    except Exception as exc:  # noqa: BLE001 - 设置不可用时按默认开启处理
        warning(f"读取启动更新设置失败，按默认开启处理: {exc!r}")
        return True
    return value if isinstance(value, bool) else True


def _valid_timestamp(value: Any) -> bool:
    """判断状态中的时间戳是否为有限数值。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def should_check_on_startup(now: Optional[float] = None) -> bool:
    """判断本次启动是否应发起自动更新检查。

    读取顺序：环境变量门控 -> 设置开关 -> 24 小时节流。设置值每次调用都重新
    读取，不存在进程级缓存。缺失/非布尔设置按 ``True`` 处理。

    Args:
        now: 可注入的当前时间戳；省略时使用 :func:`time.time`。

    Returns:
        bool: 应当检查返回 ``True``。
    """
    if _env_disabled():
        debug("启动更新检查已被环境变量禁用")
        return False
    if not _startup_setting_enabled():
        return False

    current = time.time() if now is None else float(now)
    last = read_check_state().get("last_attempt_ts")
    if not _valid_timestamp(last):
        return True
    last_value = float(last)
    if current < last_value:
        # 时钟回拨：视为到期，避免用户永远等不到检查。
        return True
    return (current - last_value) >= CHECK_INTERVAL_SECONDS


def maybe_startup_check(window: Any = None) -> Optional[str]:
    """在启动时按策略发起一次非阻塞更新检查。

    委托给 :class:`UpdateService.maybe_startup_check`，由服务先探测
    ``is_available()``，可用且到期时才写入尝试时间并派发 ``check(False)``。

    Args:
        window: 预留的主窗口引用（Todo 13 的通知接线使用），本模块不读取。

    Returns:
        Optional[str]: 已派发的请求 id；跳过或服务不可用时返回 ``None``。
    """
    try:
        from sopeek.services.update_service import get_update_service

        service = get_update_service()
    except Exception as exc:  # noqa: BLE001 - 启动路径不允许更新组件阻断
        warning(f"创建更新服务失败，跳过启动检查: {exc!r}")
        return None
    return service.maybe_startup_check(window)
