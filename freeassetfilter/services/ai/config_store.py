"""Encrypted multi-account AI configuration store (Windows DPAPI)."""
from __future__ import annotations

import base64
import ctypes
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from freeassetfilter.utils.path_utils import get_app_data_path
from .models import AIAccountConfig, AIConfigError, AIProvider


class AIConfigStore:
    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or get_app_data_path()) / "ai_accounts.json"

    @staticmethod
    def _protect(value: str) -> str:
        if os.name != "nt": raise AIConfigError("DPAPI 仅支持 Windows")
        crypt = ctypes.windll.crypt32
        class B(ctypes.Structure): _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]
        raw = value.encode("utf-8"); buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw); inp = B(len(raw), buf); out = B()
        if not crypt.CryptProtectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)): raise AIConfigError("DPAPI 加密失败")
        try: return base64.b64encode(ctypes.string_at(out.pbData, out.cbData)).decode("ascii")
        finally: ctypes.windll.kernel32.LocalFree(out.pbData)

    @staticmethod
    def _unprotect(value: str) -> str:
        if os.name != "nt": raise AIConfigError("DPAPI 仅支持 Windows")
        crypt = ctypes.windll.crypt32
        class B(ctypes.Structure): _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]
        raw = base64.b64decode(value); buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw); inp = B(len(raw), buf); out = B()
        if not crypt.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)): raise AIConfigError("DPAPI 解密失败")
        try: return ctypes.string_at(out.pbData, out.cbData).decode("utf-8")
        finally: ctypes.windll.kernel32.LocalFree(out.pbData)

    def load(self) -> dict[str, Any]:
        if not self.path.exists(): return {"version": 1, "current": "", "accounts": []}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8")); return value if isinstance(value, dict) else {}
        except (OSError, ValueError) as exc: raise AIConfigError("AI 配置损坏") from exc

    def save(self, accounts: list[AIAccountConfig], current: str = "") -> None:
        payload = {"version": 1, "current": current, "accounts": []}
        for account in accounts:
            item = {"account_id": account.account_id, "name": account.name, "provider": account.provider.value, "base_url": account.base_url, "model": account.model, "api_key": self._protect(account.api_key), "temperature": account.temperature, "max_tokens": account.max_tokens, "timeout": account.timeout, "headers": dict(account.headers), "reasoning_enabled": account.reasoning_enabled, "reasoning_effort": account.reasoning_effort, "reasoning_budget": account.reasoning_budget, "top_p": account.top_p, "response_format": account.response_format, "tool_choice": account.tool_choice, "user": account.user, "prefix": account.prefix, "strict_tools": account.strict_tools}
            payload["accounts"].append(item)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix="ai_accounts_", suffix=".tmp", dir=str(self.path.parent)); os.close(fd)
        try: Path(temp).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"); os.replace(temp, self.path)
        finally:
            if os.path.exists(temp): os.unlink(temp)

    def accounts(self) -> list[AIAccountConfig]:
        result = []
        for item in self.load().get("accounts", []):
            try: result.append(AIAccountConfig(item["account_id"], item["name"], AIProvider(item["provider"]), item["base_url"], item["model"], self._unprotect(item["api_key"]), item.get("temperature"), int(item.get("max_tokens", 4096)), float(item.get("timeout", 90)), item.get("headers", {}), item.get("reasoning_enabled"), item.get("reasoning_effort"), item.get("reasoning_budget"), item.get("top_p"), item.get("response_format"), item.get("tool_choice"), item.get("user"), item.get("prefix", False), item.get("strict_tools", False)))
            except (KeyError, ValueError, TypeError, AIConfigError) as exc: raise AIConfigError("AI 账号配置无效") from exc
        return result


__all__ = ["AIConfigStore"]
