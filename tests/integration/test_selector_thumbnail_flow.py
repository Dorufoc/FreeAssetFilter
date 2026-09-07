# -*- coding: utf-8 -*-
"""文件选择器缩略图端到端流程测试（spec Task 4 / test_selector_thumbnail_flow）。

验证 ``FileSelectorLayout``（ui/layout）+ ``ThumbnailController``（core/workers）
+ ``FileListModel.emit_icon_changed`` + ``FileIconManager`` 缩略图缓存键的
真实协作链路：

* 生成 → busy 态（生成按钮切入进度模式 ``set_progress`` 保持可点击、
  清除按钮禁用）→ ``files_ready`` 回填（模型收到
  ``dataChanged(IconPixmapRole)``、两文件 ``IconPixmapRole`` 各自回填
  为磁盘缩略图且**互不相等**——同后缀互串回归断言）→
  ``batch_finished`` 恢复按钮（退出进度模式）；
* 生成中点击 —— busy 窗口内再次点击「生成缩略图」→「继续生成 /
  取消任务」弹窗（阻塞替身管理器冻结 ``create_thumbnails_batch``
  构造确定性 busy 窗口，参考
  tests/unit/workers/test_thumbnail_controller.py）：「继续」不打断
  任务；「取消」释放互斥（``is_busy`` 归 False）、按钮恢复并弹取消
  通知；
* 清除确认框（真实 ``StyledDialog`` 非模态弹窗，``close_dialog(1)``
  模拟点击「清除」）→ ``clear_finished``（磁盘删除 + 全行刷新 + 结果
  通知 + 按钮恢复）；
* 选中优先 —— ``set_selected`` 某文件后生成仅覆盖该文件（另一文件无
  缩略图）；
* 无可生成项 —— 全部已有缩略图时再触发生成 → 同步
  ``batch_finished(0, 0)`` + 轻提示，不启动线程。

资源纪律（与既有 components 测试一致）：

* ``ThumbnailManager`` 单例的 ``_thumb_dir`` 重定向到 ``tmp_path/thumbs``
  （既有惯例，见 tests/integration/test_thumbnail_lifecycle.py），绝不触碰
  真实 appdata 缩略图目录；
* ``FileIconManager`` 缓存（含全局 ``QPixmapCache``）在每用例 setup 全清，
  避免跨用例 pixmap 污染；``SettingsManager`` 经 conftest
  ``settings_manager`` fixture 绑定临时设置文件；
* 所有等待有界（``_pump_until``，上限 15s），绝不 ``exec()`` 模态对话框、
  绝不裸 sleep 死等。
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, List, Tuple

import pytest
from PIL import Image
from PySide6.QtGui import QPixmap

# 布局模块内部使用短路径导入（from theme import tm / components.*），
# 要求 freeassetfilter/ui 位于 sys.path——与
# tests/unit/ui/layout/test_layouts.py 的 bootstrap 惯例一致。
_UI_ROOT: str = str(Path(__file__).resolve().parents[2] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.layout.file_selector_layout import FileSelectorLayout  # noqa: E402

# 与布局模块共享同一模块实例（components.* 短路径），IconPixmapRole 为 int
# 角色值，两处导入形式等价；此处取短路径以与被测接线保持一致。
from components.file_list_model import IconPixmapRole  # noqa: E402

from freeassetfilter.core.managers.thumbnail_manager import (  # noqa: E402
    get_existing_thumbnail_path,
)
import freeassetfilter.core.workers.thumbnail_controller as tc_module  # noqa: E402
from freeassetfilter.services.file_icon_manager import FileIconManager  # noqa: E402
from tests.support.qt_helpers import (  # noqa: E402
    assert_pixmap_nonempty,
    flush_widget_queue,
    safe_teardown,
)

pytestmark = pytest.mark.unit


# =============================================================================
# fixture / 公共辅助
# =============================================================================
@pytest.fixture
def thumb_env(tmp_path: Path) -> Any:
    """提供缩略图目录被隔离到临时目录的全新 ThumbnailManager 单例。

    conftest 的 ``reset_singletons`` autouse fixture 已归零
    ThumbnailManager 类级单例与模块级全局；这里重建并把 ``_thumb_dir``
    指向 ``tmp_path/thumbs``（真实 appdata 目录只在构造瞬间被 mkdir，
    不写入文件）。

    Args:
        tmp_path: pytest 内置每测试临时目录。

    Returns:
        Any: 绑定临时缓存目录的 ThumbnailManager 单例。
    """
    from freeassetfilter.core.managers.thumbnail_manager import (
        get_thumbnail_manager,
    )

    manager: Any = get_thumbnail_manager()
    thumb_dir: str = str(tmp_path / "thumbs")
    manager._thumb_dir = thumb_dir  # noqa: SLF001
    os.makedirs(thumb_dir, exist_ok=True)
    manager._clear_path_exists_cache()  # noqa: SLF001
    yield manager
    try:
        manager.clear_all_thumbnails()
    except Exception:  # noqa: BLE001 - teardown 幂等
        pass


@pytest.fixture
def selector(
    qapp: Any,
    settings_manager: Any,
    thumb_env: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """提供隔离的 FileSelectorLayout 实例（弹窗/信号记录已挂载）。

    构造前全清 FileIconManager 缓存（含全局 QPixmapCache），防止跨用例
    pixmap 污染；``_show_message_dialog`` 替换为记录器（避免真实弹窗
    堆积），控制器 batch/clear 信号与模型 dataChanged(IconPixmapRole)
    分别接入记录容器，经 ``layout._test_*`` 属性供用例断言。

    Args:
        qapp: 会话级 QApplication。
        settings_manager: 绑定临时设置文件的 SettingsManager。
        thumb_env: 缩略图目录已重定向的管理器单例。
        monkeypatch: pytest monkeypatch fixture。

    Returns:
        Any: 已挂载记录器的 FileSelectorLayout 实例。
    """
    FileIconManager().clear_cache()

    layout: Any = FileSelectorLayout()

    messages: List[Tuple[str, str]] = []
    batches: List[Tuple[int, int]] = []
    clears: List[int] = []
    icon_role_signals: List[Tuple[int, int]] = []

    monkeypatch.setattr(
        layout,
        "_show_message_dialog",
        lambda title, message: messages.append((title, message)),
    )
    layout._thumb_controller.batch_finished.connect(
        lambda success, processed: batches.append((success, processed))
    )
    layout._thumb_controller.clear_finished.connect(lambda count: clears.append(count))

    def _on_data_changed(top: Any, bottom: Any, roles: Any) -> None:
        if roles and IconPixmapRole in list(roles):
            icon_role_signals.append((top.row(), bottom.row()))

    layout._file_model.dataChanged.connect(_on_data_changed)

    # 测试观测挂载点（非产品属性）
    layout._test_messages = messages
    layout._test_batches = batches
    layout._test_clears = clears
    layout._test_icon_signals = icon_role_signals

    yield layout

    for dialog in list(getattr(layout, "_active_dialogs", [])):
        try:
            dialog.close_dialog(0)
        except Exception:  # noqa: BLE001 - teardown 兜底
            pass
    flush_widget_queue(qapp, iterations=5)
    safe_teardown(layout)


def _pump_until(
    qapp: Any,
    predicate: Callable[[], bool],
    timeout_s: float = 15.0,
) -> bool:
    """在截止期内轮询冲刷 Qt 事件直到谓词满足（有界，绝不无限等待）。

    Args:
        qapp: 会话级 QApplication 实例。
        predicate: 目标状态谓词。
        timeout_s: 最长等待秒数。

    Returns:
        bool: 谓词在超时前满足返回 True，否则 False。
    """
    deadline: float = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return bool(predicate())


def _make_solid_png(path: Path, rgb: Tuple[int, int, int]) -> str:
    """生成一张纯色 PNG（互串回归断言需要内容可区分的图片）。

    Args:
        path: 输出路径（含 .png 扩展名）。
        rgb: 纯色 RGB 三元组。

    Returns:
        str: 生成后的 PNG 文件路径。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), rgb).save(path, format="PNG")
    return str(path)


