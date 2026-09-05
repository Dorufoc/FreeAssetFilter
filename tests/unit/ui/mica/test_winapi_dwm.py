"""原生 DWM 云母桥接的单元测试（``ui.mica.winapi``）。

通过 monkeypatch ``_get_dwmapi`` 把一个记录调用的假 ``dwmapi`` 句柄注入，
验证：

* :func:`dwm_set_system_backdrop` 把属性号设为 ``DWMWA_SYSTEMBACKDROP_TYPE=38``、
  值与 ``cbAttribute`` 正确封送（``c_uint`` + ``sizeof=4``）；
* :func:`dwm_extend_frame_into_client_area` 的 ``MARGINS`` 在开启时四边
  ``-1``、关闭时四边 ``0``；
* :func:`set_native_mica` 在开启 / 关闭间正确映射 ``DWMSBT_MAINWINDOW /
  DWMSBT_DISABLED`` 并联动帧扩展；
* 非 Windows / 缺失 dwmapi / 调用失败均安全返回 ``False``，绝不抛异常。
"""

import ctypes
import sys
import types

import pytest

from freeassetfilter.ui.mica import winapi


def _fake_dwmapi(captured) -> object:
    """构造一个记录调用的假 dwmapi 句柄（用普通函数，便于设置 argtypes）。"""

    def _set(hwnd, attr, pv, cb):
        captured["set"] = (hwnd, attr, pv, cb)
        return 0  # S_OK

    def _extend(hwnd, margins):
        captured["extend"] = (hwnd, margins)
        return 0  # S_OK

    return types.SimpleNamespace(
        DwmSetWindowAttribute=_set,
        DwmExtendFrameIntoClientArea=_extend,
    )


@pytest.fixture
def fake_dwmapi(monkeypatch):
    """把 ``_get_dwmapi`` 替换为返回记录调用的假句柄。"""
    captured = {}
    lib = _fake_dwmapi(captured)
    monkeypatch.setattr(winapi, "_get_dwmapi", lambda: lib)
    # 关闭一侧的「已探测缓存」，确保总是返回注入的假句柄。
    monkeypatch.setattr(winapi, "_dwmapi", lib)
    return captured


def test_constants_are_correct() -> None:
    """DWM 属性号与云母背景类型枚举符合 Win11 SDK 约定。"""
    assert winapi.DWMWA_SYSTEMBACKDROP_TYPE == 38
    assert winapi.DWMSBT_DISABLED == 0
    assert winapi.DWMSBT_MAINWINDOW == 2


def test_set_system_backdrop_marshals_attribute_and_value(fake_dwmapi) -> None:
    """``dwm_set_system_backdrop`` 正确封送属性号、值与 sizeof。"""
    ok = winapi.dwm_set_system_backdrop(0x1234, winapi.DWMSBT_MAINWINDOW)
    assert ok is True
    hwnd, attr, pv, cb = fake_dwmapi["set"]
    assert hwnd == 0x1234
    assert int(attr.value) == winapi.DWMWA_SYSTEMBACKDROP_TYPE  # 38
    assert int(pv._obj.value) == winapi.DWMSBT_MAINWINDOW  # 2
    assert int(cb.value) == 4  # sizeof(DWORD)


def test_extend_frame_margins_neg1_when_enabled(fake_dwmapi) -> None:
    """开启时 ``MARGINS`` 四边为 -1（整个客户区可透出系统背景）。"""
    ok = winapi.dwm_extend_frame_into_client_area(0x1234, True)
    assert ok is True
    _hwnd, margins = fake_dwmapi["extend"]
    m = margins._obj
    assert (m.cxLeftWidth, m.cxRightWidth,
            m.cyTopHeight, m.cyBottomHeight) == (-1, -1, -1, -1)


def test_extend_frame_margins_zero_when_disabled(fake_dwmapi) -> None:
    """关闭时 ``MARGINS`` 四边归零，恢复正常客户区。"""
    ok = winapi.dwm_extend_frame_into_client_area(0x1234, False)
    assert ok is True
    _hwnd, margins = fake_dwmapi["extend"]
    m = margins._obj
    assert (m.cxLeftWidth, m.cxRightWidth,
            m.cyTopHeight, m.cyBottomHeight) == (0, 0, 0, 0)


def test_set_native_mica_enabled_maps_mainwindow(fake_dwmapi) -> None:
    """开启：背景类型 = MAINWINDOW 且帧扩展开启。"""
    ok = winapi.set_native_mica(0x1234, True)
    assert ok is True
    assert int(fake_dwmapi["set"][2]._obj.value) == winapi.DWMSBT_MAINWINDOW
    assert fake_dwmapi["extend"][1]._obj.cxLeftWidth == -1


