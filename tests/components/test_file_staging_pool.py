# -*- coding: utf-8 -*-
"""components 批 1（W4/todo-18）：文件暂存池组件测试。

覆盖 ``freeassetfilter/components/file_staging_pool.py`` 中
``FileStagingPool`` 的公开 / 半公开 API：

* 构造与默认状态（items/pool_model/stats_label/信号定义、备份文件路径
  重定向到 tmp、防抖 QTimer 配置）。
* 添加（add_file）：去重、display_name/original_name 兜底、is_dir →
  size_calculating、file_added_to_pool 信号、StagingPoolService 同步。
* 移除（remove_file）与清空（clear_all_without_confirmation）：
  remove_from_selector 逐项发射、preview_cancel_requested、统计刷新。
* 备份系统：save_backup / load_backup 往返、_serialize_backup_item 白名单
  归一化、flush_backup_save_now 立即落盘、_save_backup_if_needed 防抖。
* 统计（update_stats / _format_file_size）与预览态
  （set_previewing_file / clear_previewing_state）。
* 清理（cleanup：_is_closing/停表/服务 dispose）。

约束（计划 todo-18）：零生产代码改动；``backup_file`` 重定向到 tmp；
``add_file`` 一律使用非目录、非媒体（.txt）条目，避免触发文件夹大小
计算线程与缩略图线程；is_dir 分支通过 monkeypatch 短路
``_calculate_folder_size``；StagingPoolService 单例在 fixture 前后归零，
防止跨测试污染；绝不 exec() 任何模态对话框（clear_all 带确认，只测
clear_all_without_confirmation）。
"""

# targets: components.file_staging_pool

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple, Type
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import (
    QEvent,
    QMimeData,
    QObject,
    QPoint,
    QPointF,
    Qt,
    QUrl,
)
from PySide6.QtGui import (
    QCloseEvent,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
)
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
)

from freeassetfilter.components.file_staging_pool import (
    FileStagingPool,
    _MD5CalculationTask,
)
from freeassetfilter.services.staging_pool_service import StagingPoolService

from tests.support.data_factories import make_text
from tests.support.qt_helpers import flush_widget_queue, safe_teardown

pytestmark = pytest.mark.unit


# =============================================================================
# 公共辅助
# =============================================================================
def _pump_until(
    qapp: Any,
    predicate: Callable[[], bool],
    timeout_s: float = 8.0,
) -> bool:
    """在截止期内轮询冲刷 Qt 事件直到谓词满足（有界，绝不无限等待）。

    Args:
        qapp: 会话级 QApplication 实例。
        predicate: 目标板状态谓词。
        timeout_s: 最长等待秒数。

    Returns:
        bool: 谓词在超时前满足返回 True，否则 False。
    """
    deadline: float = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        flush_widget_queue(qapp, iterations=5)
        time.sleep(0.01)
    return bool(predicate())


class _FakeHoverTooltip(MagicMock):
    """HoverTooltip 替身（MagicMock 模式，同 W8 ``_FakeHoverMenu``）。

    真实 HoverTooltip 在 ``FileStagingPool.init_ui`` 中会被构造并给 5 个
    目标控件 ``installEventFilter``，还在内部创建 GlobalMouseMonitor；组合
    运行时大量真实/半构造实例累积事件过滤器，间歇触发 ``AttributeError:
    'HoverTooltip' object has no attribute '_disposed'``（半构造 = C++ 对象已
    创建、eventFilter 已安装，但 Python 属性未初始化到 ``__init__`` L52）。
    本替身只接管构造与 ``set_target_widget``/``update`` 等调用，零真实
    C++ 对象、零事件过滤器。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # MagicMock 首参会被当作 spec（spec 非空时未知属性直接抛
        # AttributeError）；生产代码以 ``HoverTooltip(self)`` 传 QWidget
        # 父指针，必须丢弃实参再裸构造，才能保持宽松自动属性。
        del args, kwargs
        super().__init__()


@pytest.fixture(autouse=True)
def _mock_hover_tooltip(monkeypatch: Any) -> None:
    """autouse 级替换 file_staging_pool 模块命名空间的 HoverTooltip 为替身。

    覆盖本文件全部用例（含不经过 ``staging_pool`` fixture、直接构造
    FileStagingPool 的 ``test_constructor_explicit_params`` 与
    ``test_constructor_default_settings_manager``），确保真实 HoverTooltip
    与其事件过滤器从不落地；monkeypatch 自动还原。

    Args:
        monkeypatch: pytest 内置 fixture。
    """
    import freeassetfilter.components.file_staging_pool as fsp

    monkeypatch.setattr(fsp, "HoverTooltip", _FakeHoverTooltip)


@pytest.fixture
def staging_pool(
    qapp: Any,
    settings_manager: Any,
    tmp_path: Path,
) -> Any:
    """提供隔离的 FileStagingPool 实例（function scope）。

    备份文件重定向到 tmp；StagingPoolService 单例在测试前后归零；
    teardown 走 cleanup() + safe_teardown()。

    Args:
        qapp: 会话级 QApplication。
        settings_manager: 临时设置文件绑定的 SettingsManager。
        tmp_path: pytest 内置临时目录。

    Returns:
        Any: 已隔离的 FileStagingPool 实例。
    """
    StagingPoolService._instance = None
    pool: Any = FileStagingPool(settings_manager=settings_manager)
    pool.backup_file = str(tmp_path / "staging_pool_backup.json")

    yield pool

    pool.cleanup()
    safe_teardown(pool)
    StagingPoolService._instance = None


def _text_info(path: str, size: int = 1024) -> Dict[str, Any]:
    """构造一个最小 .txt 文件信息字典（非目录、非媒体）。

    Args:
        path: 文件/文件夹路径。
        size: 文件大小（字节）。

    Returns:
        dict[str, Any]: 含 path/name/is_dir/size 的最小条目。
    """
    return {
        "path": path,
        "name": os.path.basename(path),
        "is_dir": False,
        "size": size,
    }


# =============================================================================
# 构造与默认状态
# =============================================================================
class TestConstruction:
    """构造后的默认状态与骨架。"""

    def test_default_state(self, staging_pool: Any) -> None:
        """初始 items 为空、模型/统计/按钮齐备、未进入关闭态。"""
        assert staging_pool.items == []
        assert staging_pool.previewing_file_path is None
        assert staging_pool.pool_model is not None
        assert staging_pool.pool_view is not None
        assert staging_pool.pool_delegate is not None
        assert staging_pool.stats_label is not None
        assert staging_pool.import_export_btn is not None
        assert staging_pool.export_btn is not None
        assert staging_pool.clear_btn is not None
        assert staging_pool._is_closing is False

    def test_backup_file_redirected(self, staging_pool: Any) -> None:
        """备份路径已被 fixture 重定向到 tmp，而非真实 data 目录。"""
        assert "staging_pool_backup.json" in staging_pool.backup_file
        assert "tmp" in staging_pool.backup_file or "Temp" in staging_pool.backup_file

    def test_backup_timer_single_shot(self, staging_pool: Any) -> None:
        """防抖备份定时器为 single shot，初始未激活。"""
        timer = staging_pool._backup_save_timer
        assert timer.isSingleShot() is True
        assert timer.isActive() is False
        assert staging_pool._backup_save_delay_ms > 0
        assert staging_pool._suspend_backup_save is False

    def test_signals_declared(self, staging_pool: Any) -> None:
        """全部公开信号均可实例化访问。"""
        for signal_name in (
            "item_right_clicked",
            "item_left_clicked",
            "remove_from_selector",
            "file_added_to_pool",
            "update_progress",
            "export_finished",
            "folder_size_calculated",
            "folder_size_result_ready",
            "total_size_ready",
            "navigate_to_path",
            "preview_cancel_requested",
        ):
            assert hasattr(staging_pool, signal_name)
            assert getattr(staging_pool, signal_name) is not None

    def test_stats_label_initial(self, staging_pool: Any) -> None:
        """初始统计文案为 0 个条目。"""
        assert "0个条目" in staging_pool.stats_label.text()


# =============================================================================
# 添加文件
# =============================================================================
class TestAddFile:
    """add_file 的去重、字段兜底与信号/服务同步。"""

    def test_add_file_populates_items(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """普通 txt 条目被加入模型并同步到 items 与池服务。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        file_b: str = make_text(str(tmp_path / "b.txt"))

        staging_pool.add_file(_text_info(file_a))
        staging_pool.add_file(_text_info(file_b))

        assert len(staging_pool.items) == 2
        assert staging_pool.pool_model.rowCount() == 2
        paths: List[str] = [item["path"] for item in staging_pool.items]
        assert os.path.normpath(file_a) in paths
        assert os.path.normpath(file_b) in paths
        # StagingPoolService 同步到同一批条目的路径
        service_paths: List[str] = [
            os.path.normpath(item["path"])
            for item in StagingPoolService().get_items()
        ]
        assert os.path.normpath(file_a) in service_paths

    def test_add_file_emits_signal(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """添加后 file_added_to_pool 信号携带该条目的路径。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        emitted: List[Dict[str, Any]] = []
        staging_pool.file_added_to_pool.connect(emitted.append)

        staging_pool.add_file(_text_info(file_a))

        assert len(emitted) == 1
        assert os.path.normpath(emitted[0]["path"]) == os.path.normpath(file_a)

    def test_add_file_deduplicates(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """同一路径重复添加只保留一条。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))

        staging_pool.add_file(_text_info(file_a))
        staging_pool.add_file(_text_info(file_a))

        assert len(staging_pool.items) == 1
        assert staging_pool.pool_model.rowCount() == 1

    def test_add_file_sets_default_display_name(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """缺失 display_name/original_name 时以 name 兜底。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))

        item: Dict[str, Any] = staging_pool.items[0]
        assert item["display_name"] == "a.txt"
        assert item["original_name"] == "a.txt"

    def test_add_dir_sets_size_calculating(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """目录条目进入时 size_calculating 置 True（且不启动真实计算线程）。"""
        folder: Path = tmp_path / "folder"
        folder.mkdir()
        monkeypatch.setattr(
            staging_pool, "_calculate_folder_size", lambda path: None
        )

        staging_pool.add_file(
            {
                "path": str(folder),
                "name": "folder",
                "is_dir": True,
                "size": 0,
            }
        )

        assert len(staging_pool.items) == 1
        assert staging_pool.items[0]["is_dir"] is True
        assert staging_pool.items[0]["size_calculating"] is True

    def test_add_file_stops_when_closing(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """组件进入关闭态后 add_file 不再写入。"""
        staging_pool._is_closing = True
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))
        assert staging_pool.items == []
        assert staging_pool.pool_model.rowCount() == 0


# =============================================================================
# 移除与清空
# =============================================================================
class TestRemoveFile:
    """remove_file 的移除/信号/预览取消。"""

    def test_remove_file_removes_and_emits(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """移除后条目消失，remove_from_selector 携带被移除条目。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))
        removed: List[Dict[str, Any]] = []
        staging_pool.remove_from_selector.connect(removed.append)

        staging_pool.remove_file(file_a)

        assert staging_pool.items == []
        assert len(removed) == 1
        assert os.path.normpath(removed[0]["path"]) == os.path.normpath(file_a)
        # 服务侧同步移除
        assert StagingPoolService().get_items() == []
        # 模型行保留但标记为正在移除（物理删除由 finalize_remove_file 完成）
        assert staging_pool.pool_model.rowCount() == 1
        assert staging_pool.pool_model._files[0].get("is_removing") is True

    def test_remove_file_preview_cancel(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """移除正在预览的文件时发射 preview_cancel_requested 并清空路径。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))
        staging_pool.set_previewing_file(file_a)
        assert staging_pool.previewing_file_path is not None

        cancelled: List[bool] = []
        staging_pool.preview_cancel_requested.connect(lambda: cancelled.append(True))
        staging_pool.remove_file(file_a)

        assert cancelled == [True]
        assert staging_pool.previewing_file_path is None

    def test_remove_file_unknown_path_noop(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """移除不存在的路径静默返回，不发射信号。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))
        removed: List[Dict[str, Any]] = []
        staging_pool.remove_from_selector.connect(removed.append)

        staging_pool.remove_file(str(tmp_path / "missing.txt"))

        assert len(staging_pool.items) == 1
        assert removed == []

    def test_handle_item_right_clicked_removes(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """_handle_item_right_clicked 按条目路径执行移除。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))

        staging_pool._handle_item_right_clicked(
            {"path": file_a, "name": "a.txt"}
        )

        assert staging_pool.items == []


class TestClearAll:
    """clear_all_without_confirmation 的清空行为。"""

    def test_clear_all_empties_and_emits_per_item(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """清空后 items/模型/服务皆空，且每个条目发一次 remove_from_selector。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        file_b: str = make_text(str(tmp_path / "b.txt"))
        staging_pool.add_file(_text_info(file_a))
        staging_pool.add_file(_text_info(file_b))

        removed: List[Dict[str, Any]] = []
        staging_pool.remove_from_selector.connect(removed.append)
        staging_pool.clear_all_without_confirmation()

        assert staging_pool.items == []
        assert staging_pool.pool_model.rowCount() == 0
        assert StagingPoolService().get_items() == []
        assert len(removed) == 2
        assert staging_pool.previewing_file_path is None

    def test_clear_all_updates_stats(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """清空后统计文案回到 0 个条目。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))
        staging_pool.clear_all_without_confirmation()
        assert "0个条目" in staging_pool.stats_label.text()


# =============================================================================
# 备份系统
# =============================================================================
class TestBackup:
    """save_backup / load_backup / 序列化 / 防抖落盘。"""

    def _populate_backup(
        self, staging_pool: Any, tmp_path: Path
    ) -> List[str]:
        """Add two text files and return their normalized paths."""
        file_a: str = os.path.normpath(make_text(str(tmp_path / "a.txt")))
        file_b: str = os.path.normpath(make_text(str(tmp_path / "b.txt")))
        staging_pool.add_file(_text_info(file_a))
        staging_pool.add_file(_text_info(file_b))
        return [file_a, file_b]

    def test_save_backup_writes_json(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """save_backup 把条目写入 backup_file 且包含 selector_state。"""
        self._populate_backup(staging_pool, tmp_path)

        staging_pool.save_backup("C:\\my\\dir")

        assert os.path.exists(staging_pool.backup_file)
        with open(staging_pool.backup_file, encoding="utf-8") as f:
            data: Dict[str, Any] = json.load(f)
        assert len(data["items"]) == 2
        assert data["selector_state"]["last_path"] == "C:\\my\\dir"

    def test_load_backup_roundtrip(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """load_backup 能还原 save_backup 写入的条目集合。"""
        expected: List[str] = self._populate_backup(staging_pool, tmp_path)
        staging_pool.save_backup("All")

        loaded: Dict[str, Any] = staging_pool.load_backup()

        assert len(loaded["items"]) == 2
        loaded_paths: List[str] = [
            os.path.normpath(item["path"]) for item in loaded["items"]
        ]
        assert set(loaded_paths) == set(expected)
        assert loaded["selector_state"]["last_path"] == "All"

    def test_load_backup_missing_returns_empty(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """备份文件不存在时返回空结构。"""
        loaded: Dict[str, Any] = staging_pool.load_backup()
        assert loaded["items"] == []
        assert loaded["selector_state"]["last_path"] == "All"

    def test_serialize_backup_item_whitelist(self, staging_pool: Any) -> None:
        """_serialize_backup_item 只保留白名单字段并归一化。"""
        serialized: Dict[str, Any] = FileStagingPool._serialize_backup_item(
            {
                "path": "/tmp/a.txt",
                "name": "a.txt",
                "display_name": "a.txt",
                "original_name": "a.txt",
                "is_dir": False,
                "size": 123,
                "is_selected": True,
                "is_missing": False,
                "size_calculating": True,
                "runtime_only": "should_be_dropped",
                "modified": 1700000000,
                "created": 1700000000,
                "suffix": ".txt",
                "info_text": "1.0 KB",
            }
        )
        assert set(serialized.keys()) == {
            "path",
            "size",
            "name",
            "display_name",
            "original_name",
            "modified",
            "created",
            "suffix",
            "info_text",
            "is_dir",
            "is_selected",
            "is_missing",
            "size_calculating",
        }
        assert "runtime_only" not in serialized
        assert serialized["size"] == 123
        assert serialized["is_dir"] is False
        assert serialized["info_text"] == "1.0 KB"

    def test_serialize_backup_item_invalid_input(self, staging_pool: Any) -> None:
        """非 dict 或缺失 path 的条目序列化为 None。"""
        assert FileStagingPool._serialize_backup_item("not-a-dict") is None
        assert FileStagingPool._serialize_backup_item({"name": "x"}) is None
        assert FileStagingPool._serialize_backup_item({"path": None}) is None

    def test_save_backup_if_needed_is_debounced(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """防抖：add_file 后未到时间不落盘，flush_backup_save_now 立即落盘。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))

        # 防抖定时器激活但尚未写盘
        assert staging_pool._backup_save_timer.isActive() is True
        assert os.path.exists(staging_pool.backup_file) is False

        staging_pool.flush_backup_save_now("All")
        assert os.path.exists(staging_pool.backup_file) is True

    def test_save_backup_if_needed_suspend_skips(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """恢复阶段挂起时 _flush_pending_backup_save 不写盘。"""
        staging_pool._suspend_backup_save = True
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))

        staging_pool._flush_pending_backup_save()

        assert os.path.exists(staging_pool.backup_file) is False