def _load_dir_into_model(layout: Any, dir_path: str) -> List[str]:
    """用产品真实的目录收集逻辑加载文件列表到模型。

    经 ``FileSelectorLayout._collect_directory_entries``（纯 IO 静态方法）
    收集条目后 ``set_files`` 填充模型——与生产链路同源，且避免
    ``_load_directory`` 的网格重算副作用。

    Args:
        layout: FileSelectorLayout 实例。
        dir_path: 待加载的目录路径。

    Returns:
        List[str]: 模型内的文件路径列表。
    """
    entries = FileSelectorLayout._collect_directory_entries(dir_path)
    assert entries is not None, f"目录收集失败: {dir_path}"
    layout._file_model.set_files(entries)
    return [entry["path"] for entry in entries]


class _BlockingBatchManager:
    """替身 ThumbnailManager：``create_thumbnails_batch`` 阻塞至事件释放。

    参考 tests/unit/workers/test_thumbnail_controller.py 的同名替身，
    用于确定性构造「生成进行中」busy 窗口（生成中点击弹窗测试）：
    本文件仅单调用场景，事件语义从简——单事件 + 完成标记。
    """

    def __init__(self) -> None:
        """初始化阻塞事件与完成标记。"""
        self._event = threading.Event()
        self.completed: bool = False

    def create_thumbnails_batch(
        self,
        file_paths: List[str],
        progress_callback: Any = None,
        cancel_check: Any = None,
    ) -> Tuple[int, int]:
        """阻塞版批量生成：等待释放事件后返回全成功统计。

        Args:
            file_paths: 待生成文件路径列表（原样接收）。
            progress_callback: 进度回调（替身不调用）。
            cancel_check: 取消检查（替身不调用）。

        Returns:
            Tuple[int, int]: (成功数, 已处理数)，均等于输入长度。
        """
        del progress_callback, cancel_check
        # 有界等待：即使测试逻辑提前失败，线程也能自行退出
        self._event.wait(timeout=10.0)
        self.completed = True
        return len(file_paths), len(file_paths)

    def release(self) -> None:
        """释放阻塞事件（teardown 兜底）。"""
        self._event.set()


