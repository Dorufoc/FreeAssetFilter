# -*- coding: utf-8 -*-
# targets: freeassetfilter.components.unified_previewer, freeassetfilter.components.file_selector, freeassetfilter.components.file_staging_pool
"""integration 批 1（W6/todo-24）：选择器 → 预览器 → 暂存池三组件联动测试。

模拟生产联动接线（main.py:1511/1515）：

* ``file_selector.file_selected.connect(unified_previewer.set_file)``；
* 暂存池 ``add_file`` 去重 / 同步 / 信号发射；
* ``copy_files`` 直接导出（内部非 daemon ``threading.Thread``），
  ``export_finished(success, error_count, errors)`` 信号收尾。

QA 验收点：

1. 三组件联动后：file_selected 驱动 preview_started（预览器收到信息）；
2. 暂存池 ``pool_model.rowCount()`` 递增（文件已入池）；
3. 导出到正常目录成功（``export_finished`` 收到 success>=1）；
4. **导出到只读目录 / 模拟权限错误返回可处理错误而非崩溃**（monkeypatch
   ``shutil.copy2`` 抛 ``PermissionError``，errors 非空但不炸进程）。

测试纪律（计划 todo-24）：

* 只用 .txt 条目（非目录、非媒体），避免文件夹大小计算线程与缩略图
  线程；不触碰 modal 对话框路径（clear_all / _check_space_and_proceed）；
* 除 copy_files 自己启动的导出线程外无其他线程，等待一律有界
  （wait_for_signal / process_qt_events）；
* ``StagingPoolService._instance`` 在 fixture 中显式重置，防止跨测试
  污染；`backup_file` 重定向 tmp。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

import pytest
from PySide6.QtWidgets import QApplication

from freeassetfilter.services.staging_pool_service import StagingPoolService

from tests.support.data_factories import file_info_dict, make_text
from tests.support.qt_helpers import process_qt_events, safe_teardown, wait_for_signal

pytestmark = pytest.mark.integration


# =============================================================================
# helper
# =============================================================================
def _make_txt_info(path: str) -> Dict[str, Any]:
    """构造与 product FileInfo 兼容的 .txt 条目（含 previewer/pool 所需键）。

    Args:
        path: .txt 文件的绝对路径。

    Returns:
        Dict[str, Any]: 含 path/name/type/extension/size/modified/is_dir/
            suffix/display_name 的条目。
    """
    info: Dict[str, Any] = file_info_dict(path, ext="txt")
    info["is_dir"] = False
    info["suffix"] = ".txt"
    info["display_name"] = os.path.basename(path)
    return info


@pytest.fixture
def selector(qapp: QApplication, settings_manager: Any) -> Any:
    """提供 CustomFileSelector 实例（function scope）。

    Args:
        qapp: 会话级 QApplication。
        settings_manager: 临时设置管理器。

    Returns:
        Any: 可用的 CustomFileSelector 实例。
    """
    from freeassetfilter.components.file_selector import CustomFileSelector

    sel: Any = CustomFileSelector(
        global_font=getattr(qapp, "global_font", None),
        dpi_scale=getattr(qapp, "dpi_scale_factor", 1.0),
        settings_manager=settings_manager,
    )
    yield sel
    safe_teardown(sel)


@pytest.fixture
def previewer(qapp: QApplication, settings_manager: Any) -> Any:
    """提供 UnifiedPreviewer 实例（function scope）。

    Args:
        qapp: 会话级 QApplication。
        settings_manager: 临时设置管理器。

    Returns:
        Any: 可用的 UnifiedPreviewer 实例（拦截真实预览切换，只验证信号）。
    """
    from freeassetfilter.components.unified_previewer import UnifiedPreviewer

    up: Any = UnifiedPreviewer(
        settings_manager=settings_manager,
        dpi_scale=getattr(qapp, "dpi_scale_factor", 1.0),
        global_font=getattr(qapp, "global_font", None),
    )
    # 拦截分派，避免真实预览组件初始化（保持测试在内存态）。
    up._start_preview_switch = lambda file_path, preview_type: None  # type: ignore[method-assign]
    yield up
    safe_teardown(up)


@pytest.fixture
def pool(qapp: QApplication, settings_manager: Any, tmp_path: Path) -> Any:
    """提供 FileStagingPool 实例，backup 重定向 tmp（function scope）。

    Args:
        qapp: 会话级 QApplication。
        settings_manager: 临时设置管理器。
        tmp_path: pytest 每测试临时目录。

    Returns:
        Any: 可用的 FileStagingPool 实例。
    """
    StagingPoolService._instance = None
    from freeassetfilter.components.file_staging_pool import FileStagingPool

    p: Any = FileStagingPool(
        settings_manager=settings_manager,
        dpi_scale=getattr(qapp, "dpi_scale_factor", 1.0),
        global_font=getattr(qapp, "global_font", None),
    )
    p.backup_file = str(tmp_path / "pool_backup.json")
    yield p

    try:
        p.cleanup()
    except Exception:
        pass
    safe_teardown(p)
    StagingPoolService._instance = None


# =============================================================================
# 三组件联动
# =============================================================================
class TestSelectorPreviewPoolFlow:
    """选择器 → 预览器 → 暂存池 完整联动。"""

    def test_flow_select_preview_add_to_pool(
        self,
        qapp: QApplication,
        tmp_path: Path,
        selector: Any,
        previewer: Any,
        pool: Any,
    ) -> None:
        """file_selected → previewer.set_file 联动；add_file → rowCount 递增。

        校验生产接线语义（main.py:1511/1515 的连接方式）在组件间成立，
        且暂存池在加入后行数增加（QA 验收点 1/2）。
        """
        txt_path: str = make_text(tmp_path / "note.txt")
        finfo: Dict[str, Any] = _make_txt_info(txt_path)

        # 生产接线（main.py:1511 的等价连接）。
        selector.file_selected.connect(previewer.set_file)

        preview_started: List[bool] = []
        previewer.preview_started.connect(lambda *_: preview_started.append(True))

        # 模拟用户点击文件（信号链路，不经真实模态 / 线程加载）。
        selector.file_selected.emit(finfo)
        process_qt_events(qapp, ms=50)

        assert preview_started, "file_selected 未驱动 preview_started 发射"
        assert previewer.current_file_info == finfo, "预览器未收到文件信息"

        # 暂存池加入（生产 add_file 路径）。
        pool.add_file(finfo)
        process_qt_events(qapp, ms=50)

        assert pool.pool_model.rowCount() == 1, "暂存池应恰好有 1 项"
        assert pool.pool_model.has_path(os.path.normpath(txt_path)), "暂存池未收录路径"

    def test_flow_duplicate_add_is_idempotent(
        self,
        qapp: QApplication,
        tmp_path: Path,
        selector: Any,
        previewer: Any,
        pool: Any,
    ) -> None:
        """重复加入同一文件不应增加行数（去重语义）。

        Args:
            qapp: 会话级 QApplication。
            tmp_path: pytest 每测试临时目录。
            selector: 文件选择器。
            previewer: 预缆器。
            pool: 暂存池。
        """
        txt_path: str = make_text(tmp_path / "dup.txt")
        finfo: Dict[str, Any] = _make_txt_info(txt_path)

        pool.add_file(finfo)
        process_qt_events(qapp, ms=30)
        pool.add_file(finfo)
        process_qt_events(qapp, ms=30)

        assert pool.pool_model.rowCount() == 1, "重复 add_file 不应增加行数"


# =============================================================================
# 导出（copy_files → export_finished）
# =============================================================================
class _NoopMessageBox:
    """空壳 CustomMessageBox：导出完成槽的模态框在测试中必须被抑制。

    生产 ``on_export_finished``（file_staging_pool.py:1113-1125）会
    ``result_msg.exec()`` 阻塞；测试进程内绝不能出现真实模态弹窗
    （计划约束：禁止真实弹窗）。
    """

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.buttonClicked = _NoopSignal()

    def set_title(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set_text(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set_buttons(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def close(self) -> None:
        return None

    def exec(self) -> None:  # noqa: A003
        return None


class _NoopSignal:
    """可被 ``.connect`` 的空信号，供 _NoopMessageBox.buttonClicked 使用。"""

    def connect(self, *_args: Any, **_kwargs: Any) -> None:
        return None


@pytest.mark.filterwarnings("ignore:.*Failed to disconnect.*:RuntimeWarning")
class TestPoolExportFlow:
    """导出到正常 / 只读目录的错误处理路径。

    直接调用 ``copy_files`` 不会经过导出对话框路径，因此
    ``on_export_finished`` 内部对 ``update_progress`` 的断开（L1104）
    会触发一次无害 RuntimeWarning——用 filterwarnings 抑制，保持验收输出干净。
    """

    @pytest.fixture(autouse=True)
    def _silence_export_modals(self, monkeypatch: Any) -> None:
        """把 file_staging_pool 模块内的 CustomMessageBox 换成空壳。

        Args:
            monkeypatch: pytest monkeypatch fixture。
        """
        import freeassetfilter.components.file_staging_pool as pool_mod

        monkeypatch.setattr(pool_mod, "CustomMessageBox", _NoopMessageBox)

    def test_copy_files_success_signal(
        self, qapp: QApplication, tmp_path: Path, pool: Any
    ) -> None:
        """copy_files 到正常目录应成功且发射 export_finished(success>=1)。"""
        src_area: Path = tmp_path / "src"
        src_area.mkdir()
        txt_path: str = make_text(src_area / "export_me.txt")
        finfo: Dict[str, Any] = _make_txt_info(txt_path)

        pool.add_file(finfo)
        process_qt_events(qapp, ms=30)

        target: Path = tmp_path / "out"
        target.mkdir()
        finished: List[Any] = []
        export_signal = pool.export_finished
        export_signal.connect(lambda *args: finished.append(args))

        pool.copy_files([finfo], str(target))
        assert wait_for_signal(export_signal, timeout_ms=5000), "export_finished 未发射"

        success, error_count, errors = finished[0]
        assert success >= 1, "应至少成功导出 1 个文件"
        assert error_count == 0 and not errors
        assert (target / "export_me.txt").is_file(), "目标目录应出现导出的文件"

    def test_copy_files_readonly_dir_error_not_crash(
        self, qapp: QApplication, tmp_path: Path, pool: Any, monkeypatch: Any
    ) -> None:
        """导出到无写权限的目标应返回可处理错误而非崩溃（QA 验收点 4）。

        用 monkeypatch 模拟 PermissionError（Windows 上只读目录在测试
        进程中仍可能可写）；断言 errors 非空、信号正常收尾、进程未崩。

        Args:
            qapp: 会话级 QApplication。
            tmp_path: pytest 每测试临时目录。
            pool: 暂存池。
            monkeypatch: pytest monkeypatch fixture。
        """
        import shutil

        src_area: Path = tmp_path / "src"
        src_area.mkdir()
        txt_path: str = make_text(src_area / "blocked.txt")
        finfo: Dict[str, Any] = _make_txt_info(txt_path)

        pool.add_file(finfo)
        process_qt_events(qapp, ms=30)

        target: Path = tmp_path / "out_ro"
        target.mkdir()

        def _deny_copy(*_args: Any, **_kwargs: Any) -> None:
            raise PermissionError("模拟目标目录无写权限")

        monkeypatch.setattr(shutil, "copy2", _deny_copy)

        finished: List[Any] = []
        export_signal = pool.export_finished
        export_signal.connect(lambda *args: finished.append(args))

        pool.copy_files([finfo], str(target))
        assert wait_for_signal(export_signal, timeout_ms=5000), "export_finished 未发射"

        success, error_count, errors = finished[0]
        assert success == 0, "不应有任何成功项"
        assert error_count == 1, "应恰好有 1 个错误"
        assert errors and "blocked.txt" in errors[0], "errors 应含失败文件信息"


# =============================================================================
# 选择器信号（独立于流的 selector 行为）
# =============================================================================
class TestSelectorSignals:
    """CustomFileSelector 文件选择信号与预览取消信号。"""

    def test_file_selected_signal_payload(
        self, qapp: QApplication, tmp_path: Path, selector: Any
    ) -> None:
        """file_selected 发射时应携带完整 file_info 字典。"""
        txt_path: str = make_text(tmp_path / "payload.txt")
        captured: List[Dict[str, Any]] = []
        selector.file_selected.connect(captured.append)

        info: Dict[str, Any] = _make_txt_info(txt_path)
        selector.file_selected.emit(info)
        process_qt_events(qapp, ms=30)

        assert captured, "file_selected 未发射"
        assert captured[0]["path"] == txt_path
        assert captured[0]["name"] == "payload.txt"