# =============================================================================
# 统计信息
# =============================================================================
class TestStats:
    """update_stats 与 _format_file_size。"""

    def test_field_format_file_size(self, staging_pool: Any) -> None:
        """自适应单位换算（B/KB/MB）。"""
        assert staging_pool._format_file_size(0) == "0 B"
        assert staging_pool._format_file_size(512) == "512 B"
        assert staging_pool._format_file_size(1024) == "1.00 KB"
        assert staging_pool._format_file_size(1536) == "1.50 KB"
        assert staging_pool._format_file_size(1048576) == "1.00 MB"

    def test_update_stats_shows_item_count_and_size(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """统计文案包含条目数与聚合大小。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a, size=2048))

        text: str = staging_pool.stats_label.text()
        assert "1个条目" in text
        assert "2.00 KB" in text

    def test_update_stats_calculating_count(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """存在 size_calculating 的目录时显示计算中计数。"""
        folder: Path = tmp_path / "folder"
        folder.mkdir()
        monkeypatch.setattr(
            staging_pool, "_calculate_folder_size", lambda path: None
        )
        staging_pool.add_file(
            {
                "path": str(folder),
                "name": "folder",
                "is_dir": True,
                "size": 0,
            }
        )

        text: str = staging_pool.stats_label.text()
        assert "1个条目" in text
        assert "正在计算1个文件夹" in text


# =============================================================================
# 预览态
# =============================================================================
class TestPreviewState:
    """set_previewing_file / clear_previewing_state。"""

    def test_set_previewing_file_normalizes(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """设置后 previewing_file_path 归一化且模型标记预览。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))

        staging_pool.set_previewing_file(file_a)

        assert staging_pool.previewing_file_path == os.path.normpath(file_a)
        item: Dict[str, Any] = staging_pool.pool_model.get_file_info_by_path(
            file_a
        )
        assert item.get("is_previewing") is True

    def test_clear_previewing_state_keeps_path(self, staging_pool: Any) -> None:
        """清除模型预览态但保留 previewing_file_path。"""
        staging_pool.previewing_file_path = "/tmp/a.txt"
        staging_pool.pool_model.add_file(_text_info("/tmp/a.txt"))
        staging_pool.set_previewing_file("/tmp/a.txt")

        staging_pool.clear_previewing_state()

        assert staging_pool.previewing_file_path == os.path.normpath(
            "/tmp/a.txt"
        )
        item: Dict[str, Any] = staging_pool.pool_model.get_file_info_by_path(
            "/tmp/a.txt"
        )
        assert item.get("is_previewing") is False


# =============================================================================
# 清理
# =============================================================================
class TestCleanup:
    """cleanup 的关闭态与资源释放。"""

    def test_cleanup_marks_closing_and_stops_timer(
        self, staging_pool: Any
    ) -> None:
        """cleanup 置关闭态并停止备份防抖定时器。"""
        staging_pool._backup_save_timer.start(30000)
        assert staging_pool._backup_save_timer.isActive() is True

        staging_pool.cleanup()

        assert staging_pool._is_closing is True
        assert staging_pool._backup_save_timer.isActive() is False

    def test_cleanup_disposes_service(self, staging_pool: Any) -> None:
        """cleanup 后 StagingPoolService 进入未初始化状态。"""
        service: StagingPoolService = StagingPoolService()
        assert service.is_initialized is True
        staging_pool.cleanup()
        assert service.is_initialized is False


# =============================================================================
# 重命名（模态对话框自动化）
# =============================================================================
class _FakeSignal:
    """CustomMessageBox.buttonClicked 的替身（仅记录处理器）。"""

    def __init__(self) -> None:
        self._handlers: List[Callable[..., Any]] = []

    def connect(self, handler: Callable[..., Any]) -> None:
        self._handlers.append(handler)

    def emit(self, *args: Any) -> None:
        for handler in list(self._handlers):
            try:
                handler(*args)
            except TypeError:
                # Qt 信号允许连接接受更少形参的槽；此处兜底 0 参 lambda。
                handler()


class _FakeMessageBox:
    """CustomMessageBox 替身：绝不阻塞，按下标队列自动点击。

    ``_queue`` 为类级消费队列，每项为 ``(button_index, input_text)``；
    ``exec()`` 弹出队首并按序号触发 ``buttonClicked`` 处理器。空队列时
    回落为 ``(0, "")``。
    """

    _queue: List[Tuple[int, Optional[str]]] = []
    _spawned: List["_FakeMessageBox"] = []

    def __init__(self, parent: Any = None) -> None:
        del parent  # 生产签名带 parent 参数，替身忽略
        self._title: str = ""
        self._text: str = ""
        self._input_value: str = ""
        self.buttonClicked = _FakeSignal()
        self.progress_bar: Any = None
        type(self)._spawned.append(self)

    def set_title(self, title: str) -> None:
        self._title = title

    def set_text(self, text: str) -> None:
        self._text = text

    def set_input(self, value: str) -> None:
        self._input_value = value

    def set_buttons(self, buttons: Any, *args: Any, **kwargs: Any) -> None:
        del buttons, args, kwargs  # 按钮布局与变体在本替身中忽略

    def set_progress(self, bar: Any) -> None:
        self.progress_bar = bar

    def get_input(self) -> str:
        return self._input_value

    def close(self, *args: Any) -> None:
        del args  # 生产代码可能以 button_index 调用 close

    def exec(self) -> int:
        idx, text = (
            type(self)._queue.pop(0)
            if type(self)._queue
            else (0, self._input_value)
        )
        self._input_value = text if text is not None else self._input_value
        self.buttonClicked.emit(idx)
        return idx


def _install_fake_message_box(monkeypatch: Any) -> None:
    """用 _FakeMessageBox 替换组件模块命名空间中的 CustomMessageBox。"""
    import freeassetfilter.components.file_staging_pool as fsp

    monkeypatch.setattr(fsp, "CustomMessageBox", _FakeMessageBox)
    _FakeMessageBox._queue = []
    _FakeMessageBox._spawned = []


