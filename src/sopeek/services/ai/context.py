"""Safe text file extraction for AI context."""
from __future__ import annotations

import base64
import csv
import io
import json
import mimetypes
from pathlib import Path
from typing import Iterable

from .models import FileContext

_TEXT_EXTS = {"txt", "md", "markdown", "rst", "log", "csv", "json", "jsonl", "py", "js", "ts", "tsx", "jsx", "html", "css", "xml", "yaml", "yml", "ini", "toml", "bat", "ps1", "c", "cpp", "h", "hpp", "java", "go", "rs"}
_IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp"}


class AIFileContextService:
    def __init__(self, max_file_bytes: int = 2_000_000, max_chars: int = 80_000, total_chars: int = 200_000) -> None:
        self.max_file_bytes = max_file_bytes
        self.max_chars = max_chars
        self.total_chars = total_chars

    def extract(self, paths: Iterable[str], include_paths: bool = False) -> list[FileContext]:
        result: list[FileContext] = []
        remaining = self.total_chars
        for raw in paths:
            if remaining <= 0: break
            path = Path(raw)
            try:
                if not path.is_file() or path.is_symlink(): raise ValueError("仅允许读取普通文件")
                if path.suffix.lower().lstrip(".") not in _TEXT_EXTS: raise ValueError("不支持的文本文件类型")
                if path.stat().st_size > self.max_file_bytes: raise ValueError("文件超过大小限制")
                data = path.read_bytes()
                text, encoding = self._decode(data)
                if path.suffix.lower() == ".json":
                    try: text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
                    except (ValueError, TypeError): pass
                if path.suffix.lower() == ".csv": text = self._format_csv(text)
                clipped = text[: min(self.max_chars, remaining)]
                result.append(FileContext(str(path) if include_paths else "", path.name, path.suffix.lower().lstrip("."), clipped, encoding, len(clipped) < len(text)))
                remaining -= len(clipped)
            except (OSError, ValueError, UnicodeError) as exc:
                result.append(FileContext("", path.name, path.suffix.lower().lstrip("."), "", "", error=str(exc)))
        return result

    def image_content_part(self, path: str, max_bytes: int = 32 * 1024 * 1024, detail: str = "auto") -> dict[str, object]:
        """Create a DeepSeek vision-compatible image_url content block."""
        file_path = Path(path)
        suffix = file_path.suffix.lower().lstrip(".")
        if not file_path.is_file() or file_path.is_symlink():
            raise ValueError("图像文件不可用")
        if suffix not in _IMAGE_EXTS:
            raise ValueError("仅支持 JPEG、PNG、GIF、WEBP 图像")
        raw = file_path.read_bytes()
        if len(raw) > max_bytes:
            raise ValueError("图像文件超过大小限制")
        mime = mimetypes.guess_type(file_path.name)[0] or "image/jpeg"
        encoded = base64.b64encode(raw).decode("ascii")
        if detail not in {"low", "high", "original", "auto"}: raise ValueError("detail 必须是 low、high、original 或 auto")
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}", "detail": detail}}

    def vision_message(self, prompt: str, image_paths: Iterable[str]) -> dict[str, object]:
        content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
        content.extend(self.image_content_part(path) for path in image_paths)
        return {"role": "user", "content": content}

    @staticmethod
    def _decode(data: bytes) -> tuple[str, str]:
        for encoding in ("utf-8-sig", "utf-16", "gb18030", "cp1252"):
            try: return data.decode(encoding), encoding
            except UnicodeDecodeError: continue
        return data.decode("utf-8", errors="replace"), "utf-8-replace"

    @staticmethod
    def _format_csv(text: str) -> str:
        rows = list(csv.reader(io.StringIO(text)))
        return "\n".join(" | ".join(row) for row in rows)


def render_file_context(contexts: Iterable[FileContext], extra: str = "") -> str:
    blocks: list[str] = []
    for item in contexts:
        if item.error: blocks.append(f"[文件 {item.name} 不可用: {item.error}]"); continue
        marker = "（内容已截断）" if item.truncated else ""
        blocks.append(f"[文件: {item.name}{marker}]\n{item.text}")
    if extra.strip(): blocks.append(f"[补充信息]\n{extra.strip()}")
    return "\n\n".join(blocks)


__all__ = ["AIFileContextService", "render_file_context"]