# =============================================================================
# 生成 → 回填 → 清除 全链路
# =============================================================================
class TestThumbnailFullChain:
    """生成 → 显示回填 → 清除 → 恢复的端到端链路。"""

    def test_generate_backfill_and_clear_full_chain(
        self, selector: Any, qapp: Any, tmp_path: Path
    ) -> None:
        """全链路：生成回填（含互串回归）→ busy 恢复 → 确认清除 → 恢复。

        Args:
            selector: 已挂载记录器的 FileSelectorLayout。
            qapp: 会话级 QApplication。
            tmp_path: pytest 内置临时目录。
        """
        src_dir: Path = tmp_path / "src"
        src_dir.mkdir()
        red_path: str = _make_solid_png(src_dir / "red.png", (255, 0, 0))
        blue_path: str = _make_solid_png(src_dir / "blue.png", (0, 0, 255))
        paths: List[str] = _load_dir_into_model(selector, str(src_dir))
        assert set(paths) == {red_path, blue_path}
        model: Any = selector._file_model
        assert model.rowCount() == 2

        # 初始无缩略图
        assert get_existing_thumbnail_path(red_path) is None
        assert get_existing_thumbnail_path(blue_path) is None

        # ── 生成（无选中 → 全目录）──
        selector._on_generate_thumbnails()

        # busy 态：恢复槽为排队连接（工作线程发射），不泵事件就不可能执行，
        # 因此以下断言与任务完成时序解耦、确定性成立
        assert selector._gen_thumb_btn.isEnabled(), (
            "生成期间生成按钮应保持可用（进度模式可点击弹窗）"
        )
        assert not selector._clean_btn.isEnabled(), "生成期间清除按钮应禁用"
        assert selector._gen_thumb_btn.progress() is not None, (
            "生成期间生成按钮应处于进度模式"
        )

        assert _pump_until(
            qapp,
            lambda: bool(selector._test_batches)
            and not selector._thumb_controller.is_busy,
        ), "生成任务超时未完成"
        assert selector._test_batches == [(2, 2)]
        assert selector._test_messages == [], "正常生成不应弹任何提示"

        # 缩略图磁盘文件已生成
        red_thumb = get_existing_thumbnail_path(red_path)
        blue_thumb = get_existing_thumbnail_path(blue_path)
        assert red_thumb is not None and os.path.exists(red_thumb)
        assert blue_thumb is not None and os.path.exists(blue_thumb)

        # 模型收到 dataChanged(IconPixmapRole)（files_ready 回填入口）
        assert selector._test_icon_signals, "模型未收到 IconPixmapRole dataChanged"

        # IconPixmapRole 回填为各自的磁盘缩略图，且互不相等（互串回归断言：
        # 缩略图缓存键含路径，同后缀不同内容文件不得共用同一 pixmap）
        row_red: int = model.get_row(red_path)
        row_blue: int = model.get_row(blue_path)
        pm_red: Any = model.data(model.index(row_red, 0), IconPixmapRole)
        pm_blue: Any = model.data(model.index(row_blue, 0), IconPixmapRole)
        assert_pixmap_nonempty(pm_red, "red.png 应回填非空缩略图")
        assert_pixmap_nonempty(pm_blue, "blue.png 应回填非空缩略图")
        assert pm_red.toImage() != pm_blue.toImage(), (
            "同后缀两文件的缩略图互串（回归）：IconPixmapRole 返回了同一 pixmap"
        )
        assert pm_red.toImage() == QPixmap(red_thumb).toImage(), (
            "red.png 的 IconPixmapRole 未回填为磁盘缩略图"
        )
        assert pm_blue.toImage() == QPixmap(blue_thumb).toImage(), (
            "blue.png 的 IconPixmapRole 未回填为磁盘缩略图"
        )

        # 按钮恢复（退出进度模式 + 双按钮可用 + 默认文案）
        assert selector._gen_thumb_btn.isEnabled()
        assert selector._clean_btn.isEnabled()
        assert selector._gen_thumb_btn.text() == "生成缩略图"
        assert selector._gen_thumb_btn.progress() is None

        # ── 清除（真实确认框 + close_dialog(1) 模拟确认）──
        selector._test_icon_signals.clear()
        selector._on_clear_thumbnails()
        confirm_dialog: Any = selector._active_dialogs[-1]
        assert confirm_dialog.windowTitle() == "清除缩略图"
        assert not selector._thumb_controller.is_busy, "确认框期间不应启动任务"

        confirm_dialog.close_dialog(1)  # 退场动画后触发 finished(1)
        assert _pump_until(qapp, lambda: bool(selector._test_clears)), (
            "清除任务超时未完成"
        )

        assert selector._test_clears == [2]
        assert get_existing_thumbnail_path(red_path) is None, "red.png 缩略图未删除"
        assert get_existing_thumbnail_path(blue_path) is None, "blue.png 缩略图未删除"
        assert selector._test_icon_signals, "清除后未全行刷新图标"
        assert any(
            title == "清除缩略图" and "已清除 2" in message
            for title, message in selector._test_messages
        ), f"未弹清除结果通知: {selector._test_messages}"
        assert selector._gen_thumb_btn.isEnabled()
        assert selector._clean_btn.isEnabled()
        assert selector._gen_thumb_btn.text() == "生成缩略图"
        assert not selector._thumb_controller.is_busy


