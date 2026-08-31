# -*- coding: utf-8 -*-
"""``ThumbnailController``（core/workers/thumbnail_controller.py）单元测试。

覆盖（spec Task 4，happy + boundary/error 各至少一条）：

* 依赖边界 —— ``ThumbnailController`` 可从
  ``freeassetfilter.core.workers.thumbnail_controller`` 导入且文件位于
  core/workers 分层路径下；controller / 布局接线 / 模型三处源码均不依赖
  ``freeassetfilter.components`` 与 ``freeassetfilter.widgets``（分层断言，
  读源码字符串，简单可靠）；
* 收集过滤与去重 —— 非媒体列表 → 空任务同步 ``batch_finished(0, 0)``
  （不启动线程、无 ``files_ready``）；混合列表（媒体 + 非媒体 + 已有
  缩略图的媒体 + 重复项）→ 仅对无缩略图的媒体文件生成；
* 真实生成信号 —— 2 张 PIL 生成的 PNG → ``files_ready`` 携带就绪文件、
  ``batch_finished(2, 2)``、缩略图磁盘文件真实落盘；
* ``is_busy`` 互斥 —— 生成进行中 ``start_generation`` / ``start_clear``
  均返回 False（用阻塞替身管理器冻结任务收尾，确定性构造 busy 窗口），
  任务结束后互斥释放；
* token 过期丢弃 —— ``cancel()`` 释放互斥允许立即启动新任务；旧任务的
  收尾统计因世代 token 失效被丢弃，仅新任务的 ``batch_finished`` 到达；
* 清除任务 —— ``start_clear`` → ``clear_finished(删除数)`` → 缩略图
  磁盘文件被真实删除。

资源纪律：ThumbnailManager 单例的 ``_thumb_dir`` 重定向到
``tmp_path/thumbs``（既有惯例，见 test_thumbnail_lifecycle.py），绝不触碰
真实 appdata 缩略图目录；所有等待有界（``_pump_until``，上限 10s），
绝不裸 wait / 死等。
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

import pytest

import freeassetfilter.core.workers.thumbnail_controller as tc_module
from freeassetfilter.core.workers.thumbnail_controller import ThumbnailController
from tests.support.data_factories import make_image, make_text

pytestmark = pytest.mark.unit

#: 项目根目录（tests/unit/workers/test_x.py → parents[3]）。
_PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

#: 依赖边界断言覆盖的被测源文件（相对项目根）。
_BOUNDARY_SOURCE_RELPATHS: List[str] = [
    "freeassetfilter/core/workers/thumbnail_controller.py",
    "freeassetfilter/ui/layout/file_selector_layout.py",
    "freeassetfilter/ui/components/file_list_model.py",
]

#: 分层边界禁止出现的导入前缀（UI 层不得反向依赖 components/widgets 包）。
_FORBIDDEN_IMPORT_PREFIXES: Tuple[str, ...] = (
    "from freeassetfilter.components",
    "from freeassetfilter.widgets",
)


# =============================================================================
# fixture / 公共辅助
# =============================================================================
@pytest.fixture
def thumb_env(tmp_path: Path) -> Any:
    """提供缩略图目录被隔离到临时目录的全新 ThumbnailManager 单例。

    遵循既有惯例（test_thumbnail_manager.py / test_thumbnail_lifecycle.py）：
    conftest 的 ``reset_singletons`` autouse fixture 已在本 fixture 之前归零
    单例，这里重建并把 ``_thumb_dir`` 指向 ``tmp_path/thumbs``，保证用例
    间零环境污染（真实 appdata 缩略图目录只在构造瞬间被 mkdir，不写入
    文件）。

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


