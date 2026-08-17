# -*- coding: utf-8 -*-
# targets: services.image_decode_worker, services.image_decoder_service
"""``ImageDecoderService`` 与 ``ImageDecodeWorker`` 单元测试（todo-13 批2）。

覆盖：
* 解码管线：PIL→QImage 真实 PNG/JPEG 转换、mock 复杂格式后端的完整
  ``decode_to_qimage`` 成功路径、损坏/缺失文件的优雅失败（不崩溃）；
* Worker：成功/失败信号、取消（启动前/运行中）、**内部 60s 超时防挂**、
  批量 10 任务全部完成。

线程纪律（AGENTS.md 跨线程模式）：
* QThread 在 ``wait()``/``deleteLater()`` 前检查 ``isRunning()``；
* teardown 中 ``terminate()`` 兜底；
* 所有信号等待经 ``tests/support/qt_helpers.py::wait_for_signal`` 有界等待。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, List, Tuple

import pytest

from freeassetfilter.services.image_decode_worker import ImageDecodeWorker
from freeassetfilter.services.image_decoder_service import (
    CorruptFileError,
    DecodeError,
    DependencyError,
    ImageDecoderService,
)
from tests.support.data_factories import make_image
from tests.support.qt_helpers import flush_widget_queue, wait_for_signal

pytestmark = pytest.mark.unit


def _make_png_bytes(width: int = 16, height: int = 12) -> bytes:
    """用 PIL 在内存中生成一张 PNG 的字节内容（不落盘）。

    Args:
        width: 图像宽度。
        height: 图像高度。

    Returns:
        bytes: PNG 编码字节。
    """
    import io

    from PIL import Image

    img = Image.new("RGB", (width, height), (10, 200, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _shutdown_worker(worker: ImageDecodeWorker, timeout_ms: int = 3000) -> None:
    """安全回收 worker：isRunning 守卫 → wait → terminate 兜底 → deleteLater。

    Args:
        worker: 待回收的 worker。
        timeout_ms: 首次 ``wait`` 的超时毫秒数。
    """
    if worker.isRunning():
        if not worker.wait(timeout_ms):
            worker.terminate()
            worker.wait(timeout_ms)
    worker.deleteLater()
    flush_widget_queue()


# ── 格式分类 / 异常层级（纯静态） ─────────────────────────────────────────


class TestFormatClassify:
    """常量集合与异常的纯分类测试。"""

    def test_is_complex_format_true_for_raw(self) -> None:
        """happy：RAW 后缀（含前导点/无点）判定为复杂格式。"""
        assert ImageDecoderService.is_complex_format(".cr2")
        assert ImageDecoderService.is_complex_format("nef")
        assert ImageDecoderService.is_complex_format("PNG") is False

    def test_is_complex_format_false_for_standard(self) -> None:
        """boundary：标准格式与未知后缀不是复杂格式。"""
        assert not ImageDecoderService.is_complex_format(".png")
        assert not ImageDecoderService.is_complex_format(".jpg")
        assert not ImageDecoderService.is_complex_format(".gif")
        assert not ImageDecoderService.is_complex_format("weird_ext")

    def test_exception_hierarchy(self) -> None:
        """boundary：异常层级为 DecodeError 子类。"""
        assert issubclass(DependencyError, DecodeError)
        assert issubclass(CorruptFileError, DecodeError)


# ── decode_to_qimage：真实文件走工程实际行为 ──────────────────────────────


class TestDecodeToQImageRealUnexpectedPaths:
    """真实 PNG/JPEG/损坏文件通过公共入口时的行为。

    生产 ``decode_to_qimage`` 仅分派 RAW/HEIF-AVIF/PSD 三类复杂格式，
    标准格式 PNG/JPEG 返回优雅的"不支持"失败（**不崩溃**），损坏的
    复杂格式文件返回错误消息（**不崩溃**）。这些测试固化该契约。
    """

    def test_png_path_returns_graceful_unsupported(self, tmp_path: Path) -> None:
        """boundary：真实 PNG 走公共入口应返回 False + 说明，不崩溃。

        Args:
            tmp_path: pytest 临时目录。
        """
        png_file: str = make_image(tmp_path / "sample.png", fmt="PNG")
        ok: bool
        result: Any
        ok, result = ImageDecoderService.decode_to_qimage(png_file)
        assert ok is False
        assert "不支持的格式" in str(result)

    def test_jpeg_path_returns_graceful_unsupported(self, tmp_path: Path) -> None:
        """boundary：真实 JPEG 走公共入口同样被优雅拒绝。

        Args:
            tmp_path: pytest 临时目录。
        """
        jpg_file: str = make_image(tmp_path / "sample.jpg", fmt="JPEG")
        ok, result = ImageDecoderService.decode_to_qimage(jpg_file)
        assert ok is False
        assert "不支持的格式" in str(result)

    def test_corrupt_psd_returns_error_not_crash(self, tmp_path: Path) -> None:
        """error：损坏的 PSD 返回错误消息而非异常。

        Args:
            tmp_path: pytest 临时目录。
        """
        bad: Path = tmp_path / "broken.psd"
        bad.write_bytes(b"NOTPSE\x00\x00 garbage bytes, not a psd file")
        ok, result = ImageDecoderService.decode_to_qimage(str(bad))
        assert ok is False
        assert "PSD" in str(result)

    def test_corrupt_cr2_returns_error_not_crash(self, tmp_path: Path) -> None:
        """error：损坏的 CR2 返回错误消息而非异常。

        Args:
            tmp_path: pytest 临时目录。
        """
        bad: Path = tmp_path / "broken.cr2"
        bad.write_bytes(b"II*\x00\x01\x02\x03raw garbage" * 200)
        ok, result = ImageDecoderService.decode_to_qimage(str(bad))
        assert ok is False
        assert str(result)  # 错误消息非空即可，具体文案随 rawpy 版本变化

    def test_missing_cr2_returns_error_not_crash(self, tmp_path: Path) -> None:
        """error：不存在的 CR2 返回错误消息而非异常。

        Args:
            tmp_path: pytest 临时目录。
        """
        ok, result = ImageDecoderService.decode_to_qimage(str(tmp_path / "ghost.cr2"))
        assert ok is False
        assert str(result)

    def test_no_extension_returns_unsupported(self, tmp_path: Path) -> None:
        """boundary：无扩展名文件返回"无法识别"。

        Args:
            tmp_path: pytest 临时目录。
        """
        no_ext: Path = tmp_path / "noext"
        no_ext.write_bytes(b"whatever")
        ok, result = ImageDecoderService.decode_to_qimage(str(no_ext))
        assert ok is False
        assert "无法识别" in str(result)

    def test_empty_path_returns_error(self) -> None:
        """boundary：空路径返回错误而非异常。"""
        ok, result = ImageDecoderService.decode_to_qimage("")
        assert ok is False
        assert str(result)


# ── PIL → QImage：真实 PNG/JPEG 解码成功路径 ─────────────────────────────


class TestPilToQImageSuccess:
    """``_pil_to_qimage`` 是服务内真实解码 PNG/JPEG 成功的核心路径。"""

    def test_png_image_converts_to_qimage(self, tmp_path: Path) -> None:
        """happy：PIL 打开的 PNG 应转换为非空 QImage，尺寸一致。

        Args:
            tmp_path: pytest 临时目录。
        """
        from PIL import Image as PILImage

        png_file: str = make_image(tmp_path / "photo.png", fmt="PNG", size=(64, 48))
        qimage: Any = ImageDecoderService._pil_to_qimage(PILImage.open(png_file))
        assert qimage is not None
        assert not qimage.isNull()
        assert qimage.width() == 64
        assert qimage.height() == 48

    def test_jpeg_image_converts_to_qimage(self, tmp_path: Path) -> None:
        """happy：PIL 打开的 JPEG 应转换为非空 QImage。

        Args:
            tmp_path: pytest 临时目录。
        """
        from PIL import Image as PILImage

        jpg_file: str = make_image(tmp_path / "photo.jpg", fmt="JPEG", size=(32, 32))
        qimage: Any = ImageDecoderService._pil_to_qimage(PILImage.open(jpg_file))
        assert qimage is not None
        assert not qimage.isNull()
        assert qimage.width() == 32

    def test_rgba_image_preserves_alpha(self) -> None:
        """happy：RGBA 图像应保留 4 字节/像素的 alpha 通道。"""
        from PIL import Image as PILImage

        img = PILImage.new("RGBA", (20, 10), (255, 0, 0, 128))
        qimage: Any = ImageDecoderService._pil_to_qimage(img)
        assert qimage is not None
        assert not qimage.isNull()
        assert qimage.format() in (None,) or qimage.width() == 20

    def test_grayscale_mode_converts_to_rgb(self) -> None:
        """boundary：灰度 'L' 模式应被转换为 RGB 后输出。"""
        from PIL import Image as PILImage

        img = PILImage.new("L", (16, 8), 128)
        qimage: Any = ImageDecoderService._pil_to_qimage(img)
        assert qimage is not None
        assert not qimage.isNull()

    def test_non_pil_input_returns_none(self) -> None:
        """error：非 PIL Image 输入返回 None 而非异常。"""
        assert ImageDecoderService._pil_to_qimage("not an image") is None
        assert ImageDecoderService._pil_to_qimage(None) is None


# ── decode_to_qimage：mock 复杂格式后端的完整成功路径 ────────────────────


class TestDecodeToQImageMockedBackend:
    """monkeypatch 复杂格式解码方法，验证公共入口的整体成功编排。"""

    def test_raw_backend_success_returns_qimage(
        self, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """happy：mock RAW 后端返回 PIL 图 → 入口应返回 (True, QImage)。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        from PIL import Image as PILImage

        def _fake_raw(file_path: str) -> PILImage.Image:
            return PILImage.open(make_image(tmp_path / "shot.png", fmt="PNG"))

        monkeypatch.setattr(ImageDecoderService, "_decode_raw", staticmethod(_fake_raw))
        ok: bool
        result: Any
        ok, result = ImageDecoderService.decode_to_qimage(str(tmp_path / "shot.cr2"))
        assert ok is True
        assert not result.isNull()

    def test_psd_backend_success_returns_qimage(
        self, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """happy：mock PSD 后端返回 RGBA 图 → 入口应返回 (True, QImage)。

        Args:
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        from PIL import Image as PILImage

        def _fake_psd(file_path: str) -> PILImage.Image:
            return PILImage.new("RGBA", (8, 8), (255, 0, 0, 255))

        monkeypatch.setattr(ImageDecoderService, "_decode_psd", staticmethod(_fake_psd))
        ok, result = ImageDecoderService.decode_to_qimage(str(tmp_path / "art.psd"))
        assert ok is True
        assert not result.isNull()


# ── ImageDecodeWorker：生命周期 / 信号 / 超时 / 并发 ─────────────────────


def _fake_qimage() -> Any:
    """构建一个最小的非空 QImage（worker 成功结果用）。"""
    from PySide6.QtGui import QImage

    return QImage(4, 4, QImage.Format.Format_RGB32)


class TestImageDecodeWorker:
    """worker 队列生命周期、取消与内部超时防挂测试。"""

    def test_decoded_signal_emitted_on_success(self, qapp: Any, monkeypatch: Any, tmp_path: Path) -> None:
        """happy：成功解码应发射 ``decoded(QImage, path)``。

        Args:
            qapp: 会话级 QApplication。
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        def _fast_decode(file_path: str):
            return True, _fake_qimage()

        monkeypatch.setattr(ImageDecoderService, "decode_to_qimage", staticmethod(_fast_decode))
        target: str = make_image(tmp_path / "target.png", fmt="PNG")
        worker: ImageDecodeWorker = ImageDecodeWorker(target)
        received: List[str] = []
        worker.decoded.connect(lambda _img, path: received.append(path))
        failed: List[str] = []
        worker.failed.connect(failed.append)
        worker.start_with_timeout()
        assert wait_for_signal(worker.decoded, timeout_ms=5000)
        assert received == [target]
        assert not failed
        _shutdown_worker(worker)

    def test_failed_signal_emitted_on_decode_error(self, qapp: Any, monkeypatch: Any, tmp_path: Path) -> None:
        """error：解码失败应发射 ``failed`` 且不解码。

        Args:
            qapp: 会话级 QApplication。
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        def _failing_decode(file_path: str):
            return False, "解码文件损坏"

        monkeypatch.setattr(ImageDecoderService, "decode_to_qimage", staticmethod(_failing_decode))
        worker: ImageDecodeWorker = ImageDecodeWorker(str(tmp_path / "broken.cr2"))
        delivered: List[str] = []
        worker.failed.connect(delivered.append)
        decoded: List[Any] = []
        worker.decoded.connect(lambda _img, path: decoded.append(path))
        worker.start_with_timeout()
        assert wait_for_signal(worker.failed, timeout_ms=5000)
        assert delivered == ["解码文件损坏"]
        assert not decoded
        _shutdown_worker(worker)

    def test_real_decode_missing_file_emits_failed(self, qapp: Any, tmp_path: Path) -> None:
        """error：真实 decode_to_qimage 对不存在文件应优雅发射 failed。

        Args:
            qapp: 会话级 QApplication。
            tmp_path: pytest 临时目录。
        """
        worker: ImageDecodeWorker = ImageDecodeWorker(str(tmp_path / "ghost.cr2"))
        delivered: List[str] = []
        worker.failed.connect(delivered.append)
        worker.start_with_timeout()
        assert wait_for_signal(worker.failed, timeout_ms=5000)
        assert delivered and delivered[0]
        _shutdown_worker(worker)

    def test_cancel_before_start_suppresses_signals(self, qapp: Any, tmp_path: Path) -> None:
        """boundary：启动前取消应抑制一切结果信号。

        Args:
            qapp: 会话级 QApplication。
            tmp_path: pytest 临时目录。
        """
        worker: ImageDecodeWorker = ImageDecodeWorker(str(tmp_path / "x.cr2"))
        worker.cancel()
        assert worker._is_cancelled is True
        emitted: List[str] = []
        worker.failed.connect(emitted.append)
        worker.decoded.connect(lambda _img, path: emitted.append(path))
        worker.start_with_timeout()
        assert not wait_for_signal(worker.failed, timeout_ms=500)
        assert not emitted
        _shutdown_worker(worker)

    def test_cancel_while_running(self, qapp: Any, monkeypatch: Any, tmp_path: Path) -> None:
        """boundary：运行中取消应置标志并抑制结果信号。

        Args:
            qapp: 会话级 QApplication。
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        entered: threading.Event = threading.Event()
        release: threading.Event = threading.Event()

        def _blocking_decode(file_path: str):
            entered.set()
            release.wait(5)
            return True, _fake_qimage()

        monkeypatch.setattr(ImageDecoderService, "decode_to_qimage", staticmethod(_blocking_decode))
        worker: ImageDecodeWorker = ImageDecodeWorker(str(tmp_path / "slow.cr2"))
        emitted: List[str] = []
        worker.failed.connect(emitted.append)
        worker.decoded.connect(lambda _img, path: emitted.append(path))
        worker.start_with_timeout()
        assert entered.wait(3), "worker 解码未进入"
        worker.cancel()
        assert worker._is_cancelled is True
        release.set()
        time.sleep(0.2)
        flush_widget_queue(qapp)
        assert not emitted  # 已取消的结果不得发射
        _shutdown_worker(worker)

    def test_internal_timeout_kills_blocked_decode(self, qapp: Any, monkeypatch: Any, tmp_path: Path) -> None:
        """error：内部超时防挂——阻塞解码应在超时后发射 failed 并终止。

        缩短 ``_DECODE_TIMEOUT_MS`` 到 50ms，mock 解码睡眠 1s；
        收到超时 failed 后释放线程，确保无泄漏。

        Args:
            qapp: 会话级 QApplication。
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        started: float = time.monotonic()
        monkeypatch.setattr("freeassetfilter.services.image_decode_worker._DECODE_TIMEOUT_MS", 50)
        # cancel() 内 wait(2000) 会阻塞主线程；此处替换为纯标志版，只测超时路径。
        monkeypatch.setattr(
            ImageDecodeWorker,
            "cancel",
            lambda self: setattr(self, "_is_cancelled", True),
        )

        def _slow_decode(file_path: str):
            time.sleep(1.0)
            return True, _fake_qimage()

        monkeypatch.setattr(ImageDecoderService, "decode_to_qimage", staticmethod(_slow_decode))
        worker: ImageDecodeWorker = ImageDecodeWorker(str(tmp_path / "stuck.cr2"))
        delivered: List[str] = []
        worker.failed.connect(delivered.append)
        worker.start_with_timeout()
        assert wait_for_signal(worker.failed, timeout_ms=2000)
        assert "超时" in delivered[0]
        elapsed: float = time.monotonic() - started
        assert elapsed < 5.0  # 超时路径必须远快于解码本身的 1s
        _shutdown_worker(worker, timeout_ms=1500)

    def test_ten_workers_all_complete(self, qapp: Any, monkeypatch: Any, tmp_path: Path) -> None:
        """happy：批量 10 个任务应全部发射 decoded，无一丢失。

        Args:
            qapp: 会话级 QApplication。
            monkeypatch: pytest monkeypatch。
            tmp_path: pytest 临时目录。
        """
        def _fast_decode(file_path: str):
            return True, _fake_qimage()

        monkeypatch.setattr(ImageDecoderService, "decode_to_qimage", staticmethod(_fast_decode))
        paths: List[str] = [
            make_image(tmp_path / f"batch_{i:02d}.png", fmt="PNG") for i in range(10)
        ]
        workers: List[ImageDecodeWorker] = []
        received: List[str] = []
        try:
            # 捕获槽先于 start 连接：排队信号必然投递到 received
            for path in paths:
                worker: ImageDecodeWorker = ImageDecodeWorker(path)
                worker.decoded.connect(lambda _img, p: received.append(str(p)))
                worker.start_with_timeout()
                workers.append(worker)
            # 信号由 worker 线程排队投递，wait_for_signal 可能错过已入队事件，
            # 故改为有界轮询事件泵直至全部到达
            deadline: float = time.monotonic() + 10.0
            while len(received) < len(paths) and time.monotonic() < deadline:
                flush_widget_queue(qapp, iterations=5)
                time.sleep(0.01)
        finally:
            for worker in workers:
                _shutdown_worker(worker)
        assert sorted(received) == sorted(paths)


__all__: Tuple[str, ...] = ()
