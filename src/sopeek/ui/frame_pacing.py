#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""让 Qt 自带动画跑在面板刷新率上（全局动画节拍补丁）。

## 问题

Qt 的动画由 `QUnifiedTimer` 统一驱动，其定时器间隔**固定约 16 ms**
（Qt 源码中的 ``DefaultAnimationInterval``），与显示器刷新率无关。因此在
240Hz 面板上，项目里 200 多处 ``QPropertyAnimation`` / ``QVariantAnimation``
（按钮 hover、卡片浮起、侧栏高亮、日期选择器逐格 hover……）全部只有约
63 fps。

PySide6 **没有绑定** ``QAnimationDriver``（实测 ImportError），无法从
驱动层换掉这个定时器；唯一的办法是让动画自己在每一帧重新插值。

## 做法

把 ``PySide6.QtCore.QPropertyAnimation`` / ``QVariantAnimation`` 这两个
**名字**替换成子类（模块属性可写，实测可行）：

* 子类保留全部 C++ 行为（插值、缓动、keyValue、循环、``finished``、
  动画组、``DeleteWhenStopped``）；
* 额外把自己注册到 :class:`~sopeek.core.managers.frame_scheduler.FrameScheduler`，
  每帧用**墙钟时间**调用一次 ``QAbstractAnimation.setCurrentTime()``，即"加帧"
  （实测：未绑定的 ``updateCurrentTime(anim, t)`` 不写属性、不发 ``valueChanged``，
  ``setCurrentTime()`` 才走 Qt 内部虚函数，立即写属性并发信号）；
* Qt 自己的 16 ms 定时器仍然保留，作为下限兜底——即使帧调度器因空闲降频
  或过载降级而变慢，动画也只是回到 63 fps，绝不会卡住或变快。

因为时间量取自 ``perf_counter()`` 而非"固定步长累加"，动画速度与定时器
精度解耦：240fps 与 60fps 下同一个 200 ms 动画都恰好走 200 ms。

## 安全阀

