# -*- coding: utf-8 -*-
"""布局层单元测试（todo-23 批 3 / task-23）。

覆盖 ui/layout 下 11 个布局模块的构造契约、尺寸生效与 set_file 分发：
全部 QWidget 布局以默认参数构造、放入内容后 geometry 非空；
带 ``set_file`` 入口的布局对缺失路径安全降级（不抛异常、返回 False 或
停留在 overlay）；``PreviewFullscreenHost`` 在无父窗口时进出全屏不抛；
``VideoPlayerLayout`` 在无 libmpv 时不真实播放（缺失路径直接返回 False）。

验证命令：
    python -m pytest tests/unit/ui/layout/test_layouts.py --timeout 60 -q
"""

# targets: ui.layout.file_pool_layout, ui.layout.file_selector_layout,
#          ui.layout.settings_layout, ui.layout.unified_previewer_layout,
#          ui.layout.preview.font_previewer_layout,
#          ui.layout.preview.fullscreen_host,
#          ui.layout.preview.image_previewer_layout,
#          ui.layout.preview.office_previewer_layout,
#          ui.layout.preview.pdf_previewer_layout,
#          ui.layout.preview.text_previewer_layout,
#          ui.layout.preview.video_player_layout

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QObject, Qt, QThread, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QEnterEvent,
    QHideEvent,
    QMouseEvent,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

# 布局模块内部使用短路径导入（from theme import tm / components.*），
# 要求 freeassetfilter/ui 位于 sys.path；与 layout/preview 模块自身的
# bootstrap 保持一致（详见 file_pool_layout.py:46 的用法）。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.layout.file_pool_layout import FilePoolLayout
from freeassetfilter.ui.layout.file_selector_layout import FileSelectorLayout
from freeassetfilter.ui.layout.preview.font_previewer_layout import (
    DEFAULT_PREVIEW_TEXT,
    FontLoadThread,
    FontPreviewerLayout,
)
from freeassetfilter.ui.layout.preview.fullscreen_host import PreviewFullscreenHost
from freeassetfilter.ui.layout.preview.image_previewer_layout import ImagePreviewerLayout
import freeassetfilter.ui.layout.preview.office_previewer_layout as _opl
from freeassetfilter.ui.layout.preview.office_previewer_layout import (
    OfficePreviewerLayout,
)
from freeassetfilter.ui.layout.preview.pdf_previewer_layout import PdfPreviewerLayout
from freeassetfilter.ui.layout.preview.text_previewer_layout import TextPreviewerLayout
import freeassetfilter.ui.layout.preview.text_previewer_layout as _tpl
from freeassetfilter.ui.layout.preview.video_player_layout import VideoPlayerLayout
from freeassetfilter.ui.layout.settings_layout import (
    AccentColorButton,
    AppearanceSettingsPage,
    CustomAccentButton,
    SettingsLayout,
)
from freeassetfilter.ui.layout.unified_previewer_layout import UnifiedPreviewerLayout

from tests.support.qt_helpers import safe_teardown  # noqa: E402

pytestmark = pytest.mark.unit

_MISSING_FILE: str = "C:/definitely/missing_file.xyz"
_LAYOUT_SIZE: tuple[int, int] = (640, 480)

#: 一张最小 1x1 PNG 的字节内容（用作 todo-30 音频封面 / 调色板输入）。
_MINI_PNG_BYTES: bytes = (
    b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00\x00\x00\x01"
    + b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0c"
    + b"IDAT\x08\xd7c\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01" + b"4\x8f\x88"
    + b"\x7d\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _FakeAudioInfo:
    """模拟 ``mutagen`` 音频对象的 ``.info``（编码参数）。"""

    def __init__(self) -> None:
        """初始化最小参数（时长/比特率/声道/采样率）。"""
        self.length = 3.5
        self.bitrate = 128000
        self.channels = 2
        self.sample_rate = 44100


class _FakeFrame:
    """模拟 ID3 / APIC frame 对象：带二进制 ``.data``。"""

    def __init__(self, data: Optional[bytes] = None) -> None:
        """初始化假 frame。

        Args:
            data: 二进制负载（封面用）。
        """
        self.data: Optional[bytes] = data


class _FakeAudio:
    """模拟 ``mutagen.File`` 的返回值（dict 风格 tags + info）。"""

    def __init__(self, tags: Optional[Dict[str, Any]] = None,
                 info: Optional[Any] = None) -> None:
        """初始化假音频对象。

        Args:
            tags: 标签容器（dict 风格）。
            info: 信息对象。
        """
        self.tags: Optional[Dict[str, Any]] = tags
        self.info: Optional[Any] = info or _FakeAudioInfo()


class _CountingMarkdownRenderer:
    """Markdown 渲染测试替身：记录 render() 调用次数与最后一次字号。

    与真实 ``MarkdownRenderer`` 保持同一构造/调用契约（``font_size`` 关键字、
    ``is_available()``、``set_font_size()``、``render(text, file_path)``），
    供字号防抖与异步渲染计数断言使用。渲染返回内嵌字号与输入长度的
    可断言内容。
    """

    call_count = 0
    last_font_size: Optional[int] = None

    def __init__(self, font_size: int = 14) -> None:
        """与真实渲染器一致的构造契约。"""
        self._font_size = font_size

    @classmethod
    def is_available(cls) -> bool:
        """模拟 markdown + pygments 可用。"""
        return True

    def set_font_size(self, size: int) -> None:
        """与真实渲染器一致的字号设置。"""
        self._font_size = size

    def render(self, text: str, file_path: Optional[str] = None) -> str:
        """返回内嵌字号与输入长度的可断言 HTML。"""
        _CountingMarkdownRenderer.call_count += 1
        _CountingMarkdownRenderer.last_font_size = self._font_size
        return f"<p>rendered-{self._font_size}:{len(text)}</p>"


class _SlowMarkdownRenderer:
    """Markdown 渲染测试替身：``SLOW`` 输入时阻塞 400ms 模拟慢渲染。

    用于「快速切换文件 → 陈旧 token 丢弃旧渲染结果」的时序验证。
    """

    def __init__(self, font_size: int = 14) -> None:
        """与真实渲染器一致的构造契约。"""
        self._font_size = font_size

    @classmethod
    def is_available(cls) -> bool:
        """模拟 markdown + pygments 可用。"""
        return True

    def set_font_size(self, size: int) -> None:
        """与真实渲染器一致的字号设置。"""
        self._font_size = size

    def render(self, text: str, file_path: Optional[str] = None) -> str:
        """慢路径 sleep 后返回文本透传内容。"""
        if "SLOW" in text:
            time.sleep(0.4)
        return f"<p>out-{text}</p>"


def _assert_layout_geometry(widget: QWidget, qapp: QApplication) -> None:
    """宿主 resize 后 geometry 有效（尺寸用例的公共断言）。"""
    widget.resize(*_LAYOUT_SIZE)
    qapp.processEvents()
    assert widget.width() > 0
    assert widget.height() == 480


def _pump_events(qapp: QApplication, ms: float = 300) -> None:
    """有界事件泵：让布局/尺寸事件与重绘完成。"""
    deadline = time.time() + ms / 1000
    while time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)


def _pump_until(
    qapp: QApplication,
    predicate: Any,
    timeout_ms: int = 3000,
) -> bool:
    """有界事件泵直到谓词成立（供异步 Markdown 渲染结果回写等待）。"""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# =============================================================================
