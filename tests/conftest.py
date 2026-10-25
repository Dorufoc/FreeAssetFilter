# -*- coding: utf-8 -*-
"""集成测试配置与共享 fixtures（tests/comprehensive-refactor 计划 todo-4 重写）。

本文件是 todo 7-29 各测试套件的容器 fixture 来源，遵循项目既有的
单例重置纪律与跨线程模式。要点：

* ``qapp``（session）：全局唯一 QApplication，附带 ``global_font`` 与
  应用级别的 ``settings_manager`` / ``theme_manager`` 属性，
  供 widget / component 初始化时不因缺少实例而 AttributeError。
* ``reset_singletons``（autouse, function）：在每个测试函数前重置全部已知
  单例的真实内部状态。清单经 V3 事实审计（详见 conftest 内 docstring），
  与旧实现（old-tests-snapshot/tests/conftest.py:234-251）相比新增了
  ThumbnailManager / MPVManager / thumbnail 模块级全局 / AppLogger /
  AsyncIconLoader，且对"类级属性不存在"的情况使用 getattr/hasattr 防护。
* 会话级可用性探测：``mpv_available`` / ``soffice_available`` /
  ``com_available`` / ``rust_available`` / ``py7z_available`` /
  ``cpp_lut_available``——复用归档旧逻辑并新增 Rust / C++ 原生探测。
* 数据生成器 fixtures 全部基于 ``tests.support.data_factories``，取代旧
  conftest 中以 ``temp_image_file`` 等命名的重复实现。
* ``FAF_VISUAL`` 环境变量驱动 ``visual_mode``，供 GUI 测试区分视觉模式。
"""

from __future__ import annotations

import ctypes
import importlib.util
import json
import os
import subprocess
import tempfile

try:  # 非 Windows 无 winreg；项目仅支持 Windows，守卫保证导入失败时回退 COM 探测
    import winreg
except ImportError:  # pragma: no cover
    winreg = None  # type: ignore[assignment]

from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

# 项目根目录加入 sys.path，保证裸 `pytest`（非 -m）也能解析 freeassetfilter/。
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(_PROJECT_ROOT))

# 数据目录统一重定向（review 3.5-4）：``FAF_DATA_DIR`` 会话级指向临时目录，
# 作为"逐测试重定向"（redirect_layout_app_data_writes）之外的全局安全网，
# 保证任何走 get_app_data_path() 的模块都不会落到仓库真实 data/。
# 全局引用持有到进程结束，随解释器退出自动清理。
_FAF_TEST_DATA_TMP = tempfile.TemporaryDirectory(prefix="faf_test_data_")
os.environ["FAF_DATA_DIR"] = _FAF_TEST_DATA_TMP.name
try:
    # 缓存可能已被运行器/更早的导入预热为真实 data/：强制失效，
    # 保证进程内所有后续解析都走 FAF_DATA_DIR。
    import freeassetfilter.utils.path_utils as _path_utils_module

    _path_utils_module._APP_DATA_PATH_CACHE = None
except Exception:
    pass  # 包尚未可用时忽略（首次解析自然走环境变量）


# =============================================================================
# 会话级 QApplication
# =============================================================================
@pytest.fixture(scope="session")
def qapp() -> Any:
    """提供全局唯一的 QApplication 实例（session scope）。

    镜像归档旧实现 old-tests-snapshot/tests/conftest.py:16-34：先取现有
    实例（避免重复创建），再挂载 ``global_font=QFont("Microsoft YaHei", 9)``，
    最后补充 ``settings_manager`` / ``theme_manager`` 属性，防止组件初始化时因
    缺少这两个应用级实例而抛 AttributeError。

    Returns:
        QApplication: 全局应用实例。
    """
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(os.sys.argv)
    app.global_font = QFont("Microsoft YaHei", 9)
    # 旧版 SettingsManager/ThemeManager 已移除：应用级设置管理器由测试
    # 需要时自行注入 SettingsManagerV2（默认 None 防止写真实数据文件）。
    if not hasattr(app, "settings_manager"):
        app.settings_manager = None
    yield app


