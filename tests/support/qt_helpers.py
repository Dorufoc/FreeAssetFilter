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

from typing import Any, List, Optional

from PySide6.QtCore import QEventLoop, QObject, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QWidget


def _application() -> Optional[QApplication]:
    """返回当前 QApplication 实例（不存在则 None）。

    Returns:
        Optional[QApplication]: 已注册的应用实例。
    """
    return QApplication.instance()  # type: ignore[return-value]


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


def flush_widget_queue(app: Optional[QApplication] = None, iterations: int = 20) -> None:
    """尽力排空 widget 事件队列（有界）。

    等宽处理多轮 ``processEvents``，保证 deleteLater/重绘等事件得到
    处理机会，同时有界以防极端情况下死循环。

    Args:
        app: QApplication 实例；省略时自动探测。
        iterations: 最大轮数。
    """
    active_app: Optional[QApplication] = app if app is not None else _application()
    if active_app is None:
        return
    for _ in range(max(0, iterations)):
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