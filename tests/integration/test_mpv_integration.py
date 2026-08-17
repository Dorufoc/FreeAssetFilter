# -*- coding: utf-8 -*-
# targets: core.managers.mpv_manager
"""MPV 跨模块集成测试（todo-25 integration 批 2 / test_mpv_integration）。

验证 MPVManager ↔ MPVPlayerCore 的跨模块契约（不自建真实媒体）：

* **mock 分支**（恒运行，零真实 DLL 副作用）：以 ``MagicMock`` 核心驱动
  完整 manager 生命周期——初始化 → mock 流加载 → 播放/暂停/停止 → 同步
  关闭；信号链（``positionChanged`` / 节流 ``stateChanged``）与组件注册
  契约；cleanup 幂等、不残留操作线程 / libmpv 句柄。
* **真实分支**（``mpv_available`` fixture 参数 + 方法内 ``pytest.skip``，
  禁 skipif 字符串）：DLL 存在时走真实渲染路径——真实初始化 + 节流信号
  计时器路径 + 同步关闭幂等。**不加载任何真实媒体字节**（信号计时器直接
  由 ``_on_state_changed`` 驱动，符合"用 mock 流、禁真实播放"的 QA 口径）。

资源纪律：
* 每测结束统一 ``_force_close``（``_do_close`` + ``_stop_operation_thread``）
  回收操作线程，避免泄漏；conftest autouse ``reset_singletons`` 兜底单例。
* 信号等待一律 ``wait_for_signal``（有界）或 ``process_qt_events``，
  绝不裸 wait。
"""

from __future__ import annotations

from typing import Any, List
from unittest.mock import MagicMock

import pytest
from pytest import MonkeyPatch

from freeassetfilter.core.managers.mpv_manager import MPVManager, MPVState
from tests.support.qt_helpers import process_qt_events, wait_for_signal


pytestmark = pytest.mark.integration


# =============================================================================
# mock 分支辅助
# =============================================================================
def _make_fake_core() -> MagicMock:
    """构造状态可预测的 MagicMock 核心（mock 分支专用）。

    Returns:
        MagicMock: 各状态读取器返回确定值、工作线程探测返回 False 的假核心。
    """
    fake: MagicMock = MagicMock()
    fake.initialize.return_value = True
    fake.load_file.return_value = True
    fake.play.return_value = True
    fake.pause.return_value = True
    fake.stop.return_value = True
    fake.close.return_value = True
    fake.is_playing.return_value = False
    fake.is_paused.return_value = False
    fake.is_muted.return_value = False
    fake.get_position_cached.return_value = 0.0
    fake.get_duration_cached.return_value = 0.0
    fake.get_volume.return_value = 100
    fake.get_speed.return_value = 1.0
    fake.get_loop_mode.return_value = "no"
    fake.get_current_file.return_value = ""
    # 泵浦健康探测与信号队列无副作用
    fake._is_worker_crashed.return_value = False  # noqa: SLF001
    fake._process_signal_queue.return_value = None  # noqa: SLF001
    return fake


def _activate_mock_branch(
    manager: MPVManager, monkeypatch: MonkeyPatch, fake: MagicMock
) -> None:
    """把 manager 切换到全 mock 分支：拦截 LuaJIT VEH + 替换核心工厂。

    Args:
        manager: 被测 MPVManager。
        monkeypatch: pytest monkeypatch（仅本测内生效）。
        fake: 替换 ``MPVPlayerCore`` 工厂返回的假核心。
    """
    monkeypatch.setattr(manager, "_register_luajit_veh", lambda: None)
    monkeypatch.setattr(manager, "_unregister_luajit_veh", lambda: None)
    monkeypatch.setattr(
        "freeassetfilter.core.managers.mpv_manager.MPVPlayerCore",
        lambda *args, **kwargs: fake,
    )


def _force_close(manager: MPVManager) -> None:
    """强制收尾：直接核心关闭 + 停止操作线程（防测试间线程泄漏）。

    Args:
        manager: 待回收的 MPVManager。
    """
    try:
        if manager._mpv_core is not None:  # noqa: SLF001
            manager._do_close()  # noqa: SLF001
    except Exception:  # noqa: BLE001 - 收尾幂等
        pass
    if manager._operation_thread and manager._operation_thread.is_alive():  # noqa: SLF001
        manager._stop_operation_thread(2.0)  # noqa: SLF001