def test_set_native_mica_disabled_maps_disabled(fake_dwmapi) -> None:
    """关闭：背景类型 = DISABLED 且帧扩展收回。"""
    ok = winapi.set_native_mica(0x1234, False)
    assert ok is True
    assert int(fake_dwmapi["set"][2]._obj.value) == winapi.DWMSBT_DISABLED
    assert fake_dwmapi["extend"][1]._obj.cxLeftWidth == 0


def test_set_native_mica_fails_gracefully_on_bad_hwnd() -> None:
    """``hwnd`` 为 0 时安全返回 False（不抛异常）。"""
    assert winapi.set_native_mica(0, True) is False
    assert winapi.set_native_mica(0, False) is False


def test_missing_dwmapi_returns_false(monkeypatch) -> None:
    """``_get_dwmapi`` 返回 ``None``（缺失）时全部接口安全返回 False。"""
    monkeypatch.setattr(winapi, "_get_dwmapi", lambda: None)
    monkeypatch.setattr(winapi, "_dwmapi", None)
    assert winapi.dwm_set_system_backdrop(0x1234, winapi.DWMSBT_MAINWINDOW) is False
    assert winapi.dwm_extend_frame_into_client_area(0x1234, True) is False
    assert winapi.set_native_mica(0x1234, True) is False


def test_dwmapi_call_failure_propagates_false(monkeypatch) -> None:
    """``DwmSetWindowAttribute`` 返回失败 HRESULT 时返回 False。"""
    captured = {}

    def _set_fail(hwnd, attr, pv, cb):
        captured["called"] = True
        return -2147024809  # E_INVALIDARG（旧系统不支持该属性）

    def _extend_fail(hwnd, margins):
        return -2147024809

    fake = types.SimpleNamespace(
        DwmSetWindowAttribute=_set_fail,
        DwmExtendFrameIntoClientArea=_extend_fail,
    )
    monkeypatch.setattr(winapi, "_get_dwmapi", lambda: fake)
    monkeypatch.setattr(winapi, "_dwmapi", fake)
    assert winapi.set_native_mica(0x1234, True) is False
    assert captured["called"] is True


def test_non_windows_skips_dwm(monkeypatch) -> None:
    """``IS_WINDOWS`` 为 False 时直接返回 False，不触碰 dwmapi。"""
    monkeypatch.setattr(winapi, "IS_WINDOWS", False)
    assert winapi.set_native_mica(0x1234, True) is False
    assert winapi.dwm_set_system_backdrop(0x1234, 2) is False
    assert winapi.dwm_extend_frame_into_client_area(0x1234, True) is False


# ---------------------------------------------------------------------------
# 深浅色对齐（DWMWA_USE_IMMERSIVE_DARK_MODE）
# ---------------------------------------------------------------------------


def test_use_dark_mode_marshals_attribute_and_value(fake_dwmapi) -> None:
    """``dwm_use_dark_mode`` 正确封送属性号 20 与布尔值（深色=1）。"""
    ok = winapi.dwm_use_dark_mode(0x1234, True)
    assert ok is True
    hwnd, attr, pv, cb = fake_dwmapi["set"]
    assert hwnd == 0x1234
    assert int(attr.value) == winapi.DWMWA_USE_IMMERSIVE_DARK_MODE
    assert int(pv._obj.value) == 1
    assert int(cb.value) == 4


def test_use_dark_mode_false_maps_zero(fake_dwmapi) -> None:
    """浅色模式：属性值封送为 0。"""
    assert winapi.dwm_use_dark_mode(0x1234, False) is True
    _hwnd, _attr, pv, _cb = fake_dwmapi["set"]
    assert int(pv._obj.value) == 0


def test_use_dark_mode_fails_gracefully(monkeypatch) -> None:
    """非 Windows / 缺失 dwmapi / hwnd=0 时安全返回 False。"""
    assert winapi.dwm_use_dark_mode(0, True) is False
    monkeypatch.setattr(winapi, "_get_dwmapi", lambda: None)
    monkeypatch.setattr(winapi, "_dwmapi", None)
    assert winapi.dwm_use_dark_mode(0x1234, True) is False
    monkeypatch.setattr(winapi, "IS_WINDOWS", False)
    assert winapi.dwm_use_dark_mode(0x1234, False) is False
