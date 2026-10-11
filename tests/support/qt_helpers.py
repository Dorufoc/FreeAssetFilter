"""Qt 测试辅助：事件泵、信号等待、安全清理与非空断言。

本模块只依赖 PySide6 与"概念性" widget/QObject（含传参的实际子类），
**禁止导入任何 freeassetfilter 产品模块**，从而成为纯测试基础设施。

设计要点：

* :func:`wait_for_signal` 基于 ``QEventLoop`` + ``QTimer.singleShot``
  兜底超时，**永不无限等待** —— 对 50ms 内从不发射的信号也能在
  给定超时内返回 False，不挂起；
* :func:`assert_pixmap_nonempty` 逐像素扫描非全零（复用旧
  ``tests/gui/test_previewer_visual.py`` 的检测思路，封装为独立 helper），
  空 pixmap / 空图像一律判失败。
"""

from __future__ import annotations

import time
from typing import Any, Callable, List, Optional

from PySide6.QtCore import QEventLoop, QObject, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QWidget


def _application() -> Optional[QApplication]:
    """返回当前 QApplication 实例（不存在则 None）。

    Returns:
        Optional[QApplication]: 已注册的应用实例。
    """
    return QApplication.instance()  # type: ignore[return-value]


#: 清道夫单批销毁的顶层窗口数量。批次间留事件泵窗口：deferred delete 与
#: 跨线程信号（QThreadPool 完成信号等）同批碰撞会在 shiboken 触发
#: ``0xC0000005``（见 :func:`safe_teardown` 的 W11 记录），分批把一批销毁
#: 拆成多次小批量以降低碰撞面。
_SCAVENGE_BATCH: int = 12

#: 需要在下发 DeferredDelete 前先 ``dispose`` 的背景材质属性名。
#: Mica 材质持有后台烘焙线程 / 看门狗 / 事件过滤器；未经 dispose 直接销毁
#: 宿主控件会让在途线程回调撞上已析构对象（原生访问冲突）。正常产品路径由
#: ``MainWindow.closeEvent`` 调 ``_dispose_mica``；测试替身/独立材质控件
#: 不经过该路径，由清道夫补齐。
_MICA_DISPOSE_ATTRS = ("_mica", "_mica_material", "_material")


def _dispose_widget_mica(widget: QWidget) -> None:
    """递归 dispose 控件树上的 Mica 材质（存在 ''dispose'' 方法时）。

    仅处理显式登记的材质属性名（``_mica`` 等），非 Mica 属性不受影响；
    任何异常静默忽略（清理是尽力而为，不改变测试结果）。

    Args:
        widget: 子树根控件。
    """
    stack: List[QWidget] = [widget]
    while stack:
        node = stack.pop()
        for attr in _MICA_DISPOSE_ATTRS:
            try:
                material = getattr(node, attr, None)
            except (AttributeError, RuntimeError):
                continue
            if material is None:
                continue
            dispose = getattr(material, "dispose", None)
            if callable(dispose):
                try:
                    dispose()
                except Exception:  # noqa: BLE001 - 清理失败不阻断
                    pass
        try:
            stack.extend(node.findChildren(QWidget))
        except RuntimeError:
            continue


def process_qt_events(app: Optional[QApplication], ms: int = 50) -> None:
    """单次事件泵：带超时地处理 Qt 待决事件。

    先冲刷一轮 ``processEvents``，进入嵌套 ``QEventLoop`` 并安排
    单发定时器在 ``ms`` 毫秒后退出，最后再冲刷一轮。

    Args:
        app: QApplication 实例；为 None 时直接返回。
        ms: 事件处理窗口毫秒数（<=0 时只做两轮无阻塞 processEvents）。
    """
    if app is None:
        return
    app.processEvents()
    if ms > 0:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()
    app.processEvents()


def wait_for_signal(signal: Any, timeout_ms: int = 5000) -> bool:
    """等待一个 Qt 信号在超时内发射（同步、有界）。

    信号发射即以 ``QEventLoop.quit`` 提前退出；否则由单发定时器在
    ``timeout_ms`` 后强制退出。**任何路径都不会无限等待**。

    Args:
        signal: Qt 信号对象（PySide6 ``SignalInstance`` 或兼容可 connect 者）。
        timeout_ms: 超时毫秒数。

    Returns:
        bool: 超时前信号已发射返回 True，否则 False。
    """
    emitted: List[bool] = [False]

    def _on_signal(*_args: Any) -> None:
        emitted[0] = True

    signal.connect(_on_signal)
    loop = QEventLoop()
    try:
        signal.connect(loop.quit)
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()
    finally:
        try:
            signal.disconnect(_on_signal)
        except (TypeError, RuntimeError):
            pass
        try:
            signal.disconnect(loop.quit)
        except (TypeError, RuntimeError):
            pass
    return emitted[0]