@pytest.fixture
def qt_app(qapp: Any) -> Any:
    """``qapp`` 的别名，兼容旧测试中的 ``qt_app`` 引用。

    Args:
        qapp: 会话级 QApplication（由父 fixture 提供）。

    Returns:
        Any: 与 ``qapp`` 相同的应用实例。
    """
    return qapp


def _cleanup_qt_runtime() -> None:
    """回收会话级 Qt 原生资源（GPU 渲染器线程 / 线程池）。

    会话结束时调用：Mica GPU 的常驻守护线程（``faf-mica-gpu``）持有
    D3D11/COM 上下文，若不显式回收，测试进程退出阶段可能撞上原生清理而
    触发访问冲突（历史症状：``test_styled_complex`` 之后组合运行偶发
    ``0xC0000005``）。``shutdown_gpu_renderer`` 内部有界 join，卡死时只
    停用不强杀；随后排空全局线程池，避免残留 QRunnable 跨文件存活。
    任何步骤失败都不抛出（清理是尽力而为）。

    Returns:
        None。
    """
    try:
        from freeassetfilter.ui.mica.gpu import shutdown_gpu_renderer

        shutdown_gpu_renderer()
    except Exception:
        pass  # 会话收尾：清理失败不拖垮测试结果
    try:
        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().waitForDone(5000)
    except Exception:
        pass  # 会话收尾：排空线程池失败不阻塞退出


@pytest.fixture(autouse=True, scope="session")
def cleanup_qt_runtime(qapp: Any) -> Any:
    """会话级 Qt 原生资源清理（依赖 ``qapp``，在会话最后执行 teardown）。

    在整套测试结束后回收 Mica GPU 渲染器常驻线程与全局线程池，
    并做一轮有界事件泵让 deferred delete 落地，最后统计存活顶层窗口
    （仅在 ``FAF_TEST_RUNTIME_DEBUG=1`` 时打印，供隔离诊断）。

    Args:
        qapp: 会话级 QApplication（保证清理发生在应用存活期内）。

    Yields:
        Any: 传入的 ``qapp``（透传，便于其它 session fixture 复用）。
    """
    yield qapp
    _cleanup_qt_runtime()
    if os.environ.get("FAF_TEST_RUNTIME_DEBUG") == "1":
        try:
            alive = len(qapp.topLevelWidgets())
            print(f"[cleanup] session end: topLevelWidgets={alive}", flush=True)
        except Exception:
            pass  # 诊断打印失败可忽略


