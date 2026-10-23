"""Qt thread-pool bridge for AI Agent streaming."""
from __future__ import annotations

import threading
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .agent import AIAgentService
from .models import AIError, ChatMessage


class AIWorkerSignals(QObject):
    event = Signal(object)
    finished = Signal(object)
    failed = Signal(object)


class AIWorker(QRunnable):
    def __init__(self, agent: AIAgentService, messages: list[ChatMessage], **kwargs: Any) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.agent = agent
        self.messages = messages
        self.kwargs = kwargs
        self.signals = AIWorkerSignals()
        self.cancel_event = threading.Event()
        self.kwargs["cancel"] = self.cancel_event

    def start(self) -> None:
        QThreadPool.globalInstance().start(self)

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            for event in self.agent.stream(self.messages, **self.kwargs):
                self.signals.event.emit(event)
            self.signals.finished.emit(None)
        except AIError as exc:
            self.signals.failed.emit(exc)
        except Exception as exc:
            self.signals.failed.emit(AIError(str(exc)))


__all__ = ["AIWorker", "AIWorkerSignals"]
