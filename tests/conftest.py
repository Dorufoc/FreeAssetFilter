# -*- coding: utf-8 -*-
"""集成测试配置与共享 fixtures（tests/comprehensive-refactor 计划 todo-4 重写）。

本文件是 todo 7-29 各测试套件的容器 fixture 来源，遵循 AGENTS.md 的
单例重置纪律与跨线程模式。要点：

* ``qapp``（session）：全局唯一 QApplication，附带 ``dpi_scale_factor`` /
  ``global_font`` 与应用级别的 ``settings_manager`` / ``theme_manager`` 属性，
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
import winreg
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

# 项目根目录加入 sys.path，保证裸 `pytest`（非 -m）也能解析 freeassetfilter/。
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(_PROJECT_ROOT))


# =============================================================================
# 会话级 QApplication
# =============================================================================
@pytest.fixture(scope="session")
def qapp() -> Any:
    """提供全局唯一的 QApplication 实例（session scope）。

    镜像归档旧实现 old-tests-snapshot/tests/conftest.py:16-34：先取现有
    实例（避免重复创建），再挂载 ``dpi_scale_factor=1.0`` 与
    ``global_font=QFont("Microsoft YaHei", 9)``，最后补充
    ``settings_manager`` / ``theme_manager`` 属性，防止组件初始化时因
    缺少这两个应用级实例而抛 AttributeError。

    Returns:
        QApplication: 全局应用实例。
    """
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from freeassetfilter.core.managers.theme_manager import ThemeManager
    from freeassetfilter.core.managers.settings_manager import SettingsManager

    app = QApplication.instance()
    if app is None:
        app = QApplication(os.sys.argv)
    app.dpi_scale_factor = 1.0
    app.global_font = QFont("Microsoft YaHei", 9)
    if not hasattr(app, "settings_manager"):
        app.settings_manager = SettingsManager()
    if not hasattr(app, "theme_manager"):
        app.theme_manager = ThemeManager()
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


# =============================================================================
# 单例重置（autouse）
# =============================================================================
def _reset_all_singletons() -> None:
    """归零全部已知单例的内部状态（供 reset_singletons 前后两阶段复用）。

    重置清单（V3 事实审计后的准确版本）：

    * ``SettingsManager``：类级 ``_instance`` / ``_initialized``
      （core/managers/settings_manager.py:24-26）。
    * ``HeartbeatManager``：类级 ``_instance`` / ``_initialized``
      （core/managers/heartbeat_manager.py:164-166）。
    * ``ThumbnailManager``：类级 ``_instance`` / ``_initialized``
      （core/managers/thumbnail_manager.py:219-220），**另有**模块级全局
      ``_thumbnail_manager``（:2466，由 ``get_thumbnail_manager()`` 缓存），
      类属性重置覆盖不到它，需单独归零。
    * ``MPVManager``：类级 ``_instance``（core/managers/mpv_manager.py:170）。
      该类**没有**类级 ``_initialized``（仅实例级，L179/L190/L229），因此
      用 ``hasattr`` 守卫跳过，避免 AttributeError。
    * ``AppLogger``：类级 ``_instance`` / ``_initialized``
      （utils/app_logger.py:835-836）。
    * ``AsyncIconLoader``：模块级 ``_instance``
      （utils/async_icon_loader.py:100）。

    **明确不做**的：

    * 不重置 ``core/managers/theme_manager.py`` 的 ``ThemeManager``——V3
      审计证实该模块**不是单例**（无 ``_instance``/``_initialized``）；
      带单例的是 ``ui/theme/theme_manager.py:66-67``，不在本清单范围。
    * 不引用 ``core/managers/update_manager.py`` 的 ``UpdateManager``——该
      模块是纯函数模块（``check_for_updates``/``compare_version_tuples`` +
      ``UpdateError``/``UpdateCancelled``），不存在该类，赋值将 NameError。

    Returns:
        None。
    """
    from freeassetfilter.core.managers.heartbeat_manager import HeartbeatManager
    from freeassetfilter.core.managers.mpv_manager import MPVManager
    from freeassetfilter.core.managers.settings_manager import SettingsManager
    from freeassetfilter.core.managers.thumbnail_manager import ThumbnailManager
    from freeassetfilter.utils.app_logger import AppLogger
    from freeassetfilter.utils.async_icon_loader import AsyncIconLoader

    import freeassetfilter.core.managers.thumbnail_manager as _thumbnail_module

    # 类级 _instance 一律归零；_initialized 仅当类上真实存在该属性时才归零。
    for _singleton in (
        SettingsManager,
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


@pytest.fixture(autouse=True, scope="function")
def reset_singletons() -> None:
    """在每个测试函数前后重置全局单例状态，保证测试隔离性。

    setup 阶段归零（防止上一测试残留污染），teardown 阶段再次归零
    （确保断言"测试结束后 ``_instance is None``"能够成立，且下一测试的
    setup 归零是幂等的）。重置清单见 :func:`_reset_all_singletons` 的
    docstring——包括 SettingsManager/HeartbeatManager/ThumbnailManager/
    MPVManager 四大管理器 + thumbnail 模块级全局 + AppLogger +
    AsyncIconLoader。

    Returns:
        None。
    """
    _reset_all_singletons()
    yield
    _reset_all_singletons()


@pytest.fixture
def settings_manager(tmp_path: Path) -> Any:
    """提供使用临时设置文件的 SettingsManager 实例（function scope）。

    Args:
        tmp_path: pytest 内置的每测试临时目录。

    Returns:
        SettingsManager: 绑定临时 ``settings.json`` 的新实例。
    """
    from freeassetfilter.core.managers.settings_manager import SettingsManager

    settings_file: Path = tmp_path / "test_settings.json"
    SettingsManager._instance = None
    SettingsManager._initialized = False
    manager = SettingsManager(settings_file=str(settings_file))
    yield manager
    SettingsManager._instance = None
    SettingsManager._initialized = False


@pytest.fixture
def heartbeat_manager(qapp: Any) -> Any:
    """创建全新的 HeartbeatManager 单例并启动（function scope）。

    遵循 AGENTS.md 测试注意事项：teardown 调用 ``stop_all()`` 并重置
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

    检查 ``native/bin`` 下的 ``rust_color_extractor_native.dll`` 与
    ``thumbnail_generator.dll``，任一个可用 ctypes 加载即判定可用。
    走 ctypes 探测，避免导入整桥模块带来的重依赖副作用。

    Returns:
        bool: 任一 Rust DLL 可加载则为 True。
    """
    return _probe_bundled_dll(
        ["rust_color_extractor_native.dll", "thumbnail_generator.dll"]
    )


@pytest.fixture(scope="session")
def cpp_lut_available() -> bool:
    """探测 C++ LUT 预览扩展模块是否可用（session scope）。

    尝试导入 ``freeassetfilter.core.native.src.cpp_lut_preview`` 并调用
    其 ``_try_import_cpp_module()`` 触发底层 .pyd 加载，再读
    ``is_cpp_available()`` 结果。加载失败/导入异常一律返回 False。

    Returns:
        bool: C++ 扩展可用则为 True，否则 False。
    """
    try:
        from freeassetfilter.core.native.src.cpp_lut_preview import (
            _try_import_cpp_module,
            is_cpp_available,
        )

        _try_import_cpp_module()
        return bool(is_cpp_available())
    except Exception:
        return False


@pytest.fixture(scope="session")
def py7z_available() -> bool:
    """探测 py7zr / 7z.exe 归档支持是否可用（session scope）。

    优先探测 ``py7zr`` 包是否可导入（``importlib.util.find_spec``）；
    若不可用则回退检查捆绑的 ``core/native/bin/7z/7z.exe`` 是否存在
    （产品归档预览实际依赖 7z.exe，见 AGENTS.md 已知坑点）。

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
        for prog_id in prog_ids:
            try:
                winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id)
                return True
            except OSError:
                continue
    except Exception:
        pass

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
                    pass
                app = None
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
# 性能基准数据集
# =============================================================================
@pytest.fixture(scope="session")
def benchmark_dataset(tmp_path_factory: Any) -> List[str]:
    """生成一个缩小版基准数据集（20 张 PNG 图片，session scope）。

    Args:
        tmp_path_factory: pytest 内置的会话级临时目录工厂。

    Returns:
        list[str]: 20 张已生成 PNG 图片的路径列表。
    """
    from tests.support.data_factories import make_image

    base_dir: Path = tmp_path_factory.mktemp("benchmark_dataset")
    paths: List[str] = []
    for i in range(20):
        paths.append(make_image(base_dir / f"bench_{i:03d}.png", fmt="PNG"))
    return paths


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