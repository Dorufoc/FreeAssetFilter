# -*- coding: utf-8 -*-
"""Office 相关 session fixtures 的冒烟测试。

消费 ``tests/conftest.py`` 中新增的 ``soffice_available`` 与
``com_available`` 两个 session-scoped fixtures，确保 ``pytest -k office``
能收集到用例（否则收集数为 0 时 pytest 会以 exit code 5 空跑通过）。
"""


def test_soffice_available_is_bool(soffice_available):
    """soffice_available fixture 必须返回 bool。"""
    assert isinstance(soffice_available, bool)


def test_com_available_is_bool(com_available):
    """com_available fixture 必须返回 bool。"""
    assert isinstance(com_available, bool)
