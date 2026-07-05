# -*- coding: utf-8 -*-

from freeassetfilter.components.update_controller import UpdateController


class _FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)


class _FakeWorker:
    def __init__(self, running=True):
        self._running = running
        self.interruption_requested = False
        self.wait_called = False
        self.finished = _FakeSignal()

    def isRunning(self):
        return self._running

    def requestInterruption(self):
        self.interruption_requested = True

    def wait(self, *args, **kwargs):
        self.wait_called = True
        raise AssertionError("UpdateController should not block waiting for a check worker")


def test_manual_click_promotes_running_silent_check_without_wait(qt_app, monkeypatch):
    controller = UpdateController(None)
    silent_worker = _FakeWorker(running=True)
    controller._silent_check_worker = silent_worker

    shown = []
    monkeypatch.setattr(controller, "_show_check_progress_dialog", lambda: shown.append(True))

    controller.on_check_updates_clicked()

    assert shown == [True]
    assert controller._manual_check_uses_silent is True
    assert controller._silent_check_worker is silent_worker
    assert silent_worker.interruption_requested is False
    assert silent_worker.wait_called is False


def test_cancel_promoted_silent_check_returns_immediately(qt_app, monkeypatch):
    controller = UpdateController(None)
    silent_worker = _FakeWorker(running=True)
    controller._silent_check_worker = silent_worker
    controller._manual_check_uses_silent = True

    closed = []
    monkeypatch.setattr(controller, "_close_current_dialog", lambda: closed.append(True))

    controller._on_check_dialog_clicked(0)

    assert closed == [True]
    assert controller._silent_check_worker is None
    assert controller._manual_check_uses_silent is False
    assert silent_worker.interruption_requested is True
    assert silent_worker.wait_called is False
    assert silent_worker in controller._retired_silent_workers


def test_cancel_manual_check_returns_immediately(qt_app, monkeypatch):
    controller = UpdateController(None)
    check_worker = _FakeWorker(running=True)
    controller._check_worker = check_worker

    closed = []
    monkeypatch.setattr(controller, "_close_current_dialog", lambda: closed.append(True))

    controller._on_check_dialog_clicked(0)

    assert closed == [True]
    assert controller._check_worker is None
    assert check_worker.interruption_requested is True
    assert check_worker.wait_called is False
    assert check_worker in controller._retired_check_workers


def test_promoted_silent_success_uses_manual_result_display(qt_app, monkeypatch):
    controller = UpdateController(None)
    controller._manual_check_uses_silent = True

    displayed = []
    result = {"update_available": False}
    monkeypatch.setattr(controller, "_show_check_result", lambda value: displayed.append(value))

    controller._on_silent_check_success(result)

    assert displayed == [result]
    assert controller._manual_check_uses_silent is False
    assert controller._silent_check_claimed_by_manual is True