# =============================================================================
# 单例重置（autouse）
# =============================================================================
def _reset_all_singletons() -> None:
    """归零全部已知单例的内部状态（供 reset_singletons 前后两阶段复用）。

    重置清单（V3 事实审计 + review 3.5-4 补齐）：

    * 类级单例：``HeartbeatManager`` / ``ThumbnailManager`` / ``MPVManager`` /
      ``AppLogger`` 的 ``_instance`` 一律归零；类上真实存在
      ``_initialized`` 时一并归零（``MPVManager`` 无类级 ``_initialized``，
      用 ``hasattr`` 守卫跳过）。
    * 模块级惰性缓存（类属性重置覆盖不到）：
      ``thumbnail_manager._thumbnail_manager``、``app_logger._app_logger``、
      ``async_icon_loader._instance``、``faf_core_bridge._instance``、
      ``lut_preview_generator._preview_generator``、
      ``lut_preview_native._module``、``mica_render._LIB``、
      ``py7z_core._7z_core_instance``。
    * ``ui/theme/app_stylesheet`` 的 QSS 注册表单例：经
      ``reset_qss_registry()`` 清空会话级累积（原因见下方内联注释）。

    **明确不做**的：

    * **不重置** ``ui/theme/theme_manager`` 的主题单例：``theme`` 包在导入时
      以 ``tm = get_theme_manager()`` 绑定模块级引用，多个模块
      ``from theme import tm`` 持有同一对象；归零 ``_theme_manager`` 只会让
      后续 ``get_theme_manager()`` 造出新实例，与既有 ``tm`` 引用分裂。
      （``core/managers/theme_manager.py`` 模块本身不是单例。）
    * 会话级原生资源（Mica GPU 渲染线程 / 全局线程池）由
      ``cleanup_qt_runtime`` 在整套测试结束时统一回收，不逐测试重置。

    Returns:
        None。
    """
    from freeassetfilter.core.managers.heartbeat_manager import HeartbeatManager
    from freeassetfilter.core.managers.mpv_manager import MPVManager
    from freeassetfilter.core.managers.thumbnail_manager import ThumbnailManager
    from freeassetfilter.utils.app_logger import AppLogger
    from freeassetfilter.utils.async_icon_loader import AsyncIconLoader

    import freeassetfilter.core.managers.thumbnail_manager as _thumbnail_module

    # 更新入口控制器持有弹窗并订阅 UpdateService 信号，先释放再销毁服务。
    try:
        from freeassetfilter.ui.update_entry import reset_update_entry_controller

        reset_update_entry_controller()
    except Exception:  # 清理阶段：控制器可能尚未创建
        pass

    # UpdateService 持有私有 QThreadPool，先走 shutdown/close 再清空单例。
    try:
        from freeassetfilter.services.update_service import UpdateService

        _update_service = UpdateService._instance
        if _update_service is not None:
            try:
                _update_service.shutdown(timeout=2.0)
            except Exception:  # 清理阶段：服务可能已自行关闭
                pass
            try:
                _update_service.close()
            except Exception:  # 清理阶段：重复关闭必须无副作用
                pass
        UpdateService._instance = None
        UpdateService._initialized = False
    except Exception:  # 测试环境可能尚未加载 UpdateService
        pass

    # 类级 _instance 一律归零；_initialized 仅当类上真实存在该属性时才归零。
    for _singleton in (
        HeartbeatManager,
        ThumbnailManager,
        MPVManager,
        AppLogger,
    ):
        _singleton._instance = None
        if hasattr(_singleton, "_initialized"):
            _singleton._initialized = False

    # thumbnail_manager 模块级全局缓存（get_thumbnail_manager 的返回值）。
    _thumbnail_module._thumbnail_manager = None

    # AsyncIconLoader 模块级单例缓存。
    AsyncIconLoader._instance = None

    # faf_core 桥模块级单例缓存（get_faf_core_bridge 的返回值）。
    import freeassetfilter.core.native.bridges.faf_core_bridge as _faf_core_bridge

    _faf_core_bridge._instance = None

    # 模块级惰性缓存（类属性重置覆盖不到；review 3.5-4 补齐）。
    import freeassetfilter.core.native.bridges.lut_preview_generator as _lut_gen
    import freeassetfilter.core.native.bridges.lut_preview_native as _lut_native
    import freeassetfilter.core.native.bridges.mica_render as _mica_render
    import freeassetfilter.core.native.bridges.py7z_core as _py7z
    import freeassetfilter.utils.app_logger as _app_logger_module

    _app_logger_module._app_logger = None
    _lut_gen._preview_generator = None
    _lut_native._module = None
    _mica_render._LIB = None
    _py7z._7z_core_instance = None

    # 数据目录缓存逐测试失效：即使某处（运行器预导入/晚到的异步回调）
    # 曾把真实 data/ 写进缓存，后续一律重新解析到 FAF_DATA_DIR 临时目录。
    import freeassetfilter.utils.path_utils as _path_utils_module

    _path_utils_module._APP_DATA_PATH_CACHE = None

    # A1 QSS singleton: drop app-stylesheet registry between tests so the
    # central sheet never accumulates session-wide under the session qapp
    # (full-tree re-polish cost grows with accumulation). Live widgets
    # re-register from their own constructors; visual tests pump events
    # which triggers the coalesced re-apply automatically.
    try:
        from freeassetfilter.ui.theme.app_stylesheet import reset_qss_registry

        reset_qss_registry()
    except Exception:
        pass  # 测试隔离：QSS 注册表重置失败不阻塞用例


@pytest.fixture(autouse=True, scope="function")
def reset_singletons() -> None:
    """在每个测试函数前后重置全局单例状态，保证测试隔离性。

    setup 阶段归零（防止上一测试残留污染），teardown 阶段再次归零
    （确保断言"测试结束后 ``_instance is None``"能够成立，且下一测试的
    setup 归零是幂等的）。完整重置清单见 :func:`_reset_all_singletons`
    的 docstring——类级单例 + 模块级惰性缓存 + QSS 注册表。

    Returns:
        None。
    """
    _reset_all_singletons()
    yield
    _reset_all_singletons()


