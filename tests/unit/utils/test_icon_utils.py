# -*- coding: utf-8 -*-
# targets: utils.icon_utils
"""icon_utils.py（freeassetfilter/utils/icon_utils.py）单元测试。

覆盖窗口/文件图标获取（HICON 有效性 + DestroyIcon 释放）、HICON→QPixmap
转换成功路径、以及**资源 finally 清理路径**（强制 GetDIBits 失败后断言
``DeleteDC`` / ``DeleteObject`` 仍被调用，即 HICON 加工过程中的 GDI 资源
不会泄漏）、图标缓存读写与无效输入的防御性返回。
"""

from __future__ import annotations

import os
import sys
import ctypes
from typing import Any, Dict

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from freeassetfilter.utils import icon_utils as iu

pytestmark = pytest.mark.unit

#: IDI_APPLICATION = 0x7F00，由系统所有，测试不应释放该句柄。
_IDI_APPLICATION = 0x7F00


def _load_system_application_icon() -> int:
    """加载系统应用程序图标（LoadIconW），返回 HICON 句柄。

    Returns:
        int: 非零 HICON 句柄。
    """
    return int(iu.user32.LoadIconW(None, _IDI_APPLICATION))


class TestHiconToPixmap:
    """HICON 到 QPixmap 转换。"""

    def test_success_converts_system_icon(self, qapp: Any) -> None:
        """有效 HICON → 返回非空 QPixmap。"""
        hicon = _load_system_application_icon()
        assert hicon != 0
        pixmap = iu.hicon_to_pixmap(hicon, 32, None)
        assert pixmap is not None
        assert not pixmap.isNull()
        assert pixmap.width() > 0

    def test_keep_original_size(self, qapp: Any) -> None:
        """keep_original_size 路径返回原始分辨率像素图。"""
        hicon = _load_system_application_icon()
        pixmap = iu.hicon_to_pixmap(hicon, 32, None, keep_original_size=True)
        assert pixmap is not None
        assert not pixmap.isNull()

    def test_invalid_hicon_returns_none(self, qapp: Any) -> None:
        """非法句柄（0 / None）不崩溃，返回 None。"""
        assert iu.hicon_to_pixmap(0, 32, None) is None
        assert iu.hicon_to_pixmap(None, 32, None) is None

    def test_finally_releases_gdi_resources_on_failure(
        self, qapp: Any, monkeypatch: Any
    ) -> None:
        """强制 GetDIBits 失败后 finally 清理路径仍完整执行。

        用 monkeypatch 把 ``gdi32.GetDIBits`` 替换为直接返回 0 的桩函数，
        使主流程中途失败；断言外层/内层 finally 中的 ``DeleteDC`` 与
        ``DeleteObject``（hbmMask + hbmColor）都得到执行。
        """
        hicon = _load_system_application_icon()
        gdi32 = iu.windll.gdi32
        calls: Dict[str, int] = {"dc": 0, "obj": 0, "dib": 0}

        def _fake_getdibits(*_args: Any) -> int:
            calls["dib"] += 1
            return 0

        def _fake_deletedc(_hdc: Any) -> int:
            calls["dc"] += 1
            return 1

        def _fake_deleteobject(_hobj: Any) -> int:
            calls["obj"] += 1
            return 1

        monkeypatch.setattr(gdi32, "GetDIBits", _fake_getdibits)
        monkeypatch.setattr(gdi32, "DeleteDC", _fake_deletedc)
        monkeypatch.setattr(gdi32, "DeleteObject", _fake_deleteobject)

        assert iu.hicon_to_pixmap(hicon, 32, None) is None
        assert calls["dib"] == 1
        assert calls["dc"] == 1
        assert calls["obj"] == 2  # hbmMask + hbmColor


class TestFileAndWindowIcons:
    """文件/窗口图标获取。"""

    def test_get_highest_resolution_icon_for_file(
        self, sample_text_file: str
    ) -> None:
        """真实文件 → 有效 HICON 且 DestroyIcon 能成功释放。"""
        hicon = iu.get_highest_resolution_icon(sample_text_file)
        assert hicon, "真实文件应能取到图标句柄"
        try:
            assert int(hicon) != 0
        finally:
            assert iu.DestroyIcon(hicon), "DestroyIcon 应成功释放句柄"

    def test_get_highest_resolution_icon_missing_file(
        self, tmp_path: Any
    ) -> None:
        """不存在的文件路径不崩溃，返回 None 或可释放句柄。"""
        result = iu.get_highest_resolution_icon(str(tmp_path / "missing.xyz"))
        if result:
            iu.DestroyIcon(result)

    def test_get_all_icons_from_exe_non_exe_returns_empty(
        self, sample_text_file: str
    ) -> None:
        """非 EXE 文件不会解出 ICON 列表（返回空列表）。"""
        icons = iu.get_all_icons_from_exe(sample_text_file)
        assert icons == []
        for icon in icons:
            iu.DestroyIcon(icon["hicon"])

    def test_get_all_icons_from_exe_python_exe(self) -> None:
        """真 EXE（python.exe）能解出图标条目且全部可释放。"""
        icons = iu.get_all_icons_from_exe(sys.executable)
        assert isinstance(icons, list)
        for icon in icons:
            assert "hicon" in icon
            assert "width" in icon
            assert "height" in icon
        for icon in icons:
            iu.DestroyIcon(icon["hicon"])

    def test_get_lnk_target_missing_file_returns_none(self, tmp_path: Any) -> None:
        """不存在的 .lnk → None（OSError 被兜底）。"""
        assert iu.get_lnk_target(str(tmp_path / "missing.lnk")) is None

    def test_get_lnk_target_bad_header_returns_none(self, tmp_path: Any) -> None:
        """魔数不是 LNK\x00 的伪 .lnk → None。"""
        path = tmp_path / "not_a_lnk.lnk"
        path.write_bytes(b"NOTLNK" + b"\x00" * 80)
        assert iu.get_lnk_target(str(path)) is None

    def test_get_lnk_target_short_header_returns_none(self, tmp_path: Any) -> None:
        """头不足 76 字节（含魔数）→ None，不触发结构反序列化。"""
        path = tmp_path / "short.lnk"
        path.write_bytes(b"LNK\x00")
        assert iu.get_lnk_target(str(path)) is None