def wait_until(
    app: Optional[QApplication],
    predicate: Callable[[], Any],
    timeout_ms: int = 5000,
    interval_ms: int = 10,
) -> bool:
    """有界等待条件成立（跨线程信号落地/后台任务完成等场景）。

    每轮先轮询 ``predicate``，未满足则泵一轮事件并短暂休眠，直到条件为真
    或超时。**任何路径都不会无限等待**。

    Args:
        app: QApplication 实例；为 None 时只轮询不泵事件。
        predicate: 无参可调用对象，返回真值表示条件满足。
        timeout_ms: 超时毫秒数。
        interval_ms: 每轮间隔毫秒数。

    Returns:
        bool: 超时前条件满足返回 True，否则 False。
    """
    deadline = time.monotonic() + max(0, timeout_ms) / 1000.0
    while True:
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return False
        if app is not None:
            app.processEvents()
        time.sleep(max(0, interval_ms) / 1000.0)


def flush_widget_queue(app: Optional[QApplication] = None, iterations: int = 20) -> None:
    """尽力排空 widget 事件队列（有界）。

    等宽处理多轮 ``processEvents``，保证 deleteLater/重绘等事件得到
    处理机会，同时有界以防极端情况下死循环。

    注：``deleteLater`` 的 DeferredDelete 事件在部分场景（未进入过真实
    事件循环、窗口未 show）不会被纯 ``processEvents`` 派发；需要彻底落地
    延迟销毁请用 :func:`drain_deferred_deletes`。

    Args:
        app: QApplication 实例；省略时自动探测。
        iterations: 最大轮数。
    """
    active_app: Optional[QApplication] = app if app is not None else _application()
    if active_app is None:
        return
    for _ in range(max(0, iterations)):
        active_app.processEvents()


def drain_deferred_deletes(
    app: Optional[QApplication] = None, rounds: int = 4
) -> None:
    """显式派发 DeferredDelete（彻底落地 deleteLater），不使用嵌套事件循环。

    ``QApplication.processEvents()`` 对 ``deleteLater`` 派发不可靠（尤其
    窗口未 ``show()`` / 从未进入 ``exec()`` 的测试进程）。这里用
    ``QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)``
    显式派发延迟销毁事件（Qt 官方途径），再做一轮普通事件泵让销毁级联
    落地；**不进入嵌套事件循环**，避免在测试调用栈中间意外处理其它排队
    信号（曾观察到把测试自己的定时器/信号提前消费导致挂起）。

    Args:
        app: QApplication 实例；省略时自动探测。
        rounds: 派发轮数（每轮 sendPostedEvents + processEvents）。
    """
    active_app: Optional[QApplication] = app if app is not None else _application()
    if active_app is None:
        return
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
    except Exception:  # noqa: BLE001
        for _ in range(max(0, rounds)):
            active_app.processEvents()
        return
    for _ in range(max(0, rounds)):
        try:
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        except Exception:  # noqa: BLE001
            pass
        active_app.processEvents()


def safe_teardown(widget: Optional[QObject]) -> None:
    """安全销毁一个 Qt widget/对象。

    按 close → deleteLater 顺序清理，并对已销毁的 C++ 对象（RuntimeError）
    或 None 输入做防御。

    W11：deleteLater 后**不**立即 processEvents()。立即全量泵会在同一批次
    同时投递残留的排队信号（跨线程 QThreadPool 完成信号、防抖定时器等）与
    本对象销毁事件，若目标包装器恰在本批次被销毁，shiboken 向已释放内存
    WRITE（0xc0000005，见 VEH：module=shiboken6.abi3.dll access=WRITE
    target=0xffffffffffffffff）。销毁延迟到下一次自然泵（各测试体内的
    flush_widget_queue / QTest.qWait）逐对象进行，避免与跨线程信号同批碰撞。

    Args:
        widget: 待清理的 QObject（通常是 QWidget）。
    """
    if widget is None:
        return
    try:
        if isinstance(widget, QWidget) and widget.isVisible():
            widget.close()
    except RuntimeError:  # C++ 对象已删除
        return
    try:
        widget.deleteLater()
    except RuntimeError:
        return


def toplevel_widget_snapshot() -> set:
    """当前全部顶层 widget 的 ``id()`` 快照（供测试隔离夹具比对）。

    Returns:
        set: 现存顶层 ``QWidget`` 包装器 id 集合；无 QApplication 时为空集。
    """
    active_app: Optional[QApplication] = _application()
    if active_app is None:
        return set()
    return {id(w) for w in active_app.topLevelWidgets()}