@pytest.fixture(autouse=True, scope="function")
def scavenge_leaked_toplevel_widgets() -> None:
    """测试隔离清道夫：销毁本测试新建的顶层窗口，遏制跨测试控件累积。

    背景（全量回归诊断结论）：UI 测试大量创建 ``MainWindow`` / 预览布局后
    仅对根窗口 ``deleteLater()``；对未 ``show()`` 的窗口或异常回溯扣住引用的
    场景，deferred delete 不落地，存活控件跨测试线性增长（实测 250 个测试
    后 5785 存活控件 / 263 顶层窗口）。应用级 QSS 单例（``app_stylesheet``）
    的 ``setStyleSheet`` 全树重刷成本随存活规模增长，最终任意一次
    ``processEvents()`` 触发的重刷都会超时（历史症状：
    ``test_show_event_gating`` 30s timeout；见
    ``tests/support/qt_helpers.py::scavenge_toplevel_widgets``）。

    本夹具在测试开始时快照现存顶层窗口集合，结束后对新增窗口统一
    close + deleteLater 并做有界事件泵，使 DeferredDelete 真正派发。
    受保护的会话级宿主窗口（若存在）通过快照排除。

    Returns:
        None。
    """
    from tests.support.qt_helpers import (
        scavenge_toplevel_widgets,
        toplevel_widget_snapshot,
    )

    baseline = toplevel_widget_snapshot()
    yield
    try:
        removed = scavenge_toplevel_widgets(baseline)
        if removed and os.environ.get("FAF_TEST_SCAVENGE_DEBUG") == "1":
            print(
                f"[scavenge] removed {removed} toplevel widget(s) after "
                f"{os.environ.get('PYTEST_CURRENT_TEST', '?')}",
                flush=True,
            )
    except Exception:
        # 清道夫失败绝不拖垮测试结果（隔离优化而非断言）。
        pass


@pytest.fixture(autouse=True, scope="function")
def redirect_layout_app_data_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """隔离 UI 布局层的持久化写入，测试一律落到 pytest 临时目录。

    背景：FileSelectorLayout / FilePoolLayout 在导航/增删文件时会把
    ``last_path.json`` / ``staging_pool_backup.json`` 写入真实的
    ``freeassetfilter/data/`` 目录，导致测试结束后真实应用启动时可能
    恢复并跳转到 pytest 的临时目录（``_pytest`` 会保留最近几次运行的
    basetemp）。此处把两个布局模块命名空间中已绑定的
    ``get_app_data_path`` 引用统一重定向到本用例的临时目录，保证布局
    测试默认与正式数据隔离（旧版 CustomFileSelector 测试已自行重定向
    ``save_path_file``，不受影响）。

    Args:
        tmp_path: pytest 内置的每测试临时目录。
        monkeypatch: pytest monkeypatch fixture。

    Returns:
        None。
    """
    import freeassetfilter.ui.layout.file_pool_layout as fpl_mod
    import freeassetfilter.ui.layout.file_selector_layout as fsl_mod

    _app_data: Path = tmp_path / "faf_test_appdata"
    _app_data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(fsl_mod, "get_app_data_path", lambda: _app_data)
    monkeypatch.setattr(fpl_mod, "get_app_data_path", lambda: _app_data)


@pytest.fixture
def settings_manager(tmp_path: Path) -> Any:
    """提供使用临时设置文件的 SettingsManagerV2 实例（function scope）。

    Args:
        tmp_path: pytest 内置的每测试临时目录。

    Returns:
        SettingsManagerV2: 绑定临时 ``settings_v2.json`` 的新实例。
    """
    from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2

    settings_file: Path = tmp_path / "test_settings_v2.json"
    manager = SettingsManagerV2(file_path=str(settings_file))
    yield manager