# =============================================================================
# 选中优先
# =============================================================================
class TestSelectionPriority:
    """``_collect_thumbnail_targets`` 的选中优先语义。"""

    def test_selected_file_generation_priority(
        self, selector: Any, qapp: Any, tmp_path: Path
    ) -> None:
        """选中某文件后生成 → 仅该文件产出缩略图，另一文件无。

        Args:
            selector: 已挂载记录器的 FileSelectorLayout。
            qapp: 会话级 QApplication。
            tmp_path: pytest 内置临时目录。
        """
        src_dir: Path = tmp_path / "src"
        src_dir.mkdir()
        red_path: str = _make_solid_png(src_dir / "red.png", (255, 0, 0))
        blue_path: str = _make_solid_png(src_dir / "blue.png", (0, 0, 255))
        _load_dir_into_model(selector, str(src_dir))

        assert selector._file_model.set_selected(red_path, True) is True

        selector._on_generate_thumbnails()
        assert _pump_until(
            qapp,
            lambda: bool(selector._test_batches)
            and not selector._thumb_controller.is_busy,
        ), "选中生成任务超时未完成"

        assert selector._test_batches == [(1, 1)]
        assert get_existing_thumbnail_path(red_path) is not None, "选中文件应有缩略图"
        assert get_existing_thumbnail_path(blue_path) is None, "未选中文件不应有缩略图"