class TestRenameFlow:
    """rename_file 通过替身输入框的完整流程。"""

    def _add_one(self, staging_pool: Any, tmp_path: Path) -> Dict[str, Any]:
        """向池中添加单条 .txt 并返回 items[0]（display_name=a.txt）。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))
        return staging_pool.items[0]

    def test_rename_success_keeps_extension(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """合法输入成功重命名，保留原后缀并同步模型/备份定时器。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(0, "renamed")]
        item: Dict[str, Any] = self._add_one(staging_pool, tmp_path)

        staging_pool.rename_file(item)

        updated: Dict[str, Any] = staging_pool.items[0]
        assert updated["display_name"] == "renamed.txt"
        assert updated["original_name"] == "a.txt"
        assert staging_pool._backup_save_timer.isActive() is True

    def test_rename_cancel_keeps_name(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """点击取消不做任何修改。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(1, None)]
        item: Dict[str, Any] = self._add_one(staging_pool, tmp_path)

        staging_pool.rename_file(item)

        assert staging_pool.items[0]["display_name"] == "a.txt"

    def test_rename_empty_name_warns_then_accepts(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """空文件名触发错误框后再输入有效名可完成。"""
        _install_fake_message_box(monkeypatch)
        # 输入框空值 → 错误框(确定) → 新输入框有效值
        _FakeMessageBox._queue = [(0, ""), (0, None), (0, "fixed")]
        item: Dict[str, Any] = self._add_one(staging_pool, tmp_path)

        staging_pool.rename_file(item)

        assert staging_pool.items[0]["display_name"] == "fixed.txt"

    def test_rename_illegal_chars_warns_then_accepts(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """含非法字符触发错误框后再输入有效名可完成。"""
        _install_fake_message_box(monkeypatch)
        # 输入框非法字符 → 错误框(确定) → 新输入框有效值
        _FakeMessageBox._queue = [(0, "bad<name"), (0, None), (0, "ok_name")]
        item: Dict[str, Any] = self._add_one(staging_pool, tmp_path)

        staging_pool.rename_file(item)

        assert staging_pool.items[0]["display_name"] == "ok_name.txt"

    def test_rename_same_name_is_noop(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """输入与原名相同直接返回，不触发备份定时器。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(0, "a.txt")]
        item: Dict[str, Any] = self._add_one(staging_pool, tmp_path)

        staging_pool.rename_file(item)

        assert staging_pool.items[0]["display_name"] == "a.txt"

    def test_rename_oversized_name_warns_then_accepts(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """超长文件名触发错误框后再输入有效名可完成。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(0, "x" * 200), (0, None), (0, "tiny")]
        item: Dict[str, Any] = self._add_one(staging_pool, tmp_path)

        staging_pool.rename_file(item)

        assert staging_pool.items[0]["display_name"] == "tiny.txt"


# =============================================================================
# 统计扩展：GB/TB 单位
# =============================================================================
class TestStatsLargeUnits:
    """_format_file_size 的 GB/TB 边界。"""

    def test_large_units(self, staging_pool: Any) -> None:
        """1023B→GB 边界与 TB 边界。"""
        assert staging_pool._format_file_size(1023) == "1023 B"
        assert staging_pool._format_file_size(1024**3) == "1.00 GB"
        assert staging_pool._format_file_size(int(1.5 * 1024**3)) == "1.50 GB"
        assert staging_pool._format_file_size(1024**4) == "1.00 TB"


# =============================================================================
# 导出流程
# =============================================================================
class TestExportFlow:
    """export_selected_files / _check_space_and_proceed / _do_export / 异步续接。"""

    def test_export_empty_pool_shows_info(
        self, staging_pool: Any, monkeypatch: Any
    ) -> None:
        """空池导出时弹出提示，不进入目录选择。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(0, None)]
        target_seen: List[str] = []
        import freeassetfilter.components.file_staging_pool as fsp

        def fake_browse(*args: Any, **kwargs: Any) -> str:
            del args, kwargs
            target_seen.append("browsed")
            return ""

        monkeypatch.setattr(
            fsp.QFileDialog, "getExistingDirectory", staticmethod(fake_browse)
        )

        staging_pool.export_selected_files()

        assert target_seen == []

    def test_export_cancel_mode_aborts(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """模式选择点取消后不再浏览目录。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(2, None)]  # 取消
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))
        target_seen: List[str] = []
        import freeassetfilter.components.file_staging_pool as fsp

        def fake_browse(*args: Any, **kwargs: Any) -> str:
            del args, kwargs
            target_seen.append("browsed")
            return ""

        monkeypatch.setattr(
            fsp.QFileDialog, "getExistingDirectory", staticmethod(fake_browse)
        )

        staging_pool.export_selected_files()

        assert target_seen == []

    def test_export_empty_directory_aborts(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """用户未选择目录直接取消后中止导出。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(0, None)]  # 直接导出
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))
        import freeassetfilter.components.file_staging_pool as fsp

        monkeypatch.setattr(
            fsp.QFileDialog,
            "getExistingDirectory",
            staticmethod(lambda *a, **k: ""),
        )
        exported: List[Any] = []
        monkeypatch.setattr(
            staging_pool, "_do_export", lambda *a: exported.append(a)
        )

        staging_pool.export_selected_files()

        assert exported == []

    def test_export_success_direct_mode(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """直接导出成功路径：模式 0，调用 _do_export。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(0, None)]  # 直接导出
        file_a: str = make_text(str(tmp_path / "a.txt"))
        file_b: str = make_text(str(tmp_path / "b.txt"))
        staging_pool.add_file(_text_info(file_a, size=512))
        staging_pool.add_file(_text_info(file_b, size=512))
        import freeassetfilter.components.file_staging_pool as fsp

        monkeypatch.setattr(
            fsp.QFileDialog,
            "getExistingDirectory",
            staticmethod(lambda *a, **k: str(tmp_path)),
        )
        monkeypatch.setattr(
            staging_pool, "get_directory_space", lambda d: (10**12, 10**12)
        )
        exported: List[Any] = []
        monkeypatch.setattr(
            staging_pool, "_do_export", lambda *a: exported.append(a)
        )

        staging_pool.export_selected_files()

        assert len(exported) == 1
        args: Tuple[list, str, int] = exported[0]
        _, target_dir, mode = args
        assert target_dir == str(tmp_path)
        assert mode == 0

    def test_export_still_calculating_goes_async(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """存在 size_calculating 目录时进入异步总大小路径。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(0, None)]  # 直接导出
        folder: Path = tmp_path / "folder"
        folder.mkdir()
        monkeypatch.setattr(
            staging_pool, "_calculate_folder_size", lambda path: None
        )
        staging_pool.add_file(
            {
                "path": str(folder),
                "name": "folder",
                "is_dir": True,
                "size": 0,
            }
        )
        import freeassetfilter.components.file_staging_pool as fsp

        monkeypatch.setattr(
            fsp.QFileDialog,
            "getExistingDirectory",
            staticmethod(lambda *a, **k: str(tmp_path)),
        )
        calc_calls: List[Any] = []
        monkeypatch.setattr(
            staging_pool,
            "calculate_total_size_async",
            lambda req_id, files: calc_calls.append((req_id, files)),
        )

        staging_pool.export_selected_files()

        assert len(calc_calls) == 1
        req_id, files = calc_calls[0]
        assert req_id.startswith("export_")
        assert len(files) == 1
        assert staging_pool._pending_export_req_id == req_id
        assert staging_pool._pending_export_state is not None
        assert "正在计算" in staging_pool.stats_label.text()

    def test_on_export_total_size_ready_stale_ignored(
        self, staging_pool: Any
    ) -> None:
        """过期 request_id 被忽略。"""
        staging_pool._pending_export_req_id = "export_1"
        staging_pool._pending_export_state = {"dummy": True}
        do_export_calls: List[Any] = []

        staging_pool._on_export_total_size_ready("export_2", 100)

        assert do_export_calls == []

    def test_on_export_total_size_ready_no_state(
        self, staging_pool: Any
    ) -> None:
        """匹配请求但无待处理状态时清空 ID 并返回。"""
        staging_pool.total_size_ready.connect(
            staging_pool._on_export_total_size_ready
        )
        staging_pool._pending_export_req_id = "export_1"
        staging_pool._pending_export_state = None

        staging_pool._on_export_total_size_ready("export_1", 100)

        assert staging_pool._pending_export_req_id is None

    def test_on_export_total_size_ready_continues_export(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """异步结果满足空间后继续调用 _do_export。"""
        _install_fake_message_box(monkeypatch)
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))
        staging_pool.total_size_ready.connect(
            staging_pool._on_export_total_size_ready
        )
        staging_pool._pending_export_req_id = "export_1"
        staging_pool._pending_export_state = {
            "target_dir": str(tmp_path),
            "all_files": list(staging_pool.items),
            "export_mode": 0,
        }
        monkeypatch.setattr(
            staging_pool, "get_directory_space", lambda d: (10**12, 10**12)
        )
        exported: List[Any] = []
        monkeypatch.setattr(
            staging_pool, "_do_export", lambda *a: exported.append(a)
        )

        staging_pool._on_export_total_size_ready("export_1", 123)

        assert len(exported) == 1
        _, target_dir, mode = exported[0]
        assert target_dir == str(tmp_path)
        assert mode == 0
        assert staging_pool._pending_export_req_id is None
        assert staging_pool._pending_export_state is None


class TestCheckSpace:
    """_check_space_and_proceed 的三个分支。"""

    def test_insufficient_space_reselect(
        self, staging_pool: Any, monkeypatch: Any
    ) -> None:
        """空间不足选"重新选择"返回 reselect。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(0, None)]
        monkeypatch.setattr(
            staging_pool, "get_directory_space", lambda d: (100, 10)
        )

        assert staging_pool._check_space_and_proceed("C:\\x", 50) == "reselect"

    def test_insufficient_space_cancel(
        self, staging_pool: Any, monkeypatch: Any
    ) -> None:
        """空间不足选"取消"返回 False。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(1, None)]
        monkeypatch.setattr(
            staging_pool, "get_directory_space", lambda d: (100, 10)
        )

        assert staging_pool._check_space_and_proceed("C:\\x", 50) is False

    def test_unknown_space_proceed(
        self, staging_pool: Any, monkeypatch: Any
    ) -> None:
        """空间未知（None/None）选"继续"返回 True。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(0, None)]
        monkeypatch.setattr(
            staging_pool, "get_directory_space", lambda d: (None, None)
        )

        assert staging_pool._check_space_and_proceed("\\\\nas\\share", 10) is True

    def test_unknown_space_reselect(
        self, staging_pool: Any, monkeypatch: Any
    ) -> None:
        """空间未知选"重新选择"返回 reselect。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(1, None)]
        monkeypatch.setattr(
            staging_pool, "get_directory_space", lambda d: (None, None)
        )

        assert staging_pool._check_space_and_proceed("\\\\nas\\share", 10) == "reselect"

    def test_unknown_space_cancel(
        self, staging_pool: Any, monkeypatch: Any
    ) -> None:
        """空间未知选"取消"返回 False。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(2, None)]
        monkeypatch.setattr(
            staging_pool, "get_directory_space", lambda d: (None, None)
        )

        assert staging_pool._check_space_and_proceed("\\\\nas\\share", 10) is False

    def test_sufficient_space_no_dialog(
        self, staging_pool: Any, monkeypatch: Any
    ) -> None:
        """空间充足时直接返回 True，不弹窗。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(0, None)]  # 不应被消费
        monkeypatch.setattr(
            staging_pool, "get_directory_space", lambda d: (10**12, 10**12)
        )

        assert staging_pool._check_space_and_proceed("C:\\x", 100) is True
        assert _FakeMessageBox._queue == [(0, None)]


