"""
文件信息采集服务（纯逻辑层，不依赖任何 Qt 控件）

面向新界面「统一文件信息预览器」：
- 基础信息：stat / 轻量读头采集（图片、音频、视频、文本、压缩包、字体）
- 详细信息：按类型展开计算（含 EXIF 常用子集与全量标签）
- 哈希值：MD5 / SHA1 / SHA256 单次读盘并行计算
- 缓存：data/file_info_cache.json（与旧版同路径同名，内部结构全新，
  version=2，仅缓存详细信息 rows 与哈希；文件 mtime_ns/size 变动自动失效）

本模块不得导入 PySide6 / UI 组件，便于脱离界面做单元测试。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from freeassetfilter.core.native.bridges.media_probe import run_ffprobe_json
from freeassetfilter.utils.app_logger import debug, error

try:
    from mutagen import File as mutagen_file
except ImportError:  # pragma: no cover - 依赖缺失时的兜底
    mutagen_file = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover - 依赖缺失时的兜底
    Image = None

try:
    import chardet
except ImportError:  # pragma: no cover - 依赖缺失时的兜底
    chardet = None

try:
    import exifread
except ImportError:  # pragma: no cover - 依赖缺失时的兜底
    exifread = None

try:
    import magic
except ImportError:  # pragma: no cover - 依赖缺失时的兜底
    magic = None


# ---------------------------------------------------------------------------
# 常量与分组
# ---------------------------------------------------------------------------

CACHE_VERSION = 2
CACHE_FILE_NAME = "file_info_cache.json"
_DEFAULT_CACHE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / CACHE_FILE_NAME
)

# 表示「无法获取 / 无值」的通用占位
UNAVAILABLE = "-"

_IMAGE_EXTS = frozenset({
    "jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "webp",
    "avif", "heic", "heif", "ico",
})
_RAW_EXTS = frozenset({"cr2", "cr3", "nef", "arw", "dng", "orf"})
_SVG_EXTS = frozenset({"svg", "svgz"})
_VIDEO_EXTS = frozenset({
    "mp4", "m4v", "mov", "avi", "mkv", "wmv", "flv", "webm",
    "mpeg", "mpg", "mxf", "3gp", "ogv", "rmvb", "m2ts", "ts", "mts", "vob",
})
_AUDIO_EXTS = frozenset({
    "mp3", "wav", "flac", "ogg", "wma", "m4a", "aif", "aiff",
    "ape", "opus", "aac", "ac3", "mka",
})
_TEXT_EXTS = frozenset({
    "txt", "md", "markdown", "rst", "log", "csv",
    "py", "pyw", "java", "cpp", "cc", "cxx", "c", "h", "hpp", "cs",
    "js", "jsx", "ts", "tsx", "html", "htm", "css", "scss", "less",
    "php", "go", "rb", "swift", "kt", "kts", "yml", "yaml", "json",
    "xml", "toml", "ini", "cfg", "conf", "sh", "bat", "cmd", "ps1",
    "sql", "lua", "pl", "asm", "vue", "svelte",
})
_ARCHIVE_EXTS = frozenset({
    "zip", "rar", "tar", "gz", "tgz", "bz2", "xz", "7z",
    "iso", "cab", "arj", "lzh",
})
_FONT_EXTS = frozenset({"ttf", "otf", "woff", "woff2"})
_PDF_EXTS = frozenset({"pdf"})
_OFFICE_EXTS = frozenset({
    "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp",
})

_TEXT_EXT_COUNTS_THRESHOLD = 16 * 1024 * 1024  # 全量字数统计的字节上限

# EXIF 常用子集：短名 → 展示标签（RAW / JPEG / TIFF 等通用）
_EXIF_COMMON_LABELS: Dict[str, str] = {
    "Make": "相机厂商",
    "Model": "相机型号",
    "LensModel": "镜头型号",
    "DateTimeOriginal": "拍摄时间",
    "DateTime": "文件时间",
    "ExposureTime": "快门速度",
    "FNumber": "光圈值",
    "ExposureBiasValue": "曝光补偿",
    "ISOSpeedRatings": "ISO",
    "FocalLength": "焦距",
    "FocalLengthIn35mmFilm": "等效焦距",
    "WhiteBalance": "白平衡",
    "Flash": "闪光灯",
    "MeteringMode": "测光模式",
    "ExposureMode": "曝光模式",
    "ExposureProgram": "曝光程序",
    "SceneCaptureType": "场景类型",
    "Orientation": "方向",
    "Software": "处理软件",
    "ColorSpace": "色彩空间",
}

_EXIF_DROP_NAMES = frozenset({
    "jpegthumbnail", "thumbnailequipment", "thumbnailimagesize",
    "thumbnailoffset", "thumbnailbytes", "exifthumbnail", "makernote",
})

_FONT_NAME_ROWS: Tuple[Tuple[int, str], ...] = (
    (1, "字体名称"),
    (2, "字体样式"),
    (3, "唯一标识符"),
    (4, "全名"),
    (5, "版本"),
    (6, "PostScript 名称"),
)

# 归档魔数嗅探（zip/gzip/rar/7z/tar/iso），仅读文件头
_ARCHIVE_SIGNATURES = (
    (b"PK\x03\x04", "ZIP"),
    (b"PK\x05\x06", "ZIP"),
    (b"PK\x07\x08", "ZIP"),
    (b"\x1f\x8b", "GZIP"),
    (b"Rar!\x1a\x07", "RAR"),
    (b"7z\xbc\xaf\x27\x1c", "7Z"),
    (b"BZh", "BZIP2"),
    (b"\xfd7zXZ\x00", "XZ"),
    (b"\xed\xab\xee\xdb", "RPM"),
)

_CACHE_LOCK = threading.Lock()
_MAX_CACHE_ENTRIES = 800


# ---------------------------------------------------------------------------
# 路径与缓存
# ---------------------------------------------------------------------------

def _cache_key(path: str) -> str:
    """缓存键：规范化绝对路径（Windows 大小写不敏感）。"""
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def get_cache_path(cache_path: Optional[str] = None) -> Path:
    """解析缓存文件路径（测试可注入临时路径）。"""
    if cache_path:
        return Path(cache_path)
    return _DEFAULT_CACHE_PATH


def _read_store(cache_path: Optional[str] = None) -> Dict[str, Any]:
    """读取整份缓存仓库（失败返回空结构）。"""
    cache_file = get_cache_path(cache_path)
    try:
        if cache_file.exists():
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("version") == CACHE_VERSION:
                return data
    except (OSError, ValueError, TypeError):
        pass
    return {"version": CACHE_VERSION, "files": {}}


def _stat_fingerprint(path: str) -> Optional[Dict[str, Any]]:
    """文件指纹（mtime_ns + size），用于缓存失效判断。"""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return {"mtime_ns": st.st_mtime_ns, "size": st.st_size}


def read_cached(path: str, cache_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """读取有效缓存条目。

    返回结构：``{"details": [[label, value], ...], "hashes": {...}}``；
    条目缺失、结构不符或文件指纹变化时返回 None。
    """
    key = _cache_key(path)
    fingerprint = _stat_fingerprint(path)
    if fingerprint is None:
        return None
    store = _read_store(cache_path)
    entry = store.get("files", {}).get(key)
    if not isinstance(entry, dict):
        return None
    if entry.get("mtime_ns") != fingerprint["mtime_ns"] or entry.get("size") != fingerprint["size"]:
        return None
    return {
        "details": entry.get("details") or [],
        "hashes": entry.get("hashes") or {},
    }


def write_cached(
    path: str,
    *,
    details: Optional[List[Tuple[str, str]]] = None,
    hashes: Optional[Dict[str, str]] = None,
    cache_path: Optional[str] = None,
) -> None:
    """写入缓存条目（原子替换，后台线程调用）。"""
    fingerprint = _stat_fingerprint(path)
    if fingerprint is None:
        return
    key = _cache_key(path)
    with _CACHE_LOCK:
        store = _read_store(cache_path)
        entry = store.setdefault("files", {}).get(key)
        if not isinstance(entry, dict):
            entry = {}
            store["files"][key] = entry
        entry["mtime_ns"] = fingerprint["mtime_ns"]
        entry["size"] = fingerprint["size"]
        if details is not None:
            entry["details"] = list(details)
        if hashes is not None:
            entry["hashes"] = dict(hashes)
        files = store["files"]
        if len(files) > _MAX_CACHE_ENTRIES:
            for stale_key in list(files)[: len(files) - _MAX_CACHE_ENTRIES]:
                files.pop(stale_key, None)
        cache_file = get_cache_path(cache_path)
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = cache_file.with_suffix(".json.tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(store, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, cache_file)
        except OSError as exc:
            error(f"[file_info_service] 写入缓存失败: {exc}")


# ---------------------------------------------------------------------------
# 格式化工具
# ---------------------------------------------------------------------------

def format_size(size: int) -> str:
    """字节数 → 可读大小（负数返回占位符）。"""
    if size is None or size < 0:
        return UNAVAILABLE
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return UNAVAILABLE


def format_duration(seconds: float) -> str:
    """秒数 → MM:SS / HH:MM:SS。"""
    if seconds is None or seconds < 0:
        return UNAVAILABLE
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_bitrate(bitrate: int) -> str:
    """bps → 可读码率。"""
    if bitrate is None or bitrate < 0:
        return UNAVAILABLE
    if bitrate < 1000:
        return f"{bitrate} bps"
    if bitrate < 1000000:
        return f"{bitrate / 1000:.1f} Kbps"
    return f"{bitrate / 1000000:.1f} Mbps"


def _format_fps(fps: float) -> str:
    """帧率 → "60 fps" / "29.97 fps"。"""
    if fps is None or fps <= 0:
        return ""
    if abs(fps - round(fps)) < 1e-6:
        return f"{int(round(fps))} fps"
    return f"{fps:.2f} fps"


def _p_label(width: int, height: int) -> str:
    """高度命中常见档位时返回 1080p 这类标签，否则返回 W×H。"""
    _P_LABELS = {2160: "2160p", 1440: "1440p", 1080: "1080p", 720: "720p",
                 576: "576p", 480: "480p", 360: "360p"}
    if height in _P_LABELS:
        return _P_LABELS[height]
    return f"{width}×{height}"


def _join(*parts: Optional[str]) -> str:
    """用 · 连接非空片段（跳过占位符与空串）。"""
    cleaned = []
    for part in parts:
        text = str(part).strip() if part is not None else ""
        if text and text != UNAVAILABLE:
            cleaned.append(text)
    return " · ".join(cleaned) or UNAVAILABLE


# ---------------------------------------------------------------------------
# 类型分类
# ---------------------------------------------------------------------------

def classify_suffix(suffix: str) -> Tuple[str, str]:
    """后缀 → (展示分类名, 标准大写扩展名)。

    示例：png → ("图片", "PNG")；mp4 → ("视频", "MP4")；
    docx → ("Office 文档", "DOCX")；未知 → ("文件", "后缀大写或空")。
    """
    ext = (suffix or "").lstrip(".").lower()
    upper = ext.upper()
    if not ext:
        return "文件", ""
    if ext in _SVG_EXTS or ext in _IMAGE_EXTS or ext in _RAW_EXTS:
        return "图片", upper
    if ext in _VIDEO_EXTS:
        return "视频", upper
    if ext in _AUDIO_EXTS:
        return "音频", upper
    if ext in _PDF_EXTS:
        return "PDF 文档", upper
    if ext in _TEXT_EXTS:
        return "文本/代码", upper
    if ext in _ARCHIVE_EXTS:
        return "压缩包", upper
    if ext in _FONT_EXTS:
        return "字体", upper
    if ext in _OFFICE_EXTS:
        return "Office 文档", upper
    return "文件", upper


def is_image_suffix(suffix: str) -> bool:
    ext = (suffix or "").lstrip(".").lower()
    return ext in _SVG_EXTS or ext in _IMAGE_EXTS or ext in _RAW_EXTS


def is_svg_suffix(suffix: str) -> bool:
    return (suffix or "").lstrip(".").lower() in _SVG_EXTS


def is_video_suffix(suffix: str) -> bool:
    return (suffix or "").lstrip(".").lower() in _VIDEO_EXTS


def is_audio_suffix(suffix: str) -> bool:
    return (suffix or "").lstrip(".").lower() in _AUDIO_EXTS


def is_text_suffix(suffix: str) -> bool:
    return (suffix or "").lstrip(".").lower() in _TEXT_EXTS


def is_archive_suffix(suffix: str) -> bool:
    return (suffix or "").lstrip(".").lower() in _ARCHIVE_EXTS


def is_font_suffix(suffix: str) -> bool:
    return (suffix or "").lstrip(".").lower() in _FONT_EXTS


def _ext_of(path: str) -> str:
    return os.path.splitext(path)[1].lstrip(".").lower()


# ---------------------------------------------------------------------------
# 基础信息（stat）
# ---------------------------------------------------------------------------

def stat_basic(path: str) -> Dict[str, Any]:
    """os.stat 基础信息；失败时字段全部为占位符。

    返回键：name/path/size/size_str/modified/created（时间 "%Y-%m-%d %H:%M"）。
    """
    name = os.path.basename(path.rstrip("\\/"))
    base: Dict[str, Any] = {
        "name": name or path,
        "path": path,
        "size": UNAVAILABLE,
        "size_str": UNAVAILABLE,
        "modified": UNAVAILABLE,
        "created": UNAVAILABLE,
    }
    try:
        st = os.stat(path)
    except OSError:
        return base
    base["size"] = st.st_size
    base["size_str"] = format_size(st.st_size)
    base["modified"] = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
    base["created"] = datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M")
    return base


# ---------------------------------------------------------------------------
# 轻量读头：选中文件即展示的类型属性
# ---------------------------------------------------------------------------

def _svg_dimensions(path: str) -> Optional[str]:
    """从 SVG 头部解析 width/height 或 viewBox（仅读开头，超时安全）。"""
    try:
        with open(path, "rb") as f:
            head = f.read(16 * 1024)
        head_text = head.decode("utf-8", errors="ignore")
        width = re.search(r"width=[\"']([0-9.]+)(px)?[\"']", head_text, re.I)
        height = re.search(r"height=[\"']([0-9.]+)(px)?[\"']", head_text, re.I)
        if width and height:
            return f"{int(float(width.group(1)))} × {int(float(height.group(1)))}"
        view_box = re.search(
            r"viewBox=[\"']\s*(-?[0-9.]+)\s+(-?[0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s*[\"']",
            head_text, re.I,
        )
        if view_box:
            vw = float(view_box.group(3))
            vh = float(view_box.group(4))
            return f"{int(vw)} × {int(vh)}"
    except OSError:
        return None
    return None


def _image_light_rows(path: str, suffix: str) -> List[Tuple[str, str]]:
    """图片基础行：尺寸 + 格式（SVG 走头部解析）。"""
    rows: List[Tuple[str, str]] = []
    if is_svg_suffix(suffix):
        dims = _svg_dimensions(path)
        rows.append(("尺寸", dims or UNAVAILABLE))
        rows.append(("格式", "SVG"))
        return rows
    if Image is None:
        return []
    try:
        with Image.open(path) as img:
            width, height = img.size
            rows.append(("尺寸", f"{width} × {height}"))
            rows.append(("格式", str(img.format or UNAVAILABLE)))
    except (OSError, ValueError, AttributeError):
        rows.append(("尺寸", UNAVAILABLE))
        rows.append(("格式", UNAVAILABLE))
    return rows


def _detect_archive_format(path: str) -> str:
    """归档格式嗅探（魔数优先，回退扩展名）。"""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
        for signature, label in _ARCHIVE_SIGNATURES:
            if head.startswith(signature):
                return label
        if head.startswith(b"\x1f\x9d"):
            return "COMPRESS"
    except OSError:
        pass
    ext = _ext_of(path)
    return {
        "zip": "ZIP", "rar": "RAR", "7z": "7Z", "tar": "TAR",
        "gz": "GZIP", "tgz": "GZIP", "bz2": "BZIP2", "xz": "XZ",
        "iso": "ISO", "cab": "CAB", "arj": "ARJ", "lzh": "LZH",
    }.get(ext, UNAVAILABLE)


def _media_probe(path: str) -> Dict[str, Any]:
    """ffprobe 单次探测（含视频流/音频流/封装信息）。"""
    try:
        payload = run_ffprobe_json(path, show_format=True, show_streams=True) or {}
    except Exception as exc:  # noqa: BLE001
        debug(f"[file_info_service] ffprobe 探测失败: {exc}")
        return {}
    result: Dict[str, Any] = {}
    format_info = payload.get("format") or {}
    streams = payload.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    def _num(value: Any) -> Optional[float]:
        try:
            number = float(value)
            return number if number > 0 else None
        except (TypeError, ValueError):
            return None

    def _frac(value: Any) -> Optional[float]:
        if value in (None, "", "0/0", "N/A"):
            return None
        text = str(value).strip()
        if "/" in text:
            try:
                num_s, den_s = text.split("/", 1)
                num = float(num_s)
                den = float(den_s)
                if den != 0 and num > 0:
                    return num / den
                return None
            except ValueError:
                return None
        return _num(text)

    if video is not None:
        result["codec"] = str(video.get("codec_name") or "")
        result["profile"] = str(video.get("profile") or "")
        if video.get("width") and video.get("height"):
            result["width"] = int(video["width"])
            result["height"] = int(video["height"])
        fps = _frac(video.get("avg_frame_rate")) or _frac(video.get("r_frame_rate"))
        if fps:
            result["fps"] = fps
        video_bitrate = _num(video.get("bit_rate"))
        if video_bitrate:
            result["video_bitrate"] = video_bitrate
    if audio is not None:
        result["audio_codec"] = str(audio.get("codec_name") or "")
        channels = audio.get("channels")
        if channels:
            try:
                result["audio_channels"] = int(channels)
            except (TypeError, ValueError):
                pass
        sample_rate = _num(audio.get("sample_rate"))
        if sample_rate:
            result["audio_sample_rate"] = int(sample_rate)
        audio_bitrate = _num(audio.get("bit_rate"))
        if audio_bitrate:
            result["audio_bitrate"] = audio_bitrate
    duration = _num(format_info.get("duration"))
    if duration:
        result["duration_seconds"] = duration
    bitrate = _num(format_info.get("bit_rate"))
    if bitrate:
        result["format_bitrate"] = bitrate
    format_name = format_info.get("format_name")
    if format_name:
        result["format_name"] = str(format_name).split(",")[0]
    if not result:
        return {}
    return result


def _video_light_rows(probe: Dict[str, Any]) -> List[Tuple[str, str]]:
    """视频基础行：时长 + 画面信息（分辨率·帧率·码率合并一栏）。"""
    rows: List[Tuple[str, str]] = []
    duration = probe.get("duration_seconds")
    if duration:
        rows.append(("时长", format_duration(float(duration))))
    picture = UNAVAILABLE
    width, height, fps = probe.get("width"), probe.get("height"), probe.get("fps")
    if width and height:
        parts: List[str] = [_p_label(int(width), int(height))]
        fps_text = _format_fps(float(fps)) if fps else ""
        if fps_text:
            parts.append(fps_text)
        bitrate = probe.get("video_bitrate") or probe.get("format_bitrate")
        if bitrate:
            parts.append(format_bitrate(int(bitrate)))
        picture = " · ".join(parts)
    rows.append(("画面信息", picture))
    return rows


def _audio_light_rows(path: str) -> List[Tuple[str, str]]:
    """音频基础行：时长/比特率/声道数/采样率/编码格式（mutagen 头读）。"""
    rows: List[Tuple[str, str]] = []
    if mutagen_file is None:
        return rows
    try:
        audio = mutagen_file(path)
    except (OSError, ValueError):
        return rows
    if audio is None or not hasattr(audio, "info"):
        return rows
    audio_info = audio.info
    length = getattr(audio_info, "length", None)
    if length is not None and length > 0:
        rows.append(("时长", format_duration(float(length))))
    bitrate = getattr(audio_info, "bitrate", None)
    if bitrate is not None and bitrate > 0:
        rows.append(("比特率", format_bitrate(int(bitrate))))
    channels = getattr(audio_info, "channels", None)
    if channels is not None and channels > 0:
        rows.append(("声道数", str(int(channels))))
    sample_rate = getattr(audio_info, "sample_rate", None)
    if sample_rate is not None and sample_rate > 0:
        rows.append(("采样率", f"{int(sample_rate)} Hz"))
    mime = getattr(audio, "mime", None)
    if mime:
        rows.append(("编码格式", str(mime[0].split("/")[-1].upper())))
    return rows


def _text_light_rows(path: str) -> List[Tuple[str, str]]:
    """文本基础行：编码格式（chardet 采样前 1KB）。"""
    encoding = UNAVAILABLE
    if chardet is not None:
        try:
            with open(path, "rb") as f:
                sample = f.read(1024)
            detected = chardet.detect(sample)
            encoding = detected.get("encoding") or UNAVAILABLE
        except OSError:
            pass
    return [("编码格式", encoding)]


def _font_name_rows(path: str) -> List[Tuple[str, str]]:
    """字体基础行：name 表（字体名称/样式/全名/版本/PostScript 名…）。"""
    rows: List[Tuple[str, str]] = []
    try:
        from fontTools.ttLib import TTFont

        with TTFont(path, lazy=True) as font:
            name_table = font["name"]
            seen_values: set = set()
            for name_id, label in _FONT_NAME_ROWS:
                for record in name_table.names:
                    if record.nameID != name_id:
                        continue
                    try:
                        value = record.string.decode("utf-8")
                    except UnicodeDecodeError:
                        try:
                            value = record.string.decode("latin-1")
                        except (UnicodeDecodeError, AttributeError):
                            break
                    value = value.strip()
                    if not value:
                        continue
                    if value in seen_values:
                        break
                    seen_values.add(value)
                    rows.append((label, value))
                    break
    except (ImportError, OSError, KeyError, AttributeError):
        pass
    return rows


def collect_light_rows(file_info: Dict[str, Any]) -> List[Tuple[str, str]]:
    """按文件类型采集「选中即展示」的属性行。

    行序：类别 / 大小 / 修改时间 / 创建时间 + 类型附加行。
    「分类」与「格式」合并为「类别」：值 = 大写扩展名 + 分类值
    （如 PNG 图片、TXT 文本/代码、ZIP 压缩包）；图片类附加行中的
    「格式」行不再重复展示。
    目录与无法读取的文件仍返回类别等基础行，绝不抛异常。
    """
    path = str(file_info.get("path", ""))
    suffix = str(file_info.get("suffix", "")).lower()
    if file_info.get("is_dir"):
        return [("类别", "文件夹")]
    stat = stat_basic(path)
    category, upper_ext = classify_suffix(suffix)
    category_value = f"{upper_ext} {category}".strip() if upper_ext else category
    rows: List[Tuple[str, str]] = [("类别", category_value)]
    rows.append(("大小", stat["size_str"]))
    rows.append(("修改时间", stat["modified"]))
    rows.append(("创建时间", stat["created"]))
    if not os.path.isfile(path):
        return rows
    if is_image_suffix(suffix):
        rows.extend(_image_light_rows(path, suffix))
    elif is_audio_suffix(suffix):
        rows.extend(_audio_light_rows(path))
    elif is_video_suffix(suffix):
        rows.extend(_video_light_rows(_media_probe(path)))
    elif is_text_suffix(suffix):
        rows.extend(_text_light_rows(path))
    elif is_archive_suffix(suffix):
        rows.append(("压缩格式", _detect_archive_format(path)))
    elif is_font_suffix(suffix):
        rows.extend(_font_name_rows(path))
    # 已并入「类别」的图片“格式”行不再重复展示
    return [(label, value) for label, value in rows if label != "格式"]


# ---------------------------------------------------------------------------
# 详细信息（展开「详细信息」时计算；EXIF 不入缓存）
# ---------------------------------------------------------------------------

def _clean_exif_value(value: Any) -> Optional[str]:
    """EXIF 值转展示文本；二进制/超大值返回 None（跳过）。"""
    text = str(value).strip()
    if not text or text == "None":
        return None
    if text.startswith("["):  # 列表型（GPS 坐标组等）信息密度低，跳过
        return None
    if len(text) > 2000:
        return None
    text = re.sub(r"\s+", " ", text)
    return text


def _clean_exif_datetime(text: str) -> str:
    """EXIF 时间 "2026:09:05 10:11:12" → "2026-09-05 10:11:12"。"""
    match = re.match(r"^(\d{4}):(\d{2}):(\d{2})", text)
    if match:
        return text.replace(match.group(0), f"{match.group(1)}-{match.group(2)}-{match.group(3)}", 1)
    return text


def _collect_exif(path: str) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """提取 EXIF，返回 (常用子集行, 其余全量行)。

    常用子集按 ``_EXIF_COMMON_LABELS`` 过滤；其余按文件内出现顺序平铺
    （跳过缩略图/厂商私有等超大或二进制标签）。RAW 文件同样适用。
    """
    if exifread is None:
        return [], []
    import contextlib
    import io

    try:
        with open(path, "rb") as f:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                tags = exifread.process_file(f, details=False)
    except OSError:
        return [], []
    common: List[Tuple[str, str]] = []
    rest: List[Tuple[str, str]] = []
    seen: set = set()
    for tag_key, tag_value in tags.items():
        short = tag_key.split(":")[-1].strip()
        if not short:
            continue
        short_lower = short.lower()
        if short_lower in _EXIF_DROP_NAMES or short_lower.startswith("maker"):
            continue
        if short in seen:
            continue
        value = _clean_exif_value(tag_value)
        if value is None:
            continue
        seen.add(short)
        if short in _EXIF_COMMON_LABELS:
            common.append((_EXIF_COMMON_LABELS[short], _clean_exif_datetime(value)))
        else:
            rest.append((short, value))
    return common, rest


def _collect_audio_tags(path: str) -> List[Tuple[str, str]]:
    """音频文本标签（标题/艺术家/专辑…）；无标签或格式不支持时为空。"""
    if mutagen_file is None:
        return []
    try:
        audio = mutagen_file(path)
    except (OSError, ValueError):
        return []
    if audio is None:
        return []
    tags = getattr(audio, "tags", None)
    if tags is None:
        return []

    key_sets = (
        ("title", "标题"),
        ("artist", "艺术家"),
        ("album", "专辑"),
        ("date", "年份"),
        ("genre", "流派"),
        ("tracknumber", "音轨号"),
    )
    id3_names = {
        "TIT2": "标题", "TPE1": "艺术家", "TALB": "专辑",
        "TDRC": "年份", "TCON": "流派", "TRCK": "音轨号",
    }
    mp4_names = {
        "\xa9nam": "标题", "\xa9ART": "艺术家", "\xa9alb": "专辑",
        "\xa9day": "年份", "\xa9gen": "流派", "trkn": "音轨号",
    }

    def _get_text(*candidates: str) -> Optional[str]:
        for key in candidates:
            item = tags.get(key)
            if item is None:
                continue
            values: List[str] = []
            for sub in (item if isinstance(item, (list, tuple)) else [item]):
                text = None
                text_attr = getattr(sub, "text", None)
                if isinstance(text_attr, (list, tuple)):
                    texts = [str(t) for t in text_attr]
                    text = "、".join(t for t in texts if t)
                elif text_attr is not None:
                    text = str(text_attr)
                else:
                    text = str(sub)
                if text:
                    values.append(text)
            if values:
                return "、".join(values)
        return None

    module_name = type(audio).__module__.lower()
    mapping: Dict[str, str] = dict(key_sets)
    if "id3" in module_name or "mp3" in module_name:
        mapping = {**id3_names, **mapping}
    if "mp4" in module_name or "m4a" in module_name:
        mapping = {**mp4_names, **mapping}
    rows: List[Tuple[str, str]] = []
    for key, label in mapping.items():
        value = _get_text(key)
        if value:
            rows.append((label, value))
    return rows


def _text_detail_rows(path: str) -> List[Tuple[str, str]]:
    """文本详情：字数/行数/单词数（超限文件跳过）+ MIME 探测。"""
    rows: List[Tuple[str, str]] = []
    encoding = "utf-8"
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    if size <= _TEXT_EXT_COUNTS_THRESHOLD:
        try:
            with open(path, "rb") as f:
                raw = f.read()
            if chardet is not None:
                detected = chardet.detect(raw[:4096]) or {}
                if detected.get("encoding"):
                    encoding = detected["encoding"]
            content: Optional[str] = None
            for candidate in (encoding, "utf-8", "latin-1"):
                try:
                    content = raw.decode(candidate)
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            if content is not None:
                rows.append(("字符数", str(len(content))))
                rows.append(("字符数(不含空格)", str(len(content.replace(" ", "")))))
                rows.append(("行数", str(content.count("\n") + 1)))
                rows.append(("单词数", str(len(content.split()))))
        except OSError:
            pass
    if magic is not None:
        try:
            rows.append(("MIME 类型", magic.Magic(mime=True).from_file(path)))
        except Exception:  # noqa: BLE001
            pass
    return rows


def _archive_detail_rows(path: str) -> List[Tuple[str, str]]:
    """压缩包详情：内部文件数 / 解压总大小 / 压缩率（7z 目录扫描）。"""
    rows: List[Tuple[str, str]] = []
    try:
        from freeassetfilter.core.native.bridges.py7z_core import list_archive

        entries = list_archive(path, encoding="utf-8")
        file_entries = [entry for entry in entries if not entry.get("is_dir")]
        if not entries:
            return rows
        total_size = sum(int(entry.get("size") or 0) for entry in file_entries)
        archive_size = os.path.getsize(path)
        rows.append(("内部文件数", str(len(file_entries))))
        if total_size > 0:
            rows.append(("解压总大小", format_size(total_size)))
            ratio = (1 - archive_size / total_size) * 100
            rows.append(("压缩率", f"{ratio:.2f}%"))
        else:
            rows.append(("解压总大小", UNAVAILABLE))
    except Exception as exc:  # noqa: BLE001
        debug(f"[file_info_service] 压缩包详情失败: {exc}")
    return rows


def _video_detail_rows(probe: Dict[str, Any]) -> List[Tuple[str, str]]:
    """视频详情：视频编解码器 / 音频流信息。"""
    rows: List[Tuple[str, str]] = []
    codec = probe.get("codec")
    if codec:
        profile = probe.get("profile")
        value = codec.upper()
        if profile:
            value = f"{value} ({profile})"
        rows.append(("视频编解码器", value))
    audio_codec = probe.get("audio_codec")
    if audio_codec:
        parts = [audio_codec.upper()]
        channels = probe.get("audio_channels")
        if channels:
            parts.append(f"{channels} 声道")
        sample_rate = probe.get("audio_sample_rate")
        if sample_rate:
            parts.append(f"{sample_rate} Hz")
        audio_bitrate = probe.get("audio_bitrate")
        if audio_bitrate:
            parts.append(format_bitrate(int(audio_bitrate)))
        rows.append(("音频流", _join(*parts)))
    return rows


def _font_detail_rows(path: str) -> List[Tuple[str, str]]:
    """字体详情：格式 / 字形数 / 上升·下降·行距。"""
    rows: List[Tuple[str, str]] = []
    try:
        from fontTools.ttLib import TTFont

        with TTFont(path, lazy=True) as font:
            font_format = "TrueType"
            if "CFF " in font:
                font_format = "OpenType/CFF"
            rows.append(("字体格式", font_format))
            rows.append(("字形数", str(len(font.getGlyphOrder()))))
            if "hhea" in font:
                hhea = font["hhea"]
                rows.append(("上升", str(hhea.ascent)))
                rows.append(("下降", str(hhea.descent)))
                rows.append(("行间距", str(hhea.lineGap)))
    except (ImportError, OSError, KeyError, AttributeError):
        pass
    return rows


def _image_detail_rows(path: str) -> List[Tuple[str, str]]:
    """图片详情：色彩模式 / 位深（SVG 无位图属性则跳过）。"""
    if Image is None:
        return []
    rows: List[Tuple[str, str]] = []
    bits_map = {"1": 1, "L": 8, "P": 8, "RGB": 24, "RGBA": 32, "CMYK": 32, "I": 32}
    try:
        with Image.open(path) as img:
            mode = str(img.mode or "")
            if mode:
                rows.append(("色彩模式", mode))
            depth = img.info.get("bits", 0) if isinstance(img.info, dict) else 0
            if not depth:
                depth = bits_map.get(mode, 0)
            if depth:
                rows.append(("位深", f"{int(depth)} bit"))
    except (OSError, ValueError, AttributeError):
        pass
    return rows


def _pdf_detail_rows() -> List[Tuple[str, str]]:
    """PDF：页数已由 PDF 预览器展示，此处不再提供额外字段。"""
    return []


def collect_detail_data(path: str) -> Dict[str, Any]:
    """按类型采集全部详细信息（调用方在后台线程执行）。

    返回：{"rows": [[label,value]...], "exif_common": [...], "exif_more": [...]}
    """
    result: Dict[str, Any] = {"rows": [], "exif_common": [], "exif_more": []}
    if not os.path.isfile(path):
        return result
    suffix = _ext_of(path)
    if is_image_suffix(suffix):
        if not is_svg_suffix(suffix):
            result["rows"] = _image_detail_rows(path)
        common, rest = _collect_exif(path)
        result["exif_common"] = common
        result["exif_more"] = rest
    elif is_audio_suffix(suffix):
        result["rows"] = _collect_audio_tags(path)
    elif is_video_suffix(suffix):
        result["rows"] = _video_detail_rows(_media_probe(path))
    elif is_text_suffix(suffix):
        result["rows"] = _text_detail_rows(path)
    elif is_archive_suffix(suffix):
        result["rows"] = _archive_detail_rows(path)
    elif is_font_suffix(suffix):
        result["rows"] = _font_detail_rows(path)
    elif suffix in _PDF_EXTS:
        result["rows"] = _pdf_detail_rows()
    return result


# ---------------------------------------------------------------------------
# 哈希值
# ---------------------------------------------------------------------------

def compute_hashes(
    path: str,
    progress: Optional[Callable[[int], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Dict[str, str]:
    """单次读盘并行计算 MD5/SHA1/SHA256；失败项为占位符。

    Args:
        path: 目标文件路径。
        progress: 可选回调（已读字节比例 0-100 的整数），在工作线程执行。
        should_stop: 可选取消回调（每块读取前探测）；取消后返回部分值，
            调用方应丢弃结果（结果未写缓存）。
    """
    md5 = hashlib.md5()  # noqa: S324 - 兼容需求字段展示
    sha1 = hashlib.sha1()  # noqa: S324
    sha256 = hashlib.sha256()
    total = 0
    try:
        total = os.path.getsize(path)
        with open(path, "rb") as f:
            read_bytes = 0
            while True:
                if should_stop is not None and should_stop():
                    break
                chunk = f.read(1024 * 256)
                if not chunk:
                    break
                md5.update(chunk)
                sha1.update(chunk)
                sha256.update(chunk)
                read_bytes += len(chunk)
                if progress is not None and total > 0 and read_bytes % (1024 * 1024) == 0:
                    progress(int(read_bytes * 100 / total))
    except OSError:
        return {"MD5": UNAVAILABLE, "SHA1": UNAVAILABLE, "SHA256": UNAVAILABLE}
    if progress is not None:
        progress(100)
    return {"MD5": md5.hexdigest(), "SHA1": sha1.hexdigest(), "SHA256": sha256.hexdigest()}