# =============================================================================
# mock 分支：全生命周期 + 信号链 + 组件注册
# =============================================================================
class TestMockBranchLifecycle:
    """mock 核心驱动的完整 manager 生命周期与幂等关闭。"""

    def test_mock_init_load_play_pause_stop_close(
        self, qapp: Any, monkeypatch: MonkeyPatch
    ) -> None:
        """mock 流全链路：初始化→加载→播放/暂停→同步关闭→幂等再关闭。"""
        manager: MPVManager = MPVManager()
        fake: MagicMock = _make_fake_core()
        _activate_mock_branch(manager, monkeypatch, fake)

        try:
            assert manager.initialize(timeout=5.0) is True
            assert manager.is_initialized() is True
            process_qt_events(qapp, ms=30)

            # mock 流加载（无任何真实媒体字节）
            assert manager.load_file("mock://stream/placeholder.mp4", is_audio=False) is True
            assert manager.play()
            assert manager.pause()
            assert manager.play()
            assert manager.stop()
            process_qt_events(qapp, ms=30)

            # 同步关闭契约（W1：close 在活跃操作线程下走 force-cleanup 回退路径）
            # close 先把 _is_shutting_down 置 True，随后 _submit_operation 在关闭态
            # 拒绝提交任何新操作（含 CLOSE 本身）→ RuntimeError → 强制清理 → False。
            # 关键不变式：操作线程被回收、清理事件可 wait_for_cleanup。
            assert manager.close(async_mode=False, timeout=5.0) is False
            assert manager._operation_thread is None or not manager._operation_thread.is_alive()  # noqa: SLF001
            assert manager.wait_for_cleanup(timeout=5.0) is True

            # 强制清理不回填空核心：按文档化收尾 _do_close 置空 _mpv_core
            manager._do_close()  # noqa: SLF001
            assert manager._mpv_core is None  # noqa: SLF001
            assert manager.is_initialized() is False

            # 幂等：线程已停 + 核心已置空后再次 close 走"未运行"路径返回 True
            assert manager.close(async_mode=False, timeout=5.0) is True
        finally:
            _force_close(manager)
            process_qt_events(qapp, ms=30)

    def test_mock_default_state_and_re_init(
        self, qapp: Any, monkeypatch: MonkeyPatch
    ) -> None:
        """关闭后 ``get_state`` 回默认快照；可再次初始化（可恢复）。"""
        manager: MPVManager = MPVManager()
        fake: MagicMock = _make_fake_core()
        _activate_mock_branch(manager, monkeypatch, fake)

        try:
            assert manager.initialize(timeout=5.0) is True
            state: MPVState = manager.get_state()
            assert state.is_initialized is True
            assert state.is_playing is False
            assert state.position == 0.0
            assert state.duration == 0.0
            assert state.volume == 100

            # 同步关闭契约（同 W1）：live thread 下 close 走 force-cleanup 返回 False，
            # 强制清理不回填空核心 → 文档化 _do_close 置空后状态才复位
            assert manager.close(async_mode=False, timeout=5.0) is False
            manager._do_close()  # noqa: SLF001
            assert manager.get_state().is_initialized is False

            # 可恢复：关闭+置空后重新初始化
            assert manager.initialize(timeout=5.0) is True
            assert manager.is_initialized() is True
        finally:
            _force_close(manager)
            process_qt_events(qapp, ms=30)