# =============================================================================
# 无可生成项（空任务轻提示）
# =============================================================================
class TestEmptyTaskHint:
    """全部已有缩略图时的空任务短路路径。"""

    def test_all_cached_triggers_hint_without_thread(
        self, selector: Any, qapp: Any, tmp_path: Path
    ) -> None:
        """全部已有缩略图再触发生成 → 同步 (0,0) + 轻提示，不启动线程。

        Args:
            selector: 已挂载记录器的 FileSelectorLayout。
            qapp: 会话级 QApplication。
            tmp_path: pytest 内置临时目录。
        """
        src_dir: Path = tmp_path / "src"
        src_dir.mkdir()
        red_path: str = _make_solid_png(src_dir / "red.png", (255, 0, 0))
        blue_path: str = _make_solid_png(src_dir / "blue.png", (0, 0, 255))
        _load_dir_into_model(selector, str(src_dir))

        # 第一轮：全目录生成到位
        selector._on_generate_thumbnails()
        assert _pump_until(
            qapp,
            lambda: bool(selector._test_batches)
            and not selector._thumb_controller.is_busy,
        ), "首轮生成任务超时未完成"
        assert selector._test_batches == [(2, 2)]
        selector._test_batches.clear()
        selector._test_messages.clear()

        # 第二轮：全部已有缩略图 → 空任务同步短路
        selector._on_generate_thumbnails()
        assert selector._test_batches == [(0, 0)], (
            "空任务应在 start_generation 返回前同步收到 batch_finished(0, 0)"
        )
        assert not selector._thumb_controller.is_busy
        # 未启动后台线程（retired refs 为空）
        assert not selector._thumb_controller._worker_threads  # noqa: SLF001
        assert any(
            title == "生成缩略图" and "均已有缩略图" in message
            for title, message in selector._test_messages
        ), f"未弹空任务轻提示: {selector._test_messages}"
        assert selector._gen_thumb_btn.isEnabled()
        assert selector._clean_btn.isEnabled()
        assert selector._gen_thumb_btn.text() == "生成缩略图"
        # 空任务短路路径经 _set_thumbnail_buttons_busy(False) 恢复——
        # 该路径同时负责退出进度模式（兼容性断言）
        assert selector._gen_thumb_btn.progress() is None


