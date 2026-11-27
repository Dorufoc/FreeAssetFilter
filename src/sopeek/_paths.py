"""Sopeek 资源与仓库路径解析——全项目唯一事实来源。

所有需要“找某个目录/文件在哪”的代码都从这里取，禁止再写
``Path(__file__).parents[N]`` 或 ``"../icons"`` 之类的相对推导：
目录层级一变（例如从 ``sopeek/`` 迁到 ``src/sopeek/``）这类代码就会静默指向
不存在的路径。

冻结态（PyInstaller onedir）下 ``__file__`` 落在 ``_internal/``，随包数据与
包代码保持同样的相对位置，因此同一套推导在源码态与冻结态都成立。

Usage:
    from sopeek._paths import icons_dir, native_bin_dir, repo_root
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import List


def package_dir() -> Path:
    """返回 ``sopeek`` 包目录（本文件所在目录）。

    Returns:
        Path: ``<repo>/src/sopeek``（源码态）或 ``<_internal>/sopeek``（冻结态）。
    """
    return Path(__file__).resolve().parent


def repo_root() -> Path:
    """返回仓库根目录；冻结态返回可执行文件所在目录。

    Returns:
        Path: 源码态为 ``<repo>``（``package_dir`` 上溯两级），
        冻结态为 exe 所在目录。
    """
    if getattr(os.sys, "frozen", False):
        return Path(os.sys.executable).resolve().parent
    return package_dir().parent.parent


def src_dir() -> Path:
    """返回源码根 ``src/``（冻结态即 ``_internal``）。

    Returns:
        Path: ``package_dir`` 的父目录。
    """
    return package_dir().parent


def resources_dir() -> Path:
    """返回随包资源根目录。

    Returns:
        Path: ``sopeek/resources/``。
    """
    return package_dir() / "resources"


def icons_dir() -> Path:
    """返回界面与文件类型图标目录。

    Returns:
        Path: ``sopeek/resources/icons/``。
    """
    return resources_dir() / "icons"


def syntax_dir() -> Path:
    """返回 TextMate 语法定义目录（``*.tmLanguage.json``）。

    Returns:
        Path: ``sopeek/resources/syntax/``。
    """
    return resources_dir() / "syntax"


def shaders_dir() -> Path:
    """返回 Qt Shader Baker 编译产物目录（``*.qsb``）。

    Returns:
        Path: ``sopeek/resources/shaders/``。
    """
    return resources_dir() / "shaders"


def docs_dir() -> Path:
    """返回随包文档目录（第三方许可清单）。

    Returns:
        Path: ``sopeek/resources/docs/``。
    """
    return resources_dir() / "docs"


def native_dir() -> Path:
    """返回原生运行时目录（``bin/`` 的父目录）。

    Returns:
        Path: ``sopeek/core/native/``。
    """
    return package_dir() / "core" / "native"


def native_bin_dir() -> Path:
    """返回原生二进制目录。

    Houses mpv runtime DLLs (``libmpv-2.dll``, ffmpeg, libplacebo, etc.),
    compiled Rust/C++ binaries (``thumbnail_generator.dll``,
    ``spk_core.dll``, ``mica_render.dll``), and ffmpeg/ffprobe executables.

    Returns:
        Path: ``sopeek/core/native/bin/``。
    """
    return native_dir() / "bin"


def archive_7z_dir() -> Path:
    """返回 7-Zip 归档工具目录（``7z.exe`` / ``7z.dll``）。

    Returns:
        Path: ``sopeek/core/native/bin/7z/``。
    """
    return native_bin_dir() / "7z"


def native_source_root() -> Path:
    """返回原生源码根目录（Rust/C++ 工程，构建输入而非随包数据）。

    Returns:
        Path: ``<repo>/native/``；冻结态该目录不存在，调用方应只在开发态使用。
    """
    return repo_root() / "native"


def launcher_dir() -> Path:
    """返回独显启动器目录（``SPK-Launcher.exe`` 的构建与安装位置）。

    Returns:
        Path: ``<repo>/packaging/launcher/``。
    """
    return repo_root() / "packaging" / "launcher"


def version_file() -> Path:
    """返回版本号文件 ``SPKVERSION`` 的路径。

    Returns:
        Path: 仓库根（源码态）或 exe 所在目录（冻结态）下的 ``SPKVERSION``。
    """
    return repo_root() / "SPKVERSION"


# ── 用户可写数据目录（运行期唯一事实来源） ──────────────────────────────
#
# 布局（v2）：
#   <root>/config      用户配置
#   <root>/state       会话/应用状态
#   <root>/assets      用户导入资源（背景、LUT）
#   <root>/cache       可再生缓存
#   <root>/logs        日志
#   <root>/updates     更新下载
#   <root>/diagnostics 诊断/性能产物
#   <root>/temp        应用自有临时目录
#
# 只有本模块允许解析 ``SPK_DATA_DIR`` / ``LOCALAPPDATA``；其他模块必须调用
# 下列具名 getter，禁止再自行拼 ``data/...`` 相对路径。


def _default_app_data_root() -> Path:
    """返回默认数据根 ``%LOCALAPPDATA%\\Sopeek\\data``（不创建）。"""
    local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
    if not local_appdata:
        local_appdata = os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return Path(local_appdata) / "Sopeek" / "data"


def app_data_root() -> Path:
    """返回应用数据根目录（``SPK_DATA_DIR`` 优先），按需创建。

    ``SPK_DATA_DIR`` 每次调用都重新读取，不做进程内缓存——测试隔离与便携
    部署可以在运行期切换目录。相对路径按当前工作目录解析为绝对路径。

    Returns:
        Path: 数据根绝对路径。
    """
    override = os.environ.get("SPK_DATA_DIR", "").strip()
    if override:
        root = Path(os.path.expanduser(override))
        if not root.is_absolute():
            root = Path(os.path.abspath(str(root)))
    else:
        root = _default_app_data_root()
    root = Path(os.path.abspath(str(root)))
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_app_data_path() -> Path:
    """返回应用数据目录（兼容旧 API，等价于 :func:`app_data_root`）。

    Returns:
        Path: 应用数据目录绝对路径。
    """
    return app_data_root()


def _ensure_dir(path: Path) -> Path:
    """确保目录存在并返回同一路径。"""
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    """返回用户配置目录 ``<root>/config``。"""
    return _ensure_dir(app_data_root() / "config")


def state_dir() -> Path:
    """返回会话/应用状态目录 ``<root>/state``。"""
    return _ensure_dir(app_data_root() / "state")


def assets_dir() -> Path:
    """返回用户导入资源根目录 ``<root>/assets``。"""
    return _ensure_dir(app_data_root() / "assets")


def cache_dir() -> Path:
    """返回可再生缓存根目录 ``<root>/cache``。"""
    return _ensure_dir(app_data_root() / "cache")


def logs_dir() -> Path:
    """返回日志目录 ``<root>/logs``。"""
    return _ensure_dir(app_data_root() / "logs")


def updates_dir() -> Path:
    """返回更新根目录 ``<root>/updates``。"""
    return _ensure_dir(app_data_root() / "updates")


def diagnostics_dir() -> Path:
    """返回诊断/性能产物根目录 ``<root>/diagnostics``。"""
    return _ensure_dir(app_data_root() / "diagnostics")


def temp_dir() -> Path:
    """返回应用自有临时根目录 ``<root>/temp``。"""
    return _ensure_dir(app_data_root() / "temp")


# ── 具体目录 ─────────────────────────────────────────────────────────


def backgrounds_dir() -> Path:
    """返回自定义背景目录 ``<root>/assets/backgrounds``。"""
    return _ensure_dir(assets_dir() / "backgrounds")


def luts_dir() -> Path:
    """返回用户 LUT 目录 ``<root>/assets/luts``。"""
    return _ensure_dir(assets_dir() / "luts")


def icon_cache_dir() -> Path:
    """返回图标缓存目录 ``<root>/cache/icons``。"""
    return _ensure_dir(cache_dir() / "icons")


def thumbnails_dir() -> Path:
    """返回缩略图缓存目录 ``<root>/cache/thumbnails``。"""
    return _ensure_dir(cache_dir() / "thumbnails")


def office_cache_dir() -> Path:
    """返回 Office 转 PDF 缓存目录 ``<root>/cache/office``。"""
    return _ensure_dir(cache_dir() / "office")


def lut_previews_dir() -> Path:
    """返回 LUT 预览缓存目录 ``<root>/cache/lut_previews``。"""
    return _ensure_dir(cache_dir() / "lut_previews")


def updates_download_dir() -> Path:
    """返回安装包下载目录 ``<root>/updates/download``。"""
    return _ensure_dir(updates_dir() / "download")


def performance_dir() -> Path:
    """返回性能快照目录 ``<root>/diagnostics/performance``。"""
    return _ensure_dir(diagnostics_dir() / "performance")


def probes_dir() -> Path:
    """返回原生诊断探针目录 ``<root>/diagnostics/probes``。"""
    return _ensure_dir(diagnostics_dir() / "probes")


def office_temp_dir() -> Path:
    """返回 Office 转换临时目录 ``<root>/temp/office``。"""
    return _ensure_dir(temp_dir() / "office")


# ── 具体文件 ─────────────────────────────────────────────────────────


def settings_file() -> Path:
    """返回设置文件 ``<root>/config/settings.json``。"""
    return config_dir() / "settings.json"


def ai_accounts_file() -> Path:
    """返回 AI 账号配置 ``<root>/config/ai_accounts.json``。"""
    return config_dir() / "ai_accounts.json"


def favorites_file() -> Path:
    """返回收藏夹 ``<root>/config/favorites.json``。"""
    return config_dir() / "favorites.json"


def last_path_file() -> Path:
    """返回上次浏览路径 ``<root>/state/last_path.json``。"""
    return state_dir() / "last_path.json"


def staging_pool_file() -> Path:
    """返回暂存池备份 ``<root>/state/staging_pool.json``。"""
    return state_dir() / "staging_pool.json"


def update_check_file() -> Path:
    """返回更新检查状态 ``<root>/state/update_check.json``。"""
    return state_dir() / "update_check.json"


def pending_update_file() -> Path:
    """返回待安装更新标记 ``<root>/state/pending_update.json``。"""
    return state_dir() / "pending_update.json"


def runtime_instance_file() -> Path:
    """返回运行实例信息 ``<root>/state/runtime_instance.json``。"""
    return state_dir() / "runtime_instance.json"


def open_request_file() -> Path:
    """返回外部「打开路径」请求 ``<root>/state/open_request.json``。

    资源管理器右键菜单会以 ``--open-path`` 启动第二个进程；当主实例已运行时，
    第二个进程把目标路径写入本文件并置位唤醒事件，主实例轮询消费后导航到该
    位置。使用文件而不是命令行转发，是因为命名管道/窗口消息在跨会话与权限
    边界上都更脆弱，而 state 目录天然是每个用户私有的。
    """
    return state_dir() / "open_request.json"


def file_info_cache_file() -> Path:
    """返回文件信息缓存 ``<root>/cache/file_info.json``。"""
    return cache_dir() / "file_info.json"


def layout_version_file() -> Path:
    """返回存储布局版本标记 ``<root>/.layout_version.json``。"""
    return app_data_root() / ".layout_version.json"


def soffice_paths() -> List[Path]:
    """返回可能包含 soffice 的目录列表（去重、按探测顺序）。

    依次探测：

    1. ``%ProgramFiles%\\LibreOffice\\program``
    2. ``%ProgramFiles(x86)%\\LibreOffice\\program``
    3. ``shutil.which`` 找到的 ``soffice``/``soffice.com`` 所在目录
    4. :func:`native_bin_dir`（便携版预留位置）

    永不抛异常、永不启动 soffice——只做路径探测。

    Returns:
        List[Path]: 去重且存在性过滤后的候选目录；未检测到 LibreOffice 时为空列表。
    """
    candidates: List[Path] = []

    # 1/2: 标准 Windows 安装位置（环境变量优先，硬编码兜底）。
    for program_files in (
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ):
        program_dir = Path(program_files) / "LibreOffice" / "program"
        if program_dir.is_dir() and any(
            (program_dir / name).is_file() for name in ("soffice.exe", "soffice.com")
        ):
            candidates.append(program_dir)

    # 3: PATH 查找——取已解析二进制所在目录。
    for name in ("soffice", "soffice.com"):
        try:
            found = shutil.which(name)
        except Exception:
            continue
        if found:
            candidates.append(Path(found).resolve().parent)

    # 4: 便携版/应用目录预留位置。
    native_bin = native_bin_dir()
    if native_bin.is_dir():
        candidates.append(native_bin)

    seen: set = set()
    result: List[Path] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
    return result


__all__ = [
    "package_dir",
    "repo_root",
    "src_dir",
    "resources_dir",
    "icons_dir",
    "syntax_dir",
    "shaders_dir",
    "docs_dir",
    "native_dir",
    "native_bin_dir",
    "archive_7z_dir",
    "native_source_root",
    "launcher_dir",
    "version_file",
    "app_data_root",
    "get_app_data_path",
    "config_dir",
    "state_dir",
    "assets_dir",
    "cache_dir",
    "logs_dir",
    "updates_dir",
    "diagnostics_dir",
    "temp_dir",
    "backgrounds_dir",
    "luts_dir",
    "icon_cache_dir",
    "thumbnails_dir",
    "office_cache_dir",
    "lut_previews_dir",
    "updates_download_dir",
    "performance_dir",
    "probes_dir",
    "office_temp_dir",
    "settings_file",
    "ai_accounts_file",
    "favorites_file",
    "last_path_file",
    "staging_pool_file",
    "update_check_file",
    "pending_update_file",
    "runtime_instance_file",
    "file_info_cache_file",
    "layout_version_file",
    "soffice_paths",
]