@pytest.fixture
def heartbeat_manager(qapp: Any) -> Any:
    """创建全新的 HeartbeatManager 单例并启动（function scope）。

    遵循项目测试注意事项：teardown 调用 ``stop_all()`` 并重置
    单例。依赖 ``qapp`` 以保证 QObject 处于正确线程。

    Args:
        qapp: 会话级 QApplication（由父 fixture 提供）。

    Returns:
        HeartbeatManager: 已 start 的新实例。
    """
    from freeassetfilter.core.managers.heartbeat_manager import HeartbeatManager

    HeartbeatManager._instance = None
    HeartbeatManager._initialized = False
    hm = HeartbeatManager()
    hm.start()
    yield hm
    hm.stop_all()
    HeartbeatManager._instance = None
    HeartbeatManager._initialized = False


# =============================================================================
# 会话级可用性探测
# =============================================================================
def _probe_bundled_dll(dll_names: List[str]) -> bool:
    """按系统路径 → 捆绑目录的顺序探测一组 DLL 能否被 ctypes 加载。

    Args:
        dll_names: 待探测的 DLL 文件名列表（优先顺序）。

    Returns:
        bool: 任一位置的任一 DLL 可加载则为 True。
    """
    search_dirs: List[Path] = [_PROJECT_ROOT]
    for base in dll_names:
        try:
            ctypes.CDLL(base)
            return True
        except OSError:
            continue
    for search_dir in search_dirs:
        for base in dll_names:
            candidate: Path = search_dir / "freeassetfilter" / "core" / "native" / "bin" / base
            if candidate.is_file():
                try:
                    ctypes.CDLL(str(candidate))
                    return True
                except OSError:
                    continue
    return False


@pytest.fixture(scope="session")
def mpv_available() -> bool:
    """探测 libmpv-2.dll 是否可加载（session scope）。

    复用归档旧逻辑（old-tests-snapshot/tests/conftest.py:480-521）：
    先尝试系统默认加载，再搜索项目内 ``freeassetfilter/core/native/bin``
    下的捆绑 DLL 逐位置尝试。从不抛出异常——任何尝试失败都返回 False。

    Returns:
        bool: libmpv-2.dll 可加载则为 True。
    """
    return _probe_bundled_dll(["libmpv-2.dll", "libmpv.dll"])


@pytest.fixture(scope="session")
def rust_available() -> bool:
    """探测 Rust 原生扩展 DLL 是否可用（session scope）。

    探测 ``native/bin`` 下的 ``thumbnail_generator.dll``，
    用 ctypes 尝试加载以判断可用性。
    用 ctypes 探测，避免导入模块时产生副作用。

    Returns:
        bool: 任一 Rust DLL 可加载即为 True。
    """
    return _probe_bundled_dll(
        ["thumbnail_generator.dll"]
    )


@pytest.fixture(scope="session")
def faf_core_available() -> bool:
    """探测 faf_core 统一原生核心 DLL 是否可用（session scope）。

    探测 ``native/bin`` 下的 ``faf_core.dll``，
    用 ctypes 尝试加载以判断可用性。
    用 ctypes 探测，避免导入模块时产生副作用。

    Returns:
        bool: faf_core.dll 可加载即为 True。
    """
    return _probe_bundled_dll(
        ["faf_core.dll"]
    )


@pytest.fixture(scope="session")
def cpp_lut_available() -> bool:
    """探测 C++ LUT 预览扩展模块是否可用（session scope）。

    经产品实际使用的加载器 ``lut_preview_native`` 探测（发布目录
    ``core/native/bin/lut_preview`` 优先），返回 ``is_cpp_available()`` 结果。
    加载失败/导入异常一律返回 False。

    Returns:
        bool: C++ 扩展可用则为 True，否则 False。
    """
    try:
        from freeassetfilter.core.native.bridges import lut_preview_native

        lut_preview_native.reset()
        return bool(lut_preview_native.is_cpp_available())
    except Exception:
        return False


@pytest.fixture(scope="session")
def py7z_available() -> bool:
    """探测 py7zr / 7z.exe 归档支持是否可用（session scope）。

    优先探测 ``py7zr`` 包是否可导入（``importlib.util.find_spec``）；
    若不可用则回退检查捆绑的 ``core/native/bin/7z/7z.exe`` 是否存在
    （产品归档预览实际依赖 7z.exe）。

    Returns:
        bool: py7zr 可用或 7z.exe 存在则为 True。
    """
    if importlib.util.find_spec("py7zr") is not None:
        return True
    seven_zip: Path = _PROJECT_ROOT / "freeassetfilter" / "core" / "native" / "bin" / "7z" / "7z.exe"
    return seven_zip.is_file()