# =============================================================================
# 生成中点击弹窗（继续 / 取消）
# =============================================================================
class TestBusyClickDialog:
    """生成进行中再次点击「生成缩略图」→「继续生成 / 取消任务」弹窗。"""

    def test_generate_click_while_busy_shows_continue_or_cancel(
        self,
        selector: Any,
        qapp: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """busy 窗口内再次点击 → 弹窗；「继续」不打断，「取消」中止并恢复。

        用阻塞替身管理器（``_BlockingBatchManager``）冻结
        ``create_thumbnails_batch`` 收尾，确定性构造 busy 窗口：第一次
        弹窗选「继续生成」（``close_dialog(0)``）断言任务未被取消；
        第二次弹窗选「取消任务」（``close_dialog(1)``）断言互斥释放、
        按钮恢复（退出进度模式 + 双按钮可用）并弹取消通知。

        Args:
            selector: 已挂载记录器的 FileSelectorLayout。
            qapp: 会话级 QApplication。
            tmp_path: pytest 内置临时目录。
            monkeypatch: pytest monkeypatch fixture。
        """
        src_dir: Path = tmp_path / "src"
        src_dir.mkdir()
        _make_solid_png(src_dir / "red.png", (255, 0, 0))
        _make_solid_png(src_dir / "blue.png", (0, 0, 255))
        _load_dir_into_model(selector, str(src_dir))

        fake = _BlockingBatchManager()
        # 仅替换 controller 模块命名空间内的管理器桥接（运行时查找），
        # 收集过滤沿用真实 is_media_file / has_thumbnail（PNG 均命中）
        monkeypatch.setattr(
            tc_module, "get_thumbnail_manager", lambda *a, **k: fake
        )
        try:
            # ── 启动生成：阻塞替身冻结收尾，进入确定性 busy 窗口 ──
            selector._on_generate_thumbnails()
            assert selector._thumb_controller.is_busy
            assert selector._gen_thumb_btn.isEnabled(), (
                "生成中按钮应保持可点击（弹窗入口）"
            )
            assert selector._gen_thumb_btn.progress() is not None, (
                "生成中按钮应处于进度模式"
            )
            assert not selector._clean_btn.isEnabled()

            # ── busy 内第一次点击：弹出「继续生成 / 取消任务」对话框 ──
            selector._on_generate_thumbnails()
            dialog: Any = selector._active_dialogs[-1]
            assert dialog.windowTitle() == "缩略图生成中"

            # 选「继续生成」：finished(0) 不触发取消，任务继续阻塞执行
            finished_results: List[int] = []
            dialog.finished.connect(lambda result: finished_results.append(result))
            dialog.close_dialog(0)
            assert _pump_until(qapp, lambda: bool(finished_results)), (
                "「继续生成」弹窗未完成退场"
            )
            assert finished_results == [0]
            assert selector._thumb_controller.is_busy, (
                "「继续生成」不应取消当前任务"
            )
            assert not any(
                "已取消" in message for _, message in selector._test_messages
            ), f"「继续生成」不应弹取消通知: {selector._test_messages}"

            # ── busy 内第二次点击：选「取消任务」──
            selector._on_generate_thumbnails()
            cancel_dialog: Any = selector._active_dialogs[-1]
            cancel_dialog.close_dialog(1)
            assert _pump_until(
                qapp, lambda: not selector._thumb_controller.is_busy
            ), "「取消任务」未释放互斥"

            # 取消后：按钮恢复（退出进度模式 + 双按钮可用 + 默认文案）
            # + 取消通知弹出
            assert selector._gen_thumb_btn.progress() is None
            assert selector._gen_thumb_btn.isEnabled()
            assert selector._clean_btn.isEnabled()
            assert selector._gen_thumb_btn.text() == "生成缩略图"
            assert any(
                title == "缩略图" and "已取消缩略图生成任务" in message
                for title, message in selector._test_messages
            ), f"未弹取消通知: {selector._test_messages}"
        finally:
            # 释放阻塞替身并泵事件，让旧线程在布局销毁前完成收尾
            # （取消后世代 token 仍有效，迟到的 batch_finished 仅触发
            # 幂等的按钮恢复）
            fake.release()
            _pump_until(qapp, lambda: fake.completed, timeout_s=3.0)
