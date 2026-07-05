from __future__ import annotations

import pytest

try:
    from tests.unit._file_selector_flow_harness import FileSelectorFlowHarness
except ImportError:
    pytest.skip("requires _file_selector_flow_harness", allow_module_level=True)


def test_fast_scroll_defers_system_icon_requests_until_resume(qt_app):
    harness = FileSelectorFlowHarness(qt_app)
    try:
        files = harness.set_system_icon_files(["exe", "url", "lnk"])

        placeholders = harness.render_rows([0])
        assert [harness.color_of(pixmap) for pixmap in placeholders] == [
            harness.placeholder_color.name(),
        ]
        assert [request[0] for request in harness.loader.requests] == [files[0]["path"]]

        harness.loader.clear_requests()
        harness.start_fast_scroll()
        assert harness.view.is_scroll_optimizing() is True

        placeholders = harness.render_rows([1, 2])
        assert [harness.color_of(pixmap) for pixmap in placeholders] == [
            harness.placeholder_color.name(),
            harness.placeholder_color.name(),
        ]
        assert harness.loader.requests == []

        harness.resume_scroll()
        assert harness.view.is_scroll_optimizing() is False

        harness.render_rows([1, 2])
        assert [request[0] for request in harness.loader.requests] == [
            files[1]["path"],
            files[2]["path"],
        ]
    finally:
        harness.close()


def test_system_icon_loaded_during_scroll_is_used_after_resume_without_extra_request(qt_app):
    harness = FileSelectorFlowHarness(qt_app)
    try:
        files = harness.set_system_icon_files(["exe"])
        target_path = files[0]["path"]

        harness.render_rows([0])
        assert harness.loader.requests == [(target_path, 38)]

        harness.start_fast_scroll()
        harness.loader.complete(target_path, harness.make_pixmap(harness.loaded_color))

        assert harness.changed_rows == []

        harness.loader.clear_requests()
        harness.resume_scroll()
        pixmap = harness.render_rows([0])[0]

        assert harness.color_of(pixmap) == harness.loaded_color.name()
        assert harness.loader.requests == []
    finally:
        harness.close()


def test_failed_system_icon_load_uses_retry_backoff_between_repaints(qt_app):
    harness = FileSelectorFlowHarness(qt_app)
    try:
        files = harness.set_system_icon_files(["url"])
        target_path = files[0]["path"]
        clock_ms = [1000.0]
        harness.model._get_monotonic_time_ms = lambda: clock_ms[0]

        harness.render_rows([0])
        assert harness.loader.requests == [(target_path, 38)]

        harness.loader.complete(target_path, None)

        harness.render_rows([0])
        assert harness.loader.requests == [(target_path, 38)]

        clock_ms[0] += harness.model._SYSTEM_ICON_RETRY_DELAY_MS + 1
        harness.render_rows([0])
        assert harness.loader.requests == [(target_path, 38), (target_path, 38)]
    finally:
        harness.close()


def test_clear_caches_removes_system_icon_cache_and_retry_backoff(qt_app):
    harness = FileSelectorFlowHarness(qt_app)
    try:
        files = harness.set_system_icon_files(["lnk"])
        target_path = files[0]["path"]
        clock_ms = [2000.0]
        harness.model._get_monotonic_time_ms = lambda: clock_ms[0]

        harness.render_rows([0])
        harness.loader.complete(target_path, harness.make_pixmap(harness.loaded_color))
        harness.loader.clear_requests()

        harness.model.clear_caches(target_path)
        harness.render_rows([0])
        assert harness.loader.requests == [(target_path, 38)]

        harness.loader.complete(target_path, None)
        harness.loader.clear_requests()
        harness.model.clear_caches(target_path)
        harness.render_rows([0])
        assert harness.loader.requests == [(target_path, 38)]
    finally:
        harness.close()