# ui.layout.file_pool_layout
# =============================================================================
class TestFilePoolLayout:
    """文件池布局：构造契约、add_file 入池与尺寸生效。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = FilePoolLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_add_file_and_query(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """add_file 入池后 has_file / get_pool_paths 可见，可安全移除。"""
        # 禁用删除动画，使 remove_file 同步完成（否则经 _removing_paths 异步走）
        import freeassetfilter.ui.layout.file_pool_layout as fpl_mod

        monkeypatch.setattr(
            fpl_mod, "is_animation_enabled", lambda *args, **kwargs: False
        )
        layout = FilePoolLayout()
        _assert_layout_geometry(layout, qapp)
        file_path = "D:/dummy/file_pool_sample.png"
        layout.add_file({"path": file_path, "name": "file_pool_sample.png"})
        assert layout.has_file(file_path) is True
        assert file_path.replace("/", "\\") in layout.get_pool_paths() or file_path in layout.get_pool_paths()
        layout.remove_file(file_path)
        assert layout.has_file(file_path) is False
        layout.deleteLater()


def _legacy_unique_target(directory: str, filename: str) -> str:
    """改造前冲突改名算法（oracle，等价 ``_get_unique_target_path``）。"""
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base}_{counter}{ext}")
        counter += 1
    return candidate


def _legacy_export_flat(files: list, target_dir: str) -> tuple:
    """改造前 ``copy_files`` 逐文件顺序复制（语义 oracle）。"""
    success = 0
    failed = 0
    errors = []
    for i, fi in enumerate(files):
        src = fi.get("path", "")
        display_name = fi.get("display_name", os.path.basename(src))
        dst = _legacy_unique_target(target_dir, display_name)
        try:
            if fi.get("is_dir"):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
            success += 1
        except (IOError, OSError, PermissionError, shutil.Error) as e:
            failed += 1
            errors.append(f"{fi.get('display_name', '?')}: {e}")
    return success, failed, errors


def _legacy_export_categorized(files: list, target_dir: str) -> tuple:
    """改造前 ``copy_files_categorized``（语义 oracle）。"""
    success = 0
    failed = 0
    errors = []
    for i, fi in enumerate(files):
        src = fi.get("path", "")
        source_dir = os.path.dirname(src)
        category = os.path.basename(source_dir) or "未分类"
        cat_dir = os.path.join(target_dir, category)
        try:
            os.makedirs(cat_dir, exist_ok=True)
        except (IOError, OSError) as e:
            failed += 1
            errors.append(f"{fi.get('display_name', '?')}: 创建分类目录失败 - {e}")
            continue
        dst = os.path.join(cat_dir, fi.get("display_name", os.path.basename(src)))
        dst = _legacy_unique_target(cat_dir, os.path.basename(dst))
        try:
            if fi.get("is_dir"):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
            success += 1
        except (IOError, OSError, PermissionError, shutil.Error) as e:
            failed += 1
            errors.append(f"{fi.get('display_name', '?')}: {e}")
    return success, failed, errors


def _snapshot_tree(root: str) -> Dict[str, bytes]:
    """递归快照目录树：相对路径 → 文件字节（不含目录条目）。"""
    snap: Dict[str, bytes] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            with open(full, "rb") as f:
                snap[rel] = f.read()
    return snap


class _FakeBridge:
    """faf_core 桥确定性替身（语义等价 native 批量复制 / 大小聚合）。

    - ``copy_files`` 记录每次调用（批次）并做真实 ``copy2/copytree``
      （目标名 = 源文件名），返回 ``{"copied","failed"}``；
    - ``available=False`` 时模拟 DLL 缺失（调用方回退 Python）；
    - ``gate`` 钩子在每次批量调用开始时触发（批次间取消测试用）。
    """

    def __init__(self, available: bool = True) -> None:
        self.available = available
        self._supports_copy = available
        self._supports_sizesum = available
        self.calls: List[List[str]] = []
        self.fail_all = False
        self.gate = None

    def copy_files(self, sources: list, dest_dir: str):
        batch = list(sources)
        self.calls.append(batch)
        if self.fail_all:
            return None
        if self.gate is not None:
            self.gate(len(self.calls))
        copied = []
        failed = []
        for src in sources:
            try:
                name = os.path.basename(src)
                dst = os.path.join(dest_dir, name)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
                copied.append(
                    {"src": src, "dst": dst, "size": os.path.getsize(src)}
                )
            except Exception as e:  # noqa: BLE001  # per-file 失败不中断整批
                failed.append({"src": src, "error": str(e)})
        return {"copied": copied, "failed": failed}

    def sum_directory_sizes(self, paths: list):
        results = []
        for p in paths:
            try:
                total = 0
                for dirpath, _dirs, files in os.walk(p):
                    for name in files:
                        try:
                            total += os.path.getsize(os.path.join(dirpath, name))
                        except OSError:
                            continue
                results.append({"path": p, "size": total, "error": None})
            except OSError as e:
                results.append({"path": p, "size": 0, "error": str(e)})
        return {"results": results}


def _patch_fpl_bridge(monkeypatch: pytest.MonkeyPatch, bridge) -> Any:
    """替换 ``file_pool_layout`` 模块内的 ``get_faf_core_bridge``。"""
    import freeassetfilter.ui.layout.file_pool_layout as fpl_mod

    monkeypatch.setattr(fpl_mod, "get_faf_core_bridge", lambda: bridge)
    return fpl_mod


def _export_items(tmp_path: Path) -> List[Dict[str, str]]:
    """构造一组含同名冲突/自定义 display_name 的导出项。"""
    dir1 = tmp_path / "dir1"
    dir1.mkdir()
    (dir1 / "a.txt").write_bytes(b"content-A")
    (dir1 / "b.txt").write_bytes(b"content-B")
    dir2 = tmp_path / "dir2"
    dir2.mkdir()
    (dir2 / "a.txt").write_bytes(b"content-A2")
    tree = dir1 / "tree"
    (tree / "sub").mkdir(parents=True)
    (tree / "sub" / "leaf.txt").write_bytes(b"leaf")
    return [
        {"path": str(dir1 / "a.txt"), "display_name": "a.txt"},
        {"path": str(dir2 / "a.txt"), "display_name": "a.txt"},  # 同名冲突
        {"path": str(dir1 / "b.txt"), "display_name": "b.txt"},
        {"path": str(dir1 / "b.txt"), "display_name": "rename.txt"},  # 自定义名
        {"path": str(tree), "display_name": "tree", "is_dir": True},  # 目录项
    ]


class TestFilePoolLayoutExport:
    """导出复制接线：native 分批 / 冲突改名 / 错误元组顺序 / 进度单调 / 取消。"""

    def test_export_batches_capped_at_32(self, qapp: QApplication,
                                         monkeypatch: pytest.MonkeyPatch,
                                         tmp_path: Path) -> None:
        """native 批 ≤32/批：70 文件 → 3 批（32/32/6），全部落地且批尺寸合规。"""
        src = tmp_path / "src"
        src.mkdir()
        files = []
        for i in range(70):
            f = src / f"f{i:02}.txt"
            f.write_bytes(bytes(100 + i))
            files.append({"path": str(f), "display_name": f.name})
        bridge = _FakeBridge(available=True)
        _patch_fpl_bridge(monkeypatch, bridge)
        out = tmp_path / "out"
        out.mkdir()
        layout = FilePoolLayout()
        s, f, e = layout.copy_files(files, str(out))
        assert s == 70 and f == 0 and e == []
        assert bridge.calls, "native 路径应被调用"
        for batch in bridge.calls:
            assert len(batch) <= 32, "单批不得超过 _EXPORT_BATCH_SIZE"
        assert len(bridge.calls) == 3, "70 文件应分 3 批（32/32/6）"
        assert len(os.listdir(out)) == 70

    def test_export_conflict_rename_matches_legacy(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """冲突改名结果与改造前字节一致（native 可用 / 假桥 / DLL 缺失三态）。"""
        from freeassetfilter.core.native.bridges.faf_core_bridge import (
            FafCoreBridge,
        )

        cases = [
            ("fallback", _FakeBridge(available=False)),
            ("native-fake", _FakeBridge(available=True)),
        ]
        if FafCoreBridge().available and FafCoreBridge()._supports_copy:  # noqa: SLF001
            cases.append(("native-real", None))

        # 目标目录里预置同名文件，进一步触发改名链。
        items = _export_items(tmp_path)
        for label, bridge in cases:
            out_new = tmp_path / f"out_new_{label}"
            out_new.mkdir()
            (out_new / "a.txt").write_bytes(b"preexisting")
            out_legacy = tmp_path / f"out_legacy_{label}"
            out_legacy.mkdir()
            (out_legacy / "a.txt").write_bytes(b"preexisting")

            if bridge is None:
                # 真实 DLL 路径：恢复真正的单例取回器。
                import freeassetfilter.ui.layout.file_pool_layout as fpl_mod
                from freeassetfilter.core.native.bridges.faf_core_bridge import (
                    get_faf_core_bridge as _real_getter,
                )

                monkeypatch.setattr(
                    fpl_mod, "get_faf_core_bridge", lambda: _real_getter()
                )
            else:
                _patch_fpl_bridge(monkeypatch, bridge)
            layout = FilePoolLayout()
            s_new, f_new, e_new = layout.copy_files(items, str(out_new))
            s_leg, f_leg, e_leg = _legacy_export_flat(items, str(out_legacy))

            assert s_new == s_leg, f"[{label}] 成功数与 oracle 不一致: {s_new} vs {s_leg}"
            assert f_new == f_leg, f"[{label}] 失败数与 oracle 不一致: {f_new} vs {f_leg}"
            assert _snapshot_tree(str(out_new)) == _snapshot_tree(
                str(out_legacy)
            ), f"[{label}] 导出结果与 oracle 字节不一致"
            # 错误元组顺序：仅比较失败的 display 名序列（native 错误串不参与）。
            failed_names_new = [err.split(":")[0] for err in e_new]
            failed_names_leg = [err.split(":")[0] for err in e_leg]
            assert failed_names_new == failed_names_leg, (
                f"[{label}] 错误元组顺序不一致: {failed_names_new} vs {failed_names_leg}"
            )

    def test_export_categorized_matches_legacy(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """分类导出的结果与改造前字节一致（含类目内同名冲突）。"""
        bridge = _FakeBridge(available=True)
        _patch_fpl_bridge(monkeypatch, bridge)
        items = _export_items(tmp_path)
        out_new = tmp_path / "out_new"
        out_new.mkdir()
        out_legacy = tmp_path / "out_legacy"
        out_legacy.mkdir()
        layout = FilePoolLayout()
        s_new, f_new, _ = layout.copy_files_categorized(items, str(out_new))
        s_leg, f_leg, _ = _legacy_export_categorized(items, str(out_legacy))
        assert s_new == s_leg and f_new == f_leg
        assert _snapshot_tree(str(out_new)) == _snapshot_tree(str(out_legacy))

    def test_export_error_tuple_order_consistent(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """错误元组 (success, failed, errors) 顺序与输入序一致（native 与回退）。"""
        src = tmp_path / "src"
        src.mkdir()
        ok1 = src / "ok1.txt"
        ok1.write_bytes(b"1")
        ok2 = src / "ok2.txt"
        ok2.write_bytes(b"2")
        missing1 = tmp_path / "ghost1.txt"
        missing2 = tmp_path / "ghost2.txt"
        files = [
            {"path": str(ok1), "display_name": "ok1.txt"},
            {"path": str(missing1), "display_name": "ghost1.txt"},
            {"path": str(ok2), "display_name": "ok2.txt"},
            {"path": str(missing2), "display_name": "ghost2.txt"},
        ]
        bridge = _FakeBridge(available=True)
        _patch_fpl_bridge(monkeypatch, bridge)
        out = tmp_path / "out"
        out.mkdir()
        layout = FilePoolLayout()
        s, f, e = layout.copy_files(files, str(out))
        assert s == 2 and f == 2
        assert [err.split(":")[0] for err in e] == ["ghost1.txt", "ghost2.txt"]

        # 回退路径同构。
        out2 = tmp_path / "out2"
        out2.mkdir()
        bridge2 = _FakeBridge(available=False)
        _patch_fpl_bridge(monkeypatch, bridge2)
        layout2 = FilePoolLayout()
        s2, f2, e2 = layout2.copy_files(files, str(out2))
        assert s2 == 2 and f2 == 2
        assert [err.split(":")[0] for err in e2] == ["ghost1.txt", "ghost2.txt"]

    def test_export_progress_monotonic(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """进度信号计数单调递增且终结于 len(files)（native 分批补发）。"""
        src = tmp_path / "src"
        src.mkdir()
        files = []
        for i in range(40):
            f = src / f"f{i:02}.txt"
            f.write_bytes(bytes(10))
            files.append({"path": str(f), "display_name": f.name})
        bridge = _FakeBridge(available=True)
        _patch_fpl_bridge(monkeypatch, bridge)
        out = tmp_path / "out"
        out.mkdir()
        layout = FilePoolLayout()
        got: List[int] = []
        layout.update_progress.connect(lambda v: got.append(int(v)))
        layout.copy_files(files, str(out))
        assert len(got) == len(files)
        assert all((got[i + 1] - got[i]) >= 1 for i in range(len(got) - 1)), (
            "进度必须单调递增"
        )
        assert got == list(range(1, len(files) + 1))

    def test_export_batch_cancel_under_500ms(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """批次间取消响应 <500ms：正在执行的批完成后立即终止，不再开新批。"""
        src = tmp_path / "src"
        src.mkdir()
        files = []
        for i in range(40):
            f = src / f"f{i:02}.txt"
            f.write_bytes(bytes(10))
            files.append({"path": str(f), "display_name": f.name})
        out = tmp_path / "out"
        out.mkdir()

        first_started = threading.Event()
        release = threading.Event()
        stop = threading.Event()

        class GatedBridge:
            available = True
            _supports_copy = True
            _supports_sizesum = True

            def __init__(self) -> None:
                self.calls: List[List[str]] = []

            def copy_files(self, sources: list, dest_dir: str):
                self.calls.append(list(sources))
                if len(self.calls) == 1:
                    first_started.set()
                    release.wait(10)
                return {
                    "copied": [
                        {"src": s, "dst": os.path.join(dest_dir, os.path.basename(s)),
                         "size": 1}
                        for s in sources
                    ],
                    "failed": [],
                }

        gated = GatedBridge()
        _patch_fpl_bridge(monkeypatch, gated)
        layout = FilePoolLayout()
        result_box: Dict[str, Any] = {}

        def _run() -> None:
            try:
                result_box["result"] = layout.copy_files(
                    files, str(out), should_stop=lambda: stop.is_set()
                )
            except Exception as ex:  # noqa: BLE001  # 记录线程异常
                result_box["error"] = repr(ex)

        t = threading.Thread(target=_run)
        start = time.perf_counter()
        t.start()
        assert first_started.wait(10), "第一批 native 调用必须启动"
        # 批次间取消：第一批仍在执行时置位 → 批完成后下个边界立即返回。
        stop.set()
        release.set()
        t.join(10)
        elapsed = time.perf_counter() - start
        assert not t.is_alive(), "取消后复制线程应在批次边界立即返回"
        assert elapsed < 0.5, f"批次间取消响应应 <500ms，实际 {elapsed * 1000:.0f}ms"
        assert len(gated.calls) == 1, "取消后不得开启第二批"
        s, f, e = result_box["result"]
        assert s == 32, "第一批 32 个文件应已复制成功"
        assert f == 0
        assert e == []

    def test_export_single_large_file_is_atomic(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """说明性记录：单文件/单目录复制为原子操作，批量取消不适用于其中。"""
        # 单文件复制不进批次（批内 ≤32 也不覆盖本文件——无后续批边界可停）。
        # 该语义由 design 承诺，不做时序断言：仅验证单文件经 native 正常落地。
        bridge = _FakeBridge(available=True)
        _patch_fpl_bridge(monkeypatch, bridge)
        src = tmp_path / "big.bin"
        src.write_bytes(bytes(64 * 1024))
        out = tmp_path / "out"
        out.mkdir()
        layout = FilePoolLayout()
        s, f, e = layout.copy_files(
            [{"path": str(src), "display_name": "big.bin"}], str(out)
        )
        assert s == 1 and f == 0 and e == []
        assert (out / "big.bin").read_bytes() == bytes(64 * 1024)

    def test_export_dll_missing_falls_back_to_python(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """DLL 缺失（mock 探测 False）→ 回退 Python 复制路径，不调 native。"""
        bridge = _FakeBridge(available=False)
        _patch_fpl_bridge(monkeypatch, bridge)
        items = _export_items(tmp_path)
        out_new = tmp_path / "out_new"
        out_new.mkdir()
        out_legacy = tmp_path / "out_legacy"
        out_legacy.mkdir()
        layout = FilePoolLayout()
        s_new, f_new, _ = layout.copy_files(items, str(out_new))
        s_leg, f_leg, _ = _legacy_export_flat(items, str(out_legacy))
        assert s_new == s_leg and f_new == f_leg
        assert _snapshot_tree(str(out_new)) == _snapshot_tree(str(out_legacy))
        assert bridge.calls == [], "DLL 缺失时不得调用 native"

    def test_export_runnable_cancel_event(self, qapp: QApplication,
                                          tmp_path: Path) -> None:
        """``_ExportCopyRunnable`` 取消标记经 ``cancel_event`` 接线。"""
        import freeassetfilter.ui.layout.file_pool_layout as fpl_mod

        layout = FilePoolLayout()
        ev = threading.Event()
        runnable = fpl_mod._ExportCopyRunnable(
            layout, [], str(tmp_path), 0, cancel_event=ev
        )
        assert runnable._should_stop() is False
        ev.set()
        assert runnable._should_stop() is True
        layout.deleteLater()


# =============================================================================
# ui.layout.file_selector_layout
# =============================================================================
class TestFileSelectorLayout:
    """文件选择器布局：构造契约与尺寸生效。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = FileSelectorLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    @staticmethod
    def _make_target_file(tmp_path) -> Path:
        """在临时目录创建一个定位目标文件，返回其路径。"""
        target = tmp_path / "locate_target.txt"
        target.write_text("locate me", encoding="utf-8")
        return target

    def test_locate_file_navigates_and_highlights(
        self, qapp: QApplication, tmp_path: object, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """文件池预览文件不在当前目录：locate_file 导航到所在目录并高亮卡片。"""
        import os

        import freeassetfilter.ui.layout.file_selector_layout as fsl_mod

        messages: list = []
        monkeypatch.setattr(
            fsl_mod.FileSelectorLayout, "_show_message_dialog",
            lambda self, t, m: messages.append((t, m)),
        )

        target = self._make_target_file(tmp_path)
        layout = FileSelectorLayout()
        _assert_layout_geometry(layout, qapp)
        assert messages == []

        layout.locate_file({"path": str(target), "name": target.name})

        target_dir = os.path.abspath(os.path.normpath(str(tmp_path)))
        assert os.path.normcase(layout._current_path) == os.path.normcase(target_dir)
        assert layout._previewing_file_path is not None
        assert (
            os.path.normcase(layout._previewing_file_path)
            == os.path.normcase(str(target))
        )
        # 等待延后滚动的 singleShot 触达后安全清理
        import time

        time.sleep(0.25)
        qapp.processEvents()
        layout.deleteLater()

    def test_locate_file_same_directory_skips_navigation(
        self, qapp: QApplication, tmp_path: object, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """目标文件已在当前目录：locate_file 不重复导航，仅高亮滚动。"""
        import os

        import freeassetfilter.ui.layout.file_selector_layout as fsl_mod

        messages: list = []
        monkeypatch.setattr(
            fsl_mod.FileSelectorLayout, "_show_message_dialog",
            lambda self, t, m: messages.append((t, m)),
        )

        target = self._make_target_file(tmp_path)
        layout = FileSelectorLayout()
        _assert_layout_geometry(layout, qapp)

        layout._load_directory(os.path.abspath(str(tmp_path)))
        assert messages == []

        navigate_calls: list = []
        original_navigate = layout._navigate_to

        def _spy_navigate(path: str) -> None:
            navigate_calls.append(path)
            original_navigate(path)

        monkeypatch.setattr(layout, "_navigate_to", _spy_navigate)

        layout.locate_file({"path": str(target), "name": target.name})

        assert navigate_calls == []  # 目录未变，不触发导航
        assert layout._previewing_file_path is not None
        assert (
            os.path.normcase(layout._previewing_file_path)
            == os.path.normcase(str(target))
        )

        import time

        time.sleep(0.25)
        qapp.processEvents()
        layout.deleteLater()

    def test_locate_file_missing_directory_shows_message(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """目标目录不存在：弹提示且不导航、不高亮。"""
        import os

        import freeassetfilter.ui.layout.file_selector_layout as fsl_mod

        messages: list = []
        monkeypatch.setattr(
            fsl_mod.FileSelectorLayout, "_show_message_dialog",
            lambda self, t, m: messages.append((t, m)),
        )

        layout = FileSelectorLayout()
        _assert_layout_geometry(layout, qapp)

        ghost = "D:/definitely/not/exists_dir/ghost.txt"
        navigate_calls: list = []
        monkeypatch.setattr(layout, "_navigate_to", lambda path: navigate_calls.append(path))

        layout.locate_file({"path": ghost, "name": "ghost.txt"})

        assert len(messages) == 1
        assert messages[0][0] == "错误"
        assert navigate_calls == []
        assert not layout._previewing_file_path
        assert os.path.normcase(layout._current_path) == os.path.normcase("All")
        layout.deleteLater()


# =============================================================================
# ui.layout.file_selector_layout — _go_back 返回过渡动画
# =============================================================================
class TestGoBackTransition:
    """_go_back 返回过渡：历史/上级/盘符根分支均一致触发 direction=-1 动画。

    全部用例均用 MagicMock 计数 begin/finish，不跑真实动画（offscreen 下
    ``FileSelectorLayout`` 真实构造，仅过渡与 IO 入口被替身替换）。
    """

    def test_history_branch_triggers_back_animation(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """历史分支：有可回退历史时 _go_back 以 -1 触发过渡并加载上一条。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            tmp_path: pytest 临时目录（真实创建 tmpA/tmpB）。
            monkeypatch: 用例级猴子补丁。
        """
        import os

        tmp_a = tmp_path / "tmpA"
        tmp_b = tmp_path / "tmpB"
        tmp_a.mkdir()
        tmp_b.mkdir()
        str_a = os.path.abspath(str(tmp_a))
        str_b = os.path.abspath(str(tmp_b))

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            # 预置历史栈顶为 tmpB，回退应落到 tmpA。
            layout._nav_history = [str_a, str_b]
            layout._history_index = 1
            layout._current_path = str_b
            begin_mock: MagicMock = MagicMock(return_value=True)
            finish_mock: MagicMock = MagicMock(return_value=True)
            load_mock: MagicMock = MagicMock()
            monkeypatch.setattr(layout._file_list, "begin_path_transition", begin_mock)
            monkeypatch.setattr(layout._file_list, "finish_path_transition", finish_mock)
            monkeypatch.setattr(layout, "_load_directory", load_mock)
            monkeypatch.setattr(layout, "_navigate_to_all", MagicMock())
            monkeypatch.setattr(layout, "_save_last_path", MagicMock())
            monkeypatch.setattr(os.path, "isdir", lambda path: True)

            layout._go_back()

            begin_mock.assert_called_once_with(-1)
            finish_mock.assert_called_once_with(-1)
            load_mock.assert_called_once_with(str_a)
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_parent_fallback_triggers_back_animation(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """上级回退（单条历史/首次访问）：parent 回退分支以 -1 触发过渡。

        覆盖启动恢复、All 重置后等单历史场景：_history_index==0 时
        _go_back 走 parent 回退分支（经 _load_directory_with_transition），
        与历史分支一致触发 -1 动画并加载 dirname 上级。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            tmp_path: pytest 临时目录（真实创建 sub/inner）。
            monkeypatch: 用例级猴子补丁。
        """
        import os

        sub_dir = tmp_path / "sub"
        deep_dir = sub_dir / "inner"
        deep_dir.mkdir(parents=True)
        str_parent = os.path.abspath(str(sub_dir))
        str_deep = os.path.abspath(str(deep_dir))

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            # 单条历史（首次访问/启动恢复场景）：栈顶即 deep，无可回退历史，
            # 回退走 parent 分支，dirname 上级即 parent。
            layout._nav_history = [str_deep]
            layout._history_index = 0
            layout._current_path = str_deep
            begin_mock: MagicMock = MagicMock(return_value=True)
            finish_mock: MagicMock = MagicMock(return_value=True)
            load_mock: MagicMock = MagicMock()
            monkeypatch.setattr(layout._file_list, "begin_path_transition", begin_mock)
            monkeypatch.setattr(layout._file_list, "finish_path_transition", finish_mock)
            monkeypatch.setattr(layout, "_load_directory", load_mock)
            monkeypatch.setattr(layout, "_navigate_to_all", MagicMock())
            monkeypatch.setattr(layout, "_save_last_path", MagicMock())
            monkeypatch.setattr(os.path, "isdir", lambda path: True)

            layout._go_back()

            begin_mock.assert_called_once_with(-1)
            finish_mock.assert_called_once_with(-1)
            load_mock.assert_called_once_with(str_parent)
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_drive_root_delegates_to_all_with_animation(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """盘符根回退：parent == current 时委托 _navigate_to_all 且带 -1 动画。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            monkeypatch: 用例级猴子补丁。
        """
        import os

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            # 无可回退历史、当前为盘符根：dirname 恒返自身以强制走 All 分支。
            layout._nav_history = []
            layout._history_index = -1
            layout._current_path = "D:\\"
            begin_mock: MagicMock = MagicMock(return_value=True)
            finish_mock: MagicMock = MagicMock(return_value=True)
            monkeypatch.setattr(layout._file_list, "begin_path_transition", begin_mock)
            monkeypatch.setattr(layout._file_list, "finish_path_transition", finish_mock)
            monkeypatch.setattr(layout, "_load_all", MagicMock())
            monkeypatch.setattr(layout, "_save_last_path", MagicMock())
            monkeypatch.setattr(layout, "_clear_last_path", MagicMock())
            monkeypatch.setattr(os.path, "isdir", lambda path: True)
            monkeypatch.setattr(os.path, "dirname", lambda path: path)
            navigate_all_calls: list = []
            original_navigate_to_all = layout._navigate_to_all

            def _spy_navigate_to_all() -> None:
                """记录委托并执行真实 All 导航（保留其内部 -1 动画）。"""
                navigate_all_calls.append(True)
                original_navigate_to_all()

            monkeypatch.setattr(layout, "_navigate_to_all", _spy_navigate_to_all)

            layout._go_back()

            assert navigate_all_calls == [True]
            begin_mock.assert_called_once_with(-1)
            finish_mock.assert_called_once_with(-1)
            assert layout._current_path == "All"
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_deep_nesting_sequential_go_back(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """深层嵌套：逐级 _go_back 每次均触发 -1 动画。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            tmp_path: pytest 临时目录（真实创建 a/b/c）。
            monkeypatch: 用例级猴子补丁。
        """
        import os

        dir_a = tmp_path / "a"
        dir_b = dir_a / "b"
        dir_c = dir_b / "c"
        dir_c.mkdir(parents=True)
        str_a = os.path.abspath(str(dir_a))
        str_b = os.path.abspath(str(dir_b))
        str_c = os.path.abspath(str(dir_c))

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            layout._nav_history = [str_a, str_b, str_c]
            layout._history_index = 2
            layout._current_path = str_c
            begin_mock: MagicMock = MagicMock(return_value=True)
            finish_mock: MagicMock = MagicMock(return_value=True)
            load_mock: MagicMock = MagicMock()
            monkeypatch.setattr(layout._file_list, "begin_path_transition", begin_mock)
            monkeypatch.setattr(layout._file_list, "finish_path_transition", finish_mock)
            monkeypatch.setattr(layout, "_load_directory", load_mock)
            monkeypatch.setattr(layout, "_navigate_to_all", MagicMock())
            monkeypatch.setattr(layout, "_save_last_path", MagicMock())
            monkeypatch.setattr(os.path, "isdir", lambda path: True)

            layout._go_back()
            layout._go_back()

            assert begin_mock.call_count == 2
            assert finish_mock.call_count == 2
            assert [c.args[0] for c in begin_mock.call_args_list] == [-1, -1]
            assert [c.args[0] for c in finish_mock.call_args_list] == [-1, -1]
            assert [c.args[0] for c in load_mock.call_args_list] == [str_b, str_a]
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    @pytest.mark.parametrize("scenario", ["history", "parent"])
    def test_direction_always_minus_one(
        self, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        scenario: str,
    ) -> None:
        """direction 一致性：历史/上级两种前置下 begin 首参恒为 -1。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            tmp_path: pytest 临时目录。
            monkeypatch: 用例级猴子补丁。
            scenario: 前置场景（history=普通历史回退，parent=回到上级）。
        """
        import os

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            if scenario == "history":
                # 普通历史回退：tmpB -> tmpA。
                tmp_a = tmp_path / "hA"
                tmp_b = tmp_path / "hB"
                tmp_a.mkdir(exist_ok=True)
                tmp_b.mkdir(exist_ok=True)
                layout._nav_history = [os.path.abspath(str(tmp_a)), os.path.abspath(str(tmp_b))]
                layout._history_index = 1
                layout._current_path = os.path.abspath(str(tmp_b))
            else:
                # 上级回退（单条历史/首次访问）：inner 经 parent 分支回到 sub。
                sub_dir = tmp_path / "psub"
                deep_dir = sub_dir / "pinner"
                deep_dir.mkdir(parents=True, exist_ok=True)
                layout._nav_history = [os.path.abspath(str(deep_dir))]
                layout._history_index = 0
                layout._current_path = os.path.abspath(str(deep_dir))
            begin_mock: MagicMock = MagicMock(return_value=True)
            finish_mock: MagicMock = MagicMock(return_value=True)
            monkeypatch.setattr(layout._file_list, "begin_path_transition", begin_mock)
            monkeypatch.setattr(layout._file_list, "finish_path_transition", finish_mock)
            monkeypatch.setattr(layout, "_load_directory", MagicMock())
            monkeypatch.setattr(layout, "_navigate_to_all", MagicMock())
            monkeypatch.setattr(layout, "_save_last_path", MagicMock())
            monkeypatch.setattr(os.path, "isdir", lambda path: True)

            layout._go_back()

            assert begin_mock.call_count == 1
            assert begin_mock.call_args.args[0] == -1
            assert finish_mock.call_args.args[0] == -1
        finally:
            safe_teardown(layout)
            qapp.processEvents()


# =============================================================================
# ui.layout.settings_layout
# =============================================================================
class TestSettingsLayout:
    """设置页布局：构造契约与尺寸生效（读取真实 settings_v2.json）。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = SettingsLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_appearance_page_uses_floating_styled_scrollbar(
        self, qapp: QApplication,
    ) -> None:
        """外观页包在浮动滚动区中：styled 浮动滚动条接管，原生滚动条隐藏。"""
        from PySide6.QtWidgets import QScrollArea

        from components.styled_scroll_area import StyledScrollBar
        from freeassetfilter.ui.layout.settings_layout import _FloatingScrollArea

        layout = SettingsLayout()
        scrolls = layout._stack.findChildren(QScrollArea)
        floating = [s for s in scrolls if isinstance(s, _FloatingScrollArea)]
        assert len(floating) == 1

        area = floating[0]
        # 原生滚动条隐藏，浮动 styled 滚动条存在
        assert area.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert area.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert isinstance(area._floating_bar, StyledScrollBar)
        # 浮动条锚定挂在外观卡片（#SettingsCard）下，贴其右缘（而非滚动区自身）
        assert area._region is area.parent()
        assert area._floating_bar.parent() is area.parent()
        # 平滑滚动在 showEvent 中初始化（未显示前未施加）
        assert area._scroller_ready is False
        safe_teardown(layout)

    def test_floating_scrollbar_range_and_value_sync(
        self, qapp: QApplication,
    ) -> None:
        """浮动滚动条与内部滚动条范围/值双向同步，随内容显隐。"""
        from freeassetfilter.ui.layout.settings_layout import _FloatingScrollArea

        area = _FloatingScrollArea()
        area.resize(400, 300)

        inner = QWidget()
        inner.setFixedHeight(800)  # 内容超出 → 产生滚动范围
        area.setWidget(inner)
        qapp.processEvents()
        area.show()
        qapp.processEvents()

        vbar = area.verticalScrollBar()
        bar = area._floating_bar
        if vbar.maximum() > 0:
            assert bar.maximum() == vbar.maximum()
            assert bar.isVisible()

            # 内部值变化 → 浮动条跟随
            vbar.setValue(10)
            assert bar.value() == 10
            # 浮动条拖动 → 内部跟随
            bar.setValue(20)
            assert vbar.value() == 20
            # 浮动条贴右侧边缘几何
            assert bar.x() == area.width() - bar.width()
        area.hide()
        safe_teardown(area)


# =============================================================================
# ui.layout.unified_previewer_layout
# =============================================================================
class TestUnifiedPreviewerLayout:
    """统一预览器布局：构造、set_file(None)/clear_preview 分发。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_info_panel_built_in_bottom_frame(self, qapp: QApplication) -> None:
        """文件信息面板已挂载到下方内容区，且随 clear_preview 复位。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        # 与产品代码使用同一 sys.path 别名，避免同一模块被双重导入
        import layout.preview.file_info_panel as fip_module

        assert isinstance(layout._info_panel, fip_module.FileInfoPanel)
        assert layout._content_bottom.layout() is not None

        layout.set_file(self._unsupported_file_info())
        qapp.processEvents()
        assert layout._info_panel._file_info is not None

        layout.clear_preview()
        qapp.processEvents()
        assert layout._info_panel._file_info is None
        layout.deleteLater()

    def test_set_file_none_is_safe(self, qapp: QApplication) -> None:
        """set_file(None) 走安全清空路径，不抛异常。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(None)
        qapp.processEvents()
        assert layout._content_layout is not None
        layout.clear_preview()
        layout.deleteLater()

    @staticmethod
    def _unsupported_file_info() -> dict:
        """无对应预览器的文件信息（不触发真实预览加载，仅驱动底栏状态）。"""
        return {"path": "D:/dummy/unsupported_sample.zzz", "suffix": "zzz", "is_dir": False}

    def test_bottom_buttons_disabled_then_enabled(
        self, qapp: QApplication,
    ) -> None:
        """无预览文件时底栏按钮禁用；set_file 后启用；clear_preview 后再禁用。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)

        assert layout._share_btn.isEnabled() is False
        assert layout._open_default_btn.isEnabled() is False
        assert layout._locate_btn.isEnabled() is False
        assert layout._close_btn.isEnabled() is False

        layout.set_file(self._unsupported_file_info())
        qapp.processEvents()
        assert layout._share_btn.isEnabled() is True
        assert layout._open_default_btn.isEnabled() is True
        assert layout._locate_btn.isEnabled() is True
        assert layout._close_btn.isEnabled() is True

        layout.clear_preview()
        qapp.processEvents()
        assert layout._share_btn.isEnabled() is False
        assert layout._open_default_btn.isEnabled() is False
        assert layout._locate_btn.isEnabled() is False
        assert layout._close_btn.isEnabled() is False
        layout.deleteLater()

    def test_locate_button_emits_requested(self, qapp: QApplication) -> None:
        """点击"定位到所在目录"发射 locate_requested(当前文件信息)。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(self._unsupported_file_info())

        received: list = []
        layout.locate_requested.connect(lambda info: received.append(info))
        layout._locate_btn.click()

        assert len(received) == 1
        assert received[0]["path"] == "D:/dummy/unsupported_sample.zzz"
        layout.deleteLater()

    def test_close_button_emits_clear_requested(self, qapp: QApplication) -> None:
        """点击 close 按钮发射 clear_requested（清除预览请求）。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(self._unsupported_file_info())

        received: list = []
        layout.clear_requested.connect(lambda: received.append(True))
        layout._close_btn.click()

        assert received == [True]
        layout.deleteLater()

    @pytest.mark.parametrize(
        "file_info, expected",
        [
            ({"path": "x.mp3", "suffix": "mp3"}, True),   # 无点号音频
            ({"path": "x.wav", "suffix": ".wav"}, True),  # 带点号音频
            ({"path": "x.MP3", "suffix": "MP3"}, True),   # 大写后缀
            ({"suffix": ""}, False),                       # 空后缀
            ({"path": "x.txt", "suffix": "txt"}, False),   # 非音频（无点）
            ({"path": "x.log", "suffix": ".txt"}, False),  # 非音频（带点）
        ],
    )
    def test_is_audio_file_normalizes_suffix(
        self, qapp: QApplication, file_info: dict, expected: bool
    ) -> None:
        """_is_audio_file 对 suffix 归一化（无点/带点/大小写）后再判音频。"""
        layout = UnifiedPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert layout._is_audio_file(file_info) is expected
        layout.deleteLater()

    # ── 分割区高度规则 ──────────────────────────────────────────────────

    def _show_split_layout(self, qapp: QApplication) -> UnifiedPreviewerLayout:
        layout = UnifiedPreviewerLayout()
        layout.show()
        layout.resize(720, 920)
        _pump_events(qapp)
        return layout

    @staticmethod
    def _split_heights(layout: UnifiedPreviewerLayout) -> tuple[int, int]:
        return layout._content_top.height(), layout._content_bottom.height()

    def test_default_start_split_is_half(
        self, qapp: QApplication,
    ) -> None:
        """默认起始状态：统一预览器与文件信息预览器各占可用高度的一半。"""
        layout = self._show_split_layout(qapp)
        available = layout._splitter.height() - layout._splitter.handleWidth()
        assert available > 0
        top, bottom = self._split_heights(layout)
        assert abs(top - bottom) <= 2
        assert abs(top - available // 2) <= 2
        # 信息区最高高度即为其默认半高
        assert layout._content_bottom.maximumHeight() == available // 2
        layout._info_panel.stop()
        safe_teardown(layout)

    def test_info_pane_capped_at_half(
        self, qapp: QApplication,
    ) -> None:
        """信息预览器最高高度不超过可用高度的一半（强制拉高也被钳制）。"""
        layout = self._show_split_layout(qapp)
        layout.set_file(self._unsupported_file_info())
        _pump_events(qapp)
        available = layout._splitter.height() - layout._splitter.handleWidth()
        half = available // 2

        # 程序化把底栏拉到远超半高 → 遵循最大高度，顶栏占余下部分
        layout._splitter.setSizes([120, available * 4])
        _pump_events(qapp)
        top, bottom = self._split_heights(layout)
        assert bottom <= half
        assert top >= half
        assert abs(top + bottom - available) <= 2
        layout._info_panel.stop()
        safe_teardown(layout)

    def test_clear_preview_restores_default_split(
        self, qapp: QApplication,
    ) -> None:
        """预览期间手动调高（顶部变大）后取消预览 → 恢复默认各半高度。"""
        layout = self._show_split_layout(qapp)
        layout.set_file(self._unsupported_file_info())
        _pump_events(qapp)
        available = layout._splitter.height() - layout._splitter.handleWidth()
        half = available // 2

        # 用户手动把信息区收窄、预览区放大
        layout._splitter.setSizes([available - half // 3, half // 3])
        _pump_events(qapp)
        top, bottom = self._split_heights(layout)
        assert bottom < half

        layout.clear_preview()
        _pump_events(qapp)
        top, bottom = self._split_heights(layout)
        assert abs(top - bottom) <= 2
        assert abs(top - half) <= 2
        assert layout._content_bottom.maximumHeight() == half
        layout._info_panel.stop()
        safe_teardown(layout)

    # ── 底栏按钮：顺序与两文字按钮等宽 ────────────────────────────────

    def test_bottom_bar_button_order(
        self, qapp: QApplication,
    ) -> None:
        """底栏顺序：share → 打开方式 → 定位目录 → close。"""
        layout = self._show_split_layout(qapp)
        share_x = layout._share_btn.x()
        open_x = layout._open_default_btn.x()
        locate_x = layout._locate_btn.x()
        close_x = layout._close_btn.x()
        assert share_x < open_x < locate_x < close_x
        assert not hasattr(layout, "_explorer_btn")
        layout._info_panel.stop()
        safe_teardown(layout)

    def test_action_buttons_equal_width_and_track_width(
        self, qapp: QApplication,
    ) -> None:
        """两个文字按钮等宽，随功能区宽度同步同增同减。"""
        layout = self._show_split_layout(qapp)

        def _widths() -> list[int]:
            return [layout._open_default_btn.width(), layout._locate_btn.width()]

        def _assert_equal(ws: list[int]) -> None:
            assert max(ws) - min(ws) <= 1  # 等分取整误差不超过 1px

        wide = _widths()
        _assert_equal(wide)
        assert wide[0] > 0

        layout.resize(980, 920)  # 变宽 → 同步变大
        _pump_events(qapp)
        wider = _widths()
        _assert_equal(wider)
        assert wider[0] > wide[0]

        layout.resize(600, 920)  # 变窄 → 同步变小
        _pump_events(qapp)
        narrow = _widths()
        _assert_equal(narrow)
        assert narrow[0] < wider[0]
        layout._info_panel.stop()
        safe_teardown(layout)


# =============================================================================
# ui.layout.preview.font_previewer_layout
# =============================================================================
class TestFontPreviewerLayout:
    """字体预览布局：构造契约与 set_file 缺失路径降级。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_file_missing_safe(self, qapp: QApplication) -> None:
        """set_file(缺失路径) 不抛异常，停留 overlay 视图。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(_MISSING_FILE)
        qapp.processEvents()
        assert layout._content_stack.currentIndex() == 1
        layout.deleteLater()


class TestFontPreviewTextDrawer:
    """预览文本编辑抽屉：标题结构 / 展开收起 / 实时同步 / 重置 / 清理收起。"""

    def _shown_layout(self, qapp: QApplication) -> FontPreviewerLayout:
        layout = FontPreviewerLayout()
        layout.show()
        layout.resize(1200, 700)
        _pump_events(qapp)
        return layout

    @staticmethod
    def _settle_drawers(
        qapp: QApplication,
        layout: FontPreviewerLayout,
        ms: float = 1500,
    ) -> None:
        """有界等待：直到左右抽屉的展开/收起动画全部结束。"""
        deadline = time.time() + ms / 1000
        while time.time() < deadline:
            animating = [
                getattr(layout, attr)._animating
                for attr in ("_text_drawer", "_ai_drawer")
                if getattr(layout, attr) is not None
            ]
            if not any(animating):
                return
            qapp.processEvents()
            time.sleep(0.01)

    def test_drawer_default_hidden_with_title(self, qapp: QApplication) -> None:
        """初始隐藏；抽屉含标题「编辑预览文本」，编辑框不再自带重复 label。"""
        from PySide6.QtWidgets import QLabel

        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert not layout._text_drawer._is_open
        assert layout._edit_preview_btn.toolTip() == "编辑预览文本"
        titles = [
            c
            for c in layout._text_drawer._panel.findChildren(QLabel)
            if c.text() == "编辑预览文本"
        ]
        assert titles
        assert layout._preview_text_edit.label == ""
        layout.deleteLater()

    def test_toggle_drawer(self, qapp: QApplication) -> None:
        """编辑按钮第一次点击展开、第二次点击收起抽屉。"""
        layout = self._shown_layout(qapp)
        layout._on_edit_preview_text()
        self._settle_drawers(qapp, layout)
        assert layout._text_drawer._is_open
        assert layout._text_drawer.isVisible()
        layout._on_edit_preview_text()
        assert not layout._text_drawer._is_open
        layout.deleteLater()

    def test_edit_text_syncs_to_preview(self, qapp: QApplication) -> None:
        """预览视图激活时：编辑框输入实时同步 _preview_text 与预览区。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout._content_stack.setCurrentIndex(0)
        layout._preview_text_edit.text = "自定义预览内容 ABC"
        qapp.processEvents()
        assert layout._preview_text == "自定义预览内容 ABC"
        assert layout._preview_view._text_edit.toPlainText() == "自定义预览内容 ABC"
        layout.deleteLater()

    def test_reset_preview_text(self, qapp: QApplication) -> None:
        """重置按钮恢复默认预览文本并同步到预览区。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout._preview_text_edit.text = "临时内容"
        layout._on_reset_preview_text()
        assert layout._preview_text == DEFAULT_PREVIEW_TEXT
        assert layout._preview_text_edit.text == DEFAULT_PREVIEW_TEXT
        layout.deleteLater()

    def test_cleanup_closes_drawers(self, qapp: QApplication) -> None:
        """cleanup() 收起已展开的编辑与 AI 抽屉，不抛异常。"""
        layout = self._shown_layout(qapp)
        layout._on_edit_preview_text()
        layout._toggle_ai_drawer()
        self._settle_drawers(qapp, layout)
        assert layout._text_drawer._is_open
        assert layout._ai_drawer._is_open
        layout.cleanup()
        assert not layout._text_drawer._is_open
        assert not layout._ai_drawer._is_open
        layout.deleteLater()


class TestFontWeightLabel:
    """字重标签：数值→标准名映射与静态/可变/未加载三种状态显示。"""

    @pytest.mark.parametrize(
        "weight,expected",
        [
            (100, "Thin"),
            (200, "ExtraLight"),
            (300, "Light"),
            (400, "Regular"),
            (500, "Medium"),
            (600, "SemiBold"),
            (700, "Bold"),
            (800, "ExtraBold"),
            (900, "Black"),
            (1000, "Black"),
            (95, "Thin"),      # 最近档偏差 ≤100
            (105, "Thin"),
            (550, "Medium"),
            (0, "Thin"),       # 越界钳制到下限 100
            (2500, "Black"),   # 越界钳制到上限 1000
        ],
    )
    def test_weight_name_mapping(
        self, weight: int, expected: str,
    ) -> None:
        assert FontPreviewerLayout.weight_name(weight) == expected

    def test_placeholder_when_not_loaded(self, qapp: QApplication) -> None:
        """未加载字体：标签 Weight + 按钮 wght（占位禁用）。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert layout._weight_label.text() == "Weight"
        assert layout._weight_value_btn.text() == "wght"
        assert not layout._weight_value_btn.isEnabled()
        layout.deleteLater()

    def test_static_font_shows_weight_name(self, qapp: QApplication) -> None:
        """静态字体加载后：标签显示真实字重名，按钮显示数值。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.current_font_family = "SomeStatic"
        layout._is_variable_font = False
        layout._current_weight = 700
        layout._sync_weight_controls()
        assert layout._weight_label.text() == "Bold"
        assert layout._weight_value_btn.text() == "700"
        assert layout._weight_value_btn.isEnabled()
        layout.current_font_family = ""
        layout._is_variable_font = False
        layout._sync_weight_controls()
        assert layout._weight_label.text() == "Weight"
        layout.deleteLater()

    def test_variable_font_keeps_weight_label(self, qapp: QApplication) -> None:
        """可变字体：标签保持 Weight，按钮显示数值。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.current_font_family = "SomeVariable"
        layout._is_variable_font = True
        layout._current_weight = 400
        layout._sync_weight_controls()
        assert layout._weight_label.text() == "Weight"
        assert layout._weight_value_btn.text() == "400"
        assert layout._weight_value_btn.isEnabled()
        layout.deleteLater()


class TestFontWeightControlsLayout:
    """字重控件布局：统一间距 / tooltip 拆分 / 折叠菜单映射 / 弹窗居中。"""

    def _shown_layout(self, qapp: QApplication) -> FontPreviewerLayout:
        layout = FontPreviewerLayout()
        layout.show()
        layout.resize(1200, 700)
        _pump_events(qapp)
        return layout

    def test_uniform_gap_after_weight_button(
        self, qapp: QApplication,
    ) -> None:
        """字重数值按钮与 AI/缩放按钮间距为统一 6px。"""
        from freeassetfilter.ui.layout.preview.preview_toolbar import (
            PreviewToolbarFrame,
        )

        layout = self._shown_layout(qapp)
        gap = PreviewToolbarFrame._GAP
        weight_right = layout._weight_value_btn.x() + layout._weight_value_btn.width()
        assert layout._ai_btn.x() - weight_right == gap
        ai_right = layout._ai_btn.x() + layout._ai_btn.width()
        assert layout._zoom_btn.x() - ai_right == gap
        layout.deleteLater()

    def test_tooltips_split_and_group_clean(
        self, qapp: QApplication,
    ) -> None:
        """标签 tooltip Weight、按钮 wght；分组自身不再带 tooltip。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert layout._weight_label.toolTip() == "Weight"
        assert layout._weight_value_btn.toolTip() == "wght"
        assert layout._weight_group.toolTip() == ""
        layout.deleteLater()

    def test_overflow_menu_label_mapping(
        self, qapp: QApplication,
    ) -> None:
        """折叠「更多」菜单：字重组显示注册名「字重」，其余控件仍取 tooltip。"""
        layout = FontPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        top_bar = layout._top_bar
        assert top_bar._menu_label(layout._weight_group) == "字重"
        assert top_bar._menu_label(layout._ai_btn) == "AI 功能"
        layout.deleteLater()

    def test_weight_popup_centered_with_button(
        self, qapp: QApplication,
    ) -> None:
        """字重弹窗水平中心与数值按钮中心对齐。"""
        import freeassetfilter.ui.layout.preview.font_previewer_layout as fpl_module

        layout = self._shown_layout(qapp)
        anchor = layout._weight_anchor_global()
        button_center = (
            layout._weight_value_btn.mapToGlobal(
                layout._weight_value_btn.rect().center()
            ).x()
        )
        assert abs(anchor.x() - button_center) <= 1  # 锚点即按钮下缘中心
        popup = fpl_module._WeightPopup(parent=layout)
        rect = popup._target_rect(anchor)
        assert abs(rect.center().x() - anchor.x()) <= 1
        popup.close()
        popup.deleteLater()
        layout.deleteLater()


# =============================================================================
# ui.layout.preview.preview_toolbar（弹窗/溢出菜单锚点）
# =============================================================================
class TestPreviewToolbarPopupAnchoring:
    """顶栏弹窗锚点：功能按钮下缘中心对齐 + 折叠回退 + 溢出菜单居中。"""

    def _shown_toolbar(self, qapp: QApplication) -> Any:
        from freeassetfilter.ui.layout.preview.preview_toolbar import (
            PreviewToolbarFrame,
        )

        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        toolbar = PreviewToolbarFrame()
        toolbar.setFixedHeight(48)
        lay.addWidget(toolbar)
        host.resize(640, 120)
        host.show()
        _pump_events(qapp)
        return host, toolbar

    def test_anchor_is_widget_bottom_center(self, qapp: QApplication) -> None:
        """可见功能按钮的弹窗锚点 = 按钮下缘水平中心。"""
        from PySide6.QtWidgets import QPushButton

        host, toolbar = self._shown_toolbar(qapp)
        try:
            button = QPushButton("X", toolbar)
            button.setFixedSize(32, 32)
            button.show()
            _pump_events(qapp)
            anchor = toolbar.popup_anchor_global(button)
            center = button.mapToGlobal(
                QPoint(button.width() // 2, button.height())
            )
            assert abs(anchor.x() - center.x()) <= 1
            assert abs(anchor.y() - center.y()) <= 1
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)

    def test_anchor_falls_back_to_more_button_when_widget_hidden(
        self, qapp: QApplication,
    ) -> None:
        """功能按钮被折叠隐藏时，锚点回退到「更多」按钮下缘中心。"""
        from PySide6.QtWidgets import QPushButton

        host, toolbar = self._shown_toolbar(qapp)
        try:
            hidden = QPushButton("Z", toolbar)
            hidden.hide()
            toolbar._more_btn.show()
            _pump_events(qapp)
            assert toolbar._more_btn.isVisible()

            anchor = toolbar.popup_anchor_global(hidden)
            center = toolbar._more_btn.mapToGlobal(
                QPoint(toolbar._more_btn.width() // 2, toolbar._more_btn.height())
            )
            assert abs(anchor.x() - center.x()) <= 1
            assert abs(anchor.y() - center.y()) <= 1
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)

    def test_anchor_falls_back_to_toolbar_when_all_hidden(
        self, qapp: QApplication,
    ) -> None:
        """功能按钮与「更多」按钮都不可见时，锚点退回顶栏自身下缘中心。"""
        from PySide6.QtWidgets import QPushButton

        host, toolbar = self._shown_toolbar(qapp)
        try:
            hidden = QPushButton("Z", toolbar)
            hidden.hide()
            toolbar._more_btn.hide()
            _pump_events(qapp)

            anchor = toolbar.popup_anchor_global(hidden)
            self_center = toolbar.mapToGlobal(
                QPoint(toolbar.width() // 2, toolbar.height())
            )
            assert abs(anchor.x() - self_center.x()) <= 1
            assert abs(anchor.y() - self_center.y()) <= 1
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)

    def test_overflow_menu_pos_centered_below_more_button(
        self, qapp: QApplication,
    ) -> None:
        """溢出菜单以「⋯」按钮下缘中心水平展开（居中对齐功能按钮）。"""
        host, toolbar = self._shown_toolbar(qapp)
        try:
            toolbar._more_btn.show()
            _pump_events(qapp)
            menu_w = 220
            pos = toolbar._overflow_menu_pos(menu_w)
            center = toolbar._more_btn.mapToGlobal(
                QPoint(toolbar._more_btn.width() // 2, toolbar._more_btn.height())
            )
            assert abs(pos.x() - (center.x() - menu_w // 2)) <= 1
            assert pos.y() == center.y() + 4  # 按钮下缘 4px 间距
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)


# =============================================================================
# ui.layout.preview.fullscreen_host
# =============================================================================
class TestPreviewFullscreenHost:
    """全屏宿主席：attach/detach 进出、无父窗口进出全屏不抛。"""

    def test_attach_detach_roundtrip(self, qapp: QApplication) -> None:
        """attach 移入宿主，exit_fullscreen 还原到原父布局。"""
        container = QWidget()
        layout = QVBoxLayout(container)
        child = QWidget(container)
        layout.addWidget(child)

        host = PreviewFullscreenHost()
        assert host.attach(child) is True
        assert host.content is child
        assert layout.indexOf(child) == -1
        host.exit_fullscreen()
        assert host.content is None
        assert layout.indexOf(child) == 0
        host.deleteLater()
        container.deleteLater()

    def test_fullscreen_without_parent_does_not_raise(
        self, qapp: QApplication
    ) -> None:
        """无父窗口时 show_fullscreen / exit_fullscreen 不抛（QA 要求）。"""
        host = PreviewFullscreenHost()
        host.show_fullscreen()
        qapp.processEvents()
        host.exit_fullscreen()
        qapp.processEvents()
        host.deleteLater()

    def test_escape_emits_signal(self, qapp: QApplication) -> None:
        """Esc 按键发射 escapePressed 信号（先 connect 再触发）。"""
        host = PreviewFullscreenHost()
        received: list[bool] = []
        host.escapePressed.connect(lambda: received.append(True))
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        host.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        assert received == [True]
        host.deleteLater()


# =============================================================================
# ui.layout.preview.image_previewer_layout
# =============================================================================
class TestImagePreviewerLayout:
    """图像预览布局：构造契约与 set_file 缺失路径返回 False。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = ImagePreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_file_missing_returns_false(self, qapp: QApplication) -> None:
        """set_file(缺失路径) 返回 False，不抛异常。"""
        layout = ImagePreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert layout.set_file(_MISSING_FILE) is False
        layout.deleteLater()

    # ── 打开即适配（真实 viewport 尺寸）与透明背景回归 ─────────────────────

    @staticmethod
    def _make_jpg(tmp_path: Any, name: str, width: int, height: int) -> str:
        """生成指定尺寸的纯色 JPG 到 tmp_path，返回路径。"""
        from PySide6.QtGui import QImage

        img = QImage(width, height, QImage.Format.Format_RGB32)
        img.fill(QColor(120, 160, 200))
        path = str(tmp_path / name)
        assert img.save(path, "JPG", 90)
        return path

    @staticmethod
    def _expected_fit_scale(pv: Any) -> float:
        """按 QGraphicsView 当前真实 viewport 计算期望 fit 比例。

        fitInView 内置约 2px/边的防锯齿留白，此处用无留白上界做近似，
        断言时允许 1% 相对误差即可排除“按默认 640×480 占位尺寸适配”
        的旧缺陷（该场景比例相差远大于 1%）。
        """
        vp = pv._image_view.viewport()
        item = pv._gif_proxy_item if pv._is_gif_mode else pv._pixmap_item
        if pv._is_gif_mode:
            rect = item.boundingRect()
            iw, ih = rect.width(), rect.height()
        else:
            pix = item.pixmap()
            iw, ih = pix.width(), pix.height()
        if not iw or not ih:
            return 0.0
        return min(vp.width() / iw, vp.height() / ih)

    def _shown_previewer(
        self, qapp: QApplication, host_w: int = 1200, host_h: int = 900,
        backdrop: str | None = None,
    ) -> tuple[Any, QWidget]:
        """按真实运行时时序构造：创建 → 加入宿主布局 → set_file 前宿主已可见。"""
        host = QWidget()
        host.resize(host_w, host_h)
        root_lay = QVBoxLayout(host)
        root_lay.setContentsMargins(0, 0, 0, 0)
        outer = QWidget(host)
        if backdrop is not None:
            # NOTE (A1 QSS singleton): backdrop must NOT use a direct
            # setStyleSheet — a widget's own sheet outranks the app-level
            # sheet by Qt level precedence and would paint over the
            # previewer's subtree transparency. Palette fill is visually
            # identical and keeps the QSS cascade untouched.
            palette = outer.palette()
            palette.setColor(outer.backgroundRole(), QColor(backdrop))
            outer.setPalette(palette)
            outer.setAutoFillBackground(True)
        root_lay.addWidget(outer)
        lay = QVBoxLayout(outer)
        lay.setContentsMargins(0, 0, 0, 0)
        pv = ImagePreviewerLayout(parent=outer)
        lay.addWidget(pv)
        host.show()
        qapp.processEvents()
        return pv, host

    def test_open_fits_to_real_viewport_not_placeholder(
        self, qapp: QApplication, tmp_path: Any,
    ) -> None:
        """大图打开后按真实预览区尺寸适配，而非未布局前的默认占位尺寸。

        旧实现：_fit_to_view 在 QGraphicsView 仍处于 Qt 默认几何
        （未加入布局 / 布局未激活）时执行，此后真实尺寸生效也无人再校正，
        观感即“打开不自动缩放”。本用例构造与统一预览器一致的时序
        （先 set_file 后布局激活），断言最终缩放贴近真实 viewport 的 fit 值。
        """
        img = self._make_jpg(tmp_path, "wide.jpg", 3000, 2000)
        pv, host = self._shown_previewer(qapp)
        pv.set_file(img)
        _pump_events(qapp, ms=600)
        try:
            vp = pv._image_view.viewport()
            assert vp.width() > 800 and vp.height() > 500, "宿主布局应已生效"
            expected = self._expected_fit_scale(pv)
            assert expected > 0.1
            actual = pv._image_view.transform().m11()
            assert pv._zoom_pct == 100
            assert abs(actual - expected) / expected <= 0.01, (
                f"打开即适配应使用真实 viewport 尺寸: actual={actual:.4f} "
                f"expected={expected:.4f} vp={vp.width()}x{vp.height()}"
            )
        finally:
            pv.cleanup()
            host.close()
            host.deleteLater()
        _pump_events(qapp, ms=100)

    def test_switching_image_refits_at_unchanged_viewport(
        self, qapp: QApplication, tmp_path: Any,
    ) -> None:
        """viewport 未变化时切换不同尺寸图片也必须重新适配（去重不误伤）。"""
        img_a = self._make_jpg(tmp_path, "a_wide.jpg", 3000, 2000)
        img_b = self._make_jpg(tmp_path, "b_square.jpg", 900, 900)
        pv, host = self._shown_previewer(qapp)
        try:
            pv.set_file(img_a)
            _pump_events(qapp, ms=500)
            scale_a = pv._image_view.transform().m11()
            vp_a = (pv._image_view.viewport().width(), pv._image_view.viewport().height())

            pv.set_file(img_b)
            _pump_events(qapp, ms=500)
            assert pv._zoom_pct == 100
            vp_b = (pv._image_view.viewport().width(), pv._image_view.viewport().height())
            assert vp_a == vp_b, "本例应在 viewport 不变的条件下切换"
            expected_b = self._expected_fit_scale(pv)
            actual_b = pv._image_view.transform().m11()
            assert abs(actual_b - expected_b) / expected_b <= 0.01, (
                f"切换文件后需重新 fit: actual={actual_b:.4f} expected={expected_b:.4f}"
            )
            # 两张图片比例差异明显时，新比例不得残留旧图比例
            expected_a = min(vp_a[0] / 3000.0, vp_a[1] / 2000.0)
            assert abs(scale_a - expected_a) / expected_a <= 0.01
            assert abs(actual_b - scale_a) / scale_a > 0.3, "正方形图不应沿用横图比例"
        finally:
            pv.cleanup()
            host.close()
            host.deleteLater()
        _pump_events(qapp, ms=100)

    def test_preview_area_background_is_transparent(
        self, qapp: QApplication, tmp_path: Any,
    ) -> None:
        """预览区不再涂 tm.surface 深色底，透出下层面板背景（同文本预览器）。

        静态断言：view 样式不含不透明 surface 填色、场景无背景画刷、
        viewport 关闭 palette 自绘；
        行为断言：方形图在宽视口内留出左右 letterbox，其区域像素应透明
        （下层面板为纯红，若有深色底则采样为不透明非透明色）。
        """
        img = self._make_jpg(tmp_path, "square.jpg", 2000, 2000)
        pv, host = self._shown_previewer(qapp, backdrop="#ff0000")
        pv.set_file(img)
        _pump_events(qapp, ms=600)
        try:
            view_ss = pv._image_view.styleSheet().lower()
            assert "surface" not in view_ss and "background-color" not in view_ss
            assert pv._image_scene.backgroundBrush().style() == Qt.NoBrush
            assert pv._image_view.viewport().autoFillBackground() is False
            vp = pv._image_view.viewport()
            assert vp.width() > 800
            image_pix = pv._pixmap_item.pixmap()
            assert image_pix.width() == 2000
            shot = vp.grab().toImage()
            # 依据图像实际渲染矩形选取“必定落在留白区”的采样点：
            # 选左右/上下四条留白中最宽的一条在其中间采样；采样坐标按比例
            # 换算到 grab 位图，兼容高 DPI 屏幕（位图为物理像素）。
            tl = pv._image_view.mapFromScene(
                pv._pixmap_item.sceneBoundingRect().topLeft()
            )
            br = pv._image_view.mapFromScene(
                pv._pixmap_item.sceneBoundingRect().bottomRight()
            )
            gaps = {
                "left": tl.x(),
                "right": vp.width() - 1 - br.x(),
                "top": tl.y(),
                "bottom": vp.height() - 1 - br.y(),
            }
            side, gap = max(gaps.items(), key=lambda kv: kv[1])
            mid_x = vp.width() // 2
            mid_y = vp.height() // 2
            if side == "left":
                log_x, log_y = gap // 2, mid_y
            elif side == "right":
                log_x, log_y = vp.width() - 1 - gap // 2, mid_y
            elif side == "top":
                log_x, log_y = mid_x, gap // 2
            else:
                log_x, log_y = mid_x, vp.height() - 1 - gap // 2
            px = int(round(log_x * shot.width() / vp.width()))
            py = int(round(log_y * shot.height() / vp.height()))
            sample = shot.pixelColor(px, py)
            assert gap >= 4, f"图片应被自适应缩放并留出留白: {gaps}"
            assert sample.alpha() == 0, (
                f"预览区留白应透明（side={side}）: {sample} gaps={gaps}"
            )
        finally:
            pv.cleanup()
            host.close()
            host.deleteLater()
        _pump_events(qapp, ms=100)


# =============================================================================
# ui.layout.preview.office_previewer_layout
# =============================================================================
class _FakeOfficeWorker(QObject):
    """``OfficeConverterWorker`` 的可控替身：不启动真实 soffice 线程。"""

    converted = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        file_info: dict,
        timeout: float | None = None,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.file_info: dict = file_info
        self._running: bool = False

    def start(self, *args: Any, **kwargs: Any) -> None:
        """镜像 start：fake 只标记运行中。"""
        self._running = True

    def is_running(self) -> bool:
        """线程是否仍在运行。"""
        return self._running

    def isRunning(self) -> bool:  # noqa: N802
        """Qt 兼容接口。"""
        return self._running

    def request_cancel(self) -> None:
        """镜像 request_cancel。"""
        self._running = False

    def wait(self, timeout_ms: int = 3000) -> bool:
        """镜像 wait。"""
        return not self._running

    def cleanup(self, wait_ms: int = 3000) -> None:
        """镜像 cleanup。"""
        self._running = False


class TestOfficePreviewerLayout:
    """Office 预览布局：构造契约与 set_file 分发（注入 fake worker）。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造（无 worker） + resize 后 geometry 非空。"""
        layout = OfficePreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.cleanup()
        layout.deleteLater()

    def test_set_file_str_routes_to_worker(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """宿主 str 路径分发 → 归一化为 dict、启动 worker（fake）。"""
        monkeypatch.setattr(_opl, "OfficeConverterWorker", _FakeOfficeWorker)
        layout = OfficePreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file("C:/fake/path/sample.docx")
        assert layout._current_suffix == "docx"
        assert isinstance(layout._current_worker, _FakeOfficeWorker)
        layout.cleanup()
        layout.deleteLater()


# =============================================================================
# ui.layout.preview.pdf_previewer_layout
# =============================================================================
class TestPdfPreviewerLayout:
    """PDF 预览布局：构造契约、set_file 缺失路径与滚动/居中几何。"""

    @staticmethod
    def _write_pdf(tmp_path: Path, pages: int = 2) -> str:
        """用 PyMuPDF 在内存构造多页 PDF（612×792pt）。"""
        fitz = pytest.importorskip("fitz")
        doc = fitz.open()
        for i in range(pages):
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, 72), f"Page {i + 1}")
        target = tmp_path / "previewer_scroll.pdf"
        doc.save(str(target))
        doc.close()
        return str(target)

    @staticmethod
    def _shown_loaded_layout(
        qapp: QApplication, tmp_path: Path,
    ) -> tuple[QWidget, PdfPreviewerLayout]:
        """展示宿主并加载双页 PDF（完成 fit 与滚动条范围定时任务）。"""
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        layout = PdfPreviewerLayout()
        host_layout.addWidget(layout)
        host.resize(520, 420)
        host.show()
        _pump_events(qapp)
        assert layout.set_file(TestPdfPreviewerLayout._write_pdf(tmp_path)) is True
        _pump_events(qapp, 400)
        return host, layout

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = PdfPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_file_missing_returns_false(self, qapp: QApplication) -> None:
        """set_file(缺失路径) 返回 False，不抛异常。"""
        layout = PdfPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        assert layout.set_file(_MISSING_FILE) is False
        layout.deleteLater()

    def test_content_centered_including_reserved_scrollbar_column(
        self, qapp: QApplication, tmp_path: Path,
    ) -> None:
        """页面白色卡片相对预览器左右边缘等距（右侧预留滚动条列计入画布）。"""
        host, layout = self._shown_loaded_layout(qapp, tmp_path)
        try:
            renderer = layout._renderer
            view = renderer._view
            assert view is not None
            assert view.right_reserved_px == 12
            # 画布中心 = (渲染器宽 + 预留列宽) / 2
            assert abs(view.frame_center_x() - (renderer.width() + 12) / 2.0) <= 0.5

            zoom = view.zoom_level
            pwz = renderer._page_widths[0] * zoom
            box_left = (0.0 - view.offset_x) * zoom + view.frame_center_x()
            white_left = box_left + 6.0
            white_right = box_left + pwz - 6.0
            ml = white_left
            mr = (renderer.width() + 12) - white_right
            assert abs(ml - mr) <= 1.0
            assert ml > 0 and mr > 0
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)

    def test_vertical_scroll_range_reserves_bottom_gap(
        self, qapp: QApplication, tmp_path: Path,
    ) -> None:
        """有纵向溢出时滚动条最大值 = 内容高 - 视口高 + 底部预留空隙。"""
        host, layout = self._shown_loaded_layout(qapp, tmp_path)
        try:
            renderer = layout._renderer
            view = renderer._view
            total_h = view._accum_page_heights[-1] * view.zoom_level
            view_h = max(view.view_height, 1)
            overflow = int(total_h - view_h)
            if overflow > 0:
                assert layout._vbar.maximum() == (
                    overflow + layout._CONTENT_BOTTOM_GAP
                )
            else:
                assert layout._vbar.maximum() == 0
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)

    def test_horizontal_scrollbar_shows_only_on_overflow(
        self, qapp: QApplication, tmp_path: Path,
    ) -> None:
        """fit 态无横向溢出 → 底行滚动条隐藏；放大后出现，回到 fit 再隐藏。"""
        host, layout = self._shown_loaded_layout(qapp, tmp_path)
        try:
            renderer = layout._renderer
            view = renderer._view
            assert not layout._hbar.isVisible()
            assert layout._hbar.maximum() == 0
            assert not layout._corner.isVisible()

            base = view.get_zoom_for_scale(100)
            renderer.set_zoom(base * 1.6)
            _pump_events(qapp, 60)
            assert layout._hbar.isVisible()
            assert layout._hbar.maximum() > 0
            assert layout._corner.isVisible()

            renderer.fit_to_page()
            _pump_events(qapp, 60)
            assert not layout._hbar.isVisible()
            assert layout._hbar.maximum() == 0
            assert not layout._corner.isVisible()
        finally:
            host.close()
            host.deleteLater()
            _pump_events(qapp)


# =============================================================================
# ui.layout.preview.text_previewer_layout
# =============================================================================
class TestTextPreviewerLayout:
    """文本预览布局：构造契约、set_text_content 与缺失路径降级。"""

    def test_construct_and_geometry(self, qapp: QApplication) -> None:
        """默认构造 + resize 后 geometry 非空。"""
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_text_content(self, qapp: QApplication) -> None:
        """直接注入文本内容不抛异常。"""
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_text_content("hello from test")
        qapp.processEvents()
        layout.deleteLater()

    def test_set_file_missing_safe(self, qapp: QApplication) -> None:
        """set_file(缺失路径) 不抛异常。"""
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        layout.set_file(_MISSING_FILE)
        qapp.processEvents()
        layout.deleteLater()

    def test_slider_debounce_single_render(
        self, qapp: QApplication, monkeypatch: Any
    ) -> None:
        """连续拖动字号滑条 10 次 → 防抖只触发一次渲染且字号为最终值。"""
        monkeypatch.setattr(_tpl, "_MarkdownRenderer", _CountingMarkdownRenderer)
        _CountingMarkdownRenderer.call_count = 0
        _CountingMarkdownRenderer.last_font_size = None
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        try:
            layout.set_text_content("# hello\nworld", "note.md")
            # 等初始异步渲染完成（事件泵直到内容回写）
            assert _pump_until(
                qapp,
                lambda: _CountingMarkdownRenderer.call_count >= 1
                and layout._markdown_view._text_browser.toPlainText().strip()
                == "rendered-14:13",
            )
            _CountingMarkdownRenderer.call_count = 0

            # 连续拖动 10 次（期间不泵事件，防抖窗口内不触发渲染）
            for size in range(20, 30):
                layout._apply_font_size_from_zoom(size)
            assert _CountingMarkdownRenderer.call_count == 0
            assert layout._font_size == 29  # 防抖期间保留最新字号

            # 泵超过 120ms 防抖窗口 → 只触发一次渲染，内容为最终字号
            _pump_events(qapp, 500)
            assert _CountingMarkdownRenderer.call_count == 1
            assert _CountingMarkdownRenderer.last_font_size == 29
            assert (
                layout._markdown_view._text_browser.toPlainText().strip()
                == "rendered-29:13"
            )
        finally:
            safe_teardown(layout)

    def test_rapid_file_switch_drops_stale_render(
        self, qapp: QApplication, monkeypatch: Any
    ) -> None:
        """快速切换文件时 token 防陈旧：旧渲染结果被丢弃，最终显示新文件。"""
        monkeypatch.setattr(_tpl, "_MarkdownRenderer", _SlowMarkdownRenderer)
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        try:
            # 先加载慢渲染文件，随即切到快文件——旧任务结果到达时已过期
            layout.set_text_content("SLOW doc", "slow.md")
            layout.set_text_content("FAST doc", "fast.md")
            assert _pump_until(
                qapp,
                lambda: layout._markdown_view._text_browser.toPlainText().strip()
                == "out-FAST doc",
                timeout_ms=6000,
            )
            assert (
                layout._markdown_view._text_browser.toPlainText().strip()
                == "out-FAST doc"
            )
        finally:
            safe_teardown(layout)

    # ------------------------------------------------------------------
    # 编码探测 worker（todo 25：全文件 chardet 移出 UI 线程 + token 防陈旧）
    # ------------------------------------------------------------------
    _ENC_FIXTURE_DIR = (
        Path(__file__).resolve().parents[3]
        / "support"
        / "faf_core_fixtures"
        / "encoding_samples"
    )

    def test_set_file_gbk_worker_redraws_correctly(
        self, qapp: QApplication, tmp_path: Any
    ) -> None:
        """GBK 文件：快速链先显示防空白，探测 worker 完成后回调解码渲染为 GBK。"""
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        try:
            raw = (self._ENC_FIXTURE_DIR / "gbk_02.txt").read_bytes()
            path = tmp_path / "gbk.txt"
            path.write_bytes(raw)
            layout.set_file(str(path))
            # 立即（未泵事件）已有快速链显示，不空白
            fast_text = layout._source_view._text_edit.toPlainText()
            assert len(fast_text) > 0, "快速链显示不应空白"
            # 探测完成后回调重渲染为 gbk（异步，泵事件直到生效）
            assert _pump_until(
                qapp,
                lambda: layout._current_encoding == "gbk"
                and layout._source_view._text_edit.toPlainText()
                == raw.decode("gbk", errors="replace"),
                timeout_ms=6000,
            )
        finally:
            safe_teardown(layout)

    def test_set_file_utf8_no_needless_rerender(
        self, qapp: QApplication, tmp_path: Any
    ) -> None:
        """utf-8 文件：快速链已选 utf-8，探测结果一致 → 不重渲染、文本正确。"""
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        try:
            raw = (self._ENC_FIXTURE_DIR / "utf8_01.txt").read_bytes()
            path = tmp_path / "u.txt"
            path.write_bytes(raw)
            layout.set_file(str(path))
            assert _pump_until(
                qapp,
                lambda: layout._current_encoding == "utf-8"
                and layout._source_view._text_edit.toPlainText()
                == raw.decode("utf-8", errors="replace"),
                timeout_ms=6000,
            )
        finally:
            safe_teardown(layout)

    def test_rapid_file_switch_drops_stale_detection(
        self, qapp: QApplication, tmp_path: Any
    ) -> None:
        """快速切文件：旧探测任务结果被 token 丢弃，最终显示新文件正确编码。"""
        layout = TextPreviewerLayout()
        _assert_layout_geometry(layout, qapp)
        try:
            gbk_raw = (self._ENC_FIXTURE_DIR / "gbk_02.txt").read_bytes()
            utf_raw = (self._ENC_FIXTURE_DIR / "utf8_01.txt").read_bytes()
            gbk_path = tmp_path / "a_gbk.txt"
            utf_path = tmp_path / "b_utf8.txt"
            gbk_path.write_bytes(gbk_raw)
            utf_path.write_bytes(utf_raw)
            layout.set_file(str(gbk_path))
            layout.set_file(str(utf_path))
            assert _pump_until(
                qapp,
                lambda: layout._current_encoding == "utf-8"
                and layout._source_view._text_edit.toPlainText()
                == utf_raw.decode("utf-8", errors="replace"),
                timeout_ms=6000,
            )
            # 陈旧探测不得把已渲染的 utf-8 覆盖回 gbk
            qapp.processEvents()
            assert layout._current_encoding == "utf-8"
            assert (
                layout._source_view._text_edit.toPlainText()
                == utf_raw.decode("utf-8", errors="replace")
            )
        finally:
            safe_teardown(layout)


# =============================================================================
# ui.layout.preview.video_player_layout
# =============================================================================
class TestVideoPlayerLayout:
    """视频播放布局：构造契约；不带 libmpv 时不真实播放（缺失路径返回 False）。"""

    def test_construct_and_geometry(
        self, qapp: QApplication, heartbeat_manager: Any
    ) -> None:
        """默认构造 + resize 后 geometry 非空（HeartbeatManager 已启动）。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            layout = VideoPlayerLayout()
            assert layout is not None
        finally:
            qapp.setProperty("faf_disable_animation", animation_enabled_original)
        _assert_layout_geometry(layout, qapp)
        layout.deleteLater()

    def test_set_file_missing_returns_false(
        self, qapp: QApplication, heartbeat_manager: Any
    ) -> None:
        """无 libmpv 时 set_file(缺失路径) 返回 False，不做真实播放。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            layout = VideoPlayerLayout()
            assert layout.set_file(_MISSING_FILE) is False
        finally:
            qapp.setProperty("faf_disable_animation", animation_enabled_original)
        layout.deleteLater()

    def test_set_file_recovers_dead_core(
        self, qapp: QApplication, heartbeat_manager: Any, tmp_path: object
    ) -> None:
        """核心死亡时 set_file 自动重建（initialize）并重新嵌入窗口后正常加载。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            media = tmp_path / "sample.mp4"
            media.write_bytes(b"\x00" * 16)
            layout = VideoPlayerLayout()

            fake_manager: Any = MagicMock()
            fake_manager.is_core_operational.return_value = False  # 核心已死
            fake_manager.initialize.return_value = True
            fake_manager.set_window_id.return_value = True
            fake_manager.load_file.return_value = True
            fake_manager.play.return_value = True
            fake_manager.set_volume.return_value = True
            fake_manager.set_speed.return_value = True
            layout._mpv_manager = fake_manager  # noqa: SLF001

            assert layout.set_file(str(media), is_audio=False) is True
            fake_manager.initialize.assert_called_once()  # 自愈重建
            fake_manager.set_window_id.assert_called_once()  # 重新嵌入
            fake_manager.load_file.assert_called_once()
            assert layout._stack.currentIndex() == 0  # noqa: SLF001
        finally:
            qapp.setProperty("faf_disable_animation", animation_enabled_original)
        layout.deleteLater()

    def test_load_failure_shows_overlay(
        self, qapp: QApplication, heartbeat_manager: Any, tmp_path: object
    ) -> None:
        """load_file 失败时切回 overlay 显示错误（不再停留黑色视频表面）。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            media = tmp_path / "bad.mp4"
            media.write_bytes(b"\x00" * 16)
            layout = VideoPlayerLayout()

            fake_manager: Any = MagicMock()
            fake_manager.is_core_operational.return_value = True
            fake_manager.set_window_id.return_value = True
            fake_manager.load_file.return_value = False  # 加载失败
            layout._mpv_manager = fake_manager  # noqa: SLF001

            assert layout.set_file(str(media), is_audio=False) is False
            assert layout._stack.currentIndex() == 1  # noqa: SLF001
            assert "无法加载文件" in layout._placeholder.text()  # noqa: SLF001
        finally:
            qapp.setProperty("faf_disable_animation", animation_enabled_original)
        layout.deleteLater()

    def test_core_rebuild_failure_shows_overlay(
        self, qapp: QApplication, heartbeat_manager: Any, tmp_path: object
    ) -> None:
        """核心重建失败时切回 overlay 显示"无法初始化播放器"。"""
        animation_enabled_original = qapp.property("faf_disable_animation")
        try:
            qapp.setProperty("faf_disable_animation", True)
            media = tmp_path / "dead.mp4"
            media.write_bytes(b"\x00" * 16)
            layout = VideoPlayerLayout()

            fake_manager: Any = MagicMock()
            fake_manager.is_core_operational.return_value = False
            fake_manager.initialize.return_value = False  # 重建失败
            layout._mpv_manager = fake_manager  # noqa: SLF001

            assert layout.set_file(str(media), is_audio=False) is False
            assert layout._stack.currentIndex() == 1  # noqa: SLF001
            assert "无法初始化播放器" in layout._placeholder.text()  # noqa: SLF001
        finally:
            qapp.setProperty("faf_disable_animation", animation_enabled_original)
        layout.deleteLater()


# =============================================================================
# ui.layout.preview.video_player_layout — todo-30 音频元数据异步化 + 单次打开
# =============================================================================
class TestVideoPlayerLayoutAsyncAudio:
    """todo-30：音频选择后 UI 立即返回；mutagen 单次打开；调色板在 worker 线程；
    token 防陈旧（快速切音频时陈旧结果丢弃）。"""

    @staticmethod
    def _make_layout_with_fake_mpv(qapp: QApplication) -> VideoPlayerLayout:
        """构造布局并替换 MPV 管理器为假对象（不真实播放），关闭 OpenGL 初始化。"""
        layout = VideoPlayerLayout()
        fake_manager: Any = MagicMock()
        fake_manager.is_core_operational.return_value = True
        fake_manager.is_initialized.return_value = True
        fake_manager.get_duration.return_value = None
        fake_manager.get_position.return_value = None
        fake_manager.set_window_id.return_value = True
        fake_manager.load_file.return_value = True
        fake_manager.play.return_value = True
        fake_manager.set_volume.return_value = True
        fake_manager.set_speed.return_value = True
        layout._mpv_manager = fake_manager  # noqa: SLF001
        # offscreen 下避免真实 OpenGL / 流体层初始化失败
        layout._fluid_background.load = lambda: None  # type: ignore[method-assign]  # noqa: SLF001
        return layout

    @staticmethod
    def _wait_until(qapp: QApplication, cond: Any, timeout: float = 5.0) -> None:
        """有界事件泵：轮询直到条件满足或超时（让 worker 信号在 UI 线程被投递）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            qapp.processEvents()
            if cond():
                return
            time.sleep(0.02)
        qapp.processEvents()
        assert cond(), "等待异步音频元数据结果超时"

    def test_audio_select_single_open_and_worker_palette(
        self,
        qapp: QApplication,
        heartbeat_manager: Any,
        tmp_path: object,
        monkeypatch: Any,
    ) -> None:
        """happiness：音频选择 → UI 立即返回；``mutagen_file`` 单次打开（=1，而非 2）；
        调色板在 worker 线程执行（线程 id 与 UI 线程不同）。"""
        calls: List[str] = []
        palette_thread_ids: List[int] = []
        ui_thread_id = threading.get_ident()

        def _slow_mutagen(_path: str) -> "_FakeAudio":
            calls.append(str(_path))
            time.sleep(1.5)  # 模拟慢速 mutagen 解析；位于 worker 线程不阻塞 UI
            return _FakeAudio(
                tags={"APIC:": _FakeFrame(data=_MINI_PNG_BYTES)},
                info=_FakeAudioInfo(),
            )

        monkeypatch.setattr(
            "freeassetfilter.services.media_metadata_service.mutagen_file", _slow_mutagen
        )

        orig_palette = VideoPlayerLayout._extract_palette_from_cover

        def _recording_palette(cover_data: bytes) -> list:
            palette_thread_ids.append(threading.get_ident())
            return orig_palette(cover_data)

        monkeypatch.setattr(
            "freeassetfilter.ui.layout.preview.video_player_layout.VideoPlayerLayout"
            "._extract_palette_from_cover",
            staticmethod(_recording_palette),
        )

        media: Path = tmp_path / "single.mp3"
        media.write_bytes(b"x")
        layout: VideoPlayerLayout = self._make_layout_with_fake_mpv(qapp)
        try:
            start = time.time()
            assert layout.set_file(str(media), is_audio=True) is True
            elapsed = time.time() - start
            # 时间断言：mutagen 被 sleep(1.5) 延迟，但 UI 线程立即返回
            assert elapsed < 1.0

            self._wait_until(qapp, lambda: len(palette_thread_ids) > 0, timeout=5.0)

            assert len(calls) == 1  # 单文件选择的 mutagen_file 调用次数 = 1（改造前 2 次）
            assert palette_thread_ids, "调色板应在 worker 线程执行"
            assert palette_thread_ids[0] != ui_thread_id  # worker 线程 id != UI 线程
            # 等 done 回传与任务移除完成后再销毁，避免 orphaned queued 事件
            self._wait_until(
                qapp,
                lambda: len(layout._audio_meta_tasks) == 0,  # noqa: SLF001
                timeout=5.0,
            )
        finally:
            pass
        layout.cleanup()
        layout.deleteLater()

    def test_audio_select_returns_immediately(
        self,
        qapp: QApplication,
        heartbeat_manager: Any,
        tmp_path: object,
        monkeypatch: Any,
    ) -> None:
        """时间断言：mutagen 模拟延迟 2s 时 UI 线程立即返回，且返回时未开始解析。"""
        calls: List[str] = []

        def _slow_mutagen(_path: str) -> "_FakeAudio":
            calls.append(str(_path))
            time.sleep(2.0)
            return _FakeAudio(tags={}, info=_FakeAudioInfo())

        monkeypatch.setattr(
            "freeassetfilter.services.media_metadata_service.mutagen_file", _slow_mutagen
        )

        media: Path = tmp_path / "slow.mp3"
        media.write_bytes(b"x")
        layout: VideoPlayerLayout = self._make_layout_with_fake_mpv(qapp)
        try:
            start = time.time()
            assert layout.set_file(str(media), is_audio=True) is True
            elapsed = time.time() - start
            assert elapsed < 1.0  # 不被 2s 的 mutagen 模拟延迟阻塞
            assert len(calls) == 0  # 返回时 worker 尚未完成解析（异步执行）
            # 等待 worker 完成（2s 延迟耗尽）再删布局，避免 queued 信号在
            # deleteLater 之后抵达产生 teardown 噪音
            self._wait_until(qapp, lambda: len(calls) == 1, timeout=5.0)
            self._wait_until(
                qapp,
                lambda: len(layout._audio_meta_tasks) == 0,  # noqa: SLF001
                timeout=5.0,
            )
        finally:
            pass
        layout.cleanup()
        layout.deleteLater()

    def test_rapid_audio_switch_drops_stale_metadata(
        self,
        qapp: QApplication,
        heartbeat_manager: Any,
        tmp_path: object,
        monkeypatch: Any,
    ) -> None:
        """token 防陈旧：首次任务 derlay 更久、后触发任务先完成——陈旧结果被丢弃。"""
        def _path_aware_mutagen(_path: str) -> "_FakeAudio":
            if str(_path).endswith("first.mp3"):
                time.sleep(1.5)  # 第一首解析慢，最后才完成 → token 已过期
                return _FakeAudio(tags={"TITLE": "第一首"}, info=_FakeAudioInfo())
            time.sleep(0.2)  # 第二首先完成 → token 最新，应被采纳
            return _FakeAudio(tags={"TITLE": "第二首"}, info=_FakeAudioInfo())

        monkeypatch.setattr(
            "freeassetfilter.services.media_metadata_service.mutagen_file",
            _path_aware_mutagen,
        )

        first: Path = tmp_path / "first.mp3"
        second: Path = tmp_path / "second.mp3"
        first.write_bytes(b"x")
        second.write_bytes(b"x")
        layout: VideoPlayerLayout = self._make_layout_with_fake_mpv(qapp)
        try:
            layout._update_audio_metadata(str(first))  # noqa: SLF001  # token=1
            layout._update_audio_metadata(str(second))  # noqa: SLF001  # token=2

            self._wait_until(
                qapp,
                lambda: layout._music_info_panel._raw_title == "第二首",  # noqa: SLF001
                timeout=5.0,
            )
            time.sleep(1.5)  # 允许陈旧的第一首结果也完成到达
            qapp.processEvents()
            # 陈旧结果被 token 守卫丢弃：最终标题仍是第二首
            assert layout._music_info_panel._raw_title == "第二首"  # noqa: SLF001
            self._wait_until(
                qapp,
                lambda: len(layout._audio_meta_tasks) == 0,  # noqa: SLF001
                timeout=5.0,
            )
        finally:
            pass
        layout.cleanup()
        layout.deleteLater()


# =============================================================================
# ui.layout.preview.font_previewer_layout — FontLoadThread
# =============================================================================
class TestFontLoadThread:
    """FontLoadThread：文件/请求 ID/中止设置与缺失路径降级。"""

    def test_construct_and_setters(self, qapp: QApplication) -> None:
        """构造后 set_file / set_request_id 生效，未启动线程。"""
        thread = FontLoadThread()
        assert isinstance(thread, QThread)
        thread.set_file(_MISSING_FILE)
        thread.set_request_id(7)
        assert thread.file_path == _MISSING_FILE
        assert thread._request_id == 7
        thread.set_request_id(0)
        thread.abort()  # abort 标记置位
        thread.deleteLater()

    def test_run_missing_path_emits_error(self, qapp: QApplication) -> None:
        """run() 同步执行：缺失路径发 error(request_id, 消息)。"""
        thread = FontLoadThread()
        thread.set_file(_MISSING_FILE)
        thread.set_request_id(42)
        received: list = []

        def _on_error(request_id: int, msg: str) -> None:
            received.append((request_id, msg))

        thread.error.connect(_on_error)
        thread.run()  # 同步执行 run 体，避免真实后台线程
        assert len(received) == 1
        assert received[0][0] == 42
        assert "不存在" in received[0][1]
        thread.deleteLater()


# =============================================================================
# ui.layout.settings_layout — AccentColorButton
# =============================================================================
class TestAccentColorButton:
    """AccentColorButton：构造、color_hex/selected/hover_progress 与点击。"""

    def test_construct(self, qapp: QApplication) -> None:
        """默认构造：color_hex 回退为传入值，未选中、hover 进度 0。"""
        btn = AccentColorButton("#007AFF", name="蓝")
        assert btn.color_hex == "#007AFF"
        assert btn.selected is False
        assert btn.hover_progress == 0.0
        safe_teardown(btn)

    def test_value_override(self, qapp: QApplication) -> None:
        """value 参数覆盖 color_hex 返回值（自动模式用）。"""
        btn = AccentColorButton("#007AFF", value="auto")
        assert btn.color_hex == "auto"
        safe_teardown(btn)

    def test_selected_roundtrip(self, qapp: QApplication) -> None:
        """selected 可写且可读回。"""
        btn = AccentColorButton("#007AFF")
        btn.selected = True
        assert btn.selected is True
        btn.selected = False
        assert btn.selected is False
        safe_teardown(btn)

    def test_click_emits_hex(self, qapp: QApplication) -> None:
        """左键按下发射 clicked(原始 hex)。"""
        btn = AccentColorButton("#007AFF")
        received: list = []

        def _on_clicked(color: str) -> None:
            received.append(color)

        btn.clicked.connect(_on_clicked)
        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(20, 20),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        btn.mousePressEvent(press)
        assert received == ["#007AFF"]
        safe_teardown(btn)

    def test_paint_event_safe(self, qapp: QApplication) -> None:
        """离屏渲染不抛异常。"""
        btn = AccentColorButton("#007AFF", center_text="A")
        btn.selected = True
        pm = QPixmap(40, 40)
        pm.fill(QColor("#000000"))
        btn.render(pm)
        safe_teardown(btn)


# =============================================================================
# ui.layout.settings_layout — CustomAccentButton
# =============================================================================
class TestCustomAccentButton:
    """CustomAccentButton：构造、selected 与点击。"""

    def test_construct(self, qapp: QApplication) -> None:
        """默认构造未选中；传参构造选中。"""
        btn = CustomAccentButton()
        assert btn.selected is False
        btn2 = CustomAccentButton(selected=True)
        assert btn2.selected is True
        safe_teardown(btn)
        safe_teardown(btn2)

    def test_selected_setter(self, qapp: QApplication) -> None:
        """selected 可写可读回。"""
        btn = CustomAccentButton()
        btn.selected = True
        assert btn.selected is True
        safe_teardown(btn)

    def test_click_emits(self, qapp: QApplication) -> None:
        """左键按下发射 clicked。"""
        btn = CustomAccentButton()
        received: list = []

        def _on_clicked() -> None:
            received.append(True)

        btn.clicked.connect(_on_clicked)
        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(20, 20),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        btn.mousePressEvent(press)
        assert received == [True]
        safe_teardown(btn)

    def test_paint_event_safe(self, qapp: QApplication) -> None:
        """离屏渲染不抛异常。"""
        btn = CustomAccentButton(selected=True)
        pm = QPixmap(40, 40)
        pm.fill(QColor("#000000"))
        btn.render(pm)
        safe_teardown(btn)


# =============================================================================
# ui.layout.settings_layout — AppearanceSettingsPage
# =============================================================================
class TestAppearanceSettingsPage:
    """AppearanceSettingsPage：构造、设置收集、主题刷新与关闭路径。"""

    def test_construct_and_collect_settings(self, qapp: QApplication) -> None:
        """构造后 collect_settings 返回 V2 外观结构。"""
        page = AppearanceSettingsPage()
        settings = page.collect_settings()
        assert "appearance" in settings
        assert "theme" in settings["appearance"]
        assert "accent_color" in settings["appearance"]
        safe_teardown(page)

    def test_refresh_theme(self, qapp: QApplication) -> None:
        """refresh_theme：同步 toggle 状态且不抛异常。"""
        page = AppearanceSettingsPage()
        page.refresh_theme()
        assert page._dark_toggle.checked == page._dark_toggle.checked
        safe_teardown(page)

    def test_event_filter_dispatches_to_super(self, qapp: QApplication) -> None:
        """面板未创建时 eventFilter 对点击返回 False（放行继续传播）。"""
        page = AppearanceSettingsPage()
        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(10, 10),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        assert page.eventFilter(page, press) is False
        safe_teardown(page)

    def test_hide_and_close_safe(self, qapp: QApplication) -> None:
        """hideEvent / closeEvent 在面板未创建时不抛异常。"""
        page = AppearanceSettingsPage()
        page.hideEvent(QHideEvent())
        page.closeEvent(QCloseEvent())
        safe_teardown(page)

    def test_mica_sliders_removed(self, qapp: QApplication) -> None:
        """米卡参数已固定（按主题定值）：外观页不再构建滑动条配置项。"""
        page = AppearanceSettingsPage()
        assert not hasattr(page, "_mica_sliders")
        assert not hasattr(page, "_mica_value_labels")
        assert not hasattr(page, "_mica_values")
        assert not hasattr(page, "_mica_preview_timer")
        assert not hasattr(page, "_native_mica_toggle")
        safe_teardown(page)

    def test_bg_segmented_hugs_content_width(self, qapp: QApplication) -> None:
        """「窗口背景」分段控件宽度贴合选项内容，不占满页面/卡片整宽。"""
        page = AppearanceSettingsPage()
        page.resize(640, 900)
        qapp.processEvents()

        seg = page._bg_segmented
        hint = seg.sizeHint()
        assert hint.width() > 0
        assert seg.width() == hint.width()
        assert seg.width() < page.width()
        # pill 容器背景只包住选项内容
        assert int(seg._header.content_width) == seg.width()
        safe_teardown(page)

    # ── 窗口背景区块（米卡效果 / 自定义图片） ─────────────────────

    @staticmethod
    def _make_fake_bg_main_window() -> Any:
        """构造记录背景 API 调用顺序的假主窗口（无需真实 QWidget）。"""

        class _FakeBgMainWindow:
            """记录 set_background_mode / set_custom_background_image 调用。"""

            def __init__(self) -> None:
                self.mode_calls: list[str] = []
                self.image_calls: list[str] = []

            def set_background_mode(self, mode: str) -> None:
                self.mode_calls.append(mode)

            def set_custom_background_image(self, path: str) -> bool:
                self.image_calls.append(path)
                return True

        return _FakeBgMainWindow()

    @staticmethod
    def _make_fake_file_dialog(result: tuple[str, str]) -> Any:
        """构造 getOpenFileName 返回固定结果的假 QFileDialog。"""

        class _FakeFileDialog:
            """静态 getOpenFileName 返回预设 (path, filter) 元组。"""

            @staticmethod
            def getOpenFileName(*args: Any, **kwargs: Any) -> tuple[str, str]:
                return result

        return _FakeFileDialog

    def test_background_default_mica_ui_state(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """默认（V2 无背景设置）：mica 模式——分段 0、图片行隐藏、滑动条可用。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )

        page = AppearanceSettingsPage()
        assert page._bg_mode == "mica"
        assert page._bg_image_name == ""
        assert page._bg_segmented.current_index == 1
        assert page._bg_image_row.isVisibleTo(page) is False
        assert page._bg_file_label.text() == "未设置"
        safe_teardown(page)

    def test_background_image_mode_loaded_from_v2(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """V2 保存 image 模式且文件存在：初始即 image UI 状态（不触发应用）。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )
        from components.custom_background import BACKGROUND_DIR_NAME

        tmp_file = str(tmp_path / "settings_v2.json")
        v2 = SettingsManagerV2(tmp_file)
        v2.load()
        v2.set(
            "appearance.background",
            {"mode": "image", "image": "custom_background.png"},
        )
        v2.save()

        bg_dir = tmp_path / BACKGROUND_DIR_NAME
        bg_dir.mkdir()
        pm = QPixmap(16, 16)
        pm.fill(QColor("#336699"))
        assert pm.save(str(bg_dir / "custom_background.png"), "PNG") is True

        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))

        page = AppearanceSettingsPage()
        assert page._bg_mode == "image"
        assert page._bg_image_name == "custom_background.png"
        assert page._bg_segmented.current_index == 2
        assert page._bg_image_row.isVisibleTo(page) is True
        assert page._bg_file_label.text() == "custom_background.png"
        safe_teardown(page)

    def test_apply_background_settings_routes_and_saves(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """_apply_background_settings：暂存优先（未提交不触碰主窗口与磁盘）。

        新语义：仅写入暂存缓存并刷新本页 UI；主窗口应用与 V2 落盘统一由
        ``SettingsLayout._submit_settings`` 在点击应用/确定时执行。
        """
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "_find_main_window", lambda self: fake_mw
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))

        page = AppearanceSettingsPage()
        page._bg_image_name = "custom_background.png"

        # image 暂存：不直调主窗口、不落盘，仅缓存 + UI 可见
        page._apply_background_settings("image")
        assert fake_mw.image_calls == []
        assert fake_mw.mode_calls == []
        assert page._staging_cache.get("appearance.background.mode") == "image"
        assert page._staging_cache.get("appearance.background.image") == "custom_background.png"
        assert page._bg_image_row.isVisibleTo(page) is True

        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background.mode") == "mica"

        # mica 暂存：同样仅缓存，不动主窗口图片接口
        page._apply_background_settings("mica")
        assert fake_mw.mode_calls == []
        assert len(fake_mw.image_calls) == 0
        assert page._bg_image_row.isVisibleTo(page) is False
        assert page._staging_cache.get("appearance.background.mode") == "mica"
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background.mode") == "mica"
        safe_teardown(page)

    def test_bg_segment_switch_with_existing_image(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """已有持久化图片时切换分段：暂存 image 模式（不经文件对话框、不直写）。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )
        from components.custom_background import BACKGROUND_DIR_NAME

        tmp_file = str(tmp_path / "settings_v2.json")
        bg_dir = tmp_path / BACKGROUND_DIR_NAME
        bg_dir.mkdir()
        pm = QPixmap(16, 16)
        pm.fill(QColor("#336699"))
        assert pm.save(str(bg_dir / "custom_background.png"), "PNG") is True

        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "_find_main_window", lambda self: fake_mw
        )

        page = AppearanceSettingsPage()
        page._bg_image_name = "custom_background.png"
        # 模拟用户点击图像分段（触发 current_changed → 处理器，仅暂存）
        page._bg_segmented.set_current_index(2)

        assert page._bg_mode == "image"
        assert page._staging_cache.get("appearance.background.mode") == "image"
        assert len(fake_mw.image_calls) == 0
        assert fake_mw.mode_calls == []
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background.mode") == "mica"
        safe_teardown(page)

    def test_bg_segment_switch_cancel_reverts(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """无图片时切换分段后取消选择：分段回退、设置不变、不调用主窗口。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))
        monkeypatch.setattr(
            sl_mod, "QFileDialog", self._make_fake_file_dialog(("", ""))
        )
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "_find_main_window", lambda self: fake_mw
        )

        page = AppearanceSettingsPage()
        page._bg_segmented.set_current_index(2)

        # 取消：分段编程式回退到云母，模式与持久化设置保持默认（未被写入）
        assert page._bg_segmented.current_index == 1
        assert page._bg_mode == "mica"
        assert fake_mw.mode_calls == []
        assert fake_mw.image_calls == []
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background") == {"mode": "mica", "image": "", "ambient": True, "blur": 0, "transparency": 80}
        safe_teardown(page)

    def test_bg_segment_switch_import_failure_shows_dialog(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """导入失败：弹 danger 对话框、分段回退、不切换不改设置。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))
        monkeypatch.setattr(
            sl_mod, "QFileDialog",
            self._make_fake_file_dialog(("D:/fake/pic.png", "图片文件 (*.png)")),
        )
        monkeypatch.setattr(
            sl_mod, "import_custom_background_image", lambda path: None
        )
        dialog_calls: list[dict] = []
        monkeypatch.setattr(
            sl_mod, "create_danger_dialog",
            lambda **kwargs: dialog_calls.append(kwargs),
        )
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "_find_main_window", lambda self: fake_mw
        )

        page = AppearanceSettingsPage()
        page._bg_segmented.set_current_index(2)

        assert len(dialog_calls) == 1
        assert dialog_calls[0]["title"] == "导入失败"
        assert page._bg_segmented.current_index == 1
        assert page._bg_mode == "mica"
        assert fake_mw.mode_calls == []
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background") == {"mode": "mica", "image": "", "ambient": True, "blur": 0, "transparency": 80}
        safe_teardown(page)

    def test_choose_bg_image_success_via_button(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """按钮点击选择图片成功：暂存文件名与 image 模式（提交前不直写）。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )
        monkeypatch.setattr(sl_mod, "get_app_data_path", lambda: str(tmp_path))
        monkeypatch.setattr(
            sl_mod, "QFileDialog",
            self._make_fake_file_dialog(("D:/fake/pic.png", "图片文件 (*.png)")),
        )
        dest = str(tmp_path / "backgrounds" / "custom_background.png")
        monkeypatch.setattr(
            sl_mod, "import_custom_background_image", lambda path: dest
        )
        fake_mw = self._make_fake_bg_main_window()
        monkeypatch.setattr(
            sl_mod.AppearanceSettingsPage, "_find_main_window", lambda self: fake_mw
        )

        page = AppearanceSettingsPage()
        # 模拟按钮点击（clicked → _on_choose_bg_image_clicked → 非强制选择）
        page._bg_choose_btn.click()

        assert page._bg_image_name == "custom_background.png"
        assert page._bg_file_label.text() == "custom_background.png"
        assert page._bg_mode == "image"
        assert page._bg_segmented.current_index == 1  # 按钮入口不切分段
        assert page._staging_cache.get("appearance.background.image") == "custom_background.png"
        assert fake_mw.image_calls == []
        assert fake_mw.mode_calls == []
        saved = SettingsManagerV2(tmp_file)
        saved.load()
        assert saved.get("appearance.background.mode") == "mica"
        safe_teardown(page)

    def test_update_bg_ui_state_toggles_image_row(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """_update_bg_ui_state：image 模式显示图片行，mica 模式隐藏。"""
        import freeassetfilter.ui.layout.settings_layout as sl_mod
        from freeassetfilter.core.managers.settings_manager_v2 import (
            SettingsManagerV2,
        )

        tmp_file = str(tmp_path / "settings_v2.json")
        monkeypatch.setattr(
            sl_mod, "SettingsManagerV2", lambda *a, **k: SettingsManagerV2(tmp_file)
        )

        page = AppearanceSettingsPage()
        page._bg_mode = "image"
        page._update_bg_ui_state()
        assert page._bg_image_row.isVisibleTo(page) is True

        page._bg_mode = "mica"
        page._update_bg_ui_state()
        assert page._bg_image_row.isVisibleTo(page) is False
        safe_teardown(page)


# =============================================================================
# _load_all 保持 Python（faf-core-rust-migration todo 10 回归测试）
# =============================================================================

class TestLoadAllStaysPython:
    """``FileSelectorLayout._load_all`` 保持 Python 实现，不经 faf_core native。

    回归背景（.omo/plans/faf-core-rust-migration todo 10）：「All」视图枚举
    逻辑驱动器（GetLogicalDrives 位掩码 ≤26 个盘 + 每盘 os.stat）无性能需求，
    显式排除出 native 范围。本组 mock 位掩码 + 注入确定性元数据，断言驱动
    列表正确且枚举路径仍为 Python（os.stat 逐盘调用、faf_core 桥零触碰）。
    """

    def test_load_all_drives_from_bitmask_stays_python(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """mock GetLogicalDrives 位掩码 → 模型驱动列表正确且确认保持 Python。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            monkeypatch: 用例级猴子补丁。
        """
        import ctypes

        import freeassetfilter.ui.layout.file_selector_layout as fsl_mod
        from components.file_list_model import FileNameRole, FilePathRole, IsDirRole

        # 位掩码 0b0000_0000_0000_0111 = 位 0/1/2 → A:/B:/C:
        drives_bitmask: int = 0b0000_0000_0000_0111
        stat_calls: list[str] = []
        bridge_calls: list[str] = []
        fake_stat = MagicMock(
            st_mtime=1_700_000_000.0,
            st_ctime=1_700_000_000.0,
        )
        orig_stat = os.stat

        def _fake_stat(path: object, **kwargs: object) -> object:
            """仅拦截驱动器根 stat（记录 + 返回确定性元数据），其余委托真实实现。"""
            if isinstance(path, str) and path in ("A:\\", "B:\\", "C:\\"):
                stat_calls.append(path)
                return fake_stat
            return orig_stat(path, **kwargs)

        monkeypatch.setattr(
            fsl_mod,
            "get_faf_core_bridge",
            lambda: bridge_calls.append("bridge"),
        )
        monkeypatch.setattr(
            ctypes.windll.kernel32, "GetLogicalDrives", lambda: drives_bitmask
        )
        monkeypatch.setattr(os, "stat", _fake_stat)

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            layout._load_all()

            model = layout._file_model
            assert model.rowCount() == 3
            names = [
                model.data(model.index(i, 0), FileNameRole) for i in range(model.rowCount())
            ]
            paths = [
                model.data(model.index(i, 0), FilePathRole) for i in range(model.rowCount())
            ]
            assert names == ["A:", "B:", "C:"]
            assert paths == ["A:\\", "B:\\", "C:\\"]
            for i in range(model.rowCount()):
                assert model.data(model.index(i, 0), IsDirRole) is True
            # 确认走 Python：逐盘 os.stat 一次，faf_core 桥完全不触碰
            assert stat_calls == ["A:\\", "B:\\", "C:\\"]
            assert bridge_calls == [], "_load_all 不得触碰 faf_core 桥（保持 Python）"
        finally:
            safe_teardown(layout)
            qapp.processEvents()

    def test_load_all_skips_unset_drive_bits(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """位掩码间隙正确跳过：0b101 → 仅 A:/C: 两盘进入模型。

        Args:
            qapp: 会话级 QApplication（offscreen）。
            monkeypatch: 用例级猴子补丁。
        """
        import ctypes

        import freeassetfilter.ui.layout.file_selector_layout as fsl_mod
        from components.file_list_model import FileNameRole

        fake_stat = MagicMock(
            st_mtime=1_700_000_000.0,
            st_ctime=1_700_000_000.0,
        )
        orig_stat = os.stat

        def _fake_stat(path: object, **kwargs: object) -> object:
            """仅拦截驱动器根 stat，其余委托真实实现（避免污染 pytest 内部）。"""
            if isinstance(path, str) and path in ("A:\\", "C:\\"):
                return fake_stat
            return orig_stat(path, **kwargs)

        monkeypatch.setattr(
            fsl_mod, "get_faf_core_bridge", lambda: None
        )
        monkeypatch.setattr(
            ctypes.windll.kernel32, "GetLogicalDrives", lambda: 0b101
        )
        monkeypatch.setattr(os, "stat", _fake_stat)

        layout = FileSelectorLayout()
        layout.resize(*_LAYOUT_SIZE)
        qapp.processEvents()
        try:
            layout._load_all()

            model = layout._file_model
            assert model.rowCount() == 2
            names = [
                model.data(model.index(i, 0), FileNameRole) for i in range(model.rowCount())
            ]
            assert names == ["A:", "C:"]
        finally:
            safe_teardown(layout)
            qapp.processEvents()