def scavenge_toplevel_widgets(baseline: set) -> int:
    """关闭并销毁测试期间新增的顶层 widget（测试隔离清道夫）。

    泄漏背景（tests-comprehensive-refactor 全量回归结论）：UI 测试创建
    ``MainWindow`` / 各预览布局后只对根窗口 ``deleteLater()``，而部分场景
    （未 ``show()`` 的窗口、被测试内异常回溯扣住的引用）下 deferred delete
    不会落地，跨测试线性累积数千存活控件。应用级 QSS 单例（
    ``app_stylesheet``）的 ``setStyleSheet`` 全树重刷成本随存活控件规模增长，
    最终任何一次 ``processEvents()`` 触发的重刷都会超时（历史症状：
    ``test_show_event_gating`` 30s timeout）。

    本函数把**每个测试新建的顶层窗口**统一 close + deleteLater，并显式
    派发 DeferredDelete（批量、批间普通事件泵；单批最多
    :data:`_SCAVENGE_BATCH` 个），从源头维持存活控件规模恒定。
    ``baseline`` 中记录的（会话级宿主）窗口不受影响。

    Args:
        baseline: ``toplevel_widget_snapshot()`` 在测试开始前采集的 id 快照。

    Returns:
        int: 被清理（close + deleteLater）的顶层窗口数量。
    """
    active_app: Optional[QApplication] = _application()
    if active_app is None:
        return 0
    targets: List[QWidget] = []
    for widget in list(active_app.topLevelWidgets()):
        if id(widget) in baseline:
            continue
        try:
            if widget.isVisible():
                widget.close()
        except RuntimeError:  # C++ 对象已销毁
            continue
        targets.append(widget)
    if not targets:
        return 0
    try:
        from freeassetfilter.ui.theme.app_stylesheet import (
            resume_qss_apply,
            suspend_qss_apply,
        )
    except Exception:  # noqa: BLE001 - 产品模块不可用时退化为直接泵
        suspend_qss_apply = resume_qss_apply = None  # type: ignore[assignment]
    if suspend_qss_apply is not None:
        suspend_qss_apply()
    try:
        # 先 dispose 全部新增树上的 Mica 材质（停后台线程/看门狗/过滤器），
        # 再下发销毁；避免强制销毁时在途线程回调撞已析构对象。
        for widget in targets:
            _dispose_widget_mica(widget)
        for start in range(0, len(targets), _SCAVENGE_BATCH):
            batch = targets[start : start + _SCAVENGE_BATCH]
            for widget in batch:
                try:
                    widget.deleteLater()
                except RuntimeError:
                    pass
            # 批量派发 + 事件泵：批间留出跨界信号落地窗口，避免全部销毁
            # 事件与跨线程信号同批碰撞（shiboken 0xC0000005 已知签名）。
            drain_deferred_deletes(active_app, rounds=1)
            active_app.processEvents()
        drain_deferred_deletes(active_app, rounds=2)
    finally:
        if resume_qss_apply is not None:
            resume_qss_apply()
    return len(targets)


def assert_pixmap_nonempty(
    pixmap: Optional[QPixmap],
    message: Optional[str] = None,
) -> None:
    """断言 pixmap 非空且含至少一个非零像素。

    复用旧 ``test_previewer_visual.py`` 的逐像素扫描思路：将 pixmap 转
    ``QImage`` 后扫描全部像素，任一像素值非 0 即通过；null pixmap /
    null image / 零尺寸 / 全零像素均判为失败。

    Args:
        pixmap: 被测 QPixmap。
        message: 自定义失败消息；缺省时给出描述性信息。

    Raises:
        AssertionError: pixmap 为 null、图像无效或全零像素。
    """
    base: str = message or "pixmap 应为非空（至少含一个非零像素）"
    if pixmap is None or pixmap.isNull():
        raise AssertionError(f"{base}；实际 pixmap 为 null")
    image = pixmap.toImage()
    if image.isNull():
        raise AssertionError(f"{base}；转换后的 QImage 为 null")
    width: int = image.width()
    height: int = image.height()
    if width <= 0 or height <= 0:
        raise AssertionError(f"{base}；图像尺寸无效 ({width}x{height})")
    found: bool = False
    for y in range(height):
        for x in range(width):
            if image.pixel(x, y) != 0:
                found = True
                break
        if found:
            break
    if not found:
        raise AssertionError(f"{base}；图像 {width}x{height} 全部像素为零")