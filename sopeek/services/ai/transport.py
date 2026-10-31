"""AI HTTP transport and model discovery."""
from __future__ import annotations

import json
import mimetypes
import os
import threading
import uuid
import urllib.error
import urllib.parse
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

    def request_json(self, method: str, url: str, headers: dict[str, str], body: bytes | None = None) -> dict[str, Any]:
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.account.timeout) as response:
                value = json.loads(response.read(2_000_000).decode("utf-8"))
                return value if isinstance(value, dict) else {}
        except urllib.error.HTTPError as exc:
            raise AIHTTPError(exc.code, exc.read(4096).decode("utf-8", errors="replace")) from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            raise AITimeoutError(str(exc)) from exc

    def upload_file(self, path: str, purpose: str = "user_data") -> dict[str, Any]:
        file_path = os.path.abspath(path)
        if not os.path.isfile(file_path): raise ValueError("文件不存在")
        if os.path.getsize(file_path) > 64 * 1024 * 1024: raise ValueError("DeepSeek Files API 单文件上限为 64 MiB")
        boundary = uuid.uuid4().hex
        filename = os.path.basename(file_path)
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        chunks = [
            f"--{boundary}\\r\\nContent-Disposition: form-data; name=\"purpose\"\\r\\n\\r\\n{purpose}\\r\\n".encode(),
            f"--{boundary}\\r\\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\\r\\nContent-Type: {mime}\\r\\n\\r\\n".encode(),
            open(file_path, "rb").read(), f"\\r\\n--{boundary}--\\r\\n".encode(),
        ]
        return self.request_json("POST", self.account.base_url.rstrip("/") + "/files", {"Authorization": f"Bearer {self.account.api_key}", "Content-Type": f"multipart/form-data; boundary={boundary}"}, b"".join(chunks))

    def list_files(self) -> dict[str, Any]:
        return self.request_json("GET", self.account.base_url.rstrip("/") + "/files", {"Authorization": f"Bearer {self.account.api_key}"})

    def get_file(self, file_id: str) -> dict[str, Any]:
        return self.request_json("GET", self.account.base_url.rstrip("/") + "/files/" + urllib.parse.quote(file_id, safe=""), {"Authorization": f"Bearer {self.account.api_key}"})

    def delete_file(self, file_id: str) -> dict[str, Any]:
        return self.request_json("DELETE", self.account.base_url.rstrip("/") + "/files/" + urllib.parse.quote(file_id, safe=""), {"Authorization": f"Bearer {self.account.api_key}"})

    def get_balance(self) -> dict[str, Any]:
        return self.request_json("GET", self.account.base_url.rstrip("/") + "/user/balance", {"Authorization": f"Bearer {self.account.api_key}"})


__all__ = ["HTTPTransport"]
