"""``sopeek._paths`` 的路径解析契约。

这些断言是重构的“防回退锁”：目录层级再变（例如再包一层），只要这些
路径仍成立，所有调用点就都还活着。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sopeek import _paths


pytestmark = pytest.mark.unit


def test_mac_data_root_uses_application_support(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(_paths.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert _paths._default_app_data_root() == tmp_path / "Library" / "Application Support" / "Sopeek" / "data"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS instance lock")
def test_mac_data_directory_lock_releases_after_close() -> None:
    from sopeek.app.instance_guard import _acquire_single_instance, _release_mutex

    lock = _acquire_single_instance()
    try:
        with pytest.raises(SystemExit) as duplicate:
            _acquire_single_instance()
        assert duplicate.value.code == 0
    finally:
        _release_mutex(lock)
    _release_mutex(_acquire_single_instance())


def test_package_dir_is_importable_package_root() -> None:
    """``package_dir()`` 必须就是 ``sopeek`` 包目录本身。"""
    assert _paths.package_dir().name == "sopeek"
    assert (_paths.package_dir() / "__init__.py").is_file()


def test_src_layout_relationship() -> None:
    """``src/`` 布局：``src_dir()`` 是包目录的父级，``repo_root()`` 再上一级。"""
    assert _paths.src_dir() == _paths.package_dir().parent
    assert _paths.src_dir().name == "src"
    assert _paths.repo_root() == _paths.src_dir().parent


def test_repo_root_contains_project_markers() -> None:
    """仓库根应包含版本文件与原生源码目录（用来判定推导没跑偏）。"""
    root = _paths.repo_root()
    assert (_paths.version_file()).is_file()
    assert _paths.version_file() == root / "SPKVERSION"
    assert (_paths.native_source_root()).is_dir()


def test_resources_layout() -> None:
    """随包资源四个子目录必须真实存在。"""
    for directory in (
        _paths.resources_dir(),
        _paths.icons_dir(),
        _paths.syntax_dir(),
        _paths.shaders_dir(),
        _paths.docs_dir(),
    ):
        assert directory.is_dir(), directory
        assert directory.parent in (_paths.resources_dir(), _paths.package_dir())


def test_native_runtime_binaries_present() -> None:
    """随包运行时目录必须含核心 DLL（缺失说明资源被误移出包）。"""
    bin_dir = _paths.native_bin_dir()
    assert bin_dir.is_dir()
    for name in ("libmpv-2.dll", "spk_core.dll", "spk_updater.exe"):
        assert (bin_dir / name).is_file(), name
    assert _paths.archive_7z_dir() == bin_dir / "7z"


def test_launcher_dir_points_into_packaging() -> None:
    """启动器目录随脚本迁移到了 ``packaging/launcher/``。"""
    launcher = _paths.launcher_dir()
    assert launcher.name == "launcher"
    assert launcher.parent.name == "packaging"
    assert launcher.parent.parent == _paths.repo_root()


def test_app_data_path_honours_env_override(
    _isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``SPK_DATA_DIR`` 优先且每次重新读取（不受进程内缓存影响）。"""
    assert _paths.get_app_data_path() == _isolated_data_dir

    custom = _isolated_data_dir / "custom"
    monkeypatch.setenv("SPK_DATA_DIR", str(custom))
    assert _paths.get_app_data_path() == custom
    assert custom.is_dir()


def test_soffice_paths_never_raises_and_is_deduplicated() -> None:
    """LibreOffice 探测只做路径判断：不抛异常、不重复、只返回存在的目录。"""
    paths = _paths.soffice_paths()
    assert isinstance(paths, list)
    assert len(paths) == len(set(paths))
    for path in paths:
        assert path.is_dir()

def test_mac_soffice_in_user_applications_or_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from sopeek.services.office_converter import _resolve_soffice_binary

    if sys.platform != "darwin":
        pytest.skip("macOS application directories")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    bundle_bin = tmp_path / "Applications" / "LibreOffice.app" / "Contents" / "MacOS"
    bundle_bin.mkdir(parents=True)
    path_bin = tmp_path / "path"
    path_bin.mkdir()
    for directory in (bundle_bin, path_bin):
        command = directory / "soffice"
        command.touch(mode=0o755)
    monkeypatch.setenv("PATH", str(path_bin))
    candidates = _paths.soffice_paths()
    assert bundle_bin in candidates and path_bin in candidates
    assert candidates.index(bundle_bin) < candidates.index(path_bin)
    # Keep system-wide installations on the test host outside this fixture.
    monkeypatch.setattr(_paths, "soffice_paths", lambda: [bundle_bin, path_bin])
    assert _resolve_soffice_binary() == bundle_bin / "soffice"
    (bundle_bin / "soffice").unlink()
    assert _resolve_soffice_binary() == path_bin / "soffice"
    (path_bin / "soffice").chmod(0o644)
    assert _resolve_soffice_binary() is None