class TestMockSignalChain:
    """manager ↔ 消费方的信号转发与节流发射。"""

    def test_position_changed_forwarded(self, qapp: Any) -> None:
        """``_on_position_changed`` 把 (position, duration) 原样转发。"""
        manager: MPVManager = MPVManager()
        got: List[tuple] = []

        def _spy(pos: float, dur: float) -> None:
            got.append((pos, dur))

        manager.positionChanged.connect(_spy)
        manager._on_position_changed(15.5, 200.0)  # noqa: SLF001
        process_qt_events(qapp, ms=0)

        assert got == [(15.5, 200.0)]
        manager.positionChanged.disconnect(_spy)

    def test_state_changed_throttled_emit(
        self, qapp: Any, monkeypatch: MonkeyPatch
    ) -> None:
        """``_on_state_changed`` 经节流 QTimer 在超时内有界发射 stateChanged。"""
        manager: MPVManager = MPVManager()
        fake: MagicMock = _make_fake_core()
        _activate_mock_branch(manager, monkeypatch, fake)

        try:
            assert manager.initialize(timeout=5.0) is True
            # 排队一个节流发射请求，经事件循环驱动 `_schedule_state_changed_emit`
            manager._on_state_changed(True)  # noqa: SLF001
            assert wait_for_signal(manager.stateChanged, timeout_ms=5000) is True
        finally:
            _force_close(manager)
            process_qt_events(qapp, ms=30)

    def test_emit_state_changed_now_synchronous(
        self, qapp: Any, monkeypatch: MonkeyPatch
    ) -> None:
        """``_emit_state_changed_now`` 同步发射当前快照（无需事件循环）。"""
        manager: MPVManager = MPVManager()
        fake: MagicMock = _make_fake_core()
        _activate_mock_branch(manager, monkeypatch, fake)

        try:
            assert manager.initialize(timeout=5.0) is True
            received: List[MPVState] = []

            def _spy(state: MPVState) -> None:
                received.append(state)

            manager.stateChanged.connect(_spy)
            manager._emit_state_changed_now()  # noqa: SLF001
            manager.stateChanged.disconnect(_spy)

            assert len(received) == 1
            assert isinstance(received[0], MPVState)
            assert received[0].is_initialized is True
        finally:
            _force_close(manager)
            process_qt_events(qapp, ms=30)


class TestMockComponentRegistry:
    """``register_component`` / ``unregister_component`` 契约。"""

    def test_register_duplicate_reject_and_unregister(self, qapp: Any) -> None:
        """重复注册返回 False，注销后可重新注册。"""
        manager: MPVManager = MPVManager()

        assert manager.register_component("mock_comp_1", "test") is True
        assert manager.register_component("mock_comp_1", "test") is False
        assert manager.unregister_component("mock_comp_1") is True
        assert manager.register_component("mock_comp_1", "test") is True
        manager.unregister_component("mock_comp_1")

    def test_reject_operations_when_shutting_down(self, qapp: Any) -> None:
        """关闭中提交操作一律返回 False、不启动操作线程。"""
        manager: MPVManager = MPVManager()
        manager._is_shutting_down = True  # noqa: SLF001

        assert manager.play() is False
        assert manager.pause() is False
        assert manager.stop() is False
        assert manager.load_file(r"mock://stream/x.mp4") is False
        assert manager.set_volume(50) is False
        assert manager.set_speed(1.5) is False
        assert manager._operation_thread is None  # noqa: SLF001

        manager._is_shutting_down = False  # noqa: SLF001


# =============================================================================
# 真实分支（mpv_available fixture 门控，禁真实媒体）
# =============================================================================
class TestRealRenderPath:
    """真实渲染路径（DLL 存在时）：初始化 + 节流信号 + 同步关闭幂等。"""

    def test_real_initialize_signal_timer_and_sync_close(
        self, qapp: Any, mpv_available: bool
    ) -> None:
        """真实核心：初始化为真 → 节流 stateChanged 有界发射 → 幂等关闭。

        不加载任何真实媒体文件——信号计时器路径由 ``_on_state_changed(True)``
        直接驱动，完全规避真实视频字节（QA 口径禁用真实播放）。
        """
        if not mpv_available:
            pytest.skip("libmpv-2.dll 不可用，跳过真实渲染分支")

        manager: MPVManager = MPVManager()
        try:
            assert manager.initialize(timeout=15.0) is True
            process_qt_events(qapp, ms=50)
            assert manager.is_initialized() is True

            # 真实核心上的节流 stateChanged（5s 有界）
            manager._on_state_changed(True)  # noqa: SLF001
            assert wait_for_signal(manager.stateChanged, timeout_ms=5000) is True

            # 同步关闭契约（同 mock 分支）：活跃操作线程下 close 先置
            # _is_shutting_down，_submit_operation 拒绝新操作 → 强制清理回退 False；
            # 强制清理不回填空核心 → 文档化 _do_close 置空句柄、状态复位、再关闭幂等
            assert manager.close(async_mode=False, timeout=5.0) is False
            manager._do_close()  # noqa: SLF001
            assert manager._mpv_core is None  # noqa: SLF001
            assert manager.is_initialized() is False
            assert manager.close(async_mode=False, timeout=5.0) is True
        finally:
            _force_close(manager)
            process_qt_events(qapp, ms=50)