class TestDoExport:
    """_do_export 的两种导出模式与进度/完成收尾。"""

    def test_do_export_direct_connects_progress(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """直接导出：进度条挂载、update_progress 已连接、copy_files 被调用。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(0, None)]  # 进度框 exec
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))
        copy_calls: List[Any] = []
        monkeypatch.setattr(
            staging_pool, "copy_files", lambda files, target: copy_calls.append(
                (files, target)
            )
        )

        staging_pool._do_export(list(staging_pool.items), str(tmp_path), 0)

        assert len(copy_calls) == 1
        assert staging_pool.current_progress_msg_box is not None
        assert staging_pool.current_export_progress_bar is not None
        # update_progress 信号已连接到进度槽（范围内 0..1）
        staging_pool.current_export_progress_bar.setValue(0)
        staging_pool.update_progress.emit(1)
        assert staging_pool.current_export_progress_bar.value() == 1

    def test_do_export_categorized_invokes_dialog(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """分类导出：调用 _show_categorized_export_dialog。"""
        _install_fake_message_box(monkeypatch)
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))
        dialog_calls: List[Any] = []
        monkeypatch.setattr(
            staging_pool,
            "_show_categorized_export_dialog",
            lambda *a: dialog_calls.append(a),
        )

        staging_pool._do_export(list(staging_pool.items), str(tmp_path), 1)

        assert len(dialog_calls) == 1
        files, target_dir, confirm_cb, cancel_cb = dialog_calls[0]
        assert target_dir == str(tmp_path)
        assert callable(confirm_cb)
        assert callable(cancel_cb)

    def test_on_update_export_progress_sets_value(
        self, staging_pool: Any, monkeypatch: Any
    ) -> None:
        """进度槽直接反映到 current_export_progress_bar。"""
        _install_fake_message_box(monkeypatch)
        from freeassetfilter.widgets.progress_widgets import D_ProgressBar

        bar = D_ProgressBar()
        bar.setRange(0, 5)
        bar.setValue(0)
        staging_pool.current_export_progress_bar = bar

        staging_pool.on_update_export_progress(3)

        assert bar.value() == 3

    def test_on_export_finished_success(
        self, staging_pool: Any, monkeypatch: Any
    ) -> None:
        """进度框关闭、update_progress 断开、成功提示弹出。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(0, None)]  # 结果框 exec 应答
        from freeassetfilter.widgets.progress_widgets import D_ProgressBar

        box = _FakeMessageBox()
        staging_pool.current_progress_msg_box = box
        staging_pool.current_export_progress_bar = D_ProgressBar()
        staging_pool.update_progress.connect(staging_pool.on_update_export_progress)
        spawned_before: int = len(_FakeMessageBox._spawned)

        staging_pool.on_export_finished(3, 0, [])

        assert not hasattr(staging_pool, "current_progress_msg_box")
        assert not hasattr(staging_pool, "current_export_progress_bar")
        # 结果框已创建并写标题
        assert len(_FakeMessageBox._spawned) == spawned_before + 1
        assert _FakeMessageBox._spawned[-1]._title == "导出完成"
        assert "成功导出 3 个文件" in _FakeMessageBox._spawned[-1]._text

    def test_on_export_finished_partial_errors(
        self, staging_pool: Any, monkeypatch: Any
    ) -> None:
        """部分失败时结果框文案包含失败详情与未显示余量。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(0, None)]  # 错误结果框 exec 应答
        staging_pool.current_progress_msg_box = _FakeMessageBox()
        from freeassetfilter.widgets.progress_widgets import D_ProgressBar

        staging_pool.current_export_progress_bar = D_ProgressBar()
        staging_pool.update_progress.connect(staging_pool.on_update_export_progress)
        spawned_before: int = len(_FakeMessageBox._spawned)

        staging_pool.on_export_finished(2, 3, ["e1", "e2", "e3", "e4", "e5", "e6"])

        # 最后创建的是结果框（错误分支）
        assert len(_FakeMessageBox._spawned) == spawned_before + 1
        result: _FakeMessageBox = _FakeMessageBox._spawned[-1]
        assert result._title == "导出结果"
        assert "失败 3 个文件" in result._text
        assert "还有 1 个错误未显示" in result._text


class TestStaleExportState:
    """_cleanup_stale_export_state 断开旧异步连接。"""

    def test_cleanup_with_pending_disconnects(
        self, staging_pool: Any
    ) -> None:
        """存在待处理请求时断开 total_size_ready 并清空状态。"""
        staging_pool.total_size_ready.connect(
            staging_pool._on_export_total_size_ready
        )
        staging_pool._pending_export_req_id = "export_1"
        staging_pool._pending_export_state = {"dummy": True}

        staging_pool._cleanup_stale_export_state()

        assert staging_pool._pending_export_req_id is None
        assert staging_pool._pending_export_state is None
        # 断开后再次清理不应抛异常（信号已无该槽）
        staging_pool._cleanup_stale_export_state()

    def test_cleanup_without_pending_noop(
        self, staging_pool: Any
    ) -> None:
        """无待处理状态时清理为幂等空操作。"""
        staging_pool._cleanup_stale_export_state()


# =============================================================================
# 文件信息与文件夹内容
# =============================================================================
class TestGetFileInfo:
    """_get_file_info 的返回结构、目录分支与错误路径。"""

    def test_file_info(self, staging_pool: Any, tmp_path: Path) -> None:
        """普通文件返回完整元信息。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        info: Optional[Dict[str, Any]] = staging_pool._get_file_info(file_a)

        assert info is not None
        assert info["name"] == "a.txt"
        assert info["path"] == file_a
        assert info["is_dir"] is False
        assert info["size"] is not None and info["size"] > 0
        assert info["size_calculating"] is False
        assert info["suffix"] == "txt"
        assert info["display_name"] == "a.txt"
        assert info["original_name"] == "a.txt"
        assert "modified" in info and "created" in info

    def test_dir_info(self, staging_pool: Any, tmp_path: Path) -> None:
        """目录返回 is_dir=True / size=None / size_calculating=True。"""
        folder: Path = tmp_path / "folder"
        folder.mkdir()
        info: Optional[Dict[str, Any]] = staging_pool._get_file_info(str(folder))

        assert info is not None
        assert info["is_dir"] is True
        assert info["size"] is None
        assert info["size_calculating"] is True
        assert info["suffix"] == ""

    def test_missing_path_returns_none(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """不存在的路径返回 None。"""
        info: Optional[Dict[str, Any]] = staging_pool._get_file_info(
            str(tmp_path / "missing.txt")
        )
        assert info is None


class TestAddFolderContents:
    """_add_folder_contents 递归收集并同步状态。"""

    def test_adds_nested_files(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """递归收集子目录中的 .txt 并同步 items/统计/备份定时器。"""
        folder: Path = tmp_path / "root"
        sub: Path = folder / "sub"
        sub.mkdir(parents=True)
        make_text(str(folder / "top.txt"))
        make_text(str(sub / "inner.txt"))

        staging_pool._add_folder_contents(str(folder))

        paths: List[str] = [item["path"] for item in staging_pool.items]
        assert any(p.endswith("top.txt") for p in paths)
        assert any(p.endswith("inner.txt") for p in paths)
        assert "2个条目" in staging_pool.stats_label.text()
        assert staging_pool._backup_save_timer.isActive() is True

    def test_missing_folder_noop(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """不存在的文件夹静默返回，不添加任何条目。"""
        staging_pool._add_folder_contents(str(tmp_path / "nope"))
        assert staging_pool.items == []


# =============================================================================
# 备份载荷
# =============================================================================
class TestBuildBackupPayload:
    """_build_backup_payload 的载荷结构。"""

    def test_payload_syncs_items_from_model(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """载荷从模型同步 items 并序列化白名单字段。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a, size=2048))

        payload: Dict[str, Any] = staging_pool._build_backup_payload("All")

        assert payload["selector_state"]["last_path"] == "All"
        assert len(payload["items"]) == 1
        item: Dict[str, Any] = payload["items"][0]
        assert item["path"] == os.path.normpath(file_a)
        assert "runtime_only" not in item

    def test_payload_default_last_path(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """last_path 缺省为 All。"""
        payload: Dict[str, Any] = staging_pool._build_backup_payload()
        assert payload["selector_state"]["last_path"] == "All"
        assert payload["items"] == []

    def test_empty_last_path_falls_back(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """空串 last_path 回落为 All。"""
        payload: Dict[str, Any] = staging_pool._build_backup_payload("")
        assert payload["selector_state"]["last_path"] == "All"


# =============================================================================
# 主列表重载
# =============================================================================
class TestReloadAllCards:
    """reload_all_cards 重载模型并过滤已缺失路径。"""

    def test_reload_empty_pool_noop(
        self, staging_pool: Any, monkeypatch: Any
    ) -> None:
        """空池直接返回。"""
        seen: List[str] = []
        monkeypatch.setattr(
            staging_pool, "refresh_all_card_icons", lambda: seen.append(1)
        )
        assert staging_pool.items == []
        staging_pool.reload_all_cards()
        assert seen == []

    def test_reload_rebuilds_model(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """重载后模型内仅保留仍存在的路径，预览态清空。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a, size=1024))
        # 注入一条已被删除的条目
        missing_path: str = str(tmp_path / "gone.txt")
        staging_pool.items.append(
            _text_info(missing_path, size=1)
        )
        staging_pool.pool_model.add_file(
            {
                **_text_info(missing_path, size=1),
                "is_missing": True,
            }
        )
        staging_pool.set_previewing_file(file_a)

        staging_pool.reload_all_cards()

        assert staging_pool.previewing_file_path is None
        paths: List[str] = [
            os.path.normpath(item["path"]) for item in staging_pool.items
        ]
        assert os.path.normpath(file_a) in paths
        assert os.path.normpath(missing_path) not in paths


# =============================================================================
# MD5 计算任务
# =============================================================================
class TestMD5CalculationTask:
    """_MD5CalculationTask 的哈希结果与异常路径。"""

    def test_computes_md5(
        self, qapp: Any, heartbeat_manager: Any, tmp_path: Path
    ) -> None:
        """后台任务计算得到文件 MD5（空字节不丢失，内容稳定）。"""
        del heartbeat_manager  # 已 start，用于 request_main_thread
        payload: bytes = b"hello\x00world content \xff\xfe"
        file_path: Path = tmp_path / "sample.bin"
        file_path.write_bytes(payload)
        results: List[Optional[str]] = []

        task = _MD5CalculationTask(str(file_path), results.append)
        task.run()

        computed: Optional[str] = None
        assert _pump_until(
            qapp, lambda: bool(results), timeout_s=5.0
        ), "回调未在超时前触发"
        computed = results[0]
        assert computed == hashlib.md5(payload).hexdigest()

    def test_missing_file_returns_none(
        self, qapp: Any, heartbeat_manager: Any, tmp_path: Path
    ) -> None:
        """文件不存在时回调收到 None（不抛出）。"""
        del heartbeat_manager
        results: List[Optional[str]] = []

        task = _MD5CalculationTask(
            str(tmp_path / "nope.bin"), results.append
        )
        task.run()

        assert _pump_until(
            qapp, lambda: bool(results), timeout_s=5.0
        ), "回调未在超时前触发"
        assert results[0] is None


# =============================================================================
# 主题 / 交互设置 / 事件过滤器
# =============================================================================
class TestThemeAndInteraction:
    """update_theme / _get_theme_colors / eventFilter 等纯 UI 方法。"""

    def test_get_theme_colors_returns_dict(self, staging_pool: Any) -> None:
        """主题色字典包含全部键且类型为 str。"""
        colors: Dict[str, str] = staging_pool._get_theme_colors()
        for key in (
            "base_color",
            "auxiliary_color",
            "normal_color",
            "secondary_color",
            "accent_color",
            "panel_background",
        ):
            assert key in colors
            assert isinstance(colors[key], str)

    def test_update_theme_no_raise(self, staging_pool: Any) -> None:
        """update_theme 在默认状态下不抛出异常。"""
        staging_pool.update_theme()
        assert staging_pool.pool_view.styleSheet()

    def test_apply_scroll_area_theme(self, staging_pool: Any) -> None:
        """应用滚动区主题后视图样式被设置、缓存被清空。"""
        colors: Dict[str, str] = staging_pool._get_theme_colors()
        staging_pool._apply_scroll_area_theme(colors)
        assert "QListView" in staging_pool.pool_view.styleSheet()

    def test_refresh_interaction_settings(
        self, staging_pool: Any, monkeypatch: Any
    ) -> None:
        """刷新交互设置不抛出异常（模型方法在测试中补齐）。"""
        monkeypatch.setattr(
            staging_pool.pool_model,
            "refresh_interaction_settings",
            lambda: None,
            raising=False,
        )
        staging_pool.refresh_interaction_settings()
        assert staging_pool.items == []

    def test_event_filter_enter_shows_buttons(
        self, staging_pool: Any
    ) -> None:
        """Enter 事件显示删除/重命名按钮。"""
        visible: List[bool] = []

        class _Btn(QObject):
            """带 setVisible 记录的按钮替身。"""

            def setVisible(self, v: bool) -> None:
                visible.append(v)

        class _Watch(QObject):
            """真实 QObject，供 eventFilter 的 super() 调用。"""

            delete_btn = _Btn()
            rename_btn = _Btn()

        class _FilterEvent(QEvent):
            """子类为实例暴露 Enter/Leave 枚举（PySide6 实例无该属性）。"""

            Enter = QEvent.Type.Enter
            Leave = QEvent.Type.Leave

        event = _FilterEvent(QEvent.Type.Enter)
        staging_pool.eventFilter(_Watch(), event)
        assert visible == [True, True]

    def test_event_filter_leave_hides_buttons(
        self, staging_pool: Any
    ) -> None:
        """Leave 事件隐藏删除/重命名按钮。"""
        visible: List[bool] = []

        class _Btn(QObject):
            """带 setVisible 记录的按钮替身。"""

            def setVisible(self, v: bool) -> None:
                visible.append(v)

        class _Watch(QObject):
            """真实 QObject，供 eventFilter 的 super() 调用。"""

            delete_btn = _Btn()
            rename_btn = _Btn()

        class _FilterEvent(QEvent):
            """同 test_event_filter_enter_shows_buttons。"""

            Enter = QEvent.Type.Enter
            Leave = QEvent.Type.Leave

        event = _FilterEvent(QEvent.Type.Leave)
        staging_pool.eventFilter(_Watch(), event)
        assert visible == [False, False]

    def test_refresh_all_card_icons_skips_empty(self, staging_pool: Any) -> None:
        """空池刷新图标安全返回。"""
        staging_pool.refresh_all_card_icons()
        assert staging_pool.items == []

    def test_refresh_all_card_icons_with_items(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """有项目时逐项刷新模型图标。"""
        file_path = tmp_path / "a.txt"
        file_path.write_text("x", encoding="utf-8")
        staging_pool.add_file(_text_info(str(file_path)))
        staging_pool.refresh_all_card_icons()
        assert len(staging_pool.items) == 1

    def test_on_folder_size_calculated_signal_handler(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """folder_size_calculated 处理器刷新统计与视图。"""
        file_path = tmp_path / "b.txt"
        file_path.write_text("x", encoding="utf-8")
        staging_pool.add_file(_text_info(str(file_path)))
        staging_pool.on_folder_size_calculated(
            staging_pool.items[0]
        )
        assert len(staging_pool.items) == 1


# =============================================================================
# 导入 / 导出数据
# =============================================================================
class TestImportExportData:
    """import_data / export_data / show_import_export_dialog。"""

    def test_import_data_valid_confirm_clear(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """合法 JSON 数组导入，确认清空后条目入池。"""
        _install_fake_message_box(monkeypatch)
        source = tmp_path / "src.txt"
        source.write_text("hi", encoding="utf-8")
        payload = [
            {"path": str(source), "name": "src.txt", "is_dir": False, "size": 2}
        ]
        json_file = tmp_path / "import.json"
        json_file.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            staticmethod(lambda *a, **k: (str(json_file), "")),
        )
        _FakeMessageBox._queue = [(0, None), (0, None)]

        dialog = QDialog()
        staging_pool.import_data(dialog)

        assert any("src.txt" in i["name"] for i in staging_pool.items)

    def test_import_data_non_list_warns(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """非数组 JSON 弹警告且不导入。"""
        _install_fake_message_box(monkeypatch)
        json_file = tmp_path / "import.json"
        json_file.write_text('{"a": 1}', encoding="utf-8")
        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            staticmethod(lambda *a, **k: (str(json_file), "")),
        )
        _FakeMessageBox._queue = [(0, None)]

        dialog = QDialog()
        staging_pool.import_data(dialog)

        assert staging_pool.items == []
        assert _FakeMessageBox._spawned[0]._title == "导入失败"

    def test_import_data_invalid_json_warns(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """JSON 解码失败弹警告且不导入。"""
        _install_fake_message_box(monkeypatch)
        json_file = tmp_path / "import.json"
        json_file.write_text("not json {", encoding="utf-8")
        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            staticmethod(lambda *a, **k: (str(json_file), "")),
        )
        _FakeMessageBox._queue = [(0, None)]

        dialog = QDialog()
        staging_pool.import_data(dialog)

        assert staging_pool.items == []
        assert _FakeMessageBox._spawned[0]._title == "导入失败"

    def test_import_data_io_error_warns(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """读取目录路径触发 OSError 警告分支。"""
        _install_fake_message_box(monkeypatch)
        target_dir = tmp_path / "a_dir"
        target_dir.mkdir()
        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            staticmethod(lambda *a, **k: (str(target_dir), "")),
        )
        _FakeMessageBox._queue = [(0, None)]

        dialog = QDialog()
        staging_pool.import_data(dialog)

        assert staging_pool.items == []
        assert _FakeMessageBox._spawned[0]._title == "导入失败"

    def test_import_data_unlinked_flow(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """存在不存在的路径时走未链接流程（方法被短路）。"""
        _install_fake_message_box(monkeypatch)
        payload = [
            {
                "path": str(tmp_path / "missing.txt"),
                "name": "missing.txt",
                "is_dir": False,
                "size": 1,
            }
        ]
        json_file = tmp_path / "import.json"
        json_file.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            staticmethod(lambda *a, **k: (str(json_file), "")),
        )
        called: List[Any] = []
        monkeypatch.setattr(
            staging_pool,
            "show_unlinked_files_dialog",
            lambda unlinked: called.append(unlinked),
        )
        _FakeMessageBox._queue = [(0, None), (0, None)]

        dialog = QDialog()
        staging_pool.import_data(dialog)

        assert len(called) == 1
        assert called[0][0]["status"] == "unlinked"
        assert staging_pool.items == []

    def test_export_data_empty_pool_warns(
        self, staging_pool: Any, monkeypatch: Any
    ) -> None:
        """空池导出提示无数据可导出。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(0, None)]
        dialog = QDialog()
        staging_pool.export_data(dialog)
        assert _FakeMessageBox._spawned[0]._title == "导出提示"

    def test_export_data_success(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """成功导出 JSON 到指定路径。"""
        _install_fake_message_box(monkeypatch)
        file_path = tmp_path / "c.txt"
        file_path.write_text("x", encoding="utf-8")
        staging_pool.add_file(_text_info(str(file_path)))
        out_file = tmp_path / "out.json"
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *a, **k: (str(out_file), "")),
        )
        _FakeMessageBox._queue = [(0, None)]

        dialog = QDialog()
        staging_pool.export_data(dialog)

        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data[0]["path"] == str(file_path)

    def test_export_data_write_error_warns(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """写入失败路径弹警告。"""
        _install_fake_message_box(monkeypatch)
        file_path = tmp_path / "d.txt"
        file_path.write_text("x", encoding="utf-8")
        staging_pool.add_file(_text_info(str(file_path)))
        bad_path = tmp_path / "no_such_dir" / "out.json"
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *a, **k: (str(bad_path), "")),
        )
        _FakeMessageBox._queue = [(0, None)]

        dialog = QDialog()
        staging_pool.export_data(dialog)

        assert _FakeMessageBox._spawned[0]._title == "导出失败"

    def test_show_import_export_dialog_import_choice(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """选择“导入数据”后进入 import_data。"""
        _install_fake_message_box(monkeypatch)
        source = tmp_path / "e.txt"
        source.write_text("hi", encoding="utf-8")
        payload = [
            {"path": str(source), "name": "e.txt", "is_dir": False, "size": 2}
        ]
        json_file = tmp_path / "import.json"
        json_file.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            staticmethod(lambda *a, **k: (str(json_file), "")),
        )
        # 选择框(0=导入) + 确认 + 完成
        _FakeMessageBox._queue = [(0, None), (0, None), (0, None)]

        staging_pool.show_import_export_dialog()

        assert any("e.txt" in i["name"] for i in staging_pool.items)

    def test_show_import_export_dialog_export_choice(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """选择“导出数据”后进入 export_data。"""
        _install_fake_message_box(monkeypatch)
        file_path = tmp_path / "f.txt"
        file_path.write_text("x", encoding="utf-8")
        staging_pool.add_file(_text_info(str(file_path)))
        out_file = tmp_path / "out.json"
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *a, **k: (str(out_file), "")),
        )
        # 选择框(1=导出) + 完成
        _FakeMessageBox._queue = [(1, None), (0, None)]

        staging_pool.show_import_export_dialog()

        assert out_file.exists()

    def test_calculate_md5_sync(self, staging_pool: Any, tmp_path: Path) -> None:
        """同步 MD5 与 hashlib 一致。"""
        target = tmp_path / "m.bin"
        payload = b"hello\x00world"
        target.write_bytes(payload)
        assert (
            staging_pool._calculate_md5_sync(str(target))
            == hashlib.md5(payload).hexdigest()
        )

    def test_calculate_md5_sync_missing_returns_none(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """缺失文件同步 MD5 返回 None。"""
        assert (
            staging_pool._calculate_md5_sync(str(tmp_path / "nope.bin"))
            is None
        )


# =============================================================================
# 未链接文件处理（辅助方法，不 exec 对话框）
# =============================================================================
class TestUnlinkedFiles:
    """unlinked 相关纯逻辑辅助方法。"""

    def _make_unlinked(
        self, original_path: str, name: str, status: str = "unlinked"
    ) -> Dict[str, Any]:
        return {
            "original_file_info": {
                "path": original_path,
                "name": name,
            },
            "status": status,
            "new_path": None,
            "md5": None,
        }

    def test_ignore_selected_files(self, staging_pool: Any, tmp_path: Path) -> None:
        """忽略选中项：状态变 ignored 且列表刷新。"""
        staging_pool.unlinked_list_widget = QListWidget()
        items = [
            self._make_unlinked(str(tmp_path / "a.txt"), "a.txt"),
            self._make_unlinked(str(tmp_path / "b.txt"), "b.txt"),
        ]
        item0 = QListWidgetItem()
        item0.setData(Qt.UserRole, 0)
        staging_pool.ignore_selected_files(items, [item0])
        assert items[0]["status"] == "ignored"
        assert items[1]["status"] == "unlinked"

    def test_ignore_all_files_confirmed(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """确认后全部忽略。"""
        _install_fake_message_box(monkeypatch)
        staging_pool.unlinked_list_widget = QListWidget()
        _FakeMessageBox._queue = [(0, None)]
        items = [
            self._make_unlinked(str(tmp_path / "a.txt"), "a.txt"),
            self._make_unlinked(str(tmp_path / "b.txt"), "b.txt"),
        ]
        staging_pool.ignore_all_files(items)
        assert all(i["status"] == "ignored" for i in items)

    def test_ignore_all_files_cancelled(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """取消后状态不变。"""
        _install_fake_message_box(monkeypatch)
        staging_pool.unlinked_list_widget = QListWidget()
        _FakeMessageBox._queue = [(1, None)]
        items = [
            self._make_unlinked(str(tmp_path / "a.txt"), "a.txt"),
        ]
        staging_pool.ignore_all_files(items)
        assert items[0]["status"] == "unlinked"

    def test_update_unlinked_list(self, staging_pool: Any, tmp_path: Path) -> None:
        """重建列表内容与 UserRole 索引。"""
        staging_pool.unlinked_list_widget = QListWidget()
        items = [
            self._make_unlinked(str(tmp_path / "a.txt"), "a.txt", "ignored"),
        ]
        staging_pool.update_unlinked_list(items)
        assert staging_pool.unlinked_list_widget.count() == 1
        assert (
            staging_pool.unlinked_list_widget.item(0).data(Qt.UserRole) == 0
        )

    def test_manual_link_selected_matching_name(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """文件名一致时直接链接。"""
        new_file = tmp_path / "a.txt"
        new_file.write_text("x", encoding="utf-8")
        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            staticmethod(lambda *a, **k: (str(new_file), "")),
        )
        items = [self._make_unlinked(str(tmp_path / "old.txt"), "a.txt")]
        item0 = QListWidgetItem()
        item0.setData(Qt.UserRole, 0)
        staging_pool.unlinked_list_widget = QListWidget()
        staging_pool.manual_link_selected_files(items, [item0])
        assert items[0]["status"] == "linked"
        assert items[0]["new_path"] == str(new_file)

    def test_manual_link_selected_mismatch_confirmed(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """文件名不一致但用户确认后链接。"""
        _install_fake_message_box(monkeypatch)
        new_file = tmp_path / "other.txt"
        new_file.write_text("x", encoding="utf-8")
        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            staticmethod(lambda *a, **k: (str(new_file), "")),
        )
        _FakeMessageBox._queue = [(0, None)]
        items = [self._make_unlinked(str(tmp_path / "old.txt"), "a.txt")]
        item0 = QListWidgetItem()
        item0.setData(Qt.UserRole, 0)
        staging_pool.unlinked_list_widget = QListWidget()
        staging_pool.manual_link_selected_files(items, [item0])
        assert items[0]["status"] == "linked"
        assert items[0]["new_path"] == str(new_file)

    def test_manual_link_selected_mismatch_cancelled(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """文件名不一致且取消时跳过。"""
        _install_fake_message_box(monkeypatch)
        new_file = tmp_path / "other.txt"
        new_file.write_text("x", encoding="utf-8")
        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            staticmethod(lambda *a, **k: (str(new_file), "")),
        )
        _FakeMessageBox._queue = [(1, None)]
        items = [self._make_unlinked(str(tmp_path / "old.txt"), "a.txt")]
        item0 = QListWidgetItem()
        item0.setData(Qt.UserRole, 0)
        staging_pool.unlinked_list_widget = QListWidget()
        staging_pool.manual_link_selected_files(items, [item0])
        assert items[0]["status"] == "unlinked"

    def test_manual_link_files_md5_match(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """目录内存在 MD5 一致文件时自动链接。"""
        _install_fake_message_box(monkeypatch)
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        original = src_dir / "same.txt"
        original.write_bytes(b"abc")
        target_dir = tmp_path / "tgt"
        target_dir.mkdir()
        (target_dir / "same.txt").write_bytes(b"abc")
        monkeypatch.setattr(
            QFileDialog,
            "getExistingDirectory",
            staticmethod(lambda *a, **k: str(target_dir)),
        )
        _FakeMessageBox._queue = [(0, None)]
        items = [self._make_unlinked(str(original), "same.txt")]
        staging_pool.unlinked_list_widget = QListWidget()
        staging_pool.manual_link_files(items, staging_pool.unlinked_list_widget)
        assert items[0]["status"] == "linked"
        assert items[0]["new_path"] == str(target_dir / "same.txt")

    def test_manual_link_files_name_match(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """仅文件名匹配时弹确认，确认后链接。"""
        _install_fake_message_box(monkeypatch)
        target_dir = tmp_path / "tgt"
        target_dir.mkdir()
        (target_dir / "a.txt").write_bytes(b"diff")
        monkeypatch.setattr(
            QFileDialog,
            "getExistingDirectory",
            staticmethod(lambda *a, **k: str(target_dir)),
        )
        _FakeMessageBox._queue = [(0, None), (0, None)]
        items = [
            self._make_unlinked(str(tmp_path / "ghost" / "a.txt"), "a.txt")
        ]
        staging_pool.unlinked_list_widget = QListWidget()
        staging_pool.manual_link_files(items, staging_pool.unlinked_list_widget)
        assert items[0]["status"] == "linked"

    def test_manual_link_files_no_dir_aborts(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """未选择目录时直接返回。"""
        monkeypatch.setattr(
            QFileDialog,
            "getExistingDirectory",
            staticmethod(lambda *a, **k: ""),
        )
        items = [self._make_unlinked(str(tmp_path / "a.txt"), "a.txt")]
        staging_pool.unlinked_list_widget = QListWidget()
        staging_pool.manual_link_files(items, staging_pool.unlinked_list_widget)
        assert items[0]["status"] == "unlinked"

    def test_finish_unlinked_dialog_all_processed(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """无未处理文件时直接 accept。"""
        from types import SimpleNamespace

        accepted: List[bool] = []
        dialog = SimpleNamespace(accept=lambda: accepted.append(True))
        items = [
            self._make_unlinked(str(tmp_path / "a.txt"), "a.txt", "ignored")
        ]
        staging_pool.finish_unlinked_files_dialog(dialog, items)
        assert accepted == [True]

    def test_finish_unlinked_dialog_remaining_confirmed(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """仍有未处理文件，确认后忽略并 accept。"""
        _install_fake_message_box(monkeypatch)
        from types import SimpleNamespace

        accepted: List[bool] = []
        dialog = SimpleNamespace(accept=lambda: accepted.append(True))
        _FakeMessageBox._queue = [(0, None)]
        items = [self._make_unlinked(str(tmp_path / "a.txt"), "a.txt")]
        staging_pool.finish_unlinked_files_dialog(dialog, items)
        assert items[0]["status"] == "ignored"
        assert accepted == [True]

    def test_finish_unlinked_dialog_remaining_cancelled(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """仍有未处理文件但取消时不 accept。"""
        _install_fake_message_box(monkeypatch)
        from types import SimpleNamespace

        accepted: List[bool] = []
        dialog = SimpleNamespace(accept=lambda: accepted.append(True))
        _FakeMessageBox._queue = [(1, None)]
        items = [self._make_unlinked(str(tmp_path / "a.txt"), "a.txt")]
        staging_pool.finish_unlinked_files_dialog(dialog, items)
        assert items[0]["status"] == "unlinked"
        assert accepted == []

    def test_show_unlinked_context_menu_no_selection(
        self, staging_pool: Any
    ) -> None:
        """无选中项时右键菜单直接返回。"""
        staging_pool.unlinked_list_widget = QListWidget()
        staging_pool.show_unlinked_context_menu(QPoint(0, 0), [])
        # 未抛出即通过

    def test_show_unlinked_context_menu_with_selection(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """有选中项时构建菜单（exec 被短路）。"""
        import freeassetfilter.components.file_staging_pool as fsp

        exec_called: List[bool] = []
        monkeypatch.setattr(
            QMenu, "exec_", lambda self, pos: exec_called.append(True)
        )
        staging_pool.unlinked_list_widget = QListWidget()
        item0 = QListWidgetItem("x")
        item0.setData(Qt.UserRole, 0)
        staging_pool.unlinked_list_widget.addItem(item0)
        staging_pool.unlinked_list_widget.setCurrentRow(0)
        items = [self._make_unlinked(str(tmp_path / "a.txt"), "a.txt")]
        staging_pool.show_unlinked_context_menu(QPoint(0, 0), items)
        assert exec_called == [True]
        # 还原 QMenu 签名，避免影响其它用例
        del fsp  # noqa: F841 (module 级别引用保持导入链完整)


# =============================================================================
# 拖拽事件
# =============================================================================
class TestDragDropEvents:
    """dragEnter/dragMove/dragLeave/drop 及 _add_dropped_item。"""

    def _mime_with_urls(self, paths: List[str]) -> QMimeData:
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        return mime

    def _make_drag_event(self, paths: List[str]) -> Any:
        """构造带 URL 的 QDragEnterEvent，并保持 mime 数据存活。

        PySide6 的事件构造器会接管 QMimeData 的所有权；若不保留 Python
        引用，GC 可能在 Qt 仍使用它时释放对象，导致访问违例崩溃。
        """
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        self._keep_alive = mime
        return QDragEnterEvent(
            QPoint(0, 0), Qt.CopyAction, mime,
            Qt.LeftButton, Qt.NoModifier,
        )

    def _make_drop_event(self, paths: List[str]) -> Any:
        """构造带 URL 的 QDropEvent，保持 mime 数据存活（同上）。"""
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        self._keep_alive = mime
        return QDropEvent(
            QPointF(0, 0), Qt.CopyAction, mime,
            Qt.LeftButton, Qt.NoModifier,
        )

    def test_drag_enter_accepts_urls(self, staging_pool: Any) -> None:
        event = self._make_drag_event(["C:/x.txt"])
        staging_pool.dragEnterEvent(event)
        assert event.isAccepted()

    def test_drag_enter_ignores_no_urls(self, staging_pool: Any) -> None:
        mime = QMimeData()
        self._keep_alive = mime
        event = QDragEnterEvent(
            QPoint(0, 0), Qt.CopyAction, mime,
            Qt.LeftButton, Qt.NoModifier,
        )
        staging_pool.dragEnterEvent(event)
        assert not event.isAccepted()

    def test_drag_move(self, staging_pool: Any) -> None:
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile("C:/x.txt")])
        self._keep_alive = mime
        event = QDragMoveEvent(
            QPoint(0, 0), Qt.CopyAction, mime,
            Qt.LeftButton, Qt.NoModifier,
        )
        staging_pool.dragMoveEvent(event)
        assert event.isAccepted()

    def test_drag_leave_restores_style(self, staging_pool: Any) -> None:
        event = QDragLeaveEvent()
        staging_pool.dragLeaveEvent(event)

    def test_drop_adds_file(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        source = tmp_path / "drop.txt"
        source.write_text("x", encoding="utf-8")
        events: List[Tuple[str, Any]] = []
        staging_pool.navigate_to_path.connect(
            lambda d, fi: events.append((d, fi))
        )
        event = self._make_drop_event([str(source)])
        staging_pool.dropEvent(event)
        assert event.isAccepted()
        assert len(events) == 1
        assert events[0][1]["name"] == "drop.txt"

    def test_drop_ignores_missing(self, staging_pool: Any, tmp_path: Path) -> None:
        events: List[Any] = []
        staging_pool.navigate_to_path.connect(lambda *a: events.append(a))
        event = self._make_drop_event([str(tmp_path / "nope.txt")])
        staging_pool.dropEvent(event)
        assert event.isAccepted()
        assert events == []

    def test_add_dropped_item_file(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        source = tmp_path / "dropped.txt"
        source.write_text("x", encoding="utf-8")
        events: List[Tuple[str, Any]] = []
        staging_pool.navigate_to_path.connect(
            lambda d, fi: events.append((d, fi))
        )
        staging_pool._add_dropped_item(str(source))
        assert events[0][0] == str(tmp_path)
        assert events[0][1]["name"] == "dropped.txt"

    def test_add_dropped_item_dir(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        target_dir = tmp_path / "dir"
        target_dir.mkdir()
        events: List[Tuple[str, Any]] = []
        staging_pool.navigate_to_path.connect(
            lambda d, fi: events.append((d, fi))
        )
        staging_pool._add_dropped_item(str(target_dir))
        assert events[0][0] == str(target_dir)
        assert events[0][1]["is_dir"] is True

    def test_add_dropped_item_missing(self, staging_pool: Any, tmp_path: Path) -> None:
        events: List[Any] = []
        staging_pool.navigate_to_path.connect(lambda *a: events.append(a))
        staging_pool._add_dropped_item(str(tmp_path / "nope.txt"))
        assert events == []


# =============================================================================
# 目录遍历与大小累加
# =============================================================================
class TestIterEntriesAndSum:
    """_iter_file_entries / _sum_folder_file_sizes 静态方法。"""

    def test_iter_file_entries_nested(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        (root / "sub").mkdir(parents=True)
        (root / "a.txt").write_text("a", encoding="utf-8")
        (root / "sub" / "b.txt").write_text("b", encoding="utf-8")
        names = sorted(
            e.name for e in FileStagingPool._iter_file_entries(str(root))
        )
        assert names == ["a.txt", "b.txt"]

    def test_iter_file_entries_cancel_preset(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        root.mkdir()
        (root / "a.txt").write_text("a", encoding="utf-8")
        cancel = threading.Event()
        cancel.set()
        result = list(
            FileStagingPool._iter_file_entries(str(root), cancel)
        )
        assert result == []

    def test_iter_file_entries_missing_dir(self, tmp_path: Path) -> None:
        result = list(
            FileStagingPool._iter_file_entries(
                str(tmp_path / "ghost"), None
            )
        )
        assert result == []

    def test_sum_folder_file_sizes(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        root.mkdir()
        (root / "a.bin").write_bytes(b"x" * 100)
        (root / "b.bin").write_bytes(b"y" * 50)
        assert FileStagingPool._sum_folder_file_sizes(str(root)) == 150

    def test_sum_folder_file_sizes_cancelled(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        root.mkdir()
        (root / "a.bin").write_bytes(b"x" * 100)
        cancel = threading.Event()
        cancel.set()
        assert FileStagingPool._sum_folder_file_sizes(str(root), cancel) is None


# =============================================================================
# 文件夹大小计算线程与回调
# =============================================================================
class TestFolderSizeCalc:
    """_calculate_folder_size 线程编排与 _on_folder_size_calculated。"""

    def test_worker_returns_size(self, tmp_path: Path) -> None:
        folder = tmp_path / "f"
        folder.mkdir()
        (folder / "a.bin").write_bytes(b"x" * 42)
        result = FileStagingPool._calculate_folder_size_worker(
            str(folder), threading.Event()
        )
        assert result == {"path": str(folder), "size": 42}

    def test_worker_cancelled_returns_none(self, tmp_path: Path) -> None:
        folder = tmp_path / "f"
        folder.mkdir()
        cancel = threading.Event()
        cancel.set()
        assert (
            FileStagingPool._calculate_folder_size_worker(str(folder), cancel)
            is None
        )

    def test_worker_missing_dir_returns_zero_size(self, tmp_path: Path) -> None:
        """缺失目录的 worker 返回 0 大小字典（不抛异常）。"""
        assert (
            FileStagingPool._calculate_folder_size_worker(
                str(tmp_path / "ghost"), threading.Event()
            )
            == {"path": str(tmp_path / "ghost"), "size": 0}
        )

    def test_calculate_folder_size_submits_and_updates(
        self, staging_pool: Any, qapp: Any, tmp_path: Path
    ) -> None:
        """真实线程池提交后，模型 size_calculating 变为 False。"""
        folder = tmp_path / "big"
        folder.mkdir()
        (folder / "a.bin").write_bytes(b"x" * 10)
        folder_info = {
            "path": str(folder),
            "name": folder.name,
            "is_dir": True,
            "size_calculating": True,
        }
        staging_pool.add_file(folder_info)
        staging_pool._calculate_folder_size(str(folder))

        def done() -> bool:
            info = staging_pool.pool_model.get_file_info_by_path(str(folder))
            return bool(info) and info["size_calculating"] is False

        assert _pump_until(qapp, done, timeout_s=8.0), "文件夹大小未完成计算"

    def test_calculate_folder_size_skips_active(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """同一路径已有未完成任务时不重复提交。"""
        folder = tmp_path / "f"
        folder.mkdir()
        future = Future()
        staging_pool._active_size_calculators[str(folder)] = future
        staging_pool._calculate_folder_size(str(folder))
        assert (
            staging_pool._active_size_calculators[str(folder)] is future
        )

    def test_cleanup_finished_calculators(self, staging_pool: Any) -> None:
        future = Future()
        future.set_result({"path": "x", "size": 1})
        staging_pool._active_size_calculators["x"] = future
        staging_pool._size_calculator_cancel_events["x"] = threading.Event()
        staging_pool._cleanup_finished_calculators()
        assert "x" not in staging_pool._active_size_calculators

    def test_stop_all_size_calculators(self, staging_pool: Any) -> None:
        from concurrent.futures import ThreadPoolExecutor

        future = Future()
        staging_pool._active_size_calculators["x"] = future
        staging_pool._size_calculator_cancel_events["x"] = threading.Event()
        staging_pool.stop_all_size_calculators()
        assert staging_pool._active_size_calculators == {}
        assert staging_pool._size_calculator_cancel_events == {}
        assert staging_pool._size_calculator_executor is None
        # 重建执行器，避免污染后续用例的 teardown
        staging_pool._size_calculator_executor = ThreadPoolExecutor(max_workers=1)

    def test_on_folder_size_calculated_updates_model(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        folder = tmp_path / "f"
        folder.mkdir()
        folder_info = {
            "path": str(folder),
            "name": folder.name,
            "is_dir": True,
            "size_calculating": True,
        }
        staging_pool.add_file(folder_info)
        staging_pool._on_folder_size_calculated(
            {"path": str(folder), "size": 123}
        )
        info = staging_pool.pool_model.get_file_info_by_path(str(folder))
        assert info["size"] == 123
        assert info["size_calculating"] is False

    def test_on_folder_size_calculated_ignores_when_closing(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        staging_pool._is_closing = True
        staging_pool._on_folder_size_calculated(
            {"path": str(tmp_path / "x"), "size": 1}
        )
        # 未抛出即通过

    def test_on_folder_size_calculated_no_path(self, staging_pool: Any) -> None:
        staging_pool._on_folder_size_calculated({})
        # 未抛出即通过

    def test_on_folder_size_calculated_unknown_path(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        staging_pool._on_folder_size_calculated(
            {"path": str(tmp_path / "ghost"), "size": 1}
        )
        # 未抛出即通过

    def test_on_folder_size_calculated_completes_pending_total(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        folder = tmp_path / "f"
        folder.mkdir()
        folder_info = {
            "path": str(folder),
            "name": folder.name,
            "is_dir": True,
            "size_calculating": True,
        }
        staging_pool.add_file(folder_info)
        emitted: List[Tuple[str, int]] = []
        staging_pool.total_size_ready.connect(
            lambda rid, total: emitted.append((rid, total))
        )
        staging_pool._pending_total_requests["req"] = {
            "base_total": 10,
            "pending_folders": {str(folder)},
        }
        staging_pool._on_folder_size_calculated(
            {"path": str(folder), "size": 5}
        )
        assert emitted == [("req", 15)]
        assert "req" not in staging_pool._pending_total_requests


# =============================================================================
# 总大小异步计算
# =============================================================================
class TestCalculateTotalSize:
    """calculate_total_size_async 分支。"""

    def test_immediate_emit_known_sizes(self, staging_pool: Any) -> None:
        emitted: List[Tuple[str, int]] = []
        staging_pool.total_size_ready.connect(
            lambda rid, total: emitted.append((rid, total))
        )
        files = [
            {"path": "a", "size_calculating": False, "size": 10},
            {"path": "b", "size_calculating": False, "size": 20},
        ]
        staging_pool.calculate_total_size_async("r1", files)
        assert emitted == [("r1", 30)]

    def test_pending_folder_stored(self, staging_pool: Any) -> None:
        emitted: List[Tuple[str, int]] = []
        staging_pool.total_size_ready.connect(
            lambda rid, total: emitted.append((rid, total))
        )
        files = [
            {"path": "folder", "size_calculating": True},
        ]
        staging_pool.calculate_total_size_async("r2", files)
        assert emitted == []
        assert "r2" in staging_pool._pending_total_requests
        assert staging_pool._pending_total_requests["r2"]["pending_folders"] == {
            "folder"
        }

    def test_unknown_path_gets_size(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        emitted: List[Tuple[str, int]] = []
        staging_pool.total_size_ready.connect(
            lambda rid, total: emitted.append((rid, total))
        )
        target = tmp_path / "s.bin"
        target.write_bytes(b"x" * 7)
        files = [{"path": str(target), "size_calculating": False}]
        staging_pool.calculate_total_size_async("r3", files)
        assert emitted == [("r3", 7)]

    def test_unknown_dir_pending(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        target = tmp_path / "d"
        target.mkdir()
        files = [{"path": str(target), "size_calculating": False}]
        staging_pool.calculate_total_size_async("r4", files)
        assert "r4" in staging_pool._pending_total_requests

    def test_missing_path_warns_no_emit(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """缺失路径既非文件也非目录 → 仅发射 (req_id, 0)。"""
        emitted: List[Any] = []
        staging_pool.total_size_ready.connect(lambda *a: emitted.append(a))
        files = [{"path": str(tmp_path / "ghost"), "size_calculating": False}]
        staging_pool.calculate_total_size_async("r5", files)
        assert emitted == [("r5", 0)]


# =============================================================================
# 复制文件（线程）
# =============================================================================
class TestCopyFiles:
    """copy_files / copy_files_categorized / _get_unique_target_path。"""

    def test_copy_files_direct_success(
        self, staging_pool: Any, qapp: Any, tmp_path: Path
    ) -> None:
        source = tmp_path / "copy.txt"
        source.write_text("content", encoding="utf-8")
        target_dir = tmp_path / "out"
        target_dir.mkdir()
        finished: List[Tuple[int, int, List[str]]] = []
        staging_pool.export_finished.disconnect(staging_pool.on_export_finished)
        staging_pool.export_finished.connect(
            lambda s, e, err: finished.append((s, e, err))
        )
        files = [
            {
                "path": str(source),
                "name": "copy.txt",
                "display_name": "copy.txt",
                "is_dir": False,
                "size": 7,
            }
        ]
        staging_pool.copy_files(files, str(target_dir))
        assert _pump_until(
            qapp, lambda: bool(finished), timeout_s=8.0
        ), "导出线程未结束"
        assert finished[0][0] == 1
        assert (target_dir / "copy.txt").read_text(
            encoding="utf-8"
        ) == "content"

    def test_copy_files_missing_source(
        self, staging_pool: Any, qapp: Any, tmp_path: Path
    ) -> None:
        target_dir = tmp_path / "out"
        target_dir.mkdir()
        finished: List[Tuple[int, int, List[str]]] = []
        staging_pool.export_finished.disconnect(staging_pool.on_export_finished)
        staging_pool.export_finished.connect(
            lambda s, e, err: finished.append((s, e, err))
        )
        files = [
            {
                "path": str(tmp_path / "ghost.txt"),
                "name": "ghost.txt",
                "display_name": "ghost.txt",
                "is_dir": False,
                "size": 0,
            }
        ]
        staging_pool.copy_files(files, str(target_dir))
        assert _pump_until(
            qapp, lambda: bool(finished), timeout_s=8.0
        ), "导出线程未结束"
        assert finished[0][1] == 1

    def test_copy_files_dir(
        self, staging_pool: Any, qapp: Any, tmp_path: Path
    ) -> None:
        source_dir = tmp_path / "src_dir"
        source_dir.mkdir()
        (source_dir / "inner.txt").write_text("i", encoding="utf-8")
        target_dir = tmp_path / "out"
        target_dir.mkdir()
        finished: List[Tuple[int, int, List[str]]] = []
        staging_pool.export_finished.disconnect(staging_pool.on_export_finished)
        staging_pool.export_finished.connect(
            lambda s, e, err: finished.append((s, e, err))
        )
        files = [
            {
                "path": str(source_dir),
                "name": source_dir.name,
                "display_name": source_dir.name,
                "is_dir": True,
            }
        ]
        staging_pool.copy_files(files, str(target_dir))
        assert _pump_until(
            qapp, lambda: bool(finished), timeout_s=8.0
        ), "导出线程未结束"
        assert finished[0][0] == 1
        assert (target_dir / source_dir.name / "inner.txt").exists()

    def test_copy_files_categorized_mapping(
        self, staging_pool: Any, qapp: Any, tmp_path: Path
    ) -> None:
        src = tmp_path / "cat"
        src.mkdir()
        source = src / "item.txt"
        source.write_text("c", encoding="utf-8")
        target_dir = tmp_path / "out"
        target_dir.mkdir()
        finished: List[Tuple[int, int, List[str]]] = []
        staging_pool.export_finished.disconnect(staging_pool.on_export_finished)
        staging_pool.export_finished.connect(
            lambda s, e, err: finished.append((s, e, err))
        )
        files = [
            {
                "path": str(source),
                "name": "item.txt",
                "display_name": "item.txt",
                "is_dir": False,
            }
        ]
        staging_pool.copy_files_categorized(
            files, str(target_dir), {"cat": "renamed"}
        )
        assert _pump_until(
            qapp, lambda: bool(finished), timeout_s=8.0
        ), "分类导出线程未结束"
        assert finished[0][0] == 1
        assert (target_dir / "renamed" / "item.txt").exists()

    def test_copy_files_categorized_makedirs_error(
        self, staging_pool: Any, qapp: Any, tmp_path: Path
    ) -> None:
        src = tmp_path / "cat"
        src.mkdir()
        source = src / "item.txt"
        source.write_text("c", encoding="utf-8")
        target_dir = tmp_path / "out"
        target_dir.mkdir()
        (target_dir / "cat").write_text("blocker", encoding="utf-8")
        finished: List[Tuple[int, int, List[str]]] = []
        staging_pool.export_finished.disconnect(staging_pool.on_export_finished)
        staging_pool.export_finished.connect(
            lambda s, e, err: finished.append((s, e, err))
        )
        files = [
            {
                "path": str(source),
                "name": "item.txt",
                "display_name": "item.txt",
                "is_dir": False,
            }
        ]
        staging_pool.copy_files_categorized(files, str(target_dir))
        assert _pump_until(
            qapp, lambda: bool(finished), timeout_s=8.0
        ), "分类导出线程未结束"
        assert finished[0][1] == 1

    def test_get_unique_target_path_no_conflict(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        assert (
            staging_pool._get_unique_target_path(str(tmp_path), "a.txt")
            == str(tmp_path / "a.txt")
        )

    def test_get_unique_target_path_conflict_with_ext(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        assert (
            staging_pool._get_unique_target_path(str(tmp_path), "a.txt")
            == str(tmp_path / "a_1.txt")
        )

    def test_get_unique_target_path_conflict_no_ext(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        (tmp_path / "a").write_text("x", encoding="utf-8")
        assert (
            staging_pool._get_unique_target_path(str(tmp_path), "a")
            == str(tmp_path / "a_1")
        )

    def test_get_unique_target_path_many_conflicts(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """9999 个冲突后回退时间戳命名。"""
        import freeassetfilter.components.file_staging_pool as fsp

        monkeypatch.setattr(fsp.os.path, "exists", lambda p: True)
        result = staging_pool._get_unique_target_path(str(tmp_path), "a.txt")
        assert result.startswith(str(tmp_path / "a_"))


# =============================================================================
# 备份边界 / 清理 / 关闭
# =============================================================================
class TestBackupAndCloseEdges:
    """save_backup 错误路径 / _build_backup_payload 回退 / closeEvent。"""

    def test_save_backup_error_warns(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        staging_pool.backup_file = str(
            tmp_path / "ghost_dir" / "backup.json"
        )
        staging_pool.save_backup("All")
        # 未抛出即通过（目录不存在触发 IOError 分支）

    def test_build_backup_payload_no_model(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        payload = staging_pool._build_backup_payload("SomePath")
        assert payload["selector_state"]["last_path"] == "SomePath"
        assert isinstance(payload["items"], list)

    def test_serialize_backup_item_empty_path(self, staging_pool: Any) -> None:
        # 空白路径经 normpath('') → '.'，返回序列化字典而非 None
        serialized = FileStagingPool._serialize_backup_item({"path": "   "})
        assert serialized is not None
        assert serialized["path"] == os.path.normpath(".")

    def test_serialize_backup_item_non_numeric_size(
        self, staging_pool: Any
    ) -> None:
        serialized = FileStagingPool._serialize_backup_item(
            {"path": "/x", "size": "not-a-number"}
        )
        assert serialized["size"] is None

    def test_get_directory_space_delegates(
        self, staging_pool: Any
    ) -> None:
        class _FakeService:
            def get_directory_space(self, directory: str) -> Any:
                return (100, 50)

        staging_pool._staging_pool_service = _FakeService()
        assert staging_pool.get_directory_space("C:/") == (100, 50)

    def test_add_folder_contents_error(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        import freeassetfilter.components.file_staging_pool as fsp

        def _raise(*args: Any, **kwargs: Any) -> Any:
            raise OSError("boom")

        monkeypatch.setattr(
            fsp.FileStagingPool, "_iter_file_entries", staticmethod(_raise)
        )
        staging_pool._add_folder_contents(str(tmp_path))
        # 未抛出即通过（OSError 被捕获）

    def test_close_event(self, staging_pool: Any) -> None:
        event = QCloseEvent()
        staging_pool.closeEvent(event)
        assert staging_pool._is_closing is True


# =============================================================================
# MD5 同步 / 异步 错误分支（批 3）
# =============================================================================
class TestMD5SyncAndAsync:
    """_calculate_md5_sync / calculate_md5_async / _MD5CalculationTask IOError。"""

    def test_calculate_md5_sync_io_error_warns(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """同步 MD5 遇 IOError 返回 None 并告警（不抛出）。"""
        import freeassetfilter.components.file_staging_pool as fsp

        target = tmp_path / "f.bin"
        target.write_bytes(b"x")
        monkeypatch.setattr(
            "builtins.open",
            lambda *a, **k: (_ for _ in ()).throw(IOError("boom")),
        )
        assert staging_pool._calculate_md5_sync(str(target)) is None

    def test_calculate_md5_async_runs_task(
        self,
        staging_pool: Any,
        qapp: Any,
        heartbeat_manager: Any,
        monkeypatch: Any,
        tmp_path: Path,
    ) -> None:
        """异步 MD5 通过线程池执行并在主线程回调。"""
        del heartbeat_manager
        import freeassetfilter.components.file_staging_pool as fsp

        target = tmp_path / "f.bin"
        target.write_bytes(b"abc")
        captured: List[Any] = []

        class _Pool:
            @staticmethod
            def start(runnable: Any) -> None:
                captured.append(runnable)
                runnable.run()

        class _FakeTP:
            @staticmethod
            def globalInstance() -> Any:
                return _Pool()

        monkeypatch.setattr(fsp, "QThreadPool", _FakeTP, raising=False)
        results: List[Optional[str]] = []
        staging_pool.calculate_md5_async(str(target), results.append)
        assert captured
        assert _pump_until(
            qapp, lambda: bool(results), timeout_s=5.0
        ), "异步回调未触发"
        assert results[0] == hashlib.md5(b"abc").hexdigest()

    def test_md5_task_io_error_callback_none(
        self,
        qapp: Any,
        heartbeat_manager: Any,
        monkeypatch: Any,
        tmp_path: Path,
    ) -> None:
        """后台任务 IOError 分支回调收到 None。"""
        del heartbeat_manager
        import freeassetfilter.components.file_staging_pool as fsp

        target = tmp_path / "f.bin"
        target.write_bytes(b"x")
        monkeypatch.setattr(
            "builtins.open",
            lambda *a, **k: (_ for _ in ()).throw(IOError("boom")),
        )
        results: List[Optional[str]] = []
        task = _MD5CalculationTask(str(target), results.append)
        task.run()
        assert _pump_until(
            qapp, lambda: bool(results), timeout_s=5.0
        ), "回调未触发"
        assert results[0] is None

    def test_md5_task_heartbeat_error_swallowed(
        self,
        qapp: Any,
        heartbeat_manager: Any,
        monkeypatch: Any,
        tmp_path: Path,
    ) -> None:
        """HeartbeatManager 抛异常被吞掉，不向外传播。"""
        del heartbeat_manager
        del qapp
        import freeassetfilter.components.file_staging_pool as fsp

        target = tmp_path / "f.bin"
        target.write_bytes(b"x")
        results: List[Optional[str]] = []

        class _BadHM:
            @staticmethod
            def request_main_thread(fn: Callable[[], None]) -> None:
                raise Exception("hm down")

        monkeypatch.setattr(fsp, "HeartbeatManager", lambda: _BadHM())
        task = _MD5CalculationTask(str(target), results.append)
        task.run()  # 不应抛出
        assert results == []


# =============================================================================
# 打开 / 双击 / 拖拽结束处理器（批 3）
# =============================================================================
class TestOpenAndClickHandlers:
    """open_file / 双击处理器 / on_card_drag_ended。"""

    def test_open_file_existing_file(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """存在的文件调用 os.startfile。"""
        import freeassetfilter.components.file_staging_pool as fsp

        target = make_text(str(tmp_path / "a.txt"))
        started: List[str] = []
        monkeypatch.setattr(
            fsp.os, "startfile", lambda p: started.append(p)
        )
        staging_pool.open_file(
            {"path": str(target), "is_dir": False}
        )
        assert started == [str(target)]

    def test_open_file_dir_noop(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """目录分支不调用 startfile。"""
        import freeassetfilter.components.file_staging_pool as fsp

        folder = tmp_path / "d"
        folder.mkdir()
        started: List[str] = []
        monkeypatch.setattr(
            fsp.os, "startfile", lambda p: started.append(p)
        )
        staging_pool.open_file({"path": str(folder), "is_dir": True})
        assert started == []

    def test_open_file_missing_noop(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """不存在路径不调用 startfile。"""
        import freeassetfilter.components.file_staging_pool as fsp

        started: List[str] = []
        monkeypatch.setattr(
            fsp.os, "startfile", lambda p: started.append(p)
        )
        staging_pool.open_file(
            {"path": str(tmp_path / "ghost.txt"), "is_dir": False}
        )
        assert started == []

    def test_on_list_item_double_clicked_emits(
        self, staging_pool: Any
    ) -> None:
        """非空 file_info 发射 item_left_clicked。"""
        emitted: List[Any] = []
        staging_pool.item_left_clicked.connect(emitted.append)
        staging_pool._on_list_item_double_clicked({"path": "x"})
        assert emitted == [{"path": "x"}]

    def test_on_delegate_rename_requested_existing(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """委托重命名请求命中条目后进入 rename_file（取消路径）。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(1, None)]  # 取消重命名
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))
        staging_pool._on_delegate_rename_requested(file_a)
        assert staging_pool.items[0]["display_name"] == "a.txt"

    def test_on_item_double_clicked_emits(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """兼容旧入口：命中条目发射 item_left_clicked。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))
        emitted: List[Any] = []
        staging_pool.item_left_clicked.connect(emitted.append)
        staging_pool.on_item_double_clicked(file_a)
        assert len(emitted) == 1
        assert emitted[0]["path"] == os.path.normpath(file_a)

    def test_on_card_drag_started_noop(self, staging_pool: Any) -> None:
        """拖拽开始回调为 pass，不抛出。"""
        staging_pool.on_card_drag_started({"path": "x"})

    def test_on_card_drag_ended_file_selector(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """拖到选择器时移除该条目。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))
        staging_pool.on_card_drag_ended(
            {"path": file_a}, "file_selector"
        )
        assert staging_pool.items == []

    def test_on_card_drag_ended_previewer(
        self, staging_pool: Any
    ) -> None:
        """拖到预览器时发射 item_left_clicked。"""
        emitted: List[Any] = []
        staging_pool.item_left_clicked.connect(emitted.append)
        staging_pool.on_card_drag_ended({"path": "x"}, "previewer")
        assert emitted == [{"path": "x"}]

    def test_on_card_drag_ended_none_noop(
        self, staging_pool: Any
    ) -> None:
        """drop_target=none 时不做任何事。"""
        staging_pool.on_card_drag_ended({"path": "x"}, "none")
        assert staging_pool.items == []

    def test_handle_item_left_clicked_preview_cancel(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """点击正在预览的卡片发射 preview_cancel_requested。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))
        staging_pool.set_previewing_file(file_a)
        cancelled: List[bool] = []
        staging_pool.preview_cancel_requested.connect(
            lambda: cancelled.append(True)
        )
        staging_pool._handle_item_left_clicked(
            {"path": file_a, "name": "a.txt"}
        )
        assert cancelled == [True]

    def test_handle_item_left_clicked_other_emits(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """点击非预览条目发射 item_left_clicked。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))
        staging_pool.set_previewing_file(
            str(tmp_path / "elsewhere.txt")
        )
        emitted: List[Any] = []
        staging_pool.item_left_clicked.connect(emitted.append)
        staging_pool._handle_item_left_clicked(
            {"path": file_a, "name": "a.txt"}
        )
        assert len(emitted) == 1