* 环境变量 ``SPK_REFRESH_ANIMATIONS=0`` 可整体关闭补丁；
* 任何一步失败（无 Qt、无 QApplication、子类化失败）都静默回退到原生行为；
* 只会"加帧"，不会改变动画的起点、终点、时长、缓动与循环次数。
"""

from __future__ import annotations

import os
import time
import weakref
from typing import Any, Optional

from PySide6.QtCore import (
    QAbstractAnimation,
    QCoreApplication,
    QPropertyAnimation,
    QVariantAnimation,
)

from sopeek.core.managers.frame_scheduler import frame_scheduler
from sopeek.utils.app_logger import debug, warning

#: 保存 Qt 原生类，供卸载与内部调用使用。
_QtPropertyAnimation = QPropertyAnimation
_QtVariantAnimation = QVariantAnimation

#: 正在跑的动画（强引用，防 `DeleteWhenStopped` 语义下被 Python GC 掉）。
_active: dict[int, Any] = {}

_installed: bool = False


def _env_enabled() -> bool:
    """读取补丁开关（默认开启）。"""
    raw = os.environ.get("SPK_REFRESH_ANIMATIONS", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _paced_init(animation: Any) -> None:
    """初始化补丁状态字段。"""
    animation._pacing_t0 = 0.0
    animation._pacing_paused_ms = 0.0
    animation._pacing_paused_at = 0.0
    animation._pacing_registered = False
    animation._pacing_token = object()
    try:
        ref = weakref.ref(animation)

        def _on_finished(*_args: Any) -> None:
            target = ref()
            if target is not None:
                _paced_unregister(target)

        animation.finished.connect(_on_finished)
    except (RuntimeError, TypeError):
        pass


def _elapsed_ms(animation: Any) -> float:
    """返回动画从 start() 起算的墙钟毫秒数（扣除暂停时长）。"""
    if animation._pacing_t0 <= 0.0:
        return 0.0
    now = time.perf_counter()
    elapsed = (now - animation._pacing_t0) * 1000.0 - animation._pacing_paused_ms
    if animation._pacing_paused_at > 0.0:
        elapsed -= (now - animation._pacing_paused_at) * 1000.0
    return max(0.0, elapsed)


def _apply_current_time(animation: Any, current: int) -> None:
    """把动画推进到 ``current`` 毫秒。

    只用公开的 :meth:`QAbstractAnimation.setCurrentTime`：它会走 Qt 内部
    的 ``updateCurrentTime`` 虚函数（属性动画在那里写目标属性、发出
    ``valueChanged``、走到终点时发 ``finished``）。实测（PySide6 6.11）：

    * 直接调未绑定的 ``updateCurrentTime(anim, t)`` **不会**写属性、
      也不会发信号，动画仍只按 Qt 自己的 16 ms 定时器走；
    * ``setCurrentTime(t)`` 会立即写属性并发信号（300 ms → opacity 0.6）。
    """
    animation.setCurrentTime(current)


def _paced_apply(animation: Any) -> None:
    """按墙钟时间把动画推进到"此刻"该有的值。"""
    try:
        if animation.state() != QAbstractAnimation.State.Running:
            _paced_unregister(animation)
            return
        duration = animation.duration()
        if duration <= 0:
            return
        current = _elapsed_ms(animation)
        if animation.loopCount() != 1:
            current = current % duration
        else:
            current = min(current, float(duration))
        if animation.direction() == QAbstractAnimation.Direction.Backward:
            current = max(0.0, duration - current)
        # 主线程已经画不过来时跳过本帧的可视更新：动画时间轴仍按墙钟推进，
        # 下一帧会直接跳到"此刻"该有的值，所以时长不变、只是少画几帧。
        # 否则 240Hz 的重绘请求会把事件循环灌满，交互延迟飙到 40~140ms。
        # 终点帧必须放行，否则 finished 不会发出。
        if current < duration and frame_scheduler().behind:
            return
        _apply_current_time(animation, int(current))
    except RuntimeError:
        # C++ 对象已销毁（DeleteWhenStopped / 父对象析构）。
        _paced_unregister(animation, force=True)


def _paced_register(animation: Any) -> None:
    """把动画登记到帧调度器（每帧加一帧）。"""
    if animation._pacing_registered:
        return
    if QCoreApplication.instance() is None:
        return
    key = id(animation)
    try:
        _active[key] = animation
        scheduler = frame_scheduler()
        scheduler.subscribe(
            f"anim:{key}",
            lambda a=animation: _paced_apply(a),
            hz=None,
            priority=1,
            owner=animation,
        )
        scheduler.request_high_rate(animation._pacing_token)
        animation._pacing_registered = True
    except Exception as exc:  # noqa: BLE001 - 加帧失败不得影响动画本身
        _active.pop(key, None)
        debug(f"frame_pacing: register failed: {exc}")


def _paced_unregister(animation: Any, force: bool = False) -> None:
    """注销动画的加帧订阅与硬需求令牌。"""
    if not force and not animation._pacing_registered:
        return
    animation._pacing_registered = False
    _active.pop(id(animation), None)
    try:
        scheduler = frame_scheduler()
        scheduler.unsubscribe(f"anim:{id(animation)}")
        scheduler.release_high_rate(animation._pacing_token)
    except Exception:  # noqa: BLE001
        pass


class _PacedAnimationMixin:
    """把 Qt 动画的推进接到帧调度器（墙钟驱动，原生 ~16ms 定时器保留为下限兜底）。"""

    def _pacing_begin(self) -> None:
        """记录起始时刻并把动画登记到帧调度器。"""
        self._pacing_t0 = time.perf_counter()
        self._pacing_paused_ms = 0.0
        self._pacing_paused_at = 0.0
        _paced_register(self)

    def start(
        self,
        policy: QAbstractAnimation.DeletionPolicy = (
            QAbstractAnimation.DeletionPolicy.KeepWhenStopped
        ),
    ) -> None:
        """启动动画并接管每帧插值。"""
        self._pacing_begin()
        super().start(policy)

    def stop(self) -> None:
        """停止动画并注销加帧订阅。"""
        super().stop()
        _paced_unregister(self)

    def pause(self) -> None:
        """暂停（墙钟同步冻结）。"""
        super().pause()
        if self._pacing_paused_at <= 0.0:
            self._pacing_paused_at = time.perf_counter()

    def resume(self) -> None:
        """恢复（把暂停时长从墙钟里扣掉）。"""
        if self._pacing_paused_at > 0.0:
            self._pacing_paused_ms += (
                time.perf_counter() - self._pacing_paused_at
            ) * 1000.0
            self._pacing_paused_at = 0.0
        super().resume()

    def setPaused(self, paused: bool) -> None:  # noqa: N802
        """``QAbstractAnimation.setPaused`` 的 Python 侧同步版本。"""
        if paused:
            self.pause()
        else:
            self.resume()


class RefreshVariantAnimation(_PacedAnimationMixin, QVariantAnimation):
    """跑在面板刷新率上的 :class:`QVariantAnimation`。"""

    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        _paced_init(self)


class RefreshPropertyAnimation(_PacedAnimationMixin, QPropertyAnimation):
    """跑在面板刷新率上的 :class:`QPropertyAnimation`。

    构造签名与 Qt 原生类完全一致（``(parent)`` 或
    ``(target, propertyName[, parent])``），因此可以整体替换类名使用。
    """

    def __init__(self, *args: Any) -> None:
        if not args:
            super().__init__()
        elif len(args) == 1:
            super().__init__(args[0])
        else:
            super().__init__(args[0], args[1], *args[2:])
        _paced_init(self)


def install_frame_pacing() -> bool:
    """把 Qt 动画类替换为刷新率对齐版本（幂等）。

    Returns:
        成功安装（或此前已安装）返回 ``True``；被环境变量关闭或安装失败
        返回 ``False``（调用方无需处理，原生节拍仍然可用）。
    """
    global _installed
    if _installed:
        return True
    if not _env_enabled():
        debug("frame_pacing: disabled by SPK_REFRESH_ANIMATIONS")
        return False
    try:
        import PySide6.QtCore as qtcore

        qtcore.QPropertyAnimation = RefreshPropertyAnimation  # type: ignore[attr-defined]
        qtcore.QVariantAnimation = RefreshVariantAnimation  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 - 补丁失败必须退回原生行为
        warning(f"frame_pacing: install failed, falling back to Qt timing: {exc}")
        return False
    _installed = True
    debug("frame_pacing: installed (animations follow panel refresh rate)")
    return True


def uninstall_frame_pacing() -> None:
    """恢复 Qt 原生动画类（测试/诊断用）。"""
    global _installed
    if not _installed:
        return
    try:
        import PySide6.QtCore as qtcore

        qtcore.QPropertyAnimation = _QtPropertyAnimation  # type: ignore[attr-defined]
        qtcore.QVariantAnimation = _QtVariantAnimation  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    for animation in list(_active.values()):
        _paced_unregister(animation, force=True)
    _active.clear()
    _installed = False


def is_installed() -> bool:
    """补丁是否已安装。"""
    return _installed


def active_animation_count() -> int:
    """当前正在加帧的动画数量（诊断用）。"""
    return len(_active)


__all__ = [
    "RefreshPropertyAnimation",
    "RefreshVariantAnimation",
    "install_frame_pacing",
    "uninstall_frame_pacing",
    "is_installed",
    "active_animation_count",
]
