"""待安装更新状态。

关于页自动下载完成且校验通过的安装包会在应用数据目录登记一份
``pending_update.json``；下次启动时引导层在创建主窗口前读取该标记，
校验安装包并直接拉起安装器。

本模块只负责标记的原子读写与静态校验，不导入 Qt、不创建更新服务；
真正的原生校验与安装器启动由 :mod:`sopeek.services.installer_launcher`
负责。标记损坏、路径越界、大小不符、版本不匹配等情况一律降级为
"没有待安装更新"并清理标记，绝不让启动流程因更新状态崩溃。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from sopeek.utils.app_logger import debug, warning
from sopeek.utils.path_utils import get_app_data_path, is_path_within_base
from sopeek.utils.version_info import get_local_version

#: 待安装更新状态文件名。
PENDING_UPDATE_FILENAME = "pending_update.json"

#: 下载目录名（与 ``installer_launcher.DOWNLOAD_DIRNAME`` 保持一致）。
DOWNLOAD_DIRNAME = "download"

#: 当前标记结构版本。
SCHEMA_VERSION = 1

_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class PendingUpdate:
    """一份待安装更新标记的稳定快照。"""

    installer_path: str
    sha256: str
    size: int
    version: str
    tag: str
    from_version: str
    created_at: float


@dataclass(frozen=True)
class PendingUpdateResult:
    """启动时处理待安装更新的结果。

    Attributes:
        launched: 是否已成功拉起安装器（调用方应退出当前进程）。
        detail: 失败原因；成功或没有待安装更新时为空串。
    """

    launched: bool
    detail: str = ""


def pending_update_path() -> Path:
    """返回待安装更新标记路径。

    Returns:
        Path: ``get_app_data_path()/pending_update.json``。
    """
    return Path(get_app_data_path()) / PENDING_UPDATE_FILENAME


def _download_root() -> Path:
    """返回允许存放安装包的下载目录。"""
    return Path(get_app_data_path()) / DOWNLOAD_DIRNAME


def _normalize_version(raw: Any) -> str:
    """去掉一个前导 ``v``/``V`` 并返回去空白后的版本号。"""
    text = str(raw or "").strip()
    return text[1:].strip() if text[:1] in ("v", "V") else text


def _valid_sha256(value: Any) -> bool:
    """判断值是否为 64 位十六进制 SHA-256。"""
    return isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) is not None


def _valid_positive_int(value: Any) -> bool:
    """判断值是否为正整数（排除 bool）。"""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _installer_path_error(path_text: Any, expected_size: int = 0) -> str:
    """校验安装包路径；返回空串表示通过，否则返回可日志化的原因。"""
    if not isinstance(path_text, str) or not path_text.strip():
        return "安装包路径为空"
    try:
        candidate = Path(path_text)
        if not candidate.is_absolute():
            return "安装包路径不是绝对路径"
        download_root = _download_root()
        if not is_path_within_base(str(candidate), str(download_root)):
            return "安装包不在下载目录内"
        resolved = Path(os.path.realpath(str(candidate)))
        base_resolved = Path(os.path.realpath(str(download_root)))
        if not resolved.is_relative_to(base_resolved):
            return "安装包解析后越出下载目录"
        if resolved.suffix.lower() != ".exe":
            return "安装包不是 .exe 文件"
        if resolved.is_symlink() or not resolved.is_file():
            return "安装包不存在或不是普通文件"
        actual_size = resolved.stat().st_size
        if expected_size > 0 and actual_size != expected_size:
            return f"安装包大小不符（期望 {expected_size}，实际 {actual_size}）"
        return ""
    except (OSError, ValueError, TypeError) as exc:
        return f"安装包路径校验失败: {exc!r}"


def _write_state(state: dict[str, Any]) -> bool:
    """原子写入待安装更新状态。"""
    temp_path: Optional[Path] = None
    try:
        path = pending_update_path()
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
        warning(f"写入待安装更新状态失败: {exc!r}")
        return False
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def write_pending_update(info: Any, installer_path: str) -> bool:
    """登记一份待安装更新。

    Args:
        info: ``UpdateInfo`` 快照（读取 ``asset`` 与 ``remote`` 字段）。
        installer_path: 下载服务返回的最终安装包路径。

    Returns:
        bool: 标记写入成功返回 ``True``。
    """
    asset = getattr(info, "asset", None)
    remote = getattr(info, "remote", None)
    if not isinstance(asset, dict):
        warning("登记待安装更新失败：缺少安装包信息")
        return False
    if not isinstance(remote, dict):
        remote = {}

    sha256 = str(asset.get("sha256") or "").strip().lower()
    size = asset.get("size")
    if not _valid_sha256(sha256):
        warning("登记待安装更新失败：安装包 SHA-256 无效")
        return False
    if not _valid_positive_int(size):
        warning("登记待安装更新失败：安装包大小无效")
        return False

    path_error = _installer_path_error(installer_path, int(size))
    if path_error:
        warning(f"登记待安装更新失败：{path_error}")
        return False

    version = _normalize_version(
        remote.get("version") or remote.get("tag") or ""
    )
    from_version = _normalize_version(get_local_version())
    if not version:
        warning("登记待安装更新失败：缺少目标版本号")
        return False
    if version == from_version:
        warning("登记待安装更新失败：目标版本与当前版本相同")
        return False

    state = {
        "schema_version": SCHEMA_VERSION,
        "installer_path": str(Path(installer_path).resolve()),
        "sha256": sha256,
        "size": int(size),
        "version": version,
        "tag": str(remote.get("tag") or ""),
        "from_version": from_version,
        "created_at": time.time(),
    }
    return _write_state(state)


def _parse_state(data: Any) -> Optional[PendingUpdate]:
    """把 JSON 对象解析为 ``PendingUpdate``；非法结构返回 ``None``。"""
    if not isinstance(data, dict):
        return None
    if data.get("schema_version") != SCHEMA_VERSION:
        return None

    installer_path = data.get("installer_path")
    sha256 = data.get("sha256")
    size = data.get("size")
    raw_version = data.get("version")
    raw_from_version = data.get("from_version")
    tag = data.get("tag")
    created_at = data.get("created_at")

    if not isinstance(installer_path, str) or not installer_path:
        return None
    if not _valid_sha256(sha256):
        return None
    if not _valid_positive_int(size):
        return None
    if not isinstance(raw_version, str) or not isinstance(
        raw_from_version, str
    ):
        return None
    version = _normalize_version(raw_version)
    from_version = _normalize_version(raw_from_version)
    if not version or not from_version:
        return None
    if not isinstance(tag, str):
        tag = ""
    if not isinstance(created_at, (int, float)) or isinstance(created_at, bool):
        created_at = 0.0

    return PendingUpdate(
        installer_path=installer_path,
        sha256=str(sha256).lower(),
        size=int(size),
        version=version,
        tag=tag,
        from_version=from_version,
        created_at=float(created_at),
    )


def read_pending_update() -> Optional[PendingUpdate]:
    """读取并校验待安装更新标记。

    文件缺失、JSON 损坏、字段非法、安装包越界/缺失/大小不符或版本不匹配
    时清理标记并返回 ``None``。

    Returns:
        Optional[PendingUpdate]: 合法标记；否则 ``None``。
    """
    path = pending_update_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as exc:
        debug(f"读取待安装更新状态失败，按空状态处理: {exc!r}")
        clear_pending_update()
        return None

    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        warning(f"待安装更新状态损坏，已清理: {exc!r}")
        clear_pending_update()
        return None

    pending = _parse_state(data)
    if pending is None:
        warning("待安装更新状态字段非法，已清理")
        clear_pending_update()
        return None

    if pending.from_version != _normalize_version(get_local_version()):
        debug("待安装更新来自其它应用版本，已清理")
        clear_pending_update()
        return None
    if pending.version == pending.from_version:
        debug("待安装更新目标版本等于当前版本，已清理")
        clear_pending_update()
        return None

    path_error = _installer_path_error(pending.installer_path, pending.size)
    if path_error:
        warning(f"待安装更新已失效（{path_error}），已清理")
        clear_pending_update()
        return None
    return pending


def clear_pending_update() -> bool:
    """删除待安装更新标记（幂等）。

    Returns:
        bool: 标记不存在或删除成功返回 ``True``。
    """
    try:
        pending_update_path().unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError as exc:
        warning(f"清理待安装更新状态失败: {exc!r}")
        return False


def apply_pending_update(
    *,
    service_factory: Optional[Callable[[], Any]] = None,
    launcher: Optional[Callable[[Any, str, str], Any]] = None,
) -> PendingUpdateResult:
    """在启动时校验并直接拉起待安装更新。

    没有标记时不会创建更新服务；有标记时无论启动成功或失败都会清理标记，
    避免后续启动反复弹窗。安装包文件本身保留，可再次检查更新重新登记。

    Args:
        service_factory: 可注入的更新服务工厂（测试用）。
        launcher: 可注入的同步校验/启动函数（测试用）；省略时使用
            :func:`sopeek.services.installer_launcher.verify_and_launch_installer`。

    Returns:
        PendingUpdateResult: 是否已拉起安装器及失败原因。
    """
    pending = read_pending_update()
    if pending is None:
        return PendingUpdateResult(False)

    launched = False
    detail = ""
    try:
        if launcher is None:
            from sopeek.services.installer_launcher import (
                verify_and_launch_installer,
            )

            launcher = verify_and_launch_installer
        if service_factory is not None:
            service = service_factory()
        else:
            from sopeek.services.update_service import get_update_service

            service = get_update_service()
        result = launcher(service, pending.installer_path, pending.sha256)
        launched = bool(getattr(result, "launched", False))
        detail = str(getattr(result, "detail", "") or "")
    except Exception as exc:  # noqa: BLE001 - 启动路径不允许更新组件阻断
        launched = False
        detail = f"更新安装失败：{exc}"
    finally:
        clear_pending_update()

    return PendingUpdateResult(launched=launched, detail=detail)