class _SignalLog:
    """信号收集器：记录控制器的全部信号发射载荷。"""

    def __init__(self, controller: ThumbnailController) -> None:
        """连接控制器的 5 个信号并初始化记录容器。

        Args:
            controller: 被测控制器实例。
        """
        self.progress: List[Tuple[int, int]] = []
        self.ready: List[str] = []
        self.batch: List[Tuple[int, int]] = []
        self.clear: List[int] = []
        self.failed: List[str] = []
        controller.progress_emitted.connect(
            lambda done, total: self.progress.append((done, total))
        )
        controller.files_ready.connect(
            lambda file_paths: self.ready.extend(file_paths)
        )
        controller.batch_finished.connect(
            lambda success, processed: self.batch.append((success, processed))
        )
        controller.clear_finished.connect(lambda count: self.clear.append(count))
        controller.failed.connect(lambda message: self.failed.append(message))


class _BlockingBatchManager:
    """替身 ThumbnailManager：``create_thumbnails_batch`` 阻塞至事件释放。

    用于确定性构造"生成进行中"的 busy 窗口（互斥与取消语义测试）：
    每次调用登记一个 ``threading.Event``，测试线程按调用内容精确释放
    （``release_call``），从而完全掌控任务完成时机。
    """

    def __init__(self) -> None:
        """初始化调用登记表与完成记录。"""
        self._lock = threading.Lock()
        self._calls: List[Tuple[str, ...]] = []
        self._events: List[threading.Event] = []
        self.completed: List[Tuple[str, ...]] = []

    def create_thumbnails_batch(
        self,
        file_paths: List[str],
        progress_callback: Optional[Callable[..., None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Tuple[int, int]:
        """阻塞版批量生成：等待对应释放事件后返回全成功统计。

        Args:
            file_paths: 待生成文件路径列表（原样接收）。
            progress_callback: 进度回调（替身不调用）。
            cancel_check: 取消检查（替身不调用）。

        Returns:
            Tuple[int, int]: (成功数, 已处理数)，均等于输入长度。
        """
        del progress_callback, cancel_check
        key: Tuple[str, ...] = tuple(file_paths)
        event = threading.Event()
        with self._lock:
            self._calls.append(key)
            self._events.append(event)
        # 有界等待：即使测试逻辑提前失败，线程也能自行退出
        event.wait(timeout=10.0)
        with self._lock:
            self.completed.append(key)
        return len(file_paths), len(file_paths)

    def release_call(self, file_paths: List[str]) -> None:
        """释放指定调用内容的阻塞事件。

        Args:
            file_paths: 当初传给 ``create_thumbnails_batch`` 的路径列表。

        Raises:
            AssertionError: 找不到对应调用（调用尚未发生）。
        """
        key: Tuple[str, ...] = tuple(file_paths)
        with self._lock:
            for call, event in zip(self._calls, self._events):
                if call == key:
                    event.set()
                    return
        raise AssertionError(f"未找到待释放的批量调用: {file_paths}")

    def release_all(self) -> None:
        """释放全部阻塞事件（teardown 兜底）。"""
        with self._lock:
            for event in self._events:
                event.set()

    def call_completed(self, file_paths: List[str]) -> bool:
        """判断指定调用是否已从 ``create_thumbnails_batch`` 返回。

        Args:
            file_paths: 当初传给 ``create_thumbnails_batch`` 的路径列表。

        Returns:
            bool: 已返回返回 True。
        """
        return tuple(file_paths) in self.completed


def _patch_controller_bridge(
    monkeypatch: pytest.MonkeyPatch,
    fake_manager: _BlockingBatchManager,
    patch_clear: bool = False,
) -> None:
    """把 controller 模块内的管理器桥接函数替换为可控替身。

    仅替换 ``thumbnail_controller`` 模块命名空间中的符号（controller 的
    全部管理器交互都经由该命名空间），不影响真实 ThumbnailManager。

    Args:
        monkeypatch: pytest monkeypatch fixture。
        fake_manager: 阻塞替身管理器。
        patch_clear: 是否同时替换 ``clear_all_thumbnails``（清除路径测试点）。
    """
    monkeypatch.setattr(
        tc_module, "get_thumbnail_manager", lambda *a, **k: fake_manager
    )
    monkeypatch.setattr(tc_module, "is_media_file", lambda file_path: True)
    monkeypatch.setattr(tc_module, "has_thumbnail", lambda file_path: False)
    if patch_clear:
        monkeypatch.setattr(tc_module, "clear_all_thumbnails", lambda: 0)


def _pump_until(
    qapp: Any,
    predicate: Callable[[], bool],
    timeout_s: float = 10.0,
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


# =============================================================================
# 依赖边界断言（spec Task 4 文件 3，并入本文件）
# =============================================================================
class TestDependencyBoundaries:
    """分层与依赖边界断言。"""

    def test_controller_importable_from_core_workers_layer(self) -> None:
        """ThumbnailController 可从 core.workers 分层路径导入且文件位置正确。"""
        import inspect

        module_path: str = inspect.getfile(tc_module)
        parts: List[str] = Path(module_path).parts
        assert tc_module.ThumbnailController is ThumbnailController
        assert "freeassetfilter" in parts
        assert "core" in parts
        assert "workers" in parts
        assert Path(module_path).name == "thumbnail_controller.py"

    @pytest.mark.parametrize("relpath", _BOUNDARY_SOURCE_RELPATHS)
    def test_sources_avoid_component_and_widget_imports(self, relpath: str) -> None:
        """被测三处源码不得依赖 freeassetfilter.components / widgets 包。

        Args:
            relpath: 相对项目根的被测源文件路径。
        """
        source_path: Path = _PROJECT_ROOT / relpath
        assert source_path.is_file(), f"被测源文件不存在: {source_path}"
        source: str = source_path.read_text(encoding="utf-8")
        for prefix in _FORBIDDEN_IMPORT_PREFIXES:
            assert prefix not in source, (
                f"{relpath} 出现分层越界导入: {prefix}"
            )


# =============================================================================
# 收集过滤与去重
# =============================================================================
class TestStartGenerationFiltering:
    """``start_generation`` 收集阶段的媒体过滤、去重与空任务短路。"""

    def test_non_media_paths_yield_empty_batch_synchronously(
        self, thumb_env: Any, tmp_path: Path
    ) -> None:
        """boundary：纯非媒体列表 → 空任务同步 batch_finished(0,0)，不启动线程。

        Args:
            thumb_env: 缩略图目录已重定向的管理器单例。
            tmp_path: pytest 内置临时目录。
        """
        controller = ThumbnailController()
        log = _SignalLog(controller)

        txt: str = make_text(tmp_path / "notes.txt")
        md: str = str(tmp_path / "readme.md")

        assert controller.start_generation([txt, md]) is True
        # 空任务路径：start_generation 返回前已同步发射 batch_finished(0, 0)
        assert log.batch == [(0, 0)]
        assert log.ready == []
        assert log.progress == []
        assert log.failed == []
        assert controller.is_busy is False

    def test_mixed_paths_generate_only_pending_media(
        self, thumb_env: Any, tmp_path: Path, qapp: Any
    ) -> None:
        """happy：混合列表仅对无缩略图的媒体文件生成（去重 + 双重过滤）。

        输入 = [无缩略图媒体, 非媒体, 已有缩略图媒体, 重复的无缩略图媒体]，
        期望仅第一个文件被生成：``batch_finished == (1, 1)``、
        ``files_ready`` 恰含该文件。

        Args:
            thumb_env: 缩略图目录已重定向的管理器单例。
            tmp_path: pytest 内置临时目录。
            qapp: 会话级 QApplication。
        """
        pending_png: str = make_image(tmp_path / "pending.png", fmt="PNG")
        txt_path: str = make_text(tmp_path / "notes.txt")
        cached_png: str = make_image(tmp_path / "cached.png", fmt="PNG")
        # 预生成 cached.png 的缩略图（真实 PIL 生成），使其命中 has_thumbnail
        pre_thumb: Optional[str] = thumb_env.create_thumbnail(cached_png)
        assert pre_thumb is not None and os.path.exists(pre_thumb)

        controller = ThumbnailController()
        log = _SignalLog(controller)

        assert (
            controller.start_generation(
                [pending_png, txt_path, cached_png, pending_png]
            )
            is True
        )
        assert _pump_until(
            qapp, lambda: bool(log.batch) and not controller.is_busy
        ), "混合列表生成任务超时未完成"
        assert log.batch == [(1, 1)]
        assert log.ready == [pending_png]
        assert log.failed == []
        after_thumb: Optional[str] = thumb_env.get_existing_thumbnail_path(pending_png)
        assert after_thumb is not None and os.path.exists(after_thumb)


# =============================================================================
# 真实生成信号
# =============================================================================
class TestGenerationSignals:
    """真实 PIL 图片批量生成的信号发射与磁盘落盘。"""

    def test_real_generation_emits_ready_and_finished(
        self, thumb_env: Any, tmp_path: Path, qapp: Any
    ) -> None:
        """happy：2 张真实 PNG → files_ready 携带文件 + batch_finished(2,2) + 落盘。

        Args:
            thumb_env: 缩略图目录已重定向的管理器单例。
            tmp_path: pytest 内置临时目录。
            qapp: 会话级 QApplication。
        """
        png_a: str = make_image(tmp_path / "signal_a.png", fmt="PNG")
        png_b: str = make_image(tmp_path / "signal_b.png", fmt="PNG")

        controller = ThumbnailController()
        log = _SignalLog(controller)
        assert controller.is_busy is False

        assert controller.start_generation([png_a, png_b]) is True
        assert _pump_until(
            qapp, lambda: bool(log.batch) and not controller.is_busy
        ), "生成任务超时未完成"

        assert log.batch == [(2, 2)]
        assert sorted(log.ready) == sorted([png_a, png_b])
        assert log.failed == []
        for file_path in (png_a, png_b):
            thumb_path: Optional[str] = thumb_env.get_existing_thumbnail_path(
                file_path
            )
            assert thumb_path is not None, f"缩略图磁盘文件缺失: {file_path}"
            assert os.path.exists(thumb_path)
        assert controller.is_busy is False


# =============================================================================
# is_busy 互斥
# =============================================================================
class TestBusyMutex:
    """生成 / 清除互斥语义（阻塞替身确定性构造 busy 窗口）。"""

    def test_start_rejected_while_busy_and_released_after_finish(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """生成进行中 start_* 均返回 False；任务结束后互斥释放。

        用阻塞替身管理器冻结生成任务收尾，在确定性的 busy 窗口内断言：
        二次 ``start_generation`` 返回 False、``start_clear`` 返回 False；
        释放后 ``batch_finished`` 到达、``is_busy`` 归 False，随后
        ``start_clear`` 被接受（清除函数同样替换为替身，不触碰磁盘）。

        Args:
            qapp: 会话级 QApplication。
            monkeypatch: pytest monkeypatch fixture。
        """
        fake = _BlockingBatchManager()
        _patch_controller_bridge(monkeypatch, fake, patch_clear=True)
        try:
            controller = ThumbnailController()
            log = _SignalLog(controller)

            assert controller.start_generation(["Z:/fake/a.png"]) is True
            assert controller.is_busy is True
            # busy 窗口内：生成与清除互斥，均被拒绝
            assert controller.start_generation(["Z:/fake/b.png"]) is False
            assert controller.start_clear() is False
            assert log.batch == []

            fake.release_all()
            assert _pump_until(
                qapp, lambda: bool(log.batch) and not controller.is_busy
            ), "阻塞生成任务释放后未完成"
            assert log.batch == [(1, 1)]

            # 互斥已释放：清除任务可被接受（替身清除立即返回 0）
            assert controller.start_clear() is True
            assert _pump_until(qapp, lambda: bool(log.clear)), "清除任务超时"
            assert log.clear == [0]
            assert controller.is_busy is False
            assert log.failed == []
        finally:
            fake.release_all()


# =============================================================================
# cancel 与世代 token
# =============================================================================
class TestCancelSemantics:
    """``cancel()`` 的互斥释放与过期 token 事件丢弃。"""

    def test_cancel_releases_mutex_and_stale_events_discarded(
        self, qapp: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cancel 后立即可启动新任务，旧任务收尾统计被世代 token 丢弃。

        流程：任务 A（2 文件）阻塞中 → ``cancel()`` 释放互斥 → 立即启动
        任务 B（3 文件）成功 → 释放 A：A 的 ``batch_finished`` 被丢弃 →
        释放 B：仅收到 B 的 ``batch_finished(3, 3)``。

        Args:
            qapp: 会话级 QApplication。
            monkeypatch: pytest monkeypatch fixture。
        """
        fake = _BlockingBatchManager()
        _patch_controller_bridge(monkeypatch, fake)
        try:
            controller = ThumbnailController()
            log = _SignalLog(controller)

            paths_a: List[str] = ["Z:/fake/old_1.png", "Z:/fake/old_2.png"]
            paths_b: List[str] = [
                "Z:/fake/new_1.png",
                "Z:/fake/new_2.png",
                "Z:/fake/new_3.png",
            ]

            assert controller.start_generation(paths_a) is True
            assert controller.is_busy is True

            # cancel：互斥立即释放（允许新任务），旧线程仍在替身中阻塞
            controller.cancel()
            assert controller.is_busy is False

            # 关键断言：cancel 后无需等待旧线程即可启动新任务
            assert controller.start_generation(paths_b) is True
            assert controller.is_busy is True

            # 释放旧任务 A：其收尾事件（batch_finished(2,2)）必须被丢弃
            fake.release_call(paths_a)
            assert _pump_until(qapp, lambda: fake.call_completed(paths_a)), (
                "旧任务 A 未在释放后完成"
            )
            # 短暂结算泵：给旧线程执行 token 比对的机会
            assert _pump_until(qapp, lambda: False, timeout_s=0.3) is False
            assert log.batch == [], f"旧任务的收尾统计未被丢弃: {log.batch}"

            # 释放新任务 B：仅 B 的统计到达
            fake.release_call(paths_b)
            assert _pump_until(
                qapp, lambda: bool(log.batch) and not controller.is_busy
            ), "新任务 B 超时未完成"
            assert log.batch == [(3, 3)]
            assert log.failed == []
            assert controller.is_busy is False
        finally:
            fake.release_all()


# =============================================================================
# 清除任务
# =============================================================================
class TestClearTask:
    """``start_clear`` 的磁盘删除与 ``clear_finished`` 信号。"""

    def test_clear_removes_thumbnail_files_and_emits_count(
        self, thumb_env: Any, tmp_path: Path, qapp: Any
    ) -> None:
        """happy：start_clear → clear_finished(删除数) → 缩略图文件被删。

        Args:
            thumb_env: 缩略图目录已重定向的管理器单例。
            tmp_path: pytest 内置临时目录。
            qapp: 会话级 QApplication。
        """
        png_path: str = make_image(tmp_path / "to_clear.png", fmt="PNG")
        thumb_path: Optional[str] = thumb_env.create_thumbnail(png_path)
        assert thumb_path is not None and os.path.exists(thumb_path)

        controller = ThumbnailController()
        log = _SignalLog(controller)
        assert controller.start_clear() is True
        assert _pump_until(
            qapp, lambda: bool(log.clear) and not controller.is_busy
        ), "清除任务超时未完成"

        assert log.clear == [1]
        assert not os.path.exists(thumb_path)
        assert thumb_env.get_existing_thumbnail_path(png_path) is None
        assert log.failed == []
        assert controller.is_busy is False
