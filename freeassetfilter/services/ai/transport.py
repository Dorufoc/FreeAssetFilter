"""AI HTTP transport and model discovery."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any, Iterable

from .models import AIAccountConfig, AICancelledError, AIHTTPError, AITimeoutError


class HTTPTransport:
    def __init__(self, account: AIAccountConfig) -> None:
        self.account = account

    def post_stream(self, url: str, headers: dict[str, str], body: bytes, cancel: threading.Event | None = None) -> Iterable[bytes]:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            response = urllib.request.urlopen(request, timeout=self.account.timeout)
            while True:
                if cancel is not None and cancel.is_set():
                    response.close()
                    raise AICancelledError("AI 请求已取消")
                chunk = response.read(4096)
                if not chunk:
                    break
                yield chunk
            response.close()
        except urllib.error.HTTPError as exc:
            payload = exc.read(2048).decode("utf-8", errors="replace")
            raise AIHTTPError(exc.code, payload) from exc
        except TimeoutError as exc:
            raise AITimeoutError("AI 请求超时") from exc
        except urllib.error.URLError as exc:
            raise AITimeoutError(str(exc.reason)) from exc

    def get_json(self, url: str, headers: dict[str, str]) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=self.account.timeout) as response:
                value = json.loads(response.read(2_000_000).decode("utf-8"))
                return value if isinstance(value, dict) else {}
        except urllib.error.HTTPError as exc:
            raise AIHTTPError(exc.code, exc.read(2048).decode("utf-8", errors="replace")) from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            raise AITimeoutError(str(exc)) from exc


__all__ = ["HTTPTransport"]