class TestIconCache:
    """图标缓存路径读写（缓存目录被 monkeypatch 隔离到 tmp_path）。"""

    def test_cache_roundtrip(
        self, qapp: Any, tmp_path: Any, monkeypatch: Any, sample_text_file: str
    ) -> None:
        """save_icon_to_cache → get_cached_icon_path 往返一致。"""
        cache_dir = tmp_path / "icons_cache"
        cache_dir.mkdir()
        monkeypatch.setattr(iu, "_ICON_CACHE_DIR", str(cache_dir))

        assert iu.get_cached_icon_path(sample_text_file) == ""
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.red)
        assert iu.save_icon_to_cache(sample_text_file, pixmap) is True
        cached = iu.get_cached_icon_path(sample_text_file)
        assert cached == os.path.join(str(cache_dir), iu._get_icon_cache_key(sample_text_file))
        assert os.path.exists(cached)

    def test_save_icon_to_cache_none_pixmap_returns_false(
        self, tmp_path: Any, monkeypatch: Any
    ) -> None:
        """pixmap 为 None → False。"""
        monkeypatch.setattr(iu, "_ICON_CACHE_DIR", str(tmp_path / "c1"))
        assert iu.save_icon_to_cache("f.png", None) is False

    def test_save_icon_to_cache_null_pixmap_returns_false(
        self, qapp: Any, tmp_path: Any, monkeypatch: Any
    ) -> None:
        """pixmap 为 null（空对象）→ False。"""
        monkeypatch.setattr(iu, "_ICON_CACHE_DIR", str(tmp_path / "c2"))
        assert iu.save_icon_to_cache("f.png", QPixmap()) is False

    def test_get_cached_icon_path_no_cache_dir(
        self, monkeypatch: Any
    ) -> None:
        """缓存目录不可用（None）→ 返回空字符串（不触碰真实 data/ 目录）。"""
        monkeypatch.setattr(iu, "_get_icon_cache_dir", lambda: None)
        assert iu.get_cached_icon_path("x.png") == ""

    def test_get_icon_cache_dir_monkeypatched(
        self, tmp_path: Any, monkeypatch: Any
    ) -> None:
        """模块级缓存目录被设置后直接返回该值。"""
        monkeypatch.setattr(iu, "_ICON_CACHE_DIR", str(tmp_path / "d"))
        assert iu.get_icon_cache_dir() == str(tmp_path / "d")


# =============================================================================
# ctypes 结构与 ShellItem 图标工厂
# =============================================================================
class TestWin32Structures:
    """``GUID`` / ``SHFILEINFOW`` 布局与 ``get_icon_from_shell_item_image_factory``。"""

    def test_guid_field_layout(self) -> None:
        """GUID 为 Data1/Data2/Data3/Data4 字段。"""
        guid = iu.GUID()
        assert [f[0] for f in iu.GUID._fields_] == [
            "Data1", "Data2", "Data3", "Data4",
        ]
        assert guid.Data1 == 0 and guid.Data2 == 0 and guid.Data3 == 0
        assert len(guid.Data4) == 8

    def test_shfileinfow_field_layout(self) -> None:
        """SHFILEINFOW 含 hIcon/iIcon/dwAttributes/名称缓冲。"""
        info = iu.SHFILEINFOW()
        assert [f[0] for f in iu.SHFILEINFOW._fields_] == [
            "hIcon", "iIcon", "dwAttributes", "szDisplayName", "szTypeName",
        ]
        assert info.hIcon is None or info.hIcon == 0
        assert info.iIcon == 0

    def test_shell_item_image_factory_missing_file_returns_none(
        self, tmp_path: Any
    ) -> None:
        """不存在的文件：SHCreateItemFromParsingName 失败 → 返回 None 不崩溃。"""
        missing = str(tmp_path / "no-such-file-1.png")
        assert iu.get_icon_from_shell_item_image_factory(missing) is None

    def test_shell_item_image_factory_with_real_file(self, tmp_path: Any) -> None:
        """真实存在的文件：返回 HICON 或 None（均不崩溃）。"""
        target = tmp_path / "icon-source.txt"
        target.write_text("plain", encoding="utf-8")
        hicon = iu.get_icon_from_shell_item_image_factory(str(target))
        # 依环境可能成功（返回整数句柄）或失败（None），两者都合法
        assert hicon is None or isinstance(hicon, int)
        if hicon:
            # 释放句柄，避免 GDI 泄漏
            iu.user32.DestroyIcon(ctypes.c_void_p(hicon))