@pytest.fixture(scope="session")
def soffice_available() -> bool:
    """探测 LibreOffice soffice 可执行文件是否可用（session scope）。

    复用归档旧逻辑（old-tests-snapshot/tests/conftest.py:524-551），通过
    ``freeassetfilter.core._paths.soffice_paths()`` 获取候选目录并在调用点
    try/except 包裹，避免与核心路径模块产生 import 时序耦合。

    Returns:
        bool: 至少一个候选目录存在 soffice 可执行文件则为 True。
    """
    try:
        from freeassetfilter.core._paths import soffice_paths
    except (ImportError, AttributeError):
        return False
    try:
        candidates = soffice_paths()
    except Exception:
        return False
    return any(
        Path(p).is_dir()
        and any((Path(p) / name).is_file() for name in ("soffice.exe", "soffice.com"))
        for p in candidates
    )


@pytest.fixture(scope="session")
def com_available() -> bool:
    """探测 MS Office / WPS COM 组件是否可用（session scope）。

    复用归档旧逻辑（old-tests-snapshot/tests/conftest.py:554-618）：优先
    注册表探测（``HKEY_CLASSES_ROOT`` 下的六个 ProgID，任一存在即可用），
    仅当注册表不可行时回退 win32com Dispatch。从不抛出异常。

    Returns:
        bool: 任一 Office/WPS ProgID 可实例化则为 True。
    """
    prog_ids: List[str] = [
        "Word.Application",
        "Excel.Application",
        "PowerPoint.Application",
        "Kwps.Application",
        "Ket.Application",
        "Kwpp.Application",
    ]
    try:
        if winreg is not None:
            for prog_id in prog_ids:
                try:
                    winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id)
                    return True
                except OSError:
                    continue
    except Exception:
        pass  # 注册表探测失败：转入 COM 回退探测

    try:
        import win32com.client
    except Exception:
        return False
    app = None
    for prog_id in prog_ids:
        try:
            app = win32com.client.Dispatch(prog_id)
            return True
        except Exception:
            continue
        finally:
            if app is not None:
                try:
                    app.Quit()
                except Exception:
                    pass  # 探测清理：退出失败忽略
                app = None
    return False


@pytest.fixture(scope="session")
def ffmpeg_available() -> bool:
    """探测捆绑的 ffmpeg.exe 是否可执行（session scope）。

    镜像 ``mpv_available`` / ``rust_available`` 的探测纪律：检查
    ``freeassetfilter/core/native/bin/ffmpeg.exe`` 存在，且
    ``subprocess.run([path, "-version"], timeout=5)`` 返回码为 0。
    从不抛出异常——任何失败都返回 False。

    Returns:
        bool: ffmpeg.exe 存在且 ``-version`` 返回 0 则为 True。
    """
    ffmpeg_bin: Path = (
        _PROJECT_ROOT / "freeassetfilter" / "core" / "native" / "bin" / "ffmpeg.exe"
    )
    if not ffmpeg_bin.is_file():
        return False
    try:
        completed = subprocess.run(
            [str(ffmpeg_bin), "-version"],
            capture_output=True,
            timeout=5,
        )
        return completed.returncode == 0
    except Exception:
        return False


# =============================================================================
# 数据生成器 fixtures（全部基于 tests.support.data_factories）
# =============================================================================
@pytest.fixture
def sample_image_file(tmp_path: Path) -> str:
    """生成一张多色几何图案的 PNG 图片。

    Args:
        tmp_path: pytest 内置的每测试临时目录。

    Returns:
        str: 生成后的 PNG 文件路径。
    """
    from tests.support.data_factories import make_image

    return make_image(tmp_path / "sample.png", fmt="PNG")