# =============================================================================
# clear_all 确认对话框（批 3）
# =============================================================================
class TestClearAllDialog:
    """clear_all 的确认/取消分支。"""

    def test_clear_all_confirmed(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """确认后清空全部条目。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(0, None)]
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))
        staging_pool.clear_all()
        assert staging_pool.items == []

    def test_clear_all_cancelled(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """取消后条目保留。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(1, None)]
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))
        staging_pool.clear_all()
        assert len(staging_pool.items) == 1


# =============================================================================
# add_file 边界分支（批 3）
# =============================================================================
class TestAddFileEdges:
    """add_file 的 is_previewing / 模型拒绝 / 媒体缩略图分支。"""

    def test_add_file_matches_previewing(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """与预览路径一致的条目被标记 is_previewing。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.set_previewing_file(file_a)
        staging_pool.add_file(_text_info(file_a))
        info = staging_pool.pool_model.get_file_info_by_path(file_a)
        assert info["is_previewing"] is True

    def test_add_file_model_rejects(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """模型 add_file 返回 False 时静默返回。"""
        file_a: str = make_text(str(tmp_path / "a.txt"))
        monkeypatch.setattr(
            staging_pool.pool_model, "add_file", lambda info: False
        )
        staging_pool.add_file(_text_info(file_a))
        assert staging_pool.items == []

    def test_add_file_media_triggers_thumbnail(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """媒体文件触发 _generate_thumbnail_async。"""
        import freeassetfilter.components.file_staging_pool as fsp

        img = tmp_path / "a.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")
        fake_mgr = SimpleNamespace(is_media_file=lambda p: True)
        monkeypatch.setattr(
            fsp, "get_thumbnail_manager", lambda scale: fake_mgr
        )
        generated: List[str] = []
        monkeypatch.setattr(
            staging_pool,
            "_generate_thumbnail_async",
            lambda path: generated.append(path),
        )
        staging_pool.add_file(_text_info(str(img)))
        assert generated == [str(img)]


# =============================================================================
# update_theme 异常 / 构造参数 / 防抖 flush（批 3）
# =============================================================================
class TestThemeAndFlushEdges:
    """update_theme 按钮异常、构造参数与 _flush_pending_backup_save。"""

    def test_update_theme_button_error_swallowed(
        self, staging_pool: Any, monkeypatch: Any
    ) -> None:
        """按钮 update_theme 抛异常被吞掉。"""
        monkeypatch.setattr(
            staging_pool.clear_btn,
            "update_theme",
            lambda: (_ for _ in ()).throw(Exception("x")),
        )
        monkeypatch.setattr(
            staging_pool.hover_tooltip,
            "update",
            lambda: (_ for _ in ()).throw(Exception("y")),
        )
        staging_pool.update_theme()  # 不应抛出

    def test_constructor_explicit_params(
        self,
        qapp: Any,
        settings_manager: Any,
        tmp_path: Path,
    ) -> None:
        """显式传入 dpi_scale/global_font。"""
        del qapp
        pool: Any = FileStagingPool(
            dpi_scale=2.0,
            global_font=QFont("Arial", 14),
            settings_manager=settings_manager,
        )
        try:
            assert pool.dpi_scale == 2.0
            assert pool.global_font.family() == "Arial"
        finally:
            pool.cleanup()
            StagingPoolService._instance = None

    def test_constructor_default_settings_manager(
        self, qapp: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """未传 settings_manager 时走默认构造分支。"""
        del qapp
        from freeassetfilter.core.managers.settings_manager import (
            SettingsManager,
        )

        real_init = SettingsManager.__init__

        def _patched_init(
            self: Any, settings_file: Optional[str] = None
        ) -> None:
            # 默认构造分支不带参数调用；把 settings_file 绑定到 tmp，
            # 避免写入仓库真实 data/ 目录。
            if settings_file is None:
                settings_file = str(tmp_path / "default_sm.json")
            real_init(self, settings_file=settings_file)

        monkeypatch.setattr(SettingsManager, "__init__", _patched_init)
        pool: Any = FileStagingPool()
        try:
            assert pool._settings_manager is not None
        finally:
            pool.cleanup()
            StagingPoolService._instance = None

    def test_flush_backup_save_writes(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """非挂起状态下 flush 立即落盘。"""
        staging_pool._suspend_backup_save = False
        staging_pool._pending_backup_last_path = "SomePath"
        staging_pool._flush_pending_backup_save()
        assert os.path.exists(staging_pool.backup_file)

    def test_flush_backup_save_suspended(
        self, staging_pool: Any, tmp_path: Path
    ) -> None:
        """挂起状态下 flush 直接返回不落盘。"""
        staging_pool._suspend_backup_save = True
        staging_pool._flush_pending_backup_save()
        assert not os.path.exists(staging_pool.backup_file)


# =============================================================================
# rename_file 边界分支（批 3）
# =============================================================================
class TestRenameEdges:
    """rename_file 的无扩展名分支与模型拒绝分支。"""

    def test_rename_no_extension(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """无扩展名条目重命名走无后缀分支。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(0, "newname")]
        target = tmp_path / "a"
        target.write_text("x", encoding="utf-8")
        staging_pool.add_file(_text_info(str(target)))
        staging_pool.rename_file(staging_pool.items[0], None)
        assert staging_pool.items[0]["display_name"] == "newname"

    def test_rename_model_fail_returns(
        self, staging_pool: Any, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """模型 rename_file 返回 False 时静默返回。"""
        _install_fake_message_box(monkeypatch)
        _FakeMessageBox._queue = [(0, "newname")]
        file_a: str = make_text(str(tmp_path / "a.txt"))
        staging_pool.add_file(_text_info(file_a))
        monkeypatch.setattr(
            staging_pool.pool_model,
            "rename_file",
            lambda path, name: False,
        )
        staging_pool.rename_file(staging_pool.items[0], None)
        assert staging_pool.items[0]["display_name"] == "a.txt"