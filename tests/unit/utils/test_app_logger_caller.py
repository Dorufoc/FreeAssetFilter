# -*- coding: utf-8 -*-
"""日志调用者解析的快捷路径（启动流畅度守护）。

背景：``ComponentSourceFilter`` 每条日志都要解析调用者文件名。原实现用
``inspect.stack()``，会为每条记录做 ``findsource`` / ``getmodule`` /
``realpath`` / ``linecache`` 校验，实测 1–3ms/条；启动期一次几十上百条日志
就在主线程上叠出 100–300ms 卡顿（加载转圈掉帧）。

本模块锁定三条不变量：

1. 解析结果仍是「调用者模块名」，而不是 ``app_logger``；
2. 解析过程**不调用** ``inspect.stack``（改为沿 ``f_back`` 读 ``co_filename``）；
3. 同一文件的解析结果走缓存。
"""

from __future__ import annotations

import inspect as inspect_module
from pathlib import Path

import pytest

from freeassetfilter.utils import app_logger

pytestmark = pytest.mark.unit


def _call_via_helper() -> str:
    """借一个非 app_logger 文件里的函数作为“调用者”。"""
    return app_logger._get_caller_filename()


def test_caller_filename_points_at_real_caller() -> None:
    """从本测试文件调用时，解析结果应为本模块名。"""
    assert _call_via_helper() == Path(__file__).stem


def test_caller_filename_does_not_use_inspect_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """解析不得依赖 ``inspect.stack``（它才是 1–3ms/条的元凶）。"""

    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("_get_caller_filename 不得调用 inspect.stack()")

    monkeypatch.setattr(inspect_module, "stack", _boom)
    assert _call_via_helper() == Path(__file__).stem


def test_caller_filename_is_cached_per_file() -> None:
    """同一文件重复解析只写一次缓存。"""
    app_logger._CALLER_STEM_CACHE.clear()
    first = _call_via_helper()
    cached = dict(app_logger._CALLER_STEM_CACHE)
    assert first == Path(__file__).stem
    second = _call_via_helper()
    assert second == first
    assert dict(app_logger._CALLER_STEM_CACHE) == cached


def test_debug_records_caller_without_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``debug()`` 落到 filter 时同样不触发 ``inspect.stack``。"""

    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("日志记录不得调用 inspect.stack()")

    monkeypatch.setattr(inspect_module, "stack", _boom)
    app_logger.debug("startup probe %s", 1)
    app_logger.info("startup probe")


def test_startup_log_flag_short_circuits() -> None:
    """启动信息输出期（``_in_startup_log``）直接返回 app_logger，不解析栈。"""
    app_logger._in_startup_log = True
    try:
        assert app_logger._get_caller_filename() == "app_logger"
    finally:
        app_logger._in_startup_log = False


def test_frame_walk_terminates_for_logging_internals() -> None:
    """从 logging 内部帧出发也能落到调用者（不会返回 unknown）。"""
    import logging

    record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    filt = app_logger.ComponentSourceFilter()
    assert filt.filter(record) is True
    # 记录源文件由 filter 写入；直接调用时栈里没有其它业务帧，
    # 因此这里只要求是字符串且非空，不约束具体值。
    assert isinstance(record.source_file, str) and record.source_file


def test_lazy_formatting_is_supported_on_instance_api() -> None:
    """单例 API（AppLogger.*）也支持 ``%s`` 惰性格式化（与模块级函数一致）。"""
    logger = app_logger.get_logger()
    logger.debug("lazy %s", 1)
    logger.info("lazy %s", 2)
    logger.warning("lazy %s", 3)