@pytest.fixture
def sample_pdf_file(tmp_path: Path) -> str:
    """生成一个最小可用 PDF 1.4 文件（纯字节构造）。

    Args:
        tmp_path: pytest 内置的每测试临时目录。

    Returns:
        str: 生成后的 PDF 文件路径。
    """
    from tests.support.data_factories import make_pdf

    return make_pdf(tmp_path / "sample.pdf")


@pytest.fixture
def sample_text_file(tmp_path: Path) -> str:
    """生成一个纯文本示例文件。

    Args:
        tmp_path: pytest 内置的每测试临时目录。

    Returns:
        str: 生成后的 .txt 文件路径。
    """
    from tests.support.data_factories import make_text

    return make_text(tmp_path / "sample.txt")


@pytest.fixture
def sample_zip_file(tmp_path: Path) -> str:
    """生成一个包含两个内部文件的 ZIP 压缩包。

    Args:
        tmp_path: pytest 内置的每测试临时目录。

    Returns:
        str: 生成后的 .zip 文件路径。
    """
    from tests.support.data_factories import make_zip

    return make_zip(
        tmp_path / "sample.zip",
        {"hello.txt": "Hello from ZIP archive!", "subdir/data.json": '{"a": 1}'},
    )


@pytest.fixture
def sample_svg_file(tmp_path: Path) -> str:
    """生成一个最小可渲染的 SVG 文件。

    Args:
        tmp_path: pytest 内置的每测试临时目录。

    Returns:
        str: 生成后的 .svg 文件路径。
    """
    from tests.support.data_factories import make_svg

    return make_svg(tmp_path / "sample.svg")


@pytest.fixture
def sample_font_file() -> Optional[str]:
    """从 Windows Fonts 复制一个字体样本到临时目录。

    Returns:
        Optional[str]: 复制后的字体文件路径；系统字体不可用时为 None，
        依赖字体的测试应据此 skip。
    """
    from tests.support.data_factories import make_font_path

    return make_font_path()


@pytest.fixture
def sample_dir(tmp_path: Path) -> str:
    """创建一个含一个嵌套文本文件的临时目录。

    Args:
        tmp_path: pytest 内置的每测试临时目录。

    Returns:
        str: 创建出的目录路径。
    """
    directory: Path = tmp_path / "sample_dir"
    directory.mkdir()
    (directory / "nested.txt").write_text("nested content", encoding="utf-8")
    return str(directory)


@pytest.fixture
def sample_dir_info(tmp_path: Path) -> Dict[str, Any]:
    """构造与产品 FileInfo 兼容的目录信息字典。

    Args:
        tmp_path: pytest 内置的每测试临时目录。

    Returns:
        dict[str, Any]: 目录元信息字典。
    """
    directory: Path = tmp_path / "sample_dir_info"
    directory.mkdir()
    return {
        "name": "sample_dir_info",
        "path": str(directory),
        "is_dir": True,
        "size": 0,
        "modified": "",
        "created": "",
        "suffix": "",
    }


@pytest.fixture
def sample_file_info(tmp_path: Path, request: Any) -> Dict[str, Any]:
    """返回符合标准 file_info 格式的文件信息字典。

    可通过 parametrize 的 extension 参数指定不同后缀（默认 "png"）：

    Usage:
        @pytest.mark.parametrize("sample_file_info", ["jpg", "pdf", "txt"], indirect=True)
        def test_something(sample_file_info):
            assert sample_file_info["extension"] == "jpg"

    Args:
        tmp_path: pytest 内置的每测试临时目录。
        request: pytest 请求对象，``request.param`` 携带扩展名。

    Returns:
        dict[str, Any]: 文件元信息字典。
    """
    from tests.support.data_factories import file_info_dict

    ext: str = getattr(request, "param", "png")
    file_path: Path = tmp_path / f"sample.{ext}"
    file_path.write_bytes(b"dummy content for file info dict")
    info: Dict[str, Any] = file_info_dict(file_path, ext=ext)
    info["path"] = str(file_path)
    return info


@pytest.fixture
def sample_image_data() -> bytes:
    """提供简单的 RGBA 图像数据（PNG 编码字节）用于颜色提取测试。

    Returns:
        bytes: 100x100 红色 RGBA PNG 的字节内容。
    """
    import io

    from PIL import Image

    img = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def temp_file(tmp_path: Path) -> str:
    """提供一个包含文本内容的临时文件路径。

    Args:
        tmp_path: pytest 内置的每测试临时目录。

    Returns:
        str: 临时 .txt 文件路径。
    """
    test_file: Path = tmp_path / "test_file.txt"
    test_file.write_text("test content", encoding="utf-8")
    return str(test_file)


@pytest.fixture
def temp_settings_file(tmp_path: Path) -> str:
    """提供带完整主题颜色结构的临时设置文件路径。

    Args:
        tmp_path: pytest 内置的每测试临时目录。

    Returns:
        str: 已写入测试设置的 .json 文件路径。
    """
    settings_data: Dict[str, Any] = {
        "appearance": {
            "theme": "dark",
            "colors": {
                "accent_color": "#FF0000",
                "base_color": "#f1f3f5",
                "secondary_color": "#333333",
                "normal_color": "#CECECE",
                "auxiliary_color": "#DDDDDD",
                "custom_design_color": "#AABBCC",
            },
        },
        "font": {"size": 12},
    }
    settings_file: Path = tmp_path / "temp_settings.json"
    settings_file.write_text(json.dumps(settings_data), encoding="utf-8")
    return str(settings_file)


@pytest.fixture
def settings_file(tmp_path: Path) -> str:
    """提供一个临时设置文件路径（不预先写入内容）。

    Args:
        tmp_path: pytest 内置的每测试临时目录。

    Returns:
        str: 未创建的 settings.json 路径。
    """
    return str(tmp_path / "settings.json")


# =============================================================================
# 视频样本 fixture
# =============================================================================
@pytest.fixture(scope="session")
def video_sample_paths(tmp_path_factory: Any) -> List[str]:
    """把 ``tests/support/media/`` 的全部视频样本复制到临时目录（session scope）。

    通过 ``tests.support.data_factories.make_video_sample`` 复制全部已提交
    样本（10 个，见 ffmpeg-minimal-rebuild 计划 Todo 5），返回按文件名
    排序的路径列表，保证参数化顺序稳定。

    Args:
        tmp_path_factory: pytest 内置的会话级临时目录工厂。

    Returns:
        list[str]: 排序后的视频样本路径列表。
    """
    from tests.support.data_factories import make_video_sample

    media_dir: Path = _PROJECT_ROOT / "tests" / "support" / "media"
    names: List[str] = sorted(p.name for p in media_dir.iterdir() if p.is_file())
    target_dir: Path = tmp_path_factory.mktemp("video_samples")
    return [make_video_sample(name, target_dir / name) for name in names]


# =============================================================================
# 视觉模式开关（GUI 测试）
# =============================================================================
@pytest.fixture(scope="session")
def visual_mode() -> bool:
    """读取 ``FAF_VISUAL`` 环境变量判断当前是否为视觉/GUI 模式。

    运行器（tests/run_tests.py, todo-5）在 ``gui`` 子命令中会设置
    ``FAF_VISUAL=1`` 并取消 offscreen；gui 测试据此决定是否执行真实
    渲染断言。

    Returns:
        bool: ``FAF_VISUAL`` 为 1/true/yes/on 等真值时返回 True。
    """
    value: str = os.environ.get("FAF_VISUAL", "")
    return value.strip().lower() in ("1", "true", "yes", "on")


# =============================================================================
# 收集阶段钩子：目录级自动超时打标
# =============================================================================
def pytest_collection_modifyitems(config: Any, items: List[Any]) -> None:
    """给未显式标记 timeout 的测试项按目录层级自动打标。

    委托 ``tests.support.timeout_policy.apply_timeout``（todo-3 的单一
    事实源）：显式 marker 优先、自动打标次之、CLI ``--timeout`` 兜底。
    此处保证裸 pytest（不经运行器）也得到一致的超时语义。

    Args:
        config: pytest 配置对象（未直接使用，hook 签名兼容）。
        items: 收集阶段产出的测试项序列，会被就地修改。
    """
    try:
        from tests.support.timeout_policy import apply_timeout

        apply_timeout(items)
    except Exception:
        # 探测/打标失败绝不阻断收集。
        pass